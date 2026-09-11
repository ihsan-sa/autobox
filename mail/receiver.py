#!/usr/bin/env python3
"""cc-mail — the box's mail door: a server for what comes in, and one subcommand for a mail the box starts.

WHAT IT IS. A Cloudflare Email Worker (`inbound-worker.js`, next to this file) is handed every mail for the
box's mail domain and POSTs it here over HTTPS through a tunnel of its own. This server checks the call, the
sender, the size and a rate limit, writes what passes into ~/.cc/mail/inbox/, and answers the worker in the same
event so the worker can reply "received" to the sender before Cloudflare closes it.

WHERE THE MAIL THEN GOES IS NOT DECIDED HERE. Once it is stored, this server puts the id on the cc-slack
daemon's socket and that is its whole part in delivery: core/mail/router.py decides which channels the mail
belongs in and the daemon posts and delivers them. This process holds no Slack token and makes no Slack call.
The daemon's answer is what the sender hears back, so a refusal ("That address is not one I route") reaches
them; a daemon that is down costs the delivery and not the mail. See docs/2026-09-08-email.md.

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
The stored mail's answer (`reply` in the 200, which the worker sends back to the sender) is the box's ACK — for a
held mail the only word its sender gets until a person decides — and it is written to ~/.cc/mail/out.log as an
`ack` line beside every mail that goes out, so one file shows all of what a sender was sent (acked()).

  cc-mail serve [--port N] [--foreground]   start (or restart): 127.0.0.1:N
  cc-mail stop                              stop it
  cc-mail status                            running? listening where? configured?
  cc-mail list [--n N]                      the last N stored mails, newest first
  cc-mail show <id>                         one mail's message.json on stdout
  cc-mail selfcheck                         tests; own fixtures, no network, no live server, no config of the box's
  cc-mail send --json FILE                  mail somebody the box is NOT replying to. FILE (`-` = stdin) is one
                                            JSON object: {"to": "A" or ["A","B"], "subject": "S", "body": "TEXT",
                                            "attachments": ["/abs/path", ...], "thread": "<chat_id>/<thread_ts>"}
                                            — those five keys and no others; attachments and thread may be
                                            left out. Every file named is attached, or the mail is not sent
                                            and the line names the file and why (a file attaches only from
                                            under MAIL_OUT_ROOTS or ~/.cc/slack/files, and under the byte
                                            cap). `thread` is the Slack thread the mail is started from —
                                            the chat_id and thread_ts off the message's tag — and the answer
                                            lands there (see below). One line either way — stdout when the
                                            mail went, stderr and exit 1 when it did not, exit 2 when the ask
                                            itself was malformed. From a session with a channel, or with a
                                            thread, the line ends with where the mail's thread is
  cc-mail send --to A[,B] --subject S [--body TEXT] [--thread <chat_id>/<thread_ts>]
                                            the same with no files: the body is --body, or stdin without it

SENDING IS THE ONLY THING HERE THAT IS NOT THE SERVER'S. `send` runs in the terminal it was typed in, talks to
the Cloudflare Worker and not to this server, and is the only way into core/mail/outbound.py's cold path — the
daemon does not have one, so no mail's body, no member and no Slack message can start a mail. It goes only to
an address on MAIL_SEND_ALLOW (MAIL_ALLOW when that is unset), which is the owner's own set of verified
destinations, and it is charged the same caps and written to the same ~/.cc/mail/out.log as a reply. It comes
From the sending SESSION'S OWN channel address, `<channel>@MAIL_DOMAIN`, when the session has one (a track
worker's `#<repo>--<track>`, an orch's channel) so the answer lands in that channel's mirror thread; a session
with no channel of its own — a repo's main session, the box session, a plain shell — sends From home@ (or
MAIL_SEND_FROM). Which it is comes off where the command runs, never off the ask (outbound.session_channel).
A MAIL FROM A CHANNEL GETS A THREAD THERE: once it is away, `send` hands it to the daemon (`mailed` on the
owner socket) which posts one line in that channel — `email to `a@b` · subject` — and writes the conversation
that line is the root of, so the person's answer is routed under it rather than opening a new thread (owner,
2026-09-10). A MAIL STARTED FROM A THREAD IS ANSWERED IN IT: `thread` names the Slack thread the session was
asked in (the `<channel>` tag's chat_id and thread_ts), the line goes UNDER that thread and the thread's root
becomes the record's, so the answer lands where the ask was — for any session, the planning seat included,
whose From stays home@ (owner, 2026-09-11: his answer to a mail started from his thread opened a new one).
The thread is named by the caller and never guessed: the thread a session last heard from is not the one it
is writing from once it acts on its own, and an orch shares its record with the repo's seat. A thread that
is already a mail's own is refused — answer that mail in its thread instead. The daemon down costs the line
and the thread, not the mail, and `send` says so. home@ mail with no thread has no line, and its answer
arrives as a new mail, as before.

THE WIRE, which core/mail/inbound-worker.js is written against:
  POST /inbound                             every other method and path is 404
  Authorization: Bearer <MAIL_SECRET>
  Content-Type: message/rfc822
  X-Mail-From: <envelope sender>            message.from in the worker
  X-Mail-To: <envelope recipient>           message.to — the address Cloudflare actually delivered to
  body: the raw RFC822 bytes, unmodified
The answer is always JSON with a `status` and a `reply`. `reply` is either a string the worker relays to the
sender with message.reply(), or null meaning the worker says nothing:
  200 {"status":"stored","id":…,"reply":…}        it is on disk. `reply` is the router's line when the daemon
                                                  answered — where it went, or why it went nowhere — and
                                                  "Received. It is in the queue as <id>." when it did not
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
                    stripped into this field — the HTML goes to `html` as it was written
      html          the mail's inline text/html parts, decoded and joined, cut at MAX_HTML characters. This is
                    the copy of the body every mail client sends beside the text: it is BODY, not a file, so it
                    is not in `attachments` and nothing is written to disk for it. "" when there is none, and
                    the only field that can be cut — raw.eml has all of it. Never rendered, opened or fetched
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
      MAIL_DOMAIN        the box's mail domain. This server accepts whatever the worker delivered and never
                         checks it; the ROUTER reads it, because `<channel>@<domain>` is only a channel name
                         when the domain is ours. Unset, every address reads as somebody else's and only the
                         reply thread of a mail already routed still works. `status` prints it
      MAIL_WORKSPACE     the owner's override table, `addr=owner` / `addr=<handle>` rows separated by commas
                         or newlines, read by the router before it asks Slack who an address is. A row with an
                         empty value (`addr=`) refuses that address. His word, and it outranks the lookup.
                         The only key here this process never loads: the daemon reads it, so a change takes
                         the daemon's restart and not this one's HUP
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
import socket
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
MAX_HTML = 256 * 1024   # how much of an inline text/html body is kept in message.json. raw.eml has all of it
MAX_CONN = 8
BUSY_WAIT = 1.0         # seconds a connection waits for one of those slots before it is answered 503 busy
HEADER_BYTES = 65536    # how much of an OVER-cap mail is still read, so its headers can say who sent it
RATE = 10
RATE_WINDOW = 3600

# The daemon's own socket (cc-slack). It is how a stored mail reaches the session it is for without a second
# Slack connection: this process holds no token and makes no Slack call of its own — it hands over an id.
SLACKSOCK = os.path.join(os.environ.get("CC_SLACK_DIR") or os.path.join(H, ".cc", "slack"), "sock")
ROUTE_WAIT = 25         # seconds to wait for the routing answer, which rides inside the worker's own event

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
    text, html, attachments, n, total = [], [], [], 0, 0
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
        # THE BODY IS NOT AN ATTACHMENT. text/plain the sender did not attach is `text`, and the text/html
        # copy of it beside it — inline, unnamed, which is how every mail client writes the alternative — is
        # `html`. Counting that copy made every mail from Gmail a mail with a file in it, and the vetting read
        # duly held them all for the owner (2026-09-09). What is still a file, counted and written: a part
        # whose disposition says `attachment`, a part the sender NAMED, and anything that is not text.
        if ctype == "text/plain" and disp != "attachment":
            text.append(safe_decode(body, part.get_content_charset()))
            continue
        if ctype == "text/html" and disp != "attachment" and not part.get_filename():
            html.append(safe_decode(body, part.get_content_charset()))
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
            "date": header(msg, "Date"), "text": "\n".join(text),
            "html": "\n".join(html)[:MAX_HTML], "attachments": attachments,
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


def acked(mail_id, who, reply):
    """The worker's immediate reply is the box's ACK to a sender — for a held mail the only word they get until
    a person decides (owner, 2026-09-09: 'at least an ack ... or telling me to check slack') — and it leaves as
    this handler's answer, not through outbound.send, so out.log showed nothing for it and a held sender read
    as never written to. One `ack` line there, in the file every mail that goes out is written to. Best
    effort: the log is never the mail, and a log that will not write costs the line and nothing else."""
    try:
        import outbound                      # noqa: E402 — a sibling, imported here for this one line
        outbound.log("%s: ack to=%s by=worker: %s" % (mail_id, who, reply))
    except Exception:
        pass


def routed(mail_id):
    """Hand the stored mail to the daemon. Gives back (the line the sender should hear, a word for the log).

    ONE REQUEST STILL LEAVES ONE LOG LINE — the word comes back to the caller instead of being written here,
    because "what happened to this mail" is one sentence and splitting it over two lines is how a log stops
    being readable per mail.

    THE DECISION IS NOT MADE HERE, and neither is any Slack call: this process has no token and never gets one.
    It puts an id on the daemon's socket (`{"mail": "<id>"}`, an owner verb) and the daemon does the rest —
    core/mail/router.py decides, cc-slack posts the mirror line and delivers. The answer comes back inside this
    same HTTP event, which is what lets a refusal ("That address is not one I route") reach the sender.

    EVERY FAILURE IS QUIET TOWARDS THE SENDER. No daemon, no socket, a timeout, an answer that is not JSON:
    the line comes back empty and the caller falls to "Received. It is in the queue as <id>.", which is true.
    Routing that did not happen is this box's problem to read in `route=` in the log, not a stranger's to be
    handed a reason for."""
    try:
        answer = daemon({"mail": mail_id})
    except Exception as e:
        return "", "unreachable %s" % clip(str(e))
    if not answer.get("ok"):
        return "", "failed %s" % clip(str(answer.get("error") or answer))
    return answer.get("reply") or "", "yes" if answer.get("routed") else "nowhere"


def daemon(req):
    """One request on cc-slack's owner socket, one JSON answer back. Raises on no daemon, a timeout or an
    answer that is not JSON — each caller says what that costs in its own words."""
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    c.settimeout(ROUTE_WAIT)
    try:
        c.connect(SLACKSOCK)
        c.sendall((json.dumps(req) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            d = c.recv(65536)
            if not d:
                break
            buf += d
    finally:
        c.close()
    return json.loads(buf or b"{}")


def mirrored(ask):
    """outbound.send_to's `mirror`, for `cc-mail send`: the mail is away, so hand it to the daemon's `mailed`
    verb, which posts one line in the sending session's channel — or under the thread the ask names — and
    writes the conversation whose root the person's answer will land under. Returns the tail of cc-mail's own
    line: where the thread is, or why there is none. A daemon that is down or refuses costs the thread, never
    the mail, and says so: an answer to a mail with no thread opens a new one, as before."""
    thread = ask.get("thread") or {}
    where = "#%s" % ask.get("channel") if not thread else "the thread %s/%s" % (thread.get("chat"), thread.get("ts"))
    try:
        answer = daemon({"mailed": ask})
    except Exception as e:
        return ". No line in %s — the channel daemon did not answer (%s), so a reply opens a new thread" % (
            where, clip(str(e)))
    if not answer.get("ok"):
        return ". No line in %s — %s, so a reply opens a new thread" % (
            where, clip(str(answer.get("error") or "the daemon refused")))
    if thread:
        return ". Its line is in your thread in #%s, and the answer lands there" % (answer.get("name") or thread.get("chat"))
    return ". Its thread is in #%s" % (answer.get("name") or ask.get("channel"))


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

        # 7. STORE, ROUTE, and answer in the same event so the worker can still reply. Store first and always:
        # a mail on disk is the promise this door makes, and routing is what happens to a mail that is already
        # kept. So a daemon that is down costs the delivery and not the mail — `cc-mail list` still has it.
        try:
            rec = store(raw, msg, who, auth, rcpt)
        except Refuse as e:         # over MAIL_MAX_ATTACH_BYTES, found while writing; store() cleaned up
            return self.refused(413, e.reason, who)
        except Exception as e:      # one broken mail must not take the door down for the next one
            self.say("error store from=%s %s: %s" % (clip(who), type(e).__name__, clip(str(e))))
            return self._json(500, {"status": "error", "reason": "could not store", "reply": None})
        line, why = routed(rec["id"])
        self.say("store id=%s from=%s(%s) to=%s bytes=%d attachments=%d auth=%s route=%s subject=%s"
                 % (rec["id"], clip(who), how, clip(rcpt), len(raw), len(rec["attachments"]),
                    rec["auth"]["verdict"], why, clip(rec["subject"])))
        reply = line or "Received. It is in the queue as %s." % rec["id"]
        acked(rec["id"], who, reply)
        self._json(200, {"status": "stored", "id": rec["id"], "reply": reply})


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


# The keys the cold send reads. NOT in CONF_KEYS: the server never sends, so it has no reason to hold a send
# secret in memory for the life of a process that answers a public tunnel. `send` reads them per run instead,
# which costs a few forks in a command a person typed and means an owner's edit is live on the next one.
SEND_KEYS = ("MAIL_SEND_URL", "MAIL_SEND_SECRET", "MAIL_DOMAIN", "MAIL_SEND_FROM", "MAIL_SEND_ALLOW",
             "MAIL_ALLOW", "MAIL_OUT_PER_HOUR", "MAIL_OUT_PER_DAY", "MAIL_OUT_ROOTS", "MAIL_OUT_MAX_ATTACH_BYTES")
SEND_JSON_KEYS = ("to", "subject", "body", "attachments", "thread")
SEND_USAGE = ("usage: cc-mail send --json FILE   (FILE or `-`: {\"to\", \"subject\", \"body\", \"attachments\": [...], "
              "\"thread\": \"<chat_id>/<thread_ts>\"})\n"
              "       cc-mail send --to A[,B] --subject S [--body TEXT] [--thread <chat_id>/<thread_ts>]   "
              "(body on stdin without --body)")
# The thread a mail is started from, as the session's `<channel>` tag names it: the chat id (or `#name`) and
# the thread's ts. Read here so a malformed one is exit 2 with the shape, never a mail with no thread.
THREAD_RE = re.compile(r"^(#?[A-Za-z0-9][A-Za-z0-9_-]*)/(\d+\.\d+)$")


def thread_of(value):
    """(chat, ts) off a `thread` value, None for none, or a str saying what was wrong with it."""
    v = str(value or "").strip()
    if not v:
        return None
    m = THREAD_RE.match(v)
    if not m:
        return "cc-mail send: thread must be <chat_id or #channel>/<thread_ts>, as the message's tag names them"
    return m.group(1), m.group(2)


def arg(opt, name):
    """One --flag's value, or "". flags() gives a bare `--to` its own name back, which is not an address."""
    v = opt.get(name) or ""
    return "" if v == name else v.strip()


def send_ask(opt):
    """The (to, subject, body, attachments, thread) a `cc-mail send` asks for, or a str saying what was wrong
    with the ask. Two shapes: `--json FILE` — one object, the five SEND_JSON_KEYS and no others, so a mistyped
    key (`attachment`, `file`) is refused by name rather than silently dropped — and the flag form, text only.
    `thread` is (chat, ts) or None either way (thread_of).

    The owner's shape (2026-09-09): "the model just gives a json with subject and body etc and then points to
    attachments and the script does the rest so it's more consistent". The JSON is the whole ask; nothing
    about the mail is decided here, only read."""
    src = arg(opt, "--json")
    if src:
        try:
            doc = json.loads(sys.stdin.read() if src == "-" else open(os.path.expanduser(src), encoding="utf-8").read())
        except (OSError, ValueError) as e:
            return "cc-mail send: cannot read %s as JSON — %s" % (src, e)
        if not isinstance(doc, dict):
            return "cc-mail send: the JSON must be one object with " + ", ".join(SEND_JSON_KEYS)
        odd = sorted(set(doc) - set(SEND_JSON_KEYS))
        if odd:
            return "cc-mail send: unknown key %s — the keys are %s" % (", ".join(odd), ", ".join(SEND_JSON_KEYS))
        to, atts = doc.get("to"), doc.get("attachments") or []
        if not isinstance(atts, list) or not all(isinstance(a, str) and a.strip() for a in atts):
            return "cc-mail send: attachments must be a list of file paths"
        if isinstance(to, list):
            to = ",".join(str(a) for a in to)
        if not str(to or "").strip():
            return "cc-mail send: no \"to\""
        body = doc.get("body")
        if body is not None and not isinstance(body, str):
            return "cc-mail send: body must be a string"
        raw = doc.get("thread")
        if raw is not None and not isinstance(raw, str):
            return "cc-mail send: thread must be a string, <chat_id>/<thread_ts>"
        thread = thread_of(raw)
        if isinstance(thread, str):
            return thread
        return str(to), str(doc.get("subject") or ""), body or "", atts, thread
    to, subject = arg(opt, "--to"), arg(opt, "--subject")
    body = opt.get("--body")
    body = "" if body is None or body == "--body" else body
    if not to:
        return SEND_USAGE
    thread = thread_of(arg(opt, "--thread"))
    if isinstance(thread, str):
        return thread
    if not body:
        if sys.stdin.isatty():
            return "cc-mail send: no body — pass --body TEXT, or pipe one in"
        body = sys.stdin.read()
    return to, subject, body, [], thread


def cmd_send(opt):
    """`cc-mail send` — one mail the box starts. outbound.send_to() decides everything; this reads the ask.

    A malformed ask is exit 2 and a line saying what was wrong — including a terminal with neither --body nor
    stdin, which is told so rather than left waiting on a tty. Exit 1 is the mail's own refusal, from send_to()."""
    ask = send_ask(opt)
    if isinstance(ask, str):
        print(ask, file=sys.stderr)
        return 2
    to, subject, body, attachments, thread = ask
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import outbound                          # noqa: E402 — a sibling, imported here for cc-mail's own reason
    # The From is the session's own channel's address when it has one, home@ when it does not — read off where
    # this command runs (session_channel), never off the ask: there is no key or flag for it (owner, 2026-09-10).
    # `mirrored` runs once the mail is away, for a session with a channel and for a mail that names the thread
    # it is started from: the line in that channel (under that thread) and the conversation its answer threads
    # under (the daemon's `mailed` verb). home@ with no thread gets neither, as before.
    ok, line = outbound.send_to({k: cfg(k, "") for k in SEND_KEYS}, to, subject, body, attachments=attachments,
                                channel=outbound.session_channel(), mirror=mirrored, thread=thread)
    print(line, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def main(argv):
    cmds = {"serve": serve, "stop": stop, "status": status, "list": cmd_list, "show": cmd_show,
            "send": cmd_send}
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
