"""health.py: main's own record of its blocking checks, judge() taking it for a base run, and the e2e set a lander,
manifest or sandbox change selects. Every case builds its own state, manifest and git answers; nothing reaches the
box. Run:
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

import calm_host  # noqa: E402,F401  (pins load and pressure; before any lander import)
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
        self.assertEqual(HL.at("demo", "t" + TIP1[:5]), {})   # a green is never taken (10-25)
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

    def test_a_check_main_retires_leaves_the_red_list_and_one_it_keeps_stays(self):
        self.go(TIP1, ["app/x.py", "lib/x.py"], red={"app", "lib"})
        self.assertEqual(set(HL.red("demo")), {"app", "lib"})
        m = manifest()
        del m.checks["app"], m.cwd["app"]
        with mock.patch.object(M, "load", lambda *a, **k: m):
            self.go(TIP2, ["app/y.py"], red={"lib"})
        self.assertEqual(set(HL.red("demo")), {"lib"})      # app retired: gone; lib still in main: still red
        self.assertNotIn("app", HL.load("demo")["checks"])

    def test_a_tip_manifest_that_reads_empty_prunes_nothing(self):
        self.go(TIP1, ["app/x.py"], red={"app"})
        with mock.patch.object(M, "load", lambda *a, **k: M.Manifest(checks={}, cwd={}, policy=T.Policy())):
            self.go(TIP2, ["app/y.py"])
        self.assertIn("app", HL.red("demo"))

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

    def test_a_pass_that_never_finishes_on_one_tip_stops_being_owed_after_tries(self):
        self.go(TIP1, ["app/x.py"])
        self.tip, self.files[TIP2] = TIP2, ["app/y.py"]
        asked = []

        def broken(name, sha):
            asked.append(name)
            raise RuntimeError("no tree")
        for _ in range(HL.TRIES):
            with self.assertRaises(RuntimeError):
                HL.run("demo", broken)
            self.assertTrue(HL.pending("demo"))
        self.assertEqual(HL.run("demo", broken), {})
        self.assertEqual(len(asked), HL.TRIES, "the pass after TRIES runs nothing")
        rec = HL.load("demo")
        self.assertEqual((rec["tip"], rec["running"]), (TIP1, ""))
        self.assertFalse(HL.pending("demo"))
        self.assertEqual(self.go(TIP2, ["app/y.py"])[0], {}, "a later tick on the same tip runs nothing")

    def give_up(self, tip, broken):
        """TRIES passes on `tip` that raise from `broken`, then the one that gives up. -> the (id, argv) said"""
        said = []
        self.tip, self.files[tip] = tip, ["app/y.py"]
        with mock.patch.object(C, "say", lambda pid, argv, repo, pr: said.append((pid, argv))):
            for _ in range(HL.TRIES):
                with self.assertRaises(RuntimeError):
                    HL.run("demo", broken)
            self.assertEqual(said, [], "no card while a pass is still owed")
            self.assertEqual(HL.run("demo", broken), {})
        return said

    def test_a_pass_that_raises_before_any_check_still_counts_its_tries(self):
        self.go(TIP1, ["app/x.py"])

        def early(*a, **k):
            raise RuntimeError("manifest unreadable")
        with mock.patch.object(M, "load", early):
            said = self.give_up(TIP2, lambda n, s: T.Result(check=n, tree=s, status=T.PASSED))
        rec = HL.load("demo")
        self.assertEqual((rec["running"], rec["tries"], rec["gave_up"]), ("", [TIP2, HL.TRIES + 1], TIP2))
        self.assertFalse(HL.pending("demo"), "a pass that fails early is not owed for good")
        self.assertEqual(len(said), 1)

    def test_a_tip_given_up_on_is_stamped_and_later_ticks_on_it_are_quiet(self):
        self.go(TIP1, ["app/x.py"])
        said = self.give_up(TIP2, lambda n, s: (_ for _ in ()).throw(RuntimeError("no tree")))
        logged = []
        with mock.patch.object(C, "log", lambda *a, **k: logged.append(a)), \
                mock.patch.object(C, "say", lambda *a, **k: self.fail("a second card on the same tip")):
            for _ in range(3):
                self.assertEqual(HL.run("demo", lambda n, s: self.fail("ran a check on a given-up tip")), {})
        self.assertEqual(logged, [], "no gave-up line every tick")
        rec = HL.load("demo")
        self.assertEqual((rec["tip"], rec["gave_up"], rec["tries"]), (TIP1, TIP2, [TIP2, HL.TRIES + 1]))
        self.assertEqual(len(said), 1)
        diffs = []
        git = self.git
        with mock.patch.object(C, "sh", lambda argv, **k: (diffs.append(argv[1:]) if argv[1:2] == ["diff"] else None,
                                                           git(argv, **k))[1]):
            self.go(TIP3, ["lib/z.py"])
        self.assertEqual([d[-2:] for d in diffs], [[TIP1, TIP3]],
                         "the next tip's range still reaches back over the given-up one: 'tip' did not move")

    def test_giving_up_sends_one_card_naming_the_tip(self):
        self.go(TIP1, ["app/x.py"])
        said = self.give_up(TIP2, lambda n, s: (_ for _ in ()).throw(RuntimeError("no tree")))
        self.assertEqual(len(said), 1)
        pid, argv = said[0]
        self.assertEqual(pid, f"land:demo:main-health-gave-up@{TIP2[:12]}")
        self.assertEqual(argv[argv.index("--id") + 1], pid, "cc-slack's --id dedups it too")
        self.assertIn(TIP2[:12], argv[-1])
        self.assertIn("gave up", argv[-1])

    def test_a_card_send_that_raises_leaves_the_tip_unstamped_and_the_next_tick_sends_it(self):
        self.go(TIP1, ["app/x.py"])
        self.tip, self.files[TIP2] = TIP2, ["app/y.py"]
        broken = lambda n, s: (_ for _ in ()).throw(RuntimeError("no tree"))  # noqa: E731
        for _ in range(HL.TRIES):
            with self.assertRaises(RuntimeError):
                HL.run("demo", broken)

        def down(*a, **k):
            raise OSError("slack down")
        with mock.patch.object(C, "say", down):
            with self.assertRaises(OSError):
                HL.run("demo", broken)
        self.assertEqual(HL.load("demo")["gave_up"], "", "no stamp for a card that never went out")
        # Opus read of #1527: the tick only calls run again while pending() holds, and run already took the want
        self.assertTrue(HL.pending("demo"), "a card that never went out keeps the tip owed")
        said = []
        with mock.patch.object(C, "say", lambda pid, argv, repo, pr: said.append(pid)):
            self.assertEqual(HL.run("demo", lambda n, s: self.fail("ran a check on a given-up tip")), {})
            self.assertEqual(HL.run("demo", lambda n, s: self.fail("ran a check on a given-up tip")), {})
        self.assertEqual(said, [f"land:demo:main-health-gave-up@{TIP2[:12]}"], "the next tick sends it, once")
        self.assertEqual(HL.load("demo")["gave_up"], TIP2)

    def test_a_pass_that_finds_main_moved_stops_and_the_next_runs_on_the_newest_tip(self):
        """10-27: a pass on 5fadc4da ran three hours past five newer merges, and its stale red held PRs main-red."""
        # the red is lib, which sorts after app by name, so only the reds-first order puts it first
        self.go(TIP1, ["lib/x.py"], red={"lib"})
        self.tip, self.files[TIP2], asked = TIP2, ["lib/z.py", "app/y.py"], []

        def check(name, sha):
            asked.append((name, sha))
            self.tip = TIP3   # main moves while the first check runs
            return T.Result(check=name, tree=sha, status=T.FAILED if name == "lib" else T.PASSED)
        self.assertEqual(HL.run("demo", check), {"lib": T.FAILED})
        self.assertEqual(asked, [("lib", TIP2)], "main's red runs first, and nothing more runs on the old tip")
        rec = HL.load("demo")
        self.assertEqual((rec["tip"], rec["running"]), (TIP1, TIP2), "the range stays owed")
        self.assertTrue(HL.pending("demo"))
        self.assertEqual(len(self.said), 1, "still red: no second alert")
        ran, asked = self.go(TIP3, ["lib/z.py", "app/y.py"])
        self.assertEqual(ran, {"app": T.PASSED, "lib": T.PASSED})
        self.assertEqual(asked, [("lib", TIP3), ("app", TIP3)])
        self.assertEqual(HL.red("demo"), {}, "the newer tip cleared the red")
        self.assertEqual((HL.load("demo")["tip"], HL.load("demo")["running"]), (TIP3, ""))
        self.assertFalse(HL.pending("demo"))

    def test_a_job_held_main_red_is_tried_now_once_the_newer_tip_passes_the_check(self):
        from lander import jobs as J
        later = "2099" + C.now()[4:]   # a hold that would not end for decades
        for pr, n in ((7, "app"), (8, "lib")):
            J.save(T.Job(repo="demo", pr=pr, state=T.HELD, stage=T.HELD,
                         extra={"hold": "box", "not_before": later, "main_red": {"check": n}}))
        self.go(TIP1, ["app/x.py"], red={"app", "lib"})
        self.tip, self.files[TIP2] = TIP2, ["app/y.py"]

        def check(name, sha):
            return T.Result(check=name, tree=sha, status=T.FAILED if name == "lib" else T.PASSED)
        with mock.patch.object(TK, "make_check", lambda root, fallback="": check), \
                mock.patch.object(TK.D, "root_of", lambda repo: self.tmp):
            lines = TK.main_health("demo", True, "")
        self.assertIn("[demo] PR #7: main passes app again, so its main-red hold is tried now", lines)
        self.assertFalse(any("PR #8" in x for x in lines), "lib is still red on main")
        with mock.patch.object(TK.J, "lane_jobs", lambda repo: []), \
                mock.patch.object(TK.C, "left_held", lambda repo: False):
            self.assertEqual(TK.waits("demo"), [TK.TICK_SECS], "the request wants the next tick")
        self.assertEqual(J.drain("demo"), ["demo#7 again"])
        self.assertEqual(J.not_before_left(J.load("demo", 7)), 0)
        self.assertGreater(J.not_before_left(J.load("demo", 8)), 0)

    def test_an_ask_from_main_health_frees_only_a_main_red_hold_whose_check_main_passes(self):
        """Perms' read of #2012: who is inbox-writable, so who=main-health alone frees no hold."""
        from lander import jobs as J
        later = "2099" + C.now()[4:]
        self.go(TIP1, ["app/x.py", "lib/x.py"], red={"app"})
        for pr, red in ((7, {"check": "app"}), (8, None), (9, {"check": "lib"}), (10, "lib")):
            J.save(T.Job(repo="demo", pr=pr, state=T.HELD, stage=T.HELD,
                         extra={"hold": "box", "not_before": later, **({"main_red": red} if red else {})}))
            J.submit("demo", pr, who="main-health")
        J.drain("demo")
        self.assertGreater(J.not_before_left(J.load("demo", 7)), 0, "main still fails app")
        self.assertGreater(J.not_before_left(J.load("demo", 8)), 0, "no main-red record")
        self.assertEqual(J.not_before_left(J.load("demo", 9)), 0, "main passes lib")
        self.assertGreater(J.not_before_left(J.load("demo", 10)), 0, "a main-red record that is no dict frees nothing")

    def test_a_bad_moved_count_reads_as_none(self):
        """Perms' read of #2019: a hand-edited or torn record must not crash the pass."""
        for bad in ("x", [1], None):
            C.write_json(HL.path("demo"), {"moved": bad})
            self.assertEqual(HL.load("demo")["moved"], 0, repr(bad))

    def test_an_empty_tip_read_is_not_main_moving(self):
        self.go(TIP1, ["app/x.py"])
        self.tip, self.files[TIP2], asked = TIP2, ["app/y.py", "lib/y.py"], []

        def check(name, sha):
            asked.append(name)
            self.tip = ""   # origin could not be read
            return T.Result(check=name, tree=sha, status=T.PASSED)
        self.assertEqual(HL.run("demo", check), {"app": T.PASSED, "lib": T.PASSED})
        self.assertEqual((HL.load("demo")["tip"], HL.load("demo")["running"]), (TIP2, ""))

    def test_a_main_that_moves_on_every_pass_gets_a_whole_record_after_tries(self):
        tips = [str(d) * 40 for d in range(4, 5 + HL.TRIES)]
        p = mock.patch.dict(PARENT, zip(tips, [TIP1] + tips))
        p.start()
        self.addCleanup(p.stop)
        self.go(TIP1, ["app/x.py"])
        log = mock.patch.object(C, "log").start()
        self.addCleanup(mock.patch.stopall)
        for k, t in enumerate(tips):
            self.tip, self.files[t] = t, ["app/y.py", "lib/y.py"]

            def check(name, sha, nxt=(tips + [""])[k + 1]):
                self.tip = nxt or self.tip + "x"   # main moves while every check runs
                return T.Result(check=name, tree=sha, status=T.PASSED)
            ran = HL.run("demo", check)
            self.assertEqual(len(ran), 1 if k < HL.TRIES else 2, f"pass {k}")
        rec = HL.load("demo")
        self.assertEqual((rec["tip"], rec["running"], rec["moved"]), (tips[-1], "", 0))
        self.assertFalse(HL.pending("demo"))
        # Opus read of #2019: the pass that finishes anyway says so, once
        self.assertEqual([c.args[2] for c in log.call_args_list if c.args[:1] == ("main-health",)].count("finish"), 1)

    def test_a_lander_change_runs_the_e2e_set(self):
        ran, _ = self.go(TIP1, ["core/lander/tip.py"])
        self.assertIn("e2e-flow", ran)
        ran, _ = self.go(TIP2, ["lib/z.py"])
        self.assertNotIn("e2e-flow", ran)


class At(Case):
    def test_at_is_only_the_exact_tree(self):
        self.go(TIP1, ["app/x.py"], red={"app"})
        self.assertEqual(HL.at("demo", "t" + TIP1[:5]), {"app": T.FAILED})
        self.assertEqual(HL.at("demo", "tother"), {})
        self.assertEqual(HL.at("demo", ""), {})

    def test_at_trusts_a_record_only_while_it_is_fresh(self):
        # architect read, 10-13: a stale red must not stand for a base run when the box fixed the check since
        self.go(TIP1, ["app/x.py"], red={"app"})
        tree = "t" + TIP1[:5]
        stamp = HL.load("demo")["checks"]["app"]["at"]
        t = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        self.assertEqual(HL.at("demo", tree, now=t + datetime.timedelta(seconds=HL.FRESH - 60)), {"app": T.FAILED})
        self.assertEqual(HL.at("demo", tree, now=t + datetime.timedelta(seconds=HL.FRESH)), {})
        rec = HL.load("demo")
        rec["checks"]["app"]["at"] = "not a stamp"
        C.write_json(HL.path("demo"), rec)
        self.assertEqual(HL.at("demo", tree), {})

    def test_red_holds_a_check_only_while_its_record_is_fresh(self):
        # read of #1309: a stale red must not put a PR first, as a stale green skips no base run
        self.go(TIP1, ["app/x.py"], red={"app"})
        stamp = HL.load("demo")["checks"]["app"]["at"]
        t = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        self.assertEqual(set(HL.red("demo", now=t + datetime.timedelta(seconds=HL.FRESH - 60))), {"app"})
        self.assertEqual(HL.red("demo", now=t + datetime.timedelta(seconds=HL.FRESH)), {})
        rec = HL.load("demo")
        rec["checks"]["app"]["at"] = "not a stamp"
        C.write_json(HL.path("demo"), rec)
        self.assertEqual(HL.red("demo"), {})


class Judge(unittest.TestCase):
    def setUp(self):
        self.c = manifest().checks["app"]
        self.trees = []

    def runner(self, red):
        def run(check, tree, where, alone=False, **kw):
            self.trees.append(tree)
            return T.Result(check=check.name, tree=tree, status=T.FAILED if tree in red else T.PASSED)
        return run

    def test_main_red_on_the_base_blocks_a_security_check_without_a_base_run(self):
        o = RUN.judge(self.c, "head", "base", runner=self.runner({"head", "base"}), main=T.FAILED, security=True)
        self.assertEqual(o.status, RUN.BLOCKED)
        self.assertEqual(self.trees, ["head"])

    def test_main_red_runs_the_base_for_a_touched_check(self):
        # a fix to one of main's reds may pass the ratchet now, which needs a base run made now
        RUN.judge(self.c, "head", "base", runner=self.runner({"head", "base"}), main=T.FAILED, touched=True)
        self.assertIn("base", self.trees)

    def test_main_red_still_runs_the_base_where_the_ratchet_may_pass_it(self):
        # the ratchet needs a base run made now, so a red record does not stand in for it
        o = RUN.judge(self.c, "head", "base", runner=self.runner({"head", "base"}), main=T.FAILED)
        self.assertIn("base", self.trees)
        self.assertNotEqual(o.status, T.FAILED)

    def test_a_red_main_showed_now_holds_as_main_red_though_its_record_is_green(self):
        # 10-25: main's green from 09:46 handed dispatch #1478 back at 10:48 for a red main's own runs had that hour
        o = RUN.judge(self.c, "head", "base", runner=self.runner({"head", "base"}), main=T.PASSED, touched=True)
        self.assertEqual(o.status, RUN.BLOCKED)
        self.assertIn("base", self.trees)

    def test_a_red_main_does_not_show_now_is_the_prs(self):
        o = RUN.judge(self.c, "head", "base", runner=self.runner({"head"}), main=T.PASSED, touched=True)
        self.assertEqual(o.status, T.FAILED)
        self.assertIn("base", self.trees)

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


    def test_an_owed_pass_runs_when_the_tip_run_raised(self):
        HL.want("demo")
        tip, deploy = types.ModuleType("tip"), types.ModuleType("deploy")
        tip.run = lambda repo, plan, check: (_ for _ in ()).throw(RuntimeError("tip broke"))
        tip.catchup = lambda repo: False
        deploy.run = lambda repo: None
        ran = []
        with mock.patch.object(HL, "run", lambda *a, **k: ran.append(1) or {"app": T.PASSED}), \
                mock.patch.object(TK, "settle", lambda repo: []), \
                mock.patch.object(TK, "due_catchup", lambda repo: False), \
                mock.patch.object(TK.MF, "host_fallback", lambda repo: ""), \
                mock.patch.object(TK.D, "root_of", lambda repo: self.tmp), \
                mock.patch.object(TK.L, "paused", lambda repo: False), \
                mock.patch.object(TK.E, "log", lambda *a, **k: None):
            lines = TK.tip_and_deploy("demo", {"tip": tip, "deploy": deploy})
        self.assertEqual(ran, [1], "the owed pass ran though the tip run raised")
        self.assertTrue(any("tip run or the deploy failed" in x for x in lines), lines)
        self.assertIn("[demo] main health: 1 check(s)", lines)

    def test_an_owed_pass_rearms_the_tick(self):
        with mock.patch.object(TK.J, "lane_jobs", lambda repo: []), \
                mock.patch.object(TK.C, "left_held", lambda repo: False):
            self.assertEqual(TK.waits("demo"), [])
            HL.want("demo")
            self.assertEqual(TK.waits("demo"), [TK.TICK_SECS])


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
