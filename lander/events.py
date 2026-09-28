"""queue.log: one line per thing that happened to a landing, the record every reader of the queue measures from.

    log(kind, repo, pr, text="", **kv)   ->  `<stamp>\\t<kind> <repo>#<pr> k=v… [text]`
    stage(repo, pr, name, **kv)          ->  `<stamp>\\tstage <repo>#<pr> <name> k=v…`
    lander times [--days N] [--repo R]   queued-to-merged at p50/p95 over the last N days (7)

The stamp is UTC `%Y-%m-%dT%H:%M:%SZ`. A value's tabs and newlines become spaces, and a None or "" value is
dropped, so one event is always one line. pr=None writes `<kind> <repo>` with no `#` (delivery-pending names a
row, not a PR). A log that will not write loses the line and never stops a landing.

KEPT SHAPES. cc-reconcile, cc-replay, the old `times` and PR #757's scripts read this file, so the kinds and their
shapes are today's (KINDS): `queued … who= chat=`, `requeued`, `again`, `refused <repo>#<pr> <reason>`,
`stage … lane | gate gate= ok=yes|no secs= | verdict verdict= | merged sha= by=` (and one `stage` per state the job
machine enters), `done … rc=`, `handed`, `handed-pushed`, `handed-end`, `notify`, `recorded`, `approval`, and
`delivery-pending <repo>/<row> pr= projections=`. `times` reads them back with LOG_EVENT_RE, unchanged.
"""
from __future__ import annotations

import calendar
import os
import re
import sys
import time

KINDS = ("queued", "requeued", "again", "refused", "stage", "done", "handed", "handed-pushed", "handed-end",
         "notify", "recorded", "approval", "delivery-pending")


def stamp(at=None) -> str:
    """Now (or `at`, epoch seconds) as the UTC stamp every record carries."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))


def epoch_of(s) -> int:
    """A stamp() string back as seconds; 0 when it is not one."""
    try:
        return calendar.timegm(time.strptime(s or "", "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return 0


def log_path() -> str:
    from lander import jobs as J   # jobs owns the paths and imports this module; asked at call time
    return os.path.join(J.landq(), "queue.log")


def _flat(v) -> str:
    return re.sub(r"[\t\r\n]+", " ", str(v))


def line(text: str) -> None:
    """Append one raw event line (already shaped) with its stamp."""
    p = log_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a") as f:
            f.write(f"{stamp()}\t{_flat(text)}\n")
    except OSError:
        pass


def log(kind: str, repo: str, pr, text: str = "", **kv) -> None:
    head = f"{kind} {repo}#{pr}" if pr is not None else f"{kind} {repo}"
    parts = [head] + [f"{k}={_flat(v)}" for k, v in kv.items() if v not in (None, "")]
    if text:
        parts.append(_flat(text))
    line(" ".join(parts))


def stage(repo: str, pr, name: str, **kv) -> None:
    """Today's `stage <repo>#<pr> <name> k=v…` line."""
    line(" ".join([f"stage {repo}#{pr} {name}"]
                  + [f"{k}={_flat(v)}" for k, v in kv.items() if v not in (None, "")]))


def delivery_pending(repo: str, row: str, pr_url: str, projections) -> None:
    line(f"delivery-pending {repo}/{row} pr={_flat(pr_url or '-')} projections={_flat(','.join(projections))}")


# --- times: ported from the old lander's lead_times/cmd_times, behaviour unchanged ------------------------------------

def pctl(values, p):
    """The nearest-rank p-th percentile of `values` (p50 of 1..4 is 2, p95 of 1..20 is 19), or None when empty."""
    v = sorted(values)
    return v[max(0, -(-len(v) * p // 100) - 1)] if v else None


def span_words(secs) -> str:
    """A duration the way a person reads it: 45s, 12m, 4h05m."""
    secs = int(secs)
    if secs < 90:
        return f"{secs}s"
    if secs < 90 * 60:
        return f"{round(secs / 60)}m"
    return f"{secs // 3600}h{secs % 3600 // 60:02d}m"


LOG_EVENT_RE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)\t(?:(queued|requeued|fix-pushed|done) ([\w.-]+)#(\d+)(?: rc=(\d+))?"
                          r"|stage ([\w.-]+)#(\d+) (\w+)(.*))")


def lead_times(lines, since=0.0, repo=""):
    """{"first", "last", "lane", "gates": {gate: [...]}} in seconds, from queue.log lines. A PR's lead time runs
    from a `queued` line to the `stage … merged` (or, in older logs, `done … rc=0|3|4`) that landed it: `first` from
    its first queue, `last` from the queue (or requeue) that landed it, `lane` that queue to the first lane after it,
    `gates` each green gate's own run. Only landings merged at or after `since`, only `repo`'s when named."""
    first, last, lane_at, got = {}, {}, {}, {"first": [], "last": [], "lane": [], "gates": {}}
    for ln in lines:
        m = LOG_EVENT_RE.match(ln)
        if not m:
            continue
        at = epoch_of(m.group(1))
        if m.group(2):
            kind, key, rc, rest = m.group(2), (m.group(3), m.group(4)), m.group(5), ""
        else:
            kind, key, rc, rest = m.group(8), (m.group(6), m.group(7)), None, m.group(9)
        if repo and key[0] != repo:
            continue
        if kind in ("queued", "requeued", "fix-pushed"):
            first.setdefault(key, at)
            last[key] = at
            lane_at.pop(key, None)
        elif kind == "lane":
            lane_at.setdefault(key, at)
        elif kind == "gate" and at >= since:
            g, s = re.search(r"\bgate=(\S+)", rest), re.search(r"\bok=yes\b.*\bsecs=(\d+)", rest)
            if g and s:   # a green run's own length: a red or stopped one ended early and would flatter the figure
                got["gates"].setdefault(g.group(1), []).append(int(s.group(1)))
        elif (kind == "merged" or (kind == "done" and rc in ("0", "3", "4"))) and key in last:
            if at >= since:
                got["first"].append(at - first[key])
                got["last"].append(at - last[key])
                if key in lane_at:
                    got["lane"].append(lane_at[key] - last[key])
            for d in (first, last, lane_at):   # merged once: the `done` after a `stage merged` is the same landing
                d.pop(key, None)
    return got


def cmd_times(argv) -> int:
    """`lander times [--days N] [--repo R]`."""
    days, repo = 7.0, ""
    try:
        opts = dict(zip(argv[::2], argv[1::2]))
        if len(argv) % 2 or set(opts) - {"--days", "--repo"}:
            raise ValueError
        days, repo = float(opts.get("--days", days)), opts.get("--repo", "")
    except ValueError:
        print("lander: usage: lander times [--days N] [--repo R]", file=sys.stderr)
        return 2
    try:
        with open(log_path(), errors="replace") as f:
            got = lead_times(f, since=time.time() - days * 86400, repo=repo)
    except OSError as e:
        print(f"lander: no queue log to measure: {e}", file=sys.stderr)
        return 1
    where = f" of {repo}" if repo else ""

    def row(name, vals):
        if not vals:
            return f"{name}: none"
        return f"{name}: p50 {span_words(pctl(vals, 50))}, p95 {span_words(pctl(vals, 95))} over {len(vals)}"
    print(f"landings{where} merged in the last {days:g} days — {len(got['first'])}")
    print("  " + row("queued → merged, from the first queue", got["first"]))
    print("  " + row("queued → merged, from the queue that landed it", got["last"]))
    print("  " + row("queued → a lane took it", got["lane"]))
    for g in sorted(got["gates"]):
        print("  " + row(f"gate {g}, green runs", got["gates"][g]))
    return 0


COMMANDS = {"times": (cmd_times, "queued-to-merged p50/p95 over queue.log [--days N] [--repo R]")}
