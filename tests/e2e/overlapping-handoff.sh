#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# overlapping-handoff.sh — the stanza "overlapping handoff: two sessions, one cwd, exactly one of them live", run alone on the fixtures it stands on.
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
if stanza "overlapping handoff: two sessions, one cwd, exactly one of them live"; then
chk cc-handoff
st=$("$B/cc" handoff --status 2>&1); grep -q "no overlapping handoff is open" <<<"$st" && ok "cc handoff --status delegates by target" || bad "cc handoff --status: [$st]"
# a real predecessor window; the successor's `claude` is /bin/true, so its pane falls through to the wrapper shell
for t in hq hs hw hx hz; do mkdir -p ~/.cc/worktrees/$REPO/$t; done   # the successor's pane IS `cc __runnext` (exec: claude must be the pane's
                                          # direct child for cc-msg), and that cds into the track's worktree or exits
tmux new-window -d -t main -n "$REPO/hx" -c "$T" "bash -c 'sleep 300; :'"   # a real child: `pane_live` is what tells a session from a bare shell
out=$("$B/cc" handoff --overlap "$REPO/hx" --session sid-pre --in-flight "uncommitted work in hx" 2>&1)
hid=$(jq -r .id "$T/handoff/$REPO--hx.json" 2>/dev/null)
{ [ -n "$hid" ] && [ "$(jq -r .live "$T/handoff/$REPO--hx.json")" = predecessor ]; } && ok "the record names the predecessor as live from the first instant" || bad "overlap record: $out"
grep -q "uncommitted work in hx" "$T/handoff/$REPO--hx.brief" 2>/dev/null && ok "the successor's brief carries what is unfinished RIGHT NOW" || bad "successor brief has no in-flight checklist"
tmux list-windows -t main -F '#W' | grep -qx "$REPO/hx~next" && ok "the successor came up ALONGSIDE — the predecessor was not stopped" || bad "no successor window"
# THE SUCCESSOR MUST ACCEPT ITS OWN STARTUP DIALOG. Its window is "<target>~next"; `cc __runnext` knew only
# the target, so it accepted in the PREDECESSOR's window and its own sat on the --dangerously-load-development-
# channels confirmation until a human noticed (2026-09-01 02:10Z; the 2026-08-28 incident, again).
tmux display-message -p -t "$REPO/hx~next" '#{pane_start_command}' 2>/dev/null | grep -q "CC_HANDOFF_WINDOW='$REPO/hx~next'" \
  && ok "the successor is started knowing its OWN window, so it accepts its own dialog and does not park on it" || bad "no CC_HANDOFF_WINDOW on the successor: $(tmux display-message -p -t "$REPO/hx~next" '#{pane_start_command}' 2>&1)"
"$B/cc" handoff --overlap "$REPO/hx" >/dev/null 2>&1 && bad "a second overlap was allowed for one target" || ok "an overlap is refused while one is open — one successor at a time"
# the guard, from BOTH sides of the record. cwd is $T: no marker, so only the record can gate.
h(){ printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s","session_id":"%s"}' "$1" "$T" "${3:-}" | env CC_HANDOFF="${2:-}" "$B/cc-guard" >/dev/null 2>&1; echo $?; }
miss=""; for c in "gh pr merge 1" "git push origin HEAD" "cc r t --go x" "cc done r t" "sudo apt install x"; do
  [ "$(h "$c" "$hid")" = 2 ] || miss="$miss [$c]"; done
[ -z "$miss" ] && ok "the non-live successor is denied merge/push/dispatch/PR/host — by its env, not by a marker" || bad "successor not gated:$miss"
[ "$(h "git log --oneline" "$hid")" = 0 ] && ok "...and may still read, search and think" || bad "successor over-gated"
[ "$(h "gh pr merge 1" "" sid-pre)" = 0 ] && ok "the LIVE predecessor is gated by none of it" || bad "predecessor gated while live"
pp=$(tmux list-panes -t "$(jq -r .predecessor.tmux "$T/handoff/$REPO--hx.json")" -F '#{pane_id}' 2>/dev/null | head -1)
[ "$(TMUX_PANE=$pp h "gh pr merge 1" "" "")" = 0 ] && ok "...nor by its pane while it is live" || bad "predecessor gated by pane while live (pane $pp)"
# THIS cutover drains at the real length, not the stanza's 1 s. --ready detaches a --retire, and at a 1 s drain
# that retirement finished HALF A SECOND later, mid-block: it kills the predecessor's window (so the pane case
# below has no pane left to be gated by) and writes <id>.done (which is precisely what un-gates the successor
# the corrupt-record case asserts is gated). Red on the full tier from 2026-09-06, those two cases and no
# others. This predecessor is ended by the kill-window below instead, never by a clock — and the hz block that
# follows, which is the one testing the retirement itself, keeps the 1 s.
CC_HANDOFF="$hid" CC_HANDOFF_RETIRE_GRACE=120 CC_HANDOFF_DRAIN=600 "$B/cc-handoff" --ready "$REPO/hx" >/dev/null 2>&1
[ "$(jq -r .live "$T/handoff/$REPO--hx.json" 2>/dev/null)" = successor ] && ok "one atomic replace moves ownership — the successor is live" || bad "cutover did not move the record"
{ [ "$(h "gh pr merge 1" "" sid-pre)" = 2 ] && [ "$(h "git push origin HEAD" "" sid-pre)" = 2 ]; } && ok "SYMMETRY: after cutover the retired PREDECESSOR is the gated one (no stale-branch push)" || bad "predecessor not gated after cutover"
[ "$(TMUX_PANE=$pp h "gh pr merge 1" "" "")" = 2 ] && ok "...by its PANE too: a planning predecessor's session_id is empty on the record, and the drain is 10 min" || bad "predecessor with no session_id not gated by pane (pane $pp)"
[ "$(h "gh pr merge 1" "$hid")" = 0 ] && ok "...and the successor, now live, is free" || bad "successor still gated after cutover"
[ "$(h "gh pr merge 1" "no-such-record")" = 2 ] && ok "CC_HANDOFF with no record to justify it stays gated (missing = the predecessor is in charge)" || bad "unbacked CC_HANDOFF ungated"
echo '{not json' > "$T/handoff/$REPO--hx.json"
{ [ "$(h "gh pr merge 1" "" sid-pre)" = 0 ] && [ "$(h "gh pr merge 1" "$hid")" = 2 ]; } && ok "a corrupt record falls one way only: predecessor free, successor gated" || bad "corrupt record fell the wrong way"
rm -f "$T/handoff/$REPO--hx.json"
for id in $(tmux list-windows -t main -F '#{window_id} #W' | awk -v r="$REPO/hx" '$2==r || $2==r"~next"{print $1}'); do tmux kill-window -t "$id"; done
# THE WRAPPER ACCEPTS A SUCCESSOR-BORN SEAT. Its pane is an interactive `claude` whose argv carries its handoff
# brief — which names cc-loop and `claude -p` as a matter of course — with the seat's own grep for cc-loop running
# under it. Read as a worker's window, `cc handoff --overlap lessons` refused a planning seat at 167k while the
# direct `cc-handoff --overlap` went through (2026-09-19; raised-cc-handoff-wrapper-misreads-successor-window).
tmux new-window -d -t main -n "$REPO/hw" -c "$T" "bash -c 'exec -a claude bash -c \"sleep 300 & grep cc-loop <(sleep 300) & wait\" --append-system-prompt \"a worker runs claude -p under cc-loop\"'"; sleep 1
out=$("$B/cc" handoff --overlap "$REPO/hw" --session sid-pre-w 2>&1)
[ -f "$T/handoff/$REPO--hw.json" ] && ok "cc handoff --overlap accepts a seat whose prompt and tool calls name cc-loop and claude -p — a session's own words are not a worker" || bad "the wrapper refused a successor-born seat: $out"
"$B/cc-handoff" --abandon "$REPO/hw" --why fixture >/dev/null 2>&1
tmux new-window -d -t main -n "$REPO/hl" -c "$T" "bash -c 'exec -a cc-loop sleep 300'"; sleep 1
out=$("$B/cc" handoff --overlap "$REPO/hl" 2>&1)
{ grep -q "headless worker" <<<"$out" && [ ! -f "$T/handoff/$REPO--hl.json" ]; } && ok "control: a pane a loop holds is still refused as a headless worker's window" || bad "a loop's window was handed off: $out"
for id in $(tmux list-windows -t main -F '#{window_id} #W' | awk -v r="$REPO" '$2 ~ "^"r"/(hw|hl)(~next)?$"{print $1}'); do tmux kill-window -t "$id"; done
# RETIREMENT ENDS THE PREDECESSOR, end to end on real windows. A session cannot exit itself (`/exit` is typed
# by a human), so the old wait-it-out never completed on its own: on 2026-08-31 a retired session ran on for
# 35 minutes as a second live voice, its window still the ACTIVE one. The grace expires into a kill.
tmux new-window -d -t main -n "$REPO/hz" -c "$T" "bash -c 'sleep 300; :'"
"$B/cc" handoff --overlap "$REPO/hz" --session sid-pre-z >/dev/null 2>&1
hz=$(jq -r .id "$T/handoff/$REPO--hz.json" 2>/dev/null); pz=$(jq -r .predecessor.tmux "$T/handoff/$REPO--hz.json" 2>/dev/null); sz=$(jq -r .successor.tmux "$T/handoff/$REPO--hz.json" 2>/dev/null)
CC_HANDOFF="$hz" "$B/cc-handoff" --ready "$REPO/hz" >/dev/null 2>&1     # --ready fires --retire in the background
for _ in $(seq 60); do [ -f "$T/handoff/$REPO--hz.json" ] || break; sleep 0.5; done
w=$(tmux list-windows -t main -F '#{window_id} #W')
{ ! grep -q "^$pz " <<<"$w"; } && ok "the predecessor is ENDED by the grace, not waited out (it cannot exit itself)" || bad "the predecessor kept its window after --retire"
{ grep -qx "$sz $REPO/hz" <<<"$w" && ! grep -q "$REPO/hz~next" <<<"$w"; } && ok "...and the successor holds its window name, so an owner attaching lands on the live session" || bad "successor window not renamed: $(grep "$REPO/hz" <<<"$w")"
[ ! -f "$T/handoff/$REPO--hz.json" ] && ok "...and the record is cleared, so nothing is gated by it any more" || bad "record survived the retirement"
[ "$(h "cc r t --go x" "$hz")" = 0 ] && ok "TONIGHT'S CASE: a COMPLETED handoff does not brick the session that won it (it still dispatches, PRs and pushes)" || bad "the survivor of a completed handoff is gated"
[ "$(h "cc r t --go x" "no-such-record")" = 2 ] && ok "...while a record missing for any OTHER reason gates exactly as before" || bad "an unbacked CC_HANDOFF was let through"
for id in $(tmux list-windows -t main -F '#{window_id} #W' | awk -v r="$REPO/hz" '$2==r || $2==r"~next" || $2==r"~old"{print $1}'); do tmux kill-window -t "$id"; done

# THE SWEEP, on real windows. Every phase above is driven by a session's own Stop hook — which is exactly what
# a session that CRASHED no longer has. On 2026-08-31 a retirement dying between the marker and the record
# would have left the survivor gated with nothing left to reap it; the cc-reconcile timer is what reaps it now.
tmux new-window -d -t main -n "$REPO/hs" -c "$T" "bash -c 'sleep 300; :'"
"$B/cc" handoff --overlap "$REPO/hs" --session sid-pre-s >/dev/null 2>&1
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
"$B/cc" handoff --overlap "$REPO/hq" --session sid-pre-q >/dev/null 2>&1
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

fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
