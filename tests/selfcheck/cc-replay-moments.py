# cc-replay-moments's selfcheck: the cases behind `cc-replay-moments selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-replay-moments execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    fails, passed = [], [0]

    def ok(name, cond):
        if cond:
            passed[0] += 1
        else:
            fails.append(name)
            print(f"FAIL {name}")

    root = tempfile.mkdtemp(prefix="cc-replay-moments-selfcheck-")
    # the box's own stall log and held-out files never reach a case: the nudge cases run with no stall log at all, and
    # an empty held-out dir proves a run with no stall moments needs no salt
    os.environ["CC_REPLAY_STALLS"] = os.path.join(root, "no-stall.log")
    os.environ["CC_REPLAY_HELDOUT_DIR"] = os.path.join(root, "no-heldout")
    try:
        snaps, slack = os.path.join(root, "snaps"), os.path.join(root, "slack")
        day = os.path.join(snaps, "2026-01-05")
        os.makedirs(day)
        os.makedirs(os.path.join(slack, "archive", "p", "CA"))
        os.symlink("2026-01-05", os.path.join(snaps, "latest"))

        def w(path, rows):
            with open(path, "w") as fh:
                for r in rows:
                    fh.write((r if isinstance(r, str) else json.dumps(r)) + "\n")

        def own(ts, at, text, chat="CA", th=None):
            return {"ts": ts, "thread_ts": th or ts, "chat": chat, "role": "owner", "text": text, "at": at}
        # archive: n1 in a thread with a box post in it; n2 top-level (falls back to the chat's last post); n3 in a
        # chat with no box post at all; c1 an unlabelled message (control); c9 outside the labels' span
        w(os.path.join(slack, "archive", "p", "CA", "2026-01.jsonl"), [
            own("100.1", "2026-01-04T10:00:00Z", "where are we", th="90.0"),
            own("200.1", "2026-01-04T12:00:00Z", "status?"),
            own("300.1", "2026-01-04T13:00:00Z", "hello?", chat="CB"),
            own("250.1", "2026-01-04T12:20:00Z", "thanks"),
            own("900.1", "2026-01-06T00:00:00Z", "later"),
            {"ts": "260.1", "chat": "CA", "role": "member", "text": "not the owner", "at": "2026-01-04T12:40:00Z"}])
        w(os.path.join(slack, "outbox.log"), [
            "2026-01-04T09:00:00Z\tpost\tCA\t90.0\tIt's queued to land, no thumbs needed.",
            "2026-01-04T09:30:00Z\tpost\tCA\t\ta top-level post",
            "2026-01-04T09:59:00Z\treact\tCA\t90.0\teyes",
            "2026-01-04T09:59:30Z\tpost-failed\tCA\t90.0\tnever reached anyone",
            "2026-01-04T11:50:00Z\tpost\tCA\t\tI've started building it.",
            "2026-01-04T12:29:00Z\tpost\tCA\t\tDone: it landed."])
        # snapshot: n4 carries its own prev_box (the archive does not have n4 at all); a failure cluster of n=3 quoting 2
        w(os.path.join(day, "slack.jsonl"), [dict(own("400.1", "2026-01-05T08:00:00Z", "done yet?", chat="CC"),
                                                  prev_box={"at": "2026-01-05T06:00:00Z", "kind": "post",
                                                            "text": "Running now: the fix."}, src="x")])
        w(os.path.join(day, "failures.jsonl"), [{"clusters": ["c-1"], "kind": "notification/false-action-needed",
                                                 "examples": ["the watchdog said land it while it was landing", "again"],
                                                 "n": 3, "last": "2026-01-05T07:00:00Z", "writers": ["w"]}])
        labels = os.path.join(root, "labels.jsonl")
        w(labels, [{"ts": "100.1", "chat": "CA", "class": "landing-chase"},
                   {"ts": "200.1", "chat": "CA", "class": "status-not-pushed"},
                   {"ts": "300.1", "chat": "CB", "class": "message-unseen"},
                   {"ts": "400.1", "chat": "CC", "class": "status-not-pushed"},
                   {"ts": "500.1", "chat": "CA", "class": "status-not-pushed"}])
        before = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)
        ms = extract(labels, snaps, slack)
        by = {m["id"]: m for m in ms}
        n1, n2, n3, n4 = by.get("n:CA:100.1"), by.get("n:CA:200.1"), by.get("n:CB:300.1"), by.get("n:CC:400.1")
        ok("a nudge in a thread takes the thread's last box post, skipping reactions and failed posts",
           n1 and n1["prev_box"]["text"].startswith("It's queued") and n1["gap_s"] == 3600 and n1["in_thread"])
        ok("a top-level nudge takes the chat's last box post before it", n2 and n2["prev_box"]["text"] == "I've started building it."
           and n2["gap_s"] == 600)
        ok("a nudge with no box post before it is kept and counted unreplayable",
           n3 and not n3["replayable"] and n3["why"] == "no box post before it")
        ok("a snapshot's own box post is used first", n4 and n4["src"] == "snapshot" and n4["gap_s"] == 7200)
        ok("a labelled nudge found nowhere is kept, unreplayable",
           by.get("n:CA:500.1", {}).get("replayable") is False and "not in" in by["n:CA:500.1"]["why"])
        ctl = [m for m in ms if m["source"] == "control"]
        ok("control is the owner's unlabelled messages inside the labels' span only (no member, nothing after)",
           [m["id"] for m in ctl] == ["c:CA:250.1"] and ctl[0]["prev_box"]["text"] == "I've started building it.")
        fl = [m for m in ms if m["source"] == "failure"]
        ok("a failure cluster of n=3 quoting 2 examples is 2 replayable moments and 1 unreplayable",
           len(fl) == 3 and sum(m["replayable"] for m in fl) == 2 and fl[0]["class"] == "notification/false-action-needed")

        cand = os.path.join(root, "new.py")
        with open(cand, "w") as fh:
            fh.write("import re\n"
                     "def judge(m):\n"
                     "    if m['source'] == 'failure':\n"
                     "        return 'flagged' if 'landing' in m['text'] else None\n"
                     "    t = (m.get('prev_box') or {}).get('text', '')\n"
                     "    return ('status', 1800) if re.search(r'queued|started|running', t, re.I) else 'pass'\n")
        old = os.path.join(root, "old.py")
        with open(old, "w") as fh:
            fh.write("def judge(m):\n    return 'status' if 'queued' in ((m.get('prev_box') or {}).get('text') or '') else None\n")
        exe = os.path.join(root, "new.sh")
        with open(exe, "w") as fh:
            fh.write("#!/usr/bin/env python3\nimport json, re, sys\nm = json.load(sys.stdin)\n"
                     "t = (m.get('prev_box') or {}).get('text', '') if m['source'] != 'failure' else ''\n"
                     "if m['source'] == 'failure': print('flagged' if 'landing' in m['text'] else 'pass')\n"
                     "elif re.search(r'queued|started|running', t, re.I): print('status 1800')\n"
                     "else: print('pass')\n")
        os.chmod(exe, 0o755)
        rep = score(ms, load_version(old), load_version(cand))

        def row(title, cls, report=None):
            report = report or rep
            sect = report.split(title, 1)[1] if title in report else ""
            for ln in sect.splitlines():
                if ln.startswith(cls + " "):
                    return ln.split()
            return []
        s = row("NUDGES", "status-not-pushed")
        # status-not-pushed: n2 (started, 10 min gap < 30 min: late), n4 (running, 2 h gap: status), 500.1 unreplayable
        ok("per class: total, replayable, unreplayable, old, new, gained, lost, late",
           s[1:9] == ["3", "2", "1", "0", "1", "1", "0", "1"])
        lc = row("NUDGES", "landing-chase")
        ok("a moment both versions prevent is neither gained nor lost", lc[1:8] == ["1", "1", "0", "1", "1", "0", "0"])
        mu = row("NUDGES", "message-unseen")
        ok("an unreplayable nudge stays in its class's total", mu[1:4] == ["1", "0", "1"])
        fk = row("FAILURES", "notification/false-action-needed")
        ok("failures are scored by kind, unreplayable ones counted", fk[1:6] == ["3", "2", "1", "0", "1"])
        ok("control counts what each version fires on outside the nudges",
           "old fires before 0, new before 1" in rep)
        ok("the unreplayable reasons are listed", "nudge: no box post before it 1" in rep
           and "failure: the snapshot quotes no text for this record 1" in rep)
        ok("an executable version scores the same as the Python one",
           score(ms, load_version(old), load_version(exe)).split("\n", 1)[1] == rep.split("\n", 1)[1])
        dflt = [r.split() for r in score(ms, load_version(None), load_version(cand)).splitlines()]
        ok("--old defaults to never firing: every old column is 0",
           all(r[4] == "0" for r in dflt if len(r) > 8 and r[1].isdigit() and r[0] != "control:")
           and "old=none" in dflt[0][1])
        ok("the same input prints the same bytes", score(ms, load_version(old), load_version(cand)) == rep)
        after = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)
        ok("extract and score write nothing beside the sources", set(after) - set(before) <= {"new.py", "old.py", "new.sh"})

        bad = os.path.join(root, "bad.py")
        with open(bad, "w") as fh:
            fh.write("def judge(m):\n    return 'maybe'\n")
        boom = os.path.join(root, "boom.py")
        with open(boom, "w") as fh:
            fh.write("def judge(m):\n    raise ValueError('no')\n")
        me = os.path.realpath(__file__)
        for name, path, want in (("a verdict outside the list stops the run", bad, "answered 'maybe'"),
                                 ("a judge that raises stops the run and names the moment", boom, "failed on ")):
            p = subprocess.run([sys.executable, me, "score", "--new", path, "--labels", labels, "--snapshots", snaps,
                                "--slack", slack], capture_output=True, text=True)
            ok(name, p.returncode == 1 and want in p.stderr)
        mf = os.path.join(root, "m.jsonl")
        p = subprocess.run([sys.executable, me, "extract", "--labels", labels, "--snapshots", day, "--slack", slack,
                            "--out", mf], capture_output=True, text=True)
        ok("extract writes the moments and says how many replay; a day dir works as --snapshots",
           p.returncode == 0 and "nudge 3 replayable / 5" in p.stdout and len(jsonl(mf)) == len(ms))
        p = subprocess.run([sys.executable, me, "score", "--new", cand, "--old", old, "--moments", mf],
                           capture_output=True, text=True)
        ok("score over a written moments file prints the same table", p.returncode == 0 and p.stdout.strip() == rep)
        p = subprocess.run([sys.executable, me, "score", "--labels", labels], capture_output=True, text=True)
        ok("score with no --new is refused with the usage", p.returncode == 2 and "usage" in p.stderr)
        p = subprocess.run([sys.executable, me, "extract", "--labels", os.path.join(root, "none.jsonl"), "--out", mf],
                           capture_output=True, text=True)
        ok("an empty or missing labels file is refused, not scored as zero", p.returncode == 2 and "no labelled" in p.stderr)

        # STALLS, on their own fixture: a stall log and two snapshot days whose board rows say how each stall ended
        sroot = os.path.join(root, "stall")
        sd1, sd2 = os.path.join(sroot, "snaps", "2026-01-05"), os.path.join(sroot, "snaps", "2026-01-06")
        os.makedirs(sd1)
        os.makedirs(sd2)
        slog = os.path.join(sroot, "stall.log")
        w(slog, ["2026-01-05T10:04:00Z\tw1\tdialog\traised r/raised-stall-w1-dialog-01051004\ta dialog has stood 4 min",
                 "2026-01-05T12:03:00Z\tw2\tdialog\traised r/raised-stall-w2-dialog-01051203\ta dialog has stood 3 min",
                 "2026-01-05T13:04:00Z\tw3\tdialog\traised r/raised-stall-w3-dialog-01051304\ta dialog has stood 4 min",
                 "2026-01-05T14:00:00Z\tw4\tdialog\tboard refused r/raised-stall-w4-dialog-01051400 (try 1)",
                 "2026-01-05T14:02:00Z\tw4\tdialog\traised r/raised-stall-w4-dialog-01051402\ta dialog has stood 6 min",
                 "2026-01-05T15:00:00Z\tw5\tdialog\tboard refused r/raised-stall-w5-dialog-01051500 (try 1)",
                 "2026-01-05T15:02:00Z\tw5\tdialog\tboard refused r/raised-stall-w5-dialog-01051500 (try 2)",
                 "2026-01-05T16:00:00Z\tw6\tdev-channels\tpressed '1'",
                 "not a line"])
        w(os.path.join(sd1, "board.jsonl"), [
            {"repo": "r", "track": "raised-stall-w1-dialog-01051004", "statuses": [],
             "notes": ["01-05T10:04 added: w1 is stuck: a dialog has stood 4 min"]},
            {"repo": "r", "track": "raised-stall-w2-dialog-01051203", "statuses": ["01-05T12:30 running", "01-05T12:40 done"],
             "notes": ["01-05T12:35 Dropped: a duplicate"]},
            {"repo": "r", "track": "raised-stall-w4-dialog-01051402", "statuses": ["01-05T14:56 merged"], "notes": []}])
        w(os.path.join(sd2, "board.jsonl"), [
            {"repo": "r", "track": "raised-stall-w1-dialog-01051004", "statuses": [],
             "notes": ["01-06T10:00 Closed in triage: stale"]}])
        sm = extract(None, os.path.join(sroot, "snaps"), slack, slog)
        sb = {m["id"]: m for m in sm}
        s1, s2 = sb.get("s:r/raised-stall-w1-dialog-01051004", {}), sb.get("s:r/raised-stall-w2-dialog-01051203", {})
        s4 = sb.get("s:r/raised-stall-w4-dialog-01051402", {})
        ok("a stall begins 'stood N min' before its log line and ends at a close note on a later snapshot day",
           s1.get("at") == "2026-01-05T10:00:00Z" and s1.get("stood_s") == 86400 and s1.get("gap_s") == 86400
           and s1.get("ended_by") == "closed note" and s1.get("replayable") is True)
        ok("a stall ends at the earliest sign on its row: a Dropped note before done, never a running status",
           s2.get("stood_s") == 2100 and s2.get("ended_by") == "dropped note")
        ok("a refused row raised again on a later pass is one stall, the raised one",
           s4.get("stood_s") == 3600 and s4.get("ended_by") == "merged"
           and "s:r/raised-stall-w4-dialog-01051400" not in sb)
        un = {m["id"]: m.get("why") for m in sm if not m["replayable"]}
        ok("a stall with no recorded end, a row the board never took and a sweep's press are kept, unreplayable",
           un == {"s:r/raised-stall-w3-dialog-01051304": "no board snapshot records how its row ended",
                  "s:r/raised-stall-w5-dialog-01051500": "the board refused its row and it was never raised",
                  "s:w6:dev-channels:2026-01-05T16:00:00Z": "the sweep pressed it; the log does not say how long it stood"})
        ok("a stall log with no labels makes only stall moments", len(sm) == 6 and {m["source"] for m in sm} == {"stall"})

        snew, sold = os.path.join(sroot, "new.py"), os.path.join(sroot, "old.py")
        with open(snew, "w") as fh:     # clears a dialog 30 min in, 50 min in for w2 (whose stall stood 35): late there
            fh.write("def judge(m):\n"
                     "    if m['source'] != 'stall' or m['class'] != 'dialog':\n        return 'pass'\n"
                     "    return ('flagged', 3000 if m['window'] == 'w2' else 1800)\n")
        with open(sold, "w") as fh:     # fires on w4 only, with no after_s: it saves the whole stand
            fh.write("def judge(m):\n    return 'flagged' if m.get('window') == 'w4' else 'pass'\n")
        srep = score(sm, load_version(sold), load_version(snew))
        d = row("STALLS", "dialog", srep)
        # dialog: 5 stalls, 3 replay (86400 + 2100 + 3600 s = 1535 min); old cuts w4's 60; new cuts 1410 + 30, w2 late
        ok("stalls are scored per kind with the minutes they stood and the minutes each version cuts",
           d[1:12] == ["5", "3", "2", "1", "2", "1", "0", "1", "1535", "60", "1440"])
        dc = row("STALLS", "dev-channels", srep)
        ok("a kind with only unreplayable stalls stays in the table at zero minutes",
           dc[1:4] == ["1", "0", "1"] and dc[9:12] == ["0", "0", "0"])
        ok("the stall unreplayable reasons are listed", "stall: no board snapshot records how its row ended 1" in srep)
        ok("stall scoring prints the same bytes twice", score(sm, load_version(sold), load_version(snew)) == srep)

        # HELD OUT: one in four by the salted hash, and everything raised from the stamp on
        salt = "0123456789abcdef0123456789abcdef"
        many = [{"id": f"s:r/raised-stall-x-{i}", "source": "stall", "raised_at": "2026-01-05T10:00:00Z"} for i in range(200)]
        mix = many + [{"id": "n:CA:1", "source": "nudge"}, {"id": "f:x:0", "source": "failure"}]
        kept, nh = split_held(mix, False, (salt, "lifted"))
        only, nh2 = split_held(mix, True, (salt, "lifted"))
        ok("about one stall moment in four is held out, and default and --held-out split them exactly",
           30 <= nh <= 70 and nh == nh2 == len(only) and len(kept) + len(only) == len(mix)
           and not {m["id"] for m in kept} & {m["id"] for m in only})
        ok("the default keeps the nudges and failures; --held-out scores the held-out stalls and nothing else",
           {"n:CA:1", "f:x:0"} <= {m["id"] for m in kept} and {m["source"] for m in only} == {"stall"})
        ok("the split is stable for one salt and moves with another",
           split_held(mix, True, (salt, "lifted"))[0] == only
           and split_held(mix, True, ("f" * 32, "lifted"))[0] != only)
        free = next(m for m in many if not is_held_out(m, salt, "lifted"))
        edge = dict(free, raised_at="2026-01-05T10:04:59Z")
        ok("a stall raised in the stamp's own minute or after is held out; one the minute before is not",
           is_held_out(edge, salt, "2026-01-05T10:04Z") and is_held_out(edge, salt, "2026-01-05T09:00Z")
           and not is_held_out(edge, salt, "2026-01-05T10:05Z") and not is_held_out(edge, salt, "lifted"))
        ok("nudges, failures and controls are never held out",
           not any(is_held_out(m, salt, "2000-01-01T00:00Z") for m in mix if m["source"] != "stall"))

        hd = os.path.join(sroot, "heldout")
        os.makedirs(hd)
        w(os.path.join(hd, "replay-heldout.salt"), [salt])
        w(os.path.join(hd, "replay-heldout.from"), ["2026-01-05T15:30Z"])
        env = dict(os.environ, CC_REPLAY_HELDOUT_DIR=hd)
        want = sum(is_held_out(m, salt, "2026-01-05T15:30Z") for m in sm)
        base = [sys.executable, me, "score", "--new", snew, "--stalls", slog, "--snapshots", os.path.join(sroot, "snaps")]
        p = subprocess.run(base, capture_output=True, text=True)
        ok("stall moments with no held-out files are refused, not scored in full",
           p.returncode == 2 and "held-out files" in p.stderr)
        os.makedirs(os.path.join(sroot, "bad"))
        w(os.path.join(sroot, "bad", "replay-heldout.salt"), ["short"])
        w(os.path.join(sroot, "bad", "replay-heldout.from"), ["lifted"])
        p = subprocess.run(base, capture_output=True, text=True, env=dict(os.environ, CC_REPLAY_HELDOUT_DIR=os.path.join(sroot, "bad")))
        ok("a salt that is not 32 hex characters is refused", p.returncode == 2 and "32 hex" in p.stderr)
        p = subprocess.run(base, capture_output=True, text=True, env=env)
        ok("score leaves the held-out stalls out and says how many (the 16:00 press is past the stamp)",
           p.returncode == 0 and f"held out: {want} stall moments left out" in p.stdout and want >= 1
           and is_held_out(sb["s:w6:dev-channels:2026-01-05T16:00:00Z"], salt, "2026-01-05T15:30Z"))
        p = subprocess.run(base + ["--held-out", "--labels", labels, "--slack", slack], capture_output=True, text=True, env=env)
        ok("score --held-out scores only the held-out stalls: no nudges, no control",
           p.returncode == 0 and f"scored only the {want} held-out" in p.stdout and "NUDGES" not in p.stdout
           and "control: 0 " in p.stdout)
        allm = os.path.join(sroot, "all.jsonl")
        w(allm, [json.dumps(dict(m, held_out=False), sort_keys=True) for m in sm])
        p = subprocess.run([sys.executable, me, "score", "--new", snew, "--moments", allm], capture_output=True, text=True,
                           env=env)
        ok("a moments file cannot unhold a moment: the split is made again from the ids",
           p.returncode == 0 and f"held out: {want} stall moments left out" in p.stdout)
        p = subprocess.run([sys.executable, me, "extract", "--stalls", slog, "--snapshots", os.path.join(sroot, "snaps"),
                            "--out", os.path.join(sroot, "x.jsonl")], capture_output=True, text=True, env=env)
        ok("extract writes no held-out stall and says how many it left out",
           p.returncode == 0 and f"{want} held-out stall moments left out" in p.stdout
           and len(jsonl(os.path.join(sroot, "x.jsonl"))) == len(sm) - want)

        # the example candidates shipped beside the tests, when this file sits in its tree
        ex = os.path.join(os.path.dirname(os.path.dirname(me)), "tests", "replay-moments")
        sp, lw = os.path.join(ex, "status-push-45m.py"), os.path.join(ex, "landing-wait-4h.py")
        if os.path.isfile(sp) and os.path.isfile(lw):
            _, spj = load_version(sp)
            _, lwj = load_version(lw)

            def mk(text, gap):
                return {"id": "x", "source": "nudge", "prev_box": {"text": text}, "gap_s": gap}
            q = "It's queued to land, no thumbs needed."
            ok("status-push fires 45 min after an in-flight post, and is late before that",
               verdict(spj, mk(q, 3000), "sp") == "status" and verdict(spj, mk(q, 600), "sp") == "late")
            ok("status-push stays quiet after a post that says the work is done or asks a question",
               verdict(spj, mk("Done: it landed.", 9000), "sp") == "pass"
               and verdict(spj, mk("Decision needed: which one? It is queued.", 9000), "sp") == "pass")
            ok("landing-wait fires only on a queued-to-land post, four hours on",
               verdict(lwj, mk(q, 15000), "lw") == "flagged" and verdict(lwj, mk(q, 3000), "lw") == "late"
               and verdict(lwj, mk("I've started building it.", 15000), "lw") == "pass")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"cc-replay-moments selfcheck: {passed[0]} passed, {len(fails)} failed")
    return 1 if fails else 0
