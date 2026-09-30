"""The tip run: after merges, the checks the merged changes reach run once on main's tip, and only a green tip deploys.

    kick(repo)                     a merge happened; the next tick runs the tip. Idempotent: ten merges before the
                                   tick are one run over all ten (COALESCED since the last green tip)
    run(repo, plan, check)         the tick's call. `plan(root, base, head, files) -> Plan` is U2's planner and
                                   `check(name, sha) -> Result` runs one named check on one commit (the tick builds it
                                   from U2's runner). Answers "green", "red", "retry", "wait" or "idle".
    catchup(repo)                  origin's main moved without this box (a hand merge, another box): kick a tip run
                                   for it, so it is checked and deployed like any merge. No <repo>.applied yet: it
                                   is seeded from the checkout's HEAD. A tip <repo>.tip-red (or the old lander's
                                   <repo>.red) names is skipped: a person mends it, not the poll
    lock(repo)                     one tip run per repo at a time (tick takes it; a second tick skips, never waits)
    green(repo, sha)               the tip run passed at exactly `sha` (deploy.run asks this)

GREEN: every check the plan names over <last green>..<tip> passed. The green sha is recorded, and a deploy of that
sha is requested and run (deploy.request, deploy.run). UNRUNNABLE (killed, OOM, no result) is never red: the run is
kept wanted and the next tick retries it.

RED: the repo's deploy targets are held (deploy.hold), so nothing red is installed, and <repo>.tip-red says why. Then
each failing check alone is bisected over the first-parent commits since the last green tip. A breaker is PROVEN
when it fails that check twice and its parent passed it; then, and only then, it is reverted: a throwaway worktree
at the tip, `git revert`, a push to the base branch, a comment on its PR, a card to its thread and the repo's seat
told. Anything short of proof (an unrunnable step, a flaky second run) reverts nothing and says the tip is red.
A revert moves the tip, so the run kicks itself; the next tick checks the reverted tip. A kick for a tip already
found red (<repo>.tip-red names it) runs nothing again: it answers "red" until the tip moves.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import re
import shutil
import tempfile

from lander import cards as C
from lander import deploy as D
from lander import git as G
from lander import types as T

PR_RE = re.compile(r"\(#(\d+)\)$")


def want_path(repo):
    return C.state("tip", f"{repo}.want")


def green_path(repo):
    return C.state("tip", f"{repo}.green")


def red_path(repo):
    return C.state(f"{repo}.tip-red")


def old_red_path(repo):
    """The old lander's note of a red base tip (after_batch); kept honoured until nothing writes it."""
    return C.state(f"{repo}.red")


@contextlib.contextmanager
def lock(repo):
    """Yields True when this process holds the repo's tip lock, False when another does (it does not wait)."""
    path = C.state("tip", f"{repo}.lock")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        os.close(fd)


def kick(repo):
    if not os.path.exists(want_path(repo)):
        C.write_json(want_path(repo), {"at": C.now()})


def green(repo, sha):
    return bool(sha) and (C.read_json(green_path(repo), {}) or {}).get("sha") == sha


def git(root, *args, timeout=300):
    rc, out = C.sh(["git", *args], cwd=root, timeout=timeout)
    return rc, out.strip()


def origin_tip(root, base):
    """origin's <base> fetched from the lander's own URL and checked against ls-remote (deploy.verified_tip), or ''."""
    with D.git_lock(root):
        return D.verified_tip(root, base)


def catchup(repo):
    """-> True when origin moved past what this box runs and a tip run is now wanted."""
    root = D.root_of(repo)
    if not os.path.isdir(os.path.join(root, ".git")) and not os.path.isfile(os.path.join(root, ".git")):
        return False
    base = D.base_of(repo)
    tip = origin_tip(root, base)
    if not tip:
        return False
    have = D.applied(repo)
    if not have:
        rc, cur = git(root, "rev-parse", "--abbrev-ref", "HEAD")
        rc2, head = git(root, "rev-parse", "HEAD")
        if rc or rc2 or cur != base:
            return False
        D.record_applied(repo, head)
        have = head
    red = C.read_json(red_path(repo), {}) or {}
    old = C.read_json(old_red_path(repo), {}) or {}
    if have == tip or tip in (red.get("tip"), old.get("tip")) or D.waiting(repo):
        return False
    kick(repo)
    return True


def run(repo, plan, check, targets=None):
    if not os.path.exists(want_path(repo)):
        return "idle"
    root, base = D.root_of(repo), D.base_of(repo)
    targets = list(targets or [repo])
    tip = origin_tip(root, base)
    if not tip:
        return "retry"
    if (C.read_json(red_path(repo), {}) or {}).get("tip") == tip:
        # already found red and said so: a kick (the tick's, for a job still waiting) does not run it all again
        with contextlib.suppress(OSError):
            os.unlink(want_path(repo))
        return "red"
    last =(C.read_json(green_path(repo), {}) or {}).get("sha") or D.applied(repo)
    if not last:
        C.write_json(green_path(repo), {"sha": tip, "at": C.now(), "seeded": True})
        return "idle"
    if last == tip:
        os.unlink(want_path(repo))
        return "green"
    rc, out = git(root, "diff", "--name-only", "--no-renames", "-z", last, tip)
    if rc:
        return "retry"
    p = plan(root, last, tip, [f for f in out.split("\0") if f])
    results = {name: check(name, tip) for name in p.checks}
    if any(r.status == T.UNRUNNABLE for r in results.values()):
        C.log("tip-retry", repo, "tip", tip=tip[:12], why="a check could not run; not red")
        return "retry"
    bad = sorted(n for n, r in results.items() if r.status == T.FAILED)
    if not bad:
        C.write_json(green_path(repo), {"sha": tip, "at": C.now(), "checks": sorted(results)})
        with contextlib.suppress(OSError):
            os.unlink(red_path(repo))
        os.unlink(want_path(repo))
        for t in targets:
            D.release(t)
        C.log("tip-green", repo, "tip", tip=tip[:12], checks=len(results))
        D.request(repo, tip, targets)
        D.run(repo, green=green)
        return "green"
    why = f"{', '.join(bad)} failed on {base} at {tip[:12]}"
    C.write_json(red_path(repo), {"tip": tip, "at": C.now(), "why": why, "checks": bad})
    for t in targets:
        D.hold(t, why, tip)
    C.log("tip-red", repo, "tip", tip=tip[:12], checks=",".join(bad))
    rc, out = git(root, "rev-list", "--first-parent", "--reverse", f"{last}..{tip}")
    commits = out.split() if rc == 0 else []
    reverted = False
    for name in bad:
        sha = bisect(commits, name, check)
        if sha and revert(repo, root, base, sha, f"{name} fails from this commit on"):
            reverted = True
            break
    if reverted:
        kick(repo)
    else:
        os.unlink(want_path(repo))
        pid = f"land:{repo}:tip:red@{tip[:12]}"
        C.say(pid, [os.path.join(C.BIN, "cc-slack"), "post", "--route", f"[{repo}] tip red", "--id", pid,
                    f"[{repo}] {why}. Nothing past {last[:12]} deploys until it is green, and no commit is proven "
                    f"to have broken it, so nothing was reverted."], repo, 0)
        C.sh([os.path.join(C.BIN, "cc-slack"), "inject", repo, f"[{repo}] {why}; nothing was reverted."], timeout=120)
    return "red"


def bisect(commits, name, check):
    """The first commit that fails `name`, when that is PROVEN: it fails twice and its parent passed. The run
    before commits[0] (the last green tip) is taken as passed. -> sha or ""."""
    if not commits:
        return ""
    lo, hi = -1, len(commits) - 1          # lo passed (or is the green tip), hi failed
    while hi - lo > 1:
        mid = (lo + hi) // 2
        st = check(name, commits[mid]).status
        if st == T.UNRUNNABLE:
            return ""
        if st == T.PASSED:
            lo = mid
        else:
            hi = mid
    again = check(name, commits[hi]).status
    return commits[hi] if again == T.FAILED else ""


def revert(repo, root, base, sha, why):
    """Revert a proven breaker on the base branch. -> the revert's sha, or "" (and it says why)."""
    rc, subject = git(root, "log", "-1", "--format=%s", sha)
    m = PR_RE.search(subject)
    pr = int(m.group(1)) if m else 0
    done = C.state("tip", f"{repo}.reverted")
    seen = C.read_json(done, []) or []
    if sha in seen:
        return ""
    tip = origin_tip(root, base)
    made, said = "", ""
    rc, _ = git(root, "merge-base", "--is-ancestor", sha, tip) if tip else (1, "")
    if not tip:
        said = f"origin/{base} could not be read"
    elif rc:
        said = f"{sha[:12]} is not on origin/{base}"
    else:
        top = os.path.realpath(os.path.expanduser(C.conf("CC_LAND_SCRATCH", "~/.cc/tmp")))
        os.makedirs(top, exist_ok=True)
        tag = re.sub(r"[^A-Za-z0-9_-]+", "-", repo) or "repo"
        tmp = tempfile.mkdtemp(prefix=f"cc-land.revert.{tag}.{pr or 'base'}.", dir=top)
        tree = os.path.join(tmp, "head")
        try:
            with D.git_lock(root):
                rc, out = git(root, "worktree", "add", "-q", "--detach", tree, tip)
            if rc:
                said = f"no worktree: {D.last(out)}"
            else:
                rc, out = git(tree, "revert", "--no-edit", sha)
                if rc:
                    said = f"git revert: {D.last(out)}"
                else:
                    url = G.remote_url(root)
                    rc, out = (git(tree, "push", "-q", url, f"HEAD:refs/heads/{base}") if url
                               else (1, "the lander holds no remote URL for this checkout"))
                    if rc:
                        said = f"git push: {D.last(out)}"
                    else:
                        made = git(tree, "rev-parse", "HEAD")[1]
        finally:
            with D.git_lock(root):
                git(root, "worktree", "remove", "--force", tree)
            shutil.rmtree(tmp, ignore_errors=True)
    what = f"PR #{pr}" if pr else f"commit {sha[:12]}"
    if made:
        text = (f"[{repo}] {what}: REVERTED ❌ — the tip check on {base} went red and the bisect proves this change "
                f"broke it: {why}. It is reverted in {made[:12]}; open a new PR with the fix, off {base} as it is now.")
        C.write_json(done, (seen + [sha])[-200:])
        C.log("reverted", repo, pr or "tip", sha=sha[:12], by=made[:12])
    else:
        text = (f"[{repo}] {what}: the tip check on {base} went red and the bisect proves this change broke it "
                f"({why}), but the revert did not happen — {said}. {base} is red until a person reverts {sha[:12]} "
                f"or fixes it.")
        C.log("revert-failed", repo, pr or "tip", sha=sha[:12], why=said[:160])
    if pr:
        C.sh(["gh", "pr", "comment", str(pr), "--body", text], cwd=root, timeout=120)
        job = T.Job(repo=repo, pr=pr, extra={"queued_at": sha[:12]})
        tt = C.track_thread(job)
        pid = C.producer_id(job, "reverted" if made else "revert-failed")
        C.say(pid, [os.path.join(C.BIN, "cc-slack"), "post", "--route", f"{tt} stopped" if tt else
                    f"[{repo}] PR #{pr} stopped", "--id", pid, text], repo, pr)
    C.sh([os.path.join(C.BIN, "cc-slack"), "inject", repo, text[:400]], timeout=120)
    return made
