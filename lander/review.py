"""The lander's review read: one tool-less read per change digest, the delta read after a handback, and the records.

    lander record <repo> <pr> LAND|HANDBACK --by <who> [--head <sha>] [--findings TEXT|-]
                                     write a read a seat made as the PR's marker comment (from the perms seat, a
                                     LAND also goes in perms' ledger: "a security path"); refused if --head moved,
                                     if it is looser than a HANDBACK already standing (old words map as below), or
                                     if the head, the base or the change digest cannot be worked out right now (a
                                     marker with an empty change= matches no reader, so nothing is posted)
    lander will-review <repo> <pr>   exit 0 when the lander would buy a read for this PR at its head, else 1
    lander perms-read <repo> <pr>    perms only: start its security read of the PR's head in a session of its own, so
                                     a hand-off of the perms window does not end it ("perms' own reads", below)
    lander perms-read <repo> <pr> --since <old head>
                                     the same read of only the change since `old`, a head perms' ledger LANDs that
                                     still carries (land_heads), when the head merges clean onto main: delta_text()
    lander perms-hold <repo> <pr>    perms only: hold the PR's merge at its head until perms' read of it says LAND
    lander perms-reads <repo> [<pr>] perms' read files, running and done, newest first
    lander perms-adopt <repo> <pr>   perms only: put its finished LAND read in its ledger, only when that read is of
                                     the PR's live head and change. A ledger LAND (here or by record) re-queues the
                                     PR's job that host_hold ended at that head (requeue_held)

ONE READ PER CHANGE DIGEST. The digest is digest_of(): change_digest() of `git diff base...head` as plain_diff()
makes it (blind to the checkout's config and attributes, so binary means binary bytes), the hunk headers and `index`
lines dropped (a binary file's full blob ids kept) and the rest hashed, so a rebase that does not change the change
keeps its key. It is the one key: the lane names its job by it, and `record` and `will-review` by it too. A read
recorded at that digest (or the legacy one, keys()) — by this lander, by a seat through `record`, or by the old
lander — is reused, never bought again, by review() and delta_review() alike. The light lane (light.py) asks
land_recorded(): that recorded verdict when it is a LAND whose marker names the PR's head now, else None; it buys
nothing.

WHERE VERDICTS LIVE. On the PR, as marker comments. Today's shape is kept so every reader still parses it:

    <!-- cc-land-review v2 change=<digest> base=<12> head=<12> verdict=<V> by=<who> -->

The new lander writes V = LAND or HANDBACK. Markers the old lander wrote are IMPORTED: LAND stays LAND;
LAND-AFTER-FIX whose findings are all `[other]` lands (that was its rule too: the findings went to a follow-up
row); any other LAND-AFTER-FIX, and DO-NOT-LAND, is HANDBACK. Only comments the box's own GitHub login wrote count
(gh's viewerDidAuthor), as before: anyone can type a marker into a PR.

WHEN A READ IS BOUGHT (review(), delta_review()). PR comments gh cannot give -> INCOMPLETE, nothing read or landed:
a handback recorded there cannot be ruled out. A HANDBACK by perms' security reader (security_reader(): exactly
perms-security-read) stands, at any head, until a later LAND by that reader at its head or the PR's head now
(open_security()), or perms' ledger holds its LAND of the PR's head now, recorded at a later second than the
HANDBACK comment was posted (_security_open(); a time that does not parse clears nothing); while it stands the
verdict is that HANDBACK and no read is bought, because no read the lander buys is a security reader's. A recorded
verdict at the digest (or the legacy digest, which kept the hunk tail) is returned as it is: the newest, except
that a LAND at the PR's exact head is not replaced by a later HANDBACK the lander's own readers wrote (recorded(),
bought()), and a read that hands back while such a LAND was recorded returns that LAND. Otherwise a HANDBACK the
box last wrote at an earlier head (latest()) gets the delta read below, paid or not: a handback is never dropped
because the head moved. Otherwise, a change the plan did not make paid (job.plan.paid false: no paid-review path,
and some check runs on it, or it adds or changes no code nothing owns) needs no read: LAND with model "" and extra
read=none.
Otherwise the lander buys one:
  - the usage limit binds (`cc-limit status` exit 0) -> INCOMPLETE, no read counted, nothing posted; extra
    `until` (limit_until) says when to ask again, and the lane holds the job till then.
  - no count of reads stops one (owner, 10-16: the two-read cap turned a PR that still needed a read into a planning
    query and a stall). The PR's reads are summed in dollars (spent(): the family, repo + PR number, so a push or a
    reopen does not reset it), and the read that takes them past READ_CEILING_USD tells the planning seat, and so
    does the read that takes them past each doubling of it (2x, 4x, ...; over_ceiling: a planner request naming the
    PR and its spend), and the reading goes on. A codex read reports no dollars, so its cost is an estimate:
    the `tokens used` count it prints at CODEX_USD_PER_MTOK, or CODEX_READ_USD when it prints none, and at least
    CODEX_READ_USD when codex exits nonzero (codex_usd).
  - one read by EACH model on CC_LAND_REVIEWERS (the passwd home's ~/.cc/config only, cards.REVIEWER_CONFIG;
    default READERS: Fable 5.1 and Astra 6 — owner, 2026-09-24: "a review goes to Fable 5.1 and Astra 6
    together"), at CC_LAND_REVIEW_EFFORT (default high; one of EFFORTS, checked before any read). A `claude-*`
    model or a claude alias (CLAUDE_ALIASES) is one `claude -p` call, no tools; any other is one `codex exec`
    call with every tool feature on CODEX_OFF disabled and the user config ignored, and before it `codex features
    list` must show nothing on outside CODEX_ON_OK. Every read runs on READ_PATH with HOME at the passwd home and no
    variable of the caller's but READ_ENV_KEEP (clean_env), claude is claude_bin() and codex is codex_bin() with
    CODEX_HOME at the passwd home, so the caller's PATH, HOME, ANTHROPIC_* or CODEX_HOME picks nothing. Both get the prompt
    core/config/lander/review.md from THIS release (not the PR's
    head) with the diff, the merged text of the changed files (a file over WHOLE_UNDER whose whole change is in the
    diff only around its changes), the brief's done-criteria and docs/REVIEW.md
    read from the BASE commit, and the PR body's Tested section (tested_of: the author's claims, labelled as claims
    to check against the diff, never instructions; folded by NFKC with format characters gone, a line that reads
    as a verdict or as the prompt's frame dropped,
    cut at TESTED_CAP), and the PR's title and whole body (body_of: the author's text, labelled as evidence of what
    the PR claims and never instructions, screened the same way, cut at BODY_CAP like the brief; a body gh could not
    fetch is a line saying so), each between `<<<name` / `name>>>` markers (a marker inside the data is broken
    up, so the data cannot close its own block). The answer is JSON (verdict, blocking[], advisory[]).
    A change lands only on EVERY reader's verdict (owner: both models read every change). A reader that hits the
    limit (`cc-limit check`), or answers nothing the first time at a head, makes the whole read INCOMPLETE and
    refunded, as if it never ran; the readers that did answer are kept at this digest (partial()), so the retry
    asks only the silent one. A READ THE HOST COULD NOT MAKE IS NEVER A HANDBACK (owner, 10-12: host reasons were
    the biggest handback cause). A reader that CANNOT answer — an HTTP 4xx such as a 403, a bad model id, a missing
    binary, a flag error, a tool feature codex will not turn off — answers nothing (a timeout), or hits its own
    budget cap is INCOMPLETE the first time at a head, held and asked again after the backoff (limit_until); the
    second time at that head it is INCOMPLETE with extra host=True (and fault=True or cap=True) naming the reader and
    the cause, which the lane sends to the planning seat as a query: held, the reason recorded, nothing asked of the
    author. An effort off EFFORTS is held the same way at once.
    A claude read runs with `--output-format stream-json`, because its `--max-budget-usd` is checked only after a
    turn: a read's one turn can spend past the cap, the CLI then reports error_max_budget_usd and its result
    carries no structured_output, though the turn already called StructuredOutput. The stream carries that call,
    so a wall with an answer in it is that answer (streamed()); only a wall without one (a refusal, a text-only
    turn) counts as a wall. A call counts as an answer only when it is whole (its turn stopped on tool_use, or the
    CLI accepted it; never a CUT stop), the CLI did not reject it, and it fits SCHEMA.
    A claude read runs with DISABLE_PROMPT_CACHING=1: the read is one API call, and the CLI otherwise writes the
    whole prompt to a one-hour cache at twice the input price for a read nothing makes again (#960 at 3447d443,
    10-07: $3.02 of a $3.49 wall was that write).
    The verdict is HANDBACK when any reader's is; the findings are all readers', each row naming its reader; the
    marker lists every reader's own verdict. Together they count as ONE read against the cap.
    CC_LAND_REVIEW_MODEL, when set, is the only reader (the old single-read setting).
    A STAND-IN FOR A LIMITED READER (#1116 and #1128 held two hours on 10-17 while Astra sat at its ChatGPT usage
    limit). When a reader that is not claude's comes back with a usage or rate limit (why starting `limit`, as
    ask_codex() reports when codex_limit() says so: a nonzero exit and an ERROR: or stream error: line of codex's
    own naming a usage, rate or session limit or a 429 (its retries spent on Too Many Requests), every line the
    prompt also holds dropped first, so PR text or a diff saying "usage limit" never makes another fault a limit) and the plan names no security path (plan.extra["security"] empty; a plan of None counts
    as unknown and gets none), one more claude read, independent of the first (its own call, no context shared),
    stands in for it: CC_LAND_REVIEW_LIMIT_READER (the passwd home's config, like every CC_LAND_REVIEW key), default the first claude reader on readers() (a value that is not a claude model turns the stand-in off).
    Its Verdict carries extra stood_in_for (the limited reader) and stood_in_why (the limit text); the marker row
    says `<claude>`: VERDICT (stood in for `<reader>`, at its usage limit), its findings say "read by <claude> for
    <reader>", and the combined Verdict's extra stood_in lists each one, so the record shows the fallback. A stand-in that fails too is handled as that
    failure (_silent), and a limit on a security path, or any other failure (a fault, a timeout, a wall), is held as
    before: perms' read gates a security path.
The read runs with its cwd in `$TMPDIR/cc-land.run.<pid>.<rand>/cc-land.review.<repo>.<pr>.<rand>`: that name is
how cc-spend puts its cost on `<repo>/review`, and every read's cost is also added to the PR's spend file
(root/<repo>-<pr>.json, `review_usd`, `reads`) that the old lander kept.

A handback's re-read is delta_review(): the interdiff between the head the prior read saw and this head, the prior
blockers numbered; it answers resolved/unresolved/moot and new blockers on added lines only. It counts as a read.
A prior blocker the read lists as moot (the change makes it no longer apply, or it lies outside the diff and is
already true) holds nothing and counts as resolved; one it lists as both moot and unresolved stays unresolved, and an
unresolved one is a HANDBACK whatever the verdict word says. A prior [security] blocker is never moot (pinned()): it
stays unresolved, named or left out of every list, and the HANDBACK stands, until a read resolves it. "Already
true" needs evidence in the read's inputs, not the author's word (delta.md says so; no code can check it). Each
prior blocker left unresolved is carried into the verdict as a blocking row with the prior row's own text and its
kind tag in front, "[security] still open from the earlier read: …" (carried()), whatever the reader's verdict
word and whether or not it named new blockers, so pinned() finds the [security] row again in the round after, and
every round.

A SECURITY PATH needs perms' security read (perms, after #1265: a tunnel unit and the Cloudflare door merged with
no security read, and the read after found a HIGH). When the plan names a changed file on the base's
tests/LANDING-security.toml (plan.extra["security"]), review(), delta_review() and would_read() look for perms'
RECORD of it, never a PR comment (perms' HANDBACK at 2f9fde5e: a seat can post any marker with `gh pr comment`):
perms_recorded() reads <passwd home>/.cc/state/<repo>/perms/security-reads.json, the perms seat's own directory,
which cc-guard lets no other session write (the Cloudflare door trusts perms-allow.json beside it the same way). It
must be the box user's own plain 0600 file, reached through no symlink, holding a JSON list of entries like
  {"repo": "<repo>", "pr": 1270, "head": "<40-hex head sha>", "change": "<the change digest>"}
and one counts only when repo, pr and head are this job's exactly, change is one of keys() (never empty), and it
is the newest entry at that repo, PR and head (newest_reads: a FIX appended after a LAND takes it back). The lander only
reads that file. Perms writes it in one of two ways, each run only from the perms seat (perms_seat_caller()), and
each entry adds verdict LAND, read, model and at: `lander record <repo> <pr> LAND --by <who> --head <sha>` from the
perms seat posts the marker and appends the entry for the PR's live head and change (read "perms" when <who> is
perms or perms-*, else <who>), but only when <sha> is that live head in full 40-hex; without it the marker is
posted and the ledger is not written. A HANDBACK, LAND-AFTER-FIX or DO-NOT-LAND recorded the same way from the perms
seat appends an entry with that word as its verdict (no full --head needed: it only holds), so a LAND perms later
hands back at one head reads as handed back. `perms-adopt` does the same for a finished `perms-read` (read naming its
file). Both append under a flock on .security-reads.lock beside the file. No other caller writes it.
With no such record the answer is INCOMPLETE with extra host=True and security=True, which the lane sends to the planning seat as a query, and no read is bought, because none the lander
buys is perms'. Any LAND marker, the lander's own and one signed PERMS_SECURITY_READER included, does not merge it.
With the record, a verdict recorded at this digest stands as on any change (a HANDBACK there still hands it back);
with none recorded the record is the LAND (model PERMS_SECURITY_READER, extra read="perms"), and nothing is bought.
A record CARRIES to a new head (carried_from()): when this head has none, an entry for an earlier head of the same
PR counts if its `verdict` is LAND or absent and the author's delta from that head to this one (delta_files(), as
interdiff() compares them: after a rebase only the PR's own paths, so main's other files drop out, plus those of
them main changed between the two merge-bases) touches no path the base's security list matches (security_globs(),
plan.select's own list). A delta that touches one, an old head that is gone, a compare git cannot make, or a
manifest that will not load carries nothing. The LAND then names the old head in extra carried_from, so nobody takes it
for a fresh read. A LAND older than any non-LAND entry of the PR carries nothing, whatever head that entry names,
and a later LAND at that entry's head does not bring it back: here every entry counts, not only each head's newest.
Only review(), delta_review() and would_read() carry; perms_recorded() itself, and so
lane.landed_at() and release, still want the head exact. A record carries also when git's own merge of the old head onto this
head's merge-base gives this head's tree exactly and this head merges clean onto main (same_change(), remerges(),
merges_clean()), so a merge of main that moved only context keeps perms' read; this carry alone also lets a host check run (lane.Lane.host_unread) and
the merge go past perms_reading(). Each such carry is a `perms-carry` line in queue.log naming both heads.
`lander record ... --by perms` or `--by perms-*` is refused unless the calling Claude session works in the perms
seat (perms_seat_caller()). The marker itself is only a comment and clears nothing; the ledger entry the perms
seat's LAND appends is what clears the path.

A LAND with advisory findings files ONE follow-up row, review-followup-pr<N> (board.followup).

PAUSE. The lane asks cc-pause and cc-tier before it calls review() (U1 owns that hold, per the design); nothing
here runs for a paused project. recurring-defect-ok: pause-hold-missing — the lane (U1) holds a paused repo before any U3 call
"""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import hashlib
import sys
import json
import bisect
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import types
import unicodedata

from lander import cards as C
from lander import gh as GH
from lander import types as T

MARK = "cc-land-review"
READ_CEILING_USD = 15.0   # a PR's reads past this, and past each doubling of it, tell the planning seat; nothing stops
CODEX_USD_PER_MTOK = 5.0  # a codex read's estimated dollars per million tokens it says it used (CC_LAND_CODEX_USD_PER_MTOK)
CODEX_READ_USD = 1.0      # a codex read that ran but printed no token count is charged this
READERS = "claude-fable-5-1 gpt-6-astra"   # the default of CC_LAND_REVIEWERS
READ_TIMEOUT = 1200
PROMPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "config", "lander")
MARK_RE = re.compile(rf"\A\s*<!-- {re.escape(MARK)} v2 change=([0-9a-f]+)((?: [^>]*?)?) "
                     r"verdict=(LAND-AFTER-FIX|DO-NOT-LAND|HANDBACK|LAND)\b([^>]*)-->")
FINDING_ROW = re.compile(r"^\d+\. ")
OTHER_ROW = re.compile(r"^\d+\. \[other\] ")

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["verdict", "blocking", "advisory"],
    "properties": {
        "verdict": {"enum": ["LAND", "HANDBACK"]},
        "blocking": {"type": "array", "maxItems": 10, "items": {
            "type": "object", "required": ["kind", "where", "what", "input", "fix"],
            "properties": {"kind": {"enum": ["correctness", "security", "scope"]}, "where": {"type": "string"},
                           "what": {"type": "string"}, "input": {"type": "string"}, "fix": {"type": "string"}}}},
        "advisory": {"type": "array", "maxItems": 10, "items": {
            "type": "object", "required": ["where", "what"],
            "properties": {"where": {"type": "string"}, "what": {"type": "string"}}}},
        "resolved": {"type": "array", "items": {"type": "string"}},
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "moot": {"type": "array", "items": {"type": "string"}},
    },
}

HUNK = re.compile(r"^@@ -[0-9,]+ \+[0-9,]+ @@.*$")
HUNK_LEGACY = re.compile(r"^@@ -[0-9,]+ \+[0-9,]+ @@")


# --- keys ----------------------------------------------------------------------------------------------------------

def change_digest(diff, legacy=False):
    """A `git diff` text -> 40 hex naming the change, '' for no diff. The same algorithm as the old lander, so its
    recorded verdicts keep their keys: `index` lines and hunk headers (numbers and, unless legacy, the function tail)
    dropped, everything else hashed verbatim. One exception, in both modes: a binary file keeps its blob ids, because
    its hunk says only "Binary files … differ" (an old binary-only record so needs a new read, the safe failure)."""
    keep, index = [], ""
    for ln in (diff or "").splitlines():
        if ln.startswith("diff --git "):
            index = ""
        if ln.startswith("index "):
            index = ln.split()[1] if len(ln.split()) > 1 else ""
            continue
        if ln.startswith("Binary files ") and ln.endswith(" differ"):
            # a binary hunk is only this line, so the blob ids are the bytes: two heads adding the same path with
            # different contents must not share a key (diff_of asks --full-index, so an id is not a short prefix)
            keep.append(f"blob {index}")
        keep.append((HUNK_LEGACY if legacy else HUNK).sub("@@", ln) if ln.startswith("@@ ") else ln)
    body = "\n".join(keep).strip()
    return hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()[:40] if body else ""


def digest_of(root, base, head):
    """THE digest of a PR at `head`, the one the lane keys its job by and `record`/`will-review` key theirs by. The
    lane once used a patch-id hash of its own, so a LAND recorded at a head was never found at that head (#739)."""
    return change_digest(diff_of(root, base, head))


def keys(job, diff):
    """The digests a recorded verdict for this job may carry: its own, and the legacy one old markers used."""
    return {job.digest or change_digest(diff), change_digest(diff, legacy=True)} - {""}


# --- the markers ---------------------------------------------------------------------------------------------------

def marker(v: T.Verdict, base, head, by):
    """The comment body recording `v`: the marker line, then the findings as numbered rows."""
    rows = [f"{i}. {b}" for i, b in enumerate(v.blocking, 1)]
    rows += [f"{i}. [other] {a}" for i, a in enumerate(v.advisory, len(rows) + 1)]
    by = re.sub(r"[^A-Za-z0-9._@-]+", "-", by or "lander")
    head_ = f"<!-- {MARK} v2 change={v.digest} base={base[:12]} head={head[:12]} verdict={v.verdict} by={by} -->"
    said = [f"- `{r['model']}`: {r['verdict']}" + (f" (stood in for `{r['stood_in_for']}`, at its usage limit)"
                                                   if r.get("stood_in_for") else "")
            for r in (v.extra or {}).get("readers") or []]
    return "\n".join([head_, f"**lander review** — `{head[:12]}`, read by `{v.model or by}`", "",
                      f"**VERDICT: {v.verdict}**", ""] + (said + [""] if said else []) + (rows or ["No findings."]))


def imported(body):
    """A marker comment body -> Verdict, mapping the old vocabulary (see the module doc), or None."""
    m = MARK_RE.match(body or "")
    if not m:
        return None
    digest, old, tail = m.group(1), m.group(3), m.group(2) + m.group(4)
    rows = [ln.strip() for ln in body[m.end():].splitlines() if FINDING_ROW.match(ln.strip())]
    other = [r for r in rows if OTHER_ROW.match(r)]
    hard = [r for r in rows if not OTHER_ROW.match(r)]
    if old == "LAND-AFTER-FIX" and not hard and other:
        verdict = T.LAND
    elif old in ("LAND-AFTER-FIX", "DO-NOT-LAND"):
        verdict = T.HANDBACK_VERDICT
        if not hard:   # a prose-only stop: its text is the blocker
            hard = [body[m.end():].strip()[:2000] or f"{old} with no findings written"]
    else:
        verdict = old
    by = re.search(r"\bby=([A-Za-z0-9._@-]+)", tail)
    head = re.search(r"\bhead=([0-9a-f]+)", tail)
    strip = lambda rs: [re.sub(r"^\d+\. (\[other\] )?", "", r) for r in rs]  # noqa: E731
    return T.Verdict(verdict=verdict, digest=digest, blocking=strip(hard) if verdict != T.LAND else [],
                     advisory=strip(other), model=by.group(1) if by else "",
                     extra={"head": head.group(1) if head else "", "imported": old})


def bought(v):
    """True when `v` is a read the lander bought: every reader named on it is one of readers()."""
    return bool(v.model) and set(v.model.split("+")) <= set(readers())


def recorded(comments, digests, head=""):
    """The newest verdict among the PR's `comments` (gh's [{"body", "viewerDidAuthor"}]) at any of `digests`. Only
    comments this box's own GitHub login wrote count: anyone can type a marker into a PR. -> Verdict or None.
    Brief (#1113): "Honour a LAND that already sits at the PR's exact head and change key" — a HANDBACK the lander's
    own readers wrote after such a LAND does not replace it, so the read cap neither queries the planning seat nor
    asks a third read. A HANDBACK anyone else recorded (a seat, a security reader) still does."""
    found = None
    for c in comments:
        v = imported(c.get("body", "")) if c.get("viewerDidAuthor") else None
        if not v or v.digest not in digests:
            continue
        at = (found.extra.get("head") or "") if found else ""
        if head and len(at) >= 7 and head.startswith(at) and found.verdict == T.LAND and bought(v):
            continue
        found = v
    return found


def latest(comments):
    """The newest verdict the box wrote on this PR at any digest, or None (a handback's re-read starts from it)."""
    found = None
    for c in comments:
        v = imported(c.get("body", "")) if c.get("viewerDidAuthor") else None
        found = v or found
    return found


# The reader a security path's LAND is signed with (the verdict review() returns on perms' record). A PR marker of
# that name counts for nothing on its own (perms' HANDBACK at 2f9fde5e); only perms_recorded() clears the path.
PERMS_SECURITY_READER = "perms-security-read"


def security_reader(v):
    """True when the reader named on verdict `v` is exactly PERMS_SECURITY_READER, the name `lander record` writes
    only from the perms seat. Perms, 10-13: "Make it match the exact constant perms-security-read that lander record
    trusts" — a name that merely says `security` (x-security, perms-security-read-2) is anyone's to write."""
    return (v.model or "") == PERMS_SECURITY_READER
# The perms seat's state root, at the passwd home: never $HOME or $CC_STATE, which a caller sets (tests patch this).
PERMS_STATE = os.path.join(C.PASSWD_HOME, ".cc", "state")
CLAUDE_VERSIONS = os.path.join(C.PASSWD_HOME, ".local", "share", "claude", "versions")   # the claude binaries
# One more versions root, for a Claude installed elsewhere: read only from this root-owned file, never from cc-config
# or the environment, which a seat writes. The code never creates it; the owner does (tests patch this and ROOT_UID).
CLAUDE_VERSIONS_FILE = "/etc/cc/claude-versions"
ROOT_UID = 0
PERMS_READS = "security-reads.json"
PERMS_READS_LOCK = ".security-reads.lock"   # grant()'s flock, beside the ledger


def repo_name(repo):
    """'demo' for 'owner/demo' or 'demo': the folder a repo's state lives in."""
    return str(repo).rsplit("/", 1)[-1]


_BOX_OWNER = []


def box_owner():
    """The box's own GitHub owner, CC_GH_PERSONAL_OWNER, read once; "" when unset or unread."""
    if not _BOX_OWNER:
        from lander import members as MB
        _BOX_OWNER.append((MB.config_read("CC_GH_PERSONAL_OWNER") or "").lower())
    return _BOX_OWNER[0]


def repo_key(repo):
    """'owner/demo', how a ledger entry and a job are matched: either may name the repo with its owner or without
    (Opus read of #1268), and a bare name is the box's own owner's, so a 'demo' under another owner never stands for
    it (perms' read of #1691). With no owner read, a bare name matches only a bare name. None when `repo` is not a
    non-empty string, and None matches nothing."""
    if not isinstance(repo, str) or not repo:
        return None
    s, owner = repo.lower(), box_owner()
    return s if "/" in s or not owner else f"{owner}/{s}"


def perms_reads_path(repo):
    return os.path.join(PERMS_STATE, repo_name(repo), "perms", PERMS_READS)


def own_json(path):
    """-> (data, why): the JSON in `path`, or (None, the reason it does not count): absent, reached through a
    symlink, not the box user's own plain 0600 file, or not JSON."""
    if os.path.realpath(path) != os.path.abspath(path):
        return None, f"{path} resolves through a symlink"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        return None, f"{path} will not open: {e.strerror}"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600:
            return None, f"{path} is not this user's own plain mode-600 file"
        with os.fdopen(fd, encoding="utf-8") as f:
            fd = None
            return json.load(f), ""
    except (OSError, ValueError) as e:
        return None, f"{path} will not read: {e}"
    finally:
        if fd is not None:
            os.close(fd)


def perms_reads(repo):
    """-> (entries, why): perms' security-read records for `repo` (the module doc), or ([], the reason none count):
    as own_json() refuses it, or not a JSON list."""
    path = perms_reads_path(repo)
    data, why = own_json(path)
    if why:
        return [], why
    if not isinstance(data, list):
        return [], f"{path} is not a JSON list"
    return [e for e in data if isinstance(e, dict)], ""


def newest_reads(entries, repo, pr):
    """{head: the newest of `entries` for exactly this repo and PR at that head}, in the order those newest entries
    were appended. perms appends under a flock, so the last entry for a head is its newest verdict: a FIX perms
    records after its LAND at one head takes the LAND back (perms' follow-up to its LAND on #1564)."""
    out, key = {}, repo_key(repo)
    for e in entries:
        if key and repo_key(e.get("repo")) == key and e.get("pr") == pr and isinstance(e.get("head"), str):
            out.pop(e["head"], None)
            out[e["head"]] = e
    return out


def perms_recorded(repo, pr, head, digests):
    """perms' newest entry for exactly this repo, PR and head (newest_reads) when it is a LAND at one of `digests`,
    else None: what a security path merges on (_security_unread, lane.landed_at), a host check runs on
    (lane.Lane.host_unread) and is released on (release.remote_rules). An entry with no `verdict` is a LAND, as in
    carried_from; a FIX or DO-NOT-LAND is not one, and one recorded after a LAND at that head takes it back. An
    empty digest is no digest (Opus read of #1564: a job with no reviewer unit has digest "", which an entry with
    an empty change would match). A delta LAND (one with `since`) stands only while its `since` is still a LAND
    head (land_heads()): a FIX perms records later at that old head takes it back too (perms' read of #1859)."""
    digests = {d for d in digests or () if d}
    if not (head and digests):
        return None
    e = newest_reads(perms_reads(repo)[0], repo, pr).get(head)
    if e is None or e.get("change") not in digests or e.get("verdict", T.LAND) != T.LAND:
        return None
    since = e.get("since")
    return e if not since or since in land_heads(types.SimpleNamespace(repo=repo, pr=pr, head=head)) else None


def security_globs(root, base, repo):
    """The base's security paths (Policy.security_review, as plan.select reads them), or None when the base's
    manifest will not load: then nothing is carried."""
    from lander import manifest as M
    try:
        return list(M.load(root, base, fallback=M.host_fallback(str(repo).rsplit("/", 1)[-1])).policy.security_review)
    except Exception:   # noqa: BLE001 — any failure to read the list fails closed
        return None


def delta_files(root, base, old, new):
    """The paths the author changed between two heads, as interdiff() compares them (after a rebase only the paths
    either head's own change touches, so main's other files drop out), plus, after a rebase, those of these paths
    main changed between the two merge-bases: a head that puts one back as it was before main's fix agrees with the
    old head there, yet merging it reverts the fix. None when that will not run: the old head is gone after a
    force-push, any git error, or a name that is not UTF-8."""
    rc, full = git(root, "rev-parse", "--verify", "-q", f"{old}^{{commit}}")
    if rc:
        return None
    rc, out, _ = heads_diff(root, base, full.strip(), new, "--name-only", "--no-renames", "-z", mains=True)
    return None if rc or "\ufffd" in out else sorted({p for p in out.split("\0") if p})


def old_globs(root, base, old, repo):
    """The security list as the base `old` was built on had it (its merge-base with `base`, found in blind()), or
    None when that will not read. perms' read of `old` was judged by a list no newer than the base it read on, and
    this one is never newer than that, so a glob main added since counts as new here: it can cost a re-read, never
    carry one."""
    with blind(root, base, old) as (got, run):
        if run is None:
            return None
        rc, mb = run("merge-base", *got[1])
    return None if rc else security_globs(root, mb.strip(), repo)


def carried_from(job):
    """The earlier head of this PR whose perms LAND carries to job.head, or "". Owner brief: "carried forward to
    the new head, but only if the delta from the old head to the new head touches no security path", and "If the
    delta touches any such path, or the old entry is missing or wasn't a LAND, carry nothing over". An entry with
    no `verdict` is a LAND (perms records only reads it passes); one naming any other word is not. Newest first.
    A path of this change on the base's list now that the old head's own base did not list (old_globs()) was never
    read as one, so it carries nothing either (perms' read of #1384: a glob main adds after the read, on a path
    the PR left alone). Only each head's newest entry counts (newest_reads): an old head whose LAND perms later
    took back with a FIX carries nothing, and nothing carries to a head whose own newest entry is not a LAND.
    Nor does a LAND older than any non-LAND entry of this PR, at whatever head, even one a later LAND at that head
    took back: a HANDBACK recorded with no --head is written at the head the PR had then, which need not be the one
    perms read (perms' read of #1624: LAND at X, the branch moved to Y, a HANDBACK written at Y, and X's LAND still
    carried to a later head), and a fresh LAND of Y is a read of Y, not of X (Opus read of #1628: with only each
    head's newest entry read, a LAND recorded at Y over that DO-NOT-LAND brought X's LAND back). Whatever the delta
    touches, an old head whose own change is this head's (same_change: a merge of main moved only context) carries."""
    olds = land_heads(job)
    if not (olds and job.head):
        return ""
    root = root_of(job)
    globs = security_globs(root, job.base_sha, job.repo)
    if globs is None:
        return same_change(job, olds)
    from lander import manifest as M
    paths = list(job.plan.extra.get("security") or []) if job.plan else []
    for old in reversed(olds):
        files = delta_files(root, job.base_sha, old, job.head)
        if files is None or any(M.match(globs, f) for f in files):
            continue
        was = old_globs(root, job.base_sha, old, job.repo) if paths else []
        if was is not None and all(M.match(was, p) for p in paths):
            return old
    return same_change(job, olds)


def land_heads(job):
    """The earlier heads of this PR whose perms LAND may carry to job.head, oldest first, by carried_from()'s rules
    (its doc): each head's newest entry a LAND, none older than any non-LAND entry of the PR, and none when this
    head's own newest entry is not a LAND."""
    entries, key = perms_reads(job.repo)[0], repo_key(job.repo)
    newest = newest_reads(entries, job.repo, job.pr)
    if job.head in newest and newest[job.head].get("verdict", T.LAND) != T.LAND:
        return []
    olds = []
    for e in entries:   # every entry, in the order perms appended them, not only each head's newest
        h = e.get("head")
        if not key or repo_key(e.get("repo")) != key or e.get("pr") != job.pr or not isinstance(h, str):
            continue
        if e.get("verdict", T.LAND) != T.LAND:
            olds = []
        elif re.fullmatch(r"[0-9a-f]{40}", h) and h != job.head:
            olds = [o for o in olds if o != h] + [h]
    return olds


def remerges(root, base, old, new):
    """True when git's own merge of `old` onto `new`'s merge-base with `base` (`git merge-tree --write-tree`, in
    blind(), no hand edit) is clean and gives `new`'s tree exactly: then `new` is `old`'s change on a newer main and
    nothing else, wherever the context around it moved. A conflict, a hand edit or a line moved within a file
    gives another tree (planning's read of 10-22)."""
    with blind(root, base, old, new) as (got, run):
        if run is None:
            return False
        b, o, n = got[1]
        rc, mn = run("merge-base", b, n)
        rc, t = (rc, "") if rc else run("merge-tree", "--write-tree", mn.strip(), o)
        rc2, nt = run("rev-parse", n + "^{tree}")
        return rc == 0 == rc2 and bool(t.split()) and t.split()[0] == nt.strip()


def on_default(job):
    """True when the PR's base is the repo's default branch and job.base_sha is the tip a fresh fetch of it reads
    (tick.default_base). Perms' read of #1859: a LANDed PR retargeted onto a worker's branch remerged clean there,
    and the carry let that branch's unread file reach the host checks."""
    from lander import tick as K
    root = root_of(job)
    name, tip = K.default_base(root, GH.slug(root))
    return bool(name) and job.extra.get("base_ref") == name and job.base_sha == tip


def same_change(job, olds=None):
    """The earlier head (of land_heads(), or `olds`) that this head is only a clean remerge of (remerges()), or "".
    Dispatch's holds of 10-20..22: 8 of 39 were a merge of main that changed only context lines, which change_digest
    hashes. Only onto a head that merges clean onto the base (merges_clean, perms' answer of 10-22), and only onto
    the repo's default branch at its fetched tip (on_default); each carry is logged with both full heads."""
    olds = land_heads(job) if olds is None else olds
    if not (olds and job.head and on_default(job)):
        return ""
    root = root_of(job)
    for old in reversed(olds):
        if remerges(root, job.base_sha, old, job.head):
            if not merges_clean(root, job.base_sha, job.head):
                return ""
            C.log("perms-carry", job.repo, job.pr, read=old, head=job.head, why="clean-remerge")
            return old
    return ""


def _perms_land(job, digests=()):
    """The LAND perms' record stands for, on a plan with a security path whose record _security_unread found; None
    on any other plan. A record carried from an earlier head says so in extra carried_from, so nobody takes it for
    a fresh read of this one."""
    if not (job.plan and job.plan.extra.get("security")):
        return None
    extra = {"read": "perms"}
    if not perms_recorded(job.repo, job.pr, job.head, digests):
        was = carried_from(job)
        if was:
            extra["carried_from"] = was
    return T.Verdict(verdict=T.LAND, digest=job.digest, model=PERMS_SECURITY_READER, extra=extra)


def open_security(comments, head):
    """The newest HANDBACK a security reader wrote on this PR that no later security reader's LAND has cleared, at
    any digest, or None. "Only a later security-reader LAND should clear it" (perms, PR #1174): a LAND by any other
    reader, the lander's own included, leaves it standing. "Tie the clear to a LAND at the same or a later head than
    the HANDBACK" (Opus read of #1277): the LAND must name the HANDBACK's head or `head`, the PR's head now (no head
    is later than that one); a LAND at some other head, or naming none, leaves it standing. Heads compare at the
    12 characters a marker keeps."""
    now = (head or "")[:12]
    found = None
    for c in comments:
        v = imported(c.get("body", "")) if c.get("viewerDidAuthor") else None
        if not (v and security_reader(v)):
            continue
        if v.verdict == T.HANDBACK_VERDICT:
            found = v
            found.extra["at"] = c.get("createdAt") or ""
        elif v.verdict == T.LAND and found:
            at = v.extra.get("head", "")[:12]
            if at and at in (found.extra.get("head", "")[:12], now):
                found = None
    return found


# --- the prompt ----------------------------------------------------------------------------------------------------

def fence(name, text):
    """Break any `name>>>` / `<<<name` inside the data so it cannot close or open its block."""
    text = text or ""
    for tag in ("diff", "files", "brief", "rules", "prior", "interdiff", "tested", "body"):
        text = text.replace(f"{tag}>>>", f"{tag}> >>").replace(f"<<<{tag}", f"<< <{tag}")
    return text


def prompt(template, **data):
    """Fill `@KEY@` slots. Data slots are fenced; the short header slots (@PR@ @REPO@ @TITLE@) are single-line."""
    filled = {}
    for k, v in data.items():
        v = str(v)
        filled[k] = " ".join(v.split())[:200] if k in ("PR", "REPO", "TITLE") else fence(k.lower(), v)
    if not filled:
        return template
    # One pass over the template only: a slot word inside filled-in data (a diff that says @RULES@) stays as it is.
    slots = re.compile("@(" + "|".join(re.escape(k) for k in filled) + ")@")
    return slots.sub(lambda m: filled[m.group(1)], template)


def load_prompt(name):
    with open(os.path.join(PROMPTS, name)) as f:
        return f.read()


def parse(answer, digest, model="", tokens=0):
    """The model's answer -> Verdict. Anything that is not the schema's object is None (nothing read the diff), and so
    is a HANDBACK that names no blocker and leaves no prior one unresolved: it asks a fix nobody can make, and a
    re-queue at that head would meet it again (#919), so it is retried as a silent read. Its unresolved prior
    blockers become blocking rows only once _buy() has run carried() on it."""
    try:
        j = json.loads(answer)
    except (TypeError, ValueError):
        return None
    if isinstance(j, dict) and "structured_output" in j:   # claude -p --output-format json wraps it
        tokens = tokens or _tokens(j)
        j = j.get("structured_output")
    if not isinstance(j, dict) or j.get("verdict") not in ("LAND", "HANDBACK"):
        return None
    blocking = [_row(f, True) for f in (j.get("blocking") or [])][:10]
    advisory = [_row(f, False) for f in (j.get("advisory") or [])][:10]
    # a prior blocker the read marks moot, or outside the diff and already true, holds nothing; one it also calls
    # unresolved stays unresolved, so a contradictory answer keeps the stop
    unresolved = [str(x) for x in j.get("unresolved") or []]
    moot = [str(x) for x in j.get("moot") or [] if str(x) not in unresolved]
    verdict = j["verdict"]
    if verdict == T.HANDBACK_VERDICT and not blocking and not unresolved:
        return None
    if verdict == T.LAND and blocking:   # a blocker is a blocker whatever the verdict word says
        verdict = T.HANDBACK_VERDICT
    return T.Verdict(verdict=verdict, digest=digest, blocking=blocking, advisory=advisory, model=model,
                     tokens=int(tokens or 0), resolved=[str(x) for x in j.get("resolved") or []] + moot,
                     unresolved=unresolved, extra={"moot": moot} if moot else {})


def pinned(v, prior):
    """A delta read's Verdict, with every prior blocker it called moot that was a [security] finding put back as
    unresolved. The brief: "keep a security reader's HANDBACK standing until a security LAND" — so a read must
    resolve it; a reader's word that it no longer applies does not. `prior` is the prior verdict's blocking rows,
    numbered from 1 as the read saw them. One the read leaves out of every list is pinned too (Opus read of #1227:
    else a LAND passes it by)."""
    sec = {str(i) for i, b in enumerate(prior, 1) if "[security]" in b}
    moot = (v.extra or {}).get("moot") or []
    done = {row_number(r) for r in v.resolved if r not in moot}
    back = sorted(sec - done - {row_number(u) for u in v.unresolved}, key=int)
    if not back:
        return v
    if moot:
        v.extra["moot"] = [m for m in moot if row_number(m) not in back]
    v.resolved = [r for r in v.resolved if row_number(r) not in back]
    v.unresolved = v.unresolved + back
    v.verdict = T.HANDBACK_VERDICT   # carried() writes each one's row, its [security] tag in front
    return v


def row_number(name):
    """A prior row's number as a read names it ('2', '#2', 'blocker 2'), or None (Opus read of #1227: a bare match
    lost '#2' its [security] tag)."""
    m = re.search(r"\d+", str(name))
    return m.group(0) if m else None


STILL_OPEN = "still open from the earlier read: "
KIND_TAG = re.compile(r"\[(correctness|security|scope)\] ")


def carried(v, prior):
    """A read's unresolved prior blockers -> blocking rows of their own, first and whatever the verdict word: each is
    the prior row's text (`unresolved` names it by number) with its kind tag kept in front, so a [security] pin is
    still a [security] row in the round after, and the round after that. A HANDBACK with no new blocker carries them
    as a LAND does, and an earlier blocker the read says is still open makes the verdict HANDBACK. A name that is no
    prior row's number ('2', '#2', 'blocker 2': row_number()) is carried as the reader wrote it. `prior` is the
    prior verdict's blocking rows, as pinned() takes them. Running it twice on one verdict adds nothing."""
    rows = list(prior or [])
    out = []
    for x in v.unresolved:
        n = row_number(x)
        row = rows[int(n) - 1] if n and 1 <= int(n) <= len(rows) else x
        m = KIND_TAG.match(row)
        tag, row = (m.group(0), row[m.end():]) if m else ("", row)
        row = row[len(STILL_OPEN):] if row.startswith(STILL_OPEN) else row
        out.append(f"{tag}{STILL_OPEN}{row}")
    if out:
        v.verdict = T.HANDBACK_VERDICT
        v.blocking = out + [b for b in v.blocking if b not in out]   # no cap: a cut would drop a [security] pin
    return v


def _row(f, hard):
    if not isinstance(f, dict):
        return str(f)
    s = f"[{f.get('kind', 'other')}] " if hard else ""
    s += f"{f.get('where') or '(nowhere named)'} — {f.get('what') or ''}"
    if hard and f.get("input"):
        s += f" (input: {f['input']})"
    if hard and f.get("fix"):
        s += f" → {f['fix']}"
    return s


def _tokens(j):
    u = j.get("usage") or {}
    return sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                             "cache_creation_input_tokens"))


# --- the spend file and the cap ------------------------------------------------------------------------------------

def spend_path(repo, pr):
    return C.state("root", f"{repo}-{pr}.json")


def spent(repo, pr):
    """The PR's spend file (the old lander's root record): reviews, asked, review_usd, wall. Never reset by a push, a
    reopen, a merge or age, so the cap holds across all of them."""
    return C.read_json(spend_path(repo, pr), {}) or {}


def charge(repo, pr, **bump):
    """Add ints/floats, set anything else, drop a None. -> the record written."""
    j = spent(repo, pr)
    j.setdefault("first", C.now())
    j.update(repo=repo, pr=pr, at=C.now())
    for k, v in bump.items():
        if v is None:
            j.pop(k, None)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            j[k] = round((j.get(k) or 0) + v, 4)
        else:
            j[k] = v
    C.write_json(spend_path(repo, pr), j)
    return j


def reads_used(repo, pr):
    j = spent(repo, pr)
    return int(j.get("reviews") or 0)


def ceiling_step(usd):
    """-> the largest of 1, 2, 4, ... whose multiple of READ_CEILING_USD `usd` has reached; 0 below the ceiling."""
    step = 0
    while usd >= READ_CEILING_USD * (step * 2 or 1):
        step = step * 2 or 1
    return step


def over_ceiling(repo, pr):
    """Once the PR's reads have cost READ_CEILING_USD or more, tell the planning seat, and again each time they pass a
    doubling of it (the spend file's `ceiling_step`: the multiple last told; a record with only the older
    `ceiling_said` was told at 1x), and go on: an alert, never a stop. -> True when it told it now. A request
    cc-notify refused is asked again by the next read's charge."""
    j = spent(repo, pr)
    usd = float(j.get("review_usd") or 0)
    step = ceiling_step(usd)
    told = int(j.get("ceiling_step") or (1 if j.get("ceiling_said") else 0))
    if step <= told:
        return False
    past = "the" if step == 1 else f"{step}x the"
    rc, _ = C.sh([os.path.join(BIN, "cc-notify"), "--ask", "--id",
                  f"land:{repo}:{pr}:read-ceiling" + (f":x{step}" if step > 1 else ""), "-t",
                  f"{repo} landing", f"[{repo}] PR #{pr}: its review reads have cost ${usd:.2f}, past {past} "
                  f"${READ_CEILING_USD:g} ceiling. The reading goes on; look at why this PR keeps needing reads."],
                 timeout=60, **C.box_hand())
    if rc:
        return False
    charge(repo, pr, ceiling_said=C.now(), ceiling_step=str(step))   # a str: charge() sets it, never adds to it
    C.log("read-ceiling", repo, pr, usd=f"{usd:.2f}", step=step)
    return True


# --- the box around a read -----------------------------------------------------------------------------------------

LIMIT_SAID = re.compile(r"\b(session|usage|rate)[ _-]?limit", re.I)
# A limit codex itself reports: a line it starts with `ERROR:` or `stream error:` at its first column (after an optional
# [timestamp]). codex echoes the prompt, PR text and diff included, so a bare LIMIT_SAID over its output would let a
# diff that says "usage limit" turn any other codex failure into a limit and bring in a stand-in (perms' and an Opus
# read, 10-20). The first column alone keeps out a diff line (each starts with +, - or a space) but not the PR body,
# file and brief blocks, which put PR text at column 0, so codex_limit() also drops every output line the prompt holds.
# A 429 that outlasts codex's own retries ("ERROR: exceeded retry limit, last status: 429 Too Many Requests", #1461,
# #1456 and #1496 on 10-20) is the ChatGPT allowance spent too, so it is a limit, not a read that answered nothing.
CODEX_LIMIT_SAID = re.compile(r"^(?:\[[^\]\n]*\][ \t]*)?(?:ERROR|stream error):[^\n]*?"
                              r"(?:\b(?:session|usage|rate)[ _-]?limit|\bstatus:?[ \t]*429\b|\b429 Too Many Requests)",
                              re.I | re.M)
WALLS = ("error_max_budget_usd", "error_max_turns")
BIN = C.BIN
# The PATH every read runs on: root-owned directories only, never the caller's (security read of #847).
READ_PATH = "/usr/local/bin:/usr/bin:/bin"


# THE READ'S ENVIRONMENT IS BUILT, NOT FILTERED (#849 Opus read, #847 delta reads). Every other variable of the
# caller's could steer the reader: ANTHROPIC_BASE_URL points claude at a server that answers LAND, HTTPS_PROXY with
# NODE_EXTRA_CA_CERTS reads and rewrites the answer, NODE_OPTIONS runs code in claude's node, and a HOME of the
# caller's picks the ~/.claude a read loads. Only these names pass, HOME is the passwd home, and CC_CONFIG_DENY
# names the passwd home's config (expanduser would follow the caller's HOME).
READ_ENV_KEEP = C.ENV_KEEP


def clean_env():
    env = {k: v for k, v in os.environ.items() if k in READ_ENV_KEEP or k.startswith("LC_")}
    env["HOME"] = C.PASSWD_HOME
    env["CC_CONFIG_DENY"] = os.path.realpath(C.REVIEWER_CONFIG)
    env["PATH"] = READ_PATH   # the caller's PATH would pick the node a `#!/usr/bin/env node` codex runs on
    return env


def scratch(repo, pr):
    """The read's cwd. cc-spend puts a transcript whose cwd has a part `cc-land.<step>.<repo>.<pr>.<rand>` on
    `<repo>/<step>`; the run root above it (`cc-land.run.<pid>.<rand>`) is walked past. The repo tag has no dots."""
    top = os.path.realpath(os.path.expanduser(C.conf("CC_LAND_SCRATCH", "~/.cc/tmp")))
    os.makedirs(top, mode=0o700, exist_ok=True)
    run = tempfile.mkdtemp(prefix=f"cc-land.run.{os.getpid()}.", dir=top)
    tag = re.sub(r"[^A-Za-z0-9_-]+", "-", repo) or "repo"
    return run, tempfile.mkdtemp(prefix=f"cc-land.review.{tag}.{pr}.", dir=run)


def readers():
    """The models that read a change, first one first (see the module doc)."""
    one = C.conf("CC_LAND_REVIEW_MODEL", "").strip()
    return [one] if one else (C.conf("CC_LAND_REVIEWERS", READERS).split() or READERS.split())


def effort():
    return C.conf("CC_LAND_REVIEW_EFFORT", "high")


# The efforts both readers take: `claude --effort` says low..max, codex's model_reasoning_effort adds none and minimal.
# claude IGNORES a value outside its list and reads at its default (probed 2026-09-30), so a typo would pass unseen.
EFFORTS = ("low", "medium", "high", "xhigh", "max")

# An answer that says the read cannot run as asked, so waiting is unlikely to mend it: a 4xx other than 429 from either
# API (a model that does not exist or is not allowed, a bad parameter), a flag the CLI does not know.
FAULT_SAID = re.compile(r'"(?:api_error_status|status)"\s*:\s*4(?!29)\d\d|unrecognized_model|may not exist'
                        r'|is not supported when|Unknown feature flag|unexpected argument|unknown option', re.I)


def fault(rc, out):
    """'' when a silent read may just be retried; else what in its output says it cannot run as asked."""
    if rc in (126, 127):   # C.sh: a missing or non-executable binary
        return " ".join((out or "").split())[-200:] or f"rc={rc}"
    m = [*FAULT_SAID.finditer(out or "")][-1:]   # the last one: an API's own sentence comes after its status
    return " ".join(out[max(0, m[0].start() - 100):m[0].end() + 160].split()) if m else ""

def strict(schema):
    """SCHEMA as codex's --output-schema takes it: every object closed, every one of its properties required."""
    if isinstance(schema, list):
        return [strict(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    s = {k: strict(v) for k, v in schema.items()}
    if s.get("type") == "object" and "properties" in s:
        s.update(additionalProperties=False, required=list(s["properties"]))
    return s


# Every codex feature that is a tool or reaches past the prompt (codex-cli 0.153.4, `codex features list`): with
# them off the read has no shell, browser, plugin, skill, hook, image or sub-agent, so a diff that asks it to read
# a file cannot get that file into the PR comment the verdict is posted as.
CODEX_OFF = ("apps", "auth_elicitation", "browser_use", "browser_use_external", "browser_use_full_cdp_access",
             "code_mode_host", "collaboration_modes", "computer_use", "goals", "hooks", "image_generation",
             "in_app_browser", "in_app_chat", "in_app_dictation", "in_app_local_automation", "mentions_v2",
             "multi_agent", "plugin_sharing", "plugins", "remote_plugin", "shell_snapshot", "shell_tool",
             "skill_mcp_dependency_install", "skill_search", "sleep_tool", "tool_call_mcp_elicitation",
             "tool_suggest", "unified_exec", "unified_exec_zsh_fork",
             "view_image", "workspace_dependencies")
# The ALLOWLIST: the features that may stay on in a read, none of them a tool. Anything else on — a feature a new
# codex adds on by default — holds the read with a stop naming it, until someone puts it on one of these lists.
CODEX_ON_OK = ("compaction_image_budget", "content_item_kinds", "enable_request_compression", "fast_mode",
               "guardian_approval", "in_app_updates", "item_ids", "personality", "remote_compaction_v2",
               "resize_all_images", "sqlite", "steer", "terminal_resize_reflow", "tui_app_server",
               "unbounded_connection_retries",
               "tool_search_always_defer_mcp_tools")   # removed in 0.153.4 and --disable does not take; the read has
                                                       # no MCP server to defer (the user config is ignored)
# A feature that is only another's back end, allowed on while the one it serves is off. `--disable unified_exec`
# does not take in 0.153.4 (it still lists true); it is how shell_tool runs, and shell_tool is off.
CODEX_BACKEND = {"unified_exec": "shell_tool"}


# The native codex the npm package vendors, run directly: /usr/local/bin/codex is a `#!/usr/bin/env node` script,
# so running it lets PATH pick the node. {prefix}, {arch} and {triple} are filled per install root and machine.
CODEX_NATIVE = "{prefix}/node_modules/@openai/codex/node_modules/@openai/codex-linux-{arch}/vendor/{triple}/bin/codex"
CODEX_PREFIXES = ("/usr/local/lib", "/usr/lib")
CODEX_ARCH = {"x86_64": ("x64", "x86_64-unknown-linux-musl"), "aarch64": ("arm64", "aarch64-unknown-linux-musl")}
CODEX_SCRIPT = "/usr/local/bin/codex"   # the fallback, absolute; its node then comes from READ_PATH


def codex_bin():
    """The codex a read runs: CC_CODEX from the reviewer config, else the vendored native binary, else CODEX_SCRIPT.
    Always a path, never a bare name resolved on a caller's PATH."""
    set_ = C.conf("CC_CODEX", "")
    if set_:
        return set_
    arch, triple = CODEX_ARCH.get(os.uname().machine, ("", ""))
    for prefix in CODEX_PREFIXES if arch else ():
        path = CODEX_NATIVE.format(prefix=prefix, arch=arch, triple=triple)
        if os.access(path, os.X_OK):
            return path
    return CODEX_SCRIPT


def codex_env():
    """clean_env() with CODEX_HOME and HOME at the passwd home: a worker's CODEX_HOME holding an AGENTS.md, or a HOME
    of its own, must not reach the read (security read of #847)."""
    return dict(clean_env(), CODEX_HOME=os.path.join(C.PASSWD_HOME, ".codex"), HOME=C.PASSWD_HOME)


def codex_argv(*argv):
    out = [codex_bin(), *argv]
    for feature in CODEX_OFF:
        out += ["--disable", feature]
    return out


def codex_tools_left(run):
    """'' when `codex features list`, under the read's own --disable flags, shows nothing on outside CODEX_ON_OK;
    else why not: the features on, or why the list could not be read. It runs under the read's own CODEX_HOME
    (codex_env()); the list takes no flag to ignore that home's config, so a feature it turns on stops the read."""
    rc, out = C.sh(codex_argv("features", "list"), cwd=run, timeout=60, env=codex_env())
    if rc:
        return f"`codex features list` failed (rc={rc}): " + " ".join((out or "").split())[-200:]
    on = {}
    for ln in (out or "").splitlines():
        words = ln.split()
        if len(words) >= 3 and words[-1] in ("true", "false"):
            on[words[0]] = words[-1] == "true"
    if not on:
        return "`codex features list` printed no feature the lander could read"
    left = sorted(f for f, v in on.items() if v and f not in CODEX_ON_OK
                  and not (f in CODEX_BACKEND and on.get(CODEX_BACKEND[f]) is False))
    return f"codex has feature(s) on that the review does not allow: {', '.join(left)}" if left else ""


# codex exec's own count: a line that is only "tokens used", then a line that is only the number (a digit first, so a
# bare "," is no count). A number written inline ("tokens used: 9") is a diff's or an answer's text, not codex's, and a
# count past CODEX_MAX_TOKENS is capped.
CODEX_TOKENS = re.compile(r"^tokens used[ \t]*\r?\n[ \t]*(\d[\d,]{0,19})[ \t]*\r?$", re.M)
CODEX_MAX_TOKENS = 50_000_000


def codex_usd(rc, out):
    """-> the estimated dollars of a `codex exec` that exited `rc` and printed `out`: the last `tokens used` count codex itself
    printed (CODEX_TOKENS, capped at CODEX_MAX_TOKENS) at CODEX_USD_PER_MTOK (CC_LAND_CODEX_USD_PER_MTOK overrides it when it is a finite number >= 0), else
    CODEX_READ_USD, and 0.0 only for rc 126/127 with no count (a missing binary or a refused flag reached no model; a
    timeout's 124 or any other failure may have run the model for the whole read). A nonzero rc with a count is
    charged at least CODEX_READ_USD: a codex that crashed before printing its own count leaves only a pair the PR
    text planted (echoed on stderr), so a "tokens used" / "0" there never makes a failed read free. A usage limit is
    not looked for here: an answer can quote the words, and ask_codex() charges nothing for a read the limit stopped."""
    said = CODEX_TOKENS.findall(out or "")
    if not said:
        return 0.0 if rc in (126, 127) else CODEX_READ_USD
    try:
        rate = float(C.conf("CC_LAND_CODEX_USD_PER_MTOK", str(CODEX_USD_PER_MTOK)))
    except ValueError:
        rate = CODEX_USD_PER_MTOK
    if not math.isfinite(rate) or rate < 0:
        rate = CODEX_USD_PER_MTOK
    try:
        tokens = min(int(said[-1].replace(",", "")), CODEX_MAX_TOKENS)
        usd = round(tokens / 1e6 * rate, 4)
        return max(usd, CODEX_READ_USD) if rc != 0 else usd
    except (ValueError, OverflowError):
        return CODEX_READ_USD


def codex_limit(rc, out, text):
    """True when a `codex exec` that exited `rc` with output `out`, asked `text`, stopped at a usage or rate limit
    (a 429 included): a nonzero exit, and a CODEX_LIMIT_SAID line in the output that is not the prompt's own. The echo can differ from
    the prompt (cut short, whitespace trimmed, CRLF), so beside taking out the exact echo, a line counts only when
    its stripped text is no prompt line, nor the start of one (an echo cut mid-line). A real limit line the prompt
    also holds is missed, which holds the read as a fault rather than bringing in a stand-in. The prompt lines are a
    set and a sorted list (perms' read of #1568: any() over them for every limit line was quadratic in planted lines),
    since the first prompt line at or after a prefix in sorted order starts with it if any does."""
    if rc == 0 or not out:
        return False
    said = {line.strip() for line in text.splitlines()} if text else set()
    order = sorted(said)
    for line in (out.replace(text, "") if text else out).splitlines():
        if not CODEX_LIMIT_SAID.search(line):
            continue
        s = line.strip()
        if s in said:
            continue
        i = bisect.bisect_left(order, s)
        if i < len(order) and order[i].startswith(s):
            continue
        return True
    return False


def ask_codex(text, repo, pr, digest, model):
    """One tool-less `codex exec` read. -> (Verdict | None, usd, why), as ask(); codex reports no dollar cost, so
    `usd` is codex_usd()'s estimate, and 0.0 when the exec never ran."""
    run, cwd = scratch(repo, pr)
    schema, answer = os.path.join(run, "schema.json"), os.path.join(run, "answer.json")
    argv = codex_argv("exec", "-m", model, "-c", f'model_reasoning_effort="{effort()}"', "-c", 'web_search="disabled"',
                      "-s", "read-only", "--ignore-user-config", "--ignore-rules", "--ephemeral",
                      "--skip-git-repo-check", "--color", "never", "--output-schema", schema, "-o", answer, "-C", cwd)
    said, rc, out, usd = "", 1, "", 0.0
    try:
        left = codex_tools_left(run)
        if left:
            return None, 0.0, f"fault: {left}"
        with open(schema, "w") as f:
            json.dump(strict(SCHEMA), f)
        rc, out = C.sh(argv + ["-"], cwd=cwd, input=text, timeout=READ_TIMEOUT, env=codex_env())
        usd = codex_usd(rc, out)
        try:
            with open(answer) as f:
                said = f.read()
        except OSError:
            pass
    finally:
        shutil.rmtree(run, ignore_errors=True)
    v = parse(said, digest, model=model)
    if v:
        return v, usd, ""
    tail = " ".join((out or "").split())[-200:]
    if codex_limit(rc, out, text):
        return None, 0.0, f"limit: rc={rc} {tail}"
    bad = fault(rc, out)
    return None, usd, f"fault: rc={rc} {bad}" if bad else f"no answer: rc={rc} {tail}"


# The names `claude --model` takes that do not start with `claude`: a reader named so is claude's, not codex's.
CLAUDE_ALIASES = ("opus", "sonnet", "haiku", "fable", "opusplan")


# WHERE THE CLAUDE A READ RUNS MAY LIVE. `ln -sf /tmp/fake ~/.local/bin/claude` from a worker's shell once swapped the
# reviewer (security read of #849): the path is the reviewer config's CC_CLAUDE or ~/.local/bin/claude at the passwd
# home, and what it resolves to must be an executable file under one of these roots, or the read is a fault and
# nothing runs. The file is run by its resolved path. This narrows the swap; it does not close a same-uid write into
# the native installer's own versions dir, which only a boundary the worker cannot write does (see the PR of #849's
# follow-up: a separate lander uid, or workers under CC_WORKER_SANDBOX).
def claude_roots():
    return (os.path.join(C.PASSWD_HOME, ".local", "share", "claude", "versions"), "/usr/local/lib", "/usr/lib", "/opt")


def claude_bin():
    """-> (path to run, "") or ("", why not)."""
    named = C.conf("CC_CLAUDE", os.path.join(C.PASSWD_HOME, ".local", "bin", "claude"))
    real = os.path.realpath(named)
    if not any(real.startswith(os.path.realpath(r) + os.sep) for r in claude_roots()):
        return "", f"the reviewer's claude {named} resolves to {real}, outside {', '.join(claude_roots())}"
    if not (os.path.isfile(real) and os.access(real, os.X_OK)):
        return "", f"the reviewer's claude {named} resolves to {real}, which is not an executable file"
    return real, ""


def is_claude(model):
    return model.startswith("claude") or model.split("[")[0] in CLAUDE_ALIASES


def fits(value, schema):
    """value against the subset of JSON Schema SCHEMA uses: type, enum, required, properties, additionalProperties,
    items, maxItems."""
    if "enum" in schema and value not in schema["enum"]:
        return False
    kind = schema.get("type")
    if kind == "string":
        return isinstance(value, str)
    if kind == "array":
        if not isinstance(value, list) or len(value) > schema.get("maxItems", len(value)):
            return False
        return all(fits(x, schema.get("items") or {}) for x in value)
    if kind == "object":
        props = schema.get("properties") or {}
        if not isinstance(value, dict) or any(k not in value for k in schema.get("required") or []):
            return False
        if schema.get("additionalProperties") is False and any(k not in props for k in value):
            return False
        return all(fits(v, props[k]) for k, v in value.items() if k in props)
    return True


# The keys of a result event that carry the model's words: its answer, and the inputs of any tool call it was denied.
MODEL_KEYS = ("structured_output", "permission_denials")


def cli_own(result):
    """A result event as streamed() left it, less the keys that carry the model's words."""
    return {k: v for k, v in result.items() if k not in MODEL_KEYS}


def cli_spoke(e):
    """True when an assistant event is the CLI's own (a limit, an API error, a bad model): fields the model cannot
    set say so. Its text is the CLI's words, and it is not the model speaking."""
    msg = e.get("message")
    return bool((isinstance(msg, dict) and msg.get("model") == "<synthetic>") or e.get("isApiErrorMessage") is True
                or e.get("error"))


CUT = ("max_tokens", "model_context_window_exceeded")   # stop reasons that end a turn before the model did


def streamed(out):
    """claude -p --output-format stream-json --verbose: one JSON event a line, the result last, stderr after it ->
    (the result event, or {}, its `result` the CLI's own words or none | the input of the StructuredOutput call that
    is the read's answer, or None | what the CLI itself said: its result event less the model's keys, its own
    assistant events' text, system events and stderr, never the model's text). A single `--output-format json`
    object is its own result.
    The result event's `result` is the last assistant event's text and its `structured_output` the model's answer, so
    a finding quoting "unknown option" or "usage limit reached" would read as the CLI's fault or limit (security read
    of #1034). The CLI reports a limit, an API error or a bad model as an assistant event of its own, which the model
    cannot forge: message.model "<synthetic>", isApiErrorMessage, or a top-level `error` (cli_spoke()). That event is
    not the model speaking; its text is the CLI's. So `result` is kept as it came when no model event came before
    it (a bad model, a limit hit before the first turn), and is the CLI's own last text when one came after the
    model's last event (a limit hit mid-read, after turns that cost money); otherwise it is dropped.
    A call is an answer only when its turn ended to make it (stop_reason tool_use, or null with a tool_result from
    the CLI accepting it, since stream-json leaves every assistant event's stop_reason null: a max_tokens stop may
    have cut the input short), no stop for its turn was a cut (CUT: the result event's stop_reason is the last
    turn's, and the CLI may accept a cut object that still fits, so a cut result's own structured_output is dropped
    too), the CLI did not reject it (a tool_result with is_error), and it is SCHEMA's object (#824, #772: on a wall
    the CLI may never have checked it, and parse() reads a missing `blocking` as none). Any accepted call
    that says HANDBACK outweighs a LAND in the same stream: the answer is the last whole HANDBACK, or none."""
    result, calls, rejected, accepted, said, spoke, last = {}, [], set(), set(), [], False, None
    # a turn is the model's assistant events between two user events, one message id: each content block is its
    # own event, and a stop that comes later for the turn (the result event's, for the last) speaks for all of it
    turn, cut, prev = 0, set(), False
    # "\n" only: splitlines() also breaks at U+2028, U+2029 and U+0085, which JSON.stringify leaves raw in a string,
    # so a finding quoting one would cut its event in two and put the model's words among the CLI's
    for line in (out or "").split("\n"):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError:
            if not line.lstrip().startswith("{"):   # a cut-off event line is the model's as much as a whole one
                said.append(line)
            continue
        if not isinstance(e, dict):
            continue
        kind, msg = e.get("type"), e.get("message") or {}
        if kind == "result":
            if e.get("stop_reason") in CUT and turn:
                cut.add(turn)
            keep = e.get("is_error") is True and not spoke
            # a cut turn's structured_output can still fit SCHEMA with `unresolved` lost off its end: never an answer
            result = {k: v for k, v in e.items() if (keep or k != "result")
                      and not (k == "structured_output" and e.get("stop_reason") in CUT)}
            if not keep and last is not None:
                result["result"] = last
            said.append(json.dumps(cli_own(result)))
            continue
        if kind not in ("assistant", "user"):
            said.append(line)
            continue
        if kind == "assistant" and cli_spoke(e):
            parts = (msg.get("content") or []) if isinstance(msg, dict) else []
            last = " ".join(c["text"] for c in parts if isinstance(c, dict) and isinstance(c.get("text"), str))
            said.append(f"{e.get('error') or 'cli'}: {last}")
            continue
        if kind == "assistant":
            spoke, last = True, None
            mid = msg.get("id") if isinstance(msg, dict) else None
            if prev is False or prev != mid:
                turn += 1
            prev = mid
            if isinstance(msg, dict) and msg.get("stop_reason") in CUT:
                cut.add(turn)
        else:
            prev = False
        for c in (msg.get("content") or []) if isinstance(msg, dict) else []:
            if not isinstance(c, dict):
                continue
            if kind == "assistant" and c.get("type") == "tool_use" and c.get("name") == "StructuredOutput":
                calls.append((c.get("id"), msg.get("stop_reason"), c.get("input"), turn))
            elif kind == "user" and c.get("type") == "tool_result":
                (rejected if c.get("is_error") else accepted).add(c.get("tool_use_id"))
    calls = [c for c in calls if c[0] is None or c[0] not in rejected]
    # stream-json writes stop_reason null on every assistant event (probed on #960 at 3447d443, 10-07: the call
    # carried null, the CLI answered it "provided successfully" and only the result event said tool_use), so a
    # null stop is whole when the CLI accepted the call and no later stop cut its turn: it parsed the input whole to
    # say so, but an object cut at max_tokens can still fit SCHEMA with an optional `unresolved` list lost off its end
    done = lambda c: c[3] not in cut and (  # noqa: E731
        c[1] == "tool_use" or (c[1] is None and c[0] is not None and c[0] in accepted))
    whole = [c[2] for c in calls if done(c) and fits(c[2], SCHEMA)]
    answer = None
    if any(isinstance(c[2], dict) and c[2].get("verdict") == "HANDBACK" for c in calls):
        answer = ([a for a in whole if a["verdict"] == "HANDBACK"] or [None])[-1]
    elif calls and done(calls[-1]) and fits(calls[-1][2], SCHEMA):
        answer = calls[-1][2]
    return result, answer, "\n".join(said)


def ask(text, repo, pr, digest, model=None):
    """One tool-less read. -> (Verdict | None, usd, why). Verdict None and why starting 'limit' is a usage limit;
    'wall' is the read's own budget cap; 'fault' is a read that cannot run as asked (fault()); any other None is a
    read that answered nothing."""
    model = model or readers()[0]
    if not is_claude(model):
        return ask_codex(text, repo, pr, digest, model)
    # The prompt goes on stdin: one argv over 128 KiB is refused by the kernel (E2BIG), and most diffs pass that.
    exe, bad = claude_bin()
    if bad:
        return None, 0.0, f"fault: {bad}"
    argv = [exe, "-p", "--model", model,
            "--effort", effort(), "--max-budget-usd", C.conf("CC_LAND_REVIEW_BUDGET", "3"),
            "--output-format", "stream-json", "--verbose", "--json-schema", json.dumps(SCHEMA),
            "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands", "--tools", ""]
    run, cwd = scratch(repo, pr)
    env = dict(clean_env(), DISABLE_PROMPT_CACHING="1")   # one call: a cache write is paid and never read
    try:
        rc, out = C.sh(argv, cwd=cwd, input=text, timeout=READ_TIMEOUT, env=env)
    finally:
        shutil.rmtree(run, ignore_errors=True)
    j, answer, cli = streamed(out)
    usd = float(j.get("total_cost_usd") or 0)
    if answer and answer["verdict"] == "HANDBACK" and "structured_output" in j:   # a HANDBACK the stream carried
        j = dict(j, structured_output=answer)                                    # outweighs the result's LAND
    v = parse(json.dumps(j), digest, model=model)
    if v:
        return v, usd, ""
    if j.get("subtype") in WALLS:
        # the turn that crossed the cap had already answered: that answer is the read, not a wall
        v = parse(json.dumps({"structured_output": answer, "usage": j.get("usage")}), digest, model=model)
        if v:
            return v, usd, ""
        return None, usd, f"wall: {j['subtype']} at ${usd:.2f}"
    own = json.dumps(cli_own(j)) if j else ""   # the CLI's words only: a diff can say "usage limit" too
    said = own[-400:] if j else cli[-400:]
    if usd == 0 and LIMIT_SAID.search(said):
        return None, usd, f"limit: {said[-160:]}"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(own or cli or "{}")
    try:
        lrc, _ = C.sh([os.path.join(BIN, "cc-limit"), "check", f.name], timeout=60)
    finally:
        os.unlink(f.name)
    if lrc == 0:
        return None, usd, "limit: cc-limit check says the run hit a usage limit"
    bad = fault(rc, cli)   # the CLI's words only: a finding can quote "unknown option" too
    return None, usd, f"fault: rc={rc} {bad}" if bad else f"no answer: rc={rc} {said[-200:]}"


# --- the repo side of a read ---------------------------------------------------------------------------------------

def root_of(job):
    """The checkout a review reads. $CC_DEV and the clones dir come from jobs (jobs.dev, jobs.clones_dir), where
    git.host_tree looks for the checkouts it takes, so the root named here is never one git.taken() refuses."""
    from lander import jobs as J
    if job.extra.get("root"):
        return job.extra["root"]
    if job.member:
        return os.path.join(J.clones_dir(), job.repo)
    return os.path.join(J.dev(), job.repo)


PLAIN_DIFF = ("--no-ext-diff", "--no-textconv", "--no-color")


def git(root, *args, timeout=120):
    """git in the checkout, with no replace refs: a worker can write refs/replace/ there and swap one object for
    another under every read that follows."""
    env = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1")
    return C.sh(["git", *args], cwd=root, timeout=timeout, env=env)


def blind(root, *revs):
    """git.sealed(): a scratch bare repo holding only the revs, fetched from the checkout, that reads no config,
    attributes or template of anyone's -> ((rc, out), run).

    A worker can write the checkout's shared .git: its objects, its replace refs, its config (diff.external, a
    textconv, a merge driver, color) and its info/attributes, where `*.py -diff` turns a text change into one "Binary
    files … differ" line and `* merge=x` runs the program merge.x.driver names. Git run here sees none of it: every
    object is re-hashed on the way in, binary is decided by a file's bytes, and a merge uses git's own text merge."""
    from lander import git as G
    return G.sealed(root, *revs, sh=C.sh)


def plain_diff(root, a, b, *opts, timeout=300):
    """`git diff <opts> a b` as git's own text, whatever the checkout's config or attributes say -> (rc, text).
    It runs in blind(): a real binary still shows as one line rather than its bytes in the prompt."""
    with blind(root, a, b) as (got, run):
        if run is None:
            return got
        return run("diff", *PLAIN_DIFF, *opts, *got[1], timeout=timeout)


def change_diff(root, base, head, *opts, timeout=300):
    """`git diff <opts> <merge-base> head`, the merge-base found in blind() too -> (rc, text). In the checkout a
    replace ref or a graft can move the merge-base onto the branch, and every path before it drops out of the diff."""
    with blind(root, base, head) as (got, run):
        if run is None:
            return got
        rc, mb = run("merge-base", *got[1])
        if rc:
            return rc, mb
        return run("diff", *PLAIN_DIFF, *opts, mb.strip(), got[1][1], timeout=timeout)


REBASED = ("(this head was rebased since the earlier read: below is a diff of the two heads limited to the paths"
           " either head's own change touches, so main's other files drop out. Main's own edits to those paths can"
           " show here too)\n")


def interdiff(root, base, old, new, timeout=300):
    """What the author changed between the head an earlier read saw and this one -> (rc, text), as heads_diff()
    compares them, a rebased one headed so the read knows."""
    rc, d, rebased = heads_diff(root, base, old, new, timeout=timeout)
    if rc or not rebased:
        return rc, d
    return 0, REBASED + (d or "(no change: the rebase alone moved this head)\n")


RESOLVED = ("\n(and the hand resolution: the old head auto-merged onto this head's merge-base with main, diffed"
            " against this head, so whatever a conflict resolution or a merge of main changed shows here)\n")


def delta_text(root, base, old, new, timeout=300):
    """What `lander perms-read --since <old>` reads -> (rc, text): interdiff() of the two heads, then the hand
    resolution, as perms checks one by hand (perms' answer of 10-22): `git merge-tree` of the old head onto the new
    head's merge-base with `base`, that tree diffed whole against the new head, so no path drops out. All in blind()."""
    rc, d = interdiff(root, base, old, new, timeout=timeout)
    if rc:
        return rc, d
    with blind(root, base, old, new) as (got, run):
        if run is None:
            return got
        b, o, n = got[1]
        rc, mn = run("merge-base", b, n)
        if rc:
            return rc, mn
        rc, out = run("merge-tree", "--write-tree", mn.strip(), o, timeout=timeout)
        if rc not in (0, 1) or not out.split():   # 1 is a conflict: its tree holds the markers, and that is read too
            return rc or 1, out
        rc, r = run("diff", *PLAIN_DIFF, "--full-index", "--no-renames", out.split()[0], n, timeout=timeout)
    return rc, (r if rc else d + RESOLVED + (r or "(none: the new head is the old one merged onto main)\n"))


def merges_clean(root, base, head):
    """True when `head` merges onto `base` with no conflict (`git merge-tree`, in blind()): perms' carry and delta
    read hold only for such a head (perms' answer of 10-22)."""
    with blind(root, base, head) as (got, run):
        return run is not None and run("merge-tree", "--write-tree", *got[1])[0] == 0


def heads_diff(root, base, old, new, *opts, mains=False, timeout=300):
    """`git diff <opts> old new` as the author changed it -> (rc, text, rebased). Unrebased (both heads share a
    merge-base with `base`) it is that diff whole. Rebased, a two-commit diff carries every file main changed, so it
    is that diff on the paths either head's own change touches (each taken against its own merge-base). Each path is
    literal, as blind() sets GIT_LITERAL_PATHSPECS. Hunks keep their numbers, so a line moved from one function into
    another still shows. With `mains` (for --name-only -z) a rebased one also names those paths main changed between
    the two merge-bases. All git runs in blind()."""
    with blind(root, base, old, new) as (got, run):
        if run is None:
            return (*got, False)
        b, o, n = got[1]
        rc, mo = run("merge-base", b, o)
        if rc:
            return rc, mo, False
        rc, mn = run("merge-base", b, n)
        if rc:
            return rc, mn, False
        mo, mn = mo.strip(), mn.strip()
        if mo == mn:
            return (*run("diff", *PLAIN_DIFF, *opts, o, n, timeout=timeout), False)
        paths = set()
        for mb, head in ((mo, o), (mn, n)):
            rc, names = run("diff", *PLAIN_DIFF, "--name-only", "--no-renames", "-z", mb, head, timeout=timeout)
            if rc:
                return rc, names, True
            if "\ufffd" in names:   # a name that isn't UTF-8 came back replaced, so as a pathspec it matches nothing
                return 1, "a path name is not UTF-8", True   # and its file would drop out silently: fail closed
            paths.update(p for p in names.split("\0") if p)
        if not paths:
            return 0, "", True
        rc, d = run("diff", *PLAIN_DIFF, *opts, o, n, "--", *sorted(paths), timeout=timeout)
        if rc or not mains:
            return rc, d, True
        rc, m = run("diff", *PLAIN_DIFF, *opts, mo, mn, "--", *sorted(paths), timeout=timeout)
        return rc, (m if rc else d + m), True


def diff_of(root, base, head):
    """The change as the review reads it. --no-renames as files_of() runs, so each section is one path: a rename
    section heads two names, and cut_paths() could pair a forged header with a decoy file."""
    rc, d = change_diff(root, base, head, "-U3", "--full-index", "--no-renames")
    return "" if rc else d


def files_of(root, base, head):
    """The paths the change touches, each as it is (-z: no quoting, a newline stays in its name)."""
    rc, out = change_diff(root, base, head, "--name-only", "--no-renames", "-z")
    return [] if rc else [p for p in out.split("\0") if p]


DIFF_CAP = 400_000


def cut_paths(diff, paths):
    """The paths whose change capped() cuts or drops, `paths` in the diff's own order (files_of()). A cut diff whose
    sections cannot be matched one to one with `paths`, each headed `diff --git a/<path> b/<path>`, drops them all,
    the safe failure: a rename is one section for two paths, a type change two for one, and a quoted name matches
    nothing, so no count that happens to agree can shift a cut path onto a whole section."""
    if len(diff) <= DIFF_CAP:
        return []
    starts = [m.start() for m in re.finditer(r"(?m)^diff --git ", diff)]
    if len(starts) != len(paths) or any(not diff.startswith(f"diff --git a/{p} b/{p}\n", at)
                                        for p, at in zip(paths, starts)):
        return list(paths)
    ends = starts[1:] + [len(diff)]
    return [p for p, end in zip(paths, ends) if end > DIFF_CAP]


def whole_paths(diff, paths):
    """The paths whose change the prompt's diff shows whole as text: the diff is not cut at all, and the path has
    exactly one section headed `diff --git a/<path> b/<path>`, with a hunk and no binary line. Every changed line of
    such a path is in the diff, so a cut of its file in the files block hides none of them. A rename, a quoted name,
    a type change (two sections) or a mode-only change matches nothing here and so keeps its flag. A cut diff names
    none: its sections are found by line, and past the cap no section can be trusted to be the path's own."""
    if len(diff) > DIFF_CAP:
        return []
    starts = [m.start() for m in re.finditer(r"(?m)^diff --git ", diff)]
    ends = starts[1:] + [len(diff)]
    whole = []
    for p in paths:
        own = [(at, end) for at, end in zip(starts, ends) if diff.startswith(f"diff --git a/{p} b/{p}\n", at)]
        if len(own) != 1:
            continue
        sec = diff[own[0][0]:own[0][1]]
        if re.search(r"(?m)^@@ ", sec) and not re.search(r"(?m)^(Binary files |GIT binary patch)", sec):
            whole.append(p)
    return whole


def capped(diff, dropped=()):
    """The diff as the prompt carries it: whole up to DIFF_CAP, else cut there with a line saying so and naming the
    paths whose change the cut takes (the digest is always taken over the whole diff)."""
    if len(diff) <= DIFF_CAP:
        return diff
    lost = f"; the change to these paths is cut or missing: {', '.join(shown(p) for p in dropped)}" if dropped else ""
    return diff[:DIFF_CAP] + f"\n(the diff is cut here: it is {len(diff)} characters and the read takes {DIFF_CAP}{lost})\n"


FILE_CAP, FILES_CAP = 60_000, 400_000
# A file whose whole change is in `diff` and that is longer than WHOLE_UNDER characters is shown around its changes,
# AROUND lines either side and no more than AROUND_CHARS characters of them (one markdown line can be 15k), not
# whole: #960 (+142/-51) carried 300k characters of files (cc-msg, selftest.sh and DESIGN.md at 60k each), 151k
# tokens a read, and walled twice at $3.49 with no verdict kept.
WHOLE_UNDER, AROUND, AROUND_CHARS = 20_000, 60, 6_000
SPAN = re.compile(r"^@@ -[0-9,]+ \+(\d+)(?:,(\d+))? @@", re.M)


def spans_of(udiff):
    """`git diff -U0` of one path -> [(first, last)], the 1-based lines of the new side each hunk touches; a hunk
    that only deletes touches the line it follows."""
    out = []
    for m in SPAN.finditer(udiff or ""):
        start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
        out.append((max(start, 1), max(start + count - 1, start, 1)))
    return out


def around(text, spans, width=AROUND, chars=AROUND_CHARS):
    """`text` cut to each span and the lines next to it, up to `width` lines and `chars` characters either side, each
    gap one line naming the lines it leaves out, or None when no span is given (then nothing says where the change
    is, and the caller shows the file as before)."""
    if not spans:
        return None
    # "\n" only, as git counts lines: splitlines() also breaks at \r and U+2028, and every window after one would
    # drift off the change it is meant to show
    parts = text.split("\n")
    lines = [x + "\n" for x in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
    keep = []
    for first, last in sorted(spans):
        lo, hi = max(min(first, len(lines)), 1), min(last, len(lines))
        took = 0
        while lo > 1 and first - lo < width and took + len(lines[lo - 2]) <= chars:
            lo, took = lo - 1, took + len(lines[lo - 2])
        took = 0
        while hi < len(lines) and hi - last < width and took + len(lines[hi]) <= chars:
            hi, took = hi + 1, took + len(lines[hi])
        if keep and lo <= keep[-1][1] + 1:
            keep[-1] = (keep[-1][0], max(keep[-1][1], hi))
        elif lo <= hi:
            keep.append((lo, hi))
    out, at = [], 1
    for lo, hi in keep:
        if lo > at:
            out.append(f"(… lines {at}-{lo - 1} of {len(lines)} not shown …)\n")
        out.append("".join(lines[lo - 1:hi]))
        if out[-1] and not out[-1].endswith("\n"):
            out[-1] += "\n"
        at = hi + 1
    if at <= len(lines):
        out.append(f"(… lines {at}-{len(lines)} of {len(lines)} not shown …)\n")
    return "".join(out)


BINARY_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".otf", ".ttf", ".woff", ".woff2", ".gpg",
                ".zip", ".gz", ".tar", ".xz", ".mp4", ".mp3", ".wav"}


def unread_binary(path, mode):
    """Why a change git calls binary must not pass unread, or "" when it may: every path is flagged unless its
    extension is a known binary type, and an executable one always is. One NUL byte makes git call a script, a unit
    file or an HTML page binary, and each still runs past it."""
    if mode == "100755":
        return "executable"
    ext = os.path.splitext(os.path.basename(path))[1].lower()
    return "" if ext in BINARY_TYPES else f"not a known binary type: {ext or 'no extension'}"


def entry(run, tree, path):
    """(mode, blob id) of `path` in `tree`, or ("", "none") when the tree has no entry for it (blind() makes the
    path literal, so `*` or `:` in a name matches only that name)."""
    rc, out = run("ls-tree", "-z", tree, "--", path)
    for ent in out.split("\0") if not rc else ():
        meta, _, name = ent.partition("\t")
        parts = meta.split()
        if name == path and len(parts) == 3:
            return parts[0], parts[2]
    return "", "none"


def shown(path):
    """The path as a files header prints it: as it is, or JSON-quoted when it holds a control character (a newline in
    a name must not start a header of its own)."""
    return json.dumps(path, ensure_ascii=False) if any(ord(c) < 32 or ord(c) == 127 for c in path) else path


def file_block(path, old_mode, new_mode, notes=(), unseen=(), text=None, body=None, exempt=False, diffed=False):
    """One path's entry in the files block, and the one place its rule is kept: a path whose whole new content the
    read does not see as text, here and in the diff, is FLAGGED with the reasons in `unseen`. `text` is the whole
    new content, `body` what is shown of it; if they differ and no reason was given the path is still FLAGGED.
    `diffed` (whole_paths()) says every changed line is in the diff, so a body short of the text is context, not a
    hidden change; a reason in `unseen` still flags. `exempt` is only for what needs no reading: a deletion, or a
    known binary type that is not executable."""
    unseen = list(unseen)
    if not exempt and not unseen and not diffed and (text is None or body != text):
        unseen.append("its content is not shown in full")
    head = "; ".join([f"old mode {old_mode or 'none'}, new mode {new_mode or 'none'}", *notes]
                     + ([f"FLAGGED: {', '.join(unseen)}"] if unseen else []))
    return f"=== {shown(path)} ({head})" + ("\n" + body if body is not None else "")


def merged_files(root, base, head, files, dropped=(), whole=()):
    """The changed files as they will be after the merge, each through file_block(). The merge and every read of it
    run in blind(), so no merge driver or attribute the checkout names can run or change what the read sees.

    FLAGGED, and so handed back by review.md: a path whose change the diff cut drops (`dropped`, from cut_paths()),
    a file cut at FILE_CAP or left out when the block is full unless its whole diff is shown (`whole`, from
    whole_paths(): then the cut is a note), a binary change unread_binary() names, a symlink or a submodule (gitlink)
    added, changed or removed, and a file git cannot show. A file is "deleted" only when the merged tree has no entry
    for it.
    A file whose whole change is in the diff (`whole`) and that is over WHOLE_UNDER characters is shown around its
    changes (around(): up to AROUND lines and AROUND_CHARS characters either side of each hunk of `git diff -U0
    <merge-base> <merged tree>`), with a note saying so; every line the change touches is in the diff, so this is
    context, not a flag. If git gives no hunk for it, it is shown as before."""
    with blind(root, base, head) as (got, run):
        if run is None:
            return "\n".join(file_block(p, "?", "?", unseen=["git could not read this change"]) for p in files)
        base, head = got[1]
        rc, tree = run("merge-tree", "--write-tree", "-z", base, head)
        tree = tree.split("\0")[0].strip() if not rc and tree.strip() else head
        rc, mb = run("merge-base", base, head)
        mb = "" if rc else mb.strip()
        out, total = [], 0
        for p in files:
            (old_mode, old_id), (new_mode, new_id) = entry(run, base, p), entry(run, tree, p)
            modes = (old_mode, new_mode)
            unseen = ["the diff is cut before its change"] if p in dropped else []
            if "120000" in modes:
                unseen.append("a symlink change" + (", its target below" if new_mode == "120000" else ""))
            if "160000" in modes:
                unseen.append("a submodule (gitlink) change: git shows a commit id, not the files it brings")
                out.append(file_block(p, *modes, [f"old commit {old_id}, new commit {new_id}"], unseen))
                continue
            if not new_mode:
                out.append(file_block(p, *modes, ["deleted by this change"], unseen, exempt=True))
                continue
            rc, text = run("show", f"{tree}:{p}")
            if rc:
                out.append(file_block(p, *modes, unseen=unseen + [f"git could not show this file, blob {new_id}"]))
                continue
            if "\0" in text[:8000]:
                why = unread_binary(p, new_mode)
                out.append(file_block(p, *modes, [f"binary, not shown: old blob {old_id}, new blob {new_id}"],
                                      unseen + ([f"binary, {why}"] if why else []), exempt=not why))
                continue
            diffed = p in whole and not unseen
            near = None
            if diffed and mb and len(text) > WHOLE_UNDER:
                rc, u = run("diff", *PLAIN_DIFF, "-U0", mb, tree, "--", p)
                near = None if rc else around(text, spans_of(u))
            body = (near if near is not None else text)[:FILE_CAP]
            if total + len(body) > FILES_CAP:
                if diffed:
                    out.append(file_block(p, *modes, ["not shown here, the files block is full; its whole diff is in "
                                                      "`diff`"], text=text, diffed=True))
                else:
                    out.append(file_block(p, *modes, unseen=unseen + ["not shown: the files block is full"], text=text))
                continue
            total += len(body)
            notes = []
            if near is not None:
                notes.append(f"shown around its changes, {len(body)} of {len(text)} characters; its whole diff is in "
                             "`diff`")
            elif len(body) < len(text) and diffed:
                notes.append(f"shown to {FILE_CAP // 1000} kB of {len(text)} characters; its whole diff is in `diff`")
            elif len(body) < len(text):
                unseen.append(f"cut at {FILE_CAP // 1000} kB of {len(text)} characters")
            out.append(file_block(p, *modes, notes, unseen, text=text, body=body, diffed=diffed))
        return "\n".join(out)


def brief_of(job):
    from lander import board
    track = board.track_for(job)
    path = os.path.join(os.path.expanduser(C.conf("CC_STATE", "~/.cc/state")), board.project_of(job), track, "task.md")
    try:
        with open(path) as f:
            return f.read()[:20_000] if track else ""
    except OSError:
        return ""


def rules_of(root, base):
    """docs/REVIEW.md at `base`, read in blind(): the checkout's ref and its object are both a worker's to write."""
    with blind(root, base) as (got, run):
        if run is None:
            return ""
        rc, text = run("show", f"{got[1][0]}:docs/REVIEW.md", timeout=60)
        return "" if rc else text


TESTED_CAP = 4000
# a heading that opens the body's own account of its testing: "## Tested", "**How it was tested**", "Testing:"
TESTED_HEAD = re.compile(r"^\s*(?:#{1,6}\s*|\*\*|__)?\s*(?:how (?:it was |this was |I )?)?test(?:ed|ing)\b", re.I)
NEXT_HEAD = re.compile(r"^\s*(?:#{1,6}\s|\*\*[^*]+\*\*\s*:?\s*$|__[^_]+__\s*:?\s*$)")
# a line that reads as a verdict or as the prompt's own frame is dropped, never shown (owner, 10-12: "strip anything
# that looks like a verdict line or a prompt-frame line"). It is matched after plain() folds the line, so fullwidth
# letters and zero-width characters cannot hide a verdict; the verdict words match in capitals only and "verdict" only
# with its ":" or "=", so a sentence that says the PR lands or was handed back survives (security read, 10-12)
UNTRUSTED_LINE = re.compile(r"(?i:verdict)\s*[:=]|\b(?:LAND|HANDBACK|DO-NOT-LAND)\b|<<<|>>>|@[A-Z]+@|<!--|-->"
                            r"|(?i:cc-land-review|\bignore (?:all |any |the )?(?:previous |above |prior |these )?"
                            r"instruction|^\s*(?:system|assistant|user|human)\s*:|</?(?:system|instructions?|prompt)\b)")


def plain(line):
    """`line` under NFKC with every format (Cf) character gone: "ＶＥＲＤＩＣＴ" reads VERDICT, "L\u200bAND" reads LAND."""
    return "".join(ch for ch in unicodedata.normalize("NFKC", line) if unicodedata.category(ch) != "Cf")


def tested_of(body):
    """The PR body's Tested section, as untrusted text for the `tested` block: from its heading ("## Tested",
    "**How it was tested**", "Testing: …") to the next heading, each line folded by plain(), every line UNTRUSTED_LINE
    matches dropped (and the count said), the rest cut at TESTED_CAP characters. '' when the body has no such
    heading."""
    got = None
    for line in (body or "").splitlines():
        line = plain(line)
        if got is None:
            if TESTED_HEAD.match(line):
                # a heading ("## Tested", "**Tested:** …") keeps what follows its colon; a plain sentence ("Tested
                # with check.sh: 0 failed") is itself the claim. Either runs to the next heading, blank lines and all
                para = not re.match(r"\s*(?:#|\*\*|__)", line)
                rest = line if para else (line.split(":", 1)[1] if ":" in line else "")
                got = [rest.strip(" *_")] if rest.strip(" *_") else []
        elif NEXT_HEAD.match(line):
            break
        else:
            got.append(line)
    if got is None:
        return ""
    kept = [line for line in got if not UNTRUSTED_LINE.search(line)]
    text = "\n".join(kept).strip()
    if len(text) > TESTED_CAP:
        text = text[:TESTED_CAP] + f"\n(… cut at {TESTED_CAP} characters)"
    if len(kept) < len(got):
        text += f"\n({len(got) - len(kept)} line(s) dropped: they read as a verdict or as this prompt's own frame)"
    return text.strip()


BODY_CAP = 20_000   # the brief's own cap (brief_of): the author's text gets no more room than the brief does
BODY_UNAVAILABLE = ("The PR body is unavailable: `gh pr view` could not fetch it, so this read was not given the "
                    "PR's title or description.")


def body_of(facts):
    """The PR's title and whole body for the `body` block: the author's text (dispatch #1111 was handed back twice on
    "the body was not provided for review" while the body named what the brief asked), each line folded by plain()
    and every line UNTRUSTED_LINE matches dropped as tested_of() does, cut at BODY_CAP. `facts` None (gh could not
    fetch them) gives BODY_UNAVAILABLE, so the read is told rather than left to guess."""
    if facts is None:
        return BODY_UNAVAILABLE
    got = [plain("Title: " + " ".join(str(facts.get("title") or "(untitled)").split()))]
    got += [plain(line) for line in str(facts.get("body") or "").splitlines()]
    kept = [line for line in got if not UNTRUSTED_LINE.search(line)]
    text = "\n".join(kept).strip()
    if not str(facts.get("body") or "").strip():
        text += "\n(the PR body is empty)"
    if len(text) > BODY_CAP:
        text = text[:BODY_CAP] + f"\n(… cut at {BODY_CAP} characters)"
    if len(kept) < len(got):
        text += f"\n({len(got) - len(kept)} line(s) dropped: they read as a verdict or as this prompt's own frame)"
    return text.strip()


def pr_view(root, pr, fields="comments"):
    """`gh pr view --json <fields>`'s answer, over REST when the repo is GitHub's (gh.pr_facts), else None."""
    return GH.pr_facts(root, pr, fields)[0]


def post(root, pr, body):
    return GH.comment(root, pr, body)


# --- review / delta_review -----------------------------------------------------------------------------------------

def _no_diff(job):
    """The PR changes files but git gave no diff (a fetch that did not land, a merge-base it cannot find): a read of
    nothing would judge nothing, so none is bought and the next tick asks again."""
    return T.Verdict(verdict=T.INCOMPLETE, digest=job.digest,
                     extra={"why": f"no diff for {len(job.files)} changed file(s) at {job.head[:12]}",
                            "until": limit_until("")})


def _unread(job):
    """gh could not give the PR's comments: a handback recorded there cannot be ruled out, so nothing is read and
    nothing lands; the next tick asks again (PR #1174: a transient gh error read as "no comments" merged it unread)."""
    return T.Verdict(verdict=T.INCOMPLETE, digest=job.digest,
                     extra={"why": f"cannot read PR #{job.pr}'s comments", "until": limit_until("")})


def _security_open(job, comments):
    """open_security(), unless perms' ledger holds its LAND of this exact head (perms_recorded at keys() of the
    job's diff): #1198's handback stood from an old head over perms' LAND at the head now, because no
    LAND marker named that head. A LAND only carried from an earlier head (carried_from) clears nothing. Nor does a
    LAND the HANDBACK was posted after or in the same second as (Opus read of #1673: perms records few FIXes, so a
    later HANDBACK marker is its only word), and a time either side does not give (E.epoch_of 0) leaves it standing."""
    from lander import events as E
    sec = open_security(comments, job.head)
    land = sec and perms_recorded(job.repo, job.pr, job.head, keys(job, diff_of(root_of(job), job.base_sha, job.head)))
    if land:
        land = E.epoch_of(land.get("at"))   # the entry whose verdict was checked: one read of the ledger
        back = E.epoch_of(sec.extra.get("at"))
        if back and land and back < land:
            return None
    return sec


def _security_stands(job, comments):
    """A security reader's HANDBACK nothing has cleared (_security_open) -> that HANDBACK, read or not: no read the
    lander buys is a security reader's, so none can clear it. Else None."""
    sec = _security_open(job, comments)
    if not sec:
        return None
    was = sec.extra.get("head", "")[:12] or "an earlier head"
    return T.Verdict(verdict=T.HANDBACK_VERDICT, digest=job.digest, model=sec.model,
                     blocking=list(sec.blocking) + [f"a security HANDBACK by {sec.model} stands from {was}; only a "
                                                    "security reader's LAND clears it (`lander record ... LAND --by "
                                                    f"{PERMS_SECURITY_READER}` from the perms seat)"],
                     extra={"head": sec.extra.get("head", ""), "security": True})


def _security_unread(job, comments, digests):
    """The plan names a security path (plan.extra["security"]) and perms' file holds no record of this head at any of
    `digests` (perms_recorded) nor one that carries to it (carried_from) -> INCOMPLETE for the planning seat
    (host=True, security=True); nothing is bought.
    Else None. `comments` is not read: no marker clears a security path."""
    need = list((job.plan.extra.get("security") if job.plan else None) or [])
    if not need:
        return None
    if perms_recorded(job.repo, job.pr, job.head, digests) or carried_from(job):
        return None
    shown = ", ".join(need[:5]) + (f" and {len(need) - 5} more" if len(need) > 5 else "")
    return T.Verdict(verdict=T.INCOMPLETE, digest=job.digest, extra={
        "host": True, "security": True,
        "why": f"it changes {shown}, which merges only on perms' security read of this change, and perms' "
               f"{PERMS_READS} holds no record of head {job.head[:12]} (perms records its LAND with `lander record "
               "... --head <full sha>` from its seat, which writes it, then queue it again)"})


def review(job, comments=None):
    """See the module doc. `comments` is the PR's comment list when the caller already has it."""
    root = root_of(job)
    if comments is None:
        facts = pr_view(root, job.pr)
        if facts is None:
            return _unread(job)
        comments = facts.get("comments") or []
    sec = _security_stands(job, comments)
    if sec:
        return sec
    diff = diff_of(root, job.base_sha, job.head)
    if not diff and job.files:
        return _no_diff(job)
    need = _security_unread(job, comments, keys(job, diff))
    if need:
        return need
    have = recorded(comments, keys(job, diff), job.head) or _perms_land(job, keys(job, diff))
    if have:
        return have
    # a HANDBACK standing from an earlier head is read again whether or not the change is on a paid path: #1064's
    # security handback was dropped when its new head touched no paid path and landed with no read
    prior = latest(comments)
    if prior and prior.verdict == T.HANDBACK_VERDICT and prior.extra.get("head"):
        return delta_review(job, prior, comments=comments, diff=diff)
    if not (job.plan and job.plan.paid) and not (prior and prior.verdict == T.HANDBACK_VERDICT):
        return T.Verdict(verdict=T.LAND, digest=job.digest, extra={"read": "none"})
    return _buy(job, "review.md", diff, {})


def standing(job, comments=None):
    """The HANDBACK the box last wrote on this PR, at any head, or None. The lane asks it of a change on no paid path
    before it lets one merge unread; a PR whose comments cannot be read raises, so the job is held, not merged."""
    if comments is None:
        facts = pr_view(root_of(job), job.pr)
        if facts is None:
            raise RuntimeError(f"cannot read PR #{job.pr}'s comments, so a standing handback cannot be ruled out")
        comments = facts.get("comments") or []
    prior = _security_open(job, comments) or latest(comments)
    return prior if prior and prior.verdict == T.HANDBACK_VERDICT else None


def land_recorded(job, comments=None):
    """The LAND already recorded at this job's head and digest (a seat's `lander record`, or an earlier read), or
    None: no such marker, a newer HANDBACK at the digest, or comments that will not read. The light lane (light.py)
    lands only on one."""
    if comments is None:
        facts = pr_view(root_of(job), job.pr)
        if facts is None:
            return None
        comments = facts.get("comments") or []
    v = recorded(comments, keys(job, diff_of(root_of(job), job.base_sha, job.head)), job.head)
    at = (v.extra.get("head") or "") if v else ""
    return v if v and v.verdict == T.LAND and len(at) >= 7 and job.head.startswith(at) else None


def delta_review(job, prior, comments=None, diff=None):
    root = root_of(job)
    if comments is None:
        facts = pr_view(root, job.pr)
        if facts is None:
            return _unread(job)
        comments = facts.get("comments") or []
    sec = _security_stands(job, comments)
    if sec:
        return sec
    diff = diff if diff is not None else diff_of(root, job.base_sha, job.head)
    if not diff and job.files:
        return _no_diff(job)
    need = _security_unread(job, comments, keys(job, diff))
    if need:
        return need
    have = recorded(comments, keys(job, diff), job.head) or _perms_land(job, keys(job, diff))
    if have:   # a verdict recorded at this digest after the prior one (a seat's `record`) is the one that stands
        return have
    was = prior.extra.get("head", "")
    rc, full = git(root, "rev-parse", "--verify", "-q", f"{was}^{{commit}}") if was else (1, "")
    rc2, inter = interdiff(root, job.base_sha, full.strip(), job.head) if not rc else (1, "")
    if rc or rc2:   # the head that read saw is gone (a force-push) or the compare failed: read it whole
        inter = ("(the head the earlier read saw is no longer in this repository, or git could not compare the two"
                 " heads; read the whole diff)")
    numbered = "\n".join(f"{i}. {b}" for i, b in enumerate(prior.blocking, 1)) or "(none)"
    return _buy(job, "delta.md", diff, {"PRIOR": numbered, "INTERDIFF": capped(inter)}, prior=prior.blocking)


LIMIT_UNTIL = re.compile(r"usage limit until (\d\d):(\d\d)Z(?:\s*\((\d+)m left\))?")
RETRY_AFTER = 900


def limit_until(text, now=None):
    """When an INCOMPLETE is worth asking again: a minute past `(Nm left)` when the limit text says it, else the
    clock time it names if that is within RETRY_AFTER, else RETRY_AFTER from now. A UTC stamp, for the lane's hold."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    m = LIMIT_UNTIL.search(text or "")
    at = now + datetime.timedelta(seconds=RETRY_AFTER)
    if m and m.group(3):
        at = now + datetime.timedelta(minutes=int(m.group(3)) + 1)
    elif m:
        end = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        end += datetime.timedelta(seconds=60)
        if now < end <= now + datetime.timedelta(seconds=RETRY_AFTER):
            at = end
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def stand_in(job, model, why):
    """The claude model that reads in place of `model` after its read came back `why`, or "": only for a usage or
    rate limit on a reader that is not claude's, on a plan that names no security path (the module doc)."""
    if not why.startswith("limit") or is_claude(model) or not job.plan or job.plan.extra.get("security"):
        return ""
    sub = C.conf("CC_LAND_REVIEW_LIMIT_READER", "").strip() or next((m for m in readers() if is_claude(m)), "")
    return sub if sub and is_claude(sub) else ""


def combined(reads):
    """[(model, Verdict)], every reader's -> the one Verdict the landing acts on: HANDBACK when any reader's is, every
    reader's findings tagged with its model (and the reader it stood in for), and extra `readers` naming each
    reader's own verdict, and `stood_in` each stand-in. A single reader's Verdict is returned as it is, unless it is
    a stand-in's."""
    subs = [{"reader": x.extra["stood_in_for"], "by": m, "why": x.extra.get("stood_in_why", "")}
            for m, x in reads if x.extra.get("stood_in_for")]
    if len(reads) == 1 and not subs:
        return reads[0][1]
    by = lambda m, x: f"{m} for {x.extra['stood_in_for']}" if x.extra.get("stood_in_for") else m  # noqa: E731
    tag = lambda attr: [f"{r} (read by {by(m, x)})" for m, x in reads for r in getattr(x, attr)]  # noqa: E731
    unresolved = sorted({u for _, x in reads for u in x.unresolved})
    first = reads[0][1]
    v = T.Verdict(verdict=T.HANDBACK_VERDICT if any(x.verdict == T.HANDBACK_VERDICT for _, x in reads) else T.LAND,
                  digest=first.digest, blocking=tag("blocking"), advisory=tag("advisory"),
                  model="+".join(m for m, _ in reads), tokens=sum(x.tokens for _, x in reads),
                  resolved=[r for r in first.resolved if r not in unresolved], unresolved=unresolved)
    v.extra["readers"] = [dict({"model": m, "verdict": x.verdict},
                               **({"stood_in_for": x.extra["stood_in_for"]} if x.extra.get("stood_in_for") else {}))
                          for m, x in reads]
    if subs:
        v.extra["stood_in"] = subs
    return v


def partial(digest, template):
    """Where the readers that answered wait while another is silent: {model: verdict}, one file per digest and
    prompt, so a retry does not buy their read again. It goes when the read is complete. It lives under the passwd
    home, never C.state(): $CC_LAND_STATE is the caller's, and a worker that queues with it pointing at its own dir
    could plant a LAND for every reader there and have no read bought (security read of #847)."""
    return os.path.join(C.PASSWD_HOME, ".cc", "state", "land", "reviews",
                        f"{digest}.{os.path.splitext(template)[0]}.partial.json")


def _held(job, why, **extra):
    """A read the host could not make twice: INCOMPLETE with extra host=True, which the lane sends to the planning seat
    with `why` and asks nothing of the PR's author. Never a HANDBACK: no finding is in it."""
    return T.Verdict(verdict=T.INCOMPLETE, digest=job.digest, extra=dict(extra, why=why, host=True))


def _silent(job, j, model, why):
    """A reader answered nothing. "A review read that fails for a reason of the host's, such as an HTTP 403, a timeout
    or the reader's per-read budget cap, never becomes a handback. It's retried once after a backoff. If it fails
    again, the PR is held with that reason recorded and no fix asked of the author" (owner, 10-12). So the first fault,
    wall or silence at a head is INCOMPLETE (refunded, held till limit_until(), asked again), and the second at that
    head is _held(), which clears the mark so a re-queue starts again at the first try. A usage limit is INCOMPLETE
    every time: it names its own reset. extra["silent"] tells the lane a fault or no answer from a wall or a limit."""
    repo, pr, head = job.repo, job.pr, job.head
    if why.startswith("wall"):
        if (j.get("wall") or {}).get("head") == head:
            charge(repo, pr, wall=None)   # a re-queue by the planning seat gets its own retry after the backoff
            return _held(job, f"the read hit its own cap twice at {head[:12]} ({model}: {why})", cap=True,
                         reader=model)
        charge(repo, pr, wall={"head": head, "why": why, "at": C.now()})
    elif not why.startswith("limit"):   # a fault (an HTTP 4xx, a missing binary) or no answer (a timeout)
        was = j.get("silent") or {}
        if (was.get("head"), was.get("reader")) == (head, model):
            charge(repo, pr, silent=None)
            said = "cannot run" if why.startswith("fault") else "answered nothing"
            return _held(job, f"review reader {model} {said} twice at {head[:12]}: {why}",
                         fault=why.startswith("fault"), reader=model)
        charge(repo, pr, silent={"head": head, "reader": model, "why": why, "at": C.now()})
    return T.Verdict(verdict=T.INCOMPLETE, digest=job.digest,
                     extra={"why": f"{model}: {why}", "until": limit_until(why), "reader": model,
                            "silent": not why.startswith(("wall", "limit"))})


def read_text(job, template, diff, more):
    """The prompt `template` filled for this job: the PR's header, the diff, the merged files, the brief, the base's
    rules, the PR body's Tested section and its whole title and body (the module doc), plus the slots in `more`."""
    root = root_of(job)
    got = pr_view(root, job.pr, "title,body")
    facts = got or {}
    # the union: job.files is the lane's list, which a job queued by an older lane may have made in the checkout's
    # own git; files_of() runs blind and sees every path
    blind_files = files_of(root, job.base_sha, job.head)
    files = list(dict.fromkeys([*job.files, *blind_files]))
    dropped = cut_paths(diff, blind_files) if len(diff) > DIFF_CAP else []
    return prompt(load_prompt(template), PR=job.pr, REPO=job.repo, TITLE=facts.get("title") or "(untitled)",
                  DIFF=capped(diff, dropped),
                  FILES=merged_files(root, job.base_sha, job.head, files, dropped, whole_paths(diff, blind_files)),
                  BRIEF=brief_of(job) or
                  "No brief was found for this PR. Judge the change against its title and its own diff.",
                  RULES=rules_of(root, job.base_sha) or "This repo ships no docs/REVIEW.md.",
                  TESTED=tested_of(facts.get("body")) or "The PR body has no Tested section.",
                  BODY=body_of(got if isinstance(got, dict) else None), **more)


def _buy(job, template, diff, more, prior=None):
    repo, pr = job.repo, job.pr
    lim_rc, lim = C.sh([os.path.join(BIN, "cc-limit"), "status"], timeout=60)
    if lim_rc == 0:
        return T.Verdict(verdict=T.INCOMPLETE, digest=job.digest,
                         extra={"why": f"usage limit: {lim.strip()}", "until": limit_until(lim)})
    j = spent(repo, pr)
    if effort() not in EFFORTS:
        return _held(job, f"the review cannot run: CC_LAND_REVIEW_EFFORT={effort()!r} is not one of "
                          f"{', '.join(EFFORTS)}", fault=True)
    root = root_of(job)
    text = read_text(job, template, diff, more)
    kept = C.read_json(partial(job.digest, template), {}) or {}
    reads, usd = [], 0.0
    for model in readers():
        if isinstance(kept.get(model), dict):
            was = T.Verdict.from_dict(kept[model])
            reads.append((was.model if was.extra.get("stood_in_for") else model, was))
            continue
        v, cost, why = ask(text, repo, pr, job.digest, model)
        if cost:
            charge(repo, pr, review_usd=cost)
            usd += cost
            over_ceiling(repo, pr)
        sub = stand_in(job, model, why) if v is None else ""
        if sub:
            C.log("stand-in", repo, pr, reader=model, by=sub, why=why[:120])
            v, cost, sub_why = ask(text, repo, pr, job.digest, sub)
            if cost:
                charge(repo, pr, review_usd=cost)
                usd += cost
                over_ceiling(repo, pr)
            if v is None:
                return _silent(job, j, sub, sub_why)
            v.extra.update(stood_in_for=model, stood_in_why=why[:300])
        if v is None:
            return _silent(job, j, model, why)
        v = carried(pinned(v, prior) if prior else v, prior)   # a first read's stray `unresolved` holds it too
        reads.append((sub or model, v))
        kept[model] = v.to_dict()
        C.write_json(partial(job.digest, template), kept)
    v = combined(reads)
    charge(repo, pr, reviews=1, silent=None)
    with contextlib.suppress(OSError):
        os.unlink(partial(job.digest, template))
    v.extra["head"] = job.head
    posted = post(root, pr, marker(v, job.base_sha, job.head, v.model))
    C.write_json(C.state("reviews", f"{job.digest}.json"), dict(v.to_dict(), repo=repo, pr=pr, posted=posted))
    C.log("stage", repo, pr, verdict=v.verdict, digest=job.digest[:12], usd=f"{usd:.2f}")
    if v.verdict == T.HANDBACK_VERDICT:   # a seat's LAND recorded at this head while the read ran stands (recorded())
        now = (pr_view(root, pr) or {}).get("comments") or []
        land = recorded(now, keys(job, diff), job.head)
        if land and land.verdict == T.LAND:
            # the same check every other path runs first: a security HANDBACK posted while the read ran outranks it
            return _security_stands(job, now) or land
    return v


def saved(digest):
    """The verdict review() bought at `digest`, from this box's copy (board.followup reads it after the merge)."""
    d = C.read_json(C.state("reviews", f"{digest}.json")) if digest else None
    return T.Verdict.from_dict(d) if d else None


# --- commands ------------------------------------------------------------------------------------------------------

OLD_WORDS = {"LAND": T.LAND, "HANDBACK": T.HANDBACK_VERDICT, "LAND-AFTER-FIX": T.HANDBACK_VERDICT,
             "DO-NOT-LAND": T.HANDBACK_VERDICT}
REPO_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")


def _job_of(repo, pr):
    """A Job for a PR as GitHub has it now: head, base, digest. -> (job, facts) or (None, why)."""
    job = T.Job(repo=repo, pr=pr)
    root = root_of(job)
    facts, why = GH.pr_facts(root, pr, "headRefOid,baseRefName,comments,state,files,headRefName")
    if not facts:   # gh.pr_facts' own why: a spent quota names its reset (lander record hid it, 2026-10-22)
        return None, f"cannot read PR #{pr} of {repo} from GitHub: {why}"
    base = facts.get("baseRefName") or "main"
    from lander import deploy as D
    from lander import git as G
    with D.git_lock(root):   # base from the lander's own URL, checked against ls-remote; never the checkout's origin
        job.base_sha = D.verified_tip(root, base)
        if G.remote_url(root):
            with contextlib.suppress(G.GitError):   # borrowed: no config or hook of the checkout's runs or steers it
                G.fetch_ids(root, f"refs/pull/{pr}/head")
    job.extra.update(base=base, head_ref=facts.get("headRefName") or "")
    job.files = [f.get("path", "") for f in facts.get("files") or []]
    job.head = facts.get("headRefOid") or ""
    job.digest = digest_of(root, job.base_sha, job.head)
    return job, facts


def extra_versions_root(path=None, owner=None):
    """The versions root named on the first line of `path` (CLAUDE_VERSIONS_FILE unless a test passes one), or None.
    Perms, 10-13: accept it "only if that file is owned by root and not group- or world-writable" — a file a seat
    could write, or a symlink to one, names no root. A missing or unreadable file, or a relative path, is None."""
    try:
        fd = os.open(path or CLAUDE_VERSIONS_FILE, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if st.st_uid != (ROOT_UID if owner is None else owner) or st.st_mode & 0o022:
            return None
        line = os.read(fd, 4096).decode("utf-8", "replace").strip().split("\n")[0].strip()
    except OSError:
        return None
    finally:
        os.close(fd)
    return line if os.path.isabs(line) else None


def is_claude_session(pid, proc="/proc", versions=None):
    """True when pid is a real Claude session: its comm is `claude` AND its /proc/<pid>/exe is under a versions root
    (CLAUDE_VERSIONS and extra_versions_root(), unless a test passes one). Perms, 10-13: any same-uid process can
    rewrite its own comm, so "accept a process as the perms seat only when /proc/<pid>/exe resolves under
    ~/.local/share/claude/versions/ AND its comm is claude". A binary an update deleted reads "<path> (deleted)",
    still under versions. The exe is compared as the kernel printed it, never realpath'd: "realpath resolves the path
    a second time through a filesystem the caller controls (a deleted folder replaced by a symlink to versions/
    passes)"."""
    with open(os.path.join(proc, str(pid), "comm")) as f:
        if f.read().strip() != "claude":
            return False
    exe = os.readlink(os.path.join(proc, str(pid), "exe"))
    if exe.endswith(" (deleted)"):
        exe = exe[:-len(" (deleted)")]
    exe = os.path.normpath(exe)   # a string operation: it reads no filesystem
    roots = [versions] if versions else [CLAUDE_VERSIONS, extra_versions_root()]
    return any(exe.startswith(r + os.sep) for v in roots if v for r in {os.path.normpath(v), os.path.realpath(v)})


def claude_ancestor(pid=None, proc="/proc", versions=None):
    """The pid of the first Claude session (is_claude_session()) at or above `pid` (default: this one's parent), walking
    /proc/<pid>/status PPid, or None when the walk reaches pid 1 or a process it cannot read. A process that only
    calls itself `claude` is walked past, like any other."""
    pid, seen = pid or os.getppid(), set()
    while pid and pid > 1 and pid not in seen:
        seen.add(pid)
        try:
            if is_claude_session(pid, proc, versions):
                return pid
            with open(os.path.join(proc, str(pid), "status")) as f:
                pid = next((int(ln.split()[1]) for ln in f if ln.startswith("PPid:")), 0)
        except (OSError, ValueError, IndexError):
            return None
    return None


def perms_seat_caller(repo, pid=None, proc="/proc", state=None, versions=None):
    """True when the Claude session that called (claude_ancestor()) runs in the perms seat: its /proc/<pid>/cwd
    resolves to <state>/<repo>/perms, state being PERMS_STATE at the passwd home unless a test passes one. Perms,
    10-13: "lander record refuses --by perms-* unless the calling Claude ancestor ... has /proc/<pid>/cwd realpath ==
    ~/.cc/state/<repo>/perms". Never $CC_STATE or $HOME, which a caller sets: a seat that set CC_STATE could start a
    claude in a <CC_STATE>/<repo>/perms of its own and write perms' name."""
    seat = claude_ancestor(pid, proc, versions)
    if seat is None:
        return False
    state = state or PERMS_STATE
    try:
        cwd = os.path.realpath(os.readlink(os.path.join(proc, str(seat), "cwd")))
    except OSError:
        return False
    return cwd == os.path.realpath(os.path.join(state, repo.rsplit("/", 1)[-1], "perms"))


def cmd_record(argv):
    """record <repo> <pr> <VERDICT> --by <who> [--head <sha>] [--findings <text>|-]. A --by of `perms` or starting
    `perms-` (perms-security-read among them) is refused unless perms_seat_caller(): only the perms seat writes
    perms' name. No marker clears a security path; perms' ledger does (perms_recorded), and a LAND recorded from the
    perms seat with --head at the PR's head in full goes there too, as does any other verdict from that seat
    (_perms_ledger)."""
    args, opts = [], {}
    it = iter(argv)
    for a in it:
        if a in ("--by", "--head", "--findings"):
            opts[a[2:]] = next(it, "")
        else:
            args.append(a)
    if len(args) != 3 or not REPO_RE.match(args[0]) or not args[1].isdigit() or args[2] not in OLD_WORDS:
        print("usage: lander record <repo> <pr> LAND|HANDBACK --by <who> [--head <sha>] [--findings TEXT|-]")
        return 2
    if not opts.get("by"):
        print("lander record: --by names who read it; a verdict with no reader is refused")
        return 2
    # perms, 10-13: "lander record refuses --by perms-* unless the calling Claude ancestor" runs in the perms seat;
    # a bare `perms` is its name too (#1523 was recorded --by perms)
    seat = perms_seat_caller(args[0])
    named = re.sub(r"[^A-Za-z0-9._@-]+", "-", opts["by"]).lower()
    if (named == "perms" or named.startswith("perms-")) and not seat:
        print(f"lander record: --by {opts['by']} is perms' name, and this was not run from the perms seat; "
              "nothing posted. Perms records its own read from its seat, which also puts it in perms' ledger.")
        return 1
    head = (opts.get("head") or "").lower()
    if head and not re.fullmatch(r"[0-9a-f]{7,40}", head):
        print(f"lander record: --head {head!r} is not a commit")
        return 2
    repo, pr, word = args[0], int(args[1]), OLD_WORDS[args[2]]
    job, facts = _job_of(repo, pr)
    if job is None:
        print(f"lander record: {facts}")
        return 1
    if facts.get("state") == "MERGED":
        print(f"lander record: PR #{pr} is merged; there is nothing to record a verdict for")
        return 1
    # brief: "Make lander record REFUSE (non-zero exit, nothing posted) when it can't compute the change digest or
    # the base" — a marker with an empty change= is one lander-self's MARK_RE skips, so it is no read at all
    missing = [n for n, x in (("head", job.head), ("base", job.base_sha), ("change digest", job.digest)) if not x]
    if missing:
        print(f"lander record: cannot work out the {' or the '.join(missing)} of PR #{pr} right now, so a marker "
              "would name no change; nothing posted. Run it again.")
        return 1
    if head and not job.head.startswith(head):
        print(f"lander record: PR #{pr} is at {job.head[:12]} now, not {head[:12]} — the branch moved after that "
              "read, so it did not read this head. Read it again.")
        return 1
    findings = sys.stdin.read() if opts.get("findings") == "-" else (opts.get("findings") or "")
    stands = recorded(facts.get("comments") or [], {job.digest}, job.head)
    who = re.sub(r"[^A-Za-z0-9._@-]+", "-", opts["by"])
    # a second reader's LAND is posted too: lander-self needs an Opus read and a security read at one head
    if stands and stands.verdict == word and (word != T.LAND or stands.model == who):
        print(f"lander record: {word} is already recorded for this change; nothing posted")
        return _perms_ledger(job, facts, seat, args[2], who, head)
    if stands and stands.verdict == T.HANDBACK_VERDICT and word == T.LAND:
        print(f"lander record: HANDBACK stands for this change and LAND is looser; push the fix instead")
        return 1
    rows = [ln.strip() for ln in findings.splitlines() if ln.strip()]
    v = T.Verdict(verdict=word, digest=job.digest, blocking=rows if word != T.LAND else [],
                  advisory=rows if word == T.LAND else [], model=opts["by"])
    if not post(root_of(job), pr, marker(v, job.base_sha, job.head, opts["by"])):
        print(f"lander record: the record did not reach PR #{pr}")
        return 1
    C.log("recorded", repo, pr, verdict=word, by=re.sub(r"[^A-Za-z0-9._@-]+", "-", opts["by"]),
          head=job.head[:12], change=job.digest[:12] or "-")
    print(f"lander record: {word} recorded on PR #{pr} at {job.head[:12]}")
    return _perms_ledger(job, facts, seat, args[2], who, head)


def _perms_ledger(job, facts, seat, said, who, head):
    """The perms seat's verdict through `record` is its security read, so it goes in perms' ledger in the same step
    (#1523: a LAND marker by perms, and no ledger entry, was refused INCOMPLETE twice). `said` is the word perms
    passed (OLD_WORDS' key), and the entry keeps it. A HANDBACK, LAND-AFTER-FIX or DO-NOT-LAND is appended as a
    non-LAND entry, so newest_reads sees a LAND that perms later handed back at the same head as handed back
    (perms' follow-up to its LAND on #1584: with no entry, the older LAND stood). Any other caller writes nothing
    there. The entry is for job.head, the PR's head now, so a LAND is written only when --head names that head in
    full: with no --head, perms' read of an earlier head would stand in the ledger for one it never read. A non-LAND
    needs no full --head: it only holds, the marker it goes with is posted at job.head too, and carried_from() lets
    no LAND older than it carry, whichever head perms read. The entry
    says `read: perms` only for perms' own name, but perms_recorded ignores `read`, so a LAND recorded from the
    perms seat under any --by also counts as the security read: whoever reads from that seat is within perms'
    trust. -> the exit code."""
    if not seat:
        return 0
    land = OLD_WORDS[said] == T.LAND
    if land and not (SHA40.fullmatch(head) and head == job.head):
        print(f"lander record: perms' ledger was not written: pass --head with the full 40-hex sha of the head "
              f"you read (PR #{job.pr} is at {job.head}), and run this record again")
        return 1
    named = who.lower()
    why = grant(job, "perms" if named == "perms" or named.startswith("perms-") else who, who,
                T.LAND if land else said)
    if why:
        print(f"lander record: the marker is on the PR, but perms' ledger {perms_reads_path(job.repo)} was not "
              f"written ({why}), so " + ("a security path will not merge on it" if land else
                                         "an earlier LAND of this head may still stand there")
              + ". Put that right and run this record again.")
        return 1
    C.log("perms-recorded", job.repo, job.pr, head=job.head[:12], change=job.digest[:12], verdict=said)
    print(f"lander record: perms' {said} of PR #{job.pr} at {job.head[:12]} is in its ledger")
    if land:
        requeue_held(job, facts)
    return 0


def would_read(job, comments):
    """-> (bool, why): whether review() would buy a read for this job now; it matches the same keys() review() does.
    A standing security HANDBACK comes first, as in review(): the landing buys no read that can clear it, so the
    security reader is told to buy its own (perms, PR #1174: "do not buy a read" blocked the one read that clears it)."""
    sec = _security_open(job, comments)
    if sec:
        was = sec.extra.get("head", "")[:12] or "an earlier head"
        return False, (f"a security HANDBACK by {sec.model} stands from {was}, and no read the landing buys can clear "
                       "it — a security reader buys its own read and records it (`lander record ... --by "
                       f"{PERMS_SECURITY_READER}` from the perms seat)")
    digests = keys(job, diff_of(root_of(job), job.base_sha, job.head))
    need = _security_unread(job, comments, digests)
    if need:
        return False, (need.extra["why"] + " — perms reads it and records that; the landing buys none")
    if recorded(comments, digests, job.head):
        return False, "a verdict is already recorded for this change, and the landing reads that"
    if _perms_land(job, digests):
        return False, "perms recorded its security read of this change, and the landing lands on that"
    if not (job.plan and job.plan.paid) and not standing(job, comments):
        return False, "it touches no paid-review path and no unchecked code, so nothing reads it"
    return True, "the landing reads it — do not buy a read of your own"


def cmd_will_review(argv):
    if len(argv) != 2 or not REPO_RE.match(argv[0]) or not argv[1].isdigit():
        print("usage: lander will-review <repo> <pr>")
        return 2
    job, facts = _job_of(argv[0], int(argv[1]))
    if job is None:
        print(f"lander will-review: {facts}")
        return 1
    try:
        from lander import plan as P   # U2's; without it the policy cannot be read, so say the lander reads it
        from lander import manifest as MF   # the lane plans with the release's fallback; so does this
        job.plan = P.plan(root_of(job), job.base_sha, job.head, job.files, fallback=MF.host_fallback(job.repo))
    except Exception:  # noqa: BLE001
        job.plan = T.Plan(paid=True)
    yes, why = would_read(job, facts.get("comments") or [])
    print(f"[{job.repo}] PR #{job.pr} at {job.head[:12]}: the landing {'WILL' if yes else 'will NOT'} read it — {why}")
    return 0 if yes else 1


# --- perms' own reads, which outlive the perms window -----------------------------------------------------------------
#
# A security read perms starts was a subagent of the perms window: a hand-off ended it and the successor ran it again
# (one delta read ran three times on 10-15). `perms-read` runs it the way the lander runs its own (read_text() on
# config/lander/security.md, one tool-less ask() by readers()[0]) in a process of its own session, so closing the
# window does not end it, and leaves the verdict where the successor finds it (`perms-reads`):
#     <passwd home>/.cc/state/<repo>/perms/reads/<pr>-<head>.json
# A second `perms-read` of a head that is running or done starts nothing. Perms' three requirements (TestPermsReads):
#   1. The file lives only in perms' own seat directory, which cc-guard lets no other session write and a member's
#      sandbox never binds (it binds ~/.cc/state/<handle>, and a handle is never a repo's name). read_dir() refuses
#      the reads dir or the seat dir above it reached through a symlink, not this user's, or open to others' writes
#      (the reads dir to any other access), and own_json() a file that is not this user's plain 0600 one.
#   2. The file names the repo, the PR and the 40-hex head it read, in its body and in its name; write_read() writes
#      no other, and load_read() refuses one whose body and name disagree.
#   3. A read becomes a grant only through `perms-adopt`, run by the perms seat: it finds the file by the PR's LIVE
#      head (GitHub's, _job_of) and appends perms' ledger entry (perms_recorded) only when that file read exactly
#      that head at the change digest the PR has now, finished, by one of readers(), and says LAND (adoptable()). A
#      stale file names another head and is never the one found; any file must still match the live head and change.
#   A running read is alive only while its pid is still the process it started (alive(): the start time matches),
#   and whatever `perms-reads` prints from a file is quoted, control characters spelled out (quoted()).
# `perms-read --since <old>` reads only delta_text() from a head whose ledger LAND still carries (land_heads(), so
# never past a FIX) onto a head that merges clean (merges_clean()); the stub, the read and the ledger entry adopt
# writes all carry `since`, and adopt checks that LAND again (perms' answer of 10-22).
# The lane waits on these files (perms_reading, asked by lane.mergeable just before the merge). It holds (box) while a
# read of the PR runs at any head, or for a read's run window (HOLD_WINDOW) while perms' `perms-hold` stub stands at
# its head, so perms can claim a PR before its read starts. Anything else short of a finished LAND at the head (or an older head's at the same change, or a
# HANDBACK at the head that perms' ledger LAND at it was recorded after) is a query for the planning seat, which is where a read that died with no verdict surfaces.

PERMS_READ_DIR = "reads"
SHA40 = re.compile(r"[0-9a-f]{40}")
CLI = os.path.join(os.path.dirname(os.path.realpath(__file__)), "cli.py")
RUN_WAIT = 10   # seconds the detached read waits for the stub that names it
HOLD_WINDOW = RUN_WAIT + READ_TIMEOUT   # seconds a perms-hold stub holds before it is a query (a read's run window)


def read_dir(repo, make=False):
    """-> (path, why): perms' reads dir for `repo` (requirement 1 above), made 0700 when `make` and the seat dir is
    there (never the seat dir itself, which is perms'), or (None, why it does not count)."""
    # brief: "the verdict file lives only in a directory a member's sandbox can't write"
    seat = os.path.dirname(perms_reads_path(repo))
    path = os.path.join(seat, PERMS_READ_DIR)
    if make and os.path.isdir(seat) and not os.path.lexists(path):
        with contextlib.suppress(FileExistsError):
            os.mkdir(path, 0o700)
    for p, loose in ((seat, 0o022), (path, 0o077)):
        if os.path.realpath(p) != os.path.abspath(p):
            return None, f"{p} resolves through a symlink"
        try:
            st = os.lstat(p)
        except OSError as e:
            return None, f"{p} will not open: {e.strerror}"
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & loose:
            return None, f"{p} is not this user's own directory with mode {0o777 & ~loose:o} or stricter"
    return path, ""


def read_name(pr, head):
    return f"{int(pr)}-{head}.json"


def write_read(repo, entry):
    """Write one read file (requirement 2), whole or not at all, mode 0600. -> (path, why)."""
    # brief: "each file names the repo, the PR and the exact head sha it read"
    if not (entry.get("repo") == repo and isinstance(entry.get("pr"), int)
            and SHA40.fullmatch(str(entry.get("head") or ""))):
        return None, "a read file names its repo, its PR and the 40-hex head it read"
    d, why = read_dir(repo, make=True)
    if not d:
        return None, why
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".", suffix=".tmp")   # 0600
    with os.fdopen(fd, "w") as f:
        json.dump(entry, f, indent=1, sort_keys=True)
    path = os.path.join(d, read_name(entry["pr"], entry["head"]))
    os.replace(tmp, path)
    return path, ""


def load_read(repo, pr, head):
    """-> (entry, why): the read file of exactly this repo, PR and head, or (None, why none counts)."""
    if not SHA40.fullmatch(head or ""):
        return None, f"{head!r} is not a 40-hex head"
    d, why = read_dir(repo)
    if not d:
        return None, why
    path = os.path.join(d, read_name(pr, head))
    e, why = own_json(path)
    if why:
        return None, why
    if not isinstance(e, dict) or (e.get("repo"), e.get("pr"), e.get("head")) != (repo, int(pr), head):
        return None, f"{path} does not name {repo} PR #{pr} at {head} in its body"
    return e, ""


def read_files(repo, pr=None):
    """-> [(pr, head)]: the read files in perms' reads dir, of PR `pr` when given, newest first. A dir that will not
    list raises OSError."""
    d, _ = read_dir(repo)
    found = []
    for n in os.listdir(d) if d else []:
        m = re.fullmatch(r"(\d+)-([0-9a-f]{40})\.json", n)
        if m and (pr is None or int(m[1]) == int(pr)):
            with contextlib.suppress(OSError):
                found.append((os.lstat(os.path.join(d, n)).st_mtime, int(m[1]), m[2]))
    return [(p, h) for _, p, h in sorted(found, reverse=True)]


def started_at(pid, proc="/proc"):
    """-> the start time of process `pid` (field 22 of /proc/<pid>/stat, clock ticks since boot) as a string, or None
    when there is no such live process. A pid and its start time name one process: a reused pid starts later."""
    try:
        with open(os.path.join(proc, str(int(pid)), "stat")) as f:
            fields = f.read().rpartition(")")[2].split()
    except (OSError, TypeError, ValueError):
        return None
    return fields[19] if len(fields) > 19 and fields[0] not in ("Z", "X") else None


def alive(e, proc="/proc"):
    """True when the process stub `e` names is still the one it started: its pid runs and started when the stub says.
    A pid alone is not enough, since a dead read's pid may be another process's by now; a stub with no start time
    (one written before this check) counts as dead, so the worst it costs is a second read."""
    when = started_at(e.get("pid"), proc)
    return when is not None and when == str(e.get("pid_start") or "")


def quoted(v):
    """Text from a read file, which a reader's answer steers, made safe to print to perms' terminal: in double quotes,
    with every control or format character (escape sequences, a carriage return, bidi overrides) spelled out."""
    out = []
    for ch in str(v):
        if ch in '"\\':
            out.append("\\" + ch)
        elif unicodedata.category(ch)[0] in "CZ" and ch != " ":
            out.append(f"\\x{ord(ch):02x}" if ord(ch) < 0x100 else f"\\u{ord(ch):04x}" if ord(ch) < 0x10000
                       else f"\\U{ord(ch):08x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def reads_absent(repo) -> bool:
    """True when perms has no reads dir for `repo` at all (it never read one of its PRs): the seat dir is no symlink
    and lstat of the reads dir's name says it is not there. Any other answer (EACCES, ELOOP, something there that
    read_dir() refuses) is not absent, so the lane fails closed on it."""
    seat = os.path.dirname(perms_reads_path(repo))
    if os.path.realpath(seat) != os.path.abspath(seat):
        return False
    try:
        os.lstat(os.path.join(seat, PERMS_READ_DIR))
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def held_since(e):
    """-> seconds since a perms-hold stub's `started`, or None when it carries no readable stamp."""
    try:
        at = datetime.datetime.strptime(str(e.get("started")), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return (datetime.datetime.now(datetime.timezone.utc) - at.replace(tzinfo=datetime.timezone.utc)).total_seconds()


def perms_reading(repo, pr, head, digest="", carried="") -> tuple:
    """-> (why, wait): why the lane must not merge PR `pr` at `head` on account of perms' own reads, or ("", False).
    dispatch#1296 merged on the lane's own read while perms' read of it ran (10-19), and #1298 had to go to draft by
    hand to wait for one. `wait` is True only when time mends it: a read of the PR at any head still running (its
    process alive), or a `perms-hold` stub at its head no older than a read's run window (HOLD_WINDOW), which perms
    starts its read from; an older stub (perms died or handed off before its read began) is a query like a dead read. Everything else that holds is
    perms' to act on, and the lane makes it a query (perms' read of #1525, 10-19: each of these let a merge through):
    a finished read at `head` that is not a LAND; one at `head` that failed, went stale or died with no verdict; reads
    of older heads and none at `head` (a push after perms' HANDBACK); a read file that will not load; a reads dir that
    is there but will not read. With none at `head`, the newest read's LAND at the same change counts as one (a rebase),
    and so does one at `carried`, the head same_change() found (or a call that finds it, run only here: it runs git).
    A HANDBACK at `head` is cleared by perms' ledger LAND at `head` and its change (perms_recorded) recorded a later
    second than the read finished; a time either side does not give clears nothing (#1842)."""
    d, why = read_dir(repo)
    if not d:
        return ("", False) if reads_absent(repo) else (f"perms' reads dir will not read ({why})", False)
    try:
        files = read_files(repo, pr)
    except OSError as x:
        return f"perms' reads dir will not list ({x.strerror or x})", False
    at, old = None, []
    for _, h in files:
        e, why = load_read(repo, pr, h)
        if not e:
            return f"perms' read file of PR #{pr} at {h[:12]} will not load ({why})", False
        if e.get("state") == "running" and alive(e):
            return f"perms' security read of PR #{pr} at {h[:12]} is still running", True
        if h == head:
            at = e
        else:
            old.append((h, e))
    if at is None:
        if not old:
            return "", False
        h, e = old[0]   # the newest: a HANDBACK after an older LAND at this change still stands
        if e.get("state") == "done" and e.get("verdict") == T.LAND and (digest and e.get("change") == digest
                                                                       or carried and h == (carried() if callable(carried) else carried)):
            return "", False
        since = f" --since {h}" if e.get("state") == "done" and e.get("verdict") == T.LAND else ""
        return (f"perms read PR #{pr} at {h[:12]} ({e.get('verdict') or e.get('state') or 'no verdict'}) and has no "
                f"read of its head {head[:12]}: perms runs `lander perms-read {repo} {pr}{since}`, then queue it "
                f"again"), False
    state = at.get("state")
    if state == "done" and at.get("verdict") == T.LAND:
        return "", False
    if state == "held":
        age = held_since(at)
        if age is not None and 0 <= age <= HOLD_WINDOW:
            return f"perms holds PR #{pr} at {head[:12]} for its security read", True
        return (f"perms held PR #{pr} at {head[:12]} for its security read and none started within "
                f"{HOLD_WINDOW // 60} minutes: perms runs `lander perms-read {repo} {pr}`, then queue it again"), False
    land = state == "done" and at.get("verdict") == T.HANDBACK_VERDICT and perms_recorded(repo, pr, head, [digest])
    if land:
        from lander import events as E
        land = E.epoch_of(land.get("at"))   # the entry whose verdict was checked: one read of the ledger
        back = E.epoch_of(at.get("finished"))
        # brief (#1842): "a security-reads LAND at the same head, recorded at a later second than the reader file's
        # finish time, clear[s] that reader file's HANDBACK"; "An unparseable time clears nothing."
        if back and land and back < land:
            return "", False
    if state == "done":
        return f"perms' security read of PR #{pr} at {head[:12]} says {at.get('verdict') or 'nothing'}", False
    said = "died with no verdict" if state == "running" else f"is {state or 'unfinished'}"
    return (f"perms' security read of PR #{pr} at {head[:12]} {said}" + (f" ({quoted(at['why'])})" if at.get("why") else "")
            + f": perms runs `lander perms-read {repo} {pr}` again, then queue it again"), False


def adoptable(job):
    """-> (entry, why): perms' finished LAND read of the PR's live head at its live change, by one of readers()
    (requirement 3), or (None, why not). `job` is _job_of()'s, from GitHub; nothing in the file says which head is
    live."""
    # brief: "the successor checks that sha against the PR's live head before it grants a merge, so a stale or
    # planted file can't carry a merge on its own"
    if not (SHA40.fullmatch(job.head or "") and job.digest):
        return None, f"cannot work out PR #{job.pr}'s head and change right now"
    at = job.head[:12]
    e, why = load_read(job.repo, job.pr, job.head)
    if e is None:
        olds = [h[:12] for _, h in read_files(job.repo, job.pr) if h != job.head]
        return None, (f"no read of PR #{job.pr} at its head {at} counts ({why})"
                      + (f"; the reads on file are of {', '.join(olds)}, which it has moved off" if olds else ""))
    if e.get("change") != job.digest:
        return None, (f"the read at {at} was of change {str(e.get('change'))[:12]}, and the PR's change is "
                      f"{job.digest[:12]} now; read it again")
    if e.get("state") != "done":
        return None, f"the read at {at} is {e.get('state') or 'unfinished'}, not done"
    if e.get("verdict") != T.LAND:
        return None, f"the read at {at} says {quoted(e.get('verdict'))}"
    if e.get("model") not in readers():
        return None, (f"the read at {at} was by {quoted(e.get('model'))}, which is not one of the readers "
                      f"({', '.join(readers())})")
    if e.get("since") and e["since"] not in land_heads(job):
        return None, (f"the read at {at} read only the change since {str(e['since'])[:12]}, and perms' LAND there no "
                      f"longer carries; read it whole")
    return e, ""


def grant(job, read, model, verdict=T.LAND, since="", refresh=True):
    """Append perms' ledger entry (perms_recorded's form) for perms' `verdict` (LAND, or a word that holds) of the
    job's head, `read` naming the read it rests on, whole or not at all: a 0600 file swapped in by rename, in a seat
    dir reached through no symlink. When that head's newest entry already says `verdict` at the job's change, only
    its `at` moves to now, unless not `refresh` (perms-adopt: re-adopting an old read must not clear a HANDBACK
    posted after it). Callers check perms_seat_caller() first. -> why not, or ''."""
    path = perms_reads_path(job.repo)
    seat = os.path.dirname(path)
    if not (SHA40.fullmatch(job.head or "") and job.digest):
        return f"PR #{job.pr}'s head or change cannot be worked out right now"
    if not os.path.isdir(seat) or os.path.realpath(seat) != os.path.abspath(seat):
        return f"perms' seat dir {seat} is missing or reached through a symlink"
    tmp = None
    try:
        # one writer at a time: two grants that each read the old list would drop one entry
        lock = os.open(os.path.join(seat, PERMS_READS_LOCK), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock, "w"):
            fcntl.flock(lock, fcntl.LOCK_EX)
            have, why = perms_reads(job.repo)
            if why and os.path.lexists(path):
                return f"perms' ledger will not read ({why}); nothing written over it"
            last = newest_reads(have, job.repo, job.pr).get(job.head) or {}
            if last.get("change") == job.digest and last.get("verdict", T.LAND) == verdict:
                # already the newest: its time moves, so a repeat LAND clears a reader's newer HANDBACK (perms_reading)
                if not refresh:
                    return ""
                last["at"] = C.now()
                last.pop("since", None)
                last.update({"since": since} if since else {})
            else:   # a LAND after a FIX at this head is appended, so it stands
                have.append({"repo": job.repo, "pr": job.pr, "head": job.head, "change": job.digest,
                             "verdict": verdict, "read": read, "model": model, "at": C.now(),
                             **({"since": since} if since else {})})
            fd, tmp = tempfile.mkstemp(dir=seat, prefix=".", suffix=".tmp")   # 0600
            with os.fdopen(fd, "w") as f:
                json.dump(have, f, indent=1)
            os.replace(tmp, path)
            tmp = None
    except OSError as e:
        return f"perms' ledger could not be written ({e.strerror or e})"
    finally:
        if tmp:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
    return ""


def requeue_held(job, facts):
    """Perms' LAND of the open PR's live head is in its ledger: a job that ended a query at that head on host_hold
    goes back in the lane, as the lander's queue command would put it (drain logs `requeued`). Any other job is left
    alone."""
    from lander import jobs as J
    from lander import lane as L
    held = J.load(job.repo, job.pr)
    if facts.get("state") == "OPEN" and held and held.state == T.QUERY and held.extra.get("host_hold") == job.head:
        J.submit(job.repo, job.pr, who="perms")
        L.spawn_tick(job.repo)


def _perms_run(repo, pr, head):
    """The detached half of perms-read: it runs only for the stub that names its own pid (written by the seat that
    started it), reads the PR at `head`, and writes the verdict into that file."""
    for _ in range(RUN_WAIT * 5):
        e, _ = load_read(repo, pr, head)
        if e and e.get("state") == "running" and e.get("pid") == os.getpid():
            break
        time.sleep(0.2)
    else:
        return 1

    def done(**kw):
        return 0 if write_read(repo, dict(e, finished=C.now(), **kw))[0] else 1
    model = readers()[0]
    if e.get("model") != model:   # the reader perms started it for, or none
        return done(state="failed", why=f"started for reader {e.get('model')!r}, and the reader now is {model!r}")
    try:
        job, facts = _job_of(repo, pr)
        if job is None:
            return done(state="failed", why=str(facts))
        if job.head != head:
            return done(state="stale", why=f"PR #{pr} moved to {job.head[:12]} before the read began")
        diff = diff_of(root_of(job), job.base_sha, job.head)
        if e.get("since"):
            rc, delta = delta_text(root_of(job), job.base_sha, e["since"], job.head)
            if rc:
                return done(state="failed", why=f"the delta since {e['since'][:12]} will not diff: {delta[:200]}")
            diff = (f"(perms' security read LANDed this PR at {e['since']}: below is only what changed since that "
                    f"head, which is all this read covers)\n" + delta)
        v, usd, why = ask(read_text(job, "security.md", diff, {}), repo, pr, job.digest, model)
    except Exception as x:  # noqa: BLE001 — any failure is written down, so the successor sees it and no one waits
        return done(state="failed", why=f"{type(x).__name__}: {x}")
    if v is None:
        return done(state="failed", model=model, usd=usd, why=why)
    return done(state="done", model=model, usd=usd, change=job.digest, verdict=v.verdict, blocking=v.blocking,
                advisory=v.advisory)


def cmd_perms_read(argv):
    """perms-read <repo> <pr> [--since <old head>]: start perms' security read of the PR's head apart from the perms
    window (the section above), or say why none starts. Perms seat only. With --since it reads only delta_text() from
    `old`, which must hold perms' LAND (land_heads()) and the head merge clean onto main (perms' answer of 10-22); its
    LAND, adopted, clears the head as a whole read would."""
    run = len(argv) == 4 and argv[2] == "--run"
    since = argv[3] if len(argv) == 4 and argv[2] == "--since" else ""
    if not (len(argv) == 2 or run or SHA40.fullmatch(since)) or not REPO_RE.match(argv[0]) or not argv[1].isdigit():
        print("usage: lander perms-read <repo> <pr> [--since <40-hex head perms LANDed>]")
        return 2
    repo, pr = argv[0], int(argv[1])
    if run:
        return _perms_run(repo, pr, argv[3])
    if not perms_seat_caller(repo):
        print("lander perms-read: only the perms seat starts its reads; nothing started")
        return 1
    job, facts = _job_of(repo, pr)
    if job is None:
        print(f"lander perms-read: {facts}")
        return 1
    if not (SHA40.fullmatch(job.head) and job.digest):
        print(f"lander perms-read: cannot work out PR #{pr}'s head and change right now; nothing started")
        return 1
    e, _ = load_read(repo, pr, job.head)
    if e and (e.get("state") == "done" or (e.get("state") == "running" and alive(e))):
        said = f" ({quoted(e.get('verdict'))})" if e.get("state") == "done" else ""
        print(f"lander perms-read: the read of PR #{pr} at {job.head[:12]} is {e['state']}{said}; nothing started")
        return 0
    if since and since not in land_heads(job):
        print(f"lander perms-read: perms' ledger holds no LAND at {since[:12]} that carries to {job.head[:12]}; "
              f"read it whole (no --since)")
        return 1
    if since and not merges_clean(root_of(job), job.base_sha, job.head):
        print(f"lander perms-read: PR #{pr} at {job.head[:12]} does not merge clean onto main; read it whole")
        return 1
    p = subprocess.Popen([sys.executable, "-P", CLI, "perms-read", repo, str(pr), "--run", job.head], cwd="/",
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    path, why = write_read(repo, {"repo": repo, "pr": pr, "head": job.head, "base": job.base_sha,
                                  "change": job.digest, "state": "running", "pid": p.pid,
                                  "pid_start": started_at(p.pid), "model": readers()[0], "started": C.now(),
                                  **({"since": since} if since else {})})
    if not path:
        p.kill()
        print(f"lander perms-read: {why}; nothing started")
        return 1
    print(f"lander perms-read: reading PR #{pr} at {job.head[:12]}" + (f" since {since[:12]}" if since else "")
          + f" (pid {p.pid}); the verdict goes to {path}")
    return 0


def cmd_perms_hold(argv):
    """perms-hold <repo> <pr>: hold the lane's merge of the PR at its live head before perms' read of it starts (the
    held stub perms_reading waits on; `perms-read` replaces it with the running read). Perms seat only."""
    if len(argv) != 2 or not REPO_RE.match(argv[0]) or not argv[1].isdigit():
        print("usage: lander perms-hold <repo> <pr>")
        return 2
    repo, pr = argv[0], int(argv[1])
    if not perms_seat_caller(repo):
        print("lander perms-hold: only the perms seat holds a PR for its read; nothing held")
        return 1
    job, facts = _job_of(repo, pr)
    if job is None:
        print(f"lander perms-hold: {facts}")
        return 1
    if not SHA40.fullmatch(job.head or ""):
        print(f"lander perms-hold: cannot work out PR #{pr}'s head right now; nothing held")
        return 1
    e, _ = load_read(repo, pr, job.head)
    if e:
        print(f"lander perms-hold: PR #{pr} at {job.head[:12]} already has a read ({e.get('state')}); nothing held")
        return 0
    path, why = write_read(repo, {"repo": repo, "pr": pr, "head": job.head, "change": job.digest, "state": "held",
                                  "started": C.now()})
    if not path:
        print(f"lander perms-hold: {why}; nothing held")
        return 1
    print(f"lander perms-hold: PR #{pr} at {job.head[:12]} waits for perms' read; `lander perms-read {repo} {pr}` "
          f"starts it")
    return 0


def cmd_perms_reads(argv):
    """perms-reads <repo> [<pr>]: perms' read files, newest first: what a successor seat finds running or done."""
    if len(argv) not in (1, 2) or not REPO_RE.match(argv[0]) or not all(a.isdigit() for a in argv[1:]):
        print("usage: lander perms-reads <repo> [<pr>]")
        return 2
    repo = argv[0]
    d, why = read_dir(repo)
    if not d:
        print(f"lander perms-reads: {why}")
        return 1
    for pr, head in read_files(repo, argv[1] if argv[1:] else None):
        e, why = load_read(repo, pr, head)
        if e is None:
            print(f"#{pr} {head[:12]} refused: {why}")
            continue
        # every field but the name's pr and head is the file's, and a reader's answer steers some: quoted, as data
        state = "died" if e.get("state") == "running" and not alive(e) else e.get("state")
        print(f"#{pr} {head[:12]} " + " ".join(quoted(x or "-") for x in (
            state, e.get("verdict"), e.get("model"), e.get("finished") or e.get("started")))
              + (f" why={quoted(e['why'])}" if e.get("why") else ""))
        for row in e.get("blocking") or []:
            print(f"    > {quoted(row)}")
    return 0


def cmd_perms_adopt(argv):
    """perms-adopt <repo> <pr>: put perms' finished LAND read of the PR's live head in perms' ledger, the grant the
    lane merges a security path on (requirement 3). Perms seat only."""
    if len(argv) != 2 or not REPO_RE.match(argv[0]) or not argv[1].isdigit():
        print("usage: lander perms-adopt <repo> <pr>")
        return 2
    repo, pr = argv[0], int(argv[1])
    if not perms_seat_caller(repo):
        print("lander perms-adopt: only the perms seat grants a merge; nothing granted")
        return 1
    job, facts = _job_of(repo, pr)
    if job is None:
        print(f"lander perms-adopt: {facts}")
        return 1
    if facts.get("state") == "MERGED":
        print(f"lander perms-adopt: PR #{pr} is merged; there is nothing to grant")
        return 1
    e, why = adoptable(job)
    why = why or grant(job, read_name(job.pr, job.head), e.get("model", ""), since=e.get("since", ""),
                       refresh=False)
    if why:
        print(f"lander perms-adopt: {why}; nothing granted")
        return 1
    C.log("perms-adopt", repo, pr, head=job.head if e.get("since") else job.head[:12], change=job.digest[:12],
          **({"since": e["since"]} if e.get("since") else {}))
    print(f"lander perms-adopt: perms' LAND of PR #{pr} at {job.head[:12]} is in its ledger")
    requeue_held(job, facts)
    return 0


COMMANDS = {"record": (cmd_record, "record a seat's review verdict on a PR at its head"),
            "will-review": (cmd_will_review, "say whether the landing would buy a read of a PR now"),
            "perms-read": (cmd_perms_read, "perms: start a security read that outlives the perms window"),
            "perms-hold": (cmd_perms_hold, "perms: hold a PR's merge until its read of it says LAND"),
            "perms-reads": (cmd_perms_reads, "perms: list its read files, running and done"),
            "perms-adopt": (cmd_perms_adopt, "perms: grant a merge on its finished read of the PR's live head")}
