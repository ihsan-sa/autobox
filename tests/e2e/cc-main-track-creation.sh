#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# cc-main-track-creation.sh — the stanza "cc main + track creation", run alone on the fixtures it stands on.
. "$(dirname "$0")/lib.sh"
# ── the stanza
if stanza "cc main + track creation" always; then
cd ~ && "$B/cc" $REPO >/dev/null 2>&1; sleep 1; tmux list-windows -t main -F '#W' | grep -qx "$REPO" && ok "main window created" || bad "main window"
# …on THIS RUN'S server, and the same `cc $REPO` aimed at the default socket opens nothing: a `_` name is a fixture's.
# A stub tmux stands in for the live server, so a broken refusal logs a new-window instead of opening one there.
mkdir -p "$T/livestub"; printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s/livestub/log"\nexit 0\n' "$T" > "$T/livestub/tmux"; chmod +x "$T/livestub/tmux"
lo=$(cd ~ && env -u TMUX -u TMUX_TMPDIR PATH="$T/livestub:$PATH" "$B/cc" $REPO 2>&1); lrc=$?
{ [ "$(tmux display-message -p -t main '#{socket_path}')" = "$T/tmux/tmux-$(id -u)/default" ] && [ "$lrc" = 1 ] \
  && grep -q "test fixture" <<<"$lo" && ! grep -qs new-window "$T/livestub/log"; } \
  && ok "a fixture's windows are on the run's own tmux server, and cc refuses a _ name on the default socket" \
  || bad "fixture on the live tmux server (rc=$lrc): $lo | $(tr '\n' '|' < "$T/livestub/log" 2>/dev/null)"
# …and a TMUX_TMPDIR that spells /tmp another way (/tmp/. or /tmp/) is the same default socket, refused the same way.
for tdir in /tmp/. /tmp/; do : > "$T/livestub/log"
  lo=$(cd ~ && env -u TMUX TMUX_TMPDIR="$tdir" PATH="$T/livestub:$PATH" "$B/cc" $REPO 2>&1); lrc=$?
  { [ "$lrc" = 1 ] && grep -q "test fixture" <<<"$lo" && ! grep -qs new-window "$T/livestub/log"; } \
    && ok "cc refuses a _ name with TMUX_TMPDIR=$tdir, the default socket spelt another way" \
    || bad "TMUX_TMPDIR=$tdir got past the live-server refusal (rc=$lrc): $lo | $(tr '\n' '|' < "$T/livestub/log" 2>/dev/null)"
done
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
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
