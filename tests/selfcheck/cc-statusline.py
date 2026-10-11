# cc-statusline's selfcheck: the cases behind `cc-statusline selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-statusline execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    import tempfile
    p = f = 0

    def ok(name, cond):
        nonlocal p, f
        if cond:
            p += 1
        else:
            f += 1
            print(f"  FAIL {name}")

    sid, record, out = extract({
        "session_id": "sid-1", "model": {"id": "claude-opus-5", "display_name": "Opus"},
        "context_window": {"total_input_tokens": 15500, "context_window_size": 200000, "used_percentage": 8},
        "cost": {"total_cost_usd": 1.23, "total_duration_ms": 45000},
        "rate_limits": {"five_hour": {"used_percentage": 12}},
    })
    ok("the fields cc-context reads are pulled out", record["used"] == 15500 and record["window"] == 200000
       and record["pct"] == 8 and record["model"] == "claude-opus-5")
    ok("the whole payload survives verbatim under raw, for a later reader (spend site, Home tab)",
       record["raw"]["rate_limits"]["five_hour"]["used_percentage"] == 12
       and record["raw"]["cost"]["total_duration_ms"] == 45000)
    ok("the printed line is one line, short, and names the model, percentage and cost",
       "\n" not in out and "Opus" in out and "8% ctx" in out and "$1.23" in out)

    # used_percentage is null early in a session (docs: "may be null early in the session") — derive it
    _, record2, _ = extract({"session_id": "sid-2", "model": {"id": "claude-sonnet-5"},
                              "context_window": {"total_input_tokens": 10000, "context_window_size": 200000,
                                                  "used_percentage": None}})
    ok("a null used_percentage is derived from the raw token counts", record2["pct"] == 5.0)

    # nothing usable yet: no context_window key at all (before the first API call)
    _, record3, out3 = extract({"session_id": "sid-3", "model": {"id": "claude-opus-5", "display_name": "Opus"}})
    ok("no context_window at all still writes a record and prints a line, not a crash",
       record3["used"] is None and record3["pct"] is None and "ctx ?" in out3)

    with tempfile.TemporaryDirectory() as d:
        global DIR
        keep, DIR = DIR, d
        write(sid, record)
        fp = os.path.join(d, "sid-1.json")
        ok("the file lands under DIR, keyed by session id", os.path.exists(fp))
        with open(fp) as fh:
            on_disk = json.load(fh)
        ok("what is on disk is exactly what extract() returned", on_disk == record)
        write(None, {"x": 1})
        ok("no session id -> nothing written (there is no key to write it under)",
           sorted(os.listdir(d)) == ["sid-1.json"])

        # session_id is untrusted input, joined straight into a path: an absolute or ../ id must never escape DIR
        outside = os.path.join(os.path.dirname(d), "escaped.json")
        write("/etc/passwd", {"x": 1})
        ok("an absolute session id is rejected, not joined onto DIR", sorted(os.listdir(d)) == ["sid-1.json"])
        write("../escaped", {"x": 1})
        ok("a ../ session id is rejected — nothing is written outside DIR", not os.path.exists(outside)
           and sorted(os.listdir(d)) == ["sid-1.json"])
        write("sid.2_ok-3", record)
        ok("an ordinary id with dots, underscores and dashes is still written normally",
           os.path.exists(os.path.join(d, "sid.2_ok-3.json")))
        write(".hidden", {"x": 1})
        ok("a leading dot is rejected too", not os.path.exists(os.path.join(d, ".hidden.json")))
        DIR = keep

    import contextlib, io
    real_stdin = sys.stdin
    try:
        sys.stdin = io.StringIO("not json")
        out_buf = io.StringIO()
        with contextlib.redirect_stdout(out_buf):
            rc = main([])
        ok("garbage stdin is never fatal — the status bar must not go blank because of this script",
           rc == 0 and out_buf.getvalue().strip() != "")
    finally:
        sys.stdin = real_stdin

    print(f"cc-statusline selfcheck: {p} passed, {f} failed")
    return 1 if f else 0
