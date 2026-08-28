#!/usr/bin/env bash
# selftest.sh — end-to-end test of the cc layer against a throwaway local repo (bare "remote"). No API calls:
export CC_NOTIFY_LOG_ONLY=1   # never push to the owner from tests
export CC_LIMIT_MIN_WAIT=1    # cc-limit test hook: any 'wait until the usage limit resets' is capped at 1 s
# claude is stubbed (CC_CLAUDE). Safe to run anytime; cleans up after itself.  Usage: tests/selftest.sh
# Exercises the bin/ THIS file ships with (a track worktree tests its own copy, not the ~/bin symlinks).
set -uo pipefail
exec </dev/null; unset CC_ROLE   # never inherit a tty (`cc` would attach tmux and swallow the run) nor a caller's worker role (the guard probes set it themselves)
B="$(cd "$(dirname "$0")/../bin" && pwd)"
pass=0; fail=0; ok(){ pass=$((pass+1)); echo "  ✓ $1"; }; bad(){ fail=$((fail+1)); echo "  ✗ $1"; }
REPO=_cctest; T=~/.cc/selftest; rm -rf "$T" ~/dev/$REPO ~/.cc/worktrees/$REPO ~/.cc/state/$REPO ~/.cc/boards/$REPO.json ~/.cc/boards/$REPO.lock; mkdir -p "$T"
cp ~/.cc/state/claude-limit "$T/stamp.bak" 2>/dev/null || true   # never wipe a LIVE usage-limit stamp: snapshot, restore at the end
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
git init -q --bare "$T/remote.git"; git clone -q "$T/remote.git" ~/dev/$REPO 2>/dev/null
( cd ~/dev/$REPO && git config user.email t@t && git config user.name t && echo x > r.md && git add -A && git commit -qm init && git branch -M main && git push -q -u origin main && git remote set-head origin -a >/dev/null 2>&1 )
export CC_CLAUDE=/bin/true
# stub claude for cc-loop: writes a journal entry + a file, 2nd iteration says DONE
cat > "$T/fakeclaude" <<'F'
#!/usr/bin/env bash
st=~/.cc/state/_cctest/w1; n=$(ls $st/runs/*.json 2>/dev/null | wc -l)
echo "iteration work $n" > "work-$n.txt"; echo "- $(date -u +%T) did step $n" >> "$st/progress.md"
[ "$n" -ge 2 ] && echo "STATUS: DONE" >> "$st/progress.md"
printf '{"is_error":false,"num_turns":2,"total_cost_usd":0.01,"session_id":"x","result":"ok %s"}' "$n"
F
# stub claude that always hits its turn cap while still doing real work (M6: capped != failed)
cat > "$T/cappedclaude" <<'F'
#!/usr/bin/env bash
st=~/.cc/state/_cctest/w2; n=$(ls $st/runs/*.json 2>/dev/null | wc -l)
echo "capped work $n" > "capped-$n.txt"; echo "- capped iteration $n" >> "$st/progress.md"
printf '{"is_error":true,"subtype":"error_max_turns","num_turns":80,"total_cost_usd":0.5,"session_id":"x","result":"hit the turn cap"}'
F
# stub claude that hangs, to prove a killed loop takes its child with it (H4)
cat > "$T/sleepclaude" <<'F'
#!/usr/bin/env bash
echo "- sleeping iteration" >> ~/.cc/state/_cctest/w3/progress.md
sleep 30
printf '{"is_error":false,"num_turns":1,"total_cost_usd":0.01,"session_id":"x","result":"ok"}'
F
# stub claude that reports a usage limit on its first call and works on the second (M10: a limit is not a failure)
cat > "$T/limitclaude" <<'F'
#!/usr/bin/env bash
st=~/.cc/state/_cctest/w4; n=$(ls $st/runs/*.json 2>/dev/null | wc -l)   # the loop already created THIS run's file
[ "$n" -le 1 ] && { printf '{"is_error":true,"result":"You'"'"'ve hit your usage limit. Your limit resets at 11:40.","total_cost_usd":0}'; exit 0; }
echo "- work after the limit lifted" >> "$st/progress.md"; echo "STATUS: DONE" >> "$st/progress.md"
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
echo "== --say / --go / cc-loop =="
"$B/cc" $REPO w1 --say hello >/dev/null 2>&1 && bad "--say should fail with no live session" || ok "--say refuses when no session"
tmux new-window -d -t main -n "$REPO/m7" "sleep 30"; sleep 1   # M7: a headless worker's pane is a shell — typed text would run as a command
"$B/cc-msg" "$REPO/m7" "hello" >"$T/m7.out" 2>&1; [ $? != 0 ] && grep -q 'task.md' "$T/m7.out" && ok "cc-msg refuses a window with no interactive claude" || bad "cc-msg typed into a headless pane"
tmux kill-window -t "$(tmux list-windows -t main -F '#{window_id} #W' | awk -v n="$REPO/m7" '$2==n{print $1}')" 2>/dev/null
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO/w1$" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
nl0=$(wc -l < ~/.cc/notify.log 2>/dev/null || echo 0)
CC_CLAUDE="$T/fakeclaude" "$B/cc" $REPO w1 --go "build the thing" --loop 3 >/dev/null 2>&1
for _ in $(seq 1 40); do grep -q 'STATUS: DONE' ~/.cc/state/$REPO/w1/progress.md 2>/dev/null && grep -qE 'DONE' ~/.cc/state/$REPO/w1/loop.log 2>/dev/null && break; sleep 1; done
grep -q 'STATUS: DONE' ~/.cc/state/$REPO/w1/progress.md 2>/dev/null && ok "loop ran to DONE via journal" || bad "loop DONE"
[ "$(ls ~/.cc/state/$REPO/w1/runs/*.json 2>/dev/null | wc -l)" = 2 ] && ok "loop stopped after DONE (2 iterations, not 3)" || bad "loop iteration count: $(ls ~/.cc/state/$REPO/w1/runs/*.json 2>/dev/null | wc -l)"
git -C "$T/remote.git" log --oneline track/w1 2>/dev/null | grep -q 'wip: checkpoint' && ok "loop iterations were checkpointed + pushed" || bad "loop checkpoint"
for _ in $(seq 1 30); do tail -n +$((nl0+1)) ~/.cc/notify.log 2>/dev/null | grep -q "$REPO/w1 done" && break; sleep 1; done   # cc-loop writes it from its tmux window, a beat after DONE
tail -n +$((nl0+1)) ~/.cc/notify.log 2>/dev/null | grep -q "$REPO/w1 done" && ok "owner notified on DONE (log backend)" || bad "notify"
st=$("$B/cc-board" get $REPO w1 status); [ "$st" = review ] && ok "board -> review after done (PR skipped: no gh remote)" || bad "board status after done: $st"
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
L(){ HOME="$T/lh" "$B/cc-limit" "$@"; }; mkdir -p "$T/lh"; lf="$T/lim.json"; miss=""   # own HOME: the table never touches the box's real stamp
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
echo "work through a usage limit" > ~/.cc/state/$REPO/w4/task.md; nl0=$(wc -l < ~/.cc/notify.log 2>/dev/null || echo 0)
"$B/cc-limit" clear; CC_CLAUDE="$T/limitclaude" "$B/cc-loop" $REPO w4 --max-iter 2 --quiet >/dev/null 2>&1; rc=$?
runs=$(ls ~/.cc/state/$REPO/w4/runs/*.json 2>/dev/null | wc -l)
{ [ "$rc" = 0 ] && [ "$runs" = 2 ] && grep -q 'STATUS: DONE' ~/.cc/state/$REPO/w4/progress.md; } &&
  ok "a limited run is retried, not counted: 2 runs, 1 iteration, DONE (exit 0)" || bad "limit loop: rc=$rc runs=$runs"
{ grep -q 'usage limit — waiting until' ~/.cc/state/$REPO/w4/loop.log && ! grep -q '^.* error (' ~/.cc/state/$REPO/w4/loop.log; } &&
  ok "the limit was logged and did not count as an error" || bad "limit log/errs: $(grep -c 'error (' ~/.cc/state/$REPO/w4/loop.log) error lines"
n=$(tail -n +$((nl0+1)) ~/.cc/notify.log 2>/dev/null | grep -c "$(hostname) limit")
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
grep -q $'\tpost\tlocal\t' "$CC_SLACK_DIR/outbox.log" 2>/dev/null && ok "reply without a token → outbox log" || bad "outbox"
setsid nohup "$B/cc-slack" daemon --no-slack >"$T/slackd.log" 2>&1 & SD=$!; sleep 1
[ "$("$B/cc-slack" inject --no-start $REPO queued-msg)" = queued ] && ok "inject with no subscriber → queued" || bad "queue"
# the channel server links to the daemon only after the host's notifications/initialized (+2 s) — feed a real MCP handshake, then hold the pipe open
rm -f "$T/fifo"; mkfifo "$T/fifo"; ( exec 3>"$T/fifo"; printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' '{"jsonrpc":"2.0","method":"notifications/initialized"}' >&3; sleep 8; exec 3>&- ) &
CC_SLACK_CHANNEL=1 "$B/cc-slack" channel $REPO < "$T/fifo" > "$T/ch2.out" 2>/dev/null & sleep 3
[ "$("$B/cc-slack" inject --no-start $REPO live-msg)" = delivered ] && ok "inject with a subscriber → delivered" || bad "deliver"
sleep 5; grep -q queued-msg "$T/ch2.out" && grep -q live-msg "$T/ch2.out" && grep -q 'notifications/claude/channel' "$T/ch2.out" && ok "backlog flushed on subscribe + live event as notifications/claude/channel" || bad "channel notifications"
kill $SD 2>/dev/null; pkill -f '^python3 .*cc-slack daemon --no-slack' 2>/dev/null; unset CC_SLACK_DIR
echo "== model fallback (cc-model + cc-limit) =="
# own HOME and own tmux server (TMUX unset, TMUX_TMPDIR into $T): the live sessions' models are never touched
MH="$T/mh"; mkdir -p "$MH/.cc/state" "$T/fb"; printf '#!/usr/bin/env bash\ncat\n' > "$T/fb/cc-loop"; chmod +x "$T/fb/cc-loop"
cat > "$T/probeclaude" <<'F'
#!/usr/bin/env bash
printf '{"is_error":false,"num_turns":1,"total_cost_usd":0.001,"result":"ok"}'
F
chmod +x "$T/probeclaude"
MT(){ env -u TMUX TMUX_TMPDIR="$T" tmux "$@"; }
ME(){ env -u TMUX TMUX_TMPDIR="$T" HOME="$MH" CC_TMUX_SESSION=_ccmodel CC_MODEL_PROC=cat \
      CC_MODEL_PRIMARY='claude-fable-5[1m]' CC_MODEL_FALLBACK=claude-opus-5 "$@"; }
M(){ ME "$B/cc-model" "$@"; }
MT new-session -d -s _ccmodel -n sess 'bash -c "cat; true"'
MT new-window -d -t _ccmodel -n wkr "bash -c '$T/fb/cc-loop; true'"   # a worker pane: cc-loop is its child and claude a grandchild
sleep 1
[ "$(M status)" = fable ] && ok "cc-model status: fable while nothing is limited" || bad "cc-model status: $(M status)"
[ -z "$(M current)" ] && ok "cc-model current is empty with no override" || bad "cc-model current leaked a model"
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
mline "Claude usage limit reached for Fable 5. Your limit resets at 14:40."
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
for id in $(MT list-windows -t _ccmodel -F '#{window_id}' 2>/dev/null); do MT kill-window -t "$id"; done   # last window gone = that scratch server is gone
# cleanup
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
if [ -f "$T/stamp.bak" ]; then mv "$T/stamp.bak" ~/.cc/state/claude-limit; else rm -f ~/.cc/state/claude-limit; fi   # restore the live stamp (or leave none)
rm -rf "$T" ~/dev/$REPO ~/.cc/worktrees/$REPO ~/.cc/state/$REPO ~/.cc/boards/$REPO.json ~/.cc/boards/$REPO.lock
( exec 9>~/.claude.json.lock; flock 9; jq '.projects |= with_entries(select(.key | test("/'"$REPO"'(/|$)") | not))' ~/.claude.json > ~/.claude.json.sel && mv ~/.claude.json.sel ~/.claude.json ) 2>/dev/null   # leave no trust entries behind
echo "== result: $pass passed, $fail failed =="; [ $fail = 0 ]
