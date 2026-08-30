# <box> — Remote Access Runbook (<date>) — source of truth: ~/dev/<control-repo>

Getting in, and what to do when it breaks. The commands themselves are `~/USAGE.md`.

## Access paths
1. Tailscale (primary): `ssh <user>@<tailscale-ip>` — MagicDNS `<box>.<tailnet>.ts.net`. Tailscale SSH, auth = your tailnet identity, key expiry disabled. Laptop `<laptop-name>` = `<laptop-tailscale-ip>`.
2. Cloudflare Tunnel (secondary): `ssh <box>` from the laptop → Access one-time-PIN email → shell. Hostname `<public-hostname>` (proxied CNAME). Tunnel `<tunnel-name>` runs as the `cloudflared` systemd service via the token in `/etc/cloudflared/token`; ingress is dashboard-managed (SSH → localhost:22). Access app "<box> SSH", policy allows `<owner-email>`. Laptop needs cloudflared installed and `~/.ssh/config`:
   ```
   Host <box>
     HostName <public-hostname>
     User <user>
     ProxyCommand cloudflared access ssh --hostname %h
   ```
3. Rescue cable: laptop adapter `<laptop-rescue-ip>` (no gateway) → `ssh <user>@<rescue-ip>`. Static on `<iface>`; never remove.
4. Phone: Claude app → Code → session `<box>` (Remote Control; the `tmux-main` user service starts it at every boot). Or any phone SSH app over Tailscale, then `tmux attach -t main`.

## Getting to a session
- `cc` attaches tmux `main`. The always-on boot session is window `box`, a Remote-Control Claude in `~/dev`. `box-status` is the one-screen health check. Everything else: `~/USAGE.md`.
- Slack ↔ sessions: `cc-slackd` (user service, `cc slack on|off|status`) holds the box's single Socket-Mode connection and routes `#<repo>` to that repo's session; sessions load the channel when started after `cc slack on`. To give the boot session the channel — this ends its current Remote-Control conversation — `cc rc restart`. Tokens and owner live in `~/.cc/config` (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_OWNER_ID`); unpair by deleting `SLACK_OWNER_ID` and restarting the unit.
- `cc-notify setup` once → the phone's ntfy app subscribes to the topic, and sessions push to you when they need a decision.

## Rescue
1. Cable laptop↔box, laptop `<laptop-rescue-ip>` no gateway, `ssh <user>@<rescue-ip>`.
2. If that fails: attach monitor + keyboard.
- **Wedged session?** DM the bot — this works with no live Claude session, `cc-slackd` alone: `!restart box` / `!restart <repo>[/<track>]` kills that tmux window and restarts it; `!restart slack` restarts `cc-slackd` itself; last resort `!restart tmux` then `!restart tmux confirm` within 2 min restarts `tmux-main.service`, killing every session on the box.
- **Whole box unresponsive at the OS level?** `!reboot` then `!reboot confirm` within 2 min (a detached `systemctl reboot`): everything returns via systemd + BIOS AC-recovery, the boot notice posts automatically, and the power log labels it `cause=clean-reboot`.
- **Box rebooted by itself?** `cat ~/.cc/state/power-events.log` — cut times from `cc-heartbeat`, each boot line carrying `cause=clean-reboot|power-loss|unknown` read from the previous boot's journal (`cc-heartbeat --dry-run [<last_alive>]` shows the line it would write). `journalctl -b -1 | tail` with no `Shutting down` line = power loss or hard reset, not the OS; SSD attr 235 `POR_Recovery_Count` counts sudden power losses. BIOS AC Recovery = On brings it back when power returns.

## Network
- `/etc/netplan/99-server.yaml` (mode 600): `<iface>` dhcp4 + static `<rescue-ip>/24`; `<wlan-iface>` dhcp4 with APs `<hotspot-ssid>` and `<home-ssid>`; both optional.
- Ethernet MAC (home DHCP reservation): `<mac>`. WiFi MAC: `<wlan-mac>`.
- chrony: NTS TLS can fail on some networks; check `chronyc tracking` after a move.

## Policy
- No host firewall (ufw/nftables); Docker manages only its own container rules.
- sshd: socket-activated (`ssh.socket`), key-only — `PasswordAuthentication no` + `KbdInteractiveAuthentication no` via `/etc/ssh/sshd_config.d/10-hardening.conf` (overrides 50-cloud-init.conf; keep a backup of the original). Tailscale SSH is separate (tailscaled) and unaffected.
- Reboots: the ask-gate stays in `~/.claude/settings.json` — the harness classifier blocks Claude from removing its own gate — and reboots are independently classifier-gated. Verify boot-time WiFi/Tailscale autoconnect and the tmux-main session across one reboot. Unattended-upgrades: security pockets only, no auto-reboot. Sleep/suspend/hibernate targets masked.
- Owner TODO: home-router DHCP reservation for `<mac>`.
