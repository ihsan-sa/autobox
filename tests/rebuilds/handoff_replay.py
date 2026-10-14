#!/usr/bin/env python3
"""handoff_replay.py — the recorded failures of the old handoff & context path, replayed against the v2 rules.
The plan is docs/rebuilds/handoff-and-context.md (its "Replay" section). It writes nothing.

usage: handoff_replay.py [--days N] [--failures FILE] [--projects DIR]... [--state DIR] [--sweep-min M]
                         [--overlap-min M] [--json]
       handoff_replay.py selfcheck

It has to run on the host, like handoff_baseline.py: a worker's sandbox sees neither the ledger nor the transcripts.
Every record replayed is a failure the old system had, so the old system replays none of them right. What's measured
is how many the v2 rules would have got right, and why the rest wouldn't:

  spend/context-over-band   The record's session (links.session, else the sid in links.source) is found as a
      transcript, and its per-turn context gives t_line (the first turn at or over the v2 rotate line) and t_band
      (the first at or over the band). Replayed right when t_band - t_line leaves room for the sweep that notices the
      seat and the overlap the predecessor keeps working through: `right` takes the worst sweep phase
      (--sweep-min, cc-reconcile's 20-minute timer, plus --overlap-min), `right_best` the best (the overlap alone).
      The old line (200k) is computed the same way, so the old column is a measure, not an assumption.
      Who the session was is read from evidence, never from where its transcript sits (an interactive track seat
      lives under a worktree too): a cc-loop iteration record naming the session (<state>/<repo>/<track>/runs/*.json)
      or a headless entrypoint ("sdk-cli", `claude -p`) makes it a worker, which no rotate rule reaches, counted
      apart; an interactive entrypoint ("cli") makes it a seat, replayed wherever it lives; neither is a gap.
      # recurring-defect-ok: pause-hold-missing — read-only replay, never launches or writes the board
      A record whose transcript shows no turn at the band (no assistant turns at all, or none that high) is a gap
      too, as is one whose transcript is gone: the moment it reported can't be re-read, so it's counted right for
      neither system. So records = replayed + workers + gaps.
  spend/handoff-packet-over-band   v2 cuts the whole packet at cc-handoff-v2's TOTAL (18 kB), under the 24 kB band,
      so each one is replayed right by construction. The packet's board state at that moment isn't kept, so the v2
      packet itself can't be re-run; the bytes reported for v2 are the cap, and that gap is named in the plan.
  handoff-input/existing-record-not-found   The path the record names (~/.cc/state/<repo>/<name>-handoff.md or
      -handover.md, or a track's progress.md) is mapped to its target, and replayed right when v2's journal_paths()
      lists it among the paths it reads.

It also counts what the lower line costs: per seat transcript in the window, whether its peak reached the v2 line
and the old line. Each seat over the v2 line is a handoff v2 opens, and the old one may not have.
"""
import glob
import importlib.machinery
import importlib.util
import json
import os
import re
import sys
import shutil
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(os.path.dirname(HERE)), "bin")
OLD_LINE = 200000


def load(name, path):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


B = load("handoff_baseline", os.path.join(HERE, "handoff_baseline.py"))
V2 = load("cc_handoff_v2", os.path.join(BIN, "cc-handoff-v2"))


def loop_sessions(state):
    """Every session id a cc-loop iteration recorded (<state>/<repo>/<track>/runs/<stamp>.json): process evidence
    that the session was a worker's iteration."""
    out = set()
    for f in glob.glob(os.path.join(state, "*", "*", "runs", "*.json")):
        try:
            with open(f) as fh:
                sid = json.load(fh).get("session_id")
        except (OSError, ValueError, AttributeError):
            continue
        if sid:
            out.add(sid)
    return out


def entrypoint(path, limit=200):
    """The transcript's own word for how the session ran: "cli" interactive, "sdk-cli" headless (`claude -p`)."""
    try:
        with open(path, errors="replace") as f:
            for i, line in enumerate(f):
                if i >= limit:
                    break
                try:
                    ep = json.loads(line).get("entrypoint")
                except (ValueError, AttributeError):
                    continue
                if ep:
                    return ep
    except OSError:
        pass
    return None


def role(path, sid, loops):
    """("worker", why) / ("seat", why) / (None, gap): from a cc-loop iteration record or the transcript's entrypoint."""
    if sid in loops:
        return "worker", "a cc-loop iteration record names it"
    ep = entrypoint(path)
    if ep == "cli":
        return "seat", "interactive entrypoint"
    if ep:
        return "worker", f"headless entrypoint {ep}"
    return None, "no loop record and no entrypoint in the transcript"


def series(path):
    return [(e[0], B.ctx(e[2])) for e in B.turns(path) if e[1] == "a" and e[0] is not None]


def first_at(ser, n):
    return next((t for t, c in ser if c >= n), None)


def session_of(r):
    links = r.get("links") or {}
    if links.get("session"):
        return links["session"]
    m = re.match(r"spend-context:([^:]+):", str(links.get("source") or ""))
    return m.group(1) if m else None


def context_case(r, roots, line, band, delay_worst, delay_best, loops=frozenset()):
    sid = session_of(r)
    path = B.transcript(sid, roots)
    out = {"kind": B.KINDS[0], "session": sid, "transcript": bool(path)}
    if not path:
        out["gap"] = "no transcript for the session"
        return out
    who, why = role(path, sid, loops)
    if who == "worker":
        out.update(worker=True, why=why)
        return out
    if who is None:
        out["gap"] = why
        return out
    ser = series(path)
    tb = first_at(ser, band)
    out["peak"] = max((c for _, c in ser), default=0)
    if tb is None:                                 # the record says it crossed the band; this transcript can't show when
        out["gap"] = "no assistant turns in the transcript" if not ser else "no turn at the band in the transcript"
        return out
    for key, ln in (("v2", line), ("old", OLD_LINE)):
        tl = first_at(ser, ln)
        gap = None if tl is None or tb is None else (tb - tl) / 60
        out[key + "_gap_min"] = None if gap is None else round(gap, 1)
        out[key + "_right"] = gap is not None and gap >= delay_worst
        out[key + "_right_best"] = gap is not None and gap >= delay_best
    return out


def packet_case(r):
    return {"kind": B.KINDS[1], "old_bytes": B.packet_bytes_of(r), "v2_bytes_max": V2.TOTAL,
            "v2_right": V2.TOTAL < B.PACKET_BAND, "old_right": False}


class _Parts:
    """The one cc-handoff function journal_paths() calls: target -> (repo, alias, track)."""
    @staticmethod
    def parts(t):
        head, _, track = t.partition("/")
        repo, _, alias = head.partition("@")
        return repo, alias, track


def target_of(path):
    m = re.match(r"~/\.cc/state/([^/]+)/([^/]+)/progress\.md$", path)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.match(r"~/\.cc/state/([^/]+)/(.+)-hand(?:off|over)\.md$", path)
    if m:
        return f"{m.group(1)}@{m.group(2)}" if m.group(2) != "planning" else m.group(1)
    return None


def record_text(r):
    """Every free-text field a record can carry: the catalogue's `text`, the ledger's observed/expected/evidence."""
    ev = r.get("evidence")
    return " ".join(str(x) for x in [r.get("text"), r.get("observed"), r.get("expected")]
                    + (ev if isinstance(ev, list) else [ev]) if x)


def record_case(r):
    paths = re.findall(r"~/\.cc/state/[\w./@-]+\.md", record_text(r))
    out = {"kind": B.KINDS[2], "path": paths[0] if paths else None, "old_right": False, "v2_right": False}
    for p in paths:
        t = target_of(p)
        if t and p in V2.journal_paths(_Parts, t)[1]:
            out.update(target=t, path=p, v2_right=True)
            break
    return out


def extra_rotations(roots, since, line, loops=frozenset()):
    """Per seat transcript touched in the window (a seat by the same evidence as context_case): its peak against the
    v2 line and the old one. A transcript with no evidence either way is counted as unknown, not as a seat."""
    v2 = old = seats = unknown = 0
    for root in roots:
        for p in glob.glob(os.path.join(root, "*", "*.jsonl")):
            try:
                if os.path.getmtime(p) < since:
                    continue
            except OSError:
                continue
            who = role(p, os.path.basename(p)[:-len(".jsonl")], loops)[0]
            if who != "seat":
                unknown += who is None
                continue
            peak = max((c for _, c in series(p)), default=0)
            seats += 1
            v2 += peak >= line
            old += peak >= OLD_LINE
    return {"seat_transcripts": seats, "v2_line_reached": v2, "old_line_reached": old, "unknown_role": unknown}


def replay(days, failures, roots, sweep_min=20, overlap_min=10, now=None, scan=True, state=None):
    line, band = V2.rotate_line()
    loops = loop_sessions(state or os.path.expanduser("~/.cc/state"))
    since = (now or time.time()) - days * 86400
    recs = [r for r in B.ledger_records(failures) if r.get("kind") in B.KINDS and (B.ts(r.get("ts") or "") or 0) >= since]
    cases = []
    for r in recs:
        if r["kind"] == B.KINDS[0]:
            cases.append(context_case(r, roots, line, band, sweep_min + overlap_min, overlap_min, loops))
        elif r["kind"] == B.KINDS[1]:
            cases.append(packet_case(r))
        else:
            cases.append(record_case(r))
    summary = {}
    for k in B.KINDS:
        cs = [c for c in cases if c["kind"] == k]
        s = {"records": len(cs), "old_right": sum(bool(c.get("old_right")) for c in cs),
             "v2_right": sum(bool(c.get("v2_right")) for c in cs)}
        if k == B.KINDS[0]:
            gaps = {}
            for c in cs:
                if c.get("gap"):
                    gaps[c["gap"]] = gaps.get(c["gap"], 0) + 1
            s.update(with_transcript=sum(c["transcript"] for c in cs), worker=sum(bool(c.get("worker")) for c in cs),
                     replayed=sum(1 for c in cs if "v2_right" in c), gaps=gaps,
                     old_right_best=sum(bool(c.get("old_right_best")) for c in cs),
                     v2_right_best=sum(bool(c.get("v2_right_best")) for c in cs))
        summary[k] = s
    out = {"days": days, "line": line, "band": band, "sweep_min": sweep_min, "overlap_min": overlap_min,
           "summary": summary, "cases": cases}
    if scan:
        out["rotations"] = extra_rotations(roots, since, line, loops)
    return out


def show(m):
    print(f"replay over {m['days']} days: v2 line {m['line']:,}, band {m['band']:,}, "
          f"sweep {m['sweep_min']} min + overlap {m['overlap_min']} min")
    for k, s in m["summary"].items():
        print(f"  {k:42} {json.dumps(s)}")
    if "rotations" in m:
        print(f"  rotations: {json.dumps(m['rotations'])}")


def selfcheck():
    passed = failed = 0

    def ok(name, cond):
        nonlocal passed, failed
        passed, failed = passed + bool(cond), failed + (not cond)
        print(("ok   " if cond else "FAIL ") + name)

    d = tempfile.mkdtemp(prefix="hr-")
    seat_dir = os.path.join(d, "projects", "-home-u-dev-r")
    work_dir = os.path.join(d, "projects", "-home-u--cc-worktrees-r-t")
    state = os.path.join(d, "state")
    os.makedirs(seat_dir)
    os.makedirs(work_dir)
    os.makedirs(os.path.join(state, "r", "t", "runs"))
    with open(os.path.join(state, "r", "t", "runs", "20261012T000000Z-1.json"), "w") as f:
        json.dump({"session_id": "wk"}, f)                                           # cc-loop's iteration record
    now = time.time()
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    t0 = now - 7200

    def write(dirn, sid, points, ep="cli"):
        with open(os.path.join(dirn, sid + ".jsonl"), "w") as f:
            f.write(json.dumps(dict({"type": "user", "timestamp": iso(t0), "message": {"content": "go"}},
                                    **({"entrypoint": ep} if ep else {}))) + "\n")
            for i, (dt, c) in enumerate(points):
                f.write(json.dumps({"type": "assistant", "timestamp": iso(t0 + dt * 60), "requestId": f"{sid}{i}",
                                    "message": {"model": "m", "usage": {"cache_read_input_tokens": c}, "content": []}}) + "\n")

    write(seat_dir, "slow", [(0, 100000), (10, 131000), (50, 151000), (60, 201000)])   # 40 min from the v2 line to the band
    write(seat_dir, "fast", [(0, 100000), (10, 131000), (15, 151000)])                 # 5 min: no sweep catches it
    write(seat_dir, "mid", [(0, 100000), (10, 131000), (25, 151000)])                  # 15 min: only a lucky sweep phase
    write(seat_dir, "calm", [(0, 100000), (10, 140000)])                               # over the v2 line, never the band
    write(seat_dir, "short", [(0, 100000), (10, 120000)])                              # its record said the band; this can't
    write(seat_dir, "empty", [])                                                       # no assistant turn at all
    write(seat_dir, "hl", [(0, 160000)], ep="sdk-cli")                                 # headless, outside any worktree
    write(work_dir, "wk", [(0, 160000)], ep=None)                                      # a loop's iteration, by its record
    write(work_dir, "tseat", [(0, 100000), (10, 131000), (50, 151000)])                # an interactive track seat
    write(work_dir, "anon", [(0, 160000)], ep=None)                                    # no evidence either way
    fl = os.path.join(d, "failures.json")
    ctx_recs = [{"kind": B.KINDS[0], "ts": iso(t0), "links": {"session": s}}
                for s in ("slow", "mid", "wk", "gone", "hl", "tseat", "anon", "short", "empty")]
    with open(fl, "w") as f:
        json.dump(ctx_recs + [
                   {"kind": B.KINDS[0], "ts": iso(t0), "links": {"source": "spend-context:fast:2026-10-12"}},
                   {"kind": B.KINDS[1], "ts": iso(t0), "cost": ["packet_bytes=155000"]},
                   {"kind": B.KINDS[2], "ts": iso(t0), "text": "the brief said '== journal == (none)' for the "
                    "lessons-site orch; the journal existed at ~/.cc/state/lessons/lessons-site-handover.md"},
                   {"kind": B.KINDS[2], "ts": iso(t0), "text": "no path named here"},
                   {"kind": B.KINDS[2], "ts": iso(t0), "observed": "the successor read no journal",
                    "evidence": ["it was at ~/.cc/state/r/o-handover.md all along"]},
                   {"kind": B.KINDS[0], "ts": iso(now - 30 * 86400), "links": {"session": "slow"}},
                   {"kind": "other/kind", "ts": iso(t0)}], f)
    env0 = {k: os.environ.pop(k, None) for k in ("CC_SPEND_CONTEXT_BAND", "CC_HANDOFF_V2_HEADROOM")}
    try:
        m = replay(14, fl, [os.path.join(d, "projects")], now=now, state=state)
    finally:
        for k, v in env0.items():
            if v is not None:
                os.environ[k] = v
    cs = {c.get("session"): c for c in m["cases"] if c["kind"] == B.KINDS[0]}
    s0, s1, s2 = (m["summary"][k] for k in B.KINDS)
    ok("only the three kinds inside the window are replayed", (s0["records"], s1["records"], s2["records"]) == (10, 1, 3))
    ok("a session found by links.session or by the sid in links.source has its transcript",
       cs["slow"]["transcript"] and cs["fast"]["transcript"] and not cs["gone"]["transcript"])
    ok("a seat with 40 minutes from the v2 line to the band is replayed right; the old line isn't, it came after",
       cs["slow"]["v2_right"] and cs["slow"]["v2_gap_min"] == 40.0 and not cs["slow"]["old_right"]
       and cs["slow"]["old_gap_min"] == -10.0)
    ok("a seat that crossed both inside one sweep is not replayed right, at either phase",
       not cs["fast"]["v2_right"] and not cs["fast"]["v2_right_best"])
    ok("a gap longer than the overlap but shorter than sweep plus overlap is right only at the best phase",
       not cs["mid"]["v2_right"] and cs["mid"]["v2_right_best"])
    ok("a worker is known by its cc-loop iteration record, not by where its transcript sits, and no rule is credited",
       cs["wk"].get("worker") and "iteration record" in cs["wk"]["why"] and "v2_right" not in cs["wk"])
    ok("...or by a headless entrypoint, even outside a worktree",
       cs["hl"].get("worker") and "sdk-cli" in cs["hl"]["why"] and "v2_right" not in cs["hl"])
    ok("an interactive track seat under a worktree is a seat, and is replayed like one",
       not cs["tseat"].get("worker") and cs["tseat"]["v2_right"] and cs["tseat"]["v2_gap_min"] == 40.0)
    ok("a session with no loop record and no entrypoint is a gap, neither excluded as a worker nor replayed",
       cs["anon"].get("gap") and not cs["anon"].get("worker") and "v2_right" not in cs["anon"])
    ok("a transcript with no turn at the band, or no assistant turn at all, is a gap and right for neither system",
       cs["short"].get("gap") == "no turn at the band in the transcript"
       and cs["empty"].get("gap") == "no assistant turns in the transcript"
       and not any(cs[k].get(f) for k in ("short", "empty") for f in ("v2_right", "old_right", "v2_right_best")))
    ok("the context summary counts right, best-phase right, workers, the replayed and each gap",
       (s0["v2_right"], s0["v2_right_best"], s0["old_right"], s0["with_transcript"], s0["worker"], s0["replayed"])
       == (2, 3, 0, 9, 2, 4)
       and s0["gaps"] == {"no transcript for the session": 1, "no loop record and no entrypoint in the transcript": 1,
                          "no turn at the band in the transcript": 1, "no assistant turns in the transcript": 1})
    pc = [c for c in m["cases"] if c["kind"] == B.KINDS[1]][0]
    ok("a packet record is replayed right by the 18 kB cap, with the old bytes kept",
       s1["v2_right"] == 1 and pc["old_bytes"] == 155000 and pc["v2_bytes_max"] < B.PACKET_BAND)
    rc = [c for c in m["cases"] if c["kind"] == B.KINDS[2]]
    ok("the catalogued -handover.md miss maps to its orch and v2 reads that path; a record naming no path isn't right",
       rc[0]["v2_right"] and rc[0]["target"] == "lessons@lessons-site" and not rc[1]["v2_right"])
    ok("...and a ledger record's path is read from its observed and evidence fields, where cc-failures keeps the text",
       rc[2]["v2_right"] and rc[2]["target"] == "r@o" and s2["v2_right"] == 2)
    ok("rotations: seven seat transcripts by evidence, five reach the v2 line and one the old line; the two workers "
       "aren't seats and the one with no evidence is counted unknown",
       m["rotations"] == {"seat_transcripts": 7, "v2_line_reached": 5, "old_line_reached": 1, "unknown_role": 1})
    ok("a track's progress.md maps to the track, a planning journal to the bare repo",
       target_of("~/.cc/state/r/t/progress.md") == "r/t" and target_of("~/.cc/state/r/planning-handoff.md") == "r")
    shutil.rmtree(d, ignore_errors=True)
    print(f"handoff_replay selfcheck: {passed} passed, {failed} failed")
    return 1 if failed else 0


def main(argv):
    if argv[:1] == ["selfcheck"]:
        return selfcheck()
    a = {"--days": "14", "--failures": None, "--sweep-min": "20", "--overlap-min": "10", "--state": None}
    roots, as_json, i = [], False, 0
    while i < len(argv):
        if argv[i] == "--json":
            as_json = True
        elif argv[i] == "--projects" and i + 1 < len(argv):
            roots.append(argv[i + 1]); i += 1
        elif argv[i] in a and i + 1 < len(argv):
            a[argv[i]] = argv[i + 1]; i += 1
        else:
            print(__doc__.split("\n\n")[1], file=sys.stderr)
            return 2
        i += 1
    m = replay(int(a["--days"]), a["--failures"], roots or [os.path.expanduser("~/.claude/projects")],
               float(a["--sweep-min"]), float(a["--overlap-min"]), state=a["--state"])
    if as_json:
        print(json.dumps(m, indent=1))
    else:
        show(m)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
