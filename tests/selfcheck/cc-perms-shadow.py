# cc-perms-shadow's selfcheck: the cases behind `cc-perms-shadow selfcheck`. Not a module: cc-perms-shadow execs this
# file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it defines. No module docstring and no top-level name but the def.

def selfcheck():
    """Each case in its own temp dir: a fake ledger, fake candidates, a fake cc-failures. No model, no HOME."""
    import contextlib
    import hashlib
    import io
    import shutil
    import tempfile
    p = f = 0

    def ok(name, cond):
        nonlocal p, f
        if cond:
            p += 1
        else:
            f += 1
            print(f"  ✗ {name}")

    tops = []

    def fixture(entries):
        """A temp dir with a ledger of (id, input, decision or None, note), a fake cc-failures and a log path."""
        d = tempfile.mkdtemp(prefix="cc-perms-shadow-sc-")
        tops.append(d)
        led = os.path.join(d, "refusals.jsonl")
        with open(led, "w") as fh:
            for n, (rid, cmd, dec, note) in enumerate(entries):
                fh.write(json.dumps({"kind": "refusal", "id": rid, "at": f"2026-10-1{n}T00:00:00Z", "source": "classifier",
                                     "window": "w", "session": "s", "tool": "Bash",
                                     "input": json.dumps({"command": cmd}), "reason": "r", "key": "k" + rid}) + "\n")
            for rid, _, dec, note in entries:
                if dec:
                    fh.write(json.dumps({"kind": "decision", "id": rid, "at": "2026-10-12T01:00:00Z", "decision": dec,
                                         "note": note, "by": "w"}) + "\n")
        fails = os.path.join(d, "failures.args")
        fake_f = os.path.join(d, "fake-failures")
        with open(fake_f, "w") as fh:
            fh.write("#!/usr/bin/env python3\nimport json, sys\n"
                     f"open({fails!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n")
        os.chmod(fake_f, 0o755)
        return d, led, os.path.join(d, "shadow", "log.jsonl"), fake_f, fails

    def cand(d, name, body):
        path = os.path.join(d, name)
        with open(path, "w") as fh:
            fh.write("#!/usr/bin/env python3\nimport json, os, sys\nc = json.load(sys.stdin)\n" + body)
        os.chmod(path, 0o755)
        return [path]

    def grant(d, count=None):
        tick = f"open({count!r}, 'a').write(c['id'] + '\\n')\n" if count else ""
        return cand(d, "grant", tick + 'print(json.dumps({"verdict": "grant", "level": "perms", "reason": "fine"}))\n')

    def lines(path):
        return [json.loads(x) for x in open(path)] if os.path.isfile(path) else []

    def stamp(path):
        st = os.stat(path)
        return hashlib.sha256(open(path, "rb").read()).hexdigest(), st.st_mtime_ns, st.st_size

    def go(cmd, led, log, fake_f, **kw):
        old = os.environ.get("CC_PERMS_SHADOW_FAILURES")
        os.environ["CC_PERMS_SHADOW_FAILURES"] = fake_f
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return run(cmd, "fixture", led, log, **kw)
        finally:
            if old is None:
                os.environ.pop("CC_PERMS_SHADOW_FAILURES", None)
            else:
                os.environ["CC_PERMS_SHADOW_FAILURES"] = old

    ledgers = []

    # 1. an agreeing grant is logged, and a plain grant raises no failure line
    d, led, log, ff, fails = fixture([("r1", "echo hello", "grant", "rule added")])
    ledgers.append((led, stamp(led)))
    seen = os.path.join(d, "seen.json")
    keep = cand(d, "keep", f"open({seen!r}, 'w').write(json.dumps(c))\n"
                           'print(json.dumps({"verdict": "grant", "level": "perms", "reason": "fine"}))\n')
    rows, flags = go(keep, led, log, ff)
    got = lines(log)
    ok("agreeing grant: one log line, perms grant, shadow grant", len(got) == 1 and got[0]["id"] == "r1"
       and got[0]["perms"] == "grant" and got[0]["shadow"] == "grant" and not got[0]["backstop"] and got[0]["ts"])
    c = json.load(open(seen)) if os.path.exists(seen) else {}
    ok("agreeing grant: the candidate got cc-perms-eval's input, and the ask is the tool and its input",
       set(c) == {"id", "date", "ask", "asker", "origin", "kind", "reaches", "reversible", "money", "evidence"}
       and c["id"] == "r1" and c["date"] == "2026-10-10T00:00:00Z" and c["ask"].startswith("Bash: ") and "echo hello" in c["ask"])
    ok("non-backstop grant: no failure line", flags == 0 and not os.path.exists(fails))

    # 2. an ask already in the log is skipped; an undecided ask is not run at all
    d, led, log, ff, fails = fixture([("r1", "echo hello", "grant", "ok"), ("r2", "echo two", None, "")])
    ledgers.append((led, stamp(led)))
    count = os.path.join(d, "calls")
    go(grant(d, count), led, log, ff)
    go(grant(d, count), led, log, ff)
    calls = open(count).read().split() if os.path.exists(count) else []
    ok("already logged: the second run calls the candidate for nothing", calls == ["r1"])
    ok("already logged: still one log line", [x["id"] for x in lines(log)] == ["r1"])
    ok("undecided: never run, never logged", "r2" not in calls)

    # 2b. --since and --max hold asks back for a later run, and that run picks them up
    d, led, log, ff, fails = fixture([("a", "echo a", "grant", "ok"), ("b", "echo b", "decline", "no need"),
                                      ("c", "echo c", "grant", "ok")])
    ledgers.append((led, stamp(led)))
    go(grant(d), led, log, ff, since="2026-10-11T00:00:00Z", max_n=1)
    ok("--since skips earlier asks, --max stops after N", [x["id"] for x in lines(log)] == ["b"])
    go(grant(d), led, log, ff)
    ok("a later run picks up what was held back", sorted(x["id"] for x in lines(log)) == ["a", "b", "c"])
    ok("decline maps to refuse", {x["id"]: x["perms"] for x in lines(log)}["b"] == "refuse")
    ok("a shadow grant on a plain decline raises no failure line", not os.path.exists(fails))

    # 3. an erroring candidate is logged as error, never a grant, and raises nothing
    d, led, log, ff, fails = fixture([("r1", "git push --force origin main", "grant", "ok")])
    ledgers.append((led, stamp(led)))
    bad = cand(d, "bad", 'print("no json here"); sys.exit(3)\n')
    rows, flags = go(bad, led, log, ff)
    got = lines(log)
    ok("error candidate: logged as error with its error text", len(got) == 1 and got[0]["shadow"] == "error"
       and got[0]["error"])
    ok("error candidate: no failure line, even on a backstop ask", flags == 0 and not os.path.exists(fails))
    missing = [os.path.join(d, "not-there")]
    d2, led2, log2, ff2, fails2 = fixture([("r9", "echo x", "grant", "ok")])
    ledgers.append((led2, stamp(led2)))
    go(missing, led2, log2, ff2)
    ok("a candidate that cannot start is an error row", [x["shadow"] for x in lines(log2)] == ["error"])

    # 4. a shadow grant on a backstop ask raises exactly one failure line, once, with --once and its source
    d, led, log, ff, fails = fixture([("r1", "git push --force origin main", "decline", "not the seat's to do"),
                                      ("r2", "echo fine", "grant", "ok")])
    ledgers.append((led, stamp(led)))
    rows, flags = go(grant(d), led, log, ff)
    go(grant(d), led, log, ff)
    calls = [json.loads(x) for x in open(fails)] if os.path.exists(fails) else []
    ok("backstop grant: exactly one failure line, across two runs", len(calls) == 1 and flags == 1)
    a = calls[0] if calls else []
    ok("backstop grant: record --once, its kind and its source link",
       a[:1] == ["record"] and "--once" in a and a[a.index("--kind") + 1] == KIND
       and "source=perms-shadow:r1" in a and a[a.index("--scope") + 1] == "fixture")
    by = {x["id"]: x for x in lines(log)}
    ok("backstop grant: the log line names it; the plain grant beside it does not",
       by["r1"]["backstop"].startswith("the ask crosses") and not by["r2"]["backstop"])

    # 4b. perms declined on the backstop (its note says so): a shadow grant there is flagged too
    d, led, log, ff, fails = fixture([("r1", "echo plain", "decline", "backstop item: the owner's call")])
    ledgers.append((led, stamp(led)))
    rows, flags = go(grant(d), led, log, ff)
    ok("declined on backstop grounds: one failure line", flags == 1
       and sum(1 for _ in open(fails)) == 1 if os.path.exists(fails) else False)
    d, led, log, ff, fails = fixture([("r1", "git push --force origin main", "decline", "backstop")])
    ledgers.append((led, stamp(led)))
    ref = cand(d, "refuse", 'print(json.dumps({"verdict": "refuse", "level": "perms", "reason": "no"}))\n')
    rows, flags = go(ref, led, log, ff)
    ok("refuse on a backstop ask: logged, no failure line", flags == 0 and not os.path.exists(fails)
       and lines(log)[0]["shadow"] == "refuse")

    # 5. the input mapping fills unknowns conservatively
    i = to_input({"tool": "Bash", "input": '{"command": "ls"}', "at": "x"})
    ok("input: cc-perms-eval's keys exactly", set(i) == {"ask", "asker", "origin", "kind", "reaches", "reversible",
                                                          "money", "evidence"})
    ok("input: origin not box unless the record says so", i["origin"] == "unknown" and i["money"] is None
       and i["evidence"] == [])
    ok("input: a record that says origin box keeps it", to_input({"tool": "T", "input": "", "origin": "box"})["origin"] == "box")

    # 6. usage: no candidate is a usage error; no ledger runs nothing
    with contextlib.redirect_stderr(io.StringIO()):
        ok("usage: run without --candidate exits 2", main(["run", "--ledger", led, "--log", log]) == 2)
        ok("usage: an unknown subcommand exits 2", main(["nope"]) == 2)
        nolog = os.path.join(tops[0], "none", "log.jsonl")
        ok("no ledger: exits 0 and writes no log", main(["run", "--candidate", "true", "--ledger",
                                                          os.path.join(tops[0], "absent.jsonl"), "--log", nolog]) == 0
           and not os.path.exists(nolog))
    with contextlib.redirect_stdout(io.StringIO()) as out:
        show(log)
    ok("show: counts the log", out.getvalue().startswith("1 asks: 1 agree, 0 disagree"))

    # 7. the ledger is never written: every fixture's ledger has its hash, mtime and size from before
    ok("the ledger is never written", all(stamp(path) == before for path, before in ledgers))

    for t in tops:
        shutil.rmtree(t, ignore_errors=True)
    print(f"cc-perms-shadow selfcheck: {p} passed, {f} failed")
    return 1 if f else 0
