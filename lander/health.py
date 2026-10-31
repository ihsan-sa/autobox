"""Main's own health: which checks are red on main, found on main itself rather than by a PR whose red judge() re-ran
on its base (architect panel, 10-13: 585 of 1,334 check rounds in 7 days ended in a main-red hold).

    run(repo, check, fallback="")  the tick's call after a tip run, under its own lock (lock(repo)), never the tip
                                   lock, so a merge's tip run and deploy never wait on it. On a tip not yet checked: each
                                   blocking check (plan.select, less the box checks the tip run itself runs and the
                                   checks nightly.py moved out) that the range since the last checked tip reaches, and
                                   every check the record holds red, run once on the tip by `check(name, sha)`
                                   (tick.make_check), the checks the record holds red first. Before each check after
                                   the first, origin's tip is read again; once main has moved, the pass moves with it
                                   and runs on the new tip what it had not reached, what the new range reaches and the
                                   record's reds, so no record waits on a tip main has left. After TRIES moves in one
                                   pass it finishes on the tip it has reached without reading origin again, so a main
                                   that merges during every check still gets a whole record. A tip origin will not give
                                   (a failed fetch) logs `unfetched` and is not a move. Each result is
                                   recorded. A check that turns red sends ONE alert on the tip run's route, naming the
                                   check, the merge, and whether the merge's parent passes it (code: the merge broke
                                   it) or fails it too (machine). -> {name: status}
                                   of what ran, {} when the tip was already checked. Each result is written as it
                                   finishes, with "running": tip; a pass killed part-way leaves those on disk, and the
                                   next pass on the same tip runs only the checks it had not reached. After TRIES
                                   passes on one tip that never finished (a check that raises or is killed each time, or
                                   the pass itself raises before any check), the next sends ONE card for it, then clears
                                   "running", stamps the tip in "gave_up" and runs nothing more on it; a send that
                                   raises writes nothing, so the pass stays pending and the next tick sends the card.
    lock(repo)                     the health lock: True when held, False when another pass holds it (never waits)
    pending(repo)                  a pass is owed though no tip was just looked at: one was killed part-way, or a tick
                                   found the lock taken and asked for one more
                                   (want(repo)), since the running pass may be on an older tip.
    red(repo)                      {name: entry} of every check current() holds red on main, whatever tree, if fresh
    current(repo, rec=None)        {name: entry} of each red the record holds that no tip run has outlived: one that
                                   ran the check (tip.run runs main's reds too), went green after the red was
                                   recorded, on the red's tip or a descendant of it. The record keeps a retired red,
                                   so the next pass runs it first.
    at(repo, tree)                 {name: failed} of each check red on exactly `tree` within the last FRESH seconds:
                                   a fresh record of a PR's base, whose red run.judge() takes instead of running a
                                   security check on that base again. An older one is left out, so the base runs as
                                   before. A green is left out too: a green 62 minutes old blamed a PR for main's own
                                   red under load (10-25).

A check red here is never left out of a PR's plan: the record says only that the check is red, not which cases, so a
PR that owned none of its paths was planned without it, and a red case it added there landed unseen behind main's
(10-20). The PR runs it, and run.judge's ratchet lets it pass only when every case it fails fails on main's tree too,
or, where neither run names a case, when it fails no more of them than main's tree.

THE RECORD, <land state>/tip/<repo>.health: {"tip": the last tip checked in full, "running": the tip a
pass is on ("" between passes), "tries": [tip, passes started on it], "gave_up": the last tip given up on (its
range stays owed to the next tip's pass, since "tip" is not moved), "checks": {name: {"status", "tree", "tip",
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
TRIES = 3          # passes started on one tip before an unfinished one stops being owed; moves within one pass


def path(repo):
    return C.state("tip", f"{repo}.health")


def load(repo):
    rec = C.read_json(path(repo), {}) or {}
    return {"tip": rec.get("tip") or "", "running": rec.get("running") or "", "tries": list(rec.get("tries") or []),
            "gave_up": rec.get("gave_up") or "",
            "checks": dict(rec.get("checks") or {})}


def red(repo, now=None):
    # read of #1309: as at(), only a record younger than FRESH, so a stale red puts no PR first
    return {n: e for n, e in current(repo).items() if fresh(e, now)}


def current(repo, rec=None):
    # 10-29: dispatch's tip run went green at 28591847 with checks=0, nothing ran `check` there, and its red at
    # 3d121183 kept the main-red alert firing for 4 h after main was fixed. Opus read of #2064: only evidence retires
    # a red, so a pass that has merely started on a newer tip, or a green from an older tip or a seeded one, does not.
    from lander import deploy as D
    from lander import tick as TK
    from lander import tip as TP
    rec = rec or load(repo)
    green = C.read_json(TP.green_path(repo), {}) or {}
    return {n: e for n, e in rec["checks"].items() if e.get("status") == T.FAILED
            and not (n in (green.get("checks") or []) and (green.get("at") or "") > (e.get("at") or "")
                     and TK.covers(D.root_of(repo), green.get("sha"), e.get("tip")))}


def age(stamp, now=None):
    """Seconds since a C.now() stamp; None when it cannot be read, which no caller trusts."""
    try:
        t = datetime.datetime.strptime(stamp or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    return ((now or datetime.datetime.now(datetime.timezone.utc)) - t).total_seconds()


def fresh(e, now=None):
    a = age(e.get("at"), now)
    return a is not None and a < FRESH


def at(repo, tree, now=None):
    # architect read, 10-13: "Only trust a record younger than a set limit, and otherwise run the base as before"
    if not tree:
        return {}
    out = {}
    for n, e in load(repo)["checks"].items():
        if e.get("tree") == tree and e.get("status") == T.FAILED and fresh(e, now):
            out[n] = e["status"]
    return out


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
    root, base = D.root_of(repo), D.base_of(repo)
    tip = TP.origin_tip(root, base)
    rec = load(repo)
    if not tip:   # the want stays: the pass it asked for is still owed
        C.log("main-health", repo, "unfetched", base=base)
        return {}
    with contextlib.suppress(FileNotFoundError):
        os.unlink(want_path(repo))   # this pass answers any want made before it read origin's tip
    if tip in (rec["tip"], rec["gave_up"]):
        return {}
    resume = rec["running"] == tip
    # Opus read of #1326: a check that raises on every try kept "running" set and ran again every tick. Counted before
    # anything below can raise (the reads of #1518): a pass that failed early stayed owed for good.
    tries = (rec["tries"][1] if rec["tries"][:1] == [tip] else 0) + 1
    rec["running"], rec["tries"] = (tip if tries <= TRIES else ""), [tip, tries]
    if tries > TRIES:
        C.log("main-health", repo, "gave-up", tip=tip[:12], tries=TRIES)
        gave_up(repo, base, tip)
        # reads of #1518: stamped, so the next tick on this tip is quiet. Perms' read of #1522: only once the card
        # went out. Opus read of #1527: nothing is written before the send either, so a send that raised leaves
        # running=tip on disk, pending() stays true, and the next tick gives up again and sends.
        rec["gave_up"] = tip
        C.write_json(path(repo), rec)
        return {}
    C.write_json(path(repo), rec)
    last, names, done, moved = rec["tip"], set(), {}, 0
    while True:
        rc, parent = git(root, "rev-parse", "--verify", "-q", f"{tip}^1")
        parent = parent if rc == 0 else ""
        rc, out = git(root, "diff", "--name-only", "--no-renames", "-z", last or parent, tip) if last or parent \
            else (1, "")
        files = [f for f in out.split("\0") if f] if rc == 0 else []
        m = MF.load(root, tip, fallback=fallback, strict=False)
        # 2026-10-14: #1286 retired the cc-member-* checks, and their FAILED entries stayed red here for good. A tip
        # manifest that read empty is no word on what main retired, so it prunes nothing.
        for n in [n for n in rec["checks"] if m.checks and n not in m.checks]:
            del rec["checks"][n]
        plan = T.Plan(checks=sorted(select(m, files)), klass=T.LEAF)
        names |= set(NG.trim(repo, m, plan).checks) | {n for n in rec["checks"] if n in m.checks and
                                                       rec["checks"][n].get("status") == T.FAILED}
        if m.checks:   # a check the new tip's manifest retired is not run on it, nor written back
            names &= m.checks.keys()
        # brief: "a killed or interrupted run keeps what it already learned and the next run picks up from there"
        if resume:
            names, resume = {n for n in names if (rec["checks"].get(n) or {}).get("tip") != tip}, False
        tree = RUN.tree_of(root, tip)
        rc, subject = git(root, "log", "-1", "--format=%s", tip)
        merge = subject if rc == 0 and subject else tip[:12]
        new = ""
        # 10-27: a pass on 5fadc4da ran three hours after main had moved five merges on; 10-30: one ran 39 checks
        # on 0d6fc10a for seven hours while #2068's fix sat on main. Main's reds run first, and a tip that moved takes
        # the pass with it: what is left, what the new range reaches and main's reds run on the newest tip.
        for i, name in enumerate(sorted(names, key=lambda n: ((rec["checks"].get(n) or {}).get("status") != T.FAILED,
                                                              n))):
            if i and moved < TRIES:   # security read of #2084: a main merging during every check never ends a pass
                now = TP.origin_tip(root, base)
                if not now:
                    C.log("main-health", repo, "unfetched", tip=tip[:12])
                elif now != tip:
                    new = now
                    break
            names.discard(name)
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
        if not new:
            break
        C.log("main-health", repo, "moved", tip=tip[:12], to=new[:12])
        last, tip, moved = tip, new, moved + 1
        rec["running"], rec["tries"] = tip, [tip, 1]
        C.write_json(path(repo), rec)
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
    text = (f"[{repo}] {name} went red on {base} at {tip[:12]} ({merge}): {said}. Until {base} is green on it "
            f"again, a PR lands only if every case it fails is red on {base} too.")
    pid = f"land:{repo}:main-red:{name}@{tip[:12]}"
    C.say(pid, [os.path.join(C.BIN, "cc-slack"), "post", "--route", f"[{repo}] main red", "--id", pid, text], repo, 0)


def gave_up(repo, base, tip):
    """One card per tip main health stopped trying: until #1518's follow-up only a log line said so."""
    text = (f"[{repo}] main health gave up on {base} at {tip[:12]}: {TRIES} passes started there and none finished, "
            f"so its checks were not recorded on that tip. The next merge's pass covers its range again.")
    pid = f"land:{repo}:main-health-gave-up@{tip[:12]}"
    C.say(pid, [os.path.join(C.BIN, "cc-slack"), "post", "--route", f"[{repo}] main health", "--id", pid, text],
          repo, 0)
