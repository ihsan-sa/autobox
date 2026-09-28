"""U5: the lander's owner-visible cards and board rules match the old lander's.

Real subprocesses against stub tools: cc-slack, cc-notify, cc-board, cc-scope and tmux are small scripts in a temp
bin/ (cards.BIN points there and it leads PATH), each writing its argv, cwd and CC_ROLE to a log and answering from
an answers dir (`<tool> <sub>.rc` / `.out`). Nothing reaches the box. Run:
python3 -m unittest discover -s core/tests/lander -t core/tests/lander -p 'test_u5_cards.py'
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from lander import board as B  # noqa: E402
from lander import cards as C  # noqa: E402
from lander import lane as L  # noqa: E402
from lander import types as T  # noqa: E402

STUB = r"""#!/bin/sh
n=${0##*/}
{ printf '%s\037' "$n" "$@"; printf '\036%s\036%s\035' "$(pwd -P)" "${CC_ROLE-}"; } >> "$U5_STUB_LOG"
k="$n $1"
[ -f "$U5_STUB_ANSWERS/$k.rc" ] || k="$n"
[ -f "$U5_STUB_ANSWERS/$k.out" ] && cat "$U5_STUB_ANSWERS/$k.out"
[ -f "$U5_STUB_ANSWERS/$k.rc" ] && exit "$(cat "$U5_STUB_ANSWERS/$k.rc")"
exit 0
"""
TOOLS = ("cc-slack", "cc-notify", "cc-board", "cc-scope", "tmux")
Q = "2026-09-27T00:00:00Z"
HEAD = "b" * 40
DOOR_WHY = L.hold_words("demo", ("bin/x", "bin/**"))


class Stubbed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lander-u5-cards.")
        self.saved_env = dict(os.environ)
        self.saved_bin, self.saved_pr_head = C.BIN, L.pr_head
        bin_ = os.path.join(self.tmp, "bin")
        os.makedirs(bin_)
        for t in TOOLS:
            p = os.path.join(bin_, t)
            with open(p, "w") as f:
                f.write(STUB)
            os.chmod(p, 0o755)
        C.BIN = bin_
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.log, self.answers_path = os.path.join(self.tmp, "calls.log"), os.path.join(self.tmp, "answers")
        os.environ.update(PATH=bin_ + os.pathsep + os.environ.get("PATH", ""), HOME=self.home,
                          U5_STUB_LOG=self.log, U5_STUB_ANSWERS=self.answers_path,
                          CC_LAND_STATE=os.path.join(self.tmp, "land"), CC_BOARDS=os.path.join(self.tmp, "boards"),
                          CC_SLACK_DIR=os.path.join(self.tmp, "slack"), CC_CONFIG=os.path.join(self.tmp, "config"),
                          CC_LANDER_STATE=os.path.join(self.tmp, "land"), CC_ROLE="track")
        self.answer({})

    def tearDown(self):
        C.BIN, L.pr_head = self.saved_bin, self.saved_pr_head
        os.environ.clear()
        os.environ.update(self.saved_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def answer(self, a):
        """{"tool sub" or "tool": [rc, out]}, replacing every answer before."""
        shutil.rmtree(self.answers_path, ignore_errors=True)
        os.makedirs(self.answers_path)
        for k, (rc, out) in a.items():
            for ext, v in (("rc", str(rc)), ("out", out)):
                with open(os.path.join(self.answers_path, f"{k}.{ext}"), "w") as f:
                    f.write(v)

    def calls(self, key=None):
        rows = []
        try:
            with open(self.log, encoding="utf-8") as f:
                for ln in f.read().split("\x1d"):
                    if not ln:
                        continue
                    argv, cwd, role = ln.split("\x1e")
                    rows.append({"argv": argv.split("\x1f")[:-1], "cwd": cwd, "role": role or None})
        except OSError:
            return []
        return [r for r in rows if key is None or " ".join(r["argv"][:len(key.split())]) == key]

    def argvs(self, key):
        return [c["argv"] for c in self.calls(key)]

    def job(self, repo="demo", member=None, **extra):
        return T.Job(repo=repo, pr=7, member=member, extra={"queued_at": Q, **extra})


class Door(Stubbed):
    """Fix 1: the door's refusal and the lane's re-ask are the 🔐 card in #approvals, from ~ with no role."""

    def test_door_refusal_is_the_owner_card_with_the_head_in_its_id(self):
        L.pr_head = lambda *a, **k: HEAD
        C.stopped(T.Job(repo="demo", pr=7), DOOR_WHY, "door")
        pid = f"land:demo:7:protected-door@{HEAD}"
        text = (f"🔐 *Approval needed:* [demo] PR #7 is not queued — {DOOR_WHY}. Nothing merged, and your own 👍 on "
                f"this card is what queues it")
        self.assertEqual(self.argvs("cc-slack"), [["cc-slack", "post", "-c", "#approvals", "--mention", "--id", pid, text]])
        c = self.calls("cc-slack")[0]
        self.assertEqual((c["cwd"], c["role"]), (os.path.realpath(self.home), None))
        C.stopped(T.Job(repo="demo", pr=7), DOOR_WHY, "door")   # the same refusal again is one card
        self.assertEqual(len(self.calls("cc-slack")), 1)
        self.assertEqual(self.calls("cc-notify"), [])

    def test_door_with_no_head_known_still_posts_and_a_not_knowing_hit_posts_nothing(self):
        L.pr_head = lambda *a, **k: ""
        C.stopped(T.Job(repo="demo", pr=8), DOOR_WHY, "door")
        self.assertIn("land:demo:8:protected-door", self.argvs("cc-slack post")[0])
        C.stopped(T.Job(repo="demo", pr=9), L.hold_words("demo", ("?", "gh could not list the files")), "door")
        self.assertEqual(len(self.calls()), 1)

    def test_lane_reask_without_approval_says_the_stop_then_the_owner_card(self):
        why = f"{DOOR_WHY}, and no 👍 of the owner's queued it"
        C.stopped(self.job(chat="C1", ts="1.2"), why, "owner")
        pid = f"land:demo:7:protected@{Q}"
        text = (f"[demo] PR #7 is NOT landing — {why}. Nothing merged and the job is off the queue; the owner's own "
                f"👍 on the 🔐 card in #approvals queues this head")
        self.assertEqual(self.argvs("cc-slack"), [
            ["cc-slack", "post", "-c", "C1", "--thread", "1.2", "--id", pid, text],
            ["cc-slack", "post", "-c", "#approvals", "--mention", "--id", pid + ":owner", "🔐 *Approval needed:* " + text]])
        self.assertEqual(self.calls("cc-notify"), [])

    def test_lane_reask_at_a_moved_head_is_routed_and_carded(self):
        why = f"{DOOR_WHY}, at a head the owner has not 👍'd (aaaa → bbbb)"
        C.stopped(self.job(), why, "owner")
        text = (f"[demo] PR #7 moved to a head the owner has not 👍'd, under a protected path — 👍 the 🔐 card in "
                f"#approvals to land this head ({why})")
        pid = f"land:demo:7:protected@{Q}"
        self.assertEqual(self.argvs("cc-slack"), [
            ["cc-slack", "post", "--route", "[demo] PR #7 stopped", "--id", pid, text],
            ["cc-slack", "post", "-c", "#approvals", "--mention", "--id", pid + ":owner", "🔐 *Approval needed:* " + text]])

    def test_owner_stop_the_box_could_not_read_is_a_planner_request_not_a_card(self):
        C.stopped(self.job(), "gh could not list the files, and demo has PROTECTED paths", "owner")
        self.assertEqual(len(self.argvs("cc-slack post")), 1)
        ask = self.argvs("cc-notify")
        self.assertEqual(ask[0][:6], ["cc-notify", "--ask", "--id", f"land:demo:7:protected@{Q}:owner", "-t",
                                      "demo approval"])


class Routes(Stubbed):
    """Fix 2: every route the lane passes goes where the old lander sent it."""

    def test_member_stop_goes_to_its_channel_not_a_route_title(self):
        j = self.job(repo="h--t", member="h")
        C.stopped(j, "a check is red", "#h")
        pid = f"land:h--t:7:stopped@{Q}"
        self.assertEqual(self.argvs("cc-slack"), [
            ["cc-slack", "post", "-c", "#h", "--id", pid, "[h--t] PR #7: NOT merged ❌ — a check is red."]])

    def test_seat_stop_is_routed_and_injected_once(self):
        C.stopped(self.job(), "a check is red", "seat")
        C.stopped(self.job(), "a check is red", "seat")
        self.assertEqual(self.argvs("cc-slack post"), [
            ["cc-slack", "post", "--route", "[demo] PR #7 stopped", "--id", f"land:demo:7:stopped@{Q}",
             "[demo] PR #7: NOT merged ❌ — a check is red. The track's seat fixes it and pushes; the lane takes the "
             "new head."]])
        self.assertEqual(self.argvs("cc-slack inject"), [
            ["cc-slack", "inject", "demo", "[demo] PR #7 landing stopped: a check is red. The way back in: fix it and "
             "push; the lane takes the new head."]])

    def test_planning_and_lander_self_file_the_planner_request(self):
        for i, route in enumerate(("planning", "lander-self", "query")):
            j = T.Job(repo="demo", pr=10 + i, extra={"queued_at": Q})
            C.stopped(j, "the review budget for this change is spent", route)
            post = self.argvs("cc-slack post")[-1]
            self.assertEqual(post[:5], ["cc-slack", "post", "--route", f"[demo] PR #{10 + i} stopped", "--id"])
            ask = self.argvs("cc-notify")[-1]
            self.assertEqual(ask[:6], ["cc-notify", "--ask", "--id", f"land:demo:{10 + i}:query@{Q}", "-t",
                                       "demo landing"])
            self.assertEqual(ask[-1], post[-1])
            self.assertIsNone(self.calls("cc-notify")[-1]["role"])
        self.assertEqual(self.argvs("cc-slack inject"), [          # only "query" wakes the repo's session too
            ["cc-slack", "inject", "demo", "[demo] PR #12 landing stopped: the review budget for this change is spent. "
             "The way back in: fix it and push; the lane takes the new head."]])
        self.assertFalse([a for a in self.argvs("cc-slack") if "#approvals" in a])

    def test_a_queue_calls_own_route_title_is_kept(self):
        C.stopped(self.job(), "red", "[demo] my title")
        self.assertEqual(self.argvs("cc-slack post")[0][2:4], ["--route", "[demo] my title"])


class Board(Stubbed):
    """Fix 3: rows are found by the lane's `branch`, members keep their track, the old board rules hold."""

    def board(self, name, tracks):
        os.makedirs(os.environ["CC_BOARDS"], exist_ok=True)
        with open(os.path.join(os.environ["CC_BOARDS"], f"{name}.json"), "w") as f:
            json.dump({"tracks": tracks}, f)

    def test_row_found_by_branch_closes_and_marks_the_ledger(self):
        self.board("demo", {"row-a": {"status": "review"}, "row-b": {"branch": "feat/b"}})
        self.answer({"cc-scope list": [0, json.dumps([{"id": "s1"}])], "cc-board get": [1, ""]})
        j = self.job(branch="track/row-a", title="t")
        self.assertEqual(B.track_for(j), "row-a")
        self.assertEqual(B.track_for(self.job(branch="feat/b")), "row-b")
        self.assertEqual(B.track_for(self.job(head_ref="feat/b")), "row-b")
        line = B.close(j)
        self.assertIn(["cc-board", "status", "demo", "row-a", "merged"], self.argvs("cc-board status"))
        self.assertEqual(self.argvs("cc-scope merged"), [["cc-scope", "merged", "demo", "s1", "--evidence", "PR #7 t"]])
        self.assertIn("demo/row-a -> merged", line)

    def test_member_job_keeps_its_track_and_its_thread(self):
        self.board("h", {"t": {"status": "review"}})
        os.makedirs(os.environ["CC_SLACK_DIR"])
        with open(os.path.join(os.environ["CC_SLACK_DIR"], "track-threads.json"), "w") as f:
            json.dump({"h/t": {"ts": "1.1"}}, f)
        j = self.job(repo="h--t", member="h", branch="whatever")
        self.assertEqual((B.project_of(j), B.track_for(j)), ("h", "t"))
        self.assertEqual(C.track_thread(j), "h/t")
        B.close(j)
        self.assertIn(["cc-board", "status", "h", "t", "merged"], self.argvs("cc-board status"))

    def test_symlinked_board_is_refused(self):
        real = os.path.join(self.tmp, "elsewhere.json")
        with open(real, "w") as f:
            json.dump({"tracks": {"x": {"pr": "7"}}}, f)
        os.makedirs(os.environ["CC_BOARDS"])
        os.symlink(real, os.path.join(os.environ["CC_BOARDS"], "demo.json"))
        self.assertEqual(B.rows("demo"), {})

    def test_orch_mark_as_the_old_lander_read_it(self):
        self.board("h", {"t": {"agent": "@5"}})
        self.answer({"tmux": [0, "@5\th@lead\n"]})
        B.close(self.job(repo="h--t", member="h"))
        self.assertEqual(self.calls("cc-board status"), [])
        self.assertEqual(self.argvs("cc-board note"), [
            ["cc-board", "note", "h", "t", "milestone landed by the lander: PR #7; left open, h@lead holds this row"]])

    def test_closes_rules_and_agent_mark_clearing(self):
        self.board("demo", {"own": {"pr": "7"}, "free": {"status": "queued", "agent": "@1:2"},
                            "blank": {"status": "running", "agent": "  "}, "held": {"held": "me"},
                            "gone": {"status": "merged"}})
        B.close(self.job(body="Closes free, blank, held, gone and no-such-row"))
        self.assertEqual(self.argvs("cc-board status"), [["cc-board", "status", "demo", "own", "merged"],
                                                         ["cc-board", "status", "demo", "free", "done"]])
        self.assertEqual(self.argvs("cc-board set"), [["cc-board", "set", "demo", "free", "agent", ""]])

    def test_followup_row_name(self):
        self.answer({"cc-board get": [1, ""]})
        B.followup(self.job(repo="h--t", member="h"), T.Verdict(verdict=T.LAND, digest="d", advisory=["x"]))
        # recurring-defect-ok: pause-hold-missing — a unit test asserting a faked cc-board argv; the lane asks cc-pause
        self.assertEqual(self.argvs("cc-board add")[0][:5], ["cc-board", "add", "h", "review-followup-pr7",
                                                             "review follow-up for PR #7"])


class OwnerCard(Stubbed):
    """A card for a new unit cc-units keeps for the owner carries the command, so his 👍 runs it."""

    def test_run_goes_out_as_an_approval_card_from_the_box_hand(self):
        self.assertTrue(C.owner_card("land:demo:deploy:enable-x.service@abc", "[demo] x.service is new",
                                     run="systemctl --user enable --now x.service"))
        self.assertEqual(self.argvs("cc-notify"), [
            ["cc-notify", "--approval", "--run", "systemctl --user enable --now x.service", "--id",
             "land:demo:deploy:enable-x.service@abc", "-t", "lander approval", "[demo] x.service is new"]])
        self.assertIsNone(self.calls("cc-notify")[0]["role"])
        self.assertEqual(self.argvs("cc-slack post"), [])

    def test_without_run_it_stays_a_door_card(self):
        C.owner_card("land:demo:7:protected-door", "[demo] PR #7 is not queued")
        self.assertEqual(self.argvs("cc-notify"), [])
        self.assertEqual(self.argvs("cc-slack post")[0][2:4], ["-c", "#approvals"])


if __name__ == "__main__":
    unittest.main()
