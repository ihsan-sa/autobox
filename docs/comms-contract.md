# The comms contract

What the owner hears from the box, and how a request reaches the seat that can settle it. Written from the
2026-09-20 comms review (the private overlay keeps the review under `docs/reviews/`); the routes below are what
`cc-notify` implements, and its selfcheck holds them.

**The box handles the technical work. The owner hears what changed, what is ready, and what only they can decide.**

## Threads

A new thread is for a meaningful piece of work the owner asked for, a useful result with no existing conversation,
or an incident that affects them. It starts exactly like this:

`:thread: *Title -* _one line description_`

The title uses ordinary words: no board names, track ids, SHAs, process ids, paths or budgets. If the owner's own
message started the conversation, the box replies there instead of opening another thread.

Updates, milestones, corrections and files are replies in that thread. Most work needs only an acknowledgement and a
result. The closing reply says **what is now usable**, or **what stopped and who owns the next step**. "Done" means
the promised result was checked.

The box does not post handoffs, worker iterations, reconnects, routine merges, automatic recoveries or repeated
reminders. Technical records stay on disk (journals, logs, the board) without becoming reading assignments.

## Questions go to whoever can answer them

| request | route | who may send it |
|---|---|---|
| planner request | `cc-notify --ask` — a file under `~/.cc/requests/` and the broker, into the control repo's planning seat; never a channel | any session |
| owner choice | `cc-notify --decision` — `#<repo>`: `❓ @owner *Decision needed:* <one question>` | the control seat only; cc-msg posts the same card itself when that seat's OWN window has stopped taking keys, because a request for it would spool behind the dead pane and be stamped delivered |
| owner authorization | `cc-notify --approval` — `#approvals`: `❓ @owner 🔐 *Approval needed:* <action and consequence>` | the control seat only; cc-land's protected door posts the same card itself, because a gate is machinery and has no seat |
| work reply | the thread the work lives in | the session doing it |
| a track's end | `cc-notify -t "<repo>/<track> <done\|needs you\|round over\|…>"` — the track's own thread in `#<repo>` (its dispatcher reads there) and one `loop:` line to the planning seat; its Slack deliverable (`slack-post.md`: `thread` on line 1, an optional `file:` line) goes the same way, the file with it; its landing line too. From inside a member boundary the same call crosses the member socket as a notice (`cc-slack escalate --notice`) and the host posts it — no token in there | the loop and the lander; never a person |
| machine log | `#<repo>-updates` (`cc-notify` with no flag) | any session |

- A worker, a member session, an orch or a unit asks the planning seat. The seat settles permissions and technical
  choices within its authority.
- Only after the seat has verified it cannot proceed does it ask the owner. A `--decision`, a `needs_owner`, a
  message prefix or a member's payload is not authority: from anything but the control seat those are the same
  planner request, and the caller is told where it went — `cc-notify` in one stderr line, the `reply` tool in its
  result. That reply still goes into the thread it was asked in; what it loses is the ❓ and the mention.
- A `#<repo>-threads` channel, where one exists, is a view of that intake, not its transport. The route works with no
  channel at all.
- Permission cards keep `yes <id>`, `no <id>` and `yes <id> fix`; the card says what `fix` grants permanently. The
  owner should not need to paste terminal commands.
- Each decision has one live card. The owner's answer in its thread resolves that card and releases only the work
  waiting on it. The box does not copy a question across channels, and a need for the owner is a mention in
  `#<repo>` or `#approvals`, never a line inside a thread where only sessions talk. That reads the destination as
  well as the sender: in a `#<repo>-threads` lane even the control seat's own `needs_owner` reply goes out without
  the ❓ and the mention, and the question is raised once in `#<repo>` as the card, linking back to the thread.
- A request that reached no seat is preserved and retried (`cc-notify requests [--retry]`). "Queued" is not
  "handled": it is neither dropped nor handed to the owner instead.
- Every request and terminal event carries a durable id, so a state posts once (`--id`).

**`#approvals` holds only what needs the owner's OK.** Routine PR cards leave it: a repo that lands its own PRs
posts a landing record in `#<repo>-updates`. A protected action that still needs the owner's authority is described
as that action, even when a PR implements it, and an ordinary reaction never authorizes it.

**A command only the owner may run goes on the card itself.** When the auto-mode classifier refuses a command to
every session, the control seat posts `cc-notify --approval --run '<cmd>' "<what it does>"`. The card shows the
command and a `run:<sha256>` stamp, and the command is stored on the host under the card's ts
(`~/.cc/approvals/run/<ts>.json`, 0600). The owner's own 👍 on that card starts `cc-slack run-approved`, which checks
the record is the box user's own and unshared, its sha256 still matches, the card is the bot's, was never edited and
ends with that exact command and stamp (a stamp in the middle of a card, say in a PR title, matches nothing), and the
owner's 👍 is on it in Slack. Then it claims the card on the host (an O_EXCL `.ran` file) and in Slack (the bot's ⏳ on
the card, refused if it is already there), runs the stored text with `bash -c` as the box's user, and replies in the
thread with the exit code only. Members read `#approvals`, so the output tail goes to the owner's DM, with tokens, keys
and `NAME=secret` values masked; the whole output stays in `~/.cc/approvals/run/<ts>.ran`. It runs in a
transient user unit, so a command that restarts the daemon still reports back. A member's 👍, a second 👍, an edited
card or a changed record runs nothing, and `~/.cc/approvals/run/log` says why. Only the control seat can post such a
card: from a worker, a member workspace or any kind but `--approval`, `--run` is refused and nothing is posted.
So is a card with three backticks anywhere in it, or a command holding a control, bidi or zero-width
character, because either can make the card show one command while another runs.

**`#<repo>-updates` is the one box log lane; nobody has to read it.**

## Session style rules

```text
Write like a colleague leaving a short note to someone reading on a phone.
Lead with the result, consequence or question. Bold the one thing that matters.
Use plain words; no slogans, triplets, em-dash cadence or process narration.
Usually write one or two sentences. Add detail only when it changes a decision.
For a new work thread: :thread: *Title -* _one line description_
Reuse the person's thread; do not open a thread for every worker or repair.
Use human titles, never board names or repo/track identifiers.
Keep paths, SHAs, process ids, config keys and test counts out of routine messages.
Put technical evidence in a file or record; link it only when useful.
Reply at meaningful milestones and completion, not at every internal transition.
Do not announce handoffs, reconnects, iterations or automatic recoveries.
Handle technical choices yourself within your authority.
Send requests beyond a session's authority to the planning seat (cc-notify --ask).
Only the planning/control session escalates a verified owner-only decision.
Mark owner choices ❓ plus a mention; use #approvals for actual authorization.
Ask one clear question and explain the consequence; preserve permission reply tokens.
Do not ask the owner to relay messages, edit state files or run routine commands.
Verify before claiming something works; distinguish an idea from an available fix.
Correct a wrong claim once, in its thread, without another speculative promise.
Render human-facing times in the server's local time.
Close with the checked outcome; do not repeat the implementation history.
```
