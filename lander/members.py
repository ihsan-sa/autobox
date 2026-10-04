"""A member workspace's own landing (review B5; U1 owns its intake). The job's repo is `<handle>--<track>`.

  member_of(repo)         (h, t) for a member project, (h, "") for the workspace itself, ("", "") for the box's
                          own — decided by the marker DEV/<h>/.cc/member-workspace, never by the name.
  member_token(h)         the granted token: MEMBERS/<h>/github-token must be a LINK to a mode-600 file; else "".
                          Printed nowhere.
  member_board(h)         the workspace's own board, read where it lives: MEMBERS/<h>/board/<h>.json, which the
                          box's BOARDS/<h>.json links to and J.board() refuses as a link. Opened with O_NOFOLLOW
                          (and O_NONBLOCK, a regular file only, under a size cap) so a link or FIFO the member leaves
                          at that name reaches nothing of the host's; {} when it cannot be read, and `tracks` always a dict of dict rows. The content is the
                          member's own: each caller checks what it takes from it. A workspace never converted, with
                          a plain (unlinked) BOARDS/<h>.json and no MEMBERS copy, reads that as before.
  granted_orgs(h)         the GitHub orgs the host granted workspace h a token for, read off the NAME of the link
                          MEMBERS/<h>/github-token alone: its target must be SECRETS/github-<h>-<org>.token. The
                          link is read with readlink (never followed, never opened); a target anywhere else, or of
                          any other name, grants nothing. A set, because a workspace may come to hold one per org.
  member_project_url(h, t, pr)  (url, "") or ("", why): the board row's `pr` (member_board) is checked, not trusted — its
                          owner must be one the HOST chose, CC_GH_PERSONAL_OWNER (cc-config) or a granted_orgs(h)
                          org, and the name one `cc-gh-token repos <h> <owner>` lists; anything else is refused
                          before the token is read. Neither the row nor the URL decides which owners are accepted.
  member_clone(repo, url) (root, "") or ("", why): the host-only clone <LANDQ>/clones/<h>--<t>, no checkout, its
                          credential gh's helper answering with GH_TOKEN, never the box's login.
  walls(root, base, head, files)  why or "": a boundary path (BOUNDARY_PATHS: .cc/** and the secret stores), or a
                          token shape (TOKEN_SHAPES) on an ADDED line of the diff, read in git.sealed() with --text so
                          no attribute of the member's hides a line. Checked before any check runs.
  spent(h) -> (usd, cap) · charge(h, usd) -> None | (spent_before, cap)   the day's ledger cc's member_gate keeps,
                          <state>/member-spend.json, cap MEMBER_DAILY_USD (cc-config, else 20).
  route(job)              "#<h>" for a member job, else "" — where its stop is said.
  env(h)                  the GH_TOKEN env for git in the clone, or None.
A member project never deploys (lane.py).
"""
from __future__ import annotations

import fcntl
import fnmatch
import json
import os
import re
import shutil
import stat
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


BOARD_MAX = 8 << 20


def member_board(handle) -> dict:
    if not member_of(handle)[0]:
        return {}
    d = f"{J.members_dir()}/{handle}/board"
    p = f"{d}/{handle}.json"
    if not os.path.lexists(p) and not os.path.lexists(d):
        return J.board(handle)   # never converted: the board is a plain file under BOARDS (J.board refuses a link)
    if os.path.islink(f"{J.members_dir()}/{handle}") or os.path.islink(d):
        return {}
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return {}
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > BOARD_MAX:
            return {}
        with os.fdopen(fd, "rb") as f:
            fd = -1
            j = json.loads(f.read(BOARD_MAX + 1))
    except (OSError, ValueError, RecursionError):   # RecursionError: a deep `[[[[…` is not a ValueError
        return {}
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(j, dict):
        return {}
    rows = j.get("tracks")   # its callers index rows as dicts: anything else in a member's file is no row
    j["tracks"] = {k: v for k, v in rows.items() if isinstance(v, dict)} if isinstance(rows, dict) else {}
    return j


ORG_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")


def granted_orgs(handle) -> set:
    # Most member workspaces' repositories sit in an org of the member's own, not the owner's account, so
    # the owner's own account alone refused the sweep's every queue (review of #965). Which orgs is the HOST's word:
    # `cc-sandbox github` names the link's target after the org it granted, and only that name is read here.
    if not HANDLE_RE.fullmatch(handle or ""):
        return set()
    d = f"{J.members_dir()}/{handle}"
    g = f"{d}/github-token"
    try:
        if os.path.islink(d) or not os.path.islink(g):
            return set()
        target = os.readlink(g)
    except OSError:
        return set()
    secrets = os.path.normpath(f"{J._home()}/.cc/secrets")
    full = os.path.normpath(os.path.join(d, target))
    base = os.path.basename(full)
    if os.path.dirname(full) != secrets or not base.startswith(f"github-{handle}-") or not base.endswith(".token"):
        return set()
    org = base[len(f"github-{handle}-"):-len(".token")]
    return {org} if ORG_RE.fullmatch(org) else set()


def member_project_url(handle, track, pr):
    row = (member_board(handle).get("tracks") or {}).get(track) or {}
    m = re.fullmatch(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/([0-9]+)", row.get("pr") or "")
    if not m or m.group(3) != str(pr):
        return "", f"the {handle} board row for {track} does not carry PR #{pr} (pr='{row.get('pr') or ''}')"
    owner, name = m.group(1), m.group(2)
    powner = config("CC_GH_PERSONAL_OWNER")
    accepted = ({powner} if powner else set()) | granted_orgs(handle)
    # the owner handed on below is the HOST's spelling of it, taken from `accepted`, never the URL's
    hit = next((a for a in sorted(accepted) if a.lower() == owner.lower()), "")
    if not hit:
        return "", (f"{owner}/{name} is not under an account this workspace was granted "
                    f"({', '.join(sorted(accepted)) or 'none: no CC_GH_PERSONAL_OWNER and no org token'})"
                    f" — a granted token opens nothing else")
    rc, out, _ = run([f"{J.bin_dir()}/cc-gh-token", "repos", handle, hit], timeout=60)
    if rc or name.lower() not in {x.strip().lower() for x in out.splitlines() if x.strip()}:
        return "", f"{owner}/{name} is not a repository of workspace {handle} (cc-gh-token repos {handle} {hit})"
    return f"https://github.com/{hit}/{name}.git", ""


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
    # read sealed: a member's own `* -diff` in .gitattributes (or the clone's config) would turn an added line
    # into "Binary files differ" and hide a token from this scan
    with G.sealed(root, base, head) as ((rc, out), run):
        if run is not None:
            rc, mb = run("merge-base", *out)
            rc, out = (rc, mb) if rc else run("diff", "--no-color", "--no-ext-diff", "--no-textconv", "--text",
                                              "--no-relative", "-U0", mb.strip(), out[1])
    if rc:
        return f"git could not show the diff to check it for tokens ({str(out).strip()[-120:]})"
    where = ""
    for ln in out.split("\n"):   # splitlines() also breaks at \r, \x0b, \x85 and U+2028: "+ok\rghp_…" hid its token
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


__all__ = ["member_of", "boundary_path", "member_token", "member_board", "granted_orgs", "member_project_url", "member_clone", "walls", "spent",
           "charge", "route", "env", "BOUNDARY_PATHS", "TOKEN_SHAPES", "MEMBER_DAILY_USD"]
