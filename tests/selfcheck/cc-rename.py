# cc-rename's selfcheck: the cases behind `cc-rename selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-rename execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

# ---------------------------------------------------------------------------- selfcheck
def selfcheck():
    """Every case builds a WHOLE fixture box of its own — its own HOME, its own bin/, its own git
    repository and worktree, its own Slack — so none of them reads state another one left behind, and
    none of them touches this box. Nothing here reaches Slack: `API` is the deny that records, and a
    case that wants an answer installs its own and puts the deny back."""
    import tempfile
    n = [0]
    fails = []

    def t(name, got, want):
        n[0] += 1
        if got == want:
            return
        fails.append(name)
        print(f"FAIL {name}: got {got!r}, want {want!r}")

    real_home, real_bin, real_path, real_api = os.environ.get("HOME"), BIN, os.environ["PATH"], API
    real_pane = os.environ.get("TMUX_PANE")
    root = tempfile.mkdtemp(prefix="cc-rename-selfcheck-")
    # The fixture project carries this process's pid: `cwd_holders` reads the real /proc, and two
    # suites running at once must never see each other's fixture as their own project.
    OLD, NEW = f"myrepo-{os.getpid()}", f"newrepo-{os.getpid()}"

    def box(label):
        """A whole box: a git repository with one linked worktree, a state dir, a board, an ask ledger,
        a config, a Slack directory and a bin/ of stubs. Returns its HOME, already installed."""
        h = f"{root}/{label}"
        fb = f"{h}/bin"
        os.makedirs(fb)
        os.environ["HOME"] = h
        globals()["BIN"] = fb
        os.environ["PATH"] = fb + os.pathsep + real_path
        for tool in ("cc-config", "cc-board", "cc-trust"):     # the real readers, over this box's own files
            shutil.copy(f"{real_bin}/{tool}", f"{fb}/{tool}")
        for tool, body in (("cc-reconcile", 'exit 0\n'),       # never a real reconcile pass
                           ("cc-loop", 'sleep 60\n'),           # a case runs this one to BE a worker
                           ("cc", 'IFS="|"; printf "%s\\n" "$*" >> "$HOME/cc.calls"\n')):
            open(f"{fb}/{tool}", "w").write("#!/bin/sh\n" + body)
            os.chmod(f"{fb}/{tool}", 0o755)
        # tmux and pgrep, stubbed: no window of this box is listed, renamed or killed.
        open(f"{fb}/tmux", "w").write(
            '#!/bin/sh\ncase "$1" in\n'
            '  list-windows) cat "$HOME/tmux.windows" 2>/dev/null;;\n'
            '  list-panes) case "$2" in\n'
            '                -a) cat "$HOME/tmux.allpanes" 2>/dev/null;;\n'    # pane -> window, for own_window
            '                 *) cat "$HOME/tmux.panes" 2>/dev/null;;\n'       # what is running in one window
            '              esac;;\n'
            '  rename-window) printf "rename %s %s\\n" "$3" "$4" >> "$HOME/tmux.calls";;\n'
            '  kill-window) printf "kill %s\\n" "$3" >> "$HOME/tmux.calls"; : > "$HOME/tmux.panes";;\n'
            'esac\nexit 0\n')
        open(f"{fb}/pgrep", "w").write('#!/bin/sh\n[ -s "$HOME/tmux.panes" ]\n')
        for tool in ("tmux", "pgrep"):
            os.chmod(f"{fb}/{tool}", 0o755)
        # Four windows: this project's planning session and its track, a project whose name merely
        # begins with this one's, and a stranger. `tmux.panes` empty means nothing is running in any
        # of them, so the box is not live until a case says it is.
        open(f"{h}/tmux.windows", "w").write(
            f"@1\t{OLD}\n@2\t{OLD}/t1\n@3\t{OLD}-skill\n@4\tother\n@5\t{OLD}/t2\n")
        open(f"{h}/tmux.panes", "w").write("")
        # …and which window each pane is in, so a case can say which one this rename is running in.
        open(f"{h}/tmux.allpanes", "w").write("%1\t@1\n%2\t@2\n%3\t@3\n%4\t@4\n%5\t@5\n")
        os.environ.pop("TMUX_PANE", None)   # the suite itself runs in tmux; a case says where it is, or nowhere
        os.makedirs(f"{h}/.cc/slack")
        os.makedirs(f"{h}/.cc/scope")
        os.makedirs(f"{state()}/{OLD}/t1")
        os.makedirs(boards())
        git(f"{h}/dev/{OLD}", "init", "-q", make=True)
        git(f"{h}/dev/{OLD}", "commit", "-q", "--allow-empty", "-m", "root")
        for tr in ("t1", "t2"):
            git(f"{h}/dev/{OLD}", "worktree", "add", "-q", f"{worktrees()}/{OLD}/{tr}", "-b", f"track/{tr}")
            os.makedirs(f"{worktrees()}/{OLD}/{tr}/.cc")
            # t1 carries a task id on the marker's third line (cc-task), t2 the two-line marker cc has always
            # written: a rename must keep the first and leave the second exactly two lines.
            tail = "b1f0c4e2-0000-4000-8000-00000000t1ab\n" if tr == "t1" else ""
            open(f"{worktrees()}/{OLD}/{tr}/.cc/track", "w").write(f"{OLD}\n{tr}\n{tail}")
            os.makedirs(f"{state()}/{OLD}/{tr}", exist_ok=True)
        open(f"{state()}/{OLD}/goals.md", "w").write("# standing goals\n")
        open(f"{state()}/{OLD}/t1/progress.md", "w").write("the journal\n")
        open(f"{boards()}/{OLD}.json", "w").write(json.dumps(
            {"repo": OLD, "path": f"{h}/dev/{OLD}", "default_branch": "main", "created": "2026-01-01T00:00:00Z",
             "tracks": {tr: {"title": "a track", "status": "running", "branch": f"track/{tr}",
                             "worktree": f"{worktrees()}/{OLD}/{tr}"} for tr in ("t1", "t2")}, "log": []}))
        open(f"{h}/.cc/scope/{OLD}.json", "w").write(json.dumps({"repo": OLD, "asks": []}))
        open(f"{slack_dir()}/routes.json", "w").write(json.dumps({f"#{OLD}-threads": OLD, "C9": f"{OLD}/t1"}))
        open(f"{slack_dir()}/channels.json", "w").write(json.dumps({OLD: "CM", "_t": 0}))
        # The harness's transcript directories, and cc-spend's read offsets — keyed by each transcript's
        # FULL PATH, which is inside one of them, plus one belonging to a directory that does not move.
        os.makedirs(f"{h}/.claude/projects")
        offs = {"/elsewhere/a-project/s.jsonl": {"off": 7, "ino": 2, "rid": "req_y"}}
        for d in (f"{h}/dev/{OLD}", f"{worktrees()}/{OLD}/t1"):
            pd = f"{h}/.claude/projects/{proj_slug(d)}"
            os.makedirs(pd)
            open(f"{pd}/s.jsonl", "w").write("{}\n")
            offs[f"{pd}/s.jsonl"] = {"off": 4242, "ino": 1, "rid": "req_x"}
        os.makedirs(f"{state()}/spend")
        open(f"{state()}/spend/offsets.json", "w").write(json.dumps(
            {"tick": "2026-01-01T00:00:00Z", "files": offs, "grew": {}, "sub_rids": {}}))
        # The broker's three tables and the handoff records — both keyed by TARGET, `<repo>` or
        # `<repo>/<track>`, and both carrying a project that merely begins with this one's letters.
        os.makedirs(f"{h}/.cc/broker")
        for tbl, val in (("pending.json", {}), ("told.json", {}), ("read.json", 0)):
            open(f"{h}/.cc/broker/{tbl}", "w").write(json.dumps(
                {OLD: val, f"{OLD}/t1": val, f"{OLD}-skill": val, "other": val}))
        os.makedirs(f"{state()}/handoff")
        for nm, rec in ((f"{OLD}.json", {"id": "h1", "target": OLD}),
                        (f"{OLD}--t1.json", {"id": "h2", "target": f"{OLD}/t1"}),
                        (f"{OLD}-skill.json", {"id": "h3", "target": f"{OLD}-skill"}),
                        ("abc123.done", {"id": "abc123", "target": f"{OLD}/t2"})):
            open(f"{state()}/handoff/{nm}", "w").write(json.dumps(rec))
        open(f"{state()}/handoff/{OLD}--t1.brief", "w").write("what the successor is to pick up\n")
        open(f"{h}/.cc/config", "w").write(
            f"SLACK_BOT_TOKEN=xoxb-selfcheck\nCC_JANITOR_REPOS={OLD} other\n"
            f"CC_SELF_LAND_EXCEPT=other {OLD}\nCC_PROJECT_CHILDREN={OLD}:tool\nPUBLISH_REPO={OLD}\n")
        for k in CONFIG_LISTS + ("CC_PROJECT_CHILDREN", "PUBLISH_REPO"):   # cc-config lets the environment win over
            os.environ.pop(k, None)                                           # the file: a caller's value is not this fixture's
        return h

    def git(d, *args, make=False):
        if make:
            os.makedirs(d, exist_ok=True)
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=cc", "-c",
                        "user.email=cc@example.invalid", "-c", "init.defaultBranch=main", "-C", d] + list(args),
                       capture_output=True, stdin=subprocess.DEVNULL, timeout=60)

    # The channels this fixture's workspace has. `<OLD>-skill` is a project of its own and must come
    # through a rename of <OLD> untouched — cc-slack's own selfcheck pins that same trap.
    def chans(h):
        return [("CM", OLD), ("CMU", f"{OLD}-updates"), ("CMT", f"{OLD}--t1"),
                ("CSK", f"{OLD}-skill"), ("CO", "other")]

    def slack(h, calls):
        """An API that answers a list and writes down every rename, and refuses anything else."""
        def fake(method, token, **kw):
            if method == "conversations.list":
                return {"channels": [{"id": c, "name": nm} for c, nm in chans(h)]}
            if method == "conversations.rename":
                calls.append((kw["channel"], kw["name"]))
                return {"ok": True}
            return deny_slack(method, token, **kw)
        return fake

    def run(*argv):
        """The command, as `cc rename` runs it, with its output captured so the tally stays readable."""
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(list(argv))
        return rc, buf.getvalue()

    def board_of(repo):
        r = subprocess.run([f"{BIN}/cc-board", "json", repo], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=30)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {}

    def cfg(h, key):
        r = subprocess.run([f"{BIN}/cc-config", "get", key], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=30)
        return r.stdout.strip()

    try:
        globals()["API"] = deny_slack
        # ------------------------------------------------------------------ end to end
        h = box("roundtrip")
        calls = []
        globals()["API"] = slack(h, calls)
        rc, out = run(OLD, NEW)
        t("a whole project renames, and says so", rc, 0)
        t("…the checkout moves", (os.path.isdir(f"{h}/dev/{NEW}"), os.path.exists(f"{h}/dev/{OLD}")), (True, False))
        t("…the worktree moves", os.path.isdir(f"{worktrees()}/{NEW}/t1"), True)
        t("…and git still owns it there: the worktree's .git and the repository's gitdir both moved",
          subprocess.run(["git", "-C", f"{worktrees()}/{NEW}/t1", "status", "--porcelain"],
                         capture_output=True, stdin=subprocess.DEVNULL, timeout=60).returncode, 0)
        t("…the worktree says which project it is, and keeps the task id a claim put on its third line",
          open(f"{worktrees()}/{NEW}/t1/.cc/track").read(),
          f"{NEW}\nt1\nb1f0c4e2-0000-4000-8000-00000000t1ab\n")
        t("…while a marker that never had one still has exactly two lines",
          open(f"{worktrees()}/{NEW}/t2/.cc/track").read(), f"{NEW}\nt2\n")
        t("…the state dir moves, journals and all", open(f"{state()}/{NEW}/t1/progress.md").read(), "the journal\n")
        b = board_of(NEW)
        t("…and the board's own reader finds it under the new name, with the paths inside it moved too",
          (b.get("repo"), b.get("path"), sorted(r["worktree"] for r in (b.get("tracks") or {}).values())),
          (NEW, f"{h}/dev/{NEW}", [f"{worktrees()}/{NEW}/t1", f"{worktrees()}/{NEW}/t2"]))
        t("…the ask ledger moves, and says the new repo", read_json(f"{h}/.cc/scope/{NEW}.json", {}).get("repo"), NEW)
        t("…every config key that names projects follows, and the others in the list are left alone",
          (cfg(h, "CC_JANITOR_REPOS"), cfg(h, "CC_SELF_LAND_EXCEPT"), cfg(h, "CC_PROJECT_CHILDREN"), cfg(h, "PUBLISH_REPO")),
          (f"{NEW} other", f"other {NEW}", f"{NEW}:tool", NEW))
        t("…the project's three channels are renamed IN PLACE — and not #<old>-skill, which is a "
          "project of its own, nor a stranger's channel",
          sorted(calls), sorted([("CM", NEW), ("CMU", f"{NEW}-updates"), ("CMT", f"{NEW}--t1")]))
        t("…a route to a channel this rename did NOT rename still points at the project, under its new name",
          read_json(f"{slack_dir()}/routes.json", {}), {f"#{OLD}-threads": NEW, "C9": f"{NEW}/t1"})
        t("…the name->id cache is dropped, so the old names stop resolving",
          os.path.exists(f"{slack_dir()}/channels.json"), False)
        t("…and this project's windows are renamed, the other two left where they are",
          sorted(open(f"{h}/tmux.calls").read().split("\n")[:-1]),
          sorted([f"rename @1 {NEW}", f"rename @2 {NEW}/t1", f"rename @5 {NEW}/t2"]))
        t("…the broker's tables follow by TARGET — the planning session's key AND each track's — and a "
          "project whose name merely begins with this one's keeps its own",
          [sorted(read_json(f"{h}/.cc/broker/{n}", {})) for n in ("pending.json", "told.json", "read.json")],
          [sorted([NEW, f"{NEW}/t1", f"{OLD}-skill", "other"])] * 3)
        # ALL THREE TARGET SHAPES, and the two look-alikes that are not this project. An ORCHESTRATOR's address
        # names handoff records and context rows just as a track's does; left out of `retarget` it was the one
        # address a rename stranded under the old project's name.
        t("…every shape of target is carried across — one a person steers, an orchestrator, a track — and a "
          "project whose name merely begins with this one's is left where it is",
          [retarget(v, OLD, NEW) for v in (OLD, f"{OLD}@dash", f"{OLD}/t1", f"{OLD}-skill", f"other/{OLD}")],
          [NEW, f"{NEW}@dash", f"{NEW}/t1", f"{OLD}-skill", f"other/{OLD}"])
        t("…the LIVE handoff record moves to its new slug and says the new target, for the project and "
          "for a track, and the retired one is retargeted where it lies",
          (read_json(f"{state()}/handoff/{NEW}.json", {}).get("target"),
           read_json(f"{state()}/handoff/{NEW}--t1.json", {}).get("target"),
           os.path.exists(f"{state()}/handoff/{OLD}.json"),
           os.path.exists(f"{state()}/handoff/{NEW}--t1.brief"),
           read_json(f"{state()}/handoff/abc123.done", {}).get("target")),
          (NEW, f"{NEW}/t1", False, True, f"{NEW}/t2"))
        t("…and the handoff record of a project that only begins with this one's letters is untouched",
          read_json(f"{state()}/handoff/{OLD}-skill.json", {}).get("target"), f"{OLD}-skill")
        t("…cc-spend's read offsets follow the transcripts, so the next tick reads on from where it "
          "stopped instead of re-reading the whole project and counting its spend twice",
          {k: v["off"] for k, v in read_json(f"{state()}/spend/offsets.json", {})["files"].items()},
          {f"{h}/.claude/projects/{proj_slug(f'{h}/dev/{NEW}')}/s.jsonl": 4242,
           f"{h}/.claude/projects/{proj_slug(f'{worktrees()}/{NEW}/t1')}/s.jsonl": 4242,
           "/elsewhere/a-project/s.jsonl": 7})
        t("…and it reaches Slack for exactly what it declared", DENIED, [])

        # ------------------------------------------------------------------ the dry run changes nothing
        h = box("dryrun")
        calls = []
        globals()["API"] = slack(h, calls)
        rc, out = run(OLD, NEW, "--dry-run")
        t("a dry run succeeds", rc, 0)
        t("…and says what it would do, naming the checkout, a channel and a window",
          (f"{h}/dev/{NEW}" in out, f"#{OLD}-updates -> #{NEW}-updates" in out, f"window {OLD}/t1" in out),
          (True, True, True))
        t("…and CHANGES NOTHING: not a path, not a channel, not a window, not a config key",
          (os.path.isdir(f"{h}/dev/{OLD}"), os.path.exists(f"{h}/dev/{NEW}"), calls,
           os.path.exists(f"{h}/tmux.calls"), cfg(h, "PUBLISH_REPO"),
           os.path.exists(f"{slack_dir()}/channels.json"), board_of(OLD).get("repo")),
          (True, False, [], False, OLD, True, OLD))

        # ------------------------------------------------------------------ …and a live one still gets its list
        h = box("dryrun-live")
        calls = []
        globals()["API"] = slack(h, calls)
        open(f"{h}/tmux.panes", "w").write("4242\n")     # a session is running in this project's windows
        rc, out = run(OLD, NEW, "-n")
        t("a dry run of a LIVE project still succeeds", rc, 0)
        t("…and still lists the whole plan — the checkout, a channel and a window — rather than "
          "printing a refusal and nothing else, which is the one time somebody most wants to read it",
          (f"{h}/dev/{NEW}" in out, f"#{OLD}-updates -> #{NEW}-updates" in out, f"window {OLD}/t1" in out),
          (True, True, True))
        t("…while saying plainly that a real run refuses as things stand, and naming --stop",
          ("a real run REFUSES" in out, "--stop" in out), (True, True))
        t("…and it still changed nothing", (os.path.isdir(f"{h}/dev/{OLD}"), calls,
                                            os.path.exists(f"{h}/tmux.calls")), (True, [], False))
        rc, out = run(OLD, NEW, "-n", "--stop")
        t("…and with --stop the same dry run adds the stop and the restarts it WOULD do, still doing none",
          (rc, "stop " in out, f"{OLD}/t1 starts again as" in out, os.path.exists(f"{h}/tmux.calls")),
          (0, True, True, False))

        # ------------------------------------------------------------------ typed from inside the project
        h = box("from-inside")
        globals()["API"] = slack(h, calls := [])
        here = os.getcwd()
        os.chdir(f"{h}/dev/{OLD}")     # `cc rename` is very often typed in the project it renames
        # A stranger standing in the SAME directory, to pin that only this rename's own line is excused.
        other = subprocess.Popen(["sleep", "60"], cwd=f"{h}/dev/{OLD}", stdin=subprocess.DEVNULL)
        try:
            t("standing in the project itself, it sees the stranger and not its own process",
              sorted(p for p, _ in cwd_holders(OLD)), [str(other.pid)])
            other.kill()
            other.wait()
            for _ in range(80):                      # the stranger's own exit is not instant
                if not cwd_holders(OLD):
                    break
                time.sleep(0.05)
            rc, out = run(OLD, NEW)
        finally:
            other.kill()
            other.wait()
            os.chdir(here)
        t("a rename TYPED INSIDE the project is not held up by its own process standing there", rc, 0)
        t("…and it moved everything, rather than stopping the sessions and then refusing",
          (os.path.isdir(f"{h}/dev/{NEW}"), os.path.exists(f"{h}/dev/{OLD}")), (True, False))

        # ------------------------------------------------------------------ a live project refuses
        h = box("live")
        globals()["API"] = slack(h, [])
        held = subprocess.Popen(["sleep", "60"], cwd=f"{h}/dev/{OLD}", stdin=subprocess.DEVNULL)
        try:
            rc, out = run(OLD, NEW)
            t("a process standing in the project's own directory is live: refused without --stop", rc, 1)
            t("…and the refusal names it and the flag that would stop it",
              (f"pid {held.pid}" in out, "--stop" in out), (True, True))
            t("…and refusing moved nothing", os.path.exists(f"{h}/dev/{NEW}"), False)
        finally:
            held.kill()
            held.wait()

        # ------------------------------------------------------------------ …and --stop stops it and starts it again
        h = box("stop")
        globals()["API"] = slack(h, [])
        open(f"{h}/tmux.panes", "w").write("4242\n")     # something is running in this project's windows
        # …and t1's is a WORKER: a real `cc-loop <old> t1`, which is the signal cc-reconcile reads to
        # tell a worker from a session. Its cwd is outside the project, so it holds nothing that moves.
        worker = subprocess.Popen([f"{h}/bin/cc-loop", OLD, "t1"], cwd=root, stdin=subprocess.DEVNULL)
        try:
            rc, out = run(OLD, NEW)
            t("a session live in its window refuses too, without the flag", rc, 1)
            t("…and nothing was stopped by a refusal", os.path.exists(f"{h}/tmux.calls"), False)
            rc, out = run(OLD, NEW, "--stop")
            t("…with --stop it goes through", rc, 0)
            t("…having killed this project's live windows and no others",
              sorted(l for l in open(f"{h}/tmux.calls").read().split("\n") if l.startswith("kill")),
              ["kill @1", "kill @2", "kill @5"])
            t("…and started each again as what it WAS: the track with a cc-loop on it as a worker, "
              "re-dispatched onto the brief already in its task.md, the other two as plain sessions",
              sorted(open(f"{h}/cc.calls").read().split("\n")[:-1]),
              sorted([NEW, f"{NEW}|t1|--go|", f"{NEW}|t2"]))
        finally:
            worker.kill()
            worker.wait()

        # ------------------------------------------------------------------ the name must be free
        h = box("taken")
        globals()["API"] = slack(h, [])
        os.makedirs(f"{h}/dev/{NEW}")
        rc, out = run(OLD, NEW)
        t("renaming onto a name this box already has is refused", (rc, "taken" in out), (1, True))
        t("…and the project it would have overwritten is untouched", os.path.isdir(f"{h}/dev/{OLD}"), True)

        h = box("taken-in-slack")
        globals()["API"] = lambda m, tok, **kw: (
            {"channels": [{"id": c, "name": nm} for c, nm in chans(h)] + [{"id": "CX", "name": NEW}]}
            if m == "conversations.list" else deny_slack(m, tok, **kw))
        rc, out = run(OLD, NEW)
        t("…and so is a name only SLACK already has: renaming half the channels and failing on the "
          "rest is the state this refusal exists to avoid", (rc, f"#{NEW} already exists" in out), (1, True))
        t("…nothing moved for that one either", os.path.exists(f"{h}/dev/{NEW}"), False)

        # ------------------------------------------------------------------ a lane of the new name is taken
        h = box("lane-taken")
        globals()["API"] = lambda m, tok, **kw: (
            {"channels": [{"id": c, "name": nm} for c, nm in chans(h)] + [{"id": "CX", "name": f"{NEW}-updates"}]}
            if m == "conversations.list" else deny_slack(m, tok, **kw))
        rc, out = run(OLD, NEW)
        t("a name whose -updates LANE is already taken in Slack is refused, even though #<new> itself "
          "is free — the half-renamed project is the state this refusal exists to avoid",
          (rc, f"#{NEW}-updates already exists" in out), (1, True))
        t("…and nothing moved for it", os.path.exists(f"{h}/dev/{NEW}"), False)

        h = box("track-lane-taken")
        globals()["API"] = lambda m, tok, **kw: (
            {"channels": [{"id": c, "name": nm} for c, nm in chans(h)] + [{"id": "CX", "name": f"{NEW}--t1"}]}
            if m == "conversations.list" else deny_slack(m, tok, **kw))
        rc, out = run(OLD, NEW)
        t("…and so is one whose TRACK channel is taken", (rc, f"#{NEW}--t1 already exists" in out), (1, True))

        # ------------------------------------------------------------------ it will not kill its own window
        h = box("own-window")
        globals()["API"] = slack(h, calls := [])
        open(f"{h}/tmux.panes", "w").write("4242\n")     # every window of this project has something in it
        os.environ["TMUX_PANE"] = "%2"                   # …and this rename is running in @2, which is OLD/t1
        rc, out = run(OLD, NEW, "--stop")
        t("a rename running in one of the project's OWN windows refuses, --stop or not: stopping it "
          "would kill this very process before a single path had moved", rc, 1)
        t("…and it says which window it is in and where to run it instead",
          (f"{OLD}/t1, one of {OLD}'s own windows" in out, "another window" in out), (True, True))
        t("…and it killed nothing and moved nothing",
          (os.path.exists(f"{h}/tmux.calls"), os.path.exists(f"{h}/dev/{NEW}")), (False, False))
        os.environ["TMUX_PANE"] = "%4"                   # @4 is a stranger's window, not this project's
        rc, out = run(OLD, NEW, "--stop")
        t("…while from a window that is NOT this project's it goes through and stops the project's own",
          (rc, sorted(l for l in open(f"{h}/tmux.calls").read().split("\n") if l.startswith("kill"))),
          (0, ["kill @1", "kill @2", "kill @5"]))
        os.environ.pop("TMUX_PANE", None)

        # ------------------------------------------------------------------ the rest of the door
        h = box("refuse")
        globals()["API"] = deny_slack
        t("a project that is not there is refused", run("nosuch", NEW)[0], 1)
        t("renaming a name to itself is refused", run(OLD, OLD)[0], 1)
        t("a name with a slash in it is refused before anything is read", run(OLD, "a/b")[0], 1)
        t("one argument is a usage error, not a rename", run(OLD)[0], 2)
        t("…and none of those reached Slack", DENIED, [])
    finally:
        globals()["API"] = real_api
        globals()["BIN"] = real_bin
        os.environ["PATH"] = real_path
        os.environ.pop("TMUX_PANE", None)
        if real_pane is not None:
            os.environ["TMUX_PANE"] = real_pane
        if real_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = real_home
        shutil.rmtree(root, ignore_errors=True)
    print(f"cc-rename selfcheck: {n[0] - len(fails)} passed, {len(fails)} failed")
    return 1 if fails else 0
