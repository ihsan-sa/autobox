# cc-handoff's selfcheck: the cases behind `cc-handoff selfcheck` (check.sh and selftest.sh run it that way; there is
# no other entry point). Not a module — cc-handoff execs this file INSIDE ITS OWN NAMESPACE and calls run_selfcheck(),
# so every name here is the tool's: `global HANDOFF, RECORDS, …` rebinds the tool's globals and the stubs for tmux,
# run() and out() land on the tool as they did when this body lived in it. Two consequences: no module docstring here
# (it would replace the tool's __doc__, which prints as usage), and no top-level name but run_selfcheck (anything
# else lands in the tool).
def run_selfcheck():
    os.environ.pop("CC_HANDOFF_NO_KICK", None)   # the suite exports it for ITS fixtures; every start() here is stubbed and the kick cases need the spawn
    nlo = os.environ.pop("CC_NOTIFY_LOG_ONLY", None)   # the suite sets it; these cases read what run() was handed, not what a door did with it
    import tempfile
    global HANDOFF, RECORDS, STATE, DEV, win_id, pane_live, pane_live_id, tmux, run, out, notify, self_wid, age, worker_held, seat_of, measure_seat
    real_out = out
    real_held = worker_held      # the real one: every case below rebinds worker_held to a stub
    _real_measure = measure_seat   # the real one: the rotation cases stub measure_seat and check one refusal of the real
    p = f = 0

    def ok(what, cond):
        nonlocal p, f
        if cond:
            p += 1
            print(f"  ✓ {what}")
        else:
            f += 1
            print(f"  ✗ {what}")

    with tempfile.TemporaryDirectory() as d:
        HANDOFF = os.path.join(d, "handoff")
        RECORDS = os.path.join(d, "context")
        STATE = os.path.join(d, "state")               # derive/retire touch spool dirs under it: never the real one
        # nothing real is started, killed or pushed from a selfcheck: tmux and the shell-outs are stubbed
        wins, msgs, dead, me, tcalls, panes = {"r1": "@1"}, [], set(), [""], [], {}

        def win_id(n):
            return wins.get(n)

        def pane_live(n):
            return n in wins and n not in dead      # `dead` = the window is still there, the session in it is not

        def pane_live_id(wid):
            return any(i == wid and n not in dead for n, i in wins.items())

        held = set()                                # window ids a headless `claude -p` holds: worker_held()'s answer

        def worker_held(wid):
            return wid in held

        ages = {}

        def age(pid):
            return ages.get(pid, 0)                 # the orphan stub hands the window id over as the pane pid

        def self_wid():
            return me[0]                            # the window --retire is pretending to run in

        def tmux(*a, _log=True, **k):
            if _log:
                tcalls.append(a)
            if ";" in a:                            # `cmd … ; cmd …`: one call, run in order
                i = a.index(";")
                tmux(*a[:i], _log=False); tmux(*a[i + 1:], _log=False)
                return ""
            if a[0] == "list-windows":
                if "pane_start_command" in " ".join(a):   # lanes(): name, id, pane pid, the command it was made with
                    return "\n".join("\t".join([n, i, "4242", f"cc-land {n[4:]} --wait"]) for n, i in wins.items())
                if "pane_pid" in " ".join(a):       # orphans(): id, "pid", name
                    return "\n".join(f"{i} {i} {n}" for n, i in wins.items())
                return "\n".join(wins.values())
            if a[0] == "capture-pane":
                return shown(a[-1])
            if a[0] == "display-message":       # `-t <window id> "#{window_id}:#{pid}"`: the mark cc-board would
                return f"{a[a.index('-t') + 1]}:900"   # stamp for that window. 900 stands in for the server pid,
                                                       # which is one number for every window on the server.
            if a[0] == "new-window":
                wins[a[a.index("-n") + 1]] = "@%d" % (len(wins) + 1)
            elif a[0] == "kill-window":
                for n, i in list(wins.items()):
                    if i == a[-1]:
                        del wins[n]
            elif a[0] == "rename-window":
                for n, i in list(wins.items()):
                    if i == a[a.index("-t") + 1]:
                        wins[a[-1]] = wins.pop(n)
            return ""

        # the fake TUI: a pane is a string, or a callable drawing the screen of the moment. `tui` is its
        # keyboard log — when accept-dialog was asked per window, and what was typed where, and when.
        BOX = '╭──────────────────────╮\n│ > Try "fix the bug"   │\n╰──────────────────────╯'
        IDLE = BOX + "\n  " + IDLE_HINT
        DIALOG = ("WARNING: Loading development channels can be unsafe.\n ❯ 1. I am using this for local "
                  "development\n   2. Exit\n Enter to confirm · Esc to cancel")
        tui = {"asked": {}, "typed": []}

        def shown(wid):
            v = panes.get(wid, "")
            return v() if callable(v) else v

        def run(argv, wait=True):
            msgs.append(list(argv))
            if argv[0].endswith("cc-slack") and argv[1:2] == ["accept-dialog"]:
                tui["asked"][argv[2]] = time.time()
            if argv[0].endswith("cc-msg"):        # the keyboard: keys reach whatever is in FRONT of the pane, so
                wid = wins.get(argv[1])           # the stub fails where cc-msg would not type — no window, or a
                                                  # dialog it may not answer (the real one spools there; a handoff
                                                  # that cannot type NOW is what these cases are about)
                if wid is None or any(x in shown(wid) for x in ("Enter to confirm", "development channels")):
                    return False
                tui["typed"].append((wid, argv[2], time.time()))
                if not callable(panes.get(wid)):  # a static screen: draw the taken turn the way the TUI does
                    panes[wid] = shown(wid) + "\n> " + argv[2] + "\n\n✻ Thinking… (" + WORKING + ")\n" + BOX
            return True

        def notify(t, m):
            msgs.append(["notify", t, m])


        ok("a target with a track slugs to one flat file",
           os.path.basename(path("r1/t1")) == "r1--t1.json" and os.path.basename(path("r1")) == "r1.json")
        ok("a target cannot escape the record dir", not TARGET_RE.match("../etc")
           and not TARGET_RE.match("r1/t1/x") and TARGET_RE.match("r1/t1"))

        os.environ.pop("CC_HANDOFF", None)
        role0 = os.environ.pop("CC_ROLE", None)   # …and neither may the ROLE of whoever is running them: these
                                                  # gates are run from a --go worker as often as from a session,
                                                  # and `worker()` would then refuse every start below. Same trap
                                                  # as $CC_HANDOFF above, restored at the end of the section.
        # recurring-defect-ok: pause-hold-missing — the `--go` above is a comment naming the ROLE these gates run
        # under, not a launch: nothing in this file starts a worker or writes the board. cc-handoff itself takes no
        # `cc-pause is <target>` hold by design — that parks the whole project (its loops, the landing queue, publish,
        # the janitor), far wider than the one retiring session a handoff is about.
        ok("no record at all -> nothing is open", read("r1") is None and status("r1") == 1)
        import contextlib, io
        e = io.StringIO()
        with contextlib.redirect_stderr(e), contextlib.redirect_stdout(io.StringIO()):
            gone = [main([c, "r1"]) for c in ("--event", "--due", "--relay")]
            gone.append(main(["--overlap", "r1", "--pct", "41"]))
        ok("the context-line machinery is gone: --event, --due, --relay and --pct are refused outright",
           gone == [1] * 4 and "unknown option --pct" in e.getvalue() and read("r1") is None)
        ok("an overlap needs a live window", start("nosuch") == 1)
        wins["r1/w1"] = "@w1"
        held.add("@w1")
        e = io.StringIO()
        with contextlib.redirect_stderr(e), contextlib.redirect_stdout(io.StringIO()):
            held_rc = start("r1/w1")
        ok("start() refuses a target whose window a headless worker holds, and says the same thing worker() says "
           "\u2014 worker() reads the CALLER's CC_ROLE, so a planning seat running `cc handoff <repo> <track>` walked "
           "straight past it and gated the running iteration through cc-guard (review of #501)",
           held_rc == 1 and read("r1/w1") is None and WORKER_REFUSAL in e.getvalue())
        held.discard("@w1")
        ok("\u2026and the same target hands off once no headless session holds it", start("r1/w1") == 0)
        ok("worker_held() says HELD when the pane will not answer \u2014 tmux gone, the window dead, ps "
           "timed out: a wrong refusal costs a retry, a wrong allow costs a gated worker and a second "
           "paid session in its worktree, so unreadable is never read as 'not a worker' (review of #501)",
           real_held("@w1") is True)     # the stub tmux answers "" to list-panes, which is the misread
        # WHAT A PANE'S PROCESSES SAY, on ps text. The loop's own pane line, an iteration under it, and the gap
        # between iterations all read HELD; a session — a fresh one, or a successor whose system prompt carries a
        # handoff brief naming cc-loop and `claude -p`, with its own grep for cc-loop running under it — does not.
        # `cc handoff --overlap lessons` refused exactly that seat on 2026-09-19 (raised-cc-handoff-wrapper-…).
        PS = "\n".join([
            "100 1 bash -c CC_CLAUDE=/home/u/.local/bin/claude /home/u/core/bin/cc-loop r1 w1 --max-iter 1; exec bash",
            "101 100 bash /home/u/core/bin/cc-loop r1 w1 --max-iter 1",
            "102 101 timeout 3600 /home/u/.local/bin/claude -p # TASK do the thing; never run cc-loop yourself",
            "200 1 bash /home/u/core/bin/cc __runnext r1 abc123 sid-1",
            "201 200 /home/u/.local/bin/claude --dangerously-skip-permissions --append-system-prompt You are the "
            "SUCCESSOR. dispatch with cc r1 t --go; a worker runs claude -p under cc-loop --remote-control r1",
            "202 201 bash -c grep cc-loop ~/.cc/state/r1/w1/loop.log | tail -1",
            "203 201 /home/u/.local/bin/claude -p summarise this",   # a headless CHILD of a session: its own tool call
            "300 1 bash",                                            # the loop ended: `exec bash` left a bare shell
            "400 1 bash -c CC_CLAUDE=/home/u/.local/bin/claude /home/u/core/bin/cc-loop r1 w2; exec bash",
            "500 1 bash -c cc-sandbox member ws1 t1 -- /home/u/core/bin/cc-loop ws1 t1 --max-iter 3; exec bash",
            "600 1 timeout 3600 /home/u/.local/bin/claude -p # TASK a bare iteration, no loop above it"])
        ok("held_in: a worker's pane is HELD — read off its cc-loop line, whose first token is an env setting",
           held_in(["100"], PS) and held_in(["400"], PS))
        ok("...the loop between two iterations is held too (the LOOP is the tell), and so is a `claude -p` alone",
           held_in(["400"], PS) and held_in(["600"], PS) and held_in(["500"], PS))
        ok("...a successor-born seat is NOT: its system prompt naming cc-loop and `claude -p`, its own grep for "
           "cc-loop and a headless tool call under it are the session's own, not a worker's",
           not held_in(["200"], PS) and not held_in(["201"], PS))
        ok("...and a bare shell, or a pane ps does not know, is not a worker either",
           not held_in(["300"], PS) and not held_in(["999"], PS))
        ok("control: read from the seat's children directly — where the walk this replaced arrived — both read "
           "held; only the interactive parent above them shields them",
           held_in(["202"], PS) is True and held_in(["203"], PS) is True)
        clear("r1/w1")
        wins.pop("r1/w1", None); wins.pop("r1/w1" + NEXT, None)    # this case's fixture windows, not the suite's
        ov = os.environ.get("CC_HANDOFF_OVERLAP")
        os.environ["CC_HANDOFF_OVERLAP"] = "0"           # unread: the overlap is the only handoff, no switch gates it
        ok("an overlap starts on a live window — and no config switch gates it (CC_HANDOFF_OVERLAP is unread)",
           start("r1") == 0)
        os.environ.pop("CC_HANDOFF_OVERLAP", None) if ov is None else os.environ.__setitem__("CC_HANDOFF_OVERLAP", ov)
        rec = read("r1")
        ok("the record names the predecessor as live", rec and rec["live"] == "predecessor")
        ok("the deadline is bounded, and the cap is 20 min — an overlap runs two planning-class sessions side "
           "by side, and the retiring seat measured ~15 of the old 45 min as actually used (2026-09-08)",
           DEFAULT_MAX == 20 * 60 and rec["deadline"] - rec["started"] == DEFAULT_MAX)
        ok("a second overlap for the same target is refused", start("r1") == 1)
        nw = [a for a in tcalls if a[0] == "new-window"][-1]
        ok("the successor is told ITS OWN window name, so it accepts the startup dialog in its own pane and "
           "not in its predecessor's — one parked on that confirmation until a human noticed (2026-09-01)",
           "CC_HANDOFF_WINDOW='r1~next' " in nw[-1] and nw[nw.index("-n") + 1] == "r1~next")
        # …and the number is still the box's to set: CC_HANDOFF_OVERLAP_MAX through cc-config, env first.
        wins["r1cap"] = "@1cap"
        os.environ["CC_HANDOFF_OVERLAP_MAX"] = "300"
        ok("CC_HANDOFF_OVERLAP_MAX overrides the default, and the brief the successor reads names the same "
           "number as the deadline", start("r1cap") == 0
           and read("r1cap")["deadline"] - read("r1cap")["started"] == 300
           and "5 minutes at most" in open(brief_path("r1cap")).read())
        os.environ.pop("CC_HANDOFF_OVERLAP_MAX", None)
        abandon("r1cap")
        ok("an overlap that ends without a cutover takes its own quiet mark back — clear() is the failsafe "
           "every ending goes through, so no target is left out of the drive loop for good",
           not os.path.exists(quiet_path("r1cap")) and read("r1cap") is None)
        wins.pop("r1cap~next", None); wins.pop("r1cap", None)

        # ---- QUIET WHILE IT IS OPEN. The successor's questions are the only thing worth a full-context wake
        # from a session that is handing over; a drive-loop tick during the overlap buys one for work it is
        # about to give away. The mark is cc-pulse's own opt-out — no second mechanism to keep in step.
        ok("the overlap marks the retiring target quiet, with cc-pulse's own opt-out",
           os.path.exists(quiet_path("r1")) and read("r1")["quiet"] == [QUIET_MARK])
        ok("...and the record says which mark is OURS, so nothing else's is taken back later",
           quiet_path("r1") == os.path.join(STATE, "r1", "pulse.off"))
        wins["r1q"] = "@1q"
        os.makedirs(os.path.join(STATE, "r1q"), exist_ok=True)
        open(quiet_path("r1q"), "w").write("the owner switched this one off\n")
        ok("a pulse.off that was already there is somebody else's decision: not claimed, not rewritten",
           start("r1q") == 0 and read("r1q")["quiet"] == []
           and "owner" in open(quiet_path("r1q")).read())
        abandon("r1q")
        ok("...and abandoning the overlap leaves it exactly where it was", os.path.exists(quiet_path("r1q")))
        wins.pop("r1q~next", None); wins.pop("r1q", None)

        # Hermetic on purpose: the CALLER's $HOME and $CC_CTX_RECORDS are exactly what this case is about, so
        # neither may decide it — selftest.sh sets the latter, and the case passed alone and failed in the run.
        env0 = {k: os.environ.get(k) for k in ("HOME", "CC_CTX_RECORDS")}
        os.environ.pop("CC_CTX_RECORDS", None)
        os.environ["HOME"] = os.path.join(d, "fakehome")
        got = [handoff_log()]
        os.environ["CC_CTX_RECORDS"] = RECORDS
        got.append(handoff_log())
        ok("a detached child's log follows $HOME, and $CC_CTX_RECORDS ahead of it — a fixture leaves no line "
           "in the box's real handoff.log",
           got == [os.path.join(d, "fakehome", ".cc", "state", "context", "handoff.log"),
                   os.path.join(RECORDS, "handoff.log")])
        for k, v in env0.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

        ok("every prompt this file types into a session leads with the machine tag — the kick, the retirement "
           "message and the stay message — so the ask ledger skips them by the tag and never by their wording",
           all(p.startswith(MACHINE) for p in (KICK, RETIRE_MSG, STAY_MSG)))

        # ---- the successor must be BRIEFED, and the brief SEEN to land. The brief itself rides in the system
        # prompt, which nothing acts on by itself; on 2026-09-01 a successor sat blank for 25 min because the
        # startup dialog ate the prompt typed at it and nobody read the pane back.
        env1 = {k: os.environ.get(k) for k in ("CC_HANDOFF_KICK_WAIT", "CC_CTX_RECORDS", "HOME", "CC_NOTIFY_LOG_ONLY",
                                               "CC_HANDOFF_NO_KICK")}
        os.environ["CC_HANDOFF_KICK_WAIT"] = "0"        # no naps, and no waiting on a window that will not come
        os.environ.pop("CC_HANDOFF_NO_KICK", None)      # the suite sets it for ITS fixtures; these cases are about the kick
        os.environ["CC_CTX_RECORDS"] = RECORDS          # ...and the detached child's log line stays in here
        os.environ["HOME"] = os.path.join(d, "fakehome")   # ...as does the journal line kick_lost() leaves
        ok("start() leaves a detached child to brief the successor",
           any(isinstance(a, list) and a[-3:-1] == ["--kick", "r1"] for a in msgs))
        ok("...and the successor's pane shell EXECS cc, so claude is the pane's direct child — where cc-msg looks "
           "(forked, it was a grandchild and every automatic kick was refused)",
           re.search(r" exec \S*cc __runnext ", nw[-1]) and not nw[-1].endswith("exec bash"))
        nid = wins["r1~next"]
        panes[nid] = IDLE
        ok("a successor at its prompt gets its opening prompt — a brief in the system prompt starts no turn",
           kick("r1", "abc") == 0)
        last = [a for a in msgs if isinstance(a, list) and a[0].endswith("cc-msg")][-1]
        ok("...typed into r1~next, ITS window, naming what it is the successor of",
           last[1] == "r1~next" and "SUCCESSOR for r1" in last[2])
        ok("...and leading with the machine tag, so the successor does not spend its first turn declining an "
           "owner row about its own startup (a121, a126, a131)", last[2].startswith(MACHINE))
        t = last[2]
        ok("...and landing is checked by reading the pane BACK", landed(nid, t))
        wrap = "\n".join(t[i:i + 17] for i in range(0, len(t), 17))   # the TUI wraps at the pane width
        panes[nid] = "> " + wrap + "\n\n⏺ Read(progress.md)\n" + IDLE
        ok("...a wrapped echo above the successor's first tool line counts as landed", landed(nid, t))
        panes[nid] = "│ > " + t[:40] + "\n│   " + t[40:80] + "\n  " + IDLE_HINT
        ok("...but the text still SITTING in the input box does not — Enter was not taken (03:32Z's successor)",
           not landed(nid, t))
        panes[nid] = "Welcome to Claude Code\n" + IDLE
        ok("...and a pane that never took it does not pass as landed", not landed(nid, t))
        ok("the child's one log line stays inside the fixture — no test writes real state",
           os.path.exists(os.path.join(RECORDS, "handoff.log")))

        # An #alerts line is now a cc-notify call with the `alerts` KIND — the table puts that at rung 4, which
        # is #alerts. Counting the channel name here would have gone green on a file that named it itself.
        posts = lambda: sum(1 for a in msgs if isinstance(a, list) and a[1:3] == ["--kind", "alerts"])
        typed = lambda: sum(1 for a in msgs if isinstance(a, list) and a[0].endswith("cc-msg"))
        told0, typed0 = posts(), typed()
        panes[nid] = "Do you trust the files in this folder?\n  Enter to confirm · Esc to cancel"
        ok("a prompt is never typed at an open dialog — that is the dialog eating it, again",
           kick("r1", "abc") == 1 and typed() == typed0)
        ok("...cc-slack is asked to press through THAT window first",
           any(isinstance(a, list) and a[:3] == [os.path.join(BIN, "cc-slack"), "accept-dialog", "r1~next"]
               for a in msgs))
        ok("...and a successor left blank goes to #alerts, not left silent beside a live session",
           posts() == told0 + 1)
        jp = os.path.join(d, "fakehome", ".cc", "state", "r1", "planning-handoff.md")
        ok("...and into the target's journal, where the next session reads first",
           os.path.exists(jp) and "sitting blank in main:r1~next" in open(jp).read())
        panes[nid] = lambda: ""                          # live, and never draws a thing
        told0, typed0 = posts(), typed()
        ok("a pane that never drew a prompt is NOT a dialog: one try at the deadline, judged by the pane — "
           "which took nothing, so the owner hears", kick("r1", "abc") == 1 and typed() == typed0 + 1 and posts() == told0 + 1)

        # THE LATE DIALOG, on the real loop with a fake clock: the pane is live from the first instant (the
        # shell forked cc), Claude Code draws the dialog seconds later, and it clears only once pressed.
        real_t, real_s = time.time, time.sleep
        clk = [real_t()]
        time.time = lambda: clk[0]
        # a sub-second sleep is subprocess's own wait poll (cfg() shells out to cc-config): it sleeps for real and
        # leaves the clock alone — on the fake clock it spun the child's whole run into minutes (flake, 2026-09-02)
        time.sleep = lambda n: real_s(n) if 0 < n < 1 else clk.__setitem__(0, clk[0] + (n or 1))
        os.environ["CC_HANDOFF_KICK_WAIT"] = "60"
        tui["asked"].pop("r1~next", None)                # the earlier dialog's press is not this one's
        t0 = clk[0]

        def late():
            if clk[0] - t0 < 4:
                return ""                                        # booting: live, nothing drawn yet
            asked = tui["asked"].get("r1~next")
            if asked is None or clk[0] < asked + 3:
                return DIALOG                                    # up until cc-slack presses it through
            turns = [x for x in tui["typed"] if x[0] == nid and x[2] >= asked + 3]
            return IDLE if not turns else "> " + turns[-1][1] + "\n\n✻ Thinking… (" + WORKING + ")\n" + BOX

        panes[nid] = late
        n0, typed0 = len(tui["typed"]), typed()
        acc0 = sum(1 for a in msgs if isinstance(a, list) and a[1:3] == ["accept-dialog", "r1~next"])
        rc = kick("r1", "abc")
        sent = tui["typed"][n0:]
        ok("a dialog that draws LATE is waited out: the prompt is typed once, after it has shown AND cleared",
           rc == 0 and len(sent) == 1 and typed() == typed0 + 1
           and sent[0][2] >= tui["asked"]["r1~next"] + 3 and clk[0] - t0 < 60)
        ok("...and cc-slack was asked to press it through, once",
           sum(1 for a in msgs if isinstance(a, list) and a[1:3] == ["accept-dialog", "r1~next"]) == acc0 + 1)
        tui["asked"].pop("r1~next"); t0 = clk[0]
        panes[nid] = lambda: "" if clk[0] - t0 < 4 else DIALOG   # a dialog nobody's Enter ever clears
        n0, told0 = len(tui["typed"]), posts()
        ok("...a dialog that never clears is never typed at, and the owner hears within the wait",
           kick("r1", "abc") == 1 and len(tui["typed"]) == n0 and posts() == told0 + 1 and clk[0] - t0 <= 62)

        time.time, time.sleep = real_t, real_s

        # THE FLIGHT LINE IS READ OFF THE LIVE WORKER TABLE, never asserted. 2026-09-16: the brief said "a background
        # task is still running" beside a workers section that said (none), and one of the successor's one batch
        # of questions went on a phantom (raised-handoff-brief-reports-a-dead-worker-as-live).
        wins["r30"] = "@30"
        with contextlib.redirect_stdout(io.StringIO()):
            start("r30", "", "a background task is still running")
        b30 = open(brief_path("r30")).read()
        ok("with no live loop under the repo the brief carries NO 'unfinished right now' line; the caller's --in-flight "
           "text is kept as the predecessor's own note, labelled as such, never promoted to a fact",
           "Unfinished RIGHT NOW" not in b30 and "predecessor's own note" in b30
           and "a background task is still running" in b30)
        clear("r30"); wins.pop("r30~next", None)
        os.makedirs(os.path.join(STATE, "r30", "w9"))
        with open(os.path.join(STATE, "r30", "w9", "loop.log"), "w") as fh:
            fh.write("iteration 2: building\n")                   # a loop that wrote a moment ago: live to --brief too
        with contextlib.redirect_stdout(io.StringIO()):
            start("r30")
        b30 = open(brief_path("r30")).read()
        ok("...and with one, the line names that loop — off the same table --brief prints — and no note is invented",
           "Unfinished RIGHT NOW" in b30 and "w9" in b30 and "predecessor's own note" not in b30
           and "w9" in live_workers("r30"))
        clear("r30"); wins.pop("r30~next", None); wins.pop("r30", None)

        # ---- --replace: a MEMBER workspace's live session handed off onto the boundary the box has NOW. #453
        # (2026-09-12) bound core/mail into the member sandbox at launch; the session already running kept its
        # old bwrap, and its successor — inside `cc-sandbox member`, where the record is not bound — could never
        # run --ready, so the owner's test waited on a hand relaunch. The host cuts over for it instead.
        dev0 = DEV
        DEV = os.path.join(d, "dev")
        os.makedirs(os.path.join(DEV, "ws1", ".cc"))
        open(os.path.join(DEV, "ws1", ".cc", "member-workspace"), "w").close()
        e = io.StringIO()
        with contextlib.redirect_stderr(e), contextlib.redirect_stdout(io.StringIO()):
            rr = [replace("r1/w1"), replace("nomember")]
        ok("--replace is for a member workspace's session only: a track, or a repo with no member marker, is told "
           "to use --overlap and no record is opened",
           rr == [1, 1] and "member workspace" in e.getvalue() and read("r1/w1") is None and read("nomember") is None)
        wins["ws1"] = "@ws1"
        o = io.StringIO()
        with contextlib.redirect_stdout(o):
            rc = replace("ws1")
        wrec = read("ws1")
        ok("--replace opens the overlap for the workspace: the record says the HOST cuts over, and the line says so",
           rc == 0 and bool(wrec) and wrec.get("host_cutover") is True and "the host cuts over" in o.getvalue())
        ok("...and its brief says so too — the successor is told it is live and that --ready is not its to run, "
           "where any other successor's brief tells it to run --ready itself",
           "the host cut you over" in open(brief_path("ws1")).read()
           and "Unfinished RIGHT NOW" not in open(brief_path("ws1")).read()
           and "the host cut you over" not in open(brief_path("r1")).read()
           and "run `cc-handoff --ready`" in open(brief_path("r1")).read())
        # …AND A LIVE LOOP UNDER THE WORKSPACE DOES NOT COST IT THAT NOTICE. The first cut assigned the flight
        # line over it, and a member whose repo had any loop running got the brief that says "run --ready" (#542).
        os.makedirs(os.path.join(DEV, "ws2", ".cc"))
        open(os.path.join(DEV, "ws2", ".cc", "member-workspace"), "w").close()
        os.makedirs(os.path.join(STATE, "ws2", "t1"))
        with open(os.path.join(STATE, "ws2", "t1", "loop.log"), "w") as fh:
            fh.write("iteration 1: building\n")
        wins["ws2"] = "@ws2"
        with contextlib.redirect_stdout(io.StringIO()):
            rc2 = replace("ws2")
        b2 = open(brief_path("ws2")).read()
        ok("...with a live loop under the workspace the brief carries BOTH: the cutover notice and the loop's name "
           "on the 'unfinished right now' line",
           rc2 == 0 and "the host cut you over" in b2 and "Unfinished RIGHT NOW" in b2 and "t1" in b2)
        clear("ws2"); wins.pop("ws2~next", None); wins.pop("ws2", None)
        ok("...while any other kind's overlap keeps the successor's own --ready", read("r1").get("host_cutover") is False)
        nid = wins["ws1~next"]
        panes[nid] = IDLE
        with contextlib.redirect_stdout(io.StringIO()):
            krc = kick("ws1", wrec["id"])
        wrec = read("ws1")
        ok("...and once the successor's opening prompt has LANDED, the kick cuts over for it — it is live and holds "
           "the window name, the old session is retiring, and no window was killed under a session",
           krc == 0 and bool(wrec) and live_side(wrec) == "successor" and wins.get("ws1") == nid
           and wins.get("ws1~old") == "@ws1")
        ok("...the kick of any other successor cuts nothing over — it reads its packet and runs --ready itself",
           live_side(read("r1")) == "predecessor")
        DEV = dev0

        # THE HANDOVER LINE IS THE TABLE'S TO PLACE. This file used to name #alerts itself, which meant the line
        # skipped the table and the test-state rule had to be copied in beside it; both are cc-notify's now.
        n0 = posts(); alert("r1/t1", "🔁 r1/t1: handover — the successor is live")
        ok("a handover line goes out as the `alerts` KIND, which the table places at rung 4 (#alerts) — this "
           "file names no channel of its own", posts() == n0 + 1)
        ok("...under a title the table can read: its SECOND word decides the kind, and the emoji the line "
           "carries is kept out of it (the title '🔁 r1/t1: handover' filed every handover ambient)",
           msgs[-1][msgs[-1].index("-t") + 1] == "r1/t1 handover" and msgs[-1][-1].startswith("🔁"))
        ok("...and it is one cc-notify call, so the synthetic-name and log-only rules that live at that one "
           "door are the only copy of them", msgs[-1][0].endswith("cc-notify") and len(msgs[-1]) == 6)
        for k, v in env1.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

        os.environ["CC_HANDOFF"] = "wrong-id"
        ok("--ready from a session whose CC_HANDOFF does not match is refused", ready("r1") == 1)
        ok("...and the predecessor is still live", read("r1")["live"] == "predecessor")

        os.environ["CC_HANDOFF"] = rec["id"]
        ok("--ready with no target finds the record by CC_HANDOFF", by_id(rec["id"])["target"] == "r1")
        ok("the successor cuts over", ready() == 0)
        ok("the commit point moved ownership forward", read("r1")["live"] == "successor")
        ok("the predecessor was told to journal and exit",
           any("cc-msg" in a[0] for a in msgs if isinstance(a, list)))
        # THE OVERLAP ENDS AT THE READY SIGNAL, not at the deadline: --ready is the successor saying its one
        # batch is answered, and the retirement is started from the commit point itself.
        ok("--ready retires the predecessor there and then — the deadline is the other way out, not the way",
           any(isinstance(a, list) and a[-2:] == ["--retire", "r1"] for a in msgs))
        ok("...and the quiet marks come off with the name: `r1` is the SUCCESSOR's now, and a live session left "
           "out of the drive loop is worse than the wakes this saved",
           not os.path.exists(quiet_path("r1")) and read("r1")["quiet"] == [])
        ok("--ready is idempotent, never a rollback", ready() == 0 and read("r1")["live"] == "successor")
        ok("--abandon after cutover is refused", abandon("r1") == 1 and read("r1")["live"] == "successor")

        lines = [json.loads(l) for l in open(os.path.join(RECORDS, "handoffs.jsonl"))]
        ok("one ledger line per phase, and never two",     # of THIS handoff: the cases above open others
           [l["kind"] for l in lines if l["target"] == "r1"] == ["overlap-started", "overlap-cutover"])

        # a successor that dies before --ready: ownership never moved, so the predecessor never noticed
        clear("r1")
        os.environ.pop("CC_HANDOFF", None)
        wins.pop("r1~next", None)
        wins["r1"] = "@1"
        ok("a fresh overlap opens once the last one is cleared", start("r1") == 0)
        wins.pop("r1~next", None)                       # the successor's window is gone
        ok("successor dead before --ready -> the predecessor is still live",
           read("r1")["live"] == "predecessor" and ready("r1", forced=True) == 2)
        told1 = sum(1 for m in msgs if m and m[0] == "notify")     # a count, not a total: the cases above tell the owner too
        ok("--abandon clears the record and tells the owner once", abandon("r1", "the successor died") == 0
           and read("r1") is None and sum(1 for m in msgs if m and m[0] == "notify") == told1 + 1)
        ok("--abandon on a cleared record is a no-op (never twice)", abandon("r1") == 0
           and sum(1 for m in msgs if m and m[0] == "notify") == told1 + 1)

        # ---- retirement DRAINS the predecessor, then ENDS it. A session cannot exit itself, so the drain
        # expires into a KILL; and the names move at cutover, so an owner attaching lands on the live one.
        os.environ["CC_HANDOFF_RETIRE_GRACE"] = "0"
        os.environ["CC_HANDOFF_DRAIN"] = "0"

        def cutover(t):
            """a target at the moment after the commit point: predecessor alive, successor waiting"""
            wins[t] = "@" + t
            start(t)
            os.environ["CC_HANDOFF"] = read(t)["id"]
            ready(t)
            return read(t)

        # ---- EVERY KIND OF SESSION THIS BOX STARTS, ALL THE WAY THROUGH -----------------------------------
        # Until 2026-09-07 the grammar had room for two shapes out of three, so an ORCHESTRATOR asked about
        # itself came back "is not a target": no orch had ever been handed off, one sat past the context
        # ceiling with no successor and nothing on the box able to start one, and a person had to restart it by
        # hand. A case that only asserts an address is ACCEPTED proves nothing about a handoff completing, so
        # each kind here is driven the whole way — started, cut over, its names moved, retired.
        os.environ.pop("CC_HANDOFF", None)
        for addr, what in (("k1", "session"), ("k1@dash", "orch"), ("k1/t1", "track")):
            ok(f"{addr} is an address, and it is {ARTICLE[what]}",
               bool(TARGET_RE.match(addr)) and kind(addr) == what)
            r = cutover(addr)
            os.environ.pop("CC_HANDOFF", None)
            ok(f"{ARTICLE[what]}: the overlap starts and the record names one live side",
               bool(r) and r["target"] == addr and live_side(r) in ("predecessor", "successor")
               and r["predecessor"]["window"] == addr + OLD)
            ok(f"{ARTICLE[what]}: it reaches CUTOVER — the successor is live, once, on one record",
               r["phase"] == "cutover" and live_side(r) == "successor"
               and [l for l in open(os.path.join(RECORDS, "handoffs.jsonl"))
                    if json.loads(l)["target"] == addr and json.loads(l)["kind"] == "overlap-cutover"])
            ok(f"{ARTICLE[what]}: the names moved, so an owner attaching lands on the live session",
               wins.get(addr) == r["successor"]["tmux"] and addr + OLD in wins and addr + NEXT not in wins)
            ok(f"{ARTICLE[what]}: the ledger row keeps the repo whole and the address whole",
               [json.loads(l) for l in open(os.path.join(RECORDS, "handoffs.jsonl"))
                if json.loads(l)["target"] == addr][-1]["repo"] == "k1")
            ok(f"{ARTICLE[what]}: it retires, and the predecessor's window goes with it",
               retire(addr) == 0 and addr + OLD not in wins and wins.get(addr) == r["successor"]["tmux"])

        # TWO LIVE SESSIONS IN ONE WORKTREE ARE TWO HANDOFFS. `k1` and `k1@dash` share a repo, a checkout and a
        # Slack channel; only the alias tells them apart. Under one key an overlap open on either would refuse
        # the other, both would journal into the same file, and the ledger could not say which was handed off.
        ok("a session a person steers and an orchestrator beside it are separate records",
           path("k1") != path("k1@dash") and slug("k1@dash") == "k1@dash")
        ok("...and separate journals: a shared one hands each the other's handoff entry",
           journal_for("k1") != journal_for("k1@dash") != journal_for("k1/t1"))

        # A JOURNAL KEPT UNDER THE WRONG NAME IS NOT A MISSING JOURNAL. No prompt ever told an orch's own
        # session where its running notes belonged (a track is handed `progress.md` outright; an orch is
        # handed nothing), so at least one (lessons@lessons-site, seen live) kept a `-handover.md` of its own.
        # Before this fix journal_for() only ever named `-handoff.md`, so `--brief` found nothing and printed
        # the journal section empty over 230+ kB of real history sitting one word away.
        with tempfile.TemporaryDirectory() as jd:
            home0 = os.environ.get("HOME")
            os.environ["HOME"] = jd
            try:
                st = os.path.join(jd, ".cc", "state", "j1")
                os.makedirs(st)
                ok("neither name exists yet: a fresh address still gets the canonical one",
                   journal_for("j1@o") == "~/.cc/state/j1/o-handoff.md")
                with open(os.path.join(st, "o-handover.md"), "w") as fh:
                    fh.write("legacy journal\n")
                ok("...a legacy '-handover.md' with no '-handoff.md' beside it is what gets read — the "
                   "regression: an orch's real history was printing as '(none)'",
                   journal_for("j1@o") == "~/.cc/state/j1/o-handover.md")
                with open(os.path.join(st, "o-handoff.md"), "w") as fh:
                    fh.write("canonical journal\n")
                ok("...but the canonical name wins the moment it exists too, so the two never fork",
                   journal_for("j1@o") == "~/.cc/state/j1/o-handoff.md")
            finally:
                if home0 is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = home0

        wins["k2"], wins["k2@dash"] = "@k2", "@k2d"
        ok("...and an overlap open on one does not refuse the other",
           start("k2") == 0 and read("k2") and start("k2@dash") == 0 and read("k2@dash")
           and read("k2")["id"] != read("k2@dash")["id"])
        abandon("k2"); abandon("k2@dash")

        os.environ["CC_ROLE"] = "worker"
        ok("a HEADLESS run takes no phase at any address — a loop iteration and a steward's one-shot both "
           "journal, end the turn, and let the next run start on a fresh context reading it",
           all(start(a) == 1 and read(a) is None for a in ("k1", "k1@dash", "k1/t1")))
        os.environ.pop("CC_ROLE", None)

        # THE TRIPWIRE. A kind that stops being recognised — a new launcher, a window renamed by hand — is a
        # session that can never be handed off and whose context shares a key with its neighbours. Nothing
        # watched for that, which is the only reason it was true of every orchestrator for weeks.
        ok("with every live window an address, nothing is reported as unaddressable",
           [n for n, _, _ in unaddressable()] == [])
        wins["not an address!"] = "@bad"
        ok("a live session whose window name is no address at all is REPORTED, by name",
           [n for n, _, _ in unaddressable()] == ["not an address!"])
        wins["k5" + NEXT] = "@k5n"
        ok("...and a side of a handoff in flight is not one of those — `orphans` owns those",
           [n for n, _, _ in unaddressable()] == ["not an address!"])
        del wins["not an address!"], wins["k5" + NEXT]

        os.environ.pop("CC_HANDOFF", None)
        wins["r2"] = "@r2"
        ok("--retire with no record kills nothing", retire("r2") == 0 and wins.get("r2") == "@r2")
        start("r2")
        ok("--retire BEFORE cutover kills nothing", retire("r2") == 0 and wins.get("r2") == "@r2"
           and read("r2") is not None)
        clear("r2")
        del wins["r2~next"]

        r = cutover("r2")
        pre, suc = r["predecessor"]["tmux"], r["successor"]["tmux"]
        ok("AT CUTOVER the predecessor is `<target>~old` and the successor holds `<target>` — an owner attaching "
           "lands on the live one from the first instant",
           wins.get("r2~old") == pre and wins.get("r2") == suc and "r2~next" not in wins)
        ok("...and the record names the windows they hold now",
           r["predecessor"]["window"] == "r2~old" and r["successor"]["window"] == "r2")
        ren = [a for a in tcalls if a[0] == "rename-window" and "r2~old" in a]
        ok("...both names move in ONE tmux call — no instant with no `<target>` window for a `cc <repo>` to fill",
           len(ren) == 1 and ren[0].count("rename-window") == 2 and ren[0][-1] == "r2")
        told = [a for a in msgs if isinstance(a, list) and a[0].endswith("cc-msg") and a[1] == "r2~old"]
        ok("...the predecessor is told, in ITS window, that it is retiring — and not that typing there is "
           "relayed anywhere: nothing relays it now", told and "retiring" in told[-1][2] and "relayed" not in told[-1][2])
        ok("...and it too leads with the machine tag: the retiring session's stop message opened an owner row "
           "as well (a132)", told and told[-1][2].startswith(MACHINE))
        ok("a predecessor still alive past the drain is ENDED, and only the successor holds the name",
           retire("r2") == 0 and wins.get("r2") == suc and "r2~old" not in wins and "r2~next" not in wins)
        ok("...the record is cleared afterwards, so nothing stays gated", read("r2") is None)
        ok("...and the completed retirement is remembered where clear() cannot reach it (2026-08-31: a "
           "finished handoff gated the only session left)", os.path.exists(done_path(r["id"])))
        marked = done_path(r["id"])
        ok("one ledger line for the retirement",
           [json.loads(l)["kind"] for l in open(os.path.join(RECORDS, "handoffs.jsonl"))][-1] == "overlap-retired")

        r = cutover("r3")
        dead.add("r3~old")                              # /exit was typed: the window is a bare shell now
        ok("a predecessor that already exited still ends, renames and clears",
           retire("r3") == 0 and wins.get("r3") == r["successor"]["tmux"] and "r3~old" not in wins
           and read("r3") is None)

        # kick() spools the opening prompt under the STARTUP name; cutover moves it to the live name, and
        # retirement removes mail addressed to the dead ~old window (review-157b: both were stranded forever).
        os.makedirs(os.path.join(STATE, "r9~next"), exist_ok=True)
        with open(os.path.join(STATE, "r9~next", "inbox.spool"), "w") as fh:
            fh.write('{"text":"opening prompt"}\n')
        r = cutover("r9")
        ok("cutover moves the ~next spool to the live name — the opening prompt is not stranded by the rename",
           not os.path.exists(os.path.join(STATE, "r9~next"))
           and open(os.path.join(STATE, "r9", "inbox.spool")).read() == '{"text":"opening prompt"}\n')
        # ...and it takes cc-msg's own lock while it does it: the 60 s drain rewrites that same file as tail+mv,
        # so an append the drain did not see is replaced by its mv — and the rmtree then deletes the only copy.
        held, _fl = [], fcntl.flock
        fcntl.flock = lambda fh, op: held.append((getattr(fh, "name", ""), op,
                                                  os.path.exists(os.path.join(STATE, "r14", "inbox.spool"))))
        try:
            os.makedirs(os.path.join(STATE, "r14~next"), exist_ok=True)
            with open(os.path.join(STATE, "r14~next", "inbox.spool"), "w") as fh:
                fh.write('{"text":"opening prompt"}\n')
            cutover("r14")
        finally:
            fcntl.flock = _fl
        ok("...holding cc-msg's own .inbox.lock, taken before a byte is written and released after the ~next dir "
           "is gone — outside it the drain's mv wins and the moved prompt is deleted with the dir it came from",
           held[:1] == [(os.path.join(STATE, "r14", ".inbox.lock"), fcntl.LOCK_EX, False)]
           and open(os.path.join(STATE, "r14", "inbox.spool")).read() == '{"text":"opening prompt"}\n'
           and not os.path.exists(os.path.join(STATE, "r14~next")))

        os.makedirs(os.path.join(STATE, "r9~old"), exist_ok=True)
        with open(os.path.join(STATE, "r9~old", "inbox.spool"), "w") as fh:
            fh.write('{"text":"retire msg"}\n')
        ok("...and retirement leaves no ~old junk: mail addressed to the dead window dies with it",
           retire("r9") == 0 and not os.path.exists(os.path.join(STATE, "r9~old")))

        # ---- THE ROWS IT WAS WORKING IN ITS OWN SUBAGENTS COME WITH IT. The cutover rename ends every `agent`
        # mark the predecessor made, while those subagents are still running and still reporting into the
        # successor: ten minutes later the watchdog called five such rows abandoned and blocked them, and a
        # blocked row is offered for dispatch again (2026-09-07, twice in one hour). carry_marks() hands them
        # over — and the two rows it must leave alone are the ones these cases are really about.
        boardf, hcalls = {}, []

        def out(argv, timeout=25, cwd=None, fail=""):
            if argv[0].endswith("cc-board") and argv[1] == "json":
                return json.dumps(boardf.get(argv[2]) or {"tracks": {}})
            if argv[0].endswith("cc-board") and argv[1] == "handover":
                hcalls.append(list(argv[2:]))          # cc-board owns the write and its own exact-match rule
                repo, frm, to, names = argv[2], argv[3], argv[4], argv[5:]
                mv = [t for t in names if (boardf[repo]["tracks"][t].get("agent") or "") == frm]
                for t in mv:
                    boardf[repo]["tracks"][t]["agent"] = to
                return "\n".join(mv)
            return real_out(argv, timeout=timeout, cwd=cwd, fail=fail)

        home0 = os.environ.get("HOME")
        os.environ["HOME"] = os.path.join(d, "fakehome")   # journal() writes under ~, and never the real one
        try:
            boardf["r15"] = {"tracks": {
                "sub":    {"status": "running", "agent": "@r15:900"},    # the predecessor's own subagent
                "worked": {"status": "running", "agent": "@r15:900"},    # …and a real worker is in this one
                "third":  {"status": "running", "agent": "@r150:900"},   # another session, one digit along
                "free":   {"status": "queued"},                          # nobody's
            }}
            wins["r15/worked"] = "@w15"                 # the track's own window, live: how the watchdog reads a worker
            r = cutover("r15")
            suc15 = r["successor"]["tmux"] + ":900"
            ok("a row the retiring session held in a subagent is the SUCCESSOR's after cutover — five such rows "
               "were blocked as abandoned ten minutes after one (2026-09-07)",
               hcalls == [["r15", "@r15:900", suc15, "sub"]]
               and boardf["r15"]["tracks"]["sub"]["agent"] == suc15)
            # …and these three are asked of what carry_marks NAMED, not only of what came back: a row it should
            # never have offered is a bug here even when cc-board's own exact match happens to spare it.
            named = [t for c in hcalls for t in c[3:]]
            ok("...a row marked by a THIRD session is never even offered, and a prefix would have offered it "
               "(`@r15` is the head of `@r150`): the whole mark is compared, never the window id alone",
               "third" not in named and boardf["r15"]["tracks"]["third"]["agent"] == "@r150:900")
            ok("...nor is a row a real worker is in — that work is not this handoff's to move",
               "worked" not in named and boardf["r15"]["tracks"]["worked"]["agent"] == "@r15:900")
            ok("...and a row nobody marked is not claimed: nothing is held that was not held before",
               "free" not in named and not boardf["r15"]["tracks"]["free"].get("agent"))
            jp15 = os.path.expanduser(journal_for("r15"))   # a regression is ONE red case, never a suite that dies
            jrn = open(jp15).read() if os.path.exists(jp15) else ""
            ok("...the journal says which rows moved, so the successor can see it did", "sub" in jrn
               and "successor's now" in jrn)
            derive(read("r15"))
            ok("...and a retried derive() moves nothing: the marks are the successor's already",
               len(hcalls) == 1)
        finally:
            out = real_out
            clear("r15")
            for w in ("r15/worked", "r15~old", "r15"):   # the window count is what the stub numbers new ids from
                wins.pop(w, None)
            os.environ.pop("CC_HANDOFF", None)
            if home0 is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = home0

        r = cutover("r4")
        me[0] = r["predecessor"]["tmux"]                # --retire called from the very window it would kill
        ok("--retire never kills the pane it is called from",
           retire("r4") == 1 and wins.get("r4~old") == r["predecessor"]["tmux"] and read("r4") is not None)
        ok("...and a refused kill leaves no completion marker: the successor stays gated",
           not os.path.exists(done_path(r["id"])))
        ok("...and the record says the drain is over (phase retired), which is what the sweep ends later",
           read("r4")["phase"] == "retired")
        me[0] = ""
        r["predecessor"]["tmux"] = r["successor"]["tmux"]   # the record names one window on both sides
        write(r)
        ok("a record naming the same window on both sides kills nothing", retire("r4") == 1
           and wins.get("r4") == r["successor"]["tmux"] and read("r4") is not None)
        r["predecessor"]["tmux"] = "@somebody-else"     # the record names a window that is not there
        write(r)
        ok("a record naming a window that is not there kills nothing — whatever holds `~old` is left alone",
           retire("r4") == 0 and wins.get("r4~old") == "@r4" and wins.get("r4") == r["successor"]["tmux"])
        wins.pop("r4~old")

        r = cutover("r6")
        wins["r6-renamed"] = wins.pop("r6~old")          # its window no longer carries the retiring name
        ok("a predecessor whose window was renamed by hand is still ended, by the id the record names",
           retire("r6") == 0 and r["predecessor"]["tmux"] not in wins.values()
           and wins.get("r6") == r["successor"]["tmux"] and read("r6") is None)

        wins["r13"] = "@r13"
        start("r13")
        rr = read("r13"); nid = rr["successor"]["tmux"]; rr["successor"]["tmux"] = ""; write(rr)
        os.environ["CC_HANDOFF"] = rr["id"]
        ok("a record with no successor id still renames it at cutover, by its `~next` name — and learns the id",
           ready("r13") == 0 and wins.get("r13") == nid and "r13~next" not in wins
           and read("r13")["successor"]["tmux"] == nid)
        os.environ.pop("CC_HANDOFF", None)
        clear("r13"); wins.pop("r13~old", None); wins.pop("r13", None)

        r = cutover("r5")
        os.environ["CC_HANDOFF_DONE_TTL"] = "0"         # every marker is now older than the TTL
        retire("r5")
        ok("a completion marker is pruned once no session can still be holding that id",
           os.path.exists(done_path(r["id"])) and not os.path.exists(marked))
        os.environ.pop("CC_HANDOFF_DONE_TTL", None)

        # ---- THE DRAIN: the predecessor keeps its window after cutover until it is idle, or the drain runs out.
        env2 = {k: os.environ.get(k) for k in ("HOME", "CC_CTX_RECORDS")}
        os.environ["HOME"] = os.path.join(d, "fakehome")
        os.environ["CC_CTX_RECORDS"] = RECORDS
        os.environ["CC_HANDOFF_DRAIN"] = "600"
        # the drain's clock: idle ends it early, work runs it to the end, and the kill comes after either
        real_t, real_s = time.time, time.sleep
        clk = [real_t()]
        time.time = lambda: clk[0]
        # a sub-second sleep is subprocess's own wait poll (cfg() shells out to cc-config): it sleeps for real and
        # leaves the clock alone — on the fake clock it spun the child's whole run into minutes (flake, 2026-09-02)
        time.sleep = lambda n: real_s(n) if 0 < n < 1 else clk.__setitem__(0, clk[0] + (n or 1))
        os.environ["CC_HANDOFF_RETIRE_GRACE"] = "120"
        r = cutover("r8")
        pre, suc = r["predecessor"]["tmux"], r["successor"]["tmux"]
        t0 = clk[0]
        panes[pre] = "❯ journalled, done.\n\n──────\n❯\u00a0\n──────\n  auto mode on (shift+tab to cycle)"
        ok("an idle predecessor with nothing typed is ended once the grace is up — not the whole drain",
           retire("r8") == 0 and 120 <= clk[0] - t0 < 600 and pre not in wins.values()
           and wins.get("r8") == suc and read("r8") is None)
        r = cutover("r9")
        pre, suc = r["predecessor"]["tmux"], r["successor"]["tmux"]
        t0 = clk[0]
        panes[pre] = "❯ working\n\n✻ Thinking… (" + WORKING + ")\n──────\n❯\u00a0\n──────"
        ok("a turn in flight is never cut short: the predecessor runs to the end of the drain, then ends",
           retire("r9") == 0 and clk[0] - t0 >= 600 and pre not in wins.values() and read("r9") is None)
        r = cutover("r10")
        pre = r["predecessor"]["tmux"]
        t0 = clk[0]
        panes[pre] = "──────\n❯ half a question typed and not yet sen\n──────\n  auto mode on"
        ok("text sitting in the input box is not idle — it waits for the drain too",
           retire("r10") == 0 and clk[0] - t0 >= 600 and read("r10") is None)
        r = cutover("r11")
        pre = r["predecessor"]["tmux"]
        t0 = clk[0]
        panes[pre] = "Do you want to proceed?\n ❯ 1. Yes\n   2. No\n Esc to cancel"
        ok("...and neither is a dialog waiting for a key", retire("r11") == 0 and clk[0] - t0 >= 600)
        r = cutover("r12")
        pre = r["predecessor"]["tmux"]
        panes[pre] = IDLE                               # the older TUI: `>` and a placeholder in the box
        t0 = clk[0]
        ok("the older TUI's empty box (`>` and a placeholder) reads as idle too",
           retire("r12") == 0 and 120 <= clk[0] - t0 < 600)

        # ---- THE PREDECESSOR STAYS FOR ITS SUBAGENTS: the successor is live for the channel from cutover, the
        # old session keeps running to hand each report on, and its retirement waits for the last one.
        env3 = {k: os.environ.get(k) for k in ("CC_HANDOFF_TASKS", "CC_HANDOFF_AGENT_IDLE", "CC_HANDOFF_AGENT_MAX")}
        troot = os.path.join(d, "tasks-root")
        tasks = os.path.join(troot, "project", "sid-sub", "tasks")
        os.makedirs(tasks)
        os.environ["CC_HANDOFF_TASKS"] = troot
        os.environ["CC_HANDOFF_AGENT_IDLE"] = "600"
        for name, quiet in (("a-live", 0), ("a-quiet", -4000)):
            t = os.path.join(d, name + ".jsonl")
            open(t, "w").close()
            os.utime(t, (clk[0] + quiet, clk[0] + quiet))   # mtimes on the FAKE clock these cases run on
            os.symlink(t, os.path.join(tasks, name + ".output"))
        open(os.path.join(tasks, "b-background.output"), "w").close()   # a background command, not a subagent
        os.symlink(os.path.join(d, "no-such.jsonl"), os.path.join(tasks, "a-gone.output"))
        # THE REPORT THAT IS ALREADY IN. A finished agent's transcript ends in its final assistant turn
        # (`stop_reason: end_turn`) and is written a minute ago like a live one's: the mtime rule alone held a
        # predecessor open for subagents whose reports were journaled and landed (2026-09-15, 2026-09-16 twice).
        # The records in the shapes the harness writes them (824 transcripts probed on 2026-09-19): a final report
        # is an assistant record of text — with `stop_reason: end_turn` (303) or `null` (431); a tool call, with
        # either, is mid-turn. The rule is cc-slack's home_agent_done: assistant, and no tool_use block.
        text = [{"type": "text", "text": "done: the report"}]
        rec_end = json.dumps({"type": "assistant", "message": {"role": "assistant", "stop_reason": "end_turn", "content": text}})
        rec_null = json.dumps({"type": "assistant", "message": {"role": "assistant", "stop_reason": None, "content": text}})
        rec_tool = json.dumps({"type": "assistant", "message": {"role": "assistant", "stop_reason": None,
                                                                "content": [{"type": "tool_use", "name": "Bash"}]}})
        tdone = os.path.join(d, "a-done.jsonl")
        with open(tdone, "w") as fh:
            fh.write(rec_tool + "\n" + rec_end + "\n")
        os.utime(tdone, (clk[0], clk[0]))                   # written just now — and still not counted
        os.symlink(tdone, os.path.join(tasks, "a-done.output"))
        tnull = os.path.join(d, "a-null.jsonl")
        with open(tnull, "w") as fh:
            fh.write(rec_tool + "\n" + rec_null + "\n")         # the commoner shape: the final text, no stop_reason
        os.utime(tnull, (clk[0], clk[0]))
        os.symlink(tnull, os.path.join(tasks, "a-null.output"))
        tlive = os.path.join(d, "a-live.jsonl")
        with open(tlive, "w") as fh:
            fh.write(rec_end + "\n" + rec_tool + "\n")           # its last record is a tool call: mid-turn, alive
        os.utime(tlive, (clk[0], clk[0]))
        ok("a subagent is a task file that is a live SYMLINK — a background command, a dangling link and a "
           "transcript gone quiet are not", subagents("sid-sub") == ["a-live"])
        ok("...and neither is one whose transcript has DELIVERED its final report — an assistant record with no "
           "tool call, whether its stop_reason says end_turn or nothing at all — however fresh its mtime",
           reported(tdone) and reported(tnull) and "a-done" not in subagents("sid-sub")
           and "a-null" not in subagents("sid-sub"))
        os.unlink(os.path.join(tasks, "a-null.output"))
        tcut = os.path.join(d, "a-cut.jsonl")
        with open(tcut, "w") as fh:                          # one complete text record, longer than the tail read
            fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "stop_reason": "end_turn",
                                                                  "content": [{"type": "text", "text": "x" * 70000}]}}) + "\n")
        ok("a tail read that lands inside the last record answers nothing — the same guard as cc-slack's — and a "
           "transcript is read whole when it fits the tail",
           not reported(tcut) and reported(tcut, tail=1 << 20))
        with open(tdone, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"role": "user"}}) + "\n")   # the parent resumed it
        os.utime(tdone, (clk[0], clk[0]))
        ok("...until its parent resumes it — a record after that final turn makes it live again",
           not reported(tdone) and sorted(subagents("sid-sub")) == ["a-done", "a-live"])
        with open(tdone, "w") as fh:
            fh.write(rec_tool + "\n" + rec_end + "\n")           # back to delivered, for the cases below
        os.utime(tdone, (clk[0], clk[0]))
        ttext = os.path.join(d, "a-text.jsonl")
        with open(ttext, "w") as fh:
            fh.write("not json at all\n")
        os.utime(ttext, (clk[0], clk[0]))
        os.symlink(ttext, os.path.join(tasks, "a-text.output"))
        ok("an unreadable tail decides nothing — a fresh transcript that is not JSON, or one that is gone, is read "
           "by its mtime as before: live",
           not reported(ttext) and not reported(os.path.join(d, "no-such.jsonl"))
           and sorted(subagents("sid-sub")) == ["a-live", "a-text"])
        os.unlink(os.path.join(tasks, "a-text.output"))     # this case's own fixture; the cases below count a-live alone
        ok("an unknown session id, or one with no task files, reads as no subagents — and the handoff is then "
           "exactly the one it was before", subagents("") == [] and subagents("sid-none") == [])

        def cutover_sub(t):
            """cutover(), for a predecessor whose session id is the one the fixture's subagents belong to"""
            wins[t] = "@" + t
            start(t)
            rr = read(t); rr["predecessor"]["session_id"] = "sid-sub"; write(rr)
            os.environ["CC_HANDOFF"] = rr["id"]
            ready(t)
            os.environ.pop("CC_HANDOFF", None)
            return read(t)

        said = lambda w: [a for a in msgs if isinstance(a, list) and a[0].endswith("cc-msg") and a[1] == w]
        r = cutover_sub("r20")
        pre, suc = r["predecessor"]["tmux"], r["successor"]["tmux"]
        jp20 = os.path.expanduser("~/.cc/state/r20/planning-handoff.md")
        ok("AT CUTOVER the successor is live exactly as ever — the channel never waits for a subagent",
           live_side(r) == "successor" and wins.get("r20") == suc and wins.get("r20~old") == pre)
        ok("...but a predecessor with one still running is told to STAY and hand each report on, not that it "
           "is retiring", said("r20~old") and said("r20~old")[-1][2].startswith(MACHINE)
           and "STAY" in said("r20~old")[-1][2] and "subagents are still running" in said("r20~old")[-1][2]
           and "retiring" not in said("r20~old")[-1][2])
        ok("...the record names what holds it, so --retire acts on that one answer from its own process",
           read("r20").get("held") == ["a-live"])
        ok("...and the journal says the successor is live and this session is staying",
           "stays for the 1 subagent" in open(jp20).read())
        ok("...and the #alerts line says it is staying, not that it is retiring",
           any(a[1:3] == ["--kind", "alerts"] and "staying for 1 subagent" in a[-1]
               for a in msgs if isinstance(a, list) and len(a) > 4))
        n20 = len(said("r20~old"))
        ok("a retried --ready re-derives, but says nothing twice: no second STAY message, no second journal line",
           ready("r20") == 0 and len(said("r20~old")) == n20
           and open(jp20).read().count("this session stays for the") == 1)
        panes[pre] = IDLE                               # idle from the first read: only the stay holds it now
        t0, n20 = clk[0], len(said("r20~old"))
        ok("RETIREMENT WAITS: while a subagent is alive the predecessor keeps its window, and it ends only "
           "once the last one is done", retire("r20") == 0 and 600 <= clk[0] - t0 < 600 + 600 + 60
           and pre not in wins.values() and wins.get("r20") == suc and read("r20") is None)
        ok("...the final handoff message comes at the END of the stay, not at cutover",
           len(said("r20~old")) == n20 + 1 and "retiring" in said("r20~old")[-1][2])
        ok("...and the journal says what ended it", "last subagent finished" in open(jp20).read())

        os.environ["CC_HANDOFF_AGENT_IDLE"] = "100000"  # nothing in the fixture ever goes quiet now
        os.environ["CC_HANDOFF_AGENT_MAX"] = "300"
        r = cutover_sub("r21")
        pre = r["predecessor"]["tmux"]
        jp21 = os.path.expanduser("~/.cc/state/r21/planning-handoff.md")
        panes[pre] = IDLE
        t0 = clk[0]
        ok("a stay is BOUNDED: a subagent that never finishes does not keep the window forever",
           retire("r21") == 0 and 300 <= clk[0] - t0 < 300 + 600 + 60 and pre not in wins.values()
           and read("r21") is None)
        ok("...and the journal says the wait ran out, not that the work finished",
           "the wait ran out" in open(jp21).read())
        r = cutover_sub("r22")
        pre = r["predecessor"]["tmux"]
        dead.add("r22~old")                             # /exit was typed: nobody is left to hand a report to
        t0 = clk[0]
        ok("a stay ends the moment that session is gone — a report has nowhere to go either way",
           retire("r22") == 0 and clk[0] - t0 < 300 and read("r22") is None)
        ok("the sweep's clock waits a stay out too: cutover plus the stay's cap, then the stay's own end",
           drain_start({"cutover": 1000, "held": ["a"]}, 3600) == 4600
           and drain_start({"cutover": 1000}, 3600) == 1000
           and drain_start({"cutover": 1000, "held": ["a"], "drain_from": 5000}, 3600) == 5000)
        for k, v in env3.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

        time.time, time.sleep = real_t, real_s
        os.environ["CC_HANDOFF_RETIRE_GRACE"] = "0"
        os.environ["CC_HANDOFF_DRAIN"] = "0"
        for k, v in env2.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        os.environ.pop("CC_HANDOFF", None)

        # ---- --sweep: what no session is left to finish. It only ever UN-GATES, so a wrong "gone" is the
        # expensive direction and every case below is about not taking one.
        os.environ["CC_HANDOFF_DRAIN"] = "600"           # the section's grace stays 0: a real drain, or every
        r = cutover("s1")                                # fresh cutover below reads as "outlived its drain"
        ok("a record whose predecessor is still there is left alone", sweep() == 0 and read("s1") is not None)
        pw = wins["s1~old"]
        del wins["s1~old"]                              # the predecessor is gone: --retire never got to finish
        ok("one sweep alone never finalizes — a single misread must not un-gate the successor",
           sweep() == 0 and read("s1") is not None and bool(read("s1").get("gone_since")))
        wins["s1~old"] = pw                             # it came back: the "gone" was a misread
        ok("...a predecessor seen again withdraws the stamp",
           sweep() == 0 and read("s1") is not None and not read("s1").get("gone_since"))
        del wins["s1~old"]
        sweep()                                         # strike one: the stamp
        rr = read("s1"); rr["gone_since"] = time.time() - 301; write(rr)   # a sweep later, still nobody
        ok("a predecessor gone past the grace is finalized (two sweeps apart)", sweep() == 0 and read("s1") is None)
        ok("...and the handover leaves one line in #alerts (owner, 2026-09-01) — as an `alerts` kind, which is "
           "the rung that lands there",
           any(a[1:3] == ["--kind", "alerts"] for a in msgs if isinstance(a, list)))
        ok("...with the marker cc-guard reads, so the survivor is not gated by the record of its own success",
           os.path.exists(done_path(r["id"])))
        ok("...and the successor is left holding the target's window name",
           wins.get("s1") == r["successor"]["tmux"] and "s1~next" not in wins)
        ok("...one ledger line, saying it was swept",
           [json.loads(l)["kind"] for l in open(os.path.join(RECORDS, "handoffs.jsonl"))][-1] == "overlap-swept")
        ok("...and a swept record is not swept again", sweep() == 0 and read("s1") is None)

        r = cutover("s5")
        pre, suc = r["predecessor"]["tmux"], r["successor"]["tmux"]
        ok("a cut-over predecessor still inside its drain is left alone",
           sweep() == 0 and read("s5") is not None and pre in wins.values())
        rr = read("s5"); rr["cutover"] = time.time() - 601; rr["phase"] = "retired"; write(rr)
        me[0] = pre
        ok("...past drain+grace, under --retire's own fence: never the sweep's own pane",
           sweep() == 0 and read("s5") is not None and pre in wins.values())
        me[0] = ""
        ok("...and otherwise the SWEEP ends it (its --retire died, or refused from the predecessor's own pane): "
           "no `~old` at phase retired forever, and its successor can hand off in its turn",
           sweep() == 0 and read("s5") is None and pre not in wins.values() and wins.get("s5") == suc
           and os.path.exists(done_path(r["id"])))
        r = cutover("s6")
        pre, suc = r["predecessor"]["tmux"], r["successor"]["tmux"]
        rr = read("s6"); rr["cutover"] = time.time() - 601; rr["held"] = ["a-live"]; write(rr)
        ok("a predecessor STAYING for its subagents is not swept away mid-stay — it is past nothing yet",
           sweep() == 0 and read("s6") is not None and pre in wins.values())
        rr = read("s6"); rr.pop("held"); rr["drain_from"] = time.time() - 601; write(rr)
        ok("...and once the stay is over it drains and is ended like any other",
           sweep() == 0 and read("s6") is None and pre not in wins.values() and wins.get("s6") == suc)
        os.environ["CC_HANDOFF_DRAIN"] = "0"

        os.environ.pop("CC_HANDOFF", None)
        told = sum(1 for m in msgs if m and m[0] == "notify")
        wins["s2"] = "@s2"
        start("s2")
        ok("an overlap still inside its deadline is not swept", sweep() == 0 and read("s2") is not None)
        rr = read("s2")
        rr["deadline"] = time.time() - 1
        write(rr)
        ok("an overdue overlap that never reached --ready expires",
           sweep() == 0 and read("s2") is None and "s2~next" not in wins)
        ok("...QUIETLY: its predecessor never stopped working, so there is nothing to tell the owner",
           sum(1 for m in msgs if m and m[0] == "notify") == told)
        wins["s2"] = "@s2"
        start("s2")
        rr = read("s2"); rr["deadline"] = time.time() - 1; write(rr)
        wins["s2-moved"] = wins.pop("s2~next")           # the successor's window no longer carries its name
        ok("an expiry finds the successor by the id the record names when its name is gone",
           sweep() == 0 and read("s2") is None and rr["successor"]["tmux"] not in wins.values())

        # 2026-09-01 05:15Z: six `~next` windows sat parked for hours with no record. Their predecessors had
        # EXITED before --ready — a bare shell still holding `<target>` — so the sweep finalized the record but
        # the successor never got the name, and nothing pointed at it again.
        wins["s4"] = "@s4"
        start("s4")
        r = read("s4")
        dead.add("s4")                                  # the predecessor exited: its window is an empty shell
        r["started"] = time.time() - 200
        r["gone_since"] = time.time() - 301
        write(r)
        ok("a predecessor that exited before --ready: its empty shell goes, and the successor takes the name",
           sweep() == 0 and read("s4") is None and "@s4" not in wins.values()
           and wins.get("s4") == r["successor"]["tmux"] and "s4~next" not in wins)
        ok("...so no `~next` window outlives its record", not any(n.endswith("~next") for n in wins))

        wins["z1~next"] = "@z1"                          # a successor window with no record at all
        ages["@z1"] = 3 * 3600
        wins["z2~old"] = "@z2"
        ages["@z2"] = 60
        n0 = posts()
        ok("a `~next` or `~old` window with no record, older than the overlap window, is reported once",
           sweep() == 0 and posts() == n0 + 1 and sweep() == 0 and posts() == n0 + 1
           and "z1~next" in wins and any("main:z1~next" in a[-1] for a in msgs if isinstance(a, list)))
        ok("...a young one is not (its record may be a moment away)",
           not any("main:z2~old" in a[-1] for a in msgs if isinstance(a, list)))
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status()
        ok("...and --status lists it, for whoever reads the box", "z1~next" in buf.getvalue() and "orphan" in buf.getvalue())
        wins.pop("z1~next"); wins.pop("z2~old")

        wins["s3"] = "@s3"
        start("s3")
        keep_tmux = tmux
        tmux = lambda *a, **k: None                     # noqa: E731 — the tmux server cannot be read at all
        ok("with tmux unreadable nothing is swept: every window would look gone",
           sweep() == 0 and read("s3") is not None)
        tmux = keep_tmux
        clear("s3")
        wins.pop("s3~next", None)
        if role0 is not None:
            os.environ["CC_ROLE"] = role0    # the caller's role back: a --go worker running the gates keeps it

        # a corrupt record reads exactly like a missing one: the predecessor is in charge
        os.makedirs(HANDOFF, exist_ok=True)
        with open(path("r1"), "w") as fh:
            fh.write("{not json")
        ok("a corrupt record is not an open overlap", read("r1") is None and read_all() == [])

        # ---- --brief: ONE packet, and the journal read from the END. Its own home, its own state dir, its
        # own board and PR list: nothing here is this box's, and the case that matters is the one it CANNOT
        # have read — an entry buried under 140 kB of history it must never touch.
        home0 = os.environ.get("HOME")
        dev0 = DEV
        bh = os.path.join(d, "briefhome")
        os.environ["HOME"] = bh
        DEV = os.path.join(bh, "dev")
        os.makedirs(os.path.join(DEV, "r9", ".git"), exist_ok=True)   # the target's own checkout, for gh
        jd = os.path.join(bh, ".cc", "state", "r9", "t9")
        os.makedirs(jd, exist_ok=True)
        jpath = os.path.join(jd, "progress.md")
        with open(jpath, "w") as fh:
            fh.write("## 2026-01-01 00:0xZ — journal at 30% ctx (the OLD one)\nOLD-ENTRY-NEVER-READ\n")
            fh.write("a line of history\n" * 8000)                    # ~140 kB between the two entries
            fh.write("## 2026-01-02 00:0xZ — journal at 31% ctx (the LAST one)\nKEPT-ENTRY\n")
            fh.write("- 01:0xZ: DATED-LINE-AFTER-IT\n")
        os.makedirs(os.path.join(STATE, "r9", "t9"), exist_ok=True)
        with open(os.path.join(STATE, "r9", "t9", "loop.log"), "w") as fh:
            fh.write("older line\n2026-01-02T01:00:00Z iter 2/3 LAST-LOOP-LINE\n")
        os.makedirs(os.path.join(STATE, "land"), exist_ok=True)
        with open(os.path.join(STATE, "land", "r9-5.json"), "w") as fh:
            json.dump({"repo": "r9", "pr": 5, "stage": "gates", "attempts": 1, "queued_at": "2026-01-02T00:00:00Z"}, fh)
        wins["lane7"] = "@70"                                          # a lane the #154 queue left running
        now = time.time()
        write({"id": "b0", "target": "r9/t9", "phase": "overlap", "live": "predecessor",
               "predecessor": {"session_id": "sid-9", "tmux": "@9", "window": "r9/t9"},
               "successor": {"session_id": "s9", "tmux": "@10", "window": "r9/t9~next"},
               "started": now, "deadline": now + 600, "phases": []})
        calls = []
        ghcwd = []

        def out(argv, timeout=25, cwd=None, fail=""):                  # the three helpers a brief reads
            calls.append(list(argv))
            if argv[0] == "gh":
                ghcwd.append(cwd)
            if argv[0].endswith("cc-board"):
                # One row per cut board_open makes, each with a `task:` line, the unindented line its text
                # wraps onto, and a note \u2014 so every assertion below reads the state its own row put there.
                # The hold is the first line under a row, as cc-board prints it; the last row's task line is the
                # last thing under it, and the footer follows it, as cc-board prints those (review of #521).
                return ("r9  base:main  /x\n"
                        "  \u25b6 t9 [running]  AN-OPEN-ROW\n"
                        "      task: LIVE-TASK-CUT\nLIVE-WRAP-CUT\n"
                        "      - LIVE-NOTE-KEPT\n"
                        "  \u00b7 t7 [queued]  A-QUEUED-ROW\n"
                        "      held (@3): QUEUED-HELD-KEPT behind #309 \u2014 do not start\n"
                        "      task: QUEUED-TASK-CUT\nQUEUED-WRAP-CUT\n"
                        "      - QUEUED-NOTE-CUT\n"
                        "  \u2713 t8 [merged]  A-FINISHED-ROW\n"
                        "      held (@9): FINISHED-HELD-CUT\n"
                        "      task: FINISHED-TASK-CUT\nFINISHED-WRAP-CUT\n"
                        "      - FINISHED-NOTE-CUT\n"
                        "  \u00b7 t6 [queued]  A-TASK-ONLY-ROW\n"
                        "      task: LAST-TASK-CUT\n"
                        "  (1 finished \u2014 cc board show r9 --all)\n")
            if argv[0] == "gh":
                return "5      track/t9      MERGEABLE\n"
            if argv[0].endswith("cc-scope"):
                return "· a1  OPEN-ASK-TEXT [t9]\n· a2  SECOND-OPEN-ASK\n"
            return ""

        import contextlib, io as _io
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = brief("r9/t9")
        b = buf.getvalue()
        text, nread, anchor = tail_entry(jpath)
        ok("--brief prints every section",
           rc == 0 and all(h in b for h in ("== journal", "== board", "== land", "== workers",
                                            "== open PRs", "== scope", "== who")))
        ok("...the journal section is the LAST 'journal at N%' entry and the dated lines after it",
           "KEPT-ENTRY" in b and "DATED-LINE-AFTER-IT" in b and "the LAST one" in b
           and anchor == "last 'journal at N%' entry")
        jsec = b.split("== journal — ")[1].split("\n== ")[0] if "== journal — " in b else ""
        ok("...and it is the CHECKPOINT VIEW (cc-lib view, 8 kB cap): its header names 1 of 2 entries and the ask that reaches the older one, "
           "and the 140 kB between the two marked entries is neither read into the packet nor over the cap",
           jsec.startswith("checkpoint view: 1 of 2 entries of") and "older entries: cc-lib ask --object r9/t9 --need history" in jsec
           and len(jsec.encode()) <= VIEW_CAP + 200)
        jv, jl = journal_view(jpath)
        bin0 = BIN
        globals()["BIN"] = os.path.join(d, "no-such-bin")
        try:
            jnone = journal_view(jpath)
        finally:
            globals()["BIN"] = bin0
        ok("...journal_view returns the body and the label; with no cc-lib beside this file it returns nothing, and the brief falls back to the tail",
           jv is not None and "KEPT-ENTRY" in jv and jl.startswith("1 of 2 entries") and jnone == (None, None))
        ok("...and it never reads past that entry: the one before it is in the file and not in the packet",
           "OLD-ENTRY-NEVER-READ" not in b and "the OLD one" not in b
           and nread < os.path.getsize(jpath) and nread <= BRIEF_CAP)
        ok("...the board is the rows that are not finished: a merged row's header, task, wrapped task text and "
           "notes are all gone, and a live row's header and notes are all there",
           "AN-OPEN-ROW" in b and "LIVE-NOTE-KEPT" in b
           and not any(s in b for s in ("A-FINISHED-ROW", "FINISHED-TASK-CUT", "FINISHED-NOTE-CUT")))
        ok("...and a FINISHED row's wrapped task text goes with it: unindented, it used to read as a new board "
           "header, reset the drop and leak the line into the packet",
           "FINISHED-WRAP-CUT" not in b and "r9  base:main  /x" in b)
        ok("...every row loses its `task:` line and the lines that text wraps onto, live row and queued row alike, "
           "while both keep the header above it — and the packet names the command that has the task text whole",
           not any(s in b for s in ("LIVE-TASK-CUT", "LIVE-WRAP-CUT", "QUEUED-TASK-CUT", "QUEUED-WRAP-CUT"))
           and "AN-OPEN-ROW" in b and "A-QUEUED-ROW" in b and "cc board get r9 <row> instructions" in b)
        ok("...and a QUEUED row is its header alone: the successor is told the row exists, not what is under it, "
           "while a running row beside it keeps its notes",
           "A-QUEUED-ROW" in b and "[queued]" in b and "QUEUED-NOTE-CUT" not in b and "LIVE-NOTE-KEPT" in b)
        ok("...except a hold a person put on it: a queued row's `held (<who>): <reason>` line survives with the header "
           "(the packet is the only place a successor is offered it), and a finished row's hold goes with the row",
           "held (@3): QUEUED-HELD-KEPT" in b and "do not start" in b and "FINISHED-HELD-CUT" not in b)
        ok("...and cc-board's footer after a row whose task line was the last thing under it is kept as the board's "
           "own line, not dropped as that row's wrapped task text",
           "(1 finished \u2014 cc board show r9 --all)" in b and "A-TASK-ONLY-ROW" in b and "LAST-TASK-CUT" not in b)
        ok("...a live lane names its window, its PR and its waiter pid, and the queue its job and stage",
           "lane7" in b and "@70" in b and "PR 7" in b and "4242" in b and "PR 5" in b and "stage gates" in b)
        ok("...a live worker is one line, the last of its loop.log", "LAST-LOOP-LINE" in b and "older line" not in b)
        ok("...the open PRs, the predecessor's window, tmux id and session are all in it",
           "track/t9" in b and "MERGEABLE" in b
           and "main:r9/t9" in b and "@9" in b and "sid-9" in b and "id b0" in b)
        ok("...and the open asks are the asks themselves, not a bare count",
           "OPEN-ASK-TEXT" in b and "a1" in b and "SECOND-OPEN-ASK" in b and "a2" in b)
        ok("...and the helpers are asked once each, for this repo only — cc-scope with `list`, not `count`",
           [c[-2:] for c in calls if c[0].endswith("cc-board")] == [["show", "r9"]]
           and [c[-2:] for c in calls if c[0].endswith("cc-scope")] == [["list", "r9"]])
        # ---- the packet's size, into the failures ledger: its own ledger dir, the band either side of this packet
        env0 = {k: os.environ.get(k) for k in ("CC_FAILURES", "CC_BRIEF_PACKET_BAND")}
        os.environ["CC_FAILURES"] = os.path.join(d, "brief-failures")
        pled = os.path.join(d, "brief-failures", "r9.jsonl")
        pledger = lambda: [json.loads(ln) for ln in open(pled)] if os.path.isfile(pled) else []
        size, ncalls, ngh = len(b.encode()), len(calls), len(ghcwd)
        try:
            os.environ["CC_BRIEF_PACKET_BAND"] = str(size + 64)       # the "m left" line may shift a byte between calls
            with contextlib.redirect_stdout(_io.StringIO()):
                brief("r9/t9")
            under = pledger()
            os.environ["CC_BRIEF_PACKET_BAND"] = str(size - 64)
            with contextlib.redirect_stdout(_io.StringIO()):
                brief("r9/t9"); brief("r9/t9")
            over = pledger()
        finally:
            for k, v in env0.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            del calls[ncalls:], ghcwd[ngh:]                           # the cases below count the first brief's helper calls
        ok("a packet under CC_BRIEF_PACKET_BAND writes no failures record", under == [])
        ok("...one over it writes one spend/handoff-packet-over-band record under its repo, keyed on the handoff, "
           "and a second brief of the same handoff writes none",
           len(over) == 1 and over[0]["kind"] == PACKET_KIND and over[0]["writer"] == "cc-handoff"
           and over[0]["links"]["source"] == "brief:r9/t9:b0")

        # THE OTHER JOURNAL SHAPE, which is the common one: a track's `progress.md` carries no
        # "journal at N%" line anywhere, so a rule that only knows that marker hands the successor the
        # banner and 64 kB of raw tail — every track target, every time. It cuts on the last dated entry.
        tj = os.path.join(jd, "track-shaped.md")
        with open(tj, "w") as fh:
            fh.write("## 2026-01-01 iteration 1\nEARLIEST-ENTRY\n")
            fh.write("a line of history\n" * 8000)                    # ~140 kB, no marker in any of it
            fh.write("## 2026-01-02 iteration 2\nMIDDLE-ENTRY\n")
            fh.write("## 2026-01-03 iteration 3\nLAST-TRACK-ENTRY\n- 01:0xZ: AND-THE-LINES-AFTER-IT\n")
        ttext, tread, tanchor = tail_entry(tj)
        ok("a journal with no 'journal at N%' line cuts on the last dated entry instead",
           tanchor == "last dated entry" and ttext.startswith("## 2026-01-03")
           and "LAST-TRACK-ENTRY" in ttext and "AND-THE-LINES-AFTER-IT" in ttext)
        ok("...and not on the raw tail: neither the entry before it nor the banner is in the packet",
           "MIDDLE-ENTRY" not in ttext and "EARLIEST-ENTRY" not in ttext
           and "the tail follows" not in ttext and tread < os.path.getsize(tj) and tread <= BRIEF_CAP)

        # THE PLANNING SHAPE IS BOTH AT ONCE: a marked entry, then runs of unmarked "## OVERLAP STARTED" /
        # "FINAL" / "TAKEOVER" entries, pages of them. Stopping at the first page that held two whole unmarked
        # headings started the packet BELOW the marked entry the successor is told to read (review of #181).
        pj = os.path.join(jd, "planning-shaped.md")
        with open(pj, "w") as fh:
            fh.write("## 2026-01-01 05:00Z - journal at 30% ctx\nOLDER-MARKED-ENTRY\n")
            fh.write("filler that is never read\n" * 2000)
            fh.write("## 2026-01-02 05:00Z - journal at 31% ctx\nTHE-MARKED-ENTRY-TO-KEEP\n")
            for i in range(3):
                fh.write("## 2026-01-02 0%d:00Z - OVERLAP STARTED\n" % (6 + i))
                fh.write("an unmarked entry after the marked one\n" * 120)
            fh.write("## 2026-01-02 09:00Z - TAKEOVER\n- 09:1xZ: THE-LAST-DATED-LINE\n")
        ptext, pread, panchor = tail_entry(pj)
        ok("a marked entry buried under pages of unmarked ones is still where the packet starts",
           panchor == "last 'journal at N%' entry" and "THE-MARKED-ENTRY-TO-KEEP" in ptext
           and ptext.startswith("## 2026-01-02 05:00Z"))
        ok("...with every unmarked entry after it kept, and the marked entry before it left out",
           "OVERLAP STARTED" in ptext and "THE-LAST-DATED-LINE" in ptext
           and "OLDER-MARKED-ENTRY" not in ptext and pread <= BRIEF_CAP)


        # WHERE gh IS ASKED IS PART OF THE ANSWER. It resolves a repo from its cwd, and --brief is run from
        # wherever the caller stands: from another repo's checkout that printed that repo's PRs under this
        # one's heading, and from a dir that is no checkout it printed none — read as "nothing is open".
        ok("gh is asked inside the target's own checkout, not wherever the caller happens to be",
           ghcwd == [os.path.join(DEV, "r9")])
        ok("...a target with no checkout to ask in says so, and never shows an empty PR list",
           prs("r-none").startswith("(unavailable:") and "r-none" in prs("r-none"))
        ok("...and a helper that could not run says so too, while one that ran is passed through",
           real_out(["false"], fail="(unavailable: x)") == "(unavailable: x)"
           and real_out(["printf", "hi"], fail="(unavailable: x)") == "hi"
           and real_out(["no-such-binary-here"], fail="(unavailable: x)") == "(unavailable: x)")
        clear("r9/t9")
        wins.pop("lane7", None)
        DEV = dev0
        if home0 is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = home0

        # ---- ROTATION: the sweep hands off a seat past the rotate line without the seat's cooperation. seat_of and
        # measure_seat are stubbed (the seat in a fixture window is a table entry; cc-context's own selfcheck pins
        # the `rotate` judgement), so every case is about what the sweep does with the answer. Each case builds
        # its own window, seat and measurement, and asserts both the seat that is rotated and the one left alone.
        seatd, meas, mcalls, msince = {}, {}, [], {}

        def seat_of(wid):
            return seatd.get(wid)

        def measure_seat(target, sid, alone, since=0):
            mcalls.append((target, sid, alone))
            msince[target] = since              # the seat's own start, which the real one hands cc-context as --since
            if not sid and not alone and not target.split("@")[0].count("/"):
                return None                     # the real one's refusal (pinned on the real one below); the rest is the table
            return meas.get(sid or target)

        def seat(name, sid, cwd="", used=0, rotate=False, line=200000, started=1234.0):
            wins[name] = "@" + name.replace("/", "-")
            seatd[wins[name]] = (sid, cwd or "/dev/" + name, started)
            meas[sid or name] = {"used": used, "rotate_line": line, "rotate": rotate, "pct": 0}

        home0 = os.environ.get("HOME")
        os.environ["HOME"] = os.path.join(d, "rothome")   # journal() writes under ~, never the real one
        rrole = os.environ.pop("CC_ROLE", None)           # the sweep runs from the timer, no role: a --go worker running the gates keeps its own
        try:
            os.environ["CC_HANDOFF_OVERLAP_MAX"] = "1200"
            seat("rt1/over", "sid-over", used=250000, rotate=True)      # "a seat over the hard line is handed off"
            seat("rt1/under", "sid-under", used=199999, rotate=False)   # "a seat under the line is untouched"
            n0 = len(msgs)
            ok("a bare --sweep (a bare cc-reconcile's) measures nothing and opens nothing: rotation is --rotate's, the tick's --apply",
               sweep() == 0 and not mcalls and read("rt1/over") is None and "rt1/over~next" not in wins)
            ok("the sweep opens the overlap for the seat past the rotate line: a record names it, the successor's window is up, "
               "and the record says the box opened it",
               sweep(True) == 0 and (read("rt1/over") or {}).get("phase") == "overlap" and wins.get("rt1/over~next")
               and "rotate line" in (read("rt1/over") or {}).get("box", ""))
            ok("...the seat under the line is untouched: no record, no successor window, nothing typed at it",
               read("rt1/under") is None and "rt1/under~next" not in wins
               and not any(m[0].endswith("cc-msg") and m[1].startswith("rt1/under") for m in msgs[n0:]))
            ok("...the seat's own id is what was measured, and the overlap carries it as the predecessor's",
               ("rt1/over", "sid-over", True) in mcalls and read("rt1/over")["predecessor"]["session_id"] == "sid-over")
            ok("...the wake is held off the target until the successor cuts over (pulse.off is the overlap's own mark)",
               os.path.exists(quiet_path("rt1/over")) and read("rt1/over")["quiet"] == [QUIET_MARK])
            ok("...the ledger row says why", any(r.get("kind") == "overlap-started" and r.get("target") == "rt1/over"
               and "rotate line" in r.get("why", "") for r in
               (json.loads(l) for l in open(os.path.join(RECORDS, "handoffs.jsonl")) if l.strip())))
            ok("...the seat's journal says the box did it",
               "rotated by the box" in open(os.path.expanduser(journal_for("rt1/over"))).read())
            with open(brief_path("rt1/over")) as fh:
                b = fh.read()
            ok("...and the successor's brief says THE BOX opened it, not that the predecessor left a note",
               "THE BOX opened this overlap" in b and "predecessor's own note" not in b)
            ok("...a stamp holds the box off that target for the retry window",
               os.path.exists(os.path.join(HANDOFF, "rt1--over.rotated")))
            ok("a target with an overlap open is not measured again", (mcalls.clear() or sweep(True) == 0)
               and not any(c[0] == "rt1/over" for c in mcalls))

            # the retry window: an overlap the box opened that expired is not reopened next tick
            seat("rt1/again", "sid-again", used=300000, rotate=True)
            os.makedirs(HANDOFF, exist_ok=True)
            with open(os.path.join(HANDOFF, "rt1--again.rotated"), "w") as fh:
                fh.write("{}")
            ok("a seat past the line whose stamp is inside CC_HANDOFF_ROTATE_RETRY is left alone (not even measured)",
               sweep(True) == 0 and read("rt1/again") is None and not any(c[0] == "rt1/again" for c in mcalls))
            os.environ["CC_HANDOFF_ROTATE_RETRY"] = "0"
            ok("...and once the retry window is over it is rotated", sweep(True) == 0 and (read("rt1/again") or {}).get("phase") == "overlap")
            del os.environ["CC_HANDOFF_ROTATE_RETRY"]

            # the stamp says an overlap OPENED: a start that refuses writes none, so the next tick tries again
            seat("rt7/x", "sid-x", used=300000, rotate=True)
            os.environ["CC_ROLE"] = "worker"               # start() refuses a worker caller (WORKER_REFUSAL)
            ok("a start that refuses leaves no stamp and no record", sweep(True) == 0 and read("rt7/x") is None
               and not os.path.exists(os.path.join(HANDOFF, "rt7--x.rotated")))
            os.environ.pop("CC_ROLE", None)
            ok("...and the next tick opens it, and only then stamps it", sweep(True) == 0
               and (read("rt7/x") or {}).get("phase") == "overlap" and os.path.exists(os.path.join(HANDOFF, "rt7--x.rotated")))

            # a headless worker's window is never a seat, however fat its transcript reads
            seat("rt1/loop", "sid-loop", used=400000, rotate=True)
            held.append(wins["rt1/loop"])
            ok("a worker's window past the line is not rotated (the iteration is its own handoff), and not measured",
               (mcalls.clear() or sweep(True) == 0) and read("rt1/loop") is None and not any(c[0] == "rt1/loop" for c in mcalls))
            held.remove(wins["rt1/loop"])

            # a seat with no id is measured by its checkout only when it is alone there
            seat("rt2", "", cwd="/dev/rt2", used=300000, rotate=True)
            seat("rt2@orch", "", cwd="/dev/rt2", used=300000, rotate=True)
            mcalls.clear(); sweep(True)
            ok("two seats with no id in one checkout are each offered as NOT alone (measure_seat says None there)",
               ("rt2", "", False) in mcalls and ("rt2@orch", "", False) in mcalls and read("rt2") is None)
            # the peer is counted BEFORE the filters: an orch with its own overlap open, or read as a worker, or its
            # ~next window up, still shares the checkout — a 50k planning seat must not be measured as alone
            seat("rt6", "", cwd="/dev/rt6", used=50000, rotate=False)
            seat("rt6@orch", "", cwd="/dev/rt6", used=300000, rotate=True)
            write({"id": "abc123", "target": "rt6@orch", "phase": "overlap", "live": "predecessor",
                   "predecessor": {"tmux": wins["rt6@orch"]}, "successor": {"tmux": ""}, "started": time.time(),
                   "deadline": time.time() + 1200})     # inside its deadline, or the reaper half expires it first
            mcalls.clear(); sweep(True)
            ok("a planning seat whose orch peer has an overlap open is still NOT alone in the checkout",
               ("rt6", "", False) in mcalls and ("rt6@orch", "", False) not in mcalls and read("rt6") is None)
            clear("rt6@orch")
            held.append(wins["rt6@orch"])
            mcalls.clear(); sweep(True)
            ok("...nor when that peer is read as a worker's window", ("rt6", "", False) in mcalls and read("rt6") is None)
            held.remove(wins["rt6@orch"])
            seat("rt6@orch~next", "", cwd="/dev/rt6")      # a successor window, not a target name: a peer all the same
            del wins["rt6@orch"]; mcalls.clear(); sweep(True)
            ok("...nor when the only other seat there is a `~next` window", ("rt6", "", False) in mcalls and read("rt6") is None)
            seat("rt3", "", cwd="/dev/rt3", used=300000, rotate=True)
            mcalls.clear(); sweep(True)
            ok("...and a seat alone in its checkout is measured as alone, and rotated",
               ("rt3", "", True) in mcalls and (read("rt3") or {}).get("phase") == "overlap")

            # THE MEASUREMENT IS BOUND TO THE LIVE PROCESS. A checkout holds whatever session wrote there last
            # inside a DAY, so a seat the owner started after quitting a 300k one was measured on the DEAD
            # session and rotated before its first turn (review of #552). The sweep hands measure_seat the
            # seat's own start, and measure_seat hands cc-context --since.
            seat("rt8", "", cwd="/dev/rt8", used=300000, rotate=True, started=4242.0)
            mcalls.clear(); sweep(True)
            ok("a no-id seat is measured from its OWN start, not from whatever wrote in that checkout",
               ("rt8", "", True) in mcalls and msince.get("rt8") == 4242.0)
            # ...and the real measure_seat, against the real cc-context: a checkout whose previous session left a
            # status-line file and a 300k transcript, both written BEFORE this seat started, measures as nothing.
            ck = os.path.join(os.environ["HOME"], "dev", "rt9")
            os.makedirs(ck, exist_ok=True)
            proj = os.path.join(os.environ["HOME"], ".claude", "projects",
                                re.sub(r"[/.]", "-", os.path.realpath(ck)))
            sld = os.path.join(d, "rot-statusline")
            os.makedirs(proj, exist_ok=True); os.makedirs(sld, exist_ok=True)
            txp, slp, then = os.path.join(proj, "sid-dead.jsonl"), os.path.join(sld, "sid-dead.json"), time.time() - 300
            with open(txp, "w") as fh:
                fh.write(json.dumps({"type": "assistant", "isSidechain": False, "message": {
                    "model": "claude-opus-5", "usage": {"input_tokens": 10, "cache_creation_input_tokens": 0,
                                                        "cache_read_input_tokens": 300000, "output_tokens": 10}}}) + "\n")
            with open(slp, "w") as fh:
                json.dump({"session_id": "sid-dead", "used": 300000, "window": 1000000, "pct": 30.0,
                           "model": "claude-opus-5", "raw": {"cwd": ck}}, fh)
            for pth in (txp, slp):               # stale for the 120 s freshness rule, well inside the day cc-context lists
                os.utime(pth, (then, then))
            keep = {k: os.environ.get(k) for k in ("CC_STATUSLINE_DIR", "CC_CTX_BOX_MODEL", "CC_CONTEXT_ROTATE_TOKENS")}
            os.environ.update({"CC_STATUSLINE_DIR": sld, "CC_CTX_BOX_MODEL": "",   # hermetic: not the box's own dir or model
                               "CC_CONTEXT_ROTATE_TOKENS": "200000"})
            try:
                ok("the finding: unbounded, the session the owner QUIT is what that checkout measures — 300k, past the rotate line",
                   (_real_measure("rt9", "", True) or {}).get("rotate") is True)
                ok("...and bound to a seat that started after it, nothing there is measurable: a FRESH no-id seat is not rotated",
                   _real_measure("rt9", "", True, time.time() - 60) is None)
            finally:
                for k, v in keep.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

            # a window with no seat in it (a bare shell) is nothing to measure
            wins["rt4"] = "@rt4"
            mcalls.clear(); sweep(True)
            ok("a window with no claude under its pane is not measured", not any(c[0] == "rt4" for c in mcalls))
            # the real measure_seat with no id, not a track, not alone: None before any cc-context call
            ok("the real measure_seat refuses a no-id seat that is not alone in its checkout without measuring anything",
               _real_measure("rt5@x", "", False) is None and _real_measure("rt5", "", False) is None)
        finally:
            if home0 is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = home0
            os.environ.pop("CC_HANDOFF_OVERLAP_MAX", None)
            if rrole is not None:
                os.environ["CC_ROLE"] = rrole
            for k in list(wins):
                if k.startswith("rt"):
                    del wins[k]
            seatd.clear(); meas.clear()

        # INDEX-AT-WRITE: the line journal() appends is in the library's index when it returns — `cc-lib ask` finds
        # it as a checkpoint under the target's own journal, and had nothing to re-read itself (re-read absent from
        # COVERAGE: the hook did it, not the ask). Its own HOME with one registered board, and the baseline pass
        # first, so the only stale source a lazy ask could catch up on is the entry.
        lhome = os.path.join(d, "libhome"); os.makedirs(os.path.join(lhome, ".cc", "boards"))
        with open(os.path.join(lhome, ".cc", "boards", "r19.json"), "w") as fh:
            json.dump({"repo": "r19", "path": os.path.join(lhome, "dev", "r19"), "tracks": {}, "log": []}, fh)
        home0 = os.environ.get("HOME"); os.environ["HOME"] = lhome
        try:
            lib = os.path.join(BIN, "cc-lib")
            subprocess.run([lib, "index"], capture_output=True, text=True, timeout=60)
            journal("r19", "handoff: the zebrafish successor is live and owns r19")
            o = subprocess.run([lib, "ask", "--repo", "r19", "--need", "history", "zebrafish successor"],
                               capture_output=True, text=True, timeout=60).stdout
            ok("a handoff line is indexed as it is written: cc-lib ask finds it as a checkpoint in the planning journal, "
               "with nothing left for the ask to re-read",
               "zebrafish successor" in o and "checkpoint" in o and "planning-handoff.md" in o
               and "OUTCOME answered" in o and "re-read" not in o)
        finally:
            if home0 is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = home0

    if nlo is not None:
        os.environ["CC_NOTIFY_LOG_ONLY"] = nlo
    print(f"cc-handoff selfcheck: {p} passed, {f} failed")
    return 1 if f else 0
