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
  app_org()               the org the box's GitHub App installation covers, CC_GH_APP_OWNER (cc-config), when an
                          installation is configured (CC_GH_APP_INSTALL_ID); else "". cc-gh-token mints a workspace's
                          push token there, scoped to the repositories `cc-gh-token repos <h>` lists.
  member_project_url(h, t, pr)  (url, "") or ("", why): the board row's `pr` (member_board) is checked, not trusted — its
                          owner must be one the HOST chose, CC_GH_PERSONAL_OWNER (cc-config), a granted_orgs(h)
                          org or app_org(), and the name one `cc-gh-token repos <h> <owner>` lists; anything else is
                          refused before the token is read. Neither the row nor the URL decides which owners are accepted.
  member_clone(repo, url) (root, "") or ("", why): the host-only clone <LANDQ>/clones/<h>--<t>, no checkout, its
                          credential gh's helper answering with GH_TOKEN, never the box's login.
  gh_config_dir(root)     the empty GH_CONFIG_DIR for gh on that clone, <LANDQ>/clones/.gh-none/<h>--<t>: outside
                          the clone, since git will not clone into a directory that holds anything.
  walls(root, base, head, files)  why or "": a boundary path (BOUNDARY_PATHS: .cc/** and the secret stores), or a
                          token shape (TOKEN_SHAPES) on an ADDED line of the diff, read in git.sealed() with --text so
                          no attribute of the member's hides a line. Checked before any check runs. The design system
                          apply-design-system has a workspace commit (design_path: .cc/design-tokens.json and
                          .cc/design-fonts/**) is carved out of the .cc/** wall, never out of SECRET_PATHS or the token
                          scan: each such path the head still holds must be a regular file (git mode 100644 or 100755,
                          so no link and no gitlink), and a font must end .ttf or .otf.
  spent(h) -> (usd, cap) · charge(h, usd) -> None | (spent_before, cap)   the day's ledger cc's member_gate keeps,
                          <state>/member-spend.json, cap MEMBER_DAILY_USD (cc-config, else 20).
  route(job)              "#<h>" for a member job, else "" — where its stop is said.
  link_door(h, owner)     True only for an owner the link's token is for: a granted_orgs(h) org, or CC_GH_PERSONAL_OWNER
                          read without failure (config_read tells a failed read from an empty one). Anything else,
                          a failed or slow cc-config included, is the app's door: it fails closed, never to the link.
  env(h, repo)            git's env in the clone: GH_TOKEN with the link's token on the link's door; else app_gitenv for
                          the clone's URL, or NO_CREDENTIAL when it names no github.com owner (no repo included).
  gh_token(h, repo)       the token gh calls for that project carry: the link's on the link's door, else a callable that
                          asks app_token(h, url) — cc-gh-token's helper, as git asks it — each time gh runs, and that
                          gh.gh() refuses to run gh on when it hands out nothing.
  app_gitenv(h, url)      what `cc-gh-token gitargs <url> <h>` names, as GIT_CONFIG_* (command-line scope, so it resets
                          the global gh helper and is never written to the clone's .git/config). No token is in it,
                          only the helper that mints one when git asks; NO_CREDENTIAL when gitargs names no helper.
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
# What apply-design-system (pdf-material-builder) tells a workspace to commit; every generator reads it from there.
DESIGN_TOKENS, DESIGN_FONTS, FONT_EXTS = ".cc/design-tokens.json", ".cc/design-fonts/", (".ttf", ".otf")
TOKEN_SHAPES = re.compile(r"github_pat_[A-Za-z0-9_]{20,}|\bgh[pousr]_[A-Za-z0-9]{30,}|\bsk-ant-[A-Za-z0-9_-]{20,}"
                          r"|\bxox[abpr]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
HANDLE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def run(argv, cwd=None, timeout=60, env=None, input=None):
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, input=input,
                           stdin=subprocess.DEVNULL if input is None else None,
                           env=dict(os.environ, **env) if env else None)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 125, "", str(e)


def config_read(key):
    """`key` as cc-config holds it: its value when set (which may be ""), "" when it is unset (exit 1, nothing
    printed), and None when the read failed or timed out, so a caller choosing a credential can tell them apart."""
    rc, out, _ = run([f"{J.bin_dir()}/cc-config", "get", key], timeout=30)
    if rc == 0:
        return out.strip()
    return "" if rc == 1 and not out.strip() else None


def config(key, default=""):
    """`key`, or `default` when it is empty, unset or could not be read: for a caller to whom all three mean the same
    (each of them then refuses or takes a default). Never the reader for which credential a call carries."""
    return config_read(key) or default


def member_of(repo):
    h, _, t = (repo or "").partition("--")
    if h and HANDLE_RE.fullmatch(h) and os.path.isfile(f"{J.dev()}/{h}/.cc/member-workspace"):
        return h, t
    return "", ""


def _under(path, globs) -> bool:
    for g in globs:
        if g.endswith("/**"):
            if path == g[:-3] or path.startswith(g[:-2]):
                return True
        elif fnmatch.fnmatchcase(path, g) or path.endswith("/" + g):
            return True
    return False


def boundary_path(path) -> bool:
    return _under(path, BOUNDARY_PATHS)


def design_path(path) -> bool:
    """A path of the design system a member PR may commit under .cc/; a secret's place is never one."""
    return (path == DESIGN_TOKENS or (path.startswith(DESIGN_FONTS) and len(path) > len(DESIGN_FONTS))) \
        and not _under(path, SECRET_PATHS)


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


def _clone_url(repo) -> str:
    from lander import git as G
    return G.remote_url(J.repo_root(repo)) if repo else ""


def env(handle, repo=""):
    """git's env for workspace `handle`'s clone of `repo`: GH_TOKEN with the link's token only on the link's door
    (link_door); on any other the app's helper (app_gitenv), or NO_CREDENTIAL — which is also what no `repo` gets,
    since there is no URL to choose a door by (a caller fetching a URL of its own reads member_token itself). None
    for no handle, or for the link's door with no token at the link."""
    return git_env(handle, _clone_url(repo)) if handle else None


def git_env(handle, url):
    owner = url_owner(url)
    if link_door(handle, owner):
        tok = member_token(handle)
        return {"GH_TOKEN": tok} if tok else None
    # the app's door: git asks cc-gh-token, and the link's token rides along nowhere
    return app_gitenv(handle, url) if owner else dict(NO_CREDENTIAL)


def app_token(handle, url) -> str:
    """The app's installation token for workspace `handle` on `url`, handed out the way git gets it: cc-gh-token's
    helper (`--workspace <h> get`, the credential protocol on stdin), which refuses another workspace's repository.
    "" when it refuses. Printed nowhere."""
    m = re.fullmatch(r"https://github\.com/([^/\s]+/[^/\s]+)", url or "")
    if not m or not HANDLE_RE.fullmatch(handle or ""):
        return ""
    rc, out, _ = run([f"{J.bin_dir()}/cc-gh-token", "--workspace", handle, "get"], timeout=60,
                     input=f"protocol=https\nhost=github.com\npath={m.group(1)}\n\n")
    tok = next((x[len("password="):] for x in out.splitlines() if x.startswith("password=")), "") if rc == 0 else ""
    return tok.strip()


def gh_token(handle, repo):
    """What the lander's gh calls for member project `repo` carry: the link's token (member_token), or, for a project
    only app_org() admits, a callable gh.gh() runs each time it calls gh, since the app token lives an hour and a
    lane run may outlast what is left of it."""
    url = _clone_url(repo)
    if link_door(handle, url_owner(url)):
        return member_token(handle)
    return lambda: app_token(handle, url)


# Resets git's helper list and names none, so a fetch the app should answer fails rather than reaching for gh's.
NO_CREDENTIAL = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": ""}


def app_gitenv(handle, url) -> dict:
    rc, out, _ = run([f"{J.bin_dir()}/cc-gh-token", "gitargs", url, handle], timeout=60)
    lines = out.splitlines()
    if rc or not lines or len(lines) % 2 or any(x != "-c" for x in lines[0::2]):
        return dict(NO_CREDENTIAL)
    pairs = [x.partition("=") for x in lines[1::2]]
    if not any(k == "credential.helper" and v.startswith("!") and "--workspace" in v for k, _, v in pairs):
        return dict(NO_CREDENTIAL)
    e = {"GIT_CONFIG_COUNT": str(len(pairs))}
    for i, (k, _, v) in enumerate(pairs):
        e[f"GIT_CONFIG_KEY_{i}"], e[f"GIT_CONFIG_VALUE_{i}"] = k, v
    return e


def url_owner(url) -> str:
    """The account of a github.com https URL, or "" for anything else."""
    m = re.fullmatch(r"https://github\.com/([^/\s]+)/[^/\s]+", url or "")
    return m.group(1) if m else ""


def link_door(handle, owner) -> bool:
    """True only when the link's token is the one for `owner`: an org granted_orgs(h) names, or CC_GH_PERSONAL_OWNER
    as cc-config read it. Decided by exclusion, so it fails closed: every other owner, no owner, and a config read
    that failed or timed out take the app's door (app_token, app_gitenv), never member_token — a link may be the
    owner's own token, and a slow cc-config once let it reach the app's org this way (review of #1079)."""
    if not owner:
        return False
    if owner.lower() in {o.lower() for o in granted_orgs(handle)}:
        return True
    powner = config_read("CC_GH_PERSONAL_OWNER")
    return bool(powner) and owner.lower() == powner.lower()


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


def app_org() -> str:
    # A workspace with no org token of its own still pushes to the app's org: cc-gh-token mints it an installation
    # token there, scoped to the repositories its ~/dev checkout names as remotes. The org is the HOST's config,
    # the same key cc-gh-token reads, and no org without a configured installation counts.
    org = config("CC_GH_APP_OWNER")
    return org if org and config("CC_GH_APP_INSTALL_ID") and ORG_RE.fullmatch(org) else ""


def member_project_url(handle, track, pr):
    row = (member_board(handle).get("tracks") or {}).get(track) or {}
    m = re.fullmatch(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/([0-9]+)", row.get("pr") or "")
    if not m or m.group(3) != str(pr):
        return "", f"the {handle} board row for {track} does not carry PR #{pr} (pr='{row.get('pr') or ''}')"
    owner, name = m.group(1), m.group(2)
    powner = config("CC_GH_PERSONAL_OWNER")
    aorg = app_org()
    accepted = ({powner} if powner else set()) | granted_orgs(handle) | ({aorg} if aorg else set())
    # the owner handed on below is the HOST's spelling of it, taken from `accepted`, never the URL's
    hit = next((a for a in sorted(accepted) if a.lower() == owner.lower()), "")
    if not hit:
        return "", (f"{owner}/{name} is not under an account this workspace was granted "
                    f"({', '.join(sorted(accepted)) or 'none: no CC_GH_PERSONAL_OWNER, no org token and no app installation'})"
                    f" — a granted token opens nothing else")
    rc, out, _ = run([f"{J.bin_dir()}/cc-gh-token", "repos", handle, hit], timeout=60)
    if rc or name.lower() not in {x.strip().lower() for x in out.splitlines() if x.strip()}:
        return "", f"{owner}/{name} is not a repository of workspace {handle} (cc-gh-token repos {handle} {hit})"
    return f"https://github.com/{hit}/{name}.git", ""


def gh_config_dir(root) -> str:
    """The empty GH_CONFIG_DIR gh runs with for the clone `root` (mode 0700, made here): <clones>/.gh-none/<name>,
    beside the clone and never inside it, since `git clone … .` refuses a directory that already holds anything."""
    d = f"{J.clones_dir()}/.gh-none"
    for x in (J.clones_dir(), d, f"{d}/{os.path.basename(os.path.normpath(root))}"):
        os.makedirs(x, mode=0o700, exist_ok=True)
    return x


def member_clone(repo, url):
    root = f"{J.clones_dir()}/{repo}"
    h = member_of(repo)[0]
    if os.path.isdir(f"{root}/.git"):
        if run(["git", "remote", "get-url", "origin"], cwd=root)[1].strip() != url:
            run(["git", "remote", "set-url", "origin", url], cwd=root)
        return root, ""
    try:
        for d in (J.clones_dir(), root):
            os.makedirs(d, mode=0o700, exist_ok=True)
        ghc = gh_config_dir(root)
    except OSError as e:
        return "", f"cannot make {root}: {e}"
    rc, out, err = run(["git", "clone", "-q", "--no-checkout", "-c", "credential.helper=",
                        "-c", "credential.helper=!gh auth git-credential", url, "."], cwd=root, timeout=900,
                       env=dict(git_env(h, url) or {}, GH_CONFIG_DIR=ghc, GIT_TERMINAL_PROMPT="0"))
    if rc:
        shutil.rmtree(root, ignore_errors=True)
        return "", f"cannot clone {url}: {(err or out).strip()[-200:]}"
    return root, ""


def _utf8(raw):
    """A path git printed as bytes, as text; None when it is not strict UTF-8 or holds U+FFFD."""
    try:
        path = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if "\ufffd" in path else path


def design_walls(run, mb, head, design) -> str:
    """Why the design files of a member change (mb..head, in the sealed repo `run` reads) are refused, or "".
    Read as bytes, so no name is decoded with errors="replace" and no entry slips past the mode check: every entry
    the head holds under the allowance must be a regular file with a UTF-8 name (a symlink is 120000, a gitlink
    160000, a tokens file turned directory leaves `.cc/design-tokens.json/x`), and every design path the change
    names must be in the head or deleted by it."""
    from lander import git as G
    senv, spec = dict(G.blind_env(), GIT_DIR=run.git_dir), (DESIGN_TOKENS, DESIGN_FONTS.rstrip("/"))

    def raw(*args):   # literal pathspecs, so no glob
        p = G._bytes(["git", "--literal-pathspecs", *args, "--", *spec], senv, timeout=120)
        return p.returncode, p.stdout if p.returncode == 0 else p.stderr.decode(errors="replace").strip()[-120:]
    rc, tree = raw("ls-tree", "-r", "-z", "--full-tree", head)
    if rc:
        return f"git could not list the design files to check them ({tree})"
    held = set()
    for ent in filter(None, tree.split(b"\0")):
        meta, _, name = ent.partition(b"\t")
        path, mode = _utf8(name), meta.split(b" ")[0].decode("ascii", "replace")
        if path is None:
            return f"the head holds {name!r} under the design files, and a member PR's design path must be a UTF-8 name"
        if path != DESIGN_TOKENS and not path.startswith(DESIGN_FONTS):
            return f"the head holds {path}, and {DESIGN_TOKENS} must be one regular file"
        if mode not in ("100644", "100755"):   # brief: "Font files must be regular files: refuse symlinks"
            return f"{path} is not a regular file (git mode {mode}), which a member PR's design system must be"
        held.add(path)
    rc, names = raw("diff", "--name-status", "-z", "--no-renames", "--no-relative", "--ignore-submodules=none", mb, head)
    if rc:
        return f"git could not list the design files the change deletes ({names})"
    parts, gone = names.split(b"\0"), set()
    for st, name in zip(parts[0::2], parts[1::2]):
        if _utf8(name) is None:
            return f"the change touches {name!r} under the design files, and a member PR's design path must be a UTF-8 name"
        if st == b"D":
            gone.add(_utf8(name))
    lost = next((f for f in design if f not in held and f not in gone), "")
    return f"{lost} is named by the change but neither held by its head nor deleted, so its mode cannot be read" \
        if lost else ""


def walls(root, base, head, files, genv=None) -> str:
    bad = [f for f in files if boundary_path(f) and not design_path(f)]
    if bad:
        return f"it touches {bad[0]}, which a member PR may not (the boundary or a secret's place)"
    design = [f for f in files if design_path(f)]
    font = [f for f in design if f != DESIGN_TOKENS and not f.lower().endswith(FONT_EXTS)]
    if font:
        return f"it touches {font[0]}, and a member PR's design font must be a .ttf or .otf file"
    odd = next((f for f in design if "\ufffd" in f), "")
    if odd:   # git.py decodes with errors="replace": a name that is not UTF-8 reaches here as U+FFFD and is no name
        return f"it touches {odd!r}, and a member PR's design path must be a UTF-8 name"
    from lander import git as G
    # read sealed: a member's own `* -diff` in .gitattributes (or the clone's config) would turn an added line
    # into "Binary files differ" and hide a token from this scan
    with G.sealed(root, base, head) as ((rc, out), run):
        if run is not None:
            rc, mb = run("merge-base", *out)
            why = design_walls(run, mb.strip(), out[1], design) if design and not rc else ""
            if why:
                return why
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


__all__ = ["member_of", "boundary_path", "design_path", "member_token", "member_board", "granted_orgs", "app_org", "link_door", "url_owner", "config_read", "app_gitenv", "app_token", "gh_token", "git_env", "member_project_url", "member_clone", "gh_config_dir", "walls", "spent",
           "charge", "route", "env", "BOUNDARY_PATHS", "TOKEN_SHAPES", "MEMBER_DAILY_USD"]
