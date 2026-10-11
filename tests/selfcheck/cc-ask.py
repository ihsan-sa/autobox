# cc-ask's selfcheck: the cases behind `cc-ask selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-ask execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.
# recurring-defect-ok: pause-hold-missing — moved test cases: the board writes and dispatches are fixtures in a temp tree, never a real one

# ── selfcheck ────────────────────────────────────────────────────────────────────────────────────────────────
def selfcheck():
    import tempfile, shutil, io, contextlib
    global HOME, DEV, BIN, LOG, RUNS, CLAUDE, DOCS_ROOT
    fails, n = [], 0

    def check(name, ok):
        nonlocal n
        n += 1
        if not ok:
            fails.append(name); print(f"  FAIL {name}")

    th = tempfile.mkdtemp(prefix="cc-ask-sc-")
    wasH, wasD, wasB, wasL, wasR, wasDocs = HOME, DEV, BIN, LOG, RUNS, DOCS_ROOT
    HOME, DEV, BIN, LOG, RUNS = th, f"{th}/dev", f"{th}/bin", f"{th}/.cc/state/ask/runs.jsonl", f"{th}/.cc/ask"
    os.makedirs(f"{DEV}/myrepo/docs"); os.makedirs(BIN)
    # a stub cc-lib: the packet is whatever it prints, and a red one leaves the packet empty
    with open(f"{BIN}/cc-lib", "w") as f:
        f.write('#!/usr/bin/env bash\n[ -n "${LIB_FAIL:-}" ] && exit 1\necho "cc-lib ask T1 · scope $3 · cap $5"\necho "HITS 1"\necho "  [document] USAGE § cc-green: run the gates"\n')
    os.chmod(f"{BIN}/cc-lib", 0o755)
    env0 = dict(os.environ)
    try:
        ok_json = json.dumps({"result": "*Run `cc-green`.*\n_source: ~/USAGE.md § cc-green_", "is_error": False,
                              "num_turns": 3, "total_cost_usd": 0.041, "usage": {"input_tokens": 10, "output_tokens": 20},
                              "modelUsage": {"claude-sonnet-5": {}}})
        os.environ["CC_ASK_FAKE"] = ok_json
        rc, out, err = answer("myrepo", "how do I run the gates?", "")
        logged = [json.loads(l) for l in open(LOG)] if os.path.exists(LOG) else []
        check("answer: a reply comes back on stdout, exit 0, and the run is one logged line with cost, turns and outcome=answered",
              rc == 0 and out.startswith("*Run `cc-green`.*") and out.endswith("_source: ~/USAGE.md § cc-green_") and err == ""
              and len(logged) == 1 and logged[0]["outcome"] == "answered" and logged[0]["cost"] == 0.041
              and logged[0]["turns"] == 3 and logged[0]["repo"] == "myrepo" and logged[0]["packet"] > 0)
        rc, out, err = answer("myrepo", "what colour is the box?", "")
        os.environ["CC_ASK_FAKE"] = json.dumps({"result": f"{NOT_RECORDED}. It would live in ~/dev/myrepo/docs/hardware.md — ask in #myrepo.",
                                                "is_error": False, "num_turns": 2, "total_cost_usd": 0.01, "usage": {}})
        rc2, out2, _ = answer("myrepo", "what colour is the box?", "")
        logged = [json.loads(l) for l in open(LOG)]
        check("answer: the 'Not in the record' line IS a reply (exit 0, posted as it is) and is logged as not-recorded, "
              "so the lane's misses can be counted against what the docs should hold",
              rc == 0 and rc2 == 0 and out2.startswith(NOT_RECORDED) and logged[-1]["outcome"] == "not-recorded"
              and logged[-2]["outcome"] == "answered")
        # the failure half: an error result, an empty result, no JSON — each is exit 1 with one reason on stderr and nothing on stdout
        os.environ["CC_ASK_FAKE"] = json.dumps({"result": "Budget of $0.25 exceeded", "is_error": True, "subtype": "error_max_budget_usd"})
        rcE, outE, errE = answer("myrepo", "q", "")
        os.environ["CC_ASK_FAKE"] = json.dumps({"result": "", "is_error": False})
        rcM, outM, errM = answer("myrepo", "q", "")
        os.environ["CC_ASK_FAKE"] = "not json"
        rcJ, outJ, errJ = answer("myrepo", "q", "")
        logged = [json.loads(l) for l in open(LOG)]
        check("answer: a model that errored, said nothing or printed no JSON is exit 1, nothing on stdout, one reason on "
              "stderr, and logged as outcome=error — the daemon posts its one line from the reason, never an empty reply",
              (rcE, outE) == (1, "") and "Budget" in errE and (rcM, outM) == (1, "") and "empty result" in errM
              and (rcJ, outJ) == (1, "") and "no JSON" in errJ and [l["outcome"] for l in logged[-3:]] == ["error"] * 3)
        os.environ["CC_ASK_FAKE"] = json.dumps({"result": "*Run `cc-green`.* It runs every gate.", "is_error": False,
                                                "num_turns": 2, "total_cost_usd": 0.01, "usage": {}})
        rcU, outU, errU = answer("myrepo", "how do I run the gates?", "")
        logged = [json.loads(l) for l in open(LOG)]
        check("answer: a reply whose last line is not `_source: ..._` is no reply at all — exit 1, nothing on stdout, "
              "'no source' on stderr, logged as outcome=error, so an uncited answer never reaches the thread looking "
              "authoritative", (rcU, outU) == (1, "") and "no source" in errU and logged[-1]["outcome"] == "error")
        rcR, _, errR = answer("nosuch", "q", "")
        rcS, _, errS = answer("my/repo", "q", "")
        rcQ, _, errQ = answer("myrepo", "   ", "")
        check("answer: a repo that is not under ~/dev, a repo/track, and an empty question are refused before any "
              "call — exit 1, 1, 2 with the reason named", (rcR, rcS, rcQ) == (1, 1, 2)
              and "no project" in errR and "no project" in errS and "empty question" in errQ)
        # the prompt: the frame's rules, the question, the thread context only when there is one, the packet or its absence
        pk = packet("myrepo", "how do I run the gates?", 4096)
        p1 = prompt("myrepo", "how do I run the gates?", "", pk)
        p2 = prompt("myrepo", "and on a worktree?", "- owner: how do I run the gates?\n- box: *Run `cc-green`.*", pk)
        os.environ["LIB_FAIL"] = "1"
        p3 = prompt("myrepo", "q", "", packet("myrepo", "q", 4096))
        del os.environ["LIB_FAIL"]
        check("prompt: the frame names the order of sources with the real paths, the cite rule, the not-recorded shape "
              "for THIS repo and the no-secrets rule; the cc-lib packet is fetched here (cap passed through) and put "
              "in; thread context appears only for a follow-up; a red cc-lib leaves an explicit empty packet",
              f"{th}/USAGE.md" in p1 and f"{th}/dev/myrepo/core/bin/<tool>" in p1 and "_source: <path>_" in p1
              and f"{NOT_RECORDED}. It would live in <path or place> — ask in #myrepo." in p1
              and "Secrets never leave the record" in p1 and "USAGE § cc-green" in p1 and "cap 4096" in p1
              and "THE QUESTION:\nhow do I run the gates?" in p1 and "EARLIER IN THIS THREAD" not in p1
              and "EARLIER IN THIS THREAD" in p2 and "- box: *Run `cc-green`.*" in p2
              and "nothing recorded for these words" in p3)
        # the call itself, through a stub claude: read-only tools, the deny list with the secret stores, the caps, the role
        del os.environ["CC_ASK_FAKE"]
        calls = f"{th}/calls"
        with open(f"{BIN}/claude", "w") as f:
            f.write('#!/usr/bin/env bash\n{ printf "claude"; printf " %s" "$@"; printf " role=%s cwd=%s\\n" "${CC_ROLE:-}" "$PWD"; cat; } > "$CALLS"\n'
                    'echo \'{"result":"ok\\n_source: x_","is_error":false,"num_turns":1,"total_cost_usd":0.01,"usage":{}}\'\n')
        os.chmod(f"{BIN}/claude", 0o755)
        wasC, CLAUDE = CLAUDE, f"{BIN}/claude"
        os.environ["CALLS"] = calls; os.environ["CC_ASK_MODEL"] = "haiku"; os.environ["CC_ASK_BUDGET"] = "0.05"
        rcC, outC, _ = answer("myrepo", "what is cc-green?", "")
        c = open(calls).read() if os.path.exists(calls) else ""
        check("the call: `claude -p` on CC_ASK_MODEL with Read/Grep/Glob only, cc-steward's deny list (Bash, Monitor, "
              "the schedulers, the notifiers) and the secret stores denied by name, no settings source, no MCP, "
              "a turn cap and CC_ASK_BUDGET, no transcript, at CC_ROLE=steward in ~/.cc/ask/<repo>; the prompt is stdin",
              rcC == 0 and outC == "ok\n_source: x_" and "--model haiku" in c and "--allowedTools Read,Grep,Glob" in c
              and "Bash,BashOutput" in c and "Monitor" in c and "CronCreate" in c and "PushNotification" in c
              and f"Read(/{th}/.cc/config)" in c and f"Grep(/{th}/.cc/secrets/**)" in c
              and "--setting-sources  --disable" in c and "--strict-mcp-config" in c and "--disable-slash-commands" in c
              and "--max-turns 12" in c and "--max-budget-usd 0.05" in c and "--no-session-persistence" in c
              and f"role=steward cwd={th}/.cc/ask/myrepo" in c and "THE QUESTION:\nwhat is cc-green?" in c)
        CLAUDE = wasC
        # ── a document by number, title or topic, from the register (a stub cc-docs with find's contract: the path on
        # stdout, exit 0; `<number>\t<title>` lines on stderr, exit 3; nothing, exit 1), and the visibility rule
        owner, view = f"{th}/documents", f"{th}/documents/ws/0123456789abcdef"
        def reg(root, docs):
            os.makedirs(f"{root}/files", exist_ok=True)
            out = {"version": 1, "projects": {}, "documents": {}}
            for num, title in docs:
                rel = f"files/{num[:3]}/{num}-A_{title.lower().replace(' ', '-')}.pdf"
                os.makedirs(os.path.dirname(f"{root}/{rel}"), exist_ok=True)
                open(f"{root}/{rel}", "w").write("%PDF-1.4\n")
                out["documents"][num] = {"title": title, "revisions": [{"rev": "A", "file": rel, "date": "2026-09-23"}]}
            json.dump(out, open(f"{root}/register.json", "w"))
        reg(owner, [("001-0003", "Autobox pitch"), ("001-0004", "Autobox deeper look")])
        reg(view, [("901-0001", "Member study plan")])
        with open(f"{BIN}/cc-docs", "w") as f:
            f.write("#!/usr/bin/env python3\nimport json, os, sys\nroot = os.environ['CC_DOCS_ROOT']\n"
                    "if os.environ.get('STUB_OUT'): print(os.environ['STUB_OUT']); sys.exit(0)\n"
                    "docs = json.load(open(root + '/register.json'))['documents']\nq = sys.argv[2:]\n"
                    "stop = {'the', 'a', 'pdf', 'doc', 'document'}\n"
                    "hits = [n for n, d in docs.items() if q[0][:8] == n] or [n for n, d in docs.items() "
                    "if all(w.lower() in d['title'].lower() for w in q if w.lower() not in stop)]\n"
                    "if len(hits) == 1: print(root + '/' + docs[hits[0]]['revisions'][-1]['file']); sys.exit(0)\n"
                    "[print(n + '-A\\t' + docs[n]['title'], file=sys.stderr) for n in hits]\nsys.exit(3 if hits else 1)\n")
        os.chmod(f"{BIN}/cc-docs", 0o755)
        os.environ["CC_ASK_FAKE"] = "not json"          # a model call in these cases would be exit 1: none is made
        DOCS_ROOT = owner
        rcN, outN, _ = answer("myrepo", "001-0003", "", documents=True)
        rcT, outT, _ = answer("myrepo", "the autobox deeper look", "", documents=True)
        logged = [json.loads(l) for l in open(LOG)]
        check("document: a number, or a title that is no question, is answered from the register with no model call — "
              "the number, revision, title and date, the source, and a last `_file:` line naming the filed PDF; the "
              "run is logged as outcome=document at no cost",
              rcN == 0 and outN.splitlines() == ["*001-0003-A* Autobox pitch, filed 23 Sep 2026",
                                                 "_source: the document register_",
                                                 f"_file: {os.path.realpath(owner)}/files/001/001-0003-A_autobox-pitch.pdf_"]
              and rcT == 0 and outT.startswith("*001-0004-A* Autobox deeper look") and outT.endswith("deeper-look.pdf_")
              and [l["outcome"] for l in logged[-2:]] == ["document"] * 2 and logged[-1]["cost"] == 0)
        rcL, outL, _ = answer("myrepo", "send me the autobox pdf", "", documents=True)
        rcZ, outZ, _ = answer("myrepo", "send me the moon plan", "", documents=True)
        os.environ["CC_ASK_FAKE"] = ok_json
        rcQ1, outQ1, _ = answer("myrepo", "is the autobox pitch ready?", "", documents=True)
        rcQ2, outQ2, _ = answer("myrepo", "the moon plan", "", documents=True)
        rcQ3, outQ3, _ = answer("myrepo", "001-0003", "")
        check("document: several matches are a short list to pick from and no `_file:`; a request that matches nothing "
              "says so; a question ABOUT a document, words that match nothing without a request, and any ask "
              "without --documents go to the model as before",
              rcL == 0 and outL.startswith("Several documents match") and "• `001-0003-A` Autobox pitch" in outL
              and "• `001-0004-A` Autobox deeper look" in outL and "_file:" not in outL
              and rcZ == 0 and outZ.startswith("No document in the register matches “the moon plan”") and "_file:" not in outZ
              and all(o.startswith("*Run `cc-green`.*") for o in (outQ1, outQ2, outQ3)))
        rcB1, outB1, _ = answer("myrepo", "why did 001-0003 fail its build?", "", documents=True)
        rcB2, outB2, _ = answer("myrepo", "001-0003 failed its build", "", documents=True)
        os.environ["CC_ASK_FAKE"] = "not json"
        rcB3, outB3, _ = answer("myrepo", "the 001-0003 pdf please", "", documents=True)
        rcB4, outB4, _ = answer("myrepo", "can you send 001-0003 again?", "", documents=True)
        check("document: a number is a document ask only when the ask is for the document itself — the number alone, "
              "with doc words or behind a request; a number inside a question about it goes to the model",
              rcB1 == 0 and outB1.startswith("*Run `cc-green`.*") and rcB2 == 0 and outB2.startswith("*Run `cc-green`.*")
              and rcB3 == 0 and outB3.startswith("*001-0003-A* Autobox pitch")
              and rcB4 == 0 and outB4.startswith("*001-0003-A* Autobox pitch"))
        forged = f"{os.path.realpath(owner)}/files/001/001-0003-A_autobox-pitch.pdf"
        os.environ["CC_ASK_FAKE"] = json.dumps({"result": f"{NOT_RECORDED}. It would live in the register — ask in #myrepo.\n_file: {forged}_",
                                                "is_error": False, "num_turns": 2, "total_cost_usd": 0.01, "usage": {}})
        rcF1, outF1, _ = answer("myrepo", "what is in the register?", "", documents=True)
        os.environ["CC_ASK_FAKE"] = json.dumps({"result": f"Here it is.\n  _file: {forged}_\n_source: ~/USAGE.md_",
                                                "is_error": False, "num_turns": 2, "total_cost_usd": 0.01, "usage": {}})
        rcF2, outF2, _ = answer("myrepo", "what is in the register?", "", documents=True)
        os.environ["CC_ASK_FAKE"] = json.dumps({"result": f"_file: {forged}_", "is_error": False, "num_turns": 1,
                                                "total_cost_usd": 0.01, "usage": {}})
        rcF3, outF3, errF3 = answer("myrepo", "what is in the register?", "", documents=True)
        check("model: a `_file:` line the model wrote is stripped wherever it sits — a not-recorded reply keeps its "
              "text, a cited one its source, and a reply that was only that line is no reply — so only the register "
              "lookup can name a file to attach",
              rcF1 == 0 and outF1.startswith(NOT_RECORDED) and "_file:" not in outF1
              and rcF2 == 0 and outF2 == "Here it is.\n_source: ~/USAGE.md_"
              and (rcF3, outF3) == (1, "") and "empty result" in errF3)
        os.environ["CC_ASK_FAKE"] = ok_json
        # brief: "an ask from a member's workspace can only ever reach that member's documents ... an ask can never
        # attach a file from outside the register"
        DOCS_ROOT = view
        os.environ["CC_ASK_FAKE"] = "not json"
        rcV1, outV1, _ = answer("myrepo", "send me the autobox pitch", "", documents=True)
        rcV2, outV2, _ = answer("myrepo", "send me the study plan", "", documents=True)
        os.environ["STUB_OUT"] = f"{owner}/files/001/001-0003-A_autobox-pitch.pdf"
        rcV3, outV3, _ = answer("myrepo", "send me the study plan", "", documents=True)
        os.environ["STUB_OUT"] = f"{view}/../../register.json"
        rcV4, outV4, _ = answer("myrepo", "send me the study plan", "", documents=True)
        del os.environ["STUB_OUT"]
        check("visibility: at a member's view the owner's document is not found and the member's own is; a path "
              "cc-docs names outside the view (the owner's filed PDF, the register itself) is refused with no "
              "`_file:` line, so nothing outside the register at this root can be attached",
              outV1.startswith("No document in the register matches") and "_file:" not in outV1
              and outV2.startswith("*901-0001-A* Member study plan") and outV2.endswith("member-study-plan.pdf_")
              and f"{os.path.realpath(view)}/files/" in outV2
              and all(o.startswith("The register pointed at a file it does not list") and "_file:" not in o
                      for o in (outV3, outV4)))
        os.remove(f"{BIN}/cc-docs")
        os.environ["CC_ASK_FAKE"] = ok_json
        rcX, outX, _ = answer("myrepo", "send me the study plan", "", documents=True)
        check("document: with no cc-docs there is no lookup and the lane answers as it did before",
              rcX == 0 and outX.startswith("*Run `cc-green`.*"))
        # THE TOOL ROUTE, on its own stubs: the owner's 2026-09-18 question drew "Not in the record" while cc-spend had
        # the figure. Each stub logs its argv to $TOOLS_CALLED, so a question that picks no route is seen to run none.
        called = f"{th}/tools-called"
        os.environ["TOOLS_CALLED"] = called
        for name, body in (("cc-spend", 'echo "cc-spend 2026-09-12..2026-09-18 — by track"\necho "  track  est \\$"\n'
                                        'echo "  home/session  900.1"\necho "  chip101/counter  28.0432"\n'),
                           ("cc", 'printf "\\033[1mboard\\033[0m %s\\n--\\n  fix-x  queued\\n" "$3"\n'),
                           ("cc-failures", 'exit 1\n')):
            with open(f"{BIN}/{name}", "w") as f:
                f.write(f'#!/usr/bin/env bash\necho "{name} $*" >> "$TOOLS_CALLED"\n{body}')
            os.chmod(f"{BIN}/{name}", 0o755)
        q = "how much did the chip101 counter project cost start to finish?"
        got = tools("myrepo", q, 4096)
        spent = open(called).read().splitlines()
        check("tool route: a cost question runs `cc-spend --by track --week` and nothing else, and its output is cut "
              "to the header and the row naming the project (the other track's row is dropped)",
              spent == ["cc-spend --by track --week"] and len(got) == 1 and got[0][0] == "cc-spend --by track --week"
              and "chip101/counter  28.0432" in got[0][1] and "home/session" not in got[0][1]
              and got[0][1].startswith("cc-spend 2026-09-12"))
        text = prompt("myrepo", q, "", "", got)
        check("tool route: the prompt carries the tool output under its command, and the frame says to cite it",
              "THE TOOL OUTPUT (`cc-spend --by track --week`" in text and "28.0432" in text
              and "_source: cc-spend --by track --week_" in text)
        os.remove(called)
        check("tool route: a question with no cost, board or ledger word runs no tool at all",
              tools("myrepo", "how do I run the gates?", 4096) == [] and not os.path.exists(called))
        board = tools("myrepo", "what is queued on the board?", 4096)
        check("tool route: a board question runs `cc board show <repo>` with ANSI stripped",
              [c for c, _ in board] == ["cc board show myrepo"] and board[0][1].startswith("board myrepo")
              and "\x1b" not in board[0][1] and "fix-x  queued" in board[0][1])
        check("tool route: a red tool (cc-failures exiting 1) is left out, not handed to the model",
              tools("myrepo", "any recurring failures?", 4096) == [])
        os.environ["CC_ASK_FAKE"] = ok_json
        answer("myrepo", q, "")
        check("tool route: the run's log line names the tools it ran",
              json.loads(open(LOG).read().splitlines()[-1]).get("tools") == ["cc-spend"])
        for name in ("cc-spend", "cc", "cc-failures"):
            os.remove(f"{BIN}/{name}")
        del os.environ["TOOLS_CALLED"]
        del os.environ["CC_ASK_FAKE"]
        # the docstring says what the code does: the knobs and the log path it names exist here
        src = open(os.path.realpath(__file__)).read()
        doc = src.split('"""')[1]
        check("contract: every knob the docstring names is one the code reads, and the log it names is LOG",
              all(k in src.split('"""', 2)[2] for k in ("CC_ASK_MODEL", "CC_ASK_BUDGET", "CC_ASK_TURNS", "CC_ASK_TIMEOUT", "CC_ASK_PACKET"))
              and all(k in doc for k in ("CC_ASK_MODEL", "CC_ASK_BUDGET", "CC_ASK_TURNS", "CC_ASK_TIMEOUT", "CC_ASK_PACKET"))
              and "~/.cc/state/ask/runs.jsonl" in doc and LOG.endswith("/.cc/state/ask/runs.jsonl"))
        # This file runs unattended on anyone's message in #<repo>-ask and pays for a model call, so it is on the
        # control layer (core/tests/control-layer, read by cc-land's gate_tier from the BASE side): a later change
        # that widened TOOLS or dropped a name from deny() buys a paid review, not the gates alone.
        ctl = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "tests", "control-layer")
        check("this file is named in the control layer, so every future change to it buys a paid review at the landing",
              "bin/cc-ask" in [ln.strip() for ln in open(ctl).read().splitlines()])
    finally:
        os.environ.clear(); os.environ.update(env0)
        HOME, DEV, BIN, LOG, RUNS, DOCS_ROOT = wasH, wasD, wasB, wasL, wasR, wasDocs
        shutil.rmtree(th, ignore_errors=True)
    print(f"cc-ask selfcheck: {n - len(fails)} passed, {len(fails)} failed")
    return 1 if fails else 0
