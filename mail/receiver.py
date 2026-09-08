#!/usr/bin/env python3
"""cc-mail — the box's mail door, inbound only, on loopback.

WHAT IT IS. A Cloudflare Email Worker (`inbound-worker.js`, next to this file) is handed every mail for the
box's mail domain and POSTs it here over HTTPS through a tunnel of its own. This server checks the call, the
sender, the size and a rate limit, writes what passes into ~/.cc/mail/inbox/, and answers the worker in the same
event so the worker can reply "received" to the sender before Cloudflare closes it. Nothing is routed, read or
acted on here — that is milestone 2. See docs/2026-09-08-email.md for the owner's one-time activation.

BINDING IS THE BOUNDARY. It binds 127.0.0.1, never a public interface, not configurable, so no inbound port is
open and the tunnel is the only way in. The shared secret is the second lock: a tunnel published without it, or
any other account on this box, would otherwise be able to POST mail into the inbox. Two locks because they fail
differently, the same reasoning dashboard/server.py's gate has.

THE FROM LINE IS NEVER TRUSTED, AND NEITHER IS THE ENVELOPE. Cloudflare Email Routing has already rejected mail
failing both SPF and DKIM and enforced the sender's DMARC policy before the worker is invoked at all
(developers.cloudflare.com/email-routing/postmaster/). The worker adds no verdict of its own — it would only be
repeating itself — so the verdict travels in the mail's own `Authentication-Results` headers, which this file
re-reads and records. Three things then decide, in this order:
  the SECRET    proves the caller is the worker and nothing else on the box,
  the VERDICT   in Authentication-Results drops a mail that says fail, even from an allow-listed address,
  the IDENTITY  is what the allow-list matches, and it is only ever an address Cloudflare's own verdict
                authenticated — see identity(). `dmarc=pass` means the `From:` header's domain is the one that
                passed, so the From address is the identity; failing that, `spf=pass` authenticates the
                ENVELOPE sender (`X-Mail-From`) and that is the identity; with neither, nothing in the mail is
                authenticated and it is dropped like any other stranger.
                Matching the envelope alone was a hole, and it is the reason this is written out at such
                length: Email Routing rejects a mail only when SPF AND DKIM BOTH fail, so
                `MAIL FROM: <an allow-listed address>` carrying a DKIM-signed `From:` of the attacker's own
                domain arrives here as spf=softfail dkim=pass dmarc=pass — vouched for by Cloudflare, but
                vouched for as somebody else. The identity is what milestone 2 routes on, so it is the
                authenticated one and the envelope is kept beside it under `auth.envelope_from`.

DROPS COME BEFORE REFUSALS, AND THAT ORDERING IS THE PRIVACY RULE. A drop answers 403 with `reply: null` and
the worker sends nothing, so an unknown sender learns nothing at all — not that the address exists, not that
there is an allow-list, not that anything happened. A refusal (too large, too many) does send a one-line reason,
which is only ever seen by someone already on the allow-list. So the allow-list is checked before the size and
the verdict before the rate limit: no path can answer a stranger with a reason.

  cc-mail serve [--port N] [--foreground]   start (or restart): 127.0.0.1:N
  cc-mail stop                              stop it
  cc-mail status                            running? listening where? configured?
  cc-mail list [--n N]                      the last N stored mails, newest first
  cc-mail show <id>                         one mail's message.json on stdout
  cc-mail selfcheck                         tests; own fixtures, no network, no live server, no config of the box's

THE WIRE, which core/mail/inbound-worker.js is written against:
  POST /inbound                             every other method and path is 404
  Authorization: Bearer <MAIL_SECRET>
  Content-Type: message/rfc822
  X-Mail-From: <envelope sender>            message.from in the worker
  X-Mail-To: <envelope recipient>           message.to — the address Cloudflare actually delivered to
  body: the raw RFC822 bytes, unmodified
The answer is always JSON with a `status` and a `reply`. `reply` is either a string the worker relays to the
sender with message.reply(), or null meaning the worker says nothing:
  200 {"status":"stored","id":…,"reply":…}        it is on disk
  401 {"status":"unauthorized","reply":null}      no secret, or the wrong one
  403 {"status":"dropped","reply":null}           the verdict says fail, no authenticated identity, or an
                                                  identity that is not on the allow-list
  413 {"status":"refused","reason":…,"reply":…}   over MAIL_MAX_BYTES, MAIL_MAX_PARTS or MAIL_MAX_ATTACH_BYTES
  429 {"status":"refused","reason":…,"reply":…}   over MAIL_RATE in MAIL_RATE_WINDOW, for this sender
  400 {"status":"refused","reason":…,"reply":null} the call itself was malformed: no X-Mail-From, a
                                                  Content-Length that is not a number, an empty body, or a
                                                  body that would not parse as a mail. `reply` is null on all
                                                  four — none of them is a person's mistake to explain
  503 {"status":"unavailable","reply":null}       MAIL_SECRET is unset on this box: every call is refused
  503 {"status":"busy","reply":null}              MAIL_MAX_CONN connections are already in flight. The worker
                                                  throws on any 503, so the sending server retries later —
                                                  which is what a queue full for a moment should do

THE STORE IS THE CONTRACT MILESTONE 2 READS. One directory per mail:

  ~/.cc/mail/inbox/<id>/
      raw.eml            the bytes as they arrived, byte for byte, and the only complete record
      message.json       the fields below
      attachments/       one file per attachment part, written as bytes

  <id> is `20260908T104512Z-a1b2c3d4`: the UTC second it arrived, then eight random hex, so it sorts by
  arrival and two mails in the same second are still two directories. It is a directory name and never
  anything else. Nothing here promises the hex never repeats: on the one-in-four-billion day it does, the
  rename onto an existing directory fails, this end answers 500 and the worker retries — a new id, no loss.

  message.json:
      id            the <id> above
      from          the AUTHENTICATED identity, and what the allow-list matched: the `From:` header's address
                    when dmarc=pass, otherwise the envelope sender when spf=pass. Never an address nothing
                    vouched for. `auth.identity` says which of the two it was and `auth.envelope_from` keeps
                    the envelope beside it, because the two disagreeing is the interesting case
      to            [addresses]. to[0] is ALWAYS the envelope recipient — the address Cloudflare delivered to,
                    which is what a catch-all makes meaningful and what milestone 2 will route on. The header
                    To: addresses follow it, minus any repeat of it
      cc            [addresses] off the Cc: header
      subject       the decoded Subject:, or ""
      message_id    the Message-ID:, or ""
      in_reply_to   the In-Reply-To:, or ""
      references    [message-ids] off References:
      date          the Date: header, or "". Written back in RFC 5322 form by the parser rather than copied:
                    a date whose weekday disagrees with its day comes out corrected, which is what a reader
                    wants and what raw.eml still has the original of
      text          every text/plain part of the body, decoded and joined. text/html is NEVER rendered or
                    stripped into this field: an HTML part is stored as an attachment like any other bytes
      attachments   [{name, path, size, type}] — `name` is the filename the SENDER gave, kept for milestone 2
                    to show and trusted for nothing; `path` is ours, relative to this directory, and is where
                    the bytes actually are; `size` is bytes on disk; `type` is the part's declared Content-Type
      auth          {results:[the raw Authentication-Results header lines], spf, dkim, dmarc, verdict,
                     header_from, envelope_from, identity}. `verdict` is pass / none / fail, decided by
                     verdict(); `identity` is "header-from" or "envelope", which of the two `from` came from,
                     decided by identity(); `header_from` is the raw `From:` line as written, trusted for
                     nothing; `envelope_from` is what the worker put in X-Mail-From
      received_at   the UTC second the POST was answered, ISO 8601 with a Z

  ATTACHMENTS ARE BYTES AND ARE NEVER OPENED HERE. They are decoded out of their MIME transfer encoding, which
  is what makes them the file the sender sent, and written. Nothing here unzips, parses, renders, executes or
  guesses at one, and the filename the sender chose never reaches the filesystem — see safe_name().

CONFIG, all of it in ~/.cc/config through cc-config, none of it in this file. This directory is published:
nothing here may name the box's domain, its addresses or its people.

READ ONCE, AT STARTUP, and again on SIGHUP (`systemctl --user reload` on the unit that runs `cc-mail serve`,
or `kill -HUP`). cc-config is a subprocess, and reading a key per mail meant five forks per stored mail on a
path an unauthenticated caller reaches — a fork budget behind a public tunnel hostname. So `serve` loads every
key below before it binds, and changing one takes a HUP or a restart. That is the one thing this costs, and
it is written on the reload step of the runbook.
      MAIL_SECRET        the shared secret the worker holds. NO DEFAULT: while it is unset every call is 503
      MAIL_PORT          5220
      MAIL_DOMAIN        the box's mail domain, as a record of which one this door is for. `status` prints it
                         and nothing else reads it: the worker builds its reply out of the address the mail
                         was sent TO, and this server accepts whatever the worker delivered. Deliberately not
                         a blocker — a door that works is not "NOT ready" over a label
      MAIL_ALLOW         the allow-list, comma- or space-separated. Falls back to LESSONS_EMAILS, which is the
                         list the box already keeps of the people it will talk to. An address added here
                         reaches the door on the next HUP or restart, not on the next mail
      MAIL_MAX_BYTES     10485760 (10 MiB), off Content-Length and again on the read
      MAIL_MAX_PARTS     64 MIME parts. A cap on FILES, not bytes: 1 MB of nested multipart parsed to 12,787
                         parts, and one file per part is 12,787 creat()s with the worker's event held open
      MAIL_MAX_ATTACH_BYTES  10485760 (10 MiB) of decoded attachment bytes across the whole mail, counted as
                         they are written. MAIL_MAX_BYTES bounds the wire, this bounds the disk
      MAIL_MAX_CONN      8 connections in flight. Over it, a call waits BUSY_WAIT seconds for a slot and is
                         then answered 503 busy — a bound on threads, memory and open files that a tunnel
                         cannot talk the box out of
      MAIL_RATE          10 mails per sender per window
      MAIL_RATE_WINDOW   3600 seconds
CC_MAIL_DIR moves the whole store, and CC_MAIL_STATE the pid/port/log, which is how the selfcheck runs against
a tree of its own and never this box's inbox.
"""
import binascii
import codecs
import email
import email.policy
import email.utils
import hmac
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

H = os.path.expanduser("~")
MAILDIR = os.environ.get("CC_MAIL_DIR") or os.path.join(H, ".cc", "mail")
STATE = os.environ.get("CC_MAIL_STATE") or os.path.join(H, ".cc", "state", "mail")
INBOX = os.path.join(MAILDIR, "inbox")
RATEFILE = os.path.join(MAILDIR, "rate.json")

BIND = "127.0.0.1"      # NOT configurable, and half the security model: the tunnel is the only way in
PORT = 5220             # 5200 is the dashboard's, 5190 cc-graphs', 5173/5174 vite's, 5201 and 5211 taken
START_WAIT = 5.0        # seconds `serve` waits for the background process before calling it failed
LOGMAX = 300            # a log line is built out of attacker-supplied strings, so it is escaped and cut
LOG_CAP = 4 * 1024 * 1024   # ...and serve.log is rolled at this size, one generation kept. See roll_log()
MAX_BYTES = 10 * 1024 * 1024
MAX_PARTS = 64
MAX_ATTACH_BYTES = 10 * 1024 * 1024
MAX_CONN = 8
BUSY_WAIT = 1.0         # seconds a connection waits for one of those slots before it is answered 503 busy
HEADER_BYTES = 65536    # how much of an OVER-cap mail is still read, so its headers can say who sent it
RATE = 10
RATE_WINDOW = 3600

# A method result that means the mail failed its check. `none` (no policy published), `neutral` and `temperror`
# are not failures and must not be treated as one — a temporary DNS error at Cloudflare would otherwise drop a
# real person's mail silently. `softfail` is SPF's "probably not authorised", and DKIM alone can still carry the
# mail, so it is not fatal on its own either; Cloudflare has already refused anything failing BOTH.
FAIL = ("fail", "permerror")


# ---------------------------------------------------------------- config

CONF_KEYS = ("MAIL_SECRET", "MAIL_PORT", "MAIL_DOMAIN", "MAIL_ALLOW", "LESSONS_EMAILS", "MAIL_MAX_BYTES",
             "MAIL_MAX_PARTS", "MAIL_MAX_ATTACH_BYTES", "MAIL_MAX_CONN", "MAIL_RATE", "MAIL_RATE_WINDOW")
CONF = {}       # what load_config() read. EMPTY means "not loaded": the terminal subcommands ask cc-config


def _from_cc_config(key):
    """One key out of ~/.cc/config, or None if it is not set there. A subprocess, so it happens at startup."""
    try:
        p = subprocess.run(["cc-config", "get", key], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def load_config():
    """Read every key this server uses, once, into CONF. Called by run() before it binds, and on SIGHUP.

    A cc-config call is a fork and an exec. Reading the allow-list, the caps and the rate off it PER MAIL was
    five of them per stored mail, on a path that begins at a public tunnel hostname and runs before the secret
    is even checked — an unauthenticated caller's fork budget, which is the shape of a cheap denial of service
    against the whole box rather than against this door. The cost of reading once is that a config change needs
    a HUP; the runbook says so at the step where the owner changes one.
    """
    global CONF
    CONF = {k: _from_cc_config(k) for k in CONF_KEYS}
    return CONF


def cfg(key, default=""):
    """A config value: the environment first, then what load_config() read (or ~/.cc/config if it has not run),
    then the default.

    Same precedence as cc-config's own, said the same way: a variable that is SET wins even when it is EMPTY, so
    `MAIL_SECRET= cc-mail serve` means "no secret" and refuses everything rather than falling through to the
    file. The environment is read here rather than only in cc-config so the selfcheck can stand up a whole
    configuration without a config file, a PATH or a subprocess.
    """
    v = os.environ.get(key)
    if v is not None:
        return v
    if key in CONF:                     # loaded at startup: no subprocess on the request path
        return default if CONF[key] is None else CONF[key]
    v = _from_cc_config(key)
    return default if v is None else v


def cfg_int(key, default):
    try:
        return int(cfg(key, "").strip() or default)
    except ValueError:
        return default


def allow_list():
    """The addresses the box accepts mail from, lowercased, out of the configuration read at startup.

    MAIL_ALLOW is this door's own key; LESSONS_EMAILS is the fallback because it is the list the box already
    keeps of the people it will talk to, and starting from it means the door works the day it is switched on
    rather than the day somebody remembers a second key. Adding an address reaches the door on the next HUP or
    restart — see load_config() for why it is not re-read per mail.
    """
    raw = cfg("MAIL_ALLOW", "") or cfg("LESSONS_EMAILS", "")
    return {a.strip().lower() for a in re.split(r"[,\s]+", raw) if a.strip()}


# ---------------------------------------------------------------- the pieces the handler is made of

def clip(text):
    """One log line: escaped, then cut.

    Everything in a log line here came off a mail — an address, a subject, a reason. repr() is what stops an
    ANSI sequence reaching the terminal of whoever later cats serve.log, and the cut is what stops a sender
    filling the disk with one header. The cut is taken AFTER repr(), on the bytes that will actually be written:
    repr() turns one hostile byte into four, so cutting first would bound the input and not the log.
    """
    out = repr(text)
    return out if len(out) <= LOGMAX else out[:LOGMAX] + "..."


def addrs(msg, header):
    """Every address in one header, lowercased, in order, without duplicates. A header that is missing, empty or
    unparseable is no addresses — never an exception, because this runs on mail a stranger composed."""
    out = []
    try:
        for _name, a in email.utils.getaddresses(msg.get_all(header, [])):
            a = a.strip().lower()
            if a and a not in out:
                out.append(a)
    except Exception:
        return out
    return out


def header(msg, name):
    """One header as a plain string: decoded, whitespace folded out, or "". Same rule — never raises."""
    try:
        v = msg.get(name)
    except Exception:
        return ""
    return "" if v is None else " ".join(str(v).split())


def verdict(msg):
    """What the mail's own Authentication-Results headers say, and whether that is a fail.

    Cloudflare's inbound MTA stamps this header before the worker runs; it is the only verdict in the system and
    nothing on the box can produce a better one. Every Authentication-Results header is read, not just the first:
    a mail can carry several, and the one that says fail is not reliably the top one.

    verdict: "fail" if any of spf/dkim/dmarc reports a failing result (see FAIL), "pass" if at least one
    reports pass and none failed, "none" if the mail carries no such header at all. `none` is deliberately NOT a
    drop: Cloudflare's own vetting is what stands, and this header is a record of it rather than the check
    itself — a mail that reached the worker without one has still been through Email Routing.
    """
    out = {"results": [], "spf": "", "dkim": "", "dmarc": "", "verdict": "none",
           "header_from": header(msg, "From")}
    try:
        lines = [" ".join(str(v).split()) for v in msg.get_all("Authentication-Results", [])]
    except Exception:
        lines = []
    out["results"] = lines
    joined = "; ".join(lines).lower()
    failed = passed = False
    for method in ("spf", "dkim", "dmarc"):
        # `dkim=pass header.d=x` and `dkim = fail` both, and never `x-dkim=` — the (?<![-\w]) is what stops a
        # method name matching inside a longer word.
        found = re.findall(r"(?<![-\w])%s\s*=\s*([a-z]+)" % method, joined)
        if not found:
            continue
        out[method] = found[0]
        for r in found:
            if r in FAIL:
                failed = True
            elif r == "pass":
                passed = True
    out["verdict"] = "fail" if failed else ("pass" if passed else "none")
    return out


def identity(msg, auth, envelope_from):
    """WHO this mail is from, for the allow-list to match — or "" when nothing in it was authenticated.

    Returns (address, how), `how` being "header-from", "envelope" or "" and going into message.json under
    `auth.identity`. The rule, and every word of it matters:

      dmarc=pass  → the `From:` HEADER address. DMARC passes only when the From domain is ALIGNED with a
                    passing SPF or DKIM, so this is the one address Cloudflare's verdict is about.
      spf=pass    → the ENVELOPE sender. SPF is a statement about MAIL FROM and nothing else, so it
                    authenticates the envelope and says nothing at all about the From header.
      neither     → "" and the mail is dropped.

    Matching the envelope whatever SPF said was the hole this replaces. Email Routing rejects a mail only when
    SPF and DKIM BOTH fail, so `MAIL FROM: <allow-listed@gmail.com>` with a `From:` of the attacker's own
    DKIM-signed domain arrives as spf=softfail dkim=pass dmarc=pass and used to be stored as the allow-listed
    person, with a "received" reply sent to the envelope they chose. Under this rule the identity is the
    attacker's own From address, which is not on the list, and it is dropped.

    `none` on both is a drop as well, and that IS a change: a mail with no Authentication-Results at all no
    longer gets in on the envelope's word. Nothing authenticated it, and the allow-list is the whole gate.

    A sender can WRITE an `Authentication-Results: …; dmarc=pass` header of their own — it is a header like any
    other. It buys them nothing here, and the reason is in verdict(): each method's recorded result is the one
    in the TOP such header, which is Cloudflare's, because an MTA prepends its own; and a `fail` anywhere in
    any of them has already dropped the mail before this function is reached.
    """
    hdr = addrs(msg, "From")
    if auth.get("dmarc") == "pass" and hdr:
        return hdr[0], "header-from"
    if auth.get("spf") == "pass" and envelope_from:
        return envelope_from, "envelope"
    return "", ""


LOG_LOCK = threading.Lock()


def roll_log(stream=None):
    """Roll serve.log when it passes LOG_CAP, keeping one generation. True if it rolled.

    Every log line here is built out of a stranger's mail, and the file is appended to for as long as the box
    runs, so something has to bound it; nothing else rotates it. The roll is a rename plus a dup2 onto the fd
    the process is already writing to, which is what makes it work while threads are mid-write: they hold the
    fd, not the file.

    It only ever touches the file that IS serve.log — samestat, not a path comparison — so a terminal, a pipe
    and the selfcheck's captured stderr are all left alone.
    """
    stream = sys.stderr if stream is None else stream
    try:
        fd = stream.fileno()
        st = os.fstat(fd)
    except (OSError, ValueError, AttributeError):
        return False
    if not stat.S_ISREG(st.st_mode) or st.st_size < LOG_CAP:
        return False
    with LOG_LOCK:
        try:
            if not os.path.samestat(os.fstat(fd), os.stat(logfile())):
                return False        # stderr is some other file: not ours to rename
            if os.fstat(fd).st_size < LOG_CAP:
                return False        # another thread rolled it while we waited
            os.replace(logfile(), logfile() + ".1")
            new = os.open(logfile(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.dup2(new, fd)
            finally:
                os.close(new)
        except OSError:
            return False            # a log that cannot be rolled must not stop a mail being answered
    return True


class Refuse(Exception):
    """A mail that is well formed and from an allow-listed person but over one of the caps, discovered while it
    was being written. It carries the one-line reason the sender gets, and store() has already cleaned up."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def safe_decode(body, charset):
    """Bytes decoded as `charset`, the way a sender's own mail declared it — or as utf-8 with errors=replace
    when that label is one Python's codecs module has never heard of. `charset` is attacker-supplied text:
    `iso-8859-8-i`, `unknown-8bit`, `x-unknown` and plenty of real mail carry a charset label with no codec
    behind it at all, and `.decode()` raises LookupError for every one of them — uncaught, that took the whole
    mail down with a 500 (store()'s rmtree undoes the write, do_POST answers 500, and the sending server just
    retries the same mail until it burns this sender's MAIL_RATE allowance). So the label is proven with
    codecs.lookup() before it is trusted; the bytes are never lost, only the label is downgraded."""
    charset = charset or "utf-8"
    try:
        codecs.lookup(charset)
        return body.decode(charset, "replace")
    except LookupError:            # no codec behind the label — or a registered one that is not a TEXT codec
        return body.decode("utf-8", "replace")   # (`hex`, `base64`, `rot13`: lookup passes, decode still raises)


def safe_name(name, n):
    """A filename WE choose, from one the sender chose. The sender's name is used for nothing but the hint.

    An attachment filename is attacker-supplied text: `../../.ssh/authorized_keys`, `-rf`, a NUL, 4 KB of
    unicode, or nothing at all. So the part index leads (it is unique on its own, and it keeps the order the
    mail had), and only [A-Za-z0-9._-] survives out of the sender's name, cut to 80. The original is kept
    verbatim in message.json's `name` for milestone 2 to display and to trust for nothing.
    """
    base = re.sub(r"[^A-Za-z0-9._-]", "_", (name or "").strip())[:80].lstrip(".")
    return "%03d-%s" % (n, base or "part")


def parse(msg, who, auth, envelope_to, mail_id, received_at, attach_dir):
    """The stored form of one mail: message.json's dict, with the attachments already written to attach_dir.

    The message arrives already parsed (do_POST needs the headers to decide anything at all, and parsing a
    hostile mail twice is a cost paid for nothing). `who` is the authenticated identity from identity(), which
    is what `from` becomes, and `auth` is the verdict dict that decided it.

    Raises Refuse when the attachment bytes pass MAIL_MAX_ATTACH_BYTES: the total is counted as each part is
    decoded, before it is written, so the cap bounds what reaches the disk rather than what is found there
    afterwards.
    """
    cap = cfg_int("MAIL_MAX_ATTACH_BYTES", MAX_ATTACH_BYTES)
    to = [envelope_to] if envelope_to else []
    for a in addrs(msg, "To"):
        if a not in to:
            to.append(a)
    text, attachments, n, total = [], [], 0, 0
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        ctype = (part.get_content_type() or "application/octet-stream").lower()
        disp = (part.get_content_disposition() or "").lower()
        try:
            body = part.get_payload(decode=True)
        except Exception:
            body = None
        if body is None:                       # a part with no decodable payload is nothing to store
            continue
        # The body is text/plain that is not an attachment. Everything else — text/html included — is bytes.
        if ctype == "text/plain" and disp != "attachment":
            text.append(safe_decode(body, part.get_content_charset()))
            continue
        n += 1
        total += len(body)
        if total > cap:
            raise Refuse("attachments too large: over %d bytes in total" % cap)
        rel = os.path.join("attachments", safe_name(part.get_filename(), n))
        path = os.path.join(attach_dir, os.path.basename(rel))
        with open(path, "wb") as f:            # bytes, written. Never opened, unpacked, rendered or run
            f.write(body)
        attachments.append({"name": part.get_filename() or "", "path": rel,
                            "size": len(body), "type": ctype})
    return {"id": mail_id, "from": who, "to": to, "cc": addrs(msg, "Cc"),
            "subject": header(msg, "Subject"), "message_id": header(msg, "Message-ID"),
            "in_reply_to": header(msg, "In-Reply-To"),
            "references": [r for r in header(msg, "References").split() if r],
            "date": header(msg, "Date"), "text": "\n".join(text), "attachments": attachments,
            "auth": auth, "received_at": received_at}


def store(raw, msg, who, auth, envelope_to):
    """Write one mail and return its message.json dict. The directory appears complete or not at all.

    The id directory is built under a `.` name and renamed into place at the end, because milestone 2 will watch
    this directory: a reader that lists inbox/ must never see a mail whose raw.eml is half written. rename() on
    the same filesystem is the only step that has to be atomic, and it is.
    """
    mail_id = "%s-%s" % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
                         binascii.hexlify(os.urandom(4)).decode())
    final = os.path.join(INBOX, mail_id)
    tmp = os.path.join(INBOX, "." + mail_id)
    os.makedirs(os.path.join(tmp, "attachments"), exist_ok=True)
    try:
        with open(os.path.join(tmp, "raw.eml"), "wb") as f:
            f.write(raw)
        rec = parse(msg, who, auth, envelope_to, mail_id,
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    os.path.join(tmp, "attachments"))
        with open(os.path.join(tmp, "message.json"), "w") as f:
            json.dump(rec, f, indent=1)
        os.rename(tmp, final)
    except BaseException:
        # A mail that breaks the parser, or trips the attachment cap half way through, must not leave its half
        # of itself on the disk for ever. The `.` name is already invisible to every reader, so this is about
        # the bytes, not about what anyone can see.
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return rec


RATE_LOCK = threading.Lock()


def rate_ok(sender, now=None):
    """Has this sender sent fewer than MAIL_RATE mails in the last MAIL_RATE_WINDOW seconds? Counts this one.

    The counter is per SENDER, not per box: one person's burst must not shut the door on everybody else. It is
    kept in one small JSON file rather than in memory so a restart does not hand a sender a fresh allowance —
    the door is restarted by hand and by the unit's Restart=on-failure, and either would otherwise be a reset.
    The lock is this process's: the server is threaded, and two mails from the same sender arriving together
    would otherwise both read the same count and both be allowed.
    """
    now = time.time() if now is None else now
    limit, window = cfg_int("MAIL_RATE", RATE), cfg_int("MAIL_RATE_WINDOW", RATE_WINDOW)
    with RATE_LOCK:
        try:
            with open(RATEFILE) as f:
                seen = json.load(f)
        except (OSError, ValueError):
            seen = {}
        if not isinstance(seen, dict):
            seen = {}
        # Prune every sender, not just this one, or the file grows for as long as the box runs.
        seen = {k: [t for t in v if isinstance(t, (int, float)) and now - t < window]
                for k, v in seen.items() if isinstance(v, list)}
        mine = seen.get(sender, [])
        if len(mine) >= limit:
            seen = {k: v for k, v in seen.items() if v}
            _write_rate(seen)
            return False, limit, window
        mine.append(now)
        seen[sender] = mine
        _write_rate({k: v for k, v in seen.items() if v})
        return True, limit, window


def _write_rate(seen):
    os.makedirs(MAILDIR, exist_ok=True)
    tmp = RATEFILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(seen, f)
        os.rename(tmp, RATEFILE)
    except OSError:
        pass        # a counter that cannot be written must not refuse a real mail; the caps above still hold


# ---------------------------------------------------------------- the server

class Handler(BaseHTTPRequestHandler):
    server_version = "cc-mail"
    sys_version = ""
    # A caller that opens a connection, promises a Content-Length and then sends nothing holds a thread for as
    # long as it likes, and this server makes one thread per connection. socketserver puts this on the socket,
    # so a stalled read gives up rather than parking. 30 s is far more than the worker's POST ever needs.
    timeout = 30

    def log_request(self, code="-", size="-"):
        """Nothing. Every request that matters writes exactly ONE line of its own, in do_POST, and the default
        would put a second one next to it — which is the difference between "an unknown sender is dropped with
        one log line" and a log that says twice as much about a stranger as the rule allows."""

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), clip(fmt % a)))

    def say(self, what):
        """The one line this request leaves behind. Written before the answer, so a mail that crashes the store
        is still in the log, and the log is rolled here because this is the only thing that grows it."""
        sys.stderr.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), what))
        sys.stderr.flush()
        roll_log()

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def dropped(self, why, sender):
        """403 and `reply: null`: the worker sends nothing, so whoever this was learns nothing — not that the
        address exists, not that there is a list. One log line, and it is the only record."""
        self.say("drop %s from=%s" % (why, clip(sender)))
        self._json(403, {"status": "dropped", "reply": None})

    def refused(self, code, reason, sender):
        """A refusal is only ever sent to somebody already on the allow-list, which is why it may carry a
        reason at all: the checks that answer a stranger have all run before any of these."""
        self.say("refuse %s from=%s" % (clip(reason), clip(sender)))
        self._json(code, {"status": "refused", "reason": reason, "reply": reason})

    def do_GET(self):
        # There is nothing to read here. Not a health endpoint either: `cc-mail status` is on the box, and an
        # endpoint that answers before the secret is checked is one more thing the tunnel exposes.
        self._json(404, {"status": "not found", "reply": None})

    do_HEAD = do_PUT = do_DELETE = do_PATCH = do_GET

    def do_POST(self):
        if self.path.split("?")[0] != "/inbound":
            return self._json(404, {"status": "not found", "reply": None})

        # 1. THE CALL. A secret that is unset is not "allow everything": while the box has none, the door is
        # shut and says so, the same way the dashboard's gate 503s until it is configured.
        secret = cfg("MAIL_SECRET", "")
        if not secret:
            self.say("refuse no-secret-configured")
            return self._json(503, {"status": "unavailable", "reply": None})
        given = self.headers.get("Authorization") or ""
        given = given[7:] if given[:7].lower() == "bearer " else ""
        # compare_digest, not ==: a byte-by-byte comparison that returns early tells a caller with a stopwatch
        # how much of the secret it has right.
        # BOTH SIDES ENCODED FIRST. compare_digest raises TypeError on a str holding a non-ASCII character, and
        # `given` is a raw request header — so `Authorization: Bearer s\xfc` killed the handler thread with an
        # uncaught traceback in serve.log and no answer at all, from an anonymous caller, before the secret was
        # even compared. On bytes it just returns False, which is the whole point of the check.
        if not hmac.compare_digest(given.encode("utf-8", "replace"), secret.encode("utf-8", "replace")):
            self.say("refuse bad-secret path=%s" % clip(self.path))
            return self._json(401, {"status": "unauthorized", "reply": None})

        sender = (self.headers.get("X-Mail-From") or "").strip().lower()
        rcpt = (self.headers.get("X-Mail-To") or "").strip().lower()
        if not sender:
            self.say("refuse no-envelope-sender")
            return self._json(400, {"status": "refused", "reason": "no envelope sender", "reply": None})

        # 2. THE BODY, bounded. Content-Length decides how much is read and MAIL_MAX_BYTES bounds that, so a
        # 500 MB body costs 10 MiB and not a byte more. The mail has to be read before the sender can be
        # decided at all, because the identity is in the mail and not in the envelope the caller wrote — and it
        # is not answered with the 413 until the identity IS decided, or the reason would reach a stranger.
        cap = cfg_int("MAIL_MAX_BYTES", MAX_BYTES)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self.say("refuse bad-content-length from=%s" % clip(sender))
            return self._json(400, {"status": "refused", "reason": "bad Content-Length", "reply": None})
        # An over-cap mail is still read as far as its headers, and only that far: the 413 below carries a
        # reason, so it may only be sent to somebody the headers identify as allow-listed. Truncating at `cap`
        # alone would cut the Authentication-Results off a mail whose cap is small, leaving a real person's
        # oversize mail dropped in silence instead of answered.
        raw = self.rfile.read(min(length, max(cap, HEADER_BYTES)))
        if not raw:
            self.say("refuse empty-body from=%s" % clip(sender))
            return self._json(400, {"status": "refused", "reason": "empty message", "reply": None})
        try:
            # Parsed ONCE, here, and handed to store() later: the verdict, the identity and the part count are
            # all read off this one object. The headers a truncated over-cap body still carries are enough for
            # all three, and it is refused below anyway.
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            auth = verdict(msg)
        except Exception:
            self.say("refuse unparseable from=%s" % clip(sender))
            return self._json(400, {"status": "refused", "reason": "message did not parse", "reply": None})

        # 3. THE VERDICT, a DROP, so it comes before anything that carries a reason.
        if auth["verdict"] == "fail":
            return self.dropped("auth-%s" % clip("spf=%s dkim=%s dmarc=%s"
                                                 % (auth["spf"], auth["dkim"], auth["dmarc"])), sender)

        # 4. THE SENDER: who the mail is authenticated as, then whether that address is on the list. Never the
        # envelope on its own — see identity(). Both outcomes are drops, so a stranger still learns nothing.
        who, how = identity(msg, auth, sender)
        if not who:
            return self.dropped("unauthenticated-sender spf=%s dmarc=%s" % (clip(auth["spf"]), clip(auth["dmarc"])),
                                sender)
        auth["envelope_from"], auth["identity"] = sender, how
        if who not in allow_list():
            return self.dropped("unknown-sender", who)

        # 5. THE CAPS, which are refusals with a reason and so all come after the allow-list. Size first, off
        # the length the caller declared; then the number of MIME parts, because one file per part is what a
        # 1 MB mail turns into 12,787 of.
        if length > cap:
            return self.refused(413, "message too large: %d bytes, the limit is %d" % (length, cap), who)
        maxparts = cfg_int("MAIL_MAX_PARTS", MAX_PARTS)
        parts = sum(1 for p in msg.walk() if p.get_content_maintype() != "multipart")
        if parts > maxparts:
            return self.refused(413, "too many parts: %d, the limit is %d" % (parts, maxparts), who)

        # 6. THE RATE, per authenticated sender.
        ok, limit, window = rate_ok(who)
        if not ok:
            return self.refused(429, "too many messages: the limit is %d in %d seconds" % (limit, window),
                                who)

        # 7. STORE, and answer in the same event so the worker can still reply.
        try:
            rec = store(raw, msg, who, auth, rcpt)
        except Refuse as e:         # over MAIL_MAX_ATTACH_BYTES, found while writing; store() cleaned up
            return self.refused(413, e.reason, who)
        except Exception as e:      # one broken mail must not take the door down for the next one
            self.say("error store from=%s %s: %s" % (clip(who), type(e).__name__, clip(str(e))))
            return self._json(500, {"status": "error", "reason": "could not store", "reply": None})
        self.say("store id=%s from=%s(%s) to=%s bytes=%d attachments=%d auth=%s subject=%s"
                 % (rec["id"], clip(who), how, clip(rcpt), len(raw), len(rec["attachments"]),
                    rec["auth"]["verdict"], clip(rec["subject"])))
        self._json(200, {"status": "stored", "id": rec["id"],
                         "reply": "Received. It is in the queue as %s." % rec["id"]})


class Server(ThreadingHTTPServer):
    """ThreadingHTTPServer with a ceiling on how many connections are in flight at once.

    One thread per connection with no bound is a public tunnel hostname's worth of threads, sockets and memory
    for whoever can reach it, and every one of them can hold its slot for `Handler.timeout` seconds by simply
    not sending anything. MAIL_MAX_CONN slots; a connection over the ceiling waits BUSY_WAIT seconds for one
    (a burst is a normal thing and should queue, not fail) and is then answered 503 busy and closed. The
    worker throws on a 503, so the sending server retries the mail later.

    The slot is taken BEFORE the thread is made and given back when that thread ends, which is why it is
    released in process_request_thread and not in shutdown_request — shutdown_request also runs on the path
    that never took one.
    """

    daemon_threads = True
    BUSY = (b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json; charset=utf-8\r\n"
            b"Content-Length: 31\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"
            b'{"status":"busy","reply":null}\n')

    def __init__(self, *a, **kw):
        self.slots = threading.BoundedSemaphore(max(1, cfg_int("MAIL_MAX_CONN", MAX_CONN)))
        super().__init__(*a, **kw)

    def process_request(self, request, client_address):
        if not self.slots.acquire(timeout=BUSY_WAIT):
            sys.stderr.write("%s refuse busy\n" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            sys.stderr.flush()
            try:
                request.sendall(self.BUSY)
            except OSError:
                pass
            return self.shutdown_request(request)
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


# ---------------------------------------------------------------- lifecycle

def flags(argv):
    """--k v and bare --k, the same parser dashboard/server.py and cc-graphs have."""
    opt, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opt[a] = argv[i + 1]
                i += 1
            else:
                opt[a] = a
        else:
            opt.setdefault("_", []).append(a)
        i += 1
    return opt


def pidfile():
    return os.path.join(STATE, "serve.pid")


def portfile():
    return os.path.join(STATE, "serve.port")


def logfile():
    return os.path.join(STATE, "serve.log")


def running():
    """The pid of this server, or None. The cmdline check is what stops a recycled pid reading as running, and
    what stops `cc-mail status` reading itself as the server it is asking about: only `serve` ever becomes one,
    and the path is resolved because the systemd unit execs ~/bin/cc-mail, a symlink to this file."""
    try:
        with open(pidfile()) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            cmdline = f.read()
    except OSError:
        return None
    args = [a.decode("utf-8", "replace") for a in cmdline.split(b"\0") if a]
    if "serve" not in args:
        return None
    me = os.path.realpath(__file__)
    return pid if any(os.path.realpath(a) == me for a in args) else None


def stop(_opt=None, quiet=False):
    pid = running()
    if not pid:
        if not quiet:
            print("cc-mail: not running")
    else:
        os.kill(pid, signal.SIGTERM)
        for _ in range(40):
            if not running():
                break
            time.sleep(0.1)
        if running():
            os.kill(pid, signal.SIGKILL)
        if not quiet:
            print("cc-mail: stopped (pid %d)" % pid)
    for p in (pidfile(), portfile()):
        try:
            os.remove(p)
        except OSError:
            pass
    return 0


def blockers():
    """What stands between this server and a mail it would store, in the words the runbook uses. Named here so
    `status` and the startup line say the same thing, and so the activation fails at the step that is wrong
    rather than at a 503 an hour later."""
    out = []
    if not cfg("MAIL_SECRET", ""):
        out.append("MAIL_SECRET is not set: every call is refused 503")
    if not allow_list():
        out.append("no allow-list: set MAIL_ALLOW (or LESSONS_EMAILS) or every mail is dropped")
    return out


def status(_opt=None):
    gaps = blockers()
    print("cc-mail: config %s" % ("ready" if not gaps else "NOT ready: " + "; ".join(gaps)))
    print("cc-mail: domain %s" % (cfg("MAIL_DOMAIN", "") or "(MAIL_DOMAIN not set — a label only, see the runbook)"))
    print("cc-mail: store %s (%d mails)"
          % (INBOX, len(os.listdir(INBOX)) if os.path.isdir(INBOX) else 0))
    pid = running()
    if not pid:
        print("cc-mail: not running")
        return 1
    try:
        with open(portfile()) as f:
            at = f.read().strip()
    except OSError:
        at = "?"
    print("cc-mail: running (pid %d) on http://%s:%s/inbound" % (pid, BIND, at))
    return 0


def on_hup(*_):
    """SIGHUP: read the configuration again. This is how an address added to the allow-list reaches a door that
    is already open (`systemctl --user kill --signal=HUP` on the unit that runs `cc-mail serve`), and it is
    the whole cost of reading the config once instead of per mail. The slot ceiling is not among it: the
    server sized itself when the port opened, and only a restart changes that."""
    load_config()
    sys.stderr.write("%s reload config\n" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    sys.stderr.flush()


def run(port):
    os.makedirs(STATE, exist_ok=True)
    os.makedirs(INBOX, exist_ok=True)
    load_config()                           # every key, once, before the port is open. See load_config()
    srv = Server((BIND, port), Handler)
    where = str(srv.server_address[1])      # what was BOUND, not what was asked: `--port 0` means "any free one"
    with open(pidfile(), "w") as f:
        f.write(str(os.getpid()))
    with open(portfile(), "w") as f:
        f.write(where)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGHUP, on_hup)
    sys.stderr.write("cc-mail: listening on http://%s:%s/inbound (store %s)\n" % (BIND, where, INBOX))
    for g in blockers():
        sys.stderr.write("cc-mail: %s\n" % g)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()


def serve(opt):
    port = int(opt.get("--port") or cfg("MAIL_PORT", "") or PORT)
    stop(opt, quiet=True)                   # serve is a restart; "not running" is not news to whoever ran it
    os.makedirs(STATE, exist_ok=True)
    if "--foreground" in opt:
        return run(port)
    log = logfile()
    argv = [sys.executable, os.path.realpath(__file__), "serve", "--port", str(port), "--foreground"]
    with open(log, "ab") as out:
        subprocess.Popen(argv, stdout=out, stderr=out, stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + START_WAIT
    while time.time() < deadline and not running():
        time.sleep(0.1)
    if not running():
        print("cc-mail: failed to start — see %s" % log, file=sys.stderr)
        return 1
    return status()


# ---------------------------------------------------------------- the store, from a terminal

def ids():
    """Stored mails, newest first. A directory whose name starts with `.` is one store() is still writing."""
    try:
        return sorted((d for d in os.listdir(INBOX) if not d.startswith(".")), reverse=True)
    except OSError:
        return []


def cmd_list(opt):
    n = int(opt.get("--n") or 20)
    for i in ids()[:n]:
        try:
            with open(os.path.join(INBOX, i, "message.json")) as f:
                m = json.load(f)
        except (OSError, ValueError):
            print("%-30s (unreadable)" % i)
            continue
        print("%-30s %-28s %2d att  %s"
              % (i, m.get("from", "")[:28], len(m.get("attachments") or []), (m.get("subject") or "")[:48]))
    return 0


def cmd_show(opt):
    args = opt.get("_") or []
    # The id is a directory name and is checked as one: `show ../../.ssh` must read nothing.
    if len(args) != 1 or args[0] not in ids():
        print("usage: cc-mail show <id>   (cc-mail list)", file=sys.stderr)
        return 2
    with open(os.path.join(INBOX, args[0], "message.json")) as f:
        print(f.read())
    return 0


def main(argv):
    cmds = {"serve": serve, "stop": stop, "status": status, "list": cmd_list, "show": cmd_show}
    cmd = argv[0] if argv else ""
    if cmd == "selfcheck":
        sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
        import selfcheck as sc               # noqa: E402  — sibling module, so the ~/bin symlink works
        return sc.run()
    if cmd not in cmds or "--help" in argv or "-h" in argv:
        print(__doc__.strip(), file=sys.stderr if cmd not in cmds else sys.stdout)
        return 2 if cmd not in cmds else 0
    return cmds[cmd](flags(argv[1:]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
