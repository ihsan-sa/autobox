#!/usr/bin/python3 -I
"""How tests/member_v2.py picks the pid namespace its cases run in, or names why it cannot (own_pidns).

The run inside needs a real bwrap that nests, which only the box has; these cases need none. Each one builds its own
HOME and its own fake wrappers, and both sides are asserted: with no working wrapper the cases still run, unnested and
named, and a wrapper that works is never reported as unnested.
"""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import types
import unittest

HERE = Path(__file__).resolve().parent


def load():
    spec = importlib.util.spec_from_file_location("member_v2_under_test", HERE / "member_v2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Launcher:   # the two names own_pidns reads off cc-member-v2
    BIN = HERE.parent / "bin"

    @staticmethod
    def require(ok, message):
        if not ok:
            raise ValueError(message)


class OwnPidns(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        home = self.root / "home"
        home.mkdir()
        old = os.environ.get("HOME")
        os.environ["HOME"] = str(home)
        self.addCleanup(lambda: os.environ.__setitem__("HOME", old) if old is not None else os.environ.pop("HOME"))
        self.mod = load()
        # own_pidns locks under the account's passwd home, not $HOME. Point that at this HOME too, so a case never
        # waits on a live selfcheck's lock or on the fd an earlier case left open.
        self.mod.pwd = types.SimpleNamespace(getpwuid=lambda uid: types.SimpleNamespace(pw_dir=str(home)))

    def wrapper(self, name, body):
        p = self.root / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)
        return str(p)

    def run_own(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                rc = self.mod.own_pidns(Launcher)
            except ValueError as exc:
                rc = exc
        return rc, out.getvalue()

    def test_no_wrapper_installed_is_named_unnested(self):
        self.mod.WRAPPERS = (str(self.root / "absent-a"), str(self.root / "absent-b"))
        rc, out = self.run_own()
        self.assertIsNone(rc)
        self.assertRegex(out, r"^cc-member-v2 selfcheck: UNNESTED: ")
        self.assertIn(f"{self.root}/absent-a: not installed", out)
        self.assertIn(f"{self.root}/absent-b: not installed", out)

    def test_a_wrapper_that_cannot_nest_is_named_with_what_it_said(self):
        refuses = self.wrapper("refuses", 'echo "bwrap: no permissions to create a new namespace" >&2; exit 1')
        self.mod.WRAPPERS = (str(self.root / "absent"), refuses)
        rc, out = self.run_own()
        self.assertIsNone(rc)
        self.assertIn(f"{self.root}/absent: not installed", out)
        self.assertIn(f"{refuses}: bwrap: no permissions to create a new namespace", out)

    def test_a_wrapper_that_works_is_not_unnested(self):
        # Its probe passes, so own_pidns goes on to plant the host process; with no sandbox to plant it in, that
        # step refuses. What matters is that it got there: no UNNESTED line.
        works = self.wrapper("works", "exit 0")
        self.mod.WRAPPERS = (works, str(self.root / "never-tried"))
        self.mod.MINIMAL = ["/bin/false"]
        rc, out = self.run_own()
        self.assertIsInstance(rc, ValueError)
        self.assertIn("planted sandbox did not start", str(rc))
        self.assertNotIn("UNNESTED", out)

    # WHICH CASES RUN. selfcheck hands cases() the side it is on; the cases themselves need the box, so a recorder
    # stands in for them here.
    def selfcheck_with(self, own_rc, env=None):
        calls = []
        self.mod.cases = lambda m, nested: calls.append(nested) or 5
        self.mod.own_pidns = lambda m: own_rc
        saved = os.environ.pop(self.mod.HOSTNS, None)
        if env is not None:
            os.environ[self.mod.HOSTNS] = env
        try:
            return self.mod.selfcheck(Launcher), calls
        finally:
            os.environ.pop(self.mod.HOSTNS, None)
            if saved is not None:
                os.environ[self.mod.HOSTNS] = saved

    def test_no_namespace_runs_the_cases_unnested(self):
        self.assertEqual(self.selfcheck_with(None), (5, [False]))

    def test_a_nested_run_returns_its_own_code_and_runs_no_cases_out_here(self):
        self.assertEqual(self.selfcheck_with(0), (0, []))
        self.assertEqual(self.selfcheck_with(1), (1, []))

    def test_inside_the_namespace_the_cases_run_nested(self):
        self.assertEqual(self.selfcheck_with(None, env="pid:[1]"), (5, [True]))


if __name__ == "__main__":
    unittest.main()
