# cc-pulse's selfcheck: the cases behind `cc-pulse selfcheck`. Not a module: cc-pulse execs this file INSIDE ITS
# OWN NAMESPACE and calls the selfcheck() it defines, so every name here is the tool's, a `global` rebinds the
# tool's, and `__file__` is the tool. No module docstring (it would replace the tool's __doc__) and no top-level name
# but the def below.

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
    tmp = tempfile.mkdtemp(prefix="cc-pulse-")
    now = int(time.time())
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    for k, v in {"CC_BOARDS": f"{tmp}/boards", "CC_STATE": f"{tmp}/state", "CC_LANDER_STATE": f"{tmp}/land",
                 "CC_WORKTREES": f"{tmp}/wt", "CC_SESSIONS": f"{tmp}/sessions", "CC_MEMBERS": f"{tmp}/members",
                 "CC_DEV": f"{tmp}/dev", "CC_PULSE": f"{tmp}/state/pulse.json",
                 "CC_PULSE_SUITES": f"{tmp}/bin/suites"}.items():
        os.environ[k] = v
    for d in ("boards", "state/r/w1", "state/statusline", "state/vitals", "land", "proc", "wt/r/w1", "bin",
              "sessions", "members/mem", "dev/r", "state/fund", "state/mem"):
        os.makedirs(f"{tmp}/{d}")
    open(f"{tmp}/bin/suites", "w").write("#!/bin/sh\necho 'cc-suites: runner lap answers: free 3'\n"
                                         "echo \"cc-suites: its GPU: Fake 4070, 5% busy, 300/8188 MiB, 40 C ($*)\"\n")
    open(f"{tmp}/bin/hang", "w").write("#!/bin/sh\nexec sleep 30\n")
    for n in ("suites", "hang"):
        os.chmod(f"{tmp}/bin/{n}", 0o755)
    proc = f"{tmp}/proc"

    def fake(pid, comm, argv, cwd=None, start="100"):
        d = f"{proc}/{pid}"
        os.makedirs(d)
        open(f"{d}/comm", "w").write(comm + "\n")
        open(f"{d}/cmdline", "wb").write("\0".join(argv).encode() + b"\0")
        open(f"{d}/stat", "w").write(f"{pid} ({comm}) S " + " ".join(["0"] * 18) + f" {start} 0 0\n")
        if cwd:
            os.symlink(cwd, f"{d}/cwd")
    fake(30, "claude", ["claude", "-p"], cwd=f"{tmp}/wt/r/w1")       # a headless worker in its worktree
    fake(40, "bash", ["bash", "/x/cc-loop", "r", "sent"])           # a worker loop between turns
    fake(50, "claude", ["claude"], cwd=f"{tmp}/dev/r")              # the repo's seat
    fake(51, "claude", ["claude"], cwd=f"{tmp}/dev/mem")            # a member's session
    fake(52, "claude", ["claude"], cwd=f"{tmp}/dev/r", start="999") # a pid reused by another process
    fake(10, "node", ["node"])
    fake(41, "python3", ["python3", "/x/cc-room", "admit", "r/py", "--log", "/x/loop.log", "--", "/x/cc-loop", "r", "py"])
    fake(60, "python3", ["python3", "/x/tool.py", "core/bin/cc-loop", "a", "b"])   # a script reading cc-loop as a file
    tck = os.sysconf("SC_CLK_TCK") or 100
    open(f"{proc}/stat", "w").write(f"cpu 0 0 0\nbtime {now - 100000}\n")    # booted 100000 s ago
    board = {"tracks": {
        "fresh": {"title": "just added", "status": "queued", "created": iso(now - 60)},
        "sent": {"title": "worker out", "status": "running", "created": iso(now - 7200),
                 "notes": [{"ts": iso(now - 900), "msg": "dispatched headless worker (loop 2)"}]},
        "w1": {"title": "live one", "status": "running", "created": iso(now - 90000)},
        "gone": {"title": "parked", "status": "running", "created": iso(now - 90000), "held": "waits on #9"},
        "lost": {"title": "lost one", "status": "running", "created": iso(now - 90000)},
        "mine": {"title": "worked by a seat", "status": "running", "created": iso(now - 90000), "agent": "@1:10"},
        "stale": {"title": "mark of a dead seat", "status": "running", "created": iso(now - 90000), "agent": "@1:999"},
        "sess": {"title": "a session", "status": "running", "kind": "session", "created": iso(now - 90000)},
        "old": {"title": "last week", "status": "merged", "created": iso(now - 7 * 86400)},
        "bad": "not a row"}}
    json.dump(board, open(f"{tmp}/boards/r.json", "w"))
    json.dump({"tracks": {"secret": {"title": "member's own words", "status": "running", "created": iso(now)}}},
              open(f"{tmp}/boards/mem.json", "w"))
    json.dump({"tracks": {"x": {"title": "test board", "status": "running", "created": iso(now)}}},
              open(f"{tmp}/boards/_t.json", "w"))
    json.dump({"repo": "r", "pr": 7, "stage": "gates", "title": "a landing"}, open(f"{tmp}/land/r-7.json", "w"))
    json.dump({"repo": "r", "pr": 8, "stage": "queued"}, open(f"{tmp}/land/r-8.json", "w"))
    json.dump({"repo": "mem", "pr": 1, "stage": "gates", "title": "member PR"}, open(f"{tmp}/land/mem-1.json", "w"))
    open(f"{tmp}/state/r/w1/loop.log", "w").close()
    os.utime(f"{tmp}/state/r/w1/loop.log", (now - 120, now - 120))
    for pid, cwd, st, age, start in ((50, f"{tmp}/dev/r", "idle", 3000, "100"), (30, f"{tmp}/wt/r/w1", "busy", 30, "100"),
                                     (51, f"{tmp}/dev/mem", "waiting", 5, "100"), (52, f"{tmp}/dev/r", "busy", 5, "100"),
                                     (99, f"{tmp}/dev/r", "busy", 5, "100"), (53, f"{tmp}/dev/r", "waiting", 60, None),
                                     (54, f"{tmp}/dev/r", "busy", 60, None), (55, f"{tmp}/dev/r", "busy", 600, None)):
        json.dump({"pid": pid, "sessionId": f"s{pid}", "cwd": cwd, "name": f"n{pid}", "status": st,
                   "statusUpdatedAt": (now - age) * 1000, "tmux": f"main:@{pid}.%{pid}",
                   **({"procStart": start} if start else {})}, open(f"{tmp}/sessions/{pid}.json", "w"))
    fake(53, "claude", ["claude"], cwd=f"{tmp}/dev/r")                                  # an older Claude Code's record
    fake(54, "bash", ["bash"], cwd=f"{tmp}/dev/r")                                      # ... whose pid bash now has
    fake(55, "claude", ["claude"], cwd=f"{tmp}/dev/r", start=str((100000 + 10) * tck))  # ... a claude born after it
    json.dump({"pct": 42}, open(f"{tmp}/state/statusline/s30.json", "w"))
    json.dump({"state": {"tracks": [
        {"state": "review", "name": "r/w1", "reason": "", "pr": {"num": 5, "owed": True, "repo": "r"}},
        {"state": "blocked", "name": "r/lost", "reason": "which colour?", "pr": None},
        {"state": "waiting", "name": "mem/secret", "reason": "member's question", "pr": None},
        {"state": "blocked", "name": "r/quiet", "reason": "", "pr": None},
        {"state": "review", "name": "mem/hidden-a", "reason": "", "pr": {"num": 42, "owed": True, "repo": "r"}},
        {"state": "review", "name": "mem/hidden-b", "reason": "", "pr": {"num": 43, "owed": True, "repo": "org/mem"}},
        {"state": "review", "name": "r/odd", "reason": "", "pr": {"num": 44, "owed": True, "repo": "mem"}}],
        "sessions": [{"repo": "r", "name": "seat", "ask": "approve deploy"}],
        "units": [["a", True, ""], ["b", False, "dead"]],
        "spend": {"today": 81.97, "rows": [{"who": "r/session", "usd": 3.5}, {"who": "r/w1", "usd": 1.0},
                                           {"who": "mem/session", "usd": 9.0}]}}},
              open(f"{tmp}/state/home.json", "w"))
    json.dump({"series": [{"key": "temp", "now": {"real": 68.6}}]}, open(f"{tmp}/state/vitals/current.json", "w"))
    open(f"{tmp}/state/model-override", "w").write(f"sonnet\t{now - 60}\t{now + 3600}\tlimit\t0\n")
    json.dump({"limit_until": now + 3600}, open(f"{tmp}/state/reconcile.json", "w"))
    json.dump({"title": "fund", "at": iso(now - 30), "rows": [
        {"label": "paper P&L", "value": "+$212", "state": "ok"}, {"label": "data age", "value": "9m", "state": "warn"},
        {"label": "x" * 40, "value": 3, "state": "purple"}, "junk"]}, open(f"{tmp}/state/fund/panel.json", "w"))
    json.dump({"title": "mine", "at": iso(now), "rows": []}, open(f"{tmp}/state/mem/panel.json", "w"))
    log = [(now - 7200, "stage r#5 merged sha=abc"), (now - 7100, "notify r#5 landed → thread"),
           (now - 30 * 3600, "notify r#3 landed → thread"), (now - 600, "stage r#6 merged sha=def"),
           (now - 500, "stage _t#1 merged sha=x"), (now - 400, "stage r#8 gate"), (now - 300, "not a line")]
    open(f"{tmp}/land/queue.log", "w").write("".join(f"{iso(t)}\t{m}\n" for t, m in log) + f"{iso(now)}\tstage r#9 mer")
    os.makedirs(f"{tmp}/land/rest")
    json.dump({"repo": "r", "pr": "5", "title": "the fifth"}, open(f"{tmp}/land/rest/r-5.json", "w"))

    # the collectors, each on the fixture above
    case("a `_` test board is skipped; a member's board is read (to be counted)", sorted(boards()) == ["mem", "r"])
    case("a non-dict row is dropped, not a crash", "bad" not in boards()["r"])
    open(f"{tmp}/boards/deep.json", "w").write("[" * 100000)
    open(f"{tmp}/boards/huge.json", "w").write('{"tracks": {}, "pad": "' + "x" * BOARD_MAX + '"}')
    bs = boards()
    case("a 100000-deep board and an over-cap board drop out alone; the other boards still show",
         bs.get("deep") == {} and bs.get("huge") == {} and bs["r"] and "mem" in bs)
    os.remove(f"{tmp}/boards/deep.json")
    os.remove(f"{tmp}/boards/huge.json")
    live, pids = procs(proc)
    case("a claude in a worktree makes its track live; a cc-loop argv does too", {"r/w1", "r/sent"} <= live)
    case("a claude outside the worktrees is no track", not any("dev" in k for k in live))
    case("a cc-loop waiting in cc-room (comm python3) makes its track live", "r/py" in live)
    case("a cc-loop word that is another process's argument makes no track live", "a/b" not in live)
    ss, smem = sessions(now, proc)
    ids = [s["id"] for s in ss]
    case("a session whose pid is gone, or was reused by another process, is left out", "99" not in ids and "52" not in ids)
    case("a session file with no procStart is kept while its pid is a claude started before the record", "53" in ids)
    case("a record with no procStart whose pid bash now has is not live", "54" not in ids)
    case("a record with no procStart whose pid a later claude has is not live", "55" not in ids)
    case("procStart compares as a number: 100, '100' and '100.0' match, '101' does not",
         same_process(proc, "30", {"procStart": 100}) and same_process(proc, "30", {"procStart": "100.0"})
         and same_process(proc, "30", {"procStart": " 100 "}) and not same_process(proc, "30", {"procStart": "101"}))
    case("a record with no procStart and no time of its own is not live", not same_process(proc, "53", {}))
    case("sessions are attention first: waiting, then busy, then idle", ids == ["53", "30", "50"])
    case("a member's session is counted, never listed", smem == 1 and "51" not in ids)
    s30 = next(s for s in ss if s["id"] == "30")
    case("a session carries its repo, track, context % and tmux window",
         (s30["repo"], s30["track"], s30["ctx_pct"], s30["win"]) == ("r", "w1", 42, "@30"))
    case("a seat in ~/dev/<repo> has its repo and no track", next(s for s in ss if s["id"] == "50")["track"] == "")
    wk, wmem = workers(boards(), live, pids, now)
    by = {w["track"]: w["live"] for w in wk}
    case("a live worker is live and shows its last move", by["w1"] == "live" and
         next(w for w in wk if w["track"] == "w1")["moved_s"] == 120)
    case("a running row with no process and no hold is offline", by["lost"] == "offline")
    case("a row whose agent mark names a live pid is a session's", by["mine"] == "session")
    case("an agent mark whose pid is gone is still offline", by["stale"] == "offline")
    case("a held row is held, not offline", by["gone"] == "held")
    case("a session row is not a worker; a member's running row is only counted", "sess" not in by and "secret" not in by
         and wmem == 1)
    nd, nmem = needs(home_state())
    case("needs: an owed PR first, then a blocked track with a reason, member asks counted, no reason no need",
         [(n["kind"], n["name"]) for n in nd] == [("pr", "PR #5"), ("ask", "seat"), ("blocked", "lost")])
    case("a member track's PR is counted by the track's own workspace, whatever repo the PR claims (r, org/mem), "
         "and an owned track's PR in a member's repo is counted too", nmem == 4)
    blob = json.dumps(nd)
    case("no member repo, PR number or track name is in needs",
         not any(w in blob for w in ("hidden", "PR #42", "PR #43", "PR #44", "org/mem", "odd", "mem")))
    ld = landed()
    case("landed: newest first, the earliest of merged and notify, no test repo, no other stage",
         ld == [(now - 600, "r", "6"), (now - 7200, "r", "5"), (now - 30 * 3600, "r", "3")])
    open(f"{tmp}/land/queue.log", "a").write("ged sha=1\n")
    case("a half-written last line is read whole on the next pass", landed()[0] == (now, "r", "9"))
    open(f"{tmp}/land/queue.log", "w").write(f"{iso(now - 60)}\tstage r#4 merged sha=2\n")
    case("a log that was cut short is read again from the top", landed() == [(now - 60, "r", "4")])
    open(f"{tmp}/land/queue.log", "w").write("".join(f"{iso(t)}\t{m}\n" for t, m in log))
    _LOG.update(ino=None)
    lg = landing(now)
    case("in-flight landings are listed, a member's left out", sorted(x["pr"] for x in lg) == [7, 8])
    case("model: an override still ahead is the model", model(now) == "sonnet")
    case("model: a lapsed override is the default", model(now + 7200) == "default")
    case("a usage limit ahead is shown and one behind is not", limit_until(now) == now + 3600 and limit_until(now + 7200) is None)

    # the panel a project writes
    pn = panels(now)
    case("a project's panel is read; a member's workspace gets none", list(pn) == ["fund"])
    f = pn["fund"]
    case("panel rows: label cut to 24, a number shown as text, an unknown state plain, a non-row dropped",
         len(f["rows"]) == 3 and f["rows"][2] == {"label": "x" * 24, "value": "3", "state": ""} and not f["stale"])
    case("a panel older than its stale_after is stale", panels(now + 700)["fund"]["stale"])
    open(f"{tmp}/state/fund/panel.json", "w").write("{not json")
    case("a panel that is not JSON carries err and no rows", panels(now)["fund"]["err"] and panels(now)["fund"]["rows"] == [])
    open(f"{tmp}/state/fund/panel.json", "w").write(json.dumps({"title": "big", "rows": [{"label": "x" * 5000}]}))
    case("a panel over 4096 bytes is refused without being parsed", panels(now)["fund"]["err"] == "over 4096 bytes")
    os.remove(f"{tmp}/state/fund/panel.json")
    os.mkfifo(f"{tmp}/state/fund/panel.json")
    t0 = time.monotonic()
    case("a panel that is a FIFO is refused at once, not waited on",
         panels(now)["fund"]["err"] and time.monotonic() - t0 < 1)
    os.remove(f"{tmp}/state/fund/panel.json")
    json.dump({"title": "fund", "at": iso(now - 30), "rows": [{"label": "paper P&L", "value": "+$212", "state": "ok"}]},
              open(f"{tmp}/state/fund/panel.json", "w"))
    os.makedirs(f"{tmp}/state/odd")
    json.dump({"title": "odd", "rows": [], "at": {str(i): "x" for i in range(20)}}, open(f"{tmp}/state/odd/panel.json", "w"))
    pn = panels(now)
    case("a panel whose at is not a string carries err; the other panels still read",
         pn["odd"]["err"] == "not a panel: at is not a time string" and pn["fund"]["err"] is None and pn["fund"]["rows"])
    case("ts() of a non-string is 0, not a crash", ts({str(i): "x" for i in range(20)}) == 0 and ts(None) == 0)
    open(f"{tmp}/state/odd/panel.json", "w").write('{"rows": [], "stale_after": 1' + "0" * 400 + "}")
    case("a stale_after too big for a float falls back to 600 s", panels(now)["odd"]["err"] is None)
    real = panel
    globals()["panel"] = lambda path, t: (1 / 0) if "/odd/" in path else real(path, t)
    pn = panels(now)
    globals()["panel"] = real
    case("a panel that raises is that panel's err alone", pn["odd"]["err"] == "unreadable: ZeroDivisionError"
         and pn["fund"]["err"] is None and pn["fund"]["rows"])
    os.remove(f"{tmp}/state/odd/panel.json")
    json.dump({"title": "fund", "at": iso(now - 30), "rows": [{"label": "paper P&L", "value": "+$212", "state": "ok"}]},
              open(f"{tmp}/state/fund/panel.json", "w"))

    # the whole snapshot, against THE SHAPE
    pulse = Pulse(proc)
    p = pulse.step(now, laptop=False)
    case("the snapshot matches THE SHAPE", valid(p) == [])
    q = Pulse(proc).step(now, laptop=False, quick=True)
    case("a quick step has sessions and workers but leaves the landing history for the next one, and says so",
         q["sessions"] and q["workers"] and not q["recent"] and "landing" not in q["sections"]
         and "LANDING reading" in text(q) and valid(q) == [])
    case("valid() names a departure from THE SHAPE",
         "glance.box.load1 missing" in valid({**p, "glance": {**p["glance"], "box": {}}}))
    g = p["glance"]
    case("glance counts sessions, workers and landings",
         g["sessions"] == {"busy": 1, "waiting": 1, "idle": 1, "shell": 0} and g["workers"] == {"live": 3, "offline": 2, "held": 1}
         and g["landing"] == {"active": 1, "queued": 1, "landed_1h": 1})
    json.dump({"series": [{"key": "temp", "now": {"real": "71.5"}}]}, open(f"{tmp}/state/vitals/current.json", "w"))
    os.utime(f"{tmp}/state/vitals/current.json", (now + 5, now + 5))
    t1 = box({})["temp_c"]
    json.dump({"series": [{"key": "temp", "now": {"real": "warm"}}]}, open(f"{tmp}/state/vitals/current.json", "w"))
    os.utime(f"{tmp}/state/vitals/current.json", (now + 6, now + 6))
    case("a temperature written as text is read as a number, and one that is no number is none",
         t1 == 71.5 and box({})["temp_c"] is None)
    hb = {**p, "glance": {**p["glance"], "box": {**p["glance"]["box"], "temp_c": "hot"}}}
    case("a header over a temp that is no number draws, without it", "°C" not in header(hb, now)[0][0]
         and "69°C" in header(p, now)[0][0])
    case("glance carries the units down, temp, spend, model and limit",
         g["box"]["units_down"] == 1 and g["box"]["temp_c"] == 68.6 and g["spend_today"] == 81.97
         and g["model"] == "sonnet" and g["limit_until"] == now + 3600)
    case("members are counts only, each open member row once", g["members"] == {"workspaces": 1, "sessions": 1, "needs": 4, "rows": 1})
    blob = json.dumps(p)
    case("nothing a member wrote, and no note text, reaches the pulse",
         "member's" not in blob and "secret" not in blob and "dispatched headless" not in blob and "waits on #9" not in blob)
    case("no member track's name, PR number or PR repo reaches the pulse",
         not any(w in blob for w in ("hidden-a", "hidden-b", "#42", "#43", "#44", "org/mem")))
    case("recent: hand-offs and landings in the last day, newest first",
         [(e["what"], e["name"]) for e in p["recent"][:3]] == [("added", "fresh"), ("landed", "#6"), ("dispatched", "sent")]
         and all(e["name"] != "old" for e in p["recent"]))
    case("a landing in recent carries the job's title", any(e["title"] == "the fifth" for e in p["recent"]))
    pr = next(x for x in p["projects"])
    case("one project row per board the box runs, with its spend and panel",
         [x["repo"] for x in p["projects"]] == ["r"] and pr["usd"] == 4.5 and pr["needs"] == 3 and pr["running"] == 7)
    os.rename(f"{tmp}/state/home.json", f"{tmp}/state/home.keep")
    open(f"{tmp}/state/home.json", "w").write('{"state": {"tracks": 5}}')
    p2 = pulse.step(now, laptop=False)
    case("a section that raises keeps its last value and names its error, and the rest still collect",
         p2["sections"]["needs"]["err"] and p2["needs"] == p["needs"] and p2["sections"]["boards"]["err"] is None)
    os.replace(f"{tmp}/state/home.keep", f"{tmp}/state/home.json")
    s30 = json.load(open(f"{tmp}/sessions/30.json"))
    json.dump({**s30, "statusUpdatedAt": "soon"}, open(f"{tmp}/sessions/30.json", "w"))
    os.utime(f"{tmp}/sessions/30.json", (now + 7, now + 7))
    p3 = pulse.step(now, laptop=False)
    sec = p3["sections"]["sessions"]
    hl = [ln for ln in home(p3, 80, 24)[0] if ln[0].startswith("SESSIONS")]
    case("a section that fails is marked stale, with the time of its last good pass, and the rest are not",
         sec["err"] and sec["stale"] and sec["at"] == p["sections"]["sessions"]["at"]
         and p3["sections"]["workers"]["stale"] is False)
    case("the main screen heads a stale block STALE with that time, in warn, within 80 columns",
         hl and hl[0][0].startswith("SESSIONS 3  STALE: as of ") and hl[0][1] == "warn" and len(hl[0][0]) <= 80)
    case("the sessions section is headed STALE too", "STALE" in section(p3, "sessions", 80, now=now)[0][0][0])
    case("a section that never collected says UNAVAILABLE",
         stale_note({"sections": {"landing": {"at": None, "err": "OSError: x", "stale": False}}}, "landing")
         .startswith("UNAVAILABLE"))
    case("a block whose sections all collected has no note", stale_note(p, "sessions") == stale_note(p, "workers") == "")
    json.dump(s30, open(f"{tmp}/sessions/30.json", "w"))
    os.utime(f"{tmp}/sessions/30.json", (now + 8, now + 8))
    case("once the section collects again it is current", pulse.step(now, laptop=False)["sections"]["sessions"]["stale"] is False)

    # the text views
    lines, items = home(p, 80, 24)
    case("the main screen fits 80x24, footer row left free", len(lines) <= 23 and all(len(t) <= 80 for t, _ in lines))
    txt = "\n".join(t for t, _ in lines)
    case("the main screen leads with NEEDS YOU and lists sessions and workers",
         lines[1][0].startswith("NEEDS YOU 3 · r PR #5") and "SESSIONS 3" in txt and "WORKERS 6" in txt and "OFFLINE" in txt)
    case("cursor items are sessions and workers, in screen order",
         {i[1][0] for i in items} == {"session", "worker"} and [i[0] for i in items] == sorted(i[0] for i in items))
    many = {**p, "sessions": [{**ss[2], "id": str(i)} for i in range(40)], "workers": wk * 6}
    lines, items = home(many, 80, 24)
    t2 = "\n".join(t for t, _ in lines)
    case("a full box still fits 24 rows, each block saying how many more", len(lines) <= 23 and "+" in t2 and "more" in t2
         and t2.count("s lists them") == 1 and t2.count("w lists them") == 1)
    lines, _ = home({**p, "sessions": [{**ss[2], "id": str(i)} for i in range(30)], "workers": []}, 80, 24)
    case("with many sessions and no workers the LANDING line still fits",
         len(lines) <= 23 and lines[-1][0].startswith("LANDING") and "(no row marked running)" in lines[-2][0])
    case("an old pulse says STALE", "STALE" in header({**p, "at": now - 120}, now)[0][0]
         and "pulse 0s" in header(p, now)[0][0])
    for name in ("sessions", "workers", "landing", "needs", "recent", "projects", "box"):
        case(f"section {name} draws from the pulse alone", section(p, name, 80, now=now)[0])
    pj = "\n".join(t for t, _ in section(p, "project", 80, "r", now)[0])
    case("a project with no panel still shows its workers", "r/w1" in pj)
    # a member's board is a symlink its sandbox can point anywhere: a FIFO must not block, /dev/zero must not grow
    os.mkfifo(f"{tmp}/fifo")
    os.symlink(f"{tmp}/fifo", f"{tmp}/boards/pipe.json")
    os.symlink("/dev/zero", f"{tmp}/boards/zero.json")
    t0 = time.monotonic()
    bd = boards()
    case("a board that is a FIFO or /dev/zero reads as empty at once; the real boards still read",
         bd.get("pipe") == {} and bd.get("zero") == {} and bd.get("r") and time.monotonic() - t0 < 1)
    case("read_capped refuses a FIFO and /dev/zero, and a regular file over its cap",
         read_capped(f"{tmp}/fifo") is None and read_capped("/dev/zero") is None
         and read_capped(f"{tmp}/boards/r.json", 10) is None and read_capped(f"{tmp}/boards/r.json") is not None)
    for n in ("pipe", "zero"):
        os.remove(f"{tmp}/boards/{n}.json")
    json.dump({"tracks": {}}, open(f"{tmp}/boards/fund.json", "w"))
    p = pulse.step(now, laptop=False)
    fj = "\n".join(t for t, _ in section(p, "project", 80, "fund", now)[0])
    case("a project's drill-in shows its panel rows", "PANEL fund" in fj and "paper P&L" in fj and "+$212" in fj)
    case("--text prints the main screen", text(p).splitlines()[1].startswith("NEEDS YOU"))

    # the laptop is asked in a thread, never in the step
    os.environ["CC_PULSE_SUITES"] = f"{tmp}/bin/hang"
    t0 = time.monotonic()
    Pulse(proc).step(now)
    case("a laptop that hangs does not hold up a step", time.monotonic() - t0 < 3)     # it hangs 30 s
    os.environ["CC_PULSE_SUITES"] = f"{tmp}/bin/suites"
    lap = laptop_line()
    case("the laptop's lines are cc-suites status's: its answer, then its GPU's stats",
         lap == "cc-suites: runner lap answers: free 3\ncc-suites: its GPU: Fake 4070, 5% busy, 300/8188 MiB, 40 C (status --quick)")
    case("…asked with --quick, never plain status, whose Blender probe outlasts the 6 s", "(status)" not in lap)
    bx = [t for t, _ in section({**p, "glance": {**p["glance"], "laptop": lap}}, "box", 80, None, now)[0]]
    case("the box section shows each laptop line on a row of its own",
         "  laptop      cc-suites: runner lap answers: free 3" in bx
         and "              cc-suites: its GPU: Fake 4070, 5% busy, 300/8188 MiB, 40 C (status --quick)" in bx)
    # the main screen leaves the laptop to the box section (x): a two-line glance.laptop puts no row on it, and no
    # row of it carries a newline that would push the 80x24 screen out of shape
    hm = home({**p, "glance": {**p["glance"], "laptop": lap}}, 80, 24)[0]
    case("the main screen prints no laptop line, and no row of it spans two lines",
         hm[1:] == home(p, 80, 24)[0][1:] and not any("\n" in t or "cc-suites" in t for t, _ in hm))

    # the feed: a write to a watched input reaches emit fast; our own write does not loop
    got, stop = [], [False]
    th = threading.Thread(target=feed, args=(lambda q: got.append((time.monotonic(), json.loads(json.dumps(q)))),
                                             lambda: stop[0], proc), daemon=True)
    th.start()
    for _ in range(100):
        if got:
            break
        time.sleep(0.01)
    time.sleep(0.2)
    n0 = len(got)
    board["tracks"]["newrow"] = {"title": "brand new", "status": "running", "created": iso(now)}
    t0 = time.monotonic()
    tmpf = f"{tmp}/boards/r.json.tmp"
    json.dump(board, open(tmpf, "w"))
    os.replace(tmpf, f"{tmp}/boards/r.json")
    seen = None
    for _ in range(300):
        hit = [t for t, q in got[n0:] if any(w["track"] == "newrow" for w in q["workers"])]
        if hit:
            seen = hit[0] - t0
            break
        time.sleep(0.005)
    stop[0] = True
    w = Watch()
    print(f"cc-pulse: a board write reached the feed in {seen * 1000:.0f} ms" if seen is not None else
          "cc-pulse: a board write never reached the feed")
    case("a board write reaches the feed within 400 ms (inotify, not the tick; ~35 ms when idle)",
         seen is not None and (seen < 0.4 or w.fd < 0))
    w.close()
    case("a closed Watch holds no descriptor", w.fd == -1)
    st = f"{tmp}/state"
    case("a write to a file the pulse reads re-collects; a log beside it does not",
         all(wanted(x) for x in (f"{st}/home.json", f"{st}/fund/panel.json", f"{tmp}/boards/r.json",
                                 f"{tmp}/land/queue.log", f"{tmp}/land/r-7.json", f"{tmp}/sessions/30.json",
                                 f"{st}/vitals/current.json", f"{st}/fund"))
         and not any(wanted(x) for x in (f"{st}/pulse.log", f"{st}/model.log", f"{st}/reconcile.log", f"{st}/pulse.json",
                                         f"{st}/r/w1/loop.log", f"{st}/r/loop.log", f"{tmp}/land/r-7.lock",
                                         f"{st}/statusline/s30.json", f"{tmp}/boards/r.json.tmp")))
    case("a busy session's statusline is not watched; the 1 s tick reads it",
         not any(d.rstrip("/").endswith("/statusline") for d in inputs()))

    # the producer writing to a file of its own choosing does not set itself off
    th.join(3)
    custom, n = f"{tmp}/state/custom.json", []
    stop = [False]

    def emit(q):
        n.append(time.monotonic())
        write(q, custom)
    th = threading.Thread(target=feed, args=(emit, lambda: stop[0], proc), kwargs={"out": custom}, daemon=True)
    th.start()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 1.6:            # chatty logs beside the inputs, written all the while
        for lg_ in (f"{tmp}/state/pulse.log", f"{tmp}/state/r/w1/loop.log"):
            with open(lg_, "a") as fh:
                fh.write("a line\n")
        time.sleep(0.02)
    stop[0] = True
    th.join(3)
    case("--out elsewhere, and logs appended 50 times a second beside the inputs: none of it collects more "
         "(two to start, then the 1 s tick)", os.path.exists(custom) and 2 <= len(n) <= 4)

    # landed() from two threads at once reads the log once
    _LOG.update(ino=None)
    res = []
    ths = [threading.Thread(target=lambda: res.append(list(landed()))) for _ in range(8)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    case("landed() called from several threads at once gives each the same answer",
         len(res) == 8 and all(r == res[0] for r in res) and res[0] and _LOG["off"] == os.path.getsize(f"{tmp}/land/queue.log"))
    write(p)
    case("write() leaves the pulse whole and no tmp file", json.load(open(out_path()))["v"] == V
         and not os.path.exists(out_path() + ".tmp"))
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"cc-pulse selfcheck: {ok} passed, {bad} failed")
    return 1 if bad else 0
