# cc-replay's selfcheck: the cases behind `cc-replay selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-replay execs this file INSIDE ITS OWN NAMESPACE and calls the cmd_selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def cmd_selfcheck():
    fails = []

    def check(name, cond):
        print(("  ✓ " if cond else "  ✗ ") + name)
        if not cond:
            fails.append(name)

    # 1. the virtual clock: four gate threads park for 100/200/300/400 s; joining them all takes the clock to +400
    #    and no wall-clock time, and each advance lands on a wake — never a tick between them.
    clock = Clock(1000)
    th = FakeThreading(clock)
    ends = []
    ts = [th.Thread(target=lambda d=d: (clock.sleep(d), ends.append(clock.now))) for d in (300, 100, 400, 200)]
    w0 = time.time()
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    _t = tempfile.mkdtemp(prefix="cc-replay-shim-")
    try:
        load_candidate(os.path.join(os.path.dirname(os.path.realpath(__file__)), "cc-la" + "nd"), _t, None, None, None)
        _said = ""
    except SystemExit as e:
        _said = str(e)
    finally:
        shutil.rmtree(_t, ignore_errors=True)
    check("today's core/bin shim onto the lander is refused as a candidate, with one line saying why", NOT_MONOLITH in _said)
    check("virtual clock: four parked gate threads advance the clock to the longest (1400), in wake order, in no wall time",
          clock.now == 1400 and sorted(ends) == [1100, 1200, 1300, 1400] and time.time() - w0 < 2)
    check("…and it advanced exactly four times — once per distinct wake, never on a tick", clock.advances == 4)
    clock = Clock(0)
    th = FakeThreading(clock)
    same = [th.Thread(target=lambda: clock.sleep(300)) for _ in range(4)]
    for t in same:
        t.start()
    for t in same:
        t.join()
    check("…and four threads parked for the SAME 300 s advance it once, to 300", clock.now == 300 and clock.advances == 1)
    # Event and Condition park too: a waiter on an Event nobody has set is parked, and the clock still moves for
    # the sleeper beside it; the set wakes the waiter without a tick.
    clock = Clock(0)
    th = FakeThreading(clock)
    ev, got = th.Event(), []
    waiter = th.Thread(target=lambda: (ev.wait(), got.append(clock.now)))
    setter = th.Thread(target=lambda: (clock.sleep(50), ev.set()))
    waiter.start(); setter.start(); waiter.join(); setter.join()
    check("an Event waiter is parked, the sleeper beside it moves the clock to 50, and set() wakes the waiter there",
          got == [50] and clock.now == 50)
    clock = Clock(0)
    th = FakeThreading(clock)
    cv, box = th.Condition(), []
    def consumer():
        with cv:
            while not box:
                cv.wait()
            box.append(clock.now)
    def producer():
        clock.sleep(70)
        with cv:
            box.append("x")
            cv.notify_all()
    c, p = th.Thread(target=consumer), th.Thread(target=producer)
    c.start(); p.start(); c.join(); p.join()
    check("a Condition waiter is parked and wakes on notify at the producer's virtual time", box == ["x", 70])
    # Arrivals: an arrival due before the next wake is injected at its own time, with the clock stopped there.
    clock = Clock(0)
    th = FakeThreading(clock)
    seen = []
    clock.inject = lambda p: seen.append((p, clock.now))
    clock.arrivals = [(40, "a"), (90, "b")]
    t = th.Thread(target=lambda: clock.sleep(100))
    t.start(); t.join()
    check("arrivals due before a wake are injected at their own times, and the sleeper still wakes at 100",
          seen == [("a", 40), ("b", 90)] and clock.now == 100)
    # A deadlock — everything parked, nothing due — is reported, not hung.
    clock = Clock(0)
    th = FakeThreading(clock)
    ev2 = th.Event()
    dead = []
    t = th.Thread(target=lambda: (lambda: dead.append(ev2.wait()))())
    t.start()
    try:
        t.join()
    except Deadlock:
        dead.append("raised")
    check("every thread parked with nothing due is a Deadlock raised to the joiner, never a hang", "raised" in dead and clock.dead)

    # 2. the conflict model: a PR conflicts when a PR merged since its base, in the replay's order, touches one of
    #    its files — and not when the files are disjoint, and not once it has rebased past that merge.
    tr = fixture_trace()
    root = tempfile.mkdtemp(prefix="cc-replay-selfcheck-")
    try:
        w = World(tr, root, Clock(0), "files")
        w.merges.append((0, "r", 2, 0, {"bin/tool2", "bin/shared"}))
        check("conflict model: PR 3 (shares bin/shared) conflicts after PR 2 merged past its base", w.conflicting(("r", 3)))
        check("…and PR 4, on disjoint files, does not", not w.conflicting(("r", 4)))
        w.rebase(("r", 3))
        check("…and a rebase past that merge clears it", not w.conflicting(("r", 3)))
        w.merges.append((1, "r", 4, 0, {"bin/tool4"}))
        check("…a later merge on other files leaves it clear", not w.conflicting(("r", 3)))
        w2 = World(tr, root, Clock(0), "none")
        w2.merges.append((0, "r", 2, 0, {"bin/shared"}))
        check("--conflicts none never conflicts", not w2.conflicting(("r", 3)))
        w4 = World(tr, root, Clock(0), "history")
        w4.merges.append((0, "r", 2, 0, {"bin/shared"}))
        w4.prs[("r", 3)]["conflicted"] = True
        check("--conflicts history (the default) conflicts a PR history saw conflict, on the same rule…",
              w4.conflicting(("r", 3)))
        w4.prs[("r", 3)]["conflicted"] = False
        check("…and never one history did not", not w4.conflicting(("r", 3)))
        # the gh answer carries it: mergeable flips to CONFLICTING, and a merge is refused with GitHub's words
        w3 = World(tr, root, Clock(0), "files")
        w3.merges.append((0, "r", 2, 0, {"bin/shared"}))
        cwd = f"{root}/dev/r"
        rc, o = w3.gh(["gh", "pr", "view", "3", "--json", "state,mergeable"], cwd)
        check("gh pr view answers CONFLICTING for it", rc == 0 and json.loads(o)["mergeable"] == "CONFLICTING")
        rc, o = w3.gh(["gh", "pr", "merge", "3", "--squash"], cwd)
        check("…and gh pr merge refuses it with GitHub's own words", rc == 1 and "merge conflicts" in o)
        rc, o = w3.gh(["gh", "pr", "merge", "4", "--squash"], cwd)
        rc2, o2 = w3.gh(["gh", "pr", "view", "4", "--json", "state,mergedAt"], cwd)
        check("a clean PR merges and reads MERGED after", rc == 0 and json.loads(o2)["state"] == "MERGED")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # 3. the trace loader: a fixture round-trips through a file, and a file that is not a trace is refused.
    d = tempfile.mkdtemp(prefix="cc-replay-selfcheck-")
    try:
        with open(f"{d}/t.json", "w") as f:
            json.dump(fixture_trace(), f)
        t = load_trace(f"{d}/t.json")
        check("trace loader: a fixture loads with its landings, arrivals, heads and medians",
              len(t["landings"]) == 4 and t["landings"][2]["files"][1][1] == "bin/shared" and t["medians"]["review"] == 200)
        with open(f"{d}/bad.json", "w") as f:
            f.write('{"version": 2}')
        try:
            load_trace(f"{d}/bad.json")
            bad = False
        except SystemExit:
            bad = True
        check("…and a file that is not a v1 or v2 trace is refused", bad)
        # the ledger and marker readers, on lines of the shapes the sources print
        ev = ledger_events_from_text("2026-09-07T10:00:00Z\tqueued r#7 who=- chat=- by=x\n2026-09-07T10:30:00Z\tdone r#7 rc=0 [r] PR #7: landed ✅\n"
                                     "2026-09-07T10:31:00Z\tqueued r#deploy span=a..b by=the catch-up sweep\n", 0, 2_000_000_000)
        check("the ledger reader keeps queued/done for a PR and drops the deploy rows",
              [e["kind"] for e in ev] == ["queued", "done"] and ev[1]["rest"].startswith("rc=0"))
        old = parse_marker("<!-- cc-land-review 926d8b229822 LAND-AFTER-FIX -->\n**cc-land review** — `926d8b229822`, model `claude-opus-5`\n")
        new = parse_marker("<!-- cc-land-review v2 change=6eeebb3b7c8ccece3c98ae8111b83bc5045fd33d base=275f737a49f3 head=418892988b79 verdict=LAND by=r-b8-reviewer -->\nx")
        check("both marker shapes are read: the head-keyed one is a bought verdict, the change-keyed one signed by a "
              "person is a recorded one", old == ("926d8b229822", "LAND-AFTER-FIX", "", "claude-opus-5", "bought")
              and new == ("418892988b79", "LAND", "6eeebb3b7c8ccece3c98ae8111b83bc5045fd33d", "r-b8-reviewer", "recorded"))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # 4. determinism, end to end: the OLD single-file tool scores the fixture twice to the same bytes, every PR
    #    merges, and the PRs on a shared file were gated one after the other (the second's merge is later). The file
    #    beside this one is a shim onto the lander now, so these run only on a copy CC_REPLAY_CANDIDATE names
    #    (`cc-bin-at <ref>` from before the cutover), and say they were skipped otherwise.
    cand = os.environ.get("CC_REPLAY_CANDIDATE") or os.path.join(os.path.dirname(os.path.realpath(__file__)), "cc-land")
    try:
        monolith = "def cmd_work(" in open(cand, errors="replace").read()
    except OSError:
        monolith = False
    if not monolith:
        print("  - end-to-end scoring skipped: no old single-file landing tool here (CC_REPLAY_CANDIDATE names one)")
    if monolith:
        a, la, ca = score(cand, fixture_trace(), verbose=True)
        b, _, _ = score(cand, fixture_trace())
        check("determinism: two scores of the fixture trace against the cc-land beside this file are byte-identical", a == b)
        check("…and every fixture PR merged in the replay", "merged=4/4" in a.splitlines()[0])
        first = a.splitlines()[0]
        check("…with the score line in its contract shape", re.match(r"^score \d+\.\d suites=\d+ reviews=\d+ repairs=\d+ unmerged=\d+ merged=\d+/\d+$", first) is not None)
        r, lr, _ = score(cand, fixture_trace(stopped=(1,), recorded_at=900), verbose=True)
        check("a LAND a person recorded after the bought review stopped PR 1 lands it — queued again by the record, read, not bought again",
              "merged=4/4" in r.splitlines()[0] and "reviews=4" in r.splitlines()[0] and "after the recorded LAND" in lr)
        u, _, _ = score(cand, fixture_trace(stopped=(1,)))
        check("…and without the record the same PR stays open on its DO-NOT-LAND", "merged=3/4" in u.splitlines()[0])
        if not (a == b and "merged=4/4" in first):
            print(la[-3000:]); print(ca[-3000:])
        check("…and a v1 trace's report names no v2 counts", "trace=v2" not in a.splitlines()[1])
        # v2, end to end. A person's hand merge: PR 1 stopped on its DO-NOT-LAND merges at the time a person
        # merged it in history…
        p2, _, _ = score(cand, fixture_trace(version=2, stopped=(1,), person=(1,)))
        check("v2 person: a PR stopped in the replay is merged at its hand-merge time, counted as the person's",
              "merged=4/4" in p2.splitlines()[0] and "person-merged=1" in p2.splitlines()[1])
        # …a PR the candidate lands before that time stays the candidate's…
        p3, _, _ = score(cand, fixture_trace(version=2, person=(4,)))
        check("…a hand-merged PR the candidate lands first is not a person's merge", "person-merged=0" in p3.splitlines()[1])
        # …and the same stop on a v1 trace stays open, as it always did.
        p1, _, _ = score(cand, fixture_trace(version=1, stopped=(1,), person=(1,)))
        check("…and a v1 trace never merges it", "merged=3/4" in p1.splitlines()[0])
    else:
        print("  · no cc-land beside this file — the end-to-end cases did not run")

    # 5. trace v2's plumbing, behind stops and extraction, each on a fixture of its own.
    root = tempfile.mkdtemp(prefix="cc-replay-selfcheck-")
    try:
        cwd = f"{root}/dev/r"
        w = World(fixture_trace(version=2), root, Clock(0), "history")
        g = lambda *a: w.git(["git", *a], cwd)
        tip0 = g("rev-parse", "--verify", "--quiet", "origin/main^{commit}")[1].strip()
        check("v2 plumbing: a head on an unmoved base holds it (is-ancestor rc 0), so merge_result gates the head",
              g("merge-base", "--is-ancestor", tip0, "3".zfill(12) + "0" * 28)[0] == 0)
        proj = g("commit-tree", g("merge-tree", "--write-tree", "1".zfill(12), "3".zfill(12))[1].strip(), "-p", "1".zfill(12), "-p", "3".zfill(12))[1].strip()
        projected = g("merge-tree", "--write-tree", proj, "4".zfill(12))[1].strip()
        w.clock.now = 10
        w.land(("r", 1)); w.land(("r", 3))
        tip = g("rev-parse", "--verify", "--quiet", "origin/main^{commit}")[1].strip()
        check("…once PR 1 merged past it, the base is no ancestor (rc 1) and the tip is a new commit",
              tip != tip0 and g("merge-base", "--is-ancestor", tip, "4".zfill(12))[0] == 1)
        check("…the merge of the base with PR 4, once 1 and 3 merged, is the very tree the projection gated",
              g("merge-tree", "--write-tree", tip, "4".zfill(12))[1].strip() == projected)
        w2 = World(fixture_trace(version=2), root, Clock(0), "history")
        w2.clock.now = 10
        w2.land(("r", 1))
        tip1 = w2.git(["git", "rev-parse", "origin/main^{commit}"], cwd)[1].strip()
        check("…and when PR 3 did not merge, it is another tree",
              w2.git(["git", "merge-tree", "--write-tree", tip1, "4".zfill(12)], cwd)[1].strip() != projected)
        v1w = World(fixture_trace(version=1), root, Clock(0), "history")
        v1w.merges.append((0, "r", 1, 0, {"bin/tool1"}))
        check("…while a v1 world answers as it always did: every head holds the base",
              v1w.git(["git", "merge-base", "--is-ancestor", "x", "4".zfill(12)], cwd)[0] == 0)
        # behind: PR 3 history saw stopped merely behind is refused once a merge passed its base; PR 4 is not.
        wb = World(fixture_trace(version=2, behind=(3,)), root, Clock(1_800_000_000), "history")
        wb.land(("r", 1))
        rc, o = wb.gh(["gh", "pr", "merge", "3", "--squash"], cwd)
        view = json.loads(wb.gh(["gh", "pr", "view", "3", "--json", "mergeStateStatus"], cwd)[1])
        check("v2 behind: a PR history stopped behind is refused with GitHub's --auto words while a merge passed its base",
              rc == 1 and "--auto" in o and view["mergeStateStatus"] == "BEHIND" and wb.n["behind"] == 1)
        check("…and a PR history never saw stopped merges though just as behind", wb.gh(["gh", "pr", "merge", "4", "--squash"], cwd)[0] == 0)
        old_head = wb.head(("r", 3))[0]
        rc, o = wb.gh(["gh", "pr", "update-branch", "3"], cwd)
        new_head, gen = wb.head(("r", 3))
        check(f"…gh pr update-branch merges the base in: a new head, the same change, {UPDATE_SECS} s on the clock, and it merges",
              rc == 0 and new_head != old_head and gen == 0 and wb.clock.now == 1_800_000_000 + UPDATE_SECS
              and wb.behind(("r", 3)) == 0 and wb.gh(["gh", "pr", "merge", "3", "--squash"], cwd)[0] == 0)
        wv1 = World(fixture_trace(version=1), root, Clock(0), "history")
        wv1.land(("r", 1))
        wv1.prs[("r", 3)]["stops"] = [{"kind": "behind", "behind": 1}]
        check("…and a v1 world neither refuses it nor answers update-branch",
              wv1.gh(["gh", "pr", "update-branch", "3"], cwd)[0] == 1 and wv1.gh(["gh", "pr", "merge", "3", "--squash"], cwd)[0] == 0)
        # extraction: the three classes read off lines of the shapes the sources print
        L = lambda at, pid, text: (at, pid, text)
        lines = [L(10, 7, "gating and reading 2 queued job(s) — side by side"),
                 L(11, 7, "  ✓ 1 gate(s) passed on PR #1 at the full tier (x): tests/check.sh"),
                 L(12, 7, "  ✓ 1 gate(s) passed on PR #2 at the full tier (x): tests/check.sh"),
                 L(13, 7, "  ✓ 1 gate(s) passed on PR #1: tests/check.sh — the full tier, x; run for this sweep by the prepare phase, on y"),
                 L(14, 7, "  ✓ 1 gate(s) passed on PR #2 at the full tier (x): tests/check.sh"),
                 L(20, 8, "  ✓ 1 gate(s) passed on PR #3 at the full tier (x): tests/check.sh"),
                 L(21, 8, "  ✓ 1 gate(s) passed on PR #3 at the full tier (x): tests/check.sh")]
        mf = memo_facts(lines, {("r", 1), ("r", 2), ("r", 3)})
        check("extract memo: a `by the prepare phase` line is a hit, gates passed twice in a prepared sweep a miss…",
              mf.get(("r", 1)) == [(13, True)] and mf.get(("r", 2)) == [(14, False)])
        check("…and twice in a sweep that prepared nothing is not a miss", ("r", 3) not in mf)
        tr = fixture_trace(person=(2,))
        tr["landings"][1]["queue_merged"] = False
        tr["landings"][0]["dones"] = [{"at": stamp(1_800_000_100), "rc": 1, "short": "[r] PR #1: NOT merged ❌ — PR #1 is not mergeable yet (checks pending, or it needs a rebase)"}]
        tr["landings"][2]["dones"] = [{"at": stamp(1_800_000_100), "rc": 1, "short": "[r] PR #3: NOT merged ❌ — PR #3 conflicts with main — rebase it, then land it"}]
        tr["landings"][3]["dones"] = [{"at": stamp(1_800_000_100), "rc": 1, "short": "[r] PR #4: NOT merged ❌ — gate tests/check.sh did not pass: a merge conflicts with x"}]
        counts = upgrade(tr, lines)
        by = {l["pr"]: l for l in tr["landings"]}
        check("extract stops: `not mergeable yet` is behind, `conflicts with main — rebase` a conflict, a red gate neither",
              [s["kind"] for s in by[1]["stops"]] == ["behind"] and [s["kind"] for s in by[3]["stops"]] == ["conflict"]
              and by[4]["stops"] == [] and by[3]["conflicted"] and not by[1]["conflicted"])
        check("extract person: a PR merged outside the queue carries its merge time, a queue merge none",
              by[2]["person"] == {"at": by[2]["merged"]} and by[1]["person"] is None)
        check("…and the trace names its version and the counts it printed",
              tr["version"] == 2 and counts == {"memo_hits": 1, "memo_misses": 1, "stops_behind": 1, "stops_conflict": 1, "person": 1})
    finally:
        shutil.rmtree(root, ignore_errors=True)
    # the change key is the landing's own: a rebase that only moved a hunk's line numbers and its function-context
    # tail is one change, and a head keyed by a legacy (tail-kept) marker still matches its v2-keyed rebase.
    # The landing's own is the lander's review.change_digest now (core/lander/review.py, beside this file's bin/).
    core = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    if core not in sys.path:
        sys.path.insert(0, core)
    import lander.review as land
    d1 = "diff --git a/x b/x\nindex 1..2 100644\n@@ -10,3 +10,4 @@ def f():\n a\n+b\n c\n"
    d2 = "diff --git a/x b/x\nindex 3..4 100644\n@@ -40,3 +40,4 @@ def g():\n a\n+b\n c\n"
    d3 = d2.replace("+b", "+z")
    check("replay digest: equals the landing's for the same diff, both rules",
          change_digest(d1) == land.change_digest(d1) and change_digest(d1, True) == land.change_digest(d1, legacy=True))
    check("…a rebase that moved only the hunk's numbers and tail is one change, under the v2 rule only",
          change_digest(d1) == change_digest(d2) and change_digest(d1, True) != change_digest(d2, True))
    check("…a legacy-keyed head and its v2-keyed rebase share a key; a changed body shares none",
          same_change((change_digest(d1, True), change_digest(d1), change_digest(d1, True)),
                      (change_digest(d2), change_digest(d2), change_digest(d2, True)))
          and not same_change((change_digest(d1, True), change_digest(d1), change_digest(d1, True)),
                              (change_digest(d3), change_digest(d3), change_digest(d3, True))))
    # the lander path (v3): a fixture queue.log and job files -> a trace; the trace -> this checkout's own lander,
    # driven in a child process (a candidate is imported as the `lander` package, once per process).
    t0 = 1_800_000_000
    lroot = tempfile.mkdtemp(prefix="cc-replay-lander-fx-")
    try:
        lq = f"{lroot}/land"
        os.makedirs(f"{lq}/rest")
        L = lambda at, text: f"{stamp(t0 + at)}\t{text}\n"  # noqa: E731
        log = "".join([
            L(-100, "queued r#9 who=x"), L(5, "stage r#9 merged sha=aa"),
            L(10, "queued r#1 who=x"), L(11, "stage r#1 lane"), L(611, "stage r#1 gate gate=a ok=yes secs=600"),
            L(620, "stage r#1 merged sha=bb"), L(700, "stage r#1 done"),
            L(20, "queued r#2 who=x"), L(21, "stage r#2 lane"), L(621, "stage r#2 gate gate=b ok=yes secs=600"),
            L(700, "stage r#2 verdict verdict=LAND"), L(710, "stage r#2 merged sha=cc"),
            L(30, "queued r#3 who=x"), L(31, "stage r#3 lane"), L(1230, "stage r#3 gate gate=a ok=no secs=600"),
            L(1231, "stage r#3 handback"), L(2000, "requeued r#3 who=x"), L(2001, "stage r#3 lane"),
            L(2601, "stage r#3 gate gate=a ok=yes secs=600"), L(2700, "stage r#3 merged sha=dd"),
            L(40, "queued r#4 who=x"), L(3000, "stage r#4 merged by=before"),
            L(50, "stage demo#7 verdict=LAND digest=x"),
            L(-300, "queued r#8 who=x"), L(-250, "stage r#8 merged sha=ab"), L(-240, "stage r#8 deploy-pending"),
            L(60, "stage r#8 done"),
            L(-300, "queued r#10 who=x"), L(-250, "stage r#10 handback"), L(100, "requeued r#10 who=x"),
            L(101, "stage r#10 lane"),
            L(-300, "queued r#11 who=x"), L(-250, "stage r#11 query"), L(70, "stage r#11 done"),
        ])
        with open(f"{lq}/queue.log", "w") as f:
            f.write("".join(sorted(log.splitlines(True))))
        for n, files, checks, paid, hist in ((1, ["x.py"], ["a"], False, []), (2, ["y.py"], ["b"], True, []),
                                              (3, ["x.py", "z.py"], ["a"], False,
                                               [{"at": stamp(t0 + 800), "state": "held", "why": "PR #3 conflicts with main: x.py"}])):
            with open(f"{lq}/rest/r-{n}.json", "w") as f:
                json.dump({"repo": "r", "pr": n, "files": files, "plan": {"checks": checks, "paid": paid}, "history": hist}, f)
        os.environ["CC_REPLAY_SYSSTAT"] = f"{lroot}/no-sysstat"
        tr = lander_trace(f"{lq}/queue.log", lq, t0, t0 + 4000)
        by = {p["pr"]: p for p in tr["prs"]}
        check("v3 extract: a PR first queued in the window is in and scored, a demo line is not a PR",
              sorted(p["pr"] for p in scored(tr)) == [1, 2, 3, 4])
        check("…one in the lane when the window opened is replayed from its start, not scored; one that left it before "
              "is replayed from its next request; one merged before it, or never asked for again, is left out",
              sorted(by) == [1, 2, 3, 4, 9, 10] and by[9]["inflight"] and by[9]["arrivals"] == by[9]["seen"] == [t0]
              and by[10]["inflight"] and by[10]["arrivals"] == [t0 + 100] and by[10]["seen"] == [t0 + 101]
              and tr["left_out"] == ["r#11"] and not by[1].get("inflight"))
        check("…a request after a handback is a new head; the gates before it are head 0, after it head 1",
              by[3]["bumps"] == [t0 + 2000] and [r[:3] for r in by[3]["gates"]["a"]] == [[0, 600, "no"], [1, 600, "yes"]]
              and by[1]["bumps"] == [])
        check("…the pick-up is history's first stage line after each request; a verdict's secs run from the line before it",
              by[3]["seen"] == [t0 + 31, t0 + 2001] and by[4]["seen"] == [t0 + 3000] and by[2]["verdicts"] == [[0, "LAND", 79]])
        check("…a conflict hold from the job file is kept at its head; a PR the lane never planned is opaque, one it planned not",
              by[3]["conflicts"] == [[0, t0 + 800]] and by[4]["opaque"] and not by[1]["opaque"]
              and by[4]["merged"] == {"at": t0 + 3000, "by": "person"} and by[1]["merged"]["by"] == "lane")
        spans = main_red_spans({"until": stamp(1000), "prs": [{"gates": {"g": [[0, 5, "main-red", 100], [0, 5, "yes", 200]]}},
                                                                {"gates": {"g": [[0, 5, "main-red", 300]], "h": [[0, 5, "yes", 50]]}}]})
        check("main red is a span of time on any PR: to the next pass anywhere, or past the window's end; a pass alone is none",
              spans == {"g": [(100, 200), (300, 1001)]})
        calm = f"{lroot}/calm.json"
        with open(calm, "w") as f:
            json.dump(tr, f)
        me = os.path.realpath(__file__)

        def run(trace, *extra):
            # three slots unless the case names its own: the candidate's own K is its host's, never a case's
            extra = extra if "--slots" in extra else (*extra, "--slots", "3")
            r = subprocess.run([sys.executable, me, "score", "--candidate", core, "--trace", trace, *extra],
                               capture_output=True, text=True, timeout=120)
            lines = r.stdout.splitlines()
            head = next((i for i, ln in enumerate(lines) if ln.startswith("PR ")), len(lines))
            rows = {ln.split()[0]: ln.split()[1:] for ln in lines[head + 1:] if ln.strip()}
            return r, rows
        a, arows = run(calm)
        b, _ = run(calm)
        num = lambda rows, k, i=1: float(rows[k][i]) if k in rows and rows[k][i] != "-" else None  # noqa: E731
        check("v3 score: a checkout's own core/lander is driven, and prints the score and history's line beside it",
              a.returncode == 0 and a.stdout.startswith("score p50 ") and "\nhistory p50 " in a.stdout)
        check("…the same trace scores to the same bytes", a.stdout == b.stdout and a.stdout)
        check("…a calm box runs #1's and #2's checks side by side: #2 merges ~11 min in, as history's recorded times say",
              num(arows, "r#2") is not None and 10.5 <= num(arows, "r#2") <= 12.0)
        check("…#3 shares x.py with #1, is handed back on its recorded red and merges on the head pushed after it",
              num(arows, "r#3") is not None and 42 <= num(arows, "r#3") <= 46)
        check("…a PR the lane never planned merges when the person merged it, not before",
              num(arows, "r#4") is not None and abs(num(arows, "r#4") - 49.3) < 0.2)
        check("…the reviewer's digest_of is answered from the trace (a stable stand-in per head), never by running git",
              (lambda u: u.digest_of("/nonexistent", "a", "h1") == u.digest_of("/nonexistent", "b", "h1")
               != u.digest_of("/nonexistent", "a", "h2"))(_digest_unit(core)))
        real_run, leak = subprocess.run, ""
        try:
            with tripwire(core):
                land.digest_of("/nonexistent", "a", "h1")
        except ReplayLeak as e:
            leak = str(e)
        check("…a lander call no stand-in answers is refused by name, not run: review.digest_of's git is a ReplayLeak",
              "review.digest_of:" in leak and "`git " in leak and subprocess.run is real_run)
        if a.returncode:
            print("    " + (a.stderr.strip().splitlines() or ["(no stderr)"])[-1])
        def leak_of(fn):
            try:
                fn()
            except ReplayLeak as e:
                return str(e)
            return ""
        check("…a unit function or a whole unit the world lacks is a ReplayLeak naming it, not a held job",
              "reviewer.nothing," in leak_of(lambda: _digest_unit(core).nothing)
              and "its tip unit" in leak_of(lambda: answering(lambda lane, name: None)(None, "tip")))
        lmods = {n: importlib.import_module(f"lander.{n}") for n in ("types", "events", "jobs", "git", "gh", "manifest",
                                                                      "run", "admission", "members", "records", "lane")}
        saved = {n: dict(vars(m)) for n, m in lmods.items()}
        unit_was, wroot = lmods["lane"].Lane.unit, tempfile.mkdtemp(prefix="cc-replay-compiled-")
        try:
            ln = lmods["lane"]
            with tripwire(core):
                raw = leak_of(lambda: ln.compiled("/nonexistent", "a", "h1")) if hasattr(ln, "compiled") else None
            stand_in(lmods, LanderWorld({"prs": [], "medians": {"review": 1}, "until": "1970-01-01T00:00:00Z"}, lmods,
                                        VClock(0, 1), 0, wroot), VClock(0, 1))
            got = [[]] if not hasattr(ln, "compiled") else []
            with tripwire(core):
                if hasattr(ln, "compiled"):
                    leak_of(lambda: got.append(ln.compiled("/nonexistent", "a", "h1")))
        finally:
            for n, m in lmods.items():
                vars(m).update(saved[n])
            lmods["lane"].Lane.unit = unit_was
            shutil.rmtree(wroot, ignore_errors=True)
        check("…lane.compiled, where the lander has it, is answered with no compiled files ([], never None), not its "
              "sealed git: unstubbed it is a ReplayLeak under the tripwire",
              got == [[]] and (raw is None or ("lane.compiled:" in raw and "`git " in raw)))
        check("…and a replay of this checkout's lander called nothing the world does not answer (the line above names it)",
              a.returncode == 0)
        # a head history let past main's red (ok=ratchet) comes back as a pass with the ratchet's note, so the
        # candidate's lane.took logs it ok=ratchet again, not ok=yes (Opus read, 10-13); a plain pass has no note
        rw = LanderWorld({"prs": [{"repo": "r", "pr": 1, "bumps": [], "gates": {"g": [[0, 5, "ratchet", 100]],
                                                                               "y": [[0, 5, "yes", 100]]}}],
                          "medians": {"review": 1, "gate": {}}, "until": "1970-01-01T00:00:00Z"}, lmods, VClock(0, 1),
                         0, wroot)
        ro = rw.run_plan("/x/r", None, __import__("types").SimpleNamespace(checks=["g", "y"]), [], "t", pr=1)
        check("…a recorded ok=ratchet replays as a pass whose note the lane reads as a ratchet",
              ro["g"].status == lmods["types"].PASSED and ro["g"].note.startswith("ratchet") and ro["y"].note == "")
        # history's load reaches the candidate's own admission: three PRs side by side on a calm box, and on a box
        # at 2x its cores as many as the candidate's slots_now() admits at that load, the rest a check later
        tq = f"{lroot}/land-load"
        os.makedirs(f"{tq}/rest")
        with open(f"{tq}/queue.log", "w") as f:
            f.write("".join(sorted(L(at, f"{w} t#{n}{x}") for n in (1, 2, 3) for at, w, x in (
                (10, "queued", " who=x"), (11, "stage", " lane"), (611, "stage", f" gate gate=c{n} ok=yes secs=600"),
                (620, "stage", f" merged sha=t{n}")))))
        for n in (1, 2, 3):
            with open(f"{tq}/rest/t-{n}.json", "w") as f:
                json.dump({"repo": "t", "pr": n, "files": [f"t{n}.py"], "plan": {"checks": [f"c{n}"], "paid": False}}, f)
        lt = lander_trace(f"{tq}/queue.log", tq, t0, t0 + 4000)
        tcalm, tload = f"{lroot}/t-calm.json", f"{lroot}/t-load.json"
        with open(tcalm, "w") as f:
            json.dump(lt, f)
        with open(tload, "w") as f:
            json.dump(dict(lt, load=[[t0 - 900, 10_000.0]]), f)
        adm = importlib.import_module("lander.admission")
        with open(f"{lroot}/loadavg", "w") as f:
            f.write(f"{2 * (os.cpu_count() or 1) + 1} 1 1 1/1 1\n")
        want = adm.slots_now(f"{lroot}/no-psi", 3, f"{lroot}/loadavg")
        fast = lambda rows: sum(1 for n in (1, 2, 3) if (num(rows, f"t#{n}") or 99) < 12)  # noqa: E731
        (_, trows), (_, lrows) = run(tcalm, "--slots", "3"), run(tload, "--slots", "3")
        check(f"…history's load at 2x the cores reaches the candidate's slots_now() ({want} of 3): that many of three "
              "PRs merge in one check's time, the rest a check later; all three on a calm box",
              want < 3 and fast(trows) == 3 and fast(lrows) == want
              and all((num(lrows, f"t#{n}") or 0) >= 19 for n in range(want + 1, 4)))
        d, _ = run(calm, "--slots", "1")
        check("…--slots is the candidate's own SLOTS: one slot on a calm box is history's pace for #2 again",
              d.returncode == 0 and "slots 1," in d.stdout)
        # slot waits on work the trace never saw: its own fixture
        bq = f"{lroot}/land-blocked"
        os.makedirs(f"{bq}/rest")
        with open(f"{bq}/queue.log", "w") as f:
            f.write("".join(sorted([
                L(10, "queued s#5 who=x"), L(11, "stage s#5 lane"), L(12, "stage s#5 checking"),
                L(1212, "stage s#5 gate gate=a ok=yes secs=10"), L(1220, "stage s#5 merged sha=ee"),
                L(10, "queued s#6 who=x"), L(11, "stage s#6 lane"), L(1211, "stage s#6 gate gate=a ok=yes secs=10"),
                L(1300, "stage s#6 merged sha=ff"),
                L(10, "queued s#7 who=x"), L(12, "stage s#7 checking"), L(9212, "stage s#7 gate gate=a ok=yes secs=10"),
                L(9300, "stage s#7 merged sha=gg"),
            ])))
        for n in (5, 6, 7):
            with open(f"{bq}/rest/s-{n}.json", "w") as f:
                json.dump({"repo": "s", "pr": n, "files": [f"f{n}.py"], "plan": {"checks": ["a"], "paid": False}}, f)
        bt = lander_trace(f"{bq}/queue.log", bq, t0, t0 + 10000)
        check("v3 extract: a check that started 20 min after the lane's `checking` sat on a slot; one after a bare "
              "`lane` line, or 2.5 h later (a stalled lane), is no slot wait",
              bt["blocked"] == [[t0 + 12, t0 + 1202]])
        waits, free = f"{lroot}/waits.json", f"{lroot}/free.json"
        only5 = dict(bt, prs=[p for p in bt["prs"] if p["pr"] == 5])
        with open(waits, "w") as f:
            json.dump(only5, f)
        with open(free, "w") as f:
            json.dump(dict(only5, blocked=[]), f)
        (e, erows), (g, grows) = run(waits), run(free)
        check("v3 score: while history's check sat on a slot someone else held, the replay's waits it out too; "
              "without that wait it runs at once",
              num(erows, "s#5") is not None and num(erows, "s#5") >= 19.8 and num(grows, "s#5") is not None
              and num(grows, "s#5") < 2)
        # history's own admission, from the release its lanes switched to: one that keeps two slots under load
        rel = f"{lroot}/rels/abcdef1234567890/core/lander"
        os.makedirs(rel)
        open(f"{rel}/__init__.py", "w").close()
        with open(f"{rel}/admission.py", "w") as f:
            f.write("import os\nLOAD_FACTOR = 2\ndef slots_now(root, k, loadavg):\n"
                    "    return k if float(open(loadavg).read().split()[0]) < 2 * os.cpu_count() else 2\n")
        aq = f"{lroot}/land-admission"
        shutil.copytree(bq, aq)
        with open(f"{aq}/queue.log", "a") as f:
            f.write(L(-50, "lane-switch s 0123456789ab->abcdef123456: lane started")
                    + L(5000, "lane-switch s abcdef123456->fedcba987654: lane started"))
        adm_rows = lander_trace(f"{aq}/queue.log", aq, t0, t0 + 10000, rels=f"{lroot}/rels")["admission"]
        check("v3 extract: history's admission is the release its lanes switched to, asked for its slots (three calm, "
              "two at load); a release that can't be found keeps the old single slot under load",
              adm_rows == [[t0, 3, 2, 2.0], [t0 + 5000, 3, 1, 2.0]])
        two, one = f"{lroot}/adm-two.json", f"{lroot}/adm-one.json"
        loaded5 = dict(only5, load=[[t0 - 900, 10_000.0]])
        with open(two, "w") as f:
            json.dump(dict(loaded5, admission=[[t0, 3, 2, 2.0]]), f)
        with open(one, "w") as f:
            json.dump(dict(loaded5, admission=[[t0, 3, 1, 2.0]]), f)
        (_, trows), (_, orows) = run(two), run(one)
        check("v3 score: under load, a history wait fills as many slots as history's admission gave (two), so a "
              "candidate with two waits it out; read as the old single slot, it would run at once",
              (num(trows, "s#5") or 0) >= 19.8 and num(orows, "s#5") is not None and num(orows, "s#5") < 2)
        # what history's lane carried into the window, and a conflict gh named at intake
        iq = f"{lroot}/land-inflight"
        os.makedirs(f"{iq}/rest")
        with open(f"{iq}/queue.log", "w") as f:
            f.write("".join(sorted([
                L(-100, "queued u#1 who=x"), L(-99, "stage u#1 lane"), L(-98, "stage u#1 checking"),
                L(600, "stage u#1 gate gate=c1 ok=yes secs=600"), L(610, "stage u#1 merged sha=u1"),
                L(10, "queued u#2 who=x"), L(11, "stage u#2 lane"), L(12, "stage u#2 checking"),
                L(1210, "stage u#2 gate gate=c2 ok=yes secs=600"), L(1220, "stage u#2 merged sha=u2"),
                L(20, "queued u#3 who=x"), L(21, "stage u#3 lane"), L(21, "stage u#3 held"),
                L(1800, "requeued u#3 who=x"), L(1801, "stage u#3 lane"), L(1810, "stage u#3 merged sha=u3"),
            ])))
        for n, hist in ((1, []), (2, []), (3, [{"at": stamp(t0 + 21), "state": "held",
                                                 "why": "PR #3 conflicts with main — rebase it"}])):
            with open(f"{iq}/rest/u-{n}.json", "w") as f:
                json.dump({"repo": "u", "pr": n, "files": [f"u{n}.py"], "history": hist,
                           "plan": {"checks": [f"c{n}"] if n < 3 else [], "paid": False}}, f)
        it = dict(lander_trace(f"{iq}/queue.log", iq, t0, t0 + 4000), blocked=[])   # no slot waits: u#1 alone holds the slot
        both, alone = f"{lroot}/inflight.json", f"{lroot}/no-inflight.json"
        with open(both, "w") as f:
            json.dump(it, f)
        with open(alone, "w") as f:
            json.dump(dict(it, prs=[p for p in it["prs"] if p["pr"] != 1]), f)
        (h, hrows), (_, krows) = run(both, "--slots", "1"), run(alone, "--slots", "1")
        check("v3 score: a PR in the lane when the window opened holds the one slot as it did in history, so the next PR "
              "waits a check for it, and without it would not; it is never a row of the score",
              h.returncode == 0 and "u#1" not in hrows and (num(hrows, "u#2") or 0) >= 19.5
              and num(krows, "u#2") is not None and num(krows, "u#2") <= 11)
        check("…a conflict history met at its first look at a head holds that head from its start until the next one: "
              "it merges after the push, as in history, not at once",
              num(hrows, "u#3") is not None and 29 <= num(hrows, "u#3") <= 31.5)
        # leaving the lane, each way, and a member PR the door refused before it was queued
        vq = f"{lroot}/land-leave"
        os.makedirs(f"{vq}/rest")
        with open(f"{vq}/queue.log", "w") as f:
            f.write("".join(sorted([
                L(10, "queued v#1 who=x"), L(11, "stage v#1 lane"), L(12, "stage v#1 checking"),
                L(72, "stage v#1 gate gate=a ok=no secs=60"), L(73, "stage v#1 handback"),
                L(10, "queued v#2 who=x"), L(11, "stage v#2 lane"), L(20, "stage v#2 merged sha=v2"),
                L(30, "refused v#2 protected:core/x"),
                L(10, "queued v#3 who=x"), L(11, "stage v#3 lane"), L(40, "stage v#3 query"),
                L(900, "requeued v#3 who=x"), L(901, "stage v#3 lane"), L(950, "stage v#3 merged sha=v3"),
                L(0, "refused m--t#4 no-clone"), L(100, "refused m--t#4 no-clone"),
                L(1000, "queued m--t#4 who=x"), L(1001, "stage m--t#4 lane"), L(1010, "stage m--t#4 merged sha=m4"),
                L(200, "refused m--u#5 not-its-repository"), L(-5000, "refused m--w#7 no-token"),
                L(-5000, "refused m--x#8 no-clone"), L(300, "refused m--x#8 no-clone"),
            ])) + "garbage\trefused m--v#6 no-token\n")
        for n, checks in ((1, ["a"]), (2, []), (3, []), (4, [])):
            key = "m--t" if n == 4 else "v"
            with open(f"{vq}/rest/{key}-{n}.json", "w") as f:
                json.dump({"repo": key, "pr": n, "files": [f"v{n}.py"], "plan": {"checks": checks, "paid": False}}, f)
        vt = lander_trace(f"{vq}/queue.log", vq, t0, t0 + 4000)
        vby = {f"{p['repo']}#{p['pr']}": p for p in vt["prs"]}
        check("v3 extract: a PR leaves history's lane at its first handback, query or merge, whichever came first; "
              "a request after a query does not move it",
              vby["v#1"]["left"] == {"at": t0 + 73, "by": "handback"} and vby["v#2"]["left"] == {"at": t0 + 20, "by": "merged"}
              and vby["v#3"]["left"] == {"at": t0 + 40, "by": "query"})
        check("…a member PR refused before its first queued keeps its refusals and is ready at the first; one refused "
              "after it was queued keeps none",
              vby["m--t#4"]["refusals"] == [[t0, "no-clone"], [t0 + 100, "no-clone"]] and vby["m--t#4"]["ready"] == t0
              and "refusals" not in vby["v#2"] and "ready" not in vby["v#1"])
        check("…refused in the window and never queued is waiting, from its first refusal even before the window; one "
              "refused only before the window is not; an undated refusal is counted unreplayable",
              [(w["key"], w["ready"]) for w in vt["waiting"]] == [("m--u#5", t0 + 200), ("m--x#8", t0 - 5000)]
              and vt["undated"] == ["m--v#6"])
        rt = lander_trace(f"{vq}/queue.log", vq, t0, t0 + 4000, ready={"m--t#4": stamp(t0 - 500), "v#1": stamp(t0 - 900)})
        rby = {f"{p['repo']}#{p['pr']}": p for p in rt["prs"]}
        check("…a ready stamp given for a refused PR moves its ready time earlier; one for a PR never refused is unused",
              rby["m--t#4"]["ready"] == t0 - 500 and "ready" not in rby["v#1"])
        with open(f"{vq}/replay.log", "w") as f:
            f.write("".join(sorted([L(15, "stage v#1 query"), L(90, "stage v#1 merged sha=a"), L(50, "stage v#2 handback"),
                                    L(60, "stage v#3 merged sha=b"), L(2000, "stage m--t#4 merged sha=c")])))
        rleft = replay_numbers(rt, f"{vq}/replay.log")[4]
        check("v3 score: the replay's own log is read the same way: each leave kind, the first one only, and a refused "
              "PR's wait counted from its ready time",
              rleft == {"v#1": (5, "query"), "v#2": (40, "handback"), "v#3": (50, "merged"), "m--t#4": (2500, "merged")})
        with open(f"{vq}/parks.log", "w") as f:   # its own log: one park that ends at a stage line, one that never does
            f.write("".join(sorted([L(10, "stage v#1 parked on=2"), L(70, "stage v#1 planned"),
                                    L(100, "stage v#3 parked on=1"), L(120, "queued v#2 who=x")])))
        parks = replay_numbers(rt, f"{vq}/parks.log")[5]
        check("v3 score: each `stage … parked` is a park, and it lasts to the PR's next stage line, or to the window's end",
              parks == {"n": 2, "secs": 60 + 3900})
        import types as _types
        pa, pb, pc = ({"pr": 1, "files": ["a", "b"], "clean_with": [2]}, {"pr": 2, "files": ["b"], "clean_with": [1]},
                      {"pr": 3, "files": ["b", "c"], "clean_with": []})
        heads = {"h1": pa, "h2": pb, "h3": pc}
        w = _types.SimpleNamespace(repo_of=lambda root: "v", pr_of_head=lambda repo, h: heads.get(h))
        check("…a candidate's clash is answered from clean_with: none for a pair git merged cleanly, the shared files "
              "for one it did not, and a doubt for a head no PR had",
              LanderWorld.clash(w, "r", "h1", "h2") == [] and LanderWorld.clash(w, "r", "h1", "h3") == ["b"]
              and LanderWorld.clash(w, "r", "h1", "hx") == ["?"])
        leave = f"{lroot}/leave.json"
        with open(leave, "w") as f:
            json.dump(rt, f)
        v, vrows = run(leave)
        check("…and the report prints ready→left beside queued→merged: the refused PR waited from its ready stamp "
              "(25 min) in both, the handback left as one",
              v.returncode == 0 and "left the lane (ready→" in v.stdout and "2 refused and never queued" in v.stdout
              and "1 refusal(s) undated" in v.stdout and vrows.get("m--t#4", [""] * 5)[2] == "25.2"
              and num(vrows, "m--t#4", 3) is not None and num(vrows, "m--t#4", 3) >= 25.0
              and vrows.get("v#1", [""] * 5)[4] == "handback/handback" and "waiting" in vrows and "unreplayable" in vrows)
        if v.returncode:
            print("    " + (v.stderr.strip().splitlines() or ["(no stderr)"])[-1])
    finally:
        os.environ.pop("CC_REPLAY_SYSSTAT", None)
        shutil.rmtree(lroot, ignore_errors=True)
    print(f"cc-replay selfcheck: {len(fails)} failed")
    return 1 if fails else 0
