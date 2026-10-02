#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# guard.sh — the stanza "guard", run alone on the fixtures it stands on.
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
# ── the stanza
if stanza "guard"; then
g(){ printf '{"tool_name":"%s","tool_input":%s,"cwd":"%s"}' "$1" "$2" "$3" | CC_ROLE=worker "$B/cc-guard" >/dev/null 2>&1; echo $?; }
[ "$(g Bash '{"command":"gh pr merge 1"}' "$wt")" = 2 ] && ok "guard blocks merge in a track (by cwd marker)" || bad "guard merge"
printf '{"tool_name":"Bash","tool_input":{"command":"gh pr merge 1"},"cwd":"%s"}' "$HOME" | "$B/cc-guard" >/dev/null 2>&1; [ $? = 0 ] && ok "guard ignores non-worker cwd" || bad "guard scope"
miss=""   # M9: the bypasses the 2026-08-27 audit walked through
for probe in 'Bash|{"command":"$(gh pr merge 1)"}' 'Bash|{"command":"bash -c \"gh pr merge\""}' 'Bash|{"command":"xargs gh pr merge"}' \
             "Bash|{\"command\":\"rm -r -f $HOME\"}" 'Bash|{"command":"rm -rf /*"}' 'Bash|{"command":"rm -rf \"$HOME/x\""}' \
             'Bash|{"command":"tmux kill-ses -t main"}' 'Bash|{"command":"pkill -f tmux"}' 'Bash|{"command":"systemctl --user restart tmux-main"}' \
             'Bash|{"command":"tmux send-keys -t main \"tmux kill-server\" Enter"}' 'Bash|{"command":"gh api -X DELETE /repos/x/y"}' 'Bash|{"command":"git symbolic-ref HEAD refs/heads/main"}' \
             "Edit|{\"file_path\":\"$wt/../../../../etc/passwd\"}"; do
  [ "$(g "${probe%%|*}" "${probe#*|}" "$wt")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "guard blocks all 13 bypass probes (quoting, wrappers, tmux kills, traversal)" || bad "guard bypass:$miss"
# A HEREDOC BODY IS DATA — except when something on the line would run it, and then it is a command again.
miss=""; for probe in 'Bash|{"command":"bash <<E\ngh pr merge 1\nE"}' 'Bash|{"command":"cat <<E\ngh pr merge 1"}' \
             'Bash|{"command":"ssh box <<E\nsudo reboot\nE"}' 'Bash|{"command":"xargs -0 <<E\ngh pr merge 1\nE"}'; do
  [ "$(g "${probe%%|*}" "${probe#*|}" "$wt")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "a heredoc an interpreter would RUN, and one that never ends, both fail closed" || bad "heredoc bypass:$miss"
miss=""; for probe in 'Bash|{"command":"cat >> notes.md <<E\nthe owner decides: gh pr merge, cc-land, sudo anything\nE"}' \
             'Bash|{"command":"git commit -F - <<E\nfix: stop cc-land running twice\nE"}'; do
  [ "$(g "${probe%%|*}" "${probe#*|}" "$wt")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "...but prose that merely NAMES a gated command is written, not refused (brief, journal, commit message)" || bad "guard reads prose as a command:$miss"
# 5. THE WORKTREE IS THE ONLY TREE A TRACK WRITES (2026-09-01: main's cc-handoff and cc-scope overwritten through a symlink farm into ~/dev/<repo>/core/bin)
ln -s ~/dev/$REPO/r.md "/tmp/cc-selftest-$RUN-lnk"; mkdir -p "$T/farm"; ln -s ~/dev/$REPO/r.md "$T/farm/r.md"   # a /tmp symlink and a scratch "bin" that both point INTO the box's tree
miss=""; for probe in "Write|{\"file_path\":\"$HOME/dev/$REPO/r.md\"}" "Edit|{\"file_path\":\"$HOME/bin/cc-guard\"}" "Write|{\"file_path\":\"/tmp/cc-selftest-$RUN-lnk\"}" \
  "Write|{\"file_path\":\"$HOME/.cc/state/$REPO/w2/task.md\"}" "Bash|{\"command\":\"echo x > ~/dev/$REPO/r.md\"}" "Bash|{\"command\":\"cp core/bin/cc-guard ~/bin/cc-guard\"}" \
  "Bash|{\"command\":\"cat x | tee -a \$HOME/dev/$REPO/r.md\"}" "Bash|{\"command\":\"install -m 755 x $HOME/bin/x\"}" "Bash|{\"command\":\"cp x $T/farm/r.md\"}" \
  "Bash|{\"command\":\"sed -i s/a/b/ ~/dev/$REPO/r.md\"}" "Bash|{\"command\":\"git -C ~/dev/$REPO checkout track/w1 -- r.md\"}" "Bash|{\"command\":\"ln -sf $wt/a.txt ~/bin/a\"}" \
  "Bash|{\"command\":\"cat x|tee -a ~/bin/y\"}" "Bash|{\"command\":\"echo d;cp x ~/bin/y\"}" "Bash|{\"command\":\"(cp x ~/bin/y)\"}" "Bash|{\"command\":\"foo;git -C ~/dev/$REPO checkout .\"}"; do
  [ "$(g "${probe%%|*}" "${probe#*|}" "$wt")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "a worker writes nothing into ~/dev/<repo> or ~/bin — by tool, redirect, cp/tee/install/sed -i/ln/git -C, through a /tmp or scratch symlink that resolves there, unspaced after ;|( too, or into another track's state" || bad "worker write fence misses:$miss"
miss=""; for probe in "Write|{\"file_path\":\"$wt/notes.md\"}" "Write|{\"file_path\":\"/tmp/cc-selftest-$RUN.txt\"}" "Write|{\"file_path\":\"$HOME/.cc/state/$REPO/w1/progress.md\"}" \
  "Bash|{\"command\":\"echo x > /tmp/cc-selftest-$RUN.txt\"}" "Bash|{\"command\":\"cat >> ~/.cc/state/$REPO/w1/progress.md <<E\\ndone\\nE\"}" "Bash|{\"command\":\"cp ~/dev/$REPO/r.md .\"}" \
  "Bash|{\"command\":\"git -C ~/dev/$REPO log -1\"}" "Bash|{\"command\":\"git commit -m \\\"no cp into ~/bin\\\"\"}" "Bash|{\"command\":\"echo x > out.txt 2>&1\"}"; do
  [ "$(g "${probe%%|*}" "${probe#*|}" "$wt")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "...and no wider: its worktree, /tmp, its own state dir, a READ from ~/dev, a git log there, and prose naming the verbs all pass" || bad "worker write fence over-blocks:$miss"
slug=$(printf '%s' "$wt" | tr '/.' '--')   # a worker that cd'd into ~/dev/<repo>: no marker under its cwd, so the transcript path (the dir it started in) anchors the fence
c(){ printf '{"tool_name":"%s","tool_input":%s,"cwd":"%s","transcript_path":"%s"}' "$1" "$2" "$3" "$HOME/.claude/projects/$slug/s.jsonl" | CC_ROLE=worker "$B/cc-guard" >/dev/null 2>&1; echo $?; }
[ "$(c Write "{\"file_path\":\"$HOME/dev/$REPO/r.md\"}" "$HOME/dev/$REPO")" = 2 ] && [ "$(c Bash '{"command":"echo x > r.md"}' "$HOME/dev/$REPO")" = 2 ] && [ "$(c Write "{\"file_path\":\"$wt/x.md\"}" "$HOME/dev/$REPO")" = 0 ] \
  && ok "a worker that cd'd into ~/dev/<repo> is still fenced to its worktree — the transcript path says where it started" || bad "a cd'd worker is fenced by its cwd"
rm -f "/tmp/cc-selftest-$RUN-lnk"
[ "$(printf '{"tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"%s"}' "$wt" | CC_ROLE=worker env PATH=/nonexistent /bin/bash "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] && ok "guard refuses when jq is missing (gates would be silently off)" || bad "guard without jq"
# …while the planning session is the other side of the same line — it is ungated by design, so a broken PATH must
# NOT start refusing its calls. (The steward tier that lived in that env went with cc-steward; a worker is the
# gated role above.)
#   `env -u` first: this suite's own runner may hold a CC_ROLE or a CC_HANDOFF, and either one inherited would
#   make the assertion fail for the wrong reason (both are read by the same `case`).
njq(){ printf '{"tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"%s"}' "$wt" | env -u CC_ROLE -u CC_HANDOFF ${1:+CC_ROLE=$1} PATH=/nonexistent /bin/bash "$B/cc-guard" >/dev/null 2>&1; echo $?; }
[ "$(njq)" = 0 ] && ok "…while an ungated planning session with no jq still runs" || bad "guard without jq: planning=$(njq) (want 0)"
# member-facing: the .cc/member-facing marker alone (NO CC_ROLE — the env is a convenience) = every worker gate plus spend/leak/wiring
# A MEMBER DENY NOW SPEAKS (see below), so every member probe runs against a STUB HOME: a fake ~/bin/cc-slack and
# ~/bin/cc-notify that only record their argv, and a ~/.cc/config with no real token. Nothing in this file may
# reach the workspace, and the secret-path probes are the stub's own files so `secret_path` still matches.
GH="$T/ghome"; mkdir -p "$GH/bin" "$GH/.cc" "$GH/.ssh"; : > "$GH/.cc/config"; : > "$GH/.ssh/id_ed25519"
mkdir -p "$GH/.claude" "$GH/repo/core/ccbox"; : > "$GH/.claude/.credentials.json"     # empty stubs, never a real token
: > "$GH/repo/core/ccbox/env"; : > "$GH/repo/core/ccbox/env.example"; ln -s "$GH/repo/core/ccbox" "$GH/ccbox"   # ~/ccbox IS a symlink on the box
cat > "$GH/bin/cc-slack" <<F
#!/usr/bin/env bash
printf 'BOT: %s\n' "\$*" >> "$T/guard.args"
F
sed 's/BOT:/NOTIFY:/' "$GH/bin/cc-slack" > "$GH/bin/cc-notify"; chmod +x "$GH/bin/cc-slack" "$GH/bin/cc-notify"
mf="$T/member"; mkdir -p "$mf/.cc"; : > "$mf/.cc/member-facing"; touch "$mf/note.md"
m(){ printf '{"tool_name":"%s","tool_input":%s,"cwd":"%s"}' "$1" "$2" "$3" | env HOME="$GH" CC_GUARD_ASKS="$T/asks" "$B/cc-guard" >/dev/null 2>&1; echo $?; }
# STAGE 0 of the worker sandbox (docs/design-worker-sandbox.md §1): the two holes that were member-only are shut
# for a WORKER too. the box user is in group `docker`, so `docker run -v /:/host` is root on the whole filesystem with no
# escalation; ~/.claude/.credentials.json is the box's Claude account and its spend, ~/ccbox/env a GitHub PAT and a
# deploy token. Same stub HOME as the member probes, and no probe reads a real credential — the guard matches the
# PATH (realpath -m resolves one that need not exist), it never opens the file.
w(){ printf '{"tool_name":"%s","tool_input":%s,"cwd":"%s"}' "$1" "$2" "$3" | env HOME="$GH" CC_GUARD_ASKS="$T/asks" CC_ROLE=worker "$B/cc-guard" >/dev/null 2>&1; echo $?; }
WP=('Bash|{"command":"docker run -v /:/host alpine cat /host/etc/shadow"}' 'Bash|{"command":"podman run --rm alpine sh"}'
    'Bash|{"command":"cat ~/.claude/.credentials.json"}' 'Bash|{"command":"jq -r .accessToken $HOME/.claude/.credentials.json"}'
    'Bash|{"command":"grep VERCEL_TOKEN ~/ccbox/env"}' 'Bash|{"command":"source $HOME/ccbox/env"}'
    "Bash|{\"command\":\"cat $GH/repo/core/ccbox/env\"}" 'Bash|{"command":"cat core/ccbox/env"}'
    "Read|{\"file_path\":\"$GH/.claude/.credentials.json\"}" "Read|{\"file_path\":\"$GH/ccbox/env\"}"
    "Read|{\"file_path\":\"$GH/repo/core/ccbox/env\"}")
miss=""; for probe in "${WP[@]}"; do [ "$(w "${probe%%|*}" "${probe#*|}" "$wt")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "a WORKER is denied containers and both credential files — by ~/ path, by real path and through a symlinked ~/ccbox alike" || bad "worker stage-0 gate misses:$miss"
miss=""; for probe in 'Bash|{"command":"ls -la"}' 'Bash|{"command":"git log --oneline -5"}' 'Bash|{"command":"cat ~/.cc/config"}' \
             'Bash|{"command":"cat core/ccbox/env.example"}' "Read|{\"file_path\":\"$GH/repo/core/ccbox/env.example\"}" \
             "Read|{\"file_path\":\"$GH/.cc/config\"}"; do
  [ "$(w "${probe%%|*}" "${probe#*|}" "$wt")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "...and no wider than that: env.example is not a credential, and the box's OTHER secrets stay member-only as before" || bad "worker gate over-blocks:$miss"
[ "$(w Bash '{"command":"systemctl --user list-units"}' "$wt")" = 2 ] \
  && ok "...and a worker's systemctl read is unchanged — denied before stage 0, denied after (the list sorts by spelling, not reach)" || bad "systemctl gate moved under stage 0"
MP=('Bash|{"command":"sudo apt install x"}' 'Bash|{"command":"gh pr merge 1"}' 'Bash|{"command":"cc r t --go build it"}'
    'Bash|{"command":"cc board add r t title text; cc r t --go"}' 'Bash|{"command":"cc-loop r t"}' 'Bash|{"command":"claude -p do it"}'
    'Bash|{"command":"cat ~/.cc/config"}' 'Bash|{"command":"tail -5 $HOME/.ssh/id_ed25519"}'
    'Bash|{"command":"docker run -v /:/host alpine"}' 'Bash|{"command":"cat ~/.claude/.credentials.json"}'
    'Bash|{"command":"head -1 ~/ccbox/env"}'
    'Bash|{"command":"cc slack off"}' 'Bash|{"command":"cc slack mkchannel help"}'
    'Bash|{"command":"cc-slack updates-sweep"}'
    "Read|{\"file_path\":\"$GH/.cc/config\"}" "Edit|{\"file_path\":\"$GH/member-probe.txt\"}")
miss=""; for probe in "${MP[@]}"; do [ "$(m "${probe%%|*}" "${probe#*|}" "$mf")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "member-facing marker denies all 16 probes (merge/host, dispatch, secrets, containers, credentials, Slack wiring incl. updates-sweep, edit outside)" || bad "member gate misses:$miss"
# ...and a session refused mkchannel must be able to get a channel WITHOUT the owner: the working path is the member
# typing `new project <name>` in the workspace channel (cc-slack's daemon makes it). A session that does not know that
# escalates to a person for something the box does by itself — which is what happened at 18:50Z on 2026-09-02.
sp=$(eval "$(sed -n 's/^MEMBER_SP=/x=/p' "$B/cc")"; printf '%s' "$x")
case "$sp" in *'`new project <name>`'*'do not run cc slack mkchannel'*) mkp=0;; *) mkp=1;; esac
[ "$mkp" = 0 ] && [ "$(m Bash '{"command":"cc slack mkchannel help"}' "$mf")" = 2 ] \
  && grep -q 'new project <name>' "$B/../templates/home/COMMS.md" \
  && ok "mkchannel is still refused a member-facing session AND it is now told where the channel really comes from: the prompt and COMMS name \`new project <name>\` — the refusal alone sent a session to the owner" \
  || bad "MEMBER_SP/COMMS.md do not name the new-project path"
# ...and the command that prompt names has to DISPATCH. `cc slack project` was advertised in MEMBER_SP, the member
# README, both COMMS files and the design doc while `cc`'s slack case had no arm for it, so a session doing exactly
# what it was told hit the usage line: nothing created, and no reason it could act on (review of PR #196). Its own
# HOME, holding no socket, so this asks nothing of a live daemon: reaching cc-slack IS the answer that comes back.
sd="$T/slack-dispatch"; mkdir -p "$sd/.cc"
sp2=$(eval "$(sed -n 's/^MEMBER_SP=/x=/p' "$B/cc")"; printf '%s' "$x")
dsp=$(env HOME="$sd" "$B/cc" slack project probe-x 2>&1); dspu=$(env HOME="$sd" "$B/cc" slack nosuchverb 2>&1)
case "$sp2" in *'`cc slack project <name>`'*) spp=0;; *) spp=1;; esac
[ "$spp" = 0 ] && grep -q 'Slack link did not answer' <<<"$dsp" && ! grep -q 'cc slack on|off' <<<"$dsp" \
  && grep -q 'cc slack on|off' <<<"$dspu" \
  && ok "the door the member prompt names is the door \`cc\` opens: \`cc slack project <name>\` reaches cc-slack (which answers that this HOME has no Slack link), while an unknown verb still falls to the usage line" \
  || bad "cc slack project does not dispatch (prompt names it: $spp; got: $(tr '\n' '|' <<<"$dsp"))"
miss=""; for probe in "${MP[@]}"; do [ "$(m "${probe%%|*}" "${probe#*|}" "$HOME")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "no regression: an unmarked cwd (planning session) is gated by none of them" || bad "unmarked cwd gated:$miss"
miss=""; for probe in 'Bash|{"command":"ls -la"}' 'Bash|{"command":"cc-notify -t help the owner must decide this"}' \
             'Bash|{"command":"git log --oneline -5"}' "Read|{\"file_path\":\"$mf/note.md\"}" "Edit|{\"file_path\":\"$mf/note.md\"}"; do
  [ "$(m "${probe%%|*}" "${probe#*|}" "$mf")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "member-facing session still reads, edits in place and escalates with cc-notify" || bad "member gate over-blocks:$miss"
miss=""; for probe in "Write|{\"file_path\":\"$GH/dev/other/x.md\"}" "Bash|{\"command\":\"cp x $GH/bin/cc-guard\"}" "Bash|{\"command\":\"echo x > ~/dev/other/x.md\"}"; do
  [ "$(m "${probe%%|*}" "${probe#*|}" "$mf")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && [ "$(m Bash "{\"command\":\"echo hi > $mf/notes.md\"}" "$mf")" = 0 ] && ok "a member is fenced the same way: ~/dev/<other> and ~/bin refused, its own dir not" || bad "member write fence:$miss"
# The probes above hand payloads STRAIGHT to cc-guard. Live, Claude Code runs the hook only for tools the PreToolUse
# MATCHER names — and Read|NotebookRead|Grep|Glob had a deny branch for days that no call ever reached, because the
# matcher stopped at NotebookEdit (audit 2026-09-01 F1). So: every tool cc-guard has a case branch for must be in the
# matcher, in BOTH files that carry it (the managed manifest the drift check reads, the default install.sh copies).
C="$B/../config"; mm=$(jq -r '.hooks[] | select(.event=="PreToolUse" and .command=="$HOME/bin/cc-guard") | .matcher' "$C/claude-managed.json")
ms=$(jq -r '.hooks.PreToolUse[] | select(any(.hooks[]; .command=="$HOME/bin/cc-guard")) | .matcher' "$C/claude-settings.json")
gt=$(grep -oE '^  [A-Za-z|]+\)' "$B/cc-guard" | tr -d ' )' | tr '|' '\n' | sort -u)   # the guard's own case labels
miss=""; for tool in $gt; do for f in managed:"$mm" settings:"$ms"; do
  tr '|' '\n' <<<"${f#*:}" | grep -qx "$tool" || miss="$miss ${f%%:*}:$tool"; done; done
[ -n "$gt" ] && grep -qx Read <<<"$gt" && [ "$mm" = "$ms" ] && [ -z "$miss" ] \
  && ok "the PreToolUse matcher carries every tool cc-guard gates ($(tr '\n' ' ' <<<"$gt"| sed 's/ $//')), identically in claude-managed.json and claude-settings.json" \
  || bad "PreToolUse matcher does not reach the guard: missing[$miss] managed=[$mm] settings=[$ms]"
# A MEMBER WORKSPACE is the one member that DOES dispatch — inside itself and nowhere else. The marker is
# .cc/member-workspace at ~/dev/<handle>, and a TRACK of that workspace inherits the tier rather than being promoted
# to the ordinary worker one by its own .cc/track. Defence in depth: docs/design-member-workspaces.md, "the boundary".
# The fixtures live under $T (~/.cc/…) and never /tmp — /tmp is a write root, so a probe there would pass for free.
# EVERY MARKER HERE CLAIMS `other`, and every case still resolves to `alice`: identity is the PATH
# (~/dev/<handle>, ~/.cc/worktrees/<repo>/<track>) because a marker's body is a file the member may edit.
mkdir -p "$GH/dev/alice/.cc" "$GH/.cc/worktrees/alice/todo/.cc" "$GH/.cc/worktrees/other/forged/.cc"
: > "$GH/dev/alice/.cc/member-facing"; printf 'other\n' > "$GH/dev/alice/.cc/member-workspace"
printf 'other\nforged\n' > "$GH/.cc/worktrees/alice/todo/.cc/track"
# …and a worktree carrying COMMITTED markers — what `git add -A` used to ship into every one of them.
: > "$GH/.cc/worktrees/other/forged/.cc/member-facing"; printf 'alice\n' > "$GH/.cc/worktrees/other/forged/.cc/member-workspace"
printf 'alice\ntodo\n' > "$GH/.cc/worktrees/other/forged/.cc/track"
mws="$GH/dev/alice"; mwt="$GH/.cc/worktrees/alice/todo"; mwf="$GH/.cc/worktrees/other/forged"
WOK=('Bash|{"command":"cc alice todo --go build it"}|W' 'Bash|{"command":"cc alice todo"}|W'
     'Bash|{"command":"cc board add alice todo title brief"}|W' 'Bash|{"command":"cc board show alice"}|W'
     'Bash|{"command":"cc alice todo --go x"}|K' "Edit|{\"file_path\":\"$GH/.cc/state/alice/todo/task.md\"}|W")
WNO=('Bash|{"command":"cc other t --go build it"}|W' 'Bash|{"command":"cc-loop other t"}|W'
     'Bash|{"command":"cc-loop alice todo"}|W' 'Bash|{"command":"cc other"}|W' 'Bash|{"command":"cc other t"}|W'
     'Bash|{"command":"cc board add other t title brief"}|W' 'Bash|{"command":"cc board show other"}|W'
     'Bash|{"command":"cc alice a --go x; cc other b --go y"}|W' 'Bash|{"command":"claude -p do it"}|W'
     'Bash|{"command":"cat ~/.cc/config"}|W' 'Bash|{"command":"docker run -v /:/host x"}|W'
     'Bash|{"command":"cc slack mkchannel x"}|W' 'Bash|{"command":"cc other t --go x"}|K'
     'Bash|{"command":"cat ~/.cc/config"}|K' 'Bash|{"command":"cc board add other t x y"}|K'
     "Edit|{\"file_path\":\"$GH/.cc/state/other/x/task.md\"}|W"
     'Bash|{"command":"cc alice todo --go x"}|F' 'Bash|{"command":"cat ~/.cc/config"}|F')
wprobe(){ local t=${1%%|*} rest=${1#*|} j c; j=${rest%|*}; c=${rest##*|}
          case "$c" in W) c=$mws;; F) c=$mwf;; *) c=$mwt;; esac; m "$t" "$j" "$c"; }
miss=""; for probe in "${WOK[@]}"; do [ "$(wprobe "$probe")" = 0 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "a member WORKSPACE works inside itself: dispatch, a session, its own board and track state — from the workspace dir and from its worker's worktree" || bad "member workspace over-blocked:$miss"
miss=""; for probe in "${WNO[@]}"; do [ "$(wprobe "$probe")" = 2 ] || miss="$miss ${probe#*|}"; done
[ -z "$miss" ] && ok "...and nothing outside it: another repo's dispatch, session, board or track state, a mixed command, raw claude -p, the box's secrets, containers, Slack wiring — from the worker's worktree too; cc-loop is refused even INSIDE (the daily cap is charged in \`cc … --go\`, so a direct loop would spend off the ledger); and a worktree carrying committed markers gains nothing at all" || bad "member workspace escapes:$miss"
[ "$(m Bash '{"command":"cc alice todo --go x"}' "$mf")" = 2 ] && ok "a plain member-facing session still dispatches nothing: the exception is the WORKSPACE marker, not the member role" || bad "member-facing session gained dispatch"
# THE DOOR OPENS FROM OUTSIDE: CC_MEMBER_SANDBOX=1 is the sandbox's to set. From a plain member dir
# `CC_MEMBER_SANDBOX=1 cc alice todo` passed every rule and started a workspace session ON THE HOST (review 2, A).
miss=""; for c in 'CC_MEMBER_SANDBOX=1 cc alice todo' 'env CC_MEMBER_SANDBOX=1 cc alice todo --go x' 'export CC_MEMBER_SANDBOX=1; cc alice todo' 'bash -c \"CC_MEMBER_SANDBOX=1 cc alice todo\"'; do
  for cw in "$mf" "$mws" "$mwt"; do [ "$(m Bash "{\"command\":\"$c\"}" "$cw")" = 2 ] || miss="$miss [$c @${cw##*/}]"; done; done
[ -z "$miss" ] && ok "setting CC_MEMBER_SANDBOX is denied from every member-tier cwd (prefix, env, export, bash -c): the boundary opens the door, never the member" || bad "CC_MEMBER_SANDBOX settable by a member:$miss"
[ "$(m Bash '{"command":"CC_MEMBER_SANDBOX=1 cc alice todo"}' "$GH")" = 0 ] && [ "$(m Bash '{"command":"grep -n CC_MEMBER_SANDBOX core/bin/cc"}' "$mws")" = 0 ] \
  && ok "...the owner's own cwd is untouched, and naming the variable (a grep) is not setting it" || bad "CC_MEMBER_SANDBOX rule over-blocks"
# .cc/track MEANS SOMETHING ONLY UNDER ~/.cc/worktrees/<repo>/<track>, where cc makes them. One in a member's subdir
# used to set role=worker there — and hand that member the box's config and another repo's dispatch (review 2, C).
mkdir -p "$GH/dev/alice/sub/.cc" "$GH/stray/.cc"; printf 'other\nt\n' > "$GH/dev/alice/sub/.cc/track"; printf 'other\nt\n' > "$GH/stray/.cc/track"
[ "$(m Bash '{"command":"cat ~/.cc/config"}' "$GH/dev/alice/sub")" = 2 ] && [ "$(m Bash '{"command":"cc other t --go x"}' "$GH/dev/alice/sub")" = 2 ] \
  && [ "$(m Bash '{"command":"cc alice todo --go x"}' "$GH/dev/alice/sub")" = 0 ] \
  && ok "a .cc/track inside a member workspace is just a file: the subdir is still alice's world (secrets and another repo's dispatch denied, its own dispatch allowed)" || bad "a member subdir's .cc/track promoted it to worker"
[ "$(m Bash '{"command":"gh pr merge 1"}' "$GH/stray")" = 0 ] && [ "$(printf '{"tool_name":"Bash","tool_input":{"command":"gh pr merge 1"},"cwd":"%s"}' "$GH/stray" | env HOME="$GH" CC_ROLE=worker "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] \
  && ok "...and outside ~/.cc/worktrees it is no track marker at all — CC_ROLE from the env still gates there" || bad "stray .cc/track honoured outside ~/.cc/worktrees"
# THE BOUNDARY (owner, 2026-09-01). member-sandbox has now BUILT it, so the invariant changed shape: a member
# workspace session no longer refuses to start — it starts INSIDE `cc-sandbox member`. What must never happen is a
# BARE one on this host, so `cc`'s own internals (__run*) refuse a workspace repo outside the boundary, cc-loop still
# refuses it, and the window `cc` opens for a member target IS the boundary. A stub tmux records the command `cc`
# would run instead of opening a window — the tmux server here is this box's live one.
gout(){ env HOME="$GH" PATH="$B:$PATH" "$@" 2>&1; }
o1=$(gout "$B/cc" __run alice todo); r1=$?
o1b=$(gout "$B/cc" __runmain alice)
o2=$(gout "$B/cc-loop" alice todo); r2=$?
o3=$(env HOME="$GH" CC_MEMBER_SANDBOX=1 "$B/cc-loop" alice todo 2>&1)
o4=$(env HOME="$GH" "$B/cc-loop" other todo 2>&1)
[ "$r1" = 1 ] && [ "$r2" = 2 ] && grep -q 'never bare on the host' <<<"$o1" && grep -q 'never bare on the host' <<<"$o1b" \
  && grep -q boundary <<<"$o2" && ! grep -q boundary <<<"$o3" && ! grep -q boundary <<<"$o4" \
  && ok "no BARE member workspace session on this host: cc's own internals and cc-loop refuse one outside the boundary, and CC_MEMBER_SANDBOX=1 is still the only thing that opens it — an ordinary repo is untouched" \
  || bad "member workspace session startable bare on the host (cc rc=$r1, cc-loop rc=$r2)"
mkdir -p "$T/stub" "$GH/dev/other"; printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "$TMUX_STUB_LOG"\nexit 0\n' > "$T/stub/tmux"; chmod +x "$T/stub/tmux"
sout(){ env HOME="$GH" PATH="$T/stub:$B:$PATH" TMUX_STUB_LOG="$T/tmux.log" CC_CLAUDE=/bin/true "$@" >/dev/null 2>&1; }
( cd "$GH/dev/alice" && git init -q -b main && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m init ) 2>/dev/null   # a track needs git; the guard cases above are done with this dir
mkdir -p "$GH/.cc/members/alice"; echo '{"claudeAiOauth": {"accessToken": "not-a-token"}}' > "$GH/.cc/members/alice/credentials.json"   # the workspace's OWN credential (a fake: cc checks the shape, never uses it) — without one cc opens nothing, see the review-156d case below
# The --go half runs on `t9` and not on `todo`: `todo` above is a plain directory with a lying marker in it, made
# to test exactly that, and a dispatch now claims the row first — which refuses a name that is not really a
# worktree on this row's branch (bin/cc-task). A member workspace's own track is what this case is about.
: > "$T/tmux.log"; sout "$B/cc" alice; sout "$B/cc" other; sout "$B/cc" alice t9 --go 'do a thing'
grep -q '__runmember alice' "$T/tmux.log" && grep -q 'cc-sandbox member alice t9 -- cc-loop' "$T/tmux.log" \
  && ! grep -q 'runmember other' "$T/tmux.log" && ! grep -q 'cc-sandbox member other' "$T/tmux.log" \
  && ok "...and the window cc opens for a member target IS the boundary: the session runs \`cc __runmember\` (which execs cc-sandbox member) and a --go loop runs \`cc-sandbox member <handle> <track> -- cc-loop\`, one wall not two, while an ordinary repo gets neither" \
  || bad "member launch is not inside the boundary: $(tr '\n' '|' < "$T/tmux.log")"
# A REPO THE BOX ALREADY HAD BECOMES ONE THE SAME WAY. The four that exist came from cc-slack's join flow; `cc-sandbox
# convert` is the path for a repo already on the box, and it writes the same markers — so every layer that reads them off
# the path agrees. Here that means `cc`: the window it opens for a converted repo is the boundary, not a planning session.
mkdir -p "$GH/dev/bob"; echo hi > "$GH/dev/bob/README.md"
cv=$(env HOME="$GH" PATH="$B:$PATH" "$B/cc-sandbox" convert bob 2>&1); rcv=$?
mkdir -p "$GH/.cc/members/bob"; echo '{"claudeAiOauth": {"accessToken": "not-a-token"}}' > "$GH/.cc/members/bob/credentials.json"
: > "$T/tmux.log"; sout "$B/cc" bob
{ [ "$rcv" = 0 ] && grep -q '__runmember bob' "$T/tmux.log" && ! grep -q '__runmain bob' "$T/tmux.log"; } \
  && ok "a repo converted with \`cc-sandbox convert\` is a member workspace to cc as well — the window it opens for it is the boundary, not a planning session" \
  || bad "a converted repo did not become a workspace (rc=$rcv, tmux='$(tr '\n' '|' < "$T/tmux.log")'): $cv"
# A REDIRECTED .git IS NOT THE HOST'S TO RUN (review-156c). A workspace track's gitlink and admin dir are written from INSIDE the
# boundary, so `.git` can name a member git dir whose config carries core.fsmonitor = <payload> (or an ext:: remote), and `cc done
# <h> <t>` on the host — what cc-loop's exit-4 message tells the owner to run — executed it as the owner: the hooksPath pin does not
# reach it (measured before the fix: the payload ran, rc=0, "no remote, so no PR"). Now `cc done` resolves the worktree's common dir
# before any other git touches it and refuses anything but ~/dev/<h>/.git — and a track that really hangs off it still finishes.
git init -q "$GH/dev/alice/evil" && git -C "$GH/dev/alice/evil" symbolic-ref HEAD refs/heads/track/todo && git -C "$GH/dev/alice/evil" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init \
  && git -C "$GH/dev/alice/evil" config core.fsmonitor "sh -c 'touch $T/fsmon-ran' _"   # the payload goes in LAST: set before the commit above, that commit itself would fire it
printf 'gitdir: %s\n' "$GH/dev/alice/evil/.git" > "$GH/.cc/worktrees/alice/todo/.git"
od=$(env HOME="$GH" PATH="$B:$PATH" "$B/cc" done alice todo 2>&1); rd=$?
{ [ "$rd" = 1 ] && grep -q '^cc: refusing to run git in ' <<<"$od" && grep -qF "$GH/.cc/worktrees/alice/todo" <<<"$od" && [ ! -e "$T/fsmon-ran" ]; } \
  && ok "cc done on a workspace track whose .git names a member git dir refuses, names the worktree, and ran no git in it (review-156c)" \
  || bad "cc done ran git against a redirected .git: rc=$rd payload=$([ -e "$T/fsmon-ran" ] && echo RAN || echo no) $od"
rm -rf "$GH/dev/alice/evil" "$GH/.cc/worktrees/alice/todo/.git"
git -C "$GH/dev/alice" worktree add -q -b track/t2 "$GH/.cc/worktrees/alice/t2" 2>/dev/null   # the genuine article: a track hanging off ~/dev/alice/.git
od=$(env HOME="$GH" PATH="$B:$PATH" "$B/cc" done alice t2 2>&1); rd=$?
{ [ "$rd" = 0 ] && ! grep -q 'refusing to run git' <<<"$od" && grep -q 'no remote, so no PR' <<<"$od"; } \
  && ok "...and a track that really hangs off ~/dev/<handle>/.git passes the same check and finishes (no remote → no PR)" || bad "cc done refused a genuine workspace track: rc=$rd $od"
git -C "$GH/dev/alice" worktree remove --force "$GH/.cc/worktrees/alice/t2" >/dev/null 2>&1; git -C "$GH/dev/alice" branch -q -D track/t2 >/dev/null 2>&1
# A WORKTREE MADE BY HAND HAS NO .cc/track, AND `cc done` USED TO BLAME THE BRANCH FOR IT: the hook committed nothing,
# --push read an empty track name and said "HEAD is 'track/t9', not 'track/'" (raised-cc-done-blames-the-branch-for-a-
# missing-track-file, 2026-09-16/18); bare `cc done` inside the worktree died on bash's "line 991: 2: repo". Now a box
# repo's worktree gets the marker written and said, the names come off the path when left off, and a file that does
# not name the track is said with its shape. A kind=session row and a local bare origin end the run right after the
# push, so the whole path after the marker runs and nothing reaches GitHub.
git init -q -b main "$GH/dev/boxr"; echo a > "$GH/dev/boxr/a.txt"; git -C "$GH/dev/boxr" add -A; git -C "$GH/dev/boxr" -c user.email=t@t -c user.name=t commit -qm base
git init -q --bare "$T/boxr.git"; git -C "$GH/dev/boxr" remote add origin "$T/boxr.git"   # a repo cc never stamped: no .cc/ exclude yet
mkdir -p "$GH/.cc/worktrees/boxr"; git -C "$GH/dev/boxr" worktree add -q -b track/t9 "$GH/.cc/worktrees/boxr/t9"   # by hand: no .cc/track
env HOME="$GH" "$B/cc-board" init boxr "$GH/dev/boxr" main >/dev/null; env HOME="$GH" "$B/cc-board" add boxr t9 "hand-made" >/dev/null
env HOME="$GH" "$B/cc-board" set boxr t9 kind session; echo work > "$GH/.cc/worktrees/boxr/t9/w.txt"
od=$(env HOME="$GH" PATH="$B:$PATH" timeout 120 "$B/cc" done boxr t9 2>&1); rd=$?
{ [ "$rd" = 0 ] && grep -q "wrote $GH/.cc/worktrees/boxr/t9/.cc/track (boxr, t9)" <<<"$od" && [ "$(cat "$GH/.cc/worktrees/boxr/t9/.cc/track")" = "$(printf 'boxr\nt9')" ] \
    && ! grep -q "not 'track/'" <<<"$od" && git -C "$T/boxr.git" rev-parse -q --verify track/t9 >/dev/null && ! git -C "$T/boxr.git" ls-tree -r --name-only track/t9 | grep -q '^\.cc/'; } \
  && ok "cc done on a hand-made box worktree writes its .cc/track, says so, and the delivery goes on from there with .cc/ excluded — no line blaming the branch" \
  || bad "cc done on a hand-made worktree: rc=$rd track='$(cat "$GH/.cc/worktrees/boxr/t9/.cc/track" 2>/dev/null | tr '\n' '|')' $od"
od=$(cd "$GH/.cc/worktrees/boxr/t9" && env HOME="$GH" PATH="$B:$PATH" timeout 120 "$B/cc" done 2>&1); rd=$?
{ [ "$rd" = 0 ] && grep -q 'cc: done boxr t9 — read off this worktree' <<<"$od"; } \
  && ok "bare \`cc done\` inside a track's worktree takes both names off its path and says so" || bad "bare cc done inside a worktree: rc=$rd $od"
od=$(cd "$T" && env HOME="$GH" PATH="$B:$PATH" timeout 60 "$B/cc" done 2>&1); rd=$?; od1=$(cd "$T" && env HOME="$GH" PATH="$B:$PATH" timeout 60 "$B/cc" done boxr 2>&1); rd1=$?
{ [ "$rd" = 2 ] && [ "$rd1" = 2 ] && grep -q '^usage: cc done <repo> <track>' <<<"$od" && grep -q '^usage: cc done <repo> <track>' <<<"$od1" && ! grep -q '2: repo' <<<"$od$od1"; } \
  && ok "…and anywhere else, or with one name, it is the usage line — not bash's '2: repo'" || bad "bare cc done elsewhere: rc=$rd/$rd1 $od / $od1"
printf 'repo: boxr\ntrack: t9\n' > "$GH/.cc/worktrees/boxr/t9/.cc/track"
od=$(env HOME="$GH" PATH="$B:$PATH" timeout 60 "$B/cc" done boxr t9 2>&1); rd=$?
{ [ "$rd" = 1 ] && grep -q "two bare lines, 'boxr' then 't9'" <<<"$od" && [ "$(sed -n 1p "$GH/.cc/worktrees/boxr/t9/.cc/track")" = "repo: boxr" ]; } \
  && ok "a .cc/track that does not name the track is said with its shape and left as written — nothing opened" || bad "malformed .cc/track: rc=$rd $od"
git -C "$GH/dev/alice" worktree add -q -b track/t2b "$GH/.cc/worktrees/alice/t2b" 2>/dev/null   # a member's hand-made worktree: the host says, and writes nothing into their tree
od=$(env HOME="$GH" PATH="$B:$PATH" timeout 60 "$B/cc" done alice t2b 2>&1); rd=$?
{ [ "$rd" = 0 ] && grep -q 'has no .cc/track' <<<"$od" && [ ! -e "$GH/.cc/worktrees/alice/t2b/.cc/track" ] && grep -q 'no remote, so no PR' <<<"$od"; } \
  && ok "…while a member's hand-made worktree is only told: the host writes no .cc/track into their tree, and the run goes on as before" \
  || bad "cc done on a member's hand-made worktree: rc=$rd written=$([ -e "$GH/.cc/worktrees/alice/t2b/.cc/track" ] && echo yes || echo no) $od"
git -C "$GH/dev/alice" worktree remove --force "$GH/.cc/worktrees/alice/t2b" >/dev/null 2>&1; git -C "$GH/dev/alice" branch -q -D track/t2b >/dev/null 2>&1
# A PROJECT'S FIRST PUSH MAKES ITS TRACK THE REPOSITORY'S DEFAULT BRANCH (GitHub: the first branch pushed into an empty
# repository), so `cc done` asked that repository for HEAD, was told the track itself, and tried to open a PR from the
# branch onto itself — "PR creation failed", the row left in review (measured live 2026-09-04 on a repository the box had
# just created). The branch is the delivery there, exactly as for a repository with no branch at all.
git init -q --bare "$T/t3.git"
git -C "$GH/dev/alice" worktree add -q -b track/t3 "$GH/.cc/worktrees/alice/t3" 2>/dev/null
mkdir -p "$GH/.cc/worktrees/alice/t3/.cc"; printf 'alice\nt3\n' > "$GH/.cc/worktrees/alice/t3/.cc/track"
git -C "$GH/.cc/worktrees/alice/t3" remote add t3 "$T/t3.git"
git -C "$GH/.cc/worktrees/alice/t3" -c user.email=t@t -c user.name=t commit -q --allow-empty -m t3
git -C "$GH/.cc/worktrees/alice/t3" push -q t3 track/t3 2>/dev/null; git -C "$T/t3.git" symbolic-ref HEAD refs/heads/track/t3
od=$(env HOME="$GH" PATH="$B:$PATH" "$B/cc" done alice t3 2>&1); rd=$?
{ [ "$rd" = 0 ] && grep -q 'no other branch there' <<<"$od" && ! grep -q 'PR creation failed' <<<"$od"; } \
  && ok "cc done on a project whose repository's default branch is the track itself ends clean — the branch is the delivery, not a PR onto itself" \
  || bad "cc done tried a PR from the track onto itself: rc=$rd $od"
git -C "$GH/dev/alice" worktree remove --force "$GH/.cc/worktrees/alice/t3" >/dev/null 2>&1; git -C "$GH/dev/alice" branch -q -D track/t3 >/dev/null 2>&1; rm -rf "$T/t3.git"
# THE SAME SHAPE AFTER main EXISTS (ece298a/r2r-dac, 2026-09-25): the default is still the track, but main is there, so
# the PR goes onto main instead of the "no other branch" ending. gh is not reachable here, so the run may fail at the PR.
git init -q --bare "$T/t3b.git"
git -C "$GH/dev/alice" worktree add -q -b track/t3b "$GH/.cc/worktrees/alice/t3b" 2>/dev/null
mkdir -p "$GH/.cc/worktrees/alice/t3b/.cc"; printf 'alice\nt3b\n' > "$GH/.cc/worktrees/alice/t3b/.cc/track"
git -C "$GH/.cc/worktrees/alice/t3b" remote add t3b "$T/t3b.git"
git -C "$GH/.cc/worktrees/alice/t3b" -c user.email=t@t -c user.name=t commit -q --allow-empty -m t3b
git -C "$GH/.cc/worktrees/alice/t3b" push -q t3b track/t3b 2>/dev/null; git -C "$GH/.cc/worktrees/alice/t3b" push -q t3b track/t3b:refs/heads/main 2>/dev/null
git -C "$T/t3b.git" symbolic-ref HEAD refs/heads/track/t3b
mkdir -p "$T/t3b-bin"; printf '#!/bin/sh\nexit 1\n' > "$T/t3b-bin/gh"; chmod +x "$T/t3b-bin/gh"   # a gh that fails at once; the real one waits on a pipe
od=$(env HOME="$GH" PATH="$T/t3b-bin:$B:$PATH" timeout 60 "$B/cc" done alice t3b 2>&1 </dev/null)
{ grep -q 'opening the PR against main' <<<"$od" && ! grep -q 'no other branch there' <<<"$od"; } \
  && ok "cc done with the default still on the track but main present opens the PR against main" \
  || bad "cc done ignored main when the default was the track: $od"
git -C "$GH/dev/alice" worktree remove --force "$GH/.cc/worktrees/alice/t3b" >/dev/null 2>&1; git -C "$GH/dev/alice" branch -q -D track/t3b >/dev/null 2>&1; rm -rf "$T/t3b.git" "$T/t3b-bin"
# A KIND=SESSION ROW IS A LIVING PROJECT, NOT A TASK: alive is its normal state, so `cc done` delivers and stops there.
# Run against a member project in daily use it pushed and then ended the row as finished (2026-09-04). The two endings
# above are a kind=track row's and are unchanged.
git init -q --bare "$T/t4.git"
git -C "$GH/dev/alice" worktree add -q -b track/t4 "$GH/.cc/worktrees/alice/t4" 2>/dev/null
mkdir -p "$GH/.cc/worktrees/alice/t4/.cc"; printf 'alice\nt4\n' > "$GH/.cc/worktrees/alice/t4/.cc/track"
git -C "$GH/.cc/worktrees/alice/t4" remote add t4 "$T/t4.git"
git -C "$GH/.cc/worktrees/alice/t4" -c user.email=t@t -c user.name=t commit -q --allow-empty -m t4
env HOME="$GH" "$B/cc-board" init alice "$GH/dev/alice" main >/dev/null
env HOME="$GH" "$B/cc-board" add alice t4 "a living project" >/dev/null
env HOME="$GH" "$B/cc-board" set alice t4 kind session; env HOME="$GH" "$B/cc-board" status alice t4 running >/dev/null
od=$(env HOME="$GH" PATH="$B:$PATH" "$B/cc" done alice t4 2>&1); rd=$?
st=$(env HOME="$GH" "$B/cc-board" get alice t4 status)
{ [ "$rd" = 0 ] && [ "$st" = running ] && git -C "$T/t4.git" rev-parse -q --verify track/t4 >/dev/null; } \
  && ok "cc done on a kind=session row pushes the delivery and leaves the row alive — a living project is never 'done'" \
  || bad "cc done ended a session row: rc=$rd status=$st $od"
git -C "$GH/dev/alice" worktree remove --force "$GH/.cc/worktrees/alice/t4" >/dev/null 2>&1; git -C "$GH/dev/alice" branch -q -D track/t4 >/dev/null 2>&1; rm -rf "$T/t4.git"
printf '[user]\n\tname = t\n\temail = t@t\n' > "$GH/.gitconfig"   # the two cases below need the host-side checkpoint to actually COMMIT, which needs an identity under this fixture's HOME
# NOTHING `cc done` RUNS WRITES INSIDE A MEMBER'S TREE. cc-checkpoint's commit mode ends in the same push --push does,
# so the plain call `cc done` makes first writes .cc/pushed and .cc/push.err.tmp too — and only the --push call three
# lines later was told to keep that state out of the tree. ~/.cc/worktrees/<handle> is bound read-WRITE in the
# member's live boundary, so on a dirty worktree a link left at one of those names had the host truncate whatever it
# pointed at, as the owner (review of #225). kind=session so the run ends at the delivery, with no PR to open.
git init -q --bare "$T/t6.git"
git -C "$GH/dev/alice" worktree add -q -b track/t6 "$GH/.cc/worktrees/alice/t6" 2>/dev/null
w6="$GH/.cc/worktrees/alice/t6"; mkdir -p "$w6/.cc"; printf 'alice\nt6\n' > "$w6/.cc/track"
git -C "$w6" remote add t6 "$T/t6.git"
git -C "$w6" -c user.email=t@t -c user.name=t commit -q --allow-empty -m t6
echo "not yours" > "$T/victim6"; ln -sf "$T/victim6" "$w6/.cc/pushed"
echo dirty > "$w6/work.txt"   # a dirty worktree is what makes the plain checkpoint commit, and then push
env HOME="$GH" "$B/cc-board" add alice t6 "a living project" >/dev/null; env HOME="$GH" "$B/cc-board" set alice t6 kind session
od=$(env HOME="$GH" PATH="$B:$PATH" "$B/cc" done alice t6 2>&1); rd=$?
{ [ "$(cat "$T/victim6")" = "not yours" ] && [ "$(cat "$GH/.cc/push-state/alice/t6/pushed" 2>/dev/null)" = "$(git -C "$w6" rev-parse HEAD)" ]; } \
  && ok "cc done writes none of the checkpoint's state in a member's tree: a link left at .cc/pushed is not written through, and the lease is the host's own" \
  || bad "cc done wrote through a link in the member's tree: victim='$(cat "$T/victim6")' rc=$rd $od"
git -C "$GH/dev/alice" worktree remove --force "$w6" >/dev/null 2>&1; git -C "$GH/dev/alice" branch -q -D track/t6 >/dev/null 2>&1; rm -rf "$T/t6.git"
# …AND INSIDE THE BOUNDARY IT KEEPS THAT STATE IN THE WORKTREE, because in there is nowhere else. For a member
# workspace the NORMAL 'cc done' runs inside it — cc-loop is launched under `cc-sandbox member` and calls it from
# there — where $HOME is a tmpfs with no ~/.cc/push-state bind at all. Redirected there anyway: done.lock stopped
# serialising that run against the host's own 'cc done' and against the 5-minute sweep, and the checkpoint.err and
# push.err it wrote died with the sandbox, so a member --go worker whose commit was refused for a staged secret lit
# `commit!` in no reader — the round 11-12 bug, back again (review round 13 of #225). In there the tree is the
# member's own and this process IS the member, so <wt>/.cc is exactly right and is where it wrote before this PR.
git init -q --bare "$T/t9.git"
git -C "$GH/dev/alice" worktree add -q -b track/t9 "$GH/.cc/worktrees/alice/t9" 2>/dev/null
w9="$GH/.cc/worktrees/alice/t9"; mkdir -p "$w9/.cc"; printf 'alice\nt9\n' > "$w9/.cc/track"
git -C "$w9" remote add t9 "$T/t9.git"
git -C "$w9" -c user.email=t@t -c user.name=t commit -q --allow-empty -m t9
echo dirty > "$w9/work.txt"   # the same shape as t6: a dirty worktree is what makes the plain checkpoint commit, and then push
env HOME="$GH" "$B/cc-board" add alice t9 "a living project" >/dev/null; env HOME="$GH" "$B/cc-board" set alice t9 kind session
od=$(env HOME="$GH" CC_MEMBER_SANDBOX=1 PATH="$B:$PATH" "$B/cc" done alice t9 2>&1); rd=$?
{ [ "$rd" = 0 ] && [ "$(cat "$w9/.cc/pushed" 2>/dev/null)" = "$(git -C "$w9" rev-parse HEAD)" ] && [ ! -e "$GH/.cc/push-state/alice/t9" ]; } \
  && ok "...while the same run INSIDE the boundary keeps it in the worktree — there is no ~/.cc/push-state in there, so a redirect would lock nothing and write the markers into a tmpfs that dies with the sandbox" \
  || bad "an in-boundary cc done put its state outside the worktree: rc=$rd $od"
git -C "$GH/dev/alice" worktree remove --force "$w9" >/dev/null 2>&1; git -C "$GH/dev/alice" branch -q -D track/t9 >/dev/null 2>&1; rm -rf "$T/t9.git" "$GH/.cc/push-state/alice/t9"
# …AND A MEMBER-WRITABLE <wt>/.cc/pushed IS NEVER THE HOST'S LEASE (round 9 of #225). An earlier cut copied its
# CONTENTS into ~/.cc/push-state and handed them to --force-with-lease, so a member who wrote the sha currently on
# the remote made cc done force-push over a commit this worktree never wrote. The migration is gone: a track whose
# host lease predates the move has none here, cc done refuses WITHOUT forcing (a named line, not "push refused"),
# and the remote is left exactly as it is. Its next real host push records the lease and it is ordinary again.
git init -q --bare "$T/t7.git"
git -C "$GH/dev/alice" worktree add -q -b track/t7 "$GH/.cc/worktrees/alice/t7" 2>/dev/null
w7="$GH/.cc/worktrees/alice/t7"; mkdir -p "$w7/.cc"; printf 'alice\nt7\n' > "$w7/.cc/track"
git -C "$w7" remote add t7 "$T/t7.git"
git -C "$w7" -c user.email=t@t -c user.name=t commit -q --allow-empty -m a7
git -C "$w7" push -q t7 track/t7; a7=$(git -C "$w7" rev-parse HEAD)   # the commit on the remote now
printf '%s\n' "$a7" > "$w7/.cc/pushed"   # THE FORGERY: the member writes the remote's current sha into the old lease location
git -C "$w7" -c user.email=t@t -c user.name=t commit -q --amend --allow-empty -m "a7 rebased"   # local diverges; a force would discard a7
env HOME="$GH" "$B/cc-board" add alice t7 "a living project" >/dev/null; env HOME="$GH" "$B/cc-board" set alice t7 kind session
od=$(env HOME="$GH" PATH="$B:$PATH" "$B/cc" done alice t7 2>&1); rd=$?
{ [ "$(git -C "$T/t7.git" rev-parse track/t7)" = "$a7" ] && [ "$rd" != 0 ] && ! grep -qE 'push refused|something else wrote' <<<"$od"; } \
  && ok "cc done never force-pushes from a member-written .cc/pushed — a forged lease is not trusted, the remote stands, and it says so by name" \
  || bad "cc done forced from a member file or mis-reported: remote=$(git -C "$T/t7.git" rev-parse track/t7) a7=$a7 rc=$rd $od"
# …AND THAT REFUSAL IS NOT A DEAD END. It used to point at a push that can never happen: the sweep said a session's
# `cc done` would push it, `cc done` said the next checkpoint push would record the lease, and a diverged branch never
# fast-forwards — so a pre-#225 track was unlandable by any automated path and both messages promised otherwise
# (review round 10 of #225). One exit, named in both: `cc-checkpoint adopt`, where a PERSON reads the commit the
# remote holds and records it — checked against the remote at that instant, never read out of the member's tree.
grep -qF "cc-checkpoint adopt alice t7" <<<"$od" \
  && ok "...and it names the one way out of rc=3, not a push that can never happen" \
  || bad "cc done's rc=3 line names no exit, or a circular one: $od"
ad=$(env HOME="$GH" PATH="$B:$PATH" "$B/cc-checkpoint" adopt alice t7 2>&1); ra=$?
{ [ "$ra" = 1 ] && grep -qF "$a7" <<<"$ad" && [ ! -e "$GH/.cc/push-state/alice/t7/pushed" ]; } \
  && ok "cc-checkpoint adopt says what the remote holds and, until a person answers with it, records nothing" \
  || bad "adopt's reading step recorded a lease or said nothing: rc=$ra $ad"
ad=$(env HOME="$GH" PATH="$B:$PATH" "$B/cc-checkpoint" adopt alice t7 "$a7" 2>&1); ra=$?
od2=$(env HOME="$GH" PATH="$B:$PATH" "$B/cc" done alice t7 2>&1); rd2=$?
{ [ "$ra" = 0 ] && [ "$rd2" = 0 ] && [ "$(git -C "$T/t7.git" rev-parse track/t7)" = "$(git -C "$w7" rev-parse HEAD)" ]; } \
  && ok "...and the sha the operator read is the exit: cc done then pushes the rebased branch, with no member file trusted" \
  || bad "adopt did not unblock cc done: adopt rc=$ra $ad / done rc=$rd2 $od2"
git -C "$GH/dev/alice" worktree remove --force "$w7" >/dev/null 2>&1; git -C "$GH/dev/alice" branch -q -D track/t7 >/dev/null 2>&1; rm -rf "$T/t7.git"
# A MEMBER PROJECT'S `push!` IS THE HOST'S ALONE; ITS `commit!` IS EITHER SIDE'S — one rule, and every reader follows
# it (cc-reconcile's host_marker/commit_marker states it). A host-side cc-checkpoint run in a member's tree keeps its
# state under ~/.cc/push-state/<handle>/<project>, so the push.err in the worktree is theirs: their Stop hook has no
# credential by design — the host pushes for it — so that file is rewritten every turn and nothing on the host clears
# it, which lit `push!` for ever on a branch the sweep had pushed (round 10 of #225). A REFUSED COMMIT IS REAL WHEREVER
# IT HAPPENED: `cc done`'s host-side call writes one under push-state (it lit nowhere at all, round 11) and the member's
# own in-boundary hook writes <wt>/.cc/checkpoint.err and can write nowhere else — reading only the host's left a member
# who staged a secret refused, uncommitted and unmentioned in every reader, with the sweep skipping the track because a
# refusal moves no HEAD (round 12). Their file's existence lights the row; none of its content is read.
mkdir -p "$GH/.cc/worktrees/alice/t8/.cc"; printf 'alice\nt8\n' > "$GH/.cc/worktrees/alice/t8/.cc/track"
env HOME="$GH" "$B/cc-board" add alice t8 "a project of alice's" >/dev/null
mrow(){ local t=$1; shift   # the one t8 row out of cc ls ("alice   t8 ")
  env HOME="$GH" PATH="$T/stub:$B:$PATH" TMUX_STUB_LOG="$T/tmux.log" "$B/$t" "$@" 2>/dev/null | grep -E 'alice[/ ] *t8[ *]'; }
# THE TWO READERS SAY IT DIFFERENTLY AND READ THE SAME TWO FILES. `cc ls` marks the row `commit!`/`push!`; the daily
# report names no row at all (#303) and counts the project as stopped — "the work it is doing is not being saved".
# So the digest is read by its OWN count of stopped work, which is what this rule can move there, and never by a
# marker it no longer prints. dgm keeps the whole report, for the leak check: no reader renders a member's bytes.
dgm=""; dgstop(){ dgm=$(env HOME="$GH" PATH="$T/stub:$B:$PATH" TMUX_STUB_LOG="$T/tmux.log" "$B/cc-reconcile" digest 2>/dev/null)
  local n; n=$(head -1 <<<"$dgm" | grep -oE '[0-9]+ stopped'); printf '%s' "${n%% *}"; }
q0=$(dgstop)   # the fixture's own stopped count, before any marker of t8's exists
touch "$GH/.cc/worktrees/alice/t8/.cc/push.err"   # the member's own, which nothing on the host writes or clears
lsm=$(mrow cc ls); qa=$(dgstop)
{ [ -n "$lsm" ] && ! grep -qE 'push!' <<<"$lsm" && [ "$qa" = "$q0" ]; } \
  && ok "a member's credential-less push.err lights nothing in either reader — their hook cannot push by design, so that file is theirs and the host's readers do not read it as a failed push" \
  || bad "a member's own push.err lit the host's readers: ls='$lsm' stopped=$qa was=$q0"
printf 'staged .env.local — refused\n' > "$GH/.cc/worktrees/alice/t8/.cc/checkpoint.err"   # …and their own refusal, in the only place their hook can write it
lsm=$(mrow cc ls); qb=$(dgstop)
{ ! grep -qE 'push!' <<<"$lsm" && grep -q 'commit!' <<<"$lsm" && [ "$qb" = "$(( q0 + 1 ))" ] \
  && ! grep -q 'env.local' <<<"$lsm" && ! grep -q 'env.local' <<<"$dgm"; } \
  && ok "…while a member's own refused checkpoint is visible in cc ls and counted as stopped work in the digest — their in-boundary hook writes it and nothing else can — and neither reader renders a byte of what the member wrote" \
  || bad "the member's own refusal is invisible, or their push.err/content leaked: ls='$lsm' stopped=$qb was=$q0 digest='$dgm'"
rm -f "$GH/.cc/worktrees/alice/t8/.cc/checkpoint.err"
mkdir -p "$GH/.cc/push-state/alice/t8"   # the HOST's own failed push and refused commit, under no bind
touch "$GH/.cc/push-state/alice/t8/push.err" "$GH/.cc/push-state/alice/t8/checkpoint.err"
lsm=$(mrow cc ls); qc=$(dgstop)
{ grep -q 'push!' <<<"$lsm" && grep -q 'commit!' <<<"$lsm" && [ "$qc" = "$(( q0 + 1 ))" ]; } \
  && ok "...while the host's own markers light push! and commit! on their own, and the digest counts the project stopped, in either reader" \
  || bad "the host's markers are invisible: ls='$lsm' stopped=$qc was=$q0"
rm -rf "$GH/.cc/worktrees/alice/t8" "$GH/.cc/push-state/alice/t8"
rm -f "$GH/.gitconfig"   # back to the fixture the rest of this stanza was written against
o5=$(env HOME="$GH" CC_MEMBER_SANDBOX=1 "$B/cc-loop" alice todo --budget 1e9 2>&1); r5=$?
o6=$(env HOME="$GH" CC_MEMBER_SANDBOX=1 "$B/cc-loop" alice todo --budget 5.5 2>&1)
[ "$r5" = 2 ] && grep -q 'budget must be' <<<"$o5" && ! grep -q 'budget must be' <<<"$o6" \
  && ok "--budget must be a plain number: '1e9' (charged as \$8, spent as a billion) is refused, 5.5 is not" || bad "non-numeric --budget passed through (rc=$r5: $o5)"
# A CAP THAT BITES MUST REACH THE ONE PERSON WHO CAN RAISE IT (owner, 2026-09-01: "it shouldnt fail silently. it
# should notify their channel to tell me to bump them up"). The refusal only posted to #<handle>-updates — rung 5,
# ambient, nobody is @'d — so a workspace could sit capped all day and the owner never knew. It now ALSO mentions him
# in #<handle> itself (cc-notify --decision = rung 1), and exactly ONCE a day: the day-stamp is claimed under the
# spend ledger's lock, so refusal number two — and a --loop's worth after it — says nothing.
git -C "$GH/dev/alice" init -q && git -C "$GH/dev/alice" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
rm -f "$GH/.cc/state/member-spend.json"
# a COPY of cc with a stub cc-slack beside it: BIN is cc's own dirname, so the stub sees the post's real args —
# the destination is the assertion (review of #168: cc-notify's member-facing walk turned the mention into a DM).
NB="$T/nb"; mkdir -p "$NB" "$GH/dev/alice/.cc"; : > "$GH/dev/alice/.cc/member-facing"; cp "$B/cc" "$NB/cc"
for h in "$B"/cc-*; do ln -sf "$h" "$NB/$(basename "$h")"; done   # cc resolves EVERY helper through its own BIN
rm -f "$NB/cc-slack"   # …and only the Slack one is the stub (a copy, not a symlink: readlink -f would escape)
# `channels` is a real branch, not a recording: cc resolves #<h> through it before it stamps a channel as told, so the
# stub has to answer like the CLI does — a listing with #alice in it, or (NC_NO_CHAN=1) one without.
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s"\nif [ "$1" = channels ]; then [ -n "${NC_NO_CHAN:-}" ] || printf "#alice        C0ALICE1 -> alice\\n"; exit 0; fi\nexit "${CAP_SLACK_RC:-0}"\n' "$T/cap.args" > "$NB/cc-slack"
chmod +x "$NB/cc-slack"; : > "$T/cap.args"
# THE CAP IS CHARGED ON THE HOST, so this fixture is the HOST path — the stub tmux, not CC_MEMBER_SANDBOX=1. That
# variable used to be the flag that got a workspace past the old sandbox_gate; it now means "inside the boundary",
# where `cc … --go` writes the brief and brokers the launch to the daemon (core/bin/cc, the `go)` case) because the
# ledger ~/.cc/state/member-spend.json does not exist in there. Setting it here would test the broker, not the cap.
# CAP_CEIL is the owner's ceiling (MEMBER_DAILY_CEILING_USD): at the cap itself, as here, the box may raise nothing and
# every crossing is a refusal — the shape these first cases were written against. The raise cases below move it.
cap(){ ( cd "$GH/dev/alice" && env HOME="$GH" PATH="$T/stub:$B:$PATH" TMUX_STUB_LOG="$T/tmux.log" CC_CLAUDE=/bin/true \
           MEMBER_DAILY_USD=5 MEMBER_DAILY_CEILING_USD="${CAP_CEIL-5}" CAP_SLACK_RC="${CAP_SLACK_RC:-0}" "$NB/cc" alice todo --go x 2>&1 ); }
c1=$(cap); r1=$?; m1=$(grep -c -- '--mention' "$T/cap.args" 2>/dev/null)
grep -q 'refused' <<<"$c1" && [ "$r1" = 1 ] && [ "$m1" = 1 ] \
  && grep -q -- '-c #alice --mention' "$T/cap.args" && grep -q -- '-c #alice-updates' "$T/cap.args" \
  && ok "a member workspace over its daily cap @-mentions the owner IN ITS OWN CHANNEL, from the workspace's own cwd — not a DM, not -updates" \
  || bad "capped dispatch did not mention the owner in #alice (rc=$r1, mentions=$m1): $(cat "$T/cap.args" 2>/dev/null)"
c2=$(cap); m2=$(grep -c -- '--mention' "$T/cap.args" 2>/dev/null)
mk=$(jq -r '.alice.mentioned // ""' "$GH/.cc/state/member-spend.json" 2>/dev/null)
grep -q 'refused' <<<"$c2" && [ "$m2" = 1 ] && [ "$mk" = "$(date -u +%F)" ] \
  && ok "…and only once that day: the second refusal still refuses and still posts to -updates, but the owner is not mentioned twice" \
  || bad "the daily cap mentioned the owner more than once (mentions=$m2, marker='$mk')"
rm -f "$GH/.cc/state/member-spend.json"; : > "$T/cap.args"
CAP_SLACK_RC=1 cap >/dev/null; mkA=$(jq -r '.alice.mentioned // ""' "$GH/.cc/state/member-spend.json" 2>/dev/null)
CAP_SLACK_RC=1 cap >/dev/null; m3=$(grep -c -- '--mention' "$T/cap.args" 2>/dev/null)
[ -z "$mkA" ] && [ "$m3" = 2 ] \
  && ok "…and a mention nobody heard releases the day-stamp: a failed post is retried on the next refusal, not inherited as silence" \
  || bad "a failed mention kept its day-stamp (marker='$mkA', attempts=$m3)"
rm -f "$GH/.cc/state/member-spend.json"; : > "$T/cap.args"
# Every case above stopped AT the gate; the raises below go through it, on to `cc-task claim` and the (stub) window,
# so the track needs the worktree `cc` makes rather than the plain dir the forged-marker cases planted at alice/todo.
rm -rf "$GH/.cc/worktrees/alice/todo"
# THE CAP IS A TELL-LINE AND THE BOX RAISES IT ITSELF, UNDER THE OWNER'S CEILING (owner 2026-09-08; a member workspace sat capped
# overnight on 2026-09-09 with its Odoo run queued because a refusal only asked him). Cap $5, ceiling $30, a dispatch
# asking $8: not refused — today's cap becomes $8 in the ledger, the $8 is charged, and one line goes to -updates and
# one to the owner in #alice. Two more (+$8 each) raise it to $16 and $24; the fourth would need $32 and that is over
# the ceiling: refused, with the ceiling named and the once-a-day mention, exactly as a crossing of the cap used to be.
c4=$(CAP_CEIL=30 cap); r4=$?; l4=$(jq -c '[.alice.cap, .alice.usd]' "$GH/.cc/state/member-spend.json" 2>/dev/null)
[ "$r4" = 0 ] && grep -q 'cap raised to \$8.00 for today (ceiling \$30.00)' <<<"$c4" && [ "$l4" = '[8,8]' ] \
  && grep -q -- '-c #alice-updates .*raised today.s cap to \$8.00' "$T/cap.args" && grep -q -- '-c #alice --mention raised `alice`.s cap to \$8.00 for today (was \$5.00' "$T/cap.args" \
  && ok "a dispatch over the day cap but under the owner's ceiling is NOT refused: the box raises today's cap to what it needs, charges it, and says so in one line in -updates and one to the owner" \
  || bad "the cap was not raised under the ceiling (rc=$r4, ledger=$l4): $c4 / $(cat "$T/cap.args" 2>/dev/null)"
: > "$T/cap.args"; CAP_CEIL=30 cap >/dev/null; CAP_CEIL=30 cap >/dev/null
l5=$(jq -c '[.alice.cap, .alice.usd, .alice.mentioned // "none"]' "$GH/.cc/state/member-spend.json" 2>/dev/null); n5=$(grep -c -- '--mention raised' "$T/cap.args")
c6=$(CAP_CEIL=30 cap); r6=$?; l6=$(jq -c '[.alice.cap, .alice.usd, .alice.mentioned // "none"]' "$GH/.cc/state/member-spend.json" 2>/dev/null)
[ "$l5" = '[24,24,"none"]' ] && [ "$n5" = 2 ] && [ "$r6" = 1 ] && grep -q 'over its \$30.00 ceiling, refused' <<<"$c6" \
  && [ "$l6" = "[24,24,\"$(date -u +%F)\"]" ] && grep -q -- '-c #alice --mention `alice` hit its \$30.00/day ceiling' "$T/cap.args" \
  && ok "…each raise is its own line to the owner, the raised cap is today's from then on, and the CEILING is where the box stops: the dispatch that would cross it is refused with the ceiling named and the once-a-day mention" \
  || bad "the ceiling did not hold (after two more: $l5, mentions=$n5; over: rc=$r6 ledger=$l6): $c6 / $(cat "$T/cap.args" 2>/dev/null)"
rm -f "$GH/.cc/state/member-spend.json"; : > "$T/cap.args"
# …and with no ceiling set the default is twice the cap, so a $5 cap raises once to $8 and refuses $16: the incident's
# shape recovers by itself on a box whose owner set only the cap, and a ceiling below the cap never lowers it.
c7=$(CAP_CEIL= cap); r7=$?; c8=$(CAP_CEIL= cap); r8=$?; l8=$(jq -c '[.alice.cap, .alice.usd]' "$GH/.cc/state/member-spend.json" 2>/dev/null)
rm -f "$GH/.cc/state/member-spend.json"; c9=$(CAP_CEIL=1 cap); r9=$?
[ "$r7" = 0 ] && grep -q 'raised to \$8.00 for today (ceiling \$10.00)' <<<"$c7" && [ "$r8" = 1 ] && grep -q 'over its \$10.00 ceiling' <<<"$c8" && [ "$l8" = '[8,8]' ] \
  && [ "$r9" = 1 ] && grep -q 'over its \$5.00 ceiling' <<<"$c9" \
  && ok "…the ceiling defaults to twice the cap when the owner set none, and one set below the cap is the cap" \
  || bad "the default ceiling is wrong (first rc=$r7 '$c7'; second rc=$r8 '$c8'; ledger $l8; ceiling<cap rc=$r9 '$c9')"
rm -f "$GH/.cc/state/member-spend.json"; : > "$T/cap.args"
# …and the other side of that same wall: INSIDE the boundary the very same command charges nothing and opens no
# window — it writes the brief and hands the daemon a `dispatch`, which is what charges the cap out here. A MEMBER
# SESSION NEVER RAISES ITS OWN CAP: the ceiling in ITS environment is nobody's — what crosses to the host is the brief
# and the loop count, no cap, no ceiling, and the ledger out here is untouched.
ci=$( ( cd "$GH/dev/alice" && env HOME="$GH" CC_MEMBER_SANDBOX=1 MEMBER_DAILY_USD=5 MEMBER_DAILY_CEILING_USD=1000 "$NB/cc" alice todo --go 'from inside' 2>&1 ) ); ri=$?
[ "$ri" = 0 ] && grep -q -- 'dispatch alice/todo --loop' "$T/cap.args" && ! grep -q -- '--mention' "$T/cap.args" \
  && ! grep -qi -- 'ceiling\|MEMBER_DAILY\|raised' "$T/cap.args" \
  && [ ! -f "$GH/.cc/state/member-spend.json" ] && grep -q 'from inside' "$GH/.cc/state/alice/todo/task.md" \
  && ok "…and inside the boundary the same dispatch is BROKERED, not charged: the brief is written to the workspace's own state dir and the daemon is asked to run it on the host, where the ledger, the cap and the ceiling actually live — a ceiling in the member's own environment raises nothing" \
  || bad "a dispatch from inside the boundary did not broker (rc=$ri, args='$(cat "$T/cap.args" 2>/dev/null)'): $ci"
rm -f "$GH/.cc/state/member-spend.json"
# NO CREDENTIAL, NO WINDOW — AND SOMEBODY IS TOLD (review-156d). cc-sandbox member refuses a workspace without its own
# credential, but it refused INSIDE the tmux window cc had already opened: a member's message autostarted a pane that died
# with the reason in it, the board row said running, and neither the member nor the owner heard a thing. cc now checks the
# file on the host before any window or board write — the session, the track session and a --go alike — and says so where
# it counts: ONE line in #<h> with the command that fixes it, the planning seat asked ONCE (a day-stamp beside the file; a
# request to the seat, cc-notify --ask, since a member-facing repo cannot promote itself to the owner's DM), nothing
# opened, nothing charged. Once, not each time (owner, 2026-09-04): the drive loop runs exactly this — `cc <repo>` — every
# 2 h, and a workspace waiting to be minted carried the same line in its channel for a day. A second stamp
# (credential-told) is what makes the channel line once; the owner's page is unchanged. Both now carry the event's
# producer id (`credential:alice`, and `:owner` for the page) — cc-slack's ledger is what makes "once" hold across
# every attempt the box makes (arch review 2026-09-08, rec 4); the stamps here are the guard in front of it.
# Same stub HOME and stub bots as the cap: the page is asserted on cc-notify's argv and never sent.
rm -f "$NB/cc-notify"; printf '#!/usr/bin/env bash\nprintf "NOTIFY: %%s\\n" "$*" >> "%s"\n' "$T/cap.args" > "$NB/cc-notify"; chmod +x "$NB/cc-notify"
# NC_SLACK_RC, not CAP_SLACK_RC: a `VAR=1 cap` above leaves that one set in this shell, and a stub post that "failed"
# would then never stamp anything. This block says for itself whether the channel heard the line.
nocred(){ ( env HOME="$GH" PATH="$T/stub:$B:$PATH" TMUX_STUB_LOG="$T/tmux.log" CC_CLAUDE=/bin/true CAP_SLACK_RC="${NC_SLACK_RC:-0}" "$NB/cc" "$@" 2>&1 ); }
rm -f "$GH/.cc/members/alice/credentials.json" "$GH/.cc/members/alice/credential-asked" "$GH/.cc/members/alice/credential-told"; : > "$T/cap.args"; : > "$T/tmux.log"
env HOME="$GH" "$B/cc-board" status alice todo queued >/dev/null 2>&1
n1=$(nocred alice); rn1=$?; n2=$(nocred alice todo); rn2=$?; n3=$(nocred alice todo --go x); rn3=$?
{ [ "$rn1" = 1 ] && [ "$rn2" = 1 ] && [ "$rn3" = 1 ] && grep -q 'no credential of its own' <<<"$n1$n2$n3" \
  && ! grep -q 'new-window' "$T/tmux.log" && [ "$(env HOME="$GH" "$B/cc-board" get alice todo status)" = queued ] \
  && [ "$(grep -c -- '^post -c #alice --major --id credential:alice mint incomplete' "$T/cap.args")" = 1 ] \
  && [ "$(grep -c -- '^NOTIFY: -t alice --ask --id credential:alice:owner -- .*needs a credential minted' "$T/cap.args")" = 1 ] \
  && [ -s "$GH/.cc/members/alice/credential-told" ] \
  && [ "$(cat "$GH/.cc/members/alice/credential-asked")" = "$(date -u +%F)" ] && [ ! -f "$GH/.cc/state/member-spend.json" ] \
  && grep -q 'cc-sandbox mint alice' <<<"$n1" && grep -q 'cc-sandbox mint alice' "$T/cap.args"; } \
  && ok "a workspace with no credential of its own opens NO window (session, track session, --go): #alice is told ONCE what to mint however often the box tries — three attempts, one line — the planning seat is asked once (a request, never his DM), the row never says running and nothing is charged" \
  || bad "a workspace without a credential still died in a pane, or said it more than once (rc=$rn1/$rn2/$rn3, status=$(env HOME="$GH" "$B/cc-board" get alice todo status 2>&1), tmux='$(tr '\n' '|' < "$T/tmux.log")', args='$(tr '\n' '|' < "$T/cap.args")'): $n1"
: > "$T/cap.args"; rm -f "$GH/.cc/members/alice/credential-told"   # a line nobody heard leaves no stamp: the next attempt says it again
NC_SLACK_RC=1 nocred alice >/dev/null; NC_SLACK_RC=1 nocred alice >/dev/null; p1=$(grep -c -- '^post -c #alice --major --id credential:alice mint incomplete' "$T/cap.args")
NC_SLACK_RC=0 nocred alice >/dev/null; p2=$(grep -c -- '^post -c #alice --major --id credential:alice mint incomplete' "$T/cap.args")
[ "$p1" = 2 ] && [ "$p2" = 3 ] && [ -s "$GH/.cc/members/alice/credential-told" ] \
  && ok "…and the once is a line somebody HEARD: a post that failed leaves no stamp and is tried again, and the attempt that lands is the one that stops the rest" \
  || bad "the channel line's stamp does not follow the post (failed=$p1, then=$p2, stamp=$(cat "$GH/.cc/members/alice/credential-told" 2>/dev/null))"
# …and "the post went out" is not "#alice heard it": with no such channel `cc-slack post` files the line in #alerts and
# still exits 0, so the stamp would call a member's channel told by a line that never reached it, for good.
: > "$T/cap.args"; rm -f "$GH/.cc/members/alice/credential-told"
NC_NO_CHAN=1 nocred alice >/dev/null; q1=$(grep -c -- '^post -c #alice --major --id credential:alice mint incomplete' "$T/cap.args")
NC_NO_CHAN= nocred alice >/dev/null; q2=$(grep -c -- '^post -c #alice --major --id credential:alice mint incomplete' "$T/cap.args")   # cleared, not omitted: an assignment prefixing a FUNCTION call stays set afterwards (see NC_SLACK_RC above)
[ "$q1" = 0 ] && [ "$q2" = 1 ] && [ -s "$GH/.cc/members/alice/credential-told" ] \
  && ok "…and with no #alice to post in, nothing is posted and nothing is stamped — the owner's page is the escalation, and the first attempt after that channel exists is the one that tells it" \
  || bad "the told-stamp was claimed without a channel to say it in (no-channel posts=$q1, then=$q2, stamp=$(cat "$GH/.cc/members/alice/credential-told" 2>/dev/null))"
: > "$T/cap.args"; rm -f "$GH/.cc/members/alice/credential-asked"   # a page nobody heard releases the stamp: the next attempt pages again
printf '#!/usr/bin/env bash\nprintf "NOTIFY: %%s\\n" "$*" >> "%s"; exit 1\n' "$T/cap.args" > "$NB/cc-notify"
nocred alice >/dev/null; nocred alice >/dev/null
[ "$(grep -c -- '^NOTIFY:' "$T/cap.args")" = 2 ] && [ ! -e "$GH/.cc/members/alice/credential-asked" ] \
  && ok "…and a page that failed leaves no day-stamp, so the next attempt pages again instead of inheriting silence" \
  || bad "a failed page kept its day-stamp (pages=$(grep -c -- '^NOTIFY:' "$T/cap.args"), stamp=$(cat "$GH/.cc/members/alice/credential-asked" 2>/dev/null))"
# A BLANK CREDENTIAL IS NOT A CREDENTIAL (2026-09-08). This wall asked `jq -e '.claudeAiOauth.accessToken'`, which is TRUE
# for "" — only false and null are falsy in jq — and "" is precisely what claude leaves in the file when a refresh is
# refused: token and refresh token emptied in place, expiresAt 0, scopes and subscriptionType intact. So the file passed
# both walls and a member's sub-project session started signed out: hours alive showing "Not logged in · Run /login",
# the board row saying running, its channel unanswered, injected messages never read, and nobody told. A blanked
# credential must refuse exactly as a missing one does, and NAME the blank: the fix is a re-mint, and nothing in the
# old line said so.
printf '#!/usr/bin/env bash\nprintf "NOTIFY: %%s\\n" "$*" >> "%s"\n' "$T/cap.args" > "$NB/cc-notify"; chmod +x "$NB/cc-notify"
: > "$T/cap.args"; : > "$T/tmux.log"; rm -f "$GH/.cc/members/alice/credential-asked" "$GH/.cc/members/alice/credential-told"
mkdir -p "$GH/.cc/members/alice"; echo '{"claudeAiOauth": {"accessToken": "", "refreshToken": "", "expiresAt": 0, "subscriptionType": "max"}}' > "$GH/.cc/members/alice/credentials.json"
b1=$(nocred alice); rb1=$?; b2=$(nocred alice todo); rb2=$?; b3=$(nocred alice todo --go x); rb3=$?
{ [ "$rb1" = 1 ] && [ "$rb2" = 1 ] && [ "$rb3" = 1 ] && ! grep -q 'new-window' "$T/tmux.log" \
  && grep -q 'no credential of its own' <<<"$b1" && [ "$(printf '%s\n' "$b1" "$b2" "$b3" | grep -c 'access token is EMPTY')" = 3 ] \
  && [ "$(env HOME="$GH" "$B/cc-board" get alice todo status)" = queued ] && [ ! -f "$GH/.cc/state/member-spend.json" ] \
  && [ "$(grep -c -- '^NOTIFY: -t alice --ask --id credential:alice:blank@[0-9]*:owner -- .*needs a credential minted.*access token is EMPTY' "$T/cap.args")" = 1 ]; } \
  && ok "a credential blanked by a refused refresh opens NO window either — session, track session and --go all refuse, the row stays queued, and the line the owner gets names the EMPTY token so he re-mints instead of hunting a live pane" \
  || bad "a blanked credential still started a session (rc=$rb1/$rb2/$rb3, status=$(env HOME="$GH" "$B/cc-board" get alice todo status 2>&1), tmux='$(tr '\n' '|' < "$T/tmux.log")', args='$(tr '\n' '|' < "$T/cap.args")'): $b1"
rm -f "$GH/.cc/members/alice/credentials.json" "$GH/.cc/members/alice/credential-asked" "$GH/.cc/members/alice/credential-told"
[ "$(printf '{"tool_name":"Bash","tool_input":{"command":"cc r t --go x"},"cwd":"%s"}' "$mf" | env HOME="$GH" CC_GUARD_ASKS="$T/asks" CC_ROLE=worker "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] && ok "a marked cwd beats an inherited CC_ROLE=worker (a marker only tightens)" || bad "member marker downgraded by CC_ROLE=worker"
[ "$(printf '{"tool_name":"Bash","tool_input":{"command":"cc r t --go x"},"cwd":"%s"}' "$GH" | env HOME="$GH" CC_GUARD_ASKS="$T/asks" CC_ROLE=member "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] && ok "CC_ROLE=member gates with no marker at all" || bad "CC_ROLE=member ignored"
[ "$(printf '{"tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"%s"}' "$mf" | CC_ROLE=member env PATH=/nonexistent /bin/bash "$B/cc-guard" >/dev/null 2>&1; echo $?)" = 2 ] && ok "guard refuses when jq is missing for a member too (no jq = no cwd = no marker walk)" || bad "member guard without jq"
# A REFUSAL IN A MEMBER-FACING CHANNEL IS A QUERY TO THE BOX, NOT A LINE IN THE MEMBER'S CHANNEL (owner 2026-09-04,
# #243). The member session gets its stderr line; ONE JSON line lands in the workspace's queries.spool with the
# right class (page = the owner could say yes, nopage = no yes exists); NOTHING is posted to the member's channel
# and the owner is not paged — cc-msg drains that spool to the box's queries session. The stub bots in $GH/bin are
# still watched: a member refusal must now reach neither of them.
QSP="$GH/.cc/state/member/queries.spool"   # the dir's name is the workspace's: $mf is $T/member
ask(){ rm -rf "$T/asks"; : > "$T/guard.args"; : > "$T/guard.err"
       printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s"}' "$1" "$2" | env -u CC_NOTIFY_LOG_ONLY HOME="$GH" CC_GUARD_ASKS="$T/asks" ${3:+CC_ROLE=$3} "$B/cc-guard" >/dev/null 2>"$T/guard.err"; echo $?; }
SEND="cc-slack post --file /tmp/carpet.png"   # the 2026-08-30 incident itself: a member asked twice for images
rm -f "$QSP"
[ "$(ask "$SEND" "$mf")" = 2 ] && ok "the member's request is still refused — the gate did not soften" || bad "member deny lost"
grep -q '^cc-guard: blocked — posting to the owner' "$T/guard.err" \
  && ok "...and the MEMBER session still gets its stderr line, saying why" || bad "nothing reached the member: $(cat "$T/guard.err")"
[ "$(wc -l < "$QSP" 2>/dev/null)" = 1 ] && jq -e 'select(.workspace == "member" and .class == "page" and (.reason | test("posting to the owner")) and (.command | test("carpet")))' "$QSP" >/dev/null 2>&1 \
  && ok "...and ONE query lands in the workspace's queries.spool — page class (the owner could say yes), naming the workspace, the command and the reason" || bad "no query recorded: $(cat "$QSP" 2>/dev/null)"
[ ! -s "$T/guard.args" ] \
  && ok "...and NOTHING is posted to the member's channel and the owner is not paged: the box's queries session answers it" || bad "a member refusal still reached Slack: $(cat "$T/guard.args")"
# same workspace, same reason, straight away: the session retrying must not fill the spool
printf '{"tool_name":"Bash","tool_input":{"command":"cc-slack post -c x hi"},"cwd":"%s"}' "$mf" | env -u CC_NOTIFY_LOG_ONLY HOME="$GH" CC_GUARD_ASKS="$T/asks" "$B/cc-guard" >/dev/null 2>&1
[ ! -s "$T/guard.args" ] && [ "$(wc -l < "$QSP")" = 1 ] && ok "one query per workspace+reason per TTL, however often the session retries" || bad "the deny sprayed: $(cat "$T/guard.args") $(cat "$QSP")"
[ "$(ask "$SEND" "$mf")" = 2 ] && [ "$(wc -l < "$QSP")" = 2 ] && ok "...and a fresh window records again (the TTL is a delay, not a mute)" || bad "the ask never comes back"
: > "$T/guard.args"; rm -f "$QSP"; [ "$(ask "gh pr merge 1" "$wt" worker)" = 2 ] && [ ! -s "$T/guard.args" ] && [ ! -e "$QSP" ] \
  && ok "a WORKER deny is untouched: it has a board, a journal and STATUS: BLOCKED, and posts nothing, records nothing" || bad "a track deny posted or recorded: $(cat "$T/guard.args")"
: > "$T/guard.args"; [ "$(ask "gh pr merge 1" "$GH")" = 0 ] && [ ! -s "$T/guard.args" ] \
  && ok "the owner's own sessions are unaffected — not gated, and nothing posted anywhere" || bad "an ungated cwd posted: $(cat "$T/guard.args")"
: > "$T/guard.args"; rm -rf "$T/asks"
[ "$(ask "cc-config list" "$mf")" = 2 ] && ok "the box's config is not a member's to read — its one sanctioned reader is denied too" || bad "cc-config list slipped the member gate"
[ "$(ask "cc-config set SLACK_APP_TOKEN x" "$mf")" = 2 ] && ok "...nor to rewrite" || bad "cc-config set slipped the member gate"
: > "$T/guard.args"; rm -rf "$T/asks"; find "$GH/.cc/state" -name queries.spool -delete 2>/dev/null   # leave the harness state as found
printf '{"tool_name":"Bash","tool_input":{"command":"gh pr merge 1"},"cwd":"%s"}' "$GH" | env -u CC_NOTIFY_LOG_ONLY HOME="$GH" CC_GUARD_ASKS="$T/asks" CC_ROLE=member "$B/cc-guard" >/dev/null 2>&1; rcm=$?
NQS="$GH/.cc/state/_nomarker/queries.spool"
[ "$rcm" = 2 ] && [ ! -s "$T/guard.args" ] && [ "$(wc -l < "$NQS" 2>/dev/null)" = 1 ] \
  && jq -e 'select(.workspace == "_nomarker" and .class == "page")' "$NQS" >/dev/null 2>&1 \
  && ok "CC_ROLE=member with no marker: still refused, nothing posted or paged by the guard — and with no workspace to name, the query is filed under the reserved _nomarker key the host drains" || bad "markerless member ask: rc $rcm $(cat "$T/guard.args") $(cat "$NQS" 2>/dev/null)"
rm -f "$NQS"
: > "$T/guard.args"; rm -rf "$T/asks"; rm -f "$QSP"   # …and the deny with no yes in it: refused, recorded as nopage, owner asleep
[ "$(ask "cc r t --go x" "$mf")" = 2 ] && [ ! -s "$T/guard.args" ] && jq -e 'select(.class == "nopage")' "$QSP" >/dev/null 2>&1 \
  && ok "a member dispatch is refused and recorded as a nopage query — nothing in the channel, and the owner is not paged: it was never his to approve for them (00:03Z)" || bad "a member dispatch paged or posted: $(cat "$T/guard.args") $(cat "$QSP" 2>/dev/null)"
echo "== every interactive session starts in auto mode =="
# The owner had to press shift+tab in each one he opened (2026-09-04). Auto mode is a HARNESS flag, so it belongs on
# the argv of every launcher that opens a session — a --go worker already carries it from cc-loop. It is the
# permission prompt and nothing else: cc-guard is a hook and still denies what it denies, in any mode.
# A copy of cc with a recording claude beside it: the assertion is the argv the launcher actually built.
AM="$T/am"; mkdir -p "$AM" "$GH/dev/other" "$GH/.cc/worktrees/other/w"
cp "$B/cc" "$AM/cc"; for h in "$B"/cc-*; do ln -sf "$h" "$AM/$(basename "$h")"; done   # cc resolves every helper through its own BIN
rm -f "$AM/cc-sandbox"   # …and only the sandbox is the stub, so the member launcher's inner argv is visible (a copy, never a write through a symlink)
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s"\n' "$T/am.argv" > "$AM/cc-sandbox"; chmod +x "$AM/cc-sandbox"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s"\n' "$T/am.argv" > "$T/am-claude"; chmod +x "$T/am-claude"
am(){ env HOME="$GH" PATH="$B:$PATH" CC_CLAUDE="$T/am-claude" "$AM/cc" "$@" </dev/null >/dev/null 2>&1; }   # </dev/null: every stanza ends in `exec bash`
amiss=""
: > "$T/am.argv"; am __runmain other;             grep -q -- '--permission-mode auto' "$T/am.argv" || amiss="$amiss __runmain"
: > "$T/am.argv"; am __run other w;               grep -q -- '--permission-mode auto' "$T/am.argv" || amiss="$amiss __run"
: > "$T/am.argv"; am __runorch other a1;          grep -q -- '--permission-mode auto' "$T/am.argv" || amiss="$amiss __runorch"
: > "$T/am.argv"; am __runplain other;            grep -q -- '--permission-mode auto' "$T/am.argv" || amiss="$amiss __runplain"
: > "$T/am.argv"; am __runnext other/w hid1 sid1; grep -q -- '--permission-mode auto' "$T/am.argv" || amiss="$amiss __runnext"
: > "$T/am.argv"; am __runmember other "";        grep -qE -- '^member other .*-- .*--permission-mode auto' "$T/am.argv" || amiss="$amiss __runmember"
[ -z "$amiss" ] && ok "cc opens every session in auto mode — planning, track, orch, plain, handoff successor, and the member one inside the boundary" \
  || bad "these launchers still start in manual mode:$amiss"
# The box's own always-on Remote-Control session is the seventh and cannot be run from here (it waits for the
# internet and never returns), so its launch line is read instead.
grep -q -- '"\$CLAUDE" --permission-mode auto --remote-control' "$B/cc-rc" \
  && ok "…and so does the box's own boot session (cc-rc)" || bad "cc-rc still starts in manual mode"
rm -rf "$AM" "$GH/.cc/worktrees/other" "$GH/.cc/state/other"; rm -f "$GH/.cc/boards/other".*   # leave the stub HOME as this stanza found it
fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
