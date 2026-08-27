# <box> — Talking to your projects and agents

Shallow first: the six moves, then who is who, then each channel in detail. Source of truth: `~/dev/<control-repo>/home/COMMS.md`.

## The six moves
1. **Slack `#<repo>`** — ask, instruct, get the answer in a thread. Phone-first. The repo's planning session answers; if none is running it is started for you.
2. **DM the bot** (or `#box`) — the box itself: status, start things, ops questions, "what's running?".
3. **Phone app → Code → session** — Remote Control: the *same* session, but you see its screen, can stop it, and type when Slack is the wrong shape (long pastes, approvals).
4. **Laptop: `ssh` + `cc <repo>`** — the same session again, in tmux. Everything you say in Slack, the app or the terminal lands in one conversation per project.
5. **Hands-off work** — in `#<repo>`: "dispatch a worker on track *name* to do *X*", or on the box `cc <repo> <track> --go "X"`. It runs headless on its own branch, ends with a PR and a ping in `#<repo>`. Nothing merges without you.
6. **Dashboard — tap the bot in the sidebar → *Home*** — one live view of the whole box, refreshed every 30 s and never posted as a message: units 🟢/🔴, every channel with its session and its open ❓, every track with iteration/cost/PR (🏃 = a worker is running), the last audit verdict and boot. Read-only; `!status` `!threads` `!digest` say the same in text.

## Who is who
| Agent | Where it lives | Reach it | Does |
|---|---|---|---|
| **box** session | tmux `main:box`, `~/dev`, Remote-Control name `<box>` | DM the bot · `#box` · phone app "<box>" · `cc` then window `box` | ops, status, starting/stopping things, questions about the box |
| **`<repo>` planning session** | tmux window `<repo>`, `~/dev/<repo>` on the default branch | `#<repo>` · phone app `<repo>` · `cc <repo>` | plans, dispatches tracks, reviews PRs; never merges, never auto-commits |
| **`<repo>/<track>` session** | window `<repo>/<track>`, own worktree + branch `track/<track>` | `#<repo>--<track>` · phone app `<repo>/<track>` · `cc <repo> <track>` | does one unit of work; every turn is auto-committed and pushed |
| **headless worker** (`--go`) | same worktree, no chat, fresh context per iteration | `cc <repo> <track>` shows its window; log `~/.cc/state/<repo>/<track>/loop.log` | executes a task file; `STATUS: DONE` → PR; `STATUS: BLOCKED` → pings you |

Sessions are named after what they own, so the Slack channel, the phone-app entry and the tmux window all share the name. (Claude.ai / Claude Desktop check in through the owner's **Slack** connector.)

## Slack in detail
- **Channels are projects.** `#<repo>` ↔ `~/dev/<repo>`; `#<repo>--<track>` ↔ that track; DM or `#box` ↔ the box. Anything else: name a channel after a folder in `~/dev`, or map it in `~/.cc/slack/routes.json` (`{"#ops": "box"}`). `cc slack mkchannel <repo>` creates + wires a channel.
- **Peer orchestrators.** `cc <repo> --orch <alias>` starts a peer session in the same channel for long/vague work; hand it a thread by starting your message with `@<alias>` (e.g. `@ai-dev take this`), and bring the main session back with `@main`.
- **Threads are conversations.** The session replies in a thread under your message; continue there. A new top-level message is a new topic — the session keeps its own memory either way.
- **Reactions tell you the state:** ❓ on a thread root = *that thread needs you* · no mark = it is in the session's hands or settled · your 🏁 on a root closes it for good · 👀 on your message = the session has it (the 👀 comes off when it answers) · ✅/❌ = your `yes <id>`/`no <id>` was delivered · "⏳ starting…" the session had to be started (your message is queued and delivered once it's up).
- **Free commands** (no tokens spent): `!status` live sessions + board · `!digest` all tracks with PR state and cost · `!sessions` who is subscribed (`<box> [main]`, `<box>@ai-dev`) · `!start` start this channel's session · `!say <text>` type into a session that has no channel (answer stays in its terminal) · `!restart box|<repo>[/track]|slack|tmux` recover a wedged session or the Slack daemon itself, no live session needed (`!restart tmux` needs a confirm — see RUNBOOK) · `!reboot` reboot the whole box (needs `!reboot confirm` — see RUNBOOK) · `!threads` on-demand snapshot of this channel's open threads in two lists — *needs you* (❓) and *quiet* (nothing for you to do); 🏁 a root to hide it · `!box` health · `!ping` · `!help`.
- **Open threads nudge themselves.** Every 15 min, any ❓ thread that has needed you for over 30 min gets one reminder posted in-thread, never repeated, carrying the actual ask: `❓ still waiting for you (33m): <the question>`, or `⏳ no answer for 33m — !restart <target> if the session is wedged` when it is the session that has gone quiet. `!threads` is the same state pulled on demand.
- **Threads carry their own status.** The bot keeps at most ONE mark on a thread root, and it means one thing: ❓ = *you* must act — either the session asked you something (a 🔐 permission prompt, `STATUS: BLOCKED`, a question) or your own last word has gone unanswered for 30 min (a stalled session; `!restart <target>` if so). Anything the session is simply working on carries no mark, so an empty channel means nothing is waiting on you. Marks appear within ~45 s of the event that caused them (a 🔐 prompt marks its thread instantly), clear the moment you reply, and expire on your 🏁 or after 48 h of quiet.
- **Agent parity on the box** (`cc-slack <cmd>`, owner/session use only, not Slack commands): `history`/`thread` pull compact recent messages (small n by design — an information diet, not a dump) · `edit`/`unsay` fix or remove the bot's own posts (including the signed `<box> · <session>` ones) · `pin`/`unpin` · `canvas` replaces a channel's canvas from stdin markdown. Sessions get the same via MCP tools; posts show as `<box> · <session>` (customized display name).
- **Approvals.** When a session hits a permission prompt you get `🔐 … Reply "yes abcde" or "no abcde"` in the channel. Answer there or in the terminal — first answer wins. Owner gates (merge, deploy, destructive/host changes, external comms) are hard-blocked for autonomous sessions and *asked* for interactive ones; from Slack you are the one who says yes.
- **PR merges.** Every finished track's PR lands in `#approvals` as `[<repo>] PR #<n>: <title> — <url>`. React 👍 and the box squash-merges it (remote branch deleted); the outcome comes back in the thread (✅ merged / ❌ with gh's error / "already merged"). Anyone else's 👍, or a 👍 on anything but the bot's own PR post, is ignored. A **failed** merge no longer stops in that thread (nothing routes there): it also pushes to your phone as `[<repo>] PR #<n> merge failed`, posts in `#<repo>` (not the fallback channel) and is injected into the repo's session, so an agent picks up the fix.
- **Attachments.** Photos, screenshots and files you send are downloaded to `~/.cc/slack/files/` and the session reads them (images render).
- **Who can talk:** only your Slack user (paired once). Everyone else is dropped silently — so your Slack login is part of the box's security.
- **What arrives on its own:** `cc-notify` posts into `#<repo>` (worker done / blocked / stalled, PR links), boot notices and the daily digest into `#<box>` or `SLACK_CHANNEL`, plus ntfy pushes to the phone.
- **The audit is one line, never a wall of text:** `cc-audit` (03:30 UTC — **review every 3rd day**, weekly on Sundays, monthly on the 1st) posts a single line into `#<box>` and puts the whole report on the **`#<box>` canvas**. The review's line is its verdict on *your* experience (`… · 3 improvements → canvas`); the code audits' is `OK: 0 checks failed · 1/5 findings · canvas updated`. Monthly findings also land on the board as `audit-<yyyymm>`; nothing gets fixed until you say so.
- **The review is the one that reads you, not the code:** every third day it goes through your channels and threads, the boards and journals, and reports how long you waited for replies, where a message ignored your style rule (quoting it), what burned budget without a result, and **what you had to do by hand that should have been automatic**.
- **Long tasks:** the session sends a one-line ack, works, then posts the result. **Messages are structured, not long** — a few section bullets with sub-bullets for detail (generally few, no hard cap when the content needs it); reference material lands where it belongs, linked in one line: the channel's *canvas* (living project state, replaced in place — open it from the channel header), the repo's `docs/` (lasting reports, on GitHub), the track journal (running detail). If you want to watch, open the same session in the phone app.
- **Nothing answers?** `!ping` (daemon alive?) → `cc slack status` on the box → `journalctl --user -u cc-slackd -n 30`. A session started before `cc slack on` has no channel: restart it and message again — `cc handoff <repo> <track>` for a track (it needs both), `cc rc restart` for the box session, and for a planning session close its window (`tmux kill-window -t main:<repo>`) then `cc <repo>`.

- **Files from the box.** `cc-slack post --file <path> [--to #<repo>|C…|U…] [--title <t>] [-m <text>]` uploads a file as the bot — default target is your DM (the box uses it for guides, PDFs, screenshots). Pure Web API (no daemon needed); clear errors on `missing_scope` / `not_in_channel`.

## Claude Code sessions (phone app or terminal)
- `cc` attach tmux · `cc <repo>` planning session · `cc <repo> <track>` track session · `cc resume` menu · `cc ls` / `cc digest` what's live and where things stand.
- Reconnect = the same command; sessions survive disconnects and reboots (tmux `main` is a user service). `cc -c <repo>` only if a process died.
- Nudge a running session: `cc <repo> <track> --say "text"` (types into it) · `cc handoff <repo> <track>` (journal + fresh context) · `cc done <repo> <track>` (PR) · `cc rm` (remove a track).
- Between sessions, Claude uses its native `SendMessage` (session name = window name); you don't need to relay.
- Phone app: Code → the session name. Remote Control shows the live screen; Slack and the app can be used on the same session at the same time.
- Box session: `cc rc status|restart`. Restarting ends its current conversation (pick `<box>` again in the app).

## Hands-off work and what needs you
- `cc <repo> <track> --go "task" [--loop N] [--budget USD] [--model sonnet]` — fresh context per iteration, journal at `~/.cc/state/<repo>/<track>/progress.md`, capped by budget and turns, ends in a PR + a ping. Or say it in `#<repo>` and the planning session runs it.
- It stops and pings you when **BLOCKED** (answer: edit the task file, rerun) or stalled. Answer questions in `#<repo>`; the planning session can also re-dispatch.
- **You decide:** merges to main, deploys, spend beyond budgets, anything destructive or host/network-level, messages sent in your name. Everything else the agents do on their own.

## Cheat sheet
    Slack #myapp "what's the state of step1?"                answer in a thread from that repo's session
    Slack DM "start myapp and summarize the board"           the box session does it
    Slack #myapp "!digest"                                   all tracks, PR state, cost — no tokens
    Slack "yes kqmtr"                                        approve a relayed permission prompt
    Phone app → Code → myapp                                 same session, live screen
    ssh <box>; cc myapp                                      same session, terminal
    cc myapp step2 --go "…"                                  headless worker → PR → ping in #myapp
    cc slack status | cc rc restart | box-status             when something's quiet
