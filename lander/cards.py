"""What the lander tells people, and the few box calls the U3 modules share.

A CARD is one message about one job. `positions(repo, jobs)` gives each job in the queue one card saying where it
stands (`place <i> in the lane`, its stage) and edits it when its place or stage changes, then once more when it leaves;
those posts and edits are capped box-wide (EDITS_PER_MIN), wait out a Slack 429 (Retry-After, at most
EDIT_BACKOFF_MAX), and a card cc-slack will not edit is posted afresh; a last edit held when its lane ended goes on a
later tick (left_held, tick.retry_cards); `pin_hold(job, why)` files one planner request for a hold only a
`lander-self promote` clears;
`waited(job, secs, now)` files one planner request (another box repo's goes into its own seat) when the tick finds
the oldest due job past WAIT_FLAG_SECS, at most one per repo (per member, across its lanes) per WAIT_FLAG_SECS;
`held(repo, now)` notes a box hold, from which that age counts.
`landed(job)` turns the PR's #approvals card to landed and says the merge where someone is listening;
`stopped(job, why, route)` says a job left the lane and who picks it up; `behind(job, why)` says the lane updated a
BEHIND PR's branch, where a stop goes, and puts it into the repo's session once. Where it goes (where()):

    chat      the Slack thread the landing was asked from (job extra `chat`, `ts`)
    member    `#<h>-updates` for a member's landing, `#<h>` for its stop; the owner's channels never hear of it
    landed    a board row's landing: ONE line on #<repo> itself (`--route "[<repo>] PR #<n> landed" --major`); a
              PR no row owns gets only the #approvals card
    track     a stop: the track's own thread (cc-slack track-thread made one), when no chat asked
    route     `--route <title>` last: the job's own `route` if the queue call carried one, else `[<repo>] PR #<n> …`

A landing is also injected through cc-broker (`--source lander`), once and as fixed text (repo, PR number, URL), into
the orch that dispatched the row's track (tell_dispatcher), because that orch reads neither #<repo> nor the track's
thread and its post-merge steps wait on it.
That orch is the one cc-loop recorded host-side at dispatch (~/.cc/state/<repo>/.dispatch/<track>), never a seat.

stopped()'s route "seat" and "query" put the stop into the repo's session with `cc-slack inject`, once; "query", "planning" and "lander-self" file
a planner request (`cc-notify --ask`) for the planning seat, never a page to the owner. A "query" or "planning" stop in a
repo that is not the box's control repo (own_seat) goes to that repo's own seat through cc-broker instead, once per head
and words rather than per queuing, and planning
hears of it only if the broker will not take it. owner_card() is the 🔐 card
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

import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import pwd
import re
import socket
import stat
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
    """A path under the landing state dir (~/.cc/state/land at the passwd home, or $CC_LAND_STATE for tests; a queued
    tick never gets the queuer's CC_LAND_STATE, lane.tick_env)."""
    root = os.environ.get("CC_LAND_STATE") or os.path.join(PASSWD_HOME, ".cc", "state", "land")
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

# AN ENVIRONMENT THE LANDER BUILDS FOR ITSELF IS BUILT, NOT FILTERED (#862 review reads). A filter misses what nobody
# listed: XDG_CONFIG_HOME names a git config (url.insteadOf redirects a fetch) and a gh config (http_unix_socket
# redirects every call), GH_REPO points gh at another PR, BASH_ENV / ENV run a file in every script. Only these names
# (and LC_*) pass; HOME is the passwd home and PATH the root-owned dirs unless the caller names its own.
ENV_KEEP = ("LANG", "LANGUAGE", "TZ", "TERM", "USER", "LOGNAME")
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"


def kept_env(env, **fixed):
    out = {k: v for k, v in env.items() if k in ENV_KEEP or k.startswith("LC_")}
    out.update(HOME=PASSWD_HOME, PATH=SYSTEM_PATH)
    out.update(fixed)
    return out


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


def broker():
    """cc-broker, the door a machine's event goes through: `inject --no-start --source <who>`. cc-slack's own inject
    takes no --source, and the daemon refuses it there as a bad target (perms on #1165: the notice never arrived)."""
    return os.path.join(BIN, "cc-broker")


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


@contextlib.contextmanager
def _flock(name):
    os.makedirs(state("cards"), exist_ok=True)
    fd = os.open(state("cards", name), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _sent_lock():
    """cards/sent.json and cards/waited.json are read, added to and written again by the lane, its cards thread and
    the tick at once; each read-modify-write runs under this lock, so one never writes back a copy that loses another's
    mark (perms' read, 10-13: the cards thread wiped a once-marker)."""
    return _flock("sent.lock")


def _pending_lock():
    """The same for cards/pending.json (say() and retry()). Never held with _sent_lock, nor across a post: retry()
    reads under it, posts, and writes its outcome back under it onto a fresh read (perms' read, 10-13)."""
    return _flock("pending.lock")


def mark_sent(*pids):
    """Add `pids` to cards/sent.json, read afresh under _sent_lock (the last 500 are kept)."""
    with _sent_lock():
        write_json(_sent_path(), ((read_json(_sent_path(), []) or []) + list(pids))[-500:])


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
        mark_sent(pid)
        return True
    with _pending_lock():
        pending = read_json(_pending_path(), {}) or {}
        pending[pid] = {"argv": argv, "tries": 1, "repo": repo, "pr": pr, "hand": bool(hand)}
        write_json(_pending_path(), pending)
    log("unsaid", repo, pr, id=pid, tries=f"1/{SAY_TRIES}", why=out.strip()[-120:].replace("\n", " "))
    return False


def retry():
    with _pending_lock():
        pending = read_json(_pending_path(), {}) or {}
    if not pending:
        return
    sent, gone, tried = [], [], []
    for pid, p in pending.items():
        ok, out = _post(p["argv"], pid, bool(p.get("hand")))
        if ok:
            sent.append(pid)
        elif p["tries"] + 1 >= SAY_TRIES:
            log("unsaid", p.get("repo", "-"), p.get("pr", 0), id=pid, gave_up="yes",
                why="Slack never took it; this line is all it gets")
            gone.append(pid)
        else:
            tried.append(pid)
    with _pending_lock():   # onto a fresh read: a card say() added meanwhile is kept
        now = read_json(_pending_path(), {}) or {}
        for pid in sent + gone:
            now.pop(pid, None)
        for pid in tried:
            if pid in now:
                now[pid]["tries"] = max(int(now[pid].get("tries") or 1), pending[pid]["tries"] + 1)
        write_json(_pending_path(), now)
    mark_sent(*sent)


def post(job, kind, text, args, pid=None):
    pid = pid or producer_id(job, kind)
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
    ok = post(job, "landed", text, args) if args else rc in (0, 3, 4)
    try:
        tell_dispatcher(job)
    except Exception as e:  # a notice that fails never fails the landing it is about
        try:
            log("unsaid", job.repo, job.pr, why=f"{type(e).__name__}: {e}"[-120:].replace("\n", " "))
        except Exception:
            pass
    return ok


DISPATCH_KEY = re.compile(r"[A-Za-z0-9._-]+@[a-z0-9-]{2,20}")
DISPATCH_MAX = 256
PR_URL = re.compile(r"https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/pull/[0-9]+")


def dispatch_path(repo, track):
    """cc-loop's host-side copy of its dispatch record: ~/.cc/state/<repo>/.dispatch/<track>. A worker's sandbox binds
    only its own ~/.cc/state/<repo>/<track>, so it cannot write here; its $ST/orch it can, so that file is never read."""
    return os.path.join(PASSWD_HOME, ".cc", "state", repo, ".dispatch", track)


def read_small(path, cap):
    """A regular file's first line, or "" — never a FIFO (it would hold the lane), never through a symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return ""
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return ""
        return os.read(fd, cap).decode("utf-8", "replace").partition("\n")[0].strip()
    except OSError:
        return ""
    finally:
        os.close(fd)


def dispatcher(job):
    """The orch that dispatched the job's track, as its broker key `<orchrepo>@<alias>`, or "". Read from the host-side
    record only (dispatch_path), and only an orch's key: a bare repo name is a seat, which reads #<repo>, and is "".
    A member, a PR no row owns, no record, or one that is not such a key -> ""."""
    from lander import board
    track = "" if job.member else board.track_for(job)
    if not track:
        return ""
    rec = read_small(dispatch_path(job.repo, track), DISPATCH_MAX)
    return rec if DISPATCH_KEY.fullmatch(rec) else ""


def tell_dispatcher(job):
    """A MERGE REACHES THE ORCH THAT DISPATCHED THE TRACK, once. The #<repo> line is the planning seat's; an orch heard
    only the worker's 'queued to land' digest and sat on its post-merge steps until the owner asked (2026-10-04:
    2.5 h). The line is fixed text (repo, PR number and the row's URL), never the PR's title, which is
    the worker's own words (security read of 25b2675e: a title 'as if from Slack' put them into another orch). The repo
    seat dispatching is not woken here: it reads #<repo>. It goes through cc-broker (broker()) as source `lander`; a
    broker that refuses it is logged unsaid, not marked sent, and landed() catches anything this raises."""
    from lander import board
    key = dispatcher(job)
    if not key:
        return
    pid = producer_id(job, "dispatcher")
    if pid in (read_json(_sent_path(), []) or []):
        return
    track = board.track_for(job)
    url = str((board.rows(board.project_of(job)).get(track) or {}).get("pr") or "")
    url = url if PR_URL.fullmatch(url) and url.endswith(f"/pull/{int(job.pr)}") else ""
    text = f"[{job.repo}] PR #{int(job.pr)} merged{' ' + url if url else ''}. Your post-merge steps for it can run now."
    rc, out = sh([broker(), "inject", "--no-start", "--source", "lander", key, text], timeout=120)
    if rc == 0:
        mark_sent(pid)
    else:
        log("unsaid", job.repo, job.pr, id=pid, to=key, why=out.strip()[-120:].replace("\n", " "))


# --- where a queued PR stands --------------------------------------------------------------------------------------

STAGE_WORDS = {T.QUEUED: "waiting its turn", T.PLANNED: "planned, its checks next",
               T.CHECKING: "its checks are running", T.MERGEABLE: "checks green, merging next", T.MERGED: "merged",
               T.HELD: "held, it is tried again later"}
LEFT_WORDS = {T.MERGED: "merged", T.DEPLOY_PENDING: "merged", T.DEPLOYED: "merged", T.DONE: "done",
              T.QUERY: "stopped, its NOT merged line says why", T.HANDBACK: "handed back to its seat"}
WAIT_FLAG_SECS = 3600


def _queued_path(repo):
    """One file per repo: each repo's lane is its own process, so a shared file would lose one lane's cards."""
    return state("cards", f"queued-{repo}.json")


def queued_where(job):
    """Where a queued card goes: the chat the landing was asked from, a member's `#<h>-updates`, the track's thread,
    else the queue call's own --route title or `[<repo>] PR #<n> queued`."""
    if job.extra.get("chat"):
        return ["-c", job.extra["chat"]] + (["--thread", job.extra["ts"]] if job.extra.get("ts") else [])
    if job.member:
        return ["-c", f"#{job.member}-updates"]
    tt = track_thread(job)
    return ["--route", f"{tt} queued" if tt else job.extra.get("route") or f"[{job.repo}] PR #{job.pr} queued"]


def where_ok(to) -> bool:
    """Is `to` the shape queued_where() writes? A card's record is read back from a file and its `to` goes into
    cc-slack's argv, so one of any other shape, or with a value that reads as a flag or holds a control character, is
    never replayed."""
    return (isinstance(to, list) and len(to) % 2 == 0 and all(isinstance(a, str) and a for a in to)
            and to[::2] in (["-c"], ["-c", "--thread"], ["--route"])
            and not any(v.startswith("-") or re.search(r"[\x00-\x1f\x7f]", v) for v in to[1::2]))


def ledger(pid):
    """(chat, ts) of the post cc-slack's sent ledger holds for a producer id, else ("", "")."""
    name = re.sub(r"[^A-Za-z0-9._@#:+-]", "_", pid)[:200] + ".json"
    rec = read_json(os.path.join(os.path.expanduser(conf("CC_SLACK_DIR", "~/.cc/slack")), "sent", name), {})
    if isinstance(rec, dict) and rec.get("accepted") and rec.get("chat") and rec.get("ts"):
        return str(rec["chat"]), str(rec["ts"])
    return "", ""


EDITS_PER_MIN = 12    # queued-card posts and edits a minute, box-wide across every lane (10-13: ~10/min drew 429s)
EDIT_BACKOFF = 60     # seconds every card edit waits after a 429 that names no Retry-After
EDIT_BACKOFF_MAX = 300   # a longer Retry-After is cut to this: a misread number never silences the cards for hours


def _edits_path():
    return state("cards", "edits.json")


def _edits():
    """cards/edits.json as {"until": secs, "at": [secs]}. Anything else there (not a dict, a field that is not a
    number) reads as empty, never a raise: a raise here would stop every lane's cards."""
    d = read_json(_edits_path(), {})
    try:
        return {"until": float(d.get("until") or 0), "at": [float(t) for t in d.get("at") or []]}
    except (AttributeError, TypeError, ValueError):
        return {"until": 0.0, "at": []}


def _edit_slot(now):
    """May a queued-card post or edit go now? Not while a 429's back-off runs (`until`), nor once EDITS_PER_MIN went
    out in the last 60 s; else it is counted and True. cards/edits.json is shared by every lane, under its own lock."""
    with _flock("edits.lock"):
        d = _edits()
        if 0 < d["until"] - now <= EDIT_BACKOFF_MAX:   # an `until` further off came from a clock stepped back
            return False
        recent = [t for t in d["at"] if 0 <= now - t < 60]   # a stamp ahead of a clock stepped back is not counted
        if len(recent) >= EDITS_PER_MIN:
            return False
        d["at"] = recent + [now]
        write_json(_edits_path(), d)
        return True


def edit_wait(now):
    """Seconds until _edit_slot could say yes again: the 429 back-off's end, or the oldest edit in a full minute
    leaving it; 0 when a slot is free now."""
    d = _edits()
    recent = sorted(t for t in d["at"] if 0 <= now - t < 60)
    full = recent[-EDITS_PER_MIN] + 60 - now if len(recent) >= EDITS_PER_MIN else 0
    wait = d["until"] - now
    return max(wait if wait <= EDIT_BACKOFF_MAX else 0, full, 0)


def _back_off(out, now):
    """Slack said 429: every card edit waits Retry-After seconds when the answer names it (at most EDIT_BACKOFF_MAX),
    else EDIT_BACKOFF. An `until` more than EDIT_BACKOFF_MAX off came from a clock stepped back, so it is dropped,
    not kept by the max (Opus read of #1279)."""
    m = re.search(r"retry[-_ ]after\D{0,3}(\d+)", out, re.I)
    secs = min(int(m.group(1)), EDIT_BACKOFF_MAX) if m else EDIT_BACKOFF
    with _flock("edits.lock"):
        d = _edits()
        kept = d["until"] if d["until"] - now <= EDIT_BACKOFF_MAX else 0
        d["until"] = max(kept, now + secs)
        write_json(_edits_path(), d)
    return secs


# what a failure that may pass prints: cc-slack timed out or could not run (sh's 124 / 127), or Slack or the network
# did not answer (a 5xx, a URLError, a socket timeout); a 429 is caught before this
TRANSIENT = re.compile(r"HTTP Error 5\d\d|urlopen error|timed out|Connection (reset|refused|aborted)|Remote end closed")


def _edit(pid, text, repo, pr):
    """Rewrite the card posted under `pid`. -> "done" when it is edited or has nothing to edit (not out yet: pending a
    retry, or held by cc-slack's engagement gate); "later" when the cap, a 429's back-off or a failure that may pass
    (TRANSIENT) holds it, so the caller keeps it for the next pass (a timeout may come after Slack made the edit, and
    a repost would then say it twice); "post" for any other failure (not this bot's card, as every card in a track's
    thread was until 10-21, gone, a missing scope or token), so the caller posts the words once as a fresh card rather
    than drop them (10-21: a hold's card was never edited, and nobody heard of a PR held 4 h). A lasting failure kept
    as "later" would take a box-wide slot every pass and starve every repo's cards (security read of #1844)."""
    chat, ts = ledger(pid)
    if not ts:
        return "done"
    now = time.time()
    if not _edit_slot(now):
        return "later"
    rc, out = sh([slack(), "edit", chat, ts, text], timeout=120)
    if rc == 0:
        return "done"
    why = out.strip()[-120:].replace("\n", " ")
    if "Error 429" in out or "ratelimited" in out:   # cc-slack edit prints "HTTP Error 429: Too Many Requests"
        log("unsaid", repo, pr, id=pid, edit="later", backoff=_back_off(out, now), why=why)
        return "later"
    if rc in (124, 127) or TRANSIENT.search(out):
        log("unsaid", repo, pr, id=pid, edit="later", why=why)
        return "later"
    log("unsaid", repo, pr, id=pid, edit="post", why=why)
    return "post"


def _repost(pid, text, to, repo, pr):
    """Post `text` as a fresh card in place of the one under `pid` that would not be edited, under a new id
    (`<pid>#<secs>`), into `to`, the card's queued_where. It takes a slot under the same cap as an edit. -> the new
    id, which later edits go to, or "" when the cap holds it for a later pass."""
    if not _edit_slot(time.time()):
        return ""
    new = f"{pid.partition('#')[0]}#{int(time.time())}"
    say(new, [slack(), "post", *to, "--id", new, text], repo, pr)
    return new


def positions(repo, jobs):
    """A QUEUED PR SAYS WHERE IT STANDS (brief: "post a queued card with the PR's position and update it as it
    moves"). `jobs` is the lane's list (jobs.lane_jobs: put first, then arrival); those not at rest are the queue.
    Each gets one card, `[<repo>] PR #<n> is queued to land: place <i> in the lane, <stage>.`, posted once under
    `land:<repo>:<pr>:queued@<queued_at>` (queued_where) and edited in place (`cc-slack edit`) only when its place or
    stage changes (10-13: a card that also counted the lane was edited for every PR that joined behind it, and the
    edits drew Slack 429s). A card whose job left the queue gets one last edit saying how, and its record goes.
    Edits go through _edit: one the box-wide cap or a 429 holds stays unrecorded and goes on a later pass; one cc-slack
    will not make is posted as a fresh card (_repost) where the record says the card went (`to`), and the record keeps
    the new card's id (`card`) for the next edit. A card gets one repost, under the same cap: one whose repost is refused
    too is marked and never edited again, so a lasting refusal never posts a card a change. A new card's post takes a
    slot under the same cap and back-off (Opus read of #1275: posts skipped the cap), and one held is posted on a
    later pass. A last edit held keeps its words (`left`) in the record; a lane that ends with one held leaves it to the tick
    (left_held). A record whose `to` is not the shape queued_where() writes is dropped on read (where_ok), and a last
    edit refused with no `to` to repost into is logged as dropped. cards/queued-<repo>.json keeps each card's
    place and stage, so a queue that has not moved sends nothing; it is read and written under the repo's
    own cards lock (lanes/<repo>.cards), so a lane's cards thread still running after its lane lock went (CARDS_WAIT
    ran out) and the next lane's never lose each other's write. No model call. The lane calls it on a thread of its
    own (Lane.carding), so a slow Slack never holds a landing.
    -> False when an edit was held for later, so the lane hands the same queue over again; else True."""
    from lander import jobs as J
    os.makedirs(J.lanes_dir(), exist_ok=True)
    fd = os.open(J.lane_file(repo, "cards"), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return _positions(repo, jobs, J)
    finally:
        os.close(fd)


def _positions(repo, jobs, J):
    said = read_json(_queued_path(repo), {})
    said = said if isinstance(said, dict) else {}
    bad = [pid for pid, last in said.items() if not isinstance(last, dict) or "to" in last and not where_ok(last["to"])
           or type(last.get("pr")) is not int]   # its pr goes into the card's words
    for pid in bad:
        log("unsaid", repo, None, id=pid, edit="dropped", why="its record is not the shape a card's is")
        del said[pid]
    live = [j for j in jobs if j.state not in J.RESTING]
    mine, moved, later = set(), bool(bad), False
    for i, job in enumerate(live, 1):
        pid = producer_id(job, "queued")
        mine.add(pid)
        last = said.get(pid)
        if last and (last.get("place"), last.get("state")) == (i, job.state):
            continue
        text = (f"[{job.repo}] PR #{job.pr} is queued to land: place {i} in the lane, "
                f"{STAGE_WORDS.get(job.state, job.state)}.")
        card, to = (last or {}).get("card") or pid, queued_where(job)
        if last:
            how = "skip" if last.get("noedit") else _edit(card, text, job.repo, job.pr)
            if how == "post" and card != pid:   # its repost would not be edited either: one fresh card, not one a change
                how = "skip"
            elif how == "post":
                card = _repost(card, text, to, job.repo, job.pr)
                how = "post" if card else "later"
        else:
            how = "post" if _edit_slot(time.time()) else "later"
        if how == "later":
            later = True
            continue
        if how == "post" and not last:
            post(job, "queued", text, to)
        said[pid], moved = {"repo": job.repo, "pr": job.pr, "place": i, "state": job.state,
                            "card": card, "to": to, **({"noedit": True} if how == "skip" else {})}, True
    state_of = {producer_id(j, "queued"): j.state for j in jobs}
    for pid, last in list(said.items()):
        if last.get("repo") != repo or pid in mine:
            continue
        left = LEFT_WORDS.get(state_of.get(pid)) or last.get("left") or "out of the lane"
        text = f"[{repo}] PR #{last.get('pr')} has left the landing queue: {left}."
        card = last.get("card") or pid
        how = "skip" if last.get("noedit") else _edit(card, text, repo, last.get("pr"))
        if how == "post" and not last.get("to"):   # a record from before `to` was kept: nowhere to post it
            log("unsaid", repo, last.get("pr"), id=pid, edit="dropped", why="no `to` to post the last words into")
        elif how == "post" and card == pid and not _repost(card, text, last["to"], repo, last.get("pr")):
            how = "later"   # one repost a card, as above, under the cap
        if how == "later":
            later, moved = True, moved or last.get("left") != left
            last["left"] = left   # the job may be gone from the list by the next pass
            continue
        del said[pid]
        moved = True
    if moved:   # the lane calls this every pass: an unmoved queue writes nothing either
        write_json(_queued_path(repo), said)
    return not later


def left_held(repo):
    """Does a card of `repo`'s wait on a last edit the cap or a 429 held (its record keeps `left`)? Its lane may have
    ended since, and nothing then hands its queue over again, so the tick does (tick.retry_cards; Opus read of #1275:
    a held last edit was never retried)."""
    said = read_json(_queued_path(repo), {})
    return isinstance(said, dict) and any(isinstance(v, dict) and v.get("left") for v in said.values())


def _waited_path():
    return state("cards", "waited.json")


def held(repo, now):
    """The tick found the box holding `repo`'s queue at `now` (a pause, a tier stop, a GitHub backoff). The age the
    tick flags counts from the last such tick, not from queued_at, so a hold that lifts is not read as a late lane."""
    with _sent_lock():
        d = read_json(_waited_path(), {}) or {}
        d.setdefault(repo, {})["held"] = int(now)
        write_json(_waited_path(), d)


def held_at(repo):
    """When the tick last found `repo`'s queue held by the box (held()); 0 when never."""
    return int(((read_json(_waited_path(), {}) or {}).get(repo) or {}).get("held") or 0)


def waited(job, secs, now=None):
    """THE OLDEST DUE JOB HAS WAITED TOO LONG (brief: "have the lander's tick flag once when the oldest due job has
    waited over 60 min"). A planner request (`cc-notify --ask` from box_hand) for the planning seat, never a page to
    the owner, and a `waited` queue.log line. Once per queuing: its id `land:<repo>:<pr>:waited@<queued_at>` goes into
    cards/sent.json once cc-notify took it (one cc-notify refused is tried again next tick). And at most one per repo
    per WAIT_FLAG_SECS (cards/waited.json), whichever job it names: a queue whose oldest job keeps changing, as a member
    closing a PR on every tick, wakes the planning seat once an hour, not once a tick (perms' read, 10-13). A member's
    lanes (`<h>--<row>`, one per board row) share one cap, keyed `member:<h>`: perms' read, 10-13, "six rows meant six
    wake-ups at once". A repo name has no ":", so no member key can be a box repo's. Another box repo's job goes to
    that repo's own seat through cc-broker (tell_own_seat), not planning: on 10-22 two dispatch PRs moving through a
    40-job queue each woke the planning seat, which could only ask dispatch; a broker that refuses it files the request.
    -> True when it was said now."""
    t = int(now if now is not None else time.time())
    pid = producer_id(job, "waited")
    if pid in (read_json(_sent_path(), []) or []):
        return False
    key = f"member:{job.member}" if job.member else job.repo
    last = int(((read_json(_waited_path(), {}) or {}).get(key) or {}).get("said") or 0)
    if last and t - last < WAIT_FLAG_SECS:
        return False
    text = (f"[{job.repo}] PR #{job.pr} has waited {secs // 60} min in the landing queue, the oldest job due there "
            f"({STAGE_WORDS.get(job.state, job.state)}). Nothing stopped it; the lane has not landed it yet.")
    if own_seat(job, "planning") and tell_own_seat(job, text):
        rc = 0
    else:
        rc, _ = sh([os.path.join(BIN, "cc-notify"), "--ask", "--id", pid, "-t", f"{job.repo} landing", text],
                   timeout=60, **box_hand())
    log("waited", job.repo, job.pr, mins=secs // 60, rc=rc)
    if rc != 0:   # not taken: left unmarked, so the next tick tries again (Opus read, 10-13)
        return False
    mark_sent(pid)
    with _sent_lock():
        d = read_json(_waited_path(), {}) or {}
        d.setdefault(key, {})["said"] = t
        write_json(_waited_path(), d)
    return True


def main_red(job, secs, now=None):
    """A CHECK RED ON MAIN HAS HELD A PR FOR AN HOUR (brief: "ONE alert line naming the check and its failing IDs ...
    not one per PR"). `job` is a PR it holds (extra.main_red); a planner request (`cc-notify --ask` from box_hand), as
    waited's, and a `main-red-alert` queue.log line. At most one per repo and check per WAIT_FLAG_SECS
    (cards/waited.json, key `main-red:<repo>:<check>`), whichever PR it names and whatever main's failing set says: a
    pid, port or count left in a case id would make every base run a new set (Opus and perms, 10-13), so the set is
    never the key. -> True when it was said now."""
    t = int(now if now is not None else time.time())
    mr = job.extra.get("main_red") or {}
    check, fails = mr.get("check") or "?", list(mr.get("fails") or [])
    key = f"main-red:{job.repo}:{check}"
    last = int(((read_json(_waited_path(), {}) or {}).get(key) or {}).get("said") or 0)
    if last and t - last < WAIT_FLAG_SECS:
        return False
    named = "; ".join(fails[:5]) + (f" (+{len(fails) - 5} more)" if len(fails) > 5 else "") if fails \
        else "none named, only its exit code"
    text = (f"[{job.repo}] check {check} has been red on main for {secs // 60} min and holds PRs that add a red of "
            f"their own to it (PR #{job.pr} among them). Main's failing cases: {named}.")
    rc, _ = sh([os.path.join(BIN, "cc-notify"), "--ask", "--id", f"land:{key}@{t}", "-t", f"{job.repo} landing", text],
               timeout=60, **box_hand())
    log("main-red-alert", job.repo, job.pr, check=check, mins=secs // 60, fails=len(fails), rc=rc)
    if rc != 0:   # not taken: left unmarked, so the next tick tries again
        return False
    with _sent_lock():
        d = read_json(_waited_path(), {}) or {}
        d.setdefault(key, {})["said"] = t
        write_json(_waited_path(), d)
    return True


def pin_hold(job, why, what=""):
    """A HOLD ONLY A PIN CLEARS REACHES THE PLANNING SEAT, as main_red does (10-21: a box repo's PR sat held 4 h on
    "the lander holds no remote URL … `lander-self promote` pins one", and nobody heard). Lane.hold asks it for a hold
    flagged where it was raised (G.Unpinned), never for one whose words merely say so: a hold's reason can carry text
    the branch wrote (a CI context, a path), so `why` goes in stripped of control characters and cut to 200; it files one planner request (`cc-notify --ask` from box_hand) naming the fix, once per
    repo and head (brief: "once per repo and head, not every retry"): its id `land:<repo>:pin@<head>` goes into
    cards/sent.json once cc-notify took it, so the hold every retry makes again is not said again; one refused is
    tried at the next hold. tip.revert asks it too for a revert it could not push, with `what` in place of "PR #<n> is
    held" and its breaker's sha as the head. -> True when it was said now."""
    pid = f"land:{job.repo}:pin@{(job.head or '')[:12]}"
    if pid in (read_json(_sent_path(), []) or []):
        return False
    why = re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", why)[:200]
    then = "." if what else "; the lane tries the PR again on its own after that."
    text = (f"[{job.repo}] {what or f'PR #{job.pr} is held'} until the lander is pinned for {job.repo}: {why}. The "
            f"fix is a `lander-self promote` that pins it{then}")
    rc, _ = sh([os.path.join(BIN, "cc-notify"), "--ask", "--id", pid, "-t", f"{job.repo} landing", text],
               timeout=60, **box_hand())
    log("pin-hold-alert", job.repo, job.pr, rc=rc)
    if rc != 0:
        return False
    mark_sent(pid)
    return True


QUERY_ROUTES = ("query", "planning", "lander-self")
PROTECTED_RE = re.compile(r"\(CC_PROTECTED_PATHS_[^)]*\)")
NEXT_MARK = " — next: "


def shorten_stop(why):
    """`why` cut to STOP_CARD_MAX. A why that ends in NEXT_MARK and its next action keeps that action whole and cuts
    the reason before it: the next step is what the reader acts on (owner 10-16)."""
    if len(why) <= STOP_CARD_MAX:
        return why
    head, sep, tail = why.rpartition(NEXT_MARK)
    room = STOP_CARD_MAX - len(sep + tail) - 1
    if sep and room >= 40:
        return head[:room] + "…" + sep + tail
    return why[:STOP_CARD_MAX - 1] + "…"


def stopped(job, why, route):
    """`route` says who picks it up, in the lane's words:

        seat         the row's own seat fixes it and pushes; the stop also goes into the repo's session (inject, once)
        #<h>         a member's landing: its own `#<h>` (where() already says so); a member is never injected
        query, planning, lander-self
                     the planning seat decides: the stop is said where a stop is said and a planner request
                     (`cc-notify --ask`) is filed, never a page to the owner; only "query" also wakes the repo's
                     session, because "planning" and "lander-self" are the planning seat's own, and an inject on top of
                     the request would wake it twice. A "query" or "planning" stop in another repo (own_seat) is that
                     repo's seat's instead: it goes to it through cc-broker as source `lander` (no planner request,
                     no second inject), and only a broker that refuses it files the planner request after all
        owner        a protected head the owner has not 👍'd, found in the lane: said once in the thread or routed,
                     then the 🔐 card (say_protected_stop)
        door         the queue call's own refusal at the protected door: only the 🔐 card (say_protected_door)

    Anything else is the queue call's own --route title, as before."""
    why = " ".join(str(why).split()) or "it stopped without saying why"
    if route == "door":
        return protected_door(job, why)
    if route == "owner":
        return protected_stop(job, why)
    short = shorten_stop(why)
    mine = own_seat(job, route)
    who = f"It is {job.repo}'s own seat's to settle" if mine else {
           "seat": "The track's seat fixes it and pushes; the lane takes the new head",
           "query": "The planning seat decides what happens to it",
           "planning": "The planning seat decides what happens to it",
           "lander-self": "It changes the lander itself, so the planning seat lands it by hand"}.get(route, "")
    url = job.extra.get("url", "")
    text = f"[{job.repo}] PR #{job.pr}: NOT merged ❌ — {short}." + (f" {who}." if who else "") + (f" {url}" if url else "")
    args = where(job, False)
    known = route in ("seat",) + QUERY_ROUTES or route.startswith("#")
    if not known and not job.extra.get("chat"):
        args = ["--route", route]
    held = lambda kind: f"land:{job.repo}:{job.pr}:{kind}@{head_reason(job, text)}"
    said = post(job, "stopped", text, args, held("stopped"))
    if (not tell_own_seat(job, text)) if mine else route in QUERY_ROUTES:   # a refused hand-off still reaches planning
        sh([os.path.join(BIN, "cc-notify"), "--ask", "--id", held("query"), "-t", f"{job.repo} landing",
            text], timeout=60, **box_hand())
    if not job.member and not mine and route in ("seat", "query"):
        sent = read_json(_sent_path(), []) or []
        pid = producer_id(job, "inject")
        if pid not in sent:
            sh([slack(), "inject", job.repo, f"[{job.repo}] PR #{job.pr} landing stopped: {short}. The way back in: "
                f"fix it and push; the lane takes the new head."], timeout=120)
            mark_sent(pid)
    return said


def control_repo():
    """The box's control repo, the one its planning seat runs in, by cc's ctl_repo rule (cc-notify's CTL too): the repo
    this copy lives in under ~/dev, else CC_BOX, else the short hostname."""
    dev = os.path.join(PASSWD_HOME, "dev") + os.sep
    if BIN.startswith(dev):
        return BIN[len(dev):].split(os.sep)[0]
    return conf("CC_BOX") or socket.gethostname().split(".")[0]


def own_seat(job, route):
    """A "query" or "planning" stop that is its repo's own seat's to settle, not the planning seat's: a box repo (no
    member) other than the control repo. On 10-16 about 15 dispatch PRs no row owned stopped one by one over 30 min,
    each a planner request the planning seat could only forward to the repo that runs dispatch."""
    return route in ("query", "planning") and not job.member and job.repo != control_repo()


def head_reason(job, text):
    """`<head>:<hash of text>`: a stop notice keyed on this says a held PR once per head and reason, not once per queuing."""
    return f"{(job.head or '')[:12]}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"


def tell_own_seat(job, text):
    """The stop into the repo's own seat through cc-broker, once per head and words: source `lander`, so ordinary
    stops that come in a run are one broker digest there rather than a wake each (a line asking for a choice still
    wakes it at once). Keyed on the head and the text (head_reason), not queued_at: on 10-21 five PRs held for perms' read woke the
    lessons seat once per lane pass, each queued again at the same head and reason. True when the broker took it (or
    did before); False files the planner request instead (stopped)."""
    pid = f"land:{job.repo}:{job.pr}:own-seat@{head_reason(job, text)}"
    if pid in (read_json(_sent_path(), []) or []):
        return True
    rc, out = sh([broker(), "inject", "--no-start", "--source", "lander", job.repo, text], timeout=120)
    if rc == 0:
        mark_sent(pid)
        return True
    log("unsaid", job.repo, job.pr, id=pid, to=job.repo, why=out.strip()[-120:].replace("\n", " "))
    return False


def behind(job, why):
    """The lane updated a BEHIND PR's branch for GitHub's strict protection (Lane.behind): said where a stop is said,
    and, but for a member, put into the repo's session once, so its seat knows the head moved under it and why."""
    why = " ".join(str(why).split())
    text = f"[{job.repo}] PR #{job.pr}: {why}."
    said = post(job, "behind", text, where(job, False))
    if not job.member:
        pid = producer_id(job, "behind-inject")
        if pid not in (read_json(_sent_path(), []) or []):
            sh([slack(), "inject", job.repo, text], timeout=120)
            mark_sent(pid)
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
        genv = M.env(job.member, job.repo) if job.member else None
        token = M.gh_token(job.member, job.repo) if job.member else None
        return L.pr_head(J.repo_root(job.repo), job.pr, token, genv) or ""
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
        # --not-perms only declares the words no permission question: they name protected paths (settings.json among
        # them), which cc-notify would otherwise refuse as undeclared. It does not skip PERMS FIRST: cc-notify files
        # every --approval with the permission session, which grants it or rules it his and posts the card itself
        rc, out = sh([os.path.join(BIN, "cc-notify"), "--approval", "--run", run, "--id", pid, "--not-perms", "-t",
                      "lander approval", text], timeout=60, **box_hand())
        log("owner-card", "-", 0, id=pid, rc=rc)
        return rc == 0
    return say(pid, [slack(), "post", "-c", "#approvals", "--mention", "--id", pid, f"🔐 *Approval needed:* {text}"],
               "-", 0, hand=True)
