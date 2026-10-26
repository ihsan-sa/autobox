"""run(): one check on one tree, safely; judge(): what a red means (design §0 Execution, Red main vs red diff; B2, B5).

THE TREE. A run never touches a checkout. materialise() writes the tree's files out of git into
`$TMPDIR/cc-land.run.<pid>.<rand>/cc-land.gates.<repo>.<pr>.<rand>/head` (the shape cc-tmp-reap and `cc-sandbox member
--tree` accept), makes it a git repo with one commit and proves `git write-tree` there equals the tree asked for
(B1: the identity check greps a real work tree); given the base tree, the repo also holds it as refs/lander/base,
for a check that compares against main (the guard's differential), and a check PINNED names runs once more with
main's copies of its pinned files laid over a fresh copy of the head, never the one its first pass ran in, when the
head changed them (pins, pinned_head). The files are read out of the checkout's objects
in a borrowed repo (git.borrowed) and every git there runs with git.blind_env(), so no config, attributes, filter or
replace ref of the checkout's runs or shapes them. Everything under the run directory goes when the run ends.

THE RUNNER (`where`, one of the check's own `where` list, or `member:<h>[:<t>]` for a member's landing):
  box      by class — static, hermetic, timing and every host check the laptop may take in the bwrap profile
           (sandbox.py), as the laptop's cage runs them: a PR head is code a worker wrote, never run as the box's
           user (manifest.on_host; perms' reviewer, 10-19). Box checks and the host checks that need this host
           (bare, or no laptop in `where`; on a PR head, only after perms' LAND at it, lane.Lane.host_unread) on the host with the environment scrubbed as today's clean_start (no CLAUDE*, no token-shaped variables, CC_CONFIG_DENY set),
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
(exit 124, 137, 143 or a signal), a box-state message (disk, quota, memory, fork) from a run that exited non-zero (a
passing check may quote that text itself), a sandbox that did not start (its stub not installed included), a mount
that is not there, a tree that did not reproduce. failed: anything else. On the box, setup says it started OUT OF
BAND (sandbox.started: a pipe the innermost setup writes and closes before the check runs, inside bwrap, cc-nosignal and
the scope), so a check that prints `bwrap:` or cc-nosignal's refusal is failed, never unrunnable, and a run that never
said it started is unrunnable whatever it exited (perms on #1452). A member's or a runner's run has no such pipe, and
its first line is read for those words as before.

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
LANDING-security.toml's paths or SECURITY_PATHS — or that the change touches, and for a head red that names no
case only when the base names none either and both print a failure count, the head's no higher); a check the base does not define, or whose run file the base lacks, has no
base run and its red is the diff's — except a check the base defines whose run file is on neither tree, which is not
run at all and is `blocked-by-main` (missing_run: main registered it before its script landed); a red run under
load (A.loaded() at either end, or starved(): a box run whose wall time was STARVED times its CPU time while a load
average stood at the box's cores), on either tree, gets ONE diagnostic rerun alone (every slot held; one that has not got them all within the largest cap
in its manifest runs as load admits instead, admission SETTLE, though a security check never does, and a loaded red from it is unrunnable, no answer), and only a base run that stands is shared; a head red that is not main's is run ONCE more on the same tree
whatever the load (alone when it was loaded), so only a red that repeats is the PR's — except, when it was not loaded
(or loaded by starved() alone short of its cap: a PR's own check sets its ratio with a sleep), a check that guards a security path or that the change touches, whose first red stands; green the second time passes
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
import hashlib
import os
import posixpath
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field

from lander import admission as A
from lander import cards as C
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
                      r"|cc-nosignal: .*refused, nothing ran|" + re.escape(S.SETUP_FAILED) + r").*", re.M)
# A live-network check that failed a name lookup met the box's resolver, not the tree: it drops out for seconds at a time
# (10-14: two pushes 17 s apart on 'Could not resolve host: github.com'), and a red for it stopped an ai-ee landing.
# Only a net check is read this way: a check with no network has no lookup to fail, so its line is the tree's own.
RESOLVE_RE = re.compile(r"Could not resolve host(?:name)?\b.*|Temporary failure in name resolution|"
                        r"Name or service not known|No address associated with hostname|\bEAI_AGAIN\b")
# …BUT ONLY WHILE THE RESOLVER ITSELF IS DOWN. A test with a typo'd host (api.jlcpcb.comm) fails the same way every run,
# and read as the network it was held three times and its author never saw the red, while main's tip answered 'retry'
# for it on every tick (perms and an Opus read of #1500, 10-20). Asking the line's own host again cannot tell a typo
# from a flap (neither resolves), and the line is the tree's text, so a PR could print one to be held. So only the last
# RESOLVE_TAIL lines are read, and a lookup line there holds only when RESOLVE_PROBE, a name that must resolve, fails.
RESOLVE_TAIL = 20
RESOLVE_PROBE = "github.com"
RESOLVE_WAIT = 5   # seconds the probe may take; one that does not answer in time failed
RED_RE = re.compile(r"✗|✘|FAIL|Error\b|error:|not ok|Traceback")
PASS_RE = re.compile(r"^\W*[✓✔]|^\s*(?:ok|pass(?:ed)?)\b", re.I)
KILLED = (124, 137, 143)
SECRET_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
SECRET_SUFFIXES = ("_TOKEN", "_KEY", "_SECRET", "_CREDS", "_WEBHOOK", "_PASSWORD")
BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin")
TAIL = 40
STARVED = 1.5   # starved(): wall time this many times the CPU time
LOG_KEEP, LOG_DAYS = 200, 7   # a red's kept log (keep_log): at most this many, none older than this many days
BLOCKED = "blocked-by-main"
# run_plan(caged=True), `lander check --caged-only`: a check that would run anywhere but the default bwrap on this box
# is not run and says so. Never a pass: the landing runs it (uncaged).
DEFERRED = "deferred"
# materialise(base_tree=): the base (main at the PR's base_sha) as a commit in the check's repo
BASE_REF = "refs/lander/base"
BASE_READ = 128   # bytes of BASE_REF base_of() reads: a sha-256 id and its newline, with room to spare
# PINNED, perms' read of #1425: a check whose run file is one of these keys (under a manifest prefix) also runs with
# these files as main has them at the PR's base, laid over the head tree, when the head changed any of them. The
# guard's differential ran the PR's own guard-replay.sh and guard-probe.jsonl, so a PR could weaken the script or
# drop probe rows and pass its own check; main's copies now judge the PR's guard too (pins, run).
# A path may climb out of the prefix (the overlay's own box set, ../tests/...); one that leaves the tree pins nothing.
PINNED = {"tests/guard-replay.sh": ("tests/guard-replay.sh", "tests/guard-probe.jsonl", "tests/guard-replay.jsonl",
                                    "../tests/guard-replay-box.jsonl")}


class Unrunnable(RuntimeError):
    pass


# --- the tree ------------------------------------------------------------------------------------------------------

def materialise(repo_root: str, tree: str, label: str = "lander.0", base_tree: str = "") -> tuple:
    """-> (run_dir, head_dir). Raises Unrunnable when the tree cannot be written out exactly. base_tree, when it is
    another tree: the head repo also holds it as the commit BASE_REF (only the objects the head lacks are copied in,
    none written out), so a check can compare against main without an origin/main (tests/guard-replay.sh)."""
    if not re.fullmatch(r"[0-9a-f]{40}", tree or ""):
        raise Unrunnable(f"not a tree id: {tree!r}")
    if base_tree and not re.fullmatch(r"[0-9a-f]{40}", base_tree):
        raise Unrunnable(f"not a base tree id: {base_tree!r}")
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
        if base_tree and base_tree != tree:
            with G.borrowed(repo_root) as scratch:
                benv = dict(G.blind_env(), GIT_DIR=scratch, GIT_NO_REPLACE_OBJECTS="1")
                pack = subprocess.run(["git", "pack-objects", "--revs", "--stdout", "-q"], env=benv, cwd=scratch,
                                      input=f"{base_tree}\n^{tree}\n".encode(), capture_output=True)
            if pack.returncode:
                raise Unrunnable(f"could not copy the base tree in: {pack.stderr.decode(errors='replace')[-300:]}")
            subprocess.run(g + ["index-pack", "--stdin"], env=henv, input=pack.stdout, check=True,
                           capture_output=True)
            base = subprocess.run(g + ["commit-tree", base_tree, "-m", f"base {base_tree}"], env=henv, check=True,
                                  capture_output=True, text=True).stdout.strip()
            subprocess.run(g + ["update-ref", BASE_REF, base], env=henv, check=True, capture_output=True)
        return run_dir, head
    except (Unrunnable, OSError, subprocess.CalledProcessError, G.GitError) as e:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise e if isinstance(e, Unrunnable) else Unrunnable(f"could not write the tree out: {e}") from None


def base_of(head: str) -> str:
    """BASE_REF as the head repo holds it, read from its file (materialise writes it loose), never through git, whose
    config the check ran with write access to; "" when there is none. The check could have written the file, and this
    runs in the lander's own process, so (Opus' read of #1453) it opens without following a link or waiting on a FIFO,
    takes only a regular file, reads one ref's length of bytes and wants ASCII: anything else is "", which base_kept()
    fails, never a hang, an endless read or an error into the lane."""
    try:
        fd = os.open(os.path.join(head, ".git", *BASE_REF.split("/")), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return ""
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return ""
        return os.read(fd, BASE_READ).decode("ascii").strip()
    except (OSError, UnicodeDecodeError):
        return ""
    finally:
        os.close(fd)


def base_kept(r: T.Result, head: str, want: str) -> T.Result:
    """`r`, or FAILED when it passed and the check left BASE_REF (`want`, as materialise set it) moved or gone in its
    head. Opus' read of #1453: a PR's cc-guard deleted the ref, guard-replay.sh skipped its differential and passed."""
    if not want or r.status != T.PASSED or base_of(head) == want:
        return r
    r.status = T.FAILED
    r.extra["why"] = (f"the check moved or deleted {BASE_REF} (main at the PR's base, {want[:12]}), which it may "
                      "compare against, so its pass proves nothing")
    return r


def pins(repo_root: str, check: T.Check, cwd: str, base_tree: str, tree: str) -> dict:
    """{path: (mode, bytes)} of the PINNED files of `check` that base_tree holds and `tree` holds otherwise (a
    different blob or mode, or none), paths from the tree's root; {} when the check pins nothing, there is no other
    side, or the base has no run file of its own to run (a base from before the script)."""
    full = cwd + M.run_file(check.run)
    key = next((k for k in PINNED if full == k or full.endswith("/" + k)), "")
    if not key or not base_tree or base_tree == tree:
        return {}
    pre = full[:len(full) - len(key)]
    out = {}
    with G.Objects(repo_root) as o:
        b, h = o.tree(base_tree), o.tree(tree)
        for rel in PINNED[key]:
            path = posixpath.normpath(pre + rel)
            if path.startswith("../") or path == "..":
                continue
            e = o.entry(b, path)
            if e is None or e[0] not in (b"100644", b"100755"):
                if rel == key:
                    return {}
                continue
            if o.entry(h, path) == e:
                continue
            kind, body = o.read(e[1])
            if kind != b"blob":
                raise G.GitError(f"{path} at {base_tree[:12]} is not a blob")
            out[path] = (0o755 if e[0] == b"100755" else 0o644, body)
    return out


def lay_over(head: str, files: dict) -> None:
    """Writes `files` ({path: (mode, bytes)}, pins) into the head work tree. A path whose directory resolves outside
    head (a symlinked directory the head carries) is Unrunnable, and a file already there, a symlink too, is
    replaced, never written through."""
    root = os.path.realpath(head)
    for path, (mode, body) in files.items():
        dest = os.path.join(head, path)
        d = os.path.dirname(dest)
        os.makedirs(d, exist_ok=True)
        if os.path.commonpath([root, os.path.realpath(d)]) != root:
            raise Unrunnable(f"{path}: its directory resolves outside the tree, so main's copy cannot go there")
        if os.path.lexists(dest):
            if os.path.isdir(dest) and not os.path.islink(dest):
                raise Unrunnable(f"{path} is a directory in the head, so main's copy cannot go there")
            os.unlink(dest)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        os.chmod(dest, mode)


def pinned_head(repo_root: str, tree: str, label: str, base_tree: str, files: dict) -> tuple:
    """-> (run_dir, head) for a PINNED check's second pass: `tree` written out afresh (materialise, with BASE_REF),
    `files` (pins) laid over it, and write-tree of that work tree proved to be `tree` with exactly those files
    replaced. Never the head the first pass ran in: the PR's own script ran there read-write and could have deleted
    BASE_REF or planted files, so main's script would judge what the PR left behind. Raises Unrunnable."""
    run_dir, head = materialise(repo_root, tree, label + ".pinned", base_tree)
    try:
        lay_over(head, files)
        g, henv = ["git", "-C", head], G.blind_env()

        def git(*argv, idx, inp=None):
            return subprocess.run(g + list(argv), env=dict(henv, GIT_INDEX_FILE=os.path.join(run_dir, idx)),
                                  input=inp, check=True, capture_output=True).stdout.decode().strip()

        git("read-tree", tree, idx="pin.want")
        for path, (mode, body) in sorted(files.items()):
            blob = git("hash-object", "-w", "--stdin", idx="pin.want", inp=body)
            git("update-index", "--add", "--cacheinfo", f"100{mode & 0o777:o},{blob},{path}", idx="pin.want")
        want = git("write-tree", idx="pin.want")
        git("add", "-A", "-f", idx="pin.got")
        for ent in git("ls-tree", "-r", "-z", tree, idx="pin.got").split("\0"):
            meta, _, path = ent.partition("\t")
            if meta.startswith("160000 commit "):
                git("update-index", "--add", "--cacheinfo", f"160000,{meta.split()[2]},{path}", idx="pin.got")
        got = git("write-tree", idx="pin.got")
        if got != want:
            raise Unrunnable(f"the tree with main's pinned files laid over is {got}, not {want}")
        return run_dir, head
    except (Unrunnable, OSError, subprocess.CalledProcessError) as e:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise e if isinstance(e, Unrunnable) else Unrunnable(f"could not lay main's pinned files over: {e}") from None


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


_STOP = threading.local()   # .event: run_plan's `cancel`, for every execute() on the thread that runs the plan;
                            # .beat: run_plan's `beat`, which _beat() keeps


def _beat(since: float) -> None:
    """beat["since"] = when the plan's current run began, before its tree and its process (0: its process started),
    and again each poll of its slot wait (_waiting), so the lane sees a check that stops on the way (lane NOSTART)."""
    b = getattr(_STOP, "beat", None)
    if b is not None:
        b["since"] = since


def _waiting() -> bool:
    """admission's stop, asked each poll of a slot wait: a live wait keeps the beat fresh, so the lane's NOSTART never
    takes a check waiting its turn for one that never started; True when the lane has stopped the plan."""
    _beat(time.time())
    return stopped()


def stopped() -> bool:
    ev = getattr(_STOP, "event", None)
    return bool(ev is not None and ev.is_set())


def execute(argv: list, cwd: str, env: dict, cap: int, log: str, stdin=None, keep: tuple = (),
            mem: str = "") -> tuple:
    """-> (rc, secs, cpu_secs, capped, peak): peak is the bytes the run's scope held at most, its memory.peak file
    `mem` as last read while it ran (the scope goes when it exits), or wait4's ru_maxrss, the most its largest process
    held, when that never read; a green box check's next admission counts it as its need (admission MEMORY). Its own session, so the cap kills the whole group; rc < 0 is a signal.
    keep: fds the run inherits (the started pipe's write end); execute closes them once the run has its copy, or
    when it starts nothing, so only the run holds them: a host check (same user, no pid namespace) could otherwise
    write STARTED through /proc/<lander>/fd/N.
    A plan's `cancel` set (the lane: the job's PR merged, closed or moved on) kills the group the same way, and a
    stopped plan starts nothing more: rc -SIGTERM, which status_of calls unrunnable, never red."""
    t0 = time.monotonic()
    try:
        if stopped():
            return -signal.SIGTERM, 0.0, 0.0, False, 0
        with open(log, "wb") as out:
            p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                                 stdout=out, stderr=subprocess.STDOUT, start_new_session=True, pass_fds=keep,
                                 preexec_fn=None, restore_signals=True)
            _beat(0)
    finally:
        for fd in keep:
            os.close(fd)
    capped, ru, held = False, None, 0
    while True:
        if mem:
            with contextlib.suppress(OSError, ValueError), open(mem) as f:
                held = int(f.read())
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
    return rc, time.monotonic() - t0, cpu, capped, held or (ru.ru_maxrss * 1024 if ru else 0)


def starved(secs: float, cpu: float) -> bool:
    """The run went short of CPU: wall time at least STARVED times its CPU time while a load average (1, 5 or 15
    minutes, read at its end) stood at the box's cores or above. A crash on a calm box is never starved."""
    return secs >= STARVED * cpu and max(os.getloadavg()) >= (os.cpu_count() or 1)


def read_log(log: str, limit: int = 400_000) -> str:
    try:
        with open(log, "rb") as f:
            f.seek(max(0, os.path.getsize(log) - limit))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def status_of(rc: int, text: str, capped: bool = False, started: bool | None = None, net: bool = False) -> tuple:
    """-> (status, why). A clean exit with no 'N failed' above zero passes whatever it prints: a check that quotes
    a box-state error (a case that fills a disk on purpose) is not the box failing, so that text counts on rc != 0.
    started: what setup said out of band (read_started) — False is unrunnable whatever the exit, True never reads
    the output for setup's words; None (no pipe: a member, a runner) reads its first line for them.
    net: the check is a live-network one, so a failed name lookup near the end of a failed run while the box's
    resolver is down (flap_in) is unrunnable, which the lane holds and runs again rather than handing back."""
    if capped:
        return T.UNRUNNABLE, "stopped at its cap"
    if rc < 0 or rc in KILLED:
        return T.UNRUNNABLE, f"killed (exit {rc})"
    m = BOX_STATE_RE.search(text) if rc else None
    if m:
        return T.UNRUNNABLE, f"the box, not the tree: {m.group(0)}"
    head = text.lstrip()[:2000]
    s = SETUP_RE.match(head)
    if started is False:   # setup's own line wherever it is (a warning may come first), else the first line
        said = SETUP_RE.search(head)
        said = said.group(0) if said else (head.splitlines() or [f"exit {rc} with no output"])[0]
        return T.UNRUNNABLE, f"the sandbox did not start: {said[:200]}"
    if started is None and rc and s:
        return T.UNRUNNABLE, f"the sandbox did not start: {s.group(0)[:200]}"
    n = [int(x) for x in FAILED_RE.findall(text)]
    if rc == 0 and not (n and n[-1] > 0):
        return T.PASSED, ""
    r = flap_in(text) if net else None
    if r:
        return T.UNRUNNABLE, f"the network, not the tree: {r[:200]}"
    return T.FAILED, f"exit {rc}" + (f", {n[-1]} failed" if n and n[-1] else "")


def flap_in(text: str) -> str | None:
    """-> the lookup line in the last RESOLVE_TAIL lines of a failed net check when RESOLVE_PROBE does not resolve
    either, else None: with the resolver answering, a failed lookup (a typo'd host never resolves) is the tree's red."""
    for ln in reversed(text.splitlines()[-RESOLVE_TAIL:]):
        r = RESOLVE_RE.search(ln)
        if r:
            return None if resolves(RESOLVE_PROBE) else r.group(0)
    return None


def resolves(host: str, wait: float = RESOLVE_WAIT) -> bool:
    """True when the box's resolver gives host an address within wait seconds. getaddrinfo has no timeout of its own,
    so it runs on a daemon thread the caller stops waiting for."""
    got = []

    def ask():
        try:
            got.append(bool(socket.getaddrinfo(host, None)))
        except (OSError, UnicodeError):
            got.append(False)
    t = threading.Thread(target=ask, daemon=True)
    t.start()
    t.join(wait)
    return bool(got and got[0])


def red_lines(text: str) -> list:
    """-> each line red in its raw or its plain() form, named plain, so a coloured red matches a quarantine row and
    names a red without escapes. Read raw too, because stripping can eat a red: an open OSC takes its line to the end
    and a CSI the F of '\x1b[FAIL' (Opus read of #1662, 10-20)."""
    def red(ln):
        return RED_RE.search(ln) and not PASS_RE.search(ln)
    return [plain(ln).strip() for ln in text.splitlines() if red(ln) or red(plain(ln))]


# THE RATCHET'S IDS: the line a suite prints for one failing case — its own ✗/✘ line, a FAIL line, pytest's FAILED or
# ERROR id (an ERROR line only in pytest's summary form, a .py path or a node id: a log's ERROR line is no case), TAP's
# not ok — read from the whole output. A run's own scratch (a /tmp path, a sha, a duration) is
# blanked so the same case is the same id on two trees; anything else that varies makes a new id, which holds.
FAIL_ID_RE = re.compile(r"^\s*(?:[✗✘]|FAIL(?:ED)?\b:?|ERROR\s(?=\S*(?:\.py\b|::))|ERROR:\s(?=\w+ \([\w.]+\)$)"
                        r"|not ok\b(?:\s*\d+\s*-?)?)"
                        r"\s*(.*?)\s*$")
FAILS_CAP = 500   # more failing lines than this and the set is not trusted: fail_ids says None, and the red holds
# Only a scratch path and a full 40-char sha are blanked: a duration or a short hex run is part of the id, because
# blanking it made 'after 900 s' the same case as 'after 31 s' (Opus read of #1305, 10-13). A lane's scratch is
# <passwd home>/.cc/tmp since #1713, so that is blanked too.
SCRATCH_RES = ((re.compile(rf"(?:/tmp|/var/tmp|{re.escape(os.path.join(C.PASSWD_HOME, '.cc', 'tmp'))})/[^\s:'\"),]*"),
                "/tmp/…"), (re.compile(r"\b[0-9a-f]{40}\b"), "…"))


# ...and how far a run got: its pass lines or its last `N passed`, and whether it crashed or was cut short. A head that
# ran less than the base, or crashed where the base did not, hides its own reds behind main's (Opus and perms, 10-13)
PASSED_N_RE = re.compile(r"\b(\d+) passed\b")
# THE COUNT IS READ OFF A SUITE'S OWN CLOSING TALLY, the whole line: pytest's `== 2 failed, 9 passed in 1.2s ==`,
# unittest's `FAILED (failures=2, errors=1)`, a selfcheck's `x selfcheck: 9 passed, 2 failed`. Any `N failed` let a
# PR's atexit print '0 failed' after the real summary and land a new red, and read '10 failed attempts' as a count
# (perms' read of #1635, 10-20). Only pytest's own words make its tally, so '12 files in 0.30s' is none (#1644). A log
# with no such line counts its failing lines, and with none of those has no count, and the red holds.
_PYTEST_WORD = r"\d+ (?:failed|passed|errors?|skipped|deselected|xfailed|xpassed|warnings?|rerun)"
TALLY_RES = (re.compile(rf"^=*\s*((?:{_PYTEST_WORD}, )*{_PYTEST_WORD}) in [\d.]+s(?: \([\d:.]+\))?\s*=*$", re.M),
             re.compile(r"^FAILED \(((?:[a-z ]+=\d+, )*[a-z ]+=\d+)\)\s*$", re.M),
             re.compile(r"^[\w.+-]+(?: [\w.+-]+)* selfcheck: ((?:\d+ passed, )?\d+ failed(?:, \d+ skipped)?)\s*$", re.M))
TALLY_PART_RE = re.compile(r"(\d+) (failed|errors?)\b|\b(failures|errors)=(\d+)")
CRASH_RE = re.compile(r"^\s*(?:Traceback \(most recent call last\)|INTERNALERROR>)|Segmentation fault|core dumped|"
                      r"^\s*(?:Killed|Aborted)\b|\bline \d+:\s+\d+ (?:Killed|Aborted)\b", re.M)
# A terminal's escapes: CSI (colour, cursor), OSC (a title or link, ended by BEL or ST), and the two-byte rest. None
# reaches past its line, and a \r ends one: an open OSC that ate to the next escape or across a \r could swallow a
# red line
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b\r\n]*(?:\x07|\x1b\\)?|\x1b[@-Z\\-_]")


def plain(text: str) -> str:
    """`text` with its terminal escapes gone and each \\r a line break. No form read a coloured tally, so a PR that
    turned its suite's colour on printed main's tally in red, a new red, then main's tally plain, and read 3 against
    3 (Opus read of #1651, 10-20). A \\r breaks the line as splitlines() already did for the ids, so a CRLF tally
    is one and a tally a progress bar overwrote is read where it stands."""
    return ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")


def ran(text: str) -> dict:
    """-> {"passes": its last `N passed`, else its count of pass lines; "failed": tally(text); "crash": a crash or
    abort marker in it; "ends": ends(text)}, all read from plain(text)."""
    text = plain(text)
    n = PASSED_N_RE.findall(text)
    passes = int(n[-1]) if n else sum(1 for ln in text.splitlines() if PASS_RE.search(ln))
    return {"passes": passes, "failed": tally(text), "crash": bool(CRASH_RE.search(text)), "ends": ends(text)}


def ends(text: str) -> bool:
    """True when nothing but blank lines follows the last closing tally (TALLY_RES). A line after it is a red the
    tally does not count: with main's '== 3 failed ==' naming no case, a PR keeping those 3 and adding 'guard: broke
    y' read 3 against 3 and landed (perms' read of #1645, 10-20). Nor may a tally before the last count a failure: a
    PR printing main's '== 3 failed ==', then a red, then a tally again (main's or a green one) hid the red between
    them (perms' read at a25d572d, 10-20), so a failure counted in any tally but the last holds."""
    tallies = sorted((m for rx in TALLY_RES for m in rx.finditer(text)), key=lambda m: m.start())
    failing = lambda m: any(int(a or b) for a, _, _, b in TALLY_PART_RE.findall(m.group(1)))
    return bool(tallies) and not text[tallies[-1].end():].strip() and not any(map(failing, tallies[:-1]))


def tally(text: str):
    """-> the largest failure count any closing tally in `text` gives (TALLY_RES), or the failing lines after the last
    one when more; with no tally, the failing lines (one case failing twice is two). None, and the red holds, when that
    is 0 (the red came from outside every tally) or a nonzero `N failed` follows the last tally: a later line can never
    lower the count (Opus read of #1645: a green tally after a red one, or a nested tool's ahead of its caller's own)."""
    tallies = sorted((m for rx in TALLY_RES for m in rx.finditer(text)), key=lambda m: m.start())
    after = text[tallies[-1].end() if tallies else 0:]
    lines = sum(1 for ln in after.splitlines() if FAIL_ID_RE.match(ln) and not PASS_RE.search(ln))
    if tallies and any(int(n) for n in FAILED_RE.findall(after)):
        return None
    return max([lines] + [sum(int(a or b) for a, _, _, b in TALLY_PART_RE.findall(m.group(1))) for m in tallies]) or None


def case_id(full: str) -> str:
    """One failing case's stored id: the line itself up to 200 characters, else a readable prefix and a hash of the
    whole line. A plain cut made two long parametrised ids that share 200 characters one id, so a new red on the PR
    matched an old one on main (perms' read of #1635, 10-20); 64 bits of sha256 keep a crafted twin out of reach."""
    if len(full) <= 200:
        return full
    return f"{full[:182]} #{hashlib.sha256(full.encode()).hexdigest()[:16]}"


def fail_ids(text: str):
    """-> the sorted failing case ids `text` names ([] when it names none: the exit code is all there is), or None
    past FAILS_CAP. Read from plain(text), so a red ✗ is the same id as a plain one."""
    got = set()
    for ln in plain(text).splitlines():
        m = FAIL_ID_RE.match(ln)
        if not m or PASS_RE.search(ln):
            continue
        name = m.group(1)
        if "::" in name:   # pytest's `FAILED tests/x.py::t - AssertionError: …`: the id is before the message
            name = name.split(" - ", 1)[0]
        for rx, to in SCRATCH_RES:
            name = rx.sub(to, name)
        got.add(case_id(f"{ln.split()[0]} {name}"))
        if len(got) > FAILS_CAP:
            return None
    return sorted(got)


# pytest's own words for what failed: its short summary, pytest itself falling over, and a file whose progress has F/E
SUMMARY_RE = re.compile(r"^(?:FAILED|ERROR) \S+.*$", re.M)
INTERNAL_RE = re.compile(r"^INTERNALERROR> .*\b\w+(?:Error|Exception)\b.*$", re.M)
PROGRESS_RE = re.compile(r"^(\S+\.py) [.sxX]*[FE][.sxXFE]*(?:\s+\[\s*\d+%\])?$", re.M)


def cause_of(text: str, rc: int) -> str:
    """One line naming why a run is red, read from its WHOLE output, not the tail (2026-09/10: an INTERNALERROR, a
    failing check.sh line above the tail and an all-pass tail each left a red nobody could name). Read from
    plain(text), so the line carries no escape codes; the kept log stays raw."""
    text = plain(text)
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

def read_started(fd: int) -> bool:
    """Whether the run said sandbox.STARTED on its pipe; every writer is gone, so this never waits."""
    os.set_blocking(fd, False)
    try:
        return os.read(fd, 64) == S.STARTED
    except (BlockingIOError, OSError):
        return False


def _box_argv(check, head, cwd, run_dir, env_extra, started_fd=None):
    """started_fd: the write end that sandbox.started() says STARTED on, innermost: after cc-nosignal or bwrap's
    setup, before the check's own shell. sandbox.pin() moves it to sandbox.FD first, outermost, since dash takes no
    fd above 9 and the lander's own is often higher."""
    pin, said = (S.pin(started_fd), S.started(S.FD)) if started_fd is not None else ([], [])
    if M.on_host(check):
        scope = [] if check.bare else [os.path.join(BIN, "cc-nosignal"), "--"]
        return (pin + scope + said + ["/bin/sh", "-c", check.run], os.path.join(head, cwd) if cwd else head,
                clean_env(env_extra), "host")
    if not S.available():
        raise Unrunnable("bwrap is not installed, so a sandboxed check has nowhere to run")
    if check.klass == T.TIMING and A.loaded():
        raise Unrunnable("box busy: a timing check waits for an idle box")
    try:
        argv = pin + S.argv(check, head, S.write_stub(run_dir), cwd, env_extra,
                            started_fd=S.FD if started_fd is not None else None)
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
        state: str | None = None, express: bool = False, lane: bool = False, first=False,
        settle: float | None = None) -> T.Result:
    """Runner.run. Runs `check` on `tree_sha` (read from repo_root's git) at `where`, holding an admission slot
    (every slot, alone=True; none for an express run that is not alone: the lane's EXPRESS bounds those). Stores
    nothing: the lane stores what it wants (records.Store). cwd: the check's manifest prefix. changed: the change's
    files, handed in as CC_LAND_CHANGED. base_tree: the other side, for the built-in manifest-widen, as the check
    repo's refs/lander/base (materialise), and where a PINNED check's files come from for its second pass, which runs
    only when the head's own pass passed, in a head written out afresh (pinned_head), and whose red is the result. lane: a landing lane's run, whose slot ticket goes before a worker's
    (admission). first: main health's, a main-red fix's or a put-first job's run (a callable from the lane, asked
    while it waits), whose ticket goes ahead of every younger one (admission FIRST CLAIM). settle: an alone run's
    wait for every slot before it runs beside others (admission SETTLE); None waits for every slot however long that takes."""
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
    _beat(time.time())
    try:
        run_dir, head = materialise(repo_root, tree_sha, label, base_tree)
    except Unrunnable as e:
        return res(T.UNRUNNABLE, str(e))
    try:
        pinned = pins(repo_root, check, cwd, base_tree, tree_sha)
    except (OSError, G.GitError) as e:
        shutil.rmtree(run_dir, ignore_errors=True)
        return res(T.UNRUNNABLE, f"could not read main's pinned files: {e}")

    def attempt(head: str, run_dir: str) -> T.Result:
        if kind != "laptop":
            return _attempt(check, tree_sha, where, "", head, run_dir, cwd, env_extra, alone, state, express, lane,
                            first, settle, repo_root)
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
            r = _attempt(check, tree_sha, where, dest, head, run_dir, cwd, env_extra, alone, state, express, lane, first,
                         settle, repo_root)
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

    dirs = [run_dir]
    try:
        # a laptop run's head is a copy on the runner, so only a run here can be held to the base it was given
        want = base_of(head) if kind != "laptop" else ""
        r = base_kept(attempt(head, run_dir), head, want)
        if not pinned or r.status != T.PASSED:
            return r
        # the head's own copies passed; main's (PINNED) now judge the same tree, written out afresh (pinned_head): the
        # PR's script ran read-write in `head`. Off the box a runner proves the tree it gets by write-tree, which a
        # laid-over tree is not, so that pass runs on the box
        if kind == "laptop" and "box" not in {w.split(":")[0] for w in check.where}:
            raise Unrunnable("main's pinned files run on the box only, and this check may not run there")
        p_dir, p_head = pinned_head(repo_root, tree_sha, label, base_tree, pinned)
        dirs.append(p_dir)
        p_want = base_of(p_head)
        if kind == "laptop":
            p = _attempt(check, tree_sha, "box", "", p_head, p_dir, cwd, env_extra, alone, state, express, lane,
                         first, settle, repo_root)
        else:
            p = attempt(p_head, p_dir)
        p = base_kept(p, p_head, p_want)
        names = sorted(pinned)
        if p.status != T.PASSED:
            p.extra["why"] = f"with main's {', '.join(names)}: {p.extra.get('why', '')}"
            p.extra["pinned"] = names
            return p
        r.secs, r.cpu_secs = round(r.secs + p.secs, 2), round(r.cpu_secs + p.cpu_secs, 2)
        r.extra["pinned"] = names
        return r
    except Unrunnable as e:
        return res(T.UNRUNNABLE, str(e))
    finally:
        for d in dirs:
            shutil.rmtree(d, ignore_errors=True)


def _attempt(check, tree_sha, where, dest, head, run_dir, cwd, env_extra, alone, state, express, lane,
             first=False, settle=None, repo=".") -> T.Result:
    """One run of `check` at `where` (on the runner `dest` when that is the laptop kind); Result.runner names the
    runner that took it: `laptop:<user@host>:-` off the box."""
    kind = where.split(":")[0]
    log = os.path.join(run_dir, "log")
    pipe = list(os.pipe()) if kind == "box" else []   # [read, write]: setup says it started on it (sandbox.started)
    try:
        stdin, tar = None, None
        if kind == "laptop":
            argv, wd, env, how = laptop_argv(check, tree_sha, cwd, dest), run_dir, clean_env(), dest
            tar = subprocess.Popen(["tar", "-C", head, "-cf", "-", "."], stdout=subprocess.PIPE)
            stdin = tar.stdout
        elif kind == "member":
            argv, wd, env, how = _member_argv(check, head, cwd, where, env_extra)
        else:
            argv, wd, env, how = _box_argv(check, head, cwd, run_dir, env_extra, started_fd=pipe[1])
        scope = "-"
        # the laptop's work is the laptop's: it takes no slot of the box's; nor does an express run (lane EXPRESS)
        free = kind == "laptop" or (express and not alone)
        k = A.slots() if alone else None
        sd = state or REC.state_dir()
        held = contextlib.nullcontext() if free else A.slot(sd, alone=alone, who=f"{check.name}@{tree_sha[:8]}",
                                                            lane=lane, first=first, k=k,
                                                            settle=settle if alone else None, stop=_waiting,
                                                            need=A.peak(sd, repo, check.name))
        with held as got:
            settled = alone and got is not None and len(got) < k   # SETTLE: it waited out settle and ran beside others
            alone = alone and not settled
            loaded = A.loaded()
            if kind == "box":   # wrapped once the slot is held, so the priority answers for the load it starts under
                argv, scope = A.wrap(check, argv, f"{check.name}-{tree_sha[:8]}", busy=bool(A.overloaded()))
            # the write end is execute's from here: it closes it once the run has it (pipe keeps only the read end)
            rc, secs, cpu, capped, peak = execute(argv, wd, env, check.cap, log, stdin,
                                                  keep=(pipe.pop(),) if pipe else (), mem=A.scope_peak(argv))
            if kind == "box" and rc == 0 and not capped:   # a red may have died before its peak (admission MEMORY)
                A.record(sd, repo, check.name, peak)
            # under load at either end of the run, or starved through it (dispatch #1504, 10-21: 1421 s for 774 s of
            # CPU at load 32.7, four timeouts, and neither end's PSI saw it)
            # A PR's own check sets its wall-to-CPU ratio (a sleep is enough), so a red loaded by that alone
            # and short of its cap is `starved`: judge() reruns it only for a check that is not security or touched
            pressed = loaded or A.loaded()
            hungry = kind == "box" and starved(secs, cpu)
            loaded, thin = pressed or hungry, hungry and not pressed and not capped
        said = None
        if pipe:   # each fd is closed once: another thread's run may take its number next
            said = read_started(pipe[0])
        if tar is not None:
            tar.stdout.close()
            tar.wait()
        text, started = read_log(log), {}
        if kind == "laptop":
            started = {"never_started": never_started(text, capped)} if dest else {}
            text, rc = _laptop_verdict(text, rc)
        st, why = status_of(rc, text, capped, started=said, net=check.net)
        if st == T.FAILED and settled and loaded:   # the rerun alone it stood for never ran: no answer, not a red
            st, why = T.UNRUNNABLE, f"red under load again, and no run alone in {settle / 60:.0f} min"
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
                        extra={"why": why, "rc": rc, "loaded": loaded, "starved": thin, "alone": alone,
                               "tail": text.splitlines()[-TAIL:], **kept, **started})
    except (Unrunnable, TimeoutError) as e:   # TimeoutError: stopped while it waited for a slot (admission STOP)
        return T.Result(check=check.name, tree=tree_sha, status=T.UNRUNNABLE, secs=0.0, load=os.getloadavg()[0],
                        runner=f"{where}:{dest}:-" if dest else where, extra={"why": str(e), "not_sent": True})
    finally:
        for fd in pipe:
            with contextlib.suppress(OSError):
                os.close(fd)


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
    loaded = bool(r.extra.get("loaded")) and not (r.extra.get("starved") and (security or touched))
    if loaded or (not security and not touched):
        r2 = go(head_tree, alone=loaded)
        out.results.append(r2)
        if r2.status == T.PASSED:
            out.status, out.note = T.PASSED, ("flaky: red, then green on the same tree" if not loaded
                                              else "flaky: red under load, green on a rerun"
                                              if r2.extra.get("alone") is False   # SETTLE ran it beside others
                                              else "flaky: red under load, green alone")
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
    case failing twice, or a lost test masked by an added passing one). A count ran() could not read (None) holds, named
    or not (Opus read of #1645). When neither run names a case, the count is all there is: it passes only when both
    runs print a failure count and end on their tally (ends), so no red after the tally goes uncounted; a head that
    names none against a base that does, or a set fail_ids could not trust (None), holds."""
    pr, main = head.extra.get("fails"), base.extra.get("fails")
    hf, bf = head.extra.get("failed", 0), base.extra.get("failed", 0)
    same = head.runner.split(":")[0] == base.runner.split(":")[0]
    went = (head.extra.get("passes") or 0) >= (base.extra.get("passes") or 0) and \
        not (head.extra.get("crash") and not base.extra.get("crash")) and None not in (hf, bf) and hf <= bf
    named = bool(pr) and main is not None and set(pr) <= set(main)
    counted = pr == [] and main == [] and None not in (head.extra.get("failed"), base.extra.get("failed")) \
        and bool(head.extra.get("ends")) and bool(base.extra.get("ends"))
    return same and went and (named or counted)


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
    if M.on_host(check):
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
             lane: bool = False, caged: bool = False, main=None, first=False, beat=None) -> dict:
    """Every check in plan.checks through judge(), one after another; -> {name: Outcome}. The lane calls it with
    its store; `lander check` with none (a worker's own red is its work, and is not recorded). fallback: the host
    manifest `m` was loaded with (manifest.host_fallback), so the base is judged by the same checks. cancel: a
    threading.Event the lane sets to stop the plan; every execute() on this thread polls it. express: the lane's
    EXPRESS (a Δ rerun's check), whose runs take no admission slot; a diagnostic rerun alone still takes them all.
    lane=True from the lane only: its box runs wait ahead of a worker's (run's `lane`). first from the lane: a
    callable, true for a main-red fix or a job put first, whose box runs take the first claim on a slot (run's
    `first`). beat: a dict _beat() keeps for the lane (NOSTART). runners=True from the lane
    only: it found no box slot for these checks, so each that may leave goes to the runners (choose_where).
    caged=True (`lander check --caged-only`): a check uncaged() names is DEFERRED, never run and never a pass, and the
    rest go where choose_where puts the lane's: one that may leave goes to a runner's cage while this box is full. main: {check: status} of main's own record on exactly base_tree (health.at), which
    judge() takes in place of a base run."""
    _STOP.event, _STOP.beat = cancel, beat
    try:
        return _run_plan(repo_root, m, plan, files, head_tree, base_tree, member=member, store=store,
                         job_key=job_key, scope=scope, pr=pr, quarantine_text=quarantine_text, runner=runner,
                         only=only, record_reds=record_reds, fallback=fallback, box_only=box_only, runners=runners,
                         express=express, lane=lane, caged=caged, main=main or {}, first=first)
    finally:
        _STOP.event = _STOP.beat = None


def _run_plan(repo_root, m, plan, files, head_tree, base_tree, *, member, store, job_key, scope, pr,
              quarantine_text, runner, only, record_reds, fallback, box_only, express, lane, caged=False,
              runners=False, main=None, first=False):
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
        lacks = missing_run(repo_root, base_tree, head_tree, base_m, name)
        if lacks:
            # main once registered a check before the PR that brought its script, and the lane handed back
            # every PR on "not found" when only that one PR could fix it
            out[name] = Outcome(name, BLOCKED, f"{BLOCKED}:{name} (main registered it, but its run file {lacks} "
                                               "is on neither the base nor the merge tree)")
            continue
        own = [p for p in c.paths if "*" not in p] + [m.cwd.get(name, "") + M.run_file(c.run)]
        # perms' terms (#1234): manifest-widen's "red blocks as a fault, never advisory", so it is never quarantined
        security = name == M.BUILTIN or any(M.match(list(m.policy.gate_first) + list(m.policy.security_review) +
                                                     list(SECURITY_PATHS), p) for p in own if p)
        # SETTLE waits out the longest a check holding a slot may run; a security check never settles, because a
        # member who loads the box could otherwise trade its rerun alone for a loaded one, where a green passes
        settle = None if security else max([c.cap] + [o.cap for o in m.checks.values()])
        touched = any(m.owns(name, f) for f in files) if name in m.checks else False
        where = choose_where(c, member, box_only=box_only, runners=runners)
        if gone and where == "laptop" and "box" in c.where:
            where = "box"   # the laptop gave no answer once in this plan: do not wait out its timeout per check
        out[name] = judge(c, head_tree, base_tree, where, runner=runner, store=store,
                          job_key=job_key, security=security, touched=touched, quarantine=rows, record=record,
                          on_base=name == M.BUILTIN or runs_on_base(repo_root, base_tree, base_m, name),
                          main=(main or {}).get(name, ""),
                          repo_root=repo_root, cwd=m.cwd.get(name, ""), changed=files,
                          label=".".join(job_key.rsplit("-", 1)) if job_key else "lander.0",
                          **({"express": True} if express else {}), **({"lane": True} if lane else {}),
                          **({"first": True} if first else {}), **({"settle": settle} if settle else {}))
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


def missing_run(repo_root: str, base_tree: str, head_tree: str, base_m, name: str) -> str:
    """The run file of check `name` when the base manifest defines it and neither the base tree nor the head's has
    that file, else '': main's gap, which no change but the one that brings the file can close."""
    if not base_tree or base_m is None or name not in base_m.checks:
        return ""
    f = M.run_file(base_m.checks[name].run)
    p = base_m.cwd.get(name, "") + f
    if not f or M.read_at(repo_root, base_tree, p) is not None or M.read_at(repo_root, head_tree, p) is not None:
        return ""
    return p


def quarantine_text(repo_root: str, rev: str) -> str:
    return "\n".join(t for t in (M.read_at(repo_root, rev, p + REC.QUARANTINE) for p in M.PREFIXES) if t)


COMMANDS = {"job-serve": (cmd_job_serve, "the laptop's end of a spilled check: hands one job to cc-suites runner, caged")}
