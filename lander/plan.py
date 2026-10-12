"""plan(): which checks a change reaches, and what kind of landing it is (design §0 Selection, §4; review S2, S3, S10).

PURE. It reads the manifest, policy and reach graph out of git at base_sha (and the head's, which may only widen:
manifest.widen) and returns a Plan. It writes nothing (a reach file's merge is written into a scratch repo that
git.sealed() removes), runs nothing and asks no network.

SELECTION, per changed file:
  - PROSE (is_prose, S10) reaches only the static checks that own it: docs/**, core/docs/**, *.pdf, images, and
    *.md — except under core/templates/**, templates/**, home/**, core/config/**, config/**, any agents/ directory,
    and any REVIEW.md, which are instructions, not prose.
  - every other path selects each check that owns it (its paths, fixtures or run file). A path no check owns is
    UNOWNED: the change widens to the policy's default_checks and Plan.unowned names it for the card.
  - a changed tool (a file under bin/, bin-private/ or core/bin/) also selects the non-static checks that own each
    of its direct callers in reach.tsv — one hop, never further.
  - a change to a manifest, policy or reach file selects the built-in manifest-widen check.
  - ADD-ONLY (owner, 2026-09-28: "a brand-new standalone tool that nothing calls should be live in minutes"): a change
    that only adds files, and modifies or deletes none, does not widen to default_checks for an unowned path, and is
    leaf rather than wide — nothing that exists can break by a file appearing next to it. Every check that OWNS an
    added path still runs, so under core/ the identity check (it owns core/**) runs as before, and the gate-first,
    lander and protected lists still decide the class. Except a path in GLOB_LOADED: something picks a file up there
    by its directory alone (a test runner, a hook, CI, units and environment.d, templates and instruction files,
    agents, skills, settings), so a new file there runs or configures something, and it widens as before.
    Plan.unowned still names every unowned path for the card; extra["add_only"] lists those that did not widen.
Plan.checks holds what runs BEFORE the merge. Box-class checks run on main's tip after it and are listed in
Plan.extra["tip"] instead — except for a gate-first change, which keeps them before the merge (owner, 2026-09-24).

KLASS, first match wins: protected (a policy protected glob, or the caller's `protected` list — CC_PROTECTED_PATHS
lives in the box's config, never in a tree) > lander (a policy lander glob, or the policy file itself — bar a
GENERATED reach file: one where every edge the change adds is one `lander reach` writes on merge-tree(base, head)
and every edge it drops is one it does not, so the change follows from the code and lands with it; an edge the code
does not make, or a change git cannot prove, stays lander, and a working copy proves nothing) > gate-first
> docs (every file prose) > wide (some path unowned, bar an add-only change's quiet ones) > leaf.
paid: some file matches paid_review, or UNGATED: some unowned path is code (anything but an added data or asset file,
inert()) and no check bar manifest-widen runs on the change, before the merge or after it (a repo with no manifest of
its own and no host fallback, or an add-only change nothing owns). Such a change is read instead of landing on
nothing, and extra["ungated"] says why it was paid.

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
DATA_EXT = (".json", ".csv", ".tsv", ".txt", ".yaml", ".yml", ".toml", ".xml", ".parquet", ".ico", ".woff",
            ".woff2", ".ttf", ".mp3", ".wav", ".mp4")
PROSE_DIRS = ("docs/**", "core/docs/**")
NOT_PROSE = ("core/templates/**", "templates/**", "home/**", "core/config/**", "config/**", "**/agents/**",
             "**/REVIEW.md")


GLOB_LOADED = ("tests/**", "core/tests/**", ".githooks/**", "core/.githooks/**", ".github/**", "core/.github/**",
               "config/**", "core/config/**", "templates/**", "core/templates/**", "home/**", "**/agents/**",
               "**/skills/**", "**/.claude/**", "slack/**", "core/slack/**")


def loads_by_nothing(path: str) -> bool:
    """A new file only stays quiet where nothing picks it up by place or by name. A top-level file (.mcp.json,
    .gitattributes, .envrc) or any dotfile or dot-directory is read by a tool by name, so it widens like GLOB_LOADED."""
    parts = path.split("/")
    return len(parts) > 1 and not any(x.startswith(".") for x in parts) and not M.match(GLOB_LOADED, path)


def is_prose(path: str) -> bool:
    """S10. Instruction files outrank the extension and the docs/ rule."""
    if M.match(NOT_PROSE, path):
        return False
    return M.match(PROSE_DIRS, path) or path.lower().endswith(PROSE_EXT)


def inert(path: str, added=()) -> bool:
    """An added file that is not code: data or an asset (DATA_EXT, or prose's extensions outside the instruction
    paths) in a place nothing loads by place or name. An ungated change made only of these, and prose, is not read."""
    return (path in added and loads_by_nothing(path) and not M.match(NOT_PROSE, path)
            and path.lower().endswith(DATA_EXT + PROSE_EXT))


def tool_name(path: str) -> str:
    for d in M.TOOL_DIRS:
        if path.startswith(d) and "/" not in path[len(d):]:
            return path[len(d):]
    return ""


def select(m: M.Manifest, files: list, protected=(), added=(), generated=()) -> T.Plan:
    """The pure core of plan(), on an already-loaded manifest. Tests call this. added: the files in `files` that do
    not exist at the base (plan() works it out); when every file is one, the change is add-only. generated: the reach
    files in `files` whose change agrees with the generator on the merge tree (plan() works it out); they do not
    make the change lander-class."""
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
    add_only = bool(files) and set(files) <= set(added)
    quiet = [f for f in unowned if add_only and loads_by_nothing(f)]
    widening = [f for f in unowned if f not in quiet]
    if widening:
        for n in pol.default:
            if n in m.checks or n == M.BUILTIN:
                names.add(n)
            else:
                faults.append(f"default check {n!r} is not in the manifest")
    prot = list(pol.protected) + list(protected)
    lander = list(pol.lander) + [p + M.POLICY for p in M.PREFIXES]
    if any(M.match(prot, f) for f in files):
        klass = T.PROTECTED
    # brief: "a reach.tsv change that exactly matches what the generator writes on the PR's merge tree follows from
    # the code, so it's not a policy edit"; "a reach.tsv edit that doesn't match the generator still goes to
    # lander-self".
    # Matched edge by edge (generated_change), so drift main already carries does not stop a PR that adds its own.
    elif any(M.match(lander, f) for f in files if f not in generated):
        klass = T.LANDER
    elif any(M.match(pol.gate_first, f) for f in files):
        klass = T.GATE_FIRST
    elif files and all(is_prose(f) for f in files):
        klass = T.DOCS
    elif widening:
        klass = T.WIDE
    else:
        klass = T.LEAF
    # design §0: box checks "never run pre-merge for an ordinary PR"; "Gate-first PRs keep them pre-merge"
    if klass != T.GATE_FIRST:
        tip = {n for n in names if n in m.checks and m.checks[n].klass == T.BOX}
        names -= tip
    extra = {"tip": sorted(tip), "reached": dict(sorted(reached.items()))}
    # finding 10-04 (raised-member-pr-lands-with-no-checks): fund#2 "merged ... about 4 seconds after it was queued"
    # with "plan checks [], results {}, review_key ''" because the repo has no check map. Code that no check runs on,
    # before the merge or after it, is read instead: the plan is paid, so the lane buys a review.
    # planning 10-12: "add-only files that aren't code (docs, data, assets) need no paid read, but any unowned code
    # path, added or changed, does". manifest-widen is padding here: it reads the manifest, never the code.
    ungated = any(not inert(f, added) for f in unowned) and not (names - {M.BUILTIN}) and not tip
    if ungated:
        extra["ungated"] = True
    if quiet:
        extra["add_only"] = quiet
    if faults:
        extra["faults"] = faults
    return T.Plan(checks=sorted(names), owned=owned, unowned=unowned, klass=klass,
                  paid=ungated or any(M.match(pol.paid_review, f) for f in files), extra=extra)


def plan(repo_root: str, base_sha: str, head_sha: str, files: list, protected=(), fallback: str = "") -> T.Plan:
    """Planner.plan. base_sha must carry a manifest that parses (else ManifestError); head_sha "" is the working
    copy. protected: the box's CC_PROTECTED_PATHS for this repo, which no tree may carry. fallback: a host manifest
    for a repo that ships none. Ungated code (select) is judged on the base's checks alone, never the head's."""
    base = M.load(repo_root, base_sha, fallback=fallback)
    head = M.load(repo_root, head_sha, fallback=fallback, strict=False)
    files = list(files)
    added = added_files(repo_root, base_sha, head_sha, files)
    generated = generated_reach(repo_root, base_sha, head_sha, files)
    p = select(M.widen(base, head), files, protected, added, generated)
    # perms 10-12: "the lane can't build its plan from the PR's own head LANDING.toml". Whether code is ungated is
    # the base's word: a check the head adds (run = 'true' over **) would otherwise make it look gated, and unpaid.
    if not p.extra.get("ungated") and select(base, files, protected, added, generated).extra.get("ungated"):
        p.paid, p.extra["ungated"] = True, True
    return p


def generated_reach(repo_root: str, base: str, head: str, files: list) -> set:
    """The reach files among `files` whose change from base to merge-tree(base, head) agrees with the generator on
    that tree (reach.generated_change), all of it read in git.sealed(). A working copy (head ""), a sealed repo git
    cannot make, a merge that conflicts or git failing is the empty set: a reach file is generated only when git
    proves it."""
    wanted = [p for p in M.PREFIXES if p + M.REACH in files]
    if not wanted or not head:
        return set()
    from lander import git as G
    try:
        # every read, the merge included, in a sealed repo: a replace ref, graft or merge driver of the checkout's
        # could otherwise show the generator code the PR does not carry
        with G.sealed(repo_root, base, head) as ((rc, out), run):
            if run is None:
                return set()
            b, h = out
            rc, merged = run("merge-tree", "--write-tree", "--name-only", "--no-messages", "-z", b, h, timeout=300)
            tree = merged.split("\0")[0].strip() if rc == 0 else ""
            if not G.SHA_RE.fullmatch(tree):
                return set()   # a conflict, or git failing: nothing is proven
            return {p + M.REACH for p in wanted if R.generated_change(run, b, tree, p)}
    except Exception:  # noqa: BLE001 — git missing, a timeout, anything: nothing is proven
        return set()


def added_files(repo_root: str, base: str, head: str, files: list) -> set:
    """The files that are not in base's tree and are in head's (head "" = the working copy). Git failing is the
    empty set: a change is add-only only when git says so. Each tree is read VERIFIED (git.py)."""
    from lander import git as G
    files = list(files)
    if not files:
        return set()
    try:
        at_base = G.paths_in(repo_root, base, files)
        at_head = G.paths_in(repo_root, head, files) if head else \
            {f for f in files if os.path.lexists(os.path.join(repo_root, f))}
    except G.GitError:
        return set()
    return {f for f in files if f not in at_base and f in at_head}


def changed(repo_root: str, base: str, head: str) -> list:
    """Every path between base and head (head "" is the working copy: tracked and untracked, not ignored), each as it
    is. No git runs in the checkout with its config: the revs are read VERIFIED, the working copy is hashed and the
    diff taken FENCED (git.worktree_tree, git.fenced_names), since `lander check` may be on a fenced worker's tree,
    run as the owner, and a filter or include.path git read there would run whatever a -c core.hooksPath pins. A root that is not
    a checkout the host made, or a tree that cannot be taken, RAISES: an empty list reads as "nothing changed,
    nothing to check", which is a false green."""
    from lander import git as G
    t = G.host_tree(repo_root)
    if t.refused:
        raise G.GitError(f"{t.refused} is not a checkout the host made with the host's empty config.worktree — git "
                         "there would run a filter or include it names as the owner")
    a = G.tree_of(repo_root, base)
    b = G.tree_of(repo_root, head) if head else G.worktree_tree(t)
    if not b:
        raise G.GitError(f"no tree could be taken of the working copy at {repo_root}")
    return G.fenced_names(t, a, b)


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
    from lander import git as G
    try:
        p = plan(repo, base, head, changed(repo, base, head), fallback=os.path.abspath(fb) if fb else "")
    except M.ManifestError as e:
        print(f"lander plan: the base's manifest does not parse: {e}", file=sys.stderr)
        return 1
    except G.GitError as e:
        print(f"lander plan: refused: {e}", file=sys.stderr)
        return 1
    print(json.dumps(p.to_dict(), indent=1))
    return 0


COMMANDS = {"plan": (cmd_plan, "the checks a change reaches and its landing class (pure; prints JSON)")}
