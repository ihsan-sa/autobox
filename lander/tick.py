"""lander tick [--repo R] [--detach] [--rearm] — what wakes the lander (review B3). Idempotent; run it any time.

  lanes     each repo with a job or an inbox request (or just R) whose lane is not running: run it here, or with
            --detach start `lander lane <repo>` detached. A lane already running re-reads the queue itself.
  handed    each handed-back watch (handed/<repo>-<pr>.json): past `until` -> removed, `handed-end`; the PR merged
            or closed -> removed, `handed-end`; the branch head moved (ls-remote, under the member's token for a
            member) -> a request carrying reads_used and the verdict goes to the inbox, `handed-pushed`, removed.
            A job for the PR already on the queue ends the watch.
  deploy    for each repo with a deploy-pending job, under its lane lock: tip.kick(repo) and a deploy.request not
            yet made — only when those units are installed.
  backoff   while the GitHub backoff runs (gh.py) no gh work is done: said once, lanes and watches wait.
  --rearm   when any job is held with a not_before, ONE transient timer per repo:
            `systemd-run --user --on-active=<secs> --unit=lander-tick-<repo>-<epoch> <core/bin/lander> tick --repo
            <repo> --rearm`, skipped when `systemctl --user list-timers` lists an active lander-tick-<repo>-* timer. No unit files are
            written. $LANDER_SYSTEMD_RUN and $LANDER_SYSTEMCTL replace the two binaries (the tests' fakes).
"""
from __future__ import annotations

import contextlib
import glob
import os
import re
import subprocess
import sys
import time

from lander import events as E
from lander import gh as GH
from lander import git as G
from lander import jobs as J
from lander import lane as L
from lander import members as M
from lander import types as T


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
            J.submit(repo, pr, who="handback push", chat=w.get("chat"), ts=w.get("ts"),
                     reads_used=int(w.get("reads_used") or 0), verdict=w.get("verdict") or None)
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
        with J.lane_lock(repo) as got:
            if not got:
                continue
            if tip:
                with contextlib.suppress(Exception):
                    tip.kick(repo)
            for job in pending if deploy else []:
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


def rearm(repos) -> list:
    sysrun = os.environ.get("LANDER_SYSTEMD_RUN") or "systemd-run"
    sysctl = os.environ.get("LANDER_SYSTEMCTL") or "systemctl"
    lander = os.path.join(J.CORE, "bin", "lander")
    lines = []
    for repo in repos:
        waits = [J.not_before_left(j) for j in J.lane_jobs(repo) if j.state == T.HELD and j.extra.get("not_before")]
        waits = [w for w in waits if w > 0]
        if not waits:
            continue
        unit = unit_name(repo)
        # Active timers only (no --all): the one that fired this tick has elapsed and is not a wait.
        rc, out, _ = L.run([sysctl, "--user", "list-timers", "--no-legend", f"{unit}-*.timer"], timeout=30)
        if rc == 0 and armed(out, unit):
            continue
        secs = min(waits) + 1
        # A stamp in the name: this tick may be running inside the unit the last timer started, and systemd-run
        # refuses a name that is still loaded.
        rc, out, err = L.run([sysrun, "--user", f"--on-active={secs}", f"--unit={unit}-{int(time.time())}", lander,
                              "tick", "--repo", repo, "--rearm"], timeout=30)
        lines.append(f"[{repo}] tick armed in {secs}s ({unit})" if rc == 0
                     else f"[{repo}] the tick timer would not arm: {GH.last(err or out)}")
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
    detach, re_arm = "--detach" in pos, "--rearm" in pos
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
    if re_arm:
        lines += rearm(repos)
    for ln in lines:
        print(ln)
    return 0


COMMANDS = {"tick": (cmd_tick, "resume lanes, poll handed PRs, retry deploys: [--repo R] [--detach] [--rearm]")}
