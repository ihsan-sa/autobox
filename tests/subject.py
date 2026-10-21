"""Fixtures for cc-subject selfcheck: real bwrap, a real proxy, a real network namespace. No API call is made and
nothing is spent: UPSTREAM points at FAKE, a plain-HTTP Messages API on the host's loopback that answers with the
usage a case sets, and the shipped UPSTREAM is asserted to be the API's one name over TLS."""
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time

CAP = {"SUBJECT_DAILY_USD": 10.0, "SUBJECT_MAX_HOURS": 1.0, "SUBJECT_CONCURRENT": 2,
       "SUBJECT_DISK_MB": 4096, "SUBJECT_DAILY_NET_MB": 16.0, "SUBJECT_KEEP_DAYS": 14,
       "SUBJECT_KEPT_MB": 8192}
COST = {"input_tokens": 1000, "output_tokens": 1400}   # $0.008 on haiku: (1000 * 1 + 1400 * 5) / 1e6


class Fake:
    """The Messages API, faked: every request it gets is kept in `log`; it answers an SSE stream (a JSON body when
    the request does not stream) carrying `usage`, its output_tokens never past the request's max_tokens as the real
    API's are not, or as `mode` says: "cut" ends the stream after message_start, "529" is an overload error.
    count_tokens answers `count` (None: usage's input_tokens), or a 500 when `count_fail`."""

    def __init__(self):
        self.log, self.mode, self.usage, self.lock = [], "ok", dict(COST), threading.Lock()
        self.count, self.count_fail = None, False
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                n = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(n)
                with fake.lock:
                    fake.log.append({"line": self.requestline, "body": body,
                                     "headers": [(k.lower(), v) for k, v in self.headers.items()]})
                try:
                    ask = json.loads(body)
                except ValueError:
                    ask = {}
                if "count_tokens" in self.path:
                    if fake.count_fail:
                        return self.send(500, "application/json", b'{"type":"error","error":{"type":"api_error"}}')
                    n = fake.usage["input_tokens"] if fake.count is None else fake.count
                    return self.send(200, "application/json", json.dumps({"input_tokens": n}).encode())
                if fake.mode == "slow":   # the whole answer is made before its head goes out, as a JSON one is
                    time.sleep(1.0)
                if fake.mode == "529":
                    return self.send(529, "application/json", b'{"type":"error","error":{"type":"overloaded_error"}}')
                model, u = ask.get("model"), dict(fake.usage)
                if type(ask.get("max_tokens")) is int:
                    u["output_tokens"] = min(u["output_tokens"], ask["max_tokens"])
                if not ask.get("stream"):
                    return self.send(200, "application/json", json.dumps(
                        {"id": "msg_x", "type": "message", "model": model, "content": [], "usage": u}).encode())
                ev = [{"type": "message_start", "message": {"id": "msg_x", "type": "message", "model": model,
                                                            "usage": {"input_tokens": u["input_tokens"], "output_tokens": 1}}},
                      {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "PONG"}},
                      {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": u["output_tokens"]}},
                      {"type": "message_stop"}]
                if fake.mode == "cut":
                    self.send_response(200)
                    self.send_header("content-type", "text/event-stream")
                    self.send_header("connection", "close")
                    self.end_headers()
                    self.wfile.write(f"event: message_start\ndata: {json.dumps(ev[0])}\n\n".encode())
                    self.close_connection = True
                    return
                data = b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in ev)
                self.send(200, "text/event-stream", data)

            def send(self, code, ctype, data):
                self.send_response(code)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def reset(self):
        with self.lock:
            self.log.clear()
        self.mode, self.usage, self.count, self.count_fail = "ok", dict(COST), None, False

    def priced(self):
        """The requests that reached the API's priced path: count_tokens, the proxy's or the subject's, is free."""
        with self.lock:
            return [r for r in self.log if "count_tokens" not in r["line"]]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


FAKE = SHIPPED = None

# What runs inside to talk to the API: raw sockets to the forwarder, so every byte of each request is the case's.
CLIENT = r'''
import json, socket, time
def req(raw):
    try:
        c = socket.create_connection(("127.0.0.1", 3128), timeout=30)
        c.sendall(raw)
        data = b""
        while True:
            d = c.recv(65536)
            if not d: break
            data += d
        c.close()
        return (data.split(b" ", 2)[1].decode() if data.startswith(b"HTTP/") else "none"), data
    except OSError as e:
        return type(e).__name__, b""
def post(path="/v1/messages?beta=true", ask=None):
    body = json.dumps(ask or {"model": "claude-haiku-4-5", "max_tokens": 2000, "stream": True,
                              "messages": [{"role": "user", "content": "hi"}]}).encode()
    return req(b"POST " + path.encode() + b" HTTP/1.1\r\nHost: 127.0.0.1:3128\r\nAuthorization: Bearer subject-placeholder"
               b"\r\nx-api-key: subject-key\r\nCookie: c=subject-cookie\r\nContent-Type: application/json\r\n"
               b"anthropic-version: 2023-06-01\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
'''

NET = CLIENT + r'''
out = {}
def tcp(host, port):
    try:
        socket.create_connection((host, port), timeout=3).close(); return "connected"
    except OSError as e:
        return type(e).__name__
out["raw_internet"] = tcp("1.1.1.1", 443)
out["raw_host_loopback"] = tcp("127.0.0.1", @API@)
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.sendto(b"x", ("8.8.8.8", 53)); out["udp"] = "sent"
except OSError as e:
    out["udp"] = type(e).__name__
s, d = post(); out["post"] = [s, b"message_stop" in d]
out["count"] = post("/v1/messages/count_tokens")[0]
out["connect"] = req(b"CONNECT api.anthropic.com:443 HTTP/1.1\r\nHost: api.anthropic.com:443\r\n\r\n")[0]
out["get"] = req(b"GET /v1/messages HTTP/1.1\r\nHost: x\r\n\r\n")[0]
out["other_path"] = post("/v1/models")[0]
out["other_query"] = post("/v1/messages?beta=true&x=1")[0]
out["absolute"] = post("http://api.anthropic.com/v1/messages")[0]
out["absolute_host"] = post("http://127.0.0.1:@API@/v1/messages")[0]
json.dump(out, open("/work/net.json", "w"))
'''

FILES = r'''
import json, os
out = {}
def read(p):
    try:
        return open(p).read()[:200]
    except OSError as e:
        return type(e).__name__
out["input"] = read("/work/data.txt")
out["escape_link"] = read("/work/escape")
out["fixture_home"] = os.path.exists(@FX@)
out["real_home"] = os.path.exists(@HOME@)
out["secret"] = read(@SECRET@)
out["passwd"] = read("/etc/passwd")
out["cred_file"] = os.path.exists("/home/subject/.claude/.credentials.json")
out["env"] = dict(os.environ)
out["etc"] = sorted(os.listdir("/etc"))
found = []
for top in ("/home/subject", "/work", "/tmp", "/run", "/etc", "/opt"):
    for d, _, names in os.walk(top):
        for n in names:
            try:
                data = open(os.path.join(d, n), "rb").read(1 << 20)
            except OSError:
                continue
            if b"fixture-access" in data or b"FIXTURE-REFRESH" in data:
                found.append(os.path.join(d, n))
out["found"] = found
json.dump(out, open("/work/files.json", "w"))
'''

# Posts until refused for good, keeping each status, then waits to be killed.
LOOP = CLIENT + r'''
got = []
for i in range(@N@):
    got.append(post()[0])
    json.dump(got, open("/work/loop.json", "w"))
    time.sleep(@GAP@)
time.sleep(60)
'''


def loop(n=12, gap=0.0):
    return ["/usr/bin/python3", "-c", LOOP.replace("@N@", str(n)).replace("@GAP@", str(gap))]


def check(ok, what):
    if not ok:
        raise AssertionError(what)
    print(f"  ok  {what}")


def fixture(m, cred=None, h="fx"):
    """A fresh fake host: HOME with a member dir, a login, a workspace tree and a secret beside it."""
    root = Path(tempfile.mkdtemp(prefix="cc-subject-"))
    m.HOME = root
    (root / ".cc/members" / h).mkdir(parents=True)
    (root / "dev" / h / "in").mkdir(parents=True)
    (root / ".cc/worktrees" / h / "t1").mkdir(parents=True)
    (root / ".ssh").mkdir()
    (root / ".ssh/id").write_text("HOST-SECRET")
    if cred is None:
        cred = {"claudeAiOauth": {"accessToken": "fixture-access", "refreshToken": "FIXTURE-REFRESH",
                                  "expiresAt": int((time.time() + 86400) * 1000)}}
    if cred:
        (root / ".cc/members" / h / "credentials.json").write_text(json.dumps(cred))
    FAKE.reset()
    return root, h


def run(m, h, argv, cap=CAP, src="", hours=1):
    res = m.start(h, {"op": "run", "argv": argv, "input": src, "hours": hours}, cap, spawn=False)
    assert res.get("ok"), res
    return res["run"], m.supervise(h, res["run"], cap)


def ledger(m, h):
    return m.Ledger(h, m.today()).read()


def case_net(m):
    root, h = fixture(m)
    rid, st = run(m, h, ["/usr/bin/python3", "-c", NET.replace("@API@", str(FAKE.port))])
    out = json.loads((m.subjects(h) / rid / "work/net.json").read_text())
    check(st["state"] == "done" and st["exit"] == 0, f"net subject ran to the end ({st['state']}, exit {st['exit']})")
    check(out["raw_internet"] != "connected", f"a raw socket to the internet fails ({out['raw_internet']})")
    check(out["raw_host_loopback"] != "connected", f"the host's own loopback, the fake API's port, is not the subject's ({out['raw_host_loopback']})")
    check(out["udp"] != "sent", f"a UDP datagram out has no route ({out['udp']})")
    check(out["post"] == ["200", True] and out["count"] == "200", f"POST /v1/messages and count_tokens reach the API ({out['post']}, {out['count']})")
    for k in ("connect", "get", "other_path", "other_query", "absolute", "absolute_host"):
        check(out[k] == "403", f"{k} is refused with 403 ({out[k]})")
    log = FAKE.log
    check([r["line"] for r in log] == ["POST /v1/messages/count_tokens?beta=true HTTP/1.1", "POST /v1/messages?beta=true HTTP/1.1",
                                       "POST /v1/messages/count_tokens HTTP/1.1"],
          f"the API saw the proxy's count of the priced call, then the two allowed requests, and nothing else ({[r['line'] for r in log]})")
    counted = json.loads(log[0]["body"])
    check(set(counted) <= set(m.COUNT_KEYS) and "max_tokens" not in counted and counted["messages"] == [{"role": "user", "content": "hi"}],
          f"the proxy's count carries only the fields count_tokens takes ({sorted(counted)})")
    for r in log:
        hd = dict(r["headers"])
        check(hd.get("authorization") == "Bearer fixture-access" and "x-api-key" not in hd and "cookie" not in hd,
              "the proxy put the workspace's token on, and the subject's key and cookie did not go out")
        check(not any("subject-" in v for _, v in r["headers"]), "no header the subject set to its own placeholder went out")
        check(hd.get("accept-encoding") == "identity" and "oauth-2025-04-20" in hd.get("anthropic-beta", "")
              and hd.get("host") == "127.0.0.1", f"identity encoding, the oauth beta and the upstream's Host ({hd})")
    want = m.price("claude-haiku-4-5", COST)
    check(abs(st["usd"] - want) < 1e-9 and abs(ledger(m, h)["usd"] - want) < 1e-9,
          f"the one priced call is settled from its usage, in the run and in the day's ledger (${st['usd']})")
    check(SHIPPED == ("api.anthropic.com", 443, True), "the shipped upstream is the model API, over TLS, and nothing else")
    shutil.rmtree(root)


def case_files(m):
    root, h = fixture(m)
    src = root / "dev" / h / "in"
    (src / "data.txt").write_text("INPUT")
    (src / "escape").symlink_to(root / ".ssh/id")
    script = (FILES.replace("@FX@", repr(str(root))).replace("@HOME@", repr(str(m.REALHOME)))
              .replace("@SECRET@", repr(str(root / ".ssh/id"))))
    rid, st = run(m, h, ["/usr/bin/python3", "-c", script], src=str(src))
    rd = m.subjects(h) / rid
    out = json.loads((rd / "work/files.json").read_text())
    check(st["state"] == "done", f"files subject ran to the end ({st['state']})")
    check(out["input"] == "INPUT", "the copied input is readable in /work")
    check(out["escape_link"] == "FileNotFoundError", "a link in the input that points out of it reaches nothing")
    check(not out["fixture_home"] and not out["real_home"], "neither the workspace's host tree nor the host's home exists inside")
    check(out["secret"] == "FileNotFoundError", "a host file by its path is absent")
    check(out["passwd"].count("\n") == 1 and out["passwd"].startswith("subject:"), "/etc/passwd is the generated one line")
    check("ld.so.cache" in out["etc"] and "shadow" not in out["etc"] and "hostname" not in out["etc"], "/etc holds only what was named")
    check(not out["cred_file"] and out["found"] == [], f"no credential file inside, and no file holds the token ({out['found']})")
    env = out["env"]
    check(not [k for k in env if k not in ("HOME", "USER", "PATH", "TMPDIR", "LANG", "ANTHROPIC_BASE_URL",
                                           "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
                                           "CC_SUBJECT_RUN", "PWD", "SHLVL", "_", "LC_CTYPE")],
          f"the environment is the one the boundary set, with no proxy variable ({sorted(env)})")
    check(env.get("ANTHROPIC_BASE_URL") == "http://127.0.0.1:3128" and env.get("CLAUDE_CODE_OAUTH_TOKEN") == "subject-placeholder"
          and not any("fixture-access" in v or "FIXTURE-REFRESH" in v for v in env.values()),
          "the API is the loopback forwarder and the token is a placeholder")
    check(not (rd / "cred").exists(), "the run dir holds no credential on the host either")
    check(not (rd / "in").exists(), "the run's host-side copy of the input is gone once it has ended")
    check((rd / "work/escape").is_symlink() and os.readlink(rd / "work/escape") == str(root / ".ssh/id"),
          "the input's link came back out as the same link, not as what it names")
    check((src / "data.txt").read_text() == "INPUT", "the workspace's own copy is untouched")
    shutil.rmtree(root)


def case_tree(m):
    root, h = fixture(m)
    (root / "outside").mkdir()
    (root / "dev" / h / "link").symlink_to(root / "outside")
    check(m.tree_ok(h, str(root / "dev" / h / "in")) == (str(root / "dev" / h / "in"), ""), "a directory of the workspace is accepted")
    check(m.tree_ok(h, str(root / ".cc/worktrees" / h / "t1"))[0], "a track worktree of the workspace is accepted")
    check(m.tree_ok(h, str(root / "outside"))[0] is None, "a directory outside the workspace is refused")
    check(m.tree_ok(h, str(root / "dev" / h / "link"))[0] is None, "a link out of the workspace is refused")
    check(m.tree_ok(h, "dev/fx/in")[0] is None, "a relative path is refused")
    check(m.tree_ok(h, str(root / "dev" / h / "in") + "\0x")[0] is None, "a path with a NUL byte is refused, not raised on")
    res = m.start(h, {"op": "run", "argv": ["true"], "input": str(root / "outside")}, CAP, spawn=False)
    check(not res["ok"] and not (root / ".cc/members" / h / "subjects").exists() or not list((root / ".cc/members" / h / "subjects").iterdir()),
          "a refused input makes no run")
    shutil.rmtree(root)


def case_caps(m):
    root, h = fixture(m)
    many = [m.start(h, {"op": "run", "argv": ["true"]}, dict(CAP, SUBJECT_CONCURRENT=100), spawn=False) for _ in range(25)]
    check(all(r["ok"] for r in many), f"no count of runs a day: 25 start ({[r.get('error') for r in many if not r['ok']]})")
    shutil.rmtree(root)
    root, h = fixture(m)
    cap = dict(CAP, SUBJECT_CONCURRENT=2)
    first = m.start(h, {"op": "run", "argv": ["true"]}, cap, spawn=False)
    third = m.start(h, {"op": "run", "argv": ["true"]}, cap, spawn=False)   # the first is still "starting": one live
    fourth = m.start(h, {"op": "run", "argv": ["true"]}, cap, spawn=False)
    check(third["ok"] and not fourth["ok"] and "at once" in fourth["error"], "the concurrency cap counts live runs")
    big = m.start(h, {"op": "run", "argv": ["true"], "hours": 2}, CAP, spawn=False)
    check(not big["ok"] and "--hours" in big["error"], "a run longer than SUBJECT_MAX_HOURS is refused")
    shutil.rmtree(root)
    root, h = fixture(m)
    src = root / "dev" / h / "in"
    (src / "locked").write_text("x")
    (src / "locked").chmod(0)
    (src / "a.txt").write_text("partial")
    bad = m.start(h, {"op": "run", "argv": ["true"], "input": str(src)}, CAP, spawn=False)
    check(not bad["ok"], f"a run whose input copy fails is refused ({bad.get('error')})")
    (src / "locked").chmod(0o600)
    rds = [m.subjects(h) / r for r, _ in m.runs_of(h)]
    check(len(rds) == 1 and m.runs_of(h)[0][1]["state"] == "failed" and not (rds[0] / "in").exists()
          and not (rds[0] / "work").exists(), f"and it leaves no input copy and no partial /work ({[sorted(os.listdir(r)) for r in rds]})")
    shutil.rmtree(root)
    root, h = fixture(m)
    led = m.Ledger(h, m.today())
    with led.edit() as d:
        d["usd"] = 9.0
        d["held"]["other/1"] = 1.0
    r = m.start(h, {"op": "run", "argv": ["true"]}, CAP, spawn=False)
    check(not r["ok"] and "spent" in r["error"], "no run starts once the day's ledger, settled and held, reaches the dollar cap")
    with led.edit() as d:
        d["usd"], d["held"], d["bytes"] = 0.0, {}, m.net_cap(CAP)
    r = m.start(h, {"op": "run", "argv": ["true"]}, CAP, spawn=False)
    check(not r["ok"] and "through the proxy" in r["error"], "nor once its bytes reach the volume cap")
    led.path.write_text("{not json")
    r = m.start(h, {"op": "run", "argv": ["true"]}, CAP, spawn=False)
    check(not r["ok"] and "will not read" in r["error"], f"and a ledger that will not read refuses the run ({r.get('error')})")
    led.path.write_text(json.dumps({"usd": -5, "held": {}, "bytes": 0}))
    r = m.start(h, {"op": "run", "argv": ["true"]}, CAP, spawn=False)
    check(not r["ok"] and "will not read" in r["error"], "as does one whose figures are not a ledger's (a negative spend)")
    shutil.rmtree(root)


def case_spend(m):
    """A subject that loops API calls: each settles at $0.008. count_tokens says 1000 in, so the hold is
    $0.002044 + $0.000005 a token out, $0.012044 at max_tokens 2000. With a $0.05 cap five go through whole, the sixth
    is cut to max_tokens 1591 ($0.010 left), and the seventh does not fit even at max_tokens 1 — 403, run killed."""
    root, h = fixture(m)
    cap = dict(CAP, SUBJECT_DAILY_USD=0.05)
    rid, st = run(m, h, loop(), cap=cap)
    got = json.loads((m.subjects(h) / rid / "work/loop.json").read_text())
    check(got[:7] == ["200"] * 6 + ["403"], f"six calls go through and the seventh is refused ({got})")
    check(st["state"] == "killed" and "daily cap" in st["why"], f"and the run is killed ({st['why']})")
    led = ledger(m, h)
    check(abs(led["usd"] - 0.048) < 1e-9 and led["usd"] <= 0.05 and not led["held"],
          f"the day's ledger holds the six settled calls, under the cap, nothing left in flight (${led['usd']})")
    check(abs(st["usd"] - 0.048) < 1e-9, f"and the run's own figure is the same (${st['usd']})")
    sent = [json.loads(r["body"])["max_tokens"] for r in FAKE.priced()]
    check(sent == [2000] * 5 + [1591], f"the refused call never reached the API, and the sixth went out cut ({sent})")
    shutil.rmtree(root)


def unit_req(path, raw):
    c = socket.socket(socket.AF_UNIX)
    c.settimeout(30)
    c.connect(str(path))
    try:
        c.sendall(raw)
    except OSError:
        pass
    data = b""
    try:
        while True:
            d = c.recv(65536)
            if not d:
                break
            data += d
    except OSError:
        pass
    c.close()
    return (int(data.split(b" ", 2)[1]) if data.startswith(b"HTTP/") else 0), data


def unit_post(path, ask=None, body=None, head=b"", target=b"/v1/messages?beta=true"):
    if body is None:
        body = json.dumps(ask or {"model": "claude-haiku-4-5", "max_tokens": 2000, "stream": True,
                                  "messages": [{"role": "user", "content": "hi"}]}).encode()
    raw = (b"POST " + target + b" HTTP/1.1\r\nHost: x\r\n" + head
           + (b"" if b"content-length" in head.lower() or b"transfer-encoding" in head.lower()
              else b"Content-Length: " + str(len(body)).encode() + b"\r\n") + b"\r\n" + body)
    return unit_req(path, raw)


def case_proxy_units(m):
    """The proxy alone, on the host: what it prices, what it holds back, what it refuses."""
    root, h = fixture(m)
    m.subjects(h).mkdir()
    d = Path(tempfile.mkdtemp(prefix="cc-px-"))
    cap = dict(CAP, SUBJECT_DAILY_USD=1.0)
    led = m.Ledger(h, "2026-01-01")
    px = m.Proxy(d / "p.sock", d / "net.log", led, "unit", cap, m.member_dir(h) / "credentials.json")
    sock = d / "p.sock"
    hk = {"model": "claude-haiku-4-5", "max_tokens": 2000, "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    body = json.dumps(hk).encode()
    R = m.reserve(hk, len(body))
    check(abs(R - (len(body) + 8192 + 2000 * 5) / 1e6) < 1e-12, f"with no count, the hold is every body byte a token plus margin, all of max_tokens out (${R:.6f})")
    Rc = m.reserve(hk, len(body), 1000)
    check(abs(Rc - (1000 + 20 + 1024 + 2000 * 5) / 1e6) < 1e-12, f"with count_tokens' 1000, the hold is that count plus 2% and 1024 (${Rc:.6f})")

    def spent(fn):
        before = led.read()["usd"]
        res = fn()
        return res, led.read()["usd"] - before

    (s, data), usd = spent(lambda: unit_post(sock, hk))
    check(s == 200 and b"message_stop" in data and abs(usd - 0.008) < 1e-9, f"an SSE answer is priced from message_start + message_delta (${usd:.6f})")
    check(led.read()["bytes"] == m.BYTES_BLOCK and px.moved < m.BYTES_BLOCK, "bytes are taken from the day a block at a time")
    (s, _), usd = spent(lambda: unit_post(sock, dict(hk, stream=False)))
    check(s == 200 and abs(usd - 0.008) < 1e-9, f"a JSON answer is priced from its usage (${usd:.6f})")
    FAKE.mode = "cut"
    (s, _), usd = spent(lambda: unit_post(sock, hk))
    check(abs(usd - Rc) < 1e-9, f"a stream cut before message_stop settles at the hold, R (${usd:.6f})")
    FAKE.mode = "slow"

    def hang_up():   # send a JSON call, then close before the answer has come back
        raw = json.dumps(dict(hk, stream=False)).encode()
        c = socket.socket(socket.AF_UNIX)
        c.connect(str(sock))
        c.sendall(b"POST /v1/messages HTTP/1.1\r\nHost: x\r\nContent-Length: %d\r\n\r\n" % len(raw) + raw)
        time.sleep(0.3)
        c.close()
        time.sleep(1.5)
    _, usd = spent(hang_up)
    check(abs(usd - Rc) < 1e-9 and not led.read()["held"],
          f"a subject that hangs up before the answer is settled at the hold, R, not at nothing (${usd:.6f})")
    FAKE.mode = "529"
    (s, _), usd = spent(lambda: unit_post(sock, hk))
    check(s == 529 and usd == 0, "an error answer is relayed and costs nothing")
    FAKE.mode = "ok"
    unk = dict(hk, model="no-such-model")
    check(m.reserve(unk, len(body)) > R and m.worst_rates("no-such-model") == (10.0, 50.0),
          "a model with no rate is held at the dearest row there is")
    (s, _), usd = spent(lambda: unit_post(sock, unk))
    check(s == 200 and abs(usd - m.price("claude-fable-5-1", COST)) < 1e-9 and usd > 0.008,
          f"and settled at the dearest row, not at nothing (${usd:.6f})")
    check(abs(m.cost("claude-haiku-4-5", dict(COST, input_tokens=300000)) - 2 * m.price("claude-haiku-4-5", dict(COST, input_tokens=300000))) < 1e-12
          and abs(m.cost("claude-haiku-4-5", dict(COST, server_tool_use={"web_search_requests": 3})) - 0.038) < 1e-9,
          "past 200k input a call costs twice, and each web search adds a cent")
    doc = dict(hk, messages=[{"role": "user", "content": [{"type": "document", "source": {"type": "file", "file_id": "f"}}]}])
    check(m.reserve(doc, 200) > 2, "a request naming a document or file is held at a full context")
    n = len(FAKE.priced())
    refusals = [
        ("mcp_servers", 403, dict(body=json.dumps(dict(hk, mcp_servers=[{"type": "url", "url": "http://x"}])).encode())),
        ("a server tool", 403, dict(body=json.dumps(dict(hk, tools=[{"type": "web_search_20250305", "name": "web_search"}])).encode())),
        ("no max_tokens", 403, dict(body=json.dumps({k: v for k, v in hk.items() if k != "max_tokens"}).encode())),
        ("chunked", 411, dict(body=b"", head=b"Transfer-Encoding: chunked\r\n")),
        ("two Content-Lengths", 411, dict(body=b"{}", head=b"Content-Length: 2\r\nContent-Length: 3\r\n")),
        ("an oversize body", 413, dict(body=b"", head=b"Content-Length: %d\r\n" % (m.BODY_MAX + 1))),
        ("an oversize head", 431, dict(body=b"{}", head=b"X-Pad: " + b"a" * (m.HEAD_MAX + 10) + b"\r\n")),
        ("a non-JSON body", 400, dict(body=b"\xff\xfe not json")),
        ("a key twice", 400, dict(body=json.dumps(hk).replace('"max_tokens": 2000', '"max_tokens": 1000000, "max_tokens": 1').encode())),
        ("deep nesting", 400, dict(body=b"[" * 200000 + b"]" * 200000)),
        ("a header with a bare LF", 400, dict(body=b"{}", head=b"X-A: a\nX-B: b\r\n")),
    ]
    for what, code, kw in refusals:
        s, _ = unit_post(sock, **kw)
        check(s == code, f"{what} is refused with {code} ({s})")
    s, _ = unit_req(sock, b"POST /v1/messages HTTP/1.1\r\nHost: x\r\n\r\n")
    check(s == 411, f"no Content-Length is refused with 411 ({s})")
    s, _ = unit_post(sock, dict(hk, tools=[{"type": "bash_20250124", "name": "bash"}, {"name": "Read", "input_schema": {}}]))
    check(s == 200 and len(FAKE.priced()) == n + 1, "client tools, custom or versioned, go through; none of the refused reached the API")
    cred = m.member_dir(h) / "credentials.json"
    real = cred.with_name("real.json")
    cred.rename(real)
    cred.symlink_to(real)
    s, _ = unit_post(sock, hk)
    check(s == 503, f"a credentials.json that is a link is no login: 503 ({s})")
    cred.unlink()
    cred.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok\r\nX-Evil: 1"}}))
    s, _ = unit_post(sock, hk)
    check(s == 503, f"nor is a token that is not one: 503 ({s})")
    real.rename(cred)
    check(len(FAKE.priced()) == n + 1, "and neither reached the API")
    # 17 connections: the sixteenth slot is the last; the next is closed unread
    held = [socket.socket(socket.AF_UNIX) for _ in range(m.Proxy.MAX)]
    for c in held:
        c.connect(str(sock))
    time.sleep(0.3)
    extra = socket.socket(socket.AF_UNIX)
    extra.connect(str(sock))
    extra.settimeout(5)
    check(m.Proxy.MAX == 16 and extra.recv(10) == b"", "past 16 connections at once the next is closed")
    for c in held + [extra]:
        c.close()
    time.sleep(0.3)
    # in flight: a hold another run has open makes this one wait, then 429; once it settles this one goes
    with led.edit() as dd:
        dd["held"]["other/1"] = 1.0 - dd["usd"] - Rc / 2
    was = m.WAIT_MAX
    m.WAIT_MAX = 1.0
    try:
        s, _ = unit_post(sock, hk)
        check(s == 429 and px.fatal is None, f"a call that fits only once others settle waits, then gets 429 ({s})")
        threading.Timer(0.3, lambda: led.settle("other/1", 0.0)).start()
        s, _ = unit_post(sock, hk)
        check(s == 200, f"and goes through when they settle within the wait ({s})")
    finally:
        m.WAIT_MAX = was
    fixed, per_out = m.hold_terms(hk, len(body), 1000)
    with led.edit() as dd:
        dd["usd"] = 1.0 - (fixed + per_out) / 2   # not even max_tokens 1 fits: the day is spent
    s, _ = unit_post(sock, hk)
    check(s == 403 and "daily cap" in (px.fatal or ""), f"a call that does not fit even with nothing in flight: 403 and the run marked to end ({px.fatal})")
    s, _ = unit_post(sock, None, body=b"{}", target=b"/v1/messages/count_tokens")
    check(s == 403, "and after that even a free call is refused")
    px.stop()
    check(led.read()["bytes"] == px.moved and not led.read()["held"], f"at the end the unused bytes go back: the day holds what moved ({px.moved})")
    bad = m.Ledger(h, "2026-01-02")
    bad.dir.mkdir(exist_ok=True)
    bad.path.write_text('{"usd": "lots"}')
    px2 = m.Proxy(d / "q.sock", d / "net.log", bad, "unit2", cap, cred)
    s, _ = unit_post(d / "q.sock", hk)
    check(s == 403 and "will not read" in (px2.fatal or ""), f"a ledger that will not read refuses the call and ends the run ({s})")
    px2.stop()
    argv = m.supervisor_argv(h, "r")
    check(argv[:3] == ["systemd-run", "--user", "--scope"] and "MemoryMax=2G" in argv and "MemorySwapMax=0" in argv,
          "the supervisor runs in a scope of its own, at most 2G and no swap")
    shutil.rmtree(d)
    shutil.rmtree(root)


def last_sent():
    """The body of the last priced request the API saw, or {} if none did."""
    got = FAKE.priced()
    return json.loads(got[-1]["body"]) if got else {}


def case_count(m):
    """The hold from count_tokens' exact input, max_tokens cut to what the day has left, and the run killed only
    once not even max_tokens 1 fits."""
    root, h = fixture(m)
    m.subjects(h).mkdir()
    d = Path(tempfile.mkdtemp(prefix="cc-px-"))
    cap = dict(CAP, SUBJECT_DAILY_USD=10.0)
    led = m.Ledger(h, "2026-01-03")
    px = m.Proxy(d / "p.sock", d / "net.log", led, "cnt", cap, m.member_dir(h) / "credentials.json")
    sock = d / "p.sock"
    # an Opus subject at a 100k-token context: ~400 KB of body, cache_control, max_tokens 32000
    big = {"model": "claude-opus-5", "max_tokens": 32000, "stream": True,
           "system": [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}],
           "messages": [{"role": "user", "content": "x" * 400000}]}
    n = len(json.dumps(big).encode())
    FAKE.count, FAKE.usage = 100000, {"input_tokens": 100000, "output_tokens": 500}
    check(m.reserve(big, n) > 10 and m.reserve(big, n, 100000) < 10,
          f"the body's estimate alone holds more than the $10 day (${m.reserve(big, n):.2f}); the exact count does not (${m.reserve(big, n, 100000):.2f})")
    s, _ = unit_post(sock, big)
    sent = last_sent()
    check(s == 200 and px.fatal is None and sent["max_tokens"] == 32000 and led.read()["usd"] <= 10,
          f"so it goes out whole, held at the counted input ({s}, ${led.read()['usd']:.4f})")
    FAKE.reset()
    hk = {"model": "claude-haiku-4-5", "max_tokens": 2000, "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    body = json.dumps(hk).encode()
    fixed, per_out = m.hold_terms(hk, len(body), 1000)
    FAKE.usage = {"input_tokens": 1000, "output_tokens": 2000}
    with led.edit() as dd:
        dd["usd"] = 10.0 - fixed - 600.5 * per_out   # room for max_tokens 600, not 2000, and nothing in flight
    s, data = unit_post(sock, hk)
    sent = last_sent()
    check(s == 200 and px.fatal is None and sent["max_tokens"] == 600
          and {k: v for k, v in sent.items() if k != "max_tokens"} == {k: v for k, v in hk.items() if k != "max_tokens"},
          f"a call that does not fit whole goes out with max_tokens cut to 600, the rest of its body as it was ({s}, {sent.get('max_tokens')})")
    check(led.read()["usd"] <= 10.0 and not led.read()["held"], f"and what it settles at keeps the day under its cap (${led.read()['usd']:.6f})")
    line = json.loads((d / "net.log").read_text().splitlines()[-1])
    check(line.get("max_tokens") == [2000, 600] and line.get("counted") == 1000, f"net.log says it was cut, and the count ({line})")
    with led.edit() as dd:
        dd["usd"] = 10.0 - fixed - 600.5 * per_out
    think = dict(hk, thinking={"type": "enabled", "budget_tokens": 1024})
    k = len(FAKE.priced())
    s, _ = unit_post(sock, think)
    check(s == 429 and px.fatal is None and len(FAKE.priced()) == k,
          f"one whose thinking budget leaves no max_tokens that fits gets 429, and the run goes on ({s}, {px.fatal})")
    FAKE.count_fail, FAKE.mode = True, "cut"
    with led.edit() as dd:
        dd["usd"] = 0.0
    before = led.read()["usd"]
    s, _ = unit_post(sock, hk)
    usd = led.read()["usd"] - before
    check(abs(usd - m.reserve(hk, len(body))) < 1e-9 and abs(usd - m.reserve(hk, len(body), 1000)) > 1e-6,
          f"when count_tokens fails the hold falls back to the body's estimate (${usd:.6f})")
    FAKE.count_fail, FAKE.mode = False, "ok"
    with led.edit() as dd:
        dd["usd"] = 10.0 - (fixed + per_out) / 2
    s, _ = unit_post(sock, hk)
    check(s == 403 and "daily cap" in (px.fatal or ""), f"only once not even max_tokens 1 fits is the run marked to end ({s}, {px.fatal})")
    px.stop()
    shutil.rmtree(d)
    shutil.rmtree(root)


def case_kept(m):
    """What a workspace keeps of its runs has a cap: past SUBJECT_KEPT_MB no run starts, and the refusal is not a run.
    A link in a kept /work counts as a link, not as what it names."""
    root, h = fixture(m)
    sub = m.subjects(h)
    rd = sub / "20261001-000000-dddddd"
    (rd / "work").mkdir(parents=True)
    (rd / "status.json").write_text(json.dumps({"run": rd.name, "argv": ["true"], "state": "done", "hours": 1,
                                                "started": m.now(), "ended": m.now()}))
    (rd / "work/a").write_bytes(os.urandom(2 << 20))
    (root / "outside").write_bytes(os.urandom(4 << 20))
    (rd / "work/link").symlink_to(root / "outside")
    cap = dict(CAP, SUBJECT_KEPT_MB=3)
    first = m.start(h, {"op": "run", "argv": ["true"]}, cap, spawn=False)
    check(first["ok"], f"2 MB kept, and a link to 4 MB outside, is under a 3 MB cap ({first})")
    (rd / "work/b").write_bytes(os.urandom(2 << 20))
    runs = len(m.runs_of(h))
    res = m.start(h, {"op": "run", "argv": ["true"]}, cap, spawn=False)
    check(not res["ok"] and "SUBJECT_KEPT_MB" in res["error"], f"past it no run starts ({res.get('error')})")
    check(len(m.runs_of(h)) == runs and m.day_totals(h, m.today())[0] == runs,
          "and the refusal made no run, so it is not one of the day's")
    check(m.DEFAULTS["SUBJECT_KEPT_MB"] == 8192, "the shipped cap is 8192 MB a workspace")
    shutil.rmtree(root)


def case_entries(m):
    """Empty files cost a tmpfs nothing but cost the host an inode each. A /work of more than WORK_ENTRIES entries is
    not copied out at all, one under it is, and the kept cap charges every entry at least ENTRY_BYTES."""
    root, h = fixture(m)
    was = m.WORK_ENTRIES
    m.WORK_ENTRIES = 50
    try:
        many = "import os\nfor i in range(60): open(f'/work/e{i}', 'w').close()"
        rid, st = run(m, h, ["/usr/bin/python3", "-c", many])
        rd = m.subjects(h) / rid
        check("files and dirs" in st.get("results", "")
              and not (rd / "work").exists(), f"60 empty files past a cap of 50 are not copied out ({st.get('results')})")
        rid, st = run(m, h, ["/usr/bin/python3", "-c", many.replace("60", "40")])
        check("results" not in st and len(os.listdir(m.subjects(h) / rid / "work")) == 40,
              f"40 under it are ({st.get('results')})")
    finally:
        m.WORK_ENTRIES = was
    check(m.WORK_ENTRIES == 100_000, "the shipped cap is 100000 entries a run")
    shutil.rmtree(root)
    root, h = fixture(m)
    rd = m.subjects(h) / "20261001-000000-eeeeee"
    (rd / "work").mkdir(parents=True)
    (rd / "status.json").write_text(json.dumps({"run": rd.name, "argv": ["true"], "state": "done", "hours": 1,
                                                "started": m.now(), "ended": m.now()}))
    for i in range(300):
        (rd / "work" / f"e{i}").touch()
    check(m.tree_bytes(rd / "work") >= 301 * m.ENTRY_BYTES, "a tree of 300 empty files costs at least 4 KB an entry")
    res = m.start(h, {"op": "run", "argv": ["true"]}, dict(CAP, SUBJECT_KEPT_MB=1), spawn=False)
    check(not res["ok"] and "SUBJECT_KEPT_MB" in res["error"],
          f"so 300 empty files kept are past a 1 MB cap, and no run starts ({res.get('error')})")
    shutil.rmtree(root)


def case_count_deep(m):
    """The count before the copy out holds an fd a level, so a chain of dirs deeper than the fd limit hits EMFILE. That
    must refuse the copy, not skip the subtree past it (os.fwalk skipped it silently). A short chain still counts."""
    import resource
    top = Path(tempfile.mkdtemp(prefix="cc-subject-deep-"))
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    try:
        d = top
        for _ in range(120):
            d = d / "d"
            d.mkdir()
        short = Path(tempfile.mkdtemp(prefix="cc-subject-short-"))
        (short / "d" / "d").mkdir(parents=True)
        fd = os.open(top, os.O_RDONLY | os.O_DIRECTORY)
        sfd = os.open(short, os.O_RDONLY | os.O_DIRECTORY)
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, hard))
        try:
            deep, ok = m.count_entries(fd, 1000), m.count_entries(sfd, 1000)
        finally:
            resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
            os.close(fd)
            os.close(sfd)
        check(isinstance(deep, str) and "could not be counted" in deep,
              f"a 120-deep chain past an fd limit of 64 refuses the copy ({deep})")
        check(ok is True, f"a 2-deep chain under the same limit is counted ({ok})")
        shutil.rmtree(short)
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
        shutil.rmtree(top)


def case_count_link(m):
    """A link in /work to a host dir is counted as one entry and never stat'd through or opened: its target here holds
    more entries than the limit and a dir no one may open, and either would refuse the count if it were reached."""
    top = Path(tempfile.mkdtemp(prefix="cc-subject-link-"))
    try:
        host, work = top / "host", top / "work"
        (host / "shut").mkdir(parents=True)
        for i in range(20):
            (host / f"f{i}").touch()
        (work / "sub").mkdir(parents=True)
        (work / "h").symlink_to(host)
        (work / "sub" / "h").symlink_to(host / "shut")
        (host / "shut").chmod(0)
        fd = os.open(work, os.O_RDONLY | os.O_DIRECTORY)
        try:
            n = m.count_entries(fd, 10)
            over = m.count_entries(fd, 2)
        finally:
            os.close(fd)
        check(n is True, f"two links to host dirs count as two entries, not what they name ({n})")
        check(isinstance(over, str) and "more than 2" in over, f"and the cap still counts them ({over})")
    finally:
        (top / "host" / "shut").chmod(0o700)
        shutil.rmtree(top)


def case_status_link(m):
    """status RUN lists a link in /work as a link and never stats through it. In a live /work an absolute link would
    resolve against the host's root, and os.fwalk stat'd every name to sort dirs from files, so a link to a host dir
    was hidden and one to a host file shown: an answer to whether that host path exists."""
    root, h = fixture(m)
    rd = m.subjects(h) / "20261001-000000-5a5a5a"
    (rd / "work" / "sub").mkdir(parents=True)
    (rd / "status.json").write_text(json.dumps({"run": rd.name, "argv": ["true"], "state": "done", "hours": 1,
                                                "started": m.now(), "ended": m.now()}))
    (rd / "work" / "sub" / "r.txt").write_text("R")
    links = {"hd": root / ".ssh", "hf": root / ".ssh/id", "gone": Path("/nonexistent-cc-subject-host-path")}
    for name, to in links.items():
        (rd / "work" / name).symlink_to(to)
    seen, real = [], os.stat

    def spy(p, *a, **k):
        if os.path.basename(str(p)) in links:
            seen.append((str(p), k.get("follow_symlinks", True)))
        return real(p, *a, **k)

    os.stat = spy
    try:
        one = m.status(h, rd.name)
    finally:
        os.stat = real
    text = one.get("text", "")
    check(one["ok"] and all(f"{n} (link)" in text.splitlines() for n in links) and "sub/r.txt" in text,
          f"links to a host dir, a host file and nothing are all listed the same, as links ({one})")
    check(not seen, f"and none of them was stat'd ({seen})")
    shutil.rmtree(root)


def case_input_unreadable(m):
    """The --in size cap walks the source and refuses a dir it cannot open, where os.fwalk skipped it and so let
    whatever was inside past the cap. The kept-results cap refuses the same way."""
    root, h = fixture(m)
    src = root / "dev" / h / "in"
    shut = src / "shut"
    shut.mkdir()
    (shut / "big").write_bytes(os.urandom(2 << 20))
    (src / "ok").write_text("ok")
    shut.chmod(0)
    hidden = None
    try:
        dst = root / "dst"
        dst.mkdir()
        got = m.copy_in(str(src), dst, 1 << 20)
        check(isinstance(got, str) and "could not be measured" in got and os.listdir(dst) == [],
              f"an --in holding a dir no one may open is refused, and nothing was copied ({got}, {os.listdir(dst)})")
        res = m.start(h, {"op": "run", "argv": ["true"], "input": str(src)}, CAP, spawn=False)
        check(not res["ok"] and "could not be measured" in res["error"], f"and through start too ({res.get('error')})")
        shut.chmod(0o700)
        hidden = m.subjects(h) / "20261001-000000-6b6b6b" / "work" / "shut"
        hidden.mkdir(parents=True)
        hidden.chmod(0)
        res = m.start(h, {"op": "run", "argv": ["true"]}, CAP, spawn=False)
        check(not res["ok"] and "SUBJECT_KEPT_MB" in res["error"] and "could not be measured" in res["error"],
              f"a kept dir no one may open stops a run starting under the kept cap ({res.get('error')})")
    finally:
        shut.chmod(0o700)
        if hidden is not None:
            hidden.chmod(0o700)
        shutil.rmtree(root)


def case_input_size(m):
    """An --in source past SUBJECT_DISK_MB is refused before the host copies anything, counted through the pinned
    descriptor with no link followed, and the refused run is left a failed one. One that grows past it while it is
    copied is stopped too."""
    root, h = fixture(m)
    src = root / "dev" / h / "in"
    (src / "big").write_bytes(os.urandom(2 << 20))
    dst = root / "dst"
    dst.mkdir()
    got = m.copy_in(str(src), dst, 1 << 20)
    check(isinstance(got, str) and "SUBJECT_DISK_MB" in got and os.listdir(dst) == [],
          f"a 2 MB source is refused at 1 MB, and nothing was copied ({got}, {os.listdir(dst)})")
    cap = dict(CAP, SUBJECT_DISK_MB=1)
    bad = m.start(h, {"op": "run", "argv": ["true"], "input": str(src)}, cap, spawn=False)
    rds = [m.subjects(h) / r for r, _ in m.runs_of(h)]
    check(not bad["ok"] and "SUBJECT_DISK_MB" in bad["error"]
          and len(rds) == 1 and m.runs_of(h)[0][1]["state"] == "failed" and not (rds[0] / "in").exists(),
          f"through start it is a failed run with no in/ left ({bad.get('error')})")
    # the count of the source misses the growth, and the copy then lingers 30s: only the check made while it runs
    # can stop it within a few seconds, since the one after it ends would wait the 30s out
    was, popen = m.tree_bytes, m.sp.Popen

    def lingers(b, **k):
        i = b.index("/usr/bin/cp")
        return popen(b[:i] + ["/usr/bin/sh", "-c", '/usr/bin/cp "$@" && exec /usr/bin/sleep 30', "sh"] + b[i + 1:], **k)

    m.tree_bytes = lambda top, dir_fd=None, limit=None: 0 if dir_fd is not None else was(top, dir_fd, limit)
    m.sp.Popen = lingers
    try:
        dst2 = root / "dst2"
        dst2.mkdir()
        t0 = time.time()
        got = m.copy_in(str(src), dst2, 1 << 20)
        took = time.time() - t0
    finally:
        m.tree_bytes, m.sp.Popen = was, popen
    check(isinstance(got, str) and "SUBJECT_DISK_MB" in got and took < 10,
          f"a source that grows past the count is stopped while it copies, in {took:.1f}s ({got})")
    (src / "big").unlink()
    (src / "link").symlink_to(root / "dst2")
    (root / "outside").write_bytes(os.urandom(4 << 20))
    (src / "far").symlink_to(root / "outside")
    dst3 = root / "dst3"
    dst3.mkdir()
    got = m.copy_in(str(src), dst3, 1 << 20)
    check(got is True and (dst3 / "far").is_symlink(), f"links in the source count as links, not as what they name ({got})")
    shutil.rmtree(root)


def case_concurrent(m):
    """Two runs of one workspace at once share one day: neither gets the whole of what is left."""
    for what, cap, word in (("dollars", dict(CAP, SUBJECT_DAILY_USD=0.05), "daily cap"),
                            ("bytes", dict(CAP, SUBJECT_DAILY_NET_MB=0.01), "through the proxy")):
        root, h = fixture(m)
        rids = [m.start(h, {"op": "run", "argv": loop(30, 0.05), "hours": 1}, cap, spawn=False)["run"] for _ in range(2)]
        sts = {}
        ts = [threading.Thread(target=lambda r=r: sts.update({r: m.supervise(h, r, cap)})) for r in rids]
        for t in ts:
            t.start()
        for t in ts:
            t.join(120)
        led = ledger(m, h)
        check(all(sts[r]["state"] == "killed" and word in sts[r]["why"] for r in rids),
              f"{what}: both runs are killed at the shared cap ({[sts[r]['why'] for r in rids]})")
        if what == "dollars":
            total = sum(sts[r]["usd"] for r in rids)
            check(led["usd"] <= 0.05 and abs(led["usd"] - total) < 1e-6 and not led["held"],
                  f"{what}: the day's ledger stays under the cap and is the two runs' sum (${led['usd']:.4f}, runs ${total:.4f})")
        else:
            total = sum(sts[r]["net_bytes"] for r in rids)
            check(led["bytes"] <= m.net_cap(cap) and led["bytes"] == total,
                  f"{what}: the day's ledger stays under the cap and is the two runs' sum ({led['bytes']} of {m.net_cap(cap)}, runs {total})")
        shutil.rmtree(root)


def case_net_cap(m):
    """Bytes are a cap of their own: a run whose calls cost almost nothing is still killed at the day's volume."""
    root, h = fixture(m)
    FAKE.usage = {"input_tokens": 1, "output_tokens": 1}
    cap = dict(CAP, SUBJECT_DAILY_NET_MB=0.005)
    rid, st = run(m, h, loop(30), cap=cap)
    got = json.loads((m.subjects(h) / rid / "work/loop.json").read_text())
    check(got[0] == "200" and "403" in got, f"calls go through until the volume cap, then are refused ({got})")
    check(st["state"] == "killed" and "through the proxy" in st["why"], f"and the run is killed ({st['why']})")
    led = ledger(m, h)
    check(st["net_bytes"] <= m.net_cap(cap) and led["bytes"] == st["net_bytes"], f"what moved stops at the cap ({st['net_bytes']} bytes)")
    check(m.DEFAULTS["SUBJECT_DAILY_NET_MB"] == 1024, "the shipped volume cap is 1024 MB, a backstop behind the dollars")
    shutil.rmtree(root)


PLANT = r'''
S=/home/subject
mkdir -p $S/.claude; rm -r -f $S/.claude; ln -s %(decoy)s $S/.claude 2>/dev/null
ln -s %(decoy)s $S/linked 2>/dev/null
'''

LIMITS = r'''
import json, os
out = {}
try:
    open("/work/big", "wb").write(b"x" * (2 << 20)); out["fsize"] = "written"
except OSError as e:
    out["fsize"] = e.errno
v = os.statvfs("/tmp"); out["tmp_bytes"] = v.f_blocks * v.f_frsize
json.dump(out, open("/work/limits.json", "w"))
'''


def case_cred_link(m):
    root, h = fixture(m)
    (root / ".claude").mkdir()
    (root / ".claude/.credentials.json").write_text("OWNER-LOGIN")
    (root / ".claude/big").write_bytes(b"x" * (4 << 20))
    rid, st = run(m, h, ["/bin/sh", "-c", PLANT % {"decoy": str(root / ".claude")}])
    rd = m.subjects(h) / rid
    check(st["state"] == "done" and not (rd / "home").exists(), "HOME is the sandbox's own tmpfs: nothing of it lands on the host")
    check((root / ".claude/.credentials.json").read_text() == "OWNER-LOGIN" and (root / ".claude/big").stat().st_size == 4 << 20,
          "a link the subject plants in HOME toward the owner's login is not followed by the host")
    shutil.rmtree(root)


def case_limits(m):
    root, h = fixture(m)
    was = m.FILE_BYTES
    m.FILE_BYTES = 1 << 20
    try:
        rid, st = run(m, h, ["/usr/bin/python3", "-c", LIMITS])
    finally:
        m.FILE_BYTES = was
    out = json.loads((m.subjects(h) / rid / "work/limits.json").read_text())
    check(out["fsize"] == 27, f"a file past the per-file limit is refused (errno {out['fsize']})")
    check(0 < out["tmp_bytes"] <= m.TMP_BYTES, f"/tmp is a tmpfs no larger than {m.TMP_BYTES >> 20} MB")
    shutil.rmtree(root)


def case_stop(m):
    root, h = fixture(m)
    res = m.start(h, {"op": "run", "argv": ["sleep", "60"]}, CAP, spawn=False)
    t = threading.Timer(1.0, lambda: m.stop(h, res["run"]))
    t.start()
    st = m.supervise(h, res["run"], CAP)
    check(st["state"] == "stopped", "stop ends a live run")
    check(not m.stop(h, res["run"])["ok"], "a run that has ended cannot be stopped again")
    check(not m.stop(h, "../../x")["ok"], "a run id that is not one is refused")
    shutil.rmtree(root)


DISK = r"""
import json, os, stat
out = {}
def fill(p, n):
    try:
        with open(p, "wb") as f:
            f.write(b"x" * n)
            f.flush()
            os.fsync(f.fileno())
        return "written"
    except OSError as e:
        return e.errno
    finally:
        if os.path.exists(p):
            os.unlink(p)
out["over"] = fill("/work/big", 3 << 20)
held = open("/work/held", "wb")
held.write(b"y" * (700 << 10))
held.flush()
os.unlink("/work/held")
out["beside_unlinked"] = fill("/work/more", 600 << 10)
held.close()
out["after_close"] = fill("/work/more", 600 << 10)
os.makedirs("/work/res/sub")
open("/work/res/sub/r.txt", "w").write("RESULT")
open("/work/res/tool", "w").write("#!/bin/sh")
os.chmod("/work/res/tool", 0o6755)
os.symlink(@DECOY@, "/work/res/decoy")
os.symlink("/work/res/sub/r.txt", "/work/res/inner")
os.chmod("/work/res/sub", 0o500)
json.dump(out, open("/work/disk.json", "w"))
"""


def case_disk(m):
    """/work is a tmpfs of SUBJECT_DISK_MB: the kernel refuses a write past it, an unlinked file still open counts,
    and at the end what is there is copied out, links as links, modes made the host's."""
    root, h = fixture(m)
    cap = dict(CAP, SUBJECT_DISK_MB=1)
    rid, st = run(m, h, ["/usr/bin/python3", "-c", DISK.replace("@DECOY@", repr(str(root / ".ssh/id")))], cap=cap)
    rd = m.subjects(h) / rid
    check(st["state"] == "done" and "results" not in st, f"the disk subject ran to the end and its /work was kept ({st})")
    out = json.loads((rd / "work/disk.json").read_text())
    check(out["over"] == 28, f"a write past the 1 MB /work gets ENOSPC (errno {out['over']})")
    check(out["beside_unlinked"] == 28 and out["after_close"] == "written",
          f"an unlinked file still open counts against it, and stops counting once closed ({out})")
    check((rd / "work/res/sub/r.txt").read_text() == "RESULT", "what the subject left in /work is copied out")
    check((rd / "work/res/decoy").is_symlink() and os.readlink(rd / "work/res/decoy") == str(root / ".ssh/id")
          and (rd / "work/res/inner").is_symlink(), "a link it planted toward the host is copied as a link, not followed")
    check((root / ".ssh/id").read_text() == "HOST-SECRET", "and the host file it names is untouched")
    modes = {n: (rd / "work" / n).lstat().st_mode & 0o7777 for n in ("res", "res/sub", "res/sub/r.txt", "res/tool")}
    check(modes == {"res": 0o700, "res/sub": 0o700, "res/sub/r.txt": 0o600, "res/tool": 0o700},
          f"copied dirs are 0700, files 0600 or 0700, with no set-id bit ({ {k: oct(v) for k, v in modes.items()} })")
    shutil.rmtree(root)
    root, h = fixture(m)
    src = root / "dev" / h / "in"
    (src / "huge").write_bytes(b"z" * (2 << 20))
    # the host's count passes it (a 4 MB cap at the start), the 1 MB /work does not: as if it grew after the count
    res = m.start(h, {"op": "run", "argv": ["/bin/sh", "-c", "echo RAN > /work/ran"], "input": str(src), "hours": 1},
                  dict(cap, SUBJECT_DISK_MB=4), spawn=False)
    rid, st = res["run"], m.supervise(h, res["run"], cap)
    rd = m.subjects(h) / rid
    check(st["state"] == "failed" and "input" in st["why"], f"an input too big for /work fails the run ({st['why']})")
    check(not (rd / "in").exists() and not (rd / "work").exists(), "and leaves neither the input copy nor a partial /work")
    shutil.rmtree(root)


def case_status(m):
    """The workspace's only view of a run: live through /proc while it runs, from the kept copy once it ends. A file
    the subject wrote is read back, a link it planted toward the host is not followed, a run id or path that climbs
    out is refused, and a process outside the run's own scope is never read."""
    root, h = fixture(m)
    res = m.start(h, {"op": "run", "argv": ["sh", "-c", "echo LIVE > /work/live.txt; sleep 60"]}, CAP, spawn=False)
    rid = res["run"]
    rd = m.subjects(h) / rid
    t = threading.Thread(target=m.supervise, args=(h, rid, CAP))
    t.start()
    got, until = {}, time.time() + 30
    while time.time() < until and not got.get("ok"):
        got = m.status(h, rid, "/work/live.txt")
        time.sleep(0.2)
    check(got == {"ok": True, "text": "LIVE\n"} and not (rd / "work").exists(),
          f"status reads a live run's file through /proc, with nothing on the host yet ({got})")
    one = m.status(h, rid)
    check("/work, live" in one["text"] and "live.txt" in one["text"], "and lists its live /work")
    check("workspace login: expires at" in one["text"] and json.loads((rd / "status.json").read_text()).get("login_expires"),
          "status.json records when the workspace's login expires, and status says so")
    m.stop(h, rid)
    t.join(60)
    check(m.status(h, rid, "live.txt") == {"ok": True, "text": "LIVE\n"} and "/work, kept" in m.status(h, rid)["text"],
          "after the end the same file is read from the kept copy")
    check(not m.launch(h, {"op": "status", "run": rid, "path": "a\0b"})["ok"], "a path with a NUL byte is refused as JSON, not raised on")
    shutil.rmtree(root)
    # a sandbox that is not the run's: bwrap outside any cc-subject scope, with a /work of its own
    root, h = fixture(m)
    rid = m.start(h, {"op": "run", "argv": ["true"]}, CAP, spawn=False)["run"]
    r, w = os.pipe()
    imp = subprocess.Popen(["bwrap", "--die-with-parent", "--info-fd", str(w), "--ro-bind", "/usr", "/usr",
                            "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
                            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/work", "--",
                            "/bin/sh", "-c", "echo IMPOSTOR > /work/x; sleep 30"], pass_fds=(w,))
    os.close(w)
    info = b""
    while b"}" not in info:
        d = os.read(r, 4096)
        if not d:
            break
        info += d
    os.close(r)
    pid = json.loads(info)["child-pid"]
    time.sleep(0.5)
    p = m.subjects(h) / rid / "status.json"
    p.write_text(json.dumps({**json.loads(p.read_text()), "state": "running", "sandbox": pid}))
    try:
        check(os.path.exists(f"/proc/{pid}/root/work/x") and not m.status(h, rid, "x")["ok"],
              "a pid whose /work is there but which is not in the run's own scope is not read")
    finally:
        imp.kill()
        imp.wait()
    shutil.rmtree(root)
    # the kept copy, with a link planted on the host side of it
    root, h = fixture(m)
    rid, st = run(m, h, ["sh", "-c", "mkdir -p /work/d && echo RESULT > /work/d/r.txt && ln -s /home/subject/.claude/.credentials.json /work/c"
                         " && echo done"])
    check(st["state"] == "done", f"the status fixture run ends cleanly ({st})")
    # the planted link resolves ON THE HOST to the host's own secret, as a subject that guessed paths would aim it
    os.symlink(root / ".ssh/id", m.subjects(h) / rid / "work/host")
    listing = m.status(h)
    check(listing["ok"] and rid in listing["text"], "status with no run lists the workspace's runs")
    one = m.status(h, rid)
    check(one["ok"] and "d/r.txt" in one["text"] and "done" in one["text"], "status RUN lists /work and tails out.log")
    check(m.status(h, rid, "d/r.txt") == {"ok": True, "text": "RESULT\n"}, "status RUN PATH reads a file the subject wrote")
    check(m.status(h, rid, "/work/d/r.txt") == {"ok": True, "text": "RESULT\n"}, "and takes the /work/... form the usage names")
    check(not m.status(h, rid, "/work/../status.json")["ok"], "a /work/ path that climbs out is still refused")
    for bad in ("host", "c", "../status.json", "/etc/passwd", "d", "d/\0r.txt"):
        r = m.status(h, rid, bad)
        check(not r["ok"] and "HOST-SECRET" not in str(r), f"status RUN {bad!r} is refused, reading nothing outside /work")
    check(not m.status(h, "../../x")["ok"] and not m.launch(h, {"op": "status", "run": "../x"})["ok"],
          "a run id that is not one is refused")
    shutil.rmtree(root)


def case_sweep(m):
    """Starting a run prunes what ended runs past SUBJECT_KEEP_DAYS keep, and old ledger days; a recent or live run is
    left whole."""
    root, h = fixture(m)
    sub = m.subjects(h)
    stamp = lambda days: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))
    gone = subprocess.Popen(["true"])
    gone.wait()
    runs = {"old": ("20260901-000000-aaaaaa", "done", 30), "recent": ("20261001-000000-bbbbbb", "done", 1),
            "live": ("20260902-000000-cccccc", "running", 30), "copying": ("20261009-000000-eeeeee", "starting", 0)}
    for name, (rid, state, days) in runs.items():
        rd = sub / rid
        for d in ("work/d", "in", "home"):
            (rd / d).mkdir(parents=True)
        (rd / "work/d/f").write_text("x")
        (rd / "work/d").chmod(0o500)   # a dir the host cannot write until it is normalised
        st = {"run": rid, "argv": ["true"], "hours": 1, "state": state, "started": stamp(days)}
        st.update({"supervisor": os.getpid()} if state == "running" else {"supervisor": gone.pid} if state == "starting"
                  else {"ended": stamp(days)})
        (rd / "status.json").write_text(json.dumps(st))
    (sub / "ledger").mkdir()
    old_day, new_day = stamp(30)[:10], stamp(1)[:10]
    for day in (old_day, new_day):
        (sub / "ledger" / f"{day}.json").write_text(json.dumps({"usd": 0.0, "held": {}, "bytes": 0}))
    res = m.start(h, {"op": "run", "argv": ["true"]}, CAP, spawn=False)
    check(res["ok"], f"a run starts ({res})")
    old = sub / runs["old"][0]
    check(not any((old / d).exists() for d in ("work", "in", "home")) and (old / "status.json").exists(),
          f"an ended run past the days kept loses work/, in/ and home/, and keeps its status ({sorted(os.listdir(old))})")
    check(all((sub / runs[k][0] / "work/d/f").exists() for k in ("recent", "live")) and (sub / runs["live"][0] / "in").exists(),
          "a recent run's /work is kept, and a live run is kept whole")
    check(not (sub / runs["copying"][0] / "in").exists() and not (sub / runs["recent"][0] / "in").exists(),
          "a run whose launcher died mid-copy loses its partial in/ whatever its age, as does any run not live")
    check(not (sub / "ledger" / f"{old_day}.json").exists() and (sub / "ledger" / f"{new_day}.json").exists(),
          "an old ledger day is deleted, a recent one kept")
    for k in ("recent", "live", "copying"):
        (sub / runs[k][0] / "work/d").chmod(0o700)
    shutil.rmtree(root)


def case_credential(m):
    root, h = fixture(m, cred={})
    res = m.start(h, {"op": "run", "argv": ["true"]}, CAP, spawn=False)
    check(not res["ok"] and "no login" in res["error"], "a workspace with no login of its own starts nothing")
    shutil.rmtree(root)
    root, h = fixture(m, cred={"claudeAiOauth": {"accessToken": "a", "expiresAt": int(time.time() * 1000)}})
    res = m.start(h, {"op": "run", "argv": ["true"]}, CAP, spawn=False)
    check(not res["ok"] and "expires" in res["error"], "a login about to expire starts nothing")
    shutil.rmtree(root)
    root, h = fixture(m)
    check(not m.launch("../x", {"op": "run"})["ok"] and not m.launch("nosuch", {"op": "run"})["ok"],
          "a handle that is not a member workspace is refused")
    shutil.rmtree(root)


def case_supervisor_fails(m):
    """Whatever kills the supervisor, the run ends in a terminal state and holds no slot."""
    root, h = fixture(m)
    rid, st = run(m, h, ["sh", "-c", "x" * 200000])   # one argument over 128 KiB: the exec fails with E2BIG
    rd = m.subjects(h) / rid
    check(st["state"] == "failed" and "Argument list too long" in st["why"], f"a command the kernel will not exec ends `failed` ({st['why']})")
    check(m.day_totals(h, m.today())[1] == 0 and not m.stop(h, rid)["ok"], "and it holds no concurrency slot")
    check(not m.sock_dir(h, rid).exists(), "and its socket dir is gone")
    was = m.RUNTIME
    m.RUNTIME = str(root / ".ssh/id")   # a file: no socket dir can be made under it
    try:
        rid, st = run(m, h, ["true"])
    finally:
        m.RUNTIME = was
    rd = m.subjects(h) / rid
    check(st["state"] == "failed" and "NotADirectoryError" in st["why"], f"a proxy that cannot start ends the run `failed` ({st['why']})")
    shutil.rmtree(root)
    root, h = fixture(m)
    gone = subprocess.Popen(["true"])
    gone.wait()
    a = m.start(h, {"op": "run", "argv": ["true"]}, CAP, spawn=False)["run"]
    b = m.start(h, {"op": "run", "argv": ["true"]}, CAP, spawn=False)["run"]
    check(m.day_totals(h, m.today())[1] == 2, "two runs whose supervisor is alive are both live")
    for r, pid in ((a, gone.pid), (b, None)):
        p = m.subjects(h) / r / "status.json"
        st = json.loads(p.read_text())
        st["state"] = "running"
        if pid is None:
            st.pop("supervisor")
        else:
            st["supervisor"] = pid
        p.write_text(json.dumps(st))
    check(m.day_totals(h, m.today())[1] == 0, "a run marked running whose supervisor is gone, or never recorded, is not live")
    res = m.stop(h, a)
    check(not res["ok"] and "supervisor" in res["error"], f"and stop says so rather than answering ok ({res['error']})")
    check(m.start(h, {"op": "run", "argv": ["true"]}, dict(CAP, SUBJECT_CONCURRENT=1), spawn=False)["ok"],
          "so a new run can start in the slots they held")
    check("failed" in m.status(h)["text"], "and status lists them as failed")
    shutil.rmtree(root)


def case_long_handle(m):
    h = "h" * 63   # the longest handle HANDLE allows
    root, h = fixture(m, h=h)
    old = root / ".cc/members" / h / "subjects" / "20261001-000000-abcdef" / "net/proxy.sock"
    check(len(str(old).encode()) > 107, f"the socket path under the run dir would be past the unix limit ({len(str(old))} bytes)")
    rid, st = run(m, h, ["true"])
    check(st["state"] == "done", f"a 63-character handle's run starts and ends ({st['state']} {st.get('why')})")
    check(len(str(m.sock_dir(h, rid) / "proxy.sock").encode()) < 108, "its socket is under the ~/.cc/s fallback, inside the limit")
    rt = Path(tempfile.mkdtemp(prefix="cc-rt-"))
    was = m.RUNTIME
    m.RUNTIME = str(rt)
    try:
        rid, st = run(m, h, ["true"])
        check(st["state"] == "done" and m.sock_dir(h, rid).parent == rt / "cc-subject",
              "with XDG_RUNTIME_DIR set the socket dir is under it")
        check(oct((rt / "cc-subject").stat().st_mode & 0o777) == "0o700" and not list((rt / "cc-subject").iterdir()),
              "that dir is 0700 and holds nothing once the run has ended")
    finally:
        m.RUNTIME = was
        shutil.rmtree(rt)
    shutil.rmtree(root)


def case_copy_backoff(m):
    """A source whose copy keeps failing waits longer before each next copy (no count of them), and one that copies
    clears the wait."""
    root, h = fixture(m)
    src = root / "dev" / h / "in"
    (src / "big").write_bytes(os.urandom(2 << 20))
    cap, ask = dict(CAP, SUBJECT_DISK_MB=1, SUBJECT_CONCURRENT=100), {"op": "run", "argv": ["true"], "input": str(src)}

    def age(secs):   # every run so far ended `secs` ago: only the newest failure's end decides the wait
        for run, st in m.runs_of(h):
            st["ended"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - secs))
            (m.subjects(h) / run / "status.json").write_text(json.dumps(st))

    first = m.start(h, ask, cap, spawn=False)
    again = m.start(h, ask, cap, spawn=False)
    check(not first["ok"] and "SUBJECT_DISK_MB" in first["error"] and not again["ok"] and "COPY_BACKOFF" in again["error"]
          and len(m.runs_of(h)) == 1, f"a failed copy holds the next copy of that source back, before any run dir "
                                      f"is made ({again.get('error')}, {len(m.runs_of(h))} runs)")
    other = m.start(h, {"op": "run", "argv": ["true"]}, cap, spawn=False)
    check(other["ok"], f"…but not a run without that source ({other.get('error')})")
    age(m.COPY_BACKOFF + 1)
    second = m.start(h, ask, cap, spawn=False)
    check(not second["ok"] and "SUBJECT_DISK_MB" in second["error"], f"once the wait is past it is copied again ({second})")
    age(m.COPY_BACKOFF + 1)
    held = m.start(h, ask, cap, spawn=False)
    check(not held["ok"] and "COPY_BACKOFF" in held["error"], f"…and the second failure in a row doubles the wait ({held})")
    for _ in range(30):   # no count: however many failed, the wait is past at COPY_BACKOFF_MAX
        age(m.COPY_BACKOFF_MAX + 1)
        m.start(h, ask, cap, spawn=False)
    age(m.COPY_BACKOFF_MAX + 1)
    late = m.start(h, ask, cap, spawn=False)
    check("COPY_BACKOFF" not in late.get("error", ""), f"the wait stops growing at COPY_BACKOFF_MAX, never a refusal for good ({late})")
    (src / "big").unlink()
    age(m.COPY_BACKOFF_MAX + 1)
    ok = m.start(h, ask, cap, spawn=False)

    def state(run, **kv):
        st = json.loads((m.subjects(h) / run / "status.json").read_text())
        (m.subjects(h) / run / "status.json").write_text(json.dumps({**st, **kv}))

    state(ok["run"], state="done")   # spawn=False starts no supervisor, so nothing else moves it past `starting`
    (src / "big").write_bytes(os.urandom(2 << 20))
    bad = m.start(h, ask, cap, spawn=False)
    retry = m.start(h, ask, cap, spawn=False)
    check(ok["ok"] and not bad["ok"] and "SUBJECT_DISK_MB" in bad["error"] and "COPY_BACKOFF" in retry["error"]
          and 0 < m.copy_wait(h, str(src)) <= m.COPY_BACKOFF,
          f"a copy that goes through starts the wait over at COPY_BACKOFF ({ok}, {bad}, {m.copy_wait(h, str(src))})")
    # B starts after A and is still copying (`starting`) when A fails: B has not cleared A's failure, so C waits
    age(m.COPY_BACKOFF_MAX + 1)
    (src / "big").unlink()
    b = m.start(h, ask, cap, spawn=False)
    (src / "big").write_bytes(os.urandom(2 << 20))
    a = m.start(h, ask, cap, spawn=False)
    runs = dict(m.runs_of(h))
    a_run = max(runs, key=lambda r: float(runs[r]["t0"]))   # the copy that just failed; A started before B
    state(a_run, t0=float(runs[b["run"]]["t0"]) - 1e-6)
    c = m.start(h, ask, cap, spawn=False)
    check(b["ok"] and not a["ok"] and "SUBJECT_DISK_MB" in a["error"] and not c["ok"] and "COPY_BACKOFF" in c["error"],
          f"a newer copy still in progress does not clear an older copy's failure ({b}, {a}, {c})")
    shutil.rmtree(root)


def selfcheck(m):
    global FAKE, SHIPPED
    if not all(shutil.which(t) for t in ("bwrap", "systemd-run", "prlimit")):
        print("cc-subject selfcheck: bwrap, systemd-run or prlimit is not installed")
        return 1
    m.TICK = 0.2
    m.WAIT_MAX = 2.0
    m.RUNTIME = None   # socket dirs under each fixture's own HOME; case_long_handle sets one of its own
    FAKE, SHIPPED = Fake(), m.UPSTREAM
    m.UPSTREAM = ("127.0.0.1", FAKE.port, False)   # never the real API: nothing in here spends
    failed = 0
    cases = (case_net, case_files, case_tree, case_caps, case_spend, case_proxy_units, case_concurrent, case_stop,
             case_credential, case_cred_link, case_limits, case_disk, case_status, case_sweep, case_supervisor_fails,
             case_long_handle, case_net_cap, case_count, case_kept, case_entries, case_count_deep,
             case_count_link, case_status_link, case_input_unreadable, case_input_size, case_copy_backoff)
    try:
        for case in cases:
            print(case.__name__)
            try:
                case(m)
            except AssertionError as e:
                failed += 1
                print(f"  FAIL {e}")
    finally:
        m.UPSTREAM = SHIPPED
        FAKE.close()
    print(f"cc-subject selfcheck: {len(cases) - failed} passed, {failed} failed")
    return 1 if failed else 0
