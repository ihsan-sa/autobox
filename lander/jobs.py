"""Job files, the inbox, the lanes' locks and every path the lander keeps state under (review B4, S11).

PATHS are read from the environment at CALL time, so a test (or a second box layout) moves them all at once:
  LANDQ    $CC_LANDER_STATE or $HOME/.cc/state/land. THE DEFAULT IS THE LIVE QUEUE the old lander uses; nothing
           runs this lane against it until cutover (U5).
  jobs     <LANDQ>/<repo>-<pr>.json — today's path, so cc-slack's Home tab, cc-reconcile, the dashboard and the
           rest keep reading; each file keeps a `stage` key (STAGE_OF[state], the word they show) beside `state`.
  inbox    <LANDQ>/jobs/new/<repo>-<pr>.<pid>.<nonce>.json — what anyone may write (submit); only the lane, holding
           its repo's lock, folds a request into the job (drain). So the lane is the job file's one writer.
  lanes    <LANDQ>/lanes/<repo>.lock (flock) + <repo>.running {pid, since}; <LANDQ>/lanes/gh.backoff (gh.py).
  handed   <LANDQ>/handed/<repo>-<pr>.json — the watch on a handed-back PR (lane.handback, tick).
  log      <LANDQ>/queue.log (events.py).
  BIN $CC_BIN or <core>/bin · DEV $CC_DEV or $HOME/dev · BOARDS $CC_BOARDS or $HOME/.cc/boards ·
  MEMBERS $CC_MEMBERS or $HOME/.cc/members.
  repo_root: the board's `path` when it holds a .git, else DEV/<repo>; a member project <h>--<t> lands out of
  <LANDQ>/clones/<h>--<t>.

THE MACHINE. A job's `state` moves only along NEXT; move() refuses any other edge (ValueError), appends one
history entry, sets `stage`, saves atomically and writes `stage <repo>#<pr> <state>` to queue.log. Every save
sets `stage` from `state`, and the record is validated (T.Job.to_dict) before it is written.

DRAIN (the lane only, under the lane lock): a request with no job makes a queued job; one for a job at rest
(done, query, handback, or held for a reason a push mends) is a fresh start that keeps reads_used and the prior
verdict (`requeued`); one for an active job fills chat/ts/who where empty and an owner approval in it replaces
the job's (`again`). A job held by the box itself (hold="box": a usage wall, a cap, an unrunnable check) is
active: a fresh start would not mend it.
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


def handed_dir() -> str:
    return f"{landq()}/handed"


def clones_dir() -> str:
    return f"{landq()}/clones"


def safe(repo: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", repo)


def job_path(repo: str, pr) -> str:
    return f"{landq()}/{repo}-{int(pr)}.json"


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
    into a directory the member writes."""
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

STAGE_OF = {T.QUEUED: "queued", T.PLANNED: "plan", T.CHECKING: "gates", T.MERGEABLE: "merge", T.MERGED: "merged",
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


def load_path(path: str):
    d = read_json(path)
    if not isinstance(d, dict):
        return None
    try:
        return T.Job.from_dict(d)
    except ValueError:
        return None


def load(repo: str, pr):
    return load_path(job_path(repo, pr))


def save(job: T.Job) -> None:
    job.stage = STAGE_OF[job.state]
    write_atomic(job_path(job.repo, job.pr), job.to_dict())


def remove(job: T.Job) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(job_path(job.repo, job.pr))


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


CARRY = ("chat", "ts", "who")
APPROVAL = ("approved_by", "approved_head")


def _fresh(job: T.Job, req: dict) -> None:
    """Back to queued with a clean slate: what a person (or a push) asked for starts again; reads_used and the
    prior verdict stay, since the reads cap is per change family, not per queue."""
    keep = {k: job.extra[k] for k in ("verdict",) + CARRY if k in job.extra}
    job.head = job.base_sha = job.digest = job.review_key = ""
    job.files, job.plan, job.results = [], None, {}
    job.extra = keep
    for k in CARRY:
        if req.get(k):
            job.extra[k] = req[k]
    for k in APPROVAL:   # an approval was about the head it saw: only this request's counts
        if req.get(k):
            job.extra[k] = req[k]
    if "reads_used" in req:
        job.reads_used = max(job.reads_used, int(req["reads_used"] or 0))
    if req.get("verdict"):
        job.extra["verdict"] = req["verdict"]
    job.extra.update(queued_at=E.stamp(), attempts=0)


def drain(repo: str) -> list:
    """Fold every inbox request for `repo` into its job. Call only under lane_lock(repo). Returns one line each."""
    lines = []
    for path, req in requests(repo):
        pr = req["pr"]
        job = load(repo, pr)
        if job is None:
            job = T.Job(repo=repo, pr=pr, reads_used=int(req.get("reads_used") or 0))
            from lander import members as M
            h, t = M.member_of(repo)
            job.member = h if h and t else None
            job.extra = {k: req[k] for k in CARRY + APPROVAL + ("verdict",) if req.get(k)}
            job.extra.update(queued_at=E.stamp(), attempts=0)
            job.history.append({"at": E.stamp(), "state": T.QUEUED})
            save(job)
            lines.append(f"{repo}#{pr} queued")
        elif job.state in (T.DONE, T.QUERY, T.HANDBACK) or (job.state == T.HELD and job.extra.get("hold") != "box"):
            _fresh(job, req)
            move(job, T.QUEUED, why="requeued")
            E.log("requeued", repo, pr, who=req.get("who") or "-")
            lines.append(f"{repo}#{pr} requeued")
        else:
            for k in CARRY:
                if req.get(k) and not job.extra.get(k):
                    job.extra[k] = req[k]
            if req.get("approved_by") and req.get("approved_head"):
                job.extra.update(approved_by=req["approved_by"], approved_head=req["approved_head"])
            save(job)
            E.log("again", repo, pr)
            lines.append(f"{repo}#{pr} again")
        with contextlib.suppress(OSError):
            os.unlink(path)
    return lines


# --- lanes ---------------------------------------------------------------------------------------------------------

def lane_file(repo: str, ext: str) -> str:
    return f"{lanes_dir()}/{safe(repo)}.{ext}"


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


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
        write_atomic(lane_file(repo, "running"), {"pid": os.getpid(), "since": E.stamp()})
        try:
            yield True
        finally:
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


def lane_jobs(repo: str) -> list:
    """`repo`'s jobs, oldest queued_at first (an unstamped one after every stamped one, then by path)."""
    got = []
    for p in job_files():
        j = load_path(p)
        if j is not None and j.repo == repo and os.path.basename(p) == f"{j.key}.json":
            at = E.epoch_of(j.extra.get("queued_at", ""))
            got.append(((0, at, p) if at else (1, 0, p), j))
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
