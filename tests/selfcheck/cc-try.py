# cc-try's selfcheck: the cases behind `cc-try selfcheck`. Not a module: cc-try execs this file INSIDE ITS OWN
# NAMESPACE and calls the selfcheck() it defines, so `__file__` is the tool and guard_of() is the tool's. No module
# docstring (it would replace the tool's __doc__) and no top-level name but the def below. Every case builds its own
# fixture — a HOME, a live checkout with an origin, the PR's head on the origin's refs/pull/N/head, a board, a
# cc-green verdict and gh/systemctl stubs — and runs the tool as a process inside it. Nothing reaches GitHub,
# systemd or this box's own ~/.cc.

def selfcheck():
    import shutil, tempfile
    fails = passes = 0
    def ok(what, cond):
        nonlocal fails, passes
        print(("  ok   " if cond else "  FAIL ") + what)
        if not cond: fails += 1
        else: passes += 1
    tool = os.path.realpath(__file__)
    core = os.path.dirname(os.path.dirname(tool))
    print("cc-try selfcheck")
    top = tempfile.mkdtemp(prefix="cctry-sc-")

    def fx(name, files=("core/bin/cc-foo",), sc_rc=0, author="boxbot", cross=False, board=True, tree=None, check="0",
           caged=False, member=False, oneshot=False):
        """One whole fixture: returns a dict with its paths, the PR head, and run() / gh() helpers."""
        T = os.path.join(top, name); H = os.path.join(T, "home"); stub = os.path.join(T, "stub")
        for d in (H, stub, os.path.join(T, "gh")): os.makedirs(d)
        env = dict(os.environ, HOME=H, PATH=stub + ":" + os.environ.get("PATH", "/usr/bin:/bin"),
                   GIT_CONFIG_GLOBAL=os.path.join(T, "gitconfig"), GIT_CONFIG_SYSTEM="/dev/null")
        with open(env["GIT_CONFIG_GLOBAL"], "w") as f:
            f.write("[user]\n\tname = t\n\temail = t@t\n[init]\n\tdefaultBranch = main\n")
        g = lambda *a, cwd=None: subprocess.run(["git", *a], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()
        def put(path, text, mode=0o755):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f: f.write(text)
            os.chmod(path, mode)
        repo = os.path.join(H, "dev", "demo")
        put(f"{repo}/core/bin/cc-foo", "#!/bin/sh\n[ \"$1\" = selfcheck ] && exit 0\necho main\n")
        put(f"{repo}/core/bin/cc-guard", "#!/bin/sh\necho guard\n")
        put(f"{repo}/core/bin/cc-special", "#!/bin/sh\necho special\n")
        put(f"{repo}/core/bin/cc-paid", "#!/bin/sh\necho paid\n")
        put(f"{repo}/tests/LANDING-policy.toml",
            '[paths]\ngate_first = ["core/bin/cc-special"]\nlander = []\npaid_review = ["core/bin/cc-paid"]\n', 0o644)
        for t in os.listdir(f"{repo}/core/bin"):      # ~/bin runs each tool from the live checkout, as on the box
            os.makedirs(f"{H}/bin", exist_ok=True); os.symlink(f"{repo}/core/bin/{t}", f"{H}/bin/{t}")
        g("init", "-q", repo); g("add", "-A", cwd=repo); g("commit", "-qm", "base", cwd=repo)
        origin = os.path.join(T, "origin.git")
        g("clone", "-q", "--bare", repo, origin); g("remote", "add", "origin", origin, cwd=repo)
        # the track's own worktree is where its PR head was made, and where its cc-green verdict is keyed
        pr = os.path.join(H, ".cc", "worktrees", "demo", "feat"); g("clone", "-q", origin, pr); g("checkout", "-qb", "track/feat", cwd=pr)
        for f in files:
            put(f"{pr}/{f}", f"#!/bin/sh\n[ \"$1\" = selfcheck ] && exit {sc_rc}\necho pr\n")
        g("add", "-A", cwd=pr); g("commit", "-qm", "the fix", cwd=pr); g("push", "-q", "origin", "HEAD:refs/pull/7/head", cwd=pr)
        head = g("rev-parse", "HEAD", cwd=pr)
        if member:                                    # a member workspace: its board is a link into ~/.cc/members
            put(f"{H}/.cc/members/demo/board/demo.json", "{}\n", 0o644)
            os.makedirs(f"{H}/.cc/boards"); os.symlink(f"{H}/.cc/members/demo/board/demo.json", f"{H}/.cc/boards/demo.json")
        elif board:
            put(f"{H}/.cc/boards/demo.json", "{}\n", 0o644)
        key = hashlib.sha1(os.path.realpath(pr).encode()).hexdigest()[:12]
        put(f"{H}/.cc/state/land/green/run-{key}.verdict",
            f"tree={tree or g('rev-parse', 'HEAD^{tree}', cwd=pr)}\ncheck={check}\nat=2026-10-11T18:00Z\nlog=x\n"
            + ("caged=1\n" if caged else ""), 0o644)
        # a unit that runs cc-foo (and another tool), and one whose tool only shares cc-foo's prefix
        put(f"{H}/.config/systemd/user/cc-foo.service",
            f"[Service]\nType={'oneshot' if oneshot else 'simple'}\nExecStart=%h/bin/cc-foo --tick\nExecStart=-%h/bin/cc-other\n", 0o644)
        put(f"{H}/.config/systemd/user/cc-near.service", "[Service]\nExecStart=%h/bin/cc-foobar\n", 0o644)
        put(f"{stub}/gh", f'#!/bin/sh\n[ -e {T}/gh/fail ] && exit 1\n[ "$1" = api ] && {{ echo boxbot; exit 0; }}\n'
                          f'[ "$1 $2" = "repo view" ] && {{ echo ownerx; exit 0; }}\n'
                          f'[ "$1 $2" = "pr view" ] && exec cat {T}/gh/"$3".json\n'
                          f'[ "$1 $2" = "pr list" ] && {{ cat {T}/gh/list.json 2>/dev/null || echo "[]"; exit 0; }}\nexit 1\n')
        put(f"{stub}/systemctl", f'#!/bin/sh\necho "$*" >> {T}/systemctl.log\n'
                                 f'case "$2" in is-active) echo active;; show) echo {"oneshot" if oneshot else "simple"};; esac\n')
        F = {"T": T, "H": H, "repo": repo, "head": head, "env": env, "g": g, "pr": pr,
             "try": os.path.join(H, ".cc", "try"), "co": os.path.join(H, ".cc", "try", "co", "demo-7"),
             "unit_d": os.path.join(H, ".config", "systemd", "user", "cc-foo.service.d")}
        def gh(n=7, **kw):
            v = {"number": n, "state": "OPEN", "headRefOid": head, "headRefName": "track/feat", "isCrossRepository": cross,
                 "author": {"login": author}, "mergeCommit": None, "files": [{"path": f} for f in files]}
            v.update(kw)
            with open(f"{T}/gh/{n}.json", "w") as f: json.dump(v, f)
        def run(*a):
            return subprocess.run([tool, *a], env=env, capture_output=True, text=True, timeout=120)
        def sysctl():
            try: return open(f"{T}/systemctl.log").read()
            except OSError: return ""
        def ledger_ops():
            try: return [json.loads(l)["op"] for l in open(f"{F['try']}/ledger.jsonl")]
            except OSError: return []
        F.update(gh=gh, run=run, sysctl=sysctl, ledger_ops=ledger_ops)
        gh()
        return F

    def untouched(F):
        return not os.path.lexists(F["co"]) and not os.listdir(F["try"] + "/bin") if os.path.isdir(F["try"] + "/bin") \
            else not os.path.lexists(F["co"])

    try:
        # --- overlay on and off ---------------------------------------------------------------------------------
        F = fx("onoff")
        r = F["run"]("on", "demo", "7")
        link = os.path.join(F["try"], "bin", "cc-foo")
        ok("on: a green PR by the box's worker goes live (exit 0)", r.returncode == 0)
        ok("…the overlay holds the changed tool, linked into the try checkout",
           os.path.islink(link) and os.readlink(link) == os.path.join(F["co"], "core/bin/cc-foo"))
        ok("…and only the changed tool", sorted(os.listdir(os.path.join(F["try"], "bin"))) == ["cc-foo"])
        ok("…the checkout is the PR's head", F["g"]("rev-parse", "HEAD", cwd=F["co"]) == F["head"])
        ok("…running it through the overlay runs the PR's version",
           subprocess.run([link], capture_output=True, text=True).stdout.strip() == "pr")
        dropin = os.path.join(F["unit_d"], "cc-try-demo-7.conf")
        txt = open(dropin).read() if os.path.exists(dropin) else ""
        ok("…the unit running it gets a drop-in: ExecStart cleared, then through the overlay, other lines kept",
           "\nExecStart=\nExecStart=%h/.cc/try/bin/cc-foo --tick\nExecStart=-%h/bin/cc-other\n" in txt)
        ok("…a unit whose tool only shares the prefix gets none",
           not os.path.exists(os.path.join(F["H"], ".config/systemd/user/cc-near.service.d")))
        ok("…the running non-oneshot unit is reloaded and restarted",
           "daemon-reload" in F["sysctl"]() and "restart cc-foo.service" in F["sysctl"]())
        ok("…and the on is a ledger line", F["ledger_ops"]() == ["on"])
        r = F["run"]("list")
        ok("list names the PR, its head and the tool", f"demo#7  head {F['head'][:12]}" in r.stdout and "cc-foo" in r.stdout)
        r = F["run"]("on", "demo", "7")
        ok("on again at the same head is a no-op", r.returncode == 0 and "already live" in r.stdout and F["ledger_ops"]() == ["on"])
        os.symlink("/bin/true", os.path.join(F["try"], "bin", "cc-mine"))
        r = F["run"]("off", "demo", "7")
        ok("off: exit 0", r.returncode == 0)
        ok("…the tool's link is gone, and a link cc-try did not write stays",
           not os.path.lexists(link) and os.path.islink(os.path.join(F["try"], "bin", "cc-mine")))
        ok("…the drop-in and its dir are gone", not os.path.exists(F["unit_d"]))
        ok("…the unit it restarted is restarted again", F["sysctl"]().count("restart cc-foo.service") == 2)
        ok("…the checkout is gone, from disk and from git's worktree list",
           not os.path.exists(F["co"]) and "try-7" not in F["g"]("worktree", "list", cwd=F["repo"]))
        ok("…nothing is live and the off is a ledger line", "nothing is live" in F["run"]("list").stdout
           and F["ledger_ops"]() == ["on", "off"])
        d = F["run"]("digest").stdout
        ok("digest names the on and the off", "demo#7 (cc-foo) went live" in d and "came off" in d and "by hand" in d)
        ok("off of something not live is refused", F["run"]("off", "demo", "7").returncode == 1)

        # --- guard refusals (each its own fixture; the kept case is `onoff` above) -------------------------------
        for name, files, says in (("guard", ("core/bin/cc-guard",), "core/bin/cc-guard (the guard)"),
                                  ("codex", ("core/bin/cc-harness-codex",), "core/bin/cc-harness-codex (the guard)"),
                                  ("policy", ("core/bin/cc-special",), "on the landing's gate_first list"),
                                  ("mixed", ("core/bin/cc-foo", "core/bin/cc-guard"), "core/bin/cc-guard (the guard)")):
            F = fx(name, files=files)
            r = F["run"]("on", "demo", "7")
            ok(f"refused: a PR changing {', '.join(files)} — says why, changes nothing",
               r.returncode == 1 and says in r.stderr and untouched(F) and F["ledger_ops"]() == [])
        ok("a root CLAUDE.md and a settings file are guards; an ordinary tool is not",
           guard_of("CLAUDE.md", "nosuchrepo") and guard_of("config/claude-settings.json", "nosuchrepo")
           and guard_of("core/bin/cc-foo", "nosuchrepo") is None)
        for name, kw, says in (("red", {"check": "1"}, "not green"), ("stale", {"tree": "0" * 40}, "not green"),
                               ("foreign", {"author": "someone"}, "not opened by the box's own workers"),
                               ("fork", {"cross": True}, "not opened by the box's own workers"),
                               ("noboard", {"board": False}, "has no board"),
                               ("notool", {"files": ("docs/x.md",)}, "changes no tool")):
            F = fx(name, **kw)
            r = F["run"]("on", "demo", "7")
            ok(f"refused: {name} — '{says}', changes nothing", r.returncode == 1 and says in r.stderr and untouched(F))

        # --- auto-revert ---------------------------------------------------------------------------------------
        def armed(name, **kw):
            F = fx(name, **kw)
            assert F["run"]("on", "demo", "7").returncode == 0, name
            return F
        def live(F): return os.path.exists(os.path.join(F["try"], "live", "demo-7.json"))
        def last_reason(F): return json.loads(open(os.path.join(F["try"], "ledger.jsonl")).read().splitlines()[-1]).get("reason", "")

        F = armed("merged")
        F["g"]("commit", "-q", "--allow-empty", "-m", "squash of #7", cwd=F["repo"])
        F["gh"](state="MERGED", mergeCommit={"oid": F["g"]("rev-parse", "HEAD", cwd=F["repo"])})
        F["run"]("check")
        ok("check: merged and in the live checkout — off, ledger says merged",
           not live(F) and not os.path.lexists(os.path.join(F["try"], "bin", "cc-foo")) and "merged" in last_reason(F)
           and F["ledger_ops"]() == ["on", "off"])
        F = armed("merged-undeployed")
        F["gh"](state="MERGED", mergeCommit={"oid": F["head"]})        # merged, but ~/dev/demo does not have it yet
        F["run"]("check")
        ok("check: merged but not yet in the live checkout — stays on", live(F) and F["ledger_ops"]() == ["on"])
        F = armed("closed")
        F["gh"](state="CLOSED"); F["run"]("check")
        ok("check: closed — off", not live(F) and "closed" in last_reason(F))
        F = armed("newhead")
        F["gh"](headRefOid="f" * 40); F["run"]("check")
        ok("check: a new head — dropped, not moved", not live(F) and "new head" in last_reason(F)
           and not os.path.exists(F["co"]))
        F = armed("nogh")
        open(os.path.join(F["T"], "gh", "fail"), "w").close(); F["run"]("check")
        ok("check: gh cannot answer — left as it is", live(F) and F["ledger_ops"]() == ["on"])
        for name, rc, stays in (("sc-red", 1, False), ("sc-green", 0, True)):
            F = armed(name, sc_rc=rc)
            p = os.path.join(F["try"], "live", "demo-7.json")
            rec = json.load(open(p)); rec["selfcheck_at"] = 0; json.dump(rec, open(p, "w"))
            F["run"]("check")
            ok(f"check: the tool's selfcheck {'passes — stays on' if stays else 'fails — off'}",
               live(F) == stays and (stays or "selfcheck failed" in last_reason(F)))
        F = armed("link-gone")
        os.unlink(os.path.join(F["try"], "bin", "cc-foo")); F["run"]("check")
        ok("check: a tried tool's overlay link gone — the rest comes off too", not live(F) and "link for cc-foo is gone" in last_reason(F)
           and not os.path.exists(os.path.join(F["unit_d"], "cc-try-demo-7.conf")))
        F = armed("sc-recent", sc_rc=1)
        F["run"]("check")
        ok("check: a failing selfcheck is not run again within the hour of the last", live(F))

        # --- the security read of #1086: each its own fixture, the kept case beside the refused one ---------------
        for name, kw, says in (
                ("base-guard", {"files": ("bin-private/cc-guard",)}, "has the name of a file that guards the box"),
                ("newname", {"files": ("core/bin/claude",)}, "not a tool ~/bin runs from"),
                ("samename", {"files": ("core/bin/cc-foo", "bin-private/cc-foo")}, "share the name cc-foo"),
                ("member", {"member": True}, "member workspace"),
                ("paid", {"files": ("core/bin/cc-paid",)}, "on the landing's paid_review list"),
                ("loop", {"files": ("core/bin/cc-loop",)}, "starts, fences or speaks for a session"),
                ("memtool", {"files": ("core/bin/cc-member-add",)}, "starts, fences or speaks for a session"),
                ("caged", {"caged": True}, "inside a worker's fence"),
                ("big", {"files": tuple(f"docs/f{i}.md" for i in range(100))}, "too big to try")):
            F = fx(name, **kw)
            r = F["run"]("on", "demo", "7")
            ok(f"refused: {name} — '{says}', changes nothing", r.returncode == 1 and says in r.stderr and untouched(F)
               and F["ledger_ops"]() == [] and not os.path.exists(os.path.join(F["try"], "live", "demo-7.json")))
        F = fx("elsewhere")
        os.unlink(os.path.join(F["H"], "bin", "cc-foo")); os.symlink("/bin/true", os.path.join(F["H"], "bin", "cc-foo"))
        r = F["run"]("on", "demo", "7")
        ok("refused: a name ~/bin takes from somewhere else", r.returncode == 1 and "not a tool ~/bin runs from" in r.stderr
           and untouched(F))
        F = fx("throwaway"); os.makedirs(os.path.join(F["H"], ".cc", "throwaway", "demo"))
        r = F["run"]("on", "demo", "7")
        ok("refused: a throwaway repo", r.returncode == 1 and "throwaway" in r.stderr and untouched(F))
        F = fx("held"); os.makedirs(os.path.join(F["try"], "bin")); os.symlink("/bin/true", os.path.join(F["try"], "bin", "cc-foo"))
        r = F["run"]("on", "demo", "7")
        ok("refused: a tool another try holds — and the holder's link stays",
           r.returncode == 1 and "another try holds it" in r.stderr and os.readlink(os.path.join(F["try"], "bin", "cc-foo")) == "/bin/true")
        F = fx("unit-held"); os.makedirs(F["unit_d"])
        open(os.path.join(F["unit_d"], "cc-try-demo-3.conf"), "w").close()
        r = F["run"]("on", "demo", "7")
        ok("refused: a unit already running from another try", r.returncode == 1 and "already runs from another try" in r.stderr
           and untouched(F) and os.listdir(F["unit_d"]) == ["cc-try-demo-3.conf"])
        F = fx("co-exists"); os.makedirs(F["co"])
        r = F["run"]("on", "demo", "7")
        ok("refused: a checkout already at the try's path — left as it is",
           r.returncode == 1 and "already exists" in r.stderr and os.listdir(F["co"]) == [] and F["ledger_ops"]() == [])
        F = fx("rollback"); os.makedirs(os.path.dirname(F["unit_d"]), exist_ok=True); open(F["unit_d"], "w").close()
        r = F["run"]("on", "demo", "7")
        ok("record first, then roll back: a failure after the links leaves no link, checkout or record, and says so",
           r.returncode == 1 and "rolled back" in r.stderr and not os.path.lexists(os.path.join(F["try"], "bin", "cc-foo"))
           and not os.path.exists(F["co"]) and not os.listdir(os.path.join(F["try"], "live"))
           and F["ledger_ops"]() == ["rollback"] and "try-7" not in F["g"]("worktree", "list", cwd=F["repo"]))
        F = fx("oneshot", oneshot=True)
        r = F["run"]("on", "demo", "7")
        ok("a oneshot unit gets its drop-in but is not restarted (its timer's next run picks it up)",
           r.returncode == 0 and os.path.exists(os.path.join(F["unit_d"], "cc-try-demo-7.conf"))
           and "restart" not in F["sysctl"]())
        F = fx("sweep")
        co = os.path.join(F["try"], "co", "demo-9"); os.makedirs(os.path.join(F["try"], "bin"))
        os.symlink(co + "/core/bin/cc-x", os.path.join(F["try"], "bin", "cc-x"))
        os.symlink("/bin/true", os.path.join(F["try"], "bin", "cc-mine"))
        stray = os.path.join(F["H"], ".config/systemd/user/cc-near.service.d"); os.makedirs(stray)
        open(os.path.join(stray, "cc-try-demo-9.conf"), "w").close()
        F["run"]("check")
        ok("check sweeps a link and a drop-in no record owns; a link cc-try did not write stays",
           not os.path.lexists(os.path.join(F["try"], "bin", "cc-x")) and not os.path.exists(stray)
           and os.path.islink(os.path.join(F["try"], "bin", "cc-mine")))
        F = fx("digest-safe"); os.makedirs(F["try"])
        with open(os.path.join(F["try"], "ledger.jsonl"), "w") as f:
            f.write(json.dumps({"at": "2099-01-01T00:00Z", "op": "off", "kind": "pr", "repo": "demo", "pr": 7, "head": "a" * 40,
                                "tools": ["<!channel>*x*"], "units": [], "by": "auto", "reason": "<http://evil|y> `z`"}) + "\n")
        d = F["run"]("digest").stdout
        ok("digest: tool names and reasons reach Slack with no mrkdwn, links or mentions",
           "demo#7 (channelx)" in d and "<" not in d and "*" not in d and "`" not in d.split("came off")[1])

        F = fx("drift"); g = F["g"]                   # main moved on in cc-guard after the PR branched
        with open(os.path.join(F["repo"], "core/bin/cc-guard"), "a") as f: f.write("# a fix on main\n")
        g("commit", "-qam", "guard fix", cwd=F["repo"])
        r = F["run"]("on", "demo", "7")
        ok("refused: a head whose guard files differ from the live checkout's — names them, changes nothing",
           r.returncode == 1 and "guard files differ" in r.stderr and "core/bin/cc-guard" in r.stderr and untouched(F)
           and F["ledger_ops"]() == [])
        g("reset", "-q", "--hard", "HEAD~1", cwd=F["repo"])
        ok("…and the same head goes live once they match again", F["run"]("on", "demo", "7").returncode == 0)
        F = fx("drift-live"); g = F["g"]              # a guard fix deploys while the try is live
        F["run"]("on", "demo", "7"); F["run"]("check")
        kept = os.path.islink(os.path.join(F["try"], "bin", "cc-foo"))
        with open(os.path.join(F["repo"], "core/bin/cc-guard"), "a") as f: f.write("# a fix on main\n")
        g("commit", "-qam", "guard fix", cwd=F["repo"])
        open(os.path.join(F["T"], "gh", "fail"), "w").close()   # and gh cannot be asked this pass
        F["run"]("check")
        offs = [json.loads(l) for l in open(os.path.join(F["try"], "ledger.jsonl")) if '"off"' in l]
        ok("check: a live try stays while its guard files match, and comes off once a guard fix deploys, gh or not",
           kept and not os.path.lexists(os.path.join(F["try"], "bin", "cc-foo")) and not os.path.lexists(F["co"])
           and len(offs) == 1 and "guard drift" in offs[0].get("reason", "") and "core/bin/cc-guard" in offs[0]["reason"])
        F = fx("mail", files=("core/bin/cc-mail",))
        r = F["run"]("on", "demo", "7")
        ok("refused: a PR changing cc-mail, which sends in the owner's name", r.returncode == 1
           and "core/bin/cc-mail" in r.stderr and "guard" in r.stderr and untouched(F))
        F = fx("env-green", check="1")               # the track's real verdict is red
        forged = os.path.join(F["T"], "forged"); shutil.copytree(os.path.join(F["H"], ".cc/state/land/green"), forged)
        for v in os.listdir(forged):
            p = os.path.join(forged, v); t = open(p).read(); open(p, "w").write(t.replace("check=1", "check=0"))
        r = subprocess.run([tool, "on", "demo", "7"], env=dict(F["env"], CC_GREEN_DIR=forged),
                           capture_output=True, text=True, timeout=120)
        ok("CC_GREEN_DIR is not read: a forged green verdict beside a red one changes nothing", r.returncode == 1
           and untouched(F) and F["ledger_ops"]() == [])
        F = fx("env-dev")
        r = subprocess.run([tool, "on", "demo", "7"], env=dict(F["env"], CC_DEV=os.path.join(F["T"], "nowhere")),
                           capture_output=True, text=True, timeout=120)
        ok("CC_DEV is not read: the live checkout is ~/dev/<repo> whatever the caller sets",
           r.returncode == 0 and os.path.islink(os.path.join(F["try"], "bin", "cc-foo")))
        F = fx("forged"); g = F["g"]
        victim = os.path.join(F["T"], "victim"); g("worktree", "add", "-q", "--detach", victim, cwd=F["repo"])
        F["run"]("on", "demo", "7")
        rf = os.path.join(F["try"], "live", "demo-7.json")
        rec = json.load(open(rf)); rec["checkout"] = victim; json.dump(rec, open(rf, "w"))
        r = F["run"]("off", "demo", "7")
        ok("off never takes the checkout from the record: a forged path elsewhere stays, the try's own goes",
           r.returncode == 0 and os.path.isdir(victim) and not os.path.lexists(F["co"]))
        os.makedirs(os.path.join(F["try"], "live"), exist_ok=True)
        json.dump({"key": "../../victim", "repo": "demo", "pr": 7, "head": F["head"], "tools": []},
                  open(os.path.join(F["try"], "live", "evil.json"), "w"))
        F["gh"](state="CLOSED"); F["run"]("check")
        ok("…and a record whose key leaves ~/.cc/try/co is not acted on", os.path.isdir(victim)
           and "nothing is live" in F["run"]("list").stdout)

        # --- the hot patch: a branch with no PR yet ---------------------------------------------------------------
        def patched(name, text=None, sc_rc=0, path=False, **kw):
            F = fx(name, **kw)
            g = F["g"]
            g("checkout", "-qb", "fix/x", cwd=F["repo"])
            with open(os.path.join(F["repo"], "core/bin/cc-foo"), "w") as f:
                f.write(text if text is not None else "#!/bin/sh\n[ \"$1\" = selfcheck ] && { echo \"cc-foo selfcheck: 1 passed, "
                        f"{sc_rc} failed\"; exit {sc_rc}; }}\necho patch\n")
            g("commit", "-qam", "patch", cwd=F["repo"]); F["phead"] = g("rev-parse", "HEAD", cwd=F["repo"])
            g("checkout", "-q", "main", cwd=F["repo"])
            F["target"] = "fix/x"
            if path:
                F["target"] = os.path.join(F["T"], "wt-fix"); g("worktree", "add", "-q", F["target"], "fix/x", cwd=F["repo"])
            F["pfile"] = os.path.join(F["try"], "live", f"demo-patch-{F['phead'][:12]}.json")
            return F
        F = patched("patch")
        r = F["run"]("on", "demo", "--branch", "fix/x")
        link = os.path.join(F["try"], "bin", "cc-foo")
        ok("hot patch: a branch whose tools' selfchecks pass goes live, and says when it expires",
           r.returncode == 0 and "expires" in r.stdout and subprocess.run([link], capture_output=True, text=True).stdout.strip() == "patch")
        rec = json.load(open(F["pfile"]))
        ok("…its expiry is 24 h after it went live", abs(rec["expires_at"] - time.time() - 24 * 3600) < 120)
        l = F["run"]("list").stdout
        ok("…list shows it apart, under Hot patches, with its expiry",
           "Hot patches" in l and f"fix/x  head {F['phead'][:12]}" in l and "expires " in l)
        ok("…and the digest names it as a hot patch with no PR",
           "hot patch demo fix/x (cc-foo) went live" in F["run"]("digest").stdout
           and "1 hot patch live with no PR" in F["run"]("digest").stdout)
        F["run"]("check")
        ok("…check before its expiry, no PR: stays", os.path.exists(F["pfile"]))
        open(os.path.join(F["T"], "gh", "fail"), "w").close()       # GitHub cannot be asked: the expiry still holds
        rec = json.load(open(F["pfile"])); rec["expires_at"] = time.time() - 1; json.dump(rec, open(F["pfile"], "w"))
        F["run"]("check")
        ok("…check after its expiry comes off on its own, with no session and no gh: the timer's pass is enough",
           not os.path.exists(F["pfile"]) and not os.path.lexists(link) and "expired" in last_reason(F))
        F = patched("patch-adopt")
        F["run"]("on", "demo", "--branch", "fix/x")
        with open(os.path.join(F["T"], "gh", "list.json"), "w") as f: json.dump([{"number": 9, "headRefOid": F["phead"], "author": {"login": "boxbot"}}], f)
        F["gh"](n=9, headRefOid=F["phead"], headRefName="fix/x")
        rec = json.load(open(F["pfile"])); rec["expires_at"] = time.time() - 1; json.dump(rec, open(F["pfile"], "w"))
        F["run"]("check")
        rec = json.load(open(F["pfile"])) if os.path.exists(F["pfile"]) else {}
        ok("hot patch: a PR at the same head adopts it — past its 24 h, it stays and follows the PR",
           rec.get("pr") == 9 and F["ledger_ops"]() == ["on", "adopt"] and "demo#9" in F["run"]("list").stdout)
        F["gh"](n=9, headRefOid=F["phead"], state="CLOSED"); F["run"]("check")
        ok("…and comes off when that PR closes", not os.path.exists(F["pfile"]) and "closed" in last_reason(F))
        F = patched("patch-other-pr")
        F["run"]("on", "demo", "--branch", "fix/x")
        with open(os.path.join(F["T"], "gh", "list.json"), "w") as f: json.dump([{"number": 9, "headRefOid": "e" * 40}], f)
        rec = json.load(open(F["pfile"])); rec["expires_at"] = time.time() - 1; json.dump(rec, open(F["pfile"], "w"))
        F["run"]("check")
        ok("hot patch: a PR at another head is not the same change — it still expires", not os.path.exists(F["pfile"]))
        F = patched("patch-fork")
        F["run"]("on", "demo", "--branch", "fix/x")
        with open(os.path.join(F["T"], "gh", "list.json"), "w") as f:
            json.dump([{"number": 9, "headRefOid": F["phead"], "isCrossRepository": True, "author": {"login": "boxbot"}}], f)
        rec = json.load(open(F["pfile"])); rec["expires_at"] = time.time() - 1; json.dump(rec, open(F["pfile"], "w"))
        F["run"]("check")
        ok("hot patch: a fork's PR at the same head does not adopt it — it still expires", not os.path.exists(F["pfile"])
           and "adopt" not in F["ledger_ops"]())
        for name, who, adopts in (("patch-stranger", "stranger", False), ("patch-owner", "ownerx", True)):
            F = patched(name)
            F["run"]("on", "demo", "--branch", "fix/x")
            with open(os.path.join(F["T"], "gh", "list.json"), "w") as f:
                json.dump([{"number": 9, "headRefOid": F["phead"], "author": {"login": who}}], f)
            F["gh"](n=9, headRefOid=F["phead"], headRefName="fix/x")
            rec = json.load(open(F["pfile"])); rec["expires_at"] = time.time() - 1; json.dump(rec, open(F["pfile"], "w"))
            F["run"]("check")
            ok(f"hot patch: a same-head PR by {'the owner adopts it' if adopts else 'someone not the owner or a box seat does not adopt it — it still expires'}",
               os.path.exists(F["pfile"]) == adopts and ("adopt" in F["ledger_ops"]()) == adopts)
        F = patched("patch-path", path=True)
        r = F["run"]("on", "demo", "--branch", F["target"])
        ok("hot patch from a worktree path goes live", r.returncode == 0 and os.path.exists(F["pfile"]))
        r = F["run"]("off", "demo", "--branch", F["target"])
        ok("…and off by the same path takes it out", r.returncode == 0 and not os.path.exists(F["pfile"])
           and F["ledger_ops"]() == ["on", "off"])
        for name, kw, says in (("patch-red", {"sc_rc": 1}, "selfcheck failed"),
                               ("patch-nosc", {"text": "#!/bin/sh\necho patch\n"}, "has no selfcheck"),
                               # the word in the file is not a selfcheck: it runs, exits 0 and prints no tally
                               ("patch-word", {"text": "#!/bin/sh\n# selfcheck: none yet\necho patch\n"}, "without its tally")):
            F = patched(name, **kw)
            r = F["run"]("on", "demo", "--branch", "fix/x")
            ok(f"hot patch refused: {says} — rolled back, nothing live",
               r.returncode == 1 and says in r.stderr and not os.path.exists(F["pfile"])
               and not os.path.lexists(os.path.join(F["try"], "bin", "cc-foo")) and F["ledger_ops"]() == ["rollback"])
        F = fx("patch-guard"); g = F["g"]
        g("checkout", "-qb", "fix/g", cwd=F["repo"])
        with open(os.path.join(F["repo"], "core/bin/cc-guard"), "a") as f: f.write("# selfcheck\n")
        g("commit", "-qam", "g", cwd=F["repo"]); g("checkout", "-q", "main", cwd=F["repo"])
        r = F["run"]("on", "demo", "--branch", "fix/g")
        ok("hot patch refused: a guard file keeps the full landing", r.returncode == 1 and "(the guard)" in r.stderr
           and F["ledger_ops"]() == [])
        r = F["run"]("on", "demo", "--branch", "main")
        ok("hot patch refused: a branch the live checkout already has", r.returncode == 1 and "nothing to patch" in r.stderr)

        # --- the line to the seat that dispatched it ------------------------------------------------------------
        for name, kw, want in (("hint-green", {}, "Green at its head: `cc-try on demo 7`"),
                               ("hint-red", {"check": "1"}, "Once its gate is green, `cc-try on demo 7`"),
                               ("hint-guard", {"files": ("core/bin/cc-guard",)}, "")):
            F = fx(name, **kw)
            r = F["run"]("hint", "demo", "https://github.com/x/demo/pull/7", "feat")
            ok(f"hint: {name} — {want or 'says nothing'}", r.returncode == 0 and r.stdout.strip().startswith(want)
               and (want or r.stdout.strip() == ""))

        # --- PATH order -----------------------------------------------------------------------------------------
        H = os.path.join(top, "pathhome"); os.makedirs(os.path.join(H, "bin")); os.makedirs(os.path.join(H, ".cc", "try", "bin"))
        for d in ("bin", ".cc/try/bin"):
            with open(os.path.join(H, d, "cc-foo"), "w") as f: f.write(f"#!/bin/sh\necho {d}\n")
            os.chmod(os.path.join(H, d, "cc-foo"), 0o755)
        for src in ("bin/cc", "bin/cc-loop", "bin/cc-rc", "install.sh"):
            lines = [l.split("export PATH")[0] for l in open(os.path.join(core, src)) if l.startswith('case ":$PATH:"')]
            for start in ("/usr/bin:/bin", f"{H}/bin:/usr/bin:/bin"):
                r = subprocess.run(["bash", "-c", "\n".join(lines) + "\necho \"$PATH\"; cc-foo"],
                                   env={"HOME": H, "PATH": start}, capture_output=True, text=True)
                got = r.stdout.splitlines()
                parts = got[0].split(":") if got else []
                ok(f"PATH order: {src}, {'with' if start.startswith(H) else 'without'} ~/bin on PATH already, "
                   "puts the overlay first and ~/bin after it",
                   parts[:1] == [f"{H}/.cc/try/bin"] and f"{H}/bin" in parts and got[1:] == [".cc/try/bin"])
    finally:
        shutil.rmtree(top, ignore_errors=True)
    print(f"cc-try selfcheck: {passes} passed, {fails} failed")
    return fails == 0
