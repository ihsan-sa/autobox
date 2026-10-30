"""lander tick's strays sweep: the box's own open PR that nothing queued gets queued, and nothing else does; a draft
the lander holds a job for, and that waits on PRs which have all merged, is marked ready.

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

SELF_MERGE_HEADS = TK.self_merge_heads   # setUp fakes it for the sweep


def pr(n, branch="fix-docs", age=3600, draft=False, base="main", body=""):
    return {"number": n, "headRefName": branch, "baseRefName": base, "isDraft": draft,
            "createdAt": E.stamp(time.time() - age), "body": body}


class Fixture(unittest.TestCase):
    """Fakes for gh, `cc lands` and the queue; the landing state is real files under a temp dir."""
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
        self.states, self.readied, self.ready_rc = {}, [], 0   # a parent's state (its REST read); gh pr ready's calls
        self.views, self.queue_rc = 0, 0   # how many parent reads; what the queue answers
        self.heads, self.asked = {}, []   # the box's self-merge prefixes; any other GitHub read

        def gh(argv, root, token=None, timeout=120):
            repo = os.path.basename(root)
            if argv[:2] == ["api", "user"]:   # gh.viewer: the login the box's PRs are by
                return 0, "box\n", ""
            if argv[:2] == ["api", "--paginate"] and "/pulls?state=open" in argv[2]:   # gh.my_open_prs, over REST
                self.lists.append(repo)
                if self.gh_rc:
                    return self.gh_rc, json.dumps({"message": "Server Error"}), "boom"
                return 0, "".join(json.dumps(dict(p, login=p.get("login", "box"))) + "\n"
                                  for p in self.open[repo]), ""
            if argv[0] == "api" and argv[1].count("/") == 4:   # repos/<slug>/pulls/<n>: a parent, by gh.pr_facts
                self.views += 1
                st = self.states.get(int(argv[1].rsplit("/", 1)[1]))
                return ((0, json.dumps({"state": "closed" if st == "MERGED" else st.lower(),
                                        "merged_at": "2026-10-14T00:00:00Z" if st == "MERGED" else None}), "")
                        if st else (1, "", "no such PR"))
            if argv[:2] == ["pr", "ready"]:
                self.readied.append((repo, int(argv[2])))
                return (self.ready_rc, "", "denied" if self.ready_rc else "")
            if argv[0] == "api":
                self.asked.append((repo, argv[1]))
                return 1, "", "HTTP 502"
            self.lists.append(repo)
            return (self.gh_rc, "" if self.gh_rc else json.dumps(self.open[repo]), "boom" if self.gh_rc else "")

        def queue(argv):
            self.queued.append((argv[0], int(argv[1])))
            print(f"[{argv[0]}] PR #{argv[1]} " + ("refused: busy" if self.queue_rc else "queued"))
            return self.queue_rc

        for target, name, fake in ((GH, "slug", lambda root: "o/" + os.path.basename(root)), (GH, "gh", gh),
                                   (TK, "self_lands", lambda repo: self.lands[repo]), (L, "cmd_queue", queue),
                                   (TK, "self_merge_heads", lambda repo: self.heads.get(repo, []))):
            p = mock.patch.object(target, name, fake)
            p.start()
            self.addCleanup(p.stop)


class Strays(Fixture):
    def test_only_a_ready_stray_of_the_box_is_queued(self):
        self.open["demo"] = [pr(5), pr(6, draft=True), pr(7, branch="track/row"), pr(8, age=120),
                             pr(9, age=3 * 86400)]
        lines = TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 5)])   # kept: ready, not a track's, inside the window
        self.assertEqual(len(lines), 1)
        self.assertIn("PR #5 was open with no landing record — queued it", lines[0])

    def test_a_pr_of_another_login_is_not_the_box_s(self):
        # REST has no --author @me: the list is every open PR, kept only where its author is gh's own login
        self.open["demo"] = [pr(5), dict(pr(6), login="someone")]
        TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 5)])

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

    def test_a_declared_head_is_left_to_its_repo_whatever_its_base_or_files(self):
        self.heads["demo"] = ["hive/", "dispatch/"]
        self.open["demo"] = [pr(5, branch="dispatch/run-5"), pr(6), pr(7, branch="hive/a", base="release"),
                             pr(8, branch="dispatchx/b")]
        lines = TK.sweep_strays(["demo"])
        # a head on no declared prefix queues as before; the ones left say nothing and read no files
        self.assertEqual((self.queued, self.asked, len(lines)), ([("demo", 6), ("demo", 8)], [], 2))

    def test_a_repo_with_no_declared_heads_is_unchanged(self):
        self.heads["demo"] = ["dispatch/"]
        self.open["other"] = [pr(6, branch="dispatch/a")]
        TK.sweep_strays(["other"])
        self.assertEqual((self.queued, self.asked), ([("other", 6)], []))

    def test_a_silent_cc_config_queues_none_of_the_repo_s_strays(self):
        # 10-30: at a busy boot cc-config timed out, read as no prefix, and 16 of the Hive's own PRs were queued
        self.heads["other"] = None
        self.open["other"] = [pr(5, branch="hive/a"), pr(6)]
        self.open["demo"] = [pr(7)]
        lines = TK.sweep_strays(["other", "demo"])
        self.assertEqual(self.queued, [("demo", 7)])
        self.assertIn("[other] strays: cc-config did not say", lines[0])

    def test_self_merge_heads_reads_the_repo_key_on_the_box(self):
        answers = {"LANDER_SELF_MERGE_HEADS_dispatch": (0, "dispatch/ hive/\n", ""),
                   "LANDER_SELF_MERGE_HEADS_a_2Eb": (1, "", ""), "LANDER_SELF_MERGE_HEADS_a_2Db": (0, "hive/\n", ""),
                   "LANDER_SELF_MERGE_HEADS_a_5Fb": (1, "", ""), "LANDER_SELF_MERGE_HEADS_slow": (125, "", "timeout"),
                   "LANDER_SELF_MERGE_HEADS_deep": (0, "hive/runs/\n", "")}
        bad = ["dispatch", "dispatch/ d", "*/", "/", "../", "dispatch/ -x/", "a//", "track/", "hive/ track/x/"]
        answers.update({f"LANDER_SELF_MERGE_HEADS_bad{i}": (0, v, "") for i, v in enumerate(bad)})
        TK.HEADS.clear()
        self.addCleanup(TK.HEADS.clear)
        with mock.patch.object(L, "run", lambda argv, timeout=60: answers[argv[2]]):
            self.assertEqual(SELF_MERGE_HEADS("dispatch"), ["dispatch/", "hive/"])
            self.assertEqual(SELF_MERGE_HEADS("deep"), ["hive/runs/"])
            self.assertEqual(SELF_MERGE_HEADS("a.b"), [])     # unset
            self.assertEqual(SELF_MERGE_HEADS("a-b"), ["hive/"])   # a key of its own, not a.b's or a_b's
            self.assertEqual(SELF_MERGE_HEADS("a_b"), [])
            self.assertIsNone(SELF_MERGE_HEADS("slow"))       # cc-config did not answer: no reading at all
            for i, v in enumerate(bad):                       # one word that is no namespace voids the whole setting
                self.assertEqual(SELF_MERGE_HEADS(f"bad{i}"), [], v)
        with mock.patch.object(L, "run", lambda argv, timeout=60: (0, "x/\n", "")):
            self.assertIsNone(SELF_MERGE_HEADS("slow"))       # asked once per tick, a silent answer too



class Drafts(Fixture):
    """A draft the lander holds a job for, whose body says "Waits on #N", is marked ready once every PR it names has
    merged; nothing else about a draft moves it."""
    def held(self, *prs):
        for n in prs:
            # the lane held it as a draft, in its own words; it re-reads it itself
            J.save(T.Job(repo="demo", pr=n, state=T.HELD, extra={"hold": "pr", "why": L.draft_why(n)}))

    def test_a_held_draft_is_marked_ready_once_its_parents_merge(self):
        self.open["demo"] = [pr(20, branch="track/half", age=5 * 86400, draft=True,
                                body="Lander half of #17.\n\nWaits on #17 and #18\n")]
        self.states = {17: "MERGED", 18: "MERGED"}
        self.held(20)
        lines = TK.sweep_strays(["demo"])
        self.assertEqual((self.readied, self.queued), ([("demo", 20)], []))
        self.assertEqual(lines, ["[demo] PR #20: #17, #18 merged — marked ready; its held job reads it again at "
                                 "its wake"])

    def test_a_draft_with_no_job_stays_a_draft_whatever_its_body_says(self):
        # someone else's edits may come as @me drafts with their text in the body, so a planted "Waits on" line must
        # not un-draft one; an ended job in rest/ (a handback a person owes) or a queue.log line is not a hold either
        self.open["demo"] = [pr(21, draft=True, body="lessons/x.md\nWaits on #17\n"),
                             pr(22, draft=True, body="Waits on #17")]
        self.states = {17: "MERGED"}
        J.save(T.Job(repo="demo", pr=22, state=T.HANDBACK))   # save files an ended job in rest/, as the lane does
        self.assertTrue(os.path.exists(J.rest_path("demo", 22)))
        self.assertIsNone(J.load_path(J.job_path("demo", 22)))
        E.log("refused", "demo", 21, "protected:x")
        self.assertEqual(TK.sweep_strays(["demo"]), [])
        self.assertEqual((self.readied, self.queued), ([], []))
        self.assertEqual(self.lists, ["demo"])   # and no gh call beyond the list: the parent is not even read

    def test_a_live_job_that_is_not_held_leaves_it_a_draft(self):
        self.open["demo"] = [pr(25, draft=True, body="Waits on #17")]
        self.states = {17: "MERGED"}
        J.save(T.Job(repo="demo", pr=25, state=T.CHECKING))
        self.assertEqual(TK.sweep_strays(["demo"]), [])
        self.assertEqual((self.readied, self.queued), ([], []))

    def test_a_job_held_for_anything_but_the_draft_stays_a_draft(self):
        # held for a conflict, then turned back into a draft by a person, with an old "Waits on" line in its body:
        # its parent merging does not undo their choice
        self.open["demo"] = [pr(26, draft=True, body="Waits on #17")]
        self.states = {17: "MERGED"}
        J.save(T.Job(repo="demo", pr=26, state=T.HELD,
                     extra={"hold": "pr", "why": "PR #26 conflicts with main in a.py — rebase it"}))
        self.assertEqual(TK.sweep_strays(["demo"]), [])
        self.assertEqual((self.readied, self.queued, self.views), ([], [], 0))
        self.assertTrue(L.DRAFT.match(L.draft_why(26)))   # while the lane's own draft hold is the one it acts on

    def requeued_draft(self, n, kind=None, why=""):
        """A job held with `kind` and `why` (none: never held) that the lane's unhold() sends back, read again by
        queued() once its PR is a draft; the job as it was saved."""
        lane, extra = L.Lane("demo", {}), {"held_from": T.QUEUED, "hold": kind, "why": why} if kind else {}
        job = T.Job(repo="demo", pr=n, state=T.HELD if kind else T.QUEUED, extra=extra)
        J.save(job)
        if kind:
            lane.unhold(job)
        with mock.patch.object(GH, "pr_facts", lambda *a, **k: ({"state": "OPEN", "isDraft": True}, "")):
            lane.queued(job)
        return J.load("demo", n)

    def test_a_draft_after_another_hold_keeps_out_of_the_draft_hold(self):
        job = self.requeued_draft(26, "pr", "PR #26 conflicts with main — rebase it")
        self.assertEqual(job.state, T.HELD)
        self.assertFalse(L.DRAFT.match(job.extra["why"]))
        self.open["demo"] = [pr(26, draft=True, body="Waits on #17")]
        self.states = {17: "MERGED"}
        TK.sweep_strays(["demo"])
        self.assertEqual(self.readied, [])

    def test_a_draft_after_a_box_hold_or_none_gets_the_draft_hold(self):
        for n, held in ((27, ()), (28, ("box", "gh could not read PR #28: boom"))):
            self.assertEqual(self.requeued_draft(n, *held).extra["why"], L.draft_why(n))

    def test_two_drafts_on_one_parent_read_it_once(self):
        self.open["demo"] = [pr(33, draft=True, body="Waits on #17"), pr(34, draft=True, body="Waits on #17")]
        self.states = {17: "MERGED"}
        self.held(33, 34)
        TK.sweep_strays(["demo"])
        self.assertEqual((self.readied, self.views), ([("demo", 33), ("demo", 34)], 1))

    def test_a_draft_stays_while_a_parent_is_open(self):
        self.open["demo"] = [pr(21, draft=True, body="- Waits on: #17, #19")]
        self.states = {17: "MERGED", 19: "OPEN"}
        self.held(21)
        self.assertEqual(TK.sweep_strays(["demo"]), [])
        self.assertEqual((self.readied, self.queued), ([], []))

    def test_a_draft_without_the_line_is_left_alone(self):
        self.open["demo"] = [pr(22, draft=True, body="when #17 merges, this un-drafts\nsee o/r#17")]
        self.states = {17: "MERGED"}
        self.held(22)
        self.assertEqual(TK.sweep_strays(["demo"]), [])
        self.assertEqual((self.readied, self.queued), ([], []))

    def test_a_parent_closed_unmerged_is_said_and_the_draft_kept(self):
        self.open["demo"] = [pr(23, draft=True, body="Waits on #17\nWaits on #18")]
        self.states = {17: "MERGED", 18: "CLOSED"}
        self.held(23)
        lines = TK.sweep_strays(["demo"])
        self.assertEqual(lines, ["[demo] draft PR #23 waits on #18, closed unmerged — it stays a draft for a person"])
        self.assertEqual((self.readied, self.queued), ([], []))

    def test_an_unreadable_parent_is_said_and_nothing_moves(self):
        self.open["demo"] = [pr(24, draft=True, body="Waits on #99")]
        self.held(24)
        lines = TK.sweep_strays(["demo"])
        self.assertEqual(lines, ["[demo] draft PR #24: gh could not say whether #99 merged — no such PR"])
        self.assertEqual((self.readied, self.queued), ([], []))

    def test_a_failed_ready_is_said(self):
        self.open["demo"] = [pr(27, draft=True, body="Waits on #17")]
        self.states = {17: "MERGED"}
        self.held(27)
        self.ready_rc = 1
        lines = TK.sweep_strays(["demo"])
        self.assertEqual(lines, ["[demo] draft PR #27: #17 merged, but marking it ready failed — denied"])
        self.assertEqual(self.queued, [])

    def test_the_drafts_gh_calls_are_capped_and_the_strays_still_handled(self):
        # three held drafts, each a parent read and a ready (6 calls) against a cap of 3; a ready stray after them
        # whose queueing fails is still queued and said
        self.open["demo"] = [pr(30, draft=True, body="Waits on #40"), pr(31, draft=True, body="Waits on #41"),
                             pr(32, draft=True, body="Waits on #42"), pr(5)]
        self.states = {40: "MERGED", 41: "MERGED", 42: "MERGED"}
        self.held(30, 31, 32)
        self.queue_rc = 1
        with mock.patch.dict(os.environ, {"LANDER_UNDRAFT_GH": "3"}):
            lines = TK.sweep_strays(["demo"])
        self.assertEqual(self.views + len(self.readied), 3)
        self.assertEqual(self.readied, [("demo", 30)])
        self.assertEqual(self.queued, [("demo", 5)])
        self.assertIn("[demo] PR #5 was open with no landing record — queueing it failed", lines[-1])

    def test_waits_on_reads_only_the_list_after_the_words(self):
        self.assertEqual(TK.waits_on({"number": 28, "body": "Waits on #28, #17 and #17"}), [17])
        self.assertEqual(TK.waits_on({"number": 29, "body": "Waits on #17; supersedes #18\nsupersedes #19"}), [17])
        self.assertEqual(TK.waits_on({"number": 29, "body": "Waits on #17, supersedes #18"}), [17])


if __name__ == "__main__":
    unittest.main()
