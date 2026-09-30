"""lander tick after a merge, end to end on a fixture repo: the tip run, the deploy, the job settling.

A real bare origin, a real checkout under $CC_DEV and a real install.sh; the tip's box check runs through U2's runner
(no systemd scope: LANDER_SCOPE=0). Only systemctl, cc-units, cc-scope, cc-slack and gh are answered by a fake
(cards.sh routes them; git and install.sh go through), and systemd-run / systemctl for the tick's timer and cc-pause
are stub scripts. Nothing waits on a wall clock. Run:
python3 -m unittest discover -s core/tests/lander -t core/tests/lander -p 'test_u5_tick.py'
"""
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from lander import cards as C  # noqa: E402
from lander import deploy as D  # noqa: E402
from lander import events as E  # noqa: E402
from lander import git as G  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import tick as TK  # noqa: E402
from lander import tip as TP  # noqa: E402
from lander import types as T  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
MANIFEST = '[[check]]\nname = "smoke"\nrun = "test ! -e app/BROKEN"\npaths = ["app/**"]\nclass = "box"\ncap = 300\n'
INSTALL = '#!/bin/sh\necho "$(git rev-parse HEAD)" >> "$U5_MARK"\ncp systemd-user/*.service "$CC_UNITS_DIR"/ 2>/dev/null\nexit 0\n'
SERVICE = "[Service]\nExecStart=/usr/bin/true\n[Install]\nWantedBy=default.target\n"


class Tick(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lander-u5-tick.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        land = os.path.join(self.tmp, "land")
        self.bin = os.path.join(self.tmp, "bin")
        self.units = os.path.join(self.tmp, "units")
        self.mark = os.path.join(self.tmp, "installed")
        for d in (self.bin, self.units, os.path.join(self.tmp, "boards")):
            os.makedirs(d)
        env = {"CC_LAND_STATE": land, "CC_LANDER_STATE": land, "LANDER_STATE": land, "HOME": self.tmp,
               "CC_LAND_SCRATCH": os.path.join(self.tmp, "scratch"), "CC_DEV": os.path.join(self.tmp, "dev"),
               "CC_BOARDS": os.path.join(self.tmp, "boards"), "CC_CONFIG": os.path.join(self.tmp, "config"),
               "CC_SLACK_DIR": os.path.join(self.tmp, "slack"), "CC_UNITS_DIR": self.units, "CC_BIN": self.bin,
               "CC_MEMBERS": os.path.join(self.tmp, "members"), "LANDER_SCOPE": "0", "U5_MARK": self.mark,
               "LANDER_SYSTEMD_RUN": os.path.join(self.bin, "systemd-run"),
               "LANDER_SYSTEMCTL": os.path.join(self.bin, "systemctl"), **GIT_ENV}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for k in ("GH_TOKEN", "CC_SLACK_ALIAS", "CC_ROLE"):
            os.environ.pop(k, None)
        # nothing reads the box's own ~/.cc/state/land or config: every state root falls back to the passwd home
        for name, val in (("PASSWD_HOME", self.tmp), ("REVIEWER_CONFIG", os.path.join(self.tmp, ".cc", "config"))):
            p = mock.patch.object(C, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(G, "ALLOW_LOCAL", True)   # the pinned URL is this bare repo, not GitHub
        p.start()
        self.addCleanup(p.stop)
        self.arms = os.path.join(self.tmp, "arms")
        self.stub("cc-pause", "exit 1")
        self.stub("cc-tier", "exit 0")
        self.stub("systemctl", "exit 0")
        self.stub("systemd-run", f'echo "$*" >> "{self.arms}"')
        # the fixture: a bare origin, a work clone that makes the merges, the box's checkout under CC_DEV
        self.origin = os.path.join(self.tmp, "origin.git")
        self.work = os.path.join(self.tmp, "work")
        self.root = os.path.join(self.tmp, "dev", "demo")
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", self.origin)
        self.git(self.tmp, "clone", "-q", self.origin, self.work)
        self.git(self.work, "checkout", "-q", "-b", "main")
        self.put({"tests/LANDING.toml": MANIFEST, "install.sh": INSTALL, "app/x": "1\n"}, "first")
        self.git(self.tmp, "clone", "-q", self.origin, self.root)
        self.first = self.git(self.root, "rev-parse", "HEAD")
        os.makedirs(os.path.join(self.tmp, ".cc", "lander"))
        with open(os.path.join(self.tmp, ".cc", "lander", "remotes.json"), "w") as f:
            json.dump({os.path.realpath(self.root): self.origin}, f)   # what `lander-self promote` pins
        # the fake box: every call cards.sh makes to a tool the box owns
        self.calls, self.policy, self.scope = [], "box", {"list": (0, "[]"), "deliver": (0, "")}
        real = C.sh

        def sh(argv, cwd=None, input=None, timeout=300, env=None):
            tool = os.path.basename(argv[0])
            if tool in ("systemctl", "cc-units", "cc-scope", "cc-slack", "gh", "cc-notify"):
                self.calls.append([tool] + list(argv[1:]))
                if tool == "systemctl":
                    return {"is-active": (0, "active\n"), "is-enabled": (1, "disabled\n"),
                            "show": (0, "100\n")}.get(argv[2], (0, ""))
                if tool == "cc-units":
                    return (0, self.policy + "\n") if argv[1] == "policy" else (0, "")
                if tool == "cc-scope":
                    return self.scope.get(argv[1], (0, ""))
                return 0, ""
            return real(argv, cwd=cwd, input=input, timeout=timeout, env=env)
        p = mock.patch.object(C, "sh", sh)
        p.start()
        self.addCleanup(p.stop)

    # --- helpers ---
    def stub(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write(f"#!/bin/sh\n{body}\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    def git(self, cwd, *a):
        return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    def put(self, files, subject, rm=()):
        for rel, text in files.items():
            path = os.path.join(self.work, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
            if rel.endswith(".sh"):
                os.chmod(path, 0o755)
        for rel in rm:
            self.git(self.work, "rm", "-q", rel)
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-qm", subject)
        self.git(self.work, "push", "-q", "origin", "HEAD:main")
        return self.git(self.work, "rev-parse", "HEAD")

    def merged(self, files, subject="a change (#7)", pr=7):
        """What the lane leaves after a merge: the squash on origin, the job deploy-pending, a tip kick, a request."""
        sha = self.put(files, subject)
        J.save(T.Job(repo="demo", pr=pr, state=T.DEPLOY_PENDING,
                     extra={"tip_sha": sha, "queued_at": E.stamp(), "post": {"tip": "ok", "deploy": "ok"}}))
        TP.kick("demo")
        D.request("demo", sha, [])
        return sha

    def tick(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(TK.cmd_tick(["--repo", "demo"]), 0)
        return out.getvalue()

    def installs(self):
        try:
            with open(self.mark) as f:
                return f.read().split()
        except OSError:
            return []

    def log(self):
        with open(os.path.join(J.landq(), "queue.log")) as f:
            return f.read()

    def said(self, needle):
        return [c for c in self.calls if c[0] == "cc-slack" and any(needle in a for a in c)]

    # --- cases ---
    def test_a_merge_is_tip_checked_deployed_and_the_job_done(self):
        D.record_applied("demo", self.first)
        sha = self.merged({"app/x": "2\n"})
        out = self.tick()
        self.assertIn("tip run: green", out)
        self.assertTrue(TP.green("demo", sha))
        self.assertEqual(self.installs(), [sha])                                  # install.sh ran once, on the tip
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), sha)           # the checkout fast-forwarded
        self.assertEqual(D.applied("demo"), sha)
        self.assertIn(["systemctl", "--user", "daemon-reload"], self.calls)
        job = J.load("demo", 7)
        self.assertEqual(job.state, T.DONE)
        self.assertEqual([h["state"] for h in job.history], [T.DEPLOYED, T.DONE])
        self.assertIn("done demo#7 rc=0", self.log())
        self.assertFalse(os.path.exists(TP.want_path("demo")))
        self.assertEqual(TK.waits("demo"), [])                                   # nothing left to wake for
        self.tick()                                                               # idempotent: nothing again
        self.assertEqual(self.installs(), [sha])

    def test_a_red_tip_holds_the_deploy_and_reverts_the_proven_breaker(self):
        D.record_applied("demo", self.first)
        bad = self.merged({"app/BROKEN": "x\n"}, subject="breaks the smoke check")
        out = self.tick()
        self.assertIn("tip run: red", out)
        self.assertEqual(self.installs(), [])                                     # nothing red is installed
        self.assertTrue(D.held("demo"))
        self.assertEqual(D.applied("demo"), self.first)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), self.first)
        self.assertIn(bad, C.read_json(C.state("tip", "demo.reverted")))        # proven twice, parent green
        tip = self.git(self.tmp, "--git-dir", self.origin, "rev-parse", "main")
        self.assertNotEqual(tip, bad)
        self.assertIn("Revert", self.git(self.tmp, "--git-dir", self.origin, "log", "-1", "--format=%s", "main"))
        self.assertEqual(J.load("demo", 7).state, T.DONE)
        self.assertIn("done demo#7 rc=1", self.log())
        self.assertTrue(os.path.exists(TP.want_path("demo")))                  # the revert moved the tip: kicked
        self.assertEqual(TK.waits("demo"), [TK.TICK_SECS])
        self.tick()                                                               # the reverted tip is green
        self.assertEqual(self.installs(), [tip])
        self.assertFalse(D.held("demo"))

    def test_an_added_unit_the_owner_keeps_gets_a_card_not_an_enable(self):
        D.record_applied("demo", self.first)
        self.policy = "owner"
        self.merged({"systemd-user/new.service": SERVICE})
        self.tick()
        self.assertTrue(os.path.exists(os.path.join(self.units, "new.service")))   # linked by install.sh
        self.assertIn(["cc-units", "policy", "new.service", "enable"], self.calls)
        self.assertFalse([c for c in self.calls if c[:3] == ["systemctl", "--user", "enable"]])
        card = [c for c in self.calls if c[:3] == ["cc-notify", "--approval", "--run"]]
        self.assertEqual(len(card), 1)                    # the owner's 👍 runs the enable the card carries
        self.assertEqual(card[0][3], "systemctl --user enable --now new.service")
        self.assertEqual(J.load("demo", 7).state, T.DONE)

    def test_an_added_unit_is_enabled_when_policy_allows(self):
        D.record_applied("demo", self.first)
        self.merged({"systemd-user/new.service": SERVICE})
        self.tick()
        self.assertIn(["systemctl", "--user", "enable", "--now", "new.service"], self.calls)
        self.assertFalse(self.said("enable --now new.service"))

    def test_an_unchecked_ask_is_unverified_said_once_and_done_rc_4(self):
        D.record_applied("demo", self.first)
        with open(os.path.join(os.environ["CC_BOARDS"], "demo.json"), "w") as f:
            json.dump({"tracks": {"row-a": {"pr": "7", "status": "running"}}}, f)
        self.scope = {"list": (0, json.dumps([{"id": "s1", "status": "merged", "text": "do a thing"}])),
                      "deliver": (2, "names no check")}
        self.merged({"app/x": "3\n"})
        self.tick()
        self.assertIn(["cc-scope", "deliver", "demo", "s1"], self.calls)
        self.assertEqual(len(self.said("NOT delivered")), 1)
        self.assertIn("done demo#7 rc=4", self.log())
        self.assertEqual(D.outcome(C.read_json(D.req_path("demo"))), 4)
        self.tick()
        self.assertEqual(len(self.said("NOT delivered")), 1)

    def test_a_hand_merge_is_caught_up_and_a_first_sight_seeds_applied(self):
        self.tick()                                                               # first sight: seeds, no deploy
        self.assertEqual(D.applied("demo"), self.first)
        self.assertEqual(self.installs(), [])
        sha = self.put({"app/x": "hand\n"}, "merged by hand elsewhere")
        os.unlink(C.state("tip", "demo.catchup"))                               # the poll is due again
        out = self.tick()
        self.assertIn("origin moved past what this box runs", out)
        self.assertEqual(self.installs(), [sha])
        self.assertEqual(D.applied("demo"), sha)

    def test_a_tip_the_old_lander_marked_red_is_not_caught_up(self):
        self.tick()
        sha = self.put({"app/x": "hand\n"}, "merged by hand elsewhere")
        C.write_json(C.state("demo.red"), {"tip": sha, "why": "the old suite"})
        os.unlink(C.state("tip", "demo.catchup"))
        self.tick()
        self.assertFalse(os.path.exists(TP.want_path("demo")))
        self.assertEqual(self.installs(), [])

    def test_the_tick_rearms_itself_while_a_deploy_waits_and_not_after(self):
        D.record_applied("demo", self.first)
        self.merged({"app/x": "4\n"})
        with mock.patch.object(TK, "tip_and_deploy", lambda repo, units: []):   # a tick that did not get to it
            self.tick()
        with open(self.arms) as f:
            armed = f.read().split("\n")[0].split()
        self.assertEqual(armed[:2], ["--user", f"--on-active={TK.TICK_SECS + 1}"])
        self.assertEqual(armed[-3:], ["--repo", "demo", "--rearm"])
        os.unlink(self.arms)
        self.tick()                                                               # deployed and settled: no timer
        self.assertFalse(os.path.exists(self.arms))

    def test_a_second_tick_skips_a_tip_run_already_going(self):
        with TP.lock("demo") as got:
            self.assertTrue(got)
            self.assertIn("a tip run is already going", self.tick())

    def test_a_busy_lane_does_not_keep_a_deployed_job_pending(self):
        # merged PRs sat deploy-pending for hours: the lane gated back to back and settle waited on its lock.
        D.record_applied("demo", self.first)
        sha = self.merged({"app/x": "5\n"})
        with J.lane_lock("demo") as got:
            self.assertTrue(got)
            self.tick()
        self.assertEqual(D.applied("demo"), sha)
        self.assertEqual(J.load("demo", 7).state, T.DONE)
        self.assertIn("done demo#7 rc=0", self.log())

    def test_a_second_tick_skips_the_settle_while_one_holds_the_rest_lock(self):
        D.record_applied("demo", self.first)
        self.merged({"app/x": "6\n"})
        with mock.patch.object(TK, "settle", lambda repo: []):   # deployed, not yet settled
            self.tick()
        with J.rest_lock("demo") as got:   # held by another tick (this test calls settle itself: its lane's
            self.assertTrue(got)           # drain would wait on this lock)
            self.assertEqual(TK.settle("demo"), [])
            self.assertEqual(TK.retry_deploys(["demo"]), [])
            self.assertEqual(J.load("demo", 7).state, T.DEPLOY_PENDING)
        self.tick()
        self.assertEqual(J.load("demo", 7).state, T.DONE)

    def test_a_deploy_retry_leaves_a_job_a_settle_ended(self):
        D.record_applied("demo", self.first)
        self.merged({"app/x": "7\n"})
        stale = J.load("demo", 7)
        stale.extra["post"].pop("deploy")
        self.tick()
        self.assertEqual(J.load("demo", 7).state, T.DONE)
        with mock.patch.object(J, "lane_jobs", lambda repo: [stale]):
            self.assertEqual(TK.retry_deploys(["demo"]), [])
        self.assertEqual(J.load("demo", 7).state, T.DONE)

    def test_a_drain_waits_for_a_settle_holding_the_rest_lock(self):
        import threading
        J.submit("demo", 8, who="test")
        out = []
        with J.rest_lock("demo") as got:
            self.assertTrue(got)
            t = threading.Thread(target=lambda: out.extend(J.drain("demo")))
            t.start()
            t.join(0.3)
            self.assertTrue(t.is_alive())
            self.assertIsNone(J.load("demo", 8))
        t.join(10)
        self.assertEqual(out, ["demo#8 queued"])


    # --- a worker can write the checkout's shared .git: nothing it plants there runs as the lander ---
    def plant(self):
        """Hooks, a merge driver and a smudge filter in the checkout, each leaving its name in `ran` if it runs."""
        ran = os.path.join(self.tmp, "ran")
        gd = os.path.join(self.root, ".git")
        for hook in ("post-checkout", "post-merge", "pre-push", "reference-transaction", "post-commit",
                     "pre-commit", "prepare-commit-msg", "commit-msg"):
            path = os.path.join(gd, "hooks", hook)
            with open(path, "w") as f:
                f.write(f'#!/bin/sh\necho {hook} >> "{ran}"\ncat >/dev/null\nexit 0\n')
            os.chmod(path, 0o755)
        self.git(self.root, "config", "merge.evil.driver", f'sh -c \'echo driver >> "{ran}"; echo pwned > "$0"\' %A')
        self.git(self.root, "config", "filter.x.smudge", f'sh -c \'echo smudge >> "{ran}"; echo pwned\'')
        with open(os.path.join(gd, "info", "attributes"), "w") as f:
            f.write("* merge=evil filter=x\n")
        with open(os.path.join(self.root, ".gitattributes"), "w") as f:
            f.write("* merge=evil filter=x\n")
        return ran

    def ran(self, path):
        try:
            with open(path) as f:
                return f.read().split()
        except OSError:
            return []

    def test_a_revert_runs_no_hook_or_merge_driver_of_the_checkouts(self):
        lines = [f"{i}\n" for i in range(1, 9)]
        self.put({"app/x": "".join(lines)}, "eight lines")
        bad = self.put({"app/x": "".join(["one\n"] + lines[1:])}, "breaks line one (#7)")
        tip = self.put({"app/x": "".join(["one\n"] + lines[1:7] + ["eight\n"])}, "touches line eight")
        ran = self.plant()
        made = TP.revert("demo", self.root, "main", bad, "smoke failed")
        self.assertEqual(self.ran(ran), [])                                       # no hook, no driver
        self.assertTrue(made)
        self.assertEqual(self.git(self.tmp, "--git-dir", self.origin, "rev-parse", "main"), made)
        self.assertEqual(self.git(self.tmp, "--git-dir", self.origin, "rev-parse", f"{made}^"), tip)
        self.assertEqual(self.git(self.tmp, "--git-dir", self.origin, "show", f"{made}:app/x"),
                         "".join(lines[:7] + ["eight\n"]).strip())               # the change undone, the rest kept
        self.assertEqual(self.git(self.tmp, "--git-dir", self.origin, "log", "-1", "--format=%B", made),
                         f'Revert "breaks line one (#7)"\n\nThis reverts commit {bad}.')
        self.assertEqual(self.git(self.root, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertIn(bad, C.read_json(C.state("tip", "demo.reverted")))

    def test_a_revert_that_conflicts_pushes_nothing(self):
        self.put({"app/x": "a\n"}, "one line")
        bad = self.put({"app/x": "2\n"}, "breaks it (#7)")
        tip = self.put({"app/x": "3\n"}, "rewrites the same line")
        self.assertEqual(TP.revert("demo", self.root, "main", bad, "smoke failed"), "")
        self.assertEqual(self.git(self.tmp, "--git-dir", self.origin, "rev-parse", "main"), tip)
        self.assertTrue(self.said("the revert did not happen"))

    def test_a_merge_commit_is_not_reverted(self):
        self.git(self.work, "checkout", "-q", "-b", "side")
        with open(os.path.join(self.work, "app", "y"), "w") as f:
            f.write("y\n")
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-qm", "side")
        self.git(self.work, "checkout", "-q", "main")
        self.put({"app/z": "z\n"}, "main side")
        self.git(self.work, "merge", "-q", "--no-edit", "side")
        self.git(self.work, "push", "-q", "origin", "HEAD:main")
        merge = self.git(self.work, "rev-parse", "HEAD")
        self.assertEqual(TP.revert("demo", self.root, "main", merge, "smoke failed"), "")
        self.assertEqual(self.git(self.tmp, "--git-dir", self.origin, "rev-parse", "main"), merge)
        self.assertTrue(self.said("the revert did not happen"))

    def test_a_pull_runs_no_hook_or_filter_of_the_checkouts(self):
        self.put({"app/y": "y\n"}, "adds y")
        sha = self.put({"app/x": "2\n"}, "a change", rm=["app/y"])
        before = self.git(self.root, "rev-parse", "HEAD")
        with open(os.path.join(self.root, "app", "untracked"), "w") as f:
            f.write("mine\n")
        ran = self.plant()
        changes = D.pull(self.root, "main", sha)
        self.assertEqual(self.ran(ran), [])                                       # no hook, no smudge
        self.assertEqual(sorted(changes), [("M", "app/x")])
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), sha)
        self.assertEqual(self.git(self.root, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        with open(os.path.join(self.root, "app", "x")) as f:
            self.assertEqual(f.read(), "2\n")
        self.assertFalse(os.path.exists(os.path.join(self.root, "app", "y")))
        with open(os.path.join(self.root, "app", "untracked")) as f:
            self.assertEqual(f.read(), "mine\n")
        self.assertEqual(self.git(self.root, "reflog", "-1", "--format=%H", "main"), sha)
        self.assertNotEqual(before, sha)
        self.assertEqual(self.git(self.root, "status", "--porcelain", "--untracked-files=no"), "")   # the index too

    def test_a_pull_that_is_not_a_fast_forward_moves_nothing(self):
        self.git(self.root, "commit", "-q", "--allow-empty", "-m", "local only")
        here = self.git(self.root, "rev-parse", "HEAD")
        sha = self.put({"app/x": "2\n"}, "a change")
        with self.assertRaises(D.Failed) as got:
            D.pull(self.root, "main", sha)
        self.assertEqual(got.exception.step, "pull")
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), here)
        with open(os.path.join(self.root, "app", "x")) as f:
            self.assertEqual(f.read(), "1\n")

    def test_a_pull_over_a_changed_file_moves_nothing(self):
        sha = self.put({"app/x": "2\n"}, "a change")
        with open(os.path.join(self.root, "app", "x"), "w") as f:
            f.write("edited\n")
        with self.assertRaises(D.Failed):
            D.pull(self.root, "main", sha)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), self.first)
        with open(os.path.join(self.root, "app", "x")) as f:
            self.assertEqual(f.read(), "edited\n")


if __name__ == "__main__":
    unittest.main()
