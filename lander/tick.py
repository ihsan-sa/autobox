"""lander tick [--repo R] [--detach] [--rearm] — what wakes the lander (review B3). Idempotent; run it any time.

  lanes     each repo with a job or an inbox request (or just R) whose lane is not running: run it here, or with
            --detach start `lander lane <repo>` detached. A lane already running re-reads the queue itself.
  handed    each handed-back watch (handed/<repo>-<pr>.json): past `until` -> removed, `handed-end`; the PR merged
            or closed -> removed, `handed-end`; the branch head moved (ls-remote, under the member's token for a
            member) -> the reads it used go to carry/ and a request (chat/ts/who only) to the inbox, `handed-pushed`,
            removed. The prior verdict is not carried: the reviewer finds it among the box's own PR markers.
            A job for the PR already on the queue ends the watch.
  deploy    for each repo with a deploy-pending job, under its rest lock (jobs.rest_lock): tip.kick(repo) and a
            deploy.request not yet made — only when those units are installed.
  tip       for each repo the box knows (boards, <repo>.applied, jobs; members and paused repos skipped), under the
            repo's tip lock (a second tick skips it, never waits): tip.catchup at most every $LANDER_CATCHUP_SECS
            (900) per repo — origin's main past <repo>.applied kicks a tip run, a first sight seeds .applied; then
            tip.run, whose checks are the box-class checks the merged range reaches (tip_plan), each run on its
            commit by U2's runner (make_check). Green deploys that sha (deploy.run); red holds the targets, bisects
            and reverts a proven breaker. Then deploy.run again, for a request whose tip is already green (a retry).
  settle    each deploy-pending job, under the rest lock (not the lane lock: a busy lane holds that from one job to
            the next, and the lane never takes up a job it rested), once the request covering its tip_sha (that sha
            or a later one) has no target waiting: -> deployed -> done, and `done` rc 0 (verified), 4 (UNVERIFIED) or 1
            (failed). A job whose merge the tip run reverted -> done rc 1.
  backoff   while the GitHub backoff runs (gh.py) no gh work is done: said once, lanes and watches wait.
  rearm     every tick (--rearm is accepted and adds nothing): ONE transient timer per repo that still waits on
            something — a job held with a not_before, a wanted tip run, a requested deploy, or a deploy-pending job
            while the tip is not red. `systemd-run --user --on-active=<secs> --unit=lander-tick-<repo>-<epoch>
            <core/bin/lander> tick --repo <repo> --rearm`, skipped when the user manager's list-timers shows an
            active lander-tick-<repo>-* timer. No unit files are written, and nothing depends on a caller ticking.
            $LANDER_SYSTEMD_RUN and $LANDER_SYSTEMCTL replace the two binaries (the tests' fakes).
"""
from __future__ import annotations

import contextlib
import glob
import inspect
import os
import re
import subprocess
import sys
import time

from lander import cards as C
from lander import deploy as D
from lander import events as E
from lander import gh as GH
from lander import git as G
from lander import jobs as J
from lander import lane as L
from lander import manifest as MF
from lander import members as M
from lander import tip as TP
from lander import types as T

TICK_SECS = 120   # how soon a wanted tip run, a requested deploy or an unsettled job is looked at again


def sweep_handed() -> list:
    lines = []
    for p in sorted(glob.glob(f"{J.handed_dir()}/*.json")):
        w = J.read_json(p) or {}
        repo, pr = w.get("repo") or "", w.get("pr")
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
        genv = M.env(h) if h else None
        root = J.repo_root(repo)
        facts = GH.pr_facts(root, pr, "headRefOid,state", (genv or {}).get("GH_TOKEN"))[0] or {}
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


def armed(out, unit) -> bool:
    """Whether list-timers names an active timer of this repo's: `<unit>-<epoch>.timer`."""
    return re.search(rf"(?:^|\s){re.escape(unit)}-\d+\.timer(?:\s|$)", out, re.M) is not None


def waits(repo) -> list:
    """Seconds until each thing the repo still waits on wants a tick; [] when nothing does. A tip that is red waits
    on a person (or the next merge, whose lane kicks the tip itself), not on a clock."""
    jobs = J.lane_jobs(repo)
    out = [J.not_before_left(j) for j in jobs if j.state == T.HELD and j.extra.get("not_before")]
    out = [w for w in out if w > 0]
    req = C.read_json(D.req_path(repo)) or {}
    requested = any((st or {}).get("state") == "requested" for st in (req.get("targets") or {}).values())
    pending = any(j.state in (T.DEPLOY_PENDING, T.DEPLOYED) for j in jobs)
    if os.path.exists(TP.want_path(repo)) or ((requested or pending) and not os.path.exists(TP.red_path(repo))):
        out.append(TICK_SECS)
    return out


def rearm(repos) -> list:
    sysrun = os.environ.get("LANDER_SYSTEMD_RUN") or "systemd-run"
    sysctl = os.environ.get("LANDER_SYSTEMCTL") or "systemctl"
    lander = os.path.join(J.CORE, "bin", "lander")
    lines = []
    for repo in repos:
        left = waits(repo)
        if not left:
            continue
        unit = unit_name(repo)
        # Active timers only (no --all): the one that fired this tick has elapsed and is not a wait.
        rc, out, _ = L.run([sysctl, "--user", "list-timers", "--no-legend", f"{unit}-*.timer"], timeout=30)
        if rc == 0 and armed(out, unit):
            continue
        secs = min(left) + 1
        # A stamp in the name: this tick may be running inside the unit the last timer started, and systemd-run
        # refuses a name that is still loaded.
        rc, out, err = L.run([sysrun, "--user", f"--on-active={secs}", f"--unit={unit}-{int(time.time())}", lander,
                              "tick", "--repo", repo, "--rearm"], timeout=30)
        lines.append(f"[{repo}] tick armed in {secs}s ({unit})" if rc == 0
                     else f"[{repo}] the tick timer would not arm: {GH.last(err or out)}")
    return lines


# --- the tip run and the deploy -------------------------------------------------------------------------------------

def known_repos(repo="") -> list:
    """Every repo this box tracks: a board names it, <repo>.applied says it was deployed, a job says it lands.
    Member projects never deploy."""
    if repo:
        return [repo] if "--" not in repo else []
    names = {os.path.basename(x)[:-len(".json")] for x in glob.glob(os.path.join(J.boards(), "*.json"))}
    names |= {os.path.basename(x)[:-len(".applied")] for x in glob.glob(C.state("*.applied"))}
    names |= set(J.all_repos())
    return sorted(n for n in names if J.REPO_RE.fullmatch(n) and "--" not in n)


def due_catchup(repo) -> bool:
    """True at most once every LANDER_CATCHUP_SECS per repo (a stamp on disk), so origin is not fetched every tick."""
    f = C.state("tip", f"{repo}.catchup")
    try:
        every = int(C.conf("LANDER_CATCHUP_SECS", "900") or 900)
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
    fallback, manifest.host_fallback, for a repo that ships none). It never raises: a tree with no manifest, or a
    broken one, reaches no box check. A gate-first change ran its box checks before the merge, on its own base; the
    tip runs them again, because the tip is what deploys."""
    from lander import manifest as MF
    from lander import plan as P
    m = MF.load(root, head, fallback=fallback, strict=False)
    p = P.select(m, list(files))
    box = set(p.extra.get("tip") or []) | {n for n in p.checks if n in m.checks and m.checks[n].klass == T.BOX}
    return T.Plan(checks=sorted(box), klass=p.klass, extra={"tip": sorted(box)})


def make_check(root, runner=None, fallback=""):
    """-> check(name, sha) -> Result: the check as the manifest at `sha` defines it, run on that commit's tree on the
    box by U2's runner. A check that commit's manifest lacks passes there (a bisect reaching back before it was
    added)."""
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
        return runner(c, tree, "box" if "box" in c.where else c.where[0], repo_root=root, cwd=m.cwd.get(name, ""))
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
    lines = []
    try:
        with TP.lock(repo) as got:
            if not got:
                return [f"[{repo}] a tip run is already going"]
            if due_catchup(repo) and tip.catchup(repo):
                lines.append(f"[{repo}] origin moved past what this box runs: a tip run is wanted")
            fb = MF.host_fallback(repo)
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
    return lines


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
        lines += sweep_handed()
        repos = [repo] if repo else J.all_repos()   # a push may have queued a new repo
        for r in repos:
            if J.running(r):
                continue
            lines += [spawn_lane(r)] if detach else L.Lane(r).run()
        lines += retry_deploys(repos)
    units, known = L.load_units(), known_repos(repo)
    for r in known:
        lines += tip_and_deploy(r, units)
    lines += rearm(list(dict.fromkeys(repos + known)))
    for ln in lines:
        print(ln)
    return 0


COMMANDS = {"tick": (cmd_tick, "resume lanes, poll handed PRs, run the tip and deploy it: [--repo R] [--detach] "
                               "[--rearm]")}
