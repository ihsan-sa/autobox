# cc-vitals's selfcheck: the cases behind `cc-vitals selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-vitals execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    """Everything that does not need pixels, proved: the two aggregations, the normalisation, the gaps, the
    palette rules and the seam. Runs in a temp dir — the live vitals are never read or written."""
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="cc-vitals-")
    live, globals()["DIR"] = DIR, tmp
    n = [0, 0]

    def check(name, ok):
        n[0 if ok else 1] += 1
        print(f"  {'OK' if ok else 'XX'} {name}")

    try:
        # -- COUNTERS: the delta across the minute IS the minute's mean, so these are exact, not sampled ------
        c0 = {"cpu": (1000, 800), "uj": 1_000_000, "wrap": 262_143_328_850}
        c1 = {"cpu": (2000, 1050), "uj": 601_000_000, "wrap": 262_143_328_850}
        r = aggregate(c0, c1, 60.0, [gauges()], CAP, 0)
        check("counter CPU: 1000 ticks, 250 idle -> exactly 75% busy for the minute", r["cpu"] == 75.0)
        check("counter power: 600 J over 60 s -> exactly 10.0 W", r["watts"] == 10.0)
        check("a counter reset mid-minute, as a restart does, drops the figure instead of drawing a spike",
              cpu_pct({"cpu": (2000, 1050)}, {"cpu": (10, 5)}) is None)
        w = {"cpu": None, "uj": 500_000, "wrap": 262_143_328_850}
        check("RAPL wrap is added back, not thrown away",
              watts({"cpu": None, "uj": 262_143_000_000, "wrap": 262_143_328_850}, w, 60.0) is not None)
        check("a wrap we cannot size is dropped rather than invented",
              watts({"cpu": None, "uj": 262_143_000_000, "wrap": None}, w, 60.0) is None)

        # -- GAUGES: mean AND max, because the mean hides the spike the owner asked to see ---------------------
        g = [{"ram": 4.0, "load": 1.0, "temp": 45.0, "disk": 49.0},
             {"ram": 6.0, "load": 3.0, "temp": 79.0, "disk": 49.0},
             {"ram": 5.0, "load": 2.0, "temp": 41.0, "disk": 49.0}]
        r = aggregate(c0, c1, 60.0, g, CAP, 0)
        check("gauge mean is the mean of the minute's samples, not one lucky read", r["temp"]["m"] == 55.0)
        check("the minute that averaged 55 C but touched 79 C keeps the 79", r["temp"]["x"] == 79.0)
        check("RAM keeps its max too", r["ram"]["x"] == 6.0)
        check("a sensor this box does not have is None, not a zero on the chart",
              aggregate(c0, c1, 60.0, [{"ram": 4.0, "load": 1.0, "disk": 9.0, "temp": None}], CAP, 0)["temp"] is None)

        # -- NORMALISATION: six capacities, one 0-100 axis -----------------------------------------------------
        check("load 3.00 on 6 cores is 50% of the box", norm("load", 3.0, CAP) == 50.0)
        check("55 C against a 100 C throttle is 55%", norm("temp", 55.0, CAP) == 55.0)
        check("17.5 W against a 35 W package limit is 50%", norm("watts", 17.5, CAP) == 50.0)
        check("49 G of 457 G is 10.72%", norm("disk", 49.0, CAP) == 10.72)
        check("the legend carries the real number, so the axis can be a percentage",
              text("ram", 4.3, CAP) == "4.3/31G" and text("temp", 55.0, CAP) == "55°C")
        check("load over the core count is NOT clamped - a box over its limit must be able to say so",
              norm("load", 9.0, CAP) == 150.0)
        s = build(0.05, now=600, data=[_row(600 - 60, load=9.0)])
        check("...and the series is flagged `over` for the renderer to mark",
              [x for x in s["series"] if x["key"] == "load"][0]["over"] is True)

        # -- REAL UNITS ON DISK: capacity changes re-scale the picture, they do not rewrite history ------------
        big = dict(CAP, disk_gb=914.0)
        s = build(0.05, now=600, data=[_row(600 - 120, cap=CAP), _row(600 - 60, cap=big)])
        d = [x for x in s["series"] if x["key"] == "disk"][0]
        check("a row is normalised against the capacity IT recorded: disk grew, same 49 G, half the %",
              d["norm"][-2] == 10.72 and d["norm"][-1] == 5.36 and d["real"][-1] == 49.0)

        # -- GAPS: a power cut is a break in the line, never a line drawn through the dark ---------------------
        s = build(0.05, now=600, data=[_row(600 - 180), _row(600 - 60)])
        c = [x for x in s["series"] if x["key"] == "cpu"][0]
        check("a minute with no row is a null on a dense axis, not an interpolation",
              c["norm"] == [None, 10.0, None, 10.0])
        check("the axis ends on the last COMPLETE minute, so a chart never opens with a trailing gap",
              s["t0"] + (s["n"] - 1) * s["step"] == 540)
        check("the payload says how much of the window is missing", s["gaps"] == 2 and s["minutes"] == 2)
        check("`now` is the newest minute that has data", c["now"]["real"] == 10.0)

        # -- a metric with no honest denominator gets no line --------------------------------------------------
        s = build(0.05, now=600, data=[_row(600 - 60, cap=dict(CAP, watts=None))])
        check("no package power limit -> no watts line, rather than a guessed one",
              not [x for x in s["series"] if x["key"] == "watts"])

        # -- PALETTE: one fixed hue per metric, in a fixed order, never recycled -------------------------------
        hues = [x["hue"] for x in SPEC]
        check("six metrics, six hues, no hue used twice", len(hues) == len(set(hues)) == 6)
        check("slots are the fixed published order 1..6, never reassigned",
              [x["slot"] for x in SPEC] == [1, 2, 3, 4, 5, 6])
        check("no series is identified by colour alone: every one has a label and its own dash",
              all(x["label"] and x["dash"] for x in SPEC) and len({x["dash"] for x in SPEC}) == 6)
        check("the surface is chosen, not flipped: one opaque image for both Slack themes",
              SURFACE["mode"] == "dark" and SURFACE["bg"].startswith("#"))
        s = build(0.05, now=600, data=[_row(600 - 60)])
        check("every series ships both surfaces' hex, so the seam never has to pick a colour",
              all(x["colour"] and x["light"] for x in s["series"]))
        check("temperature and RAM carry the max band the owner asked for; the others do not",
              all((x["norm_max"] is not None) == (x["key"] in ("temp", "ram")) for x in s["series"]))

        # -- THE CLOCK: the picture is for the owner, the rows behind it are for machines -----------------------
        _tz, INSTANT = os.environ.get("CC_TZ"), 1788274921       # 2026-09-01 15:02 UTC = 2026-09-02 00:02 in Tokyo
        try:
            os.environ["CC_TZ"] = "Asia/Tokyo"                   # a zone of its own, never this box's: the DAY moves too
            label = dt.datetime.fromtimestamp(INSTANT, chart_tz()).strftime("%H:%M")
        finally:
            os.environ.pop("CC_TZ", None) if _tz is None else os.environ.__setitem__("CC_TZ", _tz)
        check("the chart's axis is labelled in the owner's zone with no Z — the PNG goes to Slack, and a UTC axis "
              "is what the owner was reading off it (2026-09-01)",
              label == "00:02" and "Z" not in label)
        check("...while the row that minute is recorded under is still UTC and still ends in Z",
              _iso(INSTANT) == "2026-09-01T15:02:00Z")

        # -- THE SEAM (closed 2026-08-31: the owner approved the install, so the renderer is real) --------------
        png = render_png(s, f"{tmp}/x.png")
        check("the PNG backend returns real PNG BYTES — put() does the atomic rename, so a tab reading while we "
              "write never sees half a chart",
              isinstance(png, bytes) and png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 4000)
        t = render_text(s, 20)
        check("the text chart still works, and is what a box with no library gets", "CPU" in t and "temp" in t)
        check("...and labels each line with its real number", "/457G" in t)
        wrote, why = render("auto")
        check("render writes the data payload whether or not a chart can be drawn", "current.json" in wrote)
        check("auto draws the picture AND keeps the text one beside it — the text is what shows while a fresh "
              "image is being made, and in the first hour after a boot",
              "current.png" in wrote and "current.txt" in wrote and not why)
        _mpl = sys.modules.get("matplotlib")                  # a box WITHOUT the library must still degrade, not raise
        sys.modules["matplotlib"] = None
        try:
            wrote2, why2 = render("auto")
        finally:
            sys.modules["matplotlib"] = _mpl if _mpl is not None else sys.modules.pop("matplotlib", None)
        check("no library: it falls back to the text chart and says why, instead of raising",
              "current.txt" in wrote2 and "matplotlib" in why2)
        check("current.json is valid JSON with a dense axis", json.load(open(f"{tmp}/current.json"))["step"] == 60)
        check("nothing is left half-written: temp files are renamed into place", not glob.glob(f"{tmp}/.*.tmp"))

        # -- --if-stale: the flag that keeps a tab's picture honest without redrawing it every tick -------------
        check("a fresh picture is NOT redrawn: --if-stale skips, and says so by writing nothing",
              render("auto", if_stale=3600) == ([], ""))
        old_t = drawn_at()
        os.utime(f"{tmp}/current.png", (old_t - 7200, old_t - 7200))
        os.utime(f"{tmp}/current.json", (old_t - 7200, old_t - 7200))
        check("a stale one IS redrawn — this is the bug that left current.png four hours behind the data",
              "current.png" in render("auto", if_stale=300)[0] and drawn_at() > old_t - 60)
        check("drawn_at reports the age of the drawing itself, which is what a tab must show when it is old",
              drawn_at() > 0 and fresh(300) and not fresh(0.0001))
        check("a picture that was never drawn is not silently 'now'", drawn_at("nosuch.png") == 0.0)

        # -- STORAGE -------------------------------------------------------------------------------------------
        append(_row(600))
        append(_row(660))
        check("rows append one JSON line per minute to that UTC day's file",
              len(_read(f"{tmp}/1970-01-01.jsonl").splitlines()) == 2)
        open(f"{tmp}/2000-01-01.jsonl", "w").write("{}\n")
        open(f"{tmp}/{_day(time.time())}.jsonl", "a").write("not json\n")
        prune()
        check("days past KEEP_DAYS are pruned, today's is kept",
              not os.path.exists(f"{tmp}/2000-01-01.jsonl") and os.path.exists(f"{tmp}/{_day(time.time())}.jsonl"))
        check("a half-written last line is skipped, it does not take the chart down", isinstance(rows(24), list))

        # -- THE RESOLVER, stubbed: a reading like the others, and the log hears a FLIP only -----------------------
        def stub(body):                                          # a fake `getent hosts <host>`; $2 is the host
            path = f"{tmp}/getent"
            with open(path, "w") as f:
                f.write("#!/bin/sh\n" + body + "\n")
            os.chmod(path, 0o755)
            return path
        said, live_getent, live_alert = [], GETENT, alert
        globals()["alert"] = said.append
        try:
            globals()["GETENT"] = stub("exit 0")
            r = dns()
            check("both hosts answer -> a ms reading per host, kept in the row like the other readings",
                  set(r) == set(HOSTS) and all(isinstance(v, int) for v in r.values()))
            check("up, and was up: nothing said, no state file", not watch({"dns": r}) and not said
                  and not os.path.exists(f"{tmp}/dns.json"))
            globals()["GETENT"] = stub('[ "$2" = github.com ] && exit 2; exit 0')
            r = dns()
            check("a failed lookup is None, not a number", r["github.com"] is None and r["slack.com"] is not None)
            check("ONE down tick is a slow lookup, not an outage: remembered on disk, nothing said",
                  not watch({"dns": r}) and not said and json.loads(_read(f"{tmp}/dns.json")).get("since"))
            globals()["GETENT"] = stub("exit 2")
            r = dns()
            check("the SAME host missing on the SECOND tick in a row is the DOWN flip, and it names that host only",
                  watch({"dns": r}) and len(said) == 1 and "down" in said[0]
                  and "github.com" in said[0] and "slack.com" not in said[0])
            check("still down: NO repeat — an outage is one line, not one a minute",
                  dns_flip(r, now=time.time() + 60) is None and dns_flip(r, now=time.time() + 120) is None
                  and not watch({"dns": r}) and len(said) == 1)
            globals()["GETENT"] = stub("sleep 5")
            t = time.monotonic()
            check("a HUNG resolver is None after the timeout, not a hung recorder",
                  resolve("github.com", timeout=0.3) is None and time.monotonic() - t < 2)
            globals()["GETENT"] = stub("exit 0")
            r = dns()
            up = dns_flip(r, now=time.time() + 240)
            check("back: the UP flip once, carrying the outage length and every host that was out",
                  bool(up) and "back after 4 min" in up and "github.com, slack.com" in up)
            check("...and the state is cleared, so the next blip is a new outage, not a repeat",
                  dns_flip(r) is None and json.loads(_read(f"{tmp}/dns.json")) == {})
            globals()["GETENT"] = stub('[ "$2" = slack.com ] && exit 2; exit 0')
            check("a lone slow tick, the kind there were nineteen of a day: still nothing said",
                  not watch({"dns": dns()}) and len(said) == 1)
            globals()["GETENT"] = stub("exit 0")
            check("...and it clears itself quietly: no 'back' for an outage nobody was told about",
                  not watch({"dns": dns()}) and len(said) == 1
                  and json.loads(_read(f"{tmp}/dns.json")) == {})
            # two misses on adjacent ticks, a DIFFERENT host each time, are two slow lookups (review of #221)
            globals()["GETENT"] = stub('[ "$2" = github.com ] && exit 2; exit 0'); watch({"dns": dns()})
            globals()["GETENT"] = stub('[ "$2" = slack.com ] && exit 2; exit 0')
            check("a different host missing on the next tick is not an outage either: nothing said, the clock restarts",
                  not watch({"dns": dns()}) and len(said) == 1
                  and json.loads(_read(f"{tmp}/dns.json")).get("hosts") == ["slack.com"])
            globals()["GETENT"] = stub("exit 0"); watch({"dns": dns()})
            # state the previous binary wrote mid-outage has no `told`: it HAD announced, so the recovery is still said
            _save("dns.json", {"since": time.time() - 300, "hosts": ["github.com"]})
            up = dns_flip(dns())
            check("state from before this rule (no `told`) reads as announced: the UP flip is still said, once",
                  bool(up) and "back after 5 min" in up and "github.com" in up
                  and json.loads(_read(f"{tmp}/dns.json")) == {})
        finally:
            globals()["GETENT"], globals()["alert"] = live_getent, live_alert
        # the door itself: a flip is a log line now, never a Slack post — cc-notify is not even on the path
        alert("dns back after 1 min (_selfcheck)")
        events = _read(f"{tmp}/events.log")
        check("a flip is appended to events.log, UTC-stamped, not sent through cc-notify",
              bool(re.search(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\tdns back after 1 min \(_selfcheck\)$",
                              events, re.M))
              and not os.path.exists(f"{tmp}/notify.log"))

        # -- THE MAIN CHECKOUT, on a throwaway clone: clean is silence, anything else is one line, back is one ---
        genv = dict(os.environ, HOME=tmp, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
                    GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

        def g(*a, cwd=None):
            subprocess.run(["git", *a], cwd=cwd, env=genv, check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)

        def commit(repo, name, body):
            with open(f"{repo}/{name}", "w") as fh:
                fh.write(body)
            g("add", "-A", cwd=repo)
            g("commit", "-qm", name, cwd=repo)
        origin, box = f"{tmp}/origin", f"{tmp}/dev/box"
        g("init", "-q", "-b", "main", origin)
        commit(origin, "f", "one\n")
        os.makedirs(f"{box}")
        g("clone", "-q", origin, box)
        os.makedirs(f"{box}/core/bin")                           # where this script would live in it
        said.clear()
        globals()["alert"] = said.append
        try:
            r = checkout(f"{box}/core/bin")
            check("a clean clone, read from a dir inside it as ~/bin -> <repo>/core/bin is: on the default branch, "
                  "nothing modified, level with origin", bool(r) and r["top"] == box and r["branch"] == r["default"]
                  == "main" and r["dirty"] == [] and r["ahead"] == r["behind"] == 0)
            check("clean, was clean: nothing said, no state file", not watch({"checkout": r}) and not said
                  and not os.path.exists(f"{tmp}/checkout.json"))
            with open(f"{box}/f", "w") as fh:
                fh.write("overwritten\n")
            with open(f"{box}/scratch", "w") as fh:
                fh.write("x")
            r = checkout(box)
            check("a tracked file rewritten in place is dirty; the untracked file beside it is not",
                  r["dirty"] == ["f"])
            # the flip line shortens a HOME-rooted checkout to ~ (checkout_flip); under a HOME-rooted TMPDIR
            # (the box's own scratch, since #639) `box` itself is under HOME, so match the same shortening here
            check("the first dirty tick is the flip: one line naming the checkout and the file",
                  watch({"checkout": r}) and len(said) == 1
                  and f"main checkout {box.replace(HOME, '~', 1)}" in said[0]
                  and "not a clean origin/main" in said[0] and "modified f" in said[0] and "scratch" not in said[0])
            g("checkout", "-q", "-b", "track/x", cwd=box)
            r = checkout(box)
            check("still wrong, now off the branch too: NO repeat", r["branch"] == "track/x"
                  and checkout_flip(r, now=time.time() + 60) is None and len(said) == 1)
            globals()["GIT"] = stub("sleep 5")
            t = time.monotonic()
            check("a HUNG git is None after the timeout, not a hung recorder — and an unreadable tick does not "
                  "close the open fault", git("status", cwd=box, timeout=0.3) is None and time.monotonic() - t < 2
                  and checkout_flip(None) is None and _state("checkout.json").get("since"))
            globals()["GIT"] = "git"
            g("checkout", "-q", "-f", "main", cwd=box)
            r = checkout(box)
            back = checkout_flip(r, now=time.time() + 150 * 60)
            check("a clean main again (scratch still untracked): the UP line once, with the length and what was wrong",
                  r["dirty"] == [] and bool(back) and "clean origin/main again after 150 min" in back
                  and "modified f" in back and "track/x" in back)
            check("...and the state is cleared", checkout_flip(r) is None
                  and json.loads(_read(f"{tmp}/checkout.json")) == {})
            commit(box, "g", "local\n")
            r = checkout(box)
            check("a commit origin does not have is ahead, and a fault",
                  r["ahead"] == 1 and "1 commit ahead of origin/main" in (checkout_flip(r) or ""))
            g("reset", "-q", "--hard", "origin/main", cwd=box)
            check("level again: closed", "again after" in (checkout_flip(checkout(box), now=time.time() + 60) or ""))
            commit(origin, "h", "upstream\n")
            g("fetch", "-q", cwd=box)
            r = checkout(box)
            check("behind origin is a pull pending, not a fault", r["behind"] == 1 and wrong(r) == []
                  and checkout_flip(r) is None)
            g("init", "-q", "-b", "trunk", f"{tmp}/o2")
            commit(f"{tmp}/o2", "f", "1\n")
            g("clone", "-q", f"{tmp}/o2", f"{tmp}/trunk")
            check("the default branch is whatever origin's HEAD says, not the word main",
                  checkout(f"{tmp}/trunk")["default"] == "trunk" and wrong(checkout(f"{tmp}/trunk")) == [])
            check("no checkout at all is None, not a fault", checkout(tmp) is None and checkout_flip(None) is None)
        finally:
            globals()["GIT"], globals()["alert"] = "git", live_alert

        # -- and one real minute end to end, short --------------------------------------------------------------
        r = record_minute(period=2, sample=1)
        check("record_minute reads this box and returns a whole row",
              r["s"] >= 2 and r["cap"]["cores"] and r["load"]["m"] is not None and r["dt"] >= 2)
        check("the row is stamped with the minute it covers, on the minute", r["t"].endswith(":00Z"))
        check("...with the resolver reading in it", set(r["dns"]) == set(HOSTS))
        check("...and the checkout reading (this copy lives in a repo)", "checkout" in r and r["checkout"]["top"])
    finally:
        globals()["DIR"] = live
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"cc-vitals selfcheck: {n[0]} passed, {n[1]} failed")
    return 1 if n[1] else 0
