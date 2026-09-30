"""NEW: a status push 45 minutes after a box post that left work in flight, when nothing followed it.

The proposed fix for the status-not-pushed class: a post that says work is started, running, queued or landing sets a
timer, and if the thread hears nothing more within 45 minutes the box pushes one status line there itself. A post that
hands the ball to the owner (a question, a decision, a card waiting on his 👍) sets no timer: the next move is his.

For cc-replay-moments: judge(moment) -> ("status", 2700) or "pass". The replay counts it only where the owner's
message came more than 45 minutes after the post, because an earlier nudge happened before the push could.
"""
import re

IN_FLIGHT = re.compile(r"\b(queued|started|starting|running|building|being built|in progress|dispatched|working on|"
                       r"gate run|landing|will land|underway|kicked off|next:|on it)\b", re.I)
HIS_MOVE = re.compile(r"❓|decision needed|waiting on your|your :\+1:|your 👍|\bshould i\b|\bdo you want\b", re.I)
AFTER_S = 45 * 60


def judge(m):
    if m.get("source") == "failure":
        return "pass"
    text = (m.get("prev_box") or {}).get("text") or ""
    if not IN_FLIGHT.search(text) or HIS_MOVE.search(text):
        return "pass"
    return ("status", AFTER_S)
