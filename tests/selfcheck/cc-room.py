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
                                          "CC_WORKER_PACE_MARGIN", "CC_ROOM_POLL", "CC_CONFIG", "LANDER_LOADAVG")}
    procs = []

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
                          CC_WORKER_PACE_MARGIN=str(margin), CC_ROOM_POLL="0.2", CC_CONFIG=f"{d}/config")
        return d

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
        shutil.rmtree(base, ignore_errors=True)
    print(f"cc-room selfcheck: {n - bad} passed, {bad} failed")
    return 1 if bad else 0
