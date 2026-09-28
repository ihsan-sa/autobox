"""plan(): which checks a change reaches, and what kind of landing it is (design §0 Selection, §4; review S2, S3, S10).

PURE. It reads the manifest, policy and reach graph out of git at base_sha (and the head's, which may only widen:
manifest.widen) and returns a Plan. It writes nothing, runs nothing and asks no network.

SELECTION, per changed file:
  - PROSE (is_prose, S10) reaches only the static checks that own it: docs/**, core/docs/**, *.pdf, images, and
    *.md — except under core/templates/**, templates/**, home/**, core/config/**, config/**, any agents/ directory,
    and any REVIEW.md, which are instructions, not prose.
  - every other path selects each check that owns it (its paths, fixtures or run file). A path no check owns is
    UNOWNED: the change widens to the policy's default_checks and Plan.unowned names it for the card.
  - a changed tool (a file under bin/, bin-private/ or core/bin/) also selects the non-static checks that own each
    of its direct callers in reach.tsv — one hop, never further.
  - a change to a manifest, policy or reach file selects the built-in manifest-widen check.
Plan.checks holds what runs BEFORE the merge. Box-class checks run on main's tip after it and are listed in
Plan.extra["tip"] instead — except for a gate-first change, which keeps them before the merge (owner, 2026-09-24).

KLASS, first match wins: protected (a policy protected glob, or the caller's `protected` list — CC_PROTECTED_PATHS
lives in the box's config, never in a tree) > lander (a policy lander glob, or the policy file itself) > gate-first
> docs (every file prose) > wide (some path unowned) > leaf. paid: some file matches paid_review.

    lander plan [--repo DIR] [--manifest FILE] BASE [HEAD]    (no HEAD: the working copy; prints the Plan as JSON)
"""
from __future__ import annotations

import json
import os
import sys

from lander import manifest as M
from lander import reach as R
from lander import types as T

PROSE_EXT = (".md", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
PROSE_DIRS = ("docs/**", "core/docs/**")
NOT_PROSE = ("core/templates/**", "templates/**", "home/**", "core/config/**", "config/**", "**/agents/**",
             "**/REVIEW.md")


def is_prose(path: str) -> bool:
    """S10. Instruction files outrank the extension and the docs/ rule."""
    if M.match(NOT_PROSE, path):
        return False
    return M.match(PROSE_DIRS, path) or path.lower().endswith(PROSE_EXT)


def tool_name(path: str) -> str:
    for d in M.TOOL_DIRS:
        if path.startswith(d) and "/" not in path[len(d):]:
            return path[len(d):]
    return ""


def select(m: M.Manifest, files: list, protected=()) -> T.Plan:
    """The pure core of plan(), on an already-loaded manifest. Tests call this."""
    pol = m.policy
    names, tip, owned, unowned, reached = set(), set(), [], [], {}
    builtin = M.builtin_check()
    tools_at = {}
    for n in m.checks:
        for p in m.checks[n].paths:
            t = tool_name(p)
            if t and "*" not in t:
                tools_at.setdefault(t, []).append(p)

    def owners(path):
        return [n for n in m.checks if m.owns(n, path)]

    for f in files:
        if M.match(builtin.paths, f):
            names.add(M.BUILTIN)
        mine = owners(f)
        if is_prose(f):   # design §0: "Prose reaches static only"
            names.update(n for n in mine if m.checks[n].klass == T.STATIC)
            continue
        if mine:
            owned.append(f)
            names.update(mine)
        elif not M.match(builtin.paths, f):
            unowned.append(f)
        t = tool_name(f)
        for caller in R.callers(m.reach, t) if t else []:
            for cp in tools_at.get(caller, []):
                for n in owners(cp):
                    if m.checks[n].klass != T.STATIC and n not in names:
                        reached.setdefault(n, f)
    names.update(reached)
    faults = list(m.faults)
    if unowned:
        for n in pol.default:
            if n in m.checks or n == M.BUILTIN:
                names.add(n)
            else:
                faults.append(f"default check {n!r} is not in the manifest")
    prot = list(pol.protected) + list(protected)
    lander = list(pol.lander) + [p + M.POLICY for p in M.PREFIXES]
    if any(M.match(prot, f) for f in files):
        klass = T.PROTECTED
    elif any(M.match(lander, f) for f in files):
        klass = T.LANDER
    elif any(M.match(pol.gate_first, f) for f in files):
        klass = T.GATE_FIRST
    elif files and all(is_prose(f) for f in files):
        klass = T.DOCS
    elif unowned:
        klass = T.WIDE
    else:
        klass = T.LEAF
    # design §0: box checks "never run pre-merge for an ordinary PR"; "Gate-first PRs keep them pre-merge"
    if klass != T.GATE_FIRST:
        tip = {n for n in names if n in m.checks and m.checks[n].klass == T.BOX}
        names -= tip
    extra = {"tip": sorted(tip), "reached": dict(sorted(reached.items()))}
    if faults:
        extra["faults"] = faults
    return T.Plan(checks=sorted(names), owned=owned, unowned=unowned, klass=klass,
                  paid=any(M.match(pol.paid_review, f) for f in files), extra=extra)


def plan(repo_root: str, base_sha: str, head_sha: str, files: list, protected=(), fallback: str = "") -> T.Plan:
    """Planner.plan. base_sha must carry a manifest that parses (else ManifestError); head_sha "" is the working
    copy. protected: the box's CC_PROTECTED_PATHS for this repo, which no tree may carry. fallback: a host manifest
    for a repo that ships none."""
    base = M.load(repo_root, base_sha, fallback=fallback)
    head = M.load(repo_root, head_sha, fallback=fallback, strict=False)
    return select(M.widen(base, head), list(files), protected)


def changed(repo_root: str, base: str, head: str) -> list:
    import subprocess
    argv = ["git", "-C", repo_root, "diff", "--name-only", "--no-renames", base] + ([head] if head else [])
    p = subprocess.run(argv, capture_output=True, text=True)
    files = p.stdout.split() if p.returncode == 0 else []
    if not head:   # untracked files are part of a working copy's change too
        q = subprocess.run(["git", "-C", repo_root, "ls-files", "--others", "--exclude-standard"],
                           capture_output=True, text=True)
        files += [f for f in q.stdout.split() if f not in files]
    return files


def cmd_plan(argv):
    repo, fb, pos = ".", "", []
    it = iter(argv)
    for k in it:
        if k in ("--repo", "--manifest"):
            v = next(it, "")
            repo, fb = (v, fb) if k == "--repo" else (repo, v)
        else:
            pos.append(k)
    if not 1 <= len(pos) <= 2:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    base, head = pos[0], (pos[1] if len(pos) == 2 else "")
    try:
        p = plan(repo, base, head, changed(repo, base, head), fallback=os.path.abspath(fb) if fb else "")
    except M.ManifestError as e:
        print(f"lander plan: the base's manifest does not parse: {e}", file=sys.stderr)
        return 1
    print(json.dumps(p.to_dict(), indent=1))
    return 0


COMMANDS = {"plan": (cmd_plan, "the checks a change reaches and its landing class (pure; prints JSON)")}
