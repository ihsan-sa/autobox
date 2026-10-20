#!/usr/bin/python3 -I
"""How tests/member_v2.py picks the pid namespace its cases run in, or names why it cannot (own_pidns).

The run inside needs a real bwrap that nests, which only the box has; these cases need none. Each one builds its own
HOME and its own fake wrappers, and both sides are asserted: with no working wrapper the cases still run, unnested and
named, and a wrapper that works is never reported as unnested.
"""
import contextlib
import fcntl
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
        self.mod.cases = lambda m, plant: calls.append(plant) or 5
        self.mod.own_pidns = lambda m: own_rc
        saved = {k: os.environ.pop(k, None) for k in (self.mod.HOSTNS, self.mod.PLANT)}
        os.environ.update(env or {})
        try:
            return self.mod.selfcheck(Launcher), calls
        except SystemExit as exc:
            return str(exc), calls
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

    def test_no_namespace_runs_the_cases_unnested(self):
        self.assertEqual(self.selfcheck_with(None), (5, [None]))

    def test_a_nested_run_returns_its_own_code_and_runs_no_cases_out_here(self):
        self.assertEqual(self.selfcheck_with(0), (0, []))
        self.assertEqual(self.selfcheck_with(1), (1, []))

    # THE RUN INSIDE PROVES IT IS ONE. Each case opens its own descriptors: the host's pid namespace and the lock
    # under this case's HOME, held as own_pidns holds it.
    def fd(self, path, flags=os.O_RDONLY):
        f = os.open(path, flags | os.O_CLOEXEC, 0o600)
        self.addCleanup(os.close, f)
        return f

    def held_lock(self):
        d = Path(os.environ["HOME"]) / ".cc/member-v2-selfcheck"
        d.mkdir(parents=True)
        f = self.fd(d / "lock", os.O_RDWR | os.O_CREAT)
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f

    def proof(self, host, lock):
        return {self.mod.HOSTNS: f"{host} {lock}", self.mod.PLANT: "EACCES"}

    def test_the_variables_alone_are_refused_and_run_no_case(self):
        # The bypass perms' read found: any text and EACCES ran the cases on the host with no namespace or lock.
        for text in ("x", "pid:[4026531836]", "3 4"):
            rc, calls = self.selfcheck_with(None, {self.mod.HOSTNS: text, self.mod.PLANT: "EACCES"})
            self.assertRegex(rc, r"^cc-member-v2 selfcheck: refused: CC_MEMBER_V2_HOST_PIDNS is set but ", text)
            self.assertEqual(calls, [], text)

    def test_this_runs_own_namespace_is_refused(self):
        rc, calls = self.selfcheck_with(None, self.proof(self.fd("/proc/self/ns/pid"), self.held_lock()))
        self.assertIn("this run is in that pid namespace, not one of its own", rc)
        self.assertEqual(calls, [])

    def test_a_namespace_that_is_not_a_pid_one_is_refused(self):
        rc, calls = self.selfcheck_with(None, self.proof(self.fd("/proc/self/ns/net"), self.held_lock()))
        self.assertIn("its first descriptor is no pid namespace", rc)
        self.assertEqual(calls, [])

    def test_a_proof_that_holds_runs_the_cases_nested(self):
        # This process's pid namespace stands for the host's; the run's own is read off its net namespace, which is
        # also on nsfs and is not that pid namespace. Only the inode comparison is stood in for.
        self.mod.SELF_PIDNS = "/proc/self/ns/net"
        self.assertEqual(self.selfcheck_with(None, self.proof(self.fd("/proc/self/ns/pid"), self.held_lock())),
                         (5, ["EACCES"]))

    def test_a_lock_another_run_holds_is_refused(self):
        self.mod.SELF_PIDNS = "/proc/self/ns/net"
        mine = Path(os.environ["HOME"]) / ".cc/member-v2-selfcheck/lock"
        self.held_lock()   # another selfcheck's open of the same file
        rc, calls = self.selfcheck_with(None, self.proof(self.fd("/proc/self/ns/pid"), self.fd(mine, os.O_RDWR)))
        self.assertIn(f"another selfcheck holds {mine}", rc)
        self.assertEqual(calls, [])

    def test_a_descriptor_on_another_file_is_refused(self):
        self.mod.SELF_PIDNS = "/proc/self/ns/net"
        self.held_lock()
        other = self.root / "other"
        other.write_text("")
        rc, calls = self.selfcheck_with(None, self.proof(self.fd("/proc/self/ns/pid"), self.fd(other)))
        self.assertIn("its second descriptor is not ", rc)
        self.assertEqual(calls, [])

if __name__ == "__main__":
    unittest.main()
