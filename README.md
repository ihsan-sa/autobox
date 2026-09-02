# autobox

Run Claude Code as an always-on agent box you drive from Slack and your phone.

One Linux box, one tmux, one Slack app. Every project gets a planning session in `#<project>`; work runs in git worktrees by
headless workers that end in PRs; a 👍 in `#approvals` enqueues the landing job that gates, merges and deploys.
Deterministic hooks keep agents inside their lane; a Docker
sandbox runs the unrestricted ones. Thread marks tell you at a glance what needs you (❓), nothing else does.

## What you get
- `cc` — sessions, tracks (worktree + branch), headless `--go` workers, `done` → PR, `digest`, `handoff`. No spend cap: a worker still committing carries past its step limit, and one that stops producing stops itself.
- `cc-slack` — two-way Slack: `#<repo>` ↔ that repo's session, DMs ↔ the box; permission prompts relayed; `!status`/`!threads`/`!restart` without tokens.
- Hooks — `cc-checkpoint` (auto-commit+push in worktrees only), `cc-guard` (owner gates for autonomous sessions), `cc-context` + `cc-owed` (what a session is told at the end of a turn: hand off, and what it still owes Slack).
- `ccbox` — bypass-permissions Claude in Docker with an egress allowlist.
- `cc-audit` — recurring reviews of how well the box served you (3-day), code audits (weekly, monthly), and a second opinion from another model on what to delete (day 15).
- `cc-land` — **the only thing that merges, and the owner of the deploy that follows.** Gates against the PR's own head, then merge, `install.sh`, the units the change added, the restarts. A 👍 does not merge: it queues a job on disk and starts a worker, because the deploy restarts the daemon that took the 👍.
- `cc-reconcile` — the board against the box every 20 min: applies the drift that has one right answer (a PR merged, a worker is gone), ends a worker that is spending without working, reports the rest. Its snapshot is the one place `cc ls`, `cc digest` and the Slack Home tab read a track's state from.
- `cc-handoff` — the whole handoff lifecycle: a successor starts alongside its predecessor, reads the journal, then retires it; one record file names the live session and cutover is a single atomic write.
- `cc-units` / `cc-settings` — one declaration each of what must be installed (`config/units.json`, `config/claude-managed.json`) and a check that it is. `cc-settings apply` is the owner's own hand, never a script's.
- `cc-scope` — the ledger of what the owner *asked for*, as against the board's record of what the box took on. A row closes only against evidence: a command whose exit code decides, run after the deploy.
- `cc-publish` — a private box keeps this tree as `core/` and mirrors it back here after every merge, gated on its own name never shipping.
- Boot/notify — survives power cuts and reboots; Slack/ntfy notices; daily digest.
- Tests: `tests/check.sh`, `tests/selftest.sh` (200+ checks, no API calls), `cc-slack selfcheck`, `tests/slack_sim.py`.

## Blank box
Hand this repo to a Claude agent on a fresh Ubuntu box and it can do everything below except the owner's lines:
1. `git clone https://github.com/ihsan-sa/autobox ~/dev/autobox && ~/dev/autobox/install.sh` — links `bin/` into `~/bin`, arms the user units, seeds `~/CLAUDE.md` (the box contract: autonomy norm, approval list, doc pointers) and the guides from `templates/home/` where absent — `<placeholders>` stay for the owner — links `~/WORKING.md`, installs the default Claude settings. Idempotent; never rewrites a file already at `~`.
2. **Owner:** `claude` login once · a Slack app from `slack/app-manifest.json`, then `cc slack setup --bot xoxb-… --app xapp-… --owner-email you@…` and `cc slack on` · `cc-notify setup` · fill the never-touch list in `~/CLAUDE.md`. Tokens and approvals never come from the agent.
3. `cc <repo>` for each project in `~/dev` (a message in its Slack channel starts one too).
4. **Owner:** switch on `cc-pulse.timer` (installed off; `cc-pulse --dry-run` first — `~/USAGE.md` has the line). From then on the box wakes each session every 2 h and it works the loop in `WORKING.md` on its own; what still needs the owner is the approval list in `~/CLAUDE.md`, and it reaches them by @-mention.
A box that grows things of its own keeps them in a private overlay: `PRIVATE-OVERLAY.md`.

## Layout
`bin/` scripts (symlinked into `~/bin`) · `ccbox/` sandbox image · `config/` units + settings · `slack/` manifest · `tests/` · `docs/DESIGN.md` why the system is shaped this way · `docs/WORKING.md` what a session does between tasks · `templates/home/` the `~` docs a blank box starts with · `PRIVATE-OVERLAY.md` what a box adds privately.

## Rules the box follows
Sessions decide and act on their own; the owner is @-mentioned only for the approval list. Owner approves merges, deploys, spend over budget, destructive/host changes. Sessions never commit on the default branch; workers never merge. Slack messages stay short — long form goes to a canvas or a doc.

The box names itself from `hostname -s` (override with `CC_BOX`); that name titles its notifications, its Remote-Control
session and its Slack posts. A private box can carry this tree as `core/` inside its own repo — see `PRIVATE-OVERLAY.md`.

MIT — see LICENSE.
