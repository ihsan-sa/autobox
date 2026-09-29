"""run(): one check on one tree, safely; judge(): what a red means (design §0 Execution, Red main vs red diff; B2, B5).

THE TREE. A run never touches a checkout. materialise() writes the tree's files out of git into
`$TMPDIR/cc-land.run.<pid>.<rand>/cc-land.gates.<repo>.<pr>.<rand>/head` (the shape cc-tmp-reap and `cc-sandbox member
--tree` accept), makes it a git repo with one commit and proves `git write-tree` there equals the tree asked for
(B1: the identity check greps a real work tree). Everything under the run directory goes when the run ends.

THE RUNNER (`where`, one of the check's own `where` list, or `member:<h>[:<t>]` for a member's landing):
  box      by class — static, hermetic and timing in the bwrap profile (sandbox.py); host and box on the host with
           the environment scrubbed as today's clean_start (no CLAUDE*, no token-shaped variables, CC_CONFIG_DENY set).
           Every one inside an admission slot and a transient scope (admission.py). Timing runs only while the box
           is not loaded. No bwrap on this machine makes a sandboxed class unrunnable, never a host run.
  laptop   static and hermetic only, over cc-suites' own transport: its key, the destination and the pinned host key
           in ~/.cc/suites (CC_SUITES_DIR: id_ed25519, remote, known_hosts, StrictHostKeyChecking=yes), so the laptop
           is configured exactly when cc-suites' runner is, and a destination known_hosts does not name is refused
           before ssh starts. The tree goes to the runner's `job` form (`cc-suites runner`, the key's forced command),
           which unpacks it into a fresh directory with a fresh HOME per job, proves it by write-tree, runs it and
           removes both; `lander job-serve` is the same end in Python. Busy, on battery, unfit or not answering is
           unrunnable there, never red, and judge() then runs the check on the box.
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
import time
from dataclasses import dataclass, field

from lander import admission as A
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
        genv = {**os.environ, "GIT_INDEX_FILE": os.path.join(run_dir, "index")}
        for argv in (["git", "-C", repo_root, "read-tree", tree],
                     ["git", "-C", repo_root, "checkout-index", "-a", "-f", f"--prefix={head}/"]):
            p = subprocess.run(argv, env=genv, capture_output=True, text=True)
            if p.returncode:
                raise Unrunnable(f"could not write the tree out: {p.stderr.strip()[-300:]}")
        g = ["git", "-C", head, "-c", "user.name=lander", "-c", "user.email=lander@localhost"]
        subprocess.run(g + ["init", "-q"], check=True, capture_output=True)
        subprocess.run(g + ["add", "-A", "-f"], check=True, capture_output=True)
        # a submodule (gitlink) is written out as an empty directory, which add cannot turn back into the link; it
        # has no files to prove, so it is taken from the tree itself (a repo with a submodule was never runnable)
        ls = subprocess.run(["git", "-C", repo_root, "ls-tree", "-r", "-z", tree], capture_output=True, text=True)
        if ls.returncode:
            raise Unrunnable(f"could not list the tree: {ls.stderr.strip()[-300:]}")
        for ent in ls.stdout.split("\0"):
            meta, _, path = ent.partition("\t")
            if meta.startswith("160000 commit "):
                subprocess.run(g + ["update-index", "--add", "--cacheinfo", f"160000,{meta.split()[2]},{path}"],
                               check=True, capture_output=True)
        got = subprocess.run(g + ["write-tree"], capture_output=True, text=True).stdout.strip()
        if got != tree:
            raise Unrunnable(f"the tree written out is {got or 'none'}, not {tree}")
        subprocess.run(g + ["commit", "-qm", f"tree {tree}", "--no-verify"], check=True, capture_output=True)
        return run_dir, head
    except (Unrunnable, OSError, subprocess.CalledProcessError) as e:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise e if isinstance(e, Unrunnable) else Unrunnable(f"could not write the tree out: {e}") from None


def tree_of(repo_root: str, rev: str) -> str:
    """The tree id of a commit or tree; rev "" is the working copy (tracked and untracked, not ignored)."""
    if rev:
        p = subprocess.run(["git", "-C", repo_root, "rev-parse", f"{rev}^{{tree}}"], capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else ""
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


def execute(argv: list, cwd: str, env: dict, cap: int, log: str, stdin=None) -> tuple:
    """-> (rc, secs, cpu_secs, capped). Its own session, so the cap kills the whole group; rc < 0 is a signal."""
    t0 = time.monotonic()
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
        if time.monotonic() - t0 > cap:
            capped = True
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


def laptop_argv(check, tree, cwd):
    dest = laptop_dest()
    if not dest:
        raise Unrunnable(f"no laptop is configured (cc-suites: {_suites_dir()})")
    if check.klass not in (T.STATIC, T.HERMETIC):
        raise Unrunnable(f"a {check.klass} check does not leave the box")
    d = _suites_dir()
    kh, host = os.path.join(d, "known_hosts"), dest.split("@", 1)[1]
    with open(kh) as f:
        pinned = {h for ln in f if ln.strip() and not ln.startswith("#") for h in ln.split()[0].split(",")}
    if host not in pinned:
        raise Unrunnable(f"the laptop {host} has no pinned host key in {kh}")
    b = lambda s: base64.b64encode(s.encode()).decode() or "-"   # noqa: E731
    # cc-suites xport_argv's options, so this is the path the owner approved and no other
    return ["ssh", "-F", "/dev/null", "-i", os.path.join(d, "id_ed25519"), "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=4", "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={kh}",
            "-o", "GlobalKnownHostsFile=/dev/null", "-o", "ClearAllForwardings=yes",
            "-o", "KexAlgorithms=curve25519-sha256", "-a", "-x", "-T", "-C", dest, "--",
            "job", check.name, tree, str(check.cap), b(check.run), b(cwd)]


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
        argv, scope = A.wrap(check, argv, f"{check.name}-{tree_sha[:8]}") if kind == "box" else (argv, "-")
        # the laptop's work is the laptop's: it takes no slot of the box's
        held = contextlib.nullcontext() if kind == "laptop" else A.slot(state or REC.state_dir(), alone=alone)
        with held:
            loaded = A.loaded()
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
        return T.Result(check=check.name, tree=tree_sha, status=st, secs=round(secs, 2), cpu_secs=round(cpu, 2),
                        load=os.getloadavg()[0], runner=f"{where}:{how}:{scope}",
                        cases=[{"name": ln[:200], "status": T.FAILED} for ln in red_lines(text)[:50]]
                        if st == T.FAILED else [],
                        extra={"why": why, "rc": rc, "loaded": loaded, "alone": alone,
                               "tail": text.splitlines()[-TAIL:]})
    except Unrunnable as e:
        return res(T.UNRUNNABLE, str(e))
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def _laptop_verdict(text: str, rc: int) -> tuple:
    """job-serve relays the check's lines as `| …` and ends `lander-job: verdict exit=N`; anything else is no
    answer (-1: unrunnable)."""
    lines = text.splitlines()
    got = [ln for ln in lines if ln.startswith("lander-job: verdict exit=")]
    body = "\n".join(ln[2:] for ln in lines if ln.startswith("| "))
    if rc != 0 or len(got) != 1:
        refused = next((ln for ln in lines if not ln.startswith("| ")), "no answer")
        return f"laptop refused or did not answer: {refused[:200]}\n{body}", -1
    return body, int(got[0].rsplit("=", 1)[1])


# --- the laptop's end ----------------------------------------------------------------------------------------------

def cmd_job_serve(argv):
    """The laptop's forced command: `job CHECK TREE CAP RUN_B64 CWD_B64` from SSH_ORIGINAL_COMMAND (or argv), the
    tree as a tar on stdin. Every job gets a fresh directory and a fresh HOME, both removed after."""
    a = (os.environ.get("SSH_ORIGINAL_COMMAND") or " ".join(argv)).split()
    if len(a) != 6 or a[0] != "job" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", a[1]) \
            or not re.fullmatch(r"[0-9a-f]{40}", a[2]) or not a[3].isdigit():
        print("lander-job: refused: job CHECK TREE CAP RUN_B64 CWD_B64")
        return 2
    try:
        run_line = base64.b64decode(a[4], validate=True).decode()
        cwd = base64.b64decode(a[5], validate=True).decode() if a[5] != "-" else ""
    except (ValueError, UnicodeDecodeError):
        print("lander-job: refused: bad encoding")
        return 2
    if cwd.startswith("/") or ".." in cwd.split("/"):
        print("lander-job: refused: cwd leaves the tree")
        return 2
    job = tempfile.mkdtemp(prefix="lander-job.")
    try:
        work, home = os.path.join(job, "tree"), os.path.join(job, "home")
        os.mkdir(work)
        os.mkdir(home)
        if subprocess.run(["tar", "-x", "-C", work, "-f", "-", "--no-same-owner"], stdin=sys.stdin.buffer).returncode:
            print("lander-job: refused: the tree did not unpack")
            return 1
        g = ["git", "-C", work, "-c", "user.name=lander", "-c", "user.email=lander@localhost"]
        # the tar carries the box's one-commit repo; the tree is proved from the files, not from what it says
        shutil.rmtree(os.path.join(work, ".git"), ignore_errors=True)
        subprocess.run(g + ["init", "-q"], capture_output=True)
        subprocess.run(g + ["add", "-A", "-f"], capture_output=True)
        if subprocess.run(g + ["write-tree"], capture_output=True, text=True).stdout.strip() != a[2]:
            print("lander-job: refused: the unpacked tree is not the one named")
            return 1
        subprocess.run(g + ["commit", "-qm", "tree", "--no-verify"], capture_output=True)
        env = {"HOME": home, "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "TERM": "dumb",
               "TMPDIR": job, "USER": os.environ.get("USER", "lander"), "CC_SELFTEST_SPILL": "0"}
        log = os.path.join(job, "log")
        rc, _, _, capped = execute(["/bin/sh", "-c", run_line], os.path.join(work, cwd), env, int(a[3]), log)
        for ln in read_log(log).splitlines():
            print("| " + ln)
        print(f"lander-job: verdict exit={124 if capped else rc}")
        return 0
    finally:
        shutil.rmtree(job, ignore_errors=True)


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
        # a laptop that cannot take it (busy, on battery, gone) is no answer: the box runs it, as cc-suites spill did
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


def choose_where(check: T.Check, member: str = "") -> str:
    """member:<h> for a member's landing; the laptop when the box is loaded and the check may go; else box."""
    if member:
        return f"member:{member}"
    if "laptop" in check.where and check.klass in (T.STATIC, T.HERMETIC) and A.loaded() and laptop_dest():
        return "laptop"
    return "box"


def run_plan(repo_root: str, m: M.Manifest, plan: T.Plan, files: list, head_tree: str, base_tree: str = "", *,
             member: str = "", store=None, job_key: str = "", scope: str = "", pr: int | None = None,
             quarantine_text: str = "", runner=None, only=None, record_reds: bool = True,
             fallback: str = "") -> dict:
    """Every check in plan.checks through judge(), one after another; -> {name: Outcome}. The lane calls it with
    its store; `lander check` with none (a worker's own red is its work, and is not recorded). fallback: the host
    manifest `m` was loaded with (manifest.host_fallback), so the base is judged by the same checks."""
    rows = REC.quarantine_rows(quarantine_text)
    record = (lambda r, text: REC.record_red(scope, r, text, pr)) if (record_reds and scope) else None
    base_m = M.load(repo_root, base_tree, fallback=fallback, strict=False) if base_tree else None
    out, laptop_gone = {}, False
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
        where = choose_where(c, member)
        if laptop_gone and where == "laptop" and "box" in c.where:
            where = "box"   # the laptop gave no answer once in this plan: do not wait out its timeout per check
        out[name] = judge(c, head_tree, base_tree, where, runner=runner, store=store,
                          job_key=job_key, security=security, touched=touched, quarantine=rows, record=record,
                          on_base=name == M.BUILTIN or runs_on_base(repo_root, base_tree, base_m, name),
                          repo_root=repo_root, cwd=m.cwd.get(name, ""), changed=files,
                          label=".".join(job_key.rsplit("-", 1)) if job_key else "lander.0")
        laptop_gone = laptop_gone or any("laptop" in r.extra for r in out[name].results)
    return out


def runs_on_base(repo_root: str, base_tree: str, base_m, name: str) -> bool:
    """Whether the base tree can run check `name` at all: its manifest defines it and its run file is there."""
    if not base_tree or base_m is None or name not in base_m.checks:
        return False
    f = M.run_file(base_m.checks[name].run)
    return not f or M.read_at(repo_root, base_tree, base_m.cwd.get(name, "") + f) is not None


def quarantine_text(repo_root: str, rev: str) -> str:
    return "\n".join(t for t in (M.read_at(repo_root, rev, p + REC.QUARANTINE) for p in M.PREFIXES) if t)


COMMANDS = {"job-serve": (cmd_job_serve, "the laptop's end of a spilled check: one job, fresh HOME, removed after")}
