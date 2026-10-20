# cc-room's selfcheck: the cases behind `cc-room selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-room execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

# recurring-defect-ok: pause-hold-missing — selfcheck fixtures: the two-host launches run against a fake peer in a temp tree, never a real project
def selfcheck():
    global PEER_LAUNCH_TIMEOUT
    import shutil
    import signal
    import tempfile
    n = bad = 0

    def t(name, got, want):
        nonlocal n, bad
        n += 1
        if got != want:
            bad += 1
            print(f"FAIL {name}: got {got!r}, want {want!r}")

    base = tempfile.mkdtemp(prefix="cc-room-sc.")
    keep = {k: os.environ.get(k) for k in ("CC_ROOM_DIR", "CC_STATUSLINE_DIR", "CC_USAGE_DIR", "CC_WORKER_CAP",
                                          "CC_WORKER_PACE_MARGIN", "CC_ROOM_POLL", "CC_CONFIG", "LANDER_LOADAVG",
                                          "TMUX", "TMUX_PANE", "CC_SLACK_ALIAS", "CC_ROOM_TMUX", "CC_ROOM_BIN",
                                          "CC_ROOM_NOTICE_AFTER", "CC_HEAVY_CAP", "CC_HEAVY_SCOPE",
                                          "CC_ROOM_GRACE", "CC_ROOM_NOTICE_RETRY", "CC_PEER_DIR", "CC_PEER_SSH", "HOME",
                                          "CC_ROOM_TRICKLE")}
    procs = []
    strays = []   # (pid, start) of what a stub window ran: ended in the finally only while still that process

    def stray(pid):
        strays.extend((x, starttime(x)) for x in tree(pid))

    # the box's own /proc/loadavg must never decide a case — give every fixture a calm one of its own,
    # in-process and in the subprocesses admit() and check spawn (LANDER_LOADAVG, read at import)
    calm = f"{base}/loadavg.calm"
    open(calm, "w").write("0.0 0.0 0.0 1/1 1\n")
    os.environ["LANDER_LOADAVG"] = calm
    old_loadavg = admission.LOADAVG
    admission.LOADAVG = calm
    # and the box's own peer must never be asked: no case reaches ~/.cc/peer
    os.makedirs(f"{base}/nopeer")
    os.environ["CC_PEER_DIR"] = f"{base}/nopeer"

    def fixture(name, cap=2, margin=10):
        """a room and a statusline dir of this case's own, nothing held, nothing queued"""
        d = f"{base}/{name}"
        os.makedirs(f"{d}/sl")
        os.environ.update(CC_ROOM_DIR=f"{d}/room", CC_STATUSLINE_DIR=f"{d}/sl", CC_USAGE_DIR=f"{d}/usage", CC_WORKER_CAP=str(cap),
                          CC_WORKER_PACE_MARGIN=str(margin), CC_ROOM_POLL="0.2", CC_CONFIG=f"{d}/config",
                          CC_ROOM_NOTICE_AFTER="3600", CC_HEAVY_CAP="1", CC_HEAVY_SCOPE="0", CC_ROOM_BIN=f"{d}/bin",
                          CC_ROOM_TMUX=f"{d}/bin/tmux", CC_ROOM_GRACE="1", CC_ROOM_NOTICE_RETRY="300",
                          CC_ROOM_TRICKLE="0")   # a hot load holds every case but TRICKLE's own
        for k in ("TMUX", "TMUX_PANE", "CC_SLACK_ALIAS"):   # never the session's own tmux server or orch
            os.environ.pop(k, None)
        # stubs: the broker and cc-notify write down what they were told, and refuse while {d}/down exists; with
        # {d}/vanish, tmux's list-panes and new-window remove every queue entry, as a cancel in between would; tmux
        # writes each -S socket it is given to {d}/sockets, is "up" once {d}/up exists, lists the window names in
        # {d}/windows (with -a, the ids in {d}/winids), the pane pid in {d}/panepid, and a new window runs its command
        # in the background with its -e environment (unless {d}/nospawn), its pid in {d}/panepid, and prints its id and the server pid in {d}/srv
        os.makedirs(f"{d}/bin")
        for name, body in (("cc-broker", f'echo "$*" >> "{d}/told"; [ ! -e "{d}/down" ]'),
                           ("cc-notify", f'echo "notify $*" >> "{d}/told"; [ ! -e "{d}/down" ]'),
                           ("tmux", f'''if [ "$1" = -S ]; then echo "$2 $3" >> "{d}/sockets"; shift 2; fi
case "$1" in
  display-message) printf 'main\\t\\n' ;;
  has-session) [ -e "{d}/up" ] ;;
  list-windows) case " $* " in *" -a "*) cat "{d}/winids" 2>/dev/null; true ;; *) cat "{d}/windows" 2>/dev/null ;; esac ;;
  list-panes) [ -e "{d}/vanish" ] && for f in "{d}"/room/queue/*; do rm -f "$f"; done
              cat "{d}/panepid" 2>/dev/null; true ;;
  kill-window) echo "$*" >> "{d}/killed"; : > "{d}/windows"; : > "{d}/winids" ;;
  new-window) for a; do last=$a; done; echo "$*" >> "{d}/spawned"
              prev=; for a; do [ "$prev" = -e ] && export "$a"; prev=$a; done   # as tmux does: -e is the window's env
              [ -e "{d}/vanish" ] && for f in "{d}"/room/queue/*; do rm -f "$f"; done
              if [ ! -e "{d}/nospawn" ]; then sh -c "$last" </dev/null >/dev/null 2>&1 & echo $! > "{d}/panepid"; fi
              echo "@7 $(cat "{d}/srv" 2>/dev/null || echo 0)" ;;
esac''')):
            open(f"{d}/bin/{name}", "w").write(f"#!/bin/sh\n{body}\n")
            os.chmod(f"{d}/bin/{name}", 0o755)
        return d

    def queued(what, tries=50):
        """the live queue entry of that launch, once its waiter has written it"""
        for _ in range(tries):
            hit = [p for p, (_, w) in live("queue").items() if w == what]
            if hit:
                return hit[0]
            time.sleep(0.1)
        return None

    def lines(path):
        return open(path).read().splitlines() if os.path.exists(path) else []

    def usage(d, used, left_s, name="s.json"):
        json.dump({"raw": {"rate_limits": {"five_hour": {"used_percentage": used,
                                                         "resets_at": int(time.time() + left_s)}}}},
                  open(f"{d}/sl/{name}", "w"))

    def holder(what):
        """a live process holding a slot, as an admitted loop does"""
        p = subprocess.Popen([sys.executable, __file__, "admit", what, "--", "sleep", "60"],
                             stderr=subprocess.DEVNULL)
        procs.append(p)
        for _ in range(50):
            if any(w == what for _, w in live("slots").values()):
                return p
            time.sleep(0.1)
        return p

    try:
        # room means it runs: nothing held, usage behind its clock
        d = fixture("room")
        usage(d, 20, 3 * 3600)   # 40% of the window gone, 20% used
        t("room: nothing held and usage behind the clock", why_not(), "")
        mark = f"{d}/ran"
        r = subprocess.run([sys.executable, __file__, "admit", "r/room", "--", "touch", mark], timeout=20,
                           capture_output=True)
        t("room: admit runs the launch at once", (r.returncode, os.path.exists(mark)), (0, True))

        # a simulated high load queues a new start, same as the lander's own overloaded() serializes on
        d = fixture("busy")
        hot = f"{base}/loadavg.hot"
        n = os.cpu_count() or 1
        open(hot, "w").write(f"{2.0 * n} 0.00 0.00 1/1 1\n")
        admission.LOADAVG = hot
        os.environ["LANDER_LOADAVG"] = hot
        t("busy: a high load average queues a new start", "the box is busy" in why_not(), True)
        t("busy: check exits 1 while the box is busy",
          subprocess.run([sys.executable, __file__, "check"], capture_output=True, text=True).returncode, 1)
        admission.LOADAVG = calm
        os.environ["LANDER_LOADAVG"] = calm
        t("busy: a calm load average is room again", why_not(), "")

        # TRICKLE: a hold by the load average alone lets the oldest launch through once no worker has started here
        # for CC_ROOM_TRICKLE seconds; cpu or memory pressure still holds. Run as subprocesses, the only way the
        # lander's PSI dir (read at import) is the case's own and never the box's
        def trickle(name, psi_cpu=None, started_ago=None, every="600"):
            d = fixture(name)
            psi = f"{d}/psi"
            os.makedirs(psi)
            if psi_cpu is not None:
                open(f"{psi}/cpu", "w").write(f"some avg10={psi_cpu} avg60=0.00 avg300=0.00 total=0\n")
            if started_ago is not None:
                os.makedirs(f"{d}/room", exist_ok=True)
                open(f"{d}/room/started", "w").close()
                os.utime(f"{d}/room/started", (time.time() - started_ago,) * 2)
            env = dict(os.environ, LANDER_LOADAVG=hot, LANDER_PSI_DIR=psi, CC_ROOM_TRICKLE=every)
            return d, env

        d, env = trickle("trickle-none")
        r = subprocess.run([sys.executable, __file__, "check"], capture_output=True, text=True, env=env)
        t("trickle: a load-only hold with no worker started yet is room", r.returncode, 0)

        d, env = trickle("trickle-admit")
        mark = f"{d}/ran"
        r = subprocess.run([sys.executable, __file__, "admit", "r/trickle", "--", "touch", mark], timeout=20,
                           capture_output=True, env=env)
        t("trickle: admit starts the launch through a load-only hold and stamps the start",
          (r.returncode, os.path.exists(mark), os.path.exists(f"{d}/room/started")), (0, True, True))

        d, env = trickle("trickle-recent", started_ago=60)
        r = subprocess.run([sys.executable, __file__, "check"], capture_output=True, text=True, env=env)
        t("trickle: a worker started 60s ago keeps a load-only hold",
          (r.returncode, "the box is busy" in r.stdout), (1, True))

        d, env = trickle("trickle-old", started_ago=900)
        r = subprocess.run([sys.executable, __file__, "check"], capture_output=True, text=True, env=env)
        t("trickle: the last start 900s ago (over 600) is room again", r.returncode, 0)

        d, env = trickle("trickle-pressure", psi_cpu="100.00")
        r = subprocess.run([sys.executable, __file__, "check"], capture_output=True, text=True, env=env)
        t("trickle: cpu pressure holds even with no worker started yet",
          (r.returncode, "the box is busy" in r.stdout), (1, True))

        d, env = trickle("trickle-off", every="0")
        r = subprocess.run([sys.executable, __file__, "check"], capture_output=True, text=True, env=env)
        t("trickle: CC_ROOM_TRICKLE=0 holds a load-only hold as before",
          (r.returncode, "the box is busy" in r.stdout), (1, True))

        # cap reached means queued, and one under it is not
        d = fixture("cap", cap=2)
        holder("r/a")
        t("cap: one slot held of two is room", why_not(), "")
        holder("r/b")
        t("cap: two slots held of two is queued", why_not().startswith("2 worker loops are running and the cap is 2"),
          True)
        t("cap: check exits 1 with the reason",
          subprocess.run([sys.executable, __file__, "check"], capture_output=True, text=True).returncode, 1)

        # pace ahead means queued; at the margin exactly is room
        d = fixture("pace", margin=10)
        usage(d, 57, 3 * 3600)   # 2 h into 5 h = 40% gone; 57 > 40 + 10
        t("pace: 57% used with 40% of the window gone is queued", "57%" in why_not(), True)
        usage(d, 50, 3 * 3600)
        t("pace: 50% used at 40% gone and a margin of 10 is room", why_not(), "")
        usage(d, 90, -60)
        t("pace: a window that has already reset is room", why_not(), "")
        usage(d, 90, 3 * 3600, "old.json")
        os.utime(f"{d}/sl/old.json", (1, 1))
        usage(d, 10, 3 * 3600, "new.json")
        t("pace: the freshest file decides, not an older one", why_not(), "")
        os.unlink(f"{d}/sl/new.json")
        t("pace: …and with only the older one left it is queued", "90%" in why_not(), True)

        # cc-usage-poll's live reading wins over the statusline files while it is fresh, and only then
        def polled(used, left_s, age_s):
            os.makedirs(f"{d}/usage", exist_ok=True)
            json.dump({"at": time.time() - age_s, "five_hour": {"used_percentage": used,
                                                                "resets_at": time.time() + left_s}},
                      open(f"{d}/usage/now.json", "w"))
        polled(64, 3 * 3600, 30)
        t("pace: a fresh now.json decides over the statusline files", "64%" in why_not(), True)
        polled(10, 3 * 3600, 600)
        t("pace: a stale now.json falls back to the statusline files", "90%" in why_not(), True)
        polled(10, -60, 30)
        t("pace: a fresh now.json whose window has reset falls back too", "90%" in why_not(), True)

        # the queued launch runs on its own once room frees, and not before
        d = fixture("frees", cap=1)
        h = holder("r/held")
        mark = f"{d}/ran"
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/queued", "--log", f"{d}/loop.log", "--",
                              "touch", mark], stderr=subprocess.DEVNULL)
        procs.append(w)
        time.sleep(1)
        t("frees: the queued launch has not run while the cap is held", os.path.exists(mark), False)
        t("frees: its log says it was queued and why",
          "r/queued queued — 1 worker loops are running" in open(f"{d}/loop.log").read(), True)
        t("frees: `queued` names the waiting launch, and not the one holding the slot",
          subprocess.run([sys.executable, __file__, "queued"], capture_output=True, text=True).stdout, "r/queued\n")
        h.kill()
        h.wait()
        w.wait(timeout=20)
        t("frees: it runs by itself once the slot is freed", os.path.exists(mark), True)
        t("frees: a finished launch holds no slot", live("slots"), {})

        # TWO HOSTS: a busy home hands the next worker to a peer with room; a quiet home keeps it. The peer is a
        # fake host: a home of its own, reached by a fake ssh that runs `cc-peer serve` there as the forced command
        # does, with a cc that only records what it was asked and a cc-room that says the peer has room.
        d = fixture("twohosts")
        peer = f"{d}/peerhome"
        os.makedirs(f"{peer}/bin")
        os.makedirs(f"{peer}/dev/r/.git")
        for tool, body in (("cc", f'printf "%s\\n" "$*" >>{peer}/cc.argv\nexit 0'), ("cc-room", "exit 0"),
                           ("cc-board", "exit 0")):
            open(f"{peer}/bin/{tool}", "w").write(f"#!/bin/sh\n{body}\n")
            os.chmod(f"{peer}/bin/{tool}", 0o755)
        fake_ssh = f"{d}/fake-ssh"
        open(fake_ssh, "w").write(f'#!/bin/sh\nexec env -i PATH="$PATH" HOME={peer} CC_PEER_CC={peer}/bin/cc '
                                  f'SSH_ORIGINAL_COMMAND="$*" {sys.executable} {BIN}/cc-peer serve\n')
        os.chmod(fake_ssh, 0o755)
        hub = f"{d}/hubhome"
        os.makedirs(f"{hub}/.cc/peer")
        os.makedirs(f"{hub}/.cc/state/r/w")
        open(f"{hub}/.cc/peer/dest", "w").write("user@peerbox\n")
        open(f"{hub}/.cc/state/r/w/task.md", "w").write("Goal: a worker.\n")
        loop = f"{d}/cc-loop"   # the launch a seat makes; run here, it leaves a mark
        open(loop, "w").write(f"#!/bin/sh\ntouch {d}/ran-here\n")
        os.chmod(loop, 0o755)
        os.environ.update(HOME=hub, CC_PEER_DIR=f"{hub}/.cc/peer", CC_PEER_SSH=fake_ssh, LANDER_LOADAVG=hot)
        r = subprocess.run([sys.executable, __file__, "admit", "r/w", "--log", f"{d}/loop.log", "--", loop, "r", "w",
                            "--max-iter", "2", "--model", "opus"], timeout=60, capture_output=True, text=True)
        t("two hosts: a busy home hands the worker to the peer and ends", (r.returncode, os.path.exists(f"{d}/ran-here")),
          (0, False))
        argv = open(f"{peer}/cc.argv").read() if os.path.exists(f"{peer}/cc.argv") else ""
        t("two hosts: the peer ran `cc r w --go` with the brief and the loop's flags",
          argv.startswith("r w --go Goal: a worker.") and "--loop 2 --model opus" in argv, True)
        t("two hosts: the hub recorded where it went", open(f"{hub}/.cc/peer/placed/r/w").read().split()[1], "peerbox")
        t("two hosts: a worker on the peer holds no slot here", live("slots"), {})
        os.environ["LANDER_LOADAVG"] = calm
        r = subprocess.run([sys.executable, __file__, "admit", "r/w", "--", loop, "r", "w"], timeout=60,
                           capture_output=True, text=True)
        t("two hosts: a quiet home keeps the next one", (r.returncode, os.path.exists(f"{d}/ran-here")), (0, True))
        t("two hosts: …and the peer was not asked to run it", open(f"{peer}/cc.argv").read().count("--go"), 1)
        os.environ.update(LANDER_LOADAVG=hot)
        open(f"{peer}/bin/cc-room", "w").write("#!/bin/sh\necho 'load 40 on 6 cores'\nexit 1\n")
        admission.LOADAVG = hot
        spot, why = place()
        t("two hosts: both busy queues it, saying why for each", (spot, "the box is busy" in why, "load 40" in why),
          ("", True, True))
        t("two hosts: check exits 1 when neither host has room",
          subprocess.run([sys.executable, __file__, "check"], capture_output=True, text=True).returncode, 1)
        # A SLOW PEER HOLDS UP NOBODY ELSE (round-4 security read of #1159): the peer was asked inside the room lock,
        # so while it took its time no heavy run, cancel or resume on the hub could move
        slow = f"{d}/slow-ssh"
        open(slow, "w").write(f"#!/bin/sh\ntouch {d}/asked\nsleep 8\nexit 1\n")
        os.chmod(slow, 0o755)
        os.environ["CC_PEER_SSH"] = slow
        if os.path.exists(f"{d}/ran-here"):
            os.unlink(f"{d}/ran-here")
        slowp = subprocess.Popen([sys.executable, __file__, "admit", "r/w", "--", loop, "r", "w"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(slowp)
        for _ in range(200):
            if os.path.exists(f"{d}/asked"):
                break
            time.sleep(0.1)
        t0 = time.time()
        r = subprocess.run([sys.executable, __file__, "heavy", "--name", "h", "--", "touch", f"{d}/heavy-ran"],
                           timeout=60, capture_output=True, text=True)
        n_cancel = cancel("r/w")
        took = time.time() - t0
        t("slow peer: a heavy run and a cancel go through while the peer is still being asked",
          (os.path.exists(f"{d}/asked"), r.returncode, os.path.exists(f"{d}/heavy-ran"), n_cancel, took < 3),
          (True, 0, True, 1, True))
        try:
            arc = slowp.wait(timeout=30)
        except subprocess.TimeoutExpired:
            arc = "still waiting"
        t("slow peer: …and the cancelled launch ends once the peer answers, run nowhere",
          (arc, os.path.exists(f"{d}/ran-here"), open(f"{peer}/cc.argv").read().count("--go")), (0, False, 1))
        # to_peer's own ends, in this process: a no rests the peer; a launch that hangs is bounded and rests it too;
        # a cancel before the launch starts nothing; a cancel during it still drops the entry, the peer running it
        os.environ["CC_PEER_SSH"] = fake_ssh   # its cc-room still says 'load 40'
        _peer_rest[0] = 0.0
        got = to_peer("r/w", [loop, "r", "w"], None, f"{d}/no-entry", "x")
        t("to_peer: a peer that says no is rested, with its reason",
          ("load 40" in got, _peer_rest[0] > time.time() + PEER_REST - 60, "asked again later" in peer_why()), (True, True, True))
        hang = f"{d}/hang-ssh"
        open(hang, "w").write('#!/bin/sh\n[ "$1" = room ] && exit 0\nsleep 5\n')
        os.chmod(hang, 0o755)
        os.environ["CC_PEER_SSH"] = hang
        _peer_rest[0] = 0.0
        got = to_peer("r/w", [loop, "r", "w"], None, f"{d}/no-entry", "x")
        t("to_peer: a launch cancelled before it starts is never handed over", got, "cancelled")
        ent = f"{room_dir()}/queue/x"
        os.makedirs(os.path.dirname(ent), exist_ok=True)
        open(ent, "w").write("{}")
        keep_to = PEER_LAUNCH_TIMEOUT
        PEER_LAUNCH_TIMEOUT = 1
        t0 = time.time()
        try:
            got = to_peer("r/w", [loop, "r", "w"], None, ent, "x")
        finally:
            PEER_LAUNCH_TIMEOUT = keep_to
        t("to_peer: a launch that never returns is bounded, and the peer rested",
          ("did not take it" in got, time.time() - t0 < 10, _peer_rest[0] > time.time()), (True, True, True))
        t("to_peer: …and the launch waits here again with no placing stamp", read_entry(ent).get("placing"), None)
        ok_ssh = f"{d}/ok-ssh"
        open(ok_ssh, "w").write("#!/bin/sh\nexit 0\n")
        os.chmod(ok_ssh, 0o755)
        os.environ["CC_PEER_SSH"] = ok_ssh
        _peer_rest[0] = 0.0
        os.makedirs(f"{room_dir()}/cancelled", exist_ok=True)
        open(f"{room_dir()}/cancelled/x", "w").write("{}")
        got = to_peer("r/w", [loop, "r", "w"], f"{d}/tp.log", ent, "x")
        t("to_peer: cancelled while the peer was starting it, the entry and tombstone go and the log says where it runs",
          (got, os.path.exists(ent), os.path.exists(f"{room_dir()}/cancelled/x"),
           "it runs on the peer" in open(f"{d}/tp.log").read()), ("peer", False, False, True))
        _peer_rest[0] = 0.0
        admission.LOADAVG = calm
        os.environ.update(LANDER_LOADAVG=calm, CC_PEER_DIR=f"{base}/nopeer", HOME=keep["HOME"] or HOME)
        os.environ.pop("CC_PEER_SSH", None)

        # admit fails open: a room it cannot even create still runs the launch, and says so once
        d = fixture("crash")
        open(f"{d}/notadir", "w").close()
        os.environ["CC_ROOM_DIR"] = f"{d}/notadir/room"   # under a file: makedirs raises
        mark = f"{d}/ran"
        r = subprocess.run([sys.executable, __file__, "admit", "r/crash", "--log", f"{d}/loop.log", "--",
                            "touch", mark], timeout=20, capture_output=True)
        t("crash: admit that cannot make its room still runs the launch", (r.returncode, os.path.exists(mark)),
          (0, True))
        t("crash: …and its log says admission failed",
          "admission failed for r/crash" in open(f"{d}/loop.log").read(), True)

        # LOST: the brief's "a queued launch is still queued after a simulated restart" — the waiter and its tmux
        # server both die; the entry stays, out of the way, and `resume` puts it back in the same place
        d = fixture("restart", cap=1)
        h = holder("r/held")
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        mark = f"{d}/ran"
        # the launch writes down the lander it would complete through: the tree's override (CC_LAND, #1611), which
        # `cc … --go` put in the waiter's environment and the relaunch must carry, or it falls back to the pin
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/lost", "--log", f"{d}/loop.log", "--",
                              "sh", "-c", 'printf %s "$CC_LAND" > "$1.t" && mv "$1.t" "$1"', "sh", mark],
                             env=dict(os.environ, TMUX=f"{d}/sock,{srv.pid},0", TMUX_PANE="%1",
                                      CC_LAND=f"{d}/landtree"), stderr=subprocess.DEVNULL)
        procs.append(w)
        e = queued("r/lost")
        t("restart: the waiter records the tmux server it waits in, and its socket",
          (read_entry(e).get("server"), read_entry(e).get("socket")) if e else None,
          ([str(srv.pid), starttime(srv.pid)], f"{d}/sock"))
        t("restart: …and asks THAT server for its pane's name, not the default one",
          f"{d}/sock display-message" in lines(f"{d}/sockets"), True)
        for p in (w, srv):   # the restart
            p.kill()
            p.wait()
        t("restart: the entry outlives its waiter and its tmux server", bool(e) and os.path.exists(e), True)
        t("restart: …and holds nobody up while it is down", live("queue"), {})
        t("restart: status calls it lost", "lost    r/lost" in subprocess.run(
            [sys.executable, __file__, "status"], capture_output=True, text=True).stdout, True)
        t("restart: `queued` still names it, since resume starts it again without the seat",
          subprocess.run([sys.executable, __file__, "queued"], capture_output=True, text=True).stdout, "r/lost\n")
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("restart: resume waits while tmux is not back", ("resumed" in r.stdout, os.path.exists(e)), (False, True))
        open(f"{d}/up", "w").close()
        # resume itself runs where CC_LAND names the pin (a timer's environment, or the box's own): only the entry
        # can give the relaunched worker the override
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True,
                           env=dict(os.environ, CC_LAND=f"{d}/pinned"))
        t("restart: once tmux is back, resume relaunches it in a window of its old name",
          "resumed r/lost in main:r/lost" in r.stdout, True)
        socks = lines(f"{d}/sockets")
        t("restart: every tmux call resume makes goes to the socket the waiter was on",
          (bool(socks), all(x.startswith(f"{d}/sock ") for x in socks),
           {x.split()[1] for x in socks} >= {"has-session", "list-windows", "new-window"}), (True, True, True))
        sp = (lines(f"{d}/spawned") or [""])[0]
        t("restart: the saved environment goes on -e, not into the window's command line",
          (f"-e CC_ROOM_DIR={d}/room" in sp, sp.count("CC_ROOM_DIR=")), (True, 1))
        t("restart: relaunched, it is queued again in the same entry", queued("r/lost"), e)
        t("restart: …and has not run while the cap is held", os.path.exists(mark), False)
        subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("restart: a second resume starts nothing more", len(lines(f"{d}/spawned")), 1)
        h.kill()
        h.wait()
        for _ in range(100):
            if os.path.exists(mark):
                break
            time.sleep(0.2)
        t("restart: it runs by itself once the slot is freed", os.path.exists(mark), True)
        t("restart: …and completes through the lander override it was dispatched with, not the pin",
          open(mark).read() if os.path.exists(mark) else None, f"{d}/landtree")

        # PLACING (landing's security read of #1159): the waiter is killed with its tmux server after the peer took
        # the launch and before the hub recorded it. resume must not start it a second time here.
        def placing(name):
            """a busy home whose waiter is killed, with its server, while a peer with room is starting the launch"""
            d = fixture(name)
            hub = f"{d}/hubhome"
            os.makedirs(f"{hub}/.cc/peer")
            os.makedirs(f"{hub}/.cc/state/r/p")
            open(f"{hub}/.cc/peer/dest", "w").write("user@peerbox\n")
            open(f"{hub}/.cc/state/r/p/task.md", "w").write("Goal: a worker.\n")
            ssh = f"{d}/accept-ssh"   # the peer says it has room, then takes the launch and is still answering
            open(ssh, "w").write(f'#!/bin/sh\n[ "$1" = room ] && exit 0\ntouch {d}/accepted\nexec sleep 60\n')
            os.chmod(ssh, 0o755)
            loop = f"{d}/cc-loop"
            open(loop, "w").write(f"#!/bin/sh\ntouch {d}/ran-here\n")
            os.chmod(loop, 0o755)
            srv = subprocess.Popen(["sleep", "60"])
            procs.append(srv)
            w = subprocess.Popen([sys.executable, __file__, "admit", "r/p", "--log", f"{d}/loop.log", "--", loop, "r",
                                  "p"], env=dict(os.environ, TMUX=f"{d}/sock,{srv.pid},0", TMUX_PANE="%1", HOME=hub,
                                                 CC_PEER_DIR=f"{hub}/.cc/peer", CC_PEER_SSH=ssh, LANDER_LOADAVG=hot),
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            procs.append(w)
            e = queued("r/p")
            for _ in range(100):
                if os.path.exists(f"{d}/accepted"):
                    break
                time.sleep(0.1)
            stamped = read_entry(e).get("placing") if e else None
            os.killpg(w.pid, signal.SIGKILL)   # the waiter and the cc-peer it is waiting on
            w.wait()
            srv.kill()
            srv.wait()
            open(f"{d}/up", "w").close()
            os.environ["CC_PEER_DIR"] = f"{hub}/.cc/peer"
            return d, e, hub, stamped

        d, e, hub, stamped = placing("placing")
        t("placing: the entry is stamped before the peer is asked to launch", isinstance(stamped, float), True)
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("placing: resume leaves a launch the peer may be running, and opens no window",
          ("left r/p" in r.stdout, "resumed" in r.stdout, bool(e) and os.path.exists(e), lines(f"{d}/spawned")),
          (True, False, True, []))
        subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("placing: …and its log says so once, however often resume runs",
          open(f"{d}/loop.log").read().count("not relaunched: its waiter died while handing it to the peer"), 1)
        t("placing: status names it as one to check on the peer",
          "lost    r/p — its waiter died while handing it to the peer" in subprocess.run(
              [sys.executable, __file__, "status"], capture_output=True, text=True).stdout, True)
        t("placing: …and it never ran here", os.path.exists(f"{d}/ran-here"), False)
        t("placing: `queued` leaves it out, since nothing starts it until a person checks the peer",
          subprocess.run([sys.executable, __file__, "queued"], capture_output=True, text=True).stdout, "")
        os.environ["CC_PEER_DIR"] = f"{base}/nopeer"

        d, e, hub, stamped = placing("placed")
        os.makedirs(f"{hub}/.cc/peer/placed/r", exist_ok=True)   # cc-peer recorded the start just before it died
        open(f"{hub}/.cc/peer/placed/r/p", "w").write(f"{'a' * 32} peerbox {int(time.time())}\n")
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("placed: a launch the hub recorded on the peer is dropped from the queue, not relaunched",
          ("dropped r/p: it was started on peerbox" in r.stdout, bool(e) and os.path.exists(e), lines(f"{d}/spawned"),
           os.path.exists(f"{d}/ran-here")), (True, False, [], False))
        os.environ["CC_PEER_DIR"] = f"{base}/nopeer"

        d, e, hub, stamped = placing("placed-before")
        os.makedirs(f"{hub}/.cc/peer/placed/r", exist_ok=True)   # an older launch's record says nothing of this one
        open(f"{hub}/.cc/peer/placed/r/p", "w").write(f"{'a' * 32} peerbox {int(stamped or time.time()) - 3600}\n")
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("placed-before: a placed record older than the stamp is not taken for this launch",
          ("left r/p" in r.stdout, bool(e) and os.path.exists(e), lines(f"{d}/spawned")), (True, True, []))
        os.environ["CC_PEER_DIR"] = f"{base}/nopeer"

        # …and the case kept apart from it: a waiter whose tmux server is still up was ended on purpose
        d = fixture("killed", cap=1)
        holder("r/held")
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/killed", "--", "true"],
                             env=dict(os.environ, TMUX=f"{d}/sock,{srv.pid},0"), stderr=subprocess.DEVNULL)
        procs.append(w)
        e = queued("r/killed")
        w.kill()
        w.wait()
        t("killed: a killed waiter whose tmux server is up is out of the queue at once, its entry kept for the grace",
          (bool(e), live("queue"), bool(e) and os.path.exists(e)), (True, {}, True))
        time.sleep(1.2)
        t("killed: …and the entry goes once the grace is over with the server still up",
          (live("queue"), bool(e) and os.path.exists(e)), ({}, False))

        # a restart ends the waiter before its tmux server: a poll in between must not take it for a kill
        d = fixture("shutdown", cap=1)
        os.environ["CC_ROOM_GRACE"] = "60"
        holder("r/held")
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/slowdown", "--", "true"],
                             env=dict(os.environ, TMUX=f"{d}/sock,{srv.pid},0"), stderr=subprocess.DEVNULL)
        procs.append(w)
        e = queued("r/slowdown")
        w.kill()
        w.wait()
        t("shutdown: a poll while the server is still stopping keeps the entry",
          (live("queue"), bool(e) and os.path.exists(e)), ({}, True))
        srv.kill()
        srv.wait()
        t("shutdown: …and once the server is gone it is lost, for resume to start again",
          "lost    r/slowdown" in subprocess.run([sys.executable, __file__, "status"], capture_output=True,
                                                 text=True).stdout, True)

        # a relaunch whose admit never wrote leaves its own window open: the next resume closes it and starts again;
        # and an entry from before the socket was saved talks to the default server (no -S)
        d = fixture("relaunch", cap=1)
        holder("r/held")
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        open(f"{d}/srv", "w").write(str(srv.pid))
        open(f"{d}/up", "w").close()
        open(f"{d}/nospawn", "w").close()
        e = f"{d}/room/queue/1-2"
        json.dump({"pid": 1, "start": "0", "what": "r/stuck", "cmd": ["true"], "server": ["1", "0"],
                   "queued": time.time() - 60}, open(e, "w"))
        r1 = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        x = read_entry(e)
        t("relaunch: resume keeps the window it opened", x.get("opened"), ["@7", str(srv.pid), starttime(srv.pid)])
        x["relaunched"] -= 700   # its admit never wrote; the next tick comes
        json.dump(x, open(e, "w"))
        # the window still holds its waiter, stuck before it wrote (a fake cc-room that only sleeps), in its shell line
        open(f"{d}/windows", "w").write("r/stuck\n")
        open(f"{d}/winids", "w").write("@7\n")
        os.makedirs(f"{d}/fake")
        open(f"{d}/fake/cc-room", "w").write("import time\ntime.sleep(30)\n")
        pane = subprocess.Popen(["sh", "-c", f"{shlex.quote(sys.executable)} {d}/fake/cc-room admit --resume 1-2 "
                                 "r/stuck -- true; exec sh"], stdin=subprocess.DEVNULL)
        procs.append(pane)
        open(f"{d}/panepid", "w").write(str(pane.pid))
        time.sleep(0.5)
        stray(pane.pid)
        r2 = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("relaunch: the next resume closes its own window, still only its stuck waiter, and relaunches",
          ("resumed r/stuck" in r1.stdout, lines(f"{d}/killed"), "resumed r/stuck" in r2.stdout, os.path.exists(e)),
          (True, ["kill-window -t @7"], True, True))
        t("relaunch: an entry with no socket saved uses the default tmux server", lines(f"{d}/sockets"), [])
        t("relaunch: the waiter, its shell line and the idle shell count as the waiter's; nothing else does",
          [waiter_argv(a, "1-2") for a in (["bash"], ["-bash"], ["python3", "/x/cc-room", "admit", "--resume", "1-2"],
                                           ["bash", "-c", "/x/cc-room admit --resume 1-2 r/t -- cc-loop r t; exec bash"],
                                           ["sleep", "30"], ["python3", "/x/cc-room", "admit", "--resume", "1-3"],
                                           ["python3", "/x/cc-loop", "r", "t"], [])],
          [True, True, True, True, False, False, False, False])

        # the lander's input: a relaunched admit fails open and runs the launch. It drops its entry first, so the
        # next resume has nothing to act on: no kill of the running launch, no second one
        d = fixture("failopen", cap=1)
        holder("r/held")
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        open(f"{d}/srv", "w").write(str(srv.pid))
        open(f"{d}/up", "w").close()
        e = f"{d}/room/queue/1-4"
        json.dump({"pid": 1, "start": "0", "what": "r/fo", "cmd": ["sleep", "30"], "server": ["1", "0"],
                   "queued": time.time() - 60, "log": f"{d}/loop.log"}, open(e, "w"))
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True,
                           env=dict(os.environ, CC_ROOM_POLL="bad"))   # wait_for_room raises in the window
        for _ in range(100):
            if not os.path.exists(e) and "admission failed" in "".join(lines(f"{d}/loop.log")):
                break
            time.sleep(0.1)
        time.sleep(0.5)
        if lines(f"{d}/panepid"):
            stray(int(lines(f"{d}/panepid")[0]))
        ran = [proc_argv(x) for x, _ in strays if proc_argv(x) == ["sleep", "30"]]
        t("failopen: a relaunched admit that fails open drops its entry and runs the launch",
          ("resumed r/fo" in r.stdout, os.path.exists(e), bool(ran)), (True, False, True))
        open(f"{d}/windows", "w").write("r/fo\n")
        open(f"{d}/winids", "w").write("@7\n")
        subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("failopen: …and the next resume neither closes its window nor starts it again",
          (lines(f"{d}/killed"), len(lines(f"{d}/spawned"))), ([], 1))
        r = subprocess.run([sys.executable, __file__, "admit", "r/fo2", "--log", f"{d}/loop.log", "--", "true"],
                           env=dict(os.environ, CC_ROOM_POLL="bad"), capture_output=True, timeout=20)
        t("failopen: a fresh admit failing open after it queued runs CMD and leaves no entry at the FIFO's head",
          (r.returncode, sorted(os.listdir(f"{d}/room/queue"))), (0, []))
        r = subprocess.run([sys.executable, __file__, "heavy", "--name", "h", "--", "true"],
                           env=dict(os.environ, CC_ROOM_POLL="bad"), capture_output=True, timeout=20)
        t("failopen: …and so does a heavy run",
          (r.returncode, sorted(os.listdir(f"{d}/room/heavy-queue"))), (0, []))

        # belt and braces: the fail-open could not drop the entry (a full disk), so the entry is still lost and
        # names the window. resume looks first, finds the launch running there, and drops the entry instead
        d = fixture("guard", cap=1)
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        open(f"{d}/up", "w").close()
        os.makedirs(f"{d}/room/queue")
        e = f"{d}/room/queue/1-5"
        json.dump({"pid": 1, "start": "0", "what": "r/guard", "cmd": ["sleep", "30"], "server": ["1", "0"],
                   "queued": time.time() - 60, "log": f"{d}/loop.log", "relaunched": time.time() - 700,
                   "opened": ["@7", str(srv.pid), starttime(srv.pid)]}, open(e, "w"))
        if os.geteuid() != 0:   # root unlinks in a read-only directory: this needs a plain user
            os.chmod(f"{d}/room/queue", 0o500)
            pane = subprocess.Popen(["sh", "-c", f"{shlex.quote(sys.executable)} {shlex.quote(__file__)} admit --resume "
                                     f"1-5 --log {d}/loop.log r/guard -- sleep 30; exec sh"], stdin=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            procs.append(pane)
            for _ in range(100):
                if "could not drop" in "".join(lines(f"{d}/loop.log")):
                    break
                time.sleep(0.1)
            time.sleep(0.5)
            os.chmod(f"{d}/room/queue", 0o700)
            stray(pane.pid)
            t("guard: a fail-open that cannot drop its entry says so and runs the launch",
              (os.path.exists(e), "could not drop" in "".join(lines(f"{d}/loop.log")),
               any(proc_argv(x) == ["sleep", "30"] for x, _ in strays)), (True, True, True))
            open(f"{d}/panepid", "w").write(str(pane.pid))
            open(f"{d}/winids", "w").write("@7\n")
            r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
            t("guard: resume never closes a window its launch runs in, starts no second one, and drops the entry",
              (lines(f"{d}/killed"), lines(f"{d}/spawned"), os.path.exists(e), "already runs in window @7" in r.stdout),
              ([], [], False, True))
        # and a window it cannot read is left alone, with the entry
        json.dump({"pid": 1, "start": "0", "what": "r/unsure", "cmd": ["true"], "server": ["1", "0"],
                   "queued": time.time() - 60, "relaunched": time.time() - 700,
                   "opened": ["@7", str(srv.pid), starttime(srv.pid)]}, open(f"{d}/room/queue/1-6", "w"))
        open(f"{d}/winids", "w").write("@7\n")
        open(f"{d}/panepid", "w").close()   # list-panes answers nothing
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("guard: a window resume cannot read is not closed, and nothing is started or dropped",
          (lines(f"{d}/killed"), lines(f"{d}/spawned"), os.path.exists(f"{d}/room/queue/1-6"),
           "cannot tell what runs" in r.stdout), ([], [], True, True))

        # resume runs its tmux calls outside the room lock: one at a time, and a cancel in between is never undone
        d = fixture("race", cap=1)
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        open(f"{d}/srv", "w").write(str(srv.pid))
        open(f"{d}/up", "w").close()
        open(f"{d}/nospawn", "w").close()
        os.makedirs(f"{d}/room/queue")
        e = f"{d}/room/queue/1-8"
        rec = {"pid": 1, "start": "0", "what": "r/race", "cmd": ["true"], "server": ["1", "0"], "queued": time.time()}
        json.dump(rec, open(e, "w"))
        with open(f"{d}/room/.resume.lock", "w") as one:
            fcntl.flock(one, fcntl.LOCK_EX)
            r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("race: a second resume while one runs starts nothing",
          ("another cc-room resume is running" in r.stdout, lines(f"{d}/spawned")), (True, []))
        open(f"{d}/vanish", "w").close()
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("race: an entry cancelled while its window opened is not written back",
          ("its entry changed meanwhile" in r.stdout, os.path.exists(e)), (True, False))
        json.dump(dict(rec, relaunched=time.time() - 700, opened=["@7", str(srv.pid), starttime(srv.pid)]),
                  open(e, "w"))
        open(f"{d}/winids", "w").write("@7\n")
        os.makedirs(f"{d}/fake")
        open(f"{d}/fake/cc-room", "w").write("import time\ntime.sleep(30)\n")
        pane = subprocess.Popen(["sh", "-c", f"{shlex.quote(sys.executable)} {d}/fake/cc-room admit --resume 1-8 r/race "
                                 "-- true; exec sh"], stdin=subprocess.DEVNULL)
        procs.append(pane)
        open(f"{d}/panepid", "w").write(str(pane.pid))
        time.sleep(0.5)
        stray(pane.pid)
        t("race: (the fixture) the window holds only its waiter", window_state(tmux(), "@7", "1-8"), "waiter")
        json.dump(dict(rec, relaunched=time.time() - 700, opened=["@7", str(srv.pid), starttime(srv.pid)]),
                  open(e, "w"))   # the probe above ran the vanish hook
        n0 = len(lines(f"{d}/spawned"))
        r = subprocess.run([sys.executable, __file__, "resume"], capture_output=True, text=True)
        t("race: a waiter window whose entry was cancelled after it was looked at is not closed",
          (lines(f"{d}/killed"), len(lines(f"{d}/spawned")) - n0, os.path.exists(e)), ([], 0, False))

        # admit --resume of an entry whose waiter is alive (a fresh --go adopted it first) starts nothing
        d = fixture("twice", cap=1)
        os.makedirs(f"{d}/room/queue")
        json.dump({"pid": os.getpid(), "start": starttime(os.getpid()), "what": "r/twice", "cmd": ["true"]},
                  open(f"{d}/room/queue/1-3", "w"))
        mark = f"{d}/ran"
        r = subprocess.run([sys.executable, __file__, "admit", "--resume", "1-3", "--log", f"{d}/loop.log", "r/twice",
                            "--", "touch", mark], capture_output=True, timeout=20)
        t("twice: admit --resume of an entry already waiting starts nothing",
          (r.returncode, os.path.exists(mark), "already waiting" in "".join(lines(f"{d}/loop.log"))), (0, False, True))

        # a fresh `cc … --go` of a track a restart left queued takes over its entry instead of queueing twice
        d = fixture("adopt", cap=1)
        holder("r/held")
        os.makedirs(f"{d}/room/queue", exist_ok=True)
        old = f"{d}/room/queue/1-1"
        json.dump({"pid": 1, "start": "0", "what": "r/again", "cmd": ["true"], "server": ["1", "0"],
                   "queued": time.time() - 60}, open(old, "w"))
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/again", "--", "true"], stderr=subprocess.DEVNULL)
        procs.append(w)
        t("adopt: a new launch of a lost track waits in the lost entry's place", queued("r/again"), old)

        # NOTICE: a wait past the bound tells the seat that dispatched it, once; a wait under it tells nobody
        d = fixture("notice", cap=1)
        os.environ["CC_ROOM_NOTICE_AFTER"] = "1"
        holder("r/held")
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/slow", "--log", f"{d}/loop.log", "--", "true"],
                             env=dict(os.environ, CC_SLACK_ALIAS="comms"), stderr=subprocess.DEVNULL)
        procs.append(w)
        time.sleep(3)
        told = lines(f"{d}/told")
        t("notice: a wait past the bound produces one notice", len(told), 1)
        t("notice: …to the orch that dispatched it, saying why and how to cancel",
          bool(told) and told[0].startswith("inject --no-start --source room r@comms r/slow has waited")
          and "cc-room cancel r/slow" in told[0], True)
        t("notice: …and the loop log says who was told", "told r@comms" in open(f"{d}/loop.log").read(), True)
        d = fixture("scratch")
        notice(f"_cctest{os.getpid()}/t", {"queued": time.time() - 7200, "target": "r@comms"}, "x", f"{d}/loop.log")
        t("notice: a suite's scratch launch (cc-board's FIXTURE prefix) tells nobody, and the log says so",
          (lines(f"{d}/told"), "told nobody (a test namespace)" in open(f"{d}/loop.log").read()), ([], True))
        d = fixture("quiet", cap=1)
        holder("r/held")
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/brief", "--", "true"], stderr=subprocess.DEVNULL)
        procs.append(w)
        time.sleep(1.5)
        t("notice: a wait under the bound tells nobody", (bool(queued("r/brief")), lines(f"{d}/told")), (True, []))

        # a notice nobody took is tried again, with a growing wait, and is not taken for one delivered
        d = fixture("retry", cap=1)
        os.environ.update(CC_ROOM_NOTICE_AFTER="1", CC_ROOM_NOTICE_RETRY="0.3")
        open(f"{d}/down", "w").close()   # the broker and cc-notify both refuse
        holder("r/held")
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/late", "--log", f"{d}/loop.log", "--", "true"],
                             env=dict(os.environ, CC_SLACK_ALIAS="comms"), stderr=subprocess.DEVNULL)
        procs.append(w)
        e = queued("r/late")
        time.sleep(2.5)
        x = read_entry(e) if e else {}
        t("retry: a refused notice is tried again, and the entry does not call it delivered",
          (len(lines(f"{d}/told")) >= 4, "could not tell anyone" in "".join(lines(f"{d}/loop.log")),
           x.get("noticed"), x.get("notice_tries", 0) >= 2), (True, True, False, True))
        os.unlink(f"{d}/down")
        for _ in range(100):
            if "told r@comms" in "".join(lines(f"{d}/loop.log")):
                break
            time.sleep(0.1)
        n1 = len(lines(f"{d}/told"))
        time.sleep(1.5)
        t("retry: once the broker takes it, it is delivered once and tried no more",
          ("told r@comms" in "".join(lines(f"{d}/loop.log")), len(lines(f"{d}/told")) - n1,
           bool(e) and read_entry(e).get("noticed")), (True, 0, True))

        # NOTICE_TRIES refused: said once in the dispatcher's channel (a plain --major notice), not only logged
        d = fixture("unheard")
        open(f"{d}/bin/cc-notify", "w").write(f'#!/bin/sh\necho "notify $*" >> "{d}/told"\n'
                                             f'case " $* " in *" --ask "*) exit 1 ;; esac\n')
        rec = {"queued": time.time() - 7200, "target": "r@comms", "notice_tries": NOTICE_TRIES}
        said = unheard("r/deaf", rec, "the host is busy", f"{d}/loop.log")
        told = lines(f"{d}/told")
        t("unheard: after the last refused try it says so once in the repo's channel, naming how to cancel",
          (said, len(told), bool(told) and "--major --id room-unheard:r/deaf:" in told[0]
           and "cc-room cancel r/deaf" in told[0]), (True, 1, True))
        os.chmod(f"{d}/bin/cc-notify", 0o644)
        t("unheard: a channel that refuses too is logged, and the entry does not call it said",
          (unheard("r/deaf", rec, "x", f"{d}/loop.log"), "could not say in the channel" in open(f"{d}/loop.log").read()),
          (False, True))

        # status's sweep runs under the room lock, and its settling stamp never writes back an entry a cancel removed
        d = fixture("settle", cap=1)
        os.environ["CC_ROOM_GRACE"] = "60"
        srv = subprocess.Popen(["sleep", "60"])
        procs.append(srv)
        os.makedirs(f"{d}/room/queue")
        e = f"{d}/room/queue/1-7"
        stale = {"pid": 1, "start": "0", "what": "r/gone", "cmd": ["true"], "server": [str(srv.pid), starttime(srv.pid)],
                 "queued": time.time()}
        json.dump(stale, open(e, "w"))
        os.unlink(e)   # the cancel, after the sweep had read the entry
        t("settle: a stamp from a stale read does not bring a cancelled entry back",
          (settling(e, dict(stale)), os.path.exists(e)), (False, False))
        json.dump(stale, open(e, "w"))
        with Lock():
            s = subprocess.Popen([sys.executable, __file__, "status"], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            procs.append(s)
            time.sleep(1)
            t("settle: status waits for the room lock before it sweeps",
              (s.poll(), "dead_seen" in read_entry(e)), (None, False))
            os.unlink(e)   # cancel, holding the lock
        s.wait(timeout=30)
        t("settle: …and then finds the cancelled entry gone instead of writing it back", os.path.exists(e), False)

        # a queue entry keeps only what a relaunch needs: never a token from the environment
        d = fixture("env", cap=1)
        holder("r/held")
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/env", "--", "true"], stderr=subprocess.DEVNULL,
                             env=dict(os.environ, CC_SLACK_TOKEN="xoxb-sc-secret", CC_GH_TOKEN="ghp-sc-secret",
                                      LANDER_API_KEY="sc-key", CC_WORKER_MODEL="opus"))
        procs.append(w)
        e = queued("r/env")
        env = (read_entry(e).get("env") or {}) if e else {}
        t("env: no CC_*_TOKEN or key is written into the entry; what the relaunch needs is",
          (sorted(k for k in env if "TOKEN" in k or "KEY" in k), "sc-secret" in (open(e).read() if e else ""),
           env.get("CC_WORKER_MODEL"), env.get("CC_ROOM_DIR")), ([], False, "opus", f"{d}/room"))
        cc = f"{BIN}/cc"
        m = re.search(r"for v in (CC_[A-Z_ ]+); do", open(cc).read()) if os.path.exists(cc) else None
        t("env: every key `cc … --go` carries into a worker's window is one a relaunch carries too",
          sorted(set(m.group(1).split()) - set(RELAUNCH_ENV)) if m else "cc's list not found", [])

        # CANCEL: the dispatching seat drops a queued launch; it exits without running, and nothing is killed
        d = fixture("cancel", cap=1)
        holder("r/held")
        mark = f"{d}/ran"
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/drop", "--log", f"{d}/loop.log", "--",
                              "touch", mark], stderr=subprocess.DEVNULL)
        procs.append(w)
        queued("r/drop")
        r = subprocess.run([sys.executable, __file__, "cancel", "r/drop"], capture_output=True, text=True)
        t("cancel: a queued launch is cancelled", r.returncode, 0)
        t("cancel: …its waiter exits 0 on its own without running it", (w.wait(timeout=10), os.path.exists(mark)),
          (0, False))
        t("cancel: …and its log says so", "r/drop was cancelled" in open(f"{d}/loop.log").read(), True)
        t("cancel: …and its tombstone is gone with it", os.listdir(f"{d}/room/cancelled"), [])
        w = subprocess.Popen([sys.executable, __file__, "admit", "r/keep", "--", "touch", mark],
                             stderr=subprocess.DEVNULL)
        procs.append(w)
        e = queued("r/keep")
        os.unlink(e)   # what a waiter on the older code does to a JSON entry: not a cancel
        t("cancel: an entry gone with no tombstone is written again, not taken for a cancel",
          queued("r/keep"), e)
        t("cancel: nothing queued for it is exit 1",
          subprocess.run([sys.executable, __file__, "cancel", "r/drop"], capture_output=True).returncode, 1)

        # PRIORITY: `bump` moves a queued launch to the head; `now` starts one whatever the room says
        d = fixture("bump", cap=1)
        h = holder("r/held")
        ran_a, ran_b = f"{d}/ran-a", f"{d}/ran-b"
        wa = subprocess.Popen([sys.executable, __file__, "admit", "r/a", "--", "sh", "-c", f"touch {ran_a}; sleep 60"],
                              stderr=subprocess.DEVNULL)
        procs.append(wa)
        queued("r/a")
        wb = subprocess.Popen([sys.executable, __file__, "admit", "r/b", "--log", f"{d}/b.log", "--",
                               "sh", "-c", f"touch {ran_b}; sleep 60"], stderr=subprocess.DEVNULL)
        procs.append(wb)
        eb = queued("r/b")
        t("bump: before it, the queue is oldest first", [live("queue")[p][1] for p in ordered("queue")], ["r/a", "r/b"])
        r = subprocess.run([sys.executable, __file__, "bump", "r/b"], capture_output=True, text=True)
        t("bump: a queued launch is bumped", r.returncode, 0)
        t("bump: …to the head of the queue", [live("queue")[p][1] for p in ordered("queue")], ["r/b", "r/a"])
        time.sleep(0.6)   # a few polls: the waiter reads the stamp back
        os.unlink(eb)     # its waiter writes the entry again from what it holds
        t("bump: …and the waiter's own rewrite keeps the stamp", bool(read_entry(queued("r/b") or eb).get("bumped")), True)
        t("bump: …but it still waits for room", os.path.exists(ran_b), False)
        h.kill()
        h.wait()
        for _ in range(100):
            if os.path.exists(ran_b):
                break
            time.sleep(0.1)
        t("bump: once the slot frees, the bumped launch starts ahead of the older one",
          (os.path.exists(ran_b), os.path.exists(ran_a), wa.poll()), (True, False, None))
        r = subprocess.run([sys.executable, __file__, "now", "r/a"], capture_output=True, text=True)
        t("now: a queued launch is told to start", r.returncode, 0)
        for _ in range(100):
            if os.path.exists(ran_a):
                break
            time.sleep(0.1)
        t("now: …and it starts with the cap still full, taking a slot of its own",
          (os.path.exists(ran_a), sorted(w for _, w in live("slots").values()), live("queue")),
          (True, ["r/a", "r/b"], {}))
        t("bump: nothing queued for it is exit 1",
          subprocess.run([sys.executable, __file__, "bump", "r/none"], capture_output=True).returncode, 1)
        t("now: nothing queued for it is exit 1",
          subprocess.run([sys.executable, __file__, "now", "r/none"], capture_output=True).returncode, 1)
        for w in (wa, wb):
            stray(w.pid)

        # HEAVY: a heavy run waits for a heavy slot, takes no worker slot, and runs in its scope
        d = fixture("heavy", cap=1)
        h = subprocess.Popen([sys.executable, __file__, "heavy", "--name", "anneal-a", "--", "sleep", "60"],
                             stderr=subprocess.DEVNULL)
        procs.append(h)
        for _ in range(50):
            if live("heavy"):
                break
            time.sleep(0.1)
        mark = f"{d}/ran"
        w = subprocess.Popen([sys.executable, __file__, "heavy", "--name", "anneal-b", "--", "touch", mark],
                             stderr=subprocess.DEVNULL)
        procs.append(w)
        time.sleep(1)
        t("heavy: a heavy run waits while the heavy cap is held", os.path.exists(mark), False)
        t("heavy: …and heavy runs take no worker slot", why_not(), "")
        h.kill()
        h.wait()
        w.wait(timeout=20)
        t("heavy: it runs once the heavy slot frees", os.path.exists(mark), True)
        a = heavy_argv("place anneal", ["anneal", "x"], True)
        t("heavy: scoped, it runs directly in app.slice, beside the sessions' scopes, with its CPU weight",
          (a[:3], "--slice=app.slice" in a, "CPUWeight=1000" in a, a[-3:]),
          (["systemd-run", "--user", "--scope"], True, True, ["--", "anneal", "x"]))
        # CC_HEAVY_SCOPE unset: the lander's scope_available() decides, here against a stubbed systemd-run and bus
        d = fixture("scope")
        os.makedirs(f"{d}/rt")
        open(f"{d}/rt/bus", "w").close()
        open(f"{d}/bin/systemd-run", "w").write(f'#!/bin/sh\necho "$*" > "{d}/scoped"\n'
                                                'while [ "$1" != -- ]; do shift; done; shift; exec "$@"\n')
        os.chmod(f"{d}/bin/systemd-run", 0o755)
        env = {k: v for k, v in os.environ.items() if k not in ("CC_HEAVY_SCOPE", "LANDER_SCOPE")}
        env.update(PATH=f"{d}/bin:{os.environ.get('PATH', '')}", XDG_RUNTIME_DIR=f"{d}/rt")
        mark = f"{d}/ran"
        r = subprocess.run([sys.executable, __file__, "heavy", "--name", "anneal-s", "--", "touch", mark], env=env,
                           capture_output=True, text=True, timeout=20)
        t("heavy: with no CC_HEAVY_SCOPE and a user bus it runs CMD through systemd-run in app.slice",
          (r.returncode, os.path.exists(mark), "--slice=app.slice" in " ".join(lines(f"{d}/scoped")),
           "admission failed" in r.stderr), (0, True, True, False))
        t("heavy: unscoped, it runs CMD as it is", heavy_argv("x", ["anneal"], False), ["anneal"])
    finally:
        admission.LOADAVG = old_loadavg
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait()
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for pid, st in strays:   # what the stub windows ran, while it is still that process
            if st and starttime(pid) == st:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
        shutil.rmtree(base, ignore_errors=True)
    print(f"cc-room selfcheck: {n - bad} passed, {bad} failed")
    return 1 if bad else 0
