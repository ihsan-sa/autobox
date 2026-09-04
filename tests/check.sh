#!/usr/bin/env bash
# tests/check.sh — static checks over core/. bin/ and config/ are LIVE via symlinks: run before committing on
# the default branch (the pre-commit hook does). Extra python files to compile can be passed as arguments
# (a private overlay adds its own that way).
set -e; cd "$(dirname "$0")/.."
sh=(); py=()
for f in bin/* install.sh ccbox/*.sh; do [ -f "$f" ] || continue; head -1 "$f" | grep -q bash && sh+=("$f"); head -1 "$f" | grep -q python && py+=("$f"); done
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
# cc-msg's runs a whole fake box — its own HOME, a stub tmux whose pane text is a file, a stub ps — over the
# prompts it may answer, the ones it must never touch, and the spool: no tmux of this box's is read or typed at.
# cc-spend's ticks a synthetic transcript in a HOME of its own: the rates table, the offset/dedupe rules and both
# phantom rules, never this box's ledger and never a model.
# cc-econ's is fixtures of its own — a fake landing log, fake run files, a throwaway git repo — over the two
# splits that decide every number it prints: worker vs fix round, and which population a dollar belongs to.
# cc-time's is the clock rule itself: a known UTC instant rendered in a zone of its own (never this box's), and
# cc-notify's one Slack-facing stamp driven through in log-only mode with the UTC log line beside it.
# cc-broker's runs the classifier, the grouping and the debounce against a stub for the daemon's door in a HOME
# of its own: no session on this box is written to, and no message of this box's is read.
# cc-guard's runs the gates themselves against fixtures in a HOME of its own, with the owner's two real
# doors (cc-notify, cc-slack) stubbed: which denies page and which never do, and the worker kill fence.
# cc-pause's builds a whole box per case under a HOME of its own — two projects, a stub `cc` and a stub `cc-loop`
# — over pause, resume and the cold start a reboot is: the flag is a file, so a fresh process with no memory of
# the pause still reads it. Its fixture projects carry this process's pid in their names, because `on` finds the
# loops to stop with pgrep over the whole process table and a shared name would signal a real project's worker.
# cc-brief's is fixtures too — briefs it writes itself, a board and a throwaway git repo under a temp dir, and
# CC_BRIEF_FAKE standing in for the judge at every case, so the fast gate never reaches a model.
# cc-gh-token's mints against an API of its own on localhost, signing with an RSA key it generates: minting,
# reuse, the expiry margin, an absent key and which remotes it answers for. No GitHub App of this box's is
# read, nothing leaves the machine, and its token cache is a file under the temp dir, never the real one.
for c in cc-units cc-settings cc-board cc-broker cc-config cc-msg cc-spend cc-econ cc-time cc-guard cc-brief cc-gh-token cc-pause; do o=$("bin/$c" selfcheck 2>&1) || { echo "$o"; exit 1; }; done
echo "check.sh: OK (${#sh[@]} shell, $((${#py[@]} + 1 + $#)) python, json, units, manifests)"
