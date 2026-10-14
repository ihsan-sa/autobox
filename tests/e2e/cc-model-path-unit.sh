#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# cc-model-path-unit.sh — the stanza "cc-model.path fires the switch (a transient path unit, a stamp, and no tick called)", run alone on the fixtures it stands on.
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
if stanza "cc-model.path fires the switch (a transient path unit, a stamp, and no tick called)"; then
# THE BRIEF'S "a test writes the stamp and sees the switch fire via the path unit" (2026-10-03). cc-model's own (p)
# cases read the unit files and call tick themselves, so nothing there proves that the path unit triggers anything.
# This builds a TRANSIENT copy of cc-model.path in the user manager with `systemd-run --user`: its Path*= lines are
# the shipped file's, moved from %h to a HOME of its own under $T, and its service runs this tree's cc-model, copied
# there byte for byte so its siblings (cc-notify, cc-slack, cc-msg, cc-config) are absent and nothing it does can
# leave that HOME. It runs under `env -i` with only what is set here: no tmux server (TMUX_TMPDIR), no claude, a
# three-rung chain (the shipped one has no rung to move to). A qualifying stamp is written at the watched path and
# the switch is waited for, 60 s at most; nothing here calls tick. The units are named per run, collected, and
# stopped and reset by the subshell's trap on any exit. The box's own cc-model units are never touched: no
# daemon-reload, nothing enabled. With no user bus it says SKIP and passes, as on a runner with no systemd.
PH="$T/pathunit"; PU="cc-model-e2e-$$"; PUD="$(dirname "$B")/config/systemd-user"
pu_bus=""; [ -n "${XDG_RUNTIME_DIR:-}" ] && pu_bus=$(systemctl --user is-system-running 2>/dev/null)
case "$pu_bus" in running|degraded|starting|initializing|maintenance) pu_bus=up ;; esac   # degraded is a bus: one failed unit
if [ "$pu_bus" != up ]; then
  echo "  · SKIP: no user systemd bus (XDG_RUNTIME_DIR ${XDG_RUNTIME_DIR:-unset}, is-system-running said '${pu_bus}'): cc-model.path is not driven here"
else
  mkdir -p "$PH/bin" "$PH/.cc/state" "$PH/.claude" "$PH/tmux"
  cp "$B/cc-model" "$PH/bin/cc-model"
  printf '{"switchModelsOnFlag":true,"autoContinueAtUsageLimit":false}\n' > "$PH/.claude/settings.json"   # both keys set: no line to anyone
  pu_lines=$(grep -E '^Path[A-Za-z]*=' "$PUD/cc-model.path" | sed "s#=%h/#=$PH/#")
  pu_props=(); while IFS= read -r l; do [ -n "$l" ] && pu_props+=("--path-property=$l"); done <<<"$pu_lines"
  { [ "${#pu_props[@]}" -ge 1 ] && ! grep -qvF "=$PH/" <<<"$pu_lines" && grep -qxF "PathChanged=$PH/.cc/state/claude-limit" <<<"$pu_lines" &&
    cmp -s "$B/cc-model" "$PH/bin/cc-model"; } \
    && ok "the transient unit watches cc-model.path's own ${#pu_props[@]} Path*= lines, each moved under its HOME (cc-limit's stamp among them), and runs this tree's cc-model" \
    || bad "the transient unit could not be built from cc-model.path: [$pu_lines]"
  ( pu_down(){ systemctl --user stop "$PU.path" "$PU.service" 2>/dev/null; systemctl --user reset-failed "$PU.path" "$PU.service" 2>/dev/null; return 0; }
    trap pu_down EXIT; trap 'exit 143' INT TERM HUP
    systemd-run --user --quiet --collect --unit="$PU" "${pu_props[@]}" \
      /usr/bin/env -i HOME="$PH" PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 TMUX_TMPDIR="$PH/tmux" \
        CC_TMUX_SESSION="_ccpath$$" CC_MODEL_PROC=cat CC_CLAUDE="$PH/no-claude" CC_CLAUDE_SETTINGS="$PH/.claude/settings.json" \
        CC_STATUSLINE_DIR="$PH/.cc/state/statusline" CC_MODEL_MEMBERS="$PH/.cc/members" CC_MODEL_TRANSCRIPTS="$PH/transcripts" \
        CC_MODEL_RETURN_CHANNEL='#nowhere' CC_NOTIFY_LOG_ONLY=1 CC_NOTIFY_LOG="$PH/notify.log" \
        CC_MODEL_PRIMARY='claude-fable-5-1[1m]' CC_MODEL_FALLBACK='claude-opus-5[1m]' CC_MODEL_CHAIN='claude-fable-5-1 claude-opus-5 claude-sonnet-5' \
        "$PH/bin/cc-model" tick >&2 || { echo "run=refused"; exit 0; }
    for _ in $(seq 50); do [ "$(systemctl --user is-active "$PU.path" 2>/dev/null)" = active ] && break; sleep 0.1; done
    echo "armed=$(systemctl --user is-active "$PU.path" 2>/dev/null)"
    echo "before=$([ -e "$PH/.cc/state/model-override" ] && echo override)$([ -e "$PH/.cc/state/model.log" ] && echo log)"
    pu_now=$(date -u +%s)   # two runs' stamp, an hour to its reset, naming the primary: what stamp_says_switch acts on
    printf '%s\tapi\t%s\tfable\taaaaaaaa,bbbbbbbb\n' "$((pu_now + 3600))" "$pu_now" > "$PH/.cc/state/claude-limit"
    pu_t0=$(date +%s%N); pu_n=0
    for _ in $(seq 120); do pu_n=$(grep -c "$(printf '\tswitch\t')" "$PH/.cc/state/model.log" 2>/dev/null); [ "${pu_n:-0}" -ge 1 ] && break; sleep 0.5; done
    echo "waited_ms=$(( ($(date +%s%N) - pu_t0) / 1000000 ))"; echo "switchrows=${pu_n:-0}"
    echo "after=$(cut -f1 "$PH/.cc/state/model-override" 2>/dev/null)"
    pu_down
    for _ in $(seq 20); do [ -z "$(systemctl --user list-units --all --no-legend "$PU.*" 2>/dev/null)" ] && break; sleep 0.1; done
    echo "left=$(systemctl --user list-units --all --no-legend "$PU.*" 2>/dev/null | wc -l)"
  ) > "$PH/out" 2> "$PH/run.err"
  pu(){ sed -n "s/^$1=//p" "$PH/out" | tail -1; }
  { [ -z "$(pu run)" ] && [ "$(pu armed)" = active ] && [ -z "$(pu before)" ]; } \
    && ok "systemd-run armed the path unit, and nothing ran before the stamp was written" \
    || bad "the path unit did not arm cleanly: run=[$(pu run)] armed=[$(pu armed)] before=[$(pu before)] err=[$(head -c 400 "$PH/run.err")]"
  { [ "$(pu after)" = 'claude-opus-5[1m]' ] && [ "$(pu switchrows)" = 1 ]; } \
    && ok "the stamp at the watched path switched that HOME to the fallback through the path unit alone, $(pu waited_ms) ms after the write, with no tick called here" \
    || bad "no switch within 60 s of the stamp: override=[$(pu after)] switch rows=[$(pu switchrows)] log=[$(cat "$PH/.cc/state/model.log" 2>/dev/null)] err=[$(head -c 400 "$PH/run.err")]"
  [ "$(pu left)" = 0 ] && ok "both transient units are gone afterwards: stopped, reset and collected" \
    || bad "$(pu left) transient unit(s) named $PU.* still listed after the stop"
  unset -f pu
fi   # the bus: a bare `fi` here would end the stanza for split.py

fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
