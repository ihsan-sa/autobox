# <box> — Talking to your projects and agents

**How do I reach a project or agent, and who answers?** That is all this file. Below it: the Slack mechanics — channels, threads, marks, reactions, who may do what, what arrives on its own — in `~/SLACK.md`; the commands in `~/USAGE.md`. Source of truth: `~/dev/<control-repo>/home/COMMS.md`.

## The six ways in
1. **Slack `#<repo>`** — ask or instruct; that repo's planning session answers in a thread, started for you if it isn't up. Phone-first, and the one to reach for.
2. **DM the bot** (or `#box`) — the box itself: status, ops, starting things.
3. **Phone app → Code → session** — the *same* session with its live screen, for long pastes, approvals, or stopping it.
4. **`ssh` + `cc <repo>`** — the same session again, in tmux. Slack, the app and the terminal are one conversation per project.
5. **Hands-off** — in `#<repo>`: "dispatch a worker on track *name* to do *X*", or `cc <repo> <track> --go "X"`. Own branch, ends in a PR and a ping. Nothing merges without you.
6. **Home tab** — tap the bot in the Slack sidebar: what is running, what needs you, every track's cost and PR. Live and read-only. `!status` `!threads` `!digest` say the same in text.

## Who answers
| Agent | Reach it | Does |
|---|---|---|
| **box** session | DM the bot · `#box` · phone app "<box>" · `cc`, window `box` | ops, status, starting and stopping things |
| **`<repo>` planning session** | `#<repo>` · phone app `<repo>` · `cc <repo>` | plans, dispatches tracks, reviews PRs; never merges, never auto-commits |
| **`<repo>/<track>` session** | `#<repo>--<track>` · phone app `<repo>/<track>` · `cc <repo> <track>` | one unit of work on its own worktree and branch, auto-committed every turn |
| **headless worker** (`--go`) | no chat — `cc <repo> <track>` shows its window, log `~/.cc/state/<repo>/<track>/loop.log` | runs a task file; `DONE` → PR, `BLOCKED` → pings you |

Everything is named after what it owns, so the Slack channel, the phone-app entry and the tmux window share one name. (Claude.ai and Claude Desktop check in through the owner's **Slack** connector.)

## Cheat sheet
    Slack #myapp "what's the state of step1?"   that repo's session answers in a thread
    Slack #myapp "!digest"                      all tracks, PR state, cost — no tokens
    Slack "yes kqmtr"                           approve a relayed permission prompt
    Slack DM "what's running?"                  the box session answers
    ssh <box>; cc myapp                         the same session, terminal
    cc myapp step2 --go "…"                     headless worker → PR → ping in #myapp

Nothing answers? `!ping`, then `~/SLACK.md`.
