"""OLD: the one unprompted push the box already makes about work in flight — the board watchdog's landing notice.

cc-reconcile tells the owner once when a finished row's PR has waited PENDING (4 hours) with nobody landing it. Seen
from the moment, that is: the box post before the nudge said the work was queued or waiting to land, and 4 hours
passed. The watchdog reads board rows, not posts, so this is an approximation, and its "old" column is the replay's
error bar: every nudge it claims to prevent happened anyway in history.

For cc-replay-moments: judge(moment) -> ("flagged", 14400) or "pass".
"""
import re

LANDING = re.compile(r"\b(queued to land|queued|waiting to land|waits to land)\b", re.I)
AFTER_S = 4 * 3600


def judge(m):
    if m.get("source") == "failure":
        return "pass"
    text = (m.get("prev_box") or {}).get("text") or ""
    return ("flagged", AFTER_S) if LANDING.search(text) else "pass"
