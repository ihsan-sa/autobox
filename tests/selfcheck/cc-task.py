# cc-task's selfcheck: the cases behind `cc-task selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-task execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.
# recurring-defect-ok: pause-hold-missing — moved test cases: the board writes and dispatches are fixtures in a temp tree, never a real one

def selfcheck():
    """Every fixture owns its HOME, its state, its board and its git remote. No service and no runtime is called."""
    n = 0
    def ok(what, cond):
        nonlocal n
        print(("  ok   " if cond else "  FAIL ") + what)
        if not cond: n += 1
    print("cc-task selfcheck")
    with tempfile.TemporaryDirectory(prefix="cctask-proc-") as proc:   # a /proc of its own: no live pid is read
        def fake(pid, ppid, comm, argv, ticks=100):
            d = Path(proc, str(pid)); d.mkdir()
            (d / "stat").write_text(f"{pid} ({comm}) S {ppid} " + " ".join(["0"] * 17) + f" {ticks}\n")
            (d / "comm").write_text(comm + "\n"); (d / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
        fake(10, 1, "systemd", ["/usr/lib/systemd/systemd", "--user"], 3100272)
        fake(20, 10, "bash", ["bash", str(BIN / "cc")])           # `cc --go` run by a shell the manager adopted  # recurring-defect-ok: pause-hold-missing — a fake /proc argv in the selfcheck; nothing is launched
        fake(30, 20, "bash", ["bash", "-c", "cc-task claim"])
        fake(40, 10, "claude", ["claude"]); fake(50, 40, "bash", ["bash", str(BIN / "cc")])
        chain = ancestry(30, proc); who = pick(chain, None)
        ok("a cc whose only ancestor is the user manager never records the manager as the owner (2026-10-03)",
           who["pid"] != 10 and who["pid"] == 30 and [p["pid"] for p in chain] == [30, 20, 10])
        ok("…the walk stops at the manager and records nothing above it",
           chain[-1].get("systemd") is True and all(not p.get("systemd") for p in chain[:-1]))
        ok("…and with `cc` itself the only process under it, the owner is that `cc`, not the manager",
           pick(ancestry(20, proc), None)["pid"] == 20)
        ok("a claude under the manager is still the owner its runtime names",
           pick(ancestry(50, proc), "1")["pid"] == 40)
        fake(90, 1, "bash", ["bash", str(BIN / "cc")]); fake(91, 90, "bash", ["bash", str(BIN / "cc")])
        ok("a detached `cc --go` whose shell exited, adopted by pid 1 with only `cc` above cc-task, is still a "
           "caller: the nearest `cc` owns it, not 'cannot identify the calling process' (2026-10-12)",
           pick(ancestry(91, proc), "1")["pid"] == 91)
        sub_held = {"owner": owner(ancestry(91, proc)), "ended_at": None}
        Path(proc, "91").rename(Path(proc, "gone91")); outer = ancestry(90, proc)
        ok("…and once that `$(…)` copy (91) exits, the outer `cc` (90) is still the launch that owns its claim",
           launch_owner(sub_held, outer, owner(outer)) == sub_held["owner"] != owner(outer))

        # L1: THE LAUNCH OWNS ITS OWN CLAIM WHEN ITS PARENTS GO (2026-10-15). A seat's Bash runs `cc` (61) whose
        # reservation walks up to the seat's claude (41); the shell (60) is gone by the claim, `cc` is re-parented
        # to the manager and walks to itself. Its own claim must still be its own.
        fake(12, 1, "systemd", ["/usr/lib/systemd/systemd", "--user"], 3100272)   # this case's own manager
        fake(41, 12, "claude", ["claude"]); fake(60, 41, "bash", ["bash", "-c", "setsid nohup cc"])
        fake(61, 60, "bash", ["bash", str(BIN / "cc")])
        reserving = ancestry(61, proc); seat = owner(reserving)
        Path(proc, "60").rename(Path(proc, "gone60"))
        (Path(proc, "61") / "stat").write_text("61 (bash) S 12 " + " ".join(["0"] * 17) + " 100\n")
        orphan = ancestry(61, proc); bare = owner(orphan)
        held = {"owner": seat, "ended_at": None}
        ok("L1: a launch re-parented between its reservation and its claim is still that claim's owner, though "
           "the walk alone now names a different process",
           not same_owner(seat, bare) and same_owner(launch_owner(held, orphan, bare), seat))
        fake(70, 12, "bash", ["bash", str(BIN / "cc")]); other = ancestry(70, proc)
        fake(80, 41, "bash", ["bash", "-c", "cc done"]); fake(81, 80, "bash", ["bash", str(BIN / "cc")]); later = ancestry(81, proc)
        ok("L1 controls: another `cc` is not that launch, nor is a later `cc` from the same seat whose chain shares "
           "only the seat, nor the same launch once its claim has ended or on another boot",
           launch_owner(held, other, owner(other)) == owner(other)
           and launch_owner(held, later, owner(later)) == owner(later)
           and launch_owner(dict(held, ended_at=stamp()), orphan, bare) == bare
           and launch_owner({"owner": dict(seat, boot_id="previous-boot"), "ended_at": None}, orphan, bare) == bare)
        # A seat's window runs under `cc __run` (100), which is in the ancestry of every claim the seat takes. A
        # cc-task call that wrapper makes itself, with no shell between, is not the launch that took the claim.
        # recurring-defect-ok: pause-hold-missing — fake process argv in a fixture; nothing launches or writes a board
        fake(100, 12, "bash", ["bash", str(BIN / "cc"), "__run"]); fake(101, 100, "claude", ["claude"])
        fake(102, 101, "bash", ["bash", "-c", "cc r/t --go"]); fake(103, 102, "bash", ["bash", str(BIN / "cc")])
        took = ancestry(103, proc); window_held = {"owner": owner(took), "ended_at": None}; wrapper = ancestry(100, proc)
        ok("L1 control: the seat's `cc __run` wrapper calling cc-task directly is not the launch that took a claim "
           "under it, though the claim's recorded ancestry holds it; the launch itself still is",
           100 in [p["pid"] for p in took] and launch_run(wrapper) == [(100, 100)]
           and launch_owner(window_held, wrapper, owner(wrapper)) == owner(wrapper)
           and launch_owner(window_held, took, owner(wrapper)) == window_held["owner"])
    with tempfile.TemporaryDirectory(prefix="cctask-sc-") as th:
        env = {"HOME": th, "PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1"}
        def run(*args):
            return subprocess.run([sys.executable, __file__, *args], env=env, capture_output=True,
                                  text=True, timeout=60)
        def git(*args): subprocess.run(["git", *args], env=env, check=True, capture_output=True)
        root = Path(th); dev = root / "dev/r"; dev.mkdir(parents=True)
        git("init", "-q", "-b", "main", str(dev))
        git("-C", str(dev), "-c", "user.name=T", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "base")
        wt = root / ".cc/worktrees/r/t"; wt.parent.mkdir(parents=True)
        git("-C", str(dev), "worktree", "add", "-q", "-b", "track/t", str(wt))
        record = root / ".cc/state/r/t/delivery.json"
        args = ("claim", "r", "t", "--executor", "subagent")

        first = run(*args); d = json.loads(first.stdout or "{}"); before = record.read_bytes()
        ok("claim writes the record and one reservation; the same owner claiming again changes not one byte",
           first.returncode == 0 and run(*args).returncode == 0 and record.read_bytes() == before
           and d["schema"] == SCHEMA and d["claim"]["generation"] == 1 and d["claim"]["phase"] == "starting"
           and len(d["executions"]) == 1 and d["closed"] is None and d["artifact"]["errors"] == [])
        marker = wt / ".cc/track"; decoy = root / "decoy"; decoy.write_text("do not touch\n")
        ok("claiming writes the marker: the repo, the row and the task id, as a plain file",
           marker.read_text() == f"r\nt\n{d['task_id']}\n" and not marker.is_symlink())
        marker.unlink(); marker.symlink_to(decoy)
        planted = run(*args)
        ok("a link planted at .cc/track is refused, the file it named is untouched, and nothing is claimed",
           planted.returncode != 0 and decoy.read_text() == "do not touch\n" and marker.is_symlink()
           and record.read_bytes() == before)
        marker.unlink()
        os.rename(wt / ".cc", wt / ".cc-real"); os.symlink(str(root), str(wt / ".cc"))
        planted_dir = run(*args)
        ok("…and so is a link planted at .cc itself — the marker is never written through somebody else's name",
           planted_dir.returncode != 0 and record.read_bytes() == before
           and not (root / "track").exists())
        os.remove(wt / ".cc"); os.rename(wt / ".cc-real", wt / ".cc")
        ok("…while the claim that follows writes the marker again, in its own directory",
           run(*args).returncode == 0 and marker.read_text() == f"r\nt\n{d['task_id']}\n"
           and not marker.is_symlink() and record.read_bytes() == before)

        ok("no identity can be typed in, and asking `check` writes nothing — not even a state dir for a fresh row",
           run(*args, "--session-id", "typed").returncode != 0 and run("check", "r", "t").returncode == 0
           and run("check", "r", "t").stdout == "" and record.read_bytes() == before
           and run("check", "r", "fresh").returncode == 0 and not (record.parent.parent / "fresh").exists())

        c = d["claim"]; token = ("r", "t", c["claim_id"], str(c["generation"]))
        ok("renew stamps activity for the owner's own token; a wrong generation is refused",
           run("renew", *token).returncode == 0 and run("renew", *token[:-1], "2").returncode != 0
           and json.loads(record.read_text())["claim"]["activity_at"] >= c["activity_at"])
        ok("release ends the claim explicitly, and an ended claim can neither renew nor release again",
           run("release", *token, "--reason", "stopped").returncode == 0
           and json.loads(record.read_text())["claim"]["ended_at"]
           and run("renew", *token).returncode != 0
           and run("release", *token, "--reason", "late").returncode != 0)

        after = json.loads(record.read_text()); before = record.read_bytes()
        second = json.loads(run(*args).stdout)
        ok("a claim after a release keeps the task and advances the generation; the released token stays dead",
           second["task_id"] == d["task_id"] and second["claim"]["generation"] == 2
           and second["executions"][0]["execution_id"] == d["executions"][0]["execution_id"]
           and len(second["executions"]) == 2 and after["claim"]["claim_id"] != second["claim"]["claim_id"]
           and run("renew", *token).returncode != 0)

        before = record.read_bytes()
        third = json.loads(run("claim", "r", "t", "--executor", "worker").stdout)
        ok("the same owner may change executor — one task, next generation, and the old execution says so",
           third["task_id"] == d["task_id"] and third["claim"]["generation"] == 3
           and third["claim"]["executor"] == "worker" and len(third["executions"]) == 3
           and "superseded" in third["executions"][1]["outcome"]
           and record.read_bytes() != before)

        ok("show prints the record; a row without one, and an unusable name, create nothing",
           json.loads(run("show", "r", "t").stdout) == third and run("show", "r", "missing").returncode != 0
           and run("claim", "r", "../escape", "--executor", "worker").returncode != 0
           and not (record.parent.parent / "missing").exists())

        before = record.read_bytes()
        git("-C", str(wt), "checkout", "-q", "--detach")
        ok("a worktree on the wrong HEAD, and a row with no worktree at all, claim nothing and stamp nothing",
           run(*args).returncode != 0 and record.read_bytes() == before
           and run("claim", "r", "missing", "--executor", "worker").returncode != 0
           and not (record.parent.parent / "missing/delivery.json").exists())
        git("-C", str(wt), "checkout", "-q", "track/t")

        board = subprocess.run([str(BIN / "cc-board"), "init", "r", str(dev), "main"], env=env,
                               capture_output=True, text=True, timeout=30)
        for cmd in (("add", "r", "s1", "a session", ""), ("set", "r", "s1", "kind", "session")):
            subprocess.run([str(BIN / "cc-board"), *cmd], env=env, capture_output=True, timeout=30)
        ok("a session row has no task to claim, while an ordinary row on the same board still does",
           board.returncode == 0 and run("claim", "r", "s1", "--executor", "subagent").returncode != 0
           and not (record.parent.parent / "s1/delivery.json").exists()
           and run("claim", "r", "t", "--executor", "worker").returncode == 0)

        # TWO LONG-LIVED OWNERS AT ONE BARRIER. Each waits for the gate, claims, records its status and then stays
        # alive until the gate is removed — so the winner's claim can be tested while its owner is still running,
        # which is the whole of the rule. Sharing this process as a parent does not make them one owner.
        record.unlink()
        # A separate owner: it waits for the gate, claims — or, in `repair` mode, reserves a repair and then takes
        # the dispatcher's own claim on it — optionally hands the claim straight back, writes its status and then
        # stays alive until the gate is removed. Being started by this process does not make it this process.
        helper = root / "owner.py"
        helper.write_text(
            "import json,pathlib,subprocess,sys,time\n"
            "gate,out,mode,ex,py,tool,repo,row = sys.argv[1:9]\n"
            "extra = sys.argv[9:]\n"
            "g=pathlib.Path(gate)\n"
            "while not g.exists(): time.sleep(.01)\n"
            "if mode=='repair':\n"
            "    v=subprocess.run([py,tool]+extra,capture_output=True,text=True)\n"
            "    w=subprocess.run([py,tool,'claim',repo,row,'--executor','worker'],capture_output=True,text=True)\n"
            "    pathlib.Path(out).write_text('%d%d' % (v.returncode,w.returncode))\n"
            "    while g.exists(): time.sleep(.01)\n"
            "    raise SystemExit(0)\n"
            "r=subprocess.run([py,tool,'claim',repo,row,'--executor',ex],capture_output=True,text=True)\n"
            "if mode=='release' and r.returncode==0:\n"
            "    c=json.loads(r.stdout)['claim']\n"
            "    subprocess.run([py,tool,'release',repo,row,c['claim_id'],str(c['generation']),\n"
            "                    '--reason','handed back'],capture_output=True)\n"
            "pathlib.Path(out).write_text(str(r.returncode))\n"
            "while g.exists(): time.sleep(.01)\n")
        def owners(mode, n, gate, ex="subagent", row="t", extra=()):
            for stale in root.glob("rc*"): stale.unlink()
            ps = [subprocess.Popen([sys.executable, str(helper), str(gate), f"{root}/rc{i}", mode, ex,
                                    sys.executable, __file__, "r", row, *extra], env=env) for i in range(n)]
            gate.touch()
            for _ in range(6000):
                if all((root / f"rc{i}").exists() for i in range(n)): break
                time.sleep(0.01)
            return ps, sorted((root / f"rc{i}").read_text() for i in range(n))
        gate = root / "gate"
        ps, rcs = owners("hold", 2, gate)
        raced = json.loads(record.read_text()); held = record.read_bytes()
        ok("two owners claiming at once leave one winner, and a third owner is refused while it is alive",
           rcs == ["0", "1"] and len(raced["executions"]) == 1 and raced["claim"]["generation"] == 1
           and run(*args).returncode != 0 and run("check", "r", "t").returncode != 0
           and record.read_bytes() == held)
        gate.unlink()
        for p in ps: p.wait(timeout=60)
        old = raced["claim"]
        taken = run(*args)
        ok("once that owner's process is gone the row is claimable again — same task, next generation, old token dead",
           taken.returncode == 0 and json.loads(taken.stdout)["task_id"] == raced["task_id"]
           and json.loads(taken.stdout)["claim"]["generation"] == 2
           and "superseded (owner gone)" == json.loads(taken.stdout)["executions"][0]["outcome"]
           and run("renew", "r", "t", old["claim_id"], str(old["generation"])).returncode != 0)

        # A CLAIM ITS OWNER HANDED BACK DOES NOT HOLD THE ROW, however alive that owner still is. `cc … --go`
        # releases at launch — the dispatcher is not the worker — so cc-land's repair round and a re-dispatch
        # from another window have to get through (review of #279).
        record.unlink()
        gate2 = root / "gate2"; held_ps, rcs2 = owners("release", 1, gate2)
        released = json.loads(record.read_text())
        after = run("claim", "r", "t", "--executor", "worker")
        ok("a claim handed back does not hold the row, even while the owner that took it is still running",
           rcs2 == ["0"] and released["claim"]["ended_at"] and after.returncode == 0
           and json.loads(after.stdout)["task_id"] == released["task_id"]
           and json.loads(after.stdout)["claim"]["generation"] == 2
           and json.loads(after.stdout)["executions"][0]["outcome"] == "released: handed back"
           and run("check", "r", "t").returncode == 0)
        gate2.unlink()
        for p in held_ps: p.wait(timeout=60)

        # A WORKER DISPATCH TAKES OVER FROM A SUBAGENT, and only from a subagent. A subagent that never reached
        # `cc done` would otherwise hold the row for the life of its session, and the one automatic repair the
        # design gives cc-land is exactly a worker onto the row a subagent built (review of #279).
        record.unlink()
        gate3 = root / "gate3"; sub_ps, _ = owners("hold", 1, gate3)
        held = json.loads(record.read_text()); bytes3 = record.read_bytes()
        second = run("claim", "r", "t", "--executor", "subagent")
        over = run("claim", "r", "t", "--executor", "worker")
        got = json.loads(over.stdout or "{}")
        ok("a worker dispatch takes over a live subagent claim; a second subagent, on the same live claim, waits",
           second.returncode != 0 and over.returncode == 0 and got["task_id"] == held["task_id"]
           and got["claim"]["generation"] == 2 and got["claim"]["executor"] == "worker"
           and got["executions"][0]["outcome"] == "superseded (a worker took over from a subagent)"
           and run("renew", "r", "t", held["claim"]["claim_id"], "1").returncode != 0
           and bytes3 != record.read_bytes())
        gate3.unlink()
        for p in sub_ps: p.wait(timeout=60)

        record.unlink()
        gate4 = root / "gate4"; wrk_ps, _ = owners("hold", 1, gate4, ex="worker")
        bytes4 = record.read_bytes()
        ok("nothing takes a live WORKER's claim — not another worker, not a subagent, and check says so too",
           run("claim", "r", "t", "--executor", "worker").returncode != 0
           and run("claim", "r", "t", "--executor", "subagent").returncode != 0
           and run("check", "r", "t", "--executor", "worker").returncode != 0
           and record.read_bytes() == bytes4)
        gate4.unlink()
        for p in wrk_ps: p.wait(timeout=60)

        # THE PATH IS THE KEY. `cc rename` moves the whole state dir, so a record arrives under a row whose name
        # it has never heard of; refusing it killed every claim on a renamed project. The task is what carries.
        moved = json.loads(record.read_text())
        git("-C", str(dev), "worktree", "add", "-q", "-b", "track/t2", str(root / ".cc/worktrees/r/t2"))
        os.makedirs(root / ".cc/state/r/t2", exist_ok=True)
        os.replace(record, root / ".cc/state/r/t2/delivery.json")
        rekeyed = run("claim", "r", "t2", "--executor", "worker")
        got = json.loads(rekeyed.stdout or "{}")
        ok("a record that moved with its state dir answers to the row it is found under, task and history intact",
           rekeyed.returncode == 0 and got["task_id"] == moved["task_id"] and got["row"] == "t2"
           and got["branch"] == "track/t2" and got["worktree"].endswith("/.cc/worktrees/r/t2")
           and got["rekeyed"] and got["created"] == moved["created"]
           and [e["execution_id"] for e in got["executions"][:len(moved["executions"])]]
               == [e["execution_id"] for e in moved["executions"]])
        # Completion uses the same row lock and keeps the claim and execution identities intact.
        record2 = root / ".cc/state/r/t2/delivery.json"; generation = str(got["claim"]["generation"])
        def finish(cmd, *args, gen=generation): return run(cmd, "r", "t2", "--generation", gen, *args)
        sha, other = "a" * 40, "b" * 40
        written = finish("artifact", "--committed-sha", sha)
        before = record2.read_bytes()
        ok("C1: committed evidence is durable; malformed and uncommitted pushed SHAs leave it untouched",
           written.returncode == 0 and json.loads(written.stdout)["committed_sha"] == sha
           and finish("artifact", "--pushed-sha", other).returncode != 0
           and finish("artifact", "--committed-sha", "short").returncode != 0 and record2.read_bytes() == before
           and finish("pr", "https://example.test/o/r/pull/1").returncode != 0
           and finish("close", "merged").returncode != 0)
        ok("C2: only the current generation can complete; completion never creates a legacy row's record",
           finish("artifact", "--pushed-sha", sha).returncode == 0
           and finish("error", "pr", "stale", gen=str(int(generation) - 1)).returncode != 0
           and run("artifact", "r", "absent", "--generation", "1", "--committed-sha", sha).returncode != 0
           and not (root / ".cc/state/r/absent").exists())
        before = record2.read_bytes()
        with Lock(record2.parent):
            p1 = subprocess.Popen([sys.executable, __file__, "error", "r", "t2", "--generation", generation,
                                   "board", "offline"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(.15)
            held = p1.poll() is None and record2.read_bytes() == before
        p1.communicate(timeout=60)
        finish("error", "card", "offline"); finish("error", "board")
        ok("C3: completion waits on the existing lock; clearing board's error preserves card's error",
           held and p1.returncode == 0
           and [e["stage"] for e in json.loads(record2.read_text())["artifact"]["errors"]] == ["card"])
        finish("pr", "https://example.test/o/r/pull/1", "--card")
        pending = json.loads(run("receipt", "r", "t2").stdout)
        before = record2.read_bytes()
        ok("C4: PR and both pending projections can be read by a later caller; bad coordinates acknowledge nothing",
           pending["pr_url"] == "https://example.test/o/r/pull/1" and set(pending["pending"]) == {"board", "card"}
           and finish("project", "card", "--chat", "fixture", "--ts", "bad").returncode != 0
           and record2.read_bytes() == before)
        finish("project", "board"); finish("project", "card", "--chat", "fixture", "--ts", "1.2")
        finish("pr", "https://example.test/o/r/pull/1", "--card")
        settled = json.loads(run("receipt", "r", "t2").stdout)
        ok("C5: acknowledgement clears its error atomically; retry keeps the card and cannot acknowledge it twice",
           settled["card"] == {"chat": "fixture", "ts": "1.2"} and set(settled["pending"]) == {"board"}
           and finish("project", "card", "--chat", "fixture", "--ts", "1.3").returncode != 0
           and json.loads(record2.read_text())["executions"] == got["executions"]
           and settled["errors"] == [])
        # C5b's subject is the workspace delivery: a branch that IS the delivery, with no PR anywhere. C4's PR is
        # taken off the record for it and put back after, because a task that HAS one is delivery-pending and
        # refuses the claim (D1) — what this case is about is `delivered` not CLOSING the record.
        carded = json.loads(record2.read_text())
        record2.write_text(json.dumps(dict(carded, pr=None, card=None)))
        ok("C5b: a delivery with no PR projects done and leaves the task claimable — C6 is its control, where a "
           "merge closes the record and the next claim is refused",
           finish("delivered").returncode == 0
           and json.loads(run("receipt", "r", "t2").stdout)["pending"]["board"] == {"status": "done"}
           and json.loads(record2.read_text())["closed"] is None
           and run("check", "r", "t2", "--executor", "worker").returncode == 0)
        record2.write_text(json.dumps(dict(json.loads(record2.read_text()),
                                           pr=carded["pr"], card=carded["card"])))
        finish("close", "merged"); closed = json.loads(run("receipt", "r", "t2").stdout)
        ok("C6: closed receipts still accept pending board acknowledgements; claims and artifact rewrites are refused",
           closed["closed"]["status"] == "merged" and closed["pending"]["board"]["status"] == "merged"
           and finish("project", "board").returncode == 0 and finish("artifact", "--committed-sha", other).returncode != 0
           and run("claim", "r", "t2", "--executor", "worker").returncode != 0
           and json.loads(run("receipt", "r", "t2").stdout)["pending"] == {})

        # R1-R4 use the real command, row lock and canonical Git tree. No worker or runtime is launched.
        repair_base = json.loads(record2.read_text()); repair_base["closed"] = None
        repair_base["claim"]["executor"] = "subagent"
        record2.write_text(json.dumps(repair_base))
        reserve = ("reserve-repair", "r", "t2", "--generation", generation, "--branch", "track/t2",
                   "--pr", repair_base["pr"]["url"], "--head", sha)
        before = record2.read_bytes()
        with Lock(record2.parent):
            racers = [subprocess.Popen([sys.executable, __file__, *reserve], env=env, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for _ in range(2)]
            time.sleep(.15)
            held = all(p.poll() is None for p in racers) and record2.read_bytes() == before
        answers = [json.loads(p.communicate(timeout=60)[0]) for p in racers]
        reserved = json.loads(record2.read_text()); before = record2.read_bytes()
        ok("R1: repair waits for the row lock; two dispatches get one execution and only one launch permission",
           held and all(p.returncode == 0 for p in racers) and sorted(a["launch"] for a in answers) == [False, True]
           and answers[0]["execution_id"] == answers[1]["execution_id"]
           and reserved["claim"]["phase"] == "repair" and reserved["executions"][-1]["phase"] == "repair"
           and not answers[0]["repair"]["resume"] and len(reserved["executions"]) == len(repair_base["executions"]) + 1)
        claimed = run("claim", "r", "t2", "--executor", "worker")
        c = reserved["claim"]
        def adoption(b):   # what an adopting claim writes: the reservation's adopted_at, and nothing else
            d = json.loads(b); r = d["executions"][-1].get("repair") or {}
            at = r.get("adopted_at"); r["adopted_at"] = None
            return at, d
        at, rest = adoption(record2.read_bytes())
        ok("R2: the dispatcher's worker claim reuses the repair and marks it adopted; no extra build execution or "
           "new generation",
           claimed.returncode == 0 and at and rest == json.loads(before)
           and run("renew", "r", "t2", repair_base["claim"]["claim_id"], generation).returncode != 0)
        run("release", "r", "t2", c["claim_id"], str(c["generation"]), "--reason", "worker launched")
        before = record2.read_bytes(); replay = run(*reserve)
        ok("R2 control: after release, an old dispatch still gets the same reservation with launch=false",
           replay.returncode == 0 and not json.loads(replay.stdout)["launch"]
           and json.loads(replay.stdout)["execution_id"] == answers[0]["execution_id"] and record2.read_bytes() == before)
        dead = json.loads(record2.read_text()); dead["claim"]["owner"]["boot_id"] = "previous-boot"
        dead["claim"]["ended_at"] = None; record2.write_text(json.dumps(dead)); before = record2.read_bytes()
        replay = run(*reserve)
        ok("R2 restart control: an ambiguous dispatch whose owner died keeps its reservation too",
           replay.returncode == 0 and not json.loads(replay.stdout)["launch"] and record2.read_bytes() == before)
        for field, value in (("repo", "other"), ("branch", "track/other"), ("pr", {"url": "https://example.test/o/r/pull/2"}),
                             ("closed", {"status": "merged"})):
            wrong = dict(repair_base, **{field: value}); record2.write_text(json.dumps(wrong)); before = record2.read_bytes()
            refused = run(*reserve)
            ok(f"R3: repair with mismatched {field} is a request that must be refused; R1 is its control",
               refused.returncode != 0 and record2.read_bytes() == before)
        record2.write_text(json.dumps(repair_base)); before = record2.read_bytes()
        ok("R3 generation/head controls: stale generation, short SHA and absent task reserve nothing",
           run(*reserve, "--generation", "0").returncode != 0 and run(*reserve, "--head", "short").returncode != 0
           and run("reserve-repair", "r", "absent", *reserve[3:]).returncode != 0 and record2.read_bytes() == before)
        git("-C", str(root / ".cc/worktrees/r/t2"), "checkout", "-q", "--detach")
        ok("R3 worktree control: a matching record with the actual tree on the wrong HEAD reserves nothing",
           run(*reserve).returncode != 0 and record2.read_bytes() == before)
        git("-C", str(root / ".cc/worktrees/r/t2"), "checkout", "-q", "track/t2")
        repair_base["claim"]["executor"] = "worker"; record2.write_text(json.dumps(repair_base))
        worker = json.loads(run(*reserve).stdout)
        changed = json.loads(run(*reserve, "--generation", str(worker["generation"]), "--head", other).stdout)
        ok("R4: a worker repair resumes; a different head is a different execution, while the old head stays spent",
           worker["repair"]["resume"] and worker["launch"] and changed["launch"]
           and changed["execution_id"] != worker["execution_id"]
           and not json.loads(run(*reserve).stdout)["launch"])
        # R5: --relaunch is that spent head again once its claim has ended — a repair whose worker stopped on a usage
        # limit before it pushed (raised-a-limit-stopped-repair-cannot-restart) — and never while a claim is live.
        again = (*reserve[:4], str(changed["generation"]), *reserve[5:-1], other, "--relaunch")
        before = record2.read_bytes(); live = run(*again)
        held = live.returncode == 0 and not json.loads(live.stdout)["launch"] and record2.read_bytes() == before
        run("claim", "r", "t2", "--executor", "worker")   # its worker started (adopted it) and then stopped
        run("release", "r", "t2", changed["claim_id"], str(changed["generation"]), "--reason", "worker launched")
        relaunched = json.loads(run(*again).stdout)
        twice = json.loads(run(*(*again[:4], str(relaunched["generation"]), *again[5:])).stdout)
        ok("R5: --relaunch while the repair's claim is live grants nothing; once it ended it launches that head once, "
           "naming the execution it replaces",
           held and relaunched["launch"] and relaunched["repair"]["relaunch_of"] == changed["execution_id"]
           and relaunched["execution_id"] != changed["execution_id"] and relaunched["generation"] == changed["generation"] + 1
           and not twice["launch"] and twice["execution_id"] == relaunched["execution_id"])

        # D1-D4: DELIVERY-PENDING. From the PR to the closure the change belongs to the landing queue, so an
        # ordinary claim is refused — `cc … --go` asks `check` before it writes a brief or buys a turn, so the
        # refusal costs nothing. The queue's own reservation is the one re-entry, and it launches once. Each case
        # resets the record first, so one of them failing leaves the next reading the state it was written for.
        pending = json.loads(json.dumps(repair_base))
        pending["claim"].update(executor="subagent", phase="starting", ended_at=stamp(), reason="delivered")
        gen = str(pending["claim"]["generation"]); url = pending["pr"]["url"]
        def delivered():
            record2.write_text(json.dumps(pending)); return record2.read_bytes()
        def answer(r): return json.loads(r.stdout or "{}")
        reserve2 = ("reserve-repair", "r", "t2", "--generation", gen, "--branch", "track/t2",
                    "--pr", url, "--head", sha)

        before = delivered(); refused = run("claim", "r", "t2", "--executor", "worker")
        astray = run("claim", "r", "t2", "--executor", "subagent")
        asked = run("check", "r", "t2", "--executor", "worker"); unwritten = record2.read_bytes() == before
        # …and the builder's OWN live claim is no way round it either: `cc done` records the PR from inside that
        # claim, so the record is delivery-pending while the claim that built it is still live and still this
        # owner's. Only a claim in the repair PHASE is the queue's re-entry.
        building = json.loads(json.dumps(pending))
        building["claim"].update(ended_at=None, phase="starting", executor="worker", reason=None)
        record2.write_text(json.dumps(building)); before = record2.read_bytes()
        ok("D1: a recorded PR makes the row delivery-pending — claim and check refuse, naming the PR, and nothing "
           "is written, whether the claim that built it has ended or is still live and this owner's; C5b's "
           "delivery with no PR is its control",
           refused.returncode != 0 and url in refused.stderr and "delivery-pending" in refused.stderr
           and astray.returncode != 0 and asked.returncode != 0 and unwritten
           and run("claim", "r", "t2", "--executor", "worker").returncode != 0
           and record2.read_bytes() == before)

        delivered(); denied = run("claim", "r", "t2", "--executor", "worker")
        granted = answer(run(*reserve2)); after = record2.read_bytes()
        adopted = run("claim", "r", "t2", "--executor", "worker"); at, rest = adoption(record2.read_bytes())
        unchanged = bool(at) and rest == json.loads(after)
        sub = run("claim", "r", "t2", "--executor", "subagent")   # the reservation launches ONE worker, not a subagent
        ok("D2: the reservation is the way in that D1 refuses without — it launches, and the `cc … --go` the queue "
           "then runs adopts that repair instead of taking a claim of its own, while a subagent on that same "
           "reservation is still refused",
           denied.returncode != 0 and granted.get("launch") and adopted.returncode == 0 and unchanged
           and sub.returncode != 0
           and json.loads(record2.read_text())["claim"]["phase"] == "repair"
           and json.loads(record2.read_text())["executions"][-1]["execution_id"] == granted["execution_id"])

        delivered(); spent = answer(run(*reserve2)); held = json.loads(record2.read_text())["claim"]
        run("claim", "r", "t2", "--executor", "worker")   # the launch adopts it, as claim_track does before any window
        run("release", "r", "t2", held["claim_id"], str(held["generation"]), "--reason", "worker launched")
        before = record2.read_bytes(); replay = answer(run(*reserve2))
        ok("D3: a second repair for the same PR and head buys nothing — the replay grants no launch, and the row "
           "is delivery-pending again the moment the launched worker's claim ends; D2 is its control",
           spent.get("launch") and replay.get("launch") is False
           and replay["execution_id"] == spent["execution_id"]
           and run("claim", "r", "t2", "--executor", "worker").returncode != 0
           and run("claim", "r", "t2", "--executor", "subagent").returncode != 0
           and record2.read_bytes() == before)

        # D3b: A RESERVATION RELEASED BEFORE ANY LAUNCH ADOPTED IT STARTED NO WORKER (2026-10-15: the launch
        # refused its own claim, the seat released it by hand, and the head's one repair read as spent).
        delivered(); first = answer(run(*reserve2)); held = json.loads(record2.read_text())["claim"]
        run("release", "r", "t2", held["claim_id"], str(held["generation"]), "--reason", "launch refused")
        now = ("--generation", str(held["generation"]))   # `cc` reads the current generation before each reserve
        again = answer(run(*reserve2, *now)); regranted = json.loads(record2.read_text())["claim"]
        ok("D3b: a repair reservation released before any launch adopted it may be reserved again at the same "
           "head — once; D3 is the adopted control, which stays spent",
           first.get("launch") and again.get("launch") and again["execution_id"] != first["execution_id"]
           and regranted["generation"] == held["generation"] + 1 and regranted["phase"] == "repair"
           and answer(run(*reserve2, "--generation", str(regranted["generation"]))).get("launch") is False)

        delivered(); old = json.loads(record2.read_text())
        receipts = root / ".cc/state/.receipts/r"; receipts.mkdir(parents=True, exist_ok=True)
        kept = receipts / f"t2.{old['task_id']}.json"
        blocked = run("claim", "r", "t2", "--executor", "worker")
        os.replace(record2, kept)   # what `cc rm` does with a finished row: the receipt outlives it
        fresh = answer(run("claim", "r", "t2", "--executor", "worker"))
        ok("D4: new work never inherits the delivered task — refused on that record, and given a new identity only "
           "once the record is retired, which keeps the old task and its PR in the receipt",
           blocked.returncode != 0 and fresh.get("task_id") not in (None, old["task_id"])
           and fresh["pr"] is None and fresh["claim"]["generation"] == 1 and len(fresh["executions"]) == 1
           and json.loads(kept.read_text())["pr"] == old["pr"]
           and json.loads(kept.read_text())["task_id"] == old["task_id"])

        # D5: THE RESERVATION IS THE PROCESS'S THAT TOOK IT, and only two real processes can say so — every run()
        # above shares this one as its owner. cc-land reserves and then launches; a second dispatcher arriving at
        # that same PR is not that launch, whether cc-land is still running or died between the two.
        delivered(); gate5 = root / "gate5"
        land_ps, rcs5 = owners("repair", 1, gate5, row="t2", extra=reserve2)
        reserved5 = json.loads(record2.read_text())
        while_alive = run("claim", "r", "t2", "--executor", "worker")
        gate5.unlink()
        for p in land_ps: p.wait(timeout=60)
        once_gone = run("claim", "r", "t2", "--executor", "worker")
        ok("D5: another process's repair reservation is not this one's launch — its own claim is, and a second "
           "dispatcher is refused both while it runs and after it dies holding the reservation; D2 is the "
           "same-owner control",
           rcs5 == ["00"] and reserved5["claim"]["phase"] == "repair"
           and not same_owner(reserved5["claim"]["owner"], owner())
           and while_alive.returncode != 0 and once_gone.returncode != 0
           and answer(run(*reserve2)).get("launch") is False)

        # B1-B5: the runtime payload is the only agent identity. The helper is a hook stand-in, kept in
        # this fixture; no CLI accepts an agent id. Both children have this selfcheck as their parent.
        env["CC_NATIVE_ADAPTER"] = "1"
        for row in ("n1", "n2"):
            tree = root / f".cc/worktrees/r/{row}"
            git("-C", str(dev), "worktree", "add", "-q", "-b", f"track/{row}", str(tree))
            d = json.loads(run("claim", "r", row, "--executor", "subagent").stdout)
            d["claim"]["native"] = {"session_id": "parent", "dispatch_event": row}
            (root / f".cc/state/r/{row}/delivery.json").write_text(json.dumps(d))
        def native_record(row): return root / f".cc/state/r/{row}/delivery.json"
        tokens = {row: native_token(native_record(row).parent, json.loads(native_record(row).read_text())["claim"]) for row in ("n1", "n2")}
        helper = "import json,runpy,sys; from pathlib import Path; t=runpy.run_path(sys.argv[1]); " \
                 "t['native_bind'](Path(sys.argv[2]),sys.argv[3],json.loads(sys.argv[4]))"
        def bind(row, agent, event="first", parent="parent"):
            payload = {"agent_id": agent, "tool_use_id": event, "session_id": parent, "transcript_path": "fixture.jsonl"}
            return subprocess.run([sys.executable, "-c", helper, __file__, str(native_record(row).parent),
                                   tokens[row], json.dumps(payload)], env=env, capture_output=True, text=True)
        before = native_record("n1").read_bytes()
        ok("B1: begin with no binding is a request that must be refused; B2 is its control",
           run("begin", tokens["n1"]).returncode != 0 and native_record("n1").read_bytes() == before)
        ok("B2: runtime binding changes the owner; its control is that the parent can no longer release",
           bind("n1", "child-a").returncode == 0
           and json.loads(native_record("n1").read_text())["claim"]["owner"]["agent_id"] == "child-a"
           and run("release", "r", "n1", tokens["n1"].split("/")[-1], "1", "--reason", "parent returned").returncode != 0)
        before = native_record("n2").read_bytes()
        ok("B3: an agent already bound to another row is a request that must be refused; a different child is its control",
           bind("n2", "child-a").returncode != 0 and native_record("n2").read_bytes() == before
           and bind("n2", "child-b").returncode == 0)
        before = native_record("n1").read_bytes()
        ok("B4: swapped agent, wrong parent and second use are requests that must be refused; exact replay is their control",
           bind("n1", "child-b").returncode != 0 and bind("n1", "child-a", parent="other").returncode != 0
           and bind("n1", "child-a", event="second").returncode != 0 and bind("n1", "child-a").returncode == 0
           and native_record("n1").read_bytes() == before)
        worker = run("claim", "r", "n1", "--executor", "worker"); before = native_record("n1").read_bytes()
        ok("B5: a worker still supersedes a bound subagent; that old token's bootstrap is a request that must be refused",
           worker.returncode == 0 and json.loads(worker.stdout)["claim"]["generation"] == 2
           and bind("n1", "child-a").returncode != 0 and run("begin", tokens["n1"]).returncode != 0
           and native_record("n1").read_bytes() == before)

        bad_schema = json.loads(record2.read_text()); bad_schema["schema"] = 99
        (root / ".cc/state/r/t2/delivery.json").write_text(json.dumps(bad_schema))
        ok("…while a record this cc-task did not write is refused, not adopted",
           run("claim", "r", "t2", "--executor", "worker").returncode != 0
           and run("check", "r", "t2").returncode != 0
           and json.loads((root / ".cc/state/r/t2/delivery.json").read_text())["schema"] == 99)

        me = {"process": {k: process(os.getpid())[k] for k in ("pid", "start_ticks")},
              "boot_id": boot_id(), "agent_id": None}
        reused = json.loads(json.dumps(me)); reused["process"]["start_ticks"] += 1
        ok("a reused pid, another boot and a sibling agent are each a different owner, and none of them is alive",
           same_owner(me, me) and alive(me) and not same_owner(me, reused) and not alive(reused)
           and not same_owner(me, {**me, "boot_id": "another-boot"})
           and not alive({**me, "boot_id": "another-boot"})
           and not same_owner(me, {**me, "agent_id": "sibling"}))

        # A KILLED LAUNCH (2026-10-04): a `cc … --go` stopped by a Bash timeout between taking the worker claim and
        # opening the window left the claim held by the seat that typed it, alive for hours. Each case writes its
        # own row's record: the owner is a live process that is not this check's, the launcher one that has exited.
        # recurring-defect-ok: pause-hold-missing — these cases write delivery.json under the check's temp root; nothing launches a worker or writes the board
        seat = subprocess.Popen(["sleep", "600"]); gone = subprocess.Popen(["sleep", "600"])   # killed in finally
        try:
            def ident(pid): return {k: process(pid)[k] for k in ("pid", "start_ticks")}
            live_owner = {"process": ident(seat.pid), "boot_id": boot_id(), "agent_id": None}
            live_cc, dead_cc = ident(seat.pid), ident(gone.pid)
            gone.kill(); gone.wait()
            def held(row, executor, launcher):
                d = new_record("r", row, root / f".cc/worktrees/r/{row}")
                do_claim(d, live_owner, executor, by=launcher)
                if launcher and executor != "worker": d["claim"]["launcher"] = launcher   # a record nothing writes, to prove it is ignored
                f = root / f".cc/state/r/{row}/delivery.json"; f.parent.mkdir(parents=True); f.write_text(json.dumps(d))
                return d
            held("k1", "worker", dead_cc)
            ok("a worker's claim whose launching cc has exited is free to the next dispatcher, though its seat lives",
               alive(live_owner) and run("check", "r", "k1", "--executor", "worker").returncode == 0)
            held("k2", "worker", live_cc)
            ok("…while its launcher still runs, the claim is that launch's and the next dispatcher is refused",
               run("check", "r", "k2", "--executor", "worker").returncode != 0)
            held("k3", "worker", None)
            ok("…and a worker claim that names no launcher holds for its live owner, as before",
               run("check", "r", "k3", "--executor", "worker").returncode != 0)
            held("k4", "subagent", dead_cc)
            ok("a subagent's claim outlives the cc that took it: a launcher on it frees nothing",
               run("check", "r", "k4", "--executor", "subagent").returncode != 0)
            d = held("k5", "worker", dead_cc); c = d["claim"]
            ok("the same seat launching again hands its own claim to the new cc, and the same cc changes nothing",
               do_claim(d, live_owner, "worker", by=live_cc) == 1 and d["claim"] is c and c["launcher"] == live_cc
               and c["generation"] == 1 and do_claim(d, live_owner, "worker", by=live_cc) == 0)
            # recurring-defect-ok: pause-hold-missing — an in-memory record; nothing launches or writes the board
            ok("…and the same seat's `cc claim` (no launcher) keeps the one that --go recorded",
               do_claim(d, live_owner, "worker") == 0 and c["launcher"] == live_cc)
            # e2e-cc-claim, run by the lander's lane on this PR's tree merged with main (tree a7626c05) at
            # 2026-10-29T12:12Z: passed in 74 s.
            # recurring-defect-ok: pause-hold-missing — an in-memory record; nothing launches or writes the board
            dd = held("k11", "worker", dead_cc); dc = dd["claim"]
            ok("a plain `cc claim` over a worker claim whose --go has exited returns 0, keeps the dead launcher, and the row is free to the next dispatcher",
               do_claim(dd, live_owner, "worker") == 0 and dd["claim"] is dc and dc["launcher"] == dead_cc
               and run("check", "r", "k11", "--executor", "worker").returncode == 0)
            sub = new_record("r", "k6", root / ".cc/worktrees/r/k6"); do_claim(sub, live_owner, "subagent", by=live_cc)
            ok("…and a subagent's claim never records one", sub["claim"]["launcher"] is None)
            killed = held("k7", "worker", dead_cc); other = {**live_owner, "agent_id": "next-dispatcher"}
            ok("the dispatcher that takes a killed launch's claim says so on the old execution",
               do_claim(killed, other, "worker", by=live_cc) == 1 and killed["claim"]["generation"] == 2
               and killed["executions"][0]["outcome"] == "superseded (its launch was killed)")
            rep = new_record("r", "k10", root / ".cc/worktrees/r/k10"); do_claim(rep, live_owner, "worker", "repair")
            rep["executions"][-1]["repair"] = {"adopted_at": None}
            ok("a --go's claim that hands a repair reservation to its cc also marks that reservation adopted",
               do_claim(rep, live_owner, "worker", by=live_cc) == 1 and adopt(rep) == 1
               and rep["executions"][-1]["repair"]["adopted_at"] and adopt(rep) == 0)
            def under_cc(row, *flag):   # cc-task run by a shell whose argv[0] is bin/cc, as `cc` runs it
                git("-C", str(dev), "worktree", "add", "-q", "-b", f"track/{row}", str(root / f".cc/worktrees/r/{row}"))
                r = subprocess.run([str(BIN / "cc"), "-c", '"$@"; :', "cc", sys.executable, __file__, "claim", "r", row,
                                    "--executor", "worker", *flag], executable="/bin/bash", env=env,
                                   capture_output=True, text=True, timeout=60)
                return r.returncode, json.loads(r.stdout or "{}").get("claim") or {}
            rc8, c8 = under_cc("k8"); rc9, c9 = under_cc("k9", "--launch")
            ok("only a --go's claim (--launch) is tied to its cc; `cc claim --executor worker` holds for its owner",
               rc8 == 0 and rc9 == 0 and c8.get("launcher") is None and (c9.get("launcher") or {}).get("pid"))
        finally:
            seat.kill(); seat.wait()
    with tempfile.TemporaryDirectory(prefix="cctask-launch-") as proc:   # the launcher read off a fake /proc
        def fake(pid, ppid, comm, argv, ticks=100):
            d = Path(proc, str(pid)); d.mkdir()
            (d / "stat").write_text(f"{pid} ({comm}) S {ppid} " + " ".join(["0"] * 17) + f" {ticks}\n")
            (d / "comm").write_text(comm + "\n"); (d / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
        fake(40, 1, "claude", ["claude"], 7); fake(45, 40, "bash", ["bash", "-c", "cc r t --go x"], 8)
        fake(50, 45, "bash", ["bash", str(BIN / "cc"), "r", "t", "--go", "x"], 9)
        fake(60, 50, "bash", ["bash", str(BIN / "cc"), "r", "t", "--go", "x"], 11)   # the `$(…)` around cc-task
        fake(70, 40, "bash", ["bash", "-c", "cc-task claim r t --executor worker"], 12)
        ok("the launcher is the outer cc, not the `$(…)` copy of it that runs cc-task",
           launcher(ancestry(60, proc)) == {"pid": 50, "start_ticks": 9})
        ok("…and cc-task run by anything but cc has none", launcher(ancestry(70, proc)) is None)
    print(f"cc-task selfcheck: {n} failed"); return 1 if n else 0
