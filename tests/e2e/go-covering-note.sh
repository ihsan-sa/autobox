#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# go-covering-note.sh — the stanza "--go is a covering note, never a replacement for the brief (#71)", run alone on the fixtures it stands on.
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
if stanza "--go is a covering note, never a replacement for the brief (#71)"; then
# #71 stopped `--go "text"` overwriting task.md — but it then synced the BOARD from that file, so a brief that
# lived ONLY on the board (`cc board add`, the route sp_main tells every planning session to use) was still
# destroyed on both sides. That is how the same bug reached a fourth track on 2026-08-31: a 4590-byte brief
# became one 138-byte sentence, on the board as well as in task.md. These pin every side of it.
# The FIFTH variant is now impossible rather than fixed: there is one authority, $st/task.md, and the board JSON
# carries no copy to reconcile against. So these also pin the absence of that copy, and the one-off migration of
# the copies boards written before this still hold.
godisp(){ "$B/cc" $REPO "$1" --go "$2" >/dev/null 2>&1; sleep 1
  for id in $(wins "$REPO/$1"); do tmux kill-window -t "$id"; done
  # The window is gone from tmux's list well before cc-loop's own TERM trap (kill_child; parked; log) finishes writing
  # the board — waiting on the window let that straggler land after the next step planted its own board state (#71
  # migration cases going red on main, 2026-09-05). Wait on the loop PROCESS itself, matched by its own argv, bounded.
  for _ in $(seq 1 30); do pgrep -f "cc-loop $REPO $1 " >/dev/null || break; sleep 0.5; done; }
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

# task.md also carries cc-brief's IN FLIGHT block (its own cases are below), and that block is RECOMPUTED at every
# dispatch with a minute-resolution stamp — so every comparison of one dispatch against another compares what a
# PERSON typed, never the bytes: otherwise two dispatches either side of a minute boundary red the suite for a
# change nobody made.
typed(){ python3 -c 'import re,sys;print(re.sub(r"<!-- cc-brief:inflight -->.*?<!-- /cc-brief:inflight -->","",sys.stdin.read(),flags=re.S).strip())'; }

# Re-dispatch must be idempotent, and `--go ""` must move nothing at all.
b0=$(typed < "$tm"); i0=$("$B/cc-board" get $REPO g1 instructions)
godisp g1 "Work the board brief in full."
[ "$(typed < "$tm")" = "$b0" ] && ok "re-dispatching with the same note stacks nothing up" || bad "the same note was added twice"
godisp g1 ""
{ [ "$(typed < "$tm")" = "$b0" ] && [ "$("$B/cc-board" get $REPO g1 instructions)" = "$i0" ]; } \
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
[ "$(typed < "$tm4" 2>/dev/null)" = "just do this one thing" ] \
  && ok "--go on a track with no brief still works (the note becomes the task)" || bad "no-brief task.md: $(cat "$tm4" 2>/dev/null)"
[ "$("$B/cc-board" get $REPO g4 instructions)" = "just do this one thing" ] \
  && ok "--go on a track with no brief: the note IS the brief, and the board reads it back" || bad "no-brief board: $("$B/cc-board" get $REPO g4 instructions)"
# `cc board add` must never eat a brief that is already there — the failure mode all of the above exists for.
"$B/cc-board" add $REPO g4 "g4" "a different brief entirely" >/dev/null 2>&1
{ grep -q 'just do this one thing' "$tm4" && grep -q 'a different brief entirely' "$tm4"; } \
  && ok "cc-board add APPENDS to an existing brief, it never overwrites one" || bad "add clobbered task.md: $(cat "$tm4")"
"$B/cc-board" set $REPO g4 instructions "an explicitly replaced brief" >/dev/null
# `typed`: the replace is of what a person wrote; the computed IN FLIGHT block is the box's and is kept, refreshed.
[ "$(typed < "$tm4")" = "an explicitly replaced brief" ] \
  && ok "…and 'cc-board set … instructions' is the explicit way to replace one" || bad "set instructions: $(cat "$tm4")"

# …AND NONE OF THAT IS WRITTEN THROUGH A LINK. ~/.cc/state/<repo> is bound read-WRITE into a member's boundary
# (cc-sandbox), so the track directory under it is theirs to replace with one — while `cc <h> <t> --go` runs out
# here, as the owner, and `>` follows a link: a dispatch an operator typed became a write wherever it pointed
# (security review of #225; cc-checkpoint's journal_blocked walls the same class for the journal).
mkdir -p "$T/decoyB"
rm -rf ~/.cc/state/$REPO/gL; ln -s "$T/decoyB" ~/.cc/state/$REPO/gL
gl=$("$B/cc" $REPO gL --go "a note that must not leave the state dir" 2>&1); grc=$?
{ [ $grc != 0 ] && grep -q 'symlink' <<<"$gl" && [ -z "$(ls -A "$T/decoyB")" ]; } \
  && ok "a link left at the track's state dir is refused in one line, and the brief goes nowhere near it" \
  || bad "a dispatch wrote through a linked state dir (rc=$grc): $gl | $(ls -A "$T/decoyB")"
mv ~/.cc/state/$REPO "$T/statedir"; ln -s "$T/decoyB" ~/.cc/state/$REPO   # …the same bind lets them swap the REPO directory
gl=$("$B/cc" $REPO gM --go "nor this one" 2>&1); grc=$?
{ [ $grc != 0 ] && [ -z "$(ls -A "$T/decoyB")" ]; } \
  && ok "…nor a link at the repo's own state dir, checked BEFORE the mkdir that would otherwise make a directory through it" \
  || bad "a dispatch made the track dir through a linked repo dir (rc=$grc): $gl | $(ls -A "$T/decoyB")"
rm -f ~/.cc/state/$REPO; mv "$T/statedir" ~/.cc/state/$REPO; rm -f ~/.cc/state/$REPO/gL
godisp gL "a plain note in a plain state dir"
[ "$(typed < ~/.cc/state/$REPO/gL/task.md 2>/dev/null)" = "a plain note in a plain state dir" ] \
  && ok "…while a plain track still gets its task.md, which is the whole point of writing it" \
  || bad "the wall stopped an ordinary dispatch: $(cat ~/.cc/state/$REPO/gL/task.md 2>/dev/null)"
# The LOCK beside it is the same member-writable path, and `>` both follows a link and TRUNCATES: a link left at
# .lock had an operator's dispatch empty whatever it pointed at, as the owner.
printf 'not yours\n' > "$T/victimL"; mkdir -p ~/.cc/state/$REPO/gK; ln -sf "$T/victimL" ~/.cc/state/$REPO/gK/.lock
gl=$("$B/cc" $REPO gK --go "a note whose dispatch must stop at the lock" 2>&1); grc=$?
{ [ $grc != 0 ] && grep -q 'symlink' <<<"$gl" && [ "$(cat "$T/victimL")" = "not yours" ]; } \
  && ok "…and a link left at the track's .lock is refused as well, so nothing is emptied through it and no worker starts" \
  || bad "a dispatch opened a linked lock (rc=$grc): $gl | victim=[$(cat "$T/victimL")]"
rm -f ~/.cc/state/$REPO/gK/.lock

# THE SHAPE IS CHECKED AT BOTH DOORS a brief comes in by (cc-brief). The rule it enforces is written down twice
# already and a session that had read both still dispatched a page of steps, so the check is mechanical and lives
# where the brief is written, not in another prompt. Here: it refuses at each door, and the door writes nothing.
STEPS=$'Do this:\n- Add a --flag to core/bin/cc-foo\n- Edit core/bin/cc-bar to pass it through\n- Run the suite'
gs=$("$B/cc-board" add $REPO g10 "g10" "$STEPS" 2>&1); grc=$?
{ [ $grc != 0 ] && grep -q 'step-list' <<<"$gs" && [ ! -s ~/.cc/state/$REPO/g10/task.md ]; } \
  && ok "cc-board add refuses a brief of steps, names the signal, and writes nothing" || bad "add took a step list (rc=$grc): $gs"
gs=$("$B/cc" $REPO g6 --go "$STEPS" 2>&1); grc=$?
{ [ $grc != 0 ] && grep -q 'step-list' <<<"$gs" && [ ! -s ~/.cc/state/$REPO/g6/task.md ]; } \
  && ok "--go refuses the same note before it starts a worker" || bad "--go dispatched a step list (rc=$grc): $gs"
# CC_STATE points the state home — cc-brief's override ledger AND cc-board's task.md — at this run's temp dir:
# the ledger is one file for the whole box (no repo in its path), so a forced fixture here would otherwise land
# in the box's own record of real overrides. The brief lands under the same root, and that is where it is read.
gs=$(CC_STATE="$T/briefstate" CC_BRIEF_FORCE=1 "$B/cc-board" add $REPO g10 "g10" "$STEPS" 2>&1)
{ grep -q 'FLAGGED' <<<"$gs" && grep -q 'cc-foo' "$T/briefstate/$REPO/g10/task.md" \
  && grep -q '"what": "step-list"' "$T/briefstate/brief/overrides.jsonl"; } \
  && ok "CC_BRIEF_FORCE=1 flags the same brief, lets it through and writes it to the ledger — force is never silence" || bad "force: $gs"
# …and what another live track is holding is COMPUTED into the brief, never typed. This case builds its own
# holder: g1 is live on the board and its branch really does change a file, so the block has something to say.
"$B/cc-board" status $REPO g1 running >/dev/null
g1c=$( ( cd ~/.cc/worktrees/$REPO/g1 && echo held > held-by-g1.txt && git add held-by-g1.txt \
  && git -c user.email=t@t -c user.name=t commit -qm "g1 holds a file" -- held-by-g1.txt ) 2>&1 )
godisp g7 "GOAL: something worth doing, said as a goal."
t7=~/.cc/state/$REPO/g7/task.md
# A red here says which of its three legs gave (2026-09-12, one red in 40 runs and the block alone could not say):
# what the board held g1 at, what track/g1 changes against main, and what the commit above printed.
{ grep -q 'IN FLIGHT' "$t7" && grep -q 'held-by-g1.txt — g1 \[running\]' "$t7"; } \
  && ok "a dispatched brief carries what the board says is in flight, computed at dispatch, never typed" \
  || bad "no IN FLIGHT block for g1 (board: g1=$("$B/cc-board" get $REPO g1 status 2>&1); track/g1 vs main: $(git -C ~/dev/$REPO diff --name-only main...track/g1 2>&1 | tr '\n' ' '); commit: ${g1c:-quiet}): $(cat "$t7" 2>/dev/null)"
# …and it is recomputed, not accumulated: g1 finishes, and the next dispatch stops naming its file. Asserted on
# g1's own file rather than on the block as a whole — other fixture tracks in this suite are live and hold files too.
"$B/cc-board" status $REPO g1 merged >/dev/null
godisp g7 ""
{ ! grep -q 'held-by-g1.txt' "$t7" && grep -q 'said as a goal' "$t7"; } \
  && ok "…and a holder that has finished is dropped at the next dispatch, the typed brief untouched" \
  || bad "a finished holder stayed in the block: $(cat "$t7" 2>/dev/null)"

fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
