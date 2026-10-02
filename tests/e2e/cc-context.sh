#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# cc-context.sh — the stanza "cc-context (the real number, and what refuses to run without it)", run alone on the fixtures it stands on.
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
# ── the stanza
if stanza "cc-context (the real number, and what refuses to run without it)"; then
chk cc-context
chk cc-statusline   # the harness's own per-turn file cc-context prefers over its transcript estimate
chk cc-sandbox   # real bwrap on a scratch repo: secrets and sockets absent inside, git whole, off = untouched
"$B/cc-context" $REPO w1 2>&1 | grep -q '^10%  20k/200k' && ok "a track's number is read off the session the board names" || bad "cc-context $REPO w1: $("$B/cc-context" $REPO w1 2>&1) (fixture sid $sid, board sid $("$B/cc-board" get $REPO w1 session_id))"
"$B/cc-context" $REPO w1 --over 90 >/dev/null 2>&1; rc=$?; [ $rc = 1 ] && ok "--over N at 10% says under, exit 1" || bad "--over 90 at 10%: rc=$rc"
"$B/cc-context" $REPO w1 --over >/dev/null 2>&1; rc=$?; [ $rc = 1 ] && ok "a bare --over reads the hand-off line: 20k is under it" || bad "bare --over: rc=$rc"
mv "$PD/$sid.jsonl" "$T/tx.jsonl"                  # nothing measurable: the answer is 'no', not a guess
out=$("$B/cc-context" $REPO w1 --over 90 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q 'no transcript' <<<"$out"; } && ok "an unmeasurable context is exit 2, never a guess" || bad "unmeasurable: rc=$rc $out"
mv "$T/tx.jsonl" "$PD/$sid.jsonl"
# the harness's own number wins while it is fresh: a status-line file for w1's session, past the 150k line
printf '{"session_id":"%s","used":180000,"window":1000000,"pct":18,"model":"claude-opus-5","raw":{"cwd":"%s"}}' "$sid" ~/.cc/worktrees/$REPO/w1 > "$CC_STATUSLINE_DIR/$sid.json"
out=$("$B/cc-context" $REPO w1 2>&1)
{ grep -q '^18%  180k/1M' <<<"$out" && grep -q 'window from statusline' <<<"$out" && grep -q 'hand off' <<<"$out"; } \
  && ok "a fresh status-line file is the number, and past the line it says hand off" || bad "statusline: $out"
"$B/cc-context" $REPO w1 --over >/dev/null 2>&1; rc=$?; [ $rc = 0 ] && ok "...and a bare --over exits 0 past the line" || bad "bare --over past the line: rc=$rc"
"$B/cc-context" --all 2>/dev/null | grep -q "^$REPO	w1	18	180000	1000000	statusline	[0-9]*	handoff	-$" \
  && ok "--all names the track off the file's cwd, nine columns" || bad "--all: $("$B/cc-context" --all 2>&1)"
lsout=$("$B/cc" ls 2>/dev/null); grep -q "w1.*ctx 18% handoff!" <<<"$lsout" && ok "cc ls shows how full each track is" || bad "cc ls has no ctx column: $lsout"
rm -f "$CC_STATUSLINE_DIR/$sid.json"
# A HEADLESS WORKER DRAWS NO STATUS LINE. `claude -p` — every `--go` track — writes no status-line file at all, so
# --all built from that directory alone listed no worker: `cc ls`'s ctx column and the dashboard's Context block
# were blank for exactly the sessions nobody is watching. With none there, the track's own transcript is the number.
hsl=~/.claude/projects/$(readlink -f ~/.cc/worktrees/$REPO/w1 | tr '/.' '-'); mkdir -p "$hsl"; cp "$PD/$sid.jsonl" "$hsl/$sid.jsonl"
"$B/cc-context" --all 2>/dev/null | grep -q "^$REPO	w1	10	20010	200000	transcript	[0-9]*	-	-$" \
  && ok "a track with no status-line file is still listed, off its transcript" || bad "--all fallback: $("$B/cc-context" --all 2>&1 | grep "	w1	")"
rm -rf "$hsl"
# the Stop hook: UNDER the hand-off line it commits and answers nothing
echo ctx > ~/.cc/worktrees/$REPO/w1/ctx.txt
d0=$(printf '{"session_id":"%s","transcript_path":"%s","cwd":"%s"}' "$sid" "$PD/$sid.jsonl" ~/.cc/worktrees/$REPO/w1 \
  | ( cd ~/.cc/worktrees/$REPO/w1 && "$B/cc-checkpoint" ))
{ [ -z "$d0" ] && [ -z "$(git -C ~/.cc/worktrees/$REPO/w1 status --porcelain)" ]; } \
  && ok "given a Stop payload the hook commits and says nothing on stdout" || bad "the hook said: [$d0] / dirty: $(git -C ~/.cc/worktrees/$REPO/w1 status --porcelain)"
echo more > ~/.cc/worktrees/$REPO/w1/ctx2.txt
( cd ~/.cc/worktrees/$REPO/w1 && "$B/cc-checkpoint" </dev/null )   # no payload (run by hand): still commits
[ -z "$(git -C ~/.cc/worktrees/$REPO/w1 status --porcelain)" ] && ok "the hook still commits when it is given no payload" || bad "checkpoint broke without a Stop payload"
# …and PAST the line it says one thing: write the journal entry. The commit first, the ask after — so the work is
# on the branch before the turn is interrupted. On the real cc-context, measuring a transcript of 180k.
echo ctx3 > ~/.cc/worktrees/$REPO/w1/ctx3.txt
printf '{"type":"assistant","message":{"model":"claude-opus-5","usage":{"input_tokens":10,"cache_creation_input_tokens":1000,"cache_read_input_tokens":179000,"output_tokens":5}}}\n' > "$PD/$sid-full.jsonl"
d1=$(printf '{"session_id":"%s","transcript_path":"%s","cwd":"%s"}' "$sid-full" "$PD/$sid-full.jsonl" ~/.cc/worktrees/$REPO/w1 \
  | ( cd ~/.cc/worktrees/$REPO/w1 && "$B/cc-checkpoint" ))
{ grep -q '"decision": "block"' <<<"$d1" && grep -q 'Append a dated entry' <<<"$d1" \
  && [ -z "$(git -C ~/.cc/worktrees/$REPO/w1 status --porcelain)" ]; } \
  && ok "past the hand-off line the hook commits and THEN asks the session for its journal entry" || bad "past the line the hook said: [$d1] / dirty: $(git -C ~/.cc/worktrees/$REPO/w1 status --porcelain)"
rm -f "$PD/$sid-full.jsonl"
fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
