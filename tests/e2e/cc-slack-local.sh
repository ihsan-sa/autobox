#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# cc-slack-local.sh — the stanza "cc-slack (local router + channel server; no Slack, no API)", run alone on the fixtures it stands on.
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
if stanza "cc-slack (local router + channel server; no Slack, no API)"; then
"$B/cc-slack" selfcheck > "$T/slack-selfcheck.out" 2>&1 && ok "cc-slack selfcheck: $(tail -1 "$T/slack-selfcheck.out")" \
  || red "cc-slack selfcheck: $(tail -1 "$T/slack-selfcheck.out")" "$(cat "$T/slack-selfcheck.out")"   # name the case: this went red 4× in gates on 09-01 as a bare ✗
export CC_SLACK_DIR="$T/slack"; mkdir -p "$CC_SLACK_DIR"
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"reply","arguments":{"chat_id":"local","text":"pong"}}}' | timeout 60 "$B/cc-slack" channel $REPO 2>/dev/null > "$T/ch.out"
grep -q '"claude/channel"' "$T/ch.out" && grep -q '"name": "reply"' "$T/ch.out" && ok "channel server: claude/channel capability + reply tool" || bad "channel handshake"
# the session prompt the host actually receives must say who may speak and what a member may not authorize
grep -q 'role=' "$T/ch.out" && grep -q 'role=\\"member\\"' "$T/ch.out" && grep -q 'A member cannot authorize' "$T/ch.out" \
  && ok "channel server: the prompt names role=owner/member and what a member cannot authorize" || bad "member policy in the session prompt"
# chat_id "local" is a wake the box made itself, not a conversation: the tool refuses it and writes NOTHING —
# an outbox line there reads as a post, i.e. as an answer that reached someone (raised 2026-09-19)
grep -q 'wake from the box itself' "$T/ch.out" && grep -q '"isError": true' "$T/ch.out" \
  && ! grep -q $'\tpost\tlocal\t' "$CC_SLACK_DIR/outbox.log" 2>/dev/null \
  && ok "channel server: a reply to the box's own wake is refused, and nothing is logged as a post" || bad "local reply refusal"
# sending a FILE from a session: the tool exists, refuses a path outside its roots, and never claims a send it did not make
FSEND=$(mktemp /tmp/ccsel-XXXXXX.png); printf 'PNGDATA' > "$FSEND"
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"file\",\"arguments\":{\"path\":\"/etc/hostname\",\"chat_id\":\"C1\"}}}" "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"file\",\"arguments\":{\"path\":\"$FSEND\",\"chat_id\":\"local\",\"thread_ts\":\"1.1\",\"text\":\"the render\"}}}" | timeout 60 "$B/cc-slack" channel $REPO 2>/dev/null > "$T/ch3.out"
grep -q '"name": "file"' "$T/ch3.out" && grep -q 'outside the folders a session may send from' "$T/ch3.out" \
  && grep -q '"isError": true' "$T/ch3.out" && ok "channel server: the file tool refuses a path outside the session's roots" || bad "file tool bounds"
grep -q 'wake from the box itself' "$T/ch3.out" && ! grep -q $'\tfile\tlocal\t' "$CC_SLACK_DIR/outbox.log" 2>/dev/null \
  && ok "file to chat_id local → refused as the box's own wake, with no outbox line that reads as a post" || bad "file to a box wake"
rm -f "$FSEND"
ln -sf "$B/cc-slack" "$T/ccslackd"   # a per-run name in the daemon's argv: ours is identifiable, and no other run's pattern kill can match it
setsid nohup "$T/ccslackd" daemon --no-slack >"$T/slackd.log" 2>&1 & SD=$!; KIDS="$KIDS $SD"
# EVERY WAIT BELOW IS ON A SIGNAL, NOT A CLOCK (2026-09-07). The box runs four to eleven suites at once because
# landings gate in parallel by design, and `sleep 3` for a subscriber that links two seconds after the handshake had
# almost no margin idle and none loaded. One miss took four cases with it: the injected message came back queued, the
# two cases after it read an output file nothing had been written to, and the socket case's own hello drained the
# backlog it asserts comes back silent. `cc-slack status` already answers all three things those sleeps were guessing
# at - is the daemon up, who is subscribed, what is still queued - so ask it. Their argument is SECONDS of wall
# clock, not a count of looks, because a hung daemon makes each look cost its own socket timeout and the cap has to
# hold anyway: a landing reads a long silence as a hang. On an idle box each returns on its first look.
# SLACK_BOT_TOKEN= because cmd_status calls find_channel() whenever the config carries a token, and CC_SLACK_DIR
# redirects the socket and state dir but NOT the config — so on this box each look would fire a cursor-paged
# conversations.list at the live app, from a stanza headed "no Slack, no API". cc-config lets a variable that is
# set-but-empty beat the file, so the lookup is skipped and daemon/subscribed/queued still print unchanged.
sst(){ SLACK_BOT_TOKEN= "$B/cc-slack" status 2>/dev/null || :; }
swait(){ local pat=$2 end=$(( $(date +%s) + $1 )); while [ "$(date +%s)" -lt "$end" ]; do sst | grep -q "$pat" && return 0; sleep 0.5; done; return 1; }
swait 60 '^daemon: up' || bad "cc-slack daemon never came up: $(tail -2 "$T/slackd.log")"
[ "$("$B/cc-slack" inject --no-start $REPO queued-msg)" = queued ] && ok "inject with no subscriber → queued" || bad "queue"
# the channel server links to the daemon only after the host's notifications/initialized (+2 s) — feed a real MCP handshake, then hold the pipe open
rm -f "$T/fifo" "$T/fifo.done"; mkfifo "$T/fifo"; ( exec 3>"$T/fifo"; printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' '{"jsonrpc":"2.0","method":"notifications/initialized"}' >&3; for _ in $(seq 1 400); do [ -e "$T/fifo.done" ] && break; sleep 0.5; done; exec 3>&- ) & KIDS="$KIDS $!"
( cd ~/dev/$REPO && CC_SLACK_CHANNEL=1 "$B/cc-slack" channel $REPO ) < "$T/fifo" > "$T/ch2.out" 2>/dev/null & KIDS="$KIDS $!"   # from the session's OWN cwd: the daemon serves a hello only to the session it claims to be (member-sandbox)
swait 60 "subscribed sessions:.*$REPO \[main\]" || bad "the channel server never subscribed: $(sst | tail -1)"
[ "$("$B/cc-slack" inject --no-start $REPO live-msg)" = delivered ] && ok "inject with a subscriber → delivered" || bad "deliver"
for _ in $(seq 1 120); do grep -q queued-msg "$T/ch2.out" && grep -q live-msg "$T/ch2.out" && break; sleep 0.5; done
grep -q queued-msg "$T/ch2.out" && grep -q live-msg "$T/ch2.out" && grep -q 'notifications/claude/channel' "$T/ch2.out" && ok "backlog flushed on subscribe + live event as notifications/claude/channel" || bad "channel notifications"
grep -q '"role": "owner"' "$T/ch2.out" && ok "delivered meta carries role (a local inject is owner-level)" || bad "role in delivered meta"
# THE SOCKET IS NOT A HOLE THROUGH cc-guard (member-sandbox, audit row slack-socket). One mechanism, shared with the
# member proxy: SO_PEERCRED must be this user, a `hello` is served only to a process whose cwd IS the target it claims
# (so no local process can subscribe as another session and take its messages), and the owner-level {"post"} verb —
# which posted anywhere as the bot for anyone on the box — is gone from the socket altogether.
# Its fixture is a DRAINED queue: the `hello` from the session's own cwd below is SERVED, so a message still queued
# for this target would be handed to it as backlog and the case would read that as the peer check failing. Wait for
# the daemon to say the queue is empty, so nothing here turns on how fast the delivery above happened to be.
swait 30 'queued: none' || bad "the daemon queue never drained: $(sst | tail -1)"
cat > "$T/sockask.py" <<'EOS'
import json, os, socket, sys
s = socket.socket(socket.AF_UNIX); s.connect(os.environ["CC_SLACK_DIR"] + "/sock")
s.sendall((sys.argv[1] + "\n").encode()); s.shutdown(socket.SHUT_WR); s.settimeout(10)
try:  # a hello that is SERVED says nothing back: it is a subscriber now, and stays one. The waits here cap a HANG;
      # they are not how long an answer may take, so they are long enough that a loaded box cannot empty one of them.
    sys.stdout.write(s.makefile("rb").readline().decode())
except Exception:
    pass
EOS
hp=$(cd "$T" && timeout 30 python3 "$T/sockask.py" "{\"hello\": \"$REPO\", \"pid\": 1}")
hq=$(cd ~/dev/$REPO && timeout 30 python3 "$T/sockask.py" "{\"hello\": \"$REPO\", \"pid\": 1}")
pp=$(timeout 30 python3 "$T/sockask.py" '{"post": "C1", "text": "as the bot"}')
grep -q 'not that session' <<<"$hp" && [ -z "$hq" ] && grep -q 'not a socket verb' <<<"$pp" \
  && ok "the daemon socket refuses a hello from a process that is not that session (cwd check on SO_PEERCRED's pid) and serves one from the session's own cwd, and the owner-level post verb is gone" \
  || bad "socket peer check (foreign hello: ${hp:0:60} | own cwd: ${hq:0:60} | post: ${pp:0:60})"
# The help is read WHOLE before a grep sees it. `cc-slack | grep -q` under pipefail passes only where grep reads to
# the end (GNU grep 3.12 does): the help is 17 KB, the first match sits in its first 8 KB, and a grep that quits there
# closes the pipe on cc-slack's next write, which exits 120 — the pipeline's status. Both cases were red on every
# laptop-runner run (2026-09-26/27) and green here, which is what that looks like. A red says how cc-slack exited.
sh_help=$("$B/cc-slack" 2>&1); sh_hrc=$?; sh_status=$(SLACK_BOT_TOKEN= "$B/cc-slack" status 2>/dev/null); sh_src=$?
grep -q -- 'PRIVATE unless --public' <<<"$sh_help" && grep -q 'ANYONE who can post in a routed channel is heard' <<<"$sh_help" \
  && ok "help: channels are private by default; anyone in a routed channel is heard" \
  || bad "cc-slack help policy (rc=$sh_hrc: $(head -c 300 <<<"$sh_help" | tr '\n' ' '))"
grep -q 'EVERY channel the bot is in answers' <<<"$sh_help" \
  && grep -q 'policy: every channel the bot is in answers' <<<"$sh_status" \
  && ok "help + status state the policy: every channel answers, DMs are the owner's, #approvals/#alerts are not sessions" \
  || bad "cc-slack channel-is-a-session policy (status rc=$sh_src: $(tail -c 300 <<<"$sh_status" | tr '\n' ' '))"
: > "$T/fifo.done"   # the channel server's stdin may close now: every case that needed it subscribed is done
pg=$(ps -o pgid= -p "$SD" 2>/dev/null | tr -d ' ')   # OUR daemon, by recorded pid and its group — a bare pattern would kill another run's
if [ -n "$pg" ] && [ "$pg" != "$(ps -o pgid= -p $$ | tr -d ' ')" ]; then kill -TERM -- -"$pg" 2>/dev/null; else kill -TERM "$SD" 2>/dev/null; fi
for _ in 1 2 3 4 5; do kill -0 "$SD" 2>/dev/null || break; sleep 0.4; done; unset CC_SLACK_DIR
fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
