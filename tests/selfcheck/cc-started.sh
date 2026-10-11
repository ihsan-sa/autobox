# shellcheck shell=bash disable=SC2154,SC2034
# cc-started's selfcheck cases, moved out of bin/cc-started. That tool's selfcheck() sources this file, whose
# definition replaces it, and then calls it: the cases run in the tool's own shell, with its functions and
# globals, as they did when the body sat there. SC2154/SC2034 are off because those globals live in bin/cc-started.

selfcheck(){
  local n=0 f=0 W='demo/t1' rc
  T=$(mktemp -d); trap 'rm -rf "$T"' EXIT      # T is deliberately NOT local: the EXIT trap runs after this frame
  mkdir -p "$T/bin" "$T/.cc/state/$W"
  cat > "$T/bin/tmux" <<'STUB'
#!/usr/bin/env bash
case "$1" in
  list-windows)    [ -f "$CC_FAKE_GONE" ] || printf '@1 %s\n' "$CC_FAKE_WIN";;
  capture-pane)    cat "$CC_FAKE_SCREEN" 2>/dev/null;;
  display-message) printf '%s\n' "$CC_FAKE_CWD";;
esac
exit 0
STUB
  cat > "$T/bin/cc-slack" <<'STUB'
#!/usr/bin/env bash
printf 'cc-slack %s\n' "$*" >> "$CC_FAKE_CALLS"
[ -n "${CC_FAKE_DIALOG_STICKS:-}" ] || cp "$CC_FAKE_AFTER" "$CC_FAKE_SCREEN"   # the real one presses it through
STUB
  cat > "$T/bin/cc-msg" <<'STUB'
#!/usr/bin/env bash
printf 'cc-msg %s\n' "$*" >> "$CC_FAKE_CALLS"
cp "$CC_FAKE_AFTER" "$CC_FAKE_SCREEN"
STUB
  cat > "$T/bin/cc-notify" <<'STUB'
#!/usr/bin/env bash
printf 'notify %s\n' "$*" >> "$CC_FAKE_CALLS"
STUB
  chmod +x "$T"/bin/*
  export HOME="$T" CC_STARTED_BIN="$T/bin" CC_FAKE_SCREEN="$T/screen" CC_FAKE_AFTER="$T/after" \
         CC_FAKE_CALLS="$T/calls" CC_FAKE_WIN="$W" CC_FAKE_GONE="$T/gone" CC_FAKE_CWD="$T/wt" \
         PATH="$T/bin:$PATH"
  BIN="$T/bin"; WAIT=2; POLL=0.2      # the globals themselves: they were read from the environment at load,
                                      # long before this function set HOME
  local BOX='╭──────────────────────╮
│ > Try "fix the bug"  │
╰──────────────────────╯
  ? for shortcuts'
  local DIALOG='WARNING: Loading development channels can be unsafe.
 ❯ 1. I am using this for local development
   2. Exit
 Enter to confirm · Esc to cancel'
  local PERM='Do you want to run this command?
❯ 1. Yes
  2. No, and tell Claude what to do differently
  Esc to cancel'
  local LOGIN='Welcome to Claude Code
Select login method:
❯ 1. Claude account with subscription
  2. Anthropic Console account'
  local BUSY='⏺ Read(progress.md)
✻ Thinking… (esc to interrupt)'
  k(){ n=$((n+1)); if [ "$1" = 0 ]; then echo "  ok   $2"; else echo "  FAIL $2"; f=$((f+1)); fi; }
  scr(){ printf '%s\n' "$1" > "$T/screen"; }
  after(){ printf '%s\n' "$1" > "$T/after"; }
  calls(){ cat "$T/calls" 2>/dev/null; }
  # …and the call log is GREPPED AS A FILE, never `calls | grep -q`: grep -q quits at the first match, cat takes
  # SIGPIPE, and this file's `set -o pipefail` calls that a failed assertion — a red about one run in five, and a
  # silent PASS on every case that asserts nothing was called. `$(calls)` and `grep -c` read to the end: safe.
  said(){ grep -q "$@" "$T/calls" 2>/dev/null; }
  reset(){ : > "$T/calls"; rm -f "$T/gone" "$T/.cc/state/$W/inbox.spool" "$T/.cc/slack/enabled"
           rm -rf "$T/.claude" "$T/wt"; mkdir -p "$T/wt"; unset CC_FAKE_DIALOG_STICKS; }
  slackon(){ mkdir -p "$T/.cc/slack"; : > "$T/.cc/slack/enabled"; }   # what `cc slack on` leaves, and chan_accept reads
  transcript(){ local d   # in the shape cc-context reads it: <projects>/<cwd with / and . as ->/<session>.jsonl
                d="$T/.claude/projects/$(readlink -f "$T/wt" | sed 's#[/.]#-#g')"
                mkdir -p "$d"; printf '{"type":"assistant","message":{}}\n' > "$d/s.jsonl"
                [ "${1:-}" = old ] && touch -d '2 hours ago' "$d/s.jsonl"; return 0; }

  # ---- the healthy cases: nothing pressed, nothing drained, nobody told
  reset; scr "$BUSY"; started "$W"; rc=$?
  k "$([ "$rc" = 0 ] && [ -z "$(calls)" ] && echo 0 || echo 1)" "a session mid-turn is up: no keys, no drain, no page"
  reset; scr "$BOX"; started "$W"; rc=$?
  k "$([ "$rc" = 0 ] && [ -z "$(calls)" ] && echo 0 || echo 1)" "…and so is one idle at its prompt with nothing spooled for it"

  # Shapes one and two act on iteration one but are only SEEN as "running" on iteration two, once the stub's
  # cp has landed — a real second of wall clock, not the fixture's own doing. WAIT=2 leaves that second race
  # against $(date +%s)'s whole-second truncation (START is taken as "now minus 1, near enough"), so a box under
  # any load at all can burn the whole budget on fork overhead before the second read (shape one's planted
  # dialog failed that way at load 28). Widened for these two blocks only: the healthy cases above and the
  # shapes below pass or fail inside one iteration and do not need the room.
  local oldwait=$WAIT; WAIT=6
  # ---- SHAPE ONE: a startup popup, pressed through by cc-slack, then the pane is read again
  reset; scr "$DIALOG"; after "$BOX"; started "$W"; rc=$?
  k "$([ "$rc" = 0 ] && echo 0 || echo 1)" "a planted startup dialog ends with the session running"
  k "$(said -F "cc-slack accept-dialog $W" && echo 0 || echo 1)" "…because cc-slack was asked to press THAT window through"
  reset; scr "$DIALOG"; after "$BOX"; CC_FAKE_DIALOG_STICKS=1 started "$W"; rc=$?
  k "$([ "$rc" = 1 ] && said '^notify' && echo 0 || echo 1)" "…and a dialog that never clears is a page, not a silent window"
  k "$(said '^notify.*--decision' && echo 1 || echo 0)" "…filed, not pushed: any session can press a startup dialog, so it is not his to answer"
  # ONE PRESSER PER WINDOW. `cc` calls chan_accept on the line before this tool whenever Slack is on, and on a
  # successor's window cc-handoff's kick presses too: a second press loop here races the first, and the loser's
  # "2" and Enter land in the live input box as the session's first user turn.
  # (STICKS throughout, so the whole wait is spent with the dialog up: a press spawned in the background has every
  # chance to reach the call log before it is read, and an empty log means none was made.)
  reset; slackon; scr "$DIALOG"; CC_FAKE_DIALOG_STICKS=1 started "$W"; rc=$?
  k "$(said 'cc-slack' && echo 1 || echo 0)" "…and with Slack on, chan_accept is already pressing that window: this presses nothing"
  k "$([ "$rc" = 1 ] && said '^notify' && echo 0 || echo 1)" "…it still reads the pane back, and still says the dialog never cleared"
  reset; scr "$DIALOG"; QUIET=1; CC_FAKE_DIALOG_STICKS=1 started "$W"; rc=$?; QUIET=0
  k "$([ "$rc" = 1 ] && [ -z "$(calls)" ] && echo 0 || echo 1)" "…nor under --quiet, where cc-handoff's kick owns the successor's dialog and its deadline"

  # ---- SHAPE TWO: a first message that never landed — empty box, no transcript, something in the spool
  reset; scr "$BOX"; after "$BUSY"; echo '{"text":"hello"}' > "$T/.cc/state/$W/inbox.spool"
  started "$W"; rc=$?
  k "$([ "$rc" = 0 ] && echo 0 || echo 1)" "a lost first message ends with the session running"
  k "$([ "$(calls | grep -c "^cc-msg --drain $W")" = 1 ] && echo 0 || echo 1)" "…re-sent exactly once, through cc-msg's own spool"
  reset; scr "$BOX"; after "$BUSY"; echo '{"text":"hello"}' > "$T/.cc/state/$W/inbox.spool"; transcript
  started "$W" >/dev/null
  k "$(said 'cc-msg' && echo 1 || echo 0)" "…but a session whose transcript already holds a turn is never re-sent to"
  # …and an OLD transcript is not this session's. Every worktree that has ever run one has .jsonl files full of
  # assistant records; counting those made the drain unreachable anywhere but a brand-new box.
  reset; scr "$BOX"; after "$BUSY"; echo '{"text":"hello"}' > "$T/.cc/state/$W/inbox.spool"; transcript old
  started "$W" >/dev/null
  k "$([ "$(calls | grep -c "^cc-msg --drain $W")" = 1 ] && echo 0 || echo 1)" "…while a transcript LEFT BY AN EARLIER SESSION is not this one's first turn: it still drains"
  WAIT=$oldwait

  # ---- SHAPE THREE: a login screen — the owner is paged and this stops, having pressed nothing
  reset; scr "$LOGIN"; started "$W"; rc=$?
  k "$([ "$rc" = 3 ] && said '^notify.*--decision' && echo 0 || echo 1)" "a logged-out pane pages the owner and stops"
  k "$(said -e 'cc-slack' -e 'cc-msg' && echo 1 || echo 0)" "…and nothing was typed or pressed at a login screen"
  reset; scr "$(printf 'the runbook says: Please run /login\n%s' "$BOX")"; TAIL=4; started "$W" >/dev/null; TAIL=25
  k "$(said '^notify' && echo 1 || echo 0)" "…while the same words in the scrollback above a live prompt are not one"

  # ---- the owner's own gate is never answered by a script (the 48-minute successor of 2026-09-05)
  reset; scr "$PERM"; started "$W"; rc=$?
  k "$([ "$rc" = 1 ] && said 'permission prompt' && echo 0 || echo 1)" "a permission prompt is waited out and reported, never pressed"
  k "$(said 'cc-slack' && echo 1 || echo 0)" "…and cc-slack is not asked to press an owner gate"
  # …AT A RUNG THAT REACHES HIM. Without --decision the title's second word decides, and "startup" is not a word
  # cc-notify's table knows: the message saying only he can answer would go to the lane he reads when he looks.
  k "$(said '^notify.*--decision' && echo 0 || echo 1)" "…and it is escalated, not filed: nobody but the owner can clear that gate"
  # …not even with the startup words on the screen above it. accept-dialog's Enter would go INTO the prompt.
  reset; scr "$(printf '%s\n%s' "$DIALOG" "$PERM")"; after "$BOX"; TAIL=5; started "$W"; rc=$?; TAIL=25
  k "$(said 'cc-slack' && echo 1 || echo 0)" "startup words in the scrollback ABOVE a permission prompt press nothing — the foot of the pane is the dialog"
  k "$([ "$rc" = 1 ] && said 'permission prompt' && echo 0 || echo 1)" "…and it is reported as what it is"

  # …but A BUSY SESSION IS NOT A BLOCKED ONE. `cc <repo> <track>` replays the track's transcript, so an
  # already-answered dialog is redrawn in the scrollback of a session that is working fine; asked before the
  # working footer, that pane burned the whole wait and then paged the owner about a healthy session.
  reset; scr "$(printf '%s\n%s' "$PERM" "$BUSY")"; started "$W"; rc=$?
  k "$([ "$rc" = 0 ] && [ -z "$(calls)" ] && echo 0 || echo 1)" "an answered dialog ABOVE a working footer is a busy session, not a gate: no page"
  reset; scr "$(printf 'I asked the owner: Do you want to deploy tonight?\n%s' "$BOX")"; TAIL=4; started "$W"; rc=$?; TAIL=25
  k "$([ "$rc" = 0 ] && [ -z "$(calls)" ] && echo 0 || echo 1)" "…and the same words in the scrollback above a live prompt are prose, not a prompt"

  # ---- a pane that draws nothing, and a window that is not there
  reset; scr ""; started "$W"; rc=$?
  k "$([ "$rc" = 1 ] && said 'drew no prompt' && echo 0 || echo 1)" "a pane that never drew a prompt is a page, not a pass"
  k "$(said '^notify.*--decision' && echo 1 || echo 0)" "…filed too: a window that never started is restarted by the box, not by him"
  reset; scr "$BOX"; : > "$T/gone"; started "$W"; rc=$?
  k "$([ "$rc" = 2 ] && [ -z "$(calls)" ] && echo 0 || echo 1)" "no window at all is exit 2 and no page — whoever killed it owns that"

  # ---- --quiet: the handoff successor's window, whose deadline cc-handoff's kick already owns
  reset; scr ""; QUIET=1; started "$W"; rc=$?
  k "$([ "$rc" = 1 ] && [ -z "$(calls)" ] && echo 0 || echo 1)" "--quiet says nothing at the deadline — cc-handoff's kick already alerts on that window"
  reset; scr "$LOGIN"; started "$W"; rc=$?
  k "$([ "$rc" = 3 ] && said '^notify' && echo 0 || echo 1)" "…but a login screen is said whoever else is watching: nobody else looks for it"
  reset; scr "$PERM"; started "$W"; rc=$?; QUIET=0
  k "$([ "$rc" = 1 ] && said 'permission prompt' && said '^notify.*--decision' && echo 0 || echo 1)" "…and so is a standing permission prompt, at the same rung — the successor that sat on one for 48 minutes is this exact window"

  # ---- a fixture name never reaches the owner, whatever its pane says
  reset; scr "$LOGIN"; started "_cctest99/t1"; rc=$?
  k "$([ "$rc" = 0 ] && [ -z "$(calls)" ] && echo 0 || echo 1)" "a _cctest window is a fixture: nothing is read, nobody is told"

  echo "cc-started selfcheck: $((n - f)) passed, $f failed"
  [ "$f" = 0 ]
}
