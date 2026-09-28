"""One serial lane per repo: intake, the job machine, Δ revalidation, the merge and its tree proof.

    lander queue <repo|h--t> <pr> [--chat C --ts T --who W --approved-by UID --no-start]
    lander queue --task <repo> <row>
    lander lane <repo>          run the repo's lane in the foreground (what `queue` and `tick` start)

QUEUE is the door (the old cc-land's cmd_queue). It checks the shape; for a member project (`<h>--<t>`) it refuses
the workspace itself and needs the granted token, a repository the board row names under the owner's own account,
and the host-only clone (members.py), each refusal one `refused` line. A PR touching one of the repo's protected
paths (CC_PROTECTED_PATHS_<repo>, cc-config; a config that will not read is a hit) is refused unless --approved-by
is the owner's own uid (SLACK_OWNER_ID): `refused <repo>#<pr> protected:<file>`, the 🔐 card (cards.stopped, route
"door"), exit 1. With his 👍 queue writes the approval record (jobs.approve: his uid and the head gh names — a
head gh cannot name refuses); the inbox request carries no approval, because anyone may write the inbox and drain
takes only chat/ts/who from it. The request goes to the inbox (jobs.submit); `queued` is logged only for a PR
with no job yet (drain logs `again` or `requeued` for the rest, so `times` is not restarted). A paused project keeps the request and says so (exit 0); --no-start
says where it waits (exit 0); otherwise `lander tick --repo <repo>` is started detached, and a start that fails is
exit 1 "queued, but…". `queue --task` is the old queue_task unchanged: `cc done <repo> <row> --json`, `cc lands`
0 queue / 1 approval / 2 refused, anything else failed; the receipt (with `landing`) is the one line on stdout.

THE LANE (Lane.run) takes <repo>.lock (busy: return — the running lane re-reads), drains the inbox, and steps each
job, oldest queued_at first, until it rests (held until not_before, query, done, deploy-pending, handed back),
re-reading the list after each. BOX HOLDS come first and leave the file untouched and the job untimed:
`cc-pause is <repo or handle>` exit 0 holds everything; `cc-tier allows gates` exit 1 holds jobs before the merge.
  queued     gh facts; MERGED -> merged (by=before); CLOSED -> done; a draft or a conflict -> held 15 min. Under
             the git lock fetch base and head; base_sha, files (merge-base..head), digest. A member PR meets its
             walls (-> handback). THE PROTECTED DOOR, asked again at every head, reads the approval record
             (jobs.approval, never the request): the owner's uid, and the head he 👍'd — or a later head whose
             protected files are byte-identical, which carries approved_head to it (`approval … carried`); else
             -> query, route "owner". plan(); klass lander -> query "lander-self".
  checking   the plan's checks on merge-tree(base_sha, head), each through runner.run_plan (run.judge: the red-vs-
             base rule, the rerun alone under load, quarantine, the lane's records.Store under its lock, and the
             failures-ledger record of a red that is the diff's) against the manifest at base widened by the head's —
             a member's on "member:<h>" — skipping those already in results. FAILED -> handback;
             blocked-by-main (red on the base tree too) -> held 15 min and planned again from main then, not blamed;
             a check the manifest lacks -> query "planning"; UNRUNNABLE -> held 15 min, the 3rd -> query. Then,
             when the plan is paid, one read (a delta read when a prior verdict exists; none when a LAND is already
             recorded at this digest): INCOMPLETE -> held till the `until` it names (a usage limit's reset; stage
             `deferred`, which no reader counts as running), no read counted; HANDBACK ->
             reads_used+1, handback, or query "planning" at the 2nd; LAND counts a read only when it was bought.
             A member over its day's cap is held; a bought read is charged to it.
  mergeable  the head moved -> queued. main moved -> Δ re-plan (S2): rerun = (new − old) ∪ (new ∩ checks Δ
             reaches); non-empty -> checking with only those; empty -> base_sha = main and merge. THE MERGE (S1),
             all under the git lock: fetch; main_before must be base_sha (else back to Δ); expected =
             merge-tree(main_before, head); merge_attempt {main_before, expected, pin} written BEFORE gh; the squash
             pinned to head (the door made the approved head equal it), --delete-branch, --subject "<title> (#N)";
             fetch; the tip's tree must equal expected, else the tip is `unvalidated` (no deploy request; `stage …
             merged … proof=mismatch`). A refused merge drops merge_attempt; one GitHub cannot confirm either way
             keeps it and holds (box). A resume that finds merge_attempt asks GitHub first: MERGED proves against
             the squash commit GitHub names; unreadable holds again, attempt kept; any other state drops it.
  merged     board.close, cards.landed, tip.kick, deploy.request(repo, tip) — each once (job.post flags) —
             then deploy-pending; done (rc=0) for a member or an unvalidated tip. Members never deploy.
HANDBACK writes handed/<repo>-<pr>.json (7 days) and REMOVES the job file (N12); cards.stopped routes it to
"#<h>" or "seat". DONE and QUERY move the job file to rest/ (jobs.py): off the readers' queue, as the old lander's
unlink was, but still loaded by a re-queue. A unit that is not installed holds the job ("<unit> is not
installed"); a board unit that is absent is BoardRules below: the row carrying the PR -> merged (an orch-held row
gets a note only), each `Closes <row>` of the same board -> done unless held or live without an agent mark, that
mark cleared, an unknown row named; a symlinked board file is refused.

The git lock is never held across a check or a review; the lane lock is held for the whole run.
"""
from __future__ import annotations

import contextlib
import importlib
import json
import os
import re
import subprocess
import sys
import time

from lander import events as E
from lander import gh as GH
from lander import git as G
from lander import jobs as J
from lander import manifest as MF
from lander import members as M
from lander import records as REC
from lander import run as RUN
from lander import types as T

HOLD_SECS = 900          # a held job waits this long before the lane tries it again
UNRUNNABLE_TRIES = 3     # the 3rd unrunnable check (or refused merge) is a query, not another hold
READS_CAP = 2            # reads per change family; the 2nd handback is a query to the planning seat
HANDED_DAYS = 7
MAX_STEPS = 40
MOVES_BEFORE_HOLD = 5    # main moving under the merge this many times in one step holds the job
GH_PR_FILES = 100        # gh lists at most this many files; at or over it git names them all
FIELDS = "state,isDraft,mergeable,headRefOid,headRefName,baseRefName,title,body"
PRE_MERGE = (T.QUEUED, T.PLANNED, T.CHECKING)
MODULE_OF = {"planner": "plan", "runner": "run", "reviewer": "review", "cards": "cards", "board": "board",
             "deploy": "deploy", "tip": "tip"}


class UnitFault(Exception):
    """A unit that raised: the job is held and says which one."""


def load_units() -> dict:
    """The installed units (lander.<module>), each module being the unit; board falls back to BoardRules."""
    units = {}
    for u, m in MODULE_OF.items():
        try:
            units[u] = importlib.import_module(f"lander.{m}")
        except ModuleNotFoundError as e:
            if e.name not in (m, f"lander.{m}"):
                raise
    units.setdefault("board", BoardRules())
    return units


def run(argv, timeout=60, **kw):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, **kw)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 125, "", str(e)


def paused(target) -> bool:
    return run([f"{J.bin_dir()}/cc-pause", "is", str(target)], timeout=10)[0] == 0


def tier_stop() -> bool:
    return run([f"{J.bin_dir()}/cc-tier", "allows", "gates"], timeout=10)[0] == 1


# --- protected paths (the 👍 door) ---------------------------------------------------------------------------------

def protected_rules(repo):
    """The repo's protected prefixes; [] when it has none (cc-config exit 1 is "not set"); None when cc-config did
    not answer at all, which every caller reads as a hit — the one guard that must fail closed."""
    rc, out, _ = run([f"{J.bin_dir()}/cc-config", "get", "CC_PROTECTED_PATHS_" + re.sub(r"[^A-Za-z0-9]", "_", repo)],
                     timeout=30)
    return out.split() if rc == 0 else [] if rc == 1 else None


def under(path, rules):
    return next((r for r in rules if path == r.rstrip("/") or path.startswith(r.rstrip("/") + "/")), "")


def first_hit(files, rules):
    """(file, rule) for the first file under a rule, ('?', why) when the rules would not read, else None."""
    if rules is None:
        return "?", "cc-config could not read the repo's protected paths"
    for f in files:
        r = under(f, rules)
        if r:
            return f, r
    return None


def hold_words(repo, hit):
    return (f"it touches {hit[0]}, under {repo}'s PROTECTED path {hit[1]} (CC_PROTECTED_PATHS_{repo})"
            if hit[0] != "?" else f"{hit[1]}, and {repo} has PROTECTED paths")


def owner_approved(uid) -> bool:
    return bool(uid) and uid == M.config("SLACK_OWNER_ID")


def pr_head(root, pr, token=None, genv=None) -> str:
    j = GH.pr_facts(root, pr, "headRefOid,headRefName", token, 60)[0] or {}
    return G.remote_head(root, (j.get("headRefName") or "").strip(), env=genv) or (j.get("headRefOid") or "").strip()


def git_pr_files(root, pr, token=None, genv=None):
    """Every path the PR changes, from git (gh's list stops at GH_PR_FILES); None on any doubt."""
    j = GH.pr_facts(root, pr, "baseRefName,headRefName", token, 60)[0] or {}
    base, branch = (j.get("baseRefName") or "").strip(), (j.get("headRefName") or "").strip()
    if not (base and branch):
        return None
    try:
        with G.git_lock(root):
            G.fetch(root, base, branch, env=genv)
        mb = G.merge_base(root, f"refs/remotes/origin/{base}", f"refs/remotes/origin/{branch}", env=genv)
        return G.changed(root, mb, f"refs/remotes/origin/{branch}", env=genv) or None
    except G.GitError:
        return None


def protected_hit(repo, root, pr, token=None, genv=None):
    rules = protected_rules(repo)
    if rules == []:
        return None
    if rules is None:
        return first_hit([], None)
    files = GH.pr_files(root, pr, token)
    if files is None:
        return "?", "gh could not list the PR's files"
    if len(files) >= GH_PR_FILES:
        files = git_pr_files(root, pr, token, genv)
        if files is None:
            return "?", f"gh lists only the first {GH_PR_FILES} files and git could not list the rest"
    return first_hit(files, rules)


# --- the board (used when lander.board is not installed) ------------------------------------------------------------

CLOSES_RE = re.compile(r"\bCloses:?\s+([A-Za-z0-9][A-Za-z0-9_-]*(?:\s*(?:,\s*(?:and\s+)?|\s+and\s+)[A-Za-z0-9][A-Za-z0-9_-]*)*)")


def closes_rows(body):
    """The row names a PR body says it closes, in order, each once."""
    seen = []
    for m in CLOSES_RE.finditer(body or ""):
        for r in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", m.group(1)):
            r = r.strip()
            if r and r.lower() != "and" and r not in seen:
                seen.append(r)
    return seen


def orch_mark(repo, mark):
    """The orch window `<repo>@<alias>` a row's agent mark `@<window>:<pid>` names, or '' (tmux silent: '')."""
    wid = (mark or "").split(":")[0]
    if not re.fullmatch(r"@\d+", wid):
        return ""
    rc, out, _ = run([os.environ.get("LANDER_TMUX") or "tmux", "list-windows", "-t", "main", "-F",
                      "#{window_id}\t#{window_name}"])
    for row in out.splitlines() if rc == 0 else []:
        w, _, name = row.partition("\t")
        if w == wid and re.fullmatch(re.escape(repo) + r"@[a-z0-9-]{2,20}", name):
            return name
    return ""


class BoardRules:
    """board.close(job) through the cc-board CLI, as the old lander's close_board. Returns its one line."""

    def board(self, project):
        return J.board(project)

    def cc_board(self, *args):
        return run([f"{J.bin_dir()}/cc-board", *args])

    def find_track(self, project, job):
        h, t = M.member_of(job.repo)
        if h and t:
            return t
        rows = self.board(project).get("tracks") or {}
        for name, row in rows.items():
            pr = str(row.get("pr") or "")
            if re.search(rf"/pull/{job.pr}(?:/|$)", pr) or pr == str(job.pr):
                return name
        head = job.extra.get("branch") or ""
        for name, row in rows.items():
            if head and row.get("branch") == head:
                return name
        m = re.fullmatch(r"(?:track|planning|builder)/(.+)", head)
        return m.group(1) if m and m.group(1) in rows else ""

    def close(self, job):
        project = M.member_of(job.repo)[0] or job.repo
        what = f"PR #{job.pr}" + (f" ({job.extra.get('title')})" if job.extra.get("title") else "")
        t = self.find_track(project, job)
        rows = self.board(project).get("tracks") or {}
        if not t:
            return f"board: no row on {project} carries PR #{job.pr} — nothing to close"
        if t not in rows:
            return f"board: the {project} board has no row '{t}'"
        orch = orch_mark(project, (rows.get(t) or {}).get("agent"))
        if orch:
            self.cc_board("note", project, t, f"milestone landed by the lander: {what}; left open, {orch} holds this row")
            line = f"board: {project}/{t} left open — {orch} holds it"
        else:
            rc, out, err = self.cc_board("status", project, t, "merged")
            if rc:
                raise UnitFault(f"cc-board status: {GH.last(err or out)}")
            self.cc_board("note", project, t, f"landed by the lander: {what}")
            line = f"board: {project}/{t} -> merged"
        closed, unknown, held = [], [], []
        rows = self.board(project).get("tracks") or {}
        for r in closes_rows(job.extra.get("body") or ""):
            if r == t or (rows.get(r) or {}).get("status") in ("merged", "done"):
                continue
            if r not in rows:
                if re.search(r"[-_0-9]", r):   # shaped like a row; a bare word is prose
                    unknown.append(r)
                continue
            mark = (rows[r].get("agent") or "").strip()
            if rows[r].get("held") or (rows[r].get("status") in ("running", "review") and not mark):
                held.append(r)
                continue
            rc, out, err = self.cc_board("status", project, r, "done")
            if rc:
                raise UnitFault(f"cc-board status {r}: {GH.last(err or out)}")
            self.cc_board("note", project, r, f"closed by the lander: {what} says Closes {r}")
            if mark:
                self.cc_board("set", project, r, "agent", "")
            closed.append(r)
        if closed:
            line += f"; closes {', '.join(closed)}"
        if held:
            line += f" (held by a person or live on a track, left open: {', '.join(held)})"
        if unknown:
            line += f" (Closes names no row on the board: {', '.join(unknown)})"
        return line


# --- the lane ------------------------------------------------------------------------------------------------------

class Lane:
    def __init__(self, repo, units=None):
        self.repo = repo
        self.units = load_units() if units is None else dict(units)
        self.units.setdefault("board", BoardRules())
        h, t = M.member_of(repo)
        self.member = h if h and t else ""
        self.root = J.repo_root(repo)
        self.genv = M.env(self.member) if self.member else None
        self.token = (self.genv or {}).get("GH_TOKEN")
        self.fallback = MF.host_fallback(repo)   # the release's landing-repos/<repo>.toml; "" when the repo has none
        self.lines = []

    def say(self, text):
        self.lines.append(f"[{self.repo}] {text}")

    def unit(self, name):
        return self.units.get(name)

    def call(self, name, fn, *args, **kw):
        try:
            return getattr(self.unit(name), fn)(*args, **kw)
        except (UnitFault, G.GitError):
            raise
        except Exception as e:  # noqa: BLE001 — a unit's fault holds the job, never the lane
            raise UnitFault(f"{name}.{fn}: {type(e).__name__}: {e}") from e

    # -- the loop --
    def run(self):
        while True:
            with J.lane_lock(self.repo) as got:
                if not got:
                    self.say("a lane is already running; it re-reads the queue itself")
                    return self.lines
                with contextlib.suppress(OSError, ValueError):   # base runs an earlier lane shared are not reused
                    REC.new_nonce(self.repo, J.landq())
                tried = set()
                while True:
                    for ln in J.drain(self.repo):
                        self.say(ln)
                    todo = [j for j in J.lane_jobs(self.repo) if j.key not in tried and self.due(j)]
                    if not todo:
                        break
                    job = todo[0]
                    tried.add(job.key)
                    why = self.box_hold(job)
                    if why:
                        self.say(f"PR #{job.pr}: {why}")
                        continue
                    self.advance(job)
            if not J.requests(self.repo):   # a request that met the held lock after its last drain: once more
                return self.lines

    def due(self, job):
        return job.state not in J.RESTING and not (job.state == T.HELD and J.not_before_left(job))

    def box_hold(self, job):
        target = self.member or self.repo
        if paused(target):
            return f"{target} is paused — still queued, lands after `cc-pause off {target}`"
        pre = job.state in PRE_MERGE or (job.state == T.HELD and job.extra.get("held_from", T.QUEUED) in PRE_MERGE)
        if pre and tier_stop():
            return "spend tier stop — still queued, its checks run after `cc-tier set` a wider tier"
        return ""

    def advance(self, job):
        if job.state == T.QUEUED:
            E.stage(job.repo, job.pr, "lane")
        for _ in range(MAX_STEPS):
            if not self.due(job):
                return
            before = (job.state, len(job.history))
            self.step(job)
            if (job.state, len(job.history)) == before:
                return

    def step(self, job):
        steps = {T.QUEUED: self.queued, T.PLANNED: self.planned, T.CHECKING: self.checking,
                 T.MERGEABLE: self.mergeable, T.MERGED: self.merged, T.HELD: self.unhold}
        if job.state in (T.QUEUED, T.MERGEABLE) and GH.backoff():
            self.say(f"PR #{job.pr}: GitHub backoff, {GH.backoff()}s left — tried again after it")
            return
        try:
            steps[job.state](job)
        except (UnitFault, G.GitError) as e:
            self.hold(job, str(e), kind="box")

    # -- leaving the lane --
    def hold(self, job, why, kind="pr", secs=HOLD_SECS, until=0, then=None, deferred=False):
        """kind "pr": a push mends it (a new queue starts fresh); "box": time mends it (a new queue joins it).
        until: an epoch to wait for instead of secs (a usage limit's reset). then: the state to go back to (default
        the one it was held from). deferred: the job waits on a limit, not on work — stage `deferred`."""
        if job.state == T.HELD:
            return
        at = until if until > time.time() else time.time() + secs
        job.extra.update(held_from=then or job.state, hold=kind, why=why, not_before=E.stamp(at))
        if deferred:
            job.extra["deferred"] = True
        J.move(job, T.HELD, why)
        self.say(f"PR #{job.pr} held: {why}")

    def unhold(self, job):
        target = job.extra.pop("held_from", T.QUEUED)
        for k in ("hold", "not_before", "deferred"):
            job.extra.pop(k, None)
        J.move(job, target if target in J.NEXT[T.HELD] else T.QUEUED, why="retry after hold")

    def stopped(self, job, why, route):
        if self.unit("cards"):
            with contextlib.suppress(UnitFault):
                self.call("cards", "stopped", job, why, route)

    def query(self, job, why, route):
        job.extra["why"] = why
        J.move(job, T.QUERY, why)
        self.stopped(job, why, route)
        self.say(f"PR #{job.pr} is a query for {route}: {why}")

    def handback(self, job, why):
        now = time.time()
        J.write_atomic(J.handed_path(job.repo, job.pr), {
            "repo": job.repo, "pr": job.pr, "head": job.head, "branch": job.extra.get("branch") or "",
            "since": E.stamp(now), "until": E.stamp(now + HANDED_DAYS * 86400), "reads_used": job.reads_used,
            "verdict": job.extra.get("verdict") or {}, "why": why, "chat": job.extra.get("chat") or "",
            "ts": job.extra.get("ts") or ""})
        job.extra["why"] = why
        J.move(job, T.HANDBACK, why)
        J.remove(job)
        self.stopped(job, why, M.route(job) or "seat")
        E.log("handed", job.repo, job.pr, f"head={job.head[:12]} — a push to {job.extra.get('branch') or '?'} "
                                          f"re-queues it (watched {HANDED_DAYS} days)")
        self.say(f"PR #{job.pr} handed back: {why}")

    # -- the states --
    def lock(self):
        return G.git_lock(self.root)

    def queued(self, job):
        facts, why = GH.pr_facts(self.root, job.pr, FIELDS, self.token)
        if facts is None:
            return self.hold(job, f"gh could not read PR #{job.pr}: {why}", kind="box")
        base, branch = facts.get("baseRefName") or "", facts.get("headRefName") or ""
        job.extra.update(title=facts.get("title") or "", body=facts.get("body") or "", branch=branch, base_ref=base)
        state = facts.get("state") or ""
        if state == "MERGED":
            job.head = facts.get("headRefOid") or job.head
            return J.move(job, T.MERGED, why="merged before the lane got to it", by="before")
        if state == "CLOSED":
            J.move(job, T.DONE, why="the PR is closed")
            return E.log("done", job.repo, job.pr, rc=1)
        if facts.get("isDraft"):
            return self.hold(job, f"PR #{job.pr} is a draft — mark it ready for review")
        if facts.get("mergeable") == "CONFLICTING":
            return self.hold(job, f"PR #{job.pr} conflicts with {base} — rebase it")
        with self.lock():
            G.fetch(self.root, base, branch, env=self.genv)
            job.base_sha = G.rev(self.root, f"refs/remotes/origin/{base}", env=self.genv)
            job.head = G.rev(self.root, f"refs/remotes/origin/{branch}", env=self.genv)
        mb = G.merge_base(self.root, job.base_sha, job.head, env=self.genv)
        job.files = G.changed(self.root, mb, job.head, env=self.genv)
        job.digest = G.patch_digest(self.root, job.base_sha, job.head, env=self.genv)
        job.results, job.plan = {}, None
        job.extra.pop("tree", None)
        if self.member:
            why = M.walls(self.root, job.base_sha, job.head, job.files, self.genv)
            if why:
                return self.handback(job, why)
        why = self.door(job)
        if why:
            return self.query(job, why, "owner")
        if not self.unit("planner"):
            return self.hold(job, "planner is not installed", kind="box")
        job.plan = self.call("planner", "plan", self.root, job.base_sha, job.head, job.files, fallback=self.fallback)
        if job.plan.klass == T.LANDER:
            return self.query(job, "it changes the lander itself — lander-self lands it", "lander-self")
        J.move(job, T.PLANNED)

    def door(self, job):
        """Why the protected door stops this head, or ''. Asked at every head."""
        rules = protected_rules(self.repo)
        hit = first_hit(job.files, rules)
        if not hit:
            return ""
        words = hold_words(self.repo, hit)
        rec = J.approval(job.repo, job.pr)   # the lane's own record of the 👍, written by `lander queue`
        by = rec.get("approved_by") or ""
        if not owner_approved(by):
            return f"{words}, and no 👍 of the owner's queued it"
        ah = rec.get("approved_head") or ""
        if job.head == ah:
            return ""
        if rules and ah and G.protected_same(self.root, rules, ah, job.head, env=self.genv):
            E.log("approval", job.repo, job.pr, f"carried {ah[:12]} → {job.head[:12]}: protected paths unchanged")
            J.approve(job.repo, job.pr, by, job.head)
            return ""
        return f"{words}, at a head the owner has not 👍'd ({ah[:12] or 'no head recorded'} → {job.head[:12]})"

    def planned(self, job):
        J.move(job, T.CHECKING)

    def manifest(self, job):
        """The manifest at base, widened by the head's (what plan() planned on and `lander check` runs by)."""
        try:
            return MF.widen(MF.load(self.root, job.base_sha, fallback=self.fallback),
                            MF.load(self.root, job.head, fallback=self.fallback, strict=False))
        except MF.ManifestError as e:
            raise UnitFault(f"the manifest at {job.base_sha[:12]} does not parse: {e}") from None

    def checking(self, job):
        if not self.unit("runner"):
            return self.hold(job, "runner is not installed", kind="box")
        names = list(job.plan.checks if job.plan else [])
        todo = [n for n in names if n not in job.results]
        base_ref = job.extra.get("base_ref") or "main"
        if todo:
            m = self.manifest(job)
            with self.lock():
                tree, conflicts = G.merge_tree(self.root, job.base_sha, job.head, env=self.genv)
            if tree is None:
                return self.hold(job, f"PR #{job.pr} conflicts with {base_ref}: {', '.join(conflicts[:5])}")
            base_tree = G.tree_of(self.root, job.base_sha, env=self.genv)
            job.extra["tree"] = tree
            store = REC.Store(self.repo, J.lane_fd(self.repo), J.landq()) if J.lane_fd(self.repo) is not None else None
            quarantine = RUN.quarantine_text(self.root, job.base_sha)
        for n in todo:
            outs = self.call("runner", "run_plan", self.root, m, job.plan, job.files, tree, base_tree,
                             member=self.member, store=store, job_key=job.key, scope=self.member or self.repo,
                             pr=job.pr, quarantine_text=quarantine, only=[n], fallback=self.fallback)
            o = outs.get(n) or RUN.Outcome(n, T.UNRUNNABLE, "the runner gave no outcome")
            secs = int(sum(r.secs for r in o.results))
            word = {T.PASSED: "yes", RUN.BLOCKED: "main-red"}.get(o.status, "no")
            E.stage(job.repo, job.pr, "gate", gate=n, ok=word, secs=secs, note=o.note if o.status == T.PASSED else "")
            if o.status == T.FAILED:
                return self.handback(job, f"check {n} failed on the merge with {base_ref} ({tree[:12]})"
                                          + (f": {o.note}" if o.note else ""))
            if o.status == RUN.BLOCKED:
                # design §0: base red too -> blocked-by-main, not blamed; it is planned again from main after the hold
                return self.hold(job, f"{o.note}: check {n} is red on {base_ref} ({job.base_sha[:12]}) too, so it "
                                      f"is main's, not this PR's — tried again from {base_ref} later",
                                 kind="box", then=T.QUEUED)
            if o.status == T.UNRUNNABLE and o.note == "not in the manifest":
                return self.query(job, f"the plan names checks the manifest at base lacks: {n}", "planning")
            if o.status == T.UNRUNNABLE:
                job.extra["attempts"] = int(job.extra.get("attempts") or 0) + 1
                if job.extra["attempts"] >= UNRUNNABLE_TRIES:
                    return self.query(job, f"check {n} could not run {UNRUNNABLE_TRIES} times", "planning")
                return self.hold(job, f"check {n} could not run (try {job.extra['attempts']} of "
                                      f"{UNRUNNABLE_TRIES}): {o.note}", kind="box")
            job.results[n] = o.results[0].key if o.results else ""
            J.save(job)
        if job.plan and job.plan.paid and not self.review(job):
            return
        J.move(job, T.MERGEABLE)

    def review(self, job):
        """True when the job may go on to the merge; otherwise it has been held, handed back or queried."""
        prior = job.extra.get("verdict")
        pv = T.Verdict.from_dict(prior) if isinstance(prior, dict) and prior else None
        if pv and pv.verdict == T.LAND and pv.digest == job.digest:
            return True   # a LAND already read at this very digest (a Δ rerun): no second read
        if not self.unit("reviewer"):
            self.hold(job, "reviewer is not installed", kind="box")
            return False
        if self.member:
            usd, cap = M.spent(self.member)
            if usd >= cap:
                self.hold(job, f"{self.member} has spent its day's review cap (${usd:g} of ${cap:g})", kind="box")
                return False
        v = self.call("reviewer", "delta_review", job, pv) if pv else self.call("reviewer", "review", job)
        E.stage(job.repo, job.pr, "verdict", verdict=v.verdict)
        if self.member and v.tokens > 0:
            M.charge(self.member, float(v.extra.get("usd") or 1.0))
        if v.verdict == T.INCOMPLETE:   # a usage or budget wall: wait for the reset it names, no read counted
            until = v.extra.get("until") or ""
            self.hold(job, f"the review stopped on a usage or budget wall ({v.extra.get('why') or 'no reason given'}); "
                           f"no read was counted" + (f", asked again at {until}" if until else ""),
                      kind="box", until=E.epoch_of(until), deferred=True)
            return False
        job.extra["verdict"], job.review_key = v.to_dict(), v.digest
        if v.verdict == T.HANDBACK_VERDICT:
            job.reads_used += 1
            why = "the review handed it back: " + ("; ".join(v.blocking) or "no finding named")
            if job.reads_used >= READS_CAP:
                self.query(job, f"{why} — {job.reads_used} reads spent on this change", "planning")
            else:
                self.handback(job, why)
            return False
        if v.tokens > 0:
            job.reads_used += 1
        J.save(job)
        return True

    def mergeable(self, job):
        ma = job.extra.get("merge_attempt")
        if ma:   # a crash between the merge call and its proof, or a merge GitHub could not confirm
            state, oid = GH.merge_state(self.root, job.pr, self.token)
            if not state:   # unknown is not "not merged": keep the attempt and ask again
                return self.hold(job, f"GitHub could not say whether PR #{job.pr} merged", kind="box")
            if state == "MERGED":
                base = job.extra.get("base_ref") or ""
                with self.lock():
                    G.fetch(self.root, base, env=self.genv)
                    tip = oid or G.rev(self.root, f"refs/remotes/origin/{base}", env=self.genv)
                return self.proved(job, ma.get("expected") or "", tip, ma.get("pin") or job.head)
            job.extra.pop("merge_attempt", None)
            J.save(job)
        base, branch = job.extra.get("base_ref") or "", job.extra.get("branch") or ""
        for _ in range(MOVES_BEFORE_HOLD):
            with self.lock():
                G.fetch(self.root, base, branch, env=self.genv)
                head_now = G.rev(self.root, f"refs/remotes/origin/{branch}", env=self.genv)
                main_now = G.rev(self.root, f"refs/remotes/origin/{base}", env=self.genv)
            if head_now != job.head:
                return J.move(job, T.QUEUED, why=f"the head moved to {head_now[:12]}")
            if main_now != job.base_sha and self.revalidate(job, main_now):
                return J.move(job, T.CHECKING, why="main moved: rerun " + ", ".join(job.extra.get("rerun") or []))
            if self.merge(job) != "moved":
                return
        self.hold(job, f"{base} kept moving under the merge", kind="box")

    def revalidate(self, job, main_now):
        """Δ re-plan (S2). True when something must run again (only those checks' results are dropped)."""
        delta = G.changed(self.root, job.base_sha, main_now, env=self.genv)
        new = self.call("planner", "plan", self.root, main_now, job.head, job.files, fallback=self.fallback)
        own = self.call("planner", "plan", self.root, job.base_sha, main_now, delta, fallback=self.fallback).checks
        old = set(job.plan.checks if job.plan else [])
        rerun = sorted((set(new.checks) - old) | (set(new.checks) & set(own)))
        # a plan that became paid with no LAND at this digest must go through the review too
        pv = job.extra.get("verdict") or {}
        needs_read = new.paid and not (pv.get("verdict") == T.LAND and pv.get("digest") == job.digest)
        job.plan, job.base_sha = new, main_now
        for n in rerun:
            job.results.pop(n, None)
        job.extra["rerun"] = rerun
        J.save(job)
        return bool(rerun) or needs_read

    def merge(self, job):
        pin = job.head   # door() made approved_head equal it when a protected path is hit; else it is stale
        base = job.extra.get("base_ref") or ""
        with self.lock():
            G.fetch(self.root, base, env=self.genv)
            main_before = G.rev(self.root, f"refs/remotes/origin/{base}", env=self.genv)
            if main_before != job.base_sha:
                return "moved"
            expected, conflicts = G.merge_tree(self.root, main_before, job.head, env=self.genv)
            if expected is None:
                self.hold(job, f"PR #{job.pr} conflicts with {base}: {', '.join(conflicts[:5])}")
                return "held"
            job.extra["merge_attempt"] = {"main_before": main_before, "expected": expected, "pin": pin}
            J.save(job)
            ok, text = GH.merge(self.root, job.pr, pin, job.extra.get("title") or "", self.token)
            if ok is None:   # merge_attempt stays: the resume asks GitHub once it answers
                self.hold(job, text, kind="box")
                return "held"
            if not ok:
                job.extra.pop("merge_attempt", None)
                job.extra["attempts"] = int(job.extra.get("attempts") or 0) + 1
                if job.extra["attempts"] >= UNRUNNABLE_TRIES:
                    self.query(job, f"the merge was refused {job.extra['attempts']} times: {text}", "planning")
                else:
                    self.hold(job, text, kind="box" if GH.backoff() else "pr")
                return "held"
            G.fetch(self.root, base, env=self.genv)
            tip = G.rev(self.root, f"refs/remotes/origin/{base}", env=self.genv)
        self.proved(job, expected, tip, pin)
        return "merged"

    def proved(self, job, expected, tip, pin):
        """S1: the tip's tree must be the merge-tree the lane computed just before the merge call."""
        ok = bool(expected) and G.tree_of(self.root, tip, env=self.genv) == expected
        job.extra.pop("merge_attempt", None)
        job.extra["tip_sha"] = tip
        if not ok:
            job.extra["tip"] = "unvalidated"
        J.move(job, T.MERGED, sha=pin[:12], proof=None if ok else "mismatch")
        self.say(f"PR #{job.pr} merged ({tip[:12]})" + ("" if ok else " — the tip's tree is not the one validated"))

    def merged(self, job):
        post = job.extra.setdefault("post", {})

        def once(name, unit, fn, *args):
            if name in post or not self.unit(unit):
                return
            try:
                got = self.call(unit, fn, *args)
                post[name] = "ok"
                if isinstance(got, str) and got:
                    self.say(got)
            except (UnitFault, G.GitError) as e:
                post[name] = f"failed: {e}"[:300]   # bookkeeping: said once, never repeated by a resume
                self.say(f"PR #{job.pr}: {name} failed: {e}")
            J.save(job)
        once("board", "board", "close", job)
        once("card", "cards", "landed", job)
        once("tip", "tip", "kick", job.repo)
        if self.member or job.extra.get("tip") == "unvalidated":
            J.move(job, T.DONE, why="a member project never deploys" if self.member else "the tip is unvalidated")
            return E.log("done", job.repo, job.pr, rc=0)
        if not job.extra.get("tip_sha"):
            base = job.extra.get("base_ref") or ""
            with self.lock():
                G.fetch(self.root, base, env=self.genv)
                job.extra["tip_sha"] = G.rev(self.root, f"refs/remotes/origin/{base}", env=self.genv)
        once("deploy", "deploy", "request", job.repo, job.extra["tip_sha"], [])
        J.move(job, T.DEPLOY_PENDING)


# --- the verbs -----------------------------------------------------------------------------------------------------

def refuse(msg, rc=2):
    print(f"lander: {msg}", file=sys.stderr)
    return rc


def split_opts(argv, *names):
    pos, opts, rest = [], {}, list(argv)
    while rest:
        a = rest.pop(0)
        if a in names and rest:
            opts[a] = rest.pop(0)
        else:
            pos.append(a)
    return pos, opts


def spawn_tick(repo):
    """Start `lander tick --repo <repo>` detached, from this same release. -> (ok, how)."""
    argv = [sys.executable, "-P", os.path.join(J.CORE, "lander", "cli.py"), "tick", "--repo", repo]
    try:
        p = subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        return True, f"pid {p.pid}"
    except OSError as e:
        return False, str(e)


def place(repo, pr):
    ahead = [j for j in J.lane_jobs(repo) if j.pr != int(pr) and j.state not in J.RESTING]
    return f"PR #{pr} waits behind {len(ahead)} job(s) in the {repo} lane" if ahead else ""


def cmd_queue(argv):
    if argv and argv[0] == "--task":
        return queue_task(argv[1:])
    pos, opts = split_opts(argv, "--chat", "--ts", "--who", "--approved-by")
    start = "--no-start" not in pos
    pos = [a for a in pos if a != "--no-start"]
    if len(pos) > 2:
        return refuse(f"queue: unexpected '{pos[2]}'")
    repo, pr = (pos + ["", ""])[:2]
    chat, ts, who, approved_by = (opts.get(k, "") for k in ("--chat", "--ts", "--who", "--approved-by"))
    if not J.REPO_RE.fullmatch(repo or "") or not re.fullmatch(r"[0-9]+", pr or ""):
        return refuse("queue takes <repo> <pr-number> [--chat C --ts T --who name --approved-by U…]")
    handle, mtrack = M.member_of(repo)
    if handle and not mtrack:
        return refuse(f"{repo} is a member workspace — its projects land as <handle>--<track>, never the workspace")
    genv = None
    if handle:
        if not M.member_token(handle):
            E.log("refused", repo, pr, "no-token")
            return refuse(f"{handle} is granted no GitHub token (cc-sandbox github {handle}) — nothing can land for it", 1)
        url, why = M.member_project_url(handle, mtrack, pr)
        if not url:
            E.log("refused", repo, pr, "not-its-repository")
            return refuse(f"PR #{pr} is not queued — {why}", 1)
        root, why = M.member_clone(repo, url)
        if not root:
            E.log("refused", repo, pr, "no-clone")
            return refuse(f"PR #{pr} is not queued — {why}", 1)
        genv = M.env(handle)
    root = J.repo_root(repo)
    token = (genv or {}).get("GH_TOKEN")
    hit, approved_head = protected_hit(repo, root, pr, token, genv), ""
    if hit and not owner_approved(approved_by):
        E.log("refused", repo, pr, f"protected:{hit[0]}")
        cards = load_units().get("cards")
        if cards:
            with contextlib.suppress(Exception):
                cards.stopped(T.Job(repo=repo, pr=int(pr), member=handle or None), hold_words(repo, hit), "door")
        return refuse(f"PR #{pr} is not queued — {hold_words(repo, hit)}. Only the owner's own 👍 on the 🔐 card "
                      f"queues it", 1)
    if hit:
        approved_head = pr_head(root, pr, token, genv)
        if not approved_head:
            E.log("refused", repo, pr, f"protected:{hit[0]}")
            return refuse(f"PR #{pr} is not queued — {hold_words(repo, hit)}, and gh cannot say what head the 👍 "
                          f"is about", 1)
    fresh = J.load(repo, int(pr)) is None
    try:
        if approved_head:
            J.approve(repo, pr, approved_by, approved_head)
        J.submit(repo, pr, chat=chat, ts=ts, who=who)
    except OSError as e:
        return refuse(f"cannot write the request: {e} — nothing merged", 1)
    if fresh:   # a PR with a job already gets `again` or `requeued` from drain; a second `queued` restarts `times`
        E.log("queued", repo, pr, who=who or "-", chat=chat or "-")
    print(f"[{repo}] PR #{pr} queued — its checks run first, then the merge, then the deploy")
    if paused(handle or repo):
        print(f"lander: {handle or repo} is paused — nothing lands until `cc-pause off {handle or repo}`, "
              f"and this request waits for it")
        return 0
    where = place(repo, pr)
    if not start:
        if where:
            print(f"lander: {where}. Nothing was started — `lander tick` is the run it waits for")
        return 0
    ok, how = spawn_tick(repo)
    if not ok:
        return refuse(f"queued, but the lane would not start ({how}) — nothing has merged. `lander tick` runs it", 1)
    print(f"lander: lane started ({how})" + (f"; {where}" if where else ""))
    return 0


def queue_task(argv):
    """Complete a task as the host (`cc done --json`) and queue its PR when `cc lands` grants it; the receipt goes
    to stdout, human output to stderr."""
    if len(argv) != 2 or not all(J.REPO_RE.fullmatch(a) for a in argv):
        return refuse("queue --task takes <repo> <row>")
    repo, row = argv
    rc, out, _ = run([f"{J.bin_dir()}/cc", "done", repo, row, "--json"], timeout=900)
    try:
        rec = json.loads(out)
        if (not isinstance(rec, dict) or not rec.get("task_id") or not isinstance(rec.get("errors"), list)
                or not all(isinstance(e, dict) for e in rec["errors"])
                or not isinstance(rec.get("pending"), dict) or not isinstance(rec.get("pr_url") or "", str)
                or not isinstance(rec.get("card") or {}, dict)):
            raise ValueError("not a completion receipt")
    except ValueError:
        return refuse(f"queue --task needs a task record and a completion receipt for {repo}/{row} (rc {rc})", 1)
    grant = run([f"{J.bin_dir()}/cc", "lands", repo])[0]
    url = rec.get("pr_url")
    pr = re.fullmatch(r"https://[^/\s]+/[^/\s]+/[^/\s]+/pull/([0-9]+)", url or "")
    status, message, result = "approval", "It's waiting for your 👍 on the approval card.", 0
    if grant == 2:
        status, message, result = "refused", ("The repo belongs to a member, so the box won't land it. "
                                              "Someone has to merge it by hand."), 2
    elif grant not in (0, 1):
        status, message, result = ("failed", "Nothing is queued, because the box could not read whether this "
                                             "project lands its own PRs.", 1)
    elif url and not pr:
        status, message, result = "failed", ("Nothing is queued, because the link the worker recorded isn't a "
                                             "GitHub pull request."), 1
    elif not pr or rec.get("closed"):
        status, message = "none", "No PR is open for it, so there is nothing to land."
        result = int(any(e.get("stage") in ("commit", "push", "pr") for e in rec["errors"]))
    elif grant == 0:
        card = rec.get("card") or {}
        args = [f"{repo}--{row}" if M.member_of(repo)[0] else repo, pr[1], "--who", "cc done"]
        if card.get("chat") and card.get("ts"):
            args += ["--chat", card["chat"], "--ts", card["ts"]]
        with contextlib.redirect_stdout(sys.stderr):
            result = cmd_queue(args)
        status = "queued" if result == 0 else "failed"
        message = "It's queued to land, no 👍 needed." if result == 0 else "The PR is open, but the landing queue would not take it."
    rec["landing"] = {"status": status, "message": message}
    if rec.get("pending"):
        E.delivery_pending(repo, row, url or "", list(rec["pending"]))
    print(message, file=sys.stderr)
    print(json.dumps(rec))
    return result


def cmd_lane(argv):
    if len(argv) != 1 or not J.REPO_RE.fullmatch(argv[0]):
        return refuse("lane takes one repo name")
    for ln in Lane(argv[0]).run():
        print(ln)
    return 0


COMMANDS = {
    "queue": (cmd_queue, "put a PR on its repo's lane: <repo|h--t> <pr> [--chat --ts --who --approved-by --no-start]"
                         " | --task <repo> <row>"),
    "lane": (cmd_lane, "run one repo's lane in the foreground: <repo>"),
}
