"""`lander check`: a worker's own green, by the plan (review: cc-green's use of GATES moves here); `lander sweep`: every
check once, the nightly full run and the sandbox acceptance table (B2d).

    lander check [WORKTREE] [--base REV] [--manifest FILE] [--only NAME]…
        Plans the worktree's change against its base (default: the merge-base with origin/HEAD, origin/main or main)
        — the working copy as it stands, untracked files included — and runs each check the plan selects, the same
        way the lane will: same runner, same sandbox, same red-vs-base rule. Box-class checks are listed, not run:
        they run on main's tip after the merge. Nothing is stored and nothing goes to the failures ledger: a
        worker's own red is its work. Exit 0 green (a check red on the base too is main's, and is said, not held
        against the change), 1 some check red, 3 no verdict (a check could not run), 2 usage.

    lander sweep [--repo DIR] [--rev REV] [--manifest FILE] [--only NAME]… [--sandbox] [--jobs N]
        Runs every check in the manifest at REV (default HEAD) once, each on its own class's runner, and prints a
        table. --sandbox runs every one in the bwrap profile whatever its class and runs a red one again on the host
        to say which it is: passes-in-bwrap, needs-mount (green on the host, and the sandbox's red names a missing
        path), host (green only on the host), red (red on the host too) or unrunnable. Exit 0 when every check
        passed on the runner the table names for it.
"""
from __future__ import annotations

import concurrent.futures
import dataclasses
import os
import re
import subprocess
import sys

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
    for ref in ("origin/HEAD", "origin/main", "main", "master"):
        p = subprocess.run(["git", "-C", wt, "merge-base", "HEAD", ref], capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    return ""


def usage(doc_part: int) -> int:
    print(__doc__.split("\n\n")[doc_part].strip(), file=sys.stderr)
    return EXIT_USAGE


def cmd_check(argv):
    try:
        a, pos = _opts(argv, ("--base", "--manifest", "--only"))
    except ValueError as e:
        print(f"lander check: {e}", file=sys.stderr)
        return usage(1)
    if len(pos) > 1:
        return usage(1)
    wt = os.path.abspath(pos[0] if pos else ".")
    base = a["--base"] or default_base(wt)
    base_tree, head_tree = RUN.tree_of(wt, base), RUN.tree_of(wt, "")
    if not base_tree or not head_tree:
        print(f"lander check: {wt} is not a git checkout with a base to compare against", file=sys.stderr)
        return EXIT_USAGE
    fb = os.path.abspath(a["--manifest"]) if a["--manifest"] else ""
    try:
        m = M.widen(M.load(wt, base, fallback=fb), M.load(wt, head_tree, fallback=fb, strict=False))
    except M.ManifestError as e:
        print(f"lander check: the base's manifest does not parse: {e}", file=sys.stderr)
        return EXIT_NONE
    files = P.changed(wt, base, "")
    plan = P.select(m, files)
    print(f"lander check: {len(files)} file(s) changed, {len(plan.checks)} check(s), class {plan.klass}"
          + (f", unowned: {', '.join(plan.unowned)}" if plan.unowned else ""))
    for n in plan.extra.get("tip", []):
        print(f"  tip      {n} — runs on main's tip after the merge")
    for f in plan.extra.get("faults", []):
        print(f"  fault    {f}")
    outs = RUN.run_plan(wt, m, plan, files, head_tree, base_tree, only=a["--only"] or None, record_reds=False,
                        quarantine_text=RUN.quarantine_text(wt, base))
    return report(outs)


def report(outs: dict) -> int:
    worst = EXIT_GREEN
    for name, o in sorted(outs.items()):
        r = o.results[0] if o.results else None
        secs = f"{r.secs:.0f}s" if r else ""
        word = {T.PASSED: "passed", T.FAILED: "RED", T.UNRUNNABLE: "no-run", RUN.BLOCKED: "main-red"}[o.status]
        print(f"  {word:<8} {name} {secs}" + (f" — {o.note}" if o.note else ""))
        if o.status == T.FAILED:
            worst = EXIT_RED
            for ln in (o.results[-1].extra.get("tail") or [])[-12:]:
                print(f"           | {ln}")
        elif o.status == T.UNRUNNABLE and worst == EXIT_GREEN:
            worst = EXIT_NONE
    print(f"lander check: {sum(o.status == T.PASSED for o in outs.values())} passed, "
          f"{sum(o.status == T.FAILED for o in outs.values())} failed")
    return worst


# --- sweep ---------------------------------------------------------------------------------------------------------

MISSING_RE = re.compile(r"No such file or directory|not found|command not found|cannot open|ModuleNotFoundError"
                        r"|No module named|does not exist")


def sweep_one(repo: str, m: M.Manifest, name: str, tree: str, sandbox: bool, runner=None) -> dict:
    runner = runner or RUN.run
    c, cwd = m.checks[name], m.cwd.get(name, "")
    if sandbox and c.klass != T.STATIC:
        c = dataclasses.replace(c, klass=T.HERMETIC)
    r = runner(c, tree, "box", repo_root=repo, cwd=cwd)
    row = {"check": name, "class": m.checks[name].klass, "status": r.status, "secs": round(r.secs),
           "why": r.extra.get("why", ""), "verdict": ""}
    if not sandbox:
        row["verdict"] = r.status
        return row
    if r.status == T.PASSED:
        row["verdict"] = "passes-in-bwrap"
        return row
    h = runner(dataclasses.replace(c, klass=T.HOST, mounts=[]), tree, "box", repo_root=repo, cwd=cwd)
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
    repo = os.path.abspath(a["--repo"] or ".")
    rev = a["--rev"] or "HEAD"
    tree = RUN.tree_of(repo, rev)
    fb = os.path.abspath(a["--manifest"]) if a["--manifest"] else ""
    try:
        m = M.load(repo, rev, fallback=fb)
    except M.ManifestError as e:
        print(f"lander sweep: the manifest does not parse: {e}", file=sys.stderr)
        return EXIT_NONE
    names = [n for n in m.checks if not a["--only"] or n in a["--only"]]
    jobs = int(a["--jobs"] or 3)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        rows = list(ex.map(lambda n: said(sweep_one(repo, m, n, tree, a["--sandbox"])), names))
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
