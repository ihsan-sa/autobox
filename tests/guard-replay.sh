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
#      refs/lander/base when the repo has it, else origin/main) and through this tree's. A row the base refuses and
#      this tree lets through is a REGRESSION and fails the run. The lander runs checks in a one-commit tree with no
#      origin/main and puts main at the PR's base there as refs/lander/base (run.materialise), so a landing runs it.
#      Skipped, and said so, when GUARD_BASE=none or, with no GUARD_BASE set, neither ref is in the repo (main's own
#      health run, which has no other side); a GUARD_BASE set to a ref the repo lacks fails. A PR that changes this
#      script, guard-probe.jsonl, guard-replay.jsonl or the box set is also run with main's copies of them laid
#      over a fresh copy of its tree (the lander's run.PINNED), so it cannot weaken the check, drop rows or delete
#      the base ref this run reads and pass.
#
# This tree's guard is the PR's code and runs as this script's user, so before any of it runs the script is parsed
# whole (main), every row set is read into memory, the base is resolved to a commit and every base verdict is taken.
# Opus' read of #1453: a cc-guard that deleted refs/lander/base on its first call made step 3 skip and the run pass.
# The lander also fails a run that leaves refs/lander/base moved or gone (run.base_kept).
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
main(){
R=$(cd "$(dirname "$0")/.." && pwd); G=$R/bin/cc-guard
given=1
if [ -z "${GUARD_BASE:-}" ]; then
  given=0; GUARD_BASE=origin/main; (cd "$R" && git rev-parse -q --verify 'refs/lander/base^{commit}') >/dev/null 2>&1 && GUARD_BASE=refs/lander/base
fi
v=0; [ "${1:-}" = -v ] && v=1
for f in guard-replay.jsonl guard-probe.jsonl; do
  [ -s "$R/tests/$f" ] || { echo "guard-replay: tests/$f is missing or empty, so nothing would be checked" >&2; exit 1; }
done
T=$(mktemp -d -p /tmp); trap 'rm -rf "$T"' EXIT
mapfile -t CORE < "$R/tests/guard-replay.jsonl"; mapfile -t PROBE < "$R/tests/guard-probe.jsonl"; PEND=(); BOXR=()
[ -f "$R/tests/guard-replay-pending.jsonl" ] && mapfile -t PEND < "$R/tests/guard-replay-pending.jsonl"
BOX=$R/../tests/guard-replay-box.jsonl; hasbox=0; [ -f "$BOX" ] && { hasbox=1; mapfile -t BOXR < "$BOX"; }
# the base as a commit, and its guard (with its own cc-guard-argv beside it, which cc-guard finds next to itself, when
# it has one) copied out, while no code of this tree's has run: a base that resolves but has no guard fails
B=; [ "$GUARD_BASE" = none ] || B=$(cd "$R" && git rev-parse -q --verify "$GUARD_BASE^{commit}" 2>/dev/null) || B=
[ -n "$B" ] || [ $given = 0 ] || [ "$GUARD_BASE" = none ] \
  || { echo "guard-replay: GUARD_BASE=$GUARD_BASE is not a commit in this repo, so the differential cannot run" >&2; exit 1; }
mkdir -p "$T/base"
if [ -n "$B" ]; then
  (cd "$R" && git show "$B:./bin/cc-guard") > "$T/base/cc-guard" 2>/dev/null \
    || { echo "guard-replay: base $GUARD_BASE ($B) has no bin/cc-guard" >&2; exit 1; }
  (cd "$R" && git show "$B:./bin/cc-guard-argv") > "$T/base/cc-guard-argv" 2>/dev/null && chmod +x "$T/base/cc-guard-argv" \
    || rm -f "$T/base/cc-guard-argv"
fi
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

# the base side of the differential (3), before this tree's guard first runs
BRC=()
if [ -n "$B" ]; then
  for i in "${!PROBE[@]}"; do
    l=${PROBE[$i]}; [ -n "$l" ] || continue
    BRC[$i]=$(run "$T/base/cc-guard" "$(jq -r .role <<<"$l")" "$(jq -r .cmd <<<"$l")")
  done
fi

# 1. the core set
for l in "${CORE[@]}"; do
  [ -n "$l" ] || continue
  [ "$(jq -r '.pseat // false' <<<"$l")" = true ] && continue
  [ "$(jq -r '.fixture // ""' <<<"$l")" = never-touch ] && continue
  role=$(jq -r .role <<<"$l"); cmd=$(jq -r .cmd <<<"$l"); exp=$(jq -r .expect <<<"$l")
  rc=$(run "$G" "$role" "$cmd" "$(jq -r '.cwd // ""' <<<"$l")" "$(jq -r 'if has("mws") then .mws else "alice" end' <<<"$l")" "$(jq -r '.marker // false' <<<"$l")")
  got=pass; [ "$rc" = 2 ] && got=refuse; [ "$rc" = 0 ] || [ "$rc" = 2 ] || got="rc$rc"
  if [ "$got" = "$exp" ]; then pass=$((pass+1)); [ $v = 1 ] && say ok "$role" "$cmd"
  else fail=$((fail+1)); say "FAIL replay (want $exp, got $got)" "$role" "$cmd"; fi
done
echo "core replay: $pass passed, $fail failed"
[ $((pass+fail)) -gt 0 ] || { echo "guard-replay: the core replay checked no row" >&2; exit 1; }
pend=0; still=0
for l in "${PEND[@]}"; do
  [ -n "$l" ] || continue; pend=$((pend+1))
  [ "$(run "$G" "$(jq -r .role <<<"$l")" "$(jq -r .cmd <<<"$l")" "$(jq -r '.cwd // ""' <<<"$l")" "$(jq -r 'if has("mws") then .mws else "alice" end' <<<"$l")")" = 2 ] && still=$((still+1))
done
echo "pending refusals (awaiting a policy call): $pend rows, $still still refused, not counted"

# 2. the box's true catches, when the overlay has them
b=0
if [ $hasbox = 1 ]; then
  for l in "${BOXR[@]}"; do
    [ -n "$l" ] || continue
    role=$(jq -r .role <<<"$l"); cmd=$(jq -r .cmd <<<"$l")
    if [ "$(run "$G" "$role" "$cmd")" = 2 ]; then pass=$((pass+1)); b=$((b+1))
    else fail=$((fail+1)); say "FAIL box (want refuse)" "$role" "$cmd"; fi
  done
  echo "box replay: $b of $(printf '%s\n' "${BOXR[@]}" | grep -c .) refused"
else echo "box replay: no tests/guard-replay-box.jsonl here (the public core has none), skipped"; fi

# 3. the differential against the base guard, whose verdicts (BRC) were taken first
if [ -n "$B" ]; then
  n=0
  for i in "${!PROBE[@]}"; do
    l=${PROBE[$i]}; [ -n "$l" ] || continue
    role=$(jq -r .role <<<"$l"); cmd=$(jq -r .cmd <<<"$l"); n=$((n+1))
    m=${BRC[$i]}; h=$(run "$G" "$role" "$cmd")
    if ! { [ "$m" = 0 ] || [ "$m" = 2 ]; } || ! { [ "$h" = 0 ] || [ "$h" = 2 ]; }; then
      fail=$((fail+1)); say "FAIL probe (base $m, head $h: an exit that is neither pass nor refuse)" "$role" "$cmd"
    elif [ "$m" = 2 ] && [ "$h" != 2 ]; then reg=$((reg+1)); fail=$((fail+1)); say "REGRESSION (base 2, head $h)" "$role" "$cmd"
    else pass=$((pass+1)); [ $v = 1 ] && say "base $m head $h" "$role" "$cmd"; fi
  done
  echo "differential: $n rows against $GUARD_BASE (${B:0:12}), $reg REGRESSION"
  [ "$n" -gt 0 ] || { echo "guard-replay: the differential checked no row" >&2; fail=$((fail+1)); }
elif [ "$GUARD_BASE" = none ]; then echo "differential: GUARD_BASE=none, skipped"
else echo "differential: base $GUARD_BASE is not in this repo (the lander gave no base: a run on main itself), skipped; run it in a clone"; fi

echo "guard-replay: $pass passed, $fail failed"
[ "$fail" = 0 ]
}
# one line, read whole before main runs: nothing this tree's guard writes into this file afterwards is ever read
main "$@"; exit $?
