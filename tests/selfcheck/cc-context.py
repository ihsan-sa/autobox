# cc-context's selfcheck: the cases behind `cc-context selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-context execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    import contextlib, io, tempfile
    p = f = 0

    def ok(name, cond):
        nonlocal p, f
        if cond:
            p += 1
        else:
            f += 1
            print(f"  FAIL {name}")

    def tx(entries):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
        return path

    def asst(model, inp, cc, cr, out=10, side=False):
        return {"type": "assistant", "isSidechain": side, "message": {
            "model": model, "usage": {"input_tokens": inp, "cache_creation_input_tokens": cc,
                                      "cache_read_input_tokens": cr, "output_tokens": out}}}

    def run(argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    env0 = os.environ.pop("CC_CTX_WINDOW", None)
    sid0 = os.environ.pop("CLAUDE_CODE_SESSION_ID", None)   # resolve() reads it: the session RUNNING the test is not a fixture
    box0 = os.environ.get("CC_CTX_BOX_MODEL")
    os.environ["CC_CTX_BOX_MODEL"] = ""        # hermetic: what THIS box runs must not decide a fixture's window
    # …and neither must the box's own ~/.cc/config: cfg() reads through cc-config, and a hand-off line set there
    # would move the line asserted below. This run reads an EMPTY config of its own.
    cfg0 = os.environ.get("CC_CONFIG")
    cfgd = tempfile.mkdtemp(prefix="cc-context-selfcheck-")
    os.environ["CC_CONFIG"] = os.path.join(cfgd, "config"); open(os.environ["CC_CONFIG"], "w").close()
    hl0 = os.environ.pop("CC_CONTEXT_HANDOFF_TOKENS", None)

    # used = input + cache_creation + cache_read of the LAST assistant turn
    t = tx([asst("claude-opus-5", 5, 100, 200), asst("claude-opus-5", 10, 1000, 9000)])
    m = measure(t)
    ok("used = last turn's input+cache_creation+cache_read", m["used"] == 10010)
    ok("assumed window is flagged", m["window"] == DEFAULT_WINDOW and m["window_src"] == "assumed")
    ok("assumption is stated in the output", "NO evidence" in line(m))

    # a subagent's window is its own: sidechain entries never count
    m = measure(tx([asst("claude-opus-5", 10, 1000, 9000), asst("claude-opus-5", 0, 0, 500000, side=True)]))
    ok("sidechain entries are ignored", m["used"] == 10010)

    # cost-state carries the exact model id, [1m] and all
    m = measure(tx([asst("claude-opus-5", 10, 1000, 9000),
                    {"type": "cost-state", "modelUsage": {"claude-opus-5[1m]": {"inputTokens": 1}}}]))
    ok("cost-state gives the 1M window", m["window"] == BIG_WINDOW and m["window_src"] == "cost-state")
    ok("pct is against the real window", m["pct"] == 1.0)

    # a compact boundary AFTER the last answer replaces the number and dates the window
    m = measure(tx([asst("claude-opus-5", 10, 1000, 989000),
                    {"type": "system", "subtype": "compact_boundary",
                     "compactMetadata": {"trigger": "auto", "preTokens": 1000830, "postTokens": 14226}}]))
    ok("post-compact used = postTokens", m["used"] == 14226 and m["compacted"])
    ok("the session's own compaction sizes the window", m["window"] == BIG_WINDOW and m["window_src"] == "compacted")

    m = measure(tx([asst("claude-sonnet-5", 10, 1000, 189000),
                    {"type": "system", "subtype": "compact_boundary",
                     "compactMetadata": {"preTokens": 190000, "postTokens": 9000}}]))
    ok("compacting at 190k means a 200k window", m["window"] == DEFAULT_WINDOW)

    # never a percentage above 100: evidence beats the assumption
    m = measure(tx([asst("claude-opus-5", 0, 0, 640000)]))
    ok("used above the assumed window raises it", m["window"] == BIG_WINDOW and m["pct"] == 64.0)
    ok("the override is visible in the source", m["window_src"] == "assumed+observed")

    # the box's own model answers only for its own family: opus-5 and opus-5[1m] are one model, fable is not
    os.environ["CC_CTX_BOX_MODEL"] = "claude-opus-5[1m]"
    m = measure(tx([asst("claude-opus-5", 10, 1000, 9000)]))
    ok("cc-model's [1m] sizes a same-family session", m["window"] == BIG_WINDOW and m["window_src"] == "cc-model")
    m = measure(tx([asst("claude-sonnet-5", 10, 1000, 9000)]))
    ok("a different family says nothing", m["window_src"] == "assumed")
    m = measure(tx([asst("claude-opus-5", 10, 1000, 9000),
                    {"type": "cost-state", "modelUsage": {"claude-opus-5": {"inputTokens": 1}}}]))
    ok("a suffix-less id is raised to the size the box runs that family at",
       m["window"] == BIG_WINDOW and m["window_src"] == "cost-state+cc-model")
    os.environ["CC_CTX_BOX_MODEL"] = ""

    os.environ["CC_CTX_WINDOW"] = "500000"
    m = measure(tx([asst("claude-opus-5", 0, 0, 250000)]))
    ok("CC_CTX_WINDOW wins", m["window"] == 500000 and m["pct"] == 50.0 and m["window_src"] == "env")
    del os.environ["CC_CTX_WINDOW"]

    # a transcript with nothing answered yet, and a half-written last line (a live session)
    ok("no answered turn -> None", measure(tx([{"type": "user", "message": {"role": "user"}}])) is None)
    t = tx([asst("claude-opus-5", 10, 1000, 9000)])
    with open(t, "a") as fh:
        fh.write('{"type":"assistant","message":{"usa')
    ok("a half-written last line is skipped", measure(t)["used"] == 10010)

    # the tail is grown until a turn is found: a big transcript whose last turns are far back
    big = tx([asst("claude-opus-5", 1, 2, 3)] + [{"type": "user", "pad": "x" * 4000} for _ in range(200)])
    ok("tail grows past 256k of padding", measure(big)["used"] == 6)

    # the hand-off line: one absolute number, and the level and the printed line read it
    ok("the hand-off line defaults to 150k tokens", handoff_line() == 150000)
    os.environ["CC_CONTEXT_HANDOFF_TOKENS"] = "100000"
    ok("...and CC_CONTEXT_HANDOFF_TOKENS moves it", handoff_line() == 100000)
    del os.environ["CC_CONTEXT_HANDOFF_TOKENS"]
    m = judge(measure(tx([asst("claude-opus-5", 0, 0, 149999)])))
    ok("one token under the line is no level, and the line says nothing about handing off",
       m["level"] is None and "hand off" not in line(m))
    m = judge(measure(tx([asst("claude-opus-5", 0, 0, 150000)])))
    ok("at the line the level is handoff and the line says so",
       m["level"] == "handoff" and "hand off (past the 150k line)" in line(m))
    # the rotate line: above the hand-off line, its own number, and the box's to act on
    ok("the rotate line defaults to 200k tokens", rotate_line() == 200000)
    ok("one token under the rotate line is level handoff and NOT rotate, and the line does not say the box hands off",
       not m["rotate"] and m["rotate_line"] == 200000 and "rotate line" not in line(m))
    m = judge(measure(tx([asst("claude-opus-5", 0, 0, 200000)])))
    ok("at the rotate line rotate is True and the line says the box hands it off",
       m["rotate"] and m["level"] == "handoff" and "past the 200k rotate line too, so the box hands it off" in line(m))
    os.environ["CC_CONTEXT_ROTATE_TOKENS"] = "0"
    ok("...and CC_CONTEXT_ROTATE_TOKENS=0 switches it off at any size", not judge(m)["rotate"])
    os.environ["CC_CONTEXT_ROTATE_TOKENS"] = "300000"
    ok("...and a moved line is read: 200k is under 300k", not judge(m)["rotate"] and m["rotate_line"] == 300000)
    del os.environ["CC_CONTEXT_ROTATE_TOKENS"]

    # --over: a percentage, or the line itself; unmeasurable is 2, never a guess
    t = tx([asst("claude-opus-5", 10, 1000, 9000)])                       # 10010 of an assumed 200k = 5%
    ok("--over N exits 0 at/over N", run(["--transcript", t, "--over", "5"])[0] == 0)
    ok("...and 1 under it", run(["--transcript", t, "--over", "90"])[0] == 1)
    ok("a bare --over is the hand-off line: 10k is under it", run(["--transcript", t, "--over"])[0] == 1)
    os.environ["CC_CONTEXT_HANDOFF_TOKENS"] = "10000"
    ok("...and over it once the line is moved under the reading", run(["--transcript", t, "--over"])[0] == 0)
    del os.environ["CC_CONTEXT_HANDOFF_TOKENS"]
    rc, out, err = run(["--transcript", os.path.join(cfgd, "none.jsonl"), "--over", "90"])
    ok("no transcript is exit 2 and says so", rc == 2 and out == "" and "no transcript" in err)
    rc, out, err = run(["--json", "--transcript", t])
    ok("--json carries the lines, the level and rotate", rc == 0 and json.loads(out)["handoff_line"] == 150000
       and json.loads(out)["level"] is None and json.loads(out)["rotate_line"] == 200000
       and json.loads(out)["rotate"] is False)
    ok("an address with an @ in it is refused, not answered about the caller",
       run(["repo@alias"])[0] == 2 and "not <repo>" in run(["repo@alias"])[2])

    with tempfile.TemporaryDirectory() as d:
        global STATUSLINE_DIR, DEV, WORKTREES
        sl_keep, STATUSLINE_DIR = STATUSLINE_DIR, os.path.join(d, "statusline")
        dev_keep, DEV = DEV, os.path.join(d, "dev")
        wt_keep, WORKTREES = WORKTREES, os.path.join(d, "worktrees")   # hermetic: --all's transcript fallback must not read the box's own live tracks
        os.makedirs(STATUSLINE_DIR)
        # ---- the status line's own number: preferred when fresh, ignored when stale, absent or incomplete ----
        tpath = tx([asst("claude-sonnet-5", 10, 100, 200)])          # a transcript reading nowhere near 40%
        ok("sanity: the transcript alone reads nowhere near the statusline fixture below",
           measure(tpath, "sid-sl")["pct"] < 5)
        sl_file = os.path.join(STATUSLINE_DIR, "sid-sl.json")
        with open(sl_file, "w") as fh:
            json.dump({"used": 400000, "window": 1000000, "pct": 40.0, "model": "claude-opus-5", "raw": {}}, fh)
        m = statusline_measure("sid-sl")
        ok("a fresh statusline file is preferred over the transcript estimate",
           m and m["used"] == 400000 and m["window"] == 1000000 and m["pct"] == 40.0
           and m["window_src"] == "statusline")
        rc, out, _ = run(["--transcript", tpath, "--session", "sid-sl"])
        ok("...and main() takes it, line and all: 400k is past the line",
           rc == 0 and out.startswith("40%  400k/1M") and "window from statusline" in out and "hand off" in out)
        old = time.time() - STATUSLINE_MAX_AGE - 5
        os.utime(sl_file, (old, old))
        ok("a stale statusline file is ignored — the transcript estimate takes over",
           statusline_measure("sid-sl") is None and run(["--transcript", tpath, "--session", "sid-sl"])[1].startswith("0%"))
        ok("no statusline file at all also falls back to the transcript estimate", statusline_measure("sid-none") is None)
        with open(os.path.join(STATUSLINE_DIR, "sid-partial.json"), "w") as fh:
            json.dump({"used": None, "window": None, "pct": None, "model": "claude-opus-5", "raw": {}}, fh)
        ok("a file that is there but has nothing usable yet (a session barely started) is not preferred either",
           statusline_measure("sid-partial") is None)

        # ---- --all and `cc-context <repo>`: the sessions with a status-line file, named by their cwd ----
        wt = os.path.join(d, "wt"); os.makedirs(os.path.join(wt, ".cc"))
        with open(os.path.join(wt, ".cc/track"), "w") as fh:
            fh.write("repo1\ntrack1\n")
        os.makedirs(os.path.join(DEV, "repo2"))
        def sl(sid, used, cwd, age=0):
            pth = os.path.join(STATUSLINE_DIR, sid + ".json")
            with open(pth, "w") as fh:
                json.dump({"session_id": sid, "used": used, "window": 1000000, "pct": used / 10000,
                           "model": "claude-opus-5", "raw": {"cwd": cwd}}, fh)
            if age:
                os.utime(pth, (time.time() - age, time.time() - age))
        sl("sid-t", 160000, wt)                                    # a track, past the line
        sl("sid-r", 20000, os.path.join(DEV, "repo2"), age=30)     # a session a person steers, well under it
        sl("sid-r-old", 30000, os.path.join(DEV, "repo2"), age=60)   # older in the same checkout
        sl("sid-gone", 50000, wt, age=LISTED_MAX_AGE + 60)         # a day old: not a session any more
        sl("sid-x", 70000, os.path.join(d, "elsewhere"), age=90)   # a cwd that names nothing
        os.makedirs(os.path.join(wt, "core"))
        sl("sid-sub", 40000, os.path.join(wt, "core"), age=100)    # a session standing INSIDE its worktree, not at its root
        rows = run(["--all"])[1].rstrip("\n").split("\n")
        cols = [r.split("\t") for r in rows]
        # six rows: the five above and sid-sl from the block before — stale for the 120 s rule, under a day
        ok("--all keeps its nine columns, one row per live file, newest first",
           len(cols) == 6 and all(len(c) == 9 for c in cols) and cols[0][0] == "repo1" and cols[5][3] == "400000")
        ok("a track is named repo/track off its .cc/track marker, and past the line its level says handoff",
           cols[0][:3] == ["repo1", "track1", "16"] and cols[0][5] == "statusline" and cols[0][7] == "handoff")
        ok("a checkout under ~/dev is named by its repo alone, track -, level -",
           [c[:2] for c in cols[1:3]] == [["repo2", "-"], ["repo2", "-"]] and cols[1][7] == "-")
        ok("a cwd that names nothing is still a row, with - for both", cols[3][:2] == ["-", "-"])
        ok("a cwd BELOW the worktree names its track too: the marker is found by walking up",
           cols[4][:3] == ["repo1", "track1", "4"] and cols[4][5] == "statusline")
        ok("a file over a day old is not listed", not any("sid-gone" in r or c[3] == "50000" for r, c in zip(rows, cols)))
        jrows = json.loads(run(["--all", "--json"])[1])
        ok("--all --json is the same rows as the TSV, each carrying a ts the TSV has no room for",
           len(jrows) == 6 and all(r.get("ts", "").endswith("Z") for r in jrows)
           and jrows[0]["repo"] == "repo1" and jrows[0]["level"] == "handoff" and jrows[1]["level"] is None)
        ok("`cc-context <repo>` is the NEWEST session in that checkout, not the older one beside it",
           newest_in(os.path.join(DEV, "repo2")) == "sid-r"
           and run(["repo2"])[1].startswith("2%  20k/1M"))
        # --since: the box measures a seat that carries no session id by its checkout, and a session that stopped
        # writing before that seat started is not that seat (a fresh seat rotated on a dead 300k one, review of #552)
        ok("--since keeps a session that has written since it: 30 s ago is inside a 45 s bound",
           newest_in(os.path.join(DEV, "repo2"), time.time() - 45) == "sid-r"
           and run(["repo2", "--since", str(int(time.time() - 45))])[1].startswith("2%  20k/1M"))
        ok("--since drops every session that stopped writing before it: the checkout reads as no transcript, exit 2",
           newest_in(os.path.join(DEV, "repo2"), time.time() + 5) is None
           and run(["repo2", "--since", str(int(time.time() + 5))])[0] == 2)
        ok("--since without an epoch is refused, not read as a session",
           run(["repo2", "--since"])[0] == 2 and run(["repo2", "--since", "now"])[0] == 2)
        ok("...and a checkout nothing has written under is 'no transcript', exit 2",
           run(["repo3"])[0] == 2)
        STATUSLINE_DIR, DEV, WORKTREES = sl_keep, dev_keep, wt_keep

    if env0 is not None:
        os.environ["CC_CTX_WINDOW"] = env0
    if sid0 is not None:
        os.environ["CLAUDE_CODE_SESSION_ID"] = sid0
    if cfg0 is None:
        os.environ.pop("CC_CONFIG", None)
    else:
        os.environ["CC_CONFIG"] = cfg0
    shutil.rmtree(cfgd, ignore_errors=True)
    if hl0 is not None:
        os.environ["CC_CONTEXT_HANDOFF_TOKENS"] = hl0
    if box0 is None:
        os.environ.pop("CC_CTX_BOX_MODEL", None)
    else:
        os.environ["CC_CTX_BOX_MODEL"] = box0

    print(f"cc-context selfcheck: {p} passed, {f} failed")
    return 1 if f else 0
