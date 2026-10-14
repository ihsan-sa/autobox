"""Main's own health: which checks are red on main, found on main itself rather than by a PR whose red judge() re-ran
on its base (architect panel, 10-13: 585 of 1,334 check rounds in 7 days ended in a main-red hold).

    run(repo, check, fallback="")  the tick's call after a tip run, under its own lock (lock(repo)), never the tip
                                   lock, so a merge's tip run and deploy never wait on it. On a tip not yet checked: each
                                   blocking check (plan.select, less the box checks the tip run itself runs and the
                                   checks nightly.py moved out) that the range since the last checked tip reaches, and
                                   every check the record holds red, run once on the tip by `check(name, sha)`
                                   (tick.make_check). Each result is recorded. A check that turns red sends ONE alert
                                   on the tip run's route, naming the check, the merge, and whether the merge's parent
                                   passes it (code: the merge broke it) or fails it too (machine). -> {name: status}
                                   of what ran, {} when the tip was already checked. Each result is written as it
                                   finishes, with "running": tip; a pass killed part-way leaves those on disk, and the
                                   next pass on the same tip runs only the checks it had not reached.
    lock(repo)                     the health lock: True when held, False when another pass holds it (never waits)
    pending(repo)                  a pass is owed though no tip was just looked at: one was killed part-way, or a tick
                                   found the lock taken and asked for one more (want(repo)), since the running pass
                                   may be on an older tip.
    red(repo)                      {name: entry} of every check the record holds red on main, whatever tree
    at(repo, tree)                 {name: status} measured on exactly `tree` within the last FRESH seconds: a fresh
                                   record of a PR's base, which run.judge() takes instead of running the check on that
                                   base again. An older one is left out, so the base runs as before: main sitting
                                   still while the box breaks a check must not leave a stale green blaming every PR.
    trim(repo, m, plan, files)     the lane's plan without the checks red on main that the change owns no path of;
                                   Plan.extra["main_red"] names them. A change that touches one keeps it: it must turn
                                   it green, and while main is still red on it a red there is main's (judge's
                                   blocked-by-main), so it waits for that check alone.

THE RECORD, <land state>/tip/<repo>.health: {"tip": the last tip checked in full, "running": the tip a
pass is on ("" between passes), "checks": {name: {"status", "tree", "tip",
"at", "since", "cause"}}}. since and cause are kept from the run that turned the check red until it is green again.
An unrunnable result is never recorded, as red or green. Nothing here holds a deploy or reverts a merge: the tip run
does that, for the box checks.
"""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import os
import re

from lander import cards as C
from lander import types as T

PR_RE = re.compile(r"\(#(\d+)\)$")
FRESH = 2 * 3600   # seconds a record of a base tree stands in for a run on it


def path(repo):
    return C.state("tip", f"{repo}.health")


def load(repo):
    rec = C.read_json(path(repo), {}) or {}
    return {"tip": rec.get("tip") or "", "running": rec.get("running") or "", "checks": dict(rec.get("checks") or {})}


def red(repo):
    return {n: e for n, e in load(repo)["checks"].items() if e.get("status") == T.FAILED}


def age(stamp, now=None):
    """Seconds since a C.now() stamp; None when it cannot be read, which no caller trusts."""
    try:
        t = datetime.datetime.strptime(stamp or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    return ((now or datetime.datetime.now(datetime.timezone.utc)) - t).total_seconds()


def at(repo, tree, now=None):
    # architect read, 10-13: "Only trust a record younger than a set limit, and otherwise run the base as before"
    if not tree:
        return {}
    out = {}
    for n, e in load(repo)["checks"].items():
        a = age(e.get("at"), now)
        if e.get("tree") == tree and a is not None and a < FRESH:
            out[n] = e["status"]
    return out


def trim(repo, m, plan, files):
    """Any fault keeps the plan whole: running a check is never the wrong answer."""
    if plan is None:
        return plan
    try:
        held = set(red(repo)) & set(plan.checks)
        # brief: "Planning a PR leaves out checks currently red on main unless the PR touches that check's owned paths"
        out = sorted(n for n in held if n in m.checks and not any(m.owns(n, f) for f in files))
    except Exception:  # noqa: BLE001
        return plan
    if out:
        plan.checks = [n for n in plan.checks if n not in out]
        plan.extra["main_red"] = out
    return plan


def select(m, files):
    """The blocking checks the changed files reach on main: what a PR changing them would run before its merge."""
    from lander import manifest as MF
    from lander import plan as P
    return {n for n in P.select(m, list(files)).checks if n in m.checks and n != MF.BUILTIN}


def git(root, *args):
    rc, out = C.sh(["git", *args], cwd=root, timeout=300)
    return rc, out.strip()


@contextlib.contextmanager
def lock(repo):
    """Its own lock, not the tip lock: on 10-13 a pass held the tip lock for an hour and #1308's tip run and deploy
    could not start."""
    p = C.state("tip", f"{repo}.health.lock")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd = os.open(p, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        os.close(fd)


def want_path(repo):
    return C.state("tip", f"{repo}.health-want")


def want(repo):
    if not os.path.exists(want_path(repo)):
        C.write_json(want_path(repo), {"at": C.now()})


def pending(repo):
    return bool(load(repo)["running"]) or os.path.exists(want_path(repo))


def run(repo, check, fallback=""):
    from lander import deploy as D
    from lander import manifest as MF
    from lander import nightly as NG
    from lander import run as RUN
    from lander import tip as TP
    with contextlib.suppress(FileNotFoundError):
        os.unlink(want_path(repo))   # this pass answers any want made before it read origin's tip
    root, base = D.root_of(repo), D.base_of(repo)
    tip = TP.origin_tip(root, base)
    rec = load(repo)
    if not tip or rec["tip"] == tip:
        return {}
    rc, parent = git(root, "rev-parse", "--verify", "-q", f"{tip}^1")
    parent = parent if rc == 0 else ""
    last = rec["tip"] or parent
    rc, out = git(root, "diff", "--name-only", "--no-renames", "-z", last, tip) if last else (1, "")
    files = [f for f in out.split("\0") if f] if rc == 0 else []
    m = MF.load(root, tip, fallback=fallback, strict=False)
    # 2026-10-14: #1286 retired the cc-member-* checks, and their FAILED entries stayed red here for good. A tip
    # manifest that read empty is no word on what main retired, so it prunes nothing.
    for n in [n for n in rec["checks"] if m.checks and n not in m.checks]:
        del rec["checks"][n]
    plan =T.Plan(checks=sorted(select(m, files)), klass=T.LEAF)
    names = set(NG.trim(repo, m, plan).checks) | {n for n in rec["checks"] if n in m.checks and
                                                  rec["checks"][n].get("status") == T.FAILED}
    # brief: "a killed or interrupted run keeps what it already learned and the next run picks up from there"
    if rec["running"] == tip:
        names = {n for n in names if (rec["checks"].get(n) or {}).get("tip") != tip}
    rec["running"] = tip
    C.write_json(path(repo), rec)
    tree = RUN.tree_of(root, tip)
    rc, subject = git(root, "log", "-1", "--format=%s", tip)
    merge = subject if rc == 0 and subject else tip[:12]
    done = {}
    for name in sorted(names):
        r = check(name, tip)
        if r.status == T.UNRUNNABLE:
            continue
        done[name] = r.status
        was = rec["checks"].get(name) or {}
        e = {"status": r.status, "tree": tree, "tip": tip, "at": C.now()}
        if r.status == T.FAILED and was.get("status") == T.FAILED:
            e.update(since=was.get("since", ""), cause=was.get("cause", ""))
        elif r.status == T.FAILED:
            e.update(since=tip, cause=cause(check(name, parent).status if parent else T.UNRUNNABLE))
            alert(repo, base, name, tip, merge, e["cause"])
        rec["checks"][name] = e
        C.write_json(path(repo), rec)   # as it finishes: a killed pass keeps what it learned
        C.log("main-health", repo, "tip", tip=tip[:12], check=name, ok=r.status)
    rec["tip"], rec["running"] = tip, ""
    C.write_json(path(repo), rec)
    return done


def cause(at_parent):
    """The merge's parent passes the check: the merge broke it (code). It fails there too: the tree that was green on
    main is red now, which no code did (machine). The parent could not run it: unknown.
    brief: "whether the red reproduces at the merge's parent (code) or not (machine)" — read here the other way round,
    since a red the parent shares is not the merge's code; the PR says so for perms' read."""
    return {T.PASSED: "code", T.FAILED: "machine"}.get(at_parent, "unknown")


def alert(repo, base, name, tip, merge, why):
    m = PR_RE.search(merge)
    what = f"PR #{m.group(1)}" if m else f"commit {tip[:12]}"
    said = {"code": f"its parent passes it, so {what} broke it",
            "machine": "its parent fails it too, so the box changed, not the code",
            "unknown": "it could not be run on the parent, so whether it is the code or the box is not known"}[why]
    text = (f"[{repo}] {name} went red on {base} at {tip[:12]} ({merge}): {said}. PRs that touch none of its paths "
            f"land without it until {base} is green on it again.")
    pid = f"land:{repo}:main-red:{name}@{tip[:12]}"
    C.say(pid, [os.path.join(C.BIN, "cc-slack"), "post", "--route", f"[{repo}] main red", "--id", pid, text], repo, 0)
