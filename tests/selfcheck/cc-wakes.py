# cc-wakes's selfcheck: the cases behind `cc-wakes selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-wakes execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    """Each case writes its own session's transcript into a HOME of its own and reads back only that session's
    rows, asserting what is kept and what is not."""
    home, day = tempfile.mkdtemp(prefix="cc-wakes."), "2026-01-10"
    proj, dev, wt = os.path.join(home, ".claude", "projects"), os.path.join(home, "dev", "r1"), \
        os.path.join(home, ".cc", "worktrees", "r1", "t1")
    n = [0]

    def rec(t, cwd, d=day, **kw):
        n[0] += 1
        return dict(type=t, cwd=cwd, sessionId="sid", timestamp=f"{d}T10:{n[0] % 60:02d}:00Z", **kw)
    def user(content, cwd=dev, **kw):
        return rec("user", cwd, message={"role": "user", "content": content}, **kw)
    def asst(rid, rd, cwd=dev, cw=0, out=0, uses=(), lead=(), **kw):
        blocks = list(lead) + [{"type": "tool_use", "id": i, "name": nm, "input": inp} for i, nm, inp in uses]
        return rec("assistant", cwd, requestId=rid, message={"model": "claude-opus-5", "content": blocks, "usage": {
            "input_tokens": 0, "output_tokens": out, "cache_read_input_tokens": rd, "cache_creation_input_tokens": cw}},
            **kw)
    attach = lambda a: rec("attachment", dev, attachment=a)
    think = {"type": "thinking", "thinking": "", "signature": "s" * 800}
    result = lambda i, size: user([{"type": "tool_result", "tool_use_id": i, "content": "x" * size}])
    def put(rel, recs):                   # one JSON line per record; a one-record list is a .meta.json too
        p = os.path.join(proj, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in recs))

    kick = "[cc-handoff] ab: you are the SUCCESSOR for r1 - go".ljust(229) + "."
    relay = '<channel source="cc-slack" chat_id="{}" user="u" role="owner">hi</channel>'
    brief = [("t1", "Bash", {"command": "cc-handoff --brief r1"})]
    put("-p/s1.jsonl", [user(kick), asst("a1", 10000, cw=100, out=50, uses=brief), result("t1", 2300),
                        asst("a2", 10150), asst("a2", 10150), user(relay.format("C1")), asst("a3", 12000), user(relay.format("local")), asst("a4", 12100)])
    put("-p/s2.jsonl", [user(kick.replace("for r1", "for r1@al")), asst("b1", 500)])
    put("-p/s2p.jsonl", [user(kick), asst("b2", 500)])
    rd = [("Read", {"file_path": "/x/f"}), ("Read", {"file_path": "/x/f", "offset": 5}),
          ("Bash", {"command": "sed -n 1,5p /x/g 2>/dev/null"}), ("Bash", {"command": "cd /x && tail -3 /x/g"}),
          ("Read", {"file_path": "/x/h"}), ("Bash", {"command": "cat /x/f /x/k"})]
    s3 = [user("look"), asst("c0", 1000)]
    for i, (nm, inp) in enumerate(rd):
        s3 += [asst(f"c{i + 1}", 5000, uses=[(f"u{i}", nm, inp)]), result(f"u{i}", 230)]
    put("-p/s3.jsonl", s3 + [asst("c9", 5000)])
    put("-w/w1.jsonl", [user("# TASK\ngo\n# THIS ITERATION\nIteration 1 of 3.", wt), asst("d1", 100, wt)])
    put("-w/w2.jsonl", [user("# TASK\ngo\n# THIS ITERATION\nIteration 2 of 3.", wt), asst("e1", 100, wt)])
    put("-p/s5.jsonl", [user("spawn it"), asst("f1", 100), asst("sub1", 7777, isSidechain=True)])
    put("-p/s5/subagents/agent-1.jsonl", [user("build", isSidechain=True), asst("sub1", 7777, isSidechain=True)])
    put("-p/s5/subagents/agent-1.meta.json", [{"agentType": "builder"}])
    put("-p/s6.jsonl", [user("old"), asst("g1", 300, d="2026-01-09"), user("<command-name>/model</command-name>"),
                        user("new"), asst("g2", 400)])
    put("-p/s7.jsonl", [user("hello"), asst("h1", 10), user("<task-notification> done"), asst("h2", 10),
                        rec("system", dev, subtype="scheduled_task_fire"), user("Re-mark the row"), asst("h3", 10),
                        user("what now"), asst("h4", 10)])
    put("-p/s8.jsonl", [user("go"), attach({"type": "skill_listing", "content": "s" * 230}), asst("i1", 0, cw=1000),
                        attach({"type": "total_tokens_reminder", "text": "r" * 2300}),
                        attach({"type": "prompt_snapshot", "systemPrompt": ["p" * 23000]}),
                        asst("i2", 1000, cw=1000), asst("i3", 2000)])
    put("-p/s9.jsonl", [user("go"), asst("j1", 0, cw=1000, lead=[{"type": "text", "text": "y" * 2300}]),
                        user("more"), asst("j2", 1000, cw=1000), asst("j3", 2000)])
    for sid, lead in (("s10", [think]), ("s10n", [])):
        put(f"-p/{sid}.jsonl", [user("go"), asst(sid + "1", 0, cw=1000, lead=lead, uses=[("k", "Read", {"file_path": "/x/z"})]),
                                result("k", 230), asst(sid + "2", 1000, cw=600), asst(sid + "3", 1600)])

    def run():
        env = dict(os.environ, HOME=home, TZ="UTC")
        p = subprocess.run([sys.executable, os.path.realpath(__file__), "--from", day, "--to", day, "--repo", "r1"],
                           env=env, capture_output=True, text=True)
        trace = os.path.join(home, ".cc", "state", "r1", "replay", f"wakes-{day}..{day}.tsv")
        with open(trace) as f:
            return p.stdout + p.stderr, f.read()

    (out1, tsv1), (out2, tsv2) = run(), run()
    rows = [dict(zip(COLS, line.split("\t"))) for line in tsv1.splitlines()[1:]]
    of = lambda s: [r for r in rows if r["session"] == s]
    s1, s3 = of("s1"), of("s3")
    near = lambda rs, c, v: len(rs) == 1 and abs(float(rs[0][c]) - v) < 3
    cases = [
        ("a successor's kick is a handoff wake-up, its brief is carried as handoff, a split response counts once",
         [(r["kind"], r["cause"]) for r in s1][:1] == [("planning", "handoff")] and s1[0]["requests"] == "2"
         and s1[0]["cache_read"] == "20150" and s1[0]["rd_handoff"] == "100" and s1[0]["handoff_bytes"] == "2530"
         and s1[1]["rd_handoff"] == "1100" and abs(float(s1[0]["rd_usd"]) - 0.010075) < 1e-4),
        ("a real channel's owner line is a person; the same line relayed locally is a pulse",
         [r["cause"] for r in s1] == ["handoff", "person", "pulse"]),
        ("a kick naming <repo>@<alias> makes an orch; one naming the repo alone a planning seat",
         [r["kind"] for r in of("s2") + of("s2p")] == ["orch", "planning"]),
        ("a file read again, any slice, is a re-read carried to the end; a new file, or one new among old, is not",
         [r["rereads"] for r in s3] == ["2"] and s3[0]["rd_reread"] == "600"),
        ("a worker's second iteration is a handoff, its first a start",
         [(r["kind"], r["cause"]) for r in of("w2") + of("w1")] == [("worker", "handoff"), ("worker", "start")]),
        ("a subagent's file is its own kind and counts its request; the parent's sidechain copy is not counted",
         [(r["kind"], r["cache_read"]) for r in of("agent-1")] == [("subagent/builder", "7777")]
         and [r["cache_read"] for r in of("s5")] == ["100"]),
        ("a wake-up outside the window is left out, and a prompt that made no request is no wake-up",
         [(r["cause"], r["cache_read"]) for r in of("s6")] == [("person", "400")]),
        ("a task notification and a cron fire are pulses; later text with no marker is a person",
         [r["cause"] for r in of("s7")] == ["start", "pulse", "pulse", "person"]),
        ("a harness reminder after the first request is harness; one before it stays in base; a prompt snapshot is "
         "never sent, so is not counted", near(of("s8"), "rd_harness", 1000) and near(of("s8"), "ctx_base", 999)
         and near(of("s8"), "rd_unattr", 0)),
        ("a response's own text is carried as work, though the transcript's output_tokens says 0",
         [r["cause"] for r in of("s9")] == ["start", "person"] and abs(float(of("s9")[1]["rd_work"]) - 1000) < 3
         and float(of("s9")[1]["rd_unattr"]) < 3),
        ("growth past a thinking response's pieces is its redacted thinking, carried as work; the same growth after a "
         "response that did not think stays unattributed",
         near(of("s10"), "rd_work", 600) and near(of("s10"), "rd_unattr", 0)
         and near(of("s10n"), "rd_work", 113) and near(of("s10n"), "rd_unattr", 489)),
        ("the same records give the same bytes, table and trace", out1 == out2 and tsv1 == tsv2 and "handoff" in out1),
    ]
    bad = [name for name, ok in cases if not ok]
    print("\n".join(("  ok   " if ok else "  FAIL ") + name for name, ok in cases) + ("\n" + out1 if bad else ""))
    print(f"cc-wakes selfcheck: {len(cases) - len(bad)} passed, {len(bad)} failed")
    return 1 if bad else 0
