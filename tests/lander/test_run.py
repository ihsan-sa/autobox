"""U2's run cases: the tree, the status rules, the sandbox, admission and scopes, the runners, the store, the
failures ledger, quarantine, judging a red against the base, and `lander check` / `lander sweep`.

    python3 -m unittest discover -s core/tests/lander -p 'test_run.py'

Cases that start bwrap or a systemd scope skip, saying so, on a machine without one. Every case uses its own
LANDER_STATE and its own git repo.
"""
import base64
import contextlib
import datetime
import fcntl
import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest import mock

CORE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
HERE = os.path.dirname(os.path.realpath(__file__))
for p in (CORE, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from lander import admission as A  # noqa: E402
from lander import cards as C  # noqa: E402
from lander import check as CK  # noqa: E402
from lander import manifest as M  # noqa: E402
from lander import records as REC  # noqa: E402
from lander import run as RUN  # noqa: E402
from lander import sandbox as S  # noqa: E402
from lander import types as T  # noqa: E402
from test_plan import git, write  # noqa: E402

HAS_BWRAP = S.available() and subprocess.run(["bwrap", "--ro-bind", "/", "/", "true"],
                                             capture_output=True).returncode == 0
CLI = os.path.join(CORE, "lander", "cli.py")


def chk(name="c", run="true", klass=T.HERMETIC, **kw):
    return T.Check(name=name, run=run, klass=klass, **kw)


class Env(unittest.TestCase):
    """Its own state dir, no scope unless a case asks, and a repo holding one committed tree."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.tmp = d.name
        self.state = os.path.join(self.tmp, "state")
        # TMPDIR is the case's own: a run root `cc-land.run.<pid>.*` in the shared $TMPDIR whose pid is no lander
        # (this suite's is python -m unittest) is removed by a landing's sweep of dead runs, mid-check, so the log
        # and the tree vanished under load and a case read an empty log (rc 1, no lines) or a failed `git init`.
        tmpdir = os.path.join(self.tmp, "t")
        os.mkdir(tmpdir)
        # CC_SUITES_DIR: no laptop unless a case makes one (this box's own ~/.cc/suites would route a loaded run there)
        p = mock.patch.dict(os.environ, {"LANDER_STATE": self.state, "CC_LAND_STATE": os.path.join(self.tmp, "land"),
                                         "LANDER_SCOPE": "0", "TMPDIR": tmpdir,
                                         "CC_SUITES_DIR": os.path.join(self.tmp, "suites")})
        p.start()
        self.addCleanup(p.stop)
        # nothing reads the box's own ~/.cc/state/land or config: every state root falls back to the passwd home
        for name, val in (("PASSWD_HOME", os.path.join(self.tmp, "home")), ("REVIEWER_CONFIG", os.path.join(os.path.join(self.tmp, "home"), ".cc", "config"))):
            p = mock.patch.object(C, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.repo = os.path.join(self.tmp, "repo")
        os.mkdir(self.repo)
        git(self.repo, "init", "-q")
        write(self.repo, {"core/bin/tool": "#!/bin/sh\necho tool\n", "README.md": "x\n"})
        os.chmod(os.path.join(self.repo, "core/bin/tool"), 0o755)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "base")
        self.tree = RUN.tree_of(self.repo, "HEAD")

    def run_(self, check, where="box", **kw):
        return RUN.run(check, self.tree, where, repo_root=self.repo, **kw)


class Status(unittest.TestCase):
    def test_the_status_rules(self):
        cases = [((0, "all good"), T.PASSED), ((0, "tool: 1 failed"), T.FAILED),
                 ((0, "3 failed\nretry: 0 failed"), T.PASSED), ((1, "boom"), T.FAILED),
                 ((124, ""), T.UNRUNNABLE), ((137, ""), T.UNRUNNABLE), ((-9, ""), T.UNRUNNABLE),
                 ((1, "write: No space left on device"), T.UNRUNNABLE),
                 ((1, "bwrap: Can't mount proc on /newroot/proc"), T.UNRUNNABLE),
                 ((1, "Failed to connect to user scope bus via local transport"), T.UNRUNNABLE),
                 ((0, "bwrap: a line of the check's own that says bwrap:"), T.PASSED)]
        for (rc, text), want in cases:
            self.assertEqual(RUN.status_of(rc, text)[0], want, (rc, text))
        self.assertEqual(RUN.status_of(0, "", capped=True)[0], T.UNRUNNABLE)

    def test_red_lines_leave_out_pass_lines(self):
        self.assertEqual(RUN.red_lines("ok 1 fine\n✗ broke here\nFAIL two\n✓ FAIL-looking pass"),
                         ["✗ broke here", "FAIL two"])


class Tree(Env):
    def test_materialise_writes_the_exact_tree_as_a_git_repo_in_the_member_path_shape(self):
        run_dir, head = RUN.materialise(self.repo, self.tree, "repo.7")
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))
        self.assertRegex(head, r"/cc-land\.run\.\d+\.[^/]+/cc-land\.gates\.repo\.7\.[^/]+/head$")
        self.assertEqual(git(head, "rev-parse", "HEAD^{tree}"), self.tree)
        self.assertTrue(os.access(os.path.join(head, "core/bin/tool"), os.X_OK))
        self.assertEqual(git(head, "status", "--porcelain"), "")

    def test_a_tree_with_a_submodule_is_written_out_and_proved(self):
        git(self.repo, "update-index", "--add", "--cacheinfo", "160000," + "1" * 40 + ",vendor/sub")
        git(self.repo, "update-index", "--add", "--cacheinfo", "160000," + "2" * 40 + ",a dir/deeper/sub two")
        tree = git(self.repo, "write-tree")
        run_dir, head = RUN.materialise(self.repo, tree)
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))
        self.assertEqual(git(head, "rev-parse", "HEAD^{tree}"), tree)

    def test_a_bad_tree_is_unrunnable_and_leaves_nothing(self):
        tmp = os.path.join(self.tmp, "private-tmp")   # its own TMPDIR: nothing else on the box writes here
        os.mkdir(tmp)
        with mock.patch.dict(os.environ, {"TMPDIR": tmp}):
            with self.assertRaises(RUN.Unrunnable):
                RUN.materialise(self.repo, "0" * 40)
            with self.assertRaises(RUN.Unrunnable):
                RUN.materialise(self.repo, "HEAD")
        self.assertEqual(os.listdir(tmp), [])

    def test_tree_of_the_working_copy_includes_untracked_files(self):
        write(self.repo, {"new.txt": "n"})
        wt = RUN.tree_of(self.repo, "")
        self.assertNotEqual(wt, self.tree)
        self.assertIn("new.txt", git(self.repo, "ls-tree", "--name-only", wt))
        self.assertEqual(git(self.repo, "status", "--porcelain"), "?? new.txt")   # the real index is untouched


@unittest.skipUnless(HAS_BWRAP, "no working bwrap on this machine")
class Sandbox(Env):
    def test_inside_there_is_the_tree_and_none_of_the_box(self):
        home = os.path.expanduser("~")
        probe = textwrap.dedent(f'''
            set -e
            test -x core/bin/tool
            test "$(git rev-parse HEAD^{{tree}})" = {self.tree}
            test "$HOME" = /tmp/home
            test ! -e "{home}" && test "$PWD" = /work/tree
            test -z "${{SECRET_TOKEN:-}}" && test -z "${{CLAUDECODE:-}}"
            tmux has-session -t main
            command -v claude | grep -q /tmp/home/.local/bin/claude
            test "$(grep -c : /proc/net/dev)" = 1
            test "$CC_SELFTEST_SPILL" = 0
            echo "0 failed"
        ''')
        with mock.patch.dict(os.environ, {"SECRET_TOKEN": "s3cret", "CLAUDECODE": "1"}):
            r = self.run_(chk(run=probe))
        self.assertEqual(r.status, T.PASSED, r.extra)
        self.assertTrue(r.runner.startswith("box:bwrap:"), r.runner)

    def test_net_true_shares_the_network(self):
        r = self.run_(chk(run='test "$(grep -c : /proc/net/dev)" -gt 1', net=True))
        self.assertEqual(r.status, T.PASSED, r.extra)

    def test_a_mount_is_read_only_and_a_missing_mount_is_unrunnable(self):
        m = os.path.join(self.tmp, "venv")
        os.mkdir(m)
        write(m, {"marker": "here"})
        r = self.run_(chk(run=f'grep -q here {m}/marker && ! touch {m}/w 2>/dev/null', mounts=[m]))
        self.assertEqual(r.status, T.PASSED, r.extra)
        r = self.run_(chk(run="true", mounts=[m + "-gone"]))
        self.assertEqual(r.status, T.UNRUNNABLE)
        self.assertIn("mount", r.extra["why"])

    def test_the_check_runs_from_its_manifest_prefix(self):
        r = self.run_(chk(run="test -x bin/tool"), cwd="core/")
        self.assertEqual(r.status, T.PASSED, r.extra)

    def test_a_red_carries_its_red_lines_as_cases(self):
        r = self.run_(chk(run='echo "ok 1 fine"; echo "FAIL the thing"; exit 1'))
        self.assertEqual(r.status, T.FAILED)
        self.assertEqual(r.cases, [{"name": "FAIL the thing", "status": T.FAILED}])

    def test_the_cap_makes_it_unrunnable_not_red(self):
        r = self.run_(chk(run="sleep 30", cap=1))
        self.assertEqual((r.status, r.extra["why"]), (T.UNRUNNABLE, "stopped at its cap"))
        self.assertLess(r.secs, 15)

    def test_no_bwrap_makes_a_sandboxed_class_unrunnable_never_a_host_run(self):
        with mock.patch.object(S, "available", return_value=False):
            r = self.run_(chk(run="true"))
        self.assertEqual(r.status, T.UNRUNNABLE)

    @unittest.skipUnless(A.scope_available.__call__ and os.path.exists(f"/run/user/{os.getuid()}/bus"),
                         "no user systemd bus")
    def test_in_a_scope_and_memory_max_kills_to_unrunnable(self):
        with mock.patch.dict(os.environ, {"LANDER_SCOPE": "1"}), mock.patch.object(A, "MEM_MAX", "64M"):
            ok = self.run_(chk(run="cat /proc/self/cgroup; echo 0 failed"))
            big = self.run_(chk(run="python3 -c 'b = bytearray(512 * 1024 * 1024); print(len(b))'"))
        self.assertEqual(ok.status, T.PASSED, ok.extra)
        self.assertTrue(ok.runner.endswith(":scope"), ok.runner)
        self.assertEqual(big.status, T.UNRUNNABLE, big.extra)


class HostAndRunners(Env):
    def test_host_class_runs_with_the_environment_scrubbed(self):
        probe = ('test -z "${GH_TOKEN:-}${CLAUDE_X:-}${CLAUDECODE:-}${A_PASSWORD:-}" && test -n "$CC_CONFIG_DENY" '
                 '&& test "$KEEP" = yes && test -x core/bin/tool')
        with mock.patch.dict(os.environ, {"GH_TOKEN": "t", "CLAUDE_X": "1", "CLAUDECODE": "1", "A_PASSWORD": "p",
                                          "KEEP": "yes"}):
            r = self.run_(chk(run=probe, klass=T.HOST))
        self.assertEqual((r.status, r.runner.split(":")[1]), (T.PASSED, "host"), r.extra)

    def test_a_runner_the_check_does_not_list_is_refused(self):
        r = self.run_(chk(run="true", where=["box"]), where="laptop")
        self.assertEqual(r.status, T.UNRUNNABLE)
        self.assertIn("not one of this check's runners", r.extra["why"])

    def test_the_member_runner_keeps_cc_sandboxs_tree_shape(self):
        argv, wd, env, how = RUN._member_argv(chk(run="bin/x selfcheck"), "/t/head", "core/", "member:ann:t1",
                                              {"CC_LAND_CHANGED": "a b"})
        self.assertEqual(argv[1:8], ["member", "ann", "t1", "--tree", "/t/head", "--", "env"])
        self.assertTrue(argv[0].endswith("/bin/cc-sandbox"))
        self.assertEqual(argv[8:], ["CC_LAND_CHANGED=a b", "/bin/sh", "-c", "cd core/ && bin/x selfcheck"])
        self.assertEqual((wd, how), ("/t/head", "member"))
        self.assertEqual(RUN._member_argv(chk(), "/h", "", "member:ann", {})[0][3], "")

    def laptop(self, host="runner", pinned="runner"):
        # cc-suites' transport as laptop-setup leaves it: a key, the destination, and a host key pinned for `pinned`
        d = os.path.join(self.tmp, "suites")
        os.makedirs(d, exist_ok=True)
        write(d, {"id_ed25519": "k\n", "remote": f"ccsuite@{host}\n",
                  "known_hosts": f"{pinned} ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIxx\n"})
        return d

    def shim(self, name, body):
        d = os.path.join(self.tmp, name)
        os.mkdir(d)
        with open(os.path.join(d, "ssh"), "w") as f:
            f.write("#!/bin/bash\n" + body)
        os.chmod(os.path.join(d, "ssh"), 0o755)
        return {"PATH": d + ":" + os.environ["PATH"]}

    def forced(self, power):
        # the stub ssh: checks the box passed the key and the pinned host, then runs the key's forced command here
        return f'''for a in "$@"; do case "$a" in -i) k=1;; StrictHostKeyChecking=yes) s=1;; esac; done
[ "$k$s" = 11 ] || {{ echo "ssh: no key or no pinned host"; exit 255; }}
while [ "$1" != -- ]; do shift; done; shift
export SSH_ORIGINAL_COMMAND="$*" CC_SUITES_RUNNER_DIR={self.tmp}/runner CC_SUITES_POWER_DIR={power}
export CC_SUITES_LOADAVG={self.tmp}/loadavg
exec bash {RUN.BIN}/cc-suites runner
'''

    def test_the_laptop_goes_by_cc_suites_key_and_pinned_host_and_refuses_an_unpinned_one(self):
        d = self.laptop()
        argv = RUN.laptop_argv(chk(), self.tree, "core/")
        dest = argv.index("ccsuite@runner")
        self.assertEqual(argv[argv.index("-i") + 1], os.path.join(d, "id_ed25519"))
        for o in ("StrictHostKeyChecking=yes", f"UserKnownHostsFile={d}/known_hosts", "IdentitiesOnly=yes",
                  "GlobalKnownHostsFile=/dev/null", "BatchMode=yes"):
            self.assertIn(o, argv)
        self.assertEqual(argv[dest + 1:dest + 4], ["--", "job", "c"])
        # the job has no network unless its manifest says net = true, which goes as the one trailing word `net`
        self.assertEqual(len(argv), dest + 8)
        self.assertNotIn("net", argv)
        self.assertEqual(RUN.laptop_argv(chk(net=True), self.tree, "core/"), argv + ["net"])
        self.laptop(host="elsewhere")        # a destination whose host key nobody pinned: no ssh at all
        with self.assertRaisesRegex(RUN.Unrunnable, "no pinned host key"):
            RUN.laptop_argv(chk(), self.tree, "")
        os.remove(os.path.join(d, "known_hosts"))
        self.assertEqual(RUN.laptop_dest(), "")
        with mock.patch.object(A, "busy", return_value=True):
            self.assertEqual(RUN.choose_where(chk(where=["box", "laptop"])), "box")

    def test_a_check_name_with_a_newline_never_reaches_the_laptop(self):
        # the security read of #866: ssh joins argv with spaces and the runner reads the first line, so this name
        # would arrive as a well-formed job of its own ending in `net`
        self.laptop()
        t = self.tree
        for name in (f"c {t} 60 dHJ1ZQ== - net\njunk", "c\rx", "c x", "../c"):
            with self.assertRaisesRegex(RUN.Unrunnable, "not a check name"):
                RUN.laptop_argv(chk(name=name), t, "core/")
        with self.assertRaisesRegex(RUN.Unrunnable, "whitespace"):     # any other word with whitespace in it
            RUN.laptop_argv(chk(), t + "\nx", "core/")
        argv = RUN.laptop_argv(chk(name="unit-tests_2.x+y"), t, "core/")   # an ordinary name still goes
        self.assertEqual(argv[argv.index("job") + 1], "unit-tests_2.x+y")

    @unittest.skipUnless(HAS_BWRAP, "no working bwrap on this machine")
    def test_the_laptop_round_trip_gives_every_job_a_fresh_home(self):
        self.laptop()
        write(self.tmp, {"loadavg": "0.00 0.00 0.00 1/1 1\n"})
        env = self.shim("shim", self.forced(os.path.join(self.tmp, "nopower")))
        once = 'test ! -e "$HOME/seen" && touch "$HOME/seen" && test -x core/bin/tool && echo "0 failed"'
        with mock.patch.dict(os.environ, env):
            a = self.run_(chk(run=once, where=["box", "laptop"]), where="laptop")
            b = self.run_(chk(run=once, where=["box", "laptop"]), where="laptop")
            red = self.run_(chk(run="echo FAIL x; exit 1", where=["laptop"]), where="laptop")
            capped = self.run_(chk(run="sleep 30", where=["laptop"], cap=1), where="laptop")
            # a host check gets a tmux `main` of the job's own and a waiting claude, as a suite on the runner does
            # (the e2e suites and check.sh lean on both); its own `exit` is still its verdict
            main = ('tmux has-session -t main && test -x "$HOME/.local/bin/claude" && echo "tmux=$TMUX_TMPDIR" '
                    '&& echo "0 failed"')
            host = self.run_(chk(run=main, klass=T.HOST, where=["laptop"]), where="laptop")
            host_red = self.run_(chk(run="exit 3", klass=T.HOST, where=["laptop"]), where="laptop")
            bare = self.run_(chk(run='test -x "$HOME/.local/bin/claude"', where=["laptop"]), where="laptop")
            box = self.run_(chk(run="true", klass=T.BOX, where=["laptop"]), where="laptop")
        self.assertEqual((a.status, b.status), (T.PASSED, T.PASSED), (a.extra, b.extra))
        self.assertEqual(red.status, T.FAILED, red.extra)
        self.assertEqual(capped.status, T.UNRUNNABLE, capped.extra)
        self.assertEqual(host.status, T.PASSED, host.extra)
        self.assertTrue(host.runner.startswith("laptop:"), host.runner)
        # its tmux server is the job's own, never this machine's `main`, and it went with the job's directory
        self.assertIn(f"tmux={self.tmp}/runner/job.", "\n".join(host.extra["tail"]))
        self.assertEqual((host_red.status, host_red.extra["rc"]), (T.FAILED, 3))
        self.assertEqual(bare.status, T.FAILED, bare.extra)          # only a host check's line brings the prep
        self.assertEqual(box.status, T.UNRUNNABLE)                   # a box check never leaves the box
        self.assertIn("does not leave the box", box.extra["why"])
        self.assertEqual([f for f in os.listdir(os.path.join(self.tmp, "runner")) if f.startswith("job.")], [])
        os.remove(os.path.join(self.tmp, "suites", "remote"))
        self.assertEqual(self.run_(chk(where=["laptop"]), where="laptop").status, T.UNRUNNABLE)

    @unittest.skipUnless(HAS_BWRAP, "no working bwrap on this machine")
    def test_a_laptop_on_battery_runs_it_and_a_busy_one_is_unrunnable_so_the_box_runs_it(self):
        self.laptop()
        power = os.path.join(self.tmp, "power")
        write(power, {"AC/type": "Mains\n", "AC/online": "0\n"})
        write(self.tmp, {"loadavg": "0.00 0.00 0.00 1/1 1\n"})
        env = self.shim("shim2", self.forced(power))
        c = chk(run="echo ran", where=["box", "laptop"])
        with mock.patch.dict(os.environ, env):
            r = self.run_(c, where="laptop")                 # battery is no reason to refuse (#793)
            self.assertEqual(r.status, T.PASSED, r.extra)
            self.assertIn("ran", r.extra["tail"])
            write(power, {"AC/online": "1\n"})
            write(self.tmp, {"loadavg": "999.00 0.00 0.00 1/1 1\n"})
            r = self.run_(c, where="laptop")
            self.assertEqual(r.status, T.UNRUNNABLE, r.extra)
            self.assertIn("busy (load 999.00", r.extra["why"])
            seen = []

            def runner(check, tree, where, **kw):
                seen.append(where)
                return self.run_(check, where=where) if where == "laptop" else \
                    T.Result(check=check.name, tree=tree, status=T.PASSED, runner="box")
            # judge() takes that as no answer and runs it on the box: neither red nor held
            o = RUN.judge(c, self.tree, "", "laptop", runner=runner)
        self.assertEqual((o.status, seen), (T.PASSED, ["laptop", "box"]))
        self.assertIn("busy", o.results[0].extra["laptop"])
        o = RUN.judge(chk(where=["laptop"]), self.tree, "", "laptop",
                      runner=lambda *a, **k: T.Result(check="c", tree="t", status=T.UNRUNNABLE, extra={"why": "x"}))
        self.assertEqual(o.status, T.UNRUNNABLE)             # a check the box may not run stays unrunnable

    def test_the_runner_job_refuses_what_is_not_a_job(self):
        t = "a" * 40
        for cmd in ("job ../x " + t + " 5 dHJ1ZQ== -", "job c nottree 5 dHJ1ZQ== -", "job c " + t + " 5 dHJ1ZQ== Li4v",
                    "job c " + t + " 5 dHJ1ZQ== Lw==", "job c " + t + " x dHJ1ZQ== -", "job c " + t + " 5"):
            p = subprocess.run(["bash", f"{RUN.BIN}/cc-suites", "runner"], capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, env={**os.environ, "SSH_ORIGINAL_COMMAND": cmd,
                                                              "CC_SUITES_RUNNER_DIR": self.tmp + "/r"})
            self.assertEqual(p.returncode, 2, (cmd, p.stdout))
            self.assertIn("refused", p.stdout)

    def test_job_serve_refuses_what_is_not_a_job(self):
        # job-serve hands a job to cc-suites runner, the one caged runner, and takes nothing else (a suite `run`)
        for cmd in ("run x", "status", "job ../x " + "a" * 40 + " 5 dHJ1ZQ== -", "job c nottree 5 dHJ1ZQ== -",
                    "job c " + "a" * 40 + " 5 dHJ1ZQ== Li4v"):
            with mock.patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": cmd, "CC_SUITES_RUNNER_DIR": self.tmp + "/r"}), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(RUN.cmd_job_serve([]), 2, cmd)
            self.assertIn("refused", out.getvalue())

    def test_job_serve_refuses_a_second_line_before_the_runner_sees_it(self):
        # the runner reads only the first line, so a job with a \n or \r in it is refused whole, and nothing runs
        t = "a" * 40
        for cmd in (f"job c {t} 60 dHJ1ZQ== - net\njunk", f"job c\njob c {t} 60 dHJ1ZQ== - net",
                    f"job c {t} 60 dHJ1ZQ== -\r"):
            with mock.patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": cmd}), \
                    mock.patch.object(RUN.subprocess, "run", side_effect=AssertionError("the runner ran")), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(RUN.cmd_job_serve([]), 2, repr(cmd))
            self.assertIn("refused", out.getvalue())

    def test_laptop_verdict_is_the_one_last_line_whatever_the_job_printed(self):
        v = "lander-job: verdict exit="
        self.assertEqual(RUN._laptop_verdict(f"| ok\n{v}3\n", 0), ("ok", 3))
        # a fake verdict behind \r, U+2028 or \x85 stays inside its `| ` line: splitlines would have broken it out
        for sep in ("\r", " ", "\x85", "\x0b"):
            self.assertEqual(RUN._laptop_verdict(f"| x{sep}{v}0\n{v}1\n", 0)[1], 1, repr(sep))
        # a verdict glued onto the job's unterminated last line, or a second one, or one not last: no answer
        self.assertEqual(RUN._laptop_verdict(f"| x{v}1\n", 0)[1], -1)
        self.assertEqual(RUN._laptop_verdict(f"{v}0\n| x\n{v}1\n", 0)[1], -1)
        self.assertEqual(RUN._laptop_verdict(f"{v}0\n| x\n", 0)[1], -1)
        self.assertEqual(RUN._laptop_verdict(f"| x\n{v}0\r\n", 0)[1], -1)
        self.assertEqual(RUN._laptop_verdict(f"| x\n{v}0\n", 255)[1], -1)

    def test_a_served_job_is_caged_and_cannot_change_the_runner_or_its_verdict(self):
        # the security read of #806: a job is a PR's code, run as the runner's own account. It must not write the
        # runner, or its verdict, or a later job could be told it passed. The fixture stands outside any tmp dir,
        # which the cage replaces, so the job sees it and meets a read-only file, not a missing one.
        if subprocess.run(["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "true"],
                          capture_output=True).returncode:
            self.skipTest("no bwrap that runs here, so the runner takes no job at all (its selfcheck proves that)")
        cage = tempfile.mkdtemp(prefix=".cc-suites-cage.", dir=os.path.expanduser("~"))
        self.addCleanup(shutil.rmtree, cage, True)
        inst = os.path.join(cage, "cc-suites")
        write(cage, {"cc-suites": "installed-runner\n"})
        line = (f"grep -q installed-runner {inst} && echo SAW; echo forged >> {inst} && echo WROTE; "
                "echo 'lander-job: verdict exit=0'; echo own > core/own && echo OWN; exit 1")
        tar = os.path.join(self.tmp, "tree.tar")
        with open(tar, "wb") as fh:
            subprocess.run(["git", "-C", self.repo, "archive", self.tree], stdout=fh, check=True)
        b = lambda x: base64.b64encode(x.encode()).decode()   # noqa: E731
        cmd = f"job c {self.tree} 60 {b(line)} -"
        with open(tar, "rb") as fh, mock.patch.object(sys, "stdin", mock.Mock(buffer=fh)), \
                mock.patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": cmd, "CC_SUITES_RUNNER_DIR": self.tmp + "/r",
                                             "CC_SUITES_POWER_DIR": self.tmp + "/nopower",
                                             "CC_SUITES_LOADAVG": self.tmp + "/loadavg"}), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            write(self.tmp, {"loadavg": "0.00 0.00 0.00 1/1 1\n"})
            rc = RUN.cmd_job_serve([])
        text = out.getvalue()
        body, verdict = RUN._laptop_verdict(text, rc)
        self.assertEqual((rc, verdict), (0, 1), text)                  # the job's own exit, not the one it printed
        self.assertIn("SAW", body.splitlines())                        # it could read the runner…
        self.assertIn("OWN", body.splitlines())                        # …and write its own tree…
        self.assertNotIn("WROTE", body)                                # …but not the runner
        with open(inst) as f:
            self.assertEqual(f.read(), "installed-runner\n")

    def test_manifest_widen_runs_in_process_on_two_trees(self):
        write(self.repo, {"tests/LANDING.toml": '[[check]]\nname="x"\nrun="true"\n'})
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "m")
        base = RUN.tree_of(self.repo, "HEAD")
        write(self.repo, {"tests/LANDING.toml": ""})
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "drop")
        head = RUN.tree_of(self.repo, "HEAD")
        b = M.builtin_check()
        self.assertEqual(RUN.run(b, head, repo_root=self.repo, base_tree=base).status, T.FAILED)
        self.assertEqual(RUN.run(b, base, repo_root=self.repo, base_tree=base).status, T.PASSED)
        self.assertEqual(RUN.run(b, head, repo_root=self.repo).status, T.UNRUNNABLE)


class Admission(unittest.TestCase):
    def psi_dir(self, mem, cpu):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        for k, v in (("memory", mem), ("cpu", cpu)):
            with open(os.path.join(d, k), "w") as f:
                f.write(f"some avg10={v} avg60=0 avg300=0 total=1\nfull avg10=0 avg60=0 avg300=0 total=0\n")
        return d

    def setUp(self):
        # a calm load average of the case's own: the box's real one must never decide a case
        self.calm_load = self.loadavg(0.0)
        p = mock.patch.object(A, "LOADAVG", self.calm_load)
        p.start()
        self.addCleanup(p.stop)

    def loadavg(self, l1):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "w") as f:
            f.write(f"{l1} 0.00 0.00 1/1 1\n")
        self.addCleanup(os.unlink, path)
        return path

    def test_pressure_throttles_and_never_to_zero(self):
        calm = self.calm_load
        self.assertEqual(A.slots_now(self.psi_dir(1.0, 50.0), 3, calm), 3)
        self.assertEqual(A.slots_now(self.psi_dir(1.0, 1.0), 0, calm), 1)

    def test_cpu_pressure_or_load_leaves_two_slots(self):
        calm, n = self.calm_load, os.cpu_count() or 1
        hot = self.loadavg(2.0 * n)
        cpu = self.psi_dir(1.0, 99.9)
        self.assertIn("pressure", A.overloaded(cpu, calm))           # the reason line its callers print is kept
        self.assertEqual(A.slots_now(cpu, 3, calm), 2)
        self.assertEqual(A.slots_now(self.psi_dir(0, 0), 3, hot), 2)
        self.assertEqual(A.slots_now(cpu, 1, hot), 1)                # never more than k

    def test_memory_pressure_keeps_one_slot(self):
        # the memory limit is there because parallel checks ran the box out of memory: one at a time, cpu or not
        calm, n = self.calm_load, os.cpu_count() or 1
        hot = self.loadavg(2.0 * n)
        self.assertEqual(A.slots_now(self.psi_dir(40.0, 50.0), 3, calm), 1)
        self.assertEqual(A.slots_now(self.psi_dir(40.0, 99.9), 3, hot), 1)
        self.assertIn("pressure", A.overloaded(self.psi_dir(40.0, 0), calm))
        self.assertEqual(A.psi("memory", "/nonexistent"), 0.0)

    def test_slots_admit_k_then_wait_and_alone_takes_them_all(self):
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        calm = self.psi_dir(0, 0)
        with A.slot(st, psi_root=calm, k=2) as a, A.slot(st, psi_root=calm, k=2) as b:
            self.assertEqual(sorted(a + b), [1, 2])
            with self.assertRaises(TimeoutError):
                with A.slot(st, psi_root=calm, k=2, poll=0.05, deadline=0.2, say=lambda _: None):
                    pass
        with A.slot(st, psi_root=calm, k=2) as a:
            with self.assertRaises(TimeoutError):
                with A.slot(st, alone=True, psi_root=calm, k=2, poll=0.05, deadline=0.2, say=lambda _: None):
                    pass
        with A.slot(st, alone=True, psi_root=calm, k=2) as held:
            self.assertEqual(held, [1, 2])

    def test_alone_takes_slots_in_order_and_holds_none_past_a_busy_one(self):
        # one lane runs several checks at once: two alone runs each holding a slot would wait on each other forever
        import threading
        import time
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        calm = self.psi_dir(0, 0)
        with A.slot(st, psi_root=calm, k=2) as one:   # slot 1 is busy
            self.assertEqual(one, [1])
            waiting = threading.Thread(target=lambda: self.assertRaises(
                TimeoutError, lambda: A.slot(st, alone=True, psi_root=calm, k=2, poll=0.05, deadline=0.6,
                                             say=lambda _: None).__enter__()))
            waiting.start()
            time.sleep(0.2)   # the alone run is polling now
            with open(os.path.join(st, "slots", "slot.2"), "a") as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)   # raises if the waiting alone run sat on slot 2
                fcntl.flock(f, fcntl.LOCK_UN)
            waiting.join()
        with A.slot(st, alone=True, psi_root=calm, k=2) as held:   # both free: it takes both, in order
            self.assertEqual(held, [1, 2])

    def _waiter(self, st, said, got, **kw):
        """A check waiting in another thread, as a worker's green run does beside the lane: it holds what it gets
        until `got` is set back."""
        import threading

        def go():
            with A.slot(st, poll=0.02, deadline=5, say=said.append, **kw) as held:
                got["held"] = held
                got["in"].set()
                got["out"].wait(5)
        got.update({"in": threading.Event(), "out": threading.Event()})
        t = threading.Thread(target=go)
        t.start()
        return t

    def _until(self, cond, secs=3.0):
        import time
        end = time.monotonic() + secs
        while not cond() and time.monotonic() < end:
            time.sleep(0.01)
        return cond()

    def test_a_waiting_run_gets_the_slot_before_the_lane_takes_it_back(self):
        # brief: "a waiting green run getting a slot while a lane holds one", and "a log line written while it waits"
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        hot = self.psi_dir(90, 0)   # memory pressure: slot 1 alone admits
        said, got = [], {}
        lane = A.slot(st, psi_root=hot, k=3)
        self.assertEqual(lane.__enter__(), [1])
        t = self._waiter(st, said, got, psi_root=hot, k=3, who="green@abc")
        self.assertTrue(self._until(lambda: said))   # it says so while it waits, not after
        self.assertRegex(said[0], r"green@abc waiting since \d\d:\d\dZ \(0 min\) for one of slots 1-1 \(load admits 1 of 3\); 0 waiting")
        self.assertFalse(got["in"].is_set())
        lane.__exit__(None, None, None)
        # the lane comes straight back for a slot: it waits behind the green run instead of taking slot 1 again
        with self.assertRaises(TimeoutError):
            with A.slot(st, psi_root=hot, k=3, poll=0.02, deadline=0.3, say=lambda _: None):
                pass
        self.assertTrue(got["in"].wait(3))
        self.assertEqual(got["held"], [1])
        got["out"].set()
        t.join()
        with A.slot(st, psi_root=hot, k=3, deadline=1) as again:   # and once it is done, the lane's turn comes
            self.assertEqual(again, [1])
        self.assertEqual([n for n in os.listdir(os.path.join(st, "slots", "queue"))], [])   # no ticket left behind

    def test_an_alone_wait_is_not_starved_by_checks_that_keep_taking_slots(self):
        # brief: "an alone=True wait that isn't blocked forever by in-order slots"
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        calm = self.psi_dir(0, 0)
        one, two = A.slot(st, psi_root=calm, k=2), A.slot(st, psi_root=calm, k=2)
        self.assertEqual(one.__enter__() + two.__enter__(), [1, 2])
        said, got = [], {}
        t = self._waiter(st, said, got, alone=True, psi_root=calm, k=2)
        self.assertTrue(self._until(lambda: said))
        self.assertIn("for all 2 slots (alone)", said[0])
        one.__exit__(None, None, None)
        # slot 1 freed: a check that came later does not get it, so the alone run is not passed over
        with self.assertRaises(TimeoutError):
            with A.slot(st, psi_root=calm, k=2, poll=0.02, deadline=0.3, say=lambda _: None):
                pass
        self.assertFalse(got["in"].is_set())   # still waiting for slot 2, and holding slot 1 meanwhile
        two.__exit__(None, None, None)
        with self.assertRaises(TimeoutError):   # slot 2 freed: still nobody else's
            with A.slot(st, psi_root=calm, k=2, poll=0.02, deadline=0.3, say=lambda _: None):
                pass
        self.assertTrue(got["in"].wait(3))
        self.assertEqual(got["held"], [1, 2])
        got["out"].set()
        t.join()

    def test_a_dead_waiters_ticket_holds_nobody_up(self):
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        q = os.path.join(st, "slots", "queue")
        os.makedirs(q)
        dead = os.path.join(q, f"{1:020d}-1-0000dead")   # older than any live wait, and nobody holds its lock
        open(dead, "a").close()
        with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, deadline=1, say=lambda _: None) as held:
            self.assertEqual(held, [1])
        self.assertFalse(os.path.exists(dead))
        import time
        live = open(os.path.join(q, f"{time.time_ns() - 120 * 10**9:020d}-4242-0000beef"), "a")   # a live waiter ahead
        fcntl.flock(live, fcntl.LOCK_EX)
        self.addCleanup(live.close)
        said = []

        def say(line):
            said.append(line)
            raise BrokenPipeError("stderr is gone")   # and a gone stderr does not take the wait down
        with self.assertRaises(TimeoutError):
            with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, poll=0.02, deadline=0.2, say=say):
                pass
        self.assertTrue(os.path.exists(live.name))   # kept, and it goes first
        self.assertIn("1 waiting ahead of it, the oldest pid 4242, 2 min", said[0])

    def test_a_stopped_waiter_is_passed_after_the_cap_and_said(self):
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        q = os.path.join(st, "slots", "queue")
        os.makedirs(q)
        stuck = open(os.path.join(q, f"{10**9:020d}-77-5e1f5e1f"), "a")   # locked since 1970: a SIGSTOPped waiter
        fcntl.flock(stuck, fcntl.LOCK_EX)
        self.addCleanup(stuck.close)
        said = []
        with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, deadline=1, say=said.append) as held:
            self.assertEqual(held, [1])
        self.assertEqual(len(said), 1)
        self.assertRegex(said[0], r"no longer waits on ticket \d+-77-5e1f5e1f \(pid 77, \d+ min\): older than 12 h")

    def test_a_stuck_ticket_is_said_once_however_long_the_wait(self):
        # slot 1 stays busy across many polls: the stuck ticket is passed each time but said only the first; and a
        # closed stderr (ValueError, not OSError) does not take the wait down
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        q = os.path.join(st, "slots", "queue")
        os.makedirs(q)
        stuck = open(os.path.join(q, f"{10**9:020d}-77-5e1f5e1f"), "a")
        fcntl.flock(stuck, fcntl.LOCK_EX)
        self.addCleanup(stuck.close)
        hot = self.psi_dir(90, 0)   # memory pressure: slot 1 alone admits
        lane = A.slot(st, psi_root=hot, k=3, deadline=1, say=lambda _: None)
        self.assertEqual(lane.__enter__(), [1])
        self.addCleanup(lane.__exit__, None, None, None)
        said = []

        def say(line):
            said.append(line)
            raise ValueError("I/O operation on closed file")
        with self.assertRaises(TimeoutError):
            with A.slot(st, psi_root=hot, k=3, poll=0.02, deadline=0.3, say=say):
                pass
        self.assertEqual(len([s for s in said if "no longer waits" in s]), 1)
        self.assertEqual(len([s for s in said if "waiting since" in s]), 1)   # WAIT_SAY is 600 s: said once too

    def test_a_name_no_ticket_has_holds_nobody_up_and_is_never_said(self):
        # a locked '!hold' sorts before every real ticket; taken for one, it blocked every waiter with no cap
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        q = os.path.join(st, "slots", "queue")
        os.makedirs(q)
        for name in ("!hold", f"{1:020d}-1-nothex!!", f"{1:020d}-1-0000beef\nforged", f".new-{1:020d}-x-00000001"):
            f = open(os.path.join(q, name), "a")
            fcntl.flock(f, fcntl.LOCK_EX)
            self.addCleanup(f.close)
        said = []
        with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, poll=0.02, deadline=0.3, say=said.append) as held:
            self.assertEqual(held, [1])
        self.assertEqual(said, [])

    def test_out_of_fds_a_ticket_ahead_keeps_its_place(self):
        # EMFILE, ENFILE or ENOMEM opening a live ticket says nothing about the ticket: it is counted, never removed
        import errno
        import time
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        q = os.path.join(st, "slots", "queue")
        os.makedirs(q)
        ahead = f"{time.time_ns() - 60 * 10**9:020d}-4242-0000beef"
        live = open(os.path.join(q, ahead), "a")
        fcntl.flock(live, fcntl.LOCK_EX)
        self.addCleanup(live.close)
        real = os.open
        for e in (errno.EMFILE, errno.ENFILE, errno.ENOMEM):
            def fake(p, *a, e=e):
                if os.path.basename(p) == ahead:
                    raise OSError(e, os.strerror(e))
                return real(p, *a)
            with mock.patch.object(A.os, "open", side_effect=fake):
                n, oldest, stale = A._ahead(q, f"{time.time_ns():020d}-1-00000001")
            self.assertEqual((n, oldest, stale), (1, ahead, []), errno.errorcode[e])
            self.assertTrue(os.path.exists(live.name))
        real_flock = fcntl.flock

        def no_locks(fd, op):   # flock fails for want of a lock, not because the ticket is held
            raise OSError(errno.ENOLCK, os.strerror(errno.ENOLCK))
        dead = os.path.join(q, f"{time.time_ns() - 90 * 10**9:020d}-4343-0000dead")   # unlocked, but unknowable
        open(dead, "a").close()
        with mock.patch.object(A.fcntl, "flock", side_effect=no_locks):
            n, oldest, stale = A._ahead(q, f"{time.time_ns():020d}-1-00000001")
        self.assertEqual((n, oldest), (2, os.path.basename(dead)))
        self.assertTrue(os.path.exists(dead) and os.path.exists(live.name))
        self.assertIs(fcntl.flock, real_flock)

    def test_junk_in_the_queue_is_removed_never_waited_on_or_followed(self):
        import time
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        q = os.path.join(st, "slots", "queue")
        os.makedirs(q)
        old = f"{1:020d}"
        os.mkdir(os.path.join(q, f"{old}-1-00000001"))
        os.mkfifo(os.path.join(q, f"{old}-2-00000002"))   # open(p, "a") on this blocked in the kernel
        target = os.path.join(st, "planted")
        os.symlink(target, os.path.join(q, f"{old}-3-00000003"))   # followed, it made its target
        loop = os.path.join(q, f"{old}-4-00000004")
        os.symlink(loop, loop)
        shut = os.path.join(q, f"{old}-5-00000005")
        open(shut, "w").close()
        os.chmod(shut, 0)
        crashed = os.path.join(q, f".new-{old}-6-00000006")   # a crash between _ticket's open and its rename
        open(crashed, "w").close()
        os.utime(crashed, (time.time() - 600,) * 2)
        fresh = os.path.join(q, f".new-{time.time_ns():020d}-7-00000007")   # may be mid-rename: left alone
        open(fresh, "w").close()
        with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, deadline=1, say=lambda _: None) as held:
            self.assertEqual(held, [1])
        self.assertEqual(os.listdir(q), [os.path.basename(fresh)])
        self.assertFalse(os.path.lexists(target))

    def test_an_alone_waiter_lets_go_when_an_older_ticket_turns_up(self):
        # _ticket names a ticket before it is listed, so one can land older than the head: an alone waiter holding
        # slot 1 then waits on a waiter that needs slot 1, forever, unless it lets go
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        calm = self.psi_dir(0, 0)
        os.makedirs(os.path.join(st, "slots"))
        two = open(os.path.join(st, "slots", "slot.2"), "a")
        fcntl.flock(two, fcntl.LOCK_EX)   # slot 2 is busy
        self.addCleanup(two.close)
        said, got = [], {}
        t = self._waiter(st, said, got, alone=True, psi_root=calm, k=2)
        self.addCleanup(lambda: (got["out"].set(), t.join()))
        slot1 = os.path.join(st, "slots", "slot.1")

        def free(path):
            with open(path, "a") as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except BlockingIOError:
                    return False
        self.assertTrue(self._until(lambda: not free(slot1)))   # it took slot 1 and waits for slot 2
        q = os.path.join(st, "slots", "queue")
        (head,) = os.listdir(q)
        older_name = os.path.join(q, f"{int(head.split('-')[0]) - 1:020d}-1-00000001")   # just older than the head
        older = open(older_name, "a")
        fcntl.flock(older, fcntl.LOCK_EX)
        self.assertTrue(self._until(lambda: free(slot1)))   # it let slot 1 go to the older ticket
        older.close()
        os.unlink(older_name)
        two.close()
        self.assertTrue(got["in"].wait(3))
        self.assertEqual(got["held"], [1, 2])

    def test_under_pressure_only_slot_one_admits(self):
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        hot = self.psi_dir(90, 0)
        with A.slot(st, psi_root=hot, k=3) as a:
            self.assertEqual(a, [1])
            with self.assertRaises(TimeoutError):
                with A.slot(st, psi_root=hot, k=3, poll=0.05, deadline=0.2, say=lambda _: None):
                    pass

    def test_high_load_narrows_to_two_and_a_slot_still_admits(self):
        # the brief: "under a simulated high load a queued landing still starts" — two at a time, never none
        n = os.cpu_count() or 1
        calm_psi = self.psi_dir(0, 0)
        hot, calm = self.loadavg(2.0 * n), self.loadavg(2.0 * n - 0.5)
        self.assertIn(f"on {n} cores", A.overloaded(calm_psi, hot))
        self.assertEqual(A.overloaded(calm_psi, calm), "")
        self.assertEqual(A.slots_now(calm_psi, 3, hot), 2)
        self.assertEqual(A.slots_now(calm_psi, 3, calm), 3)
        self.assertEqual(A.overloaded(calm_psi, "/nonexistent"), "")
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        with A.slot(st, psi_root=calm_psi, k=3, loadavg=hot, deadline=1) as a, \
                A.slot(st, psi_root=calm_psi, k=3, loadavg=hot, deadline=1) as b:
            self.assertEqual((a, b), ([1], [2]))
            with self.assertRaises(TimeoutError):
                with A.slot(st, psi_root=calm_psi, k=3, loadavg=hot, poll=0.05, deadline=0.2, say=lambda _: None):
                    pass
            with A.slot(st, psi_root=calm_psi, k=3, loadavg=calm, deadline=1) as c:
                self.assertEqual(c, [3])

    def test_a_busy_run_is_not_niced_down(self):
        with mock.patch.object(A, "scope_available", return_value=True), \
                mock.patch.object(A.shutil, "which", return_value="/usr/bin/ionice"):
            argv, _ = A.wrap(chk(klass=T.HERMETIC), ["x"], busy=True)
            self.assertNotIn("nice", argv)
            self.assertEqual(argv[-4:], ["ionice", "-c2", "-n0", "x"])
            argv, _ = A.wrap(chk(klass=T.HERMETIC), ["x"], busy=False)
            self.assertEqual(argv[-4:], ["nice", "-n", "10", "x"])

    def test_wrap_puts_the_run_in_a_scope_and_nices_only_the_sandboxed(self):
        with mock.patch.object(A, "scope_available", return_value=True):
            argv, how = A.wrap(chk(klass=T.HERMETIC), ["x"])
            self.assertEqual(how, "scope")
            self.assertIn("--slice=lander.slice", argv)
            self.assertIn(f"MemoryMax={A.MEM_MAX}", argv)
            self.assertEqual(argv[-4:], ["nice", "-n", "10", "x"])
            argv, _ = A.wrap(chk(klass=T.HOST), ["x"])
            self.assertEqual(argv[-2:], ["--", "x"])
        with mock.patch.dict(os.environ, {"LANDER_SCOPE": "0"}):
            self.assertEqual(A.wrap(chk(klass=T.HOST), ["x"]), (["x"], "noscope"))


class Store(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = d.name
        os.makedirs(os.path.join(self.root, "lanes"))
        self.lock = open(os.path.join(self.root, "lanes", "repo.lock"), "a")
        self.addCleanup(self.lock.close)
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.r = T.Result(check="c", tree="a" * 40, status=T.PASSED)

    def test_only_the_lane_writes(self):
        with self.assertRaises(REC.NotTheLane):
            REC.Store("repo", None, self.root).put("repo-1", self.r)
        other = open(os.path.join(self.root, "lanes", "repo.lock"), "a")   # another holder's view of the lock
        self.addCleanup(other.close)
        with self.assertRaises(REC.NotTheLane):
            REC.Store("repo", other, self.root).put("repo-1", self.r)
        s = REC.Store("repo", self.lock, self.root)
        self.assertEqual(s.put("repo-1", self.r), "c/" + "a" * 40)
        self.assertEqual(s.get("repo-1", "c", "a" * 40).status, T.PASSED)
        self.assertIsNone(s.get("repo-2", "c", "a" * 40))   # one job's run is not another's

    def test_a_shared_base_run_is_reused_only_at_this_release_and_nonce(self):
        s = REC.Store("repo", self.lock, self.root)
        with self.assertRaises(REC.NotTheLane):   # no lane nonce yet
            s.put_base(self.r)
        REC.new_nonce("repo", self.root)
        s.put_base(self.r)
        self.assertIsNotNone(s.base("c", "a" * 40))
        s.release = "another-release"
        self.assertIsNone(s.base("c", "a" * 40))
        s.release = REC.release()
        REC.new_nonce("repo", self.root)            # a new lane: every earlier shared run is stale
        self.assertIsNone(s.base("c", "a" * 40))

    def test_names_that_would_leave_the_store_are_refused(self):
        s = REC.Store("repo", self.lock, self.root)
        with self.assertRaises(ValueError):
            s.put("../x", self.r)
        with self.assertRaises(ValueError):
            REC.Store("../repo")

    def test_the_red_record_goes_once_by_the_shared_key_and_never_raises(self):
        b = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(b))
        out = os.path.join(b, "args")
        with open(os.path.join(b, "cc-failures"), "w") as f:
            f.write(f'#!/bin/sh\nprintf "%s\\n" "$@" > {out}\necho "recorded F-1"\n')
        os.chmod(os.path.join(b, "cc-failures"), 0o755)
        r = T.Result(check="c", tree="b" * 40, status=T.FAILED, cases=[{"name": "FAIL one", "status": T.FAILED}])
        word = REC.record_red("repo", r, "text", pr=7, bin_dir=b)
        self.assertEqual(word, "recorded recorded F-1")
        with open(out) as f:
            args = f.read().splitlines()
        for want in ("record", "--once", "gate-verdict/red", "source=gate:c:" + "b" * 12, "pr=7"):
            self.assertIn(want, args)
        self.assertTrue(any("FAIL one" in a for a in args))
        with open(os.path.join(b, "cc-failures"), "w") as f:
            f.write("#!/bin/sh\necho nope >&2; exit 3\n")
        self.assertTrue(REC.record_red("repo", r, "t", bin_dir=b).startswith("not recorded"))
        self.assertTrue(REC.record_red("repo", r, "t", bin_dir=b + "/gone").startswith("not recorded"))


class Quarantine(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 27)

    def test_only_live_rows_count(self):
        text = ("# comment\n"
                "tool\tflaky text\twhy\towner\t2026-10-20\n"
                "tool\texpired\twhy\towner\t2026-09-26\n"
                "tool\ttoo far\twhy\towner\t2027-01-01\n"
                "tool\tno date\twhy\towner\tsoon\n"
                "tool\ttoday\twhy\towner\t2026-09-27\n")
        self.assertEqual(REC.quarantine_rows(text, self.TODAY), [("tool", "flaky text"), ("tool", "today")])

    def test_every_red_line_must_match_a_row_of_this_check(self):
        c = chk(name="selfcheck-tool", paths=["core/bin/tool"])
        rows = [("tool", "flaky text"), ("other", "boom")]
        self.assertTrue(REC.quarantined(c, ["FAIL: flaky text here"], rows))
        self.assertFalse(REC.quarantined(c, ["FAIL: flaky text here", "FAIL: real"], rows))
        self.assertFalse(REC.quarantined(c, ["FAIL boom"], rows))          # another tool's row
        self.assertFalse(REC.quarantined(c, [], rows))                     # a red with no lines is not quarantined


class Judge(unittest.TestCase):
    """judge() with a scripted runner: statuses by (tree, alone)."""

    def runner(self, script, loaded=False):
        calls = []

        def run(check, tree, where, alone=False, **kw):
            calls.append((tree, alone))
            st = script[(tree, alone)] if (tree, alone) in script else script[tree]
            return T.Result(check=check.name, tree=tree, status=st,
                            cases=[{"name": "FAIL flaky text", "status": T.FAILED}] if st == T.FAILED else [],
                            extra={"loaded": loaded, "why": st})
        return run, calls

    H, B = "h" * 40, "b" * 40

    def test_a_laptop_red_is_said_again_by_the_box(self):
        seen = []

        def run(check, tree, where, alone=False, **kw):
            seen.append(where)
            st = T.FAILED if where == "laptop" else T.PASSED
            return T.Result(check=check.name, tree=tree, status=st, extra={"why": where})
        o = RUN.judge(chk(where=["box", "laptop"]), self.H, self.B, "laptop", runner=run)
        self.assertEqual((o.status, seen), (T.PASSED, ["laptop", "box"]))
        self.assertEqual(o.results[0].extra["laptop_red"], "laptop")
        # a laptop-only check has no box to ask, so its red stands
        seen.clear()
        o = RUN.judge(chk(where=["laptop"]), self.H, "", "laptop", runner=run, on_base=False)
        self.assertEqual((o.status, seen), (T.FAILED, ["laptop"]))

    def test_a_box_red_under_load_is_never_overturned_by_the_laptop(self):
        seen = []

        def run(check, tree, where, alone=False, **kw):
            seen.append((where, alone))
            st = T.PASSED if (where == "laptop" and alone) else T.FAILED
            return T.Result(check=check.name, tree=tree, status=st, extra={"why": where, "loaded": True})
        o = RUN.judge(chk(where=["box", "laptop"]), self.H, "", "laptop", runner=run, on_base=False)
        self.assertEqual(o.status, T.FAILED)
        self.assertNotIn(("laptop", True), seen)

    def test_green_runs_once(self):
        run, calls = self.runner({self.H: T.PASSED})
        self.assertEqual(RUN.judge(chk(), self.H, self.B, runner=run).status, T.PASSED)
        self.assertEqual(calls, [(self.H, False)])

    def test_unrunnable_is_never_red_and_records_nothing(self):
        run, calls = self.runner({self.H: T.UNRUNNABLE})
        rec = mock.Mock()
        self.assertEqual(RUN.judge(chk(), self.H, self.B, runner=run, record=rec).status, T.UNRUNNABLE)
        self.assertEqual(len(calls), 1)
        rec.assert_not_called()

    def test_red_on_the_base_too_is_main_and_not_blamed(self):
        run, calls = self.runner({self.H: T.FAILED, self.B: T.FAILED})
        rec = mock.Mock()
        o = RUN.judge(chk(name="c"), self.H, self.B, runner=run, record=rec)
        self.assertEqual((o.status, o.note), (RUN.BLOCKED, "blocked-by-main:c"))
        rec.assert_not_called()

    def test_the_base_run_is_shared_through_the_lanes_store(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        os.makedirs(os.path.join(d, "lanes"))
        lock = open(os.path.join(d, "lanes", "repo.lock"), "a")
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        REC.new_nonce("repo", d)
        store = REC.Store("repo", lock, d)
        run, calls = self.runner({self.H: T.FAILED, self.B: T.FAILED})
        RUN.judge(chk(), self.H, self.B, runner=run, store=store, job_key="repo-1")
        RUN.judge(chk(), self.H, self.B, runner=run, store=store, job_key="repo-2")
        self.assertEqual(calls.count((self.B, False)), 1)     # the second job read the lane's base run
        self.assertIsNotNone(store.get("repo-1", "c", self.H))

    def test_a_red_under_load_gets_one_rerun_alone(self):
        run, calls = self.runner({(self.H, False): T.FAILED, (self.H, True): T.PASSED, self.B: T.PASSED},
                                 loaded=True)
        o = RUN.judge(chk(), self.H, self.B, runner=run)
        self.assertEqual((o.status, o.note[:5]), (T.PASSED, "flaky"))
        self.assertEqual(calls, [(self.H, False), (self.B, False), (self.H, True)])

    def store(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        os.makedirs(os.path.join(d, "lanes"))
        lock = open(os.path.join(d, "lanes", "repo.lock"), "a")
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        REC.new_nonce("repo", d)
        return REC.Store("repo", lock, d)

    def test_a_base_red_under_load_is_rerun_alone_and_only_the_rerun_is_shared(self):
        store = self.store()
        calls = []

        def run(check, tree, where, alone=False, **kw):
            calls.append((tree, alone))
            st = T.PASSED if (tree, alone) == (self.B, True) else T.FAILED
            return T.Result(check=check.name, tree=tree, status=st, extra={"loaded": not alone, "why": st})
        o = RUN.judge(chk(), self.H, self.B, runner=run, store=store, job_key="repo-1")
        self.assertEqual(calls[:3], [(self.H, False), (self.B, False), (self.B, True)])
        self.assertNotEqual(o.status, RUN.BLOCKED)                # main is green alone, so the red is not main's
        self.assertEqual(store.base("c", self.B).status, T.PASSED)  # the loaded red was never shared

    def test_a_check_the_base_lacks_is_never_run_on_the_base_and_its_red_is_the_diffs(self):
        run, calls = self.runner({self.H: T.FAILED, self.B: T.FAILED})
        rec = mock.Mock()
        o = RUN.judge(chk(), self.H, self.B, runner=run, record=rec, on_base=False)
        self.assertEqual(o.status, T.FAILED)
        self.assertNotIn((self.B, False), calls)
        rec.assert_called_once()

    def test_run_plan_skips_the_base_for_a_check_or_run_file_the_base_lacks(self):
        from test_plan import Repo
        r = Repo(self)
        head = r.commit("head", {"core/tests/LANDING.toml": __import__("test_plan").CORE_MANIFEST
                                 + '\n[[check]]\nname = "new"\nrun = "tests/new.sh"\nclass = "hermetic"\n',
                                 "core/tests/new.sh": "exit 1\n", "core/bin/a": "#!/bin/sh\nexit 1\n"})
        m = M.widen(M.load(r.root, r.base), M.load(r.root, head, strict=False))
        base_m = M.load(r.root, r.base)
        self.assertFalse(RUN.runs_on_base(r.root, r.base, base_m, "new"))     # not in the base manifest
        self.assertTrue(RUN.runs_on_base(r.root, r.base, base_m, "a"))        # bin/a is there
        self.assertFalse(RUN.runs_on_base(r.root, r.base, base_m, "e2e-x"))   # tests/e2e/x.sh is not
        self.assertTrue(RUN.runs_on_base(r.root, r.base, base_m, "docs-lint"))  # no run file to miss
        run, calls = self.runner({head: T.FAILED, r.base: T.FAILED})
        outs = RUN.run_plan(r.root, m, T.Plan(checks=["new", "e2e-x", "a"]), ["core/tests/new.sh"], head, r.base,
                            runner=run)
        self.assertEqual((outs["new"].status, outs["e2e-x"].status), (T.FAILED, T.FAILED))
        self.assertEqual(outs["a"].status, RUN.BLOCKED)                # a base that has it still compares
        self.assertEqual(calls.count((r.base, False)), 1)

    def test_a_red_not_under_load_is_not_rerun_and_is_recorded_once(self):
        run, calls = self.runner({self.H: T.FAILED, self.B: T.PASSED})
        rec = mock.Mock()
        o = RUN.judge(chk(), self.H, self.B, runner=run, record=rec)
        self.assertEqual(o.status, T.FAILED)
        self.assertNotIn((self.H, True), calls)
        rec.assert_called_once()

    def test_quarantine_passes_a_matching_red_but_not_for_security_or_a_touched_check(self):
        rows = [("c", "flaky text")]
        run, _ = self.runner({self.H: T.FAILED, self.B: T.PASSED})
        self.assertEqual(RUN.judge(chk(), self.H, self.B, runner=run, quarantine=rows).note, "quarantined")
        self.assertEqual(RUN.judge(chk(), self.H, self.B, runner=run, quarantine=rows, security=True).status,
                         T.FAILED)
        self.assertEqual(RUN.judge(chk(), self.H, self.B, runner=run, quarantine=rows, touched=True).status,
                         T.FAILED)

    def test_run_plan_derives_security_and_touched_from_the_manifest(self):
        m = M.Manifest(checks={"guard": chk(name="guard", paths=["core/bin/guard"]),
                               "c": chk(name="c", paths=["core/bin/c"])},
                       cwd={"guard": "", "c": ""},
                       policy=T.Policy(gate_first=["core/bin/guard"]))
        plan = T.Plan(checks=["c", "guard", "gone"])
        run, _ = self.runner({self.H: T.FAILED, self.B: T.PASSED})
        q = "guard\tflaky text\tw\to\t2099-01-01\nc\tflaky text\tw\to\t2099-01-01\n"
        # self.B names no tree: a base whose objects git cannot read now raises, so its manifest is the empty one
        with mock.patch.object(REC, "quarantine_rows", return_value=[("guard", "flaky text"), ("c", "flaky text")]), \
                mock.patch.object(M, "load", return_value=M.Manifest()):
            outs = RUN.run_plan(".", m, plan, ["README.md"], self.H, self.B, runner=run, quarantine_text=q)
            self.assertEqual(outs["c"].note, "quarantined")
            self.assertEqual(outs["guard"].status, T.FAILED)         # guards a gate-first path
            self.assertEqual(outs["gone"].status, T.UNRUNNABLE)
            outs = RUN.run_plan(".", m, plan, ["core/bin/c"], self.H, self.B, runner=run, quarantine_text=q)
            self.assertEqual(outs["c"].status, T.FAILED)             # the change touches the check

    def test_after_one_laptop_no_answer_the_rest_of_the_plan_goes_to_the_box(self):
        m = M.Manifest(checks={n: chk(name=n, klass=T.STATIC, where=["box", "laptop"]) for n in ("a", "b")}, cwd={"a": "", "b": ""})
        seen = []

        def run(check, tree, where, alone=False, **kw):
            seen.append(where)
            st = T.UNRUNNABLE if where == "laptop" else T.PASSED
            return T.Result(check=check.name, tree=tree, status=st, extra={"why": "no answer"})
        with mock.patch.object(A, "busy", return_value=True), \
                mock.patch.object(RUN, "laptop_dest", return_value="ccsuite@r"):
            outs = RUN.run_plan(".", m, T.Plan(checks=["a", "b"]), ["README.md"], self.H, "", runner=run)
        self.assertEqual(seen, ["laptop", "box", "box"])
        self.assertEqual([outs[n].status for n in ("a", "b")], [T.PASSED, T.PASSED])

    def test_member_and_laptop_routing(self):
        c = chk(klass=T.STATIC, where=["box", "laptop"])
        self.assertEqual(RUN.choose_where(c, "ann"), "member:ann")
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        write(d.name, {"id_ed25519": "k\n", "remote": "ccsuite@r\n", "known_hosts": "r ssh-ed25519 AAAA\n"})
        p = mock.patch.dict(os.environ, {"CC_SUITES_DIR": d.name})
        p.start()
        self.addCleanup(p.stop)
        with mock.patch.object(A, "busy", return_value=True), mock.patch.object(A, "loaded", return_value=False):
            self.assertEqual(RUN.choose_where(c), "laptop")
            # busy, not saturated, is enough for the PR's code: hermetic and host go too
            self.assertEqual(RUN.choose_where(chk(klass=T.HERMETIC, where=["box", "laptop"])), "laptop")
            self.assertEqual(RUN.choose_where(chk(klass=T.HOST, where=["box", "laptop"])), "laptop")
            self.assertEqual(RUN.choose_where(chk(klass=T.HOST, where=["box"])), "box")     # needs this host
            for k in (T.BOX, T.TIMING):
                self.assertEqual(RUN.choose_where(chk(klass=k, where=["box", "laptop"])), "box")
        with mock.patch.object(A, "busy", return_value=False):
            # laptop first (owner 2026-09-29): a calm box still sends what may leave it; the box is the fallback
            self.assertEqual(RUN.choose_where(c), "laptop")
            self.assertEqual(RUN.choose_where(chk(klass=T.HOST, where=["box", "laptop"])), "laptop")
            # the lane saw the laptop give no answer a moment ago: the box takes it without waiting out ssh
            self.assertEqual(RUN.choose_where(c, box_only=True), "box")

    def test_a_busy_box_sends_check_sh_and_the_e2e_suites_and_keeps_what_needs_it(self):
        # the shipped manifests, as the lane reads them: the heavy host checks go, the ones bound to this host stay
        with open(os.path.join(CORE, "tests", "LANDING.toml")) as f:
            checks, faults = M.parse_checks(f.read())
        self.assertEqual(faults, [])
        by = {c.name: c for c in checks}
        e2e = [n for n in by if n.startswith("e2e-")]
        self.assertGreater(len(e2e), 10)
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        write(d.name, {"id_ed25519": "k\n", "remote": "ccsuite@r\n", "known_hosts": "r ssh-ed25519 AAAA\n"})
        with mock.patch.dict(os.environ, {"CC_SUITES_DIR": d.name}), \
                mock.patch.object(A, "busy", return_value=True), mock.patch.object(A, "loaded", return_value=False):
            for n in ["check-sh"] + e2e:
                self.assertEqual((n, RUN.choose_where(by[n])), (n, "laptop"))
            for n in ("selfcheck-cc-fence", "selfcheck-cc-sandbox", "selfcheck-lander"):
                self.assertEqual((n, RUN.choose_where(by[n])), (n, "box"))

    def test_a_busy_box_that_is_not_saturated_sends_to_the_laptop_and_keeps_its_slots(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        write(d.name, {"cpu": "some avg10=90.00 avg60=90.00 avg300=90.00 total=1\n",
                       "memory": "some avg10=0.00 avg60=0.00 avg300=0.00 total=1\n"})
        self.assertTrue(A.busy(d.name))
        self.assertFalse(A.loaded(d.name))
        self.assertEqual(A.slots_now(d.name, k=3, loadavg="/nonexistent"), 3)
        write(d.name, {"cpu": "some avg10=20.00 avg60=20.00 avg300=20.00 total=1\n"})
        self.assertFalse(A.busy(d.name, "/nonexistent"))
        # the box of 2026-09-29: cpu PSI near 38, load 9-27 on 6 cores, and 1 check of 200 went out
        write(d.name, {"cpu": "some avg10=38.00 avg60=38.00 avg300=38.00 total=1\n"})
        self.assertTrue(A.busy(d.name, "/nonexistent"))
        write(d.name, {"cpu": "some avg10=10.00 avg60=10.00 avg300=10.00 total=1\n"})
        n = os.cpu_count() or 1
        write(d.name, {"la": f"{n:.2f} 0 0 1/1 1\n", "la2": f"{n - 0.5:.2f} 0 0 1/1 1\n"})
        self.assertTrue(A.busy(d.name, os.path.join(d.name, "la")))      # a load of one per core is busy
        self.assertFalse(A.busy(d.name, os.path.join(d.name, "la2")))


@unittest.skipUnless(HAS_BWRAP, "no working bwrap on this machine")
class CheckFallback(Env):
    """A repo that ships no LANDING.toml is checked by the release's tests/landing-repos/<repo>.toml, the way the lane
    plans it (review of #771: without it every other repo planned with no checks). cc-green's worker green runs this."""

    def check(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = CK.cmd_check([self.repo, "--base", "base"])
        return rc, out.getvalue()

    def test_a_repo_without_a_manifest_gets_its_fallback(self):
        git(self.repo, "branch", "base")
        write(self.repo, {"core/bin/tool": "#!/bin/sh\necho tool again\n"})
        self.assertEqual(CK.repo_name(self.repo), "repo")
        fb = os.path.join(self.tmp, "release", "tests", "landing-repos")
        os.makedirs(fb)
        with mock.patch.object(M, "FALLBACK_DIR", fb):
            rc, out = self.check()
            self.assertEqual(rc, 0, out)
            self.assertNotIn("tip      e2e", out)             # no repo.toml in the release: nothing to fall back on
            write(fb, {"repo.toml": '[[check]]\nname = "e2e"\nrun = "true"\npaths = ["**"]\nclass = "box"\n'})
            rc, out = self.check()
            self.assertEqual(rc, 0, out)
            self.assertIn("tip      e2e", out)                # the release's fallback planned it
            # the PR's own tree cannot supply one: only the release's directory is read
            write(self.repo, {"tests/landing-repos/other.toml": '[[check]]\nname = "x"\nrun = "true"\n'})
            self.assertEqual(M.host_fallback("other"), "")
        self.assertEqual(M.host_fallback("../etc/passwd"), "")


class CheckCommand(Env):
    MANIFEST = textwrap.dedent('''
        [[check]]
        name = "tool"
        run = "bin/tool | grep -q tool"
        paths = ["bin/tool"]
        class = "hermetic"

        [[check]]
        name = "e2e"
        run = "true"
        paths = ["bin/tool"]
        class = "box"
    ''')

    def setUp(self):
        super().setUp()
        write(self.repo, {"core/tests/LANDING.toml": self.MANIFEST})
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "manifest")
        git(self.repo, "branch", "base")

    def check(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = CK.cmd_check([self.repo, "--base", "base"])
        return rc, out.getvalue()

    @unittest.skipUnless(HAS_BWRAP, "no working bwrap on this machine")
    def test_green_red_and_main_red(self):
        write(self.repo, {"core/bin/tool": "#!/bin/sh\necho tool again\n"})
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertIn("passed   tool", out)
        self.assertIn("tip      e2e", out)                 # box-class: listed, not run
        write(self.repo, {"core/bin/tool": "#!/bin/sh\necho FAIL nope\nexit 1\n"})
        rc, out = self.check()
        self.assertEqual(rc, 1, out)
        self.assertIn("RED      tool", out)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "break main")
        git(self.repo, "branch", "-f", "base")
        write(self.repo, {"core/bin/tool": "#!/bin/sh\necho FAIL still\nexit 1\n"})
        rc, out = self.check()
        self.assertEqual(rc, 0, out)                           # red on the base too: main's, said, not held
        self.assertIn("main-red", out)


class Sweep(unittest.TestCase):
    def rows(self, bwrap, host, tail=""):
        def run(check, tree, where, **kw):
            st = bwrap if check.klass != T.HOST else host
            return T.Result(check=check.name, tree=tree, status=st, extra={"tail": [tail], "why": ""})
        m = M.Manifest(checks={"x": chk(name="x", klass=T.HOST)}, cwd={"x": ""})
        return CK.sweep_one(".", m, "x", "t" * 40, True, runner=run)["verdict"]

    def test_the_acceptance_verdicts(self):
        home = os.path.expanduser("~")
        self.assertEqual(self.rows(T.PASSED, T.FAILED), "passes-in-bwrap")
        self.assertEqual(self.rows(T.FAILED, T.PASSED, f"{home}/.venv/bin/python: No such file"), "needs-mount")
        self.assertEqual(self.rows(T.FAILED, T.PASSED, "tmux: lost server"), "host")
        self.assertEqual(self.rows(T.FAILED, T.FAILED), "red")
        self.assertEqual(self.rows(T.UNRUNNABLE, T.UNRUNNABLE), "unrunnable")


if __name__ == "__main__":
    unittest.main()
