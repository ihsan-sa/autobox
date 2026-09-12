#!/usr/bin/env python3
"""The way out — the box's own mail. Two ways in, and they are deliberately not the same shape. Milestone 4.

WHAT IT IS. Milestone 2 gave every mail a mirror thread in Slack and wrote the conversation to disk
(core/mail/router.py, ~/.cc/mail/conv/). This file is the tap on that thread: a message or a file the BOX posts
in it IN ANSWER TO A MAIL goes out as a mail in the same conversation — threaded on the mail's own Message-ID,
reply-all to the addresses that mail carried, From the address it was sent to. So a person who mails a brief
gets the session's answer without ever opening Slack.

THE REPLY'S MEDIUM FOLLOWS THE MESSAGE IT ANSWERS (owner, 2026-09-10). A post carries the ts of the message it
answers — the reply tool's `ts` — and `by_mail()` asks whether THAT message arrived by mail: the mirror line of
any mail on the conversation (the thread's root, or a later mail's line under it, which take_mail records in the
conversation's `mirrors`). Only then does the post travel. A post answering a Slack message in the thread — the
owner talking to the session there — stays in Slack, and so does a post that answers nothing at all: progress,
a note, a line for the channel. Before this rule every post in a mirror thread went out, and four Slack answers
in one thread were four mails in the sender's inbox. The explicit way to mail is unchanged: answer the mail's
own line (the root), or `cc-mail send`.

WHERE THE TAP IS. `post()` and `upload_file()` in core/bin/cc-slack, which are the one place everything the box
says goes through — Daemon.say, `cc-slack post`, the member socket's `reply` verb and a session's reply tool all
land there, and a PERSON'S Slack message never does. That is why "only the box's own posts go out" needs no
check of its own: a human message is not a post of ours and never reaches this file. The mail door's OWN lines
are the exception and pass `mail=False` at their call sites — the mirror line, the move offer, a move/hold/drop
answer and the not-sent note below are machinery for the person reading the channel, not the box replying to
the sender, and mailing them would echo a sender's mail back at them or name channels they cannot see.

THE RECIPIENTS ARE THE MAIL'S OWN, AND ARE FIXED BEFORE ANY SESSION RUNS. `recipients()` reads only the
conversation record M2 wrote at the mirror's creation: the mail's From, its To and its Cc, minus every address
on our own domain. Nothing here reads the reply text, a session's words, a mail body or any table a session can
write. A session cannot mail a new person through this, and there is no argument on any function here it could
use to try — `send()` is handed a channel and a thread, and the addresses come off the disk record those two
name.

  ROLE "to" ONLY. A conversation's roots are the channels the mail reached: `to` was delivered it, `cc` is
  watching. Only a `to` root speaks for the box, so a reply in a channel that was merely copied stays in Slack.

A MAIL THE BOX STARTS is the second way in and the whole of the difference. `send_to()` at the bottom takes an
address, a subject and a text, with no mail behind it — the box mailing somebody first. Two callers, both a
`cc-mail send` somebody typed: on this box's own terminal, which is the owner and the sessions running as him;
and inside a member workspace, where the command has no secret and no worker to talk to, so it hands the ask
across the member socket and the daemon's `send` verb calls this on the host FOR that workspace — From the
workspace's own address, its own files only, the same list and the same caps (owner, 2026-09-11: "all
workspaces should be able to send emails, it's a critical path"). Nothing a mail's body says and no Slack
message can start one: the daemon runs this on that verb alone, for the handle the socket belongs to. The
address is checked against the verified list BEFORE anything goes on the wire (see verified()), so a recipient
nobody meant is one line in the log rather than a POST somebody has to notice; Cloudflare's own set of verified
destinations is the second gate and refuses whatever the first let through. Everything after that check is the
reply path's, unchanged: the same worker, the same secret, the same two caps, the same log.

ONLY OUR OWN FILES ARE ATTACHED, AND THE FILE IS OPENED ONCE. `attach_bytes()` opens the path with O_NOFOLLOW
and then decides everything on that one fd — regular file, under the byte cap, and its real place (read off
/proc/self/fd) inside the workspace's own trees (MAIL_OUT_ROOTS, narrowed to `<root>/<handle>` for a member,
plus that workspace's Slack files dir — see in_workspace). Nothing is checked by path and re-opened
afterwards: the member owns that name and could swap a secret in between. A FILE EITHER ARRIVES AS A FILE, OR
THE CALLER AND THE THREAD ARE TOLD IT DID NOT (owner, 2026-09-09: "Attachements dont always work well"). On
the reply path a file that is not ours, or one over the cap, is one 📎 line in the thread naming it and the
reason: when MAIL_OUT_LINKS maps the path to a URL the mail still goes, carrying a LINK LINE in the file's
place, and the thread's line says it went as a link; when nothing maps it NOTHING is mailed and the line says
where to put the file. A cold mail (`cc-mail send --json`) names its files up front, and one that cannot go
stops the whole send with the file and the reason — see send_to(). Neither path ever says "sent" about a
file it dropped.

SENDING IS OFF UNTIL CONFIGURED. With no MAIL_SEND_URL or no MAIL_SEND_SECRET every call is a no-op that logs
one line per process and nothing else — the reply is in Slack and the thread says nothing about mail, because
nothing was promised. Turning it on is a step of the owner's runbook (docs/2026-09-08-email.md) and never a
landing's.

CAPS REFUSE IN THE THREAD, THEY DO NOT QUEUE. Over any cap, or on any refusal from Cloudflare, the reply stays
in Slack, one line in the thread says the mail was not sent and why, and the log says the same. There is one
attempt per post and no retry anywhere in this file: a mail that did not go is a line a person can read, not a
job that keeps running.

THE WIRE, which the `fetch` half of core/mail/inbound-worker.js is written against:
  POST <MAIL_SEND_URL>
  Authorization: Bearer <MAIL_SEND_SECRET>
  Content-Type: application/json
  {"from": "<an address on the box's mail domain>",
   "to":   ["<recipient>", ...],          every recipient, explicitly — the worker never reads one out of `raw`
   "raw":  "<base64 of the whole RFC822 message>"}
  200 {"ok": true,  "sent": [...], "failed": [{"to":…, "error":…}, ...]}
  400/401/403 {"ok": false, "error": "…"}   a malformed call, a wrong secret, a From that is not on the domain
`failed` is Cloudflare's own refusal — an unverified destination address, a daily limit — and it is shown in the
thread and logged. It is never a silent drop.

CONFIG, all of it in ~/.cc/config, read by cc-slack and handed here as a dict:
      MAIL_SEND_URL      the worker's send path, https://<worker>/send. Unset = sending is off
      MAIL_SEND_SECRET   the box's half of the shared secret. Unset = sending is off. NOT the same value as
                         MAIL_SECRET: that one proves the WORKER is calling the box, this one proves the box is
                         calling the worker, and one secret doing both jobs means a leak in either direction
                         costs both
      MAIL_DOMAIN        the box's mail domain (M2's key). Our own addresses are dropped from every recipient
                         list off this, which is what stops the box mailing itself in a loop
      MAIL_SEND_ALLOW    the addresses a mail the box STARTS may go to — the destinations Cloudflare has
                         verified in the account, which is all its SEND binding can deliver to. Commas or
                         whitespace. Unset falls back to MAIL_ALLOW, the people already allowed to mail the
                         box: mailing them first opens nothing that answering them did not. Both unset = no
                         cold mail goes anywhere. Replies are NOT filtered by it — they go where the mail they
                         answer came from, and Cloudflare refuses an address it has not verified
      MAIL_SEND_FROM     the address a cold mail comes From when the session sending it has no channel of its
                         own, which must be on MAIL_DOMAIN. Unset = home@ that domain, the address the door
                         already receives on, so an answer to a cold mail arrives back here and is routed like
                         any other. A session WITH a channel of its own — a track worker, an orch — never uses
                         it: its cold mail comes From <channel>@MAIL_DOMAIN, the address the router already
                         maps back to that channel, so an answer lands in that channel's mirror thread
                         (session_channel, cold_from; owner, 2026-09-10)
      MAIL_OUT_PER_HOUR  6 mails per mirror thread per hour, and 6 cold mails an hour for the whole box
      MAIL_OUT_PER_DAY   30 mails per recipient per day, counted across both paths
      MAIL_OUT_MAX_ATTACH_BYTES  8388608 (8 MiB) per file. Over it a reply's file is a 📎 line in the thread
                         (and a link line in the mail when MAIL_OUT_LINKS has a URL for it) and a cold mail is
                         refused, naming the file
      MAIL_OUT_ROOTS     ~/dev:~/.cc/worktrees — the trees a file may be attached from, colon-separated. A
                         member's workspace is narrowed to `<root>/<handle>` inside them. The workspace's own
                         Slack files dir (~/.cc/slack/files; a member's member dir) is always one more
      MAIL_OUT_LINKS     `<path prefix>=<url base>` rows, comma- or newline-separated, the same shape as
                         MAIL_WORKSPACE. A file under a prefix that cannot be attached goes as a URL in a link
                         line; one under no prefix is not mailed at all, and the thread is told
State is ~/.cc/mail/out/rate.json (the two caps' clocks) and the log is ~/.cc/mail/out.log — its own file, not
the daemon's, because `cc-slack post` on the command line has no daemon log to write to.
"""
import base64
import email.message
import email.utils
import fcntl
import json
import mimetypes
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.request

H = os.path.expanduser("~")
MAILDIR = os.environ.get("CC_MAIL_DIR") or os.path.join(H, ".cc", "mail")
OUTDIR = os.path.join(MAILDIR, "out")
RATEFILE = os.path.join(OUTDIR, "rate.json")
LOGFILE = os.path.join(MAILDIR, "out.log")

PER_HOUR = 6            # mails per mirror thread per hour
PER_DAY = 30            # mails per recipient per day
MAX_ATTACH = 8 * 1024 * 1024
SEND_TIMEOUT = 45       # seconds for the whole call to the worker. One attempt, no retry
USER_AGENT = "cc-mail/1 (+box)"  # urllib's default UA is banned in front of the Worker (Cloudflare 1010)
LOGMAX = 400            # a log line carries addresses and a worker's error string, so it is escaped and cut
BODYMAX = 60 * 1024     # of reply text put in one mail. A session that pastes a file into a message is not one

_UNCONFIGURED_SAID = [False]   # the "sending is off" line, once per process — see log_once()


def _router():
    """core/mail/router.py, its sibling. Imported on use so that importing this file costs nothing on a box
    where the mail door was never installed, which is the same reason cc-slack imports both lazily."""
    d = os.path.dirname(os.path.realpath(__file__))
    if d not in sys.path:
        sys.path.insert(0, d)
    import router
    return router


# ---------------------------------------------------------------- config, log, state

def cfg_int(cfg, key, default):
    try:
        n = int(str(cfg.get(key) or "").strip())
    except ValueError:
        return default
    return n if n > 0 else default


def clip(text):
    """One log line, out of strings a sender and a worker chose. Newlines would forge a second line."""
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(text))
    return s[:LOGMAX] + ("…" if len(s) > LOGMAX else "")


def log(line):
    try:
        os.makedirs(MAILDIR, exist_ok=True)
        with open(LOGFILE, "a") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write("%s\tout\t%s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), clip(line)))
    except OSError:
        pass


def log_once(line):
    """The unconfigured no-op's line. Once per process: a daemon that posts a hundred times with sending off
    should say so once, and a fresh `cc-slack post` saying it again is a new process and a new reader."""
    if _UNCONFIGURED_SAID[0]:
        return
    _UNCONFIGURED_SAID[0] = True
    log(line)


def configured(cfg):
    return bool((cfg.get("MAIL_SEND_URL") or "").strip() and (cfg.get("MAIL_SEND_SECRET") or "").strip())


def _rate_read():
    try:
        with open(RATEFILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _rate_write(d):
    os.makedirs(OUTDIR, exist_ok=True)
    tmp = RATEFILE + ".tmp"
    with open(tmp, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        json.dump(d, f)
    os.replace(tmp, RATEFILE)


def _rate_lock():
    os.makedirs(OUTDIR, exist_ok=True)
    f = open(os.path.join(OUTDIR, ".rate.lock"), "a")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def _prune(stamps, now, window):
    return [t for t in stamps if isinstance(t, (int, float)) and now - t < window]


def caps(cfg, key, rcpts, now=None):
    """The two clocks, checked and CHARGED together. Returns "" when the mail may go, or the one line saying
    which cap stopped it. Charging inside the same lock is what stops two sessions replying at once from both
    reading "5 of 6" and both sending.

    THE THREAD'S CAP IS CHECKED FIRST because it is the one a runaway session hits: a loop posting in one
    thread is many mails to the same few people, and stopping it at the thread costs one line, where stopping
    it per recipient would spend the day's budget of everyone on the mail first."""
    now = time.time() if now is None else now
    ph, pd = cfg_int(cfg, "MAIL_OUT_PER_HOUR", PER_HOUR), cfg_int(cfg, "MAIL_OUT_PER_DAY", PER_DAY)
    with _rate_lock():
        d = _rate_read()
        threads, people = dict(d.get("thread") or {}), dict(d.get("rcpt") or {})
        mine = _prune(threads.get(key) or [], now, 3600)
        if len(mine) >= ph:
            return "%d mails already went out of this thread in the last hour (MAIL_OUT_PER_HOUR=%d)" % (len(mine), ph)
        # the COUNT is the one on disk, not the cap: after the owner lowers MAIL_OUT_PER_DAY the two differ,
        # and a line telling somebody a number the box never counted is worse than no line
        over = [(a, len(_prune(people.get(a) or [], now, 86400))) for a in rcpts]
        over = [(a, n) for a, n in over if n >= pd]
        if over:
            return "%s already had %d mails today (MAIL_OUT_PER_DAY=%d)" % (over[0][0], over[0][1], pd)
        threads[key] = mine + [now]
        for a in rcpts:
            people[a] = _prune(people.get(a) or [], now, 86400) + [now]
        _rate_write({"thread": threads, "rcpt": people})
    return ""


# ---------------------------------------------------------------- who the mail is for

def _norm(addr):
    return email.utils.parseaddr(str(addr or ""))[1].strip().lower()


def ours(addr, domain):
    d = (domain or "").strip().lower().lstrip("@")
    a = _norm(addr)
    return bool(d) and a.endswith("@" + d)


def recipients(rec, domain):
    """(to, cc) — reply-all, off the conversation record and off nothing else.

    To  = the mail's From, then its To. Cc = the mail's Cc. Every address on OUR domain is dropped from both:
    `to[0]` is always the address the mail was delivered to (receiver.py's contract), so keeping it would mail
    the box itself and every reply would arrive as a new mail and be replied to again.
    Each address appears once, in the order it was recorded, and an address in both fields is a To."""
    seen, to, cc = set(), [], []
    fields = [(rec.get("from") or "", to)] + [(a, to) for a in (rec.get("to") or [])] \
        + [(a, cc) for a in (rec.get("cc") or [])]
    for raw, out in fields:
        a = _norm(raw)
        if not a or a in seen or ours(a, domain):
            continue
        seen.add(a)
        out.append(a)
    return to, cc


def from_addr(rec, domain):
    """The address the mail was sent TO, which is what we answer from. Empty when it is not on our own domain —
    a conversation whose envelope recipient we do not own is not one this box may put a From on."""
    a = _norm((rec.get("to") or [""])[0])
    return a if ours(a, domain) else ""


COLD_LOCAL = "home"     # the local part a cold mail comes From when MAIL_SEND_FROM is unset


def verified(cfg):
    """The addresses a mail the box STARTS may go to. A list, lowercased, in the order the owner wrote them.

    This is the whole of what keeps `send_to()` from being a relay. Cloudflare will deliver only to a
    destination address verified in the account, so the box cannot mail a stranger whatever it asks for — but
    the ask would still leave this machine, and a refusal that arrives from Cloudflare is a refusal nobody sees
    until they read the log. So the same set is kept here and checked first, and an address that is not on it
    costs one line and no POST.

    MAIL_ALLOW is the fallback because it is the set the box already exchanges mail with: those people can mail
    the box and the box already answers them by mail, so mailing them FIRST opens nothing that replying did
    not. Both keys unset means no cold mail goes anywhere, which is the state of a box that never set this up.

    Our own domain is dropped from it. An address of ours would be the box mailing its own door, and the answer
    to that mail is another mail into the same door — a loop, and one paid for at Cloudflare's end."""
    raw = (cfg.get("MAIL_SEND_ALLOW") or "").strip() or (cfg.get("MAIL_ALLOW") or "")
    domain = cfg.get("MAIL_DOMAIN") or ""
    out = []
    for piece in re.split(r"[,\s]+", raw):
        a = _norm(piece)
        if a and a not in out and not ours(a, domain):
            out.append(a)
    return out


SLACKDIR = os.environ.get("CC_SLACK_DIR") or os.path.join(H, ".cc", "slack")
DEV = os.path.join(H, "dev")
CHAN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")   # a channel name as the router reads one off an address (router.py)


def session_channel(cwd=None, env=None, slack_dir=None):
    """The channel THIS SESSION owns — a name without the `#` — or "" for a session that has none.

    "The From is derived from the session's channel by the box, never typed by the caller" (owner, 2026-09-10).
    So it is read off where the process runs, the same two facts cc-slack's detect_target and Channel read to
    place a session, and no argument names it: a track worktree carries the `.cc/track` marker `cc` wrote
    (`<repo> <track>`, found up the tree from cwd) and that session's channel is `#<repo>--<track>`; an orch
    carries CC_SLACK_ALIAS (set by `cc <repo> --orch`) and its channel is the one the daemon opened for it,
    on record in ~/.cc/slack/orchs.json under the repo and the alias. Both are names the router maps straight
    back to that channel (`<channel>@` in core/mail/router.py), so an answer lands in its mirror thread.

    "a session with no channel of its own (planning seat, box session) keeps home@": a repo's main session
    answers "" — #<repo> is the project's channel, where the owner steers, not that session's own — and so do
    the box session, a shell with no session behind it, and an orch whose channel is archived or unrecorded."""
    env = os.environ if env is None else env
    d = os.path.realpath(cwd or os.getcwd())
    x, target = d, ""
    while x and x != "/":
        marker = os.path.join(x, ".cc", "track")
        if os.path.isfile(marker):
            try:
                with open(marker) as f:
                    parts = f.read().split()
            except OSError:
                parts = []
            target = "/".join(parts[:2]) if len(parts) >= 2 else ""
            break
        x = os.path.dirname(x)
    if not target:
        if d.startswith(DEV + os.sep):
            target = d[len(DEV) + 1:].split(os.sep)[0]
        elif d not in (DEV, H):
            target = (env.get("CC_SLACK_TARGET") or "").strip()
    if "/" in target:                   # a track is its own session whatever alias its shell inherited (cc: track before alias)
        name = target.replace("/", "--", 1).lower()   # the channel was made lower-cased (cc-slack mkchannel)
        return name if CHAN_RE.fullmatch(name) else ""
    alias = (env.get("CC_SLACK_ALIAS") or "").strip()
    if alias and target:
        try:
            with open(os.path.join(slack_dir or SLACKDIR, "orchs.json")) as f:
                orchs = json.load(f)
        except (OSError, ValueError):
            orchs = {}
        for e in (orchs.values() if isinstance(orchs, dict) else []):
            if (isinstance(e, dict) and not e.get("archived") and e.get("target") == target
                    and e.get("alias") == alias and CHAN_RE.fullmatch(str(e.get("name") or ""))):
                return str(e["name"])
    return ""                           # a repo's main session, the box, a plain shell: no channel of its own


def cold_from(cfg, channel=""):
    """The From of a mail the box starts, or "" when there is none it may use.

    `channel` is the sending session's own channel (session_channel), and when there is one the From is
    <channel>@<MAIL_DOMAIN> — "the address the router already maps back to that channel, so an answer lands in
    that channel's mirror thread" (owner, 2026-09-10). It stays on MAIL_DOMAIN whatever MAIL_SEND_FROM says.

    Without one: MAIL_SEND_FROM when it is set and on our own domain — the worker refuses any other From
    anyway, so an address off the domain is caught here where the reason can be said. Unset, it is
    home@<MAIL_DOMAIN>: the address the door already receives on, so an answer to a cold mail comes back
    through the door and is routed like any other mail rather than bouncing off an address nothing listens to."""
    domain = (cfg.get("MAIL_DOMAIN") or "").strip().lower().lstrip("@")
    channel = (channel or "").strip().lstrip("#").lower()
    if channel and domain:
        return channel + "@" + domain
    a = _norm(cfg.get("MAIL_SEND_FROM") or "")
    if a:
        return a if ours(a, domain) else ""
    return COLD_LOCAL + "@" + domain if domain else ""


# ---------------------------------------------------------------- the text and the file

_MRKDWN = (
    (re.compile(r"```(?:[a-z]*\n)?(.*?)```", re.S), r"\1"),      # a code block is its own lines
    (re.compile(r"`([^`\n]+)`"), r"\1"),
    (re.compile(r"<(https?://[^|>]+)\|([^>]*)>"), r"\2 (\1)"),   # a Slack link keeps both halves
    (re.compile(r"<(https?://[^>]+)>"), r"\1"),
    (re.compile(r"<mailto:[^|>]+\|([^>]*)>"), r"\1"),
    (re.compile(r"<#[^|>]+\|([^>]*)>"), r"#\1"),                 # a channel link is its name
    (re.compile(r"<#([^|>]+)>"), r"#\1"),
    (re.compile(r"<@([^|>]+)(?:\|[^>]*)?>"), r"@\1"),
    (re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])"), r"\1"),    # *bold* and _italic_ are the words themselves
    (re.compile(r"(?<![\w_])_([^_\n]+)_(?![\w_])"), r"\1"),
    (re.compile(r"^&gt; ?", re.M), "> "),
)


def plain(text):
    """The reply as written, with Slack's markup taken off — no HTML part is built anywhere in this file, so
    this IS the mail. Nothing is added and nothing is summarised: what the thread says is what is sent."""
    s = str(text or "")
    for pat, rep in _MRKDWN:
        s = pat.sub(rep, s)
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return s.strip()[:BODYMAX]


def _roots(cfg):
    raw = (cfg.get("MAIL_OUT_ROOTS") or "").strip() or os.path.join(H, "dev") + ":" + os.path.join(H, ".cc", "worktrees")
    return [os.path.realpath(os.path.expanduser(p)) for p in raw.split(":") if p.strip()]


def in_workspace(real, rec, cfg):
    """Is this REAL path inside the workspace's own tree? A member's workspace is narrowed to their own
    directory under each root, so one member's file can never leave in another's mail. The caller passes a
    path it has already resolved — this function resolves nothing, so it cannot be raced.

    THE WORKSPACE'S SLACK FILES DIR IS ONE OF ITS TREES (2026-09-09, the owner's spreadsheet; 2026-09-10, a
    PDF): a file a person uploads into a thread is downloaded there, and it is the one place the `file` tool
    reads from besides a session's own folder — so it was exactly the ordinary way a file reached a mail
    thread, and the one way it could not travel. It is the files dir of THIS workspace and no other."""
    for base in bases(rec, cfg):
        if real == base or real.startswith(base.rstrip("/") + "/"):
            return True
    return False


def files_dir(ws, slack_dir=None):
    """The Slack files directory of one workspace — where cc-slack downloads what a person uploads into a
    thread, and where the `file` tool reads from. The owner's is ~/.cc/slack/files; a member's is the `files/`
    of their own member dir (cc-slack's member_dir), which their boundary sees AS ~/.cc/slack/files."""
    ws = (ws or "").strip()
    d = slack_dir or SLACKDIR
    return os.path.join(d, "files") if ws in ("", "owner") else os.path.join(d, "member", ws, "files")


def bases(rec, cfg):
    """Every directory a file may be attached from for this conversation's workspace, resolved: each of
    MAIL_OUT_ROOTS (narrowed to `<root>/<handle>` for a member) and that workspace's own Slack files dir."""
    ws = (rec.get("workspace") or "").strip()
    out = [root if ws in ("", "owner") else os.path.join(root, ws) for root in _roots(cfg)]
    return out + [os.path.realpath(files_dir(ws))]


NOT_OURS = "not in a tree a mail may attach from"
TOO_BIG = "too large to attach"


def attach_bytes(path, rec, cfg, cap):
    """The bytes to attach, read from ONE open file descriptor, or (None, why) when the file does not travel.

    THE FILE IS OPENED ONCE AND NEVER RE-OPENED. Checking a path and then opening it is two lookups of the
    same name, and a member who can write in their own workspace owns what that name means in between: swap
    the file for a symlink after the check and any file the daemon can read leaves the box as an attachment;
    swap in a huge one and the daemon reads it unbounded. So everything is decided on the fd itself —
    O_NOFOLLOW refuses a symlink as the last component, os.fstat says it is a regular file and how big it
    was, /proc/self/fd/<n> says where that fd actually is (which catches a symlinked DIRECTORY on the way,
    which O_NOFOLLOW does not), and the read stops at cap+1 bytes so a file that grew after the fstat is
    still capped. The bytes handed back are the ones the checks were made against."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None, NOT_OURS          # missing, unreadable, a symlink, a directory — none of them travel
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None, NOT_OURS
        try:
            real = os.readlink("/proc/self/fd/%d" % fd)
        except OSError:
            return None, NOT_OURS      # no /proc, no proof of where this fd is: it does not leave
        if real.endswith(" (deleted)") or not in_workspace(real, rec, cfg):
            return None, NOT_OURS
        if st.st_size > cap:
            return None, TOO_BIG       # the common case, and no byte of it is read
        data = b""
        while len(data) <= cap:
            chunk = os.read(fd, cap + 1 - len(data))
            if not chunk:
                break
            data += chunk
        if len(data) > cap:
            return None, TOO_BIG       # it grew between the fstat and the read
        return data, ""
    except OSError:
        return None, NOT_OURS
    finally:
        os.close(fd)


def link_for(path, cfg):
    """The URL for a file we are not attaching, or "". MAIL_OUT_LINKS rows are `<path prefix>=<url base>`; the
    longest matching prefix wins, so a row for a project inside a published tree beats the tree's own row."""
    real = os.path.realpath(path)
    best = ("", "")
    for row in re.split(r"[,\n]", cfg.get("MAIL_OUT_LINKS") or ""):
        pre, _, base = row.partition("=")
        pre, base = os.path.realpath(os.path.expanduser(pre.strip())) if pre.strip() else "", base.strip()
        if not pre or not base:
            continue
        if (real == pre or real.startswith(pre.rstrip("/") + "/")) and len(pre) > len(best[0]):
            best = (pre, base.rstrip("/") + "/" + os.path.relpath(real, pre))
    return best[1]


def human_size(n):
    """`40 KB`, `12.3 MB` — never `0.0 MB` for a file that is merely small, which read as if it were empty
    (the owner's spreadsheet, 2026-09-09)."""
    n = int(n or 0)
    if n >= 1024 * 1024:
        return "%.1f MB" % (n / (1024 * 1024))
    return "%d KB" % max(1, round(n / 1024)) if n else "0 bytes"


def link_line(path, cfg, why):
    """The line a mail carries instead of a file, when MAIL_OUT_LINKS gives it a URL. It names the file, says
    WHICH reason kept it out — out of tree (NOT_OURS) and over the cap (TOO_BIG) are two different fixes — and
    carries the URL. Never a filesystem path: a path on this box is no use to a reader and says more about the
    box than it should."""
    return "[%s — %s, %s]" % (os.path.basename(path), why, link_for(path, cfg))


def not_attached(path, rec, cfg, why, cap):
    """The one line the THREAD gets when a file the box posted did not go as a file: the file, the reason and
    what fixes it. Row a-file-the-box-sends-actually-arrives: 'a file that genuinely may not travel produces a
    failure the caller sees and a line in the thread saying so' — before this the log said "not inside the
    workspace's own tree" and then "sent", and the session believed it had delivered a file."""
    name = clip(os.path.basename(path))
    if why == TOO_BIG:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        return "📎 %s (%s) is over the %s attachment cap" % (name, human_size(size), human_size(cap))
    return "📎 %s is not in a tree a mail may attach from — put it under %s" % (name, trees(rec, cfg))


def trees(rec, cfg):
    """bases(), as a person reads them: `~/dev or ~/.cc/worktrees or ~/.cc/slack/files`."""
    return " or ".join(p.replace(H, "~", 1) if p == H or p.startswith(H + "/") else p for p in bases(rec, cfg))


# ---------------------------------------------------------------- the message

def subject_of(rec):
    s = (rec.get("subject") or "").strip() or "(no subject)"
    return s if re.match(r"^\s*re:", s, re.I) else "Re: " + s


LOCAL_MAX = 64          # octets in a local part (RFC 5321 4.5.3.1.1) — a longer one is refused by many an MTA


def tagged(addr, tag):
    """`local+tag@domain` — the address a cold mail asks to be answered at (RFC 5233 subaddressing). The
    router strips the `+tag` to name the channel and reads the tag to name the conversation (router.addressed,
    router.conv_for_reply). "" when there is no tag or no address, and "" when the tagged local part would
    pass LOCAL_MAX — a track's channel name can run to 60 characters on its own, and an address the recipient's
    server refuses would lose the answer altogether; such a mail carries no tag and its answer is matched
    the other way (router.started_match)."""
    local, sep, dom = _norm(addr).rpartition("@")
    if not (tag and sep and local) or len(local) + 1 + len(tag) > LOCAL_MAX:
        return ""
    return "%s+%s@%s" % (local, tag, dom)


def build(rec, from_a, to, cc, text, attach=None, mid=None, now=None, subject=None, reply_to=""):
    """The whole RFC822 message, as bytes, plus the Message-ID it carries.

    THREADING IS THE POINT OF THE HEADERS. In-Reply-To names the LAST mail of the conversation — the one this
    reply answers — and References carries the chain plus that id, which is what puts our mail under the
    sender's own thread in their client rather than beside it.

    The Message-ID we mint is handed back so `send()` can put it in the conversation's own `message_ids`. On
    the REPLY path that is enough: the person's next mail carries References, and their own first mail's id
    is in it. It is NOT enough for a mail the box starts: the relay behind MAIL_SEND_URL puts its own
    Message-ID on the wire (2026-09-11: the owner's reply named an id nothing here had minted), so the id we
    minted never comes back and the box cannot choose the one that does. `reply_to` is the carrier that
    survives: the cold path passes `<channel>+<tag>@<domain>` (tagged), the client answers to it, and the tag
    comes back in the envelope recipient, which nothing between here and the door rewrites."""
    m = email.message.EmailMessage()
    m["From"] = from_a
    m["To"] = ", ".join(to)
    if cc:
        m["Cc"] = ", ".join(cc)
    if reply_to:
        m["Reply-To"] = reply_to
    # `subject` is the cold path's, given whole. A mail that answers nothing is not "Re: " anything, and
    # subject_of() would put the prefix on it; every other caller passes None and gets subject_of() as before.
    m["Subject"] = subject_of(rec) if subject is None else subject
    m["Date"] = email.utils.formatdate(now if now is not None else time.time(), localtime=False)
    mid = mid or email.utils.make_msgid(domain=from_a.split("@")[-1])
    m["Message-ID"] = mid
    last = ([x for x in (rec.get("message_ids") or []) if x] or [""])[-1]
    if last:
        m["In-Reply-To"] = last
        chain = [x for x in (rec.get("references") or []) if x and x != last] + [last]
        m["References"] = " ".join(chain)
    m.set_content(text or "")
    # `attach` is one (path, bytes) pair — the reply path's — or a list of them, the cold path's.
    for path, data in ([attach] if isinstance(attach, tuple) else attach or []):
        ctype, _ = mimetypes.guess_type(path)
        maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
        m.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream",
                         filename=os.path.basename(path))
    return m.as_bytes(), mid


def call_worker(cfg, from_a, rcpts, raw):
    """One POST to the worker, one attempt. Returns (ok, failures, error). `failures` is Cloudflare's own —
    an address it will not deliver to, a limit it has hit — and is a refusal to show, never a drop to swallow.

    THE USER-AGENT IS NOT DECORATION. Cloudflare's edge refuses urllib's default `Python-urllib/<version>` on a
    workers.dev hostname with its own 403 and error code 1010 — a page, not the worker's JSON, and the worker
    is never invoked. Every mail out of this box died there until this header was set, and the log line said
    "the worker answered", which it had not. So: a name of our own, and a 403 whose body is not the worker's
    JSON now says where it really came from."""
    body = json.dumps({"from": from_a, "to": rcpts, "raw": base64.b64encode(raw).decode()}).encode()
    req = urllib.request.Request(
        (cfg.get("MAIL_SEND_URL") or "").strip(), data=body, method="POST",
        headers={"Authorization": "Bearer " + (cfg.get("MAIL_SEND_SECRET") or "").strip(),
                 "Content-Type": "application/json",
                 "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=SEND_TIMEOUT) as r:
            answer = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = (json.loads(e.read().decode("utf-8", "replace")) or {}).get("error") or ""
        except Exception:
            pass
        if not detail:
            return False, [], ("something in front of the worker answered HTTP %s — its body is not the "
                               "worker's JSON, so the worker was never reached" % e.code)
        return False, [], "the worker answered HTTP %s: %s" % (e.code, detail)
    except Exception as e:
        return False, [], "the worker could not be reached (%s)" % e.__class__.__name__
    if not isinstance(answer, dict):
        return False, [], "the worker answered something that is not its JSON"
    failed = [f for f in (answer.get("failed") or []) if isinstance(f, dict)]
    if not answer.get("ok"):
        return False, failed, str(answer.get("error") or "the worker refused the call")
    return True, failed, ""


# ---------------------------------------------------------------- the tap

def by_mail(rec, chat, ts):
    """Did the message at (chat, ts) arrive by mail? True for the mirror line of any mail on this conversation:
    a root (the first mail's line, or the line a move re-posted) and every later mail's line under it, which
    take_mail writes to `mirrors` as it posts them. False for everything else — a person's Slack message in the
    thread, and no message at all (`ts` empty). A record written before `mirrors` existed still answers for its
    root, so a conversation from before this rule can still be answered by mail.

    A MAIL THE BOX STARTED FROM SOMEBODY'S THREAD (`--thread`, send_to) is the one conversation whose root is
    NOT a mail's line: the root is the person's own message, the one the session was asked in — the daemon
    marks that root `theirs` — and the box's `email to …` line sits under it as the record's `line`. Answering
    that line mails the people it went to; answering the root — the owner's Slack message — stays in Slack, as
    every answer to a Slack message does. The mark is on the root and not on the record because a move drops
    that root and re-posts a mail's line as the new one, which mails as any moved root does. A started record
    written before either field has the line as its root and counts as before."""
    ts = str(ts or "").strip()
    if not ts:
        return False
    line = rec.get("line") or {}
    if line.get("chat") == chat and str(line.get("ts")) == ts:
        return True
    for r in rec.get("roots") or []:
        if r.get("chat") == chat and str(r.get("ts")) == ts:
            return not r.get("theirs")  # the thread the mail was started from is the person's, not a mail's line
    return any(m.get("chat") == chat and str(m.get("ts")) == ts for m in (rec.get("mirrors") or []))


def send(cfg, chat, thread, text="", path="", now=None, ts=""):
    """ONE POST IN A MIRROR THREAD, MAILED WHEN IT ANSWERS A MAIL. Returns "" when there is nothing to say in
    Slack, or the one line the caller posts in that thread saying the mail did not go and why.

    `chat`/`thread` are the only way in: the addresses come off the conversation those two name on disk, so
    there is no argument here a caller could point at somebody else. Everything that is not a `to` root of a
    known conversation returns "" and does nothing, which is every ordinary post on the box.

    `ts` is the message the post answers. It decides the medium and nothing else: a post answering a message
    that came by mail (by_mail) goes out; one answering a Slack message, or answering nothing, stays in Slack
    and this returns "" without a word — nothing was promised, so the thread says nothing."""
    if not thread or not chat:
        return ""
    R = _router()
    rec = R.conv_by_root(chat, thread)
    if not rec:
        return ""
    if not any(r.get("chat") == chat and r.get("ts") == thread and r.get("role") == "to"
               for r in (rec.get("roots") or [])):
        return ""                       # a channel that was only copied on the mail does not speak for the box
    # "a post answering a Slack-origin message stays in Slack; one answering a mail-origin message goes out as
    # mail as today; a post that answers nothing in a mail thread stays in Slack" (owner, 2026-09-10)
    if not by_mail(rec, chat, ts):
        return ""
    if not configured(cfg):
        log_once("sending is off (MAIL_SEND_URL or MAIL_SEND_SECRET unset) — %s stayed in Slack" % rec.get("id"))
        return ""                       # nothing was promised, so the thread says nothing
    domain = cfg.get("MAIL_DOMAIN") or ""
    from_a = from_addr(rec, domain)
    to, cc = recipients(rec, domain)
    if not from_a or not to + cc:
        log("%s: not sent — %s" % (rec.get("id"), "no address of ours to send from" if not from_a
                                   else "nobody left to send to"))
        return ""                       # neither is a session's doing and neither is news in the thread

    body = plain(text)
    attach, note = None, ""
    if path:
        cap = cfg_int(cfg, "MAIL_OUT_MAX_ATTACH_BYTES", MAX_ATTACH)
        data, why = attach_bytes(path, rec, cfg, cap)
        if not why:
            attach = (path, data)
        else:
            # "a file either arrives as a file, or the caller and the thread are told it did not" (the brief,
            # 2026-09-11): a file that will not travel is one line in the thread, always. With a URL
            # (MAIL_OUT_LINKS) the mail still goes and carries the link instead; without one NOTHING goes — a
            # mail whose only news is that a file was left out is not an answer, and the session that posted
            # it is better told where to put the file and asked to post it again.
            note = not_attached(path, rec, cfg, why, cap)
            if not link_for(path, cfg):
                log("%s: not sent — %s: %s" % (rec.get("id"), clip(os.path.basename(path)), why))
                return note + ". Nothing was mailed; post it again once it is."
            body = (body + "\n\n" + link_line(path, cfg, why)).strip()
            note += " — it went as a link, not a file"
            log("%s: %s %s — sent as a link line, not a file" % (rec.get("id"), clip(os.path.basename(path)), why))
    if not body and not attach:
        return ""

    rcpts = to + cc
    why = caps(cfg, "%s/%s" % (chat, thread), rcpts, now=now)
    if why:
        log("%s: not sent — %s" % (rec.get("id"), why))
        return "📪 not mailed to the sender: %s. The reply is here." % why
    raw, mid = build(rec, from_a, to, cc, body, attach=attach, now=now)
    ok, failed, err = call_worker(cfg, from_a, rcpts, raw)
    if not ok:
        log("%s: not sent — %s" % (rec.get("id"), err))
        return "📪 not mailed to the sender: %s. The reply is here." % err
    # THE ID GOES IN THE CONVERSATION, and only after the mail is away: an id nothing was ever sent with would
    # thread a stranger's reply onto this conversation. save_conv re-reads and re-writes both indexes under its
    # own lock, so the record is loaded again here rather than reusing the one above.
    fresh = R.load_conv(rec["id"]) or rec
    if mid not in (fresh.setdefault("message_ids", [])):
        fresh["message_ids"].append(mid)
    R.save_conv(fresh)
    log("%s: sent from=%s to=%s%s%s" % (rec.get("id"), from_a, ",".join(to),
                                        " cc=" + ",".join(cc) if cc else "",
                                        " attach=" + os.path.basename(path) if attach else ""))
    if failed:
        one = failed[0]
        log("%s: Cloudflare refused %s — %s" % (rec.get("id"), clip(one.get("to")), clip(one.get("error"))))
        return "📪 Cloudflare would not deliver to %s: %s%s" % (
            clip(one.get("to")), clip(one.get("error")),
            " (and %d other%s)" % (len(failed) - 1, "" if len(failed) == 2 else "s") if len(failed) > 1 else "")
    return note                         # "" when everything went as posted; the link-not-file line when not


# ---------------------------------------------------------------- the mail the box starts

COLD_KEY = "cold"       # every cold mail shares one per-hour bucket: see send_to()


def send_to(cfg, to, subject, text, attachments=None, now=None, channel="", mirror=None, thread=None, workspace=""):
    """A MAIL WITH NO MAIL BEHIND IT — the box writing to somebody first. Returns (sent?, one line).

    `channel` is the sending session's own channel, or "" — session_channel() read off where the process
    runs, and the caller passes nothing it typed. It decides the From alone (cold_from): <channel>@ for a
    session that has one, so the answer lands in that channel's mirror thread; home@ (or MAIL_SEND_FROM) for
    one that does not. The verified list, the caps and the reply path do not see it.

    `thread` is the Slack thread the mail is STARTED FROM — (chat, thread ts), as cc-mail read it off the
    ask's `thread` — or None. It changes nothing about the From: a session with no channel of its own still
    sends home@ (owner, 2026-09-10). What it changes is where the answer lands: the mail is keyed (a tag on
    its Reply-To) and mirrored exactly as a channel's mail is, and the mirror puts the `email to …` line IN
    that thread and makes the thread's root the record's, so the person's answer is routed under the message
    they asked in (owner, 2026-09-11: his answer to a mail the planning seat sent from his thread opened a new
    one — "he expected it where it was asked"). The router finds the record by the tag before it reads the
    address, so `home+<tag>@` reaches it as `<channel>+<tag>@` does.

    `workspace` is the member handle a mail is sent FOR, or "" for the box's own — the daemon's member verb
    `send` passes the socket's handle and nothing off the ask. It narrows where a file may be attached from to
    that workspace's own trees (in_workspace: `<root>/<handle>` and its Slack files dir), exactly as a reply in
    a member's mirror thread is narrowed; the From is `channel`'s to decide, as above.

    `mirror` is the caller's one chance to give the mail a thread. It is called ONCE, after the mail is away
    and only for a keyed mail — a session with a channel, or a `thread` — with what a mirror needs —
    {"channel", "from", "to", "subject", "message_id", "tag", "attachments", "thread"}, the last {"chat", "ts"}
    or None — and whatever line it answers is appended to the line returned here. cc-mail hands it to the
    daemon's `mailed` verb, which posts one line in that channel (or under that thread) and writes the
    conversation record (see the docstring's last paragraph); the daemon itself never calls this and passes
    none.

    A FILE EITHER GOES AS A FILE OR NOTHING GOES. `attachments` is the list of paths the caller named, each
    read through attach_bytes() under a reply's rules — a regular file inside MAIL_OUT_ROOTS, under
    MAIL_OUT_MAX_ATTACH_BYTES — but one that fails them is not swapped for a link line here: the send is
    refused with the file's name and the reason, before any POST. The reply path downgrades because a Slack
    thread has nowhere to put a refusal; this call has a caller reading its one line, so the line says what
    did not happen and the caller decides (copy the file under a root, or send without it).

    THE LINE IS THE WHOLE ANSWER, either way. This is called from a terminal and its caller prints what it
    says, so every outcome here — off, refused, capped, sent, or delivered to some and not others — is one
    sentence a person can act on, and every one of them is in ~/.cc/mail/out.log as well. There is one attempt
    and no retry, the same as `send()` above.

    WHAT IS DIFFERENT FROM A REPLY, and it is only the first three lines: a reply's addresses come off a
    conversation on disk and cannot be argued with, and this one is HANDED an address. So the address is
    checked against verified() before anything leaves — the list is the owner's, not this call's — and the From
    is the box's own (cold_from(), off the session's channel), never one the caller chose.

    WHAT IS THE SAME: the worker, the secret, both caps and the log. The per-hour cap is charged against one
    key for the whole box rather than per thread, because there is no thread to spread a runaway over: a
    session in a loop calling this is one bucket of six an hour, and the per-recipient day cap is shared with
    the reply path so a person cannot be mailed thirty times by one path and thirty by the other.

    NOTHING IS THREADED HERE, and the conversation is the mirror's to write. There is no mail to be
    In-Reply-To, and an id recorded against no conversation would thread a stranger's answer onto somebody
    else's — so this function writes none. A session WITH a channel gets one through `mirror`: the line it
    posts in that channel is the root, and the record beside it carries the people it went to and the TAG the
    mail asks to be answered at — `Reply-To: <channel>+<tag>@<domain>` — so the person's answer is routed under
    that line instead of opening a new thread (owner, 2026-09-10: his reply to a channel's own mail arrived as
    a new root; 2026-09-11: it still did, because the relay rewrites the Message-ID we mint, so the id in the
    record is never the one a reply names — see build()). A session with no channel gets the same through
    `thread`. An answer to a mail from a channel-less session that named no thread (home@) still arrives at
    the door as a new mail and is routed like one."""
    rcpts, allowed = [], verified(cfg)
    for piece in (to if isinstance(to, (list, tuple)) else re.split(r"[,\s]+", str(to or ""))):
        a = _norm(piece)
        if a and a not in rcpts:
            rcpts.append(a)
    subject, body = str(subject or "").strip() or "(no subject)", plain(text)

    def refuse(line):
        log("%s: not sent — %s" % (COLD_KEY, line))
        return False, line

    if not rcpts:
        return refuse("no recipient")
    if not configured(cfg):
        return refuse("sending is off — MAIL_SEND_URL or MAIL_SEND_SECRET is unset")
    from_a = cold_from(cfg, channel)
    if not from_a:
        return refuse("no address of ours to send from — set MAIL_DOMAIN, or MAIL_SEND_FROM on that domain")
    unknown = [a for a in rcpts if a not in allowed]
    if unknown:
        return refuse("%s is not one of the box's verified destinations (MAIL_SEND_ALLOW, or MAIL_ALLOW when "
                      "it is unset)" % clip(unknown[0]))
    paths = [str(p).strip() for p in (attachments or []) if str(p or "").strip()]
    if not body and not paths:
        return refuse("nothing to send: the mail has no text and no file")
    # "making the attachment actually attach or saying plainly that it did not" (owner, 2026-09-09): a file
    # that will not travel is named on the refusal line and nothing is posted — never a link line here.
    cap = cfg_int(cfg, "MAIL_OUT_MAX_ATTACH_BYTES", MAX_ATTACH)
    rec = {"workspace": (workspace or "").strip()}   # a member's files come only from their own trees (bases)
    attach = []
    for path in paths:
        data, why = attach_bytes(os.path.expanduser(path), rec, cfg, cap)
        if why == TOO_BIG:
            return refuse("%s is over the %s attachment cap (MAIL_OUT_MAX_ATTACH_BYTES) — nothing sent"
                          % (clip(os.path.basename(path)),
                             "%d MiB" % (cap // (1024 * 1024)) if cap >= 1024 * 1024 else "%d-byte" % cap))
        if why:
            return refuse("%s cannot be attached — not a readable regular file under %s — nothing sent"
                          % (clip(os.path.basename(path)), trees(rec, cfg)))
        attach.append((path, data))

    why = caps(cfg, COLD_KEY, rcpts, now=now)
    if why:
        return refuse(why)
    # THE TAG IS THE THREAD'S KEY, minted here because it has to be on the wire before the daemon writes the
    # record (`mirror` runs after the send). A session with a channel gets one, and so does a mail started from
    # a thread — "the sender's answer lands in that thread" needs the record the tag keys; home@ with neither
    # has no thread to key. It identifies, it does not hide: a tag only ever reaches a conversation in the
    # sender's own workspace (router.conv_for_reply), so eight hex digits are plenty and leave room for the
    # channel's name (tagged).
    keyed = bool(channel or thread)
    tag = os.urandom(4).hex() if keyed else ""
    reply_to = tagged(from_a, tag)
    tag = tag if reply_to else ""          # a tag the mail does not carry is not one the record may index
    raw, mid = build({}, from_a, rcpts, [], body, attach=attach, now=now, subject=subject, reply_to=reply_to)
    ok, failed, err = call_worker(cfg, from_a, rcpts, raw)
    if not ok:
        return refuse(err)

    refused = {_norm(f.get("to")) for f in failed}
    sent = [a for a in rcpts if a not in refused]
    names = [os.path.basename(p) for p, _ in attach]
    log("%s: sent from=%s to=%s subject=%s%s" % (COLD_KEY, from_a, ",".join(sent) or "(none)", clip(subject),
                                                 " attach=" + ",".join(names) if names else ""))
    with_files = (", with %s attached" % ", ".join(names)) if names else ""
    # THE MIRROR, once the mail is away and only when somebody was reached: a thread for a mail nobody got
    # would wait for an answer that cannot come. Neither a channel nor a thread is the home@ case and keeps
    # today's behaviour: no line, and the answer arrives as a new mail.
    tail = ""
    if sent and keyed and mirror is not None:
        tail = str(mirror({"channel": (channel or "").strip().lstrip("#").lower(), "from": from_a, "to": sent,
                           "subject": subject, "message_id": mid, "tag": tag, "attachments": names,
                           "thread": {"chat": str(thread[0]), "ts": str(thread[1])} if thread else None}) or "")
    if failed:
        one = failed[0]
        line = "Cloudflare would not deliver to %s: %s" % (clip(one.get("to")), clip(one.get("error")))
        log("%s: %s" % (COLD_KEY, line))
        # A verified address of ours that Cloudflare still refuses is the owner's runbook to fix, not a bug
        # here, so it is named rather than counted — and the people it DID reach are named beside it.
        return bool(sent), ("mailed %s%s. %s%s" % (", ".join(sent), with_files, line, tail)) if sent else line
    return True, "mailed %s from %s%s%s" % (", ".join(sent), from_a, with_files, tail)
