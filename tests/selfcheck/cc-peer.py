# cc-peer's selfcheck: the cases behind `cc-peer selfcheck`. Not a module: cc-peer execs this file INSIDE ITS OWN
# NAMESPACE and calls the selfcheck() it defines, so every name here is the tool's and a `global` rebinds the tool's.
# No module docstring (it would replace the tool's __doc__) and no top-level name but the def below.
# recurring-defect-ok: pause-hold-missing — selfcheck fixtures: every launch and board write here runs against a fake peer in a temp tree, never a real project
# recurring-defect-ok: held-files-unchecked — selfcheck fixtures: the replayed launches are fake rows in a temp tree, so no live track holds their files
#
# Two fake hosts, each a home of its own under one temp dir: the hub, which runs this process, and the peer, reached
# through a fake ssh (CC_PEER_SSH) that runs `cc-peer serve` there with SSH_ORIGINAL_COMMAND set, as sshd runs the
# key's forced command. Neither touches the real ~/.cc, Slack, a board or a lander: the peer's cc is a script that
# records its argv, and on the hub run_here (every call drain makes on this host) is rebound to record its own.

def selfcheck():
    import shutil
    import tempfile
    global run_here, land, call
    n = bad = 0

    def t(name, got, want):
        nonlocal n, bad
        n += 1
        if got != want:
            bad += 1
            print(f"FAIL {name}: got {got!r}, want {want!r}")

    base = tempfile.mkdtemp(prefix="cc-peer-sc.")
    keep = {k: os.environ.get(k) for k in ("HOME", "CC_PEER_DIR", "CC_PEER_SSH", "CC_PEER_SPOOL")}
    real_run_here, real_land = run_here, land
    me = os.path.join(BIN, "cc-peer")

    def fake_host(name):
        """a peer home with a clone of r, a cc that records what it is asked and a board that says no row yet"""
        h = f"{base}/{name}"
        os.makedirs(f"{h}/bin")
        os.makedirs(f"{h}/dev/r/.git")
        for tool, body in (("cc", f'printf "%s\\n" "$*" >>{h}/cc.argv\nexit 0'), ("cc-room", "exit 0"),
                           ("cc-board", f'printf "%s\\n" "$*" >>{h}/board.argv\nexit 1')):
            with open(f"{h}/bin/{tool}", "w") as f:
                f.write(f"#!/bin/sh\n{body}\n")
            os.chmod(f"{h}/bin/{tool}", 0o755)
        ssh = f"{h}/fake-ssh"
        with open(ssh, "w") as f:
            f.write(f'#!/bin/sh\nexec env -i PATH="$PATH" HOME={h} CC_PEER_CC={h}/bin/cc SSH_ORIGINAL_COMMAND="$*" '
                    f'{sys.executable} {me} serve\n')
        os.chmod(ssh, 0o755)
        return h, ssh

    def serve_as(h, words, stdin=b""):
        env = {"PATH": os.environ.get("PATH", ""), "HOME": h, "CC_PEER_CC": f"{h}/bin/cc",
               "SSH_ORIGINAL_COMMAND": words}
        p = subprocess.run([sys.executable, me, "serve"], input=stdin, capture_output=True, env=env, timeout=60)
        return p.returncode, p.stdout.decode() + p.stderr.decode()

    def lines(p):
        return open(p).read().splitlines() if os.path.exists(p) else []

    def put(h, e, name=None):
        """one spooled entry on the peer h, as `cc-peer spool` writes it"""
        d = f"{h}/.cc/peer/spool"
        os.makedirs(d, exist_ok=True)
        name = name or f"{time.time_ns():019d}-1-{uuid.uuid4().hex[:8]}.json"
        with open(f"{d}/{name}", "w") as f:
            json.dump(e, f)
        return name

    try:
        # A REPLAYED LAUNCH ID IS REFUSED: the same id twice runs cc once
        peer, ssh = fake_host("replay")
        lid = uuid.uuid4().hex
        rc1, _ = serve_as(peer, f"launch {lid} r w --base main --loop 2", b"Goal: one worker.\n")
        rc2, out2 = serve_as(peer, f"launch {lid} r w --base main --loop 2", b"Goal: one worker.\n")
        t("replay: the first launch runs", rc1, 0)
        t("replay: the same id again is refused with 3", (rc2, "already run here" in out2), (3, True))
        t("replay: …and cc ran once", sum(1 for x in lines(f"{peer}/cc.argv") if "--go" in x), 1)
        rc3, _ = serve_as(peer, f"launch {uuid.uuid4().hex} r w2", b"Goal: another.\n")
        t("replay: a fresh id still runs", (rc3, sum(1 for x in lines(f"{peer}/cc.argv") if "--go" in x)), (0, 2))
        t("replay: the shadow row was made, the board here having none",
          any(x.startswith("add r w ") for x in lines(f"{peer}/board.argv")), True)

        # THE FIXED VERB LIST: anything else is refused before it runs a thing
        for words, why in ((f"launch NOTANID r w", "an id that is not 32 hex"),
                           (f"launch {uuid.uuid4().hex} ../x w", "a repo with a path in it"),
                           (f"launch {uuid.uuid4().hex} r w --exec sh", "a flag off the list"),
                           (f"launch {uuid.uuid4().hex} nope w", "a repo with no clone here"),
                           ("sh -c id", "a verb off the list"), ("", "nothing at all")):
            rc, _ = serve_as(peer, words, b"Goal.\n")
            t(f"verbs: {why} is refused", rc, 2)
        t("verbs: none of those ran cc", sum(1 for x in lines(f"{peer}/cc.argv") if "--go" in x), 2)

        # THE HOST COMES FROM THE CONNECTION: drain stamps the name in the hub's own config, whatever an entry says
        peer, ssh = fake_host("drain")
        hub = f"{base}/hub"
        os.makedirs(f"{hub}/.cc/peer/placed/r")
        os.makedirs(f"{hub}/.cc/state/r/w")
        open(f"{hub}/.cc/peer/dest", "w").write("user@peerbox\n")
        open(f"{hub}/.cc/peer/placed/r/w", "w").write(f"{uuid.uuid4().hex} peerbox 1\n")
        os.environ.update(HOME=hub, CC_PEER_DIR=f"{hub}/.cc/peer", CC_PEER_SSH=ssh)
        ran = []

        def record(argv, env=None):
            ran.append((list(argv), dict(env or {})))
            if argv[:1] == ["git"] and "rev-parse" in argv:
                return 0, tip[0]
            return 0, ""
        run_here = record
        tip = ["0" * 40]
        e1 = put(peer, {"tool": "board", "argv": ["note", "r", "w", "half way"], "host": "otherbox", "t": 1})
        put(peer, {"tool": "board", "argv": ["note", "r", "x", "not mine"], "t": 1})
        put(peer, {"tool": "board", "argv": ["set", "r", "w", "agent", "me"], "t": 1})
        put(peer, {"tool": "notify", "repo": "r", "track": "w", "host": "otherbox", "t": 1,
                   "argv": ["--approval", "--run", "rm -rf ~", "-t", "r/w blocked", "--id", "cf-perm:t@20261020T000000Z",
                            "--", "--please"]})
        put(peer, {"tool": "shell", "argv": ["id"], "t": 1})
        drain()
        boards = [a for a, _ in ran if a[0].endswith("/cc-board")]
        t("host: a note runs on the hub with the connection's name, not the entry's",
          boards, [[f"{BIN}/cc-board", "note", "r", "w", "[peerbox] half way"]])
        t("host: no call carries the name the entry claimed", any("otherbox" in " ".join(a) for a, _ in ran), False)
        t("host: a track never placed on this peer is not touched", any("x" in a[3:4] for a in boards), False)
        notes = [(a, env) for a, env in ran if a[0].endswith("/cc-notify")]
        t("notify: it runs once, as a worker", [env.get("CC_ROLE") for _, env in notes], ["worker"])
        na = notes[0][0] if notes else []
        t("notify: an owner door becomes --ask and --run never passes",
          ("--ask" in na, "--approval" in na, "--run" in na, any("rm -rf" in x for x in na)), (True, False, False, False))
        t("notify: the title says which host, and the message after -- is kept whole",
          ("r/w blocked (peerbox)" in na, na[-1:]), (True, ["--please"]))
        t("notify: a peer's --id never names a live ask (<subject>@<stamp>), so it cannot retire one of the hub's",
          na[na.index("--id") + 1:na.index("--id") + 2] if "--id" in na else None, ["cf-perm:t_20261020T000000Z"])
        t("drain: what it could not run is still taken off the peer", os.listdir(f"{peer}/.cc/peer/spool/taken"), [])
        t("drain: it logs the dropped ones",
          sum(1 for x in lines(f"{hub}/.cc/peer/drain.log") if "dropped" in x), 3)
        ran.clear()
        put(peer, {"tool": "board", "argv": ["note", "r", "w", "again"], "t": 1}, name=e1)   # an ack that was lost
        drain()
        t("drain: an entry already drained is never run twice", ran, [])

        # A DONE WAITS FOR ITS COMMIT ON ORIGIN, then lands through the hub's own command
        sha = "a" * 40
        put(peer, {"tool": "land", "argv": ["r", "w"], "sha": sha, "pr_body": "What changed.\n", "t": int(time.time())})
        drain()
        t("land: a tip origin does not have yet lands nothing", [a for a, _ in ran if "queue" in a], [])
        t("land: …and the entry stays with the peer for the next drain",
          len(os.listdir(f"{peer}/.cc/peer/spool/taken")), 1)
        tip[0] = sha
        drain()
        t("land: with the tip on origin the hub queues it",
          [a[1:] for a, _ in ran if "queue" in a], [["queue", "--task", "r", "w"]])
        t("land: the peer's pr-body.md is beside the hub's task", open(f"{hub}/.cc/state/r/w/pr-body.md").read(),
          "What changed.\n")
        t("land: …and the peer's spool is empty", os.listdir(f"{peer}/.cc/peer/spool/taken"), [])
        # A DONE STILL NOT ON ORIGIN A DAY ON IS KEPT (owner 2026-10-20: back off and post once, never drop)
        sha2 = "b" * 40
        ran.clear()
        put(peer, {"tool": "land", "argv": ["r", "w"], "sha": sha2, "t": int(time.time()) - 2 * RETRY_FOR})
        drain()
        notes = [a for a, _ in ran if a[0].endswith("cc-notify")]
        t("late: a day-old DONE whose tip is not on origin stays with the peer",
          len(os.listdir(f"{peer}/.cc/peer/spool/taken")), 1)
        t("late: …and posts one line saying so", (len(notes), any("peer-late:" in x for x in (notes or [[]])[0])),
          (1, True))
        ran.clear()
        drain()
        t("late: the next drain inside the hour neither asks origin again nor posts again", ran, [])
        late = f"{hub}/.cc/peer/late/" + os.listdir(f"{hub}/.cc/peer/late")[0]
        os.utime(late, (time.time() - RETRY_EVERY - 1,) * 2)
        drain()
        t("late: an hour on it asks origin again, and still says nothing more",
          (any("fetch" in a for a, _ in ran), [a for a, _ in ran if a[0].endswith("cc-notify")]), (True, []))
        tip[0] = sha2
        ran.clear()
        os.utime(late, (time.time() - RETRY_EVERY - 1,) * 2)
        drain()
        t("late: once its tip reaches origin it lands, and the mark goes",
          ([a[1:] for a, _ in ran if "queue" in a], os.listdir(f"{hub}/.cc/peer/late")),
          ([["queue", "--task", "r", "w"]], []))
        # …AND ITS LINE CARRIES NO SLACK MARKUP (perms' read of #1618): git's answer is the remote's to write, so a
        # planted <!channel> or <url|text> link in it reaches the channel as plain words, never a page or a link
        planted = "remote: <!channel> <@U0OWNER> see <https://evil.example/x|the fix>"
        def planting(argv, env=None):
            ran.append((list(argv), dict(env or {})))
            return (1, planted) if "fetch" in argv else (0, "")
        run_here = planting
        ran.clear()
        put(peer, {"tool": "land", "argv": ["r", "w"], "sha": "c" * 40, "t": int(time.time()) - 2 * RETRY_FOR})
        drain()
        line = ([a[-1] for a, _ in ran if a[0].endswith("cc-notify")] or [""])[0]
        t("late: the line has no <…> markup left, and still says what git said",
          ("<" in line or ">" in line, "‹!channel›" in line, "‹https://evil.example/x|the fix›" in line), (False, True, True))
        run_here = record
        shutil.rmtree(f"{hub}/.cc/peer/late")
        for f in os.listdir(f"{peer}/.cc/peer/spool/taken"):
            os.unlink(f"{peer}/.cc/peer/spool/taken/{f}")
        tip[0] = sha                               # the cases below land the first tip
        # A LINK THE WORKER PLANTED IN ITS STATE DIR IS NEVER WRITTEN THROUGH (security read of #1159): the old fixed
        # temp name pointed at a hub tool, and a state dir that is itself a link, are both left alone
        victim = f"{base}/victim"
        open(victim, "w").write("original\n")
        os.symlink(victim, f"{hub}/.cc/state/r/w/pr-body.md.tmp")
        rc, _ = land("r", "w", sha, "echo PWNED\n", "peerbox")
        t("link: a planted pr-body.md.tmp link is not followed", open(victim).read(), "original\n")
        t("link: …and the body still lands as a plain pr-body.md",
          (rc, os.path.islink(f"{hub}/.cc/state/r/w/pr-body.md"), open(f"{hub}/.cc/state/r/w/pr-body.md").read()),
          (0, False, "echo PWNED\n"))
        t("link: …readable as the old plain write left it, not mkstemp's 0600",
          oct(os.stat(f"{hub}/.cc/state/r/w/pr-body.md").st_mode & 0o777), oct(0o644))
        os.makedirs(f"{base}/elsewhere")
        os.symlink(f"{base}/elsewhere", f"{hub}/.cc/state/r/wl")
        ran.clear()
        rc, why = land("r", "wl", sha, "body\n", "peerbox")
        t("link: a state dir that is a link is refused, nothing written and nothing queued",
          (rc, "link" in why, os.listdir(f"{base}/elsewhere"), [a for a, _ in ran if "queue" in a]), (1, True, [], []))
        os.makedirs(f"{base}/elsewhere2/w")   # the repo's dir a link, the track's a real dir under it
        os.symlink(f"{base}/elsewhere2", f"{hub}/.cc/state/rl")
        ran.clear()
        rc, why = land("rl", "w", sha, "body\n", "peerbox")
        t("link: …so is a repo state dir that is a link, though the track dir under it is real",
          (rc, os.listdir(f"{base}/elsewhere2/w"), [a for a, _ in ran if "queue" in a]), (1, [], []))
        put(peer, {"tool": "land", "argv": ["r", "z"], "sha": sha, "t": int(time.time())})
        ran.clear()
        drain()
        t("land: a track not placed on this peer is never queued", [a for a, _ in ran if "queue" in a], [])

        # ONE BAD ENTRY NEVER JAMS THE DRAIN (re-read of #1159): a directory the worker left named pr-body.md made land()
        # raise, the drain died before any ack, and every later drain took the same entry first and died again
        for tr in ("j1", "j2"):
            open(f"{hub}/.cc/peer/placed/r/{tr}", "w").write(f"{uuid.uuid4().hex} peerbox 1\n")
            os.makedirs(f"{hub}/.cc/state/r/{tr}")
        os.makedirs(f"{hub}/.cc/state/r/j1/pr-body.md")
        put(peer, {"tool": "land", "argv": ["r", "j1"], "sha": sha, "pr_body": "one\n", "t": int(time.time())})
        put(peer, {"tool": "land", "argv": ["r", "j2"], "sha": sha, "pr_body": "two\n", "t": int(time.time())})
        ran.clear()
        try:
            drain()
            raised = None
        except Exception as x:   # noqa: BLE001
            raised = type(x).__name__
        t("jam: a pr-body.md that is a directory does not stop the drain, and the next track's DONE still queues",
          (raised, [a[3:] for a, _ in ran if "queue" in a]), (None, [["r", "j2"]]))
        t("jam: …the bad entry is dropped with its line and acked, so it never comes back",
          (os.listdir(f"{peer}/.cc/peer/spool/taken"), any("pr-body.md not written" in x for x in lines(f"{hub}/.cc/peer/drain.log"))),
          ([], True))

        def boom(*a, **k):
            raise RuntimeError("an entry that raises")
        land = boom
        put(peer, {"tool": "land", "argv": ["r", "j1"], "sha": sha, "t": int(time.time())})
        put(peer, {"tool": "board", "argv": ["note", "r", "j2", "after it"], "t": 1})
        ran.clear()
        try:
            drain()
            raised = None
        except Exception as x:   # noqa: BLE001
            raised = type(x).__name__
        land = real_land
        t("jam: any entry that raises is dropped and the rest still run",
          (raised, [a[-1] for a, _ in ran if a[0].endswith("/cc-board")], os.listdir(f"{peer}/.cc/peer/spool/taken")),
          (None, ["[peerbox] after it"], []))

        # AN ENTRY'S t IS AN INT IN 0..2**40 OR IT IS DROPPED (round-3 security read of #1159): a 4000-digit t raised
        # OverflowError after the entry ran and before its marker or ack, so every drain ran the batch again
        for bad_t in (int("9" * 4000), -1, 2 ** 40 + 1, "1", 1.5, True, None):
            put(peer, {"tool": "board", "argv": ["note", "r", "j2", f"t {type(bad_t).__name__}"], "t": bad_t})
        ran.clear()
        raised = []
        for _ in range(3):
            try:
                drain()
            except Exception as x:   # noqa: BLE001
                raised.append(type(x).__name__)
        t("t: an entry whose t is not a time never raises out of the drain, however often it runs", raised, [])
        t("t: …it never runs, and each is dropped with its line and acked",
          ([a for a, _ in ran if a[0].endswith("/cc-board")], os.listdir(f"{peer}/.cc/peer/spool/taken"),
           sum(1 for x in lines(f"{hub}/.cc/peer/drain.log") if "its t is not a time" in x)), ([], [], 7))
        put(peer, {"tool": "board", "argv": ["note", "r", "j2", "edge"], "t": 2 ** 40})
        ran.clear()
        drain()
        t("t: 2**40 itself is still a time", [a[-1] for a, _ in ran if a[0].endswith("/cc-board")], ["[peerbox] edge"])

        # THE WRITER: `cc-peer spool` on the peer, as cc-board and cc-notify call it
        peer, ssh = fake_host("writer")
        env = dict(os.environ, HOME=peer, CC_PEER_SPOOL=f"{peer}/.cc/peer/spool")
        subprocess.run([sys.executable, me, "spool", "board", "note", "r", "w", "hello"], env=env, check=True)
        got = [json.load(open(f"{peer}/.cc/peer/spool/{x}")) for x in os.listdir(f"{peer}/.cc/peer/spool")]
        t("spool: one entry with the tool and the argv as given",
          [(g["tool"], g["argv"]) for g in got], [("board", ["note", "r", "w", "hello"])])
        t("spool: it names no host", any("host" in g for g in got), False)
        # A DONE CARRIES pr-body.md ONLY AS A PLAIN FILE (security read of #1159): a link the worker made would have
        # published whatever it points at as the PR body
        open(f"{base}/secret", "w").write("TOKEN\n")
        for tr, plant in (("wp", None), ("wl", "link")):
            os.makedirs(f"{peer}/.cc/state/r/{tr}")
            if plant:
                os.symlink(f"{base}/secret", f"{peer}/.cc/state/r/{tr}/pr-body.md")
            else:
                open(f"{peer}/.cc/state/r/{tr}/pr-body.md", "w").write("What changed.\n")
            subprocess.run([sys.executable, me, "spool", "land", "r", tr], env=env, capture_output=True, timeout=60)
        got = {g["argv"][1]: g.get("pr_body") for g in
               (json.load(open(f"{peer}/.cc/peer/spool/{x}")) for x in os.listdir(f"{peer}/.cc/peer/spool"))
               if g["tool"] == "land"}
        t("spool: a plain pr-body.md rides along with the DONE", got.get("wp"), "What changed.\n")
        t("spool: a pr-body.md that is a link is not read", got.get("wl"), None)

        # AN ENTRY IS AT MOST ENTRY_CAP AS WRITTEN (round-3 security read of #1159): a 64 KB pr-body.md of invalid UTF-8
        # was 393 KB once json.dump escaped it, and spool-take skipped it with no line and no ack, so the DONE was lost
        # and the entry held a take slot for good
        peer, ssh = fake_host("big")
        sp = f"{peer}/.cc/peer/spool"
        env = dict(os.environ, HOME=peer, CC_PEER_SPOOL=sp)
        for tr, body in (("bff", b"\xff" * (ENTRY_CAP // 2)), ("bemoji", "\U0001F600".encode() * (ENTRY_CAP // 8)),
                         ("bctl", b"\x01" * (ENTRY_CAP // 2))):
            os.makedirs(f"{peer}/.cc/state/r/{tr}")
            open(f"{peer}/.cc/state/r/{tr}/pr-body.md", "wb").write(body)
            subprocess.run([sys.executable, me, "spool", "land", "r", tr], env=env, capture_output=True, timeout=60)
        sizes = {json.load(open(f"{sp}/{x}"))["argv"][1]: os.path.getsize(f"{sp}/{x}") for x in os.listdir(sp)}
        t("big: each DONE is written within the entry cap", {k: v <= ENTRY_CAP for k, v in sizes.items()},
          {"bff": True, "bemoji": True, "bctl": True})
        rc, out = serve_as(peer, "spool-take")
        offered = {json.loads(x.split(" ", 1)[1])["argv"][1]: json.loads(x.split(" ", 1)[1]).get("pr_body", "")
                   for x in out.splitlines() if ENTRY_RE.fullmatch(x.split(" ", 1)[0])}
        t("big: …and spool-take offers all three", sorted(offered), ["bctl", "bemoji", "bff"])
        t("big: an emoji body fits whole once it is written as UTF-8, not \\u-escaped",
          offered.get("bemoji") == "\U0001F600" * (ENTRY_CAP // 8), True)
        t("big: a body that cannot fit is cut, never dropped",
          (0 < len(offered.get("bff", "")) < ENTRY_CAP // 2, set(offered.get("bff", "x")),
           0 < len(offered.get("bctl", "")) < ENTRY_CAP // 2), (True, {"\ufffd"}, True))
        serve_as(peer, "spool-ack " + " ".join(os.listdir(f"{sp}/taken")))
        rc = subprocess.run([sys.executable, me, "spool", "board", "note", "r", "w"] + ["x" * (ENTRY_CAP // 3)] * 4, env=env,
                            capture_output=True, timeout=60)
        t("big: a note too big for any entry is refused with its line, and nothing is written",
          (rc.returncode, "refused" in rc.stderr.decode(), [x for x in os.listdir(sp) if ENTRY_RE.fullmatch(x)]),
          (1, True, []))
        subprocess.run([sys.executable, me, "spool", "board", "note", "r", "w", b"not \xff utf-8"], env=env, check=True)
        rc, out = serve_as(peer, "spool-take")
        t("big: an argv byte that is not UTF-8 still makes an entry the peer offers",
          [json.loads(x.split(" ", 1)[1])["argv"][-1] for x in out.splitlines() if ENTRY_RE.fullmatch(x.split(" ", 1)[0])],
          ["not \udcff utf-8"])
        serve_as(peer, "spool-ack " + " ".join(os.listdir(f"{sp}/taken")))
        # what spool-take cannot offer goes aside with its line, so it never holds a TAKE_MAX slot
        over = f"{time.time_ns():019d}-5-{uuid.uuid4().hex[:8]}.json"
        arr = f"{time.time_ns():019d}-6-{uuid.uuid4().hex[:8]}.json"
        open(f"{sp}/taken/{over}", "w").write(json.dumps({"tool": "board", "argv": ["x" * ENTRY_CAP], "t": 1}))
        open(f"{sp}/taken/{arr}", "w").write("[1, 2]")
        good = put(peer, {"tool": "board", "argv": ["note", "r", "w", "kept"], "t": 1})
        rc, out = serve_as(peer, "spool-take")
        t("aside: an oversized entry and one that is not an object go aside, logged, and the good one is offered",
          (rc, [x.split(" ", 1)[0] for x in out.splitlines() if ENTRY_RE.fullmatch(x.split(" ", 1)[0])],
           sorted(os.listdir(f"{sp}/aside")), sorted(os.listdir(f"{sp}/taken")),
           sum(1 for x in lines(f"{sp}/aside.log") if over in x or arr in x)),
          (0, [good], sorted([over, arr]), [good], 2))

        # BOTH MOVES OF A TAKE ARE GUARDED AND aside/ IS NEVER FOLLOWED (round-4 security read of #1159): a file at
        # spool/aside made aside() raise inside its own except, a dir at taken/<n> broke the first move, and either
        # made every take exit 1; an aside/<n> that collided left its entry in taken/, holding a slot
        def entry(d, body):
            nm = f"{time.time_ns():019d}-7-{uuid.uuid4().hex[:8]}.json"
            open(f"{d}/{nm}", "w").write(body)
            return nm

        def offered(out):
            return [x.split(" ", 1)[0] for x in out.splitlines() if ENTRY_RE.fullmatch(x.split(" ", 1)[0])]

        good_e = json.dumps({"tool": "board", "argv": ["note", "r", "w", "kept"], "t": 1})
        peer, ssh = fake_host("aside-file")
        sp = f"{peer}/.cc/peer/spool"
        os.makedirs(f"{sp}/taken")
        open(f"{sp}/aside", "w").write("x")
        mis, good = entry(f"{sp}/taken", "[1]"), entry(f"{sp}/taken", good_e)
        rc, out = serve_as(peer, "spool-take")
        t("aside-file: a file at spool/aside: take answers 0, offers the good one, and the misfit leaves taken/ logged",
          (rc, offered(out), mis in os.listdir(f"{sp}/taken"), any(mis in x and "removed" in x for x in lines(f"{sp}/aside.log"))),
          (0, [good], False, True))
        peer, ssh = fake_host("aside-link")
        sp = f"{peer}/.cc/peer/spool"
        os.makedirs(f"{sp}/taken")
        os.makedirs(f"{base}/aside-target")
        os.symlink(f"{base}/aside-target", f"{sp}/aside")
        mis = entry(f"{sp}/taken", "[1]")
        rc, out = serve_as(peer, "spool-take")
        t("aside-link: aside/ as a link is not followed: nothing lands in its target, and the misfit leaves taken/",
          (rc, os.listdir(f"{base}/aside-target"), mis in os.listdir(f"{sp}/taken")), (0, [], False))
        peer, ssh = fake_host("aside-collide")
        sp = f"{peer}/.cc/peer/spool"
        os.makedirs(f"{sp}/taken")
        mis = entry(f"{sp}/taken", "[1]")
        os.makedirs(f"{sp}/aside/{mis}/x")
        rc, out = serve_as(peer, "spool-take")
        rc2, out2 = serve_as(peer, "spool-take")
        t("aside-collide: an aside/<n> that is a dir: the misfit leaves taken/ once, with one line, and holds no slot",
          (rc, rc2, mis in os.listdir(f"{sp}/taken"), sum(1 for x in lines(f"{sp}/aside.log") if mis in x),
           os.path.isdir(f"{sp}/aside/{mis}/x")), (0, 0, False, 1, True))
        peer, ssh = fake_host("first-move")
        sp = f"{peer}/.cc/peer/spool"
        os.makedirs(f"{sp}/taken")
        mis = entry(sp, "{}")
        os.makedirs(f"{sp}/taken/{mis}/x")
        good = entry(sp, good_e)
        rc, out = serve_as(peer, "spool-take")
        t("first-move: spool/<n> onto a dir at taken/<n>: take answers 0 and offers the good one, and neither stays",
          (rc, offered(out), mis in os.listdir(sp), mis in os.listdir(f"{sp}/taken")), (0, [good], False, False))

        # SPOOL-TAKE READS REGULAR FILES ONLY (security read of #1159): a FIFO with an entry's name used to hang it
        # until the hub's 120 s timeout, every drain; a link with one is not read through either
        peer, ssh = fake_host("take")
        good = put(peer, {"tool": "board", "argv": ["note", "r", "w", "kept"], "t": 1})
        tk = f"{peer}/.cc/peer/spool/taken"
        os.makedirs(tk)
        fifo = f"{time.time_ns():019d}-2-{uuid.uuid4().hex[:8]}.json"
        os.mkfifo(f"{tk}/{fifo}")
        open(f"{base}/outside.json", "w").write('{"tool": "board", "argv": ["note", "r", "w", "via a link"]}')
        os.symlink(f"{base}/outside.json", f"{tk}/{time.time_ns():019d}-3-{uuid.uuid4().hex[:8]}.json")
        try:
            p = subprocess.run([sys.executable, me, "serve"], capture_output=True, timeout=10,
                               env={"PATH": os.environ.get("PATH", ""), "HOME": peer, "SSH_ORIGINAL_COMMAND": "spool-take"})
            rc, out = p.returncode, p.stdout.decode()
        except subprocess.TimeoutExpired:
            rc, out = "hung", ""
        t("take: a FIFO in taken/ does not hang spool-take", rc, 0)
        t("take: …the regular entry is offered and neither the FIFO nor the link is",
          [x.split(" ", 1)[0] for x in out.splitlines()], [good])

        # A DEEPLY NESTED ENTRY IS MOVED ASIDE, NOT A STOP (round-3 security read of #1159): json.loads raised
        # RecursionError, which the catch missed, so one such file in taken/ made every spool-take exit 1
        peer, ssh = fake_host("deep")
        good = put(peer, {"tool": "board", "argv": ["note", "r", "w", "kept"], "t": 1})
        tk = f"{peer}/.cc/peer/spool/taken"
        os.makedirs(tk)
        deep = f"0{time.time_ns() % 10 ** 18:018d}-4-{uuid.uuid4().hex[:8]}.json"   # sorts first
        open(f"{tk}/{deep}", "w").write("[" * 60000 + "]" * 60000)
        rc, out = serve_as(peer, "spool-take")
        t("deep: spool-take still answers 0 and offers the good entry",
          (rc, [x.split(" ", 1)[0] for x in out.splitlines() if ENTRY_RE.fullmatch(x.split(" ", 1)[0])]),
          (0, [good]))
        t("deep: …the nested one is in aside/ with its line, out of taken/",
          (os.path.exists(f"{peer}/.cc/peer/spool/aside/{deep}"), deep in os.listdir(tk),
           any(deep in x and "RecursionError" in x for x in lines(f"{peer}/.cc/peer/spool/aside.log"))),
          (True, False, True))
        # the hub's own parse of a line: nesting the peer's stack parsed may be past the hub's, so it is caught too
        real_call = call
        call = lambda words, stdin=b"", timeout=60: (0, f"{deep} " + "[" * 60000 + "]" * 60000 + "\n", "")
        try:
            raised = None
            drain()
        except Exception as x:   # noqa: BLE001
            raised = type(x).__name__
        finally:
            call = real_call
        t("deep: a nested line from the peer does not raise out of the hub's drain", raised, None)
    finally:
        run_here, land = real_run_here, real_land
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(base, ignore_errors=True)
    print(f"cc-peer selfcheck: {n - bad} passed, {bad} failed")
    return 1 if bad else 0
