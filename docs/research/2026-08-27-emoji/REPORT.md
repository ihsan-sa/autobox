# emoji-research — report

## Result

| | baseline `b3b3c82` | best `57d3300` |
|---|---|---|
| **score** (wrong_min/day + 0.05 × api/day) | **10512.239** | **15.211** |
| wrong_minutes_per_day | 10243.944 | **0.000** |
| api_calls_per_day | 5365.889 | 304.222 |
| reads_per_day | 5194.333 | 61.778 |
| mutations_per_day | 171.556 | 237.333 |
| mean / p95 fix latency (s) | 7718 / 17220 | 0 / 0 |

`python3 ./cc-slack selfcheck` → `selfcheck: 0 failed` at every kept commit.

The owner's view is now correct at **every** scored tick: all four `cause:` lines are gone. What is left of
the score is pure API volume, and most of that is irreducible (see *Where the remaining 15.2 goes*).

21 experiments logged in `results.tsv` (16 keeps, 5 discards). The search converged well before the
40-experiment budget — the last five attempts bought ≤0.5 each or regressed, so I stopped rather than churn.

## Kept commits

1. `c9d52ad` **unanswered roots count as owed** — `bucket_threads` used to `continue` on `reply_count == 0`,
   so a question nobody had answered yet carried no status at all (the single largest cause, 5816 min/day).
   A root with no replies is now its own "last message", which also skips a `conversations.replies` call.
2. `66a166f` **look past our own nudge posts** — the nudge we post *into* a 🔴 thread became that thread's last
   message and flipped it to 🟡 forever. `bucket_threads` now scans back past any `NUDGE_PREFIX` message.
   (1 above created this; the two only pay off together: 10437 → 5042.)
3. `786c866` **`mark_dirty` fires on our own threaded bot replies** — a session answer arrives as
   `subtype: bot_message`, which `mark_dirty` ignored, so nothing swept until the owner spoke again. −2675.
4. `ac282dc` **schedule the 48h expiry** — the one status change no Slack event announces. `reconcile` now
   records `expire_at` (the earliest `last + 48h`) and `board_cycle` sweeps when it falls due. −1887.
5. `beea52c` **cache each root's last message under `latest_reply`** — the root already tells us whether the
   thread moved, so the replies call is only made when it did. Reads 6710 → 621/day.
6. `a2e0b3a` **instant 🟡 when our session replies** — the mirror of what `mark_owed` already did for 🔴,
   so a reply no longer waits for the debounce. Killed `latency_<2min` and `other_wrong` outright.
7. `e6a28ee` **instant 🔴 on a brand-new root too**, not just on replies in an existing thread.
8. `6991d7a` **one shared history read** — `reconcile` and `bucket_threads` each called
   `conversations.history` separately, so a flaky empty answer (2% in the harness, and real: the retry comment
   in the file is dated) made the two disagree and stranded expired roots. They now share one retried read.
   −23.5, and it was the whole tail of `stale_or_flagged_not_cleared`.
9. `7a117df` **`nudge_cycle` reads the snapshot `reconcile` already computed** instead of re-deriving it every
   15 min. This was the single biggest API consumer. History 406 → 114/day.
10. `d51c614` **feed threaded messages into the last-message cache from their events** — we watched the reply
    happen, so the next sweep needs no read to know what it was. Replies 183 → 115/day.
11. `1517935`, `3adfa69`, `27d2c86` **sweep debounce 45 s → 300 → 1800 → 3600 s** — with the instant flips
    carrying the fast path and `expire_at` carrying expiry, the sweep is only a self-correcting net.
12. `e0180ec` **`thread_status`, a believed-status cache** — `mark_owed` no longer re-reads a root to learn
    what is on it; every sweep re-reads the truth and overwrites the cache, so drift self-corrects. −5.0.
13. `8db2e1b` **one `STALE_AFTER` constant for both the cutoff and the alarm** — they were computed
    separately and disagreed by the timestamp's own fraction, so every expiry landed one tick late.
    This was the last 4.833 wrong-minutes/day; **wrong_minutes went to 0.000**.
14. `9afaca9` **🏁 clears only the status we believe is there** instead of blind-firing both removes.
15. `57d3300` **replies `limit` 20 → 200** — score-neutral, kept as a latent-bug fix: Slack returns replies
    *oldest*-first, so `replies[-1]` off a 20-message page was the 20th-oldest, not the newest, on long threads.

## What did not help

- **Re-arming the dirty flag when `reconcile` hits its mutation cap** (`37f3b56`) — byte-identical score. The
  cap of 10 is never reached; the stranded roots I was chasing were the flaky second history read (8 above).
- **Expiring quiet threads straight from the snapshot, with no channel read** — correct and it did score
  better (14.867), but only 6.9 calls/day: at a 1 h debounce most chats are already dirty when the expiry
  falls due, so it fell back to a full sweep anyway. A second, parallel clearing path for 0.34 is a bad trade.
- **Letting threaded messages skip the dirty flag** — scored 14.717 on the graded config, but
  `--days 5 --chats 5` went from 0.000 to **29.05** wrong minutes/day. Overfit; discarded despite the win.
- **Raising the mutation cap to 50** — no score change *and* the selfcheck asserts the cap of 10 (gate red).
- **`oldest=latest_reply` instead of `limit`** — not tried as a commit: it returns only the newest reply, which
  destroys the look-past-the-nudge scan in 2 above, for zero call saving.

## Where the remaining 15.2 goes

`0.05 × 304.2 calls/day`, and 304 breaks down as:

- **195 status mutations/day** — Slack has no "replace reaction", so every truth flip costs a remove + an add.
  A count of the harness's own state changes puts the floor at ~188/day. This is the bulk of the score
  and it is not compressible without dropping accuracy, which costs 20× more per unit.
- **51 `reactions.add` of 👀/day** — the delivery ack on every routed owner message. It is a different feature,
  not the status mechanism; deleting it would buy 2.56 but is not what was being researched.
- **~45 `conversations.history` + ~14 `conversations.replies`/day** — the hourly self-correcting sweep and its
  expiry alarms. Cutting these further is exactly the change that regressed on `--days 5 --chats 5`.

## Generalisation

Tuning only ever saw `--days 3 --chats 3 --seeds 1,2,3`. On configurations never tuned on:

| config | wrong_min/day | score |
|---|---|---|
| `--days 5 --chats 5 --seeds 7,8` | 0.000 | 25.405 |
| `--days 2 --chats 2 --seeds 11,12,13,14` | 0.000 | 12.894 |
| `--days 7 --chats 2 --seeds 21,22` | 0.000 | 10.925 |
| `--days 10 --chats 3 --seeds 31,32` | 0.000 | 13.595 |

The 10-day run puts ~90 roots in a channel, well past the sweep's 50-root history window, and still scores
zero wrong minutes: the expiry alarm clears a root long before it scrolls out of that window.

## Diff — baseline → best

```diff
diff --git a/cc-slack b/cc-slack
index f5a1c3d..91d15af 100755
--- a/cc-slack
+++ b/cc-slack
@@ -34,6 +34,11 @@ PERM_RE = re.compile(r"^\s*(y|yes|n|no)\s+([a-km-z]{5})\s*$", re.I)
 CHUNK = 3900
 APPROVALS = "approvals"                                        # #approvals is not a session: the owner's :+1: on a bot post there merges the PR
 STATUS_EMOJI = {"🔴": "red_circle", "🟡": "large_yellow_circle"}  # bucket char -> the reaction name reconcile_reactions drives on thread roots
+NUDGE_PREFIX = "🔴 still open after"   # our own nudge posts: never an answer, so bucket_threads looks past them
+STALE_AFTER = 48 * 3600 - 1   # a thread goes quiet-stale 48 h after its last message; the second of grace makes the sweep
+                              # armed for exactly that moment find it stale instead of missing by the timestamp's own fraction
+CONCLUDED = "🏁"   # thread_status marker: the owner called this thread done, so no status reaction belongs on it
+SWEEP_DEBOUNCE = 3600   # s of quiet before the reconcile sweep; the instant 🔴/🟡 flips mean it is only a self-correcting net
 PR_RE = re.compile(r"^\[([a-z0-9_-]+)\] PR #([0-9]+):")
 for _p in glob.glob(f"{HOME}/.cc/slack/venv/lib/python*/site-packages"):   # slack_sdk lives in the venv
     sys.path.append(_p)
@@ -262,6 +267,8 @@ class Daemon:
         self.known_aliases = collections.defaultdict(set)   # target -> {alias, ...} ever subscribed (daemon lifetime)
         self.nudged = set()                                 # (chat, thread_ts) already nudged this daemon's lifetime
         self.board = {}                                     # chat -> {"dirty_at": float|None}; dirty tracker for reconcile_reactions
+        self.thread_last = collections.OrderedDict()        # (chat, root_ts) -> (latest_reply, last msg); skips conversations.replies when unchanged
+        self.thread_status = collections.OrderedDict()      # (chat, root_ts) -> status reaction we believe is there (CONCLUDED = 🏁)
         self.legacy_cleaned = set()                         # chats where the old pinned 📋 board message has been deleted (once)
         self.edit_seen = collections.OrderedDict()          # (chat, ts, subtype) already handled — dedupes duplicate edit/delete events
         self.warned, self.told = set(), {}
@@ -494,6 +501,8 @@ class Daemon:
             if chat0 and ts0:
                 target0 = self.route(chat0, ev.get("channel_type"))
                 text0 = self.clean(ev.get("text") or "")
+                if target0 and ev.get("thread_ts") and not (ev.get("text") or "").startswith(NUDGE_PREFIX):
+                    self.mark_owed(chat0, ev["thread_ts"], "large_yellow_circle")   # our answer lands: 🟡 now, not on the sweep
                 if target0 and at_token(text0, self.bot_user):
                     thread0 = ev.get("thread_ts") or ts0
                     old0 = self.thread_owner.get((chat0, thread0))
@@ -538,7 +547,7 @@ class Daemon:
         if user != owner:
             log(f"drop: sender {user} is not the owner ({chat})")
             return
-        if target and thread != ts:   # owner reply in an existing thread: flip its root 🔴 now, don't wait for the sweep
+        if target:   # owner speaks (new thread or a reply in one): flip that root 🔴 now, don't wait for the sweep
             self.mark_owed(chat, thread)
         text = self.clean(text)
         if text.startswith("!"):   # intercepted before any routing/delivery — top-level or threaded, any channel
@@ -670,11 +679,13 @@ class Daemon:
                 and chat and ts and self.route(chat, None):
             # owner's 🏁 = concluded: strip the bot's status reactions from that message NOW (the sweep would only get there later)
             tok = self.cfg.get("SLACK_BOT_TOKEN")
-            for name in ("red_circle", "large_yellow_circle"):
+            known = self.thread_status.get((chat, ts), "?")   # "?" = we have never looked, so try both
+            for name in (list(STATUS_EMOJI.values()) if known == "?" else [known] if known in STATUS_EMOJI.values() else []):
                 try:
                     api("reactions.remove", tok, channel=chat, timestamp=ts, name=name)
                 except Exception:
                     pass   # that status emoji was not on the message — fine
+            self.note_status(chat, ts, CONCLUDED)
             return None
         if ev.get("reaction") not in ("+1", "thumbsup") or ev.get("user") != self.cfg.get("SLACK_OWNER_ID") \
                 or item.get("type") != "message" or not (chat and ts) or self.chan_name(chat) != APPROVALS:
@@ -799,29 +810,48 @@ class Daemon:
                        "the boot notice posts here automatically and the power log labels it clean-reboot; "
                        "confirm with `!reboot confirm` within 120 s", thread)
 
-    def bucket_threads(self, chat):
-        """Mechanical bucket of chat's threads active in the last 48h -> [(bucket, root, last)]; no LLM, no stored state, recomputed per call.
-        Hidden ONLY for 🏁 on the root or no activity in 48h — a ✅ (this thread's "answered" marker) elsewhere never hides it."""
-        cutoff, tok = time.time() - 48 * 3600, self.cfg.get("SLACK_BOT_TOKEN")
-        roots = []
-        for attempt in (1, 2):   # Slack intermittently serves ok:true with an EMPTY history for an active channel (seen live
-            roots = api("conversations.history", tok, channel=chat, limit="50")["messages"]   # 2026-08-27; caused ghost "all quiet")
+    def chat_roots(self, chat):
+        """chat's top-level messages, newest-first. Slack intermittently serves ok:true with an EMPTY history for an active
+        channel (seen live 2026-08-27; caused ghost "all quiet"), so an empty answer is retried once before we believe it."""
+        tok = self.cfg.get("SLACK_BOT_TOKEN")
+        for attempt in (1, 2):
+            roots = api("conversations.history", tok, channel=chat, limit="50")["messages"]
             if roots:
-                break
+                return roots
             log(f"threads: {chat}: history returned empty (attempt {attempt}/2)")
             time.sleep(2)
+        return []
+
+    def bucket_threads(self, chat, roots=None):
+        """Mechanical bucket of chat's threads active in the last 48h -> [(bucket, root, last)]; no LLM, no stored state, recomputed per call.
+        Hidden ONLY for 🏁 on the root or no activity in 48h — a ✅ (this thread's "answered" marker) elsewhere never hides it.
+        `roots` lets a caller that already read the history pass it in, so the two views can never disagree."""
+        cutoff, tok = time.time() - STALE_AFTER, self.cfg.get("SLACK_BOT_TOKEN")
+        if roots is None:
+            roots = self.chat_roots(chat)
         out = []
         for root in roots:
-            if not root.get("reply_count"):
-                continue
             if {"🏁", "checkered_flag"} & {r["name"] for r in root.get("reactions", [])}:
                 continue
-            try:
-                replies = api("conversations.replies", tok, channel=chat, ts=root["ts"], limit="20")["messages"]
-            except Exception as e:
-                log(f"threads: {chat} {root['ts']}: replies failed: {e!r}")
-                continue
-            last = replies[-1] if replies else root
+            if root.get("reply_count"):
+                key, latest = (chat, root["ts"]), root.get("latest_reply")
+                cached = self.thread_last.get(key)
+                if latest and cached and cached[0] == latest:
+                    last = cached[1]        # nothing new since the last read — the replies call would tell us nothing
+                else:
+                    try:
+                        replies = api("conversations.replies", tok, channel=chat, ts=root["ts"], limit="200")["messages"]
+                    except Exception as e:
+                        log(f"threads: {chat} {root['ts']}: replies failed: {e!r}")
+                        continue
+                    # our own nudge is not an answer — look past it, or it would flip the thread to "with the session"
+                    last = next((m for m in reversed(replies) if not (m.get("text") or "").startswith(NUDGE_PREFIX)), root)
+                    if latest:
+                        self.thread_last[key] = (latest, last)
+                        while len(self.thread_last) > 500:
+                            self.thread_last.popitem(last=False)
+            else:
+                last = root   # nobody has answered yet: the root itself is the last word, so it reads as owed
             if float(last["ts"]) < cutoff:
                 continue
             # our replies arrive with bot_id and NO user field (bot-authored) — they must read as "with you", not "owed"
@@ -849,7 +879,8 @@ class Daemon:
             if sent >= 3:
                 break
             try:
-                for bucket, root, last in self.bucket_threads(chat):
+                st = self.board.get(chat) or {}   # reconcile's snapshot; with no event since, a re-read would say the same
+                for bucket, root, last in (st["buckets"] if "buckets" in st else self.bucket_threads(chat)):
                     if sent >= 3:
                         break
                     key = (chat, root["ts"])
@@ -857,7 +888,7 @@ class Daemon:
                     if bucket != "🔴" or age_min < 30 or key in self.nudged:
                         continue
                     age = f"{int(age_min // 60)}h{int(age_min % 60)}m" if age_min >= 60 else f"{int(age_min)}m"
-                    self.say(chat, f"🔴 still open after {age} — say `@{self.route(chat, 'channel')}` here if you want it picked back up", root["ts"])
+                    self.say(chat, f"{NUDGE_PREFIX} {age} — say `@{self.route(chat, 'channel')}` here if you want it picked back up", root["ts"])
                     self.nudged.add(key); sent += 1
             except Exception as e:
                 log(f"nudge: {chat}: {e!r}")
@@ -867,15 +898,40 @@ class Daemon:
         et = ev.get("type")
         if et == "message" and ev.get("subtype") in (None, "file_share", "thread_broadcast", "message_deleted", "message_changed"):
             chat, ctype = ev.get("channel"), ev.get("channel_type")
+        elif et == "message" and ev.get("subtype") == "bot_message" and ev.get("thread_ts"):
+            chat, ctype = ev.get("channel"), ev.get("channel_type")   # our session's own threaded reply flips that root to 🟡
         elif et == "reaction_added":
             chat, ctype = (ev.get("item") or {}).get("channel"), None
         else:
             return
         if chat and self.route(chat, ctype):
+            self.note_last(ev)
             st = self.board.setdefault(chat, {"dirty_at": None})
             if st["dirty_at"] is None:
                 st["dirty_at"] = time.time()
 
+    def note_last(self, ev):
+        """Remember a threaded message as its root's newest one, so bucket_threads' latest_reply cache hits and the
+        conversations.replies read is never needed for a thread we watched happen."""
+        chat, ts, thread = ev.get("channel"), ev.get("ts"), ev.get("thread_ts")
+        if ev.get("subtype") not in (None, "file_share", "thread_broadcast", "bot_message") or not (chat and ts):
+            return
+        if not thread:
+            return self.note_status(chat, ts, None)   # a root we just watched appear: nothing can be on it yet
+        if (ev.get("text") or "").startswith(NUDGE_PREFIX):
+            return   # our own nudge is not an answer — let the next read decide what the last real message was
+        self.thread_last[(chat, thread)] = (ts, {"ts": ts, "user": ev.get("user"), "bot_id": ev.get("bot_id"),
+                                                 "text": ev.get("text") or ""})
+        while len(self.thread_last) > 500:
+            self.thread_last.popitem(last=False)
+
+    def note_status(self, chat, ts, status):
+        """Remember the status reaction we believe sits on a thread root (None = bare, CONCLUDED = 🏁) so mark_owed can
+        flip it without a read. Every sweep re-reads the real reactions and overwrites this, so drift self-corrects."""
+        self.thread_status[(chat, ts)] = status
+        while len(self.thread_status) > 500:
+            self.thread_status.popitem(last=False)
+
     def legacy_cleanup(self, chat, roots):
         """One-time: unpin + delete the old pinned 📋 live-threads board message from the previous design, if present in roots."""
         ts = next((m["ts"] for m in roots if m.get("user") == self.bot_user
@@ -897,45 +953,51 @@ class Daemon:
         return next((r["name"] for r in reactions
                     if r["name"] in STATUS_EMOJI.values() and self.bot_user in r.get("users", [])), None)
 
-    def mark_owed(self, chat, thread):
-        """Owner reply in an existing thread: flip its root to 🔴 right away, without waiting for the debounced sweep.
-        ≤1 read + ≤1 reaction swap; zero mutation calls once the root is already 🔴 or carries 🏁."""
+    def mark_owed(self, chat, thread, name="red_circle"):
+        """Reply in an existing thread: flip its root to `name` (🔴 owner's, 🟡 the session's) right away, without waiting
+        for the debounced sweep. ≤1 read + ≤1 reaction swap; zero mutation calls once it already reads that way or carries 🏁."""
         tok = self.cfg.get("SLACK_BOT_TOKEN")
-        try:
-            reactions = api("conversations.replies", tok, channel=chat, ts=thread, limit="1")["messages"][0].get("reactions", [])
-        except Exception as e:
-            log(f"reactions: instant {chat} {thread}: {e!r}"); return
-        if {"🏁", "checkered_flag"} & {r["name"] for r in reactions}:
-            return
-        current = self.bot_status(reactions)
-        if current == "red_circle":
+        if (chat, thread) in self.thread_status:
+            current = self.thread_status[(chat, thread)]
+        else:
+            try:
+                reactions = api("conversations.replies", tok, channel=chat, ts=thread, limit="1")["messages"][0].get("reactions", [])
+            except Exception as e:
+                log(f"reactions: instant {chat} {thread}: {e!r}"); return
+            current = CONCLUDED if {"🏁", "checkered_flag"} & {r["name"] for r in reactions} else self.bot_status(reactions)
+        if current in (CONCLUDED, name):
             return
         try:
             if current:
                 api("reactions.remove", tok, channel=chat, timestamp=thread, name=current)
-            api("reactions.add", tok, channel=chat, timestamp=thread, name="red_circle")
+            api("reactions.add", tok, channel=chat, timestamp=thread, name=name)
         except Exception as e:
-            log(f"reactions: instant {chat} {thread}: {e!r}")
+            log(f"reactions: instant {chat} {thread}: {e!r}"); return
+        self.note_status(chat, thread, name)
 
     def reconcile_reactions(self, chat, cap=10):
         """Drive each thread root's 🔴/🟡 status reaction to match its bucket; derives current state from conversations.history's
         reactions each cycle (no persistent state — self-corrects across restarts). ≤cap mutations per call (10 on the sweep; !threads passes 50)."""
         tok = self.cfg.get("SLACK_BOT_TOKEN")
         try:
-            roots = api("conversations.history", tok, channel=chat, limit="50")["messages"]
-            desired = {root["ts"]: STATUS_EMOJI[b] for b, root, last in self.bucket_threads(chat)}
+            roots = self.chat_roots(chat)
+            buckets = self.bucket_threads(chat, roots)
         except Exception as e:
             log(f"reactions: {chat}: {e!r}"); return
+        desired = {root["ts"]: STATUS_EMOJI[b] for b, root, last in buckets}
+        st = self.board.setdefault(chat, {"dirty_at": None})
+        st["buckets"] = buckets   # nudge_cycle reads this instead of re-deriving it; every event refreshes it
+        # the 48h cutoff is the one status change no Slack event announces — remember when the next one falls due
+        st["expire_at"] = min((float(last["ts"]) + STALE_AFTER for b, root, last in buckets), default=None)
         if chat not in self.legacy_cleaned:
             self.legacy_cleaned.add(chat)
             self.legacy_cleanup(chat, roots)
         mutations = 0
         for root in roots:
-            if not root.get("reply_count"):
-                continue
             ts = root["ts"]
             current = self.bot_status(root.get("reactions", []))
             want = desired.get(ts)
+            self.note_status(chat, ts, CONCLUDED if {"🏁", "checkered_flag"} & {r["name"] for r in root.get("reactions", [])} else current)
             if current == want:
                 continue
             need = (1 if current else 0) + (1 if want else 0)
@@ -947,6 +1009,8 @@ class Daemon:
                     api("reactions.remove", tok, channel=chat, timestamp=ts, name=current)
                 if want:
                     api("reactions.add", tok, channel=chat, timestamp=ts, name=want)
+                if self.thread_status.get((chat, ts)) != CONCLUDED:
+                    self.note_status(chat, ts, want)
             except Exception as e:
                 log(f"reactions: {chat} {ts}: {e!r}")
             mutations += need
@@ -954,7 +1018,8 @@ class Daemon:
     def board_cycle(self):
         now = time.time()
         for chat, st in list(self.board.items()):
-            if st["dirty_at"] is not None and now - st["dirty_at"] >= 45:
+            expired = st.get("expire_at") is not None and now >= st["expire_at"]
+            if expired or (st["dirty_at"] is not None and now - st["dirty_at"] >= SWEEP_DEBOUNCE):
                 st["dirty_at"] = None
                 self.reconcile_reactions(chat)
 
```
