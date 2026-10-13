"""run(): one check on one tree, safely; judge(): what a red means (design §0 Execution, Red main vs red diff; B2, B5).

THE TREE. A run never touches a checkout. materialise() writes the tree's files out of git into
`$TMPDIR/cc-land.run.<pid>.<rand>/cc-land.gates.<repo>.<pr>.<rand>/head` (the shape cc-tmp-reap and `cc-sandbox member
--tree` accept), makes it a git repo with one commit and proves `git write-tree` there equals the tree asked for
(B1: the identity check greps a real work tree). The files are read out of the checkout's objects in a borrowed repo
(git.borrowed) and every git there runs with git.blind_env(), so no config, attributes, filter or replace ref of the
checkout's runs or shapes them. Everything under the run directory goes when the run ends.

THE RUNNER (`where`, one of the check's own `where` list, or `member:<h>[:<t>]` for a member's landing):
  box      by class — static, hermetic and timing in the bwrap profile (sandbox.py); host and box on the host with
           the environment scrubbed as today's clean_start (no CLAUDE*, no token-shaped variables, CC_CONFIG_DENY set),
           under cc-nosignal, so a check signals only what it started (the user manager went down on 2026-10-02).
           A check that says bare = true runs without it: its cases read what cc-nosignal's Landlock domain hides
           (cc-member-v2 reading a live sandbox's /proc/<pid>/fd, cc-fence's no_new_privs case), and nothing leaves
           a domain, so inside one they fail closed or are skipped. Bare means it may signal what the lander can.
           Every one inside an admission slot and a transient scope (admission.py). Timing runs only while the box
           is not loaded. No bwrap on this machine makes a sandboxed class unrunnable, never a host run.
  laptop   static, hermetic and host (never box or timing), over cc-suites' own transport: its key, the
           destination and the pinned host key in ~/.cc/suites (CC_SUITES_DIR: id_ed25519, remote, known_hosts,
           StrictHostKeyChecking=yes), so the laptop is configured exactly when cc-suites' runner is, and a destination known_hosts does not name is refused
           before ssh starts. The tree goes to the runner's `job` form (`/usr/local/bin/cc-suites runner`, a
           root-owned copy, the key's forced command), which unpacks it into a fresh directory with a fresh HOME per
           job, proves it by write-tree, runs it caged
           (writable only in that directory, and with no network unless the check says net = true, which goes as
           the job's trailing `net`; cc-suites, THE CAGE) and removes both; `lander job-serve` hands
           the same job to it. Busy, unfit or not answering is
           unrunnable there, never red, and judge() then runs the check on the box. `remote` lists the runners in
           order, one per line (the peer host first, the laptop second; runner_dests): one the job provably never started on
           (never sent, refused busy or unfit, or ssh never reached it; never_started) is passed over for the next,
           an unreached one for RUNNER_REST, and only past the last does the box take it. A job that started on one
           and then hit its cap or went silent is that runner's result, never sent again: judge() runs it on the
           box. Every runner keeps the laptop's terms: a red on any of them is said again on
           the box. Result.runner names the runner that took it (`laptop:<user@host>:-`) and extra.passed_over the
           ones passed over, so the replay can score each. A host check's line goes with
           HOST_PREP in front: what a box has and a fresh account does not (a tmux session `main`, of a server of
           the job's own, and a waiting ~/.local/bin/claude), as `cc-suites runner` gives a whole suite, so the
           e2e suites and check.sh can run there. A check that needs this box's own host keeps `where = ["box"]`.
  member   `cc-sandbox member <h> <t> --tree <head> -- env … /bin/sh -c <run>`, the workspace's own boundary (B5).

THE STATUS. passed: exit 0 and no `N failed` with N > 0 in the output (a suite that says "1 failed" failed whatever
it exited with). unrunnable — never red: killed at the check's cap, killed by a signal or the scope's MemoryMax
(exit 124, 137, 143 or a signal), a box-state message (disk, quota, memory, fork), a sandbox that did not start, a
mount that is not there, a tree that did not reproduce. failed: anything else.

JUDGE (a red, per check): the same check on the BASE tree — main's own record of it on exactly that tree when the
tip run made one (health.py): green there is no base red, and red there stands as `blocked-by-main` with no run when
the ratchet cannot apply (a check that guards a security path or that the change touches); else the lane's shared
record when there is one — red there too
is `blocked-by-main` (main is red, the diff is not blamed) — unless THE RATCHET lets it pass: every case the head's run
names failing (fail_ids: its ✗/✘, FAIL, FAILED/ERROR or not ok lines, scratch paths and full shas blanked) fails
on the base too, the head ran as far (no fewer passes, no more failures, no crash the base lacks), both ran in the
same place, and the base's red is a run made now, in this judge() (a shared one that would let it pass is run again
first, and when that re-run is unrunnable the shared red holds as main-red), then it passes with a `ratchet` note and
Outcome.sets naming both sets (no_new_reds; never for a check that guards a security path — gate_first,
LANDING-security.toml's paths or SECURITY_PATHS — or that the change touches, and never for a head red that names no
case, where the exit code is all there is); a check the base does not define, or whose run file the base lacks, has no
base run and its red is the diff's; a red run under load, on either tree, gets ONE diagnostic rerun alone (every slot
held), and only a base run that stands is shared; a head red that is not main's is run ONCE more on the same tree
whatever the load (alone when it was loaded), so only a red that repeats is the PR's — except, when it was not loaded,
a check that guards a security path or that the change touches, whose first red stands; green the second time passes
with a `flaky` note, which the lane logs as `flake <repo>#<pr> check=<name>` (a count per check); a red whose every
red line matches a live quarantine row passes with a `quarantined` note — never for a check that guards a security
path, and never when the change touches the check itself; what is left is `failed`, and goes to the failures ledger
once (records.record_red).

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
                      r"|Failed to connect to (user )?(scope )?bus"
                      r"|cc-nosignal: .*refused, nothing ran).*", re.M)
RED_RE = re.compile(r"✗|✘|FAIL|Error\b|error:|not ok|Traceback")
PASS_RE = re.compile(r"^\W*[✓✔]|^\s*(?:ok|pass(?:ed)?)\b", re.I)
KILLED = (124, 137, 143)
SECRET_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
SECRET_SUFFIXES = ("_TOKEN", "_KEY", "_SECRET", "_CREDS", "_WEBHOOK", "_PASSWORD")
BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin")
TAIL = 40
LOG_KEEP, LOG_DAYS = 200, 7   # a red's kept log (keep_log): at most this many, none older than this many days
BLOCKED = "blocked-by-main"
# run_plan(caged=True), `lander check --caged-only`: a check that would run anywhere but the default bwrap on this box
# is not run and says so. Never a pass: the landing runs it (uncaged).
DEFERRED = "deferred"


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
    # `lander check` takes a fenced worker's tree here on the host, as the owner. Git builds it FENCED
    # (git.worktree_tree): a scratch git dir with the lander's own config, so no filter, include, hook or fsmonitor
    # the worker wrote anywhere is read. host_tree only says which host repo the tree is of; a root it does not
    # take gets no tree, and the caller has nothing.
    return G.worktree_tree(G.host_tree(repo_root))


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
    """-> (status, why). A clean exit with no 'N failed' above zero passes whatever it prints: a check that quotes
    a box-state error (a case that fills a disk on purpose) is not the box failing, so that text counts on rc != 0."""
    if capped:
        return T.UNRUNNABLE, "stopped at its cap"
    if rc < 0 or rc in KILLED:
        return T.UNRUNNABLE, f"killed (exit {rc})"
    m = BOX_STATE_RE.search(text) if rc else None
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


# THE RATCHET'S IDS: the line a suite prints for one failing case — its own ✗/✘ line, a FAIL line, pytest's FAILED or
# ERROR id (an ERROR line only in pytest's summary form, a .py path or a node id: a log's ERROR line is no case), TAP's
# not ok — read from the whole output. A run's own scratch (a /tmp path, a sha, a duration) is
# blanked so the same case is the same id on two trees; anything else that varies makes a new id, which holds.
FAIL_ID_RE = re.compile(r"^\s*(?:[✗✘]|FAIL(?:ED)?\b:?|ERROR\s(?=\S*(?:\.py\b|::))|ERROR:\s(?=\w+ \([\w.]+\)$)"
                        r"|not ok\b(?:\s*\d+\s*-?)?)"
                        r"\s*(.*?)\s*$")
FAILS_CAP = 500   # more failing lines than this and the set is not trusted: fail_ids says None, and the red holds
# Only a scratch path and a full 40-char sha are blanked: a duration or a short hex run is part of the id, because
# blanking it made 'after 900 s' the same case as 'after 31 s' (Opus read of #1305, 10-13)
SCRATCH_RES = ((re.compile(r"(?:/tmp|/var/tmp)/[^\s:'\"),]*"), "/tmp/…"), (re.compile(r"\b[0-9a-f]{40}\b"), "…"))


# ...and how far a run got: its pass lines or its last `N passed`, and whether it crashed or was cut short. A head that
# ran less than the base, or crashed where the base did not, hides its own reds behind main's (Opus and perms, 10-13)
PASSED_N_RE = re.compile(r"\b(\d+) passed\b")
CRASH_RE = re.compile(r"^\s*(?:Traceback \(most recent call last\)|INTERNALERROR>)|Segmentation fault|core dumped|"
                      r"^\s*(?:Killed|Aborted)\b|\bline \d+:\s+\d+ (?:Killed|Aborted)\b", re.M)


def ran(text: str) -> dict:
    """-> {"passes": its last `N passed`, else its count of pass lines; "failed": its last `N failed`, else its count of
    failing lines (one case failing twice is two); "crash": a crash or abort marker in it}."""
    n = PASSED_N_RE.findall(text)
    passes = int(n[-1]) if n else sum(1 for ln in text.splitlines() if PASS_RE.search(ln))
    f = FAILED_RE.findall(text)
    failed = int(f[-1]) if f else sum(1 for ln in text.splitlines() if FAIL_ID_RE.match(ln) and not PASS_RE.search(ln))
    return {"passes": passes, "failed": failed, "crash": bool(CRASH_RE.search(text))}


def fail_ids(text: str):
    """-> the sorted failing case ids `text` names ([] when it names none: the exit code is all there is), or None
    past FAILS_CAP."""
    got = set()
    for ln in text.splitlines():
        m = FAIL_ID_RE.match(ln)
        if not m or PASS_RE.search(ln):
            continue
        name = m.group(1)
        if "::" in name:   # pytest's `FAILED tests/x.py::t - AssertionError: …`: the id is before the message
            name = name.split(" - ", 1)[0]
        for rx, to in SCRATCH_RES:
            name = rx.sub(to, name)
        got.add(f"{ln.split()[0]} {name}"[:200])
        if len(got) > FAILS_CAP:
            return None
    return sorted(got)


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
        scope = [] if check.bare else [os.path.join(BIN, "cc-nosignal"), "--"]
        return (scope + ["/bin/sh", "-c", check.run], os.path.join(head, cwd) if cwd else head,
                clean_env(env_extra), "host")
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


def runner_dests() -> list:
    """cc-suites' runners (user@host), in the order they are tried — one per line of its `remote`, the peer host first and the
    laptop second — when its key and pinned host keys are there; else []. A line that is not
    user@host is skipped. Every runner takes the same key, so a second runner adds no key to this box."""
    d = _suites_dir()
    try:
        with open(os.path.join(d, "remote")) as f:
            lines = ["".join(ln.split()) for ln in f]
    except OSError:
        return []
    if not all(os.path.isfile(p) and os.path.getsize(p) for p in (os.path.join(d, "id_ed25519"),
                                                                    os.path.join(d, "known_hosts"))):
        return []
    out = []
    for dest in lines:
        if re.fullmatch(r"[A-Za-z0-9._-]+@[A-Za-z0-9._-]+", dest) and dest not in out:
            out.append(dest)
    return out


def laptop_dest() -> str:
    """The first runner off the box (runner_dests), or '' when none is configured."""
    return next(iter(runner_dests()), "")


# A runner ssh could not reach is passed over for RUNNER_REST seconds, so a gone peer host does not cost every check its
# ssh connect timeout before the laptop takes it. {user@host: monotonic time}.
RUNNER_REST = 300
_SILENT: dict = {}
NO_ANSWER = "laptop refused or did not answer"   # _laptop_verdict's word for a runner that gave no verdict
# What proves a job never started on a runner, so the next may take it (security read of #1097: a job that ran there,
# then hit its cap or lost its connection, is that runner's result, never sent again). Either is a line back
# with no relayed `| ` line, no verdict and no cap: the runner's own refusal, said before it unpacks anything (cc-suites
# runner_job, job-serve), or ssh failing before any session (connect, name, host key, auth, key exchange).
# ssh says a refused key as `user@host: Permission denied (publickey).`, so that one carries its user@host prefix.
# The user part takes no `@`, so a long line of them is read in linear time (two \S+ around one @ backtracked for seconds).
REFUSED_RE = re.compile(r"(?:cc-suite-runner|lander-job): (?:busy|unfit|refused)\b")
UNREACHED_RE = re.compile(r"ssh: connect to host \S+ port \d+: |ssh: Could not resolve hostname |"
                          r"Host key verification failed\.|(?:[^\s@]+@\S+: )?Permission denied \(|"
                          r"kex_exchange_identification: ")


def never_started(text: str, capped: bool) -> str:
    """'refused' or 'unreached' when the runner's raw output proves the job never began there, else ''."""
    lines = [ln.strip() for ln in text.split("\n")]
    if capped or any(ln.startswith("|") or "verdict" in ln for ln in lines):
        return ""
    # any line, not the first: ssh may warn ahead of it (a non-post-quantum key exchange), and neither kind can
    # come after a job began, when the runner says nothing but `| ` lines and a verdict
    if any(REFUSED_RE.match(ln) for ln in lines):
        return "refused"
    return "unreached" if any(UNREACHED_RE.match(ln) for ln in lines) else ""


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


def laptop_argv(check, tree, cwd, dest=""):
    """The ssh argv that hands `check` on `tree` to the runner `dest` (default: the first, laptop_dest)."""
    dest = dest or laptop_dest()
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
        state: str | None = None, express: bool = False, lane: bool = False) -> T.Result:
    """Runner.run. Runs `check` on `tree_sha` (read from repo_root's git) at `where`, holding an admission slot
    (every slot, alone=True; none for an express run that is not alone: the lane's EXPRESS bounds those). Stores
    nothing: the lane stores what it wants (records.Store). cwd: the check's manifest prefix. changed: the change's
    files, handed in as CC_LAND_CHANGED. base_tree: the other side, for the built-in manifest-widen. lane: a landing
    lane's run, whose slot ticket goes before a worker's (admission)."""
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
    try:
        if kind != "laptop":
            return _attempt(check, tree_sha, where, "", head, run_dir, cwd, env_extra, alone, state, express, lane)
        # the brief (R3): "the peer host keeps laptop semantics: busy or unfit means unrunnable, and a red there never counts".
        # the runners in order (the peer host first, the laptop second): one the job provably never started on (never sent,
        # refused busy or unfit, or not reached) is passed over and the next takes it; past the last, judge() runs it
        # on the box. A job that started on one (its cap, a dropped connection, any answer) is that runner's result
        # and goes nowhere else. A red on any of them is never final (judge).
        dests = runner_dests()
        if not dests:
            raise Unrunnable(f"no laptop is configured (cc-suites: {_suites_dir()})")
        now, passed = time.monotonic(), []
        awake = [d for d in dests if now - _SILENT.get(d, -RUNNER_REST) >= RUNNER_REST]
        passed += [f"{d}: not reached lately" for d in dests if d not in awake]
        r, took = None, False
        for dest in awake:
            r = _attempt(check, tree_sha, where, dest, head, run_dir, cwd, env_extra, alone, state, express, lane)
            why = str(r.extra.get("why", ""))
            if r.status != T.UNRUNNABLE or stopped() or not (r.extra.get("not_sent") or r.extra.get("never_started")):
                if r.extra.get("never_started") != "unreached":
                    _SILENT.pop(dest, None)
                took = True
                break
            if r.extra.get("never_started") == "unreached":
                _SILENT[dest] = time.monotonic()
            passed.append(f"{dest}: {why.splitlines()[0] if why else 'no answer'}")
        if r is None:
            raise Unrunnable("; ".join(passed))
        if passed:   # each runner passed over, and why, so the replay can score them
            r.extra["passed_over"] = passed
            if not took:
                r.extra["why"] = "; ".join(passed)
        return r
    except Unrunnable as e:
        return res(T.UNRUNNABLE, str(e))
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def _attempt(check, tree_sha, where, dest, head, run_dir, cwd, env_extra, alone, state, express, lane) -> T.Result:
    """One run of `check` at `where` (on the runner `dest` when that is the laptop kind); Result.runner names the
    runner that took it: `laptop:<user@host>:-` off the box."""
    kind = where.split(":")[0]
    log = os.path.join(run_dir, "log")
    try:
        stdin, tar = None, None
        if kind == "laptop":
            argv, wd, env, how = laptop_argv(check, tree_sha, cwd, dest), run_dir, clean_env(), dest
            tar = subprocess.Popen(["tar", "-C", head, "-cf", "-", "."], stdout=subprocess.PIPE)
            stdin = tar.stdout
        elif kind == "member":
            argv, wd, env, how = _member_argv(check, head, cwd, where, env_extra)
        else:
            argv, wd, env, how = _box_argv(check, head, cwd, run_dir, env_extra)
        scope = "-"
        # the laptop's work is the laptop's: it takes no slot of the box's; nor does an express run (lane EXPRESS)
        free = kind == "laptop" or (express and not alone)
        held = contextlib.nullcontext() if free else A.slot(state or REC.state_dir(), alone=alone,
                                                            who=f"{check.name}@{tree_sha[:8]}", lane=lane)
        with held:
            loaded = A.loaded()
            if kind == "box":   # wrapped once the slot is held, so the priority answers for the load it starts under
                argv, scope = A.wrap(check, argv, f"{check.name}-{tree_sha[:8]}", busy=bool(A.overloaded()))
            rc, secs, cpu, capped = execute(argv, wd, env, check.cap, log, stdin)
            loaded = loaded or A.loaded()   # under load at either end of the run
        if tar is not None:
            tar.stdout.close()
            tar.wait()
        text, started = read_log(log), {}
        if kind == "laptop":
            started = {"never_started": never_started(text, capped)} if dest else {}
            text, rc = _laptop_verdict(text, rc)
        st, why = status_of(rc, text, capped)
        if kind == "laptop" and rc == -1 and not capped:   # capped: it ran there, and "stopped at its cap" says so
            why = text.splitlines()[0] if text else "the laptop did not answer"
        kept = {}
        if st == T.FAILED:   # the log outlives run_dir, and the result names the line that failed
            kept = {"cause": cause_of(text, rc), "log": keep_log(text, check.name, tree_sha, state),
                    "fails": fail_ids(text), **ran(text)}
            why = f"{why}: {kept['cause']}"
        return T.Result(check=check.name, tree=tree_sha, status=st, secs=round(secs, 2), cpu_secs=round(cpu, 2),
                        load=os.getloadavg()[0], runner=f"{where}:{how}:{scope}",
                        cases=[{"name": ln[:200], "status": T.FAILED} for ln in red_lines(text)[:50]]
                        if st == T.FAILED else [],
                        extra={"why": why, "rc": rc, "loaded": loaded, "alone": alone,
                               "tail": text.splitlines()[-TAIL:], **kept, **started})
    except Unrunnable as e:
        return T.Result(check=check.name, tree=tree_sha, status=T.UNRUNNABLE, secs=0.0, load=os.getloadavg()[0],
                        runner=f"{where}:{dest}:-" if dest else where, extra={"why": str(e), "not_sent": True})


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
        return f"{NO_ANSWER}: {refused[:200]}\n{body}", -1
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
    sets: dict = field(default_factory=dict)   # a red on both trees: {"pr": ids, "main": ids} (no_new_reds)


def judge(check: T.Check, head_tree: str, base_tree: str, where: str = "box", *, runner=None, store=None,
          job_key: str = "", security: bool = False, touched: bool = False, quarantine: list = (),
          record=None, on_base: bool = True, main: str = "", **run_kw) -> Outcome:
    """What one check says about a change. runner defaults to run(); store (records.Store, the lane's) keeps each
    run and shares base runs; record(result, text) is called once for a red that is the diff's. on_base=False: the
    base tree has no such check or not its run file, so there is no base run and a red is the diff's. main: main's
    own record of this check on exactly base_tree (health.at), passed or failed, which stands for the base run."""
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
    # brief 10-13: "This replaces judge()'s base re-run for checks with a fresh main record" -- a red record stands
    # without a run only where the ratchet could not let the head pass anyway; it needs a base run made now
    if base_tree and check.name != M.BUILTIN and on_base and main == T.FAILED and (security or touched):
        out.status, out.note = BLOCKED, f"{BLOCKED}:{check.name} (main's own record)"
        return out
    if base_tree and check.name != M.BUILTIN and on_base and main != T.PASSED:
        def base_run():
            b = go(base_tree, base=True, keep=False)
            if b.status == T.FAILED and b.extra.get("loaded"):
                # the head's rule on the base too: a red under load is rerun alone, and only that rerun is shared
                out.results.append(b)
                b = go(base_tree, alone=True, base=True)
            elif store is not None and b.status != T.UNRUNNABLE:
                store.put_base(b)
            return b
        b = store.base(check.name, base_tree) if store is not None else None
        fresh = b is None
        b = base_run() if fresh else b
        out.results.append(b)
        # the ratchet follows quarantine's rule: never on security checks or on a PR touching the check, whose
        # change could reword its own red lines into main's
        may = not security and not touched
        if b.status == T.FAILED and may and not fresh and no_new_reds(r, b):
            # brief: "main's result at the PR's own base_sha, run in the same environment, never a cached result
            # from another host state": the shared red would let this one through, so the base is run again now
            # ...and a re-run that gave no answer (unrunnable: its cap, the laptop gone) keeps the stored red, which
            # holds as main-red: the PR is never handed back for a red main has (Opus and perms, 10-13)
            again = base_run()
            out.results.append(again)
            if again.status != T.UNRUNNABLE:
                b, fresh = again, True
        if b.status == T.FAILED:
            # brief: "If the PR's failing set is a subset of main's, the check counts as passed for this PR"
            if may and fresh and no_new_reds(r, b):
                out.status, out.note = T.PASSED, f"ratchet: no new reds, {check.name} is red on the base too"
                out.sets = {"pr": r.extra["fails"], "main": b.extra["fails"]}
                return out
            # design §0: "Base red too → blocked-by-main:<check>, not blamed"
            out.status, out.note = BLOCKED, f"{BLOCKED}:{check.name}"
            out.sets = {"pr": r.extra.get("fails"), "main": b.extra.get("fails")}
            return out
    # design §0: "One diagnostic rerun alone for a red under load"; and every other red is run once more on the
    # same tree too, "a gate that goes red is re-run once on the same commit before the PR is handed back" (owner,
    # 10-12: host-env reds were 27 handbacks): only a red that repeats is the PR's. The unloaded rerun follows
    # quarantine's rule, "never on security checks or on a PR touching the check" (security read, 10-12: a race in
    # auth code caught half the time would pass 3 times in 4)
    loaded = bool(r.extra.get("loaded"))
    if loaded or (not security and not touched):
        r2 = go(head_tree, alone=loaded)
        out.results.append(r2)
        if r2.status == T.PASSED:
            out.status, out.note = T.PASSED, ("flaky: red under load, green alone" if loaded
                                              else "flaky: red, then green on the same tree")
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


def no_new_reds(head: T.Result, base: T.Result) -> bool:
    """THE RATCHET: True when both reds ran in the same place (the box, a runner, a member) and every case the head's
    run names failing the base's names too, and the head ran as far as the base: no fewer passes, and no crash or abort
    the base lacks (a head cut short names fewer reds only because it ran less), and no more failures than the base (a
    case failing twice, or a lost test masked by an added passing one). A head run that names none falls back to the
    exit code, which says only that both are red, so it holds; so does a set fail_ids could not trust (None)."""
    pr, main = head.extra.get("fails"), base.extra.get("fails")
    same = head.runner.split(":")[0] == base.runner.split(":")[0]
    went = (head.extra.get("passes") or 0) >= (base.extra.get("passes") or 0) and \
        not (head.extra.get("crash") and not base.extra.get("crash")) and \
        (head.extra.get("failed") or 0) <= (base.extra.get("failed") or 0)
    return same and went and bool(pr) and main is not None and set(pr) <= set(main)


def may_leave(check: T.Check) -> bool:
    """A static, hermetic or host check whose `where` names the laptop. Box and timing never go."""
    return check.klass in (T.STATIC, T.HERMETIC, T.HOST) and "laptop" in check.where


def choose_where(check: T.Check, member: str = "", box_only: bool = False, runners: bool = False) -> str:
    """member:<h> for a member's landing; the runners for every check that may leave this host while spill() says
    it is full, or when the caller placed it there (runners=True: the lane found no box slot for it); else box.
    box_only: the lane saw the runners give no answer a moment ago, so the box takes it without waiting out ssh."""
    if member:
        return f"member:{member}"
    # THIS HOST FIRST, the runners when it is full (owner 2026-10-12: "ideally full ram and cpu usage on both boxes").
    # The lander now runs on a host with room to spare, so sending every check out by default left it idle while the
    # runners queued; it spills while admission.overloaded() says so (the same call cc-room holds workers on) or
    # every admission slot is held, so no check waits for a box slot while a runner may take it (spill()).
    # A runner that is busy, unfit or gone is unrunnable and the box runs it; a runner's pass stands; a red there is
    # said again on the box (judge).
    if not box_only and may_leave(check) and laptop_dest() and (runners or spill()):
        return "laptop"
    return "box"


def spill() -> str:
    """"" while this host keeps its own checks, else why they go to the runners: admission.overloaded(), the one
    signal the lander serializes on and cc-room holds workers on, or no admission slot free now (admission.free), so a
    check here would wait for one while a runner may sit idle (2026-10-02: #772 ran a check every 8-30 min on a
    box cut to 1-2 slots while the laptop answered `free 6`). choose_where and the lane's runner flights ask it. An
    OSError reading the slots counts as no slot free, so the check spills rather than the lane raising."""
    why = A.overloaded()
    if why:
        return why
    try:
        if A.free(REC.state_dir()):
            return ""
    except OSError as e:
        return f"admission slots unreadable ({e})"
    return "every admission slot on this host is held"


def uncaged(check: T.Check) -> str:
    """'' when `check` runs whole inside the default bwrap profile on this box; else why it does not. A fenced worker's
    green (cc-green's pinned host run, `lander check --caged-only`) runs only the first kind: the tree it checks is one
    the worker wrote, so a host or box check there would run the worker's code as the owner, outside every fence."""
    if check.klass in M.UNSANDBOXED:
        return f"{check.klass}-class, runs on the host outside the sandbox"
    if check.net:
        return "needs the network"
    if check.mounts:
        return "needs host mounts"
    if "box" not in check.where:
        return f"runs only on {', '.join(check.where) or 'no runner'}"
    return ""


def laptop_gone(outs: dict) -> bool:
    """A laptop run that fell back to the box because the laptop gave no answer (not because it answered busy: a
    full runner takes the next check when a slot frees, so only a silent one rests the laptop for LAPTOP_REST)."""
    return any("laptop" in r.extra and "busy" not in str(r.extra["laptop"])
               for o in outs.values() for r in o.results)


def run_plan(repo_root: str, m: M.Manifest, plan: T.Plan, files: list, head_tree: str, base_tree: str = "", *,
             member: str = "", store=None, job_key: str = "", scope: str = "", pr: int | None = None,
             quarantine_text: str = "", runner=None, only=None, record_reds: bool = True,
             fallback: str = "", box_only: bool = False, runners: bool = False, cancel=None, express: bool = False,
             lane: bool = False, caged: bool = False, main=None) -> dict:
    """Every check in plan.checks through judge(), one after another; -> {name: Outcome}. The lane calls it with
    its store; `lander check` with none (a worker's own red is its work, and is not recorded). fallback: the host
    manifest `m` was loaded with (manifest.host_fallback), so the base is judged by the same checks. cancel: a
    threading.Event the lane sets to stop the plan; every execute() on this thread polls it. express: the lane's
    EXPRESS (a Δ rerun's check), whose runs take no admission slot; a diagnostic rerun alone still takes them all.
    lane=True from the lane only: its box runs wait ahead of a worker's (run's `lane`). runners=True from the lane
    only: it found no box slot for these checks, so each that may leave goes to the runners (choose_where).
    caged=True (`lander check --caged-only`): a check uncaged() names is DEFERRED, never run and never a pass, and the
    rest run on the box only. main: {check: status} of main's own record on exactly base_tree (health.at), which
    judge() takes in place of a base run."""
    _STOP.event = cancel
    try:
        return _run_plan(repo_root, m, plan, files, head_tree, base_tree, member=member, store=store,
                         job_key=job_key, scope=scope, pr=pr, quarantine_text=quarantine_text, runner=runner,
                         only=only, record_reds=record_reds, fallback=fallback, box_only=box_only, runners=runners,
                         express=express, lane=lane, caged=caged, main=main or {})
    finally:
        _STOP.event = None


def _run_plan(repo_root, m, plan, files, head_tree, base_tree, *, member, store, job_key, scope, pr,
              quarantine_text, runner, only, record_reds, fallback, box_only, express, lane, caged=False,
              runners=False, main=None):
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
        why = uncaged(c) if caged else ""
        if why:
            out[name] = Outcome(name, DEFERRED, f"runs at landing: {why}")
            continue
        own = [p for p in c.paths if "*" not in p] + [m.cwd.get(name, "") + M.run_file(c.run)]
        # perms' terms (#1234): manifest-widen's "red blocks as a fault, never advisory", so it is never quarantined
        security = name == M.BUILTIN or any(M.match(list(m.policy.gate_first) + list(m.policy.security_review) +
                                                     list(SECURITY_PATHS), p) for p in own if p)
        touched = any(m.owns(name, f) for f in files) if name in m.checks else False
        where = "box" if caged else choose_where(c, member, box_only=box_only, runners=runners)
        if gone and where == "laptop" and "box" in c.where:
            where = "box"   # the laptop gave no answer once in this plan: do not wait out its timeout per check
        out[name] = judge(c, head_tree, base_tree, where, runner=runner, store=store,
                          job_key=job_key, security=security, touched=touched, quarantine=rows, record=record,
                          on_base=name == M.BUILTIN or runs_on_base(repo_root, base_tree, base_m, name),
                          main=(main or {}).get(name, ""),
                          repo_root=repo_root, cwd=m.cwd.get(name, ""), changed=files,
                          label=".".join(job_key.rsplit("-", 1)) if job_key else "lander.0",
                          **({"express": True} if express else {}), **({"lane": True} if lane else {}))
        gone = gone or laptop_gone({name: out[name]})
    return out


# A SECURITY CHECK guards a path no red may slip past: gate_first, tests/LANDING-security.toml's paths, and these —
# the member wall (core/bin/cc, cc-member-v2) and the Cloudflare door. perms' read of #1305, 10-13: "treat
# LANDING-security.toml paths plus those two as security and never ratchet them".
SECURITY_PATHS = ("core/bin/cc", "core/bin/cc-member-v2", "bin-private/*-cloudflare")


def runs_on_base(repo_root: str, base_tree: str, base_m, name: str) -> bool:
    """Whether the base tree can run check `name` at all: its manifest defines it and its run file is there."""
    if not base_tree or base_m is None or name not in base_m.checks:
        return False
    f = M.run_file(base_m.checks[name].run)
    return not f or M.read_at(repo_root, base_tree, base_m.cwd.get(name, "") + f) is not None


def quarantine_text(repo_root: str, rev: str) -> str:
    return "\n".join(t for t in (M.read_at(repo_root, rev, p + REC.QUARANTINE) for p in M.PREFIXES) if t)


COMMANDS = {"job-serve": (cmd_job_serve, "the laptop's end of a spilled check: hands one job to cc-suites runner, caged")}
