# cc-room's selfcheck: the cases behind `cc-room selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-room execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    import shutil
    import tempfile
    n = bad = 0

    def t(name, got, want):
        nonlocal n, bad
        n += 1
        if got != want:
            bad += 1
            print(f"FAIL {name}: got {got!r}, want {want!r}")

    base = tempfile.mkdtemp(prefix="cc-room-sc.")
    keep = {k: os.environ.get(k) for k in ("CC_ROOM_DIR", "CC_STATUSLINE_DIR", "CC_WORKER_CAP",
                                          "CC_WORKER_PACE_MARGIN", "CC_ROOM_POLL", "CC_CONFIG", "LANDER_LOADAVG",
                                          "TMUX", "TMUX_PANE", "CC_SLACK_ALIAS", "CC_ROOM_TMUX", "CC_ROOM_BIN",
                                          "CC_ROOM_NOTICE_AFTER", "CC_HEAVY_CAP", "CC_HEAVY_SCOPE",
                                          "CC_ROOM_GRACE", "CC_ROOM_NOTICE_RETRY")}
    procs = []
    strays = []   # (pid, start) of what a stub window ran: ended in the finally only while still that process

    def stray(pid):
        strays.extend((x, starttime(x)) for x in tree(pid))

    # the box's own /proc/loadavg must never decide a case — give every fixture a calm one of its own,
    # in-process and in the subprocesses admit() and check spawn (LANDER_LOADAVG, read at import)
    calm = f"{base}/loadavg.calm"
    open(calm, "w").write("0.0 0.0 0.0 1/1 1\n")
    os.environ["LANDER_LOADAVG"] = calm
    old_loadavg = admission.LOADAVG
    admission.LOADAVG = calm

    def fixture(name, cap=2, margin=10):
        """a room and a statusline dir of this case's own, nothing held, nothing queued"""
        d = f"{base}/{name}"
        os.makedirs(f"{d}/sl")
        os.environ.update(CC_ROOM_DIR=f"{d}/room", CC_STATUSLINE_DIR=f"{d}/sl", CC_WORKER_CAP=str(cap),
                          CC_WORKER_PACE_MARGIN=str(margin), CC_ROOM_POLL="0.2", CC_CONFIG=f"{d}/config",
                          CC_ROOM_NOTICE_AFTER="3600", CC_HEAVY_CAP="1", CC_HEAVY_SCOPE="0", CC_ROOM_BIN=f"{d}/bin",
                          CC_ROOM_TMUX=f"{d}/bin/tmux", CC_ROOM_GRACE="1", CC_ROOM_NOTICE_RETRY="300")
        for k in ("TMUX", "TMUX_PANE", "CC_SLACK_ALIAS"):   # never the session's own tmux server or orch
            os.environ.pop(k, None)
        # stubs: the broker and cc-notify write down what they were told, and refuse while {d}/down exists; with
        # {d}/vanish, tmux's list-panes and new-window remove every queue entry, as a cancel in between would; tmux
        # writes each -S socket it is given to {d}/sockets, is "up" once {d}/up exists, lists the window names in
        # {d}/windows (with -a, the ids in {d}/winids), the pane pid in {d}/panepid, and a new window runs its command
        # in the background (unless {d}/nospawn), its pid in {d}/panepid, and prints its id and the server pid in {d}/srv
        os.makedirs(f"{d}/bin")
        for name, body in (("cc-broker", f'echo "$*" >> "{d}/told"; [ ! -e "{d}/down" ]'),
                           ("cc-notify", f'echo "notify $*" >> "{d}/told"; [ ! -e "{d}/down" ]'),
                           ("tmux", f'''if [ "$1" = -S ]; then echo "$2 $3" >> "{d}/sockets"; shift 2; fi
case "$1" in
  display-message) printf 'main\\t\\n' ;;
  has-session) [ -e "{d}/up" ] ;;
  list-windows) case " $* " in *" -a "*) cat "{d}/winids" 2>/dev/null; true ;; *) cat "{d}/windows" 2>/dev/null ;; esac ;;
  list-panes) [ -e "{d}/vanish" ] && for f in "{d}"/room/queue/*; do rm -f "$f"; done
              cat "{d}/panepid" 2>/dev/null; true ;;
  kill-window) echo "$*" >> "{d}/killed"; : > "{d}/windows"; : > "{d}/winids" ;;
  new-window) for a; do last=$a; done; echo "$*" >> "{d}/spawned"
              [ -e "{d}/vanish" ] && for f in "{d}"/room/queue/*; do rm -f "$f"; done
              if [ ! -e "{d}/nospawn" ]; then sh -c "$last" </dev/null >/dev/null 2>&1 & echo $! > "{d}/panepid"; fi
              echo "@7 $(cat "{d}/srv" 2>/dev/null || echo 0)" ;;
esac''')):
            open(f"{d}/bin/{name}", "w").write(f"#!/bin/sh\n{body}\n")
            os.chmod(f"{d}/bin/{name}", 0o755)
        return d

    def queued(what, tries=50):
        """the live queue entry of that launch, once its waiter has written it"""
        for _ in range(tries):
            hit = [p for p, (_, w) in live("queue").items() if w == what]
            if hit:
                return hit[0]
            time.sleep(0.1)
        return None

    def lines(path):
        return open(path).read().splitlines() if os.path.exists(path) else []

    def usage(d, used, left_s, name="s.json"):
        json.dump({"raw": {"rate_limits": {"five_hour": {"used_percentage": used,
                                                         "resets_at": int(time.time() + left_s)}}}},
                  open(f"{d}/sl/{name}", "w"))

    def holder(what):
        """a live process holding a slot, as an admitted loop does"""
        p = subprocess.Popen([sys.executable, __file__, "admit", what, "--", "sleep", "60"],
                             stderr=subprocess.DEVNULL)
        procs.append(p)
        for _ in range(50):
            if any(w == what for _, w in live("slots").values()):
                return p
            time.sleep(0.1)
        return p

    try:
        # room means it runs: nothing held, usage behind its clock
        d = fixture("room")
        usage(d, 20, 3 * 3600)   # 40% of the window gone, 20% used
        t("room: nothing held and usage behind the clock", why_not(), "")
        mark = f"{d}/ran"
        r = subprocess.run([sys.executable, __file__, "admit", "r/room", "--", "touch", mark], timeout=20,
                           capture_output=True)
        t("room: admit runs the launch at once", (r.returncode, os.path.exists(mark)), (0, True))

        # a simulated high load queues a new start, same as the lander's own overloaded() serializes on
        d = fixture("busy")
        hot = f"{base}/loadavg.hot"
        n = os.cpu_count() or 1
        open(hot, "w").write(f"{2.0 * n} 0.00 0.00 1/1 1\n")
        admission.LOADAVG = hot
        os.environ["LANDER_LOADAVG"] = hot
        t("busy: a high load average queues a new start", "the box is busy" in why_not(), True)
        t("busy: check exits 1 while the box is busy",
          subprocess.run([sys.executable, __file__, "check"], capture_output=True, text=True).returncode, 1)
        admission.LOADAVG = calm
        os.environ["LANDER_LOADAVG"] = calm
        t("busy: a calm load average is room again", why_not(), "")

        # cap reached means queued, and one under it is not
        d = fixture("cap", cap=2)
        holder("r/a")
        t("cap: one slot held of two is room", why_not(), "")
        holder("r/b")
        t("cap: two slots held of two is queued", why_not().startswith("2 worker loops are running and the cap is 2"),
          True)
        t("cap: check exits 1 with the reason",
          subprocess.run([sys.executable, __file__, "check"], capture_output=True, text=True).returncode, 1)

        # pace ahead means queued; at the margin exactly is room
        d = fixture("pace", margin=10)
        usage(d, 57, 3 * 3600)   # 2 h into 5 h = 40% gone; 57 > 40 + 10
        t("pace: 57% used with 40% of the window gone is queued", "57%" in why_not(), True)
        usage(d, 50, 3 * 3600)
        t("pace: 50% used at 40% gone and a margin of 10 is room", why_not(), "")
        usage(d, 90, -60)
        t("pace: a window that has already reset is room", why_not(), "")
        usage(d, 90, 3 * 3600, "old.json")
        os.utime(f"{d}/sl/old.json", (1, 1))
        usage(d, 10, 3 * 3600, "new.json")
        t("pace: the freshest file decides, not an older one", why_not(), "")
        os.unlink(f"{d}/sl/new.json")
        t("pace: …and with only the older one left it is queued", "90%" in why_not(), True)

        # the queued launch runs on its own once room frees, and not before
        d = fixture("frees", cap=1)
        h = holder("r/held")
        mark = f"{d}/ran"
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/queued", "--log", f"{d}/loop.log", "--",
                              "touch", mark], stderr=subprocess.DEVNULL)
        procs.append(w)
        time.sleep(1)
        t("frees: the queued launch has not run while the cap is held", os.path.exists(mark), False)
        t("frees: its log says it was queued and why",
          "r/queued queued — 1 worker loops are running" in open(f"{d}/loop.log").read(), True)
        h.kill()
        h.wait()
        w.wait(timeout=20)
        t("frees: it runs by itself once the slot is freed", os.path.exists(mark), True)
        t("frees: a finished launch holds no slot", live("slots"), {})

        # admit fails open: a room it cannot even create still runs the launch, and says so once
        d = fixture("crash")
        open(f"{d}/notadir", "w").close()
        os.environ["CC_ROOM_DIR"] = f"{d}/notadir/room"   # under a file: makedirs raises
        mark = f"{d}/ran"
        r = subprocess.run([sys.executable, __file__, "admit", "r/crash", "--log", f"{d}/loop.log", "--",
                            "touch", mark], timeout=20, capture_output=True)
        t("crash: admit that cannot make its room still runs the launch", (r.returncode, os.path.exists(mark)),
          (0, True))
        t("crash: …and its log says admission failed",
          "admission failed for r/crash" in open(f"{d}/loop.log").read(), True)

        # LOST: the brief's "a queued launch is still queued after a simulated restart" — the waiter and its tmux
        # server both die; the entry stays, out of the way, and `resume` puts it back in the same place
        d = fixture("restart", cap=1)
        h = holder("r/held")
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        mark = f"{d}/ran"
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/lost", "--log", f"{d}/loop.log", "--",
                              "touch", mark], env=dict(os.environ, TMUX=f"{d}/sock,{srv.pid},0", TMUX_PANE="%1"),
                             stderr=subprocess.DEVNULL)
        procs.append(w)
        e = queued("r/lost")
        t("restart: the waiter records the tmux server it waits in, and its socket",
          (read_entry(e).get("server"), read_entry(e).get("socket")) if e else None,
          ([str(srv.pid), starttime(srv.pid)], f"{d}/sock"))
        t("restart: …and asks THAT server for its pane's name, not the default one",
          f"{d}/sock display-message" in lines(f"{d}/sockets"), True)
        for p in (w, srv):   # the restart
            p.kill()
            p.wait()
        t("restart: the entry outlives its waiter and its tmux server", bool(e) and os.path.exists(e), True)
        t("restart: …and holds nobody up while it is down", live("queue"), {})
        t("restart: status calls it lost", "lost    r/lost" in subprocess.run(
            [sys.executable, __file__, "status"], capture_output=True, text=True).stdout, True)
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("restart: resume waits while tmux is not back", ("resumed" in r.stdout, os.path.exists(e)), (False, True))
        open(f"{d}/up", "w").close()
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("restart: once tmux is back, resume relaunches it in a window of its old name",
          "resumed r/lost in main:r/lost" in r.stdout, True)
        socks = lines(f"{d}/sockets")
        t("restart: every tmux call resume makes goes to the socket the waiter was on",
          (bool(socks), all(x.startswith(f"{d}/sock ") for x in socks),
           {x.split()[1] for x in socks} >= {"has-session", "list-windows", "new-window"}), (True, True, True))
        sp = (lines(f"{d}/spawned") or [""])[0]
        t("restart: the saved environment goes on -e, not into the window's command line",
          (f"-e CC_ROOM_DIR={d}/room" in sp, sp.count("CC_ROOM_DIR=")), (True, 1))
        t("restart: relaunched, it is queued again in the same entry", queued("r/lost"), e)
        t("restart: …and has not run while the cap is held", os.path.exists(mark), False)
        subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("restart: a second resume starts nothing more", len(lines(f"{d}/spawned")), 1)
        h.kill()
        h.wait()
        for _ in range(100):
            if os.path.exists(mark):
                break
            time.sleep(0.2)
        t("restart: it runs by itself once the slot is freed", os.path.exists(mark), True)

        # …and the case kept apart from it: a waiter whose tmux server is still up was ended on purpose
        d = fixture("killed", cap=1)
        holder("r/held")
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/killed", "--", "true"],
                             env=dict(os.environ, TMUX=f"{d}/sock,{srv.pid},0"), stderr=subprocess.DEVNULL)
        procs.append(w)
        e = queued("r/killed")
        w.kill()
        w.wait()
        t("killed: a killed waiter whose tmux server is up is out of the queue at once, its entry kept for the grace",
          (bool(e), live("queue"), bool(e) and os.path.exists(e)), (True, {}, True))
        time.sleep(1.2)
        t("killed: …and the entry goes once the grace is over with the server still up",
          (live("queue"), bool(e) and os.path.exists(e)), ({}, False))

        # a restart ends the waiter before its tmux server: a poll in between must not take it for a kill
        d = fixture("shutdown", cap=1)
        os.environ["CC_ROOM_GRACE"] = "60"
        holder("r/held")
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/slowdown", "--", "true"],
                             env=dict(os.environ, TMUX=f"{d}/sock,{srv.pid},0"), stderr=subprocess.DEVNULL)
        procs.append(w)
        e = queued("r/slowdown")
        w.kill()
        w.wait()
        t("shutdown: a poll while the server is still stopping keeps the entry",
          (live("queue"), bool(e) and os.path.exists(e)), ({}, True))
        srv.kill()
        srv.wait()
        t("shutdown: …and once the server is gone it is lost, for resume to start again",
          "lost    r/slowdown" in subprocess.run([sys.executable, __file__, "status"], capture_output=True,
                                                 text=True).stdout, True)

        # a relaunch whose admit never wrote leaves its own window open: the next resume closes it and starts again;
        # and an entry from before the socket was saved talks to the default server (no -S)
        d = fixture("relaunch", cap=1)
        holder("r/held")
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        open(f"{d}/srv", "w").write(str(srv.pid))
        open(f"{d}/up", "w").close()
        open(f"{d}/nospawn", "w").close()
        e = f"{d}/room/queue/1-2"
        json.dump({"pid": 1, "start": "0", "what": "r/stuck", "cmd": ["true"], "server": ["1", "0"],
                   "queued": time.time() - 60}, open(e, "w"))
        r1 = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        x = read_entry(e)
        t("relaunch: resume keeps the window it opened", x.get("opened"), ["@7", str(srv.pid), starttime(srv.pid)])
        x["relaunched"] -= 700   # its admit never wrote; the next tick comes
        json.dump(x, open(e, "w"))
        # the window still holds its waiter, stuck before it wrote (a fake cc-room that only sleeps), in its shell line
        open(f"{d}/windows", "w").write("r/stuck\n")
        open(f"{d}/winids", "w").write("@7\n")
        os.makedirs(f"{d}/fake")
        open(f"{d}/fake/cc-room", "w").write("import time\ntime.sleep(30)\n")
        pane = subprocess.Popen(["sh", "-c", f"{shlex.quote(sys.executable)} {d}/fake/cc-room admit --resume 1-2 "
                                 "r/stuck -- true; exec sh"], stdin=subprocess.DEVNULL)
        procs.append(pane)
        open(f"{d}/panepid", "w").write(str(pane.pid))
        time.sleep(0.5)
        stray(pane.pid)
        r2 = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("relaunch: the next resume closes its own window, still only its stuck waiter, and relaunches",
          ("resumed r/stuck" in r1.stdout, lines(f"{d}/killed"), "resumed r/stuck" in r2.stdout, os.path.exists(e)),
          (True, ["kill-window -t @7"], True, True))
        t("relaunch: an entry with no socket saved uses the default tmux server", lines(f"{d}/sockets"), [])
        t("relaunch: the waiter, its shell line and the idle shell count as the waiter's; nothing else does",
          [waiter_argv(a, "1-2") for a in (["bash"], ["-bash"], ["python3", "/x/cc-room", "admit", "--resume", "1-2"],
                                           ["bash", "-c", "/x/cc-room admit --resume 1-2 r/t -- cc-loop r t; exec bash"],
                                           ["sleep", "30"], ["python3", "/x/cc-room", "admit", "--resume", "1-3"],
                                           ["python3", "/x/cc-loop", "r", "t"], [])],
          [True, True, True, True, False, False, False, False])

        # the lander's input: a relaunched admit fails open and runs the launch. It drops its entry first, so the
        # next resume has nothing to act on: no kill of the running launch, no second one
        d = fixture("failopen", cap=1)
        holder("r/held")
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        open(f"{d}/srv", "w").write(str(srv.pid))
        open(f"{d}/up", "w").close()
        e = f"{d}/room/queue/1-4"
        json.dump({"pid": 1, "start": "0", "what": "r/fo", "cmd": ["sleep", "30"], "server": ["1", "0"],
                   "queued": time.time() - 60, "log": f"{d}/loop.log"}, open(e, "w"))
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True,
                           env=dict(os.environ, CC_ROOM_POLL="bad"))   # wait_for_room raises in the window
        for _ in range(100):
            if not os.path.exists(e) and "admission failed" in "".join(lines(f"{d}/loop.log")):
                break
            time.sleep(0.1)
        time.sleep(0.5)
        if lines(f"{d}/panepid"):
            stray(int(lines(f"{d}/panepid")[0]))
        ran = [proc_argv(x) for x, _ in strays if proc_argv(x) == ["sleep", "30"]]
        t("failopen: a relaunched admit that fails open drops its entry and runs the launch",
          ("resumed r/fo" in r.stdout, os.path.exists(e), bool(ran)), (True, False, True))
        open(f"{d}/windows", "w").write("r/fo\n")
        open(f"{d}/winids", "w").write("@7\n")
        subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("failopen: …and the next resume neither closes its window nor starts it again",
          (lines(f"{d}/killed"), len(lines(f"{d}/spawned"))), ([], 1))
        r = subprocess.run([sys.executable, __file__, "admit", "r/fo2", "--log", f"{d}/loop.log", "--", "true"],
                           env=dict(os.environ, CC_ROOM_POLL="bad"), capture_output=True, timeout=20)
        t("failopen: a fresh admit failing open after it queued runs CMD and leaves no entry at the FIFO's head",
          (r.returncode, sorted(os.listdir(f"{d}/room/queue"))), (0, []))
        r = subprocess.run([sys.executable, __file__, "heavy", "--name", "h", "--", "true"],
                           env=dict(os.environ, CC_ROOM_POLL="bad"), capture_output=True, timeout=20)
        t("failopen: …and so does a heavy run",
          (r.returncode, sorted(os.listdir(f"{d}/room/heavy-queue"))), (0, []))

        # belt and braces: the fail-open could not drop the entry (a full disk), so the entry is still lost and
        # names the window. resume looks first, finds the launch running there, and drops the entry instead
        d = fixture("guard", cap=1)
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        open(f"{d}/up", "w").close()
        os.makedirs(f"{d}/room/queue")
        e = f"{d}/room/queue/1-5"
        json.dump({"pid": 1, "start": "0", "what": "r/guard", "cmd": ["sleep", "30"], "server": ["1", "0"],
                   "queued": time.time() - 60, "log": f"{d}/loop.log", "relaunched": time.time() - 700,
                   "opened": ["@7", str(srv.pid), starttime(srv.pid)]}, open(e, "w"))
        if os.geteuid() != 0:   # root unlinks in a read-only directory: this needs a plain user
            os.chmod(f"{d}/room/queue", 0o500)
            pane = subprocess.Popen(["sh", "-c", f"{shlex.quote(sys.executable)} {shlex.quote(__file__)} admit --resume "
                                     f"1-5 --log {d}/loop.log r/guard -- sleep 30; exec sh"], stdin=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            procs.append(pane)
            for _ in range(100):
                if "could not drop" in "".join(lines(f"{d}/loop.log")):
                    break
                time.sleep(0.1)
            time.sleep(0.5)
            os.chmod(f"{d}/room/queue", 0o700)
            stray(pane.pid)
            t("guard: a fail-open that cannot drop its entry says so and runs the launch",
              (os.path.exists(e), "could not drop" in "".join(lines(f"{d}/loop.log")),
               any(proc_argv(x) == ["sleep", "30"] for x, _ in strays)), (True, True, True))
            open(f"{d}/panepid", "w").write(str(pane.pid))
            open(f"{d}/winids", "w").write("@7\n")
            r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
            t("guard: resume never closes a window its launch runs in, starts no second one, and drops the entry",
              (lines(f"{d}/killed"), lines(f"{d}/spawned"), os.path.exists(e), "already runs in window @7" in r.stdout),
              ([], [], False, True))
        # and a window it cannot read is left alone, with the entry
        json.dump({"pid": 1, "start": "0", "what": "r/unsure", "cmd": ["true"], "server": ["1", "0"],
                   "queued": time.time() - 60, "relaunched": time.time() - 700,
                   "opened": ["@7", str(srv.pid), starttime(srv.pid)]}, open(f"{d}/room/queue/1-6", "w"))
        open(f"{d}/winids", "w").write("@7\n")
        open(f"{d}/panepid", "w").close()   # list-panes answers nothing
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("guard: a window resume cannot read is not closed, and nothing is started or dropped",
          (lines(f"{d}/killed"), lines(f"{d}/spawned"), os.path.exists(f"{d}/room/queue/1-6"),
           "cannot tell what runs" in r.stdout), ([], [], True, True))

        # resume runs its tmux calls outside the room lock: one at a time, and a cancel in between is never undone
        d = fixture("race", cap=1)
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        open(f"{d}/srv", "w").write(str(srv.pid))
        open(f"{d}/up", "w").close()
        open(f"{d}/nospawn", "w").close()
        os.makedirs(f"{d}/room/queue")
        e = f"{d}/room/queue/1-8"
        rec = {"pid": 1, "start": "0", "what": "r/race", "cmd": ["true"], "server": ["1", "0"], "queued": time.time()}
        json.dump(rec, open(e, "w"))
        with open(f"{d}/room/.resume.lock", "w") as one:
            fcntl.flock(one, fcntl.LOCK_EX)
            r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("race: a second resume while one runs starts nothing",
          ("another cc-room resume is running" in r.stdout, lines(f"{d}/spawned")), (True, []))
        open(f"{d}/vanish", "w").close()
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("race: an entry cancelled while its window opened is not written back",
          ("its entry changed meanwhile" in r.stdout, os.path.exists(e)), (True, False))
        json.dump(dict(rec, relaunched=time.time() - 700, opened=["@7", str(srv.pid), starttime(srv.pid)]),
                  open(e, "w"))
        open(f"{d}/winids", "w").write("@7\n")
        os.makedirs(f"{d}/fake")
        open(f"{d}/fake/cc-room", "w").write("import time\ntime.sleep(30)\n")
        pane = subprocess.Popen(["sh", "-c", f"{shlex.quote(sys.executable)} {d}/fake/cc-room admit --resume 1-8 r/race "
                                 "-- true; exec sh"], stdin=subprocess.DEVNULL)
        procs.append(pane)
        open(f"{d}/panepid", "w").write(str(pane.pid))
        time.sleep(0.5)
        stray(pane.pid)
        t("race: (the fixture) the window holds only its waiter", window_state(tmux(), "@7", "1-8"), "waiter")
        json.dump(dict(rec, relaunched=time.time() - 700, opened=["@7", str(srv.pid), starttime(srv.pid)]),
                  open(e, "w"))   # the probe above ran the vanish hook
        n0 = len(lines(f"{d}/spawned"))
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("race: a waiter window whose entry was cancelled after it was looked at is not closed",
          (lines(f"{d}/killed"), len(lines(f"{d}/spawned")) - n0, os.path.exists(e)), ([], 0, False))

        # admit --resume of an entry whose waiter is alive (a fresh --go adopted it first) starts nothing
        d = fixture("twice", cap=1)
        os.makedirs(f"{d}/room/queue")
        json.dump({"pid": os.getpid(), "start": starttime(os.getpid()), "what": "r/twice", "cmd": ["true"]},
                  open(f"{d}/room/queue/1-3", "w"))
        mark = f"{d}/ran"
        r = subprocess.run([sys.executable, __file__, "admit", "--resume", "1-3", "--log", f"{d}/loop.log", "r/twice",
                            "--", "touch", mark], capture_output=True, timeout=20)
        t("twice: admit --resume of an entry already waiting starts nothing",
          (r.returncode, os.path.exists(mark), "already waiting" in "".join(lines(f"{d}/loop.log"))), (0, False, True))

        # a fresh `cc … --go` of a track a restart left queued takes over its entry instead of queueing twice
        d = fixture("adopt", cap=1)
        holder("r/held")
        os.makedirs(f"{d}/room/queue", exist_ok=True)
        old = f"{d}/room/queue/1-1"
        json.dump({"pid": 1, "start": "0", "what": "r/again", "cmd": ["true"], "server": ["1", "0"],
                   "queued": time.time() - 60}, open(old, "w"))
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/again", "--", "true"], stderr=subprocess.DEVNULL)
        procs.append(w)
        t("adopt: a new launch of a lost track waits in the lost entry's place", queued("r/again"), old)

        # NOTICE: a wait past the bound tells the seat that dispatched it, once; a wait under it tells nobody
        d = fixture("notice", cap=1)
        os.environ["CC_ROOM_NOTICE_AFTER"] = "1"
        holder("r/held")
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/slow", "--log", f"{d}/loop.log", "--", "true"],
                             env=dict(os.environ, CC_SLACK_ALIAS="comms"), stderr=subprocess.DEVNULL)
        procs.append(w)
        time.sleep(3)
        told = lines(f"{d}/told")
        t("notice: a wait past the bound produces one notice", len(told), 1)
        t("notice: …to the orch that dispatched it, saying why and how to cancel",
          bool(told) and told[0].startswith("inject --no-start --source room r@comms r/slow has waited")
          and "cc-room cancel r/slow" in told[0], True)
        t("notice: …and the loop log says who was told", "told r@comms" in open(f"{d}/loop.log").read(), True)
        d = fixture("scratch")
        notice(f"_cctest{os.getpid()}/t", {"queued": time.time() - 7200, "target": "r@comms"}, "x", f"{d}/loop.log")
        t("notice: a suite's scratch launch (cc-board's FIXTURE prefix) tells nobody, and the log says so",
          (lines(f"{d}/told"), "told nobody (a test namespace)" in open(f"{d}/loop.log").read()), ([], True))
        d = fixture("quiet", cap=1)
        holder("r/held")
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/brief", "--", "true"], stderr=subprocess.DEVNULL)
        procs.append(w)
        time.sleep(1.5)
        t("notice: a wait under the bound tells nobody", (bool(queued("r/brief")), lines(f"{d}/told")), (True, []))

        # a notice nobody took is tried again, with a growing wait, and is not taken for one delivered
        d = fixture("retry", cap=1)
        os.environ.update(CC_ROOM_NOTICE_AFTER="1", CC_ROOM_NOTICE_RETRY="0.3")
        open(f"{d}/down", "w").close()   # the broker and cc-notify both refuse
        holder("r/held")
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/late", "--log", f"{d}/loop.log", "--", "true"],
                             env=dict(os.environ, CC_SLACK_ALIAS="comms"), stderr=subprocess.DEVNULL)
        procs.append(w)
        e = queued("r/late")
        time.sleep(2.5)
        x = read_entry(e) if e else {}
        t("retry: a refused notice is tried again, and the entry does not call it delivered",
          (len(lines(f"{d}/told")) >= 4, "could not tell anyone" in "".join(lines(f"{d}/loop.log")),
           x.get("noticed"), x.get("notice_tries", 0) >= 2), (True, True, False, True))
        os.unlink(f"{d}/down")
        for _ in range(100):
            if "told r@comms" in "".join(lines(f"{d}/loop.log")):
                break
            time.sleep(0.1)
        n1 = len(lines(f"{d}/told"))
        time.sleep(1.5)
        t("retry: once the broker takes it, it is delivered once and tried no more",
          ("told r@comms" in "".join(lines(f"{d}/loop.log")), len(lines(f"{d}/told")) - n1,
           bool(e) and read_entry(e).get("noticed")), (True, 0, True))

        # status's sweep runs under the room lock, and its settling stamp never writes back an entry a cancel removed
        d = fixture("settle", cap=1)
        os.environ["CC_ROOM_GRACE"] = "60"
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        os.makedirs(f"{d}/room/queue")
        e = f"{d}/room/queue/1-7"
        stale = {"pid": 1, "start": "0", "what": "r/gone", "cmd": ["true"], "server": [str(srv.pid), starttime(srv.pid)],
                 "queued": time.time()}
        json.dump(stale, open(e, "w"))
        os.unlink(e)   # the cancel, after the sweep had read the entry
        t("settle: a stamp from a stale read does not bring a cancelled entry back",
          (settling(e, dict(stale)), os.path.exists(e)), (False, False))
        json.dump(stale, open(e, "w"))
        with Lock():
            s = subprocess.Popen([sys.executable, __file__, "status"], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            procs.append(s)
            time.sleep(1)
            t("settle: status waits for the room lock before it sweeps",
              (s.poll(), "dead_seen" in read_entry(e)), (None, False))
            os.unlink(e)   # cancel, holding the lock
        s.wait(timeout=30)
        t("settle: …and then finds the cancelled entry gone instead of writing it back", os.path.exists(e), False)

        # a queue entry keeps only what a relaunch needs: never a token from the environment
        d = fixture("env", cap=1)
        holder("r/held")
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/env", "--", "true"], stderr=subprocess.DEVNULL,
                             env=dict(os.environ, CC_SLACK_TOKEN="xoxb-sc-secret", CC_GH_TOKEN="ghp-sc-secret",
                                      LANDER_API_KEY="sc-key", CC_WORKER_MODEL="opus"))
        procs.append(w)
        e = queued("r/env")
        env = (read_entry(e).get("env") or {}) if e else {}
        t("env: no CC_*_TOKEN or key is written into the entry; what the relaunch needs is",
          (sorted(k for k in env if "TOKEN" in k or "KEY" in k), "sc-secret" in (open(e).read() if e else ""),
           env.get("CC_WORKER_MODEL"), env.get("CC_ROOM_DIR")), ([], False, "opus", f"{d}/room"))
        cc = f"{BIN}/cc"
        m = re.search(r"for v in (CC_[A-Z_ ]+); do", open(cc).read()) if os.path.exists(cc) else None
        t("env: every key `cc … --go` carries into a worker's window is one a relaunch carries too",
          sorted(set(m.group(1).split()) - set(RELAUNCH_ENV)) if m else "cc's list not found", [])

        # CANCEL: the dispatching seat drops a queued launch; it exits without running, and nothing is killed
        d = fixture("cancel", cap=1)
        holder("r/held")
        mark = f"{d}/ran"
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/drop", "--log", f"{d}/loop.log", "--",
                              "touch", mark], stderr=subprocess.DEVNULL)
        procs.append(w)
        queued("r/drop")
        r = subprocess.run([sys.executable, __file__, "cancel", "r/drop"], capture_output=True, text=True)
        t("cancel: a queued launch is cancelled", r.returncode, 0)
        t("cancel: …its waiter exits 0 on its own without running it", (w.wait(timeout=10), os.path.exists(mark)),
          (0, False))
        t("cancel: …and its log says so", "r/drop was cancelled" in open(f"{d}/loop.log").read(), True)
        t("cancel: …and its tombstone is gone with it", os.listdir(f"{d}/room/cancelled"), [])
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/keep", "--", "touch", mark],
                             stderr=subprocess.DEVNULL)
        procs.append(w)
        e = queued("r/keep")
        os.unlink(e)   # what a waiter on the older code does to a JSON entry: not a cancel
        t("cancel: an entry gone with no tombstone is written again, not taken for a cancel",
          queued("r/keep"), e)
        t("cancel: nothing queued for it is exit 1",
          subprocess.run([sys.executable, __file__, "cancel", "r/drop"], capture_output=True).returncode, 1)

        # HEAVY: a heavy run waits for a heavy slot, takes no worker slot, and runs in its scope
        d = fixture("heavy", cap=1)
        h = subprocess.Popen([sys.executable, __file__, "heavy", "--name", "anneal-a", "--", "sleep", "60"],
                             stderr=subprocess.DEVNULL)
        procs.append(h)
        for _ in range(50):
            if live("heavy"):
                break
            time.sleep(0.1)
        mark = f"{d}/ran"
        w = subprocess.Popen([sys.executable, __file__, "heavy", "--name", "anneal-b", "--", "touch", mark],
                             stderr=subprocess.DEVNULL)
        procs.append(w)
        time.sleep(1)
        t("heavy: a heavy run waits while the heavy cap is held", os.path.exists(mark), False)
        t("heavy: …and heavy runs take no worker slot", why_not(), "")
        h.kill()
        h.wait()
        w.wait(timeout=20)
        t("heavy: it runs once the heavy slot frees", os.path.exists(mark), True)
        a = heavy_argv("place anneal", ["anneal", "x"], True)
        t("heavy: scoped, it runs directly in app.slice, beside the sessions' scopes, with its CPU weight",
          (a[:3], "--slice=app.slice" in a, "CPUWeight=1000" in a, a[-3:]),
          (["systemd-run", "--user", "--scope"], True, True, ["--", "anneal", "x"]))
        # CC_HEAVY_SCOPE unset: the lander's scope_available() decides, here against a stubbed systemd-run and bus
        d = fixture("scope")
        os.makedirs(f"{d}/rt")
        open(f"{d}/rt/bus", "w").close()
        open(f"{d}/bin/systemd-run", "w").write(f'#!/bin/sh\necho "$*" > "{d}/scoped"\n'
                                                'while [ "$1" != -- ]; do shift; done; shift; exec "$@"\n')
        os.chmod(f"{d}/bin/systemd-run", 0o755)
        env = {k: v for k, v in os.environ.items() if k not in ("CC_HEAVY_SCOPE", "LANDER_SCOPE")}
        env.update(PATH=f"{d}/bin:{os.environ.get('PATH', '')}", XDG_RUNTIME_DIR=f"{d}/rt")
        mark = f"{d}/ran"
        r = subprocess.run([sys.executable, __file__, "heavy", "--name", "anneal-s", "--", "touch", mark], env=env,
                           capture_output=True, text=True, timeout=20)
        t("heavy: with no CC_HEAVY_SCOPE and a user bus it runs CMD through systemd-run in app.slice",
          (r.returncode, os.path.exists(mark), "--slice=app.slice" in " ".join(lines(f"{d}/scoped")),
           "admission failed" in r.stderr), (0, True, True, False))
        t("heavy: unscoped, it runs CMD as it is", heavy_argv("x", ["anneal"], False), ["anneal"])
    finally:
        admission.LOADAVG = old_loadavg
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait()
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for pid, st in strays:   # what the stub windows ran, while it is still that process
            if st and starttime(pid) == st:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
        shutil.rmtree(base, ignore_errors=True)
    print(f"cc-room selfcheck: {n - bad} passed, {bad} failed")
    return 1 if bad else 0
