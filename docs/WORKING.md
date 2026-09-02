# WORKING.md — what a session does between tasks

The system's rules live in scripts; this is the part that takes judgement. Read once per session.

## the standard
A session is a productive employee, not a task runner. It does not invent work — but when the
immediate task is done it looks up: what are the standing goals, what has the owner been talking
about, what moves those forward? Steps toward a named goal are real work: scope them, dispatch
them, or do them. Work that serves no named goal is noise, however clever.

## the loop, when nothing is queued
1. What's red? — audit checks, failed units, blocked/waiting board rows, open ledger rows.
2. What did the owner ask for that is not yet delivered? — the ledger, not memory.
3. What's the next recommendation from the last architecture review not yet landed?
4. Nothing? A review is due: spawn one (cc-audit review) on whatever broke most recently.

Red beats new. Delivery beats development. Small-and-shippable beats big-and-half-done.
The sweep spans both scales: the narrow red item and the meta-level shape of the system alike.

Scripts hold the invariants (reconcile, audit, janitor); the secretary (`cc-secretary`) judges the raw evidence and
records every finding in its own ledger. It interrupts you only when a person, an approval or a choice the files
cannot settle is needed — one `secretary/…` line, worth exactly one glance. The rest is `cc-secretary status`.

The pulse runs this loop unattended: where `cc-pulse.timer` is switched on it wakes every session
every 2 h — the tick carries what the files say (red main, open asks, queued rows, rows in flight) so an empty check
is cheap — and each one works the order above on its own; nothing here waits to be asked.

## dispatch judgement
- Planner does it: <=2 files, ~60 lines, the fix already known, nothing live holding those files — short branch, PR like anything else.
- Subagent: work that is bounded, already scoped, and finishes inside this session's life — a read whose answer compresses (delegate any that would add more than ~10k here), and equally a known fix, in its own worktree, committing and pushing itself. Cheapest model that holds quality; never for grep-shaped exploration. It costs a fraction of a worker: a bounded analysis ran to well under $1 where the same job as a worker is a $2.50-$9 repair round. Two things it cannot do — it dies with this session (a handoff killed one mid-flight on 2026-09-02 and the work was redone), and it inherits this session's reach rather than getting its own gates, journal and PR.
- Worker: open design, more files, its own test cycle, unattended running, or a file another track holds. One worker per file: split by file or run in sequence (both research arms: never parallelise writers); check the board's live tracks first.
- Lump sub-goals into one worker until the diff stops being reviewable in one sitting. Each one folded in saves a spinup, a gate run, a review and a landing.
- A brief is a goal: what, why, the boundaries, 3-5 testable done-criteria — never the steps. The PR review gets the contract and the diff, never the worker's journal.
- One repair round, resumed in the same worker session so its cache and its discovery survive. Never a fresh context re-deriving what it knew; never a second open-ended budget. Then split or escalate.
- A LAND-AFTER-FIX is not yours to dispatch: the landing queue sends one fix iteration
  itself and re-queues the PR when that branch pushes. You hear about the second stop.
- No worker-to-worker messaging, no agent teams. An orch (`cc <repo> --orch <alias>`) is a peer session with its own channel, not a layer under the planner.
- Only decision-class events wake a session; everything else goes to a file it reads on its next turn. Events arriving together cost a fraction of the same events spread out.
- Hand off when replaying the context per turn costs more than a handoff over the turns still to come: an event-driven planner around 40% of the window. A worker's iteration ends at that same 40% line: cc-context marks the journal, and cc-loop's next fresh iteration is the handoff. The 60% ceiling is the backstop for interactive sessions. Keep history append-only.

## model policy
Planning sessions and orchs run the strongest available model (cc-model's primary, Fable); a headless
worker runs on CC_WORKER_MODEL (claude-opus-5) unless the dispatcher passes `--model` for that one
task — a limit override outranks both. The order lives in cc-loop's `worker_model`; the names live in
cc-model and nowhere else — when models change, change cc-model.
- Effort is the cheap dial: high by default, down for routine turns, up for the hardest.
- On each model upgrade, try deleting one harness crutch — and read the new model's own prompting guide first: a new model's regressions cost more than its crutches.

## testing bar
Done means: the new branches have selfcheck cases, the whole suite is green, and anything a daemon
or timer runs was seen doing it once for real after deploy.
