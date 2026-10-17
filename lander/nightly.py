"""Checks that never go red on a PR run nightly instead (owner, 10-12: "speed things up … just send it for max
performance"; 78 checks that were never red cost 102 of 231 gate-hours a week).

    lander nightly --repo R [--days N]     the checks that run nightly now, and the gate-hours per PR over the last
                                           N days (7) with and without them in the per-PR plan
    lander nightly run --repo R            run them once on R's applied tip (main as the box runs it); a red files
                                           one board row naming the check and puts it back in the per-PR plan

THE RECORD is queue.log, read at run time: a new manifest key or file would be refused by the live release until a
promote. Over the last WINDOW_DAYS a check's PR-CAUSED RED is a `stage <repo>#<pr> gate gate=<c> ok=no` line whose
PR's next line, other than another gate line, is its handback (`stage … handback` or `handed`). A red that main
shared is logged ok=main-red, and an ok=no the PR was held for (it could not run) is followed by a hold: neither
counts. A NIGHTLY RED is a `nightly <repo> check=<c> ok=<not yes>` line, which `run` writes: a check
that could not run on the tip counts as red, since nothing showed it still passes.

A CHECK MOVES (moved()) when all of these hold: the log goes back WINDOW_DAYS (a younger log proves nothing), the
check ran at least MIN_RUNS times in that window (one green run proves little), it had no PR-caused red and no nightly red there, and it is not GUARDED. A
guarded check stays per PR whatever its record (brief: "Keep per-PR anything that guards a gate, a sandbox, the
guard, secrets or member isolation"): the built-in manifest-widen, a box check (it runs at the tip already), a name
with one of GUARD_WORDS, and a check that owns, covers or runs a GUARDED PATH. Those are the policy's gate_first,
lander and protected lists (bar the bare tests/** globs, which hold every check's own script), GUARD_PATHS (the
guards perms named in its security read of #1190, which no policy list carries), and every tool the managed settings
register as a hook (core/config/claude-managed.json and claude-settings.json, read from this release). When those
settings can't be read, every check is guarded.

trim() takes the moved checks out of a planned PR's checks, for the lane only: a lander, gate-first or protected
change and a member's lane keep every check, and a worker's own `lander check` keeps the whole plan. `lander tick`
starts `nightly run` detached once every NIGHTLY_SECS per repo, once the log goes back far enough to move anything:
due() says when, and mark() stamps the day only after spawn() has started the sweep, so a failed start tries again
at the next tick.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

from lander import events as E
from lander import manifest as M
from lander import types as T

WINDOW_DAYS = 30
MIN_RUNS = 10
NIGHTLY_SECS = 86400
GUARD_WORDS = ("gate", "guard", "sandbox", "ccbox", "bwrap", "secret", "token", "trust", "member", "isolat",
               "lander", "land", "green", "perms", "deny", "fence", "scope", "settings", "config", "egress",
               "identity")
BROAD = ("tests/**", "core/tests/**")
GUARD_PATHS = ("dashboard/auth.py",              # Cloudflare Access on the dashboard
               "core/bin/cc-slack",              # owner / member routing
               "core/bin/cc-broker", "core/bin/cc-msg", "core/bin/cc-mail", "core/bin/cc-publish",
               "core/bin/cc-loop", "core/bin/cc-sandbox",   # the worker sandbox launch
               "core/bin/gh",                    # the org-fence shim
               "core/bin/cc-refusals", "bin-private/*cloudflare*", "core/bin/cc-tmp-reap",
               "bin-private/*library-public*",   # the library's public links
               "core/bin/cc-gh-org",             # the member org fence
               "core/slack/**", "core/mail/**")  # the Slack app and inbound/outbound mail
HOOK_SETTINGS = ("config/claude-managed.json", "config/claude-settings.json")
LINE_RE = re.compile(r"^(\S+)\t(\S+) ([\w.-]+)(?:#(\d+))?(?: (.*))?$")
KV_RE = re.compile(r"(\w+)=(\S*)")
_cache: dict = {}


def scan(lines, repo: str, now: float, days: int = 7) -> dict:
    """{"first", "runs", "pr_reds", "nightly_reds", "secs", "prs"} for `repo` from queue.log lines: runs, pr_reds
    and nightly_reds count the last WINDOW_DAYS; secs ({check: seconds}) and prs (a set) the last `days`."""
    since, recent = now - WINDOW_DAYS * 86400, now - days * 86400
    rec = {"first": 0, "runs": {}, "pr_reds": {}, "nightly_reds": {}, "secs": {}, "prs": set()}
    pending = {}
    for ln in lines:
        m = LINE_RE.match(ln.rstrip("\n"))
        if not m:
            continue
        at = E.epoch_of(m.group(1))
        if not at:
            continue
        rec["first"] = rec["first"] or at   # the log's own first line, whatever repo it names
        kind, r, pr, rest = m.group(2), m.group(3), m.group(4), m.group(5) or ""
        if r != repo or at < since:
            continue
        kv = dict(KV_RE.findall(rest))
        if kind == "nightly" and pr is None:
            if kv.get("ok") != "yes" and kv.get("check"):   # task: "An unrunnable nightly result counts as red"
                rec["nightly_reds"][kv["check"]] = at
            continue
        if pr is None:
            continue
        word = rest.split(" ", 1)[0]
        if kind == "stage" and word == "gate":
            kv = dict(KV_RE.findall(rest.split(" note=", 1)[0]))   # as events.GATE_RE: a note's text is free
        if kind == "stage" and word == "gate" and kv.get("gate"):
            g = kv["gate"]
            rec["runs"][g] = rec["runs"].get(g, 0) + 1
            if at >= recent:
                secs = kv.get("secs") or ""
                rec["secs"][g] = rec["secs"].get(g, 0) + (int(secs) if secs.isdigit() else 0)
                rec["prs"].add(pr)
            if kv.get("ok") == "no":
                pending.setdefault(pr, []).append(g)
            continue
        if pr in pending:
            gone = pending.pop(pr)
            if kind == "handed" or (kind == "stage" and word == T.HANDBACK):
                for g in gone:
                    rec["pr_reds"][g] = rec["pr_reds"].get(g, 0) + 1
    return rec


def record(repo: str, now: float | None = None, days: int = 7) -> dict:
    """scan() of the live queue.log, read again at most once an hour per repo; {} when there is no log."""
    now = now or time.time()
    p = E.log_path()
    key = (p, repo, days, int(now // 3600))
    if key not in _cache:
        try:
            with open(p, errors="replace") as f:
                _cache.clear()
                _cache[key] = scan(f, repo, now, days)
        except OSError:
            return {}
    return _cache[key]


def _probe(glob: str) -> str:
    return glob.replace("**", "x").replace("*", "x")


def hook_paths(core: str | None = None):
    """core/bin/<tool> for every hook the managed settings register, sorted; None when a settings file can't be
    read."""
    import json
    from lander import jobs as J
    core, out = core or J.CORE, set()
    for rel in HOOK_SETTINGS:
        try:
            with open(os.path.join(core, rel)) as f:
                hooks = json.load(f).get("hooks") or {}
            if isinstance(hooks, dict):   # claude-settings.json: {event: [{"hooks": [{"command"}]}]}
                hooks = [h for es in hooks.values() for e in es for h in e.get("hooks", [])]
            words = [(h.get("command") or "").split(" ", 1)[0] for h in hooks]
        except (OSError, ValueError, AttributeError, TypeError):
            return None
        out.update("core/bin/" + w[len("$HOME/bin/"):] for w in words if w.startswith("$HOME/bin/"))
    return sorted(out)


def guarded(m: M.Manifest, name: str, hooks=False) -> bool:
    """`hooks` is hook_paths()'s answer, read here when not given."""
    if name == M.BUILTIN or any(w in name for w in GUARD_WORDS):
        return True
    c = m.checks.get(name)
    if c is None or c.klass == T.BOX:
        return True
    hooks = hook_paths() if hooks is False else hooks
    if hooks is None:
        return True   # the hook list can't be read, so no check is known not to guard a hook
    pol = m.policy
    pats = [p for p in list(pol.gate_first) + list(pol.lander) + list(pol.protected) if p not in BROAD]
    pats += list(GUARD_PATHS) + hooks
    own = list(c.paths) + [m.cwd.get(name, "") + M.run_file(c.run)]
    return any(M.match(pats, _probe(p)) for p in own if p) or any(m.owns(name, _probe(p)) for p in pats)


def moved(repo: str, m: M.Manifest, rec: dict | None = None, now: float | None = None) -> list:
    """The checks of `m` that run nightly instead of per PR (the module's rule), sorted."""
    now = now or time.time()
    rec = record(repo, now) if rec is None else rec
    # brief: "A check with no red caused by a PR in 30 days, where a red that was also red on main doesn't count,
    # moves out of the per-PR plan"; "A nightly red … reopens it to per-PR for 30 days"
    if not rec or not rec["first"] or rec["first"] > now - WINDOW_DAYS * 86400:
        return []   # the log does not go back far enough to say a check was never red
    hooks = hook_paths()
    return sorted(n for n in m.checks
                  if rec["runs"].get(n, 0) >= MIN_RUNS and not rec["pr_reds"].get(n) and n not in rec["nightly_reds"]
                  and not guarded(m, n, hooks))


def trim(repo: str, m: M.Manifest, plan: T.Plan, rec: dict | None = None) -> T.Plan:
    """`plan` without the moved checks (Plan.extra["nightly"] names them); a lander, gate-first or protected plan is
    kept whole. Any fault keeps the plan whole: running a check is never the wrong answer."""
    if plan is None or plan.klass not in (T.LEAF, T.WIDE, T.DOCS):
        return plan
    try:
        out = set(moved(repo, m, rec)) & set(plan.checks)
    except Exception:  # noqa: BLE001 — a log or manifest fault runs everything
        return plan
    if out:
        plan.checks = [n for n in plan.checks if n not in out]
        plan.extra["nightly"] = sorted(out)
    return plan


def _stamp(repo: str) -> str:
    from lander import cards as C
    return C.state("nightly", f"{repo}.stamp")


def due(repo: str) -> bool:
    """True when no sweep started in the last NIGHTLY_SECS for this repo, the log goes back WINDOW_DAYS and some check
    ran MIN_RUNS times (as moved() needs). It writes nothing: mark() stamps the day once a sweep has started."""
    try:
        if time.time() - os.path.getmtime(_stamp(repo)) < NIGHTLY_SECS:
            return False
    except OSError:
        pass
    rec = record(repo)
    return bool(rec and any(n >= MIN_RUNS for n in rec["runs"].values()) and rec["first"]
                and rec["first"] <= time.time() - WINDOW_DAYS * 86400)


def mark(repo: str) -> None:
    f = _stamp(repo)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    open(f, "w").close()


def spawn(repo: str) -> tuple:
    """`lander nightly run --repo <repo>` as its own transient unit, as lane.spawn_lane starts a lane: a sweep can
    take an hour, a tick must not wait on it, and a child left in the tick's unit dies when the tick ends.
    -> (started, the line to print)."""
    from lander import jobs as J
    from lander import lane as L
    argv = [sys.executable, "-P", os.path.join(J.CORE, "lander", "cli.py"), "nightly", "run", "--repo", repo]
    unit = f"lander-nightly-{repo}-{int(time.time())}"
    rc, out, err = L.run([os.environ.get("LANDER_SYSTEMD_RUN") or "systemd-run", "--user", "--collect", "--quiet",
                          f"--unit={unit}", "--setenv=PYTHONDONTWRITEBYTECODE=1", *argv], timeout=30)
    if rc == 0:
        return True, f"[{repo}] nightly sweep started (unit {unit})"
    if os.environ.get("INVOCATION_ID"):
        return False, f"[{repo}] the nightly sweep would not start inside a unit: {(err or out).strip()[-160:] or rc}"
    try:   # tick_env's allow-list, as spawn_tick passes it: never the caller's pane env (security read of #1190)
        p = subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env=dict(L.tick_env(os.environ), PYTHONDONTWRITEBYTECODE="1"))
        return True, f"[{repo}] nightly sweep started (pid {p.pid})"
    except OSError as e:
        return False, f"[{repo}] the nightly sweep would not start: {e}"


def file_row(repo: str, check: str, sha: str, why: str) -> str:
    """One board row naming the red check, once: a row already there is left alone."""
    from lander import board as B
    from lander import cards as C
    b, row = B.tool("cc-board"), f"nightly-red-{check}"[:60]
    rc, out = C.sh([b, "get", repo, row, "status"], timeout=60)
    if rc == 0 and out.strip():
        return f"board row {row} is already there"
    brief = (f"GOAL: check {check} passes on main again. WHY: it had no PR-caused red in {WINDOW_DAYS} days, so the "
             f"lander ran it nightly instead of per PR, and it went red on main at {sha[:12]}: {why}. It is back in "
             f"the per-PR plan for {WINDOW_DAYS} days; find the merge that broke it, or why it can't run, and fix it.")
    rc, out = C.sh([b, "add", repo, row, f"check {check} went red or could not run on main overnight", brief], timeout=60)
    return f"board row {row} filed" if rc == 0 else f"board row not filed: {out.strip()[-160:]}"


def run(repo: str, check=None) -> list:
    """Each moved check once on the repo's applied tip; one `nightly` queue.log line each, a row for each red."""
    from lander import deploy as D
    from lander import tick as TK
    sha, root, fb = D.applied(repo), D.root_of(repo), M.host_fallback(repo)
    if not sha:
        return [f"[{repo}] nightly: no applied tip to run on"]
    try:
        m = M.load(root, sha, fallback=fb)
    except M.ManifestError as e:
        return [f"[{repo}] nightly: the manifest at {sha[:12]} does not parse: {e}"]
    check = check or TK.make_check(root, fallback=fb, first=False)
    lines = []
    for n in moved(repo, m):
        r = check(n, sha)
        ok = {T.PASSED: "yes", T.FAILED: "no"}.get(r.status, "unrunnable")
        E.log("nightly", repo, None, check=n, ok=ok, secs=int(r.secs), sha=sha[:12])
        lines.append(f"[{repo}] nightly {n}: {r.status}")
        if r.status != T.PASSED:   # an unrunnable result counts as red, so it files a row too
            lines.append(f"[{repo}] {file_row(repo, n, sha, r.extra.get('why') or 'see its log')}")
    return lines


def report(repo: str, m: M.Manifest, rec: dict, now: float | None = None) -> list:
    out = moved(repo, m, rec, now)
    prs = max(1, len(rec.get("prs") or ()))
    total = sum(rec["secs"].values())
    kept = sum(s for n, s in rec["secs"].items() if n not in out)
    lines = [f"{repo}: {len(out)} of {len(m.checks)} checks run nightly instead of per PR"
             + (f": {', '.join(out)}" if out else "")]
    lines.append(f"{repo}: gate-hours per PR over {len(rec.get('prs') or ())} PRs: before {total / prs / 3600:.2f} h, "
                 f"after {kept / prs / 3600:.2f} h")
    return lines


def cmd_nightly(argv):
    from lander import lane as L
    from lander import deploy as D
    pos, opts = L.split_opts(argv, "--repo", "--days")
    repo, days = opts.get("--repo", ""), opts.get("--days", "7")
    if pos == ["run"]:
        if not repo:
            return L.refuse("usage: lander nightly run --repo R")
        for ln in run(repo):
            print(ln)
        return 0
    if pos or not repo or not days.isdigit():
        return L.refuse("usage: lander nightly --repo R [--days N] | lander nightly run --repo R")
    try:
        m = M.load(D.root_of(repo), D.applied(repo) or "HEAD", fallback=M.host_fallback(repo))
    except M.ManifestError as e:
        return L.refuse(f"lander nightly: the manifest does not parse: {e}", 1)
    for ln in report(repo, m, record(repo, days=int(days))):
        print(ln)
    return 0


COMMANDS = {"nightly": (cmd_nightly, "never-red checks run nightly: the moved list and gate-hours per PR; "
                                     "`run --repo R` sweeps them [--days N]")}
