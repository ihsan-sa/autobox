# cc-live's selfcheck: the cases behind `cc-live selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-live execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

# ── selfcheck ─────────────────────────────────────────────────────────────────────────────────────────────────
def selfcheck():
    ok = bad = 0

    def case(name, cond):
        nonlocal ok, bad
        if cond:
            ok += 1
        else:
            bad += 1
            print(f"FAIL {name}")

    tmp = tempfile.mkdtemp(prefix="cc-live-")
    now = 1_790_000_000
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    for k, v in {"CC_BOARDS": f"{tmp}/boards", "CC_STATE": f"{tmp}/state", "CC_LANDER_STATE": f"{tmp}/land",
                 "CC_WORKTREES": f"{tmp}/wt", "CC_TMUX_SESSION": "cc-live-selfcheck-none", "CC_LIVE_PLAIN": "1"}.items():
        os.environ[k] = v
    for d in ("boards", "state/r/w1", "land", "proc", "wt/r/w1", "bin"):
        os.makedirs(f"{tmp}/{d}")
    # a tmux of its own, so the box's own server is never asked: no session until a case writes the windows file
    open(f"{tmp}/bin/tmux", "w").write(f"#!/bin/sh\n[ -f {tmp}/windows ] || exit 1\n"
                                       f"[ \"$1\" = capture-pane ] && {{ echo \"pane of $4\"; printf '\\n\\n'; exit 0; }}\n"
                                       f"cat {tmp}/windows\n")
    os.chmod(f"{tmp}/bin/tmux", 0o755)
    open(f"{tmp}/bin/suites", "w").write("#!/bin/sh\necho 'cc-suites: runner lap answers: free 3 cores=8 slots=4 maxload=6 load=0.10 ac=1'\n")
    open(f"{tmp}/bin/suites-hang", "w").write("#!/bin/sh\nexec sleep 30\n")
    for n in ("suites", "suites-hang"):
        os.chmod(f"{tmp}/bin/{n}", 0o755)
    os.environ["CC_LIVE_SUITES"] = f"{tmp}/bin/suites"
    os.environ["PATH"] = f"{tmp}/bin:{os.environ.get('PATH', '')}"
    board = {"tracks": {
        "fresh": {"title": "just added", "status": "queued", "created": iso(now - 60)},
        "sent": {"title": "worker out", "status": "running", "created": iso(now - 7200),
                 "notes": [{"ts": iso(now - 900), "msg": "dispatched headless worker (loop 2)"}]},
        "w1": {"title": "live one", "status": "running", "created": iso(now - 90000)},
        "gone": {"title": "dead one", "status": "running", "created": iso(now - 90000), "held": "waits on #9"},
        "lost": {"title": "lost one", "status": "running", "created": iso(now - 90000)},
        "mine": {"title": "held by a seat", "status": "running", "created": iso(now - 90000), "agent": "@1:10"},
        "stale": {"title": "mark of a dead seat", "status": "running", "created": iso(now - 90000), "agent": "@1:999"},
        "sess": {"title": "a session", "status": "running", "kind": "session", "created": iso(now - 90000)},
        "old": {"title": "last week", "status": "merged", "created": iso(now - 7 * 86400)},
        "bad": "not a row"}}
    json.dump(board, open(f"{tmp}/boards/r.json", "w"))
    json.dump({"tracks": {"x": {"title": "test board", "created": iso(now)}}}, open(f"{tmp}/boards/_t.json", "w"))
    json.dump({"repo": "r", "pr": 7, "stage": "gates", "title": "a landing"}, open(f"{tmp}/land/r-7.json", "w"))
    for pr in (8, 9):
        json.dump({"repo": "r", "pr": pr, "stage": "queued"}, open(f"{tmp}/land/r-{pr}.json", "w"))
    open(f"{tmp}/state/r/w1/loop.log", "w").close()
    os.utime(f"{tmp}/state/r/w1/loop.log", (now - 120, now - 120))

    def fake(pid, ppid, comm, argv, cwd=None):
        p = f"{tmp}/proc/{pid}"
        os.makedirs(p)
        open(f"{p}/comm", "w").write(comm + "\n")
        open(f"{p}/status", "w").write(f"Name:\t{comm}\nPPid:\t{ppid}\n")
        open(f"{p}/cmdline", "wb").write("\0".join(argv).encode() + b"\0")
        if cwd:
            os.symlink(cwd, f"{p}/cwd")
    fake(10, 1, "bash", ["bash"])                                   # seat pane with a claude two levels down
    fake(11, 10, "node", ["node"])
    fake(12, 11, "claude", ["claude"], cwd="/somewhere")
    fake(20, 1, "bash", ["bash"])                                   # a pane with nothing in it
    fake(30, 1, "claude", ["claude", "-p"], cwd=f"{tmp}/wt/r/w1")    # a headless worker in its worktree
    fake(40, 1, "bash", ["bash", "/x/cc-loop", "r", "sent"])        # a worker loop between turns
    fake(50, 1, "claude", ["claude"], cwd="/somewhere")             # a pane whose own process is claude
    fake(60, 1, "ssh", ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "lap", "job", "lint", "a" * 40, "300", "Zm9v", "-"])

    bds = boards()
    case("a `_` test board is skipped", list(bds) == ["r"])
    ho = handoffs(bds, now)
    names = [(e[3], e[1]) for e in ho]
    case("hand-offs newest first", names[:2] == [("fresh", "added"), ("sent", "dispatched")])
    case("a dispatch note outranks the older created stamp", ("sent", "dispatched") in names and ("sent", "added") not in names)
    case("a row older than a day is not a hand-off", "old" not in [e[3] for e in ho])
    case("a non-dict row is skipped, not a crash", "bad" not in [e[3] for e in ho])
    live, table = procs(f"{tmp}/proc")
    case("a claude in a worktree makes its track live", "r/w1" in live)
    case("a cc-loop argv makes its track live", "r/sent" in live)
    case("a claude outside the worktrees is no track", not any("somewhere" in k for k in live))
    case("a claude under a pane is found through its children", has_claude("10", table))
    case("an empty pane has no claude", not has_claude("20", table))
    case("a pane that is claude itself has one", has_claude("50", table))
    case("an empty pane is offline", seat_state("s", now, "20", table, now) == "offline")
    case("a quiet pane with claude is idle", seat_state("s", now - IDLE, "10", table, now) == "idle 10m")
    case("a pane that just printed is working", seat_state("s", now - IDLE + 1, "10", table, now) == "working")
    case("an orch window is shown alias@repo", shown("r@bench") == "bench@r" and shown("r/t") == "r/t" and shown("r") == "r")
    txt = "\n".join(frame(now, f"{tmp}/proc"))
    case("the frame marks a fresh hand-off NEW", "NEW   1m ago  added      r/fresh" in txt)
    case("a hand-off 10 min old is not NEW", "NEW" not in [ln for ln in txt.splitlines() if "r/sent" in ln][0])
    case("a live worker shows its last move", "r/w1  live, moved 2m ago" in txt)
    case("a running row with no process and no hold is OFFLINE", "r/lost  OFFLINE" in txt)
    case("a row whose agent mark names a live pid is worked, not offline", "r/mine  worked by a session" in txt)
    case("an agent mark whose pid is gone is still OFFLINE", "r/stale  OFFLINE" in txt)
    case("a held row with no process is named on the held line, not as offline", "no process: r/gone" in txt and "r/gone  OFFLINE" not in txt)
    case("a session row is not counted as running", "r/sess" not in txt)
    case("an active landing gets a line of its own", "r#7  gates" in txt)
    case("queued landings share one line", "queued (2): r#9 r#8" in txt or "queued (2): r#8 r#9" in txt)
    case("no tmux session: seats are marked offline", "every seat is offline" in txt)
    rows = [("seat", now, 10), ("gone", now, 20), ("r@orch", now - IDLE, 50), ("r/dead", now, 20),
            ("r/on", now, 10), ("_cctest1", now, 20)]
    open(f"{tmp}/windows", "w").write("".join(f"{n}\t{a}\t{p}\n" for n, a, p in rows))
    txt = "\n".join(frame(now, f"{tmp}/proc", width=40))
    case("a seat with claude that just printed is working", "seat" + " " * 27 + "working" in txt)
    case("a seat with no claude is offline", "gone" + " " * 27 + "offline" in txt)
    case("an orch is shown alias@repo, and idle", "orch@r" + " " * 25 + "idle 10m" in txt)
    case("a live track window is listed", "r/on " in txt)
    case("a dead track window is only counted", "r/dead" not in txt and "and 1 track window(s)" in txt)
    case("a selftest window is not listed", "_cctest1" not in txt)
    case("the LAPTOP section shows the runner's state line", "LAPTOP" in txt and "answers: free 3 cores=8 slots=4" in txt)
    case("a check spilled to the laptop is listed", "running there now (1): lint aaaaaaaa" in txt)
    for i, (job, chk, runner, st) in enumerate([("r-1", "lint", "laptop:x", "passed"), ("r-2", "check", "box:h", "passed"),
                                                ("r-3", "check", "laptop:x", "failed"), ("r-4", "lint", "laptop:x", "passed")]):
        d = f"{tmp}/land/jobs/{job}/results/{chk}"
        os.makedirs(d, exist_ok=True)
        json.dump({"runner": runner, "status": st, "check": chk}, open(f"{d}/h{i}.json", "w"))
        os.utime(f"{d}/h{i}.json", (now - 100 + i * 10, now - 100 + i * 10))
    dn = laptop_done()
    case("finished laptop checks: newest first, box ones skipped",
         [(c, j, s_) for _, c, j, s_ in dn] == [("lint", "r-4", "passed"), ("check", "r-3", "failed"), ("lint", "r-1", "passed")])
    case("laptop_done stops at n", len(laptop_done(2)) == 2)
    case("the LAPTOP block lists them with time and result",
         "    " + time.strftime("%H:%M", time.localtime(now - 70)) + "  lint  r-4  passed" in "\n".join(frame(now, f"{tmp}/proc")))
    os.environ["CC_LIVE_SUITES"] = f"{tmp}/bin/suites-hang"
    t0 = time.monotonic()
    case("a runner that hangs is one line, in bounded time",
         laptop_line() == "the laptop runner did not answer in 6 s" and time.monotonic() - t0 < 9)
    os.environ["CC_LIVE_SUITES"] = f"{tmp}/bin/suites"
    json.dump({"limit_until": now + 3600}, open(f"{tmp}/state/reconcile.json", "w"))
    case("a usage limit ahead is shown", "usage limit holds work" in "\n".join(frame(now, f"{tmp}/proc")))
    json.dump({"limit_until": now - 1}, open(f"{tmp}/state/reconcile.json", "w"))
    case("a usage limit behind is not", "usage limit" not in "\n".join(frame(now, f"{tmp}/proc")))

    # the views Enter opens, each over its own fixture
    os.makedirs(f"{tmp}/land/rest")
    json.dump({"repo": "r", "pr": "5", "title": "the fifth"}, open(f"{tmp}/land/rest/r-5.json", "w"))
    log = [(now - 7200, "stage r#5 merged sha=abc"), (now - 7100, "notify r#5 landed → thread"),
           (now - 30 * 3600, "notify r#3 landed → thread"), (now - 600, "stage r#6 merged sha=def"),
           (now - 500, "stage _t#1 merged sha=x"), (now - 400, "stage r#8 gate"), (now - 300, "not a line")]
    open(f"{tmp}/land/queue.log", "w").write("".join(f"{iso(t)}\t{m}\n" for t, m in log) + f"{iso(now)}\tstage r#9 mer")
    ld = landed()
    case("landed: newest first, the earliest of merged and notify, no test repo, no other stage",
         ld == [(now - 600, "r", "6"), (now - 7200, "r", "5"), (now - 30 * 3600, "r", "3")])
    open(f"{tmp}/land/queue.log", "a").write(f"ged sha=1\n")
    case("a half-written last line is read whole on the next refresh", landed()[0] == (now, "r", "9"))
    open(f"{tmp}/land/queue.log", "w").write(f"{iso(now - 60)}\tstage r#4 merged sha=2\n")
    case("a log that was cut short is read again from the top", landed() == [(now - 60, "r", "4")])
    open(f"{tmp}/land/queue.log", "w").write("".join(f"{iso(t)}\t{m}\n" for t, m in log))
    _LOG.update(ino=None)
    prs = "\n".join(view_prs(now, 120))
    case("the PR list says when each landed, with its title",
         f"  {local(now - 7200)}    2h ago  r#5  the fifth" in prs and "r#3" in prs and "r#8" not in prs)
    g = view_graph(now, 60, 6)
    case("the graph has one bar per hour, oldest first, the current hour last",
         len(g) == 8 and g[-1].startswith(f"  {local(int(now // 3600) * 3600, '%a %H:00')}"))
    case("the graph counts a landing in its hour and leaves out one older than its span",
         g[-1].endswith(" 1") and "2 in all" in g[0] and "3 in all" in view_graph(now, 60, 48)[0])
    open(f"{tmp}/land/queue.log", "a").write(f"{iso(int(now // 3600) * 3600 - 5 * 3600)}\tstage r#2 merged sha=3\n"
                                              f"{iso(int(now // 3600) * 3600 - 5 * 3600 - 1)}\tstage r#1 merged sha=4\n")
    case("a landing on the first second of the oldest hour is counted, one a second earlier is not",
         "3 in all" in view_graph(now, 60, 6)[0])
    case("an hour with no landing has no bar", sum(1 for ln in g[2:] if ln.rstrip().endswith(":00")) == 4)
    open(f"{tmp}/state/r/w1/loop.log", "w").write(f"{iso(now - 3000)} iter 1/2 start (budget $5)\n{iso(now - 2000)} iter 2/2 start\n"
                                                  f"{iso(now - 1000)} DONE\n{iso(now - 900)} exit 1: gave up\n")
    tl = "\n".join(view_timeline(now, 120))
    for word, what in (("added", "r/fresh  just added"), ("dispatched", "r/sent"), ("landed", "r#5  the fifth"),
                       ("worker started", "r/w1"), ("worker stopped", "r/w1"), ("worker stopped", "r/w1  exit 1: gave up")):
        case(f"the timeline shows {word} {what}", f"{word:<15} {what}" in tl)
    case("the timeline leaves out a second iteration and what is older than a day",
         tl.count("worker started") == 1 and "r#3" not in tl and "r/old" not in tl)
    w = "\n".join(view_worker(now, 120, "r", "sent"))
    case("a worker view shows its row and its notes", "r/sent  [running]  worker out" in w and "dispatched headless" in w)
    w = "\n".join(view_worker(now, 120, "r", "w1"))
    case("a worker view shows its loop log's last lines", "LOOP.LOG (last 4 lines" in w and "exit 1: gave up" in w)
    case("a row gone from the board says so", "no such row" in view_worker(now, 120, "r", "nope")[-1])
    json.dump({"repo": "r", "pr": 7, "stage": "gates", "title": "a landing",
               "history": [{"at": iso(now - 60), "state": "queued"}]}, open(f"{tmp}/land/r-7.json", "w"))
    lv = "\n".join(view_landing(now, 120, "r", "7"))
    case("a landing view shows its stage and history", "stage:     gates" in lv and "queued" in lv)
    case("an ended landing is read from rest/", view_landing(now, 120, "r", "5")[0] == "r#5  the fifth")
    sv = view_seat(now, 120, "seat", f"{tmp}/proc")
    case("a seat view shows its state and what its pane printed, blank tail cut",
         sv[0] == "seat  working" and sv[-1] == "  pane of cc-live-selfcheck-none:=seat")
    case("a seat that went away says so", view_seat(now, 120, "nope", f"{tmp}/proc")[-1] == "  (no such window now)")

    # the cursor: what the home screen offers, and what each key does
    items = []
    home = frame(now, f"{tmp}/proc", 120, items)
    case("the home screen opens with the three views", [i[3] for i in items[:3]] == [("prs",), ("graph",), ("timeline",)]
         and home[1] == "  [ PRs landed ]  [ landings graph ]  [ timeline ]" and home[1][items[1][1]:items[1][2]] == "[ landings graph ]")
    kinds = [i[3][0] for i in items]
    case("hand-offs, running rows, seats and landings are items, in screen order",
         {"worker", "seat", "landing"} <= set(kinds) and [i[0] for i in items] == sorted(i[0] for i in items))
    seat = next(i for i in items if i[3] == ("seat", "r@orch"))
    case("a seat item spans its own cell", home[seat[0]][seat[1]:seat[2]].startswith("orch@r "))
    case("the plain frame has no menu line and --once keeps its shape", "[ PRs landed ]" not in "\n".join(frame(now, f"{tmp}/proc")))
    K = curses
    nav = Nav()
    case("q quits from home", nav.key(ord("q"), items, 50, 20) == "quit")
    nav.key(K.KEY_DOWN, items, 50, 20)
    nav.key(K.KEY_DOWN, items, 50, 20)
    case("↓ moves the cursor", nav.cur == 2)
    nav.key(K.KEY_LEFT, items, 50, 20)
    case("← on home moves the cursor back, and does not leave home", nav.cur == 1 and nav.view == ("home",))
    nav.key(K.KEY_UP, items, 50, 20), nav.key(K.KEY_UP, items, 50, 20)
    case("↑ stops at the first item", nav.cur == 0)
    case("Enter opens the item under the cursor", nav.key(10, items, 50, 20) == "open" and nav.view == ("prs",))
    nav.key(K.KEY_NPAGE, [], 50, 20)
    case("PgDn scrolls a view, no further than its end", nav.top == 20 and (nav.key(K.KEY_NPAGE, [], 50, 20), nav.top)[1] == 30)
    case("Esc goes back home", nav.key(27, [], 50, 20) == "open" and nav.view == ("home",) and nav.top == 0)
    nav.key(K.KEY_DOWN, items, 50, 20)
    nav.key(K.KEY_ENTER, items, 50, 20)
    case("the graph starts at 24 h; + doubles it and - halves it, within 6 h and a week",
         nav.hours == 24 and nav.key(ord("+"), [], 9, 20) == "open" and nav.hours == 48
         and [nav.key(ord("-"), [], 9, 20) for _ in range(4)] and nav.hours == 6)
    case("+ does nothing outside the graph", (nav.key(K.KEY_BACKSPACE, [], 9, 20), nav.key(ord("+"), items, 9, 20))[1] is None)
    case("Backspace went back to the cursor it left", nav.view == ("home",) and nav.cur == 1)
    case("Esc on home stays home", nav.key(27, items, 50, 20) is None and nav.view == ("home",))
    nav.cur = len(items) - 1
    nav.fit(items, len(home), 10)
    case("the cursor's line is kept on screen", nav.top <= items[-1][0] < nav.top + 10)
    n = items[-1][0] + 25
    for _ in range(40):
        nav.key(K.KEY_DOWN, items, n, 10), nav.fit(items, n, 10)
    case("↓ past the last item scrolls home to its end, and fit leaves it there",
         nav.cur == len(items) - 1 and nav.top == n - 10)
    nav.key(K.KEY_UP, items, n, 10), nav.fit(items, n, 10)
    case("↑ scrolls back before the cursor moves", nav.cur == len(items) - 1 and nav.top == n - 11)
    fx = [(2, 0, 5, ("prs",)), (4, 0, 5, ("graph",)), (6, 0, 5, ("timeline",))]     # three items over 40 lines
    nav = Nav()
    nav.cur = 2
    nav.fit(fx, 40, 10)
    tops = [(nav.key(k, fx, 40, 10), nav.fit(fx, 40, 10), nav.top, nav.cur)[2:] for k in
            (K.KEY_NPAGE, K.KEY_NPAGE, K.KEY_PPAGE, K.KEY_PPAGE, K.KEY_PPAGE)]
    case("PgDn on the last item scrolls without moving it; PgUp scrolls back, then moves it",
         tops == [(10, 2), (20, 2), (10, 2), (0, 2), (0, 0)])
    nav = Nav()
    nav.cur = 2
    nav.fit(fx, 40, 10)
    nav.top = 20
    case("Enter on an item scrolled off screen brings it back and does not open it",
         nav.key(10, fx, 40, 10) is None and nav.view == ("home",) and nav.top == 0
         and nav.key(10, fx, 40, 10) == "open" and nav.view == ("timeline",))
    nav = Nav()
    nav.cur = 2
    nav.fit(fx, 40, 10)
    nav.top = 3
    nav.key(K.KEY_UP, fx, 40, 10)
    up = (nav.cur, nav.top)
    nav.cur, nav.top = 2, 20
    nav.key(K.KEY_UP, fx, 40, 10)
    case("↑ on the last item moves it at the first press while it shows, and scrolls only when it doesn't",
         up == (1, 3) and (nav.cur, nav.top) == (2, 19))
    nav = Nav()
    nav.cur = 2
    nav.fit(fx, 40, 10)
    moved = fx[:2] + [(8, 0, 5, ("timeline",))]
    nav.fit(moved, 40, 10)
    still = nav.top
    nav.top = 20
    nav.fit(moved, 40, 10)
    nav.fit(fx, 40, 10)
    case("a refresh that moves the cursor's line keeps the scroll past it, and leaves a visible cursor alone",
         still == 0 and nav.top == 18 and nav.cur == 2)

    class Screen:            # curses' window methods, over a dict: the whole navigable loop with no terminal
        def __init__(self, keys):
            self.keys, self.rows, self.hi, self.shots = list(keys), {}, [], []

        def keypad(self, on):
            pass

        def timeout(self, ms):
            pass

        def getmaxyx(self):
            return 40, 120

        def erase(self):
            self.rows, self.hi = {}, []

        def addstr(self, y, x, text, attr=0):
            ln = self.rows.get(y, "").ljust(x)
            self.rows[y] = ln[:x] + text + ln[x + len(text):]
            if attr == curses.A_REVERSE:
                self.hi.append(text)

        def refresh(self):
            self.shots.append(("\n".join(self.rows.get(y, "") for y in range(40)), self.hi))

        def getch(self):
            if not self.keys:
                raise KeyboardInterrupt
            return self.keys.pop(0)
    scr = Screen([K.KEY_RIGHT, K.KEY_RIGHT, 10, -1, 27, ord("q")])
    rc = ui(scr, 10, f"{tmp}/proc", clock=lambda: now)
    shots = [t for t, _ in scr.shots]
    case("the loop draws home with the cursor on the first view", scr.shots[0][1] == ["[ PRs landed ]"] and "HANDED OFF" in shots[0])
    case("→ → Enter opens the timeline, and its footer says how to go back",
         shots[3].startswith("TIMELINE") and "Esc/Backspace back" in shots[3] and scr.shots[3][1] == [])
    case("Esc brings home back with the cursor where it was, and q ends the loop with 0",
         scr.shots[-1][1] == ["[ timeline ]"] and "HANDED OFF" in shots[-1] and rc == 0)
    try:
        ui(Screen([K.KEY_DOWN]), 10, f"{tmp}/proc", clock=lambda: now)
        case("Ctrl-C leaves the loop", False)
    except KeyboardInterrupt:
        case("Ctrl-C leaves the loop", True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"cc-live selfcheck: {ok} passed, {bad} failed")
    return 1 if bad else 0
