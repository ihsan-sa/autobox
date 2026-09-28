"""Manifests and policy: which check owns which paths, read out of a git tree (design §4; review B2, S2, S3).

WHERE THEY ARE. A manifest is `<prefix>tests/LANDING.toml` for each prefix in PREFIXES ("" is the repo, "core/" the
published tree inside it), and describes the tree it sits in: its `paths`, `fixtures` and `run` are relative to
<prefix>, so a published core/ carries a manifest that still reads right on its own. The loader prefixes paths and
fixtures, and keeps the prefix as the check's working directory (Manifest.cwd). The policy is
`<prefix>tests/LANDING-policy.toml`: top-level `default_checks` (the check NAMES an unowned path widens to) and a
`[paths]` table of globs — gate_first, paid_review, lander, protected, and `default` (paths known to be unowned, kept
in Policy.extra["default_paths"] for the card). The reach graph is `<prefix>tests/reach.tsv` (reach.py).

GLOBS. `*` and `?` stay inside one path segment, `**` crosses them; `dir/**` is everything under dir.

WHAT A CHECK OWNS. Its `paths`, its `fixtures`, and its own run file — the first word of `run` when that is a
relative path (S2: a change to a check's script or fixtures selects the check).

ADD-ONLY (S3). A head may widen the manifest, never narrow it. widen_faults(base, head) names every narrowing: a
check removed or its `run` changed, a path, fixture or `where` taken away, a class moved down CLASS_RANK (toward
fewer or later runs), a policy entry removed. It also names a check the head adds or changes that grants itself
a class outside the sandbox, net = true or a mount its base definition lacks (self_widening); a check the head adds
with no class line is hermetic, not T.Check's host default (head_check). The built-in check `manifest-widen`
(BUILTIN) is selected by any change to a manifest, policy or reach file and runs widen_faults in-process on the two
git trees; `lander manifest-widen` runs it by hand. The policy file is also lander-class: plan() sends a change to
it to lander-self.

A broken BASE manifest raises ManifestError: nothing can be planned on it. A broken HEAD manifest is not fatal to the
plan (the base rules), but its faults are carried out and make manifest-widen red.
"""
from __future__ import annotations

import dataclasses
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field

from lander import types as T

PREFIXES = ("", "core/")
MANIFEST, POLICY, REACH = "tests/LANDING.toml", "tests/LANDING-policy.toml", "tests/reach.tsv"
POLICY_LISTS = ("gate_first", "paid_review", "lander", "protected")
TOOL_DIRS = ("bin/", "bin-private/", "core/bin/")
# Higher runs earlier or on more: host runs before every merge, box only on the tip, hermetic in the sandbox,
# static reads files. A class may move up this list in a head, never down.
CLASS_RANK = {T.STATIC: 0, T.HERMETIC: 1, T.TIMING: 1, T.BOX: 2, T.HOST: 3}
# The classes that run on the host outside the sandbox (run.py), and the one a check the head adds gets when it
# names no class of its own.
UNSANDBOXED = (T.BOX, T.HOST)
NEW_DEFAULT = T.HERMETIC
BUILTIN = "manifest-widen"


class ManifestError(ValueError):
    pass


# --- the host's fallback for a repo that ships no manifest ----------------------------------------------------------

CORE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
FALLBACK_DIR = ""   # tests set it; otherwise <release>/tests/landing-repos, beside the core/ this module runs from


def host_fallback(repo: str) -> str:
    """tests/landing-repos/<repo>.toml of the RELEASE this lander runs from (lander-self builds it into
    releases/<sha>/tests/landing-repos), or "" when there is none. A repo that ships no LANDING.toml is planned and
    checked by it (load's fallback). It is read from the promoted release and never from a PR's tree, so a PR cannot
    rewrite the checks it is judged by. Nothing in the environment moves it."""
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}", repo or ""):
        return ""
    d = FALLBACK_DIR or os.path.join(os.path.dirname(CORE), "tests", "landing-repos")
    p = os.path.join(d, repo + ".toml")
    return p if os.path.isfile(p) else ""


# --- globs ---------------------------------------------------------------------------------------------------------

_GLOBS: dict = {}


def glob_re(glob: str) -> re.Pattern:
    r = _GLOBS.get(glob)
    if r is None:
        out, i = [], 0
        while i < len(glob):
            if glob.startswith("**/", i):
                out.append("(?:.*/)?"); i += 3
            elif glob.startswith("/**", i) and i + 3 == len(glob):
                out.append("(?:/.*)?"); i += 3
            elif glob.startswith("**", i):
                out.append(".*"); i += 2
            elif glob[i] == "*":
                out.append("[^/]*"); i += 1
            elif glob[i] == "?":
                out.append("[^/]"); i += 1
            else:
                out.append(re.escape(glob[i])); i += 1
        r = _GLOBS[glob] = re.compile("".join(out) + r"\Z")
    return r


def match(globs, path: str) -> bool:
    return any(glob_re(g).match(path) for g in globs)


# --- reading a tree ------------------------------------------------------------------------------------------------

def read_at(repo_root: str, rev: str, path: str):
    """The file's text at rev (a commit or tree sha), or None when it is not there. rev "" reads the working copy."""
    if not rev:
        try:
            with open(os.path.join(repo_root, path), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None
    p = subprocess.run(["git", "-C", repo_root, "show", f"{rev}:{path}"], capture_output=True)
    return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else None


# --- the manifest --------------------------------------------------------------------------------------------------

@dataclass
class Manifest:
    """checks: name -> Check with paths and fixtures prefixed to the repo root. cwd: name -> the prefix its run
    starts in. reach: (caller, callee) tool-name edges from every reach.tsv. faults: what was wrong with the text.
    unclassed: the names of checks whose text has no `class` line."""
    checks: dict = field(default_factory=dict)
    cwd: dict = field(default_factory=dict)
    policy: T.Policy = field(default_factory=T.Policy)
    reach: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    faults: list = field(default_factory=list)
    unclassed: set = field(default_factory=set)

    def owns(self, name: str, path: str) -> bool:
        c = self.checks[name]
        own = [self.cwd.get(name, "") + w for w in [run_file(c.run)] if w]
        return match(c.paths, path) or path in c.fixtures or path in own


def run_file(run: str) -> str:
    """The first word of a run line when it names a file relative to the tree, else ''."""
    w = (run.split() or [""])[0]
    return w if "/" in w and not w.startswith(("/", "-", "$", "~")) else ""


def parse_checks(text: str, prefix: str = "", source: str = "", unclassed: set | None = None) -> tuple:
    """-> ([Check], [fault]). Paths and fixtures come back prefixed. unclassed: gets the name of each check that
    names no class (it keeps T.Check's default here; head_check() decides what a new one gets)."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return [], [f"{source}: not TOML: {e}"]
    faults, out = [], []
    for k in doc:
        if k != "check":
            faults.append(f"{source}: unknown top-level key {k!r}")
    for i, d in enumerate(doc.get("check", [])):
        try:
            c = T.Check.from_dict(d)
        except ValueError as e:
            faults.append(f"{source}: check #{i + 1}: {e}")
            continue
        c.paths = [prefix + p for p in c.paths]
        c.fixtures = [prefix + p for p in c.fixtures]
        if unclassed is not None and "class" not in d:
            unclassed.add(c.name)
        out.append(c)
    return out, faults


def parse_policy(text: str, prefix: str = "", source: str = "") -> tuple:
    """-> (Policy, [fault]). Globs come back prefixed; default_checks are names and are not."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return T.Policy(), [f"{source}: not TOML: {e}"]
    faults = [f"{source}: unknown top-level key {k!r}" for k in doc if k not in ("default_checks", "paths")]
    paths = doc.get("paths", {})
    faults += [f"{source}: unknown [paths] key {k!r}" for k in paths if k not in POLICY_LISTS + ("default",)]
    try:
        pol = T.Policy(default=list(doc.get("default_checks", [])),
                       extra={"default_paths": [prefix + p for p in paths.get("default", [])]},
                       **{k: [prefix + p for p in paths.get(k, [])] for k in POLICY_LISTS})
    except (ValueError, TypeError) as e:
        return T.Policy(), faults + [f"{source}: {e}"]
    return pol, faults


def union_policy(a: T.Policy, b: T.Policy) -> T.Policy:
    u = lambda x, y: x + [v for v in y if v not in x]   # noqa: E731
    return T.Policy(default=u(a.default, b.default),
                    extra={"default_paths": u(a.extra.get("default_paths", []), b.extra.get("default_paths", []))},
                    **{k: u(getattr(a, k), getattr(b, k)) for k in POLICY_LISTS})


def load(repo_root: str, rev: str, fallback: str = "", strict: bool = True) -> Manifest:
    """The manifest, policy and reach graph at rev. fallback: a manifest file on the host for a repo that ships none
    (the overlay's landing-repos/<repo>.toml), read only when the tree has no manifest of its own. strict: a fault
    raises ManifestError (the base); otherwise faults are kept on the Manifest (a head)."""
    from lander import reach as R
    m = Manifest()
    for pre in PREFIXES:
        text = read_at(repo_root, rev, pre + MANIFEST)
        if text is not None:
            m.sources.append(pre + MANIFEST)
            checks, faults = parse_checks(text, pre, pre + MANIFEST, m.unclassed)
            m.faults += faults
            for c in checks:
                if c.name in m.checks or c.name == BUILTIN:
                    m.faults.append(f"{pre + MANIFEST}: check {c.name!r} is defined twice")
                    continue
                m.checks[c.name], m.cwd[c.name] = c, pre
        text = read_at(repo_root, rev, pre + POLICY)
        if text is not None:
            m.sources.append(pre + POLICY)
            pol, faults = parse_policy(text, pre, pre + POLICY)
            m.policy, m.faults = union_policy(m.policy, pol), m.faults + faults
        text = read_at(repo_root, rev, pre + REACH)
        if text is not None:
            m.sources.append(pre + REACH)
            m.reach += R.parse(text)
    if not m.checks and fallback:
        try:
            with open(fallback, encoding="utf-8") as f:
                checks, faults = parse_checks(f.read(), "", fallback, m.unclassed)
        except OSError as e:
            checks, faults = [], [f"{fallback}: {e}"]
        m.sources.append(fallback)
        m.faults += faults
        for c in checks:
            m.checks[c.name], m.cwd[c.name] = c, ""
    for n in m.policy.default:
        if n not in m.checks:
            m.faults.append(f"default_checks names {n!r}, which no manifest defines")
    if strict and m.faults:
        raise ManifestError("; ".join(m.faults))
    return m


def builtin_check() -> T.Check:
    """manifest-widen: owns every manifest, policy and reach file; run.py runs it in-process (static, reads git)."""
    return T.Check(name=BUILTIN, run="lander manifest-widen", klass=T.STATIC, cap=60,
                   paths=[p + f for p in PREFIXES for f in (MANIFEST, POLICY, REACH)])


def head_check(base: Manifest, head: Manifest, n: str) -> T.Check:
    """The head's check n as it is judged: a check the head adds with no class line gets NEW_DEFAULT (the sandbox),
    not T.Check's host default. A check the base has keeps whatever its text says, default included."""
    c = head.checks[n]
    if n not in base.checks and n in head.unclassed:
        c = dataclasses.replace(c, klass=NEW_DEFAULT)
    return c


def self_widening(b, h: T.Check) -> list:
    """How head check h reaches past what its base definition b (None: the head adds it) already had: a class that
    runs outside the sandbox (UNSANDBOXED), net = true, or a mount (every mount is outside the tree). A check the
    head adds or changes may not grant itself any of these; the same grant already in the base is not a widening."""
    out = []
    if h.klass in UNSANDBOXED and (b is None or b.klass != h.klass):
        out.append(f"class {h.klass}")
    if h.net and not (b is not None and b.net):
        out.append("net = true")
    out += [f"mount {m}" for m in h.mounts if b is None or m not in b.mounts]
    return out


def widen(base: Manifest, head: Manifest) -> Manifest:
    """What plan() selects from: the base's checks, each check's paths and fixtures widened by the head's, plus every
    check the head adds. A narrowing in the head is ignored here (and is manifest-widen's red), and so is a check the
    head adds that grants itself more than the sandbox: it never runs before manifest-widen refuses it."""
    out = Manifest(checks=dict(base.checks), cwd=dict(base.cwd), policy=base.policy, reach=list(base.reach),
                   sources=base.sources, faults=list(head.faults))
    for n in head.checks:
        c = head_check(base, head, n)
        if n not in out.checks:
            if not self_widening(None, c):
                out.checks[n], out.cwd[n] = c, head.cwd.get(n, "")
            continue
        b = out.checks[n]
        more = [p for p in c.paths if p not in b.paths]
        fx = [p for p in c.fixtures if p not in b.fixtures]
        if more or fx:
            out.checks[n] = dataclasses.replace(b, paths=b.paths + more, fixtures=b.fixtures + fx)
    out.reach += [e for e in head.reach if e not in out.reach]
    return out


def widen_faults(base: Manifest, head: Manifest) -> list:
    """Every way the head narrows the base (S3). Empty = the head only widens."""
    bad = list(head.faults)
    # the owner's call on U2's review: a check the head adds or changes may not widen its own boundary
    for n in head.checks:
        for w in self_widening(base.checks.get(n), head_check(base, head, n)):
            bad.append(f"check {n!r}: {'adds' if n not in base.checks else 'changes'} itself to {w}, "
                       "which its base definition does not have")
    for n, b in base.checks.items():
        h = head.checks.get(n)
        if h is None:
            bad.append(f"check {n!r} was removed")
            continue
        if h.run != b.run:
            bad.append(f"check {n!r}: run changed from {b.run!r} to {h.run!r}")
        for what in ("paths", "fixtures", "where"):
            gone = [x for x in getattr(b, what) if x not in getattr(h, what)]
            if gone:
                bad.append(f"check {n!r}: {what} lost {', '.join(gone)}")
        # review S3: refuse "a removed check, a narrowed paths, box→hermetic, a removed where"
        if CLASS_RANK[h.klass] < CLASS_RANK[b.klass]:
            bad.append(f"check {n!r}: class moved from {b.klass} down to {h.klass}")
        if head.cwd.get(n, "") != base.cwd.get(n, ""):
            bad.append(f"check {n!r} moved to another manifest")
    for k in POLICY_LISTS + ("default",):
        gone = [x for x in getattr(base.policy, k) if x not in getattr(head.policy, k)]
        if gone:
            bad.append(f"policy {k} lost {', '.join(gone)}")
    return bad


def widen_check(repo_root: str, base: str, head: str) -> tuple:
    """-> (ok, text): manifest-widen on two revisions. A base that does not parse is the base's problem, not this
    change's: it passes with a note (the plan itself refuses to run on it)."""
    try:
        b = load(repo_root, base)
    except ManifestError as e:
        return True, f"manifest-widen: the base does not parse ({e}); nothing to compare against"
    bad = widen_faults(b, load(repo_root, head, strict=False))
    return (not bad), "\n".join([f"manifest-widen: FAIL {x}" for x in bad]
                                + [f"manifest-widen: {'0 failed' if not bad else f'{len(bad)} failed'}"])


def cmd_widen(argv):
    """lander manifest-widen [--repo DIR] --base REV [--head REV]  (no --head: the working copy)"""
    a = {"--repo": ".", "--base": "", "--head": ""}
    it = iter(argv)
    for k in it:
        if k not in a:
            print(cmd_widen.__doc__.strip(), file=sys.stderr)
            return 2
        a[k] = next(it, "")
    if not a["--base"]:
        print(cmd_widen.__doc__.strip(), file=sys.stderr)
        return 2
    ok, text = widen_check(a["--repo"], a["--base"], a["--head"])
    print(text)
    return 0 if ok else 1


COMMANDS = {"manifest-widen": (cmd_widen, "refuse a head that narrows LANDING.toml or its policy (S3)")}
