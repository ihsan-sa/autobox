# A seat's missing permission is granted from Slack

Row `a-seat-grant-is-answered-from-slack`, 2026-09-20. Folds `raised-planning-cannot-cc-config-set` and
`raised-a-planning-seat-cannot-install-an-approved-user-unit`.

## The problem

A box session (planning or a track) runs in auto mode. When its own layer refuses a command — an allow line
missing from `~/.claude/settings.json`, or a user unit it may not install — it gets no dialog, so it handed the
owner a command to paste at a terminal. His words: "stuff hasn't been going to the threads channel enough and I
keep having to run commands in terminal — annoying, inefficient, not scalable."

## The rule that must survive

`~/.claude/settings.json` decides what a session may do, so **no Claude session writes it** (cc-settings, "why
nothing automatic writes this file"; cc-guard names it a secret path). The one writer added here is the cc-slack
DAEMON — a systemd user unit with no Claude Code environment — acting on the owner's own Slack reply, whose identity
is checked the way `yes <id>` already is (`SLACK_OWNER_ID`). A session may only raise the card.

## The flow

1. **The seat raises the card.** `cc-slack grant allow 'Bash(cc-config set *)' [-t why]` or
   `cc-slack grant unit <path/to/name.service> [-t why]`. The daemon takes the verb only from a session of this user
   on the main socket (never a member workspace — a member has `ask`), validates the shape (one `Tool(pattern)`
   rule, never a bare `*`; a unit file under `~/dev` or `~/.cc/worktrees`, small, `.service`/`.timer`), stamps a
   five-letter id, and posts a 🔐 card in `#<ctl>-threads` with the owner's mention. The card names the exact allow
   line — or the unit file, its sha256 and the enable command — so what he approves is what gets written. Open
   grants are on disk (`grants.json`), so a card survives the daemon restart a landing causes.
2. **The owner answers on his phone.** `yes <id> fix` (a bare `yes <id>` counts the same: a grant is for good by
   nature) or `no <id>`. Anyone else gets ❌ and "only the owner can answer". `cc-slack permission <id> …` from a
   session is refused for a grant card: a seat cannot approve its own capability.
3. **The daemon writes.** First it re-reads the card — the bot's own message — and requires the exact rule (or
   the unit file and hash) to be in it: `grants.json` sits under `~/.cc/slack`, which any session of this user can
   edit, so the table is never the authority for what gets written; the card the owner read is. Then it runs `cc-settings grant allow <rule>` / `cc-settings grant unit <path> <sha256>` with
   `--by <owner> --card <id>`. cc-settings refuses under any Claude Code environment (`CLAUDECODE`, `CC_ROLE`, a
   track worktree), backs the file up, appends the ONE rule to `permissions.allow`, and re-reads its own output to
   prove everything but `.permissions.allow` (deny rules included) came through identical before it replaces the
   file. The unit route re-hashes the file (a swap between raise and approve is refused), backs up any unit already
   there, copies it into `~/.config/systemd/user/`, reloads, enables. Every grant is one line in
   `~/.cc/state/grants.log`: when, what, who, card id, backup.
4. **The card shows the outcome.** ✅⚙️ written (the thread says what and where), ❌ declined or refused with the
   reason. The raising session is told in its own channel.

## What stays refused

- A worker's or member's Bash `cc-settings apply|grant`, and a redirection, `tee`, `cp`/`mv` or `sed -i` into
  `~/.claude/settings.json`, are refused by cc-guard (until now both passed the Bash gate; the Write tool was
  refused). The planning session is ungated at cc-guard by design: its walls for this file are the auto-mode
  classifier and cc-settings' own refusal under any Claude Code environment.
- `cc-settings check` sees `permissions.allow` as unmanaged, so it stays green after a grant; a missing deny rule
  is still reported and never written.
- Grants stay narrow: one rule per card, and the rule is in the card.

## The same card for the auto-mode confirm dialog

Row `a-confirm-dialog-never-parks-a-seat`, 2026-09-22. After a run of blocked actions the auto-mode classifier puts
one call to a person: "Auto mode classifier requires confirmation for this command … Do you want to proceed?
1. Yes 2. No". A seat on it delivers nothing. cc-model's tick (1e) finds it on a live pane and reads the call from the
seat's transcript, never from the screen. A read-only call (a short list in `confirm_readonly`) gets Yes from the box.
A message can hold several calls and the CLI runs them in order, so the dialog is about the FIRST of them and a Yes
releases the rest unasked: the box answers Yes only when every unresolved call in that message reads. A message is its
`.message.id`, not its JSONL record — the CLI writes each content block as its own line under one id, and reading the
records one by one would have shown the `ls` behind a `rm -rf build` and nothing else. `confirm_readonly`
also refuses any `$`, backtick, redirection or `printf -v`, because an expansion builds a substitution the word list
never sees (`printf -v x '%s(touch p)' '$'; cat ${x@P}` runs the touch); a read-only command that needs one is a card.
What it judges has to be what the shell runs, so the command is read twice. With its quoted spans cut out, what is left
is live shell text and may hold no brace, glob or subshell. Then a quote-aware tokeniser (Python's shlex) gives the
words each command actually gets, and every check reads those words — `find . '-delete'` and `sort '-o' f f` are writes,
and an option it cannot read as a plain `-x`/`--long=value` token is a card. The tokeniser is also what cuts the
segments, on a `;`, `|`, `||` or `&&` outside quotes and nowhere else: splitting the raw text cut `sed -n '1p;wc' f`
into `sed -n '1p` and `wc' f`, each of which reads, while sed gets the one script `1p;wc` and runs it as `w c`, writing
every line of f to `./c`. So a sed script has to match `N[,M]p` in full, and text that will not tokenise (an unbalanced
quote) or carries a punctuation this list does not handle (`&`, a subshell, a redirection) is a card.
Anything else, or a call it could not read, becomes `cc-slack grant confirm '<call>' -w <window>`: the same card and
table, and the owner answers with `yes <id>` or `no <id>`. The daemon re-reads the card, then writes only his
answer to `~/.cc/state/confirm-answers/<id>`. Nothing reaches settings.json. The next tick presses that answer
while the same dialog, for the same call, still stands. After a No the seat is told not to try another route to the
same change. Only the bare "Yes" is ever pressed, never "Yes, and don't ask again", so nothing widens what the
classifier allows. The answer file is no easier to forge than a keystroke into the pane, which any session of this
user can already send, and confirm cards share one hourly cap for the box because the window they name is the caller's word.

## Selfcheck

cc-settings: grant writes one line with the rest identical, refuses a second copy, refuses under `CLAUDECODE`,
refuses a unit whose hash moved, and `check` is green after. cc-slack: grant card raised; owner's `yes … fix`
runs the writer and marks ⚙️; `no` marks ❌ and writes nothing; a non-owner's reply is refused; a session's
`cc-slack permission` on a grant card is refused; a confirm card's yes/no is recorded, never written to settings. cc-model (f):
one fixture pane per branch — a read-only call answered Yes, a write carded once, his yes and his no pressed, a
two-call message carded when its first call writes and answered Yes when both read. cc-guard: a session writing the file through Bash is refused.
