"""nightly.py through the real lane: checking()'s reuse of a pass the job's own store holds on the same merge tree,
Lane.nightly on a plan, and file_row's one row against a fake cc-board. The lane cases reuse test_lane's hermetic Fixture (fake gh, bare origin, every state path in a tmp dir). Run:
python3 -m unittest discover -s core/tests/lander -t core/tests/lander -p 'test_nightly_lane.py'
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", ".."))

import test_lane as TL  # noqa: E402
from lander import cards as C  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import lane as L  # noqa: E402
from lander import manifest as MF  # noqa: E402
from lander import nightly as NG  # noqa: E402
from lander import records as REC  # noqa: E402
from lander import types as T  # noqa: E402

setUpModule, tearDownModule = TL.setUpModule, TL.tearDownModule

TEXT = "".join(f'[[check]]\nname = "{n}"\nrun = "tests/{n}.sh"\npaths = ["{p}"]\nclass = "static"\n'
               for n, p in (("a", "a/**"), ("b", "b/**"), ("quiet", "app/**"), ("new", "a/**")))


def manifest():
    checks, faults = MF.parse_checks(TEXT, "", "t")
    assert not faults, faults
    return MF.Manifest(checks={c.name: c for c in checks}, cwd={c.name: "" for c in checks}, policy=T.Policy())


def rec(*names):
    """A record in which each of `names` ran MIN_RUNS times, never red, in a log reaching back past the window."""
    return {"first": 1, "runs": {n: NG.MIN_RUNS for n in names}, "pr_reds": {}, "nightly_reds": {},
            "secs": {}, "prs": set()}


class Case(TL.Fixture):
    def setUp(self):
        super().setUp()
        NG._cache.clear()
        self.addCleanup(NG._cache.clear)

    def moving(self, *names):
        """NG.record answers rec(*names) and every manifest load answers manifest(), for the rest of the case."""
        for p in (mock.patch.object(NG, "record", lambda repo, now=None, days=7: rec(*names)),
                  mock.patch.object(MF, "load", lambda *a, **k: manifest())):
            p.start()
            self.addCleanup(p.stop)


class Reuse(Case):
    def store(self, head, status=T.PASSED, release=None, checks=("a",)):
        """A result of each check in the store of job demo-1 on the merge of main and head; -> that tree."""
        tree = self.git(self.tmp, "--git-dir", self.origin, "merge-tree", "--write-tree", "main", head).splitlines()[0]
        s = REC.Store("demo", root=J.landq())
        for n in checks:
            r = T.Result(check=n, tree=tree, status=status, release=release or REC.release())
            REC._write(s.job_path("demo-1", n, tree), r.to_dict())
        return tree

    def test_a_stored_pass_on_the_same_tree_is_not_run_again_and_the_rest_runs(self):
        tree = self.store(self.pr(1, {"a/x": "n\n", "b/y": "n\n"}))
        J.submit("demo", 1)
        u, _ = self.land()
        self.assertEqual([c[0] for c in u["runner"].calls], ["b"])
        j = self.job()
        self.assertEqual(j.results.get("a"), f"a/{tree}")
        self.assertIn("b", j.results)
        self.assertEqual(j.state, T.DEPLOY_PENDING)
        self.assertIn(f"stage demo#1 reused gate=a tree={tree[:12]}", self.log())
        self.assertNotIn("reused gate=b", self.log())

    def test_every_check_reused_moves_the_job_on_with_no_run(self):
        tree = self.store(self.pr(1, {"a/x": "n\n", "b/y": "n\n"}), checks=("a", "b"))
        J.submit("demo", 1)
        u, _ = self.land()
        self.assertEqual(u["runner"].calls, [])
        j = self.job()
        self.assertEqual(j.results, {"a": f"a/{tree}", "b": f"b/{tree}"})
        self.assertIn("mergeable", [h["state"] for h in j.history])
        self.assertEqual(j.state, T.DEPLOY_PENDING)
        for n in ("a", "b"):
            self.assertIn(f"stage demo#1 reused gate={n} tree={tree[:12]}", self.log())

    def test_a_stored_red_runs_again(self):
        self.store(self.pr(1, {"a/x": "n\n", "b/y": "n\n"}), status=T.FAILED)
        J.submit("demo", 1)
        u, _ = self.land()
        self.assertEqual(sorted(c[0] for c in u["runner"].calls), ["a", "b"])
        self.assertNotIn("reused", self.log())

    def test_a_pass_from_another_release_runs_again(self):
        self.store(self.pr(1, {"a/x": "n\n", "b/y": "n\n"}), release="older-release")
        J.submit("demo", 1)
        u, _ = self.land()
        self.assertEqual(sorted(c[0] for c in u["runner"].calls), ["a", "b"])
        self.assertNotIn("reused", self.log())


class LaneNightly(Case):
    def plan(self):
        return T.Plan(checks=["a", "quiet"], klass=T.LEAF)

    def test_a_lane_drops_the_moved_check_and_names_it(self):
        self.moving("quiet")
        p = L.Lane("demo", self.units()).nightly("HEAD", self.plan())
        self.assertEqual((p.checks, p.extra.get("nightly")), (["a"], ["quiet"]))

    def test_a_members_lane_keeps_every_check(self):
        os.makedirs(f"{self.home}/dev/alice/.cc")
        open(f"{self.home}/dev/alice/.cc/member-workspace", "w").close()
        self.moving("quiet")
        lane = L.Lane("alice--proj", self.units())
        self.assertEqual(lane.member, "alice")
        p = lane.nightly("HEAD", self.plan())
        self.assertEqual((p.checks, p.extra.get("nightly")), (["a", "quiet"], None))

    def test_a_manifest_that_does_not_load_keeps_every_check(self):
        self.moving("quiet")

        def broken(*a, **k):
            raise MF.ManifestError("no parse")
        with mock.patch.object(MF, "load", broken):
            p = L.Lane("demo", self.units()).nightly("HEAD", self.plan())
        self.assertEqual((p.checks, p.extra.get("nightly")), (["a", "quiet"], None))


class Planning(Case):
    def test_the_planning_stage_leaves_a_moved_check_to_nightly(self):
        # lane.py's `job.plan = self.nightly(...)` after the planner: `quiet` owns a/ too, yet only `a` runs
        self.moving("quiet")
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        u, _ = self.land(planner=TL.Planner(owners={"a": "a/", "quiet": "a/"}))
        self.assertEqual([c[0] for c in u["runner"].calls], ["a"])


class StoreRelease(Case):
    def test_put_stamps_the_stores_release(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "lanes"))
        lock = open(os.path.join(root, "lanes", "demo.lock"), "a")
        self.addCleanup(lock.close)
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX)
        s = REC.Store("demo", lock, root)
        s.release = "rel-x"
        s.put("demo-1", T.Result(check="a", tree="t" * 40, status=T.PASSED, release="other"))
        self.assertEqual(s.get("demo-1", "a", "t" * 40).release, s.release)


FAKE_BOARD = r'''#!PYTHON -SI
import os, sys
rows = os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "rows.txt")
a = sys.argv[1:]
have = open(rows).read().splitlines() if os.path.exists(rows) else []
if a[0] == "add":
    open(rows, "a").write(a[1] + " " + a[2] + "\n")
    sys.exit(0)
if a[0] == "get" and a[3:] == ["status"] and a[1] + " " + a[2] in have:
    print("todo")
    sys.exit(0)
sys.exit(1)
'''


class FileRow(unittest.TestCase):
    def setUp(self):
        self.bin = tempfile.mkdtemp(prefix="lander-nightly-board.")
        self.addCleanup(shutil.rmtree, self.bin, True)
        p = os.path.join(self.bin, "cc-board")
        with open(p, "w") as f:
            f.write(FAKE_BOARD.replace("PYTHON", sys.executable, 1))
        os.chmod(p, 0o755)
        patch = mock.patch.object(C, "BIN", self.bin)
        patch.start()
        self.addCleanup(patch.stop)

    def test_one_row_not_one_per_tick(self):
        first = NG.file_row("demo", "quiet", "a" * 40, "boom")
        second = NG.file_row("demo", "quiet", "b" * 40, "boom again")
        self.assertEqual(first, "board row nightly-red-quiet filed")
        self.assertEqual(second, "board row nightly-red-quiet is already there")
        with open(os.path.join(self.bin, "rows.txt")) as f:
            self.assertEqual(f.read().splitlines(), ["demo nightly-red-quiet"])


if __name__ == "__main__":
    unittest.main()
