# shellcheck shell=bash disable=SC2154,SC2034
# cc-tier's selfcheck cases, moved out of bin/cc-tier. That tool's selfcheck() sources this file, whose
# definition replaces it, and then calls it: the cases run in the tool's own shell, with its functions and
# globals, as they did when the body sat there. SC2154/SC2034 are off because those globals live in bin/cc-tier.

selfcheck(){
  local n=0 f=0 rc out before   # T is NOT local: the EXIT trap that removes it fires outside this function
  k(){ n=$((n+1)); if [ "$1" = 0 ]; then echo "  ok   $2"; else echo "  FAIL $2"; f=$((f+1)); fi; }
  T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
  # A HOME of its own: its own config (cc-config honours CC_CONFIG), its own boards and its own log — never this
  # box's tier, and never this box's boards. cc-board reads $HOME/.cc/boards, so HOME is the fixture's.
  # The hive's steer file is the fixture's too: a real one would stop the hive's loops on every run of this.
  mkdir -p "$T/home/.cc/boards" "$T/home/.cc/state/land/queue" "$T/steer"
  C(){ HOME="$T/home" CC_CONFIG="$T/home/.cc/config" CC_TIER_STEER="$T/steer/tier.txt" "$B/cc-tier" "$@"; }
  BOARD(){ HOME="$T/home" "$B/cc-board" "$@"; }
  BOARD init alpha "$T/home/dev/alpha" >/dev/null 2>&1 || true
  BOARD init beta "$T/home/dev/beta" >/dev/null 2>&1 || true
  BOARD add alpha crit "the critical one" >/dev/null 2>&1
  BOARD add alpha plain "an ordinary row" >/dev/null 2>&1
  BOARD add beta other "another repo's row" >/dev/null 2>&1
  BOARD set alpha crit critical yes >/dev/null 2>&1

  k "$([ "$(C)" = autonomous ] && echo 0 || echo 1)" "no setting at all reads as autonomous (the default)"
  HOME="$T/home" CC_CONFIG="$T/home/.cc/config" "$B/cc-config" set CC_SPEND_TIER sideways
  k "$([ "$(C)" = autonomous ] && echo 0 || echo 1)" "a word this file does not know reads as autonomous, never as a stop nobody asked for"
  C set sideways >/dev/null 2>&1; rc=$?; k "$([ $rc = 2 ] && echo 0 || echo 1)" "…and set refuses it"
  out=$(C set stop); rc=$?
  k "$([ $rc = 0 ] && [ "$(C)" = stop ] && echo 0 || echo 1)" "set stop writes the config and reads back"
  k "$(grep -q '^The spend tier is stop, since 20' <<<"$out" && echo 0 || echo 1)" "…and prints the line, dated since the flip"
  k "$(grep -q ' autonomous -> stop$' "$T/home/.cc/state/tier.log" && echo 0 || echo 1)" "…and logs old -> new"
  k "$([ "$(cat "$T/steer/tier.txt" 2>/dev/null)" = stop ] && echo 0 || echo 1)" "…and writes the word to the hive's steer file, so its loops hold"

  # THE TABLE, every cell, one row of asserts per tier. `t` = the tier, then start / start on a critical row /
  # start on a plain row / continue on a critical row / continue on a plain row / gates / pulse / goals / explore,
  # each `y` or `n`.
  cells(){ local t="$1" got="" q
    C set "$t" >/dev/null
    for q in "start" "start alpha/crit" "start alpha/plain" "continue alpha/crit" "continue alpha/plain" gates pulse goals explore; do
      if C allows $q 2>/dev/null; then got+=y; else got+=n; fi; done
    echo "$got"; }
  k "$([ "$(cells stop)" = nnnnnnnnn ] && echo 0 || echo 1)" "stop: nothing starts or continues, no gates, no pulse, no goals, no exploring — a critical row included"
  k "$([ "$(cells essential)" = yynynyynn ] && echo 0 || echo 1)" "essential: a critical row starts and continues, a plain one waits; gates and the pulse run; goals and exploring wait"
  k "$([ "$(cells moderate)" = yyyyyyyyn ] && echo 0 || echo 1)" "moderate: everything but exploring"
  k "$([ "$(cells autonomous)" = yyyyyyyyy ] && echo 0 || echo 1)" "autonomous: everything"

  # ONE AT A TIME under essential, read off the boards: a row running on ANY board holds the next start, the
  # running row itself may go on (its next iteration asks with its own name), and the other tiers ignore it.
  C set essential >/dev/null
  BOARD status beta other running >/dev/null 2>&1
  C allows start alpha/crit 2>/dev/null; rc=$?; k "$([ $rc = 1 ] && echo 0 || echo 1)" "essential: a row running on another board holds a critical start"
  BOARD status beta other queued >/dev/null 2>&1; BOARD status alpha crit running >/dev/null 2>&1
  C allows start alpha/crit 2>/dev/null; rc=$?; k "$([ $rc = 0 ] && echo 0 || echo 1)" "…the running critical row itself may take its next iteration"
  C allows start 2>/dev/null; rc=$?; k "$([ $rc = 1 ] && echo 0 || echo 1)" "…and with no row named, a running row means no start"
  BOARD status beta other running >/dev/null 2>&1
  C allows continue alpha/crit; rc=$?; k "$([ $rc = 0 ] && echo 0 || echo 1)" "…and a critical row running beside another running row still continues: one-at-a-time is about starts"
  BOARD status beta other queued >/dev/null 2>&1
  C set moderate >/dev/null
  C allows start alpha/plain; rc=$?; k "$([ $rc = 0 ] && echo 0 || echo 1)" "control: moderate starts a plain row beside a running one"
  BOARD status alpha crit queued >/dev/null 2>&1
  BOARD add alpha chat "a channel session" >/dev/null 2>&1; BOARD set alpha chat kind session >/dev/null 2>&1
  BOARD status alpha chat running >/dev/null 2>&1
  C set essential >/dev/null
  C allows start alpha/crit 2>/dev/null; rc=$?; k "$([ $rc = 0 ] && echo 0 || echo 1)" "a running session row (kind=session) is not work in flight and holds nothing"

  # AN AGENT-MARKED ROW IS NOT A WORKER (raised-agent-mark-blocks-critical-starts-under-essential): the reconciler
  # shows a seat's marked row `running`, and it held a critical PR eight hours. Its own board, so no earlier case's
  # state stands in: the same running row holds a critical start unmarked, and holds nothing once marked.
  BOARD init gamma "$T/home/dev/gamma" >/dev/null 2>&1 || true
  BOARD add gamma g1 "a critical row" >/dev/null 2>&1; BOARD set gamma g1 critical yes >/dev/null 2>&1
  BOARD add gamma sub "a seat's subagent row" >/dev/null 2>&1; BOARD status gamma sub running >/dev/null 2>&1
  out=$(C allows start gamma/g1 2>&1); rc=$?
  k "$([ $rc = 1 ] && grep -q 'gamma/sub is running' <<<"$out" && echo 0 || echo 1)" "control: an unmarked running row holds a critical start, and the hold names that row"
  python3 -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["tracks"]["sub"]["agent"]="@3:99"; json.dump(d,open(p,"w"))' "$T/home/.cc/boards/gamma.json"
  C allows start gamma/g1; rc=$?; k "$([ $rc = 0 ] && echo 0 || echo 1)" "an agent-marked running row is a seat's subagent, not a worker, and holds nothing"
  BOARD status gamma sub queued >/dev/null 2>&1

  # A ROW WITH A PR IS CONTINUED, NOT STARTED (the landing asks `start` for its repair round): a critical row with a
  # PR starts beside a running row, one without a PR does not, and a PR does not stand in for the critical mark.
  BOARD init delta "$T/home/dev/delta" >/dev/null 2>&1 || true
  BOARD add delta fix "a critical row with a PR" >/dev/null 2>&1; BOARD set delta fix critical yes >/dev/null 2>&1
  BOARD set delta fix pr 127 >/dev/null 2>&1
  BOARD add delta new "a critical row with no PR" >/dev/null 2>&1; BOARD set delta new critical yes >/dev/null 2>&1
  BOARD add delta pl "a plain row with a PR" >/dev/null 2>&1; BOARD set delta pl pr 128 >/dev/null 2>&1
  BOARD add delta busy "a worker" >/dev/null 2>&1; BOARD status delta busy running >/dev/null 2>&1
  C allows start delta/fix; rc=$?; k "$([ $rc = 0 ] && echo 0 || echo 1)" "essential: a critical row's repair round on its PR goes beside a running worker"
  C allows start delta/new 2>/dev/null; rc=$?; k "$([ $rc = 1 ] && echo 0 || echo 1)" "…a critical row with no PR still waits its turn"
  out=$(C allows start delta/pl 2>&1); rc=$?
  k "$([ $rc = 1 ] && grep -q 'delta/pl is not marked critical' <<<"$out" && echo 0 || echo 1)" "…and a PR is not a critical mark: a plain row waits, and the hold says it is the mark"
  BOARD status delta busy queued >/dev/null 2>&1

  # THE WORD A PERSON SET IS READ, NOT REWRITTEN: allows never writes the board or the config.
  before=$(md5sum "$T/home/.cc/boards/alpha.json" "$T/home/.cc/config" | md5sum)
  C allows start alpha/crit >/dev/null 2>&1; C allows goals >/dev/null 2>&1; C line >/dev/null
  k "$([ "$before" = "$(md5sum "$T/home/.cc/boards/alpha.json" "$T/home/.cc/config" | md5sum)" ] && echo 0 || echo 1)" "allows and line read; neither writes the board or the config"

  # LEAVING STOP names the landing jobs it held, as cc-pause off does; entering it, or any other flip, says nothing.
  C set stop >/dev/null; echo '{"repo":"alpha","pr":7}' > "$T/home/.cc/state/land/queue/alpha-7.json"
  out=$(C set essential); k "$(grep -q '^1 landing job(s) waited for this' <<<"$out" && echo 0 || echo 1)" "leaving stop names the landing jobs that waited, and the command that drives them"
  out=$(C set moderate); k "$(grep -q 'landing job' <<<"$out" && echo 1 || echo 0)" "…a flip that was not from stop does not"
  k "$([ "$(cat "$T/steer/tier.txt" 2>/dev/null)" = moderate ] && echo 0 || echo 1)" "the steer file follows each flip"
  out=$(HOME="$T/home" CC_CONFIG="$T/home/.cc/config" CC_TIER_STEER="$T/none/tier.txt" "$B/cc-tier" set moderate 2>&1); rc=$?
  k "$([ $rc = 0 ] && [ ! -e "$T/none" ] && echo 0 || echo 1)" "a box with no hive (no steer dir) sets the tier and writes nothing there"
  C allows sideways >/dev/null 2>&1; rc=$?; k "$([ $rc = 2 ] && echo 0 || echo 1)" "a question this file does not know is usage, not a verdict"
  C allows start alpha >/dev/null 2>&1; rc=$?; k "$([ $rc = 2 ] && echo 0 || echo 1)" "a row is <repo>/<row>; a bare repo is refused rather than read as one"
  k "$(grep -q '^The spend tier is moderate, since .*\. Work it finds itself' <<<"$(C line)" && echo 0 || echo 1)" "line: the tier, since when, and what it means"
  echo "cc-tier selfcheck: $((n - f)) passed, $f failed"
  [ "$f" -eq 0 ]
}
