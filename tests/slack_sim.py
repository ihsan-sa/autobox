#!/usr/bin/env python3
"""slack_sim.py — READ-ONLY harness (status v3 oracle: ❓ needs you · 🔴 the session owes you · 🟠 handled): simulates Slack +
owner/session activity against cc-slack's Daemon and scores the thread-status reaction mechanism, the 🏁 flag file, the
delivery of the owner's reactions to sessions, and sessions that answer with a reaction instead of words.
Usage: python3 slack_sim.py [path/to/cc-slack] [--days 3] [--chats 3] [--seeds 1,2,3] [-v]
Prints one summary line per metric; `score:` is the single number to minimise (lower = better)."""
import sys, os, json, random, collections, importlib.machinery as M, tempfile
os.environ["CC_SLACK_DIR"] = tempfile.mkdtemp(prefix="slack-sim-")   # the daemon module persists flags/outbox under CC_SLACK_DIR: never the live ~/.cc/slack

argv = sys.argv[1:]
path = argv.pop(0) if argv and not argv[0].startswith("-") else os.path.expanduser("~/bin/cc-slack")
def opt(name, default):
    if name in argv:
        i = argv.index(name); v = argv[i + 1]; del argv[i:i + 2]; return v
    return default
DAYS = float(opt("--days", "3")); CHATS = int(opt("--chats", "3")); SEEDS = [int(s) for s in opt("--seeds", "1,2,3").split(",")]
VERBOSE = "-v" in argv; FLAKE = float(opt("--flake", "0.02"))
TICK = 30                     # daemon loop_tick cadence (s)
OWNER, BOT, BOTID = "UOWNER", "UBOT", "BBOT"
STATUS = {}   # filled from the module under test (cs.STATUS_EMOJI: char -> reaction name)

class FakeTime:               # stands in for the `time` module inside cc-slack
    def __init__(self, t0): self.now = t0
    def time(self): return self.now
    def sleep(self, s): pass
    def strftime(self, fmt, t=None): return "T"
    def gmtime(self, *a): return None
    def localtime(self, *a): return None
    def monotonic(self): return self.now

class FakeSlack:
    """Slack semantics that matter: history = top-level only, newest-first, ≤limit; replies = root+replies OLDEST-first
    (limit, oldest/inclusive, cursor, has_more); reactions with users; bot posts carry bot_id and no user."""
    def __init__(self, clock, rng, flake=0.02):
        self.clock, self.rng, self.flake = clock, rng, flake
        self.roots = collections.defaultdict(list)     # chat -> [root msgs] (append order = time order)
        self.replies = collections.defaultdict(list)   # (chat, root_ts) -> [reply msgs]
        self.calls = collections.Counter(); self.events = []   # events the daemon would receive from Socket Mode
        self.n = 0
    def ts(self):
        self.n += 1; return f"{self.clock.now:.3f}{self.n:03d}"
    def _msg(self, chat, text, user=None, bot=False, thread=None):
        m = {"ts": self.ts(), "text": text, "reactions": []}
        if bot: m["bot_id"] = BOTID; m["subtype"] = "bot_message"
        else: m["user"] = user
        if thread:
            m["thread_ts"] = thread; self.replies[(chat, thread)].append(m)
            root = next(r for r in self.roots[chat] if r["ts"] == thread)
            root["reply_count"] = root.get("reply_count", 0) + 1; root["latest_reply"] = m["ts"]
        else:
            self.roots[chat].append(m)
        return m
    def post(self, chat, text, user=None, bot=False, thread=None):   # a message arriving in Slack (+ the Socket Mode event)
        m = self._msg(chat, text, user, bot, thread)
        ev = {"type": "message", "channel": chat, "ts": m["ts"], "text": text, "channel_type": "channel"}
        if thread: ev["thread_ts"] = thread
        if bot: ev.update({"subtype": "bot_message", "bot_id": BOTID})
        else: ev["user"] = user
        self.events.append(ev); return m
    def find(self, chat, ts):
        for r in self.roots[chat]:
            if r["ts"] == ts: return r
        for k, v in self.replies.items():
            if k[0] == chat:
                for m in v:
                    if m["ts"] == ts: return m
        raise RuntimeError("message_not_found")
    def api(self, method, token, **p):
        self.calls[method] += 1
        if method == "conversations.history":
            if self.rng.random() < self.flake: return {"ok": True, "messages": []}
            lim = min(int(p.get("limit", 100)), 1000)
            msgs = list(reversed(self.roots[p["channel"]]))
            inc = str(p.get("inclusive", "false")).lower() == "true"
            if p.get("latest"):   # Slack semantics: newest first, bounded by latest/oldest (reacted_message anchors on these)
                l = float(p["latest"]); msgs = [m for m in msgs if (float(m["ts"]) <= l if inc else float(m["ts"]) < l)]
            if p.get("oldest"):
                o = float(p["oldest"]); msgs = [m for m in msgs if (float(m["ts"]) >= o if inc else float(m["ts"]) > o)]
            return {"ok": True, "messages": msgs[:lim]}
        if method == "conversations.replies":
            chat, ts = p["channel"], p["ts"]; root = self.find(chat, ts)
            msgs = [root] + self.replies[(chat, ts)]
            if p.get("oldest"):
                o = float(p["oldest"]); inc = str(p.get("inclusive", "false")).lower() == "true"
                msgs = [m for m in msgs if (float(m["ts"]) >= o if inc else float(m["ts"]) > o)]
            if p.get("latest"):
                l = float(p["latest"]); inc = str(p.get("inclusive", "false")).lower() == "true"
                msgs = [m for m in msgs if (float(m["ts"]) <= l if inc else float(m["ts"]) < l)]
            start = int(p.get("cursor") or 0); lim = int(p.get("limit", 1000))
            page = msgs[start:start + lim]; more = start + lim < len(msgs)
            out = {"ok": True, "messages": page, "has_more": more}
            if more: out["response_metadata"] = {"next_cursor": str(start + lim)}
            return out
        if method in ("reactions.add", "reactions.remove"):
            m = self.find(p["channel"], p["timestamp"]); name = p["name"]
            r = next((x for x in m["reactions"] if x["name"] == name), None)
            if method == "reactions.add":
                if r and BOT in r["users"]: raise RuntimeError("reactions.add: already_reacted")
                if r: r["users"].append(BOT)
                else: m["reactions"].append({"name": name, "users": [BOT], "count": 1})
            else:
                if not r or BOT not in r["users"]: raise RuntimeError("reactions.remove: no_reaction")
                r["users"].remove(BOT)
                if not r["users"]: m["reactions"].remove(r)
            return {"ok": True}
        if method == "chat.postMessage":
            m = self.post(p["channel"], p.get("text", ""), bot=True, thread=p.get("thread_ts") or None)
            m["username"] = p.get("username"); return {"ok": True, "ts": m["ts"]}
        if method in ("pins.remove", "chat.delete", "users.info", "conversations.info"):
            return {"ok": True, "user": {"real_name": "x"}, "channel": {"name": "x"}}
        raise RuntimeError(f"{method}: unsupported_in_sim")
    def owner_react(self, chat, ts, name, remove=False):
        m = self.find(chat, ts)
        r = next((x for x in m["reactions"] if x["name"] == name), None)
        if remove:
            if r and OWNER in r["users"]:
                r["users"].remove(OWNER)
                if not r["users"]: m["reactions"].remove(r)
        elif r: r["users"].append(OWNER)
        else: m["reactions"].append({"name": name, "users": [OWNER], "count": 1})
        self.events.append({"type": "reaction_removed" if remove else "reaction_added", "user": OWNER, "reaction": name,
                            "event_ts": f"{self.clock.now:.3f}", "item": {"type": "message", "channel": chat, "ts": ts}})
    def session_react(self, chat, ts, name):
        """A session answering the owner with the `react` MCP tool: our bot user reacts (and takes its own 👀 off), so the
        daemon hears a reaction_added of its OWN — which under addendum 2 settles that thread."""
        m = self.find(chat, ts)
        r = next((x for x in m["reactions"] if x["name"] == name), None)
        if r:
            if BOT not in r["users"]: r["users"].append(BOT)
        else: m["reactions"].append({"name": name, "users": [BOT], "count": 1})
        eyes = next((x for x in m["reactions"] if x["name"] == "eyes" and BOT in x["users"]), None)
        if eyes:
            eyes["users"].remove(BOT)
            if not eyes["users"]: m["reactions"].remove(eyes)
        self.calls["session:react"] += 2                 # the session's own two calls, not the daemon's cost
        self.events.append({"type": "reaction_added", "user": BOT, "reaction": name,
                            "event_ts": f"{self.clock.now:.3f}", "item": {"type": "message", "channel": chat, "ts": ts}})

    def bot_status(self, root):
        return next((STATUS[r["name"]] for r in root["reactions"] if r["name"] in STATUS and BOT in r["users"]), None)

def scenario(rng, chats, days, t0):
    """Owner/session activity as a time-ordered list of (t, kind, args). Threads: owner asks → session replies (usually,
    in words or — addendum 2 — with a 👍/✅ reaction on the owner's own message) →
    sometimes owner follows up → sometimes 👍 → sometimes 🏁, and a flagged thread is sometimes un-flagged or re-opened by
    a new reply (v3: the stale 🏁 stays visible and must be ignored). Nudges/marks come from the daemon itself."""
    ev = []; tid = 0
    for chat in chats:
        t = t0
        while t < t0 + days * 86400:
            hour = (t / 3600) % 24
            gap = rng.expovariate(1 / (3600 * (1.2 if 8 <= hour <= 23 else 8)))
            t += gap
            if t >= t0 + days * 86400: break
            tid += 1
            ev.append((t, "ask", {"chat": chat, "tid": tid, "text": f"question {tid}"}))
            cur = t; owner_last = True
            if rng.random() < 0.08:                          # session never answers → stays owed for 48 h (nudge material)
                ev.sort(key=lambda e: e[0]); continue
            for hop in range(rng.choice([1, 1, 2, 2, 3, 5])):
                cur += rng.uniform(15, 600); r = rng.random()
                if r < 0.15:   # session asks the owner something → needs-you until the owner answers
                    ev.append((cur, "askback", {"chat": chat, "tid": tid, "text": f"answer {tid}.{hop} — which env var should I use?"})); owner_last = False
                    cur += rng.uniform(120, 8 * 3600); ev.append((cur, "followup", {"chat": chat, "tid": tid, "text": f"use FOO {tid}.{hop}"})); owner_last = True
                    cur += rng.uniform(15, 300); ev.append((cur, "reply", {"chat": chat, "tid": tid, "text": f"done {tid}.{hop}"})); owner_last = False
                elif r < 0.22:   # permission prompt (posted by the daemon on the session's behalf) → needs-you until yes/no
                    ev.append((cur, "perm", {"chat": chat, "tid": tid, "text": "🔐 `repo` wants to run *Bash*: gh pr merge\nReply `yes abcde` or `no abcde`"})); owner_last = False
                    cur += rng.uniform(60, 4 * 3600); ev.append((cur, "followup", {"chat": chat, "tid": tid, "text": "yes abcde"})); owner_last = True
                    cur += rng.uniform(15, 120); ev.append((cur, "reply", {"chat": chat, "tid": tid, "text": f"merged {tid}.{hop}"})); owner_last = False
                elif r < 0.32:   # no text needed: the session answers with a 👍/✅ on the owner's message (addendum 2)
                    ev.append((cur, "react_answer", {"chat": chat, "tid": tid, "emoji": rng.choice(["+1", "white_check_mark"])})); owner_last = False
                else:
                    ev.append((cur, "reply", {"chat": chat, "tid": tid, "text": f"answer {tid}.{hop}"})); owner_last = False
                if rng.random() < 0.5:                      # owner follows up → the session answers again next hop
                    cur += rng.uniform(60, 6 * 3600); ev.append((cur, "followup", {"chat": chat, "tid": tid, "text": f"followup {tid}.{hop}"})); owner_last = True
                else:
                    break
            if owner_last:                                  # a trailing follow-up always gets its answer
                cur += rng.uniform(15, 600); ev.append((cur, "reply", {"chat": chat, "tid": tid, "text": f"answer {tid}.final"})); owner_last = False
            if not owner_last and rng.random() < 0.25:      # the owner's 👍 on the last answer: confirmation, not a status change
                cur += rng.uniform(30, 3600); ev.append((cur, "praise", {"chat": chat, "tid": tid, "emoji": "+1"}))
            if not owner_last and rng.random() < 0.35:
                cur += rng.uniform(600, 86400); ev.append((cur, "flag", {"chat": chat, "tid": tid}))
                r2 = rng.random()
                if r2 < 0.3:                                # taken back: every mark must come back too
                    cur += rng.uniform(300, 7200); ev.append((cur, "unflag", {"chat": chat, "tid": tid}))
                elif r2 < 0.6:                              # a new reply re-opens a flagged thread (the 🏁 reaction stays, ignored)
                    cur += rng.uniform(300, 7200)
                    ev.append((cur, "askback", {"chat": chat, "tid": tid, "text": f"one more thing {tid} — should I ship it?"}))
                    cur += rng.uniform(300, 7200); ev.append((cur, "followup", {"chat": chat, "tid": tid, "text": f"yes, ship {tid}"}))
                    cur += rng.uniform(15, 600); ev.append((cur, "reply", {"chat": chat, "tid": tid, "text": f"shipped {tid}"}))
    ev.sort(key=lambda e: e[0]); return ev

def run(seed, cs_path):
    rng = random.Random(seed); t0 = 1_800_000_000.0
    clock = FakeTime(t0); slack = FakeSlack(clock, random.Random(seed + 1000), flake=FLAKE)
    cs = M.SourceFileLoader(f"cs{seed}", cs_path).load_module()
    STATUS.clear(); STATUS.update({v: k for k, v in cs.STATUS_EMOJI.items()})
    cs.time = clock; cs.api = slack.api; cs.log = (print if VERBOSE else (lambda *a, **k: None))
    cs.outbox = lambda *a, **k: None
    cs.load_flags = lambda: {}; cs.save_flags = lambda flags: None   # READ-ONLY harness: never touch ~/.cc/slack/flags.json
    d = cs.Daemon(use_slack=False)
    d.cfg = {"SLACK_OWNER_ID": OWNER, "SLACK_BOT_TOKEN": "xoxb-fake"}; d.bot_user = BOT; d.bot_id = BOTID
    chats = [f"C{i}" for i in range(CHATS)]
    d.route = lambda chat, ctype=None: f"repo{chat[1:]}" if chat in chats else None
    d.chan_name = lambda c: f"repo{c[1:]}"; d.user_name = lambda u: u
    delivered = []
    d.deliver = lambda target, payload, **k: delivered.append(payload) or "delivered"
    for c in chats:                                  # one live session per chat: reactions are delivered only to those
        d.subs[f"repo{c[1:]}"] = [cs.Conn(None, f"repo{c[1:]}", {"alias": None})]
    d.command = lambda *a, **k: None
    d.legacy_cleanup = lambda *a, **k: None
    events = scenario(rng, chats, DAYS, t0 + 60)
    roots = {}                      # tid -> (chat, ts)
    ours = {}                       # tid -> ts of the session's newest message (what the owner reacts to)
    reacted = []                    # (tid, ts) the owner reacted to: each must reach the session
    truth_last = {}                 # tid -> ["owner"|"session"|"needs_owner", t, flag_t|None]  (t = the last MESSAGE's time)
    truth_touch = {}                # tid -> when the truth last changed (a reaction answer changes it without a message)
    owner_msg = {}                  # tid -> ts of the owner's newest message (what a session reacts to)
    wrong_s = 0.0; lat = []; pending = {}   # tid -> (truth_changed_at)  for latency
    cause = collections.Counter(); nudged_roots = set()
    n = 0; ei = 0; end = t0 + DAYS * 86400 + 3600
    def feed():
        while slack.events:
            d.on_event(slack.events.pop(0))
    while clock.now < end:
        clock.now += TICK; n += 1
        while ei < len(events) and events[ei][0] <= clock.now:
            t, kind, a = events[ei]; ei += 1
            if kind == "ask":
                m = slack.post(a["chat"], a["text"], user=OWNER); roots[a["tid"]] = (a["chat"], m["ts"]); truth_last[a["tid"]] = ["owner", clock.now, None]
                owner_msg[a["tid"]] = m["ts"]
            elif kind == "reply":
                chat, rts = roots[a["tid"]]
                slack.calls["session:react"] += 2   # session-side 👀→✅ swap on the owner's message: constant, not the daemon's doing
                ours[a["tid"]] = slack.post(chat, a["text"], bot=True, thread=rts)["ts"]; truth_last[a["tid"]][0:2] = ["session", clock.now]
            elif kind in ("askback", "perm"):
                chat, rts = roots[a["tid"]]
                ours[a["tid"]] = slack.post(chat, a["text"], bot=True, thread=rts)["ts"]; truth_last[a["tid"]][0:2] = ["needs_owner", clock.now]
            elif kind == "followup":
                chat, rts = roots[a["tid"]]
                owner_msg[a["tid"]] = slack.post(chat, a["text"], user=OWNER, thread=rts)["ts"]; truth_last[a["tid"]][0:2] = ["owner", clock.now]
            elif kind == "react_answer":                    # the session answers with an emoji: no message, but the thread is handled
                chat, rts = roots[a["tid"]]; slack.session_react(chat, owner_msg[a["tid"]], a["emoji"])
                # a ✅ from the session on the ROOT means "fully done" (owner rule 20:1x); any other reaction = handled
                truth_last[a["tid"]][0] = "done" if (a["emoji"] == "white_check_mark" and owner_msg[a["tid"]] == rts) else "session"
            elif kind == "flag":                            # a 🏁 anywhere in the thread: here on the root
                chat, rts = roots[a["tid"]]; slack.owner_react(chat, rts, "checkered_flag"); truth_last[a["tid"]][2] = clock.now
            elif kind == "unflag":
                chat, rts = roots[a["tid"]]; slack.owner_react(chat, rts, "checkered_flag", remove=True); truth_last[a["tid"]][2] = None
            elif kind == "praise" and a["tid"] in ours:     # 👍 on one of OUR messages → the session must be told
                chat, _ = roots[a["tid"]]; slack.owner_react(chat, ours[a["tid"]], a["emoji"]); reacted.append((a["tid"], ours[a["tid"]]))
            truth_touch[a["tid"]] = clock.now
            feed()
        feed()
        d.loop_tick(n); feed()
        # score the owner's view at the end of the tick (v3: ❓ needs you · 🔴 the session owes you · 🟠 handled · none = closed/stale)
        for tid, (chat, rts) in roots.items():
            root = slack.find(chat, rts); who, tlast, flag_t = truth_last[tid]
            if flag_t is not None and flag_t >= tlast: want = "✅" if who == "done" else None   # 🏁 newer than every message: bookkeeping off; the session's ✅ stays
            elif clock.now - tlast >= 48 * 3600: want = None            # 48 h quiet: even 🟠 expires
            elif who == "needs_owner": want = "❓"
            elif who == "owner": want = "❓" if clock.now - tlast >= 30 * 60 else "🔴"   # stalled at 30 min
            elif who == "done": want = "✅"                             # the session marked the root fully done
            else: want = "🟠"                                           # answered, nothing asked: handled
            have = slack.bot_status(root)
            if have != want:
                wrong_s += TICK; pending.setdefault(tid, clock.now)
                if clock.now - max(truth_touch.get(tid, tlast), flag_t or 0) < 120: cause["latency_<2min"] += TICK
                elif want is None: cause["stale_or_flagged_not_cleared"] += TICK
                elif want == "🟠": cause["handled_not_marked"] += TICK
                elif want == "🔴": cause["owed_not_marked"] += TICK
                elif who == "needs_owner": cause["session_ask_or_prompt_not_flagged"] += TICK
                else: cause["stall_not_flagged"] += TICK
            elif tid in pending:
                lat.append(clock.now - pending.pop(tid))
    per_day = DAYS
    api_total = sum(v for k, v in slack.calls.items() if not k.startswith("session:"))
    muts = slack.calls["reactions.add"] + slack.calls["reactions.remove"]
    got = {(p["meta"]["thread_ts"], p["meta"]["ts"]) for p in delivered if (p.get("meta") or {}).get("kind") == "reaction"}
    missed = [t for t in reacted if (roots[t[0]][1], t[1]) not in got]
    return {"reactions_delivered": len(got), "reactions_missed": len(missed), "reactions_expected": len(reacted),
            "api_calls_per_day": api_total / per_day, "reads_per_day": (slack.calls["conversations.history"] + slack.calls["conversations.replies"]) / per_day,
            "mutations_per_day": muts / per_day, "posts_per_day": slack.calls["chat.postMessage"] / per_day,
            "wrong_minutes_per_day": wrong_s / 60 / per_day, "mean_fix_latency_s": (sum(lat) / len(lat)) if lat else 0.0,
            "p95_fix_latency_s": (sorted(lat)[int(len(lat) * 0.95)] if lat else 0.0), "threads": len(roots),
            **{f"cause:{k}": v / 60 / per_day for k, v in cause.items()}}

if __name__ == "__main__":
    agg = collections.defaultdict(list)
    for s in SEEDS:
        r = run(s, path)
        for k, v in r.items(): agg[k].append(v)
        if VERBOSE: print(f"seed {s}: {json.dumps(r)}", file=sys.stderr)
    out = {k: sum(v) / len(v) for k, v in agg.items()}
    out["score"] = out["wrong_minutes_per_day"] + 0.05 * out["api_calls_per_day"]
    keys = ["score", "wrong_minutes_per_day", "api_calls_per_day", "reads_per_day", "mutations_per_day", "posts_per_day",
            "mean_fix_latency_s", "p95_fix_latency_s", "threads", "reactions_expected", "reactions_delivered", "reactions_missed"]
    for k in keys + sorted(k for k in out if k.startswith("cause:")):
        print(f"{k}: {out[k]:.3f}")
