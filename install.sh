#!/usr/bin/env bash
# install.sh — idempotent: link this core tree's scripts/configs into place on the box.
#   ./install.sh                  link everything, enable the user services
#   ./install.sh --etc            also (re)install the /etc reference configs with sudo
#   ./install.sh --no-services    link only — no systemctl/sudo (tests run this in a throwaway HOME)
# A box may keep this tree as `core/` inside a private repo — the "overlay" — and then the installer also links
# the overlay's home/*.md and bin-private/*, and uses its config/etc. A bare clone of autobox has no overlay.
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
O=""; [ "$(basename "$R")" = core ] && O="$(cd "$R/.." && pwd)"   # R = this tree, O = the private overlay or ""
etc=0; services=1
for a in "$@"; do case "$a" in
  --etc) etc=1 ;;
  --no-services) services=0 ;;
  *) echo "usage: $0 [--etc] [--no-services]" >&2; exit 2 ;;
esac; done

mkdir -p ~/bin ~/.cc/{boards,worktrees,state,slack} ~/.config/systemd/user ~/dev

# link <src> <dest> — like `ln -sfn`, except a REAL file/dir in the way is kept as <dest>.bak instead of clobbered.
link() {
  if [ -e "$2" ] && [ ! -L "$2" ]; then mv -f "$2" "$2.bak"; echo "kept the existing $2 as $2.bak"; fi
  ln -sfn "$1" "$2"
}

for f in "$R"/bin/*; do
  [ -f "$f" ] && [ -x "$f" ] || continue        # skip dirs (bin/__pycache__) and non-executables
  link "$f" ~/bin/"$(basename "$f")"
done
# prune the links THIS tree made whose target left it or is not a file (renamed/retired scripts, __pycache__).
# Only those: a dangling link the owner or another tool put in ~/bin is not the installer's to delete (it used to).
for l in ~/bin/*; do
  [ -L "$l" ] && [ ! -f "$l" ] || continue
  case "$(readlink "$l")" in "${O:-$R}"/*) rm -f "$l" ;; esac
done
if [ -n "$O" ]; then
  for f in "$O"/bin-private/*; do                # the overlay's own scripts, linked exactly like core's
    [ -f "$f" ] && [ -x "$f" ] || continue
    link "$f" ~/bin/"$(basename "$f")"
  done
  for f in "$O"/home/*.md; do                    # the overlay's ~ docs (CLAUDE.md, USAGE.md, RUNBOOK.md, COMMS.md, …)
    [ -f "$f" ] && link "$f" ~/"$(basename "$f")"
  done
fi
# ~/CLAUDE.md and the guides beside it: whatever is still absent at ~ after the overlay's links is seeded ONCE from
# templates/home/ — a copy, `<box>` and `<user>` filled in, the other <placeholders> the owner's to replace. A file
# already there (the overlay's link, or the owner's own) is never rewritten: it is the box's memory, not the installer's.
# This is what makes a bare clone a box with the same contract as any other: the autonomy norm, the approval list and the
# doc pointers arrive with the scripts, instead of being copied by hand (or not).
box=$("$R/bin/cc-config" get CC_BOX "$(hostname -s)" 2>/dev/null) || true
for f in "$R"/templates/home/*.md; do
  d=~/"$(basename "$f")"
  if [ -e "$d" ] || [ -L "$d" ]; then continue; fi
  sed "s|<box>|$box|g; s|<user>|${USER:-$(id -un)}|g" "$f" > "$d"
  echo "seeded $d from templates/home/ — fill in its <placeholders>"
done
link "$R/ccbox" ~/ccbox
link "$R/docs/WORKING.md" ~/WORKING.md          # what a session does between tasks — at ~ beside the guides it is read with
link "$R/config/tmux.conf" ~/.tmux.conf
# the live user units, from config/units.json — the ONE list (cc-mcp is retired: its unit is parked in mcp/).
# Which are linked, which are enabled and which the audit health-checks used to be three hardcoded lists in two
# files, and they had drifted apart: the model, reconcile and publish timers were enabled here and invisible to
# `cc-audit checks`. Adding a timer is now its unit files plus one row in that manifest, and nothing else.
# assigned first, on purpose: `for u in $(cmd)` does not trip set -e, so an unreadable manifest (no jq, no file)
# would print its error and go on to link NOTHING — the one failure mode a hardcoded list could not have.
core_units=$("$R/bin/cc-units" link)
for u in $core_units; do
  link "$R/config/systemd-user/$u" ~/.config/systemd/user/"$u"
done
# the overlay's own user units, for what only that box runs: linked like core's, never enabled here — which of
# them should start is the box owner's call (`systemctl --user enable --now <unit>` once, after this installer).
if [ -n "$O" ]; then
  for f in "$O"/config/systemd-user/*.service "$O"/config/systemd-user/*.timer; do
    [ -f "$f" ] || continue
    link "$f" ~/.config/systemd/user/"$(basename "$f")"
  done
fi

# ~/.claude/settings.json: this installer NEVER writes an existing one, and that is not laziness. That file holds
# `permissions`, and a hook entry runs a command on every prompt, so anything able to edit it can widen what a
# session may do — cc-guard lists it as a secret path. What the installer owes is a precise report: not "27 lines
# differ" (which weighed a theme change the same as a missing gate, and was ignored for days) but the managed
# entries that are unapplied, by name. `cc-settings apply` is the owner's own hand, at a terminal. See cc-settings.
if [ -f ~/.claude/settings.json ]; then
  "$R/bin/cc-settings" check || true   # a drifted subset must never abort the install: it is a report, not a gate
else
  mkdir -p ~/.claude; cp "$R/config/claude-settings.json" ~/.claude/settings.json; echo "installed default ~/.claude/settings.json"
fi
[ -f "$R/ccbox/env" ] || { cp "$R/ccbox/env.example" "$R/ccbox/env"; chmod 600 "$R/ccbox/env"; echo "created ccbox/env from example (add tokens)"; }
grep -qF 'PATH="$HOME/bin:$PATH"' ~/.bashrc 2>/dev/null || cat >> ~/.bashrc <<'B'

# autobox PATH — ensure local bins are found in every interactive shell (incl. tmux)
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH";; esac
case ":$PATH:" in *":$HOME/bin:"*) ;; *) PATH="$HOME/bin:$PATH";; esac
B

if [ "$services" = 1 ]; then
  sudo -n loginctl enable-linger "$USER" 2>/dev/null || true
  systemctl --user daemon-reload
  # Which units come on, and how, is `enable`/`start` in config/units.json — with the reason on each row. The two
  # the installer deliberately leaves off (cc-slackd, cc-vitals) are marked enable=owner there, not omitted here.
  enable_rows=$("$R/bin/cc-units" enable)   # likewise: read the rows before the loop, so a failure aborts the install
  while IFS=$'\t' read -r u start; do
    [ -n "$u" ] || continue
    case "$start" in
      no-block) systemctl --user enable "$u" && systemctl --user start --no-block "$u" ;;   # may wait minutes for the network: never block the installer
      now)      systemctl --user enable --now "$u" ;;
      *)        systemctl --user enable "$u" ;;
    esac
  done <<<"$enable_rows"
  # last, and non-fatal: a missing python3-venv must not cost you the links above
  [ -x ~/.cc/slack/venv/bin/python ] ||
    { python3 -m venv ~/.cc/slack/venv && ~/.cc/slack/venv/bin/pip install -q -r "$R/slack/requirements.txt" && echo "slack venv created"; } ||
    echo "warning: slack venv not created (apt install python3-venv, then re-run) — 'cc slack on' stays down until it is" >&2
fi

if [ "$etc" = 1 ]; then
  E="$R/templates/config/etc"; [ -n "$O" ] && [ -d "$O/config/etc" ] && E="$O/config/etc"   # the overlay's own /etc files win over the templates
  sudo install -m 644 "$E/52unattended-upgrades-local" /etc/apt/apt.conf.d/52unattended-upgrades-local
  h=/etc/ssh/sshd_config.d/10-hardening.conf                # test BEFORE keeping it: a bad file locks the box out
  if [ -f "$h" ]; then sudo cp -a "$h" "$h.bak"; fi         # sshd includes *.conf only, so the .bak is inert
  sudo install -m 644 "$E/10-hardening.conf" "$h"
  if ! sudo sshd -t; then
    if [ -f "$h.bak" ]; then sudo mv -f "$h.bak" "$h"; else sudo rm -f "$h"; fi
    echo "install.sh: sshd -t rejected the new $h — restored the previous sshd config, nothing changed" >&2; exit 1
  fi
  if [ -f "$E/60-rapl-readable.rules" ]; then   # the dashboard's watt figure: one read-only sysfs counter
    sudo install -m 644 "$E/60-rapl-readable.rules" /etc/udev/rules.d/60-rapl-readable.rules
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger --subsystem-match=powercap --action=change 2>/dev/null || true
  fi
  echo "/etc configs installed (sshd -t passed)"
fi
[ -n "$O" ] && git -C "$O" rev-parse --git-dir >/dev/null 2>&1 &&
  git -C "$O" config core.hooksPath "$(realpath --relative-to="$O" "$R/.githooks")" ||   # pre-commit = core/tests/check.sh on the default branch
  git -C "$R" config core.hooksPath .githooks 2>/dev/null || true                        # a bare autobox clone: hook the repo itself
echo "linked: bin/* -> ~/bin, ccbox, overlay docs, tmux.conf, user units. Packages expected: tmux git gh docker-ce jq curl python3 python3-venv bubblewrap socat shellcheck (see docs/DESIGN.md)."
