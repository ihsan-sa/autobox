"""The repair round: what the lane does with a PR that conflicts with its base, so a conflict hold mends itself.

    lander repair-sweep [--skip <repo>#<pr>]…   every held job whose hold is a conflict is made due now and its lane
                                                started: the lane's own conflict path (below) takes each one up

THE ROUND (owner 10-04: eleven PRs sat held on conflicts, some for two days, and nothing repaired them or woke anyone;
for one project the held PR was its whole board). The old lander had a rebase round and the new one dropped it at the
cutover (#771); this is that round again, on the same door: `cc <repo> <row> --go <brief> --loop 1 --no-extend
--repair` — cc reserves the repair of the PR at the worktree's head after its own doors (the one way back into a
delivery-pending row) and adopts a reservation a refused launch left open, so a retry is never shut out by the last
try; `--resume-last` when the task record says a worker built it — and `--say` to a seat whose window is live,
because `--go` refuses one. The worker merges the base into the PR's own branch, resolves, runs its gates and pushes;
the held job re-reads the PR at its next wake, a new head is a fresh job, and that one lands.

Lane.conflict asks start(lane, job, paths) and acts on what it answers, (kind, words):

  wait       a round was launched (or is still running) for this head, or `cc` refused it (said in the why and the
             queue log; the next wake tries again, as the next round): held another HOLD_SECS, re-read then
  planning   nothing on the box will repair it: handed back to the planning seat with ONE message (cards.stopped's
             producer id is the job's, so a later sweep or wake never says it again); a push to the branch re-queues it

  · a member's PR or a PR no row owns (a seat's) is `planning` at once: there is no track to send a round to;
  · a row whose branch is not track/<row> and has no task record is `planning`: no round runs outside its worktree;
  · ROUNDS rounds per PR, counted in the lane's own record (jobs.repair_record), so a re-queue, by a person or by
    the round's own worker, does not start the count again; only a merge ends it, so a close and a reopen buy no more.
    The budget is the PR's for its whole life: a round that repaired it gives nothing back for a later conflict.
    A round that pushed a head that still conflicts, or did not push by REPAIR_WAIT, has failed. The ROUNDS+1th
    conflict is `planning`, naming the PR and its files;
  · a launch `cc` refused (paused, the tier, the brief judge) spends no round, since nothing ran: it gives its round
    back and counts a refusal instead; a launch that goes out clears the count, and the REFUSALS-th refusal in a row
    hands the PR to `planning`. A record that is there but will not read is `planning` too: it is no licence for
    more rounds.

A path is the branch's to name, so every one shown (the brief, the why, the board note) goes through jobs.path_names:
control characters out, each cut short, five at most.

No conflict waits behind another PR (Lane.conflict): every conflict of a job that is not light comes here, whatever
else in the lane touches the same files.
"""
from __future__ import annotations

import json
import os
import re
import time

from lander import cards as C
from lander import events as E
from lander import jobs as J
from lander import types as T

ROUNDS = 2
REFUSALS = 8                # launches cc may refuse in a row (about 2 h of wakes) before the PR goes to planning
REPAIR_WAIT = 5400          # seconds a round has to push before it counts as failed
MODEL = os.environ.get("CC_LAND_FIX_MODEL") or "claude-opus-5-5"
LOOP, BUDGET = "1", "12"    # one round (--no-extend)
LIVE_SEAT = "already has a live session"   # cc's refusal of --go on a live window


def _cc(*args, timeout=300):
    """`cc` from the lander's own bin, with the box's machine seam past the brief judge (the brief is the box's)."""
    return C.sh([os.path.join(J.bin_dir(), "cc"), *args], timeout=timeout,
                env=dict(os.environ, CC_BRIEF_MACHINE="1"))


def _last(text):
    return J._CONTROL.sub("", " ".join((text or "").split()))[-200:] or "no output"


def _count(v):
    """A count from the record: an int, never below 0. TypeError or ValueError when it is not a number."""
    return max(0, int(v or 0))


def _task(repo, track):
    """The row's task record (cc-task show), {} when it has none; None when it has one that will not read."""
    if not os.path.lexists(os.path.join(J._home(), ".cc", "state", repo, track, "delivery.json")):
        return {}
    rc, out = C.sh([os.path.join(J.bin_dir(), "cc-task"), "show", repo, track], timeout=60)
    try:
        return json.loads(out) if rc == 0 else None
    except ValueError:
        return None


def brief(job, base, paths, resume):
    files = J.path_names(paths, 10) or "the files GitHub names"
    context = ("This continues your own session, so the change is already in front of you; re-read task.md for scope "
               "added since. " if resume else
               "Read task.md, progress.md and the branch diff to recover what this change is for. ")
    return (f"REBASE ROUND, dispatched by the landing queue itself. No person is waiting in this loop, and what it "
            f"does not resolve goes to the planning seat. {context}GOAL: PR #{job.pr} merges cleanly into {base}. "
            f"WHY: {base} moved under this branch and the two now conflict in {files}, so the landing holds the PR "
            f"and nothing else will move it. DO: `git fetch origin {base}` and merge origin/{base} into this branch "
            f"here, keep both sides' intent where they collide, change nothing the conflict does not touch, and run "
            f"this repo's own gates on the result. BOUNDARIES: this branch and this PR only — no second PR, no push "
            f"to {base} or any other branch, no merge of the PR; the checkpoint hook pushes this branch for you, and "
            f"the landing queue takes the new head by itself. If it cannot be resolved here, end with "
            f"'STATUS: BLOCKED: <what>' in progress.md.")


def start(lane, job, paths):
    """-> (kind, words) for one conflict of `job` with its base; see the module doc. Writes the PR's repair record
    (jobs.put_repair) {track, head, deadline, rounds, refusals[, refused]} before it launches anything."""
    from lander.lane import BoardRules   # asked at call time: lane imports this module as a unit
    base = job.extra.get("base_ref") or "main"
    files = J.path_names(paths) or "files GitHub names"
    if lane.member:
        return "planning", f"it is a member's PR, so no round runs for it: its seat merges {base} in and pushes"
    track = BoardRules().find_track(lane.repo, job)
    if not track:
        return "planning", f"no row owns it, so no round runs for it: merge {base} into it by hand ({files})"
    r = J.repair_record(lane.repo, job.pr)
    try:
        if r is None:
            raise ValueError("not a JSON object")
        done, refusals = _count(r.get("rounds")), _count(r.get("refusals"))
        deadline = float(r.get("deadline") or 0)
    except (TypeError, ValueError, OverflowError):   # a record that will not read is not a licence for more rounds
        return "planning", f"its rebase-round record will not read, so no round runs for it in {track}: {files}"
    now = time.time()
    if r.get("head") == job.head and now < deadline:
        return "wait", f"its rebase round in {track} has until {E.stamp(deadline)} to push"
    if r.get("head") != job.head:
        refusals = 0   # a new head starts a new streak: a long pause before it doesn't take this head's rounds
    if done >= ROUNDS:
        return "planning", f"{done} rebase rounds in {track} did not resolve it: {files}"
    if refusals >= REFUSALS:
        return "planning", (f"the launch of its rebase round in {track} was refused {refusals} times (the last: "
                            f"{_last(str(r.get('refused') or ''))}): {files}")
    branch = job.extra.get("branch") or ""
    task = _task(lane.repo, track)
    if task is None:
        return "planning", f"{track}'s task record will not read, so no round runs for it: {files}"
    if not task and branch != f"track/{track}":
        return "planning", f"{branch or 'its branch'} is not {track}'s own branch, so no round runs for it: {files}"
    resume = not task or (task.get("claim") or {}).get("executor") == "worker"
    r = {"track": track, "head": job.head, "rounds": done + 1, "refusals": 0, "deadline": now + REPAIR_WAIT}
    J.put_repair(lane.repo, job.pr, r)   # counted before the launch: a lane that dies mid-launch has spent the round
    go = brief(job, base, paths, resume)
    rc, out = _cc(lane.repo, track, "--go", go, "--loop", LOOP, *(["--resume-last"] if resume else []),
                  "--no-extend", "--model", MODEL, "--budget", BUDGET, "--repair")
    how = "dispatched"
    if rc and LIVE_SEAT in out:
        # a timeout (rc 124) after cc-msg typed reads as refused: a hung pane may see the brief again on a new head
        rc, out = _cc(lane.repo, track, "--say", go, timeout=120)
        how = "typed to its live seat"
        if rc in (3, 4, 5):   # typed but no turn yet: 3 kept for the busy loop's next tool call (or, rarely, the loop
            # ended before its worker took it), 4 the seat is at a model wall, 5 submitted with no turn in 12 s
            rc, how = 0, "queued for its live seat"
    if rc:   # nothing ran: the round is given back, the refusal counted, and the next wake tries again
        r.update(rounds=done, refusals=refusals + 1, refused=_last(out), deadline=now)
        J.put_repair(lane.repo, job.pr, r)
        E.log("notify", job.repo, job.pr, f"repair refused in {track}: {r['refused']}")
        return "wait", (f"its rebase round {done + 1} in {track} was not dispatched: {r['refused']}"
                        + (" — the next wake tries again" if refusals + 1 < REFUSALS else
                           " — the next wake hands it to the planning seat"))
    C.sh([os.path.join(J.bin_dir(), "cc-board"), "note", lane.repo, track,
          f"lander: PR #{job.pr} conflicts with {base} ({files}) — rebase round {done + 1} of {ROUNDS} {how}"],
         timeout=60)
    E.log("notify", job.repo, job.pr, f"repair {done + 1}/{ROUNDS} {how} in {track} head={job.head[:12]}")
    return "wait", f"rebase round {done + 1} of {ROUNDS} {how} in {track}"


CONFLICT = re.compile(r"PR #\d+ conflicts with ")


def cmd_sweep(argv):
    """Every held job whose why is a conflict, but those --skip names, made due now; each lane is started."""
    skip, args = set(), list(argv)
    while args:
        a = args.pop(0)
        if a == "--skip" and args:
            skip.add(args.pop(0))
        else:
            print(f"lander repair-sweep: unknown argument {a!r}", flush=True)
            return 2
    from lander import lane as LN

    def conflicted(job):
        return job is not None and job.state == T.HELD and CONFLICT.match(job.extra.get("why") or "")

    found = {}
    for p in J.job_files():
        job = J.load_path(p)
        if not conflicted(job):
            continue
        if f"{job.repo}#{job.pr}" in skip:
            print(f"lander repair-sweep: {job.repo}#{job.pr} skipped")
            continue
        found.setdefault(job.repo, []).append(job.pr)
    repos, swept = set(), []
    for repo in sorted(found):
        with J.lane_lock(repo) as got:   # the lane writes these files too: read and write them only while it is ours
            if not got:
                print(f"lander repair-sweep: {repo} lane busy, left for the next pass")
                continue
            for pr in found[repo]:
                job = J.load(repo, pr)   # again, under the lock: the lane may have moved it since
                if not conflicted(job):
                    continue
                job.extra["not_before"] = E.stamp(time.time())
                J.save(job)
                swept.append(f"{repo}#{pr}")
                repos.add(repo)
    for repo in sorted(repos):
        ok, said = LN.spawn_tick(repo)
        print(f"lander repair-sweep: {repo} lane {'started' if ok else 'not started: ' + said}")
    print(f"lander repair-sweep: {len(swept)} held on a conflict made due: {' '.join(swept) or 'none'}")
    return 0


COMMANDS = {"repair-sweep": (cmd_sweep, "make every held conflict due now; its lane repairs it [--skip repo#pr]")}
