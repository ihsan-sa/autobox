"""git plumbing for the lane, and the repo lock every writer of a checkout's FETCH_HEAD shares.

THE LOCK is today's file, `.git/cc-land.lock` (a linked worktree's `.git` file resolved to the main repo's gitdir),
because cc-publish and the old lander take the same one; git_lock_path and git_lock are ported unchanged. It is
held across a fetch or the merge's critical section, never across a check or a review.

    git(root, *args, check=False, env=None)  -> R(rc, out, err); check=True raises GitError on rc != 0
    fetch(root, *branches)                   origin's branches into refs/remotes/origin/<b>, from remote_url(root)
    remote_url(root)                         the URL the lander holds for the checkout (see ORIGIN below)
    rev(root, ref) · tree_of(root, commit) · merge_base(root, a, b) · remote_head(root, branch)
    merge_tree(root, base, head)  -> (tree, [])  or (None, [conflicted paths])   (`merge-tree --write-tree`)
    changed(root, a, b)           `diff --name-only --no-renames a b`
    protected_same(root, rules, approved, head)  every file under `rules` is byte-identical at both heads

ORIGIN is never the name "origin" in the checkout's shared .git/config: a worker can repoint that, unset its
fetch refspec or plant refs/remotes/origin/<b>. Every fetch, ls-remote and push goes to the URL `lander-self
pin`/`promote` wrote to ~/.cc/lander/remotes.json (realpath of the checkout -> URL), with an explicit forced
refspec. A checkout with no URL there, a URL there that is not https://github.com/<owner>/<repo>, or a config that
rewrites that URL (url.<x>.insteadOf) is refused. A member's clone under the lander's own clones dir is the one
exception: the lander made it and set its URL from the member's board row (members.member_clone).

`env` adds to os.environ for one call (a member landing's GH_TOKEN, which gh's credential helper answers with).
"""
from __future__ import annotations

import collections
import fcntl
import json
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


REMOTES = None   # a test points this at its own file; nothing outside the process can
ALLOW_LOCAL = False   # a test's bare repos as pinned URLs; nothing outside the process can set it
GH_PIN_RE = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?(?:\.git)?")


def remotes_path() -> str:
    return REMOTES or os.path.join(os.path.expanduser("~"), ".cc", "lander", "remotes.json")


def remote_url(root) -> str:
    """The URL the lander fetches `root` from, or '' when it holds none (the caller refuses)."""
    real = os.path.realpath(root)
    try:
        with open(remotes_path()) as f:
            pins = json.load(f)
    except (OSError, ValueError):
        pins = {}
    url = pins.get(real) if isinstance(pins, dict) else None
    from lander import jobs as J
    if real.startswith(os.path.realpath(J.clones_dir()) + os.sep):
        if not (isinstance(url, str) and url):
            r = git(root, "remote", "get-url", "origin", timeout=30)
            url = r.out.strip() if r.rc == 0 else ""
    elif not (isinstance(url, str) and (GH_PIN_RE.fullmatch(url) or ALLOW_LOCAL and os.path.isabs(url))):
        url = ""   # remotes.json is a file a worker could reach: only a GitHub https URL is taken from it
    return url if url and not rewritten(root, url) else ""


def config_values(root, pattern):
    """The values of every config key matching `pattern`, read with -z so a key with a space or newline in its
    subsection cannot shift where the value starts. None when git could not read the config."""
    r = git(root, "config", "-z", "--get-regexp", pattern, timeout=30)
    if r.rc not in (0, 1):
        return None
    return [rec.partition("\n")[2] for rec in r.out.split("\0") if rec]


def rewritten(root, url) -> bool:
    """True when a url.<x>.insteadOf or pushInsteadOf in any config git reads for root would send `url` elsewhere:
    the shared .git/config is a worker's to write, and a rewrite there would redirect even the pinned URL."""
    vals = config_values(root, r"^url\..*\.(push)?insteadof$")
    return vals is None or any(v and url.startswith(v) for v in vals)


def remote(root) -> str:
    url = remote_url(root)
    if not url:
        raise GitError(f"the lander holds no remote URL for {root}; `lander-self promote` pins one")
    return url


def fetch(root, *branches, env=None) -> None:
    specs = [f"+refs/heads/{b}:refs/remotes/origin/{b}" for b in branches if b]
    git(root, "fetch", "-q", remote(root), *specs, check=True, env=env)


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
    url = remote_url(root)
    if not url:
        return ""
    r = git(root, "ls-remote", url, f"refs/heads/{branch}", env=env, timeout=120)
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
        url = remote_url(root)
        if not url:
            return False
        git(root, "fetch", "-q", url, approved, head, env=env, timeout=120)
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
