#!/usr/bin/env python3
"""recurring_defects.py — the defect classes the landing review keeps stopping PRs for, looked for in a diff before
it is handed over. No model call, no network. cc-green runs `check` in its report and `selftest` in its selfcheck.

usage: recurring_defects.py check ROOT     exit 1 when the diff carries a class, 2 when the catalogue is unreadable
       recurring_defects.py selftest       every catalogue class against its own fixtures

WHERE THE LIST COMES FROM. Not from this file, and not from the catalogue alone:
  the record     every LAND-AFTER-FIX review the landing wrote down: the briefs it leaves in a track's state dir
                 ($CC_STATE_BASE/<repo>/<track>/review-<pr>.md) and their copies in $CC_REVIEWS_DIR
                 (~/.cc/state/land/reviews/<repo>-<pr>-<key>.md). A brief goes when its track dir goes, so every
                 check copies the live ones across first. The copies made before 2026-09-15 were taken from the
                 cc-land-review comments on the PRs.
  the catalogue  config/recurring-defects.json: per class, a `finding` regex that places a recorded review in it,
                 and the shape the class takes in a diff.
A class is CHECKED only when its finding regex matches reviews of RECUR or more distinct PRs. Below that it is not
recurring and nothing is looked for. A new class is a catalogue entry; whether it is checked is the record's call.

WHAT IS LOOKED AT: the lines the working copy adds against its merge-base with origin/HEAD (or origin/main), plus
untracked files. A class fires on a changed file whose path matches `path`, with an added line matching `added`,
unless the file as it now stands matches `unless` or the file's added lines match `unless_added`. A class that is
answered some other way is marked on an added line of that file: `recurring-defect-ok: <class> — <why>`.
"""
import contextlib, glob, hashlib, json, os, re, shutil, subprocess, sys, tempfile

RECUR = 2        # "caught more than once": distinct PRs, not review rounds of one PR
HERE = os.path.dirname(os.path.realpath(__file__))
CATALOGUE = os.path.join(HERE, "..", "config", "recurring-defects.json")
VERDICT_RE = re.compile(r"^\s*(?:\*\*)?VERDICT:?(?:\*\*)?\s*[:\-]?\s*(LAND-AFTER-FIX|DO-NOT-LAND|LAND)\b", re.M)  # cc-land's
COPY_RE = re.compile(r"^(.+)-(\d+)-([0-9a-f]{12})\.md$")


def reviews_dir():
    return os.environ.get("CC_REVIEWS_DIR") or os.path.expanduser("~/.cc/state/land/reviews")


def state_base():
    return os.environ.get("CC_STATE_BASE") or os.path.expanduser("~/.cc/state")


def load_catalogue(path=CATALOGUE):
    with open(path) as f:
        classes = json.load(f)["classes"]
    for c in classes:
        for k in ("name", "finding", "example", "what", "path", "added", "red", "clean"):
            if k not in c:
                raise ValueError(f"class {c.get('name', '?')} has no {k}")
        for k in ("finding", "path", "added", "unless", "unless_added"):
            if k in c:
                re.compile(c[k])
    return classes


def read(p):
    try:
        with open(p, errors="replace") as f:
            return f.read()
    except OSError:
        return None


def verdict(text):
    m = VERDICT_RE.search(text or "")
    return m.group(1) if m else ""


def sweep():
    """Copy each live LAND-AFTER-FIX brief into the reviews dir, once per content, so it outlives its track dir.
    A dir that cannot be written leaves the live briefs still counted where they are."""
    d = reviews_dir()
    for p in glob.glob(os.path.join(state_base(), "*", "*", "review-*.md")):
        text = read(p)
        m = re.match(r"review-(\d+)", os.path.basename(p))
        if not m or verdict(text) != "LAND-AFTER-FIX":
            continue
        repo = os.path.basename(os.path.dirname(os.path.dirname(p)))
        dst = os.path.join(d, f"{repo}-{m.group(1)}-{hashlib.sha1(text.encode()).hexdigest()[:12]}.md")
        try:
            if not os.path.exists(dst):
                os.makedirs(d, exist_ok=True)
                with open(dst + ".tmp", "w") as f:
                    f.write(text)
                os.replace(dst + ".tmp", dst)
        except OSError:
            pass


def record():
    """[(repo, pr, text)] for every LAND-AFTER-FIX review in the record, copies and live briefs both."""
    out = []
    for p in glob.glob(os.path.join(reviews_dir(), "*.md")):
        m, text = COPY_RE.match(os.path.basename(p)), read(p)
        if m and verdict(text) == "LAND-AFTER-FIX":
            out.append((m.group(1), int(m.group(2)), text))
    for p in glob.glob(os.path.join(state_base(), "*", "*", "review-*.md")):
        m, text = re.match(r"review-(\d+)", os.path.basename(p)), read(p)
        if m and verdict(text) == "LAND-AFTER-FIX":
            out.append((os.path.basename(os.path.dirname(os.path.dirname(p))), int(m.group(1)), text))
    return out


def stopped(classes, rec):
    """{class name: sorted ['repo#pr', …]} — the distinct PRs whose review the class's finding regex matches."""
    return {c["name"]: sorted({f"{repo}#{pr}" for repo, pr, text in rec
                               if re.search(c["finding"], text.split("VERDICT", 1)[-1], re.I)},
                              key=lambda s: (s.split("#")[0], int(s.split("#")[1])))
            for c in classes}


def git(root, *a):
    return subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, errors="replace")


def base_of(root):
    for ref in ("origin/HEAD", "origin/main", "origin/master"):
        if git(root, "rev-parse", "--verify", "-q", ref + "^{commit}").returncode == 0:
            mb = git(root, "merge-base", "HEAD", ref).stdout.strip()
            if mb:
                return ref, mb
    return None, None


def added_lines(root, mb):
    """{path: [(line number, text)]} the working copy adds against mb, untracked files whole."""
    out, path, n = {}, None, 0
    diff = git(root, "diff", "-U0", "--no-color", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/", mb).stdout
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            continue
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
        if m:
            n = int(m.group(1))
        elif path and line.startswith("+"):
            out.setdefault(path, []).append((n, line[1:]))
            n += 1
    for p in git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0"):
        text = read(os.path.join(root, p)) if p else None
        if text is not None and "\0" not in text:
            out[p] = list(enumerate(text.splitlines(), 1))
    return out


def hits(root, mb, live):
    found = []
    for path, lines in sorted(added_lines(root, mb).items()):
        post, added = read(os.path.join(root, path)) or "", "\n".join(t for _, t in lines)
        for c in live:
            if not re.search(c["path"], path):
                continue
            if re.search(r"recurring-defect-ok:\s*" + re.escape(c["name"]) + r"\b", added):
                continue
            if (c.get("unless") and re.search(c["unless"], post, re.M)) or \
               (c.get("unless_added") and re.search(c["unless_added"], added, re.M)):
                continue
            line = next((k for k, t in lines if re.search(c["added"], t)), None)
            if line:
                found.append((c, path, line))
    return found


def check(root, catalogue=CATALOGUE):
    try:
        classes = load_catalogue(catalogue)
    except (OSError, ValueError, KeyError, re.error) as e:
        print(f"  DEFECT  recurring defects — the catalogue cannot be read ({e}), so nothing is checked")
        return 2
    sweep()
    rec = record()
    if not rec:
        print(f"  ·       recurring defects — no LAND-AFTER-FIX review in the record ({reviews_dir()}): nothing to check")
        return 0
    prs = stopped(classes, rec)
    live = [c for c in classes if len(prs[c["name"]]) >= RECUR]
    if not live:
        print(f"  ·       recurring defects — no catalogue class has stopped {RECUR}+ of {len({(r, p) for r, p, _ in rec})} PRs: nothing to check")
        return 0
    ref, mb = base_of(root)
    if not mb:
        print("  ·       recurring defects — no origin/HEAD or origin/main to diff against: not checked")
        return 0
    found = hits(root, mb, live)
    for c, path, line in found:
        print(f"  DEFECT  {c['name']} at {path}:{line} — {c['what']} (the review stopped {len(prs[c['name']])} PRs for it: {', '.join(prs[c['name']][-3:])})")
    if not found:
        print(f"  clean   recurring defects — none of {', '.join(c['name'] for c in live)} in the diff against {ref}")
    return 1 if found else 0


def selftest():
    """Each case builds its own repo and record. For EVERY class in the shipped catalogue: its red fixture goes red
    when the record holds it on two PRs, and not on one; its clean fixture, a waiver, or the same text already on the
    base stay clean."""
    n = bad = 0

    def ok(name, cond, said=""):
        nonlocal n, bad
        n += 1
        bad += 0 if cond else 1
        print(f"  {'ok  ' if cond else 'FAIL'} {name}" + ("" if cond else f"\n{said}"))

    def run(root, env):
        p = subprocess.run([sys.executable, os.path.realpath(__file__), "check", root], capture_output=True, text=True,
                           env={**os.environ, **env})
        return p.returncode, p.stdout + p.stderr

    classes = load_catalogue()
    ok("the shipped catalogue reads, and every class's finding regex places its own example",
       all(re.search(c["finding"], c["example"], re.I) for c in classes))
    top = tempfile.mkdtemp(prefix="recurring-defects.")
    try:
        for c in classes:
            for i, (case, want) in enumerate((("red on two PRs", 1), ("red on one PR", 0), ("clean on two PRs", 0),
                                              ("waived", 0), ("already on the base", 0))):
                d = os.path.join(top, f"{c['name']}-{i}")
                root, revs, st = os.path.join(d, "repo"), os.path.join(d, "reviews"), os.path.join(d, "state")
                os.makedirs(revs)
                os.makedirs(root)
                git(root, "init", "-q")
                git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base")
                fx = c["clean" if case.startswith("clean") else "red"]
                text = fx["text"] + (f"# recurring-defect-ok: {c['name']} — answered elsewhere\n" if case == "waived" else "")
                os.makedirs(os.path.dirname(os.path.join(root, fx["path"])), exist_ok=True)
                with open(os.path.join(root, fx["path"]), "w") as f:
                    f.write(text)
                if case == "already on the base":
                    git(root, "add", "-A")
                    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "fixture")
                git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
                for pr in ((11, 11) if case == "red on one PR" else (11, 12)):
                    body = f"**VERDICT: LAND-AFTER-FIX**\n\n1. x:1 — {c['example']}\n"
                    with open(os.path.join(revs, f"r-{pr}-{hashlib.sha1(body.encode() + bytes([len(os.listdir(revs))])).hexdigest()[:12]}.md"), "w") as f:
                        f.write(body)
                rc, out = run(root, {"CC_REVIEWS_DIR": revs, "CC_STATE_BASE": st})
                named = f"DEFECT  {c['name']} at {fx['path']}:" in out
                ok(f"{c['name']}: {case} → {'red' if want else 'not red'}", rc == want and named == bool(want), out)
        # The record outlives the track: a live brief is copied, and still counts once its track dir is gone.
        d = os.path.join(top, "sweep")
        revs, st, c = os.path.join(d, "reviews"), os.path.join(d, "state"), classes[0]
        for t, pr, v in (("t1", 21, "LAND-AFTER-FIX"), ("t2", 22, "LAND-AFTER-FIX"), ("t3", 23, "LAND")):
            os.makedirs(os.path.join(st, "r", t))
            with open(os.path.join(st, "r", t, f"review-{pr}.md"), "w") as f:
                f.write(f"# cc-land review of PR #{pr}\n\nVERDICT: {v}\n\n1. x:1 — {c['example']}\n")
        env = {"CC_REVIEWS_DIR": revs, "CC_STATE_BASE": st}
        os.environ.update(env)
        sweep()
        shutil.rmtree(st)
        with open(os.path.join(revs, "r-24-000000000000.md"), "w") as f:      # a copy that says LAND counts for nothing
            f.write(f"VERDICT: LAND\n\n1. x:1 — {c['example']}\n")
        prs = stopped(classes, record())
        ok("a live LAND-AFTER-FIX brief is copied and counts after its track dir is gone; a LAND brief or copy does not",
           prs[c["name"]] == ["r#21", "r#22"], str(prs))
        rc, out = run(os.path.join(top, "nowhere"), {"CC_REVIEWS_DIR": os.path.join(d, "empty"), "CC_STATE_BASE": st})
        ok("an empty record checks nothing and says so", rc == 0 and "no LAND-AFTER-FIX review" in out, out)
        bogus = os.path.join(d, "bogus.json")
        with open(bogus, "w") as f:
            f.write('{"classes": [{"name": "x"}]}')
        with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet):
            rc = check(d, bogus)
        ok("an unreadable catalogue is not a clean check", rc == 2)
    finally:
        shutil.rmtree(top, ignore_errors=True)
    print(f"recurring-defects selftest: {n - bad} passed, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["check"] and len(a) == 2:
        sys.exit(check(a[1]))
    if a == ["selftest"]:
        sys.exit(selftest())
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    sys.exit(2)
