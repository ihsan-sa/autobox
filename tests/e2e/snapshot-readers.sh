#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# snapshot-readers.sh — the stanza "what the snapshot's four readers do with it (waiting vs the clock, and without it)", run alone on the fixtures it stands on.
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
if stanza "what the snapshot's four readers do with it (waiting vs the clock, and without it)"; then
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
dgn=$(HOME=$SH "$B/cc-reconcile" digest 2>/dev/null)
dga=$(sed -n '/^\*Waiting on you\*/,/^$/p' <<<"$dgn")   # the digest marks him needed by the SECTION a row is filed under
grep -q 'title s_ask' <<<"$dga" && ! grep -qE ': *$' <<<"$dga" && ok "no snapshot: the digest still says he is needed, with no colon trailing a question it does not have" || bad "digest fallback wording: $dga"
# an EMPTY or non-JSON snapshot must read as stale, not kill the reader: jq on empty input exits 0 with no
# output at all, and `$(( now - ))` is a bash abort — this guard exists precisely for the file the writer got wrong.
: > "$SH/.cc/state/reconcile.json"
lse=$(HOME=$SH "$B/cc" ls 2>&1); lserc=$?
[ $lserc = 0 ] && grep -q 's_ask' <<<"$lse" && ok "empty snapshot: \`cc ls\` treats it as stale and still prints the board" || bad "empty snapshot killed cc ls: rc=$lserc — $lse"
printf 'not json' > "$SH/.cc/state/reconcile.json"
dge=$(HOME=$SH "$B/cc-reconcile" digest 2>/dev/null); dgerc=$?
[ $dgerc = 0 ] && grep -q 's_ask' <<<"$dge" && ok "corrupt snapshot: the digest falls back to the board" || bad "corrupt snapshot broke the digest: rc=$dgerc"
# the snapshot cc-reconcile leaves behind — a question a PERSON must answer, and a loop waiting on the CLOCK while
# its board word is still `running` (it hit the limit mid-run). The clock is never "needs you".
cat > "$SH/.cc/state/reconcile.json" <<JSON
{"at":"now","epoch":$(date -u +%s),"limit_until":0,"tracks":{
 "sr/s_ask":{"state":"waiting","board":"waiting","live":true,"waiting_on":"person","why":"which syllabus?"},
 "sr/s_clock":{"state":"running","board":"running","live":true,"waiting_on":"clock","why":"a Claude usage limit"},
 "sr/s_stop":{"state":"blocked","board":"blocked","live":false,"waiting_on":"","why":""}}}
JSON
lss=$(HOME=$SH "$B/cc" ls 2>&1); dgs=$(HOME=$SH "$B/cc-reconcile" digest 2>/dev/null)
grep -q 'which syllabus?' <<<"$lss" && grep -q 'which syllabus?' <<<"$dgs" && ok "snapshot: \`cc ls\` and the digest print the same question, from the one file" || bad "the question did not reach both readers"
grep -q '⏳ held by the usage limit' <<<"$(grep s_clock <<<"$lss")" && grep -q '^⏳ Held by the usage limit:.*title s_clock' <<<"$dgs" && ! grep -q 'title s_clock' <<<"$(sed -n '/^\*Waiting on you\*/,/^$/p;/^\*Stopped\*/,/^$/p' <<<"$dgs")" && ok "snapshot: a loop held by the limit says so in both — whatever word it wears (\`running\` here, not \`blocked\`) — and the digest NAMES it without filing it as his" || bad "clock row invisible while the board says running"
dgh=$(head -1 <<<"$dgs"); grep -q '1 waiting on you' <<<"$dgh" && grep -q '1 held' <<<"$dgh" && ok "snapshot: the clock is counted as held, NOT as one more thing waiting on him — the tally he reads first" || bad "a usage limit was reported as needing the owner: $dgh"
grep -q 'title s_stop' <<<"$(sed -n '/^\*Stopped\*/,/^$/p' <<<"$dgs")" && ! grep -q 'title s_stop' <<<"$(sed -n '/^\*Waiting on you\*/,/^$/p' <<<"$dgs")" && ok "snapshot: a track that merely stopped reads as stopped, not as a question" || bad "a stopped track was filed as needing him"
rm -rf "$SH"

fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
