#!/usr/bin/env bash
# guard-replay.sh — replays the guard's corpora through bin/cc-guard, each call in a fixture HOME, never running one.
#
#   1. tests/guard-replay.jsonl: every row must come back as its "expect" (pass | refuse) for its role. The pass rows
#      are commands the guard must keep letting through; the refuse rows are hard limits, each refused for its role.
#      tests/guard-replay-pending.jsonl holds the refusals left for perms and the owner to rule on (expect pass): a
#      write by policy, or a misread no narrow exemption could clear, so their count is printed and they fail nothing.
#   2. ../tests/guard-replay-box.jsonl, the private overlay's true-catch set, when that file is present: every row
#      refused. The public core has no such file and skips it.
#   3. tests/guard-probe.jsonl, the differential: every row goes through the BASE guard ($GUARD_BASE, a ref, default
#      origin/main) and through this tree's. A row the base refuses and this tree lets through is a REGRESSION and
#      fails the run. Skipped, and said so, when GUARD_BASE=none or the base ref is not in this clone (the lander
#      runs checks in a one-commit tree with no origin/main, so run it in a clone to get the differential).
#
# It fails closed: a missing guard-replay.jsonl or guard-probe.jsonl fails, a corpus that checked no row fails, and a
# guard exit that is neither 0 (pass) nor 2 (refuse) fails, on the base as on this tree.
#
# Usage: tests/guard-replay.sh [-v]     -v prints every row, not just the wrong ones
# Roles: worker / track (a track worktree on branch track/t), mainwt (a track worktree on main), member (a workspace
#        under ~/dev/<mws>, default alice; mws "" = CC_ROLE=member with no workspace marker), pf / planning / norole
#        (no marker, no role). A row may set cwd (~ is the fixture HOME), and "marker":true writes a .cc/track
#        there, the way a session can inside its own worktree. pseat rows are the perms seat writing its
#        own state, which the guard knows by a live claude in that dir; cc-guard's selfcheck case 68 holds those.
#        A "fixture":"never-touch" row names the argv selfcheck's own never-touch list (192.0.2.10), which cc-guard
#        never reads, so it is left to that selfcheck. The fixture HOME holds a seat dir under ~/.cc/state/demo.
set -uo pipefail
R=$(cd "$(dirname "$0")/.." && pwd); G=$R/bin/cc-guard
GUARD_BASE=${GUARD_BASE:-origin/main}
v=0; [ "${1:-}" = -v ] && v=1
for f in guard-replay.jsonl guard-probe.jsonl; do
  [ -s "$R/tests/$f" ] || { echo "guard-replay: tests/$f is missing or empty, so nothing would be checked" >&2; exit 1; }
done
T=$(mktemp -d -p /tmp); trap 'rm -rf "$T"' EXIT
H=$T/home; WT=$H/.cc/worktrees/demo/t; MWT=$H/.cc/worktrees/demo/onmain
mkdir -p "$WT/.cc" "$MWT/.cc" "$H/bin" "$H/dev" "$T/x" "$H/.cc/state/demo/perms"
echo demo > "$WT/.cc/track"; echo demo > "$MWT/.cc/track"
git -C "$WT" init -q -b track/t; git -C "$MWT" init -q -b main
for s in cc-notify cc-slack cc-failures; do printf '#!/bin/sh\nexit 0\n' > "$H/bin/$s"; chmod +x "$H/bin/$s"; done
pass=0; fail=0; reg=0

# run <guard> <role> <cmd> [cwd] [mws] -> the guard's exit code
run(){ local g=$1 role=$2 cmd=$3 cwd=${4:-} mws=${5-alice} mk=${6:-false} js e=()
  case $role in
    worker|track) d=$WT;; mainwt) d=$MWT;;
    member) if [ -n "$mws" ]; then d=$H/dev/$mws; mkdir -p "$d/.cc"; : > "$d/.cc/member-facing"; : > "$d/.cc/member-workspace"
            else d=$H/dev; e=(CC_ROLE=member); fi;;
    *) d=$T/x;;
  esac
  [ -n "$cwd" ] && { d=${cwd/#\~/$H}; mkdir -p "$d"; [ "$mk" = true ] && { mkdir -p "$d/.cc"; : > "$d/.cc/track"; }; }
  js=$(jq -nc --arg c "$cmd" --arg d "$d" '{tool_name:"Bash",tool_input:{command:$c},cwd:$d,transcript_path:""}')
  env -u CC_ROLE -u CC_HANDOFF -u CC_HANDOFF_DIR -u CC_SLACK_ALIAS -u CC_GUARD_ROOT_PID HOME="$H" PATH="$H/bin:$PATH" \
    CC_GUARD_ASKS="$T/asks" CC_FAILURES="$T/ledger" "${e[@]}" bash "$g" <<<"$js" >/dev/null 2>"$T/err"; echo $?; }
say(){ printf '%s\t%s\t%s\n' "$1" "$2" "$(printf '%q' "${3:0:160}")"; case $1 in FAIL*|REG*) [ -s "$T/err" ] && echo "    $(head -c 200 "$T/err")";; esac; }

# 1. the core set, both sides
while IFS= read -r l; do
  [ -n "$l" ] || continue
  [ "$(jq -r '.pseat // false' <<<"$l")" = true ] && continue
  [ "$(jq -r '.fixture // ""' <<<"$l")" = never-touch ] && continue
  role=$(jq -r .role <<<"$l"); cmd=$(jq -r .cmd <<<"$l"); exp=$(jq -r .expect <<<"$l")
  rc=$(run "$G" "$role" "$cmd" "$(jq -r '.cwd // ""' <<<"$l")" "$(jq -r 'if has("mws") then .mws else "alice" end' <<<"$l")" "$(jq -r '.marker // false' <<<"$l")")
  got=pass; [ "$rc" = 2 ] && got=refuse; [ "$rc" = 0 ] || [ "$rc" = 2 ] || got="rc$rc"
  if [ "$got" = "$exp" ]; then pass=$((pass+1)); [ $v = 1 ] && say ok "$role" "$cmd"
  else fail=$((fail+1)); say "FAIL replay (want $exp, got $got)" "$role" "$cmd"; fi
done < "$R/tests/guard-replay.jsonl"
echo "core replay: $pass passed, $fail failed"
[ $((pass+fail)) -gt 0 ] || { echo "guard-replay: the core replay checked no row" >&2; exit 1; }
pend=0; still=0
if [ -f "$R/tests/guard-replay-pending.jsonl" ]; then
  while IFS= read -r l; do
    [ -n "$l" ] || continue; pend=$((pend+1))
    [ "$(run "$G" "$(jq -r .role <<<"$l")" "$(jq -r .cmd <<<"$l")" "$(jq -r '.cwd // ""' <<<"$l")" "$(jq -r 'if has("mws") then .mws else "alice" end' <<<"$l")")" = 2 ] && still=$((still+1))
  done < "$R/tests/guard-replay-pending.jsonl"
fi
echo "pending refusals (awaiting a policy call): $pend rows, $still still refused, not counted"

# 2. the box's true catches, when the overlay has them
BOX=$R/../tests/guard-replay-box.jsonl; b=0
if [ -f "$BOX" ]; then
  while IFS= read -r l; do
    [ -n "$l" ] || continue
    role=$(jq -r .role <<<"$l"); cmd=$(jq -r .cmd <<<"$l")
    if [ "$(run "$G" "$role" "$cmd")" = 2 ]; then pass=$((pass+1)); b=$((b+1))
    else fail=$((fail+1)); say "FAIL box (want refuse)" "$role" "$cmd"; fi
  done < "$BOX"
  echo "box replay: $b of $(grep -c . "$BOX") refused"
else echo "box replay: no tests/guard-replay-box.jsonl here (the public core has none), skipped"; fi

# 3. the differential against the base guard
# the base guard runs with the base's own cc-guard-argv beside it (cc-guard finds it next to itself), when it has one
mkdir -p "$T/base"
if [ "$GUARD_BASE" != none ] && (cd "$R" && git show "$GUARD_BASE:./bin/cc-guard") > "$T/base/cc-guard" 2>/dev/null; then
  (cd "$R" && git show "$GUARD_BASE:./bin/cc-guard-argv") > "$T/base/cc-guard-argv" 2>/dev/null && chmod +x "$T/base/cc-guard-argv" \
    || rm -f "$T/base/cc-guard-argv"
  n=0
  while IFS= read -r l; do
    [ -n "$l" ] || continue
    role=$(jq -r .role <<<"$l"); cmd=$(jq -r .cmd <<<"$l"); n=$((n+1))
    m=$(run "$T/base/cc-guard" "$role" "$cmd"); h=$(run "$G" "$role" "$cmd")
    if ! { [ "$m" = 0 ] || [ "$m" = 2 ]; } || ! { [ "$h" = 0 ] || [ "$h" = 2 ]; }; then
      fail=$((fail+1)); say "FAIL probe (base $m, head $h: an exit that is neither pass nor refuse)" "$role" "$cmd"
    elif [ "$m" = 2 ] && [ "$h" != 2 ]; then reg=$((reg+1)); fail=$((fail+1)); say "REGRESSION (base 2, head $h)" "$role" "$cmd"
    else pass=$((pass+1)); [ $v = 1 ] && say "base $m head $h" "$role" "$cmd"; fi
  done < "$R/tests/guard-probe.jsonl"
  echo "differential: $n rows against $GUARD_BASE, $reg REGRESSION"
  [ "$n" -gt 0 ] || { echo "guard-replay: the differential checked no row" >&2; fail=$((fail+1)); }
elif [ "$GUARD_BASE" = none ]; then echo "differential: GUARD_BASE=none, skipped"
else echo "differential: base $GUARD_BASE is not in this clone (the lander's one-commit check tree has none), skipped; run it in a clone"; fi

echo "guard-replay: $pass passed, $fail failed"
[ "$fail" = 0 ]
