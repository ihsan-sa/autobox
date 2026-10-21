# cc-scope's selfcheck: the cases behind `cc-scope selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-scope execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

# ---- selfcheck -------------------------------------------------------------------------------------
def selfcheck():
    global SCOPE, DEV
    import tempfile, shutil, io
    SCOPE = tempfile.mkdtemp(prefix="cc-scope-selfcheck-")
    DEV = os.path.join(SCOPE, "dev")   # the checkouts the gone cases read: nothing under ~/dev is touched
    _fl = os.environ.get("CC_FAILURES")
    os.environ["CC_FAILURES"] = os.path.join(SCOPE, "failures")   # the deliver cases below write records: a scratch ledger, never the box's own
    def ledger(repo):
        r = subprocess.run([os.path.join(os.path.dirname(os.path.realpath(__file__)), "cc-failures"), "show", "--json", "--scope", repo],
                           capture_output=True, text=True)
        return [x for x in (json.loads(r.stdout or "[]")) if x.get("kind") == "delivery/merged-not-delivered"]
    p = f = 0
    def ok(n): nonlocal p; p += 1; print("  ✓ %s" % n)
    def bad(n): nonlocal f; f += 1; print("  ✗ %s" % n)
    def t(n, cond): ok(n) if cond else bad(n)
    try:
        R = "_scopetest"
        # A check runs with this file's own bin dir on PATH, so a row may name a sibling tool plainly (review of
        # the rc=127 landings, 2026-09-02): scrub PATH entirely and a bare sibling name still resolves.
        _sib = os.path.basename(os.path.realpath(__file__))
        _keep = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = ""
            t("a check finds this file's siblings on PATH even when PATH is empty",
              run_check(R, {"check": "command -v %s >/dev/null" % _sib})[0] == 0)
            t("and a name that is not a sibling still fails, so PATH is prepended and not replaced",
              run_check(R, {"check": "command -v definitely-not-a-tool-xyz >/dev/null"})[0] != 0)
        finally:
            os.environ["PATH"] = _keep
        t("a compound ask keeps both parts",
          len(parts_of("react with :ok_hand: in #approvals. this should also remove it from the board.")) == 2)
        # An ack can OPEN a real instruction, and the whole sentence is what is kept — ack and all.
        miss = "Ok well do whatever you need to speed up the whole landing and review process"
        t("a directive behind an acknowledgement is kept whole", parts_of(miss) == [miss])
        t("...while an ack that only compliments carries no directive at all",
          parts_of("ok cool, thanks a lot") == [])

        a1, rep = add(R, "make the digest show open asks", src="slack #demo 1788")
        t("add opens an ask", a1 == "a1" and not rep)
        a2, rep = add(R, "Make the digest   show open ASKS!", src="slack #demo 1799")
        t("the same ask twice is one row with repeats=2", a2 == a1 and rep and get(R, a1)["repeats"] == 2)
        t("check exits 1 while an ask is unsettled", quiet(["check", R]) == 1)
        quiet(["claim", R, a1, "--track", "digest"])
        t("a claimed ask is still work", get(R, a1)["status"] == "claimed" and quiet(["check", R]) == 1)

        # ---- MERGED IS NOT DELIVERED -------------------------------------------------------------------
        # The failure this whole section exists for: rows were closed on "merged as PR #N" while the daemon
        # still ran the old code, and the owner was the one who found out. A merge is now its own state, it
        # is not settled, and the only thing that moves a row past it is a command exiting 0.
        try:
            quiet(["merged", R, a1]); bad("merged without evidence is refused")
        except SystemExit as e: t("merged without evidence is refused", "evidence" in str(e))
        quiet(["merged", R, a1, "--evidence", "PR #64"])
        t("a MERGED ask is still work — a PR number is not delivery",
          get(R, a1)["status"] == "merged" and quiet(["check", R]) == 1)
        t("the line you read says so, in as many words",
          "NOT delivered" in run_capture(["list", R]) and "names no check" in run_capture(["list", R]))
        t("a merged ask with no check is listed as unverified and stays open",
          quiet(["unverified", R]) == 1 and "names no check" in run_capture(["unverified", R])
          and get(R, a1)["status"] == "merged")

        # a row with NO check cannot be delivered at all: exit 2, and it does not move
        t("deliver on a row that names no check is refused (exit 2) and the row does not move",
          quiet(["deliver", R, a1]) == 2 and get(R, a1)["status"] == "merged")

        # a check that FAILS cannot reach delivered, however many times it is run
        quiet(["check-cmd", R, a1, "exit 3"])
        t("a row whose check fails is NOT delivered and stays exactly where it was",
          quiet(["deliver", R, a1]) == 1 and get(R, a1)["status"] == "merged"
          and get(R, a1)["checked"]["rc"] == 3)
        t("the failure is written next to the ask, not swallowed",
          any("check FAILED" in n["msg"] for n in get(R, a1)["notes"]))
        # …AND TO THE FAILURES LEDGER, by this runner, once: "a merged fix still fails its check" is a failure of its own
        # (delivery/merged-not-delivered), keyed to the ask and the merge, so a second tick on the same red writes nothing.
        led = ledger(R)
        t("a merged ask whose check fails is recorded in the failures ledger as delivery/merged-not-delivered, by cc-scope",
          len(led) == 1 and led[0]["writer"] == "cc-scope" and led[0]["links"].get("ask") == a1
          and led[0]["links"]["source"].startswith("scope-deliver:%s:%s:" % (R, a1)) and "rc 3" in led[0]["observed"])
        quiet(["deliver", R, a1]); quiet(["deliver", R, a1])
        t("…once, not once per check tick: two more ticks on the same red leave one record", len(ledger(R)) == 1)
        RL = R + "-long"   # its own ledger: a long ask keeps an excerpt and points at the message for the rest
        essay = "make the digest say " + " ".join(f"point {i}" for i in range(300))
        al, _ = add(RL, essay, src="slack:C1/1700000000.000100")
        la = get(RL, al)
        t("a long ask keeps a bounded excerpt, its length and the message it came from",
          len(essay) > 2000 and len(la["text"]) <= EXCERPT + 1 and essay.startswith(la["text"].rstrip("…"))
          and la["chars"] == len(essay) and la["src"] == "slack:C1/1700000000.000100")
        t("…and two long asks that part only after the excerpt stay two rows",
          add(RL, essay + " and one more point")[0] != al and add(RL, essay) == (al, True))
        bare = "and with no source given " + essay
        ab, _ = add(RL, bare)
        t("a long ask added with no --src keeps its whole text beside the ledger, and show names the file",
          not get(RL, ab)["src"] and open(full_path(RL, ab)).read().strip() == bare
          and full_path(RL, ab) in run_capture(["show", RL, ab]))
        os.remove(full_path(RL, ab))   # as a row from before the side file was
        t("a long row with no side file says it predates it in show, and asking it again writes the file",
          "predates" in run_capture(["show", RL, ab]) and add(RL, bare) == (ab, True)
          and open(full_path(RL, ab)).read().strip() == bare)
        R3 = R + "-ctl"   # its own ledger: an unsettled row left here would be work the cases below count
        a3, _ = add(R3, "a claimed ask whose check is red")
        quiet(["claim", R3, a3, "--track", "t3"]); quiet(["check-cmd", R3, a3, "exit 1"])
        t("control: a CLAIMED ask whose check fails is red but not merged, so it is not a merged-not-delivered record",
          quiet(["deliver", R3, a3]) == 1 and not ledger(R3))
        _ro = os.path.join(SCOPE, "ro"); os.makedirs(_ro); os.chmod(_ro, 0o500)
        _keepfl = os.environ["CC_FAILURES"]; os.environ["CC_FAILURES"] = os.path.join(_ro, "failures")
        try:
            _rc, err = run_capture_err(["deliver", R, a1])
            t("a writer failure (the ledger unwritable) leaves the verdict unchanged: still exit 1, still merged, one 'not recorded' line",
              _rc == 1 and get(R, a1)["status"] == "merged" and "failures ledger (%s): not recorded" % R in err)
        finally:
            os.chmod(_ro, 0o700); os.environ["CC_FAILURES"] = _keepfl
        try:
            quiet(["verify", R, a1, "--evidence", "I looked and it is fine, honestly"])
            bad("a red check cannot be talked round with a sentence")
        except SystemExit as e:
            t("a red check cannot be talked round with a sentence", "has not passed" in str(e))
        t("...and the row is still not settled", get(R, a1)["status"] == "merged" and quiet(["check", R]) == 1)

        # and a check that PASSES is what delivery means
        quiet(["check-cmd", R, a1, "true", "--replace", "exit 3 was the red case above"])
        t("a check that passes is what makes a row delivered",
          quiet(["deliver", R, a1]) == 0 and get(R, a1)["status"] == "delivered")
        t("the evidence is the check itself, not a sentence about it",
          "check passed: true" in get(R, a1)["evidence"])
        t("a delivered ask is settled: it stops being work", quiet(["check", R]) == 0)
        t("a delivered ask is not unverified", quiet(["unverified", R]) == 0)
        t("re-running deliver is a no-op — same state, still delivered",
          quiet(["deliver", R, a1]) == 0 and get(R, a1)["status"] == "delivered")
        t("re-marking it merged does not drag a delivered row backwards",
          quiet(["merged", R, a1, "--evidence", "PR #64 again"]) == 0 and get(R, a1)["status"] == "delivered")

        # the by-hand path, for the ask no command can measure — it is a PERSON's word and it is marked as one
        a2b, _ = add(R, "make the tone of the updates warmer")
        t("an ask with no possible check still cannot be delivered", quiet(["deliver", R, a2b]) == 2)
        quiet(["verify", R, a2b, "--evidence", "read the last six updates in the channel myself"])
        t("a person may close what no command can measure", get(R, a2b)["status"] == "verified")
        t("...and it is still counted as never measured",
          quiet(["unverified", R]) == 1 and "closed by hand" in run_capture(["unverified", R]))

        # A row written before any of this existed sits in `delivered` on a sentence. Reading it as settled
        # now — same word, new meaning — would close it without anything ever having been measured, which is
        # this bug wearing the fix's clothes. It goes back on the queue.
        with Lock(R):
            d = load(R); d["asks"][a1] = dict(d["asks"][a1], status="delivered", checked={},
                                              evidence="merged as PR #64 on main; deployed"); save(R, d)
        t("a row closed on a sentence before checks existed is NOT settled by the word 'delivered'",
          quiet(["check", R]) == 1 and a1 in run_capture(["list", R]))
        t("it says why, on the line you read", "back on the queue" in run_capture(["list", R]))
        t("and it is reported unverified, with the sentence it was closed on",
          quiet(["unverified", R]) == 1 and "closed on a sentence" in run_capture(["unverified", R]))
        quiet(["check-cmd", R, a1, "true", "--replace", "same check, re-registered"]); quiet(["deliver", R, a1])
        t("giving it a check that passes is what settles it", quiet(["check", R]) == 0)

        a3, _ = add(R, "rewrite the whole box in rust")
        try:
            quiet(["verify", R, a3]); bad("verify without any evidence is refused")
        except SystemExit as e: t("verify without any evidence is refused", "evidence" in str(e))

        # A decline is a DECISION: it needs a reason, it leaves the queue, and it stays in the ledger.
        try:
            quiet(["decline", R, a3]); bad("decline without a reason is refused")
        except SystemExit as e: t("decline without a reason is refused", "why" in str(e))
        quiet(["decline", R, a3, "--why", "no reader would gain anything and the box would be down for a week"])
        t("a declined ask stops counting as work", quiet(["check", R]) == 0)
        t("a declined ask stays in the ledger with its reason",
          get(R, a3)["status"] == "declined" and "down for a week" in get(R, a3)["reason"])
        t("the reason is on the line you actually read",
          "down for a week" in run_capture(["list", R, "--status", "declined"]))
        t("a declined ask is not hidden by --all", a3 in run_capture(["list", R, "--all"]))

        t("a replay matches any status and changes nothing",
          add(R, "make the digest show open asks", replay=True) == (a1, True) and get(R, a1)["repeats"] == 2)
        t("a check is carried on the row from the moment it is opened",
          get(R, add(R, "keep the tmux server up", check="test -d /")[0])["check"] == "test -d /")
        quiet(["decline", R, a3, "--why", "still no"]) if get(R, a3)["status"] != "declined" else None
        a4, rep4 = add(R, "rewrite the whole box in rust")
        t("asked again after a decline, it is back on the queue with the reason kept",
          a4 == a3 and rep4 and get(R, a3)["status"] == "open" and "down for a week" in get(R, a3)["reason"])
        quiet(["decline", R, a3, "--why", "same answer as before"])
        a5, rep5 = add(R, "make the digest show open asks")
        t("asked again after it was delivered, it is a NEW row — that is a regression, not a repeat",
          a5 != a1 and not rep5)
        quiet(["decline", R, a5, "--why", "fixture"])

        add(R, "always run the gates before a PR", track="gates")
        t("check --track only measures that track's asks", quiet(["check", R, "--track", "nope"]) == 0)
        t("check --track sees its own", quiet(["check", R, "--track", "gates"]) == 1)

        # ---- A CHECK THAT CANNOT RUN IS NOT A CHECK THAT FAILED -----------------------------------------
        # a69's boundary check was a script in its track's state dir. The track finished, the dir went with
        # it, and the row read "merged, NOT delivered — its check has not passed" for five days while nobody
        # had measured anything at all. The two cases below are that pair; they must never read alike again.
        aC, _ = add(R, "prove the workspace boundary holds from inside")
        quiet(["merged", R, aC, "--evidence", "PR #156"])
        quiet(["check-cmd", R, aC, "exit 3"])
        t("a check that RAN and said no is a FAILURE: exit 1, written on the row as one",
          quiet(["deliver", R, aC]) == 1 and get(R, aC)["checked"]["rc"] == 3
          and any("check FAILED" in n["msg"] for n in get(R, aC)["notes"]))
        t("...and the line you read says the check has not passed",
          "its check has not passed" in run_capture(["list", R]))
        gone = os.path.join(HOME, ".cc", "scope", CHECKS, "_selfcheck-no-such-check.sh")
        quiet(["check-cmd", R, aC, "bash %s" % gone, "--replace", "the cannot-run case"])
        t("a check that CANNOT RUN is a different answer: exit 3, not the 1 a real failure gets",
          quiet(["deliver", R, aC]) == 3 and get(R, aC)["checked"]["rc"] in CANNOT_RUN)
        t("...and the row says no answer, not failure",
          any("COULD NOT RUN" in n["msg"] for n in get(R, aC)["notes"])
          and not any("check FAILED (rc 127" in n["msg"] for n in get(R, aC)["notes"]))
        t("...and so does every line a person reads: list, unverified, show",
          "CANNOT RUN" in run_capture(["list", R])
          and "NEVER MEASURED" in run_capture(["unverified", R])
          and "COULD NOT RUN" in run_capture(["show", R, aC]))
        t("...and no answer still never delivers a row",
          get(R, aC)["status"] == "merged" and quiet(["check", R]) == 1)

        # ---- THE ADVICE MUST FIT THE REASON, NOT JUST THE CODE -------------------------------------------
        # CANNOT_RUN has two real causes and #297 only wrote advice for one: `gone` above is a script that
        # truly vanished, and pointing the reader at "give it a command that is there" is correct for it. But
        # a check can run PERFECTLY and choose rc 126/127 itself to say it could not measure something (the
        # rebuilt member boundary check, 2026-09-07) — the interpreter never failed to find it, so telling the
        # reader their command is missing sends them to fix a path that was never broken.
        rc, out = run_capture_err(["deliver", R, aC])   # aC's check is still `bash <gone>` from just above
        t("the vanished-script cause still gets told to give it a command that is there",
          rc == 3 and "give it a command that is there" in out.lower())
        quiet(["check-cmd", R, aC, "echo could not start 2 of 5, nothing failed >&2; exit 126", "--replace", "chosen 126"])
        rc2, out2 = run_capture_err(["deliver", R, aC])
        t("a check that RAN and chose CANNOT_RUN itself is still read as no answer, not a failure",
          rc2 == 3 and get(R, aC)["checked"]["rc"] == 126)
        t("...but it is NOT told its command is missing — that diagnosis does not fit what happened",
          "give it a command" not in out2.lower())
        t("...it is pointed at the check's own output and at re-running the SAME check",
          "read what it printed" in out2.lower() and "cc-scope deliver %s %s" % (R, aC) in out2)

        # The other half: a check must outlive the track that wrote it, and a check that goes missing must
        # not drag a row that already PASSED back onto the queue — that is this bug pointing the other way.
        src = os.path.join(SCOPE, "_a-track", "boundary-check.sh")
        os.makedirs(os.path.dirname(src), exist_ok=True)
        with open(src, "w") as fh: fh.write("exit 0\n")
        aD, _ = add(R, "prove the tab renders the block")
        quiet(["merged", R, aD, "--evidence", "PR #200"])
        quiet(["check-cmd", R, aD, "--script", src])
        kept = get(R, aD)["check"].split()[1]
        t("--script keeps the script beside the LEDGER, not in the track that wrote it",
          os.path.dirname(kept) == check_dir() and os.path.isfile(kept))
        t("and a row delivers from there", quiet(["deliver", R, aD]) == 0)
        shutil.rmtree(os.path.dirname(src))          # the track ends and the janitor takes its dir
        t("...and the check still runs after the track's own directory is gone",
          quiet(["deliver", R, aD]) == 0 and get(R, aD)["status"] == "delivered")
        os.remove(kept)                              # and now the check itself is unreachable
        t("a check that has gone missing does NOT un-deliver a row that already passed",
          quiet(["deliver", R, aD]) == 3 and get(R, aD)["status"] == "delivered" and passed(get(R, aD)))

        aE, _ = add(R, "prove the member boundary")
        doomed_cmd = "bash %s/.cc/state/%s/some-track/boundary-check.sh" % (HOME, R)
        try:
            quiet(["check-cmd", R, aE, doomed_cmd]); bad("a check run out of a track's state dir is refused")
        except SystemExit as e:
            t("a check run out of a track's state dir is refused, and says where to put it instead",
              "--script" in str(e))
        t("...but the SAME path merely looked at is not refused — 'the janitor took it' is a real check",
          quiet(["check-cmd", R, aE, "test ! -f %s/.cc/state/%s/some-track/boundary-check.sh" % (HOME, R)]) == 0)
        t("...and running a script that merely takes a temp path as an argument is not refused either",
          quiet(["check-cmd", R, aE, "bash install.sh /tmp/out.log", "--replace", "a temp path as an argument"]) == 0)
        # …and `add --check` is the SAME door: it was open while check-cmd's was shut, which is a documented
        # way to write exactly the row this refusal exists to prevent (review of #297).
        try:
            quiet(["add", R, "another ask", "--check", doomed_cmd]); bad("add --check is refused too")
        except SystemExit as e:
            t("a doomed check given at `add --check` is refused the same way check-cmd's is", "--script" in str(e))
        # ASSERT THE CHECK LANDED, not that the call returned an int — the first spelling of this case was
        # `isinstance(quiet([...]), int)`, which quiet() satisfies unconditionally, and it is why a bug that
        # dropped --check on the floor shipped green (review of #297).
        fine = "test -f /etc/hostname"
        newid = run_capture(["add", R, "an ask with a fine check", "--check", fine]).split()[1]
        t("...and an ordinary check at `add --check` is still what ends up ON the row",
          get(R, newid).get("check") == fine)

        # ---- A CHECK IS NOT REPLACED IN SILENCE ---------------------------------------------------------
        # a342 (2026-09-12): a settler wrote over a live check with a selftest it never compared to the one
        # there, and `deliver` passed the ask on a fixture.
        aF, _ = add(R, "prove the member send reached the mail log")
        t("a first check-cmd on a row is not refused", quiet(["check-cmd", R, aF, "grep -q sent /dev/null"]) == 0)
        try:
            quiet(["check-cmd", R, aF, "true"]); bad("replacing a check without --replace is refused")
        except SystemExit as e:
            t("replacing a check without --replace is refused, prints the check that is there, and keeps it",
              "grep -q sent /dev/null" in str(e) and "--replace" in str(e) and get(R, aF)["check"] == "grep -q sent /dev/null")
        try:
            quiet(["check-cmd", R, aF, "true", "--replace", " "]); bad("--replace with no reason is refused")
        except SystemExit:
            t("--replace with no reason is refused too", get(R, aF)["check"] == "grep -q sent /dev/null")
        t("--replace with a reason replaces it, and the old check and the reason are kept in the notes",
          quiet(["check-cmd", R, aF, "true", "--replace", "the log moved"]) == 0 and get(R, aF)["check"] == "true"
          and any("the log moved" in n["msg"] and "grep -q sent" in n["msg"] for n in get(R, aF)["notes"]))
        live, fixture = os.path.join(SCOPE, "_orch", "live.sh"), os.path.join(SCOPE, "_settler", "fixture.sh")
        for fp_, body_ in ((live, "# reads the live mail log\nexit 0\n"), (fixture, "# runs a selftest\nexit 0\n")):
            os.makedirs(os.path.dirname(fp_), exist_ok=True)
            with open(fp_, "w") as fh: fh.write(body_)
        aG, _ = add(R, "prove the live send")
        quiet(["check-cmd", R, aG, "--script", live])
        instG = get(R, aG)["check"].split()[1]
        try:
            quiet(["check-cmd", R, aG, "--script", fixture]); bad("a --script over an installed check is refused")
        except SystemExit as e:
            t("a --script over an installed check is refused, prints the script's body, and copies nothing over it",
              "reads the live mail log" in str(e) and "reads the live mail log" in open(instG).read())
        # an installed script edited in place, by a Write tool and not check-cmd, is not run by deliver
        aI, _ = add(R, "prove the live send, untouched")
        quiet(["check-cmd", R, aI, "--script", live])
        t("an installed script nobody edited delivers", quiet(["deliver", R, aI]) == 0)
        aH, _ = add(R, "prove the live send, edited")
        quiet(["check-cmd", R, aH, "--script", live])
        instH = get(R, aH)["check"].split()[1]
        with open(instH, "w") as fh: fh.write("# runs a selftest\nexit 0\n")
        rc, out = run_capture_err(["deliver", R, aH])
        t("a script edited in place after registration is not run: exit 3, it says so and shows the script",
          rc == 3 and "fingerprinted" in out and "runs a selftest" in out
          and get(R, aH)["status"] == "open" and not get(R, aH)["checked"])
        t("...and registering it as it is now, with a reason, is what lets it deliver (--script may name itself)",
          quiet(["check-cmd", R, aH, "--script", instH, "--replace", "read it; the selftest is right"]) == 0
          and quiet(["deliver", R, aH]) == 0)
        aJ, _ = add(R, "prove the live send, via add", check="bash %s" % instG)
        t("a check given at add is fingerprinted too, so it delivers", quiet(["deliver", R, aJ]) == 0)
        with Lock(R):
            d = load(R); d["asks"][aJ].pop("check_files"); save(R, d)
        t("a row from before fingerprints that runs a script under checks/ is not run either",
          quiet(["deliver", R, aJ]) == 3)

        # `hook` is a no-op now: it drains its payload, says nothing and exits 0, whatever it is given.
        _stdin, _ledgers = sys.stdin, repos()
        try:
            sys.stdin = io.StringIO(json.dumps({"prompt": "add the ask count to the tab", "cwd": SCOPE}))
            hrc, hout = run_capture_err(["hook"])
        finally:
            sys.stdin = _stdin
        t("hook is a silent no-op: it prints nothing, exits 0 and opens no row",
          hrc == 0 and hout == "" and repos() == _ledgers and not os.path.exists(path("box")))


        # ---- A CHECK THAT READS WHAT THE TREE NO LONGER HAS (the header's third cause) ----------------------
        # Its own checkout: two tools, one deleted in a squash commit; its own ledger row per case.
        G = "_scopegone"
        gsrc = os.path.join(DEV, G)
        os.makedirs(os.path.join(gsrc, "core", "bin"))
        def ggit(*a_):
            return subprocess.run(["git", "-C", gsrc, *a_], capture_output=True, text=True,
                                  env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        subprocess.run(["git", "init", "-q", "-b", "main", gsrc], capture_output=True)
        for fn in ("cc-old", "cc-kept"):
            open(os.path.join(gsrc, "core", "bin", fn), "w").write("#!/bin/sh\n")
        ggit("add", "-A"); ggit("commit", "-qm", "base")
        ggit("rm", "-q", "core/bin/cc-old"); ggit("commit", "-qm", "the old tool goes (#12)")
        def gone_row(text, check):
            aid, _ = add(G, text, check=check)
            quiet(["merged", G, aid, "--evidence", "PR #12"])
            return aid
        aK = gone_row("the old tool answers in one line", "test -x core/bin/cc-old")
        rcK, outK = run_capture_err(["deliver", G, aK])
        t("a failing check naming a path the tree no longer has is NO ANSWER: exit 3, the path and the deleting commit",
          rcK == 3 and "NO ANSWER" in outK and "core/bin/cc-old" in outK and "(#12)" in outK and "git show" in outK)
        t("...and the row says so, not 'failed': the record carries what is gone and stays merged",
          get(G, aK)["status"] == "merged" and get(G, aK)["checked"].get("gone")
          and any("reads what the tree no longer has" in n["msg"] for n in get(G, aK)["notes"])
          and not any("check FAILED" in n["msg"] for n in get(G, aK)["notes"]))
        t("...on every line a person reads: list, unverified, show",
          "reads what the tree no longer has" in run_capture(["list", G])
          and "reads what the tree no longer has" in run_capture(["unverified", G])
          and "reads what the tree no longer has" in run_capture(["show", G, aK]))
        t("...and it is not written to the failures ledger — nothing was measured",
          not any(x.get("links", {}).get("ask") == aK for x in ledger(G)))
        aL = gone_row("the steward ran since the ask", "test -s ~/.cc/state/old/runs.jsonl")
        rcL, outL = run_capture_err(["deliver", G, aL])
        t("a check reading ~/.cc/state/<name>/ is read as the ledger cc-<name> kept, and that tool's deletion is named",
          rcL == 3 and "the ledger cc-old kept" in outL and "(#12)" in outL)
        aM = gone_row("the kept tool is executable", "test -d core/bin/cc-kept")
        t("a failing check naming a tool that IS there is a plain failure: exit 1",
          quiet(["deliver", G, aM]) == 1 and not get(G, aM)["checked"].get("gone"))
        aN = gone_row("a tool nobody wrote yet", "test -x core/bin/cc-never")
        t("a name git never had is not gone, it was never there — a plain failure too", quiet(["deliver", G, aN]) == 1)
        aO = gone_row("the old tool is really gone", "test ! -e core/bin/cc-old")
        t("a check that PASSES is never second-guessed, whatever it names", quiet(["deliver", G, aO]) == 0
          and get(G, aO)["status"] == "delivered")

        n = int(run_capture(["count", R]))
        t("count is the number of unsettled asks", n == len(select(R)))
        t("digest says nothing when nothing is open", run_capture(["digest", "_empty"]).strip() == "")
    finally:
        shutil.rmtree(SCOPE, ignore_errors=True)
        if _fl is None: os.environ.pop("CC_FAILURES", None)
        else: os.environ["CC_FAILURES"] = _fl
    print("== cc-scope selfcheck: %d passed, %d failed ==" % (p, f))
    return 1 if f else 0
