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
3. Nothing? Then nothing: one journal line, and wait for the next event. A review runs when an incident
   or the owner asks for one, and what it finds waits as a candidate until a person promotes it — a session
   never turns a review's recommendations into work on its own (astra review 2026-09-06: six reviews in six
   days became work while total spend stayed flat).

Red beats new. Delivery beats development. Small-and-shippable beats big-and-half-done.

Scripts hold the invariants (reconcile, audit, janitor); the secretary (`cc-secretary`) judges the raw evidence and
records every finding in its own ledger. It interrupts you only when a person, an approval or a choice the files
cannot settle is needed — one `secretary/…` line, worth exactly one glance. The rest is `cc-secretary status`.

The pulse runs this loop unattended: where `cc-pulse.timer` is switched on it wakes every session
every 2 h — the tick carries what the files say (red main, open asks, queued rows, rows in flight) so an empty check
is cheap — and each one works the order above on its own; nothing here waits to be asked.

## taking a board row
The native managed path is opt-in: `cc-config get CC_NATIVE_ADAPTER 0` must return `1`, and the owner must
have registered the hooks with `cc-settings apply` at a terminal before starting the session. Put
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
A hand-made `planning/<branch>` gets no automatic repair round: on a LAND-AFTER-FIX the landing queue's fix
iteration branches a fresh worktree and pushes where the PR is not, so on that path this session resumes the
builder itself. Keep the prompt minimal — point it at the row's `task.md` and at these working rules, and say
it stays in the worktree and does not commit. When it returns, this session commits and lands it, and the landing's review is the verdict. A
reviewer subagent reads the diff first only where the landing will not review that head — a paused repo, a
`--no-review` landing — and a security-reviewer where a gate or a member boundary changes; never as a second
opinion on a diff the lander is about to read (astra review 2026-09-06, cut 3).

Leave the row `queued` while a subagent holds it, and record the claim with `cc-board note`. `queued` is the
only word cc-reconcile leaves alone: a subagent is not a worker, a cc-loop or a track pane, so the row is
never live to it, and `running` or `waiting` becomes `blocked` once the 10 min grace passes ("no worker, and
nothing says why"). The cost is that cc-pulse still counts a queued row as work waiting to be picked up — the
tick reaches this same session, which reads its own note.

Then commit the worktree, push, and open the PR with `gh` — and close the row out in this order, because the
status word on its own tells nothing downstream anything:
1. `cc-board set <repo> <row> pr <url>`. `pr` is what cc-reconcile's review watchdog and `cc-land`'s board
   close key on; without it the row asks the owner "it is waiting on a PR that was never opened" every day.
   `branch` is only cc-land's fallback when the row has no `pr`, and it would not match here anyway:
   `cc-board add` fills it with `track/<row>`, not the `planning/<row>` the PR is on.
2. `cc-board status <repo> <row> review`.
3. `cc-slack post-approval <repo> <url>` — the #approvals card is what a 👍 is given on, and nothing else
   posts one.

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

## dispatch judgement
- Planner does it itself only when the edit is already known and needs no test cycle: a line of wording, a config value, a one-hunk fix that check.sh alone covers, <=2 files, nothing live holding those files — short branch, PR like anything else. Anything that needs a selfcheck run, a new case or a negative control goes to a builder.
- Subagent: work that is bounded, already scoped, and finishes inside this session's life — a read whose answer compresses (delegate any that would add more than ~10k here), and equally a known fix, in its own worktree, leaving the commit to this session. Cheapest model that holds quality; never for grep-shaped exploration. It costs a fraction of a worker: a bounded analysis ran to well under $1 where the same job as a worker is a $2.50-$9 repair round. Two things it cannot do — it dies with this session (a handoff killed one mid-flight on 2026-09-02 and the work was redone), and it inherits this session's reach rather than getting its own gates, journal and PR.
- Subagent types live in `~/.claude/agents/`, installed from `templates/home/agents/`. **builder** makes the change in its own worktree — on Sonnet when it fits one file and a dozen lines, on Opus when it spans tools, touches a gate or a sandbox boundary, or needs its failure path reasoned through (owner, 2026-09-05). **reviewer** reads a diff against its brief and returns LAND/FIX/DO-NOT-LAND — only where the landing will not review that head. **security-reviewer** does the same on anything touching a gate, a member-writable path, git plumbing or a tmux pane. The working rules are in the type, so a spawn prompt carries only the row and the worktree — and the ledger shows what each type costs. A fix pass resumes the same builder, never a fresh one. Tune one on this box and the installer keeps your copy; change it for every box in the template.
- Worker: open design, more files, its own test cycle, unattended running, or a file another track holds. One worker per file: split by file or run in sequence (both research arms: never parallelise writers); check the board's live tracks first.
- Lump sub-goals into one worker until the diff stops being reviewable in one sitting. Each one folded in saves a spinup, a gate run, a review and a landing.
- A brief is a goal: what, why, the boundaries, 3-5 testable done-criteria — never the steps. The PR review gets the contract and the diff, never the worker's journal.
- One repair round, resumed in the same worker session so its cache and its discovery survive. Never a fresh context re-deriving what it knew; never a second open-ended budget. Then split or escalate.
- A LAND-AFTER-FIX is not yours to dispatch: the landing queue sends one fix iteration
  itself and re-queues the PR when that branch pushes. You hear about the second stop.
  A subagent's branch has no worker to push it: resume the same builder, then commit and push its worktree yourself.
- No worker-to-worker messaging, no agent teams. An orch (`cc <repo> --orch <alias>`) is a peer session with its own channel, not a layer under the planner.
- Only decision-class events wake a session; everything else goes to a file it reads on its next turn. Events arriving together cost a fraction of the same events spread out.
- Hand off when replaying the context per turn costs more than a handoff over the turns still to come: an event-driven planner around 40% of the window. A worker's iteration ends at that same 40% line: cc-context marks the journal, and cc-loop's next fresh iteration is the handoff. The 60% ceiling is the backstop for interactive sessions. Keep history append-only.

## model policy
Planning sessions and orchs run the strongest available model (cc-model's primary, Fable); a headless
worker runs on CC_WORKER_MODEL (claude-opus-5) unless the dispatcher passes `--model` for that one
task — a limit override outranks both. The order lives in cc-loop's `worker_model`; the names live in
cc-model and nowhere else — when models change, change cc-model.
- A subagent runs on its type's `model` line (builder and security-reviewer: opus; reviewer: sonnet) unless the spawner passes `model` on the Agent call, which outranks the type; that is how a tiny builder gets Sonnet. Verified on this box 2026-09-05: a builder spawned with model sonnet records claude-sonnet-5 in its transcript.
- Effort is the cheap dial: high by default, down for routine turns, up for the hardest.
- On each model upgrade, try deleting one harness crutch — and read the new model's own prompting guide first: a new model's regressions cost more than its crutches.

## testing bar
Done means: the new branches have selfcheck cases, the whole suite is green, and anything a daemon
or timer runs was seen doing it once for real after deploy.
