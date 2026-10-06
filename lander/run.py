"""run(): one check on one tree, safely; judge(): what a red means (design §0 Execution, Red main vs red diff; B2, B5).

THE TREE. A run never touches a checkout. materialise() writes the tree's files out of git into
`$TMPDIR/cc-land.run.<pid>.<rand>/cc-land.gates.<repo>.<pr>.<rand>/head` (the shape cc-tmp-reap and `cc-sandbox member
--tree` accept), makes it a git repo with one commit and proves `git write-tree` there equals the tree asked for
(B1: the identity check greps a real work tree). The files are read out of the checkout's objects in a borrowed repo
(git.borrowed) and every git there runs with git.blind_env(), so no config, attributes, filter or replace ref of the
checkout's runs or shapes them. Everything under the run directory goes when the run ends.

THE RUNNER (`where`, one of the check's own `where` list, or `member:<h>[:<t>]` for a member's landing):
  box      by class — static, hermetic and timing in the bwrap profile (sandbox.py); host and box on the host with
           the environment scrubbed as today's clean_start (no CLAUDE*, no token-shaped variables, CC_CONFIG_DENY set).
           Every one inside an admission slot and a transient scope (admission.py). Timing runs only while the box
           is not loaded. No bwrap on this machine makes a sandboxed class unrunnable, never a host run.
  laptop   static, hermetic and host (never box or timing), over cc-suites' own transport: its key, the
           destination and the pinned host key in ~/.cc/suites (CC_SUITES_DIR: id_ed25519, remote, known_hosts,
           StrictHostKeyChecking=yes), so the laptop is configured exactly when cc-suites' runner is, and a destination known_hosts does not name is refused
           before ssh starts. The tree goes to the runner's `job` form (`cc-suites runner`, the key's forced command),
           which unpacks it into a fresh directory with a fresh HOME per job, proves it by write-tree, runs it caged
           (writable only in that directory, and with no network unless the check says net = true, which goes as
           the job's trailing `net`; cc-suites, THE CAGE) and removes both; `lander job-serve` hands
           the same job to it. Busy, unfit or not answering is
           unrunnable there, never red, and judge() then runs the check on the box. A host check's line goes with
           HOST_PREP in front: what a box has and a fresh account does not (a tmux session `main`, of a server of
           the job's own, and a waiting ~/.local/bin/claude), as `cc-suites runner` gives a whole suite, so the
           e2e suites and check.sh can run there. A check that needs this box's own host keeps `where = ["box"]`.
  member   `cc-sandbox member <h> <t> --tree <head> -- env … /bin/sh -c <run>`, the workspace's own boundary (B5).

THE STATUS. passed: exit 0 and no `N failed` with N > 0 in the output (a suite that says "1 failed" failed whatever
it exited with). unrunnable — never red: killed at the check's cap, killed by a signal or the scope's MemoryMax
(exit 124, 137, 143 or a signal), a box-state message (disk, quota, memory, fork), a sandbox that did not start, a
mount that is not there, a tree that did not reproduce. failed: anything else.

JUDGE (a red, per check): the same check on the BASE tree — the lane's shared record when there is one — red there
too is `blocked-by-main` (main is red, the diff is not blamed); a check the base does not define, or whose run file
the base lacks, has no base run and its red is the diff's; a red run under load, on either tree, gets ONE diagnostic
rerun alone (every slot held), and only a base run that stands is shared; green alone passes with a `flaky` note;
a red whose every red line matches a live quarantine row passes with a `quarantined` note — never for a check that
guards a gate-first path, and never when the change touches the check itself; what is left is `failed`, and goes to
the failures ledger once (records.record_red).

A RED KEEPS ITS LOG. A failed run's output (read_log's bound) is copied to <state>/logs/ (records.state_dir, never
/tmp) before run_dir goes, at most LOG_KEEP files and none older than LOG_DAYS; the result's extra carries `log` (the
path) and `cause` (cause_of: pytest's FAILED line, an INTERNALERROR with the file that went F, the first red line, or
"no failing line" with the last line said), and its `why` ends with the cause.
"""
from __future__ import annotations

import base64
import contextlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field

from lander import admission as A
from lander import git as G
from lander import manifest as M
from lander import records as REC
from lander import sandbox as S
from lander import types as T

FAILED_RE = re.compile(r"(\d+) failed")
BOX_STATE_RE = re.compile(r"Disk quota exceeded|No space left on device|Cannot allocate memory|fork: retry"
                          r"|Resource temporarily unavailable")
SETUP_RE = re.compile(r"^(bwrap:|systemd-run:|Failed to start transient scope"
                      r"|Failed to connect to (user )?(scope )?bus).*", re.M)
RED_RE = re.compile(r"✗|✘|FAIL|Error\b|error:|not ok|Traceback")
PASS_RE = re.compile(r"^\W*[✓✔]|^\s*(?:ok|pass(?:ed)?)\b", re.I)
KILLED = (124, 137, 143)
SECRET_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
SECRET_SUFFIXES = ("_TOKEN", "_KEY", "_SECRET", "_CREDS", "_WEBHOOK", "_PASSWORD")
BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin")
TAIL = 40
LOG_KEEP, LOG_DAYS = 200, 7   # a red's kept log (keep_log): at most this many, none older than this many days
BLOCKED = "blocked-by-main"


class Unrunnable(RuntimeError):
    pass


# --- the tree ------------------------------------------------------------------------------------------------------

def materialise(repo_root: str, tree: str, label: str = "lander.0") -> tuple:
    """-> (run_dir, head_dir). Raises Unrunnable when the tree cannot be written out exactly."""
    if not re.fullmatch(r"[0-9a-f]{40}", tree or ""):
        raise Unrunnable(f"not a tree id: {tree!r}")
    run_dir = tempfile.mkdtemp(prefix=f"cc-land.run.{os.getpid()}.", dir=os.environ.get("TMPDIR") or "/tmp")
    try:
        gates = tempfile.mkdtemp(prefix=f"cc-land.gates.{label}.", dir=run_dir)
        head = os.path.join(gates, "head")
        os.mkdir(head)
        with G.borrowed(repo_root) as scratch:
            # borrowed: the checkout's attributes, config (a filter's smudge, run as the lander) and replace refs
            # are not read; its objects are, through alternates, and write-tree below proves what came out of them
            genv = dict(G.blind_env(), GIT_DIR=scratch, GIT_INDEX_FILE=os.path.join(run_dir, "index"),
                        GIT_WORK_TREE=head, GIT_NO_REPLACE_OBJECTS="1")
            for argv in (["git", "read-tree", tree], ["git", "checkout-index", "-a", "-f", f"--prefix={head}/"]):
                p = subprocess.run(argv, env=genv, cwd=scratch, capture_output=True, text=True)
                if p.returncode:
                    raise Unrunnable(f"could not write the tree out: {p.stderr.strip()[-300:]}")
            # a submodule (gitlink) is written out as an empty directory, which add cannot turn back into the link;
            # it has no files to prove, so it is taken from the tree itself (a repo with a submodule was never
            # runnable)
            ls = subprocess.run(["git", "ls-tree", "-r", "-z", tree], env=genv, cwd=scratch, capture_output=True,
                                text=True)
        if ls.returncode:
            raise Unrunnable(f"could not list the tree: {ls.stderr.strip()[-300:]}")
        # the new repo's own git reads no config but these two, and no attributes of anyone's
        g = ["git", "-C", head, "-c", "user.name=lander", "-c", "user.email=lander@localhost"]
        henv = G.blind_env()
        subprocess.run(g + ["init", "-q", "--template="], env=henv, check=True, capture_output=True)
        subprocess.run(g + ["add", "-A", "-f"], env=henv, check=True, capture_output=True)
        for ent in ls.stdout.split("\0"):
            meta, _, path = ent.partition("\t")
            if meta.startswith("160000 commit "):
                subprocess.run(g + ["update-index", "--add", "--cacheinfo", f"160000,{meta.split()[2]},{path}"],
                               env=henv, check=True, capture_output=True)
        got = subprocess.run(g + ["write-tree"], env=henv, capture_output=True, text=True).stdout.strip()
        if got != tree:
            raise Unrunnable(f"the tree written out is {got or 'none'}, not {tree}")
        subprocess.run(g + ["commit", "-qm", f"tree {tree}", "--no-verify"], env=henv, check=True, capture_output=True)
        return run_dir, head
    except (Unrunnable, OSError, subprocess.CalledProcessError, G.GitError) as e:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise e if isinstance(e, Unrunnable) else Unrunnable(f"could not write the tree out: {e}") from None


def tree_of(repo_root: str, rev: str) -> str:
    """The tree id of a commit or tree; rev "" is the working copy (tracked and untracked, not ignored)."""
    if rev:   # read VERIFIED (git.tree_of): a replace ref in the checkout would name another commit's tree
        try:
            return G.tree_of(repo_root, rev)
        except G.GitError:
            return ""
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(d, "index")}
        top = subprocess.run(["git", "-C", repo_root, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode:
            return ""
        for argv in (["git", "-C", top.stdout.strip(), "read-tree", "HEAD"],
                     ["git", "-C", top.stdout.strip(), "add", "-A"]):
            if subprocess.run(argv, env=env, capture_output=True).returncode:
                return ""
        return subprocess.run(["git", "-C", top.stdout.strip(), "write-tree"], env=env, capture_output=True,
                              text=True).stdout.strip()


# --- executing -----------------------------------------------------------------------------------------------------

def clean_env(extra: dict | None = None) -> dict:
    """Today's clean_start: the session's CLAUDE* gone, token-shaped variables gone, the live config denied."""
    env = {k: v for k, v in os.environ.items()
           if k != "CLAUDECODE" and not k.startswith("CLAUDE_") and k not in SECRET_ENV
           and not k.endswith(SECRET_SUFFIXES)}
    env["CC_CONFIG_DENY"] = os.path.realpath(os.path.expanduser("~/.cc/config"))
    env.update(extra or {})
    return env


_STOP = threading.local()   # .event: run_plan's `cancel`, for every execute() on the thread that runs the plan


def stopped() -> bool:
    ev = getattr(_STOP, "event", None)
    return bool(ev is not None and ev.is_set())


def execute(argv: list, cwd: str, env: dict, cap: int, log: str, stdin=None) -> tuple:
    """-> (rc, secs, cpu_secs, capped). Its own session, so the cap kills the whole group; rc < 0 is a signal.
    A plan's `cancel` set (the lane: the job's PR merged, closed or moved on) kills the group the same way, and a
    stopped plan starts nothing more: rc -SIGTERM, which status_of calls unrunnable, never red."""
    t0 = time.monotonic()
    if stopped():
        return -signal.SIGTERM, 0.0, 0.0, False
    with open(log, "wb") as out:
        p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                             stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
                             preexec_fn=None, restore_signals=True)
    capped, ru = False, None
    while True:
        pid, status, ru = os.wait4(p.pid, os.WNOHANG)
        if pid:
            rc = os.waitstatus_to_exitcode(status)
            break
        if time.monotonic() - t0 > cap or stopped():
            capped = not stopped()
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(p.pid, sig)
                except ProcessLookupError:
                    pass
                time.sleep(2)
            _, status, ru = os.wait4(p.pid, 0)
            rc = os.waitstatus_to_exitcode(status)
            break
        time.sleep(0.2)
    p.returncode = rc
    try:   # anything the check left behind in its group goes with it
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    cpu = (ru.ru_utime + ru.ru_stime) if ru else 0.0
    return rc, time.monotonic() - t0, cpu, capped


def read_log(log: str, limit: int = 400_000) -> str:
    try:
        with open(log, "rb") as f:
            f.seek(max(0, os.path.getsize(log) - limit))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def status_of(rc: int, text: str, capped: bool = False) -> tuple:
    """-> (status, why)."""
    if capped:
        return T.UNRUNNABLE, "stopped at its cap"
    if rc < 0 or rc in KILLED:
        return T.UNRUNNABLE, f"killed (exit {rc})"
    m = BOX_STATE_RE.search(text)
    if m:
        return T.UNRUNNABLE, f"the box, not the tree: {m.group(0)}"
    head = text.lstrip()[:2000]
    s = SETUP_RE.match(head)
    if rc and s:
        return T.UNRUNNABLE, f"the sandbox did not start: {s.group(0)[:200]}"
    n = [int(x) for x in FAILED_RE.findall(text)]
    if rc == 0 and not (n and n[-1] > 0):
        return T.PASSED, ""
    return T.FAILED, f"exit {rc}" + (f", {n[-1]} failed" if n and n[-1] else "")


def red_lines(text: str) -> list:
    return [ln.strip() for ln in text.splitlines() if RED_RE.search(ln) and not PASS_RE.search(ln)]


# pytest's own words for what failed: its short summary, pytest itself falling over, and a file whose progress has F/E
SUMMARY_RE = re.compile(r"^(?:FAILED|ERROR) \S+.*$", re.M)
INTERNAL_RE = re.compile(r"^INTERNALERROR> .*\b\w+(?:Error|Exception)\b.*$", re.M)
PROGRESS_RE = re.compile(r"^(\S+\.py) [.sxX]*[FE][.sxXFE]*(?:\s+\[\s*\d+%\])?$", re.M)


def cause_of(text: str, rc: int) -> str:
    """One line naming why a run is red, read from its WHOLE output, not the tail (2026-09/10: an INTERNALERROR, a
    failing check.sh line above the tail and an all-pass tail each left a red nobody could name)."""
    def more(got, what="more"):
        return f" (+{len(got) - 1} {what})" if len(got) > 1 else ""
    summary, internal, progress = SUMMARY_RE.findall(text), INTERNAL_RE.findall(text), PROGRESS_RE.findall(text)
    if summary:
        return summary[0].strip()[:300] + more(summary)
    if internal:   # the innermost frame is the last; the file whose progress went F is where it happened
        return (internal[-1].strip()[:300]
                + (f", after a failure in {progress[0]}" + more(progress, "more files") if progress else ""))
    if progress:
        return f"a failure in {progress[0]}" + more(progress, "more files")
    red = red_lines(text)
    if red:
        return red[0][:300] + more(red, "more red lines")
    last = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), "")
    return (f"exit {rc} with no failing line in the output — it ends: {last[:200]!r}" if last
            else f"exit {rc} with no output at all")


def logs_dir(state: str | None = None) -> str:
    return os.path.join(state or REC.state_dir(), "logs")


def keep_log(text: str, check: str, tree: str, state: str | None = None) -> str:
    """A red's output (already bounded: read_log's limit) under the lander's state, then the old ones pruned: none
    older than LOG_DAYS, at most LOG_KEEP. -> the path, '' when it could not be written."""
    d = logs_dir(state)
    try:
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{re.sub(r'[^\w.-]', '_', check)}"
                               f"-{tree[:12]}-{os.getpid()}.log")
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(text)
    except OSError:
        return ""
    prune_logs(d)
    return path


def prune_logs(d: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    try:
        logs = sorted((e for e in os.scandir(d) if e.name.endswith(".log") and e.is_file()),
                      key=lambda e: e.stat().st_mtime, reverse=True)
    except OSError:
        return
    for i, e in enumerate(logs):
        with contextlib.suppress(OSError):
            if i >= LOG_KEEP or now - e.stat().st_mtime > LOG_DAYS * 86400:
                os.unlink(e.path)


# --- the runners ---------------------------------------------------------------------------------------------------

def _box_argv(check, head, cwd, run_dir, env_extra):
    if check.klass in M.UNSANDBOXED:
        return ["/bin/sh", "-c", check.run], os.path.join(head, cwd) if cwd else head, clean_env(env_extra), "host"
    if not S.available():
        raise Unrunnable("bwrap is not installed, so a sandboxed check has nowhere to run")
    if check.klass == T.TIMING and A.loaded():
        raise Unrunnable("box busy: a timing check waits for an idle box")
    try:
        argv = S.argv(check, head, S.write_stub(run_dir), cwd, env_extra)
    except S.MissingMount as e:
        raise Unrunnable(str(e)) from None
    # bwrap clears the environment inside; outside, systemd-run still needs the user bus to open the scope
    outer = {k: os.environ[k] for k in ("PATH", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS") if k in os.environ}
    outer.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return argv, head, outer, "bwrap"


def _member_argv(check, head, cwd, where, env_extra):
    parts = where.split(":")
    h, t = parts[1], (parts[2] if len(parts) > 2 else "")
    inner = f"cd {cwd} && {check.run}" if cwd else check.run
    argv = [os.path.join(BIN, "cc-sandbox"), "member", h, t, "--tree", head, "--", "env"]
    argv += [f"{k}={v}" for k, v in (env_extra or {}).items()] + ["/bin/sh", "-c", inner]
    return argv, head, clean_env(), "member"


def _suites_dir() -> str:
    return os.environ.get("CC_SUITES_DIR") or os.path.expanduser("~/.cc/suites")


def laptop_dest() -> str:
    """cc-suites' runner (user@host) when its key, destination and pinned host key are all there, else ''."""
    d = _suites_dir()
    try:
        with open(os.path.join(d, "remote")) as f:
            dest = "".join(f.readline().split())
    except OSError:
        return ""
    ok = all(os.path.isfile(p) and os.path.getsize(p) for p in (os.path.join(d, "id_ed25519"),
                                                                 os.path.join(d, "known_hosts")))
    return dest if ok and re.fullmatch(r"[A-Za-z0-9._-]+@[A-Za-z0-9._-]+", dest) else ""


# A host check's box on the laptop: a tmux server under the job's TMPDIR (so it is gone with the job, and never
# some other server's `main`), killed when the check ends, and a claude that only waits (every model call a suite
# makes is stubbed by the suite itself), and the user runtime dir systemd-analyze --user needs (check.sh units),
# which an `env -i` job drops. The check runs in a subshell, so its own `exit` still reaches the trap.
HOST_PREP = ('unset TMUX; TMUX_TMPDIR="${TMPDIR:-/tmp}/tmux"; export TMUX_TMPDIR; '
             '[ -n "${XDG_RUNTIME_DIR:-}" ] || { XDG_RUNTIME_DIR="/run/user/$(id -u)"; [ -d "$XDG_RUNTIME_DIR" ] '
             '&& export XDG_RUNTIME_DIR || unset XDG_RUNTIME_DIR; }; '
             'mkdir -p "$TMUX_TMPDIR" "$HOME/.local/bin" && chmod 700 "$TMUX_TMPDIR"; '
             '[ -e "$HOME/.local/bin/claude" ] || { printf \'#!/bin/sh\\nexec sleep 3600\\n\' >"$HOME/.local/bin/claude" '
             '&& chmod +x "$HOME/.local/bin/claude"; }; '
             "trap 'tmux kill-server 2>/dev/null' EXIT; tmux new-session -d -s main -x 200 -y 50 2>/dev/null\n")


def laptop_argv(check, tree, cwd):
    dest = laptop_dest()
    if not dest:
        raise Unrunnable(f"no laptop is configured (cc-suites: {_suites_dir()})")
    if check.klass not in (T.STATIC, T.HERMETIC, T.HOST):
        raise Unrunnable(f"a {check.klass} check does not leave the box")
    # ssh joins argv with spaces and the runner reads one line, so a name carrying a newline could hand the laptop
    # a job of its own making (`net` included): the name must be one the runner and the records accept
    try:
        REC._safe(check.name)
    except ValueError:
        raise Unrunnable(f"not a check name the laptop takes: {check.name!r}") from None
    d = _suites_dir()
    kh, host = os.path.join(d, "known_hosts"), dest.split("@", 1)[1]
    with open(kh) as f:
        pinned = {h for ln in f if ln.strip() and not ln.startswith("#") for h in ln.split()[0].split(",")}
    if host not in pinned:
        raise Unrunnable(f"the laptop {host} has no pinned host key in {kh}")
    b = lambda s: base64.b64encode(s.encode()).decode() or "-"   # noqa: E731
    # cc-suites xport_argv's options, so this is the path the owner approved and no other
    argv = ["ssh", "-F", "/dev/null", "-i", os.path.join(d, "id_ed25519"), "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=4", "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={kh}",
            "-o", "GlobalKnownHostsFile=/dev/null", "-o", "ClearAllForwardings=yes",
            "-o", "KexAlgorithms=curve25519-sha256", "-a", "-x", "-T", "-C", dest, "--",
            "job", check.name, tree, str(check.cap), b(HOST_PREP + f"(\n{check.run}\n)" if check.klass == T.HOST
                                                      else check.run), b(cwd)] + (["net"] if check.net else [])
    # a word with whitespace in it would split or add a line on the far side: it goes as it is or not at all
    bad = next((w for w in argv if re.search(r"\s", w)), None)
    if bad is not None:
        raise Unrunnable(f"a laptop argv word carries whitespace: {bad!r}")
    return argv


def run(check: T.Check, tree_sha: str, where: str = "box", *, repo_root: str = ".", cwd: str = "",
        label: str = "lander.0", changed: list | None = None, alone: bool = False, base_tree: str = "",
        state: str | None = None) -> T.Result:
    """Runner.run. Runs `check` on `tree_sha` (read from repo_root's git) at `where`, holding an admission slot
    (every slot, alone=True). Stores nothing: the lane stores what it wants (records.Store). cwd: the check's
    manifest prefix. changed: the change's files, handed in as CC_LAND_CHANGED. base_tree: the other side, for the
    built-in manifest-widen."""
    t0 = time.monotonic()

    def res(st, why, **kw):
        return T.Result(check=check.name, tree=tree_sha, status=st, secs=time.monotonic() - t0,
                        load=os.getloadavg()[0], runner=kw.pop("runner", where), extra={"why": why, **kw})

    kind = where.split(":")[0]
    if kind not in {w.split(":")[0] for w in check.where} | {"member"}:
        return res(T.UNRUNNABLE, f"{where!r} is not one of this check's runners ({', '.join(check.where)})")
    if check.name == M.BUILTIN:
        if not base_tree:
            return res(T.UNRUNNABLE, "manifest-widen needs the base tree")
        ok, text = M.widen_check(repo_root, base_tree, tree_sha)
        return res(T.PASSED if ok else T.FAILED, "" if ok else "the head narrows the manifest", runner="builtin",
                   tail=text.splitlines()[-TAIL:])
    env_extra = {"CC_LAND_CHANGED": " ".join(changed)} if changed else {}
    try:
        run_dir, head = materialise(repo_root, tree_sha, label)
    except Unrunnable as e:
        return res(T.UNRUNNABLE, str(e))
    log = os.path.join(run_dir, "log")
    try:
        stdin, tar = None, None
        if kind == "laptop":
            argv, wd, env, how = laptop_argv(check, tree_sha, cwd), run_dir, clean_env(), "laptop"
            tar = subprocess.Popen(["tar", "-C", head, "-cf", "-", "."], stdout=subprocess.PIPE)
            stdin = tar.stdout
        elif kind == "member":
            argv, wd, env, how = _member_argv(check, head, cwd, where, env_extra)
        else:
            argv, wd, env, how = _box_argv(check, head, cwd, run_dir, env_extra)
        scope = "-"
        # the laptop's work is the laptop's: it takes no slot of the box's
        held = contextlib.nullcontext() if kind == "laptop" else A.slot(state or REC.state_dir(), alone=alone,
                                                                            who=f"{check.name}@{tree_sha[:8]}")
        with held:
            loaded = A.loaded()
            if kind == "box":   # wrapped once the slot is held, so the priority answers for the load it starts under
                argv, scope = A.wrap(check, argv, f"{check.name}-{tree_sha[:8]}", busy=bool(A.overloaded()))
            rc, secs, cpu, capped = execute(argv, wd, env, check.cap, log, stdin)
            loaded = loaded or A.loaded()   # under load at either end of the run
        if tar is not None:
            tar.stdout.close()
            tar.wait()
        text = read_log(log)
        if kind == "laptop":
            text, rc = _laptop_verdict(text, rc)
        st, why = status_of(rc, text, capped)
        if kind == "laptop" and rc == -1:
            why = text.splitlines()[0] if text else "the laptop did not answer"
        kept = {}
        if st == T.FAILED:   # the log outlives run_dir, and the result names the line that failed
            kept = {"cause": cause_of(text, rc), "log": keep_log(text, check.name, tree_sha, state)}
            why = f"{why}: {kept['cause']}"
        return T.Result(check=check.name, tree=tree_sha, status=st, secs=round(secs, 2), cpu_secs=round(cpu, 2),
                        load=os.getloadavg()[0], runner=f"{where}:{how}:{scope}",
                        cases=[{"name": ln[:200], "status": T.FAILED} for ln in red_lines(text)[:50]]
                        if st == T.FAILED else [],
                        extra={"why": why, "rc": rc, "loaded": loaded, "alone": alone,
                               "tail": text.splitlines()[-TAIL:], **kept})
    except Unrunnable as e:
        return res(T.UNRUNNABLE, str(e))
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def _laptop_verdict(text: str, rc: int) -> tuple:
    """job-serve relays the check's lines as `| …` and ends `lander-job: verdict exit=N`; anything else is no
    answer (-1: unrunnable). The runner ends every relayed line with a newline, so the split is on "\n" alone (not
    splitlines, which also breaks on \r, \x0b, \x85, \u2028…), and the verdict is the one such line and the last."""
    lines = text.split("\n")
    body = "\n".join(ln[2:] for ln in lines if ln.startswith("| "))
    got = [ln for ln in lines if "lander-job: verdict" in ln and not ln.startswith("| ")]
    last = next((ln for ln in reversed(lines) if ln.strip()), "")
    m = re.fullmatch(r"lander-job: verdict exit=([0-9]{1,3})", last)
    if rc != 0 or len(got) != 1 or not m:
        refused = next((ln for ln in lines if ln.strip() and not ln.startswith("| ")), "no answer")
        return f"laptop refused or did not answer: {refused[:200]}\n{body}", -1
    return body, int(m.group(1))


# --- the laptop's end ----------------------------------------------------------------------------------------------

def cmd_job_serve(argv):
    """The laptop's forced command in Python: `job CHECK TREE CAP RUN_B64 CWD_B64 [net]` from SSH_ORIGINAL_COMMAND (or
    argv), the tree as a tar on stdin. It hands the job to `cc-suites runner` and takes nothing else, so a job has one
    runner and one cage: its own directory writable, the runner and its account read-only (cc-suites, THE CAGE)."""
    cmd = os.environ.get("SSH_ORIGINAL_COMMAND") or " ".join(argv)
    # the runner reads one line: a job is one line, or it is refused whole
    if "\n" in cmd or "\r" in cmd or cmd.split()[:1] != ["job"]:
        print("lander-job: refused: job CHECK TREE CAP RUN_B64 CWD_B64 [net]")
        return 2
    p = subprocess.run(["bash", os.path.join(BIN, "cc-suites"), "runner"], stdin=sys.stdin.buffer,
                       stdout=subprocess.PIPE, env={**os.environ, "SSH_ORIGINAL_COMMAND": cmd})
    sys.stdout.write(p.stdout.decode(errors="replace"))
    return p.returncode


# --- judging a red -------------------------------------------------------------------------------------------------

@dataclass
class Outcome:
    """status: passed, failed, unrunnable or blocked-by-main. note: flaky / quarantined / why. results: the Result
    of each run made, head first."""
    check: str
    status: str
    note: str = ""
    results: list = field(default_factory=list)


def judge(check: T.Check, head_tree: str, base_tree: str, where: str = "box", *, runner=None, store=None,
          job_key: str = "", security: bool = False, touched: bool = False, quarantine: list = (),
          record=None, on_base: bool = True, **run_kw) -> Outcome:
    """What one check says about a change. runner defaults to run(); store (records.Store, the lane's) keeps each
    run and shares base runs; record(result, text) is called once for a red that is the diff's. on_base=False: the
    base tree has no such check or not its run file, so there is no base run and a red is the diff's."""
    runner = runner or run
    kw = {**run_kw, "base_tree": base_tree}

    def go(tree, alone=False, base=False, keep=True):
        # once the box has taken a check over, every later run of it (alone, base) stays on the box: a laptop pass
        # must never overturn a box red
        nonlocal where
        r = runner(check, tree, where, alone=alone, **kw)
        # a laptop that cannot take it (busy, gone) is no answer: the box runs it, as cc-suites spill did
        if where == "laptop" and r.status == T.UNRUNNABLE and "box" in check.where:
            why = r.extra.get("why", "")
            r = runner(check, tree, "box", alone=alone, **kw)
            r.extra["laptop"] = why
            where = "box"
        # a laptop red is not final: its python and shellcheck are older than the box's, so the box says it again
        elif where == "laptop" and r.status == T.FAILED and "box" in check.where:
            why = r.extra.get("why", "")
            r = runner(check, tree, "box", alone=alone, **kw)
            r.extra["laptop_red"] = why
            where = "box"
        if keep and store is not None and r.status != T.UNRUNNABLE:
            store.put_base(r) if base else store.put(job_key, r)
        return r

    r = go(head_tree)
    out = Outcome(check.name, r.status, r.extra.get("why", ""), [r])
    if r.status != T.FAILED:
        return out
    # a check the base does not have (or whose run file it lacks) has no base to compare: its red is the diff's
    if base_tree and check.name != M.BUILTIN and on_base:
        b = store.base(check.name, base_tree) if store is not None else None
        if b is None:
            b = go(base_tree, base=True, keep=False)
            if b.status == T.FAILED and b.extra.get("loaded"):
                # the head's rule on the base too: a red under load is rerun alone, and only that rerun is shared
                out.results.append(b)
                b = go(base_tree, alone=True, base=True)
            elif store is not None and b.status != T.UNRUNNABLE:
                store.put_base(b)
        out.results.append(b)
        # design §0: "Base red too → blocked-by-main:<check>, not blamed"
        if b.status == T.FAILED:
            out.status, out.note = BLOCKED, f"{BLOCKED}:{check.name}"
            return out
    # design §0: "One diagnostic rerun alone for a red under load"
    if r.extra.get("loaded"):
        r2 = go(head_tree, alone=True)
        out.results.append(r2)
        if r2.status == T.PASSED:
            out.status, out.note = T.PASSED, "flaky: red under load, green alone"
            return out
        if r2.status == T.UNRUNNABLE:
            out.status, out.note = T.UNRUNNABLE, r2.extra.get("why", "")
            return out
        r = r2
    lines = [c["name"] for c in r.cases] or red_lines("\n".join(r.extra.get("tail", [])))
    # design §0: quarantine "never on security checks or on a PR touching the check"
    if not security and not touched and REC.quarantined(check, lines, list(quarantine)):
        out.status, out.note = T.PASSED, "quarantined"
        return out
    out.status, out.note = T.FAILED, r.extra.get("why", "")
    if record:
        record(r, "\n".join(r.extra.get("tail", [])))
    return out


def may_leave(check: T.Check) -> bool:
    """A static, hermetic or host check whose `where` names the laptop. Box and timing never go."""
    return check.klass in (T.STATIC, T.HERMETIC, T.HOST) and "laptop" in check.where


def choose_where(check: T.Check, member: str = "", box_only: bool = False) -> str:
    """member:<h> for a member's landing; the laptop for every check that may leave the box; else box.
    box_only: the lane saw the laptop give no answer a moment ago, so the box takes it without waiting out ssh."""
    if member:
        return f"member:{member}"
    # Laptop first (owner 2026-09-29: "move as much as possible to the laptop … the box is the fallback"), whether or
    # not the box is busy: the PR's code already runs unsandboxed there as the whole suite. A laptop that is busy,
    # on battery or gone is unrunnable and the box runs it; a laptop pass stands; a red is said again on the box
    # (judge).
    if not box_only and may_leave(check) and laptop_dest():
        return "laptop"
    return "box"


def laptop_gone(outs: dict) -> bool:
    """A laptop run that fell back to the box because the laptop gave no answer (not because it answered busy: a
    full runner takes the next check when a slot frees, so only a silent one rests the laptop for LAPTOP_REST)."""
    return any("laptop" in r.extra and "busy" not in str(r.extra["laptop"])
               for o in outs.values() for r in o.results)


def run_plan(repo_root: str, m: M.Manifest, plan: T.Plan, files: list, head_tree: str, base_tree: str = "", *,
             member: str = "", store=None, job_key: str = "", scope: str = "", pr: int | None = None,
             quarantine_text: str = "", runner=None, only=None, record_reds: bool = True,
             fallback: str = "", box_only: bool = False, cancel=None) -> dict:
    """Every check in plan.checks through judge(), one after another; -> {name: Outcome}. The lane calls it with
    its store; `lander check` with none (a worker's own red is its work, and is not recorded). fallback: the host
    manifest `m` was loaded with (manifest.host_fallback), so the base is judged by the same checks. cancel: a
    threading.Event the lane sets to stop the plan; every execute() on this thread polls it."""
    _STOP.event = cancel
    try:
        return _run_plan(repo_root, m, plan, files, head_tree, base_tree, member=member, store=store,
                         job_key=job_key, scope=scope, pr=pr, quarantine_text=quarantine_text, runner=runner,
                         only=only, record_reds=record_reds, fallback=fallback, box_only=box_only)
    finally:
        _STOP.event = None


def _run_plan(repo_root, m, plan, files, head_tree, base_tree, *, member, store, job_key, scope, pr,
              quarantine_text, runner, only, record_reds, fallback, box_only):
    rows = REC.quarantine_rows(quarantine_text)
    record = (lambda r, text: REC.record_red(scope, r, text, pr)) if (record_reds and scope) else None
    base_m = M.load(repo_root, base_tree, fallback=fallback, strict=False) if base_tree else None
    out, gone = {}, False
    for name in plan.checks:
        if only and name not in only:
            continue
        c = M.builtin_check() if name == M.BUILTIN else m.checks.get(name)
        if c is None:
            out[name] = Outcome(name, T.UNRUNNABLE, "not in the manifest")
            continue
        own = [p for p in c.paths if "*" not in p] + [m.cwd.get(name, "") + M.run_file(c.run)]
        security = any(M.match(m.policy.gate_first, p) for p in own if p)
        touched = any(m.owns(name, f) for f in files) if name in m.checks else False
        where = choose_where(c, member, box_only=box_only)
        if gone and where == "laptop" and "box" in c.where:
            where = "box"   # the laptop gave no answer once in this plan: do not wait out its timeout per check
        out[name] = judge(c, head_tree, base_tree, where, runner=runner, store=store,
                          job_key=job_key, security=security, touched=touched, quarantine=rows, record=record,
                          on_base=name == M.BUILTIN or runs_on_base(repo_root, base_tree, base_m, name),
                          repo_root=repo_root, cwd=m.cwd.get(name, ""), changed=files,
                          label=".".join(job_key.rsplit("-", 1)) if job_key else "lander.0")
        gone = gone or laptop_gone({name: out[name]})
    return out


def runs_on_base(repo_root: str, base_tree: str, base_m, name: str) -> bool:
    """Whether the base tree can run check `name` at all: its manifest defines it and its run file is there."""
    if not base_tree or base_m is None or name not in base_m.checks:
        return False
    f = M.run_file(base_m.checks[name].run)
    return not f or M.read_at(repo_root, base_tree, base_m.cwd.get(name, "") + f) is not None


def quarantine_text(repo_root: str, rev: str) -> str:
    return "\n".join(t for t in (M.read_at(repo_root, rev, p + REC.QUARANTINE) for p in M.PREFIXES) if t)


COMMANDS = {"job-serve": (cmd_job_serve, "the laptop's end of a spilled check: hands one job to cc-suites runner, caged")}
