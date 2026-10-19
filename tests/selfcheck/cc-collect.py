# cc-collect's selfcheck: the cases behind `cc-collect selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-collect execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    results = []

    def case(label, ok):
        results.append(bool(ok))
        print(f"  {'ok' if ok else 'FAIL'}  {label}")

    real_home, homes = os.environ.get("HOME"), []
    W = Window(datetime(2026, 1, 10, tzinfo=timezone.utc), datetime(2026, 1, 11, tzinfo=timezone.utc))
    IN, OUT = "2026-01-10T12:00:00Z", "2026-01-09T12:00:00Z"

    def fx(files):
        """A fresh HOME holding only `files` (path under ~/.cc -> text), and a board for repo r so r is a known repo."""
        h = tempfile.mkdtemp(prefix="cc-collect-sc.")
        homes.append(h)
        os.environ["HOME"] = h
        files = {"boards/r.json": json.dumps({"repo": "r", "log": []}), **files}
        for rel, text in files.items():
            p = home(rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(text)
        return h

    def run(files):
        h = fx(files)
        out = os.path.join(h, "snap")
        idx = collect(W, out)
        got = {n: list(jlines(os.path.join(out, f"{n}.jsonl"))) for n, _ in SOURCES}
        return h, idx, got

    def arch(*rows):
        return "".join(json.dumps(r) + "\n" for r in rows)

    try:
        # slack: owner and member kept, a bot and an out-of-window message dropped
        _, idx, got = run({"slack/archive/r/C1/2026-01.jsonl": arch(
            {"ts": "1.1", "thread_ts": "1.1", "chat": "C1", "role": "owner", "target": "r", "text": "status?", "at": IN},
            {"ts": "1.2", "thread_ts": "1.2", "chat": "C1", "role": "member", "target": "r", "text": "hi", "at": IN},
            {"ts": "1.3", "thread_ts": "1.3", "chat": "C1", "role": "bot", "target": "r", "text": "x", "at": IN},
            {"ts": "0.9", "thread_ts": "0.9", "chat": "C1", "role": "owner", "target": "r", "text": "old", "at": OUT})})
        case("slack keeps owner and member messages in the window, drops a bot's and an older one",
             [r["text"] for r in got["slack"]] == ["status?", "hi"] and got["slack"][0]["repo"] == "r"
             and idx["per_repo"]["r"] == {"slack_owner": 1, "slack_member": 1})

        # the window's edges: its first second is in, its last is not
        _, _, got = run({"slack/outbox.log": "".join(f"{t}\tpost\tC1\t\t{t}\n" for t in (
            "2026-01-09T23:59:59Z", "2026-01-10T00:00:00Z", "2026-01-10T23:59:59Z", "2026-01-11T00:00:00Z"))})
        case("a window holds its first second and not the second it ends on",
             [r["text"] for r in got["outbox"]] == ["2026-01-10T00:00:00Z", "2026-01-10T23:59:59Z"])

        # prev_box: same thread first, then same chat; reactions and failed posts never count
        _, _, got = run({
            "slack/archive/r/C1/2026-01.jsonl": arch(
                {"ts": "5.0", "thread_ts": "4.0", "chat": "C1", "role": "owner", "target": "r", "text": "in thread", "at": IN},
                {"ts": "6.0", "thread_ts": "6.0", "chat": "C1", "role": "owner", "target": "r", "text": "top", "at": "2026-01-10T13:00:00Z"}),
            "slack/outbox.log": "".join("\t".join(r) + "\n" for r in [
                ("2026-01-10T11:00:00Z", "post", "C1", "4.0", "thread post"),
                ("2026-01-10T11:30:00Z", "post", "C1", "", "channel post"),
                ("2026-01-10T11:40:00Z", "react", "C1", "4.0", "eyes"),
                ("2026-01-10T11:50:00Z", "post-failed", "C1", "4.0", "lost"),
                ("2026-01-10T13:30:00Z", "post", "C1", "", "later")])})
        pb = {r["text"]: (r["prev_box"] or {}).get("text") for r in got["slack"]}
        case("prev_box is the box's last post in the same thread, else the chat; react and post-failed skipped",
             pb == {"in thread": "thread post", "top": "channel post"})
        case("outbox lists posts and failed posts but never a reaction",
             [r["text"] for r in got["outbox"]] == ["thread post", "channel post", "lost", "later"])

        # outbox: reactions counted in the index, not listed; an older post dropped
        _, idx, got = run({"slack/outbox.log": f"{IN}\treact\tC1\t\teyes\n{IN}\tpost\tC1\t\tnow\n{OUT}\tpost\tC1\t\tthen\n"})
        case("outbox counts a reaction in index.json and drops a post before the window",
             [r["text"] for r in got["outbox"]] == ["now"] and idx["sources"]["outbox"]["reactions"] == 1)

        # landings: folded per PR, a repo with no board dropped
        q = "".join(f"{t}\t{e}\n" for t, e in [
            ("2026-01-10T10:00:00Z", "queued r#7 who=x"), ("2026-01-10T10:01:00Z", "stage r#7 checking"),
            ("2026-01-10T10:02:00Z", "stage r#7 checking"), ("2026-01-10T10:03:00Z", "stage r#7 review"),
            ("2026-01-10T10:04:00Z", "recorded r#7 verdict=LAND by=y"), ("2026-01-10T10:05:00Z", "done r#7 rc=0"),
            ("2026-01-10T10:06:00Z", "reverted demo#7 sha=1"), ("2026-01-10T10:07:00Z", "removed 2 scratch roots"),
            (OUT, "queued r#6 who=x")])
        _, idx, got = run({"state/land/queue.log": q})
        L = got["landings"]
        case("landings fold to one row per PR with stages, verdicts and the last event; no-board and older lines dropped",
             len(L) == 1 and L[0]["pr"] == "r#7" and L[0]["stages"] == ["checking", "review"] and L[0]["verdicts"] == ["LAND"]
             and L[0]["last_event"] == "done rc=0" and L[0]["events"]["stage"] == 3
             and idx["sources"]["landings"]["dropped_no_board"] == 1 and idx["sources"]["landings"]["box_events"] == {"removed": 1})

        # board log
        _, idx, got = run({"boards/r.json": json.dumps({"repo": "r", "log": [
            {"ts": OUT, "track": "t", "msg": "status -> queued"}, {"ts": IN, "track": "t", "msg": "status -> running"},
            {"ts": IN, "track": "t", "msg": "note one"}, {"ts": IN, "track": "t", "msg": "note two"},
            {"ts": IN, "track": "t", "msg": "note three"}, {"ts": IN, "track": "gone", "msg": "removed"}]}),
            "boards/_scratch.json": json.dumps({"repo": "_scratch", "log": [{"ts": IN, "track": "x", "msg": "status -> running"}]})})
        B = got["board"]
        case("board folds a track's log in the window to its statuses and last two notes; a removal alone, an older "
             "entry and a scratch board are left out",
             len(B) == 1 and B[0]["track"] == "t" and B[0]["statuses"] == ["01-10T12:00 running"] and B[0]["n"] == 4
             and [n[12:] for n in B[0]["notes"]] == ["note two", "note three"] and idx["sources"]["board"]["removed_only"] == 1)
        long = [{"ts": IN, "track": "w", "msg": f"status -> {w}"} for w in
                ("queued", "running", "review", "running", "waiting", "running", "review", "running", "review", "merged")]
        _, _, got = run({"boards/r.json": json.dumps({"repo": "r", "tracks": {"a": {"goal": "G1"}, "n": {"goal": "G2"}}, "log": [
            {"ts": IN, "track": "a", "msg": "added: a row"}, {"ts": IN, "track": "n", "msg": "added the fix note"}] + long})})
        B = {r["track"]: r for r in got["board"]}
        case("cc-board's `added: ` line marks a row added and its board `goal` comes along; a note that merely starts "
             "with the word does not count as added",
             B["a"].get("added") is True and B["a"].get("goal") == "G1" and "added" not in B["n"] and B["n"].get("goal") == "G2")
        case("a long trail is cut to its first and last four moves, but `waited` still says it went waiting (5th of 10)",
             "…" in B["w"]["statuses"] and not any(x.endswith(" waiting") for x in B["w"]["statuses"])
             and B["w"].get("waited") is True and "waited" not in B["a"])
        _, _, got = run({"boards/r.json": json.dumps({"repo": "r", "tracks": ["not", "a", "dict"],
                                                       "log": [{"ts": IN, "track": "a", "msg": "added: a row"}]})})
        case("a board whose `tracks` is not a dict still folds its log, with no goal", len(got["board"]) == 1
             and got["board"][0].get("added") is True and "goal" not in got["board"][0])

        # failures
        _, _, got = run({"failures/r.jsonl": arch(
            {"id": "f1", "ts": IN, "scope": "r", "kind": "a/b", "observed": "o1", "cluster": "c1"},
            {"id": "f2", "ts": "2026-01-10T13:00:00Z", "scope": "r", "kind": "a/b", "observed": "o2", "cluster": "c1"},
            {"id": "f3", "ts": IN, "scope": "r", "kind": "a/b", "observed": "o3", "cluster": "c1"},
            {"id": "f4", "ts": IN, "scope": "r", "kind": "c/d", "observed": "o4"},
            {"id": "f0", "ts": OUT, "scope": "r", "kind": "a/b", "observed": "old"})})
        F = {r["kind"]: r for r in got["failures"]}
        case("failures fold per repo and kind, commonest first, two examples each; an older record left out",
             [r["kind"] for r in got["failures"]] == ["a/b", "c/d"] and F["a/b"]["n"] == 3 and F["a/b"]["ids"] == ["f1", "f3", "f2"]
             and F["a/b"]["examples"] == ["o1", "o3"] and F["a/b"]["last"] == "2026-01-10T13:00:00Z" and F["a/b"]["clusters"] == ["c1"])

        # loops
        _, _, got = run({"state/r/t/loop.log": f"{IN} iter 1/3 start (budget $5)\n{IN} iter 1 end rc=0 err=false/success\n"
                                                f"{IN} iter 2 end rc=124 err=/ turns=\n{IN} exit 1: 3 consecutive failures\n"
                                                f"{IN} DONE\n{OUT} DONE\n{OUT} iter 1 end rc=1 err=true\n"})
        Lp = got["loops"]
        case("loops fold a track's exits in the window: iterations, failed ones, DONE and exit lines; starts and older lines not",
             len(Lp) == 1 and (Lp[0]["iters"], Lp[0]["iter_errors"], Lp[0]["done"], Lp[0]["blocked"]) == (2, 1, 1, 0)
             and Lp[0]["exits"] == ["01-10T12:00 exit 1: 3 consecutive failures"] and Lp[0]["last_line"] == "DONE")
        _, _, got = run({"state/r/t/loop.log": f"{IN} iter 1 end rc=124 err=/ turns=\n"
                                                f"{IN} iter 1 ended with its own cc-green run still going — waiting on it, no model call: x\n"})
        case("an iteration whose cc-green run outlived it counts once: its 'iter N ended with…' line is not another iteration",
             got["loops"][0]["iters"] == 1)
        _, _, got = run({"state/r/t/loop.log": "".join(
            f"{IN} iter {k} ended with its own cc-green run still going — waiting on it, no model call: x\n" for k in (1, 2, 3))
            + f"{IN} exit 6: step limit\n"})
        case("…and three such waits do not push the track's real exit line out of the snapshot",
             [e.split(" ", 1)[1] for e in got["loops"][0]["exits"]] == ["exit 6: step limit"])

        # journals: touched in the window kept, an older one not
        h = fx({"state/r/t/progress.md": "## entry\nSTATUS: DONE\n", "state/r/u/progress.md": "old\n",
                "state/r/plan-handoff.md": "handing over\n"})
        for rel, when in (("state/r/t/progress.md", IN), ("state/r/u/progress.md", OUT), ("state/r/plan-handoff.md", IN)):
            t = datetime.strptime(when, ISO).replace(tzinfo=timezone.utc).timestamp()
            os.utime(home(rel), (t, t))
        collect(W, os.path.join(h, "snap"))
        J = list(jlines(os.path.join(h, "snap", "journals.jsonl")))
        case("journals lists files modified in the window with their STATUS, and skips an older one",
             sorted((r["path"], r["kind"], r["status"]) for r in J)
             == [("r/plan-handoff.md", "handoff", ""), ("r/t/progress.md", "journal", "STATUS: DONE")])

        # handoffs
        _, _, got = run({"state/context/handoffs.jsonl": arch(
            {"ts": IN, "kind": "started", "repo": "r", "target": "r"}, {"ts": OUT, "kind": "old", "repo": "r"},
            {"ts": datetime(2026, 1, 10, 14, tzinfo=timezone.utc).timestamp(), "kind": "epoch", "repo": "r"},
            {"ts": 1.0, "kind": "epoch-old", "repo": "r"})})
        case("handoffs keeps rows in the window, an epoch-seconds stamp read as the same UTC time",
             [(r["kind"], r["ts"]) for r in got["handoffs"]] == [("started", IN), ("epoch", "2026-01-10T14:00:00Z")])

        # spend: summed per repo/kind/model, sessions counted once, an older row out
        tsv = "#ts\tsession\tcwd\trepo\ttrack\tkind\tmodel\tin\tout\tcache_read\tcache_write\test_usd\n" + "".join(
            "\t".join(map(str, r)) + "\n" for r in [
                (IN, "s1", "/", "r", "t", "headless", "m", 1, 2, 3, 4, 0.5), (IN, "s1", "/", "r", "t", "headless", "m", 1, 2, 3, 4, 0.25),
                (IN, "s2", "/", "r", "u", "headless", "m", 1, 1, 1, 1, 1.0)])
        _, idx, got = run({"state/spend/2026-01-10.tsv": tsv,
                           "state/spend/2026-01-09.tsv": tsv.split("\n")[0] + f"\n{OUT}\ts9\t/\tr\tt\theadless\tm\t9\t9\t9\t9\t9\n"})
        K = [r for r in got["spend"] if r["by"] == "kind"]
        T = {r["track"]: r["usd"] for r in got["spend"] if r["by"] == "track"}
        case("spend sums per repo, kind and model and ranks tracks, rows before the window left out",
             len(K) == 1 and K[0]["sessions"] == 2 and K[0]["cache_read"] == 7 and K[0]["usd"] == 1.75
             and T == {"u": 1.0, "t": 0.75} and idx["per_repo"]["r"]["usd"] == 1.75)

        # caps: text cut and a file over its line cap keeps its newest rows, the rest counted
        long = "x" * 5000
        _, idx, got = run({"slack/outbox.log": "".join(f"2026-01-10T{i // 60:02d}:{i % 60:02d}:00Z\tpost\tC1\t\t{long}\n"
                                                       for i in range(CAP["outbox"] + 5))})
        case("a text is cut to its length and a file past its cap keeps the newest rows and counts the rest",
             len(got["outbox"]) == CAP["outbox"] and len(got["outbox"][0]["text"]) == TEXT["outbox"]
             and idx["sources"]["outbox"]["truncated"] == 5 and got["outbox"][0]["at"] == "2026-01-10T00:05:00Z")

        # a ranked file past its cap keeps its biggest rows, not its newest
        _, idx, got = run({"failures/r.jsonl": arch(*[{"id": f"f{k}.{i}", "ts": f"2026-01-10T{k % 24:02d}:00:00Z", "scope": "r",
                                                        "kind": f"k/{k}"} for k in range(CAP["failures"] + 2) for i in range(1 + (k < 2))])})
        case("failures past the cap keep the commonest kinds first and count the rest",
             [r["kind"] for r in got["failures"][:2]] == ["k/0", "k/1"] and len(got["failures"]) == CAP["failures"]
             and idx["sources"]["failures"]["truncated"] == 2)

        # missing sources named, not an error
        _, idx, _ = run({})
        case("an empty box writes every file and names what was missing",
             "slack/outbox.log" in idx["missing"] and "state/land/queue.log" in idx["missing"]
             and set(idx["sources"]) == {n for n, _ in SOURCES})

        # backfill: owner only, threads followed, errors named; its rows reach slack.jsonl, deduped against the archive
        h = fx({"slack/archive/r/C1/2026-01.jsonl": arch(
            {"ts": "1768046400.000100", "thread_ts": "1768046400.000100", "chat": "C1", "role": "owner", "target": "r", "text": "dup", "at": IN})})
        calls = []

        def fake(method, token, **kw):
            calls.append((method, kw.get("channel"), kw.get("oldest"), kw.get("latest")))
            if kw["channel"] == "C2":
                raise RuntimeError("not_in_channel")
            if method == "conversations.history":
                if not kw.get("cursor"):
                    return {"messages": [{"ts": "1768046400.000100", "user": "UO", "text": "dup"},
                                         {"ts": "1768046500.0", "user": "UO", "text": "parent", "reply_count": 1}],
                            "response_metadata": {"next_cursor": "p2"}}
                return {"messages": [{"ts": "1768046600.0", "user": "UM", "text": "member"},
                                     {"ts": "1768046700.0", "user": "UO", "subtype": "channel_join", "text": "j"}]}
            return {"messages": [{"ts": "1768046500.0", "user": "UO", "text": "parent"},
                                 {"ts": "1768046550.0", "user": "UO", "text": "reply", "thread_ts": "1768046500.0"}]}
        rows, errs = backfill(fake, "tok", "UO", {"C1": "r", "C2": "r"}, datetime(2026, 1, 10, tzinfo=timezone.utc),
                              datetime(2026, 1, 11, tzinfo=timezone.utc), pause=0)
        merge_backfill(rows)
        collect(W, os.path.join(h, "snap"))
        S = list(jlines(os.path.join(h, "snap", "slack.jsonl")))
        case("backfill keeps the owner's messages and replies, skips members and joins, names a chat it cannot read",
             sorted(r["text"] for r in rows) == ["dup", "parent", "reply"] and errs.keys() == {"C2"}
             and all(c[0].startswith("conversations.") for c in calls) and calls[0][2] == str(datetime(2026, 1, 10, tzinfo=timezone.utc).timestamp()))
        case("backfilled rows reach slack.jsonl, a message already archived appears once",
             sorted(r["text"] for r in S) == ["dup", "parent", "reply"]
             and [r.get("source") for r in S if r["text"] == "dup"] == [None]
             and not os.path.exists(home("slack", "archive", "r", "C1", "backfill.jsonl")))

        # backfill, thread parent before --since: its in-window reply is read; an ok:false body is an error, not 0 rows
        def old_parent(method, token, **kw):
            lo, hi = float(kw["oldest"]), float(kw["latest"])
            if method == "conversations.history":
                ms = [{"ts": "1767000000.0", "user": "UO", "text": "old", "reply_count": 2, "latest_reply": "1768046550.0"},
                      {"ts": "1767000100.0", "user": "UO", "text": "quiet", "reply_count": 1, "latest_reply": "1767000200.0"}]
                return {"messages": [m for m in ms if lo <= float(m["ts"]) < hi]}
            return {"messages": [{"ts": kw["ts"], "user": "UO", "text": "p"},
                                 {"ts": "1768046550.0", "user": "UO", "text": "late reply"},
                                 {"ts": "1767000300.0", "user": "UO", "text": "early reply"}]}
        rows, errs = backfill(old_parent, "tok", "UO", {"C1": "r"}, datetime(2026, 1, 10, tzinfo=timezone.utc),
                              datetime(2026, 1, 11, tzinfo=timezone.utc), pause=0)
        case("backfill follows a thread whose parent is before --since and keeps only its in-window reply",
             [r["text"] for r in rows] == ["late reply"] and not errs)
        rows, errs = backfill(lambda m, t, **kw: {"ok": False, "error": "missing_scope"}, "tok", "UO", {"C1": "r"},
                              datetime(2026, 1, 10, tzinfo=timezone.utc), datetime(2026, 1, 11, tzinfo=timezone.utc), pause=0)
        case("an ok:false body from the api names the chat as not read", not rows and errs.keys() == {"C1"})

        # spend with columns this tool does not know, and a loop line that ends in DONE
        _, idx, _ = run({"state/spend/2026-01-10.tsv": "#when\tcost\n" + f"{IN}\t1\n"})
        case("a spend file no row of which matches the columns is named in missing",
             any(m.startswith("state/spend (") for m in idx["missing"]))
        _, _, got = run({"state/r/t/loop.log": f"{IN} STATUS: DONE\n{IN} track finished DONE\n"})
        case("a loop line ending in DONE after other text counts as done", got["loops"][0]["done"] == 2)

        # the command itself: default name, latest link, a second run replaces, old ones pruned
        h = fx({"slack/outbox.log": ""})
        old = home("state", "improve", "snapshots", "2000-01-01")
        os.makedirs(old)
        os.utime(old, (time.time() - (KEEP_DAYS + 1) * 86400,) * 2)
        # the run names its day between these two reads; a run straddling the noon boundary may name either
        days = {default_name(datetime.now(timezone.utc).replace(microsecond=0))}
        p1 = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env={**os.environ, "HOME": h}, timeout=60)
        days.add(default_name(datetime.now(timezone.utc).replace(microsecond=0)))
        root = home("state", "improve", "snapshots")
        today = os.readlink(os.path.join(root, "latest")) if os.path.islink(os.path.join(root, "latest")) else None
        at = lambda t: default_name(datetime.fromisoformat(t))
        case("the default name is the window's midpoint day: 23:50 names its own day; 00:00 and a 00:05 catch-up the day before",
             at("2026-10-12T23:50:00+00:00") == "2026-10-12" and at("2026-10-13T00:00:00+00:00") == "2026-10-12"
             and at("2026-10-13T00:05:00+00:00") == "2026-10-12" and at("2026-10-13T12:00:01+00:00") == "2026-10-13")
        case("a default run writes <today>/, points latest at it and removes a snapshot written over 90 days ago",
             p1.returncode == 0 and today in days
             and os.path.exists(os.path.join(root, today, "index.json")) and not os.path.exists(old))
        p2 = subprocess.run([sys.executable, __file__, "--since", "2026-01-01", "--until", "2026-01-03"], capture_output=True,
                            text=True, env={**os.environ, "HOME": h}, timeout=60)
        case("--since/--until name the snapshot by both dates; --help prints the contract",
             p2.returncode == 0 and os.path.isdir(os.path.join(root, "2026-01-01..2026-01-03"))
             and os.readlink(os.path.join(root, "latest")) == "2026-01-01..2026-01-03"
             and "backfill-slack" in subprocess.run([sys.executable, __file__, "--help"], capture_output=True, text=True).stdout)
        case("a bad time is refused with a line, not a traceback",
             subprocess.run([sys.executable, __file__, "--since", "yesterdayish"], capture_output=True, text=True,
                            env={**os.environ, "HOME": h}).stderr.startswith("cc-collect: cannot read"))
    finally:
        if real_home is not None:
            os.environ["HOME"] = real_home
        for h in homes:
            shutil.rmtree(h, ignore_errors=True)
    bad = results.count(False)
    print(f"cc-collect selfcheck: {len(results) - bad} passed, {bad} failed")
    return 1 if bad else 0
