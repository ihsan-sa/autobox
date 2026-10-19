# cc-reconcile's selfcheck: the cases behind `cc-reconcile selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-reconcile execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

# ── selfcheck ────────────────────────────────────────────────────────────────────────────────────────────
def selfcheck():
    """The decision table, then one end-to-end run of each part against a throwaway HOME. No network, no Slack."""
    import tempfile
    global BOARDS                          # declared once, up top: a later read of it must not predate this
    globals().update(FILE_REMOTES=True)     # the fixtures' origins are local bare repos
    os.environ["CC_LIMIT_RESUMED"] = os.path.join(tempfile.gettempdir(), "cc-reconcile-selfcheck-no-episode")
    p = f = 0

    def ok(name, cond):
        nonlocal p, f
        if cond:
            p += 1
        else:
            f += 1
            print(f"  ✗ {name}")

    def F(**kw):
        d = {"status": "running", "pr": "", "pr_state": None, "live": False, "wt_exists": True,
             "age": 10 ** 6, "grace": GRACE, "journal": (None, ""), "loop_end": "",
             "commit_err": False, "push_err": False, "unpushed": True, "has_remote": True,
             "limited": False, "loops": [], "workers": [], "pane_idle": 0.0,
             "agent": "", "agent_live": False, "agent_stale": "", "held": "",
             "delivery": True, "started": False, "worked": False}   # every existing case below is a row that
        d.update(kw)
        return d

    def one(**kw):
        r = decide(F(**kw))
        return (r[0][0], r[0][1]) if r else ("none", None)

    def eff(**kw):                                      # the ONE word: what a consumer of the snapshot reads
        return effective(F(**kw), decide(F(**kw)))

    ok("live worker in a blocked track → running", one(status="blocked", live=True) == ("fix", "running"))
    ok("…BUT A SESSION SITTING IDLE AT ITS PROMPT IN THE WORKTREE IS NOT A WORKER: `blocked` and `waiting` are a "
       "session's words, and flipping one back to `running` on that presence alone reverted a correction within "
       "minutes, three times over two pulses (a member workspace's row, raised 2026-09-10). The brief: 'a status "
       "a session set is not reverted by decide() while no pane is live' — the word stands, and nothing is asked",
       decide(F(status="blocked", live=True, pane_idle=3 * 3600)) == []
       and decide(F(status="waiting", live=True, pane_idle=3 * 3600)) == [])
    ok("…while a pane moved inside IDLE, a worker or a loop IS work in flight and still flips it — and "
       "`queued`/`todo` is nobody's word, so an idle session in that worktree still makes it running",
       one(status="blocked", live=True, pane_idle=600) == ("fix", "running")
       and one(status="waiting", live=True, pane_idle=600) == ("fix", "running")
       and one(status="blocked", live=True, pane_idle=3 * 3600, workers=[1]) == ("fix", "running")
       and one(status="blocked", live=True, pane_idle=3 * 3600, loops=[1]) == ("fix", "running")
       and one(status="queued", live=True, pane_idle=3 * 3600) == ("fix", "running")
       and one(status="todo", live=True, pane_idle=3 * 3600) == ("fix", "running"))
    ok("…AND A BARE `agent` MARK IS NOT WORK IN FLIGHT EITHER: the re-mark loop keeps `agent_at` fresh for as "
       "long as the seat lives, so a row a session set to `blocked`/`waiting` and left marked was flipped back "
       "to `running` on every pass with no pane in the track's window at all (raised 2026-09-19). The word "
       "stands and nothing is asked; the mark still flips a `queued` row, which is nobody's word",
       decide(F(status="blocked", agent="@3:900", agent_live=True)) == []
       and decide(F(status="waiting", agent="@3:900", agent_live=True)) == []
       and one(status="queued", agent="@3:900", agent_live=True) == ("fix", "running"))
    ok("live worker in a merged track is not un-merged", one(status="merged", live=True, pr="u", pr_state="MERGED") == ("none", None))
    ok("running + no worker, but dispatched seconds ago → left alone", one(age=5, grace=600) == ("none", None))
    ok("journal BLOCKED → waiting, and the owner is asked",
       decide(F(journal=("BLOCKED", "which one?")))[0][:2] == ("ask", "waiting"))
    ok("the blocked question is carried, not summarised", "which one?" in decide(F(journal=("BLOCKED", "which one?")))[0][2])
    ok("journal DONE + merged PR → merged", one(journal=("DONE", ""), pr="u", pr_state="MERGED") == ("fix", "merged"))
    ok("journal DONE + open PR → review", one(journal=("DONE", ""), pr="u", pr_state="OPEN") == ("fix", "review"))
    ok("journal DONE + no PR → asks (nobody opened one)", one(journal=("DONE", "")) == ("ask", "review"))
    ok("loop exit → blocked, with the loop's own reason", decide(F(loop_end="exit 4: stalled"))[0][:2] == ("ask", "blocked"))
    ok("nothing says why → blocked and the owner hears about it", one() == ("ask", "blocked"))
    ok("…BUT A LAUNCH WAITING IN cc-room's QUEUE IS DISPATCHED, NOT ABANDONED: the word stands, nobody is asked, and "
       "the one line says it waits for room (raised 2026-10-03: a lessons row 3 h in the queue was set blocked 'no "
       "worker, and nothing says why' and its seat woken to find it only queued)",
       decide(F(room="waiting")) == [("held", None, "its launch is waiting in cc-room's queue for room")]
       and decide(F(status="waiting", room="waiting"))[0][:2] == ("held", None)
       and eff(status="queued", room="waiting") == "queued")
    ok("…and one a restart took (the waiter died with its tmux server, the entry kept for `cc-room resume`) says "
       "that, not 'killed, or the box restarted'", decide(F(room="lost"))[0][:2] == ("held", None)
       and "cc-room resume" in decide(F(room="lost"))[0][2])
    ok("…and one whose worktree cc has not made yet (cc makes it at launch) gets the held line alone, never 'its "
       "worktree is gone' beside it for the whole wait",
       decide(F(room="waiting", wt_exists=False)) == [("held", None, "its launch is waiting in cc-room's queue for room")])
    ok("…and a `blocked` row whose launch waits keeps its word and the report says the launch waits, not nothing",
       decide(F(status="blocked", room="waiting")) == [("held", None, "its launch is waiting in cc-room's queue for room")]
       and eff(status="blocked", room="waiting") == "blocked")
    ok("…while a live worker still outranks the queue entry: it is running", one(status="queued", live=True, room="waiting")
       == ("fix", "running"))
    ok("review + merged PR → merged", one(status="review", pr="u", pr_state="MERGED") == ("fix", "merged"))
    ok("a blocked or review row whose branch landed → merged, and no 'PR never opened' ask beside it",
       one(status="blocked", landed="its branch landed inside #5") == ("fix", "merged")
       and decide(F(status="review", landed="x")) == [("fix", "merged", "x")])
    ok("a landed row outranks a stale STATUS: BLOCKED question: merged, not `waiting` and asked again every run",
       decide(F(status="blocked", landed="x", journal=("BLOCKED", "which one?"))) == [("fix", "merged", "x")]
       and one(status="review", landed="x", journal=("BLOCKED", "q")) == ("fix", "merged"))
    ok("…but `landed` never moves a row that is not blocked or review", one(status="waiting", landed="x")[1] != "merged"
       and one(status="queued", landed="x")[1] != "merged")
    ok("merged + open PR → review", one(status="merged", pr="u", pr_state="OPEN") == ("fix", "review"))
    ok("closed-not-merged PR is never guessed at", one(status="review", pr="u", pr_state="CLOSED") == ("ask", None))
    ok("an unreadable PR state is unknown, not a fix", one(status="review", pr="u", pr_state="?") == ("info", None))
    ok("no network → no PR verdict at all", one(status="review", pr="u", pr_state=None) == ("none", None))
    ok("a missing worktree is reported, not repaired",
       ("ask", None, "its worktree is gone") in decide(F(status="review", wt_exists=False)))
    ok("…but a `review` row whose PR is open is not asked about a worktree it never had",
       not any("worktree" in w for _, _, w in decide(F(status="review", pr="u", pr_state="OPEN", wt_exists=False))))
    ok("…while a PR number nobody could confirm silences nothing — only OPEN or MERGED says origin has the branch",
       all(("ask", None, "its worktree is gone") in decide(F(status="review", pr="u", pr_state=ps, wt_exists=False))
           for ps in (None, "?", "CLOSED")))
    ok("…and `running` and `waiting` are asked whatever their PR says — those words claim a worker is in one, so "
       "the word this run lands on must not silence the one the board still carries",
       all(("ask", None, "its worktree is gone") in decide(F(status=s_, pr="u", pr_state="OPEN", wt_exists=False))
           for s_ in ("running", "waiting")))
    ok("a merged track's missing worktree is normal", decide(F(status="merged", wt_exists=False)) == [])
    ok("a track that never started is not missing a worktree — under either word for it, since boards written before "
       "the board spoke `queued` still say `todo`",
       decide(F(status="queued", wt_exists=False)) == [] and decide(F(status="todo", wt_exists=False)) == []
       and decide(F(status="queued", live=True))[0][:2] == ("fix", "running"))
    ok("…AND SO IS ONE `word` MOVED OFF QUEUED BY HAND: a person or session can set any status straight onto a "
       "row (`cc-board status`/`note`), dispatch or not — lessons/tutor-on-a-member-lesson was `queued`, never "
       "claimed, only a task.md and no worktree ever, and a note marking it `blocked` (nothing wrong with "
       "starting) was read as a lost worktree. `delivery` is cc-task's claim record, not the board's word, and "
       "a row nothing ever claimed has none",
       decide(F(status="blocked", wt_exists=False, delivery=False)) == [])
    ok("…BUT A ROW cc-task DID CLAIM keeps being asked about, whatever word it wears now: the claim record "
       "outlives the worktree it was made for",
       ("ask", None, "its worktree is gone") in decide(F(status="blocked", wt_exists=False, delivery=True)))
    ok("…AND SO DOES ONE `cc <repo> <track>` STARTED INTERACTIVELY, EVEN WITH NO CLAIM ON FILE: __run/__runmember "
       "and cc-handoff set the board's `started` flag without ever calling `cc-task claim`, so `delivery` alone "
       "misses this dispatch path — `started` catches it",
       ("ask", None, "its worktree is gone") in decide(F(status="blocked", wt_exists=False, delivery=False, started=True)))
    ok("…AND SO DOES ONE THE LEGACY WORKER PATH RAN, EVEN WITH NEITHER A CLAIM NOR `started` ON FILE: `cc <repo> "
       "<track> --go` predates cc-task claim and never sets the board's `started` flag, but a row it actually "
       "ran left a progress.md or loop.log — `worked` catches it, and the never-claimed `blocked` case above "
       "stays empty",
       ("ask", None, "its worktree is gone") in decide(F(status="running", wt_exists=False, delivery=False, started=False, worked=True)))
    ok("A ROW THAT NEVER RAN IS NEVER STARTED, NOT LOST: no claim, not started, no journal, no worktree — a row made "
       "with its project channel and given `running` by hand — is asked about in ONE line that says nothing was "
       "lost; the same word on a row cc-task did claim keeps 'killed, or the box restarted' AND 'its worktree is "
       "gone' (raised 2026-09-11, a member workspace's row). The brief: reported as never started, not as lost",
       decide(F(status="running", wt_exists=False, delivery=False, started=False, worked=False))
       == [("ask", "blocked", "never started: no claim, no worktree, no journal — the word was set by hand, "
                              "nothing was lost")]
       and [w for _, _, w in decide(F(status="running", wt_exists=False, delivery=True))]
       == ["no worker, and nothing says why (killed, or the box restarted)", "its worktree is gone"])
    ok("…and a cold mark still says what happened to a row nothing else ever ran: the mark's reason outranks "
       "never-started, which outranks lost",
       decide(F(status="running", wt_exists=False, delivery=False, started=False, worked=False,
                agent="@3:900", agent_stale="marked by a live session 6 h ago, mark expired"))
       == [("ask", "blocked", "marked by a live session 6 h ago, mark expired")])
    ok("a refused checkpoint is a finding", any("checkpoint" in w for _, _, w in decide(F(status="review", pr="u", commit_err=True))))
    unp = lambda **kw: any("not pushed" in w for _, _, w in decide(F(status="review", pr="u", **kw)))
    ok("an unpushed branch is a finding: the marker AND commits origin does not have", unp(push_err=True, unpushed=True))
    ok("…but the marker alone is not — a worktree origin already has is not nagged, however old its push.err",
       not unp(push_err=True, unpushed=False))
    ok("…and neither is a branch with work origin lacks but no failed push to say so",
       not unp(push_err=False, unpushed=True))
    ok("…while a branch the box could not judge (never fetched, detached HEAD) keeps the marker's answer, because "
       "silence about a real unpushed branch is the worse of the two", unp(push_err=True, unpushed=None))
    with tempfile.TemporaryDirectory() as tm:
        os.makedirs(f"{tm}/dev/ws/.cc"); open(f"{tm}/dev/ws/.cc/member-workspace", "w").close()
        ok("a member workspace's failed-push marker is the HOST's own, under ~/.cc/push-state — the file in the "
           "worktree is the member's, and nothing on the host writes or clears it",
           push_marker("ws", "t", tm) == f"{tm}/.cc/push-state/ws/t/push.err")
        ok("…while every other repo keeps it in the worktree, where the hook that writes it clears it",
           push_marker("plain", "t", tm) == f"{tm}/.cc/worktrees/plain/t/.cc/push.err")
        wtd, psd = f"{tm}/.cc/worktrees/ws/t/.cc", f"{tm}/.cc/push-state/ws/t"
        os.makedirs(wtd); os.makedirs(psd)
        def cm():   # the path AND whether it lit, read together: a path captured alone is falsified by the next rm
            p = commit_marker("ws", "t", tm)
            return p, os.path.exists(p)
        cm_none = cm()
        open(f"{wtd}/checkpoint.err", "w").close(); open(f"{wtd}/push.err", "w").close()   # the member's own two
        cm_member, pm_member = cm(), push_marker("ws", "t", tm)
        open(f"{psd}/checkpoint.err", "w").close()
        cm_both = cm()
        os.unlink(f"{wtd}/checkpoint.err")
        cm_host = cm()
        ok("a member workspace's `commit!` is lit by EITHER refusal — the host's under ~/.cc/push-state (what `cc "
           "done` writes) or the member's own in-boundary <wt>/.cc/checkpoint.err, the only place their hook can "
           "write; with neither there is nothing to light and the host's path is what a writer gets",
           cm_none == (f"{psd}/checkpoint.err", False) and cm_member == (f"{wtd}/checkpoint.err", True)
           and cm_both == (f"{psd}/checkpoint.err", True) and cm_host == (f"{psd}/checkpoint.err", True))
        ok("…while the failed push stays the HOST's alone, with the member's own push.err sitting right there and "
           "lighting nothing: theirs is credential-less by design, so it is rewritten every turn and cleared by "
           "nothing on the host, and reading it nagged for ever about a branch the sweep had pushed",
           pm_member == f"{psd}/push.err" and not os.path.exists(pm_member))
        ok("…and every other repo has one place for both, the worktree, where the hook that writes them clears them",
           commit_marker("plain", "t", tm) == f"{tm}/.cc/worktrees/plain/t/.cc/checkpoint.err")
    mrg = dict(status="merged", pr="u", pr_state="MERGED", push_err=True, unpushed=None, commit_err=True)
    ok("a merged row says nothing about its branch, its worktree or its last checkpoint: the merge deleted the "
       "branch, which is success", decide(F(**mrg)) == [] and decide(F(**dict(mrg, wt_exists=False))) == [])
    ok("…and `done` is the other finished word, with no PR to re-read and the same silence",
       decide(F(status="done", push_err=True, unpushed=None, commit_err=True, wt_exists=False)) == [])
    ok("…while a branch that is genuinely unpushed on a row nobody merged still says so, once its loop has ended",
       any("not pushed" in w for _, _, w in decide(F(status="running", live=False, push_err=True, unpushed=True))))
    # "shouldn't alert 'its branch is not pushed' while the row's worker loop is still alive (live loop.pid, or a
    # live window for the row)": top-harden-lef-pin-only and -macro-fill were told mid-iteration 1, nothing to push yet
    for alive in (dict(live=True), dict(agent_live=True)):
        ok(f"UNPUSHED WHILE RUNNING: a row whose worker is still alive ({next(iter(alive))}) is not told its branch "
           "is not pushed, however sure the box is; the same row with its loop ended is",
           not any("not pushed" in w for _, _, w in decide(F(status="running", push_err=True, unpushed=True, **alive)))
           and any("not pushed" in w for _, _, w in decide(F(status="running", push_err=True, unpushed=True))))
    for w_ in ("merged", "done"):
        ok(f"a `{w_}` row whose branch really does hold commits origin lacks is STILL told, though the same row is "
           "forgiven a branch the box could not judge — a fact is not a doubt",
           any("not pushed" in w for _, _, w in decide(F(status=w_, push_err=True, unpushed=True)))
           and not any("not pushed" in w for _, _, w in decide(F(status=w_, push_err=True, unpushed=None))))
    ok("…and that holds on the tick the PR merges too, when the row still says `review` and this run says `merged`",
       any("not pushed" in w for _, _, w in
           decide(F(status="review", pr="u", pr_state="MERGED", push_err=True, unpushed=True))))
    ok("…and the tick the PR merges is already finished: that run says `merged` and nothing about the branch",
       decide(F(status="review", pr="u", pr_state="MERGED", push_err=True, unpushed=None))
       == [("fix", "merged", "its PR merged")])
    ok("review with no PR and a remote → asks", any("never opened" in w for _, _, w in decide(F(status="review"))))
    ok("review with no PR and no remote is silent", decide(F(status="review", has_remote=False)) == [])
    ok("a quiet track says nothing", decide(F(status="review", pr="u", pr_state="OPEN")) == [])

    ok("a session ALIVE with a question for the owner is waiting, not running — the declaration outranks the pid, "
       "which is the whole bug: five of these said `running` for four hours",
       decide(F(status="running", live=True, journal=("BLOCKED", "which syllabus?")))[0][:2] == ("ask", "waiting"))
    ok("…and it is an ASK, so it reaches him, every run, for as long as the question stands",
       decide(F(status="waiting", live=True, journal=("BLOCKED", "which syllabus?")))[0][0] == "ask")
    ok("a worker BETWEEN ITERATIONS declared nothing and is simply running — not waiting on anyone",
       waits_for(F(live=True, loops=[2], workers=[1])) == ("", "")
       and decide(F(status="queued", live=True, loops=[2], workers=[1]))[0][:2] == ("fix", "running"))
    ok("a loop sitting out a usage limit waits on the CLOCK, not on a person, and never becomes an `ask`",
       waits_for(F(limited=True, loops=[2]))[0] == "clock"
       and [k for k, _, _ in decide(F(status="blocked", live=True, limited=True, loops=[2]))] == ["held"])
    ok("…and the two are told apart by WHO, not by the word `blocked`",
       waits_for(F(journal=("BLOCKED", "ship it?")))[0] == "person"
       and waits_for(F(limited=True, loops=[2]))[0] == "clock")
    ok("a limit standing over a track that is actually WORKING is not the clock's doing",
       waits_for(F(limited=True, loops=[2], workers=[1])) == ("", ""))
    ok("a stood-down track goes back to running by itself once its journal stops saying BLOCKED",
       decide(F(status="waiting", live=True))[0][:2] == ("fix", "running"))
    ok("…and with nobody in the worktree either, `waiting` is reconciled like a stale `running` is",
       decide(F(status="waiting", live=False))[0][:2] == ("ask", "blocked"))
    ok("`waiting` with a PR open is a person's word and survives --apply: reconciling it to `review` would erase it "
       "and the pending watchdog would nag on the next tick anyway (lessons#10; owner, 2026-09-01)",
       decide(F(status="waiting", pr="u", pr_state="OPEN")) == []
       and decide(F(status="waiting", pr="u", pr_state="OPEN", journal=("DONE", ""))) == []
       and decide(F(status="running", pr="u", pr_state="OPEN"))[0][:2] == ("fix", "review"))
    ok("…but the PR MERGING moves it: that is a fact, not a word — and a finish with no PR, or a PR closed "
       "without merging, is still reported, without touching the word",
       decide(F(status="waiting", pr="u", pr_state="MERGED", journal=("DONE", "")))[0][:2] == ("fix", "merged")
       and decide(F(status="waiting", journal=("DONE", "")))[0][:2] == ("ask", None)
       and decide(F(status="waiting", pr="u", pr_state="CLOSED", journal=("DONE", "")))[0][:2] == ("ask", None))
    ok("a merged track is never re-opened by an old question in its journal",
       decide(F(status="merged", journal=("BLOCKED", "old"), pr="u", pr_state="MERGED")) == [])
    ok("STATUS: BLOCKED with no question is still a declaration — it stopped, and only a person restarts it",
       decide(F(journal=("BLOCKED", "")))[0][:2] == ("ask", "waiting"))
    ok("nothing is ever inferred from prose: a journal that merely TALKS about waiting declares nothing",
       waits_for(F(journal=(None, "waiting on the owner for the syllabus"))) == ("", ""))
    ok("the snapshot's word is what decide() would set, not what the board says",
       effective(F(status="running", live=True, journal=("BLOCKED", "q")),
                 decide(F(status="running", live=True, journal=("BLOCKED", "q")))) == "waiting")
    ok("…and the board's own word when nothing disagrees with it",
       effective(F(status="review", pr="u", pr_state="OPEN"), []) == "review")
    ok("the snapshot carries who and why, which one status word cannot",
       snapshot([("r", "t", F(status="running", live=True), "waiting", "person", "which syllabus?")])
       ["tracks"]["r/t"] == {"state": "waiting", "board": "running", "kind": "track", "live": True,
                             "waiting_on": "person", "why": "which syllabus?", "idle_for": 0,
                             "loop": False, "agent": False, "launch": "", "held": ""})
    ok("…and a launch waiting in cc-room, which the wake reads so it never offers that row for a second dispatch",
       snapshot([("r", "t", F(status="queued", room="waiting"), "queued", "", "")])["tracks"]["r/t"]["launch"]
       == "waiting")
    ok("…and the three facts the Home tab and the wake used to read for themselves: a live loop, a live agent mark, "
       "a person's hold — so neither needs a process table, a tmux or a board field of its own",
       {k: v for k, v in snapshot([("r", "t", F(status="queued", loops=[2], agent="@1:9", agent_live=True, held=" mine "),
                                     "running", "", "")])["tracks"]["r/t"].items() if k in ("loop", "agent", "held")}
       == {"loop": True, "agent": True, "held": "mine"})
    ok("`todo` is an older board's word for `queued`, and the snapshot says `queued` — one vocabulary for every reader",
       eff(status="todo") == "queued" and eff(status="queued") == "queued")

    ok("a running row a LIVE session marked as its subagent's work is left alone past the grace, and raises "
       "no ask — the mark is the only thing on the box that says anybody is on it",
       decide(F(status="running", agent="@3:900", agent_live=True, age=10 ** 6)) == []
       and eff(status="running", agent="@3:900", agent_live=True) == "running")
    ok("…and the moment that session's window is gone the mark counts for nothing: the same row is reported "
       "abandoned, exactly as it was before any of this",
       decide(F(status="running", agent="@3:900", agent_live=False))[0][:2] == ("ask", "blocked"))
    ok("a marked row that is still `queued` is running, and says WHOSE — never 'a worker is in its worktree', "
       "which is the one thing that is not true of it; a `blocked` row the mark leaves alone entirely",
       decide(F(status="queued", agent="@3:900", agent_live=True))[0] == ("fix", "running", "a live session is doing it in a subagent")
       and decide(F(status="blocked", agent="@3:900", agent_live=True)) == []
       and decide(F(status="queued", live=True))[0][2] == "a worker is in its worktree")
    ok("…AND IT HAS NO WORKTREE: nothing dispatched it, so there is none to be gone, and the mark has to silence "
       "that rule too — otherwise the row it just made quiet goes back to NEEDS YOU on the same run",
       decide(F(status="queued", agent="@3:900", agent_live=True, wt_exists=False))
       == [("fix", "running", "a live session is doing it in a subagent")]
       and decide(F(status="running", agent="@3:900", agent_live=True, wt_exists=False)) == [])
    ok("A COLD MARK IS REPORTED WITH ITS AGE, not as 'nothing says why': the row IS unattended, and the one "
       "thing worth saying about it is that a session took it 9 h ago and never came back",
       decide(F(status="running", agent="@3:900", agent_stale="marked by a live session 9 h ago, mark expired"))
       == [("ask", "blocked", "marked by a live session 9 h ago, mark expired")])
    ok("…AND IT SAYS IT ONCE. A row marked while `queued` was flipped to `running` by the mark, and that word "
       "outlives the mark: with the worktree rule guarded on a LIVE mark, the same row drew 'mark expired' AND "
       "'its worktree is gone' 6 h later — a second NEEDS YOU line for a row that had none before it was marked",
       decide(F(status="running", agent="@3:900", agent_live=False, wt_exists=False,
                agent_stale="marked by a live session 6 h ago, mark expired"))
       == [("ask", "blocked", "marked by a live session 6 h ago, mark expired")])
    W, T0 = {"@3:900": "r"}, 1000 * 3600
    def stamp(secs_ago): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T0 - secs_ago))
    ok("a mark made a minute ago holds the row, and one made past the bound does not — with its age in the "
       "reason, so the run says what happened rather than 'nothing says why'",
       mark_why({"agent": "@3:900", "agent_at": stamp(60)}, W, "r", T0, AGENT_MARK) == (True, "")
       and mark_why({"agent": "@3:900", "agent_at": stamp(9 * 3600)}, W, "r", T0, AGENT_MARK)
       == (False, "marked by a live session 9 h ago, mark expired"))
    ok("…and a mark with no time on it holds nothing, which is every mark written before this: unreadable is "
       "'long ago' here as everywhere else, and the row comes back rather than sitting in flight for ever",
       mark_why({"agent": "@3:900"}, W, "r", T0, AGENT_MARK)[0] is False
       and mark_why({"agent": "@3:900"}, W, "r", T0, AGENT_MARK)[1] == "marked by a live session, but the mark carries no time")
    _rz = T0 - 3600.0       # an episode that BEGAN an hour before this run
    ok("a mark made before a limit that has since lifted is cold whatever its age, and the reason names the "
       "hour so the row says what happened to it",
       mark_why({"agent": "@3:900", "agent_at": stamp(5400)}, W, "r", T0, AGENT_MARK, _rz)
       == (False, "marked before the usage limit that began at "
                  + time.strftime("%H:%MZ", time.gmtime(_rz)) + " — that subagent died with it"))
    ok("…while a mark made DURING the episode, once the box was on the fallback, holds its row: the box did not "
       "stop for the limit, and that subagent is still working",
       mark_why({"agent": "@3:900", "agent_at": stamp(1800)}, W, "r", T0, AGENT_MARK, _rz) == (True, ""))
    ok("…and one made at the START second does not: that is the second the limit was first seen in",
       mark_why({"agent": "@3:900", "agent_at": stamp(3600)}, W, "r", T0, AGENT_MARK, _rz)[0] is False)
    ok("…and with no episode passed in, the age bound is the whole rule, which is what this file did before",
       mark_why({"agent": "@3:900", "agent_at": stamp(5400)}, W, "r", T0, AGENT_MARK) == (True, ""))
    ok("A MARK WHOSE SEAT HAS NOT TAKEN A TURN EXPIRES, however fresh the mark: a session's detached re-mark loop "
       "refreshes agent_at on a liveness poll a stalled seat passes, so an orch seat held its row 29 h without a "
       "turn (raised 2026-09-17). The seat's last turn is read beside the mark: none inside the window expires it "
       "with the hours in the reason; one inside the window holds; and a seat nothing says about keeps the clock "
       "it has, so the re-mark loop and this rule coexist",
       mark_why({"agent": "@3:900", "agent_at": stamp(60)}, W, "r", T0, AGENT_MARK, 0.0, T0 - 7 * 3600)
       == (False, "marked by a live session, but that seat has not taken a turn for 7 h — a re-mark is not a turn, "
                  "mark expired")
       and mark_why({"agent": "@3:900", "agent_at": stamp(60)}, W, "r", T0, AGENT_MARK, 0.0, T0 - 5 * 3600) == (True, "")
       and mark_why({"agent": "@3:900", "agent_at": stamp(60)}, W, "r", T0, AGENT_MARK, 0.0, None) == (True, ""))
    with tempfile.TemporaryDirectory() as _sd:
        # seat_turn on a REAL pane-shaped process tree: a shell whose child is a `claude` (a script by that name,
        # so comm reads claude) carrying --session-id, and cc-statusline's per-turn file for that id at a chosen
        # time — the walk, the argv read and the file are all the real thing. Then the seats that actually mark:
        # `cc <repo>` and `cc --orch` start theirs with NO --session-id (review of #538), so a second `claude` with
        # none, alone in its cwd, is found by that cwd — its transcript directory and the per-turn file whose
        # raw.cwd it is — and two such peers in one cwd are None, one never standing in for the other.
        open(f"{_sd}/claude", "w").write("#!/bin/sh\nsleep 30\n")
        os.chmod(f"{_sd}/claude", 0o755)
        for _d in ("sl", "pj", "seatA", "seatB"):
            os.makedirs(f"{_sd}/{_d}")

        def _spawn(args, cwd=None):                     # a pane's shell with a `claude` under it
            px = subprocess.Popen(["bash", "-c", f"{_sd}/claude {args}; true"], cwd=cwd,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(100):                        # until the shell's child has exec'd into `claude`
                try:
                    if any(open(f"/proc/{k}/comm").read().strip() == "claude"
                           for k in open(f"/proc/{px.pid}/task/{px.pid}/children").read().split()):
                        break
                except OSError:
                    pass
                time.sleep(0.05)
            return px
        _seat = _spawn("--session-id selfcheck-seat-1")
        _bare = subprocess.Popen(["sleep", "30"])       # a pane with no session under it
        _alone = _spawn("", cwd=f"{_sd}/seatA")         # no id, the one seat in its cwd
        _peers = [_spawn("", cwd=f"{_sd}/seatB"), _spawn("", cwd=f"{_sd}/seatB")]
        _keep_sl, _keep_pj = os.environ.get("CC_STATUSLINE_DIR"), PROJECTS
        os.environ["CC_STATUSLINE_DIR"] = f"{_sd}/sl"
        globals().update(PROJECTS=f"{_sd}/pj")
        try:
            _none = seat_turn(_seat.pid)
            open(f"{_sd}/sl/selfcheck-seat-1.json", "w").write("{}")
            _t7 = now() - 7 * 3600
            os.utime(f"{_sd}/sl/selfcheck-seat-1.json", (_t7, _t7))
            _got = seat_turn(_seat.pid)
            _cwd_none = seat_turn(_alone.pid)           # no id, nothing written for its cwd yet
            for _d in ("seatA", "seatB"):               # a transcript in each cwd's directory, 7 h old
                _pd = f"{_sd}/pj/" + re.sub(r"[/.]", "-", os.path.realpath(f"{_sd}/{_d}"))
                os.makedirs(_pd)
                open(f"{_pd}/some-session.jsonl", "w").write("{}\n")
                os.utime(f"{_pd}/some-session.jsonl", (_t7, _t7))
            _cwd_tr = seat_turn(_alone.pid)
            _t5 = now() - 5 * 3600                      # a per-turn file for that cwd, newer: the newer wins
            json.dump({"raw": {"cwd": f"{_sd}/seatA"}}, open(f"{_sd}/sl/other-id.json", "w"))
            os.utime(f"{_sd}/sl/other-id.json", (_t5, _t5))
            _cwd_sl = seat_turn(_alone.pid)
            _peer_none = [seat_turn(px.pid) for px in _peers]
        finally:
            os.environ.pop("CC_STATUSLINE_DIR", None) if _keep_sl is None else os.environ.update({"CC_STATUSLINE_DIR": _keep_sl})
            globals().update(PROJECTS=_keep_pj)
            _bare_none = seat_turn(_bare.pid)
            for _px in [_seat, _bare, _alone] + _peers:
                _px.kill()
                _px.wait(timeout=10)
        ok("seat_turn walks the pane's process tree to the `claude` under it, reads the session id off its command "
           "line and answers with cc-statusline's per-turn file for that id: the time that file says, and None "
           "before there is one, for a pane with no session under it, or for no pane — no evidence is None, "
           "never 'long ago'",
           _got is not None and abs(_got - _t7) < 2 and _none is None and _bare_none is None
           and seat_turn("") is None)
        ok("…AND A SEAT WITH NO --session-id IS FOUND BY ITS CWD, the seats that actually mark (`cc <repo>`, "
           "`cc --orch`; review of #538): None before anything is written for that cwd; the newest transcript in "
           "the cwd's directory once there is one; and the per-turn file whose raw.cwd is that cwd when it is "
           "newer — the seat's last turn, whichever file carries it",
           _cwd_none is None and _cwd_tr is not None and abs(_cwd_tr - _t7) < 2
           and _cwd_sl is not None and abs(_cwd_sl - _t5) < 2)
        ok("…while two seats with no id in ONE cwd say nothing about each other: both are None (cc-context's own "
           "'ambiguous cwd → no answer'), so a main seat and an orch sharing a checkout keep their clocks rather "
           "than one hiding behind the other's turns",
           _peer_none == [None, None])
    ok("…while a window that is gone, or is another repo's, is refused BEFORE the clock: there is no live "
       "session to name in the reason, and the row is reported exactly as any unattended row is",
       mark_why({"agent": "@9:900", "agent_at": stamp(60)}, W, "r", T0, AGENT_MARK) == (False, "")
       and mark_why({"agent": "@3:900", "agent_at": stamp(60)}, W, "other", T0, AGENT_MARK) == (False, ""))
    ok("the mark claims a session is alive and nothing else: a declared question still outranks it, and a "
       "merged row is still merged", decide(F(status="running", agent_live=True, journal=("BLOCKED", "q?")))[0][:2] == ("ask", "waiting")
       and decide(F(status="merged", agent_live=True, pr="u", pr_state="MERGED")) == [])
    ok("the snapshot counts a subagent as alive, so `cc ls` and the Home tab say the same thing this run did",
       snapshot([("r", "t", F(status="running", agent="@3:900", agent_live=True), "running", "", "")])
       ["tracks"]["r/t"]["live"] is True)
    P = ["proj\t100\t0\t@1:900", "proj/t1\t101\t0\t@2:900", "proj/t2\t999\t0\t@3:900",
         "proj\t102\t0\t", "other\t104\t0\t@4:900"]
    _live, _idle, _wins = panes(P, {"100", "101", "102", "104"}, {"100", "101"})
    ok("a window an `agent` mark can name is any window a SESSION is in — a planning session's is named for its "
       "repo alone, so the TRACK filter must not decide this, and the name comes back to be checked against it",
       _wins == {"@1:900": "proj", "@2:900": "proj/t1"} and _live == {"proj/t1"})
    _wo = {"@5:900": "proj@dash", "@6:900": "other@dash"}
    _at = {"agent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    ok("an orchestrator's mark holds its own repo's row, and still holds no other repo's",
       mark_why(dict(_at, agent="@5:900"), _wo, "proj", now(), 6 * 3600)[0]
       and not mark_why(dict(_at, agent="@6:900"), _wo, "proj", now(), 6 * 3600)[0])
    _started, _pid, _wid, _fw = False, "", "", {}
    with tempfile.TemporaryDirectory() as _ts:
        _sock = os.path.join(_ts, "tmux-%d" % os.getuid(), "default")   # where TMUX_TMPDIR=_ts resolves to
        os.makedirs(os.path.dirname(_sock), exist_ok=True)
        os.chmod(os.path.dirname(_sock), 0o700)         # tmux refuses a socket dir anyone else can read
        _keep = {k: os.environ.get(k) for k in ("TMUX", "TMUX_TMPDIR")}
        os.environ["TMUX_TMPDIR"] = _ts
        os.environ.pop("TMUX", None)
        def _tx(*a):
            try:
                return subprocess.run(["tmux", "-S", _sock, *a], capture_output=True, text=True, timeout=20)
            except Exception:                           # no tmux at all, or one that will not answer in time:
                return subprocess.CompletedProcess(a, 1, "", "")   # tmux_live swallows the same, and this case
        try:                                            # then goes RED with the rest — never a traceback
            if _tx("list-sessions").returncode != 0:    # nothing answers on our own socket: ours to make
                _started = _tx("-f", "/dev/null", "new-session", "-d", "-s", "notmain",
                               "-n", "proj@dash", "sleep 600").returncode == 0
            if _started:
                def _ask(fmt):
                    return _tx("display-message", "-p", "-t", "notmain:proj@dash", fmt).stdout.strip()
                _pid, _wid = _ask("#{pane_pid}"), _ask("#{window_id}:#{pid}")
                _fw = tmux_live({_pid}, {_pid})[2]
        finally:
            if _started:
                _tx("kill-session", "-t", "notmain")
            for _k, _v in _keep.items():
                os.environ.pop(_k, None) if _v is None else os.environ.update({_k: _v})
    ok("a real tmux window `<repo>@<alias>` in a session that is NOT `main` is read as that repo's, and its "
       "mark holds the row — an orch lives in a session of its own and every one of its rows turns on this",
       _started and _fw.get(_wid) == "proj@dash"
       and mark_why(dict(_at, agent=_wid), _fw, "proj", now(), 6 * 3600) == (True, "")
       and mark_why(dict(_at, agent=_wid), _fw, "other", now(), 6 * 3600) == (False, ""))
    ok("A CHILD IN THE PANE IS NOT A SESSION: a window left with a `tail -f` or an `htop` in it after the session "
       "exited has one for ever, and a mark on it would keep a row alive for ever — it is live for the TRACK "
       "rule and unusable as a mark, which is the difference the two tests exist for",
       "@4:900" not in _wins and panes(P, {"104"}, {"104"})[2] == {"@4:900": "other"})
    ok("…and a pane whose shell has no child is a leftover window, in neither: `cc` leaves one behind an exited "
       "session (exec bash)", "@3:900" not in _wins and "proj/t2" not in _live)
    ok("the mark carries the tmux SERVER too, because window ids restart at @0 when the server does — a mark "
       "left by a session that died in a reboot must not match whatever window is @1 now",
       "@1:900" in _wins and "@1:901" not in _wins)
    with tempfile.TemporaryDirectory() as tb:
        _B, _W, _pr, _tl = BOARDS, WTS, procs, tmux_live
        _wp, _stn = window_panes, seat_turn
        globals().update(BOARDS=tb, WTS=tb,
                         procs=lambda: (set(), set(), {"7"}, {}, {}),
                         tmux_live=lambda ppids, sessions=(): (
                             set(), {}, {"@5:900": "agentrepo", "@6:900": "otherrepo", "@7:900": "agentrepo"}),
                         window_panes=lambda: {"@5:900": "5000", "@7:900": "7000"},
                         seat_turn=lambda pid: {"5000": time.time() - 60, "7000": time.time() - 7 * 3600}.get(pid))
        try:
            for tr in ("t2", "t3"):
                os.makedirs(f"{tb}/agentrepo/{tr}")
            _fresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
            json.dump({"repo": "agentrepo", "tracks": {
                "t1": {"status": "running", "agent": "@5:900", "agent_at": _fresh, "updated": "2020-01-01T00:00:00Z"},
                "t2": {"status": "running", "agent": "@6:900", "agent_at": _fresh, "updated": "2020-01-01T00:00:00Z"},
                "t3": {"status": "running", "updated": "2020-01-01T00:00:00Z"},
                "t4": {"status": "running", "agent": "@5:900", "agent_at": "2020-01-01T00:00:00Z",
                       "updated": "2020-01-01T00:00:00Z"},
                "t5": {"status": "running", "agent": "@7:900", "agent_at": _fresh, "updated": "2020-01-01T00:00:00Z"}}},
                open(f"{tb}/agentrepo.json", "w"))
            got = {tr: fa for _, tr, _, fa in facts(["agentrepo"], net=False)}
        finally:
            globals().update(BOARDS=_B, WTS=_W, procs=_pr, tmux_live=_tl, window_panes=_wp, seat_turn=_stn)
        ok("facts() reads the seat behind each mark: t5's mark is a minute old and its window holds a session for "
           "the repo, exactly as t1's — and that seat last took a turn 7 h ago, so the mark holds nothing and the "
           "row is asked about in ONE line naming the hours, while t1's seat turned a minute ago and holds",
           got["t5"]["agent_live"] is False and got["t1"]["agent_live"] is True
           and decide(got["t5"]) == [("ask", "blocked", "marked by a live session, but that seat has not taken a "
                                                         "turn for 7 h — a re-mark is not a turn, mark expired")])
        ok("facts() reads the mark off the board file and calls the row alive, worktree or none — the whole "
           "path, so the field name is under test too and no fixture stands in for the missing worktree",
           got["t1"]["agent"] == "@5:900" and got["t1"]["agent_live"] is True
           and got["t1"]["wt_exists"] is False and decide(got["t1"]) == [])
        ok("A SESSION SPEAKS FOR ITS OWN REPO: a mark naming a window that belongs to another repo holds nothing "
           "open — the board is one file every session can write, and this is the reach it must not give",
           got["t2"]["agent_live"] is False and decide(got["t2"])[0][:2] == ("ask", "blocked"))
        ok("…and an unmarked row is untouched by any of it",
           got["t3"]["agent"] == "" and got["t3"]["agent_live"] is False
           and decide(got["t3"])[0][:2] == ("ask", "blocked"))
        ok("A MARK GOES COLD, and facts() carries the age off the board file to say so — t4's session is the "
           "same live one holding t1 open, and the only difference between the two rows is the clock. ONE "
           "record, not two: the row still has no worktree, and a cold mark must not turn that into a second "
           "finding the row never drew before it was marked",
           got["t4"]["agent_live"] is False and got["t4"]["wt_exists"] is False
           and len(decide(got["t4"])) == 1
           and decide(got["t4"])[0][:2] == ("ask", "blocked")
           and decide(got["t4"])[0][2].endswith("h ago, mark expired"))

    ok("a live pane idle 3 h is `idle`, not running: nothing is happening at it",
       eff(status="running", live=True, pane_idle=3 * 3600) == "idle")
    ok("…and the snapshot says how long, so the tab can print it instead of a stale iteration count",
       snapshot([("r", "t", F(status="running", live=True, pane_idle=3 * 3600), "idle", "", "")])
       ["tracks"]["r/t"]["idle_for"] == 3 * 3600)
    ok("a pane touched 10 min ago is simply running",
       eff(status="running", live=True, pane_idle=600) == "running")
    ok("a worker or a loop alive is work in flight whatever the keyboard shows",
       not idle_session(F(live=True, workers=[1], pane_idle=10 ** 5))
       and not idle_session(F(live=True, loops=[1], pane_idle=10 ** 5)))
    ok("no activity stamp is not evidence of idleness",
       not idle_session(F(live=True)) and eff(status="running", live=True) == "running")
    ok("`idle` never touches what counts as WAITING: a declared question still outranks the keyboard",
       eff(status="running", live=True, pane_idle=10 ** 5, journal=("BLOCKED", "q")) == "waiting")
    ok("…nor what the tool STOPS: an orphan idle at its prompt is still an orphan",
       eff(status="running", live=True, pane_idle=10 ** 5, workers=[1], stop_why="orphan") == "blocked")

    ok("finished with an open PR and nobody landing it is pending",
       pending(F(status="review", pr="u", pr_state="OPEN"), eff(status="review", pr="u", pr_state="OPEN"))
       and decide(F(status="review", pr="u", pr_state="OPEN")) == [])
    ok("an unreadable PR state never nags — `?` is not evidence that work is sitting",
       not pending(F(status="review", pr="u", pr_state="?"), eff(status="review", pr="u", pr_state="?")))
    ok("…nor is a run that never asked: --no-net leaves no PR fact, so nothing nags",
       not pending(F(status="review", pr="u", pr_state=None), eff(status="review", pr="u", pr_state=None)))
    ok("a landed track is not pending", not pending(F(status="merged", pr="u", pr_state="MERGED"), "merged"))
    ok("a track still being worked is not pending",
       not pending(F(status="running", live=True, pr="u", pr_state="OPEN"),
                   eff(status="running", live=True, pr="u", pr_state="OPEN")))
    ok("it is the EFFECTIVE state that counts, not the board's word: a stale `running` over an open PR with "
       "nobody in the worktree is a finished track, and pending",
       eff(status="running", pr="u", pr_state="OPEN") == "review"
       and pending(F(status="running", pr="u", pr_state="OPEN"), eff(status="running", pr="u", pr_state="OPEN")))
    ok("a held row raises nothing a person has to answer: the row that would be reported abandoned says `held` "
       "instead, and the same row unheld is the `ask` it always was",
       [k for k, _, _ in decide(F(status="running", live=False, held="behind #309"))] == ["held"]
       and decide(F(status="running", live=False))[0][:2] == ("ask", "blocked"))
    ok("…and it takes a REASON to hold one: an empty word, or one that is only spaces, holds nothing",
       decide(F(status="running", live=False, held=""))[0][0] == "ask"
       and decide(F(status="running", live=False, held="   "))[0][0] == "ask")
    ok("…the hold carries its reason into what is printed, because a hold nobody can see is the board note this "
       "replaces", decide(F(status="running", live=False, held="behind #309"))[0][2] == "held: behind #309")
    ok("a held row is still RECONCILED — a silent fix keeps the board true about a merged PR, and `held` says so "
       "beside it; the ask is the only thing the hold takes away",
       [(k, s) for k, s, _ in decide(F(status="review", pr="u", pr_state="MERGED", held="behind #309"))]
       == [("fix", "merged"), ("held", None)]
       and eff(status="review", pr="u", pr_state="MERGED", held="behind #309") == "merged")
    ok("…and a RUNAWAY on a held row is still stopped: a hold is a person's word about what to do next, never a "
       "licence to burn tokens with nothing coming out",
       [k for k, _, _ in decide(F(status="running", live=True, held="behind #309", stop_why="orphan"))]
       == ["stop", "held"])
    ok("…and a held row whose branch is not pushed still says so: the sweep deletes that branch at 48 h, and a "
       "hold that muted this would feed the only copy of those commits to `git branch -D`",
       any("not pushed" in w for _, _, w in
           decide(F(status="running", live=False, held="behind #309", push_err=True, unpushed=True)))
       and any("only in the worktree" in w for _, _, w in
               decide(F(status="running", live=False, held="behind #309", commit_err=True))))
    ok("…and a held row's QUESTION still reaches the owner: the person-ask is what puts the row on `waiting`, his "
       "NEEDS YOU list, and a hold is a word about the next move, not an answer to what was asked",
       [(k, s) for k, s, _ in decide(F(status="running", live=True, held="behind #309",
                                       journal=("BLOCKED", "which repo?")))]
       == [("ask", "waiting"), ("held", None)]
       and eff(status="running", live=True, held="behind #309", journal=("BLOCKED", "which repo?")) == "waiting")
    ok("…while a SESSION row is untouched by any of it: a channel is not a task, so it has nothing to hold",
       decide(F(kind="session", status="running", live=True, held="behind #309")) == [])
    ok("…except the one word a PERSON typed: a `waiting` row is never pending, however it is reconciled — landing "
       "is what it is waiting on (lessons#10 was nagged five times; owner, 2026-09-01)",
       not pending(F(status="waiting", pr="u", pr_state="OPEN"), "review")
       and not pending(F(status="waiting", pr="u", pr_state="OPEN"),
                       eff(status="waiting", pr="u", pr_state="OPEN")))

    def W(**kw):
        d = {"orphans": [], "workers": [111], "loops": [222], "limited": False, "idle": 4 * 3600}
        d.update(kw)
        return d

    ok("an orphaned worker — no cc-loop above it — is ended on sight, first sighting and all",
       "no cc-loop above it" in runaway(W(orphans=[111], loops=[]), False))
    ok("a worker under its loop, moving, is left alone", runaway(W(idle=60), True) == "")
    ok("wedged for hours but seen only once → not yet; one run is not two",
       runaway(W(), False) == "")
    ok("wedged for hours and the run before saw it too → ended", "wedged" in runaway(W(), True))
    ok("a loop waiting out a usage limit is waiting, not wedged", runaway(W(limited=True), True) == "")
    import tempfile
    _keep, _p = os.environ.get("CC_LIMIT_STAMP"), tempfile.mkstemp(suffix=".claude-limit")[1]
    os.environ["CC_LIMIT_STAMP"] = _p
    try:
        _t = int(now()) + 3600
        open(_p, "w").write(f"{_t}\tusage limit\t{int(now())}\tclaude-fable-5-1\tdeadbeef\n")
        ok("a stamp ONE run hit leaves the reconciler unlimited: that run's limit is not the box's",
           not limit_active() and limit_until() == 0.0)
        open(_p, "w").write(f"{_t}\tusage limit\t{int(now())}\t\tdeadbeef,cafef00d\n")
        ok("two runs on it make it the box's — with an empty model field, as the 09-04 stamp had",
           limit_active() and limit_until() == float(_t))
    finally:
        os.unlink(_p)
        os.environ.pop("CC_LIMIT_STAMP", None) if _keep is None else os.environ.update({"CC_LIMIT_STAMP": _keep})
    ok("a loop between iterations, with no worker under it, is not wedged", runaway(W(workers=[]), True) == "")
    ok("an expensive job that keeps moving is never a runaway — there is no spend cap anywhere here",
       runaway(W(idle=30), True) == "")
    ok("…and decide() ends it instead of calling it healthy",
       decide(F(status="running", live=True, stop_why="x"))[0][:2] == ("stop", "blocked"))
    ok("a track being ended is not also 'fixed' to running",
       len(decide(F(status="queued", live=True, stop_why="x"))) == 1)
    ok("a session row is never moved by presence, grace, a PR, a worktree, DONE or a runaway — alive, dead past "
       "grace, merged, wedged: decide() has nothing to say; the same facts on a track still decide it",
       all(decide(F(kind="session", **kw)) == [] for kw in (
           dict(status="running"), dict(status="blocked", live=True), dict(status="queued", live=True),
           dict(status="review", pr="u", pr_state="MERGED"), dict(status="running", live=True, stop_why="x"),
           dict(status="running", wt_exists=False, push_err=True), dict(status="running", journal=("DONE", ""))))
       and decide(F(kind="track", status="blocked", live=True))[0][:2] == ("fix", "running")
       and decide(F(status="blocked", live=True))[0][:2] == ("fix", "running"))
    ok("…but a session with a question for the owner is WAITING like a track — the ask record, so it is set, offered "
       "and paged: five course sessions are what waits_for() was written for, and kind=session must not silence them",
       decide(F(kind="session", status="running", live=True, journal=("BLOCKED", "which syllabus?")))[0][:2] == ("ask", "waiting")
       and "which syllabus?" in decide(F(kind="session", status="running", live=True, journal=("BLOCKED", "which syllabus?")))[0][2]
       and decide(F(kind="session", status="running", live=False, journal=("BLOCKED", "which syllabus?")))[0][:2] == ("ask", "waiting")
       and decide(F(kind="session", status="merged", journal=("BLOCKED", "old"))) == [])
    ok("…and it clears the same way once the journal stops saying BLOCKED — never to the `blocked` a dead track "
       "gets. The word it lands on is one the box can SEE: `running` where a session is open, `queued` where the "
       "window is gone, because `running` is a claim that something is happening and nothing is (#174 stopped the "
       "DISPLAY printing it; this is the board field, which was flipped back on every tick of a dead session)",
       decide(F(kind="session", status="waiting", live=True))[0][:2] == ("fix", "running")
       and decide(F(kind="session", status="waiting", live=False))[0][:2] == ("fix", "queued")
       and decide(F(status="waiting", live=False))[0][:2] == ("ask", "blocked"))
    ok("the ONE WORD for a session is its kind, `session` — cc ls and cc digest print that, never the `running` its "
       "row carries — with `waiting` the one track word it wears; a track's word is unchanged",
       effective(F(kind="session", status="running"), []) == "session"
       and effective(F(kind="session", status="waiting"), [("fix", "running", "")]) == "session"
       and effective(F(kind="session", status="running"), [("ask", "waiting", "")]) == "waiting"
       and effective(F(kind="session", status="waiting"), [("fix", "queued", "")]) == "session"   # …and the dead one reads the same
       and effective(F(status="running"), []) == "running" and effective(F(status="waiting"), [("fix", "running", "")]) == "running")

    with tempfile.TemporaryDirectory() as tg:
        def g(d, *a):
            return subprocess.run(["git", "-C", d, *a], capture_output=True, text=True, timeout=30)
        _d, _w = DEV, WTS
        globals().update(DEV=f"{tg}/dev", WTS=f"{tg}/wts")
        try:
            bare, co, wt2 = f"{tg}/origin.git", f"{tg}/dev/r", f"{tg}/wts/r/t"
            g(tg, "init", "-q", "--bare", bare)
            g(tg, "clone", "-q", bare, co)
            g(co, "config", "user.email", "s@e"); g(co, "config", "user.name", "s")
            open(f"{co}/a", "w").write("0"); g(co, "add", "a"); g(co, "commit", "-qm", "zero")
            g(co, "worktree", "add", "-q", "-b", "track/t", wt2)
            open(f"{wt2}/a", "w").write("1")
            g(wt2, "commit", "-qam", "one")
            ok("real git: a branch origin has never seen cannot be judged — None, so the marker's answer stands",
               branch_unpushed("r", wt2) is None)
            g(wt2, "push", "-q", "-u", "origin", "HEAD")
            ok("real git: a branch origin HAS is not unpushed, whatever a leftover push.err says",
               branch_unpushed("r", wt2) is False)
            open(f"{wt2}/a", "w").write("2")
            g(wt2, "commit", "-qam", "two")
            ok("real git: a commit origin does not have IS unpushed", branch_unpushed("r", wt2) is True)
            ok("real git: a directory that is not a checkout cannot be judged", branch_unpushed("r", tg + "/wts/r/nope") is None)
            ok("real git: nor can the repo's own checkout, which is no worktree under WTS/<repo>/",
               branch_unpushed("r", co) is None and wt_branch("r", wt2) == "track/t" and wt_branch("r", co) == "")
        finally:
            globals().update(DEV=_d, WTS=_w)

    with tempfile.TemporaryDirectory() as th:
        env = dict(os.environ, HOME=th, CC_NOTIFY_LOG_ONLY="1", CC_NOTIFY_LOG=f"{th}/notify.log",
                   CC_OFFER_AFTER="0")        # the cases below offer on the first pass; the grace has its own case
        repo = f"selfcheckrepo{os.getpid()}"
        os.makedirs(f"{th}/.cc/worktrees/{repo}/t1", exist_ok=True)
        os.makedirs(f"{th}/.cc/worktrees/{repo}/t3", exist_ok=True)
        os.makedirs(f"{th}/.cc/state/{repo}/t1", exist_ok=True)
        open(f"{th}/.cc/state/{repo}/t1/progress.md", "w").write("- did a thing\nSTATUS: BLOCKED: which schema?\n")

        def cb(*a):
            return subprocess.run([f"{BIN}/cc-board", *a], env=env, capture_output=True, text=True, timeout=30)

        cb("init", repo, f"{th}/dev/{repo}", "main")
        cb("add", repo, "t1", "a track that stood down", "")
        cb("status", repo, "t1", "running")
        r = subprocess.run([sys.executable, os.path.realpath(__file__), repo, "--apply", "--notify",
                            "--no-net", "--grace", "0"], env=env, capture_output=True, text=True, timeout=120)
        ok("end to end: exits 1 when something needs a person", r.returncode == 1)
        ok("end to end: the track that stood down says `waiting` on the board now — not `running`, and not the "
           "`blocked` that reads the same as a loop that gave up",
           cb("get", repo, "t1", "status").stdout.strip() == "waiting")
        ok("end to end: the board carries a note saying it was reconciled",
           any("reconciled: running → waiting" in n["msg"]
               for n in json.loads(cb("json", repo).stdout)["tracks"]["t1"]["notes"]))
        ok("end to end: the question from the journal reached the report", "which schema?" in r.stdout)
        ok("end to end: the orphaned worktree is reported", f"{repo}/t3" in r.stdout)
        ok("end to end: the owner was told once", sum("board" in ln for ln in
                                                      open(f"{th}/notify.log").read().splitlines()) == 1)
        r2 = subprocess.run([sys.executable, os.path.realpath(__file__), repo, "--apply", "--notify",
                             "--no-net", "--grace", "0"], env=env, capture_output=True, text=True, timeout=120)
        ok("end to end: a second run does not page the owner again",
           sum("board" in ln for ln in open(f"{th}/notify.log").read().splitlines()) == 1)
        ok("end to end: and it is idempotent — the track stays waiting",
           cb("get", repo, "t1", "status").stdout.strip() == "waiting" and r2.returncode == 1)
        argvN = [sys.executable, os.path.realpath(__file__), repo, "--apply", "--notify",
                 "--no-net", "--grace", "0", "--repeat", "0"]
        base = sum("board" in ln for ln in open(f"{th}/notify.log").read().splitlines())
        subprocess.run(argvN, env=dict(env, CC_RECONCILE_INJECT="/bin/true"),
                       capture_output=True, text=True, timeout=120)
        ok("end to end: a finding the live session accepts pages nobody",
           sum("board" in ln for ln in open(f"{th}/notify.log").read().splitlines()) == base)
        subprocess.run(argvN, env=dict(env, CC_RECONCILE_INJECT="/bin/false"),
                       capture_output=True, text=True, timeout=120)
        ok("end to end: …and one nobody took still pages the owner",
           sum("board" in ln for ln in open(f"{th}/notify.log").read().splitlines()) == base + 1)
        def tree(root):   # every file under it with its size and mtime: what a pure read must leave exactly as it found
            out = {}
            for d, _, fs in os.walk(root):
                for x in fs:
                    try:
                        st_ = os.stat(f"{d}/{x}"); out[f"{d}/{x}"] = (st_.st_size, st_.st_mtime_ns)
                    except OSError:
                        pass
            return out
        before = tree(f"{th}/.cc")
        r3 = subprocess.run([sys.executable, os.path.realpath(__file__), "snapshot"],
                            env=env, capture_output=True, text=True, timeout=120)
        snp = json.loads(r3.stdout)
        ok("end to end: `snapshot` prints every track's real state, who it waits on and why",
           snp["tracks"][f"{repo}/t1"]["state"] == "waiting"
           and snp["tracks"][f"{repo}/t1"]["waiting_on"] == "person"
           and "which schema?" in snp["tracks"][f"{repo}/t1"]["why"])
        ok("end to end: …and WRITES NOTHING — no reconcile.json, no wedged ledger, no sweep's leftovers: the Home tab "
           "and the wake take one per pass, and a pass must never move the timer's state",
           r3.returncode == 0 and not os.path.exists(f"{th}/.cc/state/reconcile.json") and tree(f"{th}/.cc") == before)
        rA = subprocess.run([sys.executable, os.path.realpath(__file__), "snapshot", "--apply"],
                            env=env, capture_output=True, text=True, timeout=120)
        ok("end to end: …and refuses --apply and --notify outright, rather than quietly doing either",
           rA.returncode == 2 and "writes nothing" in rA.stderr and tree(f"{th}/.cc") == before)
        subprocess.run([sys.executable, os.path.realpath(__file__), "--no-net", "--grace", "0"],
                       env=env, capture_output=True, text=True, timeout=120)   # the timer's shape: unfiltered, so it writes
        ok("end to end: the unfiltered run is what leaves it on disk for `digest` and `cc ls` to read",
           json.load(open(f"{th}/.cc/state/reconcile.json"))["tracks"][f"{repo}/t1"]["state"] == "waiting")
        view_ = lambda: subprocess.run([sys.executable, os.path.realpath(__file__), "view"], env=env,
                                       capture_output=True, text=True, timeout=60)
        rv = view_(); row = [ln.split("\t") for ln in rv.stdout.splitlines() if ln.startswith(f"{repo}/t1\t")]
        ok("end to end: `view` hands the readers that row as TSV — key, state, who, why — from the file, not a rerun",
           rv.returncode == 0 and len(row) == 1 and row[0][1:3] == ["waiting", "person"] and "which schema?" in row[0][3])
        sp = f"{th}/.cc/state/reconcile.json"; fresh = open(sp).read()
        open(sp, "w").write(json.dumps(dict(json.loads(fresh), epoch=int(now()) - FRESH - 1))); rv2 = view_()
        open(sp, "w").write(fresh)
        ok("end to end: …and a stale one is no rows at all, exit 0 — the reader keeps the board's word",
           rv2.returncode == 0 and rv2.stdout == "")
        os.makedirs(f"{th}/.cc/worktrees/{repo}/sess9", exist_ok=True)
        os.makedirs(f"{th}/.cc/state/{repo}/sess9", exist_ok=True)
        open(f"{th}/.cc/state/{repo}/sess9/progress.md", "w").write("- recon done\nSTATUS: BLOCKED: which syllabus?\n")
        cb("add", repo, "sess9", "a course session", "")
        cb("set", repo, "sess9", "kind", "session")
        cb("status", repo, "sess9", "running")
        rS = subprocess.run(argvN, env=dict(env, CC_RECONCILE_INJECT="/bin/false"), capture_output=True, text=True, timeout=120)
        snap_ = lambda: json.loads(subprocess.run([sys.executable, os.path.realpath(__file__), "snapshot"], env=env,
                                                  capture_output=True, text=True, timeout=120).stdout)["tracks"]
        snpS = snap_().get(f"{repo}/sess9") or {}   # `snapshot` is pure: it is the box as it stands, not the file
        ok("end to end: a session's question reaches the owner like a track's — `waiting` on the board, in the run's "
           "output, in the snapshot with who and why, and paged when no session took it",
           cb("get", repo, "sess9", "status").stdout.strip() == "waiting" and "sess9" in rS.stdout
           and snpS.get("state") == "waiting" and snpS.get("waiting_on") == "person" and "which syllabus?" in snpS.get("why", "")
           and "sess9" in open(f"{th}/notify.log").read())
        open(f"{th}/.cc/state/{repo}/sess9/progress.md", "w").write("- owner answered; building\n")
        subprocess.run([sys.executable, os.path.realpath(__file__), repo, "--apply", "--notify",
                        "--no-net", "--grace", "0"], env=env, capture_output=True, text=True, timeout=120)
        snpS = snap_()[f"{repo}/sess9"]
        ok("end to end: …and answered, it leaves `waiting` — never to the `blocked` a dead track gets, and with no "
           "session open on it, never to `running` either: the board field says `queued` and the snapshot word is "
           "`session`, so cc ls and cc digest print neither",
           cb("get", repo, "sess9", "status").stdout.strip() == "queued"
           and snpS["state"] == "session" and snpS["waiting_on"] == "")
        open(f"{th}/.cc/state/{repo}/t1/progress.md", "w").write("- owner answered; picked back up\n")
        r4 = subprocess.run([sys.executable, os.path.realpath(__file__), repo, "--apply", "--notify",
                             "--no-net", "--grace", "0"], env=env, capture_output=True, text=True, timeout=120)
        ok("end to end: an answered question does not leave `waiting` stuck on the board",
           cb("get", repo, "t1", "status").stdout.strip() == "blocked")
        os.makedirs(f"{th}/.cc/worktrees/{repo}/t2", exist_ok=True)
        open(f"{th}/gh", "w").write("#!/bin/sh\necho OPEN\n")
        open(f"{th}/inj", "w").write(f'#!/bin/sh\necho "$@" >> {th}/inj.log\n')
        os.chmod(f"{th}/gh", 0o755)
        os.chmod(f"{th}/inj", 0o755)
        open(f"{th}/inj.log", "w").close()
        cb("add", repo, "t2", "finished, PR open, nobody landed it", "")
        cb("status", repo, "t2", "review")
        cb("set", repo, "t2", "pr", "https://example.invalid/pr/9")
        argvP = [sys.executable, os.path.realpath(__file__), repo, "--apply", "--notify", "--grace", "0"]
        penv = dict(env, PATH=f"{th}:{os.environ['PATH']}", CC_RECONCILE_INJECT=f"{th}/inj")
        seenp = f"{th}/.cc/state/reconcile.seen.json"

        def offered():
            return sum("not landed" in ln for ln in open(f"{th}/inj.log").read().splitlines())

        def alerted():
            return sum(ln.startswith("alerts") for ln in open(f"{th}/notify.log").read().splitlines())

        a0 = alerted()
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: a finished track with an open PR is handed to the repo's own session", offered() == 1)
        ok("end to end: …and NOT to the owner yet — it has only just finished", alerted() == a0)
        ok("end to end: the pending key survives the ledger write, which used to keep `ask` findings only",
           float(json.load(open(seenp))[f"pending {repo}/t2"]) > 0)
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: the offer is made ONCE per PR — the next run, nothing changed, says nothing to the session",
           offered() == 1)
        led = json.load(open(seenp))                     # …and now it has stood there for five hours
        led[f"pending {repo}/t2"] = now() - 5 * 3600
        json.dump(led, open(seenp, "w"))
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: past the window nobody picked it up, so #alerts gets one line", alerted() == a0 + 1)
        nag = [ln for ln in open(f"{th}/notify.log").read().splitlines() if ln.startswith("alerts")][-1]
        ok("end to end: …a plain sentence with the span said aloud and the PR link, and no slug for a name",
           "has been waiting to land for 5 hours, and nobody has picked it up. https://example.invalid/pr/9" in nag
           and f"{repo}/t2" not in nag)
        ok("end to end: …and it names the project, because #alerts carries every project's lines",
           nag.startswith(f"alerts\t⏳ {repo}: "))
        ok("a span is said as you would say it: an hour, hours, then days",
           [spoken_hours(x) for x in (600, 3600, 12 * 3600, 3 * 86400)] == ["an hour", "an hour", "12 hours", "3 days"])
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: …one per window, however many times the timer fires in it — and still one offer",
           alerted() == a0 + 1 and offered() == 1)
        led = json.load(open(seenp))                      # …and now a SECOND window has passed since that one line
        led[f"alerted {repo}/t2"] = now() - 5 * 3600
        json.dump(led, open(seenp, "w"))
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: AT MOST ONE notice per PR, EVER — a second window past the first alert raises nothing more",
           alerted() == a0 + 1)
        ok("...but the age itself keeps counting in the file, for `view`/the dashboard to read",
           float(json.load(open(seenp))[f"pending {repo}/t2"]) > 0)
        os.remove(f"{th}/gh")                            # no gh = no PR answer at all, which is not evidence
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: with the PR state unreadable it goes quiet rather than guessing at unlanded work",
           offered() == 1)
        ok("end to end: …and keeps the keys: one failed poll restarts neither the owner's clock nor the offer",
           all(x in json.load(open(seenp)) for x in (f"pending {repo}/t2", f"alerted {repo}/t2",
                                                       f"offered {repo}/t2 https://example.invalid/pr/9")))
        open(f"{th}/gh", "w").write("#!/bin/sh\necho OPEN\n")
        os.chmod(f"{th}/gh", 0o755)
        json.dump({}, open(seenp, "w"))
        cb("status", repo, "t2", "waiting")
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: a row the board says is `waiting` is not nagged about its PR", offered() == 1)
        ok("end to end: …and --apply leaves that word alone, so the skip holds on every tick, not just the first",
           cb("get", repo, "t2", "status").stdout.strip() == "waiting")
        cb("status", repo, "t2", "review")
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: …the same row back in `review` is offered once — the ledger was not what silenced it",
           offered() == 2)
        os.makedirs(f"{th}/.cc/state/land", exist_ok=True)
        json.dump({"repo": repo, "pr": 9}, open(f"{th}/.cc/state/land/{repo}-9.json", "w"))
        json.dump({}, open(seenp, "w"))                  # a clean ledger: only the job file can silence this run
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: a PR with a job in the landing queue is being landed — no nag", offered() == 2)
        json.dump({"repo": repo, "pr": 9, "state": "handback", "stage": "handed"},
                  open(f"{th}/.cc/state/land/{repo}-9.json", "w"))
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: …but a job the lander handed back (state handback) is nobody's landing: offered once", offered() == 3)
        os.remove(f"{th}/.cc/state/land/{repo}-9.json")
        json.dump({}, open(seenp, "w"))
        os.makedirs(f"{th}/lnd/core/lander", exist_ok=True)
        open(f"{th}/lnd/core/lander/cli.py", "w").write("import time\ntime.sleep(60)\n")
        lander = subprocess.Popen([sys.executable, "-P", f"{th}/lnd/core/lander/cli.py", "queue", repo, "9"],
                                  start_new_session=True)
        o_ = offered()
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        lander.kill()
        lander.wait(timeout=10)
        ok("end to end: a PR named by a live lander argv (python3 -P …/core/lander/cli.py queue) — no nag",
           offered() == o_)
        json.dump({}, open(seenp, "w"))
        open(f"{th}/cc-land", "w").write("#!/bin/sh\nsleep 60\n")   # a live argv naming the PR, not a real landing
        os.chmod(f"{th}/cc-land", 0o755)
        lander = subprocess.Popen([f"{th}/cc-land", repo, "9"], start_new_session=True)
        o_ = offered()
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        lander.kill()
        lander.wait(timeout=10)
        ok("end to end: a PR named by a live cc-land argv is being landed — no nag", offered() == o_)
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: …and one that falls out of a lane unlanded is news again, once", offered() == o_ + 1)
        os.makedirs(f"{th}/.cc/state/land/root", exist_ok=True)
        rootp = f"{th}/.cc/state/land/root/{repo}-9.json"
        json.dump({"repo": repo, "pr": 9, "reviews": 2, "repairs": 1}, open(rootp, "w"))
        json.dump({}, open(seenp, "w"))                  # a clean ledger: only the record can silence this run
        o_ = offered()
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: a PR between two landing rounds — no job file, but a work record a landing wrote minutes "
           "ago — is mid-flight, not abandoned: no nag", offered() == o_)
        cold = now() - BETWEEN_ROUNDS - 60
        os.utime(rootp, (cold, cold))
        json.dump({}, open(seenp, "w"))
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: …and a record older than that is history, not a landing: the same row is nagged once",
           offered() == o_ + 1)
        # THE OFFER WAITS OUT OFFER_AFTER (raised-watchdog-offers-a-pr-the-lander-is-gating): a seat clears its mark
        # and queues the PR minutes later, and an offer in between reached it while cc-land was gating #553.
        genv, jobp = dict(penv, CC_OFFER_AFTER="600"), f"{th}/.cc/state/land/{repo}-9.json"
        json.dump({}, open(seenp, "w"))              # (the root record above is cold, so it silences nothing)
        o_ = offered()
        subprocess.run(argvP, env=genv, capture_output=True, text=True, timeout=120)
        ok("end to end: a PR that has just gone pending is not offered on the first pass — its clock starts",
           offered() == o_ and float(json.load(open(seenp)).get(f"pending {repo}/t2") or 0) > 0)
        json.dump({"repo": repo, "pr": 9}, open(jobp, "w"))              # …the seat queues it inside the grace
        led = json.load(open(seenp)); led[f"pending {repo}/t2"] = now() - 900; json.dump(led, open(seenp, "w"))
        subprocess.run(argvP, env=genv, capture_output=True, text=True, timeout=120)
        ok("end to end: …queued inside the grace, it is never offered once the grace is over", offered() == o_)
        os.remove(jobp)
        led = json.load(open(seenp)); led[f"pending {repo}/t2"] = now() - 900; json.dump(led, open(seenp, "w"))
        subprocess.run(argvP, env=genv, capture_output=True, text=True, timeout=120)
        ok("end to end: …and the control: past the grace with nobody landing it, it is offered once",
           offered() == o_ + 1)
        os.remove(rootp)

        # A NAG THE AUTHORITATIVE STATE DISPROVES IS A FAILURE, WRITTEN WHERE IT HAPPENED (false_nags; the design's
        # "cc-reconcile (a nag the authoritative state disproved)"). The row was just nagged (the line above), at a
        # time the seen-ledger holds. Now cc-land's work record turns up saying it had the PR ten minutes BEFORE that
        # nag, and the PR reads MERGED: the memo is dropped, and the drop is held against the record → ONE line in the
        # failure ledger, notification/false-action-needed, at the NAG's time, naming the PR. A fixture ledger of its
        # own (CC_FAILURES), so nothing here can touch the box's.
        fdir = f"{th}/.cc/failures"
        fenv = dict(penv, CC_FAILURES=fdir)

        def failures(kind=FALSE_NAG):
            try:
                return [json.loads(ln) for ln in open(f"{fdir}/{repo}.jsonl") if kind in ln]
            except OSError:
                return []

        nag_at = float(json.load(open(seenp))[f"offered {repo}/t2 https://example.invalid/pr/9"])
        json.dump({"repo": repo, "pr": 9, "first": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(nag_at - 600))}, open(rootp, "w"))
        open(f"{th}/gh", "w").write("#!/bin/sh\necho MERGED\n")
        rF = subprocess.run(argvP, env=fenv, capture_output=True, text=True, timeout=120)
        fl = failures()
        ok("a nag the landing's own record disproves — cc-land had the PR before the watchdog said 'land it' — is "
           "written to the failure ledger once the memo drops: one notification/false-action-needed line, at the nag's "
           "time, naming the PR",
           len(fl) == 1 and fl[0]["links"].get("pr") == "9" and fl[0]["writer"] == "cc-reconcile"
           and abs(epoch(fl[0]["ts"]) - nag_at) < 2 and "since" in fl[0]["observed"]
           and f"offered {repo}/t2 https://example.invalid/pr/9" not in json.load(open(seenp)))
        ok("…and the pass itself decided what it always decides: the row reconciled to merged, the exit its own "
           "(1: the fixture's other rows still need a person), no traceback",
           rF.returncode == 1 and "Traceback" not in rF.stderr and cb("get", repo, "t2", "status").stdout.strip() == "merged")
        # THE OTHER SIDE: a nag that simply CLEARED — the PR merged after it, no record, no landing window — is a
        # nag that worked or a person's doing, and nothing is written. Back to review, nagged again, then merged
        # with nothing predating the nag.
        os.remove(rootp)
        open(f"{th}/gh", "w").write("#!/bin/sh\necho OPEN\n")
        cb("status", repo, "t2", "review")
        json.dump({}, open(seenp, "w"))
        subprocess.run(argvP, env=fenv, capture_output=True, text=True, timeout=120)
        n0 = len(failures())
        nagged = f"offered {repo}/t2 https://example.invalid/pr/9" in json.load(open(seenp))
        open(f"{th}/gh", "w").write("#!/bin/sh\necho MERGED\n")
        subprocess.run(argvP, env=fenv, capture_output=True, text=True, timeout=120)
        ok("a nag that cleared with nothing predating it — the PR merged after the session was told — records "
           "nothing: the memo dropped and the ledger holds what it held",
           nagged and f"offered {repo}/t2 https://example.invalid/pr/9" not in json.load(open(seenp)) and len(failures()) == n0)
        # …AND A LEDGER THAT CANNOT BE WRITTEN CHANGES NOTHING ABOUT THE PASS. The disproving record again, with
        # CC_FAILURES pointing at a FILE: cc-failures cannot make its directory and dies; the pass still drops the
        # memo, still reconciles the row, still exits 0, and says why in reconcile.log.
        open(f"{th}/gh", "w").write("#!/bin/sh\necho OPEN\n")
        cb("status", repo, "t2", "review")
        json.dump({}, open(seenp, "w"))
        subprocess.run(argvP, env=fenv, capture_output=True, text=True, timeout=120)
        nag_at = float(json.load(open(seenp))[f"offered {repo}/t2 https://example.invalid/pr/9"])
        json.dump({"repo": repo, "pr": 9, "first": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(nag_at - 600))}, open(rootp, "w"))
        open(f"{th}/gh", "w").write("#!/bin/sh\necho MERGED\n")
        open(f"{th}/notadir", "w").close()
        n0 = len(failures())
        rB = subprocess.run(argvP, env=dict(fenv, CC_FAILURES=f"{th}/notadir"), capture_output=True, text=True, timeout=120)
        rlog = open(f"{th}/.cc/state/reconcile.log").read() if os.path.exists(f"{th}/.cc/state/reconcile.log") else ""
        ok("a ledger write that fails leaves the pass exactly as it was — the same exit, the memo dropped, the row "
           "merged — and reconcile.log says the writer failed",
           rB.returncode == rF.returncode and "Traceback" not in rB.stderr and cb("get", repo, "t2", "status").stdout.strip() == "merged"
           and f"offered {repo}/t2 https://example.invalid/pr/9" not in json.load(open(seenp))
           and "writer failed" in rlog and len(failures()) == n0)
        os.remove(rootp)
        # THE ORPHAN NAG: a worktree the board never heard of, reported while GitHub could not be asked (no
        # evidence, so it is reported as it always was); the next pass finds the directory gone and GitHub answering
        # that a PR from that branch had been OPEN since an hour before the nag → one line, the PR named. A gh that
        # fails `pr list` at nag time and answers it at drop time, the way a blip does.
        os.makedirs(f"{th}/dev/{repo}", exist_ok=True)   # branch_prs asks from the repo's own checkout, which a real box has
        owt = f"{th}/.cc/worktrees/{repo}/orph-x"
        os.makedirs(owt, exist_ok=True)
        old_ = now() - 7200
        os.utime(owt, (old_, old_))
        open(f"{th}/gh", "w").write("#!/bin/sh\ncase \"$*\" in *\"pr list\"*) exit 1;; esac\necho OPEN\n")
        json.dump({}, open(seenp, "w"))
        subprocess.run(argvP, env=fenv, capture_output=True, text=True, timeout=120)
        okey = f"{repo}/orph-x: {ORPHAN_WHY}"
        onag = float(json.load(open(seenp)).get(okey) or 0)
        created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime((onag or now()) - 3600))
        open(f"{th}/gh", "w").write("#!/bin/sh\ncase \"$*\" in *\"pr list\"*) echo '[{\"number\":11,\"state\":\"OPEN\",\"mergedAt\":null,\"createdAt\":\"" + created + "\"}]';; *) echo OPEN;; esac\n")
        shutil.rmtree(owt)
        subprocess.run(argvP, env=fenv, capture_output=True, text=True, timeout=120)
        fo = [r for r in failures() if r["links"].get("pr") == "11"]
        ok("an orphan-worktree nag whose branch already had an OPEN PR when it went out is written once when the "
           "memo drops, at the nag's time, naming that PR",
           onag > 0 and len(fo) == 1 and abs(epoch(fo[0]["ts"]) - onag) < 2 and "already open" in fo[0]["observed"]
           and okey not in json.load(open(seenp)))
        # the fixture as the cases below expect it: t2 in review with an OPEN PR, a clean memo ledger
        open(f"{th}/gh", "w").write("#!/bin/sh\necho OPEN\n")
        cb("status", repo, "t2", "review")
        json.dump({}, open(seenp, "w"))

        # A PARKED PROJECT IS NOT NAGGED — not its session, not the owner. The REAL cc-pause is asked here, reading
        # the real flag file in this scratch HOME, so the whole path is pinned rather than a stand-in for it. Its own
        # fixture: a clean ledger, so nothing but the pause can be the reason the offer does not happen.
        PAUSED_FLAG = '{"at":"2026-01-01T00:00:00Z","by":"owner","note":"","loops":[]}\n'
        json.dump({}, open(seenp, "w"))
        os.makedirs(f"{th}/.cc/state/{repo}", exist_ok=True)
        open(f"{th}/.cc/state/{repo}/paused", "w").write(PAUSED_FLAG)
        o0, a1 = offered(), alerted()
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: a parked project's row is neither offered to its session nor paged about — the owner "
           "parked it himself, so a nag about it is spend he asked the box to stop",
           offered() == o0 and alerted() == a1)
        ok("end to end: …and no nag memo is written for it either, so the finding is news again at the resume "
           "with its `unlanded for Nh` clock counting from then instead of through the park",
           json.load(open(seenp)) == {})
        ok("end to end: …while the reconciling itself still runs for it: the row is in the snapshot exactly as "
           "before, because a pause stops what SPENDS, not what keeps the board true",
           (snap_().get(f"{repo}/t2") or {}).get("state"))
        os.remove(f"{th}/.cc/state/{repo}/paused")
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: …and that same row, resumed, is offered once — the pause was what silenced it and the "
           "finding was not lost", offered() == o0 + 1)
        json.dump({}, open(seenp, "w"))
        os.makedirs(f"{th}/.cc/state/{repo}-other", exist_ok=True)
        open(f"{th}/.cc/state/{repo}-other/paused", "w").write(PAUSED_FLAG)
        o1 = offered()
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: parking ANOTHER project does not silence this one — the gate asks about the repo each row "
           "belongs to, never whether something somewhere is parked", offered() == o1 + 1)
        shutil.rmtree(f"{th}/.cc/state/{repo}-other")
        json.dump({}, open(seenp, "w"))

        o2, a2 = offered(), alerted()
        cb("set", repo, "t2", "held", "behind #309 — landing this one first opens the hole")
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: a held row is never offered as 'review and land it', is not paged about, and no memo is "
           "kept — so the PR is news again, once, when a person lifts the hold",
           offered() == o2 and alerted() == a2
           and not any("t2" in k for k in json.load(open(seenp))))
        ok("end to end: …and --apply leaves the row itself exactly as it was — its word, its PR and its reason "
           "all stand, because a held row is one a person still has to be able to see and release",
           cb("get", repo, "t2", "status").stdout.strip() == "review"
           and cb("get", repo, "t2", "pr").stdout.strip() == "https://example.invalid/pr/9"
           and cb("get", repo, "t2", "held").stdout.strip().startswith("behind #309"))
        ok("end to end: …and `show` still lists it with that reason: this view is the only place a held row is "
           "offered to a person at all", "held (" in cb("show", repo).stdout
           and "behind #309" in cb("show", repo).stdout)
        cb("set", repo, "t2", "held", "")
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: …and that same row, hold lifted, is offered once — the hold was what silenced it and the "
           "finding was not lost", offered() == o2 + 1)
        json.dump({}, open(seenp, "w"))

        # THE PR IS READ AGAIN AT SEND TIME. facts() reads it when the run begins; the tick runs between; PR #521
        # merged 16 s before "review and land it" went out on the older read, and a seat woke on it (~110k cache
        # read) to find nothing to do (raised 2026-09-19). Own fixture: four fresh rows, a gh that answers per PR
        # and, for two of them, differently the second time it is asked — the run's first read and its send-time
        # read are the two calls.
        open(f"{th}/gh", "w").write(f'''#!/bin/sh
        case "$*" in
          *pr/77*"--json state"*) n=$(cat {th}/gh77.n 2>/dev/null || echo 0); echo $((n + 1)) > {th}/gh77.n
                                  [ "$n" -ge 1 ] && echo MERGED || echo OPEN ;;
          *pr/79*"--json state"*) n=$(cat {th}/gh79.n 2>/dev/null || echo 0); echo $((n + 1)) > {th}/gh79.n
                                  [ "$n" -ge 1 ] && echo MERGED || echo CLOSED ;;
          *pr/80*"--json state"*) echo CLOSED ;;
          *) echo OPEN ;;
        esac
        ''')
        for tr, n in (("t7", 77), ("t8", 78), ("t9", 79), ("t10", 80)):
            cb("add", repo, tr, f"pr {n}", "")
            cb("status", repo, tr, "review")
            cb("set", repo, tr, "pr", f"https://example.invalid/pr/{n}")
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        inj6 = open(f"{th}/inj.log").read()
        led6 = json.load(open(seenp))
        ok("end to end: a finished row whose PR read OPEN when the run began and MERGED at send time is not "
           "offered as 'review and land it', and keeps no memo and no clock — the next pass marks it merged",
           "t7" not in inj6 and not any("t7" in k for k in led6))
        ok("end to end: …while the row beside it whose PR still reads OPEN at send time is offered exactly as "
           "before — the re-read drops a merged PR, not the nag",
           sum(f"{repo}/t8: finished, PR open, not landed" in ln for ln in inj6.splitlines()) == 1
           and f"offered {repo}/t8 https://example.invalid/pr/78" in led6)
        ok("end to end: …and a NEEDS-YOU finding about a PR — 'closed without merging' — is re-read the same way: "
           "merged by send time it is not sent, and the row beside it whose PR is still closed is",
           "t9" not in inj6 and f"board watchdog: {repo}/t10 — its PR was closed without merging" in inj6)
        ok("end to end: …and the re-read was made — once per PR, only for a line about to go out: the two PRs "
           "that changed were each asked twice, and the two that did not, no more than the run's own read",
           open(f"{th}/gh77.n").read().strip() == "2" and open(f"{th}/gh79.n").read().strip() == "2")
        for tr in ("t7", "t8", "t9", "t10"):
            cb("rm", repo, tr)
        open(f"{th}/gh", "w").write("#!/bin/sh\necho OPEN\n")
        json.dump({}, open(seenp, "w"))

        # …AND IT DROPS ONLY WHAT THE MERGE ANSWERS. A `merged` row whose branch really holds commits origin lacks
        # is still reported (the invariant up top, and asserted at decide level above). Dropping every line on a
        # MERGED PR took that safety ask off the wire and wrote its key as 0, so every pass dropped it again while
        # the sweep counted down to deleting the branch with the commits on it. Own fixture: a real checkout one
        # commit ahead of its origin, with the failed-push marker beside it. A worktree of the repo's own checkout,
        # as cc makes them: git runs only in one of those (wt_pin).
        wtU, o11, dv = f"{th}/.cc/worktrees/{repo}/t11", f"{th}/o11.git", f"{th}/dev/{repo}"

        def gu(*a, d=None):
            return subprocess.run(["git", *(["-C", d] if d else []), "-c", "user.name=s", "-c", "user.email=s@e", *a],
                                  capture_output=True, text=True, timeout=30)

        gu("init", "-q", "--bare", o11)
        gu("init", "-q", "-b", "main", dv); gu("commit", "-q", "--allow-empty", "-m", "zero", d=dv)
        gu("remote", "add", "origin", o11, d=dv)
        gu("worktree", "add", "-q", "-b", "track/t11", wtU, d=dv)
        open(f"{wtU}/a", "w").write("1")
        gu("add", "a", d=wtU); gu("commit", "-qm", "one", d=wtU)
        gu("push", "-q", "-u", "origin", "HEAD", d=wtU)
        open(f"{wtU}/a", "w").write("2")
        gu("commit", "-qam", "two", d=wtU)               # the commit origin does not have
        os.makedirs(f"{wtU}/.cc", exist_ok=True)
        open(f"{wtU}/.cc/push.err", "w").close()
        open(f"{th}/gh", "w").write(f'''#!/bin/sh
        case "$*" in
          *pr/82*"--json state"*) n=$(cat {th}/gh82.n 2>/dev/null || echo 0); echo $((n + 1)) > {th}/gh82.n
                                  [ "$n" -ge 1 ] && echo MERGED || echo OPEN ;;
          *) echo MERGED ;;
        esac
        ''')
        cb("add", repo, "t11", "merged, and its branch never reached origin", "")
        cb("status", repo, "t11", "merged")
        cb("set", repo, "t11", "pr", "https://example.invalid/pr/81")
        cb("add", repo, "t12", "pr 82", "")
        cb("status", repo, "t12", "review")
        cb("set", repo, "t12", "pr", "https://example.invalid/pr/82")
        n7 = len(open(f"{th}/inj.log").read().splitlines())
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        inj7 = "\n".join(open(f"{th}/inj.log").read().splitlines()[n7:])
        led7 = json.load(open(seenp))
        ok("end to end: a MERGED PR at send time drops the lines the merge answers and NOT the safety ask beside "
           "them: a merged row holding commits origin lacks is still offered, and keeps its memo, because no "
           "merge makes that work safe and the sweep deletes the branch at 48 h",
           sum(f"{repo}/t11 — its branch is not pushed" in ln for ln in inj7.splitlines()) == 1
           and float(led7.get(f"{repo}/t11: its branch is not pushed") or 0) > 0)
        ok("end to end: …while in that same pass the row whose only finding IS the merge's answer is dropped "
           "exactly as t7 was — 'review and land it' on a PR that merged since the run began, no memo, no clock",
           "t12" not in inj7 and not any("t12" in k for k in led7))
        for tr in ("t11", "t12"):
            cb("rm", repo, tr)
        shutil.rmtree(wtU, ignore_errors=True); shutil.rmtree(o11, ignore_errors=True)
        gu("worktree", "prune", d=dv); gu("remote", "remove", "origin", d=dv)
        open(f"{th}/gh", "w").write("#!/bin/sh\necho OPEN\n")
        json.dump({}, open(seenp, "w"))

        # A ROW WAITING ON A PERSON IS NOT UNATTENDED. Its seat stood down and said so (STATUS: BLOCKED), and the
        # row is `pending` all the same — finished, PR open, nothing landing it, on a repo whose PRs this box does
        # land — so nothing else in this fixture can be the reason it goes quiet. The answer is the owner's, so
        # "review and land it" is a full context read that can change nothing: career/positioning PR #4 was offered
        # one every ~2 h while it sat in review waiting on him.
        st2 = f"{th}/.cc/state/{repo}/t2"
        os.makedirs(st2, exist_ok=True)
        open(f"{st2}/progress.md", "w").write("- asked the owner\nSTATUS: BLOCKED: land #9 now, or hold it?\n")

        def blocked_run():
            """One --apply --notify pass over the fixture as it stands, with its records for t2 back. The word is
            set back to `done` first: the pass reconciles it to `review`, and the state under test is this one."""
            cb("status", repo, "t2", "done")
            r = subprocess.run(argvP + ["--json"], env=penv, capture_output=True, text=True, timeout=120)
            return [x for x in json.loads(r.stdout or '{"records": []}')["records"] if x["track"] == "t2"]

        o5, a5 = offered(), alerted()
        rec5 = blocked_run()
        ok("end to end: the fixture is that state itself and not a stand-in for it — the pass read the PR as OPEN "
           "off a board word that is not `waiting` and put the row in `review`, which is `pending` exactly",
           [(x["from"], x["to"], x["kind"]) for x in rec5] == [("done", "review", "fix")])
        ok("end to end: …and its seat was told nothing: a row whose own journal says it is waiting on a person is "
           "never offered 'review and land it' — it has been picked up and the answer is not that seat's to give — "
           "is not paged about as work nobody took, and keeps no memo, so it is news again when the answer comes",
           offered() == o5 and alerted() == a5 and not any("t2" in k for k in json.load(open(seenp))))
        os.remove(f"{th}/gh")
        blocked_run()
        open(f"{th}/gh", "w").write("#!/bin/sh\necho OPEN\n")
        os.chmod(f"{th}/gh", 0o755)
        blocked_run()
        ok("end to end: …and a poll flap is not a way round it: the pass that could not read the PR keeps no memo, "
           "and the next one, reading OPEN again off that clean slate, still says nothing to the seat",
           offered() == o5)
        os.remove(f"{st2}/progress.md")      # the owner answered — the same row, the same repo, nothing else changed
        json.dump({}, open(seenp, "w"))
        cb("status", repo, "t2", "done")
        subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
        ok("end to end: …and that same row, no longer waiting on anyone, is offered once: the wait on a person was "
           "what silenced it, not anything else about this fixture", offered() == o5 + 1)
        json.dump({}, open(seenp, "w"))

        vj, HD = f"{th}/verdict.json", "09dd584c561e9e18d3025a8db244809f9d5b776a"
        open(f"{th}/gh", "w").write(f'#!/bin/sh\ncase "$*" in\n  *headRefOid*) cat {vj} ;;\n  *) echo OPEN ;;\nesac\n')
        os.chmod(f"{th}/gh", 0o755)
        mark = f"<!-- cc-land-review v2 change=369953f4b8fd base=a178c4925378 head={HD[:12]} verdict=%s by=w -->"

        def verdicts(*bodies):
            """Offers made in one run with exactly these comments on the PR, off a clean ledger."""
            json.dump({"headRefOid": HD, "comments": [{"body": b} for b in bodies]}, open(vj, "w"))
            json.dump({}, open(seenp, "w"))
            o_ = offered()
            subprocess.run(argvP, env=penv, capture_output=True, text=True, timeout=120)
            return offered() - o_

        ok("end to end: a PR with DO-NOT-LAND recorded against the head it is at NOW is never offered as 'review "
           "and land it' — the box read this change and said no, and the PR state is not the verdict",
           verdicts(mark % "DO-NOT-LAND" + "\n1. a.py:1 — the finding") == 0)
        ok("end to end: …and no memo is kept for it, so the PR is news again, once, when the head moves past the "
           "verdict", not any("t2" in k for k in json.load(open(seenp))))
        ok("end to end: LAND-AFTER-FIX stops a landing exactly as DO-NOT-LAND does, so 'review and land it' is "
           "the wrong move for it too — the remedy is the fix that verdict names",
           verdicts(mark % "LAND-AFTER-FIX") == 0)
        ok("end to end: the older head-keyed marker shape is read the same way — a verdict recorded before the "
           "change key existed is still a refusal",
           verdicts(f"<!-- cc-land-review {HD[:12]} DO-NOT-LAND -->") == 0)
        ok("end to end: a verdict about a head the PR has moved PAST is spent: the push answered it, the change "
           "is unread again and landing it is the right offer",
           verdicts("<!-- cc-land-review v2 change=1 base=2 head=ffffffffffff verdict=DO-NOT-LAND by=w -->") == 1)
        ok("end to end: a LAND standing on this head silences nothing — that is the watchdog's line being right",
           verdicts(mark % "LAND") == 1)
        ok("end to end: …and a finding that QUOTES a marker is text about the change, not the answer to it: the "
           "read is anchored at the start of the comment, as cc-land's own is",
           verdicts("1. cc-land:9 — a comment that starts " + mark % "DO-NOT-LAND") == 1)
        open(f"{th}/gh", "w").write("#!/bin/sh\necho OPEN\n")
        os.chmod(f"{th}/gh", 0o755)
        json.dump({}, open(seenp, "w"))

        victim = subprocess.Popen(["sleep", "60"], start_new_session=True)   # its own group, so nothing else is in range
        STARTS[victim.pid] = start_ticks(victim.pid)                           # as the scan would have recorded it
        ended = end_it([victim.pid])
        try:
            victim.wait(timeout=10)
            died = True
        except Exception:
            victim.kill()
            died = False
        ok("ending a runaway really ends it, group and all", ended and died)
        ok("a process that is already gone counts as ended, not as a failure", end_it([victim.pid]))
        # A process in a group it does not lead: the group is someone else's, so only the process is TERMed.
        lead = subprocess.Popen(["sh", "-c", "sleep 60 & echo $!; exec sleep 60"], start_new_session=True,
                                stdout=subprocess.PIPE, text=True)
        member = int(lead.stdout.readline())
        STARTS[member] = start_ticks(member)
        end_it([member])
        time.sleep(0.3)
        try:
            gone = open(f"/proc/{member}/stat").read().rsplit(")", 1)[1].split()[0] == "Z"
        except OSError:
            gone = True
        ok("a process that does not lead its group is ended alone; the group's leader is left running",
           gone and lead.poll() is None)
        lead.kill(); lead.wait()
        ok("pid 1 is never signalled, whatever the list says", keeper(1) and not end_it([1]))
        named = "import ctypes, sys, time; ctypes.CDLL(None).prctl(15, b'systemd', 0, 0, 0); print(1, flush=True); time.sleep(30)"
        fakes = [subprocess.Popen([sys.executable, "-c", named] + extra, stdout=subprocess.PIPE) for extra in ([], ["--user"])]
        for fp in fakes:
            fp.stdout.readline()
        sysd = f"{th}/systemd"   # a binary named systemd, so its exe is one: the shape of the real manager
        shutil.copy("/bin/sh", sysd)
        fakes.append(subprocess.Popen([sysd, "-c", "echo 1; read x", "systemd", "--user"], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE))
        fakes[2].stdout.readline()
        ok("a runaway that names itself systemd is no keeper, nor one that also has --user in its argv; a binary "
           "named systemd run with --user is", not keeper(fakes[0].pid) and not keeper(fakes[1].pid) and keeper(fakes[2].pid))
        for fp in fakes:
            fp.kill(); fp.wait()
        held = subprocess.Popen(["sleep", "60"], start_new_session=True)
        STARTS[held.pid] = (start_ticks(held.pid) or 0) + 1   # the scan saw some other process at this pid
        refused = not end_it([held.pid])
        time.sleep(0.2)
        ok("a pid whose start time is not the one the scan saw is refused and left running",
           refused and held.poll() is None)
        held.kill(); held.wait()
        STARTS.pop(held.pid, None)
        held = subprocess.Popen(["sleep", "60"], start_new_session=True)
        STARTS.pop(held.pid, None)   # the scan never saw it, or saw it change under its reads
        refused = not end_it([held.pid])
        time.sleep(0.2)
        ok("a pid the scan recorded no start time for is not signalled: it is skipped, not read afresh and compared "
           "with itself", refused and held.poll() is None)
        held.kill(); held.wait()
        loop = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "cc-loop", "_ccsc", "scan"])
        try:
            want = None
            for _ in range(50):   # until its argv is the exec'd one the scan reads
                if b"cc-loop" in open(f"/proc/{loop.pid}/cmdline", "rb").read():
                    want = start_ticks(loop.pid)
                    break
                time.sleep(0.05)
            seen = procs()[4].get("_ccsc/scan", [])
            ok("the scan records a cc-loop with the start time it had before its argv was read",
               seen == [loop.pid] and STARTS.get(loop.pid) == want is not None)
            STARTS.pop(loop.pid, None)
            real_ticks, reads = start_ticks, []

            def moved(pid):   # the second read, after argv and cwd, sees another process at this pid
                t = real_ticks(pid)
                if int(pid) == loop.pid:
                    reads.append(t)
                    return t + (len(reads) - 1)
                return t
            globals()["start_ticks"] = moved
            try:
                seen = procs()[4].get("_ccsc/scan", [])
            finally:
                globals()["start_ticks"] = real_ticks
            ok("a pid whose start time changes between the read before its argv and the read after is dropped from "
               "the scan, and no start time is kept for it", seen == [] and loop.pid not in STARTS and len(reads) == 2)
        finally:
            loop.kill(); loop.wait()
            STARTS.pop(loop.pid, None)
        waiter = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "/b/cc-room", "admit", "_ccsc/wait",
                                   "--log", "/s/loop.log", "--", "/b/cc-loop", "_ccsc", "wait", "--max-iter", "1"])
        try:
            for _ in range(50):
                if b"cc-loop" in open(f"/proc/{waiter.pid}/cmdline", "rb").read():
                    break
                time.sleep(0.05)
            got = procs()
            ok("a `cc-room admit R/T -- cc-loop R T` waiter is no loop and no live track, though the loop's name is on "
               "its command line: it flipped a `queued` row to running, 'a worker is in its worktree'",
               "_ccsc/wait" not in got[0] and "_ccsc/wait" not in got[4])
        finally:
            waiter.kill(); waiter.wait()
            STARTS.pop(waiter.pid, None)
        with tempfile.TemporaryDirectory() as rd:
            os.makedirs(f"{rd}/queue")
            gone = subprocess.Popen(["true"])            # exited but not reaped: a zombie whose pid nobody can reuse
            os.waitid(os.P_PID, gone.pid, os.WEXITED | os.WNOWAIT)
            me, mine = os.getpid(), start_ticks(os.getpid())
            for n, e in (("1-alive", {"what": "rq/alive", "pid": me, "start": str(mine)}),
                         ("2-lost", {"what": "rq/lost", "pid": gone.pid, "start": "1", "cmd": ["cc-loop"],
                                     "server": [gone.pid, "1"], "queued": now() - 60}),
                         ("3-killed", {"what": "rq/killed", "pid": gone.pid, "start": "1", "cmd": ["cc-loop"],
                                       "server": [me, str(mine)], "queued": now() - 60}),
                         ("4-old", {"what": "rq/old", "pid": gone.pid, "start": "1", "cmd": ["cc-loop"],
                                    "server": [gone.pid, "1"], "queued": now() - 8 * 86400})):
                json.dump(e, open(f"{rd}/queue/{n}", "w"))
            json.dump({"what": "rq/half", "pid": me, "start": str(mine)}, open(f"{rd}/queue/5-half.tmp", "w"))
            open(f"{rd}/queue/6-junk", "w").write("not json")
            for n, srv in (("0-srvdict", {"pid": 1, "start": "1"}), ("8-srvstr", "ab"), ("9-srvshort", [1])):
                json.dump({"what": f"rq/{n}", "server": srv, "cmd": ["cc-loop"], "queued": now() - 60},
                          open(f"{rd}/queue/{n}", "w"))
            prev = os.environ.get("CC_ROOM_DIR")
            os.environ["CC_ROOM_DIR"] = rd
            try:
                got = room_launches()
            finally:
                os.environ.pop("CC_ROOM_DIR") if prev is None else os.environ.update(CC_ROOM_DIR=prev)
                gone.wait()
            ok("room_launches: a live waiter's entry is `waiting`, one whose waiter AND tmux server are gone is `lost` "
               "(cc-room resume starts it again); one killed under a live server, one past 7 days, a half-written .tmp "
               "and an unreadable file are none; an entry whose `server` is a dict, a two-letter string or one item "
               "is skipped and the entries after it are still read (a dict raised KeyError and stopped the pass for "
               "every repo)", got == {"rq/alive": "waiting", "rq/lost": "lost"})
        other = subprocess.Popen(["sleep", "300"])
        fx, own = f"_cctest{other.pid}", f"_cctest{os.getpid()}"
        try:
            for r in (fx, own):
                cb("init", r, f"{th}/dev/{r}", "main")
                cb("add", r, "w1", "push refused", "")
                cb("status", r, "w1", "waiting")
            for w in ("w1", "w5"):                      # the worktrees a suite lays down: one on its board, one not
                os.makedirs(f"{th}/.cc/worktrees/{fx}/{w}", exist_ok=True)
            rF = subprocess.run([sys.executable, os.path.realpath(__file__), "--apply", "--no-net", "--grace", "0"],
                                env=env, capture_output=True, text=True, timeout=120)
        finally:
            other.kill(); other.wait()
        snpF = json.load(open(f"{th}/.cc/state/reconcile.json"))["tracks"]
        ok("a `_cctest<pid>` board is a selftest fixture, not a board: the unfiltered pass reconciles the real repo "
           "beside it and never it — not in the output, not in the snapshot the digest and the Home tab read",
           rF.returncode in (0, 1) and fx not in rF.stdout and not any(k.startswith(fx) for k in snpF)
           and any(k.startswith(repo) for k in snpF))
        ok("…and its WORKTREES are that suite's scaffolding too, never 'a worktree with no board entry': the run "
           "prints every record, and neither the one on the fixture board nor the one with no row at all is there",
           f"{fx}/w1" not in rF.stdout and f"{fx}/w5" not in rF.stdout)
        ok("…and a fixture whose suite is alive survives the sweep that pass gives the sweep",
           os.path.exists(f"{th}/.cc/boards/{fx}.json"))
        ok("…while a `_cctest<pid>` board whose <pid> is this pass's own ancestor is the suite's own: reconciled and "
           "snapshotted like any board — the suite's `cc ls` and `cc digest` must see their track",
           any(k.startswith(own) for k in snpF))
        for w in ("t", "u"):
            os.makedirs(f"{th}/.cc/worktrees/_ccsbx99999999/{w}", exist_ok=True)
        os.makedirs(f"{th}/.cc/worktrees/{repo}/stray", exist_ok=True)
        rS = subprocess.run([sys.executable, os.path.realpath(__file__), "--no-net", "--grace", "0"],
                            env=env, capture_output=True, text=True, timeout=120)
        ok("a leaked `_ccsbx<pid>` is a suite's scratch on the same rule as `_cctest<pid>`, so its worktrees raise "
           "nothing — while one under a REAL repo with no row on its board is still work the board never heard of",
           "_ccsbx99999999" not in rS.stdout
           and f"{repo}/stray" in rS.stdout and "a worktree with no board entry" in rS.stdout)
        shutil.rmtree(f"{th}/.cc/worktrees/{repo}/stray", ignore_errors=True)
        shutil.rmtree(f"{th}/.cc/worktrees/_ccsbx99999999", ignore_errors=True)
        deliv, prj = f"{th}/.cc/worktrees/{repo}/deliver", f"{th}/prs.json"
        os.makedirs(f"{th}/dev/{repo}", exist_ok=True)      # branch_prs asks from the repo's own checkout or not at all
        subprocess.run(["git", "-C", f"{th}/dev/{repo}", "worktree", "add", "-q", "-b", "track/deliver-x", deliv],
                       capture_output=True, timeout=30)     # the repo's own checkout is a git repo since t11's case
        open(f"{th}/gh", "w").write(f'#!/bin/sh\ncase "$*" in\n  *"pr list"*) cat {prj} ;;\n  *) echo OPEN ;;\nesac\n')
        os.chmod(f"{th}/gh", 0o755)

        def orphaned(*flags):
            open(prj, "w").write(flags[0])
            r_ = subprocess.run([sys.executable, os.path.realpath(__file__), repo, *flags[1:]],
                                env=penv, capture_output=True, text=True, timeout=120)
            return f"{repo}/deliver" in r_.stdout

        ok("a worktree whose branch has no PR and no landing is work the board never heard of, as it always was",
           orphaned("[]", "--grace", "0"))
        ok("…but one whose branch has an OPEN PR is a delivery in flight — the builder's worktree is named for its "
           "branch, so no row will ever carry that name, and the offer is a wake-up that finds nothing to do",
           not orphaned('[{"number":9,"state":"OPEN"}]', "--grace", "0"))
        ok("…and one whose PR MERGED a minute ago is that same delivery landing: the merge, the worktree's removal "
           "and this pass race each other, and a person was paged about a worktree whose PR had merged 106 s "
           "before the run (2026-09-11)",
           not orphaned('[{"number":9,"state":"MERGED","mergedAt":"%s"}]'
                        % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() - 60)), "--grace", "0"))
        ok("…while one merged longer ago than a landing's own gap is a leftover nothing is coming back for, and "
           "is reported as a worktree with no board entry always was",
           orphaned('[{"number":9,"state":"MERGED","mergedAt":"%s"}]'
                    % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() - BETWEEN_ROUNDS - 60)),
                    "--grace", "0"))
        ok("…while a PR that is closed and nobody is landing leaves the worktree a leftover again: reported",
           orphaned('[{"number":9,"state":"CLOSED"}]', "--grace", "0"))
        os.makedirs(f"{th}/.cc/state/land", exist_ok=True)
        json.dump({"repo": repo, "pr": 9}, open(f"{th}/.cc/state/land/{repo}-9.json", "w"))
        ok("…and the same PR with a job in the landing queue is mid-delivery, whatever state GitHub says it is in",
           not orphaned('[{"number":9,"state":"CLOSED"}]', "--grace", "0"))
        os.remove(f"{th}/.cc/state/land/{repo}-9.json")
        ok("a worktree made inside the grace window is not reported before its row or its PR can exist",
           not orphaned("[]"))
        ok("…and with no network the branch cannot be looked up, so nothing is forgiven on suspicion",
           orphaned('[{"number":9,"state":"OPEN"}]', "--grace", "0", "--no-net"))
        cb("add", repo, "namedwt", "a row whose worktree is not named after it", "")
        cb("set", repo, "namedwt", "worktree", deliv)
        ok("a row that names the directory outright is the board having heard of it, under any row name and with "
           "no GitHub in it at all", not orphaned("[]", "--grace", "0", "--no-net"))
        shutil.rmtree(deliv, ignore_errors=True)
    def load(name):
        import importlib.machinery, importlib.util
        sp = importlib.util.spec_from_loader(name.replace("-", "_"),
                                             importlib.machinery.SourceFileLoader(name.replace("-", "_"), f"{BIN}/{name}"))
        m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
        return m
    five = {"stale": F(status="blocked", live=True, workers=[1]),              # the board says blocked; a worker is in it
            "asked": F(status="running", journal=("BLOCKED", "which key?")),    # its journal declared a question
            "worker": F(status="running", live=True, workers=[1], loops=[2]),   # a loop and its worker, working
            "idle": F(status="running", live=True, pane_idle=3 * 3600),         # a pane open, nobody at it for 3 h
            "marked": F(status="queued", agent="@3:900", agent_live=True)}      # a live session's subagent has it
    rows5 = []
    for t, fx5 in five.items():
        st5 = effective(fx5, decide(fx5))
        rows5.append(("r", t, fx5, st5) + (waits_for(fx5) if st5 not in TERMINAL else ("", "")))
    snap5 = snapshot(rows5)["tracks"]
    ok("the fixture decides as the table says — running · waiting · running · idle · running, alive where something "
       "is, the question and the mark and the loop and the idle clock carried",
       {k: (v["state"], v["live"], v["waiting_on"]) for k, v in snap5.items()}
       == {"r/stale": ("running", True, ""), "r/asked": ("waiting", False, "person"), "r/worker": ("running", True, ""),
           "r/idle": ("idle", True, ""), "r/marked": ("running", True, "")}
       and snap5["r/asked"]["why"] == "which key?" and snap5["r/marked"]["agent"] and snap5["r/worker"]["loop"]
       and snap5["r/idle"]["idle_for"] == 3 * 3600)
    th5 = tempfile.mkdtemp(prefix="cc-reconcile-consumers-")
    try:
        os.makedirs(f"{th5}/.cc/boards")
        board5 = {t: {"status": fx5["status"], "updated": "2026-09-01T00:00:00Z"} for t, fx5 in five.items()}
        json.dump({"repo": "r", "tracks": board5}, open(f"{th5}/.cc/boards/r.json", "w"))
        slack = load("cc-slack")
        slack.HOME = th5
        home5 = {t["name"]: t for t in slack.home_tracks(snap5, {})[0]}
        ok("THE HOME TAB SAYS WHAT THIS SAID — the same word and the same question for all five, the board it "
           "contradicts printed as stale, the idle clock and no iteration count where no loop is: it reads "
           "home_snapshot() and decides nothing of its own",
           {k: v["state"] for k, v in home5.items()} == {k: v["state"] for k, v in snap5.items()}
           and {k: v["reason"] for k, v in home5.items()}
               == {k: (v["why"] if v["waiting_on"] == "person" else "") for k, v in snap5.items()}
           and "board stale" in home5["r/stale"]["detail"] and "board stale" in home5["r/marked"]["detail"]
           and "idle 3h" in home5["r/idle"]["detail"] and "board stale" not in home5["r/worker"]["detail"])
        home0 = {t["name"]: t for t in slack.home_tracks({}, {})[0]}
        ok("…and with NO snapshot both fall back the way `view` does — the board's own word, nothing alive, no question, "
           "no mark holding — so a decider that cannot answer never splits the two",
           {k: (v["state"], v["reason"], v["detail"]) for k, v in home0.items()}
           == {f"r/{t}": (r["status"], "", "—") for t, r in board5.items()})
    finally:
        shutil.rmtree(th5, ignore_errors=True)
    def bounded(fn, secs=10):   # a read that hangs on the pipe (a plain open would, for good) fails THIS case, not the suite
        import threading
        box = []
        def go():
            try: box.append(fn())
            except Exception as e: box.append(e)
        t = threading.Thread(target=go, daemon=True); t.start(); t.join(secs)
        return box[0] if box else "hung"
    _b, BOARDS = BOARDS, tempfile.mkdtemp(prefix="cc-reconcile-pipe-")
    try:
        os.mkfifo(f"{BOARDS}/pipe.json")
        json.dump({"repo": "real", "tracks": {}}, open(f"{BOARDS}/real.json", "w"))
        ok("boards(): a pipe planted where a board should be is unreadable (None), not a hang, and the real one beside it reads",
           bounded(lambda: [(os.path.basename(fn), d) for fn, d in boards()]) == [("pipe.json", None), ("real.json", {"repo": "real", "tracks": {}})])
    finally:
        shutil.rmtree(BOARDS, ignore_errors=True); BOARDS = _b
    _b, _s, th9 = BOARDS, STATE, tempfile.mkdtemp(prefix="cc-reconcile-tw-")
    globals().update(BOARDS=f"{th9}/.cc/boards", STATE=f"{th9}/.cc/state")
    try:
        os.makedirs(BOARDS); os.makedirs(f"{th9}/dev")
        subprocess.run([f"{BIN}/cc-throwaway", "new", "hb-9"], env={**os.environ, "HOME": th9}, capture_output=True, check=True)
        os.makedirs(f"{th9}/dev/real"); open(f"{th9}/.cc/throwaway/real", "w").write("forged\n")   # a mark nobody made with `new`
        for r in ("hb-9", "real", "other"):
            json.dump({"repo": r, "tracks": {}}, open(f"{BOARDS}/{r}.json", "w"))
        ok("boards(): a throwaway repo's board is skipped, so no pulse, digest or watchdog reads it — while a real one, "
           "even one with a forged registry file, and an unmarked one beside it still read",
           [os.path.basename(fn) for fn, _ in boards()] == ["other.json", "real.json"])
        _w = WTS; globals().update(WTS=f"{th9}/.cc/worktrees")
        try:
            for r in ("hb-9", "other"):
                os.makedirs(f"{WTS}/{r}/fix"); os.utime(f"{WTS}/{r}/fix", (0, 0))
            ok("orphans(): a throwaway repo's old worktree is no orphan, so nobody is asked or paged about it — while an "
               "unmarked repo's beside it still is",
               [(r, t) for r, t, _ in orphans(None, net=False, grace=GRACE)] == [("other", "fix")])
        finally:
            globals().update(WTS=_w)
    finally:
        shutil.rmtree(th9, ignore_errors=True); globals().update(BOARDS=_b, STATE=_s)
    _b, _w, _s, thd = BOARDS, WTS, STATE, tempfile.mkdtemp(prefix="cc-reconcile-depth-")
    globals().update(BOARDS=f"{thd}/.cc/boards", WTS=f"{thd}/.cc/worktrees", STATE=f"{thd}/.cc/state")
    try:
        os.makedirs(BOARDS)
        json.dump({"repo": "other", "tracks": {}}, open(f"{BOARDS}/other.json", "w"))
        for wd in (f"{WTS}/nosuchrepo/sub", f"{WTS}/other/fix"):   # a worktree made at the wrong depth, and a real repo's
            os.makedirs(wd); os.utime(wd, (0, 0))
        ok("orphans(): a dir at WTS/nosuchrepo/sub with no board gives no orphan (a worktree at the wrong depth is not a "
           "track of a repo that is not there) — while a real repo's untracked worktree beside it still is",
           [(r, t) for r, t, _ in orphans(None, net=False, grace=GRACE)] == [("other", "fix")])
    finally:
        shutil.rmtree(thd, ignore_errors=True); globals().update(BOARDS=_b, WTS=_w, STATE=_s)
    # ── the tick's parts: reconcile, wake, sweep, digest — each in a HOME of its own ──
    import contextlib, io
    _g = {k: globals()[k] for k in ("BOARDS", "WTS", "STATE", "DEV", "PULSE_LOG", "JANITOR_LOG", "procs", "tmux_live",
                                    "windows", "live_session", "now")}
    _envkeys = ("HOME", "CC_RECONCILE_STUBS", "PATH", "CC_NOTIFY_LOG_ONLY", "CC_NOTIFY_LOG", "CC_CONFIG", "CC_WAKE")
    _env = {k: os.environ.get(k) for k in _envkeys}

    def scratch(th, stubs):
        """Point every path at <th>, and every sibling this file wakes or sweeps with at a stub in <th>/stubs."""
        os.makedirs(f"{th}/stubs", exist_ok=True)
        for name, body in stubs.items():
            open(f"{th}/stubs/{name}", "w").write("#!/bin/sh\n" + body + "\n"); os.chmod(f"{th}/stubs/{name}", 0o755)
        os.environ.update(HOME=th, CC_RECONCILE_STUBS=f"{th}/stubs", PATH=f"{th}/stubs:{_env['PATH']}",
                          CC_NOTIFY_LOG_ONLY="1", CC_NOTIFY_LOG=f"{th}/notify.log", CC_CONFIG=f"{th}/.cc/config")
        os.environ.pop("CC_WAKE", None)                 # the box's own switch never reaches a fixture
        globals().update(BOARDS=f"{th}/.cc/boards", WTS=f"{th}/.cc/worktrees", STATE=f"{th}/.cc/state", DEV=f"{th}/dev",
                         PULSE_LOG=f"{th}/.cc/state/pulse.log", JANITOR_LOG=f"{th}/.cc/state/janitor.log")
        os.makedirs(f"{th}/.cc/boards", exist_ok=True); os.makedirs(f"{th}/.cc/state", exist_ok=True)

    def restore():
        globals().update(_g)
        for k, v in _env.items():
            os.environ.pop(k, None) if v is None else os.environ.update({k: v})

    def quietly(fn, *a):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn(*a)
        return buf.getvalue()
    NOOP = {"cc-tier": "exit 0", "cc-limit": "exit 1", "cc-pause": "exit 1", "cc-handoff": "exit 1", "cc-model": "exit 1",
            "cc-spend": ":", "cc-scope": ":", "tmux": ":"}
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() - 3 * 86400))
    # (a) a `running` row whose worker AND session are gone past the grace is reconciled; an identical live one is not
    ta = tempfile.mkdtemp(prefix="cc-reconcile-apply-")
    try:
        scratch(ta, NOOP)
        sh(f"{BIN}/cc-board", "init", "ra", f"{ta}/dev/ra", "main", timeout=30)
        for t in ("dead", "alive"):
            os.makedirs(f"{ta}/.cc/worktrees/ra/{t}")
            sh(f"{BIN}/cc-board", "add", "ra", t, "a row", "", timeout=30)
            sh(f"{BIN}/cc-board", "status", "ra", t, "running", timeout=30)
        globals().update(procs=lambda: ({"ra/alive"}, set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}))
        quietly(main, ["ra", "--apply", "--no-net", "--grace", "0"])
        b = board_read(f"{ta}/.cc/boards/ra.json")["tracks"]
        ok("APPLY: a running row with no worker and no session past the grace is set `blocked`, with a `reconciled:` note",
           b["dead"]["status"] == "blocked" and any("reconciled: running → blocked" in str(n.get("msg", "")) for n in b["dead"].get("notes") or []))
        ok("…while the identical row with a live process in its worktree is left exactly as it was",
           b["alive"]["status"] == "running" and not (b["alive"].get("notes") or []))
    finally:
        restore(); shutil.rmtree(ta, ignore_errors=True)
    # (l) LANDED ELSEWHERE: a row whose branch landed inside another PR goes merged; a half-landed one stays
    tl = tempfile.mkdtemp(prefix="cc-reconcile-landed-")
    try:
        R = f"{tl}/dev/rl"
        g = lambda *a: (sh("git", "-C", R, "-c", "user.name=t", "-c", "user.email=t@t", *a, timeout=30).stdout or "").strip()
        def put(name, body, msg):
            open(f"{R}/{name}", "w").write(body); g("add", name); g("commit", "-qm", msg)
        os.makedirs(R); g("init", "-q", "-b", "main"); open(f"{R}/r.txt", "w").write("x\ny\nz\n"); g("add", "r.txt")
        open(f"{R}/ab.txt", "w").write("alpha=0\nbeta=0\n"); open(f"{R}/gd.txt", "w").write("gamma=0\ndelta=0\n")
        g("add", "ab.txt", "gd.txt"); put("a.txt", "1\n2\n3\n", "c0")
        g("branch", "track/stacked"); g("branch", "track/half"); g("branch", "track/rv")
        g("branch", "track/adj"); g("branch", "track/combo")
        put("b.txt", "b\n", "c1"); g("branch", "track/fresh")    # fresh: on main's first-parent line, no work of its own
        g("checkout", "-q", "track/stacked"); put("a.txt", "one\n2\n3\n", "s1")
        g("checkout", "-q", "-b", "track/evil"); g("merge", "-q", "--no-commit", "main")   # main merged in, z.txt added
        open(f"{R}/z.txt", "w").write("z\n"); g("add", "z.txt"); g("commit", "-qm", "merge main")
        g("checkout", "-q", "-b", "track/carrier", "main"); g("cherry-pick", "track/stacked")
        put("a.txt", "one\n2\nthree\n", "k2")                    # the PR that carried s1, rebased, plus its own commit
        g("checkout", "-q", "track/half"); g("cherry-pick", "track/stacked"); put("h.txt", "h\n", "h2")
        g("checkout", "-q", "track/rv"); put("r.txt", "X\ny\nz\n", "rv1")
        g("checkout", "-q", "-b", "track/reverter", "main"); g("cherry-pick", "track/rv")   # carried rv1, then
        g("revert", "--no-edit", "HEAD"); put("q.txt", "q\n", "q1")                         # took it out before its squash
        g("checkout", "-q", "track/adj"); put("ab.txt", "alpha=1\nbeta=0\n", "adj1")
        g("checkout", "-q", "-b", "track/adjcarrier", "main"); g("cherry-pick", "track/adj")   # carried adj1, took it
        g("revert", "--no-edit", "HEAD"); put("ab.txt", "alpha=0\nbeta=1\n", "adj2")     # out, then edited the next line
        g("checkout", "-q", "track/combo"); put("gd.txt", "gamma=1\ndelta=0\n", "cb1")
        g("checkout", "-q", "-b", "track/combocarrier", "main"); g("cherry-pick", "track/combo")
        put("gd.txt", "gamma=1\ndelta=1\n", "cb2")                 # carried cb1 for real, plus the next line
        g("checkout", "-q", "main"); g("merge", "-q", "--squash", "track/carrier"); g("commit", "-qm", "carrier (#5)")
        g("merge", "-q", "--squash", "track/reverter"); g("commit", "-qm", "reverter (#8)")
        g("merge", "-q", "--squash", "track/adjcarrier"); g("commit", "-qm", "adjcarrier (#10)")
        g("merge", "-q", "--squash", "track/combocarrier"); g("commit", "-qm", "combocarrier (#11)")
        put("a.txt", "ONE\n2\nthree\n", "c3")                    # main moves on: merging the stacked tip would conflict
        put("gd.txt", "gamma=2\ndelta=1\n", "c4")                 # …and the combo tip
        g("checkout", "-q", "-b", "track/plain"); put("p.txt", "p\n", "p1")
        g("checkout", "-q", "main"); g("merge", "-q", "--no-ff", "-m", "plain (#6)", "track/plain")
        g("branch", "track/busy", "track/stacked")             # landed too, but a worker is in it
        g("branch", "track/ownpr", "track/stacked")            # landed too, but its own PR could not be read
        g("branch", "feature/odd", "track/stacked")            # landed too, on a branch not named after its row
        sh("git", "init", "-q", "--bare", f"{tl}/origin.git", timeout=30)
        g("remote", "add", "origin", f"{tl}/origin.git"); g("push", "-q", "origin", "main")
        g("checkout", "-q", "-b", "track/unpushed"); put("u.txt", "u\n", "u1")   # merged into a main nobody pushed
        g("checkout", "-q", "main"); g("merge", "-q", "--no-ff", "-m", "local only", "track/unpushed")
        heads = ",".join(f'{{"number": {n}, "headRefOid": "{g("rev-parse", b)}"}}' for n, b in ((5, "track/carrier"),
                                                                    (8, "track/reverter"), (10, "track/adjcarrier"),
                                                                    (11, "track/combocarrier")))
        scratch(tl, dict(NOOP, gh=f'case "$*" in *"--state merged"*) echo \'[{heads}]\';; *) echo "[]";; esac'))
        cbl = lambda *a: sh(f"{BIN}/cc-board", *a, timeout=30)
        cbl("init", "rl", R, "main")
        rows = (("stacked", "blocked"), ("half", "blocked"), ("fresh", "review"), ("plain", "review"), ("busy", "blocked"),
                ("ownpr", "review"), ("rv", "blocked"), ("evil", "blocked"), ("unpushed", "review"), ("odd", "blocked"),
                ("adj", "blocked"), ("combo", "blocked"))
        for t, st in rows:
            cbl("add", "rl", t, "a row", ""); cbl("status", "rl", t, st)
            if t != "odd":
                os.makedirs(f"{tl}/.cc/worktrees/rl/{t}")
        g("worktree", "add", "-q", f"{tl}/.cc/worktrees/rl/odd", "feature/odd")
        cbl("set", "rl", "ownpr", "pr", "https://github.com/o/rl/pull/9")
        globals().update(procs=lambda: ({"rl/busy"}, set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}))
        cache = f"{tl}/.cc/state/landed-patches.json"
        rep = quietly(main, ["rl", "--grace", "0"])
        b = board_read(f"{tl}/.cc/boards/rl.json")["tracks"]
        ok("LANDED: a report run lists what it would close and writes neither the board nor the patch-id cache",
           "would fix  rl/stacked" in rep and b["stacked"]["status"] == "blocked" and not os.path.exists(cache))
        quietly(main, ["rl", "--apply", "--grace", "0"])
        b = board_read(f"{tl}/.cc/boards/rl.json")["tracks"]
        note = lambda t: " ".join(str(n.get("msg", "")) for n in b[t].get("notes") or [])
        ok("LANDED: a blocked row whose branch was rebased into another PR that squash-merged goes `merged`, naming "
           "that PR — main moved on past it, so only its patches say it landed; --apply keeps the patch-ids",
           b["stacked"]["status"] == "merged" and "reconciled: blocked → merged (its branch landed inside #5)" in note("stacked")
           and os.path.exists(cache))
        ok("…and a review row whose branch merged into origin's main with a merge commit goes `merged` too",
           b["plain"]["status"] == "merged" and "nothing left that main lacks" in note("plain"))
        ok("…as does a row whose worktree sits on a branch not named after it (the worktree's own branch is read)",
           b["odd"]["status"] == "merged" and "inside #5" in note("odd"))
        ok("…while a half-landed branch (one commit landed, one nowhere) stays blocked, untouched",
           b["half"]["status"] == "blocked" and "merged" not in note("half"))
        ok("…a branch with no work of its own past main stays in review, and a landed one with a worker in it "
           "is never set merged: 'never touch a row that is running or has a live worker'",
           b["fresh"]["status"] == "review" and b["busy"]["status"] != "merged" and "merged" not in note("busy"))
        ok("…and a landed one whose own PR this pass could not read stays in review: that PR may be open, and the "
           "next pass would set it back (a row whose PR is still open while its commits sit inside another merged PR)",
           b["ownpr"]["status"] == "review" and "merged" not in note("ownpr"))
        ok("…a branch whose patch a merged PR applied and then reverted before its squash stays blocked: its patch-id "
           "is in #8's history, but #8's final tree does not hold it",
           b["rv"]["status"] == "blocked" and "merged" not in note("rv"))
        adj_fork = g("merge-base", "origin/main", "track/adj")
        ok("…a branch whose patch #10 applied, reverted, then edited the line next to it stays blocked: its hunk no "
           "longer applies to #10's tree, but its old line is still there, and failing to apply proves nothing",
           b["adj"]["status"] == "blocked" and "merged" not in note("adj")
           and not delivered(R, adj_fork, g("rev-parse", "track/adj"), [g("rev-parse", "track/adjcarrier")]))
        ok("…while one that really went in inside a combined #11, which then edited the line next to it, goes `merged`",
           b["combo"]["status"] == "merged" and "inside #11" in note("combo"))
        evil = g("rev-parse", "track/evil")
        ok("…a branch whose own patch landed in #5 but whose merge commit added z.txt stays blocked: the merge adds "
           "changes of its own, which a clean merge commit (main's `plain (#6)`) does not",
           b["evil"]["status"] == "blocked" and merge_adds(R, evil) and not merge_adds(R, g("rev-parse", "origin/main")))
        ok("…and a branch merged only into a local main nobody pushed stays in review: origin's main decides",
           b["unpushed"]["status"] == "review" and "merged" not in note("unpushed"))
        # a landed branch whose real worktree holds uncommitted work; and its clean twin, which does go merged
        for t in ("dirtywt", "cleanwt"):
            g("branch", f"track/{t}", "track/stacked"); cbl("add", "rl", t, "a row", ""); cbl("status", "rl", t, "blocked")
            g("worktree", "add", "-q", f"{tl}/.cc/worktrees/rl/{t}", f"track/{t}")
        open(f"{tl}/.cc/worktrees/rl/dirtywt/wip.txt", "w").write("not committed\n")
        # a row whose `worktree` (board text a member writes) names a repo of its own with a planted core.fsmonitor:
        # one outside WTS, and one inside WTS/rl/ that is a plain clone rather than a worktree of DEV/rl
        pw = f"{tl}/fsmonitor-ran"
        for t, path in (("planted", f"{tl}/member/planted"), ("planted2", f"{tl}/.cc/worktrees/rl/planted2")):
            g("branch", f"track/{t}", "track/stacked"); cbl("add", "rl", t, "a row", ""); cbl("status", "rl", t, "blocked")
            sh("git", "init", "-q", path, timeout=30)
            open(f"{path}/.git/config", "a").write(f"[core]\n\tfsmonitor = touch {pw}\n")
            cbl("set", "rl", t, "worktree", path)
        sh("git", "-C", f"{tl}/member/planted", "status", "--porcelain", timeout=30)
        armed = os.path.exists(pw)                       # the fixture is live: plain `git status` there runs it
        if armed:
            os.remove(pw)
        quietly(main, ["rl", "--grace", "0"]); quietly(main, ["rl", "--apply", "--grace", "0"])
        b = board_read(f"{tl}/.cc/boards/rl.json")["tracks"]
        ok("LANDED: a landed branch whose worktree holds uncommitted work stays blocked, while its clean twin goes merged",
           b["dirtywt"]["status"] == "blocked" and "merged" not in note("dirtywt")
           and b["cleanwt"]["status"] == "merged" and "inside #5" in note("cleanwt"))
        ok("LANDED: a row's `worktree` pointing at a repo with a planted core.fsmonitor never runs it (outside WTS, or "
           "inside it but not a worktree of DEV/<repo>): the row is judged on its branch name alone",
           armed and not os.path.exists(pw) and b["planted"]["status"] == "merged"
           and b["planted2"]["status"] == "merged"
           and wt_pin("rl", f"{tl}/member/planted") is None and wt_pin("rl", f"{tl}/.cc/worktrees/rl/planted2") is None
           and wt_pin("rl", f"{tl}/.cc/worktrees/rl/cleanwt")[0] == os.path.realpath(f"{tl}/.cc/worktrees/rl/cleanwt"))
        # the two shapes the security read reproduced, each armed first (plain git runs the planted command) and then
        # run through every pass that reaches them, which must not. PAIR: a planted admin dir DEV/rl/.git/worktrees/
        # pair whose `commondir` names a repo with an fsmonitor, and WTS/rl/pair/.git pointing at it; wt_pin() vouches
        # for the pair, so only wt_git()'s own GIT_COMMON_DIR keeps git off that commondir. GITLINK: a real worktree with
        # an embedded repo staged as a gitlink, whose own config has an fsmonitor: `status` would run git inside it.
        pw2, rlg = f"{tl}/fsmonitor-ran2", os.path.realpath(R) + "/.git"
        sh("git", "init", "-q", f"{tl}/member/evilcommon", timeout=30)
        open(f"{tl}/member/evilcommon/.git/config", "a").write(f"[core]\n\tfsmonitor = touch {pw2}\n")
        adm, pwt = f"{rlg}/worktrees/pair", f"{tl}/.cc/worktrees/rl/pair"
        os.makedirs(adm); os.makedirs(pwt)
        g("branch", "track/pair", "track/stacked"); cbl("add", "rl", "pair", "a row", ""); cbl("status", "rl", "pair", "blocked")
        open(f"{adm}/HEAD", "w").write("ref: refs/heads/track/pair\n")
        open(f"{adm}/commondir", "w").write(f"{tl}/member/evilcommon/.git\n")
        open(f"{adm}/gitdir", "w").write(os.path.realpath(pwt) + "/.git\n")
        open(f"{pwt}/.git", "w").write(f"gitdir: {adm}\n")
        g("branch", "track/gitlink", "track/stacked"); cbl("add", "rl", "gitlink", "a row", ""); cbl("status", "rl", "gitlink", "done")
        glw = f"{tl}/.cc/worktrees/rl/gitlink"
        g("worktree", "add", "-q", glw, "track/gitlink")
        gi = lambda *a: sh("git", "-C", glw, "-c", "user.name=t", "-c", "user.email=t@t", *a, timeout=30)
        gi("init", "-q", "inner"); open(f"{glw}/inner/i", "w").write("i\n")
        gi("-C", "inner", "add", "i"); gi("-C", "inner", "commit", "-qm", "i")
        open(f"{glw}/inner/.git/config", "a").write(f"[core]\n\tfsmonitor = touch {pw}\n")
        gi("add", "inner")
        sh("git", "-C", pwt, "status", "--porcelain", timeout=30); sh("git", "-C", glw, "status", "--porcelain", timeout=30)
        armed2 = os.path.exists(pw) and os.path.exists(pw2)
        for x in (pw, pw2):
            if os.path.exists(x):
                os.remove(x)
        quietly(main, ["rl", "--grace", "0"]); quietly(main, ["rl", "--apply", "--grace", "0"])
        quietly(sweep_repo, "rl", Sweep(dry=True), {}, False, 0)   # rule 1 reads gitlink's dirt, rule 2 every row's
        seen = branch_unpushed("rl", pwt), dirty("rl", glw), dirty("rl", pwt), wt_branch("rl", pwt)
        b = board_read(f"{tl}/.cc/boards/rl.json")["tracks"]
        ok("PINNED GIT: a planted worktrees/pair/commondir + WTS/rl/pair/.git pair, and a staged embedded repo with an "
           "fsmonitor in a real worktree, run neither command through reconcile, --apply, the sweep or the helpers",
           armed2 and not os.path.exists(pw) and not os.path.exists(pw2)
           and wt_pin("rl", pwt) is not None and seen[3] == "track/pair"
           and b["gitlink"]["status"] == "done")
        _pi = patch_ids
        try:                                             # a head whose read timed out is not cached for good
            globals().update(patch_ids=lambda *a: None)
            c0 = {}; landed_ctx(R, [(5, g("rev-parse", "track/carrier"))], c0)
            globals().update(patch_ids=_pi)
            c1 = {}; landed_ctx(R, [(5, g("rev-parse", "track/carrier"))], c1)
        finally:
            globals().update(patch_ids=_pi)
        ok("LANDED: a merged head whose patch-ids could not be read (timeout) is left out of the cache; a read one is kept",
           c0 == {} and list(c1.values())[0][0] == 5 and list(c1.values())[0][1])
        # MAIN-GITDIR COMMONDIR: a member plants DEV/rl/.git/commondir naming a repo of theirs whose config gives origin
        # an uploadpack command and an fsmonitor. Plain git in the checkout follows it (armed first); every repo-level
        # call reconcile and the sweep make (has_remote, merged heads, patch-ids, ls-remote) must run neither.
        pw3, evc = f"{tl}/commondir-ran", f"{tl}/member/evilcd"
        sh("git", "init", "-q", evc, timeout=30)
        open(f"{evc}/.git/config", "a").write(f'[remote "origin"]\n\turl = {tl}/origin.git\n'
                                              f'\tuploadpack = touch {pw3}; git-upload-pack\n[core]\n\tfsmonitor = touch {pw3}\n')
        open(f"{R}/.git/commondir", "w").write(f"{evc}/.git\n")
        try:
            sh("git", "-C", R, "ls-remote", "--heads", "origin", timeout=30)
            armed3 = os.path.exists(pw3)
            if armed3:
                os.remove(pw3)
            globals().get("_SHADOWS", {}).clear()            # nothing this pass made before the plant is reused
            quietly(main, ["rl", "--grace", "0"])
            out3 = quietly(sweep_repo, "rl", Sweep(dry=True), {}, False, 0)
        finally:
            os.remove(f"{R}/.git/commondir")
        ok("PINNED GIT: a planted commondir in the checkout's own .git (origin's uploadpack and an fsmonitor in the repo "
           "it names) runs nothing through reconcile or the sweep, which still list origin's branches",
           armed3 and not os.path.exists(pw3) and "origin could not be listed" not in out3)
    finally:
        restore(); shutil.rmtree(tl, ignore_errors=True)
    # (m) THE BAYESIAN-SQUIRREL SHAPE: six branches rebased into two squash-merged PRs, main moved on since. Five are
    # a stack (backtester → backtester-fixes → live-path → live-path-fixes → live-kill-fixes) carried by #5 (the
    # kill-file-fixes branch); prices is carried by #7 (prices-fixes). Each layer edits lines the one below wrote.
    tm = tempfile.mkdtemp(prefix="cc-reconcile-bs-")
    try:
        R = f"{tm}/dev/bs"
        g = lambda *a: (sh("git", "-C", R, "-c", "user.name=t", "-c", "user.email=t@t", *a, timeout=30).stdout or "").strip()
        def put(name, body, msg):
            open(f"{R}/{name}", "w").write(body); g("add", name); g("commit", "-qm", msg)
        nine = lambda first, last: f"{first}\n" + "".join(f"{i}\n" for i in range(2, 9)) + f"{last}\n"
        os.makedirs(R); g("init", "-q", "-b", "main"); put("a.txt", nine(1, 9), "c0")
        g("checkout", "-q", "-b", "track/prices"); put("prices.py", "p\n", "p1")
        g("checkout", "-q", "-b", "track/dashboard", "main"); put("dash.py", "d\n", "d1")   # landed nowhere
        g("checkout", "-q", "-b", "track/backtester", "main"); put("bt.py", "a\nb\nc\n", "bt1")
        g("checkout", "-q", "-b", "track/backtester-fixes"); put("bt.py", "a\nB\nc\n", "bt2")
        g("checkout", "-q", "-b", "track/live-path"); put("live.py", "l1\nl2\n", "lp1"); put("a.txt", nine("L", 9), "lp1b")
        g("checkout", "-q", "-b", "track/live-path-fixes"); put("live.py", "L1\nl2\n", "lp2")
        g("checkout", "-q", "-b", "track/live-kill-fixes"); put("kill.py", "k\n", "lk1")
        g("checkout", "-q", "main"); put("a.txt", nine(1, "9m"), "m1")   # main moves on, clear of lp1b's lines
        stack = g("rev-list", "--reverse", "main..track/live-kill-fixes").split()
        g("checkout", "-q", "-b", "track/kill-file-fixes"); g("cherry-pick", *stack)        # the stack, rebased
        put("kf.txt", "kf\n", "kf1")
        g("checkout", "-q", "main"); g("merge", "-q", "--squash", "track/kill-file-fixes"); g("commit", "-qm", "kill-file-fixes (#5)")
        g("checkout", "-q", "-b", "track/prices-fixes"); g("cherry-pick", "track/prices"); put("prices.py", "P\n", "p2")
        g("checkout", "-q", "main"); g("merge", "-q", "--squash", "track/prices-fixes"); g("commit", "-qm", "prices-fixes (#7)")
        put("a.txt", nine("LL", "9m"), "m2"); put("prices.py", "PP\n", "m3"); put("bt.py", "a\nB\nC\n", "m4")   # on again
        sh("git", "init", "-q", "--bare", f"{tm}/origin.git", timeout=30)
        g("remote", "add", "origin", f"{tm}/origin.git"); g("push", "-q", "origin", "main")
        heads = ",".join(f'{{"number": {n}, "headRefOid": "{g("rev-parse", b)}"}}' for n, b in ((5, "track/kill-file-fixes"),
                                                                                            (7, "track/prices-fixes")))
        scratch(tm, dict(NOOP, gh=f'case "$*" in *"--state merged"*) echo \'[{heads}]\';; *) echo "[]";; esac'))
        cbl = lambda *a: sh(f"{BIN}/cc-board", *a, timeout=30)
        cbl("init", "bs", R, "main")
        six = ("backtester", "backtester-fixes", "live-path", "live-path-fixes", "live-kill-fixes", "prices")
        for t in six + ("dashboard",):
            os.makedirs(f"{tm}/.cc/worktrees/bs/{t}"); cbl("add", "bs", t, "a row", ""); cbl("status", "bs", t, "blocked")
        globals().update(procs=lambda: (set(), set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}))
        plain = all(sh("git", "-C", R, "merge-tree", "--write-tree", "origin/main", f"track/{t}", timeout=30).returncode
                    for t in six)
        quietly(main, ["bs", "--apply", "--grace", "0"])
        b = board_read(f"{tm}/.cc/boards/bs.json")["tracks"]
        inside = {t: next((n for n in (str(x.get("msg", "")) for x in b[t].get("notes") or []) if "landed inside" in n), "")
                  for t in b}
        ok("BAYESIAN-SQUIRREL: of seven blocked rows, exactly the six whose branches went in through fund#5 and #7 go "
           "`merged` — none of them merges into main cleanly any more — and the one that landed nowhere stays",
           plain and sorted(t for t in b if b[t]["status"] == "merged") == sorted(six) and b["dashboard"]["status"] == "blocked")
        ok("…five name #5 and prices names #7",
           all(inside[t].endswith("(its branch landed inside #5)") for t in six[:5]) and inside["prices"].endswith("inside #7)"))
    finally:
        restore(); shutil.rmtree(tm, ignore_errors=True)
    # (h) HOLDS: a hold that waits on a merged PR is lifted; on an open one it stands; beside another condition, a note
    ok("HOLDS: the hold's own wait words name the PRs — both of `#558 and #561`, `improve's #632` — and nothing else",
       hold_prs("starts when #558 and #561 land: same files; then one worker")[0] == (558, 561)
       and hold_prs("starts when improve's #632 lands")[0] == (632,)
       and hold_prs("waits for PR #12")[0] == (12,) and hold_prs("after #7")[0] == (7,))
    ok("…while a PR that CLOSES the row, or one only mentioned, is no wait: its landing is not this row's go",
       hold_prs("covered by open PR #635, which names this row in its Closes list")[0] == ()
       and hold_prs("orch owns it: after #782's rebase, promote ends the lane")[0] == ()
       and hold_prs("hold sweep: #695 landed; still needs a probe")[0] == ())
    ok("…and a hold that names an owner decision, load, or another row on the board is mixed; a bare PR wait is not",
       hold_prs("starts when #11 lands and the owner decides")[1] == "owner"
       and hold_prs("after #11, when the lane's load drains")[1] == "load"
       and hold_prs("after #11 and other-row-here", "me", {"other-row-here": {}})[1] == "row other-row-here"
       and hold_prs("starts when #11 lands: same file core/bin/cc-slack; then a builder", "me", {"me": {}})[1] == "")
    th_ = tempfile.mkdtemp(prefix="cc-reconcile-holds-")
    try:
        scratch(th_, dict(NOOP, gh=f'echo "$3" >> {th_}/gh.log; case "$3" in 11) echo MERGED;; 12) echo OPEN;; '
                                    f'13) echo CLOSED;; esac'))
        cbh = lambda *a: sh(f"{BIN}/cc-board", *a, timeout=30)
        cbh("init", "rh", f"{th_}/dev/rh", "main")
        for t, hold in (("m", "starts when #11 lands: same file; then a builder"), ("o", "waits for PR #12"),
                        ("c", "after #13"), ("x", "starts when #11 lands and the owner decides the shape"),
                        ("fin", "after #11")):
            cbh("add", "rh", t, "a row", ""); cbh("set", "rh", t, "held", hold)
        cbh("status", "rh", "fin", "merged")
        rows = lambda: board_read(f"{th_}/.cc/boards/rh.json")["tracks"]
        msgs = lambda t: [str(n.get("msg", "")) for n in rows()[t].get("notes") or []]
        asked = lambda: open(f"{th_}/gh.log").read().split() if os.path.exists(f"{th_}/gh.log") else []
        ok("HOLDS: --no-net asks nothing and changes nothing", holds_pass(False) == [] and asked() == [])
        dry = holds_pass(True, dry=True)
        ok("HOLDS: a dry run lists what it would lift and what it would note, and writes nothing",
           any("hold lifted  rh/m" in ln for ln in dry) and any("hold kept  rh/x" in ln for ln in dry)
           and rows()["m"]["held"] and not any("hold" in m for m in msgs("x"))
           and not os.path.exists(f"{th_}/.cc/state/hold-prs.json"))
        os.remove(f"{th_}/gh.log")
        quietly(tick, {}, True)
        ok("HOLDS (the tick): a hold waiting on a merged PR is lifted, with a note quoting what it said",
           not str(rows()["m"].get("held") or "") and any("hold lifted by cc-reconcile: #11 has merged" in m
                                                         and "starts when #11" in m for m in msgs("m")))
        ok("…while a hold on an OPEN PR, and one on a PR closed unmerged, stand untouched with no note",
           rows()["o"]["held"] == "waits for PR #12" and rows()["c"]["held"] == "after #13"
           and not msgs("o") and not msgs("c"))
        ok("…and a MIXED hold stays held and only gets a note that the PR half is met",
           rows()["x"]["held"].startswith("starts when #11") and any("the PR half is met (#11 has merged)" in m for m in msgs("x")))
        ok("…and a finished row's hold is not read at all",
           rows()["fin"]["held"] == "after #11" and not msgs("fin"))
        ok("…and each distinct PR is asked ONCE for the pass, however many holds name it",
           sorted(asked()) == ["11", "12", "13"])
        os.remove(f"{th_}/gh.log")
        quietly(tick, {}, True)
        ok("HOLDS: the next tick asks only the PRs that have not merged — a merge is cached for good — and the mixed "
           "hold is not noted twice", sorted(asked()) == ["12", "13"]
           and sum("the PR half is met" in m for m in msgs("x")) == 1)
    finally:
        restore(); shutil.rmtree(th_, ignore_errors=True)
    # PR STATES IN ONE BATCH: a board sorted late still has its PRs read when earlier boards spent the PRMAX budget
    tq = tempfile.mkdtemp(prefix="cc-reconcile-prbatch-")
    try:
        gql = ('{"data":{"repository":{"p5":{"state":"MERGED"},"p6":{"state":"OPEN"},"p7":null}},'
               '"errors":[{"message":"Could not resolve to a PullRequest with the number of 7."}]}')
        scratch(tq, dict(NOOP, gh=f'echo "$*" >> {tq}/gh.log; [ "$1" = api ] && [ -f {tq}/gql ] && cat {tq}/gql && exit 1; '
                                  f'[ "$2" = view ] && echo "$3" >> {tq}/view.log; exit 1'))
        os.makedirs(f"{tq}/dev/zz")
        json.dump({"repo": "zz", "tracks": {
            "a": {"status": "review", "pr": "https://github.com/o/zz/pull/5", "updated": old},
            "b": {"status": "review", "pr": "6", "updated": old},
            "c": {"status": "review", "pr": "https://github.com/o/zz/pull/7", "updated": old},
            "m": {"status": "merged", "pr": "https://github.com/o/zz/pull/8", "updated": old}}},
                  open(f"{tq}/.cc/boards/zz.json", "w"))
        globals().update(procs=lambda: (set(), set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}),
                         PRMAX=0)
        open(f"{tq}/gql", "w").write(gql)
        got = {tr: fa["pr_state"] for _, tr, _, fa in facts(["zz"])}
        calls = open(f"{tq}/gh.log").read().splitlines()
        ok("PR BATCH: with the one-at-a-time budget spent, one GraphQL query still reads the board's PRs — a URL "
           "and a bare number alike — and a PR it could not answer stays unknown, never guessed",
           got == {"a": "MERGED", "b": "OPEN", "c": "?", "m": None}
           and sum(c.startswith("api graphql") for c in calls) == 2 and not os.path.exists(f"{tq}/view.log"))
        ok("…and a merged row's PR is not asked at all",
           not any("p8:" in c for c in calls))
        ok("…and decide() moves the merged one to merged and keeps the open one in review, with no 'worktree gone'",
           decide(F(status="review", pr="u", pr_state=got["a"], wt_exists=False, worked=True))[0][:2] == ("fix", "merged")
           and not any("worktree" in w for _, _, w in decide(F(status="review", pr="u", pr_state=got["b"],
                                                                 wt_exists=False, worked=True))))
        os.remove(f"{tq}/gql"); os.remove(f"{tq}/gh.log"); globals()["PRMAX"] = 1
        got = {tr: fa["pr_state"] for _, tr, _, fa in facts(["zz"])}
        ok("…and when the batch fails (GraphQL rate-limited), the budget reads one PR alone and the rest are unknown",
           sorted(got.values(), key=str) == ["?", "?", "?", None]
           and len(open(f"{tq}/view.log").read().split()) == 1)
    finally:
        restore(); shutil.rmtree(tq, ignore_errors=True)
    # (b) the tick wakes an idle seat once for a startable row, not again for the same state, never for a channel repo
    tb = tempfile.mkdtemp(prefix="cc-reconcile-wake-")
    try:
        scratch(tb, dict(NOOP, **{"cc-brief": 'r=$2; shift 2; IFS=,; echo "$r: $# of $# queued rows could start now"; '
                                              'echo "  a builder each: $*"',
                                  "cc": f'echo "start $1" >> {tb}/cc.log', "cc-msg": f'echo "msg $1" >> {tb}/cc.log'}))
        os.makedirs(f"{tb}/dev/wr"); os.makedirs(f"{tb}/dev/chan")
        json.dump({"repo": "wr", "tracks": {"q1": {"status": "queued", "updated": old}}}, open(f"{tb}/.cc/boards/wr.json", "w"))
        json.dump({"repo": "chan", "tracks": {"s1": {"kind": "session", "status": "running", "updated": old},
                                              "s2": {"kind": "session", "status": "queued", "updated": old}}},
                  open(f"{tb}/.cc/boards/chan.json", "w"))
        globals().update(procs=lambda: (set(), set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}))

        def woke():
            return open(f"{tb}/cc.log").read().splitlines() if os.path.exists(f"{tb}/cc.log") else []
        quietly(tick, {}, True)
        # "cc-pulse.timer ... INSTALLED OFF: ... switching that on is the owner's call, not the installer's" (units.json)
        ok("WAKE: with CC_WAKE unset the tick wakes nobody, starts nothing, and pulse.log says the wake is off",
           woke() == [] and "wr skip — the wake is off" in open(f"{tb}/.cc/state/pulse.log").read()
           and not os.path.exists(f"{tb}/.cc/state/wr/pulse.look"))
        os.environ["CC_WAKE"] = "on"
        quietly(tick, {}, True)
        ok("WAKE: switched on, the tick starts the seat of a repo with no live window when cc-brief says a queued row could start",
           woke() == ["start wr"] and os.path.exists(f"{tb}/.cc/state/wr/pulse.look"))
        quietly(tick, {}, True)
        ok("…and the next tick does NOT wake it again for the same state", woke() == ["start wr"])
        json.dump({"repo": "wr", "tracks": {"q1": {"status": "blocked", "updated": old}}}, open(f"{tb}/.cc/boards/wr.json", "w"))
        quietly(tick, {}, True)
        ok("…while a row that STOPPED is a new state, and wakes it once more", woke() == ["start wr", "start wr"])
        plog = open(f"{tb}/.cc/state/pulse.log").read()
        ok("…and a board whose rows are all kind=session is never woken: no start, no line for it in pulse.log",
           "chan" not in "".join(woke()) and " chan " not in plog and "wr start" in plog)
        open(f"{tb}/.cc/state/wr/paused", "w").write('{"at":"2026-01-01T00:00:00Z","by":"owner","note":"","loops":[]}\n')
        os.remove(f"{tb}/stubs/cc-pause")               # no stub: the real cc-pause reads the flag
        json.dump({"repo": "wr", "tracks": {"q1": {"status": "queued", "updated": old}}}, open(f"{tb}/.cc/boards/wr.json", "w"))
        quietly(tick, {}, True)
        ok("…and a paused project is not woken however startable its rows are", woke() == ["start wr", "start wr"]
           and "paused" in open(f"{tb}/.cc/state/pulse.log").read())
        os.remove(f"{tb}/.cc/state/wr/paused"); open(f"{tb}/.cc/state/wr/pulse.off", "w").close()
        json.dump({"repo": "wr", "tracks": {"q1": {"status": "queued", "updated": old},
                                            "q3": {"status": "blocked", "updated": old}}}, open(f"{tb}/.cc/boards/wr.json", "w"))
        quietly(tick, {}, True)
        ok("…nor one whose pulse.off is set (cc-handoff's overlap mark): a new state, still no wake",
           woke() == ["start wr", "start wr"] and "pulse.off" in open(f"{tb}/.cc/state/pulse.log").read())
        os.remove(f"{tb}/.cc/state/wr/pulse.off")
        quietly(tick, {}, True)
        ok("…and with the mark gone that new state wakes it", woke() == ["start wr", "start wr", "start wr"])
        json.dump({"repo": "wr", "tracks": {"q2": {"status": "queued", "updated": old, "bundle": "bundle-x-0000"},
                                            "bundle-x-0000": {"status": "running", "updated": old}}}, open(f"{tb}/.cc/boards/wr.json", "w"))
        quietly(tick, {}, True)
        ok("…a queued row inside a LIVE bundle is in flight, not startable — the bundle row is what is running it — so no wake",
           woke() == ["start wr"] * 3 and "nothing a seat can act on" in open(f"{tb}/.cc/state/pulse.log").read().splitlines()[-1])
        json.dump({"repo": "wr", "tracks": {"q2": {"status": "queued", "updated": old, "bundle": "bundle-x-0000"},
                                            "bundle-x-0000": {"status": "merged", "updated": old}}}, open(f"{tb}/.cc/boards/wr.json", "w"))
        quietly(tick, {}, True)
        ok("…and once the bundle row is no longer live its member is queued again, and wakes the seat", woke() == ["start wr"] * 4)
        json.dump({"repo": "wr", "tracks": {"q4": {"status": "queued", "updated": old}}}, open(f"{tb}/.cc/boards/wr.json", "w"))
        quietly(tick, {"wr/q4": {"state": "queued", "launch": "waiting"}}, True)
        ok("…a queued row whose launch already waits in cc-room is dispatched, not startable: offering it sends a second "
           "worker for the same work (raised 2026-10-03), so no wake",
           woke() == ["start wr"] * 4 and "nothing a seat can act on" in open(f"{tb}/.cc/state/pulse.log").read().splitlines()[-1])
        quietly(tick, {"wr/q4": {"state": "queued", "launch": ""}}, True)
        ok("…and with no launch waiting the same row wakes the seat", woke() == ["start wr"] * 5)
    finally:
        restore(); shutil.rmtree(tb, ignore_errors=True)
    # OWNER-HELD ASKS, end to end: "it is waiting on you" goes out once for a parked or asked row, however short the
    # repeat; a plain waiting row is still told again each repeat (raised-watchdog-repings-parked-row).
    with tempfile.TemporaryDirectory() as th:
        env = dict(os.environ, HOME=th, CC_NOTIFY_LOG_ONLY="1", CC_NOTIFY_LOG=f"{th}/notify.log",
                   CC_SLACK_DIR=f"{th}/.cc/slack", CC_RECONCILE_INJECT=f"{th}/inj")
        repo = f"selfcheckowner{os.getpid()}"
        open(f"{th}/inj", "w").write(f'#!/bin/sh\necho "$@" >> {th}/inj.log\n'); os.chmod(f"{th}/inj", 0o755)
        os.makedirs(f"{th}/.cc/slack")
        json.dump({"C1:1": {"text": f"🔒 confirm the release for {repo}/asked-t-row?", "at": now()}},
                  open(f"{th}/.cc/slack/owner-asks.json", "w"))

        def cb(*a):
            return subprocess.run([f"{BIN}/cc-board", *a], env=env, capture_output=True, text=True, timeout=30)
        cb("init", repo, f"{th}/dev/{repo}", "main")
        for t in ("parked-t-row", "asked-t-row", "plain-t-row"):
            os.makedirs(f"{th}/.cc/worktrees/{repo}/{t}"); os.makedirs(f"{th}/.cc/state/{repo}/{t}")
            open(f"{th}/.cc/state/{repo}/{t}/progress.md", "w").write("STATUS: BLOCKED: no API key on the box\n")
            cb("add", repo, t, "a row that stood down", ""); cb("status", repo, t, "waiting")
        os.makedirs(f"{th}/.cc/worktrees/{repo}/unpushed-t-row/.cc")   # its loop ended; the branch is unjudged
        open(f"{th}/.cc/worktrees/{repo}/unpushed-t-row/.cc/push.err", "w").close()
        cb("add", repo, "unpushed-t-row", "a row whose push failed", ""); cb("status", repo, "unpushed-t-row", "review")
        cb("note", repo, "parked-t-row", "Parked on purpose: the key arrives as an env grant after #1022 lands.")
        argv = [sys.executable, os.path.realpath(__file__), repo, "--notify", "--no-net", "--grace", "0", "--repeat", "0"]
        for _ in range(3):
            subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120)
        told = open(f"{th}/inj.log").read().splitlines() if os.path.exists(f"{th}/inj.log") else []
        n = {t: sum(f"{repo}/{t} " in ln and "waiting on you" in ln for ln in told)
             for t in ("parked-t-row", "asked-t-row", "plain-t-row")}
        ok("OWNER-HELD ASKS: three passes at --repeat 0 tell the parked row and the asked row once each",
           n["parked-t-row"] == 1 and n["asked-t-row"] == 1)
        ok("…and that one line says it is said once, naming the pending owner ask or the parking note",
           any("asked-t-row" in ln and "an owner ask is already pending, so this is said once" in ln for ln in told)
           and any("parked-t-row" in ln and "parked on purpose" in ln for ln in told))
        ok("…while the plain waiting row is told on every pass, as before", n["plain-t-row"] == 3)
        ok("UNPUSHED ONCE: three passes at --repeat 0 tell an ended row's unpushed branch once, not every pass, "
           "beside the plain row that is told three times",
           sum(f"{repo}/unpushed-t-row " in ln and "not pushed" in ln for ln in told) == 1)
    # ORPHAN ONCE (raised-orphan-worktree-nags-wake-a-sleeping-seat): a worktree with no board entry is told once while
    # its directory stands, even when a pass in between skips it (here a fresh mtime inside --grace), which used to
    # drop its memo and make the next pass call it news; once the directory is gone and comes back, it is news again.
    with tempfile.TemporaryDirectory() as th:
        env = dict(os.environ, HOME=th, CC_NOTIFY_LOG_ONLY="1", CC_NOTIFY_LOG=f"{th}/notify.log",
                   CC_SLACK_DIR=f"{th}/.cc/slack", CC_RECONCILE_INJECT=f"{th}/inj")
        repo = f"selfcheckorphan{os.getpid()}"
        open(f"{th}/inj", "w").write(f'#!/bin/sh\necho "$@" >> {th}/inj.log\n'); os.chmod(f"{th}/inj", 0o755)
        subprocess.run([f"{BIN}/cc-board", "init", repo, f"{th}/dev/{repo}", "main"], env=env, capture_output=True, timeout=30)
        owt = f"{th}/.cc/worktrees/{repo}/left-x"

        def opass(grace):
            subprocess.run([sys.executable, os.path.realpath(__file__), repo, "--notify", "--no-net", "--grace", str(grace),
                            "--repeat", "0"], env=env, capture_output=True, text=True, timeout=120)
            return sum(f"{repo}/left-x " in ln and ORPHAN_WHY in ln
                       for ln in (open(f"{th}/inj.log").read().splitlines() if os.path.exists(f"{th}/inj.log") else []))
        os.makedirs(owt)
        n1 = opass(0)
        os.utime(owt)                                   # touched: inside a 600 s grace the next pass skips it
        n2 = opass(600)
        n3 = opass(0)
        ok("ORPHAN ONCE: a worktree with no board entry is told on the first pass, not again after a pass that "
           "skipped it, nor on the pass after that, at --repeat 0", (n1, n2, n3) == (1, 1, 1))
        shutil.rmtree(owt); opass(0); os.makedirs(owt)
        ok("…and once its directory has gone, a worktree made again at that path is told again", opass(0) == 2)
    # (b1) OWNER-HELD (brief C6): "a row that is waiting on an open owner ask, held for his yes, or noted as parked on
    # purpose wakes its seat once and not every day. When a wake does fire, it says an owner ask is already pending."
    T = now()
    ok("OWNER-HELD: an open owner ask naming the row's slug holds it, and the line says an ask is already pending",
       owner_held("chip-flow", "sensor-counted-rebuild", [], [("", "🔒 <@U1> chip-flow/sensor-counted-rebuild: confirm the release?")])
       == "an owner ask is already pending")
    ok("…while an ask naming a LONGER slug that contains it does not, nor does a row with no ask and plain notes",
       owner_held("chip-flow", "sensor", [], [("", "about sensor-counted-rebuild")]) == "" and owner_held("r", "x-y", ["re-dispatched"], []) == "")
    ok("…and the repo counts: the same slug under another repo is not held, the same repo is",
       owner_held("other-repo", "sensor-counted-rebuild", [], [("", "🔒 <@U1> chip-flow/sensor-counted-rebuild: confirm?")]) == ""
       and owner_held("chip-flow", "sensor-counted-rebuild", [], [("", "chip-flow sensor-counted-rebuild: ok?")]) != ""
       and owner_held("chip", "sensor-counted-rebuild", [], [("", "chip-flow/sensor-counted-rebuild: ok?")]) == "")
    ok("…and the ask's chat counts: no repo in the text, the ask in this repo's channel holds; in another repo's channel it does not",
       owner_held("chip-flow", "sensor-counted-rebuild", [], [("C9", "release ok? sensor-counted-rebuild")], {"C9"}) != ""
       and owner_held("chip-flow", "sensor-counted-rebuild", [], [("C7", "release ok? sensor-counted-rebuild")], {"C9"}) == ""
       and owner_held("chip-flow", "sensor-counted-rebuild", [], [("C9", "release ok? sensor")], {"C9"}) == ""
       and owner_held("chip-flow", "sensor-counted-rebuild", [], [("", "release ok? sensor-counted-rebuild")], {"C9"}) == "")
    tc = tempfile.mkdtemp(prefix="cc-reconcile-chans-")
    try:
        json.dump({"chip-flow": "C9", "chip-flow-updates": "C8", "chip-flow@x": "C6", "chip": "C1", "chip-flows": "C2", "chip-flow--sub": "C5", "chip-flow--sub-updates": "C4"},
                  open(f"{tc}/channels.json", "w"))
        ok("…repo_channels takes `<repo>`, `<repo>-…` and `<repo>@…` keys but not `<repo>--…` ones, and an unreadable file is none",
           repo_channels("chip-flow", f"{tc}/channels.json") == {"C9", "C8", "C6"}
           and repo_channels("chip-flow", f"{tc}/none.json") == set())
        ok("…and a key goes to the longest repo it starts with: `chip` keeps `chip-flows` but never takes `chip-flow`'s channels, nor a `chip-flow--` repo's",
           repo_channels("chip", f"{tc}/channels.json", ["chip", "chip-flow"]) == {"C1", "C2"}
           and repo_channels("chip-flow", f"{tc}/channels.json", ["chip", "chip-flow"]) == {"C9", "C8", "C6"}
           and owner_held("chip", "sensor-counted-rebuild", [], [("C9", "release ok? sensor-counted-rebuild")],
                          repo_channels("chip", f"{tc}/channels.json", ["chip", "chip-flow"])) == "")
    finally:
        shutil.rmtree(tc, ignore_errors=True)
    ok("…a note that parks the row on purpose holds it (any of the last three notes), an older one does not",
       owner_held("r", "boxtown-grok", ["loop exit 3", "Parked on purpose: the key arrives later."], []) != ""
       and owner_held("r", "aiportfolio-404", ["Superseded: it comes back when the owner says yes."], []) != ""
       and owner_held("r", "r", ["Parked on purpose.", "a", "b", "c"], []) == "")
    tq = tempfile.mkdtemp(prefix="cc-reconcile-asks-")
    try:
        json.dump({"C1:1": {"text": "asks about row-a-b", "at": T - 3600},
                   "C1:2": {"text": "asks about row-c-d", "at": T - 8 * 86400},
                   "_C1:3": {"text": "row-e-f", "at": T}}, open(f"{tq}/owner-asks.json", "w"))
        ok("OWNER-HELD: open_asks reads the unanswered asks inside a week — not one older, not an answer's \"_\" key",
           open_asks(f"{tq}/owner-asks.json", T) == [("", "asks about row-a-b")])
        ok("…and an unreadable table is no asks, not an error", open_asks(f"{tq}/none.json", T) == [])
    finally:
        shutil.rmtree(tq, ignore_errors=True)
    tw = tempfile.mkdtemp(prefix="cc-reconcile-ownerwake-")
    _oa = OWNER_ASKS
    try:
        scratch(tw, dict(NOOP, **{"cc-brief": ":",          # `cc-brief ready` on blocked rows alone prints nothing
                                  "cc": f'echo "start $1" >> {tw}/cc.log', "cc-msg": f'echo "msg $1" >> {tw}/cc.log'}))
        os.environ["CC_WAKE"] = "on"
        globals().update(procs=lambda: (set(), set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}),
                         OWNER_ASKS=f"{tw}/owner-asks.json")
        json.dump({"C1:1": {"text": "🔒 confirm the release for wask/ask-row-x?", "at": now()}}, open(f"{tw}/owner-asks.json", "w"))
        for r, row in (("wpark", {"status": "blocked", "updated": old,
                                  "notes": [{"msg": "Parked on purpose: the key arrives with #1022."}]}),
                       ("wask", {"status": "blocked", "updated": old}),
                       ("wplain", {"status": "blocked", "updated": old, "notes": [{"msg": "loop exit 3"}]})):
            os.makedirs(f"{tw}/dev/{r}")
            k = "ask-row-x" if r == "wask" else f"{r}-row"
            json.dump({"repo": r, "tracks": {k: row}}, open(f"{tw}/.cc/boards/{r}.json", "w"))

        def woke(r):
            return sum(ln == f"start {r}" for ln in open(f"{tw}/cc.log").read().splitlines()) if os.path.exists(f"{tw}/cc.log") else 0
        quietly(tick, {}, True)
        plog = open(f"{tw}/.cc/state/pulse.log").read()
        ok("OWNER-HELD WAKE: the first time, each stopped row wakes its seat — parked, asked and plain alike",
           (woke("wpark"), woke("wask"), woke("wplain")) == (1, 1, 1))
        ok("…and that wake says the parked row is parked and the asked row's owner ask is already pending",
           "wpark-row: parked on purpose" in plog and "ask-row-x: an owner ask is already pending" in plog
           and "wplain-row:" not in plog)
        for r in ("wpark", "wask", "wplain"):           # a day and an hour later, nothing changed
            os.utime(f"{tw}/.cc/state/{r}/pulse.look", (now() - 25 * 3600,) * 2)
        quietly(tick, {}, True)
        plog = open(f"{tw}/.cc/state/pulse.log").read()
        ok("OWNER-HELD WAKE: past QUIET_H the parked and the asked rows wake nobody again, and pulse.log says why",
           (woke("wpark"), woke("wask")) == (1, 1) and "wpark skip" in plog and "wait on the owner" in plog)
        ok("…while the plain stopped row is re-woken after QUIET_H, as before", woke("wplain") == 2)
    finally:
        restore(); globals().update(OWNER_ASKS=_oa); shutil.rmtree(tw, ignore_errors=True)
    # (b2) a LIVE seat: an idle pane is typed one cc-msg line, never a second session; a pane mid-turn is typed nothing
    ti = tempfile.mkdtemp(prefix="cc-reconcile-idle-")
    try:
        scratch(ti, dict(NOOP, **{"cc-brief": 'echo "$2: 1 of 1 queued rows could start now: q1"',
                                  "cc": f'echo "start $1" >> {ti}/cc.log', "cc-msg": f'echo "msg $1" >> {ti}/cc.log',
                                  "tmux": f'[ "$1" = capture-pane ] && cat {ti}/pane'}))
        os.makedirs(f"{ti}/dev/wr")
        os.environ["CC_WAKE"] = "on"
        globals().update(procs=lambda: (set(), set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}),
                         windows=lambda: {"wr": ("@7", "4242")}, live_session=lambda pid: pid == "4242")

        def typed():
            return open(f"{ti}/cc.log").read().splitlines() if os.path.exists(f"{ti}/cc.log") else []
        json.dump({"repo": "wr", "tracks": {"q1": {"status": "queued", "updated": old}}}, open(f"{ti}/.cc/boards/wr.json", "w"))
        open(f"{ti}/pane", "w").write("❯ \n  ? for shortcuts\n")
        quietly(tick, {}, True)
        ok("WAKE, LIVE SEAT: an idle pane in a live window is typed exactly one cc-msg line and no second session is started",
           typed() == ["msg wr"] and "wr tick — live and idle" in open(f"{ti}/.cc/state/pulse.log").read())
        json.dump({"repo": "wr", "tracks": {"q1": {"status": "blocked", "updated": old}}}, open(f"{ti}/.cc/boards/wr.json", "w"))
        open(f"{ti}/pane", "w").write("✻ Working… (12s · esc to interrupt)\n")
        quietly(tick, {}, True)
        ok("…while the same seat mid-turn (`esc to interrupt`) is typed nothing for a new state, and pulse.log says so",
           typed() == ["msg wr"] and "wr skip — mid-turn" in open(f"{ti}/.cc/state/pulse.log").read())
    finally:
        restore(); shutil.rmtree(ti, ignore_errors=True)
    # (b3) a seat MID-HANDOFF: before the cutover nothing is typed; once the record calls the successor live, the
    # successor (which holds `<repo>` from then) is woken like any live seat, drain or no drain
    for live, want, what in (("predecessor", [], "skip — mid-handoff"), ("successor", ["msg wr"], "tick — live and idle")):
        th = tempfile.mkdtemp(prefix="cc-reconcile-handoff-")
        try:
            scratch(th, dict(NOOP, **{"cc-brief": 'echo "$2: 1 of 1 queued rows could start now: q1"',
                                      "cc-handoff": f'echo "wr overlap live={live}"; exit 0',
                                      "cc": f'echo "start $1" >> {th}/cc.log', "cc-msg": f'echo "msg $1" >> {th}/cc.log',
                                      "tmux": f'[ "$1" = capture-pane ] && cat {th}/pane'}))
            os.makedirs(f"{th}/dev/wr")
            os.environ["CC_WAKE"] = "on"
            globals().update(procs=lambda: (set(), set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}),
                             windows=lambda: {"wr": ("@7", "4242")}, live_session=lambda pid: pid == "4242")
            json.dump({"repo": "wr", "tracks": {"q1": {"status": "queued", "updated": old}}}, open(f"{th}/.cc/boards/wr.json", "w"))
            open(f"{th}/pane", "w").write("❯ \n  ? for shortcuts\n")
            quietly(tick, {}, True)
            got = open(f"{th}/cc.log").read().splitlines() if os.path.exists(f"{th}/cc.log") else []
            ok(f"WAKE, MID-HANDOFF with the {live} live: " + ("nothing is typed at a seat that is being replaced"
               if not want else "the successor is woken for the new row, without waiting out the drain"),
               got == want and f"wr {what}" in open(f"{th}/.cc/state/pulse.log").read())
        finally:
            restore(); shutil.rmtree(th, ignore_errors=True)
    # (b3) ONE LOOK PER HALF: what `cc-brief ready` says about the queued rows is not news about a row that has been
    # blocked all along. Keyed together, the queued verdict moving re-announced the blocked row every ~20 min.
    tc = tempfile.mkdtemp(prefix="cc-reconcile-look-")
    try:
        scratch(tc, dict(NOOP, **{"cc-brief": f"cat {tc}/ready", "cc": f'echo "start $1" >> {tc}/cc.log'}))
        os.makedirs(f"{tc}/dev/wr")
        os.environ["CC_WAKE"] = "on"
        globals().update(procs=lambda: (set(), set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}))

        def rows(**tracks):
            json.dump({"repo": "wr", "tracks": {k: {"status": v, "updated": old} for k, v in tracks.items()}},
                      open(f"{tc}/.cc/boards/wr.json", "w"))

        def woke():
            return open(f"{tc}/cc.log").read().splitlines() if os.path.exists(f"{tc}/cc.log") else []
        rows(b1="blocked", q1="queued")
        open(f"{tc}/ready", "w").write("wr: 1 of 1 queued rows could start now\n  a builder each: q1\n")
        quietly(tick, {}, True)
        ok("WAKE, ONE LOOK PER HALF: a blocked row beside a startable queued one wakes the seat", woke() == ["start wr"])
        open(f"{tc}/ready", "w").write("")              # cc-brief ready prints nothing when no queued row is free
        quietly(tick, {}, True)
        ok("…and the queued row's verdict going away is not a new state for the blocked one: no second wake",
           woke() == ["start wr"] and "for this same state" in open(f"{tc}/.cc/state/pulse.log").read())
        rows(b1="blocked", q1="running")                # …nor is the due list itself: q1 is not due at all now
        quietly(tick, {}, True)
        ok("…nor is the queued row leaving the due list", woke() == ["start wr"])
        rows(b1="blocked", q1="running", b2="blocked")
        quietly(tick, {}, True)
        ok("…while a second row stopping IS a new state, and wakes the seat once more", woke() == ["start wr"] * 2)
        rows(b1="blocked", q1="running", b2="blocked", q5="queued", q6="queued")
        quietly(tick, {}, True)                         # 09-27: the due list grew by a row each tick, nothing could start
        ok("…an UNCHANGED stopped set beside new queued rows that cannot start is not a wake (09-27: four in an hour)",
           woke() == ["start wr"] * 2 and "for this same state" in open(f"{tc}/.cc/state/pulse.log").read().splitlines()[-1])
        rows(b2="blocked", q5="queued", q6="queued")
        quietly(tick, {}, True)
        rows(b1="blocked", b2="blocked", q5="queued", q6="queued")
        quietly(tick, {}, True)
        ok("…nor is the set shrinking, or flickering back to the set the seat was last woken for", woke() == ["start wr"] * 2)
        open(f"{tc}/ready", "w").write("wr: 1 of 2 queued rows could start now — 1 group shares a file\n"
                                       "  one builder for a.txt, b.txt: q5\n")
        quietly(tick, {}, True)
        ok("…while a queued row cc-brief now names as startable IS news, and wakes it", woke() == ["start wr"] * 3)
        quietly(tick, {}, True)
        ok("…once", woke() == ["start wr"] * 3)
    finally:
        restore(); shutil.rmtree(tc, ignore_errors=True)
    # (b5) A FALSE NAG IS ONE A LANDING WAS LIVE AT. Each PR stands on its own work record and queue-log lines: 39 of
    # the 40 work-record records by 10-02 were nags sent after cc-land had already failed the PR, and 32 of the 51
    # window records sat in a window the lander since #771 never closes with a `done` line.
    tn = tempfile.mkdtemp(prefix="cc-reconcile-falsenag-")
    _home, _rf = HOME, record_failure
    try:
        os.makedirs(f"{tn}/.cc/state/land/root")
        got, nag = [], now() - 3600

        def iso(t):
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))

        def nagged(n, first=None, touched=None, log=()):
            if first:
                json.dump({"repo": "fr", "pr": n, "first": iso(first), "at": iso(touched or first)},
                          open(f"{tn}/.cc/state/land/root/fr-{n}.json", "w"))
            with open(f"{tn}/.cc/state/land/queue.log", "a") as f:
                f.writelines(f"{iso(t)}\t{ev.replace('PR', f'fr#{n}')}\n" for t, ev in log)
            del got[:]
            false_nags({f"offered fr/t{n} https://example.invalid/pr/{n}": nag}, {}, net=False)
            return [o for o in got if f"PR #{n} " in o]
        globals().update(HOME=tn, record_failure=lambda scope, kind, observed, ts, **k: got.append(observed))
        live = nagged(1, first=nag - 600, touched=nag - 300)
        ok("FALSE NAGS: a work record from a landing live at the nag — first before it, touched minutes before it — "
           "makes the nag false: one record", len(live) == 1 and "work record says it had the PR" in live[0])
        ok("…while a STALE touch, last written more than BETWEEN_ROUNDS before the nag, is history: nothing written",
           nagged(2, first=nag - 3 * 3600, touched=nag - BETWEEN_ROUNDS - 60) == [])
        ok("…and a landing that ended in a TERMINAL failure before the nag (`done rc=1`) leaves the nag right: nothing "
           "written, however fresh the record's touch",
           nagged(3, first=nag - 7200, touched=nag - 600,
                  log=[(nag - 7200, "queued PR who=-"), (nag - 900, "done PR rc=1 [fr] PR #3: NOT merged")]) == [])
        ok("…nor does the new lander's own end of one (`stage PR handback`, no `done` line) leave its window open to now",
           nagged(4, first=nag - 7200, touched=nag - 600,
                  log=[(nag - 7200, "queued PR who=-"), (nag - 5400, "stage PR gate gate=x ok=no"),
                       (nag - 5400, "stage PR handback")]) == [])
        back = nagged(5, log=[(nag - 7200, "queued PR who=-"), (nag - 5400, "stage PR handback"),
                              (nag - 600, "stage PR lane")])
        ok("…while a PR the lander took up again after a handback IS in its hands at the nag: one record, from the window",
           len(back) == 1 and "queue log shows a landing" in back[0])
        for i, w in enumerate(LAND_ENDS):               # a terminal word that ends the line: no trailing metadata
            ok(f"…and a bare `{w} PR` with nothing after the PR token closes its window too: a later nag is right",
               nagged(10 + i, first=nag - 7200, touched=nag - 600,
                      log=[(nag - 7200, "queued PR who=-"), (nag - 1800, f"{w} PR")]) == [])
        ok("…the reviewer's input — `queued fr#7 who=-` then `handed fr#7`, the nag ten minutes after — is not a landing",
           nagged(7, first=nag - 1200, touched=nag - 600,
                  log=[(nag - 1200, "queued PR who=-"), (nag - 600, "handed PR")]) == [])
    finally:
        globals().update(HOME=_home, record_failure=_rf); shutil.rmtree(tn, ignore_errors=True)
    # (b4) the daily line's hour and date are LA's, whatever zone the host is in
    tz = tempfile.mkdtemp(prefix="cc-reconcile-digest-at-")
    try:
        scratch(tz, NOOP)

        def posts():
            return [ln for ln in open(f"{tz}/notify.log").read().splitlines() if ln.startswith("digest\t")] \
                if os.path.exists(f"{tz}/notify.log") else []
        globals().update(procs=lambda: (set(), set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}),
                         now=lambda: calendar.timegm((2026, 9, 15, 17, 30, 0)))      # 10:30 PDT: past 11:00 in UTC and in EDT
        quietly(tick, {}, True)
        ok("DIGEST AT: 17:30 UTC is 10:30 in Los Angeles, so no stamp is written",
           not os.path.exists(f"{tz}/.cc/state/digest.stamp"))
        globals().update(now=lambda: calendar.timegm((2026, 9, 15, 18, 5, 0)))       # 11:05 PDT
        quietly(tick, {}, True)
        ok("…18:05 UTC is 11:05 there: stamped with LA's date, and NOT posted — a debugging engineer reads the "
           "boards, not the control channel, for this; `digest --notify` still posts it by hand",
           posts() == [] and open(f"{tz}/.cc/state/digest.stamp").read().strip() == "2026-09-15")
        globals().update(now=lambda: calendar.timegm((2026, 9, 16, 5, 0, 0)))        # 22:00 PDT, still the 15th there
        quietly(tick, {}, True)
        ok("…and 05:00 UTC the next day is still the 15th in LA: the stamp does not move",
           posts() == [] and open(f"{tz}/.cc/state/digest.stamp").read().strip() == "2026-09-15")
    finally:
        restore(); shutil.rmtree(tz, ignore_errors=True)
    # (c) sweep: a terminal track older than 48 h goes; a dirty one is reported and kept
    tc = tempfile.mkdtemp(prefix="cc-reconcile-sweep-")
    try:
        scratch(tc, dict(NOOP, cc=f'echo "$*" >> {tc}/cc.log'))
        json.dump({"repo": "sw", "tracks": {"gone": {"status": "merged", "updated": old},
                                            "dirty": {"status": "merged", "updated": old},
                                            "young": {"status": "merged", "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                                            "open": {"status": "review", "updated": old}}},
                  open(f"{tc}/.cc/boards/sw.json", "w"))
        for t in ("gone", "dirty", "young", "open"):
            os.makedirs(f"{tc}/.cc/worktrees/sw/{t}")
        subprocess.run(["git", "-C", f"{tc}/.cc/worktrees/sw/dirty", "init", "-q"], capture_output=True)
        open(f"{tc}/.cc/worktrees/sw/dirty/wip.txt", "w").write("uncommitted\n")
        globals().update(procs=lambda: (set(), set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}))
        out = quietly(sweep_cmd, ["sw"])
        did = open(f"{tc}/cc.log").read().splitlines() if os.path.exists(f"{tc}/cc.log") else []
        ok("SWEEP: a merged track older than 48 h with a clean worktree is removed with `cc rm`, and nothing else is",
           did == ["rm sw gone"])
        ok("…the dirty one is reported, not removed, and says why", "sw/dirty — uncommitted changes" in out)
        ok("…a merged track inside 48 h and a `review` row are not candidates at all",
           "sw/young" not in out and "sw/open" not in out)
        ok("…and --dry removes nothing and says what it would", "would rm sw/gone" in quietly(sweep_cmd, ["sw", "--dry"]) and did == ["rm sw gone"])
    finally:
        restore(); shutil.rmtree(tc, ignore_errors=True)
    # (c2) sweep rule 2: a merged row's branch goes once, at the merge; a tip pushed after it, or a session row's, stays
    tb = tempfile.mkdtemp(prefix="cc-reconcile-branch-")
    try:
        def git(*a):
            return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout.strip()
        git("init", "-q", "--bare", f"{tb}/origin.git")
        git("init", "-q", f"{tb}/dev/br")
        git("-C", f"{tb}/dev/br", "remote", "add", "origin", f"{tb}/origin.git")
        heads = {}
        for i, t in enumerate(("once", "later", "seat")):
            git("-C", f"{tb}/dev/br", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", t)
            heads[t] = git("-C", f"{tb}/dev/br", "rev-parse", "HEAD")
            git("-C", f"{tb}/dev/br", "push", "-q", "origin", f"HEAD:refs/heads/track/{t}")
        # `later` merged at its first tip, then the row's worker pushed again: origin's tip is not the merged head
        git("-C", f"{tb}/dev/br", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "after")
        git("-C", f"{tb}/dev/br", "push", "-q", "origin", "HEAD:refs/heads/track/later")
        prs = [{"number": n, "state": "MERGED", "headRefName": f"track/{t}", "headRefOid": heads[t],
                "mergedAt": "2026-09-20T00:00:00Z"} for n, t in enumerate(("once", "later", "seat"), 1)]
        scratch(tb, dict(NOOP, gh=f"cat {tb}/prs.json"))
        json.dump(prs, open(f"{tb}/prs.json", "w"))
        young = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        json.dump({"repo": "br", "tracks": {"once": {"status": "merged", "updated": young},
                                            "later": {"status": "merged", "updated": young},
                                            "seat": {"status": "merged", "kind": "session", "updated": young}}},
                  open(f"{tb}/.cc/boards/br.json", "w"))
        globals().update(procs=lambda: (set(), set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}))
        on_origin = lambda: sorted(ln.split("refs/heads/")[-1] for ln in
                                   git("ls-remote", "--heads", f"{tb}/origin.git").splitlines())
        out = quietly(sweep_cmd, ["br"])
        ok("SWEEP rule 2: a one-shot row whose PR merged at origin's tip has its branch deleted",
           "track/once" not in on_origin() and "delete origin/track/once — its PR is merged" in out)
        ok("…but a tip pushed after the merge is kept and reported, not deleted on every pass (the lessons rescues)",
           "track/later" in on_origin() and "origin/track/later — its PR merged, but origin's tip" in out)
        ok("…and a session row's branch is never touched, merged PR and matching tip or not: a seat outlives each PR",
           "track/seat" in on_origin() and "track/seat" not in out)
        out = quietly(sweep_cmd, ["br"])
        ok("…and the next pass deletes nothing more: the delete ran once, at the merge",
           on_origin() == ["track/later", "track/seat"] and "track/seat" not in out)
    finally:
        restore(); shutil.rmtree(tb, ignore_errors=True)
    # (c3) A MEMBER WORKSPACE'S CHECKOUT: the sweep takes no destructive step in it — no `cc rm` (rule 1), no push
    # --delete (rule 2), no worktree removal (rule 9) — and hands each to the member's own seat instead. Two attacks ride
    # on it, and both went through at 5560f0c2: a refs/remotes/origin the member links at another repo's refs/heads (the
    # owner's push --delete then deleted that repo's branch), and a .claude the member swaps for a link between the
    # rule-9 check and its rmtree (which then removed a directory outside the workspace).
    tm2 = tempfile.mkdtemp(prefix="cc-reconcile-member-")
    _home = HOME
    try:
        def git(*a):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], capture_output=True,
                                  text=True, timeout=30)
        mb, vic, vdir = f"{tm2}/dev/mb", f"{tm2}/dev/vic", f"{tm2}/victim"
        git("init", "-q", "--bare", f"{tm2}/origin.git")
        git("init", "-q", "-b", "main", mb); git("-C", mb, "remote", "add", "origin", f"{tm2}/origin.git")
        git("-C", mb, "commit", "-q", "--allow-empty", "-m", "c0"); git("-C", mb, "push", "-q", "origin", "main")
        git("-C", mb, "push", "-q", "origin", "HEAD:refs/heads/track/once")
        tip = git("-C", mb, "rev-parse", "HEAD").stdout.strip()
        git("init", "-q", "-b", "main", vic); git("-C", vic, "commit", "-q", "--allow-empty", "-m", "v0")
        git("-C", vic, "branch", "track/once")
        shutil.rmtree(f"{mb}/.git/refs/remotes/origin/track", ignore_errors=True)    # origin/main stays a plain ref
        os.symlink(f"{vic}/.git/refs/heads/track", f"{mb}/.git/refs/remotes/origin/track")   # the planted refs link
        os.makedirs(f"{mb}/.cc"); open(f"{mb}/.cc/member-workspace", "w").close()
        sub = f"{mb}/{AGENT_WT}/sub"
        git("-C", mb, "worktree", "add", "-q", "--detach", sub)
        os.makedirs(f"{vdir}/worktrees/sub"); open(f"{vdir}/worktrees/sub/keep", "w").write("the owner's\n")
        for root, ds, fs in os.walk(f"{mb}/.claude"):                                # idle past rule 9's 4 h
            for x in ds + fs + [""]:
                os.utime(os.path.join(root, x), (0, 0), follow_symlinks=False)
        scratch(tm2, dict(NOOP, gh=f"cat {tm2}/prs.json", cc=f'echo "$*" >> {tm2}/cc.log',
                          **{"cc-msg": f'echo "$*" >> {tm2}/msg.log'}))
        json.dump([{"number": 1, "state": "MERGED", "headRefName": "track/once", "headRefOid": tip,
                    "mergedAt": "2026-09-20T00:00:00Z"}], open(f"{tm2}/prs.json", "w"))
        young = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        json.dump({"repo": "mb", "tracks": {"once": {"status": "merged", "updated": young},
                                            "gone": {"status": "merged", "updated": old}}},
                  open(f"{tm2}/.cc/boards/mb.json", "w"))
        os.makedirs(f"{tm2}/.cc/worktrees/mb/gone")
        globals().update(procs=lambda: (set(), set(), set(), {}, {}), tmux_live=lambda p, s=(): (set(), {}, {}))
        _dirty, calls = dirty, []

        def swapping(repo, wt):                          # the member's move, between rule 9's check and its rmtree
            calls.append(wt)
            if len([c for c in calls if c == sub]) == 2 and not os.path.islink(f"{mb}/.claude"):
                os.rename(f"{mb}/.claude", f"{mb}/.claude-was"); os.symlink(vdir, f"{mb}/.claude")
            return _dirty(repo, wt)
        globals().update(dirty=swapping)
        try:
            out = quietly(sweep_cmd, ["mb"])
        finally:
            globals().update(dirty=_dirty)
        if os.path.islink(f"{mb}/.claude"):
            os.unlink(f"{mb}/.claude"); os.rename(f"{mb}/.claude-was", f"{mb}/.claude")
        refs = lambda d: git("-C", d, "for-each-ref", "--format=%(refname)").stdout.split()
        msgs = lambda: open(f"{tm2}/msg.log").read().splitlines() if os.path.exists(f"{tm2}/msg.log") else []
        stale = open(f"{tm2}/.cc/state/mb/stale.md").read() if os.path.exists(f"{tm2}/.cc/state/mb/stale.md") else ""
        ok("MEMBER CHECKOUT: a branch whose PR merged at origin's tip is not deleted, and the member's refs link at "
           "another repo's refs/heads deletes nothing there", "refs/heads/track/once" in refs(f"{tm2}/origin.git")
           and "refs/heads/track/once" in refs(vic) and "stale, left to its own seat: would delete" in out)
        ok("…an idle subagent worktree is not removed, and a .claude swapped for a link mid-sweep removes nothing "
           "outside the workspace", os.path.exists(f"{vdir}/worktrees/sub/keep") and os.path.isdir(sub))
        ok("…a merged row past 48 h is not `cc rm`ed: its worktree is a worktree of the member's checkout",
           not os.path.exists(f"{tm2}/cc.log") and os.path.isdir(f"{tm2}/.cc/worktrees/mb/gone"))
        ok("…and all three go to the member's own seat: listed in its state dir's stale.md, with one cc-msg line",
           all(x in stale for x in ("delete origin/track/once", f"rm worktree {sub}", "rm mb/gone"))
           and len(msgs()) == 1 and msgs()[0].startswith("mb sweep: 3 stale items"))
        quietly(sweep_cmd, ["mb"])
        ok("…the next pass with the same list sends nothing more", len(msgs()) == 1)
        sd = git_shadow(mb)
        ok("…and a read's shadow holds COPIES of the refs, the planted link skipped, never followed",
           not os.path.islink(f"{sd}/refs") and not os.path.lexists(f"{sd}/refs/remotes/origin/track")
           and os.path.isfile(f"{sd}/refs/remotes/origin/main") and not os.path.islink(f"{sd}/objects"))
        os.remove(f"{mb}/.cc/member-workspace"); os.makedirs(f"{tm2}/.cc/members/mb")
        globals().update(HOME=tm2)
        ok("MEMBER CHECKOUT: the host-side ~/.cc/members/<repo> marks a member workspace when the checkout's own marker "
           "is gone (a member can delete that one), and a repo with neither is the owner's",
           member_ws("mb") and not member_ws("vic"))
    finally:
        globals().update(HOME=_home); restore(); shutil.rmtree(tm2, ignore_errors=True)
    ok("branch_verdict: a MERGED PR with no head read deletes nothing",
       branch_verdict({"board": "merged", "pr": "MERGED", "head": "", "tip": "", "dirty": False})[0] == "report")
    # (d) digest: a waiting row's question is listed; a merged-and-quiet row is not there at all
    td = tempfile.mkdtemp(prefix="cc-reconcile-digest-")
    try:
        scratch(td, dict(NOOP, **{"cc-config": "echo fixturebox"}))
        json.dump({"repo": "dg", "tracks": {"ask": {"status": "waiting", "title": "the importer", "updated": old},
                                            "quiet": {"status": "merged", "title": "a quiet thing", "updated": old},
                                            "dead": {"status": "blocked", "title": "the nightly export", "updated": old,
                                                     "notes": [{"ts": "x", "msg": "ran out of disk"}]}}},
                  open(f"{td}/.cc/boards/dg.json", "w"))
        dtext = digest_text({"dg/ask": {"state": "waiting", "waiting_on": "person", "why": "skip the bad row or stop?"}})
        ok("DIGEST: what waits on him leads, carrying the row's question", "*Waiting on you*" in dtext and "• dg: skip the bad row or stop?" in dtext)
        ok("…a merged row that went quiet is not in the report at all", "quiet thing" not in dtext)
        ok("…the first line carries the counts, and a stopped row says what broke",
           dtext.startswith("*fixturebox* today: 1 waiting on you, 1 stopped.") and "• dg, the nightly export: ran out of disk" in dtext)
        ok("…with no usable snapshot the board's own word stands: the waiting row is named by its title, no colon trailing",
           "• dg: the importer" in digest_text({}) and "the importer:" not in digest_text({}))
        open(f"{td}/.cc/state/reconcile.json", "w").write("not json")
        ok("…and `digest` itself prints from the board over a corrupt snapshot file", "the importer" in quietly(digest_cmd, []))
        hold = {"dg/dead": {"state": "blocked", "waiting_on": "clock", "why": ""}}
        ok("…a row the usage limit holds is named once at the top and is neither his nor stopped",
           "⏳ Held by the usage limit: the nightly export." in digest_text(hold) and "1 waiting on you, 1 held." in digest_text(hold))
        # the failure ledger's line: cc-failures owns the numbers, so a stub answers `metrics` and `eligible` from
        # files, and the case asserts the line IS those numbers — three kinds named, the rest counted; an empty
        # ledger, or no cc-failures at all, is no line and the report still prints.
        open(f"{td}/stubs/cc-failures", "w").write(f'#!/bin/sh\ncase "$1" in metrics) cat "{td}/fmetrics";; eligible) cat "{td}/feligible";; esac\n')
        os.chmod(f"{td}/stubs/cc-failures", 0o755)
        open(f"{td}/fmetrics", "w").write("records: 123 (120 confirmed)  clusters: 76  eligible: 4\nrecording delay (filed - happened, min): median 0\n")
        open(f"{td}/feligible", "w").write(
            "c-1\tdemo\tguard-policy/permitted-text-refused\t11 episodes in 14d\t11 episode(s)\t2026-09-08T17:21..2026-09-11T19:11\tunclaimed 3d 6h\n"
            "c-2\tdemo\tnotification/false-action-needed\t9 episodes in 14d\t9 episode(s)\t2026-09-09T02:31..2026-09-11T16:45\tclaimed 2h ago i-ab12cd34\n"
            "c-3\tdemo\tfailure-detection/person-first\tcritical: person-first\t3 episode(s)\t2026-09-10T16:57..2026-09-11T03:30\tunclaimed 1d 9h\n"
            "c-4\tdemo\tboard-row/x\t3 episodes in 14d\t3 episode(s)\t2026-09-08T06:33..2026-09-11T17:20\tunclaimed 8h 59m\n")
        ok("…the failure ledger is one line: what it holds and what crossed the rule, three kinds named with episodes and claim word, the rest counted",
           "🧾 The failure ledger holds 123 records in 76 groups. 4 happened often enough to need a look: permitted text refused (11 times, "
           "nobody on it for 3 days); false action needed (9 times, someone has taken it); person first (3 times, nobody on it for 33 hours); and 1 more."
           in digest_text({}))
        open(f"{td}/fmetrics", "w").write("records: 5 (5 confirmed)  clusters: 2  eligible: 0\n"); open(f"{td}/feligible", "w").close()
        ok("…a ledger with records and nothing eligible says so", "🧾 The failure ledger holds 5 records in 2 groups, and none needs a look." in digest_text({}))
        # what the perms seat granted from his goals is told after in the digest (cc-infer digest), never a card:
        # the full report carries its block, the phone one names it; a ledger with nothing in the window adds nothing
        open(f"{td}/stubs/cc-infer", "w").write(f'#!/bin/sh\ncat "{td}/granted"\n')
        os.chmod(f"{td}/stubs/cc-infer", 0o755)
        open(f"{td}/granted", "w").write("*Granted from your goals* (told after; nothing to tap)\n• serve the demo site (from goals.md; undo: unroute; watched)\n")
        ok("…a grant from his goals is in the report, told after", "• serve the demo site (from goals.md; undo: unroute; watched)" in digest_text({})
           and "what was granted from your goals" in digest_text({}, phone=True))
        open(f"{td}/granted", "w").close()
        ok("…and no grant in the window is no block and no mention", "Granted from your goals" not in digest_text({})
           and "granted from your goals" not in digest_text({}, phone=True))
        open(f"{td}/fmetrics", "w").write("records: 0 (0 confirmed)  clusters: 0  eligible: 0\n")
        ok("…an empty ledger is no line at all", "🧾" not in digest_text({}))
        ok("…no cc-collect snapshot is no agenticness section", "How far it ran without you" not in digest_text({}))
        open(f"{td}/stubs/cc-agenticness", "w").write("#!/bin/sh\necho '• dg: 2 landed (1 never waited on a person)'\n")
        os.chmod(f"{td}/stubs/cc-agenticness", 0o755)
        ok("…while a snapshot's lines come in under their own heading in the whole report, and not in the phone one",
           "*How far it ran without you*\n• dg: 2 landed (1 never waited on a person)" in digest_text({})
           and "How far it ran" not in digest_text({}, phone=True))
        os.remove(f"{td}/stubs/cc-agenticness")
        open(f"{td}/stubs/cc-failures", "w").write("#!/bin/sh\nexit 1\n")   # a box whose cc-failures cannot answer
        dnone = digest_text({})
        ok("…and a box whose cc-failures cannot answer gets no line either, and the report still prints", "Failures:" not in dnone and dnone.startswith("*fixturebox* today"))
        quietly(digest_cmd, ["--notify"])
        ok("…and --notify posts once, to the log under a harness", open(f"{td}/notify.log").read().startswith("digest\t*fixturebox* today"))
        _shD, _loD, argvD = globals()["sh"], os.environ.pop("CC_NOTIFY_LOG_ONLY", None), []
        try:
            globals()["sh"] = lambda *cmd, **kw: argvD.append(cmd[1:])
            digest_post("*fixturebox* today: nothing moved. $0 spent.")
        finally:
            globals()["sh"] = _shD
            if _loD is not None:
                os.environ["CC_NOTIFY_LOG_ONLY"] = _loD
        ok("…and off the harness digest_post posts --major --keep, so cc-slack's engagement gate never folds the digest "
           "into itself in a control repo he has been away from: " + repr(argvD),
           [a[:3] for a in argvD if a[:1] == ("post",)] == [("post", "--major", "--keep")])
    finally:
        restore(); shutil.rmtree(td, ignore_errors=True)
    # (e) digest: a queued row inside a live bundle is being written, so it counts under the bundle and not as queued
    te = tempfile.mkdtemp(prefix="cc-reconcile-bundle-")
    try:
        scratch(te, dict(NOOP, **{"cc-config": "echo fixturebox"}))
        def bd(pack):
            json.dump({"repo": "bd", "tracks": {"pack": {"status": pack, "title": "bundle: two rows on the importer", "updated": old},
                                                "inpack": {"status": "queued", "title": "a row inside that bundle", "bundle": "pack", "updated": old},
                                                "loose": {"status": "queued", "title": "a row in no bundle", "updated": old}}},
                      open(f"{te}/.cc/boards/bd.json", "w"))
        bd("running"); btext = digest_text({})
        ok("DIGEST: a queued row inside a LIVE bundle is counted in the bundle, not as queued — the bundle row is what is moving",
           btext.startswith("*fixturebox* today: 1 moving.") and "bundle: two rows on the importer" in btext and "1 queued, 1 in bundles." in btext)
        bd("merged"); btext = digest_text({})
        ok("…and once the bundle row is no longer live its member is queued again", "2 queued" in btext and "in bundles" not in btext)
        # (e′) the tick re-offers planner requests the broker has not taken — "queued" is not "handled" — and only when there are any
        open(f"{te}/stubs/cc-notify", "w").write(f"#!/bin/sh\necho \"$@\" >> {te}/notify.argv\n"); os.chmod(f"{te}/stubs/cc-notify", 0o755)
        retry_requests()
        ok("REQUESTS: a tick with nothing under ~/.cc/requests asks cc-notify nothing", not os.path.exists(f"{te}/notify.argv"))
        os.makedirs(f"{te}/.cc/requests"); open(f"{te}/.cc/requests/stop:bd-loose.json", "w").write('{"delivered": false}')
        retry_requests()
        ok("…and one on file is re-offered through `cc-notify requests --retry`, never posted and never the owner's",
           open(f"{te}/notify.argv").read().strip() == "requests --retry")
    finally:
        restore(); shutil.rmtree(te, ignore_errors=True)
    # (f) the POSTED digest fits a phone: a box as busy as the 09-10 one (1736 chars) — every section full, every
    # sibling answering — posts the counts, what waits on him and one link; the whole report stays for the terminal
    tf = tempfile.mkdtemp(prefix="cc-reconcile-phone-")
    try:
        scratch(tf, dict(NOOP, **{
            "cc-config": f'case "$2" in CC_BOX) echo fixturebox;; CC_DIGEST_LINK) cat "{tf}/link";; *) echo "$3";; esac',
            "cc-spend": "echo 'total 538.4 40.2'", "cc-limit": "echo 'is at 91% of its 5-hour window'",
            "cc-model": "echo 'opus until probe — fable is not available to this account'",
            "cc-tier": "echo 'The spend tier is essential, since 2026-09-14 14:22. Only what the owner asked for.'",
            "cc-scope": "echo '• 📋 91 asks of yours still open (5 merged but not delivered, 2 asked more than once)'",
            "cc-failures": f'case "$1" in metrics) echo "records: 123 (120 confirmed)  clusters: 76  eligible: 4";; '
                           f'eligible) cat "{tf}/feligible";; esac'}))
        open(f"{tf}/link", "w").write("https://example.slack.com/app-home\n")
        open(f"{tf}/feligible", "w").write("".join(f"c-{i}\tdemo\tkind-{i}/symptom-of-some-length\t9 episodes in 14d\t9 episode(s)\tx..y\tunclaimed 3d\n"
                                                   for i in range(4)))
        recent = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() - 3600))
        asks = {"ask1": "the importer skips rows whose date is in the old format — skip them for good, backfill from the March "
                        "export, or stop the nightly run until you decide which?",
                "ask2": "the member workspace for the tutor wants a second GitHub token scoped to its own repo; grant it or keep "
                        "landing its PRs by hand from the host?"}
        tr = {k: {"status": "waiting", "title": k, "updated": old} for k in asks}
        tr.update({f"ship{i}": {"status": "merged", "title": f"shipped piece number {i} with a title as long as the real ones get",
                                "updated": recent} for i in range(7)})
        tr.update({f"move{i}": {"status": "running", "title": f"moving piece number {i} with a title as long as the real ones get",
                                "updated": old} for i in range(6)})
        tr.update({f"stop{i}": {"status": "blocked", "title": f"stopped piece {i}", "updated": old,
                                "notes": [{"ts": "x", "msg": f"INSTANCE 2026-09-12T03:2xZ: paused at 2 iterations, committed nothing, note {i}"}]}
                   for i in range(4)})
        tr["clock"] = {"status": "running", "title": "the nightly export", "updated": old}
        json.dump({"repo": "busy", "tracks": tr}, open(f"{tf}/.cc/boards/busy.json", "w"))
        os.makedirs(f"{tf}/.cc/slack", exist_ok=True)
        json.dump({f"C1:{i}": {"at": 1788000000 + i, "channel": "#demo", "text": f"pinned thread {i} about something worth a second look",
                               "link": f"https://example.slack.com/archives/C1/p178800000{i}"} for i in range(5)},
                  open(f"{tf}/.cc/slack/revisit.json", "w"))
        snap = {f"busy/{k}": {"state": "waiting", "waiting_on": "person", "why": q} for k, q in asks.items()}
        snap["busy/clock"] = {"state": "running", "waiting_on": "clock", "why": "a Claude usage limit"}
        full, ptext = digest_text(snap), digest_text(snap, phone=True)
        shown = re.sub(r"<https://[^|>]+\|([^>]+)>", r"\1", ptext)   # what the screen shows: a link is its label, as cc-slack counts
        ok(f"PHONE DIGEST: the fixture is as busy as the 09-10 post (whole report {len(full)} chars, over 1200) and the "
           f"posted one fits a screen ({len(shown)} chars shown, at most 600)", len(full) > 1200 and len(shown) <= 600)
        wait = ptext.split("*Waiting on you*", 1)[-1]
        ok("…every needs-you item is still there, under Waiting on you: each row's question and the asks line",
           "*Waiting on you*" in ptext and all(f"• busy: {q[:100]}" in wait for q in asks.values()) and "91 asks of yours still open" in wait)
        ok("…the counts line is the whole report's own, word for word", ptext.splitlines()[0] == full.splitlines()[0]
           and ptext.startswith("*fixturebox* today: 7 shipped, 6 moving, 2 waiting on you, 4 stopped, 1 held. $538 spent"))
        ok("…and the rest is one line, linked, naming what it left out",
           "More on <https://example.slack.com/app-home|the dashboard>: why each stopped, what moved, your 5 📌." in ptext)
        ok("…what it left out is not listed — stopped notes, shipped titles, pins, failure kinds, held names, the tier's gloss, the asks' "
           "breakdown — while the whole report keeps every one",
           all(x not in ptext and x in full for x in ("committed nothing", "shipped piece number", "archives/C1", "symptom of some length (",
                                                     "nightly export", "since 2026-09-14", "5 merged but not delivered"))
           and "🧾 4 kinds of failure need a look." in ptext and "🪫 The spend tier is essential.\n" in ptext
           and "⏳ Claude is at 91% of its 5-hour window." in ptext)
        ok("…and the model line names the outage's KIND — a Fable-only one is not a limit, and its sessions come back by themselves",
           "🔁 Model: opus until probe — fable is not available to this account — not a limit; its sessions are on the next model and return by themselves when it answers again." in full
           and "🔁" not in ptext)
        open(f"{tf}/feligible", "w").close()
        ok("…and a ledger where nothing crossed the rule is no line in the phone one, while the whole report still says so",
           "🧾" not in digest_text(snap, phone=True) and "none needs a look." in digest_text(snap))
        open(f"{tf}/link", "w").write("the dashboard\n")
        ok("…a CC_DIGEST_LINK that is not an https URL is no link: the line names the Home tab",
           "More on the Home tab: why each stopped" in digest_text(snap, phone=True) and "<" not in digest_text(snap, phone=True))
        posted = quietly(digest_cmd, ["--notify"])
        ok("…`digest --notify` prints the phone one it posts, and bare `digest` prints the whole report",
           posted == digest_text({}, phone=True) and "*Stopped*" in quietly(digest_cmd, [])
           and open(f"{tf}/notify.log").read().startswith("digest\t*fixturebox* today: 7 shipped"))
        json.dump({"repo": "busy", "tracks": {k: v for k, v in tr.items() if k in asks}}, open(f"{tf}/.cc/boards/busy.json", "w"))
        os.remove(f"{tf}/.cc/slack/revisit.json")
        ok("…and a box with only questions for him has no rest line at all", "More on" not in digest_text(snap, phone=True)
           and "*Waiting on you*" in digest_text(snap, phone=True))
    finally:
        restore(); shutil.rmtree(tf, ignore_errors=True)
    # ── the failure investigation: inert without the setting, held by the tier or a running one, one claim, one launch ──
    ti = tempfile.mkdtemp(prefix="cc-reconcile-inv-")
    _ie = {k: os.environ.get(k) for k in ("HOME", "CC_CONFIG", "CC_FAILURES", "CC_RECONCILE_LAUNCH", "CC_RECONCILE_PROC",
                                          "CC_RECONCILE_DEEP_LAUNCH",
                                          "CC_SPEND_TIER", "CC_RECONCILE_STUBS")}
    _is, _inv, _deep, _ij = STATE, investigate, deep_fix, ideas_judge
    try:
        os.environ.pop("CC_RECONCILE_STUBS", None)
        os.environ.update(HOME=ti, CC_CONFIG=f"{ti}/.cc/config", CC_FAILURES=f"{ti}/.cc/failures",
                          CC_RECONCILE_LAUNCH=f"{ti}/launch", CC_RECONCILE_PROC=f"{ti}/proc", CC_SPEND_TIER="autonomous")
        globals()["STATE"] = f"{ti}/.cc/state"
        os.makedirs(f"{ti}/.cc"); os.makedirs(f"{ti}/proc")
        open(f"{ti}/launch", "w").write(f'#!/bin/sh\necho "$@" >> {ti}/launch.log\n'); os.chmod(f"{ti}/launch", 0o755)

        def rec(kind, days_ago, *extra):
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() - days_ago * 86400))
            sh(f"{BIN}/cc-failures", "record", "--scope", "sc", "--kind", kind, "--observed", "o", "--ts", ts, *extra)

        def launched():
            return open(f"{ti}/launch.log").read().splitlines() if os.path.exists(f"{ti}/launch.log") else []

        def elig():
            return (sh(f"{BIN}/cc-failures", "eligible") or subprocess.CompletedProcess([], 1, "", "")).stdout

        def proc(pid, *argv):
            os.makedirs(f"{ti}/proc/{pid}", exist_ok=True)
            open(f"{ti}/proc/{pid}/cmdline", "wb").write(("\0".join(argv) + "\0").encode())
        for d in (5, 3, 1):
            rec("guard-policy/permitted-text-refused", d)          # three episodes: eligible on the rule
        ok("INVESTIGATE INERT: without CC_FAILURES_INVESTIGATE=on nothing is claimed or launched, the cluster stays unclaimed",
           investigate() is None and launched() == [] and "\tunclaimed" in elig())
        dry = investigate(dry=True)
        ok("…and --dry names the cluster it would claim and what holds it, claiming nothing",
           dry.startswith("  investigation  would claim i-") and "is not on" in dry and "\tunclaimed" in elig())
        sh(f"{BIN}/cc-config", "set", INVESTIGATE_KEY, "on")
        os.environ["CC_SPEND_TIER"] = "moderate"               # the environment outranks the file, as selftest.sh pins it
        ok("INVESTIGATE TIER: the setting on but `cc-tier allows explore` says no: no claim, no launch, the line says so",
           "tier holds" in (investigate() or "") and launched() == [] and re.search(r"\tunclaimed \d", elig()))
        os.environ["CC_SPEND_TIER"] = "autonomous"
        proc("4242", "/usr/bin/claude", "-p", "run cc-audit failure i-x")
        proc("4243", "/x/cc-audit", "checks")
        ok("running_investigation: a claude QUOTING the command and a cc-audit that is not `failure` hold nothing",
           not running_investigation(f"{ti}/proc"))
        proc("4244", "/bin/bash", "/x/bin/cc-audit", "failure", "i-elsewhere")
        ok("…while a `cc-audit failure` running holds the pass: no claim, no launch — never two at once",
           running_investigation(f"{ti}/proc") and investigate() is None and launched() == [] and "\tunclaimed" in elig())
        shutil.rmtree(f"{ti}/proc/4244")
        line = investigate()
        ok("INVESTIGATE LAUNCH: the setting on, the tier autonomous, nothing running: ONE claim, ONE `cc-audit failure <claim>`",
           len(launched()) == 1 and launched()[0].startswith("failure i-") and "\tclaimed" in elig()
           and (line or "").startswith("  investigation  i-"))
        ok("…and the launch is one line in reconcile.log",
           "\tinvestigation\ti-" in open(f"{ti}/.cc/state/reconcile.log").read())
        ok("…and the next pass launches nothing: the cluster is held by its claim", investigate() is None and len(launched()) == 1)
        rec("gate-target/wrong-revision", 1, "--critical", "main-gate-or-deploy-red")   # a critical cluster: the other slot
        investigate()
        ok("…while a critical cluster is the next pass's one launch", len(launched()) == 2 and launched()[1].startswith("failure i-"))
        # ── the deep fix: a case red once launches nothing; red on three landings, one claim and ONE max-effort launch ──
        os.environ["CC_RECONCILE_DEEP_LAUNCH"] = f"{ti}/deep"
        open(f"{ti}/deep", "w").write(f'#!/bin/sh\nprintf "%s " "$1" "$2" "$3" "$5" "$6" "$7" "$8" "$9" "${{10}}" "${{11}}" "${{12}}" >> {ti}/deep.log\n'
                                      f'echo >> {ti}/deep.log\nprintf "%s" "$4" > {ti}/deep.brief\n')
        os.chmod(f"{ti}/deep", 0o755)

        def deeps():
            return open(f"{ti}/deep.log").read().splitlines() if os.path.exists(f"{ti}/deep.log") else []

        def red(pr, hours_ago):
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() - hours_ago * 3600))
            sh(f"{BIN}/cc-failures", "record", "--scope", "dp", "--kind", "gate-verdict/red", "--ts", ts, "--link", f"pr={pr}",
               "--link", "gate=core/tests/selftest.sh", "--observed", "gate core/tests/selftest.sh did not pass: ✗ cc-guard case 7 is red")
        sh(f"{BIN}/cc-config", "set", DEEP_KEY, "on")
        red(1, 3)
        ok("DEEP FIX: the switch on, the tier autonomous, a case red on ONE landing: nothing claimed, nothing launched",
           deep_fix() is None and deeps() == [] and not os.path.exists(f"{ti}/.cc/failures/recurring/claims.jsonl"))
        red(2, 2); red(3, 1)
        sh(f"{BIN}/cc-config", "set", DEEP_KEY, "off")
        ok("…red on three, but CC_RECURRING_RED_FIX off: inert, and --dry names the case and what holds it",
           deep_fix() is None and deeps() == [] and "is not on" in (deep_fix(dry=True) or ""))
        sh(f"{BIN}/cc-config", "set", DEEP_KEY, "on")
        os.environ["CC_SPEND_TIER"] = "moderate"
        ok("…on, but the tier holds explore work: no claim, no launch, the line says the tier holds it",
           "tier holds" in (deep_fix() or "") and deeps() == [] and not os.path.exists(f"{ti}/.cc/failures/recurring/claims.jsonl"))
        os.environ["CC_SPEND_TIER"] = "autonomous"
        line = deep_fix()
        ok("…allowed: ONE claim and ONE worker, `cc dp recurring-red-<case> --go` on claude-opus-5-5 at --effort max",
           len(deeps()) == 1 and re.fullmatch(r"dp recurring-red-[0-9a-f]{8} --go --model claude-opus-5-5 --effort max --loop 3 --budget 25 ",
                                              deeps()[0]) is not None
           and len(open(f"{ti}/.cc/failures/recurring/claims.jsonl").read().splitlines()) == 1
           and "launched" in (line or "") and "\tdeep-fix\td-" in open(f"{ti}/.cc/state/reconcile.log").read())
        ok("…its brief names the case, the landings and the way out for a cause outside the repo",
           all(w in open(f"{ti}/deep.brief").read() for w in ("CASE: cc-guard case N is red", "PR #1, PR #2, PR #3", "raised-", "never merge by hand")))
        red(4, 0)
        ok("…and inside the cool-down the next pass launches nothing, the case red again or not",
           deep_fix() is None and len(deeps()) == 1)
        os.environ.pop("CC_RECONCILE_DEEP_LAUNCH")
        sh(f"{BIN}/cc-config", "set", DEEP_KEY, "off")
        scratch(ti, NOOP)
        globals()["investigate"] = lambda dry=False: "  investigation  from-the-tick"
        globals()["deep_fix"] = lambda dry=False: "  deep fix   from-the-tick"
        globals()["ideas_judge"] = lambda: ["  ideas  from-the-tick"]
        ok("THE TICK carries it: the investigation's line is printed by tick(), no timer of its own",
           "investigation  from-the-tick" in quietly(tick, {}, False))
        ok("…and so does the deep fix's", "deep fix   from-the-tick" in quietly(tick, {}, False))
        ok("…and so does the ideas judge's", "ideas  from-the-tick" in quietly(tick, {}, False))
    finally:
        restore(); globals().update(STATE=_is, investigate=_inv, deep_fix=_deep, ideas_judge=_ij)
        for k, v in _ie.items():
            os.environ.pop(k, None) if v is None else os.environ.update({k: v})
        shutil.rmtree(ti, ignore_errors=True)
    print(f"cc-reconcile selfcheck: {p} passed, {f} failed")
    return 1 if f else 0
