"""One lane per repo: intake, the job machine (every queued PR's checks side by side), the look at a moved main, the
merge (one at a time) and its tree proof.

    lander queue <repo|h--t> <pr> [--chat C --ts T --who W --approved-by UID --no-start --light]
    lander queue --task <repo> <row>
    lander lane <repo>          run the repo's lane in the foreground (what `queue` and `tick` start), then arm
                                the repo's tick (tick.rearm) for the holds it left

QUEUE is the door (the old cc-land's cmd_queue). It checks the shape; for a member project (`<h>--<t>`) it refuses
the workspace itself and needs the granted token, a repository the board row names under the owner's own account,
and the host-only clone (members.py), each refusal one `refused` line. A PR touching one of the repo's protected
paths (CC_PROTECTED_PATHS_<repo>, cc-config; a config that will not read is a hit) is refused unless --approved-by
is the owner's own uid (SLACK_OWNER_ID): `refused <repo>#<pr> protected:<file>`, the 🔐 card (cards.stopped, route
"door"), exit 1. With his 👍 queue writes the approval record (jobs.approve: his uid and the head gh names — a
head gh cannot name refuses); the inbox request carries no approval, because anyone may write the inbox and drain
takes only chat/ts/who from it. The request goes to the inbox (jobs.submit); `queued` is logged only for a PR
with no job yet (drain logs `again` or `requeued` for the rest, so `times` is not restarted). A paused project keeps the request and says so (exit 0); --no-start
says where it waits (exit 0); otherwise `lander tick --repo <repo>` is started detached (with only an allow-list of
the caller's environment: tick_env), and a start that fails is
exit 1 "queued, but…". `queue --task` is the old queue_task unchanged: `cc done <repo> <row> --json`, `cc lands`
0 queue / 1 approval / 2 refused, anything else failed; the receipt (with `landing`) is the one line on stdout.
`queue --light` also prints whether the PR's paths let it go the light way, naming the path that does not
(light_word); the lane decides it for every PR anyway, asked or not.

THE LIGHT LANE (light.py has who qualifies): at each queued turn of a PR in the repo's own lane, Lane.light() asks
light.why_not (no file on a list the lander guards a landing by) and then reviewer.land_recorded (a LAND recorded at
the head and digest) and keeps the answer in extra["light"]: True (`stage <repo>#<pr> light`, once per head), or
why not. A light job plans only its static and hermetic checks (light.trim, at
planned; a plan that keeps none is not light), goes before every due job but one put first or one whose plan holds a check main is red on, is handed back when a
check is blocked by main (since the ratchet, reds it refused to call main's), moves its base to main without main_moved's re-check when main moves at mergeable and the new base still lets it go
light (the merge's merge-tree still proves it clean; when it does not, main_moved re-checks it as any job and its
full plan's checks the trim left out run before the merge), and is handed back on a conflict with its base found after it was
planned (checking, the merge) instead of a repair round. Everything else (the door, the compiled-file refusal, GitHub CI, the pinned merge and its proof) is as below.

THE LANE (Lane.run) takes <repo>.lock (busy: return — the running lane re-reads), drains the inbox, and steps each
job until it rests (held until not_before, query, done, deploy-pending, handed back) or waits on a check, re-reading
the list after each. CHECKS RUN IN PARALLEL, MERGES ONE AT A TIME (lander-redesign.tex, "Changes that don't overlap
land side by side"; 2026-09-29 a three-file PR waited 7 h behind ~11 half-hour PRs on a box at load 4.8 of 6 cores):
a checking job hands its next check to the lane's pool and the lane goes on to other jobs, and so does a job whose
review read is due (at most LANDER_REVIEW_SLOTS reads at once, as cc-config reads it): a read takes up to READ_TIMEOUT
per reader, and while it ran on
the lane's thread no finished check was recorded and no free slot filled (10-13: 3 of 5 slots free for hours, 39 jobs
checking). Its verdict is acted on at the job's next turn; everything else — the gh facts, planning, the look at a moved main
and the merge — happens on the lane's own thread, so merges stay serial and pinned. Each pass hands the queue to
cards.positions on a thread of its own (Lane.cards_pass), so a slow Slack holds neither; the lane's end waits up to
CARDS_WAIT for those cards. The lane keeps at most
A.slots_now() checks in flight (A.slots(): LANDER_SLOTS from cc-config, else what the host's cores and memory hold,
read again each minute; 2 while the box is overloaded(), 1 under memory pressure) on the box, and up to
A.LAPTOP_SLOTS more on the laptop; each box run still takes its box-wide admission slot, so another repo's lane can
hold this one's check at the door. A job holds one check at a time on the box while another due job wants its first
there (one queued, planned, or checking with none on the box); when none does, its checks the runners
do not take fill every free box slot, but only while run.spill() is quiet (no admission ticket waits, so another
lane's or a worker's check is not pushed back) and never in a member's lane. A job held or handed back
has its other checks in flight stopped. Its checks that may leave the box run on the laptop side by side (any check
that may leave goes there when the lane has no box place for it now, or run.spill() finds every admission slot
held), so a red stops the rest of the suite only once it is recorded (the ones already in flight finish). A
member's lane never sends a check to the laptop. A laptop that gave no answer rests for LAPTOP_REST: the box takes
the lane's checks meanwhile. Where a check may run is the tip of the PR's base branch's word on it (manifest.placed),
not the PR's base. A finished check is recorded on the lane's thread; one whose job left checking, or its head or
base, meanwhile is not.
SMALL FIRST (owner, 2026-09-28: a one-line PR waited behind ~20 full-suite PRs): a free slot goes to the oldest job
that is not heavy — a plan of more than LANDER_SMALL_CHECKS (default 5) checks, or one with a full-suite check
(LANDER_FULL_CHECKS, default check-sh) — and only then to the oldest heavy one; a job not planned yet counts as small,
and so does a heavy one queued LANDER_HEAVY_WAIT seconds ago or more (default 3600: 10-13, #943's 38 checks ran none
for 3 h behind small and parked jobs) until its first check runs; from then on it is heavy again (owner, 09-28: a
one-line PR must not wait behind every aged heavy one). So a small PR waits for at most one check when the box allows
one slot, besides the first check of each heavy PR queued LANDER_HEAVY_WAIT before it, and for none when a slot is
free. NO PR
WAITS MORE THAN A DAY (idea panel, 2026-10-04: #746 sat ~20 h re-queued, unplanned and unexplained): a job queued
LANDER_WAIT_CAP seconds ago or more (default 86400) takes its turn before every younger one, small or heavy, but a
main-red fix (below).
PUT FIRST: a job `queue --first` stamped (jobs.first) goes before all of these, overdue, heavy or not, oldest stamp
first; place() says who put it there. Its checks take a FRONT slot ticket, ahead of every waiter's, and one already
waiting for a slot when it is put first moves up then (admission FIRST CLAIM; dispatch #2026, 10-25: put first, its
check sat 5 h in the slot queue). A new head after a query drops the put-first (queued; perms-c9, 10-26), but the
head the lane's own branch update made (behind) keeps it, at that head.
NOSTART (dispatch #2026, 10-25: a check's gate dir sat 5 h with nothing run in it while the lane checked later PRs): a
check whose current run has not started its process LANDER_NOSTART seconds (default 7200) after it began, a live wait
for a slot aside (run keeps the beat while it polls), is said in queue.log (`nostart`) and stopped, so one stopped
before its slot comes back unrunnable and the job is held and tried again (took), its third time a query naming why.
One stuck before that (its tree written out by a hung git) is only said: nothing there asks the stop.
MAIN-RED FIX FIRST (brief, 10-13: "A PR whose plan includes a check that is red on main, and that is green on the PR,
jumps the queue: it's checked and merged first"): after the jobs put first, a job whose plan holds a check main's
record holds red (health.red, read once per pass; none in a member's lane) goes before every other, overdue or not;
its checks start with those red ones, and every check it runs takes a FIRST CLAIM slot (admission.py; brief, 10-13:
"give main health's checks and a main-red fix's checks first claim on a free slot, ahead of ordinary PR checks, so
health can't starve").
EVERY QUEUED PR AT ONCE (brief, 10-13: "Every queued PR gets its checks planned and run at once on merge-tree(base,
head), up to the slot limit. No PR parks because another PR touches the same files, is held, is conflicted, or shares
only a doc."): a queued job is planned at its turn whatever the other jobs change or wait on; only its own conflict
with main (CONFLICT below) stops it. Each turn of the loop first records the checks that finished, so a freed slot
is seen while queued jobs keep the turn list full, and a job held during the pass has a turn again once its
not_before has passed. BOX HOLDS come first and leave the file untouched and the job untimed:
`cc-pause is <repo or handle>` exit 0 holds everything; `cc-tier allows gates` exit 1 holds jobs before the merge.
  queued     gh facts; MERGED -> merged (by=before); CLOSED -> done; a fork's PR (isCrossRepository: the lane reads
             heads from origin's branches only) -> query; a draft -> held 15 min; a conflict -> CONFLICT
             below (GitHub's CONFLICTING with no file git names -> held 15 min). Under
             the git lock fetch base and head; base_sha, files (merge-base..head), digest (the
             reviewer's digest_of, the key `record` and `will-review` use). A member PR meets its
             walls (-> handback). EVERY lane then refuses a PR that adds or changes a compiled file (__pycache__,
             .pyc, .pyo, .so, .pyd) anywhere, a binary under core/ or bin-private/, an executable binary anywhere,
             or a new or changed symlink
             anywhere but config/system/ (-> handback naming
             them; a list that will not read holds, kind box): the set is
             binaries() of the bin/lander-self committed beside this lander/ (SELF_TOOL, loaded, never copied),
             read in the sealed repo, so the two lanes refuse one set. THE PROTECTED DOOR, asked again at every head,
             reads the approval record
             (jobs.approval, never the request): the owner's uid, and the head he 👍'd — or a later head whose
             protected files are byte-identical, which carries approved_head to it (`approval … carried`); else
             -> query, route "owner". plan(); klass
             lander -> query "lander-self"; then nightly.trim takes out the checks that run nightly instead (not on
             a member's lane). A check main's record holds red stays in the plan, so run.judge's ratchet compares its
             failing cases with main's (10-20: leaving it out of the plan let a new red case land behind main's
             old one). A check main's record holds on this very base tree stands for its base run in run.judge.
  checking   the plan's checks on merge-tree(base_sha, head), made once per base and head (extra tree_of), each
             through runner.run_plan (run.judge: the red-vs-base rule, the rerun alone under load, quarantine, the lane's records.Store under its lock, and the
             failures-ledger record of a red that is the diff's) against the manifest at base widened by the head's —
             a member's on "member:<h>" — skipping those already in results, and those the job's own store
             holds a pass of on this very tree from this release (`stage … reused gate= tree=`). A check the box
             runs on the host itself (manifest.on_host; not on a member's lane) runs only once perms' file records a
             security LAND at exactly this head and digest (review.perms_recorded), or at an older head this head is a clean
             remerge of on the default branch (review.same_change; no other carry; host_unread): the rest
             of the plan runs first, and when only these are left the job is held (box) while perms' read of the PR
             runs (review.perms_reading), else a query "planning" naming them (host_hold; perms' LAND on #1561,
             10-20: a worker that edits a host check's run file selects it, and its head ran as the box's user
             before any read). RE-READ: every RECHECK_SECS while it
             checks, at its next turn after an `again` request, and before its review read is bought (hive#67, 10-23: 2
             full reads of heads a push had replaced), the job reads the PR's state and, only while it is OPEN,
             origin's head (#1925's read: no 120 s ls-remote on the lane thread for a PR that ended); not OPEN or
             a new head -> its checks in flight are stopped (run.execute kills their process groups) and it goes
             back to queued, which ends a merged PR as merged (by=before) and a closed one as done, so no check
             runs on for a PR that already left (10-04: #794 merged at 16:47Z and held 57 jobs behind
             it, still checking, for 40+ min; ai-ee #99 checked a stale head for 50 min). FAILED (a red run.judge
             saw twice on the same tree) -> handback, or queued again when main has moved off base_sha since (#1468:
             a fix main took mid-gate), once per head (extra regated), so a red again on the newer main is handed
             back naming both mains; a red then green passes and logs `flake <repo>#<pr> check=<n>`;
             a red whose failing cases are all red on the base too (run.no_new_reds, the ratchet) passes, with
             `stage … gate ok=ratchet` and a `ratchet <repo>#<pr> check= pr_reds= main_reds=` line naming both sets;
             blocked-by-main (red on the base tree too, and the ratchet would not pass it) -> queued again at once
             when main has moved off base_sha since, else held 15 min and planned again from main then, not blamed;
             extra.main_red keeps since= (its first hold on that check) and main's ids for tick.flag_main_red,
             dropped when the job is planned at a new head;
             a check the manifest lacks -> query "planning"; UNRUNNABLE -> held 15 min, the 3rd -> query, each
             quoting its reason through jobs.quoted (a gate's output line: no control or markup, 200 chars). Then,
             when the plan is paid or a HANDBACK stands on the PR from any head (handed_back(): the job's own, or
             one the box wrote there), one read (a delta read when a prior verdict exists; none when a LAND is already
             recorded at this digest, and on a plan with a security path only while perms' record of it stands,
             landed_at()): INCOMPLETE -> held till the `until` it names (a usage limit's reset; stage
             `deferred`, which no reader counts as running), no read counted; the hold of a usage limit cc-limit has a
             stamp of is marked extra.limit and ends sooner once the limit does (tick.lift_limits, jobs.drain); INCOMPLETE with extra host (a
             read the host failed twice at one head: a 4xx, a timeout, its own cap; or a security path with no
             record by perms of this head and digest) -> query "planning", never a
             handback; HANDBACK ->
             reads_used+1 and a handback, however many reads came before (owner 10-16: no count of reads turns
             it into a query; review.py's dollar ceiling alerts instead); LAND counts a read only when it was bought.
             A member over its day's cap is held; a bought read is charged to it. A read whose job leaves
             checking (or its digest) mid-read keeps its review slot until it ends, and is charged then.
  mergeable  the head moved -> queued. main moved -> main_moved (brief, 10-13: "At merge time, re-check only when
             merge-tree finds a text conflict with current main, or main is red on a check the PR's plan includes.
             Otherwise merge on the verdict it already has."): merge-tree(main, head) conflicts -> CONFLICT below;
             checks of its plan main's record holds red -> checking with only those, each one not in FULL_CHECKS,
             defined at the head as on main, with no file of its run line in the PR, and whose green runs in the queue log all took at
             most EXPRESS_SECS run EXPRESS (EXPRESS_SLOTS lane-wide beside width(), no admission slot, so a
             seconds-long rerun does not queue behind suites; none while A.mem_loaded());
             a re-plan at main read for its class and its read (gates): lander class -> query "lander-self"; paid
             there -> its paid and security carried onto the plan, and with no LAND at this digest (perms' record
             when security is named) -> checking, where review() reads it; the plan is otherwise not adopted and
             adds no rerun (a job no longer light adopts it whole); otherwise base_sha = main, no check run again.
             GITHUB CI comes next (gh.ci_state at the head):
             red -> handback naming each failed check; "starved" (every red is a job GitHub cancelled because no
             hosted runner took it) -> gh.rerun of those runs and held CI_WAIT_SECS, at most STARVED_RERUNS times
             at one head, then handback as red; queued or running -> held CI_WAIT_SECS, the CI_WAITS+1th wait at
             one head a query "planning"; an empty rollup on a base with
             .github/workflows -> held the same way CI_REGISTER_WAITS times, then on as no CI; unreadable -> held,
             the CI_UNREADS+1th at one head a query "planning", but a spent rate limit (GitHub's rate_limit at 0) is held uncounted until its reset; green or no CI at all -> on, but a light FIX (review.light_lane) with no CI is handed back (one not on GitHub with no saved read is a query "planning"). Perms reading the PR
             (review.perms_reading: its read of any head still running, or its perms-hold stub at this head) ->
             held (box), so a read perms started or claimed is waited on; any other read of the PR short of a LAND
             at this head (or an older head's LAND at this change), or perms' reads that will not read -> query
             "planning", so a read that died with no verdict surfaces. THE MERGE (S1),
             all under the git lock: fetch; main_before must be base_sha (else main_moved again); expected =
             merge-tree(main_before, head); merge_attempt {main_before, expected, pin} written BEFORE gh; the squash
             pinned to head (the door made the approved head equal it), --delete-branch, --subject "<title> (#N)";
             fetch; the tip's tree must equal expected, else the tip is `unvalidated` (no deploy request; `stage …
             merged … proof=mismatch`). A refused merge drops merge_attempt; refused with the PR BEHIND its base
             (gh.behind: strict branch protection), the lane updates the branch once per job (gh.update_branch,
             extra behind_update), says so to the repo's seat (cards.behind) and holds CI_WAIT_SECS, so the new head
             is queued again and checked before the one retry; BEHIND again, or an update GitHub refuses, is a
             query "planning". Any other refusal holds, the UNRUNNABLE_TRIES-th a query. One GitHub cannot confirm
             either way keeps it and holds (box). A resume that finds merge_attempt asks GitHub first: MERGED proves
             against the squash commit GitHub names; unreadable holds again, attempt kept; any other state drops it.
  merged     board.close, cards.landed, tip.kick, deploy.request(repo, tip) — each once (job.post flags) —
             then deploy-pending; done (rc=0) for a member or an unvalidated tip. Members never deploy.
  held       past not_before, back to the state it was held from. One held from planned, checking or mergeable
             (no merge_attempt) reads the PR's state, head and base first: not OPEN, a head that is not job.head
             or a base that is not the base_ref it was read on -> queued instead, which ends a closed PR (done rc=1)
             or a merged one (merged, by=before) and starts a new head or base afresh; gh unreadable -> stays held another HOLD_SECS; a GitHub backoff -> waits for it.
CONFLICT (a conflict with the base found at queued, checking, main_moved or the merge; Lane.conflict, repair.py):
repair.start dispatches one rebase round to the PR's own row and the job is held until the branch moves, and a PR nothing will
repair (no row, a member's, ROUNDS rounds failed) is handed back to "planning" (a member's to "#<h>").
HANDBACK writes handed/<repo>-<pr>.json (7 days; after a red check it also names the check and head that were red)
and REMOVES the job file (N12). A re-queue after it is stamped when it came, red or not, at that head or another, so a
red PR goes to the back (jobs.drain); that check green on the retry at the same head logs `flake <repo>#<pr> check=<n>
on=retry`. Only a hold keeps the job's place, and for PLACE_HOLDS holds: the next one stamps it afresh (Lane.hold).
cards.stopped routes it to
"#<h>" or "seat", or the route the caller names. DONE and QUERY move the job file to rest/ (jobs.py): off the readers' queue, as the old lander's
unlink was, but still loaded by a re-queue. A unit that is not installed holds the job ("<unit> is not
installed"); a board unit that is absent is BoardRules below: the row carrying the PR -> merged (an orch-held row
gets a note only; a PR no row carries takes the first row its body Closes that carries no PR and the rules below would close),
each `Closes <row>` of the same board -> done unless held or live without an agent mark, that
mark cleared, an unknown row named; a symlinked board file is refused.

A PROMOTE REACHES A RUNNING LANE between jobs. Before it drains or takes up a job, the lane compares the release
it runs from with what ~/.cc/lander/current names now (jobs.stale_release; a lander run from a checkout never
switches). When they differ it drains no request, plans no job and starts no check, but while the checks and review
reads in flight finish, a checking job whose checks are all recorded and a mergeable or merged one still take their
turns, so one whose checks are done is read and merged meanwhile (dispatch #2121, 10-28: green, read
and adopted, it sat 2 h at stage review while the old lane waited out two full suites at load 58), and a mergeable one
whose base moved waits for the new release to plan it there; once none is in
flight it records the reads (a read's verdict is saved on its job, and a LAND carries to the new lane through landed_at;
10-22: #23's read, dropped at two promotes, was bought again each time), lets the lane lock go, starts `lander lane <repo>` detached from the new release, logs `lane-switch` and
returns. A check in flight finishes on the release it started on; a job partway through its checks keeps its results
and goes on in the new lane. It starts the new lane rather than exec'ing itself because a lane may be running inside
a `tick`, and an exec would drop that tick's tip and deploy pass.

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
import threading
import time
from concurrent import futures

from lander import admission as A
from lander import cards as C
from lander import events as E
from lander import gh as GH
from lander import git as G
from lander import health as HL
from lander import jobs as J
from lander import manifest as MF
from lander import light as LT
from lander import members as M
from lander import nightly as NG
from lander import records as REC
from lander import run as RUN
from lander import types as T

# Perms, after #1298: "EVERY lane refuses __pycache__, .pyc, .pyo, .so, .pyd and NUL-bearing blobs under core/ AND
# bin-private/" — one definition, binaries() of the bin/lander-self in the same tree as this lane.
SELF_TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "lander-self")
_SELF = []


def compiled(root, base, head):
    """The paths `head` adds or changes from merge-base(base, head) that are not source, as SELF_TOOL's binaries()
    names them (a compiled name anywhere; a binary under core/ or bin-private/; an executable binary anywhere; a
    symlink anywhere but config/system/), read in a sealed repo on every PR, since a name alone shows no mode. None
    on any doubt: the tool
    missing or not loading, or a sealed read or list failing."""
    try:
        if not _SELF:
            from importlib.machinery import SourceFileLoader
            import importlib.util as iu
            loader = SourceFileLoader("lander_self_tool", SELF_TOOL)
            mod = iu.module_from_spec(iu.spec_from_loader(loader.name, loader))
            loader.exec_module(mod)
            _SELF.append(mod)
        tool = _SELF[0]
        with G.sealed(root, base, head) as ((rc, out), run):
            if run is None:
                return None
            rc, mb = run("merge-base", *out)
            if rc:
                return None
            env = {**G.blind_env(), "GIT_DIR": run.git_dir}

            def raw(*a):
                p = subprocess.run(["git", *a], cwd=run.git_dir, env=env, capture_output=True,
                                   stdin=subprocess.DEVNULL, timeout=120)
                return p.returncode, p.stdout
            return tool.binaries(root, mb.strip(), out[1], tool.BINARY_ROOTS, run=raw,
                                 peek=tool.git_peek(["git"], cwd=run.git_dir, env=env))
    except Exception:  # noqa: BLE001 — fail closed: a doubt holds the job, it never lets a binary through
        return None


HOLD_SECS = 900          # a held job waits this long before the lane tries it again
UNRUNNABLE_TRIES = 3     # the 3rd unrunnable check (or refused merge) is a query naming its cause and the next step
# owner 10-16: a stop says its reason and the next action in one line, so the planning seat acts on it, never asks
NEXT_UNRUNNABLE = " — next: clear what stops the check on the box (the reason above), then queue the PR again"
NEXT_REFUSED = " — next: clear what GitHub names, then queue the PR again"
HANDED_DAYS = 7
MAX_STEPS = 40
PLACE_HOLDS = 4          # holds a job keeps its queued_at through; the next one stamps it afresh (Lane.hold)
MAIN_RED_WAITS = 4       # holds a main-red job sits out while main and its head stay put, before it tries anyway
MOVES_BEFORE_HOLD = 5    # main moving under the merge this many times in one step holds the job
GH_PR_FILES = 100        # gh lists at most this many files; at or over it git names them all
FIELDS = "state,isDraft,mergeable,headRefOid,headRefName,baseRefName,title,body,isCrossRepository"
PRE_MERGE = (T.QUEUED, T.PLANNED, T.CHECKING)
SMALL_CHECKS = int(os.environ.get("LANDER_SMALL_CHECKS") or 5)   # a plan with more checks than this is heavy
# …and so is a plan with one of these, however few its checks: a count is not a cost, and check-sh is the whole suite
FULL_CHECKS = tuple((os.environ.get("LANDER_FULL_CHECKS") or "check-sh").split())
# EXPRESS: a check a mergeable job reruns only because main moved (main_moved) and that is not one of FULL_CHECKS runs
# at once, beside the box's width() and with no admission slot, at most this many lane-wide (2026-10-02/03: #905 was
# sent back four times for a 0 s core-identity rerun that waited hours behind half-hour suites, while main moved again)
EXPRESS_SLOTS = int(os.environ.get("LANDER_EXPRESS_SLOTS") or 1)
# …and only a check whose every green run in the queue log's last EXPRESS_TAIL bytes took at most this many seconds:
# one with no green run there (a new or renamed check) waits for a slot like any other
EXPRESS_SECS = float(os.environ.get("LANDER_EXPRESS_SECS") or 120)
EXPRESS_TAIL = 1 << 20
# idea panel, 10-04: "no PR waits more than 24 h in a lane without a landing attempt". A job queued this long takes a
# slot first
WAIT_CAP = float(os.environ.get("LANDER_WAIT_CAP") or 86400)
# brief, 10-13: "end the starvation of heavy plans". A heavy job queued this long ago counts as small, so it takes its
# turn in arrival order beside the small ones (#943, 38 checks, ran none for 3 h behind small jobs)
HEAVY_WAIT = float(os.environ.get("LANDER_HEAVY_WAIT") or 3600)
LAPTOP_REST = 300       # seconds the box takes the laptop's checks after the laptop gave no answer
CI_WAIT_SECS = 120       # a head whose GitHub CI is still running is looked at again this often…
CI_WAITS = 30            # …this many times (an hour) before it is a query
CI_REGISTER_WAITS = 2    # waits on a base with workflows but no check yet, before it lands as a repo with no CI
STARVED_RERUNS = 2       # reruns of runs GitHub cancelled for want of a hosted runner, at one head, before red
RECHECK_SECS = float(os.environ.get("LANDER_RECHECK_SECS") or 300)   # a checking job re-reads its PR this often
CI_UNREADS = 4           # holds (HOLD_SECS each: an hour) at one head whose CI GitHub would not show, then a query
CARDS_WAIT = 30          # seconds the lane's end waits for its queued cards (cards_pass); a slower Slack is left
POLL = 5                 # seconds the lane waits on its checks before it looks at the inbox again
NOSTART = float(os.environ.get("LANDER_NOSTART") or 7200)   # a check not started this long after it began is stopped
MODULE_OF = {"planner": "plan", "runner": "run", "reviewer": "review", "cards": "cards", "board": "board",
             "deploy": "deploy", "tip": "tip", "repair": "repair"}


class Flight:
    """One check a job has in the lane's pool, and the head, base and merge tree it was started on."""

    def __init__(self, future, pr, name, head, base, tree, laptop, stop, express=False):
        self.future, self.pr, self.name, self.head, self.base, self.tree = future, pr, name, head, base, tree
        self.laptop = laptop   # sent to the laptop: it counts against LAPTOP_SLOTS, not the box's slots
        self.stop = stop   # a threading.Event; set: run.execute kills the check (the job left this head)
        self.express = express   # a rerun's after main moved (EXPRESS): it counts against EXPRESS_SLOTS, not the box's slots
        self.beat = {"since": time.time()}   # run._beat: when its current run began or last polled for a slot, 0 once
                                             # its process started


class Reading:
    """One review read a job has in the lane's pool, and the digest it reads; seen: its end has woken the job."""

    def __init__(self, future, digest):
        self.future, self.digest, self.seen = future, digest, False


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


def landed_at(job, pv) -> bool:
    """pv, a Verdict's dict, is a LAND at this job's digest the merge may stand on without asking the reviewer again.
    On a plan that names a security path (plan.extra["security"]) it is only while perms' own file records this head
    and digest (review.perms_recorded); a LAND marker alone never is, whoever it names."""
    if not (pv and pv.get("verdict") == T.LAND and pv.get("digest") == job.digest):
        return False
    from lander import review as R
    return not (job.plan and job.plan.extra.get("security")) or R.perms_recorded(job.repo, job.pr, job.head,
                                                                                 {job.digest})


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
            got = G.fetch(root, base, branch, env=genv)
        return G.pr_changed(root, got[base], got[branch], env=genv) or None
    except G.GitError:
        return None


UNLISTED = "gh could not list the PR's files"


def protected_hit(repo, root, pr, token=None, genv=None):
    rules = protected_rules(repo)
    if rules == []:
        return None
    if rules is None:
        return first_hit([], None)
    files = GH.pr_files(root, pr, token)
    if files is None:
        return "?", UNLISTED
    if len(files) >= GH_PR_FILES:
        files = git_pr_files(root, pr, token, genv)
        if files is None:
            return "?", f"gh lists only the first {GH_PR_FILES} files and git could not list the rest"
    return first_hit(files, rules)


def light_word(repo, root, pr, token=None, genv=None) -> str:
    """What `queue --light` prints: whether the PR's paths let it go the light way (light.py), naming the path that
    does not. The LAND it also needs is the lane's to find, at the head it plans."""
    if M.member_of(repo)[0]:
        return f"PR #{pr} goes the normal way: it is a member's PR"
    j = GH.pr_facts(root, pr, "baseRefName,headRefName", token, 60)[0] or {}
    base, branch = (j.get("baseRefName") or "").strip(), (j.get("headRefName") or "").strip()
    try:
        with G.git_lock(root):
            got = G.fetch(root, base, branch, env=genv) if base and branch else {}
        files = G.pr_changed(root, got[base], got[branch], env=genv) if got else []
    except G.GitError:
        got, files = {}, []
    why = LT.why_not(root, got[base], files, protected_rules(repo), MF.host_fallback(repo)) if got \
        else "gh or git could not name its base, head and files"
    return (f"PR #{pr} goes the normal way: {why}" if why
            else f"PR #{pr} goes the light way once a LAND is recorded at its head")


def draft_why(pr) -> str:
    """The why of the hold a draft gets at its queued read. tick's un-draft sweep acts on this hold alone: a PR held
    for anything else that a person turned back into a draft is theirs to mark ready."""
    return f"PR #{pr} is a draft — mark it ready for review"


DRAFT = re.compile(r"PR #\d+ is a draft — ")


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

    def board(self, project):   # a member's board is the link J.board refuses: read its target, no link followed
        return M.member_board(project) if M.member_of(project)[0] else J.board(project)

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
        rows = self.board(project).get("tracks") or {}
        t = self.find_track(project, job) or next(   # a cloud/ PR names its row only in Closes; for close only
            (r for r in closes_rows(job.extra.get("body") or "") if T.closable(rows.get(r)) and not rows[r].get("pr")), "")
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
            if not T.closable(rows[r]):
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


def box_hold(target, job):
    """Why the box holds `job` from its turn ("" when it does not): `target` (the member, else the repo) paused, or a
    spend tier stop for a job not merged yet. The lane says it per turn; the tick's age flag (tick.flag_waited) skips
    a held job, since nothing in the queue is late while the box itself holds it."""
    if paused(target):
        return f"{target} is paused — still queued, lands after `cc-pause off {target}`"
    pre = job.state in PRE_MERGE or (job.state == T.HELD and job.extra.get("held_from", T.QUEUED) in PRE_MERGE)
    if pre and tier_stop():
        return "spend tier stop — still queued, its checks run after `cc-tier set` a wider tier"
    return ""


# --- the lane ------------------------------------------------------------------------------------------------------

class Lane:
    def __init__(self, repo, units=None):
        self.repo = repo
        self.units = load_units() if units is None else dict(units)
        self.units.setdefault("board", BoardRules())
        h, t = M.member_of(repo)
        self.member = h if h and t else ""
        self.root = J.repo_root(repo)
        self.genv = M.env(self.member, repo) if self.member else None
        self.token = M.gh_token(self.member, repo) if self.member else None
        self.fallback = MF.host_fallback(repo)   # the release's landing-repos/<repo>.toml; "" when the repo has none
        self.lines = []
        self.tried = set()
        self.waiting = set()     # tried and waiting on a slot: tried again when one frees
        self.placeless = set()   # waiting with no place for a check, said once in queue.log (no_place) until one has
        self.refused = set()     # tried and refused a turn by a GitHub backoff or a box hold: tried again when it ends
        self.inflight = {}       # (job key, check) -> Flight: every check the lane has in the pool
        self.laptop_down = 0.0   # when the laptop last gave no answer: the box takes its checks for LAPTOP_REST
        self.tips = {}           # {"sha", "m"}: the base branch tip's manifest, for where a check may run
        self.origin = {}         # {branch: sha}: what origin last sent for each branch this lane fetched
        self.reds = set()        # the checks main's record holds red (main_reds), read once per pass of the loop
        self.tried_nb = {}       # job key -> its not_before when it last had its turn: a later one has fallen due
        self.tried_q = {}        # job key -> (queued_at, head) when its turn ended: another is a re-queue or a push
        self.pool = None
        self.moved = ""          # the release `current` moved to while this lane runs: only finishing jobs step
        self.jobs = []           # the lane's jobs as this pass of the loop read them (spare_box)
        self.reading = {}        # job key -> Reading: each review read the lane has in the pool
        self.dropped = []        # reads whose job moved on mid-read: they hold a review slot until they end
        # review reads the lane's pool runs at once (each up to review.READ_TIMEOUT per reader); a job past its checks
        # waits for a place like a check does. LANDER_REVIEW_SLOTS as cc-config reads it, else 1: read from the
        # environment alone, a lane started without it ran one read at a time though ~/.cc/config set 3 (2026-10-22)
        self.review_slots = A.config_slots("LANDER_REVIEW_SLOTS") or 1
        self.carding = None      # the thread posting the queued cards (cards_pass), at most one at a time
        self.carded = None       # what the queue looked like at the last cards pass that went through

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
            moved = ""
            with J.lane_lock(self.repo) as got:
                if not got:
                    self.say("a lane is already running; it re-reads the queue itself")
                    return self.lines
                with contextlib.suppress(OSError, ValueError):   # base runs an earlier lane shared are not reused
                    REC.new_nonce(self.repo, J.landq())
                tried = self.tried = set()
                self.waiting, self.refused, self.inflight, self.placeless = set(), set(), {}, set()
                # as wide as the cores, not today's K: the pool outlives a change of K, which takes no restart
                width = max(A.slots(), os.cpu_count() or 1)
                with futures.ThreadPoolExecutor(max_workers=width + A.LAPTOP_SLOTS + EXPRESS_SLOTS + self.review_slots,
                                                thread_name_prefix="check") as pool:
                    self.pool = pool
                    moved = self.loop(tried)
                self.cards_pass(J.lane_jobs(self.repo), wait=CARDS_WAIT)   # the last edits go out before the lock does
            if moved:   # the lock is let go first, so the lane started from `current` can take it
                mine = os.path.basename(J.running_release())[:12]
                ok, how = spawn_lane(self.repo, moved)
                E.log("lane-switch", self.repo, None, f"{mine}->{os.path.basename(moved)[:12]}: "
                                                      f"{'lane started, ' + how if ok else 'no lane: ' + how}")
                self.say(f"`current` moved from {mine} to {os.path.basename(moved)[:12]}: this lane takes no new "
                         f"job and starts no check, only finishing the jobs whose checks are done; "
                         + (f"a lane on the new release started ({how})" if ok
                                     else f"the new lane would not start ({how}); the next tick starts it"))
                return self.lines
            if not J.requests(self.repo):   # a request that met the held lock after its last drain: once more
                return self.lines

    def loop(self, tried) -> str:
        """Step jobs until none is due and no check is in flight. -> the release `current` moved to, or ''."""
        while True:
            # a promote since the last job: no new job and no new check on this release, and the switch once the checks
            # and reads in flight have finished and been recorded: a read left behind was thrown away, and its job took
            # a place in the next lane to read again (#23, 2026-10-22)
            moved = self.moved = J.stale_release()
            if moved and not self.inflight and all(f.done() for f in self.pending_reads()):
                jobs = J.lane_jobs(self.repo)
                self.drop_reads(jobs)
                for j in jobs:
                    if j.key in self.reading:   # its verdict is saved; a LAND carries to the next lane (landed_at)
                        try:
                            self.review(j)
                        except (UnitFault, G.GitError) as e:
                            self.hold(j, str(e), kind="box", pin=isinstance(e, G.Unpinned))
                return moved
            if any(f.future.done() for f in self.inflight.values()):   # only a look at what has finished, never a wait
                self.reap(0)   # a finished check is recorded (its slot freed) even while queued jobs keep todo full
                continue       # and a promote that came while it ran is seen before any job moves on
            for ln in ([] if moved else J.drain(self.repo)):   # a request waits for the new release to plan it
                self.say(ln)
            moved = self.moved = J.stale_release()   # again: a promote before a request this drain took leaves it queued
            jobs = self.jobs = J.lane_jobs(self.repo)
            self.drop_reads(jobs)
            self.cards_pass(jobs)
            for k, r in self.reading.items():   # a read that has ended gives its job a turn, once
                if r.future.done() and not r.seen:
                    r.seen = True
                    tried.discard(k)
            self.reds = self.main_reds()
            self.nostart()
            for j in jobs:   # a job that has had its turn gets another when (a) it was held since and that hold has
                # run out, (b) it is checking and due a re-read of its PR, waiting or not, unless the box holds it
                # (paused, a tier stop): re-admitted, it would be refused before it read, every pass, unslept, or
                # (c) it was queued again since or has a new head (a push): its queued_at or head differs, or (d) its
                # turn was refused by a backoff or a box
                # hold that has ended: nothing else lets it back while checks run, so it sat silent until the lane
                # process ended. A move or a hold (reap) is no re-queue. A job whose turn ended it (handed back, query, done) left `tried` then,
                # since a re-queue may share its one-second stamp. Without these a re-queue drained in this pass sat
                # in `tried` until the lane process ended (#1226, #1228, #1234)
                if j.key not in tried:
                    continue
                if (j.state == T.HELD and self.due(j) and self.tried_nb.get(j.key) != j.extra.get("not_before")) \
                        or (self.reread_due(j) and not self.box_hold(j)) \
                        or self.tried_q.get(j.key) != self.queued_mark(j) \
                        or (j.key in self.refused and not GH.backoff() and not self.box_hold(j)):
                    tried.discard(j.key)
                    self.refused.discard(j.key)
            todo = [j for j in jobs if j.key not in tried and self.due(j) and (not moved or self.finishing(j))]
            if not todo:   # every due job has had its turn: record what finished (a freed slot), or wait for it
                if not (self.inflight or self.pending_reads() or moved):
                    return ""
                self.reap(POLL)   # the timeout lets a new request in while every check still runs
                continue
            free = self.slot_free()
            # one put first (queue --first), then one whose plan holds a check main's record holds red (brief, 10-13:
            # "A PR whose plan includes a check that is red on main, and that is green on the PR, jumps the queue:
            # it's checked and merged first"), then a job in the lane WAIT_CAP or longer,
            # then the oldest small job (a heavy one queued HEAVY_WAIT or longer ago counts as small until its first
            # check runs), else the oldest heavy one; and of those, while a slot is free, a checking job with a check
            # left first (brief, 10-13: "while a check slot is free and some checking job has a check left to run, the
            # lane starts that check before it spends time replanning queued or parked jobs")
            reds = self.reds
            job = min(todo, key=lambda j: (not J.first(j.repo, j.pr), not (j.plan and set(j.plan.checks) & reds),
                                           j.extra.get("light") is not True,
                                           not self.overdue(j, "queued_at"),
                                           self.heavy(j) and not (self.overdue(j, "queued_at", HEAVY_WAIT)
                                                                  and not self.started(j)),
                                           not (free and self.check_left(j))))
            tried.add(job.key)
            self.tried_nb[job.key] = job.extra.get("not_before")
            self.tried_q[job.key] = self.queued_mark(job)
            why = self.box_hold(job)
            if why:
                self.say(f"PR #{job.pr}: {why}")
                self.refused.add(job.key)
                continue
            before = (job.state, len(job.history), len(self.inflight))
            self.advance(job)
            self.tried_q[job.key] = self.queued_mark(job)   # what its own turn wrote (a plan's head) is no re-queue
            if job.state in J.ENDED:   # it left the lane: only a re-queue brings it back, and that gets a turn
                tried.discard(job.key)
            if (job.state, len(job.history), len(self.inflight)) != before:
                self.wake(but=job.key)   # a job moved or took a slot: whatever waited on it looks again

    def nostart(self):
        """Stop each check whose current run has not started NOSTART seconds after it began; say so once."""
        for (_, n), f in self.inflight.items():
            since = f.beat.get("since") or 0
            if since and time.time() - since >= NOSTART and not f.stop.is_set():
                f.stop.set()
                E.log("nostart", self.repo, f.pr, f"check {n} has not started in {(time.time() - since) / 60:.0f} min; "
                                                  "stopped, and tried again after a hold", check=n)

    def wake(self, but=""):
        """The jobs waiting on a slot or a read look again."""
        self.tried -= self.waiting - {but}
        self.waiting &= {but}

    def main_reds(self) -> set:
        """The checks main's own record holds red (health.red); none in a member's lane, whose main the box's health
        does not run, and none when the record will not read."""
        if self.member:
            return set()
        try:
            return set(HL.red(self.repo))
        except Exception:  # noqa: BLE001 — an unread record orders nothing first, never stops the lane
            return set()

    @staticmethod
    def finishing(job) -> bool:
        """A job whose checks are all recorded, or that is merging: what an old release still takes a turn for while
        a promote waits on the checks in flight (dispatch #2121, 10-28)."""
        return job.state in (T.MERGEABLE, T.MERGED) or (
            job.state == T.CHECKING and bool(job.plan) and all(n in job.results for n in job.plan.checks))

    def check_left(self, job) -> bool:
        """A checking job with a check of its plan neither recorded nor in the pool."""
        return job.state == T.CHECKING and bool(job.plan) and any(
            n not in job.results and (job.key, n) not in self.inflight for n in job.plan.checks)

    def slot_free(self) -> bool:
        """A box slot is free, or a runner's while the laptop is up."""
        return self.room(False) or (bool(RUN.laptop_dest()) and not self.member and self.laptop_up()
                                    and self.room(True))

    def no_place(self, job, check, up):
        """queue.log says once that job's next check has no place now, until one of its checks gets one: the lane's
        own lines go nowhere a person reads, and a PR waiting for a slot looked wedged (dispatch, 10-24/25)."""
        if job.key in self.placeless:
            return
        self.placeless.add(job.key)
        box = sum(1 for f in self.inflight.values() if not f.laptop and not f.express)
        far = sum(1 for f in self.inflight.values() if f.laptop)
        E.log("slot", self.repo, job.pr, "waiting for a place to run a check", check=check,
              box=f"{box}/{self.width()}", laptop=f"{far}/{A.LAPTOP_SLOTS}" if up else "down")

    def width(self) -> int:
        """How many box checks this lane keeps in flight: the admission slots the box allows now."""
        return A.slots_now()

    def room(self, laptop: bool) -> bool:
        """A free place for one more check: on the laptop (LAPTOP_SLOTS), else among the box's width()."""
        n = sum(1 for f in self.inflight.values() if f.laptop == laptop and not f.express)
        return n < (A.LAPTOP_SLOTS if laptop else self.width())

    def express(self, job) -> list:
        """The checks of `job` still to run that go EXPRESS: the ones main_moved named at this very base and head,
        and none while the box is under memory pressure (admission is down to one slot then: parallel checks have
        run it out of memory), so those wait for a slot like any other check."""
        x = job.extra.get("express") or {}
        if x.get("on") != [job.base_sha, job.head] or A.mem_loaded():
            return []
        return list(x.get("checks") or [])

    @staticmethod
    def quick(repo, names) -> list:
        """Of `names`, the checks whose green runs of `repo` in the queue log's tail all took at most EXPRESS_SECS."""
        try:
            with open(E.log_path(), "rb") as f:
                at = max(0, f.seek(0, os.SEEK_END) - EXPRESS_TAIL)
                f.seek(at)
                lines = f.read().decode(errors="replace").splitlines()[1 if at else 0:]   # a cut first line
        except OSError:
            return []
        took = E.lead_times(lines, repo=repo)["gates"]
        return [n for n in names if took.get(n) and max(took[n]) <= EXPRESS_SECS]

    def unchanged(self, job, main_now, names) -> list:
        """Of `names`, the checks `job` runs as main has them: defined the same, in the same manifest, at its head as
        at main_now, and with no file of their run line (MF.run_files) among the PR's own. The times quick() reads are
        kept by name across every PR, so they say nothing of a check this PR redefines or whose script it edits."""
        try:
            base = MF.load(self.root, main_now, fallback=self.fallback)
            head = MF.load(self.root, job.head, fallback=self.fallback, strict=False)
        except (MF.ManifestError, G.GitError):
            return []
        mine = set(job.files or [])
        out = []
        for n in names:
            b, pre = base.checks.get(n), base.cwd.get(n, "")
            if b is None or head.checks.get(n) != b or head.cwd.get(n, "") != pre:
                continue
            ran = [pre + w for w in MF.run_files(b.run)]
            if not any(f == w or f.startswith(w + "/") for f in mine for w in ran):
                out.append(n)
        return out

    def express_room(self) -> bool:
        return sum(1 for f in self.inflight.values() if f.express) < EXPRESS_SLOTS

    def cards_pass(self, jobs, wait=0):
        """Each queued PR's card says where it stands (cards.positions), on a daemon thread of its own: a slow or
        hung Slack holds neither the loop nor a check slot (Opus read, 10-13: "positions() must not hold the lane loop
        on a slow Slack"). One pass at a time: while one runs the queue is not handed over again, and a later pass
        hands over the queue as it is then. A queue unchanged since the last hand-over sends nothing. `wait`: seconds
        the lane's end waits for the cards (CARDS_WAIT), so a PR that just left gets its last edit; a fault is
        logged `unsaid`, never the lane's, and leaves the queue unmarked, so the next pass hands it over again (Opus
        read, 10-13: a faulted pass was not retried until the queue moved). So does a pass whose positions() returns
        False: an edit the box-wide cap or a Slack 429 held goes out on a later pass."""
        if not self.unit("cards"):
            return
        seen = [(j.pr, j.state, j.extra.get("queued_at")) for j in jobs]
        if wait and self.carding:
            self.carding.join(wait)
        if seen == self.carded or (self.carding and self.carding.is_alive()):
            return

        def say():
            try:
                if self.call("cards", "positions", self.repo, jobs) is not False:
                    self.carded = seen
            except UnitFault as e:
                E.log("unsaid", self.repo, None, str(e)[:160])

        self.carding = threading.Thread(target=say, name="cards", daemon=True)
        self.carding.start()
        if wait:
            self.carding.join(wait)

    def laptop_up(self) -> bool:
        return time.time() - self.laptop_down >= LAPTOP_REST

    def reap(self, wait):
        """Record each check the pool has finished (waiting up to `wait` seconds for the first) on the lane's thread;
        the job then goes on at its next turn."""
        # a read already done is not waited on: nothing marks it seen during a promote's wait, so it spun that loop
        pending = [f.future for f in self.inflight.values()] + [f for f in self.pending_reads() if not f.done()]
        if not pending:
            return
        done, _ = futures.wait(pending, timeout=wait, return_when=futures.FIRST_COMPLETED)
        for key, f in list(self.inflight.items()):
            if f.future not in done:
                continue
            del self.inflight[key]
            self.tried.discard(key[0])
            job = J.load(self.repo, f.pr)
            if (job is None or job.state != T.CHECKING or (job.head, job.base_sha) != (f.head, f.base)
                    or f.name in job.results):
                self.say(f"PR #{f.pr}: check {f.name} finished for a head or base the job has left; not recorded")
                continue
            try:
                outs = f.future.result()
                if f.laptop and RUN.laptop_gone(outs):
                    self.laptop_down = time.time()   # it gave no answer: the box takes the next ones for a while
                self.took(job, f, outs)
            except (UnitFault, G.GitError) as e:
                self.hold(job, str(e), kind="box", pin=isinstance(e, G.Unpinned))
        if done:
            self.wake()

    def pending_reads(self) -> list:
        """The futures of the review reads in the pool whose end has not woken their job yet, and of the dropped reads
        still running (the lane waits for them, so each is charged when it ends)."""
        return [r.future for r in self.reading.values() if not r.seen] + [r.future for r in self.dropped]

    def drop_reads(self, jobs):
        """A read whose job has left checking or moved to another digest is dropped (its verdict is on the PR, so a
        later read at that digest finds it and buys none). Opus, 10-13: "Keep a dropped read counted until its future
        is done, and charge it then": it keeps its review slot while it runs, and a member pays for it at its
        end, so a push mid-read does not dodge the day's cap."""
        checking = {j.key: j.digest for j in jobs if j.state == T.CHECKING}
        for k, r in list(self.reading.items()):
            if checking.get(k) != r.digest:
                del self.reading[k]
                self.dropped.append(r)
        for r in [r for r in self.dropped if r.future.done()]:
            self.dropped.remove(r)
            if r.future.exception() is None:   # a reviewer's fault on a read nobody waits for charges nothing
                self.charge(r.future.result())

    def charge(self, v):
        """A member's lane pays for a read that bought tokens."""
        if self.member and v.tokens > 0:
            M.charge(self.member, float(v.extra.get("usd") or 1.0))

    @staticmethod
    def reread_due(job) -> bool:
        """A checking job that has not read its PR in RECHECK_SECS, or that an `again` request named since."""
        return job.state == T.CHECKING and (bool(job.extra.get("reread"))
                                            or time.time() - E.epoch_of(job.extra.get("read_at")) >= RECHECK_SECS)

    def reread(self, job, when="while it was checking") -> bool:
        """Read a checking job's PR state and head (origin's own, as pr_head: headRefOid lags a push). True when the
        job has left checking: the PR merged, closed or has a new head, so its checks in flight are stopped and it is
        queued again (queued() ends or restarts it). An unreadable PR, or a GitHub backoff, leaves it checking and
        reads again in RECHECK_SECS. review() asks it too before it buys a read (hive#67, 10-23: two full reads of
        heads a push had already replaced)."""
        # "A job whose PR already merged must finish as done and unpark its chain. A new head pushed mid-check must
        # cancel the old check." (brief, 2026-10-06)
        job.extra.pop("reread", None)
        job.extra["read_at"] = E.stamp()
        facts = None if GH.backoff() else GH.pr_facts(self.root, job.pr, "state,headRefOid", self.token)[0]
        if facts is None:
            J.save(job)
            return False
        state = facts.get("state") or ""
        # only an open PR's head matters: a merged or closed one leaves checking whatever it points at (#1925)
        head = (G.remote_head(self.root, job.extra.get("branch") or "", env=self.genv) or facts.get("headRefOid") or ""
                if state == "OPEN" else "")
        if state == "OPEN" and (not head or head == job.head):
            J.save(job)
            return False
        self.stop_checks(job)
        why = f"the PR is {state.lower() or 'not open'}" if state != "OPEN" else f"the head moved to {head[:12]}"
        J.move(job, T.QUEUED, why=f"{why} {when}")
        self.say(f"PR #{job.pr}: {why}; its checks in flight are stopped")
        return True

    def stop_checks(self, job):
        """Stop every check `job` has in flight; each is reaped (not recorded) once its process group is gone."""
        for (key, _), f in self.inflight.items():
            if key == job.key:
                f.stop.set()

    @staticmethod
    def queued_mark(job) -> tuple:
        """What only a re-queue or a new head changes: a move or a hold leaves it alone."""
        return str(job.extra.get("queued_at") or ""), job.head

    @staticmethod
    def due(job, now=None):
        """Not at rest, and no hold still running at `now` (the wall clock when None; the tick passes its own)."""
        return job.state not in J.RESTING and not (job.state == T.HELD and J.not_before_left(job, now))

    @staticmethod
    def heavy(job) -> bool:
        """A plan of more than SMALL_CHECKS checks, or one holding a full-suite check (FULL_CHECKS). Not planned
        yet is small: planning is cheap and says which."""
        return bool(job.plan and (len(job.plan.checks) > SMALL_CHECKS
                                  or any(n in FULL_CHECKS for n in job.plan.checks)))

    @staticmethod
    def overdue(job, field, cap=None) -> bool:
        """The stamp in job.extra[field] (queued_at: in the lane) is `cap` (WAIT_CAP) or more ago."""
        at = E.epoch_of(job.extra.get(field) or "")
        return bool(at) and time.time() - at >= (WAIT_CAP if cap is None else cap)

    def started(self, job) -> bool:
        """A check of `job`'s plan has run here: one is recorded or in the pool."""
        return bool(job.results) or any(k[0] == job.key for k in self.inflight)

    def spare_box(self, job) -> bool:
        """A box slot free now is spare for `job`'s second (third…) check: no other due job of this pass wants its
        first one — a queued job, a planned one, or a checking one with a check left to start and none on
        the box. (brief, 10-13: "every free slot runs a pending check"; three of five slots sat free for hours while
        39 jobs were checking, each held to one box check.) Never in a member's lane (perms, 10-13: a member PR ran 3
        checks at once where main runs 1, its tickets ahead of the owner's worker greens), and only while this host
        keeps its own checks (run.spill() says nothing: no admission ticket waits, a slot is free, not overloaded)."""
        if self.member:
            return False
        for j in self.jobs:
            if j.key == job.key or not self.due(j) or j.state == T.HELD:
                continue
            if j.state in (T.QUEUED, T.PLANNED):
                return False
            if j.state == T.CHECKING and j.plan:
                mine = [k for k in self.inflight if k[0] == j.key]
                left = [n for n in j.plan.checks if n not in j.results and (j.key, n) not in self.inflight]
                if left and not any(not self.inflight[k].laptop and not self.inflight[k].express for k in mine):
                    return False
        return not RUN.spill()   # last: it reads the admission slots

    def box_hold(self, job):
        return box_hold(self.member or self.repo, job)

    def advance(self, job):
        if job.state == T.QUEUED:
            E.stage(job.repo, job.pr, "lane")
        for _ in range(MAX_STEPS):
            # after a promote, a job that is no longer finishing (a push or a re-read sent it back, main moved and a
            # check reruns) stops here: the new release plans and checks it
            if not self.due(job) or (self.moved and not self.finishing(job)):
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
            self.refused.add(job.key)
            return
        try:
            steps[job.state](job)
        except (UnitFault, G.GitError) as e:
            self.hold(job, str(e), kind="box", pin=isinstance(e, G.Unpinned))

    # -- leaving the lane --
    def hold(self, job, why, kind="pr", secs=HOLD_SECS, until=0, then=None, deferred=False, pin=False, limit=False):
        """kind "pr": a push mends it (a new queue starts fresh); "box": time mends it (a new queue joins it).
        until: an epoch to wait for instead of secs (a usage limit's reset). then: the state to go back to (default
        the one it was held from). deferred: the job waits on a limit, not on work — stage `deferred`. pin: only a
        pin clears it (G.Unpinned), so the planning seat is told (cards.pin_hold). limit: it waits on a usage limit,
        and is asked again once that limit has gone, whatever `until` said (tick.lift_limits, jobs.drain)."""
        if job.state == T.HELD:
            return
        # perms, 10-13: "after a handback or a main-red hold, the job's other checks keep running for nothing"
        self.stop_checks(job)
        # perms, 10-12: "only the early holds keep the place, and that keep must be bounded": past PLACE_HOLDS holds
        # the place goes, or a job held for days would come back overdue and go ahead of everyone
        holds = int(job.extra.get("holds") or 0) + 1
        if holds > PLACE_HOLDS:
            holds = 0
            job.extra["queued_at"] = E.stamp()
        job.extra["holds"] = holds
        at = until if until > time.time() else time.time() + secs
        job.extra.update(held_from=then or job.state, hold=kind, why=why, not_before=E.stamp(at))
        if deferred:
            job.extra["deferred"] = True
        if limit:
            job.extra["limit"] = True
        J.move(job, T.HELD, why)
        self.say(f"PR #{job.pr} held: {why}")
        if pin:   # on a thread of its own: cc-notify may take its 60 s, and the lane lock is held here
            threading.Thread(target=self.tell_pin, args=(job, why), name="pin").start()

    def tell_pin(self, job, why):
        with contextlib.suppress(UnitFault):
            self.call("cards", "pin_hold", job, why)

    def unhold(self, job):
        target, why = job.extra.get("held_from", T.QUEUED), "retry after hold"
        # "every time a held or handed-back job is looked at again, it re-reads the PR's state and head. Closed or
        # merged means it leaves the queue with one line. A new head means a fresh job" (2026-09-30: a PR sat closed
        # for days, held <-> checking at a head it no longer had). queued() reads GitHub itself; a merge_attempt is
        # mergeable()'s to prove; a deploy-pending job is past the PR.
        if target in (T.PLANNED, T.CHECKING, T.MERGEABLE) and not job.extra.get("merge_attempt"):
            if GH.backoff():
                return self.say(f"PR #{job.pr}: GitHub backoff, {GH.backoff()}s left — tried again after it")
            facts, err = GH.pr_facts(self.root, job.pr, "state,headRefOid,baseRefName", self.token)
            if facts is None:   # unknown is not "unchanged": stay held, and the timer brings it back
                job.extra["not_before"] = E.stamp(time.time() + HOLD_SECS)
                J.save(job)
                return self.say(f"PR #{job.pr} stays held: gh could not read it: {err}")
            state, head = facts.get("state") or "", facts.get("headRefOid") or ""
            base, was = facts.get("baseRefName") or "", job.extra.get("base_ref") or ""
            if state != "OPEN":   # queued() ends it: closed -> done rc=1, merged -> merged by=before
                target, why = T.QUEUED, f"retry after hold: the PR is {state.lower() or 'not open'}"
            elif head and head != job.head:
                target, why = T.QUEUED, f"retry after hold: the head moved to {head[:12]}"
            elif base and was and base != was:   # retargeted: its base_sha, files and results were read on `was`
                target, why = T.QUEUED, f"retry after hold: the base moved from {was} to {base}"
        if job.extra.get("hold") == "box":   # tick.flag_waited counts the job's age from here (perms' read, 10-13)
            job.extra["unheld_at"] = E.stamp()
        job.extra["last_hold"] = job.extra.get("hold")   # queued() reads whose hold a later draft followed
        for k in ("held_from", "hold", "not_before", "deferred", "limit"):
            job.extra.pop(k, None)
        J.move(job, target if target in J.NEXT[T.HELD] else T.QUEUED, why=why)

    def stopped(self, job, why, route):
        if self.unit("cards"):
            with contextlib.suppress(UnitFault):
                self.call("cards", "stopped", job, why, route)

    def query(self, job, why, route):
        job.extra["why"] = why
        J.move(job, T.QUERY, why)
        self.stopped(job, why, route)
        self.say(f"PR #{job.pr} is a query for {route}: {why}")

    def conflict(self, job, paths):
        """`job` conflicts with its base in `paths` (repair.py has the round). The repair unit answers: a round
        launched or running holds the job; nothing that will repair it hands it back to the planning seat (a member's
        to its own channel) with one message, and a push to the branch re-queues it."""
        base = job.extra.get("base_ref") or "main"
        why = f"PR #{job.pr} conflicts with {base}: {J.path_names(paths)}"   # a path is the branch's: shown clean
        # brief 10-13: "If it can't merge cleanly, hand it back. Don't park it." A queued job's flag is an older head's
        if job.extra.get("light") is True and job.state != T.QUEUED:
            return self.handback(job, f"{why} — rebase it and queue it again")
        if not self.unit("repair"):
            return self.hold(job, f"{why} — rebase it")
        kind, words = self.call("repair", "start", self, job, paths)
        if kind == "planning":
            return self.handback(job, f"{why} — {words}", route=M.route(job) or "planning")
        self.hold(job, f"{why} — {words}")

    def handback(self, job, why, route=""):
        now = time.time()
        J.write_atomic(J.handed_path(job.repo, job.pr), {
            "repo": job.repo, "pr": job.pr, "head": job.head, "branch": job.extra.get("branch") or "",
            "since": E.stamp(now), "until": E.stamp(now + HANDED_DAYS * 86400), "reads_used": job.reads_used,
            "verdict": job.extra.get("verdict") or {}, "why": why, "chat": job.extra.get("chat") or "",
            "ts": job.extra.get("ts") or "", "red": job.extra.get("red") or {}})
        job.extra["why"] = why
        self.stop_checks(job)   # perms, 10-13: a red's sibling checks would run on for nothing
        J.move(job, T.HANDBACK, why)
        J.remove(job)
        self.stopped(job, why, route or M.route(job) or "seat")
        E.log("handed", job.repo, job.pr, f"head={job.head[:12]} — a push to {job.extra.get('branch') or '?'} "
                                          f"re-queues it (watched {HANDED_DAYS} days)")
        self.say(f"PR #{job.pr} handed back: {why}")

    # -- the states --
    def lock(self):
        return G.git_lock(self.root)

    def fetch(self, *branches):
        """G.fetch's {branch: sha}, kept for tip_manifest: never refs/remotes/origin/<b>, which a worker can move."""
        got = G.fetch(self.root, *branches, env=self.genv)
        self.origin.update(got)
        return got

    def queued(self, job):
        facts, why = GH.pr_facts(self.root, job.pr, FIELDS, self.token)
        if facts is None:
            return self.hold(job, f"gh could not read PR #{job.pr}: {why}", kind="box")
        base, branch = facts.get("baseRefName") or "", facts.get("headRefName") or ""
        job.extra.update(title=facts.get("title") or "", body=facts.get("body") or "", branch=branch, base_ref=base)
        job.extra["read_at"] = E.stamp()   # what a checking job's re-read counts RECHECK_SECS from
        job.extra.pop("reread", None)
        state = facts.get("state") or ""
        if state == "MERGED":
            job.head = facts.get("headRefOid") or job.head
            return J.move(job, T.MERGED, why="merged before the lane got to it", by="before")
        if state == "CLOSED":
            J.move(job, T.DONE, why="the PR is closed")
            return E.log("done", job.repo, job.pr, rc=1)
        if facts.get("isCrossRepository"):
            # perms on #1925: the lane reads a head from origin's branch of that name, so a fork's PR whose branch
            # name origin also has was checked at origin's head, then queued again at every pass as "moved". A
            # query rests: a handback's push watch reads origin's branch too, and would re-queue it each tick
            return self.query(job, f"PR #{job.pr} comes from a fork, and the lane checks and merges only branches "
                                   f"on this repo: push {branch or 'it'} here and open the PR from that",
                              M.route(job) or "seat")
        if facts.get("isDraft"):
            # held for something of the PR's own (not the box's), then drafted: a person did that, and the hold's
            # why stays out of DRAFT so tick's un-draft sweep leaves it theirs
            prev = job.extra.get("why") or ""
            if prev and not DRAFT.match(prev) and job.extra.get("last_hold") == "pr":
                return self.hold(job, f"PR #{job.pr} was turned back into a draft — mark it ready for review")
            return self.hold(job, draft_why(job.pr))
        if facts.get("mergeable") == "CONFLICTING":
            # GitHub names no files: the merge-tree of what origin sends does, and an empty answer is GitHub's
            # word against git's — held as before, and read again at the next wake
            with self.lock():
                got = self.fetch(base, branch)
                job.base_sha, job.head = got[base], got[branch]
                job.files = G.pr_changed(self.root, job.base_sha, job.head, env=self.genv)
                _, paths = G.merge_tree(self.root, job.base_sha, job.head, env=self.genv)
            if not paths:
                return self.hold(job, f"PR #{job.pr} conflicts with {base} — rebase it")
            return self.conflict(job, paths)
        with self.lock():
            got = self.fetch(base, branch)
            job.base_sha, job.head = got[base], got[branch]
        put, moved = J.first(job.repo, job.pr), (job.extra.get("behind_update") or {}).get("from")
        if put.get("head") and put["head"] == moved and self.base_merge(job.head, moved, job.base_sha):
            # the lane's own update moved it: GitHub's merge of the base sits on the head put first, and nothing on top
            # (#1982 review: a merge whose second parent is not on the base is an author's, so it drops the put-first)
            J.write_atomic(J.first_path(job.repo, job.pr), {**put, "head": job.head})
        elif put.get("head") not in (None, job.head):   # put first, queried, then pushed (first)
            J.drop_first(job.repo, job.pr)
        mr = job.extra.get("main_red")
        if isinstance(mr, dict) and mr.get("head") != job.head:
            # a new head is planned against current main, so the old head's hold, its since= and its alert are moot
            # (#2107: a merge of main into the branch left the old head's record alerting for 3 h)
            job.extra.pop("main_red")
        elif isinstance(mr, dict) and mr.get("base") == job.base_sha and int(mr.get("waits") or 0) < MAIN_RED_WAITS:
            # main was red on a check and neither main nor the head has moved: no checks, held again (hold() saves
            # job.extra, so the count carries to the next pass)
            mr["waits"] = int(mr.get("waits") or 0) + 1
            return self.hold(job, f"main-red: {base} has not moved since check {mr.get('check')} was red on it "
                                  f"(wait {mr['waits']} of {MAIN_RED_WAITS})", kind="box")
        job.files = G.pr_changed(self.root, job.base_sha, job.head, env=self.genv)
        # the reviewer's digest_of, the key `record` and `will-review` use: a LAND recorded at a head is the verdict
        # the lane finds at that head (#739 was handed back at the read cap under a patch-id key of the lane's own)
        job.digest = self.call("reviewer", "digest_of", self.root, job.base_sha, job.head) \
            if self.unit("reviewer") else ""
        job.results, job.plan = {}, None
        job.extra.pop("tree", None)
        job.extra.pop("tree_of", None)
        if self.member:
            why = M.walls(self.root, job.base_sha, job.head, job.files, self.genv)
            if why:
                return self.handback(job, why)
        bins = compiled(self.root, job.base_sha, job.head)
        if bins is None:
            return self.hold(job, "the lander could not read whether the PR adds a compiled file", kind="box")
        if bins:
            return self.handback(job, f"it adds {len(bins)} file(s) that are not source — compiled anywhere, a "
                                      f"binary under core/ or bin-private/, an executable binary anywhere, or a "
                                      f"symlink outside config/system/ "
                                      f"({', '.join(bins[:8])}); "
                                      "these could run in place of the source that was read, so take them out of "
                                      "the PR")
        why = self.door(job)
        if why:
            return self.query(job, why, "owner")
        # brief, 10-13: "Every queued PR gets its checks planned and run at once on merge-tree(base, head), up to the
        # slot limit. No PR parks because another PR touches the same files, is held, is conflicted, or shares only a
        # doc."
        self.light(job)   # extra["light"] at this head: planned() trims a light job's plan
        if not self.unit("planner"):
            return self.hold(job, "planner is not installed", kind="box")
        job.plan = self.call("planner", "plan", self.root, job.base_sha, job.head, job.files, fallback=self.fallback)
        if job.plan.klass == T.LANDER:
            return self.query(job, "it changes the lander itself — lander-self lands it", "lander-self")
        job.plan = self.nightly(job.base_sha, job.plan)
        J.move(job, T.PLANNED)

    def nightly(self, base, plan):
        """`plan` (planned on `base`) without the checks nightly.py runs nightly instead; a member's lane, or a
        manifest that does not load, keeps every check."""
        if self.member:
            return plan
        try:
            return NG.trim(self.repo, MF.load(self.root, base, fallback=self.fallback), plan)
        except Exception:  # noqa: BLE001 — any fault runs every check, never the wrong answer
            return plan

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

    def light(self, job) -> bool:
        """Whether `job` at this head goes the light way (light.py), kept in job.extra["light"]: True, or the reason
        it does not. Asked at every queued turn, since a new head or a newly recorded LAND changes the answer."""
        why = "it is a member's PR" if self.member else LT.why_not(self.root, job.base_sha, job.files,
                                                                    protected_rules(self.repo), self.fallback)
        if not why:
            try:   # a reader that fails is the normal lane, never a hold
                land = self.call("reviewer", "land_recorded", job) if self.unit("reviewer") else None
            except Exception:  # noqa: BLE001
                land = None
            why = "" if land is not None and land.verdict == T.LAND else "no LAND is recorded at its head"
        was = job.extra.get("light")
        job.extra["light"] = why or True
        if not why and was is not True:
            E.stage(job.repo, job.pr, "light", head=job.head[:12])
        return not why

    def planned(self, job):
        if job.extra.get("light") is True:   # brief 10-13: "the PR's static and hermetic checks"
            wide = LT.widened(job.plan) if job.plan else ""
            kept = LT.trim(self.manifest(job), job.plan) if job.plan and not wide else None
            if wide:   # Opus read of #1316: "a plan of klass T.WIDE, or any widening entry in unowned, is not light"
                job.extra["light"] = wide
            elif kept is not None and kept.checks:
                job.plan = kept
            else:   # security read of #1316: "a trimmed plan that comes out empty means the PR isn't light"
                job.extra["light"] = "its plan keeps no static or hermetic check"
        J.move(job, T.CHECKING)

    def manifest(self, job):
        """The manifest at base, widened by the head's less the checks main retired since the head branched (MF.fork;
        what plan() planned on and `lander check` runs by), with each
        check's `where` from the tip of the base branch (MF.placed): a PR based before main let a check leave the box
        still sends it (2026-09-29, #800 waited hours on ten box-only host checks main had let go)."""
        try:
            m = MF.widen(MF.load(self.root, job.base_sha, fallback=self.fallback),
                         MF.load(self.root, job.head, fallback=self.fallback, strict=False),
                         since=MF.fork(self.root, job.base_sha, job.head, self.fallback))
        except MF.ManifestError as e:
            raise UnitFault(f"the manifest at {job.base_sha[:12]} does not parse: {e}") from None
        tip = self.tip_manifest(job.extra.get("base_ref") or "main")
        return MF.placed(m, tip) if tip is not None else m

    def tip_manifest(self, base: str):
        """The manifest at the tip origin last sent for <base>, read once per tip; None when there is none yet or it
        cannot be read (m keeps its own `where`, as before)."""
        sha = self.origin.get(base)
        if not sha:
            return None
        if self.tips.get("sha") != sha:
            try:
                self.tips = {"sha": sha, "m": MF.load(self.root, sha, fallback=self.fallback)}
            except (MF.ManifestError, G.GitError):
                self.tips = {"sha": sha, "m": None}
        return self.tips["m"]

    def checking(self, job):
        """Hand the job's next check to the pool (when the lane has a slot for it), or, when the plan is paid or a
        handback stands, go on to the review and the merge. The check's outcome is recorded by took(), on the lane's
        thread."""
        if not self.unit("runner"):
            return self.hold(job, "runner is not installed", kind="box")
        if self.reread_due(job) and self.reread(job):
            return None
        todo = [n for n in (job.plan.checks if job.plan else []) if n not in job.results]
        red = (job.extra.get("main_red") or {}).get("check")
        # the check main was red on goes first (while main is still red, one check says so), then any check main's
        # record holds red now: a main-red fix proves its fix before the rest of its plan
        todo.sort(key=lambda n: (n != red, n not in self.reds))
        if todo and self.moved:   # a promote: the lane on the new release runs it
            self.waiting.add(job.key)
            return None
        if todo:
            # the laptop's slots first (every check of the plan that may leave the box, several PRs' at once), the
            # box's beside them (one check per job there); a check waits only for a place of its own kind
            todo = [n for n in todo if (job.key, n) not in self.inflight]
            dest = bool(RUN.laptop_dest()) and not self.member
            up = dest and self.laptop_up()
            kw = {"box_only": True} if dest else {}   # a box slot's check stays on the box, not a wait on ssh
            fast = [n for n in todo if n in self.express(job)]
            if not todo or not (self.room(False) or (up and self.room(True)) or (fast and self.express_room())):
                if todo:
                    self.no_place(job, todo[0], up)
                self.waiting.add(job.key)    # it goes on when a check finishes and frees a slot
                return None
            m = self.manifest(job)
            pair = [job.base_sha, job.head]
            if job.extra.get("tree") and job.extra.get("tree_of") == pair:
                # the merge this job already made of this very base and head: merge_tree builds a sealed copy under
                # the git lock (seconds), and run.materialise proves the tree by write-tree whatever the checkout holds
                tree, conflicts = job.extra["tree"], []
            else:
                with self.lock():
                    tree, conflicts = G.merge_tree(self.root, job.base_sha, job.head, env=self.genv)
            if tree is None:
                return self.conflict(job, conflicts)
            base_tree = G.tree_of(self.root, job.base_sha, env=self.genv)
            if job.extra.get("tree") != tree or job.extra.get("tree_of") != pair:
                job.extra.update(tree=tree, tree_of=pair)
                J.save(job)
            store = REC.Store(self.repo, J.lane_fd(self.repo), J.landq()) if J.lane_fd(self.repo) is not None else None
            # brief: "a check that passed on the same tree hash doesn't run again for the same PR" — the job's own
            # store outlives a requeue (a hold for a red main, a push that merges to the same tree)
            again = [n for n in todo if store is not None and self.passed(store, job, n, tree)]
            if again:
                if not [n for n in todo if n not in again] and not any(k[0] == job.key for k in self.inflight):
                    return self.checking(job)
                todo = [n for n in todo if n not in again]
            held = self.host_unread(job, m, todo)
            if held:   # the rest of the plan runs first; these wait for perms' LAND at this head (host_hold)
                todo = [n for n in todo if n not in held]
                if not todo:
                    if any(k[0] == job.key for k in self.inflight):
                        self.waiting.add(job.key)
                        return None
                    return self.host_hold(job, held)
            quarantine = RUN.quarantine_text(self.root, job.base_sha)
            main = {} if self.member else HL.at(self.repo, base_tree)   # main's own record on this base (health.py)
            # brief, 10-13: "give main health's checks and a main-red fix's checks first claim on a free slot, ahead of
            # ordinary PR checks, so health can't starve": a job whose plan holds a check main is red on
            fix, repo, pr = bool(set(job.plan.checks) & self.reds), job.repo, job.pr

            def first():   # asked by admission each poll: put first while it waits, the check moves up to the front
                return A.FRONT if J.first(repo, pr) else fix
            for n in todo:
                c = MF.builtin_check() if n == MF.BUILTIN else m.checks.get(n)
                express = n in fast and self.express_room()
                box = self.room(False) and not any(k[0] == job.key and not f.laptop for k, f in self.inflight.items())
                if express:   # EXPRESS: on the box (or the member's sandbox) now, no slot, no ssh to wait out
                    laptop = False
                elif up and c is not None and RUN.may_leave(c) and self.room(True) and (not box or RUN.spill()):
                    # brief: "send checks to any registered runner that has free slots ... instead of waiting for a
                    # box slot". The runners when this host has no place for it now: the lane's box places are
                    # taken, the job holds its one, or every admission slot is (run.spill; #772 waited 8-30 min a
                    # check on a box cut to 1-2 slots while the laptop answered `free 6`)
                    laptop = True
                elif box or (self.room(False) and self.spare_box(job)):
                    # the box, one check per job at a time while another job waits for its first (so an older heavy
                    # PR does not take every box slot), and as many as are free when none does (spare_box) and the
                    # runners will not take them; a check that may leave runs here too when the laptop is full or
                    # resting and the box has room
                    laptop = False
                else:
                    if not self.room(False):   # not the one box check per job: the lane's box places are all taken
                        self.no_place(job, n, up)
                    continue   # no place of either kind for it now: tried again when a check finishes
                self.placeless.discard(job.key)
                stop = threading.Event()
                flight = Flight(None, job.pr, n, job.head, job.base_sha, tree, laptop, stop, express)
                fut = self.pool.submit(self.call, "runner", "run_plan", self.root, m, job.plan, job.files, tree,
                                       base_tree, member=self.member, store=store, job_key=job.key,
                                       scope=self.member or self.repo, pr=job.pr, quarantine_text=quarantine,
                                       only=[n], fallback=self.fallback, cancel=stop, lane=True,
                                       **({"runners": True} if laptop else kw),
                                       **({"express": True} if express else {}), **({"main": main} if main else {}),
                                       first=first, beat=flight.beat)
                flight.future = fut
                self.inflight[(job.key, n)] = flight
            self.waiting.add(job.key)   # submitted or not, it goes on when a check finishes and frees a slot
            return None
        # a handback standing from an earlier head is read again even off the paid paths: #1064's security handback
        # "was tied to the old head and nothing carried it forward or asked for a new read"
        # (a read already in the pool is waited on, with no new look at the PR's comments)
        if (job.key in self.reading or (job.plan and job.plan.paid) or self.handed_back(job)) \
                and not self.review(job):
            return None
        J.move(job, T.MERGEABLE)

    def host_unread(self, job, m, todo) -> list:
        """The checks of `todo` the box runs on the host itself (MF.on_host) while perms' file records no security
        LAND at exactly this head and digest (review.perms_recorded), or at an older head this head is a clean remerge
        of on the default branch at its tip (review.same_change; no other carry), else []. Such a
        check runs the head's code as the box's user, outside the bwrap profile, and a head is code a worker wrote
        (perms' LAND on #1561, 10-20: a worker that edits a host check's run file selects that check, so the head ran
        on the host before any read). A member's lane runs every check in the member's sandbox: none is held."""
        if self.member:
            return []
        names = [n for n in todo if n != MF.BUILTIN and m.checks.get(n) is not None and MF.on_host(m.checks[n])]
        if not names:
            return []
        from lander import review as R
        return [] if R.perms_recorded(job.repo, job.pr, job.head, {job.digest}) or R.same_change(job) else names

    def host_hold(self, job, held):
        """Every other check of the plan has passed and `held` (host_unread) is left: held (box) while perms' read of
        the PR runs or its perms-hold stub stands at this head (review.perms_reading), else a query "planning", which
        asks perms for its read, or, when that read at this head finished LAND but is not in perms' ledger, for its
        perms-adopt (perms-read would start nothing). Its LAND at this head re-queues the job (review.requeue_held, or the tick's
        `landed` sweep for a LAND written into the ledger by hand)."""
        from lander import review as R
        names = ", ".join(held)
        why = (f"{names} run{'s' if len(held) == 1 else ''} the head's code on the host, so "
               f"{'it waits' if len(held) == 1 else 'they wait'} for perms' security LAND at {job.head[:12]}")
        reading, wait = R.perms_reading(job.repo, job.pr, job.head, job.digest)
        if reading and wait:
            return self.hold(job, f"{why}: {reading}", kind="box")
        at, _ = R.load_read(job.repo, job.pr, job.head)
        verb = "perms-adopt" if at and at.get("state") == "done" and at.get("verdict") == T.LAND else "perms-read"
        olds = R.land_heads(job) if verb == "perms-read" else []
        since = f" --since {olds[-1]}" if olds else ""   # perms reads only the change since its last LAND
        job.extra["host_hold"] = job.head
        return self.query(job, f"{why} (lander {verb} {job.repo} {job.pr}{since})"
                               + (f": {reading}" if reading else ""), "planning")

    def handed_back(self, job):
        """True when a HANDBACK stands on the PR: the job's own last read, or the newest verdict the box wrote there
        (a seat's `lander record`). A PR whose comments cannot be read raises, so the job is held, never merged."""
        pv = job.extra.get("verdict")
        if isinstance(pv, dict) and pv.get("verdict") == T.HANDBACK_VERDICT:
            return True
        return bool(self.unit("reviewer") and self.call("reviewer", "standing", job))

    def passed(self, store, job, n, tree) -> bool:
        """True, with the pass kept in job.results and a `reused` stage line, when this job's own store holds a pass of
        check n on this very tree from this release."""
        r = store.get(job.key, n, tree)
        if r is None or r.status != T.PASSED or r.tree != tree or r.check != n or r.release != store.release:
            return False
        E.stage(job.repo, job.pr, "reused", gate=n, tree=tree[:12])
        job.results[n] = r.key
        J.save(job)
        return True

    def took(self, job, f, outs):
        """Record one finished check of `job` (f: its Flight): red hands back, main-red holds (a light job hands back),
        else it is kept."""
        n, tree, base_ref = f.name, f.tree, job.extra.get("base_ref") or "main"
        o = outs.get(n) or RUN.Outcome(n, T.UNRUNNABLE, "the runner gave no outcome")
        secs = int(sum(r.secs for r in o.results))
        ratchet = o.status == T.PASSED and o.note.startswith("ratchet")
        word = "ratchet" if ratchet else {T.PASSED: "yes", RUN.BLOCKED: "main-red"}.get(o.status, "no")
        E.stage(job.repo, job.pr, "gate", gate=n, ok=word, secs=secs, note=o.note if o.status == T.PASSED else "")
        if ratchet:   # brief: "logged as ok=ratchet with both sets"
            E.log("ratchet", job.repo, job.pr, check=n, head=job.head[:12], base=job.base_sha[:12],
                  pr_reds=";".join(o.sets.get("pr") or []), main_reds=";".join(o.sets.get("main") or []))
        if o.status == T.PASSED and o.note.startswith("flaky"):   # "the flake is logged with the check's name"
            E.log("flake", job.repo, job.pr, check=n, head=job.head[:12])
        retry = job.extra.get("retry")
        if o.status == T.PASSED and isinstance(retry, dict) and retry.get("check") == n \
                and retry.get("head") == job.head:   # red twice at this head before it was handed back, green now
            E.log("flake", job.repo, job.pr, check=n, head=job.head[:12], on="retry")
            job.extra.pop("retry")
        if o.status == T.FAILED:
            # #1468 (10-20): the gate ran on the main of its queueing, and a fix main took meanwhile turned the red
            # into a handback; a red is the PR's only on the main it would merge into, so a moved main gates it again,
            # once per head: a red again on the newer main is the PR's own (main moves faster than a gate runs)
            regated = job.extra.get("regated") if isinstance(job.extra.get("regated"), dict) else {}
            if regated.get("head") != job.head:
                with self.lock():
                    now = self.fetch(base_ref)[base_ref]
                if now != job.base_sha:
                    self.stop_checks(job)
                    job.extra["regated"] = {"head": job.head, "main": job.base_sha}
                    return J.move(job, T.QUEUED, why=f"check {n} failed on {base_ref} {job.base_sha[:12]}, which "
                                                     f"has moved to {now[:12]}: gated again on it")
            # the handed record names it, so a green on the retry at this head is a flake
            job.extra["red"] = {"check": n, "head": job.head}
            again = (f", red on {(regated.get('main') or '')[:12]} and again on {job.base_sha[:12]}"
                     if regated.get("head") == job.head else "")
            return self.handback(job, f"check {n} failed on the merge with {base_ref} ({tree[:12]}{again})"
                                      + (f": {J.quoted(o.note)}" if o.note else ""))   # a gate's line
        if o.status == RUN.BLOCKED and job.extra.get("light") is True:
            # security read of #1316: since the ratchet, blocked-by-main means reds it refused (a security check, a
            # check the PR touches, new failing cases), so a light job hands back; it is never kept and merged
            return self.handback(job, f"check {n} is red on the merge with {base_ref} ({tree[:12]}) and the ratchet "
                                      f"would not call it main's, so the light lane hands it back"
                                      + (f": {J.quoted(o.note)}" if o.note else ""))
        if o.status == RUN.BLOCKED:
            # since: when this check first held this job, kept while it holds it again, for tick.flag_main_red's
            # hour; base and fails: this newest judge's, which that alert names, also when main has moved and it is
            # queued again below (10-26: the alert for #1952 named its first hold's base while main was red on a newer)
            mr = job.extra.get("main_red") if isinstance(job.extra.get("main_red"), dict) else {}
            since = mr.get("since") if mr.get("check") == n and mr.get("since") else E.stamp()
            job.extra["main_red"] = {"check": n, "base": job.base_sha, "head": job.head, "waits": 0, "since": since,
                                     "fails": (o.sets.get("main") or [])[:20]}
            # as a red at #1468: a red on a main that has moved since says nothing of the main it would merge into, so
            # it is planned again there now, not held on the old one (read of #1966)
            with self.lock():
                now = self.fetch(base_ref)[base_ref]
            if now != job.base_sha:
                self.stop_checks(job)
                return J.move(job, T.QUEUED, why=f"check {n} is red on {base_ref} {job.base_sha[:12]}, which has "
                                                 f"moved to {now[:12]}: gated again on it")
            # design §0: base red too -> blocked-by-main, not blamed; it is planned again from main after the hold
            return self.hold(job, f"{o.note}: check {n} is red on {base_ref} ({job.base_sha[:12]}) too, so it "
                                  f"is main's, not this PR's — tried again from {base_ref} later",
                             kind="box", then=T.QUEUED)
        if o.status == T.UNRUNNABLE and o.note == "not in the manifest":
            return self.query(job, f"the plan names checks the manifest at base lacks: {n}", "planning")
        if o.status == T.UNRUNNABLE:
            job.extra["attempts"] = int(job.extra.get("attempts") or 0) + 1
            note = J.quoted(o.note)   # the note can quote a gate's own output line: shown clean and cut short
            if job.extra["attempts"] >= UNRUNNABLE_TRIES:
                # the last try's reason goes with the query: "could not run 3 times" alone sent a full /tmp to
                # planning as a mystery (#1087, 2026-10-11), its cause left in the hold history and a gone log
                return self.query(job, f"check {n} could not run {UNRUNNABLE_TRIES} times"
                                       + (f": {note}" if note else "") + NEXT_UNRUNNABLE, "planning")
            return self.hold(job, f"check {n} could not run (try {job.extra['attempts']} of "
                                  f"{UNRUNNABLE_TRIES}): {note}", kind="box")
        if (job.extra.get("main_red") or {}).get("check") == n:
            job.extra.pop("main_red", None)   # the check main was red on passes: main is green on it again
        job.results[n] = o.results[0].key if o.results else ""
        J.save(job)
        return None

    def review(self, job):
        """True when the job may go on to the merge; otherwise its read is in the pool (the job waits for it, as for a
        check) or it has been held, handed back or queried."""
        prior = job.extra.get("verdict")
        pv = T.Verdict.from_dict(prior) if isinstance(prior, dict) and prior else None
        if pv and landed_at(job, pv.to_dict()):
            return True   # a LAND already read at this very digest (a rerun after main moved): no second read
        if not self.unit("reviewer"):
            self.hold(job, "reviewer is not installed", kind="box")
            return False
        if self.member:
            usd, cap = M.spent(self.member)
            if usd >= cap:
                self.hold(job, f"{self.member} has spent its day's review cap (${usd:g} of ${cap:g})", kind="box")
                return False
        r = self.reading.get(job.key)
        if r is not None and r.digest != job.digest:   # a read of an earlier digest still holds its place
            self.dropped.append(self.reading.pop(job.key))
            r = None
        if r is None:
            if len(self.reading) + len(self.dropped) >= self.review_slots:
                self.waiting.add(job.key)   # it goes on when a read ends and frees its place
                return False
            if self.reread(job, "before its read"):   # a superseded head is never bought a read
                return False
            fn = ("delta_review", job, pv) if pv else ("review", job)
            self.reading[job.key] = Reading(self.pool.submit(self.call, "reviewer", *fn), job.digest)
            self.waiting.add(job.key)
            return False
        if not r.future.done():
            self.waiting.add(job.key)
            return False
        del self.reading[job.key]
        v = r.future.result()   # a reviewer's fault is a UnitFault here, on the lane's thread: step() holds the job
        E.stage(job.repo, job.pr, "verdict", verdict=v.verdict)
        self.charge(v)
        if v.verdict == T.INCOMPLETE and v.extra.get("host"):
            # "If it fails again, the PR is held with that reason recorded and no fix asked of the author" (owner,
            # 10-12): a read the host could not make twice is the planning seat's, never a handback
            self.query(job, f"the review read could not be made, so nothing is asked of the PR: "
                            f"{v.extra.get('why') or 'no reason given'}", "planning")
            return False
        if v.verdict == T.INCOMPLETE:   # a wall, a limit or a silent read: wait for the time it names, no read counted
            until = v.extra.get("until") or ""
            what = ("a reader handed back without naming a blocker, or answered nothing; retrying"
                    if v.extra.get("silent") else "the review stopped on a usage or budget wall")
            self.hold(job, f"{what} ({v.extra.get('why') or 'no reason given'}); "
                           f"no read was counted" + (f", asked again at {until}" if until else ""),
                      kind="box", until=E.epoch_of(until), deferred=True, limit=bool(v.extra.get("limit")))
            return False
        job.extra["verdict"], job.review_key = v.to_dict(), v.digest
        if v.verdict == T.HANDBACK_VERDICT:
            job.reads_used += 1
            self.handback(job, "the review handed it back: " + ("; ".join(v.blocking) or "no finding named"))
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
                    got = self.fetch(base)   # oid too needs its objects here, for the proof
                    tip = oid or got[base]
                return self.proved(job, ma.get("expected") or "", tip, ma.get("pin") or job.head)
            job.extra.pop("merge_attempt", None)
            J.save(job)
        base, branch = job.extra.get("base_ref") or "", job.extra.get("branch") or ""
        for _ in range(MOVES_BEFORE_HOLD):
            with self.lock():
                got = self.fetch(base, branch)
                head_now, main_now = got[branch], got[base]
            if head_now != job.head:
                return J.move(job, T.QUEUED, why=f"the head moved to {head_now[:12]}")
            if main_now != job.base_sha and self.moved:   # a promote waits: the new release plans it at main_now
                return
            if main_now != job.base_sha and job.extra.get("light") is True:
                # asked again at the new base: a policy main took since may now list one of its files
                why = LT.why_not(self.root, main_now, job.files, protected_rules(self.repo), self.fallback)
                if why:   # not light any more: main_moved adopts the full plan at main_now (and sends it for the
                    job.extra["light"] = why   # read it now needs), then the checks the light trim left out run
                    if not self.main_moved(job, main_now, adopt=True):   # (rule 2 keeps the verdicts it has; it
                        return                                            # never lowers which checks a PR must pass)
                    left = [n for n in job.plan.checks if n not in job.results]
                    if left:
                        job.extra["rerun"] = left
                        return J.move(job, T.CHECKING, why="no longer light: check " + ", ".join(left))
                else:
                    job.base_sha = main_now   # brief 10-13: "merge at the head right away"; merge() proves it clean
                    J.save(job)
            if main_now != job.base_sha and not self.main_moved(job, main_now):
                return
            if not self.ci_green(job):   # after the head check: a moved head is queued again, not waited on
                return
            from lander import review as R
            fixed = job.extra.get("ci") == "none" and R.light_fixed(job)
            if fixed is None:   # perms' read of #2008: not on GitHub and no saved read, so nothing says it was a LAND
                return self.query(job, f"no saved read at {job.head[:12]} and no GitHub to ask whether it was a full "
                                       f"LAND, so it needs a person to look", "planning")
            if fixed:
                # security read of #1922: a PR that drops its own CI trigger lands as "no CI", and a demoted FIX
                # would merge with no test at all; with no CI the light path keeps the HANDBACK
                return self.handback(job, f"no GitHub CI ran at {job.head[:12]}, and its read was not shown to be a full "
                                          f"LAND (a FIX the light path demoted, or GitHub gave no answer), so it "
                                          f"needs a full fix round")
            # row, 10-19: "the landing lane merged dispatch#1296 on its own one review read ... before perms'
            # security read finished" — so a read perms has going holds the merge, and one that ended short of a
            # LAND is a query (perms' read of #1525: a dead read held silently)
            reading, wait = R.perms_reading(job.repo, job.pr, job.head, job.digest, lambda: R.same_change(job))
            if reading and wait:
                return self.hold(job, reading, kind="box")
            if reading:
                return self.query(job, reading, "planning")
            if self.merge(job) != "moved":
                return
        self.hold(job, f"{base} kept moving under the merge", kind="box")

    def ci_green(self, job) -> bool:
        """True when GitHub's CI lets the merge go: green, or no CI at all ("a repo with no CI configured lands as it
        does today"). "the lander never merges a head whose GitHub CI is red or still running" (2026-10-02: website
        #27-29 and #64-68 merged and deployed on a red build): red hands it back, running holds it. An empty check
        list on a base with workflows GitHub runs (GH.workflows_on: one disabled there is no CI) waits
        CI_REGISTER_WAITS for GitHub to register the runs, then lands as no CI (workflows that never run on a PR).
        Unreadable holds, and the CI_UNREADS+1th at one head is a query: a token that reads the PR but not its checks
        would otherwise hold it every sweep, silently. A spent rate limit is never counted (2026-10-21: three PRs
        became queries over a spent hour and sat two hours past its reset) and waits
        for its reset; "rate limit" in gh's words with the quota left is counted like any unread (GH.spent)."""
        try:
            workflows = GH.workflows_on(self.root, G.has_workflows(self.root, job.base_sha), self.token)
        except G.GitError:
            workflows = True   # a base that cannot be read is not evidence of no CI: wait for checks to show
        runs = []   # the starved cancels' run ids, as ci_state verified them; never read back out of detail
        state, detail = GH.ci_state(self.root, job.pr, job.head, self.token, workflows=workflows, runs=runs)
        if state:
            job.extra.pop("ci_unread", None)
        if state in ("pending", "unregistered"):
            n = self.count(job, "ci_wait")
            if state == "unregistered" and n > CI_REGISTER_WAITS:
                self.say(f"PR #{job.pr}: no GitHub check registered at {job.head[:12]} after {CI_REGISTER_WAITS} "
                         f"waits — its workflows do not run on a PR, so it lands as a repo with no CI")
                state = "none"
            elif n > CI_WAITS:
                self.query(job, f"GitHub CI has not finished at {job.head[:12]} after {CI_WAITS} waits: {detail}",
                           "planning")
                return False
            else:
                self.hold(job, f"GitHub CI is not done at {job.head[:12]}: {detail}", kind="box", secs=CI_WAIT_SECS)
                return False
        if state in ("green", "none"):
            job.extra.pop("ci_wait", None)
            job.extra["ci"] = state   # a light FIX merges only on CI that ran (mergeable)
            return True
        if state == "starved" and self.count(job, "ci_starved") <= STARVED_RERUNS:
            # "A GitHub runner-not-acquired cancel must rerun, not hand back" (2026-10-05: #80, #93-95 handed back
            # with nothing in their code failing): each cancelled run again, and the job waits for it like running CI
            got = [GH.rerun(self.root, r, self.token) for r in runs]
            self.hold(job, f"GitHub cancelled CI at {job.head[:12]} for want of a hosted runner ({detail}); "
                           + ("rerun " + ", ".join(runs) if got and all(ok for ok, _ in got)
                              else "the rerun was refused: " + "; ".join(t for ok, t in got if not ok)),
                      kind="box", secs=CI_WAIT_SECS)
            return False
        if state in ("red", "starved"):
            self.handback(job, f"GitHub CI is red at {job.head[:12]}: {detail} — fix it, or re-run it on GitHub, "
                               f"and queue it again")
        elif GH.SPENT in detail:   # GitHub's own rate_limit says spent: held uncounted until its reset
            self.hold(job, f"GitHub CI could not be read: {detail}", kind="box", until=GH.RESETS.get(self.token, 0),
                      deferred=True)
        elif self.count(job, "ci_unread") > CI_UNREADS:
            self.query(job, f"GitHub CI could not be read at {job.head[:12]} {CI_UNREADS + 1} times running: "
                            f"{detail or 'no answer'} — can the lander's token read this repo's checks?", "planning")
        else:
            self.hold(job, f"GitHub CI could not be read: {detail or 'no answer'}", kind="box")
        return False

    @staticmethod
    def count(job, key) -> int:
        """One more look at this head under job.extra[key]; a new head starts again at 1."""
        w = job.extra.get(key) if isinstance(job.extra.get(key), dict) else {}
        n = int(w.get("n") or 0) + 1 if w.get("head") == job.head else 1
        job.extra[key] = {"head": job.head, "n": n}
        return n

    def main_moved(self, job, main_now, adopt=False) -> bool:
        """main moved from job.base_sha to main_now under a mergeable job (brief, 10-13: "At merge time, re-check only
        when merge-tree finds a text conflict with current main, or main is red on a check the PR's plan includes.
        Otherwise merge on the verdict it already has. A text conflict goes to the existing repair or handback path, as
        now."). A conflict -> conflict(), False. A re-plan at main_now is read for its class and its read, gates:
        lander class -> query "lander-self", False. Paid there (a paid_review or LANDING-security.toml rule main took
        since) -> its paid and security carried onto job.plan, which never lowers them; and with no LAND at this
        digest the merge may stand on (landed_at, which wants perms' record when security is named) -> back to
        checking, where review() reads it, False: the old revalidate's "a plan that became paid with no LAND at this
        digest must go through the review too" (security read of #1334). adopt (a job no longer light): job.plan
        becomes that re-plan, so the checks the light trim left out run too; otherwise it is not adopted and adds no
        rerun. Checks of its plan main's record holds red (main_reds) -> their results dropped, base_sha = main_now,
        back to checking with only those (extra rerun; EXPRESS for the ones not in FULL_CHECKS, defined at the head
        as on main and short in the queue log), False. Otherwise base_sha = main_now and True: it goes on to GitHub's
        CI and the merge, with no check run again."""
        with self.lock():
            tree, conflicts = G.merge_tree(self.root, main_now, job.head, env=self.genv)
        if tree is None:
            self.conflict(job, conflicts)
            return False
        # the plan decides which lane lands it and whether a read must stand behind the merge, gates; rule 2 decides
        # what reruns. A reach.tsv or policy the old base had need not be what the new one has: a re-plan at main_now
        # that turns lander class is not merged here, and one that turns paid is not merged without its read.
        new = self.call("planner", "plan", self.root, main_now, job.head, job.files, fallback=self.fallback)
        if new.klass == T.LANDER:
            self.query(job, "it changes the lander itself — lander-self lands it", "lander-self")
            return False
        if adopt or job.plan is None:
            job.plan = new
        elif new.paid:
            job.plan.paid = True
            if new.extra.get("security"):
                job.plan.extra["security"] = sorted(set(job.plan.extra.get("security") or [])
                                                    | set(new.extra["security"]))
        reds = sorted(self.main_reds() & set(job.plan.checks if job.plan else []))
        job.base_sha = main_now
        pv = job.extra.get("verdict") or {}
        if not reds and new.paid and not landed_at(job, pv):
            J.move(job, T.CHECKING, why="main moved and its plan there wants a read: "
                                        + ("a security reader's" if job.plan.extra.get("security")
                                           else "no LAND is recorded at this digest"))
            return False
        if not reds:
            J.save(job)
            return True
        for n in reds:
            job.results.pop(n, None)
        job.extra["rerun"] = reds
        job.extra["express"] = {"on": [main_now, job.head],
                                "checks": self.quick(job.repo, self.unchanged(job, main_now,
                                                                              [n for n in reds
                                                                               if n not in FULL_CHECKS]))}
        J.move(job, T.CHECKING, why=f"main moved and is red on {', '.join(reds)}: rerun {', '.join(reds)}")
        return False

    def merge(self, job):
        pin = job.head   # door() made approved_head equal it when a protected path is hit; else it is stale
        base = job.extra.get("base_ref") or ""
        with contextlib.ExitStack() as held:
            held.enter_context(self.lock())
            main_before = self.fetch(base)[base]
            if main_before != job.base_sha:
                return "moved"
            expected, conflicts = G.merge_tree(self.root, main_before, job.head, env=self.genv)
            if expected is None:
                held.close()   # the git lock is let go before a repair round is dispatched
                self.conflict(job, conflicts)
                return "held"
            job.extra["merge_attempt"] = {"main_before": main_before, "expected": expected, "pin": pin}
            J.save(job)
            ok, text = GH.merge(self.root, job.pr, pin, job.extra.get("title") or "", self.token)
            if ok is None:   # merge_attempt stays: the resume asks GitHub once it answers
                self.hold(job, text, kind="box")
                return "held"
            if not ok:
                job.extra.pop("merge_attempt", None)
                if GH.behind(self.root, job.pr, self.token):
                    held.close()
                    return self.behind(job, base, text)
                job.extra["attempts"] = int(job.extra.get("attempts") or 0) + 1
                if job.extra["attempts"] >= UNRUNNABLE_TRIES:
                    self.query(job, f"the merge was refused {job.extra['attempts']} times: {text}{NEXT_REFUSED}",
                               "planning")
                else:
                    self.hold(job, text, kind="box" if GH.backoff() else "pr")
                return "held"
            tip = self.fetch(base)[base]
        self.proved(job, expected, tip, pin)
        return "merged"

    def base_merge(self, head, first, base):
        """Whether `head` is exactly GitHub's update-branch merge onto `first` of a commit on `base`: two parents, the
        first `first`, the second on `base`, and the tree the merge of the two; False when it does not read."""
        try:
            parents = G.git(self.root, "rev-list", "--parents", "-n1", head, env=self.genv).out.split()[1:]
            return len(parents) == 2 and parents[0] == first and \
                G.git(self.root, "merge-base", "--is-ancestor", parents[1], base, env=self.genv).rc == 0 and \
                G.merge_tree(self.root, first, parents[1], env=self.genv)[0] == \
                G.git(self.root, "rev-parse", f"{head}^{{tree}}", check=True, env=self.genv).out.strip()
        except G.GitError:
            return False

    def behind(self, job, base, refused):
        """GitHub's strict branch protection refused the merge because the PR's branch is BEHIND `base` (chip-flow #66,
        10-13: refused three times as 'Required status check "check" is expected', and nobody was told). The row: "on
        a strict BEHIND refusal, update the branch, wait for checks at the new head and retry once, and say so to the
        repo's seat; don't retry the same refusal." So the branch is updated once per job (extra behind_update), the
        seat is told (cards.behind), and the job is held: the update moves the head, so unhold() queues it again and
        its checks and GitHub's CI run at the new head before the one retry. BEHIND again after that update, or an
        update GitHub refuses, is a query for the planning seat, never another merge call. -> "held"."""
        done = job.extra.get("behind_update")
        if isinstance(done, dict):
            self.query(job, f"GitHub refused the merge as behind {base} again after the lane updated the branch once "
                            f"(from {str(done.get('from') or '')[:12]}): {refused}", "planning")
            return "held"
        ok, text = GH.update_branch(self.root, job.pr, job.head, self.token)
        if not ok:
            self.query(job, f"GitHub refused the merge as behind {base} ({refused}), and updating the branch failed: "
                            f"{text}", "planning")
            return "held"
        job.extra["behind_update"] = {"from": job.head, "at": E.stamp()}
        why = (f"GitHub refused the merge because the branch is behind {base}, so the lane updated the branch from "
               f"{job.head[:12]}; it merges once the checks pass at the new head")
        if self.unit("cards"):
            with contextlib.suppress(UnitFault):
                self.call("cards", "behind", job, why)
        self.hold(job, why, kind="box", secs=CI_WAIT_SECS)
        return "held"

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
        member = self.member or M.workspace(self.repo)   # a member's bare workspace board deploys nothing either
        if member or job.extra.get("tip") == "unvalidated":
            J.move(job, T.DONE, why="a member project never deploys" if member else "the tip is unvalidated")
            return E.log("done", job.repo, job.pr, rc=0)
        if not job.extra.get("tip_sha"):
            base = job.extra.get("base_ref") or ""
            with self.lock():
                job.extra["tip_sha"] = self.fetch(base)[base]
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


def spawn_lane(repo, release):
    """Start `lander lane <repo>` detached from `release` (what `current` named a moment ago). -> (ok, how).
    As its own transient unit, like a tick: this lane may be running inside a tick's unit, and a child left in that
    unit's cgroup is killed when the tick ends, mid-job. A plain detached child only when systemd-run fails.
    The pid is in the name: a lane that finds `current` moved again switches within the second it started, and
    systemd-run refuses the name of its own unit, still loaded (10-27: dispatch was left with no lane)."""
    argv = [sys.executable, "-P", os.path.join(release, "core", "lander", "cli.py"), "lane", repo]
    sysrun = os.environ.get("LANDER_SYSTEMD_RUN") or "systemd-run"
    unit = f"lander-lane-{repo}-{int(time.time())}-{os.getpid()}"
    rc, out, err = run([sysrun, "--user", "--collect", "--quiet", f"--unit={unit}",
                        "--setenv=PYTHONDONTWRITEBYTECODE=1", *argv], timeout=30)
    if rc == 0:
        return True, f"unit {unit}"
    if os.environ.get("INVOCATION_ID"):   # inside a unit: a child would die with it; the next tick starts the lane
        return False, f"systemd-run failed ({GH.last(err or out) or rc}) inside a unit"
    try:
        p = subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        return True, f"pid {p.pid}"
    except OSError as e:
        return False, str(e)


# WHO REVIEWS A LANDING IS NOT THE QUEUER'S TO CHOOSE (security read of #847). `cc done` in a worker's shell
# queues, and queue starts the tick below, which runs the lane and its review inline, so a worker's
# `CC_CLAUDE=<a fake that writes LAND> cc done` once chose its own reviewer. cards.conf reads the reviewer keys from
# the passwd home's config alone (cards.REVIEWER_CONFIG), and the tick gets its caller's environment only through
# cards.kept_env's allow-list (#862 review reads: a list of names to strip let XDG_CONFIG_HOME, GH_REPO and BASH_ENV
# through). HOME is the passwd home, since every state root falls back to it, and PATH is tick_path(). Two more are
# the tick's own, never the caller's: XDG_RUNTIME_DIR at /run/user/<uid>, where `systemd-run --user` finds the
# manager (a caller's could name a socket of its own), and INVOCATION_ID, which only tells spawn_lane that this tick
# runs inside a unit and a plain child would die with it.


def tick_path():
    """The root-owned dirs first, so a gh, git or claude in ~/bin or ~/.local/bin (a worker can write both) shadows
    nothing; the home dirs after them for the box's own tools."""
    home = C.PASSWD_HOME
    return f"{C.SYSTEM_PATH}:{home}/bin:{home}/.local/bin"


def tick_env(env):
    """The environment a queued tick starts with: kept_env's allow-list of the caller's, HOME at the passwd home,
    PATH at tick_path(), and XDG_RUNTIME_DIR / INVOCATION_ID as above. TMPDIR is the box's scratch on disk
    (environment.d's 60-cc-tmp.conf), never the caller's: without it a lane's runs fell to /tmp, which dispatch's
    fence masks, and main read red (2026-10-20)."""
    out = C.kept_env(env, PATH=tick_path())
    run = f"/run/user/{os.getuid()}"
    if os.path.isdir(run):
        out["XDG_RUNTIME_DIR"] = run
    out["TMPDIR"] = os.path.join(C.PASSWD_HOME, ".cc", "tmp")
    os.makedirs(out["TMPDIR"], mode=0o700, exist_ok=True)   # install.sh makes it; a missing one must not fall back to /tmp
    if env.get("INVOCATION_ID"):
        out["INVOCATION_ID"] = env["INVOCATION_ID"]
    return out


def spawn_tick(repo):
    """Start `lander tick --repo <repo>` detached, from this same release, with tick_env. -> (ok, how)."""
    argv = [sys.executable, "-P", os.path.join(J.CORE, "lander", "cli.py"), "tick", "--repo", repo]
    try:
        p = subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env=dict(tick_env(os.environ), PYTHONDONTWRITEBYTECODE="1"))
        return True, f"pid {p.pid}"
    except OSError as e:
        return False, str(e)


def place(repo, pr):
    """Where PR `pr` stands in its lane, and who put it first if someone did; '' when nothing is ahead of it."""
    jobs = [j for j in J.lane_jobs(repo) if j.state not in J.RESTING]
    put, keys = J.first(repo, pr), [j.pr for j in jobs]
    mine = E.epoch_of(put.get("at", ""))
    # not drained yet: behind every job, or, put first, behind those put first before it
    ahead = (jobs[:keys.index(int(pr))] if int(pr) in keys
             else [j for j in jobs if not put or 0 < E.epoch_of(J.first(repo, j.pr).get("at", "")) < mine])
    by = f"PR #{pr} was put first by {put['by']}; " if put else ""
    return (f"{by}it waits behind {len(ahead)} job(s) in the {repo} lane" if ahead
            else f"{by}nothing is ahead of it" if put else "")


def cmd_queue(argv):
    if argv and argv[0] == "--task":
        return queue_task(argv[1:])
    pos, opts = split_opts(argv, "--chat", "--ts", "--who", "--approved-by")
    start, put_first, light = "--no-start" not in pos, "--first" in pos, "--light" in pos
    pos = [a for a in pos if a not in ("--no-start", "--first", "--light")]
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
        genv = M.env(handle, repo)
    root = J.repo_root(repo)
    token = M.gh_token(handle, repo) if handle else None
    hit, approved_head = protected_hit(repo, root, pr, token, genv), ""
    if hit and hit[1] == UNLISTED and not owner_approved(approved_by):
        # a spent REST hour (or any gh failure) refused the PR with a 🔐 card it never needed, and nothing queued it
        # after the reset (2026-10-23); the lane's door asks again at every head from git's own list, so it queues
        print(f"lander: {UNLISTED} — the lane checks its paths against the protected ones at the head it plans")
        hit = None
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
        if put_first:   # a planning seat's or the owner's call: cc-guard refuses every lander command to a worker
            J.put_first(repo, pr, who or os.environ.get("CC_SLACK_ALIAS") or os.environ.get("USER") or "-")
        J.submit(repo, pr, chat=chat, ts=ts, who=who)
    except OSError as e:
        return refuse(f"cannot write the request: {e} — nothing merged", 1)
    if fresh:   # a PR with a job already gets `again` or `requeued` from drain; a second `queued` restarts `times`
        E.log("queued", repo, pr, who=who or "-", chat=chat or "-")
    if put_first:
        E.log("first", repo, pr, who=J.first(repo, pr).get("by") or "-")
    print(f"[{repo}] PR #{pr} queued — its checks run first, then the merge, then the deploy")
    if light:   # brief 10-13: "Print why a PR doesn't qualify, naming the protected path"
        print(f"lander: {light_word(repo, root, pr, token, genv)}")
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
    from lander import tick   # tick imports this module
    # a lane no tick ran inline (a lane switch's, `tick --detach`'s) arms the tick its holds wait for, as a tick does
    for ln in Lane(argv[0]).run() + tick.rearm([argv[0]]):
        print(ln)
    return 0


COMMANDS = {
    "queue": (cmd_queue, "put a PR on its repo's lane: <repo|h--t> <pr> [--chat --ts --who --approved-by --no-start"
                         " --first (to the front of the lane; a planning seat or the owner)]"
                         " | --task <repo> <row>"),
    "lane": (cmd_lane, "run one repo's lane in the foreground: <repo>"),
}
