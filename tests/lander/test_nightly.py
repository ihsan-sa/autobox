"""nightly.py: which never-red checks leave the per-PR plan, the tick's once-a-day sweep, and the lane's reuse of a
pass on the same tree. Every case builds its own log, manifest and state. Run:
python3 -m unittest discover -s core/tests/lander -t core/tests/lander -p 'test_nightly.py'
"""
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from lander import events as E  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import lane as L  # noqa: E402
from lander import manifest as M  # noqa: E402
from lander import nightly as NG  # noqa: E402
from lander import records as REC  # noqa: E402
from lander import tick as TK  # noqa: E402
from lander import types as T  # noqa: E402

NOW = 1_800_000_000
OLD, RECENT = E.stamp(NOW - 40 * 86400), E.stamp(NOW - 86400)
TEXT = """
[[check]]
name = "quiet"
run = "tests/quiet.sh"
paths = ["app/**"]
class = "static"
[[check]]
name = "broke"
run = "tests/broke.sh"
paths = ["app/**"]
class = "static"
[[check]]
name = "unrun"
run = "tests/unrun.sh"
paths = ["app/**"]
class = "static"
[[check]]
name = "selfcheck-cc-guard"
run = "bin/cc-guard selfcheck"
paths = ["bin/cc-guard"]
class = "host"
[[check]]
name = "owns-gate"
run = "tests/og.sh"
paths = ["hooks/**"]
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
                      policy=T.Policy(gate_first=["hooks/**", "tests/**"], lander=["lander/**"]))


def log(*lines):
    return [f"{at}\t{text}\n" for at, text in lines]


BASE = [(OLD, "queued demo#1 who=x"),
        (RECENT, "stage demo#1 gate gate=quiet ok=yes secs=600"),
        (RECENT, "stage demo#1 gate gate=boxy ok=yes secs=60"),
        (RECENT, "stage demo#1 gate gate=selfcheck-cc-guard ok=yes secs=60"),
        (RECENT, "stage demo#1 gate gate=owns-gate ok=yes secs=60"),
        (RECENT, "stage demo#2 gate gate=broke ok=no secs=30"),
        (RECENT, "stage demo#3 gate gate=quiet ok=yes secs=1200"),
        (RECENT, "stage demo#2 handback why=x"),
        (RECENT, "handed demo#2 head=abc")]


class Scan(unittest.TestCase):
    def test_a_red_handed_back_is_the_prs_and_a_red_then_held_is_not(self):
        rec = NG.scan(log(*BASE, (RECENT, "stage demo#4 gate gate=quiet ok=no secs=1"),
                          (RECENT, "stage demo#4 held why=could not run"),
                          (RECENT, "stage demo#5 gate gate=quiet ok=main-red secs=1"),
                          (RECENT, "stage other#9 gate gate=quiet ok=no secs=1"),
                          (RECENT, "handed other#9 head=abc")), "demo", NOW)
        self.assertEqual(rec["pr_reds"], {"broke": 1})
        self.assertEqual(rec["runs"]["quiet"], 4)
        self.assertEqual(rec["prs"], {"1", "2", "3", "4", "5"})

    def test_a_nightly_red_is_kept_and_a_nightly_green_is_not(self):
        rec = NG.scan(log((RECENT, "nightly demo check=quiet ok=no secs=3 sha=abc"),
                          (RECENT, "nightly demo check=broke ok=yes secs=3 sha=abc")), "demo", NOW)
        self.assertEqual(list(rec["nightly_reds"]), ["quiet"])

    def test_an_unrunnable_nightly_result_counts_as_red(self):
        # task: "An unrunnable nightly result counts as red"
        rec = NG.scan(log((RECENT, "nightly demo check=quiet ok=unrunnable secs=0 sha=abc"),
                          (RECENT, "nightly demo check=broke ok=yes secs=3 sha=abc")), "demo", NOW)
        self.assertEqual(list(rec["nightly_reds"]), ["quiet"])


class FewRuns(unittest.TestCase):
    """The cases below lower MIN_RUNS so a short fixture log can move a check; this one keeps the real value."""

    def test_a_check_moves_only_after_min_runs_green_runs(self):
        runs = [(RECENT, f"stage demo#{9 + i} gate gate=quiet ok=yes secs=5") for i in range(NG.MIN_RUNS - 1)]
        rec = NG.scan(log(BASE[0], *runs), "demo", NOW)
        self.assertEqual(NG.moved("demo", manifest(), rec, NOW), [])   # one short of the minimum
        rec = NG.scan(log(BASE[0], *runs, (RECENT, "stage demo#99 gate gate=quiet ok=yes secs=5")), "demo", NOW)
        self.assertEqual(NG.moved("demo", manifest(), rec, NOW), ["quiet"])

    def test_a_note_is_not_read_as_the_lines_own_fields(self):
        rec = NG.scan(log(BASE[0], (RECENT, "stage demo#2 gate gate=quiet ok=yes secs=5 note=was ok=no gate=broke"),
                          (RECENT, "handed demo#2 head=abc")), "demo", NOW)
        self.assertEqual((rec["runs"], rec["pr_reds"]), ({"quiet": 1}, {}))


class OneRun(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(NG, "MIN_RUNS", 1)
        p.start()
        self.addCleanup(p.stop)


class Moved(OneRun):
    def test_only_a_never_red_unguarded_check_that_ran_moves(self):
        rec = NG.scan(log(*BASE), "demo", NOW)
        # broke: a PR's red; unrun: no run; selfcheck-cc-guard: a guard word; owns-gate: a gate_first path; boxy: box
        self.assertEqual(NG.moved("demo", manifest(), rec, NOW), ["quiet"])

    def test_a_log_younger_than_the_window_moves_nothing(self):
        rec = NG.scan(log(*BASE[1:]), "demo", NOW)
        self.assertEqual(NG.moved("demo", manifest(), rec, NOW), [])

    def test_a_nightly_red_puts_the_check_back(self):
        rec = NG.scan(log(*BASE, (RECENT, "nightly demo check=quiet ok=no secs=3 sha=abc")), "demo", NOW)
        self.assertEqual(NG.moved("demo", manifest(), rec, NOW), [])

    def test_a_red_older_than_the_window_does_not_count(self):
        old_red = [(E.stamp(NOW - 35 * 86400), "stage demo#7 gate gate=broke ok=no secs=1"),
                   (E.stamp(NOW - 35 * 86400), "handed demo#7 head=abc")]
        rec = NG.scan(log(*[b for b in BASE if "demo#2" not in b[1]], *old_red,
                          (RECENT, "stage demo#8 gate gate=broke ok=yes secs=1")), "demo", NOW)
        self.assertEqual(NG.moved("demo", manifest(), rec, NOW), ["broke", "quiet"])


ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
# perms' security read of #1190: each of these guards a gate, the sandbox, routing or member isolation, and no name
# word or policy list caught them
GUARD_CHECKS = ("selfcheck-dashboard", "py-compile-cc-slack", "selfcheck-cc-slack", "e2e-cc-slack-local",
                "selfcheck-cc-broker", "selfcheck-cc-msg", "selfcheck-cc-mail", "selfcheck-cc-publish",
                "selfcheck-cc-loop", "e2e-say-go-loop", "selfcheck-cc-gh-org", "shellcheck-gh",
                "selfcheck-cc-refusals", "selfcheck-cc-tmp-reap",
                "selfcheck-cc-subagent-bound")


class Guards(unittest.TestCase):
    def test_the_real_manifests_guarding_checks_stay_per_pr(self):
        def read_at(root, rev, path):   # the working tree's manifest, the one this tree would land
            try:
                with open(os.path.join(root, path), encoding="utf-8") as f:
                    return f.read()
            except FileNotFoundError:
                return None
        with mock.patch.object(M, "read_at", read_at):
            m = M.load(ROOT, "HEAD")
        # the overlay's own Cloudflare tool, found by its path so core/ never names the box
        cloudflare = [n for n, c in m.checks.items() if any(M.match(["bin-private/*cloudflare*"], p) for p in c.paths)]
        self.assertTrue(cloudflare, "no check covers the overlay's Cloudflare tool")
        missing = [n for n in GUARD_CHECKS if n not in m.checks]
        self.assertEqual(missing, [], "a guarding check was renamed: update GUARD_CHECKS")
        rec = {"first": 1, "runs": {n: NG.MIN_RUNS for n in m.checks}, "pr_reds": {}, "nightly_reds": {}}
        out = NG.moved("box", m, rec, NOW)
        self.assertEqual([n for n in GUARD_CHECKS + tuple(cloudflare) if n in out], [])
        cal = [n for n in m.checks if n.startswith("py-compile-") and n.endswith("-cal")]
        self.assertTrue(cal and all(n in out for n in cal))   # the rule still moves a check that guards nothing

    def test_every_hook_tool_is_a_guarded_path(self):
        hooks = NG.hook_paths()
        for tool in ("core/bin/cc-guard", "core/bin/cc-subagent-bound", "core/bin/cc-refusals"):
            self.assertIn(tool, hooks)
        m = manifest()
        m.checks["hooked"] = M.parse_checks('[[check]]\nname = "hooked"\nrun = "core/bin/cc-checkpoint selfcheck"\n'
                                            'paths = ["core/bin/cc-checkpoint"]\nclass = "host"\n', "", "t")[0][0]
        self.assertTrue(NG.guarded(m, "hooked", ["core/bin/cc-checkpoint"]))
        self.assertFalse(NG.guarded(m, "hooked", []))

    def test_unreadable_hook_settings_guard_every_check(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        os.makedirs(os.path.join(d, "config"))
        for rel in NG.HOOK_SETTINGS:
            with open(os.path.join(d, rel), "w") as f:
                f.write('{"hooks": [{"command": "$HOME/bin/cc-x hook"}]}' if "managed" in rel else
                        '{"hooks": {"Stop": [{"hooks": [{"command": "$HOME/bin/cc-y"}]}]}}')
        self.assertEqual(NG.hook_paths(d), ["core/bin/cc-x", "core/bin/cc-y"])
        with open(os.path.join(d, NG.HOOK_SETTINGS[1]), "w") as f:
            f.write("{not json")
        self.assertIsNone(NG.hook_paths(d))
        self.assertTrue(NG.guarded(manifest(), "quiet", None))
        self.assertFalse(NG.guarded(manifest(), "quiet", []))


class Trim(OneRun):
    def setUp(self):
        super().setUp()
        self.rec = NG.scan(log(*BASE), "demo", NOW)

    def test_a_leaf_plan_loses_the_moved_check(self):
        with mock.patch.object(NG.time, "time", lambda: NOW):
            p = NG.trim("demo", manifest(), T.Plan(checks=["broke", "quiet"], klass=T.LEAF), self.rec)
        self.assertEqual((p.checks, p.extra.get("nightly")), (["broke"], ["quiet"]))

    def test_a_gate_first_plan_keeps_every_check(self):
        with mock.patch.object(NG.time, "time", lambda: NOW):
            p = NG.trim("demo", manifest(), T.Plan(checks=["broke", "quiet"], klass=T.GATE_FIRST), self.rec)
        self.assertEqual((p.checks, p.extra.get("nightly")), (["broke", "quiet"], None))

    def test_report_prints_before_and_after(self):
        lines = NG.report("demo", manifest(), self.rec, NOW)
        self.assertIn("1 of 6 checks run nightly instead of per PR: quiet", lines[0])
        # 2010 s over 3 PRs before; 210 s without quiet's 1800
        self.assertIn("over 3 PRs: before 0.19 h, after 0.02 h", lines[1])


class State(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(NG, "MIN_RUNS", 1)
        p.start()
        self.addCleanup(p.stop)
        self.tmp = tempfile.mkdtemp(prefix="lander-nightly.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = {"LANDER_STATE": self.tmp, "CC_LAND_STATE": self.tmp, "CC_LANDER_STATE": self.tmp,
               "HOME": self.tmp, "CC_CONFIG": os.path.join(self.tmp, "config")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        NG._cache.clear()
        self.addCleanup(NG._cache.clear)

    def write_log(self, lines):
        os.makedirs(os.path.dirname(E.log_path()), exist_ok=True)
        with open(E.log_path(), "w") as f:
            f.writelines(lines)


class Tick(State):
    def units(self):
        return {"tip": types.ModuleType("tip"), "deploy": types.ModuleType("deploy")}

    def test_the_sweep_starts_once_a_day_and_only_on_an_old_enough_log(self):
        started = []
        with mock.patch.object(L, "paused", lambda r: False), \
                mock.patch.object(NG, "spawn", lambda r: (True, started.append(r) or f"[{r}] started")):
            self.write_log(log(*BASE[1:]))   # a day old: nothing can move yet
            self.assertEqual(TK.nightly("demo", self.units()), [])
            NG._cache.clear()
            self.write_log([f"{E.stamp(time.time() - 40 * 86400)}\tqueued demo#1 who=x\n",
                            f"{E.stamp()}\tstage demo#1 gate gate=quiet ok=yes secs=5\n"])
            self.assertEqual(TK.nightly("demo", self.units()), ["[demo] started"])
            self.assertEqual(TK.nightly("demo", self.units()), [])   # the stamp: not again today
            self.assertEqual(TK.nightly("al--proj", self.units()), [])   # a member's repo: never
        self.assertEqual(started, ["demo"])

    def test_a_tick_without_installed_units_starts_nothing(self):
        self.assertEqual(TK.nightly("demo", {}), [])

    def old_log(self):
        self.write_log([f"{E.stamp(time.time() - 40 * 86400)}\tqueued demo#1 who=x\n",
                        f"{E.stamp()}\tstage demo#1 gate gate=quiet ok=yes secs=5\n"])

    def test_a_sweep_is_due_only_when_some_check_ran_min_runs_times(self):
        p = mock.patch.object(NG, "MIN_RUNS", 3)   # State's setUp lowers it to 1
        p.start()
        self.addCleanup(p.stop)
        few = [f"{E.stamp(time.time() - 40 * 86400)}\tqueued demo#1 who=x\n"]
        few += [f"{E.stamp()}\tstage demo#1 gate gate=quiet ok=yes secs=5\n"] * (NG.MIN_RUNS - 1)
        self.write_log(few)
        self.assertFalse(NG.due("demo"))   # moved() would move nothing, so a sweep has nothing to cover
        NG._cache.clear()   # the cache keys on the log's stat, which a same-size rewrite may not change
        self.write_log(few + [few[-1]])
        self.assertTrue(NG.due("demo"))

    def test_a_failed_start_does_not_spend_the_day(self):
        self.old_log()
        tries = []
        with mock.patch.object(L, "paused", lambda r: False), \
                mock.patch.object(NG, "spawn", lambda r: (tries.append(r) is None and len(tries) > 1, f"try {len(tries)}")):
            self.assertEqual(TK.nightly("demo", self.units()), ["try 1"])   # would not start: no stamp
            self.assertEqual(TK.nightly("demo", self.units()), ["try 2"])   # so the next tick tries again
            self.assertEqual(TK.nightly("demo", self.units()), [])          # and a start stamps the day
        self.assertEqual(len(tries), 2)

    def test_a_raising_due_or_spawn_is_a_tick_fault_not_the_ticks_end(self):
        self.old_log()

        def boom(*a):
            raise OSError("disk full")
        for name in ("due", "spawn"):
            with mock.patch.object(L, "paused", lambda r: False), mock.patch.object(NG, name, boom):
                self.assertEqual(TK.nightly("demo", self.units()),
                                 ["[demo] the nightly sweep failed: OSError: disk full"])
        with open(E.log_path()) as f:
            self.assertEqual(f.read().count("tick-fault demo nightly: OSError: disk full"), 2)
        self.assertTrue(NG.due("demo"))   # neither fault stamped the day


class Run(State):
    def test_a_red_logs_and_files_one_row_and_a_green_files_none(self):
        rec = NG.scan(log(*BASE), "demo", NOW)
        rec["first"] = 1   # the window is measured from the real clock in run()
        rows = []
        results = {"quiet": T.Result(check="quiet", tree="t", status=T.FAILED, secs=4, extra={"why": "boom"})}
        with mock.patch.object(NG, "record", lambda repo, now=None, days=7: rec), \
                mock.patch.object(NG.M, "load", lambda *a, **k: manifest()), \
                mock.patch("lander.deploy.applied", lambda repo: "a" * 40), \
                mock.patch.object(NG, "file_row", lambda r, n, sha, why: rows.append((n, why)) or "filed"):
            NG.run("demo", check=lambda n, sha: results[n])
            with open(E.log_path()) as f:
                self.assertIn("nightly demo check=quiet ok=no secs=4 sha=aaaaaaaaaaaa", f.read())
            self.assertEqual(rows, [("quiet", "boom")])
            rows.clear()
            results["quiet"] = T.Result(check="quiet", tree="t", status=T.PASSED, secs=4)
            NG.run("demo", check=lambda n, sha: results[n])
            self.assertEqual(rows, [])

    def test_an_unrunnable_check_logs_red_and_files_a_row(self):
        rec = NG.scan(log(*BASE), "demo", NOW)
        rec["first"] = 1
        rows = []
        with mock.patch.object(NG, "record", lambda repo, now=None, days=7: rec), \
                mock.patch.object(NG.M, "load", lambda *a, **k: manifest()), \
                mock.patch("lander.deploy.applied", lambda repo: "a" * 40), \
                mock.patch.object(NG, "file_row", lambda r, n, sha, why: rows.append(n) or "filed"):
            NG.run("demo", check=lambda n, sha: T.Result(check=n, tree="t", status=T.UNRUNNABLE, secs=0))
            with open(E.log_path()) as f:
                self.assertIn("nightly demo check=quiet ok=unrunnable", f.read())
        self.assertEqual(rows, ["quiet"])


class Spawn(unittest.TestCase):
    def test_the_fallback_child_gets_the_tick_env_not_the_callers(self):
        seen = {}

        def popen(argv, **kw):
            seen.update(kw["env"])
            return types.SimpleNamespace(pid=7)
        env = {k: v for k, v in os.environ.items() if k != "INVOCATION_ID"}
        env.update(CC_CLAUDE="/tmp/fake-reviewer", BASH_ENV="/tmp/evil", PATH="/tmp/evil-bin")
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(L, "run", lambda *a, **k: (1, "", "no manager")), \
                mock.patch.object(NG.subprocess, "Popen", popen):
            self.assertEqual(NG.spawn("demo"), (True, "[demo] nightly sweep started (pid 7)"))
        self.assertNotIn("CC_CLAUDE", seen)
        self.assertNotIn("BASH_ENV", seen)
        self.assertEqual(seen["PATH"], L.tick_path())
        self.assertEqual(seen["PYTHONDONTWRITEBYTECODE"], "1")


class Reuse(State):
    def job(self):
        return T.Job(repo="demo", pr=5, head="h" * 40, state=T.CHECKING)

    def put(self, status, release=None):
        r = T.Result(check="quiet", tree="t" * 40, status=status, release=release or REC.release())
        REC._write(REC.Store("demo", root=self.tmp).job_path("demo-5", "quiet", "t" * 40), r.to_dict())

    def passed(self):
        job = self.job()
        with mock.patch.object(J, "save", lambda j: None):
            ok = L.Lane.passed(None, REC.Store("demo", root=self.tmp), job, "quiet", "t" * 40)
        return ok, job.results

    def test_a_pass_on_the_same_tree_is_reused(self):
        self.put(T.PASSED)
        self.assertEqual(self.passed(), (True, {"quiet": "quiet/" + "t" * 40}))
        with open(E.log_path()) as f:
            self.assertIn("stage demo#5 reused gate=quiet tree=tttttttttttt", f.read())

    def test_a_red_another_release_or_another_tree_is_not(self):
        self.assertEqual(self.passed(), (False, {}))
        self.put(T.FAILED)
        self.assertEqual(self.passed(), (False, {}))
        self.put(T.PASSED, release="older")
        self.assertEqual(self.passed(), (False, {}))


if __name__ == "__main__":
    unittest.main()
