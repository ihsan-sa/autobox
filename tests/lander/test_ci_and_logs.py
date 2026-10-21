"""The lane merges only on green GitHub CI, and a red check keeps its full log and names its cause.

    python3 -m unittest discover -s core/tests/lander -p 'test_ci_and_logs.py' -v

The CI cases use test_lane's fixture (a bare origin, a fake gh answering from a JSON file); each PR's
statusCheckRollup is set on the fake. The log cases use test_run's Env (its own LANDER_STATE and repo).
"""
import json
import os
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import test_lane as TL  # noqa: E402
import test_run as TR  # noqa: E402
from lander import events as E  # noqa: E402
from lander import gh as GH  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import lane as L  # noqa: E402
from lander import run as RUN  # noqa: E402
from lander import types as T  # noqa: E402

setUpModule, tearDownModule = TL.setUpModule, TL.tearDownModule


def run_(name, status="COMPLETED", conclusion="SUCCESS", url="https://ci/1"):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion, "detailsUrl": url}


def ctx(name, state):
    return {"__typename": "StatusContext", "context": name, "state": state, "targetUrl": ""}


class CIGate(TL.Fixture):
    def handed(self, pr=1):
        p = J.handed_path("demo", pr)
        return J.read_json(p) if os.path.exists(p) else None

    def test_red_ci_hands_back_and_never_merges(self):
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[run_("lint"), run_("test-and-build", conclusion="FAILURE")])
        J.submit("demo", 1)
        self.land()
        self.assertEqual(self.box().get("merges", []), [])
        h = self.handed()
        self.assertIsNotNone(h)
        self.assertIn("GitHub CI is red", h["why"])
        self.assertIn("test-and-build failure (https://ci/1)", h["why"])
        self.assertNotIn("lint", h["why"])   # a passing check is not named as the cause

    def test_a_red_status_context_hands_back(self):
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[ctx("ci/build", "ERROR")])
        J.submit("demo", 1)
        self.land()
        self.assertEqual(self.box().get("merges", []), [])
        self.assertIn("ci/build error", self.handed()["why"])

    def test_running_ci_holds_then_merges_once_green(self):
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[run_("lint"), run_("test", status="IN_PROGRESS",
                                                                          conclusion="")])
        J.submit("demo", 1)
        self.land()
        j = self.job()
        self.assertEqual(self.box().get("merges", []), [])
        self.assertEqual((j.state, j.extra["held_from"]), (T.HELD, T.MERGEABLE))
        self.assertIn("still running: test", j.extra["why"])
        self.assertIsNone(self.handed())
        b = self.box()
        b["prs"]["1"]["statusCheckRollup"] = [run_("lint"), run_("test")]
        self.set_box(prs=b["prs"])
        j.extra["not_before"] = "2000-01-01T00:00:00Z"
        J.save(j)
        self.land()
        self.assertEqual(len(self.box()["merges"]), 1)
        self.assertNotIn("ci_wait", self.job().extra)

    def test_a_pending_status_context_holds(self):
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[ctx("ci/build", "PENDING")])
        J.submit("demo", 1)
        self.land()
        self.assertEqual(self.box().get("merges", []), [])
        self.assertEqual(self.job().state, T.HELD)

    def test_ci_that_never_finishes_becomes_a_query(self):
        head = self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[run_("test", status="QUEUED", conclusion="")])
        J.submit("demo", 1)
        self.land()
        j = self.job()
        self.assertEqual(j.extra["ci_wait"], {"head": head, "n": 1})
        j.extra["ci_wait"]["n"] = L.CI_WAITS
        j.extra["not_before"] = "2000-01-01T00:00:00Z"
        J.save(j)
        self.land()
        j = self.job()
        self.assertEqual(j.state, T.QUERY)
        self.assertIn("has not finished", j.extra["why"])
        self.assertEqual(self.box().get("merges", []), [])

    def test_green_ci_merges(self):
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[run_("test"), run_("docs", conclusion="SKIPPED"),
                                                      ctx("ci/build", "SUCCESS")])
        J.submit("demo", 1)
        self.land()
        self.assertEqual(len(self.box()["merges"]), 1)
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)

    def test_no_ci_lands_as_before(self):
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[])
        J.submit("demo", 1)
        self.land()
        self.assertEqual(len(self.box()["merges"]), 1)

    def again(self):
        j = self.job()
        j.extra["not_before"] = "2000-01-01T00:00:00Z"
        J.save(j)
        self.land()
        return self.job()

    def with_workflows(self):
        self.push("main", {".github/workflows/ci.yml": "on: pull_request\n"}, fresh=False)

    def test_no_check_yet_on_a_base_with_workflows_waits_for_them(self):
        self.with_workflows()
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[])
        J.submit("demo", 1)
        self.land()
        j = self.job()
        self.assertEqual(self.box().get("merges", []), [])
        self.assertEqual((j.state, j.extra["held_from"]), (T.HELD, T.MERGEABLE))
        self.assertIn("no check has registered yet", j.extra["why"])
        b = self.box()
        b["prs"]["1"]["statusCheckRollup"] = [run_("test", conclusion="FAILURE")]   # the runs show up, and fail
        self.set_box(prs=b["prs"])
        self.again()
        self.assertEqual(self.box().get("merges", []), [])
        self.assertIn("test failure", self.handed()["why"])

    def test_workflows_that_never_run_on_a_pr_land_after_the_wait(self):
        self.with_workflows()
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[])
        J.submit("demo", 1)
        self.land()
        for _ in range(L.CI_REGISTER_WAITS - 1):
            self.assertEqual(self.again().state, T.HELD)
        self.assertEqual(self.box().get("merges", []), [])
        self.again()
        self.assertEqual(len(self.box()["merges"]), 1)
        self.assertNotIn("ci_wait", self.job().extra)

    def test_unreadable_ci_holds_then_becomes_a_query(self):
        head = self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[run_("test")])
        self.set_box(checks_denied="HTTP 403: Resource not accessible by personal access token")
        J.submit("demo", 1)
        self.land()
        j = self.job()
        self.assertEqual((j.state, j.extra["held_from"]), (T.HELD, T.MERGEABLE))
        self.assertIn("could not be read", j.extra["why"])
        self.assertEqual(j.extra["ci_unread"], {"head": head, "n": 1})
        self.assertEqual(self.again().extra["ci_unread"]["n"], 2)   # the plain PR read still works: it comes back
        j = self.job()
        j.extra["ci_unread"]["n"] = L.CI_UNREADS
        J.save(j)
        j = self.again()
        self.assertEqual(j.state, T.QUERY)
        self.assertIn("could not be read", j.extra["why"])
        self.assertIn("403", j.extra["why"])
        self.assertEqual(self.box().get("merges", []), [])

    def test_a_spent_rate_limit_keeps_its_job_and_lands_after_the_reset(self):
        reset = int(time.time()) + 3000
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[run_("test")])
        self.set_box(checks_denied="gh: API rate limit exceeded for user ID 1. (HTTP 403)",
                     rate_limit={"remaining": 0, "reset": reset})
        J.submit("demo", 1)
        self.land()
        for _ in range(L.CI_UNREADS + 2):   # more spent reads than an unreadable CI is allowed before a query
            os.unlink(GH.backoff_path())    # the backoff the spent read set has run out
            j = self.again()
            self.assertEqual((j.state, j.extra["held_from"]), (T.HELD, T.MERGEABLE))
            self.assertIn(GH.SPENT, j.extra["why"])
            self.assertEqual(j.extra["not_before"], E.stamp(reset))   # held until GitHub's own reset, no longer
            self.assertNotIn("ci_unread", j.extra)
        self.set_box(checks_denied="", rate_limit=None)   # the quota resets
        os.unlink(GH.backoff_path())
        self.again()
        self.assertEqual(len(self.box()["merges"]), 1)

    def test_a_member_tokens_spent_quota_holds_its_job_not_every_lane(self):
        # Opus read of #1799: a member lane's spent installation quota wrote the shared backoff, and while it stands
        # the tick skips every lane and handed watch on the box
        reset = int(time.time()) + 3000
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[run_("test")])
        self.set_box(checks_denied="gh: API rate limit exceeded for installation ID 1. (HTTP 403)",
                     rate_limit={"remaining": 0, "reset": reset})
        J.submit("demo", 1)
        init = L.Lane.__init__

        def member(lane, *a, **kw):
            init(lane, *a, **kw)
            lane.token = "member-token"
        with mock.patch.object(L.Lane, "__init__", member):
            self.land()
        j = self.job()
        self.assertEqual((j.state, j.extra["not_before"]), (T.HELD, E.stamp(reset)))   # its own job waits the hour
        self.assertIn(GH.SPENT, j.extra["why"])
        self.assertEqual(GH.backoff(), 0)   # what tick reads before every lane: another repo's lane still ticks

    def test_rate_limit_words_with_the_quota_left_become_a_query(self):
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[run_("test")])
        self.set_box(checks_denied="gh: rate limit, or so a proxy says (HTTP 403)")   # rate_limit: 5000 left
        J.submit("demo", 1)
        self.land()
        for n in range(1, L.CI_UNREADS + 1):
            j = self.job()
            self.assertEqual((j.state, j.extra["ci_unread"]["n"]), (T.HELD, n))
            self.assertNotIn(GH.SPENT, j.extra["why"])
            os.unlink(GH.backoff_path())
            j = self.again()
        self.assertEqual(j.state, T.QUERY)
        self.assertIn("rate limit, or so a proxy says", j.extra["why"])

    def test_a_readable_ci_clears_the_unread_count(self):
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[run_("test")])
        self.set_box(checks_denied="HTTP 403: Resource not accessible by integration")
        J.submit("demo", 1)
        self.land()
        self.set_box(checks_denied="")
        self.again()
        self.assertEqual(len(self.box()["merges"]), 1)
        self.assertNotIn("ci_unread", self.job().extra)


STARVED_URL = "https://github.com/o/r/actions/runs/77/job/88"
STARVED_NOTE = {"message": "The job was not acquired by Runner of type hosted even after multiple attempts"}


class Starved(TL.Fixture):
    """A job GitHub cancelled because no hosted runner took it is rerun, not handed back (2026-10-05: #80 and #93-95
    handed back as red CI with nothing in their code failing). Each case queues its own PR."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(GH, "slug", lambda root: "o/r")   # the fixture's origin is a bare repo, not GitHub
        p.start()
        self.addCleanup(p.stop)

    def starved_pr(self, name="test", job=None):
        head = self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[run_("lint"), run_(name, conclusion="CANCELLED",
                                                                                 url=STARVED_URL)])
        self.set_box(annotations={"88": [STARVED_NOTE]}, check_runs={"88": {"app": {"slug": "github-actions"}}},
                     jobs={"88": {"run_id": 77, "head_sha": head, **(job or {})}})
        J.submit("demo", 1)

    def again(self):
        j = self.job()
        j.extra["not_before"] = "2000-01-01T00:00:00Z"
        J.save(j)
        self.land()

    def test_a_runner_starved_cancel_is_rerun_and_then_merges(self):
        self.starved_pr()
        self.set_box(after_rerun=[run_("lint"), run_("test")])
        self.land()
        j = self.job()
        self.assertEqual((j.state, j.extra["held_from"]), (T.HELD, T.MERGEABLE))
        self.assertIn("for want of a hosted runner", j.extra["why"])
        self.assertIn("rerun 77", j.extra["why"])
        self.assertEqual(self.box()["reruns"], ["77"])
        self.assertFalse(os.path.exists(J.handed_path("demo", 1)))
        self.again()
        self.assertEqual(len(self.box()["merges"]), 1)
        self.assertEqual(self.box()["reruns"], ["77"])

    def test_a_cancel_still_starved_after_the_reruns_is_handed_back(self):
        self.starved_pr()   # no after_rerun: every rerun is starved again
        self.land()
        for _ in range(L.STARVED_RERUNS):
            self.again()
        self.assertEqual(self.box()["reruns"], ["77"] * L.STARVED_RERUNS)
        self.assertEqual(self.box().get("merges", []), [])
        self.assertIn("GitHub CI is red", J.read_json(J.handed_path("demo", 1))["why"])

    def test_a_hostile_check_name_reruns_only_the_run_github_vouches_for(self):
        # a member's job named to look like a run id must not steer the rerun onto run 999 (seat security read)
        self.starved_pr(name="x (run 999)")
        self.land()
        self.assertEqual(self.box()["reruns"], ["77"])

    def red_with_no_rerun(self, job):
        self.starved_pr(job=job)
        self.land()
        self.assertNotIn("reruns", self.box())
        self.assertIn("GitHub CI is red", J.read_json(J.handed_path("demo", 1))["why"])

    def test_a_url_whose_job_is_another_runs_is_red_with_no_rerun(self):
        self.red_with_no_rerun({"run_id": 55})

    def test_a_job_at_another_head_is_red_with_no_rerun(self):
        self.red_with_no_rerun({"head_sha": "f" * 40})

    def test_a_real_failure_beside_a_starved_cancel_hands_back_with_no_rerun(self):
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[run_("lint", conclusion="FAILURE"),
                                                      run_("test", conclusion="CANCELLED", url=STARVED_URL)])
        self.set_box(annotations={"88": [STARVED_NOTE]})
        J.submit("demo", 1)
        self.land()
        self.assertNotIn("reruns", self.box())
        self.assertIn("lint failure", J.read_json(J.handed_path("demo", 1))["why"])


class CIState(unittest.TestCase):
    def facts(self, j):
        return mock.patch.object(GH, "pr_facts", lambda *a, **k: (j, "") if j is not None else (None, "gh down"))

    def test_states(self):
        pin = "a" * 40
        cases = [({"headRefOid": pin, "statusCheckRollup": None}, "none"),
                 ({"headRefOid": pin, "statusCheckRollup": [run_("t")]}, "green"),
                 ({"headRefOid": pin, "statusCheckRollup": [run_("t", conclusion="CANCELLED")]}, "red"),
                 ({"headRefOid": pin, "statusCheckRollup": [run_("t", conclusion="FAILURE"),
                                                            run_("u", status="IN_PROGRESS", conclusion="")]}, "red"),
                 ({"headRefOid": pin, "statusCheckRollup": [ctx("s", "EXPECTED")]}, "pending"),
                 # GitHub's checks belong to another head than the one the merge pins: they say nothing about it
                 ({"headRefOid": "b" * 40, "statusCheckRollup": [run_("t")]}, "pending"),
                 (None, "")]
        for j, want in cases:
            with self.subTest(j=j), self.facts(j):
                self.assertEqual(GH.ci_state("/x", 1, pin)[0], want)

    def test_a_cancel_is_starved_only_when_github_vouches_for_its_run_head_and_app(self):
        pin = "a" * 40
        cancelled = run_("t", conclusion="CANCELLED", url=STARVED_URL)
        job = {"run_id": 77, "head_sha": pin}
        actions = {"app": {"slug": "github-actions"}}
        running = run_("u", status="IN_PROGRESS", conclusion="")
        cases = [  # (annotations, actions job 88, check run 88, rollup, state, run ids)
            ([STARVED_NOTE], job, actions, [cancelled], "starved", ["77"]),
            ([STARVED_NOTE], job, actions, [run_("x (run 999)", conclusion="CANCELLED", url=STARVED_URL)],
             "starved", ["77"]),   # a name that looks like a run id steers nothing
            ([{"message": "The operation was canceled."}], job, actions, [cancelled], "red", []),
            ([STARVED_NOTE], job, actions, [cancelled, run_("u", conclusion="FAILURE")], "red", []),
            ([STARVED_NOTE], job, actions, [run_("t", conclusion="CANCELLED", url="https://ci/1")], "red", []),
            ([STARVED_NOTE], {**job, "run_id": 55}, actions, [cancelled], "red", []),   # the URL's job is another run's
            ([STARVED_NOTE], {**job, "head_sha": "b" * 40}, actions, [cancelled], "red", []),   # another head's job
            ([STARVED_NOTE], None, actions, [cancelled], "red", []),   # no such Actions job
            ([STARVED_NOTE], job, {"app": {"slug": "some-app"}}, [cancelled], "red", []),   # not GitHub Actions
            # another job still runs: rerun --failed would refuse, so it waits rather than spend a try
            ([STARVED_NOTE], job, actions, [cancelled, running], "pending", [])]
        for notes, aj, cr, rows, want, ids in cases:
            answers = {"repos/o/r/check-runs/88/annotations": notes, "repos/o/r/actions/jobs/88": aj,
                       "repos/o/r/check-runs/88": cr}

            def gh(argv, root, token=None, timeout=120, answers=answers):
                self.assertEqual(argv[0], "api")
                got = answers[argv[1]]
                return (0, json.dumps(got), "") if got is not None else (1, "", "HTTP 404")
            runs = []
            with self.subTest(aj=aj, cr=cr, rows=rows), \
                    self.facts({"headRefOid": pin, "statusCheckRollup": rows}), \
                    mock.patch.object(GH, "slug", lambda root: "o/r"), mock.patch.object(GH, "gh", gh):
                state, detail = GH.ci_state("/x", 1, pin, runs=runs)
                self.assertEqual((state, runs), (want, ids))
                self.assertNotIn("999", "".join(runs))

    def test_an_empty_list_on_a_base_with_workflows_is_not_no_ci(self):
        pin = "a" * 40
        for rows, want in (([], "unregistered"), (None, "unregistered"), ([run_("t")], "green")):
            with self.subTest(rows=rows), self.facts({"headRefOid": pin, "statusCheckRollup": rows}):
                self.assertEqual(GH.ci_state("/x", 1, pin, workflows=True)[0], want)


class RestFacts(unittest.TestCase):
    """pr_facts answers the lane's fields over REST, in gh pr view's shape; only comments and checks spend GraphQL."""
    PULL = {"number": 7, "state": "closed", "merged_at": "2026-10-19T18:00:00Z", "merge_commit_sha": "m" * 40,
            "draft": False, "mergeable": None, "mergeable_state": "behind", "title": "t", "body": None,
            "head": {"sha": "h" * 40, "ref": "track/x"}, "base": {"ref": "main"}, "html_url": "https://github.com/o/r/pull/7"}

    def run_gh(self, answers):
        calls = []

        def gh(argv, root, token=None, timeout=120, note=True):
            calls.append(argv)
            got = answers.get(" ".join(argv))
            return got if isinstance(got, tuple) else (0, got, "") if got is not None else (1, "", "HTTP 404")
        return calls, mock.patch.object(GH, "gh", gh)

    def test_lane_fields_are_one_rest_get(self):
        calls, p = self.run_gh({"api repos/o/r/pulls/7": json.dumps(self.PULL)})
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):
            j, why = GH.pr_facts("/x", 7, "state,headRefOid,headRefName,baseRefName,mergeCommit,mergeable,body,isDraft")
        self.assertEqual((j, why), ({"state": "MERGED", "headRefOid": "h" * 40, "headRefName": "track/x",
                                     "baseRefName": "main", "mergeCommit": {"oid": "m" * 40}, "mergeable": "UNKNOWN",
                                     "body": "", "isDraft": False}, ""))
        self.assertEqual(calls, [["api", "repos/o/r/pulls/7"]])
        open_pr = dict(self.PULL, state="open", merged_at=None, mergeable=False)
        _, p = self.run_gh({"api repos/o/r/pulls/7": json.dumps(open_pr)})
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):
            j, _ = GH.pr_facts("/x", 7, "state,mergeCommit,mergeable,mergeStateStatus")
        self.assertEqual(j, {"state": "OPEN", "mergeCommit": None, "mergeable": "CONFLICTING",
                             "mergeStateStatus": "BEHIND"})

    def test_files_are_the_rest_file_list(self):
        calls, p = self.run_gh({"api --paginate repos/o/r/pulls/7/files?per_page=100 -q .[].filename": "a.py\nb/c.sh\n"})
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):
            self.assertEqual(GH.pr_files("/x", 7), ["a.py", "b/c.sh"])
        self.assertEqual(len(calls), 1)

    def test_checks_are_the_heads_check_runs_and_statuses(self):
        pin = "h" * 40
        calls, p = self.run_gh({
            "api repos/o/r/pulls/7": json.dumps(self.PULL),
            f"api repos/o/r/commits/{pin}/check-runs?per_page=100": json.dumps({"total_count": 2, "check_runs": [
                {"name": "check", "status": "completed", "conclusion": "success", "details_url": "u1"},
                {"name": "slow", "status": "in_progress", "conclusion": None, "details_url": "u2"}]}),
            f"api repos/o/r/commits/{pin}/status?per_page=100": json.dumps({"total_count": 1, "statuses": [
                {"context": "ci/x", "state": "failure", "target_url": "u3"}]})})
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):
            j, _ = GH.pr_facts("/x", 7, "headRefOid,statusCheckRollup")
            self.assertEqual(GH.ci_state("/x", 7, pin), ("red", "ci/x failure (u3)"))
        self.assertEqual(j["statusCheckRollup"], [
            {"__typename": "CheckRun", "name": "check", "status": "COMPLETED", "conclusion": "SUCCESS", "detailsUrl": "u1"},
            {"__typename": "CheckRun", "name": "slow", "status": "IN_PROGRESS", "conclusion": "", "detailsUrl": "u2"},
            {"__typename": "StatusContext", "context": "ci/x", "state": "FAILURE", "targetUrl": "u3"}])
        self.assertFalse([c for c in calls if c[:2] == ["pr", "view"]])
        _, p = self.run_gh({"api repos/o/r/pulls/7": json.dumps(self.PULL)})   # a checks list GitHub would not give
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):              # is unreadable, never "no CI"
            self.assertEqual(GH.ci_state("/x", 7, pin)[0], "")

    def test_more_than_a_page_of_checks_is_paged_on(self):
        # perms on #1547: one page of check runs held 100, so a red 101st was never read
        pin, ok = "h" * 40, {"name": "c", "status": "completed", "conclusion": "success", "details_url": "u"}
        runs = f"api repos/o/r/commits/{pin}/check-runs?per_page=100"
        calls, p = self.run_gh({
            "api repos/o/r/pulls/7": json.dumps(self.PULL),
            runs: json.dumps({"total_count": 101, "check_runs": [ok] * 100}),
            runs + "&page=2": json.dumps({"total_count": 101, "check_runs": [
                {"name": "late", "status": "completed", "conclusion": "failure", "details_url": "u9"}]}),
            f"api repos/o/r/commits/{pin}/status?per_page=100": json.dumps({"total_count": 0, "statuses": []})})
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):
            self.assertEqual(GH.ci_state("/x", 7, pin)[0], "red")
        self.assertEqual(sum("check-runs" in " ".join(c) for c in calls), 2)
        _, p = self.run_gh({"api repos/o/r/pulls/7": json.dumps(self.PULL),   # page 2 unanswered: unreadable, not green
                            runs: json.dumps({"total_count": 101, "check_runs": [ok] * 100}),
                            f"api repos/o/r/commits/{pin}/status?per_page=100":
                                json.dumps({"total_count": 0, "statuses": []})})
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):
            self.assertEqual(GH.ci_state("/x", 7, pin)[0], "")
        calls, p = self.run_gh({"api repos/o/r/pulls/7": json.dumps(self.PULL),   # exactly 100: total_count stops it
                                runs: json.dumps({"total_count": 100, "check_runs": [ok] * 100}),
                                f"api repos/o/r/commits/{pin}/status?per_page=100":
                                    json.dumps({"total_count": 0, "statuses": []})})
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):
            self.assertEqual(GH.ci_state("/x", 7, pin)[0], "green")
        self.assertEqual(sum("check-runs" in " ".join(c) for c in calls), 1)

    def test_a_check_list_read_short_of_its_total_is_unreadable(self):
        # the Opus read at 5f4dad4b: page 1 says 101 and holds 100 green, page 2 answers [], so the 101st was never read
        pin, ok = "h" * 40, {"name": "c", "status": "completed", "conclusion": "success", "details_url": "u"}
        runs = f"api repos/o/r/commits/{pin}/check-runs?per_page=100"
        _, p = self.run_gh({"api repos/o/r/pulls/7": json.dumps(self.PULL),
                            runs: json.dumps({"total_count": 101, "check_runs": [ok] * 100}),
                            runs + "&page=2": json.dumps({"total_count": 101, "check_runs": []}),
                            f"api repos/o/r/commits/{pin}/status?per_page=100":
                                json.dumps({"total_count": 0, "statuses": []})})
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):
            j, why = GH.pr_facts("/x", 7, "statusCheckRollup")
            self.assertEqual(GH.ci_state("/x", 7, pin)[0], "")
        self.assertIsNone(j)
        self.assertIn("read short: 100 of 101", why)

    def test_a_check_list_that_repeats_its_page_is_unreadable(self):
        # perms on #1547: the same full page every time would page forever and read green
        pin, calls = "h" * 40, []
        page = json.dumps({"total_count": 10 ** 6, "check_runs": [
            {"id": 5 + i, "name": "c", "status": "completed", "conclusion": "success", "details_url": "u"}
            for i in range(100)]})

        def gh(argv, root, token=None, timeout=120, note=True):
            calls.append(argv)
            if len(calls) > 50:
                raise AssertionError("paged on past a repeated page")
            if argv[1] == "repos/o/r/pulls/7":
                return 0, json.dumps(self.PULL), ""
            return 0, page if "check-runs" in argv[1] else json.dumps({"total_count": 0, "statuses": []}), ""
        with mock.patch.object(GH, "gh", gh), mock.patch.object(GH, "slug", lambda root: "o/r"):
            j, why = GH.pr_facts("/x", 7, "statusCheckRollup")
            self.assertEqual(GH.ci_state("/x", 7, pin)[0], "")
        self.assertIsNone(j)
        self.assertIn("repeats an earlier page", why)

    def test_a_total_count_that_is_not_a_count_is_unreadable(self):
        # perms on #1559: -1, 0 and the string '101' each passed a full page 1 as the whole list
        pin, ok = "h" * 40, {"name": "c", "status": "completed", "conclusion": "success", "details_url": "u"}
        runs = f"api repos/o/r/commits/{pin}/check-runs?per_page=100"
        for total, said in ((-1, "not a count"), ("101", "not a count"), (True, "not a count"),
                            (None, "not a count"), (100.0, "not a count"), (0, "read past: 100 of 0")):
            _, p = self.run_gh({"api repos/o/r/pulls/7": json.dumps(self.PULL),
                                runs: json.dumps({"total_count": total, "check_runs": [ok] * 100}),
                                f"api repos/o/r/commits/{pin}/status?per_page=100":
                                    json.dumps({"total_count": 0, "statuses": []})})
            with self.subTest(total=total), p, mock.patch.object(GH, "slug", lambda root: "o/r"):
                j, why = GH.pr_facts("/x", 7, "statusCheckRollup")
                self.assertIsNone(j)
                self.assertIn(said, why)
        _, p = self.run_gh({"api repos/o/r/pulls/7": json.dumps(self.PULL),   # statuses are held to it too
                            runs: json.dumps({"total_count": 1, "check_runs": [ok]}),
                            f"api repos/o/r/commits/{pin}/status?per_page=100": json.dumps({"statuses": []})})
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):
            j, why = GH.pr_facts("/x", 7, "statusCheckRollup")
        self.assertIsNone(j)
        self.assertIn("status page 1 total_count is None, not a count", why)

    def test_the_largest_total_count_across_pages_is_the_one_read_to(self):
        # the Opus read on #1559: page 1 says 102 and page 2 says 101, so the last page's total let 101 pass
        pin, ok = "h" * 40, {"name": "c", "status": "completed", "conclusion": "success", "details_url": "u"}
        runs = f"api repos/o/r/commits/{pin}/check-runs?per_page=100"
        _, p = self.run_gh({"api repos/o/r/pulls/7": json.dumps(self.PULL),
                            runs: json.dumps({"total_count": 102, "check_runs": [ok] * 100}),
                            runs + "&page=2": json.dumps({"total_count": 101, "check_runs": [dict(ok, name="late")]}),
                            f"api repos/o/r/commits/{pin}/status?per_page=100":
                                json.dumps({"total_count": 0, "statuses": []})})
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):
            j, why = GH.pr_facts("/x", 7, "statusCheckRollup")
        self.assertIsNone(j)
        self.assertIn("read short: 101 of 102", why)

    def test_pages_stop_at_the_bound_page_ones_total_count_gives(self):
        # perms on #1559: a list whose total_count grows by a page each time, of rows never seen, pages forever.
        # Page 1 says 101, so two pages is all there can be
        pin, calls = "h" * 40, []

        def gh(argv, root, token=None, timeout=120, note=True):
            calls.append(argv)
            if len(calls) > 50:
                raise AssertionError("paged on past the bound")
            if argv[1] == "repos/o/r/pulls/7":
                return 0, json.dumps(self.PULL), ""
            if "check-runs" not in argv[1]:
                return 0, json.dumps({"total_count": 0, "statuses": []}), ""
            n = int(argv[1].split("&page=")[1]) if "&page=" in argv[1] else 1
            return 0, json.dumps({"total_count": 100 * n + 1, "check_runs": [
                {"id": 1000 * n + i, "name": "c", "status": "completed", "conclusion": "success",
                 "details_url": "u"} for i in range(100)]}), ""
        with mock.patch.object(GH, "gh", gh), mock.patch.object(GH, "slug", lambda root: "o/r"):
            j, why = GH.pr_facts("/x", 7, "statusCheckRollup")
        self.assertIsNone(j)
        self.assertIn("check-runs runs past the 2 page(s) its total_count allows", why)
        self.assertEqual(sum("check-runs" in " ".join(c) for c in calls), 2)

    COMMENTS = ("api --paginate repos/o/r/issues/7/comments?per_page=100 -q "
                ".[] | {body, login: .user.login, createdAt: .created_at}")

    def test_comments_go_over_rest_too(self):
        line = json.dumps({"body": "LAND", "login": "box", "createdAt": "2026-10-19T00:00:00Z"})
        for fields in ("comments", "state,comments"):
            GH._VIEWER.clear()
            calls, p = self.run_gh({self.COMMENTS: line, "api user -q .login": "box",
                                    "api repos/o/r/pulls/7": json.dumps(self.PULL)})
            with self.subTest(fields=fields), p, mock.patch.object(GH, "slug", lambda root: "o/r"):
                j, why = GH.pr_facts("/x", 7, fields)
                self.assertEqual((j["comments"], why), ([{"body": "LAND", "author": {"login": "box"},
                                                          "createdAt": "2026-10-19T00:00:00Z",
                                                          "viewerDidAuthor": True}], ""))
                self.assertFalse(any(c[:1] != ["api"] for c in calls))   # no `gh pr view`: no GraphQL

    def test_a_spent_rate_limit_is_said_with_its_reset(self):
        reset = int(time.time()) + 3000
        limit = json.dumps({"resources": {"core": {"remaining": 4815, "reset": 1}, "graphql": {"remaining": 0, "reset": reset}}})
        for fields, ask in (("state", "api repos/o/r/pulls/7"), ("comments", self.COMMENTS)):
            _, p = self.run_gh({ask: (1, "", "GraphQL: API rate limit already exceeded for user ID 1."), "api rate_limit": limit})
            with self.subTest(fields=fields), p, mock.patch.object(GH, "slug", lambda root: "o/r"):
                self.assertEqual(GH.pr_facts("/x", 7, fields),
                                 (None, f"{GH.SPENT} until " + time.strftime("%H:%MZ", time.gmtime(reset))))
                self.assertEqual((GH.RESETS[None], GH.backoff()), (reset, 0))   # GraphQL's hour holds the job only
        said = "gh: API rate limit exceeded for user ID 1. (HTTP 403)"
        for limit in (json.dumps({"resources": {"core": {"remaining": 12, "reset": 1}}}), (1, "", "HTTP 502")):
            _, p = self.run_gh({"api repos/o/r/pulls/7": (1, "", said), "api rate_limit": limit})
            with self.subTest(limit=limit), p, mock.patch.object(GH, "slug", lambda root: "o/r"):
                # the quota left, or rate_limit itself unread: gh's words alone are not a spent quota
                self.assertEqual(GH.pr_facts("/x", 7, "state"), (None, said))
        _, p = self.run_gh({"api repos/o/r/pulls/7": (1, "", "HTTP 502: bad gateway")})
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):   # any other failure keeps gh's own words
            self.assertEqual(GH.pr_facts("/x", 7, "state"), (None, "HTTP 502: bad gateway"))


    def test_a_spent_reset_already_past_backs_off_a_minute(self):
        # Opus read of #1799: a reset in the past (clock skew) wrote a backoff already over, and every lane asked
        # GitHub against the spent quota each tick
        limit = json.dumps({"resources": {"core": {"remaining": 0, "reset": int(time.time()) - 600}}})
        self.addCleanup(os.unlink, GH.backoff_path())
        _, p = self.run_gh({"api repos/o/r/pulls/7": (1, "", "gh: API rate limit exceeded (HTTP 403)"), "api rate_limit": limit})
        with p, mock.patch.object(GH, "slug", lambda root: "o/r"):
            self.assertIn(GH.SPENT, GH.pr_facts("/x", 7, "state")[1])
        self.assertGreaterEqual(GH.backoff(), GH.BACKOFF_MIN - 1)
        self.assertGreaterEqual(GH.RESETS[None], time.time() + GH.BACKOFF_MIN - 1)

class Cause(unittest.TestCase):
    def test_internalerror_names_the_exception_and_the_file(self):
        text = ("tests/test_a.py ....F..\nINTERNALERROR> Traceback (most recent call last):\n"
                "INTERNALERROR>   File \"x.py\", line 1\nINTERNALERROR> ValueError: I/O operation on closed file.\n")
        c = RUN.cause_of(text, 3)
        self.assertIn("ValueError: I/O operation on closed file.", c)
        self.assertIn("tests/test_a.py", c)

    def test_the_short_summary_wins(self):
        text = "tests/t.py .F\nFAILED tests/t.py::test_x - assert 1 == 2\n1 failed, 1 passed\n"
        self.assertEqual(RUN.cause_of(text, 1), "FAILED tests/t.py::test_x - assert 1 == 2")

    def test_a_red_line_above_the_tail_is_named(self):
        text = "✗ check-foo\n" + "".join(f"ok line {i}\n" for i in range(RUN.TAIL * 3)) + "15 passed, 1 failed\n"
        self.assertNotIn("✗ check-foo", "\n".join(text.splitlines()[-RUN.TAIL:]))
        self.assertEqual(RUN.cause_of(text, 1), "✗ check-foo")

    def test_an_all_pass_tail_says_so(self):
        c = RUN.cause_of("........ [ 50%]\n........ [100%]\n", 1)
        self.assertIn("exit 1 with no failing line", c)
        self.assertIn("[100%]", c)
        self.assertEqual(RUN.cause_of("", 2), "exit 2 with no output at all")


class KeptLog(TR.Env):
    def test_a_red_keeps_its_full_log_and_names_its_cause(self):
        script = ("echo 'tests/test_a.py ..F'; for i in $(seq 200); do echo filler $i; done; "
                  "echo 'INTERNALERROR> ValueError: I/O operation on closed file.'; exit 3")
        r = self.run_(TR.chk(run=script, klass=T.HOST))
        self.assertEqual(r.status, T.FAILED, r.extra)
        log = r.extra["log"]
        self.assertTrue(log.startswith(os.path.join(self.state, "logs") + os.sep), log)
        with open(log) as f:
            kept = f.read()
        self.assertIn("tests/test_a.py ..F", kept)   # the head of the output, which the tail drops
        self.assertNotIn("tests/test_a.py ..F", r.extra["tail"])
        self.assertIn("ValueError: I/O operation on closed file.", r.extra["cause"])
        self.assertIn(r.extra["cause"], r.extra["why"])

    def test_a_pass_keeps_nothing(self):
        r = self.run_(TR.chk(run="echo fine", klass=T.HOST))
        self.assertEqual(r.status, T.PASSED, r.extra)
        self.assertNotIn("log", r.extra)
        self.assertFalse(os.path.exists(os.path.join(self.state, "logs")))

    def test_old_and_surplus_logs_are_pruned(self):
        d = RUN.logs_dir(self.state)
        os.makedirs(d)
        now = time.time()
        for i in range(5):
            p = os.path.join(d, f"{i}.log")
            open(p, "w").close()
            os.utime(p, (now - i, now - i))
        old = os.path.join(d, "old.log")
        open(old, "w").close()
        os.utime(old, (now - (RUN.LOG_DAYS + 1) * 86400,) * 2)
        other = os.path.join(d, "notes.txt")
        open(other, "w").close()
        with mock.patch.object(RUN, "LOG_KEEP", 3):
            RUN.prune_logs(d, now)
        self.assertEqual(sorted(os.listdir(d)), ["0.log", "1.log", "2.log", "notes.txt"])


if __name__ == "__main__":
    unittest.main()
