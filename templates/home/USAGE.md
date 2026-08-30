# <box> — Usage

Shallow first. Each section: the 2–3 things you actually type. Why it is shaped this way: `core/docs/DESIGN.md`. Talking to projects and agents: `COMMS.md`.

## Connect
- Laptop: `ssh <user>@<tailscale-ip>` (Tailscale) · anywhere: `ssh <box>` (Cloudflare, OTP) · rescue cable: `ssh <user>@<rescue-ip>`
- Phone: Claude app → Code → session `<box>` (Remote Control). Shell on phone: SSH app over Tailscale → `tmux attach -t main`.
- Work survives disconnects because it runs in tmux `main`. Detach: `Ctrl-b d`. Reattach: `tmux attach -t main`.

## Sessions (`cc`)
- `cc <repo>` — planning session for `~/dev/<repo>` (main branch; plans, dispatches, reviews PRs; never merges).
- `cc <repo> <track>` — worker session on its own worktree + branch `track/<track>`. Auto-commits and pushes after every turn. Finish with `cc done <repo> <track>` → PR.
- `cc <repo> --orch <alias> ["brief"]` — a peer orchestrator in the primary worktree, addressable as `@<alias>` in that repo's channel and in its own `#<parent>-<alias>-<id>` (routing table `~/.cc/slack/orchs.json`). Archived when the session exits, by `cc slack archive <#chan>`, or by the daily janitor 24 h after it is gone.
- `cc resume` — menu of all sessions by name/status. `cc ls` / `cc digest` — what's running and where things stand.
- Reconnect = the same `cc …` command. `cc -c <repo> [track]` only if the process died.

## Autonomous work (hands-off)
- `cc <repo> <track> --go "instruction"` — headless worker: fresh context per iteration, journal at `~/.cc/state/<repo>/<track>/progress.md`, ends with a PR and a phone push. Options: `--loop N` (iterations, default 1) `--budget USD` (per iteration, default 8) `--turns N` (default 80) `--model sonnet`.
- It stops and pings you if BLOCKED, stalled, or capped twice with nothing to show. To answer a BLOCKED: append to `~/.cc/state/<repo>/<track>/task.md`, delete the `STATUS:` line from `progress.md`, then `cc <repo> <track> --go ""` (empty instruction = re-dispatch the task already there). Nothing merges to main without you.
- `cc <repo> <track> --say "text"` — talk to a running *interactive* session; a headless worker's pane is a shell, so it refuses and points you at task.md. `cc handoff <repo> <track>` — journal + fresh context.
- **A usage limit on the primary model moves every session to the fallback, and back.** `cc-model.timer` ticks every 60 s and switches when `cc-limit`'s stamp names the primary (`CC_MODEL_PRIMARY`), or a live pane shows a fresh `usage limit` line *and* a one-turn probe agrees. Live interactive sessions are retyped to `/model <fallback>` (`CC_MODEL_FALLBACK`); headless workers pick it up from `cc-model current` next iteration. One line per switch (`<box> model` → `#alerts`). It probes the primary after the reset time (at most every 15 min) and restores on the first answer. `cc-model status` → the current model or `<fallback> until 11:40Z`; override in `~/.cc/state/model-override`, log in `~/.cc/state/model.log`; never two switches within 10 min, and effort stays what `~/.claude/settings.json` says.

## Sandbox (`ccbox`) — untrusted or fully unrestricted work
- `ccbox <name>` — Claude with `--dangerously-skip-permissions` in Docker; only `~/dev/<name>` is mounted, at `/workspace/<name>`, so sessions, memory and trust never bleed between projects. Egress is limited to `~/ccbox/allowed-domains` (`--open-egress` lifts it); `-c` = `claude --continue`. Tokens: `~/ccbox/env` — missing → it refuses (`cp env.example env`, chmod 600). `ccbox <control-repo>` is refused: that repo's `core/bin/` is the host's `~/bin`.
- `ccbox ls | stop | rm | shell <name> | logs <name> | build [<name>]`. `ls` shows each box's egress mode; `logs <name>` shows the firewall run — a `WARN: could not resolve …` line means that domain was skipped and is *not* reachable. Inner tmux prefix is `C-a`.
- Options apply when the container is **created**: on a running box `ccbox <name> --open-egress|-c` refuses rather than silently attach — `ccbox stop <name>`, then start it again. A stopped box is recreated from the image, so installed packages and `/tmp` are lost; `/workspace/<name>`, the login volume and `/commandhistory` survive. `ccbox build` after editing `~/ccbox/*`.
- Project images: `ccbox build <name>` builds `ccbox-<name>:latest` from `~/dev/<name>/docker/Dockerfile` and `ccbox <name>` picks it up (`--image IMG` overrides). Headless: `ccbox <name> --cmd "..."` runs that command in the container's tmux instead of interactive claude. Images may ship `/usr/local/bin/ccbox-project-init` (runs at start).

## Recurring audit (`cc-audit`) — hands-off, never fixes anything
- `cc-audit.timer` runs `cc-audit auto` daily at 03:30 UTC and picks the mode from the date: **day 1 → monthly**, else **Sunday → weekly**, else **every 3rd day-of-year → review**, else it exits quietly. By hand: `cc-audit checks|review|weekly|monthly [--dry] [--no-post]` (`--dry` touches nothing, `--no-post` writes the file but skips Slack).
- **checks** (no LLM, ~3 min): the suites (`tests/check.sh`, `tests/selftest.sh`, `cc-slack selfcheck`, `tests/slack_sim.py`), user units, heartbeat freshness, Slack daemon and its errors since the last report, disk/load, settings drift vs `config/claude-settings.json`, `~/bin` and home-doc symlinks, leftovers and worker spend — one PASS/FAIL line each. Every other mode runs it first.
- **review** (every 3rd day — the one you actually read): checks, plus a read-only LLM pass over **how well the box served you**. Sections: responsiveness, communication quality against your own style rule (it quotes the worst offender), work outcomes, breakages, **what you had to do by hand that should have been automatic**, and the 3 most valuable improvements.
- **weekly** = checks + a read-only code audit of one area, rotating by ISO week: cc core → cc-slack → ccbox → boot/notify/install/docs. **monthly** = all four plus a synthesis, and it puts the findings on the board as track `audit-<yyyymm>` (todo) — to be dispatched **when you say so**.
- Reports: `~/.cc/state/audit/<date>-<mode>[-<area>].md`, log `~/.cc/state/audit/audit.log`. Slack gets **one line**; the full report replaces the `#<box>` canvas.

## Notifications
- Sessions and loops call `cc-notify "…"` when they finish or need you → **Slack** (webhook in `~/.cc/config`) and **ntfy** push (subscribe the phone to the topic from `cc-notify setup`). Daily digest at 13:00 UTC. Log: `~/.cc/notify.log`.
- Every boot posts one message (`cc-boot-notify`): time up, whether the last boot ended cleanly or by power loss, and seconds dark. `cc-heartbeat` keeps a 10 s fsync'd stamp; events accumulate in `~/.cc/state/power-events.log` (`cause=clean-reboot` or `cause=power-loss`).

## Slack, two-way (`cc slack`)
How the conversation itself works — channels, threads, marks, who may do what, the free `!` commands and the agent-facing `cc-slack` ones — is `COMMS.md`. Here: the setup and the box-side commands.
- One Slack app ("<box>", Socket Mode: no inbound port, no tunnel). Once: `cc slack setup` prints the 5 steps — create the app from `slack/app-manifest.json`, `cc slack setup --bot xoxb-… --app xapp-… --owner-email you@x`, `cc slack on`, then `cc slack mkchannel <repo>` per project (**private by default**, `--public` opts out; a `#<repo>--<sub>` name inherits `#<repo>`'s people). The bot cannot create the app itself.
- `cc slack status|channels|off|archive <#chan>`. Extra routes: `~/.cc/slack/routes.json`. From the shell, `cc-slack inject <target> "text"` pushes a message the same way; with Slack off the reply lands in `~/.cc/slack/outbox.log`. `cc-notify` posts into `#<repo>` when the title starts with a repo name.
- Sessions pick up their channel when (re)started after `cc slack on` — for the boot session see RUNBOOK. Built on Claude Code *channels* (research preview, loaded with the development flag).
- **Merge PRs with a 👍.** `cc done` posts `[<repo>] PR #<n>: <title> — <url>` into `#approvals`; react 👍 on that message and the box squash-merges it, answering in the thread. Manual post: `cc-slack post-approval <repo> <n|url>`. Needs `reactions:read` + the `reaction_added` event in the manifest (reinstall after changing it).
- **Live dashboard — tap the bot in the Slack sidebar → *Home*.** Units 🟢/🔴 + disk/load + any usage-limit stamp; one line per channel with its session and open ❓ count; every board track with iteration, cost, PR state and `commit!`/`push!` flags; the newest `cc-audit review` verdict and the last boot. Needs `home_tab_enabled` + the `app_home_opened` bot event — **re-paste `slack/app-manifest.json` (or `cc-slack manifest …`), hit Reinstall, then `systemctl --user restart cc-slackd`**; without them the daemon logs one line and leaves the tab alone.
- `cc quick doing|done "…"` — log work that has no track; Home lists what is in progress.

## Check in from Claude.ai / Claude Desktop
- Through the Slack connector: claude.ai posts as you into your channels, and `!status`/`!digest`/`!threads` are the read API — no extra server on the box.

## Cheat sheet
    cc myapp                             plan
    cc myapp step1 --go "…"              dispatch a worker      cc myapp step1   watch/attach it
    cc done myapp step1                  open the PR            cc resume        pick any session
    ccbox experiment                     unrestricted, boxed    box-status       health
    cc slack setup | on | status         Slack ↔ sessions       #<repo> in Slack talk to that session
