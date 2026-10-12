# cc-i2m's selfcheck: the cases behind `cc-i2m selfcheck`. Not a module: cc-i2m execs this file INSIDE ITS OWN
# NAMESPACE and calls the selfcheck() it defines, so every name here is the tool's. No module docstring (it would
# replace the tool's __doc__) and no top-level name but the def below.

def selfcheck():
    """Each case builds its own board, queue.log, git and waits lines in memory (never the box's) and measures only
    those, asserting the stage that is counted and the one that is not."""
    import tempfile
    D = "2026-01-10"
    T = lambda hm: f"{D}T{hm}:00Z"                       # "10:05" -> a stamp on the fixture day
    E = lambda hm: epoch_of(T(hm))
    LO, HI = day_epoch(D), day_epoch(D) + 86400

    def board(rows, log=()):
        return {"tracks": {n: {"title": n, "status": "merged", "pr": f"https://x/r/pull/{pr}" if pr else "",
                               "created": T(c), "notes": [], **extra} for n, pr, c, extra in rows},
                "log": [{"ts": T(hm), "track": n, "msg": m} for hm, n, m in log]}

    def q(*lines):
        return [f"{T(hm)}\t{text}\n" for hm, text in lines]

    def git(*merges):                                     # (hh:mm, subject) -> `git log --format=%ct%x09%s` lines
        return [f"{E(hm)}\t{subject}\n" for hm, subject in merges]

    def one(b, ql=(), wl=(), repo="r", **kw):
        got = measure(b, list(ql), list(wl), repo, LO, HI, **kw)
        return got[0]["stages"] if len(got) == 1 else got

    cases = []
    # 1. a full pipeline: every stage boundary from the row to the lane's merge
    s = one(board([("a", 1, "10:00", {})],
                  [("10:10", "a", "dispatched headless worker (loop 1)"), ("11:00", "a", "status -> review")]),
            q(("11:00", "queued r#1 who=w"), ("11:10", "stage r#1 lane"), ("11:20", "stage r#1 planned"),
              ("11:25", "stage r#1 gate gate=t ok=yes secs=60"), ("11:40", "stage r#1 verdict verdict=LAND"),
              ("11:45", "stage r#1 merged sha=x by=lander")))
    cases.append(("a lane's PR: brief, worker, lander (queued, then taken by the lane until planned) and checks, "
                  "adding up to its whole time",
                  (s["brief"], s["worker"], s["lander"], s["checks"], s["hold"]) == (600, 3000, 1200, 1500, 0)))
    # 2. a hand-built row: the `dispatched` stamp is its dispatch; with none at all the brief is 0, never negative
    b = board([("h", 2, "10:00", {"dispatched": T("10:30")}), ("n", 3, "10:00", {})],
              [("12:00", "h", "status -> review"), ("13:00", "h", "status -> merged"),
               ("12:00", "n", "status -> review"), ("13:00", "n", "status -> merged")])
    got = {p["row"]: p for p in measure(b, [], [], "r", LO, HI)}
    cases.append(("a hand-built row's `dispatched` stamp splits brief from worker; a row with none has brief 0 and "
                  "is counted as dispatch unknown",
                  got["h"]["stages"]["brief"] == 1800 and got["h"]["dispatch_known"]
                  and got["n"]["stages"]["brief"] == 0 and got["n"]["stages"]["worker"] == 7200
                  and not got["n"]["dispatch_known"] and summary(list(got.values()))["dispatch_unknown"] == 1))
    # 3. the dispatch: a session's `agent` handoff or a reconciled `status -> running` is not one, the headless
    #    worker's note before the PR opened is, and one after it opened is not (it was never this PR's worker)
    b = board([("old", 4, "01:00", {}), ("late", 5, "01:00", {})],
              [("01:05", "old", "agent @1:2 -> @3:2 (handoff)"), ("01:06", "old", "status -> running"),
               ("09:00", "old", "dispatched headless worker (loop 3)"), ("10:00", "old", "status -> review"),
               ("08:00", "late", "status -> review"), ("09:00", "late", "dispatched headless worker (loop 1)")])
    got = {p["row"]: p["stages"] for p in measure(b, [], [], "r", LO, HI, git(("11:00", "x (#4)"), ("11:00", "y (#5)")))}
    cases.append(("only a headless worker's dispatch note before the PR opened starts the worker: an agent handoff or "
                  "a reconciled running status leaves the wait in brief",
                  (got["old"]["brief"], got["old"]["worker"]) == (8 * 3600, 3600)
                  and (got["late"]["brief"], got["late"]["worker"]) == (0, 7 * 3600)))
    # 4. landed by hand: only `recorded` lines, so its whole open life is the seat's
    s = one(board([("m", 6, "10:00", {"dispatched": T("10:00")})],
                  [("11:00", "m", "status -> review"), ("12:00", "m", "status -> merged")]),
            q(("11:20", "recorded r#6 verdict=HANDBACK by=seat"), ("11:40", "recorded r#6 verdict=LAND by=seat")))
    cases.append(("a PR a seat landed by hand is seat time from its opening to its merge, a HANDBACK record with no "
                  "requeue after it included", (s["seat"], s["checks"], s["hold"], s["handback"]) == (3600, 0, 0, 0)))
    # 5. holds: a checking pass that finds a check red on main is main-red with its hold; a retry tick of a held PR
    #    keeps it held; a hold after a red check that is not red on main is hold
    def held(ok):
        return one(board([("x", 7, "10:00", {"dispatched": T("10:00")})], [("10:00", "x", "status -> review")]),
                   q(("10:00", "queued r#7 who=w"), ("10:00", "stage r#7 planned"),
                     ("10:10", f"stage r#7 gate gate=t ok={ok} secs=600"), ("10:10", "stage r#7 held"),
                     ("10:40", "stage r#7 queued"), ("10:40", "stage r#7 held"),
                     ("11:10", "stage r#7 planned"), ("11:20", "stage r#7 merged sha=x by=l")))
    red, other = held("main-red"), held("no")
    cases.append(("a checking pass that ends held on main red is main-red with its hold, retry ticks and all; a hold "
                  "after any other red check is hold",
                  (red["main-red"], red["hold"], red["checks"], red["lander"]) == (4200, 0, 600, 0)
                  and (other["hold"], other["main-red"], other["checks"]) == (3600, 0, 1200)))
    # 6. a handback round runs to the requeue, a query to the seat runs to its requeue, and both go back to lander
    s = one(board([("k", 8, "10:00", {"dispatched": T("10:00")})], [("10:00", "k", "status -> review")]),
            q(("10:00", "queued r#8 who=w"), ("10:05", "stage r#8 planned"), ("10:10", "stage r#8 handback"),
              ("11:10", "requeued r#8 who=w"), ("11:15", "stage r#8 checking"), ("11:20", "stage r#8 query"),
              ("13:20", "queued r#8 who=seat"), ("13:30", "stage r#8 lane"), ("13:35", "stage r#8 planned"),
              ("13:40", "stage r#8 merged sha=x by=l")))
    cases.append(("a handback runs to the push that requeues it and a query to the seat's requeue; each comes back "
                  "to the lander's queue",
                  (s["handback"], s["seat"], s["lander"], s["checks"]) == (3600, 7200, 1500, 900)))
    # 7. a seat's recorded HANDBACK during a query is a fix round from there to the requeue
    s = one(board([("y", 9, "10:00", {"dispatched": T("10:00")})], [("10:00", "y", "status -> review")]),
            q(("10:00", "queued r#9 who=w"), ("10:00", "stage r#9 planned"), ("10:10", "stage r#9 query"),
              ("10:40", "recorded r#9 verdict=HANDBACK by=seat"), ("11:40", "queued r#9 who=w"),
              ("11:40", "stage r#9 planned"), ("11:50", "stage r#9 merged sha=x by=l")))
    cases.append(("a seat's HANDBACK record inside a query turns the rest of it into a fix round",
                  (s["seat"], s["handback"], s["checks"]) == (1800, 3600, 1200)))
    # 8. green slot waits: this row's, inside its worker span, come out of worker; another row's do not count
    s = one(board([("g", 10, "10:00", {"dispatched": T("10:00")})], [("12:00", "g", "status -> review"),
                                                                     ("12:30", "g", "status -> merged")]),
            wl=[f"{T('10:30')}\t{T('11:00')}\tg\tlander-check\t1800\n", f"{T('10:45')}\t{T('11:15')}\tg\tx\t1800\n",
                f"{T('10:00')}\t{T('12:00')}\tother\tx\t7200\n", f"{T('12:10')}\t{T('12:20')}\tg\tx\t600\n"])
    cases.append(("a row's own green slot waits inside its worker span are green (overlaps counted once); another "
                  "row's, or one after the PR opened, are not", (s["green"], s["worker"]) == (2700, 4500)))
    # 9. the merged set comes from git: a row the board never moved to merged, and a PR with no row at all, count
    b = board([("stuck", 11, "09:00", {"status": "review"})], [("09:30", "stuck", "status -> review")])
    got = {p["pr"]: p for p in measure(b, q(("10:00", "queued r#12 who=w"), ("10:05", "stage r#12 planned")), [],
                                       "r", LO, HI, git(("12:00", "fixed it (#11)"), ("11:00", "split (#12)"),
                                                        ("08:00", "chore without a number")))}
    cases.append(("git's merges decide the set: a row still in review whose PR merged counts, and a PR with no row "
                  "counts from its first queue line",
                  sorted(got) == [11, 12] and got[11]["total"] == 3 * 3600 and got[11]["row"] == "stuck"
                  and got[12]["row"] == "" and not got[12]["on_board"] and got[12]["title"] == "split"
                  and got[12]["total"] == 3600 and got[12]["stages"]["checks"] == 3300))
    # 10. a row with no `pr` is found by its branch tip, by its title, or by `(#N` in its title; a row that names
    #     another PR is never taken
    b = board([("tip", 0, "08:00", {}), ("titled", 0, "08:00", {"title": "Same words"}),
               ("split", 0, "08:00", {"title": "Checks for #13, split out (#15, draft)"}),
               ("other", 99, "08:00", {"title": "Same words"})],
              [("09:00", "tip", "status -> review"), ("09:00", "titled", "status -> review"),
               ("09:00", "split", "status -> review")])
    got = {p["pr"]: p["row"] for p in measure(
        b, q(("09:30", "recorded r#13 verdict=LAND by=s head=abcdef123456")), [], "r", LO, HI,
        git(("10:00", "Tip words (#13)"), ("10:00", "Same words (#14)"), ("10:00", "Checks (#15)")),
        ["abcdef1234567890 refs/remotes/origin/track/tip\n", "0123456789ab refs/heads/track/titled\n"])}
    cases.append(("a row with no PR link is found by its branch tip, its title, or a `(#N` in its title",
                  got == {13: "tip", 14: "titled", 15: "split"}))
    # 11. a PR the board never saw open: its branch's first commit stands in for the opening
    b = board([("seat", 0, "06:00", {"title": "seat built (#16)"})])
    got = {p["pr"]: p for p in measure(b, q(("09:00", "recorded r#16 verdict=LAND by=s"),
                                            ("10:00", "recorded r#17 verdict=LAND by=s")), [], "r", LO, HI,
                                       git(("11:00", "seat built (#16)"), ("11:00", "no row (#17)")), (),
                                       first_commit={"seat": E("05:00"), "nr": E("07:00")}.get)}
    cases.append(("with no review line the branch's first commit is the opening, before the row if need be; with "
                  "neither, the first queue line is",
                  got[16]["total"] == 6 * 3600 and got[16]["stages"]["seat"] == 6 * 3600
                  and got[17]["total"] == 3600 and got[17]["stages"]["seat"] == 3600))
    # 12. the window: a PR merged the day after is not in it, and a queue line of another repo is never read; a merge
    #     the lander logged that git has not fetched still counts
    b = board([("in", 18, "10:00", {}), ("out", 19, "10:00", {})],
              [("11:00", "in", "status -> merged"), ("11:00", "out", "status -> merged")])
    got = measure(b, q(("10:30", "stage o#18 merged sha=x by=l")), [], "r", LO, HI)
    late = measure(board([("late", 20, "10:00", {})]), [f"2026-01-11T01:00:00Z\tstage r#20 merged sha=x by=l\n"],
                   [], "r", LO, HI)
    unfetched = measure(board([("lf", 21, "10:00", {})]), q(("12:00", "stage r#21 merged sha=x by=l")), [], "r", LO,
                        HI, git(("11:00", "something else (#22)")))
    cases.append(("a PR merged outside the window is left out; another repo's queue line does not move this one's "
                  "merge; the lander's merge line counts when git has not fetched it",
                  [p["row"] for p in got] == ["in", "out"] and got[0]["total"] == 3600 and late == []
                  and [p["pr"] for p in unfetched] == [21, 22] and unfetched[0]["total"] == 7200))
    # 13. the verdict names the stage with the most total time, and the text and --json say the same
    b = board([("a", 1, "10:00", {"dispatched": T("10:00")}), ("b", 2, "10:00", {"dispatched": T("12:00")})],
              [("10:30", "a", "status -> review"), ("11:00", "a", "status -> merged"),
               ("12:10", "b", "status -> review"), ("12:20", "b", "status -> merged")])
    prs = measure(b, [], [], "r", LO, HI)
    sm = summary(prs)
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "boards"))
    with open(os.path.join(d, "boards", "r.json"), "w") as f:
        json.dump(b, f)
    env = {k: os.environ.get(k) for k in ("CC_BOARDS", "CC_LANDER_STATE", "CC_GREEN_DIR")}
    os.environ.update(CC_BOARDS=os.path.join(d, "boards"), CC_LANDER_STATE=os.path.join(d, "land"),
                      CC_GREEN_DIR=os.path.join(d, "green"))
    import io, contextlib
    try:
        txt, js = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(txt):
            rc1 = main(["--repo", "r", "--from", D, "--to", D])
        with contextlib.redirect_stdout(js):
            rc2 = main(["--repo", "r", "--from", D, "--json"])
    finally:
        for k, v in env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    j = json.loads(js.getvalue() or "{}")
    cases.append(("the verdict names the biggest stage by total, and the table and --json carry the same verdict",
                  sm["biggest"] == "brief" and sm["verdict"].startswith("the biggest stage is brief: 2h00m of 3h20m (60%)")
                  and rc1 == 0 and rc2 == 0 and f"verdict: {sm['verdict']}" in txt.getvalue()
                  and j.get("verdict") == sm["verdict"] and j["stages"]["brief"]["total"] == 7200
                  and j["to"] == time.strftime("%Y-%m-%d", time.gmtime())))
    cases.append(("an empty window says so rather than naming a stage",
                  summary([])["verdict"] == "no PR merged in this window" and summary([])["biggest"] == ""))
    # 14. the git readers: a squash subject's number, track/ branch tips local and remote, nothing else
    cases.append(("git_merges keeps a `(#N)` subject's number and newest time; branch_tips reads only track/ refs",
                  git_merges(["200\tb (#5)\n", "100\ta (#5)\n", "50\tno number\n"]) == {5: (200, "b")}
                  and branch_tips(["abc1234 refs/heads/track/x\n", "def5678 refs/remotes/origin/track/y\n",
                                   "0123456 refs/heads/main\n"]) == [("abc1234", "x"), ("def5678", "y")]))
    bad = [name for name, ok in cases if not ok]
    print("\n".join(("  ok   " if ok else "  FAIL ") + name for name, ok in cases))
    print(f"cc-i2m selfcheck: {len(cases) - len(bad)} passed, {len(bad)} failed")
    return 1 if bad else 0
