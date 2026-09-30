"""The lander's review read: one tool-less read per change digest, the delta read after a handback, and the records.

    lander record <repo> <pr> LAND|HANDBACK --by <who> [--head <sha>] [--findings TEXT|-]
                                     write a read a seat made as the PR's marker comment; refused if --head moved,
                                     or if it is looser than a HANDBACK already standing (old words map as below)
    lander will-review <repo> <pr>   exit 0 when the lander would buy a read for this PR at its head, else 1

ONE READ PER CHANGE DIGEST. The digest is digest_of(): change_digest() of `git diff base...head` as plain_diff()
makes it (blind to the checkout's config and attributes, so binary means binary bytes), the hunk headers and `index`
lines dropped (a binary file's full blob ids kept) and the rest hashed, so a rebase that does not change the change
keeps its key. It is the one key: the lane names its job by it, and `record` and `will-review` by it too. A read
recorded at that digest (or the legacy one, keys()) — by this lander, by a seat through `record`, or by the old
lander — is reused, never bought again, by review() and delta_review() alike.

WHERE VERDICTS LIVE. On the PR, as marker comments. Today's shape is kept so every reader still parses it:

    <!-- cc-land-review v2 change=<digest> base=<12> head=<12> verdict=<V> by=<who> -->

The new lander writes V = LAND or HANDBACK. Markers the old lander wrote are IMPORTED: LAND stays LAND;
LAND-AFTER-FIX whose findings are all `[other]` lands (that was its rule too: the findings went to a follow-up
row); any other LAND-AFTER-FIX, and DO-NOT-LAND, is HANDBACK. Only comments the box's own GitHub login wrote count
(gh's viewerDidAuthor), as before: anyone can type a marker into a PR.

WHEN A READ IS BOUGHT (review()). A recorded verdict at the digest (or the legacy digest, which kept the hunk
tail) is returned as it is. Otherwise, a change that touches no paid-review path (job.plan.paid false) needs no
read: LAND with model "" and extra read=none. Otherwise the lander buys one:
  - the usage limit binds (`cc-limit status` exit 0) -> INCOMPLETE, no read counted, nothing posted; extra
    `until` (limit_until) says when to ask again, and the lane holds the job till then.
  - two reads already spent on this PR (the family: repo + PR number, so a push or a reopen does not reset it) ->
    HANDBACK with extra cap=True and no read bought; the lane sends a query card to the planning seat.
  - else one read by EACH model on CC_LAND_REVIEWERS (the passwd home's ~/.cc/config only, cards.REVIEWER_CONFIG;
    default READERS: Fable 5.1 and Astra 6 — owner, 2026-09-24: "a review goes to Fable 5.1 and Astra 6
    together"), at CC_LAND_REVIEW_EFFORT (default high; one of EFFORTS, checked before any read). A `claude-*`
    model or a claude alias (CLAUDE_ALIASES) is one `claude -p` call, no tools; any other is one `codex exec`
    call with every tool feature on CODEX_OFF disabled and the user config ignored, and before it `codex features
    list` must show nothing on outside CODEX_ON_OK. Every read runs on READ_PATH with HOME at the passwd home and no
    variable of the caller's but READ_ENV_KEEP (clean_env), claude is claude_bin() and codex is codex_bin() with
    CODEX_HOME at the passwd home, so the caller's PATH, HOME, ANTHROPIC_* or CODEX_HOME picks nothing. Both get the prompt
    core/config/lander/review.md from THIS release (not the PR's
    head) with the diff, the merged text of the changed files, the brief's done-criteria and docs/REVIEW.md
    read from the BASE commit, each between `<<<name` / `name>>>` markers (a marker inside the data is broken
    up, so the data cannot close its own block). The answer is JSON (verdict, blocking[], advisory[]).
    A change lands only on EVERY reader's verdict (owner: both models read every change). A reader that hits the
    limit (`cc-limit check`), or answers nothing the first time at a head, makes the whole read INCOMPLETE and
    refunded, as if it never ran; the readers that did answer are kept at this digest (partial()), so the retry
    asks only the silent one. A reader that CANNOT answer — a bad model id or effort, a missing binary, a flag
    error, a tool feature codex will not turn off — or answers nothing twice at one head is a HANDBACK stop naming
    the reader and the cause (extra fault=True), never a silent retry.
    The verdict is HANDBACK when any reader's is; the findings are all readers', each row naming its reader; the
    marker lists every reader's own verdict. Together they count as ONE read against the cap.
    CC_LAND_REVIEW_MODEL, when set, is the only reader (the old single-read setting).
The read runs with its cwd in `$TMPDIR/cc-land.run.<pid>.<rand>/cc-land.review.<repo>.<pr>.<rand>`: that name is
how cc-spend puts its cost on `<repo>/review`, and every read's cost is also added to the PR's spend file
(root/<repo>-<pr>.json, `review_usd`, `reads`) that the old lander kept.

A handback's re-read is delta_review(): the interdiff between the head the prior read saw and this head, the prior
blockers numbered; it answers resolved/unresolved and new blockers on added lines only. It counts as a read.

A LAND with advisory findings files ONE follow-up row, review-followup-pr<N> (board.followup).

PAUSE. The lane asks cc-pause and cc-tier before it calls review() (U1 owns that hold, per the design); nothing
here runs for a paused project. recurring-defect-ok: pause-hold-missing — the lane (U1) holds a paused repo before any U3 call
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import sys
import json
import os
import re
import shutil
import tempfile

from lander import cards as C
from lander import types as T

MARK = "cc-land-review"
MAX_READS = 2
READERS = "claude-fable-5-1 gpt-6-astra"   # the default of CC_LAND_REVIEWERS
READ_TIMEOUT = 1200
PROMPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "config", "lander")
OLD_VERDICTS = ("LAND-AFTER-FIX", "DO-NOT-LAND", "LAND", "HANDBACK")
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
    said = [f"- `{r['model']}`: {r['verdict']}" for r in (v.extra or {}).get("readers") or []]
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


def recorded(comments, digests):
    """The newest verdict among the PR's `comments` (gh's [{"body", "viewerDidAuthor"}]) at any of `digests`. Only
    comments this box's own GitHub login wrote count: anyone can type a marker into a PR. -> Verdict or None."""
    found = None
    for c in comments:
        v = imported(c.get("body", "")) if c.get("viewerDidAuthor") else None
        if v and v.digest in digests:
            found = v
    return found


def latest(comments):
    """The newest verdict the box wrote on this PR at any digest, or None (a handback's re-read starts from it)."""
    found = None
    for c in comments:
        v = imported(c.get("body", "")) if c.get("viewerDidAuthor") else None
        found = v or found
    return found


# --- the prompt ----------------------------------------------------------------------------------------------------

def fence(name, text):
    """Break any `name>>>` / `<<<name` inside the data so it cannot close or open its block."""
    text = text or ""
    for tag in ("diff", "files", "brief", "rules", "prior", "interdiff"):
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
    """The model's answer -> Verdict. Anything that is not the schema's object is None (nothing read the diff)."""
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
    unresolved = [str(x) for x in j.get("unresolved") or []]
    verdict = j["verdict"]
    if verdict == T.LAND and (blocking or unresolved):   # a blocker is a blocker whatever the verdict word says,
        verdict = T.HANDBACK_VERDICT                     # and so is an earlier blocker the read says is still open
        if not blocking:
            blocking = [f"still open from the earlier read: {x}" for x in unresolved][:10]
    return T.Verdict(verdict=verdict, digest=digest, blocking=blocking, advisory=advisory, model=model,
                     tokens=int(tokens or 0), resolved=[str(x) for x in j.get("resolved") or []],
                     unresolved=unresolved)


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


# --- the box around a read -----------------------------------------------------------------------------------------

SECRET_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
SECRET_TAIL = ("_TOKEN", "_KEY", "_SECRET", "_CREDS", "_WEBHOOK", "_PASSWORD")
LIMIT_SAID = re.compile(r"\b(session|usage|rate)[ _-]?limit", re.I)
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

# An answer that says the read cannot run as asked, so waiting will not mend it: a 4xx other than 429 from either
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


def ask_codex(text, repo, pr, digest, model):
    """One tool-less `codex exec` read. -> (Verdict | None, 0.0, why), as ask(); codex reports no dollar cost."""
    run, cwd = scratch(repo, pr)
    schema, answer = os.path.join(run, "schema.json"), os.path.join(run, "answer.json")
    argv = codex_argv("exec", "-m", model, "-c", f'model_reasoning_effort="{effort()}"', "-c", 'web_search="disabled"',
                      "-s", "read-only", "--ignore-user-config", "--ignore-rules", "--ephemeral",
                      "--skip-git-repo-check", "--color", "never", "--output-schema", schema, "-o", answer, "-C", cwd)
    said, rc, out = "", 1, ""
    try:
        left = codex_tools_left(run)
        if left:
            return None, 0.0, f"fault: {left}"
        with open(schema, "w") as f:
            json.dump(strict(SCHEMA), f)
        rc, out = C.sh(argv + ["-"], cwd=cwd, input=text, timeout=READ_TIMEOUT, env=codex_env())
        try:
            with open(answer) as f:
                said = f.read()
        except OSError:
            pass
    finally:
        shutil.rmtree(run, ignore_errors=True)
    v = parse(said, digest, model=model)
    if v:
        return v, 0.0, ""
    tail = " ".join((out or "").split())[-200:]
    if LIMIT_SAID.search(out or ""):
        return None, 0.0, f"limit: rc={rc} {tail}"
    bad = fault(rc, out)
    return None, 0.0, f"fault: rc={rc} {bad}" if bad else f"no answer: rc={rc} {tail}"


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
            "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
            "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands", "--tools", ""]
    run, cwd = scratch(repo, pr)
    try:
        rc, out = C.sh(argv, cwd=cwd, input=text, timeout=READ_TIMEOUT, env=clean_env())
    finally:
        shutil.rmtree(run, ignore_errors=True)
    try:
        j = json.loads(out)
    except ValueError:
        j = {}
    usd = float(j.get("total_cost_usd") or 0) if isinstance(j, dict) else 0.0
    v = parse(out, digest, model=model)
    if v:
        return v, usd, ""
    if isinstance(j, dict) and j.get("subtype") in WALLS:
        return None, usd, f"wall: {j['subtype']} at ${usd:.2f}"
    said = json.dumps(j)[-400:] if j else out[-400:]
    if usd == 0 and LIMIT_SAID.search(said):
        return None, usd, f"limit: {said[-160:]}"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(out or "{}")
    try:
        lrc, _ = C.sh([os.path.join(BIN, "cc-limit"), "check", f.name], timeout=60)
    finally:
        os.unlink(f.name)
    if lrc == 0:
        return None, usd, "limit: cc-limit check says the run hit a usage limit"
    bad = fault(rc, out)
    return None, usd, f"fault: rc={rc} {bad}" if bad else f"no answer: rc={rc} {said[-200:]}"


# --- the repo side of a read ---------------------------------------------------------------------------------------

def root_of(job):
    if job.extra.get("root"):
        return job.extra["root"]
    if job.member:
        return C.state("clones", job.repo)
    return os.path.join(os.path.expanduser(C.conf("CC_DEV", "~/dev")), job.repo)


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
    for it."""
    with blind(root, base, head) as (got, run):
        if run is None:
            return "\n".join(file_block(p, "?", "?", unseen=["git could not read this change"]) for p in files)
        base, head = got[1]
        rc, tree = run("merge-tree", "--write-tree", "-z", base, head)
        tree = tree.split("\0")[0].strip() if not rc and tree.strip() else head
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
            body = text[:FILE_CAP]
            if total + len(body) > FILES_CAP:
                if diffed:
                    out.append(file_block(p, *modes, ["not shown here, the files block is full; its whole diff is in "
                                                      "`diff`"], text=text, diffed=True))
                else:
                    out.append(file_block(p, *modes, unseen=unseen + ["not shown: the files block is full"], text=text))
                continue
            total += len(body)
            notes = []
            if len(body) < len(text) and diffed:
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


def pr_view(root, pr, fields="comments"):
    rc, out = C.sh(["gh", "pr", "view", str(pr), "--json", fields], cwd=root, timeout=120)
    try:
        return json.loads(out) if rc == 0 else None
    except ValueError:
        return None


def post(root, pr, body):
    rc, out = C.sh(["gh", "pr", "comment", str(pr), "--body-file", "-"], cwd=root, input=body, timeout=120)
    return rc == 0


# --- review / delta_review -----------------------------------------------------------------------------------------

def _stop(job, why, **extra):
    return T.Verdict(verdict=T.HANDBACK_VERDICT, digest=job.digest, blocking=[why], extra=extra)


def _no_diff(job):
    """The PR changes files but git gave no diff (a fetch that did not land, a merge-base it cannot find): a read of
    nothing would judge nothing, so none is bought and the next tick asks again."""
    return T.Verdict(verdict=T.INCOMPLETE, digest=job.digest,
                     extra={"why": f"no diff for {len(job.files)} changed file(s) at {job.head[:12]}",
                            "until": limit_until("")})


def review(job, comments=None):
    """See the module doc. `comments` is the PR's comment list when the caller already has it."""
    root = root_of(job)
    if comments is None:
        comments = (pr_view(root, job.pr) or {}).get("comments") or []
    diff = diff_of(root, job.base_sha, job.head)
    if not diff and job.files:
        return _no_diff(job)
    have = recorded(comments, keys(job, diff))
    if have:
        return have
    if not (job.plan and job.plan.paid):
        return T.Verdict(verdict=T.LAND, digest=job.digest, extra={"read": "none"})
    prior = latest(comments)
    if prior and prior.verdict == T.HANDBACK_VERDICT and prior.extra.get("head"):
        return delta_review(job, prior, comments=comments, diff=diff)
    return _buy(job, "review.md", diff, {})


def delta_review(job, prior, comments=None, diff=None):
    root = root_of(job)
    if comments is None:
        comments = (pr_view(root, job.pr) or {}).get("comments") or []
    diff = diff if diff is not None else diff_of(root, job.base_sha, job.head)
    if not diff and job.files:
        return _no_diff(job)
    have = recorded(comments, keys(job, diff))
    if have:   # a verdict recorded at this digest after the prior one (a seat's `record`) is the one that stands
        return have
    was = prior.extra.get("head", "")
    rc, full = git(root, "rev-parse", "--verify", "-q", f"{was}^{{commit}}") if was else (1, "")
    rc2, inter = plain_diff(root, full.strip(), job.head) if not rc else (1, "")
    if rc or rc2:   # the head that read saw is gone (a force-push): read it whole, against the prior findings
        inter = "(the head the earlier read saw is no longer in this repository; read the whole diff)"
    numbered = "\n".join(f"{i}. {b}" for i, b in enumerate(prior.blocking, 1)) or "(none)"
    return _buy(job, "delta.md", diff, {"PRIOR": numbered, "INTERDIFF": capped(inter)})


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


def combined(reads):
    """[(model, Verdict)], every reader's -> the one Verdict the landing acts on: HANDBACK when any reader's is, every
    reader's findings tagged with its model, and extra `readers` naming each reader's own verdict. A single reader's
    Verdict is returned as it is."""
    if len(reads) == 1:
        return reads[0][1]
    tag = lambda attr: [f"{r} (read by {m})" for m, x in reads for r in getattr(x, attr)]  # noqa: E731
    unresolved = sorted({u for _, x in reads for u in x.unresolved})
    first = reads[0][1]
    v = T.Verdict(verdict=T.HANDBACK_VERDICT if any(x.verdict == T.HANDBACK_VERDICT for _, x in reads) else T.LAND,
                  digest=first.digest, blocking=tag("blocking"), advisory=tag("advisory"),
                  model="+".join(m for m, _ in reads), tokens=sum(x.tokens for _, x in reads),
                  resolved=[r for r in first.resolved if r not in unresolved], unresolved=unresolved)
    v.extra["readers"] = [{"model": m, "verdict": x.verdict} for m, x in reads]
    return v


def partial(digest, template):
    """Where the readers that answered wait while another is silent: {model: verdict}, one file per digest and
    prompt, so a retry does not buy their read again. It goes when the read is complete. It lives under the passwd
    home, never C.state(): $CC_LAND_STATE is the caller's, and a worker that queues with it pointing at its own dir
    could plant a LAND for every reader there and have no read bought (security read of #847)."""
    return os.path.join(C.PASSWD_HOME, ".cc", "state", "land", "reviews",
                        f"{digest}.{os.path.splitext(template)[0]}.partial.json")


def _silent(job, j, model, why):
    """A reader answered nothing: INCOMPLETE (refunded, held, asked again), or a stop naming it when waiting will not
    mend it (a fault, or a second silence or wall at the same head)."""
    repo, pr, head = job.repo, job.pr, job.head
    if why.startswith("fault"):
        return _stop(job, f"review reader {model} cannot run: {why[len('fault: '):]}", fault=True, reader=model)
    if why.startswith("wall"):
        if (j.get("wall") or {}).get("head") == head:
            return _stop(job, f"the read hit its own cap twice at {head[:12]} ({model}: {why})", cap=True)
        charge(repo, pr, wall={"head": head, "why": why, "at": C.now()})
    elif not why.startswith("limit"):
        was = j.get("silent") or {}
        if (was.get("head"), was.get("reader")) == (head, model):
            return _stop(job, f"review reader {model} answered nothing twice at {head[:12]}: {why}",
                         fault=True, reader=model)
        charge(repo, pr, silent={"head": head, "reader": model, "why": why, "at": C.now()})
    return T.Verdict(verdict=T.INCOMPLETE, digest=job.digest,
                     extra={"why": f"{model}: {why}", "until": limit_until(why), "reader": model})


def _buy(job, template, diff, more):
    repo, pr = job.repo, job.pr
    lim_rc, lim = C.sh([os.path.join(BIN, "cc-limit"), "status"], timeout=60)
    if lim_rc == 0:
        return T.Verdict(verdict=T.INCOMPLETE, digest=job.digest,
                         extra={"why": f"usage limit: {lim.strip()}", "until": limit_until(lim)})
    j = spent(repo, pr)
    if int(j.get("reviews") or 0) >= MAX_READS:
        return _stop(job, f"two reads already spent on PR #{pr}; the planning seat decides", cap=True)
    if effort() not in EFFORTS:
        return _stop(job, f"the review cannot run: CC_LAND_REVIEW_EFFORT={effort()!r} is not one of "
                          f"{', '.join(EFFORTS)}", fault=True)
    root = root_of(job)
    facts = pr_view(root, pr, "title") or {}
    # the union: job.files is the lane's list, which a job queued by an older lane may have made in the checkout's
    # own git; files_of() runs blind and sees every path
    blind_files = files_of(root, job.base_sha, job.head)
    files = list(dict.fromkeys([*job.files, *blind_files]))
    dropped = cut_paths(diff, blind_files) if len(diff) > DIFF_CAP else []
    text = prompt(load_prompt(template), PR=pr, REPO=repo, TITLE=facts.get("title") or "(untitled)",
                  DIFF=capped(diff, dropped),
                  FILES=merged_files(root, job.base_sha, job.head, files, dropped, whole_paths(diff, blind_files)),
                  BRIEF=brief_of(job) or
                  "No brief was found for this PR. Judge the change against its title and its own diff.",
                  RULES=rules_of(root, job.base_sha) or "This repo ships no docs/REVIEW.md.", **more)
    kept = C.read_json(partial(job.digest, template), {}) or {}
    reads, usd = [], 0.0
    for model in readers():
        if isinstance(kept.get(model), dict):
            reads.append((model, T.Verdict.from_dict(kept[model])))
            continue
        v, cost, why = ask(text, repo, pr, job.digest, model)
        if cost:
            charge(repo, pr, review_usd=cost)
            usd += cost
        if v is None:
            return _silent(job, j, model, why)
        reads.append((model, v))
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
    facts = pr_view(root, pr, "headRefOid,baseRefName,comments,state,files,headRefName")
    if not facts:
        return None, f"cannot read PR #{pr} of {repo} from GitHub"
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


def cmd_record(argv):
    """record <repo> <pr> <VERDICT> --by <who> [--head <sha>] [--findings <text>|-]"""
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
    if head and not job.head.startswith(head):
        print(f"lander record: PR #{pr} is at {job.head[:12]} now, not {head[:12]} — the branch moved after that "
              "read, so it did not read this head. Read it again.")
        return 1
    findings = sys.stdin.read() if opts.get("findings") == "-" else (opts.get("findings") or "")
    stands = recorded(facts.get("comments") or [], {job.digest})
    who = re.sub(r"[^A-Za-z0-9._@-]+", "-", opts["by"])
    # a second reader's LAND is posted too: lander-self needs an Opus read and a security read at one head
    if stands and stands.verdict == word and (word != T.LAND or stands.model == who):
        print(f"lander record: {word} is already recorded for this change; nothing to do")
        return 0
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
    return 0


def would_read(job, comments):
    """-> (bool, why): whether review() would buy a read for this job now; it matches the same keys() review() does."""
    if recorded(comments, keys(job, diff_of(root_of(job), job.base_sha, job.head))):
        return False, "a verdict is already recorded for this change, and the landing reads that"
    if not (job.plan and job.plan.paid):
        return False, "it touches no paid-review path, so nothing reads it"
    if reads_used(job.repo, job.pr) >= MAX_READS:
        return False, f"its {MAX_READS} reads are spent; record the verdict of a read you buy (`lander record`)"
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
        job.plan = P.plan(root_of(job), job.base_sha, job.head, job.files)
    except Exception:  # noqa: BLE001
        job.plan = T.Plan(paid=True)
    yes, why = would_read(job, facts.get("comments") or [])
    print(f"[{job.repo}] PR #{job.pr} at {job.head[:12]}: the landing {'WILL' if yes else 'will NOT'} read it — {why}")
    return 0 if yes else 1


COMMANDS = {"record": (cmd_record, "record a seat's review verdict on a PR at its head"),
            "will-review": (cmd_will_review, "say whether the landing would buy a read of a PR now")}
