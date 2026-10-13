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
    kids, socks, fifo_fds = [], [], []
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
        # a user service's PrivateTmp=yes /tmp and snap's: old, unheld, unnamed, ours, and never taken
        private = [mk("systemd-private-0123456789abcdef0123456789abcdef-box-cal.service-AbCdEf"),
                   mk("snap-private-tmp"), mk("snap-private-tmp.AbCd12")]

        # A server's door: bound by a relative name from inside its dir, because an AF_UNIX path stops at 108 bytes
        # and a lander's run root under TMPDIR is longer than that (the 922 review: bind raised and the check died).
        import socket as _socket

        def listen_in(d, name):
            here = os.getcwd()
            os.chdir(d)
            try:
                sk = _socket.socket(_socket.AF_UNIX)
                socks.append(sk)
                sk.bind(name)
                sk.listen(1)
            finally:
                os.chdir(here)

        # headless Chrome's scratch is a family, a dot name included; a listening socket or a fifo inside keeps it
        # whatever its age, and this process holding the socket is no help: its fd reads socket:[inode] in /proc
        chrome_go = mk(".com.google.Chrome.Go12Cd")
        open(f"{root}/.com.google.Chrome.Fi12Le", "w").write("x")
        chrome_sock = mk(".com.google.Chrome.Sk12Cd")
        listen_in(chrome_sock, "SingletonSocket")

        def fifo_in(d, held_open):
            os.mkfifo(f"{d}/pipe")
            if held_open:   # a fifo's fd reads as its path in /proc, so the process holding it keeps the dir
                fifo_fds.append(os.open(f"{d}/pipe", os.O_RDWR | os.O_NONBLOCK))
            return d
        chrome_fifo = fifo_in(mk(".com.google.Chrome.Ff12Cd"), True)
        land_fifo = fifo_in(mk("cc-land.run.999999997.fifo1234"), True)
        dash_sock = mk("dash-web-sock1234/run")
        listen_in(dash_sock, "s")
        dash_sock = os.path.dirname(dash_sock)
        # a dead server's door: a socket file nothing has bound any more, and a fifo nobody has open
        dead_sock = mk("cc-render.Dsock1/run")
        listen_in(dead_sock, f"gone-sc-{os.getpid()}")
        socks.pop().close()
        dead_sock = os.path.dirname(dead_sock)
        dead_fifo = fifo_in(mk(".com.google.Chrome.Dfifo1"), False)
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
        s_fifo = mk(f"claude-{uid}/-home-u-dev-r/88888888-9999-aaaa-bbbb-cccccccccccc/scratchpad")
        fifo_in(s_fifo, True)
        s_dead_fifo = fifo_in(mk(f"claude-{uid}/-home-u-dev-r/99999999-aaaa-bbbb-cccc-dddddddddddd/scratchpad"), False)
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
        # by a relative name, so a base under a lander's own run root (cc-land.run.*) puts no lander word in argv
        not_l = spawn([sys.executable, "-P", "landerish.py", "lander"], cwd=f"{base}/x")
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
        # `claude` straight from execve, not from bash: bash exports PWD, and a TMPDIR holding a session id (a
        # session's own scratch) would make this cwd name one, so the claude would not be blind
        kids.append(spawn(["claude", "60"], executable=sleep, cwd=blind_cwd))
        time.sleep(0.5)   # let each child reach its cwd, its open() and its mmap

        def reap(apply_, when=now, as_uid=None, hours=HOURS):
            buf = io.StringIO()
            todo = run(root, apply_, hours, now=when, uid=as_uid, out=buf, sessions=sessions, any_name=True)
            return {p for p, *_ in todo}, buf.getvalue()

        dry, text = reap(False)
        ok("a dry run removes nothing", all(os.path.lexists(p) for p in dry) and dry)
        ok("…and prints each entry it would remove with its size, and a total",
           "would remove" in text and old_dash in text and " MB" in text and "cc-tmp-reap: would remove" in text)
        ok("an old dir of a named family goes", old_dash in dry and f"{root}/cc-brief.q1w2e3r4" in dry)
        ok("an old file of a named family goes (a gate log)", f"{root}/cc-green.gate.Ab12Cd" in dry)
        ok("an old render scratch dir goes (cc-suites render, killed mid-stream)", render_left in dry)
        ok("a young one stays", young not in dry)
        ok("an old headless Chrome scratch dir or file goes, dot name and all",
           chrome_go in dry and f"{root}/.com.google.Chrome.Fi12Le" in dry)
        ok("…but not one holding a live listening socket that no process names", chrome_sock not in dry)
        ok("…nor one holding a fifo a process has open", chrome_fifo not in dry)
        ok("a socket or fifo keeps every family: a dead lander's run root, a dash dir with one a level down",
           land_fifo not in dry and dash_sock not in dry)
        ok("a dead server's socket file pins nothing: its old dir goes", dead_sock in dry)
        ok("…and nor does a fifo nobody has open", dead_fifo in dry)
        ok("an old dir with one fresh file inside stays", fresh_inside not in dry)
        ok("names no tool here made stay for 72 h (tmp.*, a bare mkdtemp, a person's dir, a prefix alone)",
           not dry.intersection(unnamed))
        # …and then go: a session's ad-hoc /tmp/<name> (13 G of a 16 G /tmp on 2026-09-27) has no family,
        # so its session ending is read as nothing naming it, holding it or writing to it for STALE_HOURS
        named_live = mk("ss-live-session")
        kids.append(spawn(["bash", "-c", "sleep 60; :", f"{named_live}/out.txt"]))   # a live session's argv names it
        door = mk("tmux-0")
        listen_in(door, "default")
        dot = mk(".X99-lock-dir")
        # names with odd bytes, each named by a live process and nothing else: a whitespace split once kept `my` and
        # took `my task` (the 922 review). A space in argv, a newline in the environment, a shell-escaped space in a
        # `bash -c` script, and a cwd whose name has both.
        odd = {"space in argv": mk("my task"), "newline in environ": mk("line\nbreak"),
               "escaped space in a script": mk("esc aped"), "space and newline in cwd": mk("cwd sp\nnl")}
        kids.append(spawn(["bash", "-c", "sleep 60; :", f"{odd['space in argv']}/out.txt"]))
        kids.append(spawn([sleep, "60"], env={**quiet, "OUT": f"{odd['newline in environ']}/out.txt"}))
        kids.append(spawn(["bash", "-c", f"sleep 60; cat {root}/esc\\ aped/out; :"]))
        kids.append(spawn([sleep, "60"], cwd=odd["space and newline in cwd"]))
        time.sleep(0.3)
        later = reap(False, when=now + 2 * 86400)[0]
        ok("…and after 72 h an unnamed dir nothing holds or names goes (an ended session's scratch)",
           set(unnamed) <= later)
        ok("…but never a service's private /tmp (systemd-private-*), at any age", private[0] not in later)
        ok("…nor snap's (snap-private-tmp, snap-private-tmp.*), at any age", not later.intersection(private[1:]))
        buf = io.StringIO()
        tmpdir_only = {p for p, *_ in run(root, False, HOURS, now=now + 2 * 86400, out=buf, sessions=sessions,
                                           any_name=False)}
        ok("…and in a root other than /tmp and the scratch on disk an unnamed dir stays at any age, a family still goes",
           not tmpdir_only.intersection(unnamed) and old_dash in tmpdir_only)
        ok("…which TMPDIR naming another dir is: only /tmp and the scratch on disk take any name",
           os.path.realpath(root) not in stale_roots() and os.path.realpath("/tmp") in stale_roots()
           and os.path.realpath(SCRATCH) in stale_roots())
        ok("…while one a live process names in its argv stays", named_live not in later)
        for what, p in odd.items():
            ok(f"…and so does one with odd bytes in its name ({what})", p not in later)
        ok("a mention keeps every name it may mean: up to a space or a colon, and whole",
           named_entries(f"x {root}/my task/out\0P={root}/a:{root}/b c".encode(), root)
           >= {"my", "my task", "a", "a:", "b", "b c"})
        ok("…and never a name it cannot (another root, a longer name with the same start)",
           not named_entries(f"/elsewhere/my task {root}x/my {root}/mytask".encode(), root) & {"my", "my task"})
        ok("…and one with a socket inside (a server's door) or a dot name stays", door not in later and dot not in later)
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
        ok("…but not one with a fifo inside that a process has open", os.path.dirname(s_fifo) not in dry)
        ok("…while one whose fifo nobody has open goes", os.path.dirname(s_dead_fifo) in dry)
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
                kids.append(spawn(["claude", "60"], executable=sleep, cwd=proj))
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
        gone, _ = reap(True, when=now + 3 * 86400)
        ok("--apply after 72 h takes the unnamed dirs and leaves each odd-named one a live process names",
           set(unnamed) <= gone and all(os.path.isdir(p) for p in odd.values()) and not gone & set(odd.values())
           and all(os.path.isdir(p) for p in private))
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
        for sk in socks:
            sk.close()
        for fd in fifo_fds:
            os.close(fd)
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
