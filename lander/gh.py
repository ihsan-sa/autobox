"""GitHub, through the `gh` on PATH — the one place the lander asks it anything or merges.

    gh(argv, root, token=None, timeout=120)  -> (rc, stdout, stderr). A member landing passes its workspace token:
        it goes in GH_TOKEN (GH_CONFIG_DIR at an empty dir, so the box's own login is never used) and is printed
        nowhere.
    pr_facts(root, pr, fields) -> (dict, "") | (None, why)     one `gh pr view --json <fields> [-R <slug>]`
    pr_files(root, pr) -> [paths] | None · slug(root) -> "owner/name" | ""
    merge_state(root, pr) -> (state, merge_oid): GitHub's "MERGED"/"OPEN"/"CLOSED" and the squash commit's oid, or
        ("", "") when gh would not answer — which is never read as "not merged".
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
        env.update(GH_TOKEN=token, GH_CONFIG_DIR=os.path.join(root, ".gh-none"))
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
