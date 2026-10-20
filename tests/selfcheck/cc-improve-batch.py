# cc-improve-batch's selfcheck: the cases behind `cc-improve-batch selfcheck` (check.sh and selftest.sh run it that way; there is no
# other entry point). Not a module: cc-improve-batch execs this file INSIDE ITS OWN NAMESPACE and calls the selfcheck() it
# defines, so every name here is the tool's, a `global` rebinds the tool's, and `__file__` is the tool. No
# module docstring (it would replace the tool's __doc__) and no top-level name but the defs below.

def selfcheck():
    results = []

    def case(label, ok):
        results.append(bool(ok))
        print(f"  {'ok' if ok else 'FAIL'}  {label}")

    real_home = os.environ.get("HOME")
    keep = {k: os.environ.get(k) for k in ("HOME", "CC_CLAUDE", "CC_CONFIG", "STUB_LOG", "STUB_FAIL", "IMPROVE_BATCH_BUDGET", "IMPROVE_BATCH_REPOS", "CC_JOB_NOTIFY", "STUB_COST")}

    def fixture():
        h = tempfile.mkdtemp(prefix="cc-improve-batch-sc.")
        os.environ.update({"HOME": h, "CC_CLAUDE": os.path.join(h, "claude"), "CC_CONFIG": os.path.join(h, "config"),
                           "STUB_LOG": os.path.join(h, "calls.jsonl"), "CC_JOB_NOTIFY": os.path.join(h, "notify")})
        with open(os.environ["CC_JOB_NOTIFY"], "w") as f:   # never the live cc-notify: a crossed budget lands in a file
            f.write(f"#!/bin/sh\necho \"$*\" >> '{h}/notified'\n")
        os.chmod(os.environ["CC_JOB_NOTIFY"], 0o755)
        for k in ("STUB_FAIL", "IMPROVE_BATCH_BUDGET", "IMPROVE_BATCH_REPOS", "STUB_COST"):
            os.environ.pop(k, None)
        open(os.environ["CC_CONFIG"], "w").close()
        with open(os.environ["CC_CLAUDE"], "w") as f:
            f.write(STUB)
        os.chmod(os.environ["CC_CLAUDE"], 0o755)
        nd = os.path.join(h, ".cc", "state", "somerepo", "improve", "nudges")
        os.makedirs(nd)
        with open(os.path.join(nd, "method.md"), "w") as f:
            f.write("# method\n## Filter\nkeep status checks\n")
        with open(os.path.join(nd, "2026-01-01-classes.md"), "w") as f:
            f.write("| Rank | Class | Count | Span | Avoid | Score | Proposed automation (short) |\n|---|---|---|---|---|---|---|\n"
                    "| 1 | status-not-pushed | 9 | x | 3 | 27 | progress push |\n| 2 | landing-chase | 5 | x | 2 | 10 | lander posts |\n\n"
                    "## 1. status-not-pushed — 9\n\nStatus check: where are we.\n\n## 2. landing-chase — 5\n\nLanding chase.\n")
        snap = os.path.join(h, ".cc", "state", "improve", "snapshots", "2026-01-10")
        os.makedirs(snap)
        owner = [{"role": "owner", "at": f"2026-01-10T0{i}:00:00Z", "channel": "#r", "text": t, "prev_box": {"text": "queued"}}
                 for i, t in enumerate(["where are we", "status?", "please build a thing", "did it land", "hmm", ""])]
        rows = {"slack": owner + [{"role": "member", "text": "hi"}],
                "outbox": [{"text": "progress: 3 of 4 done"}],
                "failures": [{"kind": "spend/context-over-band", "n": 5, "repo": "r", "examples": ["read 160k"]},
                             {"kind": "notification/false-action-needed", "n": 2, "repo": "r", "examples": ["nagged"]}],
                "landings": [{"pr": "r#1", "repo": "r", "events": {"again": 1}, "last_event": "stages path=serial ok=yes total=4000s", "verdicts": ["LAND"]},
                             {"pr": "r#2", "repo": "r", "events": {}, "last_event": "done rc=0", "verdicts": ["LAND"]}],
                "loops": [{"repo": "r", "track": "t", "iter_errors": 1, "last_line": "exit 3"}]}
        for n, rs in rows.items():
            with open(os.path.join(snap, n + ".jsonl"), "w") as f:
                f.writelines(json.dumps(r) + "\n" for r in rs)
        with open(os.path.join(snap, "index.json"), "w") as f:
            f.write("{}")
        # a repo with commits for the fix picker
        d = os.path.join(h, "dev", "r")
        os.makedirs(d)
        g = ["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", d], check=True)
        for when, msg in (("2026-01-09T12:00:00Z", "progress push on row change"), ("2026-01-15T12:00:00Z", "a later fix")):
            subprocess.run(g + ["commit", "-q", "--allow-empty", "-m", msg], check=True,
                           env=dict(os.environ, GIT_COMMITTER_DATE=when, GIT_AUTHOR_DATE=when))
        return h, snap

    def calls():
        return list(jlines(os.environ["STUB_LOG"]))

    def main_(*argv):
        p = subprocess.run([sys.executable, os.path.realpath(__file__), *argv], capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout + p.stderr

    homes = []
    try:
        # 1. the full run with a stubbed model: all four passes, the report, the jsonl, and the cost
        h, snap = fixture()
        homes.append(h)
        rc, out = main_()
        rep = os.path.join(h, ".cc", "state", "improve", "reports")
        fs = list(jlines(os.path.join(rep, "2026-01-10.jsonl")))
        md = open(os.path.join(rep, "2026-01-10.md")).read() if os.path.exists(os.path.join(rep, "2026-01-10.md")) else ""
        heads = [c["head"] for c in calls()]
        case("with no `latest` snapshot it exits 2 and says so", rc == 2 and "no snapshot" in out and not calls())
        os.symlink("2026-01-10", os.path.join(h, ".cc", "state", "improve", "snapshots", "latest"))
        open(os.environ["STUB_LOG"], "w").close()
        rc, out = main_()
        fs = list(jlines(os.path.join(rep, "2026-01-10.jsonl")))
        md = open(os.path.join(rep, "2026-01-10.md")).read() if os.path.exists(os.path.join(rep, "2026-01-10.md")) else ""
        heads = [c["head"] for c in calls()]
        case("with `latest` set, it exits 0 and prints the day's cost", rc == 0 and "cost $0.10" in out and "2026-01-10.md" in out)
        case("each of the five model calls ran once, in pass order",
             heads == ["PASS: nudges", "PASS: failures", "PASS: fixes-pick", "PASS: fixes-judge", "PASS: ideas"])
        case("all four passes have a section, and the cost line is in the report",
             all(s in md for s in ("## 1. Nudges", "## 2. Failure patterns", "## 3. Fixes still firing", "## 4. Ideas")) and "cost $0.10" in md)
        by = {f["id"]: f for f in fs}
        case("every finding has class, evidence and score = cost x freq",
             fs and all({"class", "evidence", "cost", "freq", "score"} <= set(f) and f["score"] == f["cost"] * f["freq"] for f in fs))
        case("nudges: status-not-pushed counted 2 at its classes-file avoidability 3; landing-chase 1 at 2",
             by.get("nudge:status-not-pushed", {}).get("score") == 6 and by.get("nudge:landing-chase", {}).get("score") == 2)
        case("an `other` nudge under three messages is not a finding", not any(i.startswith("nudge:other") for i in by))
        nud = calls()[0]["prompt"]
        case("the nudge pass got owner messages only, blanks dropped, no member and no other source",
             "where are we" in nud and '"hi"' not in nud and "context-over-band" not in nud and "keep status checks" in nud)
        case("failures: two groups merged into one pattern at cost 2, the rest kept one per group",
             by.get("failure:spend/context-over-band", {}).get("freq") == 6 and by["failure:spend/context-over-band"]["cost"] == 2
             and "failure:notification/false-action-needed" in by and "failure:landing:again" in by and "failure:landing:slow" in by)
        pick = calls()[2]["prompt"]
        case("the fix picker saw the day's commit subjects, not a later one's, and what the snapshot prints",
             "progress push on row change" in pick and "a later fix" not in pick and "landings event names: again" in pick)
        judge = calls()[3]["prompt"]
        case("a fix whose trace is in the snapshot is firing and not judged; a silent one is; a bad source is dropped",
             "digest-line" in judge and '"regex": "progress:"' not in judge and "nowhere" not in md)
        case("the fix the judge called quiet is a finding and ranks first", fs[0]["pass"] == "fixes" and "status digest" in fs[0]["title"])
        case("an idea is a finding, ranked last", fs[-1]["pass"] == "ideas" and fs[-1]["title"].startswith("tell the owner"))
        cnt = list(jlines(os.path.join(rep, "nudge-counts.jsonl")))
        case("the day's nudge counts are written for the trend", {(r["class"], r["n"]) for r in cnt} == {("status-not-pushed", 2), ("landing-chase", 1)})

        # 2. a second day reads the first for trend and recurrence; a rerun replaces, never doubles, its counts
        snap2 = snap.replace("2026-01-10", "2026-01-11")
        shutil.copytree(snap, snap2)
        rc, out = main_(snap2)
        f2 = {f["id"]: f for f in jlines(os.path.join(rep, "2026-01-11.jsonl"))}
        rc, out = main_(snap2)
        cnt = list(jlines(os.path.join(rep, "nudge-counts.jsonl")))
        case("day two shows the trend [2, 2] and that the failure pattern recurred on one earlier day",
             f2.get("nudge:status-not-pushed", {}).get("trend") == [2, 2] and f2["failure:spend/context-over-band"]["recurred_days"] == 1)
        case("a rerun of a day replaces its counts", len(cnt) == 4)

        # 3. a failed pass is reported and the rest still run; pass 2 falls back to one finding per group
        h, snap = fixture()
        homes.append(h)
        os.environ["STUB_FAIL"] = "failures"
        out_dir = os.path.join(h, "out")
        rc, out = main_(snap, "--out", out_dir)
        md = open(os.path.join(out_dir, "2026-01-10.md")).read()
        f3 = {f["id"]: f for f in jlines(os.path.join(out_dir, "2026-01-10.jsonl"))}
        case("a failed failures call: exit 0, named as failed, each group kept at cost 1",
             rc == 0 and "failed: failures" in out and "The pass failed" in md and f3.get("failure:spend/context-over-band", {}).get("cost") == 1
             and "ideas" in {f["pass"] for f in f3.values()})
        case("--out writes there, and not to the default reports folder",
             not os.path.exists(os.path.join(h, ".cc", "state", "improve", "reports")))

        # 4. THE BUDGET ALERTS, IT NEVER STOPS WORK (owner 10-16/20): $0.06 is crossed by the second call, every pass
        #    still runs, and one ambient line says so
        h, snap = fixture()
        homes.append(h)
        os.environ["IMPROVE_BATCH_BUDGET"] = "0.06"
        rc, out = main_(snap)
        cs = calls()
        said = open(os.path.join(h, "notified")).read() if os.path.exists(os.path.join(h, "notified")) else ""
        case("a budget of $0.06 is crossed and every pass still runs, with no dollar cap on any call",
             rc == 0 and [c["head"].split(": ", 1)[-1] for c in cs] == ["nudges", "failures", "fixes-pick", "fixes-judge", "ideas"]
             and not any("--max-budget-usd" in c["argv"] for c in cs) and "failed" not in out)
        case("…its first crossing posts one ambient cc-notify line, and only one",
             said.count("\n") == 1 and "--id budget:cc-improve-batch:" in said)

        # 4b. one call over OVER_CALL says so once and is not cut off; the day goes on
        h, snap = fixture()
        homes.append(h)
        os.environ.update(IMPROVE_BATCH_BUDGET="100", STUB_COST=f"{OVER_CALL + 0.10:.2f}")
        rc, out = main_(snap)
        os.environ.pop("STUB_COST")
        said = open(os.path.join(h, "notified")).read() if os.path.exists(os.path.join(h, "notified")) else ""
        case("every call over OVER_CALL still returns and every pass runs, and one line says so, once",
             rc == 0 and len(calls()) == 5 and "failed" not in out
             and said.count("\n") == 1 and "--id call:cc-improve-batch:" in said)

        # 5. the spend tier: a tier that holds `goals` spends nothing; one that allows it runs
        h, snap = fixture()
        homes.append(h)
        with open(os.environ["CC_CONFIG"], "w") as f:
            f.write("CC_SPEND_TIER=essential\n")
        rc, out = main_(snap)
        case("under the essential tier: exit 0, no model call, no report", rc == 0 and not calls() and "tier holds" in out
             and not os.path.exists(os.path.join(h, ".cc", "state", "improve", "reports")))
        with open(os.environ["CC_CONFIG"], "w") as f:
            f.write("CC_SPEND_TIER=moderate\n")
        rc, out = main_(snap)
        case("under the moderate tier it runs", rc == 0 and len(calls()) == 5)

        # 6. a `latest` snapshot cc-collect left yesterday is refused; the same snapshot named outright still runs
        h, snap = fixture()
        homes.append(h)
        os.symlink("2026-01-10", os.path.join(h, ".cc", "state", "improve", "snapshots", "latest"))
        with open(os.path.join(snap, "index.json"), "w") as f:
            json.dump({"generated": "2026-01-10T23:50:00Z"}, f)
        rc, out = main_()
        case("a `latest` over 26 h old: exit 2, says cc-collect hasn't run, no model call",
             rc == 2 and "has not run" in out and not calls())
        rc, out = main_("2026-01-10")
        case("the same old snapshot named outright still runs", rc == 0 and len(calls()) == 5)
        with open(os.path.join(snap, "index.json"), "w") as f:
            json.dump({"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f)
        open(os.environ["STUB_LOG"], "w").close()
        rc, out = main_()
        case("a `latest` generated now runs", rc == 0 and len(calls()) == 5)

        # 7. in-process, with a fake model: registry rows, failure ids, the ideas note
        class Fake:
            def __init__(self, replies):
                self.replies, self.asked = replies, []

            def ask(self, pass_name, prompt):
                self.asked.append(pass_name)
                return self.replies.get(pass_name, [])

        h, snap = fixture()
        homes.append(h)
        with open(os.path.join(os.path.dirname(snap), "x.jsonl"), "w") as f:
            f.write('{"text": "progress: outside the snapshot"}\n')
        with open(os.path.join(h, ".cc", "state", "improve", "fixes.jsonl"), "w") as f:
            for row in ({"measure": "m:a", "fix": "kept", "source": "outbox", "regex": "progress:"},
                        {"measure": "m:a", "fix": "no source", "regex": "progress:"},
                        {"measure": "m:a", "fix": "escapes", "source": "../x", "regex": "progress:"},
                        {"measure": "m:a", "fix": "not a source", "source": "index", "regex": "."}):
                f.write(json.dumps(row) + "\n")
        found = [{"id": "m:a", "pass": "nudges", "title": "a", "cost": 2, "freq": 3}]
        try:
            q, ch = pass_fixes(snap, Fake({}), "2026-01-10", found, {}, {})
            fixes = [c["fix"] for c in ch]
        except Exception as e:  # noqa: BLE001 - the crash is what this case looks for
            fixes = [f"crashed: {e!r}"]
        case("registry rows: one with a known source is checked; no source, ../x and a non-source are dropped", fixes == ["kept"])
        case("trace_hits refuses a source outside SOURCES", trace_hits(snap, "../x", "progress")[0] is None
             and trace_hits(snap, "outbox", "progress")[0] == 1)

        with open(os.path.join(snap, "failures.jsonl"), "w") as f:
            f.write(json.dumps({"kind": "again", "n": 1, "repo": "r"}) + "\n")
        fs7 = pass_failures(snap, Fake({}), os.path.join(h, "out7"), "2026-01-10", {}, {})
        ids = [f["id"] for f in fs7]
        case("ledger kind `again` and landing `again` stay two findings: failure:again and failure:landing:again",
             "failure:again" in ids and "failure:landing:again" in ids and len(ids) == len(set(ids)))

        notes = {}
        six = [{"title": f"idea {i}", "cost": 1, "freq": 1} for i in range(6)]
        got = pass_ideas(Fake({"ideas": six}), found, [], notes, {})
        case("ideas: six returned, four kept, and the note says both", len(got) == 4 and notes["ideas"] == "4 ideas kept of 6 returned")
        notes = {}
        got = pass_ideas(Fake({"ideas": six[:2]}), found, [], notes, {})
        case("ideas: two returned, both kept", len(got) == 2 and notes["ideas"] == "2 ideas kept of 2 returned")
        many = [{"id": f"m:{i}", "pass": "nudges", "title": f"t{i}", "cost": 1, "freq": 1} for i in range(15)]
        fk = Fake({"ideas": []})
        prompts = []
        fk.ask = lambda pass_name, prompt: prompts.append(prompt) or []
        pass_ideas(fk, many, [], {}, {})
        case("ideas: the pass is shown every finding, not the first ten", prompts and all(f'"m:{i}"' in prompts[0] for i in range(15)))

        # 8. the service's start timeout covers the worst case the code can make
        unit = os.path.join(os.path.dirname(BIN), "config", "systemd-user", "cc-improve-batch.service")
        if os.path.exists(unit):
            m = re.search(r"^TimeoutStartSec=(\d+)$", open(unit).read(), re.M)
            worst = (4 + -(-600 // NUDGE_CHUNK)) * CALL_TIMEOUT
            case(f"TimeoutStartSec covers 4 calls plus nudge chunks for 600 owner messages ({worst} s)",
                 m and int(m.group(1)) >= worst)
            case("the service orders itself after cc-collect", re.search(r"^After=cc-collect\.service$", open(unit).read(), re.M))
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        os.environ["HOME"] = real_home or ""
        for h in homes:
            shutil.rmtree(h, ignore_errors=True)
    bad = results.count(False)
    print(f"cc-improve-batch selfcheck: {len(results) - bad} passed, {bad} failed")
    return 1 if bad else 0
