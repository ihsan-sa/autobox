#!/usr/bin/env python3
"""split.py — writes core/tests/e2e/<slug>.sh, one file per selftest.sh stanza that has a body of its own.

Each file is GENERATED from selftest.sh, never hand-copied, so the two cannot drift apart while both exist:
  split.py           write every file
  split.py --check   write nothing; exit 1 naming each file that differs from what it would write now

A generated file sources lib.sh (the preamble without the suite machinery), then runs, in selftest.sh's order,
the base fixture stanzas and the top-level lines that come before its stanza, then the stanza, then e2e_end.

The table below maps each stanza title to its file. A title in selftest.sh that is not in the table is an error,
unless its body is nothing but `chk cc-foo` lines (the same rule as selftest.sh's STANZA_HALF scan): those are a
tool's own selfcheck and get no file here. A table entry with no stanza, or one whose stanza is chk-only, is an
error too.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SELFTEST = os.path.join(HERE, "..", "selftest.sh")
GREEN = os.path.join(HERE, "..", "green.sh")

SLUGS = {
    "cc main + track creation": "cc-main-track-creation",
    "cc claim: the canonical track prepared and claimed, with nothing launched": "cc-claim",
    "checkpoint hook": "checkpoint-hook",
    "cc-context (the real number, and what refuses to run without it)": "cc-context",
    "guard": "guard",
    "overlapping handoff: two sessions, one cwd, exactly one of them live": "overlapping-handoff",
    "cc-notify: an escalation reaches the PLANNING SEAT, not the owner and not the channel it came from": "cc-notify-escalation",
    "--say / --go / cc-loop": "say-go-loop",
    "--go is a covering note, never a replacement for the brief (#71)": "go-covering-note",
    "a finished track leaves the default board view (a13)": "finished-track-board",
    "the step limit carries on, and a runaway does not (cc-loop)": "step-limit",
    "usage limits (cc-limit + cc-loop)": "usage-limits",
    "one limit episode, end to end (cc-limit writes the record and the episode down; cc-model and cc-reconcile read them)": "limit-episode",
    "resume/digest/rm": "resume-digest-rm",
    "cc-slack (local router + channel server; no Slack, no API)": "cc-slack-local",
    "model fallback (cc-model + cc-limit)": "model-fallback",
    "ccbox: a new box's ~/.claude gets the login and nothing else": "ccbox-login",
    "ccbox: a headless --cmd, and the seed helper's image (docker stubbed)": "ccbox-headless",
    "cc-trust prune (recorded trust vs real dirs)": "cc-trust-prune",
    "cc-rename (a project's name, everywhere the box keys by it)": "cc-rename",
    "what the snapshot's four readers do with it (waiting vs the clock, and without it)": "snapshot-readers",
    "cc-publish: core/ publishes itself": "cc-publish",
    "install.sh on a blank HOME (the bare-clone bootstrap)": "install-blank-home",
    "the suite's own reporting, and what a green run leaves behind": "suite-reporting",
    "the suite's own slots (a cap, not a queue)": "suite-slots",
}

# The fixtures every file stands on: selftest.sh's `always` stanzas that build the repo, w1 and its session.
BASE = ["cc main + track creation", "checkpoint hook"]

# A stanza that stands on state an earlier NON-always stanza leaves names that stanza here; it runs as a fixture.
DEPS = {
}

# A stanza that tests selftest.sh's own machinery gets that machinery, extracted from selftest.sh's preamble
# (start and end line patterns, both inclusive) and run after lib.sh, where it replaces lib.sh's reduced copy.
EXTRAS = {
    "suite-reporting": [
        (r"^qbad\(\)\{", r"^qbad\(\)\{"),
        (r"^land_scope \"\$B\"$", r"^land_scope \"\$B\"$"),
        (r"^declare -A STANZA_TOOLS", r"^  END \{ if \(title != \"\"\) emit\(\) \}' \"\$SELF\"\)$"),
        (r"^selftest_reach\(\)\{", r"^  printf '%s' \"\$tools\"; \}$"),
        (r"^stanza\(\)\{", r"^  return 0; \}$"),
        (r"^chk\(\)\{", r"^  return 0; \}$"),
        (r"^declare -A PFPID", r"^unclaim\(\)"),
    ],
}

CHK_ONLY = re.compile(r"^chk +cc-[a-z0-9-]+[ \t]*(#.*)?$")
HEADER = re.compile(r'^(if )?stanza "([^"]*)"')
MARK = "# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py."
# Every generated file ends on these two lines. A stanza drives cc against a throwaway fixture repo, so the
# review's pause and held-files questions are asked of the tool it tests, not of the test. They sit after
# e2e_end so that appending them never moves a line a running copy of the file is reading.
TRAILER = [
    "# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's",
    "# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives",
]


def die(msg):
    sys.stderr.write("split.py: %s\n" % msg)
    sys.exit(2)


def parse(lines):
    """-> preamble lines, and segments in order: ('stanza', title, lines) or ('top', None, lines)."""
    first = next((i for i, l in enumerate(lines) if HEADER.match(l)), None)
    if first is None:
        die("no stanza in selftest.sh")
    segs, top, i, last_end = [], [], first, first
    while i < len(lines):
        m = HEADER.match(lines[i])
        if m:
            if top:
                segs.append(("top", None, top))
                top = []
            j = i
            while j < len(lines) and lines[j] != "fi":
                j += 1
            if j == len(lines):
                die("stanza %r has no closing fi" % m.group(2))
            segs.append(("stanza", m.group(2), lines[i:j + 1]))
            i = last_end = j + 1
            continue
        top.append(lines[i])
        i += 1
    # what follows the last stanza is selftest.sh's end-of-run, which lib.sh's e2e_end stands in for
    return lines[:first], segs


def chk_only(body):
    """The STANZA_HALF rule: every body line is a comment, blank, then/fi, or a bare `chk cc-foo`."""
    for l in body[1:]:
        if re.match(r"^[ \t]*#", l) or re.match(r"^[ \t]*$", l) or l in ("fi", "then") or CHK_ONLY.match(l):
            continue
        return False
    return True


def extract(pre, start, end, slug):
    s = next((i for i, l in enumerate(pre) if re.search(start, l)), None)
    if s is None:
        die("%s: no line in selftest.sh's preamble matches %r" % (slug, start))
    e = next((i for i in range(s, len(pre)) if re.search(end, pre[i])), None)
    if e is None:
        die("%s: no end %r after %r in selftest.sh's preamble" % (slug, end, start))
    return pre[s:e + 1]


def top_lines(seg):
    """A top-level gap's commands: its comments and blanks dropped, and `prefetch` (lib.sh has none)."""
    return [l for l in seg if not re.match(r"^[ \t]*(#|$)", l) and not l.startswith("prefetch ")]


def build():
    with open(SELFTEST) as f:
        lines = f.read().split("\n")
    with open(GREEN) as f:
        green_fns = set(re.findall(r"^([a-z_]+)\(\)", f.read(), re.M))
    pre, segs = parse(lines)
    titles = [t for k, t, _ in segs if k == "stanza"]
    errs, skipped, out = [], [], {}
    for t in SLUGS:
        if t not in titles:
            errs.append("table entry with no stanza: %r" % t)
    for dep_slug, deps in DEPS.items():
        for d in deps:
            if d not in titles:
                errs.append("%s: declared fixture %r is no stanza" % (dep_slug, d))
    for b in BASE:
        if b not in titles:
            errs.append("base fixture %r is no stanza" % b)
    for idx, (kind, title, body) in enumerate(segs):
        if kind != "stanza":
            continue
        if chk_only(body):
            if title in SLUGS:
                errs.append("%r is chk-only and gets no file, but the table names it" % title)
            skipped.append(title)
            continue
        if title not in SLUGS:
            errs.append("stanza with a body of its own and no slug: %r" % title)
            continue
        slug = SLUGS[title]
        fixtures = set(BASE) | set(DEPS.get(slug, []))
        parts, used = [], list(body)
        for k2, t2, b2 in segs[:idx]:
            if k2 == "stanza" and t2 in fixtures:
                parts += ["# ── fixture: %s" % t2] + b2
                used += b2
            elif k2 == "top":
                tl = top_lines(b2)
                if tl:
                    parts += ["# ── top level, between stanzas"] + tl
        for d in DEPS.get(slug, []):
            if titles.index(d) > titles.index(title):
                errs.append("%s: fixture %r comes after it in selftest.sh" % (slug, d))
        text = "\n".join(used)
        needs_green = any(re.search(r"(^|[^A-Za-z0-9_])%s([^A-Za-z0-9_]|$)" % fn, text, re.M) for fn in green_fns)
        head = [
            "#!/usr/bin/env bash",
            MARK,
            "# %s.sh — the stanza \"%s\", run alone on the fixtures it stands on." % (slug, title),
            '. "$(dirname "$0")/lib.sh"',
        ]
        if needs_green:
            head.append('. "$(dirname "$SELF")/green.sh"   # this stanza calls what green.sh defines')
        for s, e in EXTRAS.get(slug, []):
            head += ["# ── from selftest.sh's preamble: the machinery this stanza tests"] + extract(pre, s, e, slug)
        out[slug] = "\n".join(head + parts + ["# ── the stanza"] + body + ["e2e_end"] + TRAILER + [""])
    for s in EXTRAS:
        if s not in out:
            errs.append("EXTRAS names %r, which is no generated file" % s)
    if errs:
        die("\n  ".join(["selftest.sh and the table disagree:"] + errs))
    return out, skipped


def main():
    check = sys.argv[1:] == ["--check"]
    if sys.argv[1:] and not check:
        die("usage: split.py [--check]")
    out, skipped = build()
    differ = []
    for slug, text in sorted(out.items()):
        p = os.path.join(HERE, slug + ".sh")
        try:
            with open(p) as f:
                have = f.read()
        except OSError:
            have = None
        if have != text:
            differ.append(p)
            if not check:
                with open(p, "w") as f:
                    f.write(text)
        # the manifest runs each stanza by path, so it must be executable
        if have is not None and not os.access(p, os.X_OK):
            if check:
                differ.append(p + " (not executable)")
        if not check and os.path.exists(p):
            os.chmod(p, 0o755)
    # a generated file whose stanza is gone (or renamed) is stale
    for n in sorted(os.listdir(HERE)):
        p = os.path.join(HERE, n)
        if n.endswith(".sh") and n[:-3] not in out and n != "lib.sh":
            with open(p) as f:
                if MARK in f.read():
                    differ.append(p + " (stale: no stanza generates it)")
    if check:
        for p in differ:
            print("split.py --check: differs from what split.py writes now: %s" % os.path.relpath(p))
        sys.exit(1 if differ else 0)
    for t in skipped:
        print("  · skipped by rule (body is only chk lines): %s" % t)
    stale = [p for p in differ if p.endswith("generates it)")]
    print("split.py: %d files, %d written, %d skipped by rule%s" % (
        len(out), len(differ) - len(stale), len(skipped),
        (", stale (remove by hand): " + " ".join(stale)) if stale else ""))


if __name__ == "__main__":
    main()
