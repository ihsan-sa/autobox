# cc-board's selfcheck: the cases behind `cc-board selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-board execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.
# recurring-defect-ok: pause-hold-missing — moved test cases: the board writes and dispatches are fixtures in a temp tree, never a real one

def selfcheck():
    """STATIC: the two rules this file owns, checked against fixtures — no board, no state dir, no clock beyond
    its own. Run by tests/check.sh, so a regression fails the commit rather than the next `cc board show`."""
    global BOARDS, LOCK_WAIT, STATE   # two cases below shorten the wait and point the boards at the fixture, and put both back
    n = 0
    def ok(what, cond):
        nonlocal n
        print(("  ok   " if cond else "  FAIL ") + what)
        if not cond: n += 1
    old_ = lambda st: {"status": st, "updated": "2000-01-01T00:00:00Z"}
    new_ = lambda st: {"status": st, "updated": now()}
    print("cc-board selfcheck")
    ok("a running track is on the default view", shown(new_("running")) and shown(old_("running")))
    ok("a track just merged is still shown, so the owner sees what landed", shown(new_("merged")))
    ok("…and leaves once the window is past", not shown(old_("merged")) and not shown(old_("done")))
    ok("a stamp that cannot be read counts as old, never as pinned", not shown({"status": "merged"})
       and not shown({"status": "done", "updated": "yesterday"}))
    ok("blocked and waiting never leave — they are what the board is for",
       shown(old_("blocked")) and shown(old_("waiting")) and shown(old_("review")))
    ok("the window is what the comment above it says", SHOWN_FOR == 2 * 3600 and shown(new_("merged"), 0) is False)
    # …and the invariant the whole change exists for, exercised for real in a HOME of its own: the brief lands in
    # the file, the JSON never carries a copy, and every route ADDS to a brief rather than eating it.
    import subprocess, tempfile, shutil
    th = tempfile.mkdtemp(prefix="ccboard-sc-")
    try:
        def run(*args, env=None):   # env: extra variables for this one call
            base = {k: v for k, v in os.environ.items() if k != "CC_BRIEF_MACHINE"}
            try: return subprocess.run([sys.executable, os.path.realpath(__file__), *args],
                                       env={**base, "HOME": th, **(env or {})},
                                       capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired as e:   # a hang is ONE failed case, not a suite that never ends
                out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
                return subprocess.CompletedProcess(e.cmd, 124, out, f"cc-board selfcheck: `{' '.join(args)}` hung for 60 s")
        def bounded(fn, secs=10):   # an in-process call that hangs (a blocking flock, a plain open of a pipe) fails THIS case, not the suite
            import threading
            box = []
            def go():
                try: box.append(fn())
                except Exception as e: box.append(e)
            t = threading.Thread(target=go, daemon=True); t.start(); t.join(secs)
            return box[0] if box else "hung"
        run("init", "r", "/tmp/r", "main"); run("add", "r", "t1", "T", "THE BRIEF, in full.")
        blob = run("json", "r").stdout
        ok("`add` writes the brief to task.md", open(f"{th}/.cc/state/r/t1/task.md").read().strip() == "THE BRIEF, in full.")
        ok("…and the board JSON keeps no copy of it", "instructions" not in blob and "THE BRIEF" not in blob)
        ok("`get instructions` reads that file", run("get", "r", "t1", "instructions").stdout.strip() == "THE BRIEF, in full.")
        # #451: a 66-character row the board took and cc then refused to dispatch. Its own names: 64 kept, 65 refused.
        n64, n65 = "n" * 64, "m" * 65
        k, x = run("add", "r", n64, "T", "GOAL: kept."), run("add", "r", n65, "T", "GOAL: refused.")
        rows = json.loads(run("json", "r").stdout)["tracks"]
        ok("`add` takes a 64-character row name and refuses a 65-character one cc could not dispatch, writing nothing for it",
           k.returncode == 0 and n64 in rows and x.returncode != 0 and "64 at most" in x.stderr
           and n65 not in rows and not os.path.exists(f"{th}/.cc/state/r/{n65}"))
        # Its own fixture: cc-brief's block written into that file by hand, so this stands whether or not a board
        # anywhere has a live track. `cc done` builds the PR body out of this read.
        open(f"{th}/.cc/state/r/t1/task.md", "a").write(
            "\n<!-- cc-brief:inflight -->\nIN FLIGHT: core/bin/cc-foo — other [running]\n<!-- /cc-brief:inflight -->\n")
        ok("…without the computed IN FLIGHT block: a reader asking for the brief gets what a person typed",
           run("get", "r", "t1", "instructions").stdout.strip() == "THE BRIEF, in full.")
        run("add", "r", "t1", "T", "a one-line note")
        body = open(f"{th}/.cc/state/r/t1/task.md").read()
        ok("`add` appends to a brief instead of overwriting it (four tracks lost one that way)",
           "THE BRIEF, in full." in body and "a one-line note" in body)
        run("add", "r", "t1", "T", "a one-line note")
        ok("…and adding the same thing twice stacks nothing up",
           open(f"{th}/.cc/state/r/t1/task.md").read() == body)
        # SCOPE APPENDED AFTER DISPATCH IS SAID ON THE ROW: owner scope appended to a row whose PR was out reached
        # nobody. Own rows: t5 fresh then grown, t6 grown with its PR out; the fresh add and a repeat are the controls.
        def row(track):
            d = json.loads(run("json", "r").stdout)
            return d["tracks"][track], [e["msg"] for e in d["log"] if e.get("track") == track]
        run("add", "r", "t5", "T5", "GOAL: the first scope.")
        t5, log5 = row("t5")
        ok("a fresh `add` writes no 'scope appended' note, and its log line says added",
           not any("scope appended" in (x.get("msg") or "") for x in t5.get("notes") or [])
           and log5 == ["added: T5"])
        run("add", "r", "t5", "T5", "GOAL: a second scope, appended.")
        t5, log5 = row("t5")
        grown = [x.get("msg") or "" for x in t5.get("notes") or [] if "scope appended" in (x.get("msg") or "")]
        ok("`add` that grows an existing brief notes it on the row — its first new line, and that the next iteration "
           "reads it — and logs 'scope appended: <title>'",
           len(grown) == 1 and grown[0].startswith("scope appended (") and "GOAL: a second scope, appended." in grown[0]
           and "the next iteration reads it" in grown[0] and "PR is out" not in grown[0]
           and log5[-1] == "scope appended: T5")
        run("add", "r", "t5", "T5", "GOAL: a second scope, appended.")
        t5, log5 = row("t5")
        ok("…and the same text again grows nothing, so no second note and the log says added",
           sum("scope appended" in (x.get("msg") or "") for x in t5.get("notes") or []) == 1
           and log5[-1] == "added: T5")
        run("add", "r", "t6", "T6", "GOAL: the first scope.")
        run("set", "r", "t6", "pr", "https://example.test/o/r/pull/9")
        run("add", "r", "t6", "T6", "GOAL: scope that came after the PR.")
        t6, _ = row("t6")
        grown = [x.get("msg") or "" for x in t6.get("notes") or [] if "scope appended" in (x.get("msg") or "")]
        ok("…and on a row whose PR is out, the note says no iteration reads it until the PR is handed back",
           len(grown) == 1 and "its PR is out" in grown[0] and "the next iteration reads it" not in grown[0])
        # …but "the same thing" is a WHOLE LINE, not a prefix: `add` used a substring and --go a `head -c`, and both
        # took "note 1" for "note 10" — a dispatch note silently dropped (the stress case below found it).
        run("add", "r", "t4", "T4", "a one-line note")   # its own row: the longer line first, then the prefix, both ways
        run("add", "r", "t4", "T4", "a one-line"); run("brief", "append", "--top", "r", "t4", "a one-line")
        body = open(f"{th}/.cc/state/r/t4/task.md").read()
        ok("a note that is only the start of a line already there is a different note, at the bottom and on top",
           body.count("a one-line\n") == 2 and body.startswith("a one-line\n\n") and body.count("a one-line note\n") == 1)
        run("brief", "append", "--top", "r", "t4", "a one-line")
        ok("…and the note on top, repeated, stacks nothing up", open(f"{th}/.cc/state/r/t4/task.md").read() == body)
        T1, bak = f"{th}/.cc/state/r/t1/task.md", f"{th}/.cc/state/r/t1/task.md.bak"
        was, old = open(T1).read(), os.path.getsize(T1)
        r = run("set", "r", "t1", "instructions", "REPLACED")
        ok("`set instructions` is the explicit way to replace it",
           open(f"{th}/.cc/state/r/t1/task.md").read().strip() == "REPLACED")
        # …and it is the one deliberate way to LOSE a brief, so it says what it took out and keeps it: a 13 kB brief
        # went to 3.5 kB with rc=0 and no output, and five planning turns dug it out of a transcript (lessons, 2026-09-18).
        ok("…and it says what it replaced — old size, new size, where the old brief is — and leaves that copy whole beside it",
           f"replaced — {old} bytes → {os.path.getsize(T1)}; the old brief is {bak}" in r.stdout
           and os.path.exists(bak) and open(bak).read() == was)
        r = run("set", "r", "t1", "instructions", "REPLACED")
        ok("…a replace that changes nothing says so and does not overwrite that copy with the same text",
           "unchanged" in r.stdout and open(bak).read() == was)
        # …a step list is taken as written: `set` is a door, but shape is asked for in the prompt, not refused.
        r = run("set", "r", "t1", "instructions",
                "Do this:\n- Add a --flag to cc-foo\n- Edit cc-bar to pass it through\n- Run the suite")
        ok("`set instructions` takes a step list like any text — shape is the prompt's to ask for, not a refusal",
           r.returncode == 0 and "Run the suite" in open(f"{th}/.cc/state/r/t1/task.md").read())
        # migration: a row written before this still carries the brief in the JSON, and is moved once
        d = json.load(open(f"{th}/.cc/boards/r.json")); d["tracks"]["t2"] = {"title": "T2", "status": "queued",
            "instructions": "AN OLD BRIEF", "updated": now()}
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        got = run("get", "r", "t2", "instructions").stdout.strip()
        ok("a pre-#94 board copy migrates into task.md on first read",
           got == "AN OLD BRIEF" and open(f"{th}/.cc/state/r/t2/task.md").read().strip() == "AN OLD BRIEF")
        ok("…and is gone from the JSON afterwards, so there is only ever one authority",
           "AN OLD BRIEF" not in run("json", "r").stdout)
        ok("`show` prints the brief from the file", "Run the suite" in run("show", "r").stdout)
        d = json.load(open(f"{th}/.cc/boards/r.json")); d["tracks"]["t3"] = {"title": "T3", "status": "queued",
            "instructions": "A THIRD OLD BRIEF", "updated": now()}
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        run("add", "r", "t3", "renamed")     # a bare re-add drops the JSON copy — it must migrate it, not lose it
        rt = run("add", "r", "t3", "a note meant for the row")
        ok("a re-add of an existing row keeps the title a person set, and says how to rename or note it",
           json.load(open(f"{th}/.cc/boards/r.json"))["tracks"]["t3"]["title"] == "T3"
           and "title 'T3' is kept" in rt.stderr and "cc-board note r t3" in rt.stderr)
        run("add", "r", "ph", "ph"); rp = run("add", "r", "ph", "the real title")
        ok("…but the placeholder title (the row's own name, as cc stamps it) is replaced, without a warning",
           json.load(open(f"{th}/.cc/boards/r.json"))["tracks"]["ph"]["title"] == "the real title"
           and "is kept" not in rp.stderr)
        run("add", "r", "mg", "main is red: old failure")
        rm = run("add", "r", "mg", "main is red: new failure", env={"CC_BRIEF_MACHINE": "1"})
        ok("…and a machine writer (CC_BRIEF_MACHINE=1) re-adding its own row updates the title, as cc-audit's main gate does",
           json.load(open(f"{th}/.cc/boards/r.json"))["tracks"]["mg"]["title"] == "main is red: new failure"
           and "is kept" not in rm.stderr)
        ok("a re-add of a legacy row migrates its brief before dropping the JSON copy",
           open(f"{th}/.cc/state/r/t3/task.md").read().strip() == "A THIRD OLD BRIEF"
           and "A THIRD OLD BRIEF" not in run("json", "r").stdout)
        # a13's own proof, on rendered output rather than on the predicate: a merged row past its window is not in
        # `cc board show`, IS in `--all`, and the view says it hid something. This is the ledger row's check-cmd.
        run("add", "r", "m1", "M1 LANDED"); run("status", "r", "m1", "merged")
        fresh = run("show", "r").stdout
        d = json.load(open(f"{th}/.cc/boards/r.json")); d["tracks"]["m1"]["updated"] = "2000-01-01T00:00:00Z"
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        stale = run("show", "r").stdout
        ok("a13: a just-merged row is on the default board, one past its window is not",
           "M1 LANDED" in fresh and "M1 LANDED" not in stale)
        ok("a13: `--all` still prints it, and the default view says it hid something",
           "M1 LANDED" in run("show", "r", "--all").stdout and "finished" in stale)
        # ── THE ONE LOCKED WRITER, driven by concurrent PROCESSES — the contention it exists for. Before it, `add`,
        # `cc --go` and `cc-brief refresh` were three unlocked read-replaces with three temp names, and two landing
        # together kept whichever wrote last (arch review 2026-09-08, rec 10). Its own row; every arm below is one of
        # those writers' verbs, as the CLI runs it; afterwards every note is there once and whole, and there is ONE
        # block, well-formed, at the end. Twelve of each: with the flock taken out, twelve lost a note in every run
        # measured, six in only some (2026-09-11) — the race is real but narrow, and the case has to see it.
        run("add", "r", "st", "STRESS", "GOAL: the brief that must survive.")
        ST = f"{th}/.cc/state/r/st/task.md"; SENV = {**os.environ, "HOME": th}
        def blk(i): return f"{MARK_A}\nIN FLIGHT (from the board, 2026-09-11T00:{i:02d}Z): f{i}.txt — o [running]\n{MARK_B}\n"
        def spawn(*args, stdin=None):
            pr = subprocess.Popen([sys.executable, os.path.realpath(__file__), *args], env=SENV, text=True,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            pr.stdin.write(stdin or ""); pr.stdin.close(); return pr
        def finish(procs):
            out = []
            for pr in procs:
                try: out.append((pr.wait(timeout=120), pr.stderr.read()))
                except subprocess.TimeoutExpired: pr.kill(); out.append((124, "hung"))
            return out
        N = 12
        procs = []
        for i in range(N):   # interleaved: an add's append, a --go's re-dispatch and a refresh's annotate, six times over
            procs += [spawn("brief", "append", "r", "st", f"bottom note {i}"),
                      spawn("brief", "append", "--top", "r", "st", f"dispatch note {i}"),
                      spawn("brief", "annotate", "r", "st", "-", stdin=blk(i))]
        rcs = finish(procs); got = open(ST).read(); typed = human(got); b = INFLIGHT_RE.search(got)
        ok("stress: 12 appends, 12 re-dispatches and 12 annotates at once all serialise — none refused, none hung",
           all(rc == 0 for rc, _ in rcs) or print("   ", [e for rc, e in rcs if rc]))
        ok("stress: no note is lost, torn or doubled, and the brief they joined is whole",
           "GOAL: the brief that must survive.\n" in typed
           and all(typed.count(f"bottom note {i}\n") == 1 and typed.count(f"dispatch note {i}\n") == 1 for i in range(N)))
        ok("stress: exactly one block afterwards, well-formed, one annotate's own, and last in the file",
           got.count(MARK_A) == 1 and got.count(MARK_B) == 1 and b is not None
           and b.group(0) in [blk(i) for i in range(N)] and got.endswith(b.group(0)))
        # …and a REPLACE in the mix: the new brief is there once, a note that landed after it is whole, and one before
        # it is gone — that is what replace is for — and the block is still one block.
        procs = [spawn("brief", "append", "r", "st", f"late note {i}") for i in range(3)]
        procs.insert(1, spawn("brief", "replace", "r", "st", "REPLACED: the brief, deliberately."))
        procs.insert(3, spawn("brief", "annotate", "r", "st", "-", stdin=blk(9)))
        rcs = finish(procs); got = open(ST).read(); typed = human(got)
        ok("stress: a replace among appends and an annotate — none refused, the new brief once, every surviving note whole, one block",
           all(rc == 0 for rc, _ in rcs) and typed.count("REPLACED: the brief, deliberately.\n") == 1
           and all(typed.count(f"late note {i}\n") in (0, 1) for i in range(3)) and "bottom note" not in typed
           and got.count(MARK_A) == 1 and got.count(MARK_B) == 1)
        # ── A BOARD WRITE HAPPENS WHOLE OR NOT AT ALL (2026-09-19). Two course seats ran `add` at the same moment and
        # both rows were found with a task.md, a log line and no entry in tracks{} — the board's log says `rm` took
        # them (11:03Z, another seat), not a lost write; N adds at once ARE N rows, and this pins it. But the brief DID
        # land before the board was so much as opened, so an add that failed at the board step (no board, a lock held
        # past the wait, a save that failed) left exactly that half-row: a brief nothing can close. Now it leaves nothing.
        procs = [spawn("add", "r", f"c{i}", f"C{i}", f"GOAL: row {i} lands whole.") for i in range(N)]
        rcs = finish(procs); rows = json.load(open(f"{th}/.cc/boards/r.json"))
        ok("12 `add`s at once are 12 rows in tracks{}, each with its log line and its brief — none refused, none lost",
           all(rc == 0 for rc, _ in rcs) and all(f"c{i}" in rows["tracks"] for i in range(N))
           and sum(1 for l in rows["log"] if l["msg"].startswith("added: C")) == N
           and all(open(f"{th}/.cc/state/r/c{i}/task.md").read().startswith(f"GOAL: row {i} lands whole.") for i in range(N)))
        r = run("add", "nob", "x", "T", "GOAL: a brief for a board that is not there.")
        ok("an `add` for a repo with no board says so and writes nothing — no state dir, no brief",
           r.returncode != 0 and "no board" in r.stderr and not os.path.exists(f"{th}/.cc/state/nob"))
        holder = open(f"{th}/.cc/boards/r.lock", "w"); fcntl.flock(holder, fcntl.LOCK_EX)
        HENV = {**SENV, "CC_BOARD_LOCK_WAIT": "0.5"}
        def held_add(*args): return subprocess.run([sys.executable, os.path.realpath(__file__), "add", *args], env=HENV,
                                                   capture_output=True, text=True, timeout=60)
        was = open(ST).read()
        r1 = held_add("r", "held1", "H", "GOAL: never lands.")
        r2 = held_add("r", "st", "STRESS", "GOAL: a note that must come out again.")
        holder.close()
        ok("an `add` whose board lock is held past the wait is refused in one line, and the brief it had written comes out again — no half-row",
           r1.returncode != 0 and "held by another process" in r1.stderr
           and "held1" not in json.load(open(f"{th}/.cc/boards/r.json"))["tracks"] and not os.path.exists(f"{th}/.cc/state/r/held1"))
        ok("…and on a row that had a brief, the note comes out and the brief is exactly what it was",
           r2.returncode != 0 and "held by another process" in r2.stderr and open(ST).read() == was)
        ok("…and the same add lands once the lock is free", run("add", "r", "held1", "H", "GOAL: never lands.").returncode == 0
           and "held1" in json.load(open(f"{th}/.cc/boards/r.json"))["tracks"] and open(f"{th}/.cc/state/r/held1/task.md").read() == "GOAL: never lands.\n")
        # A LOCK SOMEBODY ELSE HOLDS is waited for, briefly, then refused in one line — never a hang, never a write
        # through it — and the same edit lands once it is free. In-process, ungated: the shape check is not what is under test.
        real_wait, LOCK_WAIT, sroot = LOCK_WAIT, 0.5, f"{th}/.cc/state"
        try:
            holder = open(f"{th}/.cc/state/r/st/task.md.lock", "w"); fcntl.flock(holder, fcntl.LOCK_EX)
            before = open(ST).read(); t0 = time.monotonic()
            got = bounded(lambda: brief_edit("append", "r", "st", "a note under a held lock", state=sroot, gated=False), 5)
            waited = time.monotonic() - t0; holder.close()
            ok("a brief lock somebody else holds is waited for, briefly, then refused in one line — not a hang — and nothing is written",
               isinstance(got, Refused) and "held by another process" in str(got) and 0.4 < waited < 5 and open(ST).read() == before)
            got = bounded(lambda: brief_edit("append", "r", "st", "a note under a held lock", state=sroot, gated=False), 5)
            ok("…and the same edit lands once the lock is free", not isinstance(got, Exception) and "a note under a held lock\n" in open(ST).read())
        finally: LOCK_WAIT = real_wait
        # THE WALLS (security review of #225), now the writer's: the state dir is member-writable, so a link at the
        # track dir or at task.md is refused — never made through, read through or written through.
        os.symlink(f"{th}/elsewhere", f"{sroot}/r/lnk"); os.makedirs(f"{sroot}/r/lnk2")
        os.symlink("/etc/hostname", f"{sroot}/r/lnk2/task.md")
        r1 = bounded(lambda: brief_edit("append", "r", "lnk", "x", state=sroot, gated=False), 5)
        r2 = bounded(lambda: brief_edit("append", "r", "lnk2", "x", state=sroot, gated=False), 5)
        ok("a link at the track dir is refused, and nothing is made through it",
           isinstance(r1, Refused) and not os.path.exists(f"{th}/elsewhere"))
        ok("a link at task.md is refused, not read or written through, and leaves no temp file behind",
           isinstance(r2, Refused) and os.path.islink(f"{sroot}/r/lnk2/task.md") and not glob.glob(f"{sroot}/r/lnk2/*.tmp"))
        real_state = STATE; STATE = sroot
        try: leaked = read_brief("r", "lnk2")
        finally: STATE = real_state
        ok("WALL (secrets): read_brief — what show, get and cc done's PR body print — reads '' through a link at task.md, "
           "never the file it names", leaked == "" and open("/etc/hostname").read() not in ("", leaked))
        ok("a brief that is not there is not made for an annotate", brief_edit("annotate", "r", "none", blk(1), state=sroot) == ("", "")
           and not os.path.exists(f"{sroot}/r/none"))
        # a shell-mangled emoji reaches argv as a lone surrogate; stored once, it turned every `show` into a traceback
        bad = "T \udc94 mangled"
        r = run("add", "r", "s1", bad); run("set", "r", "s1", "title", bad)
        stored = json.load(open(f"{th}/.cc/boards/r.json"))["tracks"]["s1"]["title"]
        ok("`add` and `set title` never store a lone surrogate", r.returncode == 0 and "\udc94" not in stored and "mangled" in stored)
        d = json.load(open(f"{th}/.cc/boards/r.json")); d["tracks"]["s1"]["title"] = bad   # one written before this fix
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        sh, ls = run("show", "r"), run("list")
        ok("`show` and `list` print a bad title already on disk instead of crashing",
           sh.returncode == 0 and ls.returncode == 0 and "mangled" in sh.stdout and "mangled" in ls.stdout)
        # THE BASE IS A REPO FACT, and this is how a shell reader asks for it — cc, cc-loop and cc-checkpoint all
        # do, before they trust origin/HEAD. This is the contract those three read, so it is pinned on a base that
        # is NOT `main`: `main` is also the word every one of them falls back to, so a `base` that answered it
        # blindly would look right in all three (review of #230). A repo with no board answers an empty line and
        # rc 0 rather than failing — `cc` asks while it is creating one — and that empty answer is the callers' cue.
        run("init", "r", "/tmp/r", "trunk")
        ok("`base` prints the board's base, not the word its callers fall back to", run("base", "r").stdout == "trunk\n")
        run("init", "r", "/tmp/r", "main")   # …and back, so the rows below read the board every other case wrote
        nb = run("base", "nosuch")
        ok("…and a repo with no board answers an empty line and rc 0, which is how a caller knows to fall back",
           nb.stdout == "\n" and nb.returncode == 0 and run("base", "r").stdout == "main\n")
        # KIND: a row is a `track` unless it says `session`, and a session row says so wherever a row is printed
        ok("a row with no kind field is a track, and `add` stamps the kind on a new row",
           run("get", "r", "t2", "kind").stdout.strip() == "track"
           and json.load(open(f"{th}/.cc/boards/r.json"))["tracks"]["t1"]["kind"] == "track")
        r = run("set", "r", "t1", "kind", "channel")
        ok("`set kind` takes track or session and nothing else",
           r.returncode != 0 and run("get", "r", "t1", "kind").stdout.strip() == "track")
        # A FIELD NAME THAT DOES NOT EXIST IS AN ERROR, NOT A DEAD KEY (2026-09-07): `set … state review` used to
        # write a `state` key beside the real `status` and print nothing — the exact confusion that cost two
        # sessions a silent no-op before either found the cause.
        r = run("set", "r", "t1", "state", "review")
        ok("`set` refuses a field it does not know, naming the fields that do exist, and writes nothing",
           r.returncode != 0 and "state" in r.stderr and "status" in r.stderr
           and "state" not in json.load(open(f"{th}/.cc/boards/r.json"))["tracks"]["t1"])
        run("set", "r", "t1", "status", "review")
        ok("…while a field that does exist still sets, `status` included",
           run("get", "r", "t1", "status").stdout.strip() == "review")
        run("set", "r", "t1", "status", "queued")   # back to what later cases in this suite expect of t1
        # cc-board-dream marks a row it set done (`dream`, and `folded_into` for a fold) and never takes such a row as
        # evidence; a person who reopens or completes it through either door makes it theirs, so the marks go.
        def dream_mark():
            bd = json.load(open(f"{th}/.cc/boards/r.json"))
            bd["tracks"]["t1"].update(status="done", dream="r:x:0", folded_into="t9")
            json.dump(bd, open(f"{th}/.cc/boards/r.json", "w"))
        def marks():
            row = json.load(open(f"{th}/.cc/boards/r.json"))["tracks"]["t1"]
            return [k for k in ("dream", "folded_into") if k in row], row["status"]
        dream_mark(); run("status", "r", "t1", "queued"); m1 = marks()
        dream_mark(); run("set", "r", "t1", "status", "queued"); m2 = marks()
        ok("a status set through `status` or `set … status` clears cc-board-dream's done marks",
           m1 == ([], "queued") and m2 == ([], "queued"))
        # A STRING `notes` FIELD (three rows on the live board carry one today, from `set … notes "<text>"`
        # writing any field verbatim before this fix): `note` used to crash on it with AttributeError —
        # 'str' object has no attribute 'append'.
        rpath = f"{th}/.cc/boards/r.json"
        bj = json.load(open(rpath)); bj["tracks"]["t1"]["notes"] = "an old string note"
        json.dump(bj, open(rpath, "w"))
        rn = run("note", "r", "t1", "a new note")
        ok("`note` takes a row whose `notes` field is a string, rather than crashing on .append",
           rn.returncode == 0 and rn.stderr == "")
        sh2, js2 = run("show", "r").stdout, run("json", "r").stdout
        ok("…and `show`/`json` list both the old text and the new note",
           "an old string note" in sh2 and "a new note" in sh2
           and "an old string note" in js2 and "a new note" in js2)
        run("set", "r", "t1", "notes", "set writes one note, not a bare string")
        ok("`set … notes \"x\"` leaves a list behind",
           isinstance(json.load(open(rpath))["tracks"]["t1"]["notes"], list))
        run("add", "r", "sess9", "a course session", ""); run("set", "r", "sess9", "kind", "session")
        run("status", "r", "sess9", "running"); run("add", "r", "sess9", "a course session", "")
        ok("a session row keeps its kind across a re-add", run("get", "r", "sess9", "kind").stdout.strip() == "session")
        ls, sh = run("list").stdout, run("show", "r").stdout
        ok("`list` says `session` in the status column for a session row — cc ls, cc digest and cc resume read that "
           "column — and a track's status exactly as before",
           "r\tsess9\tsession\t" in ls and "r\tt1\tqueued\t" in ls)
        ok("`show` prints a session row after the tracks, indented, with no status icon; a track row as before",
           "  ↳ \033[1msess9\033[0m [session]  a course session" in sh and "  · \033[1mt1\033[0m [queued]" in sh
           and sh.index("[queued]") < sh.index("[session]"))
        run("add", "r", "numbered", "a numbered worker", ""); run("set", "r", "numbered", "agent_no", "a9")
        shn = run("show", "r").stdout
        ok("`show` prints a row's agent number beside its name, and a row with none as before",
           "\033[1mnumbered\033[0m a9 [queued]" in shn and "\033[1mt1\033[0m [queued]" in shn)
        # THE TASK IDENTITY ON THE ROW (bin/cc-task). It is read off the row's own state dir at render time, so
        # there is nothing on the board to get out of step with it — and a row without a record is byte-identical
        # to what it printed before this existed, which is what "preserve legacy rows" has to mean.
        def lay(row, rec):
            os.makedirs(f"{th}/.cc/state/r/{row}", exist_ok=True)
            with open(f"{th}/.cc/state/r/{row}/delivery.json", "w") as fh: fh.write(rec)
        task = {"schema": 1, "repo": "r", "row": "t1", "task_id": "00000000-0000-4000-8000-000000000001",
                "claim": {"executor": "subagent", "phase": "starting", "started_at": now()}}
        dp = f"{th}/.cc/state/r/t1/delivery.json"
        before, tsv = run("show", "r").stdout, run("list").stdout
        lay("t1", json.dumps(task)); projected = run("show", "r").stdout
        detail = next((l for l in projected.splitlines(True) if "delivery:" in l), "")
        ok("`show` projects the task UUID, executor, phase and claim age; every other byte, and the TSV, are unchanged",
           task["task_id"] in detail and "subagent  starting  claim age " in detail
           and re.search(r"claim age \d+s", detail) is not None
           and projected.replace(detail, "", 1) == before and run("list").stdout == tsv)
        task["claim"].update(executor="worker", phase="released", started_at="2000-01-01T00:00:00Z")
        lay("t1", json.dumps(task)); changed = run("show", "r").stdout
        ok("the line follows the durable record, an old claim included — no board field caches any of it",
           "worker  released  claim age " in changed and "claim age 0s" not in changed
           and "subagent  starting" not in changed)
        task["claim"].update(phase="released", ended_at=now(), reason="worker launched")
        lay("t1", json.dumps(task)); ended = run("show", "r").stdout
        ok("a claim that has ended says why, not what it was last doing — a worker's is handed back at launch",
           "worker  ended (worker launched)  claim age " in ended and "  released  " not in ended)
        task["claim"].pop("ended_at"); task["claim"].pop("reason")
        task["row"] = "sibling"; lay("t1", json.dumps(task))
        ok("a record naming another row is not this row's, and shows nothing", run("show", "r").stdout == before)
        junk = ('{', '"held"', '17', 'null', '[{"schema": 1}]', '{"schema": 1, "repo": "r", "row": "t1"}')
        for j in junk: lay("t1", j)
        outs = [(lay("t1", j), run("show", "r"))[1] for j in junk]
        ok("nothing shaped like a record shows one — unparseable, a bare scalar, a list, no task id — and the "
           "board is whole either way (that dir is bound rw into a worker sandbox and a member workspace)",
           all(o.stdout == before and "Traceback" not in o.stderr for o in outs))
        lay("t1", '{"schema": 1, "repo": "r", "row": "t1", "task_id": "x", "claim": "held"}')
        broken = run("show", "r")
        ok("…and a record whose claim is a string still prints its row, with the claim unknown rather than a traceback",
           "Traceback" not in broken.stderr and broken.returncode == 0
           and "delivery: x  ?  ?  claim age unknown" in broken.stdout
           and broken.stdout.replace("      delivery: x  ?  ?  claim age unknown\n", "", 1) == before)
        os.remove(dp); task["row"] = "sess9"; lay("sess9", json.dumps(task))
        ok("a row with no record, and a session row with a task-shaped file beside it, print exactly as before",
           run("show", "r").stdout == before and run("list").stdout == tsv)
        os.remove(f"{th}/.cc/state/r/sess9/delivery.json")
        # AGENT: who is on a row when nothing on the box is. `me` stamps the session's OWN tmux window, because a
        # subagent is not a process cc-reconcile or cc-pulse can see, and the session running it is (owner, 2026-09-04).
        stub = f"{th}/stub"; os.makedirs(stub, exist_ok=True)
        def tmux_stub(body):
            open(f"{stub}/tmux", "w").write("#!/bin/sh\n" + body + "\n"); os.chmod(f"{stub}/tmux", 0o755)
        def runt(*args, pane="%9", ccpane=""):   # CC_TMUX_PANE always set here: a seat running this suite has its own
            return subprocess.run([sys.executable, os.path.realpath(__file__), *args],
                                  env={**os.environ, "HOME": th, "TMUX_PANE": pane, "CC_TMUX_PANE": ccpane,
                                       "PATH": stub + os.pathsep + os.environ.get("PATH", "")},
                                  capture_output=True, text=True)
        # the three fields agent_id asks for: the mark, and the two things a reader tests the window on
        # THE STUB ANSWERS BOTH QUESTIONS agent_id ASKS, because the second one is the whole check: the pane's
        # own line, and `list-windows -t main`, which is what cc-pulse and cc-reconcile ask. `listed=False` is a
        # window that session does not have.
        def win_stub(sess, name, mark="@7:4242", listed=True):
            wid = mark.split(":")[0]
            nm = name.replace("\n", "\\n")   # a window name MAY hold a newline, and that is a case below: printf puts it back
            tmux_stub(f'[ "$1" = list-windows ] && {{ printf "@4\\n{wid if listed else "@6"}\\n"; exit 0; }}\n'
                      f'printf "{mark}\\t{sess}\\t{nm}\\n"')
        win_stub("main", "r")
        runt("set", "r", "t1", "agent", "me")
        ok("`set … agent me` stores this session's window AND the tmux server that numbered it — window ids "
           "restart at @0 when the server does, and a mark left across a reboot must match nothing",
           run("get", "r", "t1", "agent").stdout.strip() == "@7:4242")
        r = runt("set", "r", "t1", "agent", "me", pane="")
        ok("…outside tmux it refuses rather than storing a mark that means nothing, and the old one stands",
           r.returncode != 0 and run("get", "r", "t1", "agent").stdout.strip() == "@7:4242")
        win_stub("main", "r", mark="@8:4242")
        r = runt("set", "r", "t1", "agent", "me", pane="", ccpane="%9")
        ok("…but a seat whose claude lost $TMUX_PANE (a restored one: claude scrubs it on respawn) marks through "
           "$CC_TMUX_PANE, which `cc __run*` set from the same pane",
           r.returncode == 0 and run("get", "r", "t1", "agent").stdout.strip() == "@8:4242")
        win_stub("main", "r")
        runt("set", "r", "t1", "agent", "me")
        tmux_stub("exit 1")
        r = runt("set", "r", "t1", "agent", "me")
        ok("…and a tmux that will not name the window is a refusal too, never a blank mark",
           r.returncode != 0 and run("get", "r", "t1", "agent").stdout.strip() == "@7:4242")
        win_stub("main", "r")
        r = runt("set", "r", "t1", "agent", "@1:2")
        ok("A MARK IS MADE BY THE SESSION IT NAMES, never typed: every session writes this one file, so a "
           "hand-written id naming somebody else's live window would hold a row open with nothing to see",
           r.returncode != 0 and run("get", "r", "t1", "agent").stdout.strip() == "@7:4242")
        at1 = run("get", "r", "t1", "agent_at").stdout.strip()
        ok("a mark carries WHEN it was made, because a mark that never expires holds a row open for as long as "
           "the session's window lives — and `updated` cannot say, every other `set` moves it too",
           re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", at1) is not None)
        d = json.load(open(f"{th}/.cc/boards/r.json"))
        d["tracks"]["t1"]["agent_at"] = "2020-01-01T00:00:00Z"
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        runt("set", "r", "t1", "agent", "me")
        ok("…and marking again refreshes it: that is how a session still on the row says so, and the one command "
           "it costs is the whole price of the mark expiring at all",
           run("get", "r", "t1", "agent_at").stdout.strip() >= at1)
        d = json.load(open(f"{th}/.cc/boards/r.json"))
        d["tracks"]["t1"]["agent_at"] = "2020-01-01T00:00:00Z"
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        r = run("set", "r", "t1", "agent_at", "2099-01-01T00:00:00Z")
        ok("THE CLOCK IS NOT A FIELD ANYONE SETS: setting it by hand is refused and the cold mark stays cold — "
           "otherwise any writer of this file could refresh a stale mark for ever, or stamp a time onto a row "
           "with no mark at all",
           r.returncode != 0 and run("get", "r", "t1", "agent_at").stdout.strip() == "2020-01-01T00:00:00Z"
           and run("set", "r", "t2", "agent_at", "2099-01-01T00:00:00Z").returncode != 0
           and run("get", "r", "t2", "agent_at").stdout.strip() == "")
        runt("set", "r", "t1", "agent", "me")
        run("set", "r", "t1", "agent", "")
        ok("`agent ''` hands the row back, time and all",
           run("get", "r", "t1", "agent").stdout.strip() == ""
           and run("get", "r", "t1", "agent_at").stdout.strip() == "")
        # WHEN A WORKER STARTED: stamped once on the first start of each kind, never moved, never set by hand
        for dpn in ("dp1", "dp2", "dp3", "dp4"):   # not `n` (the failure count ok() keeps) nor `row` (a helper)
            run("add", "r", dpn, dpn)
        runt("set", "r", "dp1", "agent", "me"); run("status", "r", "dp2", "running")
        run("note", "r", "dp3", "dispatched headless worker (loop 1)"); run("note", "r", "dp4", "a remark")
        run("status", "r", "dp4", "review")
        dp = lambda dpn: run("get", "r", dpn, "dispatched").stdout.strip()
        first = dp("dp2")
        d = json.load(open(f"{th}/.cc/boards/r.json"))
        d["tracks"]["dp2"]["dispatched"] = "2020-01-01T00:00:00Z"
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        run("status", "r", "dp2", "running")
        ok("a row a worker starts on carries `dispatched` (a mark, `status running` or cc --go's note), kept once "
           "stamped; a remark or another status stamps nothing, and it is not set by hand",
           all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", dp(dpn) or "") for dpn in ("dp1", "dp3")) and first
           and dp("dp2") == "2020-01-01T00:00:00Z" and dp("dp4") == ""
           and run("set", "r", "dp4", "dispatched", "2099-01-01T00:00:00Z").returncode != 0 and dp("dp4") == "")
        # A MARK FROM A WINDOW NO READER COUNTS IS REFUSED (2026-09-07). The reader keeps a mark only where its
        # window is in tmux session `main` and named for the ROW'S OWN REPO — cc-reconcile's mark_why matches
        # `#{window_name}` against the repo, and cc-pulse and the Home tab read its snapshot. A
        # claim from any other window therefore records an owner nobody recognises: the row reads unowned, the
        # watchdog calls it abandoned and it is offered for dispatch while the subagent is still writing it, so
        # the claim RELEASES the row instead of holding it. Its own row, marked by a window it does not use.
        d = json.load(open(f"{th}/.cc/boards/r.json"))
        d["tracks"]["u1"] = {"title": "u1", "status": "running", "agent": "@5:900", "kind": "track",
                             "agent_at": "2020-01-01T00:00:00Z", "updated": "2020-01-01T00:00:00Z"}
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        u1 = lambda k="agent": json.load(open(f"{th}/.cc/boards/r.json"))["tracks"]["u1"].get(k, "")
        for sess, name, why in (("main", "r~old", "a session cc-handoff retired, subagents still running"),
                                ("main", "r/t1", "a track session"),
                                ("main", "other", "a session speaking for another repo"),
                                ("main", "other@x1", "an orch of another repo"),
                                ("main", "rr@x1", "an orch of a repo whose name merely starts with this one"),
                                ("main", "r@x1~old", "an orch cc-handoff retired, whose marks stopped counting"),
                                ("main", "r@", "an orch shape with no alias in it"),
                                ("main", "r@a\nzzz", "a name whose SECOND line is what a reader would parse"),
                                ("work", "r", "the right name outside the tmux session cc-pulse lists"),
                                ("work", "r@x1", "an orch outside the tmux session cc-pulse lists")):
            win_stub(sess, name, listed=(sess != "work"))
            rf = runt("set", "r", "u1", "agent", "me")
            ok(f"a mark from {why} — window '{name}' in '{sess}' — is refused, the reason names both what this "
               "window is and what a read one would be, and the row keeps the mark and the clock it already "
               "had: a claim must never be the thing that releases a row",
               rf.returncode != 0 and f"'{name}' in tmux session '{sess}'" in rf.stderr
               and "named 'r' or 'r@<alias>' in 'main'" in rf.stderr
               and u1() == "@5:900" and u1("agent_at") == "2020-01-01T00:00:00Z"
               and u1("updated") == "2020-01-01T00:00:00Z")
        # A SESSION GROUPED ONTO `main` IS ON `main`. `tmux new-session -t main` shares main's windows, and tmux
        # answers a pane's #{session_name} with whichever session of the group it resolves — `main-13`, say.
        # Testing that NAME refused a live planning session's claim on its own row (2026-09-07) while both
        # readers, which ask `list-windows -t main`, listed the very same window and
        # would have counted the mark. The window a reader counts is the window `main` lists, so ask that.
        win_stub("main-13", "r")
        rf = runt("set", "r", "u1", "agent", "me")
        ok("a session grouped onto `main` — tmux answers 'main-13' for its pane — marks its own row, because "
           "the readers list that window under `main` and would count it",
           rf.returncode == 0 and u1() == "@7:4242")
        # AN ORCHESTRATOR IS A SESSION OF THIS REPO. `cc <repo> --orch <alias>` opens `<repo>@<alias>` beside the
        # planning window, on the same checkout and the same board, and both readers have counted its mark since
        # #329 — only this end refused it, so an orch could not claim a row at all. Two rows two orchs were
        # working were flipped to `blocked` on the owner's list and offered for dispatch again (2026-09-08).
        d = json.load(open(f"{th}/.cc/boards/r.json"))
        d["tracks"]["u1"]["agent"] = "@5:900"; d["tracks"]["u1"]["agent_at"] = "2020-01-01T00:00:00Z"
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        win_stub("main-18", "r@improve")
        rf = runt("set", "r", "u1", "agent", "me")
        ok("…and so does an ORCHESTRATOR of this repo, from 'r@improve' in the session tmux answers for its "
           "pane: it is a peer session on the same board, and both readers count that name",
           rf.returncode == 0 and u1() == "@7:4242" and u1("agent_at") > "2020-01-01T00:00:00Z")
        run("set", "r", "u1", "agent", "@5:900")
        d = json.load(open(f"{th}/.cc/boards/r.json"))
        d["tracks"]["u1"]["agent"] = "@5:900"; d["tracks"]["u1"]["agent_at"] = "2020-01-01T00:00:00Z"
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        win_stub("main", "r")
        rf = runt("set", "r", "u1", "agent", "me")
        ok("…and from the window a reader DOES count the same command claims exactly as it always did — this "
           "refuses a bad mark, it does not add a way to write one",
           rf.returncode == 0 and u1() == "@7:4242" and u1("agent_at") > "2020-01-01T00:00:00Z")
        win_stub("main", "r~old")
        rf = runt("set", "r", "u1", "agent", "")
        ok("…while HANDING A ROW BACK is not a claim and still works from any window at all: the refusal is "
           "about writing an owner nobody reads, never about a session letting go of a row",
           rf.returncode == 0 and u1() == "" and u1("agent_at") == "")
        # HANDOVER: the one way a mark moves to a window other than the one that made it. cc-handoff calls it at a
        # cutover, because the retiring session's subagents keep running and report into its successor — without it
        # the watchdog called five such rows abandoned ten minutes later and put them back in the pool (2026-09-07).
        d = json.load(open(f"{th}/.cc/boards/r.json"))
        for row, ag in (("h1", "@3:900"), ("h2", "@3:900"), ("h3", "@30:900"), ("h4", "")):
            d["tracks"][row] = {"title": row, "status": "running", "agent": ag, "kind": "track",
                                "agent_at": "2020-01-01T00:00:00Z", "updated": "2020-01-01T00:00:00Z"}
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        fld = lambda row, k: json.load(open(f"{th}/.cc/boards/r.json"))["tracks"][row].get(k, "")
        mv = run("handover", "r", "@3:900", "@7:900", "h1", "h3", "h4", "nosuch")
        ok("`handover` moves the rows it is named that carry exactly that mark, and prints what moved",
           mv.returncode == 0 and mv.stdout == "h1\n" and fld("h1", "agent") == "@7:900"
           and fld("h1", "updated") > "2020-01-01T00:00:00Z")
        ok("…carrying the mark's CLOCK rather than restarting it: a mark both readers had already expired stays "
           "expired, or a cutover would revive a row whose subagent died hours ago and hold it six hours more",
           fld("h1", "agent_at") == "2020-01-01T00:00:00Z")
        ok("…and only those: a row carrying the same mark that was not named is left where it was",
           fld("h2", "agent") == "@3:900")
        ok("…never on a prefix of the window id: `@3:900` is not `@30:900`, and that match would hand one "
           "session's live row to another in silence", fld("h3", "agent") == "@30:900")
        ok("…and it never CLAIMS a row — an unmarked row named on the line stays unmarked, which is why this is "
           "not the hole `set … agent` refuses: nothing is held that was not held already",
           fld("h4", "agent") == "")
        bad = run("handover", "r", "@3:900", "@7", "h2")
        same = run("handover", "r", "@7:900", "@7:900", "h1")
        ok("…a destination that is not a mark, and a move onto the same window, are refused and write nothing",
           bad.returncode != 0 and same.returncode != 0 and fld("h2", "agent") == "@3:900"
           and fld("h1", "agent") == "@7:900")
        typed = run("set", "r", "h2", "agent", "@7:900")
        ok("…and `set … agent` still takes only `me` and '': the exception is this verb, not the field",
           typed.returncode != 0 and fld("h2", "agent") == "@3:900")
        d = json.load(open(f"{th}/.cc/boards/r.json"))
        for row in ("h1", "h2", "h3", "h4"): d["tracks"].pop(row)
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        # A ROW SOMEBODY IS DELIBERATELY SITTING ON (see `held` up top). The watchers each have their own case;
        # these are the ones this file owns — the word goes on, the word comes off, and the row is otherwise
        # exactly the row it was.
        d = json.load(open(f"{th}/.cc/boards/r.json"))
        d["tracks"]["k1"] = {"title": "k1", "status": "review", "kind": "track", "pr": "#325",
                             "agent": "@3:900", "agent_at": "2020-01-01T00:00:00Z",
                             "notes": [{"ts": now(), "msg": "behind #309"}], "updated": now()}
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        run("set", "r", "k1", "held", "behind #309, which carries a paid verdict — #309 first, then rebase")
        sh = run("show", "r").stdout
        ok("`set … held` stores the reason and stamps who held it and when",
           fld("k1", "held").startswith("behind #309") and fld("k1", "held_by") and fld("k1", "held_at"))
        ok("…and `show` still lists a held row, with its reason: every watcher is quiet about it on purpose, so "
           "this is the only place a person is offered it at all",
           "\033[1mk1\033[0m [review]" in sh and "      held (" in sh and "behind #309" in sh)
        ok("…while NOTHING ELSE about the row changes — status, PR, notes and the `agent` mark all stand",
           (fld("k1", "status"), fld("k1", "pr"), fld("k1", "agent")) == ("review", "#325", "@3:900")
           and fld("k1", "agent_at") == "2020-01-01T00:00:00Z" and "#325" in sh and "behind #309" in sh)
        by, at = run("set", "r", "k1", "held_by", "someone"), run("set", "r", "k1", "held_at", now())
        ok("neither stamp is settable by hand — a typed holder names somebody who never agreed to be asked — "
           "and the hold is left exactly as it was",
           by.returncode != 0 and at.returncode != 0 and fld("k1", "held_by") != "someone"
           and fld("k1", "held").startswith("behind #309"))
        run("set", "r", "k1", "held", "")
        ok("`set … held ''` lifts the hold and clears both stamps: the row goes back to being every watcher's",
           (fld("k1", "held"), fld("k1", "held_by"), fld("k1", "held_at")) == ("", "", ""))
        d = json.load(open(f"{th}/.cc/boards/r.json")); d["tracks"].pop("k1")
        json.dump(d, open(f"{th}/.cc/boards/r.json", "w"))
        # A FIXTURE IS NOT A BOARD: a `_cctest<pid>` board with a waiting row beside the real one is in neither `list`
        # nor `boards` unless `--all` asks — the one rule every reader of ~/.cc/boards calls or names
        json.dump({"repo": "_cctest99999999", "tracks": {"w1": {"status": "waiting", "title": "push refused", "updated": now()}}},
                  open(f"{th}/.cc/boards/_cctest99999999.json", "w"))
        ls, la, bs, ba = run("list").stdout, run("list", "--all").stdout, run("boards").stdout, run("boards", "--all").stdout
        ok("a `_cctest<pid>` board is a selftest fixture, not a board: `list` and `boards` skip it and print the real one beside it",
           "_cctest" not in ls and "r\tt1\t" in ls and bs.split() == ["r"])
        ok("…and `--all` is the only way to see it", "_cctest99999999\tw1\twaiting" in la and ba.split() == ["_cctest99999999", "r"])
        # …but INSIDE its run it is a board: the suite's own `cc ls` / `cc digest` descend from <pid>. This selfcheck
        # stands in for the suite — the cc-board it spawns is under our pid — and the 99999999 one stays hidden beside it
        own = f"_cctest{os.getpid()}"
        json.dump({"repo": own, "tracks": {"w1": {"status": "running", "title": "own run", "updated": now()}}},
                  open(f"{th}/.cc/boards/{own}.json", "w"))
        lo, bo = run("list").stdout, run("boards").stdout.split()
        ok("…while the run that made a fixture — any process under its <pid> — sees it as a board without --all",
           f"{own}\tw1\trunning" in lo and "_cctest99999999" not in lo and bo == [own, "r"])
        os.remove(f"{th}/.cc/boards/_cctest99999999.json"); os.remove(f"{th}/.cc/boards/{own}.json")
        # THE PREFIX IS THE NAMESPACE, NOT ONE SUITE'S NAME: cc-sandbox's selfchecks name their scratch `_ccsbx<pid>`,
        # and a leaked one was read as a real repo whose worktrees no board knew (2026-09-02). Its own fixtures, both
        # sides: the dead suite's board is hidden, this run's is not, and a repo that merely contains the word is real.
        json.dump({"repo": "_ccsbx99999999", "tracks": {"t": {"status": "running", "title": "leak", "updated": now()}}},
                  open(f"{th}/.cc/boards/_ccsbx99999999.json", "w"))
        json.dump({"repo": "myrepo_cctesting", "tracks": {"t": {"status": "running", "title": "real", "updated": now()}}},
                  open(f"{th}/.cc/boards/myrepo_cctesting.json", "w"))
        mine = f"_ccsbx{os.getpid()}"
        json.dump({"repo": mine, "tracks": {"t": {"status": "running", "title": "ours", "updated": now()}}},
                  open(f"{th}/.cc/boards/{mine}.json", "w"))
        bs, ba = run("boards").stdout.split(), run("boards", "--all").stdout.split()
        ok("a leaked `_ccsbx<pid>` board is a fixture on the same rule as `_cctest<pid>` — the suite is gone, so it is "
           "scaffolding — while this run's own is a board, and a real repo that merely CONTAINS the word always was",
           bs == [mine, "myrepo_cctesting", "r"] and "_ccsbx99999999" in ba)
        for b in ("_ccsbx99999999", "myrepo_cctesting", mine):
            os.remove(f"{th}/.cc/boards/{b}.json")
        # …AND THE RULE IS ASKED, NOT COPIED (arch review 2026-09-08, rec 11). cc-reconcile, the Home tab, cc-land's
        # catch-up and cc-janitor import this file and call these — so the whole answer, in one batch, on the names
        # a listing hands them, with this process standing in for the suite (its pid is the one in lineage):
        # a suite's live fixture is a board to its descendants only, an orphan is a board to nobody, and a repo that
        # merely contains the word is real everywhere.
        ex = ["_cctest99999999", "_ccsbx99999999.json", "myrepo_cctesting", f"_cctest{os.getpid()}", "_cclive.lock",
              f"_ccsbx{os.getpid()}.json", "r.json", "myrepo_cctest12"]
        ok("`reals` is the batched answer: from one listing, in its order, the real repos and this run's own fixtures — "
           "another suite's, an orphan's and a prefixed name with no pid are gone; the repo that contains the word stays",
           reals(ex) == ["myrepo_cctesting", f"_cctest{os.getpid()}", f"_ccsbx{os.getpid()}.json", "r.json", "myrepo_cctest12"])
        ok("`suite_pid` reads the pid off the name as a reader holds it — a board file, a window `<name>/t`, a handoff "
           "successor `<name>~next` — and nothing off a real repo, a prefixed name with no pid, or a pid glued to letters",
           [suite_pid(x) for x in ("_cctest123", "_cctest123.json", "_ccsbx123/t", "_cctest123/hx~next", "_cclive.lock",
                                   "myrepo_cctesting", "myrepo_cctest123", "_cctest123abc")] == [123, 123, 123, 123, None, None, None, None]
           and SUITE.search("cc-handoff: _cctest99999999/hx — gone").group(1) == "99999999"
           and SUITE.search("cc-handoff: myrepo_cctest12/hx — real") is None)
        # …and a tripwire on the siblings: none carries a copy of the rule again — no `startswith("_cc…")` and no
        # `_cc[a-z]+` regex of its own outside this file. Two copies read `_cctest` alone for ten days (2026-09-01 →
        # 2026-09-11) and a leaked `_ccsbx<pid>` was a repo to the Home tab and the landing queue while scaffolding
        # to reconcile. Comments are stripped; a docstring that names the shape is not a rule.
        here = os.path.dirname(os.path.realpath(__file__))
        COPY = re.compile(r"""startswith\(\s*["']_cc|_cc\[a-z\]""")
        def copies_in(path):
            lines = open(path, errors="replace").read().split("\n")
            if not (lines[0].startswith("#!") and "python" in lines[0]): return []
            return [i for i, line in enumerate(lines, 1) if COPY.search(line.split("#")[0])]
        copies = [f"{n}:{i}" for n in sorted(os.listdir(here)) if n.startswith("cc") and n != "cc-board" and os.path.isfile(f"{here}/{n}")
                  for i in copies_in(f"{here}/{n}")]
        ok("no sibling tool carries its own copy of the fixture rule — each asks `reals` / `suite_pid` (tripwire)", not copies)
        if copies: print("       " + ", ".join(copies))
        # ── A NEW ROW IS TOLD WHICH LIVE ROW IS ALREADY IN THESE FILES, at the door it comes in by. Every extra
        # row costs its own gates, review read and merge, so two asks in one file that could have been one brief
        # buy a second landing for nothing — and whether they are one concern was a match made from memory, missed
        # exactly when the session had just changed hands. cc-brief does the arithmetic; this OFFERS and never
        # joins, so the row is added either way and a person runs the command or does not.
        jr = os.path.join(th, "jrepo")
        os.makedirs(jr)
        genv = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        def jgit(*g): subprocess.run(["git", "-C", jr, *g], capture_output=True, env=genv)
        subprocess.run(["git", "init", "-q", "-b", "main", jr], capture_output=True)
        for fn in ("shared.txt", "alone.txt"): open(os.path.join(jr, fn), "w").write("base\n")
        jgit("add", "-A"); jgit("commit", "-qm", "base"); jgit("checkout", "-q", "-b", "track/first-row", "main")
        open(os.path.join(jr, "shared.txt"), "a").write("held\n")
        jgit("add", "-A"); jgit("commit", "-qm", "held"); jgit("checkout", "-q", "main")
        run("init", "j", jr, "main")
        run("add", "j", "first-row", "the row already writing it", "GOAL: shared.txt is wrong.")
        run("status", "j", "first-row", "running")
        a = run("add", "j", "second-ask", "a second ask in the same file",
                "GOAL: shared.txt is wrong in one more way.")
        ok("`add` says which LIVE row is already in these files, and how the ask would reach whoever is on it",
           "first-row [running]" in a.stderr and "shared.txt" in a.stderr and "cc j first-row --say" in a.stderr)
        ok("…and the offer is the command that appends the ask to that row's brief — joining is one line",
           "cc board add j first-row 'the row already writing it'" in a.stderr)
        ok("…and the row is added all the same: the box offers here, it never decides",
           a.returncode == 0 and "track 'second-ask' added to j" in a.stdout and "second-ask" in run("json", "j").stdout)
        b = run("add", "j", "on-its-own", "an ask nobody else is in", "GOAL: alone.txt is wrong.")
        ok("an add that overlaps nothing is left completely alone — no offer, no heading, no line",
           "already on this work" not in b.stderr and "track 'on-its-own' added to j" in b.stdout)
        # A MEMBER WORKSPACE'S BOARD IS A LINK: cc-sandbox keeps the file in ~/.cc/members/<h>/board/ and binds that directory
        # as the session's ~/.cc/boards, leaving ~/.cc/boards/<h>.json a symlink so every host path still works. A rename onto
        # the link's own path would replace the LINK with a plain file, and the two sides would hold two boards again.
        os.makedirs(f"{th}/.cc/members/lk/board"); os.symlink(f"{th}/.cc/members/lk/board/lk.json", f"{th}/.cc/boards/lk.json")
        run("init", "lk", "/tmp/lk", "main"); run("add", "lk", "t1", "T")
        ok("a save through a linked board lands in the file the link names, and the link is still a link",
           os.path.islink(f"{th}/.cc/boards/lk.json") and "t1" in json.load(open(f"{th}/.cc/members/lk/board/lk.json"))["tracks"]
           and "lk" in run("boards").stdout.split() and not os.path.exists(f"{th}/.cc/boards/lk.json.tmp"))
        # …AND THE HOST NEVER FOLLOWS A LINK PLANTED IN THAT DIRECTORY (review of #224): the member writes it, so a link
        # in place of the board, a link at the .tmp name, or a link or a pipe in place of the lock is the member's — and
        # each used to be followed: a save renamed the board over any owner-writable file, the lock's open truncated one.
        # Every case: refused (or simply unused), the victim byte for byte, the previous board intact, no hang.
        victim = f"{th}/victim"; open(victim, "w").write("SECRET\n")
        mb = f"{th}/.cc/members/lk/board"
        os.replace(f"{mb}/lk.json", f"{mb}/lk.real"); os.symlink(victim, f"{mb}/lk.json")
        r1, r2, r3 = run("status", "lk", "t1", "running"), run("get", "lk", "t1", "status"), run("list")
        ok("a link planted where the member's board file was is refused by the host's save and its read — exit 1, one line, the victim untouched",
           r1.returncode == 1 and "refused" in r1.stderr and r2.returncode == 1 and "refused" in r2.stderr
           and open(victim).read() == "SECRET\n" and os.readlink(f"{mb}/lk.json") == victim)
        ok("…and `list` skips that board and still lists the others", "r\t" in r3.stdout and "lk.json: unreadable" in r3.stderr)
        os.remove(f"{mb}/lk.json"); os.mkfifo(f"{mb}/lk.json")
        r1, r2 = run("status", "lk", "t1", "running"), run("get", "lk", "t1", "status")
        ok("a pipe planted there is refused the same way, and neither the save nor the read hangs on it",
           r1.returncode == 1 and "refused" in r1.stderr and r2.returncode == 1 and "refused" in r2.stderr)
        os.remove(f"{mb}/lk.json"); os.replace(f"{mb}/lk.real", f"{mb}/lk.json")
        os.symlink(victim, f"{mb}/lk.json.tmp")
        r1 = run("status", "lk", "t1", "running")
        unused = os.path.islink(f"{mb}/lk.json.tmp") and os.readlink(f"{mb}/lk.json.tmp") == victim   # gone = a save renamed it onto the board
        ok("a link planted at the .tmp name is never what the save writes: the save lands, the victim untouched, the link unused",
           r1.returncode == 0 and json.load(open(f"{mb}/lk.json"))["tracks"]["t1"]["status"] == "running"
           and open(victim).read() == "SECRET\n" and unused)
        if os.path.lexists(f"{mb}/lk.json.tmp"): os.remove(f"{mb}/lk.json.tmp")
        os.remove(f"{th}/.cc/boards/lk.lock"); os.symlink(f"{mb}/lk.lock", f"{th}/.cc/boards/lk.lock")   # as board_dir leaves it
        os.symlink(victim, f"{mb}/lk.lock")
        r1 = run("status", "lk", "t1", "queued")
        os.remove(f"{mb}/lk.lock"); os.mkfifo(f"{mb}/lk.lock")
        r2 = run("status", "lk", "t1", "queued")
        ok("a link, then a pipe, in place of the lock is refused — the victim is not truncated, the host does not hang, the board is as it was",
           r1.returncode == 1 and "refused" in r1.stderr and r2.returncode == 1 and "refused" in r2.stderr
           and open(victim).read() == "SECRET\n" and json.load(open(f"{mb}/lk.json"))["tracks"]["t1"]["status"] == "running")
        os.remove(f"{mb}/lk.lock"); open(f"{mb}/lk.lock", "w").close()
        ok("…and with a plain file back at the lock the save goes through the host's link as before",
           run("status", "lk", "t1", "queued").returncode == 0 and json.load(open(f"{mb}/lk.json"))["tracks"]["t1"]["status"] == "queued")
        # …AND THE SAME AT THE HOST'S OWN ENTRY, which is where a WORKER can plant one: ~/.cc/boards is bind-mounted rw
        # inside that sandbox too. `rm r.json; ln -s <the owner's file> r.json` and the host's next save renames a board
        # over it. A link there is followed only to ~/.cc/members/<h>/board/<h>.json, what board_dir makes, and to nothing else.
        for name, why in (("r.json", "board"), ("r.lock", "lock")):
            keep = f"{th}/.cc/boards/{name}.keep"
            if os.path.lexists(f"{th}/.cc/boards/{name}"): os.replace(f"{th}/.cc/boards/{name}", keep)
            os.symlink(victim, f"{th}/.cc/boards/{name}")
            r1, r2 = run("status", "r", "t1", "running"), run("get", "r", "t1", "status")
            os.remove(f"{th}/.cc/boards/{name}")
            if os.path.lexists(keep): os.replace(keep, f"{th}/.cc/boards/{name}")
            ok(f"a link planted at the host's own {why} entry — what a sandboxed worker can write — is refused before "
               f"anything opens it, and the file it aimed at is byte for byte what it was",
               r1.returncode == 1 and "refused" in r1.stderr and "Traceback" not in r1.stderr
               and (why == "lock" or (r2.returncode == 1 and "refused" in r2.stderr))
               and open(victim).read() == "SECRET\n")
        ok("…and the board that link stood in front of is untouched and still saves",
           run("status", "r", "t1", "queued").returncode == 0
           and json.load(open(f"{th}/.cc/boards/r.json"))["tracks"]["t1"]["status"] == "queued")
        # BELT AND BRACES (the second pass of that review): a board file has ONE name — link(2) across two binds is EXDEV
        # today — and a DIRECTORY made at the lock's name or the board's is one line, not a traceback.
        os.link(f"{mb}/lk.json", f"{mb}/lk.two")
        r1, r2 = run("status", "lk", "t1", "running"), run("get", "lk", "t1", "status")
        os.remove(f"{mb}/lk.two")
        ok("a board file with a second name (a hard link) is refused, save and read alike",
           r1.returncode == 1 and "refused" in r1.stderr and r2.returncode == 1 and "refused" in r2.stderr)
        os.remove(f"{mb}/lk.lock"); os.mkdir(f"{mb}/lk.lock")
        r1 = run("status", "lk", "t1", "running")
        os.rmdir(f"{mb}/lk.lock"); open(f"{mb}/lk.lock", "w").close()
        os.replace(f"{mb}/lk.json", f"{mb}/lk.real"); os.mkdir(f"{mb}/lk.json")
        r2, r3 = run("status", "lk", "t1", "running"), run("get", "lk", "t1", "status")
        os.rmdir(f"{mb}/lk.json"); os.replace(f"{mb}/lk.real", f"{mb}/lk.json")
        ok("a directory made at the lock's name, or at the board's, is refused in one line — no traceback",
           all(r.returncode == 1 and "refused" in r.stderr and "Traceback" not in r.stderr for r in (r1, r2, r3)))
        # NO SIBLING OPENS A BOARD ITSELF: the host readers import `read` (the way cc-time is imported), cc-audit runs
        # `cc-board json`. A tripwire, not a proof, in two passes per function: every name bound to a board path (BOARDS,
        # bpath(), a string under .cc/boards — by `x = …`, `for x in …`, `with … as x`) is collected, and a line that reads
        # (open, json.load, read_text/read_bytes, shutil.copy*, a cat/cp/jq call) with such a name as an argument, or with
        # the path spelled out, is flagged. A line that writes ("w") is a suite laying a fixture in its own directory. A
        # shell file gets the one-line rule: cat/cp/jq with the board path in the same command.
        here = os.path.dirname(os.path.realpath(__file__))
        MARK = re.compile(r'\bBOARDS\b|\.cc/boards|\bbpath\(')
        VERB = re.compile(r'\b(open|load|loads|read_text|read_bytes|copy|copy2|copyfile|cat|cp|jq)\b')
        def plain_opens(path):
            out, bound = [], {}
            lines = open(path, errors="replace").read().split("\n")
            py = lines[0].startswith("#!") and "python" in lines[0]
            for i, line in enumerate(lines, 1):
                code = line.split("#")[0].rstrip()
                if not code.strip(): continue
                indent = len(code) - len(code.lstrip())
                if re.match(r'\s*def\s', code): bound = {k: v for k, v in bound.items() if v <= indent}   # a new function: its predecessor's names are gone
                write = '"w"' in code or "'w'" in code
                marked = bool(MARK.search(code))
                if not py:
                    if not write and re.search(r'\b(cat|cp|jq)\b[^|;&]*(\.cc/boards|\bBOARDS\b)', code): out.append(f"{os.path.basename(path)}:{i}")
                    continue
                if marked and not write:   # pass one: a name bound to a board path
                    m = (re.match(r'\s*for\s+(\w+)\s+in\b', code) or re.match(r'\s*with\b.*\bas\s+(\w+)\s*:', code)
                         or re.match(r'\s*([\w\s,]+?)\s*=[^=]', code))
                    for nm in (m.group(1).split(",") if m else []): bound[nm.strip()] = indent
                if write or not VERB.search(code): continue
                if marked or any(re.search(r'[(,\[]\s*' + re.escape(nm) + r'\s*[,)\]]', code) for nm in bound if nm):   # pass two
                    out.append(f"{os.path.basename(path)}:{i}")
            return out
        bad = [x for n in sorted(os.listdir(here)) if n.startswith("cc") and n != "cc-board" and os.path.isfile(f"{here}/{n}")
               for x in plain_opens(f"{here}/{n}")]
        ok("no sibling tool opens ~/.cc/boards/<repo>.json itself — each reads through `read` or `cc-board json` (tripwire)", not bad)
        if bad: print("       " + ", ".join(bad))
        # …AND THAT TRIPWIRE ONLY GUARDS ANYTHING IF IT RUNS. A suite runs a tool's selfcheck when that tool or
        # something that invokes it changed (tests/green.sh), and the case above guards code that is not this
        # file's: scoped that way it slept through the change that broke it. green.sh answers `want_selfcheck` for
        # cc-board whatever changed — pinned here in both halves, the rule and the two gates that ask it, because
        # the rule on its own is dead the moment a suite goes back to asking `want`.
        tests = os.path.normpath(f"{here}/../tests")
        def src(name):
            try: return open(f"{tests}/{name}").read().split("\n")
            except OSError: return []
        sb = f"{th}/scopebin"; os.makedirs(sb, exist_ok=True)
        for nm in ("cc-board", "cc-leaf"): open(f"{sb}/{nm}", "w").write("#!/bin/sh\n")
        def asks(fn):   # a diff of one tool that cc-board neither is nor calls
            r = subprocess.run(["bash", "-c", '. "$1" || exit 1; CC_LAND_CHANGED=core/bin/cc-leaf land_scope "$2"; '
                                f'{fn} cc-board && echo yes || echo no', "_", f"{tests}/green.sh", sb],
                               capture_output=True, text=True)
            return r.stdout.strip()
        chk_sh, self_sh = src("check.sh"), src("selftest.sh")
        loop = [l for l in chk_sh if re.match(r'\s*want_selfcheck "\$c"', l)]           # check.sh's selfcheck loop…
        listed = [l for l in chk_sh if re.match(r'\s*for c in cc-', l) and " cc-board " in l]   # …over a list holding cc-board
        gate = [l for l in self_sh if re.match(r'\s*want_selfcheck "\$t"', l)]          # selftest.sh's chk()
        at = self_sh.index("chk cc-board") if "chk cc-board" in self_sh else -1
        stz = next((self_sh[k] for k in range(at, -1, -1) if re.match(r'(if )?stanza "', self_sh[k])), "") if at >= 0 else ""
        ok("…and a landing that changes any tool under bin/ runs these cases: green.sh says yes for cc-board "
           "whatever changed, where the invoke graph alone says no, and both suites gate this selfcheck on that",
           asks("want_selfcheck") == "yes" and asks("want") == "no"
           and len(loop) == 1 and len(listed) == 1 and len(gate) == 1 and stz.rstrip().endswith("always"))
        # A FAILED RENAME LEAVES THE PREVIOUS BOARD (review-156d). The in-place fallback exists for the bind-mounted board
        # inside a member boundary — rename over a mount point is EBUSY — and for nothing else: a full or read-only disk used
        # to truncate the live board to zero bytes on the way to failing. os.replace is stood in for; the board dir is this
        # run's own; _save is called in-process, the way every writer calls it.
        real_boards, real_replace, real_wait = BOARDS, os.replace, LOCK_WAIT
        BOARDS = f"{th}/.cc/boards"
        try:
            # A LOCK HELD FROM INSIDE IS A MEMBER-CONTROLLED HANG: the lock file is in the member's directory. The host
            # takes it non-blocking, waits LOCK_WAIT, then refuses in one line — it never sits on a member's flock for good.
            LOCK_WAIT = 0.5
            holder = open(f"{mb}/lk.lock", "w"); fcntl.flock(holder, fcntl.LOCK_EX)
            def take():
                with Lock("lk"): return "taken"
            t0 = time.monotonic(); got = bounded(take, 5)   # a lock that blocks (the old LOCK_EX) sits here: the guard fails the case, the suite goes on
            waited = time.monotonic() - t0; holder.close()
            ok("a board lock somebody else holds is waited for, briefly, then refused in one line — not a hang — and taken once it is free",
               isinstance(got, Refused) and 0.4 < waited < 5 and bounded(take, 5) == "taken")
            before = open(f"{th}/.cc/boards/r.json").read()
            def failing(code):
                def rep(a, b): raise OSError(code, os.strerror(code))
                return rep
            for code in (errno.ENOSPC, errno.EROFS, errno.EIO):
                os.replace = failing(code)
                try: _save("r", {"repo": "r", "tracks": {}}); raised = False
                except OSError as e: raised = e.errno == code
                ok(f"a rename that fails with {errno.errorcode[code]} (full or read-only target) re-raises and leaves the previous board intact",
                   raised and open(f"{th}/.cc/boards/r.json").read() == before and not glob.glob(f"{th}/.cc/boards/r.json.*tmp"))
            os.replace = failing(errno.EBUSY)
            _save("r", {"repo": "r", "tracks": {"z": {"status": "queued", "title": "in place"}}})
            ok("…while the mount point's EBUSY writes in place, whole, and clears the .tmp",
               json.load(open(f"{th}/.cc/boards/r.json"))["tracks"] == {"z": {"status": "queued", "title": "in place"}}
               and not glob.glob(f"{th}/.cc/boards/r.json.*tmp"))
        finally:
            BOARDS, os.replace, LOCK_WAIT = real_boards, real_replace, real_wait
        # A WORKER THE HUB PLACED ON A PEER HOST (CC_PEER_SPOOL set): its note lands on the board here AND goes to the
        # spool for the hub; a set or an add never does, and without the variable nothing is spooled
        os.makedirs(f"{th}/dev/pr", exist_ok=True); run("init", "pr", f"{th}/dev/pr"); run("add", "pr", "w", "a row", "GOAL: x.")
        sp = f"{th}/peer-spool"
        run("note", "pr", "w", "half way", env={"CC_PEER_SPOOL": sp})
        run("set", "pr", "w", "agent", "me", env={"CC_PEER_SPOOL": sp})
        run("note", "pr", "w", "not placed")
        got = [json.load(open(f"{sp}/{x}")) for x in sorted(os.listdir(sp))] if os.path.isdir(sp) else []
        ok("peer: a placed worker's note is spooled for the hub, once, and its set is not",
           [(g["tool"], g["argv"]) for g in got] == [("board", ["note", "pr", "w", "half way"])])
        ok("…and the note is on this host's own row too", "half way" in run("get", "pr", "w", "notes").stdout
           or "half way" in open(f"{th}/.cc/boards/pr.json").read())
        # INDEX-AT-WRITE: a note is in the knowledge base's index the moment `note` returns — `cc-lib ask` finds it with its
        # kind and ids and had nothing to re-read itself (re-read absent from COVERAGE: the hook did it, not the ask).
        # Its own HOME, its own board, and the baseline pass first so the only stale source a lazy ask could catch
        # up on is the note.
        lib = os.path.join(os.path.dirname(os.path.realpath(__file__)), "cc-lib")
        th2 = tempfile.mkdtemp(prefix="ccboard-sc-lib-"); LENV = {**os.environ, "HOME": th2}
        try:
            def cli(*args): return subprocess.run([sys.executable, os.path.realpath(__file__), *args], env=LENV, text=True, capture_output=True, timeout=120)
            def libq(*args): return subprocess.run([lib, *args], env=LENV, text=True, capture_output=True, timeout=60).stdout
            os.makedirs(f"{th2}/dev/r"); cli("init", "r", f"{th2}/dev/r"); cli("add", "r", "st", "a row", "GOAL: something.")
            libq("index")
            cli("note", "r", "st", "zebrafish handover: the unit is active and the owner has used it")
            o = libq("ask", "--object", "r/st", "--need", "history", "zebrafish handover")
            ok("cc-board note is indexed as it is written: cc-lib ask finds the note as kind note under its row, with nothing left for the ask to re-read",
               "zebrafish handover" in o and "note" in o and "st" in o and "OUTCOME answered" in o and "re-read" not in o)
        finally:
            shutil.rmtree(th2, ignore_errors=True)
    finally:
        shutil.rmtree(th, ignore_errors=True)
    print(f"cc-board selfcheck: {n} failed")
    return 1 if n else 0
