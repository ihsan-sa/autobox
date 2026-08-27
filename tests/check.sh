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
for f in slack/*.json config/claude-settings.json; do jq -e . "$f" >/dev/null; done
v=$(systemd-analyze --user verify config/systemd-user/*.service 2>&1 | grep -v '^\s*$' || true); [ -z "$v" ] || { echo "$v"; exit 1; }
echo "check.sh: OK (${#sh[@]} shell, $((${#py[@]} + 1 + $#)) python, json, units)"
