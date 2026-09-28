"""The lane end to end with the REAL planner, runner and reviewer (U5): a fixture repo carrying a real
tests/LANDING.toml and policy, lander.plan and lander.run doing the planning and the runs, lander.review doing the
read. Only the outside is stubbed: gh and the merge API (test_lane's fakes), cc-limit, the failures ledger, and the
cards/board/deploy/tip units (they post to Slack and touch the box).

    python3 -m unittest discover -s core/tests/lander -t core/tests/lander -p 'test_u5_lane.py' -v

Load-robust: no wall-clock deadline anywhere; the checks are `host` class (no bwrap, no scope), and whether the box
is loaded only decides whether a red is rerun alone, which gives the same verdict here.
"""
import os
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.realpath(__file__))
CORE = os.path.dirname(os.path.dirname(HERE))
for p in (CORE, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import test_lane as TL  # noqa: E402
from lander import events as E  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import lane as L  # noqa: E402
from lander import plan as PLAN  # noqa: E402
from lander import records as REC  # noqa: E402
from lander import review as RV  # noqa: E402
from lander import run as RUN  # noqa: E402
from lander import types as T  # noqa: E402

MANIFEST = """
[[check]]
name = "a"
run = "sh tests/a.sh"
paths = ["a/**"]
class = "host"

[[check]]
name = "b"
run = "sh tests/b.sh"
paths = ["b/**"]
class = "host"

[[check]]
name = "c"
run = "true"
paths = ["c/**"]
class = "host"
"""
POLICY = """
default_checks = ["a"]

[paths]
paid_review = ["c/**"]
"""
# each check is red when its file says "bad"
CHECK = 'if grep -q bad {f}; then echo "FAIL {f} says bad"; exit 1; fi\necho "ok {f}"\n'
LIMIT = '#!/bin/sh\n[ "$1" = status ] && { echo "usage limit until 23:59Z (120m left)"; exit 0; }\nexit 1\n'


def setUpModule():
    TL.setUpModule()


def tearDownModule():
    TL.tearDownModule()


class RealUnits(TL.Fixture):
    def setUp(self):
        super().setUp()
        env = {"LANDER_STATE": os.environ["CC_LANDER_STATE"], "LANDER_SCOPE": "0"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.reds = []
        p = mock.patch.object(REC, "record_red", lambda scope, r, text, pr=None, **kw: self.reds.append(
            (scope, r.check, r.tree, pr)) or "recorded")
        p.start()
        self.addCleanup(p.stop)
        self.limit_bin = os.path.join(self.tmp, "limitbin")
        os.makedirs(self.limit_bin)
        with open(os.path.join(self.limit_bin, "cc-limit"), "w") as f:
            f.write(LIMIT)
        os.chmod(os.path.join(self.limit_bin, "cc-limit"), 0o755)
        p = mock.patch.object(RV, "BIN", self.limit_bin)
        p.start()
        self.addCleanup(p.stop)
        self.main({"tests/LANDING.toml": MANIFEST, "tests/LANDING-policy.toml": POLICY,
                   "tests/a.sh": CHECK.format(f="a/x"), "tests/b.sh": CHECK.format(f="b/gate")})

    def main(self, files):
        """A commit straight onto origin's main."""
        self.git(self.work, "fetch", "-q", "origin")
        self.git(self.work, "checkout", "-q", "-B", "main", "origin/main")
        self.write(self.work, files)
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-qm", f"main {sorted(files)}")
        self.git(self.work, "push", "-q", "origin", "main:refs/heads/main")

    def land(self, repo="demo", **units):
        u = {"planner": PLAN, "runner": RUN, "reviewer": RV, "cards": TL.Rec(), "board": TL.Rec(),
             "deploy": TL.Rec(), "tip": TL.Rec()}
        u.update(units)
        return u, L.Lane(repo, u).run()

    def test_a_green_pr_merges_through_the_real_plan_and_runs(self):
        self.pr(1, {"a/x": "good\n"})
        J.submit("demo", 1)
        u, lines = self.land()
        j = self.job()
        self.assertEqual(j.state, T.DEPLOY_PENDING, lines)
        self.assertEqual(j.plan.checks, ["a"])
        self.assertEqual(list(j.results), ["a"])
        self.assertEqual(u["deploy"].calls, [("request", "demo", self.origin_rev("main"), [])])
        self.assertIn("stage demo#1 gate gate=a ok=yes", self.log())
        self.assertEqual(self.reds, [])
        # the run was stored by the lane under its lock: the job's own record of check a on the merge tree
        store = REC.Store("demo", root=J.landq())
        self.assertIsNotNone(store.get(j.key, "a", j.extra["tree"]))

    def test_a_red_pr_is_handed_back_and_recorded_once(self):
        self.pr(1, {"a/x": "bad\n"})
        J.submit("demo", 1)
        u, lines = self.land()
        self.assertIsNone(self.job(), lines)                          # handed back: the job file is gone
        self.assertTrue(os.path.exists(J.handed_path("demo", 1)))
        self.assertEqual(u["cards"].calls[0][0], "stopped")
        self.assertEqual([(s, c, pr) for s, c, _, pr in self.reds], [("demo", "a", 1)])
        self.assertEqual(self.box().get("merges", []), [])

    def test_a_check_red_on_main_too_is_blocked_by_main_not_blamed(self):
        self.main({"b/gate": "bad\n"})                               # main breaks check b
        self.pr(1, {"b/y": "a change b owns\n"})
        J.submit("demo", 1)
        u, lines = self.land()
        j = self.job()
        self.assertEqual((j.state, j.extra["hold"], j.extra["held_from"]), (T.HELD, "box", T.QUEUED), lines)
        self.assertIn("blocked-by-main:b", j.extra["why"])
        self.assertEqual(self.reds, [])                               # not the PR's red: no ledger record
        self.assertEqual(u["cards"].calls, [])                        # and nobody is told the PR broke it
        self.assertFalse(os.path.exists(J.handed_path("demo", 1)))
        self.assertEqual(self.box().get("merges", []), [])
        self.assertIn("gate=b ok=main-red", self.log())
        # main mended: after the hold the job is planned again from main and lands
        self.main({"b/gate": "fine\n"})
        j.extra["not_before"] = E.stamp(time.time() - 1)
        J.save(j)
        u, lines = self.land()
        self.assertEqual(self.job().state, T.DEPLOY_PENDING, lines)

    def test_a_limit_deferred_review_waits_for_the_reset(self):
        self.pr(1, {"c/w": "paid\n"})
        J.submit("demo", 1)
        before = time.time()
        u, lines = self.land()
        j = self.job()
        self.assertEqual((j.state, j.reads_used, j.extra["hold"]), (T.HELD, 0, "box"), lines)
        self.assertTrue(j.plan.paid)
        # not_before is the reset cc-limit named (120 min + 1), not the 15-minute hold
        self.assertGreater(E.epoch_of(j.extra["not_before"]), before + 110 * 60)
        d = J.read_json(J.job_path("demo", 1))
        self.assertEqual(d["stage"], "deferred")                      # the Home tab does not count it as running
        self.assertIn("usage limit", j.extra["why"])
        # a lane run before the reset leaves it alone: no read is asked for
        with mock.patch.object(RV, "_buy", side_effect=AssertionError("a read was asked for")):
            self.land()
        self.assertEqual(self.job().state, T.HELD)

    def test_ended_jobs_leave_the_readers_directory(self):
        self.pr(1, {"a/x": "n\n"}, state="CLOSED", headRefOid="e" * 40)
        J.submit("demo", 1)
        self.land()
        self.assertFalse(os.path.exists(J.job_path("demo", 1)))      # done: off <LANDQ>/*.json, as the old unlink
        self.assertEqual(self.job().state, T.DONE)                   # …but a re-queue still finds it
        self.assertTrue(os.path.exists(J.rest_path("demo", 1)))
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        self.assertTrue(os.path.exists(J.job_path("demo", 1)))
        self.assertFalse(os.path.exists(J.rest_path("demo", 1)))
        self.assertEqual(J.read_json(J.job_path("demo", 1))["stage"], "queued")


if __name__ == "__main__":
    unittest.main()
