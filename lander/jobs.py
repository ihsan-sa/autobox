"""Job files, the inbox, the lanes' locks and every path the lander keeps state under (review B4, S11).

PATHS are read from the environment at CALL time, so a test (or a second box layout) moves them all at once:
  LANDQ    $CC_LANDER_STATE or $HOME/.cc/state/land. THE DEFAULT IS THE LIVE QUEUE the old lander uses; nothing
           runs this lane against it until cutover (U5).
  jobs     <LANDQ>/<repo>-<pr>.json — today's path, so cc-slack's Home tab, cc-reconcile, the dashboard and the
           rest keep reading; each file keeps a `stage` key (STAGE_OF[state], the word they show) beside `state`.
  inbox    <LANDQ>/jobs/new/<repo>-<pr>.<pid>.<nonce>.json — what anyone may write (submit); only the lane, holding
           its repo's lock, folds a request into the job (drain). So the lane is the job file's one writer.
  lanes    <LANDQ>/lanes/<repo>.lock (flock) + <repo>.running {pid, since}; <LANDQ>/lanes/gh.backoff (gh.py).
           <LANDQ>/lanes/<repo>.settle (flock): what the tick holds to settle a deploy-pending job, and drain
           holds to write one. The lane rests a job there and never takes it up again, so settling does not need
           the lane lock, which a busy lane holds from one job to the next.
  handed   <LANDQ>/handed/<repo>-<pr>.json — the watch on a handed-back PR (lane.handback, tick).
  rest     <LANDQ>/rest/<repo>-<pr>.json — a job that has ENDED (done, query, handback). The old lander unlinked its
           job file when the landing finished, and every reader counts <LANDQ>/*.json as a landing in flight (the Home
           tab's RUNNING tally, cc-bundle's queue depth), so an ended job leaves that directory; load() still finds it
           here, so a re-queue keeps reads_used and the prior verdict.
  log      <LANDQ>/queue.log (events.py).
  BIN $CC_BIN or <core>/bin · DEV $CC_DEV or $HOME/dev · BOARDS $CC_BOARDS or $HOME/.cc/boards ·
  MEMBERS $CC_MEMBERS or $HOME/.cc/members.
  repo_root: the board's `path` when it holds a .git, else DEV/<repo>; a member project <h>--<t> lands out of
  <LANDQ>/clones/<h>--<t>.

THE MACHINE. A job's `state` moves only along NEXT; move() refuses any other edge (ValueError), appends one
history entry, sets `stage`, saves atomically and writes `stage <repo>#<pr> <state>` to queue.log. Every save
sets `stage` (stage_of: STAGE_OF[state], in the old lander's words where the readers filter on one — `review` for a
checked job waiting on its read, `deferred` for a job held till a usage limit resets, which the Home tab and the
dashboard do not count as running), and the record is validated (T.Job.to_dict) before it is written.

DRAIN (the lane only, under the lane lock, then rest_lock): a request with no job makes a queued job; one for a job
at rest (done, query, handback, or held for a reason a push mends) is a fresh start that keeps reads_used and the prior
verdict (`requeued`); one for an active job fills chat/ts/who where empty (`again`), and on a checking job sets
extra.reread so it reads its PR's state and head at its next turn (a push mid-check re-queues it, which says `again`).
A job held by the box itself (hold="box": a usage wall, a cap, an unrunnable check) is active: a fresh start would
not mend it.
A REQUEST IS UNTRUSTED. Anyone may write the inbox, so drain takes only chat, ts and who from it (repo and pr route
it). An approval, a verdict or a reads count in a request is dropped: the owner's 👍 is the approval record
`lander queue` writes after it checked the uid itself (approvals/<repo>-<pr>.json, read by the lane's door), and a
verdict comes only from the lane's own review or from PR markers the box's login wrote (review.recorded).
  approvals <LANDQ>/approvals/<repo>-<pr>.json {approved_by, approved_head, at} — approve()/approval().
  carry     <LANDQ>/carry/<repo>-<pr>.json {reads_used} — a handed-back job's spent reads, written by the tick
            when a push re-queues it and taken by drain, so the reads cap still holds across the handback.
  first     <LANDQ>/first/<repo>-<pr>.json {by, at} — `lander queue --first` put the PR at the front of its lane
            (put_first/first). Never a request field, for the same reason as an approval. lane_jobs lists a job
            with one before every other, oldest `at` first. It is good for one landing: the job's move to a resting
            state (merged, closed, handed back, a query) and its removal take it away (drop_first), so a PR closed
            unmerged and queued again later waits its turn unless someone puts it first again.
"""
from __future__ import annotations

import contextlib
import fcntl
import glob
import json
import os
import re
import secrets
import tempfile
import time

from lander import events as E
from lander import types as T

CORE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def _home() -> str:
    return os.environ.get("HOME") or os.path.expanduser("~")


def landq() -> str:
    return os.environ.get("CC_LANDER_STATE") or f"{_home()}/.cc/state/land"


def running_release() -> str:
    """The tree this code runs from: releases/<sha> for a pinned lander, a checkout's root in development."""
    return os.path.dirname(CORE)


def current_release() -> str:
    """What ~/.cc/lander/current resolves to now, or '' when it is missing or points outside releases/."""
    root = f"{_home()}/.cc/lander"
    cur, rels = os.path.realpath(f"{root}/current"), os.path.realpath(f"{root}/releases")
    return cur if os.path.islink(f"{root}/current") and cur.startswith(rels + "/") and os.path.isfile(
        f"{cur}/core/lander/cli.py") else ""


def stale_release() -> str:
    """The release `current` names when it is not the one this code runs from, else ''. A lander run from a
    checkout (development, the tests) is never stale: only a pinned release is switched."""
    mine, cur = running_release(), current_release()
    rels = os.path.realpath(f"{_home()}/.cc/lander/releases")
    return cur if cur and mine.startswith(rels + "/") and cur != mine else ""


def state_dir() -> str:
    """The directory LANDQ sits in (~/.cc/state by default): member-spend.json lives there, as cc's member_gate reads it."""
    return os.path.dirname(landq().rstrip("/"))


def bin_dir() -> str:
    return os.environ.get("CC_BIN") or f"{CORE}/bin"


def dev() -> str:
    return os.environ.get("CC_DEV") or f"{_home()}/dev"


def boards() -> str:
    return os.environ.get("CC_BOARDS") or f"{_home()}/.cc/boards"


def members_dir() -> str:
    return os.environ.get("CC_MEMBERS") or f"{_home()}/.cc/members"


def inbox_dir() -> str:
    return f"{landq()}/jobs/new"


def lanes_dir() -> str:
    return f"{landq()}/lanes"


def rest_dir() -> str:
    return f"{landq()}/rest"


def handed_dir() -> str:
    return f"{landq()}/handed"


def clones_dir() -> str:
    return f"{landq()}/clones"


def safe(repo: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", repo)


def job_path(repo: str, pr) -> str:
    return f"{landq()}/{repo}-{int(pr)}.json"


def rest_path(repo: str, pr) -> str:
    return f"{rest_dir()}/{repo}-{int(pr)}.json"


def handed_path(repo: str, pr) -> str:
    return f"{handed_dir()}/{repo}-{int(pr)}.json"


REPO_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}")


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_atomic(path: str, obj) -> None:
    """A reader sees the whole file or the one before, never half of one: mkstemp in the dir, fsync, rename."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def board(repo: str) -> dict:
    """The board JSON for `repo`, or {}. A symlinked board file is refused ({}): a member's board could be a link
    into a directory the member writes, and repo_root() trusts the `path` this returns. A member workspace's own
    row is read through members.member_board(), which opens the link's target without following anything."""
    p = f"{boards()}/{repo}.json"
    if os.path.islink(p):
        return {}
    j = read_json(p)
    return j if isinstance(j, dict) else {}


def repo_root(repo: str) -> str:
    from lander import members as M   # members imports this module for its paths
    h, t = M.member_of(repo)
    if h and t:
        return f"{clones_dir()}/{repo}"
    p = board(repo).get("path") or ""
    return p if p and os.path.isdir(f"{p}/.git") else f"{dev()}/{repo}"


# --- the machine ---------------------------------------------------------------------------------------------------

STAGE_OF = {T.QUEUED: "queued", T.PLANNED: "gates", T.CHECKING: "gates", T.MERGEABLE: "merge", T.MERGED: "merged",
            T.DEPLOY_PENDING: "install", T.DEPLOYED: "verify", T.DONE: "done", T.HANDBACK: "handed",
            T.HELD: "held", T.QUERY: "query"}

NEXT = {
    T.QUEUED: {T.PLANNED, T.HELD, T.QUERY, T.HANDBACK, T.MERGED, T.DONE},
    T.PLANNED: {T.CHECKING, T.MERGEABLE, T.HELD, T.QUERY, T.HANDBACK, T.QUEUED},
    T.CHECKING: {T.MERGEABLE, T.HELD, T.QUERY, T.HANDBACK, T.QUEUED},
    T.MERGEABLE: {T.CHECKING, T.MERGED, T.HELD, T.QUERY, T.HANDBACK, T.QUEUED},
    T.MERGED: {T.DEPLOY_PENDING, T.DONE},
    T.DEPLOY_PENDING: {T.DEPLOYED, T.DONE, T.HELD},
    T.DEPLOYED: {T.DONE},
    T.HELD: {T.QUEUED, T.PLANNED, T.CHECKING, T.MERGEABLE, T.DEPLOY_PENDING, T.QUERY, T.HANDBACK, T.DONE},
    T.QUERY: {T.QUEUED, T.DONE},
    T.HANDBACK: {T.QUEUED, T.DONE},
    T.DONE: {T.QUEUED},
}

# At rest: nothing the lane does moves it; a request (drain) or a tick does.
RESTING = (T.QUERY, T.DONE, T.DEPLOY_PENDING, T.DEPLOYED, T.HANDBACK)
# Ended: the job file leaves <LANDQ>/*.json for rest/ (the readers count every file there as in flight).
ENDED = (T.DONE, T.QUERY, T.HANDBACK)


def stage_of(job: T.Job) -> str:
    if job.state == T.HELD and job.extra.get("deferred"):
        return "deferred"
    if job.state == T.CHECKING and job.plan and job.plan.paid and all(n in job.results for n in job.plan.checks):
        return "review"
    return STAGE_OF[job.state]


def file_of(job: T.Job) -> str:
    """Where the job's file sits for its state: today's path while it is live, rest/ once it has ended."""
    return rest_path(job.repo, job.pr) if job.state in ENDED else job_path(job.repo, job.pr)


def load_path(path: str):
    d = read_json(path)
    if not isinstance(d, dict):
        return None
    try:
        return T.Job.from_dict(d)
    except ValueError:
        return None


def load(repo: str, pr):
    """The live job, else the ended one in rest/, else None."""
    return load_path(job_path(repo, pr)) or load_path(rest_path(repo, pr))


def save(job: T.Job) -> None:
    job.stage = stage_of(job)
    path = file_of(job)
    write_atomic(path, job.to_dict())
    other = rest_path(job.repo, job.pr) if path == job_path(job.repo, job.pr) else job_path(job.repo, job.pr)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(other)


def remove(job: T.Job) -> None:
    for p in (job_path(job.repo, job.pr), rest_path(job.repo, job.pr)):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(p)
    drop_first(job.repo, job.pr)


def move(job: T.Job, state: str, why: str = "", **kv) -> T.Job:
    """One edge of NEXT: refused (ValueError, nothing written) when it is not one. kv go on the history entry and
    the `stage` line (sha=, by=, proof=)."""
    T.check_enum("state", state, T.JOB_STATES)
    if state not in NEXT.get(job.state, ()):
        raise ValueError(f"{job.key}: {job.state} -> {state} is not an edge the lander takes")
    entry = {"at": E.stamp(), "state": state, **({"why": why} if why else {}),
             **{k: v for k, v in kv.items() if v not in (None, "")}}
    job.history.append(entry)
    job.state = state
    save(job)
    if state in RESTING:   # a put-first is good for one landing (jobs.first)
        drop_first(job.repo, job.pr)
    E.stage(job.repo, job.pr, state, **kv)
    return job


# --- the inbox (S11) -----------------------------------------------------------------------------------------------

def submit(repo: str, pr, **fields) -> str:
    """Write one request for (repo, pr) into the inbox; anyone may. Returns its path."""
    d = inbox_dir()
    os.makedirs(d, exist_ok=True)
    path = f"{d}/{repo}-{int(pr)}.{os.getpid()}.{secrets.token_hex(4)}.json"
    write_atomic(path, {"repo": repo, "pr": int(pr), "at": E.stamp(),
                        **{k: v for k, v in fields.items() if v not in (None, "")}})
    return path


def requests(repo: str = ""):
    """[(path, request)] oldest first; a file that is not a request is moved aside."""
    out = []
    for p in sorted(glob.glob(f"{inbox_dir()}/*.json"), key=lambda p: (os.path.getmtime(p), p)):
        r = read_json(p)
        if not (isinstance(r, dict) and isinstance(r.get("repo"), str) and isinstance(r.get("pr"), int)
                and REPO_RE.fullmatch(r["repo"])):
            with contextlib.suppress(OSError):
                os.replace(p, p + ".unreadable")
            continue
        if not repo or r["repo"] == repo:
            out.append((p, r))
    return out


CARRY = ("chat", "ts", "who")   # the only fields drain takes from a request (review of #771: an inbox request is
                                # anyone's, so an approval or a verdict in one is dropped, never trusted)


def approvals_dir() -> str:
    return f"{landq()}/approvals"


def approval_path(repo: str, pr) -> str:
    return f"{approvals_dir()}/{safe(repo)}-{int(pr)}.json"


def approve(repo: str, pr, by: str, head: str) -> None:
    """Record the owner's 👍 on (repo, pr) at `head`. Only `lander queue`, after owner_approved(by) and a head gh named,
    and the door carrying it to a head whose protected files are identical, call this."""
    os.makedirs(approvals_dir(), exist_ok=True)
    write_atomic(approval_path(repo, pr), {"approved_by": by, "approved_head": head, "at": E.stamp()})


def approval(repo: str, pr) -> dict:
    """{approved_by, approved_head} from the approval record, or {} (none, or not that shape)."""
    r = read_json(approval_path(repo, pr))
    if not (isinstance(r, dict) and isinstance(r.get("approved_by"), str) and isinstance(r.get("approved_head"), str)
            and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", r["approved_head"])):
        return {}
    return {"approved_by": r["approved_by"], "approved_head": r["approved_head"]}


def carry_path(repo: str, pr) -> str:
    return f"{landq()}/carry/{safe(repo)}-{int(pr)}.json"


def carry(repo: str, pr, reads_used: int) -> None:
    """What a handed-back job had spent, for the lane to pick up when the push re-queues it (tick.sweep_handed). It
    is the lane's own record, never a request field: a request is anyone's."""
    os.makedirs(os.path.dirname(carry_path(repo, pr)), exist_ok=True)
    write_atomic(carry_path(repo, pr), {"reads_used": int(reads_used or 0), "at": E.stamp()})


def take_carry(repo: str, pr) -> int:
    """The reads a handed-back job had used (0 when none was carried); the record is removed."""
    p = carry_path(repo, pr)
    r = read_json(p)
    with contextlib.suppress(OSError):
        os.unlink(p)
    n = r.get("reads_used") if isinstance(r, dict) else 0
    return n if isinstance(n, int) and n > 0 else 0


def _fresh(job: T.Job, req: dict) -> None:
    """Back to queued with a clean slate: what a person (or a push) asked for starts again; reads_used and the
    prior verdict stay, since the reads cap is per change family, not per queue. Only CARRY comes from `req`."""
    keep = {k: job.extra[k] for k in ("verdict",) + CARRY if k in job.extra}
    job.head = job.base_sha = job.digest = job.review_key = ""
    job.files, job.plan, job.results = [], None, {}
    job.extra = keep
    for k in CARRY:
        if req.get(k):
            job.extra[k] = req[k]
    job.extra.update(queued_at=E.stamp(), attempts=0)


def drain(repo: str) -> list:
    """Fold every inbox request for `repo` into its job. Call only under lane_lock(repo). Returns one line each.
    It takes rest_lock too (waiting: a settle holds it briefly), since a request may name a job the tick settles."""
    with rest_lock(repo, wait=True):
        return _drain(repo)


def _drain(repo: str) -> list:
    lines = []
    for path, req in requests(repo):
        pr = req["pr"]
        job, spent = load(repo, pr), take_carry(repo, pr)
        if job is None:
            job = T.Job(repo=repo, pr=pr, reads_used=spent)
            from lander import members as M
            h, t = M.member_of(repo)
            job.member = h if h and t else None
            job.extra = {k: req[k] for k in CARRY if req.get(k)}
            job.extra.update(queued_at=E.stamp(), attempts=0)
            job.history.append({"at": E.stamp(), "state": T.QUEUED})
            save(job)
            lines.append(f"{repo}#{pr} queued")
        elif job.state in (T.DONE, T.QUERY, T.HANDBACK) or (job.state == T.HELD and job.extra.get("hold") != "box"):
            _fresh(job, req)
            job.reads_used = max(job.reads_used, spent)
            move(job, T.QUEUED, why="requeued")
            E.log("requeued", repo, pr, who=req.get("who") or "-")
            lines.append(f"{repo}#{pr} requeued")
        else:
            for k in CARRY:
                if req.get(k) and not job.extra.get(k):
                    job.extra[k] = req[k]
            if job.state == T.CHECKING:   # lane.reread: a push mid-check is the commonest `again`
                job.extra["reread"] = True   # only a checking job reads it; any other `again` leaves the job as it was
            save(job)
            E.log("again", repo, pr)
            lines.append(f"{repo}#{pr} again")
        with contextlib.suppress(OSError):
            os.unlink(path)
    return lines


# --- lanes ---------------------------------------------------------------------------------------------------------

def lane_file(repo: str, ext: str) -> str:
    return f"{lanes_dir()}/{safe(repo)}.{ext}"


_HELD: dict = {}   # repo -> the fd on which this process holds lanes/<repo>.lock (records.Store checks it)


def lane_fd(repo: str):
    return _HELD.get(repo)


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


@contextlib.contextmanager
def rest_lock(repo: str, wait: bool = False):
    """`with rest_lock(r) as got:` — the lock on the jobs the lane has rested at deploy-pending or deployed. Taken
    after lane_lock when both are held (drain), never the other way round."""
    os.makedirs(lanes_dir(), exist_ok=True)
    fd = os.open(lane_file(repo, "settle"), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextlib.contextmanager
def lane_lock(repo: str, wait: bool = False):
    """`with lane_lock(r) as got:` — got is True when this process holds the repo's lane, False when another lane
    does (and wait=False). While held, <repo>.running names this pid; it is removed on the way out."""
    os.makedirs(lanes_dir(), exist_ok=True)
    fd = os.open(lane_file(repo, "lock"), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        write_atomic(lane_file(repo, "running"), {"pid": os.getpid(), "since": E.stamp(),
                                                  "release": running_release()})
        _HELD[repo] = fd
        try:
            yield True
        finally:
            _HELD.pop(repo, None)
            with contextlib.suppress(OSError):
                os.unlink(lane_file(repo, "running"))
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def running(repo: str) -> int:
    """The pid of the live lane for `repo`, or 0 (no marker, or its pid is gone)."""
    pid = (read_json(lane_file(repo, "running")) or {}).get("pid")
    return int(pid) if pid and pid_alive(pid) else 0


# --- listing -------------------------------------------------------------------------------------------------------

def job_files() -> list:
    return [p for p in glob.glob(f"{landq()}/*.json") if re.fullmatch(r".+-\d+\.json", os.path.basename(p))]


def first_path(repo: str, pr) -> str:
    return f"{landq()}/first/{safe(repo)}-{int(pr)}.json"


def put_first(repo: str, pr, by: str) -> None:
    """Put (repo, pr) at the front of its lane. Only `lander queue --first` calls this; cc-guard keeps that from
    workers, as it does every other lane-moving command."""
    os.makedirs(os.path.dirname(first_path(repo, pr)), exist_ok=True)
    write_atomic(first_path(repo, pr), {"by": by, "at": E.stamp()})


def drop_first(repo: str, pr) -> None:
    """Take (repo, pr)'s put-first record away: its job came to rest or was removed."""
    with contextlib.suppress(OSError):
        os.unlink(first_path(repo, pr))


def first(repo: str, pr) -> dict:
    """{by, at} when (repo, pr) was put first, else {}."""
    r = read_json(first_path(repo, pr))
    ok = isinstance(r, dict) and isinstance(r.get("by"), str) and E.epoch_of(r.get("at") or "")
    return {"by": r["by"], "at": r["at"]} if ok else {}


def arrival(job: T.Job) -> tuple:
    """The job's place in arrival order, put-first aside: oldest queued_at first, an unstamped one after every
    stamped one, a tie by path. lane.overlapping() reads "older" from it, so putting a job first never lets it pass
    an older job that shares its files."""
    at = E.epoch_of(job.extra.get("queued_at", ""))
    return (0, at, job_path(job.repo, job.pr)) if at else (1, 0, job_path(job.repo, job.pr))


def lane_jobs(repo: str) -> list:
    """`repo`'s jobs: those put first (oldest stamp first), then in arrival order."""
    got = []
    for p in job_files():
        j = load_path(p)
        if j is not None and j.repo == repo and os.path.basename(p) == f"{j.key}.json":
            put = E.epoch_of(first(repo, j.pr).get("at", ""))
            got.append(((0, put, p) if put else (1,) + arrival(j), j))
    return [j for _, j in sorted(got, key=lambda x: x[0])]


def all_repos() -> list:
    """Every repo with a job file or an inbox request."""
    seen = []
    for p in job_files():
        j = load_path(p)
        if j is not None and j.repo not in seen:
            seen.append(j.repo)
    for _, r in requests():
        if r["repo"] not in seen:
            seen.append(r["repo"])
    return seen


def not_before_left(job: T.Job, now=None) -> int:
    """Seconds until a held job may be tried again (0: now)."""
    at = E.epoch_of(job.extra.get("not_before", ""))
    return max(0, at - int(now if now is not None else time.time())) if at else 0
