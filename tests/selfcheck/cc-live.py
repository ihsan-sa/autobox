# cc-live's selfcheck: the cases behind `cc-live selfcheck`. Not a module: cc-live execs this file INSIDE ITS OWN
# NAMESPACE and calls the selfcheck() it defines, so every name here is the tool's and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below. Every source is a
# fixture in a temp dir pointed at by env; nothing reads the live host's status dir, ledger, units or release.

# ── selfcheck ─────────────────────────────────────────────────────────────────────────────────────────────────
def key_limit():
    """(ms a keypress may take to redraw, why): 16, or 48 under load, as cc-live-old holds to."""
    if os.environ.get("CC_LOADED"):
        return 48, "CC_LOADED is set"
    load, cores = os.getloadavg()[0], os.cpu_count() or 1
    return (48, f"load {load:.1f} on {cores} cores") if load >= cores else (16, "the target")


def selfcheck():
    ok = bad = 0

    def case(name, cond):
        nonlocal ok, bad
        if cond:
            ok += 1
        else:
            bad += 1
            print(f"FAIL {name}")

    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="cc-live-")
    st, now = f"{tmp}/status", int(time.time())
    os.makedirs(st)
    for k, v in {"CC_LIVE_STATUS_DIR": st, "CC_LEDGER": f"{tmp}/ledger.jsonl", "CC_LIVE_RELEASE": f"{tmp}/current",
                 "CC_LIVE_UNITS": f"{tmp}/units", "CC_PULSE": f"{tmp}/pulse.json"}.items():
        os.environ[k] = v
    stamp_ = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    sd = lambda t: time.strftime("%a %Y-%m-%d %H:%M:%S %Z", time.localtime(t))

    def write(name, body, where=st):
        with open(f"{where}/{name}.new", "w", encoding="utf-8") as fh:
            fh.write(body if isinstance(body, str) else json.dumps(body))
        os.replace(f"{where}/{name}.new", f"{where}/{name}")   # as the door writes: one rename

    def unit(name, active, since, restarts=0):
        return (f"Id={name}\nActiveState={active}\nSubState={'running' if active == 'active' else active}\n"
                f"ActiveEnterTimestamp={sd(since) if since else ''}\nNRestarts={restarts}\n")

    # ── the sentence door (<R>.txt), from the host's sample of 2026-10-14 ──
    dac = (f"demo (o/demo), {stamp_}\n"
           '  Stuck: issue #6 "Working toward GOALS.md" failed at 11:00, before a PR: Permission denied (publickey).\n'
           '  Running: issue #10 "Working toward GOALS.md", 3 min\n'
           "  Open: PR #11 (not checked yet)\n"
           "  Today 2 merged, $1.56 spent; last 7 days 2 merged, $1.56 spent.\n"
           "  Loop running, last poll 2 min ago\n"
           "  1 ledger line couldn't be read\n")
    p = from_txt(dac)
    case("txt: the header gives the repo and the stamp",
         p["repo"] == "o/demo" and abs(p["at"] - now) < 60)
    case("txt: Running: is a run with its issue, title and the door's rounded age",
         p["runs"] == [{"issue": 10, "title": "Working toward GOALS.md", "state": "running", "age": "3 min",
                        "text": 'issue #10 "Working toward GOALS.md", 3 min'}])
    case("txt: Open:, Stuck: and Today are read by their opening word",
         p["open"] == ["PR #11 (not checked yet)"] and p["stuck"][0].startswith("issue #6") and
         (p["merged"], p["spent"]) == (2, 1.56))
    case("txt: Loop gives the state and a last poll counted back from the stamp",
         p["loop"] == "running" and abs(p["poll"] - (p["at"] - 120)) < 1)
    case("txt: a line with no known opening word is kept verbatim", p["other"] == ["1 ledger line couldn't be read"])
    case("txt: the fields the sentences never carry stay None, so they draw n/p",
         p["runs_today"] is None and p["release"] is None)
    case("txt: late, down and off loops",
         from_txt("x\n  Loop running, last poll 9 min ago, late\n")["loop"] == "late" and
         from_txt("x\n  Loop failed, last poll 3 min ago\n")["loop"] == "down" and
         from_txt("x\n  Loop off: this project isn't on dispatch's units\n")["loop"] == "off" and
         from_txt("x\n  Loop state unknown, no poll yet, late\n")["loop"] is None)
    needs = from_txt("app (o/app)\n  Needs you: PR #77 stopped (it changes his standing goals) "
                     "and is still open (checked 6 min ago)\n")
    case("txt: Needs you: is an ask waiting on a person", needs["asks"] and needs["asks"][0].startswith("PR #77"))

    # ── the field door (<R>.json, schema v1) ──
    def run(state, **kw):
        r = {"issue": 212, "title": "fix the header", "trigger": {"kind": "ask", "via": "mail", "channel": "C0ABC",
             "ts": "1791992179.499989"}, "started_at": now - 40, "ended_at": None, "spent": 0.12, "state": state,
             "on": None, "why": None, "pr": None, "read": None}
        r.update(kw)
        return r

    def doc(runs, **kw):
        d = {"v": 1, "repo": "o/web", "at": now, "release": "aeed4aae35c5",
             "loop": {"state": "running", "last_poll": now - 30}, "today": {"runs": 3, "merged": 1, "spent": 4.1},
             "runs": runs}
        d.update(kw)
        return d

    pr = {"number": 1367, "url": "https://github.com/o/web/pull/1367", "gh": "is green and up to date"}
    walk = [run("running"),
            run("running", pr=pr, spent=0.7),
            run("running", pr=pr, spent=0.7, read={"verdict": "LAND", "sha": "abc", "at": now - 5}),
            run("merged", pr=pr, spent=0.7, read={"verdict": "LAND", "sha": "abc", "at": now - 5},
                started_at=now - 300, ended_at=now)]
    flows = [flow(r, from_json(json.dumps(doc([r]))), now) for r in walk]
    case("json: a run walks trigger → running → PR → read → merged, a step at a time",
         flows[0].endswith("running 40s · $0.12") and "ask by mail" in flows[0] and
         flows[1].endswith("→ PR #1367 (is green and up to date)") and flows[2].endswith("→ read: LAND") and
         "ran 5m · $0.70 → PR #1367 → read: LAND → merged" in flows[3])
    held = from_json(json.dumps(doc([run("held", on="owner", why="it changes his standing goals", pr=pr,
                                         ended_at=now)])))
    case("json: a run held on the owner is waiting on a person, with its why",
         held["asks"] == ["held on owner: #212 PR #1367 it changes his standing goals"] and
         "held on owner: it changes his standing goals" in flow(held["runs"][0], held, now))
    stuck = from_json(json.dumps(doc([run("failed", why="no PR: push refused", ended_at=now)])))
    case("json: a failed run is listed as stuck and draws no PR step",
         stuck["stuck"] == ["failed: #212 no PR: push refused"] and "→ PR" not in flow(stuck["runs"][0], stuck, now))
    nul = from_json(json.dumps({"v": 1, "repo": "o/r", "at": None, "release": None, "loop": None, "today": None,
                                "runs": [run("merged", trigger=None, spent=None, started_at=None, ended_at=None)]}))
    f = flow(nul["runs"][0], nul, now)
    case("json: every null field draws n/p, never a guess",
         "trigger n/p n/p" in f and "ran n/p · n/p → PR n/p → merged n/p" in f and nul["spent"] is None)
    case("json: a file that isn't schema v1 is not taken for one",
         from_json('{"v": 2}') is None and from_json("not json") is None)

    # ── the whole snapshot from a fixture host ──
    write("demo.txt", dac)
    write("demo.json", '{"v": 9}')                  # not v1: the sentences are read instead
    write("web.txt", f"web (o/web), {stamp_}\n  Nothing running or open.\n")
    write("web.json", doc(walk[:1] + [run("merged", issue=211, pr=pr, started_at=now - 900, ended_at=now - 300)]))
    write("app.txt", "app (o/app)\n  Needs you: PR #77 stopped and is still open\n")
    write("all.txt", "Dispatch at …\n")
    write("digest.txt", "Needs you: app <https://github.com/o/app/pull/77|#77> changes your "
                        "standing goals.\n")
    write("health.json", {"fx_down": None})
    with open(f"{tmp}/units", "w") as fh:
        fh.write("\n".join([unit("dispatch-fx.service", "active", now - 3600),
                            unit("dispatch-loop@web.service", "active", now - 3 * 3600),
                            unit("dispatch-loop@demo.service", "active", now - 600),
                            unit("dispatch-loop@tool.service", "failed", now - 720, restarts=3),
                            unit("dispatch-loop@app.service", "inactive", None)]))
    os.symlink("releases/aeed4aae35c57db233a98fd4fff0fa3f30d6108d", f"{tmp}/current")
    rows = [{"kind": "health", "at": now - 600, "outcome": "failed", "why": "disk-high root"},
            {"kind": "health", "at": now - 300, "outcome": "failed", "why": "disk-high root"},
            {"kind": "selftest", "at": now - 900, "outcome": "failed", "why": "check-extra identity", "repo": "o/r"},
            {"kind": "health", "at": now - 2 * DAY, "outcome": "failed", "why": "an old one"},
            {"kind": "health", "at": now - 60, "outcome": "ok", "why": "passed"}]
    with open(f"{tmp}/ledger.jsonl", "w") as fh:
        fh.write("\n".join(map(json.dumps, rows)) + "\n{torn line\n")
    e = collect(now)
    ps = e["projects"]
    case("the projects are the loop units and the door's files, less all/digest/health",
         sorted(ps) == ["app", "demo", "tool", "web"])
    case("<R>.json is read when it is v1, and <R>.txt otherwise",
         ps["web"]["src"] == "json" and ps["demo"]["src"] == "txt")
    case("a project with a unit and no door file reads n/p", ps["tool"]["src"] == NP)
    screen = text(e, now, 160)
    case("the header counts loops up, fx, spend and what waits on a person",
         "loops 2/4 up · fx up" in screen and "$5.66 today" in screen and "1 waiting on a person" in screen)
    case("runs today is n/p while any project's door doesn't publish it", "runs today n/p" in screen)
    case("a loop's row: up and since, FAILED with restarts, INACTIVE",
         re.search(r"web +up 3h", screen) and re.search(r"tool +FAILED 12m ↻3", screen) and
         re.search(r"app +INACTIVE ", screen))
    case("the release comes from the json, else the current link",
         re.search(r"web .* aeed4aae35c5 +3 +1 +\$4\.10", screen) and
         re.search(r"demo .* aeed4aae35c5 +n/p +2 +\$1\.56", screen))
    case("the running run and today's finished one sit under their project",
         "run #212 ▶ ask by mail" in screen and "run #211 ✓" in screen and "open: PR #11 (not checked yet)" in screen)
    case("health: ledger failures in 24 h grouped, an old one and a passing one dropped, a torn line counted",
         [(g["why"], g["n"]) for g in e["ledger"]] == [("disk-high root", 2), ("check-extra identity", 1)] and
         e["ledger_bad"] == 1 and "disk-high root ×2" in screen and "an old one" not in screen)
    case("the digest's first line, with Slack links drawn as their labels",
         "digest: Needs you: app #77 changes your standing goals." in screen)
    case("the old system says so when no fresh pulse is there", "cc-pulse not running here" in screen)
    with open(f"{tmp}/pulse.json", "w") as fh:
        json.dump({"at": now, "glance": {"needs": {"n": 2}, "sessions": {"busy": 3, "waiting": 1},
                                         "workers": {"live": 5}, "landing": {"active": 1, "queued": 2}}}, fh)
    case("the old system in one line from a fresh pulse", "sessions 3 busy 1 waiting · workers 5 live" in
         text(collect(now), now, 160))
    write("digest.txt", "")
    case("an empty digest is a quiet day", "digest: quiet (empty)" in text(collect(now), now, 160))
    os.unlink(f"{st}/digest.txt")
    case("a missing digest is n/p", "digest: n/p" in text(collect(now), now, 160))

    # ── the door, and nothing past it ──
    secret = f"{tmp}/private"
    os.makedirs(secret)
    with open(f"{secret}/state.txt", "w") as fh:
        fh.write("tenant-private-secret\n")
    os.symlink(f"{secret}/state.txt", f"{st}/leak.txt")
    os.makedirs(f"{st}/sub.txt")
    e2 = collect(now)
    case("a symlink in the door is refused, so nothing outside it is read",
         e2["projects"]["leak"]["src"] == "unreadable" and "tenant-private-secret" not in json.dumps(e2))
    case("a directory named like a file isn't read", e2["projects"]["sub"]["src"] == "unreadable")
    case("only plain names are opened", door("../private/state.txt") is False and door("a/b.txt") is False)
    if os.geteuid() != 0:
        os.chmod(f"{st}/app.txt", 0)
        case("a file the user can't open draws unreadable", collect(now)["projects"]["app"]["src"] ==
             "unreadable")
        os.chmod(f"{st}/app.txt", 0o640)
    os.environ["CC_LIVE_UNITS"] = f"{tmp}/no-such-units"
    e3 = collect(now)
    case("with systemd unreadable, loops are n/p and each loop cell falls back to the door's word",
         "loops n/p" in text(e3, now, 200) and loop_cell(e3["projects"]["web"], now, e3["units"])[0] == "running")
    os.environ["CC_LIVE_UNITS"] = f"{tmp}/units"

    # ── fail soft: an odd file is one odd row, a FIFO never hangs, no control character reaches the screen ──
    odd = {"odd-loop.json": '{"v": 1, "loop": "running"}', "odd-today.json": '{"v": 1, "today": [1]}',
           "odd-pr.json": doc([run("running", pr="x")]),
           "odd-trigger.json": doc([run("merged", trigger="ask", ended_at=now)]),
           "odd-stamp.txt": "acme (a/b), 2026-13-45 99:99\n  Today 1 merged, $1.2.3 spent\n",
           "odd-deep.json": "[" * 100000}
    for n, body in odd.items():
        write(n, body)
    e4 = collect(now)
    p4, screen4 = e4["projects"], text(e4, now, 200)
    case("fail soft: a field of the wrong shape is absent, so it draws n/p",
         p4["odd-loop"]["src"] == "json" and p4["odd-loop"]["loop"] is None and p4["odd-today"]["merged"] is None and
         p4["odd-pr"]["runs"][0]["pr"] is None and "run #212 ▶" in screen4 and
         any("trigger n/p" in t for t, _, _ in project(e4, "odd-trigger", now, 200)))
    case("fail soft: a header stamp that is no time draws n/p, and an odd Today line is kept verbatim",
         p4["odd-stamp"]["src"] == "txt" and p4["odd-stamp"]["at"] is None and
         p4["odd-stamp"]["other"] == ["Today 1 merged, $1.2.3 spent"])
    case("fail soft: a file that raises while read is one unreadable row with the error's name",
         p4["odd-deep"]["src"] == "unreadable" and p4["odd-deep"]["other"] == ["could not read it: RecursionError"]
         and re.search(r"odd-deep .*unreadable", screen4))
    case("fail soft: the other projects still render beside the odd ones",
         p4["demo"]["src"] == "txt" and p4["web"]["src"] == "json" and re.search(r"web .* aeed4aae35c5", screen4) and
         re.search(r"demo .* aeed4aae35c5 +n/p +2", screen4) and all(project(e4, n, now, 200) for n in p4))
    nan = from_json('{"v": 1, "at": NaN, "today": {"spent": Infinity}, "runs": 5}')
    case("fail soft: NaN and Infinity are no numbers, and runs that aren't a list are none",
         nan["at"] is None and nan["spent"] is None and nan["runs"] == [])
    write("esc.txt", 'esc (o/esc)\n  Running: issue #5 "evil\x1b[2J\x1b]0;pwned\x07 title", 1 min\n')
    write("esc2.json", doc([run("failed", why="red\x1b[31m why\x9b", ended_at=now)]))
    with open(f"{tmp}/ledger.jsonl", "a") as fh:
        fh.write(json.dumps({"kind": "\x1b[1mhealth", "at": now - 30, "outcome": "failed", "why": "esc\x07 why",
                             "repo": "o/\x9bbad"}) + "\n")
    os.mkfifo(f"{st}/pipe.txt")
    os.mkfifo(f"{st}/digest.txt")
    try:
        once = subprocess.run([sys.executable, __file__, "--once"], capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        once = None
    os.unlink(f"{st}/pipe.txt")        # gone before anything below reads the door in-process, where a FIFO opened
    os.unlink(f"{st}/digest.txt")      # without O_NONBLOCK would hang the selfcheck instead of failing it
    out = once.stdout if once else ""
    case("a FIFO in place of a status file is refused at once: --once returns and draws it unreadable",
         once is not None and once.returncode == 0 and re.search(r"pipe .*unreadable", out) and
         "digest: unreadable" in out)
    case("no control character reaches --once from a title, a why, or a ledger kind, why or repo",
         "evil" in out and "red" in out and "o/bad" in out and not CTRL.search(out.replace("\n", "")))
    case("cut drops C0, DEL and C1 characters before it measures", cut("a\x1b[2Jb\x7f\x85c\td", 8) == "a[2Jbcd")

    # ── the feed: re-read when a source moves, not otherwise ──
    feed = Feed()
    feed.step(now)
    v = feed.version
    case("an unchanged door is not re-read", feed.step(now + 1) is False and feed.version == v)
    write("web.json", doc(walk[1:2]))
    case("a rename in the door moves the version", feed.step(now + 2) and feed.version == v + 1 and
         "PR #1367" in text(feed.e, now + 2, 160))

    # ── keys, on a fake screen ──
    class Screen:
        def __init__(self, keys, h=30, w=160):
            self.keys, self.h, self.w, self.rows, self.shots = list(keys), h, w, {}, []

        def getmaxyx(self):
            return self.h, self.w

        def keypad(self, on):
            pass

        def timeout(self, ms):
            pass

        def erase(self):
            self.rows = {}

        def addstr(self, y, x, s, attr=0):
            self.rows[y] = s

        def refresh(self):
            self.shots.append("\n".join(self.rows.get(y, "") for y in range(self.h)))

        def getch(self):
            return self.keys.pop(0) if self.keys else ord("q")

    import curses as K
    opened, timing = [], []
    keys = [K.KEY_DOWN, 10, 27, ord("a"), 27, ord("H"), ord("h"), ord("s"), ord("o"), ord("q")]
    scr = Screen(keys)
    rc = ui(scr, feed, clock=lambda: now + 2, tones={}, timing=timing, old=lambda s, k: opened.append(chr(k)))
    shots = scr.shots
    case("home draws first, with the footer on the last row",
         shots[0].splitlines()[0].startswith("hive ·") and shots[0].splitlines()[-1].startswith("↑↓ move"))
    case("↓ then Enter opens the second project, with its fields and what its door doesn't publish",
         any(s.startswith("demo  (o/demo)  from txt") and "not published by" in s
             for s in shots))
    case("a opens waiting and stuck, H the health view", any(s.startswith("WAITING ON A PERSON\n") for s in shots)
         and any(s.startswith("HEALTH (24 h)") and "disk-high root ×2" in s for s in shots))
    case("an old section's key and o open cc-live-old on that key; q quits with 0", opened == ["s", "o"] and rc == 0)
    case("no control character reaches the curses screen", shots and not any(CTRL.search(x.replace("\n", ""))
                                                                              for x in shots))
    worst = max(timing) * 1000 if timing else -1
    limit, why = key_limit()
    print(f"cc-live: a key redrew in {worst:.1f} ms at worst ({len(timing)} keys); limit {limit} ms ({why})")
    case(f"every key redraws in under {limit} ms ({why})", timing and worst < limit)
    shutil.rmtree(tmp, ignore_errors=True)
    # hive is a link to this file, and check.sh wants the tally under the name it ran
    print(f"{os.path.basename(sys.argv[0]) or 'cc-live'} selfcheck: {ok} passed, {bad} failed")
    return 1 if bad else 0
