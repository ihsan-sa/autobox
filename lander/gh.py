"""GitHub, through the `gh` on PATH — the one place the lander asks it anything or merges.

    gh(argv, root, token=None, timeout=120)  -> (rc, stdout, stderr). A member landing passes its workspace token:
        it goes in GH_TOKEN (GH_CONFIG_DIR at an empty dir outside the clone, members.gh_config_dir, so the box's
        own login is never used) and is printed nowhere. A callable token (members.gh_token, the app's) is called
        for each gh run; when it gives nothing, gh is not run at all.
    pr_facts(root, pr, fields) -> (dict, "") | (None, why)     `gh pr view --json <fields> [-R <slug>]`'s answer,
        over REST (GET repos/<slug>/pulls/<pr>, .../files, the head's check-runs and status) when every field is in
        REST_FIELDS, else through that GraphQL call; a spent rate limit is said with its reset (spent), GitHub's
        secondary limit as itself (SECONDARY, which clears in minutes)
    get(root, path, token=None, timeout=120) -> (rc, body, stderr): `gh api <path>` (a GET), CONDITIONAL: the last
        answer and its ETag are kept under <LANDQ>/gh-etag, and the GET carries If-None-Match, so an unchanged answer
        is a 304, which costs no quota and gives the kept body while it says open; a closed or merged one is asked
        again plainly, so a planted copy with a current ETag never settles a PR. The kept file is read only when it
        is a regular file, never through a link or a FIFO. Always asked, even for a merged pull: a repo made
        again under its name has a new #1. As #1898's cc-reconcile rest(): the box spent its REST hour 15-25 min
        early, three times on 2026-10-23. prune_kept() drops kept answers a day old; the tick runs it.
    pr_files(root, pr) -> [paths] | None · slug(root) -> "owner/name" | ""
    merge_state(root, pr) -> (state, merge_oid): GitHub's "MERGED"/"OPEN"/"CLOSED" and the squash commit's oid, or
        ("", "") when gh would not answer — which is never read as "not merged".
    ci_state(root, pr, pin, workflows=False, runs=None) -> (state, detail): the PR's GitHub checks at head `pin` —
        "green", "red", "pending", "starved" (every red is an Actions job GitHub cancelled because no hosted runner
        took it, and none is still running; their run ids go into the caller's `runs` list, never parsed from
        detail), "unregistered" (no check yet, though the base has workflows), "none" (no CI at all) or ""
        (unreadable). The lane merges on green or none only.
    workflows_on(root, paths) -> bool: any of the base tree's workflow `paths` is one GitHub lists as active; the tree's
        own answer (any paths at all) when GitHub cannot be read. Cached per repo for WORKFLOWS_TTL.
    rerun(root, run_id) -> (ok, text): `gh run rerun <run_id> --failed [-R <slug>]`, which reruns the cancelled jobs.
    behind(root, pr) -> bool: GitHub's mergeStateStatus is BEHIND (strict branch protection: the PR's branch must hold
        the base's tip before it merges); False when gh would not answer.
    update_branch(root, pr, head) -> (ok, text): `gh api -X PUT repos/<slug>/pulls/<pr>/update-branch -f
        expected_head_sha=<head>`, which merges the base into the PR's branch on GitHub; refused if the head moved.
    merge(root, pr, pin, title) -> (ok, text), ok True | False | None
        `gh api -X PUT repos/<slug>/pulls/<pr>/merge -f merge_method=squash -f sha=<pin> -f commit_title="<title>
        (#<pr>)"`, over REST, then the branch deleted (delete_branch). Merged only when rc is 0 and GitHub's answer
        says merged; any failure is merged only when GitHub then reports the PR MERGED (an earlier merge, a second
        one overlapping this, or gh timing out after GitHub merged), refused when it reports another state, and
        None — unknown — when GitHub cannot be read. REST never arms auto-merge, which would land with nothing
        gating or deploying it.

BACKOFF (B3). A failure that looks like GitHub or the network being down — rc != 0, no JSON on stdout, and text
matching BACKOFF_RE (but not a member token's or GraphQL's rate limit) — records <LANDQ>/lanes/gh.backoff
{until, fails}: 1 minute, doubling per failure up to 30; the box login's spent REST quota sets it to its reset (spent).
backoff() is the seconds left; any gh success clears it. The lane and the tick skip gh work while it runs.
"""
from __future__ import annotations

import contextlib
import glob
import hashlib
import json
import os
import re
import stat
import subprocess
import time
from urllib.parse import quote

BACKOFF_RE = re.compile(r"timeout|timed out|connect|\b502\b|\b503\b|rate limit|could not resolve", re.I)
BACKOFF_MIN, BACKOFF_MAX = 60, 1800


def backoff_path() -> str:
    from lander import jobs as J
    return f"{J.lanes_dir()}/gh.backoff"


def backoff() -> int:
    """Seconds left on the GitHub backoff, 0 when none."""
    from lander import jobs as J
    b = J.read_json(backoff_path()) or {}
    try:
        return max(0, int(float(b.get("until", 0)) - time.time()))
    except (TypeError, ValueError):
        return 0


def _note(rc: int, out: str, err: str) -> None:
    from lander import jobs as J
    if rc == 0:
        if os.path.exists(backoff_path()):
            with contextlib.suppress(OSError):
                os.unlink(backoff_path())
        return
    # a JSON stdout is a body (a title may say "timeout"), so only stderr counts then: gh api still says a spent
    # quota or a 502 there with rc != 0 while stdout holds GitHub's error JSON
    if out.startswith("HTTP/"):   # get()'s -i: a header such as "Connection:" is no failure, so only the body counts
        out = out.replace("\r\n", "\n").partition("\n\n")[2]
    said = err if out.strip().startswith(("{", "[")) else out + "\n" + err
    if not BACKOFF_RE.search(said):
        return
    fails = int((J.read_json(backoff_path()) or {}).get("fails", 0)) + 1
    secs = min(BACKOFF_MAX, BACKOFF_MIN * 2 ** (fails - 1))
    with contextlib.suppress(OSError):
        J.write_atomic(backoff_path(), {"until": time.time() + secs, "fails": fails})


def gh(argv, root, token=None, timeout=120, note=True, stdin=None):
    env = dict(os.environ)
    if callable(token):   # a member's app token (members.gh_token), asked for now: it lives an hour
        token = token()
        if not token:   # never None, which would run gh as the box's own login
            return 1, "", "cc-gh-token handed out no app token for this workspace's repository — gh was not run"
    if token:
        from lander import members as M   # members imports nothing of this module
        try:
            ghc = M.gh_config_dir(root)
        except OSError as e:
            return 1, "", f"cannot make an empty GH_CONFIG_DIR for {root}: {e}"
        env.update(GH_TOKEN=token, GH_CONFIG_DIR=ghc)
    try:
        p = subprocess.run(["gh", *argv], cwd=root, capture_output=True, text=True, timeout=timeout, env=env,
                           **({"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}))
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", "gh timed out"
    except OSError as e:
        rc, out, err = 127, "", f"gh would not run: {e}"
    # spent()'s own ask leaves the backoff its failure set; a member token's or GraphQL's spent quota is not the box
    # login's REST hour every lane runs on, so it holds its own job (spent), not every lane
    if note and not ("rate limit" in err.lower() and (token or "graphql" in err.lower())):
        _note(rc, out, err)
    return rc, out, err


# GITHUB'S SECONDARY (CONTENT-CREATION) LIMIT IS NOT A SPENT QUOTA (raised-cc-done-secondary-limit-stops-rows,
# 2026-10-27): lander record's comment was refused twice with core at 4862 of 5000, and gh's line ran past 200 characters,
# so its tail kept only "(HTTP 403)" and record said waiting would not fix it. It clears by itself in minutes.
SECONDARY = "GitHub's secondary (content-creation) rate limit for this login was hit; it clears by itself in minutes"


def last(text, n=200) -> str:
    # the last line only (Opus read of #2013): an earlier line naming the secondary limit is not the failure that ended it
    line = next((l.strip() for l in reversed((text or "").splitlines()) if l.strip()), "")
    return SECONDARY if "secondary rate limit" in line.lower() else line[-n:]


# THE LANE READS A PR OVER REST (raised-graphql-hour-spent-stalls-landing, 2026-10-19): `gh pr view` spends the
# login's GraphQL hour, which ran out at 18:1xZ with REST still at 4815 of 5000, and every gh pr call on the box failed
# until the reset. A read whose fields are all below is one GET of the pull (and its files), answered in the shape
# `gh pr view --json` gives, so no caller changes; statusCheckRollup is the head's check runs and commit statuses
# (two more GETs, each paged on past 100), the CI wait's every-two-minutes read. Comments are the issue's comments, each marked
# viewerDidAuthor when its author is the login gh runs as (GET /user, once per process and token; no answer fails the read), and a refusal on
# the rate limit says so with its reset.
REST_FIELDS = {"state", "isDraft", "mergeable", "headRefOid", "headRefName", "baseRefName", "title", "body",
               "mergeCommit", "mergedAt", "mergeStateStatus", "files", "number", "url", "statusCheckRollup",
               "comments", "isCrossRepository"}
_VIEWER = {}


def viewer(root, token=None) -> str:
    """The login gh answers as, "" when GitHub will not say (a 502, the timeout, an app token with no user); the
    readers that need it then fail closed. Cached per process for the box login or a token string; a callable token
    is asked each time, as it would share the box login's key."""
    key = token if isinstance(token, str) else "" if token is None else None
    if key is None or key not in _VIEWER:
        rc, out, _ = gh(["api", "user", "-q", ".login"], root, token, 30)
        # rc first, then a login; a 200 with no login has gh -q print the word null, which is no login either
        if rc or out.strip() == "null" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*(\[bot\])?", out.strip()):
            return ""
        if key is None:
            return out.strip()
        _VIEWER[key] = out.strip()
    return _VIEWER[key]


def comments(root, pr, token=None, timeout=120):
    """The PR's comments over REST, in `gh pr view --json comments`' shape ({body, author, createdAt,
    viewerDidAuthor}) -> (list, "") | (None, why)."""
    s = slug(root)
    rc, out, err = gh(["api", "--paginate", f"repos/{s}/issues/{int(pr)}/comments?per_page=100", "-q",
                       ".[] | {body, login: .user.login, createdAt: .created_at}"], root, token, timeout)
    if rc:   # rc first: a refusal's stdout is GitHub's error JSON, not a comment
        return None, spent(root, err, token) or last(err or out) or f"gh exit {rc}"
    me, got = viewer(root, token), []
    if not me:   # fail closed: with no viewer no HANDBACK would be the box's own, and a standing one would be missed
        return None, "GitHub would not say which login gh runs as"
    for line in out.splitlines():
        try:
            c = json.loads(line) if line.strip() else None
        except ValueError:
            return None, "gh answered comments that are not JSON"
        if isinstance(c, dict):
            got.append({"body": c.get("body") or "", "author": {"login": c.get("login") or ""},
                        "createdAt": c.get("createdAt") or "",
                        "viewerDidAuthor": c.get("login") == me})
    return got, ""


def my_open_prs(root, token=None, timeout=120):
    """The open PRs gh's own login opened, over REST (`gh pr list --author @me` spends the GraphQL hour), in that
    list's shape ({number, isDraft, headRefName, baseRefName, createdAt, body}) -> (list, "") | (None, why)."""
    s = slug(root)
    rc, out, err = gh(["api", "--paginate", f"repos/{s}/pulls?state=open&per_page=100", "-q",
                       ".[] | {number, isDraft: .draft, headRefName: .head.ref, baseRefName: .base.ref, "
                       "createdAt: .created_at, body, login: .user.login}"], root, token, timeout)
    if rc:   # rc first: a refusal's stdout is GitHub's error JSON, not a PR
        return None, spent(root, err, token) or last(err or out) or f"gh exit {rc}"
    me = viewer(root, token)
    if not me:
        return None, "GitHub would not say which login gh runs as"
    got = []
    for line in out.splitlines():
        try:
            p = json.loads(line) if line.strip() else None
        except ValueError:
            return None, "gh answered PRs that are not JSON"
        if isinstance(p, dict) and p.pop("login", None) == me:
            got.append(p)
    return got, ""


def comment_why(root, pr, body, token=None) -> str:
    """Post `body` as a PR comment over REST -> "" when GitHub took it, else gh's own words for why not."""
    s = slug(root)   # the body on stdin, never in argv: a long review would pass the kernel's argument limit
    if not s or not str(pr).isdigit():
        rc, out, err = gh(["pr", "comment", str(pr), "--body-file", "-"], root, token, 120, stdin=body)
        return (last(err or out) or f"gh exit {rc}") if rc else ""
    rc, out, err = gh(["api", f"repos/{s}/issues/{int(pr)}/comments", "--input", "-"], root, token, 120,
                      stdin=json.dumps({"body": body}))
    try:
        if not rc and json.loads(out).get("id"):
            return ""
    except (ValueError, AttributeError):
        pass
    return last(err or out) or f"gh exit {rc}"


def comment(root, pr, body, token=None) -> bool:
    """Post `body` as a PR comment over REST; True when GitHub took it."""
    return not comment_why(root, pr, body, token)


def rest_facts(p, want) -> dict:
    """GitHub's REST pull object -> the `gh pr view --json` fields in `want` (files are not in it)."""
    merged = bool(p.get("merged_at"))
    head, base = p.get("head") or {}, p.get("base") or {}
    every = {"state": "MERGED" if merged else str(p.get("state") or "").upper(), "isDraft": bool(p.get("draft")),
             "mergeable": {True: "MERGEABLE", False: "CONFLICTING"}.get(p.get("mergeable"), "UNKNOWN"),
             "headRefOid": head.get("sha") or "", "headRefName": head.get("ref") or "",
             "baseRefName": base.get("ref") or "", "title": p.get("title") or "", "body": p.get("body") or "",
             "mergeCommit": {"oid": p.get("merge_commit_sha") or ""} if merged else None,
             "mergedAt": p.get("merged_at"), "mergeStateStatus": str(p.get("mergeable_state") or "unknown").upper(),
             "number": p.get("number"), "url": p.get("html_url") or "",
             "isCrossRepository": (head.get("repo") or {}).get("full_name") != (base.get("repo") or {}).get("full_name")}
    return {k: every[k] for k in want if k in every}


def rollup(runs, statuses) -> list:
    """REST check runs and commit statuses -> statusCheckRollup's rows, as gh pr view gives them."""
    return ([{"__typename": "CheckRun", "name": r.get("name") or "", "status": str(r.get("status") or "").upper(),
              "conclusion": str(r.get("conclusion") or "").upper(), "detailsUrl": r.get("details_url") or ""}
             for r in runs if isinstance(r, dict)]
            + [{"__typename": "StatusContext", "context": c.get("context") or "", "state": str(c.get("state") or "").upper(),
                "targetUrl": c.get("target_url") or ""} for c in statuses if isinstance(c, dict)])


SPENT = "GitHub's API rate limit for this login is spent"
RESETS = {}   # token -> the end of the hold spent() last found for it, which the lane holds the job until


def spent(root, text, token=None) -> str:
    """One plain line when gh's failure says rate limit and GET rate_limit (free) shows the quota it names (GraphQL
    when its words say so, else core REST) at 0, naming when it resets; RESETS[token] is then that reset, or a minute
    on when it is already past (clock skew). Only the box login's REST quota (token None, core) sets the shared backoff
    every lane and the tick wait on; a member's quota or GraphQL's holds just its job (Opus read of #1799). Else "":
    text that only says rate limit, or a rate_limit that will not answer, is gh's own failure, counted like any other
    (perms' read of #1769: the words alone held a job forever)."""
    if "rate limit" not in (text or "").lower() or "secondary rate limit" in text.lower():
        return ""   # the secondary limit holds no quota at 0: last() names it
    kind = "graphql" if "graphql" in text.lower() else "core"
    rc, out, _ = gh(["api", "rate_limit"], root, token, 30, note=False)
    try:
        r = json.loads(out)["resources"][kind]
        if r["remaining"] != 0:   # "if the quota is NOT spent, the 'rate limit' text was something else"
            return ""
        at = RESETS[token] = max(int(r["reset"]), time.time() + BACKOFF_MIN)
    except (ValueError, TypeError, KeyError, AttributeError):
        return ""
    if token is None and kind == "core":
        from lander import jobs as J
        with contextlib.suppress(OSError):
            J.write_atomic(backoff_path(), {"until": at, "fails": 0})
    return f"{SPENT} until " + time.strftime("%H:%MZ", time.gmtime(at))


def pr_facts(root, pr, fields, token=None, timeout=120):
    s = slug(root)   # named, so a GH_REPO of the caller's cannot point the read at another repository's PR
    want = [f for f in fields.split(",") if f]
    if s and want and set(want) <= REST_FIELDS and str(pr).isdigit():
        j = {}
        if set(want) - {"files", "comments"}:   # statusCheckRollup needs the head this GET names
            rc, out, err = get(root, f"repos/{s}/pulls/{int(pr)}", token, timeout)
            try:
                p = json.loads(out) if not rc else None
            except ValueError:
                p = None
            if not isinstance(p, dict):
                return None, spent(root, err, token) or last(err or out) or f"gh exit {rc}"
            j = rest_facts(p, want)
            if "statusCheckRollup" in want:   # the checks of the head GitHub reports, as GraphQL's rollup is
                sha, got = (p.get("head") or {}).get("sha") or "", []
                for path, key in (("check-runs", "check_runs"), ("status", "statuses")):
                    # paged until total_count is read or a page comes short: a red 101st hides. Every page must
                    # give total_count as a non-negative int, the largest seen is the one the read must reach, and
                    # page 1's says how many pages there can be (total//100+1), so a forged list that never ends
                    # stops there. A page that opens on a row an earlier page opened on is the list going round,
                    # and a list that ends short of its total_count or runs past it was not read as it is: all
                    # fail the read
                    runs, page, firsts, most, pages = [], 1, set(), 0, 1
                    while True:
                        rc, out, err = gh(["api", f"repos/{s}/commits/{sha}/{path}?per_page=100"
                                                  + (f"&page={page}" if page > 1 else "")], root, token, timeout)
                        try:
                            d = json.loads(out) if not rc else {}
                            rows, total = d.get(key), d.get("total_count")
                        except (ValueError, AttributeError):
                            rows = total = None
                        if not isinstance(rows, list):
                            return None, spent(root, err, token) or last(err or out) or f"gh exit {rc}"
                        if type(total) is not int or total < 0:
                            return None, f"{path} page {page} total_count is {total!r}, not a count"
                        most = max(most, total)
                        if page == 1:
                            pages = total // 100 + 1
                        if rows:
                            first = (rows[0].get("id") if isinstance(rows[0], dict) and "id" in rows[0]
                                     else json.dumps(rows[0], sort_keys=True))
                            if first in firsts:
                                return None, f"{path} page {page} repeats an earlier page"
                            firsts.add(first)
                        runs += rows
                        if len(rows) < 100 or len(runs) >= most:
                            break
                        if page >= pages:
                            return None, f"{path} runs past the {pages} page(s) its total_count allows"
                        page += 1
                    if len(runs) != most:
                        return None, f"{path} read {'short' if len(runs) < most else 'past'}: {len(runs)} of {most}"
                    got.append(runs)
                j["statusCheckRollup"] = rollup(*got)
        if "files" in want:
            rc, out, err = gh(["api", "--paginate", f"repos/{s}/pulls/{int(pr)}/files?per_page=100", "-q",
                               ".[].filename"], root, token, timeout)
            if rc:
                return None, spent(root, err, token) or last(err or out) or f"gh exit {rc}"
            j["files"] = [{"path": f} for f in out.splitlines() if f]
        if "comments" in want:
            j["comments"], why = comments(root, pr, token, timeout)
            if j["comments"] is None:
                return None, why
        return j, ""
    rc, out, err = gh(["pr", "view", str(pr), "--json", fields] + (["-R", s] if s else []), root, token, timeout)
    if rc:
        return None, spent(root, err, token) or last(err or out) or f"gh exit {rc}"
    try:
        j = json.loads(out)
    except ValueError:
        j = None
    return (j, "") if isinstance(j, dict) else (None, "gh answered with no PR object")


def pr_files(root, pr, token=None):
    j, _ = pr_facts(root, pr, "files", token)
    if j is None:
        return None
    return sorted({(f.get("path") or "") for f in j.get("files") or [] if isinstance(f, dict)} - {""})


def merge_state(root, pr, token=None):
    """Ask GitHub what became of the PR: gh reporting a failure does not mean the merge did not happen.
    -> (state, merge_oid); ("", "") when GitHub could not be read."""
    j = pr_facts(root, pr, "state,mergeCommit", token, 60)[0]
    if j is None or not j.get("state"):
        return "", ""
    mc = j.get("mergeCommit")
    return str(j["state"]), (str(mc.get("oid") or "") if isinstance(mc, dict) else "")


def behind(root, pr, token=None) -> bool:
    """True when GitHub says the PR's branch is BEHIND its base, the state a strict branch protection refuses to merge
    (chip-flow #66, 2026-10-13: 'Required status check "check" is expected', three times). Unreadable is False."""
    j = pr_facts(root, pr, "mergeStateStatus", token, 60)[0]
    return bool(j) and j.get("mergeStateStatus") == "BEHIND"


def update_branch(root, pr, head, token=None):
    """Merge the base into the PR's branch on GitHub, pinned to `head` (expected_head_sha): GitHub refuses it when the
    branch moved since. The new head is GitHub's merge commit, so the PR's checks run again there. -> (ok, text)."""
    s = slug(root)
    if not (s and head):
        return False, "no GitHub repo or head to update the branch at"
    rc, out, err = gh(["api", "-X", "PUT", f"repos/{s}/pulls/{int(pr)}/update-branch", "-f",
                       f"expected_head_sha={head}"], root, token, 60)
    return not rc, last(err or out) or ("updated" if not rc else f"gh exit {rc}")


CI_GREEN = {"SUCCESS", "NEUTRAL", "SKIPPED"}


def ci_state(root, pr, pin, token=None, workflows=False, runs=None):
    """GitHub CI at the head the merge will pin. -> (state, detail):
    "green" every check and status passed · "red" one failed (detail names each, with its link) · "pending" one is
    queued or running, or GitHub reports another head than `pin` (its checks are not this head's) · "unregistered"
    no check or status yet while `workflows` (the base has .github/workflows): right after a push GitHub takes a
    while to register the runs, so an empty list there is not "no CI" · "none" no check or status at all and no
    workflows — a repo with no CI, which lands as before · "" GitHub could not be read (detail why) · "starved"
    every red is a cancel starved_run() vouches for and nothing is pending: their run ids are appended to `runs`."""
    j, why = pr_facts(root, pr, "headRefOid,statusCheckRollup", token, 60)
    if j is None:
        return "", why
    if (j.get("headRefOid") or "") != pin:
        return "pending", f"GitHub reports head {(j.get('headRefOid') or '?')[:12]}, not {pin[:12]}"
    rows = [r for r in j.get("statusCheckRollup") or [] if isinstance(r, dict)]
    if not rows:
        return ("unregistered", "no check has registered yet, though the base has workflows") if workflows \
            else ("none", "")
    red, pending, cancelled = [], [], []
    for r in rows:
        name = r.get("name") or r.get("context") or "?"
        link = r.get("detailsUrl") or r.get("targetUrl") or ""
        if r.get("__typename") == "StatusContext" or "context" in r:
            word = (r.get("state") or "").upper()
            done = word not in ("PENDING", "EXPECTED", "")
        else:
            word = (r.get("conclusion") or "").upper()
            done = (r.get("status") or "").upper() == "COMPLETED"
        if not done:
            pending.append(name)
        elif word not in CI_GREEN:
            red.append(f"{name} {word.lower() or 'failed'}" + (f" ({link})" if link else ""))
            if word == "CANCELLED":
                cancelled.append((name, r))
    starved = [(name, starved_run(root, r, pin, token)) for name, r in cancelled] \
        if red and len(cancelled) == len(red) else []
    if starved and all(run for _, run in starved):
        if pending:   # `gh run rerun --failed` refuses a run whose other jobs still run: wait for them first
            return "pending", "still running: " + ", ".join(pending)
        if runs is not None:
            runs.extend(dict.fromkeys(run for _, run in starved))
        return "starved", "; ".join(f"{name} cancelled: no hosted runner took it" for name, _ in starved)
    if red:
        return "red", "; ".join(red)
    if pending:
        return "pending", "still running: " + ", ".join(pending)
    return "green", f"{len(rows)} check(s) passed"


WORKFLOWS_TTL = 300
_WORKFLOWS = {}   # slug -> (when, {path: state}) as actions/workflows last answered there


def workflows_on(root, paths, token=None) -> bool:
    """Any of `paths` (the base tree's workflow files) is a workflow GitHub runs: actions/workflows lists its path as
    active (2026-10-21: dispatch's only workflow, disabled_manually since 10-15 but still in the tree, held every PR
    CI_REGISTER_WAITS for runs that never came). GitHub unreadable is the tree's answer, any paths at all, so an outage
    never skips real CI. One read per repo per WORKFLOWS_TTL, so a queue of PRs asks once."""
    if not paths:
        return False
    s = slug(root)
    hit = _WORKFLOWS.get(s)
    if not hit or time.time() - hit[0] > WORKFLOWS_TTL:
        j = api_json(root, f"repos/{s}/actions/workflows?per_page=100", token) if s else None
        rows = j.get("workflows") if isinstance(j, dict) else None
        if not isinstance(rows, list):   # "if that API call fails, fall back to today's tree-only answer"
            return True
        hit = _WORKFLOWS[s] = (time.time(), {r.get("path"): r.get("state") for r in rows if isinstance(r, dict)})
    # a path GitHub doesn't list (added inside the TTL, past page 1, or a name it spells differently) still counts:
    # only a workflow GitHub names as off skips the wait
    return any(hit[1].get(p, "active") == "active" for p in paths)


STARVED_RE = re.compile(r"not acquired by Runner", re.I)
JOB_URL_RE = re.compile(r"/actions/runs/(\d+)/job/(\d+)")


def get(root, path, token=None, timeout=120):
    from lander import jobs as J
    f = f"{J.landq()}/gh-etag/{hashlib.sha1(path.encode()).hexdigest()}.json"
    kept = {}   # read as #1912's rest_kept does: a link, a FIFO or anything not a regular file is no copy
    with contextlib.suppress(Exception), os.fdopen(os.open(f, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)) as r:
        kept = json.load(r) if stat.S_ISREG(os.fstat(r.fileno()).st_mode) else {}
    body = kept.get("body") if isinstance(kept, dict) else None
    tag = ["-H", f"If-None-Match: {kept['etag']}"] if isinstance(body, dict) and kept.get("etag") else []
    rc, out, err = gh(["api", path, "-i", *tag], root, token, timeout)
    head, _, out = out.replace("\r\n", "\n").partition("\n\n") if out.startswith("HTTP/") else ("", "", out)
    if tag and re.match(r"HTTP/\S+ 304", head):
        if body.get("state") == "open":
            _note(0, "", "")   # gh exits 1 on a 304, which is a success
            return 0, json.dumps(body), ""
        # a closed or merged answer is final, and anyone who can write the kept file can give it a current ETag for
        # GitHub's 304 to vouch for, so only GitHub's own body settles it
        rc, out, err = gh(["api", path, "-i"], root, token, timeout)
        head, _, out = out.replace("\r\n", "\n").partition("\n\n") if out.startswith("HTTP/") else ("", "", out)
    m = re.search(r"^etag: *(.+?)\s*$", head, re.I | re.M)
    with contextlib.suppress(ValueError, OSError):
        if m and not rc:
            J.write_atomic(f, {"etag": m.group(1), "body": json.loads(out)})
    return rc, out, err


def prune_kept(age=86400):
    """Drop get()'s kept answers older than `age`: a PR that closed is never asked again, and one still open is asked
    once more with a 200, then kept again."""
    from lander import jobs as J
    for f in glob.glob(f"{J.landq()}/gh-etag/*.json"):
        with contextlib.suppress(OSError):
            if time.time() - os.path.getmtime(f) > age:
                os.unlink(f)


def api_json(root, path, token=None):
    """GET `path` through gh api -> the parsed answer, or None when gh failed or answered no JSON."""
    rc, out, _ = gh(["api", path], root, token, 60)
    try:
        return json.loads(out) if not rc else None
    except ValueError:
        return None


def starved_run(root, row, pin, token=None) -> str:
    """The Actions run id of a CANCELLED check run whose annotations say no hosted runner took it ("The job was not
    acquired by Runner of type hosted even after multiple attempts"), else "" (2026-10-05: four PRs handed back as red
    CI for it, with nothing in their code failing). A PR's workflow with checks: write sets any details_url, name and
    annotations it likes, so the URL's job is read back from GitHub: it must be a github-actions check run whose job
    belongs to the URL's run at head `pin`, or the cancel stays red and nothing is rerun. Unreadable is ""."""
    m = JOB_URL_RE.search(row.get("detailsUrl") or "")
    s = slug(root)
    if not m or not s:
        return ""
    run, job = m.group(1), m.group(2)
    notes = api_json(root, f"repos/{s}/check-runs/{job}/annotations", token)
    if not any(isinstance(n, dict) and STARVED_RE.search(str(n.get("message") or ""))
               for n in (notes if isinstance(notes, list) else [])):
        return ""
    aj = api_json(root, f"repos/{s}/actions/jobs/{job}", token)
    if not isinstance(aj, dict) or str(aj.get("run_id") or "") != run or (aj.get("head_sha") or "") != pin:
        return ""
    cr = api_json(root, f"repos/{s}/check-runs/{job}", token)
    app = cr.get("app") if isinstance(cr, dict) else None
    return run if isinstance(app, dict) and app.get("slug") == "github-actions" else ""


def rerun(root, run_id, token=None):
    s = slug(root)
    rc, out, err = gh(["run", "rerun", str(run_id), "--failed"] + (["-R", s] if s else []), root, token, 60)
    return not rc, last(err or out) or ("rerun" if not rc else f"gh exit {rc}")


def slug(root) -> str:
    """owner/repo off the URL the lander holds for the checkout (git.remote_url, not the shared config's origin),
    so gh deletes only the remote branch; '' when it is not GitHub."""
    from lander import git as G
    url = G.remote_url(root)
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def merge_argv(root, pr, pin, title) -> list:
    """The squash merge over REST, pinned: GitHub refuses it (409) when the head is no longer `pin`. REST never arms
    auto-merge, and spends none of the login's GraphQL hour (2026-10-19: `gh pr merge` failed twice on it)."""
    return (["api", "-X", "PUT", f"repos/{slug(root)}/pulls/{int(pr)}/merge", "-f", "merge_method=squash",
             "-f", f"sha={pin}"] + (["-f", f"commit_title={title} (#{pr})"] if title else []))


def delete_branch(root, pr, token=None) -> str:
    """Delete a merged PR's branch on GitHub, as `gh pr merge --delete-branch` did: only a branch of this repository
    (a fork's is not ours). -> "" when deleted, else why not; never a failure of the merge."""
    s = slug(root)
    p = api_json(root, f"repos/{s}/pulls/{int(pr)}", token)
    head = (p.get("head") or {}) if isinstance(p, dict) else {}
    ref, repo = head.get("ref") or "", ((head.get("repo") or {}).get("full_name") or "")
    if not ref or repo.lower() != s.lower():
        return "the branch was left: GitHub did not name it as this repository's"
    # quoted: a head named x#y would otherwise send DELETE …/heads/x and delete another branch
    rc, out, err = gh(["api", "-X", "DELETE", f"repos/{s}/git/refs/heads/{quote(ref, safe='/')}"], root, token, 60)
    return "" if not rc else f"the branch was left: {last(err or out) or f'gh exit {rc}'}"


def merge(root, pr, pin, title, token=None):
    if not pin:
        return False, "no head to pin the merge to"
    if not slug(root) or not str(pr).isdigit():
        return False, "no GitHub repo or PR number to merge"
    rc, out, err = gh(merge_argv(root, pr, pin, title), root, token, timeout=300)
    try:   # rc first: on a refusal stdout holds GitHub's error JSON, never a merge
        merged = not rc and json.loads(out).get("merged") is True
    except (ValueError, AttributeError):
        merged = False
    if not merged:
        text = (err or out).strip() or f"gh exit {rc}"
        # a refusal ("not mergeable", 405) is merged only when GitHub says MERGED: a PR closed unmerged is not in,
        # and an earlier merge, or one GitHub finished after gh gave up, is
        state = merge_state(root, pr, token)[0]
        if state == "MERGED":
            return True, f"PR #{pr} merged (the merge call failed, but GitHub says it is in)"
        if not state:
            return None, f"merge #{pr}: {last(text)} — and GitHub could not say whether it merged"
        return False, f"merge #{pr}: {spent(root, err, token) or last(text)}"
    left = delete_branch(root, pr, token)
    return True, f"PR #{pr} merged (squash, " + (left or "remote branch deleted") + ")"
