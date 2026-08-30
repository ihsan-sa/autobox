# The private overlay

autobox is the generic half. Everything that names *your* box — its hardware, IPs, SSIDs, tokens, Slack workspace —
stays in a private repo that carries this tree as `core/`. `install.sh` detects that: if it sits at `<repo>/core/install.sh`
it also links the overlay's `home/*.md` and `bin-private/*`, and prefers the overlay's `config/etc/` over `templates/config/etc/`.

```
my-box/                 private repo (the overlay)
├── core/               this tree, added with: git subtree add --prefix=core <autobox-url> main --squash
├── home/               CLAUDE.md RUNBOOK.md COMMS.md USAGE.md  → symlinked into ~
├── bin-private/        scripts only this box has            → symlinked into ~/bin
├── config/etc/         this box's sshd / unattended-upgrades
├── config/systemd-user/  user units only this box runs      → symlinked into ~/.config/systemd/user (enable by hand)
├── docs/               this box's incidents, audits, guides
└── tests/check-extra.sh   optional: static checks for the files above (the pre-commit hook runs it after core's)
```

A bare clone of autobox works too — it just has no overlay, so `install.sh` links `core/bin` and nothing else.

## What a new box fills in

1. **`home/`** — copy `core/templates/home/*.md` to `<overlay>/home/` and replace every `<placeholder>`:
   `<box>` (the box's name, must match `hostname -s` or whatever you set as `CC_BOX`), `<user>`, `<owner-email>`,
   `<control-repo>`, `<tailscale-ip>`, `<tailnet>`, `<public-hostname>`, `<rescue-ip>`, `<iface>`, `<mac>`, SSIDs, hardware.
   These four files are the box's own memory: `CLAUDE.md` is what every Claude session on it reads first, so keep it
   short — the machine's specs, power and disk history belong in `<overlay>/docs/hardware.md`, which it links.
2. **`~/.cc/config`** (mode 600, never committed) — `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_OWNER_ID`,
   `SLACK_WEBHOOK`, `SLACK_CHANNEL`, `NTFY_TOPIC`, and `CC_BOX` if the box's name is not `hostname -s`.
   `cc slack setup` and `cc-notify setup` write these for you.
3. **Slack app** — create one from `core/slack/app-manifest.json` (replace the `<box>` placeholders in `display_information`
   and `bot_user`), install it to your workspace, then `cc slack setup --bot xoxb-… --app xapp-… --owner-email you@example.com`
   and `cc slack on`. One app per box; Socket Mode, so no inbound port.
4. **`ccbox/env`** — `install.sh` seeds it from `env.example`. Owner name/email for git inside the sandbox and any
   `GH_TOKEN` / project tokens live there, chmod 600, gitignored — never in `core/`.
5. **`config/etc/`** (optional) — if this box's sshd or unattended-upgrades policy differs from
   `core/templates/config/etc/`, put your versions here and `install.sh --etc` uses them instead.
6. **`bin-private/`** (optional) — scripts that only make sense on this box (they get linked into `~/bin` like core's).
7. **`config/systemd-user/`** (optional) — `*.service` / `*.timer` for what only this box runs (typically driving a
   `bin-private/` script). `install.sh` links them next to core's; unlike core's it never enables them — do that once
   yourself with `systemctl --user enable --now <unit>`, so nothing starts on your box that you did not ask for.

## Keeping core in sync

From the overlay repo, on the default branch:

```
cc-publish setup <autobox-url> <your-repo>       # once: writes PUBLISH_* into ~/.cc/config
cc-publish status                                # in sync? behind?
cc-publish --dry-run                             # the exact commit it would push
git subtree pull --prefix=core <autobox-url> main --squash    # take upstream changes
```

Publishing then happens **by itself after every merge** to your default branch, and `cc-publish` is idempotent, so it is
safe to run by hand any time. It sends the *whole* `core/` tree of `origin/<default branch>` as one commit on the public
repo's tip and never picks paths — the only thing that decides what is public is where you put the file.

Nothing under `core/` may name your box — not its contents, not a file name, not the commit subject. `cc-publish` checks
all three against your user, host and repo names (add IPs, serials or a tailnet with `PUBLISH_DENY=`) and **aborts the
whole publish** on a hit rather than shipping a trimmed tree, telling you through `cc-notify`. The pre-commit hook blocks
the same strings earlier. Publishing is off until `PUBLISH_REMOTE` exists, so a bare clone of autobox never publishes.
