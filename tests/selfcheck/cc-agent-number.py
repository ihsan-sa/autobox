# cc-agent-number's selfcheck: the cases behind `cc-agent-number selfcheck`. Not a module: the tool execs this file
# INSIDE ITS OWN NAMESPACE and calls the selfcheck() it defines, so `__file__` is the tool. No module docstring (it
# would replace the tool's __doc__) and no top-level name but the def below.

def selfcheck():
    import subprocess
    import tempfile
    n = f = 0

    def check(name, cond, got=None):
        nonlocal n, f
        n += 1
        print(("  ok   " if cond else "  FAIL ") + name + ("" if cond or got is None else "  << %r" % (got,)))
        if not cond:
            f += 1

    def spawn(d, k):   # k agents started at once, each its own process, as the box's spawners are
        env = dict(os.environ, CC_STATE=d)
        ps = [subprocess.Popen([__file__, "next", "test", f"t{i}", "0"], env=env, stdout=subprocess.PIPE, text=True)
              for i in range(k)]
        return [p.communicate()[0].strip() for p in ps]

    # Each case has a ledger of its own.
    with tempfile.TemporaryDirectory() as d:
        got = spawn(d, 2)
        check("two agents started at once get two different numbers", len(set(got)) == 2 and set(got) == {"a1", "a2"}, got)
    with tempfile.TemporaryDirectory() as d:
        got = spawn(d, 20)
        check("twenty at once get twenty numbers, a1..a20, none twice", sorted(got) == sorted(f"a{i}" for i in range(1, 21)), got)
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "agent-numbers.jsonl"), "w") as fh:
            fh.write(json.dumps({"n": 41, "id": "a41"}) + "\n" + '{"n": 4')   # a restart, after a write torn by a crash
        got = spawn(d, 1) + spawn(d, 1)
        check("after a restart the sequence carries on past a torn last line, and the take after it moves on",
              got == ["a42", "a43"], got)
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "agent-numbers.jsonl"), "w") as fh:
            fh.write(json.dumps({"n": 500, "name": "x" * 10000}) + "\n" + '{"n": Infinity}\n')
        got = spawn(d, 1)
        check("a line longer than any window still counts, and an n of Infinity is skipped", got == ["a501"], got)
    with tempfile.TemporaryDirectory() as d:
        led = os.path.join(d, "agent-numbers.jsonl")
        with open(led, "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)   # a holder that never lets go
            t = time.monotonic()
            r = subprocess.run(["bash", "-c", 'n=$("$0" next test t 0 2>/dev/null); echo "started${n:+ $n}"', __file__],
                               env=dict(os.environ, CC_STATE=d), capture_output=True, text=True, timeout=30)
            took = time.monotonic() - t
        check("a stuck lock holder costs a take its deadline, then it gives up and the caller starts without a number",
              r.stdout == "started\n" and LOCK_WAIT <= took < LOCK_WAIT + 3, (r.stdout, round(took, 1)))
    # THE CALLERS' OWN LINES, read from the tools and run against a stub cc-agent-number that hands out a99, so the
    # case runs what ships, not a copy of it.
    bindir = os.path.dirname(os.path.realpath(__file__))
    src = lambda tool, word: next(ln for ln in open(os.path.join(bindir, tool)) if word in ln)
    with tempfile.TemporaryDirectory() as d:
        with open(f"{d}/cc-agent-number", "w") as fh:
            fh.write("#!/bin/sh\necho a99\n")
        with open(f"{d}/tmux", "w") as fh:
            fh.write('#!/bin/sh\nfor a; do last=$a; done; printf %s "$last"\n')
        os.chmod(f"{d}/cc-agent-number", 0o755); os.chmod(f"{d}/tmux", 0o755)
        loop = src("cc-loop", 'CC_AGENT_NO=${AGENTNO:-')
        def run(script, **e):
            env = {k: v for k, v in os.environ.items() if k not in ("CC_AGENT_NO", "CC_MEMBER_SANDBOX")}
            return subprocess.run(["bash", "-c", script], env=dict(env, BIN=d, PATH=f"{d}:{env['PATH']}", **e),
                                  capture_output=True, text=True, timeout=30).stdout
        got = [run(loop + 'echo "$CC_AGENT_NO"', **e).strip() for e in
               ({}, {"CC_AGENT_NO": "a5"}, {"AGENTNO": "a5"})]
        check("cc-loop takes a new number for its worker, never its spawner's, but keeps the one the host passed a "
              "member's loop as --agent-no", got == ["a99", "a99", "a5"], got)
        member = (src("cc", 'n=$("$BIN/cc-agent-number" next worker') +
                  src("cc", "tmux new-window -d -t \"$SESSION\" -n \"$win\" -c \"$wt\" \"$(printf '%s%q member"))  # recurring-defect-ok: pause-hold-missing — runs the real line against a stub tmux; launches nothing
        got = run(member, SESSION="s", win="w", wt=d, repo="r", track="t", LOOPN="2")
        check("cc --go for a member's workspace takes the number on the host and puts it in the loop's window",
              " member r t -- cc-loop r t --max-iter 2 --agent-no a99" in got and "CC_AGENT_NO" not in got, got)
    chk = src("cc-loop", '--agent-no must be')
    got = [subprocess.run(["bash", "-c", chk + "echo ok"], env=dict(os.environ, AGENTNO=v), capture_output=True, text=True)
           for v in ("a12", "12", "a1;x")]
    check("cc-loop accepts --agent-no a12 and refuses 12 and a1;x with exit 2 before any work",
          [(r.returncode, r.stdout) for r in got] == [(0, "ok\n"), (2, ""), (2, "")], got)
    print(f"cc-agent-number selfcheck: {n - f} passed, {f} failed")
    return 1 if f else 0
