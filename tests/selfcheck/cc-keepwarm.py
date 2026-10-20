# cc-keepwarm's selfcheck: the cases behind `cc-keepwarm selfcheck`. Not a module: cc-keepwarm execs this file INSIDE
# ITS OWN NAMESPACE and calls the selfcheck() it defines, so every name here is the tool's and a `global` rebinds the
# tool's. No module docstring and no top-level name but the defs below. Each case builds its own transcript and pane.

def selfcheck():
    global STATE, LOG, PROJECTS
    import tempfile, io, contextlib
    d = tempfile.mkdtemp(prefix="cc-keepwarm-sc.")
    STATE, LOG, PROJECTS = f"{d}/keepwarm.json", f"{d}/keepwarm.log", f"{d}/projects"
    os.makedirs(f"{PROJECTS}/-home-x-dev-r", exist_ok=True)
    NOW = 1_800_000_000.0
    ok = bad = 0

    def k(cond, what):
        nonlocal ok, bad
        if cond:
            ok += 1
        else:
            bad += 1; print(f"FAIL: {what}")

    def iso(t):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".000Z"

    def user(t, text, entry="cli"):
        return {"type": "user", "timestamp": iso(t), "entrypoint": entry, "message": {"role": "user", "content": text}}

    def result(t):
        return {"type": "user", "timestamp": iso(t), "entrypoint": "cli",
                "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}}

    n = [0]

    def call(t, ctx, write=None, stop="end_turn", model="claude-opus-5-5", tools=()):
        n[0] += 1
        w = ctx if write is None else write
        content = [{"type": "text", "text": "done"}] + [{"type": "tool_use", "name": nm, "input": inp} for nm, inp in tools]
        return {"type": "assistant", "timestamp": iso(t), "entrypoint": "cli", "requestId": f"req{n[0]}",
                "message": {"id": f"msg{n[0]}", "model": model, "stop_reason": stop, "content": content,
                            "usage": {"input_tokens": 3, "cache_creation_input_tokens": w,
                                      "cache_read_input_tokens": ctx - w, "output_tokens": 50}}}

    def limit(t):
        return {"type": "assistant", "timestamp": iso(t), "entrypoint": "cli", "isApiErrorMessage": True, "error": "rate_limit",
                "message": {"id": f"lim{t}", "model": "<synthetic>", "content": [{"type": "text", "text": "You've hit your weekly limit"}],
                            "usage": {"input_tokens": 0, "output_tokens": 0}}}

    def busy_history(last, ctx=150_000, turns=3):
        """A seat that took `turns` real turns in the hours before its last call at `last`."""
        out = []
        for i in range(turns, 0, -1):
            t = last - i * 1800
            out += [user(t, f"wake {i}"), call(t + 30, ctx - i * 1000)]
        return out + [user(last - 60, "last"), call(last, ctx)]

    def transcript(sid, rows):
        p = f"{PROJECTS}/-home-x-dev-r/{sid}.jsonl"
        with open(p, "w") as f:
            f.write("\n".join(json.dumps(r) for r in rows) + "\n")
        return p

    IDLE = "╭───\n│ ❯ \n╰───\n  ? for shortcuts\n"
    BUSY = "⏺ Reading files…\n  ✻ Thinking… (esc to interrupt)\n│ ❯ \n"

    class Fake(Host):
        def __init__(self, on=True, binds=False):
            self.on, self.binds, self.wins, self.scr, self.args, self.kids, self.paths, self.typed = on, binds, [], {}, {}, {}, {}, []

        def add(self, name, mode, scr=IDLE, path=None, extra=(), copy=False):
            i = len(self.wins) + 1
            wid, pane, cl = f"@{i}", str(1000 + i), str(2000 + i)
            self.wins.append((wid, name, pane, copy))
            self.scr[wid] = scr
            self.args[pane] = ["bash", "/home/x/bin/cc", mode] if mode else ["bash"]
            self.args[cl] = ["claude", *extra]
            self.kids[pane] = [cl]
            self.paths[pane] = path
            return wid

        def enabled(self): return self.on
        def limit_binds(self): return self.binds
        def windows(self): return list(self.wins)
        def screen(self, wid): return self.scr[wid]
        def argv(self, pid): return self.args.get(str(pid), [])
        def tree(self, pid): return [str(pid)] + self.kids.get(str(pid), [])
        def transcript(self, pid): return self.paths.get(str(pid))
        def type(self, wid, text):
            self.typed.append((wid, text)); return "sent"

    q = lambda: contextlib.redirect_stdout(io.StringIO())
    last = NOW - 52 * 60

    def fresh():
        for p in (STATE, LOG):
            if os.path.exists(p):
                os.remove(p)

    # 1 an idle planning seat that has been taking turns, 52 min after its last call: one keepalive, the line itself
    fresh(); h = Fake(); w = h.add("r", "__runmain", path=transcript("s1", busy_history(last)))
    with q():
        tick(h, True, NOW)
    k(h.typed == [(w, KEEPALIVE)], f"an idle seat likely to wake gets one keepalive (typed {h.typed})")
    k(MARK in KEEPALIVE and "no tools" in KEEPALIVE and "\n" not in KEEPALIVE, "the keepalive is one line asking for no tools")

    # 2 two ticks in one window send one; a third after the keepalive's own call is chain 1, still under max_chain
    with q():
        tick(h, True, NOW + 300)
    k(len(h.typed) == 1, "a second tick in the same window sends nothing more")

    # 3 an orch and the perms seat are seats too
    fresh(); h = Fake(); h.add("r@fund", "__runorch", path=transcript("s3", busy_history(last)))
    h.add("perms", None, path=transcript("s3b", busy_history(last)), extra=("--dangerously-skip-permissions",))
    with q():
        tick(h, True, NOW)
    k(len(h.typed) == 2, f"an orch and perms are kept warm like planning (typed {len(h.typed)})")

    # 4 a busy seat: the pane says esc to interrupt
    fresh(); h = Fake(); h.add("r", "__runmain", scr=BUSY, path=transcript("s4", busy_history(last)))
    with q():
        tick(h, True, NOW)
    k(h.typed == [], "a seat mid-turn on its pane gets none")

    # 5 a busy seat: its transcript ends on a tool call with no result (a long foreground tool)
    fresh(); h = Fake()
    rows = busy_history(last - 60)[:-1] + [call(last, 150_000, stop="tool_use", tools=[("Bash", {"command": "sleep 9999"})])]
    h.add("r", "__runmain", path=transcript("s5", rows))
    with q():
        tick(h, True, NOW)
    k(h.typed == [], "a seat whose transcript ends on an open tool call gets none")

    # 6 a limit-parked seat: the transcript ends on the limit error; and the pane's wall alone; and cc-limit's stamp
    fresh(); h = Fake(); h.add("r", "__runmain", path=transcript("s6", busy_history(last - 120) + [user(last - 5, "go"), limit(last)]))
    with q():
        tick(h, True, NOW)
    k(h.typed == [], "a seat whose transcript ends on a usage-limit error gets none")
    fresh(); h = Fake(); h.add("r", "__runmain", scr="You've hit your weekly limit · resets 1pm\n│ ❯ \n", path=transcript("s6b", busy_history(last)))
    with q():
        tick(h, True, NOW)
    k(h.typed == [], "a seat showing the limit wall on its pane gets none")
    fresh(); h = Fake(binds=True); h.add("r", "__runmain", path=transcript("s6c", busy_history(last)))
    with q():
        tick(h, True, NOW)
    k(h.typed == [], "while cc-limit's stamp binds nobody gets one")

    # 7 a cold seat the rule rejects: one turn in six hours and nothing out
    fresh(); h = Fake(); h.add("r", "__runmain", path=transcript("s7", [user(last - 60, "only"), call(last, 150_000)]))
    with q():
        tick(h, True, NOW)
    k(h.typed == [], "a cold seat the rule rejects gets none")
    # …but the same seat with a background task out is likely to wake on its notification
    fresh(); h = Fake()
    h.add("r", "__runmain", path=transcript("s7b", [user(last - 60, "only"), call(last, 150_000, tools=[("Monitor", {"command": "x"})])]))
    with q():
        tick(h, True, NOW)
    k(len(h.typed) == 1, "a quiet seat with a Monitor out is kept warm")
    # …and a small context is cheaper to write again than to keep
    fresh(); h = Fake(); h.add("r", "__runmain", path=transcript("s7c", busy_history(last, ctx=20_000)))
    with q():
        tick(h, True, NOW)
    k(h.typed == [], "a seat under min_ctx gets none")

    # 8 a member session, a track, a worker and a handoff window get none, whatever their transcript says
    fresh(); h = Fake()
    h.add("r", "__runmember", path=transcript("s8", busy_history(last)))
    h.add("r2", "__runmain", path=transcript("s8b", busy_history(last)), extra=("cc-sandbox",))
    h.add("r/t", "__run", path=transcript("s8c", busy_history(last)))
    h.add("r~next", "__runmain", path=transcript("s8d", busy_history(last)))
    with q():
        tick(h, True, NOW)
    k(h.typed == [], f"a member, a sandboxed pane, a track and a handoff window get none (typed {h.typed})")

    # 9 the window: 40 min idle is too early, 70 min is too late (the cache is gone; a keepalive would only re-write it)
    for mins in (40, 70):
        fresh(); h = Fake(); h.add("r", "__runmain", path=transcript(f"s9{mins}", busy_history(NOW - mins * 60)))
        with q():
            tick(h, True, NOW)
        k(h.typed == [], f"{mins} min idle gets none")

    # 10 a person typing, a dialog and copy mode hold it; the key off holds everything
    for name, kw in (("typing", {"scr": "│ ❯ half a sentence\n"}), ("dialog", {"scr": "Do you want to proceed?\n Esc to cancel\n"}),
                     ("copy", {"copy": True})):
        fresh(); h = Fake(); h.add("r", "__runmain", path=transcript(f"s10{name}", busy_history(last)), **kw)
        with q():
            tick(h, True, NOW)
        k(h.typed == [], f"a pane with {name} gets none")
    fresh(); h = Fake(on=False); h.add("r", "__runmain", path=transcript("s10off", busy_history(last)))
    with q():
        tick(h, True, NOW)
    k(h.typed == [], f"{KEY} off sends nothing")

    # 11 a chain stops at max_chain: three keepalives since the last real turn and the fourth is not sent
    fresh(); h = Fake()
    rows = busy_history(last - 3 * 55 * 60)
    for i in range(DEFAULT.max_chain):
        t = last - (DEFAULT.max_chain - 1 - i) * 55 * 60
        rows += [user(t - 5, KEEPALIVE), call(t, 150_000 + i * 500, write=500)]
    h.add("r", "__runmain", path=transcript("s11", rows))
    with q():
        tick(h, True, NOW)
    k(h.typed == [], "a seat already kept warm max_chain times since its last real turn gets none")
    s = read_session(open(f"{PROJECTS}/-home-x-dev-r/s11.jsonl"))
    k(features(s, s["calls"][-1].t)["chain"] == DEFAULT.max_chain and len(s["kas"]) == DEFAULT.max_chain,
      "keepalive turns count as the chain, never as the seat's own turns")

    # 12 a failure on one seat is a log line and the walk moves on
    fresh(); h = Fake(); h.add("r", "__runmain", path=f"{d}/missing.jsonl"); w2 = h.add("r2", "__runmain", path=transcript("s12", busy_history(last)))
    with q():
        tick(h, True, NOW)
    k(h.typed == [(w2, KEEPALIVE)] and "error" in open(LOG).read(), "one seat's failure is logged and the next is still served")

    # 13 the replay: a seat woken 80 min after a quiet call with work out is saved; one never woken is wasted
    s = read_session([json.dumps(r) for r in
                      [user(NOW - 9000, "a"), call(NOW - 8990, 200_000, tools=[("Monitor", {})]),
                       user(NOW - 8990 + 80 * 60, "<task-notification>done</task-notification>"),
                       call(NOW - 8990 + 80 * 60 + 5, 201_000, write=201_000)]])
    r = replay_session(s, DEFAULT, NOW - 86400, NOW)
    k(r["cold"] == 1 and r["warmed"] == 1 and r["ka"] >= 1 and r["saved"] > r["ka_cost"] > 0,
      f"replay: a cold wake the rule kept warm is a saving larger than its keepalive ({r})")
    s = read_session([json.dumps(r) for r in [user(NOW - 30000, "a"), call(NOW - 29990, 200_000, tools=[("Monitor", {})])]])
    r = replay_session(s, DEFAULT, NOW - 86400, NOW)
    k(r["ka"] == DEFAULT.max_chain and r["wasted"] == DEFAULT.max_chain and r["saved"] == 0,
      f"replay: a seat that never woke wastes max_chain keepalives ({r})")
    s = read_session([json.dumps(r) for r in busy_history(NOW - 20000, ctx=150_000)[:-2] +
                      [user(NOW - 20000, "x"), call(NOW - 19990, 150_000), user(NOW - 19980, "y"), limit(NOW - 19970),
                       user(NOW - 19000, "resume"), call(NOW - 18990, 151_000, write=151_000)]])
    r = replay_session(s, DEFAULT, NOW - 86400, NOW - 18000)     # ends before the resumed call's own idle window
    k(r["resume_cold"] == 1 and r["ka"] == 0, f"replay: a cold resume after a limit is counted for the add-on, never kept warm ({r})")

    # 14 Host.type re-captures the pane before Enter and presses it only when the box holds the keepalive alone
    class Tmux(Host):
        def __init__(self, after): self.after, self.keys = after, []
        def run(self, *a, timeout=10): self.keys.append(a[-1]); return 0, ""
        def screen(self, wid): return self.after
    wrapped = "╭───\n│ ❯ " + KEEPALIVE[:60] + "\n│   " + KEEPALIVE[60:] + "\n╰───\n  ? for shortcuts\n"
    sleep, time.sleep = time.sleep, lambda s: None
    try:
        for after, want, what in [(wrapped, "sent", "the keepalive alone, wrapped"),
                                  (wrapped.replace("period.", "period.and my own"), "pane changed before Enter", "a person typing after it"),
                                  (wrapped + "  ✻ Thinking… (esc to interrupt)\n", "pane changed before Enter", "a wake in the gap"),
                                  (None, "pane changed before Enter", "an unreadable pane")]:
            h = Tmux(after); said = h.type("@1", KEEPALIVE)
            k(said == want and (h.keys[-1] == "Enter") == (want == "sent"), f"type with {what}: {said}, keys {h.keys}")
    finally:
        time.sleep = sleep

    print(f"cc-keepwarm selfcheck: {ok} passed, {bad} failed")
    return 0 if bad == 0 else 1
