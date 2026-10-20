"""`lander check`: a worker's own green, by the plan (review: cc-green's use of GATES moves here); `lander sweep`: every
check once, the nightly full run and the sandbox acceptance table (B2d).

    lander check [WORKTREE] [--base REV] [--manifest FILE] [--only NAME]… [--caged-only]
        Plans the worktree's change against its base (default: the merge-base with origin/HEAD, origin/main or main)
        — the working copy as it stands, untracked files included — and runs each check the plan selects, the same
        way the lane will: same runner, same sandbox, same red-vs-base rule. Box-class checks are listed, not run:
        they run on main's tip after the merge. Nothing is stored and nothing goes to the failures ledger: a
        worker's own red is its work. Exit 0 green (a check red on the base too is main's, and is said, not held
        against the change), 1 some check red — each red with its tail, the line that names its cause and the path
        of its full log, which outlives the run (run.keep_log) — 3 no verdict (a check could not run), 2 usage. A repo that ships no
        manifest is checked by the release's tests/landing-repos/<repo>.toml (manifest.host_fallback), as the lane
        does; --manifest FILE names another. --caged-only runs only the checks that run whole in the bwrap profile on
        this box: a host- or box-class check, or one that needs the network, a mount or another runner, is not run
        and is said as `deferred — runs at landing`, never as passed, and the last line says the green is not a full
        one. cc-green's run for a fenced worker always passes it (the tree is one the worker wrote).

    lander sweep [--repo DIR] [--rev REV] [--manifest FILE] [--only NAME]… [--sandbox] [--jobs N]
        Runs every check in the manifest at REV (default HEAD) once, each on its own class's runner, and prints a
        table. --sandbox runs every one in the bwrap profile whatever its class and runs a red one again on the host
        to say which it is: passes-in-bwrap, needs-mount (green on the host, and the sandbox's red names a missing
        path), host (green only on the host), red (red on the host too) or unrunnable. REV is resolved to one commit
        first, and the manifest, the tree and the host re-run's test are all of it. The host re-run happens only when
        that commit is the one origin sends for main when sweep fetches it (never the local origin/main ref, which a
        worker can move); for any other REV, or when the fetch fails, a sandbox-red check is reported red, never run
        on the host. A REV that names no commit is a usage error. Exit 0 when every check passed on the runner the
        table names for it.
"""
from __future__ import annotations

import concurrent.futures
import dataclasses
import os
import re
import sys

from lander import git as G
from lander import manifest as M
from lander import plan as P
from lander import run as RUN
from lander import types as T

EXIT_GREEN, EXIT_RED, EXIT_USAGE, EXIT_NONE = 0, 1, 2, 3


def _opts(argv, flags, multi=("--only",), bools=()):
    a, pos = {k: ([] if k in multi else "") for k in flags}, []
    a.update({b: False for b in bools})
    it = iter(argv)
    for k in it:
        if k in bools:
            a[k] = True
        elif k in flags:
            v = next(it, None)
            if v is None:
                raise ValueError(f"{k} takes a value")
            if k in multi:
                a[k].append(v)
            else:
                a[k] = v
        elif k.startswith("-"):
            raise ValueError(f"unknown option {k}")
        else:
            pos.append(k)
    return a, pos


def default_base(wt: str) -> str:
    """The merge-base of the tree's HEAD and the first of origin's HEAD, origin/main, main and master it names, by
    git.merge_base: every ref read as files and merge-base run sealed, so no git opens the worker's config.worktree
    (an include.path FIFO there hung `merge-base` run in the tree) and no object it rewrote steers the base."""
    t = G.host_tree(wt)
    for ref in ("refs/remotes/origin/HEAD", "refs/remotes/origin/main", "main", "master"):
        b = G.merge_base(t, "HEAD", ref)
        if b:
            return b
    return ""


def repo_name(wt: str) -> str:
    """The repo a worktree belongs to: the directory holding its main gitdir (~/dev/<repo>/.git -> <repo>), which is
    the name the lane knows it by and host_fallback looks it up under. Read off git.host_tree, so no git runs."""
    t = G.host_tree(wt)
    return "" if t.refused else os.path.basename(os.path.dirname(t.common))


def host_top(path: str):
    """git.host_tree of path or the nearest directory above it that the host made, by host_tree alone (no git
    discovery): `lander sweep --repo <subdir>` on the owner's own checkout still finds its top."""
    p = os.path.realpath(path)
    while True:
        t = G.host_tree(p)
        if not t.refused or os.path.dirname(p) == p:
            return t
        p = os.path.dirname(p)


def usage(doc_part: int) -> int:
    print(__doc__.split("\n\n")[doc_part].strip(), file=sys.stderr)
    return EXIT_USAGE


def cmd_check(argv):
    if hasattr(sys.stdout, "reconfigure"):   # a worker's log (cc-green) shows each line as it is said, not at exit
        sys.stdout.reconfigure(line_buffering=True)
    try:
        a, pos = _opts(argv, ("--base", "--manifest", "--only"), bools=("--caged-only",))
    except ValueError as e:
        print(f"lander check: {e}", file=sys.stderr)
        return usage(1)
    caged = a["--caged-only"]
    if len(pos) > 1:
        return usage(1)
    wt = os.path.abspath(pos[0] if pos else ".")
    # Before any git call on the tree, it must be one the host made (git.host_tree): git takes a sub/.git a worker
    # planted for a repo (its config read) or climbs past it to the worktree, so a subdirectory's default "." is
    # refused rather than resolved by a git call. A config.worktree that is not the host's runs its filters and
    # includes on the first `add -A`, as the owner, whatever a -c core.hooksPath pins: refused with no verdict, never repaired.
    t = G.host_tree(wt)
    if t.refused and os.path.basename(t.refused) == "config.worktree":
        print(f"lander check: refused — {t.refused} is not the host's empty file, so git here would run what it says "
              "as the owner. No tree was taken and no check ran; take this to the owner.", file=sys.stderr)
        return EXIT_NONE
    if t.refused:
        print(f"lander check: {wt} is not a checkout's top directory that the host made ({t.refused} is not one it "
              "registered), so git there could read a config a worker wrote; run it on the root of your worktree "
              "(`git rev-parse --show-toplevel`).", file=sys.stderr)
        return EXIT_USAGE
    base = a["--base"] or default_base(wt)
    base_tree, head_tree = RUN.tree_of(wt, base), RUN.tree_of(wt, "")
    if not base_tree or not head_tree:
        print(f"lander check: {wt} is not a git checkout with a base to compare against", file=sys.stderr)
        return EXIT_USAGE
    fb = os.path.abspath(a["--manifest"]) if a["--manifest"] else M.host_fallback(repo_name(wt))
    try:
        m = M.widen(M.load(wt, base, fallback=fb), M.load(wt, head_tree, fallback=fb, strict=False))
    except M.ManifestError as e:
        print(f"lander check: the base's manifest does not parse: {e}", file=sys.stderr)
        return EXIT_NONE
    try:
        files = P.changed(wt, base, "")
    except G.GitError as e:
        print(f"lander check: no change list could be taken of {wt}: {e}", file=sys.stderr)
        return EXIT_NONE
    plan = P.select(m, files)
    print(f"lander check: {len(files)} file(s) changed, {len(plan.checks)} check(s), class {plan.klass}"
          + (f", unowned: {', '.join(plan.unowned)}" if plan.unowned else ""))
    if caged:
        print("lander check: caged only — host, box, network, mount and remote checks are deferred to the landing")
    for n in plan.extra.get("tip", []):
        print(f"  tip      {n} — runs on main's tip after the merge")
    for f in plan.extra.get("faults", []):
        print(f"  fault    {f}")
    outs = RUN.run_plan(wt, m, plan, files, head_tree, base_tree, only=a["--only"] or None, record_reds=False,
                        quarantine_text=RUN.quarantine_text(wt, base), fallback=fb,
                        **({"caged": True, "box_only": True} if caged else {}))
    return report(outs)


def report(outs: dict) -> int:
    worst = EXIT_GREEN
    for name, o in sorted(outs.items()):
        r = o.results[0] if o.results else None
        secs = f"{r.secs:.0f}s" if r else ""
        word = {T.PASSED: "passed", T.FAILED: "RED", T.UNRUNNABLE: "no-run", RUN.BLOCKED: "main-red",
                RUN.DEFERRED: "deferred"}[o.status]
        print(f"  {word:<8} {name} {secs}" + (f" — {o.note}" if o.note else ""))
        if o.status == T.FAILED:
            worst = EXIT_RED
            last = o.results[-1].extra
            for ln in (last.get("tail") or [])[-12:]:
                print(f"           | {ln}")
            if last.get("cause"):
                print(f"           cause: {last['cause']}")
            if last.get("log"):
                print(f"           full log: {last['log']}")
        elif o.status == T.UNRUNNABLE and worst == EXIT_GREEN:
            worst = EXIT_NONE
    deferred = sum(o.status == RUN.DEFERRED for o in outs.values())
    print(f"lander check: {sum(o.status == T.PASSED for o in outs.values())} passed, "
          f"{sum(o.status == T.FAILED for o in outs.values())} failed"
          + (f", {deferred} deferred to the landing — caged checks only, NOT a full green" if deferred else ""))
    return worst


# --- sweep ---------------------------------------------------------------------------------------------------------

MISSING_RE = re.compile(r"No such file or directory|not found|command not found|cannot open|ModuleNotFoundError"
                        r"|No module named|does not exist")


def commit_of(t, rev: str) -> str:
    """The full commit id rev names in Tree t (read by git._name, no git opens the checkout's config), or "" when it
    names none. cmd_sweep resolves --rev once, so the main compare, the manifest and the tree are of one commit."""
    if t.refused:
        return ""
    with G.fenced(t, bare=True) as env:
        rc, got = G._name(t, env, rev + "^{commit}")
    return got if rc == 0 else ""


def rev_is_main(t, sha: str, fetch=None) -> bool:
    """True when sha is the commit origin itself sends for main now (G.fetch's own report, never
    refs/remotes/origin/main, which a worker or a member's clone can move). A fetch that fails is not main."""
    if t.refused or not G.SHA_RE.fullmatch(sha or ""):
        return False
    try:
        main = (fetch or G.fetch)(t.work_tree, "main")["main"]
    except G.GitError:   # perms, 10-20: "a GitError means 'not main', so refuse the host rerun"
        return False
    return sha == main


def sweep_one(repo: str, m: M.Manifest, name: str, tree: str, sandbox: bool, runner=None,
              host_rerun: bool = True) -> dict:
    runner = runner or RUN.run
    o, cwd = m.checks[name], m.cwd.get(name, "")
    c = o
    if sandbox and c.klass != T.STATIC:
        # bare only drops cc-nosignal from a host run; inside bwrap it means nothing, so the bwrap try clears it
        c = dataclasses.replace(c, klass=T.HERMETIC, bare=False)
    r = runner(c, tree, "box", repo_root=repo, cwd=cwd)
    row = {"check": name, "class": m.checks[name].klass, "status": r.status, "secs": round(r.secs),
           "why": r.extra.get("why", ""), "verdict": ""}
    if not sandbox:
        row["verdict"] = r.status
        return row
    if r.status == T.PASSED:
        row["verdict"] = "passes-in-bwrap"
        return row
    if not host_rerun:   # unread code (REV is not origin's main) never runs on the host, as the owner
        row["verdict"] = "red"
        row["why"] = ("failed in the sandbox; host re-run refused, --rev is not origin's main | "
                      + (r.extra.get("why", "") or next((ln for ln in reversed(r.extra.get("tail", []))
                                                       if ln.strip()), "")))[:160]
        return row
    h = runner(dataclasses.replace(o, klass=T.HOST, mounts=[], where=["box"]), tree, "box", repo_root=repo, cwd=cwd)
    tail = "\n".join(r.extra.get("tail", []))
    home = os.path.expanduser("~")
    if h.status == T.PASSED:
        row["verdict"] = "needs-mount" if (home in tail or MISSING_RE.search(tail)) else "host"
    else:
        row["verdict"] = "red" if h.status == T.FAILED else "unrunnable"
    row["why"] = (r.extra.get("why", "") + " | " + next((ln for ln in reversed(r.extra.get("tail", []))
                                                          if ln.strip()), ""))[:160]
    return row


def said(row: dict) -> dict:
    """One line per check on stderr as it finishes, so a long sweep shows how far it has got."""
    print(f"lander sweep: {row['check']} {row['verdict']} {row['secs']}s", file=sys.stderr, flush=True)
    return row


def cmd_sweep(argv):
    try:
        a, pos = _opts(argv, ("--repo", "--rev", "--manifest", "--only", "--jobs"), bools=("--sandbox",))
    except ValueError as e:
        print(f"lander sweep: {e}", file=sys.stderr)
        return usage(2)
    if pos:
        return usage(2)
    t = host_top(a["--repo"] or ".")
    if t.refused:
        print(f"lander sweep: {os.path.abspath(a['--repo'] or '.')} is in no checkout the host made", file=sys.stderr)
        return usage(2)
    repo = t.work_tree
    rev = a["--rev"] or "HEAD"
    sha = commit_of(t, rev)
    if not sha:
        print(f"lander sweep: --rev {rev} names no commit", file=sys.stderr)
        return usage(2)
    tree = RUN.tree_of(repo, sha)
    fb = os.path.abspath(a["--manifest"]) if a["--manifest"] else M.host_fallback(repo_name(repo))
    try:
        m = M.load(repo, sha, fallback=fb)
    except M.ManifestError as e:
        print(f"lander sweep: the manifest does not parse: {e}", file=sys.stderr)
        return EXIT_NONE
    names = [n for n in m.checks if not a["--only"] or n in a["--only"]]
    jobs = int(a["--jobs"] or 3)
    rerun = rev_is_main(t, sha) if a["--sandbox"] else True
    if a["--sandbox"] and not rerun:
        print(f"lander sweep: --rev {rev} is not the commit origin sends for main: a check red in the sandbox is "
              "reported red, not re-run on the host", file=sys.stderr)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        rows = list(ex.map(lambda n: said(sweep_one(repo, m, n, tree, a["--sandbox"], host_rerun=rerun)), names))
    print("| check | class | verdict | secs | why |\n|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['check']} | {r['class']} | {r['verdict']} | {r['secs']} | {r['why'].replace('|', '/')} |")
    ok = {"passes-in-bwrap", "needs-mount", "host", T.PASSED}
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("lander sweep: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    return EXIT_GREEN if all(r["verdict"] in ok for r in rows) else EXIT_RED


COMMANDS = {
    "check": (cmd_check, "a worker's own green: plan the worktree's change and run what it selects"),
    "sweep": (cmd_sweep, "run every check once (nightly); --sandbox gives the bwrap acceptance table"),
}
