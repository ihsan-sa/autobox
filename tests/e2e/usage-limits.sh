#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# usage-limits.sh — the stanza "usage limits (cc-limit + cc-loop)", run alone on the fixtures it stands on.
. "$(dirname "$0")/lib.sh"
. "$(dirname "$SELF")/green.sh"   # this stanza calls what green.sh defines
# ── fixture: cc main + track creation
if stanza "cc main + track creation" always; then
cd ~ && "$B/cc" $REPO >/dev/null 2>&1; sleep 1; tmux list-windows -t main -F '#W' | grep -qx "$REPO" && ok "main window created" || bad "main window"
"$B/cc" $REPO w1 >/dev/null 2>&1; sleep 1
[ -d ~/.cc/worktrees/$REPO/w1/.cc ] && [ "$(git -C ~/.cc/worktrees/$REPO/w1 symbolic-ref --short HEAD)" = track/w1 ] && ok "worktree on track/w1 with marker" || bad "worktree/branch"
grep -qxF '.cc/' "$(git -C ~/dev/$REPO rev-parse --path-format=absolute --git-common-dir)/info/exclude" && ok ".cc/ git-excluded" || bad ".cc/ exclusion"
[ "$("$B/cc-board" get $REPO w1 status)" = running ] && ok "board tracks status" || bad "board status"
# A TRACK IS CUT FROM THE PROJECT'S BASE, NOT FROM WHATEVER THE REMOTE CALLS ITS DEFAULT. GitHub makes the first branch
# pushed into a new repository its default, so a workspace's origin/HEAD came to name another project's TRACK, and the
# next track was cut from that — carrying a whole other project's tree into a fresh repository (2026-09-04). The board
# records the base and cc-land already lands against it; creation asks the same place.
( cd ~/dev/$REPO && git checkout -q -b other && echo carpet > carpet.txt && git add -A && git commit -qm "another project's tree" \
  && git push -q origin other:track/other && git checkout -q main && git branch -q -D other ) >/dev/null 2>&1
git -C ~/dev/$REPO fetch -q origin; git -C ~/dev/$REPO symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/track/other
"$B/cc" $REPO w9 >/dev/null 2>&1; sleep 1
{ [ ! -e ~/.cc/worktrees/$REPO/w9/carpet.txt ] && git -C ~/.cc/worktrees/$REPO/w9 merge-base --is-ancestor origin/main HEAD; } \
  && ok "a new track is cut from the board's base even when origin/HEAD names a track branch" \
  || bad "track w9 was cut from origin/HEAD: another project's tree came with it"
git -C ~/dev/$REPO symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main
fi
# ── fixture: checkpoint hook
if stanza "checkpoint hook" always; then
echo hi > ~/.cc/worktrees/$REPO/w1/a.txt; ( cd ~/.cc/worktrees/$REPO/w1 && "$B/cc-checkpoint" )
git -C "$T/remote.git" branch | grep -q track/w1 && ok "checkpoint committed + pushed track branch" || bad "checkpoint push"
echo junk > ~/dev/$REPO/junk.txt; ( cd ~/dev/$REPO && "$B/cc-checkpoint" ); git -C ~/dev/$REPO status --short | grep -q junk && ok "checkpoint no-op on primary worktree" || bad "primary worktree touched!"
# H1: a session that repoints HEAD at the default branch must not get its work committed+pushed there
wt=~/.cc/worktrees/$REPO/w1; m0=$(git -C "$T/remote.git" rev-parse main)
( cd "$wt" && git symbolic-ref HEAD refs/heads/main && echo a > a.txt && "$B/cc-checkpoint" )
[ "$(git -C "$T/remote.git" rev-parse main)" = "$m0" ] && [ -s "$wt/.cc/checkpoint.err" ] && ok "checkpoint refuses a HEAD repointed at main (remote main untouched)" || bad "checkpoint pushed a rewritten HEAD!"
( cd "$wt" && git symbolic-ref HEAD refs/heads/track/w1; rm -f a.txt "$wt/.cc/checkpoint.err" )
printf 'x\n' > "$wt/.env.local"; ( cd "$wt" && "$B/cc-checkpoint" )
[ -s "$wt/.cc/checkpoint.err" ] && ! git -C "$wt" log -1 --name-only 2>/dev/null | grep -q '\.env\.local' && ok "checkpoint refuses secret-looking files (.env.local)" || bad "secret committed"
rm -f "$wt/.env.local" "$wt/.cc/checkpoint.err"
touch "$wt/.cc/push.err"; lsout=$("$B/cc" ls 2>/dev/null)   # capture, don't pipe: grep -q would SIGPIPE cc and pipefail would call that a failure
grep -q 'push!' <<<"$lsout" && ok "cc ls surfaces a failed push" || bad "push.err invisible"; rm -f "$wt/.cc/push.err"
# ── the lease. 2026-08-31: a track rebased its own branch, the plain push was rejected non-fast-forward, and it
# finished green with everything committed and NO PR — only the watchdog saw it. A track branch has exactly one
# writer, so its own rewrite has to land; a write it did NOT make has to stop it dead, and out loud.
echo pre > "$wt/pre.txt"; ( cd "$wt" && "$B/cc-checkpoint" )   # a commit of OUR OWN to rewrite below: later cases still read the branch this suite built above
( cd "$wt" && git commit -q --amend -m "rewritten by a rebase" )   # what a rebase leaves behind: a diverged branch
echo rebased > "$wt/b.txt"; ( cd "$wt" && "$B/cc-checkpoint" )
{ [ "$(git -C "$T/remote.git" rev-parse track/w1)" = "$(git -C "$wt" rev-parse HEAD)" ] && [ ! -f "$wt/.cc/push.err" ]; } \
  && ok "checkpoint pushes a branch this worktree rebased — the lease holds, no non-fast-forward dead end" || bad "a rebased branch never reached the remote"
git clone -q "$T/remote.git" "$T/foreign" 2>/dev/null   # somebody ELSE writes to that branch: the one case the lease exists for
( cd "$T/foreign" && git config user.email o@o && git config user.name o && git checkout -q track/w1 \
  && echo not-ours > f.txt && git add -A && git commit -qm "a write this track did not make" && git push -q origin track/w1 )
fw=$(git -C "$T/remote.git" rev-parse track/w1)
( cd "$wt" && git commit -q --amend -m "and this track rebases again" )   # diverged too, so a plain push could not have landed either
echo more > "$wt/c.txt"; ( cd "$wt" && "$B/cc-checkpoint" )
[ "$(git -C "$T/remote.git" rev-parse track/w1)" = "$fw" ] && ok "a foreign write is NOT overwritten — the lease refuses rather than force" || bad "the lease clobbered somebody else's commit"
{ grep -q 'push refused' "$wt/.cc/push.err" && grep -q '^STATUS: BLOCKED: push refused' ~/.cc/state/$REPO/w1/progress.md \
  && "$B/cc-board" show $REPO 2>/dev/null | grep -q 'push refused'; } \
  && ok "...and says so in all three places at once: push.err (cc ls), the journal (STATUS: BLOCKED stops the loop) and the board" \
  || bad "the refusal was silent somewhere — err=$(grep -c refused "$wt/.cc/push.err" 2>/dev/null) journal=$(grep -c 'STATUS: BLOCKED' ~/.cc/state/$REPO/w1/progress.md 2>/dev/null) board=$("$B/cc-board" show $REPO 2>/dev/null | grep -c 'push refused')"
echo again > "$wt/c2.txt"; ( cd "$wt" && "$B/cc-checkpoint" )   # the hook fires again next turn (with work, or it never reaches the push) and the branch is still blocked
[ "$(grep -c '^STATUS: BLOCKED: push refused' ~/.cc/state/$REPO/w1/progress.md)" = 1 ] && ok "a hook firing every turn does not spam the journal with the same refusal" || bad "duplicate STATUS lines: $(grep -c '^STATUS: BLOCKED' ~/.cc/state/$REPO/w1/progress.md)"
( cd "$wt" && git fetch -q origin && git rebase -q origin/track/w1 >/dev/null 2>&1 )   # the human answer: take the foreign commit in, then carry on
echo after > "$wt/d.txt"; ( cd "$wt" && "$B/cc-checkpoint" )
{ [ "$(git -C "$T/remote.git" rev-parse track/w1)" = "$(git -C "$wt" rev-parse HEAD)" ] && [ ! -f "$wt/.cc/push.err" ]; } \
  && ok "once the foreign commit is rebased in, the very next checkpoint pushes again (the block is not sticky)" || bad "still blocked after the branch was reconciled"
rm -rf "$T/foreign"
# H2: a hand-deleted worktree dir stays registered in git; cc must prune + rebuild it, never stamp a plain dir
# THE RELAUNCH MUST FIND W1'S TRANSCRIPT. `cc __run` on a started session with no transcript mints a NEW session_id,
# a second or more later in its own window. The cc-context fixture below reads the id after this, so under load it
# read the old one and every cc-context case said 'no transcript' (the #463 and #465 landings, 2026-09-12). With a
# transcript there, the relaunch resumes the id it has; the fixture fills the file in.
PD=~/.claude/projects/$REPO-ctx; mkdir -p "$PD"; : > "$PD/$("$B/cc-board" get $REPO w1 session_id).jsonl"
rm -rf "$wt"; "$B/cc" $REPO w1 >/dev/null 2>&1; sleep 1
[ "$(git -C "$wt" rev-parse --show-toplevel 2>/dev/null)" = "$(readlink -f "$wt")" ] && [ -f "$wt/.cc/track" ] && ok "hand-deleted worktree is rebuilt as a real worktree" || bad "worktree rebuilt as a plain dir"
# H3: repo/track names are validated — no path traversal, no options as track names
mkdir -p ~/.cc/state/${REPO}_canary; "$B/cc" rm $REPO ../${REPO}_canary >/dev/null 2>&1
[ $? != 0 ] && [ -d ~/.cc/state/${REPO}_canary ] && ok "cc rm refuses a traversing track name" || bad "cc rm traversal!"
rmdir ~/.cc/state/${REPO}_canary 2>/dev/null
"$B/cc" $REPO --go "x" >/dev/null 2>&1; [ $? != 0 ] && [ ! -d ~/.cc/worktrees/$REPO/--go ] && ok "cc refuses a track named --go" || bad "track '--go' created"
fi
# ── top level, between stanzas
export CC_STATUSLINE_DIR="$T/statusline" CC_CONTEXT_HANDOFF_TOKENS=150000 CC_CTX_BOX_MODEL=   # status-line files under $T, and this box's own model never sizes a fixture
mkdir -p "$CC_STATUSLINE_DIR"
PD=~/.claude/projects/$REPO-ctx; mkdir -p "$PD"    # a transcript for the session the board names for w1 (and see H2: it must exist before a relaunch)
sid=$("$B/cc-board" get $REPO w1 session_id)
printf '{"type":"assistant","message":{"model":"claude-opus-5","usage":{"input_tokens":10,"cache_creation_input_tokens":1000,"cache_read_input_tokens":19000,"output_tokens":5}}}\n' > "$PD/$sid.jsonl"
# ── top level, between stanzas
export CC_HANDOFF_DIR="$T/handoff" CC_CTX_RECORDS="$T/ctx" CC_HANDOFF_RETIRE_GRACE=1 CC_HANDOFF_DRAIN=1   # never the box's own records — CC_CTX_RECORDS is
# ── the stanza
if stanza "usage limits (cc-limit + cc-loop)"; then
L(){ HOME="$T/lh" CC_LIMIT_STAMP="$T/lh/claude-limit" "$B/cc-limit" "$@"; }; mkdir -p "$T/lh"; lf="$T/lim.json"; miss=""   # own HOME: the table never touches the box's real stamp
say(){ printf '{"is_error":%s,"result":"%s","total_cost_usd":0}' "$1" "$2" > "$lf"; }
while IFS='|' read -r want iserr text; do [ -z "$want" ] && continue
  say "$iserr" "$text"; L check "$lf" >/dev/null; [ "$?" = "$want" ] || miss="$miss [$text]"; L clear; done <<'CASES'
0|true|You've hit your usage limit. Your limit resets at 11:40.
0|true|5-hour limit reached; resets 2pm (America/Toronto)
0|true|rate limit exceeded, reset in 35 minutes
0|true|429 Too Many Requests; resets at 2026-12-01T11:40:00Z
0|true|API Error 429
0|true|overloaded_error: server is overloaded
1|false|did the work, all good
1|true|fatal: connection refused by 127.0.0.1
CASES
: > "$T/empty.json"; printf 'HTTP 429 Too Many Requests\n' > "$T/lim.err"
L check "$T/empty.json" "$T/lim.err" >/dev/null || miss="$miss [stderr-only 429]"; L clear
[ -z "$miss" ] && ok "cc-limit check: 6 limit phrasings + stderr-only detected, 2 non-limits ignored" || bad "cc-limit check:$miss"

# t0 is the clock cc-limit itself reads (CC_LIMIT_NOW), not one taken after `L check` returns: under load the
# gap between the fixture write and this test's own `date` call stretched past 30s and reds every landing on
# branches that never touch cc-limit ('+89s', '+90s' — see the row that fixed this). Pinning `now` makes the
# parse deterministic: u is exactly t0+120 regardless of how long the subprocess took to run.
say true "rate limit; reset in 2 minutes"; t0=$(date -u +%s); u=$(CC_LIMIT_NOW=$t0 L check "$lf"); u=${u#LIMIT }; d=$((u - t0))
{ [ "$d" -ge 100 ] && [ "$d" -le 140 ]; } && ok "cc-limit parses a relative reset ('in 2 minutes' -> +${d}s)" || qbad cc-limit "relative reset parsed to +${d}s"
L status | grep -q 'usage limit until .*Z (.*left)' && ok "cc-limit status reports the live stamp" || bad "cc-limit status while set"
L clear; [ "$(L status)" = clear ] && [ "$(L status >/dev/null; echo $?)" = 1 ] && ok "cc-limit clear -> status clear (exit 1)" || bad "cc-limit clear"
# The record/resume state machine — arm, resume, first_seen, nudged_recently and the exit-code contract — is
# only exercised here. It lives in the selftest and not in check.sh's static list because it forks real
# processes and sleeps.
chk cc-limit
say true "API Error 429"; b1=$(L check "$lf"); say true "API Error 429"; b2=$(L check "$lf")   # no time in the message: 5 min, then 10
{ [ $(( ${b1#LIMIT } - $(date -u +%s) )) -le 320 ] && [ $(( ${b2#LIMIT } - ${b1#LIMIT } )) -ge 250 ]; } &&
  ok "cc-limit backs off 5 -> 10 min when the message carries no reset time" || bad "backoff: $b1 then $b2"; L clear
"$B/cc" $REPO w4 >/dev/null 2>&1; sleep 1
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO/w4$" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
echo "work through a usage limit" > ~/.cc/state/$REPO/w4/task.md; nl0=$(wc -l < "$CC_NOTIFY_LOG" 2>/dev/null || echo 0)
"$B/cc-limit" clear
# The record path gets its own files and NO timer for this one run. `check` ends in a scan of the live tmux
# session, and this call is under the REAL HOME with a real stamp: without these four the scan would write the
# box's own ~/.cc/state/limit-interrupted for any session whose pane carries the wording — a source file quoting
# it is enough — arm a real one-shot, and type "usage limit lifted" into a live session (review of #171). The
# stamp itself stays real, because the assertions below read it.
CC_LIMIT_RECORD="$T/lh/limit-interrupted" CC_LIMIT_NUDGED="$T/lh/limit-nudged" CC_LIMIT_SEEN="$T/lh/limit-seen" \
  CC_LIMIT_ARM=- CC_CLAUDE="$T/limitclaude" "$B/cc-loop" $REPO w4 --max-iter 2 --quiet >/dev/null 2>&1; rc=$?
runs=$(ls ~/.cc/state/$REPO/w4/runs/*.json 2>/dev/null | wc -l)
{ [ "$rc" = 0 ] && [ "$runs" = 2 ] && grep -q 'STATUS: DONE' ~/.cc/state/$REPO/w4/progress.md; } &&
  ok "a limited run is retried, not counted: 2 runs, 1 iteration, DONE (exit 0)" || bad "limit loop: rc=$rc runs=$runs"
{ grep -q 'usage limit — waiting until' ~/.cc/state/$REPO/w4/loop.log && ! grep -q '^.* error (' ~/.cc/state/$REPO/w4/loop.log; } &&
  ok "the limit was logged and did not count as an error" || bad "limit log/errs: $(grep -c 'error (' ~/.cc/state/$REPO/w4/loop.log) error lines"
n=$(tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -c "$(hostname) limit")
[ "$n" = 0 ] && ok "a limit episode posts nothing to the owner: the wait is in the loop log above" || bad "limit notify count: $n"
[ "$("$B/cc-limit" status)" = clear ] && ok "the stamp is cleared by the run that got through" || bad "stamp left behind"
"$B/cc" rm $REPO w4 >/dev/null 2>&1
# A STOP FILE WRITTEN DURING THE PRE-ITERATION LIMIT WAIT IS READ WHEN THE WAIT ENDS, before anything is charged (review
# of #541: that wait is up to 6 h, and the file was read only after the iteration it then started — a full model call).
# A stamp another run set binds this loop (same cwd, one observer), so it waits at its door; the stop file is written the
# moment the log says so, inside a 3 s wait; the loop must then end on it with NO run. Own track, own stamp, cleared after.
"$B/cc" $REPO w23 >/dev/null 2>&1; sleep 1
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO/w23$" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
echo "stop me while I wait" > ~/.cc/state/$REPO/w23/task.md; rm -f ~/.cc/state/$REPO/w23/stop
printf '{"is_error":true,"result":"rate limit; reset in 2 minutes","total_cost_usd":0}' > "$T/w23-lim.json"
"$B/cc-limit" check "$T/w23-lim.json" >/dev/null   # the stamp, keyed to this cwd — the loop below runs from the same one
( for _ in $(seq 100); do grep -q 'waiting before starting' ~/.cc/state/$REPO/w23/loop.log 2>/dev/null && break; sleep 0.1; done
  echo "wasted" > ~/.cc/state/$REPO/w23/stop ) &
CC_LIMIT_MIN_WAIT=3 CC_LIMIT_RECORD="$T/lh/limit-interrupted" CC_LIMIT_NUDGED="$T/lh/limit-nudged" CC_LIMIT_SEEN="$T/lh/limit-seen" CC_LIMIT_ARM=- \
  CC_CLAUDE="$T/limitclaude" "$B/cc-loop" $REPO w23 --max-iter 2 --quiet >/dev/null 2>&1; rc=$?; wait
runs=$(ls ~/.cc/state/$REPO/w23/runs/*.json 2>/dev/null | wc -l)
{ [ "$rc" = 14 ] && [ "$runs" = 0 ] && grep -q 'waiting before starting' ~/.cc/state/$REPO/w23/loop.log && grep -q 'exit 14: stopped by .*/w23/stop' ~/.cc/state/$REPO/w23/loop.log; } \
  && ok "a stop file written while the loop waits out a limit at its door is read when the wait ends: exit 14 with NO run — the iteration the wait was holding is never charged" \
  || bad "stop during limit wait: rc=$rc runs=$runs log: $(tail -3 ~/.cc/state/$REPO/w23/loop.log 2>/dev/null | cut -c1-160)"
"$B/cc-limit" clear; "$B/cc" rm $REPO w23 >/dev/null 2>&1
fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
