"""lander tick [--repo R] [--detach] [--rearm] — what wakes the lander (review B3). Idempotent; run it any time.

  lanes     each repo with a job or an inbox request (or just R) whose lane is not running: run it here, or with
            --detach start `lander lane <repo>` detached. A lane already running re-reads the queue itself.
  handed    each handed-back watch (handed/<repo>-<pr>.json; R's only, when named): past `until` -> removed,
            `handed-end`; the PR merged or closed -> removed, `handed-end`; the branch head moved (ls-remote, under the
            member's token for a member) -> the reads it used go to carry/ and a request (chat/ts/who only) to the
            inbox, `handed-pushed`, removed. The prior verdict is not carried: the reviewer finds it among the box's
            own PR markers.
            A job for the PR already on the queue ends the watch. Then gh.prune_kept() drops kept PR answers a day old.
  repairs   each job held on a conflict (repair.CONFLICT) that a rebase round was started for at its head (the
            repair record's head is the job's): the branch head moved (ls-remote; '' on any doubt does nothing) ->
            a request (who "repair push", chat/ts) to the inbox, which makes the held job fresh, and a `notify`
            line. A request already waiting for the PR is left to do that. (2026-10-12: #998's round pushed and no
            queue line followed; it sat held until it was queued by hand.)
  strays    for each repo the box knows that lands its own PRs (`cc lands` 0; members skipped) and has a GitHub
            origin, at most every $LANDER_STRAY_SECS (900): the box's own open PRs (`gh pr list --author @me`) are
            read, and one that nothing ever queued is queued here (`queue … --who tick --no-start`, so the protected-
            path door still decides). Left alone: a draft, a head on track/* (cc-loop queues a track's PR), one
            opened under 10 min ago (its seat may queue it itself) or over 48 h ago, and any PR with a job, a rest
            file, a handed watch, an inbox request or a single queue.log line — the lander saw it once, so a stop or
            a refusal is not undone by a sweep. A draft the lander holds a queue job for as a draft, whose body has
            a "Waits on #N" line (#N, #M on one or more such lines), is marked ready (`gh pr ready`) once every PR it
            names has merged; the held job reads it again at its wake. A draft with no job, or held for anything
            else, is never touched, whatever its body says, and a parent closed unmerged is said each sweep and the
            draft kept. The drafts' gh calls are capped per sweep at $LANDER_UNDRAFT_GH (20); the rest wait for the
            next sweep.
            Also left: a head on a LANDER_SELF_MERGE_HEADS_<repo> prefix (cc-config, unset by default, such as
            `dispatch/`), whatever its base or files: that repo lands, reviews and secures those itself (10-24: a
            repo with no security list had every such PR queued while a security-path test stood). An unread setting
            names no prefix, so its PRs queue as before.
  ended     for each repo with a job stopped in query (rest/) or held, at most every $LANDER_ENDED_SECS (900) per repo:
            GitHub is asked what became of each such PR, with no lock held. A held job the lane itself tried to
            merge (merge_attempt set, or held from past queued/planned/checking) is left to the lane, which proves it.
            MERGED (lander-self landed it, or a person merged it by hand) -> merged, with the lane's own
            `stage <repo>#<pr> merged` line (by=outside, sha= the merge commit, merged_at= GitHub's mergedAt), then
            done and `done` rc 0, both written in one save into rest/ (a lane never finds it live at merged); CLOSED
            -> done and `done` rc 1; open on a LANDER_SELF_MERGE_HEADS_<repo> head -> done and `done` rc 1, its
            repo lands it (10-24: such a held job was asked about every sweep, and its notices woke a seat for nothing).
            The locks are taken only to move a job, which is read again under them: a query
            moves under the rest lock; a held job is the lane's, so it moves only while no lane runs (the lane lock,
            never waited on). Nothing is posted, closed on a board or deployed for it:
            the tip catch-up deploys main. One repo's fault is said and logged (tick-fault), never the tick's end.
  limits    each job held on a usage limit, before its until, once `cc-limit status` says clear: a request to the
            inbox, which asks it again (lift_limits). Such a hold wants a tick every review.RETRY_AFTER (waits).
            `lander settle-merged <repo> <pr> [--by WHO]` runs the same for one PR at once (lander-self land calls it).
  landed    each query job host_hold ended at a head perms' ledger now records a LAND for, at the job's change
            (review.perms_recorded; no gh call): a request to the inbox, so this tick's lane runs it again. Any
            writer of the ledger counts, since the ledger is what the host check itself runs on.
  waited    each repo with a job (no gh call; none at all in a GitHub backoff): the oldest due job (Lane.due) queued
            more than cards.WAIT_FLAG_SECS (60 min) ago and not held by the box (lane.box_hold: paused, a tier
            stop; or a lane "box" hold) -> one planner request (cards.waited), once per queuing and at most one per
            repo, or per member across its lanes, per hour; marked sent only once cc-notify took it. A box hold is
            noted (cards.held), and the age counts from the hold's end (the last hold seen, or the job's unheld_at).
  main-red  each repo (none in a GitHub backoff): a check red on main whose oldest hold on a job (extra.main_red
            since=) began more than cards.WAIT_FLAG_SECS ago -> one planner request (cards.main_red) naming the
            check and main's failing cases, at most once an hour per repo and check, whichever PRs it holds. A
            hold main's own record (health) has since seen pass on main says nothing: main went green on it.
  stalled   each repo with a due job whose lane has moved no job on (no verdict, hold, handback, query or merge
            line) for over STALL_TIMES (3) times the p90 of its own last STALL_HISTORY (100) gaps between those, or
            the box's when it has fewer than STALL_GAPS (20) -> one request to its seat (cards.stalled) per stall, at
            most hourly per repo (owner, 10-22: a Hive queue sat 65 min unseen while new PRs kept coming in).
  cards     each repo (those above, and each with a queued-card record) with no lane running whose queued card
            waits on a last edit the box-wide cap or a Slack 429 held (cards.left_held): cards.positions on its queue, so the edit goes once a slot is free; the rearm
            step arms a tick for when it will be (cards.edit_wait). A running lane hands its queue over itself.
  deploy    for each repo with a deploy-pending job, under its rest lock (jobs.rest_lock): tip.kick(repo) and a
            deploy.request not yet made — only when those units are installed.
  tip       for each repo the box knows (boards, <repo>.applied, jobs; members and paused repos skipped), under the
            repo's tip lock (a second tick skips it, never waits): tip.catchup at most every $LANDER_CATCHUP_SECS
            (900) per repo — origin's main past <repo>.applied kicks a tip run, a first sight seeds .applied; then
            tip.run, whose checks are the box-class checks the merged range reaches (tip_plan), each run on its
            commit by U2's runner (make_check). Green deploys that sha (deploy.run); red holds the targets, bisects
            and reverts a proven breaker. Then deploy.run again, for a request whose tip is already green (a retry).
            Then, with the tip lock let go and the repo's jobs settled (below), on a tip the run looked at (green or
            red) or when a pass is owed (health.pending: one killed part-way or stopped, or asked for while another
            ran), health.run under the repo's health lock (a second tick skips it and asks for one more pass): the
            blocking checks the merged range reaches and every check main is red on, run on the tip and kept as
            main's own record (the lane plans by it), each result written as it finishes; a check that turns red is
            said once on the tip run's route; a pass stops once main moves on, owed to the newest tip; a job held
            main-red on a check it finds green is asked again. It holds no deploy, reverts nothing, and never holds
            the tip lock, so the next merge's tip run and deploy start while it runs.
  nightly   for each repo the tip step runs for, at most once every nightly.NIGHTLY_SECS (a day) and only once
            queue.log goes back nightly.WINDOW_DAYS: `lander nightly run --repo <repo>` as a transient unit, which
            runs the checks nightly.py moved out of the per-PR plan on the applied tip.
  settle    each deploy-pending job, under the rest lock (not the lane lock: a busy lane holds that from one job to
            the next, and the lane never takes up a job it rested), once the request covering its tip_sha (that sha
            or a later one) has no target waiting: -> deployed -> done, and `done` rc 0 (verified), 4 (UNVERIFIED) or 1
            (failed). A job whose merge the tip run reverted -> done rc 1.
  backoff   while the GitHub backoff runs (gh.py) no gh work is done: said once, lanes and watches wait.
  rearm     every tick (--rearm is accepted and adds nothing): ONE transient timer per repo that still waits on
            something — a job held with a not_before, a wanted tip run, a requested deploy, a deploy-pending job
            while the tip is not red, an owed main health pass (health.pending), an inbox request (TICK_SECS: one
            written after the tick's lanes ran), a handed watch (TICK_SECS: only its repo's tick sweeps it, and any
            tick arms every repo that has one), or a hold that ran out while a lane runs (TICK_SECS: that lane may
            end without it). `systemd-run --user --on-active=<secs>
            --unit=lander-tick-<repo>-<epoch it fires> <core/bin/lander> tick --repo <repo> --rearm`, skipped when
            the user manager's list-timers shows a lander-tick-<repo>-* timer firing from now to then. A lane run
            outside a tick (`lander lane`: a lane switch's, `tick --detach`'s) rearms its repo as it ends. No unit
            files are written, and nothing depends on a caller ticking.
            A repo with no checkout (repo_root is not a directory) is never armed, so a gone repo's timer dies.
            $LANDER_SYSTEMD_RUN and $LANDER_SYSTEMCTL replace the two binaries (the tests' fakes).
"""
from __future__ import annotations

import contextlib
import glob
import inspect
import io
import json
import os
import re
import subprocess
import sys
import time

from lander import cards as C
from lander import deploy as D
from lander import events as E
from lander import gh as GH
from lander import health as HL
from lander import git as G
from lander import jobs as J
from lander import lane as L
from lander import manifest as MF
from lander import members as M
from lander import nightly as NG
from lander import review as R
from lander import tip as TP
from lander import types as T

TICK_SECS = 120   # how soon a wanted tip run, a requested deploy or an unsettled job is looked at again
STRAY_GRACE = 600            # a seat that queues its own PR in the same turn gets there first
STRAY_MAX_AGE = 48 * 3600    # an older PR that nothing queued was left open on purpose


def sweep_handed(only="") -> list:
    lines = []
    for p in sorted(glob.glob(f"{J.handed_dir()}/*.json")):
        w = J.read_json(p) or {}
        repo, pr = w.get("repo") or "", w.get("pr")
        if only and repo != only:   # brief: "read each PR once per tick round across repos" (18 units read all)
            continue
        if not (isinstance(pr, int) and J.REPO_RE.fullmatch(repo)) or os.path.basename(p) != f"{repo}-{pr}.json":
            with contextlib.suppress(OSError):
                os.replace(p, p + ".unreadable")
            continue

        def end(why):
            with contextlib.suppress(OSError):
                os.unlink(p)
            E.log("handed-end", repo, pr, f"{why}; the watch ends")
            lines.append(f"[{repo}] PR #{pr}: {why}; the watch ends")
        if time.time() >= E.epoch_of(w.get("until")):
            end("watched long enough")
            continue
        job = J.load(repo, pr)
        if job is not None and job.state != T.DONE:
            end("queued again by hand")
            continue
        h = M.member_of(repo)[0]
        genv = M.env(h, repo) if h else None
        root = J.repo_root(repo)
        facts = GH.pr_facts(root, pr, "headRefOid,state", M.gh_token(h, repo) if h else None)[0] or {}
        state = facts.get("state") or ""
        if state in ("MERGED", "CLOSED"):
            end(f"the PR is {state.lower()}")
            continue
        head = G.remote_head(root, w.get("branch") or "", env=genv) or (facts.get("headRefOid") or "")
        if head and head != w.get("head"):
            J.carry(repo, pr, int(w.get("reads_used") or 0))   # the lane's record; a request carries no counts
            J.submit(repo, pr, who="handback push", chat=w.get("chat"), ts=w.get("ts"))
            E.log("handed-pushed", repo, pr, f"{(w.get('head') or '')[:12]}->{head[:12]} — re-queued")
            with contextlib.suppress(OSError):
                os.unlink(p)
            lines.append(f"[{repo}] PR #{pr}: pushed after it was handed back ({head[:12]}) — re-queued")
    return lines


def sweep_repairs() -> list:
    from lander import repair as RP
    lines = []
    for p in J.job_files():
        job = J.load_path(p)
        if not (job and job.state == T.HELD and job.extra.get("hold") != "box" and job.head
                and RP.CONFLICT.match(job.extra.get("why") or "")):
            continue
        r = J.repair_record(job.repo, job.pr)
        if not (r and r.get("head") == job.head) or any(q["pr"] == job.pr for _, q in J.requests(job.repo)):
            continue
        try:   # one PR's fault is said, never the tick's end
            h = M.member_of(job.repo)[0]
            head = G.remote_head(J.repo_root(job.repo), job.extra.get("branch") or "",
                                 env=M.env(h, job.repo) if h else None)
        except Exception as e:  # noqa: BLE001
            lines.append(f"[{job.repo}] PR #{job.pr}: the repair watch could not read its branch: {e}")
            continue
        if head and head != job.head:
            J.submit(job.repo, job.pr, who="repair push", chat=job.extra.get("chat"), ts=job.extra.get("ts"))
            E.log("notify", job.repo, job.pr, f"repair pushed {job.head[:12]}->{head[:12]} — re-queued")
            lines.append(f"[{job.repo}] PR #{job.pr}: its rebase round pushed ({head[:12]}) — re-queued")
    return lines


def self_lands(repo) -> bool:
    """`cc lands <repo>` answers 0: the one reader of the standing grant (CC_SELF_LAND_EXCEPT, member-facing)."""
    try:
        return subprocess.call([os.path.join(J.bin_dir(), "cc"), "lands", repo], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30) == 0
    except (OSError, subprocess.SubprocessError):
        return False


def self_merge_heads(repo) -> list:
    """LANDER_SELF_MERGE_HEADS_<repo> (cc-config, whitespace-separated branch namespaces, each ending in "/", such
    as `dispatch/`): the head prefixes the repo merges on its own read. Kept on the box, so a repo cannot switch off
    its own sweep; [] when unset, when cc-config did not answer, or when any word is not such a namespace or lies
    under track/ (cc-loop's own heads). Each character of the name past [A-Za-z0-9] is written _XX (its hex), so
    a-b (a_2Db) and a_b (a_5Fb) keep keys of their own."""
    key = "LANDER_SELF_MERGE_HEADS_" + re.sub(r"[^A-Za-z0-9]", lambda m: f"_{ord(m.group()):02X}", repo)
    rc, out, _ = L.run([f"{J.bin_dir()}/cc-config", "get", key], timeout=30)
    heads = out.split() if rc == 0 else []
    return heads if all(re.fullmatch(r"(?:[A-Za-z0-9][A-Za-z0-9._-]*/)+", h) and not h.startswith("track/")
                        for h in heads) else []


def default_base(root, slug) -> tuple:
    """(the repo's default branch, the commit a fresh fetch got for it), or ("", "") when either will not read."""
    try:
        name = (GH.api_json(root, f"repos/{slug}") or {}).get("default_branch") or ""
        return (name, G.fetch(root, name)[name]) if name else ("", "")
    except Exception:   # noqa: BLE001 — no default branch read: review's on_default carries nothing
        return ("", "")


def logged_prs(repo) -> set:
    """Every PR number of `repo` that queue.log names at all: one the lander has ever seen, whatever became of it."""
    pat = re.compile(r"^\S+\t\S+ " + re.escape(repo) + r"#([0-9]+)(?:\s|$)")
    seen = set()
    with contextlib.suppress(OSError), open(E.log_path(), errors="replace") as f:
        for ln in f:
            m = pat.match(ln)
            if m:
                seen.add(int(m.group(1)))
    return seen


def has_record(repo, pr) -> bool:
    """A job, a rest file, a handed watch or an inbox request for (repo, pr): the lander holds it already."""
    return (J.load(repo, pr) is not None or os.path.exists(J.rest_path(repo, pr))
            or os.path.exists(J.handed_path(repo, pr)) or any(r["pr"] == pr for _, r in J.requests(repo)))


def sweep_strays(repos) -> list:
    """Queue the box's own open PRs that nothing queued (raised-seat-pr-never-reaches-the-lane, 2026-10-03: a seat's
    `gh pr create` wrote no lane entry, and the PR sat 2.5 h unqueued while the owner had been told it was queued).
    cc-loop queues a track's PR, so a head on track/* is left to it; a draft is a PR its author keeps back.
    A head on a self_merge_heads prefix is left to its repo."""
    lines, budget = [], [undraft_cap()]
    for repo in repos:
        root = J.repo_root(repo)
        if "--" in repo or not os.path.exists(os.path.join(root, ".git")):
            continue
        s = GH.slug(root)
        if not s or not due_every(C.state("tip", f"{repo}.strays"), "LANDER_STRAY_SECS") or not self_lands(repo):
            continue
        prs, why = GH.my_open_prs(root)
        if prs is None:
            lines.append(f"[{repo}] strays: gh could not list the open PRs — {why}")
            continue
        now, seen, heads, parents = time.time(), None, None, {}
        for p in prs:
            if not isinstance(p, dict) or not isinstance(p.get("number"), int):
                continue
            if p.get("isDraft"):
                lines += undraft(repo, root, s, p, parents, budget)
                continue
            n, head = p["number"], str(p.get("headRefName") or "")
            if head.startswith("track/"):
                continue
            if not STRAY_GRACE <= now - E.epoch_of(p.get("createdAt")) <= STRAY_MAX_AGE or has_record(repo, n):
                continue
            seen = logged_prs(repo) if seen is None else seen
            if n in seen:   # landed, refused, stopped or handed back once: what happens next is a person's call
                continue
            heads = self_merge_heads(repo) if heads is None else heads
            if any(head.startswith(h) for h in heads):
                continue    # the repo lands it itself
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                qrc = L.cmd_queue([repo, str(n), "--who", "tick", "--no-start"])
            said = GH.last(buf.getvalue()) or f"exit {qrc}"
            lines.append(f"[{repo}] PR #{n} was open with no landing record — " +
                         (f"queued it ({said})" if qrc == 0 else f"queueing it failed: {said}"))
    return lines


# a line of a draft's body naming the PRs it waits on: "Waits on #1017", "Waits on: #1001 and #1017". Only the list
# straight after the words counts, so "Waits on #5; supersedes #7" names #5 alone.
WAITS_ON = re.compile(r"^[ \t]*(?:[-*][ \t]*)?waits on\b:?((?:[ \t]*(?:,|and\b|&)?[ \t]*#[0-9]+\b)+)", re.I | re.M)


def waits_on(p) -> list:
    """The PR numbers a draft's body names on its "Waits on" lines, its own number left out. #N only: o/r#N is
    another repo's PR, which this sweep does not read."""
    got = []
    for m in WAITS_ON.finditer(str(p.get("body") or "")):
        for n in re.findall(r"#([0-9]+)", m.group(1)):
            if int(n) != p.get("number") and int(n) not in got:
                got.append(int(n))
    return got


def undraft_cap() -> int:
    """How many gh calls one sweep may spend on drafts: $LANDER_UNDRAFT_GH, 20 when unset or not a number."""
    try:
        return max(0, int(os.environ.get("LANDER_UNDRAFT_GH") or 20))
    except ValueError:
        return 20


def undraft(repo, root, s, p, parents, budget) -> list:
    """raised-lander-half-draft-outlives-its-parent, 2026-10-14: three drafts sat ~12 h after their parents merged,
    the un-draft being a line in a seat's journal that nothing acted on. A draft the lander holds a live HELD job for,
    held because it is a draft (lane.DRAFT), whose body says "Waits on #N", is marked ready once every PR it names
    has merged; the held job reads it again at its wake. The body alone is never enough: a tool may open someone
    else's edits as @me drafts for a person to land, with text they wrote in the body, so a planted line must not
    un-draft one. An ended job in rest/ (a handback, a query) is a person's decision still owed, so it does not count
    either; holds re-arm and never move there. A parent closed unmerged is said and the draft kept. parents: {n: state}
    read this sweep; budget: [gh calls left]."""
    n = p["number"]
    job = J.load_path(J.job_path(repo, n))
    # a hold for a conflict or a red check is not one the lander drafted: a person who turned that PR back into a
    # draft meant it, whatever "Waits on" line its body still carries (Opus read of #1344)
    held = job is not None and job.state == T.HELD and L.DRAFT.match(job.extra.get("why") or "")
    want = waits_on(p) if held else []
    if not want:
        return []
    for w in want:
        if w not in parents:
            if budget[0] <= 0:
                return []
            budget[0] -= 1
            facts, why = GH.pr_facts(root, w, "state", None, 60)
            if facts is None:
                return [f"[{repo}] draft PR #{n}: gh could not say whether #{w} merged — {why}"]
            parents[w] = facts.get("state") or ""
    shut = [w for w in want if parents[w] == "CLOSED"]
    if shut:
        return [f"[{repo}] draft PR #{n} waits on " + ", ".join(f"#{w}" for w in shut) +
                ", closed unmerged — it stays a draft for a person"]
    if any(parents[w] != "MERGED" for w in want) or budget[0] <= 0:
        return []
    budget[0] -= 1
    named = ", ".join(f"#{w}" for w in want)
    rc, out, err = GH.gh(["pr", "ready", str(n), "-R", s], root, None, 60)
    if rc:
        why = GH.last(err or out) or f"exit {rc}"
        return [f"[{repo}] draft PR #{n}: {named} merged, but marking it ready failed — {why}"]
    return [f"[{repo}] PR #{n}: {named} merged — marked ready; its held job reads it again at its wake"]


# what the `ended` step looks at: a job stopped for a person, or held, whose PR may have been merged around the lane
ENDED_WATCH = (T.QUERY, T.HELD)


def watched(job) -> bool:
    """A query job, or a held one the lane has not yet tried to merge: one the lane itself merged (merge_attempt set
    at its hold, or held from past PRE_MERGE) is left to the lane's own path, which proves it, closes its row, posts
    it and deploys it."""
    if job is None or job.state not in ENDED_WATCH:
        return False
    # handback on #1250: "Skip held jobs that have merge_attempt set, or whose held_from is outside PRE_MERGE"
    return job.state != T.HELD or (not job.extra.get("merge_attempt")
                                   and job.extra.get("held_from", T.QUEUED) in L.PRE_MERGE)


def ended_jobs(repo="") -> dict:
    """{repo: [pr, …]} of every query job at rest and every held job watched() keeps (of `repo`, when named)."""
    got = {}
    for p in sorted(glob.glob(f"{J.rest_dir()}/*.json")) + J.job_files():
        j = J.load_path(p)
        if not watched(j) or (repo and j.repo != repo) or os.path.basename(p) != f"{j.key}.json":
            continue
        if j.pr not in got.setdefault(j.repo, []):
            got[j.repo].append(j.pr)
    return got


def settle_ended(repo, prs, by="outside", wait=False) -> list:
    """Move each of `prs` that is a watched() job and whose PR GitHub says MERGED to merged then done, CLOSED or
    open on a self_merge_heads prefix to done (tick docstring, `ended`). GitHub is asked first with no lock held (a
    gh call may take 60 s, and a lane that starts meanwhile must not find its lock taken); the locks are then taken
    only to move a job, and each job is read again under them. wait: wait for the rest lock (one PR, asked by
    hand) instead of skipping."""
    h = M.member_of(repo)[0]
    token = M.gh_token(h, repo) if h else None
    root, lines, ended, heads = J.repo_root(repo), [], {}, None
    for pr in prs:
        if not watched(J.load(repo, pr)):
            continue
        facts, why = GH.pr_facts(root, pr, "state,mergedAt,mergeCommit,headRefName", token, 60)
        if facts is None:
            lines.append(f"[{repo}] PR #{pr}: gh could not say whether it merged — {why}")
            continue
        if facts.get("state") not in ("MERGED", "CLOSED"):
            heads = self_merge_heads(repo) if heads is None else heads
            if not any(str(facts.get("headRefName") or "").startswith(x) for x in heads):
                continue
        ended[pr] = facts
    if not ended:
        return lines
    with contextlib.ExitStack() as st:
        lane = st.enter_context(J.lane_lock(repo))   # a held job is the lane's: it moves only while no lane runs
        if not st.enter_context(J.rest_lock(repo, wait=wait)):
            return lines   # a drain or a settle holds it; the next tick looks again
        for pr, facts in ended.items():
            job = J.load(repo, pr)   # the lane or a re-queue may have moved it while GitHub was asked
            if not watched(job) or (job.state == T.HELD and not lane):
                continue
            was = job.state
            if facts["state"] == "MERGED":
                mc = facts.get("mergeCommit")
                oid = str(mc.get("oid") or "") if isinstance(mc, dict) else ""
                J.move(job, T.MERGED, why=f"merged outside the lane, by {by}", defer=True, by=by, sha=oid[:12],
                       merged_at=facts.get("mergedAt") or "")   # one save with done: a lane never sees it merged
                J.move(job, T.DONE, why="merged outside the lane: no deploy of its own, the tip catch-up deploys main")
                E.log("done", repo, pr, rc=0)
                lines.append(f"[{repo}] PR #{pr}: merged on GitHub ({by}) — {was} -> merged -> done")
            else:
                why = "the PR is closed" if facts["state"] == "CLOSED" else "its repo lands it itself"
                J.move(job, T.DONE, why=why)
                E.log("done", repo, pr, rc=1)
                lines.append(f"[{repo}] PR #{pr}: {why} — {was} -> done")
    return lines


def sweep_ended(repo="") -> list:
    """The tick's `ended` step: settle_ended for each repo's query and held jobs, at most every LANDER_ENDED_SECS."""
    lines = []
    for r, prs in ended_jobs(repo).items():
        try:
            if J.REPO_RE.fullmatch(r) and due_every(C.state("tip", f"{r}.ended"), "LANDER_ENDED_SECS"):
                lines += settle_ended(r, prs)
        except Exception as e:  # noqa: BLE001 — as tip_and_deploy: one repo's fault is said and logged
            E.log("tick-fault", r, None, f"ended: {type(e).__name__}: {e}")
            lines.append(f"[{r}] the ended sweep failed: {type(e).__name__}: {e}")
    return lines


def lift_limits(repo="") -> list:
    """The tick's `limits` step: a job held on a usage limit (extra.limit) is asked again once `cc-limit status` says
    clear, whatever its stored until (10-23: an old login's stamp held 14 PRs' reviews for hours after the box had
    moved to an account with room). An inbox request does it (jobs.drain), so a running lane takes it too, and one
    already waiting is enough. cc-limit is asked once a tick, and only while such a hold runs. Only a limit cc-limit
    has a stamp of is marked (review.STAMPED, _buy): one it never saw would read clear and be asked every tick."""
    held = [(r, j.pr) for r in ([repo] if repo else J.all_repos()) for j in J.lane_jobs(r)
            if j.state == T.HELD and j.extra.get("limit") and J.not_before_left(j)]
    if not held or C.sh([os.path.join(R.BIN, "cc-limit"), "status"], timeout=60)[0] != 1:   # 1 = clear; a fault is not
        return []
    waiting = {(q["repo"], q["pr"]) for _, q in J.requests()}
    for r, pr in held:
        if (r, pr) not in waiting:
            J.submit(r, pr, who="limit")
    return [f"[{r}] PR #{pr}: the usage limit it was held on has gone, so it is asked again" for r, pr in held]


def sweep_landed(repo="") -> list:
    """The tick's `landed` step: a query job host_hold ended at a head that perms' ledger now records a LAND for, at
    the job's change (review.perms_recorded, what the host check itself runs on), goes back in the lane however the
    LAND got there. perms-d3, 10-20: a fresh perms seat that `lander record` refuses writes security-reads.json
    itself, and #1724's job sat held until a seat queued it by hand. It reads only local files, so it runs every
    tick. A job whose ledger will not read (an entry perms_recorded raises on) is said and logged, as in
    sweep_ended, and the sweep and the tick go on."""
    lines = []
    for p in sorted(glob.glob(f"{J.rest_dir()}/*.json")):
        j = J.load_path(p)
        h = j is not None and j.state == T.QUERY and (not repo or j.repo == repo) and j.extra.get("host_hold")
        try:
            if h and R.perms_recorded(j.repo, j.pr, h, {j.digest}):
                J.submit(j.repo, j.pr, who="perms")
                lines.append(f"[{j.repo}] PR #{j.pr}: perms' LAND at {h[:12]} is in its ledger — queued again")
        except Exception as e:  # noqa: BLE001 — as sweep_ended: one bad ledger entry never stops every lane
            E.log("tick-fault", j.repo, j.pr, f"landed: {type(e).__name__}: {e}")
            lines.append(f"[{j.repo}] PR #{j.pr}: the landed sweep failed: {type(e).__name__}: {e}")
    return lines


def cmd_settle_merged(argv) -> int:
    pos, opts = L.split_opts(argv, "--by")
    by = opts.get("--by", "") or "outside"
    if len(pos) != 2 or not J.REPO_RE.fullmatch(pos[0]) or not pos[1].isdigit() \
            or not re.fullmatch(r"[A-Za-z0-9._@-]{1,40}", by):
        return L.refuse("usage: lander settle-merged <repo> <pr> [--by WHO]")
    lines = settle_ended(pos[0], [int(pos[1])], by=by, wait=True)
    for ln in lines or [f"[{pos[0]}] PR #{pos[1]}: no query or held job whose PR ended — nothing moved"]:
        print(ln)
    return 0


def retry_deploys(repos) -> list:
    """tip.kick and a deploy request not yet made, for each repo with a deploy-pending job."""
    units = L.load_units()
    tip, deploy = units.get("tip"), units.get("deploy")
    lines = []
    if not (tip or deploy):
        return lines
    for repo in repos:
        pending = [j for j in J.lane_jobs(repo) if j.state == T.DEPLOY_PENDING]
        if not pending:
            continue
        with J.rest_lock(repo) as got:
            if not got:   # a settle or a drain has it; the next tick retries
                continue
            if tip:
                with contextlib.suppress(Exception):
                    tip.kick(repo)
            for job in pending if deploy else []:
                job = J.load(repo, job.pr)   # read again under the lock: a settle may have ended it
                if job is None or job.state != T.DEPLOY_PENDING:
                    continue
                post = job.extra.setdefault("post", {})
                if post.get("deploy") == "ok" or not job.extra.get("tip_sha"):
                    continue
                try:
                    deploy.request(repo, job.extra["tip_sha"], [])
                    post["deploy"] = "ok"
                    lines.append(f"[{repo}] PR #{job.pr}: deploy of {job.extra['tip_sha'][:12]} requested")
                except Exception as e:  # noqa: BLE001 — retried next tick
                    post["deploy"] = f"failed: {e}"[:300]
                J.save(job)
    return lines


def unit_name(repo) -> str:
    return "lander-tick-" + re.sub(r"[^A-Za-z0-9_.-]+", "-", repo)


def armed(out, unit, by) -> bool:
    """Whether list-timers names a timer of this repo's that fires between now and `by`: `<unit>-<epoch>.timer`, the
    epoch when it fires. One firing later is no wait for `by`, and one whose time has passed (the timer of the tick
    running now) is none at all (10-22: a wall hold sat 4 h)."""
    now, pat = time.time(), rf"(?:^|\s){re.escape(unit)}-(\d+)\.timer(?:\s|$)"
    return any(now - 1 <= int(e) <= by for e in re.findall(pat, out, re.M))


def waits(repo) -> list:
    """Seconds until each thing the repo still waits on wants a tick; [] when nothing does. A tip that is red waits
    on a person (or the next merge, whose lane kicks the tip itself), not on a clock."""
    jobs = J.lane_jobs(repo)
    # a usage limit's hold is looked at every RETRY_AFTER, whatever its until: lift_limits ends it with the limit
    held = [min(J.not_before_left(j), R.RETRY_AFTER) if j.extra.get("limit") else J.not_before_left(j)
            for j in jobs if j.state == T.HELD and j.extra.get("not_before")]
    out = [w for w in held if w > 0]
    if 0 in held and J.running(repo):   # a hold ran out while a lane runs: a lane that ends without it is followed up
        out.append(TICK_SECS)
    req = C.read_json(D.req_path(repo)) or {}
    requested = any((st or {}).get("state") == "requested" for st in (req.get("targets") or {}).values())
    pending = any(j.state in (T.DEPLOY_PENDING, T.DEPLOYED) for j in jobs)
    # HL.pending: a killed pass or a want a skipped tick left; health.TRIES bounds how long a pass stays owed. An inbox
    # request: one main_health or lift_limits wrote after this tick's lanes ran waits for the next tick's
    if os.path.exists(TP.want_path(repo)) or ((requested or pending) and not os.path.exists(TP.red_path(repo))) \
            or HL.pending(repo) or J.requests(repo):
        out.append(TICK_SECS)
    if glob.glob(f"{J.handed_dir()}/{repo}-*.json"):   # its handed watches: only its own tick sweeps them
        out.append(TICK_SECS)
    if C.left_held(repo):   # a held last card edit (retry_cards): a tick once the cap or the 429's back-off lets it go
        # …but a running lane hands it over itself and retry_cards skips it, so one TICK_SECS tick looks again after,
        # not a tick every 2 s while it runs (Opus read of #1279)
        out.append(TICK_SECS if J.running(repo) else max(int(C.edit_wait(time.time())), 1))
    return out


def rearm(repos) -> list:
    sysrun = os.environ.get("LANDER_SYSTEMD_RUN") or "systemd-run"
    sysctl = os.environ.get("LANDER_SYSTEMCTL") or "systemctl"
    lander = os.path.join(J.CORE, "bin", "lander")
    lines = []
    for repo in repos:
        # A repo with no checkout arms nothing: a suite's fixture (_cctest<pid>) is deleted when its run ends, and its
        # timer kept re-arming for that gone repo about 77 times a day across two releases (10-02/03). This tick is
        # the last; the left-over state waits for a checkout that will not come back.
        if not os.path.isdir(J.repo_root(repo)):
            continue
        left = waits(repo)
        if not left:
            continue
        unit = unit_name(repo)
        # Active timers only (no --all): the one that fired this tick has elapsed and is not a wait.
        rc, out, _ = L.run([sysctl, "--user", "list-timers", "--no-legend", f"{unit}-*.timer"], timeout=30)
        secs = min(left) + 1
        at = int(time.time()) + secs
        if rc == 0 and armed(out, unit, at):
            continue
        # When it fires, in the name: this tick may be running inside the unit the last timer started, and
        # systemd-run refuses a name that is still loaded.
        rc, out, err = L.run([sysrun, "--user", f"--on-active={secs}", f"--unit={unit}-{at}", lander,
                              "tick", "--repo", repo, "--rearm"], timeout=30)
        lines.append(f"[{repo}] tick armed in {secs}s ({unit})" if rc == 0
                     else f"[{repo}] the tick timer would not arm: {GH.last(err or out)}")
    return lines


# --- the tip run and the deploy -------------------------------------------------------------------------------------

def known_repos(repo="") -> list:
    """Every repo this box tracks: a board names it, <repo>.applied says it was deployed, a job says it lands.
    Member projects never deploy, and neither does a member's own workspace board: ~/dev/<h> holds clones of several
    of the member's repos, so its main may follow none of them and its origin's main never fast-forward it (one such
    board failed every deploy for five days, 2026-10-18 to 10-23). Its projects land as <h>--<repo>, with no deploy."""
    if repo:
        return [repo] if "--" not in repo and not M.workspace(repo) else []
    names = {os.path.basename(x)[:-len(".json")] for x in glob.glob(os.path.join(J.boards(), "*.json"))}
    names |= {os.path.basename(x)[:-len(".applied")] for x in glob.glob(C.state("*.applied"))}
    names |= set(J.all_repos())
    return sorted(n for n in names if J.REPO_RE.fullmatch(n) and "--" not in n and not M.workspace(n))


def due_catchup(repo) -> bool:
    """True at most once every LANDER_CATCHUP_SECS per repo (a stamp on disk), so origin is not fetched every tick."""
    return due_every(C.state("tip", f"{repo}.catchup"), "LANDER_CATCHUP_SECS")


def due_every(f, key) -> bool:
    """True when the stamp file `f` is older than the config's `key` seconds (900), and touches it."""
    try:
        every = int(C.conf(key, "900") or 900)
    except ValueError:
        every = 900
    try:
        if time.time() - os.path.getmtime(f) < every:
            return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with contextlib.suppress(OSError):
        open(f, "w").close()
    return True


def tip_plan(root, base, head, files, fallback=""):
    """The tip run's plan: the box-class checks the merged range reaches, from the tip's own manifest (or the host
    fallback, manifest.host_fallback, for a repo that ships none). A tree with no manifest, or a broken one, reaches
    no box check; a manifest that cannot be read VERIFIED raises GitError, which ends the tip run, and the deploy
    with it, in tip_and_deploy. A gate-first change ran its box checks before the merge, on its own base; the
    tip runs them again, because the tip is what deploys."""
    from lander import manifest as MF
    from lander import plan as P
    m = MF.load(root, head, fallback=fallback, strict=False)
    p = P.select(m, list(files))
    box = set(p.extra.get("tip") or []) | {n for n in p.checks if n in m.checks and m.checks[n].klass == T.BOX}
    return T.Plan(checks=sorted(box), klass=p.klass, extra={"tip": sorted(box)})


def make_check(root, runner=None, fallback="", first=True):
    """-> check(name, sha) -> Result: the check as the manifest at `sha` defines it, run on that commit's tree on the
    box by U2's runner. A check that commit's manifest lacks passes there (a bisect reaching back before it was
    added). With `first` (the default: the tip run and main health) the runner gets first=True, so the check takes
    a FIRST CLAIM slot (admission); the nightly sweep is not main health and passes first=False."""
    from lander import manifest as MF
    from lander import run as R
    runner = runner or R.run
    seen = {}

    def check(name, sha):
        if sha not in seen:
            seen[sha] = MF.load(root, sha, fallback=fallback, strict=False)
        m = seen[sha]
        c = m.checks.get(name)
        if c is None:
            return T.Result(check=name, tree=sha, status=T.PASSED, extra={"why": f"not in the manifest at {sha[:12]}"})
        tree = R.tree_of(root, sha)
        if not tree:
            return T.Result(check=name, tree=sha, status=T.UNRUNNABLE, extra={"why": f"no tree for {sha[:12]}"})
        # brief, 10-13: "give main health's checks and a main-red fix's checks first claim on a free slot, ahead of
        # ordinary PR checks, so health can't starve"
        return runner(c, tree, "box" if "box" in c.where else c.where[0], repo_root=root, cwd=m.cwd.get(name, ""),
                      **({"first": True} if first else {}))
    return check


def covers(root, req_sha, sha) -> bool:
    """The request's sha is the job's merge or a descendant of it."""
    if not (req_sha and sha):
        return False
    return req_sha == sha or D.git(root, "merge-base", "--is-ancestor", sha, req_sha)[0] == 0


def settle(repo) -> list:
    """deploy-pending -> deployed -> done, once the deploy request covering the job's merge has finished."""
    pending = [j for j in J.lane_jobs(repo) if j.state in (T.DEPLOY_PENDING, T.DEPLOYED)]
    if not pending:
        return []
    req = C.read_json(D.req_path(repo)) or {}
    rc = D.outcome(req)
    reverted = C.read_json(C.state("tip", f"{repo}.reverted"), []) or []
    root, lines = D.root_of(repo), []
    with J.rest_lock(repo) as got:
        if not got:   # another tick is settling, or the lane is draining a request; the timer brings the next tick
            return []
        for job in pending:
            job = J.load(repo, job.pr)
            if job is None or job.state not in (T.DEPLOY_PENDING, T.DEPLOYED):
                continue
            sha = job.extra.get("tip_sha") or ""
            if sha and sha in reverted:
                J.move(job, T.DONE, why="the tip run proved this merge broke main, and it was reverted")
                E.log("done", repo, job.pr, rc=1)
                lines.append(f"[{repo}] PR #{job.pr}: reverted after a red tip — done")
                continue
            if rc is None or not covers(root, req.get("sha", ""), sha):
                continue
            said = ", ".join(f"{t} {(st or {}).get('state')}" for t, st in req["targets"].items())
            if job.state == T.DEPLOY_PENDING and rc != 1:
                J.move(job, T.DEPLOYED, sha=req["sha"][:12])
            J.move(job, T.DONE, why=f"deploy of {req['sha'][:12]}: {said}")
            E.log("done", repo, job.pr, rc=rc)
            lines.append(f"[{repo}] PR #{job.pr}: deploy {said} — done")
    return lines


def tip_and_deploy(repo, units) -> list:
    """The tip run, the deploy and the settling of jobs for one repo. Only the installed units (modules) run it; a
    lane test's recording fakes are left alone."""
    tip, deploy = units.get("tip"), units.get("deploy")
    if not (inspect.ismodule(tip) and inspect.ismodule(deploy)) or "--" in repo or L.paused(repo):
        return []
    lines, st, fb = [], "idle", ""
    try:
        fb = MF.host_fallback(repo)
        with TP.lock(repo) as got:
            if not got:
                return [f"[{repo}] a tip run is already going"]
            if due_catchup(repo) and tip.catchup(repo):
                lines.append(f"[{repo}] origin moved past what this box runs: a tip run is wanted")
            st = tip.run(repo, plan=lambda *a: tip_plan(*a, fallback=fb),
                         check=make_check(D.root_of(repo), fallback=fb))
            if st != "idle":
                lines.append(f"[{repo}] tip run: {st}")
            if st != "red":
                deploy.run(repo)
        lines += settle(repo)
    except Exception as e:  # noqa: BLE001 — one repo's fault is said and logged, never the tick's end
        E.log("tick-fault", repo, None, f"{type(e).__name__}: {e}")
        lines.append(f"[{repo}] the tip run or the deploy failed: {type(e).__name__}: {e}")
    return lines + main_health(repo, st in ("green", "red"), fb)


def main_health(repo, looked, fb) -> list:
    """Main's own record of its blocking checks (health.py), after the tip lock is let go and the jobs are settled.
    brief: "a merge's tip run and deploy never wait on main health": it holds its own lock, so the next tick's tip
    run starts while it runs. It runs on a tip the run just looked at (green or red), or when a pass is owed (one
    killed part-way, one stopped because main moved on, or one asked for while another held the lock). A job held
    main-red on a check the pass found green is asked again (who=main-health, whose hold jobs.drain makes due now):
    10-27, #1976 sat out its hold 2 h after main passed the check. Its fault is logged, never the tick's end."""
    try:
        if not (looked or HL.pending(repo)):
            return []
        with HL.lock(repo) as got:
            if not got:
                HL.want(repo)
                return [f"[{repo}] main health is already running"]
            ran = HL.run(repo, make_check(D.root_of(repo), fallback=fb), fallback=fb)
        if not ran:
            return []
        bad = sorted(n for n, said in ran.items() if said == T.FAILED)
        lines = [f"[{repo}] main health: {len(ran)} check(s)" + (f", red: {', '.join(bad)}" if bad else "")]
        for j in J.lane_jobs(repo):
            n = (j.extra.get("main_red") or {}).get("check") if j.state == T.HELD else None
            if ran.get(n) == T.PASSED:
                J.submit(repo, j.pr, who="main-health")
                lines.append(f"[{repo}] PR #{j.pr}: main passes {n} again, so its main-red hold is tried now")
        return lines
    except Exception as e:  # noqa: BLE001 — main health is a record, never the deploy's settling
        E.log("tick-fault", repo, None, f"main health: {type(e).__name__}: {e}")
        return [f"[{repo}] main health failed: {type(e).__name__}: {e}"]


def nightly(repo, units) -> list:
    """Once a day per repo, the never-red checks' sweep (nightly.py), started detached. As tip_and_deploy: only the
    installed units run it, members and paused repos are skipped, and a fault is logged as tick-fault, never the
    tick's end. The day is stamped only once the sweep has started, so a failed start tries again next tick."""
    if not (inspect.ismodule(units.get("tip")) and inspect.ismodule(units.get("deploy"))) or "--" in repo:
        return []
    try:
        if not NG.due(repo) or L.paused(repo):
            return []
        started, line = NG.spawn(repo)
        if started:
            NG.mark(repo)
        return [line]
    except Exception as e:  # noqa: BLE001 — as tip_and_deploy: one repo's fault is said and logged
        E.log("tick-fault", repo, None, f"nightly: {type(e).__name__}: {e}")
        return [f"[{repo}] the nightly sweep failed: {type(e).__name__}: {e}"]


def flag_waited(repos, cards, now=None) -> list:
    """Brief: "have the lander's tick flag once when the oldest due job has waited over 60 min". For each repo, the
    due job (Lane.due: not at rest, no hold still running) with the oldest queued_at; queued more than
    cards.WAIT_FLAG_SECS ago (queued_at is to the second, so seconds are compared, and exactly 60 min is not over)
    -> cards.waited, which says it once per queuing and at most once per repo per WAIT_FLAG_SECS. A job with no
    queued_at has no age and is never flagged.
    Nothing is flagged while the box itself holds the queue: a GitHub backoff (every repo), or the oldest due job held
    by L.box_hold (its repo or member paused, a spend tier stop) or in a lane "box" hold (the day review cap, a usage
    wall) whose time is up but which the lane has not let go yet, since the lane is not late then (perms' read, 10-13:
    a held repo sent a false "Nothing stopped it" each tick). Each such hold is noted (cards.held), and the age counts
    from the latest of queued_at, the job's unheld_at (Lane.unhold stamps it when a box hold ends) and the last tick
    that found a hold, so a queue a hold just let go is not late at once (perms' read, 10-13). `cards` is the installed cards unit (L.load_units); with none, nothing is flagged."""
    lines, t = [], int(now if now is not None else time.time())
    if GH.backoff():
        for r in (repos if cards else []):
            try:
                if J.lane_jobs(r):
                    cards.held(r, t)
            except Exception as e:  # noqa: BLE001 — as below
                E.log("tick-fault", r, None, f"waited: {type(e).__name__}: {e}")
        return lines
    for r in (repos if cards else []):
        try:
            aged = [(E.epoch_of(j.extra.get("queued_at") or ""), j) for j in J.lane_jobs(r) if L.Lane.due(j, t)]
            aged = [(at, j) for at, j in aged if at]
            if not aged:
                continue
            at, job = min(aged, key=lambda x: x[0])
            h, tr = M.member_of(r)
            # a box hold still running is skipped; one whose time is up is due but HELD until the lane's unhold(), so
            # its age counts from the hold's end (not_before) — a dead lane that never unholds it is still flagged
            if L.box_hold(h if h and tr else r, job):
                cards.held(r, t)
                continue
            since = max(at, E.epoch_of(job.extra.get("unheld_at") or "") or 0, int(cards.held_at(r) or 0),
                        E.epoch_of(job.extra.get("not_before") or "") or 0)
            if t - since <= C.WAIT_FLAG_SECS:
                continue
            if cards.waited(job, t - at, now=t):
                seat = f"{r}'s own seat" if cards.own_seat(job, "planning") else "the planning seat"
                lines.append(f"[{r}] PR #{job.pr} has waited {(t - at) // 60} min in the queue; {seat} is told")
        except Exception as e:  # noqa: BLE001 — as tip_and_deploy: one repo's fault is said and logged
            E.log("tick-fault", r, None, f"waited: {type(e).__name__}: {e}")
    return lines


def flag_main_red(repos, cards, now=None) -> list:
    """Brief: "A main-red check that has held anything for more than an hour produces ONE alert line naming the check
    and its failing IDs". For each repo, each job whose extra.main_red names a check with a since= more than
    cards.WAIT_FLAG_SECS ago (seconds against seconds; exactly an hour is not more) -> cards.main_red, which says it
    at most once an hour per repo and check, whichever PR it names; the oldest such job per check is the one asked.
    A hold whose check main's own record (health) passed at or after its since= is skipped: a held job keeps
    extra.main_red until its own run of the check, so without this main going green left the hold aging into an
    alert (10-19: "red on main for 203 min" sent 21 min after main-health logged it passed on the tip).
    `cards` is the installed cards unit; with none, or in a GitHub backoff, nothing is flagged."""
    lines, t = [], int(now if now is not None else time.time())
    for r in (repos if cards and not GH.backoff() else []):
        try:
            oldest = {}
            try:
                rec = HL.load(r)["checks"]
            except (TypeError, ValueError, AttributeError):  # a wrong-shape health file reads as no record
                rec = {}
            for j in J.lane_jobs(r):
                mr = j.extra.get("main_red")
                at = E.epoch_of(mr.get("since") or "") if isinstance(mr, dict) else 0
                main = rec.get(mr.get("check")) if at else None
                if isinstance(main, dict) and main.get("status") == T.PASSED and E.epoch_of(main.get("at")) >= at:
                    continue
                if at and t - at > C.WAIT_FLAG_SECS and (mr.get("check") not in oldest
                                                         or at < oldest[mr.get("check")][0]):
                    oldest[mr.get("check")] = (at, j)
            for n, (at, j) in sorted(oldest.items()):
                if cards.main_red(j, t - at, now=t):
                    lines.append(f"[{r}] check {n} has been red on main for {(t - at) // 60} min; "
                                 f"the planning seat is told")
        except Exception as e:  # noqa: BLE001 — as flag_waited: one repo's fault is logged, never the tick's end
            E.log("tick-fault", r, None, f"main-red: {type(e).__name__}: {e}")
    return lines


STALL_HISTORY = 100  # a lane's last this many gaps between moves are its recent history
STALL_GAPS = 20      # a lane with fewer is judged on the box's
STALL_TIMES = 3      # a gap this many times its history's p90 is a stall
STALL_PASS = 60      # moves this close to the one before are one pass of the lane, so no gap between them
STALL_TAIL = 8 << 20   # bytes of queue.log's end read for that history
STALL_MOVES = ("verdict", "held", "handback", "query", "merged")   # a job moving on, not one coming in


def stage_times() -> dict:
    """{repo: [(epoch, name) of each `stage` line, oldest first]} from queue.log's last STALL_TAIL bytes."""
    try:
        with open(E.log_path(), "rb") as f:
            f.seek(max(0, os.fstat(f.fileno()).st_size - STALL_TAIL))
            text = f.read().decode(errors="replace")
    except OSError:
        return {}
    out = {}
    for at, r, name in re.findall(r"^(\S+)\tstage ([\w.-]+)#\S+ ([\w-]+)", text, re.M):
        out.setdefault(r, []).append((E.epoch_of(at), name))
    return out


def move_gaps(lines) -> tuple:
    """(gaps, last): the gaps between a lane's passes that moved a job on (STALL_MOVES, each within STALL_PASS of
    the one before is one pass), each counted from the first line after the pass before, so a spell with nothing
    in the lane is not history; and the epoch of its last such pass, or 0."""
    gaps, last, start = [], 0, 0
    for a, name in lines:
        if name not in STALL_MOVES:
            start = start or a
        elif not last or a - last > STALL_PASS:
            if last:
                gaps.append(a - max(last, start))
            last, start = a, 0
        else:
            last = a
    return gaps, last


def flag_stalled(repos, cards, now=None) -> list:
    """A LANE WHOSE QUEUE HAS STOPPED MOVING (owner, 10-22: "should have been caught automatically", after 18 Hive PRs
    sat at review about 65 min while a hung read held the lane's one slot). For each repo with a due job (Lane.due),
    the time since it last moved a job on (move_gaps: a verdict, hold, handback, query or merge; new PRs kept coming
    in through that stall, so intake is not movement) against its own last STALL_HISTORY gaps between moves, or the
    box's when it has fewer than STALL_GAPS (a young lane): over STALL_TIMES times their p90 -> cards.stalled, said
    once per stall and at most hourly per repo. Quiet counts from the latest of that move and when its oldest due job
    became due (as flag_waited's age: queued, let go by a hold, or a box hold the tick last saw, so the moment a
    usage wall lifts is not a stall). A lane that never moved a job, or whose oldest due job the box holds
    (L.box_hold, as flag_waited), is not judged. `cards` is the installed cards unit; with none, or in a GitHub
    backoff, nothing is flagged."""
    lines, t = [], int(now if now is not None else time.time())
    times = stage_times() if cards and repos and not GH.backoff() else {}
    moves = {r: move_gaps(v) for r, v in times.items()}
    box = [g for gaps, _ in moves.values() for g in gaps]
    for r in repos if times else []:
        try:
            gaps, last = moves.get(r, ([], 0))
            gaps = gaps[-STALL_HISTORY:] if len(gaps) >= STALL_GAPS else box
            due = [j for j in J.lane_jobs(r) if L.Lane.due(j, t)]
            if len(gaps) < STALL_GAPS or not last or not due:
                continue
            job = min(due, key=lambda j: j.extra.get("queued_at") or "")
            since = max([last, int(cards.held_at(r) or 0)] + [E.epoch_of(job.extra.get(k) or "") or 0
                                                             for k in ("queued_at", "unheld_at", "not_before")])
            usual, idle = E.pctl(gaps, 90), t - since
            if idle <= STALL_TIMES * usual:
                continue
            h, tr = M.member_of(r)
            if L.box_hold(h if h and tr else r, job):   # paused or a tier stop: the box holds it, the lane is not late
                continue
            if cards.stalled(job, idle, usual, E.stamp(since), now=t):
                lines.append(f"[{r}] the queue has not moved for {idle // 60} min; its seat is told")
        except Exception as e:  # noqa: BLE001 — as flag_waited: one repo's fault is logged, never the tick's end
            E.log("tick-fault", r, None, f"stalled: {type(e).__name__}: {e}")
    return lines


def carded_repos(repo="") -> list:
    """Each repo with a queued-card record (cards/queued-<repo>.json), or just `repo`: one whose queue emptied may have
    no job, board or .applied left to name it, and still wait on a held last edit."""
    if repo:
        return [repo]
    names = [os.path.basename(p)[len("queued-"):-len(".json")] for p in glob.glob(C.state("cards", "queued-*.json"))]
    return sorted(n for n in names if J.REPO_RE.fullmatch(n))


def retry_cards(repos, cards) -> None:
    """A queued card's last edit that the cap or a 429 held goes again (cards.left_held): its lane may have ended with
    it held, and an empty queue starts no lane to hand it over (Opus read of #1275). A repo whose lane runs is left to
    the lane. `cards` is the installed cards unit; with none, nothing is retried. Nothing is said: the card is the
    message, and queue.log has the edit's own `unsaid` line when it is held again."""
    for r in (repos if cards else []):
        try:
            if cards.left_held(r) and not J.running(r):
                cards.positions(r, J.lane_jobs(r))
        except Exception as e:  # noqa: BLE001 — as flag_waited: one repo's fault is logged, never the tick's end
            E.log("tick-fault", r, None, f"cards: {type(e).__name__}: {e}")


def spawn_lane(repo):
    argv = [sys.executable, "-P", os.path.join(J.CORE, "lander", "cli.py"), "lane", repo]
    try:
        p = subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        return f"[{repo}] lane started (pid {p.pid})"
    except OSError as e:
        return f"[{repo}] the lane would not start: {e}"


def cmd_tick(argv) -> int:
    pos, opts = L.split_opts(argv, "--repo")
    detach = "--detach" in pos   # --rearm: every tick re-arms now; the flag stays for the timers armed with it
    extra = [a for a in pos if a not in ("--detach", "--rearm")]
    repo = opts.get("--repo", "")
    if extra or (repo and not J.REPO_RE.fullmatch(repo)):
        return L.refuse("usage: lander tick [--repo R] [--detach] [--rearm]")
    lines = []
    wait = GH.backoff()
    repos = [repo] if repo else J.all_repos()
    if wait:
        lines.append(f"lander: GitHub backoff — {wait}s left; lanes and handed watches wait for it")
    else:
        lines += sweep_handed(repo)
        GH.prune_kept()
        lines += sweep_repairs()
        lines += sweep_strays(known_repos(repo))
        lines += sweep_ended(repo)
        lines += sweep_landed(repo)
        lines += lift_limits(repo)
        repos = [repo] if repo else J.all_repos()   # a push or a stray may have queued a new repo
        for r in repos:
            if J.running(r):
                continue
            lines += [spawn_lane(r)] if detach else L.Lane(r).run()
        lines += retry_deploys(repos)
    units, known = L.load_units(), known_repos(repo)
    lines += flag_waited(repos, units.get("cards"))
    lines += flag_main_red(repos, units.get("cards"))
    lines += flag_stalled(repos, units.get("cards"))
    retry_cards(list(dict.fromkeys(repos + known + carded_repos(repo))), units.get("cards"))
    for r in known:
        lines += tip_and_deploy(r, units)
        lines += nightly(r, units)
    # any tick arms a repo with handed watches, so one whose own timer had lapsed is swept again
    handed = [(J.read_json(p) or {}).get("repo") or "" for p in glob.glob(f"{J.handed_dir()}/*.json")]
    handed = [r for r in handed if J.REPO_RE.fullmatch(r)]
    lines += rearm(list(dict.fromkeys(repos + known + carded_repos(repo) + handed)))
    for ln in lines:
        print(ln)
    return 0


COMMANDS = {"tick": (cmd_tick, "resume lanes, poll handed PRs, run the tip and deploy it: [--repo R] [--detach] "
                               "[--rearm]"),
            "settle-merged": (cmd_settle_merged, "move <repo> <pr>'s query or held job to merged (or done) once GitHub "
                                                 "says it merged (or closed, or open on a head its repo lands itself) "
                                                 "[--by WHO]")}
