# cc-time's selfcheck: the cases behind `cc-time selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-time execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    import re
    n = f = 0

    def check(name, cond):
        nonlocal n, f
        n += 1
        print(("  ok   " if cond else "  FAIL ") + name)
        if not cond:
            f += 1

    # A zone of its own, never this box's: a fixed offset, no DST, and far enough east that the DAY moves too —
    # a renderer that only pretended to convert would still pass a same-day check.
    FZ, INSTANT = "Asia/Tokyo", 1788274921          # 2026-09-01 15:02 UTC = 2026-09-02 00:02 in Tokyo
    was = os.environ.get("CC_TZ")
    try:
        os.environ["CC_TZ"] = "UTC"
        check("a known instant in UTC is its own HH:MM", slack(INSTANT) == "15:02")
        os.environ["CC_TZ"] = FZ
        check("…and in the configured zone it is that zone's HH:MM", slack(INSTANT) == "00:02")
        check("--date carries the zone's DAY, which is not the UTC one", slack(INSTANT, day=True) == "2026-09-02 00:02")
        check("no rendering carries a Z — that is the whole rule",
              "Z" not in slack(INSTANT) + slack(INSTANT, day=True) + slack())
        check("a UTC ISO stamp (what the board, the queue and GitHub write) converts too",
              slack("2026-09-01T04:33:58Z") == "13:33")
        check("a fractional epoch renders the same minute", slack(f"{INSTANT}.947") == "00:02")
        check("several WHENs render one line each, in order, and an empty list renders nothing",
              slack_all([INSTANT, INSTANT + 3600]) == ["00:02", "01:02"] and slack_all([]) == [])
        check("zone names what is in force", zone() == FZ)
        os.environ["CC_TZ"] = "Mars/Olympus"        # date(1) and ZoneInfo would take it and give UTC, unremarked
        err = io_capture()
        check("an unknown zone falls back to the box's OWN zone and says so, rather than a silent UTC",
              slack(INSTANT) == dt.datetime.fromtimestamp(INSTANT).strftime("%H:%M")
              and "no zone called Mars/Olympus" in err())
        del os.environ["CC_TZ"]                      # whatever THIS box is set to: the shape is what can be asserted
        check("with nothing configured there is still a zone, an HH:MM and no Z",
              bool(zone()) and bool(re.fullmatch(r"\d\d:\d\d", slack(INSTANT))))
    finally:
        os.environ.pop("CC_TZ", None) if was is None else os.environ.__setitem__("CC_TZ", was)

    # THE DOOR: cc-notify's one Slack-facing stamp. Its push is a real send, so this drives it in log-only mode and
    # reads back the line it wrote — whose trailing `rung=… kind=… send=…` is cc-notify's, and not this rule's.
    import tempfile
    log = tempfile.mktemp(prefix="_selfcheck_cctime_")
    env = dict(os.environ, CC_TZ=FZ, CC_NOTIFY_LOG_ONLY="1", CC_NOTIFY_LOG=log)
    try:
        subprocess.run([f"{BIN}/cc-notify", "test"], env=env, capture_output=True, timeout=60,
                       stdin=subprocess.DEVNULL)
        line = open(log).read().strip()
    except Exception as e:
        line = f"(cc-notify did not run: {e})"
    check("cc-notify's push is stamped HH:MM with no Z and no 'UTC'",
          bool(re.search(r"\tNotifications work\. \d\d:\d\d(\t|$)", line)))
    check("…while the LOG line beside it is still UTC and still ends in Z",
          bool(re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\t", line)))
    if os.path.exists(log):
        os.remove(log)
    print(f"cc-time selfcheck: {n - f} passed, {f} failed")
    return 0 if f == 0 else 1
