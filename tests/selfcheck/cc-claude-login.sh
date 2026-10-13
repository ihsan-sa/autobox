# shellcheck shell=bash disable=SC2154,SC2034
# cc-claude-login's selfcheck cases. The tool's selfcheck() sources this file, whose definition replaces it, and
# then calls it. Every case runs against a fake claude, a HOME of its own and a tmux server on its own socket, so it
# never touches this box's logins or its tmux.

selfcheck(){
  local n=0 f=0 rc out
  k(){ n=$((n+1)); if [ "$1" = 0 ]; then echo "  ok   $2"; else echo "  FAIL $2"; f=$((f+1)); fi; }
  T="$(mktemp -d)"; trap 'tmux -S "$T/sock" kill-server 2>/dev/null; rm -rf "$T"' EXIT
  mkdir -p "$T/home"
  # The fake claude: `auth login` prints a link that is wider than a default pane and waits for a code; "good"
  # writes credentials into CLAUDE_CONFIG_DIR, anything else is refused. `auth status` reads them back. The
  # second line of a login is a counter, so a reused login is told apart from a new one.
  cat >"$T/claude" <<'EOF'
#!/usr/bin/env bash
case "$1 $2" in
  "auth login")
    echo "started" >>"$CLAUDE_CONFIG_DIR/logins"
    printf 'Browser didn'"'"'t open? Use the url below to sign in:\n\n'
    printf 'https://claude.ai/oauth/authorize?code=true&client_id=fake&state=%s%0200d\n\n' "$(wc -l <"$CLAUDE_CONFIG_DIR/logins")" 0
    printf 'Paste code here if prompted > '
    read -r c
    [ "$c" = good ] || { echo "OAuth error: invalid code"; exit 1; }
    echo '{"token":"x"}' >"$CLAUDE_CONFIG_DIR/.credentials.json"; echo "Login successful."; exit 0 ;;
  "auth status")
    if [ -f "$CLAUDE_CONFIG_DIR/.credentials.json" ]; then echo '{ "loggedIn": true }'; else echo '{ "loggedIn": false }'; fi ;;
esac
EOF
  chmod +x "$T/claude"
  L(){ HOME="$T/home" CC_CLAUDE_BIN="$T/claude" CC_LOGIN_TMUX="$T/sock" CC_LOGIN_WAIT=10 "$B/cc-claude-login" "$@"; }
  S(){ tmux -S "$T/sock" has-session -t "=cc-login-$1" 2>/dev/null; }

  out=$(L start workers); rc=$?
  k "$([ $rc = 0 ] && grep -q -E '^https://claude\.ai/oauth/authorize\?code=true&client_id=fake&state=1(0{200})$' <<<"$out" && echo 0 || echo 1)" \
    "start prints the whole login link on one line, unwrapped"
  k "$([ -d "$T/home/.claude-workers" ] && [ "$(stat -c %a "$T/home/.claude-workers")" = 700 ] && echo 0 || echo 1)" \
    "…and the login runs against ~/.claude-<name>, made private"
  k "$(S workers && echo 0 || echo 1)" "…and stays waiting in its own tmux session after start returns"
  out2=$(L start workers); rc=$?
  k "$([ $rc = 0 ] && [ "$out2" = "$out" ] && [ "$(wc -l <"$T/home/.claude-workers/logins")" = 1 ] && echo 0 || echo 1)" \
    "a second start while it waits prints the same link and starts no second login"

  out=$(L code workers bad); rc=$?
  k "$([ $rc = 1 ] && grep -q '"loggedIn": false' <<<"$out" && echo 0 || echo 1)" "a code the login refuses exits 1 and says not logged in"
  k "$(S workers && echo 1 || echo 0)" "…and its session is gone"
  L code workers good >/dev/null 2>&1; rc=$?
  k "$([ $rc = 1 ] && echo 0 || echo 1)" "a code with no login waiting exits 1"

  L start workers >/dev/null && out=$(L code workers good); rc=$?
  k "$([ $rc = 0 ] && grep -q '"loggedIn": true' <<<"$out" && [ -f "$T/home/.claude-workers/.credentials.json" ] && echo 0 || echo 1)" \
    "a fresh start and the right code log ~/.claude-workers in"
  k "$(S workers && echo 1 || echo 0)" "…and its session is gone"
  L status workers >/dev/null; rc=$?; k "$([ $rc = 0 ] && echo 0 || echo 1)" "status exits 0 for the logged-in name"
  L status other >/dev/null; rc=$?; k "$([ $rc = 1 ] && echo 0 || echo 1)" "…and 1 for a name that never logged in"

  for bad in ../x "a/b" "" "-x" "has space"; do
    L start "$bad" >/dev/null 2>&1; rc=$?
    k "$([ $rc = 2 ] && echo 0 || echo 1)" "start refuses the name '$bad' (usage, exit 2)"
  done
  k "$([ ! -e "$T/home/.claude-" ] && [ ! -e "$T/.claude-x" ] && echo 0 || echo 1)" "…and makes no directory for one"

  printf '#!/bin/sh\necho "no link here"; sleep 30\n' >"$T/mute"; chmod +x "$T/mute"
  out=$(HOME="$T/home" CC_CLAUDE_BIN="$T/mute" CC_LOGIN_TMUX="$T/sock" CC_LOGIN_WAIT=1 "$B/cc-claude-login" start quiet 2>&1); rc=$?
  k "$([ $rc = 1 ] && grep -q 'no link here' <<<"$out" && echo 0 || echo 1)" "a login that shows no link exits 1 and shows its screen"
  k "$(S quiet && echo 1 || echo 0)" "…and leaves no session behind"

  echo "cc-claude-login selfcheck: $((n - f)) passed, $f failed"; [ "$f" = 0 ]
}
