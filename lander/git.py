"""git plumbing for the lane, and the repo lock every writer of a checkout's FETCH_HEAD shares.

THE LOCK is today's file, `.git/cc-land.lock` (a linked worktree's `.git` file resolved to the main repo's gitdir),
because cc-publish and the old lander take the same one; git_lock_path and git_lock are ported unchanged. It is
held across a fetch or the merge's critical section, never across a check or a review.

    git(root, *args, check=False, env=None)  -> R(rc, out, err); check=True raises GitError on rc != 0
    fetch(root, *branches)                   origin's branches into refs/remotes/origin/<b>, from remote_url(root)
    remote_url(root)                         the URL the lander holds for the checkout (see ORIGIN below)
    rev(root, ref) · tree_of(root, commit) · remote_head(root, branch)
    merge_tree(root, base, head)  -> (tree, [])  or (None, [conflicted paths])   (`merge-tree --write-tree`)
    sealed(root, *revs)           a scratch repo holding only the revs, fetched from the checkout (see SEALED)
    changed(root, a, b)           `diff --name-only --no-renames -z a b`, each path as it is, read sealed
    pr_changed(root, base, head)  changed() from the merge-base of base and head, both found sealed
    protected_same(root, rules, approved, head)  every file under `rules` is byte-identical at both heads, sealed

SEALED is how every read that decides a gate or feeds the review sees a change. A worker can write the checkout's
shared .git: its objects (a loose object file is the worker's own, so a chmod lets it put the base tree's bytes under
the head tree's name and the diff lists no paths), refs/replace and grafts (a swapped commit or a moved merge-base),
a commit-graph, its config (core.worktree with diff.relative empties a diff; diff.external, textconv, a merge driver)
and its attributes (`* -diff`). sealed() fetches the revs by id from the checkout into an empty bare repo that reads
no config, attributes or template of anyone's: index-pack re-hashes every object it receives, so an object whose bytes
do not match its name fails the fetch and the read fails closed, and upload-pack sends the real objects, never a
replacement.

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
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
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
    # -z: a path git would quote ("run\303\251.sh") or that holds a newline comes back as it is
    r = git(root, "merge-tree", "--write-tree", "--name-only", "--no-messages", "-z", base, head, env=env)
    lines = r.out.split("\0")
    if r.rc == 0 and lines and SHA_RE.fullmatch(lines[0].strip()):
        return lines[0].strip(), []
    if r.rc == 1 and lines:
        return None, sorted({p for p in lines[1:] if p})
    raise GitError(f"git merge-tree {base[:12]} {head[:12]}: {(r.err or r.out).strip()[-300:]}")


def blind_env() -> dict:
    """os.environ with no GIT_* of the caller's and no system, global or user config or attributes."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    # core.attributesFile unset still reads ~/.config/git/attributes, so it is pointed at nothing
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_ATTR_NOSYSTEM="1", GIT_CONFIG_COUNT="1",
               GIT_CONFIG_KEY_0="core.attributesFile", GIT_CONFIG_VALUE_0=os.devnull, GIT_LITERAL_PATHSPECS="1")
    return env


def _sh(argv, cwd=None, env=None, timeout=120):
    try:
        # bytes, decoded with no newline translation: text=True would read a \r in a path or a line as \n
        p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        out, err = p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
        return p.returncode, out if p.returncode == 0 else (err or out)
    except (OSError, subprocess.TimeoutExpired) as x:
        return 125, str(x)


@contextlib.contextmanager
def sealed(root, *revs, sh=None):
    """A scratch bare repo holding the revs and what they reach, fetched from the checkout (SEALED above) ->
    ((rc, out), run). On success rc is 0, out the revs as commit ids, and run(*git_args, timeout=) runs git there
    with blind_env(); else run is None and (rc, out) says why. `sh(argv, cwd=, env=, timeout=) -> (rc, out)` runs
    each git (review.py passes its own, which its tests answer). Any doubt (a rev git will not name, an object whose
    bytes are not its name, a fetch that fails) is the else."""
    env, sh = blind_env(), sh or _sh
    # the ids are named in the checkout with no replace refs; a forged object there is caught by the fetch below
    if any(r.startswith("-") for r in revs):   # rev-parse echoes --end-of-options, so an option is refused
        yield (1, f"not a revision: {revs}"), None
        return
    rc, out = sh(["git", "rev-parse", "--path-format=absolute", "--git-common-dir",
                  *(f"{r}^{{commit}}" for r in revs)], cwd=root, env=dict(env, GIT_NO_REPLACE_OBJECTS="1"), timeout=60)
    lines = out.splitlines()
    if rc or len(lines) != 1 + len(revs) or not all(SHA_RE.fullmatch(x) for x in lines[1:]):
        yield (rc or 1, out), None   # the scratch repo has no refs, so every rev goes to it as a commit id
        return
    scratch = tempfile.mkdtemp(prefix="cc-land.git.")
    try:
        rc, err = sh(["git", "init", "-q", "--bare", "--template=", scratch], cwd=scratch, env=env, timeout=60)
        if rc:
            yield (rc, err), None
            return
        env["GIT_DIR"] = scratch

        def run(*args, timeout=120):
            return sh(["git", *args], cwd=scratch, env=env, timeout=timeout)
        rc, err = run("fetch", "-q", "--no-tags", "--no-write-fetch-head", "--no-recurse-submodules", lines[0],
                      *dict.fromkeys(lines[1:]), timeout=600)
        if rc:
            yield (rc, err), None
            return
        yield (0, lines[1:]), run
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


NAMES = ("diff", "--name-only", "--no-renames", "--no-relative", "--ignore-submodules=none", "-z")


def _names(run, a, b) -> list:
    rc, out = run(*NAMES, a, b)
    if rc:
        raise GitError(f"git diff --name-only {a[:12]} {b[:12]}: {out.strip()[-300:]}")
    return sorted({p for p in out.split("\0") if p})


def changed(root, a, b, env=None) -> list:
    """Every path between a and b, read sealed(); --ignore-submodules=none so a .gitmodules `ignore = all` cannot hide
    a gitlink from the plan, the walls and the protected paths. `env` is taken for the callers' sake: the fetch is
    local and needs no token."""
    with sealed(root, a, b) as ((rc, out), run):
        if run is None:
            raise GitError(f"git could not read {a[:12]}..{b[:12]} sealed: {str(out).strip()[-300:]}")
        return _names(run, *out)


def pr_changed(root, base, head, env=None) -> list:
    """Every path the change touches: changed() from the merge-base of base and head, found in the same sealed repo,
    so no replace ref, graft or commit-graph of the checkout's can move it onto the branch."""
    with sealed(root, base, head) as ((rc, out), run):
        if run is None:
            raise GitError(f"git could not read {base[:12]}...{head[:12]} sealed: {str(out).strip()[-300:]}")
        rc, mb = run("merge-base", *out)
        if rc:
            raise GitError(f"git merge-base {base[:12]} {head[:12]}: {mb.strip()[-300:]}")
        return _names(run, mb.strip(), out[1])


def protected_same(root, rules, approved, head, env=None) -> bool:
    """True only when git SHOWS every file under `rules` is the same at `head` as at `approved`, read sealed(); every
    doubt (no rules, a head git will not name after one fetch, a diff that fails) is False, and the caller re-asks."""
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
    with sealed(root, approved, head) as ((rc, out), run):
        return run is not None and out == [approved, head] and \
            run("diff", "--quiet", "--no-relative", "--ignore-submodules=none", "--no-ext-diff", "--no-textconv",
                *out, "--", *rules, timeout=60)[0] == 0


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
