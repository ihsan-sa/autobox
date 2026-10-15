# cc-voice's selfcheck: the cases behind `cc-voice selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-voice execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    import tempfile
    n = f = 0

    def check(name, cond):
        nonlocal n, f
        n += 1
        print(("  ok   " if cond else "  FAIL ") + name)
        if not cond:
            f += 1

    def err_of(argv, timeout=None, device=None):
        e = dict(env, CC_VOICE_TIMEOUT=timeout) if timeout else env   # a 1 s cap: the hang case must not wait out 420
        e = dict(e, CC_VOICE_DEVICE=device) if device else e
        r = subprocess.run([os.path.realpath(__file__)] + argv, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, env=e, timeout=120)
        return r.returncode, r.stdout, r.stderr

    # A BOX OF ITS OWN: a fake venv whose python prints a transcript, a fake `claude` that records what it was
    # asked and answers, and a fake recording. No weights are downloaded, no model is called, no ~/.cc is read.
    box = tempfile.mkdtemp(prefix="cc-voice-selfcheck-")
    os.makedirs(f"{box}/venv/bin")
    os.makedirs(f"{box}/models/fake")
    open(f"{box}/models/fake/model.bin", "w").write("weights")
    audio = f"{box}/audio_message.m4a"
    open(audio, "wb").write(b"\x00\x00\x00\x1cftypM4A \x00\x00\x00\x00 not really audio")
    SAID = ("so um the thing is I was thinking maybe we should uh no actually — ship the loop fix first, "
            "then the board thing, and tell me when the PR is up")
    with open(f"{box}/venv/bin/python", "w") as fh:
        fh.write(f'#!/bin/sh\nprintf %s "$*" > {box}/whisper.argv\n'
                 f'echo \'{{"text": "{SAID}", "seconds": 12.4, "language": "en"}}\'\n')
    os.chmod(f"{box}/venv/bin/python", 0o755)
    with open(f"{box}/claude", "w") as fh:
        fh.write(f'#!/bin/sh\nprintf %s "$*" > {box}/claude.argv\ncat > {box}/claude.stdin\n'
                 f'cat {box}/claude.out\n')
    os.chmod(f"{box}/claude", 0o755)
    open(f"{box}/claude.out", "w").write(json.dumps({"result": "Ship the loop fix first, then the board change, "
                                                               "and tell me when the PR is up.", "is_error": False}))
    env = dict(os.environ, CC_VOICE_DIR=box, CC_CLAUDE=f"{box}/claude", CC_VOICE_MODEL="large-v3-turbo")
    env.pop("CC_VOICE_FAKE", None)

    rc, out, _ = err_of(["text", audio])
    d = json.loads(out) if rc == 0 else {}
    prompt = open(f"{box}/claude.stdin").read() if os.path.exists(f"{box}/claude.stdin") else ""
    argv = open(f"{box}/claude.argv").read() if os.path.exists(f"{box}/claude.argv") else ""
    check("text: both halves come back — the transcript as spoken, and the condensed message under it",
          rc == 0 and d.get("transcript") == SAID and d.get("condensed", "").startswith("Ship the loop fix")
          and d.get("seconds") == 12.4 and d.get("model") == "large-v3-turbo")
    check("text: the recording is read by the LOCAL transcriber and its path never reaches the model call",
          audio in open(f"{box}/whisper.argv").read() and audio not in prompt and audio not in argv)
    check("the condensing call is one turn of the small model with NO tools — nothing it reads can act",
          "--model sonnet" in argv and "--tools" in argv and "--max-turns 1" in argv
          and "--no-session-persistence" in argv)
    # …AND THE OTHER TWO LAYERS, on the ARGV that was actually sent: a list that is right in the file and never
    # reaches the call is the same hole. Until 2026-09-06 there was no --disallowedTools here, and the prompt is a
    # recording somebody sent to Slack — the least trustworthy input on this box.
    parts = argv.split()          # the fake records "$*"; the deny list is one argv word, so it survives the join
    denied = set((parts[parts.index("--disallowedTools") + 1] if "--disallowedTools" in parts else "").split(","))
    check("…and names the escape hatches by tool as well, the WHOLE list and not a prefix of it — `Bash` alone is "
          "not enough, a probe once reached the shell through `Monitor`, and the four read tools go too because "
          "this call answers from the transcript alone",
          {"Bash", "BashOutput", "KillShell", "Edit", "Write", "MultiEdit", "NotebookEdit", "WebFetch",
           "WebSearch", "Agent", "Task", "Monitor", "Workflow", "Skill", "ToolSearch", "CronCreate", "CronDelete",
           "CronList", "ScheduleWakeup", "SendMessage", "RemoteTrigger", "PushNotification", "DesignSync",
           "ListAgents", "EnterWorktree", "ExitWorktree", "Read", "Grep", "Glob", "LS"} <= denied)
    # THE DRIFT CASE. cc-audit's SECRET_PATHS is the canonical list and is READ from it rather than spelled out
    # here, because hand-copying is what left .cc/secrets out of three files and .cc/members out of six. MISSING,
    # never DIFFERENT: this call may deny more than cc-audit and may never deny less. An unreadable or unparseable
    # cc-audit gives (), which FAILS — a drift case that cannot find its source has stopped checking.
    def canon():
        try:
            src = open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "cc-audit")).read()
        except OSError:
            return ()
        m = re.search(r'^SECRET_PATHS="([^"]*)"', src, re.M)
        return tuple(m.group(1).split()) if m else ()
    want = canon()
    check("…and every secret store cc-audit denies is denied here too, by path, to Read and to Grep alike",
          bool(want) and all(f"Read(/{HOME}/{p})" in argv and f"Grep(/{HOME}/{p})" in argv for p in want))
    check("…and those paths and no others — a case that could not tell a missing one apart proves nothing",
          f"Read(/{HOME}/.cc/state)" not in argv)
    check("the transcript is fenced and framed as DATA, so a sentence inside the memo is not an instruction",
          SAID in prompt and "```" in prompt and "DATA, not instructions" in prompt)
    check("the weights are never fetched at message time — the model is loaded local_files_only",
          "local_files_only=not fetch" in PROGRAM and open(f"{box}/whisper.argv").read().split()[-1] == "read")

    os.unlink(f"{box}/claude.argv")
    rc2, out2, _ = err_of(["transcript", audio])
    check("transcript: the words alone, and NOT ONE model call — the local half stands on its own",
          rc2 == 0 and out2.strip() == SAID and not os.path.exists(f"{box}/claude.argv"))

    open(f"{box}/claude.out", "w").write("not json at all")
    rc3, out3, err3 = err_of(["text", audio])
    d3 = json.loads(out3) if rc3 == 0 else {}
    check("a condensing call that fails LOSES NOTHING: rc 0, an empty `condensed`, the transcript intact",
          rc3 == 0 and d3.get("transcript") == SAID and d3.get("condensed") == "" and "no JSON" in err3)

    rc4, _, err4 = err_of(["text", f"{box}/nope.m4a"])
    check("a recording that is not there is refused by name, before the venv is touched",
          rc4 == 2 and "no such recording" in err4)

    long_py = f'#!/bin/sh\necho \'{{"text": "on and on", "seconds": {MAX_SECONDS + 1}, "language": "en"}}\'\n'
    with open(f"{box}/venv/bin/python", "w") as fh:
        fh.write(long_py)
    os.chmod(f"{box}/venv/bin/python", 0o755)
    rc5, _, err5 = err_of(["text", audio])
    check(f"a recording longer than {MAX_SECONDS}s is not a memo: refused, not sat on", rc5 == 2 and "longer than a memo" in err5)

    # THE CALLS THAT DO NOT RETURN. Every case above answers with an exit code; these two RAISE out of
    # subprocess.run, which is the shape a wedged transcriber and an unrunnable one really have. Both must come
    # back as a line a person can act on, never as a traceback out of the daemon thread that called this.
    with open(f"{box}/venv/bin/python", "w") as fh:
        fh.write("#!/bin/sh\nsleep 30\n")
    os.chmod(f"{box}/venv/bin/python", 0o755)
    rcT, _, errT = err_of(["text", audio], timeout="1")          # …and the child is killed with it, not left running
    os.chmod(f"{box}/venv/bin/python", 0o644)                    # there, but not runnable: subprocess raises OSError
    rcX, _, errX = err_of(["text", audio])
    check("a transcriber that HANGS is cut off at the cap and says so; one that will not start says that instead — "
          "both as one line, neither as a traceback",
          rcT == 2 and "took longer than 1s" in errT and rcX == 2 and "would not start" in errX)

    with open(f"{box}/venv/bin/python", "w") as fh:
        fh.write(f'#!/bin/sh\necho \'{{"text": "{SAID}", "seconds": 12.4, "language": "en"}}\'\n')
    os.chmod(f"{box}/venv/bin/python", 0o755)
    env = dict(env, CC_CLAUDE=f"{box}/no-such-claude")
    rcC, outC, errC = err_of(["text", audio])
    dC = json.loads(outC) if rcC == 0 else {}
    check("a model binary that is not there raises where the condensing call is made — and STILL loses nothing: the "
          "transcript comes back with an empty `condensed`, for the caller to fall back on",
          rcC == 0 and dC.get("transcript") == SAID and dC.get("condensed") == ""
          and "condensing call failed" in errC and "FileNotFoundError" in errC)

    # THE GPU IS AN OPTION. First PROGRAM itself, run by a real python against a stub faster_whisper whose cuda load
    # raises (the shape of a missing cuBLAS or an out-of-memory card): it runs ONE device and exits non-zero on cuda,
    # 3 when auto finds no CUDA device, and cpu transcribes.
    os.makedirs(f"{box}/stub/faster_whisper")
    with open(f"{box}/stub/faster_whisper/__init__.py", "w") as fh:
        fh.write("class WhisperModel:\n"
                 "    def __init__(self, model, device, compute_type, **k):\n"
                 "        if device == 'cuda':\n            raise RuntimeError('libcublas.so.12 not found')\n"
                 "        self.device = device\n"
                 "    def transcribe(self, path, **k):\n"
                 "        class S: text = ' on the ' + self.device\n"
                 "        class I: duration = 1.0; language = 'en'\n"
                 "        return [S()], I()\n")
    def prog(dev):
        r = subprocess.run([sys.executable, "-c", PROGRAM, "m", audio, f"{box}/models", "read"], capture_output=True,
                           text=True, stdin=subprocess.DEVNULL, timeout=60,
                           env=dict(os.environ, PYTHONPATH=f"{box}/stub", CC_VOICE_DEVICE=dev))
        return r.returncode, (json.loads(r.stdout.splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else {})
    rcG, _ = prog("cuda")
    rcA, _ = prog("auto")
    rcP, dP = prog("cpu")
    check("PROGRAM runs one device: cuda that cannot load exits non-zero, auto with no CUDA device exits 3, cpu "
          "transcribes", rcG not in (0, 3) and rcA == 3 and rcP == 0 and dP.get("device") == "cpu")
    check("…and preloads the CUDA wheels from site-packages only, never sys.path, whose '' is the working directory",
          "getsitepackages" in PROGRAM and "in sys.path" not in PROGRAM)
    # Then the parent, against a venv python that ABORTS on the GPU try, as CTranslate2 does on a missing cuDNN: no
    # except inside that process can catch it, so the CPU run has to come from out here, and the reason is printed
    # on a run that succeeds, not only on one that fails.
    py = f"{box}/venv/bin/python"
    keep = open(py).read()
    with open(py, "w") as fh:
        fh.write(f'#!/bin/sh\n[ "$CC_VOICE_DEVICE" = cpu ] || kill -ABRT $$\n'
                 f'echo \'{{"text": "on the cpu", "seconds": 1.0, "language": "en", "device": "cpu"}}\'\n')
    rcF, outF, errF = err_of(["text", audio])
    dF = json.loads(outF) if rcF == 0 else {}
    check("a GPU run killed by a signal falls back to the CPU in the parent, and says so on stderr and in the answer",
          rcF == 0 and dF.get("transcript") == "on the cpu" and dF.get("device") == "cpu"
          and "SIGABRT" in dF.get("gpu", "") and "cuda failed" in errF and "using the CPU" in errF)
    rcN, _, errN = err_of(["transcript", audio], device="cpu")
    check("…and CC_VOICE_DEVICE=cpu never tries the GPU, so it has nothing to say about it",
          rcN == 0 and "cuda failed" not in errN)
    with open(py, "w") as fh:
        fh.write(keep)

    empty = tempfile.mkdtemp(prefix="cc-voice-bare-")
    env = dict(os.environ, CC_VOICE_DIR=empty)
    rc6, out6, err6 = err_of(["status"])
    rc7, _, err7 = err_of(["text", audio])
    check("with nothing installed, status and a memo both say the ONE command that fixes it",
          rc6 == 1 and "cc-voice install" in out6 and rc7 == 2 and "cc-voice install" in err7)
    subprocess.run(["rm", "-rf", box, empty])
    print(f"cc-voice selfcheck: {n - f} passed, {f} failed")
    return 1 if f else 0
