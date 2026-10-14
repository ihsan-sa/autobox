#!/usr/bin/env python3
"""handoff_baseline.py — the old handoff & context system's numbers, measured from what the box already keeps.
The plan is docs/rebuilds/handoff-and-context.md; this is its "Baseline" section's instrument. It writes nothing.

usage: handoff_baseline.py [--days N] [--records FILE] [--failures FILE] [--projects DIR]... [--json]
       handoff_baseline.py selfcheck

It has to run on the host: a worker's sandbox sees neither the ledger nor the records nor other seats' transcripts.

WHAT IT READS
  --records   ~/.cc/state/context/handoffs.jsonl, cc-handoff's one line per phase. overlap-started carries the
              PREDECESSOR's session id (the live side then); overlap-cutover / overlap-forced the SUCCESSOR's.
  --failures  a JSON list of ledger records; by default `cc-failures show --json --all`.
  --projects  where transcripts live (default ~/.claude/projects); <session_id>.jsonl is found under any of them.

WHAT IT MEASURES, per handoff that has both a start and a cutover row
  overlap_min     cutover minus start; retired minus start when a retired row exists (both said).
  packet_bytes    the longest tool result in the successor's transcript for a `cc-handoff --brief` call. The packet
                  itself is not kept anywhere else, so this recovers it from the one place it was read.
  packet_tokens   the successor's context after that result minus before it (input + cache tokens of the turns).
  ready_ctx       the successor's context on the first assistant turn after its `cc-handoff --ready` call.
  questions       the successor's `cc-msg` calls before --ready: a proxy for question rounds, since the KICK asks
                  for ONE batch. A proxy, and named as one in the plan.
  pred_peak       the predecessor's largest per-turn context before the start; past_band when >= --band.
  cost_usd        the successor's spend from its first turn to the --ready turn, plus the predecessor's spend from
                  the start to the retired row (or the transcript's end), priced by cc-spend's usd().
And from the ledger: records of the three kinds this rebuild is aimed at, and the packet_bytes their cost carries.
"""
import glob
import importlib.machinery
import importlib.util
import json
import os
import re
import statistics
import subprocess
import sys
import shutil
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(os.path.dirname(HERE)), "bin")
KINDS = ("spend/context-over-band", "spend/handoff-packet-over-band", "handoff-input/existing-record-not-found")
BAND = 150000
PACKET_BAND = 24 * 1024


def spend():
    """cc-spend as a module, for its usd(): one price table on the box, never a second one here."""
    p = os.path.join(BIN, "cc-spend")
    spec = importlib.util.spec_from_loader("cc_spend", importlib.machinery.SourceFileLoader("cc_spend", p))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def ts(s):
    try:
        return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except (TypeError, ValueError):
        return None


def jsonl(path):
    out = []
    try:
        with open(path, errors="replace") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def ctx(u):
    return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


def transcript(sid, roots):
    if not sid:
        return None
    for r in roots:
        hit = glob.glob(os.path.join(r, "*", sid + ".jsonl")) + glob.glob(os.path.join(r, sid + ".jsonl"))
        if hit:
            return hit[0]
    return None


def turns(path):
    """The transcript as (t, kind, payload) in order: ('a', usage, model, rid) per assistant request (deduped on
    requestId), ('call', id, command) per Bash tool_use, ('result', id, text) per tool result. Sidechains skipped."""
    out, seen = [], set()
    for r in jsonl(path):
        if r.get("isSidechain"):
            continue
        t = ts(r.get("timestamp") or "")
        msg = r.get("message") or {}
        content = msg.get("content")
        if r.get("type") == "assistant":
            rid = r.get("requestId") or msg.get("id")
            if msg.get("usage") and rid not in seen:
                seen.add(rid)
                out.append((t, "a", msg["usage"], msg.get("model"), rid))
            for c in content if isinstance(content, list) else []:
                if c.get("type") == "tool_use":
                    out.append((t, "call", c.get("id"), str((c.get("input") or {}).get("command") or "")))
        elif r.get("type") == "user" and isinstance(content, list):
            for c in content:
                if c.get("type") == "tool_result":
                    body = c.get("content")
                    if isinstance(body, list):
                        body = "".join(x.get("text", "") for x in body if isinstance(x, dict))
                    out.append((t, "result", c.get("tool_use_id"), str(body or "")))
    return out


def successor(path, usd):
    tl = turns(path)
    calls = {e[2]: e[3] for e in tl if e[1] == "call"}
    brief_ids = {i for i, c in calls.items() if re.search(r"cc-handoff\b.*--brief|cc handoff\b.*--brief", c)}
    ready_ids = [i for i, c in calls.items() if re.search(r"cc-handoff\b.*--ready|cc handoff\b.*--ready", c)]
    m = {"packet_bytes": None, "packet_tokens": None, "ready_ctx": None, "questions": 0, "cost_usd": 0.0}
    last_ctx, pending, ready_at, priced = None, None, None, True
    for i, e in enumerate(tl):
        if e[1] == "a":
            c = ctx(e[2])
            if pending is not None and last_ctx is not None:
                m["packet_tokens"] = max(m["packet_tokens"] or 0, c - last_ctx)
                pending = None
            if ready_at is None or i <= ready_at:
                v = usd(e[3], e[2])
                priced = priced and v is not None
                m["cost_usd"] += v or 0.0
            if ready_at is not None and m["ready_ctx"] is None and i > ready_at:
                m["ready_ctx"] = c
            last_ctx = c
        elif e[1] == "call":
            if ready_at is None and re.search(r"\bcc-msg\b", e[3]):
                m["questions"] += 1
            if e[2] in ready_ids and ready_at is None:
                ready_at = i
        elif e[1] == "result" and e[2] in brief_ids:
            n = len(e[3].encode())
            if n > (m["packet_bytes"] or 0):
                m["packet_bytes"], pending = n, True
    if ready_at is None:
        m["cost_usd"] = None                     # no --ready in the transcript: the onboarding has no end to price to
    elif not priced:
        m["cost_usd"] = None
    return m


def predecessor(path, start, end, usd):
    peak, cost = 0, 0.0
    for e in turns(path):
        if e[1] != "a" or e[0] is None:
            continue
        if e[0] < start:
            peak = max(peak, ctx(e[2]))
        elif end is None or e[0] <= end:
            cost += usd(e[3], e[2]) or 0.0
    return peak, cost


def ledger_records(path):
    if path:
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return []
    try:
        p = subprocess.run([os.path.join(BIN, "cc-failures"), "show", "--json", "--all"], capture_output=True,
                           text=True, timeout=120)
        return json.loads(p.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def packet_bytes_of(r):
    for c in r.get("cost") or []:
        s = c if isinstance(c, str) else json.dumps(c)
        mm = re.search(r"packet_bytes\D*(\d+)", s)
        if mm:
            return int(mm.group(1))
    return None


def dist(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "median": statistics.median(xs), "p90": xs[min(len(xs) - 1, int(len(xs) * 0.9))],
            "max": xs[-1], "mean": round(sum(xs) / len(xs), 4)}


def measure(days, records, failures, roots, band=BAND, usd=None, now=None):
    usd = usd or spend().usd
    since = (now or time.time()) - days * 86400
    by = {}
    for r in jsonl(records):
        t = ts(r.get("ts") or "")
        if t is None or t < since:
            continue
        by.setdefault(r.get("handoff"), {})[r.get("kind")] = (t, r)
    rows = []
    for hid, ph in by.items():
        st = ph.get("overlap-started")
        cut = ph.get("overlap-cutover") or ph.get("overlap-forced")
        if not st or not cut:
            continue
        ret = ph.get("overlap-retired")
        row = {"handoff": hid, "target": st[1].get("target"), "box": bool(st[1].get("why")),
               "overlap_min": round((cut[0] - st[0]) / 60, 1),
               "overlap_total_min": round((ret[0] - st[0]) / 60, 1) if ret else None,
               "succ_transcript": False, "pred_transcript": False}
        sp = transcript(cut[1].get("session_id"), roots)
        if sp:
            row["succ_transcript"] = True
            row.update(successor(sp, usd))
        pp = transcript(st[1].get("session_id"), roots)
        if pp:
            row["pred_transcript"] = True
            row["pred_peak"], row["pred_overlap_usd"] = predecessor(pp, st[0], ret[0] if ret else None, usd)
            row["past_band"] = row["pred_peak"] >= band
        rows.append(row)
    fails = [r for r in ledger_records(failures) if r.get("kind") in KINDS and (ts(r.get("ts") or "") or 0) >= since]
    out = {"days": days, "handoffs": len(rows), "box_rotations": sum(r["box"] for r in rows),
           "with_successor_transcript": sum(r["succ_transcript"] for r in rows),
           "with_predecessor_transcript": sum(r["pred_transcript"] for r in rows)}
    for k in ("overlap_min", "overlap_total_min", "packet_bytes", "packet_tokens", "ready_ctx", "questions",
              "pred_peak"):
        out[k] = dist([r.get(k) for r in rows])
    cost = [r["cost_usd"] + r.get("pred_overlap_usd", 0.0) for r in rows if r.get("cost_usd") is not None]
    out["cost_usd"] = dist(cost)
    out["past_band"] = sum(1 for r in rows if r.get("past_band"))
    out["ledger"] = {k: sum(1 for r in fails if r.get("kind") == k) for k in KINDS}
    out["ledger_packet_bytes"] = dist([packet_bytes_of(r) for r in fails if r.get("kind") == KINDS[1]])
    out["ledger_with_transcript"] = None    # a ledger record names a session only in free text; see the plan's Gaps
    out["rows"] = rows
    return out


def show(m):
    print(f"handoffs in {m['days']} days: {m['handoffs']} ({m['box_rotations']} box rotations); successor transcript "
          f"for {m['with_successor_transcript']}, predecessor for {m['with_predecessor_transcript']}")
    for k in ("packet_bytes", "packet_tokens", "ready_ctx", "overlap_min", "overlap_total_min", "questions",
              "pred_peak", "cost_usd"):
        print(f"  {k:18} {json.dumps(m[k])}")
    print(f"  predecessor past the {BAND:,} band before the start: {m['past_band']} of {m['with_predecessor_transcript']}")
    print(f"  ledger: {json.dumps(m['ledger'])}")
    print(f"  ledger packet_bytes: {json.dumps(m['ledger_packet_bytes'])}")


def selfcheck():
    passed = failed = 0

    def ok(name, cond):
        nonlocal passed, failed
        passed, failed = passed + bool(cond), failed + (not cond)
        print(("ok   " if cond else "FAIL ") + name)

    d = tempfile.mkdtemp(prefix="hb-")
    proj = os.path.join(d, "projects", "x")
    os.makedirs(proj)
    now = time.time()
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    t0 = now - 3600

    def u(c):
        return {"input_tokens": 10, "cache_read_input_tokens": c, "cache_creation_input_tokens": 0, "output_tokens": 5}

    def asst(t, rid, c, calls=()):
        return {"type": "assistant", "timestamp": iso(t), "requestId": rid,
                "message": {"model": "m", "usage": u(c), "content": [
                    {"type": "tool_use", "id": i, "input": {"command": cmd}} for i, cmd in calls]}}

    def res(t, i, text):
        return {"type": "user", "timestamp": iso(t), "message": {"content": [
            {"type": "tool_result", "tool_use_id": i, "content": text}]}}

    succ = [asst(t0 + 60, "s1", 20000, [("b", "cc-handoff --brief r/t")]), res(t0 + 61, "b", "x" * 30000),
            asst(t0 + 62, "s2", 28000, [("q", "cc-msg 'r/t~old' 'which loops?'")]),
            asst(t0 + 120, "s3", 29000, [("r", "cc-handoff --ready")]), res(t0 + 121, "r", "live"),
            asst(t0 + 122, "s4", 30000), asst(t0 + 123, "s4", 30000),
            {"type": "assistant", "isSidechain": True, "timestamp": iso(t0 + 124), "requestId": "z",
             "message": {"model": "m", "usage": u(999999), "content": []}}]
    pred = [asst(t0 - 600, "p1", 160000), asst(t0 + 30, "p2", 170000), asst(t0 + 900, "p3", 171000)]
    for sid, body in (("succ", succ), ("pred", pred)):
        with open(os.path.join(proj, sid + ".jsonl"), "w") as f:
            f.write("\n".join(json.dumps(x) for x in body) + "\n")
    rec = os.path.join(d, "handoffs.jsonl")
    with open(rec, "w") as f:
        for t, kind, sid, extra in ((t0, "overlap-started", "pred", {"why": "over the line"}),
                                    (t0 + 120, "overlap-cutover", "succ", {}), (t0 + 600, "overlap-retired", "succ", {}),
                                    (t0, "overlap-started", "lone", {}),
                                    (now - 30 * 86400, "overlap-started", "old", {})):
            f.write(json.dumps(dict({"ts": iso(t), "kind": kind, "handoff": "h-" + sid if sid in ("lone", "old") else "h1",
                                     "target": "r/t", "session_id": sid}, **extra)) + "\n")
    fl = os.path.join(d, "failures.json")
    with open(fl, "w") as f:
        json.dump([{"kind": KINDS[1], "ts": iso(t0), "cost": ["packet_bytes=150000"]},
                   {"kind": KINDS[0], "ts": iso(t0), "cost": []},
                   {"kind": KINDS[0], "ts": iso(now - 30 * 86400), "cost": []},
                   {"kind": "other/kind", "ts": iso(t0), "cost": []}], f)
    price = lambda model, us: ctx(us) / 1e6
    m = measure(14, rec, fl, [os.path.join(d, "projects")], usd=price, now=now)
    r = m["rows"][0] if m["rows"] else {}
    ok("a handoff with a start and a cutover is counted; one with a start alone, or older than the window, is not",
       m["handoffs"] == 1)
    ok("a start that carries a why is a box rotation", m["box_rotations"] == 1)
    ok("overlap minutes run start to cutover, and start to retired", r.get("overlap_min") == 2.0 and r.get("overlap_total_min") == 10.0)
    ok("the packet is recovered from the --brief tool result in the successor's transcript", r.get("packet_bytes") == 30000)
    ok("packet tokens are the context after that result minus before it", r.get("packet_tokens") == 8000)
    ok("the context at --ready is the first turn after the --ready call", r.get("ready_ctx") == 30010)
    ok("a cc-msg before --ready is one question round", r.get("questions") == 1)
    ok("the predecessor's peak is read before the start only, and past the band is said",
       r.get("pred_peak") == 160010 and r.get("past_band") is True)
    ok("a sidechain turn and a repeated requestId are not priced; the successor is priced up to --ready only",
       abs(r.get("cost_usd", 0) - (20010 + 28010 + 29010) / 1e6) < 1e-9)
    ok("the predecessor's overlap spend runs from the start to the retired row", abs(r.get("pred_overlap_usd", 0) - 170010 / 1e6) < 1e-9)
    ok("the ledger counts only the three kinds, inside the window", m["ledger"] == {KINDS[0]: 1, KINDS[1]: 1, KINDS[2]: 0})
    ok("a packet record's bytes come from its cost", m["ledger_packet_bytes"].get("max") == 150000)
    shutil.rmtree(d, ignore_errors=True)
    print(f"handoff_baseline selfcheck: {passed} passed, {failed} failed")
    return 1 if failed else 0


def main(argv):
    if argv[:1] == ["selfcheck"]:
        return selfcheck()
    a = {"--days": "14", "--records": os.path.expanduser("~/.cc/state/context/handoffs.jsonl"), "--failures": None}
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
    m = measure(int(a["--days"]), a["--records"], a["--failures"], roots or [os.path.expanduser("~/.claude/projects")])
    if as_json:
        print(json.dumps(m, indent=1))
    else:
        show(m)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
