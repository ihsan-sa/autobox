"""Deploy: merged main, at exactly the sha the tip run passed, onto a target checkout, and proof it took.

    request(repo, sha, targets)   ask for `sha` to go to `targets` (checkout names under $CC_DEV; the repo's own by
                                  default). Written to deploy/<repo>.json; nothing runs yet.
    run(repo, green=tip.green)    does a request whose sha the tip passed, target by target; a held target is
                                  skipped on its own and the rest go
    hold(target, why) · release(target) · held(target)    the per-target hold the tip run sets on red

The request file is not land/<repo>-deploy.json, because the old lander still reads that one until cutover.

THE STEPS, per target, in order; the first that fails stops that target and says so:

  1. branch   the checkout is on its base branch (board `default_branch`, else main)
  2. pull     under the repo's git lock (U1's, shared with cc-publish): verified_tip fetches <base> from the URL the
              lander holds (git.remote_url, never the checkout's "origin") and checks it against ls-remote; a sha
              that is not that tip or an ancestor of it is refused; then `git merge --ff-only <sha>`, so a
              checkout a person moved is refused, never reset
  3. install  the first executable of core/install.sh, install.sh, with no flags; then `systemctl --user
              daemon-reload`; then <repo>.applied records the sha
  4. units    a systemd-user unit this change ADDED is enabled with `enable --now`, unless its .timer does it, it
              has no [Install], install.sh did not link it, or `cc-units policy <u> enable` says owner — then the
              owner gets one 🔐 card with the command, and nothing else asks him (S5)
  5. restart  a linked .service whose Exec runs a changed file, or that `cc-units restart-for` names, is restarted
              and PROVED by a new MainPID. `cc-units` policy none skips it; policy owner files a cc-scope restart
              ask (scope.owner_ask). tmux-main.service is NEVER restarted: it holds every session on the box.
  6. daemons  `cc-units daemons-for`: a bare process running a changed program is restarted by its policy's
              command and PROVED by a pid that was not there before
  7. verify   the track's open cc-scope asks run their own checks (scope.deliver) — LAST, so what it measures is
              what now runs. A check that is red, absent or could not run leaves the deploy `unverified`,
              and one card says it was deployed but NOT delivered (`lander deploy` exits 4, as UNVERIFIED did)

A member workspace's repo (`<h>--<t>`) installs nothing: no units, no restarts; its request is answered "nothing to
deploy". The request's `targets` map records each target's state: requested, held, deployed, verified, unverified
or failed, with the step and why; `from` is what was deployed before it, and every target (and every retry of a
failed one) takes its changed files from `from`..sha. A request with no target requested or held stops no catch-up.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import re
import shlex

from lander import cards as C
from lander import git as G
from lander import scope

NEVER = "tmux-main.service"
UNIT_RE = re.compile(r"(?:^|/)systemd-user/([^/]+\.(?:service|timer))$")
EXEC_RE = re.compile(r"^Exec[A-Za-z]*=(.*)$", re.M)


class Failed(Exception):
    def __init__(self, step, why):
        super().__init__(f"{step}: {why}")
        self.step, self.why = step, why


# --- the request and holds -----------------------------------------------------------------------------------------

def req_path(repo):
    return C.state("deploy", f"{repo}.json")


def hold_path(target):
    return C.state("holds", f"{target}.json")


def request(repo, sha, targets=None):
    """A new request replaces the old one. When the old one still has a target that did not finish (anything but
    verified), its `from` is kept, so the new diff still covers the change it owed (a restart that failed, say)."""
    targets = list(targets or [repo])
    old = C.read_json(req_path(repo)) or {}
    since = applied(repo)
    if old.get("from") and any((st or {}).get("state") != "verified" for st in (old.get("targets") or {}).values()):
        since = old["from"]
    C.write_json(req_path(repo), {"repo": repo, "sha": sha, "at": C.now(), "from": since,
                                  "targets": {t: {"state": "requested"} for t in targets}})
    C.log("deploy-requested", repo, "deploy", sha=sha[:12], targets=",".join(targets))


def hold(target, why, sha=""):
    C.write_json(hold_path(target), {"at": C.now(), "why": why, "sha": sha})


def release(target):
    with contextlib.suppress(OSError):
        os.unlink(hold_path(target))


def held(target):
    return C.read_json(hold_path(target))


WAITING = ("requested", "held")
TRIES = 3   # a failed target is deployed again by this many calls of run(), then waits for a new request


def waiting(repo):
    """True while the repo's deploy request still has a target to do (requested, or held by a red tip). A request
    whose every target finished is history: it stops nothing, so a later hand merge is still caught up."""
    req = C.read_json(req_path(repo)) or {}
    return any((st or {}).get("state") in WAITING for st in (req.get("targets") or {}).values())


def applied(repo):
    return (C.read_json(C.state(f"{repo}.applied"), {}) or {}).get("sha", "")


def record_applied(repo, sha):
    C.write_json(C.state(f"{repo}.applied"), {"sha": sha, "at": C.now()})


# --- small box calls -----------------------------------------------------------------------------------------------

def root_of(target):
    return os.path.join(os.path.expanduser(C.conf("CC_DEV", "~/dev")), target)


def base_of(repo):
    d = C.read_json(os.path.join(os.path.expanduser(C.conf("CC_BOARDS", "~/.cc/boards")), f"{repo}.json"), {})
    return (d or {}).get("default_branch") or "main"


def git(root, *args, timeout=300):
    rc, out = C.sh(["git", *args], cwd=root, timeout=timeout)
    return rc, out.strip()


def last(out, n=200):
    return " ".join(str(out).split())[-n:]


def systemctl(*args, timeout=120):
    return C.sh(["systemctl", "--user", *args], timeout=timeout)


def units_dir():
    return os.path.expanduser(C.conf("CC_UNITS_DIR", "~/.config/systemd/user"))


def linked():
    try:
        return sorted(f for f in os.listdir(units_dir()) if f.endswith((".service", ".timer")))
    except OSError:
        return []


def unit_text(u):
    try:
        with open(os.path.join(units_dir(), u)) as f:
            return f.read()
    except OSError:
        return ""


def cc_units(*args, timeout=120):
    return C.sh([os.path.join(C.BIN, "cc-units"), *args], timeout=timeout)


@contextlib.contextmanager
def git_lock(root):
    """U1's lock when lander/git.py is there (it is the one cc-publish shares); the same file, taken the same way,
    when it is not yet."""
    try:
        from lander.git import git_lock as lock  # type: ignore[import-not-found]
    except ImportError:
        lock = None
    if lock is not None:
        with lock(root):
            yield
        return
    gitdir = os.path.join(root, ".git")
    if os.path.isfile(gitdir):
        with open(gitdir) as f:
            g = f.read().strip().removeprefix("gitdir:").strip()
        g = os.path.normpath(os.path.join(root, g))
        gitdir = os.path.dirname(os.path.dirname(g)) if os.path.basename(os.path.dirname(g)) == "worktrees" else g
    fd = None
    try:
        fd = os.open(os.path.join(gitdir, "cc-land.lock"), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        pass
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)


def verified_tip(root, base):
    """origin's <base> as the lander may trust it, or '' on any doubt: the sha git.fetch reports origin sent from the
    lander's own URL (fetched borrowed, so no config or hook of the checkout's runs or steers it), and ls-remote names
    the same sha. The caller holds git_lock."""
    url = G.remote_url(root)
    if not url or not re.fullmatch(r"[A-Za-z0-9._/-]+", base or ""):
        return ""
    try:
        sha = G.fetch(root, base)[base]
    except G.GitError:
        return ""
    return sha if G.ls_remote(root, url, base) == sha else ""


# --- the steps -----------------------------------------------------------------------------------------------------

def pull(root, base, sha, since=""):
    """Fast-forward to `sha`; -> the (status, path) changes from `since` (what was deployed before this request) to
    `sha`. Not from the checkout's HEAD: on a retry after a failed install or restart the checkout is already at `sha`,
    and a diff from there would be empty, so the retry would skip every unit and restart."""
    rc, cur = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if rc or cur != base:
        raise Failed("branch", f"{root} is on '{cur}', not '{base}' — deploy from the default-branch checkout")
    _, before = git(root, "rev-parse", "HEAD")
    if since and git(root, "cat-file", "-e", f"{since}^{{commit}}")[0] == 0:
        before = since
    with git_lock(root):
        tip = verified_tip(root, base)
        if not tip:
            raise Failed("pull", f"origin/{base} could not be fetched from the lander's own remote and checked "
                                 f"against it; nothing merged in {root}")
        if sha != tip and git(root, "merge-base", "--is-ancestor", sha, tip)[0] != 0:
            raise Failed("pull", f"{sha[:12]} is not on origin/{base} ({tip[:12]}); nothing merged in {root}")
        rc, out = git(root, "merge", "--ff-only", "-q", sha)
    if rc:
        raise Failed("pull", f"git merge --ff-only {sha[:12]} in {root}: {last(out)}")
    rc, out = git(root, "diff", "--name-status", "--no-renames", "-z", before, sha)
    parts = out.split("\0") if rc == 0 else []   # -z: status, path, status, path, ... each path as it is
    return [(s[:1], p) for s, p in zip(parts[0::2], parts[1::2]) if s and p]


def install(root, repo, sha):
    inst = next((p for p in ("core/install.sh", "install.sh") if os.access(os.path.join(root, p), os.X_OK)), "")
    if inst:
        path = os.path.join(root, inst)
        rc, out = C.sh([path], cwd=os.path.dirname(path), timeout=900)
        if rc:
            raise Failed("install", f"{inst}: {last(out)}")
        systemctl("daemon-reload")
    record_applied(repo, sha)
    return f"installed with {inst}" if inst else "pulled; no install.sh to run"


def enable_units(changes, repo, sha):
    added = [m.group(1) for s, p in changes if s == "A" for m in [UNIT_RE.search(p)] if m]
    have, notes, on = linked(), [], []
    for u in added:
        stem, ext = u.rsplit(".", 1)
        if ext == "service" and f"{stem}.timer" in set(added) | set(have):
            notes.append(f"{u} runs from its timer")
            continue
        if u not in have:
            notes.append(f"{u} is not linked (install.sh names its units one by one — add it there)")
            continue
        if ext == "service" and "[Install]" not in unit_text(u):
            notes.append(f"{u} has no [Install]")
            continue
        _, pol = cc_units("policy", u, "enable", timeout=30)
        if pol.strip() == "owner":
            C.owner_card(f"land:{repo}:deploy:enable-{u}@{sha[:12]}",
                         f"[{repo}] {u} is new, and cc-units keeps turning it on for you: "
                         f"`systemctl --user enable --now {u}`", run=f"systemctl --user enable --now {u}")
            notes.append(f"{u} linked and left off; the owner has the card")
            continue
        _, st = systemctl("is-enabled", u)
        if st.strip() == "enabled":
            notes.append(f"{u} already on")
            continue
        rc, out = systemctl("enable", "--now", u)
        if rc:
            raise Failed("units", f"systemctl --user enable --now {u}: {last(out)}")
        on.append(u)
    return on, notes


def main_pid(u):
    rc, out = systemctl("show", "-p", "MainPID", "--value", u, timeout=30)
    return out.strip() if rc == 0 else ""


def instances(u):
    if "@." not in u:
        return [u]
    stem = u.split("@.", 1)[0]
    rc, out = systemctl("list-units", "--all", "--plain", "--no-legend", f"{stem}@*.service")
    names = [ln.split()[0] for ln in out.splitlines() if ln.strip()] if rc == 0 else []
    return names or [u]


def restart_units(root, changes, project, src):
    files = [p for s, p in changes if s != "D"]
    if not files:
        return [], [], []
    moved = {os.path.basename(p) for p in files}
    rc, out = cc_units("restart-for", "--root", root, *files)
    if rc:
        raise Failed("restart", f"cc-units restart-for: {last(out)}")
    declared = dict(ln.split("\t") for ln in out.splitlines() if ln.count("\t") == 1)
    restarted, asks, notes = [], [], []
    for u in [x for x in linked() if x.endswith(".service")]:
        runs = {os.path.basename(t) for m in EXEC_RE.finditer(unit_text(u)) for t in m.group(1).split() if "/" in t}
        if not (runs & moved or u in declared):
            continue
        if u == NEVER:
            notes.append(f"{u} runs changed code but is never restarted by a deploy; do it by hand (`cc rc restart`)")
            continue
        if declared.get(u) == "none":
            continue
        for inst in instances(u):
            if declared.get(u) == "owner":
                asked, note = scope.owner_ask(project, inst, src)
                (asks if asked else notes).append(note)
                continue
            _, act = systemctl("is-active", inst)
            if act.strip() != "active":
                continue
            was = main_pid(inst)
            rc, out = systemctl("restart", inst, timeout=180)
            if rc:
                raise Failed("restart", f"systemctl --user restart {inst}: {last(out)}")
            now = main_pid(inst)
            if not now or now == "0" or now == was:
                raise Failed("restart", f"{inst} restarted but its pid did not change (was {was}, now {now or 'none'})")
            restarted.append(f"{inst} (pid {was} -> {now})")
    return restarted, asks, notes


def running(root, rel):
    """Pids of this user's bare processes (in no .service) whose program is <root>/<rel>, the lander's own excluded."""
    want, mine, out = os.path.realpath(os.path.join(root, rel)), set(), set()
    pid = os.getpid()
    while pid > 1:
        mine.add(pid)
        try:
            with open(f"/proc/{pid}/status") as f:
                pid = int(next(ln.split()[1] for ln in f if ln.startswith("PPid:")))
        except (OSError, StopIteration, ValueError):
            break
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) in mine:
            continue
        try:
            if os.stat(f"/proc/{d}").st_uid != os.getuid():
                continue
            with open(f"/proc/{d}/cgroup") as f:
                if f.read().strip().endswith(".service"):
                    continue
            with open(f"/proc/{d}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")[:2]
        except OSError:
            continue
        for a in argv:
            a = a.decode(errors="replace")
            if "/" in a and os.path.realpath(os.path.join(root, a)) == want:
                out.add(int(d))
    return out


def daemons(root, changes):
    files = [p for s, p in changes if s != "D"]
    if not files:
        return [], []
    rc, out = cc_units("daemons-for", "--root", root, *files)
    if rc:
        raise Failed("daemons", f"cc-units daemons-for: {last(out)}")
    done, notes = [], []
    for ln in out.splitlines():
        cells = ln.split("\t")
        if len(cells) != 3:
            continue
        name, policy, runs = cells
        was = running(root, runs)
        if not was:
            notes.append(f"{name} is not running here")
            continue
        if policy in ("none", "owner"):
            notes.append(f"{name}: restart={policy}, left running the old code (pid {', '.join(map(str, sorted(was)))})")
            continue
        argv = shlex.split(policy)
        rc, o = C.sh([os.path.join(root, argv[0])] + argv[1:], cwd=root, timeout=180)
        if rc:
            raise Failed("daemons", f"{policy}: {last(o)}")
        now = running(root, runs)
        if not now or now & was:
            raise Failed("daemons", f"{name}: " + (f"still pid {', '.join(map(str, sorted(now & was)))}"
                                                  if now else "not running after its restart"))
        done.append(f"{name} (pid {', '.join(map(str, sorted(now)))})")
    return done, notes


# --- the run -------------------------------------------------------------------------------------------------------

PR_RE = re.compile(r"\(#(\d+)\)$")


def tracks_in(root, repo, before, sha):
    """The board rows of the PRs whose squash commits this deploy brings (subject ends `(#N)`), oldest first."""
    from lander import board
    rc, out = git(root, "log", "--reverse", "--format=%s", f"{before}..{sha}") if before else (1, "")
    out_rows = []
    for s in out.splitlines() if rc == 0 else []:
        m = PR_RE.search(s.strip())
        t = board.track_of(repo, int(m.group(1))) if m else ""
        if t and t not in out_rows:
            out_rows.append(t)
    return out_rows


def deploy_one(repo, target, sha, since=None):
    """-> (state, line, owner_asks). Raises nothing; a failed step is state `failed` with the step named. `since` is
    what was deployed before the request (its `from`), so a retry and a second target see the whole change."""
    root = root_of(target)
    before = applied(repo) if since is None else since
    try:
        changes = pull(root, base_of(repo), sha, before)
        said = [install(root, repo, sha)]
        on, notes = enable_units(changes, repo, sha)
        restarted, asks, n2 = restart_units(root, changes, repo, f"deploy of {repo} at {sha[:12]}")
        started, n3 = daemons(root, changes)
    except Failed as e:
        return "failed", f"{e.step}: {e.why}", []
    said += [f"enabled {', '.join(on)}"] if on else []
    said += [f"restarted {', '.join(restarted + started)}"] if restarted or started else []
    said += notes + n2 + n3
    ok = True
    for track in tracks_in(root, repo, before, sha):
        good, line, _ = scope.deliver(repo, repo, track)
        ok = ok and good
        if line:
            said.append(f"{track}: {line}")
    return ("verified" if ok else "unverified"), "; ".join(said), asks


def run(repo, green=None):
    """Deploy the repo's request to every target the tip passed and nobody holds. -> the request dict, or None.
    A failed target is tried again by the next call, TRIES times in all; after that only a new request moves it."""
    if "--" in repo:
        with contextlib.suppress(OSError):
            os.unlink(req_path(repo))
        return None
    req = C.read_json(req_path(repo))
    if not req:
        return None
    if green is None:
        from lander import tip
        green = tip.green
    sha = req["sha"]
    if not green(repo, sha):
        return req
    if not req.get("from"):   # a request written before `from` was kept: what was deployed before this run
        req["from"] = applied(repo)
    since = req["from"] if req["from"] != sha else ""
    for target, st in req["targets"].items():
        if st.get("state") in ("deployed", "verified", "unverified"):
            continue
        if st.get("state") == "failed" and int(st.get("tries") or 0) >= TRIES:
            continue
        h = held(target)
        if h:
            st.update(state="held", why=h.get("why", ""))
            continue
        state, line, asks = deploy_one(repo, target, sha, since)
        st.update(state=state, why=line, at=C.now())
        if state == "failed":
            st["tries"] = int(st.get("tries") or 0) + 1
        C.log("deployed" if state != "failed" else "deploy-failed", repo, "deploy", target=target, sha=sha[:12],
              state=state)
        pid = f"land:{repo}:deploy:{target}:{state}@{sha[:12]}"
        if state == "failed":
            # --major: the owner was told "merged", so a deploy that failed is his to know, on #<repo> and not only in
            # the -updates lane (#770 was called live by hand while its deploy had failed, 2026-09-28)
            C.say(pid, [os.path.join(C.BIN, "cc-slack"), "post", "--route", f"[{repo}] deploy stopped", "--major", "--id", pid,
                        f"[{repo}] main at {sha[:12]} merged but did not deploy to {target} — {line}"], repo, 0)
            continue
        text = f"[{repo}] deployed {sha[:12]}" + (f" to {target}" if target != repo else "")
        if state == "unverified":
            # the old lander's UNVERIFIED (exit 4): merged and deployed, but what was asked for is not proved here
            text += (f" — but NOT delivered: {line}. The asks stay open; `cc-scope unverified {repo}` lists them.")
        if asks:
            text += (f" ⚠️ Please restart {', '.join(asks)}. Until then the box runs the old code for "
                     f"{'it' if len(asks) == 1 else 'them'}.")
        if state == "unverified" or asks:
            C.say(pid, [os.path.join(C.BIN, "cc-slack"), "post", "--route", f"[{repo}] deploy", "--mention", "--id",
                        pid, text], repo, 0)
    C.write_json(req_path(repo), req)
    return req


def outcome(req):
    """-> the exit code the old lander gave a deploy: 1 a target failed, 4 one is UNVERIFIED, 0 all verified.
    None while a target still waits (requested, or held by a red tip)."""
    states = [(st or {}).get("state") for st in ((req or {}).get("targets") or {}).values()]
    if not states or any(s in WAITING for s in states):
        return None
    return 1 if "failed" in states else 4 if "unverified" in states else 0


def cmd_deploy(argv):
    if len(argv) != 1:
        print("usage: lander deploy <repo>   do the repo's pending deploy request if its tip is green "
              "(exit 1 failed, 4 unverified)")
        return 2
    req = run(argv[0])
    if not req:
        print(f"{argv[0]}: nothing to deploy")
        return 0
    for t, st in req["targets"].items():
        print(f"{t}: {st['state']}" + (f" — {st['why']}" if st.get("why") else ""))
    return outcome(req) or 0


COMMANDS = {"deploy": (cmd_deploy, "do <repo>'s pending deploy request once its tip is green")}
