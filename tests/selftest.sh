#!/usr/bin/env bash
# selftest.sh — end-to-end test of the cc layer against a throwaway local repo (bare "remote"). No API calls:
export CC_NOTIFY_LOG_ONLY=1   # never push to the owner from tests
export CC_LIMIT_MIN_WAIT=1    # cc-limit test hook: any 'wait until the usage limit resets' is capped at 1 s
# claude is stubbed (CC_CLAUDE). Safe to run anytime, INCLUDING alongside another copy of itself in another
# worktree: every run is namespaced (see $RUN below), the two runs take turns (see the lock below) and each
# cleans up after itself.  Usage: tests/selftest.sh
# Exercises the bin/ THIS file ships with (a track worktree tests its own copy, not the ~/bin symlinks).
set -uo pipefail
exec </dev/null; unset CC_ROLE CC_HANDOFF CLAUDECODE "${!CLAUDE_@}"   # never inherit a tty (`cc` would attach tmux and swallow the run) nor a
# caller's worker role NOR ITS HANDOFF ID — the guard and overlap probes set both themselves. $CC_HANDOFF stays in a
# session's environment for the life of that session, deliberately, so the model cannot unset it; a suite that
# inherits it is asserting against whoever happens to be running it. On 2026-08-31 that produced FOUR separate red
# gates in one night, in both directions: cases that passed only for a handoff survivor, and cases that failed only
# for one. Each was patched individually and the class came back within the hour. Unset it once, here, for all of it.
# NOR THE SESSION a land was typed in: CLAUDECODE=1, CLAUDE_PID, CLAUDE_CODE_* rode every chain a Claude Code shell
# started on 2026-09-01 (02:54–04:05Z) — the same class: a suite carrying them asserts against whoever runs it.
B="$(cd "$(dirname "$0")/../bin" && pwd)"
SELF="$(readlink -f "$0")"
# ── one run at a time ────────────────────────────────────────────────────────────────────────────────────────
# $RUN namespaces everything this suite OWNS; it cannot namespace what the box only has one of — the live `main`
# tmux server, ~/.claude.json, the cc-model dialog panes. Two suites at once fight over those, and on 2026-08-31/
# 09-01 that cost three land cycles: red runs that were green alone. A false red is worse than a slow one — it can
# false-open the main-gate row — so overlapping runs QUEUE here rather than race. Wait, never fail: the second run
# is not wrong, it is early.
LOCKF="${CC_SELFTEST_LOCK:-$HOME/.cc/selftest.lock}"; mkdir -p "$(dirname "$LOCKF")"
if [ -z "${CC_SELFTEST_HELD:-}" ]; then
  exec {LK}>>"$LOCKF"   # >> and never >: a waiter that truncated the file would wipe the pid it is about to read
  if ! flock -n $LK; then
    # Whoever holds it wrote their pid a hair after taking it, so what the file says for that hair is the pid the
    # PREVIOUS run left. Read until the name is of something actually alive, then say it, once, and queue.
    h=$(head -1 "$LOCKF" 2>/dev/null)
    for _ in $(seq 1 40); do { [ -n "$h" ] && kill -0 "$h"; } 2>/dev/null && break; sleep 0.05; h=$(head -1 "$LOCKF" 2>/dev/null); done
    echo "== waiting: $LOCKF is held by pid ${h:-?} =="
    flock $LK   # wait, never fail: the second run is not wrong, it is early
  fi
  : >"$LOCKF"; echo $$ >&$LK   # ours, and named for whoever queues next
  # Hold it HERE, and run the suite as a child with the fd shut ({LK}>&-). An flock lives until every copy of its
  # fd is closed, and a fd the suite held would be inherited by everything it spawns: one orphan it failed to reap
  # (case H4 below is exactly that) used to pin this lock long after its run was gone, leaving the next run queued
  # behind a pid that was already dead — for as long as the orphan lived. Nothing below this line can hold the
  # lock; this shell can, it does nothing else until the suite returns, and it lets go on every path out.
  # …and the suite's SIGNALS are its own as well, not the launcher's. A `nohup`'d launch (every land chain the
  # planning session ran out of its shell on 2026-09-01) leaves SIGHUP ignored; exec keeps that, and bash silently
  # cannot trap a signal ignored at entry — cc-loop's HUP trap did nothing, and H4 ("orphaned claude survived the
  # loop kill") went red 3/3 from that shell and green from tmux, with the env unset for good measure and the real
  # difference unnoticed. Bash cannot undo it either, so the exec goes through python, which puts HUP/INT/QUIT/TERM
  # back to default — the way tmux and systemd start things. (Repro: nohup a cc-loop, HUP it, its claude lives on.)
  export CC_SELFTEST_HELD=$$
  python3 -c 'import os, signal, sys
for s in (signal.SIGHUP, signal.SIGINT, signal.SIGQUIT, signal.SIGTERM): signal.signal(s, signal.SIG_DFL)
os.execv(sys.argv[1], sys.argv[1:])' "$SELF" "$@" {LK}>&-; exit $?
fi
HOLDER=$CC_SELFTEST_HELD; unset CC_SELFTEST_HELD   # our children must not think they are already inside the lock
if [ -n "${CC_SELFTEST_LOCK_ONLY:-}" ]; then   # the case below re-runs this file to here and no further —
  echo "== lock taken by pid $HOLDER =="                # it stops before a single fixture exists
  # ...and, asked to, leaves one child behind on purpose, so the case can prove the child did NOT inherit the lock.
  if [ -n "${CC_SELFTEST_LOCK_ORPHAN:-}" ]; then sleep 60 & echo "== orphan $! =="; fi
  exit 0
fi
pass=0; fail=0; ok(){ pass=$((pass+1)); echo "  ✓ $1"; }; bad(){ fail=$((fail+1)); echo "  ✗ $1"; }
# Every run owns a namespace ($RUN): repo name, fixture dir, notify log, usage-limit stamp, tmux windows and
# processes all carry it. Two selftests (two worktrees, one box) must never read, write or kill each other's things
# — a global `pkill` here once failed 4 tests in a run that was, on its own, green.
RUN=$$; REPO=_cctest$RUN; T=~/.cc/selftest-$RUN; mkdir -p "$T"
export CC_NOTIFY_LOG="$T/notify.log"      # not the box's own ~/.cc/notify.log: runs would count each other's lines
export CC_LIMIT_STAMP="$T/claude-limit"   # not the box's live stamp: a test limit must never make a real loop wait
export CC_HANDOFF_DIR="$T/handoff"        # not ~/.cc/state/handoff: an overlap case writes REAL records, and they
export CC_HANDOFF_KICK_WAIT=0          # every real --overlap leaves a detached --kick child: with a wait it polls tmux for
export CC_HANDOFF_NO_KICK=1   # ...and no --kick child at all: a fixture successor never boots, and a kick that cannot land pages the owner
                                          # 4 min and recreates $T/ctx/handoff.log after the trap; with none it gives up at once
                                          # outlived the run — `cc-handoff --status` was listing a week of _cctest
                                          # successors, and cc-guard walks that directory on every single call.
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
if [ "\$n" -lt 4 ]; then echo "capped work \$n" > "capped-\$n.txt"; echo "- capped iteration \$n" >> "\$st/progress.md"; fi
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
sbx=$("$B/cc-sandbox" selfcheck 2>&1 | tail -1)   # real bwrap on a scratch repo: secrets and sockets absent inside, git whole, off = untouched
grep -q '0 failed' <<<"$sbx" && ok "cc-sandbox selfcheck: ${sbx##*: }" || bad "cc-sandbox selfcheck: $sbx"
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
# the fixture is 20k of a 200k window, so the floors (60k/90k) are lowered out of the way for these cases.
# CC_HANDOFF_OVERLAP=0 is PINNED, like the overlap section below pins it per command. These four cases assert
# the classic stop-then-restart path (PENDING, deferred while work is in flight), and `cc-context` takes that
# path only when the overlap is off — or when $CC_HANDOFF is set, which is the trap. Unpinned they read the
# key from the BOX's ~/.cc/config, so once the owner turned overlapping handoffs on they stopped exercising
# the deferral they were written for and started asserting against the overlap path.
# MEASURED 2026-08-31, because the number is the argument: main gave 163/0 to the one session holding
# $CC_HANDOFF and 159/4 to every worker, the owner, and every fresh session. Five consecutive workers saw the
# red, called it "pre-existing, not mine" — each correctly — and none could prove it, because the only session
# placed to adjudicate was the one that could not reproduce it. A suite must assert the path it NAMES, not the
# one the box happens to be configured for. The overlap path has its own cases below and in `cc-context
# selfcheck`; this path must keep working because the new one fails INTO it.
CTXP="CC_CONTEXT_WARN_MIN=0 CC_CONTEXT_HANDOFF_MIN=0 CC_HANDOFF_OVERLAP=0"
export CC_HANDOFF_OVERLAP=0   # for the calls in this section that do not go through $CTXP
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

unset CC_HANDOFF_OVERLAP   # the overlap section below decides for itself, per command
echo "== cc-owed (the same hook says what is still owed in Slack) =="
owc=$("$B/cc-owed" selfcheck 2>&1)
grep -q '0 failed' <<<"$owc" && ok "cc-owed selfcheck: ${owc##*: }" || bad "cc-owed selfcheck: $owc"
OWD="$T/owed"; SLD="$T/slackdir"; mkdir -p "$SLD"     # records and cc-slack's marks both under $T: never the box's own
CH=C0TEST0001; RT=1700000000.000100
hook(){ pay "${2:-}" | ( cd ~/.cc/worktrees/$REPO/w1 && env CC_OWED_RECORDS="$OWD" CC_SLACK_DIR="$SLD" ${1:+env $1} "$B/cc-checkpoint" ); }
cat >> "$PD/$sid.jsonl" <<EOF
{"type":"user","timestamp":"2026-01-01T01:00:00Z","message":{"role":"user","content":"<channel source=\"cc-slack\" chat_id=\"$CH\" thread_ts=\"$RT\" ts=\"$RT\" user=\"Owner\" role=\"owner\" channel=\"#one\" target=\"one\">\ndid it land\n</channel>"}}
EOF
o1=$(hook)
{ grep -q 'OWED' <<<"$o1" && grep -q "$CH" <<<"$o1" && grep -q 'did it land' <<<"$o1"; } \
  && ok "a message nothing answered is said back to the session, with the call that pays it" || bad "no owed decision: $o1"
[ -z "$(hook)" ] && ok "it is said once, not every turn" || bad "the session was told twice: $(hook)"
"$B/cc-owed" --transcript "$PD/$sid.jsonl" >/dev/null 2>&1; [ $? = 1 ] \
  && ok "a debt is an exit code too, for anything that asks" || bad "cc-owed --transcript did not report the debt"
rm -f "$T/ctx/$sid.json" "$OWD/$sid.json"    # both hooks fresh: one decision must carry both, owed first
o2=$(hook "$CTXP CC_CONTEXT_WARN_PCT=1 CC_CONTEXT_HANDOFF_PCT=2" ',"background_tasks":[{"id":"x"}]')
{ grep -q 'OWED' <<<"$o2" && grep -q 'CONTEXT 10%' <<<"$o2" && [ "$(grep -c decision <<<"$o2")" = 1 ]; } \
  && ok "the context line and the debt arrive as ONE decision, the debt first" || bad "hooks did not merge: $o2"
python3 - "$SLD/marks.json" "$CH:$RT:white_check_mark" <<'PY'   # cc-slack's own file, written here as it writes it
import json, sys
json.dump({sys.argv[2]: 9999999999.0}, open(sys.argv[1], "w"))
PY
rm -f "$OWD/$sid.json"
[ -z "$(hook)" ] && ok "a ✅ the session put on the thread settles it — cc-slack's marks are read, not recomputed" \
  || bad "a done thread was still owed: $(hook)"
rm -f "$SLD/marks.json" "$OWD/$sid.json"
cat >> "$PD/$sid.jsonl" <<EOF
{"type":"assistant","timestamp":"2026-01-01T01:01:00Z","message":{"role":"assistant","content":[{"type":"tool_use","name":"mcp__cc-slack__reply","input":{"chat_id":"$CH","thread_ts":"$RT","ts":"$RT","text":"it landed"}}]}}
EOF
[ -z "$(hook)" ] && ok "a word in that thread ends the debt" || bad "answered thread still owed: $(hook)"
[ "$(env CC_OWED_RECORDS="$OWD" "$B/cc-owed" --ledger | wc -l)" = 2 ] \
  && ok "every debt said is one countable line on the ledger" || bad "ledger: $(env CC_OWED_RECORDS="$OWD" "$B/cc-owed" --ledger)"
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
# A HEREDOC BODY IS DATA — except when something on the line would run it, and then it is a command again.
miss=""; for probe in 'Bash|{"command":"bash <<E\ngh pr merge 1\nE"}' 'Bash|{"command":"cat <<E\ngh pr merge 1"}' \
             'Bash|{"command":"ssh box <<E\nsudo reboot\nE"}' 'Bash|{"command":"xargs -0 <<E\ngh pr merge 1\nE"}'; do
  [ "$(g "${probe%%|*}" "${probe#*|}" "$wt")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "a heredoc an interpreter would RUN, and one that never ends, both fail closed" || bad "heredoc bypass:$miss"
miss=""; for probe in 'Bash|{"command":"cat >> notes.md <<E\nthe owner decides: gh pr merge, cc-land, sudo anything\nE"}' \
             'Bash|{"command":"git commit -F - <<E\nfix: stop cc-land running twice\nE"}'; do
  [ "$(g "${probe%%|*}" "${probe#*|}" "$wt")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "...but prose that merely NAMES a gated command is written, not refused (brief, journal, commit message)" || bad "guard reads prose as a command:$miss"
[ "$(printf '{"tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"%s"}' "$wt" | CC_ROLE=worker env PATH=/nonexistent /bin/bash "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] && ok "guard refuses when jq is missing (gates would be silently off)" || bad "guard without jq"
# member-facing: the .cc/member-facing marker alone (NO CC_ROLE — the env is a convenience) = every worker gate plus spend/leak/wiring
# A MEMBER DENY NOW SPEAKS (see below), so every member probe runs against a STUB HOME: a fake ~/bin/cc-slack and
# ~/bin/cc-notify that only record their argv, and a ~/.cc/config with no real token. Nothing in this file may
# reach the workspace, and the secret-path probes are the stub's own files so `secret_path` still matches.
GH="$T/ghome"; mkdir -p "$GH/bin" "$GH/.cc" "$GH/.ssh"; : > "$GH/.cc/config"; : > "$GH/.ssh/id_ed25519"
mkdir -p "$GH/.claude" "$GH/repo/core/ccbox"; : > "$GH/.claude/.credentials.json"     # empty stubs, never a real token
: > "$GH/repo/core/ccbox/env"; : > "$GH/repo/core/ccbox/env.example"; ln -s "$GH/repo/core/ccbox" "$GH/ccbox"   # ~/ccbox IS a symlink on the box
cat > "$GH/bin/cc-slack" <<F
#!/usr/bin/env bash
printf 'BOT: %s\n' "\$*" >> "$T/guard.args"
F
sed 's/BOT:/NOTIFY:/' "$GH/bin/cc-slack" > "$GH/bin/cc-notify"; chmod +x "$GH/bin/cc-slack" "$GH/bin/cc-notify"
mf="$T/member"; mkdir -p "$mf/.cc"; : > "$mf/.cc/member-facing"; touch "$mf/note.md"
m(){ printf '{"tool_name":"%s","tool_input":%s,"cwd":"%s"}' "$1" "$2" "$3" | env HOME="$GH" CC_GUARD_ASKS="$T/asks" "$B/cc-guard" >/dev/null 2>&1; echo $?; }
# STAGE 0 of the worker sandbox (docs/design-worker-sandbox.md §1): the two holes that were member-only are shut
# for a WORKER too. the box user is in group `docker`, so `docker run -v /:/host` is root on the whole filesystem with no
# escalation; ~/.claude/.credentials.json is the box's Claude account and its spend, ~/ccbox/env a GitHub PAT and a
# deploy token. Same stub HOME as the member probes, and no probe reads a real credential — the guard matches the
# PATH (realpath -m resolves one that need not exist), it never opens the file.
w(){ printf '{"tool_name":"%s","tool_input":%s,"cwd":"%s"}' "$1" "$2" "$3" | env HOME="$GH" CC_GUARD_ASKS="$T/asks" CC_ROLE=worker "$B/cc-guard" >/dev/null 2>&1; echo $?; }
WP=('Bash|{"command":"docker run -v /:/host alpine cat /host/etc/shadow"}' 'Bash|{"command":"podman run --rm alpine sh"}'
    'Bash|{"command":"cat ~/.claude/.credentials.json"}' 'Bash|{"command":"jq -r .accessToken $HOME/.claude/.credentials.json"}'
    'Bash|{"command":"grep VERCEL_TOKEN ~/ccbox/env"}' 'Bash|{"command":"source $HOME/ccbox/env"}'
    "Bash|{\"command\":\"cat $GH/repo/core/ccbox/env\"}" 'Bash|{"command":"cat core/ccbox/env"}'
    "Read|{\"file_path\":\"$GH/.claude/.credentials.json\"}" "Read|{\"file_path\":\"$GH/ccbox/env\"}"
    "Read|{\"file_path\":\"$GH/repo/core/ccbox/env\"}")
miss=""; for probe in "${WP[@]}"; do [ "$(w "${probe%%|*}" "${probe#*|}" "$wt")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "a WORKER is denied containers and both credential files — by ~/ path, by real path and through a symlinked ~/ccbox alike" || bad "worker stage-0 gate misses:$miss"
miss=""; for probe in 'Bash|{"command":"ls -la"}' 'Bash|{"command":"git log --oneline -5"}' 'Bash|{"command":"cat ~/.cc/config"}' \
             'Bash|{"command":"cat core/ccbox/env.example"}' "Read|{\"file_path\":\"$GH/repo/core/ccbox/env.example\"}" \
             "Read|{\"file_path\":\"$GH/.cc/config\"}"; do
  [ "$(w "${probe%%|*}" "${probe#*|}" "$wt")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "...and no wider than that: env.example is not a credential, and the box's OTHER secrets stay member-only as before" || bad "worker gate over-blocks:$miss"
[ "$(w Bash '{"command":"systemctl --user list-units"}' "$wt")" = 2 ] \
  && ok "...and a worker's systemctl read is unchanged — denied before stage 0, denied after (the list sorts by spelling, not reach)" || bad "systemctl gate moved under stage 0"
MP=('Bash|{"command":"sudo apt install x"}' 'Bash|{"command":"gh pr merge 1"}' 'Bash|{"command":"cc r t --go build it"}'
    'Bash|{"command":"cc board add r t title text --go"}' 'Bash|{"command":"cc-loop r t"}' 'Bash|{"command":"claude -p do it"}'
    'Bash|{"command":"cat ~/.cc/config"}' 'Bash|{"command":"tail -5 $HOME/.ssh/id_ed25519"}'
    'Bash|{"command":"docker run -v /:/host alpine"}' 'Bash|{"command":"cat ~/.claude/.credentials.json"}'
    'Bash|{"command":"head -1 ~/ccbox/env"}'
    'Bash|{"command":"cc slack off"}' 'Bash|{"command":"cc slack mkchannel help"}'
    'Bash|{"command":"cc-slack updates-sweep"}'
    "Read|{\"file_path\":\"$GH/.cc/config\"}" "Edit|{\"file_path\":\"$GH/member-probe.txt\"}")
miss=""; for probe in "${MP[@]}"; do [ "$(m "${probe%%|*}" "${probe#*|}" "$mf")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "member-facing marker denies all 16 probes (merge/host, dispatch, secrets, containers, credentials, Slack wiring incl. updates-sweep, edit outside)" || bad "member gate misses:$miss"
miss=""; for probe in "${MP[@]}"; do [ "$(m "${probe%%|*}" "${probe#*|}" "$HOME")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "no regression: an unmarked cwd (planning session) is gated by none of them" || bad "unmarked cwd gated:$miss"
miss=""; for probe in 'Bash|{"command":"ls -la"}' 'Bash|{"command":"cc-notify -t help the owner must decide this"}' \
             'Bash|{"command":"git log --oneline -5"}' "Read|{\"file_path\":\"$mf/note.md\"}" "Edit|{\"file_path\":\"$mf/note.md\"}"; do
  [ "$(m "${probe%%|*}" "${probe#*|}" "$mf")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "member-facing session still reads, edits in place and escalates with cc-notify" || bad "member gate over-blocks:$miss"
# The probes above hand payloads STRAIGHT to cc-guard. Live, Claude Code runs the hook only for tools the PreToolUse
# MATCHER names — and Read|NotebookRead|Grep|Glob had a deny branch for days that no call ever reached, because the
# matcher stopped at NotebookEdit (audit 2026-09-01 F1). So: every tool cc-guard has a case branch for must be in the
# matcher, in BOTH files that carry it (the managed manifest the drift check reads, the default install.sh copies).
C="$B/../config"; mm=$(jq -r '.hooks[] | select(.event=="PreToolUse") | .matcher' "$C/claude-managed.json")
ms=$(jq -r '.hooks.PreToolUse[] | select(any(.hooks[]; .command|test("cc-guard"))) | .matcher' "$C/claude-settings.json")
gt=$(grep -oE '^  [A-Za-z|]+\)' "$B/cc-guard" | tr -d ' )' | tr '|' '\n' | sort -u)   # the guard's own case labels
miss=""; for tool in $gt; do for f in managed:"$mm" settings:"$ms"; do
  tr '|' '\n' <<<"${f#*:}" | grep -qx "$tool" || miss="$miss ${f%%:*}:$tool"; done; done
[ -n "$gt" ] && grep -qx Read <<<"$gt" && [ "$mm" = "$ms" ] && [ -z "$miss" ] \
  && ok "the PreToolUse matcher carries every tool cc-guard gates ($(tr '\n' ' ' <<<"$gt"| sed 's/ $//')), identically in claude-managed.json and claude-settings.json" \
  || bad "PreToolUse matcher does not reach the guard: missing[$miss] managed=[$mm] settings=[$ms]"
# A MEMBER WORKSPACE is the one member that DOES dispatch — inside itself and nowhere else. The marker is
# .cc/member-workspace at ~/dev/<handle>, and a TRACK of that workspace inherits the tier rather than being promoted
# to the ordinary worker one by its own .cc/track. Defence in depth: docs/design-member-workspaces.md, "the boundary".
# The fixtures live under $T (~/.cc/…) and never /tmp — /tmp is a write root, so a probe there would pass for free.
# EVERY MARKER HERE CLAIMS `other`, and every case still resolves to `alice`: identity is the PATH
# (~/dev/<handle>, ~/.cc/worktrees/<repo>/<track>) because a marker's body is a file the member may edit.
mkdir -p "$GH/dev/alice/.cc" "$GH/.cc/worktrees/alice/todo/.cc" "$GH/.cc/worktrees/other/forged/.cc"
: > "$GH/dev/alice/.cc/member-facing"; printf 'other\n' > "$GH/dev/alice/.cc/member-workspace"
printf 'other\nforged\n' > "$GH/.cc/worktrees/alice/todo/.cc/track"
# …and a worktree carrying COMMITTED markers — what `git add -A` used to ship into every one of them.
: > "$GH/.cc/worktrees/other/forged/.cc/member-facing"; printf 'alice\n' > "$GH/.cc/worktrees/other/forged/.cc/member-workspace"
printf 'alice\ntodo\n' > "$GH/.cc/worktrees/other/forged/.cc/track"
mws="$GH/dev/alice"; mwt="$GH/.cc/worktrees/alice/todo"; mwf="$GH/.cc/worktrees/other/forged"
WOK=('Bash|{"command":"cc alice todo --go build it"}|W' 'Bash|{"command":"cc alice todo"}|W'
     'Bash|{"command":"cc board add alice todo title brief"}|W' 'Bash|{"command":"cc board show alice"}|W'
     'Bash|{"command":"cc alice todo --go x"}|K' "Edit|{\"file_path\":\"$GH/.cc/state/alice/todo/task.md\"}|W")
WNO=('Bash|{"command":"cc other t --go build it"}|W' 'Bash|{"command":"cc-loop other t"}|W'
     'Bash|{"command":"cc-loop alice todo"}|W' 'Bash|{"command":"cc other"}|W' 'Bash|{"command":"cc other t"}|W'
     'Bash|{"command":"cc board add other t title brief"}|W' 'Bash|{"command":"cc board show other"}|W'
     'Bash|{"command":"cc alice a --go x; cc other b --go y"}|W' 'Bash|{"command":"claude -p do it"}|W'
     'Bash|{"command":"cat ~/.cc/config"}|W' 'Bash|{"command":"docker run -v /:/host x"}|W'
     'Bash|{"command":"cc slack mkchannel x"}|W' 'Bash|{"command":"cc other t --go x"}|K'
     'Bash|{"command":"cat ~/.cc/config"}|K' 'Bash|{"command":"cc board add other t x y"}|K'
     "Edit|{\"file_path\":\"$GH/.cc/state/other/x/task.md\"}|W"
     'Bash|{"command":"cc alice todo --go x"}|F' 'Bash|{"command":"cat ~/.cc/config"}|F')
wprobe(){ local t=${1%%|*} rest=${1#*|} j c; j=${rest%|*}; c=${rest##*|}
          case "$c" in W) c=$mws;; F) c=$mwf;; *) c=$mwt;; esac; m "$t" "$j" "$c"; }
miss=""; for probe in "${WOK[@]}"; do [ "$(wprobe "$probe")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "a member WORKSPACE works inside itself: dispatch, a session, its own board and track state — from the workspace dir and from its worker's worktree" || bad "member workspace over-blocked:$miss"
miss=""; for probe in "${WNO[@]}"; do [ "$(wprobe "$probe")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "...and nothing outside it: another repo's dispatch, session, board or track state, a mixed command, raw claude -p, the box's secrets, containers, Slack wiring — from the worker's worktree too; cc-loop is refused even INSIDE (the daily cap is charged in \`cc … --go\`, so a direct loop would spend off the ledger); and a worktree carrying committed markers gains nothing at all" || bad "member workspace escapes:$miss"
[ "$(m Bash '{"command":"cc alice todo --go x"}' "$mf")" = 2 ] && ok "a plain member-facing session still dispatches nothing: the exception is the WORKSPACE marker, not the member role" || bad "member-facing session gained dispatch"
# THE DOOR OPENS FROM OUTSIDE: CC_MEMBER_SANDBOX=1 is the sandbox's to set. From a plain member dir
# `CC_MEMBER_SANDBOX=1 cc alice todo` passed every rule and started a workspace session ON THE HOST (review 2, A).
miss=""; for c in 'CC_MEMBER_SANDBOX=1 cc alice todo' 'env CC_MEMBER_SANDBOX=1 cc alice todo --go x' 'export CC_MEMBER_SANDBOX=1; cc alice todo' 'bash -c \"CC_MEMBER_SANDBOX=1 cc alice todo\"'; do
  for cw in "$mf" "$mws" "$mwt"; do [ "$(m Bash "{\"command\":\"$c\"}" "$cw")" = 2 ] || miss="$miss [$c @${cw##*/}]"; done; done
[ -z "$miss" ] && ok "setting CC_MEMBER_SANDBOX is denied from every member-tier cwd (prefix, env, export, bash -c): the boundary opens the door, never the member" || bad "CC_MEMBER_SANDBOX settable by a member:$miss"
[ "$(m Bash '{"command":"CC_MEMBER_SANDBOX=1 cc alice todo"}' "$GH")" = 0 ] && [ "$(m Bash '{"command":"grep -n CC_MEMBER_SANDBOX core/bin/cc"}' "$mws")" = 0 ] \
  && ok "...the owner's own cwd is untouched, and naming the variable (a grep) is not setting it" || bad "CC_MEMBER_SANDBOX rule over-blocks"
# .cc/track MEANS SOMETHING ONLY UNDER ~/.cc/worktrees/<repo>/<track>, where cc makes them. One in a member's subdir
# used to set role=worker there — and hand that member the box's config and another repo's dispatch (review 2, C).
mkdir -p "$GH/dev/alice/sub/.cc" "$GH/stray/.cc"; printf 'other\nt\n' > "$GH/dev/alice/sub/.cc/track"; printf 'other\nt\n' > "$GH/stray/.cc/track"
[ "$(m Bash '{"command":"cat ~/.cc/config"}' "$GH/dev/alice/sub")" = 2 ] && [ "$(m Bash '{"command":"cc other t --go x"}' "$GH/dev/alice/sub")" = 2 ] \
  && [ "$(m Bash '{"command":"cc alice todo --go x"}' "$GH/dev/alice/sub")" = 0 ] \
  && ok "a .cc/track inside a member workspace is just a file: the subdir is still alice's world (secrets and another repo's dispatch denied, its own dispatch allowed)" || bad "a member subdir's .cc/track promoted it to worker"
[ "$(m Bash '{"command":"gh pr merge 1"}' "$GH/stray")" = 0 ] && [ "$(printf '{"tool_name":"Bash","tool_input":{"command":"gh pr merge 1"},"cwd":"%s"}' "$GH/stray" | env HOME="$GH" CC_ROLE=worker "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] \
  && ok "...and outside ~/.cc/worktrees it is no track marker at all — CC_ROLE from the env still gates there" || bad "stray .cc/track honoured outside ~/.cc/worktrees"
# THE BOUNDARY (owner, 2026-09-01): a member workspace session — interactive, main or worker — does not run on this
# host at all until member-sandbox exists. Not a guard rule: `cc` and `cc-loop` refuse it themselves, whoever asks,
# and CC_MEMBER_SANDBOX=1 (set inside the boundary) is the only thing that opens the door.
gout(){ env HOME="$GH" PATH="$B:$PATH" "$@" 2>&1; }
o1=$(gout "$B/cc" alice todo --go x); r1=$?
o2=$(gout "$B/cc-loop" alice todo); r2=$?
o3=$(env HOME="$GH" CC_MEMBER_SANDBOX=1 "$B/cc-loop" alice todo 2>&1)
o4=$(env HOME="$GH" "$B/cc-loop" other todo 2>&1)
[ "$r1" = 1 ] && [ "$r2" = 2 ] && grep -q 'member workspace' <<<"$o1" && grep -q boundary <<<"$o2" \
  && ! grep -q boundary <<<"$o3" && ! grep -q boundary <<<"$o4" \
  && ok "cc and cc-loop refuse to start a member workspace session on the host (the boundary is not a blocklist), and only CC_MEMBER_SANDBOX=1 opens it — an ordinary repo is untouched" \
  || bad "member workspace session startable on the host (cc rc=$r1, cc-loop rc=$r2)"
o5=$(env HOME="$GH" CC_MEMBER_SANDBOX=1 "$B/cc-loop" alice todo --budget 1e9 2>&1); r5=$?
o6=$(env HOME="$GH" CC_MEMBER_SANDBOX=1 "$B/cc-loop" alice todo --budget 5.5 2>&1)
[ "$r5" = 2 ] && grep -q 'budget must be' <<<"$o5" && ! grep -q 'budget must be' <<<"$o6" \
  && ok "--budget must be a plain number: '1e9' (charged as \$8, spent as a billion) is refused, 5.5 is not" || bad "non-numeric --budget passed through (rc=$r5: $o5)"
[ "$(printf '{"tool_name":"Bash","tool_input":{"command":"cc r t --go x"},"cwd":"%s"}' "$mf" | env HOME="$GH" CC_GUARD_ASKS="$T/asks" CC_ROLE=worker "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] && ok "a marked cwd beats an inherited CC_ROLE=worker (a marker only tightens)" || bad "member marker downgraded by CC_ROLE=worker"
[ "$(printf '{"tool_name":"Bash","tool_input":{"command":"cc r t --go x"},"cwd":"%s"}' "$GH" | env HOME="$GH" CC_GUARD_ASKS="$T/asks" CC_ROLE=member "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] && ok "CC_ROLE=member gates with no marker at all" || bad "CC_ROLE=member ignored"
[ "$(printf '{"tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"%s"}' "$mf" | CC_ROLE=member env PATH=/nonexistent /bin/bash "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] && ok "guard refuses when jq is missing for a member too (no jq = no cwd = no marker walk)" || bad "member guard without jq"
# A REFUSAL IN A MEMBER-FACING CHANNEL IS AN ASK, NOT SILENCE — the member sees it AND the owner is told.
# Both halves used to end at the deny: the member got nothing, the owner was never told there was anything to
# approve, and a gate that stops work without producing a visible ask looks exactly like the box ignoring somebody.
ask(){ rm -rf "$T/asks"; : > "$T/guard.args"
       printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s"}' "$1" "$2" | env HOME="$GH" CC_GUARD_ASKS="$T/asks" ${3:+CC_ROLE=$3} "$B/cc-guard" >/dev/null 2>&1; echo $?; }
SEND="cc-slack post --file /tmp/carpet.png"   # the 2026-08-30 incident itself: a member asked twice for images
[ "$(ask "$SEND" "$mf")" = 2 ] && ok "the member's request is still refused — the gate did not soften" || bad "member deny lost"
grep -q "^BOT: post -c #member .*posting to the owner" "$T/guard.args" \
  && ok "...and the MEMBER sees why, in their own channel (the dir's name is the channel's)" || bad "nothing reached the member: $(cat "$T/guard.args")"
grep -q '🔐' "$T/guard.args" \
  && ok "...as the box's own 🔐 form, which the daemon's sweep marks ❓ needs-you on the owner's tab" || bad "no 🔐 in the channel post"
grep -q "^NOTIFY: --owner -p high .*posting to the owner" "$T/guard.args" \
  && ok "...and the OWNER is told there is something to approve (--owner: a DM, never that channel)" || bad "the owner was not told: $(cat "$T/guard.args")"
: > "$T/guard.args"   # same channel, same reason, straight away: the session retrying must not spray the channel
printf '{"tool_name":"Bash","tool_input":{"command":"cc-slack post -c x hi"},"cwd":"%s"}' "$mf" | env HOME="$GH" CC_GUARD_ASKS="$T/asks" "$B/cc-guard" >/dev/null 2>&1
[ ! -s "$T/guard.args" ] && ok "one ask per channel+reason per TTL, however often the session retries" || bad "the deny sprayed: $(cat "$T/guard.args")"
[ "$(ask "$SEND" "$mf")" = 2 ] && [ -s "$T/guard.args" ] && ok "...and a fresh window asks again (the TTL is a delay, not a mute)" || bad "the ask never comes back"
: > "$T/guard.args"; [ "$(ask "gh pr merge 1" "$wt" worker)" = 2 ] && [ ! -s "$T/guard.args" ] \
  && ok "a WORKER deny is untouched: it has a board, a journal and STATUS: BLOCKED, and posts nothing" || bad "a track deny posted to Slack: $(cat "$T/guard.args")"
: > "$T/guard.args"; [ "$(ask "gh pr merge 1" "$GH")" = 0 ] && [ ! -s "$T/guard.args" ] \
  && ok "the owner's own sessions are unaffected — not gated, and nothing posted anywhere" || bad "an ungated cwd posted: $(cat "$T/guard.args")"
: > "$T/guard.args"; rm -rf "$T/asks"
[ "$(ask "cc-config list" "$mf")" = 2 ] && ok "the box's config is not a member's to read — its one sanctioned reader is denied too" || bad "cc-config list slipped the member gate"
[ "$(ask "cc-config set SLACK_APP_TOKEN x" "$mf")" = 2 ] && ok "...nor to rewrite" || bad "cc-config set slipped the member gate"
: > "$T/guard.args"; rm -rf "$T/asks"   # leave the harness state as found: the cases below read these fresh
printf '{"tool_name":"Bash","tool_input":{"command":"cc r t --go x"},"cwd":"%s"}' "$GH" | env HOME="$GH" CC_GUARD_ASKS="$T/asks" CC_ROLE=member "$B/cc-guard" >/dev/null 2>&1
{ grep -q '^NOTIFY: --owner' "$T/guard.args" && ! grep -q '^BOT:' "$T/guard.args"; } \
  && ok "CC_ROLE=member with no marker: the owner is still told, and nothing is posted to a channel we cannot name" || bad "markerless member ask: $(cat "$T/guard.args")"
echo "== overlapping handoff: two sessions, one cwd, exactly one of them live =="
export CC_HANDOFF_DIR="$T/handoff" CC_HANDOFF_RETIRE_GRACE=1 CC_HANDOFF_DRAIN=1   # never the box's own records, never a 2-min grace or a 10-min drain
ho=$("$B/cc-handoff" selfcheck 2>&1 | tail -1)
grep -q '0 failed' <<<"$ho" && ok "cc-handoff selfcheck: ${ho##*: }" || bad "cc-handoff selfcheck: $ho"
st=$("$B/cc" handoff --status 2>&1); grep -q "no overlapping handoff is open" <<<"$st" && ok "cc handoff --status delegates by target" || bad "cc handoff --status: [$st]"
out=$(CC_HANDOFF_OVERLAP=0 "$B/cc" handoff --overlap "$REPO" 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "CC_HANDOFF_OVERLAP" <<<"$out"; } && ok "the overlap path is off until it is turned on (the old handoff is untouched)" || bad "overlap not gated by config: $out"
# a real predecessor window; the successor's `claude` is /bin/true, so its pane falls through to the wrapper shell
for t in hq hs hx hz; do mkdir -p ~/.cc/worktrees/$REPO/$t; done   # the successor's pane IS `cc __runnext` (exec: claude must be the pane's
                                          # direct child for cc-msg), and that cds into the track's worktree or exits
tmux new-window -d -t main -n "$REPO/hx" -c "$T" "bash -c 'sleep 300; :'"   # a real child: `pane_live` is what tells a session from a bare shell
out=$(CC_HANDOFF_OVERLAP=1 "$B/cc" handoff --overlap "$REPO/hx" --session sid-pre --in-flight "uncommitted work in hx" 2>&1)
hid=$(jq -r .id "$T/handoff/$REPO--hx.json" 2>/dev/null)
{ [ -n "$hid" ] && [ "$(jq -r .live "$T/handoff/$REPO--hx.json")" = predecessor ]; } && ok "the record names the predecessor as live from the first instant" || bad "overlap record: $out"
grep -q "uncommitted work in hx" "$T/handoff/$REPO--hx.brief" 2>/dev/null && ok "the successor's brief carries what is unfinished RIGHT NOW" || bad "successor brief has no in-flight checklist"
tmux list-windows -t main -F '#W' | grep -qx "$REPO/hx~next" && ok "the successor came up ALONGSIDE — the predecessor was not stopped" || bad "no successor window"
# THE SUCCESSOR MUST ACCEPT ITS OWN STARTUP DIALOG. Its window is "<target>~next"; `cc __runnext` knew only
# the target, so it accepted in the PREDECESSOR's window and its own sat on the --dangerously-load-development-
# channels confirmation until a human noticed (2026-09-01 02:10Z; the 2026-08-28 incident, again).
tmux display-message -p -t "$REPO/hx~next" '#{pane_start_command}' 2>/dev/null | grep -q "CC_HANDOFF_WINDOW='$REPO/hx~next'" \
  && ok "the successor is started knowing its OWN window, so it accepts its own dialog and does not park on it" || bad "no CC_HANDOFF_WINDOW on the successor: $(tmux display-message -p -t "$REPO/hx~next" '#{pane_start_command}' 2>&1)"
CC_HANDOFF_OVERLAP=1 "$B/cc" handoff --overlap "$REPO/hx" >/dev/null 2>&1 && bad "a second overlap was allowed for one target" || ok "an overlap is refused while one is open — one successor at a time"
# the guard, from BOTH sides of the record. cwd is $T: no marker, so only the record can gate.
h(){ printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s","session_id":"%s"}' "$1" "$T" "${3:-}" | env CC_HANDOFF="${2:-}" "$B/cc-guard" >/dev/null 2>&1; echo $?; }
miss=""; for c in "gh pr merge 1" "git push origin HEAD" "cc r t --go x" "cc done r t" "sudo apt install x"; do
  [ "$(h "$c" "$hid")" = 2 ] || miss="$miss [$c]"; done
[ -z "$miss" ] && ok "the non-live successor is denied merge/push/dispatch/PR/host — by its env, not by a marker" || bad "successor not gated:$miss"
[ "$(h "git log --oneline" "$hid")" = 0 ] && ok "...and may still read, search and think" || bad "successor over-gated"
[ "$(h "gh pr merge 1" "" sid-pre)" = 0 ] && ok "the LIVE predecessor is gated by none of it" || bad "predecessor gated while live"
pp=$(tmux list-panes -t "$(jq -r .predecessor.tmux "$T/handoff/$REPO--hx.json")" -F '#{pane_id}' 2>/dev/null | head -1)
[ "$(TMUX_PANE=$pp h "gh pr merge 1" "" "")" = 0 ] && ok "...nor by its pane while it is live" || bad "predecessor gated by pane while live (pane $pp)"
CC_HANDOFF="$hid" "$B/cc-handoff" --ready "$REPO/hx" >/dev/null 2>&1
[ "$(jq -r .live "$T/handoff/$REPO--hx.json" 2>/dev/null)" = successor ] && ok "one atomic replace moves ownership — the successor is live" || bad "cutover did not move the record"
{ [ "$(h "gh pr merge 1" "" sid-pre)" = 2 ] && [ "$(h "git push origin HEAD" "" sid-pre)" = 2 ]; } && ok "SYMMETRY: after cutover the retired PREDECESSOR is the gated one (no stale-branch push)" || bad "predecessor not gated after cutover"
[ "$(TMUX_PANE=$pp h "gh pr merge 1" "" "")" = 2 ] && ok "...by its PANE too: a planning predecessor's session_id is empty on the record, and the drain is 10 min" || bad "predecessor with no session_id not gated by pane (pane $pp)"
[ "$(h "gh pr merge 1" "$hid")" = 0 ] && ok "...and the successor, now live, is free" || bad "successor still gated after cutover"
[ "$(h "gh pr merge 1" "no-such-record")" = 2 ] && ok "CC_HANDOFF with no record to justify it stays gated (missing = the predecessor is in charge)" || bad "unbacked CC_HANDOFF ungated"
echo '{not json' > "$T/handoff/$REPO--hx.json"
{ [ "$(h "gh pr merge 1" "" sid-pre)" = 0 ] && [ "$(h "gh pr merge 1" "$hid")" = 2 ]; } && ok "a corrupt record falls one way only: predecessor free, successor gated" || bad "corrupt record fell the wrong way"
rm -f "$T/handoff/$REPO--hx.json"
for id in $(tmux list-windows -t main -F '#{window_id} #W' | awk -v r="$REPO/hx" '$2==r || $2==r"~next"{print $1}'); do tmux kill-window -t "$id"; done
# RETIREMENT ENDS THE PREDECESSOR, end to end on real windows. A session cannot exit itself (`/exit` is typed
# by a human), so the old wait-it-out never completed on its own: on 2026-08-31 a retired session ran on for
# 35 minutes as a second live voice, its window still the ACTIVE one. The grace expires into a kill.
tmux new-window -d -t main -n "$REPO/hz" -c "$T" "bash -c 'sleep 300; :'"
CC_HANDOFF_OVERLAP=1 "$B/cc" handoff --overlap "$REPO/hz" --session sid-pre-z >/dev/null 2>&1
hz=$(jq -r .id "$T/handoff/$REPO--hz.json" 2>/dev/null); pz=$(jq -r .predecessor.tmux "$T/handoff/$REPO--hz.json" 2>/dev/null); sz=$(jq -r .successor.tmux "$T/handoff/$REPO--hz.json" 2>/dev/null)
CC_HANDOFF="$hz" "$B/cc-handoff" --ready "$REPO/hz" >/dev/null 2>&1     # --ready fires --retire in the background
for _ in $(seq 60); do [ -f "$T/handoff/$REPO--hz.json" ] || break; sleep 0.5; done
w=$(tmux list-windows -t main -F '#{window_id} #W')
{ ! grep -q "^$pz " <<<"$w"; } && ok "the predecessor is ENDED by the grace, not waited out (it cannot exit itself)" || bad "the predecessor kept its window after --retire"
{ grep -qx "$sz $REPO/hz" <<<"$w" && ! grep -q "$REPO/hz~next" <<<"$w"; } && ok "...and the successor holds its window name, so an owner attaching lands on the live session" || bad "successor window not renamed: $(grep "$REPO/hz" <<<"$w")"
[ ! -f "$T/handoff/$REPO--hz.json" ] && ok "...and the record is cleared, so nothing is gated by it any more" || bad "record survived the retirement"
[ "$(h "cc r t --go x" "$hz")" = 0 ] && ok "TONIGHT'S CASE: a COMPLETED handoff does not brick the session that won it (it still dispatches, PRs and pushes)" || bad "the survivor of a completed handoff is gated"
[ "$(h "cc r t --go x" "no-such-record")" = 2 ] && ok "...while a record missing for any OTHER reason gates exactly as before" || bad "an unbacked CC_HANDOFF was let through"
# TONIGHT'S OTHER HALF, end to end: that survivor must also be able to hand ITSELF off. $CC_HANDOFF dies with
# the successor's process, not with the handoff, so read as a bare flag it silenced cc-context and cc-handoff
# for the rest of that session's life — the box could overlap a target exactly ONCE, and on 2026-09-01 the
# planning session sat past the hand-off line all evening at 51.5% until a human started the handoff by hand.
ev=$(CC_HANDOFF="$hz" CC_HANDOFF_OVERLAP=1 "$B/cc-handoff" --event "$REPO/hz" --level handoff --pct 51.5 --live 2>/dev/null)
{ [ "$(jq -r .action <<<"$ev")" = overlap ] && [ -f "$T/handoff/$REPO--hz.json" ]; } \
  && ok "TONIGHT'S CASE: past the hand-off line, the survivor of a RETIRED handoff opens one of its own — the overlap is not a one-shot" || bad "no overlap opened for the survivor: [$ev]"
"$B/cc-handoff" --abandon "$REPO/hz" >/dev/null 2>&1
ev=$(CC_HANDOFF="$hz-still-open" CC_HANDOFF_OVERLAP=1 "$B/cc-handoff" --event "$REPO/hz" --level handoff --pct 51.5 --live 2>/dev/null)
{ [ "$(jq -r .action <<<"$ev")" = "" ] && [ ! -f "$T/handoff/$REPO--hz.json" ]; } \
  && ok "...while a handoff still OPEN keeps its successor out of it — the rule only relaxes once <id>.done is there" || bad "an open handoff did not hold: [$ev]"
for id in $(tmux list-windows -t main -F '#{window_id} #W' | awk -v r="$REPO/hz" '$2==r || $2==r"~next" || $2==r"~old"{print $1}'); do tmux kill-window -t "$id"; done

# THE SWEEP, on real windows. Every phase above is driven by a session's own Stop hook — which is exactly what
# a session that CRASHED no longer has. On 2026-08-31 a retirement dying between the marker and the record
# would have left the survivor gated with nothing left to reap it; the cc-reconcile timer is what reaps it now.
tmux new-window -d -t main -n "$REPO/hs" -c "$T" "bash -c 'sleep 300; :'"
CC_HANDOFF_OVERLAP=1 "$B/cc" handoff --overlap "$REPO/hs" --session sid-pre-s >/dev/null 2>&1
hs=$(jq -r .id "$T/handoff/$REPO--hs.json" 2>/dev/null); ss=$(jq -r .successor.tmux "$T/handoff/$REPO--hs.json" 2>/dev/null)
"$B/cc-handoff" --sweep >/dev/null 2>&1
[ -f "$T/handoff/$REPO--hs.json" ] && ok "the sweep leaves an overlap that is inside its deadline alone" || bad "a live overlap was swept"
python3 - "$T/handoff/$REPO--hs.json" <<'EOP'
import json, sys, time
r = json.load(open(sys.argv[1])); r["live"] = "successor"; r["phase"] = "cutover"; r["cutover"] = time.time() - 600
json.dump(r, open(sys.argv[1], "w"))
EOP
for id in $(tmux list-windows -t main -F '#{window_id} #W' | awk -v r="$REPO/hs" '$2==r{print $1}'); do tmux kill-window -t "$id"; done   # the predecessor crashed after the cutover
"$B/cc-handoff" --sweep >/dev/null 2>&1
[ -f "$T/handoff/$REPO--hs.json" ] && ok "one sweep alone leaves the record: a single 'gone' reading never un-gates" || bad "one sweep finalized alone"
CC_HANDOFF_GONE_CONFIRM=0 "$B/cc-handoff" --sweep >/dev/null 2>&1
[ ! -f "$T/handoff/$REPO--hs.json" ] && ok "a record whose predecessor is GONE past the grace is finalized by the sweep (two sweeps apart)" || bad "stale record survived the sweep"
[ -f "$T/handoff/$hs.done" ] && ok "...the marker is written, so cc-guard un-gates the only session left" || bad "no completion marker from the sweep"
[ "$(h "cc r t --go x" "$hs")" = 0 ] && ok "...and the survivor of a crashed retirement really is un-gated" || bad "the survivor of a swept handoff is still gated"
tmux list-windows -t main -F '#{window_id} #W' | grep -qx "$ss $REPO/hs" && ok "...holding the target's window name, so an owner attaching lands on it" || bad "the successor did not take the window name"
# the other half: an overlap that never reached --ready expires QUIETLY — its predecessor never stopped working
nb=$(cat "$CC_NOTIFY_LOG" 2>/dev/null | wc -l)
tmux new-window -d -t main -n "$REPO/hq" -c "$T" "bash -c 'sleep 300; :'"
CC_HANDOFF_OVERLAP=1 "$B/cc" handoff --overlap "$REPO/hq" --session sid-pre-q >/dev/null 2>&1
python3 - "$T/handoff/$REPO--hq.json" <<'EOP'
import json, sys, time
r = json.load(open(sys.argv[1])); r["deadline"] = time.time() - 600
json.dump(r, open(sys.argv[1], "w"))
EOP
"$B/cc-handoff" --sweep >/dev/null 2>&1
{ [ ! -f "$T/handoff/$REPO--hq.json" ] && ! tmux list-windows -t main -F '#W' | grep -qx "$REPO/hq~next"; }   && ok "an overdue overlap that never reached --ready expires, successor window and all" || bad "overdue overlap not expired"
[ "$(cat "$CC_NOTIFY_LOG" 2>/dev/null | wc -l)" = "$nb" ] && ok "...quietly: nothing was pushed to the owner about a session that never stopped working" || bad "the quiet expiry paged the owner"
tmux list-windows -t main -F '#W' | grep -qx "$REPO/hq" && ok "...and the predecessor carries on, untouched" || bad "the quiet expiry took the predecessor's window"
for id in $(tmux list-windows -t main -F '#{window_id} #W' | awk -v r="$REPO" '$2 ~ "^"r"/(hs|hq)(~next)?$"{print $1}'); do tmux kill-window -t "$id"; done
# the sweep has NO unit of its own: the existing reconcile timer is what gives it a turn (review rec #8)
grep -q 'cc-handoff", "--sweep"' "$B/cc-reconcile" && [ ! -e "$(dirname "$B")/config/systemd-user/cc-handoff.timer" ]   && ok "the sweep rides the existing cc-reconcile timer — no new unit" || bad "the sweep is not wired through cc-reconcile"
unset CC_HANDOFF_DIR CC_HANDOFF_RETIRE_GRACE CC_HANDOFF_DRAIN

echo "== cc-notify: an escalation reaches the OWNER, not the channel it came from =="
# own HOME (the box's real config and owner id stay out of this) + a stub bot: the args cc-notify hands cc-slack ARE the routing
NH="$T/nh"; mkdir -p "$NH/bin" "$NH/.cc" "$T/chan/.cc" "$T/plain"; : > "$T/chan/.cc/member-facing"
cat > "$NH/bin/cc-slack" <<F
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$T/slack.args"
F
chmod +x "$NH/bin/cc-slack"; printf 'SLACK_BOT_TOKEN=xoxb-test\nSLACK_OWNER_ID=UOWNER\n' > "$NH/.cc/config"
# -u for every config key: the environment now WINS over the file (cc-config's one rule), so a key exported by
# whatever session is running this would beat the fixture's own config below.
N(){ w=$1; shift; : > "$T/slack.args"
     ( cd "$w" && env -u CC_NOTIFY_LOG_ONLY -u SLACK_BOT_TOKEN -u SLACK_OWNER_ID -u SLACK_WEBHOOK -u SLACK_ALERTS \
           -u NTFY_TOPIC -u NTFY_SERVER -u CC_BOX HOME="$NH" CC_NOTIFY_LOG="$NH/.cc/notify.log" "$B/cc-notify" "$@" >/dev/null 2>&1 ); }
N "$T/chan" "Alice needs the staging DB restored"
{ grep -q -- '-c UOWNER' "$T/slack.args" && ! grep -q -- '--route' "$T/slack.args"; } \
  && ok "a member-facing session's escalation DMs the owner, never its own channel" || bad "escalation went to the channel: $(cat "$T/slack.args")"
grep -q 'chan escalation' "$T/slack.args" && ok "it says where it came from (default title '<session dir> escalation')" || bad "escalation title: $(head -1 "$T/slack.args")"
N "$T/plain" --owner "the disk is filling up"
grep -q -- '-c UOWNER' "$T/slack.args" && ok "--owner reaches the owner from any session" || bad "--owner ignored: $(cat "$T/slack.args")"
N "$T/plain" -t "demorepo/w1 done" "PR: x"     # a REAL repo name: this fixture's own is _cctest…, which the gate below stops on purpose
{ grep -q -- "--route demorepo/w1 done" "$T/slack.args" && ! grep -q -- '-c ' "$T/slack.args"; } \
  && ok "no regression: an ordinary notice still routes by title (#<repo>, #alerts)" || bad "routing changed: $(cat "$T/slack.args")"
# THE LADDER (owner, 2026-09-01): the rung is a routing decision, and --decision is the only thing that buys rung 1.
! grep -q -- '--mention' "$T/slack.args" \
  && ok "...and it is ambient — no --mention, so cc-slack aims it at the #<repo>-updates lane (rung 5)" || bad "an ordinary notice @-mentioned the owner: $(cat "$T/slack.args")"
N "$T/plain" --decision -t "demorepo blocked" "which database do I restore?"
{ grep -q -- '--mention' "$T/slack.args" && grep -q -- '--route demorepo blocked' "$T/slack.args"; } \
  && ok "--decision is rung 1: same route, plus --mention — the MAIN channel and a real @-mention of the owner" || bad "--decision did not ask for a mention: $(cat "$T/slack.args")"
N "$T/chan" --decision "the staging DB restore needs your call"
{ grep -q -- '-c UOWNER' "$T/slack.args" && ! grep -q -- '--mention' "$T/slack.args"; } \
  && ok "--decision from a member-facing session still DMs the owner — a DM already IS rung 1, and the mention would have gone to the members" || bad "--decision leaked into the member channel: $(cat "$T/slack.args")"
# THROWAWAY TEST STATE MUST NEVER PAGE THE OWNER: four days of "[_cctest…] PR #7 merged, deploy stopped" in #alerts
# came from selfchecks whose failures are REAL calls to cc-notify. The gate is here, at the one door every outward
# notification goes through, so it holds for a caller nobody thought to configure. The line is still LOGGED — the
# trail is all a fixture was ever meant to leave.
N "$T/plain" -t "[$REPO] PR #7 merged, deploy stopped" "cc-land: not a git repo"
{ [ ! -s "$T/slack.args" ] && grep -q "$REPO" "$NH/.cc/notify.log"; } \
  && ok "a synthetic repo name (_cctest…/_selfcheck…) is logged and never pushed — a fixture cannot page the owner" \
  || bad "test state reached the owner: $(cat "$T/slack.args")"
N "$T/plain" -t "myrepo_cctesting deploy" "real"
grep -q -- '--route' "$T/slack.args" \
  && ok "…and a real repo that merely contains the word still pages (the gate is anchored, not a substring match)" \
  || bad "real repo swallowed by the synthetic-name gate"
printf 'SLACK_BOT_TOKEN=xoxb-test\n' > "$NH/.cc/config"   # owner not paired
N "$T/chan" "Bob asks for an API key"
{ grep -q -- '-c #alerts' "$T/slack.args" && ! grep -q -- '--route' "$T/slack.args"; } \
  && ok "unpaired owner: the escalation falls back to #alerts, still not the member channel" || bad "unpaired escalation: $(cat "$T/slack.args")"
echo "== --say / --go / cc-loop =="
"$B/cc" $REPO w1 --say hello >/dev/null 2>&1 && bad "--say should fail with no live session" || ok "--say refuses when no session"
tmux new-window -d -t main -n "$REPO/m7" "sleep 30"; sleep 1   # M7: a headless worker's pane is a shell — typed text would run as a command
"$B/cc-msg" "$REPO/m7" "hello" >"$T/m7.out" 2>&1; [ $? != 0 ] && grep -q 'task.md' "$T/m7.out" && ok "cc-msg refuses a window with no interactive claude" || bad "cc-msg typed into a headless pane"
tmux kill-window -t "$(tmux list-windows -t main -F '#{window_id} #W' | awk -v n="$REPO/m7" '$2==n{print $1}')" 2>/dev/null
# M8: a pane with a claude under it AND a dialog on screen. The text, or the Enter after it, would ANSWER the
# dialog, and a tool-permission prompt answered by a script is an unattended approval of what the owner gates on.
# The pane is a copy of bash named `claude` (coreutils refuses to run under another name) with `; true` at every
# level (bash exec-replaces itself on a lone final command, and the process must stay a `claude`).
mkdir -p "$T/fakebin"; cp "$(readlink -f /bin/bash)" "$T/fakebin/claude"
printf 'echo "Do you want to proceed?"\n"%s" -c "sleep 30; true"\ntrue\n' "$T/fakebin/claude" > "$T/m8.sh"
tmux new-window -d -t main -n "$REPO/m8" "bash $T/m8.sh"; sleep 1
"$B/cc-msg" "$REPO/m8" "hello" >"$T/m8.out" 2>&1; m8=$?
{ [ $m8 = 3 ] && grep -q 'dialog' "$T/m8.out"; } && ok "cc-msg refuses a pane with a dialog open — it would answer a permission prompt" || bad "cc-msg typed at a pane with a dialog open (rc=$m8): $(cat "$T/m8.out")"
# M9: the same pane WITHOUT the dialog line — the guard must not be a permanent refusal, and this claude is a
# GRANDCHILD of the pane, the shape `cc-handoff --overlap` starts and the old direct-child test called dead.
printf 'bash -c \x27"%s" -c "sleep 30; true"; true\x27\ntrue\n' "$T/fakebin/claude" > "$T/m9.sh"
tmux new-window -d -t main -n "$REPO/m9" "bash $T/m9.sh"; sleep 1
"$B/cc-msg" "$REPO/m9" "hello" >"$T/m9.out" 2>&1; m9=$?
[ $m9 = 0 ] && ok "cc-msg types at an overlap successor, whose claude is a grandchild of the pane" || bad "cc-msg refused a live session (rc=$m9): $(cat "$T/m9.out")"
for w in m8 m9; do tmux kill-window -t "$(tmux list-windows -t main -F '#{window_id} #W' | awk -v n="$REPO/$w" '$2==n{print $1}')" 2>/dev/null; done
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO/w1$" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
nl0=$(wc -l < "$CC_NOTIFY_LOG" 2>/dev/null || echo 0)
CC_CLAUDE="$T/fakeclaude" "$B/cc" $REPO w1 --go "build the thing" --loop 3 >/dev/null 2>&1
for _ in $(seq 1 40); do grep -q 'STATUS: DONE' ~/.cc/state/$REPO/w1/progress.md 2>/dev/null && grep -qE 'DONE' ~/.cc/state/$REPO/w1/loop.log 2>/dev/null && break; sleep 1; done
grep -q 'STATUS: DONE' ~/.cc/state/$REPO/w1/progress.md 2>/dev/null && ok "loop ran to DONE via journal" || bad "loop DONE"
[ "$(ls ~/.cc/state/$REPO/w1/runs/*.json 2>/dev/null | wc -l)" = 2 ] && ok "loop stopped after DONE (2 iterations, not 3)" || bad "loop iteration count: $(ls ~/.cc/state/$REPO/w1/runs/*.json 2>/dev/null | wc -l)"
rlog=$(git -C "$T/remote.git" log --oneline track/w1 2>/dev/null)   # capture, don't pipe: grep -q exits on the first match, git log takes SIGPIPE and pipefail calls the whole line a failure once the branch has more than a handful of commits
grep -q 'wip: checkpoint' <<<"$rlog" && ok "loop iterations were checkpointed + pushed" || bad "loop checkpoint — remote track/w1: $(head -3 <<<"$rlog" | tr '\n' ' ') | push.err: $(tr '\n' ' ' < ~/.cc/worktrees/$REPO/w1/.cc/push.err 2>/dev/null)"
for _ in $(seq 1 30); do tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -q "$REPO/w1 done" && break; sleep 1; done   # cc-loop writes it from its tmux window, a beat after DONE
tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -q "$REPO/w1 done" && ok "owner notified on DONE (log backend)" || bad "notify"
st=$("$B/cc-board" get $REPO w1 status); [ "$st" = review ] && ok "board -> review after done (PR skipped: no gh remote)" || bad "board status after done: $st"

echo "== --go is a covering note, never a replacement for the brief (#71) =="
# #71 stopped `--go "text"` overwriting task.md — but it then synced the BOARD from that file, so a brief that
# lived ONLY on the board (`cc board add`, the route sp_main tells every planning session to use) was still
# destroyed on both sides. That is how the same bug reached a fourth track on 2026-08-31: a 4590-byte brief
# became one 138-byte sentence, on the board as well as in task.md. These pin every side of it.
# The FIFTH variant is now impossible rather than fixed: there is one authority, $st/task.md, and the board JSON
# carries no copy to reconcile against. So these also pin the absence of that copy, and the one-off migration of
# the copies boards written before this still hold.
godisp(){ "$B/cc" $REPO "$1" --go "$2" >/dev/null 2>&1; sleep 1
  for id in $(wins "$REPO/$1"); do tmux kill-window -t "$id"; done
  for _ in 1 2 3 4 5; do [ -z "$(wins "$REPO/$1")" ] && break; sleep 1; done; }
BRIEF=$(printf 'BRIEF HEAD: the carefully written plan.\n%s\nBRIEF TAIL: the last item.' "$(for i in $(seq 1 60); do echo "brief detail line $i"; done)")

# THE #71 REGRESSION CASE: the brief is on the board and task.md does not exist yet — the exact live shape.
"$B/cc-board" add $REPO g1 "g1" "$BRIEF" >/dev/null
godisp g1 "Work the board brief in full."
tm=~/.cc/state/$REPO/g1/task.md; bi=$("$B/cc-board" get $REPO g1 instructions)
{ grep -q 'BRIEF HEAD' "$tm" && grep -q 'BRIEF TAIL' "$tm" && grep -q 'Work the board brief in full.' "$tm"; } \
  && ok "#71: --go on a board-only brief keeps the WHOLE brief in task.md and adds the note" \
  || bad "#71: task.md is $(wc -c < "$tm" 2>/dev/null) bytes, first line: $(head -1 "$tm" 2>/dev/null)"
{ grep -q 'BRIEF HEAD' <<<"$bi" && grep -q 'BRIEF TAIL' <<<"$bi" && grep -q 'Work the board brief in full.' <<<"$bi"; } \
  && ok "#71: 'cc-board get … instructions' still answers with the whole brief — from the file" \
  || bad "#71: get instructions returned $(wc -c <<<"$bi") bytes"
grep -q 'BRIEF HEAD' ~/.cc/boards/$REPO.json \
  && bad "the board JSON still carries a copy of the brief — there are two authorities again" \
  || ok "the board JSON carries NO copy of the brief: one authority, nothing to reconcile"
[ "$(head -1 "$tm")" = "Work the board brief in full." ] \
  && ok "#71: the --go note sits ABOVE the brief, so the worker reads it first" || bad "note is not line 1: $(head -1 "$tm")"

# Re-dispatch must be idempotent, and `--go ""` must move nothing at all.
b0=$(cat "$tm"); i0=$("$B/cc-board" get $REPO g1 instructions)
godisp g1 "Work the board brief in full."
[ "$(cat "$tm")" = "$b0" ] && ok "re-dispatching with the same note stacks nothing up" || bad "the same note was added twice"
godisp g1 ""
{ [ "$(cat "$tm")" = "$b0" ] && [ "$("$B/cc-board" get $REPO g1 instructions)" = "$i0" ]; } \
  && ok '--go "" re-dispatches and changes neither task.md nor the board' || bad '--go "" moved task.md or the board'

# A board written BEFORE this change still holds the brief in its JSON: the first read moves it, once, and the
# copy is gone afterwards. Without this, every track that existed at the upgrade would have lost its brief.
mkdir -p ~/.cc/state/$REPO/g5
"$B/cc-board" add $REPO g5 "g5" >/dev/null
python3 - "$REPO" <<'MIG'
import json, os, sys
p = os.path.expanduser(f"~/.cc/boards/{sys.argv[1]}.json"); d = json.load(open(p))
d["tracks"]["g5"]["instructions"] = "LEGACY BRIEF: written when the board still held one."
json.dump(d, open(p, "w"), indent=2)
MIG
g5=$("$B/cc-board" get $REPO g5 instructions)
{ [ "$g5" = "LEGACY BRIEF: written when the board still held one." ] \
  && grep -q 'LEGACY BRIEF' ~/.cc/state/$REPO/g5/task.md; } \
  && ok "migration: a pre-#94 board brief is answered with, and moved into, task.md" || bad "migration lost it: $g5"
grep -q 'LEGACY BRIEF' ~/.cc/boards/$REPO.json \
  && bad "migration left the copy in the board JSON" || ok "migration: …and the JSON copy is gone, so it can never come back over the file"
godisp g5 "note after the migration"
{ [ "$(head -1 ~/.cc/state/$REPO/g5/task.md)" = "note after the migration" ] \
  && grep -q 'LEGACY BRIEF' ~/.cc/state/$REPO/g5/task.md; } \
  && ok "migration: a dispatch afterwards adds its note and keeps the migrated brief" || bad "dispatch after migration lost the brief"

# The half #71 did fix: brief in task.md, nothing on the board.
mkdir -p ~/.cc/state/$REPO/g2; printf '%s\n' "$BRIEF" > ~/.cc/state/$REPO/g2/task.md
godisp g2 "the covering note"
tm2=~/.cc/state/$REPO/g2/task.md
{ grep -q 'BRIEF HEAD' "$tm2" && grep -q 'BRIEF TAIL' "$tm2" && [ "$(head -1 "$tm2")" = "the covering note" ]; } \
  && ok "brief in task.md only: the note goes above it and the brief survives" || bad "file-only brief: $(head -1 "$tm2")"

# Both sides hold something different: the dispatch merges, it does not pick one and drop the other.
mkdir -p ~/.cc/state/$REPO/g3; printf 'a line somebody left in the file\n' > ~/.cc/state/$REPO/g3/task.md
"$B/cc-board" add $REPO g3 "g3" "$BRIEF" >/dev/null
godisp g3 "dispatch note"
tm3=~/.cc/state/$REPO/g3/task.md
{ grep -q 'BRIEF HEAD' "$tm3" && grep -q 'a line somebody left in the file' "$tm3" && grep -q 'dispatch note' "$tm3"; } \
  && ok "board brief and a different task.md: both are kept, neither is overwritten" || bad "merge dropped a side: $(wc -c < "$tm3") bytes"

# No brief anywhere: --go still works, and the note becomes the task on both sides.
godisp g4 "just do this one thing"
tm4=~/.cc/state/$REPO/g4/task.md
[ "$(cat "$tm4" 2>/dev/null)" = "just do this one thing" ] \
  && ok "--go on a track with no brief still works (the note becomes the task)" || bad "no-brief task.md: $(cat "$tm4" 2>/dev/null)"
[ "$("$B/cc-board" get $REPO g4 instructions)" = "just do this one thing" ] \
  && ok "--go on a track with no brief: the note IS the brief, and the board reads it back" || bad "no-brief board: $("$B/cc-board" get $REPO g4 instructions)"
# `cc board add` must never eat a brief that is already there — the failure mode all of the above exists for.
"$B/cc-board" add $REPO g4 "g4" "a different brief entirely" >/dev/null 2>&1
{ grep -q 'just do this one thing' "$tm4" && grep -q 'a different brief entirely' "$tm4"; } \
  && ok "cc-board add APPENDS to an existing brief, it never overwrites one" || bad "add clobbered task.md: $(cat "$tm4")"
"$B/cc-board" set $REPO g4 instructions "an explicitly replaced brief" >/dev/null
[ "$(cat "$tm4")" = "an explicitly replaced brief" ] \
  && ok "…and 'cc-board set … instructions' is the explicit way to replace one" || bad "set instructions: $(cat "$tm4")"

echo "== a finished track leaves the default board view (a13) =="
# owner, 2026-08-30: "this should also remove it from the board". Filter at render — no archive file to drift.
# A row stays for cc-board's SHOWN_FOR window after it finishes so the owner sees WHAT landed; then it is history,
# and `--all` still prints it. Backdating `updated` is how the window is crossed without waiting two hours.
"$B/cc-board" add $REPO m1 "m1 landed" >/dev/null; "$B/cc-board" status $REPO m1 merged >/dev/null
"$B/cc-board" show $REPO | grep -q 'm1 landed' \
  && ok "a13: a just-merged track is still on the board, so the owner sees what landed" || bad "a13: it vanished immediately"
python3 - "$REPO" <<'BACK'
import json, os, sys
p = os.path.expanduser(f"~/.cc/boards/{sys.argv[1]}.json"); d = json.load(open(p))
d["tracks"]["m1"]["updated"] = "2000-01-01T00:00:00Z"
json.dump(d, open(p, "w"), indent=2)
BACK
"$B/cc-board" show $REPO | grep -q 'm1 landed' \
  && bad "a13: a merged track is still on the default board after its window" \
  || ok "a13: past its window, a merged track is gone from the default 'cc board show'"
"$B/cc-board" show $REPO --all | grep -q 'm1 landed' \
  && ok "a13: --all still prints it — the history is filtered, never deleted" || bad "a13: --all lost it"
"$B/cc-board" show $REPO | grep -q 'finished' \
  && ok "a13: the default view SAYS it hid something, so nobody wonders where it went" || bad "a13: the view hid a row silently"
"$B/cc-board" show $REPO | grep -q 'g1' \
  && ok "a13: an unfinished track is untouched by the filter" || bad "a13: the filter dropped a live track"
o=$("$B/cc-board" selfcheck 2>&1); grep -q ': 0 failed' <<<"$o" \
  && ok "cc-board selfcheck: 0 failed" || { bad "cc-board selfcheck"; echo "$o" | grep FAIL | head -5; }
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
# P6: THE 2026-08-31 CASE END TO END — the track rebased its own branch before finishing. The plain push died
# non-fast-forward, so `cc done` opened no PR and the work sat on the branch until the watchdog found it.
( cd ~/.cc/worktrees/$REPO/w5 && git commit -q --amend -m "rebased before finishing" )
echo "work that must not be stranded" > ~/.cc/worktrees/$REPO/w5/late.txt
PATH="$T/ghbin:$PATH" "$B/cc" done $REPO w5 > "$T/done6.out" 2>&1; rc6=$?
{ [ "$rc6" = 0 ] && [ "$(wc -l < "$T/gh.create")" = 3 ] \
  && [ "$(git -C "$T/remote.git" rev-parse track/w5)" = "$(git -C ~/.cc/worktrees/$REPO/w5 rev-parse HEAD)" ]; } \
  && ok "cc done: a track that rebased its own branch still pushes it and still gets a PR (P6)" \
  || bad "rebase-then-done stranded the work: rc=$rc6 creates=$(wc -l < "$T/gh.create") $(cat "$T/done6.out")"
# P7: and the other way — a foreign write on that branch stops `cc done` dead. No PR over the top of somebody else.
( cd "$T" && git clone -q "$T/remote.git" foreign5 2>/dev/null && cd foreign5 && git config user.email o@o && git config user.name o \
  && git checkout -q track/w5 && echo not-ours > z.txt && git add -A && git commit -qm "a write w5 did not make" && git push -q origin track/w5 )
fw5=$(git -C "$T/remote.git" rev-parse track/w5)
( cd ~/.cc/worktrees/$REPO/w5 && git commit -q --amend -m "diverged too" )
PATH="$T/ghbin:$PATH" "$B/cc" done $REPO w5 > "$T/done7.out" 2>&1; rc7=$?
{ [ "$rc7" != 0 ] && [ "$(wc -l < "$T/gh.create")" = 3 ] && [ "$(git -C "$T/remote.git" rev-parse track/w5)" = "$fw5" ] \
  && grep -q 'no PR opened' "$T/done7.out" && grep -q '^STATUS: BLOCKED: push refused' ~/.cc/state/$REPO/w5/progress.md; } \
  && ok "cc done: a foreign write on the branch opens no PR, overwrites nothing, and says why (P7)" \
  || bad "cc done over a foreign write: rc=$rc7 creates=$(wc -l < "$T/gh.create") $(cat "$T/done7.out")"
rm -rf "$T/foreign5"
# M6: is_error=true with subtype error_max_* and real output is a CAP, not a failure — the loop must keep going
"$B/cc" $REPO w2 >/dev/null 2>&1; sleep 1
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO/w2$" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
echo "do capped work" > ~/.cc/state/$REPO/w2/task.md
CC_CLAUDE="$T/cappedclaude" "$B/cc-loop" $REPO w2 --max-iter 3 --quiet >/dev/null 2>&1; rc=$?
runs=$(ls ~/.cc/state/$REPO/w2/runs/*.json 2>/dev/null | wc -l)
{ [ "$rc" != 5 ] && [ "$runs" -gt 3 ]; } && ok "productive but capped iterations are not failures — the loop ran past its 3-step limit ($runs runs, not exit 5)" || bad "capped loop: rc=$rc runs=$runs"
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
echo "== the step limit carries on, and a runaway does not (cc-loop) =="
# Every stub here is the same shape: it decides per iteration whether to COMMIT (a file in the worktree),
# whether to JOURNAL, and what it cost. That pair is the whole runaway rule, and the money is never the reason.
mkclaude(){ cat > "$T/$1" <<F
#!/usr/bin/env bash
st=$HOME/.cc/state/$REPO/$2; n=\$(ls \$st/runs/*.json 2>/dev/null | wc -l)   # cc-loop opens THIS run's json before it starts us: n is 1 on the first iteration
$3
printf '{"is_error":%s,"num_turns":2,"total_cost_usd":%s,"session_id":"x","result":"%s"}' "\${err:-false}" "\${cost:-0.5}" "\${res:-ok \$n}"
F
chmod +x "$T/$1"; }
mktrack(){ "$B/cc" $REPO "$1" >/dev/null 2>&1; sleep 1; for id in $(wins "$REPO/$1"); do tmux kill-window -t "$id"; done; echo "$2" > ~/.cc/state/$REPO/$1/task.md; }
lg(){ cat ~/.cc/state/$REPO/$1/loop.log; }
nruns(){ ls ~/.cc/state/$REPO/$1/runs/*.json 2>/dev/null | wc -l; }

# 1+2: three iterations in a row with nothing to show stop the loop, and the owner hears once, not three times
mktrack w8 "spin forever"; mkclaude spinclaude w8 ':'   # commits nothing, journals nothing, ever
nl0=$(wc -l < "$CC_NOTIFY_LOG" 2>/dev/null || echo 0)
CC_CLAUDE="$T/spinclaude" "$B/cc-loop" $REPO w8 --max-iter 20 --quiet >/dev/null 2>&1; rc=$?
{ [ "$rc" = 9 ] && [ "$(nruns w8)" = 3 ]; } && ok "three progress-free iterations stop the loop (exit 9 after 3, not 20)" || bad "runaway: rc=$rc runs=$(nruns w8)"
lg w8 | grep -q 'runaway signal 3/3' && [ "$("$B/cc-board" get $REPO w8 status)" = blocked ] && ok "…the reason is in the log and the board says blocked — a state a person must settle" || bad "runaway log/board: $(lg w8 | tail -2)"
n=$(tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -c "w8 is running away")
[ "$n" = 1 ] && ok "…and the owner is told once, with the numbers — not once per barren iteration" || bad "runaway notify count: $n"

# 3: an expensive job that keeps producing is never touched. $50 an iteration, and no cap anywhere.
mktrack w9 "expensive but productive"
mkclaude richclaude w9 'cost=50; echo "work $n" > "rich-$n.txt"; echo "- did step $n" >> "$st/progress.md"; [ "$n" -ge 2 ] && echo "STATUS: DONE" >> "$st/progress.md"'
CC_CLAUDE="$T/richclaude" "$B/cc-loop" $REPO w9 --max-iter 3 --quiet >/dev/null 2>&1; rc=$?
{ [ "$rc" = 0 ] && ! lg w9 | grep -q 'runaway signal'; } && ok "an expensive job that keeps committing runs untouched (\$100, no cap, no signal)" || bad "expensive job flagged: rc=$rc $(lg w9 | grep runaway | head -1)"

# 4+5: the step limit carries on when that iteration COMMITTED, and stops when it did not
mktrack w10 "carry on once"
mkclaude carryclaude w10 'if [ "$n" -lt 2 ]; then echo "work $n" > "carry-$n.txt"; fi; echo "- step $n" >> "$st/progress.md"'
CC_CLAUDE="$T/carryclaude" "$B/cc-loop" $REPO w10 --max-iter 1 --quiet >/dev/null 2>&1; rc=$?
{ [ "$(nruns w10)" = 2 ] && [ "$(lg w10 | grep -c 'carrying on')" = 1 ]; } && ok "the step limit is a checkpoint: an iteration that committed buys another batch" || bad "carry-on: runs=$(nruns w10) carried=$(lg w10 | grep -c 'carrying on')"
{ [ "$rc" = 6 ] && lg w10 | grep -q 'committed nothing, so it did not carry itself on'; } && ok "…and an iteration that committed nothing does not — the loop stops at exit 6" || bad "step limit without commits: rc=$rc"

# 6: neither a question for a person nor a run of errors is ever carried on
mktrack w11 "ask something"
mkclaude askclaude w11 'echo "work $n" > "ask-$n.txt"; echo "- step $n" >> "$st/progress.md"; echo "STATUS: BLOCKED: which schema?" >> "$st/progress.md"'
CC_CLAUDE="$T/askclaude" "$B/cc-loop" $REPO w11 --max-iter 1 --quiet >/dev/null 2>&1; rc=$?
{ [ "$rc" = 3 ] && [ "$(nruns w11)" = 1 ] && ! lg w11 | grep -q 'carrying on'; } && ok "STATUS: BLOCKED is never carried on — it is a question, even with work committed" || bad "blocked carried on: rc=$rc runs=$(nruns w11)"
# …and the word it leaves is `waiting`, not `blocked`: the loop is the first to know a person is being asked, and it
# must write what cc-reconcile and the Home tab already read out of that same journal line, or the tab prints drift.
[ "$("$B/cc-board" get $REPO w11 status)" = waiting ] && ok "…and the board says \`waiting\`, the one word that reaches the owner's NEEDS YOU list — not \`blocked\`, which is every other way a loop stops" || bad "exit 3 board status: $("$B/cc-board" get $REPO w11 status)"
mktrack w12 "fail every time"
mkclaude failclaude w12 'err=true; res="fatal: it broke"'
CC_CLAUDE="$T/failclaude" "$B/cc-loop" $REPO w12 --max-iter 5 --quiet >/dev/null 2>&1; rc=$?
{ [ "$rc" = 5 ] && [ "$(nruns w12)" = 2 ] && ! lg w12 | grep -q 'carrying on'; } && ok "an error is never carried on either — two in a row and it stops (exit 5)" || bad "error carried on: rc=$rc runs=$(nruns w12)"
# 7+8: what the loop does OUTSIDE the worker's process (sandbox stage 1a, review of #129). A sandboxed worker's Stop hook
# commits but cannot push (no credential inside), so the loop pushes whatever is ahead of origin — even with nothing
# left to commit. And the hooks that loop-side git runs come from the MAIN checkout, never the worktree the worker edits.
mktrack w13 "commit inside, push from outside"
mkclaude insideclaude w13 'echo "committed inside $n" > "inside-$n.txt"; git add -A && git commit -qm "inside, unpushed"; echo "- step $n" >> "$st/progress.md"; echo "STATUS: BLOCKED: q" >> "$st/progress.md"'
CC_CLAUDE="$T/insideclaude" "$B/cc-loop" $REPO w13 --max-iter 1 --quiet >/dev/null 2>&1; rc=$?
{ [ "$rc" = 3 ] && [ -n "$(git -C "$T/remote.git" rev-parse -q --verify track/w13)" ] && [ "$(git -C "$T/remote.git" rev-parse -q --verify track/w13)" = "$(git -C ~/.cc/worktrees/$REPO/w13 rev-parse HEAD)" ]; } \
  && ok "a commit the worker made itself reaches origin from outside the loop's checkpoint, with nothing left to commit (a sandboxed Stop hook cannot push)" \
  || bad "inside commit never pushed: rc=$rc remote=$(git -C "$T/remote.git" rev-parse -q --verify track/w13) local=$(git -C ~/.cc/worktrees/$REPO/w13 rev-parse HEAD)"
mktrack w14 "write a hook"; st14=~/.cc/state/$REPO/w14
git -C ~/dev/$REPO config core.hooksPath hooks   # relative, like a repo that tracks its hooks (core/.githooks): git resolves it against whichever worktree it runs in
mkdir -p ~/dev/$REPO/hooks; printf '#!/bin/sh\ntouch %s/hook-main\n' "$st14" > ~/dev/$REPO/hooks/pre-commit; chmod +x ~/dev/$REPO/hooks/pre-commit
mkclaude hookclaude w14 'mkdir -p hooks; printf "#!/bin/sh\ntouch $st/hook-wt\n" > hooks/pre-commit; chmod +x hooks/pre-commit; echo "- step $n" >> "$st/progress.md"; echo "STATUS: BLOCKED: q" >> "$st/progress.md"'
CC_CLAUDE="$T/hookclaude" "$B/cc-loop" $REPO w14 --max-iter 1 --quiet >/dev/null 2>&1; rc=$?
{ git -C ~/.cc/worktrees/$REPO/w14 log -1 --format=%s | grep -q '^wip: checkpoint' && [ -e "$st14/hook-main" ] && [ ! -e "$st14/hook-wt" ]; } \
  && ok "loop-side git (the checkpoint) runs the MAIN checkout's hooks, never the one the worker just wrote into its worktree" \
  || bad "host ran the worktree's hook: rc=$rc main=$([ -e "$st14/hook-main" ] && echo ran || echo no) wt=$([ -e "$st14/hook-wt" ] && echo RAN || echo no) last=$(git -C ~/.cc/worktrees/$REPO/w14 log -1 --format=%s)"
git -C ~/dev/$REPO config --unset core.hooksPath; rm -f ~/dev/$REPO/hooks/pre-commit; rmdir ~/dev/$REPO/hooks
for t in w8 w9 w10 w11 w12 w13 w14; do "$B/cc" rm $REPO $t >/dev/null 2>&1; done

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

echo "== ccbox: a new box's ~/.claude gets the login and nothing else =="
# The seed runs in a throwaway container (no docker here), so the snippet itself runs on stub files: the newest
# credentials win, .claude.json keeps oauthAccount only (never project history), nothing to copy writes nothing.
S=$T/seed; mkdir -p "$S/src/ccbox-claude" "$S/src/ccbox-claude-old" "$S/dst"
snip=$(grep -o "'D=/home/node/.claude;.*rm -f \$D/.claude.json'" "$B/ccbox" | sed "s|^'||; s|'\$||; s|/home/node/.claude|$S/dst|g; s|/src/|$S/src/|g")
[ -n "$snip" ] && ok "ccbox carries the seed snippet" || bad "seed snippet not found in ccbox"
echo '{"t":"old"}' > "$S/src/ccbox-claude-old/.credentials.json"; touch -d '2 days ago' "$S/src/ccbox-claude-old/.credentials.json"
echo '{"t":"new"}' > "$S/src/ccbox-claude/.credentials.json"; chmod 600 "$S/src/ccbox-claude/.credentials.json"
echo '{"oauthAccount":{"e":"a@b"},"projects":{"/workspace/x":{"history":["prompt"]}},"theme":"dark"}' > "$S/src/ccbox-claude/.claude.json"
sh -c "$snip"
[ "$(cat "$S/dst/.credentials.json" 2>/dev/null)" = '{"t":"new"}' ] && [ "$(stat -c %a "$S/dst/.credentials.json")" = 600 ] \
  && ok "the newest credentials are copied, mode kept" || bad "seed: $(ls -la "$S/dst")"
[ "$(jq -c . "$S/dst/.claude.json" 2>/dev/null)" = '{"oauthAccount":{"e":"a@b"}}' ] \
  && ok ".claude.json keeps oauthAccount only — no project history" || bad "seed .claude.json: $(cat "$S/dst/.claude.json" 2>/dev/null)"
rm -f "$S/dst"/.claude.json "$S/dst"/.credentials.json; echo '{"theme":"dark"}' > "$S/src/ccbox-claude/.claude.json"; sh -c "$snip"
[ -f "$S/dst/.credentials.json" ] && [ ! -e "$S/dst/.claude.json" ] \
  && ok "no oauthAccount → no .claude.json (the entrypoint makes its own)" || bad "seed without oauthAccount: $(ls -A "$S/dst")"
rm -f "$S/dst"/.credentials.json "$S"/src/*/.credentials.json; sh -c "$snip"; rc=$?
[ "$rc" = 0 ] && [ -z "$(ls -A "$S/dst")" ] && ok "nothing to copy → nothing written, exit 0" || bad "seed with no source: rc=$rc $(ls -A "$S/dst")"

echo "== ccbox: a headless --cmd, and the seed helper's image (docker stubbed) =="
# A docker stub records every call and plays a box whose project image exists, whose ~/.claude volume does not and
# whose command prints a line and exits 3 — the two things review-139 caught: the seed copy must run in the BASE
# image (every box's login is mounted into it, and a project image comes from a Dockerfile its own agent can write),
# and a --cmd run with no TTY must hand back the command's output and exit status instead of "did not come up".
X=$T/ccbox; mkdir -p "$X/bin" "$X/home/dev" "$X/cfg"; : > "$X/cfg/env"; : > "$X/cfg/allowed-domains"
printf '#!/bin/sh\necho docker\n' > "$X/bin/id"   # ccbox's d() calls plain docker when the user is in the docker group
cat > "$X/bin/docker" <<EOF
#!/bin/sh
printf '%s\n' "\$*" >> "$X/calls"
case "\$1 \$2" in
  "image inspect") case "\$3" in ccbox:latest|ccbox-proj:latest) exit 0 ;; *) exit 1 ;; esac ;;   # base AND project image exist
  "inspect --type") echo false ;;    # the container is not running
  "volume inspect") exit 1 ;;        # a NEW box
  "volume ls") echo ccbox-claude ;;  # one volume to seed from
  "logs -f") printf 'Firewall configuration complete\nhi from the box\n' ;;
  "wait ccbox-proj") echo 3 ;;
esac
EOF
chmod +x "$X/bin/docker" "$X/bin/id"
out=$(PATH="$X/bin:$PATH" HOME=$X/home CCBOX_CFG=$X/cfg "$B/ccbox" proj --cmd 'echo hi' 2>&1 </dev/null); rc=$?
[ "$rc" = 3 ] && grep -q 'hi from the box' <<<"$out" && ok "a no-TTY --cmd prints the command's output and exits with its status (3)" || bad "headless --cmd: rc=$rc out=$out"
seed=$(grep '^run --rm ' "$X/calls"); start=$(grep '^run -d ' "$X/calls")
grep -q ' ccbox:latest -c ' <<<"$seed" && ! grep -q 'ccbox-proj:latest' <<<"$seed" && grep -q ' ccbox-proj:latest$' <<<"$start" && grep -q 'CCBOX_TTY=0' <<<"$start" \
  && ok "the seed copy runs in the base image while the box runs its project image; CCBOX_TTY=0 passed in" || bad "seed: $seed / start: $start"

echo "== cc-trust prune (recorded trust vs real dirs) =="
TH=$T/trusthome; mkdir -p "$TH/real-dir"
printf '{"projects":{"%s":{"hasTrustDialogAccepted":true},"/gone/nowhere-%s":{"hasTrustDialogAccepted":true}}}' "$TH/real-dir" "$$" > "$TH/.claude.json"
HOME=$TH "$B/cc-trust" prune >/dev/null
jq -e --arg d "$TH/real-dir" '.projects[$d]' "$TH/.claude.json" >/dev/null && [ "$(jq '.projects | length' "$TH/.claude.json")" = 1 ] \
  && ok "prune drops the gone dir and keeps the living one" || bad "prune: $(cat "$TH/.claude.json")"

echo "== cc-reconcile (board vs reality: decision table + one end-to-end apply, no network) =="
rec=$("$B/cc-reconcile" selfcheck 2>&1)
grep -q '0 failed' <<<"$rec" && ok "cc-reconcile selfcheck: ${rec##*: }" || bad "cc-reconcile selfcheck: $rec"

echo "== cc-janitor (the weekly sweep: decision table + one end-to-end pass over a fake box) =="
# Its own HOME, board, origin and stub tmux/gh — nothing here can reach this box's tmux server or GitHub.
jan=$("$B/cc-janitor" selfcheck 2>&1)
grep -q '0 failed' <<<"$jan" && ok "cc-janitor selfcheck: ${jan##*: }" || bad "cc-janitor selfcheck: $jan"

echo "== cc-pulse (the drive loop: whole-machine enumeration, start, tick, and the three reasons not to) =="
# Its own HOME with two boards and one orch, and stub tmux/cc/cc-msg/cc-handoff — it starts no session
# on this box and types into none of the live ones.
pul=$("$B/cc-pulse" selfcheck 2>&1)
grep -q '0 failed' <<<"$pul" && ok "cc-pulse selfcheck: ${pul##*: }" || bad "cc-pulse selfcheck: $pul"

echo "== cc-secretary (the judgment layer: fixtures, a fake model, the whole escalation ladder, no network) =="
# Its own HOME, stub tmux/ps/claude/cc-slack/cc-notify — it reads no pane and reaches no session on this box.
secr=$("$B/cc-secretary" selfcheck 2>&1)
grep -q '0 failed' <<<"$secr" && ok "cc-secretary selfcheck: ${secr##*: }" || bad "cc-secretary selfcheck: $secr"

echo "== what the snapshot's four readers do with it (waiting vs the clock, and without it) =="
# cc-reconcile's own selfcheck covers PRODUCING the snapshot; this covers the two things that only break in the
# readers. Its own HOME, because ~/.cc/state/reconcile.json is a fixed path and this box's live one must not move.
SH=$T/snaphome; mkdir -p "$SH/.cc/state" "$SH/dev/sr"
sb(){ HOME=$SH "$B/cc-board" "$@"; }
sb init sr "$SH/dev/sr" main >/dev/null; for t in s_ask s_clock s_stop; do sb add sr $t "title $t" "" >/dev/null; done
sb status sr s_ask waiting >/dev/null; sb status sr s_clock running >/dev/null; sb status sr s_stop blocked >/dev/null
# NO snapshot yet: every key a reader looks up is unset. `cc ls` runs under `set -u`, and a missing default there
# killed the whole listing rather than one column — a stale timer must never cost the owner his board.
lsn=$(HOME=$SH "$B/cc" ls 2>&1); lsrc=$?
[ $lsrc = 0 ] && grep -q 's_ask' <<<"$lsn" && ok "no snapshot: \`cc ls\` still prints every track (a missing key must not kill the listing)" || bad "cc ls without a snapshot: rc=$lsrc"
grep -q '❓' <<<"$lsn" && ok "no snapshot: a waiting track is still marked, with no question to show" || bad "cc ls dropped the waiting mark"
dgn=$(HOME=$SH "$B/cc-digest" 2>/dev/null)
dga=$(grep s_ask <<<"$dgn")
grep -q '❓ needs you' <<<"$dga" && ! grep -q 'needs you:' <<<"$dga" && ok "no snapshot: the digest still says he is needed, with no colon trailing a question it does not have" || bad "digest fallback wording: $dga"
# an EMPTY or non-JSON snapshot must read as stale, not kill the reader: jq on empty input exits 0 with no
# output at all, and `$(( now - ))` is a bash abort — this guard exists precisely for the file the writer got wrong.
: > "$SH/.cc/state/reconcile.json"
lse=$(HOME=$SH "$B/cc" ls 2>&1); lserc=$?
[ $lserc = 0 ] && grep -q 's_ask' <<<"$lse" && ok "empty snapshot: \`cc ls\` treats it as stale and still prints the board" || bad "empty snapshot killed cc ls: rc=$lserc — $lse"
printf 'not json' > "$SH/.cc/state/reconcile.json"
dge=$(HOME=$SH "$B/cc-digest" 2>/dev/null); dgerc=$?
[ $dgerc = 0 ] && grep -q 's_ask' <<<"$dge" && ok "corrupt snapshot: the digest falls back to the board" || bad "corrupt snapshot broke the digest: rc=$dgerc"
# the snapshot cc-reconcile leaves behind — a question a PERSON must answer, and a loop waiting on the CLOCK while
# its board word is still `running` (it hit the limit mid-run). The clock is never "needs you".
cat > "$SH/.cc/state/reconcile.json" <<JSON
{"at":"now","epoch":$(date -u +%s),"limit_until":0,"tracks":{
 "sr/s_ask":{"state":"waiting","board":"waiting","live":true,"waiting_on":"person","why":"which syllabus?"},
 "sr/s_clock":{"state":"running","board":"running","live":true,"waiting_on":"clock","why":"a Claude usage limit"},
 "sr/s_stop":{"state":"blocked","board":"blocked","live":false,"waiting_on":"","why":""}}}
JSON
lss=$(HOME=$SH "$B/cc" ls 2>&1); dgs=$(HOME=$SH "$B/cc-digest" 2>/dev/null)
grep -q 'which syllabus?' <<<"$lss" && grep -q 'which syllabus?' <<<"$dgs" && ok "snapshot: \`cc ls\` and the digest print the same question, from the one file" || bad "the question did not reach both readers"
grep -q '⏳ held by the usage limit' <<<"$(grep s_clock <<<"$lss")" && grep -q '⏳ held by the usage limit' <<<"$(grep s_clock <<<"$dgs")" && ok "snapshot: a loop held by the limit says so in both — whatever word it wears (\`running\` here, not \`blocked\`)" || bad "clock row invisible while the board says running"
! grep -q 'needs you' <<<"$(grep s_clock <<<"$dgs")" && ok "snapshot: the clock is NOT on his list — there is nothing for him to answer" || bad "a usage limit was reported as needing the owner"
grep -q '⛔ stopped' <<<"$(grep s_stop <<<"$dgs")" && ! grep -q 'needs you' <<<"$(grep s_stop <<<"$dgs")" && ok "snapshot: a track that merely stopped reads as stopped, not as a question" || bad "a stopped track was filed as needing him"
rm -rf "$SH"

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
echo "== install.sh on a blank HOME (the bare-clone bootstrap) =="
# THIS tree, copied as a bare autobox clone (a dir not named core/ has no overlay), installed into an empty HOME with
# --no-services: nothing enabled or started, no privileges, nothing of this box's touched. ccbox/env is a token file
# and stays behind. The fixtures ($T) go with the run's EXIT trap.
IR="$T/autobox"; IH="$T/blank"; mkdir -p "$IR" "$IH"
tar -C "$B/.." --exclude=./ccbox/env --exclude=__pycache__ -cf - . | tar -C "$IR" -xf -
inst(){ ( cd "$IH" && env HOME="$IH" USER=tester CC_BOX=testbox GIT_CEILING_DIRECTORIES="$T" "$IR/install.sh" --no-services ) >"$T/install.log" 2>&1; }
inst && ok "install.sh runs clean on a blank HOME (--no-services)" || bad "install.sh failed on a blank HOME: $(tail -3 "$T/install.log" | tr '\n' ' ')"
[ "$(readlink -f "$IH/bin/cc")" = "$IR/bin/cc" ] && [ "$(readlink -f "$IH/bin/cc-pulse")" = "$IR/bin/cc-pulse" ] && ok "bin/* linked into ~/bin from the installed tree" || bad "~/bin links missing or pointing elsewhere"
# the prune is scoped to what this tree linked: a stale link of its own (target left the tree) goes, a dangling
# link someone ELSE put in ~/bin stays — install.sh used to delete every dangling link in ~/bin, whoever made it
ln -s "$IR/bin/retired-script" "$IH/bin/retired-script"; ln -s "$T/never-ours" "$IH/bin/foreign"
inst
[ ! -L "$IH/bin/retired-script" ] && [ -L "$IH/bin/foreign" ] && ok "prune removes only this tree's stale ~/bin links — a foreign dangling link is left alone" || bad "prune scope: retired link $([ -L "$IH/bin/retired-script" ] && echo kept || echo gone), foreign link $([ -L "$IH/bin/foreign" ] && echo kept || echo gone)"
rm -f "$IH/bin/foreign"
miss=""; for u in $("$IR/bin/cc-units" link); do [ -L "$IH/.config/systemd/user/$u" ] || miss="$miss $u"; done
[ -z "$miss" ] && ok "every unit in the manifest is linked, cc-pulse.timer included (switching on is the services step)" || bad "units not linked:$miss"
{ [ -f "$IH/CLAUDE.md" ] && [ ! -L "$IH/CLAUDE.md" ] && grep -q '^# testbox — ' "$IH/CLAUDE.md" && grep -q 'Autonomy is the norm' "$IH/CLAUDE.md" && grep -q 'The owner approves' "$IH/CLAUDE.md" && grep -q '~/WORKING.md' "$IH/CLAUDE.md" && ! grep -q '<user>' "$IH/CLAUDE.md"; } && ok "~/CLAUDE.md seeded as a copy of the contract, <box>/<user> filled in, the rest left to the owner" || bad "~/CLAUDE.md not seeded as the box contract"
miss=""; for g in USAGE COMMS RUNBOOK SLACK; do [ -f "$IH/$g.md" ] || miss="$miss $g"; done
[ -z "$miss" ] && ok "the guides the contract points at exist at ~ (USAGE COMMS RUNBOOK SLACK)" || bad "guides missing:$miss"
[ "$(readlink -f "$IH/WORKING.md")" = "$IR/docs/WORKING.md" ] && ok "~/WORKING.md links to the tree's docs/WORKING.md" || bad "~/WORKING.md not linked"
[ -f "$IH/.claude/settings.json" ] && env HOME="$IH" CC_SETTINGS_FILE="$IH/.claude/settings.json" "$IR/bin/cc-settings" check >/dev/null 2>&1 && ok "default ~/.claude/settings.json installed and satisfies the managed subset" || bad "settings.json missing or drifted from claude-managed.json"
# the second run is the deploy path (every landing re-runs install.sh): it must change nothing, and an existing
# ~/CLAUDE.md — here the owner's own — is never rewritten
echo "# mine" > "$IH/CLAUDE.md"
snap(){ ( cd "$IH" && { find . -printf '%P %y %l\n' | sort; find . -type f -exec md5sum {} + | sort; } | md5sum ); }
s1=$(snap); inst; s2=$(snap)
[ "$s1" = "$s2" ] && ok "a second install.sh run changes nothing (idempotent — the deploy path)" || bad "the second install.sh run changed the HOME"
[ "$(cat "$IH/CLAUDE.md")" = "# mine" ] && ok "an existing ~/CLAUDE.md is never rewritten" || bad "install.sh overwrote ~/CLAUDE.md"
[ "$(grep -c 'autobox PATH' "$IH/.bashrc")" = 1 ] && ok "~/.bashrc gets the PATH block once" || bad "PATH block appended more than once"
echo "== ask ledger (cc-scope) =="
# The ledger has no fixtures to build: its selfcheck works in a temp dir of its own and removes it on the way out.
sc=$("$B/cc-scope" selfcheck 2>&1)
grep -q "0 failed" <<<"$sc" && ok "cc-scope selfcheck: $(tail -1 <<<"$sc")" || bad "cc-scope selfcheck: $(tail -1 <<<"$sc")"
echo "== landing (cc-land) =="
# Its decision table only: the real thing merges, installs and starts services, so every call it would make to
# the world is stood in for. Nothing here reaches git, Slack, systemd or the board.
sc=$("$B/cc-land" selfcheck 2>&1)
grep -q "cc-land selfcheck: 0 failed" <<<"$sc" && ok "$(tail -1 <<<"$sc")" || bad "$(tail -1 <<<"$sc")"
echo "== cc-audit: the second opinion on what to delete (codex) =="
# No fixtures: `cc-audit selfcheck` stubs codex logged-out/answering/crashing/silent in a temp dir of its own and
# removes it. It exits before checks() runs, so calling it from here does NOT recurse back into this file.
sc=$("$B/cc-audit" selfcheck 2>&1)
grep -q "0 failed" <<<"$sc" && ok "cc-audit selfcheck: $(tail -1 <<<"$sc")" || bad "cc-audit selfcheck: $(tail -1 <<<"$sc")"
echo "== the suite's own lock (one run at a time) =="
# Re-runs THIS FILE, stopping at the lock ($CC_SELFTEST_LOCK_ONLY) — no fixtures, no tmux, no repo, so the suite
# never runs inside itself. On a lock of its own ($CC_SELFTEST_LOCK): the real one is held by the very run doing
# the testing, and opening it a second time from here would deadlock this run against nobody but itself. Nothing
# waits on a clock — the holder holds until a flag file appears, and the waiter is watched for the line it prints
# — so a loaded box makes this case slower, never red, and it costs the suite a fraction of a second either way.
L="$T/lock"
( exec 8>>"$L"; flock 8; : >"$L"; echo $BASHPID >&8; for _ in $(seq 1 600); do [ -e "$L.go" ] && break; sleep 0.1; done ) &
hp=$!; KIDS="$KIDS $hp"
for _ in $(seq 1 100); do [ -s "$L" ] && break; sleep 0.1; done   # the stand-in holder has it, and has named itself
env CC_SELFTEST_LOCK="$L" CC_SELFTEST_LOCK_ONLY=1 CC_SELFTEST_LOCK_ORPHAN=1 "$SELF" >"$T/lock.out" 2>&1 & cp=$!; KIDS="$KIDS $cp"
for _ in $(seq 1 300); do grep -q '^== waiting:' "$T/lock.out" 2>/dev/null && break; sleep 0.1; done
{ grep -q "is held by pid $hp ==" "$T/lock.out" && kill -0 $cp 2>/dev/null; } \
  && ok "a second run names the pid holding the lock — and is still sitting on it, not failing past it" \
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
cd ~ || exit 1
# cleanup: windows, the scratch tmux server, every fixture process, $T, the repo dirs and ~/.claude.json — the EXIT
# trap does it on every path out, including a kill, so nothing this run started can outlive it
echo "== result: $pass passed, $fail failed =="; [ $fail = 0 ]
