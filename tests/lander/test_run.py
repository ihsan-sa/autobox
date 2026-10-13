"""U2's run cases: the tree, the status rules, the sandbox, admission and scopes, the runners, the store, the
failures ledger, quarantine, judging a red against the base, and `lander check` / `lander sweep`.

    python3 -m unittest discover -s core/tests/lander -p 'test_run.py'

Cases that start bwrap or a systemd scope skip, saying so, on a machine without one. Every case uses its own
LANDER_STATE and its own git repo.
"""
import base64
import contextlib
import dataclasses
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
import time
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


def nnp(status: str) -> str:
    """The NoNewPrivs value out of a /proc/<pid>/status text, '' when it has none."""
    return next((ln.split(":", 1)[1].strip() for ln in status.splitlines() if ln.startswith("NoNewPrivs:")), "")


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
                                         "CC_SUITES_DIR": os.path.join(self.tmp, "suites"),
                                         # the host's checkouts are $CC_DEV/<repo> and the boards' paths (git.host_tree)
                                         "CC_DEV": self.tmp, "CC_BOARDS": os.path.join(self.tmp, "boards")})
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
                 # a passing check may quote the box-state text itself (cc-subject's /work-too-small case)
                 ((0, "cp: No space left on device\nok 25 passed, 0 failed"), T.PASSED),
                 ((0, "Cannot allocate memory\n3 failed"), T.FAILED),
                 ((0, "3 failed"), T.FAILED),
                 ((1, "bwrap: Can't mount proc on /newroot/proc"), T.UNRUNNABLE),
                 ((1, "Failed to connect to user scope bus via local transport"), T.UNRUNNABLE),
                 # no signal scope on the kernel: cc-nosignal refuses and nothing ran, so it isn't the tree's red
                 ((3, "cc-nosignal: Landlock ABI 5 has no signal scope — refused, nothing ran. A check here"), T.UNRUNNABLE),
                 ((0, "bwrap: a line of the check's own that says bwrap:"), T.PASSED)]
        for (rc, text), want in cases:
            self.assertEqual(RUN.status_of(rc, text)[0], want, (rc, text))
        self.assertEqual(RUN.status_of(0, "", capped=True)[0], T.UNRUNNABLE)
        self.assertEqual(RUN.status_of(1, "cp: No space left on device"),
                         (T.UNRUNNABLE, "the box, not the tree: No space left on device"))

    def test_red_lines_leave_out_pass_lines(self):
        self.assertEqual(RUN.red_lines("ok 1 fine\n✗ broke here\nFAIL two\n✓ FAIL-looking pass"),
                         ["✗ broke here", "FAIL two"])


class Cancel(unittest.TestCase):
    """run_plan's cancel stops the check the lane no longer wants: its PR merged, closed or moved on mid-check."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lander-cancel-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ev = threading.Event()
        RUN._STOP.event = self.ev
        self.addCleanup(setattr, RUN._STOP, "event", None)

    def execute(self, argv):
        return RUN.execute(argv, self.tmp, dict(os.environ), 120, os.path.join(self.tmp, "log"))

    def test_a_cancel_kills_the_running_check_and_starts_no_more(self):
        threading.Timer(0.3, self.ev.set).start()
        t0 = time.monotonic()
        rc, _, _, capped = self.execute(["sleep", "60"])
        self.assertLess(time.monotonic() - t0, 20)
        self.assertLess(rc, 0)
        self.assertFalse(capped)   # stopped, not timed out: status_of calls it unrunnable, never red
        marker = os.path.join(self.tmp, "ran")
        rc, _, _, _ = self.execute(["touch", marker])
        self.assertLess(rc, 0)
        self.assertFalse(os.path.exists(marker))

    def test_no_cancel_runs_the_check_to_its_end(self):
        marker = os.path.join(self.tmp, "ran")
        self.assertEqual(self.execute(["touch", marker])[0], 0)
        self.assertTrue(os.path.exists(marker))


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

    def test_tree_of_the_working_copy_runs_none_of_its_hooks(self):
        # cc-green's pinned host run for a fenced worker takes the worker's tree this way, as the owner. A relative
        # core.hooksPath (core/.githooks here) is a directory the worker writes, and read-tree and add fire
        # post-index-change; .git/hooks and a core.fsmonitor command are pinned off the same way.
        marks = os.path.join(self.tmp, "marks")
        os.mkdir(marks)
        hook = f"#!/bin/sh\ntouch {marks}/\"$(basename \"$0\")\"\n"
        for d in ("core/.githooks", ".git/hooks"):
            for name in ("post-index-change", "reference-transaction", "fsmon"):
                write(self.repo, {f"{d}/{name}": hook})
                os.chmod(os.path.join(self.repo, d, name), 0o755)
        write(self.repo, {"new.txt": "n"})
        for cfg in ((), ("core.hooksPath", "core/.githooks")):
            if cfg:
                git(self.repo, "config", *cfg)
            git(self.repo, "config", "core.fsmonitor", os.path.join(self.repo, "core/.githooks/fsmon"))
            wt = RUN.tree_of(self.repo, "")
            self.assertIn("new.txt", git(self.repo, "ls-tree", "--name-only", wt))
            self.assertEqual(os.listdir(marks), [], cfg or "the default .git/hooks")
        git(self.repo, "config", "--unset", "core.fsmonitor")
        git(self.repo, "add", "new.txt")   # …and the hooks are real: a plain index write by git fires one
        self.assertIn("post-index-change", os.listdir(marks))

    def test_a_worktree_config_that_is_not_the_hosts_is_refused_and_runs_nothing(self):
        # With extensions.worktreeConfig on, git reads <admin dir>/config.worktree, which a worker writes. A filter's
        # clean command there plus `* filter=x` in .gitattributes ran on the host's `add -A` as the owner whatever
        # NOHOOK pinned (#1078's security read), and an include.path in it reaches the same through another file.
        from lander import plan as P
        git(self.repo, "config", "extensions.worktreeConfig", "true")
        wt = os.path.join(self.tmp, "wt")
        git(self.repo, "worktree", "add", "-q", wt, "-b", "track/x")
        gd, base = git(wt, "rev-parse", "--absolute-git-dir"), git(self.repo, "rev-parse", "HEAD")
        marks = os.path.join(self.tmp, "fmarks")
        os.mkdir(marks)
        inc = os.path.join(self.tmp, "inc.cfg")
        filt = f'[filter "x"]\n\tclean = "touch {marks}/clean; cat"\n'
        with open(inc, "w") as f:
            f.write(filt)
        write(wt, {".gitattributes": "* filter=x\n", "new.txt": "n"})
        open(os.path.join(gd, "config.worktree"), "w").close()   # the box's own: empty, and the tree is taken
        self.assertIn("new.txt", git(self.repo, "ls-tree", "--name-only", RUN.tree_of(wt, "")))
        for name, body in (("filter", filt), ("include.path", f"[include]\n\tpath = {inc}\n")):
            with open(os.path.join(gd, "config.worktree"), "w") as f:
                f.write(body)
            self.assertEqual(RUN.tree_of(wt, ""), "", name)
            with self.assertRaises(RUN.G.GitError, msg=name):
                P.changed(wt, base, "")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                rc = CK.cmd_check([wt, "--base", base])
            self.assertEqual(rc, CK.EXIT_NONE, name)
            self.assertIn("config.worktree is not the host's", err.getvalue(), name)
            self.assertEqual(os.listdir(marks), [], name)
        os.remove(os.path.join(gd, "config.worktree"))   # …and a link to an empty file is refused too: not a plain file
        os.symlink(os.devnull, os.path.join(gd, "config.worktree"))
        self.assertEqual(RUN.tree_of(wt, ""), "")
        os.remove(os.path.join(gd, "config.worktree"))
        with open(os.path.join(gd, "config.worktree"), "w") as f:
            f.write(filt)
        git(wt, "add", "-A")   # …and the plant is real: a plain git add runs the filter
        self.assertIn("clean", os.listdir(marks))

    def test_a_fifo_worktree_config_is_refused_without_git_opening_it(self):
        # git opens config.worktree to find the admin dir (rev-parse), so a FIFO planted there hung the lander before
        # its lstat (#1078's security read). The admin dir comes from the worktree's .git gitfile instead, and only a
        # regular file is ever opened. Run in a child with a timeout so the old code fails here and never hangs the suite.
        git(self.repo, "config", "extensions.worktreeConfig", "true")
        wt = os.path.join(self.tmp, "wt")
        git(self.repo, "worktree", "add", "-q", wt, "-b", "track/x")
        gd, base = git(wt, "rev-parse", "--absolute-git-dir"), git(self.repo, "rev-parse", "HEAD")
        os.mkfifo(os.path.join(gd, "config.worktree"))
        os.mkdir(os.path.join(wt, "sub"))
        probe = textwrap.dedent(f'''
            import contextlib, io, sys
            sys.path.insert(0, {CORE!r})
            from lander import check as CK, git as G, plan as P, run as RUN
            print(bool(G.foreign_config({wt!r})), bool(G.foreign_config({os.path.join(wt, "sub")!r})))
            print(RUN.tree_of({wt!r}, "") == "")
            try:
                P.changed({wt!r}, {base!r}, "")
                print("changed-ran")
            except G.GitError:
                print("changed-refused")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                print(CK.cmd_check([{wt!r}, "--base", {base!r}]) == CK.EXIT_NONE, "not the host's" in err.getvalue())
        ''')
        p = subprocess.Popen([sys.executable, "-c", probe], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True)
        try:
            out, err = p.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, 9)   # the child and the git it is blocked in
            p.communicate()
            self.fail("the lander hung on a FIFO config.worktree")
        self.assertEqual(out.split("\n"), ["True True", "True", "changed-refused", "True True", ""], err)
        # …a gitfile that is not a regular file is refused the same way, and is never opened either
        os.remove(os.path.join(gd, "config.worktree"))
        os.rename(os.path.join(wt, ".git"), os.path.join(self.tmp, "gitfile"))
        os.mkfifo(os.path.join(wt, ".git"))
        p = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {CORE!r}); from lander import git; "
                            f"print(git.foreign_config({wt!r}))"], capture_output=True, text=True, timeout=20)
        self.assertEqual(p.stdout.strip(), os.path.join(wt, ".git"), p.stderr)
        # …and with the gitfile back, a relative gitdir: line resolves against the worktree and finds the same admin dir
        os.remove(os.path.join(wt, ".git"))
        for end in ("\n", "\r\n"):   # git strips a CR as well as the LF
            with open(os.path.join(wt, ".git"), "w", newline="") as f:
                f.write(f"gitdir: {os.path.relpath(gd, wt)}{end}")
            if os.path.lexists(os.path.join(gd, "config.worktree")):
                os.remove(os.path.join(gd, "config.worktree"))
            self.assertEqual(RUN.G.foreign_config(wt), "", repr(end))
            with open(os.path.join(gd, "config.worktree"), "w") as f:
                f.write("[core]\n")
            self.assertEqual(RUN.G.foreign_config(wt), os.path.join(gd, "config.worktree"), repr(end))
        self.assertEqual(RUN.G.foreign_config(self.repo), "")   # the main checkout's .git is a dir: never looked at

    def test_a_subdirectory_is_refused_since_git_climbs_past_what_is_planted_there(self):
        # foreign_config walked up to the first .git and took a directory there for a main checkout, but git skips a
        # .git (or a bare repo) it does not take for one and climbs on to the worktree's gitfile, so `lander check sub`
        # with an empty sub/.git ran a worker's filter (#1078's second security read). Only root's own .git counts.
        from lander import plan as P
        git(self.repo, "config", "extensions.worktreeConfig", "true")
        wt = os.path.join(self.tmp, "wt")
        git(self.repo, "worktree", "add", "-q", wt, "-b", "track/x")
        gd, base = git(wt, "rev-parse", "--absolute-git-dir"), git(self.repo, "rev-parse", "HEAD")
        marks = os.path.join(self.tmp, "smarks")
        os.mkdir(marks)
        filt = f'[filter "x"]\n\tclean = "touch {marks}/clean; cat"\n'
        sub = os.path.join(wt, "sub")
        write(wt, {".gitattributes": "* filter=x\n", "sub/new.txt": "n"})
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        for plant in ("empty .git", "bare repo"):
            if plant == "empty .git":   # the hostile file is the admin dir's config.worktree, which git reaches
                os.mkdir(os.path.join(sub, ".git"))
                with open(os.path.join(gd, "config.worktree"), "w") as f:
                    f.write(filt)
            else:                       # the hostile file is sub/config, which git reads as the repo's own
                shutil.rmtree(os.path.join(sub, ".git"))
                open(os.path.join(gd, "config.worktree"), "w").close()
                for d in ("objects", "refs"):
                    os.mkdir(os.path.join(sub, d))
                write(sub, {"HEAD": "ref: refs/heads/main\n", "config": f"[core]\n\tbare = true\n{filt}"})
            self.assertIn("touch", git(sub, "config", "filter.x.clean"), plant)   # the plant is real: git reads it
            self.assertTrue(RUN.G.foreign_config(sub), plant)
            self.assertEqual(RUN.tree_of(sub, ""), "", plant)
            with self.assertRaises(RUN.G.GitError, msg=plant):
                P.changed(sub, base, "")
            for argv, at in (([sub, "--base", base], cwd), (["--base", base], sub)):   # named, and the default "."
                os.chdir(at)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                    rc = CK.cmd_check(argv)
                os.chdir(cwd)
                self.assertIn(rc, (CK.EXIT_USAGE, CK.EXIT_NONE), (plant, argv, err.getvalue()))
            self.assertEqual(os.listdir(marks), [], plant)
        os.remove(os.path.join(sub, "config"))   # …and a plain subdirectory is refused by name, before any git call
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(CK.cmd_check([os.path.join(wt, "sub", "objects"), "--base", base]), CK.EXIT_USAGE)
        self.assertIn("not a checkout's top directory", err.getvalue())

    def test_only_a_tree_the_host_made_is_taken(self):
        # foreign_config imitated git's discovery by the names inside root/.git, but git also reads HEAD and follows
        # commondir, and takes a repo a worker built for a real one (#1078's third reads). Each plant below passed as
        # clean while git climbed to the worktree's config.worktree or read a config the worker wrote. Only a linked
        # worktree registered under a host repo's own .git/worktrees, or the host checkout itself, is taken now.
        from lander import plan as P
        git(self.repo, "config", "extensions.worktreeConfig", "true")
        wt = os.path.join(self.tmp, "wt")
        git(self.repo, "worktree", "add", "-q", wt, "-b", "track/x")
        gd, base = git(wt, "rev-parse", "--absolute-git-dir"), git(self.repo, "rev-parse", "HEAD")
        marks = os.path.join(self.tmp, "hmarks")
        os.mkdir(marks)
        filt = f'[filter "x"]\n\tclean = "touch {marks}/clean; cat"\n'
        sub, cfgwt = os.path.join(wt, "sub"), os.path.join(gd, "config.worktree")
        write(wt, {".gitattributes": "* filter=x\n", "sub/new.txt": "n"})
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        ws = os.path.join(self.tmp, "scratch")   # where the worker writes its own repos: not a host checkout ($CC_DEV/<x>)

        def repo_at(d, cfg=filt):   # what git takes for a repo: HEAD, objects, refs, and a config the worker wrote
            write(d, {"HEAD": "ref: refs/heads/main\n", "config": cfg})
            for n in ("objects", "refs"):
                os.makedirs(os.path.join(d, n), exist_ok=True)

        def fake_common():   # a whole repo of the worker's, with sub registered as its linked worktree
            c = os.path.join(ws, "evilc", ".git")
            repo_at(c, "[core]\n\trepositoryformatversion = 0\n" + filt)
            write(os.path.join(c, "worktrees", "sub"), {"HEAD": "ref: refs/heads/main\n", "commondir": "../..\n",
                                                        "gitdir": os.path.join(sub, ".git") + "\n"})
            write(sub, {".git": f"gitdir: {os.path.join(c, 'worktrees', 'sub')}\n"})
        plants = (   # (name, plant it, whether git then reads a filter the worker wrote)
            ("junk HEAD", lambda: (write(gd, {"config.worktree": filt}), repo_at(os.path.join(sub, ".git")),
                                   write(sub, {".git/HEAD": "junk\n"})), True),
            ("commondir nowhere", lambda: (write(gd, {"config.worktree": filt}),
                                           write(sub, {".git/HEAD": "ref: refs/heads/main\n",
                                                       ".git/commondir": "/nonexistent\n"})), True),
            ("fake repo", lambda: repo_at(os.path.join(sub, ".git")), True),
            ("gitfile to a worker dir", lambda: (repo_at(os.path.join(ws, "evil")),
                                                 write(sub, {".git": f"gitdir: {os.path.join(ws, 'evil')}\n"})),
             True),
            ("worktree of a worker repo", fake_common, True),
            ("gitdir not pointing back", lambda: write(sub, {".git": f"gitdir: {gd}\n"}), False),
        )
        for name, plant, hostile in plants:
            with self.subTest(name):
                for p in (os.path.join(sub, ".git"), os.path.join(ws, "evil"), os.path.join(ws, "evilc")):
                    if os.path.isdir(p):
                        shutil.rmtree(p)
                    elif os.path.lexists(p):
                        os.remove(p)
                open(cfgwt, "w").close()
                plant()
                if hostile:   # the plant is real: git in sub reads the worker's filter
                    self.assertIn("touch", git(sub, "config", "filter.x.clean"))
                self.assertTrue(RUN.G.foreign_config(sub))
                self.assertEqual(RUN.tree_of(sub, ""), "")
                with self.assertRaises(RUN.G.GitError):
                    P.changed(sub, base, "")
                for argv, at in (([sub, "--base", base], cwd), (["--base", base], sub)):   # named, and the default "."
                    os.chdir(at)
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                        rc = CK.cmd_check(argv)
                    os.chdir(cwd)
                    self.assertIn(rc, (CK.EXIT_USAGE, CK.EXIT_NONE), (argv, err.getvalue()))
                for argv, at in ((["--repo", sub, base], cwd), ([base], sub)):   # `lander plan`, named and from sub
                    os.chdir(at)
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        rc = P.cmd_plan(argv)
                    os.chdir(cwd)
                    self.assertNotEqual(rc, 0, argv)
                self.assertEqual(os.listdir(marks), [])
        if os.path.lexists(os.path.join(sub, ".git")):
            os.remove(os.path.join(sub, ".git"))
        open(cfgwt, "w").close()
        # …the admin dir's commondir pointed at a repo of the worker's: the root itself is refused
        with open(os.path.join(gd, "commondir")) as f:
            commondir = f.read()
        repo_at(os.path.join(ws, "evilr"), "[extensions]\n\tworktreeConfig = true\n" + filt)
        os.mkdir(os.path.join(ws, "evilr", "worktrees"))
        write(gd, {"commondir": os.path.join(ws, "evilr") + "\n"})
        self.assertIn("touch", git(wt, "config", "filter.x.clean"))
        self.assertTrue(RUN.G.foreign_config(wt))
        self.assertEqual(RUN.tree_of(wt, ""), "")
        self.assertEqual(os.listdir(marks), [])
        write(gd, {"commondir": commondir})
        # …and what the host made is still taken: the worktree and the main checkout. A submodule is not: its git dir
        # is one a worker can copy into its own admin dir (test_a_repo_in_the_admin_dirs_modules_is_refused)
        self.assertEqual(RUN.G.foreign_config(wt), "")
        self.assertIn("sub", git(self.repo, "ls-tree", "--name-only", RUN.tree_of(wt, "")))
        self.assertEqual(sorted(P.changed(wt, base, "")), [".gitattributes", "sub/new.txt"])
        self.assertEqual(RUN.G.foreign_config(self.repo), "")
        self.assertTrue(RUN.tree_of(self.repo, ""))
        src = os.path.join(self.tmp, "smsrc")
        os.mkdir(src)
        git(src, "init", "-q")
        git(src, "commit", "-q", "--allow-empty", "-m", "s")
        git(self.repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", src, "mod")
        mod = os.path.join(self.repo, "mod")
        self.assertTrue(RUN.G.foreign_config(mod))
        self.assertEqual(RUN.tree_of(mod, ""), "")
        self.assertEqual(os.listdir(marks), [])

    def hostile(self):
        """A linked worktree the host registered, with worktreeConfig on, `* filter=x` in its .gitattributes and a
        file for the filter to run on -> (wt, its admin dir, base, marks dir, a config that defines filter x)."""
        git(self.repo, "config", "extensions.worktreeConfig", "true")
        wt = os.path.join(self.tmp, "wt")
        git(self.repo, "worktree", "add", "-q", wt, "-b", "track/x")
        gd, base = git(wt, "rev-parse", "--absolute-git-dir"), git(self.repo, "rev-parse", "HEAD")
        marks = os.path.join(self.tmp, "fmarks")
        os.mkdir(marks)
        write(wt, {".gitattributes": "* filter=x\n", "new.txt": "n\n"})
        return wt, gd, base, marks, f'[filter "x"]\n\tclean = "touch {marks}/clean; cat"\n'

    def test_a_repo_in_the_admin_dirs_modules_is_refused(self):
        # #1078's fourth read: the submodule arm took any git dir under <common>/worktrees/<id>/modules, and a worker
        # writes its own admin dir, so a repo copied there with a filter in its config, named by sub/.git, ran it
        from lander import plan as P
        wt, gd, base, marks, filt = self.hostile()
        evil, src = os.path.join(gd, "modules", "evil"), os.path.join(self.tmp, "tmpl")
        os.mkdir(src)
        git(src, "init", "-q")
        git(src, "commit", "-q", "--allow-empty", "-m", "x")
        shutil.copytree(os.path.join(src, ".git"), evil)
        with open(os.path.join(evil, "config"), "a") as f:
            f.write(filt)
        write(wt, {"sub/new.txt": "n\n", "sub/.gitattributes": "* filter=x\n", "sub/.git": f"gitdir: {evil}\n"})
        sub = os.path.join(wt, "sub")
        self.assertIn("touch", git(sub, "config", "filter.x.clean"))   # the plant is real: git in sub reads it
        self.assertTrue(RUN.G.foreign_config(sub))
        self.assertEqual(RUN.tree_of(sub, ""), "")
        with self.assertRaises(RUN.G.GitError):
            P.changed(sub, base, "")
        self.assertTrue(RUN.tree_of(wt, ""))   # the root is the host's: sub is a gitlink there, and nothing runs
        self.assertEqual(os.listdir(marks), [])

    def test_a_commondir_in_a_host_checkouts_git_dir_is_refused(self):
        # the directory arm took $CC_DEV/<name>/.git without looking inside: a member's planted .git/commondir sent
        # git to a common dir of the member's own, its config read and its filter run on `add -A`
        alice, evilc, marks = (os.path.join(self.tmp, n) for n in ("alice", "evilc", "cmarks"))
        os.mkdir(alice)
        os.mkdir(marks)
        git(alice, "init", "-q")
        git(alice, "commit", "-q", "--allow-empty", "-m", "i")
        self.assertEqual(RUN.G.foreign_config(alice), "")
        write(alice, {".gitattributes": "* filter=x\n", "new.txt": "n\n"})
        git(self.tmp, "init", "-q", "--bare", evilc)
        shutil.copytree(os.path.join(alice, ".git", "objects"), os.path.join(evilc, "objects"), dirs_exist_ok=True)
        shutil.copytree(os.path.join(alice, ".git", "refs"), os.path.join(evilc, "refs"), dirs_exist_ok=True)
        with open(os.path.join(evilc, "config"), "a") as f:
            f.write(f'[filter "x"]\n\tclean = "touch {marks}/clean; cat"\n')
        write(alice, {".git/commondir": evilc + "\n"})
        self.assertIn("touch", git(alice, "config", "filter.x.clean"))   # the plant is real
        self.assertEqual(RUN.G.foreign_config(alice), os.path.join(alice, ".git", "commondir"))
        self.assertEqual(RUN.tree_of(alice, ""), "")
        with self.assertRaises(RUN.G.GitError):
            RUN.G.at(alice)
        self.assertEqual(os.listdir(marks), [])

    def test_a_config_worktree_written_after_the_check_is_never_read(self):
        # #1078's fourth read: config.worktree is the worker's own file while it runs, so whatever host_tree saw, a
        # rewrite between its check and `add -A` ran the filter (11 times in 150 tree_of calls). Here the rewrite
        # lands right after every host_tree call, which is the race won every time: git builds the tree FENCED, in a
        # git dir of the lander's own, so the rewritten file is never read
        from lander import plan as P
        wt, gd, base, marks, filt = self.hostile()
        inc = os.path.join(self.tmp, "inc.cfg")
        write(self.tmp, {"inc.cfg": filt})
        real = RUN.G.host_tree
        for name, body in (("a filter", filt), ("an include", f"[include]\n\tpath = {inc}\n")):
            with self.subTest(name):
                open(os.path.join(gd, "config.worktree"), "w").close()

                def racing(root, body=body):
                    t = real(root)
                    write(gd, {"config.worktree": body})
                    return t
                with mock.patch.object(RUN.G, "host_tree", racing):
                    tree = RUN.tree_of(wt, "")
                    self.assertIn("touch", git(wt, "config", "filter.x.clean"))   # the rewrite is real
                    open(os.path.join(gd, "config.worktree"), "w").close()
                    files = P.changed(wt, base, "")
                    self.assertIn("touch", git(wt, "config", "filter.x.clean"))
                open(os.path.join(gd, "config.worktree"), "w").close()   # before plain_tree, which would run it
                self.assertTrue(tree)
                self.assertEqual(sorted(files), [".gitattributes", "new.txt"])
                self.assertEqual(os.listdir(marks), [])
                # the tree is the one plain hashing names with no filter about (green_tree's three commands)
                self.assertEqual(tree, self.plain_tree(wt))

    def test_reads_after_host_tree_never_open_a_rewritten_config_worktree(self):
        # #1078's fifth read: check's merge-base, the VERIFIED reads' cat-file and sealed()'s rev-parse still ran with
        # GIT_DIR the worker's admin dir, so a config.worktree rewritten after host_tree to include a FIFO hung
        # `lander check` for good, and an included filter could steer what they read. Refs are read as files now and
        # git runs in a bare FENCED reader. A child with a timeout, so the old code fails here and never hangs the suite.
        wt, gd, base, marks, filt = self.hostile()
        fifo, inc = os.path.join(self.tmp, "inc.fifo"), os.path.join(self.tmp, "inc.cfg")
        os.mkfifo(fifo)
        write(self.tmp, {"inc.cfg": filt})
        cfgwt = os.path.join(gd, "config.worktree")
        base_tree = git(self.repo, "rev-parse", f"{base}^{{tree}}")
        for name, path in (("a FIFO include", fifo), ("a filter include", inc)):
            with self.subTest(name):
                open(cfgwt, "w").close()
                probe = textwrap.dedent(f'''
                    import sys
                    sys.path.insert(0, {CORE!r})
                    from lander import check as CK, git as G, plan as P
                    real = G.host_tree
                    def racing(root):
                        t = real(root)
                        with open({cfgwt!r}, "w") as f:
                            f.write("[include]\\n\\tpath = {path}\\n")
                        return t
                    def fresh():   # the host's empty file, and host_tree takes it again: the race won each call
                        open({cfgwt!r}, "w").close()
                        G._TREES.clear()
                    G.host_tree = racing
                    fresh()
                    print(CK.default_base({wt!r}) == {base!r})
                    fresh()
                    print(G.tree_of({wt!r}, {base!r}) == {base_tree!r}, G.tree_of({wt!r}, "HEAD") == {base_tree!r})
                    fresh()
                    print(G.read_verified({wt!r}, "HEAD", "README.md") is not None)
                    fresh()
                    with G.sealed({wt!r}, {base!r}, "HEAD") as ((rc, out), run):
                        print(rc, out == [{base!r}, {base!r}])
                    fresh()
                    print(sorted(P.changed({wt!r}, {base!r}, "")))
                    print("include" in open({cfgwt!r}).read())
                ''')
                p = subprocess.Popen([sys.executable, "-c", probe], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, start_new_session=True)
                try:
                    out, err = p.communicate(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, 9)   # the child and the git it is blocked in
                    p.communicate()
                    self.fail(f"a read hung on {name} in config.worktree")
                self.assertEqual(out.split("\n"), ["True", "True True", "True", "0 True",
                                                   "['.gitattributes', 'new.txt']", "True", ""], err)
                self.assertEqual(os.listdir(marks), [])
        open(cfgwt, "w").close()

    def test_a_name_is_read_as_files_and_resolved_in_the_reader(self):
        # _name: a ref by git's DWIM order read as files, then what follows it and an abbreviated id in the reader
        wt, gd, base, marks, filt = self.hostile()
        t = RUN.G.host_tree(wt)
        tree = git(self.repo, "rev-parse", f"{base}^{{tree}}")
        with RUN.G.fenced(t, bare=True) as env:
            self.assertNotIn("GIT_WORK_TREE", env)
            for rev, want in (("HEAD", base), ("track/x", base), ("refs/heads/track/x", base), ("HEAD^{tree}", tree),
                              ("track/x:", tree), (base[:10], base), (f"{base}^{{commit}}", base)):
                self.assertEqual(RUN.G._name(t, env, rev), (0, want), rev)
            for rev in ("-x", "", "no/such/branch", "HEAD~9"):
                self.assertNotEqual(RUN.G._name(t, env, rev)[0], 0, rev)
        self.assertEqual(RUN.G.merge_base(t, "HEAD", "track/x"), base)
        self.assertEqual(RUN.G.merge_base(t, "HEAD", "no/such/branch"), "")
        self.assertEqual(RUN.G.merge_base(RUN.G.Tree("", "", wt), "HEAD", "HEAD"), "")
        with RUN.G.sealed(wt, "no/such/branch") as ((rc, out), run):
            self.assertIsNone(run)
        self.assertEqual(RUN.G.objects_dir(wt), os.path.join(t.common, "objects"))
        shutil.rmtree(os.path.join(t.common, "objects", "pack"))
        with self.assertRaises(RUN.G.GitError):
            RUN.G.objects_dir(wt)

    def test_a_ref_under_a_symlinked_directory_is_never_read(self):
        # #1078's security read: _ref opened the ref O_NOFOLLOW, which covers its last component only, so a worker's
        # <admin>/refs/worktree (or a dir under the common refs/) made a link sent the read to a file elsewhere
        wt, gd, base, marks, filt = self.hostile()
        t = RUN.G.host_tree(wt)
        other = git(self.repo, "commit-tree", "-m", "o", f"{base}^{{tree}}")
        out = os.path.join(self.tmp, "elsewhere")
        write(out, {"x": other + "\n"})
        for top, ref in ((gd, "refs/worktree/x"), (t.common, "refs/heads/evil/x")):
            with self.subTest(ref):
                d = os.path.join(top, os.path.dirname(ref))
                write(d, {"x": other + "\n"})   # kept: the same ref in a real directory is read
                self.assertEqual(RUN.G._ref(t, ref), other)
                shutil.rmtree(d)
                os.symlink(out, d)   # suppressed: the directory a link to one elsewhere
                with open(os.path.join(top, ref)) as f:
                    self.assertEqual(f.read().strip(), other)   # the plant is real
                self.assertEqual(RUN.G._ref(t, ref), "")
                os.unlink(d)
        os.symlink(out, os.path.join(gd, "refs", "worktree"))   # a symbolic HEAD names it: refused at the link too
        write(gd, {"HEAD": "ref: refs/worktree/x\n"})
        self.assertEqual(RUN.G._ref(t, "HEAD"), "")

    def test_a_rewritten_loose_commit_does_not_move_the_merge_base(self):
        # #1078's security read: the worker writes the host's objects, and merge-base ran FENCED on them, so its own
        # commit's loose file rewritten under the old name with main's tip as parent moved check's base onto main.
        # Not the tip: git re-hashes the object a name resolves to, but not the parents a history walk opens
        import zlib
        wt, gd, base, marks, filt = self.hostile()
        git(wt, "commit", "-q", "--allow-empty", "-m", "c1")
        c1 = git(wt, "rev-parse", "HEAD")
        git(wt, "commit", "-q", "--allow-empty", "-m", "c2")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "m1")
        c2, m1 = git(wt, "rev-parse", "HEAD"), git(self.repo, "rev-parse", "HEAD")
        main = git(self.repo, "symbolic-ref", "--short", "HEAD")
        t = RUN.G.host_tree(wt)
        self.assertEqual(RUN.G.merge_base(t, "HEAD", main), base)   # kept: the honest objects give the honest base
        self.assertEqual(CK.default_base(wt), base)
        body = git(wt, "cat-file", "commit", c1).replace(f"parent {base}", f"parent {m1}", 1).encode() + b"\n"
        loose = os.path.join(t.common, "objects", c1[:2], c1[2:])
        os.chmod(loose, 0o644)
        with open(loose, "wb") as f:
            f.write(zlib.compress(b"commit %d\0" % len(body) + body))
        self.assertEqual(git(self.repo, "merge-base", c2, m1), m1)   # the plant is real: git takes the forged parent
        with RUN.G.fenced(t, bare=True) as env:   # and so did the FENCED reader merge_base ran in
            self.assertEqual(subprocess.run(["git", "merge-base", c2, m1], cwd=env["GIT_DIR"], env=env, text=True,
                                            capture_output=True).stdout.strip(), m1)
        self.assertEqual(RUN.G.merge_base(t, "HEAD", main), "")   # suppressed: the sealed fetch re-hashes it
        self.assertEqual(CK.default_base(wt), "")

    def test_an_objects_session_that_outlives_its_timer_fails_closed(self):
        wt, gd, base, marks, filt = self.hostile()
        with mock.patch.object(RUN.G, "OBJECTS_SECS", 0.05):
            with RUN.G.Objects(wt) as o:
                o.p.wait(timeout=20)   # the timer killed cat-file
                with self.assertRaises(RUN.G.GitError):
                    o.read(base)

    def plain_tree(self, top):
        """tests/green.sh's green_tree: read-tree HEAD, add -A, write-tree in the checkout on an index of its own."""
        idx = os.path.join(self.tmp, "plain.index")
        env = dict(os.environ, GIT_INDEX_FILE=idx)
        for a in (("read-tree", "HEAD"), ("add", "-A")):
            subprocess.run(["git", "-C", top, *a], env=env, check=True, capture_output=True)
        tree = subprocess.run(["git", "-C", top, "write-tree"], env=env, check=True, capture_output=True,
                              text=True).stdout.strip()
        os.remove(idx)
        return tree

    def test_the_fenced_tree_is_the_tree_plain_hashing_names(self):
        # landing verdicts compare the tree a worker's green named (green_tree, plain git in the checkout) with the
        # one the lander takes; FENCED must name the same tree wherever no filter or eol rule is configured
        wt = os.path.join(self.tmp, "wt")
        write(self.repo, {".gitignore": "*.log\nbuild/\n", "kept.log": "tracked though ignored\n", "gone.txt": "g\n",
                          "link-target": "t\n"})
        os.symlink("link-target", os.path.join(self.repo, "link"))
        git(self.repo, "add", "-A", "-f")
        git(self.repo, "commit", "-qm", "more")
        git(self.repo, "worktree", "add", "-q", wt, "-b", "track/eq")
        write(wt, {"README.md": "changed\n", "untracked.txt": "u\n", "x.log": "ignored\n", "build/o": "ignored\n",
                   "kept.log": "tracked, changed\n", "skipme": "by info/exclude\n", "deep/a/b.txt": "b\n"})
        os.remove(os.path.join(wt, "gone.txt"))
        os.chmod(os.path.join(wt, "core/bin/tool"), 0o644)
        write(self.repo, {".git/info/exclude": "skipme\n"})
        for top in (wt, self.repo):
            with self.subTest(top):
                got = RUN.tree_of(top, "")
                self.assertTrue(got)
                self.assertEqual(got, self.plain_tree(top))
        names = git(self.repo, "ls-tree", "-r", "--name-only", RUN.tree_of(wt, "")).split("\n")
        self.assertIn("untracked.txt", names)
        self.assertIn("kept.log", names)
        for gone in ("x.log", "build/o", "skipme", "gone.txt"):
            self.assertNotIn(gone, names)

    def test_a_refused_root_runs_no_git_and_its_cached_tree_is_dropped(self):
        # at() on a root host_tree refuses gave git a ceiling and ran it anyway, and a refusal after an accept
        # dropped the cached tree so the next object read fell back to that. It raises now, before any git runs
        wt, gd, base, marks, filt = self.hostile()
        outside = tempfile.mkdtemp(prefix="not-a-host-checkout.")
        self.addCleanup(shutil.rmtree, outside, True)
        git(outside, "init", "-q")
        git(outside, "commit", "-q", "--allow-empty", "-m", "x")
        head = git(outside, "rev-parse", "HEAD")
        with self.assertRaises(RUN.G.GitError):
            RUN.G.at(outside)
        with self.assertRaises(RUN.G.GitError):
            RUN.G.objects_dir(outside)
        with self.assertRaises(RUN.G.GitError):
            RUN.G.read_verified(outside, head, "x")
        with RUN.G.sealed(outside, head) as ((rc, out), run):
            self.assertIsNone(run)
            self.assertIn("not a checkout the host made", out)
        self.assertEqual(RUN.tree_of(outside, head), "")
        # …and a tree taken once, then refused, is refused from then on, not read through the cache
        self.assertEqual(RUN.G.at(wt)["GIT_DIR"], gd)
        write(gd, {"config.worktree": filt})
        self.assertTrue(RUN.G.foreign_config(wt))
        with self.assertRaises(RUN.G.GitError):
            RUN.G.at(wt)
        with self.assertRaises(RUN.G.GitError):
            RUN.G.read_verified(wt, base, "README.md")
        self.assertEqual(os.listdir(marks), [])

    def test_a_nul_in_a_gitfile_or_the_admin_gitdir_is_a_refusal_not_a_traceback(self):
        wt, gd, base, marks, filt = self.hostile()
        with open(os.path.join(gd, "gitdir")) as f:
            back = f.read()
        write(gd, {"gitdir": back.rstrip("\n") + "\0x\n"})
        self.assertTrue(RUN.G.foreign_config(wt))
        self.assertEqual(RUN.tree_of(wt, ""), "")
        write(gd, {"gitdir": back})
        self.assertEqual(RUN.G.foreign_config(wt), "")
        write(wt, {".git": f"gitdir: {gd}\0junk\n"})
        self.assertEqual(RUN.G.foreign_config(wt), os.path.join(wt, ".git"))
        self.assertEqual(RUN.G.foreign_config(wt + "\0"), wt + "\0")

    def test_a_board_path_outside_dev_and_a_member_clone_are_host_checkouts(self):
        # the host lands into $CC_DEV/<repo>, a board's `path` (named after the repo or not) and a member's clone
        # under the lander's clones dir (jobs.repo_root): each is taken, and the same tree outside them is not
        import json
        lq = os.path.join(self.tmp, "lq")
        os.makedirs(os.environ["CC_BOARDS"])
        os.makedirs(os.path.join(self.tmp, "bob", ".cc"))
        write(self.tmp, {"bob/.cc/member-workspace": ""})
        roots = {"board named after it": os.path.join(self.tmp, "srv", "proj"),
                 "board under another name": os.path.join(self.tmp, "srv", "other-dir"),
                 "member clone": os.path.join(lq, "clones", "bob--proj")}
        for name, root in roots.items():
            with self.subTest(name):
                os.makedirs(root)
                git(root, "init", "-q")
                write(root, {"f": "1\n"})
                git(root, "add", "-A")
                git(root, "commit", "-qm", "x")
                with mock.patch.dict(os.environ, {"CC_LANDER_STATE": os.path.join(self.tmp, "elsewhere")}):
                    self.assertTrue(RUN.G.foreign_config(root))   # before its board or clones dir names it
                    self.assertEqual(RUN.tree_of(root, ""), "")
                if name.startswith("board"):
                    with open(os.path.join(os.environ["CC_BOARDS"], ("proj" if "after" in name else "anyname")
                                           + ".json"), "w") as f:
                        json.dump({"path": root}, f)
                with mock.patch.dict(os.environ, {"CC_LANDER_STATE": lq}):
                    self.assertEqual(RUN.G.foreign_config(root), "")
                    self.assertEqual(RUN.tree_of(root, ""), git(root, "rev-parse", "HEAD^{tree}"))

    def test_sweep_climbs_from_a_subdirectory_to_the_host_checkout(self):
        # `lander sweep --repo <subdir>` on the owner's own checkout: the top is found by host_tree, not git discovery
        sub = os.path.join(self.repo, "core", "bin")
        self.assertEqual(CK.host_top(sub).work_tree, self.repo)
        self.assertEqual(CK.host_top(self.repo).work_tree, self.repo)
        nowhere = tempfile.mkdtemp(prefix="in-no-checkout.")
        self.addCleanup(shutil.rmtree, nowhere, True)
        self.assertTrue(CK.host_top(nowhere).refused)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(CK.cmd_sweep(["--repo", nowhere]), CK.EXIT_USAGE)
        self.assertIn("in no checkout the host made", err.getvalue())


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

    def test_an_express_run_takes_no_slot_and_a_lone_one_takes_them_all(self):
        # the lane's EXPRESS bounds its own runs; a diagnostic rerun alone still runs by itself
        calls, real = [], A.slot

        def slot(state, alone=False, **kw):
            calls.append(alone)
            return real(state, alone=alone, **kw)
        with mock.patch.object(A, "slot", slot):
            r = self.run_(chk(klass=T.HOST), express=True)
            self.assertEqual((r.status, calls), (T.PASSED, []))
            r = self.run_(chk(klass=T.HOST), express=True, alone=True)
            self.assertEqual((r.status, calls), (T.PASSED, [True]))
            r = self.run_(chk(klass=T.HOST))
            self.assertEqual((r.status, calls), (T.PASSED, [True, False]))

    def test_a_lanes_express_run_takes_no_slot_and_its_other_runs_wait_as_a_lane(self):
        # lane=True only moves the run's ticket ahead of a worker's: an express run still takes no slot at all
        calls, real = [], A.slot

        def slot(state, alone=False, lane=False, **kw):
            calls.append((alone, lane))
            return real(state, alone=alone, lane=lane, **kw)
        with mock.patch.object(A, "slot", slot):
            r = self.run_(chk(klass=T.HOST), express=True, lane=True)
            self.assertEqual((r.status, calls), (T.PASSED, []))
            r = self.run_(chk(klass=T.HOST), lane=True)
            self.assertEqual((r.status, calls), (T.PASSED, [(False, True)]))

    def test_host_and_box_checks_are_wrapped_in_cc_nosignal(self):
        for klass in (T.HOST, T.BOX):
            argv, wd, _env, how = RUN._box_argv(chk(run="echo hi", klass=klass), "/head", "", "/run", {})
            self.assertTrue(argv[0].endswith("/cc-nosignal"), argv)
            self.assertEqual(argv[1], "--")
            self.assertEqual((how, wd), ("host", "/head"))

    def test_a_bare_check_is_not_wrapped_in_cc_nosignal(self):
        for klass in (T.HOST, T.BOX):
            argv, wd, _env, how = RUN._box_argv(chk(run="echo hi", klass=klass, bare=True), "/head", "", "/run", {})
            self.assertEqual(argv, ["/bin/sh", "-c", "echo hi"])
            self.assertEqual((how, wd), ("host", "/head"))

    def test_a_bare_check_runs_outside_the_signal_scope_and_an_ordinary_one_inside(self):
        # cc-nosignal's scope is a Landlock domain with no_new_privs, which nothing clears: a bare check's process
        # reads 0, an ordinary host check's 1. (cc-member-v2 cannot read a live sandbox's fds from inside one.)
        with open("/proc/self/status") as f:
            mine = nnp(f.read())
        if mine != "0":
            self.skipTest("this suite already runs with no_new_privs (a sandbox or a scope), so 0 cannot be seen")
        probe = "grep -q '^NoNewPrivs:[[:space:]]*{}$' /proc/self/status"
        inside = self.run_(chk(run=probe.format(1), klass=T.HOST))
        if inside.status == T.UNRUNNABLE:
            self.skipTest(f"cc-nosignal cannot scope a check on this kernel: {inside.extra}")
        self.assertEqual(inside.status, T.PASSED, inside.extra)
        for klass in (T.HOST, T.BOX):
            bare = self.run_(chk(run=probe.format(0), klass=klass, bare=True))
            self.assertEqual(bare.status, T.PASSED, (klass, bare.extra))

    def test_a_sandboxed_check_is_not_wrapped_in_cc_nosignal(self):
        with mock.patch.object(S, "available", return_value=True), \
                mock.patch.object(S, "write_stub", return_value="/stub"), \
                mock.patch.object(S, "argv", return_value=["bwrap", "--", "sh"]):
            argv, _wd, _env, how = RUN._box_argv(chk(run="true", klass=T.HERMETIC), "/head", "", "/run", {})
        self.assertEqual((argv, how), (["bwrap", "--", "sh"], "bwrap"))
        self.assertFalse(any(a.endswith("cc-nosignal") for a in argv))

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

    def two_runners(self):
        # R3: `remote` lists the peer host first and the laptop second; each fake runner answers as the
        # file $tmp/say.<host> says (busy, red, gone, dropped, hang; else a pass), and the stub logs which it was asked
        d = self.laptop(host="peer")
        write(d, {"remote": "ccsuite@peer\nccsuite@laptop\n",
                  "known_hosts": "peer,laptop ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIxx\n"})
        calls = os.path.join(self.tmp, "calls")
        env = self.shim("two", f'''prev=; for a in "$@"; do [ "$a" = -- ] && break; prev=$a; done
h=${{prev#*@}}; echo "$h" >> {calls}; cat >/dev/null
case "$(cat {self.tmp}/say.$h 2>/dev/null)" in
  busy) echo "lander-job: busy (load 9.00)"; exit 75;;
  gone) echo "ssh: connect to host $h port 22: Connection timed out" >&2; exit 255;;
  dropped) echo "Timeout, server $h not responding." >&2; exit 255;;
  hang) sleep 30;;
  red) echo "| it broke"; echo "lander-job: verdict exit=1";;
  *) echo "| ran on $h"; echo "lander-job: verdict exit=0";;
esac
''')
        c = chk(run="echo ran", where=["box", "laptop"])
        RUN._SILENT.clear()
        self.addCleanup(RUN._SILENT.clear)

        def go(c=c, **say):
            for h in ("peer", "laptop"):
                write(self.tmp, {f"say.{h}": say.get(h, "") + "\n"})
            open(calls, "w").close()
            with mock.patch.dict(os.environ, env):
                r = self.run_(c, where="laptop")
            with open(calls) as f:
                return r, f.read().split()
        return go

    def test_two_runners_in_order_the_busy_one_is_passed_over_and_the_one_that_took_it_is_named(self):
        go = self.two_runners()
        r, asked = go(peer="busy")              # the first busy: the second takes it, and the result says so
        self.assertEqual((r.status, r.runner, asked), (T.PASSED, "laptop:ccsuite@laptop:-", ["peer", "laptop"]),
                         r.extra)
        self.assertIn("ran on laptop", r.extra["tail"])
        self.assertIn("busy", r.extra["passed_over"][0])
        self.assertTrue(r.extra["passed_over"][0].startswith("ccsuite@peer: "))
        r, asked = go()                          # the first free: it takes it, and the second is never asked
        self.assertEqual((r.status, r.runner, asked), (T.PASSED, "laptop:ccsuite@peer:-", ["peer"]), r.extra)
        self.assertNotIn("passed_over", r.extra)
        r, asked = go(peer="red")               # a red there is a red to judge(), never a turn for the next runner
        self.assertEqual((r.status, r.runner, asked), (T.FAILED, "laptop:ccsuite@peer:-", ["peer"]), r.extra)
        r, asked = go(peer="busy", laptop="busy")   # both busy: unrunnable, so judge() runs it on the box
        self.assertEqual((r.status, asked), (T.UNRUNNABLE, ["peer", "laptop"]), r.extra)
        self.assertEqual(len(r.extra["passed_over"]), 2)
        self.assertEqual(RUN._SILENT, {})        # a busy runner answered: it is not rested
        r, asked = go(peer="gone")              # one ssh never reached is passed over, and rested for RUNNER_REST…
        self.assertEqual((r.status, r.runner, asked), (T.PASSED, "laptop:ccsuite@laptop:-", ["peer", "laptop"]))
        self.assertIn("Connection timed out", r.extra["passed_over"][0])
        r, asked = go()
        self.assertEqual((r.runner, asked), ("laptop:ccsuite@laptop:-", ["laptop"]))
        self.assertIn("not reached lately", r.extra["passed_over"][0])
        RUN._SILENT["ccsuite@peer"] -= RUN.RUNNER_REST     # …and asked again once that is over
        r, asked = go()
        self.assertEqual((r.runner, asked), ("laptop:ccsuite@peer:-", ["peer"]))

    def test_a_job_that_started_on_a_runner_is_never_sent_to_the_next(self):
        # the security read of #1097: a check that ran on the first runner, then lost its connection or hit its cap,
        # ran once already; the second must not run it again, and the first is not rested for it. judge() takes it.
        go = self.two_runners()
        r, asked = go(peer="dropped")
        self.assertEqual((r.status, r.runner, asked), (T.UNRUNNABLE, "laptop:ccsuite@peer:-", ["peer"]), r.extra)
        self.assertIn("not responding", r.extra["why"])
        self.assertNotIn("passed_over", r.extra)
        r, asked = go(chk(run="sleep 30", where=["box", "laptop"], cap=1), peer="hang")
        self.assertEqual((r.status, r.runner, asked), (T.UNRUNNABLE, "laptop:ccsuite@peer:-", ["peer"]), r.extra)
        self.assertEqual(r.extra["why"], "stopped at its cap")
        self.assertEqual(RUN._SILENT, {})
        r, asked = go()                          # and peer takes the next check at once
        self.assertEqual((r.status, r.runner, asked), (T.PASSED, "laptop:ccsuite@peer:-", ["peer"]), r.extra)
        # what proves a job never began there: a refusal or ssh failing before any session, never a cap or a relay
        self.assertEqual(RUN.never_started("cc-suite-runner: unfit (missing: git)\n", False), "refused")
        self.assertEqual(RUN.never_started("** WARNING: connection is not using a post-quantum key exchange\n"
                                           "ssh: Could not resolve hostname peer: Name or service not known\n",
                                           False), "unreached")
        # ssh puts user@host ahead of a refused key: a peer without the account or the key must still be passed over
        self.assertEqual(RUN.never_started("ccsuite@peer: Permission denied (publickey).\n", False), "unreached")
        self.assertEqual(RUN.never_started("ccsuite@fd7a::1: Permission denied (publickey).\n", False), "unreached")
        # a runner's line is not trusted to be short: 40k '@' is read in linear time, not seconds of backtracking
        t0 = time.monotonic()
        self.assertEqual(RUN.never_started("@" * 40000 + "\n", False), "")
        self.assertLess(time.monotonic() - t0, 0.5)
        for text, capped in (("", False), ("ssh: connect to host x port 22: No route to host\n", True),
                             ("| ccsuite@peer: Permission denied (publickey).\n", False),
                             ("| cc-suite-runner: busy\nlander-job: verdict exit=1\n", False),
                             ("Connection to peer closed by remote host.\n", False)):
            self.assertEqual(RUN.never_started(text, capped), "", text)

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

    def meminfo(self, kb):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "w") as f:
            f.write(f"MemTotal:       {kb} kB\nMemFree:        1000 kB\n")
        self.addCleanup(os.unlink, path)
        return path

    def test_host_slots_are_the_cores_and_memory_the_host_has(self):
        # the tower of 2026-10-12: 20 cores and 30 GB ran 3 slots at load ~9 while PRs waited for one
        tower = self.meminfo(31918896)
        with mock.patch.object(A, "MEM_MAX", "6G"):
            self.assertEqual(A.host_slots(tower, 20), 5)                       # 20 // 2 is 10, and 30 GB holds 5 of 6G
            self.assertEqual(A.host_slots(self.meminfo(12 * 1024 ** 2), 20), 2)   # memory is the bound
            self.assertEqual(A.host_slots(tower, 6), 3)                        # the old box keeps its 3
            self.assertEqual(A.host_slots(tower, 1), 1)                        # never 0
            self.assertEqual(A.host_slots("/nonexistent", 20), 10)             # no MemTotal: the cores decide
        with mock.patch.object(A, "MEM_MAX", "infinity"):
            self.assertEqual(A.host_slots(self.meminfo(1024), 20), 10)         # no per-check cap: the cores decide

    def test_slots_come_from_cc_config_and_are_read_again_unrestarted(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        cfg = os.path.join(d, "config")
        env = {k: v for k, v in os.environ.items() if k != "LANDER_SLOTS"}
        env.update(CC_CONFIG=cfg, CC_BIN=os.path.join(os.path.dirname(A.__file__), "..", "bin"))
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(A, "_read", (None, 0.0)), \
                mock.patch.object(A, "SLOTS", None), mock.patch.object(A, "host_slots", lambda *a, **k: 4):
            write(d, {"config": "LANDER_SLOTS=7\n"})
            self.assertEqual(A.slots(now=1000.0), 7)
            write(d, {"config": "LANDER_SLOTS=2\n"})
            self.assertEqual(A.slots(now=1000.0 + A.CONFIG_TTL - 1), 7)        # inside the TTL: not asked again
            self.assertEqual(A.slots(now=1000.0 + A.CONFIG_TTL), 2)            # past it: the lane follows the change
            for i, bad in enumerate(("0", "three", "", "\u00b2")):   # '²' is a digit to isdigit()
                write(d, {"config": f"LANDER_SLOTS={bad}\n"})
                self.assertEqual(A.slots(now=2000.0 * (i + 1)), 4)              # not a K: the host's
            write(d, {"config": "LANDER_SLOTS=300\n"})
            with mock.patch("os.cpu_count", return_value=8):
                self.assertEqual(A.slots(now=8500.0), 8)                       # never more than the cores
            write(d, {"config": f"LANDER_SLOTS={'9' * 5000}\n"})   # past int()'s 4300 digits: no ValueError
            with mock.patch("os.cpu_count", return_value=8):
                self.assertEqual(A.slots(now=8800.0), 8)                       # the cores, like 300
            os.unlink(cfg)
            self.assertEqual(A.slots(now=9000.0), 4)                           # unset: the host's
            with mock.patch.object(A, "SLOTS", 9):
                self.assertEqual(A.slots(now=9001.0), 9)                       # a caller's fixed K wins

    def test_a_cc_config_missing_or_timing_out_leaves_the_host_k(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with mock.patch.object(A, "_read", (None, 0.0)), mock.patch.object(A, "SLOTS", None), \
                mock.patch.object(A, "host_slots", lambda *a, **k: 4):
            with mock.patch.dict(os.environ, {"CC_BIN": d, "LANDER_SLOTS": "7"}):   # no cc-config in that bin
                self.assertIsNone(A.config_slots())
                self.assertEqual(A.slots(now=1000.0), 4)
            boom = subprocess.TimeoutExpired(["cc-config"], 10)
            with mock.patch.object(A.subprocess, "run", side_effect=boom):
                self.assertIsNone(A.config_slots())
                self.assertEqual(A.slots(now=2000.0), 4)

    def test_alone_waits_for_a_slot_past_its_own_k(self):
        # brief: "an 'alone' re-run ... runs beside checks on slots 4-8" when K rose 3 to 8 under it
        st = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, st)
        calm = self.psi_dir(0, 0)
        with contextlib.ExitStack() as busy:
            self.assertEqual(busy.enter_context(A.slot(st, psi_root=calm, k=8)), [1])
            self.assertEqual(busy.enter_context(A.slot(st, psi_root=calm, k=8)), [2])   # past an alone run's K of 1
            busy.close()
            far = contextlib.ExitStack()
            first = busy.enter_context(A.slot(st, psi_root=calm, k=8))
            self.assertEqual(far.enter_context(A.slot(st, psi_root=calm, k=8)), [2])
            self.assertEqual(first, [1])
            busy.close()   # slot 1 free, slot 2 still busy: an alone run counting K=1 still waits
            with self.assertRaises(TimeoutError):
                with A.slot(st, alone=True, psi_root=calm, k=1, poll=0.05, deadline=0.2, say=lambda _: None):
                    pass
            far.close()
        with A.slot(st, alone=True, psi_root=calm, k=1) as mine:   # nothing busy: it runs
            self.assertEqual(mine, [1])
            with self.assertRaises(TimeoutError):   # and while it runs, no check takes slot 2 beside it
                with A.slot(st, psi_root=calm, k=8, poll=0.05, deadline=0.2, say=lambda _: None):
                    pass

    def test_free_counts_the_slots_a_check_takes_now_and_none_while_anyone_waits(self):
        # brief (2026-10-02, #772): a check must not wait for a box slot while a runner has room, so spill() asks
        # free() whether one would wait here; it looks without holding anything
        st = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, st)
        calm = self.psi_dir(0, 0)
        self.assertEqual(A.free(st, psi_root=calm, k=2), 2)   # no slots directory yet: every slot is free
        with A.slot(st, psi_root=calm, k=2):
            self.assertEqual(A.free(st, psi_root=calm, k=2), 1)
            with A.slot(st, psi_root=calm, k=2):
                self.assertEqual(A.free(st, psi_root=calm, k=2), 0)
            self.assertEqual(A.free(st, psi_root=calm, k=2), 1)
        self.assertEqual(A.free(st, psi_root=calm, k=2), 2)   # and looking took nothing
        with A.slot(st, psi_root=calm, k=1):
            self.assertEqual(A.free(st, psi_root=calm, k=1), 0)
            self.assertEqual(A.free(st, psi_root=calm, k=3), 2)   # K rose: the slots past the held one are free
        # a live ticket in the queue goes first (FAIR WAIT), so a new check would wait behind it
        q = os.path.join(st, "slots", "queue")
        name, tf = A._ticket(q)
        try:
            self.assertEqual(A.free(st, psi_root=calm, k=2), 0)
        finally:
            tf.close()
        self.assertEqual(A.free(st, psi_root=calm, k=2), 2)   # its waiter gone, the ticket no longer counts
        with A.slot(st, alone=True, psi_root=calm, k=1):   # an alone run holds the gate: nothing runs beside it
            self.assertEqual(A.free(st, psi_root=calm, k=2), 0)
        self.assertEqual(A.free(st, psi_root=calm, k=2), 2)

    def test_slots_now_backs_off_from_the_new_k(self):
        calm, hot = self.calm_load, self.loadavg(2.0 * (os.cpu_count() or 1))
        with mock.patch.object(A, "slots", lambda: 6):
            self.assertEqual(A.slots_now(self.psi_dir(1.0, 50.0), None, calm), 6)
            self.assertEqual(A.slots_now(self.psi_dir(1.0, 99.9), None, calm), 2)   # cpu pressure keeps two
            self.assertEqual(A.slots_now(self.psi_dir(0, 0), None, hot), 2)         # so does the load average
            self.assertEqual(A.slots_now(self.psi_dir(40.0, 1.0), None, calm), 1)   # memory pressure keeps one

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

    def test_a_long_slot_wait_writes_one_line_to_the_run_status(self):
        # a cc-green run sat 2-3 h on slots with only its header in its log, five times: past WAIT_SAY its status says so, once
        st, note = tempfile.mkdtemp(), tempfile.mktemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        calm = self.psi_dir(0, 0)
        with mock.patch.object(A, "WAIT_SAY", 0.1), mock.patch.object(A, "_noted", False), \
                mock.patch.dict(os.environ, {"LANDER_WAIT_NOTE": note}), contextlib.redirect_stderr(io.StringIO()):
            with A.slot(st, psi_root=calm, k=1):
                for _ in range(2):   # two checks of one run wait: still one line
                    with self.assertRaises(TimeoutError):
                        with A.slot(st, psi_root=calm, k=1, poll=0.05, deadline=0.4):
                            pass
        with open(note) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("waiting="), lines)
        self.assertIn("waiting since", lines[0])
        self.assertIn("cc-green stop", lines[0])
        # …and a waiter with no note (the landing lane) writes no status line, however long it waits
        env = {k: v for k, v in os.environ.items() if k != "LANDER_WAIT_NOTE"}
        with mock.patch.object(A, "WAIT_SAY", 0.1), mock.patch.object(A, "_noted", False), \
                mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(io.StringIO()):
            with A.slot(st, psi_root=calm, k=1):
                with self.assertRaises(TimeoutError):
                    with A.slot(st, psi_root=calm, k=1, poll=0.05, deadline=0.4):
                        pass
            self.assertFalse(A._noted)

    def test_a_held_slot_appends_one_wait_record_and_a_waiter_without_a_log_writes_none(self):
        # cc-green's one log per worktree is overwritten by the next run, so its slot waits went with it (cc-i2m)
        st, d = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.addCleanup(lambda: [__import__("shutil").rmtree(x) for x in (st, d)])
        wl, calm = os.path.join(d, ".cc", "w", "waits-r.tsv"), self.psi_dir(0, 0)
        out = os.path.join(st, "elsewhere.tsv")                 # outside ~/.cc: never written
        with mock.patch.dict(os.environ, {"HOME": d, "LANDER_WAIT_LOG": out}):
            with A.slot(st, psi_root=calm, k=1, who="t@abc"):
                pass
        self.assertFalse(os.path.exists(out))
        with mock.patch.dict(os.environ, {"HOME": d, "LANDER_WAIT_LOG": wl, "LANDER_WAIT_ROW": "row\n1"}):
            with A.slot(st, psi_root=calm, k=1, who="t@abc"):
                pass
        env = {k: v for k, v in os.environ.items() if k != "LANDER_WAIT_LOG"}
        with mock.patch.dict(os.environ, env, clear=True):
            with A.slot(st, psi_root=calm, k=1, who="lane"):
                pass
        with open(wl) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1, lines)
        start, end, row, who, secs = lines[0].split("\t")
        self.assertRegex(start, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertLessEqual(start, end)
        self.assertEqual((row, who), ("row 1", "t@abc"))
        self.assertRegex(secs, r"^\d+$")

    def test_an_unwritable_wait_log_never_breaks_the_held_slot(self):
        # the record is best effort: a directory, a reader-less FIFO or a symlink at the path must not raise or block
        st, d = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.addCleanup(lambda: [__import__("shutil").rmtree(x) for x in (st, d)])
        cc = os.path.join(d, ".cc")
        os.makedirs(os.path.join(cc, "dir"))
        fifo, link = os.path.join(cc, "fifo"), os.path.join(cc, "link")
        os.mkfifo(fifo)
        os.symlink(os.path.join(cc, "target"), link)
        for wl in (os.path.join(cc, "dir"), fifo, link):
            ran = []
            with mock.patch.dict(os.environ, {"HOME": d, "LANDER_WAIT_LOG": wl}):
                with A.slot(st, psi_root=self.psi_dir(0, 0), k=1, who="t"):
                    ran.append(wl)
            self.assertEqual(ran, [wl])
        self.assertFalse(os.path.exists(os.path.join(cc, "target")))

    def test_a_wait_note_cannot_plant_a_status_field(self):
        # a check name comes from the tree's TOML; a newline in it must not add an exit= line cc-green reads first
        note = tempfile.mktemp()
        self.addCleanup(lambda: os.path.exists(note) and os.unlink(note))
        with mock.patch.object(A, "_noted", False), mock.patch.dict(os.environ, {"LANDER_WAIT_NOTE": note}):
            A._note("x\nexit=0")
        with open(note) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertFalse(any(l.startswith("exit=") for l in lines), lines)

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

    def lanes_first_queue(self, name):
        """A slots dir whose queue holds one live (locked) ticket, `name`."""
        st = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(st))
        q = os.path.join(st, "slots", "queue")
        os.makedirs(q)
        f = open(os.path.join(q, name), "a")
        fcntl.flock(f, fcntl.LOCK_EX)
        self.addCleanup(f.close)
        return st

    def test_a_lanes_wait_goes_before_an_older_workers(self):
        import time
        st = self.lanes_first_queue(f"{time.time_ns() - 120 * 10**9:020d}-4242-0000beef")   # a worker, 2 min in
        with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, deadline=1, say=lambda _: None, lane=True) as held:
            self.assertEqual(held, [1])
        said = []   # and a worker's wait still goes behind it
        with self.assertRaises(TimeoutError):
            with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, poll=0.02, deadline=0.2, say=said.append):
                pass
        self.assertIn("1 waiting ahead of it, the oldest pid 4242, 2 min", said[0])

    def test_a_workers_wait_goes_behind_a_newer_lanes(self):
        import time
        st = self.lanes_first_queue(f"+{time.time_ns() + 60 * 10**9:019d}-4343-0000cafe")   # a lane, newer than us
        said = []
        with self.assertRaises(TimeoutError):
            with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, poll=0.02, deadline=0.2, say=said.append):
                pass
        self.assertIn("1 waiting ahead of it, the oldest pid 4343", said[0])
        # between two lanes the older goes first, as before
        with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, deadline=1, say=lambda _: None, lane=True) as held:
            self.assertEqual(held, [1])

    def test_a_prove_hold_holds_the_lane_and_lets_its_own_sweep_through(self):
        # PROVE HOLD: "the lane admits no new checks while a prove runs" — but the sweep that names the hold does
        import time
        now = time.time_ns()
        hold = f"+{now - 60 * 10**9:019d}-4545-0000a0a0"   # lander-self's, a minute in
        st = self.lanes_first_queue(hold)
        q = os.path.join(st, "slots", "queue")
        lane = open(os.path.join(q, f"+{now - 30 * 10**9:019d}-4646-0000b0b0"), "a")   # a lane waiter behind it
        fcntl.flock(lane, fcntl.LOCK_EX)
        self.addCleanup(lane.close)
        said = []
        with self.assertRaises(TimeoutError):   # the lane's next check waits behind the hold
            with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, poll=0.02, deadline=0.2, say=said.append, lane=True):
                pass
        self.assertIn("2 waiting ahead of it, the oldest pid 4545", said[0])
        self.assertEqual(A.free(st, self.psi_dir(0, 0), 2), 0)   # so the lane sends what it can to the runners
        with mock.patch.dict(os.environ, {"LANDER_PROVE_HOLD": hold}):
            self.assertEqual(A._ahead(q, "~")[:2], (0, None))   # neither the hold nor the lane behind it counts
            self.assertEqual(A.free(st, self.psi_dir(0, 0), 2), 2)
            with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, deadline=1, say=lambda _: None) as held:
                self.assertEqual(held, [1])
        older = open(os.path.join(q, f"+{now - 90 * 10**9:019d}-4747-0000c0c0"), "a")   # a waiter from before it
        fcntl.flock(older, fcntl.LOCK_EX)
        self.addCleanup(older.close)
        with mock.patch.dict(os.environ, {"LANDER_PROVE_HOLD": hold}):
            self.assertEqual(A._ahead(q, "~")[:2], (1, os.path.basename(older.name)))   # still goes first
        with mock.patch.dict(os.environ, {"LANDER_PROVE_HOLD": "!not-a-ticket"}):
            self.assertEqual(A._ahead(q, "~")[0], 3)   # a name no ticket has bounds nothing
        older.close()
        # lander-self crashed: its flock is gone, and the next waiter removes the ticket and goes on
        q_hold = os.path.join(q, hold)
        os.rename(q_hold, q_hold + ".x")   # the held file moves off a ticket's name; an unlocked one takes its place
        open(q_hold, "a").close()
        self.assertEqual(A._ahead(q, "~")[:2], (1, os.path.basename(lane.name)))
        self.assertFalse(os.path.exists(q_hold))

    def test_a_first_ticket_goes_before_older_lane_and_worker_waits_and_behind_a_prove_hold(self):
        # FIRST CLAIM (brief, 10-13: main health's and a main-red fix's checks get "first claim on a free slot, ahead of
        # ordinary PR checks"): its ticket is a lane's, FIRST_BACK s back, which is less than a prove hold's 3600 s
        import time
        now = time.time_ns()
        st = self.lanes_first_queue(f"+{now - 120 * 10**9:019d}-4242-0000beef")   # a lane's check, 2 min in
        q = os.path.join(st, "slots", "queue")
        worker = open(os.path.join(q, f"{now - 600 * 10**9:020d}-4343-0000cafe"), "a")   # a worker's, 10 min in
        fcntl.flock(worker, fcntl.LOCK_EX)
        self.addCleanup(worker.close)
        said = []   # suppressed: an ordinary lane check waits behind the older lane ticket
        with self.assertRaises(TimeoutError):
            with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, poll=0.02, deadline=0.2, say=said.append, lane=True):
                pass
        self.assertIn("1 waiting ahead of it, the oldest pid 4242", said[0])
        with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, deadline=1, say=lambda _: None, lane=True,
                    first=True) as held:   # kept: the first claim goes ahead of both
            self.assertEqual(held, [1])
        hold = open(os.path.join(q, f"+{now - 3600 * 10**9:019d}-4545-0000a0a0"), "a")   # a prove hold, 3600 s back
        fcntl.flock(hold, fcntl.LOCK_EX)
        self.addCleanup(hold.close)
        said = []
        with self.assertRaises(TimeoutError):   # and behind a prove hold
            with A.slot(st, psi_root=self.psi_dir(0, 0), k=2, poll=0.02, deadline=0.2, say=said.append, first=True):
                pass
        self.assertIn("1 waiting ahead of it, the oldest pid 4545", said[0])
        self.assertLess(A.FIRST_BACK, 3600)

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
        # and the ALONE GATE with it: kept, the older waiter's check could never take it shared, and the two wait
        # on each other forever
        self.assertTrue(self._until(lambda: free(os.path.join(st, "slots", "alone"))))
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
        # a laptop-only check has no box to ask, so its red stands once the laptop says it twice
        seen.clear()
        o = RUN.judge(chk(where=["laptop"]), self.H, "", "laptop", runner=run, on_base=False)
        self.assertEqual((o.status, seen), (T.FAILED, ["laptop", "laptop"]))

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

    def test_a_red_not_under_load_is_rerun_once_on_the_same_tree_and_recorded_once(self):
        run, calls = self.runner({self.H: T.FAILED, self.B: T.PASSED})
        rec = mock.Mock()
        o = RUN.judge(chk(), self.H, self.B, runner=run, record=rec)
        self.assertEqual(o.status, T.FAILED)                       # red twice: the PR's
        self.assertEqual(calls, [(self.H, False), (self.B, False), (self.H, False)])
        rec.assert_called_once()

    def test_a_red_then_green_on_the_same_tree_passes_as_a_flake_and_records_nothing(self):
        n = [0]

        def run(check, tree, where, alone=False, **kw):
            n[0] += tree == self.H
            st = T.FAILED if (tree == self.H and n[0] == 1) else T.PASSED
            return T.Result(check=check.name, tree=tree, status=st, extra={"why": st})
        rec = mock.Mock()
        o = RUN.judge(chk(), self.H, self.B, runner=run, record=rec)
        self.assertEqual((o.status, o.note), (T.PASSED, "flaky: red, then green on the same tree"))
        self.assertEqual(n[0], 2)
        rec.assert_not_called()

    def red_then_green(self):
        """A runner whose first head run is red and every later run green, and the head runs it made."""
        n = [0]

        def run(check, tree, where, alone=False, **kw):
            n[0] += tree == self.H
            st = T.FAILED if (tree == self.H and n[0] == 1) else T.PASSED
            return T.Result(check=check.name, tree=tree, status=st, extra={"why": st})
        return run, n

    def test_a_security_check_red_is_never_rerun_so_a_flaky_red_stands(self):
        run, n = self.red_then_green()
        self.assertEqual(RUN.judge(chk(), self.H, self.B, runner=run).status, T.PASSED)    # an ordinary check: flake
        self.assertEqual(n[0], 2)
        run, n = self.red_then_green()
        rec = mock.Mock()
        o = RUN.judge(chk(), self.H, self.B, runner=run, record=rec, security=True)
        self.assertEqual(o.status, T.FAILED)                       # a race in auth code is the PR's at its first red
        self.assertEqual(n[0], 1)
        rec.assert_called_once()

    def test_a_check_the_pr_touches_is_never_rerun_so_a_flaky_red_stands(self):
        run, n = self.red_then_green()
        self.assertEqual(RUN.judge(chk(), self.H, self.B, runner=run).status, T.PASSED)
        self.assertEqual(n[0], 2)
        run, n = self.red_then_green()
        o = RUN.judge(chk(), self.H, self.B, runner=run, touched=True)
        self.assertEqual(o.status, T.FAILED)
        self.assertEqual(n[0], 1)

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

    def test_a_quarantine_row_never_passes_a_manifest_widen_red(self):
        # perms' terms (#1234): manifest-widen's "red blocks as a fault, never advisory"
        m = M.Manifest(checks={}, cwd={})
        run, _ = self.runner({self.H: T.FAILED, self.B: T.PASSED})
        q = f"{M.BUILTIN}\tflaky text\tw\to\t2099-01-01\n"
        with mock.patch.object(REC, "quarantine_rows", return_value=[(M.BUILTIN, "flaky text")]), \
                mock.patch.object(M, "load", return_value=M.Manifest()):
            outs = RUN.run_plan(".", m, T.Plan(checks=[M.BUILTIN]), ["README.md"], self.H, self.B,
                                runner=run, quarantine_text=q)
        self.assertEqual(outs[M.BUILTIN].status, T.FAILED)
        self.assertNotEqual(outs[M.BUILTIN].note, "quarantined")

    def test_after_one_laptop_no_answer_the_rest_of_the_plan_goes_to_the_box(self):
        m = M.Manifest(checks={n: chk(name=n, klass=T.STATIC, where=["box", "laptop"]) for n in ("a", "b")}, cwd={"a": "", "b": ""})
        seen = []

        def run(check, tree, where, alone=False, **kw):
            seen.append(where)
            st = T.UNRUNNABLE if where == "laptop" else T.PASSED
            return T.Result(check=check.name, tree=tree, status=st, extra={"why": "no answer"})
        with mock.patch.object(A, "overloaded", return_value="load 50.0 on 20 cores (at least 2x)"), \
                mock.patch.object(RUN, "laptop_dest", return_value="ccsuite@r"):
            outs = RUN.run_plan(".", m, T.Plan(checks=["a", "b"]), ["README.md"], self.H, "", runner=run)
        self.assertEqual(seen, ["laptop", "box", "box"])
        self.assertEqual([outs[n].status for n in ("a", "b")], [T.PASSED, T.PASSED])

    def test_run_plan_hands_lane_to_the_runner_only_when_asked(self):
        m = M.Manifest(checks={"a": chk(name="a", klass=T.STATIC, where=["box"])}, cwd={"a": ""})
        seen = []

        def run(check, tree, where, alone=False, **kw):
            seen.append(kw.get("lane"))
            return T.Result(check=check.name, tree=tree, status=T.PASSED)
        RUN.run_plan(".", m, T.Plan(checks=["a"]), ["README.md"], self.H, "", runner=run, lane=True)
        RUN.run_plan(".", m, T.Plan(checks=["a"]), ["README.md"], self.H, "", runner=run)
        self.assertEqual(seen, [True, None])

    def test_member_and_laptop_routing(self):
        c = chk(klass=T.STATIC, where=["box", "laptop"])
        self.assertEqual(RUN.choose_where(c, "ann"), "member:ann")
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        write(d.name, {"id_ed25519": "k\n", "remote": "ccsuite@r\n", "known_hosts": "r ssh-ed25519 AAAA\n"})
        p = mock.patch.dict(os.environ, {"CC_SUITES_DIR": d.name})
        p.start()
        self.addCleanup(p.stop)
        with mock.patch.object(A, "overloaded", return_value="load 50.0 on 20 cores (at least 2x)"):
            # an overloaded lander spills: what may leave goes to the runners, hermetic and host included
            self.assertEqual(RUN.choose_where(c), "laptop")
            self.assertEqual(RUN.choose_where(chk(klass=T.HERMETIC, where=["box", "laptop"])), "laptop")
            self.assertEqual(RUN.choose_where(chk(klass=T.HOST, where=["box", "laptop"])), "laptop")
            self.assertEqual(RUN.choose_where(chk(klass=T.HOST, where=["box"])), "box")     # needs this host
            for k in (T.BOX, T.TIMING):
                self.assertEqual(RUN.choose_where(chk(klass=k, where=["box", "laptop"])), "box")
            # the lane saw the runners give no answer a moment ago: the box takes it without waiting out ssh
            self.assertEqual(RUN.choose_where(c, box_only=True), "box")
        with mock.patch.object(A, "overloaded", return_value=""), mock.patch.object(A, "busy", return_value=True), \
                mock.patch.object(A, "free", return_value=1):
            # a quiet lander keeps it (a slot is free here, so the live box's own slots never decide this case) (owner 2026-10-12): busy() is not overloaded(), and nothing leaves
            self.assertEqual(RUN.choose_where(c), "box")
            self.assertEqual(RUN.choose_where(chk(klass=T.HOST, where=["box", "laptop"])), "box")
            # ...unless the lane placed it on the runners (it had no box slot for it): then it goes, if it may
            self.assertEqual(RUN.choose_where(c, runners=True), "laptop")
            self.assertEqual(RUN.choose_where(chk(klass=T.HOST, where=["box"]), runners=True), "box")
            self.assertEqual(RUN.choose_where(chk(klass=T.BOX, where=["box", "laptop"]), runners=True), "box")
            self.assertEqual(RUN.choose_where(c, box_only=True, runners=True), "box")
            self.assertEqual(RUN.choose_where(c, "ann", runners=True), "member:ann")

    def test_spill_when_overloaded_or_every_admission_slot_is_held(self):
        # brief (2026-10-02, #772 ran a check every 8-30 min on 1-2 box slots while the laptop said `free 6`):
        # a calm box whose slots are all held sends what may leave to the runners, rather than wait for a slot
        c = chk(klass=T.STATIC, where=["box", "laptop"])
        st = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, st)
        with mock.patch.object(RUN, "laptop_dest", return_value="ccsuite@r"), \
                mock.patch.object(A, "overloaded", return_value=""), mock.patch.object(A, "slots", return_value=1), \
                mock.patch.dict(os.environ, {"LANDER_STATE": st}):
            self.assertEqual((RUN.spill(), RUN.choose_where(c)), ("", "box"))   # a free slot: it stays
            with A.slot(st, k=1):
                self.assertEqual(RUN.spill(), "every admission slot on this host is held")
                self.assertEqual(RUN.choose_where(c), "laptop")
                self.assertEqual(RUN.choose_where(c, box_only=True), "box")
                self.assertEqual(RUN.choose_where(chk(klass=T.HOST, where=["box"])), "box")   # needs this host
            self.assertEqual((RUN.spill(), RUN.choose_where(c)), ("", "box"))
        with mock.patch.object(A, "overloaded", return_value="load 50.0 on 20 cores (at least 2x)"), \
                mock.patch.object(A, "free", return_value=3):
            self.assertEqual(RUN.spill(), "load 50.0 on 20 cores (at least 2x)")   # overloaded says why first

    def test_spill_when_the_admission_slots_cannot_be_read(self):
        # Opus read: an OSError from A.free() counts as no free slot, so the check spills rather than the lane raising
        c = chk(klass=T.STATIC, where=["box", "laptop"])
        with mock.patch.object(RUN, "laptop_dest", return_value="ccsuite@r"), \
                mock.patch.object(A, "overloaded", return_value=""), \
                mock.patch.object(A, "free", side_effect=PermissionError("denied")):
            self.assertTrue(RUN.spill().startswith("admission slots unreadable"))
            self.assertEqual(RUN.choose_where(c), "laptop")
        with mock.patch.object(RUN, "laptop_dest", return_value="ccsuite@r"), \
                mock.patch.object(A, "overloaded", return_value=""), mock.patch.object(A, "free", return_value=1):
            self.assertEqual((RUN.spill(), RUN.choose_where(c)), ("", "box"))   # readable and free: it stays

    def test_run_plan_sends_the_lanes_runner_placement_on_to_choose_where(self):
        m = M.Manifest(checks={"a": chk(name="a", klass=T.STATIC, where=["box", "laptop"])}, cwd={"a": ""})
        seen = []

        def run(check, tree, where, alone=False, **kw):
            seen.append(where)
            return T.Result(check=check.name, tree=tree, status=T.PASSED)
        with mock.patch.object(RUN, "laptop_dest", return_value="ccsuite@r"), \
                mock.patch.object(RUN, "spill", return_value=""):
            RUN.run_plan(".", m, T.Plan(checks=["a"]), ["README.md"], self.H, "", runner=run, runners=True)
            RUN.run_plan(".", m, T.Plan(checks=["a"]), ["README.md"], self.H, "", runner=run)
        self.assertEqual(seen, ["laptop", "box"])

    def test_an_overloaded_box_sends_check_sh_and_the_e2e_suites_and_keeps_what_needs_it(self):
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
                mock.patch.object(A, "overloaded", return_value="load 50.0 on 20 cores (at least 2x)"):
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


class CheckCaged(Env):
    """`lander check --caged-only`, cc-green's run for a fenced worker: the tree is the worker's, so a host- or box-class
    check, or one that needs the network, a mount or another runner, is deferred to the landing and never run or passed
    (2026-10-11, #1078's Opus reads: a worker edited a host check's script, asked for green, and it ran as the owner)."""

    def setUp(self):
        super().setUp()
        self.mark = os.path.join(self.tmp, "marks")
        os.mkdir(self.mark)
        man = textwrap.dedent(f'''
            [[check]]
            name = "on-host"
            run = "touch {self.mark}/host"
            paths = ["bin/tool"]
            class = "host"

            [[check]]
            name = "on-box"
            run = "touch {self.mark}/box"
            paths = ["bin/tool"]
            class = "box"

            [[check]]
            name = "caged"
            run = "bin/tool | grep -q tool"
            paths = ["bin/tool"]
            class = "hermetic"
        ''')
        # gate-first, so the box-class check is planned before the merge and not only listed for the tip
        write(self.repo, {"core/tests/LANDING.toml": man,
                          "core/tests/LANDING-policy.toml": '[paths]\ngate_first = ["bin/**"]\n'})
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "manifest")
        git(self.repo, "branch", "base")
        write(self.repo, {"core/bin/tool": "#!/bin/sh\necho tool again\n"})

    def check(self, *more):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = CK.cmd_check([self.repo, "--base", "base", *more])
        return rc, out.getvalue()

    @unittest.skipUnless(HAS_BWRAP, "no working bwrap on this machine")
    def test_caged_only_defers_host_and_box_checks_and_runs_none_of_them(self):
        rc, out = self.check("--caged-only")
        self.assertEqual(rc, 0, out)
        self.assertEqual(os.listdir(self.mark), [], out)          # neither script ran
        self.assertIn("deferred on-host", " ".join(out.split()))
        self.assertIn("deferred on-box", " ".join(out.split()))
        self.assertIn("runs at landing: host-class", out)
        self.assertIn("passed   caged", out)                      # the caged one still runs
        self.assertIn("1 passed, 0 failed, 2 deferred to the landing — caged checks only, NOT a full green", out)
        self.assertNotIn("passed   on-", out)

    @unittest.skipUnless(HAS_BWRAP, "no working bwrap on this machine")
    def test_without_it_both_run_as_before(self):
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(os.listdir(self.mark)), ["box", "host"], out)
        self.assertIn("3 passed, 0 failed\n", out)
        self.assertNotIn("deferred", out)

    def test_what_uncaged_names(self):
        c = T.Check(name="x", run="true", klass=T.HERMETIC)
        self.assertEqual(RUN.uncaged(c), "")
        self.assertEqual(RUN.uncaged(dataclasses.replace(c, klass=T.STATIC)), "")
        self.assertIn("host-class", RUN.uncaged(dataclasses.replace(c, klass=T.HOST)))
        self.assertIn("box-class", RUN.uncaged(dataclasses.replace(c, klass=T.BOX)))
        self.assertEqual(RUN.uncaged(dataclasses.replace(c, net=True)), "needs the network")
        self.assertEqual(RUN.uncaged(dataclasses.replace(c, mounts=["~/x"])), "needs host mounts")
        self.assertEqual(RUN.uncaged(dataclasses.replace(c, where=["laptop"])), "runs only on laptop")

    def test_a_caged_plan_never_leaves_the_box(self):
        seen = []

        def runner(check, tree, where, **kw):
            seen.append(where)
            return T.Result(check=check.name, tree=tree, status=T.PASSED, secs=0)
        c = T.Check(name="x", run="true", klass=T.HERMETIC, where=["laptop", "box"])
        m = M.Manifest(checks={"x": c})
        with mock.patch.object(RUN, "laptop_dest", return_value="u@h"), mock.patch.object(A, "overloaded", return_value="load 50.0 on 20 cores (at least 2x)"):
            RUN.run_plan(self.repo, m, T.Plan(checks=["x"]), [], "h", runner=runner, record_reds=False)
            RUN.run_plan(self.repo, m, T.Plan(checks=["x"]), [], "h", runner=runner, record_reds=False, caged=True)
        self.assertEqual(seen, ["laptop", "box"])


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


class Ratchet(unittest.TestCase):
    """Owner, 10-13: "a red check on main stops holding PRs that don't make it worse". judge() with a scripted runner
    whose reds name failing cases (extra.fails, as run() reads them with fail_ids)."""

    H, B = "h" * 40, "b" * 40

    def runner(self, fails, where_of=lambda tree: "box", ran=None):
        """fails: tree -> its failing ids (a list, or None), False (green), or "unrunnable" (no answer). ran: tree -> the
        extra run() reads off a red with RUN.ran ({"passes": n, "crash": bool})."""
        calls = []

        def run(check, tree, where, alone=False, **kw):
            calls.append((tree, alone))
            f = fails[tree]
            st = {False: T.PASSED, "unrunnable": T.UNRUNNABLE}.get(f, T.FAILED) if not isinstance(f, list) \
                else T.FAILED
            return T.Result(check=check.name, tree=tree, status=st, runner=f"{where_of(tree)}:x:-",
                            extra={"loaded": False, "why": st,
                                   **({"fails": f, **(ran or {}).get(tree, {})} if st == T.FAILED else {})})
        return run, calls

    def test_a_head_that_ran_less_or_crashed_where_the_base_did_not_holds(self):
        # Opus and perms, 10-13: "a crash or early abort reads as no new reds"
        fails = {self.H: ["✗ a"], self.B: ["✗ a"]}
        for ran, want in (({self.H: {"passes": 3}, self.B: {"passes": 9}}, RUN.BLOCKED),
                          ({self.H: {"passes": 9, "crash": True}, self.B: {"passes": 9}}, RUN.BLOCKED),
                          ({self.H: {"passes": 9, "crash": True}, self.B: {"passes": 9, "crash": True}}, T.PASSED),
                          ({self.H: {"passes": 9}, self.B: {"passes": 9}}, T.PASSED)):
            run, _ = self.runner(fails, ran=ran)
            self.assertEqual(RUN.judge(chk(name="c"), self.H, self.B, runner=run).status, want, ran)

    def test_ran_reads_passes_and_crashes(self):
        self.assertEqual(RUN.ran("✓ a\n✓ b\n✗ c\n"), {"passes": 2, "failed": 1, "crash": False})
        self.assertEqual(RUN.ran("✓ a\n== 7 passed, 1 failed ==\n"), {"passes": 7, "failed": 1, "crash": False})
        self.assertEqual(RUN.ran("✓ a\nTraceback (most recent call last):\n")["crash"], True)
        self.assertEqual(RUN.ran("✓ a\nSegmentation fault (core dumped)\n")["crash"], True)
        # Opus delta read, 10-13: an indented Traceback and bash's own kill line are crashes; a case naming one is not
        self.assertEqual(RUN.ran("✓ a\n    Traceback (most recent call last):\n")["crash"], True)
        self.assertEqual(RUN.ran("✓ a\n./t.sh: line 1: 123 Killed    python3 x\n")["crash"], True)
        self.assertEqual(RUN.ran("✓ a\n✓ a Killed process is reaped\n")["crash"], False)
        # one case failing twice is two failures
        self.assertEqual(RUN.ran("FAIL a\nFAIL a\n")["failed"], 2)

    def test_a_head_with_more_failures_than_the_base_holds(self):
        # Opus delta read, 10-13: "hold when the head has more failing lines than the base, including no-pass-line
        # suites and an added passing test masking a lost one"
        fails = {self.H: ["FAIL a"], self.B: ["FAIL a"]}
        for ran, want in (({self.H: {"passes": 0, "failed": 2}, self.B: {"passes": 0, "failed": 1}}, RUN.BLOCKED),
                          ({self.H: {"passes": 10, "failed": 2}, self.B: {"passes": 9, "failed": 1}}, RUN.BLOCKED),
                          ({self.H: {"passes": 9, "failed": 1}, self.B: {"passes": 9, "failed": 2}}, T.PASSED),
                          ({self.H: {"passes": 9, "failed": 1}, self.B: {"passes": 9, "failed": 1}}, T.PASSED)):
            run, _ = self.runner(fails, ran=ran)
            self.assertEqual(RUN.judge(chk(name="c"), self.H, self.B, runner=run).status, want, ran)

    def test_run_plan_treats_the_member_wall_the_door_and_security_toml_paths_as_security(self):
        # perms' read of #1305, 10-13: "treat LANDING-security.toml paths plus those two as security and never
        # ratchet them"
        paths = {"wall": "core/bin/cc", "member": "core/bin/cc-member-v2", "door": "bin-private/box-cloudflare",
                 "unit": "config/cloudflare/w.js", "gate": "core/bin/guard", "plain": "core/bin/plain",
                 "other": "bin-private/box-move"}
        m = M.Manifest(checks={n: chk(name=n, paths=[p]) for n, p in paths.items()}, cwd={n: "" for n in paths},
                       policy=T.Policy(gate_first=["core/bin/guard"], security_review=["config/cloudflare/**"]))
        got = {}

        def judge(c, *a, security=False, **kw):
            got[c.name] = security
            return RUN.Outcome(c.name, T.PASSED, "")
        with mock.patch.object(RUN, "judge", judge), mock.patch.object(M, "load", return_value=M.Manifest()):
            RUN.run_plan(".", m, T.Plan(checks=list(paths)), ["README.md"], self.H, self.B)
        self.assertEqual(got, {"wall": True, "member": True, "door": True, "unit": True, "gate": True,
                               "plain": False, "other": False})

    def test_a_stored_base_red_whose_rerun_gives_no_answer_holds_as_main_red(self):
        # Opus and perms, 10-13: "fall back to the stored base red and hold as main-red, never hand the PR back"
        store = self.store()
        run, _ = self.runner({self.H: ["✗ a"], self.B: ["✗ a"]})
        store.put_base(run(chk(), self.B, "box"))
        run, calls = self.runner({self.H: ["✗ a"], self.B: "unrunnable"})
        rec = mock.Mock()
        o = RUN.judge(chk(), self.H, self.B, runner=run, store=store, job_key="repo-1", record=rec)
        self.assertEqual((o.status, o.note), (RUN.BLOCKED, "blocked-by-main:c"))
        self.assertEqual(calls, [(self.H, False), (self.B, False)])
        rec.assert_not_called()

    def store(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        os.makedirs(os.path.join(d, "lanes"))
        lock = open(os.path.join(d, "lanes", "repo.lock"), "a")
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        REC.new_nonce("repo", d)
        return REC.Store("repo", lock, d)

    def test_a_red_that_main_has_too_passes_and_names_both_sets(self):
        run, calls = self.runner({self.H: ["✗ a"], self.B: ["✗ a", "✗ b"]})
        rec = mock.Mock()
        o = RUN.judge(chk(name="c"), self.H, self.B, runner=run, record=rec)
        self.assertEqual((o.status, o.note[:7]), (T.PASSED, "ratchet"))
        self.assertEqual(o.sets, {"pr": ["✗ a"], "main": ["✗ a", "✗ b"]})
        self.assertEqual(calls, [(self.H, False), (self.B, False)])   # no rerun of the head: main's red explains it
        rec.assert_not_called()

    def test_a_red_main_lacks_still_holds(self):
        run, _ = self.runner({self.H: ["✗ a", "✗ new"], self.B: ["✗ a"]})
        o = RUN.judge(chk(name="c"), self.H, self.B, runner=run)
        self.assertEqual((o.status, o.note), (RUN.BLOCKED, "blocked-by-main:c"))
        self.assertEqual(o.sets, {"pr": ["✗ a", "✗ new"], "main": ["✗ a"]})

    def test_a_suite_that_names_nothing_falls_back_to_the_exit_code_and_holds(self):
        for head, base in (([], ["✗ a"]), ([], []), (["✗ a"], []), (None, ["✗ a"]), (["✗ a"], None)):
            run, _ = self.runner({self.H: head, self.B: base})
            o = RUN.judge(chk(name="c"), self.H, self.B, runner=run)
            self.assertEqual(o.status, RUN.BLOCKED, (head, base))

    def test_a_shared_base_red_is_run_again_now_before_it_lets_a_pr_through(self):
        store = self.store()
        run, calls = self.runner({self.H: ["✗ a"], self.B: ["✗ a"]})
        RUN.judge(chk(), self.H, self.B, runner=run, store=store, job_key="repo-1")
        calls.clear()
        o = RUN.judge(chk(), self.H, self.B, runner=run, store=store, job_key="repo-2")
        self.assertEqual(o.status, T.PASSED)
        self.assertEqual(calls, [(self.H, False), (self.B, False)])   # the stored red was not taken on its word
        # main fixed since (the host state the stored red was made in is gone): the fresh base is green, so the
        # PR's red is its own, said twice on its tree
        run, calls = self.runner({self.H: ["✗ a"], self.B: False})
        o = RUN.judge(chk(), self.H, self.B, runner=run, store=store, job_key="repo-3")
        self.assertEqual(o.status, T.FAILED)
        self.assertEqual(store.base("c", self.B).status, T.PASSED)
        # a stored red that already shows a new red holds without a base run
        run, calls = self.runner({self.H: ["✗ new"], self.B: ["✗ a"]})
        store.put_base(run(chk(), self.B, "box"))
        calls.clear()
        o = RUN.judge(chk(), self.H, self.B, runner=run, store=store, job_key="repo-4")
        self.assertEqual((o.status, calls), (RUN.BLOCKED, [(self.H, False)]))

    def test_never_for_a_security_check_a_touched_check_or_runs_in_two_places(self):
        run, _ = self.runner({self.H: ["✗ a"], self.B: ["✗ a"]})
        self.assertEqual(RUN.judge(chk(), self.H, self.B, runner=run, security=True).status, RUN.BLOCKED)
        self.assertEqual(RUN.judge(chk(), self.H, self.B, runner=run, touched=True).status, RUN.BLOCKED)
        self.assertEqual(RUN.judge(chk(), self.H, self.B, runner=run).status, T.PASSED)   # the same pair, untouched
        run, _ = self.runner({self.H: ["✗ a"], self.B: ["✗ a"]}, where_of=lambda t: "laptop" if t == self.H else "box")
        self.assertEqual(RUN.judge(chk(), self.H, self.B, runner=run).status, RUN.BLOCKED)


class FailIds(unittest.TestCase):
    def test_a_suites_failing_lines_with_their_scratch_blanked(self):
        text = "\n".join([
            "  ✓ fine", "  ✗ cc-context reads /tmp/tmp.Xy12ab/state", "FAIL: race at " + "abcdef0123" * 4,
            "FAILED tests/x.py::test_a - AssertionError: 1 != 2", "not ok 7 - tap case", "Traceback (most recent call",
            "== result: 3 passed, 4 failed ==", "ok 8 - tap fine"])
        self.assertEqual(RUN.fail_ids(text), sorted([
            "✗ cc-context reads /tmp/…", "FAIL: race at …", "FAILED tests/x.py::test_a", "not tap case"]))
        same = RUN.fail_ids("  ✗ cc-context reads /tmp/tmp.Qq99zz/state")
        self.assertTrue(set(same) <= set(RUN.fail_ids(text)))   # another run's scratch is the same case
        self.assertEqual(RUN.fail_ids("exit 1 and nothing to say\nTraceback x"), [])
        self.assertIsNone(RUN.fail_ids("\n".join(f"✗ case {i}" for i in range(RUN.FAILS_CAP + 1))))
        # an ERROR line is a case only in pytest's summary form; a log's own ERROR line names none (Opus read, 10-13)
        self.assertEqual(RUN.fail_ids("ERROR: port 4123 in use\nERROR connecting to db\n"
                                      "ERROR tests/y.py::test_b - OSError\nERROR tests/z.py\n"),
                         ["ERROR tests/y.py::test_b", "ERROR tests/z.py"])
        # ...and in unittest's form, so an error moving between tests is a new id (Opus delta read, 10-13)
        self.assertEqual(RUN.fail_ids("ERROR: test_q (m.C)\nERROR: test_q failed to start\n"),
                         ["ERROR: test_q (m.C)"])
        # only a scratch path and a full sha are blanked: a duration or a short id is part of the case (same read)
        self.assertNotEqual(RUN.fail_ids("✗ done after 900 s"), RUN.fail_ids("✗ done after 31 s"))
        self.assertNotEqual(RUN.fail_ids("✗ job 12345678"), RUN.fail_ids("✗ job 87654321"))


if __name__ == "__main__":
    unittest.main()
