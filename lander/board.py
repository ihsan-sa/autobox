"""The board after a merge: the track's row, the rows the PR says it closes, and one follow-up row for advice.

    track_of(project, pr, head_ref)  the board row a PR came from: the row whose `pr` is this PR, else the row whose
                                     `branch` is the head branch, else `track/<row>`, `planning/<row>` or
                                     `builder/<row>` naming a row; "" when none does
    close(job)                       the row goes `merged` with a note, unless an orch holds it (then a note only);
                                     every row the PR body names with `Closes <row>` goes `done` (same board only)
    followup(job, verdict)           one `review-followup-pr<N>` row carrying the review's advisory findings

close() also files the follow-up row for the verdict review() bought at the job's digest, and marks the track's
cc-scope asks MERGED (scope.merged), so the lane's one call after a merge does all three.

CLOSES RULES. `Closes a, b and c` in the PR body (capital C). A row is skipped when it is the PR's own row or already
merged/done; LEFT OPEN when a person holds it (`held`) or it is running/in review with no agent mark, since nobody's
track will finish it then; closed `done` with a note and its agent mark cleared otherwise. A name with a dash, digit
or underscore that is not on the board is reported; a bare word ("Closes the gap") is prose and ignored.

Nothing here raises: a board write that fails is a line in the answer, and the merge already happened. The job's
`extra` supplies `branch` (or the older `head_ref`), `title`, `body` and, when U1 set them, `project` (the board's name; the repo by default)
and `track`.
"""
from __future__ import annotations

import os
import re

from lander import cards as C

CLOSES_RE = re.compile(r"\bCloses:?\s+([A-Za-z0-9][A-Za-z0-9_-]*(?:\s*(?:,\s*(?:and\s+)?|\s+and\s+)"
                       r"[A-Za-z0-9][A-Za-z0-9_-]*)*)")
CLOSES_SPLIT = re.compile(r"\s*,\s*(?:and\s+)?|\s+and\s+")
BRANCH_RE = re.compile(r"^(?:track|planning|builder)/(.+)$")
ORCH_MARK = re.compile(r"^@\d+$")


def tool(name):
    return os.path.join(C.BIN, name)


def rows(project):
    """The board's tracks; {} for a symlinked board file (a member's board could link into a dir the member writes)."""
    p = os.path.join(os.path.expanduser(C.conf("CC_BOARDS", "~/.cc/boards")), f"{project}.json")
    if os.path.islink(p):
        return {}
    d = C.read_json(p, {})
    t = (d or {}).get("tracks")
    return t if isinstance(t, dict) else {}


def pr_matches(value, pr):
    v = str(value or "")
    return v == str(pr) or bool(re.search(rf"/pull/{int(pr)}(?:/|$)", v))


def track_of(project, pr, head_ref=""):
    tracks = rows(project)
    for name, r in tracks.items():
        if isinstance(r, dict) and pr_matches(r.get("pr"), pr):
            return name
    for name, r in tracks.items():
        if head_ref and isinstance(r, dict) and r.get("branch") == head_ref:
            return name
    m = BRANCH_RE.match(head_ref or "")
    return m.group(1) if m and m.group(1) in tracks else ""


def project_of(job):
    return job.extra.get("project") or job.member or job.repo


def track_for(job):
    """The job's row: U1's `track`, a member landing's own <t> (repo `<h>--<t>`), else looked up by PR and by the head
    branch (the lane keeps it as `branch`; `head_ref` is the older name)."""
    if job.extra.get("track"):
        return job.extra["track"]
    if job.member and "--" in job.repo:
        return job.repo.partition("--")[2]
    return track_of(project_of(job), job.pr, job.extra.get("branch") or job.extra.get("head_ref") or "")


def what(job):
    t = job.extra.get("title", "")
    return f"PR #{job.pr}" + (f" {t}" if t else "")


def orch_of(repo, agent):
    """The orch window holding a row: its agent mark is `@<window id>:<pid>` and that window is `<repo>@<alias>`."""
    wid = (agent or "").strip().split(":")[0]
    if not ORCH_MARK.fullmatch(wid):
        return ""
    rc, out = C.sh(["tmux", "list-windows", "-t", "main", "-F", "#{window_id}\t#{window_name}"], timeout=60)
    for ln in out.splitlines() if rc == 0 else []:
        w, _, name = ln.partition("\t")
        if w == wid and re.fullmatch(rf"{re.escape(repo)}@[a-z0-9-]{{2,20}}", name):
            return name
    return ""


def closes(body):
    out = []
    for m in CLOSES_RE.finditer(body or ""):
        for r in CLOSES_SPLIT.split(m.group(1)):
            if r and r != "and" and r not in out:
                out.append(r)
    return out


def close(job):
    """-> one line for the card. After a merge: the review's advice row, the track's cc-scope asks to MERGED, the
    PR's row and the rows it Closes. Never raises."""
    from lander import review, scope
    project, track = project_of(job), track_for(job)
    tail = [x for x in (followup(job, review.saved(job.digest)), scope.merged(project, track, what(job))) if x]
    line = _close(job, project, track)
    return "; ".join([line] + tail)


def _close(job, project, track):
    if not track:
        return "board: this PR is no board row's"
    tracks = rows(project)
    row = tracks.get(track)
    if not isinstance(row, dict):
        return f"board: {project}/{track} is not on the board"
    b = tool("cc-board")
    orch = orch_of(project, row.get("agent", ""))
    if orch:
        C.sh([b, "note", project, track, f"milestone landed by the lander: {what(job)}; left open, {orch} holds this row"],
             timeout=60)
        line = f"board: {project}/{track} left open for {orch}"
    else:
        rc, out = C.sh([b, "status", project, track, "merged"], timeout=60)
        if rc:
            return f"board: cc-board status {track} failed: {out.strip()[-200:]}"
        C.sh([b, "note", project, track, f"landed by the lander: {what(job)}"], timeout=60)
        line = f"board: {project}/{track} -> merged"
    shut, held, unknown = [], [], []
    for r in closes(job.extra.get("body", "")):
        cur = tracks.get(r)
        if r == track or (isinstance(cur, dict) and cur.get("status") in ("merged", "done")):
            continue
        if not isinstance(cur, dict):
            if re.search(r"[-_0-9]", r):
                unknown.append(r)
            continue
        mark = str(cur.get("agent") or "").strip()
        if cur.get("held") or (cur.get("status") in ("running", "review") and not mark):
            held.append(r)
            continue
        rc, out = C.sh([b, "status", project, r, "done"], timeout=60)
        if rc:
            line += f"; cc-board status {r} failed: {out.strip()[-120:]}"
            continue
        C.sh([b, "note", project, r, f"closed by the lander: {what(job)} says Closes {r}"], timeout=60)
        if mark:
            C.sh([b, "set", project, r, "agent", ""], timeout=60)
        shut.append(r)
    if shut:
        line += f"; closes {', '.join(shut)}"
    if held:
        line += f" (held by a person or live on a track, left open: {', '.join(held)})"
    if unknown:
        line += f" (Closes names no row on the board: {', '.join(unknown)})"
    return line


def followup(job, verdict):
    """One row for a LAND's advisory findings, once per PR. -> a line, "" when there was nothing to file."""
    if verdict is None or not verdict.advisory:
        return ""
    project, row = project_of(job), f"review-followup-pr{job.pr}"
    b = tool("cc-board")
    rc, out = C.sh([b, "get", project, row, "status"], timeout=60)
    if rc == 0 and out.strip():
        return f"its review findings are already board row {row}"
    said = "\n".join(f"{i}. {a}" for i, a in enumerate(verdict.advisory, 1))
    brief = (f"GOAL: the review's non-blocking findings on {what(job)} are answered on main. WHY: the landing review "
             f"said LAND with advice that blocks nothing, so the PR landed and the advice came here.\nFINDINGS:\n{said}")
    rc, out = C.sh([b, "add", project, row, f"review follow-up for PR #{job.pr}", brief], timeout=60)
    if rc:
        C.log("followup-failed", job.repo, job.pr, why=out.strip()[-160:].replace("\n", " "))
        return ""
    return f"its review advice is board row {row}"
