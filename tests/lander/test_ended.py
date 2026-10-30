"""lander tick's `ended` step and `lander settle-merged`: a query or held job whose PR was merged around the lane
(lander-self, a hand merge) moves to merged with the lane's own merged line, then done; a closed one ends done.

gh is answered by a fake; the job files, rest/, queue.log and the stamps are real files under a temp dir. Run:
python3 -m unittest discover -s core/tests/lander -t core/tests/lander -p 'test_ended.py'
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

import calm_host  # noqa: E402,F401  (pins load and pressure; before any lander import)
from lander import events as E  # noqa: E402
from lander import gh as GH  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import tick as TK  # noqa: E402
from lander import types as T  # noqa: E402

MERGED_AT = "2026-10-12T17:48:59Z"


class Ended(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lander-ended.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        land = os.path.join(self.tmp, "land")
        p = mock.patch.dict(os.environ, {"CC_LAND_STATE": land, "CC_LANDER_STATE": land, "HOME": self.tmp,
                                         "CC_DEV": os.path.join(self.tmp, "dev"),
                                         "CC_BOARDS": os.path.join(self.tmp, "boards"),
                                         "LANDER_ENDED_SECS": "900"})
        p.start()
        self.addCleanup(p.stop)
        os.makedirs(os.path.join(self.tmp, "dev", "demo", ".git"))
        self.gh = {}      # pr -> what gh pr view answers (None: gh failed)
        self.asked = []

        def pr_facts(root, pr, fields, token=None, timeout=120):
            self.asked.append(int(pr))
            got = self.gh.get(int(pr))
            return (None, "boom") if got is None else (dict(got), "")
        p = mock.patch.object(GH, "pr_facts", pr_facts)
        p.start()
        self.addCleanup(p.stop)
        self.heads = []   # the box's LANDER_SELF_MERGE_HEADS_demo
        p = mock.patch.object(TK, "self_merge_heads", lambda repo: self.heads)
        p.start()
        self.addCleanup(p.stop)

    def job(self, pr, state, repo="demo"):
        """A job brought to `state` along the lane's own edges, as the lane leaves it."""
        j = T.Job(repo=repo, pr=pr, head="a" * 40)
        J.save(j)
        if state == T.QUERY:
            J.move(j, T.QUERY, "it changes the lander itself — lander-self lands it")
        elif state == T.HELD:
            j.extra.update(held_from=T.QUEUED, hold="box", not_before=E.stamp(9999999999))
            J.move(j, T.HELD, "a usage wall")
        return j

    def log(self):
        with open(E.log_path()) as f:
            return f.read()

    def merged(self, oid="m" * 40):
        return {"state": "MERGED", "mergedAt": MERGED_AT, "mergeCommit": {"oid": oid}}

    def test_a_lander_self_merge_moves_the_query_to_merged_with_the_lanes_merged_line(self):
        self.job(7, T.QUERY)
        self.job(8, T.QUERY)          # another query of the repo, still open: kept
        self.gh = {7: self.merged("c" * 40), 8: {"state": "OPEN"}}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = TK.cmd_settle_merged(["demo", "7", "--by", "lander-self"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.asked, [7])   # one PR asked by hand: no other job is read
        self.assertIn("PR #7: merged on GitHub (lander-self) — query -> merged -> done", buf.getvalue())
        j = J.load("demo", 7)
        self.assertEqual(j.state, T.DONE)
        self.assertEqual([h["state"] for h in j.history][-2:], [T.MERGED, T.DONE])
        log = self.log()
        self.assertRegex(log, rf"\tstage demo#7 merged by=lander-self sha={'c' * 12} merged_at={MERGED_AT}\n")
        self.assertRegex(log, r"\tdone demo#7 rc=0\n")
        self.assertEqual(J.load("demo", 8).state, T.QUERY)   # suppressed: GitHub says it is still open
        self.assertNotIn("demo#8 merged", log)

    def test_settle_merged_leaves_a_job_that_is_not_query_or_held(self):
        j = T.Job(repo="demo", pr=9, head="a" * 40)
        J.save(j)                      # queued: the lane's own queued() reads GitHub for it
        self.gh = {9: self.merged()}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            TK.cmd_settle_merged(["demo", "9"])
        self.assertEqual(J.load("demo", 9).state, T.QUEUED)
        self.assertEqual(self.asked, [])
        self.assertIn("nothing moved", buf.getvalue())

    def test_the_tick_sweep_ends_a_backlog_merged_or_closed_outside_the_lander(self):
        self.job(1, T.QUERY)
        self.job(2, T.QUERY)
        self.job(3, T.HELD)
        self.job(4, T.QUERY)
        self.job(5, T.QUERY)
        self.gh = {1: self.merged(), 2: {"state": "CLOSED"}, 3: self.merged(), 4: {"state": "OPEN"}, 5: None}
        lines = TK.sweep_ended()
        self.assertEqual(sorted(self.asked), [1, 2, 3, 4, 5])
        self.assertEqual({p: J.load("demo", p).state for p in (1, 2, 3, 4, 5)},
                         {1: T.DONE, 2: T.DONE, 3: T.DONE, 4: T.QUERY, 5: T.QUERY})
        log = self.log()
        self.assertRegex(log, rf"\tstage demo#1 merged by=outside sha={'m' * 12} merged_at={MERGED_AT}\n")
        self.assertRegex(log, rf"\tstage demo#3 merged by=outside sha={'m' * 12} merged_at={MERGED_AT}\n")
        self.assertRegex(log, r"\tdone demo#2 rc=1\n")
        self.assertNotIn("demo#2 merged", log)                  # closed is not merged
        self.assertNotRegex(log, r"demo#[45] (merged|rc=)")     # open, and unread, stay as they were
        self.assertTrue(any("PR #5: gh could not say" in ln for ln in lines))
        # every ended job left the live directory for rest/: the readers count *.json as in flight
        self.assertFalse(os.path.exists(J.job_path("demo", 3)))
        self.assertTrue(os.path.exists(J.rest_path("demo", 3)))

    def test_an_open_job_on_a_head_its_repo_lands_itself_is_let_go(self):
        self.heads = ["dispatch/"]
        self.job(1, T.HELD)
        self.job(2, T.QUERY)
        self.job(3, T.HELD)
        self.gh = {1: {"state": "OPEN", "headRefName": "dispatch/146"},
                   2: {"state": "OPEN", "headRefName": "dispatch/x"}, 3: {"state": "OPEN", "headRefName": "track/fix"}}
        lines = TK.sweep_ended()
        self.assertEqual({p: J.load("demo", p).state for p in (1, 2, 3)}, {1: T.DONE, 2: T.DONE, 3: T.HELD})
        self.assertTrue(os.path.exists(J.rest_path("demo", 1)))
        self.assertRegex(self.log(), r"\tdone demo#1 rc=1\n")
        self.assertNotIn("demo#1 merged", self.log())
        self.assertIn("[demo] PR #1: its repo lands it itself — held -> done", lines)

    def test_a_silent_cc_config_lets_no_open_job_go(self):
        self.heads = None
        self.job(1, T.HELD)
        self.gh = {1: {"state": "OPEN", "headRefName": "x/1"}}
        self.assertEqual((TK.sweep_ended(), J.load("demo", 1).state), ([], T.HELD))

    def test_the_sweep_runs_at_most_once_a_window_per_repo(self):
        self.job(1, T.QUERY)
        self.gh = {1: {"state": "OPEN"}}
        TK.sweep_ended()
        TK.sweep_ended()
        self.assertEqual(self.asked, [1])

    def test_a_held_job_moves_only_while_no_lane_runs(self):
        self.job(3, T.HELD)
        self.job(4, T.QUERY)
        self.gh = {3: self.merged(), 4: self.merged()}
        with J.lane_lock("demo") as got:   # a lane holds the repo: its held job is its own to move
            self.assertTrue(got)
            pid = os.fork()
            if pid == 0:   # the sweep runs in another process, as the tick does, so the flock really is held
                code = 1
                try:
                    TK.settle_ended("demo", [3, 4])
                    code = 0
                finally:
                    os._exit(code)
            self.assertEqual(os.waitpid(pid, 0)[1], 0)
        self.assertEqual(J.load("demo", 3).state, T.HELD)   # suppressed: the lane's
        self.assertEqual(J.load("demo", 4).state, T.DONE)   # kept: a query is at rest, not the lane's

    def test_a_rest_lock_held_elsewhere_skips_the_sweep(self):
        self.job(1, T.QUERY)
        self.gh = {1: self.merged()}
        with J.rest_lock("demo") as got:
            self.assertTrue(got)
            pid = os.fork()
            if pid == 0:
                code = 1
                try:
                    code = 0 if TK.settle_ended("demo", [1]) == [] else 2
                finally:
                    os._exit(code)
            self.assertEqual(os.waitpid(pid, 0)[1], 0)
        self.assertEqual(J.load("demo", 1).state, T.QUERY)
        TK.settle_ended("demo", [1])                        # free again: it moves
        self.assertEqual(J.load("demo", 1).state, T.DONE)

    def test_a_held_job_the_lane_merged_is_left_to_the_lanes_own_path(self):
        """Opus handback on #1250: a job the lane held after its merge call (lane.mergeable, merge_attempt set) is
        the lane's to prove, close, post and deploy; the sweep must not mark it by=outside."""
        self.job(3, T.HELD)                     # held before the merge: kept, it moves
        j = self.job(4, T.HELD)                 # held with a merge attempt on it: suppressed
        j.extra["merge_attempt"] = {"expected": "e" * 40, "pin": "a" * 40}
        J.save(j)
        j = self.job(5, T.HELD)                 # held from past PRE_MERGE: suppressed
        j.extra["held_from"] = T.MERGEABLE
        J.save(j)
        self.gh = {3: self.merged(), 4: self.merged(), 5: self.merged()}
        self.assertEqual(TK.ended_jobs("demo"), {"demo": [3]})
        TK.settle_ended("demo", [3, 4, 5])
        self.assertEqual(self.asked, [3])
        self.assertEqual(J.load("demo", 3).state, T.DONE)
        for pr in (4, 5):
            self.assertEqual(J.load("demo", pr).state, T.HELD)
        self.assertIn("stage demo#3 merged by=outside", self.log())
        self.assertNotIn("demo#4 merged", self.log())
        self.assertNotIn("demo#5 merged", self.log())

    def test_no_gh_call_runs_while_a_lock_is_held(self):
        """Opus handback on #1250: a gh call may take 60 s, and a lane that starts meanwhile exits 'already
        running' when the sweep holds its lock. Each lock is probed from a fresh descriptor inside the gh call."""
        import fcntl
        self.job(1, T.QUERY)
        self.job(2, T.HELD)
        self.gh = {1: self.merged(), 2: {"state": "CLOSED"}}
        held = []
        real = GH.pr_facts

        def probing(root, pr, fields, token=None, timeout=120):
            for name in ("lock", "settle"):
                fd = os.open(J.lane_file("demo", name), os.O_RDWR | os.O_CREAT, 0o644)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except BlockingIOError:
                    held.append((pr, name))
                finally:
                    os.close(fd)
            return real(root, pr, fields, token, timeout)
        os.makedirs(J.lanes_dir(), exist_ok=True)
        with mock.patch.object(GH, "pr_facts", probing):
            TK.settle_ended("demo", [1, 2])
        self.assertEqual(self.asked, [1, 2])
        self.assertEqual(held, [])
        self.assertEqual(J.load("demo", 1).state, T.DONE)   # and both still move, under the locks
        self.assertEqual(J.load("demo", 2).state, T.DONE)

    def test_a_job_requeued_while_github_is_asked_is_not_moved(self):
        self.job(1, T.QUERY)
        self.job(2, T.QUERY)
        self.gh = {1: self.merged(), 2: self.merged()}
        real = GH.pr_facts

        def requeue(root, pr, fields, token=None, timeout=120):
            if int(pr) == 1:   # a person queues #1 again while its gh call runs
                J.move(J.load("demo", 1), T.QUEUED, why="requeued")
            return real(root, pr, fields, token, timeout)
        with mock.patch.object(GH, "pr_facts", requeue):
            TK.settle_ended("demo", [1, 2])
        self.assertEqual(J.load("demo", 1).state, T.QUEUED)   # suppressed: read again under the lock
        self.assertEqual(J.load("demo", 2).state, T.DONE)     # kept

    def test_merged_and_done_are_one_save_into_rest(self):
        """perms handback on #1250: two saves left a live `merged` file a running lane could take to deploy-pending
        over the done. The held job's one save is done, in rest/; the live file is gone."""
        self.job(3, T.HELD)
        self.job(4, T.QUERY)
        self.gh = {3: self.merged(), 4: self.merged()}
        saved, real = [], J.save

        def spy(job):   # after each of the sweep's saves a lane looks, as Lane.merged would: a live merged job is
            saved.append((job.pr, job.state))   # sent on to deploy-pending over whatever the sweep writes next
            real(job)
            for j in J.lane_jobs("demo"):
                if j.state == T.MERGED:
                    j.state = T.DEPLOY_PENDING
                    real(j)
        with mock.patch.object(J, "save", spy):
            TK.settle_ended("demo", [3, 4])
        self.assertEqual(saved, [(3, T.DONE), (4, T.DONE)])
        self.assertEqual(J.load("demo", 3).state, T.DONE)   # no lane save landed between merged and done
        self.assertFalse(os.path.exists(J.job_path("demo", 3)))
        self.assertTrue(os.path.exists(J.rest_path("demo", 3)))
        j = J.load("demo", 3)
        self.assertEqual([h["state"] for h in j.history][-2:], [T.MERGED, T.DONE])   # both edges kept in history
        self.assertIn("stage demo#3 merged by=outside", self.log())

    def test_one_repos_fault_does_not_end_the_sweep(self):
        os.makedirs(os.path.join(self.tmp, "dev", "other", ".git"))
        self.job(1, T.QUERY, repo="other")
        self.job(2, T.QUERY)
        self.gh = {1: self.merged(), 2: self.merged()}
        real = TK.settle_ended

        def faulty(repo, prs, **kw):
            if repo == "other":
                raise OSError("disk gone")
            return real(repo, prs, **kw)
        with mock.patch.object(TK, "settle_ended", faulty):
            lines = TK.sweep_ended()
        self.assertIn("[other] the ended sweep failed: OSError: disk gone", lines)   # said
        self.assertIn("tick-fault other", self.log())                               # and logged
        self.assertEqual(J.load("other", 1).state, T.QUERY)
        self.assertEqual(J.load("demo", 2).state, T.DONE)                           # the other repo still settles

    def test_lead_time_of_a_merge_found_later_runs_to_githubs_merged_at(self):
        q = E.epoch_of("2026-10-12T17:00:00Z")
        lines = [f"{E.stamp(q)}\tqueued demo#7",
                 f"2026-10-13T09:00:00Z\tstage demo#7 merged by=outside sha=abc merged_at={MERGED_AT}",
                 f"{E.stamp(q)}\tqueued demo#8",
                 "2026-10-12T18:00:00Z\tstage demo#8 merged sha=abc"]
        got = E.lead_times(lines)
        self.assertEqual(sorted(got["first"]), [2939, 3600])   # #7 to 17:48:59, not the sweep's next morning


if __name__ == "__main__":
    unittest.main()
