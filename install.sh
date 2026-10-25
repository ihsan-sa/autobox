#!/usr/bin/env bash
# install.sh — idempotent: link this core tree's scripts/configs into place on the box.
#   ./install.sh                  link everything, enable the user services
#   ./install.sh --etc            also (re)install the /etc reference configs with sudo
#   ./install.sh --no-services    link only — no systemctl/sudo (tests run this in a throwaway HOME)
#   ./install.sh --join <peer>    install, then record that this box is to join <peer> (a skeleton: it writes
#                                 ~/.cc/peer/join and prints what is left; no key, no network, no message yet)
# The box's name is CC_BOX from ~/.cc/config, else from the environment (then written into the config); with neither,
# install stops. It never guesses one from the hostname, and nothing here names a real box.
# A box may keep this tree as `core/` inside a private repo — the "overlay" — and then the installer also links
# the overlay's home/*.md and bin-private/*, uses its config/etc, and lays its config/claude-settings.json over
# the default when it writes a first ~/.claude/settings.json. A bare clone of autobox has no overlay.
# A script with a root-owned copy in /usr/local/bin is never linked into ~/bin, where it would shadow that copy.
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
O=""; [ "$(basename "$R")" = core ] && O="$(cd "$R/.." && pwd)"   # R = this tree, O = the private overlay or ""
etc=0; services=1; join=""
usage="usage: $0 [--etc] [--no-services] [--join <peer>]"
while [ $# -gt 0 ]; do case "$1" in
  --etc) etc=1 ;;
  --no-services) services=0 ;;
  --join) [ $# -ge 2 ] || { echo "$usage" >&2; exit 2; }; join="$2"; shift ;;
  *) echo "$usage" >&2; exit 2 ;;
esac; shift; done
# the lander names the box (and so the perms seat) from ~/.cc/config alone, never the environment or CC_CONFIG, so
# the name is read from and written to that file
boxcfg(){ env -u CC_BOX -u CC_CONFIG "$R/bin/cc-config" "$@"; }
box=$(boxcfg get CC_BOX) || box=${CC_BOX:-}
[ -n "$box" ] || { echo "install.sh: this box has no name: CC_BOX is in neither ~/.cc/config nor the environment; rerun with CC_BOX=<name>" >&2; exit 2; }
if [ -n "$join" ]; then   # checked before anything is linked, so a bad name changes nothing
  [[ $join =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || { echo "install.sh: --join wants a box name ([a-z0-9-]), not '$join'" >&2; exit 2; }
  [ "$join" != "$box" ] || { echo "install.sh: this box is $box — it cannot join itself (CC_BOX in ~/.cc/config names it)" >&2; exit 2; }
fi

mkdir -p ~/bin ~/.cc/{boards,worktrees,state,slack} ~/.config/systemd/user ~/.config/environment.d ~/dev
[ -d ~/.cc/tmp ] || mkdir -m 700 ~/.cc/tmp   # TMPDIR for every unit and session (config/environment.d/cc-tmp.conf): made before anything reads it
boxcfg get CC_BOX >/dev/null || { boxcfg set CC_BOX "$box"; echo "wrote CC_BOX=$box into ~/.cc/config"; }

# link <src> <dest> — like `ln -sfn`, except a REAL file/dir in the way is kept as <dest>.bak instead of clobbered.
link() {
  if [ -e "$2" ] && [ ! -L "$2" ]; then mv -f "$2" "$2.bak"; echo "kept the existing $2 as $2.bak"; fi
  ln -sfn "$1" "$2"
}
# linkbin <script> — link it into ~/bin, unless a root-owned regular file of that name sits in /usr/local/bin: perms
# installs hardened copies there, and ~/bin comes first on PATH, so a link would shadow one. An old link of ours goes.
rootbin=${CC_ROOT_BIN:-/usr/local/bin} rootuid=${CC_ROOT_UID:-0}   # the selftest points these at its own dir and uid
linkbin() {
  local n; n=$(basename "$1")
  if [ -f "$rootbin/$n" ] && [ ! -L "$rootbin/$n" ] && [ "$(stat -c %u "$rootbin/$n")" = "$rootuid" ]; then
    case "$(readlink ~/bin/"$n")" in "${O:-$R}"/*) rm -f ~/bin/"$n" ;; esac
    echo "skipped $n: root-owned $rootbin/$n would be shadowed by a ~/bin link"
  else link "$1" ~/bin/"$n"; fi
}

for f in "$R"/bin/*; do
  [ -f "$f" ] && [ -x "$f" ] || continue        # skip dirs (bin/__pycache__) and non-executables
  linkbin "$f"
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
    linkbin "$f"
  done
  for f in "$O"/home/*.md; do                    # the overlay's ~ docs (CLAUDE.md, USAGE.md, RUNBOOK.md, COMMS.md, …)
    [ -f "$f" ] && link "$f" ~/"$(basename "$f")"
  done
  # this machine's own facts (its network, what never to touch) live in boxes/<box>/BOX.md, one per box, so the
  # overlay's shared docs can name ~/BOX.md and each box reads its own. A box with no entry yet gets no link, and
  # loses the one an earlier install made for another box name (else it reads that machine's network as its own);
  # a ~/BOX.md the owner made, a file or a link to anywhere else, stays.
  if [ -f "$O/boxes/$box/BOX.md" ]; then link "$O/boxes/$box/BOX.md" ~/BOX.md
  else
    if [ -L ~/BOX.md ]; then case "$(readlink ~/BOX.md)" in
      "$O"/boxes/*/BOX.md) rm -f ~/BOX.md; echo "removed ~/BOX.md: it pointed at another box's facts" ;;
    esac; fi
    echo "no boxes/$box/BOX.md in the overlay — this machine's facts are not written down yet"
  fi
  # the overlay's user memory, home/claude/CLAUDE.md, becomes ~/.claude/CLAUDE.md. That is where the owner's
  # imports (@~/BOX.md, @~/OWNER.md) live: Claude Code loads user-memory imports without the "external imports"
  # dialog, which a @ in ~/CLAUDE.md raised in every new directory and every sandboxed start. A member's sandbox has
  # its own ~/.claude, so the owner's files never reach a member's context. A real file or a link elsewhere stays.
  if [ -f "$O/home/claude/CLAUDE.md" ]; then
    mkdir -p ~/.claude
    if [ -e ~/.claude/CLAUDE.md ] && { [ ! -L ~/.claude/CLAUDE.md ] || [ "$(readlink ~/.claude/CLAUDE.md)" != "$O/home/claude/CLAUDE.md" ]; }; then
      echo "kept your own ~/.claude/CLAUDE.md — the overlay's user memory (home/claude/CLAUDE.md) is not linked; import it from yours"
    else ln -sfn "$O/home/claude/CLAUDE.md" ~/.claude/CLAUDE.md; fi
  fi
fi
# ~/CLAUDE.md and the guides beside it: whatever is still absent at ~ after the overlay's links is seeded ONCE from
# templates/home/ — a copy, `<box>` and `<user>` filled in, the other <placeholders> the owner's to replace. A file
# already there (the overlay's link, or the owner's own) is never rewritten: it is the box's memory, not the installer's.
# This is what makes a bare clone a box with the same contract as any other: the autonomy norm, the approval list and the
# doc pointers arrive with the scripts, instead of being copied by hand (or not).
# A template line that is exactly {{WRITING_BLOCK}} becomes config/writing-prompt.md, the box's one writing block:
# the same file every session's system prompt and the Slack tool carry, so a template never keeps a copy of its own.
fill() { sed -e "/^{{WRITING_BLOCK}}\$/{r $R/config/writing-prompt.md" -e 'd}' "$1"; }
for f in "$R"/templates/home/*.md; do
  d=~/"$(basename "$f")"
  if [ -e "$d" ] || [ -L "$d" ]; then continue; fi
  fill "$f" | sed "s|<box>|$box|g; s|<user>|${USER:-$(id -un)}|g" > "$d"
  echo "seeded $d from templates/home/ — fill in its <placeholders>"
done
# ~/.claude/agents/: the agent types a session spawns (builder, reviewer, security-reviewer). The harness reads this
# directory, so they have to be real files there and not links into the repo — a link would put the owner's tuning of
# one straight into a commit. Copies drift, so each one gets a stamp of what was last installed: dest = stamp means
# nobody has touched it and it follows the template; dest ≠ stamp means the owner edited it, and it is kept and named,
# never overwritten. Which type is used when is docs/WORKING.md. What is installed is the template with the writing
# block filled in (fill, above), so a new block reaches an untouched agent the same way a new template does.
mkdir -p ~/.claude/agents ~/.cc/state/agents-installed
filled=$(mktemp)
for t in "$R"/templates/home/agents/*.md; do
  [ -f "$t" ] || continue
  f="$filled"; fill "$t" > "$f"
  n="$(basename "$t")"; d=~/.claude/agents/"$n"; s=~/.cc/state/agents-installed/"$n"
  if [ -L "$d" ];      then echo "left the symlink at ~/.claude/agents/$n alone — an agent type is a real file here (a cp would write through the link, and a dangling one reads as absent)"
  elif [ ! -e "$d" ];  then cp "$f" "$d"; cp "$f" "$s"; echo "installed agent $n"
  elif cmp -s "$f" "$d"; then cp "$f" "$s"                                                    # already the template: keep the stamp honest, say nothing
  elif cmp -s "$d" "$s"; then cp "$f" "$d"; cp "$f" "$s"; echo "updated agent $n from its template"
  else echo "kept your edited ~/.claude/agents/$n — the template moved on (diff it against $t)"; fi
done
rm -f "$filled"
link "$R/ccbox" ~/ccbox
link "$R/docs/WORKING.md" ~/WORKING.md          # what a session does between tasks — at ~ beside the guides it is read with
link "$R/docs/WRITING.md" ~/WRITING.md          # the writing guide config/writing-prompt.md names in its last line
link "$R/config/tmux.conf" ~/.tmux.conf
link "$R/config/environment.d/cc-tmp.conf" ~/.config/environment.d/60-cc-tmp.conf   # the box's scratch off /tmp; units see it after daemon-reload
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
  for f in "$O"/config/systemd-user/*.service "$O"/config/systemd-user/*.timer "$O"/config/systemd-user/*.path; do
    [ -f "$f" ] || continue
    link "$f" ~/.config/systemd/user/"$(basename "$f")"
  done
fi
# prune the links THIS tree made whose unit file left it (a PR deleted it): otherwise systemd keeps the dangling
# link forever, the unit sits in --failed as not-found, and every seat that reads --failed pays for it again
# (case raised-a-deleted-unit-leaves-a-dangling-link-and-a-red — #483 deleted 10 units, 2026-09-15, and none of
# their 10 links went). Same rule as the ~/bin prune above, same reason: only a link THIS tree made is ours to
# remove, never one the owner or another tool put here by hand.
pruned=""
for l in ~/.config/systemd/user/*; do
  [ -L "$l" ] && [ ! -f "$l" ] || continue
  case "$(readlink "$l")" in "${O:-$R}"/*) rm -f "$l"; pruned="$pruned ${l##*/}" ;; esac
done
# ...and the links `systemctl --user enable` wrote for such a unit into *.wants/ and *.requires/: those are what
# keep timers.target pointing at the dead timer, so they, not the bare unit link, are what put it in --failed.
# Same scope: a dangling link whose target is in this tree, or is a unit link the loop above just removed.
for l in ~/.config/systemd/user/*.wants/* ~/.config/systemd/user/*.requires/*; do
  [ -L "$l" ] && [ ! -e "$l" ] || continue
  t=$(readlink "$l")
  case "$t" in
    "${O:-$R}"/*) rm -f "$l"; pruned="$pruned ${l##*/}" ;;
    "$HOME"/.config/systemd/user/*) case " $pruned " in *" ${t##*/} "*) rm -f "$l" ;; esac ;;
  esac
done

# ~/.claude/settings.json: this installer NEVER writes an existing one, and that is not laziness. That file holds
# `permissions`, and a hook entry runs a command on every prompt, so anything able to edit it can widen what a
# session may do — cc-guard lists it as a secret path. What the installer owes is a precise report: not "27 lines
# differ" (which weighed a theme change the same as a missing gate, and was ignored for days) but the managed
# entries that are unapplied, by name. `cc-settings apply` is the owner's own hand, at a terminal. See cc-settings.
if [ -f ~/.claude/settings.json ]; then
  "$R/bin/cc-settings" check || true   # a drifted subset must never abort the install: it is a report, not a gate
else
  # The overlay's config/claude-settings.json holds only the box's own keys (its autoMode entries, say) and wins
  # key by key over the default; a list in it replaces the default's whole list rather than appending to it.
  mkdir -p ~/.claude
  if [ -n "$O" ] && [ -f "$O/config/claude-settings.json" ]; then
    jq -s '.[0] * .[1]' "$R/config/claude-settings.json" "$O/config/claude-settings.json" > ~/.claude/settings.json.new
    mv ~/.claude/settings.json.new ~/.claude/settings.json; echo "installed default ~/.claude/settings.json, with the overlay's keys"
  else cp "$R/config/claude-settings.json" ~/.claude/settings.json; echo "installed default ~/.claude/settings.json"; fi
fi
[ -f "$R/ccbox/env" ] || { cp "$R/ccbox/env.example" "$R/ccbox/env"; chmod 600 "$R/ccbox/env"; echo "created ccbox/env from example (add tokens)"; }
grep -qF 'PATH="$HOME/bin:$PATH"' ~/.bashrc 2>/dev/null || cat >> ~/.bashrc <<'B'

# autobox PATH — ensure local bins are found in every interactive shell (incl. tmux)
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH";; esac
case ":$PATH:" in *":$HOME/bin:"*) ;; *) PATH="$HOME/bin:$PATH";; esac
B
# cc-try's overlay ahead of ~/bin, in its own block so a box whose ~/.bashrc already has the one above gets it too
grep -qF 'PATH="$HOME/.cc/try/bin:$PATH"' ~/.bashrc 2>/dev/null || cat >> ~/.bashrc <<'B'

# autobox try overlay — tools `cc-try on` put live from a green, unlanded PR, ahead of ~/bin (empty otherwise)
case ":$PATH:" in *":$HOME/.cc/try/bin:"*) ;; *) PATH="$HOME/.cc/try/bin:$PATH";; esac
B

if [ "$services" = 1 ]; then
  sudo -n loginctl enable-linger "$USER" 2>/dev/null || true
  systemctl --user daemon-reload
  # A pruned unit is STOPPED too: a timer whose file left the tree is still loaded and armed after the reload, and
  # it fires its service (now not-found) every tick until somebody stops it — cc-msg.timer and cc-sweep.timer, retired
  # into cc-broker.timer on 2026-10-03, would have. Then a pruned unit that was in failed state stays listed in
  # --failed until reset, even after the reload.
  # shellcheck disable=SC2086  # $pruned splits into unit names on purpose
  [ -z "$pruned" ] || systemctl --user stop $pruned 2>/dev/null || true
  # shellcheck disable=SC2086
  [ -z "$pruned" ] || systemctl --user reset-failed $pruned 2>/dev/null || true
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
  # tmux-main's ExecCondition skips the start when a session "main" is already up outside the unit, so the loop
  # above passed; say so once, because nothing restarts that server if it dies until the unit owns it again.
  if ! systemctl --user is-active --quiet tmux-main.service && tmux has-session -t =main 2>/dev/null; then
    echo "tmux-main: session main runs on a tmux server started outside tmux-main.service; the unit adopts it at the next box restart"
  fi
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
  sudo install -d -m 0755 /run/sshd   # sshd -t needs it; with ssh.socket a fresh box has none until sshd first runs
  if ! sudo sshd -t; then
    if [ -f "$h.bak" ]; then sudo mv -f "$h.bak" "$h"; else sudo rm -f "$h"; fi
    echo "install.sh: sshd -t rejected the new $h — restored the previous sshd config, nothing changed" >&2; exit 1
  fi
  if [ -f "$E/60-rapl-readable.rules" ]; then   # the dashboard's watt figure: one read-only sysfs counter
    sudo install -m 644 "$E/60-rapl-readable.rules" /etc/udev/rules.d/60-rapl-readable.rules
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger --subsystem-match=powercap --action=change 2>/dev/null || true
  fi
  if [ -f "$E/60-io-uring.conf" ]; then   # io_uring for root only: cc-member-v2's walk cannot see a closed registered ring
    sudo install -m 644 "$E/60-io-uring.conf" /etc/sysctl.d/60-io-uring.conf
    sudo sysctl -q -p /etc/sysctl.d/60-io-uring.conf ||
      echo "install.sh: kernel.io_uring_disabled not applied: this kernel may predate the setting (6.6)" >&2
  fi
  if [ -f "$E/claude-bwrap" ] && [ -f "$E/claude-bwrap-path.json" ]; then   # Claude Code's Bash sandbox under the AppArmor userns restriction: see the profile's header
    b=/usr/local/libexec/claude-bwrap                       # a copy, so re-run --etc after a bubblewrap update
    a=/etc/apparmor.d/claude-bwrap ms=/etc/claude-code/managed-settings.d/50-claude-bwrap.json
    k=$(mktemp -d)                                          # a re-run that fails puts the working pair back; never a .bak in apparmor.d, which loads at boot
    if [ -f "$b" ] && [ -f "$a" ]; then sudo cp -a "$b" "$k/copy" && sudo cp -a "$a" "$k/profile"; fi
    sudo install -D -o root -g "$(id -gn)" -m 0750 /usr/bin/bwrap "$b"   # 0750: only the owner's uid may use the userns it grants
    sudo install -m 644 "$E/claude-bwrap" "$a"
    if ! sudo apparmor_parser -r "$a"; then
      if [ -f "$k/copy" ] && [ -f "$k/profile" ]; then                    # the kernel kept the old profile; the files go back to match it
        sudo cp -a "$k/copy" "$b" && sudo cp -a "$k/profile" "$a"
        sudo rm -rf "$k"
        echo "install.sh: apparmor_parser rejected the new claude-bwrap — restored the previous profile and copy, sandbox.bwrapPath unchanged" >&2; exit 1
      fi
      sudo rm -rf "$k"; sudo rm -f "$a" "$b" "$ms"          # no copy left behind, so no setting may name it
      echo "install.sh: apparmor_parser rejected claude-bwrap — removed it, the copy and sandbox.bwrapPath" >&2; exit 1
    fi
    sudo rm -rf "$k"
    sudo install -D -m 644 "$E/claude-bwrap-path.json" "$ms"   # bwrapPath is honoured from managed settings only
  fi
  echo "/etc configs installed (sshd -t passed)"
fi
# git rerere, for every clone on the box. A track branch is a chain of wip checkpoints, so rebasing one onto a moved
# base replays EVERY checkpoint through the same conflicting lines: #194 wanted the same two lines resolved seven
# times and was merged instead, to resolve them once. rerere records the first resolution and replays it for the rest
# of that rebase. It does NOT help across two SEPARATE merges of a moved base — the sides differ each time and rerere
# matches on their content. Global and not per-repo, because the box rebases in every clone under ~/dev and in their
# worktrees, and the next clone would be missed; global git config is otherwise none of this installer's business, so
# it writes ONLY when the owner has said nothing — an explicit true or false is his answer and stands.
# rerere.autoUpdate is deliberately left off: a replayed resolution is still staged by hand, because one recorded
# wrong replays silently. Inspect it with `git rerere status` / `git rerere diff`, drop one with
# `git rerere forget <path>`, drop all with `rm -r "$(git rev-parse --git-path rr-cache)"`.
[ -n "$(git config --global --get rerere.enabled 2>/dev/null)" ] || git config --global rerere.enabled true || true   # a git that cannot write must not cost the links above
# The GitHub orgs this box may not touch (~/.cc/github-deny, a box fact, never in this tree): the credential helper
# first for github.com, and one url.insteadOf per listed org onto the refusing remote helper, both in the owner's global
# git config, written idempotently and only on a box that HAS a list. Re-run after editing the list. cc-github-deny says the rest.
"$R/bin/cc-github-deny" install || echo "warning: cc-github-deny install failed — the git layers of the org deny list are not wired; run it by hand" >&2
[ -n "$O" ] && git -C "$O" rev-parse --git-dir >/dev/null 2>&1 &&
  git -C "$O" config core.hooksPath "$(realpath --relative-to="$O" "$R/.githooks")" ||   # pre-commit = core/tests/check.sh on the default branch
  git -C "$R" config core.hooksPath .githooks 2>/dev/null || true                        # a bare autobox clone: hook the repo itself
# --join: the skeleton of bringing up a second box (docs/architecture/second-box.md in the overlay). Today it only
# writes down the intent, so the steps still to come (the peer key, the introduction card, the overlay bundle) have
# somewhere to start from, and says plainly that none of them has run.
if [ -n "$join" ]; then
  mkdir -p ~/.cc/peer && chmod 700 ~/.cc/peer
  grep -qx "peer=$join" ~/.cc/peer/join 2>/dev/null ||   # a rerun keeps the first ask and its time
    printf 'box=%s\npeer=%s\nasked=%s\n' "$box" "$join" "$(date -u +%FT%TZ)" > ~/.cc/peer/join
  echo "join: $box is set to join $join (~/.cc/peer/join). Not built yet: the peer key, the link and the introduction card, so nothing has contacted $join."
fi
echo "linked: bin/* -> ~/bin, ccbox, overlay docs, tmux.conf, the scratch TMPDIR, user units. Packages expected: tmux git gh docker-ce jq curl python3 python3-venv bubblewrap socat shellcheck (see docs/DESIGN.md)."
