#!/usr/bin/env python3
# cc-board-dream's selfcheck: `cc-board-dream selfcheck` runs this file with the tool's path. Unlike the exec'd
# selfchecks beside it, it drives the tool as a subprocess, because cc-board fixes its board and state homes from
# HOME and CC_STATE when it is imported: each case gets a fresh HOME, a fixture board named for this run
# (`_ccdream<pid>`, a board only inside this run), a git repo, and a fake claude. Never a live board.
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

TOOL = sys.argv[1]
REPO = f"_ccdream{os.getpid()}"
results, homes = [], []


def case(label, ok):
    results.append(bool(ok))
    print(f"  {'ok' if ok else 'FAIL'}  {label}")


FAKE = r'''#!/usr/bin/env python3
import json, os, re, sys
p = sys.stdin.read()
open(__file__ + ".prompts", "a").write(p + "\n=====\n")
if "Return ONE JSON object" in p and '"rows"' in p:
    rows = re.findall(r"^<<<ROW (\S+)$", p, re.M)
    out = {"rows": [{"row": r, "done": "old-thing" in r, "sure": "high", "why": "old.py was removed", "by": "c1"}
                    for r in dict.fromkeys(rows)]}
else:
    out = {"pairs": []}
    for j, a, b in re.findall(r"^PAIR (\d+)\n<<<ROW (\S+)\n(?:.*\n)*?ROW>>>\n<<<ROW (\S+)$", p, re.M):
        out["pairs"].append({"pair": j if os.environ.get("FAKE_PAIR_STR") else int(j), "verdict": "same" if "dup" in a and "dup" in b else "different", "why": "w"})
print(json.dumps({"result": json.dumps(out), "total_cost_usd": 0.001}))
'''

DUP = "The slack reply renderer drops the thread timestamp when the reply carries a file, so the answer lands as a new top-level post."


def ago(h):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - h * 3600))


def fx():
    """A fresh HOME with one fixture board, its briefs, a git repo and a fake claude. -> (home, env)."""
    h = tempfile.mkdtemp(prefix="cc-board-dream-sc.")
    homes.append(h)
    repo = os.path.join(h, "repo")
    os.makedirs(os.path.join(repo, "core", "lib"))
    for f, t in (("core/lib/old.py", "x = 1\n"), ("core/lib/alive.py", "y = 2\n")):
        with open(os.path.join(repo, f), "w") as fh:
            fh.write(t)
    g = ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-qm", "start"], check=True)
    os.remove(os.path.join(repo, "core/lib/old.py"))
    subprocess.run(g + ["commit", "-qam", "drop old.py"], check=True)
    rows = {
        "merged-fix": ("merged", 80, {}, "Fix the thing.\nCloses raised-closed-by-name and raised-held-closed\n"),
        "raised-closed-by-name": ("queued", 72, {}, "Something the merged fix closes.\n"),
        "raised-held-closed": ("queued", 72, {"held": "owner wants to read it"}, "Held, named by Closes.\n"),
        "raised-old-thing": ("queued", 72, {}, "core/lib/old.py raises on an empty list.\n"),
        "raised-old-other": ("queued", 72, {}, "The parser in core/lib/old.py is slow on big inputs.\n"),
        "raised-dup-a": ("queued", 96, {}, DUP + "\n"),
        "raised-dup-b": ("queued", 72, {}, DUP + "\nCost: two turns burnt re-posting the answer.\n"),
        "raised-dup-young": ("queued", 1, {}, DUP + "\n"),
        "raised-dup-marked": ("queued", 72, {"agent": "@1"}, DUP + "\n"),
        "raised-dup-pr": ("queued", 72, {"pr": "#5"}, DUP + "\n"),
        "raised-dup-running": ("running", 72, {}, DUP + "\n"),
        "raised-unrelated": ("queued", 72, {}, "Emoji width breaks the dashboard table alignment on phones.\n"),
    }
    tracks = {}
    for n, (st, age, extra, brief) in rows.items():
        tracks[n] = {"title": n.replace("-", " "), "kind": "track", "status": st, "notes": [], "created": ago(age),
                     "agent": "", "pr": "", **extra}
        d = os.path.join(h, "state", REPO, n)
        os.makedirs(d)
        with open(os.path.join(d, "task.md"), "w") as fh:
            fh.write(brief)
    os.makedirs(os.path.join(h, ".cc", "boards"))
    with open(os.path.join(h, ".cc", "boards", REPO + ".json"), "w") as fh:
        json.dump({"repo": REPO, "tracks": tracks, "log": [], "path": repo, "default_branch": "main"}, fh, indent=2)
    fake = os.path.join(h, "fake-claude")
    with open(fake, "w") as fh:
        fh.write(FAKE)
    os.chmod(fake, 0o755)
    open(os.path.join(h, "config"), "w").close()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CC_", "BOARD_DREAM_"))}
    env.update(HOME=h, CC_STATE=os.path.join(h, "state"), BOARD_DREAM_STATE=os.path.join(h, "bd"), CC_CLAUDE=fake,
               CC_CONFIG=os.path.join(h, "config"), CC_BOARD_LOCK_WAIT="2")
    return h, env


def run(env, *args):
    p = subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True, env=env, timeout=120)
    return p.returncode, p.stdout + p.stderr


def board(h):
    with open(os.path.join(h, ".cc", "boards", REPO + ".json")) as fh:
        return json.load(fh)["tracks"]


def brief(h, n):
    with open(os.path.join(h, "state", REPO, n, "task.md")) as fh:
        return fh.read()


def plan(h):
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with open(os.path.join(h, "bd", day, REPO + ".json")) as fh:
        return json.load(fh)


def ledger(h):
    p = os.path.join(h, "bd", REPO + ".jsonl")
    return [json.loads(x) for x in open(p)] if os.path.isfile(p) else []


def actions(h):
    """The ledger's close and fold lines (each is followed by an `applied` line once it finished)."""
    return [x for x in ledger(h) if x.get("action") in ("close", "fold")]


def set_brief(h, n, text):
    with open(os.path.join(h, "state", REPO, n, "task.md"), "w") as fh:
        fh.write(text)


def add_row(h, n, text, status="queued", age=72):
    bp = os.path.join(h, ".cc", "boards", REPO + ".json")
    d = json.load(open(bp))
    d["tracks"][n] = {"title": n.replace("-", " "), "kind": "track", "status": status, "notes": [], "created": ago(age),
                      "agent": "", "pr": ""}
    json.dump(d, open(bp, "w"), indent=2)
    os.makedirs(os.path.join(h, "state", REPO, n), exist_ok=True)
    set_brief(h, n, text)


def ccboard(env, *args):
    p = subprocess.run([sys.executable, os.path.join(os.path.dirname(TOOL), "cc-board"), *args],
                       capture_output=True, text=True, env=env, timeout=60)
    return p.returncode, p.stdout + p.stderr


INFLIGHT = "<!-- cc-brief:inflight -->\nIN FLIGHT: a worker's state\n<!-- /cc-brief:inflight -->\n"


def main():
    # 1. a dry run plans and writes nothing to the board
    h, env = fx()
    before = open(os.path.join(h, ".cc", "boards", REPO + ".json")).read()
    rc, out = run(env, "run", "--repo", REPO)
    p = plan(h)
    closes = sorted(c["row"] for c in p["closes"])
    case("dry: the board's bytes are unchanged", rc == 0 and open(os.path.join(h, ".cc", "boards", REPO + ".json")).read() == before)
    case("dry: Closes in a merged row's brief closes the row, and a held row it names is left alone",
         "raised-closed-by-name" in closes and "raised-held-closed" not in closes)
    case("dry: a row whose file is gone closes when the model is sure, and one it says is not done stays",
         "raised-old-thing" in closes and "raised-old-other" not in closes)
    case("dry: the duplicate pair is one fold under the older row",
         p["folds"] == [{"parent": "raised-dup-a", "children": ["raised-dup-b"]}])
    left = set(p["candidates"])
    case("dry: a young, marked, PR'd, running or held row is never a candidate; a plain queued one is",
         not left & {"raised-dup-young", "raised-dup-marked", "raised-dup-pr", "raised-dup-running", "raised-held-closed"}
         and "raised-unrelated" in left)
    case("dry: the model only saw pairs similarity picked (the unrelated row is in none)",
         all("raised-unrelated" not in (x["a"], x["b"]) for x in p["pairs"]) and p["pairs"])
    case("dry: the report is written", os.path.exists(os.path.join(h, "bd", time.strftime("%Y-%m-%d", time.gmtime()), REPO + ".md")))

    # 2. a live run writes it, with a ledger line per action holding the old state
    h, env = fx()
    rc, out = run(env, "run", "--repo", REPO, "--live")
    t = board(h)
    case("live: closed and folded rows are done; the rest keep their status",
         rc == 0 and all(t[n]["status"] == "done" for n in ("raised-closed-by-name", "raised-old-thing", "raised-dup-b"))
         and all(t[n]["status"] == "queued" for n in ("raised-held-closed", "raised-old-other", "raised-dup-a",
                                                       "raised-dup-young", "raised-dup-marked", "raised-dup-pr"))
         and t["raised-dup-running"]["status"] == "running")
    pb = brief(h, "raised-dup-a")
    case("live: the parent's brief carries the child's facts and its cost line, under a heading naming it",
         "Folded in by cc-board-dream" in pb and "raised-dup-b" in pb and "Cost: two turns burnt" in pb)
    L = actions(h)
    case("live: one ledger line per action, each with the row's old status, and each marked applied",
         sorted(x["row"] for x in L) == ["raised-closed-by-name", "raised-dup-b", "raised-old-thing"]
         and all(x["old"]["status"] == "queued" for x in L)
         and {x["of"] for x in ledger(h) if x["action"] == "applied"} == {x["id"] for x in L})
    rc, out = run(env, "run", "--repo", REPO, "--live")
    case("live: a second night finds nothing more to do", len(actions(h)) == 3 and "did not finish" not in out)

    # 3. undo puts a fold back, word for word, and once only
    h, env = fx()
    orig = brief(h, "raised-dup-a")
    run(env, "run", "--repo", REPO, "--live")
    fid = next(x["id"] for x in ledger(h) if x["action"] == "fold")
    rc, out = run(env, "undo", fid)
    t = board(h)
    case("undo: the folded child is queued again and the parent's brief is back as it was",
         rc == 0 and t["raised-dup-b"]["status"] == "queued" and brief(h, "raised-dup-a") == orig)
    case("undo: the close it did not name is untouched", t["raised-old-thing"]["status"] == "done")
    rc, out = run(env, "undo", fid)
    case("undo: a second undo of the same action is refused", rc != 0 and "already undone" in out)

    # 4. undo leaves a row a person moved since
    h, env = fx()
    run(env, "run", "--repo", REPO, "--live")
    cid = next(x["id"] for x in actions(h) if x["row"] == "raised-old-thing")
    bp = os.path.join(h, ".cc", "boards", REPO + ".json")
    d = json.load(open(bp))
    d["tracks"]["raised-old-thing"]["status"] = "running"
    json.dump(d, open(bp, "w"))
    rc, out = run(env, "undo", cid)
    case("undo: a row no longer at the pass's done is left as the person set it",
         board(h)["raised-old-thing"]["status"] == "running" and "left as it is" in out)
    other = next(x["id"] for x in actions(h) if x["row"] == "raised-closed-by-name")
    run(env, "undo", other)
    case("undo: a close still at the pass's done goes back to queued", board(h)["raised-closed-by-name"]["status"] == "queued")

    # 4a. a fold moves the child's whole brief: a cost line past 20,000 characters still reaches the parent
    h, env = fx()
    set_brief(h, "raised-dup-b", (DUP + "\n") * 200 + "Cost: the tail line past the read cap.\n")
    run(env, "run", "--repo", REPO, "--live")
    case("fold: a child brief longer than the prompt cap is appended whole, its last line included",
         board(h)["raised-dup-b"]["status"] == "done" and "Cost: the tail line past the read cap." in brief(h, "raised-dup-a"))

    # 4b. a folded row is no completion: its "Closes C" does not close C on a later night
    h, env = fx()
    set_brief(h, "raised-dup-b", DUP + "\nCloses raised-lonely\n")
    add_row(h, "raised-lonely", "Unicode in branch names breaks the worktree path on checkout.\n")
    run(env, "run", "--repo", REPO, "--live")
    first = board(h)
    run(env, "run", "--repo", REPO, "--live")
    t = board(h)
    case("fold: a folded child's Closes is not evidence; the row it names stays queued the next night",
         first["raised-dup-b"].get("folded_into") == "raised-dup-a" and t["raised-dup-b"]["status"] == "done"
         and t["raised-lonely"]["status"] == "queued" and "raised-lonely" not in [x["row"] for x in actions(h)])

    # 4c. undo leaves a row that was reopened and done again since: a transition came between
    h, env = fx()
    run(env, "run", "--repo", REPO, "--live")
    cid = next(x["id"] for x in actions(h) if x["row"] == "raised-old-thing")
    r1, _ = ccboard(env, "status", REPO, "raised-old-thing", "queued")
    r2, _ = ccboard(env, "status", REPO, "raised-old-thing", "done")
    rc, out = run(env, "undo", cid)
    case("undo: a row reopened and completed again since the action is left done",
         r1 == 0 and r2 == 0 and board(h)["raised-old-thing"]["status"] == "done" and "left as it is" in out)

    # 4d. undo reads, checks and rewrites the parent's brief under the brief's lock: an edit made while it waits is kept
    h, env = fx()
    set_brief(h, "raised-dup-a", DUP + "\n\n" + INFLIGHT)
    run(env, "run", "--repo", REPO, "--live")
    fid = next(x["id"] for x in actions(h) if x["action"] == "fold")
    lockf = open(os.path.join(h, "state", REPO, "raised-dup-a", "task.md.lock"), "a")
    fcntl.flock(lockf, fcntl.LOCK_EX)
    pr = subprocess.Popen([sys.executable, TOOL, "undo", fid], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, env={**env, "CC_BOARD_LOCK_WAIT": "8"})
    time.sleep(2.5)
    set_brief(h, "raised-dup-a", "A person's late edit.\n" + brief(h, "raised-dup-a"))
    fcntl.flock(lockf, fcntl.LOCK_UN)
    lockf.close()
    out = pr.communicate(timeout=60)[0]
    pb = brief(h, "raised-dup-a")
    case("undo: an edit made while undo waited is kept, the fold's text is out, the in-flight block stays",
         pr.returncode == 0 and pb == "A person's late edit.\n" + DUP + "\n\n" + INFLIGHT)

    # 4e. the ledger line is written before the board: a ledger that cannot be written changes nothing
    h, env = fx()
    bp = os.path.join(h, ".cc", "boards", REPO + ".json")
    before, pbefore = open(bp).read(), brief(h, "raised-dup-a")
    os.makedirs(os.path.join(h, "bd", REPO + ".jsonl"))
    rc, out = run(env, "run", "--repo", REPO, "--live")
    case("journal: with the ledger unwritable the board and the parent's brief are unchanged",
         open(bp).read() == before and brief(h, "raised-dup-a") == pbefore and "nothing of it written" in out)

    # 4f. an action that dies after its ledger line is named by the next run and undone like any other
    h, env = fx()
    orig = brief(h, "raised-dup-a")
    bdir = os.path.join(h, ".cc", "boards")
    open(os.path.join(bdir, REPO + ".lock"), "a").close()
    os.chmod(bdir, 0o555)            # the board's save fails; the fold's brief append before it has landed
    rc, out = run(env, "run", "--repo", REPO, "--live")
    os.chmod(bdir, 0o755)
    fid = next((x["id"] for x in actions(h) if x["action"] == "fold"), None)
    appended = fid is not None and "Folded in by cc-board-dream" in brief(h, "raised-dup-a")
    rc2, out2 = run(env, "run", "--repo", REPO)
    rc3, out3 = run(env, "undo", fid or "none")
    case("journal: an interrupted fold is in the ledger, the next run names it, and undo takes its text out",
         appended and "did not finish" in out and f"action {fid} did not finish" in out2
         and rc3 == 0 and brief(h, "raised-dup-a") == orig and board(h)["raised-dup-b"]["status"] == "queued")
    rc4, out4 = run(env, "run", "--repo", REPO)
    case("journal: once undone, the interrupted action is no longer named", f"action {fid} did not finish" not in out4)

    # 4f2. each fold's block carries its action's id: undoing a fold whose append was refused leaves the retry's block
    h, env = fx()
    lockf = open(os.path.join(h, "state", REPO, "raised-dup-a", "task.md.lock"), "a")
    fcntl.flock(lockf, fcntl.LOCK_EX)
    rc, out = run(env, "run", "--repo", REPO, "--live")       # the parent's brief is locked: the fold's append is refused
    fcntl.flock(lockf, fcntl.LOCK_UN)
    lockf.close()
    refused = "Folded in by cc-board-dream" not in brief(h, "raised-dup-a") and "did not finish" in out
    run(env, "run", "--repo", REPO, "--live")                 # the retry folds it
    folds = [x["id"] for x in actions(h) if x["action"] == "fold"]
    after_retry = brief(h, "raised-dup-a")
    rc, out = run(env, "undo", folds[0] if folds else "none")
    case("undo: undoing a fold whose append was refused leaves the later retry's block in the parent's brief",
         refused and len(folds) == 2 and after_retry.count("Folded in by cc-board-dream") == 1
         and brief(h, "raised-dup-a") == after_retry and board(h)["raised-dup-b"]["status"] == "done")

    # 4f3. a row the pass closed, then reopened and completed by a person through cc-board, is evidence again
    h, env = fx()
    set_brief(h, "raised-closed-by-name", "Something the merged fix closes.\nCloses raised-lonely\n")
    add_row(h, "raised-lonely", "Unicode in branch names breaks the worktree path on checkout.\n")
    run(env, "run", "--repo", REPO, "--live")
    first = board(h)
    r1, _ = ccboard(env, "status", REPO, "raised-closed-by-name", "queued")
    r2, _ = ccboard(env, "status", REPO, "raised-closed-by-name", "merged")
    run(env, "run", "--repo", REPO, "--live")
    t = board(h)
    case("evidence: a dream-closed row a person reopened and merged counts again; its Closes closes the row it names",
         first["raised-closed-by-name"].get("dream") and first["raised-lonely"]["status"] == "queued"
         and r1 == 0 and r2 == 0 and "dream" not in t["raised-closed-by-name"] and t["raised-lonely"]["status"] == "done")

    # 4g. a model that numbers its pairs as strings is still read
    h, env = fx()
    run({**env, "FAKE_PAIR_STR": "1"}, "run", "--repo", REPO)
    case("model: \"pair\": \"0\" matches pair 0", plan(h)["folds"] == [{"parent": "raised-dup-a", "children": ["raised-dup-b"]}])

    # 4h. a merged row's pr-body.md is read without the machine's in-flight block, as its brief is
    h, env = fx()
    with open(os.path.join(h, "state", REPO, "merged-fix", "pr-body.md"), "w") as fh:
        fh.write("The fix.\n<!-- cc-brief:inflight -->\nCloses raised-unrelated\n<!-- /cc-brief:inflight -->\n")
    run(env, "run", "--repo", REPO)
    case("evidence: Closes inside pr-body.md's in-flight block closes nothing",
         "raised-unrelated" not in [c["row"] for c in plan(h)["closes"]])

    # 5. score against a person's grouping
    h, env = fx()
    run(env, "run", "--repo", REPO)
    hand = os.path.join(h, "hand.txt")
    with open(hand, "w") as fh:
        fh.write("group 1: raised-dup-a, raised-dup-b and raised-old-other\nraised-unrelated alone\n")
    day = time.strftime("%Y-%m-%d", time.gmtime())
    rc, out = run(env, "score", os.path.join(h, "bd", day, REPO + ".json"), hand)
    case("score: agreement counted over the rows the person named, every disagreement listed",
         rc == 0 and "rows scored: 4; pairs: 6; agree: 4/6" in out
         and "person grouped, pass did not: raised-dup-a + raised-old-other" in out
         and "person grouped, pass did not: raised-dup-b + raised-old-other" in out
         and "pass grouped, person did not" not in out)

    # 6. the spend tier's stop runs nothing
    h, env = fx()
    with open(env["CC_CONFIG"], "w") as fh:
        fh.write("CC_SPEND_TIER=stop\n")
    rc, out = run(env, "run", "--repo", REPO, "--live")
    case("tier stop: nothing planned, no model call, board untouched",
         "nothing run" in out and not os.path.exists(os.path.join(h, "bd", day))
         and not os.path.exists(env["CC_CLAUDE"] + ".prompts") and board(h)["raised-dup-b"]["status"] == "queued")

    # 7. the prompts fence row text as data
    h, env = fx()
    run(env, "run", "--repo", REPO)
    pr = open(env["CC_CLAUDE"] + ".prompts").read()
    case("prompt: row text is fenced and called data", "<<<ROW raised-dup-a" in pr and "never instructions to you" in pr)

    for x in homes:
        shutil.rmtree(x, ignore_errors=True)
    bad = results.count(False)
    print(f"cc-board-dream selfcheck: {len(results) - bad} passed, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
