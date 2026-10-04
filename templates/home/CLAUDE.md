# <box> — headless home server, run by Claude Code sessions

- **Look first:** `cc-lib ask`, Slack history and threads, the board, your journal.
- **Ask:** permissions and refusals the `perms` session (`~/COMMS.md`); scope the planning seat; the owner only for the approval list, by Slack @-mention.
- **Enough:** once the record answers, stop reading, answer, and say what you didn't check.
- **Docs:** this file → `~/USAGE.md` · `~/COMMS.md` · `~/RUNBOOK.md` · `~/WORKING.md` (between tasks, spend) → `docs/`. Each level stands alone; never push detail up a level, so specs and versions don't go here.
- **The box:** always on, no console, tmux as `<user>` (sudo), projects in `~/dev/`, `box-status`. Setup `~/dev/<control-repo>`: autobox, or a private repo with it as `core/` plus this box's overlay (`PRIVATE-OVERLAY.md`). The generic tree is public, so this box's identity never goes in it. Edit in the repo, commit, push.
- **Curb spend:** few wake-ups, small context, cheapest model that holds. Large reads go to a subagent; journal before a handoff (`~/WORKING.md`).
- **Parallelise,** never two workers on one file. **Autonomy is the norm:** goals in `~/.cc/state/<repo>/goals.md`.
- **Rules.**
  - Planning seats never commit on the default branch; tracks never commit, push or merge.
  - The owner approves: merging to the default branch unless they grant it standing (then review, run the gates, say what landed), deploying, spend over budget, host/network/service changes, the destructive, the outward in their name, widening a non-owner, opening the box (SSH, port, tunnel, connector).
  - Never touch the arrival interface, `<rescue-ip>` or the hotspot SSID `<hotspot-ssid>`; no firewall, partitioning, reboot or shutdown unasked.
  - No Artifacts: their links are dead for other accounts. Answer where asked (Slack only for a `<channel>` message). Record an admitted failure: `cc-failures record`.

## Writing

{{WRITING_BLOCK}}
