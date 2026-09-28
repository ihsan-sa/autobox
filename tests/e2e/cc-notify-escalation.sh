#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# cc-notify-escalation.sh — the stanza "cc-notify: an escalation reaches the PLANNING SEAT, not the owner and not the channel it came from", run alone on the fixtures it stands on.
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
if stanza "cc-notify: an escalation reaches the PLANNING SEAT, not the owner and not the channel it came from"; then
# own HOME (the box's real config and owner id stay out of this) + a stub bot and a stub broker: the args cc-notify hands
# cc-slack ARE the routing, and the args it hands cc-broker are the request (core/docs/comms-contract.md: a member-facing
# session asks the seat; only the control seat asks the owner)
NH="$T/nh"; mkdir -p "$NH/bin" "$NH/.cc" "$T/chan/.cc" "$T/plain"; : > "$T/chan/.cc/member-facing"
cat > "$NH/bin/cc-slack" <<F
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$T/slack.args"
F
cat > "$NH/bin/cc-broker" <<F
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$T/broker.args"
F
chmod +x "$NH/bin/cc-slack" "$NH/bin/cc-broker"; printf 'SLACK_BOT_TOKEN=xoxb-test\nSLACK_OWNER_ID=UOWNER\n' > "$NH/.cc/config"
# -u for every config key: the environment now WINS over the file (cc-config's one rule), so a key exported by
# whatever session is running this would beat the fixture's own config below.
N(){ w=$1; shift; : > "$T/slack.args"; : > "$T/broker.args"
     ( cd "$w" && env -u CC_NOTIFY_LOG_ONLY -u CC_MEMBER_SANDBOX -u CC_ROLE -u SLACK_BOT_TOKEN -u SLACK_OWNER_ID -u SLACK_WEBHOOK -u SLACK_ALERTS \
           -u NTFY_TOPIC -u NTFY_SERVER -u CC_BOX HOME="$NH" CC_NOTIFY_LOG="$NH/.cc/notify.log" "$B/cc-notify" "$@" >/dev/null 2>&1 ); }
N "$T/chan" "Alice needs the staging DB restored"
{ ! grep -q -- '-c UOWNER' "$T/slack.args" && ! grep -q -- '--route' "$T/slack.args" && grep -q -- '^inject --source request .* from chan: ' "$T/broker.args"; } \
  && ok "a member-facing session's escalation is a REQUEST to the planning seat (the broker), never the owner's DM and never its own channel" || bad "escalation went to Slack: $(cat "$T/slack.args") / broker: $(cat "$T/broker.args")"
grep -q 'chan escalation' "$T/broker.args" && ok "it says where it came from (default title '<session dir> escalation')" || bad "escalation title: $(head -1 "$T/broker.args")"
[ "$(ls "$NH/.cc/requests"/*.json 2>/dev/null | wc -l)" = 1 ] && [ "$(jq -r .from "$NH"/.cc/requests/*.json)" = chan ] \
  && ok "…and the request is on file first, naming the workspace the marker names — the file is the request, the broker its transport" || bad "request file: $(ls "$NH/.cc/requests" 2>&1)"
N "$T/plain" --owner "the disk is filling up"
grep -q -- '-c UOWNER' "$T/slack.args" && ok "--owner from the control seat (no marker, no daemon seat claiming the process) is his DM" || bad "--owner ignored: $(cat "$T/slack.args")"
N "$T/plain" -t "demorepo/w1 done" "PR: x"     # a REAL repo name: this fixture's own is _cctest…, which the gate below stops on purpose
{ grep -q -- "--route demorepo/w1 done" "$T/slack.args" && ! grep -q -- '-c ' "$T/slack.args"; } \
  && ok "no regression: an ordinary notice still routes by title (#<repo>, #alerts)" || bad "routing changed: $(cat "$T/slack.args")"
# THE LADDER (owner, 2026-09-01): the rung is a routing decision, and --decision is the only thing that buys rung 1.
! grep -q -- '--mention' "$T/slack.args" \
  && ok "...and it is ambient — no --mention, so cc-slack aims it at the #<repo>-updates lane (rung 5)" || bad "an ordinary notice @-mentioned the owner: $(cat "$T/slack.args")"
N "$T/plain" --decision -t "demorepo blocked" "which database do I restore?"
{ grep -q -- '--mention' "$T/slack.args" && grep -q -- '--route demorepo blocked' "$T/slack.args"; } \
  && ok "--decision is rung 1: same route, plus --mention — the MAIN channel and a real @-mention of the owner" || bad "--decision did not ask for a mention: $(cat "$T/slack.args")"
# …and the member's own words are a MESSAGE, never flags: the daemon relays them after `--`, so a member who writes
# "--decision" is escalating that text, not buying rung 1 — and not silently sending an empty one either.
N "$T/plain" --owner -- --decision
{ grep -q -- '-c UOWNER' "$T/slack.args" && grep -q -- '--decision' "$T/slack.args" && ! grep -q -- '--mention' "$T/slack.args"; } \
  && ok "after --, a message that looks like a flag is the message — text somebody else wrote cannot become an option" \
  || bad "-- did not end the options: $(cat "$T/slack.args")"
N "$T/chan" --decision "the staging DB restore needs your call"
{ ! grep -q -- '-c UOWNER' "$T/slack.args" && ! grep -q -- '--mention' "$T/slack.args" && grep -q -- '^inject --source request ' "$T/broker.args"; } \
  && ok "--decision from a member-facing session is that same request — a flag is not authority; only the control seat asks the owner" || bad "--decision from a member-facing session reached Slack: $(cat "$T/slack.args")"
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
{ [ ! -s "$T/slack.args" ] && grep -q -- '^inject --source request ' "$T/broker.args"; } \
  && ok "unpaired owner: the escalation is the seat's request just the same — no owner id is needed to ask the seat, and nothing goes to #alerts or the member channel" || bad "unpaired escalation: $(cat "$T/slack.args")"
rm -f "$NH/bin/cc-broker"; N "$T/chan" "Carol asks for a repo"
{ [ ! -s "$T/slack.args" ] && [ "$(jq -r 'select(.delivered==false) | .id' "$NH"/.cc/requests/*.json | wc -l)" = 1 ]; } \
  && ok "…and with no broker to take it the request stays on file, delivered=false, for cc-notify requests --retry — not dropped, and not dumped on the owner instead" || bad "undelivered request: slack='$(cat "$T/slack.args")' files=$(ls "$NH/.cc/requests" 2>&1)"
# INSIDE A MEMBER WORKSPACE'S BOUNDARY (cc-sandbox member) ~/.cc/config is ABSENT, so every rung above is unconfigured:
# `tried` stayed 0 and this exited 0 having written a tmpfs log and reached NOBODY — a blocked member told its
# escalation worked. The one door out is the workspace's own socket; the daemon holds the token and makes the call.
rm -f "$NH/.cc/config"
M(){ : > "$T/slack.args"
     ( cd "$T/chan" && env -u CC_NOTIFY_LOG_ONLY -u SLACK_BOT_TOKEN -u SLACK_OWNER_ID -u SLACK_WEBHOOK -u SLACK_ALERTS \
           -u NTFY_TOPIC -u NTFY_SERVER -u CC_BOX CC_MEMBER_SANDBOX=1 HOME="$NH" \
           CC_NOTIFY_LOG="$NH/.cc/notify.log" "$B/cc-notify" "$@" >/dev/null 2>&1 ); }
M -p high -t "alice help" "I am blocked and need the owner"; mrc=$?
{ [ "$mrc" = 0 ] && grep -qx 'escalate -t alice help' "$T/slack.args"; } \
  && ok "inside a member boundary the escalation goes out over the workspace's socket (cc-slack escalate) — the config it cannot see is not the route, and the caller's -p does not travel with it: the table decides that outside the boundary" \
  || bad "in-boundary escalation: rc=$mrc args=$(cat "$T/slack.args")"
printf '#!/usr/bin/env bash\nexit 1\n' > "$NH/bin/cc-slack"; chmod +x "$NH/bin/cc-slack"
M -t "alice help" "nobody is listening"; mrc=$?
[ "$mrc" != 0 ] \
  && ok "…and when the link does not take it, cc-notify FAILS — exiting 0 having reached nobody is what a blocked member cannot afford" \
  || bad "an escalation that reached nobody still exited 0"
# THE RUNG IS THE TABLE'S, NOT THE CALLER'S — the table itself, the dedup key and which kinds ring his phone, in a
# HOME, a log, a dedup dir and an ntfy of its own: nothing of this box's is read and nothing leaves the machine.
# cc-notify is on tests/check.sh's selfcheck list as well, and runs there too, the same way cc-task, cc-native,
# cc-brief and cc-handoff do — both gates are scoped to the change, so this costs a second on a cc-notify change
# and nothing at all on any other.
chk cc-notify
fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
