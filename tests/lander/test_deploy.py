"""lander deploy, tip, cards, board and scope: what happens after a merge, with a fake box.

Every case builds its own state, checkout and unit dir under a temp dir; FakeBox (test_review) answers every git,
gh, systemctl and cc-* call, so nothing reaches the box. Run:
python3 -m unittest discover -s core/tests/lander -p 'test_deploy.py'
"""
import contextlib
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from test_review import Case, FakeBox  # noqa: E402

from lander import board as B  # noqa: E402
from lander import cards as C  # noqa: E402
from lander import deploy as D  # noqa: E402
from lander import git as G  # noqa: E402
from lander import scope as S  # noqa: E402
from lander import tip as TP  # noqa: E402
from lander import types as T  # noqa: E402

OLD, NEW = "a" * 40, "c" * 40



def nul(argv, text):
    """A path list as git prints it under -z: every tab and newline a NUL."""
    return text.replace("\t", "\0").replace("\n", "\0") if "-z" in argv else text

class Box(Case):
    def setUp(self):
        super().setUp()
        self.dev = os.path.join(self.tmp, "dev")
        self.units = os.path.join(self.tmp, "units")
        os.environ["CC_DEV"], os.environ["CC_UNITS_DIR"] = self.dev, self.units
        self.root = os.path.join(self.dev, "demo")
        os.makedirs(os.path.join(self.root, ".git"))
        os.makedirs(self.units)
        inst = os.path.join(self.root, "install.sh")
        with open(inst, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(inst, 0o755)
        self.pids = {}
        self.real_running = D.running
        G.REMOTES = os.path.join(self.tmp, "remotes.json")   # what `lander-self promote` pins
        C.write_json(G.REMOTES, {os.path.realpath(self.root): "https://github.com/o/demo.git"})
        # git.fetch and git.ls_remote run real git in a borrowed repo; the fake box answers them instead, as it answers
        # rev-parse refs/remotes/origin/<b> and ls-remote
        def fetch(root, *branches, env=None):
            got = {b: C.sh(["git", "rev-parse", f"refs/remotes/origin/{b}"], cwd=root)[1].strip() for b in branches}
            if not all(G.SHA_RE.fullmatch(v) for v in got.values()):
                raise G.GitError("fetch failed")
            return got

        def ls_remote(root, url, branch, env=None):
            rc, out = C.sh(["git", "ls-remote", url, f"refs/heads/{branch}"], cwd=root)
            rows = [r.split("\t")[0] for r in out.splitlines() if r.endswith(f"\trefs/heads/{branch}")] if rc == 0 else []
            return rows[0] if rows else ""
        # a borrowed repo needs the checkout's real objects; the fake box answers the git run there instead
        def borrowed(root):
            return contextlib.nullcontext(os.path.join(self.tmp, "borrowed.git"))
        for name, fn in (("fetch", fetch), ("ls_remote", ls_remote), ("borrowed", borrowed)):
            p = mock.patch.object(G, name, fn)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        for k in ("CC_DEV", "CC_UNITS_DIR"):
            os.environ.pop(k, None)
        D.running = self.real_running
        G.REMOTES = None
        super().tearDown()

    def unit(self, name, text="[Service]\nExecStart=%h/dev/demo/bin/daemon\n[Install]\nWantedBy=default.target\n"):
        with open(os.path.join(self.units, name), "w") as f:
            f.write(text)

    def fake(self, changes="M\tbin/daemon", branch="main", **kw):
        pids = self.pids

        def git(argv):
            sub = argv[1:]
            if sub[:2] == ["rev-parse", "--abbrev-ref"]:
                return 0, branch + "\n"
            if sub[-1:] == ["--git-dir"]:
                return 0, os.path.join(self.root, ".git") + "\n"
            if sub[:2] == ["rev-parse", "HEAD"]:
                return 0, OLD + "\n"
            if sub[:2] == ["rev-parse", "refs/remotes/origin/main"]:
                return 0, NEW + "\n"
            if sub[:1] == ["ls-remote"]:
                return 0, NEW + "\trefs/heads/main\n"
            if sub[:2] == ["merge-base", "--is-ancestor"]:   # OLD comes before NEW, not after it
                return (1, "") if sub[2:4] == [NEW, OLD] else (0, "")
            if sub[:1] == ["diff"]:
                return 0, nul(argv, changes + "\n")
            if sub[:1] == ["log"]:
                return 0, "a change (#7)\n"
            return 0, ""

        def systemctl(argv):
            verb, u = argv[2], argv[-1]
            if verb == "is-active":
                return 0, "active\n"
            if verb == "is-enabled":
                return 1, "disabled\n"
            if verb == "show":
                return 0, str(pids.get(u, 100)) + "\n"
            if verb == "restart":
                pids[u] = pids.get(u, 100) + (0 if u.startswith("stuck") else 1)
            return 0, ""

        answers = {"git " + k: git for k in ("rev-parse", "diff", "log", "fetch", "merge", "ls-remote", "merge-base",
                                             "update-index", "read-tree", "update-ref")}
        answers.update({"systemctl": systemctl, "install.sh": (0, "linked\n"), "cc-units restart-for": (0, ""),
                        "cc-units daemons-for": (0, ""), "cc-units policy": (0, "box\n"),
                        "cc-scope list": (0, "[]"), "cc-slack post": (0, ""), "cc-slack inject": (0, ""),
                        "cc-board get": (1, "")})
        answers.update(kw)
        C.sh = FakeBox(**answers)
        return C.sh


class TestDeploy(Box):
    def test_request_waits_for_a_green_tip(self):
        box = self.fake()
        D.request("demo", NEW)
        req = D.run("demo", green=lambda r, s: False)
        self.assertEqual(req["targets"]["demo"]["state"], "requested")
        self.assertEqual(box.called("git read-tree"), [])

    def test_green_deploys_ff_only_installs_and_records_applied(self):
        box = self.fake()
        D.request("demo", NEW)
        req = D.run("demo", green=lambda r, s: s == NEW)
        self.assertEqual(req["targets"]["demo"]["state"], "verified")
        self.assertEqual(box.called("git read-tree")[0]["argv"][1:], ["read-tree", "-m", "-u", OLD, NEW])
        self.assertEqual(box.called("git update-ref")[0]["argv"][-3:], ["refs/heads/main", NEW, OLD])
        self.assertEqual(box.called("git merge"), [])        # no merge in the checkout: its hooks would run
        self.assertEqual(len(box.called("install.sh")), 1)
        self.assertIn(["systemctl", "--user", "daemon-reload"], [c["argv"] for c in box.calls])
        self.assertEqual(D.applied("demo"), NEW)
        self.assertEqual(box.called("cc-slack post"), [])      # a clean deploy says nothing: the landed line already went

    def test_a_moved_aside_draft_is_said_without_a_mention_and_a_clean_deploy_says_nothing(self):
        self.fake()
        with mock.patch.object(D, "fast_forward", lambda *a: f"moved 1 {D.MOVED} to /x/deploy-aside: docs/d.md"):
            D.request("demo", NEW)
            st = D.run("demo", green=lambda r, s: s == NEW)["targets"]["demo"]
        self.assertEqual(st["state"], "verified")
        said = C.sh.called("cc-slack post")
        self.assertEqual(len(said), 1)
        self.assertNotIn("--mention", said[0]["argv"])
        self.assertIn("docs/d.md", said[0]["argv"][-1])
        box = self.fake()
        with mock.patch.object(D, "fast_forward", lambda *a: ""):
            D.request("demo", "d" * 40)
            st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertEqual((st["state"], box.called("cc-slack post")), ("verified", []))

    def test_a_moved_aside_draft_is_still_said_when_the_install_then_fails(self):
        box = self.fake(**{"install.sh": (1, "install broke\n")})
        with mock.patch.object(D, "fast_forward", lambda *a: f"moved 1 {D.MOVED} to /x/deploy-aside: docs/d.md"):
            D.request("demo", NEW)
            st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertEqual((st["state"], st["tries"]), ("failed", 1))
        self.assertTrue(st["why"].startswith("install: install.sh: install broke"), st["why"])
        self.assertIn("docs/d.md", st["why"])
        card = box.called("cc-slack post")
        self.assertEqual(len(card), 1)
        self.assertIn("did not deploy", card[0]["argv"][-1])
        self.assertIn(f"{D.MOVED} to /x/deploy-aside: docs/d.md", card[0]["argv"][-1])

    def test_a_moved_aside_draft_rides_on_the_restart_mention(self):
        self.unit("demo-daemon.service")
        box = self.fake(**{"cc-units restart-for": (0, "demo-daemon.service\towner\n"), "cc-scope add": (0, "")})
        with mock.patch.object(D, "fast_forward", lambda *a: f"moved 1 {D.MOVED} to /x/deploy-aside: docs/d.md"):
            D.request("demo", NEW)
            st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertEqual(st["state"], "verified")
        said = box.called("cc-slack post")
        self.assertEqual(len(said), 1)                     # one post: the mention carries the move, no second line
        self.assertIn("--mention", said[0]["argv"])
        self.assertIn("Please restart demo-daemon.service", said[0]["argv"][-1])
        self.assertIn(f"{D.MOVED} to /x/deploy-aside: docs/d.md", said[0]["argv"][-1])

    def test_a_checkout_off_its_branch_is_refused_not_reset(self):
        box = self.fake(branch="feature")
        D.request("demo", NEW)
        st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertEqual(st["state"], "failed")
        self.assertIn("branch", st["why"])
        self.assertEqual(box.called("git read-tree"), [])
        # the owner heard "merged", so a failed deploy is said on #<repo> (--major), once per target and sha
        D.run("demo", green=lambda r, s: True)
        said = box.called("cc-slack post")
        self.assertEqual(len(said), 1)
        self.assertIn("--major", said[0]["argv"])
        self.assertIn("did not deploy", said[0]["argv"][-1])

    def test_a_held_target_waits_and_another_goes(self):
        os.makedirs(os.path.join(self.dev, "demo2", ".git"))
        C.write_json(G.REMOTES, {os.path.realpath(p): "https://github.com/o/demo.git"
                                 for p in (self.root, os.path.join(self.dev, "demo2"))})
        self.fake()
        D.hold("demo", "a check is red")
        D.request("demo", NEW, ["demo", "demo2"])
        req = D.run("demo", green=lambda r, s: True)
        self.assertEqual(req["targets"]["demo"]["state"], "held")
        self.assertEqual(req["targets"]["demo2"]["state"], "verified")
        D.release("demo")
        self.assertIsNone(D.held("demo"))

    def test_a_restart_is_proved_by_a_new_pid(self):
        self.unit("demo-daemon.service")
        self.fake()
        D.request("demo", NEW)
        st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertIn("demo-daemon.service (pid 100 -> 101)", st["why"])

    def test_a_retry_after_a_failed_install_still_restarts_what_changed(self):
        self.unit("demo-daemon.service")
        D.record_applied("demo", OLD)
        at = {"head": OLD}
        box = self.fake(**{"install.sh": (1, "install broke\n"), "git cat-file": (0, "")})
        git = box.answers["git rev-parse"]

        def moved(argv):   # the checkout keeps its fast-forward; a diff from its HEAD is empty
            sub = argv[1:]
            if sub[:1] == ["update-ref"]:
                at["head"] = NEW
            if sub[:2] == ["rev-parse", "HEAD"]:
                return 0, at["head"] + "\n"
            if sub[:1] == ["diff"]:
                return (0, nul(argv, "M\tbin/daemon\n")) if sub[-2] == OLD else (0, "")
            return git(argv)
        box.answers.update({"git " + k: moved for k in ("rev-parse", "diff", "update-ref")})
        D.request("demo", NEW)
        self.assertEqual(D.run("demo", green=lambda r, s: True)["targets"]["demo"]["state"], "failed")
        self.assertEqual(at["head"], NEW)
        box.answers["install.sh"] = (0, "linked\n")
        st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertEqual(st["state"], "verified")
        self.assertIn("demo-daemon.service (pid 100 -> 101)", st["why"])

    def test_a_checkout_already_past_the_sha_deploys_and_moves_nothing(self):
        # `merge --ff-only <sha>` on a checkout already ahead of it was a no-op that succeeded; fast_forward must be too
        ahead = "e" * 40
        box = self.fake()
        git = box.answers["git rev-parse"]

        def past(argv):
            sub = argv[1:]
            if sub[:2] == ["rev-parse", "HEAD"]:
                return 0, ahead + "\n"
            if sub[:2] == ["merge-base", "--is-ancestor"]:
                return (0, "") if sub[2:4] == [NEW, ahead] else (1, "")
            return git(argv)
        box.answers.update({"git " + k: past for k in ("rev-parse", "merge-base")})
        D.request("demo", NEW)
        st = D.run("demo", green=lambda r, s: s == NEW)["targets"]["demo"]
        self.assertEqual(st["state"], "verified", st.get("why"))
        self.assertEqual(box.called("git read-tree") + box.called("git update-ref"), [])

    def test_a_new_request_keeps_the_base_a_failed_restart_still_owes(self):
        self.unit("demo-daemon.service")
        D.record_applied("demo", OLD)
        mid = "d" * 40
        box = self.fake(**{"git cat-file": (0, "")})
        git, sysctl = box.answers["git rev-parse"], box.answers["systemctl"]
        tries = []

        def diff(argv):   # only a diff from OLD sees bin/daemon; MID..NEW changes docs alone
            return 0, nul(argv, "M\tbin/daemon\nM\tdocs/x.md\n" if argv[-2] == OLD else "M\tdocs/x.md\n")

        def systemctl(argv):   # the first restart leaves the pid where it was
            if argv[2] == "restart":
                tries.append(argv[-1])
                if len(tries) == 1:
                    return 0, ""
            return sysctl(argv)
        box.answers.update({"git diff": diff, "systemctl": systemctl, "git rev-parse": git})
        D.request("demo", mid)
        st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertEqual(st["state"], "failed")
        self.assertIn("pid did not change", st["why"])
        self.assertEqual(D.applied("demo"), mid)
        D.request("demo", NEW)
        self.assertEqual(C.read_json(D.req_path("demo"))["from"], OLD)
        st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertEqual(st["state"], "verified")
        self.assertIn("demo-daemon.service (pid 100 -> 101)", st["why"])
        self.assertEqual(len(tries), 2)
        D.request("demo", "9" * 40)   # once every target is verified, the next request starts from what is applied
        self.assertEqual(C.read_json(D.req_path("demo"))["from"], NEW)

    def test_a_restart_whose_pid_did_not_move_fails(self):
        self.unit("stuck.service")
        self.fake()
        D.request("demo", NEW)
        st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertEqual(st["state"], "failed")
        self.assertIn("pid did not change", st["why"])

    def test_tmux_main_is_never_restarted(self):
        self.unit("tmux-main.service")
        box = self.fake()
        D.request("demo", NEW)
        st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertNotIn(["systemctl", "--user", "restart", "tmux-main.service"], [c["argv"] for c in box.calls])
        self.assertIn("never restarted", st["why"])

    def test_a_restart_the_owner_keeps_is_a_ledger_ask_not_a_restart(self):
        self.unit("demo-daemon.service")
        box = self.fake(**{"cc-units restart-for": (0, "demo-daemon.service\towner\n"), "cc-scope add": (0, "")})
        D.request("demo", NEW)
        D.run("demo", green=lambda r, s: True)
        self.assertEqual(len(box.called("cc-scope add")), 1)
        self.assertNotIn("restart", [c["argv"][2] for c in box.called("systemctl")])
        self.assertIn("--mention", box.called("cc-slack post")[0]["argv"])

    def test_an_added_unit_is_enabled_unless_policy_says_owner(self):
        self.unit("new.service")
        self.unit("mine.service")
        box = self.fake(changes="A\tconfig/systemd-user/new.service\nA\tconfig/systemd-user/mine.service",
                        **{"cc-units policy": lambda a: (0, "owner\n" if a[2] == "mine.service" else "box\n")})
        D.request("demo", NEW)
        D.run("demo", green=lambda r, s: True)
        enabled = [c["argv"][-1] for c in box.called("systemctl") if c["argv"][2] == "enable"]
        self.assertEqual(enabled, ["new.service"])
        cards = [c["argv"] for c in box.called("cc-notify --approval")]
        self.assertEqual(len(cards), 1)                     # the 👍 runs the command the card carries
        self.assertIn("mine.service", cards[0][-1])
        self.assertEqual(cards[0][cards[0].index("--run") + 1], "systemctl --user enable --now mine.service")

    def test_a_bare_daemon_restart_is_proved_by_new_pids(self):
        box = self.fake(**{"cc-units daemons-for": (0, "watcher\tbin/restart-watcher\tbin/daemon\n"),
                           "restart-watcher": (0, "")})
        seen = iter([{11}, {12}])
        D.running = lambda root, rel: next(seen)
        D.request("demo", NEW)
        st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertIn("watcher (pid 12)", st["why"])
        self.assertEqual(len(box.called("restart-watcher")), 1)

    def test_a_daemon_on_its_old_pid_fails(self):
        self.fake(**{"cc-units daemons-for": (0, "watcher\tbin/restart-watcher\tbin/daemon\n"),
                     "restart-watcher": (0, "")})
        D.running = lambda root, rel: {11}
        D.request("demo", NEW)
        self.assertEqual(D.run("demo", green=lambda r, s: True)["targets"]["demo"]["state"], "failed")

    def test_verify_runs_last_and_an_unchecked_ask_is_unverified(self):
        os.makedirs(os.environ["CC_BOARDS"])
        with open(os.path.join(os.environ["CC_BOARDS"], "demo.json"), "w") as f:
            json.dump({"tracks": {"row-a": {"pr": "https://x/pull/7", "status": "review"}}}, f)
        D.record_applied("demo", OLD)
        box = self.fake(**{"cc-scope list": (0, json.dumps([{"id": "s1", "status": "merged"},
                                                          {"id": "s2", "status": "open"}])),
                           "cc-scope deliver": lambda a: (0 if a[-1] == "s1" else 2, "")})
        D.request("demo", NEW)
        st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertEqual(st["state"], "unverified")
        self.assertIn("UNVERIFIED and still open: s2", st["why"])
        keys = [box.key(c["argv"]) for c in box.calls]
        self.assertGreater(keys.index("cc-scope deliver"), keys.index("install.sh"))

    def test_a_member_repo_deploys_nothing(self):
        box = self.fake()
        D.request("h--t", NEW)
        self.assertIsNone(D.run("h--t", green=lambda r, s: True))
        self.assertEqual(box.called("git read-tree"), [])


class Tip(Box):
    def tipbox(self, tip=NEW, commits=()):
        def git(argv):
            sub = argv[1:]
            if sub[:1] == ["rev-parse"] and sub[1:2] == ["refs/remotes/origin/main"]:
                return 0, tip + "\n"
            if sub[:1] == ["ls-remote"]:
                return 0, tip + "\trefs/heads/main\n"
            if sub[:2] == ["rev-list", "--parents"]:
                return 0, f"{sub[-1]} {'0' * 40}\n"
            if sub[:1] == ["rev-list"]:
                return 0, "\n".join(commits) + "\n"
            if sub[:1] == ["merge-tree"]:
                return 0, "e" * 40 + "\n"
            if sub[:1] == ["commit-tree"]:
                return 0, "d" * 40 + "\n"
            if sub[:1] == ["diff"]:
                return 0, nul(argv, "x.py\n")
            if sub[:1] == ["log"]:
                return 0, "the change (#7)\n"
            if sub[:1] == ["rev-parse"] and sub[1:2] == ["HEAD"]:
                return 0, "f" * 40 + "\n"
            if sub[-1:] == ["--git-dir"]:
                return 0, os.path.join(self.root, ".git") + "\n"
            if sub[:1] == ["rev-parse"]:
                return 0, "main\n"
            return 0, ""
        box = self.fake()
        box.answers.update({"git " + k: git for k in ("rev-parse", "rev-list", "diff", "log", "fetch", "merge",
                                                      "merge-tree", "commit-tree", "push", "merge-base", "ls-remote")})
        box.answers["gh pr comment"] = (0, "")
        return box

    def result(self, status):
        return T.Result(check="c", tree="t", status=status)

    def test_the_revert_author_is_not_the_callers(self):
        # XDG_CONFIG_HOME/git/config is read by `git config --global`: a worker's would name the revert's author
        xdg = os.path.join(self.tmp, "xdg")
        os.makedirs(os.path.join(xdg, "git"))
        with open(os.path.join(xdg, "git", "config"), "w") as f:
            f.write("[user]\n\tname = evil\n\temail = evil@example.com\n")
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": xdg, "GIT_CONFIG_GLOBAL": os.path.join(xdg, "git", "config")}):
            self.assertEqual(TP.identity(), ("lander", "lander@localhost"))

    def test_kick_is_idempotent_and_merges_coalesce(self):
        TP.kick("demo")
        first = C.read_json(TP.want_path("demo"))
        TP.kick("demo")
        self.assertEqual(C.read_json(TP.want_path("demo")), first)

    def test_no_kick_no_run(self):
        self.tipbox()
        self.assertEqual(TP.run("demo", plan=None, check=None), "idle")

    def test_green_tip_records_and_deploys(self):
        self.tipbox()
        D.record_applied("demo", OLD)
        TP.kick("demo")
        runs = []
        out = TP.run("demo", plan=lambda r, b, h, f: T.Plan(checks=["unit"]),
                     check=lambda n, s: runs.append((n, s)) or self.result(T.PASSED))
        self.assertEqual(out, "green")
        self.assertEqual(runs, [("unit", NEW)])
        self.assertTrue(TP.green("demo", NEW))
        self.assertEqual(C.read_json(D.req_path("demo"))["targets"]["demo"]["state"], "verified")
        self.assertFalse(os.path.exists(TP.want_path("demo")))

    def test_unrunnable_is_a_retry_not_red(self):
        self.tipbox()
        D.record_applied("demo", OLD)
        TP.kick("demo")
        out = TP.run("demo", plan=lambda *a: T.Plan(checks=["unit"]), check=lambda n, s: self.result(T.UNRUNNABLE))
        self.assertEqual(out, "retry")
        self.assertIsNone(D.held("demo"))
        self.assertTrue(os.path.exists(TP.want_path("demo")))

    def test_red_holds_bisects_the_failing_check_and_reverts_a_proven_breaker(self):
        commits = ["1" * 40, "2" * 40, "3" * 40, NEW]
        box = self.tipbox(commits=commits)
        D.record_applied("demo", OLD)
        TP.kick("demo")
        asked = []

        def check(name, sha):
            asked.append((name, sha))
            if name == "other":
                return self.result(T.PASSED)
            return self.result(T.FAILED if sha in commits[2:] else T.PASSED)
        out = TP.run("demo", plan=lambda *a: T.Plan(checks=["unit", "other"]), check=check)
        self.assertEqual(out, "red")
        self.assertIn("unit failed", D.held("demo")["why"])
        self.assertTrue(all(n == "unit" for n, s in asked[2:]), "only the failing check is bisected")
        self.assertIn(f"--merge-base={'3' * 40}", box.called("git merge-tree")[0]["argv"])
        self.assertEqual(box.called("git push")[0]["argv"][-1], f"{'d' * 40}:refs/heads/main")
        self.assertEqual(box.called("git push")[0]["cwd"], os.path.join(self.tmp, "borrowed.git"))
        self.assertEqual([c for c in box.calls if c["argv"][1:2] in (["worktree"], ["revert"])], [])
        self.assertTrue(os.path.exists(TP.want_path("demo")), "a revert kicks the next tip run")
        self.assertIn("REVERTED", box.called("gh pr comment")[0]["argv"][-1])

    def test_a_flaky_breaker_is_not_reverted(self):
        commits = ["1" * 40, NEW]
        box = self.tipbox(commits=commits)
        D.record_applied("demo", OLD)
        TP.kick("demo")
        seen = []

        def check(name, sha):
            seen.append(sha)
            return self.result(T.FAILED if len(seen) == 1 else T.PASSED)
        self.assertEqual(TP.run("demo", plan=lambda *a: T.Plan(checks=["unit"]), check=check), "red")
        self.assertEqual(box.called("git push"), [])
        self.assertTrue(D.held("demo"))

    def test_catchup_kicks_when_origin_moved_and_not_when_it_is_red_there(self):
        self.tipbox()
        D.record_applied("demo", OLD)
        self.assertTrue(TP.catchup("demo"))
        os.unlink(TP.want_path("demo"))
        C.write_json(TP.red_path("demo"), {"tip": NEW})
        self.assertFalse(TP.catchup("demo"))


    def test_a_finished_request_does_not_stop_catchup_but_a_waiting_one_does(self):
        self.tipbox()
        D.record_applied("demo", OLD)
        for state, kicks in (("verified", True), ("failed", True), ("requested", False), ("held", False)):
            with contextlib.suppress(OSError):
                os.unlink(TP.want_path("demo"))
            C.write_json(D.req_path("demo"), {"repo": "demo", "sha": OLD, "targets": {"demo": {"state": state}}})
            self.assertEqual(TP.catchup("demo"), kicks, state)
            self.assertEqual(os.path.exists(TP.want_path("demo")), kicks, state)


class TestCards(Box):
    def job(self, **extra):
        return T.Job(repo="demo", pr=7, extra={"queued_at": "2026-09-27T00:00:00Z", **extra})

    def test_route_precedence(self):
        self.fake()
        self.assertEqual(C.where(self.job(chat="C1", ts="1.2"), False), ["-c", "C1", "--thread", "1.2"])
        os.makedirs(os.environ["CC_SLACK_DIR"])
        with open(os.path.join(os.environ["CC_SLACK_DIR"], "track-threads.json"), "w") as f:
            json.dump({"demo/row-a": {"chat": "C2", "ts": "3.4"}}, f)
        self.assertEqual(C.where(self.job(track="row-a"), False), ["--route", "demo/row-a stopped"])
        # a landing is not said in the track's thread (it sits in the -updates lane now) but once on #<repo>
        self.assertEqual(C.where(self.job(track="row-a"), True), ["--route", "[demo] PR #7 landed", "--major"])
        m = T.Job(repo="h--t", pr=7, member="h")
        self.assertEqual(C.where(m, True), ["-c", "#h-updates"])
        self.assertEqual(C.where(m, False), ["-c", "#h"])
        self.assertIsNone(C.where(self.job(), True))     # a PR no row owns: the card alone, its seat tells him
        self.assertEqual(C.where(self.job(), False), ["--route", "[demo] PR #7 stopped"])

    def test_a_card_goes_once_by_producer_id(self):
        box = self.fake()
        C.stopped(self.job(), "a check is red", "seat")
        C.stopped(self.job(), "a check is red", "seat")
        self.assertEqual(len(box.called("cc-slack post")), 1)
        self.assertEqual(len(box.called("cc-slack inject")), 1)
        self.assertIn("land:demo:7:stopped@2026-09-27T00:00:00Z", box.called("cc-slack post")[0]["argv"])

    def test_a_refused_card_is_retried_up_to_say_tries(self):
        box = self.fake(**{"cc-slack post": (1, "slack down")})
        C.stopped(self.job(), "red", "query")
        self.assertEqual(len(box.called("cc-notify --ask")), 1)
        for _ in range(C.SAY_TRIES + 2):
            C.retry()
        self.assertEqual(len(box.called("cc-slack post")), C.SAY_TRIES)
        self.assertEqual(C.read_json(C.state("cards", "pending.json")), {})

    def test_landed_turns_the_approval_card_and_names_owner_restarts(self):
        box = self.fake(**{"cc-slack post-approval": (0, "")})
        C.landed(self.job())
        self.assertEqual(box.called("cc-slack post"), [])         # no row: the card alone
        C.landed(self.job(track="row-a"))
        C.landed(self.job(track="row-a"))
        self.assertEqual(len(box.called("cc-slack post-approval")), 3)
        self.assertEqual(len(box.called("cc-slack post")), 1)          # the landed line once, on the main lane
        self.assertIn("--major", box.called("cc-slack post")[0]["argv"])
        self.assertNotIn("--mention", box.called("cc-slack post")[0]["argv"])
        C.landed(self.job(owner_asks=["x.service (`systemctl --user restart x.service`)"], queued_at="2"))
        self.assertIn("--mention", box.called("cc-slack post")[1]["argv"])

    def test_test_state_never_reaches_the_owner(self):
        box = self.fake()
        self.assertFalse(C.owner_card("id", "[_selfcheck-repo] x.service"))
        self.assertEqual(box.called("cc-slack post"), [])


class TestBoard(Box):
    def board(self, tracks):
        os.makedirs(os.environ["CC_BOARDS"], exist_ok=True)
        with open(os.path.join(os.environ["CC_BOARDS"], "demo.json"), "w") as f:
            json.dump({"tracks": tracks}, f)

    def test_track_of_by_pr_then_branch(self):
        self.board({"a": {"pr": "https://g/pull/7"}, "b": {"branch": "feat/b"}, "c": {}})
        self.assertEqual(B.track_of("demo", 7), "a")
        self.assertEqual(B.track_of("demo", 8, "feat/b"), "b")
        self.assertEqual(B.track_of("demo", 9, "track/c"), "c")
        self.assertEqual(B.track_of("demo", 9, "track/zz"), "")

    def test_close_marks_merged_and_closes_only_free_rows(self):
        self.board({"own": {"pr": "7"}, "free": {"status": "queued", "agent": "x"}, "live": {"status": "running"},
                    "gone": {"status": "done"}})
        box = self.fake(**{"cc-board status": (0, ""), "cc-board note": (0, ""), "cc-board set": (0, "")})
        job = T.Job(repo="demo", pr=7, extra={"body": "Closes free, live, gone and no-such-row. Closes the gap"})
        line = B.close(job)
        st = [c["argv"][3:] for c in box.called("cc-board status")]
        self.assertEqual(st, [["own", "merged"], ["free", "done"]])
        self.assertEqual(box.called("cc-board set")[0]["argv"][3:], ["free", "agent", ""])
        self.assertIn("left open: live", line)
        self.assertIn("no row on the board: no-such-row", line)

    def test_an_orch_held_row_gets_a_note_only(self):
        self.board({"own": {"pr": "7", "agent": "@5:123"}})
        box = self.fake(tmux=(0, "@5\tdemo@lander\n"), **{"cc-board note": (0, "")})
        B.close(T.Job(repo="demo", pr=7))
        self.assertEqual(box.called("cc-board status"), [])
        self.assertIn("demo@lander holds this row", box.called("cc-board note")[0]["argv"][-1])

    def test_followup_row_once_for_advice_only(self):
        # recurring-defect-ok: pause-hold-missing — a fake board; the pause hold is the lane's (U1)
        box = self.fake(**{"cc-board add": (0, "")})
        job = T.Job(repo="demo", pr=7)
        self.assertEqual(B.followup(job, T.Verdict(verdict=T.LAND, digest="d")), "")
        B.followup(job, T.Verdict(verdict=T.LAND, digest="d", advisory=["name it"]))
        self.assertEqual(box.called("cc-board add")[0]["argv"][3], "review-followup-pr7")
        box.answers["cc-board get"] = (0, "queued\n")
        B.followup(job, T.Verdict(verdict=T.LAND, digest="d", advisory=["name it"]))
        self.assertEqual(len(box.called("cc-board add")), 1)


class TestScope(Box):
    def test_merged_marks_every_ask_on_the_track(self):
        box = self.fake(**{"cc-scope list": (0, json.dumps([{"id": "s1"}, {"id": "s2"}])), "cc-scope merged": (0, "")})
        self.assertIn("2 ask(s)", S.merged("demo", "row-a", "PR #7"))
        self.assertEqual(S.merged("demo", "", "PR #7"), "")
        self.assertEqual(len(box.called("cc-scope merged")), 2)

    def test_owner_ask_is_filed_once_and_not_for_a_stopped_unit(self):
        rows = []
        box = self.fake(**{"cc-scope list": lambda a: (0, json.dumps(rows)),
                           "cc-scope add": lambda a: rows.append({"id": "s9", "text": a[3]}) or (0, "")})
        self.assertTrue(S.owner_ask("demo", "x.service", "PR #7")[0])
        self.assertFalse(S.owner_ask("demo", "x.service", "PR #8")[0])
        self.assertEqual(len(box.called("cc-scope add")), 1)
        box.answers["systemctl"] = (3, "inactive\n")
        self.assertFalse(S.owner_ask("demo", "y.service", "PR #7")[0])

    def test_deliver_reads_each_exit_code(self):
        self.fake(**{"cc-scope list": (0, json.dumps([{"id": i, "status": "open"} for i in ("g", "r", "b", "s")])),
                     "cc-scope deliver": lambda a: ({"g": 0, "r": 1, "b": 2, "s": 3}[a[-1]], "")})
        ok, line, bad = S.deliver("demo", "demo", "row-a")
        self.assertFalse(ok)
        self.assertEqual(sorted(bad), ["b", "r", "s"])
        self.assertIn("COULD NOT RUN, never measured (not a red check): s", line)


if __name__ == "__main__":
    unittest.main()
