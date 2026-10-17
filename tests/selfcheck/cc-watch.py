# cc-watch's selfcheck: the cases behind `cc-watch selfcheck` (there is no other entry point). Not a module: cc-watch
# execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it defines, so `__file__` is the tool. No module
# docstring (it would replace the tool's __doc__) and no top-level name but the def below.

def selfcheck():
    import shlex
    import stat
    n = [0, 0]
    tool = os.path.realpath(__file__)

    def check(name, cond, got=None):
        n[0 if cond else 1] += 1
        print(("  ok   " if cond else "  FAIL ") + name + ("" if cond or got is None else "  << %r" % (got,)))

    def script(path, text):
        with open(path, "w") as fh:
            fh.write(text)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def box(t):
        """A fresh box under t: its own HOME, spool, state, an empty shipped dir and fakes for cc-slack, curl and
        the Cloudflare tool, each driven by a file the case writes. Nothing of the real box is read or written."""
        for d in ("bin", "spool", "state", "shipped", "home"):
            os.makedirs(os.path.join(t, d), exist_ok=True)
        for d in ("state", "spool"):   # the run refuses a state dir or spool anyone else can open
            os.chmod(os.path.join(t, d), 0o700)
        # cc-slack: logs "<channel>\t<id>\t<text>"; exits with the number in slack-rc (0 when absent).
        script(os.path.join(t, "bin", "cc-slack"),
               "#!/bin/sh\nprintf '%s\\t%s\\t%s\\n' \"$3\" \"$5\" \"$6\" >> \"$WT/slack.log\"\n"
               "[ -f \"$WT/slack-rc\" ] && exit \"$(cat \"$WT/slack-rc\")\"\nexit 0\n")
        # curl: answers from web.json, {url: [status, location, body, curl exit]}; an unknown url is a 404.
        script(os.path.join(t, "bin", "curl"), "#!/usr/bin/env python3\nimport json, os, sys\n"
               "a = sys.argv[1:]; url = a[-1]; out = a[a.index('-o') + 1]\n"
               "open(os.path.join(os.environ['WT'], 'curl.log'), 'a').write(('-g ' if '-g' in a else '') + url + '\\n')\n"
               "web = json.load(open(os.path.join(os.environ['WT'], 'web.json')))\n"
               "st, loc, body, rc = web.get(url, [404, '', 'not found', 0])\n"
               "open(out, 'w').write(body)\n"
               "if rc: sys.exit(rc)\n"
               "sys.stdout.write(f'{st} {loc}')\n")
        # The Cloudflare tool: api() answers from cf.json; {"status": 403} raises as the real one does on a 403.
        with open(os.path.join(t, "cf.py"), "w") as fh:
            fh.write("import json, os\n"
                     "class ApiError(Exception):\n    def __init__(self, s):\n        self.status = s\n"
                     "def zone_id(name):\n    return 'z' * 32\n"
                     "def api(method, path, scope, body=None):\n"
                     "    r = json.load(open(os.path.join(os.environ['WT'], 'cf.json')))\n"
                     "    if 'status' in r:\n"
                     "        if r['status'] == 403:\n            ping_permission_needed(scope)\n"
                     "        raise ApiError(r['status'])\n    return r\n"
                     "def ping_permission_needed(scope):\n"
                     "    open(os.path.join(os.environ['WT'], 'pings'), 'a').write(scope + '\\n')\n")
        cf(t, 10, 60, 0)
        with open(os.path.join(t, "web.json"), "w") as fh:
            json.dump({}, fh)
        return t

    def cf(t, hour, before, scan, errors=0):
        groups = [{"count": hour - errors, "dimensions": {"edgeResponseStatus": 200}}]
        if errors:
            groups.append({"count": errors, "dimensions": {"edgeResponseStatus": 404}})
        with open(os.path.join(t, "cf.json"), "w") as fh:
            json.dump({"data": {"viewer": {"zones": [{"hour": groups, "before": [{"count": before}],
                                                      "scan": [{"count": scan}]}]}}}, fh)

    def web(t, pages):
        with open(os.path.join(t, "web.json"), "w") as fh:
            json.dump(pages, fh)

    def env(t):
        e = dict(os.environ, WT=t, HOME=os.path.join(t, "home"), CC_WATCH_DIR=os.path.join(t, "spool"),
                 CC_WATCH_STATE=os.path.join(t, "state"), CC_WATCH_SHIPPED=os.path.join(t, "shipped"),
                 CC_WATCH_CF=os.path.join(t, "cf.py"), PATH=os.path.join(t, "bin") + ":" + os.environ["PATH"])
        e.pop("SLACK_ALERTS", None)
        return e

    def cc(t, *args):
        p = subprocess.run([sys.executable, tool] + list(args), env=env(t), capture_output=True, text=True)
        return p.returncode, p.stdout.strip()

    def watcher(t, name, code_file, revert="tell", expires=None, every="60"):
        """A watcher whose check exits with the number in code_file and says 'reason <n>'."""
        chk = f"c=$(cat {code_file}); echo reason $c; exit $c"
        args = ["add", "--name", name, "--granted", "a test grant", "--check", chk, "--every", every,
                "--revert", revert, "--owner", "#perms-test"]
        cc(t, *(args + (["--expires", expires] if expires else [])))

    def set_code(t, c):
        with open(os.path.join(t, "code"), "w") as fh:
            fh.write(str(c))

    def due(t, name):
        """Make the watcher due again without waiting: its last run moved an hour back."""
        p = os.path.join(t, "state", name + ".json")
        st = json.load(open(p))
        st["last"] -= 3600
        json.dump(st, open(p, "w"))

    def lines(t, f):
        try:
            return [ln for ln in open(os.path.join(t, f)).read().splitlines() if ln]
        except OSError:
            return []

    print("cc-watch selfcheck")
    # OK is silent: a passing check posts nothing and its state says OK.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 0); watcher(t, "w", os.path.join(t, "code"))
        cc(t, "run")
        check("OK: silent", lines(t, "slack.log") == [], lines(t, "slack.log"))
        check("OK: recorded", json.load(open(os.path.join(t, "state", "w.json"))).get("verdict") == "OK")

    # WARN goes to the owner's channel once, however many due runs say WARN again.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 1); watcher(t, "w", os.path.join(t, "code"))
        cc(t, "run"); due(t, "w"); cc(t, "run")
        got = lines(t, "slack.log")
        check("WARN: one post, to the owner", len(got) == 1 and got[0].startswith("#perms-test\t") and "reason 1" in got[0], got)

    # A run that is not due runs no check: the second run straight after the first changes nothing.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 0); watcher(t, "w", os.path.join(t, "code"))
        cc(t, "run"); set_code(t, 1); cc(t, "run")
        check("not due: no check ran", lines(t, "slack.log") == [] and
              json.load(open(os.path.join(t, "state", "w.json")))["verdict"] == "OK")

    # BAD runs the revert exactly once and posts to #alerts once; after an OK the next BAD is a new episode.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 2)
        watcher(t, "w", os.path.join(t, "code"), revert=f"echo undone >> {t}/reverts")
        cc(t, "run"); due(t, "w"); cc(t, "run"); due(t, "w"); cc(t, "run")
        got = lines(t, "slack.log")
        check("BAD: revert ran exactly once", lines(t, "reverts") == ["undone"], lines(t, "reverts"))
        check("BAD: one post, to #alerts, saying it reverted",
              len(got) == 1 and got[0].startswith("#alerts\t") and "reverted with" in got[0], got)
        set_code(t, 0); due(t, "w"); cc(t, "run")
        check("BAD then OK: silent", len(lines(t, "slack.log")) == 1)
        set_code(t, 2); due(t, "w"); cc(t, "run")
        check("BAD again after OK: reverts and posts again",
              len(lines(t, "reverts")) == 2 and len(lines(t, "slack.log")) == 2, (lines(t, "reverts"), lines(t, "slack.log")))

    # revert "tell" (a grant that predates watchers) runs nothing and says it is the owner's to undo.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 2); watcher(t, "w", os.path.join(t, "code"))
        cc(t, "run")
        got = lines(t, "slack.log")
        check("BAD with tell: posted, not reverted", len(got) == 1 and "not reverted" in got[0], got)

    # A post Slack refused is tried again on the next due run, with the same id; the revert is not run again.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 2)
        watcher(t, "w", os.path.join(t, "code"), revert=f"echo undone >> {t}/reverts")
        with open(os.path.join(t, "slack-rc"), "w") as fh:
            fh.write("1")
        cc(t, "run"); os.remove(os.path.join(t, "slack-rc")); due(t, "w"); cc(t, "run"); due(t, "w"); cc(t, "run")
        ids = [ln.split("\t")[1] for ln in lines(t, "slack.log")]
        check("failed post: retried once with the same id, revert once",
              len(ids) == 2 and ids[0] == ids[1] and lines(t, "reverts") == ["undone"], (ids, lines(t, "reverts")))

    # An expired watcher runs no check; one expiring later still runs.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 1)
        watcher(t, "old", os.path.join(t, "code"), expires="2020-01-01T00:00Z")
        watcher(t, "new", os.path.join(t, "code"), expires="2999-01-01T00:00Z")
        cc(t, "run")
        got = lines(t, "slack.log")
        check("expired: skipped, the live one ran", len(got) == 1 and "watcher new" in got[0], got)
        listed = {ln.split()[0]: ln for ln in cc(t, "list")[1].splitlines()}
        check("expired: listed as expired, the live one not", "expired" in listed.get("old", "") and
              "expired" not in listed.get("new", "x expired"), listed)

    # A BAD post that failed is still sent when the next check is OK; the revert is not run again.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 2)
        watcher(t, "w", os.path.join(t, "code"), revert=f"echo undone >> {t}/reverts")
        with open(os.path.join(t, "slack-rc"), "w") as fh:
            fh.write("1")
        cc(t, "run")
        os.remove(os.path.join(t, "slack-rc")); set_code(t, 0); due(t, "w"); cc(t, "run")
        got = lines(t, "slack.log")
        check("failed BAD post, then OK: the BAD post still lands, once",
              len(got) == 2 and got[0] == got[1] and got[1].startswith("#alerts\t") and "reverted with" in got[1]
              and lines(t, "reverts") == ["undone"], (got, lines(t, "reverts")))
        due(t, "w"); cc(t, "run")
        check("failed BAD post, then OK: not sent a third time", len(lines(t, "slack.log")) == 2, lines(t, "slack.log"))
    # A sent BAD post is not sent again by a later OK.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 2); watcher(t, "w", os.path.join(t, "code"))
        cc(t, "run"); set_code(t, 0); due(t, "w"); cc(t, "run")
        check("sent BAD post, then OK: one post", len(lines(t, "slack.log")) == 1, lines(t, "slack.log"))

    # A spec that cannot be read is skipped and the watchers after it still run; "every" may be like 15m.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 1)
        for nm, extra in (("a-expires", {"expires": "next tuesday"}), ("b-every", {"every": "soon"})):
            with open(os.path.join(t, "spool", nm + ".json"), "w") as fh:
                json.dump(dict({"name": nm, "check": "exit 1", "owner": "#perms-test"}, **extra), fh)
        with open(os.path.join(t, "spool", "c-15m.json"), "w") as fh:
            json.dump({"name": "c-15m", "check": f"c=$(cat {t}/code); echo reason $c; exit $c", "every": "15m",
                       "owner": "#perms-test"}, fh)
        watcher(t, "z", os.path.join(t, "code"))
        p = subprocess.run([sys.executable, tool, "run"], env=env(t), capture_output=True, text=True)
        got = lines(t, "slack.log")
        check("bad specs: skipped and named, the others ran",
              p.returncode == 0 and sorted(ln.split("\t")[1].split(":")[1] for ln in got) == ["c-15m", "z"]
              and "a-expires" in p.stderr and "b-every" in p.stderr, (p.returncode, got, p.stderr))

    # A second BAD while Slack is down queues behind the first: both land, in order, once Slack is back.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 2); watcher(t, "w", os.path.join(t, "code"))
        with open(os.path.join(t, "slack-rc"), "w") as fh:
            fh.write("1")
        cc(t, "run"); set_code(t, 0); due(t, "w"); cc(t, "run"); set_code(t, 2); due(t, "w"); cc(t, "run")
        os.remove(os.path.join(t, "slack-rc")); cc(t, "run")
        ids = [ln.split("\t")[1] for ln in lines(t, "slack.log")]
        # The fake logs refused tries too; the last run is the first Slack takes, and it sends the two in order.
        check("unsent BADs queue: both land, oldest first",
              ids[-2:] == ["watch:w:1:BAD", "watch:w:2:BAD"] and ids.count("watch:w:2:BAD") == 1, ids)

    # The state lives under the spool (~/.cc/watch/state by default), not ~/.cc/state, and is made 0700.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 0); watcher(t, "w", os.path.join(t, "code"))
        e = env(t); e.pop("CC_WATCH_STATE")
        subprocess.run([sys.executable, tool, "run"], env=e, capture_output=True, text=True)
        sd = os.path.join(t, "spool", "state")
        check("state: default dir is the spool's state/, mode 0700",
              os.path.isfile(os.path.join(sd, "w.json")) and stat.S_IMODE(os.stat(sd).st_mode) == 0o700)

    # A .lock planted as a symlink is not followed: the run refuses and its target keeps its bytes.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 1); watcher(t, "w", os.path.join(t, "code"))
        with open(os.path.join(t, "precious"), "w") as fh:
            fh.write("keep me")
        os.symlink(os.path.join(t, "precious"), os.path.join(t, "state", ".lock"))
        rc, _ = cc(t, "run")
        check("symlinked lock: refused, target untouched, no check ran",
              rc == 1 and open(os.path.join(t, "precious")).read() == "keep me" and lines(t, "slack.log") == [],
              (rc, lines(t, "slack.log")))
    # A state dir open to others, or a symlink to one, is refused; a 0700 one of our own runs.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 1); watcher(t, "w", os.path.join(t, "code"))
        os.chmod(os.path.join(t, "state"), 0o777)
        rc, _ = cc(t, "run")
        check("state dir 0777: refused, no check ran", rc == 1 and lines(t, "slack.log") == [], rc)
        os.chmod(os.path.join(t, "state"), 0o700)
        rc, _ = cc(t, "run")
        check("state dir 0700: runs", rc == 0 and len(lines(t, "slack.log")) == 1, (rc, lines(t, "slack.log")))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 1); watcher(t, "w", os.path.join(t, "code"))
        os.rmdir(os.path.join(t, "state")); os.makedirs(os.path.join(t, "real"), mode=0o700)
        os.symlink(os.path.join(t, "real"), os.path.join(t, "state"))
        rc, _ = cc(t, "run")
        check("state dir a symlink: refused", rc == 1 and lines(t, "slack.log") == [], rc)

    # One run at a time: a run that finds the lock held runs no check.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        import fcntl as _fcntl
        box(t); set_code(t, 1); watcher(t, "w", os.path.join(t, "code"))
        with open(os.path.join(t, "state", ".lock"), "w") as held:
            _fcntl.flock(held, _fcntl.LOCK_EX)
            rc, _ = cc(t, "run")
            check("locked: exits 0 and runs no check", rc == 0 and lines(t, "slack.log") == []
                  and not os.path.exists(os.path.join(t, "state", "w.json")), lines(t, "slack.log"))
        cc(t, "run")
        check("lock released: the next run checks", len(lines(t, "slack.log")) == 1, lines(t, "slack.log"))

    # The public-URL kit, each case on its own fake web and fake analytics.
    H = "https://site.example.org"
    access = [302, "https://team.cloudflareaccess.com/cdn-cgi/access/login/site", "", 0]
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": access})
        rc, out = cc(t, "url", "site.example.org", "--expect", "access")
        check("url access: Access login is OK", rc == 0 and "Access login" in out, (rc, out))
    # Only the real Access redirect counts: its host ends in .cloudflareaccess.com and its path is the login path.
    for loc in ("/cdn-cgi/access/login/site", "https://site.example.org/cdn-cgi/access/login/site",
                "https://evil.org/cdn-cgi/access/login/x?next=team.cloudflareaccess.com",
                "https://team.cloudflareaccess.com.evil.org/cdn-cgi/access/login/site",
                "http://team.cloudflareaccess.com/cdn-cgi/access/login/site",
                "https://team.cloudflareaccess.com/elsewhere"):
        with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
            box(t); web(t, {H + "/": [302, loc, "", 0]})
            rc, out = cc(t, "url", "site.example.org", "--expect", "access")
            check(f"url access: lookalike redirect {loc} is not Access", rc == 1 and "expected an Access" in out, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": [200, "", "<html>hello</html>", 0]})
        rc, out = cc(t, "url", "site.example.org", "--expect", "access")
        check("url access: a page with no login is BAD", rc == 2 and "no Access login" in out, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": [0, "", "", 60]})
        rc, out = cc(t, "url", "site.example.org", "--expect", "page")
        check("url: invalid TLS is BAD", rc == 2 and "TLS" in out, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": [200, "", "<html><a href='/a'>a</a> <a href='https://other.org/x'>x</a></html>", 0],
                        H + "/a": [200, "", "<p>fine</p>", 0]})
        rc, out = cc(t, "url", "site.example.org", "--expect", "page")
        check("url page: clean site is OK", rc == 0 and "nothing exposed" in out, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": [200, "", "<html>ok</html>", 0], H + "/.env": [200, "", "DB_PASSWORD=x\n", 0]})
        rc, out = cc(t, "url", "site.example.org", "--expect", "page")
        check("url page: a served .env is BAD", rc == 2 and "/.env is served" in out, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        tok = "ghp_" + "A" * 36
        box(t); web(t, {H + "/": [200, "", "<a href='/err'>e</a>", 0],
                        H + "/err": [500, "", f"Traceback (most recent call last):\n  token {tok}", 0]})
        rc, out = cc(t, "url", "site.example.org", "--expect", "reachable")
        check("url: a linked traceback with a secret is BAD, the secret not printed",
              rc == 2 and "traceback" in out and "secret-shaped" in out and tok not in out, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": access})
        with open(os.path.join(t, "cf.json"), "w") as fh:
            json.dump({"status": 403}, fh)
        rc, out = cc(t, "url", "site.example.org", "--expect", "access")
        check("traffic: no analytics scope is said, and OK", rc == 0 and "no analytics scope" in out, (rc, out))
        check("traffic: no analytics scope pages nobody", lines(t, "pings") == [], lines(t, "pings"))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": access})
        with open(os.path.join(t, "cf.json"), "w") as fh:
            json.dump({"status": 500}, fh)
        rc, out = cc(t, "url", "site.example.org", "--expect", "access")
        check("traffic: another API failure is WARN, and pages nobody", rc == 1 and lines(t, "pings") == [], (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": access}); cf(t, 5000, 600, 0)
        rc, out = cc(t, "url", "site.example.org", "--expect", "access")
        check("traffic: a spike over baseline is WARN", rc == 1 and "5000 requests" in out, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": access}); cf(t, 400, 2400, 0, errors=300)
        rc, out = cc(t, "url", "site.example.org", "--expect", "access")
        check("traffic: an error surge is WARN, no spike", rc == 1 and "4xx or 5xx" in out and "against" not in out, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": access}); cf(t, 200, 1200, 5000)
        rc, out = cc(t, "url", "site.example.org", "--expect", "access")
        check("traffic: a scanner burst is WARN however big, never BAD", rc == 1 and "5000 scanner-path" in out, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": access}); cf(t, 200, 1200, 0)
        rc, out = cc(t, "url", "site.example.org", "--expect", "access")
        check("traffic: no scanner paths is OK", rc == 0 and "traffic normal" in out, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": [200, "", "<a href='/p[1-99999]'>x</a>", 0], H + "/p[1-99999]": [200, "", "ok", 0]})
        cc(t, "url", "site.example.org", "--expect", "page")
        got = lines(t, "curl.log")
        check("url: every fetch is -g, so a bracketed link is one path",
              H + "/p[1-99999]" in [ln[3:] for ln in got] and all(ln.startswith("-g ") for ln in got), got)

    # Lane fixes at 4d9442b9, each on its own fixture.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": access, H + "/.git/config": [200, "", "[core]\n\tbare = false\n", 0]})
        rc, out = cc(t, "url", "site.example.org", "--expect", "access")
        check("url access: exposure is probed behind Access too", rc == 2 and "/.git/config is served" in out, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": access})
        rc, out = cc(t, "url", "site.example.org", "--expect", "access")
        check("url access: Access with nothing exposed stays OK", rc == 0, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": [500, "", "Traceback (most recent call last):\n  boom", 0]})
        rc, out = cc(t, "url", "site.example.org", "--expect", "reachable")
        check("url: a 500 at the root has its body read", rc == 2 and "/ shows a server traceback" in out, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": [404, "", "Traceback (most recent call last):", 0]})
        rc, out = cc(t, "url", "site.example.org", "--expect", "reachable")
        check("url: a 404 at the root is not read as a page", rc == 0, (rc, out))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": [200, "", "<a href='/v?token=s3cr3t'>2</a> <a href='/v'>v</a>", 0],
                        H + "/v?token=s3cr3t": [200, "", "<title>Index of /files</title>", 0], H + "/v": [200, "", "ok", 0]})
        rc, out = cc(t, "url", "site.example.org", "--expect", "page")
        got = [ln[3:] for ln in lines(t, "curl.log")]
        check("url: a link keeps its query string, and the finding never shows it",
              rc == 2 and "/v?… is a directory listing" in out and "s3cr3t" not in out
              and H + "/v?token=s3cr3t" in got and H + "/v" in got, (rc, out, got))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); set_code(t, 2); watcher(t, "w", os.path.join(t, "code"), revert=f"echo r >> {t}/reverts")
        os.chmod(os.path.join(t, "spool"), 0o777)
        cc(t, "run")
        check("spool: one open to others is not run", lines(t, "reverts") == [] and lines(t, "slack.log") == [],
              (lines(t, "reverts"), lines(t, "slack.log")))
        os.chmod(os.path.join(t, "spool"), 0o700)
        cc(t, "run")
        check("spool: the same spool at 0700 is run", lines(t, "reverts") == ["r"], lines(t, "reverts"))
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); os.rmdir(os.path.join(t, "spool")); os.mkdir(os.path.join(t, "real"), 0o700)
        os.symlink(os.path.join(t, "real"), os.path.join(t, "spool"))
        rc, _ = cc(t, "add", "--name", "w", "--granted", "g", "--check", "true", "--owner", "#perms-test")
        check("spool: add refuses a symlinked spool", rc == 2 and os.listdir(os.path.join(t, "real")) == [], rc)
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t)
        p = subprocess.run([sys.executable, tool, "add", "--name", "w", "--granted", "g", "--check", "true",
                            "--every", "soon", "--owner", "#perms-test"], env=env(t), capture_output=True, text=True)
        check("add: a bad --every is one line, no traceback, nothing written",
              p.returncode == 2 and "Traceback" not in p.stderr and len(p.stderr.strip().splitlines()) == 1
              and os.listdir(os.path.join(t, "spool")) == [], (p.returncode, p.stderr))
        rc, _ = cc(t, "add", "--name", "w", "--granted", "g", "--check", "true", "--every", "15m", "--owner", "#perms-test")
        check("add: a good --every is written", rc == 0 and os.listdir(os.path.join(t, "spool")) == ["w.json"], rc)

    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); os.rmdir(os.path.join(t, "spool")); set_code(t, 2)
        e = dict(env(t)); e.pop("CC_WATCH_STATE")   # the default: state inside the spool
        old = os.umask(0o022)
        try:
            subprocess.run([sys.executable, tool, "run"], env=e, capture_output=True)
            subprocess.run([sys.executable, tool, "add", "--name", "w", "--granted", "g", "--owner", "#perms-test",
                            "--check", f"exit $(cat {t}/code)", "--revert", f"echo r >> {t}/reverts"], env=e, capture_output=True)
            subprocess.run([sys.executable, tool, "run"], env=e, capture_output=True)
        finally:
            os.umask(old)
        mode = stat.S_IMODE(os.stat(os.path.join(t, "spool")).st_mode)
        check("spool: a first run makes it 0700, and its specs then run", mode == 0o700 and lines(t, "reverts") == ["r"],
              (oct(mode), lines(t, "reverts")))

    # End to end: a watcher on the URL kit that goes BAD reverts once and tells #alerts once.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": [200, "", "<html>open</html>", 0]})
        cc(t, "add", "--name", "site", "--granted", "public site.example.org", "--every", "60", "--owner", "#perms-test",
           "--check", f"{sys.executable} {tool} url site.example.org --expect access",
           "--revert", f"echo closed >> {t}/reverts")
        cc(t, "run"); due(t, "site"); cc(t, "run")
        got = lines(t, "slack.log")
        check("url watcher: BAD reverts once, one #alerts post",
              lines(t, "reverts") == ["closed"] and len(got) == 1 and got[0].startswith("#alerts\t"), (lines(t, "reverts"), got))

    # A shipped spec runs only its own url check, as argv: one that parses to anything else, or carries a revert,
    # is skipped, and shell text around an anchored check is handed to url as words, never run.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        box(t); web(t, {H + "/": [200, "", "<html>fine</html>", 0]})
        pw = os.path.join(t, "pwned")
        for name, chk, rev in (("good", "cc-watch url site.example.org --expect page", "tell"),
                               ("lead", f"echo x >> {pw}; cc-watch url site.example.org --expect page", "tell"),
                               ("pipe", f"curl x | sh; cc-watch url site.example.org --expect page", "tell"),
                               ("trail", f"cc-watch url site.example.org --expect page; echo x >> {pw}", "tell"),
                               ("rev", "cc-watch url site.example.org --expect page", f"echo x >> {pw}")):
            with open(os.path.join(t, "shipped", name + ".json"), "w") as fh:
                json.dump({"name": name, "granted": "g", "check": chk, "every": 60, "revert": rev,
                           "expires": None, "owner": "#alerts"}, fh)
        p = subprocess.run([sys.executable, tool, "run"], env=env(t), capture_output=True, text=True)
        ran = sorted(f[:-5] for f in os.listdir(os.path.join(t, "state")) if f.endswith(".json"))
        good = json.load(open(os.path.join(t, "state", "good.json"))).get("verdict") if "good" in ran else None
        check("shipped spec: an anchored url check runs and says OK", good == "OK", (ran, good, p.stderr))
        check("shipped spec: a check that is not wholly cc-watch url, or has a revert, is skipped and named",
              ran == ["good", "trail"] and all(f"{n}.json: a shipped check" in p.stderr for n in ("lead", "pipe", "rev")),
              (ran, p.stderr))
        check("shipped spec: no shell ever runs its text", not os.path.exists(pw), lines(t, "pwned"))

    # The sweep of main runs as a shipped spec too, but only as the two bare words: no REV, repo or shell text.
    sweep = shipped_argv("lander-self sweep")
    check("shipped spec: `lander-self sweep` runs the lander-self beside this tool, as argv",
          sweep == [sys.executable, os.path.join(BIN, "lander-self"), "sweep"], sweep)
    check("…and one that names a REV, a repo or more text is refused",
          all(shipped_argv(c) is None for c in ("lander-self sweep HEAD~1", "lander-self sweep --repo /tmp/x",
                                                 "lander-self sweep; touch /tmp/x", "lander-self promote")))

    def shipped_ok(root):
        """None when root carries no config/ (core published on its own), else (passed, what was wrong)."""
        shipped = os.path.join(root, "config", "watch")
        if not os.path.isdir(os.path.join(root, "config")):
            return None
        bad = []
        files = sorted(glob.glob(os.path.join(shipped, "*.json")))
        for p in files:
            s = json.load(open(p))
            try:
                argv = shlex.split(s.get("check", ""))
            except ValueError:
                argv = []
            if (s.get("revert") != "tell" or (argv[:2] != ["cc-watch", "url"] and argv != ["lander-self", "sweep"])
                    or s.get("owner") != "#alerts"):
                bad.append(os.path.basename(p))
        return bool(files) and not bad, bad or "no specs in " + shipped

    # A repo that ships config/ must ship its host watchers: a missing config/watch fails rather than skipping.
    with tempfile.TemporaryDirectory(prefix="cc-watch-sc-") as t:
        bare = shipped_ok(t)
        os.makedirs(os.path.join(t, "config"))
        gone = shipped_ok(t)
        check("shipped host watchers: no config/ is a skip, a config/ with no watch dir fails",
              bare is None and gone is not None and not gone[0], (bare, gone))

    # The shipped specs for the box's own hosts parse, and each is a tell-only url watcher or the sweep of main.
    got = shipped_ok(os.path.dirname(os.path.dirname(os.path.dirname(tool))))
    if got is None:   # core published on its own carries no config/
        print("  skip shipped host watchers: no config/ beside core")
    else:
        check("shipped host watchers: present, tell-only url checks or the sweep, owner #alerts", got[0], got[1])

    print(f"cc-watch selfcheck: {n[0]} passed, {n[1]} failed")
    return 1 if n[1] else 0
