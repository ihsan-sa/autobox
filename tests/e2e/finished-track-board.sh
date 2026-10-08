#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# finished-track-board.sh — the stanza "a finished track leaves the default board view (a13)", run alone on the fixtures it stands on.
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
if stanza "a finished track leaves the default board view (a13)"; then
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
"$B/cc-board" add $REPO a13live "a13 still running" >/dev/null; "$B/cc-board" show $REPO | grep -q 'a13 still running' \
  && ok "a13: an unfinished track is untouched by the filter" || bad "a13: the filter dropped a live track"
# KIND=SESSION (owner, 2026-09-01): `cc <repo> <name> --session` marks a row a channel-like session — a long-lived
# session with no task to finish. cc-reconcile leaves its status alone (a track with nobody in its worktree past
# grace would be reconciled); the rest of the rule is pinned in cc-board's and cc-slack's selfchecks.
"$B/cc" "$REPO" sess1 --session >/dev/null 2>&1
[ "$("$B/cc-board" get "$REPO" sess1 kind)" = session ] && ok "cc <repo> <name> --session makes the row kind=session" || bad "--session did not set the kind: $("$B/cc-board" get "$REPO" sess1 kind)"
"$B/cc-board" status "$REPO" sess1 running >/dev/null; for id in $(wins "$REPO/sess1"); do tmux kill-window -t "$id"; done   # nobody in it now
"$B/cc-reconcile" "$REPO" --apply --no-net --grace 0 >/dev/null 2>&1
[ "$("$B/cc-board" get "$REPO" sess1 status)" = running ] && ok "cc-reconcile --apply leaves a session row's status alone" || bad "reconcile flipped the session row to $("$B/cc-board" get "$REPO" sess1 status)"
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
# M2 completion fixtures begin. This block owns its HOME, board, state, remotes and every service stub.
(
pass=0; fail=0
export HOME="$T/done-home" D="$T/done-fixture" REALBIN="$B"
mkdir -p "$HOME/dev/r" "$D/bin"
export PATH="$D/bin:/usr/bin:/bin" GIT_CONFIG_GLOBAL="$D/gitconfig" GIT_CONFIG_SYSTEM=/dev/null
unset GIT_CONFIG_COUNT GH_TOKEN GH_HOST CC_GIT_NAME CC_GIT_EMAIL
export CC_SELF_LAND_EXCEPT=r   # r is the exception here: nothing in this fixture self-lands
export GH_REPO=wrong/repository CC_SLACK="$D/bin/cc-slack"
export CC_CLAUDE=/bin/true
printf '[user]\n name = fixture\n email = fixture@example.test\n' > "$D/gitconfig"
cp "$B/cc" "$B/cc-task" "$D/bin/"; cp "$B/cc-checkpoint" "$D/bin/checkpoint-real"
cat > "$D/bin/cc-checkpoint" <<'SH'
#!/bin/bash
[ "${1:-}" = --commit ] && [ -e "$D/zero" ] && exit 0
[ "${1:-}" = --push ] && [ -e "$D/push-zero" ] && exit 0
exec "$D/bin/checkpoint-real" "$@"
SH
cat > "$D/bin/cc-board" <<'SH'
#!/bin/bash
echo "$*" >> "$D/board.calls"
case "$(cat "$D/board.fail" 2>/dev/null):$*" in all:*|pr:set*pr*|status:status*) exit 1;; esac
exec "$REALBIN/cc-board" "$@"
SH
cat > "$D/bin/gh" <<'SH'
#!/bin/bash
echo "$*" >> "$D/gh.calls"
[ "${GH_REPO:-}" = "$(cat "$D/gh-repo" 2>/dev/null || echo "$D/remote.git")" ] || [ -e "$D/legacy" ] || exit 9
case "$*" in
  *"pr list"*"--state open"*) [ ! -e "$D/open.fail" ] || exit 1; cat "$D/open" 2>/dev/null; exit 0;;
  *"pr list"*"--state merged"*)
    [ ! -e "$D/merged.fail" ] || exit 1
    [ -s "$D/merged.oid" ] && grep -qF "$(cat "$D/merged.oid")" <<<"$*" && cat "$D/url"; exit 0;;
  *"pr create"*)
    echo create >> "$D/creates"; printf '%s\n' "$@" > "$D/create.args"
    [ ! -e "$D/empty" ] || exit 0
    [ ! -e "$D/url-error" ] || { cat "$D/url" >&2; exit 1; }
    cp "$D/url" "$D/open"
    [ ! -e "$D/lost" ] || exit 1
    cat "$D/url";;
esac
SH
cat > "$D/bin/git" <<'SH'
#!/bin/bash
case "$*" in *'remote get-url --push origin') [ ! -e "$D/public-url" ] || { cat "$D/public-url"; exit 0; };; esac
exec /usr/bin/git "$@"
SH
cat > "$D/bin/cc-slack" <<'SH'
#!/bin/bash
[ "$1" = post-approval ] || exit 0
echo card >> "$D/cards"
[ ! -e "$D/card.fail" ] || exit 1
[ ! -e "$D/card.empty" ] || exit 0
echo 'fixture 123.456'
SH
for tool in cc-config cc-scope cc-trust cc-gh-token; do printf '#!/bin/sh\nexit 0\n' > "$D/bin/$tool"; done
printf '#!/bin/sh\nexit 1\n' > "$D/bin/tmux"; chmod +x "$D/bin/"*
git init -q -b main "$HOME/dev/r"; git init -q --bare "$D/remote.git"
printf '/.cc/\n' > "$HOME/dev/r/.gitignore"
git -C "$HOME/dev/r" add -A; git -C "$HOME/dev/r" commit -qm base
git -C "$HOME/dev/r" remote add origin "$D/remote.git"; git -C "$HOME/dev/r" push -q origin main
git -C "$D/remote.git" symbolic-ref HEAD refs/heads/main
"$B/cc-board" init r "$HOME/dev/r" main >/dev/null
newdone(){
  row=$1; wt="$HOME/.cc/worktrees/r/$row"; st="$HOME/.cc/state/r/$row"
  mkdir -p "$(dirname "$wt")" "$st"
  git -C "$HOME/dev/r" worktree add -q -b "track/$row" "$wt"
  "$B/cc-board" add r "$row" "$row title" 'the acceptance brief' >/dev/null
  "$D/bin/cc-task" claim r "$row" --executor subagent >/dev/null
  printf 'Brief from task.md\n<!-- cc-brief:inflight -->\nprivate inflight\n<!-- /cc-brief:inflight -->\nAcceptance stays.\n' > "$st/task.md"
  echo work > "$wt/work.txt"
  rm -f "$D/"*.fail "$D/zero" "$D/push-zero" "$D/lost" "$D/empty" "$D/card.empty" "$D/legacy" "$D/open" "$D/merged.oid" "$D/url-error" "$D/public-url" "$D/gh-repo"
  : > "$D/creates"; : > "$D/cards"; : > "$D/gh.calls"; : > "$D/board.calls"
  echo https://github.com/fixture/repo/pull/42 > "$D/url"
}
rundone(){ "$D/bin/cc" done r "$row" --json > "$D/out" 2> "$D/err"; rc=$?; }
hasreceipt(){ jq -e "$1" "$D/out" >/dev/null 2>&1; }
newdone dirty; touch "$D/zero"; rundone
{ [ "$rc" != 0 ] && [ ! -s "$D/creates" ] && [ -n "$(git -C "$wt" status --porcelain)" ] \
  && hasreceipt '.committed_sha == null and .errors[0].stage == "commit"'; } \
  && ok "P10: a checkpoint returning zero with uncommitted work opens no PR" || bad "P10: $(cat "$D/out" "$D/err")"
rm "$D/zero"; rundone; first=$(git -C "$wt" rev-parse HEAD)
{ [ "$rc" = 0 ] && hasreceipt '.committed_sha == .pushed_sha and .pr_url != null and .pending == {}' \
  && grep -qx "PR: $(cat "$D/url")" "$D/err" && grep -qx 'card: fixture 123.456' "$D/err"; } \
  && ok "P10 control: real completion returns SHAs and preserves the human PR/card lines" || bad "P10 control: $(cat "$D/out" "$D/err")"
rundone
{ [ "$rc" = 0 ] && [ "$(git -C "$wt" rev-parse HEAD)" = "$first" ] && [ "$(wc -l < "$D/creates")" = 1 ] \
  && [ "$(wc -l < "$D/cards")" = 1 ]; } && ok "P11: a clean retry makes no new commit, PR or card" || bad "P11: $(cat "$D/out" "$D/err")"
newdone secret; echo fixture > "$wt/.env"; rundone
{ [ "$rc" != 0 ] && [ ! -s "$D/gh.calls" ] && git -C "$wt" diff --cached --quiet; } \
  && ok "P12: a secret refusal never reaches PR lookup" || bad "P12: $(cat "$D/out" "$D/err")"
rm "$wt/.env"; printf '#!/bin/sh\nexit 1\n' > "$HOME/dev/r/.git/hooks/pre-commit"; chmod +x "$HOME/dev/r/.git/hooks/pre-commit"
rundone; rm "$HOME/dev/r/.git/hooks/pre-commit"
{ [ "$rc" != 0 ] && [ ! -s "$D/gh.calls" ]; } && ok "P12 control: a failed commit also opens nothing" || bad "P12 control: $(cat "$D/out" "$D/err")"
rundone
[ "$rc" = 0 ] && ok "P12 recovery: removing the refusal delivers the same work" || bad "P12 recovery: $(cat "$D/out" "$D/err")"
newdone offtrack; git -C "$wt" checkout -q -b track/elsewhere; rundone
{ [ "$rc" != 0 ] && [ ! -s "$D/gh.calls" ] && hasreceipt '.committed_sha == null'; } \
  && ok "P12 branch control: a different HEAD cannot complete the task" || bad "P12 branch control: $(cat "$D/out" "$D/err")"
newdone push; printf '#!/bin/sh\nexit 1\n' > "$D/remote.git/hooks/pre-receive"; chmod +x "$D/remote.git/hooks/pre-receive"
rundone; rm "$D/remote.git/hooks/pre-receive"
{ [ "$rc" != 0 ] && [ ! -s "$D/gh.calls" ] && hasreceipt '.committed_sha != null and .pushed_sha == null'; } \
  && ok "P13: failed push keeps the commit receipt and prevents PR lookup/create" || bad "P13: $(cat "$D/out" "$D/err")"
touch "$D/push-zero"; rundone; rm "$D/push-zero"
{ [ "$rc" != 0 ] && [ ! -s "$D/gh.calls" ]; } && ok "P13 control: push exit zero without the remote head is still incomplete" || bad "P13 control: $(cat "$D/out" "$D/err")"
rundone
[ "$rc" = 0 ] && ok "P13 recovery: the next push reaches the fixture remote and opens one PR" || bad "P13 recovery: $(cat "$D/out" "$D/err")"
newdone lookup; touch "$D/open.fail"; rundone
{ [ "$rc" != 0 ] && [ ! -s "$D/creates" ] && hasreceipt '.pushed_sha != null and .errors[0].stage == "pr"'; } \
  && ok "P14: failed open lookup is not evidence of no PR" || bad "P14: $(cat "$D/out" "$D/err")"
rm "$D/open.fail"; touch "$D/merged.fail"; rundone
{ [ "$rc" != 0 ] && [ ! -s "$D/creates" ]; } && ok "P14 control: failed merged lookup also cannot create" || bad "P14 control: $(cat "$D/out" "$D/err")"
rm "$D/merged.fail"; touch "$D/lost"; rundone
{ [ "$rc" != 0 ] && [ "$(wc -l < "$D/creates")" = 1 ] && hasreceipt '.pr_url == null and .errors[0].stage == "pr"'; } \
  && ok "P15: losing the create response leaves a failed receipt, with no review projection" || bad "P15: $(cat "$D/out" "$D/err")"
rundone
{ [ "$rc" = 0 ] && [ "$(wc -l < "$D/creates")" = 1 ] && hasreceipt '.pr_url != null and .errors == []'; } \
  && ok "P15 control: retry finds that PR by pushed repository and head, despite a wrong caller GH_REPO" || bad "P15 control: $(cat "$D/out" "$D/err")"
newdone urlerror; touch "$D/url-error"; rundone
{ [ "$rc" != 0 ] && hasreceipt '.pr_url == null' && [ ! -s "$D/cards" ]; } \
  && ok "P15 error control: a URL in failed create output is not a PR receipt" || bad "P15 error control: $(cat "$D/out" "$D/err")"
newdone projections; echo all > "$D/board.fail"; touch "$D/card.fail"; rundone; first=$(git -C "$wt" rev-parse HEAD)
{ [ "$rc" != 0 ] && hasreceipt '.pr_url != null and .committed_sha == .pushed_sha and (.pending | keys) == ["board","card"]' \
  && ! grep -q 'get r projections instructions' "$D/board.calls" && grep -qx 'Brief from task.md' "$D/create.args" \
  && grep -qx 'Acceptance stays.' "$D/create.args" && ! grep -q 'private inflight' "$D/create.args" \
  && [ "$(jq -r .claim.reason "$st/delivery.json")" = delivered ]; } \
  && ok "P16: board/card outages retain pending projections and release the builder; task.md supplies the stripped brief" || bad "P16: $(cat "$D/out" "$D/err")"
echo status > "$D/board.fail"; rundone
{ [ "$rc" != 0 ] && hasreceipt '.pending.board.status == "review" and .pending.card.url != null'; } \
  && ok "P16 control: a successful board PR write does not hide a failed status write, and a board this box could not write is a non-zero completion" || bad "P16 control: $(cat "$D/out" "$D/err")"
rm "$D/board.fail" "$D/card.fail"; touch "$D/card.empty"; rundone
{ [ "$rc" = 0 ] && hasreceipt '.pending.board == null and .pending.card != null and .card == null' \
  && grep -q 'still pending' "$D/err"; } \
  && ok "P17: a card that answers without coordinates stays pending and says so — Slack being out does not turn a real PR into a failed delivery (the control is P16's board, which does)" || bad "P17: $(cat "$D/out" "$D/err")"
rm "$D/card.empty"; rundone
{ [ "$rc" = 0 ] && hasreceipt '.pending == {} and .errors == [] and .card == {"chat":"fixture","ts":"123.456"}' \
  && [ "$(git -C "$wt" rev-parse HEAD)" = "$first" ] && [ "$(wc -l < "$D/creates")" = 1 ]; } \
  && ok "P17 control: the next caller settles both projections without another commit or PR" || bad "P17 control: $(cat "$D/out" "$D/err")"
newdone merged; (cd "$wt" && "$D/bin/cc-checkpoint" --commit)
git -C "$wt" rev-parse HEAD > "$D/merged.oid"; echo all > "$D/board.fail"; rundone
{ [ "$rc" != 0 ] && [ ! -s "$D/creates" ] && [ ! -s "$D/cards" ] \
  && hasreceipt '.closed.status == "merged" and .pending.board.status == "merged"'; } \
  && ok "P18: a merged head opens no duplicate PR/card and durably queues its failed closure projection" || bad "P18: $(cat "$D/out" "$D/err")"
rm "$D/board.fail"; : > "$D/gh.calls"; rundone
{ [ "$rc" = 0 ] && [ ! -s "$D/gh.calls" ] && hasreceipt '.closed.status == "merged" and .pending == {}'; } \
  && ok "P18 recovery: a closed receipt retries the board without another GitHub call" || bad "P18 recovery: $(cat "$D/out" "$D/err")"
"$D/bin/cc" claim r "$row" --executor worker > "$D/claim1" 2>&1; c1=$?
{ [ "$c1" != 0 ] && grep -q closed "$D/claim1" && [ "$(jq -r .closed.status < "$st/delivery.json")" = merged ]; } \
  && ok "P18 claim control: a merge really is the end — the next dispatch's claim on that row is refused (the control for P21 dispatch, where a delivery with no PR is not)" \
  || bad "P18 claim control: rc=$c1 $(cat "$D/claim1")"
echo later > "$wt/later.txt"; rundone
{ [ "$rc" != 0 ] && [ ! -s "$D/gh.calls" ] && hasreceipt '.closed.status == "merged" and .errors[0].stage == "commit"'; } \
  && ok "P18 closure control: later edits cannot inherit a closed delivery" || bad "P18 closure control: $(cat "$D/out" "$D/err")"
rm "$wt/later.txt"; rundone
cp "$st/delivery.json" "$D/retained"; tid=$(jq -r .task_id "$st/delivery.json"); "$D/bin/cc" rm r "$row" >/dev/null 2>&1
{ [ ! -d "$wt" ] && [ ! -d "$st" ] && cmp -s "$HOME/.cc/state/r/.receipts/$row.$tid.json" "$D/retained"; } \
  && ok "P19: removing a managed row retires its receipt instead of deleting the only task-to-PR mapping" \
  || bad "P19: $(ls -R "$HOME/.cc/state/r" 2>&1 | tr '\n' ' ')"
newdone "$row"   # …and the name it freed takes a NEW task, rather than inheriting a closed one nothing can claim
{ [ "$(jq -r .task_id "$st/delivery.json")" != "$tid" ] && [ -f "$HOME/.cc/state/r/.receipts/$row.$tid.json" ]; } \
  && ok "P19 reuse control: a rebuilt row of the same name gets its own task, and the retired receipt is still there" \
  || bad "P19 reuse control: $(jq -r .task_id "$st/delivery.json" 2>&1)"
"$D/bin/cc" rm r "$row" >/dev/null 2>&1
newdone different; git -C "$wt" rev-parse HEAD > "$D/merged.oid"; rundone
{ [ "$rc" = 0 ] && [ "$(wc -l < "$D/creates")" = 1 ] && hasreceipt '.closed == null'; } \
  && ok "P18 control: a different merged head does not suppress new work" || bad "P18 control: $(cat "$D/out" "$D/err")"
newdone legacy; rm "$st/delivery.json"; touch "$D/legacy" "$D/empty"
"$D/bin/cc" done r "$row" > "$D/legacy.out" 2>&1; rc=$?
printf 'PR creation failed (no remote? try: cd %s && gh pr create --base main)\n' "$wt" > "$D/expected"
{ [ "$rc" = 0 ] && cmp -s "$D/legacy.out" "$D/expected" && [ ! -e "$st/delivery.json" ] \
  && [ "$("$B/cc-board" get r "$row" status)" = review ]; } \
  && ok "P20: a legacy row retains its exact output, exit and board behavior on empty create response" || bad "P20: $(cat "$D/legacy.out")"
"$D/bin/cc" done r "$row" --json > "$D/jout" 2> "$D/jerr"; jrc=$?
{ [ "$jrc" != 0 ] && [ ! -s "$D/jout" ] && grep -q 'needs a task record' "$D/jerr"; } \
  && ok "P20 json control: --json is refused on a legacy row rather than printing a receipt nothing wrote" || bad "P20 json control: rc=$jrc $(cat "$D/jerr")"
"$D/bin/cc" rm r "$row" >/dev/null 2>&1
[ ! -e "$st" ] && ok "P19 control: legacy removal still removes state" || bad "P19 control: legacy state retained"
newdone empty; touch "$D/empty"; rundone
{ [ "$rc" != 0 ] && hasreceipt '.pr_url == null and .errors[0].stage == "pr"' \
  && [ "$("$B/cc-board" get r "$row" status)" != review ]; } \
  && ok "P20 control: the same empty response on a managed row fails and never projects review" || bad "P20 control: $(cat "$D/out" "$D/err")"
newdone brief; rm "$st/task.md"; rundone
{ [ "$rc" != 0 ] && [ ! -s "$D/creates" ]; } && ok "P16 brief control: a missing task.md is not replaced by a board read" || bad "P16 brief control: $(cat "$D/out" "$D/err")"
for spelling in https ssh; do
  newdone "$spelling"
  public=https://github.com/fixture/repo.git; [ "$spelling" = https ] || public=git@github.com:fixture/repo.git
  # Git still goes to our bare repo. Only get-url presents the spelling a hosted remote would return.
  git -C "$wt" config --add "url.$D/remote.git.insteadOf" "$public"
  echo "$public" > "$D/public-url"; echo github.com/fixture/repo > "$D/gh-repo"; rundone
  { [ "$rc" = 0 ] && hasreceipt '.pr_url != null and .committed_sha == .pushed_sha'; } \
    && ok "P22 $spelling: PR lookup pins the push repository in gh format, ignoring caller GH_REPO" || bad "P22 $spelling: $(cat "$D/out" "$D/err")"
done
newdone local; git -C "$HOME/dev/r" remote remove origin; mkdir -p "$HOME/dev/r/.cc"; touch "$HOME/dev/r/.cc/member-workspace"
echo all > "$D/board.fail"; rundone
{ [ "$rc" != 0 ] && hasreceipt '.closed == null and .pushed_sha == null and .pending.board.status == "done"' \
  && [ ! -s "$D/gh.calls" ] && [ ! -s "$D/cards" ]; } \
  && ok "P21: the existing local workspace exception records done and a pending board write" || bad "P21: $(cat "$D/out" "$D/err")"
rm "$D/board.fail"; rundone
{ [ "$rc" = 0 ] && hasreceipt '.closed == null and .pending == {}'; } \
  && ok "P21 control: retry settles the non-PR delivery without inventing a pushed SHA" || bad "P21 control: $(cat "$D/out" "$D/err")"
# …and the row stays DISPATCHABLE. A workspace project's branch delivery is its ordinary ending, not the end of the
# task: closing it left the next `--go` refused, with nowhere to go but `cc rm`, which deletes the very branch that
# ending called the delivery. This is the claim `--go` takes for itself — no tmux, no model.
tid2=$(jq -r .task_id < "$st/delivery.json")
"$D/bin/cc" claim r "$row" --executor worker > "$D/claim2" 2>&1; c2=$?
{ [ "$c2" = 0 ] && [ "$(jq -r .claim.generation < "$st/delivery.json")" -gt 1 ] \
  && [ "$(jq -r .task_id < "$D/claim2")" = "$tid2" ]; } \
  && ok "P21 dispatch: a delivery with no PR leaves the row claimable, so the next dispatch runs — on the next generation of the same task" \
  || bad "P21 dispatch: rc=$c2 $(cat "$D/claim2")"
# P23: A HOST REPO WITH NO REMOTE ends the same way (raised-done-no-remote): a benchmark's hb-N is local git, and
# `cc done` used to stop it at done_fail "no remote — no PR opened", leaving the row blocked for the pulse to wake a
# seat over. Its committed branch is the delivery. The workspace marker goes first, so this is the host's own path.
rm -f "$HOME/dev/r/.cc/member-workspace"; newdone hostlocal; rundone
{ [ "$rc" = 0 ] && hasreceipt '.closed == null and .pending == {} and .pr_url == null and .pushed_sha == null and .committed_sha != null and .errors == []' \
  && [ ! -s "$D/gh.calls" ] && [ ! -s "$D/cards" ] && [ ! -s "$D/creates" ] && [ "$("$B/cc-board" get r "$row" status)" = done ] \
  && [ "$(git -C "$HOME/dev/r" rev-parse "track/$row")" = "$(jq -r .committed_sha "$D/out")" ]; } \
  && ok "P23: a host repo with no remote finishes done on its committed branch — no PR, no card, no error" || bad "P23: rc=$rc $(cat "$D/out" "$D/err")"
git -C "$HOME/dev/r" remote add origin "$D/no-such-remote.git"; newdone hostpush; rundone   # a remote that is there and cannot take the push
{ [ "$rc" != 0 ] && hasreceipt '.errors[0].stage == "push"' && [ "$("$B/cc-board" get r "$row" status)" != done ]; } \
  && ok "P23 control: the same host repo WITH a remote whose push fails still fails, and is not called done" || bad "P23 control: rc=$rc $(cat "$D/out" "$D/err")"
printf '%s %s\n' "$pass" "$fail" > "$D/counts"
)
read -r m2pass m2fail < "$T/done-fixture/counts"; pass=$((pass+m2pass)); fail=$((fail+m2fail))
# M2 completion fixtures end.
# P8: THE STANDING GRANT, and where it may NOT be spent. A project CC_SELF_LAND_EXCEPT (~/.cc/config) does not name
# does not wait for a 👍 — but `cc done` never queues the landing itself, however granted the repo is: a worker and a
# member-facing session are both told to run that command, and a queue behind it would be the merge cc-guard denies
# them wearing another name. The queue is cc-loop's (P9 below), and all `cc done` does is say who lands this one and
# hand over the card. `SLACK_BOT_TOKEN=` pins the real door: this is the first cc done case whose gh stub returns a
# URL, so it is the first that could reach #approvals with a fixture PR.
mkdir -p "$T/ghbin8"
printf '#!/usr/bin/env bash\ncase "$*" in *"pr create"*) echo "https://github.com/x/y/pull/77";; esac\nexit 0\n' > "$T/ghbin8/gh"
printf '#!/bin/sh\necho "$*" >> "%s/land.calls"\necho "[x] PR #77 queued"\n' "$T" > "$T/landstub"
chmod +x "$T/ghbin8/gh" "$T/landstub"; : > "$T/land.calls"
"$B/cc" $REPO w18 >/dev/null 2>&1; sleep 1
for id in $(wins "$REPO/w18"); do tmux kill-window -t "$id"; done
echo "the grant" > ~/.cc/worktrees/$REPO/w18/g.txt
done8(){ env SLACK_BOT_TOKEN= CC_LAND="$T/landstub" PATH="$T/ghbin8:$PATH" "$@" "$B/cc" done $REPO w18 2>&1; }
o8a=$(done8)
{ [ ! -s "$T/land.calls" ] && grep -q 'land it with:  cc-land' <<<"$o8a"; } \
  && ok "cc done: a repo named as an exception waits for a 👍, and it says how to land it (P8a)" \
  || bad "cc done on an ungranted repo: $(cat "$T/land.calls") $o8a"
o8b=$(done8 CC_SELF_LAND_EXCEPT="other")
{ [ ! -s "$T/land.calls" ] && grep -q "lands its own PRs" <<<"$o8b" && grep -q "the loop queues PR #77" <<<"$o8b"; } \
  && ok "cc done: even for a repo that holds the grant, cc done queues nothing — it names the loop as what lands it, so the one command a worker is told to run is not a way round the merge gate (P8b)" \
  || bad "cc done queued a landing itself: $(cat "$T/land.calls") $o8b"
mkdir -p ~/dev/$REPO/.cc; touch ~/dev/$REPO/.cc/member-facing
o8c=$(done8 CC_SELF_LAND_EXCEPT=); rm -f ~/dev/$REPO/.cc/member-facing
{ [ ! -s "$T/land.calls" ] && grep -q 'land it with:  cc-land' <<<"$o8c" && ! grep -q 'lands its own PRs' <<<"$o8c"; } \
  && ok "cc done: a MEMBER-FACING repo nobody listed holds no grant — it waits for a 👍 and says how to land it, like any exception (P8c; P8b is its control)" \
  || bad "cc done on a member-facing repo: $(cat "$T/land.calls") $o8c"
# P8d: the rest of the table, `self_lands` lifted out of `cc` and run over a ~/dev of its own — NOT through `cc done`:
# marking this suite's fixture a member WORKSPACE would send cc-checkpoint down pick_remote's workspace path, where a
# project with no repository has one CREATED for it against this box's real GitHub App. A fixture must never reach
# that. 1 = named as an exception, or member-facing · 0 = granted · 2 = a workspace with no token.
mkdir -p "$T/dev8/ws/.cc" "$T/dev8/mf/.cc" "$T/dev8/proj"
touch "$T/dev8/ws/.cc/member-workspace" "$T/dev8/mf/.cc/member-facing"
sl8(){ ( export DEV="$T/dev8" BIN="$B" HOME="$T/dev8" CC_SELF_LAND_EXCEPT="$1"
         eval "$(sed -n '/^member_facing()/p;/^member_workspace()/p;/^self_lands(){/,/^}/p' "$B/cc")"
         self_lands "$2" ); echo $?; }
{ [ "$(sl8 'a b' proj)" = 0 ] && [ "$(sl8 '' proj)" = 0 ] && [ "$(sl8 'a proj b' proj)" = 1 ] \
  && [ "$(sl8 '' ws)" = 2 ] && [ "$(sl8 '' mf)" = 1 ] && [ "$(sl8 ws ws)" = 1 ] && [ "$(sl8 mf mf)" = 1 ]; } \
  && ok "cc self_lands: every repo holds the grant unless CC_SELF_LAND_EXCEPT names it (an empty list excepts nothing), a named one and a member-facing one ask, and an unnamed member workspace with no token gets a word of its own — nothing can land for it (P8d)" \
  || bad "self_lands table: unlisted=$(sl8 'a b' proj) empty=$(sl8 '' proj) listed=$(sl8 'a proj b' proj) ws=$(sl8 '' ws) mf=$(sl8 '' mf) ws-listed=$(sl8 ws ws) mf-listed=$(sl8 mf mf)"
r8u=$(CC_SELF_LAND_EXCEPT="$REPO" "$B/cc" lands $REPO >/dev/null 2>&1; echo $?)
r8g=$(CC_SELF_LAND_EXCEPT= "$B/cc" lands $REPO >/dev/null 2>&1; echo $?)
{ [ "$r8u" = 1 ] && [ "$r8g" = 0 ]; } \
  && ok "cc lands <repo> is the grant test and only the test: it answers with its exit code, queues nothing and writes nothing, which is why cc-loop may ask it (P8e)" \
  || bad "cc lands: ungranted=$r8u granted=$r8g"
# P8f: a PR touching a PROTECTED PATH holds even where the repo holds the grant — cc-land queue refuses
# to queue it, and only the owner's own 👍 does (PR #551, 2026-09-19: the card said "the loop queues PR #551 …
# nothing waits on a 👍" and nothing did, because it touched learn-fetch/). `cc done` now asks cc-land's OWN
# protected_hit before saying that, rather than reading CC_PROTECTED_PATHS a second time.
printf '#!/usr/bin/env bash\ncase "$*" in *"pr create"*) echo "https://github.com/x/y/pull/77";; *"pr view 77 --json files"*) echo {\\"files\\":[{\\"path\\":\\"learn-fetch/foo.py\\"}]};; esac\nexit 0\n' > "$T/ghbin8/gh"
o8f=$(done8 CC_SELF_LAND_EXCEPT= CC_PROTECTED_PATHS_"$REPO"=learn-fetch/)
{ [ ! -s "$T/land.calls" ] && grep -q "learn-fetch/foo.py" <<<"$o8f" && grep -q "PROTECTED path" <<<"$o8f" \
  && grep -q "owner's own 👍 on the 🔐 card in #approvals" <<<"$o8f" && ! grep -q "this card" <<<"$o8f" \
  && ! grep -q "nothing waits on a 👍" <<<"$o8f"; } \
  && ok "cc done: a PR touching a PROTECTED path is never said to be queued by the grant — it names the 🔐 card in #approvals as the door, never the PR card (a 👍 there does nothing) and never 'nothing waits on a 👍' (P8f)" \
  || bad "cc done on a protected-path PR: $(cat "$T/land.calls") $o8f"
printf '#!/usr/bin/env bash\ncase "$*" in *"pr create"*) echo "https://github.com/x/y/pull/77";; esac\nexit 0\n' > "$T/ghbin8/gh"   # the plain stub again, for whatever reuses ghbin8 next
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
wait $lp 2>/dev/null
# H4b: …and from a launcher that IGNORES HUP — a `setsid nohup cc-loop` typed out of a session shell, the shape of the
# relaunch-orphans incident. exec keeps SIG_IGN and bash cannot trap a signal ignored at entry, so the loop's HUP trap was a
# no-op and its claude lived on. cc-loop puts its signals back to default at launch, before that trap is set.
( trap '' HUP; exec env CC_CLAUDE="$T/sleepclaude" "$B/cc-loop" $REPO w3 --max-iter 1 --quiet ) >/dev/null 2>&1 & lp=$!
for _ in $(seq 1 10); do pgrep -f "$T/sleepclaude" >/dev/null && break; sleep 1; done
kill -HUP $lp 2>/dev/null; gone=no
for _ in $(seq 1 5); do sleep 1; pgrep -f "$T/sleepclaude" >/dev/null || { gone=yes; break; }; done
[ "$gone" = yes ] && ok "…and from a launcher that ignores HUP (setsid nohup out of a session shell): the loop resets its signals at launch, so the kill still takes its claude" || { bad "HUP-ignoring launcher: the loop kept SIG_IGN and its claude survived (relaunch orphans)"; pkill -f "$T/sleepclaude"; kill -TERM $lp 2>/dev/null; }
wait $lp 2>/dev/null; "$B/cc" rm $REPO w3 >/dev/null 2>&1
fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
