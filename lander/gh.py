"""GitHub, through the `gh` on PATH — the one place the lander asks it anything or merges.

    gh(argv, root, token=None, timeout=120)  -> (rc, stdout, stderr). A member landing passes its workspace token:
        it goes in GH_TOKEN (GH_CONFIG_DIR at an empty dir outside the clone, members.gh_config_dir, so the box's
        own login is never used) and is printed nowhere.
    pr_facts(root, pr, fields) -> (dict, "") | (None, why)     one `gh pr view --json <fields> [-R <slug>]`
    pr_files(root, pr) -> [paths] | None · slug(root) -> "owner/name" | ""
    merge_state(root, pr) -> (state, merge_oid): GitHub's "MERGED"/"OPEN"/"CLOSED" and the squash commit's oid, or
        ("", "") when gh would not answer — which is never read as "not merged".
    ci_state(root, pr, pin, workflows=False, runs=None) -> (state, detail): the PR's GitHub checks at head `pin` —
        "green", "red", "pending", "starved" (every red is an Actions job GitHub cancelled because no hosted runner
        took it, and none is still running; their run ids go into the caller's `runs` list, never parsed from
        detail), "unregistered" (no check yet, though the base has workflows), "none" (no CI at all) or ""
        (unreadable). The lane merges on green or none only.
    rerun(root, run_id) -> (ok, text): `gh run rerun <run_id> --failed [-R <slug>]`, which reruns the cancelled jobs.
    merge(root, pr, pin, title) -> (ok, text), ok True | False | None
        `gh pr merge <pr> --squash --delete-branch --match-head-commit <pin> [-R <slug>] --subject "<title> (#<pr>)"`.
        "already merged" is merged; "is closed" and any other failure are merged only when GitHub then reports the
        PR MERGED (a second merge overlapped this one, or gh timed out after GitHub merged), refused when it reports
        another state, and None — unknown — when GitHub cannot be read. An answer about auto-merge is a refusal:
        auto-merge is never armed, since it would land with nothing gating or deploying it.

BACKOFF (B3). A failure that looks like GitHub or the network being down — rc != 0, no JSON on stdout, and text
matching BACKOFF_RE — records <LANDQ>/lanes/gh.backoff {until, fails}: 1 minute, doubling per failure up to 30.
backoff() is the seconds left; any gh success clears it. The lane and the tick skip gh work while it runs.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import time

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
    if out.strip().startswith(("{", "[")) or not BACKOFF_RE.search(out + "\n" + err):
        return
    fails = int((J.read_json(backoff_path()) or {}).get("fails", 0)) + 1
    secs = min(BACKOFF_MAX, BACKOFF_MIN * 2 ** (fails - 1))
    with contextlib.suppress(OSError):
        J.write_atomic(backoff_path(), {"until": time.time() + secs, "fails": fails})


def gh(argv, root, token=None, timeout=120):
    env = dict(os.environ)
    if token:
        from lander import members as M   # members imports nothing of this module
        try:
            ghc = M.gh_config_dir(root)
        except OSError as e:
            return 1, "", f"cannot make an empty GH_CONFIG_DIR for {root}: {e}"
        env.update(GH_TOKEN=token, GH_CONFIG_DIR=ghc)
    try:
        p = subprocess.run(["gh", *argv], cwd=root, capture_output=True, text=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", "gh timed out"
    except OSError as e:
        rc, out, err = 127, "", f"gh would not run: {e}"
    _note(rc, out, err)
    return rc, out, err


def last(text, n=200) -> str:
    return next((l.strip() for l in reversed((text or "").splitlines()) if l.strip()), "")[-n:]


def pr_facts(root, pr, fields, token=None, timeout=120):
    s = slug(root)   # named, so a GH_REPO of the caller's cannot point the read at another repository's PR
    rc, out, err = gh(["pr", "view", str(pr), "--json", fields] + (["-R", s] if s else []), root, token, timeout)
    if rc:
        return None, last(err or out) or f"gh exit {rc}"
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


STARVED_RE = re.compile(r"not acquired by Runner", re.I)
JOB_URL_RE = re.compile(r"/actions/runs/(\d+)/job/(\d+)")


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
    s = slug(root)
    return (["pr", "merge", str(pr), "--squash", "--delete-branch", "--match-head-commit", pin]
            + (["-R", s] if s else []) + (["--subject", f"{title} (#{pr})"] if title else []))


def merge(root, pr, pin, title, token=None):
    if not pin:
        return False, "no head to pin the merge to"
    rc, out, err = gh(merge_argv(root, pr, pin, title), root, token, timeout=300)
    text = (out + "\n" + err).strip()
    if "already merged" in text:
        return True, f"PR #{pr} was already merged"
    if rc and ("--auto" in text or "auto-merge" in text):
        return False, f"PR #{pr} is not mergeable yet — nothing merged, and no auto-merge was armed"
    if rc:
        # "is closed" is merged only when GitHub says MERGED: a PR closed unmerged is not in
        state = merge_state(root, pr, token)[0]
        if state == "MERGED":
            return True, f"PR #{pr} merged (gh failed, but GitHub says it is in)"
        if not state:
            return None, f"gh pr merge #{pr}: {last(text)} — and GitHub could not say whether it merged"
        return False, f"gh pr merge #{pr}: {last(text)}"
    return True, f"PR #{pr} merged (squash, remote branch deleted)"
