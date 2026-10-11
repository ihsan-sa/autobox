# cc-native's selfcheck: the cases behind `cc-native selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-native execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.
# recurring-defect-ok: pause-hold-missing — moved test cases: the board writes and dispatches are fixtures in a temp tree, never a real one

def selfcheck():
    from concurrent.futures import ThreadPoolExecutor
    n = failed = 0
    def ok(label, cond):
        nonlocal n, failed
        n += 1; failed += not cond
        print(("  ok   " if cond else "  FAIL ") + label)
    with tempfile.TemporaryDirectory(prefix="ccnative-sc-") as th:
        root = Path(th); home = root / "home"; binpath = home / "bin"; binpath.mkdir(parents=True)
        env = {"HOME": str(home), "PATH": f"{binpath}:/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1",
               "CC_CONFIG": str(root / "config"), "CC_NATIVE_ADAPTER": "1", "CC_NATIVE_DEADLINE": "300"}
        for tool in ("cc-native", "cc-task", "cc", "cc-board", "cc-checkpoint", "cc-config"):
            shutil.copy2(BIN / tool, binpath / tool)
        # These fixture doors record any accidental live operation. Git uses only our own bare remote.
        for tool in ("tmux", "systemctl", "systemd-run", "gh", "cc-land", "cc-slack", "cc-notify", "claude"):
            p = binpath / tool
            p.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{root}/services"\nexit 1\n'); p.chmod(0o755)
        (binpath / "cc-trust").write_text("#!/bin/sh\nexit 0\n"); (binpath / "cc-trust").chmod(0o755)
        def run(*args, input=None, extra=None):
            return subprocess.run([str(x) for x in args], input=input, capture_output=True, text=True,
                                  env={**env, **(extra or {})}, cwd=home, timeout=600)
        def git(*args):
            r = run("git", *args)
            if r.returncode: raise ValueError(r.stderr)
            return r.stdout.strip()
        dev = home / "dev/r"; dev.mkdir(parents=True)
        git("config", "--global", "user.name", "fixture"); git("config", "--global", "user.email", "fixture@example.test")
        git("init", "-q", "-b", "main", dev); (dev / "base").write_text("base\n")
        git("-C", dev, "add", "."); git("-C", dev, "commit", "-qm", "base")
        remote = root / "remote.git"; git("init", "--bare", "-q", remote)
        git("-C", dev, "remote", "add", "origin", remote); git("-C", dev, "push", "-q", "origin", "main")
        run(binpath / "cc-board", "init", "r", dev, "main")
        for row in ("a", "b", "c", "bad"):
            run(binpath / "cc-board", "add", "r", row, row, "A fixture brief with acceptance criteria.")
        base = {"session_id": "parent", "transcript_path": str(root / "parent.jsonl"), "cwd": str(dev)}
        def spawn(row, tool="Agent"):
            return dict(base, hook_event_name="PreToolUse", tool_name=tool, tool_use_id=f"dispatch-{row}",
                        tool_input={"prompt": f"CC-Row: r/{row}\nBuild the row.", "description": "fixture change",
                                    "subagent_type": "builder", "isolation": "worktree"})
        def boot(token, agent, event=None):
            return dict(base, hook_event_name="PreToolUse", tool_name="Bash", agent_id=agent,
                        tool_use_id=event or f"begin-{agent}", tool_input={"command": f"cc-task begin {token}"})
        def end(agent):
            return dict(base, hook_event_name="SubagentStop", agent_id=agent, agent_type="builder",
                        agent_transcript_path=str(root / f"{agent}.jsonl"), stop_hook_active=False)
        def g(payload, flag="1", extra=None):
            return run(binpath / "cc-native", input=json.dumps(payload),
                       extra={"CC_NATIVE_ADAPTER": flag, **(extra or {})})
        def answer(r): return json.loads(r.stdout or "{}").get("hookSpecificOutput", {})
        def record(row): return home / f".cc/state/r/{row}/delivery.json"
        def load(row): return json.loads(record(row).read_text())
        def wt(row): return home / f".cc/worktrees/r/{row}"
        def snap(): return {str(p): p.read_bytes() for p in home.rglob("*") if p.is_file()}
        before = snap(); off = g(spawn("a"), "0")
        ok("N1: off dispatch decides and writes nothing; N2 is its control", off.returncode == 0 and not off.stdout and snap() == before)
        default = run(binpath / "cc-native", input=json.dumps(spawn("a")), extra={"CC_NATIVE_ADAPTER": ""})
        env.pop("CC_NATIVE_ADAPTER"); absent = run(binpath / "cc-native", input=json.dumps(spawn("a")))
        env["CC_NATIVE_ADAPTER"] = "1"
        ok("N1 default control: an absent or empty flag is off", not default.stdout and not absent.stdout and snap() == before)
        # Two payloads of one parent wait at the same lock, then claim separate rows. They are real hook
        # processes, not function calls, and the parent stays alive through both bootstraps and both ends.
        lockdir = home / ".cc/native"
        with task.Lock(lockdir):
            ps = [subprocess.Popen([str(binpath / "cc-native")], env=env, cwd=home, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
            for p, row in zip(ps, ("a", "b")): p.stdin.write(json.dumps(spawn(row, "Task" if row == "b" else "Agent"))); p.stdin.close(); p.stdin = None
            time.sleep(.15); held = all(p.poll() is None for p in ps)
        outputs = [json.loads(p.communicate(timeout=600)[0])["hookSpecificOutput"] for p in ps]
        if any(a["permissionDecision"] != "allow" for a in outputs): raise ValueError(f"fixture dispatch: {outputs}")
        tokens = [task.native_token(record(row).parent, load(row)["claim"]) for row in ("a", "b")]
        ok("N2: concurrent Agent and Task dispatches prepare distinct canonical trees and tokens", held and all(p.returncode == 0 for p in ps)
           and all(a["permissionDecision"] == "allow" and "isolation" not in a["updatedInput"] for a in outputs)
           and len(set(tokens)) == 2 and all(str(wt(row)) in a["updatedInput"]["prompt"] and load(row)["task_id"] in a["updatedInput"]["prompt"]
               and git("-C", wt(row), "branch", "--show-current") == f"track/{row}" for row, a in zip(("a", "b"), outputs)))
        before = record("a").read_bytes(); replay = g(spawn("a"))
        refused = g(dict(spawn("a"), tool_use_id="another-dispatch"))
        ok("N3: replay keeps the same token; another dispatch of that row is a request that must be refused; N2 is its control",
           answer(replay) == outputs[0] and answer(refused).get("permissionDecision") == "deny" and record("a").read_bytes() == before)
        unbound = run(binpath / "cc-task", "begin", tokens[0])
        before = snap(); g(boot(tokens[0], "child-a"), "0"); g(end("child-a"), "0")
        offbegin = run(binpath / "cc-task", "begin", tokens[0], extra={"CC_NATIVE_ADAPTER": "0"})
        ok("N4: begin with no binding is a request that must be refused; off bootstrap/end/begin write nothing; N5 is its control",
           unbound.returncode != 0 and offbegin.returncode == 0 and not offbegin.stdout and snap() == before)
        with ThreadPoolExecutor(2) as pool:
            bindings = list(pool.map(g, [boot(token, agent) for token, agent in zip(tokens, ("child-a", "child-b"))]))
        begins = [run(binpath / "cc-task", "begin", token) for token in tokens]
        ok("N5: both children of one parent bind their own row and begin returns its worktree, brief and journal",
           all(r.returncode == 0 and not r.stdout for r in bindings) and all(r.returncode == 0 for r in begins)
           and all(json.loads(r.stdout)["worktree"] == str(wt(row)) and json.loads(r.stdout)["task.md"] == str(record(row).parent / "task.md")
                   and json.loads(r.stdout)["progress.md"] == str(record(row).parent / "progress.md")
                   and load(row)["claim"]["owner"]["agent_id"] == agent for row, agent, r in zip(("a", "b"), ("child-a", "child-b"), begins)))
        before = snap()
        for label, payload in (("sibling token", boot(tokens[1], "child-a")),
                               ("second use", boot(tokens[0], "child-a", "second-begin")),
                               ("missing agent", {k: v for k, v in boot(tokens[0], "child-a").items() if k != "agent_id"}),
                               ("wrong parent", dict(boot(tokens[0], "child-a"), session_id="other")),
                               ("no live claim", boot("absent-token", "child-c"))):
            refused = g(payload); off = g(payload, "0")
            ok(f"N6 {label}: a request that must be refused; N5 is its control; off decides nothing",
               answer(refused).get("permissionDecision") == "deny" and not off.stdout and off.returncode == 0 and snap() == before)
        ok("N6 replay control: the same bootstrap hook is idempotent; a second begin command cannot consume it again",
           not g(boot(tokens[0], "child-a")).stdout and run(binpath / "cc-task", "begin", tokens[0]).returncode != 0 and snap() == before)
        for row in ("a", "b"): (wt(row) / "change").write_text(f"{row}\n")
        (dev / "planner-only").write_text("leave dirty\n"); before = snap()
        unknown = g(end("unknown")); g(end("unknown"), "0")
        for agent in ("child-a", "child-b"): g(end(agent), "0")
        ok("N7: unknown and off ends commit nothing; N8 is their control", not unknown.stdout and unknown.returncode == 0 and snap() == before)
        with ThreadPoolExecutor(2) as pool: list(pool.map(g, [end(agent) for agent in ("child-a", "child-b")]))
        ok("N8: both ends commit their bound tree, record the SHA and release ready while the parent stays dirty",
           all(load(row)["artifact"]["committed_sha"] == git("-C", wt(row), "rev-parse", "HEAD")
               and not git("-C", wt(row), "status", "--porcelain") and load(row)["claim"]["ended_at"]
               and load(row)["claim"]["phase"] == "ready" and load(row)["claim"]["live"] is False for row in ("a", "b"))
           and "planner-only" in git("-C", dev, "status", "--porcelain") and git("--git-dir", remote, "for-each-ref", "--format=%(refname)") == "refs/heads/main")
        before = snap(); g(end("child-a"))
        ok("N8 replay control: a repeated end changes no byte", snap() == before)
        for mode in ("secret", "wrong-head", "default", "lying-path", "commit-failure", "worker-takeover"):
            row = "c"; g(dict(spawn(row), tool_use_id=mode)); token = task.native_token(record(row).parent, load(row)["claim"])
            agent = f"child-{mode}"; g(boot(token, agent)); run(binpath / "cc-task", "begin", token)
            original = git("-C", wt(row), "rev-parse", "HEAD"); change = wt(row) / (".env" if mode == "secret" else "change")
            change.write_text(f"{mode}\n")
            hookfile = dev / ".git/hooks/pre-commit"
            if mode == "wrong-head": git("-C", wt(row), "checkout", "-q", "--detach")
            if mode == "default": git("-C", wt(row), "symbolic-ref", "HEAD", "refs/heads/main")
            if mode == "lying-path":
                d = load(row); d["worktree"] = str(dev); record(row).write_text(json.dumps(d))
            if mode == "commit-failure": hookfile.write_text("#!/bin/sh\nexit 1\n"); hookfile.chmod(0o755)
            if mode == "worker-takeover": run(binpath / "cc-task", "claim", "r", row, "--executor", "worker")
            g(end(agent)); d = load(row)
            if mode == "lying-path":
                ok("N9 lying record control: end derives the tree from its state path; the planner stays dirty",
                   git("-C", wt(row), "rev-parse", "HEAD") != original and (dev / "planner-only").exists())
            else:
                ok(f"N9 {mode}: a request that must be refused; N8 is its control",
                   git("-C", wt(row), "rev-parse", "HEAD") == original and change.exists()
                   and (d["claim"]["executor"] == "worker" if mode == "worker-takeover" else
                        d["claim"]["phase"] == "blocked" and bool(d["artifact"]["errors"])))
            if hookfile.exists(): hookfile.unlink()
            if mode in ("wrong-head", "default"): git("-C", wt(row), "symbolic-ref", "HEAD", "refs/heads/track/c")
            change.unlink()
        before = snap()
        noheader = dict(spawn("legacy"), tool_input={"prompt": "Build the legacy row.", "isolation": "worktree"})
        for payload in (noheader, dict(spawn("a"), tool_name="Read"), dict(base, hook_event_name="SubagentStart", agent_id="child")):
            r = g(payload); ok("N10: an unowned payload decides nothing; N2 is its control", r.returncode == 0 and not r.stdout and snap() == before)
        # A legacy Agent stand-in owns its .claude tree. The unchanged call reaches it; the builder leaves
        # dirty work, and only the fixture planning session commits and records its PR request.
        legacy = dev / ".claude/worktrees/agent-legacy"
        git("-C", dev, "worktree", "add", "-q", "-b", "planning/legacy", legacy)
        (legacy / "legacy-change").write_text("legacy\n"); old = git("-C", legacy, "rev-parse", "HEAD")
        g(end("legacy")); dirty = git("-C", legacy, "status", "--porcelain")
        git("-C", legacy, "add", "."); git("-C", legacy, "commit", "-qm", "session commits legacy")
        (root / "legacy-pr-request").write_text("session: open PR for planning/legacy\n")
        ok("N11: no-header legacy keeps its Agent tree and planning branch; only the session commits and requests its PR",
           dirty and old != git("-C", legacy, "rev-parse", "HEAD") and not record("legacy").exists()
           and git("-C", legacy, "branch", "--show-current") == "planning/legacy")
        record("bad").write_text("unreadable JSON"); before = snap(); r = g(spawn("bad"))
        nojq = root / "no-jq"; nojq.mkdir(); (nojq / "python3").symlink_to(sys.executable)
        missing = g(spawn("a"), extra={"PATH": str(nojq)})
        malformed = run(binpath / "cc-native", input="not json")
        unreadable = g(boot("r/bad/token", "child-bad"))
        ok("N12: unreadable record, malformed payload and no jq decide and write nothing; N2 is their control",
           all(r.returncode == 0 and not r.stdout for r in (r, missing, malformed, unreadable)) and snap() == before)
        # A claim refusal from cc is its own reason, not an adapter paraphrase.
        payload = spawn("missing"); payload["tool_input"]["prompt"] = "CC-Row: absent/missing\nBuild."
        r = g(payload); direct = run(binpath / "cc", "claim", "absent", "missing", "--executor", "subagent")
        ok("N13: cc's refused claim is a request that must be refused with its own message; N2 is its control",
           answer(r).get("permissionDecision") == "deny" and answer(r)["permissionDecisionReason"] == (direct.stdout + direct.stderr).strip())
        # The budget still binds when the fixture's own is short: a claim that stalls is killed, group and all,
        # and the dispatch is refused. N2 is its control, the same dispatch allowed under the wide fixture budget.
        slow = root / "slow-bin"; slow.mkdir()
        for tool in ("cc-native", "cc-task", "cc-config"): shutil.copy2(BIN / tool, slow / tool)
        (slow / "cc").write_text(f'#!/bin/sh\necho $$ > "{root}/slow-pid"\nexec sleep 60\n'); (slow / "cc").chmod(0o755)
        started = time.monotonic()
        r = run(slow / "cc-native", input=json.dumps(spawn("slow")), extra={"CC_NATIVE_DEADLINE": "2"})
        took = time.monotonic() - started; pid = int((root / "slow-pid").read_text() or 0)
        try: os.kill(pid, 0); stalled = True
        except ProcessLookupError: stalled = False
        ok("N15: a claim past CC_NATIVE_DEADLINE is killed and refused; N2 is its control",
           answer(r).get("permissionDecisionReason") == "cc-native: claim/checkpoint deadline expired"
           and not stalled and took < 50 and not record("slow").exists())
        saved = os.environ.get("CC_NATIVE_DEADLINE")
        try:
            widths = []
            for value in ("", "abc", "0", "-5", "nan", "inf", "300"):
                os.environ["CC_NATIVE_DEADLINE"] = value; widths.append(budget())
        finally:
            if saved is None: os.environ.pop("CC_NATIVE_DEADLINE", None)
            else: os.environ["CC_NATIVE_DEADLINE"] = saved
        ok("N15 default control: an absent, unreadable or non-positive CC_NATIVE_DEADLINE is the 11 s budget",
           widths == [11.0] * 6 + [300.0])
        calls = (root / "services").read_text() if (root / "services").exists() else ""
        ok("N14: no service, PR, queue or push was called by any managed hook; N8 records only local commits",
           not calls.strip())
    # The tally shape selftest.sh's chk() anchors on ("…: 0 failed" / "…, 0 failed", selftest.sh:121-123):
    # anything else is read as no tally at all, which is how it says a selfcheck died.
    print(f"cc-native selfcheck: {n - failed} passed, {failed} failed"); return 1 if failed else 0
