# <box> — Usage

Shallow first. Each section: the 2–3 things you actually type. Details: `core/docs/DESIGN.md`. Talking to projects/agents: `COMMS.md`.

## Connect
- Laptop: `ssh <user>@<tailscale-ip>` (Tailscale) · anywhere: `ssh <box>` (Cloudflare, OTP) · rescue cable: `ssh <user>@<rescue-ip>`
- Phone: Claude app → Code → session `<box>` (Remote Control). Shell on phone: SSH app over Tailscale → `tmux attach -t main`.
- Work survives disconnects because it runs in tmux `main`. Detach: `Ctrl-b d`. Reattach: `tmux attach -t main`.

## Sessions (`cc`)
- `cc <repo>` — planning session for `~/dev/<repo>` (main branch; plans, dispatches, reviews PRs; never merges).
- `cc <repo> <track>` — a worker session on its own worktree + branch `track/<track>`. Auto-commits + pushes after every turn. Finish with `cc done <repo> <track>` → PR.
- `cc <repo> --orch <alias>` — a peer orchestrator session in the primary worktree (planning-session conventions), addressable in that repo's Slack channel as `@<alias>` alongside the main session.
- `cc resume` — menu of all sessions by name/status. `cc ls` / `cc digest` — what's running and where things stand.
- Reconnect = same `cc …` command; it reattaches to the live session. `cc -c <repo> [track]` only if the process died.

## Autonomous work (hands-off)
- `cc <repo> <track> --go "instruction"` — headless worker on that track: fresh context per iteration, journal at `~/.cc/state/<repo>/<track>/progress.md`, ends with a PR and a phone push. Options: `--loop N` (iterations, default 1) `--budget USD` (per iteration, default 8) `--turns N` (default 80) `--model sonnet`.
- It stops and pings you if BLOCKED, stalled, or capped twice with nothing to show. Answer a BLOCKED by appending to `~/.cc/state/<repo>/<track>/task.md`, deleting the `STATUS:` line from `progress.md`, then `cc <repo> <track> --go ""` (empty instruction = re-dispatch the task already there). Nothing merges to main without you.
- `cc <repo> <track> --say "text"` — talk to a running *interactive* session (a headless worker's pane is a shell; it refuses and tells you to use task.md). `cc handoff <repo> <track>` — journal + fresh context.

## Sandbox (`ccbox`) — untrusted or fully unrestricted work
- `ccbox <name>` — Claude with `--dangerously-skip-permissions` in Docker; only `~/dev/<name>` is mounted, at `/workspace/<name>` (so sessions/memory/trust never bleed between projects); egress limited to `~/ccbox/allowed-domains` (`--open-egress` lifts); `-c` = `claude --continue`. Tokens: `~/ccbox/env` — missing → it refuses (`cp env.example env`, chmod 600). `ccbox <control-repo>` is refused: that repo's `core/bin/` is the host's `~/bin`.
- `ccbox ls | stop | rm | shell <name> | logs <name> | build [<name>]`. `ls` shows each box's egress mode; `logs <name>` shows the firewall run (a `WARN: could not resolve …` line = that domain was skipped, so it is *not* reachable from the box). Inner tmux prefix is `C-a`.
- Options apply when the container is **created**: on a running box `ccbox <name> --open-egress|-c` refuses instead of silently attaching — `ccbox stop <name>`, then start it again. A stopped box is recreated from the image, so container-layer state (installed packages, `/tmp`) is lost; only `/workspace/<name>`, the login volume and `/commandhistory` survive. `ccbox build` after editing `~/ccbox/*` (pulls the base image and pins the current claude-code version).
- Project images: `ccbox build <name>` builds `ccbox-<name>:latest` from `~/dev/<name>/docker/Dockerfile` (context `~/dev/<name>`) and `ccbox <name>` picks it up automatically (`--image IMG` overrides). Headless: `ccbox <name> --cmd "..."` runs that command in the container's tmux instead of interactive claude. Images may ship `/usr/local/bin/ccbox-project-init` (runs at start).

## Recurring audit (`cc-audit`) — hands-off, never fixes anything
- `cc-audit.timer` runs `cc-audit auto` daily at 03:30 UTC and picks the mode from the date: **day 1 → monthly**, else **Sunday → weekly**, else **every 3rd day-of-year → review**, else it exits quietly. Run any mode by hand: `cc-audit checks|review|weekly|monthly [--dry] [--no-post]` (`--dry` prints and touches nothing, `--no-post` writes the file but skips Slack).
- **checks** (no LLM, ~3 min): the suites (`tests/check.sh`, `tests/selftest.sh`, `cc-slack selfcheck`, `tests/slack_sim.py`), user units, heartbeat freshness, Slack daemon, `cc-slackd` errors since the last report, disk/load, settings drift vs `config/claude-settings.json`, `~/bin` and home-doc symlinks, leftovers (old ccbox containers, boardless worktrees, dead trust entries) and worker spend since the last report — one PASS/FAIL line each. Every other mode runs it first and uses the table as input.
- **review** (every 3rd day — the one you actually read): checks + a read-only LLM pass over **how well the box served you** in the window — your Slack channels and threads, the boards, the track journals, `~/.cc/notify.log`, the daemon journal. Sections: responsiveness (your message → first reply, threads still on ❓), communication quality against your own style rule (it quotes the worst offender), work outcomes (DONE/BLOCKED/stalled, iterations, cost, PRs), breakages, **what you had to do by hand that should have been automatic**, and the 3 most valuable concrete improvements.
- **weekly** = checks + one read-only LLM *code* audit of one area, rotating by ISO week: cc core → cc-slack → ccbox → boot/notify/install/docs. **monthly** = checks + all four areas + a synthesis, and it puts the findings on the board as track `audit-<yyyymm>` (status todo) for the planning session to dispatch **when you say so** — cc-audit never fixes anything itself.
- Reports: `~/.cc/state/audit/<date>-<mode>[-<area>].md`, log `~/.cc/state/audit/audit.log`. Slack gets **one line**; the full report replaces the `#<box>` canvas.

## Notifications
- Sessions and loops call `cc-notify "…"` when they finish or need you → **Slack** (webhook in `~/.cc/config`) and **ntfy** push (phone app subscribes to the topic from `cc-notify setup`). Inside a Remote-Control session Claude can also push straight to the Claude app. Daily digest at 13:00 UTC. Log: `~/.cc/notify.log`.
- Every boot posts one message (`cc-boot-notify`): time up, whether the previous boot ended cleanly or by power loss / hard reset, and seconds dark. `cc-heartbeat` keeps a 10 s fsync'd alive stamp; power events accumulate in `~/.cc/state/power-events.log` (each boot line labelled `cause=clean-reboot` or `cause=power-loss`).

## Slack, two-way — talk to sessions from your phone (`cc slack`)
- One Slack app ("<box>", Socket Mode: no inbound port, no tunnel). Once: `cc slack setup` prints the 5 steps — create the app from `slack/app-manifest.json`, `cc slack setup --bot xoxb-… --app xapp-… --owner-email you@x`, `cc slack on`, then `cc slack mkchannel myapp <box> …` creates a channel per project (invites you, sets the topic). The bot can create/join channels and invite you; it cannot create the app itself.
- **Channels are projects.** `#myapp` → that repo's planning session, `#myapp--step1` → that track's session, a DM (or `#box`) → the box session. Write there; the session answers in a thread (👀 while it works, ✅ when it has replied). No session running? It is started for you and gets your message once up. Extra routes: `~/.cc/slack/routes.json`.
- Free commands (no tokens spent): `!status` `!digest` `!sessions` `!start` `!say <text>` `!restart box|<repo>[/track]|slack|tmux` `!reboot` (whole-box reboot, two-step confirm) `!threads` (this channel's open threads) `!box` `!ping` `!help`. Permission prompts reach Slack as `yes <id>` / `no <id>` questions.
- Thread roots carry at most ONE bot mark: ❓ = *you* must act (the session asked you something, or your last word has gone 30 min unanswered); no mark = the session has it or it is settled; cleared by your 🏁 or after 48 h quiet. `!threads` lists the same state (*needs you* / *quiet*), and an ❓ thread older than 30 min gets one in-thread nudge carrying the ask.
- Agent-facing parity: sessions can pull `history`/`thread` (small n by design — an information diet, not a dump), `edit`/`unsay` their own posts, `pin`/`unpin`, and replace a channel `canvas`, all via `cc-slack <cmd>` or the matching MCP tools; posts show as `<box> · <session>`.
- Sessions pick up the channel when (re)started after `cc slack on` (boot session: see RUNBOOK). `cc slack status|channels|off`. From the shell, `cc-slack inject <target> "text"` pushes a message the same way; with Slack off the reply lands in `~/.cc/slack/outbox.log`. `cc-notify` posts into `#<repo>` when the title starts with a repo name. Built on Claude Code *channels* (research preview, loaded with the development flag).
- **Merge PRs with a 👍.** `cc done` posts `[<repo>] PR #<n>: <title> — <url>` into `#approvals`; react 👍 on that message and the box squash-merges it (remote branch deleted), answering in the thread with ✅/❌. Only *your* 👍 on the bot's own post counts; `#approvals` is not a session channel. Manual post: `cc-slack post-approval <repo> <n|url>`. Needs `reactions:read` + the `reaction_added` event in the app manifest (reinstall after changing it).
- **Live dashboard — tap the bot in the Slack sidebar → *Home*.** One always-current view (`views.publish`, republished every 30 s and whenever you open the tab — never a message, never a new channel): units 🟢/🔴 + disk/load + any Claude usage-limit stamp; one line per channel with its session (🟢 live / 🟡 idle / ⚪ none) and its open ❓ count; every board track with iteration, cost, PR state and `commit!`/`push!` flags, 🏃 where a worker is actually running; the newest `cc-audit review` verdict and the last boot. Needs `home_tab_enabled` + the `app_home_opened` bot event in the app manifest — **re-paste `core/slack/app-manifest.json` (or `cc-slack manifest …`), hit Reinstall, then `systemctl --user restart cc-slackd`**; without them the daemon logs one line and leaves the tab alone until it restarts.
- Send yourself a file: `cc-slack post --file <path> [--to #<repo>|C…|U…] [--title <t>] [-m <text>]` (default: your DM; Web API only, no daemon).

## Check in from Claude.ai / Claude Desktop
- Through the Slack connector: claude.ai posts as you into your channels, and `!status`/`!digest`/`!threads` are the read API — no extra server on the box.

## Cheat sheet
    cc myapp                             plan
    cc myapp step1 --go "…"              dispatch a worker      cc myapp step1   watch/attach it
    cc done myapp step1                  open the PR            cc resume        pick any session
    ccbox experiment                     unrestricted, boxed    box-status       health
    cc slack setup | on | status         Slack ↔ sessions       #<repo> in Slack talk to that session
