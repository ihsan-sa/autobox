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
                           ("CC_SUBAGENT_CONTEXT_TOKENS", "CC_SUBAGENT_WRAPUP_TOKENS", "CC_CONFIG")}
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
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = hook(raw)
        s = out.getvalue()
        return rc, (json.loads(s)["hookSpecificOutput"] if s.strip() else None)

    try:
        # 1. under the bound: the call runs, nothing is recorded
        sub("s1", "a1", [asst(9000), asst(100000)])
        rc, d = run(payload("s1", "a1"))
        ok("under the bound: no decision", rc == 0 and d is None)
        ok("under the bound: no crossing recorded", not os.path.exists(os.path.join(STATE, "s1-a1.json")))

        # 2. at the bound exactly, on its own fixture: refused with the wrap-up order, and the crossing recorded
        sub("s2", "a2", [asst(9000), asst(150000 - 105)])
        rc, d = run(payload("s2", "a2"))
        ok("at the bound: refused", rc == 0 and d and d["permissionDecision"] == "deny")
        ok("the refusal orders a save and a report", d and "progress file" in d["permissionDecisionReason"]
           and "re-spawn" in d["permissionDecisionReason"] and "150,000" in d["permissionDecisionReason"])
        ok("the crossing is recorded", json.load(open(os.path.join(STATE, "s2-a2.json")))["used"] == 150000)
        # one token under, a sibling: untouched
        sub("s2", "a2b", [asst(150000 - 106)])
        ok("one token under the bound: no decision", run(payload("s2", "a2b"))[1] is None)

        # 3. inside the wrap-up room the calls run; past it every call is refused with the stop order
        sub("s3", "a3", [asst(200000)])
        run(payload("s3", "a3"))
        sub("s3", "a3", [asst(200000), asst(229000)])
        ok("inside the wrap-up room: the call runs", run(payload("s3", "a3"))[1] is None)
        sub("s3", "a3", [asst(200000), asst(229000), asst(240000)])
        rc, d = run(payload("s3", "a3"))
        ok("past the wrap-up room: refused with the stop order",
           d and d["permissionDecision"] == "deny" and "End your turn now" in d["permissionDecisionReason"])
        ok("…and again on the next call", (run(payload("s3", "a3"))[1] or {}).get("permissionDecision") == "deny")

        # 4. a session's own call (no agent_id) is never judged, however large its context
        with open(os.path.join(proj, "s4.jsonl"), "w") as fh:
            fh.write(json.dumps(asst(900000)) + "\n")
        sub("s4", "a4", [asst(900000)])
        ok("a session's own call: no decision", run(payload("s4"))[1] is None)
        ok("the same subagent's call: refused", (run(payload("s4", "a4"))[1] or {}).get("permissionDecision") == "deny")

        # 5. the bound is configurable, and 0 switches it off
        sub("s5", "a5", [asst(60000)])
        os.environ["CC_SUBAGENT_CONTEXT_TOKENS"] = "50000"
        ok("a lower configured bound refuses at 60k", (run(payload("s5", "a5"))[1] or {}).get("permissionDecision") == "deny")
        sub("s5", "a5b", [asst(60000)])
        os.environ["CC_SUBAGENT_CONTEXT_TOKENS"] = "0"
        ok("bound 0: off", run(payload("s5", "a5b"))[1] is None)
        with open(os.environ["CC_CONFIG"], "w") as fh:
            fh.write("CC_SUBAGENT_CONTEXT_TOKENS=50000\n")
        os.environ.pop("CC_SUBAGENT_CONTEXT_TOKENS")
        ok("the bound is read from ~/.cc/config", (run(payload("s5", "a5b"))[1] or {}).get("permissionDecision") == "deny")
        open(os.environ["CC_CONFIG"], "w").close()

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
