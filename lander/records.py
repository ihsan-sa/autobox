"""What a run leaves behind: the result store, the failures-ledger record of a red, and the quarantine list (S12).

THE STORE, under the landing state dir (LANDER_STATE, default ~/.cc/state/land):
  jobs/<repo>-<pr>/results/<check>/<tree>.json   one job's own runs; read back only by that job
  results/<check>/<tree>.json                    base-tree runs the lane made, the only runs another job may reuse
Only the lane writes either (S12): a Store opened with the lane's lock fd refuses to write unless that fd still holds
`lanes/<repo>.lock`. A shared run is stamped with this release and the lane's nonce (`lanes/<repo>.nonce`, made fresh
by new_nonce() when a lane starts), and base() returns it only when both still match — a record left by an older
release, an earlier lane or anything else is not reused. THE RESIDUAL, stated: a process running as this same user
can read the nonce and forge a record; the store keeps honest mistakes and old runs out, not a hostile same-uid
writer. A worker's own `lander check` writes nothing here.

A RED goes to the failures ledger once per check and tree (cc-failures record --once, links.source
gate:<check>:<tree12>, kind gate-verdict/red), the key cc-green uses, so it is one record whoever saw it first. The
write never decides anything: a failure to write is a line in the answer, not an exception.

QUARANTINE is `<prefix>tests/quarantine`, read from the base: `<tool><TAB><text>\t<why>\t<owner>\t<YYYY-MM-DD>`. A row
counts when its date is a real date, not past, and at most 60 days out. Its tool is a check name or the name of the
tool a check owns.
"""
from __future__ import annotations

import datetime
import fcntl
import json
import os
import re
import secrets
import subprocess
import threading

from lander import types as T

QUARANTINE, QUARANTINE_DAYS = "tests/quarantine", 60


def state_dir() -> str:
    return os.environ.get("LANDER_STATE") or os.path.expanduser("~/.cc/state/land")


def release() -> str:
    """The pinned release's name (current -> releases/<sha>), or `dev` for a checkout."""
    here = os.path.realpath(__file__)
    cur = os.path.realpath(os.path.expanduser("~/.cc/lander/current"))
    return os.path.basename(cur) if here.startswith(cur + os.sep) else "dev"


def _write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"   # the lane's checks write from several threads
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _read(path: str):
    try:
        with open(path) as f:
            return T.Result.from_dict(json.load(f))
    except (OSError, ValueError):
        return None


def _safe(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", name or ""):
        raise ValueError(f"not a safe name for a record path: {name!r}")
    return name


def new_nonce(repo: str, root: str | None = None) -> str:
    """The lane calls this once when it starts: every shared record an earlier lane made stops being reused."""
    root = root or state_dir()
    p = os.path.join(root, "lanes", f"{_safe(repo)}.nonce")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    n = secrets.token_hex(16)
    fd = os.open(f"{p}.tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(n)
    os.replace(f"{p}.tmp", p)
    return n


def nonce(repo: str, root: str | None = None) -> str:
    try:
        with open(os.path.join(root or state_dir(), "lanes", f"{_safe(repo)}.nonce")) as f:
            return f.read().strip()
    except OSError:
        return ""


class NotTheLane(PermissionError):
    pass


class Store:
    """repo: the lane's repo. lock_fd: the open fd on which the lane holds lanes/<repo>.lock; None = read-only."""

    def __init__(self, repo: str, lock_fd=None, root: str | None = None):
        self.repo, self.lock_fd, self.root = _safe(repo), lock_fd, root or state_dir()
        self.release = release()

    def job_path(self, job_key: str, check: str, tree: str) -> str:
        return os.path.join(self.root, "jobs", _safe(job_key), "results", _safe(check), f"{_safe(tree)}.json")

    def shared_path(self, check: str, tree: str) -> str:
        return os.path.join(self.root, "results", _safe(check), f"{_safe(tree)}.json")

    def _lane(self) -> None:
        if self.lock_fd is None:
            raise NotTheLane("this store is read-only: only the lane writes results")
        try:   # flock on the lane's own open file description succeeds again; another holder makes it fail
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise NotTheLane(f"the fd given does not hold the lane lock for {self.repo}: {e}") from None

    def put(self, job_key: str, r: T.Result) -> str:
        self._lane()
        p = self.job_path(job_key, r.check, r.tree)
        _write(p, r.to_dict())
        return r.key

    def get(self, job_key: str, check: str, tree: str):
        return _read(self.job_path(job_key, check, tree))

    def put_base(self, r: T.Result) -> str:
        """A base-tree run, shared with every job that waits on the same base; stamped release + nonce."""
        self._lane()
        r.release, r.nonce = self.release, nonce(self.repo, self.root)
        if not r.nonce:
            raise NotTheLane(f"no lane nonce for {self.repo}: new_nonce() runs when the lane starts")
        _write(self.shared_path(r.check, r.tree), r.to_dict())
        return r.key

    def base(self, check: str, tree: str):
        r = _read(self.shared_path(check, tree))
        n = nonce(self.repo, self.root)
        return r if r and n and r.release == self.release and r.nonce == n else None


# --- the failures ledger -------------------------------------------------------------------------------------------

def record_red(scope: str, r: T.Result, text: str, pr: int | None = None, log: str = "", bin_dir: str = "") -> str:
    """One gate-verdict/red record for check r.check on tree r.tree. Returns a one-line word, never raises."""
    exe = os.path.join(bin_dir, "cc-failures") if bin_dir else os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin", "cc-failures")
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    red = [c.get("name", "") for c in r.cases if c.get("status") == T.FAILED] or lines[-3:]
    argv = [exe, "record", "--once", "--scope", scope, "--kind", "gate-verdict/red",
            "--observed", (f"check {r.check} did not pass at the landing of {scope}{f' PR #{pr}' if pr else ''} "
                           f"on {r.tree[:12]}: " + " · ".join(red[:3]))[:600],
            "--expected", "a tree handed over passes its checks", "--writer", "lander", "--detector", "box",
            "--detector-evidence", "lander saw it", "--cost", "fix-iteration=1",
            "--link", f"source=gate:{r.check}:{r.tree[:12]}", "--link", f"gate={r.check}", "--link", f"tree={r.tree}"]
    argv += (["--link", f"pr={pr}"] if pr else []) + (["--link", f"log={log}"] if log else [])
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        last = (p.stdout.strip().splitlines() or p.stderr.strip().splitlines() or [""])[-1]
        return f"recorded {last}" if p.returncode == 0 else f"not recorded: cc-failures exited {p.returncode}: {last}"
    except (OSError, subprocess.SubprocessError) as e:
        return f"not recorded: {type(e).__name__}: {e}"


# --- quarantine ----------------------------------------------------------------------------------------------------

def quarantine_rows(text: str, today: datetime.date | None = None) -> list:
    """The rows that count today: [(tool, text)]."""
    today = today or datetime.date.today()
    out = []
    for line in (text or "").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) < 5 or not f[0] or not f[1]:
            continue
        try:
            exp = datetime.date.fromisoformat(f[4].strip())
        except ValueError:
            continue
        if today <= exp <= today + datetime.timedelta(days=QUARANTINE_DAYS):
            out.append((f[0], f[1]))
    return out


def quarantined(check: T.Check, red_lines: list, rows: list) -> bool:
    """Every red line this check reported carries the text of a row for this check (or for a tool it owns)."""
    tools = {check.name} | {p.rsplit("/", 1)[-1] for p in check.paths if "*" not in p}
    texts = [t for tool, t in rows if tool in tools]
    return bool(red_lines) and bool(texts) and all(any(t in ln for t in texts) for ln in red_lines)
