# <box> — Talking to your projects and agents

**How do I reach a project or agent, and who answers?** That is all this file: lanes, marks, who may do what, what arrives unasked. Setup and commands: `~/USAGE.md`. Source of truth: `~/dev/<control-repo>/home/COMMS.md`.

## Two lanes per project
Every repo has a **pair** of channels reaching the *same* session:

- **`#<repo>`** — yours: questions, answers, decisions, the majors. **One sentence per idea**, unless you ask for more or a technical explanation needs it.
- **`#<repo>-updates`** — everything automated or long: digests, milestone and progress posts, audits, janitor lines.

A reply comes back in the lane you asked on. `#alerts` and `#approvals` keep their own jobs; a track or sub-orch channel is already a detail lane and is not split again. `cc slack mkchannel <repo>` makes the pair; `cc slack updates-sweep` gives the lane to channels that predate it.

## How loudly you hear about it
The ladder — cheapest rung that does the job; the agent picks, you never filter:

1. **`cc-notify --decision` / `--approval`** — *you, now*, and only from the planning seat: a choice only you can make lands in `#<repo>` as `❓ @you *Decision needed:* <one question>`; an authorization (a protected path, a restart, spend beyond its authority) lands in `#approvals` as `❓ @you 🔐 *Approval needed:* <action and consequence>`. One live card per decision; your answer in its thread resolves that card. Everything below the seat — a worker, a member session, an orch, a unit — asks the seat instead (`cc-notify --ask`, behind the scenes: a file and the broker, no channel), and the seat asks you only once it has verified it cannot settle it. A mention that could have waited is a bug.
2. **`needs_owner`** — *a question stalling one track*, and only from the planning seat: the reply opens with ❓ and your mention — that is the whole signal. Declared by any other session — a track, an orch, a member workspace, another repo's seat — it is rung 1's request to the seat instead: the reply goes into its thread carrying no mention of you.
3. **`#approvals` card** — *one tap when convenient*.
4. **`#alerts`** — *notable, nothing to do*: handovers, watchdog fallbacks, unit failures.
5. **`#<repo>-updates`** — *ambient*.
6. **The digest** — anything that can wait for 11:00 waits for it.

**A message that needs your decision opens with ❓ and @-mentions you; an update, or one session posting into another's channel, carries neither — and nothing else can mention you** (rungs 1 and 2, and a mail the box holds for your verdict, are the only doors; a typed handle of yours goes out as code).

Litmus: needs a decision → ❓ + mention · needs a tap → approvals · notable only → alerts · else updates or the digest.

## The six ways in
1. **Slack `#<repo>`** — ask or instruct; that repo's planning session answers in a thread, started for you if it isn't up. Phone-first, and the one to reach for. `#<repo>-updates` reaches the same session and carries what is automated. **Speak it if that is easier** — a voice memo in the channel arrives as a message: the box transcribes it locally, replies under your recording with the words as spoken and the condensed text in italics beneath, and the session answers the condensed text. Needs `cc-voice install` once (USAGE); a parked project stays parked — nothing is transcribed, so the recording queues as an attachment and the session reads it with `cc-voice text <path>` at `!resume`.
2. **DM the bot** (or `#box`) — the box itself: status, ops, starting things.
3. **Phone app → Code → session** — the *same* session with its live screen, for long pastes, approvals, or stopping it.
4. **`ssh` + `cc <repo>`** — the same session again, in tmux. Slack, the app and the terminal are one conversation per project.
5. **Hands-off** — in `#<repo>`: "dispatch a worker on track *name* to do *X*", or `cc <repo> <track> --go "X"`. Own branch, ends in a PR and a ping. Nothing merges without you.
6. **Dashboard** — the web page off `~/.cc/state/home.json`: what is running, what needs you, every track's cost and PR. Live and read-only.

## Who answers
| Agent | Reach it | Does |
|---|---|---|
| **box** session | DM the bot · `#box` · phone app "<box>" · `cc`, window `box` | ops, status, starting and stopping things |
| **`<repo>` planning session** | `#<repo>` · `#<repo>-updates` · phone app `<repo>` · `cc <repo>` | plans, dispatches tracks, reviews PRs; never auto-commits; merges only on the owner's standing grant, after reviewing and running the gates — otherwise merging is theirs |
| **`<repo>/<track>` session** | its `🧵 <repo>/<track>` thread in `#<repo>` · phone app `<repo>/<track>` · `cc <repo> <track>` | one unit of work on its own worktree and branch, auto-committed every turn |
| **headless worker** (`--go`) | no chat — `cc <repo> <track>` shows its window, log `~/.cc/state/<repo>/<track>/loop.log` | runs a task file; `DONE` → PR, `BLOCKED` → a request to the planning seat, which answers it or asks you |

Everything is named after what it owns, so the Slack channel, the phone-app entry and the tmux window share one name. (Claude.ai and Claude Desktop check in through the owner's **Slack** connector.)


## Where an answer goes
Split by **kind**, not by the surface the text appeared on. Answering is `~/CLAUDE.md`'s rule — reply where you were asked. This section is the other kind: what to do when you *need* the owner.
- **Needing the owner** — a decision, an approval, a permission, a blocked action you cannot finish without them — leaves the terminal, whatever surface the problem appeared on, and goes to whoever can settle it: a session below the planning seat asks the seat (`cc-notify --ask`, or its `--decision` becomes that same request); the seat settles what is its own and asks the owner with rung 1 for what only they can decide; rung 2 `reply(needs_owner=true)` is how the seat marks a question stalling one track, and from any session below it that call is the same request. The owner reads Slack on a phone, so a line in a terminal or a row on a board does not reach them.
- **Waiting in a terminal is not a rung.** A session with no `<channel>` tag to reply to still has `cc-notify`.
- A result they are already waiting on in a terminal stays in that terminal.

## Channels are sessions
- `#<repo>` ↔ `~/dev/<repo>`; `#<repo>-updates` the same session's automated lane; a track is a thread in `#<repo>`, not a channel (a legacy `#<repo>--<track>` still routes); DM or `#box` the box. Anything else: name a channel after a folder in `~/dev`, or map it in `~/.cc/slack/routes.json`. `cc slack mkchannel <repo>` wires the pair, private by default (`--public` opts out); an already-public one is flagged by `cc slack channels` and flipped in Slack by hand.
- **A new member project**, two doors, both ending in the daemon — a boundary has no Slack token and never makes one itself. A PERSON types `new project <name>` in a member workspace channel; it counts only from that workspace's member or the owner, so a session saying it is ignored. A SESSION runs `cc slack project <name>` inside the workspace, at most 3 an hour (a person typing the phrase is not capped). Either way the daemon opens the project's one thread in `#<workspace>` (`🧵 <workspace>/<name>`) and its board row — no channel of its own; the folder comes with the first session. The workspace half of the name comes from the caller's own socket, never from what it typed, so neither door can name another workspace's project. A THIRD door needs nobody at all: a workspace declares where its projects live in `.cc/projects` (one glob a line — a lessons workspace writes `*/COURSE.md`), and the daemon's 15-min sweep gives every directory those match its thread, through the same `ask_project` and the same 3/h cap, so a folder a member named cannot open a thread that reads as anyone else's. `cc slack mkchannel` is the unscoped admin command and stays the owner's.
- A channel that maps to nothing becomes a session on its first message: `~/dev/<name>` is created with a `CLAUDE.md`, a git repo and the `.cc/member-facing` marker — read-only outside its folder, so changes come to you in the thread. 3 new dirs an hour; never for DMs, `#approvals`/`#alerts` or archived channels. To promote one: rename the folder, add a remote, drop the marker.
- A track is one thread in `#<repo>`, opened when `--go` starts it (`🧵 <repo>/<track> — <title>`): the worker's lines, its landing line and anything you say to it live there, and no channel is made for it. A reply in the thread reaches the track's session while one runs; a headless worker cannot chat and a finished track has nothing running, so either way the reply goes to the `<repo>` session prefixed `[asked in <repo>/<track>'s thread …]` and is answered back in the thread — no notice line. A message never starts a track session; `!restart <repo>/<track>` does.
- `cc <repo> --orch <alias>` starts a peer orchestrator — named `<alias>@<repo>` everywhere you read it — in its own `#<repo>-<alias>-<id>` channel (the brief becomes the purpose, the link lands in the thread that asked); `@<alias>` / `@main` hand a thread over. Archived when it exits, or after 24 h gone.

## Marks — whose turn it is
- Nothing marks a thread root or nudges you: a reply that needs your decision opens with ❓ and mentions you, and that is the whole signal. `!restart <target>` if a session looks wedged.
- On your message: 👀 it has it · a reaction back is its answer (👍 yes, or done with nothing to say · 👎 no · ✅ done · ❌ can't · 🤔 unclear) · "⏳ starting…" queued until the session is up.
- A reaction on a session's message reaches it as `👍 on your 07:12 reply: "…"` — 👍 act, don't ask again · 👎 no.
- Your 📌 on any message marks the thread "revisit": not an ask, nothing nags, nothing counts it as owed — it is kept until you take the 📌 off, shown on the dashboard (TO REVISIT), in the daily digest and by `cc-slack revisit`.

## Who may do what
- **A 🔐 permission prompt from a MEMBER workspace goes to `#<control repo>-threads`**, not to her own channel: a member cannot answer one, so a prompt left there waits on the owner happening to look (a session sat blocked on `Bash(curl:*)` twice on 2026-09-08). `yes <id>` / `no <id>` in that thread still reaches HER session — the answer is routed by request id, not by the channel — and the session reading that lane can answer it in place with `cc slack permission <id> yes|no`, which says in the thread what it decided and who did. Every other target's prompt goes where it always did.
- Channel membership is the access control: anyone in a channel that routes to a session is answered as `role="member"`. A member cannot authorize an owner gate, answer a 🔐 prompt, run a `!` command, or hand a thread over; the session does the ungated part and hands the rest to the planning seat (`cc-notify`, or `reply(needs_owner)`, which files a request), and that seat asks you if only you can decide. A member's 👍 on a card in `#approvals` queues that PR for landing (repos outside `CC_SELF_LAND_REPOS`); a PR on a protected path is queued only by your own 👍 on its 🔐 card in `#approvals`; a repo in `CC_SELF_LAND_REPOS` lands its own green PRs. A non-owner DM gets 👋 and one line. Each non-owner also gets a private `#<handle>` pair and a `~/dev/<handle>` workspace on a daily budget (`cc-slack member add`).
- `.cc/member-facing` in a folder makes every session started there role=member by code (`cc-guard`): no dispatching work, no reading the box's secrets, no re-wiring Slack; `cc-notify` stays open so it can ask the planning seat (its `--owner` is that request too, never your DM). A blocklist, not a sandbox — for isolation use `ccbox`.
- 🔐 prompts arrive as `🔐 … Reply "yes abcde" or "no abcde"`; first answer, Slack or terminal, wins. Owner gates are hard-blocked for autonomous sessions and asked of interactive ones.
- Each finished track's PR is one card — in `#<repo>-updates` for a repo that lands itself (`CC_SELF_LAND_REPOS`: a landing record, nothing to tap unless that landing stops and asks for your 👍, which the card itself takes — that starts the landing again and approves nothing), in `#approvals` for any other, where your 👍 queues a landing job — the gates against the PR's own head, then a review pass, then merge, install and restart — with the outcome in the thread. A failed merge posts in `#<repo>-updates` and is injected into the repo's session; the PR is what needs you, and that is a card you tap.

## What crosses the wire
- Your photos and files land in `~/.cc/slack/files/`; a shared message arrives as one bracketed line. Sessions @-mention people (handle, name or first name; channel members first; nobody is invited) — an unresolved handle goes out as code and the sender is told `REACHED NOBODY`. A session attaches a render or screenshot with the `file` tool (own folder, `/tmp` or `~/.cc/slack/files`, 25 MB); from the shell, `cc-slack post --file <path> [--to …] [--thread <ts>]`. Same parity for `cc-slack history|thread|edit|unsay|pin|unpin|canvas`; posts show as `<box> · <session>`.
- Commands that need no session: `!pause` `!resume` `!restart box|<repo>[/track]|slack|tmux` `!reboot` (`!restart tmux` and `!reboot` confirm first — RUNBOOK). Anything else you type is a message to the session.
- Unasked: `cc-notify` into `#<repo>-updates` (`--decision` climbs to `#<repo>` with a mention); boot, limit, model-switch and audit lines into `#alerts`; the daily digest into `#<box>-updates`; an escalation (`--owner`) from the planning seat is a DM and a phone push; from a member-facing session or a member workspace it is a request to the planning seat, never your DM and never the channel it came from. `#approvals` holds only what needs your OK: a repo that lands itself keeps its PR cards in its `-updates` lane. A usage limit pauses workers and shows as `⏳ Claude usage limit until …`. `cc-audit` (03:30 UTC) puts its report on the control repo's canvas and its findings on the board (`audit-`/`arch-`/`delete-…` rows); nothing is fixed until you say so.

## Cheat sheet
    Slack #myapp "what's the state of step1?"   that repo's session answers in a thread
    #myapp-updates                              the same session's automated posts and progress
    Slack "yes kqmtr"                           approve a relayed permission prompt
    Slack DM "what's running?"                  the box session answers
    ssh <box>; cc myapp                         the same session, terminal
    cc myapp step2 --go "…"                     headless worker → PR → ping in #myapp

## Nothing answers?
`cc slack status` → `journalctl --user -u cc-slackd -n 30`. A session started before `cc slack on` has no channel: restart it — `cc handoff <repo> <track>` for a track (a fresh session takes over, then retires it), `cc rc restart` for the box, `tmux kill-window -t main:<repo>` then `cc <repo>` for a planning session.
