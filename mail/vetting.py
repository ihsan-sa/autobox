#!/usr/bin/env python3
"""The vetting step — one read of every mail before anything acts on it. Milestone 3 of the mail door.

WHERE IT SITS. receiver.py stored the mail (M1) and router.py said which channels it belongs in (M2). This
file goes between that decision and the delivery: one read, one verdict, and cc-slack's take_mail delivers only
on `clean`. Nothing here posts, delivers or starts anything, and nothing here opens an attachment's bytes.

THREE ANSWERS AND NOTHING ELSE.
  clean       delivered as before, with the verdict in the mirror thread so a person can see why it went through.
  suspicious  nothing delivered, started or run. The mirror carries the note and an @-mention of the owner, and
              the mail waits in that thread for `deliver it` or `drop it` from a person who may say it.
  refused     one line in the log, one line for the sender in the mirror thread, nothing delivered.

THE MODEL PICKS A REASON, NOT AN OUTCOME. Its whole vocabulary is the keys of REASONS below, fixed in the
schema and checked against the table again here; the verdict and the sentence a person reads are OURS, looked
up from that key. So the read cannot invent a word, and no text a sender wrote ever reaches the mirror note or
the log through this file — the mail's own subject and preview are already in the mirror line above it. The
mail is quoted to the model as data, inside tags, with no tools and no session: it is weighed, never obeyed.

A SENDER THE BOX ALREADY KNOWS IS NOT READ AS A STRANGER. Every mail that reaches this file came from an
address the mail provider authenticated AND that is on the box's own list — the receiver drops the rest — and
the read still spent itself on whether that sender could be trusted, which is what held nearly every mail the
owner sent his own box (owner, 2026-09-10, the fourth time:
"if it comes from an approved email thats already a good sign. and then you need to see if it makes sense
that its going to a specific channel"). So trusted() answers that first question once, box-wide, off ONE list:
MAIL_ALLOW (LESSONS_EMAILS when it is unset), the same key the receiver reads, in the daemon's cfg. There is
no per-channel trust: an address on the list is known everywhere. A known sender gets ONE read, on the cheap
model, whose vocabulary is KNOWN_REASONS and whose whole question is the second one — does THIS mail fit THE
CHANNEL it is going to — plus the one thing trust does not buy: a mail that asks the box to act against its
own rules is held whoever sent it (`against-rules`). No history is quoted, because "is this like them" is the
first question again; no separate security read runs, because "does this link fit the sender's world" is too.
The sandbox still inspects every attachment, and its report goes to that one read as a line per file — a file
it could not inspect is a fact in the report, not a hold, since a known sender's spreadsheet is exactly what
`unreadable` kept holding. Nothing is opened, fetched or run here for a known sender any more than for a
stranger. The verdict says both halves, so neither answers the other: "the sender is on the box's list, and
the mail fits where it is going" / "…, but it does not fit the channel it is going to". A sender NOT on that
list — none reach this file today, since the receiver's list is the same one — takes the path below.

WHAT A STRANGER IS WEIGHED AGAINST. What this sender has asked for before (the subjects of their earlier mail to THIS
workspace that was delivered, out of ~/.cc/mail/conv) and what the workspace it is going to is for (the
target's goals, board and journal, under ~/.cc/state and ~/.cc/boards). A mail from a stranger to a workspace
it has nothing to do with is the shape this catches. A sender with NO history here is not that shape and is not
held for it — see asked() — because a first mail is ordinary and every sender has one.

NEITHER OF THOSE IS THE BOX'S OWN WORD, and the prompt says so. A subject is what a sender typed, a goals file
and a board row are writable inside the member's own workspace, and an attachment's name is chosen by whoever
sent it. Every one of them is flattened to one line, capped, and handed to the read inside data tags — the same
fence the mail's own body goes in — so a newline in one cannot forge a line of the report it sits in and
nothing quoted there arrives in the prompt's own voice.

TWO READS FOR A STRANGER, AND THE SECOND ONE ONLY WHEN THERE IS SOMETHING TO READ. Plain text is a cheap model
(MAIL_VET_MODEL, default `haiku`), and a known sender's one read is on it too. A stranger's mail carrying links
or attachments gets a second, security read on a stronger one (MAIL_VET_SECURITY_MODEL, default `sonnet`) which
sees the links as text and the sandbox's report on the attachments. LINKS ARE NEVER FETCHED — a link is judged
from its domain and the ask around it, and
fetching one is the target session's business, inside its own sandbox, after delivery. The worse of the two
answers wins.

AN ATTACHMENT'S BYTES ARE READ INSIDE A SANDBOX OR NOT AT ALL. inspect() hands the file's descriptor to a
command inside `cc-sandbox` — the member profile for a member workspace, the worker profile for a track that
has a worktree, the one MAIL_VET_SANDBOX names when the box has said which, and otherwise `cc-sandbox vet`, the
boundary the box provides for exactly this and has nothing of the box in — and reads back a type and, for text,
its first characters. There is no host path: a sandbox that will not start, one that fails, a budget that runs
out and a type nothing in there can name are all `unreadable`, which is suspicious. This process never decodes
an archive, renders a document or runs anything of the sender's.

A MAIL WHOSE BODY CAME AS HTML IS STILL READ. A client that sends no text/plain part leaves message.json's
`text` empty and its body in `html`, and a mail nothing has read is one nobody can judge. The body handed to
both reads is router.body_text() — the tags stripped out and the characters kept — and the links are the ones
written in that text plus the href of every link in the source. The HTML is never rendered, opened or fetched.

THE BUDGET IS PER MAIL AND PER SENDER PER DAY. Each read carries --max-budget-usd (MAIL_VET_COST, default
0.05) and each sender gets MAIL_VET_DAY_MAX reads a UTC day (default 20), counted in
~/.cc/state/mail/vet.json. A sender over it is held for a person, never dropped quietly.

FAIL CLOSED, AND SAY WHY. A model that is not installed, times out, errs or answers with a word off the table
gives `unread` — suspicious — because a mail nothing has read is exactly the one a person should see. A read
that FAILED rather than answered leaves one line in the log and carries its cause into the note the mirror
thread shows, since "nobody has read this" on its own told nobody that cc-slackd's unit had no PATH to
`claude` (2026-09-09). CC_MAIL_VET_FAKE
is the tests' door: `<text read>|<security read>`, each an entry of REASONS, and an empty one is a model that is
not there.
"""
import json
import os
import re
import subprocess
import sys
import time

H = os.path.expanduser("~")
MAILDIR = os.environ.get("CC_MAIL_DIR") or os.path.join(H, ".cc", "mail")
CONVDIR = os.path.join(MAILDIR, "conv")
STATE = os.environ.get("CC_MAIL_STATE") or os.path.join(H, ".cc", "state", "mail")
CCSTATE = os.environ.get("CC_STATE_DIR") or os.path.join(H, ".cc", "state")
BOARDS = os.environ.get("CC_BOARD_DIR") or os.path.join(H, ".cc", "boards")
WORKTREES = os.path.join(H, ".cc", "worktrees")
DEV = os.path.join(H, "dev")
MEMBER_MARKER = ".cc/member-workspace"      # at ~/dev/<handle>, the same file cc-slack's workspace_of reads

BIN = os.path.dirname(os.path.dirname(os.path.realpath(__file__))) + "/bin"
SANDBOX = os.environ.get("CC_SANDBOX") or os.path.join(BIN, "cc-sandbox")
VET_PROFILE = "vet"     # cc-sandbox's own boundary, and the one no workspace has to exist for — see boundary()
CLAUDE = os.environ.get("CC_CLAUDE") or "claude"
CONFIG = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "config")

VET_MAX = 6000          # of the body handed to a read. A mail that needs more than a screen to place is suspicious anyway
ASKS = 8                # earlier subjects from this sender, newest first
ASK_MAX = 200           # of one of them, on one line
NAME_MAX = 120          # of an attachment's name or its declared type, on one line
CONV_SCAN = 200         # conversation files looked at to find them — newest first, and the id sorts by time
GOALS_MAX = 1200        # of each of the three box-side files (goals, board, journal)
LINKS = 20              # links quoted to the security read
TIMEOUT = 60            # seconds for one read. A read that does not answer is `unread`, which is already safe
INSPECT_BYTES = 262144  # of an attachment fed to the sandbox
INSPECT_TEXT = 2000     # of it quoted back, once it turns out to be text
INSPECT_SECS = 20       # the sandbox's own wall clock, inside `timeout`
INSPECT_WAIT = 90       # ours around it, for a boundary that never starts
CAUSE_MAX = 120         # of the one line saying why a read did not answer; it goes in the mirror note too


def _router():
    """core/mail/router.py, its sibling, imported on use — outbound.py's shape and for its reason: importing this
    file must cost nothing on a box where the mail door was never installed. It is the ONE place that says what a
    mail's body is, whichever part carried it, so both reads below see the same body the mirror line shows."""
    d = os.path.dirname(os.path.realpath(__file__))
    if d not in sys.path:
        sys.path.insert(0, d)
    import router
    return router


# THE WHOLE VOCABULARY: the model may answer with one of these keys and nothing else, and the verdict and the
# sentence a person reads come from here rather than from the read. The keys under `model` are what each read
# is allowed to pick; the rest are ours to conclude.
REASONS = {
    "fits":        ("clean", "it reads as ordinary mail from this sender, and fits what this workspace is for"),
    "off-goals":   ("suspicious", "it asks for something outside what this workspace is for"),
    "misplaced":   ("suspicious", "a mail like this does not fit the channel it is going to"),
    "against-rules": ("suspicious", "it asks the box to act against its own rules"),
    "instruction": ("suspicious", "it reads as an instruction to the box rather than a message to a person"),
    "unlike":      ("suspicious", "it is not the kind of thing this sender has asked for before"),
    "link":        ("suspicious", "a link in it does not fit this sender's world"),
    "attachment":  ("suspicious", "an attachment in it does not fit this sender's world"),
    "unreadable":  ("suspicious", "an attachment could not be inspected inside the sandbox"),
    "budget":      ("suspicious", "this sender is over the day's vetting budget"),
    "unread":      ("suspicious", "the vetting read did not run, so nobody has read this yet"),
    "scam":        ("refused", "it asks for money, credentials or access"),
    "phish":       ("refused", "it is dressed up as somebody else's mail"),
    "junk":        ("refused", "it is bulk mail, not a message to this box"),
}
TEXT_REASONS = ["fits", "off-goals", "instruction", "unlike", "scam", "phish", "junk"]
SEC_REASONS = ["fits", "link", "attachment", "scam", "phish"]
# The known sender's whole vocabulary: the destination question, and the one hold trust does not lift. Not
# `unlike`, `phish` or `junk` — each is "can this sender be trusted", which the list already answered — and not
# `instruction`, because a known sender telling the box to do something is the ordinary case, not a hold.
KNOWN_REASONS = ["fits", "misplaced", "against-rules"]
KNOWN = "the sender is on the box's list"      # the first half of every known sender's verdict, said in words
RANK = {"clean": 0, "suspicious": 1, "refused": 2}

# Types the sandbox can say something useful about. Everything else — an archive, an office document (which is
# an archive), anything it could only call `data` — is `unreadable`: not opened here, not opened there, held for
# a person. `text/*` is the only family whose content is quoted to the security read.
INSPECTABLE = ("text/", "image/", "application/pdf", "application/json", "application/xml", "message/rfc822")

# A reply in a mail's mirror thread that finishes a held mail, and the only two forms there are. Anchored both
# ends for MOVE's reason: a sentence that mentions delivering is not a decision.
DECIDE = re.compile(r"^\s*(?P<word>deliver|drop)(?:\s+it)?\s*[.!]?\s*$", re.I)

URL = re.compile(r"\b(?:https?://|www\.)[^\s<>()\[\]{}\"']+", re.I)


class Verdict:
    """One mail's answer. `reason` is a key of REASONS, `verdict` and `why` come from it, and neither carries a
    word the sender wrote — the line a person reads is built from those in cc-slack's mail_note.

    `cause` is the one exception to that and is ours, not anyone's text: why a read did not answer, kept only
    on `unread`, where "nobody has read this" is the whole of what a person is told otherwise.

    `known` is a sender on the box's list, and the sentence then says BOTH answers — that the sender is known,
    and what was decided about the mail and its channel — so a person reading the thread sees which question
    held it, and a hold on the destination is never mistaken for doubt about the sender."""

    def __init__(self, reason, cost=0, cause="", known=False):
        self.reason = reason if reason in REASONS else "unread"
        self.verdict, self.why = REASONS[self.reason]
        self.cause = _one(cause, CAUSE_MAX) if self.reason == "unread" else ""
        if self.cause:
            self.why = "%s (%s)" % (self.why, self.cause)
        self.known = bool(known)
        if self.known:
            self.why = KNOWN + (", and the mail fits where it is going" if self.clean else ", but " + self.why)
        self.cost = cost

    @property
    def clean(self):
        return self.verdict == "clean"

    def __repr__(self):
        return "Verdict(%s/%s)" % (self.verdict, self.reason)


def worse(a, b):
    return a if RANK[a.verdict] >= RANK[b.verdict] else b


def _one(s, n):
    """One line of at most n characters — what every piece of text somebody else wrote is reduced to before it
    is quoted to a read. The sandbox's own output is already stripped this way (see INSPECT); this is the same
    thing for the names, subjects and board rows that never went through it. Whitespace of any kind collapses to
    a single space, so a newline cannot start a line of ours."""
    return " ".join((s or "").split())[:n]


# ---------------------------------------------------------------- the one list of senders the box knows

def allow_list(cfg):
    """The addresses the box takes mail from, lowercased, out of the daemon's cfg: MAIL_ALLOW, and LESSONS_EMAILS
    when that is unset. receiver.allow_list()'s rule on the same key, read here from the cfg the daemon hands
    in rather than from the receiver's own startup copy, so the two doors read one setting."""
    raw = (cfg or {}).get("MAIL_ALLOW") or (cfg or {}).get("LESSONS_EMAILS") or ""
    return {a.strip().lower() for a in re.split(r"[,\s]+", raw) if a.strip()}


def trusted(sender, cfg):
    """Whether this sender is one the box already knows — BOX-WIDE, off the one list, with no channel in the
    question (owner, 2026-09-10: "this should be done on the box wide vetting level imo not on the channel
    level"). `sender` is message.json's `from`, which the receiver's identity() authenticated, and never the
    envelope. No list, or a cfg without one, trusts nobody: the stranger path is the safe default. router.py
    may read this if it ever needs the answer; it is the one place the answer is given."""
    return bool((sender or "").strip()) and (sender or "").strip().lower() in allow_list(cfg)


# ---------------------------------------------------------------- the day's budget

def _day():
    return time.strftime("%Y-%m-%d", time.gmtime())


def spent(sender):
    """How many reads this sender has had today. The file is one day's counts and is replaced when the day
    turns, so it does not grow and yesterday is not evidence about today."""
    try:
        with open(os.path.join(STATE, "vet.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(d, dict) or d.get("day") != _day():
        return 0
    return int((d.get("senders") or {}).get((sender or "").lower()) or 0)


def charge(sender):
    """One more read against this sender's day. Read-modify-write on a file only the daemon writes, so no lock:
    a lost count costs a read, not a boundary."""
    path = os.path.join(STATE, "vet.json")
    try:
        with open(path) as f:
            d = json.load(f)
        if not isinstance(d, dict) or d.get("day") != _day():
            raise ValueError
    except (OSError, ValueError):
        d = {"day": _day(), "senders": {}}
    d.setdefault("senders", {})
    key = (sender or "").lower()
    d["senders"][key] = int(d["senders"].get(key) or 0) + 1
    try:
        os.makedirs(STATE, exist_ok=True)
        tmp = path + ".%d.tmp" % os.getpid()
        with open(tmp, "w") as f:
            json.dump(d, f, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass


# ---------------------------------------------------------------- what the mail is weighed against

def past_asks(sender, ws, n=ASKS):
    """The subjects this sender has already sent THIS workspace AND HAD DELIVERED, newest first. A
    conversation's file name is its first mail's id, which begins with a UTC stamp, so the directory sorts by
    time and the newest are read first. Only this workspace's records are opened, for the reason save_conv keys
    them that way.

    A MAIL NOBODY LET THROUGH IS NOT HISTORY. What is read here is the conversation's `asks`, which cc-slack's
    take_mail writes on the clean path and nowhere else — not for a held mail, not for a refused one, and not
    for one a person released out of a hold. Otherwise the first mail of a pair does the work: held, delivered
    nowhere, and still quoted to the read that weighs the second as something this sender asks for."""
    out = []
    try:
        names = sorted((f for f in os.listdir(CONVDIR) if f.endswith(".json") and f != "index.json"),
                       reverse=True)
    except OSError:
        return out
    for name in names[:CONV_SCAN]:
        try:
            with open(os.path.join(CONVDIR, name)) as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get("workspace") != ws:
            continue
        if (rec.get("from") or "").lower() != (sender or "").lower():
            continue
        for s in reversed(rec.get("asks") or []):    # newest last as take_mail appends them
            out.append(s or "(no subject)")
            if len(out) >= n:
                return out
    return out


def asked(subjects):
    """That list, as the read sees it: at most ASKS of them, one line each, cut to ASK_MAX, and fenced by the
    prompt in <asks> tags as text the SENDER wrote. A subject is whatever they typed, so a newline in one used
    to become another line of a list the prompt presents as this box's record of them — a forged ask, and an
    instruction under it.

    AN EMPTY HISTORY IS NOT EVIDENCE, and it has to say so in words: the first live run held a perfectly
    ordinary mail as `unlike` because the sender had no earlier conversation in that workspace and the prompt's
    tie-break turned the empty list into a reason. Every sender's first mail would have been held, and the
    senders that reach the receiver are authenticated before any of this. What to DO about an empty list is the
    prompt's own line, outside the tags — it is our instruction, not the sender's evidence."""
    if not subjects:
        return "Nothing: this is the first mail this sender has sent this workspace."
    return "\n".join("- %s" % (_one(s, ASK_MAX) or "(no subject)") for s in subjects[:ASKS])


def _head(path, n=GOALS_MAX):
    try:
        with open(path) as f:
            return f.read(n)
    except OSError:
        return ""


def goals(target):
    """What the workspace this mail is going to is for, in the workspace's own writing: the repo's goals, the
    rows on its board, and the head of this track's journal. Missing files are normal — a channel with none of
    the three is judged on the rest.

    IT IS NOT THE BOX'S WORD AND THE PROMPT DOES NOT PRESENT IT AS ONE. A member writes inside their own
    workspace, so goals.md, a board row and a journal line are all reachable by somebody who is not the owner,
    and an instruction planted in one would otherwise reach the read in the prompt's own voice. Each piece is
    capped, each board row is flattened to one line, and the prompt fences the whole block in <workspace> tags
    as text the workspace wrote."""
    repo, _, track = (target or "").partition("/")
    if not repo:
        return ""
    bits = []
    g = _head(os.path.join(CCSTATE, repo, "goals.md"))
    if g:
        bits.append("Goals of %s:\n%s" % (repo, g))
    try:
        with open(os.path.join(BOARDS, "%s.json" % repo)) as f:
            rows = json.load(f)
        rows = rows.get("rows") if isinstance(rows, dict) else rows
        titles = [_one(str((r or {}).get("title") or (r or {}).get("name") or ""), ASK_MAX)
                  for r in (rows or []) if isinstance(r, dict)]
        if any(titles):
            bits.append("On its board: %s" % "; ".join(t for t in titles if t)[:GOALS_MAX])
    except (OSError, ValueError, AttributeError):
        pass
    if track:
        j = _head(os.path.join(CCSTATE, repo, track, "progress.md"))
        if j:
            bits.append("The journal of %s:\n%s" % (target, j))
    return "\n\n".join(bits)


def links(msg):
    """Every link the mail carries, once each, in the order it wrote them: the ones written out in its body \u2014
    whichever part carried that body, so an HTML-only mail's too \u2014 followed by the href behind every `<a>` in the
    HTML source, which a stripped body loses.

    `click here` IS THE WHOLE REASON FOR THE SECOND HALF. Strip the tags and that link is gone from the text
    while the ask around it stays, so the security read would weigh an invitation with nothing to weigh it
    against. THE HREFS ARE READ OUT OF THE CHARACTERS AND NEVER FOLLOWED \u2014 nothing in this door fetches a link,
    renders the HTML or opens anything it names."""
    r = _router()
    out = []
    for u in URL.findall(r.body_text(msg)) + r.html_links(msg.get("html")):
        u = u.rstrip(".,;:)\u2019'\"")
        if u and u not in out:
            out.append(u)
    return out[:LINKS]


# ---------------------------------------------------------------- the sandbox an attachment is opened in

def boundary(ws, target, cfg):
    """The argv that runs a command INSIDE a sandbox — the workspace's own where it has one, and the box's own
    where it does not. Never the host.

    A member workspace has one always (`cc-sandbox member`, which is bwrap whatever the environment says). A
    track with a worktree has the worker profile, which is opt-in, so CC_WORKER_SANDBOX=1 is set by the caller
    below and never inherited. A workspace with neither — the owner's own DM, a channel that is not a track —
    borrows one: the track MAIL_VET_SANDBOX names when the box has said which, and otherwise `cc-sandbox vet`,
    THE BOUNDARY THE BOX PROVIDES FOR ITSELF. That last one is the answer to a fresh install and to a borrowed
    worktree that has been removed: with no key set the key's absence used to mean no boundary, so every mail
    with an attachment — which, before a text/html alternative stopped counting as one, was every mail from
    Gmail — was held as `unreadable` (2026-09-09). It needs no repo, no worktree and no configuration, and
    nothing of this box is inside it.

    Still no host path: this answers argv that goes through cc-sandbox or nothing at all, and a boundary that
    will not start is a read that did not happen — `unreadable`, which is suspicious."""
    if ws and os.path.isfile(os.path.join(DEV, ws, MEMBER_MARKER)):
        return [SANDBOX, "member", ws, "--"]
    for spec in ((target or ""), (cfg.get("MAIL_VET_SANDBOX") or "").strip()):
        repo, _, track = spec.partition("/")
        if repo and track and os.path.isdir(os.path.join(WORKTREES, repo, track)):
            return [SANDBOX, repo, track, "--"]
    return [SANDBOX, VET_PROFILE, "--"]


# `head -c` is the size budget and `timeout` the time one; the type comes off the bytes rather than the name the
# sender chose, and the text is stripped to printable ASCII so what comes back cannot carry control characters
# into a prompt. Nothing is decoded, unpacked or run: `file` reads magic bytes and stops.
INSPECT = ("f=$(mktemp) || exit 3; trap 'rm -f \"$f\"' EXIT; head -c %d > \"$f\" || exit 3; "
           "file -b --mime-type \"$f\" || exit 3; head -c %d \"$f\" | tr -c '\\11\\12\\40-\\176' '.'")


def inspect(att, base, argv):
    """One attachment, read inside the boundary. Gives back (type, text) — the type off its own bytes, and its
    first characters when it turned out to be text — or (None, "") when the boundary did not answer at all. A
    type outside INSPECTABLE comes back as the type it is, unopened; inspected() is what says that counts as
    `unreadable`, and the known sender's report says what the file is instead.

    THE BYTES NEVER ENTER THIS PROCESS. The file is opened for the descriptor alone and that descriptor is the
    child's stdin, so the kernel moves the bytes from the file into the sandbox and nothing here reads one. The
    path is checked against the mail's own directory first, because it came out of a file a sender wrote."""
    if not argv:
        return None, ""
    src = os.path.realpath(os.path.join(base, att.get("path") or ""))
    if not src.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(src):
        return None, ""
    fd = None
    try:
        fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
        r = subprocess.run(list(argv) + ["timeout", str(INSPECT_SECS), "sh", "-c",
                                         INSPECT % (INSPECT_BYTES, INSPECT_TEXT)],
                           stdin=fd, capture_output=True, text=True, timeout=INSPECT_WAIT, cwd=H,
                           env=dict(os.environ, CC_WORKER_SANDBOX="1"))
    except Exception:
        return None, ""
    finally:
        if fd is not None:
            os.close(fd)
    if r.returncode != 0:
        return None, ""
    out = (r.stdout or "").split("\n", 1)
    kind = _one(out[0].lower(), NAME_MAX)
    if not kind:
        return None, ""
    return kind, (out[1] if len(out) > 1 and kind.startswith("text/") else "")[:INSPECT_TEXT]


def inspected(msg, argv):
    """Every attachment through the boundary, as (report, unreadable). The report is what the read sees;
    `unreadable` is true as soon as one attachment could not be inspected or is of a kind the sandbox does not
    open, and for a stranger that alone holds the mail — a type the sandbox cannot name is suspicious, not
    clean. For a known sender it is a line in the report and the read weighs it (see vet()).

    THE NAME AND THE DECLARED TYPE ARE THE SENDER'S, and the report reads as the sandbox's own words, so both
    are flattened to one line first. get_filename() decodes RFC2047, which means a filename can arrive carrying
    newlines: unflattened, one attachment wrote as many lines of this report as it liked — a second file that
    was never there, and under it a sentence telling the read what the only correct answer is. The prompt fences
    the block as data as well, and one attachment is still one line."""
    base = os.path.join(MAILDIR, "inbox", msg.get("id") or "")
    rows, bad = [], False
    for a in msg.get("attachments") or []:
        name = _one(a.get("name"), NAME_MAX) or "?"
        declared = _one(a.get("type"), NAME_MAX) or "?"
        kind, text = inspect(a, base, argv)
        if kind is None:
            bad = True
            rows.append("- %s (declared %s, %s bytes): the sandbox could not inspect it"
                        % (name, declared, a.get("size") or 0))
            continue
        if not kind.startswith(INSPECTABLE):
            bad = True
            rows.append("- %s (declared %s, really %s, %s bytes): a kind the sandbox does not open"
                        % (name, declared, kind, a.get("size") or 0))
            continue
        rows.append("- %s (declared %s, really %s, %s bytes)%s"
                    % (name, declared, kind, a.get("size") or 0,
                       ("\n  its first characters: " + " ".join(text.split())) if text else ""))
    return "\n".join(rows), bad


# ---------------------------------------------------------------- the read

def _data(v):
    """Text that goes inside a fence, unable to close it. Every field a prompt is filled with is somebody
    else's writing or quotes it — the body, a subject, a name, a board row — and the fences are literal tags,
    so a `</mail>` or `</files>` typed into any of them would end the data block and put what follows in the
    prompt's own voice. Every `<` that could start a tag becomes a single angle quotation mark; the text still
    reads, and no tag can form."""
    return re.sub(r"<(?=/?[A-Za-z])", "\u2039", v or "")


def _prompt(name, fields):
    with open(os.path.realpath(os.path.join(CONFIG, name))) as f:
        text = f.read()
    for k, v in fields.items():
        text = text.replace("@%s@" % k, _data(v) or "(none)")
    return text


def _log(line):
    """One line about this file's own workings, on stderr — the journal for the daemon, the captured log for
    the selfcheck. receiver.py's shape, so one mail reads as one story."""
    try:
        sys.stderr.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                      " ".join(str(line).split())))
        sys.stderr.flush()
    except Exception:
        pass


def _cause(e, rc=None):
    """Why a read did not answer, in one short line: the exception's class and the least of it that names the
    cause. Never str() of a TimeoutExpired, which carries the whole argv — the schema, the model, the prompt's
    own size — and never anything a sender wrote. The return code comes along when the process did run."""
    if isinstance(e, subprocess.TimeoutExpired):
        detail = "no answer in %ss" % TIMEOUT
    elif isinstance(e, OSError) and e.filename:
        detail = str(e.filename)
    else:
        detail = str(e)
    return _one("%s: %s%s" % (type(e).__name__, detail, "" if rc is None else " (rc=%s)" % rc), CAUSE_MAX)


def _ask(prompt, allowed, model, cost, fake):
    """(one answer off `allowed`, why not). Anything that is not an answer off `allowed` — a model that is not
    installed, a timeout, an error, a word off the list — comes back None, which the caller reads as `unread`;
    `why` is one short line whenever the read FAILED rather than answered, and it rides into the mirror note so
    a held mail says what went wrong instead of only that nobody read it."""
    if fake is not None:
        got = fake.strip().lower()
        return (got, "") if got in allowed else (None, "")
    schema = json.dumps({"type": "object", "required": ["reason"], "additionalProperties": False,
                         "properties": {"reason": {"type": "string", "enum": list(allowed)}}})
    rc = None
    try:
        r = subprocess.run([CLAUDE, "-p", "--model", model, "--tools", "", "--strict-mcp-config",
                            "--setting-sources", "", "--disable-slash-commands", "--max-turns", "3",
                            "--no-session-persistence", "--output-format", "json", "--json-schema", schema,
                            "--max-budget-usd", str(cost)],
                           input=prompt, capture_output=True, text=True, timeout=TIMEOUT, cwd=H,
                           env=dict(os.environ, CC_ROLE="worker", MAX_THINKING_TOKENS="0"))
        rc = r.returncode
        got = (json.loads(r.stdout).get("structured_output") or {}).get("reason")
    except Exception as e:
        why = _cause(e, rc)
        _log("mail vet: the read did not answer: %s" % why)
        return None, why
    got = (got or "").strip().lower()
    if got in allowed:
        return got, ""
    # The schema pins the enum, so a word off it is the read malfunctioning, not the model being unsure. The
    # word itself is never quoted: it is model output, and no text from a read reaches the mirror note.
    _log("mail vet: the read answered off the list (rc=%s)" % rc)
    return None, "the read answered off the list"


def _fakes():
    """CC_MAIL_VET_FAKE as (text read, security read). Unset is a real model; set is the tests' answer, and an
    empty half is a model that is not there."""
    fake = os.environ.get("CC_MAIL_VET_FAKE")
    if fake is None:
        return None, None
    a, _, b = fake.partition("|")
    return a, b


def vet(msg, dec, cfg=None):
    """ONE MAIL, ONE VERDICT. `dec` is router.route()'s Decision — its workspace and its first To channel are
    what the mail is weighed against — and `cfg` is the daemon's configuration.

    The order is the cost. The day's budget is checked before any model runs. A KNOWN SENDER — trusted(), off the
    box's one list — then gets one read and no other: the destination question, with the mail's links and the
    sandbox's report on its files in front of it, and `fits` unless the mail does not belong in that channel or
    asks the box to break its rules. A stranger gets the cheap read next; the security read only happens when
    there is a link or an attachment to read, and not even then if the sandbox already said an attachment
    cannot be inspected, because that answer is already "a person decides"."""
    cfg = cfg or {}
    sender = (msg.get("from") or "").lower()
    ws = dec.workspace or ""
    known = trusted(sender, cfg)
    if spent(sender) >= max(1, int(cfg.get("MAIL_VET_DAY_MAX") or 20)):
        return Verdict("budget", known=known)
    cost = cfg.get("MAIL_VET_COST") or "0.05"
    ftext, fsec = _fakes()
    charge(sender)

    target = (dec.to or dec.cc or [None])[0]
    body = _router().body_text(msg)[:VET_MAX]   # `text`, or an HTML-only mail's body with its tags stripped
    urls, atts = links(msg), msg.get("attachments") or []
    if known:
        # THE BRIEF'S OWN LINE: "an approved sender is a good sign, not a blank cheque — a mail that asks the box
        # to act against its own rules is still held whoever sent it, and nothing here weakens the rule that a
        # link is never fetched and an attachment is only ever read inside a sandbox". So the boundary still
        # inspects, the read still sees the links as text, and `against-rules` is on the list; what is gone is
        # the second read and the hold on a file the sandbox could not open, both of which asked about the
        # sender. `known` on the Verdict is what makes the note say both halves.
        report = inspected(msg, boundary(ws, target.target if target else "", cfg))[0] if atts else ""
        # WHO is the sender's own standing, not the Decision's workspace. An `unmapped` mail (router.UNMAPPED)
        # carries workspace="owner" because it is in the owner's session for HIM to place — the sender is an
        # address on the list that no workspace claims, and a read told "the box's owner" would wave through
        # as fitting his channel whatever a stranger to every workspace wrote (review of #433, 2026-09-11).
        if dec.rule == _router().UNMAPPED:
            who = ("an address on the box's list that no workspace claims — the mail is in the owner's own "
                   "channel so that he can place it, which is where every such mail goes")
        else:
            who = "the box's owner" if ws == "owner" else "a member of this box"
        got, why = _ask(_prompt("mail-vet-known-prompt.md",
                                {"SENDER": sender, "WHO": who,
                                 "WORKSPACE": ws, "TARGET": "#" + target.name if target else "(nowhere)",
                                 "GOALS": goals(target.target if target else ""),
                                 "LINKS": "\n".join("- %s" % u for u in urls), "ATTACHMENTS": report,
                                 "SUBJECT": msg.get("subject") or "(no subject)", "BODY": body}),
                        KNOWN_REASONS, cfg.get("MAIL_VET_MODEL") or "haiku", cost, ftext)
        return Verdict(got, cause=why, known=True)

    got, why = _ask(_prompt("mail-vet-prompt.md",
                            {"WORKSPACE": ws, "TARGET": "#" + target.name if target else "(nowhere)",
                             "GOALS": goals(target.target if target else ""),
                             "ASKS": asked(past_asks(sender, ws)),
                             "SENDER": sender, "SUBJECT": msg.get("subject") or "(no subject)", "BODY": body}),
                    TEXT_REASONS, cfg.get("MAIL_VET_MODEL") or "haiku", cost, ftext)
    v = Verdict(got, cause=why)

    if not urls and not atts:
        return v
    report, bad = inspected(msg, boundary(ws, target.target if target else "", cfg)) if atts else ("", False)
    if bad:
        return worse(v, Verdict("unreadable"))
    got, why = _ask(_prompt("mail-vet-security-prompt.md",
                            {"SENDER": sender, "WORKSPACE": ws,
                             "TARGET": "#" + target.name if target else "(nowhere)",
                             "LINKS": "\n".join("- %s" % u for u in urls),
                             "ATTACHMENTS": report,
                             "SUBJECT": msg.get("subject") or "(no subject)", "BODY": body}),
                    SEC_REASONS, cfg.get("MAIL_VET_SECURITY_MODEL") or "sonnet", cost, fsec)
    return worse(v, Verdict(got, cause=why))


# ---------------------------------------------------------------- the reply that finishes a held mail

def decided(text):
    """`deliver it` or `drop it` — "deliver", "drop" or None. The one grammar a held mail's thread answers;
    everything else said in there is an ordinary message and is left alone."""
    m = DECIDE.match((text or "").strip())
    return m.group("word").lower() if m else None
