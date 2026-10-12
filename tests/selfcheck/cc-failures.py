# cc-failures's selfcheck: the cases behind `cc-failures selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-failures execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    n = f = 0
    def ok(what, cond):
        nonlocal n, f
        n += 1
        if not cond: f += 1
        print(("  ok   " if cond else "  FAIL ") + what)
    T = tempfile.mkdtemp(prefix="cc-failures-sc.")
    home = os.path.join(T, "home"); os.makedirs(os.path.join(home, ".cc", "boards"))
    env = dict(os.environ, HOME=home, CC_FAILURES=os.path.join(T, "failures"), CC_STATE=os.path.join(T, "state"))
    def C(*a, rc=0, inp=None):
        p = subprocess.run([os.path.join(B, "cc-failures"), *a], capture_output=True, text=True, env=env, input=inp)
        return p.returncode, p.stdout, p.stderr
    ledger = lambda s: open(os.path.join(T, "failures", f"{s}.jsonl")).read() if os.path.isfile(os.path.join(T, "failures", f"{s}.jsonl")) else ""
    lines = lambda s: [json.loads(l) for l in ledger(s).splitlines() if l.strip()]
    K = "guard-policy/permitted-text-refused"
    try:
        print("cc-failures selfcheck")
        # ---- record
        rc, out, err = C("record", "--scope", "alpha", "--kind", K, "--observed", "a grep pattern was refused", "--writer", "t")
        ok("record writes one line and prints its id", rc == 0 and out.startswith("f-") and len(lines("alpha")) == 1)
        rid = out.split()[0]
        r = lines("alpha")[0]
        ok("…the line carries every field the record names", all(k in r for k in ("ts", "filed", "scope", "kind", "fingerprint", "cluster", "expected", "observed", "evidence", "detector", "writer", "cost", "links", "status", "critical")) and r["id"] == rid and r["status"] == "confirmed")
        rc, out, err = C("record", "--scope", "alpha", "--observed", "no kind")
        ok("…no kind: refused, rc 2, nothing written", rc == 2 and len(lines("alpha")) == 1)
        rc, out, err = C("record", "--scope", "../alpha", "--kind", K, "--observed", "x")
        ok("…a scope that is a path, not a name: refused", rc == 2 and "scope is a" in err and not os.path.exists(os.path.join(T, "alpha.jsonl")))
        rc, out, err = C("record", "--scope", "alpha", "--kind", "nosymptom", "--observed", "x")
        ok("…a kind that is not contract/symptom: refused", rc == 2 and len(lines("alpha")) == 1)
        rc, out, err = C("record", "--scope", "alpha", "--kind", K, "--observed", "x", "--critical", "sideways")
        ok("…a critical reason the catalogue does not list: refused", rc == 2 and "critical is one of" in err and len(lines("alpha")) == 1)
        rc, out, err = C("record", "--scope", "alpha", "--kind", "fresh/never-seen", "--observed", "x")
        ok("a kind outside the catalogue is written, and said", rc == 0 and "not in the catalogue" in err and lines("alpha")[-1]["kind"] == "fresh/never-seen")
        before = len(lines("alpha"))
        rc, out, err = C("record", "--scope", "alpha", "--kind", K, "--observed", "the owner pointed at it", "--detector", "person", "--detector-evidence", "thread")
        ls = lines("alpha")
        ok("detector person: the record AND a person-first gap record, critical, linked to it", rc == 0 and len(ls) == before + 2
           and ls[-1]["kind"] == GAP_KIND and ls[-1]["critical"] == "person-first" and ls[-1]["links"].get("episode") == ls[-2]["id"] and ls[-2]["critical"] == "")
        before = len(lines("alpha"))
        C("record", "--scope", "alpha", "--kind", K, "--observed", "seen by a script", "--detector", "box")
        ok("…detector box: one record, no gap record", len(lines("alpha")) == before + 1)
        # ---- no --detector: the review's person-first test runs on --observed; each case on a scope of its own
        rc, out, err = C("record", "--scope", "dflt", "--kind", K, "--observed", "the owner found it on the second run")
        dl = lines("dflt")
        ok("defaulted→person: no --detector and the observed says the owner found it: person, the phrase as evidence, and the gap record",
           rc == 0 and dl[0]["detector"] == {"who": "person", "evidence": "owner found"} and len(dl) == 2 and dl[-1]["kind"] == GAP_KIND)
        rc, out, err = C("record", "--scope", "expl", "--kind", K, "--observed", "the owner found it", "--detector", "unknown")
        el = lines("expl")
        ok("explicit --detector unknown is kept, though the observed says the owner found it", rc == 0 and len(el) == 1 and el[0]["detector"] == {"who": "unknown", "evidence": ""})
        rc, out, err = C("record", "--scope", "nomatch", "--kind", K, "--observed", "a grep pattern was refused")
        ol = lines("nomatch")
        ok("no match→unknown: no --detector and no person in the observed: unknown, with no evidence", rc == 0 and len(ol) == 1 and ol[0]["detector"] == {"who": "unknown", "evidence": ""})
        rc, out, err = C("record", "--scope", "alpha", "--kind", K, "--observed", "", "--cost", "turns=1", "--link", "pr=7")
        ok("an empty observed is refused", rc == 2)
        rc, out, err = C("record", "--scope", "alpha", "--kind", K, "--observed", "x", "--cost", "turns=1", "--cost", "owner=one line", "--link", "pr=7", "--evidence", "a", "--evidence", "b", "--ts", "2026-09-01T10:00Z")
        r = lines("alpha")[-1]
        ok("cost, links, evidence and --ts are stored as given", r["cost"] == ["turns=1", "owner=one line"] and r["links"] == {"pr": "7"} and r["evidence"] == ["a", "b"] and r["ts"] == "2026-09-01T10:00:00Z")
        # ---- --once: one record per links.source, on a scope of its own
        rc1, out1, _ = C("record", "--scope", "once", "--kind", K, "--observed", "x", "--link", "source=k:1", "--once")
        rc2, out2, _ = C("record", "--scope", "once", "--kind", K, "--observed", "x again", "--link", "source=k:1", "--once")
        rc3, out3, _ = C("record", "--scope", "once", "--kind", K, "--observed", "y", "--link", "source=k:2", "--once")
        ok("--once writes the first record of a source, and a second with that source writes nothing and names the first",
           rc1 == rc2 == rc3 == 0 and out2.strip() == f"already {out1.split()[0]}" and out3.startswith("f-")
           and [r["links"]["source"] for r in lines("once")] == ["k:1", "k:2"])
        rc, out, err = C("record", "--scope", "once", "--kind", K, "--observed", "z", "--once")
        ok("…--once with no source is refused, nothing written", rc == 2 and "--once needs" in err and len(lines("once")) == 2)
        # ---- corrections append; the original line is untouched
        raw = ledger("alpha")
        rc, out, err = C("record", "--scope", "alpha", "--kind", K, "--observed", "was a correct refusal", "--corrects", rid, "--status", "refuted")
        ok("a correction is appended, the original bytes are untouched, and the read folds it in", rc == 0 and ledger("alpha").startswith(raw)
           and next(x for x in load_in(env, "alpha") if x["id"] == rid)["status"] == "refuted")
        rc, out, err = C("record", "--scope", "alpha", "--kind", K, "--observed", "x", "--corrects", rid)
        ok("…a correction without a status is refused", rc == 2)
        rc, out, err = C("record", "--scope", "alpha", "--kind", K, "--observed", "x", "--corrects", "f-nope", "--status", "refuted")
        ok("…a correction of an id the ledger does not hold is refused", rc == 2)
        # ---- eligible: the rule, on its own scope
        def rec(scope, ts, kind=K, **kw):
            a = ["record", "--scope", scope, "--kind", kind, "--observed", "o", "--ts", ts]
            for k, v in kw.items(): a += [f"--{k}", v]
            return C(*a)
        elig = lambda *a: [l.split()[0] for l in C("eligible", *a)[1].splitlines() if l.strip()]
        cid = fpid(fingerprint("beta", K))
        rec("beta", "2026-09-01T10:00Z"); rec("beta", "2026-09-03T10:00Z")
        ok("two episodes in 14 days: not eligible", elig("--scope", "beta", "--as-of", "2026-09-04T00:00Z") == [])
        rec("beta", "2026-09-03T10:20Z")
        ok("…a third record 20 minutes after the second is the SAME episode: still not eligible", elig("--scope", "beta", "--as-of", "2026-09-04T00:00Z") == [])
        rec("delta", "2026-09-03T10:00Z"); rec("delta", "2026-09-03T10:29Z"); rec("delta", "2026-09-03T10:59Z")
        ok("the edge: 29 minutes after the last record is the same episode, 30 exactly is a new one", "2 episode(s)" in C("show", "--scope", "delta", "--as-of", "2026-09-04T00:00Z")[1])
        rec("beta", "2026-09-05T10:00Z")
        ok("a third distinct episode: eligible, and eligible prints the cluster id first on its line", elig("--scope", "beta", "--as-of", "2026-09-06T00:00Z") == [cid])
        ok("…--as-of before the third episode: not eligible", elig("--scope", "beta", "--as-of", "2026-09-04T12:00Z") == [])
        ok("…--as-of fifteen days after the first: two in the window, not eligible", elig("--scope", "beta", "--as-of", "2026-09-16T12:00Z") == [])
        rc, out, _ = C("show", "--scope", "beta", "--as-of", "2026-09-30T00:00Z")
        ok("fourteen quiet days and the cluster leaves the view; --all shows it", "quiet cluster" in out and cid not in out and cid in C("show", "--scope", "beta", "--as-of", "2026-09-30T00:00Z", "--all")[1])
        rec("beta", "2026-09-05T11:00Z", status="asserted")
        rc, out, _ = C("show", "--scope", "beta", "--as-of", "2026-09-06T00:00Z")
        ok("an asserted record is stored but not counted", "4 record(s)" in out and len([x for x in load_in(env, "beta")]) == 5)
        gid = fpid(fingerprint("gamma", "gate-target/wrong-revision"))
        rc, out, _ = rec("gamma", "2026-09-05T10:00Z", kind="gate-target/wrong-revision", critical="main-gate-or-deploy-red")
        crit_id = out.split()[0]
        ok("a critical record is eligible on first sight", elig("--scope", "gamma", "--as-of", "2026-09-06T00:00Z") == [gid])
        C("record", "--scope", "gamma", "--kind", "gate-target/wrong-revision", "--observed", "a sanctioned deploy", "--corrects", crit_id, "--status", "refuted")
        ok("…refuted, it is not", elig("--scope", "gamma", "--as-of", "2026-09-06T00:00Z") == [])
        ok("…and a person-first record makes the gap cluster eligible at once", fpid(fingerprint("alpha", GAP_KIND)) in elig("--scope", "alpha"))
        ok("eligible with no scope reads every ledger", set(elig("--as-of", "2026-09-06T00:00Z")) >= {cid})
        # ---- claim: once per cluster, two a rolling day by slot, the scope ledgers untouched. As of 2026-09-06 only
        # beta is eligible (alpha's records are stamped now, gamma's critical is refuted, delta has two episodes).
        claims_f = lambda: [json.loads(l) for l in open(os.path.join(T, "failures", "claims.jsonl")).read().splitlines() if l.strip()] if os.path.isfile(os.path.join(T, "failures", "claims.jsonl")) else []
        raw_beta = ledger("beta")
        ok("before any claim an eligible cluster reads unclaimed, aged from the moment the rule fired (the third episode)", any(l.startswith(cid) and l.endswith("\tunclaimed 14h 0m") for l in C("eligible", "--as-of", "2026-09-06T00:00Z")[1].splitlines()))
        rc, out, err = C("claim", "--as-of", "2026-09-06T00:00Z", "--dry")
        ok("claim --dry says what it would claim and writes nothing", rc == 0 and out.split("\t")[1] == cid and claims_f() == [])
        rc, out, err = C("claim", "--as-of", "2026-09-06T00:00Z")
        f1 = out.rstrip("\n").split("\t")
        ok("claim takes the one eligible cluster: one claims line; prints claim, cluster, scope, kind, why, slot", rc == 0 and len(f1) == 6 and f1[0].startswith("i-") and f1[1] == cid and f1[2] == "beta" and f1[3] == K and f1[4] == "3 episodes in 14d" and f1[5] == "routine" and len(claims_f()) == 1)
        claim1 = f1[0]
        rc, out, err = C("claim", "--as-of", "2026-09-06T00:00Z")
        ok("CLAIM ONCE: a second pass claims nothing, says why, and writes no line", rc == 1 and out == "" and "nothing to claim: 1 eligible, 1 claimed" in err and len(claims_f()) == 1)
        ok("…the scope ledger's bytes are untouched: a claim is not a record", ledger("beta") == raw_beta)
        ok("…and the cluster stays eligible, now saying who holds it", any(l.startswith(cid) and l.endswith(f"\tclaimed 2026-09-06T00:00 {claim1}") for l in C("eligible", "--as-of", "2026-09-06T00:00Z")[1].splitlines())
           and f"claimed 2026-09-06T00:00 {claim1}" in C("show", "--scope", "beta", "--as-of", "2026-09-06T00:00Z")[1])
        os.makedirs(os.path.join(T, "failures", "reports")); rep1 = os.path.join(T, "failures", "reports", f"{claim1}.md")
        open(rep1, "w").write("# r\n")
        ok("…and `reported` once the report file is there", f"{claim1} reported" in C("show", "--scope", "beta", "--as-of", "2026-09-06T00:00Z")[1])
        # A REPORT THAT SAYS THE INVESTIGATION DID NOT HAPPEN IS NOT A RESULT. Its own fixture, written the way
        # cc-audit writes it: the marker line, then a report body. Both states are asserted — the claim is offered
        # again once the stamp has passed, and until then it is not (which is what keeps a limit episode cheap).
        open(rep1, "w").write("**Not investigated (deferred):** Claude usage limit until 06:00Z · again after "
                              "2026-09-06T06:00:00Z\n\n_investigation_\n")
        shown = C("show", "--scope", "beta", "--as-of", "2026-09-06T00:00Z")[1]
        ok("a postponed investigation reads `deferred` with the stamp it comes back at, never `reported`",
           f"{claim1} deferred, again after 2026-09-06T06:00:00Z" in shown and "reported" not in shown)
        rc, out, err = C("claim", "--as-of", "2026-09-06T00:00Z")
        ok("…and before that stamp it is not offered: nothing is claimed and no line is written",
           rc == 1 and "nothing to claim: 1 eligible, 1 claimed" in err and len(claims_f()) == 1)
        rc, out, err = C("claim", "--as-of", "2026-09-06T06:00:00Z")
        ok("…AT the stamp the SAME claim is offered again — the cluster comes back, and it costs no new claims line",
           rc == 0 and out.split("\t")[0] == claim1 and out.split("\t")[1] == cid and len(claims_f()) == 1)
        open(rep1, "w").write("**Not investigated (failed):** budget ran out: $0.44 spent of the $0.60 cap · again "
                              "after 2026-09-07T00:00:00Z\n\n_investigation_\n")
        ok("a broad pass that ran and failed reads `failed` — the run happened, and it is still not a report",
           f"{claim1} failed, again after 2026-09-07T00:00:00Z" in C("show", "--scope", "beta", "--as-of", "2026-09-06T00:00Z")[1])
        rc, out, err = C("claim", "--as-of", "2026-09-06T00:00Z")
        ok("…and it too waits for its stamp rather than spending the cap again the same day", rc == 1 and len(claims_f()) == 1)
        # THE FREE-LIST ORDER MATCHES THE deferred GUARD's: a free critical cluster is claimed ahead of any free
        # non-critical one, even when the non-critical one has more episodes_14d. Its own scope, two kinds (two
        # clusters), both slots open (no prior claim within 24h of the --as-of below): nothing else can win the race.
        # Claims and ledger put back after so this leaves no mark on the rolling-day tests further down.
        claims_raw0 = open(os.path.join(T, "failures", "claims.jsonl")).read()
        for d in ("01", "03", "05"): rec("raceslot", f"2026-09-{d}T09:00Z")
        rec("raceslot", "2026-09-07T09:00Z", kind="gate-target/wrong-revision", critical="main-gate-or-deploy-red")
        rcid = fpid(fingerprint("raceslot", K)); ccid = fpid(fingerprint("raceslot", "gate-target/wrong-revision"))
        before_claims = len(claims_f())
        rc, out, err = C("claim", "--scope", "raceslot", "--as-of", "2026-09-08T00:00Z")
        ok("a free critical cluster is claimed before a free routine cluster with more episodes_14d",
           rc == 0 and out.split("\t")[1] == ccid and out.split("\t")[1] != rcid
           and out.rstrip("\n").split("\t")[5] == "critical" and len(claims_f()) == before_claims + 1)
        open(os.path.join(T, "failures", "claims.jsonl"), "w").write(claims_raw0)
        os.remove(os.path.join(T, "failures", "raceslot.jsonl"))
        # A HANDBACK NEVER STARVES A CLUSTER NOBODY HAS LOOKED AT. Its own fixture — critical clusters stamped after
        # every other case's --as-of, so they are invisible to those — and its own claims, put back at the end so the
        # slot cases below still count what they wrote. Both sides of each word: the handback yields while free work
        # waits, and it comes back the moment none does.
        claims_raw = open(os.path.join(T, "failures", "claims.jsonl")).read()
        rec("crita", "2026-09-09T09:00Z", critical="main-gate-or-deploy-red")
        open(rep1, "w").write("**Not investigated (failed):** budget ran out: $0.44 spent of the $0.60 cap · again "
                              "after 2026-09-08T00:00:00Z\n\n_investigation_\n")
        rc, out, err = C("claim", "--as-of", "2026-09-09T10:00Z")
        ok("a `failed` claim due again yields to a critical cluster nobody holds — that one is claimed the day it crosses",
           rc == 0 and out.split("\t")[2] == "crita" and out.rstrip("\n").split("\t")[5] == "critical"
           and out.split("\t")[0] != claim1 and len(claims_f()) == 2)
        rc, out, err = C("claim", "--as-of", "2026-09-09T10:05Z")
        ok("…and with no free cluster waiting the same claim comes back: a pass that failed is no gravestone either",
           rc == 0 and out.split("\t")[0] == claim1 and len(claims_f()) == 2)
        rec("critb", "2026-09-09T09:00Z", critical="main-gate-or-deploy-red")
        open(rep1, "w").write("**Not investigated (deferred):** Claude usage limit until 06:00Z · again after "
                              "2026-09-08T00:00:00Z\n\n_investigation_\n")
        rc, out, err = C("claim", "--as-of", "2026-09-09T10:10Z")
        ok("a `deferred` claim due again yields to a critical cluster as well, rather than hold the slot out",
           rc == 0 and out.split("\t")[2] == "critb" and out.split("\t")[0] != claim1 and len(claims_f()) == 3)
        rc, out, err = C("claim", "--as-of", "2026-09-09T10:15Z")
        ok("…and with none waiting it is handed back, still without a new claims line",
           rc == 0 and out.split("\t")[0] == claim1 and len(claims_f()) == 3)
        open(os.path.join(T, "failures", "claims.jsonl"), "w").write(claims_raw)
        for sc in ("crita", "critb"): os.remove(os.path.join(T, "failures", f"{sc}.jsonl"))
        open(rep1, "w").write("**Not investigated (deferred):** a limit · again after soon\n")
        shown = C("show", "--scope", "beta", "--as-of", "2026-09-06T00:00Z")[1]
        rc, out, err = C("claim", "--as-of", "2026-09-06T00:00Z")
        ok("…a stamp that cannot be read is no reason to wait: it says so and the claim comes back at once",
           f"{claim1} deferred, again after the next claim" in shown and rc == 0 and out.split("\t")[0] == claim1 and len(claims_f()) == 1)
        open(rep1, "w").write("a report that merely quotes `**Not investigated (deferred):** x · again after y` lower down\n")
        ok("…the marker counts only as the report's FIRST line: a report quoting it is still a result",
           f"{claim1} reported" in C("show", "--scope", "beta", "--as-of", "2026-09-06T00:00Z")[1])
        open(rep1, "w").write("# r\n")   # back to an investigated report: the slot cases below claim other clusters
        # the day's slots: a routine cluster only takes the routine slot; a critical one takes critical, or routine when critical is spent
        for d in ("01", "03", "05"): rec("eps", f"2026-09-{d}T09:00Z")
        for sc in ("crit2", "crit3"): rec(sc, "2026-09-05T09:00Z", critical="main-gate-or-deploy-red")
        rc, out, err = C("claim", "--as-of", "2026-09-06T00:10Z")
        ok("the routine slot spent, a routine cluster waits and a critical one takes the critical slot", rc == 0 and out.split("\t")[2] == "crit2" and out.rstrip("\n").split("\t")[5] == "critical")
        rc, out, err = C("claim", "--as-of", "2026-09-06T00:10Z")
        ok("…both slots spent: nothing, and it says which", rc == 1 and "routine/critical slot(s) used" in err and len(claims_f()) == 2)
        ok("…the unclaimed clusters stay eligible and visible with their age", sum(l.endswith("\tunclaimed 15h 10m") for l in C("eligible", "--as-of", "2026-09-06T00:10Z")[1].splitlines()) == 2)
        rc, out, err = C("claim", "--as-of", "2026-09-07T00:10Z")
        ok("a rolling day later both slots are free: the critical cluster goes first, even with fewer episodes", rc == 0 and out.split("\t")[2] == "crit3" and out.rstrip("\n").split("\t")[5] == "critical")
        rc, out, err = C("claim", "--as-of", "2026-09-07T00:10Z")
        ok("…then the routine cluster, in the routine slot", rc == 0 and out.split("\t")[2] == "eps" and out.rstrip("\n").split("\t")[5] == "routine")
        for sc in ("crit4", "crit5"): rec(sc, "2026-09-07T09:00Z", critical="main-gate-or-deploy-red")
        rc, out, err = C("claim", "--as-of", "2026-09-08T00:10Z"); rc2, out2, err2 = C("claim", "--as-of", "2026-09-08T00:10Z")
        ok("a critical cluster may take the routine slot once the critical one is spent", rc == 0 and out.rstrip("\n").split("\t")[5] == "critical" and rc2 == 0 and out2.rstrip("\n").split("\t")[5] == "routine")
        for d in ("15", "17", "19"): rec("beta", f"2026-09-{d}T10:00Z")
        rc, out, err = C("claim", "--scope", "beta", "--as-of", "2026-09-21T00:00Z")
        ok("a cluster still eligible fourteen days after its claim is a repeat: claimed again, a new id", rc == 0 and out.split("\t")[1] == cid and out.split("\t")[0] != claim1)
        # ---- packet: what the investigation reads
        rc, out, err = C("packet", claim1, "--as-of", "2026-09-06T00:00Z")
        ok("packet by claim id: the header, the count, the crossing at the third episode, the scope's other clusters", rc == 0 and out.startswith(f"# failure packet {claim1} — cluster {cid}")
           and "records: 4 confirmed of 5" in out and "### the crossing: " in out and "2026-09-05T10:00:00Z" in out.split("### the crossing")[1].splitlines()[0] and "the rule fired: 2026-09-05T10:00:00Z (3 episodes in 14d)" in out and "## the scope's other clusters" in out)
        rc, out, err = C("packet", cid, "--as-of", "2026-09-06T00:00Z")
        ok("…and by cluster id", rc == 0 and f"cluster {cid}" in out and "claimed: no" not in out)
        rc, out, err = C("packet", "i-nope")
        ok("…an id nobody holds is refused", rc == 2 and "no claim or cluster" in err)
        # ---- import: a fixture board, through cc-board
        repo = f"_ccfail{os.getpid()}"
        board = {"repo": repo, "path": os.path.join(home, "dev", repo), "default_branch": "main", "log": [], "tracks": {
            "raised-guard-reads-heredoc-body-as-a-command": {"title": "the guard refused a heredoc", "status": "queued", "created": "2026-09-08T22:00:00Z", "updated": "2026-09-09T21:04:46Z", "notes": [
                {"ts": "2026-09-09T05:09:07Z", "msg": "INSTANCE 2026-09-09 05:07Z (planning): a member hit it too"},
                {"ts": "2026-09-09T21:04:46Z", "msg": "INSTANCE 2026-09-09 19:0x–19:4xZ (member): four relays"},
                {"ts": "2026-09-10T00:10:00Z", "msg": "INSTANCE 23:3xZ, dateless and after the filing hour: the day before"},
                {"ts": "2026-09-10T02:00:00Z", "msg": "scoped; no instance here"}]},
            "containment-tests-run-the-shipping-shape": {"title": "not a raised row, but its notes count", "status": "queued", "created": "2026-09-07T18:00:00Z", "notes": [
                {"ts": "2026-09-07T19:08:49Z", "msg": "2026-09-07 19:3xZ — THIRD INSTANCE, the owner caught it on PR 1"},
                {"ts": "2026-09-11T03:20:49Z", "msg": "INSTANCE 2026-09-10 17:12 PDT (thread): stated in the server's zone"},
                {"ts": "2026-09-11T17:18:43Z", "msg": "INSTANCE 17:2xZ (builder): rounded past its own filing"}]},
            "raised-nothing-said": {"title": "a raised row with no times stated; the owner asked for the file", "status": "queued", "created": "2026-09-10T08:00:00Z", "notes": []},
            "plain-row": {"title": "no INSTANCE, not raised", "status": "done", "created": "2026-09-01T08:00:00Z", "notes": [{"ts": "2026-09-02T08:00:00Z", "msg": "done"}]}}}
        with open(os.path.join(home, ".cc", "boards", f"{repo}.json"), "w") as fh: json.dump(board, fh)
        os.makedirs(os.path.join(T, "state", repo, "raised-nothing-said"))
        with open(os.path.join(T, "state", repo, "raised-nothing-said", "task.md"), "w") as fh:
            fh.write("GOAL: x\nINSTANCE 2026-09-10 09:00Z (worker): one in the brief\n")
        rc, out, err = C("import", repo, "--dry")
        ok("import --dry writes nothing and says what it would", rc == 0 and ledger(repo) == "" and "would write" in out and "9 new record(s) (dry)" in out)
        rc, out, err = C("import", repo)
        ls = {r["links"]["source"]: r for r in load_in(env, repo)}
        ok("import writes the raised- row at its creation, the INSTANCE notes, and the brief line — one each, nothing for a note or row without one",
           rc == 0 and len(ls) == 9 + 1 and "note:%s/raised-guard-reads-heredoc-body-as-a-command@2026-09-10T02:00:00Z" % repo not in ls
           and "board:%s/plain-row" % repo not in ls and "board:%s/containment-tests-run-the-shipping-shape" % repo not in ls)
        g = "raised-guard-reads-heredoc-body-as-a-command"
        ok("…the raised row's record is at its filing time, and its filed stamp is the same", ls[f"board:{repo}/{g}"]["ts"] == "2026-09-08T22:00:00Z" == ls[f"board:{repo}/{g}"]["filed"])
        ok("…a note's stated time is the record's time, the note's own stamp is when it was filed",
           ls[f"note:{repo}/{g}@2026-09-09T05:09:07Z"]["ts"] == "2026-09-09T05:07:00Z" and ls[f"note:{repo}/{g}@2026-09-09T05:09:07Z"]["filed"] == "2026-09-09T05:09:07Z")
        ok("…`19:0x–19:4xZ`: the first time, x floored", ls[f"note:{repo}/{g}@2026-09-09T21:04:46Z"]["ts"] == "2026-09-09T19:00:00Z")
        ok("…`23:3xZ` filed at 00:10Z: the day before", ls[f"note:{repo}/{g}@2026-09-10T00:10:00Z"]["ts"] == "2026-09-09T23:30:00Z")
        c = "containment-tests-run-the-shipping-shape"
        ok("…`17:12 PDT` is 00:12Z the next day", ls[f"note:{repo}/{c}@2026-09-11T03:20:49Z"]["ts"] == "2026-09-11T00:12:00Z")
        ok("…`17:2xZ` filed at 17:18Z is the same day (an hour's slack, not a day's)", ls[f"note:{repo}/{c}@2026-09-11T17:18:43Z"]["ts"] == "2026-09-11T17:20:00Z")
        ok("…the brief's INSTANCE line: its stated time, filed unknown", ls[f"brief:{repo}/raised-nothing-said#2"]["ts"] == "2026-09-10T09:00:00Z" and ls[f"brief:{repo}/raised-nothing-said#2"]["filed"] == "")
        ok("a row the catalogue matches files under that kind; one it does not under its own family",
           ls[f"board:{repo}/{g}"]["kind"] == K and ls[f"board:{repo}/raised-nothing-said"]["kind"] == "board-row/raised-nothing-said" and ls[f"note:{repo}/{c}@2026-09-11T17:18:43Z"]["kind"] == f"board-row/{c}")
        ok("a note saying the owner caught it is detector person, with the phrase as evidence, and gets its gap record",
           ls[f"note:{repo}/{c}@2026-09-07T19:08:49Z"]["detector"] == {"who": "person", "evidence": "owner caught"} and ls.get(f"note:{repo}/{c}@2026-09-07T19:08:49Z#gap", {}).get("kind") == GAP_KIND)
        ok("…one that does not say is unknown, said", ls[f"board:{repo}/{g}"]["detector"]["who"] == "unknown")
        ok("…and 'the owner asked' is what the box was doing, not who caught it: unknown", ls[f"board:{repo}/raised-nothing-said"]["detector"]["who"] == "unknown")
        ok("…and 'the owner would have found it' is a counterfactual, not a detection", stated_detector("the owner would have found it first")[0] == "unknown" and stated_detector("the owner found it first")[0] == "person")
        rc, out, err = C("import", repo)
        ok("a second import writes nothing: each source once", rc == 0 and "0 new record(s)" in out and len(load_in(env, repo)) == 10)
        ok("the guard row: three INSTANCE episodes in 14 days of 09-10 — eligible on the real rule", fpid(fingerprint(repo, K)) in elig("--scope", repo, "--as-of", "2026-09-10T12:00Z"))
        rc, out, err = C("import", "_ccnoboard")
        ok("a repo with no board is refused, not imported empty", rc == 2 and "cc-board json" in err)
        # ---- cc board failures renders the ledger
        p = subprocess.run([os.path.join(B, "cc-board"), "failures", repo, "--as-of", "2026-09-10T12:00Z"], capture_output=True, text=True, env=env)
        ok("`cc board failures <repo>` renders the scope's clusters, eligible marked", p.returncode == 0 and fpid(fingerprint(repo, K)) in p.stdout and "ELIGIBLE" in p.stdout and repo in p.stdout)
        p = subprocess.run([os.path.join(B, "cc-board"), "failures", "_ccempty"], capture_output=True, text=True, env=env)
        ok("…and an empty scope says so", p.returncode == 0 and "no failures recorded" in p.stdout)
        # ---- metrics: the ledger, and a labelled fixture
        rc, out, err = C("metrics", "--scope", repo)
        ok("metrics on a ledger: records, clusters, eligible, the recording delay and the detector shares", rc == 0 and "records: 10" in out and "recording delay" in out and "median" in out and "detector: unknown" in out)
        # THE LABELLED FIXTURE ships beside the suite (tests/failures-fixture.jsonl): ten September-shaped lines a
        # person labelled, two of them deliberately where the name-matcher and the label disagree — one row a person
        # files under the guard family whose name does not start with guard (a split), one correct refusal whose name
        # does (a match). The numbers below are counted by hand from that file; a change to either moves them.
        rc, out, err = C("metrics", FIXTURE)
        ok("metrics on the labelled fixture: the false-match, false-split and true-time rates with their counts, and the delay",
           rc == 0 and "false match rate: 4/12" in out and "false split rate: 4/12" in out and "true time recovered: 9/10" in out
           and "recording delay (filed - happened, min): median 1, max 367, n=10" in out)
        rc, out, err = C("metrics", os.path.join(T, "missing.jsonl"))
        ok("…a fixture that is not there is refused, not reported empty", rc == 2 and "fixture" in err)
        # ---- replay: the shipped September events, this detector, then candidates on the same frozen inputs
        rc, out, err = C("replay")
        AE, GAP = fpid(fingerprint("box", "answer-evidence/wrong-object-or-proxy")), fpid(fingerprint("box", GAP_KIND))
        ok("replay on the shipped events: the 09-07 crossing the design cites — answer-evidence fires at the third episode, 20:50Z",
           rc == 0 and f"‼ {AE}  box  answer-evidence/wrong-object-or-proxy  fired 2026-09-07T20:50 (3 episodes in 14d)" in out)
        ok("…the person-first gap cluster fires on first sight, 09-06 05:02Z", f"‼ {GAP}  box  failure-detection/person-first  fired 2026-09-06T05:02 (critical: person-first)" in out)
        ok("…a two-episode cluster stays quiet, and is printed as quiet", "gate-target/wrong-revision  quiet  2 record(s), 2 episode(s)" in out)
        ctl = [l for l in out.splitlines() if "control '" in l]
        ok("…every negative control is printed, quiet, and the run is scored", len(ctl) == 5 and all(l.strip().startswith("quiet  control") for l in ctl) and out.rstrip().endswith("controls quiet: scored"))
        ok("…the live ledger was neither read nor written: no box scope appeared under CC_FAILURES", not os.path.exists(os.path.join(T, "failures", "box.jsonl")))
        rc, out, err = C("replay", "--json")
        j = json.loads(out) if rc == 0 else {}
        ok("replay --json prints the run: clusters with fired/control, no errors", rc == 0 and j.get("clusters", {}).get(AE, {}).get("fired", {}).get("at") == "2026-09-07T20:50:00Z" and j["errors"] == [])
        rc, out, err = C("replay", os.path.join(T, "none.jsonl"))
        ok("an events file that is not there is refused, not replayed empty", rc == 2 and "events" in err)
        bad = os.path.join(T, "bad.jsonl"); open(bad, "w").write('{"ts": "2026-09-01T10:00Z", "scope": "s", "text": "no kind and no row"}\n')
        rc, out, err = C("replay", bad)
        ok("…and a line with neither kind nor row is refused", rc == 2 and "kind or row" in err)
        # CANDIDATES: the same events, another detector. A copy of this file with the episode gap cut to 5 minutes turns the
        # "one episode written three times" control into three episodes: it fires, and the run is red, not scored.
        src = open(os.path.join(B, "cc-failures")).read()
        cand = os.path.join(T, "cand-gap5"); open(cand, "w").write(src.replace("EPISODE_GAP_MIN = 30 ", "EPISODE_GAP_MIN = 5 ")); os.chmod(cand, 0o755)
        rc, out, err = C("replay", "--candidate", cand)
        ok("a candidate that fires on a negative control: the control line says FIRED, the run is RED, rc 1",
           rc == 1 and any(l.strip().startswith("FIRED  control 'one episode written three times'") for l in out.splitlines()) and "RED: a control fired" in out
           and out.count("controls quiet") == 0)
        ok("…the baseline in the same run still shows the control quiet", "baseline:" in out and out.split("candidate:")[0].count("quiet  control") == 5)
        cand2 = os.path.join(T, "cand-two"); open(cand2, "w").write(src.replace("EPISODES_NEEDED = 3 ", "EPISODES_NEEDED = 2 ")); os.chmod(cand2, 0o755)
        rc, out, err = C("replay", "--candidate", cand2)
        ok("a candidate needing two episodes: the crossing moves earlier and the difference says by how much — and the two-episode control fires, so it is red",
           rc == 1 and f"~ {AE}  answer-evidence/wrong-object-or-proxy  crossing moved 2026-09-07T20:50 → 2026-09-07T19:30 (earlier by 1h 20m)" in out
           and any(l.strip().startswith("FIRED  control 'two episodes in fourteen days'") for l in out.splitlines()))
        cat2 = json.load(open(CATALOGUE)); cat2["kinds"]["notification/false-action-needed"]["match"] = []
        ccat = os.path.join(T, "cat-no-steward.json"); json.dump(cat2, open(ccat, "w"))
        rc, out, err = C("replay", "--candidate-catalogue", ccat)
        NF = fpid(fingerprint("box", "notification/false-action-needed"))
        ok("a candidate catalogue that drops a match: the rows file under their own families and that cluster no longer fires",
           rc == 0 and f"- no longer fires {NF}  box  notification/false-action-needed" in out and "only in the candidate: 4" in out)
        ok("…the baseline's catalogue is untouched by --candidate-catalogue", f"‼ {NF}" in out.split("candidate:")[0])
        rc, out, err = C("replay", "--candidate", cand2, "--candidate-catalogue", ccat)
        ok("…both together: the candidate executable runs with the candidate catalogue", rc == 1 and f"- no longer fires {NF}" in out and "crossing moved" in out)
        rc, out, err = C("replay", "--candidate-catalogue", CATALOGUE)
        ok("the same detector twice: no difference", rc == 0 and "no difference: the same clusters fire at the same moments" in out)
        mixed = os.path.join(T, "mixed.jsonl")
        with open(mixed, "w") as fh:
            fh.write('{"label": "real", "ts": "2026-09-01T10:00Z", "scope": "s", "kind": "a/b", "text": "a real event", "detector": "box"}\n')
            fh.write('{"label": "ctl", "control": "must not fire", "ts": "2026-09-02T10:00Z", "scope": "s", "kind": "a/b", "text": "a control in the same cluster", "detector": "box"}\n')
        rc, out, err = C("replay", mixed)
        ok("a control that shares a cluster with a real event is a fixture error: said, and rc 1", rc == 1 and "ERROR control 'must not fire' shares cluster" in out)
        # ---- recurring gate reds: a case, counted by landing, claimed once, held through its cool-down
        env["CC_CONFIG"] = os.path.join(T, "config")          # the thresholds' defaults, whatever the box's own file says
        def red(pr, line, ts, scope="rr", gate="core/tests/selftest.sh", excerpt=None):
            return C("record", "--scope", scope, "--kind", RED_KIND, "--ts", ts, "--writer", "cc-land",
                     "--observed", f"gate {gate} did not pass at the landing of {scope} PR #{pr} on abcdef012345: {line}",
                     "--link", f"gate={gate}", "--link", f"pr={pr}", *(["--evidence", f"excerpt:{excerpt}"] if excerpt else []))
        at = lambda h: utc(now_dt() - datetime.timedelta(hours=h))
        rcl = lambda *a: C("recurring", "claim", "--scope", "rr", *a)
        claimed = lambda: [json.loads(l) for l in open(os.path.join(T, "failures", "recurring", "claims.jsonl"))] if os.path.isfile(os.path.join(T, "failures", "recurring", "claims.jsonl")) else []
        for h in (5, 4, 3):
            red(101, "✗ relative reset parsed to +72s · /tmp/x.123/log", at(h))    # one PR, re-run three times
        rc, out, err = rcl()
        ok("RECURRING: a case red once, however often that one PR re-runs, is one landing — nothing is claimed", rc == 1 and claimed() == [] and "no red case on 3" in err)
        ok("…and `recurring` lists it with its one landing", "\t1 landing(s)\tunclaimed\trelative reset parsed to +Ns" in C("recurring", "--scope", "rr")[1])
        ex = os.path.join(T, "excerpt.log")
        with open(ex, "w") as fh: fh.write("source=gate:x\nlog=/tmp/y (9 bytes)\n\n14:  ✗ relative reset parsed to +91s\n\n--- tail ---\n  ✗ a tail line is not a case\n")
        red(102, "✗ relative reset parsed to +80s", at(2)); red(103, "(no ✗ in this observed text)", at(1), excerpt=ex)
        rc, out, err = rcl()
        k = json.loads(out) if rc == 0 else {}
        ok("…red on three PRs (one of them read from its excerpt, numbers aside): ONE claim, naming the case, its landings and the worker's track",
           rc == 0 and len(claimed()) == 1 and k.get("text") == "relative reset parsed to +Ns" and k.get("landings") == ["PR #101", "PR #102", "PR #103"]
           and k.get("track", "").startswith("recurring-red-") and k.get("excerpts") == [ex])
        ok("…the excerpt's tail is not read as a case", "a tail line" not in C("recurring", "--scope", "rr")[1])
        red(104, "✗ relative reset parsed to +5s", at(0))
        rc, out, err = rcl()
        ok("…and the next ask inside the cool-down claims nothing, even with the case red again: held by its claim", rc == 1 and len(claimed()) == 1 and "held by d-" in err)
        rc, out, err = C("recurring", "held", "--scope", "rr", "--text", "gate core/tests/selftest.sh did not pass: ✗ relative reset parsed to +12s  [full output: /tmp/a/b.log]")
        ok("HELD: a landing's red that is only the held case is held, and says by which claim", rc == 0 and out.startswith("held: d-") and "recurring-red-" in out)
        rc, out, err = C("recurring", "held", "--scope", "rr", "--text", "gate g did not pass: ✗ relative reset parsed to +1s · ✗ a case of its own")
        ok("…while a red that also names a case of its own is not", rc == 1 and out == "")
        ok("…nor the same case in another scope", C("recurring", "held", "--scope", "other", "--text", "✗ relative reset parsed to +1s")[0] == 1)
        later = utc(now_dt() + datetime.timedelta(hours=25))
        rc, out, err = rcl("--as-of", later)
        ok("PAST THE COOL-DOWN, a case not red on the threshold again since its claim is not claimed again", rc == 1 and len(claimed()) == 1 and "since d-" in err)
        ok("…and the landing no longer holds for it", C("recurring", "held", "--scope", "rr", "--text", "✗ relative reset parsed to +1s", "--as-of", later)[0] == 1)
        rc, out, err = rcl("--dry")
        ok("--dry claims nothing", rc == 1 and len(claimed()) == 1)
        env["CC_RECURRING_RED_MIN"] = "2"
        red(201, "✗ another case entirely", at(2)); red(202, "✗ another case entirely", at(1))
        rc, out, err = rcl()
        ok("THE THRESHOLD is a cc-config key (the environment wins): at 2, a case red on two PRs is claimed", rc == 0 and json.loads(out)["text"] == "another case entirely" and len(claimed()) == 2)
        red(301, "✗ a third case", at(2)); red(302, "✗ a third case", at(1))
        rc, out, err = rcl()
        ok("…and two claims a rolling day is the cap, whatever the cases", rc == 1 and len(claimed()) == 2 and "the cap" in err)
        del env["CC_RECURRING_RED_MIN"]
        # …and the lander's own record (records.record_red's argv, --once and its links) feeds the same count
        def red_l(pr, line, ts, check="core-guard"):
            return C("record", "--once", "--scope", "rl", "--kind", RED_KIND, "--ts", ts,
                     "--observed", f"check {check} did not pass at the landing of rl PR #{pr} on abcdef012345: {line}",
                     "--expected", "a tree handed over passes its checks", "--writer", "lander", "--detector", "box",
                     "--detector-evidence", "lander saw it", "--cost", "fix-iteration=1",
                     "--link", f"source=gate:{check}:abcdef01234{pr % 10}", "--link", f"gate={check}",
                     "--link", f"tree=abcdef01234{pr % 10}", "--link", f"pr={pr}")
        for i, pr in enumerate((401, 402, 403)):
            red_l(pr, f"✗ the lander's case failed after {i + 3}s · FAIL: a second case", at(3 - i))
        out = C("recurring", "--scope", "rl")[1]
        ok("…a red the LANDER wrote (--writer lander, `check … did not pass`) is counted by landing the same way",
           "\t3 landing(s)" in out and "unclaimed\tthe lander's case failed after Ns" in out and "a second case" in out)
        rc, out, err = C("kinds")
        ok("kinds prints the catalogue's kinds and the critical reasons", rc == 0 and out.count("/") >= 6 and "person-first" in out and K in out)
        rc, out, err = C("sideways")
        ok("an unknown command is usage, rc 2", rc == 2)
    finally:
        shutil.rmtree(T, ignore_errors=True)
    print(f"cc-failures selfcheck: {n - f} passed, {f} failed")
    return 1 if f else 0
