#!/usr/bin/env bash
# tests/check.sh — static checks over core/. bin/ and config/ are LIVE via symlinks: run before committing on
# the default branch (the pre-commit hook does). Extra python files to compile can be passed as arguments
# (a private overlay adds its own that way).
set -e; cd "$(dirname "$0")/.."
sh=(); py=()
for f in bin/*; do [ -f "$f" ] || continue; head -1 "$f" | grep -q bash && sh+=("$f"); head -1 "$f" | grep -q python && py+=("$f"); done
bash -n "${sh[@]}"
shellcheck -S warning -e SC1090,SC1010 "${sh[@]}"
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile "${py[@]}" tests/slack_sim.py "$@"
for f in slack/*.json config/claude-settings.json config/units.json config/claude-managed.json; do jq -e . "$f" >/dev/null; done
H=$(mktemp -d); ln -s "$PWD/bin" "$H/bin"   # verify the units against THIS tree's bin/, not against what the box happens to have linked
v=$(HOME="$H" systemd-analyze --user verify config/systemd-user/*.service config/systemd-user/*.timer 2>&1 | grep -v '^\s*$' || true); rm -rf "$H"
[ -z "$v" ] || { echo "$v"; exit 1; }
# A unit nobody links is a unit that never runs. install.sh used to name each one, so this test grepped it; now
# config/units.json is the one list and `cc-units selfcheck` fails when it and config/systemd-user/ disagree in
# either direction — a new unit file without a row, or a row without a file. Both selfchecks are static: they read
# this tree and their own fixtures, never live systemd and never ~/.claude/settings.json.
# cc-board's is the same shape: the default board view's filter, and the one-authority rule for the brief, both
# against its own fixtures in a HOME of its own — never this box's board.
# cc-config's is the same: its own config file in a temp dir, never this box's — precedence, locking, and the
# one that matters, that a value like $(…) is read back as those characters and executes nothing.
for c in cc-units cc-settings cc-board cc-config; do o=$("bin/$c" selfcheck 2>&1) || { echo "$o"; exit 1; }; done
echo "check.sh: OK (${#sh[@]} shell, $((${#py[@]} + 1 + $#)) python, json, units, manifests)"
