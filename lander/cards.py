"""What the lander tells people, and the few box calls the U3 modules share.

A CARD is one message about one job. `landed(job)` turns the PR's #approvals card to landed and says the merge where
someone is listening; `stopped(job, why, route)` says a job left the lane and who picks it up. Where it goes (where()):

    chat      the Slack thread the landing was asked from (job extra `chat`, `ts`)
    member    `#<h>-updates` for a member's landing, `#<h>` for its stop; the owner's channels never hear of it
    landed    a board row's landing: ONE line on #<repo> itself (`--route "[<repo>] PR #<n> landed" --major`); a
              PR no row owns gets only the #approvals card
    track     a stop: the track's own thread (cc-slack track-thread made one), when no chat asked
    route     `--route <title>` last: the job's own `route` if the queue call carried one, else `[<repo>] PR #<n> …`

stopped()'s route "seat" and "query" put the stop into the repo's session with `cc-slack inject`, once; "query", "planning" and "lander-self" file
a planner request (`cc-notify --ask`) for the planning seat, never a page to the owner. owner_card() is the 🔐 card
in #approvals, the one cc-slack turns the owner's 👍 into a queue from: the protected door's refusal ("door"), a
protected head stopped in the lane ("owner"), and what cc-units policy keeps for the owner at deploy.

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
import pwd
import re
import subprocess
import time

from lander import types as T

SAY_TRIES = 6
BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin")


# --- shared helpers ------------------------------------------------------------------------------------------------

def sh(argv, cwd=None, input=None, timeout=300, env=None):
    """Run argv; -> (rc, stdout+stderr). A missing tool, an argv too long or a timeout is rc 127 / 124 with the reason, never a raise.
    The output is decoded as it is, with no newline translation: text=True turns a lone \r into \n, and a \r in a
    changed line then forges a `diff --git` header in the diff the review reads."""
    try:
        p = subprocess.run(argv, cwd=cwd, input=input.encode() if isinstance(input, str) else input,
                           capture_output=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or b"").decode(errors="replace") + (p.stderr or b"").decode(errors="replace")
    except OSError as e:   # a missing tool, or an argv the kernel refuses (E2BIG)
        return 127, f"{type(e).__name__}: {e}"
    except subprocess.TimeoutExpired:
        return 124, f"{argv[0]}: timed out after {timeout}s"


def state(*parts):
    """A path under the landing state dir (~/.cc/state/land, or $CC_LAND_STATE for tests)."""
    root = os.environ.get("CC_LAND_STATE") or os.path.expanduser("~/.cc/state/land")
    return os.path.join(root, *parts)


def _passwd_home():
    try:
        return pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:   # no passwd entry: no config and no default claude, never one a caller's HOME names
        return "/nonexistent"


# WHO REVIEWS A LANDING IS THE CONFIG FILE'S, NOT THE CALLER'S (security read of #849). The keys that pick the
# review's model, budget, effort, reviewers and binary are read from the config at the passwd home and nowhere else:
# not the environment, not HOME, not CC_CONFIG, so `CC_CLAUDE=<a fake that writes LAND> lander tick` from a worker's
# script chooses nothing. Tests patch REVIEWER_CONFIG (and PASSWD_HOME); no env var moves either.
PASSWD_HOME = _passwd_home()
REVIEWER_CONFIG = os.path.join(PASSWD_HOME, ".cc", "config")


def reviewer_key(key):
    return key.startswith("CC_LAND_REVIEW") or key in ("CC_CLAUDE", "CC_CODEX")


def conf(key, default=""):
    """A box setting: the environment first, then ~/.cc/config (KEY=value lines), then the default. A reviewer_key
    comes from REVIEWER_CONFIG only."""
    if reviewer_key(key):
        path = REVIEWER_CONFIG
    elif key in os.environ:
        return os.environ[key]
    else:
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
    """The post's arguments. Precedence: the chat the landing was asked from, `#<h>` for a member, and then a landing
    goes to #<repo> itself while a stop goes to the track's thread, else its --route line. The owner wants a landing
    "pushed once, at the moment it happens" (comms audit, 2026-09-28): a track's thread now sits in the -updates
    lane he does not read, so a board row's landing is said on the main lane (--major), and nowhere else. A PR no row
    owns (a seat's own fix) still gets only the #approvals card: its seat is the one who tells him."""
    kind = "landed" if ok else "stopped"
    if job.extra.get("chat"):
        return ["-c", job.extra["chat"]] + (["--thread", job.extra["ts"]] if job.extra.get("ts") else [])
    if job.member:
        return ["-c", f"#{job.member}-updates" if ok else f"#{job.member}"]
    if ok and not restart:
        from lander import board
        return ["--route", f"[{job.repo}] PR #{job.pr} landed", "--major"] if board.track_for(job) else None
    tt = "" if restart else track_thread(job)
    if tt:
        return ["--route", f"{tt} {kind}"]
    return ["--route", job.extra.get("route") or f"[{job.repo}] PR #{job.pr} {kind}"] + (["--mention"] if restart else [])


def _sent_path():
    return state("cards", "sent.json")


def _pending_path():
    return state("cards", "pending.json")


def _post(argv, pid, hand=False):
    rc, out = sh(argv, timeout=180, **(box_hand() if hand else {}))
    return rc == 0 or "no SLACK_BOT_TOKEN" in out, out


def say(pid, argv, repo, pr, hand=False):
    """Send one card once. A refusal is kept in pending and retried by the next say() up to SAY_TRIES. `hand`: send it
    from box_hand() (the 🔐 card), and so does its retry."""
    retry()
    sent = read_json(_sent_path(), []) or []
    if pid in sent:
        return True
    ok, out = _post(argv, pid, hand)
    if ok:
        write_json(_sent_path(), (sent + [pid])[-500:])
        return True
    pending = read_json(_pending_path(), {}) or {}
    pending[pid] = {"argv": argv, "tries": 1, "repo": repo, "pr": pr, "hand": bool(hand)}
    write_json(_pending_path(), pending)
    log("unsaid", repo, pr, id=pid, tries=f"1/{SAY_TRIES}", why=out.strip()[-120:].replace("\n", " "))
    return False


def retry():
    pending = read_json(_pending_path(), {}) or {}
    if not pending:
        return
    sent = read_json(_sent_path(), []) or []
    for pid, p in list(pending.items()):
        ok, out = _post(p["argv"], pid, bool(p.get("hand")))
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
    """The #approvals card reads landed, and the one line the landing gets (where()). A restart the owner keeps goes with it."""
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


QUERY_ROUTES = ("query", "planning", "lander-self")
PROTECTED_RE = re.compile(r"\(CC_PROTECTED_PATHS_[^)]*\)")


def stopped(job, why, route):
    """`route` says who picks it up, in the lane's words:

        seat         the row's own seat fixes it and pushes; the stop also goes into the repo's session (inject, once)
        #<h>         a member's landing: its own `#<h>` (where() already says so); a member is never injected
        query, planning, lander-self
                     the planning seat decides: the stop is said where a stop is said and a planner request
                     (`cc-notify --ask`) is filed, never a page to the owner; only "query" also wakes the repo's
                     session, because "planning" and "lander-self" are the planning seat's own, and an inject on top of
                     the request would wake it twice
        owner        a protected head the owner has not 👍'd, found in the lane: said once in the thread or routed,
                     then the 🔐 card (say_protected_stop)
        door         the queue call's own refusal at the protected door: only the 🔐 card (say_protected_door)

    Anything else is the queue call's own --route title, as before."""
    why = " ".join(str(why).split()) or "it stopped without saying why"
    if route == "door":
        return protected_door(job, why)
    if route == "owner":
        return protected_stop(job, why)
    short = why if len(why) <= STOP_CARD_MAX else why[:STOP_CARD_MAX - 1] + "…"
    who = {"seat": "The track's seat fixes it and pushes; the lane takes the new head",
           "query": "The planning seat decides what happens to it",
           "planning": "The planning seat decides what happens to it",
           "lander-self": "It changes the lander itself, so the planning seat lands it by hand"}.get(route, "")
    url = job.extra.get("url", "")
    text = f"[{job.repo}] PR #{job.pr}: NOT merged ❌ — {short}." + (f" {who}." if who else "") + (f" {url}" if url else "")
    args = where(job, False)
    known = route in ("seat",) + QUERY_ROUTES or route.startswith("#")
    if not known and not job.extra.get("chat"):
        args = ["--route", route]
    said = post(job, "stopped", text, args)
    if route in QUERY_ROUTES:
        sh([os.path.join(BIN, "cc-notify"), "--ask", "--id", producer_id(job, "query"), "-t", f"{job.repo} landing",
            text], timeout=60, **box_hand())
    if not job.member and route in ("seat", "query"):
        sent = read_json(_sent_path(), []) or []
        pid = producer_id(job, "inject")
        if pid not in sent:
            sh([slack(), "inject", job.repo, f"[{job.repo}] PR #{job.pr} landing stopped: {short}. The way back in: "
                f"fix it and push; the lane takes the new head."], timeout=120)
            write_json(_sent_path(), (sent + [pid])[-500:])
    return said


def box_hand():
    """The cwd and env a card to the owner is raised from: ~ and no role. cc-notify and cc-slack read who is asking
    from the caller (CC_ROLE, CC_MEMBER_SANDBOX, a .cc/track marker above the cwd), and a lane started from a track's
    worktree must not make the 🔐 card a track's request."""
    return {"cwd": os.path.expanduser("~"),
            "env": {k: v for k, v in os.environ.items() if k not in ("CC_ROLE", "CC_MEMBER_SANDBOX")}}


def _door_head(job):
    """The PR's head for the door card's id; the queue call refuses before a job has one, so ask gh. "" on doubt."""
    if job.head:
        return job.head
    try:
        from lander import jobs as J
        from lander import lane as L
        from lander import members as M
        genv = M.env(job.member) if job.member else None
        return L.pr_head(J.repo_root(job.repo), job.pr, (genv or {}).get("GH_TOKEN"), genv) or ""
    except Exception:   # noqa: BLE001 — the card goes without a head in its id rather than not at all
        return ""


def protected_door(job, why):
    """The 🔐 card the door's own refusal leaves, worded as cc-slack reads an authorization card ("[<repo>] PR #<n>
    …", APPROVAL_RE), so the owner's 👍 on it queues the head. The id carries the head: the same refusal is one card
    and a new head a new question. A hit the box could not read (no named file) is not his to answer: no card."""
    if not PROTECTED_RE.search(why):
        log("unsaid", job.repo, job.pr, why="protected door not-knowing, no 🔐 card")
        return False
    head = _door_head(job)
    pid = f"land:{job.repo}:{job.pr}:protected-door" + (f"@{head}" if head else "")
    return owner_card(pid, f"[{job.repo}] PR #{job.pr} is not queued — {why}. Nothing merged, and your own 👍 on "
                           f"this card is what queues it")


def protected_stop(job, why):
    """A protected head stopped in the lane: said once in the job's thread (else routed as a stop), then the 🔐 card
    for a named file, or a planner request when the box could not read which file it was."""
    if "has not 👍'd" in why:
        text = (f"[{job.repo}] PR #{job.pr} moved to a head the owner has not 👍'd, under a protected path — 👍 the "
                f"🔐 card in #approvals to land this head ({why})")
    else:
        text = (f"[{job.repo}] PR #{job.pr} is NOT landing — {why}. Nothing merged and the job is off the queue; "
                f"the owner's own 👍 on the 🔐 card in #approvals queues this head")
    pid = producer_id(job, "protected")
    chat, ts = job.extra.get("chat") or "", job.extra.get("ts") or ""
    args = ["-c", chat, *(["--thread", ts] if ts else [])] if chat else ["--route", f"[{job.repo}] PR #{job.pr} stopped"]
    said = say(pid, [slack(), "post", *args, "--id", pid, text], job.repo, job.pr)
    if PROTECTED_RE.search(why):
        owner_card(f"{pid}:owner", text)
    else:
        sh([os.path.join(BIN, "cc-notify"), "--ask", "--id", f"{pid}:owner", "-t", f"{job.repo} approval", text],
           timeout=60, **box_hand())
    return said


def owner_card(pid, text, run=None):
    """The 🔐 card in #approvals. Only for what policy keeps for the owner (a unit enable cc-units says is his).
    With `run`, the card goes out as `cc-notify --approval --run <cmd>` from the box's own hand, so the owner's 👍
    runs that command once; without it, the 👍 is read by cc-slack's authorization-card handler (a door card)."""
    if TEST_STATE.search(text):
        log("unsaid", "-", 0, id=pid, why="synthetic test state, no 🔐 card posted")
        return False
    if run:
        rc, out = sh([os.path.join(BIN, "cc-notify"), "--approval", "--run", run, "--id", pid, "-t",
                      "lander approval", text], timeout=60, **box_hand())
        log("owner-card", "-", 0, id=pid, rc=rc)
        return rc == 0
    return say(pid, [slack(), "post", "-c", "#approvals", "--mention", "--id", pid, f"🔐 *Approval needed:* {text}"],
               "-", 0, hand=True)
