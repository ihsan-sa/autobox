#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# model-fallback.sh — the stanza "model fallback (cc-model + cc-limit)", run alone on the fixtures it stands on.
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
if stanza "model fallback (cc-model + cc-limit)"; then
# own HOME and own tmux server (TMUX unset, TMUX_TMPDIR into $T): the live sessions' models are never touched
MH="$T/mh"; mkdir -p "$MH/.cc/state" "$T/fb"; printf '#!/usr/bin/env bash\ncat\n' > "$T/fb/cc-loop"; chmod +x "$T/fb/cc-loop"
cat > "$T/probeclaude" <<'F'
#!/usr/bin/env bash
printf '{"is_error":false,"num_turns":1,"total_cost_usd":0.001,"result":"ok"}'
F
chmod +x "$T/probeclaude"
ME(){ env -u TMUX TMUX_TMPDIR="$T" HOME="$MH" CC_TMUX_SESSION=_ccmodel CC_MODEL_PROC=cat \
      CC_NOTIFY_LOG="$MH/.cc/notify.log" CC_LIMIT_STAMP="$MH/.cc/state/claude-limit" CC_STATUSLINE_DIR="$MH/.cc/state/statusline" \
      CC_MODEL_PRIMARY='claude-fable-5[1m]' CC_MODEL_FALLBACK=claude-opus-5 CC_MODEL_CHAIN='claude-fable-5 claude-opus-5 claude-sonnet-5' "$@"; }   # the fixture pins its chain: the shipped one has no Fable rung since 2026-09-23
M(){ ME "$B/cc-model" "$@"; }
muntil(){   # how `cc-model status` must render the override's own until: the clock alone today, dated on any other
            # day. HH:MMZ alone made a 24-hour override read as one that lapsed hours ago (2026-09-02).
  local t; t=$(cut -f3 "$MH/.cc/state/model-override" 2>/dev/null)
  [ "$(date -u -d "@$t" +%F)" = "$(date -u +%F)" ] && date -u -d "@$t" +%H:%MZ || date -u -d "@$t" +%FT%H:%MZ; }
MT new-session -d -s _ccmodel -n sess 'bash -c "cat; true"'
MT new-window -d -t _ccmodel -n wkr "bash -c '$T/fb/cc-loop; true'"   # a worker pane: cc-loop is its child and claude a grandchild
sleep 1
[ "$(M status)" = fable ] && ok "cc-model status: fable while nothing is limited" || bad "cc-model status: $(M status)"
[ "$(M current)" = 'claude-fable-5[1m]' ] && ok "cc-model current names the box's primary with no override" || bad "cc-model current: $(M current)"
[ -z "$(M forced)" ] && ok "cc-model forced is empty with no override — the old 'current' meaning, moved not dropped" || bad "cc-model forced leaked a model"
# A DISAGREEMENT BETWEEN WHAT THE BOX DISPATCHES AND WHAT IS RUNNING IS SAID OUT LOUD (2026-09-07): about 31 windows
# were on the harness default and nothing anywhere reported one, because the only pass that looks at a live session's
# model retunes same-family only. tick reads cc-statusline's own per-session record — never a pane, which may merely
# NAME a model — and writes one row: moving a running session stays the retune pass's job, and this must not do it.
mkdir -p "$MH/.cc/state/statusline"
printf '{"session_id":"agrees","model":"claude-fable-5[1m]","raw":{}}' > "$MH/.cc/state/statusline/agrees.json"
printf '{"session_id":"astray","model":"claude-opus-5","raw":{}}'      > "$MH/.cc/state/statusline/astray.json"
ME "$B/cc-model" tick
{ [ "$(grep -c $'\tmismatch\t' "$MH/.cc/state/model.log")" = 1 ] \
  && grep -q $'\tmismatch\tclaude-opus-5\tastray — this box dispatches claude-fable-5\[1m\]' "$MH/.cc/state/model.log" \
  && [ "$(M status)" = "fable — 1 session on another model" ] && [ ! -f "$MH/.cc/state/model-override" ]; } \
  && ok "cc-model tick reports the one session running something other than the model the box dispatches — named in the log, counted in status, and nothing switched or typed" \
  || bad "mismatch unreported: rows=$(grep -c $'\tmismatch\t' "$MH/.cc/state/model.log") status=$(M status)"
rm -rf "$MH/.cc/state/statusline"; : > "$MH/.cc/state/model.log"   # the cases below assert a bare `fable` status
printf '{"is_error":true,"result":"claude-fable-5: You are out of usage credits. Run /usage-credits to keep using Fable 5.","total_cost_usd":0}' > "$T/cred.json"
ME "$B/cc-limit" check "$T/cred.json" >/dev/null
# USAGE CREDITS ARE NOT A LIMIT (2026-09-04): one model this account cannot run, and no reset lifts that. No stamp —
# cc-model is told instead, records fable as unavailable, moves the box off it and says so. The record is cleared
# right after, so the limit cases below start from a box on its primary.
{ [ ! -e "$MH/.cc/state/claude-limit" ] && grep -q '^fable' "$MH/.cc/state/model-unavailable" 2>/dev/null \
  && [ "$(M status)" = "opus until probe — fable is not available to this account" ]; } \
  && ok "cc-limit: an exhausted credit balance is not a limit — no stamp, fable recorded as unavailable, the box moved off it and status says so" \
  || bad "credits read wrong: stamp=$([ -e "$MH/.cc/state/claude-limit" ] && echo yes || echo no) status=$(M status)"
# The brief: "live-host and account assertions (tutor credentials, account/model availability) move out of PR gates
# into monitoring." The account/model cases above assert on a fixture HOME and a fixture refusal, never on what this
# account can run today — that is cc-model tick's to watch on the box. Asserted, so a case that starts reading the
# live account is caught here rather than as a landing red on a day the account changes.
{ [ "$MH" != "$HOME" ] && [ "$(ME sh -c 'printf %s "$HOME"')" = "$MH" ] \
  && [ "$(ME sh -c 'cat "$HOME/.cc/state/model-unavailable"' | cut -f1)" = fable ]; } \
  && ok "the account/model-availability cases read a fixture home and its record, never this box's live account" \
  || bad "an account/model case reached past its fixture home ($MH)"
rm -f "$MH/.cc/state/claude-limit" "$MH/.cc/state/model-unavailable" "$MH/.cc/state/model-override" "$MH/.cc/state/model-seen" "$MH/.cc/state/model-refused"   # model-refused: that real refusal would hold the probe below for an hour
: > "$MH/.cc/state/model.log"; : > "$MH/.cc/notify.log"   # …and the move it just made: one switch per 10 min, so a switch row
                                                          # left here holds every case below on the anti-flap gap, and the
                                                          # credits line would be counted as the limit's notify
printf '{"is_error":true,"result":"claude-fable-5: You have hit your usage limit. Your limit resets at 11:40.","total_cost_usd":0}' > "$T/fab.json"
ME env CC_LIMIT_OBSERVER=worker-a "$B/cc-limit" check "$T/fab.json" >/dev/null
[ "$(cut -f4 "$MH/.cc/state/claude-limit")" = fable ] && ok "cc-limit records the limited model (stamp field 4)" || bad "stamp model: $(cut -f4 "$MH/.cc/state/claude-limit" 2>/dev/null)"
# ONE run's limit is not the box's: on 2026-09-04 one worker's 09:13Z stamp moved every session for six hours while
# opus went on answering. A second run has to hit the same limit before anything but that run is moved.
[ "$(M status)" = fable ] && ok "one run's limit leaves every other session on the primary model" || bad "one run's limit moved the box: $(M status)"
ME env CC_LIMIT_OBSERVER=worker-b "$B/cc-limit" check "$T/fab.json" >/dev/null   # a second worker hits the same limit
{ [ "$(M status)" = "opus until $(muntil)" ] && [ "$(cut -f3 "$MH/.cc/state/model-override")" -gt "$(date -u +%s)" ]; } && ok "a fable limit two runs hit puts the box on opus until the reset, dated whenever that reset is not today" || bad "cc-model status after a fable limit: $(M status), want opus until $(muntil)"
[ "$(M current)" = claude-opus-5 ] && ok "cc-model current feeds --model to new sessions and workers" || bad "cc-model current: $(M current)"
sleep 1
MT capture-pane -p -t _ccmodel:sess | grep -q '/model claude-opus-5' && ok "switch typed /model into the live interactive session" || bad "nothing typed into the session"
MT capture-pane -p -t _ccmodel:wkr | grep -q '/model' && bad "typed into a headless worker window!" || ok "headless worker window (cc-loop) skipped"
n=$(grep -c ' model' "$MH/.cc/notify.log" 2>/dev/null)
{ [ "${n:-0}" = 0 ] && grep -q $'\tswitch\tclaude-opus-5\t' "$MH/.cc/state/model.log"; } && ok "a switch posts nothing to the owner and is recorded once in model.log" || bad "switch notify count: $n / model.log switch rows: $(grep -c $'\tswitch\t' "$MH/.cc/state/model.log")"
ME "$B/cc-limit" check "$T/fab.json" >/dev/null   # the same limit again
[ "$(grep -c $'\tswitch\t' "$MH/.cc/state/model.log")" = 1 ] && ok "a second hit on the same limit is a no-op (idempotent)" || bad "switch not idempotent"
mnow=$(date -u +%s); printf 'claude-opus-5\t%s\t%s\ttest\t0\n' "$((mnow-600))" "$((mnow-60))" > "$MH/.cc/state/model-override"
: > "$MH/.cc/state/model.log"   # forget that switch: the 10-min anti-flap gap is not what this case is about
rm -f "$MH/.cc/state/claude-limit"   # …and the reset this case is about HAS passed, so its stamp goes with it: a stamp
                                     # that still names fable is a probe that cannot tell (it would re-switch anyway)
nl0=$(wc -l < "$MH/.cc/notify.log")
ME env CC_CLAUDE="$T/probeclaude" "$B/cc-model" tick
{ [ ! -f "$MH/.cc/state/model-override" ] && [ "$(M status)" = fable ]; } && ok "tick restores fable once the reset passed and the probe answered" || bad "override survived a successful probe"
sleep 1
# THE LIFT HANDS A SESSION BACK; IT DOES NOT RETYPE IT (owner, 2026-09-18). A window that belongs on the primary
# gets `cc-handoff --overlap`, and the `/model` line the restore used to type is gone. cc-handoff does not run to
# completion here: it works on `main:<window>` and this fixture's tmux server has no `main`, on purpose, so it
# refuses and its refusal is the row's tail. What this asserts is the ask, and that the pane was left alone. The
# card a window that is not major gets, and the 👍 that runs `cc-model return`, stay in cc-model's own selfcheck:
# neither may reach Slack from here.
mrows=$(grep -c $'\thandoff\t' "$MH/.cc/state/model.log")
{ ! MT capture-pane -p -t _ccmodel:sess | grep -qF '/model claude-fable-5[1m]'; } && [ "$mrows" = 1 ] \
  && grep -qF $'\thandoff\tclaude-fable-5[1m]\t_ccmodel:sess' "$MH/.cc/state/model.log" \
  && ok "the lift asks cc-handoff for the live session and types no /model into it" \
  || bad "restore: handoff rows=$mrows, typed=$(MT capture-pane -p -t _ccmodel:sess | grep -c 'claude-fable-5\[1m\]')"
n=$(tail -n +$((nl0+1)) "$MH/.cc/notify.log" | grep -c 'is back'); [ "$n" = 0 ] && ok "a restore posts nothing to the owner: the handoff row above is its record" || bad "restore notify count: $n"
# a live pane that mentions a limit: the probe decides, and one line fires once
cat > "$T/failprobe" <<'F'
#!/usr/bin/env bash
printf '{"is_error":true,"result":"You have hit your usage limit. Your limit resets at 11:40.","total_cost_usd":0}'; exit 1
F
chmod +x "$T/failprobe"
rm -f "$MH/.cc/state/model-override" "$MH/.cc/state/claude-limit" "$MH/.cc/state/model-seen"; : > "$MH/.cc/state/model.log"
mline(){ MT send-keys -t _ccmodel:sess -l -- "$1"; sleep 0.3; MT send-keys -t _ccmodel:sess Enter; sleep 0.5; }
# EACH LINE NAMES ITS MODEL, the way the CLI writes one. The scan probes a pane line only when the pane names the
# family the box is on, and these two lines took that name from the `/model claude-fable-5[1m]` the restore used
# to type here. With the lift handing sessions back instead, both read as Opus's limit and neither case tested
# anything (PR #533's gate, 2026-09-19).
mline "Claude usage limit reached for Fable 5. Your limit resets at 11:40."
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE="$T/probeclaude" "$B/cc-model" tick
[ "$(M status)" = fable ] && ok "a pane that mentions a limit while the model still answers does not switch" || bad "pane scan switched on a docs/question line: $(M status)"
mline "Claude usage limit reached for Fable 5. Your limit resets at 12:40."
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE="$T/failprobe" "$B/cc-model" tick
[ "$(M status)" = "opus until probe" ] && ok "a real limit line in a live pane switches the box (probe agrees)" || bad "pane scan: $(M status)"
rm -f "$MH/.cc/state/model-override"; : > "$MH/.cc/state/model.log"
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE="$T/failprobe" "$B/cc-model" tick
[ "$(M status)" = fable ] && ok "the same pane line never fires twice (per-window hash)" || bad "pane line fired again"
mline "Claude usage limit reached for Fable 5. Your limit resets at 13:40."
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE=/nonexistent/claude "$B/cc-model" tick
[ "$(M status)" = fable ] && ok "a pane line with a probe that cannot run does not switch (unknown, not limited)" || bad "switched on an unrunnable probe: $(M status)"
# … and that line is NOT used up: the next tick, with a probe that runs, still switches (2026-08-27: one unrunnable
# probe swallowed the only limit line of the day and the box stayed on a model that would not answer)
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE="$T/failprobe" "$B/cc-model" tick
[ "$(M status)" = "opus until probe" ] && ok "a line an inconclusive probe could not judge fires again on the next tick" || bad "pane line was consumed by an unrunnable probe: $(M status)"
rm -f "$MH/.cc/state/model-override" "$MH/.cc/state/model-seen"; : > "$MH/.cc/state/model.log"
# the CLI says a credit balance is empty, not "usage limit" — same thing for us, and it exits non-zero
cat > "$T/creditprobe" <<'F'
#!/usr/bin/env bash
printf '{"subtype":"success","is_error":true,"result":"You'"'"'re out of usage credits. Switch to another model, or manage usage credits at claude.ai/settings/usage, to continue."}'; exit 1
F
chmod +x "$T/creditprobe"
mline "You are out of usage credits. Run /usage-credits to keep using Fable 5 or /model to switch models."
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE="$T/creditprobe" "$B/cc-model" tick
[ "$(M status)" = "opus until probe — fable is not available to this account" ] && ok "\"out of usage credits\" on a pane, confirmed by the probe, is a MOVE: fable recorded as not this account's, the box on opus, and status says which" || bad "credit exhaustion read wrong: $(M status)"
rm -f "$MH/.cc/state/model-override" "$MH/.cc/state/model-seen" "$MH/.cc/state/model-unavailable"; : > "$MH/.cc/state/model.log"
# the probe's OWN run failed (its budget cap, its turn cap): unknown — never "the model is limited"
cat > "$T/budgetprobe" <<'F'
#!/usr/bin/env bash
printf '{"subtype":"error_max_budget_usd","is_error":true,"result":null}'; exit 1
F
chmod +x "$T/budgetprobe"
mline "Claude usage limit reached for Fable 5. Your limit resets at 15:40."
ME env CC_MODEL_PROBE_EVERY=0 CC_CLAUDE="$T/budgetprobe" "$B/cc-model" tick
{ [ "$(M status)" = fable ] && grep -q 'error_max_budget_usd' "$MH/.cc/state/model.log"; } && ok "a probe that broke on its own budget is unknown, and says so in the log" || bad "budget-capped probe misread: $(M status)"
rm -f "$MH/.cc/state/model-override"; : > "$MH/.cc/state/model.log"
# a mid-conversation /model opens a "Switch model?" confirmation: unanswered, the session sits on the dialog and stays
# on the model that will not answer (2026-08-28: that is exactly what every live session did)
MT send-keys -t _ccmodel:sess -l -- "Switch model? 1. Yes, switch to Opus 5"; sleep 0.3; MT send-keys -t _ccmodel:sess Enter; sleep 0.5
ME env CC_MODEL_DIALOG_WAIT=0.5 "$B/cc-model" switch opus "dialog case" >/dev/null 2>&1
sleep 1
MT capture-pane -p -t _ccmodel:sess | tail -n 3 | grep -qx '1' && ok "a Switch-model confirmation is answered, so the switch actually takes" || bad "the switch left the confirmation dialog open"
rm -f "$MH/.cc/state/model-override" "$MH/.cc/state/model-seen" "$MH/.cc/state/claude-limit"; : > "$MH/.cc/state/model.log"
# THE CLI'S OWN LIMIT PROMPT (2026-09-01): it is not a line to be confirmed by a probe — answering one spends the very
# usage credits the prompt is offering. It is answered in the pane, and the box moves on the wording alone.
# The pane gets the dialog in the SHAPE the CLI draws it — the wording alone is deliberately not enough since the
# review of #155 (this file, cc-model's own header and the brief all quote it), so a one-line fixture proves nothing.
mline "You have reached your Fable 5 limit for this week."
mline "Continuing on Fable 5 uses usage credits."
mline "❯ Switch to Opus 5 (1M context) and continue"
mline "  Manage usage credits on claude.ai"
mline "Enter to confirm · Esc to cancel"
ME env CC_CLAUDE=/nonexistent/claude "$B/cc-model" tick   # a probe here could only fail: the prompt must not need one
[ "$(M status)" = "opus until $(muntil)" ] && ok "the CLI's own limit prompt moves the box with no probe at all, and the day it holds until is on the line — the prompt names no reset, so this one runs a day out" || bad "limit prompt did not switch: $(M status), want opus until $(muntil)"
grep -q 'answered' "$MH/.cc/state/model.log" && ok "and the prompt in that pane is answered, so the session is not left sitting on it" || bad "the limit prompt was left unanswered"
mnow=$(date -u +%s); printf 'claude-opus-5\t%s\t%s\tprompt\t0\n' "$((mnow-1200))" "$((mnow-60))" > "$MH/.cc/state/model-override"
: > "$MH/.cc/state/model.log"
ME env CC_CLAUDE="$T/probeclaude" "$B/cc-model" tick   # …and a probe that ANSWERS is not proof: it may be paying credits
{ [ "$(M current)" = claude-opus-5 ] && grep -q 'not probing' "$MH/.cc/state/model.log"; } && ok "no restore while that wording is still on a pane (a probe cannot tell who paid)" || bad "restored while the limit prompt was still on the pane: $(M status)"
# ── the retune pass INSIDE tick(), on a real pane — not only the decision function it calls ──
# A session the CLI last put on another id of the primary's OWN family (`claude-fable-5` while the box wants
# `claude-fable-5-1`, four times the cache-read price) is invisible to every family test in cc-model. This drives
# the whole pass: the pane, the typing, the `retune` row it writes and the throttle that reads that row back. The
# two are coupled by the shape of that row, and if they ever come apart this types /model into somebody's live
# session once a minute — so the last case here proves it is that row, and nothing else, that keeps it quiet.
MT kill-window -t _ccmodel:sess 2>/dev/null; MT new-window -d -t _ccmodel -n sess 'bash -c "cat; true"'; sleep 1
rm -f "$MH/.cc/state/model-override" "$MH/.cc/state/model-seen" "$MH/.cc/state/claude-limit"; : > "$MH/.cc/state/model.log"
mline "❯ /model claude-fable-5"
mline "  ⎿  Set model to Fable 5 and saved as your default for new sessions"
MR(){ ME env CC_MODEL_PRIMARY='claude-fable-5-1[1m]' CC_MODEL_DIALOG_WAIT=0.2 CC_CLAUDE=/nonexistent/claude "$B/cc-model" "$@"; }
mtyped(){ MT capture-pane -p -t _ccmodel:sess | grep -cF '/model claude-fable-5-1[1m]'; }
mretunes(){ grep -c "$(printf '\tretune\t')" "$MH/.cc/state/model.log" 2>/dev/null || echo 0; }
MR tick; sleep 1
{ [ "$(mtyped)" -ge 1 ] && [ "$(mretunes)" = 1 ]; } && ok "a pane the CLI left on the primary's OLD id is retuned by tick itself: /model <primary> typed into it, one \`retune\` row in model.log" || bad "retune pass did not fire: typed=$(mtyped) rows=$(mretunes) log=$(cat "$MH/.cc/state/model.log")"
mt1=$(mtyped)
MR tick; sleep 1
{ [ "$(mtyped)" = "$mt1" ] && [ "$(mretunes)" = 1 ]; } && ok "…and the next tick, inside CC_MODEL_RETUNE_GAP, types nothing more — the pane still reads as Fable 5, so without the throttle this would fire every 60 s" || bad "second tick retyped: typed=$(mtyped) was $mt1, rows=$(mretunes)"
ME env CC_MODEL_PRIMARY='claude-fable-5-1[1m]' CC_MODEL_DIALOG_WAIT=0.2 CC_MODEL_RETUNE_GAP=0 CC_CLAUDE=/nonexistent/claude "$B/cc-model" tick; sleep 1
{ [ "$(mtyped)" -gt "$mt1" ] && [ "$(mretunes)" = 2 ]; } && ok "…and it is that row that silences it: with the gap at 0 the same pane is retuned again, so the row the pass writes and the throttle that reads it cannot drift apart unnoticed" || bad "gap=0 did not retune again: typed=$(mtyped) was $mt1, rows=$(mretunes)"
for id in $(MT list-windows -t _ccmodel -F '#{window_id}' 2>/dev/null); do MT kill-window -t "$id"; done   # last window gone = that scratch server is gone

fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
