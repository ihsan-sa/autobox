"""lander tick's strays sweep: the box's own open PR that nothing queued gets queued, and nothing else does.

gh, `cc lands` and the queue itself are answered by fakes; the landing state, queue.log and the stamps are real files
under a temp dir. Run:
python3 -m unittest discover -s core/tests/lander -t core/tests/lander -p 'test_strays.py'
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from lander import events as E  # noqa: E402
from lander import gh as GH  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import lane as L  # noqa: E402
from lander import tick as TK  # noqa: E402
from lander import types as T  # noqa: E402


def pr(n, branch="fix-docs", age=3600, draft=False):
    return {"number": n, "headRefName": branch, "isDraft": draft, "createdAt": E.stamp(time.time() - age)}


class Strays(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lander-strays.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        land = os.path.join(self.tmp, "land")
        p = mock.patch.dict(os.environ, {"CC_LAND_STATE": land, "CC_LANDER_STATE": land, "HOME": self.tmp,
                                         "CC_DEV": os.path.join(self.tmp, "dev"),
                                         "CC_BOARDS": os.path.join(self.tmp, "boards"),
                                         "LANDER_STRAY_SECS": "900"})
        p.start()
        self.addCleanup(p.stop)
        for repo in ("demo", "other"):
            os.makedirs(os.path.join(self.tmp, "dev", repo, ".git"))
        self.open = {"demo": [], "other": []}   # what gh pr list answers, per repo
        self.lists, self.queued, self.lands = [], [], {"demo": True, "other": True}
        self.gh_rc = 0

        def gh(argv, root, token=None, timeout=120):
            repo = os.path.basename(root)
            self.lists.append(repo)
            return (self.gh_rc, "" if self.gh_rc else json.dumps(self.open[repo]), "boom" if self.gh_rc else "")

        def queue(argv):
            self.queued.append((argv[0], int(argv[1])))
            print(f"[{argv[0]}] PR #{argv[1]} queued")
            return 0
        for target, name, fake in ((GH, "slug", lambda root: "o/" + os.path.basename(root)), (GH, "gh", gh),
                                   (TK, "self_lands", lambda repo: self.lands[repo]), (L, "cmd_queue", queue)):
            p = mock.patch.object(target, name, fake)
            p.start()
            self.addCleanup(p.stop)

    def test_only_a_ready_stray_of_the_box_is_queued(self):
        self.open["demo"] = [pr(5), pr(6, draft=True), pr(7, branch="track/row"), pr(8, age=120),
                             pr(9, age=3 * 86400)]
        lines = TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 5)])   # kept: ready, not a track's, inside the window
        self.assertEqual(len(lines), 1)
        self.assertIn("PR #5 was open with no landing record — queued it", lines[0])

    def test_a_pr_the_lander_holds_or_ever_logged_is_left_alone(self):
        self.open["demo"] = [pr(5), pr(10), pr(11), pr(50)]
        E.log("refused", "demo", 5, "protected:x")       # seen once: a refusal is not undone by a sweep
        J.submit("demo", 10)                            # an inbox request already waits
        E.log("queued", "xdemo", 11)                    # another repo's line names no PR of this one
        E.log("queued", "demo", 500)                    # nor does a longer number
        TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 11), ("demo", 50)])

    def test_a_pr_with_only_a_job_a_rest_file_or_a_handed_watch_is_left_alone(self):
        self.open["demo"] = [pr(12), pr(13), pr(14), pr(50)]   # none of 12-14 has a queue.log line
        J.save(T.Job(repo="demo", pr=12, state=T.CHECKING))      # a live job
        for path in (J.rest_path("demo", 13), J.handed_path("demo", 14)):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("{}")                                    # exists, but J.load reads no job from it
        self.assertIsNone(J.load("demo", 13))
        TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 50)])

    def test_a_failed_queue_is_said(self):
        self.open["demo"] = [pr(5)]
        with mock.patch.object(L, "cmd_queue", lambda argv: (print("no room"), 1)[1]):
            lines = TK.sweep_strays(["demo"])
        self.assertEqual(lines, ["[demo] PR #5 was open with no landing record — queueing it failed: no room"])

    def test_a_member_repo_is_never_listed(self):
        os.makedirs(os.path.join(self.tmp, "dev", "h--t", ".git"))
        self.open["h--t"] = [pr(5)]
        TK.sweep_strays(["h--t"])
        self.assertEqual((self.lists, self.queued), ([], []))

    def test_a_repo_that_does_not_land_itself_is_not_queued(self):
        self.open["demo"] = [pr(5)]
        self.open["other"] = [pr(6)]
        self.lands["other"] = False
        TK.sweep_strays(["demo", "other"])
        self.assertEqual(self.queued, [("demo", 5)])
        self.assertEqual(self.lists, ["demo"])          # its PRs are never even listed

    def test_the_sweep_reads_github_once_per_window(self):
        self.open["demo"] = [pr(5)]
        TK.sweep_strays(["demo"])
        TK.sweep_strays(["demo"])
        self.assertEqual(self.lists, ["demo"])          # suppressed: the stamp is fresh
        os.utime(TK.C.state("tip", "demo.strays"), (time.time() - 901, time.time() - 901))
        TK.sweep_strays(["demo"])
        self.assertEqual(self.lists, ["demo", "demo"])  # kept: the window has passed

    def test_a_gh_failure_is_said_and_queues_nothing(self):
        self.open["demo"] = [pr(5)]
        self.gh_rc = 1
        lines = TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [])
        self.assertEqual(lines, ["[demo] strays: gh could not list the open PRs — boom"])
        self.gh_rc = 0
        os.unlink(TK.C.state("tip", "demo.strays"))
        TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 5)])    # kept: the next window's read queues it

    def test_a_repo_with_no_checkout_or_no_github_origin_is_skipped(self):
        self.open["demo"] = [pr(5)]
        with mock.patch.object(GH, "slug", lambda root: ""):
            TK.sweep_strays(["demo", "nowhere"])
        self.assertEqual((self.lists, self.queued), ([], []))
        TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 5)])


if __name__ == "__main__":
    unittest.main()
