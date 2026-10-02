#!/usr/bin/env bash
# lib.sh — the setup every core/tests/e2e/<slug>.sh stands on, sourced as its first line. It is selftest.sh's
# preamble with the suite machinery taken out: no slots, lock, runner spill, reach scoping, prefetch, halves or
# quarantine. Each generated file runs one stanza alone, on the same fixtures, and ends on e2e_end.
# What stays: every CC_* the caller carried is dropped, every state path a driven tool writes goes under $T, the
# run is namespaced by $RUN, the fixture repo and the claude stubs, and the checks at the end that the run left
# the box's ~/.cc as it found it.
set -uo pipefail
for v in "${!CC_@}"; do case $v in CC_SELFTEST_*|CC_GREEN_DIR|CC_CONFIG_DENY) ;; *) unset "$v";; esac; done
export CC_NOTIFY_LOG_ONLY=1   # never push to the owner from tests
export CC_LIMIT_MIN_WAIT=1    # cc-limit test hook: any 'wait until the usage limit resets' is capped at 1 s
export CC_SPEND_TIER=autonomous   # the box's own spend tier (cc-tier) never colours a fixture: each --go below must start — and cc carries
                                  # it into the loop's tmux window (its `pre` list), where cc-loop asks the tier again; the case is by the CC_LOOP_TRIM one
exec </dev/null; unset CLAUDECODE "${!CLAUDE_@}"   # never inherit a tty nor the calling session's environment
E2E_FILE="$(readlink -f "$0")"                              # the generated file that is running
B="$(cd "$(dirname "$E2E_FILE")/../../bin" && pwd)"         # core/bin, the tools this tree ships
SELF="$(cd "$(dirname "$E2E_FILE")/.." && pwd)/selftest.sh" # stanza bodies read "$SELF" and its directory verbatim
# The file's SIGNALS are its own, not the launcher's, and it DIES WITH ITS LAUNCHER: bash cannot trap a signal that
# was ignored at entry (a nohup'd launch ignores HUP, and case H4 needs HUP at its default), so the file re-runs
# itself through python, which puts HUP/INT/QUIT/TERM back to default and sets PR_SET_PDEATHSIG. This shell waits.
if [ -z "${E2E_HELD:-}" ]; then
  export E2E_HELD=$$
  python3 -c 'import ctypes, os, signal, sys
for s in (signal.SIGHUP, signal.SIGINT, signal.SIGQUIT, signal.SIGTERM): signal.signal(s, signal.SIG_DFL)
try: ctypes.CDLL(None).prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG
except Exception: pass
if os.getppid() != int(sys.argv[1]): sys.exit(143)   # the holder died before the line above took hold
os.execv(sys.argv[2], sys.argv[2:])' "$$" "$BASH" "$E2E_FILE" "$@"; exit $?
fi
unset E2E_HELD   # children must not think they are already re-run
pass=0; fail=0; ok(){ pass=$((pass+1)); echo "  ✓ $1"; }; bad(){ fail=$((fail+1)); echo "  ✗ $1"; }
qbad(){ bad "$2"; }   # no quarantine here: a red case is red
RED_CASES=5
red(){ bad "$1"; grep -E '✗|✘|FAIL|Traceback' <<<"${2:-}" | head -n "$RED_CASES"; return 0; }
unred(){ sed -e 's/\([1-9][0-9]*\) failed/\1 red/g' -e 's/✗/·/g' -e 's/✘/·/g' -e 's/FAIL/red/g'; }
stanza(){ echo "== $1 =="; return 0; }   # every stanza a file carries runs: the file was picked for it
chk(){   # `chk cc-foo`: that tool's own selfcheck as one case. Red once is run once more (LOAD-BOUND, as in selftest.sh).
  local t=$1 o r rc keep flipped o2 r2
  o=$("$B/$t" selfcheck 2>&1); rc=$?
  r=$(grep -o "$t selfcheck: .*" <<<"$o" | tail -1)
  grep -qE '(: |, )0 failed' <<<"$r" && { ok "$r"; return 0; }
  if [ -n "$r" ] && [ "${CC_SELFTEST_RERUN:-1}" != 0 ]; then
    o2=$("$B/$t" selfcheck 2>&1); r2=$(grep -o "$t selfcheck: .*" <<<"$o2" | tail -1)
    if grep -qE '(: |, )0 failed' <<<"$r2"; then
      flipped=$(grep -E '✗|✘|FAIL' <<<"$o" | head -n "$RED_CASES" | sed 's/^ *//' | tr '\n' ';')
      ok "$r2 — LOAD-BOUND: $(unred <<<"$r") beside the suite, green alone; the cases that flipped: $(unred <<<"${flipped%;}")"; return 0
    fi
    [ -n "$r2" ] && { red "$t selfcheck: $r2 (and $r the first time — red alone as well, not load)" "$o2"; return 0; }
  fi
  [ -n "$r" ] && { red "$t selfcheck: $r" "$o"; return 0; }
  keep=/tmp/$t-selfcheck-$RUN.log; printf '%s\n' "$o" > "$keep" 2>/dev/null || keep=nowhere
  bad "$t selfcheck: no tally line — exit $rc, $(printf %s "$o" | wc -c) bytes, kept in $keep"
  [ -n "$o" ] && tail -3 <<<"$o" | sed 's/^/      /'
  return 0; }
RUN=$$; REPO=_cctest$RUN; T=~/.cc/selftest-$RUN; mkdir -p "$T"; : > "$T/born"   # born: what "modified during this run" means below
export CC_SELF_LAND_EXCEPT=$REPO         # every project lands itself by default, and the box's own config never decides a fixture: a case that means the grant sets this itself
export CC_NOTIFY_LOG="$T/notify.log"      # not the box's own ~/.cc/notify.log: runs would count each other's lines
export CC_ROOM_DIR="$T/room" CC_WORKER_CAP=1000 CC_WORKER_PACE_MARGIN=100   # cc-room: a fixture --go never queues behind the box's real loops or its five-hour pace, and never takes one of its slots
# …nor behind the box's LOAD: cc-room also asks the lander's overloaded(), and at a load of twice the cores every
# fixture --go sat in `cc-room admit` and never ran (say-go-loop red at two unrelated landings, 09-29, load 14-17 on
# 6 cores). A calm load average and calm PSI of the run's own, and the default factor whatever the caller carried.
mkdir -p "$T/psi"; echo "0.00 0.00 0.00 1/1 1" > "$T/loadavg"
for k in cpu memory io; do echo "some avg10=0.00 avg60=0.00 avg300=0.00 total=0" > "$T/psi/$k"; done
export LANDER_LOADAVG="$T/loadavg" LANDER_PSI_DIR="$T/psi" LANDER_LOAD_FACTOR=2
export CC_LIMIT_STAMP="$T/claude-limit"   # not the box's live stamp: a test limit must never make a real loop wait
export CC_FAILURES="$T/failures"          # not ~/.cc/failures: the loop stops and red gates below are fixtures, and the
                                          # ledger counts what it holds (cc-loop stop_record, cc-green red)
export CC_HANDOFF_DIR="$T/handoff"        # not ~/.cc/state/handoff: an overlap case writes REAL records, and they
export CC_HANDOFF_KICK_WAIT=0          # every real --overlap leaves a detached --kick child: with a wait it polls tmux for
export CC_HANDOFF_NO_KICK=1   # ...and no --kick child at all: a fixture successor never boots, and a kick that cannot land pages the owner
                                          # 4 min and recreates $T/ctx/handoff.log after the trap; with none it gives up at once
                                          # outlived the run — `cc-handoff --status` was listing a week of _cctest
                                          # successors, and cc-guard walks that directory on every single call.
# EVERY OTHER STATE PATH A DRIVEN TOOL WRITES WITHOUT BEING TOLD WHERE, under $T as well — the whole set, here, not
# each one at the stanza that first noticed it. #501 dropped CC_CTX_RECORDS from its stanza and every gate run of
# that branch appended _cctest rows to the owner's live handoffs.jsonl for 15 h (90 rows; the App Home counted
# them). A case may still narrow one of these to its own subdir; what it may not do is leave one pointing at ~/.cc.
# The check at the end of this file is what says whether this list is complete: a run's marker found in a box file.
export CC_CTX_RECORDS="$T/ctx"                 # cc-handoff's ledger (state/context/handoffs.jsonl)
export CC_STATUSLINE_DIR="$T/statusline"       # cc-context/cc-statusline per-session records
export CC_GUARD_ASKS="$T/guard-asks"           # cc-guard's refusal spool (~/.cc/guard-asks)
export CC_SCOPE_DIR="$T/scope"                 # cc-scope's ask ledger
export CC_QUERIES_STATE="$T/queries-state"     # cc-slack's spool root for member queries
export CC_LIMIT_SEEN="$T/limit-seen" CC_LIMIT_RECORD="$T/limit-interrupted" CC_LIMIT_NUDGED="$T/limit-nudged" CC_LIMIT_RESUMED="$T/limit-resumed"   # cc-limit's records (M10 hits a limit for real)
MT(){ env -u TMUX TMUX_TMPDIR="$T" tmux "$@"; }   # the model section's scratch tmux server: own socket, under $T
wins(){ tmux list-windows -t main -F '#{window_id} #W' 2>/dev/null | awk -v r="$1" '$2==r || index($2,r"/")==1 {print $1}'; }
KIDS=""   # long-lived fixtures started below, and each prefetched selfcheck until its chk reaps it; the trap takes
          # each one's whole process group, by PID, never by pattern — so a pid leaves this list when it is reaped
cleanup(){ rc=$?; trap - EXIT
  for p in $KIDS; do pg=$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')
    if [ -n "$pg" ] && [ "$pg" != "$(ps -o pgid= -p $$ | tr -d ' ')" ]; then kill -TERM -- -"$pg" 2>/dev/null; else kill -TERM "$p" 2>/dev/null; fi; done
  MT kill-server 2>/dev/null   # the scratch server and its panes die WITH the run: one `cat` fixture outlived a run by 2.5 h
  for id in $(wins "$REPO"); do tmux kill-window -t "$id"; done
  rm -rf "$T" ~/dev/$REPO ~/.cc/worktrees/$REPO ~/.cc/state/$REPO ~/.cc/boards/$REPO.json ~/.cc/boards/$REPO.lock ~/.claude/projects/$REPO-ctx
  ( exec 9>~/.claude.json.lock; flock 9; jq '.projects |= with_entries(select(.key | test("/'"$REPO"'(/|$)") | not))' ~/.claude.json > ~/.claude.json.$RUN.sel && mv ~/.claude.json.$RUN.sel ~/.claude.json ) 2>/dev/null   # leave no trust entries behind
  rm -f ~/.claude.json.$RUN.sel; exit $rc; }
trap cleanup EXIT INT TERM HUP
# THE BOX'S OWN FLAGS, AS THIS RUN FOUND THEM. Files a person set by hand and no daemon rewrites: `cc` reads
# ~/.cc/slack/enabled straight from $HOME, no CC_* names it, and a case that toggled it left the box's Slack off for
# 12 min (2026-09-19). Compared at the end: presence, inode, size and mtime at the resolution the filesystem keeps —
# the flag is an empty file, so a rm and a touch inside one second are the same size and the same second; the inode
# and the fraction are what say it happened. A toggle off and on again is a change too.
BOX_FLAGS="config slack/enabled github-deny github-deny.gitconfig"
box_flags(){ local f; for f in $BOX_FLAGS; do stat -c "$f %i %s %.Y" ~/.cc/$f 2>/dev/null || echo "$f absent"; done; }
box_flags > "$T/flags.before"
git init -q --bare "$T/remote.git"; git clone -q "$T/remote.git" ~/dev/$REPO 2>/dev/null
( cd ~/dev/$REPO && git config user.email t@t && git config user.name t && echo x > r.md && git add -A && git commit -qm init && git branch -M main && git push -q -u origin main && git remote set-head origin -a >/dev/null 2>&1 )
export CC_CLAUDE=/bin/true
# stub claude for cc-loop: writes a journal entry + a file, 2nd iteration says DONE
cat > "$T/fakeclaude" <<F
#!/usr/bin/env bash
st=$HOME/.cc/state/$REPO/w1; n=\$(ls \$st/runs/*.json 2>/dev/null | wc -l)
echo "iteration work \$n" > "work-\$n.txt"; echo "- \$(date -u +%T) did step \$n" >> "\$st/progress.md"
[ "\$n" -ge 2 ] && echo "STATUS: DONE" >> "\$st/progress.md"
printf '{"is_error":false,"num_turns":2,"total_cost_usd":0.01,"session_id":"x","result":"ok %s"}' "\$n"
F
# stub claude that always hits its turn cap while still doing real work (M6: capped != failed)
cat > "$T/cappedclaude" <<F
#!/usr/bin/env bash
st=$HOME/.cc/state/$REPO/w2; n=\$(ls \$st/runs/*.json 2>/dev/null | wc -l)
if [ "\$n" -lt 4 ]; then echo "capped work \$n" > "capped-\$n.txt"; echo "- capped iteration \$n" >> "\$st/progress.md"; fi
printf '{"is_error":true,"subtype":"error_max_turns","num_turns":80,"total_cost_usd":0.5,"session_id":"x","result":"hit the turn cap"}'
F
# stub claude that hangs, to prove a killed loop takes its child with it (H4)
cat > "$T/sleepclaude" <<F
#!/usr/bin/env bash
echo "- sleeping iteration" >> $HOME/.cc/state/$REPO/w3/progress.md
sleep 30
printf '{"is_error":false,"num_turns":1,"total_cost_usd":0.01,"session_id":"x","result":"ok"}'
F
# stub claude that reports a usage limit on its first call and works on the second (M10: a limit is not a failure)
cat > "$T/limitclaude" <<F
#!/usr/bin/env bash
st=$HOME/.cc/state/$REPO/w4; n=\$(ls \$st/runs/*.json 2>/dev/null | wc -l)   # the loop already created THIS run's file
[ "\$n" -le 1 ] && { printf '{"is_error":true,"result":"You'"'"'ve hit your usage limit. Your limit resets at 11:40.","total_cost_usd":0}'; exit 0; }
echo "- work after the limit lifted" >> "\$st/progress.md"; echo "STATUS: DONE" >> "\$st/progress.md"
printf '{"is_error":false,"num_turns":1,"total_cost_usd":0.01,"session_id":"x","result":"ok"}'
F
chmod +x "$T/fakeclaude" "$T/cappedclaude" "$T/sleepclaude" "$T/limitclaude"
# THE END OF EVERY FILE: the run left the box's ~/.cc as it found it, then the result line (selftest.sh has the reasons).
e2e_end(){
cd ~ || exit 1
BOX_PATHS="notify.log failures state/claude-limit state/handoff state/context state/statusline guard-asks scope state/limit-seen state/limit-interrupted state/limit-nudged state/limit-resumed slack"
box_marked(){   # <root> → the files under it, changed since this run began, that name this run's fixtures
  find "$1" -path "$1/worktrees" -prune -o -path "$1/slack/files" -prune -o -path "$1/slack/member" -prune -o -path "$1/voice" -prune \
       -o -path "$1/selftest-*" -prune -o -path "$1/state/$REPO" -prune \
       -o -type f -newer "$T/born" ! -name "$REPO.*" ! -name 'selftest.lock*' -print 2>/dev/null \
     | xargs -r grep -l -e "$REPO" -e "selftest-$RUN" 2>/dev/null; }
box_split(){   # <root> <marked files…> → $leak: under a BOX_PATHS default of <root>; $seen: anywhere else
  local r=$1 f b hit; shift; leak=""; seen=""
  for f in "$@"; do hit=""; for b in $BOX_PATHS; do case $f in "$r/$b"|"$r/$b"/*) hit=1;; esac; done
    if [ -n "$hit" ]; then leak="$leak $f"; else seen="$seen $f"; fi; done; }
C=$T/boxctl; mkdir -p "$C/state/context" "$C/selftest-0" "$C/boards"
echo "$REPO" > "$C/state/context/handoffs.jsonl"; echo "$REPO" > "$C/state/reconcile.log"
echo "$REPO" > "$C/old"; touch -d "@$(($(stat -c %Y "$T/born") - 3600))" "$C/old"; echo "$REPO" > "$C/selftest-0/log"; echo "$REPO" > "$C/boards/$REPO.json"; echo other > "$C/state/clean.log"
box_split "$C" $(box_marked "$C")
[ "$leak" = " $C/state/context/handoffs.jsonl" ] && [ "$seen" = " $C/state/reconcile.log" ] \
  && ok "control: a marker in state/context reads as a leak, one in reconcile.log as a watcher; an old file, a sibling run's, a board file and a clean file are not found" \
  || bad "the leak/watcher walk is wrong: leak=[$leak] seen=[$seen]"
box_split ~/.cc $(box_marked ~/.cc)   # brief: "a run leaves ~/.cc byte-identical (checked)" — empty $leak is that, for the paths the block redirects
[ -z "$leak" ] && ok "the run wrote nothing of its own into a box file: no $REPO in the box's copy of a path the export block redirects" \
  || bad "a box file carries this run's fixtures (a CC_* state path still points at ~/.cc — add it to the export block, and its default to BOX_PATHS):$leak"
[ -z "$seen" ] || echo "  · the box's own watchers wrote about this run's fixtures (not a leak — a live tick reading the fixture board or transcripts):$seen"
box_flags > "$T/flags.after"
flagdiff=$(diff "$T/flags.before" "$T/flags.after" | grep '^[<>]'); cfgdiff=$(grep '^[<>] config ' <<<"$flagdiff")
if [ -n "$cfgdiff" ] && ! grep -q -e "$REPO" -e "selftest-$RUN" ~/.cc/config 2>/dev/null; then
  echo "  · the box's config changed during the run and names none of its fixtures — a live cc-config set, not this run's: $(tr '\n' ' ' <<<"$cfgdiff")"
  flagdiff=$(grep -v '^[<>] config ' <<<"$flagdiff")
fi
cfgdiff=$(grep '^[<>] config ' <<<"$flagdiff"); flagdiff=$(grep -v '^[<>] config ' <<<"$flagdiff")
secdiff=$(grep '^[<>] github-deny' <<<"$flagdiff"); flagdiff=$(grep -v '^[<>] github-deny' <<<"$flagdiff")
[ -z "$secdiff" ] && ok "…and github-deny and its gitconfig are as the run found them" \
  || bad "a security control changed during the run (github-deny): $(tr '\n' ' ' <<<"$secdiff")"
[ -z "$cfgdiff" ] && ok "…and the box's config is as the run found it, or moved by a live set that names no fixture" \
  || bad "the box's config changed during the run and names this run's fixtures: $(tr '\n' ' ' <<<"$cfgdiff")"
[ -z "$flagdiff" ] || echo "  · a box flag changed while the run went (a person's, or a case's — reported, not red): $(tr '\n' ' ' <<<"$flagdiff")"
echo "== result: $pass passed, $fail failed =="; [ $fail = 0 ] || exit 1; exit 0; }
# recurring-defect-ok: pause-hold-missing — setup for tests of cc on a fixture repo; the pause check is the tool's, not the test's
# recurring-defect-ok: held-files-unchecked — setup for tests of cc on a fixture repo; held_files is checked in the tool it drives
