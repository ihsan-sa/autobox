# cc-tmp-reap's selfcheck: the cases behind `cc-tmp-reap selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-tmp-reap execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    import contextlib
    import io
    cases = []

    def ok(what, cond):
        cases.append((what, bool(cond)))
        print(f"  {'ok ' if cond else 'FAIL'} {what}")

    base = tempfile.mkdtemp(prefix="cc-tmp-reap-sc.")
    root = f"{base}/tmp"
    os.makedirs(root)
    kids = []
    try:
        uid = os.getuid()
        sid_dead, sid_argv, sid_env = ("11111111-2222-3333-4444-555555555555", "22222222-3333-4444-5555-666666666666",
                                       "33333333-4444-5555-6666-777777777777")

        def mk(rel, files=("f",)):
            d = f"{root}/{rel}"
            os.makedirs(d, exist_ok=True)
            for f in files:
                with open(f"{d}/{f}", "w") as fh:
                    fh.write("x" * 5000)
            return d

        # the clock is run two days ahead, so every fixture is "old" unless it is dated into that future on purpose
        now = time.time() + 2 * 86400
        old_dash = mk("dash-src-abc12345")
        mk("cc-brief.q1w2e3r4")
        render_left = mk("cc-render.Ab12Cd")
        open(f"{root}/cc-green.gate.Ab12Cd", "w").write("log")
        young = mk("dash-web-young123")
        fresh_inside = mk("cc-slack-selfcheck-in5ide77", ("a", "b"))
        for p in (young, f"{young}/f", f"{fresh_inside}/b"):
            os.utime(p, (now, now))
        unnamed = [mk("tmp.AbCdEf1234"), mk("abcdefgh12"), mk("notes"), mk("dash-src-")]
        target = mk("real-dir-elsewhere")
        os.symlink(target, f"{root}/cc-brief.l1nk3d99")
        cwd_held = mk("cc-land-selfcheck-h-cwdheld1")
        fd_held = mk("claude-empty-fdheld12")
        map_held = mk("ccspend-empty-maphld12")
        run_dead = mk("cc-land.run.999999999.dead1234", ("cc-land.gates.r.1.x",))
        run_live = mk("cc-land.run.PID.live1234")
        run_kept = mk("cc-land.run.999999998.kept1234", (KEPT, "cc-land-gate-x.log"))
        lander_scr = [mk("lander-job.ab12cd34"), mk("lander-self.check.ab12cd34"), mk("lander-self.shadow.ab12cd34")]
        s_dead = mk(f"claude-{uid}/-home-u-dev-r/{sid_dead}/scratchpad")
        s_argv = mk(f"claude-{uid}/-home-u-dev-r/{sid_argv}/scratchpad")
        s_env = mk(f"claude-{uid}/-home-u-dev-r/{sid_env}/tasks")
        s_notsid = mk(f"claude-{uid}/-home-u-dev-r/not-a-session")
        s_cwd = mk(f"claude-{uid}/-home-u-dev-r/44444444-5555-6666-7777-888888888888")
        sid_json = "55555555-6666-7777-8888-999999999999"
        s_json = mk(f"claude-{uid}/-home-u-dev-r/{sid_json}/tasks")
        blind_cwd = mk("blind-proj.x")   # a live claude process in here names no id anywhere
        blind_slug = re.sub(r"[^A-Za-z0-9]", "-", blind_cwd)
        s_blind = mk(f"claude-{uid}/{blind_slug}/66666666-7777-8888-9999-aaaaaaaaaaaa/scratchpad")
        sessions = f"{base}/sessions"
        os.makedirs(sessions)

        sleep = shutil.which("sleep")

        # Every fixture process in a group of its own, so killpg ends it whole, and with no session id inherited from
        # the caller: run from inside a Claude session, CLAUDE_CODE_SESSION_ID made the "blind" claude a named one.
        quiet = {k: v for k, v in os.environ.items() if not SESSION.search(v)}

        def spawn(*a, **k):
            return subprocess.Popen(*a, start_new_session=True, **{"env": quiet, **k})
        kids.append(spawn([sleep, "60"], cwd=cwd_held))
        kids.append(spawn([sys.executable, "-c", "import sys,time; f=open(sys.argv[1]); time.sleep(60)",
                                      f"{fd_held}/f"]))
        kids.append(spawn([sys.executable, "-c", "import mmap,sys,time; f=open(sys.argv[1],'rb'); "
                                      "m=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ); f.close(); time.sleep(60)",
                                      f"{map_held}/f"]))
        lander = spawn(["bash", "-c", "exec -a cc-land sleep 60"])
        kids.append(lander)
        live_name = f"cc-land.run.{lander.pid}.live1234"
        os.rename(run_live, f"{root}/{live_name}")
        run_live = f"{root}/{live_name}"
        # the new lander: `python3 -P …/core/lander/cli.py lane r`, and lander-self; and a pid that is neither
        os.makedirs(f"{base}/x/core/lander")
        for f in ("core/lander/cli.py", "landerish.py"):
            open(f"{base}/x/{f}", "w").write("import time\ntime.sleep(60)\n")
        new_l = spawn([sys.executable, "-P", f"{base}/x/core/lander/cli.py", "lane", "r"])
        self_l = spawn(["bash", "-c", "exec -a /x/core/bin/lander-self sleep 60"])
        not_l = spawn([sys.executable, "-P", f"{base}/x/landerish.py", "lander"])
        kids += [new_l, self_l, not_l]
        run_new = mk(f"cc-land.run.{new_l.pid}.newlnd12")
        run_self = mk(f"cc-land.run.{self_l.pid}.selfln12")
        run_other = mk(f"cc-land.run.{not_l.pid}.other123")
        kids.append(spawn(["bash", "-c", "sleep 60; :", sid_argv]))
        kids.append(spawn([sleep, "60"], env={**os.environ, "SOME_SESSION": sid_env}))
        kids.append(spawn([sleep, "60"], cwd=s_cwd))
        by_json = spawn(["bash", "-c", "exec -a claude sleep 60"])
        kids.append(by_json)
        json.dump({"sessionId": sid_json, "cwd": "/home/u/dev/r"}, open(f"{sessions}/{by_json.pid}.json", "w"))
        kids.append(spawn(["bash", "-c", "exec -a claude sleep 60"], cwd=blind_cwd))
        time.sleep(0.5)   # let each child reach its cwd, its open() and its mmap

        def reap(apply_, when=now, as_uid=None, hours=HOURS):
            buf = io.StringIO()
            todo = run(root, apply_, hours, now=when, uid=as_uid, out=buf, sessions=sessions)
            return {p for p, *_ in todo}, buf.getvalue()

        dry, text = reap(False)
        ok("a dry run removes nothing", all(os.path.lexists(p) for p in dry) and dry)
        ok("…and prints each entry it would remove with its size, and a total",
           "would remove" in text and old_dash in text and " MB" in text and "cc-tmp-reap: would remove" in text)
        ok("an old dir of a named family goes", old_dash in dry and f"{root}/cc-brief.q1w2e3r4" in dry)
        ok("an old file of a named family goes (a gate log)", f"{root}/cc-green.gate.Ab12Cd" in dry)
        ok("an old render scratch dir goes (cc-suites render, killed mid-stream)", render_left in dry)
        ok("a young one stays", young not in dry)
        ok("an old dir with one fresh file inside stays", fresh_inside not in dry)
        ok("names no tool here made stay, however old (tmp.*, a bare mkdtemp, a person's dir, a prefix alone)",
           not dry.intersection(unnamed))
        ok("a symlink named like a family stays, and so does what it points at",
           f"{root}/cc-brief.l1nk3d99" not in dry and target not in dry)
        ok("a dir some process has as its cwd stays", cwd_held not in dry)
        ok("a dir holding a file some process has open stays", fd_held not in dry)
        ok("a dir holding a file some process has mapped stays", map_held not in dry)
        ok("a cc-land run root whose pid is dead goes", run_dead in dry)
        ok("…and one whose pid is a live cc-land stays", run_live not in dry)
        ok("…and one whose pid is the new lander (python3 -P …/core/lander/cli.py) or lander-self stays",
           run_new not in dry and run_self not in dry)
        ok("…while a live pid that is no lander keeps nothing", run_other in dry)
        ok("old lander-job.* / lander-self.check.* / lander-self.shadow.* scratch goes", set(lander_scr) <= dry)
        ok("…and one with the .kept marker stays for 72 h", run_kept not in dry)
        ok("…and goes after them", run_kept in reap(False, when=now + 3 * 86400)[0])
        ok("a session's scratch whose id no process names goes", os.path.dirname(s_dead) in dry)
        ok("…and one whose id is in a live process's argv stays", os.path.dirname(s_argv) not in dry)
        ok("…and one whose id is in a live process's environment stays", os.path.dirname(s_env) not in dry)
        ok("…and one a live process has its cwd in stays", s_cwd not in dry)
        ok("…and one a live claude's ~/.claude/sessions/<pid>.json names stays", os.path.dirname(s_json) not in dry)
        ok("…and every one under the cwd slug of a live claude that names no id stays",
           os.path.dirname(s_blind) not in dry)
        ok("…and a dir under claude-<uid> that is not a session id stays, and so do the slug dir and the root",
           s_notsid not in dry and f"{root}/claude-{uid}" not in dry and f"{root}/claude-{uid}/-home-u-dev-r" not in dry)
        ok("another user's entries are never taken", not reap(False, as_uid=uid + 12345)[0])
        ok("--hours moves the line: at 100 h the two-day-old fixtures stay", not reap(False, hours=100)[0])
        at13 = reap(False, when=time.time() + 13 * 3600, hours=12)[0]
        ok("…but a session's scratch stays under 24 h whatever --hours says, while a 13 h old family dir goes",
           old_dash in at13 and os.path.dirname(s_dead) not in at13)
        err, read, real_roots = io.StringIO(), [], roots
        try:   # roots() stands in for the box's: a refusal that regressed would reach no real root, and is seen here
            globals()["roots"] = lambda: read.append(1) or []
            with contextlib.redirect_stderr(err):
                rc = main(["--apply", "--hours", "0.5"])
        finally:
            globals()["roots"] = real_roots
        ok("--hours below 1 is refused before any root is read", rc == 2 and "below 1" in err.getvalue() and not read)
        gone, text = reap(True)
        ok("--apply removes exactly what the dry run listed", gone == dry and not any(os.path.lexists(p) for p in gone))
        ok("…and leaves every other fixture in place",
           all(os.path.lexists(p) for p in [young, fresh_inside, cwd_held, fd_held, map_held, run_live, run_kept,
                                             target, s_argv, s_env, s_cwd, s_json, s_blind, *unnamed]))
        ok("…and says what it removed per family", "cc-tmp-reap: removed" in text and "dashboard selfcheck: 1" in text)
        ok("a second run finds nothing more to do", not reap(True)[0])
        # An entry rmtree cannot empty (a dir inside it with no write bit) is named, and not counted as removed.
        stuck = mk("dash-deps-stuck123/sub")
        os.chmod(stuck, 0o500)
        try:
            _, text = reap(True)
            ok("an entry that cannot be removed is said so, stays, and is not counted",
               f"could not remove {os.path.dirname(stuck)}" in text and "removed 0 entries" in text
               and os.path.lexists(f"{stuck}/f"))
        finally:
            os.chmod(stuck, 0o700)
            shutil.rmtree(os.path.dirname(stuck), ignore_errors=True)

        # Between the plan and each remove: a file written, a process that takes a dir as its cwd, and a claude that
        # names no session id started in a project whose session scratch was judged dead. Once with only the new pids
        # read (a RECHECK_S far off), once with /proc read whole again (a RECHECK_S already passed).
        def race(tag, recheck):
            written, held = mk(f"dash-home-{tag}wr1"), mk(f"dash-deps-{tag}hld1")
            gone_ok = mk(f"dash-all-{tag}go1")
            proj = mk(f"late-{tag}.x")
            sdir = os.path.dirname(mk(f"claude-{uid}/{re.sub(r'[^A-Za-z0-9]', '-', proj)}/"
                                      f"77777777-8888-9999-aaaa-bbbbbbbbbbbb/scratchpad"))
            real_plan, real_recheck = plan, RECHECK_S

            def racing(*a, **k):
                todo = real_plan(*a, **k)
                os.utime(f"{written}/f")
                kids.append(spawn([sleep, "60"], cwd=held))
                kids.append(spawn(["bash", "-c", "exec -a claude sleep 60"], cwd=proj))
                time.sleep(0.5)
                return todo
            try:
                globals()["plan"], globals()["RECHECK_S"] = racing, recheck
                todo, text = reap(True)
            finally:
                globals()["plan"], globals()["RECHECK_S"] = real_plan, real_recheck
            judged = {written, held, gone_ok, sdir} <= todo
            ok(f"[{tag}] all four were judged dead, and the one nothing touched since goes",
               judged and not os.path.lexists(gone_ok))
            ok(f"[{tag}] one written to after the plan is left, and says so",
               os.path.lexists(f"{written}/f") and f"left {written}:" in text)
            ok(f"[{tag}] one a process started after the plan holds is left",
               os.path.lexists(f"{held}/f") and f"left {held}:" in text)
            ok(f"[{tag}] a session's scratch under the cwd of a claude started after the plan is left",
               os.path.lexists(f"{sdir}/scratchpad/f") and f"left {sdir}:" in text)
        race("newpid", 3600)
        race("reread", 0)
        # WHERE: the scratch on disk and TMPDIR are reaped beside /tmp, each once; a root that is missing is skipped.
        real_scratch, real_tempdir = SCRATCH, tempfile.tempdir
        try:
            globals()["SCRATCH"], tempfile.tempdir = f"{base}/scratch", root
            missing = roots()
            os.makedirs(SCRATCH)
            both = roots()
            tempfile.tempdir = SCRATCH
            same = roots()
        finally:
            globals()["SCRATCH"], tempfile.tempdir = real_scratch, real_tempdir
        ok("roots: /tmp, the scratch on disk and TMPDIR are each reaped — and TMPDIR naming the scratch lists it once",
           both == ["/tmp", os.path.realpath(f"{base}/scratch"), os.path.realpath(root)]
           and same == ["/tmp", os.path.realpath(f"{base}/scratch")])
        ok("…and a scratch root that does not exist yet is left out, not an error",
           missing == ["/tmp", os.path.realpath(root)])
    finally:
        for k in kids:   # the whole group: a `bash -c` fixture's sleep would outlive its shell
            try:
                os.killpg(k.pid, 9)
            except OSError:
                k.kill()
            k.wait()
        shutil.rmtree(base, ignore_errors=True)
    bad = [w for w, c in cases if not c]
    print(f"cc-tmp-reap selfcheck: {len(cases) - len(bad)} passed, {len(bad)} failed")
    return 1 if bad else 0
