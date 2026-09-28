#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# step-limit.sh — the stanza "the step limit carries on, and a runaway does not (cc-loop)", run alone on the fixtures it stands on.
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
if stanza "the step limit carries on, and a runaway does not (cc-loop)"; then
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
n=$(tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep "w8 is running away" | grep -vc "rung=P")
[ "$n" = 0 ] && ok "…and nothing goes to the owner: the stop is the planning seat's request, below, and the numbers stay in the log" || bad "runaway notify count: $n"
# …and a stop NO seat took is also a planner request (cc-notify --ask: kept on file and retried, never dropped and never
# his alone to catch) — one, under the stop's own id; this fixture's repo is synthetic, so it is logged and not asked.
nq=$(tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep "w8 is running away" | grep -c "rung=P kind=request")
[ "$nq" = 1 ] && ok "…and the stop nobody heard is filed once as a planner request beside that line, not dumped on the owner alone" || bad "stop request count: $nq"

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
# 6b: --no-extend — the bound cc-land's fix round asks for, and a plain `cc` flag besides (core/bin/cc:407). A
# round that ends AT its bound having COMMITTED is over, not stalled: exit 0, no page, and the owner never reads
# "the last one committed nothing" about a round that just pushed. The board word claims a review only where a PR
# exists to carry it — cc-reconcile reads a `review` row with no PR as "it is waiting on a PR that was never
# opened" and files that at the owner every 20 minutes, which is the class of false finding this change closes.
mktrack w14 "one bounded round, with a PR"
mkclaude boundclaude w14 'echo "work $n" > "bound-$n.txt"; echo "- step $n" >> "$st/progress.md"'
"$B/cc-board" set $REPO w14 pr "https://example.invalid/pr/1" >/dev/null 2>&1
nlb=$(wc -l < "$CC_NOTIFY_LOG" 2>/dev/null || echo 0)
CC_CLAUDE="$T/boundclaude" "$B/cc-loop" $REPO w14 --max-iter 1 --no-extend --quiet >/dev/null 2>&1; rc=$?
{ [ "$rc" = 0 ] && [ "$(nruns w14)" = 1 ] && ! lg w14 | grep -q 'carrying on' \
  && [ "$("$B/cc-board" get $REPO w14 status)" = review ] \
  && ! tail -n +$((nlb+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -q 'committed nothing'; } \
  && ok "a bounded round whose last iteration COMMITTED is over, not paused: exit 0, board \`review\`, and no 'committed nothing' line at the owner" \
  || bad "no-extend with commits: rc=$rc runs=$(nruns w14) board=$("$B/cc-board" get $REPO w14 status)"
mktrack w15 "one bounded round, no PR"
mkclaude bound15claude w15 'echo "work $n" > "bound15-$n.txt"; echo "- step $n" >> "$st/progress.md"'
CC_CLAUDE="$T/bound15claude" "$B/cc-loop" $REPO w15 --max-iter 1 --no-extend --quiet >/dev/null 2>&1; rc=$?
{ [ "$rc" = 0 ] && [ "$("$B/cc-board" get $REPO w15 status)" = blocked ]; } \
  && ok "…and one that opened no PR lands on \`blocked\`, never \`review\` — the word cc-reconcile would settle it on anyway, and the one that files no finding" \
  || bad "no-extend without a PR: rc=$rc board=$("$B/cc-board" get $REPO w15 status)"
# 6c: AN ITERATION THAT ENDS WITH ITS OWN cc-green RUN STILL GOING IS NOT IDLE (twelve "committed nothing" stops over a
# detached suite in ten days to 2026-09-19, each a relaunch and a planning wake). The stub cc-green answers as the real
# one does on a root with a run going: `wait` says still running (exit 3) twice, then ended (exit 0); asked on the next
# iteration, nothing is running. The stub claude journals NOTHING on iteration 1 — the run is all it did — so without
# the fix that iteration is a runaway signal AND the step limit stops the loop (exit 6, one run). Own track, own
# stub, own counter; the stub also writes where it was asked from, which must be this track's worktree and no other.
mktrack w20 "start the suite, then read it"
mkclaude greenclaude w20 '[ "$n" -ge 2 ] && echo "STATUS: DONE" >> "$st/progress.md"'
cat > "$T/greenstub" <<F
#!/bin/sh
echo "\$PWD" >> "$T/green.cwd"; c=\$(cat "$T/green.n" 2>/dev/null || echo 0); c=\$((c+1)); echo \$c > "$T/green.n"
case "\$1:\$c" in wait:1|wait:2) echo "cc-green: still running (pid 1, since now) — log $T/green.log"; exit 3;;
  wait:3) echo "cc-green: the run (pid 1, started now) has ended — log $T/green.log"; echo "cc-green: green on abc"; exit 0;;
  *) echo "cc-green: green on abc"; exit 0;; esac
F
chmod +x "$T/greenstub"; rm -f "$T/green.n" "$T/green.cwd"
CC_GREEN="$T/greenstub" CC_CLAUDE="$T/greenclaude" "$B/cc-loop" $REPO w20 --max-iter 1 --quiet >/dev/null 2>&1; rc=$?
{ [ "$rc" = 0 ] && [ "$(nruns w20)" = 2 ] && lg w20 | grep -q 'still going — waiting on it, no model call' \
  && lg w20 | grep -q 'one more iteration to read the result' && ! lg w20 | grep -q 'runaway signal' \
  && grep -q "^- cc-loop: the cc-green run iteration 1 started ended while the loop waited on it (exit 0, log $T/green.log)" ~/.cc/state/$REPO/w20/progress.md \
  && [ "$(sort -u "$T/green.cwd")" = "$HOME/.cc/worktrees/$REPO/w20" ]; } \
  && ok "an iteration that ends with its own cc-green run still going is not idle: the loop waits it out (no model call), journals the result for the next context, raises no runaway signal, and at the step limit buys ONE more iteration to read it — asked on this track's worktree, no other" \
  || bad "gate-wait: rc=$rc runs=$(nruns w20) cwd='$(sort -u "$T/green.cwd" 2>/dev/null)' log: $(lg w20 | grep -E 'cc-green|runaway|exit' | tail -3)"
# 6c': …AND THAT ONE ITERATION IS GRANTED ONCE PER ROUND, AND THE SPEND RULE STILL COUNTS A GATED ITERATION (review of
# #541): a worker that ends EVERY iteration with a fresh suite run on a red gate, never committing, was extended at every
# limit and excused from every runaway signal — no bound on the spend at all. Here every iteration is gated (the stub
# cc-green says running, running, ended, for two iterations, then nothing running — BOUNDED, because against the
# defective loop an unbounded stub never ends: the first draft of this case ran 490 extended iterations on the
# pre-repair bins and was ended by its stop file), nothing commits, nothing journals, and the loop is given a $0.10
# yardstick against $0.50 iterations: iteration 1 is gated and buys one more; iteration 2 is gated too, but the grant
# is spent until a commit, so the loop ends there (exit 6, two runs, not three) — and its spend since the last commit,
# 5x the yardstick, is a runaway signal in the log even though the iteration was gated.
mktrack w22 "re-run the red suite forever"
mkclaude green22claude w22 ':'   # commits nothing, journals nothing, ever — the run is all it does
cat > "$T/greenstub22" <<F
#!/bin/sh
c=\$(cat "$T/green22.n" 2>/dev/null || echo 0); c=\$((c+1)); echo \$c > "$T/green22.n"
case "\$1:\$c" in wait:1|wait:2|wait:4|wait:5) echo "cc-green: still running (pid 1, since now) — log $T/green22.log"; exit 3;;
  wait:3|wait:6) echo "cc-green: the run (pid 1, started now) has ended — log $T/green22.log"; echo "cc-green: NOT green on abc"; exit 1;;
  *) echo "cc-green: NOT green on abc"; exit 1;; esac
F
chmod +x "$T/greenstub22"; rm -f "$T/green22.n"
CC_GREEN="$T/greenstub22" CC_CLAUDE="$T/green22claude" "$B/cc-loop" $REPO w22 --max-iter 1 --budget 0.1 --quiet >/dev/null 2>&1; rc=$?
{ [ "$rc" = 6 ] && [ "$(nruns w22)" = 2 ] && [ "$(lg w22 | grep -c 'one more iteration to read the result')" = 1 ] \
  && lg w22 | grep -q 'runaway signal 1/3: spent \$1.0* since its last commit' && ! lg w22 | grep -q 'runaway signal .*journal untouched'; } \
  && ok "…and that extra iteration is granted ONCE per round: a worker re-running its suite every iteration without committing is extended once and then stopped at the limit (exit 6, two runs), and the spend-since-last-commit rule still counts a gated iteration — only the untouched journal and the repeated outcome are what the live run explains" \
  || bad "gate-wait grant: rc=$rc runs=$(nruns w22) grants=$(lg w22 | grep -c 'one more iteration') log: $(lg w22 | grep -E 'runaway|exit' | tail -3)"
# 6d: A LOOP IS STOPPED BY A FILE, NOT A KILL. Written while iteration 1 runs (here by the stub claude itself — the
# shape of a session touching it while the worker is mid-turn), it ends the loop before iteration 2's model call:
# one run, exit 14, the board `blocked` with the reason, one journal line, the file consumed, nobody paged. And a
# stop file from BEFORE the dispatch is stale — cleared at start, so the re-dispatch it predates still runs its
# first iteration: the same case proves both, since one run means the stale file did not stop it and the live one did.
mktrack w21 "stop me by file"
mkclaude stopclaude w21 'echo "- step $n" >> "$st/progress.md"; echo "wasted: wrong branch" > "$st/stop"'
echo stale > ~/.cc/state/$REPO/w21/stop
nls=$(wc -l < "$CC_NOTIFY_LOG" 2>/dev/null || echo 0)
CC_CLAUDE="$T/stopclaude" "$B/cc-loop" $REPO w21 --max-iter 3 --quiet >/dev/null 2>&1; rc=$?
{ [ "$rc" = 14 ] && [ "$(nruns w21)" = 1 ] && [ ! -e ~/.cc/state/$REPO/w21/stop ] && [ "$("$B/cc-board" get $REPO w21 status)" = blocked ] \
  && lg w21 | grep -q 'stop file from before this dispatch was cleared' \
  && lg w21 | grep -q 'exit 14: stopped by .*/w21/stop after iteration 1 — wasted: wrong branch' \
  && grep -q '^- cc-loop: stopped by .*/w21/stop after iteration 1 — wasted: wrong branch' ~/.cc/state/$REPO/w21/progress.md \
  && [ "$(tail -n +$((nls+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -c "/w21 ")" = 0 ]; } \
  && ok "a stop file written mid-run ends the loop before its next model call: one run of three, exit 14, board \`blocked\` with the reason in the log and the journal, the file consumed, nobody paged — and a stop file from before the dispatch is cleared at start rather than obeyed" \
  || bad "stop file: rc=$rc runs=$(nruns w21) file=$([ -e ~/.cc/state/$REPO/w21/stop ] && echo present || echo gone) board=$("$B/cc-board" get $REPO w21 status) notified=$(tail -n +$((nls+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -c "/w21 ") log: $(lg w21 | tail -2)"
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
# 9: DONE is the worker's word; done is `cc done`'s (monthly audit 2026-09-01 F3). The push behind it died — a DNS blip at
# 05:07Z, a refused lease — and the loop, piping `cc done` through tail -1, notified DONE with `PR: ` empty, exited 0, and
# the board went green over work no PR carried. Here the remote refuses that one branch, the way a dead network would.
mktrack w15 "finish, and lose the push"
mkclaude doneclaude w15 'echo "work $n" > "done-$n.txt"; echo "- step $n" >> "$st/progress.md"; echo "STATUS: DONE" >> "$st/progress.md"'
mkdir -p "$T/remote.git/hooks"; printf '#!/bin/sh\nwhile read o n r; do [ "$r" = refs/heads/track/w15 ] && { echo "the network went away" >&2; exit 1; }; done; exit 0\n' > "$T/remote.git/hooks/pre-receive"; chmod +x "$T/remote.git/hooks/pre-receive"
nl0=$(wc -l < "$CC_NOTIFY_LOG" 2>/dev/null || echo 0)
CC_CLAUDE="$T/doneclaude" "$B/cc-loop" $REPO w15 --max-iter 1 --quiet >/dev/null 2>&1; rc=$?
rm -f "$T/remote.git/hooks/pre-receive"
{ [ "$rc" = 4 ] && [ "$("$B/cc-board" get $REPO w15 status)" = blocked ] && "$B/cc-board" get $REPO w15 notes | grep -q 'loop exit 4: .*push failed' \
  && ! tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -q "w15 done" && tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -q "w15 finished, but opened no PR"; } \
  && ok "STATUS: DONE over a dead push is not done: cc done's failure reaches the loop — exit 4, board blocked with the reason, no DONE notice (audit F3)" \
  || bad "a dead push finished green: rc=$rc status=$("$B/cc-board" get $REPO w15 status) notes=$("$B/cc-board" get $REPO w15 notes | tail -c 200)"
# P9: THE GRANT IS SPENT BY THE LOOP, and by nothing a session can type. A track on a repo
# CC_SELF_LAND_EXCEPT does not name that finishes DONE has its landing queued right here, once `cc done` has returned a PR — and
# with the coordinates of the card `cc done` just posted, so a landing that STOPS marks and answers that card instead
# of leaving one that still reads as pending in #approvals. Both real doors are stubbed: CC_LAND, because a real
# `queue` writes into this box's own landing queue and starts a worker that gates, MERGES and deploys; CC_SLACK,
# because a real post-approval puts a fixture PR in the owner's #approvals.
mktrack w19 "finish, and land itself"
mkclaude landclaude w19 'echo "work $n" > "land-$n.txt"; echo "- step $n" >> "$st/progress.md"; echo "STATUS: DONE" >> "$st/progress.md"'
# Its own copies of the two P8 stubs: a scoped run may skip the stanza that made them, and a case that borrows
# another stanza's fixture is red for a reason that has nothing to do with what it tests.
mkdir -p "$T/ghbin8"
printf '#!/usr/bin/env bash\ncase "$*" in *"pr create"*) echo "https://github.com/x/y/pull/77";; esac\nexit 0\n' > "$T/ghbin8/gh"
printf '#!/bin/sh\necho "$*" >> "%s/land.calls"\necho "[x] PR #77 queued"\n' "$T" > "$T/landstub"
printf '#!/bin/sh\ncase "$1" in post-approval) echo "CAPPR 1788000000.000100";; esac\nexit 0\n' > "$T/slackstub"; chmod +x "$T/ghbin8/gh" "$T/landstub" "$T/slackstub"
: > "$T/land.calls"
CC_SELF_LAND_EXCEPT= CC_LAND="$T/landstub" CC_SLACK="$T/slackstub" CC_CLAUDE="$T/landclaude" PATH="$T/ghbin8:$PATH" \
  "$B/cc-loop" $REPO w19 --max-iter 1 --quiet >/dev/null 2>&1; rc=$?
{ [ "$rc" = 0 ] && grep -qx "queue $REPO 77 --who cc done --chat CAPPR --ts 1788000000.000100" "$T/land.calls"; } \
  && ok "cc-loop spends the grant: a DONE track on a granted repo has its PR queued by the LOOP — on the host, in a process no session can spell — carrying the #approvals card cc done just posted, so a stopped landing answers that card (P9)" \
  || bad "the loop did not queue with the card: rc=$rc calls=[$(cat "$T/land.calls")]"
: > "$T/land.calls"
CC_LAND="$T/landstub" CC_SLACK="$T/slackstub" CC_CLAUDE="$T/landclaude" PATH="$T/ghbin8:$PATH" \
  "$B/cc-loop" $REPO w19 --max-iter 1 --quiet >/dev/null 2>&1
[ ! -s "$T/land.calls" ] \
  && ok "…and a repo named as an exception (the suite's own CC_SELF_LAND_EXCEPT) is left exactly as it was: the loop queues nothing and the PR waits for a 👍 (P9b)" \
  || bad "the loop queued a landing for an ungranted repo: $(cat "$T/land.calls")"
# P9c-P9j: managed host delivery. Own HOME, board, state and Git remote; systemd-run only records a start.
(
pass=0; fail=0
export HOME="$T/delivery-home" D="$T/delivery-fixture" REALBIN="$B"
mkdir -p "$HOME/dev/r" "$D/bin"
export PATH="$D/bin:/usr/bin:/bin" GIT_CONFIG_GLOBAL="$D/gitconfig" GIT_CONFIG_SYSTEM=/dev/null
export CC_CONFIG="$D/config" CC_SELF_LAND_EXCEPT= CC_SLACK="$D/bin/cc-slack" CC_CLAUDE="$D/bin/claude"
unset GIT_CONFIG_COUNT GH_TOKEN GH_HOST GH_REPO TMUX TMUX_PANE CC_MEMBER_SANDBOX CC_WORKER_SANDBOX
printf '[user]\n name = fixture\n email = fixture@example.test\n' > "$D/gitconfig"; : > "$D/config"
cp "$B/cc" "$B/cc-task" "$B/cc-loop" "$B/cc-land" "$B/cc-checkpoint" "$B/cc-config" "$D/bin/"
cat > "$D/bin/cc-board" <<'SH'
#!/bin/bash
case "$*" in 'status r row review') [ ! -e "$D/board.fail" ] || exit 1;; esac
exec "$REALBIN/cc-board" "$@"
SH
cat > "$D/bin/gh" <<'SH'
#!/bin/bash
echo "$*" >> "$D/gh.calls"
case "$*" in
  *'pr list'*'--state open'*) cat "$D/open" 2>/dev/null; exit 0;;
  *'pr list'*) exit 0;;
  *'pr create'*) echo create >> "$D/creates"; echo https://github.com/fixture/repo/pull/77 | tee "$D/open";;
esac
SH
cat > "$D/bin/cc-slack" <<'SH'
#!/bin/bash
[ "$1" = post-approval ] || exit 0
[ ! -e "$D/card.fail" ] || exit 1
echo 'fixture 123.456'
SH
cat > "$D/bin/claude" <<'SH'
#!/bin/bash
echo work >> work.txt
echo 'STATUS: DONE' >> "$HOME/.cc/state/r/row/progress.md"
echo '{"is_error":false,"num_turns":1,"total_cost_usd":0,"result":"done"}'
SH
cat > "$D/bin/host-queue" <<'SH'
#!/bin/bash
echo "$*" >> "$D/host.calls"
exec "$D/bin/cc-land" "$@"
SH
printf '#!/bin/sh\necho "$*" >> "$D/starts"\nexit 0\n' > "$D/bin/systemd-run"
printf '#!/bin/sh\necho "$*" >> "$D/notices"\n' > "$D/bin/cc-notify"
printf '#!/bin/sh\nwhile [ "$1" != -- ]; do shift; done; shift\nexec "$@"\n' > "$D/bin/cc-sandbox"
for tool in cc-pause tmux; do printf '#!/bin/sh\nexit 1\n' > "$D/bin/$tool"; done
for tool in cc-model cc-limit cc-scope cc-trust cc-gh-token; do printf '#!/bin/sh\nexit 1\n' > "$D/bin/$tool"; done
chmod +x "$D/bin/"*
# THAT cc-sandbox STANDS IN FOR A BOUNDARY, SO IT HAS TO BE ABLE TO FAIL. Everything up to `--` is the profile —
# `<repo> <track> --`, `member <h> --` and `vet --` — and the command after it runs whole. The fixed `shift 3` it
# replaced ate a `vet` profile's first command word (core/mail/selfcheck.py); that stub, and no stub, read red here.
sbx_runs(){ for p in 'r row' 'member h' vet; do [ "$("$1" $p -- printf '%s|' timeout 'a b' 2>/dev/null)" = 'timeout|a b|' ] || return 1; done; }
printf '#!/bin/sh\nshift 3\nexec "$@"\n' > "$D/shift3-sandbox"; chmod +x "$D/shift3-sandbox"
{ sbx_runs "$D/bin/cc-sandbox" && ! sbx_runs "$D/shift3-sandbox" && ! sbx_runs "$D/no-such-sandbox"; } \
  && ok "P9s: the fixture's cc-sandbox runs the command whole after every profile; a shift-3 stub and a missing one read red" \
  || bad "P9s: the fixture's cc-sandbox mis-reads a profile, or the control stubs pass"
export CC_LAND="$D/bin/host-queue"
git init -q -b main "$HOME/dev/r"; git init -q --bare "$D/remote.git"
echo '/.cc/' > "$HOME/dev/r/.gitignore"
git -C "$HOME/dev/r" add -A; git -C "$HOME/dev/r" commit -qm base
git -C "$HOME/dev/r" remote add origin "$D/remote.git"; git -C "$HOME/dev/r" push -q origin main
git -C "$D/remote.git" symbolic-ref HEAD refs/heads/main
"$B/cc-board" init r "$HOME/dev/r" main >/dev/null
"$B/cc-board" add r row 'delivery fixture' 'Finish the change.' >/dev/null
wt="$HOME/.cc/worktrees/r/row"; st="$HOME/.cc/state/r/row"; q="$HOME/.cc/state/land/r-77.json"
mkdir -p "$(dirname "$wt")"; git -C "$HOME/dev/r" worktree add -q -b track/row "$wt"
"$D/bin/cc-task" claim r row --executor subagent >/dev/null
echo work > "$wt/work.txt"
"$D/bin/cc-land" queue --task r row > "$D/receipt" 2> "$D/err"; first_rc=$?
first_job=$(cat "$q" 2>/dev/null)
"$D/bin/cc-loop" r row --max-iter 1 --quiet > "$D/loop.out" 2>&1; loop_rc=$?
{ [ "$first_rc" = 0 ] && [ "$loop_rc" = 0 ] && [ "$(cat "$q")" = "$first_job" ] \
  && [ "$(wc -l < "$D/creates")" = 1 ] && grep -qx 'queue --task r row' "$D/host.calls" \
  && jq -e '.chat == "fixture" and .ts == "123.456"' "$q" >/dev/null \
  && jq -e '.landing.status == "queued"' "$D/receipt" >/dev/null; } \
  && ok "P9c: planner and loop reach one queue job and one PR with the receipt's approval card" \
  || bad "P9c: first=$first_rc loop=$loop_rc $(cat "$D/err" "$D/loop.out")"
rm -f "$q"; : > "$D/starts"
CC_SELF_LAND_EXCEPT=r "$D/bin/cc-land" queue --task r row > "$D/receipt" 2> "$D/err"; rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$q" ] && [ ! -s "$D/starts" ] && jq -e '.landing.status == "approval" and .card.chat == "fixture"' "$D/receipt" >/dev/null; } \
  && ok "P9d: a repo named as an exception keeps the PR and card but queues nothing; P9c is its control" || bad "P9d: $(cat "$D/receipt" "$D/err")"
mkdir -p "$HOME/dev/r/.cc"; touch "$HOME/dev/r/.cc/member-facing"
"$D/bin/cc-land" queue --task r row > "$D/receipt" 2> "$D/err"; rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$q" ] && [ ! -s "$D/starts" ] && jq -e '.landing.status == "approval" and .card.chat == "fixture"' "$D/receipt" >/dev/null; } \
  && ok "P9e: an unlisted member-facing task holds no grant — it keeps the PR and card and waits for a 👍, as P9d's exception does; P9c is its control" || bad "P9e: rc=$rc $(cat "$D/receipt" "$D/err")"
rm "$HOME/dev/r/.cc/member-facing"
for projection in board card; do
  # The same PR, with its announcement pending. A board/card outage is never the missing-PR page.
  jq --arg p "$projection" '.pending[$p] = (if $p == "board" then {pr:.pr.url,status:"review"} else {url:.pr.url} end) | if $p == "card" then .card=null else . end' \
    "$st/delivery.json" > "$D/record"; mv "$D/record" "$st/delivery.json"
  touch "$D/$projection.fail"; : > "$D/notices"
  "$D/bin/cc-loop" r row --max-iter 1 --quiet > "$D/loop.out" 2>&1; rc=$?
  { [ "$rc" = 0 ] && [ -e "$q" ] && ! grep -q 'finished, but opened no PR' "$D/notices" \
    && grep -q "delivery projection pending: $projection" "$st/loop.log" \
    && [ "$("$B/cc-board" get r row status)" != blocked ]; } \
    && ok "P9f $projection: pending projection over a real PR logs a note, queues, and never blocks or pages" || bad "P9f $projection: rc=$rc $(cat "$D/loop.out")"
  rm "$D/$projection.fail"
  "$D/bin/cc-land" queue --task r row > "$D/receipt" 2> "$D/err"
  jq -e '.pending == {} and .errors == []' "$D/receipt" >/dev/null \
    && ok "P9f $projection control: retry settles the same delivery without a new PR" || bad "P9f retry: $(cat "$D/receipt")"
done
rm "$q"; mv "$st/delivery.json" "$D/saved-record"
"$D/bin/cc-land" queue --task r row > "$D/receipt" 2> "$D/err"; rc=$?
{ [ "$rc" != 0 ] && [ ! -e "$q" ] && grep -q 'needs a task record' "$D/err"; } \
  && ok "P9g: queue --task refuses a legacy row out loud; P9c is its control" || bad "P9g: rc=$rc $(cat "$D/err")"
mv "$D/saved-record" "$st/delivery.json"
# Remove prior PR evidence: this is a new task whose first push fails, the control to P9f.
jq '.pr=null | .card=null' "$st/delivery.json" > "$D/record"; mv "$D/record" "$st/delivery.json"
printf '#!/bin/sh\necho "fixture push refused" >&2\nexit 1\n' > "$D/remote.git/hooks/pre-receive"; chmod +x "$D/remote.git/hooks/pre-receive"
: > "$D/notices"; : > "$D/gh.calls"
"$D/bin/cc-loop" r row --max-iter 1 --quiet > "$D/loop.out" 2>&1; rc=$?
{ [ "$rc" = 4 ] && [ ! -e "$q" ] && [ "$("$B/cc-board" get r row status)" = blocked ] \
  && grep -q 'finished, but opened no PR' "$D/notices" && grep -q 'push failed' "$st/loop.log" && [ ! -s "$D/gh.calls" ]; } \
  && ok "P9h: no PR after a failed push keeps exit 4, blocked and the existing page; P9f is its control" || bad "P9h: rc=$rc $(cat "$D/loop.out")"
rm "$D/remote.git/hooks/pre-receive"; : > "$D/notices"
CC_LAND=/bin/true "$D/bin/cc-loop" r row --max-iter 1 --quiet > "$D/loop.out" 2>&1; rc=$?
{ [ "$rc" = 12 ] && [ "$("$B/cc-board" get r row status)" = blocked ] && grep -q 'delivery unconfirmed' "$D/notices" \
  && ! grep -q 'finished, but opened no PR' "$D/notices"; } \
  && ok "P9i: an empty host response uses exit 12 and says delivery is unconfirmed; P9c's receipt is its control" || bad "P9i: rc=$rc $(cat "$D/loop.out")"
# The real cc --go must adopt the lander's reservation through its shell subprocesses. The window is a stub.
cat > "$D/bin/tmux" <<'SH'
#!/bin/bash
case "$1" in new-window) jq -e '.claim.phase == "repair"' "$HOME/.cc/state/r/row/delivery.json" > "$D/phase-at-launch";; esac
exit 0
SH
printf '#!/bin/sh\nexit 1\n' > "$D/bin/pgrep"; chmod +x "$D/bin/pgrep"
python3 - <<'PY' > "$D/repair.out" 2>&1
import json, os, pathlib, subprocess
root = pathlib.Path.home(); bins = pathlib.Path(os.environ['D']) / 'bin'
record = root / '.cc/state/r/row/delivery.json'
d = json.loads(record.read_text()); d['pr'] = {'url': 'https://github.com/fixture/repo/pull/77'}
record.write_text(json.dumps(d))
def run(*argv):
    return subprocess.run(list(map(str, argv)), capture_output=True, text=True, check=True)
head = run('git', '-C', root / '.cc/worktrees/r/row', 'rev-parse', 'HEAD').stdout.strip()
args = (bins / 'cc-task', 'reserve-repair', 'r', 'row', '--generation', str(d['claim']['generation']),
        '--branch', 'track/row', '--pr', d['pr']['url'], '--head', head)
reservation = json.loads(run(*args).stdout)
run(bins / 'cc', 'r', 'row', '--go', '', '--loop', '1', '--no-extend')
after = json.loads(record.read_text()); replay = json.loads(run(*args).stdout)
assert reservation['launch'] and not replay['launch']
assert after['claim']['generation'] == reservation['generation'] and after['claim']['ended_at']
assert len(after['executions']) == len(d['executions']) + 1
assert after['executions'][-1]['execution_id'] == reservation['execution_id'] == replay['execution_id']
assert after['executions'][-1]['phase'] == 'repair'
PY
rc=$?
{ [ "$rc" = 0 ] && grep -qx true "$D/phase-at-launch"; } \
  && ok "P9j: cc --go adopts and releases the reserved repair without a build execution; replay grants no launch" || bad "P9j: $(cat "$D/repair.out")"
printf '%s %s\n' "$pass" "$fail" > "$D/counts"
)
read -r m3pass m3fail < "$T/delivery-fixture/counts"; pass=$((pass+m3pass)); fail=$((fail+m3fail))
# 10: the context trim (CC_LOOP_TRIM) reaches the worker's own environment when it is on, and OFF IS THE DEFAULT —
# off is the run this loop has always done, with no context edit in the request at all. It ships off so a week of
# shadow measurement (`cc-loop context-report`) can decide it on dollars per accepted PR, not on tokens per turn.
mktrack w16 "trimmed or not"
mkclaude trimclaude w16 'echo "${CLAUDE_CODE_EXTRA_BODY:-none}" > "$st/extra-body"; echo "- step $n" >> "$st/progress.md"'
: > "$T/trimcfg"   # its own empty config, so "off by default" is the default and not whatever this box has set
CC_CONFIG="$T/trimcfg" CC_CLAUDE="$T/trimclaude" "$B/cc-loop" $REPO w16 --max-iter 1 --quiet >/dev/null 2>&1
off=$(cat ~/.cc/state/$REPO/w16/extra-body 2>/dev/null)
CC_LOOP_TRIM=1 CC_CONFIG="$T/trimcfg" CC_CLAUDE="$T/trimclaude" "$B/cc-loop" $REPO w16 --max-iter 1 --quiet >/dev/null 2>&1
on=$(cat ~/.cc/state/$REPO/w16/extra-body 2>/dev/null)
{ [ "$off" = none ] && [ "$(jq -r '.context_management.edits[0].type' <<<"$on" 2>/dev/null)" = clear_tool_uses_20250919 ] \
  && [ "$(lg w16 | grep -c 'context trim on')" = 1 ]; } \
  && ok "the context trim is off by default — the worker's environment carries no context edit at all — and CC_LOOP_TRIM=1 puts one there, on the run the log names" \
  || bad "context trim wiring: off=$(head -c 60 <<<"$off") on=$(head -c 60 <<<"$on") logged=$(lg w16 | grep -c 'context trim on')"
# 11: …and the knob survives the DISPATCH, which is the only way anyone sets it per run. `cc … --go` starts the loop
# in a NEW TMUX WINDOW, and that window gets the tmux server's environment, not the caller's — so a knob that is not
# in cc's `pre` whitelist is silently dropped and cc-config falls back to ~/.cc/config. That fails in BOTH directions
# (`CC_LOOP_TRIM=0` in front of a box whose config says 1 still trims; `=1` on a box with no key does not), and a
# shadow week comparing trimmed against untrimmed tracks would be measuring neither (review of #184). Own stub, own log.
mktrack w17 "dispatched, trimmed or not"   # its own track and its own tmux stub: this case reads the command cc
mkdir -p "$T/trimstub"; printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "$TMUX_STUB_LOG"\nexit 0\n' > "$T/trimstub/tmux"   # would have launched, so nothing runs
chmod +x "$T/trimstub/tmux"
god(){ : > "$T/trimgo.log"; env PATH="$T/trimstub:$B:$PATH" TMUX_STUB_LOG="$T/trimgo.log" CC_CLAUDE=/bin/true "$@" \
         "$B/cc" $REPO w17 --go 'trim or not' >/dev/null 2>&1; grep new-window "$T/trimgo.log"; }
gnone=$(god env); gon=$(god env CC_LOOP_TRIM=1); goff=$(god env CC_LOOP_TRIM=0)
{ ! grep -q CC_LOOP_TRIM <<<"$gnone" && grep -q 'CC_LOOP_TRIM=1 ' <<<"$gon" && grep -q 'CC_LOOP_TRIM=0 ' <<<"$goff"; } \
  && ok "the trim knob survives \`cc --go\`: set in front of one dispatch it reaches the loop's own window — 0 as loudly as 1, so a box whose config says 1 can still run one track untrimmed — and nothing is carried when it is unset" \
  || bad "CC_LOOP_TRIM does not cross the tmux window: unset='$(head -c 90 <<<"$gnone")' on='$(head -c 90 <<<"$gon")' off='$(head -c 90 <<<"$goff")'"
# The failures ledger crosses the same way. This file exports CC_FAILURES="$T/failures" so its fixture loops' stops
# (cc-loop stop_record → cc-green red) land in scratch; off cc's list they landed in the box's own ledger — twelve
# `_cctest…` records and their excerpts under ~/.cc/failures from one green suite run, 2026-09-12.
gfl=$(god env CC_FAILURES="$T/flx"); gnofl=$(god env -u CC_FAILURES)
{ grep -qF "CC_FAILURES=$T/flx " <<<"$gfl" && ! grep -q CC_FAILURES <<<"$gnofl"; } \
  && ok "CC_FAILURES crosses \`cc --go\` into the loop's window — a suite's fixture stops reach its scratch ledger, never the box's own — and nothing is carried when it is unset" \
  || bad "CC_FAILURES does not cross the tmux window: set='$(head -c 120 <<<"$gfl")' unset='$(head -c 90 <<<"$gnofl")'"
# …and the spend tier. cc's own tier door reads the environment, but cc-loop asks `cc-tier allows` again at its start
# and at every iteration, from inside the window: off the list it read the BOX's ~/.cc/config, and this file's own
# `export CC_SPEND_TIER=autonomous` (line 5) never reached it — under the box's `stop` (2026-09-16..18) the w1 loop
# above died at its door with no log line, five cases red, and nothing named the tier. "each --go below must start"
# holds only if the word crosses.
gtier=$(god env CC_SPEND_TIER=autonomous); gnotier=$(god env -u CC_SPEND_TIER)
{ grep -q 'CC_SPEND_TIER=autonomous ' <<<"$gtier" && ! grep -q CC_SPEND_TIER <<<"$gnotier"; } \
  && ok "CC_SPEND_TIER crosses \`cc --go\` into the loop's window — the tier the dispatcher answered from is the one the loop's own door asks, so a fixture under the box's stop still starts — and nothing is carried when it is unset" \
  || bad "CC_SPEND_TIER does not cross the tmux window: set='$(head -c 120 <<<"$gtier")' unset='$(head -c 90 <<<"$gnotier")'"
# …and the orch that dispatched a track, the same way: cc-loop records CC_SLACK_ALIAS at start for its stop notice ("a
# track dispatched by an orch has its stop notice addressed to that orch's alias"), and off this list the loop's window
# never had it — every stop woke the repo seat (raised-a-tracks-stop-wakes-the-repo-seat-not-its-orch).
galias=$(god env CC_SLACK_ALIAS=orc); gnoalias=$(god env -u CC_SLACK_ALIAS)
{ grep -q 'CC_SLACK_ALIAS=orc ' <<<"$galias" && ! grep -q CC_SLACK_ALIAS <<<"$gnoalias"; } \
  && ok "CC_SLACK_ALIAS crosses \`cc --go\` into the loop's window — the orch that dispatched a track is what its stop notice is addressed to — and nothing is carried when no orch is in front of the dispatch" \
  || bad "CC_SLACK_ALIAS does not cross the tmux window: set='$(head -c 120 <<<"$galias")' unset='$(head -c 90 <<<"$gnoalias")'"
for t in w8 w9 w10 w11 w12 w13 w14 w15 w16 w17 w18 w19 w20 w21 w22; do "$B/cc" rm $REPO $t >/dev/null 2>&1; done

fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
