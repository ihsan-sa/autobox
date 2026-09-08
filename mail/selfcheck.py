#!/usr/bin/env python3
"""`cc-mail selfcheck` — the mail door's own tests. No network, no config of this box's, no live server.

Every case builds its whole world and takes it away again: its own store directory, its own configuration in
the environment (which wins over ~/.cc/config, so nothing here can read or write the box's real one), its own
captured log, and a server on a port the KERNEL picks on 127.0.0.1, closed at the end of the case. Nothing here
reads ~/.cc/mail, and a case never stands on state another case happened to leave behind.

The requests are real HTTP against a real handler, because most of what this file has to prove is about what
reaches the wire: which status code, whether `reply` is a string or null, and how many lines went to the log.
"""
import email.message
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import receiver as r        # noqa: E402

KEYS = {"id", "from", "to", "cc", "subject", "message_id", "in_reply_to", "references",
        "date", "text", "attachments", "auth", "received_at"}   # the contract, spelled out in receiver.py

SECRET = "s" * 40
ALLOWED = "friend@allowed.example"
OTHER = "second@allowed.example"
STRANGER = "nobody@elsewhere.example"
RCPT = "brief@box.example"


def eml(frm=ALLOWED, to=RCPT, subject="a brief", auth="spf=pass dkim=pass dmarc=pass",
        body="do the thing\nplease", attach=None, html=None, headers=None):
    """One mail, built the way a real one arrives. `frm` here is the From: HEADER — the envelope sender is a
    separate argument to post(), and half of what this file tests is that the two are not confused."""
    m = email.message.EmailMessage()
    m["From"] = frm
    m["To"] = to
    m["Subject"] = subject
    if auth is not None:
        m["Authentication-Results"] = "mx.cloudflare.net; " + auth
    for k, v in (headers or {}).items():
        m[k] = v
    m.set_content(body)
    if html is not None:
        m.add_attachment(html.encode(), maintype="text", subtype="html")
    for name, data in (attach or []):
        m.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    return m.as_bytes()


def _hostile():
    """Four attachment parts whose filenames are the four things a sender tries: a traversal, an absolute path,
    a leading dot, and 4 KB of name. Plus one part with no filename at all. Assembled by hand because
    email.message will not write these headers, which is exactly why the reader has to survive them."""
    parts, names = [], ["../../../etc/passwd", "/passwd", ".hidden", "n" * 4000, None]
    for i, name in enumerate(names):
        disp = "attachment" if name is None else 'attachment; filename="%s"' % name
        parts.append("--B\r\nContent-Type: application/octet-stream\r\n"
                     "Content-Disposition: %s\r\nContent-Transfer-Encoding: base64\r\n\r\nZGF0YQ==\r\n" % disp)
    return ("From: Someone <friend@allowed.example>\r\nTo: %s\r\nSubject: files\r\n"
            "Authentication-Results: mx.cloudflare.net; spf=pass dkim=pass dmarc=pass\r\n"
            "MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=B\r\n\r\n"
            "--B\r\nContent-Type: text/plain\r\n\r\nhere they are\r\n%s--B--\r\n"
            % (RCPT, "".join(parts))).encode()


HOSTILE_NAMES = _hostile()


def many_parts(n, data="data"):
    """A well-formed mail from an allow-listed address with `n` attachment parts and nothing else in it.

    Built by hand because the point is the count: 1 MB of nested multipart parsed to 12,787 parts, and one file
    per part is 12,787 creat()s with the Worker's event held open for the length of them."""
    head = ("From: %s\r\nTo: %s\r\nSubject: many\r\n"
            "Authentication-Results: mx.cloudflare.net; spf=pass dkim=pass dmarc=pass\r\n"
            "MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=B\r\n\r\n" % (ALLOWED, RCPT))
    body = "".join('--B\r\nContent-Type: application/octet-stream\r\n'
                   'Content-Disposition: attachment; filename="f%d.bin"\r\n\r\n%s\r\n' % (i, data)
                   for i in range(n))
    return (head + body + "--B--\r\n").encode()


def charset_mail(charset, body=b"hello there"):
    """One mail whose text/plain part declares `charset` and nothing else — built by hand, because
    EmailMessage.set_content() only ever encodes through a charset Python's codecs module already knows, and
    the point here is a label it does not: `x-unknown`, `unknown-8bit`, real ones like `iso-8859-8-i` that
    codecs simply never registered."""
    return (("From: %s\r\nTo: %s\r\nSubject: charset\r\n"
             "Authentication-Results: mx.cloudflare.net; spf=pass dkim=pass dmarc=pass\r\n"
             'MIME-Version: 1.0\r\nContent-Type: text/plain; charset="%s"\r\n\r\n'
             % (ALLOWED, RCPT, charset)).encode() + body)


WORKER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "inbound-worker.js")

# The stub for the one thing the Worker imports from the Cloudflare runtime. Nothing here sends a mail; the
# harness only needs to see that reply() was called.
EMAIL_STUB = """export class EmailMessage {
  constructor(from, to, raw) { this.from = from; this.to = to; this.raw = raw; }
}
"""

# Runs the Worker's OWN email() handler — not a copy of its logic — once per case, with `fetch` returning that
# case's answer, and writes down what the handler did with it.
HARNESS = r"""import fs from "node:fs";
import worker from "./worker.mjs";

const cases = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = {};
for (const c of cases) {
  const replies = [];
  globalThis.fetch = async () => {
    if (c.unreachable) throw new Error("connect ECONNREFUSED");
    return new Response(c.body, { status: c.status, headers: { "content-type": c.type } });
  };
  const message = {
    raw: "From: a@b.example\r\nTo: brief@box.example\r\n\r\nhi\r\n",
    from: "a@b.example",
    to: "brief@box.example",
    headers: new Map([["subject", "a brief"], ["message-id", "<x@b.example>"]]),
    reply: async (m) => { replies.push(m); },
  };
  try {
    await worker.email(message, { BOX_URL: "https://box.example/inbound", MAIL_SECRET: "s" }, {});
    out[c.name] = replies.length ? "replied" : "returned";
  } catch (err) {
    out[c.name] = "threw";
  }
}
fs.writeFileSync(process.argv[3], JSON.stringify(out));
"""


def worker_verdicts(cases):
    """What core/mail/inbound-worker.js does with each answer in `cases`: "returned" (the event ends cleanly, so
    the mail is accepted and this Worker is done with it), "replied" (that, and it mailed the sender back) or
    "threw" (the event fails, the mail is NOT accepted, and the sending server retries it later).

    Returns None when there is no node on PATH — the Worker runs at Cloudflare, not here, so a box without node
    simply does not check this. Everything the handler touches is stubbed: `cloudflare:email`, `fetch` and the
    EmailMessage it is handed."""
    node = shutil.which("node")
    if not node:
        return None
    tmp = tempfile.mkdtemp(prefix="cc-mail-worker.")
    try:
        src = open(WORKER).read()
        assert '"cloudflare:email"' in src, "inbound-worker.js no longer imports cloudflare:email"
        with open(os.path.join(tmp, "worker.mjs"), "w") as f:
            f.write(src.replace('"cloudflare:email"', '"./cloudflare-email.mjs"'))
        for name, text in (("cloudflare-email.mjs", EMAIL_STUB), ("harness.mjs", HARNESS)):
            with open(os.path.join(tmp, name), "w") as f:
                f.write(text)
        with open(os.path.join(tmp, "cases.json"), "w") as f:
            json.dump(cases, f)
        out = os.path.join(tmp, "out.json")
        p = subprocess.run([node, os.path.join(tmp, "harness.mjs"), os.path.join(tmp, "cases.json"), out],
                           capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            print("  node harness failed: %s" % (p.stderr.strip()[-300:] or "no stderr"))
            return {}
        with open(out) as f:
            return json.load(f)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class Box:
    """One case's whole world. Enter it, post to it, read its log and its store, leave it with nothing behind."""

    KEYS = ("MAIL_SECRET", "MAIL_ALLOW", "LESSONS_EMAILS", "MAIL_MAX_BYTES", "MAIL_MAX_PARTS",
            "MAIL_MAX_ATTACH_BYTES", "MAIL_MAX_CONN", "MAIL_RATE", "MAIL_RATE_WINDOW", "MAIL_DOMAIN",
            "MAIL_PORT", "PATH")

    def __init__(self, secret=SECRET, allow=ALLOWED + "," + OTHER, use_env=True, **cfg):
        self.cfg = dict(MAIL_SECRET=secret, MAIL_ALLOW=allow, LESSONS_EMAILS="",
                        MAIL_MAX_BYTES="", MAIL_MAX_PARTS="", MAIL_MAX_ATTACH_BYTES="", MAIL_MAX_CONN="",
                        MAIL_RATE="", MAIL_RATE_WINDOW="", MAIL_DOMAIN="box.example", MAIL_PORT="")
        self.cfg.update({k: str(v) for k, v in cfg.items()})
        # use_env=False puts the same values behind a STUB cc-config on PATH instead, which is the only way to
        # count how many times the server asks for one. See the "read once" case.
        self.use_env = use_env

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="cc-mail-selfcheck.")
        self.saved_env = {k: os.environ.get(k) for k in self.KEYS}
        self.saved_conf = r.CONF
        r.CONF = {}
        self.saved = (r.MAILDIR, r.INBOX, r.RATEFILE, r.STATE)
        r.MAILDIR = self.tmp
        r.INBOX = os.path.join(self.tmp, "inbox")
        r.RATEFILE = os.path.join(self.tmp, "rate.json")
        r.STATE = os.path.join(self.tmp, "state")
        os.makedirs(r.INBOX)
        os.makedirs(r.STATE)
        if self.use_env:
            # EVERY key the receiver reads is set here, empty ones included: an unset key would fall through to
            # cc-config and this box's real ~/.cc/config, and a test that reads the owner's allow-list is not
            # a test.
            os.environ.update(self.cfg)
        else:
            for key in self.cfg:
                os.environ.pop(key, None)
            self._stub_cc_config()
            r.load_config()
        self.saved_err, self.err = sys.stderr, io.StringIO()
        sys.stderr = self.err
        self.srv = r.Server((r.BIND, 0), r.Handler)
        self.host, self.port = self.srv.server_address[0], self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_):
        self.srv.shutdown()
        self.srv.server_close()
        sys.stderr = self.saved_err
        r.MAILDIR, r.INBOX, r.RATEFILE, r.STATE = self.saved
        r.CONF = self.saved_conf
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- the stub cc-config, for the one case that has to count the calls the server makes to it

    def _stub_cc_config(self):
        """A `cc-config` on PATH that appends the key it was asked for to a file and answers from values.txt."""
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        self.values = os.path.join(self.tmp, "values.txt")
        self.calls = os.path.join(self.tmp, "calls.txt")
        self.write_conf(self.cfg)
        path = os.path.join(bindir, "cc-config")
        with open(path, "w") as f:
            f.write("#!/bin/sh\nprintf '%%s\\n' \"$2\" >> %s\n"
                    "line=$(grep \"^$2=\" %s) || exit 1\nprintf '%%s\\n' \"${line#*=}\"\n"
                    % (self.calls, self.values))
        os.chmod(path, 0o755)
        os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")

    def write_conf(self, values):
        with open(self.values, "w") as f:
            for k, v in values.items():
                f.write("%s=%s\n" % (k, v))

    def conf_calls(self):
        try:
            with open(self.calls) as f:
                return len(f.read().split())
        except OSError:
            return 0

    def post(self, raw, sender=ALLOWED, rcpt=RCPT, secret=SECRET, path="/inbound", method="POST"):
        """The worker's call, byte for byte. Returns (status, parsed JSON)."""
        h = {"Content-Type": "message/rfc822"}
        if secret is not None:
            h["Authorization"] = "Bearer " + secret
        if sender is not None:
            h["X-Mail-From"] = sender
        if rcpt is not None:
            h["X-Mail-To"] = rcpt
        req = urllib.request.Request("http://%s:%d%s" % (self.host, self.port, path),
                                     data=raw, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def lines(self):
        return [ln for ln in self.err.getvalue().splitlines() if ln.strip()]

    def clear(self):
        """Start this request's log at zero, so "exactly one line" is a claim about one request."""
        self.err.seek(0)
        self.err.truncate(0)

    def ids(self):
        return sorted(d for d in os.listdir(r.INBOX) if not d.startswith("."))

    def mail(self, mail_id):
        with open(os.path.join(r.INBOX, mail_id, "message.json")) as f:
            return json.load(f)


def run():
    n = [0]
    fails = []

    def k(cond, name):
        n[0] += 1
        if cond:
            print("  ok   %s" % name)
        else:
            print("  FAIL %s" % name)
            fails.append(name)

    # ---------------------------------------------------------------- 1. an allow-listed mail is stored
    with Box() as b:
        raw = eml(frm="Friend <friend@allowed.example>", subject="=?utf-8?q?a_brief_=E2=80=94_now?=",
                  body="do the thing", html="<b>ignore me</b>",
                  attach=[("report.pdf", b"%PDF-1.4\x00\x01bytes")],
                  headers={"Cc": "watcher@allowed.example", "Message-ID": "<abc@sender.example>",
                           "In-Reply-To": "<prev@sender.example>",
                           "References": "<one@sender.example> <prev@sender.example>",
                           # 2026-09-08 was a Tuesday: the wrong weekday is the point, see below
                           "Date": "Mon, 8 Sep 2026 10:45:12 +0000"})
        code, ans = b.post(raw, sender=ALLOWED, rcpt=RCPT)
        k(code == 200 and ans.get("status") == "stored", "an allow-listed mail is stored (200)")
        k(isinstance(ans.get("reply"), str) and ans.get("id", "") in ans.get("reply", ""),
          "…and the answer carries the text the worker replies to the sender")
        got = b.ids()
        k(len(got) == 1 and re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", got[0]) is not None,
          "…in one directory named <UTC stamp>-<8 hex>")
        m = b.mail(got[0])
        k(set(m) == KEYS, "message.json has exactly the documented keys, no more and no fewer")
        with open(os.path.join(r.INBOX, got[0], "raw.eml"), "rb") as f:
            k(f.read() == raw, "raw.eml is the bytes that arrived, byte for byte")
        k(m["from"] == ALLOWED, "`from` is the AUTHENTICATED identity, which is what the allow-list matched")
        k(m["auth"]["identity"] == "header-from" and m["auth"]["envelope_from"] == ALLOWED,
          "…and auth says which of the two it came from, with the envelope kept beside it")
        k(m["auth"]["header_from"] == "Friend <friend@allowed.example>",
          "…while the raw From: line is recorded as written")
        k(set(m["auth"]) == {"results", "spf", "dkim", "dmarc", "verdict", "header_from", "envelope_from",
                             "identity"}, "auth has exactly the documented keys")
        k(m["to"][0] == RCPT, "to[0] is the envelope recipient — the address milestone 2 routes on")
        k(m["to"][1:] == [], "…and the To: header's own address, being the same one, is not repeated")
        k(m["cc"] == ["watcher@allowed.example"], "cc comes off the Cc: header")
        k(m["subject"] == "a brief — now", "the subject is decoded out of RFC 2047")
        k(m["message_id"] == "<abc@sender.example>" and m["in_reply_to"] == "<prev@sender.example>"
          and m["references"] == ["<one@sender.example>", "<prev@sender.example>"],
          "the threading headers are kept as they were")
        k(m["date"] == "Tue, 08 Sep 2026 10:45:12 +0000",
          "the Date: is re-rendered by the parser, so a wrong weekday comes out corrected (raw.eml has the original)")
        k("do the thing" in m["text"] and "ignore me" not in m["text"],
          "`text` is the text/plain body, and the HTML part is NOT rendered into it")
        att = {a["name"]: a for a in m["attachments"]}
        k("report.pdf" in att and att["report.pdf"]["size"] == len(b"%PDF-1.4\x00\x01bytes")
          and att["report.pdf"]["type"] == "application/octet-stream", "the attachment is listed with its size and type")
        p = os.path.join(r.INBOX, got[0], att["report.pdf"]["path"])
        k(os.path.isfile(p) and open(p, "rb").read() == b"%PDF-1.4\x00\x01bytes",
          "…and its bytes are on disk, decoded out of MIME and not touched otherwise")
        k(att["report.pdf"]["path"].startswith("attachments/"), "…under attachments/, at the path WE chose")
        k(len(m["attachments"]) == 2 and any(a["type"] == "text/html" for a in m["attachments"]),
          "the HTML part is stored as bytes like any other attachment")
        k(m["auth"]["verdict"] == "pass" and m["auth"]["results"], "the mail's own Authentication-Results are recorded")
        k(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", m["received_at"]) is not None,
          "received_at is a UTC ISO stamp")

    # -------------------------------------------- 1b. a charset Python has no codec for is not a 500
    for charset in ("x-unknown", "unknown-8bit", "hex"):   # hex: a registered codec that is not a text encoding
        with Box() as b:
            code, ans = b.post(charset_mail(charset), sender=ALLOWED)
            k(code == 200 and ans.get("status") == "stored",
              "charset=%s is 200 stored, not the 500 that used to send the sender into a retry loop" % charset)
            got = b.ids()
            k(len(got) == 1 and "hello there" in b.mail(got[0]).get("text", ""),
              "…and its text/plain body is present — decoded as utf-8 once the label proved to have no codec")

    # ---------------------------------------------------------------- 2. an unknown sender learns nothing
    with Box() as b:
        b.clear()
        code, ans = b.post(eml(frm=STRANGER), sender=STRANGER)
        k(code == 403 and ans.get("status") == "dropped", "an unknown sender is dropped (403)")
        k(ans.get("reply") is None, "…with reply null, so the worker sends the stranger nothing at all")
        k(len(b.lines()) == 1 and "drop unknown-sender" in b.lines()[0],
          "…leaving exactly one log line: %r" % (b.lines() or [""])[0][:60])
        k(b.ids() == [], "…and nothing on disk")
        b.clear()
        code, _ = b.post(eml(), sender=ALLOWED)
        k(code == 200 and len(b.ids()) == 1, "the same mail from an allow-listed address IS stored")
        k(len(b.lines()) == 1 and b.lines()[0].count("store id=") == 1,
          "…and that too is one line, not two: the http.server default line is off")

    # an oversize mail from a stranger must still be a silent drop and never a reason — the check order is
    # "the sender, then the size", and swapping the two would tell a stranger the address exists.
    with Box(MAIL_MAX_BYTES=200) as b:
        code, ans = b.post(eml(frm=STRANGER, body="x" * 4000), sender=STRANGER)
        k(code == 403 and ans.get("reply") is None,
          "an oversize mail from a stranger is dropped, not refused with a reason (drops come first)")
        code, ans = b.post(eml(body="x" * 4000), sender=ALLOWED)
        k(code == 413 and isinstance(ans.get("reply"), str),
          "…the same mail from an allow-listed address gets the reason")

    # ---------------------------------------------------------------- 3. the call itself
    with Box() as b:
        b.clear()
        code, ans = b.post(eml(), secret="wrong")
        k(code == 401 and ans.get("status") == "unauthorized" and ans.get("reply") is None,
          "a call with the wrong secret is refused 401 and says nothing")
        k(len(b.lines()) == 1 and "bad-secret" in b.lines()[0], "…and is logged")
        k(b.ids() == [], "…and stores nothing")
        code, _ = b.post(eml(), secret=None)
        k(code == 401 and b.ids() == [], "a call with no Authorization header at all is refused too")
        code, _ = b.post(eml(), secret=SECRET)
        k(code == 200 and len(b.ids()) == 1, "the same call with the right secret is stored")
    with Box(secret="") as b:
        code, ans = b.post(eml(), secret=SECRET)
        k(code == 503 and ans.get("status") == "unavailable" and ans.get("reply") is None,
          "while MAIL_SECRET is unset on the box every call is refused 503 — never allowed through")
        k(b.ids() == [], "…and nothing is stored")

    # ---------------------------------------------------------------- 4. size
    with Box(MAIL_MAX_BYTES=3000) as b:
        code, ans = b.post(eml(body="x" * 8000))
        k(code == 413 and ans.get("status") == "refused", "a mail over MAIL_MAX_BYTES is refused (413)")
        k(isinstance(ans.get("reply"), str) and "3000" in ans["reply"],
          "…with a one-line reason naming the limit, for the worker to relay: %r" % (ans.get("reply") or "")[:50])
        k(b.ids() == [], "…and nothing is stored")
        code, _ = b.post(eml(body="x" * 100))
        k(code == 200 and len(b.ids()) == 1, "a mail under the cap from the same sender is stored")

    # ---------------------------------------------------------------- 5. the per-sender rate limit
    with Box(MAIL_RATE=3, MAIL_RATE_WINDOW=3600) as b:
        codes = [b.post(eml(body="m%d" % i))[0] for i in range(3)]
        k(codes == [200, 200, 200] and len(b.ids()) == 3, "the first MAIL_RATE mails from a sender are stored")
        code, ans = b.post(eml(body="one too many"))
        k(code == 429 and ans.get("status") == "refused", "…and the next one is refused (429)")
        k(isinstance(ans.get("reply"), str) and "3" in ans["reply"],
          "…with a reason naming the limit: %r" % (ans.get("reply") or "")[:50])
        k(len(b.ids()) == 3, "…and it is not stored")
        code, _ = b.post(eml(frm=OTHER, body="from someone else"), sender=OTHER)
        k(code == 200 and len(b.ids()) == 4,
          "the limit is PER SENDER: one person's burst does not shut the door on anybody else")
    with Box(MAIL_RATE=2, MAIL_RATE_WINDOW=60) as b:
        r.RATEFILE = os.path.join(b.tmp, "rate.json")
        now = time.time()
        with open(r.RATEFILE, "w") as f:                     # two mails, but from 10 minutes ago
            json.dump({ALLOWED: [now - 600, now - 601]}, f)
        k(b.post(eml())[0] == 200, "a count older than MAIL_RATE_WINDOW does not hold a mail back")
        with open(r.RATEFILE, "w") as f:
            json.dump({ALLOWED: [now, now]}, f)
        k(b.post(eml())[0] == 429,
          "…and a count inside the window does, read off the file — so a restart is not a fresh allowance")

    # ---------------------------------------------------------------- 6. the verdict in the mail's own headers
    with Box() as b:
        b.clear()
        code, ans = b.post(eml(auth="spf=pass dkim=fail dmarc=pass"))
        k(code == 403 and ans.get("status") == "dropped" and ans.get("reply") is None,
          "a mail whose headers say dkim=fail is dropped even from an allow-listed address")
        k(len(b.lines()) == 1 and "drop auth-" in b.lines()[0], "…with one log line naming the verdict")
        k(b.ids() == [], "…and nothing stored")
        k(b.post(eml(auth="spf=pass dkim=pass dmarc=fail"))[0] == 403, "dmarc=fail is a drop too")
        k(b.post(eml(auth="spf=permerror dkim=none dmarc=none"))[0] == 403, "…and so is a permerror")
        code, _ = b.post(eml(auth="spf=pass dkim=pass dmarc=pass"))
        k(code == 200, "the same mail with a passing verdict is stored")
        code, _ = b.post(eml(auth="spf=temperror dkim=pass dmarc=pass"))
        k(code == 200,
          "a temperror beside a pass is NOT a fail: a DNS blip at Cloudflare must not silently eat real mail")
        b.clear()
        code, ans = b.post(eml(auth=None))
        k(code == 403 and ans.get("reply") is None,
          "a mail carrying no Authentication-Results at all is dropped — nothing in it was authenticated")
        k(len(b.lines()) == 1 and "drop unauthenticated-sender" in b.lines()[0],
          "…with one log line saying that, and not that the sender was unknown: %r" % (b.lines() or [""])[0][:60])
    k(r.verdict(email.message_from_string(
        "Authentication-Results: mx; spf=temperror\n\nhi"))["verdict"] == "none",
      "a temperror on its own is recorded as verdict `none`, never as a fail")
    k(r.verdict(email.message_from_string(
        "Authentication-Results: mx; x-dkim=fail; spf=pass\n\nhi"))["verdict"] == "pass",
      "a method name inside a longer word (x-dkim=fail) is not that method's result")
    k(r.verdict(email.message_from_string(
        "Authentication-Results: mx; spf=pass\nAuthentication-Results: mx2; dkim=fail\n\nhi"))["verdict"] == "fail",
      "every Authentication-Results header is read, not only the first")

    # ------------------------------------------- 6b. WHICH address the allow-list is matched against
    # The hole this replaces: Email Routing rejects a mail only when SPF and DKIM BOTH fail, so an envelope of
    # `MAIL FROM: <an allow-listed address>` sent under the attacker's own DKIM-signed, DMARC-aligned domain
    # reaches the worker vouched for — vouched for as somebody else. Matching the envelope stored it as the
    # allow-listed person and replied "received" to the envelope the attacker chose. Google's SPF ends ~all,
    # so softfail was the ordinary case and not a corner of one.
    with Box() as b:
        b.clear()
        code, ans = b.post(eml(frm="attacker@evil.example", auth="spf=softfail dkim=pass dmarc=pass"),
                           sender=ALLOWED)
        k(code == 403 and ans.get("reply") is None,
          "an allow-listed ENVELOPE carrying the attacker's own DMARC-passing From: is dropped")
        k(b.ids() == [] and len(b.lines()) == 1 and "drop unknown-sender" in b.lines()[0],
          "…storing nothing and telling them nothing: %r" % (b.lines() or [""])[0][:60])
        for a in ("spf=softfail dkim=none dmarc=none", "spf=none dkim=none dmarc=none",
                  "spf=neutral dkim=none dmarc=none"):
            code, ans = b.post(eml(frm=ALLOWED, auth=a), sender=ALLOWED)
            k(code == 403 and ans.get("reply") is None,
              "no method passed, so no address is authenticated and the mail is dropped: %s" % a)
        k(b.ids() == [], "…and none of those three, every one of which used to be stored, reached the disk")
        # An Authentication-Results header is a header, and a sender can write one. Cloudflare's is the TOP
        # one, because an MTA prepends its own, and verdict() records the top one's result for each method.
        code, ans = b.post(eml(frm=ALLOWED, auth="spf=none dkim=none dmarc=none",
                               headers={"Authentication-Results": "evil; spf=pass dkim=pass dmarc=pass"}),
                           sender=STRANGER)
        k(code == 403 and b.ids() == [],
          "a sender's OWN Authentication-Results header, under Cloudflare's, promotes them to nothing")
    # dmarc=pass is a statement about the From: header's domain, so the From: header is the identity.
    with Box() as b:
        code, _ = b.post(eml(frm=ALLOWED, auth="spf=softfail dkim=pass dmarc=pass"), sender=STRANGER)
        k(code == 200 and len(b.ids()) == 1,
          "dmarc=pass on an allow-listed From: is stored, whatever envelope carried it")
        m = b.mail(b.ids()[0])
        k(m["from"] == ALLOWED and m["auth"]["identity"] == "header-from"
          and m["auth"]["envelope_from"] == STRANGER,
          "…as the From: address, with the envelope kept beside it and matched against nothing")
    # SPF is a statement about MAIL FROM and nothing else, so spf=pass authenticates the envelope alone.
    with Box() as b:
        code, _ = b.post(eml(frm="attacker@evil.example", auth="spf=pass dkim=none dmarc=none"), sender=OTHER)
        k(code == 200 and len(b.ids()) == 1,
          "spf=pass with no DMARC is stored on the ENVELOPE's word, which is the one SPF vouched for")
        m = b.mail(b.ids()[0])
        k(m["from"] == OTHER and m["auth"]["identity"] == "envelope",
          "…as the envelope address, the From: header deciding nothing at all")
    msg = email.message_from_string("From: a@b\n\nhi")
    k(r.identity(msg, {"dmarc": "pass", "spf": "fail"}, "c@d") == ("a@b", "header-from")
      and r.identity(msg, {"dmarc": "none", "spf": "pass"}, "c@d") == ("c@d", "envelope")
      and r.identity(msg, {"dmarc": "none", "spf": "none"}, "c@d") == ("", "")
      and r.identity(email.message_from_string("Subject: x\n\nhi"), {"dmarc": "pass"}, "c@d") == ("", ""),
      "identity(): dmarc=pass takes the header, spf=pass takes the envelope, neither — or no From: — takes nothing")

    # ---------------------------------------------------------------- 7. the filename the sender chose
    # Built as raw bytes on purpose. email.message refuses to WRITE most of these names, which is the point:
    # a hostile mail is not composed by a well-behaved library, and this door is the thing that reads one.
    with Box() as b:
        code, _ = b.post(HOSTILE_NAMES)
        k(code == 200, "a mail whose attachments are named for a traversal is stored like any other")
        m = b.mail(b.ids()[0])
        d = os.path.join(r.INBOX, b.ids()[0], "attachments")
        on_disk = os.listdir(d)
        k(len(on_disk) == 5 and all("/" not in f and not f.startswith(".") for f in on_disk),
          "…with every part inside attachments/, under a name we chose: %s" % sorted(on_disk))
        k(all(os.path.realpath(os.path.join(d, os.path.basename(a["path"]))).startswith(os.path.realpath(d) + os.sep)
              for a in m["attachments"]), "…and nothing written outside that directory")
        k(not os.path.exists(os.path.join(b.tmp, "etc")) and not os.path.exists(os.path.join(b.tmp, "passwd")),
          "…the traversal reached nowhere")
        k(any(a["name"] == "../../../etc/passwd" for a in m["attachments"]),
          "…while `name` keeps what the sender wrote, for milestone 2 to show and to trust for nothing")
        k(all(len(os.path.basename(a["path"])) <= 84 for a in m["attachments"]),
          "…a 4 KB filename is cut, so it cannot be the thing that fills the disk or breaks the path")
        k(any(os.path.basename(a["path"]).endswith("-part") for a in m["attachments"]),
          "…and a part with no filename at all still gets one")

    # ---------------------------------------------------------------- 8. the door itself
    with Box() as b:
        k(b.host == "127.0.0.1" and r.BIND == "127.0.0.1",
          "the server binds 127.0.0.1 and nothing else — the tunnel is the only way in")
        k(b.post(eml(), path="/")[0] == 404 and b.post(eml(), path="/anything")[0] == 404,
          "a POST anywhere but /inbound is 404, right secret or not")
        k(b.post(b"", method="GET", path="/inbound")[0] == 404,
          "there is no GET side at all, not even a health endpoint the tunnel could answer")
        code, ans = b.post(eml(), sender=None)
        k(code == 400 and ans.get("reply") is None, "a call with no X-Mail-From is refused 400 and replies nothing")
        code, ans = b.post(b"")
        k(code == 400 and ans.get("reason") == "empty message" and ans.get("reply") is None,
          "an empty body is refused 400 — not stored as a mail with nothing in it")
        # There is no case for the `message did not parse` branch on purpose: email.message_from_bytes does not
        # raise on rubbish — a body with no headers at all is simply a mail with none — so nothing that can be
        # sent down this socket reaches it. It stays as the catch around a parse of attacker bytes.
        # compare_digest raises TypeError on a str with a non-ASCII character, and this one comes straight off
        # the wire. Before the encode it killed the handler thread: no answer at all, and a raw traceback in
        # serve.log from an anonymous caller. The answer must be the ordinary 401.
        code, ans = b.post(eml(), secret="sü")     # latin-1, so the HTTP client itself will carry it: b"s\xfc"
        k(code == 401 and ans.get("status") == "unauthorized",
          "a secret with non-ASCII bytes in it is refused 401, not crashed on")
        # Content-Length is read with int() and urllib always writes a real one, so this branch needs a socket
        # of its own to reach. It is reachable: anything that can open the port can write the header by hand.
        s = socket.create_connection((b.host, b.port), timeout=10)
        s.sendall(b"POST /inbound HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + SECRET.encode()
                  + b"\r\nX-Mail-From: " + ALLOWED.encode() + b"\r\nContent-Length: abc\r\n\r\n")
        first = s.recv(200).split(b"\r\n")[0]
        s.close()
        k(b"400" in first, "a Content-Length that is not a number is answered 400: %r" % first[:40])
        k(b.ids() == [], "…and none of that stored anything")
        code, _ = b.post(eml())
        k(code == 200, "a well-formed call on /inbound is still stored after all of that")
        open(os.path.join(r.INBOX, ".20260101T000000Z-deadbeef"), "w").close()
        k(r.ids() == b.ids(), "a directory store() is still writing (leading dot) is not listed as a mail")

    # ---------------------------------------------------------------- 9. what one mail may cost
    # A cap on FILES, not on bytes: the parts are what turn into creat()s. The mail is well formed and the
    # sender is on the list, so this is a refusal with a reason and never a silent drop.
    with Box(MAIL_MAX_PARTS=4) as b:
        code, ans = b.post(many_parts(5))
        k(code == 413 and "too many parts" in (ans.get("reason") or ""),
          "a mail with more parts than MAIL_MAX_PARTS is refused (413): %r" % (ans.get("reason") or "")[:50])
        k(isinstance(ans.get("reply"), str), "…with the reason as `reply`, for the worker to relay")
        k(os.listdir(r.INBOX) == [], "…and nothing on disk, not even a directory half written")
        k(b.post(many_parts(4))[0] == 200 and len(b.ids()) == 1, "a mail at the cap is stored")
    # And a cap on the bytes those parts decode to, counted as they are written rather than found afterwards.
    with Box(MAIL_MAX_ATTACH_BYTES=100) as b:
        code, ans = b.post(many_parts(5, "x" * 40))
        k(code == 413 and "attachments too large" in (ans.get("reason") or ""),
          "attachments over MAIL_MAX_ATTACH_BYTES are refused (413): %r" % (ans.get("reason") or "")[:50])
        k(os.listdir(r.INBOX) == [],
          "…and the directory that was half written when the cap was hit is gone, tmp name and all")
        k(b.post(many_parts(2, "x" * 40))[0] == 200 and len(b.ids()) == 1,
          "…while a mail inside the cap is stored")

    # ---------------------------------------------------------------- 10. the ceiling on connections
    # One thread per connection with no ceiling is the tunnel's to spend: a caller that connects and then sends
    # nothing holds a thread for Handler.timeout seconds and can do it as often as it likes. Over the ceiling a
    # connection waits BUSY_WAIT for a slot and is then answered 503 busy, which the worker turns into a retry.
    with Box(MAIL_MAX_CONN=1) as b:
        held = socket.create_connection((b.host, b.port), timeout=10)
        held.sendall(b"POST /inbound HTTP/1.1\r\nHost: x\r\n")     # no blank line: the handler waits for one
        time.sleep(0.3)
        s = socket.create_connection((b.host, b.port), timeout=10)
        s.sendall(b"POST /inbound HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n")
        first = s.recv(300)
        s.close()
        k(b"503" in first and b'"busy"' in first,
          "with the only slot held, the next connection is answered 503 busy: %r" % first.split(b"\r\n")[0][:40])
        k(b.ids() == [], "…and stores nothing")
        held.close()
        time.sleep(0.3)
        k(b.post(eml())[0] == 200, "…and the slot comes back when that connection ends")

    # ---------------------------------------------------------------- 11. serve.log is bounded
    # Every line in it is built out of a stranger's mail and nothing else rotates it.
    with Box() as b:
        log = r.logfile()
        with open(log, "w") as f:
            f.write("x" * (r.LOG_CAP + 10))
        with open(log, "a") as f:
            k(r.roll_log(f) is True, "serve.log past LOG_CAP is rolled")
            k(os.path.isfile(log + ".1") and os.path.getsize(log) == 0,
              "…the old one kept as serve.log.1, a new one started")
            f.write("after\n")
            f.flush()
            k(open(log).read() == "after\n", "…and the process goes on writing, into the new file")
            k(r.roll_log(f) is False, "a log under the cap is left alone")
        other = os.path.join(b.tmp, "not-the-log")
        with open(other, "w") as f:
            f.write("y" * (r.LOG_CAP + 10))
        with open(other, "a") as f:
            k(r.roll_log(f) is False and not os.path.exists(other + ".1"),
              "…a stderr that is some other file is never renamed, however big it is")
        k(r.roll_log(io.StringIO()) is False, "…and neither is one with no file behind it, like this test's")

    # ---------------------------------------------------------------- 12. the config is read once, at startup
    # cc-config is a fork and an exec. Reading the allow-list, the caps and the rate per mail was five of them
    # per stored mail, on a path that begins at a public tunnel hostname and runs before the secret is checked.
    # Here cc-config is a stub on PATH that counts what it was asked for.
    with Box(use_env=False) as b:
        start = b.conf_calls()
        k(start >= len(r.CONF_KEYS), "every key is read from cc-config at startup: %d calls" % start)
        k([b.post(eml(body="m%d" % i))[0] for i in range(3)] == [200, 200, 200],
          "…and mail is stored out of what it read")
        k(b.conf_calls() == start, "…with not one cc-config call per mail: still %d" % b.conf_calls())
        b.post(eml(frm=STRANGER), sender=STRANGER, secret="wrong")
        k(b.conf_calls() == start, "…and a call with the wrong secret makes the box fork nothing at all")
        b.write_conf(dict(b.cfg, MAIL_ALLOW=ALLOWED + "," + STRANGER))
        k(b.post(eml(frm=STRANGER), sender=STRANGER)[0] == 403,
          "an address added to the config does not reach a door that is already open")
        # The reload is a SIGHUP, sent here to this process with the handler run() installs — the runbook's
        # `systemctl --user kill --signal=HUP` on the unit that runs `cc-mail serve`, and the only way an
        # unreachable handler would ever be noticed.
        old = signal.getsignal(signal.SIGHUP)
        signal.signal(signal.SIGHUP, r.on_hup)
        os.kill(os.getpid(), signal.SIGHUP)
        time.sleep(0.2)
        signal.signal(signal.SIGHUP, old)
        k(b.post(eml(frm=STRANGER), sender=STRANGER)[0] == 200, "…and a SIGHUP is what makes it")
        k(b.conf_calls() > start, "…paying for the reads once more, then, and not per mail")
        k(any("reload config" in ln for ln in b.lines()), "…and saying so in the log")

    # ------------------------------------------------- 13. the Worker's idea of a FINAL answer (mail loss)
    # The Worker is the last thing between the sender's server and the mail being gone: an event that returns
    # has ACCEPTED the mail, an event that throws has not, so the sending server still holds it and retries.
    # So anything that is not the receiver's own answer has to throw, and the two ways to get one are ordinary
    # mistakes: BOX_URL pasted without the `/inbound` path — which the receiver answers 404, in JSON, so no
    # content-type test would catch it — and Access or the tunnel answering with a page of its own. Every case
    # below is the real inbound-worker.js running, with fetch and cloudflare:email stubbed. See worker_verdicts.
    js = "application/json; charset=utf-8"
    html = "text/html; charset=utf-8"
    v = worker_verdicts([
        {"name": "stored", "status": 200, "type": js, "body": '{"status":"stored","id":"x","reply":null}'},
        {"name": "stored+reply", "status": 200, "type": js,
         "body": '{"status":"stored","id":"x","reply":"got it"}'},
        {"name": "refused", "status": 413, "type": js,
         "body": '{"status":"refused","reason":"too big","reply":"too big"}'},
        {"name": "rate", "status": 429, "type": js,
         "body": '{"status":"refused","reason":"too many","reply":"too many"}'},
        {"name": "malformed", "status": 400, "type": js,
         "body": '{"status":"refused","reason":"no X-Mail-From","reply":null}'},
        {"name": "dropped", "status": 403, "type": js, "body": '{"status":"dropped","reply":null}'},
        {"name": "no path", "status": 404, "type": js, "body": '{"status":"not found","reply":null}'},
        {"name": "access page", "status": 200, "type": html, "body": "<html>Sign in</html>"},
        {"name": "access 403", "status": 403, "type": html, "body": "<html>denied</html>"},
        {"name": "not ours", "status": 200, "type": js, "body": '{"status":"ok"}'},
        {"name": "unauthorized", "status": 401, "type": js, "body": '{"status":"unauthorized","reply":null}'},
        {"name": "busy", "status": 503, "type": js, "body": '{"status":"busy","reply":null}'},
        {"name": "tunnel down", "status": 502, "type": html, "body": "<html>Bad gateway</html>"},
        {"name": "unreachable", "unreachable": True},
    ])
    if v is None:
        print("  --   the Worker's answer handling needs node on PATH: not checked here")
    else:
        k(v.get("stored") == "returned", "the Worker takes a 200 `stored` as final and says nothing back")
        k(v.get("stored+reply") == "replied", "…and relays the `reply` when the receiver gave it one")
        k(v.get("refused") == "replied" and v.get("rate") == "replied",
          "…relays the reason on 413 and 429, which the receiver has already decided")
        k(v.get("malformed") == "returned", "…takes the 400 as final and answers a malformed call nothing")
        k(v.get("dropped") == "returned", "…and a 403 drop is final too: no reply, no bounce, no retry")
        k(v.get("no path") == "threw",
          "BOX_URL without /inbound (404) THROWS, so the mail is retried and not silently lost")
        k(v.get("access page") == "threw", "…so does an HTTP 200 that is a login page and not the receiver")
        k(v.get("not ours") == "threw", "…and a 200 whose JSON does not say `stored`")
        k(v.get("access 403") == "threw", "…and a 403 from in front of the receiver, not from it")
        k(v.get("unauthorized") == "threw" and v.get("busy") == "threw" and v.get("tunnel down") == "threw",
          "401, 503 busy and a 502 from the tunnel all throw: ours to fix, and the mail waits")
        k(v.get("unreachable") == "threw", "…as does the box being off the air entirely")

    print("cc-mail selfcheck: %d passed, %d failed" % (n[0] - len(fails), len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(run())
