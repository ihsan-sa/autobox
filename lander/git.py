"""git plumbing for the lane, and the repo lock every writer of a checkout's FETCH_HEAD shares.

THE LOCK is today's file, `.git/cc-land.lock` (a linked worktree's `.git` file resolved to the main repo's gitdir),
because cc-publish and the old lander take the same one; git_lock_path and git_lock are ported unchanged. It is
held across a fetch or the merge's critical section, never across a check or a review.

    git(root, *args, check=False, env=None)  -> R(rc, out, err); check=True raises GitError on rc != 0
    fetch(root, *branches)                   origin's branches into refs/remotes/origin/<b>
    rev(root, ref) · tree_of(root, commit) · merge_base(root, a, b) · remote_head(root, branch)
    merge_tree(root, base, head)  -> (tree, [])  or (None, [conflicted paths])   (`merge-tree --write-tree`)
    changed(root, a, b)           `diff --name-only --no-renames a b`
    patch_digest(root, base, head) sha256 over `git patch-id --stable` of the diff merge-base..head: a rebase
                                   that changes nothing of the diff keeps the digest
    protected_same(root, rules, approved, head)  every file under `rules` is byte-identical at both heads

`env` adds to os.environ for one call (a member landing's GH_TOKEN, which gh's credential helper answers with).
"""
from __future__ import annotations

import collections
import fcntl
import hashlib
import os
import re
import subprocess
import threading

R = collections.namedtuple("R", "rc out err")
SHA_RE = re.compile(r"[0-9a-f]{40}")


class GitError(Exception):
    """A git call that had to answer and did not."""


def git(root, *args, check=False, env=None, timeout=300, input=None) -> R:
    e = dict(os.environ, **env) if env else None
    try:
        p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=timeout, env=e,
                           input=input, stdin=None if input is not None else subprocess.DEVNULL)
        r = R(p.returncode, p.stdout, p.stderr)
    except (OSError, subprocess.TimeoutExpired) as x:
        r = R(125, "", str(x))
    if check and r.rc:
        raise GitError(f"git {' '.join(args[:3])}: {(r.err or r.out).strip()[-300:]}")
    return r


def fetch(root, *branches, env=None) -> None:
    specs = [f"+refs/heads/{b}:refs/remotes/origin/{b}" for b in branches if b]
    git(root, "fetch", "-q", "origin", *specs, check=True, env=env)


def rev(root, ref, env=None) -> str:
    out = git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}", check=True, env=env).out.strip()
    if not SHA_RE.fullmatch(out):
        raise GitError(f"git rev-parse {ref}: {out!r}")
    return out


def tree_of(root, commit, env=None) -> str:
    return git(root, "rev-parse", "--verify", f"{commit}^{{tree}}", check=True, env=env).out.strip()


def merge_base(root, a, b, env=None) -> str:
    return git(root, "merge-base", a, b, check=True, env=env).out.strip()


def remote_head(root, branch, env=None) -> str:
    """What origin itself says refs/heads/<branch> is, or '' on any doubt (the PR object's headRefOid lags it)."""
    if not branch:
        return ""
    r = git(root, "ls-remote", "origin", f"refs/heads/{branch}", env=env, timeout=120)
    for row in r.out.splitlines() if r.rc == 0 else []:
        sha, _, ref = row.partition("\t")
        if ref == f"refs/heads/{branch}" and SHA_RE.fullmatch(sha):
            return sha
    return ""


def merge_tree(root, base, head, env=None):
    """(tree, []) for a clean merge of head into base, (None, paths) for a conflict. Any other failure raises."""
    r = git(root, "merge-tree", "--write-tree", "--name-only", "--no-messages", base, head, env=env)
    lines = r.out.splitlines()
    if r.rc == 0 and lines and SHA_RE.fullmatch(lines[0].strip()):
        return lines[0].strip(), []
    if r.rc == 1 and lines:
        return None, sorted({l.strip() for l in lines[1:] if l.strip()})
    raise GitError(f"git merge-tree {base[:12]} {head[:12]}: {(r.err or r.out).strip()[-300:]}")


def changed(root, a, b, env=None) -> list:
    out = git(root, "diff", "--name-only", "--no-renames", a, b, check=True, env=env).out
    return sorted({l.strip() for l in out.splitlines() if l.strip()})


def patch_digest(root, base, head, env=None) -> str:
    mb = merge_base(root, base, head, env=env)
    diff = git(root, "diff", "--no-color", "--no-ext-diff", mb, head, check=True, env=env).out
    pid = git(root, "patch-id", "--stable", input=diff, env=env).out.split()
    return hashlib.sha256((pid[0] if pid else "").encode()).hexdigest()


def protected_same(root, rules, approved, head, env=None) -> bool:
    """True only when git SHOWS every file under `rules` is the same at `head` as at `approved`; every doubt (no
    rules, a head git will not name after one fetch, a diff that fails) is False, and the caller re-asks."""
    if not rules or not approved or not head:
        return False

    def named():
        # one --verify per head: the old lander passed both to one `rev-parse --verify`, which always exits 128
        # ("Needed a single revision"), so its carry never fired and every new head re-asked the owner
        outs = [git(root, "rev-parse", "--verify", "--end-of-options", f"{s}^{{commit}}", env=env, timeout=30)
                for s in (approved, head)]
        return all(r.rc == 0 for r in outs) and [r.out.strip() for r in outs] == [approved, head]
    if not named():
        git(root, "fetch", "-q", "origin", approved, head, env=env, timeout=120)
        if not named():
            return False
    return git(root, "diff", "--quiet", approved, head, "--", *rules, env=env, timeout=60).rc == 0


# --- the repo lock (ported unchanged) ------------------------------------------------------------------------------

_LOCKS, _LOCKS_GUARD = {}, threading.Lock()


def git_lock_path(root):
    """The file the repo lock is taken on: inside the repo's own `.git` (a linked worktree's `.git` file points
    into the main one, whose FETCH_HEAD is the shared one), else a name under LANDQ/gitlock derived from the root."""
    g = os.path.join(root, ".git")
    if os.path.isfile(g):
        try:
            with open(g) as f:
                line = f.read().strip()
        except OSError:
            line = ""
        if line.startswith("gitdir:"):
            g = os.path.abspath(os.path.join(root, line.split(":", 1)[1].strip()))
            if os.path.basename(os.path.dirname(g)) == "worktrees":
                g = os.path.dirname(os.path.dirname(g))
    if os.path.isdir(g):
        return os.path.join(g, "cc-land.lock")
    from lander import jobs as J
    d = f"{J.landq()}/gitlock"
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return ""
    return f"{d}/{re.sub(r'[^A-Za-z0-9]+', '-', os.path.abspath(root)).strip('-')}.lock"


class git_lock:
    """One lock per repository, across processes (an flock in .git) and threads (a reentrant RLock, taken first);
    a lock file that cannot be opened skips the flock."""

    def __init__(self, root):
        self.path = git_lock_path(root)
        with _LOCKS_GUARD:
            self.st = _LOCKS.setdefault(self.path or root, {"rl": threading.RLock(), "fd": None, "depth": 0})

    def __enter__(self):
        self.st["rl"].acquire()
        try:
            if self.st["depth"] == 0 and self.path:
                fd = None
                try:
                    fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
                    fcntl.flock(fd, fcntl.LOCK_EX)
                except OSError:
                    if fd is not None:
                        os.close(fd)
                    fd = None
                self.st["fd"] = fd
            self.st["depth"] += 1
        except BaseException:
            self.st["rl"].release()
            raise
        return self

    def __exit__(self, *exc):
        try:
            self.st["depth"] -= 1
            if self.st["depth"] == 0 and self.st["fd"] is not None:
                fd, self.st["fd"] = self.st["fd"], None
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
        finally:
            self.st["rl"].release()
        return False
