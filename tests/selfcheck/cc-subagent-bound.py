# cc-subagent-bound's selfcheck: the cases behind `cc-subagent-bound selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-subagent-bound execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    import contextlib, io
    p = f = 0

    def ok(name, cond):
        nonlocal p, f
        if cond:
            p += 1
        else:
            f += 1
            print(f"  FAIL {name}")

    global STATE
    home = tempfile.mkdtemp(prefix="cc-subagent-bound-selfcheck-")
    state0, env0 = STATE, {k: os.environ.pop(k, None) for k in
                           ("CC_SUBAGENT_SAVE_TOKENS", "CC_CONFIG")}
    STATE = os.path.join(home, "state")
    os.environ["CC_CONFIG"] = os.path.join(home, "config")        # an empty config: the box's own must not move a line
    open(os.environ["CC_CONFIG"], "w").close()
    proj = os.path.join(home, "projects", "-dev-x")
    os.makedirs(proj)

    def asst(cr, rid="r", cc=100, inp=5):
        return {"type": "assistant", "isSidechain": True, "requestId": rid, "message": {"usage": {
            "input_tokens": inp, "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr}}}

    def sub(parent, agent, entries):
        d = os.path.join(proj, parent, "subagents")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"agent-{agent}.jsonl")
        with open(path, "w") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
        return path

    def payload(parent, agent=None, **kw):
        d = {"session_id": parent, "transcript_path": os.path.join(proj, parent + ".jsonl"), "cwd": home,
             "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "true"}}
        if agent:
            d["agent_id"] = agent
        d.update(kw)
        return json.dumps(d)

    def run(raw):
        global _file_cfg
        _file_cfg = None                                          # a hook is one process: its config is read afresh
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = hook(raw)
        s = out.getvalue()
        return rc, (json.loads(s)["hookSpecificOutput"] if s.strip() else None)

    def parallel(parent, agent):
        """Sixteen hooks for one agent at the save line, let go at once; the number that refused."""
        sub(parent, agent, [asst(95000)])
        gate_r, gate_w = os.pipe()
        res_r, res_w = os.pipe()
        kids = []
        for _ in range(16):
            pid = os.fork()
            if pid == 0:
                os.close(gate_w)
                os.read(gate_r, 1)   # every child blocks here until the gate closes
                global PAUSE
                PAUSE = 0.05                                      # so without a claim every child reads no record
                try:
                    said = run(payload(parent, agent))[1]
                    os.write(res_w, b"1" if said and said["permissionDecision"] == "deny" else b"0")
                finally:
                    os._exit(0)
            kids.append(pid)
        os.close(gate_w)
        os.close(res_w)
        for pid in kids:
            os.waitpid(pid, 0)
        got = b""
        while True:
            c = os.read(res_r, 64)
            if not c:
                break
            got += c
        os.close(gate_r)
        os.close(res_r)
        return got.count(b"1") if len(got) == 16 else -1

    try:
        # 1. under the save line (90000): the call runs, nothing is recorded
        sub("s1", "a1", [asst(9000), asst(80000)])
        rc, d = run(payload("s1", "a1"))
        ok("under the save line: no decision", rc == 0 and d is None)
        ok("under the save line: nothing recorded", not os.path.exists(os.path.join(STATE, "s1-a1.json"))
           and not os.path.exists(os.path.join(STATE, "s1-a1.json.saved")))

        # 2. far past the old 150000 bound after its save, on its own fixture: the calls run
        sub("s2", "a2", [asst(95000)])
        ok("the save comes first", (run(payload("s2", "a2"))[1] or {}).get("permissionDecision") == "deny")
        sub("s2", "a2", [asst(95000), asst(400000)])
        ok("400k after the save: the call runs", run(payload("s2", "a2"))[1] is None)
        ok("…and the next one too", run(payload("s2", "a2"))[1] is None)

        # 3. a first call already past 150000 with no save yet: refused once with the save order, then calls run
        sub("s3", "a3", [asst(200000)])
        rc, d = run(payload("s3", "a3"))
        ok("a first call past 150k: the save order", rc == 0 and d and d["permissionDecision"] == "deny"
           and d["permissionDecisionReason"].startswith("SAVE NOW") and "200,105" in d["permissionDecisionReason"])
        ok("the save order names no bound", "bound" not in d["permissionDecisionReason"]
           and "refused" not in d["permissionDecisionReason"])
        ok("the next call runs", run(payload("s3", "a3"))[1] is None)

        # 4. a session's own call (no agent_id) is never judged, however large its context
        with open(os.path.join(proj, "s4.jsonl"), "w") as fh:
            fh.write(json.dumps(asst(900000)) + "\n")
        sub("s4", "a4", [asst(900000)])
        ok("a session's own call: no decision", run(payload("s4"))[1] is None)
        ok("the same subagent's call: the save order", "SAVE NOW" in
           ((run(payload("s4", "a4"))[1] or {}).get("permissionDecisionReason") or ""))

        # 6. a compact after the last turn measures its postTokens; agent_transcript_path wins over the derived path
        sub("s6", "a6", [asst(400000), {"type": "system", "subtype": "compact_boundary",
                                          "compactMetadata": {"preTokens": 400000, "postTokens": 20000}}])
        ok("a compact brings it under: no decision", run(payload("s6", "a6"))[1] is None)
        other = sub("s6x", "elsewhere", [asst(300000)])
        ok("agent_transcript_path is the file read",
           (run(payload("s6", "a6", agent_transcript_path=other))[1] or {}).get("permissionDecision") == "deny")

        # 7. nothing readable decides nothing: bad JSON, a missing transcript, a first call with no turn yet, a bad id
        ok("bad JSON: no decision", run("{not json")[1] is None)
        ok("no transcript: no decision", run(payload("s7", "missing"))[1] is None)
        sub("s7", "fresh", [{"type": "user", "message": {"content": "go"}}])
        ok("no assistant turn yet: no decision", run(payload("s7", "fresh"))[1] is None)
        sub("s7", "a7", [asst(900000)])
        ok("an agent_id with a path in it: no decision", run(payload("s7", "../s7/subagents/agent-a7"))[1] is None)

        # 8. the file on disk is what is measured: a real transcript's usage shape, a half-written last line
        path = sub("s8", "a8", [asst(10, rid="x")])
        with open(path, "a") as fh:
            fh.write(json.dumps(asst(170000, rid="y")) + "\n" + '{"type":"assistant","message":{"usa')
        ok("a half-written last line is skipped", used_of(path) == 170105)

        # 9. measure: per-line and deduplicated sums, and the over-count by peak context
        mroot = os.path.join(home, "m")
        for parent, agent, entries in (("p", "big", [asst(200000, "r1"), asst(200000, "r1"), asst(310000, "r2")]),
                                       ("p", "small", [asst(1000, "q1"), asst(2000, "q2")])):
            d = os.path.join(mroot, "-dev-y", parent, "subagents")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"agent-{agent}.jsonl"), "w") as fh:
                fh.write("".join(json.dumps(e) + "\n" for e in entries))
        buf = io.StringIO()
        files, tot, n_over, big = measure(0, 300000, out=buf, root=mroot)
        ok("measure: files, per-line sum, dedup sum", files == 2 and tot == [713000, 513000])
        ok("measure: the over-count is by peak context", n_over == 1 and big == [710000, 510000])
        ok("measure: the report names both figures", "per line 0.00B" in buf.getvalue()
           and "deduplicated" in buf.getvalue())
        old = os.path.join(mroot, "-dev-y", "p", "subagents", "agent-small.jsonl")
        os.utime(old, (1000, 1000))
        ok("measure: --since drops an older file", measure(2000, 300000, out=io.StringIO(), root=mroot)[0] == 1)

        # 10. the early save: once at 90000, then every call runs
        sub("s10", "a10", [asst(90000 - 106)])
        ok("one token under the save line: no decision", run(payload("s10", "a10"))[1] is None)
        sub("s10", "a10", [asst(90000 - 105)])
        rc, d = run(payload("s10", "a10"))
        ok("at the save line: refused once with the save order", rc == 0 and d and d["permissionDecision"] == "deny"
           and "NOT run; run it again" in d["permissionDecisionReason"]
           and "names a file to write" in d["permissionDecisionReason"]
           and "keep writing as you go" in d["permissionDecisionReason"]
           and "write no files, write none" in d["permissionDecisionReason"]
           and "next calls run normally" in d["permissionDecisionReason"])
        rec = json.load(open(os.path.join(STATE, "s10-a10.json")))
        ok("the save is recorded", rec.get("saved") == 90000 and rec.get("save") == 90000 and "bound" not in rec)
        ok("the next call at the same size runs", run(payload("s10", "a10"))[1] is None)
        sub("s10", "a10", [asst(140000)])
        ok("a later, larger call runs", run(payload("s10", "a10"))[1] is None)
        # 0 turns it off; a set figure moves it; a save that cannot be recorded leaves the call alone
        sub("s10", "a10d", [asst(95000)])
        os.environ["CC_SUBAGENT_SAVE_TOKENS"] = "0"
        ok("save 0: off", run(payload("s10", "a10d"))[1] is None
           and not os.path.exists(os.path.join(STATE, "s10-a10d.json")))
        os.environ["CC_SUBAGENT_SAVE_TOKENS"] = "120000"
        ok("save set to 120k: 95k runs", run(payload("s10", "a10d"))[1] is None)
        sub("s10", "a10d", [asst(125000)])
        ok("save set to 120k: 125k is refused once",
           (run(payload("s10", "a10d"))[1] or {}).get("permissionDecision") == "deny")
        os.environ.pop("CC_SUBAGENT_SAVE_TOKENS")
        blocker = os.path.join(home, "not-a-dir")
        open(blocker, "w").close()
        state_ok, STATE = STATE, os.path.join(blocker, "state")
        sub("s10", "a10e", [asst(95000)])
        ok("an unrecordable save: no decision", run(payload("s10", "a10e"))[1] is None)
        STATE = state_ok

        # 11. parallel tool calls: sixteen hooks for one agent at the save line, let go at once, refuse it exactly once,
        # with the per-agent lock (a11) and with the lock unobtainable, a symlink O_NOFOLLOW refuses (a11n)
        os.makedirs(STATE, exist_ok=True)
        os.symlink(os.path.join(home, "elsewhere"), os.path.join(STATE, "s11-a11n.json.lock"))
        for ag in ("a11", "a11n"):
            ok(f"sixteen parallel hooks at the save line ({ag}): one save refusal, the rest run", parallel("s11", ag) == 1)
        ok("an unobtainable lock is never followed", not os.path.exists(os.path.join(home, "elsewhere")))

        # 12. the test pause is never read from the environment: a bad value there neither crashes nor slows the hook
        sub("s12", "a12", [asst(95000)])
        os.environ["CC_SUBAGENT_BOUND_PAUSE"] = "not-a-number"
        try:
            ok("a bad pause in the environment: the save order as before",
               "names a file to write" in ((run(payload("s12", "a12"))[1] or {}).get("permissionDecisionReason") or ""))
        finally:
            os.environ.pop("CC_SUBAGENT_BOUND_PAUSE", None)

        # 13. the save line from ~/.cc/config costs one cc-config call; set to 0 in the environment, none and off
        with open(os.environ["CC_CONFIG"], "w") as fh:
            fh.write("CC_SUBAGENT_SAVE_TOKENS=40000\nSLACK_OTHER=x\n")
        calls, real_run = [], subprocess.run
        subprocess.run = lambda cmd, *a, **k: (calls.append(cmd), real_run(cmd, *a, **k))[1]
        try:
            sub("s13", "a13", [asst(35000)])
            ok("config: under the file's 40k runs", run(payload("s13", "a13"))[1] is None)
            ok("config: one cc-config call", len(calls) == 1)
            sub("s13", "a13", [asst(45000)])
            ok("config: the save line is read from the file",
               (run(payload("s13", "a13"))[1] or {}).get("permissionDecision") == "deny")
            sub("s13", "a13b", [asst(400000)])
            calls.clear()
            os.environ["CC_SUBAGENT_SAVE_TOKENS"] = "0"
            ok("save 0 in the environment: off, with no cc-config call",
               run(payload("s13", "a13b"))[1] is None and calls == []
               and not os.path.exists(os.path.join(STATE, "s13-a13b.json.saved")))
        finally:
            subprocess.run = real_run
            os.environ.pop("CC_SUBAGENT_SAVE_TOKENS", None)
            open(os.environ["CC_CONFIG"], "w").close()

        # 14. pruning: a new agent's first lock deletes state older than PRUNE_DAYS, keeps the rest and other files
        old = time.time() - (PRUNE_DAYS + 1) * 86400
        for n in ("old-x.json", "old-x.json.lock", "old-x.json.saved", "keep.txt"):
            open(os.path.join(STATE, n), "w").close()
            os.utime(os.path.join(STATE, n), (old, old))
        open(os.path.join(STATE, "new-y.json.lock"), "w").close()
        sub("s14", "a14", [asst(1000)])
        run(payload("s14", "a14"))
        left = set(os.listdir(STATE))
        ok("prune: old state is deleted", not {"old-x.json", "old-x.json.lock", "old-x.json.saved"} & left)
        ok("prune: fresh state and other files stay", {"new-y.json.lock", "keep.txt", "s14-a14.json.lock"} <= left)
        open(os.path.join(STATE, "old-z.json"), "w").close()
        os.utime(os.path.join(STATE, "old-z.json"), (old, old))
        run(payload("s14", "a14"))
        ok("prune: an agent's later calls do not sweep", os.path.exists(os.path.join(STATE, "old-z.json")))
    finally:
        STATE = state0
        for k, v in env0.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(home, ignore_errors=True)
    print(f"cc-subagent-bound selfcheck: {p} passed, {f} failed")
    return 1 if f else 0
