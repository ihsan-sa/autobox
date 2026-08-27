#!/bin/bash
# ccbox container entrypoint (runs as node): egress firewall -> git/gh setup -> trust the workspace -> claude in tmux.
# docker stop -> TERM -> tmux kill-server -> exit 143; when claude exits the tmux session ends and the container exits.
set -uo pipefail
trap 'tmux kill-server 2>/dev/null; exit 143' TERM INT   # installed before the firewall run so docker stop is honoured from the first second
if [ "${CCBOX_OPEN_EGRESS:-0}" = "1" ]; then echo "ccbox: egress OPEN (no firewall)"; else sudo /usr/local/bin/init-firewall.sh || { echo "ccbox: firewall setup FAILED - refusing to start"; exit 1; }; fi
[ -n "${GIT_AUTHOR_NAME:-}" ]  && git config --global user.name  "$GIT_AUTHOR_NAME"
[ -n "${GIT_AUTHOR_EMAIL:-}" ] && git config --global user.email "$GIT_AUTHOR_EMAIL"
[ -n "${GH_TOKEN:-}" ] && gh auth setup-git >/dev/null 2>&1 && echo "ccbox: git credential helper = gh (GH_TOKEN)"
NAME="${CCBOX_NAME:-ccbox}"; WS="/workspace/$NAME"   # one dir per project: sessions/memory/trust never bleed across projects
f="$CLAUDE_CONFIG_DIR/.claude.json"; [ -f "$f" ] || echo '{}' > "$f"
jq --arg ws "$WS" '.projects[$ws] = ((.projects[$ws] // {}) + {hasTrustDialogAccepted: true}) | .hasCompletedOnboarding = true | .bypassPermissionsModeAccepted = true | .theme = (.theme // "dark")' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
[ -x /usr/local/bin/ccbox-project-init ] && /usr/local/bin/ccbox-project-init   # project images (ccbox build <name>) hook their per-workspace setup here
if [ -n "${CCBOX_CMD:-}" ]; then   # headless: run the given command instead of interactive claude (ccbox <name> --cmd "...")
  printf '%s\n' "$CCBOX_CMD" > /tmp/ccbox-cmd.sh   # via a file (any quoting survives); NOT a login shell: Debian /etc/profile would reset PATH
  tmux new-session -d -s main -c "$WS" "bash /tmp/ccbox-cmd.sh; echo; echo 'command exited - shell (type exit to stop the container)'; exec bash"
else
  tmux new-session -d -s main -c "$WS" "claude --dangerously-skip-permissions --remote-control ccbox-${NAME} ${CCBOX_CLAUDE_ARGS:-}; echo 'claude exited - stopping the container'"
fi
while tmux has-session -t main 2>/dev/null; do sleep 5 & wait $!; done
