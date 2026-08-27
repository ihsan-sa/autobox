# <box> — Remote Access Runbook (<date>) — source of truth: ~/dev/<control-repo>

## Access paths
1. Tailscale (primary): `ssh <user>@<tailscale-ip>` — MagicDNS `<box>.<tailnet>.ts.net`. Tailscale SSH, auth = your tailnet identity. Key expiry: disabled. Laptop `<laptop-name>` = `<laptop-tailscale-ip>`. Verified cable-out.
2. Cloudflare Tunnel (secondary): `ssh <box>` from the laptop → Access one-time-PIN email → shell. Hostname `<public-hostname>` (proxied CNAME). Tunnel `<tunnel-name>` is run by the `cloudflared` systemd service via the token in `/etc/cloudflared/token`; ingress is dashboard-managed (SSH → localhost:22). Access app "<box> SSH", policy allows `<owner-email>`. Laptop needs cloudflared installed and `~/.ssh/config`:
   ```
   Host <box>
     HostName <public-hostname>
     User <user>
     ProxyCommand cloudflared access ssh --hostname %h
   ```
3. Rescue cable: laptop adapter `<laptop-rescue-ip>` (no gateway) → `ssh <user>@<rescue-ip>`. Static on `<iface>`; never remove.
4. Phone: Claude app → Code → session `<box>` (Remote Control; the `tmux-main` user service starts it at every boot). Or any phone SSH app over Tailscale, then `tmux attach -t main`.

## Sessions (scripts in ~/bin)
- `cc` attach tmux `main`; `cc <project>` opens a window in ~/dev/<project> running `claude --remote-control <project>`; `cc -c <project>` continues its last conversation; `cc ls`.
- The always-on boot session: tmux `main`, window `box`, running a Remote-Control Claude in ~/dev.
- `ccbox <project>` — sandboxed `--dangerously-skip-permissions` Claude in Docker: only ~/dev/<project> mounted as /workspace, shared login volume `ccbox-claude`, egress limited to ~/ccbox/allowed-domains (+GitHub); `ccbox <p> --open-egress` lifts the firewall; `-c` continues. GitHub/Vercel tokens go in ~/ccbox/env (chmod 600). Inner tmux prefix C-a. `ccbox ls|stop|rm|shell|logs|build`.
- `box-status` — one-screen health check.
- Slack ↔ sessions: `cc-slackd` (user service, `cc slack on|off|status`) holds the box's single Socket-Mode connection and routes `#<repo>` to that repo's session; sessions load the channel when started after `cc slack on`. To give the boot session the channel (ends its current Remote-Control conversation): `cc rc restart`. Tokens/owner in `~/.cc/config` (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_OWNER_ID`); unpair by deleting `SLACK_OWNER_ID` and restarting the unit.
- `cc-notify setup` once → phone ntfy app subscribes to the topic; sessions/loops push to you when they need a decision. `cc digest` = status of all orchestrated work.
- `cc <repo> --orch <alias>` — a peer orchestrator: same planning-session conventions as `cc <repo>` (primary worktree, no auto-commit hook, may merge) but addressable in Slack by `@<alias>`; merge authority is per-repo policy set in that repo's own docs, not here.

## Network
- /etc/netplan/99-server.yaml (mode 600): `<iface>` dhcp4 + static `<rescue-ip>/24`; `<wlan-iface>` dhcp4 with APs `<hotspot-ssid>` and `<home-ssid>`; both optional.
- Ethernet MAC (home DHCP reservation): `<mac>`. WiFi MAC: `<wlan-mac>`.
- chrony: NTS TLS can fail on some networks; check `chronyc tracking` after a move.

## Rescue
1. Cable laptop↔box, laptop `<laptop-rescue-ip>` no gateway, `ssh <user>@<rescue-ip>`.
2. If that fails: attach monitor + keyboard.
- Wedged session? DM the bot (works with no live Claude session, cc-slackd only): `!restart box` / `!restart <repo>[/<track>]` kills that tmux window and restarts it, `!restart slack` restarts `cc-slackd` itself; last resort `!restart tmux` then `!restart tmux confirm` within 2 min restarts `tmux-main.service` (kills every session on the box).
- Whole box unresponsive at the OS level (not just a session)? `!reboot` then `!reboot confirm` within 2 min (a detached `systemctl reboot`): everything returns via systemd + BIOS AC-recovery, the boot notice posts automatically, and the power log labels it `cause=clean-reboot`.
- Agents can pull Slack history/thread context themselves (`cc-slack history`/`thread`) — small n by design, an information diet rather than a full-context dump.
- Box rebooted by itself: `cat ~/.cc/state/power-events.log` (cut times from `cc-heartbeat`; each boot line carries `cause=clean-reboot|power-loss|unknown`, read from the previous boot's journal; `cc-heartbeat --dry-run [<last_alive>]` shows the line it would write); `journalctl -b -1 | tail` with no `Shutting down` line = power loss/hard reset, not the OS; SSD attr 235 `POR_Recovery_Count` counts sudden power losses. Every boot posts to Slack/ntfy (`cc-boot-notify`). BIOS AC Recovery = On brings it back when power returns.

## Policy
- No host firewall (ufw/nftables); Docker manages only its own container rules.
- sshd: socket-activated (ssh.socket enabled). Key-only: PasswordAuthentication no + KbdInteractiveAuthentication no via /etc/ssh/sshd_config.d/10-hardening.conf (overrides 50-cloud-init.conf; keep a backup of the original).
- Reboots: the reboot ask-gate stays in ~/.claude/settings.json (the harness classifier blocks Claude from removing its own gate) and reboots are independently classifier-gated. Verify boot-time WiFi/Tailscale autoconnect + the tmux-main session across one reboot. Unattended-upgrades: security pockets only, no auto-reboot. Sleep/suspend/hibernate targets masked.
- Owner TODO: home-router DHCP reservation for `<mac>`.
