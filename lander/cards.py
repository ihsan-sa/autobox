"""What the lander tells people, and the few box calls the U3 modules share.

A CARD is one message about one job. `landed(job)` turns the PR's #approvals card to landed and says the merge where
someone is listening; `stopped(job, why, route)` says a job left the lane and who picks it up. Where it goes (where()):

    chat      the Slack thread the landing was asked from (job extra `chat`, `ts`)
    track     the track's own thread (cc-slack track-thread made one), when no chat asked
    member    `#<h>-updates` for a member's landing, `#<h>` for its stop; the owner's channels never hear of it
    route     `--route <title>` last: the job's own `route` if the queue call carried one, else `[<repo>] PR #<n> …`

A clean landing with none of the first three says nothing beyond the #approvals card. stopped()'s route "seat" also
puts the stop into the repo's session with `cc-slack inject`, once; "query" also files a planner request
(`cc-notify --ask`) for the planning seat, never a page to the owner. owner_card() is the 🔐 card, and only
deploy calls it, for what cc-units policy keeps for the owner.

DEDUPE BY PRODUCER ID. Every card carries `--id land:<repo>:<pr>:<kind>@<queued_at>` (the old lander's shape, so a
card either sent goes once). An id in `cards/sent.json` is not sent again. A card Slack refuses is kept in
`cards/pending.json` and every later say() retries it, up to SAY_TRIES tries in all; after that the queue.log line
is all it gets, and the log says so.

SHARED HELPERS. `sh`, `state()`, `conf()` and `log()` are here because every U3 module talks to the box through
them, and the tests swap exactly these.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import time

from lander import types as T

SAY_TRIES = 6
BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin")


# --- shared helpers ------------------------------------------------------------------------------------------------

def sh(argv, cwd=None, input=None, timeout=300, env=None):
    """Run argv; -> (rc, stdout+stderr). A missing tool, an argv too long or a timeout is rc 127 / 124 with the reason, never a raise."""
    try:
        p = subprocess.run(argv, cwd=cwd, input=input, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except OSError as e:   # a missing tool, or an argv the kernel refuses (E2BIG)
        return 127, f"{type(e).__name__}: {e}"
    except subprocess.TimeoutExpired:
        return 124, f"{argv[0]}: timed out after {timeout}s"


def state(*parts):
    """A path under the landing state dir (~/.cc/state/land, or $CC_LAND_STATE for tests)."""
    root = os.environ.get("CC_LAND_STATE") or os.path.expanduser("~/.cc/state/land")
    return os.path.join(root, *parts)


def conf(key, default=""):
    """A box setting: the environment first, then ~/.cc/config (KEY=value lines), then the default."""
    if key in os.environ:
        return os.environ[key]
    path = os.environ.get("CC_CONFIG") or os.path.expanduser("~/.cc/config")
    try:
        with open(path) as f:
            for ln in f:
                k, _, v = ln.strip().partition("=")
                if k == key or k == f"export {key}":
                    return v.strip().strip("'\"")
    except OSError:
        pass
    return default


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(kind, repo, pr, **kv):
    """One queue.log line through U1's events module when it is there; the same line shape written here when not."""
    try:
        from lander import events  # type: ignore[attr-defined]
        return events.log(kind, repo, pr, **kv)
    except ImportError:
        pass
    tail = " ".join(f"{k}={v}" for k, v in kv.items())
    os.makedirs(state(), exist_ok=True)
    with open(state("queue.log"), "a") as f:
        f.write(f"{now()}\t{kind} {repo}#{pr}{' ' + tail if tail else ''}\n")


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """Atomic: a reader sees the old file or the new one, never half of one."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


# --- cards ---------------------------------------------------------------------------------------------------------

STOP_CARD_MAX = 200
TEST_STATE = re.compile(r"(?:^|[^A-Za-z0-9])_(?:cctest|selfcheck)")


def slack():
    return os.path.join(BIN, "cc-slack")


def producer_id(job, kind):
    """`land:<repo>:<pr>:<kind>@<queued_at>` — the old lander's shape, so a card either one sent is sent once."""
    at = job.extra.get("queued_at", "")
    return f"land:{job.repo}:{job.pr}:{kind}" + (f"@{at}" if at else "")


def track_thread(job):
    """`<repo or handle>/<track>` when that track has a thread (cc-slack track-thread made one), else ""."""
    from lander import board
    track = board.track_for(job)
    if not track:
        return ""
    tt = read_json(os.path.join(os.path.expanduser(conf("CC_SLACK_DIR", "~/.cc/slack")), "track-threads.json"), {})
    target = f"{job.member or job.repo}/{track}"
    return target if isinstance((tt or {}).get(target), dict) and tt[target].get("ts") else ""


def where(job, ok, restart=False):
    """The post's arguments, or None when the #approvals card is all a clean landing gets. Precedence: the chat the
    landing was asked from, the track's thread, `#<h>` for a member, and the --route line last."""
    kind = "landed" if ok else "stopped"
    if job.extra.get("chat"):
        return ["-c", job.extra["chat"]] + (["--thread", job.extra["ts"]] if job.extra.get("ts") else [])
    tt = "" if restart else track_thread(job)
    if tt:
        return ["--route", f"{tt} {kind}"]
    if job.member:
        return ["-c", f"#{job.member}-updates" if ok else f"#{job.member}"]
    if ok and not restart:
        return None
    return ["--route", job.extra.get("route") or f"[{job.repo}] PR #{job.pr} {kind}"] + (["--mention"] if restart else [])


def _sent_path():
    return state("cards", "sent.json")


def _pending_path():
    return state("cards", "pending.json")


def _post(argv, pid):
    rc, out = sh(argv, timeout=180)
    return rc == 0 or "no SLACK_BOT_TOKEN" in out, out


def say(pid, argv, repo, pr):
    """Send one card once. A refusal is kept in pending and retried by the next say() up to SAY_TRIES."""
    retry()
    sent = read_json(_sent_path(), []) or []
    if pid in sent:
        return True
    ok, out = _post(argv, pid)
    if ok:
        write_json(_sent_path(), (sent + [pid])[-500:])
        return True
    pending = read_json(_pending_path(), {}) or {}
    pending[pid] = {"argv": argv, "tries": 1, "repo": repo, "pr": pr}
    write_json(_pending_path(), pending)
    log("unsaid", repo, pr, id=pid, tries=f"1/{SAY_TRIES}", why=out.strip()[-120:].replace("\n", " "))
    return False


def retry():
    pending = read_json(_pending_path(), {}) or {}
    if not pending:
        return
    sent = read_json(_sent_path(), []) or []
    for pid, p in list(pending.items()):
        ok, out = _post(p["argv"], pid)
        if ok:
            sent.append(pid)
            del pending[pid]
        elif p["tries"] + 1 >= SAY_TRIES:
            log("unsaid", p.get("repo", "-"), p.get("pr", 0), id=pid, gave_up="yes",
                why="Slack never took it; this line is all it gets")
            del pending[pid]
        else:
            p["tries"] += 1
    write_json(_sent_path(), sent[-500:])
    write_json(_pending_path(), pending)


def post(job, kind, text, args):
    pid = producer_id(job, kind)
    return say(pid, [slack(), "post", *args, "--id", pid, text], job.repo, job.pr)


def landed(job):
    """The #approvals card reads landed, and the one line a thread hears. A restart the owner keeps goes with it."""
    rc, out = sh([slack(), "post-approval", "--landed", job.repo, str(job.pr)], timeout=120)
    if rc not in (0, 3, 4):
        log("card", job.repo, job.pr, pending="yes", why=out.strip()[-120:].replace("\n", " "))
    asks = job.extra.get("owner_asks") or []
    text = f"[{job.repo}] PR #{job.pr} merged ✅" + (f" — {job.extra['title']}" if job.extra.get("title") else "")
    if job.member:
        text += "."
    else:
        text += ". The tip check runs on main next, and the box deploys it once that is green."
    if asks:
        text += f" ⚠️ Please restart {', '.join(asks)}. Until then the box runs the old code for {'it' if len(asks) == 1 else 'them'}."
    args = where(job, True, restart=bool(asks))
    return post(job, "landed", text, args) if args else rc in (0, 3, 4)


def stopped(job, why, route):
    """`route` says who picks it up: "seat" (the row's own seat fixes it and pushes), "query" (the planning seat
    decides; a planner request, never the owner), or a --route target of the queue call's own."""
    why = " ".join(str(why).split()) or "it stopped without saying why"
    short = why if len(why) <= STOP_CARD_MAX else why[:STOP_CARD_MAX - 1] + "…"
    who = {"seat": "The track's seat fixes it and pushes; the lane takes the new head",
           "query": "The planning seat decides what happens to it"}.get(route, "")
    url = job.extra.get("url", "")
    text = f"[{job.repo}] PR #{job.pr}: NOT merged ❌ — {short}." + (f" {who}." if who else "") + (f" {url}" if url else "")
    args = where(job, False)
    if route not in ("seat", "query") and not job.extra.get("chat"):
        args = ["--route", route]
    said = post(job, "stopped", text, args)
    if route == "query":
        sh([os.path.join(BIN, "cc-notify"), "--ask", "--id", producer_id(job, "query"), "-t", f"{job.repo} landing",
            text], timeout=60)
    if not job.member and route == "seat":
        sent = read_json(_sent_path(), []) or []
        pid = producer_id(job, "inject")
        if pid not in sent:
            sh([slack(), "inject", job.repo, f"PR #{job.pr} landing stopped: {short}. The way back in: fix it and "
                f"push; the lane takes the new head."], timeout=120)
            write_json(_sent_path(), (sent + [pid])[-500:])
    return said


def owner_card(pid, text):
    """The 🔐 card in #approvals. Only for what policy keeps for the owner (a unit enable cc-units says is his)."""
    if TEST_STATE.search(text):
        log("unsaid", "-", 0, id=pid, why="synthetic test state, no 🔐 card posted")
        return False
    return say(pid, [slack(), "post", "-c", "#approvals", "--mention", "--id", pid, f"🔐 *Approval needed:* {text}"],
               "-", 0)
