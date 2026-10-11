# cc-name's selfcheck: the cases behind `cc-name selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-name execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    import shutil
    import tempfile
    n = f = 0

    def check(name, cond, got=None):
        nonlocal n, f
        n += 1
        print(("  ok   " if cond else "  FAIL ") + name + ("" if cond or got is None else "  << %r" % (got,)))
        if not cond:
            f += 1

    # A WHOLE BOX OF ITS OWN: its own HOME, its own board (read through the real cc-board), its own ~/dev and its
    # own word table. No board, workspace, member or table of this box's is read, and nothing outside the temp dir
    # is written.
    d = tempfile.mkdtemp(prefix="cc-name-selfcheck-")
    was = {k: os.environ.get(k) for k in ("HOME", "CC_NAME_WORDS")}
    try:
        os.makedirs(os.path.join(d, ".cc", "boards"))
        os.makedirs(os.path.join(d, ".cc", "members", "rugs-helper"))
        for repo, text in (("shop", "# shop\n\nA [small](http://x) **shop** for rugs. Second sentence.\n"),
                           ("mill", "# mill\n\nThe mill that weaves them. And the rest.\n"),
                           ("rugs-helper", "# rugs-helper\n\nYour workspace on the box. Everything lives here.\n")):
            os.makedirs(os.path.join(d, "dev", repo))
            with open(os.path.join(d, "dev", repo, "README.md"), "w") as fh:
                fh.write(text)
        rows = {"fix-the-till": {"title": "the till adds tax twice", "status": "running"},
                "no-title": {"title": "", "status": "review"},
                "echo": {"title": "Echo", "status": "review"},
                "session": {"title": "the planning window", "status": "running"}}
        with open(os.path.join(d, ".cc", "boards", "shop.json"), "w") as fh:
            json.dump({"repo": "shop", "tracks": rows, "log": []}, fh)
        table = {"tracks": {"session": {"name": "Planning and chat", "about": "the sessions a person talks to here"},
                            "-": {"about": "sessions the ledger could not place on a track"}},
                 "workspaces": {"shop": {"about": "the till, the stock and the rugs"},
                                "-": {"about": "Sessions not inside any project"}}}
        wp = os.path.join(d, "names.json")
        with open(wp, "w") as fh:
            json.dump(table, fh)
        bad = os.path.join(d, "broken.json")
        with open(bad, "w") as fh:
            fh.write("{ this is not json\n")
        os.environ["HOME"], os.environ["CC_NAME_WORDS"] = d, wp

        t = read("shop", "fix-the-till", rows)
        check("a board row: its title is the description, its slug read aloud the name",
              t == {"repo": "shop", "track": "fix-the-till", "name": "Fix the till",
                    "about": "the till adds tax twice"}, t)
        check("…and a title that only repeats the slug says nothing more, like no title at all",
              read("shop", "echo", rows)["about"] == "" and read("shop", "no-title", rows)["about"] == "")
        check("the board beats the word table where both name a track",
              read("shop", "session", rows) == {"repo": "shop", "track": "session", "name": "Session",
                                                "about": "the planning window"})
        check("a track no board carries is the table's words",
              read("shop", "session", {}) == {"repo": "shop", "track": "session", "name": "Planning and chat",
                                              "about": "the sessions a person talks to here"})
        check("neither: the slug read aloud, and no description",
              read("shop", "no-row-anywhere", {}) == {"repo": "shop", "track": "no-row-anywhere",
                                                      "name": "No row anywhere", "about": ""})
        check("the ledger's `-` reads as words at both levels, not as a dash",
              read("-", "-", {})["name"] == "Other" and read("-")["name"] == "No project"
              and read("-")["about"] == "Sessions not inside any project")
        check("a workspace is its own name, described by the table",
              read("shop") == {"repo": "shop", "track": "", "name": "shop", "member": False,
                               "about": "the till, the stock and the rugs"})
        check("…and by its README's first sentence, markdown stripped, where the table says nothing",
              read("mill")["about"] == "The mill that weaves them.", read("mill"))
        check("a member's workspace says what it is: its README speaks to the member, not about the work",
              read("rugs-helper") == {"repo": "rugs-helper", "track": "", "name": "rugs-helper",
                                      "about": MEMBER_ABOUT, "member": True}, read("rugs-helper"))
        check("the board is read through cc-board when the caller hands over no rows",
              read("shop", "fix-the-till")["about"] == "the till adds tax twice")
        check("a repo with no board at all still names its track, and raises nothing",
              read("nosuch", "a-track") == {"repo": "nosuch", "track": "a-track", "name": "A track", "about": ""})

        # THE EMPTY TABLE — what a box that has written no wordings gets. Every name is still a name.
        os.environ["CC_NAME_WORDS"] = ""
        check("with NO table at all every name is still a name, off the slug and the README",
              read("shop", "session", {})["name"] == "Session" and read("shop", "session", {})["about"] == ""
              and read("-")["name"] == "No project" and read("-", "-", {})["name"] == "Other"
              and read("shop")["about"] == "A small shop for rugs.", read("shop"))
        check("…and the board's titles still describe the tracks it carries",
              read("shop", "fix-the-till", rows)["about"] == "the till adds tax twice")

        # A TABLE THAT WILL NOT PARSE is a worse page, never no page.
        os.environ["CC_NAME_WORDS"] = bad
        err, done = sys.stderr, None
        try:
            import io
            sys.stderr = io.StringIO()
            got = read("shop", "session", {})
            done = sys.stderr.getvalue()
        finally:
            sys.stderr = err
        check("a table that will not parse is refused to stderr and read as empty, not raised",
              got["name"] == "Session" and "will not read" in (done or ""), done)

        # THE CLI, which is how a shell — anything that is not a Python importer — reads the same answer.
        os.environ["CC_NAME_WORDS"] = wp
        env = dict(os.environ, HOME=d, CC_NAME_WORDS=wp)
        me = os.path.realpath(__file__)

        def cli(*a):
            return subprocess.run([me, *a], capture_output=True, text=True, env=env,
                                  stdin=subprocess.DEVNULL, timeout=TIMEOUT)
        r = cli("shop", "fix-the-till")
        check("the CLI prints the name, one line", r.returncode == 0 and r.stdout == "Fix the till\n", r.stdout)
        check("--about prints the description", cli("--about", "shop", "fix-the-till").stdout
              == "the till adds tax twice\n")
        r = cli("--json", "shop")
        check("--json prints the object the importers get, member and all",
              json.loads(r.stdout) == read("shop"), r.stdout)
        check("a workspace with no track named prints the workspace", cli("shop").stdout == "shop\n")
        check("no argument is a usage line and a non-zero exit, never a blank name",
              cli().returncode == 2 and not cli().stdout.strip())
    finally:
        for k, v in was.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        shutil.rmtree(d, ignore_errors=True)
    print("cc-name selfcheck: %d passed, %d failed" % (n - f, f))
    return 0 if f == 0 else 1
