# cc-usage-poll's selfcheck: the cases behind `cc-usage-poll selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-usage-poll execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    global _TEST_ORIGIN
    import contextlib, http.server, io, shutil, subprocess, tempfile, threading
    n = bad = 0

    def t(name, got, want):
        nonlocal n, bad
        n += 1
        if got != want:
            bad += 1
            print(f"FAIL {name}: got {got!r}, want {want!r}")

    # a fake endpoint on loopback: no network. /api/oauth/usage answers with reply[0] (status, body, headers);
    # /elsewhere is where a redirect points. Every request's path and headers are kept
    reply, seen = [None], []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
            code, body, hdrs = reply[0] if self.path == "/api/oauth/usage" else (200, "{}", {})
            self.send_response(code)
            for k, v in hdrs.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{srv.server_port}"
    base = tempfile.mkdtemp(prefix="cc-usage-poll-sc.")
    secret = "sk-ant-oat01-SELFCHECK-NOT-A-TOKEN"
    os.makedirs(f"{base}/claude")
    keep = {k: os.environ.get(k) for k in ("CC_USAGE_DIR", "CLAUDE_CONFIG_DIR", "CC_USAGE_TIMEOUT")}
    errs = io.StringIO()

    def creds(expires_in):
        json.dump({"claudeAiOauth": {"accessToken": secret, "expiresAt": int((time.time() + expires_in) * 1000)}},
                  open(f"{base}/claude/.credentials.json", "w"))

    def run():
        with contextlib.redirect_stderr(errs), contextlib.redirect_stdout(errs):
            return poll()

    def read(name):
        try:
            return json.load(open(f"{base}/usage/{name}"))
        except OSError:
            return None

    try:
        # the fixed endpoint: no environment or argument moves it, and it is https
        env = dict(os.environ, CC_USAGE_URL=f"{origin}/api/oauth/usage")
        r = subprocess.run([sys.executable, "-c", f"import runpy; g = runpy.run_path({__file__!r}, run_name='x'); "
                            "print(g['opener']()[1])"], env=env, capture_output=True, text=True, timeout=30)
        t("a real run asks the fixed https Anthropic URL, whatever CC_USAGE_URL says",
          r.stdout.strip(), "https://api.anthropic.com/api/oauth/usage")

        _TEST_ORIGIN = origin
        os.environ.update(CC_USAGE_DIR=f"{base}/usage", CLAUDE_CONFIG_DIR=f"{base}/claude", CC_USAGE_TIMEOUT="5")
        creds(3600)
        reply[0] = (200, json.dumps({"five_hour": {"utilization": 64.0, "resets_at": "2026-10-19T03:00:00+00:00"},
                                     "seven_day": {"utilization": 21, "resets_at": "2026-10-23T00:00:00Z"},
                                     "seven_day_opus": None}), {})
        before = time.time()
        rc, d = run(), read("now.json") or {}
        t("good reply: exit 0", rc, 0)
        t("good reply: five_hour used% and resets_at as epoch",
          d.get("five_hour"), {"used_percentage": 64.0, "resets_at": 1792378800.0})
        t("good reply: seven_day too", d.get("seven_day"), {"used_percentage": 21.0, "resets_at": 1792713600.0})
        t("good reply: stamped with the time it was read", before - 1 <= d.get("at", 0) <= time.time(), True)
        h = seen[-1][1] if seen else {}
        t("request: the OAuth bearer and the oauth beta header",
          (h.get("authorization"), h.get("anthropic-beta")), (f"Bearer {secret}", "oauth-2025-04-20"))
        t("one request per run", len(seen), 1)

        good = open(f"{base}/usage/now.json").read()
        reply[0] = (500, '{"error": "boom"}', {})
        t("failure: exit 1", run(), 1)
        t("failure: now.json keeps the last good read", open(f"{base}/usage/now.json").read(), good)
        t("failure: error.json names the type and status, nothing else",
          {k: v for k, v in (read("error.json") or {}).items() if k != "at"}, {"error": "HTTPError", "status": 500})

        reply[0] = (200, "not json", {})
        t("a reply that is not JSON is a failure that keeps the old file",
          (run(), open(f"{base}/usage/now.json").read(), (read("error.json") or {}).get("error")),
          (1, good, "JSONDecodeError"))

        # a redirect is refused: the token never reaches the place it points to
        for code in (301, 302, 307, 308):
            reply[0] = (code, "", {"Location": f"{origin}/elsewhere"})
            k = len(seen)
            rc = run()
            t(f"a {code} is refused and not followed",
              (rc, [p for p, _ in seen[k:]], (read("error.json") or {}).get("status")),
              (1, ["/api/oauth/usage"], code))

        # a 429 waits out its Retry-After: runs before it ask nothing and change nothing
        reply[0] = (429, "", {"Retry-After": "120"})
        rc, e = run(), read("error.json") or {}
        t("429: exit 1, Retry-After kept as the time to wait until",
          (rc, e.get("status"), 119 <= e.get("retry_after", 0) - time.time() <= 121), (1, 429, True))
        reply[0] = (200, json.dumps({"five_hour": {"utilization": 70, "resets_at": None}}), {})
        k = len(seen)
        t("429: a run inside the wait skips, asks nothing, keeps both files",
          (run(), len(seen) - k, open(f"{base}/usage/now.json").read(), read("error.json")), (0, 0, good, e))
        e["retry_after"] = time.time() - 1
        json.dump(e, open(f"{base}/usage/error.json", "w"))
        t("429: once the wait has passed it asks again, and a good read removes error.json",
          (run(), len(seen) - k, os.path.exists(f"{base}/usage/error.json")), (0, 1, False))
        reply[0] = (429, "", {"Retry-After": "86400"})
        run()
        t("429: a Retry-After past RETRY_CAP waits RETRY_CAP",
          (read("error.json") or {}).get("retry_after", 0) - time.time() <= RETRY_CAP, True)
        os.unlink(f"{base}/usage/error.json")
        reply[0] = (429, "", {"Retry-After": "soon"})
        run()
        t("429: an unreadable Retry-After still waits a minute",
          55 <= (read("error.json") or {}).get("retry_after", 0) - time.time() <= 61, True)
        os.unlink(f"{base}/usage/error.json")

        creds(-60)
        k = len(seen)
        t("an expired token is a failure and asks nothing", (run(), len(seen) - k), (1, 0))
        files = "".join(open(os.path.join(dp, f)).read() for dp, _, fs in os.walk(f"{base}/usage") for f in fs)
        t("the token is never printed or written", secret in errs.getvalue() + files, False)
    finally:
        _TEST_ORIGIN = None
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        srv.shutdown()
        shutil.rmtree(base, ignore_errors=True)
    print(f"cc-usage-poll selfcheck: {n - bad} passed, {bad} failed")
    return 1 if bad else 0
