# autobox

Run Claude Code as an always-on agent box you drive from Slack and your phone.

One Linux box, one tmux, one Slack app. Every project gets a planning session in `#<project>`; work runs in git worktrees by
headless workers that end in PRs; a 👍 in `#approvals` merges. Deterministic hooks keep agents inside their lane; a Docker
sandbox runs the unrestricted ones. Thread marks tell you at a glance what needs you (❓), nothing else does.

## What you get
- `cc` — sessions, tracks (worktree + branch), headless `--go` workers, `done` → PR, `digest`, `handoff`. No spend cap: a worker still committing carries past its step limit, and one that stops producing stops itself.
- `cc-slack` — two-way Slack: `#<repo>` ↔ that repo's session, DMs ↔ the box; permission prompts relayed; `!status`/`!threads`/`!restart` without tokens.
- Hooks — `cc-checkpoint` (auto-commit+push in worktrees only), `cc-guard` (owner gates for autonomous sessions), `cc-context` + `cc-owed` (what a session is told at the end of a turn: hand off, and what it still owes Slack).
- `ccbox` — bypass-permissions Claude in Docker with an egress allowlist.
- `cc-audit` — recurring reviews of how well the box served you (3-day), code audits (weekly, monthly), and a second opinion from another model on what to delete (day 15).
- `cc-reconcile` — the board against the box every 20 min: applies the drift that has one right answer (a PR merged, a worker is gone), ends a worker that is spending without working, reports the rest.
- `cc-publish` — a private box keeps this tree as `core/` and mirrors it back here after every merge, gated on its own name never shipping.
- Boot/notify — survives power cuts and reboots; Slack/ntfy notices; daily digest.
- Tests: `tests/check.sh`, `tests/selftest.sh` (84 checks, no API calls), `cc-slack selfcheck`, `tests/slack_sim.py`.

## Install (Ubuntu, 10 minutes)
1. `git clone https://github.com/ihsan-sa/autobox ~/dev/autobox && ~/dev/autobox/install.sh`
2. `cp templates/home/* ~/` and fill the placeholders (box name, owner, reach paths).
3. Slack: create an app from `slack/app-manifest.json` (replace `<box>` in it), then `cc slack setup --bot xoxb-… --app xapp-…` and `cc slack on`.
4. `cc-notify setup` (ntfy topic), `claude` login once, `cc <repo>` for each project in `~/dev`.

## Layout
`bin/` scripts (symlinked into `~/bin`) · `ccbox/` sandbox image · `config/` units + settings · `slack/` manifest · `tests/` · `docs/DESIGN.md` · `templates/` + `PRIVATE-OVERLAY.md` what a box adds privately.

## Rules the box follows
Owner approves merges, deploys, spend over budget, destructive/host changes. Sessions never commit on the default branch; workers never merge. Slack messages stay short — long form goes to a canvas or a doc.

The box names itself from `hostname -s` (override with `CC_BOX`); that name titles its notifications, its Remote-Control
session and its Slack posts. A private box can carry this tree as `core/` inside its own repo — see `PRIVATE-OVERLAY.md`.

MIT — see LICENSE.
