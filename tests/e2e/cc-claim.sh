#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# cc-claim.sh — the stanza "cc claim: the canonical track prepared and claimed, with nothing launched", run alone on the fixtures it stands on.
. "$(dirname "$0")/lib.sh"
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
# ── the stanza
if stanza "cc claim: the canonical track prepared and claimed, with nothing launched"; then
# ONE DELIVERY PATH, milestone 1. A subagent gets the worktree and branch a worker gets — same place, same
# branch — without a window or a model being started for it, and from then on the row carries one durable task
# id (bin/cc-task). What the id is FOR is later milestones; that it survives a second claim and a change of
# executor is what this pins. cc-task's own selfcheck owns the claim rules; these are the door `cc` puts on them.
chk cc-task
mkdir -p ~/.cc/state/$REPO/c1; printf 'Do the c1 thing.\n' > ~/.cc/state/$REPO/c1/task.md
# A tmux of this case's own, so the presence mark is the same values wherever the suite runs — `agent me` is
# the session's WINDOW, and a landing runs this from systemd, where there is none. The box's tmux is not touched.
# It answers with the window a READER counts (cc-board agent_id): the mark, tmux session `main`, and a window
# named for this repo. Anything else and cc-board refuses the mark, which is the point of that refusal.
mkdir -p "$T/tmuxstub"; printf '#!/bin/sh\n[ "$1" = display-message ] && { printf "@99:4242\\tmain\\t'"$REPO"'\\n"; exit 0; }\n[ "$1" = list-windows ] && { printf "@4\\n@99\\n"; exit 0; }\nexit 1\n' > "$T/tmuxstub/tmux"; chmod +x "$T/tmuxstub/tmux"
rec=$(env PATH="$T/tmuxstub:$PATH" TMUX_PANE=%1 "$B/cc" claim $REPO c1 --executor subagent 2>"$T/c1.err"); crc=$?
tid=$(jq -r .task_id <<<"$rec" 2>/dev/null)
{ [ "$crc" = 0 ] && [ "$(git -C ~/.cc/worktrees/$REPO/c1 symbolic-ref --short HEAD 2>/dev/null)" = track/c1 ] \
  && [ "$(sed -n 3p ~/.cc/worktrees/$REPO/c1/.cc/track)" = "$tid" ] \
  && [ "$(sed -n 1,2p ~/.cc/worktrees/$REPO/c1/.cc/track | tr '\n' ' ')" = "$REPO c1 " ] \
  && [ "$("$B/cc-board" get $REPO c1 status)" = running ] \
  && [ -z "$(wins "$REPO/c1")" ] && [ ! -f ~/.cc/state/$REPO/c1/loop.log ] \
  && [ "$("$B/cc-board" get $REPO c1 agent)" = "@99:4242" ]; } \
  && ok "cc claim prepares the canonical worktree, stamps the task on the marker and marks the session as present — no window, no worker, no model" \
  || bad "cc claim: rc=$crc tid=$tid branch=$(git -C ~/.cc/worktrees/$REPO/c1 symbolic-ref --short HEAD 2>/dev/null) $(cat "$T/c1.err")"
bshow=$("$B/cc-board" show $REPO 2>/dev/null)   # captured, never piped into grep -q: the SIGPIPE would be this line's own failure
{ [ "$(jq -r .task_id <<<"$("$B/cc" claim $REPO c1 --executor subagent 2>/dev/null)")" = "$tid" ] \
  && [ "$(jq -r .task_id < ~/.cc/state/$REPO/c1/delivery.json)" = "$tid" ] \
  && [ "$(jq -r .worktree <<<"$("$B/cc-task" show $REPO c1)")" = "$HOME/.cc/worktrees/$REPO/c1" ] \
  && grep -q "delivery: $tid  subagent" <<<"$bshow"; } \
  && ok "claiming it again is the same task, and the board row shows that identity" \
  || bad "a second claim did not keep the task: $("$B/cc-task" show $REPO c1 2>&1 | head -5 | tr '\n' ' ')"
# …and --go is the other executor of the same task, not a second one — and its claim is a DISPATCH reservation,
# handed back once the window is up: cc-task records the owner off the running process, which for a --go is
# whoever dispatched and never the loop, so a claim left standing would refuse cc-land's repair round and the
# documented BLOCKED recovery from any other window (review of #279). The mark goes too: a worker is a process
# the box can see, and a stale one would hide a worker that died.
"$B/cc" $REPO c1 --go "" >/dev/null 2>&1
d1=~/.cc/state/$REPO/c1/delivery.json
{ [ "$(jq -r .task_id < "$d1")" = "$tid" ] && [ "$(jq -r .claim.executor < "$d1")" = worker ] \
  && [ "$(sed -n 3p ~/.cc/worktrees/$REPO/c1/.cc/track)" = "$tid" ] \
  && [ "$(jq -r .claim.reason < "$d1")" = "worker launched" ] && [ "$(jq -r .claim.ended_at < "$d1")" != null ] \
  && [ "$(jq -r '.executions[-1].outcome' < "$d1")" = "released: worker launched" ] \
  && [ -z "$("$B/cc-board" get $REPO c1 agent)" ] && "$B/cc-task" check $REPO c1; } \
  && ok "--go claims the same task as a worker, then hands the reservation back at launch — the row is dispatchable again" \
  || bad "--go did not claim and release: $(tr -d '\n' < "$d1" | head -c 200)"
for id in $(wins "$REPO/c1"); do tmux kill-window -t "$id"; done
# A SECOND OWNER. A subagent has no window and no loop, so while its process really is on the row no other
# SUBAGENT takes it — but a worker dispatch does, because that is the repair round the design gives cc-land, onto
# the very worktree the subagent built, and a subagent that never reached `cc done` must not block it for the
# life of its session (review of #279). A live WORKER's claim is taken by nothing.
mkdir -p ~/.cc/state/$REPO/c5; printf 'Do the c5 thing.\n' > ~/.cc/state/$REPO/c5/task.md
hold(){ ( "$B/cc" claim $REPO c5 --executor "$1" >/dev/null 2>&1; while [ ! -f "$T/c5.stop" ]; do sleep 0.2; done ) & }
d5=~/.cc/state/$REPO/c5/delivery.json
rm -f "$T/c5.stop"; hold subagent; holder=$!; KIDS="$KIDS $holder"
for _ in $(seq 1 100); do [ -f "$d5" ] && break; sleep 0.1; done
c5tid=$(jq -r .task_id < "$d5" 2>/dev/null)
"$B/cc" claim $REPO c5 --executor subagent >"$T/c5.out" 2>&1; h1=$?
{ [ "$h1" != 0 ] && grep -q 'live owner' "$T/c5.out" \
  && [ "$(jq -r .claim.generation < "$d5")" = 1 ]; } \
  && ok "a second subagent waits on a row a live subagent is on — the claim is not taken and nothing is written" \
  || bad "a second subagent took a live claim: rc=$h1 $(cat "$T/c5.out")"
"$B/cc" $REPO c5 --go "" >"$T/c5go.out" 2>&1; h2=$?
{ [ "$h2" = 0 ] && [ "$(jq -r .task_id < "$d5")" = "$c5tid" ] \
  && [ "$(jq -r .claim.generation < "$d5")" = 2 ] \
  && [ "$(jq -r '.executions[0].outcome' < "$d5")" = "superseded (a worker took over from a subagent)" ]; } \
  && ok "…while a worker dispatch takes that same row over — one task, a new generation, and the record says why" \
  || qbad cc "a repair dispatch was refused a row a subagent still holds: rc=$h2 $(cat "$T/c5go.out")"
for id in $(wins "$REPO/c5"); do tmux kill-window -t "$id"; done
touch "$T/c5.stop"; wait $holder 2>/dev/null; KIDS="${KIDS% $holder}"
rm -f "$T/c5.stop" "$d5"; hold worker; holder=$!; KIDS="$KIDS $holder"
for _ in $(seq 1 100); do [ -f "$d5" ] && break; sleep 0.1; done
"$B/cc" claim $REPO c5 --executor subagent >"$T/c5w1.out" 2>&1; h3=$?
"$B/cc" $REPO c5 --go "" >"$T/c5w2.out" 2>&1; h4=$?
{ [ "$h3" != 0 ] && [ "$h4" != 0 ] && [ -z "$(wins "$REPO/c5")" ] \
  && [ "$(jq -r .claim.generation < "$d5")" = 1 ] && [ "$(jq -r .claim.executor < "$d5")" = worker ]; } \
  && ok "…and a live WORKER's claim is taken by nothing — not a subagent, not another dispatch" \
  || bad "a live worker claim was taken: claim rc=$h3 go rc=$h4 $(cat "$T/c5w1.out" "$T/c5w2.out")"
touch "$T/c5.stop"; wait $holder 2>/dev/null; KIDS="${KIDS% $holder}"
# DELIVERY IS WHAT ENDS A SUBAGENT'S CLAIM. `cc done` is the end of its turn on the row, so the row is free for
# the lander and for the next dispatcher — from any process, not only the one that claimed. Completion now
# needs an actual PR and card response; the missing-response control lives beside P7 below.
mkdir -p "$T/ghc" "$T/ccslack"
printf '#!/bin/sh\ncase "$*" in *"pr create"*) echo https://github.com/fixture/repo/pull/1;; esac\nexit 0\n' > "$T/ghc/gh"
printf '#!/bin/sh\necho "fixture 1.2"\nexit 0\n' > "$T/ccslack/cc-slack"; chmod +x "$T/ghc/gh" "$T/ccslack/cc-slack"
mkdir -p ~/.cc/state/$REPO/c6; printf 'Do the c6 thing.\n' > ~/.cc/state/$REPO/c6/task.md
"$B/cc" claim $REPO c6 --executor subagent >/dev/null 2>&1
c6tid=$(jq -r .task_id < ~/.cc/state/$REPO/c6/delivery.json 2>/dev/null); d6=~/.cc/state/$REPO/c6/delivery.json
echo "the subagent's work" > ~/.cc/worktrees/$REPO/c6/c6.txt
env PATH="$T/ghc:$PATH" CC_SLACK="$T/ccslack/cc-slack" "$B/cc" done $REPO c6 >"$T/c6done.out" 2>&1
{ [ "$("$B/cc-board" get $REPO c6 status)" = review ] && [ "$(jq -r .claim.ended_at < "$d6")" != null ] \
  && [ "$(jq -r .claim.reason < "$d6")" = delivered ] \
  && [ "$(jq -r '.executions[-1].outcome' < "$d6")" = "released: delivered" ]; } \
  && ok "cc done ends the claim the delivered work was done under — the row is in review and nobody still holds it" \
  || bad "cc done left the row claimed: $(tr -d '\n' < "$d6" | head -c 200) :: $(cat "$T/c6done.out")"
# A TRACK IS A THREAD, NOT A CHANNEL (owner, 2026-09-18). `cc … --go` opens the track's ONE thread in #<repo> through
# `cc-slack track-thread`, titled from the board row, once, before the loop starts — and asks cc-slack for nothing
# else: no channel of the track's own. CC_SLACK names the stub, and its being set is what turns the link on for
# this dispatch (as for `done`'s card): the case never touches ~/.cc/slack/enabled, the BOX's flag — this suite runs
# in the real HOME, and a first version that toggled it left the box's Slack off (2026-09-19).
mkdir -p ~/.cc/state/$REPO/c7 "$T/cctt"; "$B/cc-board" add $REPO c7 "the c7 title" >/dev/null 2>&1; printf 'Do the c7 thing.\n' > ~/.cc/state/$REPO/c7/task.md
printf '#!/bin/sh\necho "$*" >> "%s"\necho "C0FIX 1.2"\nexit 0\n' "$T/tt.args" > "$T/cctt/cc-slack"; chmod +x "$T/cctt/cc-slack"; : > "$T/tt.args"
CC_SLACK="$T/cctt/cc-slack" "$B/cc" $REPO c7 --go "" >"$T/c7on.out" 2>&1
for id in $(wins "$REPO/c7"); do tmux kill-window -t "$id"; done
{ [ "$(grep -c '^track-thread ' "$T/tt.args")" = 1 ] \
  && grep -q "^track-thread $REPO/c7 --title the c7 title\$" "$T/tt.args" \
  && ! grep -q 'mkchannel\|channel ' "$T/tt.args"; } \
  && ok "cc … --go opens the track's one thread (cc-slack track-thread <repo>/<track> --title <row title>), once, and asks for no channel" \
  || bad "--go did not open the track thread as expected: $(cat "$T/tt.args" | tr '\n' '|') :: $(tail -3 "$T/c7on.out" | tr '\n' ' ')"
# …AND FROM THAT PR ON, THE ROW IS THE LANDING QUEUE'S. A plain dispatch — this process's or any other's — is
# refused before it writes a brief or buys a turn, because the remainder of a track kept running inside a change
# already delivered and landed it twice (arch review 2026-09-08 rec 6). The queue's own reservation for that PR
# and head is the one way back in, and the dispatch it then runs adopts that repair rather than claiming afresh.
cp "$d6" "$T/c6before.json"
( "$B/cc" $REPO c6 --go "" >"$T/c6go.out" 2>&1; echo $? > "$T/c6go.rc" )   # a subshell of its own: a different owner
{ [ "$(cat "$T/c6go.rc")" != 0 ] && grep -q 'delivery-pending' "$T/c6go.out" \
  && grep -q 'fixture/repo/pull/1' "$T/c6go.out" \
  && cmp -s "$d6" "$T/c6before.json" && [ -z "$(wins "$REPO/c6")" ]; } \
  && ok "…and a delivered row is not dispatched again: the refusal names the PR, and no window, brief or record write was spent" \
  || bad "a delivered row dispatched anyway: rc=$(cat "$T/c6go.rc") $(cat "$T/c6go.out")"
# The queue's two steps, in one process the way cc-land runs them: the reservation, then its own dispatch. Both
# plain commands here — a $(…) or a subshell would be a second owner, which is what D5 of cc-task refuses.
"$B/cc-task" reserve-repair $REPO c6 --generation 1 --branch track/c6 \
  --pr https://github.com/fixture/repo/pull/1 --head 6c6c6c6c6c6c6c6c6c6c6c6c6c6c6c6c6c6c6c6c >"$T/c6res.out" 2>&1; r6=$?
"$B/cc" $REPO c6 --go "" >"$T/c6go2.out" 2>&1; g6=$?
e6=$(jq -r .execution_id < "$T/c6res.out")   # the reservation's own execution: adopting it appends no second one
{ [ "$r6" = 0 ] && [ "$(jq -r .launch < "$T/c6res.out")" = true ] && [ "$g6" = 0 ] \
  && [ -n "$(wins "$REPO/c6")" ] && [ "$(jq -r .task_id < "$d6")" = "$c6tid" ] \
  && [ "$(jq -r .claim.generation < "$d6")" = 2 ] \
  && [ "$(jq -r '.executions[-1].execution_id' < "$d6")" = "$e6" ] \
  && [ "$(jq -r '.executions[-1].phase' < "$d6")" = repair ] \
  && [ "$(jq -r '.executions[-1].outcome' < "$d6")" = "released: worker launched" ]; } \
  && ok "…so the queue's repair round is what dispatches it afterwards — the same task, its reservation adopted instead of a claim of its own" \
  || bad "the repair round would not dispatch a delivered row: reserve rc=$r6 go rc=$g6 $(cat "$T/c6res.out" "$T/c6go2.out")"
for id in $(wins "$REPO/c6"); do tmux kill-window -t "$id"; done
# NOTHING THE HOST OPENS IN A TRACK'S OWN DIRECTORIES IS WRITTEN THROUGH A PLANTED NAME. $wt/.cc and $st are
# bound read-write into that track's worker sandbox and into a member workspace, so a link left at a name the
# DISPATCH path opens would have the next `--go` — cc-land's repair round, which needs no person — truncate any
# file the owner can write. The marker is cc-task's business and has its own cases; these are cc's two locks.
decoy="$T/decoy"; echo "do not touch" > "$decoy"
ln -sf "$decoy" ~/.cc/worktrees/$REPO/c1/.cc/done.lock
env PATH="$T/ghc:$PATH" CC_SLACK="$T/ccslack/cc-slack" "$B/cc" done $REPO c1 >"$T/lk1.out" 2>&1; k1=$?
rm -f ~/.cc/worktrees/$REPO/c1/.cc/done.lock
ln -sf "$decoy" ~/.cc/state/$REPO/c1/.lock
"$B/cc" $REPO c1 --go "" >"$T/lk2.out" 2>&1; k2=$?
rm -f ~/.cc/state/$REPO/c1/.lock
{ [ "$k1" != 0 ] && [ "$k2" != 0 ] && grep -q 'symlink' "$T/lk1.out" && grep -q 'symlink' "$T/lk2.out" \
  && [ "$(cat "$decoy")" = "do not touch" ] && [ -z "$(wins "$REPO/c1")" ]; } \
  && ok "a link planted at a track's done.lock or its state lock is refused — the file it named is untouched" \
  || bad "cc wrote through a planted lock: done rc=$k1 go rc=$k2 decoy='$(cat "$decoy")' $(cat "$T/lk1.out" "$T/lk2.out")"
# THE SPEND TIER refuses --go HERE, before any window opens: the dispatcher — cc-land's fix round, the planning seat —
# must hear exit 1, not "worker started" for a loop that dies at its door (review of #414). The planted lock is the
# control: under autonomous the same command gets PAST the tier and the lock stops it instead, so no window either way.
ln -sf "$decoy" ~/.cc/state/$REPO/c1/.lock
CC_SPEND_TIER=stop "$B/cc" $REPO c1 --go "" >"$T/tier1.out" 2>&1; tr1=$?
CC_SPEND_TIER=autonomous "$B/cc" $REPO c1 --go "" >"$T/tier2.out" 2>&1; tr2=$?
rm -f ~/.cc/state/$REPO/c1/.lock
{ [ "$tr1" = 1 ] && grep -q 'waits' "$T/tier1.out" && ! grep -q 'symlink' "$T/tier1.out" \
  && [ "$tr2" != 0 ] && grep -q 'symlink' "$T/tier2.out" && ! grep -q 'waits' "$T/tier2.out" && [ -z "$(wins "$REPO/c1")" ]; } \
  && ok "cc --go is refused by the spend tier before any window opens (exit 1, 'waits'); under autonomous the same command gets past it" \
  || bad "tier gate on --go: stop rc=$tr1 '$(cat "$T/tier1.out")' autonomous rc=$tr2 '$(cat "$T/tier2.out")'"
{ env PATH="$T/ghc:$PATH" CC_SLACK="$T/ccslack/cc-slack" "$B/cc" done $REPO c1 >"$T/lk3.out" 2>&1 \
  && [ ! -L ~/.cc/worktrees/$REPO/c1/.cc/done.lock ]; } \
  && ok "…and with plain files back at those names the same command runs as before" \
  || bad "the link check refuses an honest lock too: $(cat "$T/lk3.out")"
# THE REFUSAL NAMES THE REAL REASON, NOT THE MARK (2026-09-23): an owner-asked row already marked critical, held
# under essential because another row is already running (one at a time), was told "mark it critical" — a re-mark,
# a retry and a read of cc-tier's source cost three turns before the real cause (another row running) turned up.
# Fresh rows: c1/c5/c6 above finished their own scenes and their status is not this test's to depend on.
# w1, w9 and others (lines 373, 381...) are left `running` for the rest of the suite — parked here so the ONLY
# row `other_running` can name is other1; otherwise this case would pass or fail on board scan order, not on
# the fix (cc-tier's other_running prints the FIRST running row it finds across every board on the box).
running_rows=$("$B/cc-board" json $REPO 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
for k, t in (d.get("tracks") or {}).items():
    if isinstance(t, dict) and t.get("status") == "running": print(k)')
for rr in $running_rows; do "$B/cc-board" status $REPO "$rr" queued >/dev/null 2>&1; done
"$B/cc-board" add $REPO crit1 "an owner-asked critical row" >/dev/null 2>&1
"$B/cc-board" set $REPO crit1 critical yes >/dev/null 2>&1
mkdir -p ~/.cc/state/$REPO/crit1; printf 'Do the crit1 thing.\n' > ~/.cc/state/$REPO/crit1/task.md
"$B/cc-board" add $REPO other1 "another row already running" >/dev/null 2>&1
"$B/cc-board" status $REPO other1 running >/dev/null 2>&1
CC_SPEND_TIER=essential "$B/cc" $REPO crit1 --go "" >"$T/tiername.out" 2>&1; trn=$?
"$B/cc-board" status $REPO other1 queued >/dev/null 2>&1
for rr in $running_rows; do "$B/cc-board" status $REPO "$rr" running >/dev/null 2>&1; done
{ [ "$trn" = 1 ] && grep -q "$REPO/other1 is running" "$T/tiername.out" \
  && ! grep -qi 'mark it critical\|not marked critical' "$T/tiername.out" && [ -z "$(wins "$REPO/crit1")" ]; } \
  && ok "a row already marked critical, held because another row is running, is told THAT — not sent back to mark itself critical" \
  || bad "tier refusal misnamed the cause: rc=$trn $(cat "$T/tiername.out")"
# THE THREE THAT MUST STAMP NOTHING. A row with no brief (task.md is the brief's one home, and a claim may not
# quietly become a re-brief), a session row (a channel has no task to finish), and a repository that is not there.
"$B/cc-board" add $REPO c2 "no brief yet" >/dev/null 2>&1
"$B/cc" claim $REPO c2 --executor worker >"$T/c2.out" 2>&1; c2rc=$?
{ [ "$c2rc" != 0 ] && grep -q 'task.md' "$T/c2.out" && [ ! -f ~/.cc/state/$REPO/c2/delivery.json ]; } \
  && ok "a row with no brief claims nothing, and the refusal names task.md" || bad "claimed an unbriefed row: rc=$c2rc $(cat "$T/c2.out")"
mkdir -p ~/.cc/state/$REPO/c3; printf 'a channel, not a task\n' > ~/.cc/state/$REPO/c3/task.md
"$B/cc-board" add $REPO c3 "a session" >/dev/null 2>&1; "$B/cc-board" set $REPO c3 kind session >/dev/null 2>&1
"$B/cc" claim $REPO c3 --executor subagent >"$T/c3.out" 2>&1; c3rc=$?
{ [ "$c3rc" != 0 ] && [ ! -f ~/.cc/state/$REPO/c3/delivery.json ] \
  && [ "$("$B/cc-board" get $REPO c3 kind)" = session ]; } \
  && ok "a session row has no task to claim, and is still a session afterwards" || bad "claimed a session row: rc=$c3rc $(cat "$T/c3.out")"
"$B/cc" claim ${REPO}x c4 --executor worker >"$T/c4.out" 2>&1; c4rc=$?
{ [ "$c4rc" != 0 ] && [ ! -e ~/.cc/state/${REPO}x ] && [ ! -e ~/.cc/worktrees/${REPO}x ]; } \
  && ok "a repository that is not there prepares nothing and stamps no claim" || bad "claimed a track in a repo that does not exist: rc=$c4rc $(cat "$T/c4.out")"
rm -rf ~/.cc/state/${REPO}x ~/.cc/worktrees/${REPO}x ~/.cc/boards/${REPO}x.json ~/.cc/boards/${REPO}x.lock
fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
