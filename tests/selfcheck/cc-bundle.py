# cc-bundle's selfcheck: the cases behind `cc-bundle selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-bundle execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

# ── selfcheck ────────────────────────────────────────────────────────────────────────────────────────────────
def selfcheck():
    import contextlib, io, shutil, tempfile
    global BIN
    p = f = 0

    def ok(name, cond):
        nonlocal p, f
        print(("ok   " if cond else "FAIL ") + name)
        p, f = p + (1 if cond else 0), f + (0 if cond else 1)

    tmp = tempfile.mkdtemp(prefix="cc-bundle-sc.")
    fake_home = os.path.join(tmp, "home")
    boards, state = os.path.join(fake_home, ".cc", "boards"), os.path.join(fake_home, ".cc", "state")
    os.makedirs(boards); os.makedirs(os.path.join(state, "land"))
    # cc-brief and cc-board both read their homes at import: point them here BEFORE the first import.
    os.environ.update(HOME=fake_home, CC_BOARDS=boards, CC_STATE=state)
    os.environ.pop("CC_BUNDLE_WIDTH", None)
    B = brief_mod()
    repo = "beta"
    src = os.path.join(tmp, "src")

    def git(*args):
        return subprocess.run(["git", "-C", src, *args], capture_output=True, text=True,
                              env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})

    subprocess.run(["git", "init", "-q", "-b", "main", src], capture_output=True)
    os.makedirs(os.path.join(src, "bin")); os.makedirs(os.path.join(src, "tests"))
    for fn in ("bin/cc-slackx", "bin/cc-guardx", "bin/other-tool", "notes.txt"):
        open(os.path.join(src, fn), "w").write("base\n")
    open(os.path.join(src, "tests", "control-layer"), "w").write("# the gate\nbin/cc-guardx\n")
    git("add", "-A"); git("commit", "-qm", "base")
    git("checkout", "-q", "-b", "track/live", "main")
    open(os.path.join(src, "notes.txt"), "a").write("live\n")
    git("add", "-A"); git("commit", "-qm", "live"); git("checkout", "-q", "main")

    def board(tracks):
        with open(os.path.join(boards, repo + ".json"), "w") as fh:
            json.dump({"repo": repo, "path": src, "default_branch": "main", "tracks": tracks, "log": []}, fh)

    def brief_of(track, text):
        d = os.path.join(state, repo, track)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "task.md"), "w").write(text)

    # ── the siblings, stubbed: `cc` records its argv; cc-tier and cc-limit answer what the case sets.
    fbin = os.path.join(tmp, "bin")
    os.makedirs(fbin)
    calls = os.path.join(tmp, "calls")
    open(os.path.join(fbin, "cc"), "w").write(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALLS\"\nexit \"${CC_FAKE_CC_RC:-0}\"\n")
    open(os.path.join(fbin, "cc-tier"), "w").write("#!/bin/sh\nexit \"${CC_FAKE_TIER_RC:-0}\"\n")
    open(os.path.join(fbin, "cc-pause"), "w").write("#!/bin/sh\nexit \"${CC_FAKE_PAUSE_RC:-1}\"\n")
    open(os.path.join(fbin, "cc-limit"), "w").write(
        "#!/bin/sh\n[ -n \"$CC_FAKE_LIMIT\" ] && { echo \"$CC_FAKE_LIMIT\"; exit 0; }\nexit 1\n")
    for t in ("cc-board", "cc-brief"):      # the real ones, beside this copy
        os.symlink(os.path.join(os.path.dirname(os.path.realpath(__file__)), t), os.path.join(fbin, t))
    for fn in os.listdir(fbin):
        os.chmod(os.path.join(fbin, fn), 0o755)
    os.environ["CALLS"] = calls
    BIN = fbin

    def calls_made():
        try:
            return open(calls).read().splitlines()
        except OSError:
            return []

    # ── what a bundle is
    board({"row-a": {"status": "queued", "title": "a is wrong"}, "row-b": {"status": "queued", "title": "b too"},
           "row-c": {"status": "queued", "title": "c stands alone"}, "row-d": {"status": "queued"},
           "row-e": {"status": "queued"}})
    brief_of("row-a", "GOAL: bin/cc-slackx says the wrong thing.\n")
    brief_of("row-b", "GOAL: bin/cc-slackx says another wrong thing.\n")
    brief_of("row-c", "GOAL: notes.txt on its own.\n")
    brief_of("row-d", "GOAL: bin/cc-guardx refuses a thing, and bin/other-tool with it.\n")
    brief_of("row-e", "GOAL: bin/other-tool prints the wrong line.\n")
    bs = bundles(repo)
    ok("two queued rows naming one file are a bundle, and a row sharing nothing is not in any",
       bs is not None and [b["rows"] for b in bs] == [["row-a", "row-b"], ["row-d", "row-e"]])
    one = next(b for b in bs if b["rows"] == ["row-a", "row-b"])
    ok("a bundle on one file outside the control layer runs on Sonnet", one["model"] == "sonnet")
    two = next(b for b in bs if b["rows"] == ["row-d", "row-e"])
    ok("…and one that names a control-layer file, or more than one file, runs on Opus", two["model"] == "opus")
    ok("the name carries the shared file and a hash of the member set", re.fullmatch(r"bundle-cc-slackx-[0-9a-f]{4}", one["name"]) is not None
       and bundle_name(["bin/cc-slackx"], ["row-a", "row-b"]) == one["name"] and bundle_name(["bin/cc-slackx"], ["row-a", "x"]) != one["name"])
    ok("the shared files and everything the members name are both reported",
       one["files"] == ["bin/cc-slackx"] and two["named"] == ["bin/cc-guardx", "bin/other-tool"])

    text = compose(repo, one)
    ok("the composed brief closes every member, so the bundle's PR closes them all when it lands",
       "Closes row-a and row-b." in text)
    ok("…and carries each member's brief verbatim under its own heading",
       "## row-a — a is wrong" in text and "bin/cc-slackx says another wrong thing" in text)
    ok("…and says what a raised- section is, for the worker", "account of what broke" in text)

    # ── A ROW JOINS ON A FILE ITS BRIEF NAMES AS THE FIX, NOT ON ONE ITS STORY MENTIONS. A raised- row's account
    # names the tool that printed the wrong thing; a bundle made of such rows shares a cast and no fix, and the
    # judge refuses it (2026-09-13). The story row here mentions the bundle's file and nothing else, the aside row
    # mentions it AND says its fix goes elsewhere: neither is a member.
    board({"row-a": {"status": "queued"}, "row-b": {"status": "queued"},
           "story": {"status": "queued"}, "aside": {"status": "queued"}})
    brief_of("story", "WHAT BROKE: 02:1xZ, bin/cc-slackx printed nothing and the seat read that as empty.\n"
                      "WHAT IT COST: a turn, and a wrong answer acted on.\n")
    brief_of("aside", "WHAT BROKE: bin/cc-slackx printed the wrong line.\nThe fix goes in notes.txt.\n")
    bs = bundles(repo)
    ok("A ROW WHOSE ACCOUNT MERELY NAMES THE TOOL IS NOT A MEMBER of the bundle on that tool — the join is the fix",
       [b["rows"] for b in bs] == [["row-a", "row-b"]])
    ok("…and neither is a row whose story names it while its fix goes elsewhere",
       all("aside" not in b["rows"] for b in bs))

    board({"row-a": {"status": "queued"}, "row-b": {"status": "queued"}, "proj": {"status": "queued"}})
    brief_of("proj", "GOAL: a knowledge library.\nM1: bin/cc-slackx learns to write to it.\nM2: the rest.\n")
    ok("a project row — a brief with milestones — stays whole: dropped from the group it would join",
       [b["rows"] for b in bundles(repo)] == [["row-a", "row-b"]])
    board({"row-a": {"status": "queued"}, "proj": {"status": "queued"}})
    ok("…and a group left with one row is no bundle", bundles(repo) == [])
    board({"row-a": {"status": "queued"}, "row-d": {"status": "queued"}, "proj": {"status": "queued"}})
    brief_of("proj", "GOAL: a library.\nM1: bin/cc-slackx writes to it.\nM2: bin/cc-guardx reads it.\n")
    ok("…and a project row that was the only link between two rows sharing nothing leaves no bundle behind",
       bundles(repo) == [])
    board({"row-a": {"status": "queued"}, "row-b": {"status": "queued"}, "proj": {"status": "queued"}})
    brief_of("proj", "GOAL: a loop.\nSHAPE PROPOSED (the orch decides): M1 the scorer on bin/cc-slackx, M2 the loop.\n")
    ok("a brief numbering its milestones mid-line (M1 … M2, no line of their own) is a project row too",
       [b["rows"] for b in bundles(repo)] == [["row-a", "row-b"]])
    brief_of("proj", "GOAL: bin/cc-slackx, plainly.\n")
    ok("…and the same row with a plain brief is a member", [b["rows"] for b in bundles(repo)] == [["proj", "row-a", "row-b"]])
    board({"row-a": {"status": "queued"}, "row-b": {"status": "queued"},
           "proj": {"status": "queued", "agent": "@1:2", "agent_at": "2020-01-01T00:00:00Z"}})
    ok("a row whose agent mark went cold is offered by `ready`, and is no member here: nobody handed it back",
       [b["rows"] for b in bundles(repo)] == [["row-a", "row-b"]])
    board({"row-a": {"status": "queued"}, "row-b": {"status": "queued"},
           "proj": {"status": "queued", "agent": "@1:2", "agent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}})
    ok("…nor is one whose mark is warm", [b["rows"] for b in bundles(repo)] == [["row-a", "row-b"]])
    board({"row-a": {"status": "queued"}, "row-b": {"status": "queued"}, "proj": {"status": "queued", "agent": "", "agent_at": ""}})
    ok("…and a row handed back (`agent \"\"`) is a member again", [b["rows"] for b in bundles(repo)] == [["proj", "row-a", "row-b"]])

    # ── the caps: a group over one is split on the file its rows most share, and what it leaves waits
    rows = {f"r{i}": {"status": "queued"} for i in range(1, 8)}
    rows.update({"glue": {"status": "queued"}, "s1": {"status": "queued"}, "s2": {"status": "queued"}})
    board(rows)
    for i in range(1, 8):
        brief_of(f"r{i}", f"GOAL: bin/other-tool prints line {i} wrong.\n")
    brief_of("glue", "GOAL: bin/other-tool and bin/cc-slackx disagree.\n")
    brief_of("s1", "GOAL: bin/cc-slackx, one thing.\n"); brief_of("s2", "GOAL: bin/cc-slackx, another.\n")
    bs = bundles(repo)
    ok("ten rows one broad row glues are not one bundle: the file most of them share takes ROWS_MAX of them, the "
       "rest are grouped again on their own",
       [b["rows"] for b in bs] == [["r1", "r2", "r3", "r4", "r5", "r6"], ["s1", "s2"]])
    ok("…the rows left over that name a file it names wait behind it, the broad one among them",
       bs[0]["waits"] == ["glue", "r7"] and bs[1]["waits"] == [])
    ok("…and bundles offered together name no file in common", not (set(bs[0]["named"]) & set(bs[1]["named"])))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show(repo)
    ok("…and `show` says which rows wait", "2 wait behind it (they name a file it names): glue, r7" in buf.getvalue())
    board({f"r{i}": {"status": "queued"} for i in range(1, 7)})
    bs = bundles(repo)
    ok("a group at the cap is offered whole", [b["rows"] for b in bs] == [["r1", "r2", "r3", "r4", "r5", "r6"]] and bs[0]["waits"] == [])
    # …and the wait holds ACROSS ticks, not only inside the one that computed it (review of #478): the dispatched
    # bundle's members leave `ready`, and its row holds no files until the worker commits, so the rows that waited
    # would have grouped again on the same file at the next tick and started a second worker in it.
    board(rows)
    open(calls, "w").close()
    went = go(repo, out=io.StringIO())
    tr = B.board_of(repo).get("tracks") or {}
    first = bundle_name(["bin/other-tool"], [f"r{i}" for i in range(1, 7)])
    ok("go starts the first bundle of a split and marks its members",
       went == first and all(tr[f"r{i}"].get("bundle") == first for i in range(1, 7)))

    def edit(fn):
        pth = os.path.join(boards, repo + ".json")
        with open(pth) as fh:
            dd = json.load(fh)
        fn(dd["tracks"])
        with open(pth, "w") as fh:
            json.dump(dd, fh)
    ok("…and while its row is live with no commit, the rows that waited are still no bundle, the rest still are",
       [b["rows"] for b in bundles(repo)] == [["s1", "s2"]])
    edit(lambda t: t[first].update(status="running"))
    ok("…the same once it is running", [b["rows"] for b in bundles(repo)] == [["s1", "s2"]])

    def landed(t):
        t[first].update(status="done")
        for i in range(1, 7):
            t[f"r{i}"].update(status="done")
    edit(landed)
    ok("…and once it has landed, they are grouped again", [b["rows"] for b in bundles(repo)] == [["glue", "r7", "s1", "s2"]])
    open(calls, "w").close()
    os.environ["CC_BUNDLE_FILES"] = "2"
    board({"f1": {"status": "queued"}, "f2": {"status": "queued"}, "f3": {"status": "queued"}})
    brief_of("f1", "GOAL: bin/other-tool and notes.txt.\n")
    brief_of("f2", "GOAL: bin/other-tool and bin/cc-guardx.\n")
    brief_of("f3", "GOAL: bin/other-tool alone.\n")
    ok("the files cap (here CC_BUNDLE_FILES=2) splits the same way: the narrowest rows fill it, the one that would "
       "widen it waits", [(b["rows"], b["named"], b["waits"]) for b in bundles(repo)]
       == [(["f1", "f3"], ["bin/other-tool", "notes.txt"], ["f2"])])
    board({"p": {"status": "queued"}, "q": {"status": "queued"}, "s1": {"status": "queued"}, "s2": {"status": "queued"}})
    brief_of("p", "GOAL: bin/other-tool, notes.txt and bin/cc-guardx.\n")
    brief_of("q", "GOAL: bin/other-tool, notes.txt and tests/control-layer.\n")
    ok("…and a pair too wide for it on its own is no bundle — the seat's — and costs the rows beside it nothing",
       [b["rows"] for b in bundles(repo)] == [["s1", "s2"]])
    os.environ.pop("CC_BUNDLE_FILES")

    board({"row-a": {"status": "queued"}, "row-b": {"status": "queued"},
           "live": {"status": "review", "branch": "track/live", "pr": "1"}})
    brief_of("row-a", "GOAL: notes.txt is held by the live row.\n")
    brief_of("row-b", "GOAL: notes.txt as well.\n")
    ok("rows sharing a file a live track holds are not offered — `ready` calls neither free", bundles(repo) == [])
    brief_of("row-a", "GOAL: bin/cc-slackx says the wrong thing.\n")
    brief_of("row-b", "GOAL: bin/cc-slackx says another wrong thing.\n")
    board({"row-a": {"status": "queued"}, "died": {"status": "blocked", "pr": "7", "branch": "track/live"}})
    brief_of("died", "GOAL: bin/cc-slackx, whose landing died with the PR open.\n")
    ok("a blocked row with a PR — a landing that died — is in flight, not a member: no bundle with the queued row",
       bundles(repo) == [])
    board({"row-a": {"status": "queued"}, "row-b": {"status": "queued", "pr": "8"}})
    ok("…nor is a queued row that already carries a PR", bundles(repo) == [])
    board({"row-a": {"status": "queued"}, "row-b": {"status": "blocked"}})
    ok("…nor a blocked row without one: only `queued` rows are members", bundles(repo) == [])

    # ── the holds, each on its own fixture, and the dispatch
    board({"row-a": {"status": "queued", "title": "a is wrong"}, "row-b": {"status": "queued", "title": "b too"}})
    for i in range(QUEUE_HOLD):
        open(os.path.join(state, "land", f"x-{i}.json"), "w").write(json.dumps({"repo": "x", "pr": str(i)}))
    os.environ["CC_FAKE_PAUSE_RC"] = "0"
    ok("a parked project holds it before anything else, and says so",
       holds(repo, B.board_of(repo)) == "the project is paused (cc-pause)")
    went = go(repo, out=io.StringIO())
    tr = B.board_of(repo).get("tracks") or {}
    ok("…and `go` on a parked project adds no row, marks no member and starts nothing — the board is untouched",
       went == "" and sorted(tr) == ["row-a", "row-b"] and not any(tr[k].get("bundle") for k in tr)
       and calls_made() == [])
    os.environ.pop("CC_FAKE_PAUSE_RC")
    try:
        os.remove(log_path(repo))   # the hold it logged; the queue cases below count their own lines
    except OSError:
        pass
    ok("the landing queue at the hold stops a dispatch, and says so", "landing queue holds 4" in holds(repo, B.board_of(repo)))
    os.remove(os.path.join(state, "land", "x-0.json"))
    ok("…and one job under it does not", holds(repo, B.board_of(repo)) == "")
    os.environ["CC_FAKE_TIER_RC"] = "1"
    ok("the spend tier holds it", "spend tier" in holds(repo, B.board_of(repo)))
    os.environ.pop("CC_FAKE_TIER_RC")
    os.environ["CC_FAKE_LIMIT"] = "usage limit until 18:00"
    ok("a box-wide usage limit holds it", "usage limit" in holds(repo, B.board_of(repo)))
    os.environ["CC_FAKE_LIMIT"] = "usage limit until 18:00 (this run only)"
    ok("…but one run's own limit is not the box's", holds(repo, B.board_of(repo)) == "")
    os.environ.pop("CC_FAKE_LIMIT")
    board({"row-a": {"status": "queued"}, "row-b": {"status": "queued"}, "bundle-p-0000": {"status": "running"},
           "bundle-q-0000": {"status": "queued"}})
    ok("two bundles already live is the width, and a third waits", "2 bundles already live" in holds(repo, B.board_of(repo)))
    os.environ["CC_BUNDLE_WIDTH"] = "3"
    ok("…and CC_BUNDLE_WIDTH widens it", holds(repo, B.board_of(repo)) == "")
    os.environ.pop("CC_BUNDLE_WIDTH")

    board({"row-a": {"status": "queued", "title": "a is wrong"}, "row-b": {"status": "queued", "title": "b too"}})
    for i in range(QUEUE_HOLD):
        open(os.path.join(state, "land", f"x-{i}.json"), "w").write(json.dumps({"repo": "x", "pr": str(i)}))
    go(repo, dry=True, out=io.StringIO())
    ok("a dry run under a hold writes nothing", not os.path.exists(log_path(repo)))
    go(repo, out=io.StringIO()); go(repo, out=io.StringIO())
    ok("a hold is logged once, not once per tick while it stands",
       [json.loads(l)["event"] for l in open(log_path(repo))] == ["held"])
    for i in range(QUEUE_HOLD):
        os.remove(os.path.join(state, "land", f"x-{i}.json"))
    os.remove(log_path(repo))
    buf = io.StringIO()
    went = go(repo, dry=True, out=buf)
    ok("--dry-run names the bundle and the model and starts nothing",
       went == one["name"] and "would start bundle-cc-slackx" in buf.getvalue() and "sonnet" in buf.getvalue()
       and calls_made() == [] and one["name"] not in (B.board_of(repo).get("tracks") or {}))
    buf = io.StringIO()
    went = go(repo, out=buf)
    tr = B.board_of(repo).get("tracks") or {}
    ok("go adds the bundle row through cc-board add, with the composed brief as its task",
       went == one["name"] and one["name"] in tr and "Closes row-a and row-b." in B.brief_text(repo, one["name"]))
    ok("…marks every member `bundle: <row>` and leaves it queued",
       all(tr[k].get("bundle") == one["name"] and tr[k].get("status") == "queued" for k in ("row-a", "row-b")))
    ok("…starts the worker with `cc <repo> <row> --go \"\"` on the band's model, --loop 3",
       calls_made() == [f"{repo} {one['name']} --go  --loop 3 --model claude-sonnet-5"])
    ok("…logs the dispatch", any(json.loads(l)["event"] == "dispatched" for l in open(log_path(repo))))
    ok("…and the members are out of the pool while the bundle row is live: nothing to run now",
       bundles(repo) == [] and set(B.candidates(B.board_of(repo))) == {one["name"]})
    buf = io.StringIO()
    ok("a second go starts nothing and prints nothing", go(repo, out=buf) == "" and buf.getvalue() == "")

    # …a bundle row that already exists is not added twice, whatever its status
    board({"row-a": {"status": "queued"}, "row-b": {"status": "queued"}, one["name"]: {"status": "blocked"}})
    open(calls, "w").close()
    ok("a bundle whose row already exists (here blocked) is left to the seat, not re-added or re-started",
       go(repo, out=io.StringIO()) == "" and calls_made() == [])

    # …and a refusal at the door is recorded and not retried inside the window. The door is cc-board add and the
    # refusal is the brief's SHAPE: a member whose brief is a list of edits makes the composed brief one too.
    os.remove(log_path(repo))
    board({"row-a": {"status": "queued", "title": "row-a"}, "row-b": {"status": "queued", "title": "row-b"}})
    brief_of("row-a", "FILES: bin/cc-slackx\nDo this:\n- Add a --flag to bin/cc-slackx\n- Edit bin/cc-slackx to pass it "
                      "through\n- Run the suite\n")
    buf = io.StringIO()
    went = go(repo, out=buf)
    tr = B.board_of(repo).get("tracks") or {}
    ok("a shape refusal at cc-board add stops the bundle: no row, no marks, no worker, said and logged",
       went == "" and "refused at the door" in buf.getvalue() and one["name"] not in tr
       and not tr["row-a"].get("bundle") and calls_made() == [] and one["name"] in refused_recently(repo))
    brief_of("row-a", "GOAL: bin/cc-slackx says the wrong thing.\n")
    ok("…and the same set is not offered again inside the window",
       go(repo, dry=True, out=io.StringIO()) == "")
    os.remove(log_path(repo))

    # …and `cc` refusing the launch (a paused project, the tier at the row) leaves the row for the seat
    board({"row-a": {"status": "queued", "title": "row-a"}, "row-b": {"status": "queued", "title": "row-b"}})
    os.environ["CC_FAKE_CC_RC"] = "1"
    buf = io.StringIO()
    went = go(repo, out=buf)
    ok("`cc --go` refusing leaves the added row and its marks for the seat, and logs the refusal",
       went == "" and "added but not started" in buf.getvalue()
       and any(json.loads(l)["event"] == "refused" for l in open(log_path(repo))))
    os.environ.pop("CC_FAKE_CC_RC")

    # ── show
    os.remove(log_path(repo))
    board({"row-a": {"status": "queued", "title": "row-a"}, "row-b": {"status": "queued", "title": "row-b"}})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show(repo)
    ok("show prints each bundle with its model, files and rows",
       "1 bundle the box would run" in buf.getvalue() and f"{one['name']} [sonnet] bin/cc-slackx: row-a, row-b" in buf.getvalue())
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show(repo, as_json=True)
    ok("…and --json is the same answer as data", json.loads(buf.getvalue())[0]["rows"] == ["row-a", "row-b"])
    for i in range(QUEUE_HOLD):
        open(os.path.join(state, "land", f"x-{i}.json"), "w").write(json.dumps({"repo": "x", "pr": str(i)}))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show(repo)
    ok("…and names what holds them", "held: the landing queue holds 4" in buf.getvalue())
    board({"row-c": {"status": "queued"}})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show(repo)
    ok("nothing to run prints nothing", buf.getvalue() == "")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\ncc-bundle selfcheck: {p} passed, {f} failed")
    return 1 if f else 0
