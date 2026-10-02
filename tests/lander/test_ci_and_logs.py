"""The lane merges only on green GitHub CI, and a red check keeps its full log and names its cause.

    python3 -m unittest discover -s core/tests/lander -p 'test_ci_and_logs.py' -v

The CI cases use test_lane's fixture (a bare origin, a fake gh answering from a JSON file); each PR's
statusCheckRollup is set on the fake. The log cases use test_run's Env (its own LANDER_STATE and repo).
"""
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

    def test_a_readable_ci_clears_the_unread_count(self):
        self.pr(1, {"a/x": "n\n"}, statusCheckRollup=[run_("test")])
        self.set_box(checks_denied="HTTP 403: Resource not accessible by integration")
        J.submit("demo", 1)
        self.land()
        self.set_box(checks_denied="")
        self.again()
        self.assertEqual(len(self.box()["merges"]), 1)
        self.assertNotIn("ci_unread", self.job().extra)


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

    def test_an_empty_list_on_a_base_with_workflows_is_not_no_ci(self):
        pin = "a" * 40
        for rows, want in (([], "unregistered"), (None, "unregistered"), ([run_("t")], "green")):
            with self.subTest(rows=rows), self.facts({"headRefOid": pin, "statusCheckRollup": rows}):
                self.assertEqual(GH.ci_state("/x", 1, pin, workflows=True)[0], want)


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
