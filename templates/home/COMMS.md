# <box> — Talking to your projects and agents

**How do I reach a project or agent, and who answers?** That is all this file: lanes, marks, who may do what, what arrives unasked. Setup and commands: `~/USAGE.md`. Source of truth: `~/dev/<control-repo>/home/COMMS.md`.

## Two lanes per project
Every repo has a **pair** of channels reaching the *same* session:

- **`#<repo>`** — yours: questions, answers, decisions, the majors. **One sentence per idea**, unless you ask for more or a technical explanation needs it.
- **`#<repo>-updates`** — everything automated or long: digests, milestone and progress posts, audits, janitor lines.

A reply comes back in the lane you asked on. `#alerts` and `#approvals` keep their own jobs; a track or sub-orch channel is already a detail lane and is not split again. `cc slack mkchannel <repo>` makes the pair; `cc slack updates-sweep` gives the lane to channels that predate it.

## How loudly you hear about it
The ladder — cheapest rung that does the job; the agent picks, you never filter:

1. **@-mention in `#<repo>`** — *you, now*: a decision blocking a track, an approval-class action waiting, an incident touching money, access or anything outward. A mention that could have waited is a bug.
2. **`needs_owner`** — *next time you open Slack*: a question stalling one track, as a row on your NEEDS YOU list.
3. **`#approvals` card** — *one tap when convenient*.
4. **`#alerts`** — *notable, nothing to do*: handovers, watchdog fallbacks, unit failures.
5. **`#<repo>-updates`** — *ambient*.
6. **The digest** — anything that can wait for 11:00 waits for it.

Litmus: needs a decision → mention · needs a tap → approvals · notable only → alerts · else updates or the digest.

## The six ways in
1. **Slack `#<repo>`** — ask or instruct; that repo's planning session answers in a thread, started for you if it isn't up. Phone-first, and the one to reach for. `#<repo>-updates` reaches the same session and carries what is automated.
2. **DM the bot** (or `#box`) — the box itself: status, ops, starting things.
3. **Phone app → Code → session** — the *same* session with its live screen, for long pastes, approvals, or stopping it.
4. **`ssh` + `cc <repo>`** — the same session again, in tmux. Slack, the app and the terminal are one conversation per project.
5. **Hands-off** — in `#<repo>`: "dispatch a worker on track *name* to do *X*", or `cc <repo> <track> --go "X"`. Own branch, ends in a PR and a ping. Nothing merges without you.
6. **Home tab** — tap the bot in the Slack sidebar: what is running, what needs you, every track's cost and PR. Live and read-only. `!status` `!threads` `!digest` say the same in text.

## Who answers
| Agent | Reach it | Does |
|---|---|---|
| **box** session | DM the bot · `#box` · phone app "<box>" · `cc`, window `box` | ops, status, starting and stopping things |
| **`<repo>` planning session** | `#<repo>` · `#<repo>-updates` · phone app `<repo>` · `cc <repo>` | plans, dispatches tracks, reviews PRs; never auto-commits; merges only on the owner's standing grant, after reviewing and running the gates — otherwise merging is theirs |
| **`<repo>/<track>` session** | `#<repo>--<track>` · phone app `<repo>/<track>` · `cc <repo> <track>` | one unit of work on its own worktree and branch, auto-committed every turn |
| **headless worker** (`--go`) | no chat — `cc <repo> <track>` shows its window, log `~/.cc/state/<repo>/<track>/loop.log` | runs a task file; `DONE` → PR, `BLOCKED` → pings you |

Everything is named after what it owns, so the Slack channel, the phone-app entry and the tmux window share one name. (Claude.ai and Claude Desktop check in through the owner's **Slack** connector.)

## Channels are sessions
- `#<repo>` ↔ `~/dev/<repo>`; `#<repo>-updates` the same session's automated lane; `#<repo>--<track>` that track; DM or `#box` the box. Anything else: name a channel after a folder in `~/dev`, or map it in `~/.cc/slack/routes.json`. `cc slack mkchannel <repo>` wires the pair, private by default (`--public` opts out); an already-public one is flagged by `cc slack channels` and flipped in Slack by hand.
- A channel that maps to nothing becomes a session on its first message: `~/dev/<name>` is created with a `CLAUDE.md`, a git repo and the `.cc/member-facing` marker — read-only outside its folder, so changes come to you in the thread. 3 new dirs an hour; never for DMs, `#approvals`/`#alerts` or archived channels. To promote one: rename the folder, add a remote, drop the marker.
- A track channel whose worker is headless cannot chat: the question goes to the `<repo>` session as `[asked in #<repo>--<track> while its headless worker runs]` and is answered there.
- `cc <repo> --orch <alias>` starts a peer orchestrator in its own `#<repo>-<alias>-<id>` channel (the brief becomes the purpose, the link lands in the thread that asked); `@<alias>` / `@main` hand a thread over. Archived when it exits, or after 24 h gone.

## Marks — whose turn it is
- Thread root: ❓ *you* must act (a 🔐 prompt, `STATUS: BLOCKED`, a declared `needs_owner`, or your own last word 30 min unanswered — `!restart <target>` if wedged) · 🔴 the session owes you, inside its 30 min · 🟠 handled, clears after 48 h · 🔧 working · ✅ finished. A channel with no ❓ has nothing waiting on you. Marks follow within ~45 s; a ❓ older than 30 min gets exactly one in-thread nudge, never on a thread you 🏁'd. `!threads` lists them.
- On your message: 👀 it has it · a reaction back is its answer (👍 yes, or done with nothing to say · 👎 no · ✅ done · ❌ can't · 🤔 unclear) · "⏳ starting…" queued until the session is up.
- Your 🏁 closes a thread (marks off, nudges off; reply to reopen). Any other reaction on a session's message reaches it as `👍 on your 07:12 reply: "…"` — 👍 act, don't ask again · 👎 no — and settles the thread. 🏁 is the only reaction you ever need to set.

## Who may do what
- Channel membership is the access control: anyone in a channel that routes to a session is answered as `role="member"`. A member cannot authorize an owner gate, answer a 🔐 prompt, run a `!` command beyond `!help`/`!status`, or hand a thread over; the session does the ungated part and @-mentions you for the rest. A member's 👍 in `#approvals` merges and their 🏁 closes; a non-owner DM gets 👋 and one line. Each non-owner also gets a private `#<handle>` pair and a `~/dev/<handle>` workspace on a daily budget (`cc-slack member add`).
- `.cc/member-facing` in a folder makes every session started there role=member by code (`cc-guard`): no dispatching work, no reading the box's secrets, no re-wiring Slack; `cc-notify` stays open so it can ask you. A blocklist, not a sandbox — for isolation use `ccbox`.
- 🔐 prompts arrive as `🔐 … Reply "yes abcde" or "no abcde"`; first answer, Slack or terminal, wins. Owner gates are hard-blocked for autonomous sessions and asked of interactive ones.
- Each finished track's PR is one card in `#approvals`; 👍 queues a landing job — a review pass, the gates against the PR's own head, then merge, install and restart — with the outcome in the thread. A failed merge pushes to your phone, posts in `#<repo>-updates` and is injected into the repo's session.

## What crosses the wire
- Your photos and files land in `~/.cc/slack/files/`; a shared message arrives as one bracketed line. Sessions @-mention people (handle, name or first name; channel members first; nobody is invited) — an unresolved handle goes out as code and the sender is told `REACHED NOBODY`. A session attaches a render or screenshot with the `file` tool (own folder, `/tmp` or `~/.cc/slack/files`, 25 MB); from the shell, `cc-slack post --file <path> [--to …] [--thread <ts>]`. Same parity for `cc-slack history|thread|edit|unsay|pin|unpin|canvas`; posts show as `<box> · <session>`.
- Free commands, no tokens: `!status` `!digest` `!sessions` `!threads` `!start` `!say <text>` `!restart box|<repo>[/track]|slack|tmux` `!reboot` `!box` `!ping` `!help` (`!restart tmux` and `!reboot` confirm first — RUNBOOK).
- Unasked: `cc-notify` into `#<repo>-updates` (`--decision` climbs to `#<repo>` with a mention); boot, limit, model-switch and audit lines into `#alerts`; the daily digest into `#<box>-updates`; an escalation (`--owner`, or from a member-facing session) is a DM and a phone push, never the channel it came from. A usage limit pauses workers and shows as `⏳ Claude usage limit until …` in `!status`. `cc-audit` (03:30 UTC) puts its report on the control repo's canvas and its findings on the board (`audit-`/`arch-`/`delete-…` rows); nothing is fixed until you say so.

## Cheat sheet
    Slack #myapp "what's the state of step1?"   that repo's session answers in a thread
    Slack #myapp "!digest"                      all tracks, PR state, cost — no tokens
    #myapp-updates                              the same session's automated posts and progress
    Slack "yes kqmtr"                           approve a relayed permission prompt
    Slack DM "what's running?"                  the box session answers
    ssh <box>; cc myapp                         the same session, terminal
    cc myapp step2 --go "…"                     headless worker → PR → ping in #myapp

## Nothing answers?
`!ping` → `cc slack status` → `journalctl --user -u cc-slackd -n 30`. A session started before `cc slack on` has no channel: restart it — `cc handoff <repo> <track>` for a track, `cc rc restart` for the box, `tmux kill-window -t main:<repo>` then `cc <repo>` for a planning session.
