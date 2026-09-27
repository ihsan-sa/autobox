"""The lander skeleton's cases: every record survives JSON, bad values are refused, and cli.py collects commands.

    python3 -m unittest discover -s core/tests/lander -p 'test_types.py'
    core/bin/lander selfcheck        (runs this file and prints the tally line)
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

CORE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from lander import cli  # noqa: E402
from lander import types as T  # noqa: E402

SAMPLES = {
    T.Plan: T.Plan(checks=["cc-time"], owned=["core/bin/cc-time"], klass=T.WIDE, paid=True, unowned=["x.sh"]),
    T.Result: T.Result(check="cc-time", tree="a" * 40, status=T.UNRUNNABLE, cases=[{"name": "c1", "status": "ok"}],
                       secs=1.5, cpu_secs=0.7, load=2.25, runner="box", release="r1", nonce="n1"),
    T.Verdict: T.Verdict(verdict=T.HANDBACK_VERDICT, digest="d1", blocking=["b"], advisory=["a"], model="m",
                         tokens=1200, resolved=["r"], unresolved=["u"]),
    T.Check: T.Check(name="cc-time", run="bin/cc-time selfcheck", paths=["core/bin/cc-time"], klass=T.HERMETIC,
                     cap=60, where=["box", "laptop"], mounts=["/usr"], net=True, fixtures=["f.json"]),
    T.Policy: T.Policy(gate_first=["core/bin/cc-guard"], paid_review=["core/bin/*"], lander=["core/lander/**"],
                       protected=["core/.githooks/**"], default=["check"]),
}
SAMPLES[T.Job] = T.Job(repo="h--t", pr=12, head="h" * 40, base_sha="b" * 40, digest="d1", files=["a", "b"],
                       state=T.DEPLOY_PENDING, stage="deploying", plan=SAMPLES[T.Plan],
                       results={"cc-time": "cc-time/" + "a" * 40}, review_key="k", reads_used=2,
                       history=[{"at": "2026-01-01T00:00:00Z", "state": "queued"}], member="h")


def through_json(rec):
    return type(rec).from_dict(json.loads(json.dumps(rec.to_dict())))


class RoundTrip(unittest.TestCase):
    def test_every_record_has_a_sample(self):
        self.assertEqual(set(T.RECORDS), set(SAMPLES))

    def test_round_trip(self):
        for cls, rec in SAMPLES.items():
            with self.subTest(cls.__name__):
                back = through_json(rec)
                self.assertEqual(back, rec)
                self.assertEqual(back.to_dict(), rec.to_dict())

    def test_defaults_round_trip(self):
        for rec in (T.Job(repo="r", pr=1), T.Plan(), T.Policy(), T.Verdict(verdict=T.LAND, digest="d"),
                    T.Result(check="c", tree="t", status=T.PASSED), T.Check(name="c", run="true")):
            with self.subTest(type(rec).__name__):
                self.assertEqual(through_json(rec), rec)

    def test_job_nests_plan_and_keeps_stage(self):
        d = SAMPLES[T.Job].to_dict()
        self.assertEqual(d["plan"]["klass"], T.WIDE)
        self.assertEqual(d["stage"], "deploying")
        self.assertIsInstance(T.Job.from_dict(d).plan, T.Plan)
        self.assertEqual(SAMPLES[T.Job].key, "h--t-12")

    def test_check_class_is_class_on_the_wire(self):
        d = SAMPLES[T.Check].to_dict()
        self.assertEqual(d["class"], T.HERMETIC)
        self.assertNotIn("klass", d)

    def test_unknown_keys_survive_a_rewrite(self):
        d = dict(SAMPLES[T.Job].to_dict(), chat="C1", ts="1.2")
        back = T.Job.from_dict(d).to_dict()
        self.assertEqual((back["chat"], back["ts"]), ("C1", "1.2"))

    def test_result_key(self):
        self.assertEqual(SAMPLES[T.Result].key, SAMPLES[T.Job].results["cc-time"])


class Refusals(unittest.TestCase):
    BAD = [(T.Job, "state", "landing"), (T.Plan, "klass", "tiny"), (T.Result, "status", "red"),
           (T.Verdict, "verdict", "FIX"), (T.Check, "class", "laptop")]

    def test_bad_enum_values(self):
        for cls, key, value in self.BAD:
            with self.subTest(f"{cls.__name__}.{key}={value}"):
                d = dict(SAMPLES[cls].to_dict(), **{key: value})
                with self.assertRaises(ValueError):
                    cls.from_dict(d)

    def test_bad_enum_on_construction_and_on_write(self):
        with self.assertRaises(ValueError):
            T.Job(repo="r", pr=1, state="nope")
        j = T.Job(repo="r", pr=1)
        j.state = "nope"
        with self.assertRaises(ValueError):
            j.to_dict()

    def test_bad_types(self):
        for d in ({"repo": "r", "pr": "12"}, {"repo": "r", "pr": True}, {"repo": "r", "pr": 1, "files": "a"},
                  {"repo": "r", "pr": 1, "plan": "leaf"}):
            with self.subTest(d), self.assertRaises(ValueError):
                T.Job.from_dict(d)

    def test_missing_required(self):
        with self.assertRaises(ValueError):
            T.Job.from_dict({"pr": 1})
        with self.assertRaises(ValueError):
            T.Result.from_dict([])

    def test_check_refuses_unknown_keys(self):
        with self.assertRaises(ValueError):
            T.Check.from_dict({"name": "c", "run": "true", "path": ["x"]})

    def test_enum_tuples_are_what_the_design_says(self):
        self.assertEqual(len(T.JOB_STATES), 11)
        self.assertEqual(T.CHECK_CLASSES, ("static", "hermetic", "box", "timing", "host"))


class Protocols(unittest.TestCase):
    def test_each_call_names_its_unit(self):
        calls = {T.Planner: ["plan"], T.Runner: ["run"], T.Reviewer: ["review", "delta_review"], T.Events: ["log"],
                 T.Cards: ["landed", "stopped"], T.Board: ["close"], T.Deploy: ["request"], T.Tip: ["kick"]}
        for proto, names in calls.items():
            for n in names:
                with self.subTest(f"{proto.__name__}.{n}"):
                    self.assertRegex(getattr(proto, n).__doc__ or "", r"^U\d, lander/\w+\.py\.")


class Mod:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def ok(argv):
    return 0


class Collect(unittest.TestCase):
    def load(self, table):
        def load(m):
            if table[m] == "absent":
                raise ModuleNotFoundError(f"No module named 'lander.{m}'", name=f"lander.{m}")
            if table[m] == "broken":
                raise ModuleNotFoundError("No module named 'tomlkit'", name="tomlkit")
            if table[m] == "raises":
                raise SyntaxError("bad")
            return table[m]
        return load

    def test_collects_from_a_fake_module(self):
        table = {"plan": Mod(COMMANDS={"plan": (ok, "print the plan"), "reach": (ok, "write reach.tsv")}),
                 "lane": Mod(), "tip": "absent"}
        cmds, faults = cli.collect(sorted(table), self.load(table))
        self.assertEqual(faults, [])
        self.assertEqual(sorted(cmds), ["plan", "reach"])
        self.assertEqual(cmds["plan"], (ok, "print the plan", "plan"))

    def test_faults_are_reported_not_raised(self):
        table = {"a": "broken", "b": "raises", "c": Mod(COMMANDS=[]), "d": Mod(COMMANDS={"x": ok}),
                 "e": Mod(COMMANDS={"y": (ok, "one")}), "f": Mod(COMMANDS={"y": (ok, "two")}),
                 "g": Mod(COMMANDS={"selfcheck": (ok, "mine")})}
        cmds, faults = cli.collect(sorted(table), self.load(table))
        self.assertEqual(len(faults), 6, faults)
        self.assertEqual(cmds["y"][2], "e")
        self.assertNotIn("selfcheck", cmds)

    def test_modules_skips_the_skeleton(self):
        with tempfile.TemporaryDirectory() as d:
            for f in ("cli.py", "types.py", "__init__.py", "plan.py", "lane.py", "notes.md", "_priv.py"):
                open(os.path.join(d, f), "w").close()
            self.assertEqual(cli.modules(d), ["lane", "plan"])

    def test_help_lists_commands(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--help"]), 0)
        self.assertIn("selfcheck", out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["no-such-command"]), 2)


if __name__ == "__main__":
    unittest.main()
