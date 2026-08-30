#!/usr/bin/env bash
# selftest.sh — end-to-end test of the cc layer against a throwaway local repo (bare "remote"). No API calls:
export CC_NOTIFY_LOG_ONLY=1   # never push to the owner from tests
export CC_LIMIT_MIN_WAIT=1    # cc-limit test hook: any 'wait until the usage limit resets' is capped at 1 s
# claude is stubbed (CC_CLAUDE). Safe to run anytime, INCLUDING alongside another copy of itself in another
# worktree: every run is namespaced (see $RUN below) and cleans up after itself.  Usage: tests/selftest.sh
# Exercises the bin/ THIS file ships with (a track worktree tests its own copy, not the ~/bin symlinks).
set -uo pipefail
exec </dev/null; unset CC_ROLE   # never inherit a tty (`cc` would attach tmux and swallow the run) nor a caller's worker role (the guard probes set it themselves)
B="$(cd "$(dirname "$0")/../bin" && pwd)"
pass=0; fail=0; ok(){ pass=$((pass+1)); echo "  ✓ $1"; }; bad(){ fail=$((fail+1)); echo "  ✗ $1"; }
# Every run owns a namespace ($RUN): repo name, fixture dir, notify log, usage-limit stamp, tmux windows and
# processes all carry it. Two selftests (two worktrees, one box) must never read, write or kill each other's things
# — a global `pkill` here once failed 4 tests in a run that was, on its own, green.
RUN=$$; REPO=_cctest$RUN; T=~/.cc/selftest-$RUN; mkdir -p "$T"
export CC_NOTIFY_LOG="$T/notify.log"      # not the box's own ~/.cc/notify.log: runs would count each other's lines
export CC_LIMIT_STAMP="$T/claude-limit"   # not the box's live stamp: a test limit must never make a real loop wait
MT(){ env -u TMUX TMUX_TMPDIR="$T" tmux "$@"; }   # the model section's scratch tmux server: own socket, under $T
wins(){ tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | awk -v r="$1" '$2==r || index($2,r"/")==1 {print $1}'; }
KIDS=""   # long-lived fixtures started below; the trap takes each one's whole process group, by PID, never by pattern
cleanup(){ rc=$?; trap - EXIT
  for p in $KIDS; do pg=$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')
    if [ -n "$pg" ] && [ "$pg" != "$(ps -o pgid= -p $$ | tr -d ' ')" ]; then kill -TERM -- -"$pg" 2>/dev/null; else kill -TERM "$p" 2>/dev/null; fi; done
  MT kill-server 2>/dev/null   # the scratch server and its panes die WITH the run: one `cat` fixture outlived a run by 2.5 h
  for id in $(wins "$REPO"); do tmux kill-window -t "$id"; done
  rm -rf "$T" ~/dev/$REPO ~/.cc/worktrees/$REPO ~/.cc/state/$REPO ~/.cc/boards/$REPO.json ~/.cc/boards/$REPO.lock ~/.claude/projects/$REPO-ctx
  ( exec 9>~/.claude.json.lock; flock 9; jq '.projects |= with_entries(select(.key | test("/'"$REPO"'(/|$)") | not))' ~/.claude.json > ~/.claude.json.$RUN.sel && mv ~/.claude.json.$RUN.sel ~/.claude.json ) 2>/dev/null   # leave no trust entries behind
  rm -f ~/.claude.json.$RUN.sel; exit $rc; }
trap cleanup EXIT INT TERM HUP
git init -q --bare "$T/remote.git"; git clone -q "$T/remote.git" ~/dev/$REPO 2>/dev/null
( cd ~/dev/$REPO && git config user.email t@t && git config user.name t && echo x > r.md && git add -A && git commit -qm init && git branch -M main && git push -q -u origin main && git remote set-head origin -a >/dev/null 2>&1 )
export CC_CLAUDE=/bin/true
# stub claude for cc-loop: writes a journal entry + a file, 2nd iteration says DONE
cat > "$T/fakeclaude" <<F
#!/usr/bin/env bash
st=$HOME/.cc/state/$REPO/w1; n=\$(ls \$st/runs/*.json 2>/dev/null | wc -l)
echo "iteration work \$n" > "work-\$n.txt"; echo "- \$(date -u +%T) did step \$n" >> "\$st/progress.md"
[ "\$n" -ge 2 ] && echo "STATUS: DONE" >> "\$st/progress.md"
printf '{"is_error":false,"num_turns":2,"total_cost_usd":0.01,"session_id":"x","result":"ok %s"}' "\$n"
F
# stub claude that always hits its turn cap while still doing real work (M6: capped != failed)
cat > "$T/cappedclaude" <<F
#!/usr/bin/env bash
st=$HOME/.cc/state/$REPO/w2; n=\$(ls \$st/runs/*.json 2>/dev/null | wc -l)
echo "capped work \$n" > "capped-\$n.txt"; echo "- capped iteration \$n" >> "\$st/progress.md"
printf '{"is_error":true,"subtype":"error_max_turns","num_turns":80,"total_cost_usd":0.5,"session_id":"x","result":"hit the turn cap"}'
F
# stub claude that hangs, to prove a killed loop takes its child with it (H4)
cat > "$T/sleepclaude" <<F
#!/usr/bin/env bash
echo "- sleeping iteration" >> $HOME/.cc/state/$REPO/w3/progress.md
sleep 30
printf '{"is_error":false,"num_turns":1,"total_cost_usd":0.01,"session_id":"x","result":"ok"}'
F
# stub claude that reports a usage limit on its first call and works on the second (M10: a limit is not a failure)
cat > "$T/limitclaude" <<F
#!/usr/bin/env bash
st=$HOME/.cc/state/$REPO/w4; n=\$(ls \$st/runs/*.json 2>/dev/null | wc -l)   # the loop already created THIS run's file
[ "\$n" -le 1 ] && { printf '{"is_error":true,"result":"You'"'"'ve hit your usage limit. Your limit resets at 11:40.","total_cost_usd":0}'; exit 0; }
echo "- work after the limit lifted" >> "\$st/progress.md"; echo "STATUS: DONE" >> "\$st/progress.md"
printf '{"is_error":false,"num_turns":1,"total_cost_usd":0.01,"session_id":"x","result":"ok"}'
F
chmod +x "$T/fakeclaude" "$T/cappedclaude" "$T/sleepclaude" "$T/limitclaude"
echo "== cc main + track creation =="
cd ~ && "$B/cc" $REPO >/dev/null 2>&1; sleep 1; tmux list-windows -t main -F '#W' | grep -qx "$REPO" && ok "main window created" || bad "main window"
"$B/cc" $REPO w1 >/dev/null 2>&1; sleep 1
[ -d ~/.cc/worktrees/$REPO/w1/.cc ] && [ "$(git -C ~/.cc/worktrees/$REPO/w1 symbolic-ref --short HEAD)" = track/w1 ] && ok "worktree on track/w1 with marker" || bad "worktree/branch"
grep -qxF '.cc/' "$(git -C ~/dev/$REPO rev-parse --path-format=absolute --git-common-dir)/info/exclude" && ok ".cc/ git-excluded" || bad ".cc/ exclusion"
[ "$("$B/cc-board" get $REPO w1 status)" = running ] && ok "board tracks status" || bad "board status"
echo "== checkpoint hook =="
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
# H2: a hand-deleted worktree dir stays registered in git; cc must prune + rebuild it, never stamp a plain dir
rm -rf "$wt"; "$B/cc" $REPO w1 >/dev/null 2>&1; sleep 1
[ "$(git -C "$wt" rev-parse --show-toplevel 2>/dev/null)" = "$(readlink -f "$wt")" ] && [ -f "$wt/.cc/track" ] && ok "hand-deleted worktree is rebuilt as a real worktree" || bad "worktree rebuilt as a plain dir"
# H3: repo/track names are validated — no path traversal, no options as track names
mkdir -p ~/.cc/state/${REPO}_canary; "$B/cc" rm $REPO ../${REPO}_canary >/dev/null 2>&1
[ $? != 0 ] && [ -d ~/.cc/state/${REPO}_canary ] && ok "cc rm refuses a traversing track name" || bad "cc rm traversal!"
rmdir ~/.cc/state/${REPO}_canary 2>/dev/null
"$B/cc" $REPO --go "x" >/dev/null 2>&1; [ $? != 0 ] && [ ! -d ~/.cc/worktrees/$REPO/--go ] && ok "cc refuses a track named --go" || bad "track '--go' created"
echo "== cc-context (the real number, and what refuses to run without it) =="
ctx=$("$B/cc-context" selfcheck 2>&1)
grep -q '0 failed' <<<"$ctx" && ok "cc-context selfcheck: ${ctx##*: }" || bad "cc-context selfcheck: $ctx"
export CC_CTX_RECORDS="$T/ctx" CC_CTX_BOX_MODEL=   # records under $T, and this box's own model never sizes a fixture
PD=~/.claude/projects/$REPO-ctx; mkdir -p "$PD"    # a transcript for the session the board names for w1
sid=$("$B/cc-board" get $REPO w1 session_id)
printf '{"type":"assistant","message":{"model":"claude-opus-5","usage":{"input_tokens":10,"cache_creation_input_tokens":1000,"cache_read_input_tokens":19000,"output_tokens":5}}}\n' > "$PD/$sid.jsonl"
"$B/cc-context" $REPO w1 2>&1 | grep -q '^10%  20k/200k' && ok "a track's number is read off the session the board names" || bad "cc-context $REPO w1: $("$B/cc-context" $REPO w1 2>&1)"
out=$("$B/cc" handoff $REPO w1 --over 90 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q 'under 90%' <<<"$out" && tmux list-windows -t main -F '#W' | grep -qx "$REPO/w1"; } \
  && ok "handoff --over leaves a session that is not full alone" || bad "handoff --over 90 at 10%: rc=$rc $out"
mv "$PD/$sid.jsonl" "$T/tx.jsonl"                  # nothing measurable: the answer is 'no', not a guess
out=$("$B/cc" handoff $REPO w1 --over 90 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q 'not handing off on a guess' <<<"$out" && tmux list-windows -t main -F '#W' | grep -qx "$REPO/w1"; } \
  && ok "an unmeasurable context refuses the handoff instead of guessing" || bad "unmeasurable handoff: rc=$rc $out"
mv "$T/tx.jsonl" "$PD/$sid.jsonl"
# the Stop hook is the only place the transcript path is handed over: it must record from the payload
printf '{"session_id":"%s","transcript_path":"%s","cwd":"%s"}' "$sid" "$PD/$sid.jsonl" ~/.cc/worktrees/$REPO/w1 \
  | ( cd ~/.cc/worktrees/$REPO/w1 && "$B/cc-checkpoint" )
[ -s "$T/ctx/$sid.json" ] && grep -q '"pct": 10' "$T/ctx/$sid.json" && ok "the Stop hook records the measurement it was handed" || bad "no record from the Stop hook"
grep -q 'decision' "$T/ctx/$sid.json" && bad "a session under the line was told something" || ok "under the journal line the session is left alone"
# over the line: the hook answers on stdout with the Stop decision that makes the session journal (once)
pay(){ printf '{"session_id":"%s","transcript_path":"%s","cwd":"%s"%s}' "$sid" "$PD/$sid.jsonl" ~/.cc/worktrees/$REPO/w1 "${1:-}"; }
rm -f "$T/ctx/$sid.json"
# the fixture is 20k of a 200k window, so the floors (60k/90k) are lowered out of the way for these cases
CTXP="CC_CONTEXT_WARN_MIN=0 CC_CONTEXT_HANDOFF_MIN=0"
d1=$(pay | ( cd ~/.cc/worktrees/$REPO/w1 && env $CTXP CC_CONTEXT_WARN_PCT=5 CC_CONTEXT_HANDOFF_PCT=45 "$B/cc-checkpoint" ))
{ grep -q '"decision": "block"' <<<"$d1" && grep -q "state/$REPO/w1/progress.md" <<<"$d1"; } \
  && ok "over the journal line the hook tells the session to write its handoff entry" || bad "no Stop decision: $d1"
d2=$(pay | ( cd ~/.cc/worktrees/$REPO/w1 && env $CTXP CC_CONTEXT_WARN_PCT=5 CC_CONTEXT_HANDOFF_PCT=45 "$B/cc-checkpoint" ))
[ -z "$d2" ] && ok "it is said once, not every turn" || bad "the session was told twice: $d2"
d3=$(pay ',"stop_hook_active":true' | ( cd ~/.cc/worktrees/$REPO/w1 && env $CTXP CC_CONTEXT_WARN_PCT=1 CC_CONTEXT_HANDOFF_PCT=2 "$B/cc-checkpoint" ))
[ -z "$d3" ] && ok "never while a Stop hook is already holding the session" || bad "blocked a session that was already held: $d3"
# past the handoff line with something in flight: PENDING, and the session keeps working — nothing is restarted
d4=$(pay ',"background_tasks":[{"id":"x"}]' | ( cd ~/.cc/worktrees/$REPO/w1 && env $CTXP CC_CONTEXT_WARN_PCT=1 CC_CONTEXT_HANDOFF_PCT=2 "$B/cc-checkpoint" ))
{ grep -q 'PENDING' <<<"$d4" && grep -q 'background task' <<<"$d4" && tmux list-windows -t main -F '#W' | grep -qx "$REPO/w1"; } \
  && ok "past the handoff line with work in flight the handoff is pending, not taken" || bad "pending handoff: $d4"
grep -q '"pending": true' "$T/ctx/$sid.json" && ok "the pending handoff is on the record" || bad "no pending flag: $(cat "$T/ctx/$sid.json")"
# the durable record: one countable line per crossing, which line fired, and no prose to parse
[ "$("$B/cc-context" --handoffs 2>/dev/null | wc -l)" = 2 ] && ok "every crossing is one countable line on the ledger" || bad "ledger: $("$B/cc-context" --handoffs)"
"$B/cc-context" --handoffs | cut -f2 | tr '\n' ' ' | grep -q 'journal handoff-deferred' \
  && ok "the ledger says which line fired" || bad "ledger kinds: $("$B/cc-context" --handoffs | cut -f2 | tr '\n' ' ')"
out=$("$B/cc" handoff $REPO w1 --over 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q 'under the handoff line' <<<"$out"; } && ok "a bare --over uses that session's own handoff line" || bad "bare --over: rc=$rc $out"
lsout=$("$B/cc" ls 2>/dev/null); grep -q "w1.*ctx 10%" <<<"$lsout" && ok "cc ls shows how full each track is" || bad "cc ls has no ctx column"
( cd ~/.cc/worktrees/$REPO/w1 && "$B/cc-checkpoint" </dev/null )   # no payload (run by hand): still commits, records nothing new
[ -z "$(git -C ~/.cc/worktrees/$REPO/w1 status --porcelain)" ] && ok "the hook still commits when it is given no payload" || bad "checkpoint broke without a Stop payload"
unset CC_CTX_BOX_MODEL

echo "== guard =="
g(){ printf '{"tool_name":"%s","tool_input":%s,"cwd":"%s"}' "$1" "$2" "$3" | CC_ROLE=worker "$B/cc-guard" >/dev/null 2>&1; echo $?; }
[ "$(g Bash '{"command":"gh pr merge 1"}' "$wt")" = 2 ] && ok "guard blocks merge in a track (by cwd marker)" || bad "guard merge"
printf '{"tool_name":"Bash","tool_input":{"command":"gh pr merge 1"},"cwd":"%s"}' "$HOME" | "$B/cc-guard" >/dev/null 2>&1; [ $? = 0 ] && ok "guard ignores non-worker cwd" || bad "guard scope"
miss=""   # M9: the bypasses the 2026-08-27 audit walked through
for probe in 'Bash|{"command":"$(gh pr merge 1)"}' 'Bash|{"command":"bash -c \"gh pr merge\""}' 'Bash|{"command":"xargs gh pr merge"}' \
             "Bash|{\"command\":\"rm -r -f $HOME\"}" 'Bash|{"command":"rm -rf /*"}' 'Bash|{"command":"rm -rf \"$HOME/x\""}' \
             'Bash|{"command":"tmux kill-ses -t main"}' 'Bash|{"command":"pkill -f tmux"}' 'Bash|{"command":"systemctl --user restart tmux-main"}' \
             'Bash|{"command":"tmux send-keys -t main \"tmux kill-server\" Enter"}' 'Bash|{"command":"gh api /repos/x/y"}' 'Bash|{"command":"git symbolic-ref HEAD refs/heads/main"}' \
             "Edit|{\"file_path\":\"$wt/../../../../etc/passwd\"}"; do
  [ "$(g "${probe%%|*}" "${probe#*|}" "$wt")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "guard blocks all 13 bypass probes (quoting, wrappers, tmux kills, traversal)" || bad "guard bypass:$miss"
[ "$(printf '{"tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"%s"}' "$wt" | CC_ROLE=worker env PATH=/nonexistent /bin/bash "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] && ok "guard refuses when jq is missing (gates would be silently off)" || bad "guard without jq"
# member-facing: the .cc/member-facing marker alone (NO CC_ROLE — the env is a convenience) = every worker gate plus spend/leak/wiring
mf="$T/member"; mkdir -p "$mf/.cc"; : > "$mf/.cc/member-facing"; touch "$mf/note.md"
m(){ printf '{"tool_name":"%s","tool_input":%s,"cwd":"%s"}' "$1" "$2" "$3" | "$B/cc-guard" >/dev/null 2>&1; echo $?; }
MP=('Bash|{"command":"sudo apt install x"}' 'Bash|{"command":"gh pr merge 1"}' 'Bash|{"command":"cc r t --go build it"}'
    'Bash|{"command":"cc board add r t title text --go"}' 'Bash|{"command":"cc-loop r t"}' 'Bash|{"command":"claude -p do it"}'
    'Bash|{"command":"cat ~/.cc/config"}' 'Bash|{"command":"tail -5 $HOME/.ssh/id_ed25519"}'
    'Bash|{"command":"cc slack off"}' 'Bash|{"command":"cc slack mkchannel help"}'
    "Read|{\"file_path\":\"$HOME/.cc/config\"}" "Edit|{\"file_path\":\"$HOME/member-probe.txt\"}")
miss=""; for probe in "${MP[@]}"; do [ "$(m "${probe%%|*}" "${probe#*|}" "$mf")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "member-facing marker denies all 12 probes (merge/host, dispatch, secrets, Slack wiring, edit outside)" || bad "member gate misses:$miss"
miss=""; for probe in "${MP[@]}"; do [ "$(m "${probe%%|*}" "${probe#*|}" "$HOME")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "no regression: an unmarked cwd (planning session) is gated by none of them" || bad "unmarked cwd gated:$miss"
miss=""; for probe in 'Bash|{"command":"ls -la"}' 'Bash|{"command":"cc-notify -t help the owner must decide this"}' \
             'Bash|{"command":"git log --oneline -5"}' "Read|{\"file_path\":\"$mf/note.md\"}" "Edit|{\"file_path\":\"$mf/note.md\"}"; do
  [ "$(m "${probe%%|*}" "${probe#*|}" "$mf")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "member-facing session still reads, edits in place and escalates with cc-notify" || bad "member gate over-blocks:$miss"
[ "$(g Bash '{"command":"cc r t --go x"}' "$mf")" = 2 ] && ok "a marked cwd beats an inherited CC_ROLE=worker (a marker only tightens)" || bad "member marker downgraded by CC_ROLE=worker"
[ "$(printf '{"tool_name":"Bash","tool_input":{"command":"cc r t --go x"},"cwd":"%s"}' "$HOME" | CC_ROLE=member "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] && ok "CC_ROLE=member gates with no marker at all" || bad "CC_ROLE=member ignored"
[ "$(printf '{"tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"%s"}' "$mf" | CC_ROLE=member env PATH=/nonexistent /bin/bash "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] && ok "guard refuses when jq is missing for a member too (no jq = no cwd = no marker walk)" || bad "member guard without jq"
echo "== cc-notify: an escalation reaches the OWNER, not the channel it came from =="
# own HOME (the box's real config and owner id stay out of this) + a stub bot: the args cc-notify hands cc-slack ARE the routing
NH="$T/nh"; mkdir -p "$NH/bin" "$NH/.cc" "$T/chan/.cc" "$T/plain"; : > "$T/chan/.cc/member-facing"
cat > "$NH/bin/cc-slack" <<F
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$T/slack.args"
F
chmod +x "$NH/bin/cc-slack"; printf 'SLACK_BOT_TOKEN=xoxb-test\nSLACK_OWNER_ID=UOWNER\n' > "$NH/.cc/config"
N(){ w=$1; shift; : > "$T/slack.args"
     ( cd "$w" && env -u CC_NOTIFY_LOG_ONLY HOME="$NH" CC_NOTIFY_LOG="$NH/.cc/notify.log" "$B/cc-notify" "$@" >/dev/null 2>&1 ); }
N "$T/chan" "Alice needs the staging DB restored"
{ grep -q -- '-c UOWNER' "$T/slack.args" && ! grep -q -- '--route' "$T/slack.args"; } \
  && ok "a member-facing session's escalation DMs the owner, never its own channel" || bad "escalation went to the channel: $(cat "$T/slack.args")"
grep -q 'chan escalation' "$T/slack.args" && ok "it says where it came from (default title '<session dir> escalation')" || bad "escalation title: $(head -1 "$T/slack.args")"
N "$T/plain" --owner "the disk is filling up"
grep -q -- '-c UOWNER' "$T/slack.args" && ok "--owner reaches the owner from any session" || bad "--owner ignored: $(cat "$T/slack.args")"
N "$T/plain" -t "$REPO/w1 done" "PR: x"
{ grep -q -- "--route $REPO/w1 done" "$T/slack.args" && ! grep -q -- '-c ' "$T/slack.args"; } \
  && ok "no regression: an ordinary notice still routes by title (#<repo>, #alerts)" || bad "routing changed: $(cat "$T/slack.args")"
printf 'SLACK_BOT_TOKEN=xoxb-test\n' > "$NH/.cc/config"   # owner not paired
N "$T/chan" "Bob asks for an API key"
{ grep -q -- '-c #alerts' "$T/slack.args" && ! grep -q -- '--route' "$T/slack.args"; } \
  && ok "unpaired owner: the escalation falls back to #alerts, still not the member channel" || bad "unpaired escalation: $(cat "$T/slack.args")"
echo "== --say / --go / cc-loop =="
"$B/cc" $REPO w1 --say hello >/dev/null 2>&1 && bad "--say should fail with no live session" || ok "--say refuses when no session"
tmux new-window -d -t main -n "$REPO/m7" "sleep 30"; sleep 1   # M7: a headless worker's pane is a shell — typed text would run as a command
"$B/cc-msg" "$REPO/m7" "hello" >"$T/m7.out" 2>&1; [ $? != 0 ] && grep -q 'task.md' "$T/m7.out" && ok "cc-msg refuses a window with no interactive claude" || bad "cc-msg typed into a headless pane"
tmux kill-window -t "$(tmux list-windows -t main -F '#{window_id} #W' | awk -v n="$REPO/m7" '$2==n{print $1}')" 2>/dev/null
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO/w1$" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
nl0=$(wc -l < "$CC_NOTIFY_LOG" 2>/dev/null || echo 0)
CC_CLAUDE="$T/fakeclaude" "$B/cc" $REPO w1 --go "build the thing" --loop 3 >/dev/null 2>&1
for _ in $(seq 1 40); do grep -q 'STATUS: DONE' ~/.cc/state/$REPO/w1/progress.md 2>/dev/null && grep -qE 'DONE' ~/.cc/state/$REPO/w1/loop.log 2>/dev/null && break; sleep 1; done
grep -q 'STATUS: DONE' ~/.cc/state/$REPO/w1/progress.md 2>/dev/null && ok "loop ran to DONE via journal" || bad "loop DONE"
[ "$(ls ~/.cc/state/$REPO/w1/runs/*.json 2>/dev/null | wc -l)" = 2 ] && ok "loop stopped after DONE (2 iterations, not 3)" || bad "loop iteration count: $(ls ~/.cc/state/$REPO/w1/runs/*.json 2>/dev/null | wc -l)"
git -C "$T/remote.git" log --oneline track/w1 2>/dev/null | grep -q 'wip: checkpoint' && ok "loop iterations were checkpointed + pushed" || bad "loop checkpoint"
for _ in $(seq 1 30); do tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -q "$REPO/w1 done" && break; sleep 1; done   # cc-loop writes it from its tmux window, a beat after DONE
tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -q "$REPO/w1 done" && ok "owner notified on DONE (log backend)" || bad "notify"
st=$("$B/cc-board" get $REPO w1 status); [ "$st" = review ] && ok "board -> review after done (PR skipped: no gh remote)" || bad "board status after done: $st"
# P1-P4: one branch, one PR. The loop calls `cc done` when the worker writes STATUS: DONE and a session calls it when it
# finishes by hand; a squash-merge deletes the branch, so the late caller saw nothing OPEN and opened a duplicate of commits
# GitHub had already merged (#24/#25 and #29/#30 — same headRefOid). The stub gh never prints a URL from `pr create`, so
# `cc done` takes its "PR creation failed" branch and no Slack call is ever made from this section.
mkdir -p "$T/ghbin"
cat > "$T/ghbin/gh" <<'F'
#!/usr/bin/env bash
D=$(dirname "$(dirname "$0")")
case "$*" in
  *"pr list"*"--state open"*)   exit 0 ;;                                            # nothing open on this branch
  *"pr list"*"--state merged"*) [ -s "$D/merged.oid" ] && grep -qF "$(cat "$D/merged.oid")" <<<"$*" && cat "$D/merged.url"; exit 0 ;;
  *"pr create"*) echo create >> "$D/gh.create"; echo "(no url from this stub)"; exit 0 ;;
esac
exit 0
F
chmod +x "$T/ghbin/gh"; : > "$T/gh.create"; : > "$T/merged.oid"; echo "https://example.invalid/pull/29" > "$T/merged.url"
"$B/cc" $REPO w5 >/dev/null 2>&1; sleep 1
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO/w5$" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
PATH="$T/ghbin:$PATH" "$B/cc" done $REPO w5 >/dev/null 2>&1
[ "$(wc -l < "$T/gh.create")" = 1 ] && ok "cc done: nothing open and nothing merged for this branch → one PR is opened (P1)" || bad "cc done opened $(wc -l < "$T/gh.create") PRs"
git -C ~/.cc/worktrees/$REPO/w5 rev-parse track/w5 > "$T/merged.oid"   # that PR was squash-merged: same commits, branch gone
PATH="$T/ghbin:$PATH" "$B/cc" done $REPO w5 > "$T/done2.out" 2>&1
[ "$(wc -l < "$T/gh.create")" = 1 ] && grep -q 'already merged' "$T/done2.out" && ok "cc done: those commits are already merged → NO second PR, and it says which one (P2)" || bad "cc done opened a duplicate PR: $(cat "$T/done2.out")"
st=$("$B/cc-board" get $REPO w5 status); [ "$st" = merged ] && ok "cc done: the board says merged, not review-forever (P3)" || bad "board after an already-merged done: $st"
echo "more work after the merge" > ~/.cc/worktrees/$REPO/w5/after.txt   # cc done checkpoints this itself: a NEW tip
PATH="$T/ghbin:$PATH" "$B/cc" done $REPO w5 >/dev/null 2>&1
[ "$(wc -l < "$T/gh.create")" = 2 ] && ok "cc done: a commit AFTER the merge is new work → a second PR is right (P4)" || bad "cc done skipped a PR for real new commits"
( exec 9>~/.cc/worktrees/$REPO/w5/.cc/done.lock; flock 9; sleep 3 ) & lk=$!   # a first `cc done` still inside the list→create window
sleep 1; CC_DONE_LOCK_WAIT=1 PATH="$T/ghbin:$PATH" "$B/cc" done $REPO w5 > "$T/done5.out" 2>&1; rc5=$?; wait $lk 2>/dev/null
[ "$rc5" = 1 ] && grep -q 'still running' "$T/done5.out" && [ "$(wc -l < "$T/gh.create")" = 2 ] && ok "cc done: two callers at once are serialised — the second opens nothing (P5)" || bad "cc done raced itself: rc=$rc5 creates=$(wc -l < "$T/gh.create")"
# M6: is_error=true with subtype error_max_* and real output is a CAP, not a failure — the loop must keep going
"$B/cc" $REPO w2 >/dev/null 2>&1; sleep 1
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO/w2$" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
echo "do capped work" > ~/.cc/state/$REPO/w2/task.md
CC_CLAUDE="$T/cappedclaude" "$B/cc-loop" $REPO w2 --max-iter 3 --quiet >/dev/null 2>&1; rc=$?
[ "$rc" = 6 ] && [ "$(ls ~/.cc/state/$REPO/w2/runs/*.json 2>/dev/null | wc -l)" = 3 ] && ok "productive but capped iterations are not failures (ran 3, exit 6 not 5)" || bad "capped loop: rc=$rc runs=$(ls ~/.cc/state/$REPO/w2/runs/*.json 2>/dev/null | wc -l)"
grep -q 'capped' ~/.cc/state/$REPO/w2/loop.log && [ "$("$B/cc-board" get $REPO w2 status)" = blocked ] && ok "cap logged + board left blocked, not running" || bad "capped log/board status"
# H4: a killed loop must not leave claude re-parented to systemd, still editing the worktree
"$B/cc" $REPO w3 >/dev/null 2>&1; sleep 1
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO/w3$" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
echo "hang for a while" > ~/.cc/state/$REPO/w3/task.md
CC_CLAUDE="$T/sleepclaude" "$B/cc-loop" $REPO w3 --max-iter 1 --quiet >/dev/null 2>&1 & lp=$!
for _ in $(seq 1 10); do pgrep -f "$T/sleepclaude" >/dev/null && break; sleep 1; done
kill -HUP $lp 2>/dev/null; gone=no
for _ in $(seq 1 5); do sleep 1; pgrep -f "$T/sleepclaude" >/dev/null || { gone=yes; break; }; done
[ "$gone" = yes ] && ok "killing the loop kills its claude child (no orphan left in the worktree)" || { bad "orphaned claude survived the loop kill"; pkill -f "$T/sleepclaude"; }
wait $lp 2>/dev/null; "$B/cc" rm $REPO w3 >/dev/null 2>&1
echo "== usage limits (cc-limit + cc-loop) =="
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
say true "rate limit; reset in 2 minutes"; u=$(L check "$lf"); u=${u#LIMIT }; d=$((u - $(date -u +%s)))
{ [ "$d" -ge 100 ] && [ "$d" -le 140 ]; } && ok "cc-limit parses a relative reset ('in 2 minutes' -> +${d}s)" || bad "relative reset parsed to +${d}s"
L status | grep -q 'usage limit until .*Z (.*left)' && ok "cc-limit status reports the live stamp" || bad "cc-limit status while set"
L clear; [ "$(L status)" = clear ] && [ "$(L status >/dev/null; echo $?)" = 1 ] && ok "cc-limit clear -> status clear (exit 1)" || bad "cc-limit clear"
say true "API Error 429"; b1=$(L check "$lf"); say true "API Error 429"; b2=$(L check "$lf")   # no time in the message: 5 min, then 10
{ [ $(( ${b1#LIMIT } - $(date -u +%s) )) -le 320 ] && [ $(( ${b2#LIMIT } - ${b1#LIMIT } )) -ge 250 ]; } &&
  ok "cc-limit backs off 5 -> 10 min when the message carries no reset time" || bad "backoff: $b1 then $b2"; L clear
"$B/cc" $REPO w4 >/dev/null 2>&1; sleep 1
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO/w4$" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
echo "work through a usage limit" > ~/.cc/state/$REPO/w4/task.md; nl0=$(wc -l < "$CC_NOTIFY_LOG" 2>/dev/null || echo 0)
"$B/cc-limit" clear; CC_CLAUDE="$T/limitclaude" "$B/cc-loop" $REPO w4 --max-iter 2 --quiet >/dev/null 2>&1; rc=$?
runs=$(ls ~/.cc/state/$REPO/w4/runs/*.json 2>/dev/null | wc -l)
{ [ "$rc" = 0 ] && [ "$runs" = 2 ] && grep -q 'STATUS: DONE' ~/.cc/state/$REPO/w4/progress.md; } &&
  ok "a limited run is retried, not counted: 2 runs, 1 iteration, DONE (exit 0)" || bad "limit loop: rc=$rc runs=$runs"
{ grep -q 'usage limit — waiting until' ~/.cc/state/$REPO/w4/loop.log && ! grep -q '^.* error (' ~/.cc/state/$REPO/w4/loop.log; } &&
  ok "the limit was logged and did not count as an error" || bad "limit log/errs: $(grep -c 'error (' ~/.cc/state/$REPO/w4/loop.log) error lines"
n=$(tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -c "$(hostname) limit")
[ "$n" = 1 ] && ok "owner told exactly once per limit episode (title '$(hostname) limit' -> #alerts)" || bad "limit notify count: $n"
[ "$("$B/cc-limit" status)" = clear ] && ok "the stamp is cleared by the run that got through" || bad "stamp left behind"
"$B/cc" rm $REPO w4 >/dev/null 2>&1
echo "== resume/digest/rm =="
grep -q "$REPO" <<<"$("$B/cc" digest)" && ok "digest lists the track" || bad "digest"
"$B/cc" rm $REPO w1 >/dev/null 2>&1; [ ! -d ~/.cc/worktrees/$REPO/w1 ] && ok "rm removed worktree" || bad "rm"
"$B/cc" rm $REPO w2 >/dev/null 2>&1
echo "== cc-slack (local router + channel server; no Slack, no API) =="
"$B/cc-slack" selfcheck >/dev/null 2>&1 && ok "cc-slack selfcheck (mrkdwn, chunks, target detection)" || bad "cc-slack selfcheck"
export CC_SLACK_DIR="$T/slack"; mkdir -p "$CC_SLACK_DIR"
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"reply","arguments":{"chat_id":"local","text":"pong"}}}' | timeout 10 "$B/cc-slack" channel $REPO 2>/dev/null > "$T/ch.out"
grep -q '"claude/channel"' "$T/ch.out" && grep -q '"name": "reply"' "$T/ch.out" && ok "channel server: claude/channel capability + reply tool" || bad "channel handshake"
# the session prompt the host actually receives must say who may speak and what a member may not authorize
grep -q 'role=' "$T/ch.out" && grep -q 'role=\\"member\\"' "$T/ch.out" && grep -q 'CANNOT' "$T/ch.out" \
  && ok "channel server: the prompt names role=owner/member and what a member cannot authorize" || bad "member policy in the session prompt"
grep -q $'\tpost\tlocal\t' "$CC_SLACK_DIR/outbox.log" 2>/dev/null && ok "reply without a token → outbox log" || bad "outbox"
# sending a FILE from a session: the tool exists, refuses a path outside its roots, and never claims a send it did not make
FSEND=$(mktemp /tmp/ccsel-XXXXXX.png); printf 'PNGDATA' > "$FSEND"
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"file\",\"arguments\":{\"path\":\"/etc/hostname\",\"chat_id\":\"local\"}}}" "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"file\",\"arguments\":{\"path\":\"$FSEND\",\"chat_id\":\"local\",\"thread_ts\":\"1.1\",\"text\":\"the render\"}}}" | timeout 10 "$B/cc-slack" channel $REPO 2>/dev/null > "$T/ch3.out"
grep -q '"name": "file"' "$T/ch3.out" && grep -q 'outside the folders a session may send from' "$T/ch3.out" \
  && grep -q '"isError": true' "$T/ch3.out" && ok "channel server: the file tool refuses a path outside the session's roots" || bad "file tool bounds"
grep -q 'NOT sent' "$T/ch3.out" && grep -q $'\tfile\tlocal\t' "$CC_SLACK_DIR/outbox.log" \
  && ok "file to chat_id local → outbox line, and the tool says it was NOT sent" || bad "file outbox honesty"
rm -f "$FSEND"
ln -sf "$B/cc-slack" "$T/ccslackd"   # a per-run name in the daemon's argv: ours is identifiable, and no other run's pattern kill can match it
setsid nohup "$T/ccslackd" daemon --no-slack >"$T/slackd.log" 2>&1 & SD=$!; KIDS="$KIDS $SD"; sleep 1
[ "$("$B/cc-slack" inject --no-start $REPO queued-msg)" = queued ] && ok "inject with no subscriber → queued" || bad "queue"
# the channel server links to the daemon only after the host's notifications/initialized (+2 s) — feed a real MCP handshake, then hold the pipe open
rm -f "$T/fifo"; mkfifo "$T/fifo"; ( exec 3>"$T/fifo"; printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' '{"jsonrpc":"2.0","method":"notifications/initialized"}' >&3; sleep 8; exec 3>&- ) & KIDS="$KIDS $!"
CC_SLACK_CHANNEL=1 "$B/cc-slack" channel $REPO < "$T/fifo" > "$T/ch2.out" 2>/dev/null & KIDS="$KIDS $!"; sleep 3
[ "$("$B/cc-slack" inject --no-start $REPO live-msg)" = delivered ] && ok "inject with a subscriber → delivered" || bad "deliver"
sleep 5; grep -q queued-msg "$T/ch2.out" && grep -q live-msg "$T/ch2.out" && grep -q 'notifications/claude/channel' "$T/ch2.out" && ok "backlog flushed on subscribe + live event as notifications/claude/channel" || bad "channel notifications"
grep -q '"role": "owner"' "$T/ch2.out" && ok "delivered meta carries role (a local inject is owner-level)" || bad "role in delivered meta"
"$B/cc-slack" 2>&1 | grep -q -- 'PRIVATE unless --public' && "$B/cc-slack" 2>&1 | grep -q 'ANYONE who can post in a routed channel is heard' \
  && ok "help: channels are private by default; anyone in a routed channel is heard" || bad "cc-slack help policy"
"$B/cc-slack" 2>&1 | grep -q 'EVERY channel the bot is in answers' \
  && "$B/cc-slack" status 2>/dev/null | grep -q 'policy: every channel the bot is in answers' \
  && ok "help + status state the policy: every channel answers, DMs are the owner's, #approvals/#alerts are not sessions" || bad "cc-slack channel-is-a-session policy"
pg=$(ps -o pgid= -p "$SD" 2>/dev/null | tr -d ' ')   # OUR daemon, by recorded pid and its group — a bare pattern would kill another run's
if [ -n "$pg" ] && [ "$pg" != "$(ps -o pgid= -p $$ | tr -d ' ')" ]; then kill -TERM -- -"$pg" 2>/dev/null; else kill -TERM "$SD" 2>/dev/null; fi
for _ in 1 2 3 4 5; do kill -0 "$SD" 2>/dev/null || break; sleep 0.4; done; unset CC_SLACK_DIR
echo "== model fallback (cc-model + cc-limit) =="
# own HOME and own tmux server (TMUX unset, TMUX_TMPDIR into $T): the live sessions' models are never touched
MH="$T/mh"; mkdir -p "$MH/.cc/state" "$T/fb"; printf '#!/usr/bin/env bash\ncat\n' > "$T/fb/cc-loop"; chmod +x "$T/fb/cc-loop"
cat > "$T/probeclaude" <<'F'
#!/usr/bin/env bash
printf '{"is_error":false,"num_turns":1,"total_cost_usd":0.001,"result":"ok"}'
F
chmod +x "$T/probeclaude"
ME(){ env -u TMUX TMUX_TMPDIR="$T" HOME="$MH" CC_TMUX_SESSION=_ccmodel CC_MODEL_PROC=cat \
      CC_NOTIFY_LOG="$MH/.cc/notify.log" CC_LIMIT_STAMP="$MH/.cc/state/claude-limit" \
      CC_MODEL_PRIMARY='claude-fable-5[1m]' CC_MODEL_FALLBACK=claude-opus-5 "$@"; }
M(){ ME "$B/cc-model" "$@"; }
MT new-session -d -s _ccmodel -n sess 'bash -c "cat; true"'
MT new-window -d -t _ccmodel -n wkr "bash -c '$T/fb/cc-loop; true'"   # a worker pane: cc-loop is its child and claude a grandchild
sleep 1
[ "$(M status)" = fable ] && ok "cc-model status: fable while nothing is limited" || bad "cc-model status: $(M status)"
[ -z "$(M current)" ] && ok "cc-model current is empty with no override" || bad "cc-model current leaked a model"
printf '{"is_error":true,"result":"claude-fable-5: You are out of usage credits. Run /usage-credits to keep using Fable 5.","total_cost_usd":0}' > "$T/cred.json"
ME "$B/cc-limit" check "$T/cred.json" >/dev/null
{ ME "$B/cc-limit" status | grep -q 'usage limit until'; } && ok "cc-limit: an exhausted credit balance is a limit too (backoff, no reset time in the message)" || bad "cc-limit missed the credit wording"
rm -f "$MH/.cc/state/claude-limit"
printf '{"is_error":true,"result":"claude-fable-5: You have hit your usage limit. Your limit resets at 11:40.","total_cost_usd":0}' > "$T/fab.json"
ME "$B/cc-limit" check "$T/fab.json" >/dev/null
[ "$(cut -f4 "$MH/.cc/state/claude-limit")" = fable ] && ok "cc-limit records the limited model (stamp field 4)" || bad "stamp model: $(cut -f4 "$MH/.cc/state/claude-limit" 2>/dev/null)"
M status | grep -qE '^opus until [0-9]{2}:[0-9]{2}Z$' && ok "a fable limit puts the box on opus until the reset" || bad "cc-model status after a fable limit: $(M status)"
[ "$(M current)" = claude-opus-5 ] && ok "cc-model current feeds --model to new sessions and workers" || bad "cc-model current: $(M current)"
sleep 1
MT capture-pane -p -t _ccmodel:sess | grep -q '/model claude-opus-5' && ok "switch typed /model into the live interactive session" || bad "nothing typed into the session"
MT capture-pane -p -t _ccmodel:wkr | grep -q '/model' && bad "typed into a headless worker window!" || ok "headless worker window (cc-loop) skipped"
n=$(grep -c ' model' "$MH/.cc/notify.log" 2>/dev/null)
[ "$n" = 1 ] && ok "one line to the owner per switch (title '<box> model' -> #alerts)" || bad "switch notify count: $n"
ME "$B/cc-limit" check "$T/fab.json" >/dev/null   # the same limit again
[ "$(grep -c ' model' "$MH/.cc/notify.log" 2>/dev/null)" = 1 ] && ok "a second hit on the same limit is a no-op (idempotent)" || bad "switch not idempotent"
mnow=$(date -u +%s); printf 'claude-opus-5\t%s\t%s\ttest\t0\n' "$((mnow-600))" "$((mnow-60))" > "$MH/.cc/state/model-override"
: > "$MH/.cc/state/model.log"   # forget that switch: the 10-min anti-flap gap is not what this case is about
nl0=$(wc -l < "$MH/.cc/notify.log")
ME env CC_CLAUDE="$T/probeclaude" "$B/cc-model" tick
{ [ ! -f "$MH/.cc/state/model-override" ] && [ "$(M status)" = fable ]; } && ok "tick restores fable once the reset passed and the probe answered" || bad "override survived a successful probe"
sleep 1
MT capture-pane -p -t _ccmodel:sess | grep -qF '/model claude-fable-5[1m]' && ok "restore typed /model claude-fable-5[1m] into the live session" || bad "restore not typed"
n=$(tail -n +$((nl0+1)) "$MH/.cc/notify.log" | grep -c 'is back'); [ "$n" = 1 ] && ok "exactly one 'Fable back' line to the owner" || bad "restore notify count: $n"
# a live pane that mentions a limit: the probe decides, and one line fires once
cat > "$T/failprobe" <<'F'
#!/usr/bin/env bash
printf '{"is_error":true,"result":"You have hit your usage limit. Your limit resets at 11:40.","total_cost_usd":0}'; exit 1
F
chmod +x "$T/failprobe"
rm -f "$MH/.cc/state/model-override" "$MH/.cc/state/claude-limit" "$MH/.cc/state/model-seen"; : > "$MH/.cc/state/model.log"
mline(){ MT send-keys -t _ccmodel:sess -l -- "$1"; sleep 0.3; MT send-keys -t _ccmodel:sess Enter; sleep 0.5; }
mline "Claude usage limit reached. Your limit resets at 11:40."
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE="$T/probeclaude" "$B/cc-model" tick
[ "$(M status)" = fable ] && ok "a pane that mentions a limit while the model still answers does not switch" || bad "pane scan switched on a docs/question line: $(M status)"
mline "Claude usage limit reached. Your limit resets at 12:40."
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE="$T/failprobe" "$B/cc-model" tick
[ "$(M status)" = "opus until probe" ] && ok "a real limit line in a live pane switches the box (probe agrees)" || bad "pane scan: $(M status)"
rm -f "$MH/.cc/state/model-override"; : > "$MH/.cc/state/model.log"
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE="$T/failprobe" "$B/cc-model" tick
[ "$(M status)" = fable ] && ok "the same pane line never fires twice (per-window hash)" || bad "pane line fired again"
mline "Claude usage limit reached for Fable 5. Your limit resets at 13:40."
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE=/nonexistent/claude "$B/cc-model" tick
[ "$(M status)" = fable ] && ok "a pane line with a probe that cannot run does not switch (unknown, not limited)" || bad "switched on an unrunnable probe: $(M status)"
# … and that line is NOT used up: the next tick, with a probe that runs, still switches (2026-08-27: one unrunnable
# probe swallowed the only limit line of the day and the box stayed on a model that would not answer)
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE="$T/failprobe" "$B/cc-model" tick
[ "$(M status)" = "opus until probe" ] && ok "a line an inconclusive probe could not judge fires again on the next tick" || bad "pane line was consumed by an unrunnable probe: $(M status)"
rm -f "$MH/.cc/state/model-override" "$MH/.cc/state/model-seen"; : > "$MH/.cc/state/model.log"
# the CLI says a credit balance is empty, not "usage limit" — same thing for us, and it exits non-zero
cat > "$T/creditprobe" <<'F'
#!/usr/bin/env bash
printf '{"subtype":"success","is_error":true,"result":"You'"'"'re out of usage credits. Switch to another model, or manage usage credits at claude.ai/settings/usage, to continue."}'; exit 1
F
chmod +x "$T/creditprobe"
mline "You are out of usage credits. Run /usage-credits to keep using Fable 5 or /model to switch models."
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE="$T/creditprobe" "$B/cc-model" tick
[ "$(M status)" = "opus until probe" ] && ok "\"out of usage credits\" counts as limited (whatever the exit status)" || bad "credit exhaustion not treated as a limit: $(M status)"
rm -f "$MH/.cc/state/model-override" "$MH/.cc/state/model-seen"; : > "$MH/.cc/state/model.log"
# the probe's OWN run failed (its budget cap, its turn cap): unknown — never "the model is limited"
cat > "$T/budgetprobe" <<'F'
#!/usr/bin/env bash
printf '{"subtype":"error_max_budget_usd","is_error":true,"result":null}'; exit 1
F
chmod +x "$T/budgetprobe"
mline "Claude usage limit reached for Fable 5. Your limit resets at 15:40."
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE="$T/budgetprobe" "$B/cc-model" tick
{ [ "$(M status)" = fable ] && grep -q 'error_max_budget_usd' "$MH/.cc/state/model.log"; } && ok "a probe that broke on its own budget is unknown, and says so in the log" || bad "budget-capped probe misread: $(M status)"
rm -f "$MH/.cc/state/model-override"; : > "$MH/.cc/state/model.log"
# a mid-conversation /model opens a "Switch model?" confirmation: unanswered, the session sits on the dialog and stays
# on the model that will not answer (2026-08-28: that is exactly what every live session did)
MT send-keys -t _ccmodel:sess -l -- "Switch model? 1. Yes, switch to Opus 5"; sleep 0.3; MT send-keys -t _ccmodel:sess Enter; sleep 0.5
ME env CC_MODEL_DIALOG_WAIT=0.5 "$B/cc-model" switch opus "dialog case" >/dev/null 2>&1
sleep 1
MT capture-pane -p -t _ccmodel:sess | tail -n 3 | grep -qx '1' && ok "a Switch-model confirmation is answered, so the switch actually takes" || bad "the switch left the confirmation dialog open"
for id in $(MT list-windows -t _ccmodel -F '#{window_id}' 2>/dev/null); do MT kill-window -t "$id"; done   # last window gone = that scratch server is gone

echo "== cc-reconcile (board vs reality: decision table + one end-to-end apply, no network) =="
rec=$("$B/cc-reconcile" selfcheck 2>&1)
grep -q '0 failed' <<<"$rec" && ok "cc-reconcile selfcheck: ${rec##*: }" || bad "cc-reconcile selfcheck: $rec"

echo "== cc-publish: core/ publishes itself =="
PUB="$T/mirror.git"; git init -q --bare "$PUB"
cd ~/dev/$REPO || exit 1
pub(){ env CC_PUBLISH_STATE="$T" CC_NOTIFY_LOG="$T/notify.log" PUBLISH_REMOTE="$PUB" PUBLISH_REPO=$REPO PUBLISH_PREFIX=core PUBLISH_BRANCH=main PUBLISH_ALLOW=LICENSE "$B/cc-publish"; }
mkdir -p core/bin && echo generic > core/bin/tool && echo "overlay only" > private.md
git add -A && git commit -qm "core: a generic tool" >/dev/null && git push -q origin HEAD
pub >/dev/null 2>&1
[ "$(git rev-parse main:core)" = "$(git -C "$PUB" rev-parse 'main^{tree}' 2>/dev/null)" ] && ok "publishes the WHOLE prefix (published tree == core/, nothing filtered)" || bad "published tree differs from core/"
git -C "$PUB" ls-tree -r --name-only main | grep -q private.md && bad "the overlay leaked into the public repo" || ok "nothing outside core/ ships"
[ "$(git -C "$PUB" rev-list --count main)" = 1 ] && ok "one commit per publish — the private repo's own history stays private" || bad "published more than one commit"
pub 2>&1 | grep -q "already up to date" && ok "a publish with nothing new is a no-op" || bad "re-publish was not a no-op"
# the ONE veto: this box's own name inside the prefix stops the publish dead — it is never trimmed out to get past it
was=$(git -C "$PUB" rev-parse main)
echo "built for $(id -un) on $(hostname -s)" > core/bin/leak
git add -A && git commit -qm "core: a leak" >/dev/null && git push -q origin HEAD
out=$(pub 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "identity gate" <<<"$out" && [ "$(git -C "$PUB" rev-parse main)" = "$was" ]; } && ok "identity inside core/ ABORTS the publish and pushes nothing" || bad "identity gate did not stop the publish: $out"
# on a timer the same abort comes back every 15 min: it must page the owner ONCE, and still fail loudly each run
paged(){ grep -c "publish blocked" "$T/notify.log" 2>/dev/null || echo 0; }
n=$(paged); out=$(pub 2>&1); rc=$?
{ [ "$(paged)" = "$n" ] && [ $rc != 0 ] && grep -q "identity gate" <<<"$out"; } && ok "the same abort pages the owner once, not once per timer tick (it still fails loudly)" || bad "a repeated abort re-paged the owner (was $n, now $(paged))"
git rm -q core/bin/leak && git commit -qm "core: no leak" >/dev/null && git push -q origin HEAD
pub >/dev/null 2>&1
[ -f "$T/publish.notified" ] && bad "a publish that got through still remembers the old abort — it would never page again" || ok "a publish that gets through forgets the abort, so the same reason pages again if it returns"
{ [ "$(git rev-parse main:core)" = "$(git -C "$PUB" rev-parse 'main^{tree}')" ] && git -C "$PUB" ls-tree -r --name-only main | grep -qx bin/tool; } && ok "with the leak fixed the whole prefix ships again, untrimmed" || bad "publish after the fix was incomplete"
was=$(git -C "$PUB" rev-parse main); echo wip > core/bin/wip; git add -A; git commit -qm "core: never pushed" >/dev/null
pub >/dev/null 2>&1
[ "$(git -C "$PUB" rev-parse main)" = "$was" ] && ok "only origin's default branch is published — local, unpushed work is not" || bad "unpushed work reached the public repo"
git reset -q --hard origin/main
env CC_PUBLISH_STATE="$T" CC_NOTIFY_LOG="$T/notify.log" PUBLISH_REMOTE= PUBLISH_REPO=$REPO "$B/cc-publish" status 2>&1 | grep -q "publish: off" && ok "no PUBLISH_REMOTE: publishing is simply off (a bare clone never publishes)" || bad "unconfigured publish is not off"
cd ~ || exit 1
# cleanup: windows, the scratch tmux server, every fixture process, $T, the repo dirs and ~/.claude.json — the EXIT
# trap does it on every path out, including a kill, so nothing this run started can outlive it
echo "== result: $pass passed, $fail failed =="; [ $fail = 0 ]
