"""A member workspace's own landing (review B5; U1 owns its intake). The job's repo is `<handle>--<track>`.

  member_of(repo)         (h, t) for a member project, (h, "") for the workspace itself, ("", "") for the box's
                          own — decided by the marker DEV/<h>/.cc/member-workspace, never by the name.
  member_token(h)         the granted token: MEMBERS/<h>/github-token must be a LINK to a mode-600 file; else "".
                          Printed nowhere.
  member_project_url(h, t, pr)  (url, "") or ("", why): the board row's `pr` is checked, not trusted — the owner
                          must be CC_GH_PERSONAL_OWNER (cc-config) and the name one `cc-gh-token repos <h> <owner>`
                          lists; anything else is refused before the token is read.
  member_clone(repo, url) (root, "") or ("", why): the host-only clone <LANDQ>/clones/<h>--<t>, no checkout, its
                          credential gh's helper answering with GH_TOKEN, never the box's login.
  walls(root, base, head, files)  why or "": a boundary path (BOUNDARY_PATHS: .cc/** and the secret stores), or a
                          token shape (TOKEN_SHAPES) on an ADDED line of the diff. Checked before any check runs.
  spent(h) -> (usd, cap) · charge(h, usd) -> None | (spent_before, cap)   the day's ledger cc's member_gate keeps,
                          <state>/member-spend.json, cap MEMBER_DAILY_USD (cc-config, else 20).
  route(job)              "#<h>" for a member job, else "" — where its stop is said.
  env(h)                  the GH_TOKEN env for git in the clone, or None.
A member project never deploys (lane.py).
"""
from __future__ import annotations

import fcntl
import fnmatch
import os
import re
import shutil
import subprocess
import time

from lander import jobs as J

MEMBER_DAILY_USD = 20
# A copy of cc-audit's SECRET_PATHS (canonical there), as the old lander keeps it.
SECRET_PATHS = (".cc/config", ".cc/secrets/**", ".cc/members/**", "ccbox/env", ".ssh/**",
                ".claude/.credentials.json", ".claude.json", ".config/gh/**")
BOUNDARY_PATHS = (".cc/**",) + SECRET_PATHS
TOKEN_SHAPES = re.compile(r"github_pat_[A-Za-z0-9_]{20,}|\bgh[pousr]_[A-Za-z0-9]{30,}|\bsk-ant-[A-Za-z0-9_-]{20,}"
                          r"|\bxox[abpr]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
HANDLE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def run(argv, cwd=None, timeout=60, env=None):
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, **env) if env else None)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 125, "", str(e)


def config(key, default=""):
    rc, out, _ = run([f"{J.bin_dir()}/cc-config", "get", key], timeout=30)
    return (out.strip() if rc == 0 and out.strip() else "") or default


def member_of(repo):
    h, _, t = (repo or "").partition("--")
    if h and HANDLE_RE.fullmatch(h) and os.path.isfile(f"{J.dev()}/{h}/.cc/member-workspace"):
        return h, t
    return "", ""


def boundary_path(path) -> bool:
    for g in BOUNDARY_PATHS:
        if g.endswith("/**"):
            if path == g[:-3] or path.startswith(g[:-2]):
                return True
        elif fnmatch.fnmatchcase(path, g) or path.endswith("/" + g):
            return True
    return False


def member_token(handle) -> str:
    g = f"{J.members_dir()}/{handle}/github-token"
    try:
        f = os.path.realpath(g)
        st = os.stat(f)
        if not os.path.islink(g) or not os.path.isfile(f) or (st.st_mode & 0o777) != 0o600:
            return ""
        with open(f) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def env(handle):
    tok = member_token(handle) if handle else ""
    return {"GH_TOKEN": tok} if tok else None


def member_project_url(handle, track, pr):
    row = (J.board(handle).get("tracks") or {}).get(track) or {}
    m = re.fullmatch(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/([0-9]+)", row.get("pr") or "")
    if not m or m.group(3) != str(pr):
        return "", f"the {handle} board row for {track} does not carry PR #{pr} (pr='{row.get('pr') or ''}')"
    owner, name = m.group(1), m.group(2)
    powner = config("CC_GH_PERSONAL_OWNER")
    if not powner or owner.lower() != powner.lower():
        return "", (f"{owner}/{name} is not under the owner's own account "
                    f"({powner or 'CC_GH_PERSONAL_OWNER is not set'}) — a granted token opens nothing else")
    rc, out, _ = run([f"{J.bin_dir()}/cc-gh-token", "repos", handle, powner], timeout=60)
    if rc or name.lower() not in {x.strip().lower() for x in out.splitlines() if x.strip()}:
        return "", f"{owner}/{name} is not a repository of workspace {handle} (cc-gh-token repos {handle} {powner})"
    return f"https://github.com/{owner}/{name}.git", ""


def member_clone(repo, url):
    root = f"{J.clones_dir()}/{repo}"
    h = member_of(repo)[0]
    if os.path.isdir(f"{root}/.git"):
        if run(["git", "remote", "get-url", "origin"], cwd=root)[1].strip() != url:
            run(["git", "remote", "set-url", "origin", url], cwd=root)
        return root, ""
    try:
        for d in (J.clones_dir(), root, f"{root}/.gh-none"):
            os.makedirs(d, mode=0o700, exist_ok=True)
    except OSError as e:
        return "", f"cannot make {root}: {e}"
    rc, out, err = run(["git", "clone", "-q", "--no-checkout", "-c", "credential.helper=",
                        "-c", "credential.helper=!gh auth git-credential", url, "."], cwd=root, timeout=900,
                       env=dict(env(h) or {}, GH_CONFIG_DIR=f"{root}/.gh-none"))
    if rc:
        shutil.rmtree(root, ignore_errors=True)
        return "", f"cannot clone {url}: {(err or out).strip()[-200:]}"
    return root, ""


def walls(root, base, head, files, genv=None) -> str:
    bad = [f for f in files if boundary_path(f)]
    if bad:
        return f"it touches {bad[0]}, which a member PR may not (the boundary or a secret's place)"
    from lander import git as G
    r = G.git(root, "diff", "--no-color", "--no-ext-diff", "-U0", f"{base}...{head}", env=genv)
    if r.rc:
        return f"git could not show the diff to check it for tokens ({r.err.strip()[-120:]})"
    where = ""
    for ln in r.out.splitlines():
        if ln.startswith("+++ "):
            where = ln[6:] if ln.startswith("+++ b/") else ln[4:]
        elif ln.startswith("+") and TOKEN_SHAPES.search(ln):
            return f"an added line in {where} is shaped like a token"
    return ""


def spend_path() -> str:
    return f"{J.state_dir()}/member-spend.json"


def cap() -> float:
    try:
        return float(config("MEMBER_DAILY_USD", str(MEMBER_DAILY_USD)))
    except ValueError:
        return float(MEMBER_DAILY_USD)


def _today_row(cur, handle, day):
    row = cur.get(handle) if isinstance(cur.get(handle), dict) else {}
    return row, (float(row.get("usd") or 0) if row.get("day") == day else 0.0)


def spent(handle):
    cur = J.read_json(spend_path())
    day = time.strftime("%Y-%m-%d", time.gmtime())
    return _today_row(cur if isinstance(cur, dict) else {}, handle, day)[1], cap()


def charge(handle, usd):
    """Charge `usd` to today under the ledger's lock. None when charged, (spent_before, cap) on a refusal."""
    c = cap()
    day = time.strftime("%Y-%m-%d", time.gmtime())
    os.makedirs(J.state_dir(), exist_ok=True)
    with open(f"{spend_path()}.lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        cur = J.read_json(spend_path())
        cur = cur if isinstance(cur, dict) else {}
        row, s = _today_row(cur, handle, day)
        if s + usd > c:
            return s, c
        row = dict(row) if row.get("day") == day else {}
        row.update(day=day, usd=round(s + usd, 2))
        cur[handle] = row
        J.write_atomic(spend_path(), cur)
    return None


def route(job) -> str:
    return f"#{job.member}" if getattr(job, "member", None) else ""


__all__ = ["member_of", "boundary_path", "member_token", "member_project_url", "member_clone", "walls", "spent",
           "charge", "route", "env", "BOUNDARY_PATHS", "TOKEN_SHAPES", "MEMBER_DAILY_USD"]
