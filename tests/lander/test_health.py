"""health.py: main's own record of its blocking checks, the lane's plan trimmed by it, judge() taking it for a base
run, and the e2e set a lander, manifest or sandbox change selects. Every case builds its own state, manifest and git
answers; nothing reaches the box. Run:
python3 -m unittest discover -s core/tests/lander -t core/tests/lander -p 'test_health.py'
"""
import datetime
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from lander import cards as C  # noqa: E402
from lander import health as HL  # noqa: E402
from lander import manifest as M  # noqa: E402
from lander import nightly as NG  # noqa: E402
from lander import plan as P  # noqa: E402
from lander import run as RUN  # noqa: E402
from lander import tick as TK  # noqa: E402
from lander import tip as TP  # noqa: E402
from lander import types as T  # noqa: E402

TIP1, TIP2, TIP3 = "1" * 40, "2" * 40, "3" * 40
PARENT = {TIP1: "0" * 40, TIP2: TIP1, TIP3: TIP2}
TEXT = """
[[check]]
name = "app"
run = "tests/app.sh"
paths = ["app/**"]
class = "static"
[[check]]
name = "lib"
run = "tests/lib.sh"
paths = ["lib/**"]
class = "static"
[[check]]
name = "e2e-flow"
run = "tests/e2e/flow.sh"
paths = ["bin/flow"]
class = "host"
[[check]]
name = "boxy"
run = "tests/boxy.sh"
paths = ["app/**"]
class = "box"
"""


def manifest():
    checks, faults = M.parse_checks(TEXT, "", "t")
    assert not faults, faults
    return M.Manifest(checks={c.name: c for c in checks}, cwd={c.name: "" for c in checks},
                      policy=T.Policy(lander=["lander/**"]))


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.files = {}          # tip -> the files git diff names for the range ending there
        self.said = []
        for target, name, fn in ((C, "sh", self.git),
                                 (C, "say", lambda pid, argv, repo, pr: self.said.append(argv[-1])),
                                 (TP, "origin_tip", lambda root, base: self.tip),
                                 (M, "load", lambda *a, **k: manifest()),
                                 (RUN, "tree_of", lambda root, rev: "t" + rev[:5]),
                                 (NG, "trim", lambda repo, m, plan: plan)):
            p = mock.patch.object(target, name, fn)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {"CC_LAND_STATE": self.tmp, "CC_LANDER_STATE": self.tmp})
        p.start()
        self.addCleanup(p.stop)

    def git(self, argv, cwd=None, timeout=None, env=None):
        sub = argv[1:]
        if sub[:1] == ["rev-parse"]:
            return 0, PARENT[sub[-1][:-2]] + "\n"
        if sub[:1] == ["diff"]:
            return 0, "\0".join(self.files.get(sub[-1], [])) + "\0"
        if sub[:1] == ["log"]:
            return 0, f"change at {sub[-1][:4]} (#7)\n"
        return 1, ""

    def go(self, tip, files, red=()):
        """One health pass on `tip`, whose range changed `files`; checks in `red` fail on the tip. -> (ran, asked)"""
        self.tip, self.files[tip], asked = tip, list(files), []

        def check(name, sha):
            asked.append((name, sha))
            st = T.FAILED if name in red and sha == tip else T.PASSED
            return T.Result(check=name, tree=sha, status=st)
        return HL.run("demo", check), asked


class Run(Case):
    def test_only_the_blocking_checks_the_range_reaches_run_and_a_box_check_is_left_to_the_tip_run(self):
        ran, asked = self.go(TIP1, ["app/x.py"])
        self.assertEqual(ran, {"app": T.PASSED})              # not lib (untouched), not boxy (the tip run's)
        self.assertEqual(asked, [("app", TIP1)])
        self.assertEqual(HL.load("demo")["tip"], TIP1)
        self.assertEqual(HL.at("demo", "t" + TIP1[:5]), {"app": T.PASSED})
        self.assertEqual(self.go(TIP1, ["app/x.py"])[0], {})  # a tip already checked runs nothing again
        self.assertEqual(self.said, [])

    def test_a_check_turning_red_alerts_once_naming_the_merge_and_code_when_its_parent_passes(self):
        self.go(TIP1, ["app/x.py"])
        ran, asked = self.go(TIP2, ["app/y.py"], red={"app"})
        self.assertEqual(ran, {"app": T.FAILED})
        self.assertIn(("app", TIP1), asked, "the merge's parent is asked")
        e = HL.red("demo")["app"]
        self.assertEqual((e["since"], e["cause"]), (TIP2, "code"))
        self.assertEqual(len(self.said), 1)
        self.assertIn("app went red on main", self.said[0])
        self.assertIn("PR #7 broke it", self.said[0])
        # still red on the next tip, whose range does not touch app: it runs again (red is always re-run), with no
        # second alert, and keeps since and cause
        ran, _ = self.go(TIP3, ["lib/z.py"], red={"app"})
        self.assertEqual(ran, {"app": T.FAILED, "lib": T.PASSED})
        self.assertEqual(len(self.said), 1)
        self.assertEqual(HL.red("demo")["app"]["since"], TIP2)

    def test_a_red_the_parent_shares_is_said_as_the_machine(self):
        self.tip, self.files[TIP2] = TIP2, ["app/y.py"]
        HL.run("demo", lambda n, s: T.Result(check=n, tree=s, status=T.FAILED))
        self.assertEqual(HL.red("demo")["app"]["cause"], "machine")
        self.assertIn("the box changed, not the code", self.said[0])

    def test_red_turns_green_and_leaves_the_red_list(self):
        self.go(TIP1, ["app/x.py"], red={"app"})
        self.assertIn("app", HL.red("demo"))
        ran, _ = self.go(TIP2, ["lib/z.py"])
        self.assertEqual(ran["app"], T.PASSED)
        self.assertEqual(HL.red("demo"), {})
        self.assertNotIn("since", HL.load("demo")["checks"]["app"])

    def test_an_unrunnable_result_is_not_recorded(self):
        self.tip, self.files[TIP1] = TIP1, ["app/x.py"]
        self.assertEqual(HL.run("demo", lambda n, s: T.Result(check=n, tree=s, status=T.UNRUNNABLE)), {})
        self.assertEqual(HL.load("demo")["checks"], {})
        self.assertEqual(self.said, [])

    def test_a_killed_pass_keeps_its_finished_results_and_the_next_pass_picks_up_from_there(self):
        self.go(TIP1, ["app/x.py"])
        self.tip, self.files[TIP2] = TIP2, ["app/y.py", "lib/z.py"]

        def killed(name, sha):
            if name == "lib":
                raise KeyboardInterrupt("killed")
            return T.Result(check=name, tree=sha, status=T.PASSED)
        with self.assertRaises(KeyboardInterrupt):
            HL.run("demo", killed)
        rec = HL.load("demo")
        self.assertEqual(rec["checks"]["app"]["tip"], TIP2, "app finished before the kill: it is on disk")
        self.assertEqual((rec["tip"], rec["running"]), (TIP1, TIP2), "the pass is not marked done")
        self.assertTrue(HL.pending("demo"))
        ran, asked = self.go(TIP2, ["app/y.py", "lib/z.py"])
        self.assertEqual(asked, [("lib", TIP2)], "only the check the killed pass had not reached runs")
        self.assertEqual(ran, {"lib": T.PASSED})
        rec = HL.load("demo")
        self.assertEqual((rec["tip"], rec["running"]), (TIP2, ""))
        self.assertFalse(HL.pending("demo"))

    def test_a_killed_pass_on_an_older_tip_is_not_taken_for_the_new_tip(self):
        self.go(TIP1, ["app/x.py"])
        self.tip, self.files[TIP2] = TIP2, ["app/y.py"]
        with self.assertRaises(KeyboardInterrupt):
            HL.run("demo", lambda n, s: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.files[TIP3] = ["app/y.py", "lib/z.py"]
        ran, asked = self.go(TIP3, ["app/y.py", "lib/z.py"])
        self.assertEqual(ran, {"app": T.PASSED, "lib": T.PASSED}, "every check the range reaches runs on the new tip")

    def test_a_lander_change_runs_the_e2e_set(self):
        ran, _ = self.go(TIP1, ["core/lander/tip.py"])
        self.assertIn("e2e-flow", ran)
        ran, _ = self.go(TIP2, ["lib/z.py"])
        self.assertNotIn("e2e-flow", ran)


class Trim(Case):
    def plan(self):
        return T.Plan(checks=["app", "lib"], klass=T.LEAF)

    def test_a_check_red_on_main_leaves_a_plan_that_touches_none_of_its_paths(self):
        self.go(TIP1, ["app/x.py"], red={"app"})
        p = HL.trim("demo", manifest(), self.plan(), ["lib/z.py"])
        self.assertEqual((p.checks, p.extra["main_red"]), (["lib"], ["app"]))

    def test_a_plan_that_touches_the_red_checks_paths_keeps_it(self):
        # brief: "unless the PR touches that check's owned paths"
        self.go(TIP1, ["app/x.py"], red={"app"})
        p = HL.trim("demo", manifest(), self.plan(), ["app/x.py"])
        self.assertEqual(p.checks, ["app", "lib"])
        self.assertNotIn("main_red", p.extra)

    def test_no_record_keeps_every_check(self):
        p = HL.trim("demo", manifest(), self.plan(), ["lib/z.py"])
        self.assertEqual(p.checks, ["app", "lib"])

    def test_at_is_only_the_exact_tree(self):
        self.go(TIP1, ["app/x.py"], red={"app"})
        self.assertEqual(HL.at("demo", "t" + TIP1[:5]), {"app": T.FAILED})
        self.assertEqual(HL.at("demo", "tother"), {})
        self.assertEqual(HL.at("demo", ""), {})

    def test_at_trusts_a_record_only_while_it_is_fresh(self):
        # architect read, 10-13: a stale green must not skip the base run when the box broke the check since
        self.go(TIP1, ["app/x.py"])
        tree = "t" + TIP1[:5]
        stamp = HL.load("demo")["checks"]["app"]["at"]
        t = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        self.assertEqual(HL.at("demo", tree, now=t + datetime.timedelta(seconds=HL.FRESH - 60)), {"app": T.PASSED})
        self.assertEqual(HL.at("demo", tree, now=t + datetime.timedelta(seconds=HL.FRESH)), {})
        rec = HL.load("demo")
        rec["checks"]["app"]["at"] = "not a stamp"
        C.write_json(HL.path("demo"), rec)
        self.assertEqual(HL.at("demo", tree), {})


class Judge(unittest.TestCase):
    def setUp(self):
        self.c = manifest().checks["app"]
        self.trees = []

    def runner(self, red):
        def run(check, tree, where, alone=False, **kw):
            self.trees.append(tree)
            return T.Result(check=check.name, tree=tree, status=T.FAILED if tree in red else T.PASSED)
        return run

    def test_main_red_on_the_base_blocks_without_a_base_run(self):
        o = RUN.judge(self.c, "head", "base", runner=self.runner({"head", "base"}), main=T.FAILED, touched=True)
        self.assertEqual(o.status, RUN.BLOCKED)
        self.assertEqual(self.trees, ["head"])

    def test_main_red_still_runs_the_base_where_the_ratchet_may_pass_it(self):
        # the ratchet needs a base run made now, so a red record does not stand in for it
        o = RUN.judge(self.c, "head", "base", runner=self.runner({"head", "base"}), main=T.FAILED)
        self.assertIn("base", self.trees)
        self.assertNotEqual(o.status, T.FAILED)

    def test_main_green_on_the_base_makes_a_red_the_prs_without_a_base_run(self):
        o = RUN.judge(self.c, "head", "base", runner=self.runner({"head", "base"}), main=T.PASSED)
        self.assertEqual(o.status, T.FAILED)
        self.assertNotIn("base", self.trees)

    def test_a_pr_that_turns_a_main_red_check_green_passes(self):
        o = RUN.judge(self.c, "head", "base", runner=self.runner({"base"}), main=T.FAILED)
        self.assertEqual(o.status, T.PASSED)

    def test_no_record_runs_the_base_as_before(self):
        o = RUN.judge(self.c, "head", "base", runner=self.runner({"head", "base"}))
        self.assertEqual(o.status, RUN.BLOCKED)
        self.assertIn("base", self.trees)


class Tick(Case):
    def tick(self, health, st="green", tipran=None):
        tip, deploy = types.ModuleType("tip"), types.ModuleType("deploy")
        tip.run = lambda repo, plan, check: (tipran.append(repo) if tipran is not None else None) or st
        tip.catchup = lambda repo: False
        deploy.run = lambda repo: None
        settled = []
        with mock.patch.object(HL, "run", health), \
                mock.patch.object(TK, "settle", lambda repo: settled.append(repo) or []), \
                mock.patch.object(TK, "due_catchup", lambda repo: False), \
                mock.patch.object(TK.MF, "host_fallback", lambda repo: ""), \
                mock.patch.object(TK.D, "root_of", lambda repo: self.tmp), \
                mock.patch.object(TK.L, "paused", lambda repo: False), \
                mock.patch.object(TK.E, "log", lambda *a, **k: None):
            lines = TK.tip_and_deploy("demo", {"tip": tip, "deploy": deploy})
        return lines, settled

    def test_a_main_health_fault_still_settles_the_repos_jobs(self):
        def boom(*a, **k):
            raise RuntimeError("no tree")
        lines, settled = self.tick(boom)
        self.assertEqual(settled, ["demo"])
        self.assertTrue(any("main health failed" in x for x in lines), lines)

    def test_a_main_health_run_that_works_settles_and_says_nothing_failed(self):
        lines, settled = self.tick(lambda *a, **k: {"app": T.PASSED})
        self.assertEqual(settled, ["demo"])
        self.assertFalse(any("failed" in x for x in lines), lines)

    def test_a_tip_run_starts_while_main_health_is_mid_run(self):
        inner, tipran = {}, []

        def health(*a, **k):   # mid-run: the next merge's tick comes in
            with TP.lock("demo") as got:
                inner["tip lock free"] = got
            inner["lines"], _ = self.tick(lambda *a, **k: self.fail("a second health pass ran"), tipran=tipran)
            return {"app": T.PASSED}
        lines, settled = self.tick(health)
        self.assertTrue(inner["tip lock free"], "main health holds the tip lock")
        self.assertEqual(tipran, ["demo"], "the second tick's tip run did not start")
        self.assertNotIn("[demo] a tip run is already going", inner["lines"])
        self.assertIn("[demo] main health is already running", inner["lines"])
        self.assertTrue(HL.pending("demo"), "the skipped tick asks for one more pass")
        self.assertIn("[demo] main health: 1 check(s)", lines)

    def test_an_owed_pass_runs_on_an_idle_tip_and_none_runs_when_nothing_is_owed(self):
        ran = []
        self.tick(lambda *a, **k: ran.append(1) or {}, st="idle")
        self.assertEqual(ran, [], "an idle tip with nothing owed runs no health pass")
        HL.want("demo")
        self.tick(lambda *a, **k: ran.append(1) or {}, st="idle")
        self.assertEqual(ran, [1], "an owed pass runs though the tip was idle")


class E2E(unittest.TestCase):
    def test_lander_manifest_and_sandbox_changes_select_every_e2e_check(self):
        for f in ("core/lander/tip.py", "tests/LANDING.toml", "core/tests/LANDING-policy.toml", "core/bin/cc-sandbox",
                  "bin/cc-fence", "config/etc/claude-bwrap", "core/config/etc/claude-bwrap-path.json"):
            p = P.select(manifest(), [f])
            self.assertIn("e2e-flow", p.checks, f)
            self.assertEqual(p.extra["e2e"], f)

    def test_any_other_change_selects_e2e_only_by_its_paths(self):
        self.assertNotIn("e2e-flow", P.select(manifest(), ["app/x.py"]).checks)
        self.assertIn("e2e-flow", P.select(manifest(), ["bin/flow"]).checks)
        self.assertNotIn("e2e", P.select(manifest(), ["app/x.py"]).extra)


if __name__ == "__main__":
    unittest.main()
