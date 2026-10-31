# cc-brief's selfcheck: the cases behind `cc-brief selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-brief execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.
# recurring-defect-ok: pause-hold-missing — moved test cases: the board writes and dispatches are fixtures in a temp tree, never a real one

def selfcheck():
    import tempfile
    global BOARDS, STATE
    import io, contextlib
    p = f = 0

    def ok(name, cond):
        nonlocal p, f
        print(("ok   " if cond else "FAIL ") + name)
        p, f = p + (1 if cond else 0), f + (0 if cond else 1)

    # ── the block: computed from the board, and only the block is ever rewritten ──
    tmp = tempfile.mkdtemp(prefix="cc-brief.")
    BOARDS, STATE = os.path.join(tmp, "boards"), os.path.join(tmp, "state")
    os.makedirs(BOARDS)
    # ── the check never refuses: a step list, a command block and a command run dispatch as typed ──
    steps = ("Do this:\n- Add a --flag to core/bin/cc-foo\n- Edit core/bin/cc-bar so it passes the flag through\n"
             "- Run the suite and make sure it is green\n```\ngit checkout -b track/foo\nbash core/tests/selftest.sh\n```\n")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = check(steps, for_="r/t")
    ok("a brief of steps and commands passes the check in silence (exit 0): that rule is a line in the prompt now",
       rc == 0 and err.getvalue() == "")
    def bounded(fn, secs=10):   # a read that hangs on the pipe (a plain open would, for good) fails THIS case, not the suite
        import threading
        box = []
        def go():
            try: box.append(fn())
            except Exception as e: box.append(e)
        t = threading.Thread(target=go, daemon=True); t.start(); t.join(secs)
        return box[0] if box else "hung"
    os.mkfifo(os.path.join(BOARDS, "pipe.json"))   # A PIPE PLANTED WHERE A BOARD SHOULD BE (review of #224): the read is cc-board's opener now, so it is no board, never a hang
    ok("a pipe planted where a board should be is 'nothing is known', not a hang", bounded(lambda: inflight("pipe")) is None)
    os.remove(os.path.join(BOARDS, "pipe.json"))
    repo = "selfcheckrepo"
    src = os.path.join(tmp, "repo")
    os.makedirs(src)

    def git(*args, **kw):
        return subprocess.run(["git", "-C", src, *args], capture_output=True, text=True,
                              env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}, **kw)

    subprocess.run(["git", "init", "-q", "-b", "main", src], capture_output=True)
    open(os.path.join(src, "held.txt"), "w").write("base\n")
    open(os.path.join(src, "other.txt"), "w").write("base\n")
    # …and, for the `ready` cases at the end: a file whose bare name is its own, and one basename two share.
    for d, fn in (("bin", "cc-fixture"), ("a", "dup.txt"), ("b", "dup.txt")):
        os.makedirs(os.path.join(src, d), exist_ok=True)
        open(os.path.join(src, d, fn), "w").write("base\n")
    for fn in ("pulled.txt", "wt.txt"):        # for the stale-`branch` cases: reached by PR ref and by worktree
        open(os.path.join(src, fn), "w").write("base\n")
    git("add", "-A"); git("commit", "-qm", "base")
    for br, fn in (("track/one", "held.txt"), ("track/two", "held.txt"), ("track/gone", "other.txt"),
                   ("track/tool", "bin/cc-fixture"), ("cut/elsewhere", "pulled.txt"), ("cut/checked-out", "wt.txt")):
        git("checkout", "-q", "-b", br, "main")
        open(os.path.join(src, fn), "a").write(br + "\n")
        git("add", "-A"); git("commit", "-qm", br)
    git("checkout", "-q", "main")
    # A ROW WHOSE `branch` FIELD IS STALE, both ways it is still readable without the network: somebody fetched
    # the PR, and the row's own worktree is sitting on the real branch whatever the board says.
    git("update-ref", "refs/pull/9/head", "cut/elsewhere")
    wt = os.path.join(tmp, "wt")
    git("worktree", "add", "-q", wt, "cut/checked-out")
    # A CHECKOUT THAT IS NOT THIS ONE, for the `worktree` guard: same branch name, another repository entirely.
    foreign = os.path.join(tmp, "foreign")
    subprocess.run(["git", "init", "-q", "-b", "cut/checked-out", foreign], capture_output=True)
    open(os.path.join(foreign, "wt.txt"), "w").write("theirs\n")
    subprocess.run(["git", "-C", foreign, "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", foreign, "commit", "-qm", "theirs"], capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})

    def board(tracks):
        with open(os.path.join(BOARDS, repo + ".json"), "w") as fh:
            json.dump({"repo": repo, "path": src, "default_branch": "main", "tracks": tracks}, fh)

    board({"one": {"status": "review", "branch": "track/one"},
           "two": {"status": "running", "branch": "track/two"},
           "gone": {"status": "merged", "branch": "track/gone"}})
    blk = inflight(repo, exclude="two")
    ok("a live track's file is reported as held, with who holds it", "held.txt — one [review]" in blk)
    ok("…and the brief's own track is not reported against itself", "two [running]" not in blk)
    ok("a merged row holds nothing — its file is absent", "other.txt" not in blk)
    ok("the block is delimited so only it can ever be rewritten", blk.startswith(MARK_A) and blk.rstrip().endswith(MARK_B))

    board({"one": {"status": "review", "branch": "track/one"},
           "sess": {"status": "running", "branch": "track/gone", "kind": "session"}})
    blk2 = inflight(repo, exclude="")
    ok("a row a person marked kind=session is read and skipped, never reported as a holder",
       "held.txt" in blk2 and "sess" not in blk2 and "other.txt" not in blk2)

    board({"gone": {"status": "merged", "branch": "track/gone"}})
    ok("nothing held: no block, so a brief carries no line about nothing", inflight(repo, exclude="") == "")
    ok("an unreadable board is NOT the same answer as nothing held", inflight("no-such-board") is None)

    # rewrite: the typed brief survives verbatim, the stale block does not
    board({"one": {"status": "review", "branch": "track/one"}})
    td = os.path.join(STATE, repo, "mine")
    os.makedirs(td)
    typed = "GOAL: a goal a person typed.\n\nBOUNDARIES: nothing here is the machine's to touch.\n"
    task = os.path.join(td, "task.md")
    open(task, "w").write(typed + "\n" + MARK_A + "\nIN FLIGHT (from the board, 1999-01-01T00:00Z): stale.txt — ghost [running]\n" + MARK_B + "\n")
    refresh(repo, "mine")
    got = open(task).read()
    ok("refresh replaces the machine's stale block", "stale.txt" not in got and "held.txt" in got)
    ok("…and every line a person typed is still there, verbatim", typed.strip() in got)
    ok("…and there is exactly one block afterwards", got.count(MARK_A) == 1 and got.count(MARK_B) == 1)
    open(task, "w").write(typed)
    refresh(repo, "mine")
    ok("a brief with no block gets one appended", MARK_A in open(task).read() and typed.strip() in open(task).read())
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        check(open(task).read(), for_="r/t")
    ok("the block is not checked as if a person typed it: no warning", err.getvalue() == "" and "held.txt" in open(task).read())
    refresh(repo, "absent-track")
    ok("a track with no brief is not an error", True)

    # the block goes as it came: when the last holder finishes, the brief stops claiming the file is held
    board({"one": {"status": "merged", "branch": "track/one"}})
    refresh(repo, "mine")
    after = open(task).read()
    ok("the last holder finishing takes the block back out", MARK_A not in after and "held.txt" not in after)
    ok("…and the typed brief is still whole", typed.strip() in after)
    # ITS OWN FIXTURE, and a pure one: put the block in and take it out again, and the writer's text — including a
    # gap they left — must come back byte for byte. The tool tidying a brief it did not write is the thing to catch.
    theirs = "GOAL: a thing.\n\n\n\nwith a gap the writer left.\n"
    merge = _board().merge
    ok("adding the block and taking it out again returns the typed brief byte for byte",
       merge(merge(theirs, MARK_A + "\nIN FLIGHT: x\n" + MARK_B + "\n"), "") == theirs)

    open(task, "w").write(typed + "\n" + MARK_A + "\nIN FLIGHT: something\n" + MARK_B + "\n")
    refresh("no-such-board", "mine")
    ok("a board that cannot be read leaves the block alone rather than deleting it",
       MARK_A in open(task).read())

    # ── ready: which queued rows nothing in flight is holding, and which of them are one builder's work ──
    def brief_of(track, text):
        d = os.path.join(STATE, repo, track)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "task.md"), "w").write(text)

    def say(*only):
        """cmd_ready as `main` would reach it, so the flag parsing is under test too, not just the arithmetic."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["ready", repo, *only])
        return rc, buf.getvalue()

    idx = tracked(src)
    ok("a bare name exactly one tracked file carries IS that file — briefs write `cc-fixture`, not its path",
       named("GOAL: cc-fixture answers the wrong question.\n", src, idx) == {"bin/cc-fixture"})
    ok("…and a basename two directories share names neither of them, so it is not read as a file at all",
       named("GOAL: dup.txt is wrong.\n", src, idx) == set())
    ok("a whole path counts when it resolves in the checkout, and is prose when it does not",
       named("GOAL: bin/cc-fixture, not bin/cc-nothing.\n", src, idx) == {"bin/cc-fixture"})
    ok("an ordinary word is never a file, however many of them a brief has",
       named("GOAL: the box says what could be running, and nobody has to notice by hand.\n", src, idx) == set())
    # A BOUNDARY IS SPELT LIKE A TARGET, and read as one it made ten rows collide on a file every brief warns
    # about (review of #371). The clause that says a file is somebody else's is dropped, and only that clause.
    ok("A FILE NAMED IN ORDER TO SAY IT WILL NOT BE TOUCHED IS NOT THIS ROW'S — and the target beside it still is",
       named("GOAL: held.txt is wrong.\nBOUNDARIES: other.txt is held by PR #9. Never edits bin/cc-fixture.\n",
             src, idx) == {"held.txt"})
    ok("…and the em-dash a brief hangs its boundary off does not end the clause, or the path would come straight "
       "back", named("GOAL: a thing.\nBOUNDARIES: wt.txt, pulled.txt — do not touch them.\n", src, idx) == set())
    ok("…while a boundary in the NEXT sentence cannot eat the one before it",
       named("GOAL: held.txt is wrong. Leave other.txt alone.\n", src, idx) == {"held.txt"})
    # A BOUNDARY GOVERNS ITS CLAUSE AND NOT THE SENTENCE. Prose here is compound, so dropping the sentence took
    # the row's real target out with the boundary and under-reported what it owns (re-review of #371).
    ok("a sentence that says what this row WILL write and what it must stay off keeps the first and drops the "
       "second — one clause each",
       named("GOAL: this row will edit bin/cc-fixture, but do not touch held.txt -- that stays with the other "
             "track.\n", src, idx) == {"bin/cc-fixture"})
    ok("…and an ownership clause joined to a boundary one by `and` survives it, which is how a BOUNDARIES line "
       "is usually written",
       named("BOUNDARIES: held.txt is held by PR #9 and other.txt is this row's to rewrite.\n",
             src, idx) == {"other.txt"})
    ok("…but a boundary's own comma LIST is one boundary, not a target after the first name",
       named("GOAL: never edits held.txt, other.txt, bin/cc-fixture or the approval list.\n", src, idx) == set())

    FRESH = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    board({"one": {"status": "review", "branch": "track/one"},
           "q1": {"status": "queued"}, "q2": {"status": "queued"}, "q3": {"status": "queued"},
           "sat": {"status": "queued", "held": "the owner has not decided yet"},
           "mine": {"status": "queued", "agent": "@1:7", "agent_at": FRESH, "branch": "track/tool"}})
    brief_of("q1", "GOAL: what held.txt says is wrong.\n")
    brief_of("q2", "GOAL: other.txt says the wrong thing.\n")
    brief_of("q3", "GOAL: other.txt again, from the other end.\n")
    brief_of("sat", "GOAL: other.txt, but nobody is to touch it yet.\n")
    brief_of("mine", "GOAL: bin/cc-fixture, and a subagent is already on it.\n")
    free, groups, weighed, unplaced, blind = ready(repo)
    ok("THE ROWS THAT COULD START NOW ARE NAMED — nothing in flight is holding a file their briefs name",
       free == ["q2", "q3"])
    ok("…and a queued row whose brief names a file a live track is holding is not one of them", "q1" not in free)
    ok("a row a person is sitting on and a row a live session marked as its own are not even weighed",
       weighed == 3 and "sat" not in free and "mine" not in free)
    ok("two free rows naming the SAME file are ONE builder's work, and come out grouped by that file",
       groups == [(["other.txt"], ["q2", "q3"])])
    rc, out = say()
    ok("the printed answer carries both halves — how many could start, and which belong together",
       rc == 0 and "2 of 3 queued rows could start now" in out and "one builder for other.txt: q2, q3" in out)

    board({"a1": {"status": "queued"}, "a2": {"status": "queued"}, "a3": {"status": "queued"}})
    brief_of("a1", "GOAL: held.txt.\n")
    brief_of("a2", "GOAL: held.txt, and other.txt with it.\n")
    brief_of("a3", "GOAL: other.txt.\n")
    ok("the join is transitive: a shares with b and b with c, so all three are one builder's and not two workers'",
       ready(repo)[1] == [(["held.txt", "other.txt"], ["a1", "a2", "a3"])])
    ok("a caller that has already decided which rows to weigh gets exactly those weighed",
       ready(repo, only=["a1"])[2] == 1)

    board({"tool": {"status": "running", "branch": "track/tool"}, "q4": {"status": "queued"}})
    brief_of("q4", "GOAL: cc-fixture answers the wrong question.\n")
    ok("a row naming its file the way a brief actually writes it — the bare name — still sees the collision",
       ready(repo)[0] == [])

    # ── THE FIX AGAINST THE MENTION. A raised- row's account names every tool in its story; a dispatch brief
    # names its target under GOAL, FILES or BOUNDARIES, or says where the fix goes. Both are `names`; only the
    # second is `touches`, and the group `ready` prints (which cc-bundle runs) joins on touches alone.
    story = ("WHAT BROKE: 02:1xZ, bin/cc-fixture printed nothing and the seat read that as empty.\n"
             "WHAT IT COST: a turn, and a wrong answer acted on.\n")
    ok("a file a story names is a mention, never the fix", touches(story, src, idx) == set()
       and named(story, src, idx) == {"bin/cc-fixture"})
    ok("a file under FILES, GOAL or BOUNDARIES is the fix",
       touches("GOAL: the seat is told.\nFILES: bin/cc-fixture, other.txt\n", src, idx) == {"bin/cc-fixture", "other.txt"}
       and touches("GOAL: bin/cc-fixture answers.\nWHY: held.txt lied.\n", src, idx) == {"bin/cc-fixture"})
    ok("…and so is one in a clause that says where the fix goes, carried across its own `and`",
       touches(story + "The fix goes in other.txt.\n", src, idx) == {"other.txt"}
       and touches("Touch only bin/cc-fixture and other.txt — held.txt is the other row's.\n", src, idx)
       == {"bin/cc-fixture", "other.txt"})
    ok("…while a boundary under BOUNDARIES is still nobody's fix, however the brief spells the must-not",
       touches("BOUNDARIES: bin/cc-fixture. Do not touch held.txt.\n", src, idx) == {"bin/cc-fixture"}
       and touches("FILES: bin/cc-fixture; it must not touch held.txt.\n", src, idx) == {"bin/cc-fixture"})
    ok("a story's own 'fix', 'edit' and 'touches' name no target",
       touches("bin/cc-fixture returned LAND-AFTER-FIX, then gh pr edit exited 0; the diff touches only other.txt "
               "and the fix would vanish.\n", src, idx) == set())
    board({"fa": {"status": "queued"}, "fc": {"status": "queued"}, "story": {"status": "queued"}})
    brief_of("fa", "GOAL: bin/cc-fixture answers the wrong question.\n")
    brief_of("fc", "GOAL: bin/cc-fixture takes a --flag.\n")
    brief_of("story", story)
    free, groups, weighed, unplaced, blind = ready(repo)
    ok("A QUEUED ROW JOINS A GROUP ONLY ON A FILE ITS BRIEF NAMES AS THE FIX: the row whose account merely "
       "names the tool is free, and in no group", free == ["fa", "fc", "story"]
       and groups == [(["bin/cc-fixture"], ["fa", "fc"])])
    board({"tool": {"status": "running", "branch": "track/tool"}, "story": {"status": "queued"}})
    ok("…but its mention still holds it back while a live row holds that file — free errs toward collision",
       ready(repo)[0] == [])

    # ── A LIVE ROW HOLDS WHAT ITS WORKTREE HAS CHANGED, COMMITTED OR NOT. A worker's hook commits at the end of
    # an iteration; until then its branch says nothing, and `ready` offered core/bin/cc-handoff to seven rows
    # twelve minutes into a live edit of it. The `wt` checkout here is on cut/checked-out (wt.txt committed); an
    # uncommitted edit to other.txt in it is what the row holds now.
    open(os.path.join(wt, "other.txt"), "a").write("mid-iteration\n")
    board({"wt": {"status": "running", "branch": "cut/checked-out"}, "qw": {"status": "queued"}})
    brief_of("qw", "GOAL: other.txt is wrong.\n")
    byrow, unplaced = held_files(board_of(repo), skip={"qw"}, net=False)
    ok("a running row's uncommitted edit is a file it holds — read off its worktree, not its branch",
       byrow.get("wt") == ("running", ["other.txt", "wt.txt"]) and unplaced == [])
    ok("…and `ready` drops the queued row that names it", ready(repo, net=False)[0] == [])
    ok("…and `belongs` offers that row to a new ask in the same file",
       [(r[0], r[3]) for r in belongs(repo, "qw")] == [("wt", ["other.txt"])])
    ok("…and the IN FLIGHT block names it", "other.txt — wt [running]" in (inflight(repo, exclude="qw") or ""))
    subprocess.run(["git", "-C", wt, "checkout", "-q", "--", "other.txt"], capture_output=True)
    byrow, _ = held_files(board_of(repo), skip={"qw"}, net=False)
    ok("…and with the edit reverted the row holds its committed file alone", byrow.get("wt") == ("running", ["wt.txt"]))

    # ── A status=blocked ROW NEVER APPEARS IN `ready`, named or not: the pulse hands `ready` its own due list,
    # which carries blocked rows, and the wake said "a builder each" three times for two rows a seat had already
    # declined on the row itself (raised-brief-ready-lists-blocked-rows-as-startable).
    board({"stopped": {"status": "blocked"}, "qk": {"status": "queued"}})
    brief_of("stopped", "GOAL: held.txt, but PR #528 has to land first.\n")
    brief_of("qk", "GOAL: other.txt is wrong.\n")
    ok("a blocked row is not weighed and not free", ready(repo, net=False) == (["qk"], [], 1, [], []))
    ok("…not even when the caller names it, as the pulse does",
       ready(repo, only=["stopped", "qk"], net=False) == (["qk"], [], 1, [], []))
    rc, out = say("stopped", "qk")
    ok("…so the wake line never carries it", "stopped" not in out and "1 of 1 queued row could start now" in out)

    # ── A ROW WITH NO BRIEF IS NEVER OFFERED: a worker launched on it had only the go note and no bounds
    # (raised-a-row-dispatched-without-its-brief).
    board({"nobrief": {"status": "queued"}, "qk": {"status": "queued"}})
    brief_of("nobrief", "\n" + MARK_A + "\nIN FLIGHT (from the board, 1999-01-01T00:00Z):\n  held.txt — one [review]\n" + MARK_B + "\n")
    brief_of("qk", "GOAL: other.txt is wrong.\n")
    ok("a queued row whose brief is empty is not offered, even when named",
       ready(repo, net=False)[0] == ["qk"] and ready(repo, only=["nobrief", "qk"], net=False)[0] == ["qk"])

    board({"one": {"status": "review", "branch": "track/one"}, "q2": {"status": "queued"}})
    brief_of("q2", "GOAL: other.txt says the wrong thing.\n\n" + MARK_A +
             "\nIN FLIGHT (from the board, 1999-01-01T00:00Z):\n  held.txt — one [review]\n" + MARK_B + "\n")
    ok("the IN FLIGHT block is this tool's own writing, so a brief carrying one does not collide with it",
       ready(repo)[0] == ["q2"])

    # ── A STALE `branch` FIELD IS NORMAL, and reading it as the whole answer is how a live PR held nothing at
    # all: the ref did not resolve, the diff came back empty, and every queued row sharing that PR's files read
    # as free (review of #367). Three ways the work is still found without the network, then the honest UNKNOWN.
    ok("the number is read off a `pr` field written either way — bare, or as the whole URL",
       pr_number("9") == "9" and pr_number("https://example.invalid/x/y/pull/364") == "364")
    board({"wt": {"status": "review", "branch": "track/long-gone", "worktree": wt}, "q6": {"status": "queued"}})
    brief_of("q6", "GOAL: wt.txt is wrong.\n")
    byrow, unplaced = held_files(board_of(repo), skip={"q6"})
    ok("a row whose branch field is stale is placed by its own WORKTREE, which is on the real branch",
       byrow.get("wt") == ("review", ["wt.txt"]) and unplaced == [])
    ok("…so the queued row that shares that file is not offered as free", ready(repo)[0] == [])

    board({"pr9": {"status": "review", "branch": "track/long-gone", "pr": "9"}, "q7": {"status": "queued"}})
    brief_of("q7", "GOAL: pulled.txt is wrong.\n")
    byrow, unplaced = held_files(board_of(repo), skip={"q7"})
    ok("a row with no worktree either is placed by its PR, from a refs/pull ref somebody fetched — no network",
       byrow.get("pr9") == ("review", ["pulled.txt"]) and unplaced == [])
    ok("…and that PR's files are held against the queued row that names one", ready(repo)[0] == [])

    # ── A ROW NOTHING PLACES WITHHOLDS THE ANSWER RATHER THAN QUALIFYING IT. Its files are unknown, and FREE IS
    # A CLAIM OF SAFETY: the row this was measured on holds two files its brief never spells, so a queued row
    # naming one of them came back free with a general note that some row was unread as the only warning
    # (re-review of #367). The guess its brief gives can take a row OUT of the free list; it can never put one in.
    board({"lost": {"status": "review", "branch": "track/long-gone", "pr": "5"}, "q8": {"status": "queued"},
           "q9": {"status": "queued"}})
    brief_of("lost", "GOAL: pulled.txt is wrong, and nothing here says where the work is.\n")
    brief_of("q8", "GOAL: pulled.txt from the other end.\n")
    brief_of("q9", "GOAL: wt.txt, which nobody is on.\n")
    free, groups, weighed, unplaced, blind = ready(repo, net=False)
    ok("a row IN FLIGHT with a PR that nothing places is UNKNOWN, never 'holds nothing'",
       unplaced == ["lost"] and blind == [])
    ok("…and NO row is called free while it is there — not the one that shares its files, nor the one that does "
       "not: a brief's paths are a guess, and free is a claim of safety",
       free == [] and "q9" not in free)
    rc, out = say("--no-net")
    ok("…and the answer names it with its goal line, so a person can go and place it by hand",
       "none can be called free" in out and "lost (read from its brief only) — GOAL: pulled.txt is wrong" in out)
    ok("…and says what would settle it, and gives no count that reads as room",
       "the branch the work is really on" in out and "could start now" not in out)

    board({"blind": {"status": "review", "branch": "track/long-gone", "pr": "5"}, "qa": {"status": "queued"}})
    brief_of("blind", "GOAL: a member session's work reaches the far end without a person.\n\n"
                      "WHY: it is described here in prose and no filename appears anywhere in it.\n")
    brief_of("qa", "GOAL: held.txt is wrong.\n")
    free, groups, weighed, unplaced, blind = ready(repo, net=False)
    ok("a row whose OWN BRIEF names no file either is blind — nothing at all is known about what it holds",
       blind == ["blind"] and unplaced == ["blind"] and free == [])
    rc, out = say("--no-net")
    ok("…and the answer says which of the two it is, so the reader knows there is nothing to go on",
       "blind (brief names no file either) — GOAL: a member session's work reaches" in out)
    board({"blind": {"status": "review", "branch": "track/long-gone", "pr": "5", "worktree": src},
           "qa": {"status": "queued"}})
    ok("…and placing it — here by a worktree that IS this repo's — brings the whole answer back",
       ready(repo, net=False) == (["qa"], [], 1, [], []))
    board({"blind": {"status": "review", "branch": "track/long-gone", "pr": "5", "worktree": tmp},
           "qa": {"status": "queued"}})
    ok("a `worktree` field is as stale as a `branch` one: a directory that is not a checkout places nothing",
       ready(repo, net=False)[3] == ["blind"])
    board({"blind": {"status": "review", "branch": "track/long-gone", "pr": "5", "worktree": foreign},
           "qa": {"status": "queued"}})
    ok("…and a checkout that is ANOTHER repository's places nothing either, whatever branch it is on",
       ready(repo, net=False)[3] == ["blind"])

    # …and GitHub is the last place a row can be placed, which is why it is asked BY DEFAULT: withholding is only
    # worth anything if the ordinary run has something to withhold about. `--no-net` is for a run that must not
    # leave the box, and it answers less often — that is the trade, and both halves are here.
    gbin = os.path.join(tmp, "gbin")
    os.makedirs(gbin, exist_ok=True)
    open(os.path.join(gbin, "gh"), "w").write("#!/bin/sh\nprintf '%s\\n' held.txt\n")
    os.chmod(os.path.join(gbin, "gh"), 0o755)
    was_path = os.environ["PATH"]
    os.environ["PATH"] = gbin + os.pathsep + was_path
    board({"lost": {"status": "review", "branch": "track/long-gone", "pr": "https://example.invalid/x/pull/77"},
           "qn": {"status": "queued"}, "qz": {"status": "queued"}})
    brief_of("lost", "GOAL: nothing here says where the work is.\n")
    brief_of("qn", "GOAL: held.txt is wrong.\n")
    brief_of("qz", "GOAL: other.txt is wrong.\n")
    ok("GitHub places a row no local ref could, and the answer comes back whole — the PR's files held, the row "
       "that shares none of them free",
       ready(repo) == (["qz"], [], 2, [], []))
    ok("…and --no-net makes no call at all: the row is unplaced, and nothing is called free",
       ready(repo, net=False) == ([], [], 2, ["lost"], ["lost"]))
    os.environ["PATH"] = was_path

    board({"never": {"status": "queued", "branch": "track/long-gone"}, "q8": {"status": "queued"}})
    ok("a row nobody ever dispatched — no ref, no PR, no mark — holds nothing and is not unknown either",
       ready(repo, only=["q8"]) == (["q8"], [], 1, [], []))
    # ── A ROW WITH NO BRANCH ANYWHERE HOLDS NOTHING, WHATEVER ITS STATUS SAYS (raised-one-branchless-row-makes-
    # every-queued-row-unplaceable, 2026-09-12): a project row an orch holds — `running`, its `agent` mark warm,
    # a `branch` and `worktree` nothing resolves, no PR — made all 23 queued rows "unplaceable", every pulse.
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    board({"project": {"status": "running", "branch": "track/long-gone", "worktree": os.path.join(tmp, "nowhere"),
                       "agent": "@1:2", "agent_at": stamp},
           "q8": {"status": "queued"}, "q9": {"status": "queued"}})
    brief_of("project", "GOAL: a knowledge library for the box; its code work runs in tracks of its own.\n")
    brief_of("q8", "GOAL: pulled.txt from the other end.\n")
    brief_of("q9", "GOAL: wt.txt, which nobody is on.\n")
    byrow, unplaced = held_files(board_of(repo), skip={"q8", "q9"}, net=False)
    ok("a running row an orch holds, with no ref, no worktree and no PR, holds nothing — it is not unplaced",
       byrow.get("project") == ("running", []) and unplaced == [])
    ok("…so the queued rows are called free, and the answer is not withheld for it",
       ready(repo, net=False) == (["q8", "q9"], [], 2, [], []))
    # …and the same row WITH a PR is the #367 case again: its work is somewhere, and the answer waits on it.
    board({"project": {"status": "running", "branch": "track/long-gone", "pr": "5"}, "q8": {"status": "queued"}})
    ok("…while the same row with a PR nothing local places is still unknown, as before",
       ready(repo, net=False)[3] == ["project"])
    # ── THE WORKTREE GIT LISTS UNDER THE ROW'S OWN NAME places it when both board fields are stale or empty.
    named_wt = os.path.join(tmp, "by-name")
    git("worktree", "add", "-q", "-b", "cut/by-name", named_wt, "cut/checked-out")
    board({"by-name": {"status": "running", "branch": "track/long-gone"}, "qb": {"status": "queued"}})
    brief_of("qb", "GOAL: wt.txt is wrong.\n")
    byrow, unplaced = held_files(board_of(repo), skip={"qb"}, net=False)
    ok("a row whose branch field is stale and whose worktree field is empty is placed by the worktree git lists "
       "under its own name", byrow.get("by-name") == ("running", ["wt.txt"]) and unplaced == [])
    ok("…and holds its file against the queued row that names it", ready(repo, net=False)[0] == [])
    git("worktree", "remove", "--force", named_wt)
    # ── A ROW INSIDE A LIVE BUNDLE IS BEING WRITTEN, whoever asks: cc-bundle's `bundle` field on a member names
    # the bundle row, and the member stays `queued` so that bundle's PR can close it.
    board({"bundle-x": {"status": "running", "branch": "track/long-gone"},
           "m1": {"status": "queued", "bundle": "bundle-x"}, "m2": {"status": "queued", "bundle": "bundle-x"},
           "solo": {"status": "queued"}})
    for k in ("m1", "m2", "solo"):
        brief_of(k, "GOAL: other.txt is wrong.\n")
    ok("a queued row inside a live bundle is not a candidate, even when it is named",
       sorted(candidates(board_of(repo))) == ["solo"] and candidates(board_of(repo), only=["m1", "solo"]).keys() == {"solo"})
    board({"bundle-x": {"status": "done", "branch": "track/long-gone"},
           "m1": {"status": "queued", "bundle": "bundle-x"}, "solo": {"status": "queued"}})
    ok("…and comes back to the pool once the bundle row is no longer live",
       sorted(candidates(board_of(repo))) == ["m1", "solo"])

    # ── A DEPENDENCY NAMED BY TRACK IS A COLLISION. Briefs say "it goes after <row> — same file" and never spell
    # the file, so the row read as free while that row's PR held it.
    board({"the-holder-row": {"status": "review", "branch": "track/one"},
           "q10": {"status": "queued"}, "q11": {"status": "queued"}})
    brief_of("q10", "GOAL: a thing.\n\nBOUNDARIES: this goes after the-holder-row - it builds on it and cannot "
                    "be written in parallel with it.\n")
    brief_of("q11", "GOAL: a thing that stands on its own and names nobody.\n")
    free, groups, weighed, unplaced, blind = ready(repo)
    ok("a brief that names another ROW inherits that row's held files, spelled out or not", free == ["q11"])
    board({"q12": {"status": "queued"}, "q13": {"status": "queued"}})
    brief_of("q12", "GOAL: this follows q13 and lands on top of it.\n")
    brief_of("q13", "GOAL: other.txt says the wrong thing.\n")
    ok("…and two QUEUED rows joined that way are one builder's work, by the file only one of them named",
       ready(repo)[1] == [(["other.txt"], ["q12", "q13"])])

    # THE SAME SENTENCE HAS TO ANSWER BOTH WAYS at this end too, where own[] is what a queued row is weighed on:
    # the file it names to stay OFF must not hold it back, and the file the same sentence says it will write must.
    brief_of("compound", "GOAL: this row will edit other.txt, but do not touch held.txt "
                         "— that stays with the other track.\n")
    board({"holds-held": {"status": "review", "branch": "track/one"}, "compound": {"status": "queued"}})
    off = ready(repo)[0]
    board({"holds-other": {"status": "review", "branch": "track/gone"}, "compound": {"status": "queued"}})
    ok("a row is free of the file its own brief named only to STAY OFF it, and still held by the file the same "
       "compound sentence says it will write", off == ["compound"] and ready(repo)[0] == [])

    board({"one": {"status": "review", "branch": "track/one"}, "q1": {"status": "queued"}})
    ok("NOTHING COULD START IS SILENCE — not a count, not a heading, not a line", say() == (0, ""))
    board({"one": {"status": "merged", "branch": "track/one"}})
    ok("…and so is a board with no row waiting at all", say() == (0, ""))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_ready("no-such-board", ())
    ok("a board that cannot be READ is not the same answer as nothing, and neither is printed as the other",
       ready("no-such-board") is None and rc == 0 and buf.getvalue() == "")

    # ── belongs: a new ask joins the row already in that code, instead of opening a landing of its own ──
    def offer(track):
        """cmd_belongs as `main` reaches it, so the argument handling is under test with the arithmetic."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["belongs", repo, track])
        return rc, buf.getvalue()

    board({"already-on-it": {"status": "review", "branch": "track/one", "title": "held.txt, from the far end"},
           "elsewhere": {"status": "running", "branch": "track/gone"},
           "landed": {"status": "merged", "branch": "track/two"},
           "new": {"status": "queued"}, "lone": {"status": "queued"}})
    brief_of("new", "GOAL: held.txt is wrong in one more way.\n")
    brief_of("lone", "GOAL: wt.txt, which nobody at all is on.\n")
    got = belongs(repo, "new")
    ok("A NEW ASK IN A FILE A LIVE ROW IS WRITING IS TOLD WHICH ROW, and told nothing about the rest of the board",
       [(r[0], r[1], r[3]) for r in got] == [("already-on-it", "review", ["held.txt"])])
    rc, out = offer("new")
    ok("…and the offer is a command a person can run, against the row's own title, not a description of one",
       rc == 0 and "1 live row is already on this work" in out
       and "cc board add selfcheckrepo already-on-it 'held.txt, from the far end' '<the ask>'" in out)
    ok("…and it says the row's PR is open, which is what decides whether the ask can still go in",
       "already-on-it [review] — held.txt." in out and "its PR is open" in out)
    ok("A ROW THAT OVERLAPS NOTHING IS LEFT ALONE — no offer, no heading, no line at all", offer("lone") == (0, ""))
    ok("a merged row is not offered: its landing is spent, and joining it buys nothing",
       all(r[0] != "landed" for r in got))

    board({"a-queued-one": {"status": "queued", "branch": "track/two"},
           "z-pr-open": {"status": "review", "branch": "track/one"}, "new": {"status": "queued"}})
    brief_of("new", "GOAL: held.txt and other.txt are both wrong.\n")
    brief_of("a-queued-one", "GOAL: held.txt from a third angle, and other.txt with it.\n")
    brief_of("z-pr-open", "GOAL: other.txt as well as held.txt.\n")
    ok("the row furthest along is offered first: an open PR is a landing already committed to, and two QUEUED "
       "rows sharing a file are what `ready` groups anyway",
       [r[0] for r in belongs(repo, "new")] == ["z-pr-open", "a-queued-one"])
    brief_of("new", "GOAL: held.txt is wrong in one more way.\n")

    # ── ONE SHARED FILE IS ONLY EVIDENCE WHILE IT IS THE PAIR'S. Offering on any single file put sixteen rows in
    # front of a person, ten of them sharing nothing but cc-land or a suite, and buried the row worth joining. ──
    board({"hub-a": {"status": "review", "branch": "track/one"},
           "hub-b": {"status": "running", "branch": "track/two"}, "new": {"status": "queued"}})
    ok("A SINGLE SHARED FILE THE REST OF THE LIVE BOARD ALSO WANTS IS COMMON GROUND, not a concern in common: an "
       "offer resting on it alone is not made", belongs(repo, "new") == [])
    board({"hub-a": {"status": "review", "branch": "track/one"}, "new": {"status": "queued"}})
    ok("…while that same one file shared with ONE other row is exactly the pair worth offering",
       [r[0] for r in belongs(repo, "new")] == ["hub-a"])
    board({"hub-a": {"status": "review", "branch": "track/one"},
           "hub-b": {"status": "running", "branch": "track/two"},
           "the-real-pair": {"status": "running", "branch": "track/tool"}, "new": {"status": "queued"}})
    brief_of("new", "GOAL: held.txt and bin/cc-fixture are both wrong.\n")
    brief_of("the-real-pair", "GOAL: held.txt, and bin/cc-fixture with it.\n")
    ok("…and a SECOND shared file clears the floor however common the first is — which is the row a person was "
       "looking for", [r[0] for r in belongs(repo, "new")] == ["the-real-pair"])

    # A BOUNDARY IS NOT OWNERSHIP, the same rule `named` keeps: a brief spelling a file it must stay out of was
    # read as writing it, and the row actually holding that file was offered as one to lump the ask onto.
    board({"in-my-file": {"status": "review", "branch": "track/one"},
           "in-the-one-i-must-not": {"status": "running", "branch": "track/gone"}, "new": {"status": "queued"}})
    brief_of("new", "GOAL: held.txt is wrong in one more way.\n"
                    "BOUNDARIES: other.txt is held by in-the-one-i-must-not — do not touch it.\n")
    ok("A ROW WHOSE FILE THIS BRIEF NAMES ONLY TO STAY OUT OF IT IS NOT OFFERED, by file or by its own name, and "
       "the row holding what this one is actually writing still is",
       [r[0] for r in belongs(repo, "new")] == ["in-my-file"])
    brief_of("new", "GOAL: held.txt is wrong in one more way.\n")

    # THE ASYMMETRY THE ROW EXISTS FOR: a session's own subagent takes the ask mid-run and nothing on the box can
    # see it, so the mark is the only sign; a headless worker cannot be reached at all and gets its brief instead.
    board({"in-a-subagent": {"status": "running", "branch": "track/one", "agent": "@1:7", "agent_at": FRESH},
           "new": {"status": "queued"}})
    rc, out = offer("new")
    ok("a row a session is running in its own subagent is offered as one to patch through that session",
       "has it in a subagent, which takes the ask mid-run" in out)
    board({"a-worker": {"status": "running", "branch": "track/one"}, "new": {"status": "queued"}})
    rc, out = offer("new")
    ok("…and a row with no mark says both routes, because the board cannot tell a window from a headless worker",
       "cc selfcheckrepo a-worker --say" in out and "reads its brief at the next iteration" in out)

    # A DEPENDENCY NAMED BY TRACK IS THE SAME OFFER, and briefs write one far more often than they write a path.
    board({"the-other-row": {"status": "running", "branch": "track/gone"}, "new": {"status": "queued"}})
    brief_of("new", "GOAL: a thing.\n\nBOUNDARIES: this builds on the-other-row and cannot be written beside it.\n")
    rc, out = offer("new")
    ok("a brief that names another live ROW is offered that row, with no file spelled anywhere in either",
       "the-other-row [running] — named in this brief" in out)

    # GENEROUS WHERE `ready` IS CAREFUL: a row no ref places still offers what its own brief names, because this
    # is a suggestion a person weighs and not a claim that anything is safe to start.
    board({"unplaced": {"status": "review", "branch": "track/long-gone"}, "new": {"status": "queued"}})
    brief_of("unplaced", "GOAL: held.txt is being rewritten here.\n")
    brief_of("new", "GOAL: held.txt is wrong in one more way.\n")
    ok("a row nothing places is still offered, on the files its own brief names",
       [r[0] for r in belongs(repo, "new")] == ["unplaced"])

    board({"one": {"status": "review", "branch": "track/one"}, "new": {"status": "queued"}})
    brief_of("new", "GOAL: other.txt.\n\n" + MARK_A +
             "\nIN FLIGHT (from the board, 1999-01-01T00:00Z):\n  held.txt — one [review]\n" + MARK_B + "\n")
    ok("the IN FLIGHT block is this tool's own writing, so a brief carrying one is not offered its own block back",
       belongs(repo, "new") == [])
    board({"sess": {"status": "running", "branch": "track/one", "kind": "session"}, "new": {"status": "queued"}})
    brief_of("new", "GOAL: held.txt is wrong in one more way.\n")
    ok("a row a person marked kind=session holds no work to join, so it is never offered",
       belongs(repo, "new") == [])
    ok("a track the board does not carry is nothing to offer against, and is not an error",
       belongs(repo, "no-such-track") == [])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_belongs("no-such-board", "new")
    ok("a board that cannot be read says nothing and offers nothing, and is not the same answer as no overlap",
       belongs("no-such-board", "new") is None and rc == 0 and buf.getvalue() == "")

    # ── what the tree no longer has: the door asks git, over the fix scope, against the base as fetched ──
    gsrc = os.path.join(tmp, "gone-repo")
    os.makedirs(os.path.join(gsrc, "core", "bin"))
    def ggit(*args):
        return subprocess.run(["git", "-C", gsrc, *args], capture_output=True, text=True,
                              env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    subprocess.run(["git", "init", "-q", "-b", "main", gsrc], capture_output=True)
    for fn in ("cc-old", "cc-kept"):
        open(os.path.join(gsrc, "core", "bin", fn), "w").write("#!/bin/sh\n")
    ggit("add", "-A"); ggit("commit", "-qm", "base")
    ggit("commit", "-q", "--allow-empty", "-m", "a queued row is dispatched once (#494)")
    ggit("rm", "-q", "core/bin/cc-old"); ggit("commit", "-qm", "the old tool goes (#12)")
    with open(os.path.join(BOARDS, "gonerepo.json"), "w") as fh:
        json.dump({"repo": "gonerepo", "path": gsrc, "default_branch": "main", "tracks": {}}, fh)
    root, ref = tree_for("gonerepo/t")
    ok("--for names a board: the brief is read against that board's checkout — HEAD until a base is fetched",
       root == gsrc and ref == "HEAD")
    G = lambda text: gone(text, gsrc, ref)
    hit = G("GOAL: cc-old answers in one line.\n")
    ok("a GOAL naming a tool the tree no longer has: absent-path, naming the commit that deleted it",
       [s_ for s_, _ in hit] == ["absent-path"] and "(#12)" in hit[0][1])
    ok("…and the same by its path", any("core/bin/cc-old — deleted by" in l for _, l in G("FILES: core/bin/cc-old\n")))
    ok("a tool that is there is not a finding", G("GOAL: cc-kept answers in one line.\nFILES: core/bin/cc-kept\n") == [])
    ok("a path git never had is a tool the brief asks for, not one it lost",
       G("GOAL: a new cc-next tool.\nFILES: core/bin/cc-next\n") == [])
    ok("the deleted tool in the STORY is the good brief — WHY is not the fix scope",
       G("GOAL: cc-kept wakes a seat once.\n\nWHY: #12 deleted cc-old; do not go looking for core/bin/cc-old.\n") == [])
    ok("…nor is a boundary clause naming it", G("FILES: core/bin/cc-kept; do not touch core/bin/cc-old.\n") == [])
    ok("a directory that is there, written with its slash, is not a deletion", G("SCOPE: core/ only.\n") == [])
    hit = G("GOAL: PR #12 is open and its review wants a line fixed.\n")
    ok("a brief that says a PR is open when it has merged: merged-pr, naming the squash commit",
       [s_ for s_, _ in hit] == ["merged-pr"] and "(#12)" in hit[0][1])
    ok("…in any of its spellings", all(G(t) for t in ("GOAL: fix the finding on PR #12 (in review).\n",
                                                        "GOAL: the open PR #12 gets a typo fixed.\n",
                                                        "FIX: get it in before #12 lands.\n")))
    ok("sequencing on a PR is not a claim that it is open — the merge satisfies it rather than falsifying it",
       G("GOAL: cc-kept says less.\nSCOPE: dispatch only after #12 lands, once #13 has merged.\n") == [])
    ok("a PR that has not merged is not a finding", G("GOAL: PR #77 is open and wants a typo fixed.\n") == [])
    # THE STATE WORD IS PREDICATED OF THE PR (review of #548): a merged PR mentioned near one of this repo's everyday
    # words is not a claim that it is open — not one comma away, and not through an `and`, which is not a connector
    # here at all. With no copula, no "still" and no bracket, the state word has to end the clause.
    ok("a merged PR named near an everyday word is not named as open",
       all(G(t) == [] for t in ("GOAL: since #494 landed, a queued row is dispatched twice.\n",
                                "GOAL: since #494, queued rows are dispatched twice.\n",
                                "GOAL: close #494 and open the next row.\n",
                                "GOAL: since #494 the IN FLIGHT block lists a pending row twice.\n",
                                "GOAL: #494 left the door open to a second dispatch.\n")))
    ok("…while the PR itself said to be open still is",
       all(G(t) for t in ("GOAL: PR #494, which sits in review, wants a line fixed.\n",
                          "GOAL: #494 has not yet merged and its finding is ours.\n",
                          "GOAL: #494, still open, is ours to finish.\n",
                          "GOAL: the review of #494, unmerged, wants a line fixed.\n")))
    ok("a PR in the story is not one either", G("GOAL: cc-kept says less.\n\nWHY: PR #12 was open for a week.\n") == [])
    # THE BASE AS FETCHED, NOT THE WORKING FILES: the checkout is whatever was last pulled, and the deletion that
    # landed since is the one a brief written today misses. origin/main is put at HEAD and the checkout wound back.
    ggit("update-ref", "refs/remotes/origin/main", "HEAD")
    ggit("checkout", "-q", "HEAD~1")     # detached: core/bin/cc-old is back on disk; origin/main still lacks it
    root, ref = tree_for("gonerepo/t")
    ok("once the base is fetched, that is the ref read", ref == "origin/main")
    ok("…and a file the checkout has but the base lacks is absent — the tree is the base, not the disk",
       os.path.isfile(os.path.join(gsrc, "core", "bin", "cc-old"))
       and [s_ for s_, _ in gone("GOAL: cc-old answers.\n", gsrc, ref)] == ["absent-path"])
    here = os.getcwd(); os.chdir(tmp)
    try: nowhere = tree_for("")
    finally: os.chdir(here)
    ok("no board and no git tree is nothing to check against — never a refusal", nowhere == ("", ""))
    # …AND AT THE DOOR: a warning with the commit, exit 0, and the good brief through in silence.
    def door(text):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = check(text, for_="gonerepo/t")
        return rc, err.getvalue()
    rc, err = door("GOAL: cc-old answers in one line.\n")
    ok("at the door a brief naming an absent tool is WARNED (exit 0), with the commit and the way out",
       rc == 0 and "WARNING" in err and "absent-path" in err and "(#12)" in err and "git show" in err)
    rc, err = door("GOAL: PR #12 is open and wants a line fixed.\n")
    ok("…and so is one whose named PR has merged", rc == 0 and "merged-pr" in err and "(#12)" in err)
    ok("the good brief passes the door in silence",
       door("GOAL: cc-kept wakes a seat once.\n\nWHY: #12 deleted cc-old; the wake moved here.\n") == (0, ""))

    print(f"\ncc-brief selfcheck: {p} passed, {f} failed")
    return 1 if f else 0
