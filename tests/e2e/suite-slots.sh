#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# suite-slots.sh — the stanza "the suite's own slots (a cap, not a queue)", run alone on the fixtures it stands on.
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
if stanza "the suite's own slots (a cap, not a queue)" always; then
# Re-runs THIS FILE, stopping at the lock ($CC_SELFTEST_LOCK_ONLY) — no fixtures, no tmux, no repo, so the suite
# never runs inside itself. On a lock of its own ($CC_SELFTEST_LOCK): the real one is held by the very run doing
# the testing, and opening it a second time from here would deadlock this run against nobody but itself. Nothing
# waits on a clock — the holder holds until a flag file appears, and the waiter is watched for the line it prints
# — so a loaded box makes this case slower, never red, and it costs the suite a fraction of a second either way.
L="$T/lock"
( exec 8>>"$L"; flock 8; : >"$L"; echo $BASHPID >&8; for _ in $(seq 1 600); do [ -e "$L.go" ] && break; sleep 0.1; done ) &
hp=$!; KIDS="$KIDS $hp"
for _ in $(seq 1 100); do [ -s "$L" ] && break; sleep 0.1; done   # the stand-in holder has it, and has named itself
env CC_SELFTEST_LOCK="$L" CC_SELFTEST_SLOTS=1 CC_SELFTEST_LOCK_ONLY=1 CC_SELFTEST_LOCK_ORPHAN=1 "$SELF" >"$T/lock.out" 2>&1 & cp=$!; KIDS="$KIDS $cp"
for _ in $(seq 1 300); do grep -q '^== waiting:' "$T/lock.out" 2>/dev/null && break; sleep 0.1; done
{ grep -q "is held by pid $hp (" "$T/lock.out" && kill -0 $cp 2>/dev/null; } \
  && ok "with one slot, a second run names the pid holding it — and is still sitting on it, not failing past it" \
  || bad "the second run did not queue: $(tr '\n' ' ' <"$T/lock.out")"
touch "$L.go"; wait $cp; lrc=$?
cpid=$(sed -n 's/^== lock taken by pid \([0-9]*\) ==$/\1/p' "$T/lock.out")
{ [ $lrc = 0 ] && [ -n "$cpid" ] && [ "$(head -1 "$L")" = "$cpid" ]; } \
  && ok "...and the moment the lock frees it runs, green, leaving its OWN pid in for whoever queues next" \
  || bad "the waiter never took over: rc=$lrc lock=[$(head -1 "$L")] said=[$cpid]"
# ...and the child IT left behind must not still be holding the lock. An flock lives until every copy of the fd is
# shut, so before the fd was closed for it a single unreaped orphan pinned the suite's lock as long as it lived, and
# the next run queued behind a pid already dead. That is the regression this line is here to catch.
orp=$(sed -n 's/^== orphan \([0-9]*\) ==$/\1/p' "$T/lock.out")
{ [ -n "$orp" ] && kill -0 "$orp" 2>/dev/null && flock -n "$L" -c true 2>/dev/null; } \
  && ok "a child that outlives a run does not outlive its lock — nobody queues behind a ghost" \
  || bad "the lock outlived the run (orphan=[$orp] holder=[$(fuser "$L" 2>&1 | tr -s " ")])"
kill "$orp" 2>/dev/null
# …and the suite DIES WITH ITS HOLDER. Killed alone, the holder freed the slot while the suite ran on unowned, and
# three such runs loaded the box on 2026-09-25 beside the ones the cap let in (PR_SET_PDEATHSIG, at the holder).
L4=$T/lock4
env CC_SELFTEST_LOCK="$L4" CC_SELFTEST_SLOTS=2 CC_SELFTEST_LOCK_ONLY=1 CC_SELFTEST_LOCK_HOLD="$L4.go" "$SELF" >"$T/lock4.out" 2>&1 & h4=$!; KIDS="$KIDS $h4"
for _ in $(seq 1 100); do grep -q '^== lock taken' "$T/lock4.out" 2>/dev/null && break; sleep 0.1; done
s4=$(pgrep -P "$h4" | head -1)
kill -KILL "$h4" 2>/dev/null; wait "$h4" 2>/dev/null
for _ in $(seq 1 50); do kill -0 "$s4" 2>/dev/null || break; sleep 0.1; done
{ [ -n "$s4" ] && ! kill -0 "$s4" 2>/dev/null; } \
  && ok "…and a suite whose holder is killed dies with it, so no run goes on outside the cap" \
  || bad "the suite outlived its killed holder (holder $h4, suite ${s4:-not found}): $(tr '\n' ' ' <"$T/lock4.out")"
touch "$L4.go"; kill "$s4" 2>/dev/null
# …and with TWO slots, two runs are in at once and a third waits on both of them — the whole of what the cap is
# for: landings' suites side by side, each on fixtures it owns. Same stand-in holders, same lock-only runs.
L2="$T/lock2"
( exec 8>>"$L2"; flock 8; : >"$L2"; echo $BASHPID >&8; for _ in $(seq 1 600); do [ -e "$L2.go" ] && break; sleep 0.1; done ) & h1=$!; KIDS="$KIDS $h1"
for _ in $(seq 1 100); do [ -s "$L2" ] && break; sleep 0.1; done
two=$(env CC_SELFTEST_LOCK="$L2" CC_SELFTEST_SLOTS=2 CC_SELFTEST_LOCK_ONLY=1 "$SELF" 2>&1)
{ ! grep -q '^== waiting' <<<"$two" && grep -q '^== lock taken' <<<"$two" && [ -s "$L2.2" ]; } \
  && ok "with two slots, a second run takes the free one at once — no waiting, its pid in the second file" \
  || bad "the second run did not take the free slot: $(tr '\n' ' ' <<<"$two")"
( exec 8>>"$L2.2"; flock 8; : >"$L2.2"; echo $BASHPID >&8; for _ in $(seq 1 600); do [ -e "$L2.go" ] && break; sleep 0.1; done ) & h2=$!; KIDS="$KIDS $h2"
for _ in $(seq 1 100); do [ "$(head -1 "$L2.2" 2>/dev/null)" = "$h2" ] && break; sleep 0.1; done
env CC_SELFTEST_LOCK="$L2" CC_SELFTEST_SLOTS=2 CC_SELFTEST_LOCK_ONLY=1 "$SELF" >"$T/lock2.out" 2>&1 & c3=$!; KIDS="$KIDS $c3"
for _ in $(seq 1 300); do grep -q '^== waiting:' "$T/lock2.out" 2>/dev/null && break; sleep 0.1; done
{ grep -q "is held by pid $h1 $h2 (" "$T/lock2.out" && kill -0 $c3 2>/dev/null; } \
  && ok "...and a third, with both slots held, waits and names both holders" \
  || bad "the third run did not wait on both: $(tr '\n' ' ' <"$T/lock2.out")"
touch "$L2.go"; wait $c3; l2rc=$?
[ $l2rc = 0 ] && ok "...and runs the moment one of them frees" || bad "the waiter never got a slot: rc=$l2rc"
# A LANDING GOES FIRST, on a lock of its own. Stand-ins hold slots 2..6 — every slot a run that is not a landing's may
# use, whatever this host's core count makes its cap — and slot 1 stays free. The run with no CC_SELFTEST_SLOTS (not
# a landing's) must wait with slot 1 free; a landing's must take slot 1 at once. Then slot 1 is held as well, a landing
# waits, one slot frees, and the landing gets it while the other run, which was waiting first, is still waiting.
L3="$T/lock3"; h3=""
for i in 2 3 4 5 6; do
  ( exec 8>>"$L3.$i"; flock 8; : >"$L3.$i"; echo $BASHPID >&8; for _ in $(seq 1 600); do [ -e "$L3.go$i" ] || [ -e "$L3.go" ] && break; sleep 0.1; done ) &
  h3="$h3 $!"; KIDS="$KIDS $!"
done
for i in 2 3 4 5 6; do for _ in $(seq 1 100); do [ -s "$L3.$i" ] && break; sleep 0.1; done; done
env -u CC_SELFTEST_SLOTS CC_SELFTEST_LOCK="$L3" CC_SELFTEST_LOCK_ONLY=1 "$SELF" >"$T/lock3n.out" 2>&1 & c3n=$!; KIDS="$KIDS $c3n"
for _ in $(seq 1 300); do grep -q '^== waiting:' "$T/lock3n.out" 2>/dev/null && break; sleep 0.1; done
{ grep -q '^== waiting:' "$T/lock3n.out" && ! grep -q '^== lock taken' "$T/lock3n.out" && kill -0 $c3n 2>/dev/null \
  && flock -n "$L3" -c true; } \
  && ok "a run that is not a landing's waits with slot 1 free — that slot is a landing's alone" \
  || bad "the non-landing run took or failed past the reserved slot: $(tr '\n' ' ' <"$T/lock3n.out")"
land=$(env CC_SELFTEST_LOCK="$L3" CC_SELFTEST_SLOTS=6 CC_SELFTEST_LOCK_ONLY=1 "$SELF" 2>&1)
{ ! grep -q '^== waiting' <<<"$land" && grep -q '^== lock taken' <<<"$land"; } \
  && ok "...and a landing's run takes it at once, however many other runs hold the rest" \
  || bad "the landing did not get the reserved slot: $(tr '\n' ' ' <<<"$land")"
( exec 8>>"$L3"; flock 8; : >"$L3"; echo $BASHPID >&8; for _ in $(seq 1 600); do [ -e "$L3.go" ] && break; sleep 0.1; done ) & KIDS="$KIDS $!"
for _ in $(seq 1 100); do [ "$(head -1 "$L3" 2>/dev/null)" = "$!" ] && break; sleep 0.1; done
env CC_SELFTEST_LOCK="$L3" CC_SELFTEST_SLOTS=6 CC_SELFTEST_LOCK_ONLY=1 CC_SELFTEST_LOCK_HOLD="$L3.go" "$SELF" >"$T/lock3l.out" 2>&1 & c3l=$!; KIDS="$KIDS $c3l"
for _ in $(seq 1 300); do grep -q '^== waiting:' "$T/lock3l.out" 2>/dev/null && break; sleep 0.1; done
touch "$L3.go3"
for _ in $(seq 1 300); do grep -q '^== lock taken' "$T/lock3l.out" 2>/dev/null && break; sleep 0.1; done
sleep 2   # two of the waiters' one-second turns: time enough for the other run to take slot 3 if it were going to
{ grep -q '^== lock taken' "$T/lock3l.out" && ! grep -q '^== lock taken' "$T/lock3n.out" && kill -0 $c3n 2>/dev/null; } \
  && ok "...and with every slot held, the slot that frees goes to the waiting landing, not the run that was waiting before it" \
  || bad "the landing did not go first: landing=[$(tr '\n' ' ' <"$T/lock3l.out")] other=[$(tr '\n' ' ' <"$T/lock3n.out")]"
grep -q 'a landing waiting ahead' "$T/lock3n.out" \
  && ok "...and the run held back says it is waiting behind a landing" || bad "no 'landing ahead' line: $(tr '\n' ' ' <"$T/lock3n.out")"
touch "$L3.go"; wait $c3l; wait $c3n; l3rc=$?
[ $l3rc = 0 ] && grep -q '^== lock taken' "$T/lock3n.out" \
  && ok "...and it runs once the landing has its slot and one frees" || bad "the held-back run never got a slot: rc=$l3rc"
# THE RUNNER FIRST: a run offers itself to the runner before it takes a slot here. A stub cc-suites (CC_SELFTEST_SUITES)
# logs each call and answers what the case says; the real one has its own selfcheck.
LS="$T/lockspill"; printf '#!/usr/bin/env bash\necho "$1" >> "%s.calls"; [ "$1" = spill ] && exit "$(cat "%s.rc")"; exit 0\n' "$LS" "$LS" > "$T/suites-stub"
chmod +x "$T/suites-stub"
echo 0 > "$LS.rc"; sp=$(env CC_SELFTEST_LOCK="$LS" CC_SELFTEST_SLOTS=1 CC_SELFTEST_LOCK_ONLY=1 CC_SELFTEST_SUITES="$T/suites-stub" "$SELF" 2>&1); sprc=$?
{ [ "$sprc" = 0 ] && ! grep -q '^== lock taken' <<<"$sp" && [ "$(cat "$LS.calls")" = spill ]; } \
  && ok "a run the runner passes takes no slot here: offered first, and its pass is the exit" || bad "spill-first: rc=$sprc calls=[$(tr '\n' ' ' <"$LS.calls")] $(tr '\n' ' ' <<<"$sp")"
rm -f "$LS.calls"; echo 76 > "$LS.rc"
sp=$(env CC_SELFTEST_LOCK="$LS" CC_SELFTEST_SLOTS=1 CC_SELFTEST_LOCK_ONLY=1 CC_SELFTEST_SUITES="$T/suites-stub" "$SELF" 2>&1); sprc=$?
{ [ "$sprc" = 0 ] && grep -q '^== lock taken' <<<"$sp"; } \
  && ok "...a red (or cut-off) run there runs here: 76 takes a slot" || bad "76 did not run here: rc=$sprc $(tr '\n' ' ' <<<"$sp")"
# …and is not offered again while it waits: with the only slot held, a 76 run calls spill once, a 75 run again at once
( exec 8>>"$LS"; flock 8; : >"$LS"; echo $BASHPID >&8; for _ in $(seq 1 600); do [ -e "$LS.go" ] && break; sleep 0.1; done ) & hs=$!; KIDS="$KIDS $hs"
for _ in $(seq 1 100); do [ "$(head -1 "$LS" 2>/dev/null)" = "$hs" ] && break; sleep 0.1; done
for want in 76 75; do
  rm -f "$LS.calls"; echo "$want" > "$LS.rc"
  env CC_SELFTEST_LOCK="$LS" CC_SELFTEST_SLOTS=1 CC_SELFTEST_LOCK_ONLY=1 CC_SELFTEST_SUITES="$T/suites-stub" "$SELF" >"$T/lockspill.$want.out" 2>&1 & sw=$!; KIDS="$KIDS $sw"
  for _ in $(seq 1 300); do grep -q '^== waiting:' "$T/lockspill.$want.out" 2>/dev/null && break; sleep 0.1; done
  sleep 1.5; kill "$sw" 2>/dev/null; wait "$sw" 2>/dev/null
  eval "spills$want=$(grep -cx spill "$LS.calls" 2>/dev/null)"
done
touch "$LS.go"; wait "$hs" 2>/dev/null
{ [ "${spills76:-}" = 1 ] && [ "${spills75:-}" = 2 ]; } \
  && ok "...and, waiting, a run that ran there is not offered again, while one that never ran there is (76 → 1 offer, 75 → 2)" \
  || bad "re-offer rule: 76 → ${spills76:-?} offers (want 1), 75 → ${spills75:-?} (want 2)"
# A FULL RUNNER AND A LOADED BOX: a run that is not a landing's waits for the runner a while before running here. The
# stub answers `free 0` to status and 75 to a spill until its Nth call ($LW.pass: the spill that passes, 0 = none).
LW="$T/lockwait"; printf '#!/usr/bin/env bash
echo "$1" >> "%s.calls"
[ "$1" = status ] && { echo "cc-suites: runner r answers: free 0 cores=8"; exit 0; }
[ "$1" = spill ] && { [ "$(grep -cx spill "%s.calls")" = "$(cat "%s.pass")" ] && exit 0; exit 75; }
exit 0
' "$LW" "$LW" "$LW" > "$T/suites-wait"
chmod +x "$T/suites-wait"; echo "99.00 99.00 99.00 1/1 1" > "$LW.loaded"; echo "0.00 0.00 0.00 1/1 1" > "$LW.idle"
lw(){ rm -f "$LW.calls"; echo "$1" > "$LW.pass"; shift
      env -u CC_SELFTEST_SLOTS CC_SELFTEST_LOCK="$LW" CC_SELFTEST_LOCK_ONLY=1 CC_SELFTEST_SUITES="$T/suites-wait" \
        CC_SELFTEST_RUNNER_POLL=1 "$@" "$SELF" 2>&1; }
w1=$(lw 2 CC_SELFTEST_LOADAVG="$LW.loaded" CC_SELFTEST_RUNNER_WAIT=30); w1rc=$?
{ [ "$w1rc" = 0 ] && grep -q 'waiting up to 30s for the runner' <<<"$w1" && ! grep -q '^== lock taken' <<<"$w1" && [ "$(grep -cx spill "$LW.calls")" = 2 ]; } \
  && ok "a run that is not a landing's, turned away by a full runner while this box is loaded, waits and offers itself again, and the runner's pass is its exit" \
  || bad "wait for a full runner: rc=$w1rc calls=[$(tr '\n' ' ' <"$LW.calls")] $(tr '\n' ' ' <<<"$w1")"
w2=$(lw 0 CC_SELFTEST_LOADAVG="$LW.loaded" CC_SELFTEST_RUNNER_WAIT=2); w2rc=$?
{ [ "$w2rc" = 0 ] && grep -q '^== waited 2s for the runner — running here' <<<"$w2" && grep -q '^== lock taken' <<<"$w2" && [ "$(grep -cx spill "$LW.calls")" = 3 ]; } \
  && ok "...and waits no longer than CC_SELFTEST_RUNNER_WAIT, then takes a slot here" \
  || bad "runner wait bound: rc=$w2rc calls=[$(tr '\n' ' ' <"$LW.calls")] $(tr '\n' ' ' <<<"$w2")"
w3=$(lw 2 CC_SELFTEST_LOADAVG="$LW.idle" CC_SELFTEST_RUNNER_WAIT=30); w3rc=$?
{ [ "$w3rc" = 0 ] && ! grep -q 'waiting up to' <<<"$w3" && grep -q '^== lock taken' <<<"$w3" && [ "$(grep -cx spill "$LW.calls")" = 1 ]; } \
  && ok "...but on a box that is not loaded it runs here at once" \
  || bad "runner wait on an idle box: rc=$w3rc calls=[$(tr '\n' ' ' <"$LW.calls")] $(tr '\n' ' ' <<<"$w3")"
rm -f "$LW.calls"; echo 2 > "$LW.pass"
w4=$(env CC_SELFTEST_LOCK="$LW" CC_SELFTEST_SLOTS=1 CC_SELFTEST_LOCK_ONLY=1 CC_SELFTEST_SUITES="$T/suites-wait" CC_SELFTEST_RUNNER_POLL=1 \
       CC_SELFTEST_LOADAVG="$LW.loaded" CC_SELFTEST_RUNNER_WAIT=30 "$SELF" 2>&1); w4rc=$?
{ [ "$w4rc" = 0 ] && ! grep -q 'waiting up to' <<<"$w4" && grep -q '^== lock taken' <<<"$w4"; } \
  && ok "...and a landing never waits for the runner, loaded box or not" \
  || bad "a landing waited for the runner: rc=$w4rc $(tr '\n' ' ' <<<"$w4")"
fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
