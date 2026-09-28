"""The owner's ask ledger (cc-scope) after a landing: what merged, what still needs a person, and what was delivered.

    merged(project, track, evidence)   every ask on the track's rows goes MERGED, with the PR as evidence
    owner_ask(project, unit, src)      one `restart <unit>:` ask for a unit whose restart the owner keeps
                                       (cc-units policy restart=owner); never a second ask for the same unit
    deliver(repo, project, track)      runs each open ask's own check here. It is the LAST step of a deploy, so
                                       what it measures is the code the box is now running.

deliver's answer is (ok, line, unverified). cc-scope deliver exits 0 when the ask's check ran and passed, 2 when
the ask names no check, 3 when the check could not run (never measured, which is not red), anything else red. Any
ask not 0 is UNVERIFIED and stays open; the deploy says so rather than calling itself done.
"""
from __future__ import annotations

import json
import os
import shlex

from lander import cards as C

OWNER_ASK = ("restart {unit}: a landing changed the code it runs and config/units.json keeps its restart for you "
             "(restart=owner), so the box is on the old code until you run `{cmd}`")
DELIVER_OPEN = ("open", "claimed", "merged")


def tool():
    return os.path.join(C.BIN, "cc-scope")


def asks(project, track=""):
    """-> the ledger's rows (a list), or None when the project has no ledger."""
    argv = [tool(), "list", project] + (["--track", track] if track else []) + ["--json"]
    rc, out = C.sh(argv, timeout=300)
    if rc:
        return None
    try:
        rows = json.loads(out or "[]")
    except ValueError:
        return []
    return rows if isinstance(rows, list) else []


def merged(project, track, evidence):
    if not track:
        return ""
    rows = asks(project, track)
    if not rows:
        return ""
    done, bad = [], []
    for r in rows:
        rid = str(r.get("id", "")) if isinstance(r, dict) else ""
        if not rid:
            continue
        rc, out = C.sh([tool(), "merged", project, rid, "--evidence", evidence], timeout=60)
        (bad if rc else done).append(rid if not rc else f"{rid} ({out.strip()[-80:]})")
    line = f"ledger: {len(done)} ask(s) on {track} marked MERGED" if done else ""
    return line + (f"; could not mark {', '.join(bad)}" if bad else "")


def owner_ask(project, unit, src):
    """-> (asked, note). A unit that is not running needs no restart, so nobody is asked."""
    cmd = f"systemctl --user restart {shlex.quote(unit)}"
    rc, out = C.sh(["systemctl", "--user", "is-active", unit], timeout=60)
    if out.strip() in ("inactive", "failed"):
        return False, f"{unit} is {out.strip()}, so it needs no restart"
    key = f"restart {unit}:"
    for r in asks(project) or []:
        if isinstance(r, dict) and str(r.get("text", "")).startswith(key):
            return False, f"{unit}: already asked ({r.get('id', '?')})"
    rc, out = C.sh([tool(), "add", project, OWNER_ASK.format(unit=unit, cmd=cmd), "--who", "box", "--src", src],
                   timeout=60)
    if rc:
        return False, f"{unit}: the restart ask did not go on the ledger: {out.strip()[-120:]}"
    return True, f"{unit} (`{cmd}`)"


def deliver(repo, project, track):
    """-> (ok, line, unverified ids). No track or no open ask is (True, "", [])."""
    if not track:
        return True, "", []
    rows = [r for r in asks(project, track) or [] if isinstance(r, dict) and r.get("status") in DELIVER_OPEN]
    good, red, bare, silent = [], [], [], []
    for r in rows:
        rid = str(r.get("id", ""))
        rc, _ = C.sh([tool(), "deliver", repo, rid], timeout=900)
        {0: good, 2: bare, 3: silent}.get(rc, red).append(rid)
    if not rows:
        return True, "", []
    if not (red or bare or silent):
        return True, f"delivered — every check ran here and passed: {', '.join(good)}", []
    parts = [f"delivered: {', '.join(good) or 'none'}"]
    if red:
        parts.append(f"CHECK FAILED, still open: {', '.join(red)}")
    if silent:
        parts.append(f"COULD NOT RUN, never measured (not a red check): {', '.join(silent)}")
    if bare:
        parts.append(f"names no check, UNVERIFIED and still open: {', '.join(bare)}")
    return False, "; ".join(parts) + f" — `cc-scope unverified {repo}` lists them", red + silent + bare
