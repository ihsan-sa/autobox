#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# say-go-loop.sh — the stanza "--say / --go / cc-loop", run alone on the fixtures it stands on.
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
# …but a row name over 64 characters, on the board before its add refused one, is still removable: the janitor's
# `cc rm` failed 77 times on 8 such worktrees (2026-09-14..27). Its own fixture; a 256-character name stays refused.
LONG=r-$(printf 'x%.0s' $(seq 1 70)); mkdir -p ~/.cc/worktrees/$REPO/$LONG ~/.cc/state/$REPO/$LONG
"$B/cc" rm $REPO $LONG >/dev/null 2>&1; lrc=$?
[ $lrc = 0 ] && [ ! -d ~/.cc/worktrees/$REPO/$LONG ] && [ ! -d ~/.cc/state/$REPO/$LONG ] && ok "cc rm removes a worktree whose row name is over 64 characters" || bad "cc rm refused a long row name (rc=$lrc)"
TOOLONG=r-$(printf 'x%.0s' $(seq 1 254)); "$B/cc" rm $REPO $TOOLONG >/dev/null 2>&1
[ $? != 0 ] && ok "…while a 256-character track name is still refused" || bad "cc rm took a 256-character name"
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
if stanza "--say / --go / cc-loop"; then
"$B/cc" $REPO w1 --say hello >/dev/null 2>&1 && bad "--say should fail with no live session" || ok "--say refuses when no session"
tmux new-window -d -t main -n "$REPO/m7" "sleep 30"; sleep 1   # M7: a headless worker's pane is a shell — typed text would run as a command
"$B/cc-msg" "$REPO/m7" "hello" >"$T/m7.out" 2>&1; [ $? != 0 ] && grep -q 'task.md' "$T/m7.out" && ok "cc-msg refuses a window with no interactive claude" || bad "cc-msg typed into a headless pane"
tmux kill-window -t "$(tmux list-windows -t main -F '#{window_id} #W' | awk -v n="$REPO/m7" '$2==n{print $1}')" 2>/dev/null
# M8: a pane with a claude under it AND a permission dialog on screen. The text, or the Enter after it, would
# ANSWER the dialog, and a tool-permission prompt answered by a script is an unattended approval of what the owner
# gates on — so it is not typed. It is not thrown away either (2026-09-01: twelve panes on a model-limit prompt,
# every tick and secretary finding aimed at them refused and lost): it goes to that session's inbox spool, cc-msg
# says "queued", and the 60 s drain hands it over once the pane is free.
# The pane is a copy of bash named `claude` (coreutils refuses to run under another name) with `; true` at every
# level (bash exec-replaces itself on a lone final command, and the process must stay a `claude`).
mkdir -p "$T/fakebin"; cp "$(readlink -f /bin/bash)" "$T/fakebin/claude"
printf 'echo "Do you want to proceed?"\n"%s" -c "sleep 30; true"\ntrue\n' "$T/fakebin/claude" > "$T/m8.sh"
tmux new-window -d -t main -n "$REPO/m8" "bash $T/m8.sh"; sleep 1
"$B/cc-msg" "$REPO/m8" "hello" >"$T/m8.out" 2>&1; m8=$?
m8sp=~/.cc/state/$REPO/m8/inbox.spool
{ [ $m8 = 0 ] && grep -q '^queued$' "$T/m8.out" && jq -e '.text == "hello"' "$m8sp" >/dev/null 2>&1; } \
  && ok "cc-msg spools for a pane with a dialog open — it would answer a permission prompt, and a dropped message is how a session goes silent" \
  || bad "cc-msg did not queue behind a dialog (rc=$m8): $(cat "$T/m8.out") · spool: $(cat "$m8sp" 2>/dev/null)"
"$B/cc-msg" --drain "$REPO/m8" >/dev/null 2>&1
jq -e '.text == "hello"' "$m8sp" >/dev/null 2>&1 \
  && ok "…and the drain leaves it spooled while the dialog is still up" || bad "the drain typed into a pane with a dialog open"
# M9: the same pane WITHOUT the dialog line — the guard must not be a permanent refusal, and this claude is a
# GRANDCHILD of the pane, the shape `cc-handoff --overlap` starts and the old direct-child test called dead.
printf 'bash -c \x27"%s" -c "sleep 30; true"; true\x27\ntrue\n' "$T/fakebin/claude" > "$T/m9.sh"
tmux new-window -d -t main -n "$REPO/m9" "bash $T/m9.sh"; sleep 1
"$B/cc-msg" "$REPO/m9" "hello" >"$T/m9.out" 2>&1; m9=$?
{ [ $m9 = 0 ] && [ ! -s "$T/m9.out" ] && [ ! -s ~/.cc/state/$REPO/m9/inbox.spool ]; } \
  && ok "cc-msg types at an overlap successor, whose claude is a grandchild of the pane — delivered, silent, spool empty" \
  || bad "cc-msg refused a live session (rc=$m9): $(cat "$T/m9.out")"
for w in m8 m9; do tmux kill-window -t "$(tmux list-windows -t main -F '#{window_id} #W' | awk -v n="$REPO/$w" '$2==n{print $1}')" 2>/dev/null; done
for id in $(tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | grep " $REPO/w1$" | cut -d' ' -f1); do tmux kill-window -t "$id"; done
nl0=$(wc -l < "$CC_NOTIFY_LOG" 2>/dev/null || echo 0)
ll0=$(wc -l < ~/.cc/state/$REPO/w1/loop.log 2>/dev/null || echo 0)
# THE FIXTURE --go MUST GET A ROOM. Queued by cc-room it never starts, and the cases below read that as `loop DONE`
# + `iteration count: 0` (#752, #788, 09-29: the box's load, which the e2e preamble did not isolate). Say it here.
rw=$("$B/cc-room" check 2>&1) && ok "cc-room admits the fixture --go: the box's load, PSI, loops and pace never queue it" \
  || bad "cc-room would queue the fixture --go: $rw"
CC_CLAUDE="$T/fakeclaude" "$B/cc" $REPO w1 --go "build the thing" --loop 3 >/dev/null 2>&1
# WAIT ON THE LOOP'S OWN END, NOT THE CLOCK. A fixed 40 s here went red on a loaded box (#670, #699, #722, 09-25..27:
# `loop DONE` + `loop iteration count: 1`, while the notify and board cases below passed — the loop DID finish, a
# beat after the wait gave up). Every stop of cc-loop logs `exit <n>:`, and this fixture ends in one (exit 4, no PR);
# this run's lines only, since w1's loop.log carries earlier stanzas'. The cap only keeps a hung loop from hanging the suite.
for _ in $(seq 1 300); do tail -n +$((ll0+1)) ~/.cc/state/$REPO/w1/loop.log 2>/dev/null | grep -qE '^[^ ]+ exit [0-9]+:' && break; sleep 1; done
for _ in $(seq 1 30); do pgrep -f "cc-loop $REPO w1 " >/dev/null || break; sleep 1; done   # …and its process gone, so nothing below races its last writes
grep -q 'STATUS: DONE' ~/.cc/state/$REPO/w1/progress.md 2>/dev/null && ok "loop ran to DONE via journal" || bad "loop DONE"
[ "$(ls ~/.cc/state/$REPO/w1/runs/*.json 2>/dev/null | wc -l)" = 2 ] && ok "loop stopped after DONE (2 iterations, not 3)" || bad "loop iteration count: $(ls ~/.cc/state/$REPO/w1/runs/*.json 2>/dev/null | wc -l)"
rlog=$(git -C "$T/remote.git" log --oneline track/w1 2>/dev/null)   # capture, don't pipe: grep -q exits on the first match, git log takes SIGPIPE and pipefail calls the whole line a failure once the branch has more than a handful of commits
grep -q 'wip: checkpoint' <<<"$rlog" && ok "loop iterations were checkpointed + pushed" || bad "loop checkpoint — remote track/w1: $(head -3 <<<"$rlog" | tr '\n' ' ') | push.err: $(tr '\n' ' ' < ~/.cc/worktrees/$REPO/w1/.cc/push.err 2>/dev/null)"
# `cc --go` CLAIMS the row, so this is a MANAGED task, and nothing behind this fixture's remote is GitHub: the PR
# lookup cannot answer. A lookup that failed is not evidence that no PR exists, so completion stops there — the
# false success this used to take (`PR creation failed`, exit 0, row left in `review`) is what M2 deletes.
for _ in $(seq 1 30); do tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -q "$REPO/w1 finished, but opened no PR" && break; sleep 1; done   # cc-loop writes it from its tmux window, a beat after DONE
tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | grep -q "$REPO/w1 finished, but opened no PR" \
  && ok "the owner is told a managed track opened no PR — not a DONE notice over an empty PR line (log backend)" \
  || bad "notify: $(tail -n +$((nl0+1)) "$CC_NOTIFY_LOG" 2>/dev/null | tr '\n' ' ')"
st=$("$B/cc-board" get $REPO w1 status); [ "$st" = blocked ] && ok "…and the row says blocked, not review: a PR nobody opened does not put work up for review" || bad "board status after done: $st"
grep -q 'open PR lookup failed' ~/.cc/state/$REPO/w1/loop.log && ok "…and the reason the loop carries is the one that stopped it, not a later summary line" || bad "loop note: $(tail -2 ~/.cc/state/$REPO/w1/loop.log | tr '\n' ' ')"
# …and the same command is safe to run again. Both real doors stay shut: the gh stub answers for GitHub, CC_SLACK
# for #approvals — a fixture PR must never reach either.
mkdir -p "$T/ghw1"
printf '#!/usr/bin/env bash\ncase "$*" in *"pr create"*) echo "https://github.com/x/y/pull/91";; esac\nexit 0\n' > "$T/ghw1/gh"
printf '#!/bin/sh\ncase "$1" in post-approval) echo "W1CARD 1788000000.000200";; esac\nexit 0\n' > "$T/ghw1/slack"; chmod +x "$T/ghw1/gh" "$T/ghw1/slack"
w1out=$(env SLACK_BOT_TOKEN= CC_SLACK="$T/ghw1/slack" PATH="$T/ghw1:$PATH" "$B/cc" done $REPO w1 --json 2>"$T/w1.err"); w1rc=$?
{ [ "$w1rc" = 0 ] && [ "$("$B/cc-board" get $REPO w1 status)" = review ] \
  && jq -e '.pr_url == "https://github.com/x/y/pull/91" and .committed_sha == .pushed_sha and .pending == {} and .errors == [] and .card.chat == "W1CARD"' <<<"$w1out" >/dev/null; } \
  && ok "…and cc done is safe to run again: once GitHub answers, the retry opens the PR, settles both projections and moves the row to review" \
  || bad "w1 retry: rc=$w1rc receipt=$w1out err=$(tail -2 "$T/w1.err" | tr '\n' ' ')"

fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
