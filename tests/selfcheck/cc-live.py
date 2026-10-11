# cc-live's selfcheck: the cases behind `cc-live selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-live execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

# ── selfcheck ─────────────────────────────────────────────────────────────────────────────────────────────────
def key_limit(load=None, cores=None):
    """(ms a keypress may take to redraw, why). The target, or under load the slack a shared box needs."""
    KEY_MS, KEY_MS_LOADED = 16, 48
    if os.environ.get("CC_LOADED"):
        return KEY_MS_LOADED, "CC_LOADED is set"
    load = os.getloadavg()[0] if load is None else load
    cores = (os.cpu_count() or 1) if cores is None else cores
    if load >= cores:
        return KEY_MS_LOADED, f"load {load:.1f} on {cores} cores"
    return KEY_MS, "the target"


def selfcheck():
    ok = bad = 0

    def case(name, cond):
        nonlocal ok, bad
        if cond:
            ok += 1
        else:
            bad += 1
            print(f"FAIL {name}")

    import tempfile
    tmp = tempfile.mkdtemp(prefix="cc-live-")
    now = int(time.time())
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    for k, v in {"CC_BOARDS": f"{tmp}/boards", "CC_STATE": f"{tmp}/state", "CC_LANDER_STATE": f"{tmp}/land",
                 "CC_WORKTREES": f"{tmp}/wt", "CC_SESSIONS": f"{tmp}/sessions", "CC_MEMBERS": f"{tmp}/members",
                 "CC_DEV": f"{tmp}/dev", "CC_PULSE": f"{tmp}/state/pulse.json", "CC_PULSE_SUITES": "/bin/true",
                 "CC_LIVE_FAILURES": f"{tmp}/bin/failures"}.items():
        os.environ[k] = v
    os.environ.pop("TMUX", None)
    for d in ("boards", "state/r/w1", "state/fund", "land/rest", "proc", "wt/r/w1", "bin", "sessions", "members", "dev/r"):
        os.makedirs(f"{tmp}/{d}")
    open(f"{tmp}/bin/tmux", "w").write("#!/bin/sh\n[ \"$1\" = capture-pane ] && { echo \"pane of $4\"; printf '\\n\\n'; }\n"
                                      "[ \"$1\" = switch-client ] && { sleep 1; echo \"no client for $3\" >&2; exit 1; }\nexit 0\n")
    open(f"{tmp}/bin/failures", "w").write("#!/bin/sh\necho '  c-1  gate-verdict/red  3 record(s)'\n")
    for n in ("tmux", "failures"):
        os.chmod(f"{tmp}/bin/{n}", 0o755)
    os.environ["PATH"] = f"{tmp}/bin:{os.environ.get('PATH', '')}"
    proc = f"{tmp}/proc"
    for pid, comm, cwd in ((30, "claude", f"{tmp}/wt/r/w1"), (50, "claude", f"{tmp}/dev/r")):
        os.makedirs(f"{proc}/{pid}")
        open(f"{proc}/{pid}/comm", "w").write(comm + "\n")
        open(f"{proc}/{pid}/cmdline", "wb").write(b"claude\0")
        open(f"{proc}/{pid}/stat", "w").write(f"{pid} ({comm}) S " + " ".join(["0"] * 18) + " 100 0\n")
        os.symlink(cwd, f"{proc}/{pid}/cwd")
        json.dump({"pid": pid, "sessionId": f"s{pid}", "cwd": cwd, "name": f"n{pid}", "status": "busy",
                   "statusUpdatedAt": (now - 60) * 1000, "tmux": f"main:@{pid}.%{pid}", "procStart": "100"},
                  open(f"{tmp}/sessions/{pid}.json", "w"))
    board = {"tracks": {
        "fresh": {"title": "just added", "status": "queued", "created": iso(now - 60)},
        "sent": {"title": "worker out", "status": "running", "created": iso(now - 7200),
                 "notes": [{"ts": iso(now - 900), "msg": "dispatched headless worker (loop 2)"}]},
        "w1": {"title": "live one", "status": "running", "created": iso(now - 90000)},
        "stuck": {"title": "a blocked one", "status": "blocked", "created": iso(now - 90000)},
        "old": {"title": "last week", "status": "merged", "created": iso(now - 7 * 86400)}}}
    json.dump(board, open(f"{tmp}/boards/r.json", "w"))
    json.dump({"tracks": {}}, open(f"{tmp}/boards/fund.json", "w"))
    json.dump({"title": "fund", "at": iso(now), "rows": [{"label": "paper P&L", "value": "+$212", "state": "ok"}]},
              open(f"{tmp}/state/fund/panel.json", "w"))
    json.dump({"repo": "r", "pr": 7, "stage": "gates", "title": "a landing",
               "history": [{"at": iso(now - 60), "state": "queued"}]}, open(f"{tmp}/land/r-7.json", "w"))
    json.dump({"repo": "r", "pr": "5", "title": "the fifth"}, open(f"{tmp}/land/rest/r-5.json", "w"))
    log = [(now - 7200, "stage r#5 merged sha=abc"), (now - 30 * 3600, "notify r#3 landed → thread"),
           (now - 600, "stage r#6 merged sha=def")]
    open(f"{tmp}/land/queue.log", "w").write("".join(f"{iso(t)}\t{m}\n" for t, m in log))
    open(f"{tmp}/state/r/w1/loop.log", "w").write(f"{iso(now - 3000)} iter 1/2 start (budget $5)\n{iso(now - 2000)} iter 2/2 start\n"
                                                  f"{iso(now - 1000)} DONE\n{iso(now - 900)} exit 1: gave up\n")
    pulse = P.Pulse(proc)
    p = pulse.step(now, laptop=False)
    W = 120

    # the deeper views, each over the fixture
    prs = "\n".join(t for t, _ in view_prs(now, W)[0])
    case("the PR list says when each landed, with its title", f"  {local(now - 7200)}    2h ago  r#5  the fifth" in prs and "r#3" in prs)
    g = [t for t, _ in view_graph(now, 60, 6)[0]]
    case("the graph has one bar per hour, the current hour last, counting what is in its span",
         len(g) == 8 and g[-1].startswith(f"  {local(int(now // 3600) * 3600, '%a %H:00')}") and "in all" in g[0])
    case("a wider graph counts the landing a narrow one leaves out",
         "2 in all" in g[0] and "3 in all" in view_graph(now, 60, 48)[0][0][0])
    tl = "\n".join(t for t, _ in view_timeline(now, W)[0])
    for word, what in (("added", "r/fresh  just added"), ("dispatched", "r/sent"), ("landed", "r#5  the fifth"),
                       ("worker started", "r/w1"), ("worker stopped", "r/w1  exit 1: gave up")):
        case(f"the timeline shows {word} {what}", f"{word:<15} {what}" in tl)
    case("the timeline leaves out a second iteration and what is older than a day",
         tl.count("worker started") == 1 and "r#3" not in tl and "r/old" not in tl)
    wv = "\n".join(t for t, _ in view_worker(now, W, "r", "sent")[0])
    case("a worker view shows its row and its notes", "r/sent  [running]  worker out" in wv and "dispatched headless" in wv)
    case("a worker view shows its loop log's last lines", "exit 1: gave up" in "\n".join(t for t, _ in view_worker(now, W, "r", "w1")[0]))
    case("a row gone from the board says so", "no such row" in view_worker(now, W, "r", "nope")[0][-1][0])
    lv = "\n".join(t for t, _ in view_landing(now, W, "r", "7")[0])
    case("a landing view shows its stage and history; an ended one is read from rest/",
         "stage:     gates" in lv and "queued" in lv and view_landing(now, W, "r", "5")[0][0][0] == "r#5  the fifth")
    sv = [t for t, _ in view_session(now, W, "30", p)[0]]
    case("a session view shows its state and its pane, blank tail cut", sv[0].startswith("n30  busy") and sv[-1] == "  pane of @30")
    case("a session gone from the pulse says so", "not on the pulse" in view_session(now, W, "9", p)[0][-1][0])
    bl, bi = view_board(now, W, "")
    case("the board view counts each project's open rows, and Enter goes to them",
         any("r " in t and "running 2" in t and "blocked 1" in t for t, _ in bl) and ("board", "r") in [i[1] for i in bi])
    rl, ri = view_board(now, W, "r")
    case("a project's board lists its open rows, running first, and each opens", rl[1][0].lstrip().startswith("running")
         and len(ri) == 4 and ri[0][1][0] == "worker" and not any("last week" in t for t, _ in rl))
    case("the failures view is cc-failures show", "gate-verdict/red" in view_failures(now, W)[0][2][0])
    case("the models view names the model and the log", view_models(now, W)[0][0][0].startswith("MODEL  default"))

    # the command line and the section keys
    case("a typed project name opens it; a section prefix opens the section; nonsense opens nothing",
         resolve("fund", p) == ("section", "project", "fund") and resolve("fail", p) == ("failures",)
         and resolve("bo", p) == ("board", "") and resolve("zzz", p) is None)
    K = curses
    nav = Nav()
    home, items = render(nav.view, p, Deep(), 80, 23, 24)
    case("home fits 80x24 and its items are sessions and workers",
         len(home) <= 23 and {i[1][0] for i in items} == {"session", "worker"})
    case("q quits from home", nav.key(ord("q"), items, 50, 20) == "quit")
    for k, v in ((ord("s"), ("section", "sessions")), (ord("b"), ("board", "")), (ord("f"), ("failures",)),
                 (ord("m"), ("models",)), (ord("l"), ("section", "landing")), (ord("n"), ("section", "needs")),
                 (ord("p"), ("section", "projects")), (ord("x"), ("section", "box")), (ord("P"), ("prs",)),
                 (ord("T"), ("timeline",)), (ord("w"), ("section", "workers")), (ord("r"), ("section", "recent"))):
        nav = Nav()
        case(f"one key from home opens {v}", nav.key(k, items, 50, 20) == "open" and nav.view == v)
    case("r again in recent opens the full timeline, as its heading says",
         "r again: the full timeline" in render(("section", "recent"), p, Deep(), 80, 23, 24)[0][0][0]
         and nav.key(ord("r"), [], 50, 20) == "open" and nav.view == ("timeline",))
    sp = {**p, "sections": {**p["sections"], "sessions": {"at": now - 300, "err": "TypeError: x", "stale": True}}}
    sh = [ln for ln in render(("home",), sp, Deep(), 80, 23, 24)[0] if ln[0].startswith("SESSIONS")]
    case("a stale sessions section is drawn STALE with its time, in warn, on home and in its section",
         sh and "STALE: as of" in sh[0][0] and sh[0][1] == "warn"
         and "STALE" in render(("section", "sessions"), sp, Deep(), 80, 23, 24)[0][0][0]
         and not any("STALE" in t for t, _ in render(("home",), p, Deep(), 80, 23, 24)[0]))
    nav = Nav()
    nav.key(ord("s"), items, 50, 20)
    nav.key(ord("b"), [], 50, 20)
    case("a section key from inside a section opens it on top, and h goes straight home",
         len(nav.stack) == 3 and nav.key(ord("h"), [], 50, 20) == "open" and nav.stack == [("home",)])
    nav = Nav()
    for k in (ord(":"), ord("f"), ord("u"), ord("n"), 127, ord("n"), ord("d")):
        nav.key(k, items, 50, 20, p)
    case("the command line takes letters and Backspace, and does not jump on them", nav.cmd == "fund" and nav.view == ("home",))
    case("Enter on the command line jumps to the project", nav.key(10, items, 50, 20, p) == "open"
         and nav.view == ("section", "project", "fund") and nav.cmd is None)
    case("b in a project opens that project's board rows", nav.key(ord("b"), [], 50, 20) == "open" and nav.view == ("board", "fund"))
    nav = Nav()
    nav.key(ord("p"), items, 50, 20)
    pl, pi = render(nav.view, p, Deep(), 80, 23, 24)
    nav.cur[-1] = [i[1] for i in pi].index(("section", "project", "fund"))
    case("Enter on a project's line opens its drill-in, drawn from the pulse",
         nav.key(10, pi, len(pl), 23) == "open" and render(nav.view, p, Deep(), 80, 23, 24)[0][1][0].startswith("PANEL fund"))
    nav = Nav()
    nav.key(ord("/"), items, 50, 20, p), nav.key(ord("x"), items, 50, 20, p)
    case("Esc closes the command line without moving", nav.key(27, items, 50, 20, p) is None and nav.cmd is None
         and nav.view == ("home",))
    nav = Nav()
    nav.key(K.KEY_DOWN, items, 50, 20)
    case("↓ moves the cursor; Enter opens the row under it", nav.cur[-1] == 1 and nav.key(10, items, 50, 20) == "open"
         and nav.view == items[1][1])
    case("Esc goes back to home with the cursor where it was", nav.key(27, [], 50, 20) == "open" and nav.view == ("home",)
         and nav.cur == [1])
    case("Esc on home stays home", nav.key(27, items, 50, 20) is None and nav.view == ("home",))
    nav.key(ord("T"), items, 50, 20)
    nav.key(K.KEY_NPAGE, [], 50, 20)
    case("PgDn scrolls a view with no rows to pick, no further than its end",
         nav.top[-1] == 20 and (nav.key(K.KEY_NPAGE, [], 50, 20), nav.top[-1])[1] == 30)
    nav = Nav()
    nav.key(ord("g"), items, 50, 20)
    case("the graph starts at 24 h; + doubles it and - halves it, within 6 h and a week",
         nav.hours == 24 and nav.key(ord("+"), [], 9, 20) == "open" and nav.hours == 48
         and [nav.key(ord("-"), [], 9, 20) for _ in range(4)] and nav.hours == 6
         and (nav.key(27, [], 9, 20), nav.key(ord("+"), items, 9, 20))[1] is None)
    sess_item = next(i for i in items if i[1][0] == "session")
    nav = Nav()
    nav.cur[-1] = items.index(sess_item)
    case("t on a session asks for tmux; on a worker it does nothing", nav.key(ord("t"), items, 50, 20) == "tmux"
         and (setattr(nav, "cur", [items.index(next(i for i in items if i[1][0] == "worker"))]),
              nav.key(ord("t"), items, 50, 20))[1] is None)
    case("t outside tmux says so instead of failing", switch("@30") == "t needs cc-live running inside tmux")
    fx = [(2, ("prs",)), (4, ("graph",)), (30, ("timeline",))]
    nav = Nav()
    nav.cur[-1] = 2
    nav.fit(fx, 40, 10)
    case("fit keeps the cursor's line on screen", nav.top[-1] <= 30 < nav.top[-1] + 10)
    p40 = {**p, "sessions": [{**p["sessions"][0], "id": str(i), "name": f"x{i}"} for i in range(40)]}
    nav = Nav()
    nav.key(ord("s"), items, 50, 23)
    sl, si = render(nav.view, p40, Deep(), 80, 23, 24)
    nav.fit(si, len(sl), 23)

    def pg(k):
        nav.key(k, si, len(sl), 23)
        nav.fit(si, len(sl), 23)
        return nav.top[-1], nav.cur[-1]
    down = pg(K.KEY_NPAGE)
    case("PgDn in a list of 40 sessions pages down and takes the cursor along",
         down[0] > 0 and down[0] <= si[down[1]][0] < down[0] + 23)
    case("PgUp comes back to the top, the cursor with it", pg(K.KEY_PPAGE) == (0, 0))
    pg(K.KEY_NPAGE)
    case("PgDn at the end puts the cursor on the last row", pg(K.KEY_NPAGE)[1] == len(si) - 1)

    # the deep views never block the loop
    deep = Deep()
    os.environ["CC_LIVE_FAILURES"] = f"{tmp}/bin/slow"
    open(f"{tmp}/bin/slow", "w").write("#!/bin/sh\nsleep 1; echo done\n")
    os.chmod(f"{tmp}/bin/slow", 0o755)
    t0 = time.perf_counter()
    first = deep.get(("failures",), 80, 24, p)
    case("a slow deeper view answers 'reading…' at once (the view takes 1 s) and fills in later",
         time.perf_counter() - t0 < 0.15 and first[0][0][0] == "reading…")

    # the whole loop over a fake screen: what it draws, how fast a key redraws, and a pulse change reaching it
    class Screen:            # curses' window methods, over a dict: the whole navigable loop with no terminal
        def __init__(self, keys, h=24, w=80):
            self.keys, self.rows, self.hi, self.shots, self.h, self.w = list(keys), {}, [], [], h, w

        def keypad(self, on):
            pass

        def timeout(self, ms):
            pass

        def getmaxyx(self):
            return self.h, self.w

        def erase(self):
            self.rows, self.hi = {}, []

        def addstr(self, y, x, text, attr=0):
            ln = self.rows.get(y, "").ljust(x)
            self.rows[y] = ln[:x] + text + ln[x + len(text):]
            if attr & curses.A_REVERSE:
                self.hi.append(text)

        def refresh(self):
            self.shots.append(("\n".join(self.rows.get(y, "") for y in range(self.h)), list(self.hi)))

        def getch(self):
            if not self.keys:
                raise KeyboardInterrupt
            k = self.keys.pop(0)
            if callable(k):
                return k()
            return k

    feed = Feed(proc)
    feed.put(p)
    tones = {"": 0, "bold": 0, "dim": 0, "warn": 0, "bad": 0}
    keys = [ord("s"), 27, K.KEY_DOWN, ord("b"), 27, ord(":"), ord("f"), ord("u"), 10, 27, ord("q")]
    timing = []
    scr = Screen(keys)
    rc = ui(scr, feed, Deep(), clock=lambda: now, tones=tones, timing=timing)
    shots = [t for t, _ in scr.shots]
    case("the loop draws home first, at 80x24, with the footer on the last row",
         shots[0].splitlines()[1].startswith("needs you") and "SESSIONS 2" in shots[0] and shots[0].splitlines()[23].startswith("s sess"))
    case("s opens sessions, Esc comes home, b opens the board, : fu Enter opens the fund's panel, q quits with 0",
         any(t.startswith("SESSIONS 2, waiting first") for t in shots) and any("PANEL fund" in t for t in shots)
         and "SESSIONS 2" in shots[-1] and rc == 0)
    case("the cursor is drawn on the row it is on", scr.shots[0][1] and scr.shots[0][1][0].lstrip().startswith("n"))
    worst = max(timing) * 1000 if timing else -1
    limit, why = key_limit()
    print(f"cc-live: a key redrew in {worst:.1f} ms at worst ({len(timing)} keys); limit {limit} ms ({why})")
    case(f"every key redraws in under {limit} ms ({why})", timing and worst < limit)
    loaded = os.environ.pop("CC_LOADED", None)
    case("the key limit is 16 ms on a calm box and 48 ms under load or with CC_LOADED set",
         key_limit(1.0, 6)[0] == 16 and key_limit(6.0, 6)[0] == 48
         and (os.environ.__setitem__("CC_LOADED", "1"), key_limit(0.0, 6)[0])[1] == 48)
    os.environ.pop("CC_LOADED", None)
    if loaded is not None:
        os.environ["CC_LOADED"] = loaded
    feet = [FOOT, FOOT_IN] + [t.splitlines()[23] for t in shots]
    case("every footer fits 79 columns, and home's ends with q quit", all(len(f) <= 79 for f in feet)
         and FOOT.endswith("q quit"))

    # t inside tmux: the switch runs in a thread, the key redraws at once, and tmux's answer reaches the footer
    os.environ["TMUX"] = "/tmp/fake,1,0"
    timing, scr = [], None

    def until_footer():
        if "tmux: no client for @" in scr.rows.get(23, ""):
            return ord("q")
        time.sleep(0.01)
        return -1
    scr = Screen([ord("t")] + [until_footer] * 300)
    try:
        ui(scr, feed, Deep(), clock=lambda: now, tones=tones, timing=timing)
    except KeyboardInterrupt:
        pass
    os.environ.pop("TMUX", None)
    feet = [t.splitlines()[23] for t, _ in scr.shots]
    case("t switches in a thread: the key redraws at once, saying so, and tmux's answer follows",
         timing and timing[0] < limit / 1000 and any(f.startswith("switching to") for f in feet)
         and "tmux: no client for @" in feet[-1])

    stamp = {}

    def change():                                  # a board write, while the loop runs on the in-process feed
        board["tracks"]["newrow"] = {"title": "brand new", "status": "running", "created": iso(now)}
        json.dump(board, open(f"{tmp}/boards/r.json.tmp", "w"))
        os.replace(f"{tmp}/boards/r.json.tmp", f"{tmp}/boards/r.json")
        stamp["t"] = time.perf_counter()
        return -1
    live = Feed(proc)
    live.done = False
    live.start()
    for _ in range(200):
        if live.p:
            break
        time.sleep(0.01)
    case("with no fresh pulse.json, cc-live collects in a thread of its own", live.local and live.p)

    class Watcher(Screen):
        def refresh(self):
            super().refresh()
            if "t" in stamp and "seen" not in stamp and "newrow" in self.shots[-1][0]:
                stamp["seen"] = time.perf_counter() - stamp["t"]

        def getch(self):
            if "t" not in stamp:
                return change()
            if "seen" in stamp or time.perf_counter() - stamp["t"] > 2:
                raise KeyboardInterrupt
            time.sleep(0.005)
            return -1
    try:
        ui(Watcher([], h=60, w=120), live, Deep(), tones=tones)
    except KeyboardInterrupt:
        pass
    live.done = True
    print(f"cc-live: a board write was on screen in {stamp['seen'] * 1000:.0f} ms" if "seen" in stamp
          else "cc-live: a board write never reached the screen")
    case("a board write is on screen in under 400 ms (~35 ms when idle)", stamp.get("seen", 9) < 0.4)

    # a feed that raises says so on screen, and the Watch it opened is closed
    made, RealWatch, RealFeed = [], P.Watch, P.feed

    class CountedWatch(RealWatch):
        def __init__(self):
            super().__init__()
            made.append(self)

    def broken(*a, **k):
        raise RuntimeError("boom")
    P.Watch, P.feed = CountedWatch, broken
    dead = Feed(proc)
    dead.follow()
    P.Watch, P.feed = RealWatch, RealFeed
    case("a feed that raises keeps its error and closes its Watch", dead.err == "RuntimeError: boom"
         and made and all(m.fd < 0 for m in made))
    case("with no pulse, the error is the screen", render(("home",), None, Deep(), 80, 23, 24, dead.err)[0][0][0]
         .startswith("PULSE STOPPED (RuntimeError: boom)"))
    el, ei = render(("home",), p, Deep(), 80, 23, 24, dead.err)
    case("with a pulse, the error heads the view, which still fits, and the cursor rows move down one",
         el[0][0].startswith("PULSE STOPPED") and len(el) <= 23 and ei[0][0] == items[0][0] + 1 and ei[0][1] == items[0][1])
    P.write(p)
    fol = Feed(proc)
    threading.Thread(target=fol.follow, daemon=True).start()
    for _ in range(200):
        if fol.p:
            break
        time.sleep(0.01)
    case("a fresh pulse.json is followed, not collected again", fol.p and not fol.local)
    fol.done = True
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"cc-live selfcheck: {ok} passed, {bad} failed")
    return 1 if bad else 0
