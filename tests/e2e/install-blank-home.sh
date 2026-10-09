#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# install-blank-home.sh — the stanza "install.sh on a blank HOME (the bare-clone bootstrap)", run alone on the fixtures it stands on.
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
if stanza "install.sh on a blank HOME (the bare-clone bootstrap)" always; then   # always: it drives install.sh through $IR/… , never $B/cc-foo, so the scan can never see what it reaches
# THIS tree, copied as a bare autobox clone (a dir not named core/ has no overlay), installed into an empty HOME with
# --no-services: nothing enabled or started, no privileges, nothing of this box's touched. ccbox/env is a token file
# and stays behind. The fixtures ($T) go with the run's EXIT trap.
IR="$T/autobox"; IH="$T/blank"; mkdir -p "$IR" "$IH"
tar -C "$B/.." --exclude=./ccbox/env --exclude=__pycache__ -cf - . | tar -C "$IR" -xf -
inst(){ ( cd "$IH" && env HOME="$IH" XDG_CONFIG_HOME="$IH/.config" USER=tester CC_BOX=testbox GIT_CEILING_DIRECTORIES="$T" "$IR/install.sh" --no-services ) >"$T/install.log" 2>&1; }   # XDG too: the installer writes global git config, and a fixture reads nobody's but its own
inst && ok "install.sh runs clean on a blank HOME (--no-services)" || bad "install.sh failed on a blank HOME: $(tail -3 "$T/install.log" | tr '\n' ' ')"
[ "$(readlink -f "$IH/bin/cc")" = "$IR/bin/cc" ] && [ "$(readlink -f "$IH/bin/cc-reconcile")" = "$IR/bin/cc-reconcile" ] && ok "bin/* linked into ~/bin from the installed tree" || bad "~/bin links missing or pointing elsewhere"
# the prune is scoped to what this tree linked: a stale link of its own (target left the tree) goes, a dangling
# link someone ELSE put in ~/bin stays — install.sh used to delete every dangling link in ~/bin, whoever made it
ln -s "$IR/bin/retired-script" "$IH/bin/retired-script"; ln -s "$T/never-ours" "$IH/bin/foreign"
inst
[ ! -L "$IH/bin/retired-script" ] && [ -L "$IH/bin/foreign" ] && ok "prune removes only this tree's stale ~/bin links — a foreign dangling link is left alone" || bad "prune scope: retired link $([ -L "$IH/bin/retired-script" ] && echo kept || echo gone), foreign link $([ -L "$IH/bin/foreign" ] && echo kept || echo gone)"
rm -f "$IH/bin/foreign"
miss=""; for u in $("$IR/bin/cc-units" link); do [ -L "$IH/.config/systemd/user/$u" ] || miss="$miss $u"; done
[ -z "$miss" ] && ok "every unit in the manifest is linked, cc-reconcile.timer included (switching on is the services step)" || bad "units not linked:$miss"
# the same prune, scoped the same way, for ~/.config/systemd/user: a unit a PR deletes must not leave its link
# dangling forever — that is how `systemctl --user --failed` reads not-found for good and stays red (case
# raised-a-deleted-unit-leaves-a-dangling-link-and-a-red: #483 deleted 10 units, 2026-09-15, none of their 10
# links went). A foreign dangling link in the same directory — the owner's or another tool's — is left alone.
ln -s "$IR/config/systemd-user/retired.timer" "$IH/.config/systemd/user/retired.timer"; ln -s "$T/never-ours" "$IH/.config/systemd/user/foreign.timer"
# and the enable link left in timers.target.wants/ for it — that one is what keeps the dead timer in --failed.
# A foreign dangling wants link (not in this tree, not pointing at a link the prune removed) stays.
mkdir -p "$IH/.config/systemd/user/timers.target.wants"
ln -s "$IH/.config/systemd/user/retired.timer" "$IH/.config/systemd/user/timers.target.wants/retired.timer"
ln -s "$IH/.config/systemd/user/gone-by-hand.timer" "$IH/.config/systemd/user/timers.target.wants/gone-by-hand.timer"
inst
{ [ ! -L "$IH/.config/systemd/user/timers.target.wants/retired.timer" ] && [ -L "$IH/.config/systemd/user/timers.target.wants/gone-by-hand.timer" ]; } && ok "a pruned unit's enable link in timers.target.wants goes with it — a foreign dangling wants link is left alone" || bad "wants prune scope: retired wants link $([ -L "$IH/.config/systemd/user/timers.target.wants/retired.timer" ] && echo kept || echo gone), foreign wants link $([ -L "$IH/.config/systemd/user/timers.target.wants/gone-by-hand.timer" ] && echo kept || echo gone)"
rm -f "$IH/.config/systemd/user/timers.target.wants/gone-by-hand.timer"
{ [ ! -e "$IH/.config/systemd/user/retired.timer" ] && [ -L "$IH/.config/systemd/user/foreign.timer" ]; } && ok "a unit's dangling link is pruned once its source file is gone — a foreign dangling link is left alone" || bad "systemd-user prune scope: retired link $([ -e "$IH/.config/systemd/user/retired.timer" ] && echo kept || echo gone), foreign link $([ -L "$IH/.config/systemd/user/foreign.timer" ] && echo kept || echo gone)"
rm -f "$IH/.config/systemd/user/foreign.timer"
{ [ -f "$IH/CLAUDE.md" ] && [ ! -L "$IH/CLAUDE.md" ] && grep -q '^# testbox — ' "$IH/CLAUDE.md" && grep -q 'Autonomy is the norm' "$IH/CLAUDE.md" && grep -q 'The owner approves' "$IH/CLAUDE.md" && grep -q '~/WORKING.md' "$IH/CLAUDE.md" && ! grep -q '<user>' "$IH/CLAUDE.md"; } && ok "~/CLAUDE.md seeded as a copy of the contract, <box>/<user> filled in, the rest left to the owner" || bad "~/CLAUDE.md not seeded as the box contract"
miss=""; for g in USAGE COMMS RUNBOOK; do [ -f "$IH/$g.md" ] || miss="$miss $g"; done
[ -z "$miss" ] && ok "the guides the contract points at exist at ~ (USAGE COMMS RUNBOOK; SLACK folded into COMMS)" || bad "guides missing:$miss"
[ "$(readlink -f "$IH/WORKING.md")" = "$IR/docs/WORKING.md" ] && ok "~/WORKING.md links to the tree's docs/WORKING.md" || bad "~/WORKING.md not linked"
# the one writing block: a template keeps a {{WRITING_BLOCK}} line and install.sh fills it from config/writing-prompt.md,
# so ~/CLAUDE.md and the agent types say what the system prompts say. The guide the block names is linked beside it.
blockn(){ python3 - "$IR/config/writing-prompt.md" "$1" <<'PY'
import sys; b = open(sys.argv[1]).read().strip(); t = open(sys.argv[2]).read(); print(t.count(b) if len(b) > 200 else -1, int("{{WRITING_BLOCK}}" in t))
PY
}
[ "$(blockn "$IH/CLAUDE.md")" = "1 0" ] && ok "the seeded ~/CLAUDE.md carries the writing block exactly once, and no unfilled placeholder" || bad "~/CLAUDE.md and the writing block: $(blockn "$IH/CLAUDE.md") (want 1 0)"
[ "$(blockn "$IR/templates/home/CLAUDE.md")" = "0 1" ] && ok "…and its template keeps the placeholder, never a copy of the text" || bad "templates/home/CLAUDE.md holds a copy of the block: $(blockn "$IR/templates/home/CLAUDE.md") (want 0 1)"
{ [ "$(readlink -f "$IH/WRITING.md")" = "$IR/docs/WRITING.md" ] && [ -s "$IH/WRITING.md" ] && grep -qF '~/WRITING.md' "$IR/config/writing-prompt.md"; } && ok "~/WRITING.md, the guide the block names, links to the tree's docs/WRITING.md" || bad "~/WRITING.md not linked, empty, or not the path the block names"
[ -f "$IH/.claude/settings.json" ] && env HOME="$IH" CC_SETTINGS_FILE="$IH/.claude/settings.json" "$IR/bin/cc-settings" check >/dev/null 2>&1 && ok "default ~/.claude/settings.json installed and satisfies the managed subset" || bad "settings.json missing or drifted from claude-managed.json"
# M4-2: the installed managed hooks pass check. Missing registrations are the control (cc-native is retired, so a
# PreToolUse hook and the Stop hook stand in for it).
jq '(.hooks.PreToolUse[] | .hooks) |= map(select(.command != "$HOME/bin/cc-subagent-bound hook")) | del(.hooks.Stop)' \
  "$IH/.claude/settings.json" > "$T/unapplied-native.json"
out=$(env HOME="$IH" CC_SETTINGS_FILE="$T/unapplied-native.json" "$IR/bin/cc-settings" check); rc=$?
[ "$rc" != 0 ] && grep -q 'UNAPPLIED: hook PreToolUse Stop' <<<"$out" \
  && ok "M4-2: the installed subset passes; missing managed hooks are reported UNAPPLIED without apply" \
  || bad "M4-2: native registration control: $out"
# the agent types, at ~/.claude/agents/ where the harness reads them. Copies, so the owner can tune one on the box —
# which is exactly why they need a stamp: an untouched copy still follows its template, an edited one is never
# overwritten. Both directions, because either failure is silent (a stale builder, or the owner's tuning gone).
filled(){ awk -v b="$IR/config/writing-prompt.md" '$0 == "{{WRITING_BLOCK}}" { while ((getline l < b) > 0) print l; close(b); next } { print }' "$1"; }   # the template as it installs
miss=""; for f in "$IR"/templates/home/agents/*.md; do n=$(basename "$f"); { filled "$f" | cmp -s - "$IH/.claude/agents/$n"; } && [ "$(blockn "$IH/.claude/agents/$n")" = "1 0" ] && [ "$(blockn "$f")" = "0 1" ] || miss="$miss $n"; done
[ -z "$miss" ] && ok "every agent type is installed at ~/.claude/agents/ with the writing block filled in exactly once ($(cd "$IR/templates/home/agents" && echo *.md | sed 's/\.md//g'))" || bad "agent types not installed or drifted:$miss"
echo "# the owner's own tuning" >> "$IH/.claude/agents/builder.md"; printf '\nthe template moved on.\n' >> "$IR/templates/home/agents/reviewer.md"; inst
grep -q "^# the owner's own tuning$" "$IH/.claude/agents/builder.md" && ok "an agent the owner edited by hand survives the next install" || bad "install.sh overwrote a hand-edited agent"
{ filled "$IR/templates/home/agents/reviewer.md" | cmp -s - "$IH/.claude/agents/reviewer.md"; } && ok "…and an untouched one follows its template when the template changes" || bad "a changed agent template never reached ~/.claude/agents"
# swapping the block is a file swap and no code: the next install carries it to an untouched agent, never to an edited one
printf '\nA swapped line.\n' >> "$IR/config/writing-prompt.md"; inst
{ grep -q '^A swapped line\.$' "$IH/.claude/agents/reviewer.md" && ! grep -q 'A swapped line' "$IH/.claude/agents/builder.md" && grep -q "^# the owner's own tuning$" "$IH/.claude/agents/builder.md"; } && ok "a swapped writing block reaches an untouched agent on the next install, and the hand-edited one is still kept" || bad "a swapped writing block did not reach ~/.claude/agents/reviewer.md, or it overwrote the edited builder"
# a symlink in that directory is never written through: a dangling one reads as absent to -e, and the cp would have
# landed on whatever it points at — here a path outside ~/.claude entirely
mv "$IH/.claude/agents/security-reviewer.md" "$T/moved-agent"; ln -s "$T/gone-agent" "$IH/.claude/agents/security-reviewer.md"; inst
{ [ ! -e "$T/gone-agent" ] && [ -L "$IH/.claude/agents/security-reviewer.md" ]; } && ok "a symlink at ~/.claude/agents/<type>.md is left alone, not written through" || bad "install.sh wrote through a dangling agent symlink"
rm -f "$IH/.claude/agents/security-reviewer.md"; mv "$T/moved-agent" "$IH/.claude/agents/security-reviewer.md"
# the second run is the deploy path (every landing re-runs install.sh): it must change nothing, and an existing
# ~/CLAUDE.md — here the owner's own — is never rewritten
echo "# mine" > "$IH/CLAUDE.md"
snap(){ ( cd "$IH" && { find . -printf '%P %y %l\n' | sort; find . -type f -exec md5sum {} + | sort; } | md5sum ); }
s1=$(snap); inst; s2=$(snap)
[ "$s1" = "$s2" ] && ok "a second install.sh run changes nothing (idempotent — the deploy path)" || bad "the second install.sh run changed the HOME"
[ "$(cat "$IH/CLAUDE.md")" = "# mine" ] && ok "an existing ~/CLAUDE.md is never rewritten" || bad "install.sh overwrote ~/CLAUDE.md"
[ "$(grep -c 'autobox PATH' "$IH/.bashrc")" = 1 ] && ok "~/.bashrc gets the PATH block once" || bad "PATH block appended more than once"
# git rerere, on for the box: a track branch is a chain of checkpoints, so one rebase replays the same conflict through
# every one of them (#194 wanted the same two lines resolved seven times). Global, because it must hold in every clone
# under ~/dev and in their worktrees — and only where the owner has said nothing.
gcg(){ env HOME="$IH" XDG_CONFIG_HOME="$IH/.config" git config --global "$@"; }
[ "$(gcg --get rerere.enabled)" = true ] && ok "install.sh switches git rerere on for the box — a conflict resolved once in a rebase is not resolved by hand again" || bad "rerere not enabled: '$(gcg --get rerere.enabled)'"
gcg rerere.enabled false; inst
[ "$(gcg --get rerere.enabled)" = false ] && ok "…and never over the owner's own answer: an explicit false stands" || bad "install.sh overwrote the owner's rerere setting"
fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
