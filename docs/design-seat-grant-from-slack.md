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

## Selfcheck

cc-settings: grant writes one line with the rest identical, refuses a second copy, refuses under `CLAUDECODE`,
refuses a unit whose hash moved, and `check` is green after. cc-slack: grant card raised; owner's `yes … fix`
runs the writer and marks ⚙️; `no` marks ❌ and writes nothing; a non-owner's reply is refused; a session's
`cc-slack permission` on a grant card is refused. cc-guard: a session writing the file through Bash is refused.
