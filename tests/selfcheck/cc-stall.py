# cc-stall's selfcheck: the cases behind `cc-stall selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-stall execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    global STATE, LOG, SETTLE
    d = tempfile.mkdtemp(prefix="cc-stall-sc.")
    STATE, LOG, SETTLE = f"{d}/stall.json", f"{d}/stall.log", 0
    rows = f"{d}/rows"
    stub = f"{d}/board"
    with open(stub, "w") as f:
        f.write(f"#!/bin/sh\n[ -f {d}/refuse ] && exit 1\nprintf '%s|%s|%s\\n' \"$3\" \"$4\" \"$CC_BRIEF_MACHINE\" >> {rows}\n")
    os.chmod(stub, 0o755)
    os.environ.update(CC_STALL_BOARD=stub, CC_STALL_REPO="ctl")
    ok = bad = 0

    def k(cond, what):
        nonlocal ok, bad
        if cond:
            ok += 1
        else:
            bad += 1; print(f"FAIL: {what}")

    def raised():
        try:
            return open(rows).read().splitlines()
        except OSError:
            return []

    def fresh():
        for p in (STATE, rows, f"{d}/refuse"):
            if os.path.exists(p):
                os.remove(p)

    import io, contextlib
    q = contextlib.redirect_stdout(io.StringIO())

    # 1 the dev-channels dialog at a live claude is cleared with the digit 1, and raises nothing
    fresh(); t = Fake(); w = t.add("box", DEV, after=READY)
    with q: run(t, True, 1000)
    k(t.keys == [(w, "1")], "dev-channels dialog: the digit 1, once — never Up, which wraps to 2. Exit")
    k(raised() == [], "…and a dialog it cleared raises no row")
    # 2 …but not at a DEAD pane that still shows it (the 2026-09-23 loop pressed into exactly that)
    fresh(); t = Fake(); t.add("box", DEV + "\nclaude exited (1) - restarting in 15s\n", live=False)
    with q: run(t, True, 1000)
    k(t.keys == [], "a dead pane still showing the dialog gets no key")
    # 3 …nor with its footer not at the bottom, nor with a permission word on the screen, nor in copy mode, nor bare
    for scr, what in ((DEV + "\n❯ typed by the owner\n", "footer not at the bottom"), (PERM, "a permission word")):
        fresh(); t = Fake(); t.add("box", scr)
        with q: run(t, True, 1000)
        k(t.keys == [], f"no key with {what}")
    fresh(); t = Fake(); t.add("box", DEV, mode=True)
    with q: run(t, True, 1000)
    k(t.keys == [], "no key into a pane somebody is scrolling")
    fresh(); t = Fake(); t.add("box", DEV)
    with q: run(t, False, 1000)
    k(t.keys == [] and raised() == [], "without --apply: nothing pressed, nothing raised")
    # 4 a known dialog that stays up after its key is unknown from then on: never pressed twice, raised once
    fresh(); t = Fake(); w = t.add("box", DEV, after=DEV)
    with q:
        for s in (1000, 1120, 1240, 1360):
            run(t, True, s)
    k(t.keys == [(w, "1")], "a known dialog its key did not close is pressed once, not every pass")
    k(len(raised()) == 1 and re.match(r"raised-stall-box-dialog-\d{8}\|", raised()[0]), "…and raised once, as a dialog")
    # 5 an unknown dialog: nothing pressed, raised once after STAND_S and two passes, never again while it stands
    fresh(); t = Fake(); t.add("proj@voice", ODD)
    with q:
        run(t, True, 1000)
        k(raised() == [], "an unknown dialog seen once is not raised yet")
        run(t, True, 1000 + STAND_S)
        run(t, True, 1000 + STAND_S + 120); run(t, True, 1000 + STAND_S + 240)
    k(t.keys == [], "an unknown dialog gets no key")
    r = raised()
    k(len(r) == 1 and re.fullmatch(r"raised-stall-proj-voice-dialog-\d{8}", r[0].split("|")[0]) and r[0].endswith("|1"),
      f"an unknown dialog is raised once, a machine row named after its window: {r}")
    k("main:proj@voice is stuck" in (r[0] if r else ""), "…and its title names the window")
    # …it closes and comes back: a new stall, a new report
    t.scr["@0"] = READY
    with q: run(t, True, 2000)
    t.scr["@0"] = ODD
    with q: run(t, True, 2100); run(t, True, 2100 + STAND_S)
    k(len(raised()) == 2, "the same dialog back after it closed is a new stall, raised again")
    # 6 a relaunch loop: raised once while it runs, re-armed when it stops
    fresh(); t = Fake(); line = "claude exited (1) - restarting in 15s (Ctrl-C for a shell)\n"
    t.add("box", "$ ", hist=line, live=False)
    with q:
        run(t, True, 1000)
        t.hist["@0"] = line * 5; run(t, True, 1120)
    r = raised()
    k(len(r) == 1 and re.match(r"raised-stall-box-loop-\d{8}\|", r[0]), f"a relaunch loop is raised: {r}")
    k(t.keys == [], "…and nothing is pressed for it")
    with q:
        t.hist["@0"] = line * 9; run(t, True, 1240)
    k(len(raised()) == 1, "a loop still running is not raised a second time")
    with q:
        run(t, True, 1360)
        t.hist["@0"] = line * 13; run(t, True, 1480)
    k(len(raised()) == 1, "one still pass inside a backoff does not re-arm the report")
    with q:
        for s in (1600, 1720, 1840, 1960):
            run(t, True, s)
        t.hist["@0"] = line * 17; run(t, True, 2080)
    k(len(raised()) == 2, "a loop that stopped past LOOP_REARM and started again is a new stall")
    # a slow loop in cc-rc's 120 s backoff: +1 on most passes, a 0 between, raised exactly once
    fresh(); t = Fake(); t.add("box", "$ ", hist=line, live=False); n, s = 1, 1000
    with q:
        for g in (0, 1, 1, 1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1):
            n += g; t.hist["@0"] = line * n; run(t, True, s); s += 150
    k(len(raised()) == 1, f"a slow loop with a still pass between relaunches is raised once: {raised()}")
    # a slow one: one relaunch per pass, three passes running
    fresh(); t = Fake(); t.add("box", "$ ", hist=line, live=False)
    with q:
        for i, s in enumerate((1000, 1120, 1240, 1360)):
            t.hist["@0"] = line * (1 + i); run(t, True, s)
    k(len(raised()) == 1, "one relaunch on each of three passes running is a loop too")
    # the first look, a cleared history and a long gap are baselines, not growth
    fresh(); t = Fake(); t.add("box", "$ ", hist=line * 40, live=False)
    with q:
        run(t, True, 1000)
        t.hist["@0"] = line * 44; run(t, True, 1000 + LOOP_GAP + 1)
    k(raised() == [], "an old count seen first, or after a long gap, raises nothing")
    # 7 a healthy session — ready, or mid-turn — is left alone, and its state dropped
    fresh(); t = Fake(); t.add("box", READY, hist=line); t.add("lessons", BUSY)
    with q:
        for s in (1000, 1120, 1240, 1360):
            run(t, True, s)
    k(t.keys == [] and raised() == [], "a ready session and a busy one: no key, no row")
    k(not any("dialog" in x for x in load()), "…and no dialog state kept for them")
    # 8 a board that refuses: tried again next pass, TRIES times at most
    fresh(); open(f"{d}/refuse", "w").close(); t = Fake(); t.add("box", ODD)
    with q:
        for i in range(8):
            run(t, True, 1000 + i * STAND_S)
    st = load()
    k(st.get("box\tdialog", {}).get("tries") == TRIES, f"a refused row is retried {TRIES} times, then left: {st}")
    # 9 a window that is gone takes its state with it; a long window name still makes a dispatchable row name
    t.wins = []
    with q: run(t, True, 9000)
    k(load() == {}, "a window gone from tmux leaves no state")
    k(len(row_name("x" * 90, "dialog")) <= 64 and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}",
      row_name("lessons/ece203 x", "loop")), "row names stay inside cc's valid_name")
    k(row_name("box", "loop", 1000) != row_name("box", "loop", 1000 + 3600),
      "a later stall of the same kind in the same window gets a row of its own, never the first one's")
    # 10 one broken window does not stop the pass
    fresh(); t = Fake(); t.add("bad", ODD); t.add("box", DEV, after=READY)
    orig = t.history
    t.history = lambda wid: (_ for _ in ()).throw(RuntimeError("boom")) if wid == "@0" else orig(wid)
    with q: run(t, True, 1000)
    k(t.keys == [("@1", "1")], "a window that throws is logged and skipped; the next is still cleared")

    # 11 the other half of the 2026-09-23 fix: cc-rc beside this copy clears the dead screen before it starts
    # accept-dialog, so the dialog text that one reads is the new claude's, never the last one's
    try:
        rc = open(f"{BIN}/cc-rc").read()
        k(-1 < rc.find("printf '\\033[H\\033[2J'") < rc.find("accept-dialog box"),
          "cc-rc clears the screen before each launch's accept-dialog")
    except OSError:
        k(False, "cc-rc is beside cc-stall")

    print(f"cc-stall selfcheck: {ok} passed, {bad} failed")
    return 1 if bad else 0
