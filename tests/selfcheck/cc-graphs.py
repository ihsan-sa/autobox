# cc-graphs's selfcheck: the cases behind `cc-graphs selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-graphs execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck(_opt=None):
    global LEDGER, WORKTREES, WEB, VITALS, PROJ, STATE
    ok, bad = 0, []

    def t(name, cond):
        nonlocal ok
        if cond:
            ok += 1
        else:
            bad.append(name)

    keep_l, keep_w, keep_web, keep_v, keep_p, keep_s = LEDGER, WORKTREES, WEB, VITALS, PROJ, STATE
    root = tempfile.mkdtemp(prefix="cc-graphs-selfcheck-")
    try:
        WORKTREES = os.path.join(root, "wt")
        upto = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
        today, past = "2026-05-04", "2026-05-03"

        # 1 — lane, all four, and the one that has to be tested first: a review IS headless and IS in /tmp, so
        #     `review` before `worker`/`other` is the whole rule. Both the kept and the suppressed answer asserted.
        #     The two cwds are written out rather than built from SCRATCH: a fixture made of the constant it is
        #     testing passes whatever that constant says, which is how the older spelling went unnoticed here.
        NEW, OLD = "/tmp/cc-land.review.myrepo.7.ab12/head", "/tmp/cc-land-ab12/x"
        t("lane review", lane({"cwd": NEW, "kind": "headless"}) == "review")
        t("lane review not worker", lane({"cwd": NEW, "kind": "headless"}) != "worker")
        # …and the bare name the lander made before it put the repo and the step in the directory: the ledger still
        # holds those rows, and reading only the new spelling empties this line into `other`.
        t("lane review, the older name too", lane({"cwd": OLD, "kind": "headless"}) == "review")
        t("lane worker", lane({"cwd": WORKTREES + "/repo/track", "kind": "headless"}) == "worker")
        t("lane session", lane({"cwd": os.path.join(root, "dev"), "kind": "interactive"}) == "session")
        t("lane other", lane({"cwd": "/tmp/probe-x", "kind": "headless"}) == "other")
        t("lane worker needs headless", lane({"cwd": WORKTREES + "/r/t", "kind": "interactive"}) == "session")
        # a cwd that merely STARTS with the worktrees string is not inside it
        t("lane worktree prefix is not a parent", lane({"cwd": WORKTREES + "-else/x", "kind": "headless"}) == "other")

        # 2 — a row lands in the bucket holding its stamp, and two rows a bucket apart do not merge.
        LEDGER = os.path.join(root, "l2")
        _fixture(LEDGER, today, [_row("2026-05-04T11:00:10Z", usd=2.0), _row("2026-05-04T11:02:00Z", usd=3.0),
                                 _row("2026-05-04T11:20:00Z", usd=5.0)])
        r = tokens(hours=24, by="lane", step=900, upto=upto)
        g = r["groups"][0]
        i1 = int(datetime(2026, 5, 4, 11, 0, tzinfo=timezone.utc).timestamp() - r["t0"]) // 900
        i2 = int(datetime(2026, 5, 4, 11, 15, tzinfo=timezone.utc).timestamp() - r["t0"]) // 900
        t("bucket sums same window", abs(g["usd"][i1] - 5.0) < 1e-9)
        t("bucket keeps later row apart", abs(g["usd"][i2] - 5.0) < 1e-9 and i1 != i2)
        t("bucket total", abs(r["total"]["usd"] - 10.0) < 1e-9)
        t("tokens is the four counts", g["tokens"][i1] == 2 * (1 + 2 + 3 + 4))
        t("last bucket flagged partial", r["partial"] is True)
        t("buckets are epoch-aligned", r["t0"] % 900 == 0)

        # 3 — the window is a filter: a row before t0 is gone, one inside is kept.
        LEDGER = os.path.join(root, "l3")
        _fixture(LEDGER, past, [_row("2026-05-03T01:00:00Z", usd=9.0)])
        _fixture(LEDGER, today, [_row("2026-05-04T11:00:00Z", sess="a", usd=1.0),
                                 _row("2026-05-04T11:05:00Z", sess="b", usd=1.0)])
        r = tokens(hours=6, by="lane", step=900, upto=upto)
        t("window drops the older row", abs(r["total"]["usd"] - 2.0) < 1e-9)
        r = tokens(hours=24, by="lane", step=DAY, upto=upto)
        t("wider window keeps it", abs(r["total"]["usd"] - 11.0) < 1e-9)

        # 4 — a backfilled day (one row per (session, model), and the day is over) is DROPPED below daily buckets
        #     and INCLUDED at daily ones. Both halves asserted, on state this case built.
        LEDGER = os.path.join(root, "l4")
        _fixture(LEDGER, past, [_row("2026-05-03T23:00:00Z", sess="a", usd=4.0),
                                _row("2026-05-03T23:00:00Z", sess="b", usd=6.0)])
        _fixture(LEDGER, today, [_row("2026-05-04T11:00:00Z", sess="c", usd=1.0),
                                 _row("2026-05-04T11:30:00Z", sess="c", usd=1.0)])
        r = tokens(hours=24, by="lane", step=900, upto=upto)
        t("coarse day not drawn", abs(r["total"]["usd"] - 2.0) < 1e-9)
        t("coarse day reported", [c["day"] for c in r["coarse"]["days"]] == [past]
          and abs(r["coarse"]["usd"] - 10.0) < 1e-9)
        # the half that matters: blank over the coarse day, a real 0 where the box simply spent nothing
        blind_i = int(datetime(2026, 5, 3, 23, 0, tzinfo=timezone.utc).timestamp() - r["t0"]) // 900
        seen_i = int(datetime(2026, 5, 4, 11, 0, tzinfo=timezone.utc).timestamp() - r["t0"]) // 900
        quiet_i = int(datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc).timestamp() - r["t0"]) // 900
        g0 = r["groups"][0]
        t("coarse buckets are null, not zero", g0["usd"][blind_i] is None and g0["tokens"][blind_i] is None)
        t("a drawn bucket is a number", g0["usd"][seen_i] == 1.0)
        t("a genuinely quiet bucket is zero, not null", g0["usd"][quiet_i] == 0)
        t("nulls are left out of the total", abs(g0["total"]["usd"] - 2.0) < 1e-9)
        r = tokens(hours=24, by="lane", step=DAY, upto=upto)
        t("coarse day drawn at daily", abs(r["total"]["usd"] - 12.0) < 1e-9 and not r["coarse"]["days"])

        # 4b — before the ledger's first day the answer is BLANK; after it, an empty bucket is a real zero.
        LEDGER = os.path.join(root, "l4b")
        _fixture(LEDGER, today, [_row("2026-05-04T11:00:00Z", sess="a", usd=1.0),
                                 _row("2026-05-04T11:30:00Z", sess="a", usd=1.0)])
        r = tokens(hours=24, by="lane", step=900, upto=upto)
        g0 = r["groups"][0]
        before = int(datetime(2026, 5, 3, 20, 0, tzinfo=timezone.utc).timestamp() - r["t0"]) // 900
        after = int(datetime(2026, 5, 4, 5, 0, tzinfo=timezone.utc).timestamp() - r["t0"]) // 900
        t("before the ledger starts is blank", g0["usd"][before] is None)
        t("a quiet bucket after it is zero", g0["usd"][after] == 0)
        t("the ledger's first day is reported", r["coarse"]["ledger_from"] == today)

        # 4d — THE PREFIX RULE (review finding, PR #199). `rows == distinct keys` also matches a genuinely quiet
        #      day, so it may only be believed about the ledger's OPENING run. Both halves on one fixture: the
        #      opening day is blanked and reported, and a quiet day with the SAME signature AFTER a normal day is
        #      drawn — which is the spend the old rule dropped while telling the reader a backfill caused it.
        LEDGER = os.path.join(root, "l4d")
        _fixture(LEDGER, "2026-05-01", [_row("2026-05-01T13:00:00Z", sess=x, usd=4.0) for x in ("a", "b")])
        _fixture(LEDGER, "2026-05-02", [_row("2026-05-02T13:00:00Z", sess="c", usd=1.0),
                                        _row("2026-05-02T13:30:00Z", sess="c", usd=1.0)])
        _fixture(LEDGER, "2026-05-03", [_row("2026-05-03T13:00:00Z", sess=x, usd=3.0) for x in ("d", "e")])
        _fixture(LEDGER, today, [_row("2026-05-04T11:00:00Z", sess="f", usd=5.0)])
        r = tokens(hours=72, by="lane", step=900, upto=upto)
        g0 = r["groups"][0]
        at = lambda dt_: int(dt_.timestamp() - r["t0"]) // 900
        near = lambda v, x: v is not None and abs(v - x) < 1e-9      # a blanked bucket must FAIL, not raise
        opening = at(datetime(2026, 5, 1, 13, 0, tzinfo=timezone.utc))
        normal = at(datetime(2026, 5, 2, 13, 0, tzinfo=timezone.utc))
        quiet = at(datetime(2026, 5, 3, 13, 0, tzinfo=timezone.utc))
        t("the opening day is still blanked", g0["usd"][opening] is None)
        t("only the opening day is reported coarse", [c["day"] for c in r["coarse"]["days"]] == ["2026-05-01"]
          and abs(r["coarse"]["usd"] - 8.0) < 1e-9)
        t("the day that breaks the run is drawn", near(g0["usd"][normal], 1.0))
        t("a quiet day AFTER it is drawn, not blamed on a backfill", near(g0["usd"][quiet], 6.0))
        t("its spend is in the total", abs(r["total"]["usd"] - 13.0) < 1e-9)

        # 4c — an empty ledger answers, it does not crash: no lines, no totals, nothing claimed.
        LEDGER = os.path.join(root, "empty")
        os.makedirs(LEDGER)
        r = tokens(hours=24, by="lane", step=900, upto=upto)
        t("empty ledger answers", r["groups"] == [] and r["total"]["usd"] == 0 and r["rows"] == 0)
        t("empty ledger claims no first day", r["coarse"]["ledger_from"] is None)

        # 5 — today is never coarse: this morning legitimately has one row per session so far.
        LEDGER = os.path.join(root, "l5")
        _fixture(LEDGER, today, [_row("2026-05-04T09:00:00Z", sess="a", usd=1.0),
                                 _row("2026-05-04T10:00:00Z", sess="b", usd=1.0)])
        r = tokens(hours=24, by="lane", step=900, upto=upto)
        t("day in progress is drawn", abs(r["total"]["usd"] - 2.0) < 1e-9)
        t("day in progress is not coarse", not r["coarse"]["days"])

        # 6 — more groups than fit fold into `other`, and folding loses nothing.
        LEDGER = os.path.join(root, "l6")
        _fixture(LEDGER, today, [_row("2026-05-04T11:00:00Z", sess="s%d" % k, track="t%02d" % k, usd=float(k + 1))
                                 for k in range(MAX_GROUPS + 5)])
        r = tokens(hours=24, by="track", step=900, upto=upto)
        want = sum(float(k + 1) for k in range(MAX_GROUPS + 5))
        t("fold keeps every dollar", abs(r["total"]["usd"] - want) < 1e-6)
        t("fold caps the lines", len(r["groups"]) <= MAX_GROUPS + 1 and r["folded"])
        t("fold has an other line", any(g["key"] == "other" for g in r["groups"]))
        t("biggest track survives folding", any(g["key"] == "t%02d" % (MAX_GROUPS + 4) for g in r["groups"]))
        # the colour a group gets must not move when the ranking does. Same five groups both times — a set that
        # folds would change WHICH groups survive, which is a different question from this one.
        LEDGER = os.path.join(root, "l6b")
        _fixture(LEDGER, today, [_row("2026-05-04T11:00:00Z", sess="s%d" % k, track="t%d" % k, usd=float(k + 1))
                                 for k in range(5)])
        up = tokens(hours=24, by="track", step=900, upto=upto)
        _fixture(LEDGER, today, [_row("2026-05-04T11:00:00Z", sess="s%d" % k, track="t%d" % k, usd=float(5 - k))
                                 for k in range(5)])
        down = tokens(hours=24, by="track", step=900, upto=upto)
        c1 = {g["key"]: g["colour"] for g in up["groups"]}
        t("the ranking really did flip",
          [g["key"] for g in down["groups"]] == list(reversed([g["key"] for g in up["groups"]])))
        t("colour follows the name, not the rank", all(c1[g["key"]] == g["colour"] for g in down["groups"]))
        # 6c — and not the MEMBERSHIP either (review finding, PR #199): an index over the surviving names moved
        #      every line below a newcomer. These five names hash to five different slots, so what this case
        #      isolates is membership, not a collision — a collision is settled by walking to the next free slot
        #      and CAN move the later name, which the comment beside the code says outright.
        LEDGER = os.path.join(root, "l6c")
        four = [_row("2026-05-04T11:00:00Z", sess="s%d" % k, track="t%d" % k, usd=float(k)) for k in (1, 2, 3, 4)]
        _fixture(LEDGER, today, four)
        before = tokens(hours=24, by="track", step=900, upto=upto)
        # the newcomer sorts FIRST and outspends them all, which is the shape that shifted an index-based slot
        _fixture(LEDGER, today, four + [_row("2026-05-04T11:00:00Z", sess="s0", track="t0", usd=99.0)])
        after = tokens(hours=24, by="track", step=900, upto=upto)
        cb = {g["key"]: g["colour"] for g in before["groups"]}
        ca = {g["key"]: g["colour"] for g in after["groups"]}
        t("the membership really did change", set(ca) - set(cb) == {"t0"} and after["groups"][0]["key"] == "t0")
        t("a newcomer re-colours nobody", all(ca[k] == cb[k] for k in cb))
        t("and the survivors still differ from each other", len(set(ca.values())) == len(ca))

        # 7 — a torn row is skipped, not a crash, and the good row beside it still counts.
        LEDGER = os.path.join(root, "l7")
        os.makedirs(LEDGER)
        with open(os.path.join(LEDGER, today + ".tsv"), "w") as f:
            f.write("#" + "\t".join(COLS) + "\n")
            f.write("2026-05-04T11:00:00Z\tbroken\n")
            f.write("\t".join(str(x) for x in _row("2026-05-04T11:00:00Z", usd=7.0)) + "\n")
            f.write("not-a-stamp\ts\t/w\tr\tt\theadless\tm\t1\t1\t1\t1\t1.0\n")
        r = tokens(hours=24, by="lane", step=900, upto=upto)
        t("torn rows skipped, good row kept", abs(r["total"]["usd"] - 7.0) < 1e-9 and r["rows"] == 1)

        # 8 — the bucket a window gets on its own, at both sides of each edge. On an empty ledger of its own:
        #     these are the window arithmetic and must not read the rows case 7 happened to leave behind.
        LEDGER = os.path.join(root, "l8")
        os.makedirs(LEDGER)
        t("auto 6h", auto_step(6) == TICK and auto_step(7) == 900)
        t("auto 48h", auto_step(48) == 900 and auto_step(49) == 3600)
        t("auto 7d", auto_step(24 * 7) == 3600 and auto_step(24 * 7 + 1) == DAY)
        t("bad bucket refused", _raises(lambda: tokens(hours=24, step=77, upto=upto)))
        t("too many buckets refused", _raises(lambda: tokens(hours=24 * 90, step=TICK, upto=upto)))
        t("that same window is fine daily", tokens(hours=24 * 90, step=DAY, upto=upto)["n"] <= MAX_BUCKETS)
        t("bad group refused", _raises(lambda: tokens(hours=24, by="session", upto=upto)))
        # a finer bucket is still held at 90 days, so a window past that is refused rather than silently cut
        t("a finer bucket keeps the 90-day bound", _raises(lambda: tokens(hours=24 * 400, step=3600, upto=upto)))

        # 8a — A DAILY WINDOW IS NOT CUT AT 90 DAYS (review finding, PR #578). The all-time ask — the ledger's
        #      first day file to now — used to be clamped to 2160 h, so a ledger older than that lost its opening
        #      months from `total` while the caller was told it had asked for every day. Fixture ledger, real
        #      window arithmetic: the first day is 200 days back and its dollars have to be in the total.
        LEDGER = os.path.join(root, "l8a")
        old_day = (upto - timedelta(days=200)).date().isoformat()
        _fixture(LEDGER, old_day, [_row(old_day + "T01:00:00Z", sess="a", usd=8.0)])
        _fixture(LEDGER, today, [_row("2026-05-04T11:00:00Z", sess="b", usd=1.0)])
        old_midnight = datetime.strptime(old_day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        far = int((upto - old_midnight).total_seconds() // 3600) + 1        # rounded up, as the dashboard asks it
        r = tokens(hours=far, by="lane", step=DAY, upto=upto)
        t("a 200-day daily window keeps its first day", abs(r["total"]["usd"] - 9.0) < 1e-9)
        t("and the window answered is the one asked for", r["window_h"] == far and far > 24 * 90)
        LEDGER = os.path.join(root, "l8")             # 8b's arithmetic is the empty ledger's again, not this one's

        # 8b — the /usage-style raw total (--raw / raw=True): every assistant record's usage, no dedup at all —
        #      not even cc-spend's requestId one — reproducing the naive sum /usage does. Off by default and
        #      strictly additive: it must never move total.tokens or any group.
        PROJ = os.path.join(root, "proj")
        os.makedirs(os.path.join(PROJ, "p1"))

        def _tline(rid, ts, i=0, o=0, cr=0, cw=0):
            return json.dumps({"type": "assistant", "requestId": rid, "timestamp": ts, "sessionId": "s1",
                                "message": {"usage": {"input_tokens": i, "output_tokens": o,
                                                       "cache_read_input_tokens": cr,
                                                       "cache_creation_input_tokens": cw}}})

        raw_now = now()
        in_win = (raw_now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        out_win = (raw_now - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        with open(os.path.join(PROJ, "p1", "s1.jsonl"), "w") as f:
            f.write(_tline("req1", in_win, i=10, o=1, cr=2, cw=3) + "\n")   # one response, logged 3 times over —
            f.write(_tline("req1", in_win, i=10, o=1, cr=2, cw=3) + "\n")   # cc-spend dedupes these to ONE;
            f.write(_tline("req1", in_win, i=10, o=1, cr=2, cw=3) + "\n")   # raw does not
            f.write(_tline("req2", in_win, i=5, o=0, cr=0, cw=0) + "\n")    # a second, distinct response
            f.write(_tline("req3", out_win, i=999, o=0, cr=0, cw=0) + "\n")  # outside the window — its own
                                                                              # record says so, not its file's

        r_no_raw = tokens(hours=24, by="lane", step=900, upto=raw_now)
        t("raw is opt-in: absent unless asked for", "raw" not in r_no_raw)

        r_raw = tokens(hours=24, by="lane", step=900, upto=raw_now, raw=True)
        t("raw sums every record with no dedup: req1's three copies all count", r_raw["raw"]["in"] == 10 * 3 + 5)
        t("a record's own timestamp outside the window is excluded even though its file is fresh",
          r_raw["raw"]["in"] != 10 * 3 + 5 + 999)
        t("raw tokens is the four counts summed", r_raw["raw"]["tokens"] ==
          r_raw["raw"]["in"] + r_raw["raw"]["out"] + r_raw["raw"]["cache_read"] + r_raw["raw"]["cache_write"])
        t("raw never moves the box's own count", r_raw["total"] == r_no_raw["total"]
          and r_raw["groups"] == r_no_raw["groups"])

        # a file whose last write predates the window cannot hold a record inside it, whatever the record itself
        # claims — skipped without being opened at all.
        old = os.path.join(PROJ, "p1", "old.jsonl")
        with open(old, "w") as f:
            f.write(_tline("req9", in_win, i=12345) + "\n")
        stale = raw_now.timestamp() - 999999
        os.utime(old, (stale, stale))
        r_raw2 = tokens(hours=24, by="lane", step=900, upto=raw_now, raw=True)
        t("a file untouched since before the window is skipped, not read", r_raw2["raw"]["in"] == r_raw["raw"]["in"])

        # 8b — a restart comes back on the port it was already serving. `serve` IS a restart, and a landing that
        #      brings this server back after changing it must not move the page the owner has open.
        STATE = os.path.join(root, "state")
        os.makedirs(STATE)
        t("serve_port: nothing running, the default", serve_port({}) == PORT)
        with open(pidfile(), "w") as f:
            f.write(str(os.getpid()))               # this process's own cmdline names cc-graphs, so running() sees it
        with open(portfile(), "w") as f:
            f.write("5199")
        t("serve_port: a running server keeps the port it is on", serve_port({}) == 5199 != PORT)
        t("serve_port: --port still wins over it", serve_port({"--port": "5201"}) == 5201)
        with open(portfile(), "w") as f:
            f.write("not a number")
        t("serve_port: an unreadable port file falls back, it does not crash the restart", serve_port({}) == PORT)

        # 9 — the server: loopback, read-only, exact asset allowlist.
        WEB = os.path.join(root, "web")
        os.makedirs(WEB)
        for a in ASSETS:
            with open(os.path.join(WEB, a), "w") as f:
                f.write("/*%s*/" % a)
        with open(os.path.join(root, "secret"), "w") as f:
            f.write("no")
        t("bind is loopback", BIND == "127.0.0.1")
        import threading
        import urllib.request
        quiet = Handler.log_message
        Handler.log_message = lambda *a, **k: None      # the cases are the output; an access log is not
        srv = ThreadingHTTPServer((BIND, 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://%s:%d" % (BIND, srv.server_port)

        def get(p, method="GET"):
            rq = urllib.request.Request(base + p, method=method)
            try:
                with urllib.request.urlopen(rq, timeout=5) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as e:
                return e.code, e.read()
        try:
            t("index served", get("/")[0] == 200 and get("/")[1].startswith(b"/*index.html"))
            t("asset served", get("/app.js")[0] == 200)
            t("head has no body", get("/app.js", "HEAD")[1] == b"")
            t("unknown asset refused", get("/secret")[0] == 404)
            t("traversal refused", get("/../secret")[0] == 404 and get("/%2e%2e/secret")[0] == 404)
            t("post refused", get("/", "POST")[0] == 405)
            t("unknown api is 404 json", get("/api/nope")[0] == 404)
            t("bad query is 400 not 500", get("/api/tokens?by=nope")[0] == 400)
            # A fixture of its own, and stamped NOW: the endpoint asks the real clock, not this case's `upto`.
            # The earlier day of zero-cost rows is there so that "before the ledger begins is blank" cannot blank
            # the row itself when this runs in the first minute after UTC midnight — the total is 3.5 either way.
            LEDGER = os.path.join(root, "l9")
            yday = (now() - timedelta(days=1)).strftime("%Y-%m-%d")
            _fixture(LEDGER, yday, [_row(yday + "T00:00:0%dZ" % k, i=0, o=0, cr=0, cw=0, usd=0.0) for k in (0, 1)])
            _fixture(LEDGER, now().strftime("%Y-%m-%d"), [_row(iso(time.time() - 60), usd=3.5)])
            code, body = get("/api/tokens?hours=24&bucket=900")
            j = json.loads(body)
            t("tokens endpoint is the same function, on this case's own ledger",
              code == 200 and j["step"] == 900 and abs(j["total"]["usd"] - 3.5) < 1e-9)
            code, body = get("/api/tokens?hours=24&bucket=900")
            t("raw absent by default over the wire too", "raw" not in json.loads(body))
            # PROJ is still case 8b's fixture — this only proves the query param reaches the same raw_tokens()
            code, body = get("/api/tokens?hours=24&bucket=900&raw=1")
            t("?raw=1 turns it on over the wire", json.loads(body)["raw"]["in"] == 10 * 3 + 5)

            # 10 — /api/vitals is a PASSTHROUGH and nothing else: whatever cc-vitals prints comes back unchanged.
            #      On a stub written here, because this case must never run this box's own recorder. Both sides:
            #      the object that is passed through, and the cc-vitals that fails — which is an error the page
            #      can show, not a server that fell over with it.
            VITALS = os.path.join(root, "stub-vitals.py")
            spec = {"generated": "2026-05-04T12:00:00Z", "n": 2, "step": 60, "t0": 1,
                    "series": [{"key": "cpu", "norm": [1.0, None]}]}
            with open(VITALS, "w") as f:
                f.write("import sys\nsys.stdout.write(%r)\n" % json.dumps(spec))
            t("vitals passes cc-vitals through unchanged", vitals(hours=6) == spec)
            code, body = get("/api/vitals?hours=6")
            t("vitals endpoint serves that same object", code == 200 and json.loads(body) == spec)
            with open(VITALS, "w") as f:
                f.write("import sys\nsys.stderr.write('recorder is off\\n')\nsys.exit(1)\n")
            code, body = get("/api/vitals?hours=6")
            t("a failing cc-vitals is an error the page can show",
              code == 500 and "recorder is off" in json.loads(body)["error"])
            t("and the server is still up after it", get("/")[0] == 200)
        finally:
            srv.shutdown()
            srv.server_close()
            Handler.log_message = quiet
    finally:
        LEDGER, WORKTREES, WEB, VITALS, PROJ, STATE = keep_l, keep_w, keep_web, keep_v, keep_p, keep_s
        shutil.rmtree(root, ignore_errors=True)

    print("cc-graphs selfcheck: %d passed, %d failed" % (ok, len(bad)))
    for b in bad:
        print("  FAIL", b)
    return 1 if bad else 0
