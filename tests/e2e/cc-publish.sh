#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# cc-publish.sh — the stanza "cc-publish: core/ publishes itself", run alone on the fixtures it stands on.
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
if stanza "cc-publish: core/ publishes itself"; then
PUB="$T/mirror.git"; git init -q --bare "$PUB"
cd ~/dev/$REPO || exit 1
# A LEDGER OF ITS OWN, beside the call that needs it — not the run-wide export far above. The abort below RECORDS
# a failure, and on 2026-09-11 that record landed in the box's LIVE ~/.cc/failures as scope `_cctest<pid>`, 18 times
# over the next day, where the detector read every one as real. Pointed here, the two cases after the abort read
# both ends: the record is in this dir, and the live one gained nothing. Drop this and the first goes red.
pub(){ env CC_PUBLISH_STATE="$T" CC_FAILURES="$T/failures-publish" CC_NOTIFY_LOG="$T/notify.log" PUBLISH_REMOTE="$PUB" PUBLISH_REPO=$REPO PUBLISH_PREFIX=core PUBLISH_BRANCH=main PUBLISH_ALLOW=LICENSE "$B/cc-publish"; }
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
# BOTH ENDS of the record that abort wrote: it is in this stanza's own ledger, and the box's live one gained no
# `_cctest…` scope. The second line only READS ~/.cc/failures — this suite never writes or deletes anything there.
[ -s "$T/failures-publish/$REPO.jsonl" ] && ok "the abort's failure record lands in the ledger this stanza pointed the recorder at" || bad "the abort recorded nothing in $T/failures-publish — the pointer in pub() is gone, and the next hand to remove the run-wide one leaks into ~/.cc/failures"
[ ! -e ~/.cc/failures/"$REPO".jsonl ] && ok "…and the box's LIVE ~/.cc/failures never gains a \`$REPO\` scope — the 2026-09-11 leak, now a case" || bad "a selftest run wrote $REPO.jsonl into the live ~/.cc/failures"
git rm -q core/bin/leak && git commit -qm "core: no leak" >/dev/null && git push -q origin HEAD
pub >/dev/null 2>&1
[ -f "$T/publish.notified" ] && bad "a publish that got through still remembers the old abort — it would never page again" || ok "a publish that gets through forgets the abort, so the same reason pages again if it returns"
{ [ "$(git rev-parse main:core)" = "$(git -C "$PUB" rev-parse 'main^{tree}')" ] && git -C "$PUB" ls-tree -r --name-only main | grep -qx bin/tool; } && ok "with the leak fixed the whole prefix ships again, untrimmed" || bad "publish after the fix was incomplete"
was=$(git -C "$PUB" rev-parse main); echo wip > core/bin/wip; git add -A; git commit -qm "core: never pushed" >/dev/null
pub >/dev/null 2>&1
[ "$(git -C "$PUB" rev-parse main)" = "$was" ] && ok "only origin's default branch is published — local, unpushed work is not" || bad "unpushed work reached the public repo"
git reset -q --hard origin/main
env CC_PUBLISH_STATE="$T" CC_NOTIFY_LOG="$T/notify.log" PUBLISH_REMOTE= PUBLISH_REPO=$REPO "$B/cc-publish" status 2>&1 | grep -q "publish: off" && ok "no PUBLISH_REMOTE: publishing is simply off (a bare clone never publishes)" || bad "unconfigured publish is not off"
fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
