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
              that is not that tip or an ancestor of it is refused; then fast_forward: what `git merge --ff-only
              <sha>` did, with no hook, filter or config of the checkout's run, so a checkout a person moved is
              refused, never reset. Before read-tree runs, an untracked file or symlink standing where <sha> adds a
              tracked one (a draft of a doc that later got committed), ignored or not, is moved to the lander's state
              dir, deploy-aside/<checkout>/, through parents opened with O_NOFOLLOW; the deploy's line names what
              moved. If read-tree still refuses, the files go back, and the line names any that could not. An
              untracked directory there, or a tracked one holding anything untracked, is never moved: the deploy
              fails and names it, and read-tree never runs (git 2.53's would overwrite an ignored file and delete an
              ignored directory without refusing). A staged or changed file the merge changes whose copy on disk
              is already <sha>'s is staged as it is (settle); one that differs is a person's edit, kept, and the
              deploy fails as "a dirty checkout, not main red", naming the checkout and the files
  3. install  the one installer the repo names in tests/LANDING-deploy.toml (`installer = "<path>"`), with no
              flags; then `systemctl --user daemon-reload`; then <repo>.applied records the sha. Nothing at a guessed
              path runs: with no such file or key the deploy pulls only and says so. A name that is not a regular
              file inside the checkout (a symlink anywhere on the way, an absolute path or one leaving the tree) fails
              the step and says why. plan.py makes a change to that file a security read in every repo
  4. units    a systemd-user unit this change ADDED is enabled with `enable --now`, unless its .timer does it, it
              has no [Install], install.sh did not link it, or `cc-units policy <u> enable` says owner — then the
              owner gets one 🔐 card with the command, and nothing else asks him (S5). The policy is read from the
              manifests of the tree just deployed, never the lander's own release: a change that adds a unit and
              its enable=owner row together is otherwise enabled anyway (#1126's hostdoor units on the hub, 10-13)
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
import errno
import fcntl
import json
import os
import re
import shlex
import stat
import tempfile
import time
import tomllib

from lander import cards as C
from lander import git as G
from lander import manifest as M
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
MOVED = "untracked file(s) that stood where the merge adds tracked ones"   # deploy_one's line; run() says it
# A failed target is tried again by a later run(), with no count cap: BACKOFF seconds after its first failure,
# doubling to BACKOFF_MAX (owner 10-16: a cap that left a target waiting for a new request was a stop nobody was told
# of; a fix that lands on the box, or a unit that comes back, now deploys). The first failure posts, and a retry
# posts again only when its reason differs from the one last posted (fail_reason) or REPOST_AFTER has passed since
# that post: a deploy that keeps failing is never quiet for more than a day, and a backoff retry is not a card.
BACKOFF, BACKOFF_MAX = 600, 6 * 3600
REPOST_AFTER = 24 * 3600


def fail_reason(line):
    """-> what a failure line is compared on: its first part (`<step>: <why>`, without the files moved aside after
    it), with every run of digits one `#`, so a pid, a count or a time in the step's output is not a new reason."""
    return re.sub(r"\d+", "#", (line or "").split("; ")[0]).strip()


def retry_wait(tries):
    """-> seconds a target failed `tries` times waits before the next try."""
    return min(BACKOFF * 2 ** max(int(tries) - 1, 0), BACKOFF_MAX)


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


def git(root, *args, timeout=300, env=None):
    rc, out = C.sh(["git", *args], cwd=root, timeout=timeout, env=env)
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


def cc_units(*args, timeout=120, env=None):
    return C.sh([os.path.join(C.BIN, "cc-units"), *args], timeout=timeout, env=env)


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

def pull(root, base, sha, since="", said=None):
    """Fast-forward to `sha`; -> the (status, path) changes from `since` (what was deployed before this request) to
    `sha`. A line about untracked files moved out of the way is appended to `said`. Not from the checkout's HEAD: on a retry after a failed install or restart the checkout is already at `sha`,
    and a diff from there would be empty, so the retry would skip every unit and restart."""
    with git_lock(root):   # HEAD is read under the lock, so no one else's merge moves it between here and the move
        rc, cur = git(root, "rev-parse", "--abbrev-ref", "HEAD")
        if rc or cur != base:
            raise Failed("branch", f"{root} is on '{cur}', not '{base}' — deploy from the default-branch checkout")
        _, head = git(root, "rev-parse", "HEAD")
        before = head
        if since and git(root, "cat-file", "-e", f"{since}^{{commit}}")[0] == 0:
            before = since
        tip = verified_tip(root, base)
        if not tip:
            raise Failed("pull", f"origin/{base} could not be fetched from the lander's own remote and checked "
                                 f"against it; nothing merged in {root}")
        if sha != tip and git(root, "merge-base", "--is-ancestor", sha, tip)[0] != 0:
            raise Failed("pull", f"{sha[:12]} is not on origin/{base} ({tip[:12]}); nothing merged in {root}")
        try:
            moved = fast_forward(root, base, head, sha)
            if moved and said is not None:
                said.append(moved)
        except G.GitError as x:
            raise Failed("pull", f"no scratch repo for {root}: {last(x)}; nothing merged") from None
    try:
        with G.borrowed(root) as gd:
            rc, out = git(root, "diff", "--name-status", "--no-renames", "-z", before, sha,
                          env=G.hookless_env(GIT_DIR=gd))
    except G.GitError as x:
        rc, out = 1, str(x)
    parts = out.split("\0") if rc == 0 else []   # -z: status, path, status, path, ... each path as it is
    return [(s[:1], p) for s, p in zip(parts[0::2], parts[1::2]) if s and p]


def fast_forward(root, base, head, sha):
    """Move the checkout from `head` to `sha` the way `git merge --ff-only` would, with nothing of the checkout's own
    run: a worker can write its shared .git, so a post-merge, post-checkout or reference-transaction hook, or a smudge
    filter its config names, would run as the lander. read-tree -m -u runs in a borrowed() repo (no config, so no
    filter; read-tree runs no hook) on the checkout's own index and files, and refuses as merge does when a changed or
    untracked file is in the way; then update-ref moves the branch, hooks off. read-tree does NOT refuse for an ignored
    file, so before it runs, the untracked files at paths `sha` adds, ignored ones too, are moved aside (aside()), and
    an untracked dir there (in_the_way) refuses the deploy with read-tree never run. If read-tree refuses after the
    move, the files are put back.
    A checkout already at `sha` or past it is left as it is, as `merge --ff-only` leaves it ("Already up to date").
    -> a line naming what was moved aside, or "". Raises Failed, or GitError when no borrowed repo could be made."""
    if head == sha:
        return ""
    with G.borrowed(root) as gd:
        if git(root, "merge-base", "--is-ancestor", sha, head, env=G.hookless_env(GIT_DIR=gd))[0] == 0:
            return ""
        if git(root, "merge-base", "--is-ancestor", head, sha, env=G.hookless_env(GIT_DIR=gd))[0] != 0:
            raise Failed("pull", f"{sha[:12]} is not a fast-forward of {head[:12]} in {root}; nothing merged")
        rc, gitdir = git(root, "rev-parse", "--path-format=absolute", "--git-dir", env=G.hookless_env())
        if rc or not os.path.isabs(gitdir) or "\n" in gitdir:
            raise Failed("pull", f"git names no git dir for {root}: {last(gitdir)}")
        env = G.hookless_env(GIT_DIR=gd, GIT_WORK_TREE=root, GIT_INDEX_FILE=os.path.join(gitdir, "index"))
        git(root, "update-index", "-q", "--refresh", env=env)   # rc 1 = a file differs; read-tree says which
        # the brief (2026-10-03): "an older untracked draft of it (09-27) sat in the checkout, so the deploy's git
        # read-tree refused 3 times" — an untracked file where `sha` adds a tracked one is moved aside, not left to
        # stop every deploy after it. And BEFORE read-tree, not on its refusal: the #967 security read (2026-10-04)
        # found git 2.53's read-tree -m -u "overwrites ignored files and deletes ignored folders ... without
        # refusing", so an ignored path is treated as an untracked one is: moved aside or refused, never overwritten
        found = in_the_way(root, head, sha, env)
        if found is None:
            raise Failed("pull", f"git could not list what {sha[:12]} adds over {head[:12]} in {root}; nothing merged")
        files, dirs = found
        if dirs:   # a directory is a person's work, a mail queue or a build: it is never moved, nor left to read-tree
            raise Failed("pull", f"{len(dirs)} untracked dir(s) stand where the merge adds a file and are left for a "
                                 f"person: {', '.join(dirs[:5])}; nothing merged into {root}")
        moved, dest, why = aside(root, files)
        if why:
            raise Failed("pull", f"{why}; nothing merged into {root}")
        local = settle(root, head, sha, env)
        rc, out = git(root, "read-tree", "-m", "-u", head, sha, env=env)
        said = ""
        if rc and moved:
            left = put_back(root, moved, dest)
            out += (f" (it still refused with {len(moved)} untracked file(s) moved aside; "
                    + (f"{len(moved) - len(left)} went back and {len(left)} could not, so they stay in "
                       "deploy-aside: " + ", ".join(os.path.join(dest, p) for p in left) if left
                       else "they are back") + ")")
        elif moved:
            said = (f"moved {len(moved)} {MOVED} to {dest}: "
                    + ", ".join(moved[:5]) + (", ..." if len(moved) > 5 else ""))
    if rc:
        raise Failed("pull", (f"a dirty checkout, not main red: {root} has local changes the merge would overwrite, "
                              f"left for a person: {', '.join(local[:5])}" + (", ..." if len(local) > 5 else "")
                              + "; " if local else "")
                     + f"git read-tree -m -u {head[:12]} {sha[:12]} in {root}: {last(out, 600)}")
    rc, out = git(root, "update-ref", "-m", f"lander: fast-forward to {sha[:12]}", f"refs/heads/{base}", sha, head,
                  env=G.hookless_env())
    if rc:
        raise Failed("pull", f"git update-ref refs/heads/{base} {sha[:12]} in {root}: {last(out)}"
                     + (f"; {said}" if said else ""))
    return said


def settle(root, head, sha, env):
    """A path `sha` changes that is staged or changed in the checkout, but whose file on disk is already `sha`'s (or
    is gone where `sha` deletes it), is staged as it is, so read-tree takes it: on 2026-10-21 a stale staged draft of
    read.py whose file already matched main held every dispatch deploy for 1.5 h, and the brief says "if a staged or
    modified file already matches what the pull brings in, that alone shouldn't stop the deploy". -> the paths still local after
    that: a person's edit, never discarded, which read-tree refuses on."""
    rc, changed = git(root, "diff", "--name-only", "--no-renames", "-z", head, sha, env=env)
    rc2, staged = git(root, "diff-index", "--cached", "--name-only", "-z", head, env=env)
    rc3, edited = git(root, "diff-files", "--name-only", "-z", env=env)
    if rc or rc2 or rc3:
        return []
    paths = sorted(set(changed.split("\0")) & set((staged + "\0" + edited).split("\0")) - {""})
    local = []
    for p in paths:
        want = git(root, "rev-parse", "-q", "--verify", f"{sha}:{p}", env=env)[1]
        full = os.path.join(root, p)
        if os.path.isfile(full) and not os.path.islink(full):
            have = git(root, "hash-object", "--no-filters", "--", p, env=env)[1]
        else:
            have = "" if not os.path.lexists(full) else None
        if have != want or git(root, "update-index", "--add", "--remove", "--", p, env=env)[0]:
            local.append(p)
    return local


def unsafe(p):
    """A path git should never have handed us: an empty, `.` or `..` part, or a `.git` in any case."""
    return any(x in ("", ".", "..") or x.lower() == ".git" for x in p.split("/"))


def in_the_way(root, head, sha, env):
    """-> (files, dirs): the untracked paths in `root` that stop read-tree adding what `sha` adds over `head`. Files
    are the added path itself, or the first part of it that is not a directory, when that is a regular file or a
    symlink (never followed); only they are moved aside. Dirs are untracked directories standing where `sha` adds a
    file: never moved (a PR that adds a file `.mail-out` must not move the mail queue), so fast_forward refuses and
    names them. Untracked takes in ignored: git 2.53's read-tree overwrites an ignored file and deletes an ignored
    dir where it refuses for any other untracked one, so fast_forward calls this before read-tree, never on its
    refusal. A tracked dir where `sha` adds a file is a dir here too when it holds anything untracked (an ignored token
    file read-tree would delete with the tracked ones). A tracked path is otherwise never either; read-tree's refusal
    for a changed tracked file stands. A path with a `..`, `.` or `.git` part, or whose parent resolves outside
    `root`, is skipped: a crafted tree entry moves nothing outside the checkout. -> None when git cannot list them."""
    rc, out = git(root, "diff", "--name-only", "--no-renames", "--diff-filter=A", "-z", head, sha, env=env)
    rc2, idx = git(root, "ls-files", "-z", env=env)
    if rc or rc2:
        return None
    tracked = {p for p in idx.split("\0") if p}
    top = os.path.realpath(root)
    files, dirs = [], []
    for p in (p for p in out.split("\0") if p):
        if unsafe(p):
            continue
        parts = p.split("/")
        for i in range(1, len(parts) + 1):
            q = "/".join(parts[:i])
            full = os.path.join(root, q)
            try:
                st = os.lstat(full)
            except OSError:
                break
            if i < len(parts) and stat.S_ISDIR(st.st_mode):
                continue
            # the parent, not q itself: a symlink in the way is moved as a link wherever it points
            up = os.path.realpath(os.path.dirname(full))
            inside = up == top or up.startswith(top + os.sep)
            if inside and q not in tracked and not any(t.startswith(q + "/") for t in tracked):
                if stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
                    files += [q] if q not in files else []
                elif stat.S_ISDIR(st.st_mode):
                    dirs += [q] if q not in dirs else []
            elif inside and stat.S_ISDIR(st.st_mode) and holds_untracked(root, q, tracked):
                dirs += [q] if q not in dirs else []
            break
    return files, dirs


def holds_untracked(root, q, tracked):
    """Is there anything under the dir `q` that is not in `tracked`? Links are not followed; a dir that cannot be
    read counts as yes, so what cannot be seen is never handed to read-tree to delete."""
    def no(x):
        raise x
    try:
        for d, subs, names in os.walk(os.path.join(root, q), onerror=no):
            for n in names + [s for s in subs if os.path.islink(os.path.join(d, s))]:
                if os.path.relpath(os.path.join(d, n), root).replace(os.sep, "/") not in tracked:
                    return True
    except OSError:
        return True
    return False


def aside(root, paths):
    """Move `paths` (relative to `root`) under a fresh dir in the lander's state, deploy-aside/<checkout>/. ->
    (the paths moved, that dir, why nothing moved). A state dir that cannot be made, or a move that fails, puts back
    the ones already moved and moves nothing, so read-tree's refusal stands and the deploy fails, counted."""
    if not paths:
        return [], "", ""
    try:
        base = C.state("deploy-aside", os.path.basename(os.path.normpath(root)))
        os.makedirs(base, exist_ok=True)
        dest = tempfile.mkdtemp(prefix=time.strftime("%Y%m%dT%H%M%SZ-", time.gmtime()), dir=base)
    except OSError as x:
        return [], "", f"no untracked file was moved aside: {x}"
    moved = []
    for p in paths:
        try:
            os.makedirs(os.path.dirname(os.path.join(dest, p)), exist_ok=True)
            move(root, dest, p)
        except OSError as x:
            left = put_back(root, moved, dest)
            return [], "", (f"moving {p} aside failed ({x}), so nothing was moved"
                            + (f"; {len(left)} could not go back and stay in deploy-aside: "
                               + ", ".join(os.path.join(dest, q) for q in left) if left else ""))
        moved.append(p)
    return moved, dest, ""


def put_back(root, moved, dest):
    """Move `moved` back from `dest` into `root`; never over something now there (move()). -> the paths still in
    `dest`."""
    left = []
    for p in moved:
        try:
            move(dest, root, p)
        except OSError:
            left.append(p)
    if not left:
        for d, _, _ in os.walk(dest, topdown=False):   # what is left is the empty dirs
            with contextlib.suppress(OSError):
                os.rmdir(d)
    return left


def walk_to(root, rel):
    """-> an fd on the dir holding `rel` under `root`, each part below `root` opened with O_NOFOLLOW, so a parent that
    is a symlink raises OSError instead of being followed. The caller closes it."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in (x for x in os.path.dirname(rel).split("/") if x):
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
    except BaseException:
        os.close(fd)
        raise
    return fd


def move(src_root, dst_root, rel):
    """Move the file or symlink `rel` from `src_root` to the same path under `dst_root` (whose dirs exist), as itself:
    a link moves as a link. Through parents walk_to() opened with O_NOFOLLOW, and never over anything at the
    destination: a hard link then an unlink, or a copy made with O_EXCL where the link fails with EXDEV (another
    filesystem) or EPERM (a file another user owns, under fs.protected_hardlinks); a failed unlink removes the copy. The #967 re-read
    (2026-10-04) named "a race window between the lstat walk and the move": a parent swapped for a symlink in between
    is refused here, not followed, and a leaf swapped for a dir cannot be linked."""
    name = os.path.basename(rel)
    s = walk_to(src_root, rel)
    try:
        d = walk_to(dst_root, rel)
        try:
            try:
                os.link(name, name, src_dir_fd=s, dst_dir_fd=d, follow_symlinks=False)
            except OSError as x:
                # the FIX read (2026-10-12): link fails "with EPERM on a file owned by another user
                # (fs.protected_hardlinks=1 here), where the old rename worked", so EPERM copies as EXDEV does
                if x.errno not in (errno.EXDEV, errno.EPERM):
                    raise
                copy_at(s, d, name)
            try:
                os.unlink(name, dir_fd=s)
            except OSError:
                with contextlib.suppress(OSError):
                    os.unlink(name, dir_fd=d)
                raise
        finally:
            os.close(d)
    finally:
        os.close(s)


def copy_at(s, d, name):
    """Copy the file or symlink `name` from dir fd `s` to dir fd `d`, never following a link and never over anything;
    the copy gets the permission bits only (no setuid, setgid or sticky), anything else raises EPERM, and a
    part-written copy is removed."""
    st = os.stat(name, dir_fd=s, follow_symlinks=False)
    if stat.S_ISLNK(st.st_mode):
        os.symlink(os.readlink(name, dir_fd=s), name, dir_fd=d)
        return
    if not stat.S_ISREG(st.st_mode):
        raise OSError(errno.EPERM, "neither a file nor a symlink", name)
    i = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=s)   # a fifo swapped in never blocks
    try:
        if not stat.S_ISREG(os.fstat(i).st_mode):
            raise OSError(errno.EPERM, "neither a file nor a symlink", name)
        o = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=d)
        try:
            os.fchmod(o, st.st_mode & 0o777)   # never a setuid or setgid bit onto a file the lander owns
            while chunk := os.read(i, 1 << 20):
                while chunk:
                    chunk = chunk[os.write(o, chunk):]
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(name, dir_fd=d)
            raise
        finally:
            os.close(o)
    finally:
        os.close(i)


INSTALLER = M.DEPLOY


def installer(root):
    """The checkout's named installer, relative to `root`, or "" when INSTALLER names none. Raises Failed when the
    file does not parse, or the name is not a regular file inside the tree with no symlink on the way."""
    try:
        with open(os.path.join(root, INSTALLER), "rb") as f:
            inst = tomllib.load(f).get("installer", "")
    except FileNotFoundError:
        return ""
    except (OSError, ValueError) as e:
        raise Failed("install", f"{INSTALLER}: {e}")
    if not inst:
        return ""
    full = os.path.join(os.path.realpath(root), str(inst))
    if (not isinstance(inst, str) or os.path.isabs(inst) or os.path.normpath(inst) != inst
            or os.path.realpath(full) != full or not os.path.isfile(full)):
        raise Failed("install", f"{INSTALLER} names {inst!r}, which is not a regular file inside the checkout "
                                f"(a symlink or a path out of the tree is refused)")
    return inst


def install(root, repo, sha):
    inst = installer(root)
    if inst:
        path = os.path.join(root, inst)
        rc, out = C.sh([path], cwd=os.path.dirname(path), timeout=900)
        if rc:
            raise Failed("install", f"{inst}: {last(out)}")
        systemctl("daemon-reload")
    record_applied(repo, sha)
    return f"installed with {inst}" if inst else f"pulled only: {INSTALLER} names no installer"


def manifest_env(root):
    """cc-units' env for the tree at `root`: its core manifest with `root` as the overlay when it keeps core/ inside,
    else its own config/units.json. {} for a tree with neither (the lander's own manifests then answer)."""
    core = os.path.join(root, "core", "config", "units.json")
    if os.path.isfile(core):
        return {"CC_UNITS_MANIFEST": core, "CC_UNITS_OVERLAY": root}
    own = os.path.join(root, "config", "units.json")
    return {"CC_UNITS_MANIFEST": own, "CC_UNITS_OVERLAY": ""} if os.path.isfile(own) else {}


def manifests_parse(extra):
    """Whether every manifest `extra` (manifest_env's answer) points cc-units at parses: the core one and the
    overlay's own config/units.json. True for {} (the lander's own manifests answer then)."""
    paths = [extra.get("CC_UNITS_MANIFEST", "")]
    if extra.get("CC_UNITS_OVERLAY"):
        paths.append(os.path.join(extra["CC_UNITS_OVERLAY"], "config", "units.json"))
    for p in filter(os.path.isfile, filter(None, paths)):
        try:
            with open(p) as f:
                json.load(f)["units"]
        except (OSError, ValueError, KeyError, TypeError):
            return False
    return True


def enable_units(changes, repo, sha, root):
    added = [m.group(1) for s, p in changes if s == "A" for m in [UNIT_RE.search(p)] if m]
    have, notes, on = linked(), [], []
    extra = manifest_env(root)
    env = {**os.environ, **extra} if extra else None
    broken = not manifests_parse(extra)
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
        # brief: "if the deployed tree's units.json (core or overlay) doesn't parse, or cc-units gives an empty or
        # unreadable answer for a unit, treat that unit as enable=owner: leave it off and card it, never enable --now"
        rc, pol = (1, "") if broken else cc_units("policy", u, "enable", timeout=30, env=env)
        if rc or pol.strip() in ("", "owner"):
            C.owner_card(f"land:{repo}:deploy:enable-{u}@{sha[:12]}",
                         f"[{repo}] {u} is new, and cc-units keeps turning it on for you: "
                         f"`systemctl --user enable --now {u}`", run=f"systemctl --user enable --now {u}")
            notes.append(f"{u} linked and left off; its approval card is with perms (the owner where a box has no permission session)")
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
    extra = manifest_env(root)   # the deployed tree's rows, as enable_units reads them, not the lander's own release
    rc, out = cc_units("restart-for", "--root", root, *files, env={**os.environ, **extra} if extra else None)
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
        said = []
        changes = pull(root, base_of(repo), sha, before, said)
        said.append(install(root, repo, sha))
        on, notes = enable_units(changes, repo, sha, root)
        restarted, asks, n2 = restart_units(root, changes, repo, f"deploy of {repo} at {sha[:12]}")
        started, n3 = daemons(root, changes)
    except Failed as e:   # files moved aside before an install or restart failed are still said: a retry moves none
        return "failed", "; ".join([f"{e.step}: {e.why}"] + said), []
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
    A failed target is tried again once its retry_wait has passed, with no cap on the tries."""
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
        if st.get("state") == "failed" and time.time() < float(st.get("retry_at") or 0):
            continue
        h = held(target)
        if h:
            st.update(state="held", why=h.get("why", ""))
            continue
        state, line, asks = deploy_one(repo, target, sha, since)
        st.update(state=state, why=line, at=C.now())
        if state == "failed":
            st["tries"] = int(st.get("tries") or 0) + 1
            st["retry_at"] = time.time() + retry_wait(st["tries"])
        C.log("deployed" if state != "failed" else "deploy-failed", repo, "deploy", target=target, sha=sha[:12],
              state=state)
        pid = f"land:{repo}:deploy:{target}:{state}@{sha[:12]}"
        if state == "failed":
            # --major: the owner was told "merged", so a deploy that failed is his to know, on #<repo> and not only in
            # the -updates lane (#770 was called live by hand while its deploy had failed, 2026-09-28). On the first
            # failure, and on a retry whose reason changed or that comes a REPOST_AFTER after the last post; the
            # retries between are queue.log lines, not more cards
            reason, now = fail_reason(line), time.time()
            if st["tries"] == 1:
                head = f"[{repo}] main at {sha[:12]} merged but did not deploy to {target} — {line}."
            elif reason != st.get("said_reason"):
                head = (f"[{repo}] main at {sha[:12]} still did not deploy to {target}, now for another reason "
                        f"(try {st['tries']}) — {line}.")
            elif now - float(st.get("said_at") or 0) >= REPOST_AFTER:
                head = (f"[{repo}] main at {sha[:12]} has still not deployed to {target} after {st['tries']} tries "
                        f"over a day — {line}.")
            else:
                continue
            if st["tries"] > 1:
                pid += f":{st['tries']}"
            # recorded whether or not cc-slack took it: a refused card is in say()'s pending, retried from there
            st.update(said_reason=reason, said_at=now)
            C.say(pid, [os.path.join(C.BIN, "cc-slack"), "post", "--route", f"[{repo}] deploy stopped", "--major",
                        "--id", pid, f"{head} It is tried again in {retry_wait(st['tries']) // 60} min and then less "
                        "often; it posts again if the reason changes or a day passes"], repo, 0)
            continue
        text = f"[{repo}] deployed {sha[:12]}" + (f" to {target}" if target != repo else "")
        if state == "unverified":
            # the old lander's UNVERIFIED (exit 4): merged and deployed, but what was asked for is not proved here
            text += (f" — but NOT delivered: {line}. The asks stay open; `cc-scope unverified {repo}` lists them.")
        if asks:
            text += (f" ⚠️ Please restart {', '.join(asks)}. Until then the box runs the old code for "
                     f"{'it' if len(asks) == 1 else 'them'}.")
        # a person's draft moved out of their checkout: they hear where it went, with a mention only if one is due
        moved = next((x for x in line.split("; ") if MOVED in x), "")
        if moved and moved not in text:
            text += f" — {moved}"
        if state == "unverified" or asks:
            C.say(pid, [os.path.join(C.BIN, "cc-slack"), "post", "--route", f"[{repo}] deploy", "--mention", "--id",
                        pid, text], repo, 0)
        elif moved:
            C.say(pid, [os.path.join(C.BIN, "cc-slack"), "post", "--route", f"[{repo}] deploy", "--id", pid, text],
                  repo, 0)
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
