# shellcheck shell=bash disable=SC2154,SC2034
# cc-limit's selfcheck cases, moved out of bin/cc-limit. That tool's selfcheck() sources this file, whose
# definition replaces it, and then calls it: the cases run in the tool's own shell, with its functions and
# globals, as they did when the body sat there. SC2154/SC2034 are off because those globals live in bin/cc-limit.

selfcheck(){   # stubs only: its own HOME, a stub tmux and cc-msg, and a clock it is handed. No tmux server, no timer,
               # no session on this box is read or written.
  local d n=0 bad=0 t0=1000000000 t1 t2 t3 t4 rc h out deep work OBS=runA cutoff firstseen
  d=$(mktemp -d) || return 1
  t(){ n=$((n+1)); [ "$2" = "$3" ] && return 0; bad=$((bad+1)); printf 'FAIL %s: got %s, want %s\n' "$1" "$2" "$3"; }
  mkdir -p "$d/bin" "$d/.cc/state" "$d/panes"
  cat > "$d/bin/tmux" <<'EOF'
#!/usr/bin/env bash
# selfcheck stub: capture-pane prints $CC_FAKE_PANES/<pane-id>, or nothing when that pane is gone; display-message
# resolves a window id to a pane id out of $CC_FAKE_PANES/<id>.id, the way tmux does; list-panes reads the fake
# session out of $CC_FAKE_PANELIST ("<pane-id> <pane-pid> <window>" lines, the format scan asks for); send-keys is
# logged AND acted on — Escape ends the turn, so the working footer leaves that pane exactly as it does on the box.
set -u; cmd="${1:-}"; shift || true; targ=""; args="$*"
while [ $# -gt 0 ]; do case "$1" in -t) targ="${2:-}"; shift 2;; *) shift;; esac; done
case "$cmd" in
  display-message) cat "$CC_FAKE_PANES/$targ.id" 2>/dev/null;;
  capture-pane) cat "$CC_FAKE_PANES/$targ" 2>/dev/null;;
  list-panes) cat "${CC_FAKE_PANELIST:-/dev/null}" 2>/dev/null;;
  send-keys) printf 'keys %s :: %s\n' "$targ" "$args" >> "$CC_FAKE_CALLS"
             case "$args" in *Escape*) grep -v 'esc to interrupt' "$CC_FAKE_PANES/$targ" > "$CC_FAKE_PANES/$targ.t" 2>/dev/null
                                       mv "$CC_FAKE_PANES/$targ.t" "$CC_FAKE_PANES/$targ" 2>/dev/null;; esac;;
esac
exit 0
EOF
  cat > "$d/bin/cc-msg" <<'EOF'
#!/usr/bin/env bash
# selfcheck stub: the real cc-msg SPOOLS instead of typing when the pane is mid-turn, and that is the whole of the
# 2026-09-05 failure — so does this one, for any window with a $CC_FAKE_PANES/<window>.win pane mapping on file.
set -u; p=""; [ -n "${1:-}" ] && p=$(cat "$CC_FAKE_PANES/$1.win" 2>/dev/null)
if [ -n "$p" ] && grep -qF 'esc to interrupt' "$CC_FAKE_PANES/$p" 2>/dev/null
then printf 'spool %s :: %s\n' "${1:-}" "${2:-}" >> "$CC_FAKE_CALLS"
else printf 'msg %s :: %s\n' "${1:-}" "${2:-}" >> "$CC_FAKE_CALLS"; fi
EOF
  cat > "$d/bin/arm" <<'EOF'
#!/usr/bin/env bash
set -u; printf 'arm %s %s\n' "${1:-}" "${2:-}" >> "$CC_FAKE_CALLS"
EOF
  cat > "$d/bin/cc-model" <<'EOF'
#!/usr/bin/env bash
set -u; printf 'model %s\n' "$*" >> "$CC_FAKE_CALLS"
[ "${1:-}" = status ] && [ -n "${CC_FAKE_MODEL_SAY:-}" ] && printf '%s\n' "$CC_FAKE_MODEL_SAY"
[ "${1:-}" = status ] && [ -n "${CC_FAKE_MODEL_HANG:-}" ] && { sleep 30 & sleep 30; }
exit 0
EOF
  cat > "$d/bin/cc-notify" <<'EOF'
#!/usr/bin/env bash
set -u; printf 'notify %s\n' "$*" >> "$CC_FAKE_CALLS"
EOF
  chmod +x "$d/bin/tmux" "$d/bin/cc-msg" "$d/bin/arm" "$d/bin/cc-model" "$d/bin/cc-notify"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/@1"
  : > "$d/calls"
  # EVERY CC_LIMIT_* path is pinned under $d, not just inherited from HOME: a caller may hold its own in the
  # environment — selftest.sh exports CC_LIMIT_STAMP so that a test limit never makes a real loop wait — and a
  # selfcheck that read the caller's stamp would be testing the caller's state instead of its own fixtures.
  me(){ local at="$1"; shift; HOME="$d" PATH="$d/bin:$PATH" CC_LIMIT_BIN="$d/bin" CC_LIMIT_ARM="$d/bin/arm" \
    CC_LIMIT_STAMP="$d/.cc/state/claude-limit" CC_LIMIT_RECORD="$d/.cc/state/limit-interrupted" \
    CC_LIMIT_NUDGED="$d/.cc/state/limit-nudged" CC_LIMIT_SEEN="$d/.cc/state/limit-seen" \
    CC_LIMIT_RESUMED="$d/.cc/state/limit-resumed" \
    CC_FAKE_PANES="$d/panes" CC_FAKE_CALLS="$d/calls" CC_FAKE_PANELIST="$d/panes.list" \
    CC_LIMIT_OBSERVER="$OBS" CC_LIMIT_MIN_WAIT='' CC_LIMIT_MAX_WAIT='' CC_LIMIT_SETTLE=0 \
    CC_LIMIT_NOW="$at" bash "$SELF" "$@"; }
  led(){   # one row of cc-spend's ledger — $1 epoch, $2 session, $3 model, $4 track (default `t`): "<ts> <session>
           # <cwd> <repo> <track> <kind> <model> <in> <out> <cache_read> <cache_write> <est_usd>", ts in the UTC
           # ISO seconds it prints
    mkdir -p "$d/.cc/state/spend"
    printf '%s\ts%s\t/x\tmyrepo\t%s\theadless\t%s\t1\t1\t0\t0\t0.01\n' \
      "$(date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ)" "$2" "${4:-t}" "$3" >> "$d/.cc/state/spend/$(date -u -d "@$1" +%F).tsv"; }
  calls(){ grep -c "$1" "$d/calls" 2>/dev/null | tr -d '\n'; }

  me "$t0" record @1 alpha >/dev/null 2>&1
  t 'a limit line ALONE is not recorded (this box says "usage limit" in its own docs)' \
    "$([ -e "$d/.cc/state/limit-interrupted" ] && echo yes || echo no)" no
  printf '%s\t%s\t%s\t%s\n' "$((t0 + 1800))" iso "$t0" fable > "$d/.cc/state/claude-limit"
  out=$(me "$t0" record --dry @1 alpha 2>&1)
  t '--dry says what it would record and writes nothing' \
    "$(grep -c would <<<"$out")$([ -e "$d/.cc/state/limit-interrupted" ] && echo yes || echo no)" 1no
  me "$t0" record @1 alpha >/dev/null 2>&1
  t 'an interrupted session is recorded as <pane, window, reset, episode start, tags>' \
    "$(cat "$d/.cc/state/limit-interrupted" 2>/dev/null)" "$(printf '@1\talpha\t%s\t%s\tindep' $((t0 + 1800)) "$t0")"
  t '…and the start is the STAMP\'"'"'s first-seen, not the reset and not the moment it was recorded: that is when
     the 429 killed this session\'"'"'s subagents' \
    "$(cut -f4 "$d/.cc/state/limit-interrupted")" "$t0"
  t 'recording arms ONE one-shot, a few seconds past the reset, in a unit named for that reset' \
    "$(grep -c "^arm 181[0-9] cc-limit-resume-$((t0 + 1800))\$" "$d/calls")" 1
  me "$t0" record @1 alpha >/dev/null 2>&1
  t 'the same pane twice is one record, not two' "$(wc -l < "$d/.cc/state/limit-interrupted")" 1

  me $((t0 + 60)) resume >/dev/null 2>&1
  t 'NOTHING is sent before the reset, and the record survives' \
    "$(calls '^msg ')$(wc -l < "$d/.cc/state/limit-interrupted")" 01
  me $((t0 + 1900)) resume >/dev/null 2>&1
  t 'at the reset the session is nudged, once, through cc-msg' "$(calls '^msg alpha ')" 1
  t 'the nudge names the time, box-local (no Z), and points at the journal and the board' \
    "$(grep -cE 'usage limit lifted at [0-9]{2}:[0-9]{2} — continue the turn you were on; your journal and board say where you were' "$d/calls")" 1
  t 'and the record is cleared by the nudge' "$([ -e "$d/.cc/state/limit-interrupted" ] && echo yes || echo no)" no
  t 'the resume is nudged into the session (kept) but nothing goes to the owner (cut) — $RESUMED is the record' \
    "$(calls '^notify ')" 0
  me $((t0 + 1901)) resume >/dev/null 2>&1
  t 'a second resume nudges nobody: one message per interruption, ever' "$(calls '^msg alpha ')" 1
  # The pane still shows the line it was stopped by — the nudge does not wipe its screen. Recording that stale line
  # again is the OTHER way one interruption becomes two nudges, and the live stamp below is there so the quiet
  # window is the only thing refusing it.
  printf '%s\t%s\t%s\t%s\n' "$((t0 + 3700))" iso "$t0" fable > "$d/.cc/state/claude-limit"
  me $((t0 + 1902)) record @1 alpha >/dev/null 2>&1
  t 'the stale limit line on a pane just nudged is not a second record' \
    "$([ -e "$d/.cc/state/limit-interrupted" ] && echo yes || echo no)" no

  # cc-model's own VERDICT stands in for the stamp once the stamp has expired: a switch event in model.log.
  # The banked hash in model-seen does NOT — it is written for every adjudicated probe, "not a live limit" included.
  t1=$((t0 + 7200))   # the rest of the cases are a later episode: past the quiet window the nudge above opened
  h=$(printf '%s' "alpha$(grep -iE "$PANE_RE" "$d/panes/@1" | tail -1)" | md5sum | cut -c1-16)
  printf '%s\n' "$h" > "$d/.cc/state/model-seen"; rm -f "$d/.cc/state/claude-limit" "$d/.cc/state/limit-interrupted"
  me "$t1" record @1 alpha >/dev/null 2>&1
  t 'the banked probe hash alone corroborates nothing: adjudicated is not limited' \
    "$([ -e "$d/.cc/state/limit-interrupted" ] && echo yes || echo no)" no
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((t1 - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  me "$t1" record @1 alpha >/dev/null 2>&1
  t 'a switch cc-model judged corroborates it with no live stamp, and the pane names the reset' \
    "$(cut -f3 "$d/.cc/state/limit-interrupted" 2>/dev/null)" $((t1 + 1800))
  printf '> \n' > "$d/panes/@1"   # the session came back by itself
  me $((t1 + 1900)) resume >/dev/null 2>&1
  t 'a session that moved on is skipped, not nudged, and forgotten' \
    "$(calls '^msg alpha ')$([ -e "$d/.cc/state/limit-interrupted" ] && echo yes || echo no)" 1no
  me "$t1" record @9 gone >/dev/null 2>&1
  t 'a pane that shows no limit at all is not a record' \
    "$([ -e "$d/.cc/state/limit-interrupted" ] && echo yes || echo no)" no

  # cc-reconcile's wake holds WINDOW ids and `scan` holds pane ids: one session must not become two records, which is two nudges.
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/%7"
  printf '%s\n' '%7' > "$d/panes/@5.id"
  printf '%s\t%s\t%s\t%s\n' "$((t1 + 1800))" iso "$t1" fable > "$d/.cc/state/claude-limit"
  me "$t1" record @5 alpha >/dev/null 2>&1; me "$t1" record %7 alpha >/dev/null 2>&1
  t 'a window id and a pane id for the same session are ONE record' \
    "$(wc -l < "$d/.cc/state/limit-interrupted")$(cut -f1 "$d/.cc/state/limit-interrupted")" '1%7'


  # FINDING 1 (review of #171): two sessions, two resets. The one-shot that fires for the first has to leave a timer
  # behind for the second — an arming that stopped the unit it was running in would SIGTERM this shell before it got
  # there, and the second session would wait for a pulse that may never come. Each arming names its own unit.
  t2=$((t1 + 7200)); rm -f "$d/.cc/state/limit-interrupted" "$d/.cc/state/claude-limit" "$d/.cc/state/limit-nudged"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/@1"
  printf 'Claude usage limit reached. Your limit will reset in 60 minutes\n> \n' > "$d/panes/%7"
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((t2 - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  me "$t2" record @1 alpha >/dev/null 2>&1; me "$t2" record %7 beta >/dev/null 2>&1
  t 'two interrupted sessions are two records, and the arming is for the EARLIER reset' \
    "$(wc -l < "$d/.cc/state/limit-interrupted")$(tail -1 "$d/calls" | cut -d' ' -f3)" "2cc-limit-resume-$((t2 + 1800))"
  : > "$d/calls"
  me $((t2 + 1815)) resume >/dev/null 2>&1
  t 'the first reset nudges only the first, and the second is still on file' \
    "$(calls '^msg alpha ')$(calls '^msg beta ')$(wc -l < "$d/.cc/state/limit-interrupted")" 101
  t 'and that same run arms a NEW unit for the second — never the one it is running in' \
    "$(grep -c "^arm [0-9]* cc-limit-resume-$((t2 + 3600))\$" "$d/calls")" 1

  # FINDING 2: `check` writes a 5-minute GUESS into the stamp (src=backoff:N) when the message named no time. A nudge
  # at a guess reaches a session that is still limited, and spends the one nudge that was owed at the real reset.
  t3=$((t2 + 7200)); rm -f "$d/.cc/state/limit-interrupted" "$d/.cc/state/limit-nudged"; : > "$d/calls"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/@1"
  printf '%s\t%s\t%s\t%s\n' "$((t3 + 300))" backoff:5 "$t3" fable > "$d/.cc/state/claude-limit"
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((t3 - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  me "$t3" record @1 alpha >/dev/null 2>&1
  t 'a backoff GUESS is not a reset: the time the PANE names is recorded, not the guess' \
    "$(cut -f3 "$d/.cc/state/limit-interrupted" 2>/dev/null)" $((t3 + 1800))

  # THE EXIT CODE IS A CONTRACT (finding 4): cc-reconcile's wake reads it to decide whether that pane may be typed at, so
  # "limited, and I am not recording it" must not look like "nothing to see here".
  rm -f "$d/.cc/state/limit-interrupted" "$d/.cc/state/limit-nudged"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/@1"
  printf 'Claude usage limit reached.\n> \n' > "$d/panes/@3"   # limited, and names no reset at all
  me "$t3" record @3 gamma >/dev/null 2>&1; rc=$?
  t 'a guess and a pane with no time = nothing recorded, and exit 2: the pane is still limited' \
    "$rc$([ -e "$d/.cc/state/limit-interrupted" ] && echo yes || echo no)" 2no
  me "$t3" record @9 gone >/dev/null 2>&1; rc=$?
  t 'a pane with no limit line at all is exit 1 — that one IS safe to type at' "$rc" 1
  rm -f "$d/.cc/state/claude-limit" "$d/.cc/state/model.log" "$d/.cc/state/limit-seen"   # a line first seen NOW
  me "$t3" record @1 alpha >/dev/null 2>&1; rc=$?
  t 'a limit line nothing corroborates yet is exit 2, not 1: it is still a limited pane' "$rc" 2
  me "$((t3 + 7200))" record @1 alpha >/dev/null 2>&1; rc=$?
  t 'the same line two hours later, still uncorroborated, is exit 1: scrollback, not a limit — that pane may be ticked (review-171b)' "$rc" 1
  # …and the other half of that rule, which a row kept per PANE would get wrong: two days on, the limit really
  # stops this session, so the pane shows a NEW line. That is a new sighting with its own hour — reading the old
  # one as "old news" is how the pulse comes to type at a session the limit has just stopped (review of #171).
  printf 'Claude usage limit reached. Your limit will reset at 2026-09-04 19:00Z\n> \n' > "$d/panes/@1"
  me "$((t3 + 172800))" record @1 alpha >/dev/null 2>&1; rc=$?
  t 'a NEW limit line on a pane that showed the wording days ago is exit 2, not 1 — the old sighting is not this one' \
    "$rc" 2
  t 'and the day-old row is dropped on the way through, so the file does not grow for ever' \
    "$(wc -l < "$d/.cc/state/limit-seen")" 1
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/@1"
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((t3 - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  me "$t3" record @1 alpha >/dev/null 2>&1; rc=$?
  t 'and a pane that becomes a record is exit 0' "$rc$(cut -f3 "$d/.cc/state/limit-interrupted")" "0$((t3 + 1800))"
  me "$t3" record @1 alpha >/dev/null 2>&1; rc=$?
  t 'a pane already on file is recorded again, not refused — the record is one row, and it stays exit 0' \
    "$rc$(wc -l < "$d/.cc/state/limit-interrupted")" 01


  # FINDING 2 (review of #171, third round): a `cc-handoff --overlap` successor runs `bash -c '… cc __runnext …'`,
  # so its claude is a GRANDCHILD of the pane — and the direct-child test called that session dead and never
  # recorded the very session this file exists to rescue. Real processes, because the walk reads /proc: a COPY OF
  # BASH named claude, since `ps` and the `-p` test both read the name the kernel holds.
  t4=$((t3 + 7200)); rm -f "$d/.cc/state/limit-interrupted" "$d/.cc/state/limit-nudged" "$d/.cc/state/limit-seen"
  cp "$(readlink -f /bin/bash)" "$d/bin/claude"
  bash -c "bash -c \"'$d/bin/claude' -c 'sleep 20; true'; true\"; true" </dev/null >/dev/null 2>&1 &
  deep=$!
  bash -c "'$d/bin/claude' -p -c 'sleep 20; true'; true" </dev/null >/dev/null 2>&1 &
  work=$!
  sleep 0.6                                    # both panes need their children to exist before anything walks them
  printf '@1 %s alpha\n@2 %s beta\n' "$deep" "$work" > "$d/panes.list"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/@1"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/@2"
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((t4 - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  me "$t4" record >/dev/null 2>&1
  t 'a session whose claude is a GRANDCHILD is scanned and recorded, not called dead' \
    "$(cut -f1,2 "$d/.cc/state/limit-interrupted" 2>/dev/null)" "$(printf '@1\talpha')"
  t 'and a pane whose only claude is headless is left out — it parks and reruns itself' \
    "$(grep -c '^@2' "$d/.cc/state/limit-interrupted" 2>/dev/null)" 0

  # FINDING 1: `check` prints LIMIT <epoch> AFTER that scan, and parse_reset writes $u as a global. A record made
  # for some other pane must not rewrite the reset this run is about to print — "LIMIT 0" is what the owner reads
  # as "resumes at 00:00Z". The pane says 30 minutes, the message below names no time at all, so the stamp's own
  # 5-minute backoff is the only right answer to print.
  rm -f "$d/.cc/state/claude-limit" "$d/.cc/state/limit-interrupted" "$d/.cc/state/limit-seen"
  printf '{"is_error":true,"result":"API Error 429 too many requests"}\n' > "$d/run.json"
  out=$(me "$t4" check "$d/run.json" 2>/dev/null)
  t 'the scan at the end of `check` cannot rewrite the reset check prints' "$out" "LIMIT $((t4 + 300))"
  t 'and that same run did record the pane, at the time the PANE named, not the backoff guess' \
    "$(cut -f3 "$d/.cc/state/limit-interrupted" 2>/dev/null)" $((t4 + 1800))
  kill "$deep" "$work" >/dev/null 2>&1; pkill -f "$d/bin/claude" >/dev/null 2>&1   # $d is a fresh mktemp: matches nothing else

  # FINDING 1 (review-171c): a pane's line is STALE TEXT. Re-reading "in 30 minutes" on every round moved the record
  # 30 minutes past each read, so the nudge owed at the reset was never sent. A pane re-read never moves a record.
  t5=$((t4 + 7200)); rm -f "$d/.cc/state/claude-limit" "$d/.cc/state/limit-interrupted" "$d/.cc/state/limit-nudged" "$d/.cc/state/limit-seen"; : > "$d/calls"
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((t5 - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  me "$t5" record @1 alpha >/dev/null 2>&1                     # recorded at T for T+1800
  me "$((t5 + 7200))" record @1 alpha >/dev/null 2>&1; rc=$?   # the same unchanged pane, two hours later
  t 'a record re-read from the same stale pane two hours on still says its ORIGINAL reset' \
    "$rc$(cut -f3 "$d/.cc/state/limit-interrupted" 2>/dev/null)" "0$((t5 + 1800))"
  me "$((t5 + 7200))" resume >/dev/null 2>&1
  t 'and the resume in that same round nudges it — the reset is long past' "$(calls '^msg alpha ')" 1
  # The absolute form was worse: "reset at 3pm" re-read at 16:00 rolled over to TOMORROW's 3pm in one step. In
  # `record` a clock time already past is "no reset time yet". Real clock: parse_reset's clock times are today's,
  # and today's 00:00 is the one clock time that is always already past.
  nowr=$(date -u +%s); mid=$(date -u -d "00:00" +%s)
  rm -f "$d/.cc/state/limit-interrupted" "$d/.cc/state/limit-nudged"; : > "$d/calls"
  printf 'Claude usage limit reached. Your limit will reset at 00:00\n> \n' > "$d/panes/@1"
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((nowr - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  me "$((mid - 7200))" record @1 alpha >/dev/null 2>&1         # last evening: 00:00 was still ahead
  t 'a clock time still ahead is recorded for today' "$(cut -f3 "$d/.cc/state/limit-interrupted" 2>/dev/null)" "$mid"
  me "$nowr" record @1 alpha >/dev/null 2>&1; rc=$?
  t 'the same line once that time has passed is NOT rolled over to tomorrow: exit 1 (safe to tick), record untouched' \
    "$rc$(cut -f3 "$d/.cc/state/limit-interrupted" 2>/dev/null)" "1$mid"
  me "$nowr" resume >/dev/null 2>&1
  t 'and resume nudges it now, not tomorrow' "$(calls '^msg alpha ')" 1

  # ── WHAT ELSE THE LIMIT KILLED: publishing the episode so a dead subagent's row comes back ──────────────────
  # Own fixture and own clock: a session nudged above must not be what makes any of these pass, and the file
  # under test is removed before each case so its absence means something.
  rez(){ cat "$d/.cc/state/limit-resumed" 2>/dev/null; }
  ta=$((t5 + 43200)); rm -f "$d/.cc/state/claude-limit" "$d/.cc/state/limit-interrupted" \
    "$d/.cc/state/limit-nudged" "$d/.cc/state/limit-seen" "$d/.cc/state/limit-resumed"; : > "$d/calls"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/@1"
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((ta - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  me "$ta" record @1 alpha >/dev/null 2>&1
  me $((ta + 60)) resume >/dev/null 2>&1
  t 'no episode is published before the reset: the limit is still on and its subagents are not dead yet' \
    "$([ -e "$d/.cc/state/limit-resumed" ] && echo yes || echo no)" no
  me $((ta + 1900)) resume >/dev/null 2>&1
  t 'at the reset the episode is published as <started, reset, resumed>, so a mark older than its START is cold' \
    "$(rez)" "$(printf '%s\t%s\t%s' "$ta" $((ta + 1800)) $((ta + 1900)))"

  # A reset the stamp has moved OUT is not an episode that ended — publishing it would call every live subagent
  # dead in the middle of a limit that is still standing.
  tb=$((ta + 7200)); rm -f "$d/.cc/state/claude-limit" "$d/.cc/state/limit-interrupted" \
    "$d/.cc/state/limit-nudged" "$d/.cc/state/limit-seen" "$d/.cc/state/limit-resumed"; : > "$d/calls"
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((tb - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  me "$tb" record @1 alpha >/dev/null 2>&1                                          # recorded for tb+1800
  printf '%s\t%s\t%s\t%s\n' "$((tb + 3600))" iso "$tb" fable > "$d/.cc/state/claude-limit"   # …the API moved it to tb+3600
  me $((tb + 1900)) resume >/dev/null 2>&1
  t 'a record whose reset the stamp moved out publishes nothing — that limit has not lifted' \
    "$([ -e "$d/.cc/state/limit-resumed" ] && echo yes || echo no)" no
  rm -f "$d/.cc/state/claude-limit"
  me $((tb + 3700)) resume >/dev/null 2>&1
  t '…and once the moved reset really passes, THAT is the episode published, not the one first recorded' \
    "$(rez)" "$(printf '%s\t%s\t%s' "$tb" $((tb + 3600)) $((tb + 3700)))"

  # A pane that came back by itself is not nudged — but the subagents it had out still died on the 429.
  tc=$((tb + 7200)); rm -f "$d/.cc/state/limit-interrupted" "$d/.cc/state/limit-nudged" \
    "$d/.cc/state/limit-seen" "$d/.cc/state/limit-resumed"; : > "$d/calls"
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((tc - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  me "$tc" record @1 alpha >/dev/null 2>&1
  printf '> \n' > "$d/panes/@1"   # it moved on: no limit line left on the screen
  me $((tc + 1900)) resume >/dev/null 2>&1
  t 'a pane that moved on by itself gets no nudge, and the episode is published all the same' \
    "$(calls '^msg alpha ')$(rez)" "0$(printf '%s\t%s\t%s' "$tc" $((tc + 1800)) $((tc + 1900)))"

  # Two sessions, two resets, one episode: the LATEST reset is the bar, or a mark made between the two resets
  # would be read as older than the limit and a live subagent called dead.
  td=$((tc + 7200)); rm -f "$d/.cc/state/limit-interrupted" "$d/.cc/state/limit-nudged" \
    "$d/.cc/state/limit-seen" "$d/.cc/state/limit-resumed"; : > "$d/calls"
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((td - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/@1"
  printf 'Claude usage limit reached. Your limit will reset in 90 minutes\n> \n' > "$d/panes/@2"
  me "$td" record @2 beta >/dev/null 2>&1                 # the LATER reset first, so the last row read is the
  me $((td + 120)) record @1 alpha >/dev/null 2>&1        # EARLIER one — and two minutes later, so two starts
  me $((td + 5500)) resume >/dev/null 2>&1
  t 'two records, one episode: the LATEST reset is published, not the last row read' \
    "$(cut -f2 <<<"$(rez)")" $((td + 5400))
  t '…and the EARLIEST start, because that is the bar every mark is judged against and the earliest one calls
     the fewest live subagents dead' \
    "$(cut -f1 <<<"$(rez)")" "$td"

  # A due record carrying NO start (written before the review of #264 added the field) makes the episode
  # unpublishable rather than guessed: a start that is too late reads live marks as dead, which is the whole
  # failure this file is here to avoid.
  te=$((td + 21600)); rm -f "$d/.cc/state/limit-nudged" "$d/.cc/state/limit-resumed"; : > "$d/calls"
  printf '@1\talpha\t%s\n' $((te + 1800)) > "$d/.cc/state/limit-interrupted"   # three fields, the old shape
  me $((te + 1900)) resume >/dev/null 2>&1
  t 'a due record with no start publishes no episode at all — a guessed start would call live rows dead,
     and the nudge that record was written for still goes' \
    "$([ -e "$d/.cc/state/limit-resumed" ] && echo yes || echo no)$(calls '^msg alpha ')" no1

  # ── A RECORD IS NOT ALWAYS A SECOND WITNESS (review of #264) ─────────────────────────────────────────────────
  # cc-model counts a record as the second run that hit a limit, and record() corroborates a pane's line with the
  # very stamp cc-model is about to believe — so a one-observer stamp plus this morning's leftover wording would be
  # two witnesses that are really one. Own fixture and own clock: the SAME pane is recorded twice, once with a line
  # older than the episode and once with a line inside it, and both answers are asserted.
  tg=$((te + 21600)); : > "$d/calls"
  rm -f "$d/.cc/state/limit-interrupted" "$d/.cc/state/limit-nudged" "$d/.cc/state/limit-seen" \
    "$d/.cc/state/claude-limit" "$d/.cc/state/limit-resumed"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/@1"
  printf '%s\t%s\t%s\t%s\t%s\n' $((tg - 3600)) iso $((tg - 7200)) fable aaaaaaaa > "$d/.cc/state/claude-limit"
  me $((tg - 7200)) record @1 alpha >/dev/null 2>&1   # the morning's episode: that line is first seen HERE
  rm -f "$d/.cc/state/limit-interrupted" "$d/.cc/state/limit-nudged"
  printf '%s\t%s\t%s\t%s\t%s\n' $((tg + 1800)) iso "$tg" fable bbbbbbbb > "$d/.cc/state/claude-limit"
  me $((tg + 60)) record @1 alpha >/dev/null 2>&1     # …and hours later a fresh stamp, one observer, same screen
  t 'a stale limit line under a fresh stamp is still recorded — that session IS stopped — but not as an
     independent sighting: it is the witness the stamp already is, so cc-model still wants two observers' \
    "$(awk -F'\t' '$2=="alpha"{print $3 "/" $5}' "$d/.cc/state/limit-interrupted")" "$((tg + 1800))/"
  printf 'Claude usage limit reached. Your limit will reset in 90 minutes\n> \n' > "$d/panes/%7"
  me $((tg + 60)) record @5 beta >/dev/null 2>&1      # a line this episode put there, first seen inside it
  t '…while a line first seen at or after the stamp'"'"'s own first-seen IS a second witness, and is tagged so' \
    "$(awk -F'\t' '$2=="beta"{print $5}' "$d/.cc/state/limit-interrupted")" indep

  # ── ONE RUN'S LIMIT IS NOT THE BOX'S (2026-09-04) ────────────────────────────────────────────────────────────
  # 09:13:29Z one headless worker was told "usage limit until 06:00Z" and exited 8; every other session read that
  # stamp and did nothing for six hours while opus went on answering. Own fixture, own state: nothing above leaves
  # a stamp, a ledger or an observer these cases could lean on.
  t6=$((t5 + 86400)); rm -rf "$d/.cc/state/spend"
  rm -f "$d/.cc/state/claude-limit" "$d/.cc/state/claude-limit.disbelieved" "$d/.cc/state/limit-interrupted" \
    "$d/.cc/state/limit-nudged" "$d/.cc/state/limit-seen" "$d/.cc/state/model.log"
  : > "$d/panes.list"; : > "$d/calls"
  printf '{"is_error":true,"result":"claude-fable-5: Claude usage limit reached. Your limit resets at %s"}\n' \
    "$(date -u -d "@$((t6 + 54000))" +%Y-%m-%dT%H:%M:%SZ)" > "$d/run.json"   # 15 h out, the way that morning read
  OBS=worker-a; me "$t6" check "$d/run.json" >/dev/null 2>&1
  t 'the run that hit the limit is written into the stamp as its one observer' \
    "$(cut -f5 "$d/.cc/state/claude-limit")" "$(printf worker-a | md5sum | cut -c1-8)"
  out=$(me "$t6" status 2>/dev/null); rc=$?
  t 'and THAT run is stopped by it, exactly as before' "$rc$(grep -c 'this run only' <<<"$out")" 01
  t 'and it still refuses to wait out a 15 h limit (CC_LIMIT_MAX_WAIT) — it parks and reruns itself' \
    "$(me "$t6" wait >/dev/null 2>&1; echo $?)" 1
  OBS=worker-b; out=$(me "$t6" status 2>&1); rc=$?
  t 'every OTHER run reads clear: one run hitting a limit stops that run and nothing else' \
    "$rc$(grep -c '^clear$' <<<"$out")" 11
  t '…and is told on stderr what it is not being stopped by' \
    "$(grep -c 'no second run has hit it' <<<"$out")" 1
  t '…in words cc-land cannot read back as a live limit out of its merged stdout+stderr' \
    "$(grep -cE 'usage limit until [0-9]{2}:[0-9]{2}Z' <<<"$out")" 0
  t 'a run the stamp does not bind has nothing to wait for' "$(me "$t6" wait >/dev/null 2>&1; echo $?)" 0
  t 'and one run does not move the box off its model either' "$(calls '^model (limited|unavailable)')" 0   # `status` asks cc-model too, and that is no move
  me $((t6 + 60)) check "$d/run.json" >/dev/null 2>&1   # a SECOND worker hits the same limit
  t 'two runs on the same limit make it account-wide' \
    "$(cut -f5 "$d/.cc/state/claude-limit" | tr ',' '\n' | grep -c .)" 2
  OBS=worker-c; out=$(me $((t6 + 60)) status 2>/dev/null); rc=$?
  t 'and then every run is parked by it — a real account-wide limit parks the box as it does today' \
    "$rc$(grep -c 'this run only' <<<"$out")" 00
  t 'and only then is cc-model told whose limit it was' "$(calls '^model limited fable')" 1

  # THE ACCOUNT ANSWERING. A limit two runs hit can still be wrong: on 09-04 the ledger had successful opus rows at
  # 14:54, 14:55 and 14:59Z from three different sessions while the box sat parked. Two DIFFERENT sessions, on the
  # limited model, past the grace — believing a limit wrongly costs a day, disbelieving one wrongly costs a reset.
  cutoff=$((t6 + 300))   # GRACE past the moment the stamp was first seen
  led $((cutoff + 60)) 1 claude-fable-5-1
  t 'ONE session answering is not proof — a person can pay a real limit out in usage credits' \
    "$(me $((t6 + 7200)) status >/dev/null 2>&1; echo $?)" 0
  led $((cutoff + 70)) 2 claude-opus-5
  t 'and two sessions on ANOTHER model do not disprove a limit that named fable' \
    "$(me $((t6 + 7200)) status >/dev/null 2>&1; echo $?)" 0
  led "$cutoff" 3 claude-fable-5-1
  t 'a row ON the cutoff second is not past it: the ledger prints seconds and is compared as seconds' \
    "$(me $((t6 + 7200)) status >/dev/null 2>&1; echo $?)" 0
  led $((cutoff + 80)) 3 claude-fable-5-1
  firstseen=$(cut -f3 "$d/.cc/state/claude-limit")
  out=$(me $((t6 + 7200)) status 2>/dev/null); rc=$?
  t 'TWO sessions answering the limited model past the grace drops the stamp — no six-hour dead box' \
    "$rc$out$([ -e "$d/.cc/state/claude-limit" ] && echo yes || echo no)" 1clearno
  t 'nothing goes to the owner — a debugging engineer reads the record below, not a Slack post' \
    "$(calls '^notify ')" 0
  t 'the disbelieved stamp is marked in its own file — the record the cut post used to duplicate' \
    "$(cat "$d/.cc/state/claude-limit.disbelieved" 2>/dev/null)" "$firstseen"
  me $((t6 + 7260)) status >/dev/null 2>&1
  t 'a second look still sends nothing' "$(calls '^notify ')" 0
  me $((t6 + 7260)) clear
  t 'clear forgets the episode too, so the next one gets its own line' \
    "$([ -e "$d/.cc/state/claude-limit.disbelieved" ] && echo yes || echo no)" no

  # A LIMIT THAT SPANS DAYS. answering() read two ledger files — the day the stamp was first seen and today — so a
  # stamp first seen late on day 1 with a reset a week out, disproved all through day 2, was still believed on day 3
  # (review of #215). Own fixture: a fresh two-observer stamp, and rows on the MIDDLE day only.
  rm -rf "$d/.cc/state/spend"; rm -f "$d/.cc/state/claude-limit" "$d/.cc/state/claude-limit.disbelieved"; : > "$d/calls"
  t7=$(date -u -d "$(date -u -d "@$t6" +%F) 23:00:00" +%s)   # 23:00Z on day 1
  printf '{"is_error":true,"result":"claude-fable-5: Claude usage limit reached. Your limit resets at %s"}\n' \
    "$(date -u -d "@$((t7 + 7 * 86400))" +%Y-%m-%dT%H:%M:%SZ)" > "$d/run3.json"   # a week out: the weekly reset
  OBS=worker-a; me "$t7" check "$d/run3.json" >/dev/null 2>&1
  OBS=worker-b; me $((t7 + 60)) check "$d/run3.json" >/dev/null 2>&1   # a second run: account-wide, the box parks
  led $((t7 + 43200)) 5 claude-fable-5-1; led $((t7 + 43260)) 6 claude-fable-5-1   # day 2, 11:00Z: two sessions answer
  OBS=worker-c; out=$(me $((t7 + 2 * 86400)) status 2>/dev/null); rc=$?   # day 3: no row on day 1, none today
  t 'a stamp spanning three days is disproved by rows on the MIDDLE day, not only its first day and today' \
    "$rc$out" 1clear

  # THE TUTOR'S CHATS ARE NOT THIS ACCOUNT ANSWERING (2026-09-22). The ledger carries the hosted tutor's turns
  # now, and those calls are made on the tutor's own account, so two student chats past the cutoff must leave a
  # real limit believed. Own fixture: a fresh two-observer stamp and a ledger emptied first.
  rm -rf "$d/.cc/state/spend"; rm -f "$d/.cc/state/claude-limit" "$d/.cc/state/claude-limit.disbelieved"; : > "$d/calls"
  t8=$((t7 + 10 * 86400))
  printf '{"is_error":true,"result":"claude-fable-5: Claude usage limit reached. Your limit resets at %s"}\n' \
    "$(date -u -d "@$((t8 + 54000))" +%Y-%m-%dT%H:%M:%SZ)" > "$d/run4.json"
  OBS=worker-a; me "$t8" check "$d/run4.json" >/dev/null 2>&1
  OBS=worker-b; me $((t8 + 60)) check "$d/run4.json" >/dev/null 2>&1   # two runs: account-wide, the box parks
  led $((t8 + 900)) 7 claude-fable-5-1 tutor; led $((t8 + 960)) 8 claude-fable-5-1 tutor
  OBS=worker-c; out=$(me $((t8 + 7200)) status 2>/dev/null); rc=$?
  t 'two TUTOR sessions answering past the grace leave the limit standing — that is the tutor account, not this one' \
    "$rc$([ -e "$d/.cc/state/claude-limit" ] && echo yes || echo no)" 0yes
  led $((t8 + 1020)) 9 claude-fable-5-1; led $((t8 + 1080)) 10 claude-fable-5-1   # …and this box's own two sessions
  out=$(me $((t8 + 7200)) status 2>/dev/null); rc=$?
  t '…while two of this box'"'"'s OWN sessions at the same moment still drop it' \
    "$rc$out$([ -e "$d/.cc/state/claude-limit" ] && echo yes || echo no)" 1clearno

  # THE STAMP THAT STARTED ALL THIS NAMED NO MODEL, so its field 4 is empty. Its own fixture: a fresh stamp and no
  # ledger, so nothing here but the split is under test.
  rm -rf "$d/.cc/state/spend"; rm -f "$d/.cc/state/claude-limit"; OBS=worker-d
  printf '{"is_error":true,"result":"Claude usage limit reached. Your limit resets at %s"}\n' \
    "$(date -u -d "@$((t6 + 54000))" +%Y-%m-%dT%H:%M:%SZ)" > "$d/run2.json"
  me "$t6" check "$d/run2.json" >/dev/null 2>&1
  t 'a limit naming no model leaves field 4 empty and field 5 still readable' \
    "$(cut -f4,5 "$d/.cc/state/claude-limit")" "$(printf '\t%s' "$(printf worker-d | md5sum | cut -c1-8)")"
  t '…and the run that hit it still finds its own key there' \
    "$(me "$t6" status 2>/dev/null | grep -c 'this run only')" 1

  # USAGE CREDITS ARE NOT A LIMIT (2026-09-03). Every call to Fable on a Pro account answered "Fable 5.1 requires
  # usage credits" — one model this account cannot run, for good — and the word "credits" in the limit pattern
  # wrote a box-wide stamp for it. Own fixture: no stamp, no ledger, and the message verbatim.
  rm -rf "$d/.cc/state/spend"; rm -f "$d/.cc/state/claude-limit" "$d/.cc/state/claude-limit.disbelieved"; : > "$d/calls"; OBS=worker-e
  printf '{"is_error":true,"stop_reason":"stop_sequence","terminal_reason":"api_error","result":"Fable 5.1 requires usage credits","modelUsage":{"claude-haiku-4-5-20251001":{"inputTokens":9},"claude-fable-5-1":{"inputTokens":2}}}\n' > "$d/credits.json"
  out=$(me "$t6" check "$d/credits.json" 2>/dev/null); rc=$?
  t 'a model that needs usage credits is not a limit: check says so (exit 1) and prints no LIMIT' "$rc$out" 1
  t 'and writes no stamp, so nothing else on the box is held by it' "$([ -e "$d/.cc/state/claude-limit" ] && echo yes || echo no)" no
  t 'and tells cc-model that model is unavailable, in the words the API used' \
    "$(grep -c '^model unavailable fable Fable 5.1 requires usage credits$' "$d/calls")" 1
  # the 2026-08-28 wording came with a 429 on it and named no model in its text: the run's own main model is the one,
  # never the haiku side-call
  printf '{"is_error":true,"api_error_status":429,"result":"You'"'"'re out of usage credits. Switch to another model, or manage usage credits at claude.ai/settings/usage?from=cc_cli_limit_message, to continue.","modelUsage":{"claude-haiku-4-5-20251001":{"inputTokens":9},"claude-fable-5":{"inputTokens":2}}}\n' > "$d/credits2.json"
  : > "$d/calls"; me "$t6" check "$d/credits2.json" >/dev/null 2>&1; rc=$?
  t 'out of usage credits (2026-08-28) is the same: no stamp, and the model is the run'"'"'s own, not the side-call' \
    "$rc$([ -e "$d/.cc/state/claude-limit" ] && echo yes || echo no)$(grep -c "^model unavailable fable You're out of usage credits$" "$d/calls")" 1no1
  # A MONTHLY SPEND CAP IS THE SAME KIND AS USAGE CREDITS (owner, 2026-09-15): the reset the line names is the
  # weekly limit's and does not lift the cap; the model that draws on credits is out, the others answer. Own
  # fixture: the line verbatim with a reset 22 h out, naming no model — the run's asked model is the one.
  rm -f "$d/.cc/state/claude-limit" "$d/.cc/state/claude-limit.disbelieved"; : > "$d/calls"; OBS=worker-f
  printf '{"is_error":true,"result":"You'"'"'ve hit your monthly spend limit · raise it at claude.ai/settings/usage · your weekly limit resets %s (UTC)"}\n' \
    "$(date -u -d "@$((t6 + 79200))" +%H:%M)" > "$d/cap.json"
  out=$(me "$t6" check "$d/cap.json" '' 'claude-fable-5-1[1m]' 2>/dev/null); rc=$?
  t 'a monthly spend cap is not a limit (exit 1, no LIMIT, no stamp): the weekly reset it quotes is not its lift, and nothing waits on it' \
    "$rc:$out:$([ -e "$d/.cc/state/claude-limit" ] && echo stamp || echo none)" "1::none"
  t '…the line names no model, so the model the run was dispatched on is recorded — cc-loop passes it' \
    "$(grep -c "^model unavailable fable You've hit your monthly spend limit$" "$d/calls")" 1
  t '…and cc-limit does not tell the owner itself: cc-model does, once per episode, with what lifts it' "$(grep -c '^notify' "$d/calls")" 0
  # …while a real limit whose text names no model is still caught, still shared, and names the right family
  printf '{"is_error":true,"api_error_status":429,"result":"Claude usage limit reached. Your limit resets at %s","modelUsage":{"claude-haiku-4-5-20251001":{"inputTokens":9},"claude-opus-5":{"inputTokens":2}}}\n' \
    "$(date -u -d "@$((t6 + 1800))" +%Y-%m-%dT%H:%M:%SZ)" > "$d/opuslim.json"
  : > "$d/calls"; out=$(me "$t6" check "$d/opuslim.json" 2>/dev/null); rc=$?
  t 'a real limit is still a timed stamp' "$rc$out" "0LIMIT $((t6 + 1800))"
  t 'and it names the model that hit it, not the CLI'"'"'s haiku side-call (the 09-03 stamp named the wrong family)' \
    "$(cut -f4 "$d/.cc/state/claude-limit")" opus
  t 'and cc-model is not told anything is unavailable' "$(calls '^model unavailable')" 0
  printf '{"is_error":true,"result":"Claude usage limit reached · continuing on Fable 5 uses usage credits · resets at %s"}\n' \
    "$(date -u -d "@$((t6 + 3600))" +%Y-%m-%dT%H:%M:%SZ)" > "$d/both.json"
  rm -f "$d/.cc/state/claude-limit"; : > "$d/calls"; out=$(me "$t6" check "$d/both.json" 2>/dev/null); rc=$?
  t 'a limit hit with no credits left to continue on is still a limit: the limit wording wins' \
    "$rc$out$(calls '^model unavailable')" "0LIMIT $((t6 + 3600))0"

  # A DAY IS NOT AN HOUR, AND THE ZONE IS THE ONE THE MESSAGE NAMES (2026-09-03). The weekly limit read "resets
  # Sep 7, 10am (America/Los_Angeles)": the clock branch took the 7 out of "Sep 7" for an hour, so the box was
  # parked to 07:00 Los Angeles — three hours early on a limit with days to run. The URL in the same line is the
  # second half of it: the zone used to be the FIRST thing in the text with a slash in it, which was "ai/settings",
  # and the clock was then read as UTC. Fixed clocks throughout, so these hold whatever year the suite runs in.
  rm -rf "$d/.cc/state/spend"; rm -f "$d/.cc/state/claude-limit.disbelieved"; OBS=worker-f
  t8=$(date -u -d '2026-09-04 22:53:00' +%s); t9=$(date -u -d '2026-12-31 20:00:00' +%s)
  rt(){   # $1 the clock, $2 the wording -> "<the epoch check stamped, UTC> <how it read it>". The stamp is dropped
          # first, so a case that ends in backoff always gets the first step of it and never a doubling of the case
          # before, and every case reads only its own message.
    local o; rm -f "$d/.cc/state/claude-limit"
    printf '{"is_error":true,"result":"Claude usage limit reached · %s"}\n' "$2" > "$d/rt.json"
    o=$(me "$1" check "$d/rt.json" 2>/dev/null)
    printf '%s %s' "$(date -u -d "@${o#LIMIT }" +%FT%H:%MZ 2>/dev/null)" "$(cut -f2 "$d/.cc/state/claude-limit" 2>/dev/null)"; }
  back(){ printf '%s backoff:5' "$(date -u -d "@$(($1 + 300))" +%FT%H:%MZ)"; }   # what a message with no readable time gets
  t 'a day and a clock are read in the zone the message names: Sep 7 10am Los Angeles = 17:00Z, not 14:00Z' \
    "$(rt "$t8" 'resets Sep 7, 10am (America/Los_Angeles) · manage usage at claude.ai/settings/usage?from=cc_cli_limit_message')" \
    '2026-09-07T17:00Z date'
  t 'the same day and clock naming no zone is UTC, never whatever the host clock is set to' \
    "$(rt "$t8" 'resets Sep 7, 10am')" '2026-09-07T10:00Z date'
  # BOTH ORDERINGS GET WRITTEN, and either read as a bare clock lands on today: 10am on the 5th, two days early.
  t 'the clock written before the day is still the day'"'"'s clock' \
    "$(rt "$t8" 'resets at 10am on Sep 7 (America/Los_Angeles)')" '2026-09-07T17:00Z date'
  t 'the day written first, the way most of the world writes it, reads the same' \
    "$(rt "$t8" 'resets 7 Sep, 10am (America/Los_Angeles)')" '2026-09-07T17:00Z date'
  t 'a day with no clock on it is the start of that day, and the ordinal and the dot are not part of the date' \
    "$(rt "$t8" 'resets Sept. 7th (America/Los_Angeles)')" '2026-09-07T07:00Z date'
  # THE YEAR THE MESSAGE LEAVES OUT. A day already past is next year's when next year's is days out…
  t 'a day already past is next year'"'"'s when next year'"'"'s is days out' \
    "$(rt "$t9" 'resets Jan 2, 9am (America/Los_Angeles)')" '2027-01-02T17:00Z date'
  t '…but not when next year'"'"'s is months out: that is a stale message, and the backoff is the safe read' \
    "$(rt "$t9" 'resets Mar 4, 9am (America/Los_Angeles)')" "$(back "$t9")"
  # NOTHING FURTHER OUT THAN A FORTNIGHT IS A RESET. check only ever guards against the past, so either of these
  # would have written a stamp months or decades out and parked the box for good.
  t 'a day that lands eleven months out is a misread, not a reset — "resets Dec 31" read on Jan 3' \
    "$(rt "$(date -u -d '2027-01-03 12:00:00' +%s)" 'resets Dec 31, 10am (America/Los_Angeles)')" \
    "$(back "$(date -u -d '2027-01-03 12:00:00' +%s)")"
  t 'and a year the message names itself is bounded the same way' \
    "$(rt "$t8" 'resets Sep 7 2077, 10am (America/Los_Angeles)')" "$(back "$t8")"
  t '…while a year it names inside the fortnight is taken as written' \
    "$(rt "$(date -u -d '2026-12-28 12:00:00' +%s)" 'resets Jan 2 2027, 9am (America/Los_Angeles)')" \
    '2027-01-02T17:00Z date'

  # ── A TURN THAT NEVER ENDED (2026-09-05) ─────────────────────────────────────────────────────────────────────
  # The planning session took the 429 inside a turn that never finished, so the nudge owed at the reset would have
  # spooled behind that turn exactly as the model switch, the pulse and every lander event did. Own fixture, own
  # clock, own state: two sessions, one still mid-turn at the reset and one already back at its input box — the
  # case that gets the Escape and the case that must not are both asserted here.
  ta=$((t0 + 400000)); : > "$d/calls"; : > "$d/panes.list"
  rm -f "$d/.cc/state/claude-limit" "$d/.cc/state/limit-interrupted" "$d/.cc/state/limit-nudged" \
    "$d/.cc/state/limit-seen"
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((ta - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n✻ Thinking… (esc to interrupt)\n' > "$d/panes/@1"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/%7"
  printf '%s\n' '%7' > "$d/panes/@5.id"
  printf '@1\n' > "$d/panes/alpha.win"; printf '%s\n' '%7' > "$d/panes/beta.win"   # so the stub cc-msg can spool
  me "$ta" record @1 alpha >/dev/null 2>&1; me "$ta" record @5 beta >/dev/null 2>&1
  me $((ta + 1900)) resume >/dev/null 2>&1
  t 'a session still mid-turn at the reset has that turn ended first, with one Escape' \
    "$(grep -c '^keys @1 :: .*Escape' "$d/calls")" 1
  t '…and is nudged after it, so the line is TYPED instead of spooling behind a turn that never ends' \
    "$(calls '^msg alpha ')$(calls '^spool alpha ')" 10
  t 'a session already back at its input box is nudged with NO keystroke: Escape at a live pane interrupts it' \
    "$(grep -c '^keys %7' "$d/calls")$(calls '^msg beta ')" 01
  t 'nothing goes to the owner for the episode — automatic resume is routine, not a Slack post' \
    "$(calls '^notify ')" 0
  t '…the episode is on file instead, for cc-reconcile\'"'"'s digest and a debugging engineer' \
    "$(cat "$d/.cc/state/limit-resumed" 2>/dev/null | cut -f1,2)" "$ta	$((ta + 1800))"
  : > "$d/calls"; me $((ta + 1901)) resume >/dev/null 2>&1
  t 'and a resume with nothing left on file tells the owner nothing' "$(calls '^notify ')" 0

  # …AND NOT A TURN THAT STARTED AFTER THE 429 (review of #264). The ordinary 429 DOES end the turn; cc-msg's
  # drain then types the spooled lines at the freed pane and a new turn starts, with the stale limit line still on
  # screen. On the footer alone the reset would Escape that live turn mid-tool-call. Own fixture, own clock: one
  # session recorded IDLE and mid-turn at the reset (the case that must not be pressed) and one recorded mid-turn
  # and mid-turn still (the case that must), so neither can pass on the other's state.
  tf=$((ta + 7200)); : > "$d/calls"
  rm -f "$d/.cc/state/limit-interrupted" "$d/.cc/state/limit-nudged" "$d/.cc/state/limit-seen"
  printf '%s\t%s\tswitch\t%s\t%s\n' iso "$((tf - 60))" claude-opus-5 "1 session(s); test" > "$d/.cc/state/model.log"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n> \n' > "$d/panes/@1"
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n✻ Thinking… (esc to interrupt)\n' > "$d/panes/%7"
  me "$tf" record @1 alpha >/dev/null 2>&1; me "$tf" record @5 beta >/dev/null 2>&1
  t 'the record says which of the two was mid-turn when it was written, and only that one' \
    "$(awk -F'\t' '{printf "%s=%s ", $2, $5}' "$d/.cc/state/limit-interrupted")" 'alpha= beta=working '
  # …and now the OTHER way round at the reset: alpha has started a fresh turn, beta is still in the old one.
  printf 'Claude usage limit reached. Your limit will reset in 30 minutes\n✻ Thinking… (esc to interrupt)\n' > "$d/panes/@1"
  me $((tf + 1900)) resume >/dev/null 2>&1
  t 'a session that was NOT mid-turn when it was recorded is never Escaped, however busy it is at the reset:
     that is a turn it started after the 429, and the nudge waits behind it the way any line does' \
    "$(grep -c '^keys @1' "$d/calls")$(calls '^spool alpha ')$(calls '^msg alpha ')" 010
  t '…while the one that WAS mid-turn then and is mid-turn now is still ended and typed at' \
    "$(grep -c '^keys %7 :: .*Escape' "$d/calls")$(calls '^msg beta ')" 11

  # `status` ASKS cc-model FOR ITS NOTE, BOUNDED (48 copies piled up behind a cc-model that did not return in 400 s).
  # Its own clear HOME: a cc-model that answers is heard on stderr, one that hangs — and leaves a child holding its
  # output — is given up on inside the bound, and either way stdout says "clear" and the exit is 1.
  d2=$(mktemp -d); mkdir -p "$d2/.cc/state"
  sm(){ HOME="$d2" PATH="$d/bin:$PATH" CC_LIMIT_BIN="$d/bin" CC_LIMIT_STAMP="$d2/.cc/state/claude-limit" \
    CC_LIMIT_RECORD="$d2/.cc/state/limit-interrupted" CC_LIMIT_SEEN="$d2/.cc/state/limit-seen" CC_FAKE_CALLS="$d2/calls" \
    CC_LIMIT_OBSERVER=x CC_LIMIT_MODEL_WAIT=1 "$@" bash "$SELF" status; }
  out=$(sm env CC_FAKE_MODEL_SAY='claude-x: not available to this account' 2>&1); rc=$?
  t 'status, clear: cc-model saying a model is unavailable is a note on stderr, and stdout still reads clear' \
    "$rc $(grep -c '^note: claude-x: not available' <<<"$out") $(grep -cx clear <<<"$out")" '1 1 1'
  s0=$SECONDS; out=$(sm env CC_FAKE_MODEL_HANG=1 CC_FAKE_MODEL_SAY='claude-x: not available to this account' 2>&1); rc=$?
  t 'status, clear: a cc-model that hangs (a child holding its output) is given up on inside the bound — no note, still clear' \
    "$rc $(( SECONDS - s0 < 10 )) $(grep -c '^note:' <<<"$out") $(grep -cx clear <<<"$out")" '1 1 0 1'
  rm -rf "$d2"

  rm -rf "$d"; printf 'cc-limit selfcheck: %d passed, %d failed\n' $((n - bad)) "$bad"; [ "$bad" = 0 ]; }
