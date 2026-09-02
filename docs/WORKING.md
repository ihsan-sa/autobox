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

Scripts hold the invariants (reconcile, audit, janitor); the secretary (`cc-secretary`) judges the raw evidence and
hands you a `secretary/…` line; you decide — it is worth exactly one glance, and a wrong one costs nothing more.

The pulse runs this loop unattended: where `cc-pulse.timer` is switched on it wakes every session
every 2 h — the tick carries what the files say (red main, open asks, queued rows, rows in flight) so an empty check
is cheap — and each one works the order above on its own; nothing here waits to be asked.

## dispatch judgement
- One worker per file, always. Check the board's live tracks before dispatching.
- A brief is a GOAL, not a plan: what, why, the boundaries, and how done is judged —
  3-5 testable done-criteria, on one screen. The worker chooses the implementation, the
  tests and the docs; naming those for it buys a worse answer than it would have found.
  The PR review verifies against the done-criteria, briefed with the contract and the
  diff, never the worker's own journal.
- A LAND-AFTER-FIX is not yours to dispatch: the landing queue sends one fix iteration
  itself and re-queues the PR when that branch pushes. You hear about the second stop.
- Small fix with no live collision → short branch by the planning session. More → a worker.

## model policy
On each model upgrade, try deleting one harness crutch: every workaround encodes an
assumption about model weakness, and those expire.


Planning runs the strongest available model; workers run the strong-but-cheaper tier. Both names
live in cc-model and nowhere else — when models change, change cc-model.

## testing bar
Done means: the new branches have selfcheck cases, the whole suite is green, and anything a daemon
or timer runs was seen doing it once for real after deploy.
