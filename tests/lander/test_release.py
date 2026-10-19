"""lander release: each refusal perms set (perms-66) stops it and names its rule; the command only files a request,
and the lane applies it under its own lock, where a job the lane picked up first, or a PR that moved, is kept. The
PR's facts (gh, the base policy, cc-config) and the lane's head read are fakes; the job files, the inbox, the lane
lock and queue.log are real files under a temp dir. Run:
python3 -m unittest discover -s core/tests/lander -t core/tests/lander -p 'test_release.py'
"""
import fcntl
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from lander import jobs as J  # noqa: E402
from lander import release as RL  # noqa: E402
from lander import review as R  # noqa: E402
from lander import types as T  # noqa: E402

HEAD = "a" * 40
OLD = "b" * 40
REAL_FACTS = RL.facts   # setUp swaps RL.facts for a fake; one case reads the real one against stubbed gh and git


def mark(verdict, by, head=HEAD, own=True):
    v = T.Verdict(verdict=verdict, digest="c0ffee", blocking=["x"] if verdict != T.LAND else [])
    return {"body": R.marker(v, "d" * 40, head, by), "viewerDidAuthor": own}


class StandingHandback(unittest.TestCase):
    def test_only_perms_security_reader_stands_at_an_old_head(self):
        """Perms, 10-13: a reader whose name only says `security` is anyone's to write, so it is not perms'."""
        self.assertEqual(RL.standing_handback([mark(T.HANDBACK_VERDICT, "perms-security-read", head=OLD)], HEAD),
                         ("perms-security-read", OLD[:12]))
        for by in ("x-security", "perms-security-read-2", "security"):
            self.assertIsNone(RL.standing_handback([mark(T.HANDBACK_VERDICT, by, head=OLD)], HEAD), by)
            self.assertEqual(RL.standing_handback([mark(T.HANDBACK_VERDICT, by)], HEAD), (by, HEAD[:12]), by)


class Release(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lander-release.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.land = os.path.join(self.tmp, "land")
        p = mock.patch.dict(os.environ, {"CC_LAND_STATE": self.land, "CC_LANDER_STATE": self.land,
                                         "HOME": self.tmp, "CC_DEV": os.path.join(self.tmp, "dev")})
        p.start()
        self.addCleanup(p.stop)
        self.facts = {"head": HEAD, "comments": [], "files": ["docs/a.md"],
                      "lander": ["core/lander/**", "tests/LANDING-policy.toml"], "protected": []}

        def facts(repo, pr):
            if isinstance(self.facts, Exception):
                raise self.facts
            return self.facts
        p = mock.patch.object(RL, "facts", facts)
        p.start()
        self.addCleanup(p.stop)

    def queued(self, repo="demo", pr=5, **kw):
        job = T.Job(repo=repo, pr=pr, **kw)
        job.history.append({"at": "2026-10-12T00:00:00Z", "state": T.QUEUED})
        job.extra.update(queued_at="2026-10-12T00:00:00Z")
        J.save(job)
        return job

    def log(self):
        try:
            with open(os.path.join(self.land, "queue.log")) as f:
                return f.read()
        except OSError:
            return ""

    def refused(self, rule, repo="demo", pr=5):
        rc, line, _ = RL.release(repo, pr, "lean")
        self.assertEqual(rc, 1, line)
        self.assertIn(f"refused {repo}#{pr} {rule}:", line)
        self.assertFalse([r for _, r in J.requests(repo) if r.get("release")])   # no request filed
        self.assertNotIn("released", self.log())
        return line

    def lane(self, repo="demo"):
        """What the lane does at its next pick: drain the inbox under its lock."""
        with J.lane_lock(repo) as got:
            self.assertTrue(got)
            return J.drain(repo)

    def forge(self, pr=5, repo="demo", **over):
        """A hand-written request: whole, and made for the job as it is now, unless `over` says otherwise."""
        job = J.load(repo, pr)
        stamp = "2026-10-12T00:00:00Z"
        req = dict(release="lean", head=HEAD, rid="feed00",
                   **(RL.mark_of(job) if job else {"seen": 1, "queued_at": stamp, "last": stamp}))
        req.update(over)
        J.submit(repo, pr, **{k: v for k, v in req.items() if v is not None})

    def requested(self, repo="demo", pr=5):
        rc, line, rid = RL.release(repo, pr, "lean")
        self.assertEqual(rc, 0, line)
        self.assertEqual(line, f"lander release: {repo}#{pr} requested by lean rid={rid}")
        return rid

    def test_a_queued_job_is_released_by_the_lane_and_logged(self):
        self.queued()
        J.submit("demo", 5, who="x")
        J.submit("demo", 6, who="y")
        rid = self.requested()
        self.assertEqual(J.load("demo", 5).state, T.QUEUED)   # the command wrote only the request
        self.assertNotIn("released", self.log())
        self.assertIn("demo#5 released by lean", self.lane())
        self.assertIsNone(J.load("demo", 5))
        self.assertEqual(J.load("demo", 6).state, T.QUEUED)   # another PR's request is drained as usual
        self.assertEqual(J.requests("demo"), [])
        self.assertIn(f"released demo#5 rid={rid} by=lean head={HEAD}", self.log())
        self.assertNotIn("demo#5 again", self.log())   # its own waiting request went with it

    def test_member_lane_is_refused(self):
        self.queued(repo="ih--proj")
        self.refused("member", repo="ih--proj")
        self.assertIsNotNone(J.load("ih--proj", 5))
        self.queued(repo="other", member="ih")   # the job naming a member is the same rule
        self.refused("member", repo="other")

    def test_open_query_is_refused(self):
        job = self.queued()
        J.move(job, T.QUERY, "the owner's door")
        self.refused("query")
        self.assertEqual(J.load("demo", 5).state, T.QUERY)

    def test_only_a_queued_stage_is_released(self):
        self.refused("stage")   # no job at all
        job = self.queued()
        J.move(job, T.PLANNED)
        self.refused("stage")
        self.assertEqual(J.load("demo", 5).state, T.PLANNED)

    def test_owner_approval_is_refused(self):
        self.queued()
        J.approve("demo", 5, "U-OWNER", HEAD)
        self.refused("approval")
        self.assertIsNotNone(J.load("demo", 5))

    def test_protected_path_is_refused(self):
        self.queued()
        self.facts.update(files=["config/secrets.env"], protected=["config/"])
        self.refused("protected")
        self.facts.update(files=["docs/a.md"])   # the same rules, a PR that keeps off them: requested
        self.requested()

    def test_lander_class_is_refused(self):
        self.queued()
        self.facts.update(files=["docs/a.md", "core/lander/lane.py"])
        self.assertIn("core/lander/lane.py is on the lander list", self.refused("lander"))
        self.facts.update(files=["tests/LANDING-policy.toml"])
        self.refused("lander")

    def test_a_job_once_a_lander_self_query_is_refused(self):
        self.queued(history=[{"at": "2026-10-11T00:00:00Z", "state": T.QUERY,
                              "why": "it changes the lander itself — lander-self lands it"}])
        self.refused("lander")

    def test_box_handback_at_head_is_refused(self):
        self.queued()
        self.facts["comments"] = [mark(T.HANDBACK_VERDICT, "opus-5.5")]
        self.refused("handback")

    def test_security_handback_stands_at_any_head(self):
        self.queued()
        self.facts["comments"] = [mark(T.HANDBACK_VERDICT, R.PERMS_SECURITY_READER, head=OLD)]
        self.refused("handback")

    def test_handbacks_that_do_not_stand_are_released(self):
        self.queued()
        self.facts["comments"] = [
            mark(T.HANDBACK_VERDICT, "opus-5.5", head=OLD),                 # another reader's, at an older head
            mark(T.HANDBACK_VERDICT, "security-reviewer", own=False),       # typed in by someone else
            mark(T.HANDBACK_VERDICT, "codex"), mark(T.LAND, "codex"),       # its reader's newer LAND replaced it
        ]
        self.requested()

    def test_a_security_path_needs_perms_record_of_the_change(self):
        p = mock.patch.object(R, "PERMS_STATE", os.path.join(self.tmp, "perms-state"))
        p.start()
        self.addCleanup(p.stop)
        path = R.perms_reads_path("demo")
        os.makedirs(os.path.dirname(path))

        def record(**kw):
            with open(path, "w") as f:
                json.dump([dict({"repo": "demo", "pr": 5, "head": HEAD, "change": "c0ffee"}, **kw)], f)
            os.chmod(path, 0o600)
        self.queued()
        self.facts.update(files=["config/systemd-user/x.service"], security=["config/systemd-user/x.service"],
                          digests=["c0ffee"])
        land = {"body": R.marker(T.Verdict(verdict=T.LAND, digest="c0ffee"), "d" * 40, HEAD, "perms-security-read"),
                "viewerDidAuthor": True}
        self.facts["comments"] = [land]   # a marker alone, even signed perms-security-read, is no record
        self.assertIn("perms has recorded no security read", self.refused("security"))
        for kw in ({"head": OLD}, {"change": "0dd"}, {"pr": 6}):
            record(**kw)
            self.refused("security")
        record()
        self.requested()

    def test_no_security_path_needs_no_perms_land(self):
        self.queued()
        self.facts.update(security=[], digests=[], comments=[mark(T.LAND, "opus-5.5")])
        self.requested()

    def test_an_unread_fact_fails_closed(self):
        self.queued()
        self.facts = RL.Unread("gh would not read the PR: boom")
        self.assertIn("boom", self.refused("unread"))
        self.assertIsNotNone(J.load("demo", 5))

    def test_a_busy_lane_does_not_stop_the_request(self):
        self.queued()
        os.makedirs(J.lanes_dir(), exist_ok=True)
        fd = os.open(J.lane_file("demo", "lock"), os.O_RDWR | os.O_CREAT, 0o644)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)   # the lane's, held job to job: the command never waits on it
        self.requested()
        self.assertEqual(J.load("demo", 5).state, T.QUEUED)
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.lane()
        self.assertIsNone(J.load("demo", 5))

    def test_a_job_the_lane_picks_up_first_is_kept(self):
        self.queued()
        rid = self.requested()
        J.move(J.load("demo", 5), T.PLANNED)   # the lane took it up before it drained the request
        self.assertIn("demo#5 release refused (raced)", self.lane())
        self.assertEqual(J.load("demo", 5).state, T.PLANNED)
        self.assertIn(f"release-refused demo#5 rid={rid} by=lean head={HEAD} raced: the job is not the one the "
                      "release read", self.log())
        self.assertNotIn("\treleased", self.log())

    def test_a_job_moved_and_back_to_queued_is_kept(self):
        self.queued()
        self.requested()
        job = J.load("demo", 5)
        J.move(job, T.PLANNED)
        J.move(job, T.QUEUED, why="requeued")   # queued again, but not the job the release read
        self.lane()
        self.assertEqual(J.load("demo", 5).state, T.QUEUED)
        self.assertIn("raced", self.log())

    def test_the_lane_checks_the_job_rules_again(self):
        self.queued()
        self.requested()
        J.approve("demo", 5, "U-OWNER", HEAD)   # the owner approved it after the command read
        self.lane()
        self.assertEqual(J.load("demo", 5).state, T.QUEUED)
        self.assertIn("release-refused demo#5", self.log())
        self.assertIn("approval:", self.log())

    def test_a_release_request_never_makes_a_job(self):
        self.forge(7, rid="f00f00")   # forged, or for a job already gone
        self.lane()
        self.assertIsNone(J.load("demo", 7))
        self.assertIn("release-refused demo#7 rid=f00f00 by=lean head=", self.log())
        self.assertIn(" stage: ", self.log())

    def test_a_push_after_the_read_keeps_the_job(self):
        self.queued()
        rid = self.requested()
        self.facts["head"] = OLD   # head B (it may touch core/lander/ or a protected path) came after the read of A
        self.assertIn("demo#5 release refused (stale-head)", self.lane())
        self.assertEqual(J.load("demo", 5).state, T.QUEUED)
        self.assertIn(f"release-refused demo#5 rid={rid} by=lean head={HEAD} stale-head:", self.log())
        self.assertNotIn("\treleased", self.log())

    def test_the_head_that_will_not_read_keeps_the_job(self):
        self.queued()
        self.requested()

        self.facts = RL.Unread("gh would not read the PR: boom")   # the lane reads it again, failing closed
        self.lane()
        self.assertEqual(J.load("demo", 5).state, T.QUEUED)
        self.assertIn("unread: gh would not read the PR: boom", self.log())

    def test_a_request_with_no_whole_seen_keeps_a_live_job(self):
        self.queued()
        for seen in ("1", None, True, 1.0):   # True is an int to isinstance; not to this
            self.forge(seen=seen)
            self.assertIn("demo#5 release refused (request)", self.lane())
            self.assertEqual(J.load("demo", 5).state, T.QUEUED)
        self.forge(queued_at=None)   # no queued_at stamp
        self.assertIn("demo#5 release refused (request)", self.lane())
        self.forge(rid="not-hex")   # nor a rid that is not hex
        self.lane()
        self.assertEqual(J.load("demo", 5).state, T.QUEUED)
        self.assertNotIn("rid=not-hex", self.log())

    def test_a_forged_request_on_a_live_queued_job_reads_every_rule_again(self):
        self.queued()
        self.facts.update(files=["core/lander/lane.py"])   # lander-class: the command would refuse it, so forge one
        self.forge()   # whole, and made for the job as it is (seen, queued_at, last all right)
        self.assertIn("demo#5 release refused (lander)", self.lane())
        self.assertEqual(J.load("demo", 5).state, T.QUEUED)
        self.facts.update(files=["config/secrets.env"], protected=["config/"])
        self.forge()
        self.assertIn("demo#5 release refused (protected)", self.lane())
        self.facts.update(files=["docs/a.md"], protected=[], comments=[mark(T.HANDBACK_VERDICT, "opus-5.5")])
        self.forge()
        self.assertIn("demo#5 release refused (handback)", self.lane())
        self.assertEqual(J.load("demo", 5).state, T.QUEUED)
        self.assertNotIn("\treleased", self.log())

    def test_a_member_lane_is_refused_at_the_lane(self):
        self.queued(repo="ih--proj")
        self.forge(repo="ih--proj")
        self.assertIn("ih--proj#5 release refused (member)", self.lane("ih--proj"))
        self.assertIsNotNone(J.load("ih--proj", 5))
        self.queued(repo="other", member="ih")
        self.forge(repo="other")
        self.assertIn("other#5 release refused (member)", self.lane("other"))
        self.assertIsNotNone(J.load("other", 5))

    def test_a_replayed_request_does_not_drop_a_requeued_job(self):
        job = self.queued()
        saved = RL.mark_of(job)
        job.extra["queued_at"] = "2026-10-12T09:00:00Z"   # queued again since: a fresh start writes a new queued_at
        J.save(job)
        self.forge(**saved)
        self.assertIn("demo#5 release refused (raced)", self.lane())
        self.assertEqual(J.load("demo", 5).state, T.QUEUED)
        job = J.load("demo", 5)
        saved = RL.mark_of(job)
        job.history[-1]["at"] = "2026-10-12T09:30:00Z"   # the same length, a different newest entry
        J.save(job)
        self.forge(**saved)
        self.assertIn("demo#5 release refused (raced)", self.lane())

    def test_a_request_filed_after_the_release_is_not_swallowed(self):
        self.queued()
        rid = self.requested()
        path = J.submit("demo", 5, who="owner")   # the owner queued it again after the release was filed
        t = os.path.getmtime(path) + 5
        os.utime(path, (t, t))
        lines = self.lane()
        self.assertIn("demo#5 release refused (newer)", lines)
        self.assertIn("demo#5 again", lines)   # the owner's request was drained, not dropped
        self.assertEqual(J.load("demo", 5).state, T.QUEUED)
        self.assertEqual(RL.wait("demo", 5, rid, 0)[0], 1)

    def test_an_approval_record_that_will_not_read_refuses(self):
        self.queued()
        os.makedirs(J.approvals_dir(), exist_ok=True)
        with open(J.approval_path("demo", 5), "w") as f:
            f.write("{not json")
        self.assertIn("will not read", self.refused("approval"))

    def test_a_who_with_a_space_cannot_answer_another_wait(self):
        self.queued()
        rid = self.requested()
        self.forge(release=f"x rid={rid}\x1b[2J", seen="no")   # refused, its line written
        self.lane()
        self.assertIn("by=x-rid-", self.log())
        self.assertNotIn("\x1b", self.log())   # its escape never reaches queue.log
        rc, line = RL.wait("demo", 5, rid, 0)
        self.assertEqual(rc, 0, line)   # the real request's own `released` line, not the forged refusal
        self.assertIn(f"released demo#5 rid={rid} by=lean", line)
        self.assertEqual(RL.clean_by("a b\tc=d"), "a-bc-d")   # a tab is a control byte: taken out

    def test_a_second_request_for_the_pr_gets_its_own_line(self):
        self.queued()
        one, two = self.requested(), self.requested()
        lines = self.lane()
        self.assertIn("demo#5 released by lean", lines)
        self.assertIn("demo#5 release refused (duplicate)", lines)
        self.assertEqual(RL.wait("demo", 5, one, 0)[0], 0)
        rc, line = RL.wait("demo", 5, two, 0)
        self.assertEqual(rc, 1)
        self.assertIn(f"duplicate: released already by rid={one}", line)

    def test_a_request_that_breaks_apply_is_set_aside(self):
        self.queued()
        rid = self.requested()
        with mock.patch.object(RL, "apply", mock.Mock(side_effect=KeyError("boom"))):
            self.assertIn("demo#5 release refused (error)", self.lane())
        self.assertEqual(J.requests("demo"), [])   # not retried at the next drain
        self.assertEqual(glob.glob(os.path.join(J.inbox_dir(), "demo-5.*")), [])   # (4) owns nothing: no inbox name
        failed = os.listdir(os.path.join(J.inbox_dir(), "failed"))
        self.assertEqual(len([n for n in failed if n.endswith(".failed")]), 1)
        self.assertIn(f"release-refused demo#5 rid={rid} by=lean head={HEAD} error: KeyError", self.log())
        self.assertEqual(J.load("demo", 5).state, T.QUEUED)
        self.assertEqual(self.lane(), [])

    def test_wait_reports_what_the_lane_did(self):
        self.queued()
        rid = self.requested()
        self.assertEqual(RL.wait("demo", 5, rid, 0)[0], 3)   # nothing yet: still waits
        self.lane()
        rc, line = RL.wait("demo", 5, rid, 0)
        self.assertEqual(rc, 0)
        self.assertTrue(line.startswith("released demo#5 rid="), line)
        self.queued(pr=8)
        rid8 = self.requested(pr=8)
        J.move(J.load("demo", 8), T.PLANNED)
        self.lane()
        self.assertEqual(RL.wait("demo", 8, rid8, 0)[0], 1)
        self.assertEqual(RL.wait("demo", 8, "nope", 0)[0], 3)   # another rid's line does not answer this one

    def test_facts_reads_the_pr_the_base_policy_and_the_protected_paths(self):
        import contextlib
        from lander import gh as GH, git as G, lane as L, manifest as MF
        pol = T.Policy(lander=["core/lander/**"])
        gh = {"headRefOid": HEAD, "baseRefName": "main", "comments": [mark(T.LAND, "opus")],
              "files": [{"path": "docs/a.md"}]}
        with mock.patch.object(GH, "pr_facts", lambda root, pr, fields: (gh, "")), \
                mock.patch.object(G, "git_lock", lambda root: contextlib.nullcontext()), \
                mock.patch.object(G, "fetch", lambda root, b: {b: OLD}), \
                mock.patch.object(G, "fetch_ids", lambda root, *revs: None), \
                mock.patch.object(G, "pr_changed", lambda root, base, head: ["docs/a.md"]), \
                mock.patch.object(MF, "load", lambda root, rev, fallback="": mock.Mock(policy=pol)), \
                mock.patch.object(L, "protected_rules", lambda repo: ["config/"]):
            f = REAL_FACTS("demo", 5)
            self.assertEqual((f["head"], f["files"], f["protected"]), (HEAD, ["docs/a.md"], ["config/"]))
            self.assertIn("core/lander/**", f["lander"])
            self.assertIn("core/tests/LANDING-policy.toml", f["lander"])
            with mock.patch.object(L, "protected_rules", lambda repo: None):   # cc-config silent: fails closed
                self.assertRaises(RL.Unread, REAL_FACTS, "demo", 5)
        with mock.patch.object(GH, "pr_facts", lambda root, pr, fields: (None, "boom")):
            self.assertRaises(RL.Unread, REAL_FACTS, "demo", 5)

    def test_a_rename_gh_names_by_its_new_path_is_read_from_git(self):
        """perms' HANDBACK on #1207 (1): gh lists only a rename's new path, so a git mv of the policy file slipped past
        the lander rule. facts() lists the files with git at the head gh named, old and new paths both."""
        import subprocess
        from lander import gh as GH, git as G, lane as L, manifest as MF
        repo = os.path.join(self.tmp, "r")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")

        def git(*a):
            return subprocess.run(["git", "-C", repo, *a], env=env, check=True, capture_output=True,
                                  text=True).stdout.strip()
        os.makedirs(os.path.join(repo, "tests"))
        git("init", "-q", "-b", "main")
        boards = os.path.join(self.tmp, "boards")   # a checkout the host made (a board names it), else taken() refuses
        os.makedirs(boards)
        with open(os.path.join(boards, "demo.json"), "w") as fh:
            json.dump({"path": repo}, fh)
        p = mock.patch.dict(os.environ, {"CC_BOARDS": boards})
        p.start()
        self.addCleanup(p.stop)
        with open(os.path.join(repo, "tests", "LANDING-policy.toml"), "w") as fh:
            fh.write("lander = []\n" * 20)
        git("add", "-A")
        git("commit", "-qm", "base")
        base = git("rev-parse", "HEAD")
        git("mv", "tests/LANDING-policy.toml", "tests/policy-old.toml")
        git("commit", "-qm", "move")
        head = git("rev-parse", "HEAD")
        self.assertEqual(G.pr_changed(repo, base, head), ["tests/LANDING-policy.toml", "tests/policy-old.toml"])
        gh = {"headRefOid": head, "baseRefName": "main", "comments": [],
              "files": [{"path": "tests/policy-old.toml"}]}   # what gh says of the move: the new path only
        seen = []
        with mock.patch.object(GH, "pr_facts", lambda root, pr, fields: (gh, "")), \
                mock.patch.object(J, "repo_root", lambda r: repo), \
                mock.patch.object(G, "fetch", lambda root, b: {b: base}), \
                mock.patch.object(G, "fetch_ids", lambda root, *revs: seen.extend(revs)), \
                mock.patch.object(MF, "load", lambda root, rev, fallback="": mock.Mock(policy=T.Policy(lander=[]))), \
                mock.patch.object(L, "protected_rules", lambda repo: []), \
                mock.patch.object(RL, "facts", REAL_FACTS):
            f = RL.facts("demo", 5)
            self.assertEqual(f["files"], ["tests/LANDING-policy.toml", "tests/policy-old.toml"])
            self.assertEqual(seen, ["refs/pull/5/head"])
            self.queued()
            line = self.refused("lander")
            self.assertIn("tests/LANDING-policy.toml is on the lander list", line)
            with mock.patch.object(G, "pr_changed", mock.Mock(side_effect=G.GitError("no such commit"))):
                self.refused("unread")   # git will not list them at gh's head: fails closed, gh's list is not enough

    def test_apply_never_holds_rest_lock_while_it_reads_the_pr(self):
        """perms' HANDBACK on #1207 (2): a tick holds rest_lock and then takes git_lock (tip.kick), so the release,
        which reads gh and fetches under git_lock, must not hold rest_lock: the lane applies it before taking it."""
        self.queued()
        self.requested()
        J.submit("demo", 6, who="y")
        free, order = [], []
        real = J.rest_lock

        def facts(repo, pr):
            order.append("facts")
            with real(repo) as got:   # non-blocking, on a fd of its own: False if anyone holds it
                free.append(got)
            return self.facts

        def spy(repo, wait=False):
            order.append("rest_lock")
            return real(repo, wait)
        with mock.patch.object(RL, "facts", facts), mock.patch.object(J, "rest_lock", spy):
            lines = self.lane()
        self.assertIn("demo#5 released by lean", lines)
        self.assertIn("demo#6 queued", lines)   # the rest of the inbox is still drained, under rest_lock
        self.assertEqual((free, order), ([True], ["facts", "rest_lock"]))

    def test_a_path_in_a_refusal_is_shown_clean(self):
        """perms' HANDBACK on #1207 (3): a path is the branch's to name; a refusal shows it through J.path_names."""
        self.queued()
        self.facts.update(files=["config/x\x1b[31m\nfake line"], protected=["config/"])
        line = self.refused("protected")
        self.assertNotRegex(line, r"[\x00-\x1f\x7f]")
        self.assertIn("config/x[31mfake line", line)
        self.facts.update(files=["core/lander/\x1bq.py"], protected=[])
        line = self.refused("lander")
        self.assertNotRegex(line, r"[\x00-\x1f\x7f]")
        self.assertIn("core/lander/q.py is on the lander list", line)

    def test_release_is_a_command(self):
        from lander import cli
        cmds, faults = cli.collect(["release"])
        self.assertEqual((cmds["release"][0], faults), (RL.cmd_release, []))

    def test_usage(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(RL.cmd_release(["demo"]), 2)
            self.assertEqual(RL.cmd_release(["demo", "x"]), 2)
            self.assertEqual(RL.cmd_release(["demo", "5", "--by"]), 2)
            self.assertEqual(RL.cmd_release(["demo", "5", "--wait", "soon"]), 2)
            self.assertEqual(RL.cmd_release(["demo", "5", "--wait", "-1"]), 2)
        self.queued()
        with mock.patch("sys.stdout"):
            self.assertEqual(RL.cmd_release(["demo", "5", "--by", "lean", "--wait", "0"]), 3)


class GhViewer(unittest.TestCase):
    """Opus FIX at 1d882403: with no viewer every comment read as someone else's, so a standing HANDBACK went
    unseen and release carried on; the read now fails closed, as the GraphQL one did."""

    def setUp(self):
        from lander import gh as GH
        self.GH, self.calls, self.user = GH, [], (0, "box-bot\n", "")
        for p in (mock.patch.dict(GH._VIEWER, clear=True), mock.patch.object(GH, "slug", lambda root: "o/r"),
                  mock.patch.object(GH, "gh", self.gh)):
            p.start()
            self.addCleanup(p.stop)

    def gh(self, argv, root, token=None, timeout=120, note=True, stdin=None):
        self.calls.append((argv, stdin))
        if argv[:2] == ["api", "user"]:
            return self.user
        if argv[:1] == ["pr"]:
            return 0, "", ""
        if argv[-2:] == ["--input", "-"]:
            return 0, '{"id": 1}', ""
        body = R.marker(T.Verdict(verdict=T.HANDBACK_VERDICT, digest="c0ffee", blocking=["x"]), "d" * 40, HEAD,
                        "opus-5.5")
        return 0, json.dumps({"body": body, "login": "box-bot", "createdAt": "t"}) + "\n", ""

    def test_no_viewer_fails_the_comment_read(self):
        got, _ = self.GH.comments("/r", 5)
        self.assertEqual(RL.standing_handback(got, HEAD), ("opus-5.5", HEAD[:12]))   # the box's own HANDBACK stands
        self.GH._VIEWER.clear()
        for fail in ((1, "", "HTTP 502"), (124, "", "gh timed out"), (0, "", "")):
            self.user = fail
            self.assertEqual(self.GH.comments("/r", 5), (None, "GitHub would not say which login gh runs as"))

    def test_a_callable_token_is_never_cached(self):
        def tok():
            return "t"
        self.assertEqual(self.GH.viewer("/r", tok), "box-bot")
        self.assertEqual(self.GH._VIEWER, {})   # it would share the box login's "" key
        self.user = (0, "other\n", "")
        self.assertEqual(self.GH.viewer("/r", tok), "other")
        self.assertEqual(self.GH.viewer("/r"), "other")
        self.user = (0, "box-bot\n", "")
        self.assertEqual(self.GH.viewer("/r"), "other")   # the box login's own answer is cached

    def test_the_comment_body_goes_on_stdin(self):
        big = "x" * 300000
        self.assertTrue(self.GH.comment("/r", 5, big))
        with mock.patch.object(self.GH, "slug", lambda root: ""):
            self.assertTrue(self.GH.comment("/r", 5, big))
        for argv, stdin in self.calls:
            self.assertNotIn(big, argv)
        self.assertEqual(self.calls[-1], (["pr", "comment", "5", "--body-file", "-"], big))


if __name__ == "__main__":
    unittest.main()
