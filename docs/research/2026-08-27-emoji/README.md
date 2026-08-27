# Thread-status reactions — simulation + autoresearch (2026-08-27)

Shallow first: a 2-second simulator of Slack + owner/session activity scored `cc-slack`'s 🔴/🟡 mechanism; an autonomous loop (Karpathy-autoresearch style, Opus in a `ccbox` sandbox, bypass mode, 21 experiments, $6.45) took the score from **10512 → 15.2**: wrong-state minutes/day **10244 → 0**, Slack API calls/day **5366 → 304**. The kept mechanics were ported into `cc-slack` (PR #15); the semantics were then replaced by status v2, which the same harness scores (`tests/slack_sim.py`). Files here: `REPORT.md` (the loop's own report), `results.tsv` (one row per experiment), `kept.diff` (best version vs baseline).

## Harness — `tests/slack_sim.py` (read-only)
- Fake Slack with the semantics that matter: `conversations.history` = top-level only, newest-first, `limit`; `conversations.replies` = root+replies **oldest**-first with `limit`/`oldest`/`cursor`/`has_more`; reactions carry `users`; bot posts carry `bot_id` and no `user`; 2 % empty-history flake.
- Seeded scenario, 3 chats × 3 days × 3 seeds: owner asks, session answers (15–600 s), follow-ups, session questions, 🔐 prompts, 🏁, 8 % never answered.
- Oracle = what the owner should see on each root each 30 s tick. Metrics: `wrong_minutes_per_day` by cause, `api_calls_per_day` by method, fix latency. `score = wrong_min + 0.05 × calls`.
- Run: `python3 tests/slack_sim.py bin/cc-slack [--days 3 --chats 3 --seeds 1,2,3 --flake 0.02]`. The status emoji set is read from the module (`STATUS_EMOJI`), so it scores any design.

## Loop rules (program.md in the sandbox)
One idea → one commit → one run → one `results.tsv` row; keep only a strictly lower score with `cc-slack selfcheck` green; equal-or-worse → `git reset --hard`; simplicity criterion; never edit the harness; stop when ideas dry up (it stopped at 21 of 40).

## What the loop found (kept, in order)
| # | change | effect |
|---|---|---|
| 1 | unanswered roots (`reply_count==0`) get a status | −4.3k wrong-min/day (largest single cause) |
| 2 | look past our own nudge posts when picking `last` | the nudge itself had been flipping 🔴→🟡 |
| 3 | `mark_dirty` on our own `bot_message` replies | a session answer never triggered a sweep |
| 4 | self-scheduled 48 h expiry (`expire_at`) | the one change no Slack event announces |
| 5 | per-root last-message cache keyed on `latest_reply` | reads 6710 → 621/day |
| 6–7 | event-driven instant flips on our reply / new owner root | latency → 0 |
| 8 | one shared, retried history read for reconcile + buckets | flaky empty reads stranded expired roots |
| 9 | nudge sweep reuses the reconcile snapshot | history 406 → 114/day |
| 10 | threaded events feed the cache | replies 183 → 115/day |
| 11 | sweep debounce 45 s → 3600 s (instant flips carry the fast path) | sweep = self-correcting net only |
| 12 | believed-status cache (`thread_status`) | no read before a flip; sweeps overwrite it |
| 13 | one `STALE_AFTER` for cutoff and alarm | last 4.8 wrong-min/day → 0 |
| 14–15 | 🏁 removes only the believed status; replies `limit` 200 | latent long-thread bug |

Discarded: re-arming dirty on the mutation cap (no effect), expiry without a read (+0.3 for a second path), skipping dirty on threaded messages (overfit: 0 → 29 wrong-min on 5 chats × 5 days), mutation cap 50 (selfcheck asserts 10).

Remaining 304 calls/day: 195 status mutations (Slack has no "replace reaction": every truth flip = remove + add — the floor), 51 👀 acks (a different feature), ~60 hourly sweep reads.

## Status v2 (owner-perspective study)
12 Opus judges (6 designs × 2 personas) + a blind emoji-meaning probe, judging as the owner on a phone across 6 scenarios. Consensus: the status must be keyed to **who must act**, not who spoke last (a 🔐 prompt is a bot message, so v1 read it as "settled"); colour-only 🔴/🟡 dots fail on phones, dark mode and colour-blindness; ✅-as-ack collides with ✅-as-done; the ⏳ starting notice is the best-liked element. Result (in `cc-slack`): **❓ = needs you** (session question, 🔐 prompt, BLOCKED, or no answer for 30 min), **nothing** = in the session's hands or settled, **your 🏁** = closed, **👀** = received (removed on reply, no ✅). Nudges only on ❓ threads and carry the ask. Under the v2 oracle: score 56190 (main before) → 39.5 (wrong 8.6 min/day, 619 calls/day).
