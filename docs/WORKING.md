# WORKING.md — what a session does between tasks

The system's rules live in scripts; this is the part that takes judgement. Read once per session.

## spend comes first
What the box costs is the context carried per wake-up, not the code written — the cache reads of a busy day run
two orders of magnitude above everything written in it. So the four calls that set the bill come before the rest
of this file, and every session kind is handed the short form of them at start (`config/spend-prompt.md`):
fewest wake-ups, smallest context, cheapest model that holds quality, one review read per head. The numbers and
the reasoning are where they belong — waking under **dispatch judgement**, the bands under **model policy**, the
single read under **taking a board row** — and this section only says which comes first when they compete.
It is a rule about how you work, not a throttle: the usage limit is the owner's to set, and no session holds
work back for it or asks him to choose between a review and a landing.
Smallest context has one hard edge: a seat still past the rotate line (`CC_CONTEXT_ROTATE_TOKENS`, 200k) is
rotated by the box on the next reconcile tick, nag acted on or not (`cc-handoff`, ROTATION).

## the spend tier
One box-wide setting, `cc-tier` (`CC_SPEND_TIER`, default autonomous). The owner flips it with `cc-tier set
<word>` or by saying the word to the planning seat, which runs that command and answers in one line. The
scripts hold the mechanical half (cc-reconcile, cc-loop and the landing queue ask `cc-tier allows`); what a seat
may take on is this file's:
- **stop** — nothing starts, no queued landing runs its gates, cc-reconcile's tick wakes nobody. The seat answers the
  owner and does nothing else: no dispatch, no subagent, no goals turn.
- **essential** — only rows marked critical start (`cc board set <repo> <row> critical yes`), one at a time,
  on the cheapest model that holds, one review each. A task the owner asks for is marked critical by whoever
  dispatches it. No goals turn, no work the box finds itself — a self-improvement trial and a failure
  investigation wait with everything else.
- **moderate** — take on what you find yourself only when it is important or cheap. What waits: a new orch, a
  worker with `--loop` above 1, an exploration row, a self-improvement trial, a failure investigation, a
  review-into-work round — ask `cc-tier allows explore` before dispatching one of those, and `cc-tier allows
  goals` before a goals turn.
- **autonomous** — as until now: discover, fix, explore.
Never blocked by any spend tier: answering the owner, a task he asked for, a landing already past its gates, or
recording to a board — a finding, a raised- row, a backlog note. A spend-tier
flip signals no running iteration — it finishes, and the next one asks. Read it: `cc-tier`, `cc digest`, Home.
Never stop or start a unit for a tier: a unit that spends asks the tier itself (`ExecCondition=%h/bin/cc-tier allows
<what>` in its file; `cc-units tiered` lists them), and one that spends nothing, like a LEARN pull that only files,
runs at every tier. A hand stop on 10-18 outlived the tier by 2.5 days and cost two LEARN deadlines.

## the standard
A session is a productive employee, not a task runner. It does not invent work — but when the
immediate task is done it looks up: what are the standing goals, what has the owner been talking
about, what moves those forward? Steps toward a named goal are real work: scope them, dispatch
them, or do them. Work that serves no named goal is noise, however clever.

A goal with a number gets one: `cc-goal add <repo> <goal> --measure "<cmd>" --direction min|max`, and each row
dispatched toward it gets `cc-goal attempt <repo> <goal> <row>`. Once the attempts have landed and settled, the
broker's sweep reads the number. If it hasn't moved after two of them, the owner and the seat are told once, and
the next attempt is refused until `--pivot "<what is different>"` says how it steps outside the approach that
didn't work. Landing speed sat at 5.3 h for two days while each fix was built inside the same design, and the
owner had to order the pivot himself (2026-09-25).

A roadblock is something to work around before it is a question for the owner. When a command is refused or a
step stalls, read what the refusal actually saw (a stale hold, a wrong path, a missing file) and look for another
route first. Park on him only when the answer really is his: "things shouldnt wait on me unless they really have
to" (owner, 2026-09-30).

When something needs designing (a diagram set, a UI, a layout, a visual identity), offer the owner a
Claude Design run and hand over a ready prompt: what it is for, the pieces and how they connect, what
must read at a glance, the look, and the deliverables. Send it as a file in the thread. It runs in
parallel with anything the box draws itself, and he brings the result back to compare (owner, 2026-10-02).

## the loop, when nothing is queued
1. What's red? — audit checks, failed units, blocked/waiting board rows, open ledger rows.
2. What did the owner ask for that is not yet delivered? — the ledger, not memory.
3. Nothing? Then nothing: one journal line, and wait for the next event. A review runs when an incident
   or the owner asks for one, and what it finds waits as a candidate until a person promotes it — a session
   never turns a review's recommendations into work on its own (astra review 2026-09-06: six reviews in six
   days became work while total spend stayed flat).

Red beats new. Delivery beats development. Small-and-shippable beats big-and-half-done.

Scripts hold the invariants (reconcile, audit). Judgment — what looks wrong, what needs you — is the session's
own now: no secretary reads the evidence for it, and no separate watch loops run beside it either; a vanished
landing or a duplicate worker is this session's own to notice.

`cc-reconcile`'s tick runs this loop unattended: a queued row that can start, or a row that stopped (`blocked`),
wakes that repo's planning seat once per state — there is no 2-hourly wake of every session any more. An orch is
never woken this way; its own channel and its own workers wake it. Each session works the order above on its own;
nothing here waits to be asked.

## "bring it all back up"
When the owner says to bring everything back up (or unpause everything, or restart the missing sessions), the
planning seat runs one command, `cc-recover bringup`, with `--except <repo>` for any project he names as separate.
It returns at once and runs detached for a few minutes. It unpauses every project, relaunches each missing seat,
orch and member, restarts worker loops that stopped on the usage limit, and asks each live seat to pick its work
back up. It never answers a usage-limit dialog and never touches perms. Read its summary in
`~/.cc/recover/bringup.log` when the cc-notify line arrives, then do the two things it leaves to you: relaunch
perms if it says perms is down, and tell the owner which windows sit on the dialog and which member credentials
look blank. The steps are in `cc-recover`'s docstring.

## taking a board row
The native managed path is opt-in: `cc-config get CC_NATIVE_ADAPTER 0` must return `1`, and the owner must
have registered `$HOME/bin/cc-native` by hand in `~/.claude/settings.json` (PreToolUse with matcher
`Agent|Task|Bash`, and SubagentStop) before starting the session. `cc-settings apply` never adds it; while the
flag is `1` it leaves it alone, and once the flag is back to `0` it removes it. Put
`CC-Row: <repo>/<row>` on the first prompt line; omit Agent worktree isolation. Dispatch claims and prepares
the canonical track and supplies a token. The builder runs `cc-task begin <claim-token>` first, then works
in the returned worktree using its `task.md` and `progress.md`. The end hook commits and releases the claim.
After reading the diff, this session runs `cc-land queue --task <repo> <row>`. No hand claim mark or git
commit is needed on this path. With no header, keep the legacy flow below.

A row runs as a subagent of this session, in the worktree the Agent tool gives it under
`.claude/worktrees/`, on a `planning/<row>` branch. That is not a `cc` track worktree: the `.cc/track`
marker cc-checkpoint keys on is written only by `cc <repo> <row>` and `cc <repo> <row> --go`, and both of
those start a session, so `cc done` cannot finish this work. This session commits, pushes and opens the PR
itself, with git and `gh`.
A hand-made `planning/<branch>` has no track seat to hand a HANDBACK to, and nothing in the lander starts a
worker for it, so on that path this session resumes the builder itself. Keep the prompt minimal — point it at the row's `task.md` and at these working rules, and say
it stays in the worktree and does not commit. When it returns, this session commits, opens the PR and reviews
it HERE — once, at the open, not again inside the landing slot. A reviewer subagent reads the diff against the
row's brief (on the worker model where the diff is control layer: that is the read the landing would otherwise
buy), and `cc-land record <repo> <pr> <verdict> --by <who> --head <the sha it read>` writes the answer onto the
PR — `--head` because a branch pushed between the read and the record would otherwise inherit the pass. The
record is keyed to the diff and not the head SHA, so the rebase before merging keeps it and an edit does not.
To hold a PR while you check something, record HANDBACK yourself with `--by` your seat's name (the repo for its
planning seat, the track for a track); once your read passes, release it with LAND under that `--by` and `--head`
at the same head, from the directory the seat runs in. Only that reader can release its own hold this way, and a
HANDBACK from another reader or from the lander's own read still stands until a fix is pushed.
A landing that finds one buys no review — most of the hour a PR used to spend queued. A security-reviewer still
reads anything touching a gate or a member boundary. Record nothing and the landing reviews it itself, as
before (astra review 2026-09-06, cut 3: the diff is read once — this moves that one read to the open).

Leave the row `queued` while a subagent holds it, and record the claim with `cc-board note`. `queued` is the
only word cc-reconcile leaves alone: a subagent is not a worker, a cc-loop or a track pane, so the row is
never live to it, and `running` or `waiting` becomes `blocked` once the 10 min grace passes ("no worker, and
nothing says why"). The cost is that cc-reconcile's tick still counts a queued row as work waiting to be picked
up — the tick reaches this same session, which reads its own note.

Then commit the worktree, push, and open the PR with `gh` — and close the row out in this order, because the
status word on its own tells nothing downstream anything:
1. `cc-board set <repo> <row> pr <url>`. `pr` is what cc-reconcile's review watchdog and `cc-land`'s board
   close key on; without it the row asks the owner "it is waiting on a PR that was never opened" every day.
   `branch` is only cc-land's fallback when the row has no `pr`, and it would not match here anyway:
   `cc-board add` fills it with `track/<row>`, not the `planning/<row>` the PR is on.
2. `cc-board status <repo> <row> review`.
3. `cc-slack post-approval <repo> <url>` — the #approvals card is what a 👍 is given on, and nothing else
   posts one.

If the change alters the shape of the box rather than one tool's behaviour, update `core/docs/DESIGN.md` in the
same PR. Nothing rebuilds it: the session that changed the shape is the one that knows what changed.

`cc done <repo> <row>` does those three in one call, but only in a worktree `cc` made — it reads the
`.cc/track` marker. Landing follows the repo's standing: this session runs `cc-land <repo> <pr>` where the
owner has granted standing merging, the card otherwise, and cc-land closes the row by the PR URL.

A project with more than one milestone that the owner steers in its own channel gets a peer orchestrator
instead of a worker — `cc <repo> --orch <alias> "<purpose>"`, handed the row's state (mechanics in
`~/USAGE.md`'s `--orch` line). A `cc <repo> <track> --go` worker is right for a bounded build that ends
with a PR, or a big task split into serial pieces: it gets its own gates, journal and PR, but its channel
ends with it.

Subagents die with the session that spawned them, so a session does not hand off while any are in flight:
finish them or abandon them first. A retired session is gated as a worker — it can no longer push or land —
so anything left running is the successor's to pick up, worktrees and landing both.

## the reading procedure
The knowledge base is what `cc-lib` serves: the journals, boards, landing records and memory the box indexes as
sessions write them. The library is something else, the document library `cc-docs` files finished PDFs into.
The rule, one line in every session's standing text (`config/library-prompt.md`): an owner-facing claim about a
permission, a process, merged code, a live service, a PR's review or what a track did is preceded by `cc-lib ask`
or a probe of the object, and the ticket it prints is the receipt. Of fifteen recorded misses
(`docs/design-knowledge-library-2026-09-11.md`), twelve had the record on disk and the session answered from memory
or a proxy. The tool retrieves; it never calls a model. The steps:
1. Name the claim — current state, a rule or decision, history, or an aggregate — and the object (row, PR, run, path, channel, date). Split only independent claims.
2. `cc-lib ask --object <id> --need current|decision|history|aggregate "<question>"`. It opens a ticket with the byte cap and 1.5 s budget and prints the best hits, then COVERAGE and OUTCOME. With `--need current` it searches no records: it prints the object's own routes and a PROBE line naming where the live state is read (`gh pr view`, the landing queue, tmux).
3. Authoritative route first: task state from the reconciler, a review from the landing root record at the matching head, a run from its id, cost from `cc-spend` on the right time basis. A live claim needs a live probe of the object — a record about it is not the object.
4. Search only what is unresolved. Follow a hit to its record (`cc-lib get <rid>`) and its span; never read a whole journal because one line matched.
5. Widen deliberately: one reformulation, then dates and kinds, then (owner sessions only) across workspaces.
6. Check identity, authority and time: same head, same run, decision still in force, summary linked to evidence. Missing, unreadable, stale and not-searched are four different answers, and COVERAGE names each (pending, unreadable, hook-misses).
7. Stop on sufficiency or budget. Cite the record and its stamp. An empty search means "not recorded in the covered scope", never "no".
8. Delegate only a compressible large read: one bounded subagent, same workspace, no recursive spawning.
9. Leave only new knowledge — a note for a new decision, finding or explanation. What you write to a journal, the board, a landing record or a memory file is indexed as you write it (the write path calls `cc-lib index --touch`; a hook that could not index shows as `hook-misses` until the 5-minute sweep reconciles), so a minute later you ask rather than remember.

## dispatch judgement
- Planner does it itself only when the edit is already known and needs no test cycle: a line of wording, a config value, a one-hunk fix that check.sh alone covers, <=2 files, nothing live holding those files — short branch, PR like anything else. Anything that needs a selfcheck run, a new case or a negative control goes to a builder.
- Subagent: work that is bounded, already scoped, and finishes inside this session's life — a read whose answer compresses (delegate any that would add more than ~10k here), and equally a known fix, in its own worktree, leaving the commit to this session. Cheapest model that holds quality; never for grep-shaped exploration. It costs a fraction of a worker: a bounded analysis ran to well under $1 where the same job as a worker is a $2.50-$9 repair round. Two things it cannot do — it dies with this session (a handoff killed one mid-flight on 2026-09-02 and the work was redone), and it inherits this session's reach rather than getting its own gates, journal and PR. A long reader's brief names its deliverable file and tells it to write there as it goes, because `cc-subagent-bound` cuts it off at 150k with only 30k left to write in.
- Subagent types live in `~/.claude/agents/`, installed from `templates/home/agents/`. **builder** makes the change in its own worktree — on Sonnet when it fits one file and a dozen lines, on Opus when it spans tools, touches a gate or a sandbox boundary, or needs its failure path reasoned through (owner, 2026-09-05). **reviewer** reads a diff against its brief and returns LAND/FIX/DO-NOT-LAND — only where the landing will not review that head. The lander knows only LAND and HANDBACK, so record a FIX or DO-NOT-LAND with `cc-land record` as HANDBACK (it refuses the word FIX, and reads an old DO-NOT-LAND as HANDBACK). **security-reviewer** does the same on anything touching a gate, a member-writable path, git plumbing or a tmux pane. The working rules are in the type, so a spawn prompt carries only the row and the worktree — and the ledger shows what each type costs. A fix pass resumes the same builder, never a fresh one. Tune one on this box and the installer keeps your copy; change it for every box in the template.
- Worker: open design, more files, its own test cycle, unattended running, or a file another track holds. Two rows on one file both run by default, and the landing rebases the second (owner, 2026-10-12: "anything in the system can be revised at any time"). This is a measured default, not a hard rule: if a second PR on a file gets handed back more often than the baseline, improve may bring back the hold. Hold a row only on a real dependency (unmerged code it needs, an owner decision, a covering PR), worded "starts when #N lands" so cc-reconcile's holds pass (every tick; `cc-reconcile holds --dry` shows it) frees it the tick that PR merges (a hold that also names another condition only gets a note); check the board's live tracks first.
- An autoresearch loop: when the goal is a number you can measure, reach for `cc-autoresearch` instead of a one-shot worker. A faster page, a better score on a lesson's quiz, a backtest's return or a replay score all qualify. It runs trials unattended. Each trial gets one agent and one change, then the metric runs, and the change is kept only if the score beat the best so far. Every trial is a line in a results file. It stops at the trial, spend or time cap you give it and wakes you once with the best score against the baseline. It needs three things from you: a metric command that prints one number, kept out of the target (`--ruler` names its files, and a change that moves them stops the run); a target that is the only thing a trial may touch; and a branch that isn't the default one. It commits nothing, so the kept change lands as an ordinary PR from that worktree. Run it with `start` from a worker, and build the metric to fail a trial that breaks a rule, because a faster wrong answer must not score. Have it run the code's checks and compare an output against a reference. Run it on a fresh copy of frozen data each time, since the changed code really runs: on live data a moving input or a warm cache scores luck, and a change can write where it never should. One early run kept a cache that wrote into the very data it was reading. The run measures the baseline and the best again at the end, and says whether the win held. A one-shot worker is still right when nothing measures the result, or when one change is plainly the fix. `cc-autoresearch` with no arguments prints the flags.
- Lump sub-goals into one worker until the diff stops being reviewable in one sitting. Each one folded in saves a spinup, a gate run, a review and a landing.
- A brief is a goal: what, why, the boundaries, 3-5 testable done-criteria — never the steps. When the goal is scorable, the brief names its metric on a line of its own: `METRIC: <command that prints one number> · <lower|higher> is better · baseline <n> · target <n>`. That line is what the worker hands `cc-autoresearch`. The PR review gets the contract and the diff, never the worker's journal.
- One repair round, resumed in the same worker session so its cache and its discovery survive. Never a fresh context re-deriving what it knew; never a second open-ended budget. Then split or escalate.
- The lander gives two verdicts, LAND and HANDBACK (an old LAND-AFTER-FIX marker is read back as one of them).
  A HANDBACK goes to the track's seat, and the lander starts no worker loop for it: the fix is yours to send to
  a worker. `cc <repo> <row> --go "<the findings>" --repair` (add `--resume-last` to keep the
  worker's context) puts one fix onto the same branch, and its `cc done` re-queues the PR.
  On a row the owner designed (its brief cites his message), findings that name the reviewer's FIX are posted to
  him in the row's thread before the round runs, one item per list line, so write each narrowing as its own `- ` line.
  The worker builds each as its own commit; he names any he declines, and landing does not wait on him.
  A subagent's branch has no worker to push it: resume the same builder, then commit and push its worktree yourself.
- A baseline copy of `bin/` to run an old selfcheck against comes from `cc-bin-at <ref> [dir]`, which prints a directory of real files. Never a directory of `ln -s` into a checkout: twice a later `cp` followed a link and overwrote a live tool.
- Waiting is not work. Blocked on an owner decision, dispatch everything that does not turn on his answer, and let only the rows that do wait. A checkpoint or handoff that says the same as the last one is not written, because restating "unchanged, still waiting" costs a full context read and moves nothing. Waiting is a scheduled wake-up: pick when you will look again and do not re-read in between. One seat sat on four owner decisions for eleven hours, wrote about ten such entries and dispatched nothing.
- **Usable before landed: a green fix goes live now, not when the landing gets to it.** "Use the prototype now and land it later" (owner, 2026-10-11). Once a PR's own `cc-green` verdict is green at its head, the seat that dispatched it runs `cc-try on <repo> <pr>` without asking anyone. That puts the tools the PR changes into `~/.cc/try/bin`, which sits ahead of `~/bin` for every new session, worker and shell, and points any user unit that runs one of them at the PR's checkout. The planning seat may do the same for the box's own tools. A worker or a member can't: cc-guard refuses `cc-try on`, `off` and `check` to them as it refuses cc-land, so a worker hands its dispatcher the line instead. It comes back off by itself when main has the change, the PR closes or gets a new head, a guard fix deploys under it, or a tried tool's selfcheck fails; `cc-try off` takes it off by hand and `cc-try list` shows what is live. A new head is dropped rather than followed, so run `on` again once that head is green. cc-try refuses anything that guards the box (cc-guard, hooks, the sandbox, settings, the lander, approvals and permissions, the CLAUDE.md sources, and the tools that start, fence or speak for a session), and those keep the full landing. It takes only a tool `~/bin` already runs from that same file, so a new name never goes live this way, and it refuses a member workspace's PR. Every on and off goes in a ledger, and the owner sees it in the daily digest. When a worker finishes green at its head, the line its dispatcher gets carries the `cc-try on` command for its PR. Without that line the seat does nothing: it doesn't re-run a green on the host to earn one, because `cc done` has already queued the PR and the landing gates it anyway. A seat acts on a red.
- **A hole that needs patching before there is a PR: `cc-try on <repo> --branch <branch or worktree>`.** It takes a committed branch with no PR yet, once the tools it changes pass their own selfchecks at that commit, and the same guard refusals apply. It comes off by itself 24 h later, whether or not any session is alive, unless a PR at the same head has been opened by then; after that it follows the PR. `cc-try list` and the digest show hot patches apart from PR tries, so a patch never quietly becomes permanent.
- **The soft path: when you need a behaviour now and its code fix is still landing, do the behaviour yourself until the fix lands.** Do it by hand, or with a model call, from the day the need shows up, and say so in your journal; the fix lands behind you and takes over. The approvals sweep is the example: until the code path exists, the seat watches for his 👍 and does what it approves. Waiting for the landing while the need goes unmet is the thing this rule removes.
- No worker-to-worker messaging, no agent teams. An orch (`cc <repo> --orch <alias>`) is a peer session with its own channel, not a layer under the planner.
- Only decision-class events wake a session; everything else goes to a file it reads on its next turn. Events arriving together cost a fraction of the same events spread out. A monitor, watch or notifier emits on TERMINAL states only and once — a line per stage it passes through is the same information at several times the price.
- **A Monitor pipeline must end in a stage that flushes per line, or a live pipe delivers nothing.** The Bash tool's own `grep` is a function that execs the claude binary as `ugrep`, and `grep -v` through it never emits on a live pipe even though it passes on a finished file; a final `cut`/`sed`/`head` block-buffers on a pipe too. Write it as `tail -F <log> | /usr/bin/grep -E --line-buffered '<pattern>' | awk '!/<exclude-a>|<exclude-b>/ {print; fflush()}'` — the real `grep` binary by path, and any exclusion in a final `awk` that calls `fflush()` itself, never a bare filter last. **Prove it live once before trusting it**: append a matching line to the log (or wait for one real event) and see it arrive — testing the same pipeline against the file that already exists proves only that the file matches, not that a live tail delivers (2026-09-12: two Monitors armed this way delivered nothing for hours).
- Hand off when replaying the context per turn costs more than a handoff over the turns still to come. There is one line and it is an absolute number of tokens, not a percentage: `CC_CONTEXT_HANDOFF_TOKENS` (`~/.cc/config`, default 150k), the same line on a 200k window and on a 1M one. `cc-context` measures and says so, and past the line the Stop hook asks you once an hour for a dated journal entry — that is the only thing that acts on the answer, so the handoff itself is yours: the session runs `cc-handoff --overlap` as a spend choice of its own. Past the rotate line above it (`CC_CONTEXT_ROTATE_TOKENS`, default 200k) the box rotates you: `cc-handoff --sweep` on the reconcile tick opens the overlap, the successor reads your journal and asks you once, and you retire — so journal at the nag, or be asked cold. A worker needs none of that: its iteration ends, and the loop's next one starts cold on the journal — that IS its handoff, with nothing marking the journal and nothing to decide. Keep history append-only.

## model policy
Planning sessions and orchs run the strongest available model (cc-model's primary, Opus 5.5); a headless
worker runs on CC_WORKER_MODEL (claude-opus-5-5) unless the dispatcher passes `--model` for that one
task — a limit override outranks both. A planning session never runs below Opus: with Opus out
cc-model parks it rather than move it to Sonnet, and hands it back on Opus when that answers. The order lives in cc-loop's `worker_model`; the names live in
cc-model and nowhere else — when models change, change cc-model.
- A subagent runs on its type's `model` line (builder and security-reviewer: claude-opus-5-5; reviewer: sonnet) unless the spawner passes `model` on the Agent call, which outranks the type; that is how a tiny builder gets Sonnet. Verified on this box 2026-09-05: a builder spawned with model sonnet records claude-sonnet-5 in its transcript.
- Effort is the cheap dial: medium by default (Opus 5.5 at medium matches Opus 5 at high), down for routine turns, up for the hardest — xhigh for the audit's authority band. Fable is a hand-picked escalation, used only when Opus 5.5 at xhigh visibly misses.
- On each model upgrade, try deleting one harness crutch — and read the new model's own prompting guide first: a new model's regressions cost more than its crutches.

## testing bar
Done means: the new branches have selfcheck cases, the whole suite is green, and anything a daemon
or timer runs was seen doing it once for real after deploy.

A GitHub workflow a session writes bills the owner's minutes on a private repo (macOS 10x, Windows 2x), so its
defaults are: `ubuntu-latest` only on `push` and `pull_request`; `push` limited to the default branch, so a PR runs
once and not twice; a `concurrency` group keyed on the ref with `cancel-in-progress: true`; and macOS or Windows jobs
only on release tags or `workflow_dispatch`. Widen one only when the brief asks for it. A workflow that runs on every
bot commit is a cost too: run the check locally or on the merge instead.

A member's code only ever runs inside its sandbox. To rerun a member workspace's checks by hand, use
`cc-sandbox member <handle> [<track>] -- <cmd>`; cc-guard refuses a host session running a file under `~/dev/<handle>`
or `~/.cc/worktrees/<handle>`, or make/npm/pytest and the like pointed there, because there it runs as the owner.
