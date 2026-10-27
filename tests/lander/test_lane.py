"""The lane's cases (U1): intake, the inbox, the job machine, Δ revalidation, the merge and its tree proof, the
door, the board rules, events/times, handback + tick, crash resume.

    python3 -m unittest discover -s core/tests/lander -p 'test_lane.py' -v

Hermetic: every case builds a bare origin + clones under a tmp dir, HOME and every lander path point there, and
PATH starts with a tmp bin of fakes (gh answering from a JSON file and squashing for real onto the bare origin;
cc-config, cc-pause, cc-tier, cc-board, cc, cc-gh-token, systemd-run, systemctl, tmux). The units are stubs.
"""
import contextlib
import dataclasses
import errno
from concurrent import futures
import io
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import types
import time
import unittest
from unittest import mock

CORE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from lander import cards as C  # noqa: E402
from lander import events as E  # noqa: E402
from lander import gh as GH  # noqa: E402
from lander import git as G  # noqa: E402
from lander import health as HL  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import lane as L  # noqa: E402
from lander import manifest as MF  # noqa: E402
from lander import members as M  # noqa: E402
from lander import repair as RP  # noqa: E402
from lander import review as R  # noqa: E402
from lander import tick as TK  # noqa: E402
from lander import types as T  # noqa: E402

REAL_SPAWN_TICK = L.spawn_tick

FAKE = r'''#!PYTHON -SI
import json, os, sys
me, a = os.path.basename(sys.argv[0]), sys.argv[1:]
box_path = os.environ["FAKE_BOX"]
box = json.load(open(box_path))
box.setdefault("calls", []).append([me] + a)
if me == "gh":
    box.setdefault("gh_tokens", []).append(os.environ.get("GH_TOKEN", ""))
def save(): json.dump(box, open(box_path, "w"), indent=1)
def out(rc, text="", err=""):
    save()
    if text: print(text)
    if err: print(err, file=sys.stderr)
    sys.exit(rc)
def g(*args, env=None, inp=None):
    import subprocess
    return subprocess.run(["git", "--git-dir", box["origin"], *args], capture_output=True, text=True,
                          env=env, input=inp).stdout.strip()
if me == "gh":
    if box.get("down"):
        out(1, "", "error connecting to api.github.com")
    prs = box.setdefault("prs", {})
    import re
    rest = re.fullmatch(r"repos/[^/]+/[^/]+/(pulls/(\d+)(/files\?per_page=100)?|commits/(\w+)/(check-runs|status)\?per_page=100)",
                        a[1]) if a[:1] == ["api"] and len(a) > 1 else None
    if a[:2] == ["api", "--paginate"]:
        rest = re.fullmatch(r"repos/[^/]+/[^/]+/(pulls/(\d+)(/files)\?per_page=100)()()", a[2])
    if rest:   # GitHub's REST answer, made from the same PR the pr view below gives (gh.pr_facts' REST path)
        n, files, sha, what = rest.group(2), rest.group(3), rest.group(4), rest.group(5)
        if sha:
            n = next((k for k, v in prs.items() if v.get("state", "OPEN") == "OPEN"
                      and g("rev-parse", "refs/heads/" + v["headRefName"]) == sha), None)
        a = ["pr", "view", n or "0", "--json", "files" if files else
             "statusCheckRollup" if sha else "state,isDraft,mergeable,headRefOid,headRefName,baseRefName,title,body,mergeCommit,mergeStateStatus"]
        rest = (files, sha, what)
    if a[:2] == ["api", "user"]:   # gh.viewer: the box's own login
        out(0, "box")
    if a[:2] == ["api", "rate_limit"]:   # gh.spent: the core quota the box sets, else a full one
        out(0, json.dumps({"resources": {"core": box.get("rate_limit") or {"remaining": 5000, "reset": 0}}}))
    rcom = re.fullmatch(r"repos/[^/]+/[^/]+/issues/(\d+)/comments(\?per_page=100)?", a[2] if a[1:2] == ["--paginate"]
                        else a[1]) if a[:1] == ["api"] and len(a) > 2 else None
    if rcom:   # an issue's comments over REST: listed (gh.comments, after its -q) or one posted (gh.comment)
        pr = prs.get(rcom.group(1))
        if pr is None:
            out(1, json.dumps({"message": "Not Found"}), "gh: Not Found (HTTP 404)")
        if rcom.group(2):
            out(0, "\n".join(json.dumps({"body": c.get("body", ""), "login": "box" if c.get("viewerDidAuthor") else
                                         "someone", "createdAt": c.get("createdAt", "")}) for c in pr.get("comments") or []))
        box.setdefault("posted", []).append((rcom.group(1), json.load(sys.stdin)["body"] if "--input" in a
                                             else a[a.index("-f") + 1][len("body="):]))
        out(0, json.dumps({"id": len(box["posted"])}))
    rmerge = re.fullmatch(r"repos/[^/]+/[^/]+/pulls/(\d+)/merge", a[3]) if a[:3] == ["api", "-X", "PUT"] else None
    if rmerge:   # the REST squash merge (gh.merge_argv), recorded as the merge it is: pin, title, no branch delete
        box.setdefault("rest_merges", []).append(a)
        f = dict(x.split("=", 1) for x in a[4:] if "=" in x)
        if rmerge.group(1) not in prs:
            out(1, json.dumps({"message": "Not Found"}), "gh: Not Found (HTTP 404)")
        a = ["pr", "merge", rmerge.group(1), "--squash", "--match-head-commit", f.get("sha", "")] \
            + (["--subject", f["commit_title"]] if "commit_title" in f else [])
    rdel = re.fullmatch(r"repos/[^/]+/[^/]+/git/refs/heads/(.+)", a[3]) if a[:3] == ["api", "-X", "DELETE"] else None
    if rdel:
        box.setdefault("deleted", []).append(rdel.group(1))
        if box.get("delete_fail"):
            out(1, "", box["delete_fail"])
        g("update-ref", "-d", "refs/heads/" + rdel.group(1))
        out(0)
    if a[:2] == ["pr", "view"]:
        pr = prs.get(a[2])
        if pr is None:
            out(1, "", "Not Found (HTTP 404)" if rest else "no pull requests found")
        fields = a[a.index("--json") + 1].split(",")
        if "statusCheckRollup" in fields and box.get("checks_denied"):   # a token that reads the PR, not its checks
            out(1, "", box["checks_denied"])
        d = {"state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE", "baseRefName": "main",
             "title": "PR %s" % a[2], "body": ""}
        d.update(pr)
        d["mergeStateStatus"] = "BEHIND" if box.get("behind") else "CLEAN"   # strict protection, base moved on
        if d["state"] == "OPEN":
            d["headRefOid"] = g("rev-parse", "refs/heads/" + pr["headRefName"])
        if "files" in fields:
            mb = g("merge-base", "refs/heads/main", d["headRefOid"])
            d["files"] = [{"path": p} for p in g("diff", "--name-only", mb, d["headRefOid"]).splitlines()]
        if rest and rest[0]:
            out(0, "\n".join(f["path"] for f in d["files"]))
        if rest and rest[1]:
            rows = d.get("statusCheckRollup") or []
            if rest[2] == "status":
                st = [r for r in rows if "context" in r]
                out(0, json.dumps({"total_count": len(st), "statuses": [
                    {"context": r.get("context"), "state": (r.get("state") or "").lower(),
                     "target_url": r.get("targetUrl")} for r in st]}))
            cr = [r for r in rows if "context" not in r]
            out(0, json.dumps({"total_count": len(cr), "check_runs": [
                {"name": r.get("name"), "status": (r.get("status") or "").lower(),
                 "conclusion": (r.get("conclusion") or "").lower() or None,
                 "details_url": r.get("detailsUrl")} for r in cr]}))
        if rest:
            mc = d.get("mergeCommit") if d["state"] == "MERGED" else None
            out(0, json.dumps({"number": int(a[2]), "state": "open" if d["state"] == "OPEN" else "closed",
                               "merged_at": "2026-10-19T00:00:00Z" if d["state"] == "MERGED" else None,
                               "merge_commit_sha": (mc or {}).get("oid"), "draft": d["isDraft"],
                               "mergeable": {"MERGEABLE": True, "CONFLICTING": False}.get(d["mergeable"]),
                               "mergeable_state": d["mergeStateStatus"].lower(), "title": d["title"], "body": d["body"],
                               "head": {"sha": d.get("headRefOid"), "ref": d.get("headRefName"),
                                        "repo": {"full_name": d.get("headRepo", "o/demo")}},
                               "base": {"ref": d["baseRefName"], "repo": {"full_name": "o/demo"}}}))
        out(0, json.dumps({f: d.get(f) for f in fields}))
    if a[:2] == ["pr", "merge"]:
        pr = prs[a[2]]
        box.setdefault("merges", []).append(a)
        if box.get("lockpath"):
            import fcntl
            fd = os.open(box["lockpath"], os.O_RDWR | os.O_CREAT)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                box["lock_during_merge"] = "free"
            except BlockingIOError:
                box["lock_during_merge"] = "held"
            os.close(fd)
        if box.get("merge_fail"):
            out(1, json.dumps({"message": box["merge_fail"]}) if rmerge else "", box["merge_fail"])
        if box.get("behind"):
            out(1, "", 'gh: Required status check "check" is expected. (HTTP 405)' if rmerge else
                'GraphQL: Required status check "check" is expected. (mergePullRequest)')
        if pr.get("state") == "MERGED" and rmerge:
            out(1, json.dumps({"message": "Pull Request is not mergeable"}), "gh: Pull Request is not mergeable (HTTP 405)")
        head = g("rev-parse", "refs/heads/" + pr["headRefName"])
        pin = a[a.index("--match-head-commit") + 1]
        if pin != head:
            out(1, "", "gh: Head branch was modified. Review and try the merge again. (HTTP 409)" if rmerge else
                "GraphQL: Head branch was modified. Review and try the merge again.")
        if box.pop("race", None):   # a third party lands in the window before the squash
            idx = os.path.join(os.path.dirname(box_path), "race.idx")
            env = dict(os.environ, GIT_INDEX_FILE=idx)
            g("read-tree", "refs/heads/main", env=env)
            blob = g("hash-object", "-w", "--stdin", inp="third party\n")
            g("update-index", "--add", "--cacheinfo", "100644,%s,third/party.txt" % blob, env=env)
            c = g("commit-tree", g("write-tree", env=env), "-p", "refs/heads/main", "-m", "third party")
            g("update-ref", "refs/heads/main", c)
        tree = g("merge-tree", "--write-tree", "refs/heads/main", head).splitlines()[0]
        subj = a[a.index("--subject") + 1] if "--subject" in a else "squash"
        c = g("commit-tree", tree, "-p", "refs/heads/main", "-m", subj)
        g("update-ref", "refs/heads/main", c)
        pr.update(state="MERGED", headRefOid=head, mergeCommit={"oid": c})
        if "--delete-branch" in a:
            g("update-ref", "-d", "refs/heads/" + pr["headRefName"])
        if box.pop("merge_then_timeout", None):   # GitHub merged, gh gave up, and GitHub stops answering
            box["down"] = True
            out(124, "", "gh timed out")
        out(0, json.dumps({"sha": c, "merged": True, "message": "Pull Request successfully merged"}) if rmerge
            else "merged")
    if a[:3] == ["api", "-X", "PUT"] and a[3].endswith("/update-branch"):   # GitHub merges main into the branch
        pr = prs[a[3].split("/")[-2]]
        box.setdefault("updates", []).append(a[3:])
        if box.get("update_fail"):
            out(1, "", box["update_fail"])
        head = g("rev-parse", "refs/heads/" + pr["headRefName"])
        if a[a.index("-f") + 1] != "expected_head_sha=" + head:
            out(1, "", "gh: expected head sha didn't match current head ref. (HTTP 422)")
        tree = g("merge-tree", "--write-tree", "refs/heads/main", head).splitlines()[0]
        c = g("commit-tree", tree, "-p", head, "-p", "refs/heads/main", "-m", "Merge branch 'main'")
        g("update-ref", "refs/heads/" + pr["headRefName"], c)
        box["behind"] = bool(box.get("stay_behind"))
        out(0, json.dumps({"message": "Updating pull request branch.", "url": "x"}))
    if a[:1] == ["api"] and a[1].endswith("/annotations"):   # repos/<slug>/check-runs/<id>/annotations
        out(0, json.dumps(box.get("annotations", {}).get(a[1].split("/")[-2], [])))
    if a[:1] == ["api"] and ("/actions/jobs/" in a[1] or "/check-runs/" in a[1]):   # one job, one check run
        got = box.get("jobs" if "/actions/jobs/" in a[1] else "check_runs", {}).get(a[1].split("/")[-1])
        out(0, json.dumps(got)) if got is not None else out(1, "", "gh: Not Found (HTTP 404)")
    if a[:1] == ["api"] and "/actions/workflows?" in a[1]:   # gh.workflows_on: box["workflows"], else GitHub is down
        out(0, json.dumps({"workflows": box["workflows"]})) if "workflows" in box else out(1, "", "HTTP 502")
    if a[:2] == ["run", "rerun"]:   # a rerun GitHub accepts; after_rerun is every PR's rollup from then on
        box.setdefault("reruns", []).append(a[2])
        for pr in prs.values():
            if "after_rerun" in box:
                pr["statusCheckRollup"] = box["after_rerun"]
        out(0)
    out(1, "", "fake gh: unknown call")
if me == "cc-config":
    v = box.get("config", {}).get(a[1])
    if v is False:
        out(3, "", "cannot read config")
    out(0, v) if v is not None else out(1)
if me == "cc-pause":
    out(0 if a[1] in box.get("paused", []) else 1)
if me == "cc-tier":
    out(1 if box.get("tier_stop") else 0)
if me == "cc-gh-token" and a[0] == "--workspace":   # the helper's get: app_token, the credential protocol
    box["cred_in"] = sys.stdin.read()
    out(0, f"username=x-access-token\npassword={box['app_token']}") if box.get("app_token") else out(1, "", "refused")
if me == "cc-gh-token" and a[0] == "gitargs":   # gitargs: {handle: the lines it prints}
    out(box.get("gitargs_rc", 0), box.get("gitargs", {}).get(a[2] if len(a) > 2 else "", ""))
if me == "cc-gh-token":   # member_repos: a list for any owner, or {owner: [names]} so the owner asked for counts;
    r = box.get("member_repos", [])   # ws_repos: {handle: {owner: [names]}} so the workspace asked for counts too
    if "ws_repos" in box:
        r = box["ws_repos"].get(a[1], {})
    out(0, "\n".join(r.get(a[2] if len(a) > 2 else "", []) if isinstance(r, dict) else r))
if me == "cc":
    if a[0] == "done":
        out(0, json.dumps(box["receipt"]))
    if "--say" in a:   # a repair round typed to a live seat
        out(box.get("say_rc", box.get("go_rc", 0)), box.get("say_out", box.get("go_out", "")))
    if "--go" in a:   # a repair round's dispatch
        out(box.get("go_rc", 0), box.get("go_out", ""))
    out(box.get("lands", 0))
if me == "cc-board":
    p = os.path.join(os.environ["CC_BOARDS"], a[1] + ".json")
    b = json.load(open(p))
    row = b["tracks"][a[2]]
    if a[0] == "status":
        row["status"] = a[3]
    elif a[0] == "note":
        row.setdefault("notes", []).append(a[3])
    elif a[0] == "set":
        row[a[3]] = a[4]
    json.dump(b, open(p, "w"))
    out(0)
if me == "tmux":
    out(0, "\n".join(box.get("windows", [])))
if me == "systemctl":
    out(0, box.get("timers", ""))
if me == "systemd-run":
    out(0)
out(2, "", "fake: no such tool")
'''
FAKES = ("gh", "cc-config", "cc-pause", "cc-tier", "cc-gh-token", "cc", "cc-board", "tmux", "systemctl", "systemd-run")


# --- stub units ----------------------------------------------------------------------------------------------------

class Planner:
    def __init__(self, owners=None, paid=False, klass=T.LEAF):
        self.owners = dict(owners or {"a": "a/", "b": "b/", "c": "c/"})
        self.paid, self.klass, self.calls = paid, klass, []

    def plan(self, root, base, head, files, fallback=""):
        self.calls.append((base, head, tuple(files)))
        self.fallback = fallback
        checks = sorted(n for n, p in self.owners.items() if any(f.startswith(p) for f in files))
        return T.Plan(checks=checks, klass=self.klass, paid=self.paid)

    def checks(self, root, sha):
        return [T.Check(name=n, run="true") for n in self.owners]


class Runner:
    def __init__(self, status=None, hook=None, missing=(), notes=None):
        self.status, self.hook, self.calls, self.missing = dict(status or {}), hook, [], set(missing)
        self.notes = dict(notes or {})   # {name: the Outcome's note}, as run.judge says it (a flake's "flaky: …")
        self.plan_kw = []   # (only, express, lane) of each run_plan call
        self.firsts = []    # (pr, only, first) of each run_plan call: first is the admission's first claim (rule 4)

    def run_plan(self, root, m, plan, files, head_tree, base_tree="", *, member="", only=None, **kw):
        """lander.run.run_plan's shape: {name: Outcome}; a name in `missing` is one the manifest lacks."""
        from lander import run as RUN
        self.plan_kw.append((tuple(only or ()), kw.get("express", False), kw.get("lane", False)))
        first = kw.get("first")
        self.firsts.append((kw.get("pr"), tuple(only or ()), first() if callable(first) else first))
        out = {}
        for n in plan.checks:
            if only and n not in only:
                continue
            if n in self.missing:
                out[n] = RUN.Outcome(n, T.UNRUNNABLE, "not in the manifest")
                continue
            r = self.run(T.Check(name=n, run="true"), head_tree, f"member:{member}" if member else "box")
            out[n] = RUN.Outcome(n, r.status, self.notes.get(n, ""), [r])
        return out

    def run(self, check, tree, where):
        self.calls.append((check.name, tree, where))
        if self.hook:
            self.hook(check.name, len(self.calls))
        return T.Result(check=check.name, tree=tree, status=self.status.get(check.name, T.PASSED), secs=2.0)


class Reviewer:
    def __init__(self, *verdicts):
        self.verdicts, self.calls, self.stands = list(verdicts), [], None

    def digest_of(self, root, base, head):
        return "f" * 40

    def review(self, job):
        self.calls.append(("review", job.digest))
        return self.verdicts.pop(0)

    def delta_review(self, job, prior):
        self.calls.append(("delta", prior.verdict))
        return self.verdicts.pop(0)

    def standing(self, job):
        return self.stands


class Rec:
    """A unit that records each call. The lane's every-pass `positions` (the queued cards) goes to its own list, so
    `calls` reads as the events a case asserts."""
    def __init__(self):
        self.calls, self.positions_calls = [], []

    def positions(self, repo, jobs):
        self.positions_calls.append((repo, [(j.pr, j.state) for j in jobs]))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a: self.calls.append((name,) + a)


class SlowCards(Rec):
    """A cards unit whose queued cards hang, as a Slack that does not answer: positions waits until `go` is set."""
    def __init__(self):
        super().__init__()
        self.go = threading.Event()

    def positions(self, repo, jobs):
        super().positions(repo, jobs)
        self.go.wait(60)


def V(verdict, tokens=100, blocking=(), **extra):
    return T.Verdict(verdict=verdict, digest="", tokens=tokens, blocking=list(blocking), extra=extra)


# --- the fixture ---------------------------------------------------------------------------------------------------

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
SHARED = {}


def setUpModule():
    """The fakes, and one template origin + two clones every case copies (a clone per case costs the most)."""
    d = SHARED["dir"] = tempfile.mkdtemp(prefix="lander-shared-")
    SHARED["bin"] = os.path.join(d, "bin")
    os.makedirs(SHARED["bin"])
    for n in FAKES:
        p = os.path.join(SHARED["bin"], n)
        with open(p, "w") as f:
            f.write(FAKE.replace("PYTHON", sys.executable, 1))
        os.chmod(p, 0o755)
    env = dict(os.environ, **GIT_ENV)

    def git(cwd, *a):
        subprocess.run(["git", *a], cwd=cwd, env=env, check=True, capture_output=True)
    tpl = SHARED["tpl"] = os.path.join(d, "tpl")
    git(d, "init", "-q", "--bare", "-b", "main", f"{tpl}/origin.git")
    git(d, "clone", "-q", f"{tpl}/origin.git", f"{tpl}/work")
    for rel, text in {"a/x": "a1\n", "b/y": "b1\n", "c/z": "c1\n", "docs/r.md": "r\n"}.items():
        os.makedirs(os.path.dirname(f"{tpl}/work/{rel}"), exist_ok=True)
        with open(f"{tpl}/work/{rel}", "w") as f:
            f.write(text)
    git(f"{tpl}/work", "add", "-A")
    git(f"{tpl}/work", "commit", "-qm", "base")
    git(f"{tpl}/work", "push", "-q", "origin", "HEAD:refs/heads/main")
    git(d, "clone", "-q", f"{tpl}/origin.git", f"{tpl}/root")


def tearDownModule():
    shutil.rmtree(SHARED.get("dir", ""), ignore_errors=True)


def copy_repo(src, dst, old_origin, new_origin):
    shutil.copytree(src, dst, symlinks=True)
    cfg = os.path.join(dst, ".git", "config")
    if os.path.isfile(cfg):
        with open(cfg) as f:
            text = f.read()
        with open(cfg, "w") as f:
            f.write(text.replace(old_origin, new_origin))


class Fixture(unittest.TestCase):
    maxDiff = None
    bindir = property(lambda self: SHARED["bin"])

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lander-lane-")
        self.home = os.path.join(self.tmp, "home")
        self.origin = os.path.join(self.tmp, "origin.git")
        self.work = os.path.join(self.tmp, "work")
        self.box_path = os.path.join(self.tmp, "box.json")
        env = {"HOME": self.home, "CC_LANDER_STATE": f"{self.home}/.cc/state/land",
               "CC_LAND_STATE": f"{self.home}/.cc/state/land", "CC_BIN": self.bindir,
               "CC_DEV": f"{self.home}/dev", "CC_BOARDS": f"{self.home}/.cc/boards",
               "CC_MEMBERS": f"{self.home}/.cc/members", "PATH": self.bindir + os.pathsep + os.environ["PATH"],
               "FAKE_BOX": self.box_path, **GIT_ENV, "LANDER_TMUX": f"{self.bindir}/tmux",
               "LANDER_SYSTEMD_RUN": f"{self.bindir}/systemd-run", "LANDER_SYSTEMCTL": f"{self.bindir}/systemctl"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for k in ("GH_TOKEN", "CC_SLACK_ALIAS"):
            os.environ.pop(k, None)
        # nothing reads the box's own ~/.cc/state/land or config: every state root falls back to the passwd home
        for name, val in (("PASSWD_HOME", self.home), ("REVIEWER_CONFIG", os.path.join(self.home, ".cc", "config"))):
            p = mock.patch.object(C, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.environ["CC_BOARDS"])
        tpl = SHARED["tpl"]
        self.root = f"{self.home}/dev/demo"
        shutil.copytree(f"{tpl}/origin.git", self.origin, symlinks=True)
        copy_repo(f"{tpl}/work", self.work, f"{tpl}/origin.git", self.origin)
        copy_repo(f"{tpl}/root", self.root, f"{tpl}/origin.git", self.origin)
        self.set_box(origin=self.origin, prs={}, config={}, paused=[])
        self.pin_remote(self.root, self.origin)
        p = mock.patch.object(G, "ALLOW_LOCAL", True)   # the pinned URL is this bare repo, not GitHub
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(GH, "slug", lambda root: "o/demo")   # GitHub's name for it: the lane asks over REST
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(GH._VIEWER, clear=True)   # each case's gh says its own login
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(GH._WORKFLOWS, clear=True)   # each case's GitHub lists its own workflows
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(L, "spawn_tick", lambda repo: (True, "test"))
        p.start()
        self.addCleanup(p.stop)

    # helpers
    def pin_remote(self, root, url):
        """What `lander-self promote` writes: the URL the lander fetches this checkout from."""
        p = f"{self.home}/.cc/lander/remotes.json"
        os.makedirs(os.path.dirname(p), exist_ok=True)
        pins = json.load(open(p)) if os.path.exists(p) else {}
        pins[os.path.realpath(root)] = url
        with open(p, "w") as f:
            json.dump(pins, f)

    def git(self, cwd, *a):
        return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    def write(self, root, files):
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(root, rel)) or root, exist_ok=True)
            with open(os.path.join(root, rel), "w") as f:
                f.write(text)

    def box(self):
        with open(self.box_path) as f:
            return json.load(f)

    def set_box(self, **kw):
        b = self.box() if os.path.exists(self.box_path) else {}
        b.update(kw)
        with open(self.box_path, "w") as f:
            json.dump(b, f)

    def push(self, branch, files, base="main", fresh=True):
        """A commit on `branch` (from origin/<base> when fresh, else on the branch's tip) pushed to origin."""
        self.git(self.work, "fetch", "-q", "origin")
        start = f"origin/{base}" if fresh else f"origin/{branch}"
        self.git(self.work, "checkout", "-q", "-B", branch, start)
        self.write(self.work, files)
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-qm", f"{branch} {sorted(files)}")
        self.git(self.work, "push", "-q", "-f", "origin", f"{branch}:refs/heads/{branch}")
        return self.git(self.work, "rev-parse", "HEAD")

    def origin_rev(self, ref):
        return self.git(self.tmp, "--git-dir", self.origin, "rev-parse", ref)

    def pr(self, num, files, branch=None, **kw):
        branch = branch or f"track/row-{num}"
        head = self.push(branch, files)
        b = self.box()
        b["prs"][str(num)] = {"headRefName": branch, "title": f"row {num} change", **kw}
        self.set_box(prs=b["prs"])
        return head

    def units(self, **kw):
        u = {"planner": Planner(), "runner": Runner(), "reviewer": Reviewer(), "cards": Rec(), "board": Rec(),
             "deploy": Rec(), "tip": Rec()}
        u.update(kw)
        return u

    def queue(self, *argv):
        o, e = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
            rc = L.cmd_queue(list(argv))
        return rc, o.getvalue(), e.getvalue()

    def land(self, repo="demo", **units):
        u = self.units(**units)
        lines = L.Lane(repo, u).run()
        return u, lines

    def log(self):
        try:
            with open(E.log_path()) as f:
                return f.read()
        except OSError:
            return ""

    def job(self, pr=1, repo="demo"):
        return J.load(repo, pr)

    def main_red(self, *names, repo="demo"):
        """main's own record (health.py) holds `names` red at origin/main's tip."""
        path = HL.path(repo)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"tip": self.origin_rev("main"),
                       "checks": {n: {"status": T.FAILED, "at": E.stamp(time.time())} for n in names}}, f)


# --- the cases -----------------------------------------------------------------------------------------------------

class Intake(Fixture):
    def test_queue_writes_a_request_and_drain_makes_the_job(self):
        self.pr(1, {"docs/r.md": "new\n"})
        rc, out, err = self.queue("demo", "1", "--no-start", "--who", "w", "--chat", "C1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(J.requests("demo")), 1)
        self.assertFalse(os.path.exists(J.job_path("demo", 1)))   # the queue never writes the job itself
        self.assertIn("queued demo#1 who=w chat=C1", self.log())
        with J.lane_lock("demo") as got:
            self.assertTrue(got)
            self.assertEqual(J.drain("demo"), ["demo#1 queued"])
        d = J.read_json(J.job_path("demo", 1))
        self.assertEqual((d["state"], d["stage"], d["chat"], d["who"]), ("queued", "queued", "C1", "w"))
        self.assertEqual(J.requests("demo"), [])

    def test_queue_first_puts_a_queued_pr_at_the_front_and_says_who(self):
        for n in (1, 2, 3):
            self.pr(n, {f"docs/r{n}.md": "new\n"})
            self.assertEqual(self.queue("demo", str(n), "--no-start")[0], 0)
        with J.lane_lock("demo"):
            J.drain("demo")
        self.assertEqual([j.pr for j in J.lane_jobs("demo")], [1, 2, 3])   # no stamp: queued order
        self.assertEqual(L.place("demo", 3), "it waits behind 2 job(s) in the demo lane")
        rc, out, err = self.queue("demo", "3", "--no-start", "--first", "--who", "seat-x")
        self.assertEqual(rc, 0, err)
        self.assertEqual([j.pr for j in J.lane_jobs("demo")], [3, 1, 2])
        self.assertEqual(J.first("demo", 3)["by"], "seat-x")
        self.assertEqual(J.first("demo", 1), {})
        self.assertIn("\tfirst demo#3 who=seat-x", self.log())
        self.assertEqual(L.place("demo", 3), "PR #3 was put first by seat-x; nothing is ahead of it")
        self.assertIn("put first by seat-x; nothing is ahead", out)

    def test_two_prs_put_first_go_oldest_stamp_first(self):
        for n in (1, 2, 3):
            self.pr(n, {f"docs/r{n}.md": "new\n"})
            J.submit("demo", n)
        with J.lane_lock("demo"):
            J.drain("demo")
        os.makedirs(os.path.dirname(J.first_path("demo", 2)))
        J.write_atomic(J.first_path("demo", 2), {"by": "owner", "at": E.stamp(time.time() + 60)})
        J.write_atomic(J.first_path("demo", 3), {"by": "seat", "at": E.stamp(time.time())})
        J.write_atomic(J.first_path("demo", 1), {"by": 7, "at": "not a stamp"})   # not a record: not first
        self.assertEqual([j.pr for j in J.lane_jobs("demo")], [3, 2, 1])
        self.assertEqual(L.place("demo", 2), "PR #2 was put first by owner; it waits behind 1 job(s) in the demo lane")

    def test_place_of_a_pr_put_first_before_its_request_is_drained(self):
        for n in (1, 2, 3):
            self.pr(n, {f"docs/r{n}.md": "new\n"})
            J.submit("demo", n)
        self.pr(4, {"docs/r4.md": "new\n"})
        with J.lane_lock("demo"):
            J.drain("demo")
        os.makedirs(os.path.dirname(J.first_path("demo", 2)))
        J.write_atomic(J.first_path("demo", 2), {"by": "owner", "at": E.stamp(time.time() - 60)})   # before #4
        J.write_atomic(J.first_path("demo", 3), {"by": "owner", "at": E.stamp(time.time() + 60)})   # after it
        J.write_atomic(J.first_path("demo", 1), {"by": "x", "at": "~"})   # not a stamp: not put first
        self.assertEqual(L.place("demo", 4), "it waits behind 3 job(s) in the demo lane")   # not put first: behind all
        rc, out, err = self.queue("demo", "4", "--no-start", "--first", "--who", "seat-x")
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(J.requests("demo")), 1)   # not drained yet
        self.assertIn("PR #4 was put first by seat-x; it waits behind 1 job(s) in the demo lane", out)

    def test_a_second_queue_of_a_live_job_writes_no_queued_line(self):
        self.pr(1, {"docs/r.md": "new\n"})
        self.assertEqual(self.queue("demo", "1", "--no-start")[0], 0)
        with J.lane_lock("demo"):
            J.drain("demo")
        self.assertEqual(self.queue("demo", "1", "--no-start")[0], 0)
        with J.lane_lock("demo"):
            self.assertEqual(J.drain("demo"), ["demo#1 again"])
        self.assertEqual(self.log().count("\tqueued demo#1 "), 1)   # the first queue's line only; `times` is not reset
        self.assertIn("\tagain demo#1", self.log())

    def test_again_vs_requeued(self):
        J.submit("demo", 1, chat="C1")
        with J.lane_lock("demo"):
            J.drain("demo")
        J.submit("demo", 1, chat="C2", ts="T2")       # active job: fills only what is empty
        with J.lane_lock("demo"):
            self.assertEqual(J.drain("demo"), ["demo#1 again"])
        j = self.job()
        self.assertEqual((j.extra["chat"], j.extra["ts"]), ("C1", "T2"))
        j.reads_used, j.extra["verdict"] = 1, V(T.HANDBACK_VERDICT).to_dict()
        J.move(j, T.QUERY, "x")
        J.submit("demo", 1, who="again")               # at rest: a fresh start keeping reads and verdict
        with J.lane_lock("demo"):
            self.assertEqual(J.drain("demo"), ["demo#1 requeued"])
        j = self.job()
        self.assertEqual((j.state, j.reads_used, j.extra["verdict"]["verdict"]), (T.QUEUED, 1, "HANDBACK"))
        self.assertIn("again demo#1", self.log())
        self.assertIn("requeued demo#1", self.log())

    def test_box_held_job_is_joined_not_restarted(self):
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        j = self.job()
        j.extra.update(hold="box", held_from=T.CHECKING)
        J.move(j, T.HELD, "usage wall")
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            self.assertEqual(J.drain("demo"), ["demo#1 again"])
        self.assertEqual(self.job().state, T.HELD)

    def test_bad_shapes_refused(self):
        self.assertEqual(self.queue("de mo", "1")[0], 2)
        self.assertEqual(self.queue("demo", "x")[0], 2)
        self.assertEqual(self.queue("demo", "1", "extra")[0], 2)

    def test_queue_starts_the_lane_or_says_it_did_not(self):
        self.pr(1, {"docs/r.md": "n\n"})
        started = []
        with mock.patch.object(L, "spawn_tick", lambda r: (started.append(r) or True, "pid 1")):
            self.assertEqual(self.queue("demo", "1")[0], 0)
        self.assertEqual(started, ["demo"])
        with mock.patch.object(L, "spawn_tick", lambda r: (False, "no fork")):
            rc, _, err = self.queue("demo", "1")
        self.assertEqual(rc, 1)
        self.assertIn("queued, but", err)

    def test_paused_keeps_the_request(self):
        self.pr(1, {"docs/r.md": "n\n"})
        self.set_box(paused=["demo"])
        with mock.patch.object(L, "spawn_tick", side_effect=AssertionError("started")):
            rc, out, _ = self.queue("demo", "1")
        self.assertEqual(rc, 0)
        self.assertIn("paused", out)
        self.assertEqual(len(J.requests("demo")), 1)


class Members(Fixture):
    def make_member(self, token=True):
        os.makedirs(f"{self.home}/dev/alice/.cc")
        open(f"{self.home}/dev/alice/.cc/member-workspace", "w").close()
        with open(f"{os.environ['CC_BOARDS']}/alice.json", "w") as f:
            json.dump({"tracks": {"proj": {"pr": "https://github.com/own/proj/pull/1"}}}, f)
        self.set_box(config={"CC_GH_PERSONAL_OWNER": "own"}, member_repos=["proj"])
        if token:
            d = f"{self.home}/.cc/members/alice"
            os.makedirs(d)
            real = f"{self.tmp}/tok"
            with open(real, "w") as f:
                f.write("tok-value\n")
            os.chmod(real, 0o600)
            os.symlink(real, f"{d}/github-token")
        # the host-only clone, made ahead as a clone of the fixture origin (member_clone keeps an existing one)
        self.git(self.tmp, "clone", "-q", self.origin, f"{J.clones_dir()}/alice--proj")
        # that bare repo stands in for github.com/own/proj, the row's URL, as ALLOW_LOCAL lets it stand in for a pin:
        # an owner the credential choice cannot read would take the app's door (link_door fails closed)
        real = M.url_owner
        p = mock.patch.object(M, "url_owner", lambda url: "own" if url == self.origin else real(url))
        p.start()
        self.addCleanup(p.stop)

    def test_workspace_and_no_token_refused(self):
        self.make_member(token=False)
        self.assertEqual(M.member_of("alice--proj"), ("alice", "proj"))
        self.assertEqual(M.member_of("bob--proj"), ("", ""))          # no marker: not a member, whatever the name
        self.assertEqual(self.queue("alice", "1")[0], 2)
        rc, _, err = self.queue("alice--proj", "1")
        self.assertEqual(rc, 1)
        self.assertIn("refused alice--proj#1 no-token", self.log())
        self.assertEqual(J.requests(), [])

    def test_granted_member_is_queued_and_wrong_repo_refused(self):
        self.make_member()
        self.assertEqual(M.member_token("alice"), "tok-value")
        self.pr(1, {"docs/r.md": "n\n"})
        with mock.patch.object(M, "member_clone", lambda repo, url: (f"{J.clones_dir()}/{repo}", "")):
            rc, _, err = self.queue("alice--proj", "1", "--no-start")
            self.assertEqual(rc, 0, err)
            self.assertIn("queued alice--proj#1", self.log())
            rc, _, err = self.queue("alice--proj", "2", "--no-start")   # the board row carries #1, not #2
        self.assertEqual(rc, 1)
        self.assertIn("refused alice--proj#2 not-its-repository", self.log())

    def test_a_first_member_clone_really_clones_with_gh_config_outside_it(self):
        # git itself, not a stub: a GH_CONFIG_DIR made inside the clone dir left it non-empty and `git clone … .`
        # refused every first clone ("destination path '.' already exists and is not an empty directory")
        self.make_member()
        shutil.rmtree(J.clones_dir())   # a fresh box: no clones dir at all yet
        seen, real_run = [], M.run
        def spy(argv, cwd=None, timeout=60, env=None):
            seen.append((argv, cwd, dict(env or {})))
            return real_run(argv, cwd=cwd, timeout=timeout, env=env)
        with mock.patch.object(M, "run", spy):
            root, why = M.member_clone("alice--proj", self.origin)
        self.assertEqual((root, why), (f"{J.clones_dir()}/alice--proj", ""))
        self.assertTrue(os.path.isdir(f"{root}/.git"))
        self.assertEqual(self.git(root, "rev-parse", "origin/main"), self.git(self.origin, "rev-parse", "main"))
        clone = [e for a, _, e in seen if a[:2] == ["git", "clone"]]
        self.assertEqual(len(clone), 1)
        ghc = clone[0]["GH_CONFIG_DIR"]
        self.assertEqual(clone[0]["GH_TOKEN"], "tok-value")
        self.assertFalse(os.path.realpath(ghc).startswith(os.path.realpath(root) + os.sep), ghc)
        self.assertEqual(os.listdir(ghc), [])
        self.assertEqual(stat.S_IMODE(os.stat(ghc).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(ghc)).st_mode), 0o700)
        self.assertFalse(os.path.exists(f"{root}/.gh-none"))
        # gh with a member's token uses that same dir, never one inside the clone
        with mock.patch.object(GH.subprocess, "run", side_effect=OSError("no gh")) as r:
            GH.gh(["pr", "view", "1"], root, token="tok-value")
        self.assertEqual(r.call_args.kwargs["env"]["GH_CONFIG_DIR"], ghc)
        self.assertFalse(os.path.exists(f"{root}/.gh-none"))
        # the existing-clone branch keeps the clone and only re-points origin
        self.assertEqual(M.member_clone("alice--proj", self.origin), (root, ""))

    def converted(self):
        """The layout a converted workspace has: BOARDS/alice.json is a link into MEMBERS/alice/board/."""
        d = f"{self.home}/.cc/members/alice/board"
        os.makedirs(d)
        os.replace(f"{os.environ['CC_BOARDS']}/alice.json", f"{d}/alice.json")
        os.symlink(f"{d}/alice.json", f"{os.environ['CC_BOARDS']}/alice.json")
        return f"{d}/alice.json"

    def test_a_converted_workspace_row_is_read_through_its_link(self):
        self.make_member()
        self.converted()
        self.assertEqual(J.board("alice"), {})   # the box's own reader still refuses the link
        self.assertEqual(M.member_board("alice")["tracks"]["proj"]["pr"], "https://github.com/own/proj/pull/1")
        self.assertIn("proj", L.BoardRules().board("alice")["tracks"])   # …so a merge can mark the row merged
        self.pr(1, {"docs/r.md": "n\n"})
        with mock.patch.object(M, "member_clone", lambda repo, url: (f"{J.clones_dir()}/{repo}", "")):
            rc, _, err = self.queue("alice--proj", "1", "--no-start")
        self.assertEqual(rc, 0, err)
        self.assertIn("queued alice--proj#1", self.log())

    def test_a_link_or_fifo_at_the_members_board_is_not_followed(self):
        self.make_member()
        p = self.converted()
        elsewhere = f"{self.tmp}/elsewhere.json"
        os.replace(p, elsewhere)
        os.symlink(elsewhere, p)   # what a member could leave at that name from inside
        self.assertEqual(M.member_board("alice"), {})
        rc, _, err = self.queue("alice--proj", "1", "--no-start")
        self.assertEqual(rc, 1)
        self.assertIn("does not carry PR #1", err)
        os.unlink(p)
        os.mkfifo(p)   # opened without O_NONBLOCK this would hang the door
        self.assertEqual(M.member_board("alice"), {})
        self.assertEqual(M.member_board("bob"), {})   # no marker: no member, no board

    def test_a_malformed_or_oversized_members_board_reads_as_no_row(self):
        self.make_member()
        p = self.converted()
        for body in ("[" * 200000, '{"tracks": [1]}', '{"tracks": {"proj": "x"}}'):
            with open(p, "w") as f:
                f.write(body)
            self.assertEqual(M.member_board("alice").get("tracks") or {}, {}, body[:20])
            rc, _, err = self.queue("alice--proj", "1", "--no-start")
            self.assertEqual(rc, 1, body[:20])
            self.assertIn("does not carry PR #1", err)
        with open(p, "w") as f:
            json.dump({"tracks": {"proj": {"pr": "https://github.com/own/proj/pull/1"}}}, f)
        self.assertIn("proj", M.member_board("alice")["tracks"])   # control: the same file, well formed, is read
        with mock.patch.object(M, "BOARD_MAX", 10):
            self.assertEqual(M.member_board("alice"), {})

    def org_grant(self, target, org_repos=("proj",)):
        """The grant `cc-sandbox github alice <file>` makes: MEMBERS/alice/github-token, a link to `target`."""
        os.makedirs(f"{self.home}/.cc/secrets", exist_ok=True)
        full = os.path.normpath(os.path.join(f"{self.home}/.cc/members/alice", target))
        if os.path.dirname(full) == f"{self.home}/.cc/secrets":
            with open(full, "w") as f:
                f.write("org-token\n")
            os.chmod(full, 0o600)
        g = f"{self.home}/.cc/members/alice/github-token"
        os.unlink(g)
        os.symlink(target, g)
        self.set_box(member_repos={"own": ["proj"], "acme": list(org_repos)})

    def row_pr(self, url):
        with open(f"{os.environ['CC_BOARDS']}/alice.json", "w") as f:
            json.dump({"tracks": {"proj": {"pr": url}}}, f)

    def test_granted_orgs_come_from_the_links_name_alone(self):
        self.make_member()
        sec = f"{self.home}/.cc/secrets"
        self.assertEqual(M.granted_orgs("alice"), set())   # a link outside ~/.cc/secrets grants no org
        self.org_grant(f"{sec}/github-alice-acme.token")
        self.assertEqual(M.granted_orgs("alice"), {"acme"})
        self.org_grant("../../secrets/github-alice-acme.token")   # relative, as ln -s may write it
        self.assertEqual(M.granted_orgs("alice"), {"acme"})
        for bad in (f"{sec}/alice-github.token", f"{sec}/github-personal.token", f"{sec}/github-bob-acme.token",
                    f"{sec}/github-alice-.token", f"{sec}/github-alice-a_b.token", f"{sec}/sub/github-alice-acme.token",
                    f"{self.tmp}/github-alice-acme.token", f"{sec}/../github-alice-acme.token"):
            self.org_grant(bad)
            self.assertEqual(M.granted_orgs("alice"), set(), bad)
        self.assertEqual(M.granted_orgs("../alice"), set())

    def test_a_granted_orgs_row_reaches_a_queued_job_and_an_ungranted_one_is_refused(self):
        # board row → member_project_url → queued job, for a repository in the org the host granted the token for
        self.make_member()
        self.org_grant(f"{self.home}/.cc/secrets/github-alice-acme.token")
        self.row_pr("https://github.com/ACME/proj/pull/1")
        self.pr(1, {"docs/r.md": "n\n"})
        urls = []

        def clone(repo, url):
            urls.append(url)
            return f"{J.clones_dir()}/{repo}", ""
        with mock.patch.object(M, "member_clone", clone):
            rc, _, err = self.queue("alice--proj", "1", "--no-start")
        self.assertEqual(rc, 0, err)
        self.assertIn("queued alice--proj#1", self.log())
        self.assertEqual(urls, ["https://github.com/acme/proj.git"])   # the host's spelling of the owner, not the row's
        self.assertIn(["cc-gh-token", "repos", "alice", "acme"], self.box()["calls"])
        self.assertEqual([(r["repo"], r["pr"]) for _, r in J.requests()], [("alice--proj", 1)])   # the queued job
        # an org the host granted nothing for: refused before any token or clone, whatever the row says
        self.row_pr("https://github.com/evil-org/proj/pull/2")
        self.set_box(calls=[])
        with mock.patch.object(M, "member_clone", clone):
            rc, _, err = self.queue("alice--proj", "2", "--no-start")
        self.assertEqual(rc, 1)
        self.assertIn("refused alice--proj#2 not-its-repository", self.log())
        self.assertIn("evil-org/proj is not under an account this workspace was granted (acme, own)", err)
        self.assertFalse([c for c in self.box()["calls"] if c[0] == "cc-gh-token"])
        self.assertEqual(urls, ["https://github.com/acme/proj.git"])
        self.assertEqual(len(J.requests()), 1)
        # the granted org, but a repository the workspace does not own there: still refused
        self.row_pr("https://github.com/acme/other/pull/3")
        rc, _, err = self.queue("alice--proj", "3", "--no-start")
        self.assertEqual(rc, 1)
        self.assertIn("acme/other is not a repository of workspace alice", err)

    def test_an_app_org_row_reaches_a_queued_job_and_nothing_wider_does(self):
        # a workspace with no org token pushes to the app's org with cc-gh-token's installation token; its PR there
        # is accepted when the host configured that installation and `cc-gh-token repos <h> <org>` lists the name
        self.make_member()
        self.set_box(config={"CC_GH_PERSONAL_OWNER": "own", "CC_GH_APP_OWNER": "appco", "CC_GH_APP_INSTALL_ID": "1"},
                     ws_repos={"alice": {"own": ["proj"], "appco": ["proj"]}, "bob": {"appco": ["bobs"]}})
        self.assertEqual(M.granted_orgs("alice"), set())   # no org token: the app org is the only door here
        self.row_pr("https://github.com/AppCo/proj/pull/1")
        self.pr(1, {"docs/r.md": "n\n"})
        urls = []

        def clone(repo, url):
            urls.append(url)
            return f"{J.clones_dir()}/{repo}", ""
        with mock.patch.object(M, "member_clone", clone):
            rc, _, err = self.queue("alice--proj", "1", "--no-start")
        self.assertEqual(rc, 0, err)
        self.assertIn("queued alice--proj#1", self.log())
        self.assertEqual(urls, ["https://github.com/appco/proj.git"])   # the host's spelling of the owner, not the row's
        self.assertIn(["cc-gh-token", "repos", "alice", "appco"], self.box()["calls"])
        # another workspace's repository in the app org: the membership check still runs, for alice, and refuses
        self.row_pr("https://github.com/appco/bobs/pull/2")
        rc, _, err = self.queue("alice--proj", "2", "--no-start")
        self.assertEqual(rc, 1)
        self.assertIn("appco/bobs is not a repository of workspace alice", err)
        # a repository in no workspace's list
        self.row_pr("https://github.com/appco/other/pull/3")
        rc, _, err = self.queue("alice--proj", "3", "--no-start")
        self.assertEqual(rc, 1)
        self.assertIn("appco/other is not a repository of workspace alice", err)
        # an org with no installation for this box: refused before cc-gh-token is asked
        self.row_pr("https://github.com/elsewhere/proj/pull/4")
        self.set_box(calls=[])
        rc, _, err = self.queue("alice--proj", "4", "--no-start")
        self.assertEqual(rc, 1)
        self.assertIn("elsewhere/proj is not under an account this workspace was granted (appco, own)", err)
        self.assertFalse([c for c in self.box()["calls"] if c[0] == "cc-gh-token"])
        # the app org named but no installation configured: not accepted, the same refusal
        self.set_box(config={"CC_GH_PERSONAL_OWNER": "own", "CC_GH_APP_OWNER": "appco"})
        self.assertEqual(M.app_org(), "")
        self.row_pr("https://github.com/appco/proj/pull/5")
        rc, _, err = self.queue("alice--proj", "5", "--no-start")
        self.assertEqual(rc, 1)
        self.assertIn("appco/proj is not under an account this workspace was granted (own)", err)
        self.assertEqual(urls, ["https://github.com/appco/proj.git"])
        self.assertEqual(len(J.requests()), 1)

    def app_box(self):
        helper = "!/x/cc-gh-token --workspace alice"
        self.set_box(config={"CC_GH_PERSONAL_OWNER": "own", "CC_GH_APP_OWNER": "appco", "CC_GH_APP_INSTALL_ID": "1"},
                     ws_repos={"alice": {"own": ["proj"], "appco": ["proj"]}},
                     gitargs={"alice": f"-c\ncredential.helper=\n-c\ncredential.helper={helper}\n-c\ncredential.useHttpPath=true"})
        return helper

    def clone_spy(self, url):
        """member_clone on a fresh box with git clone itself stubbed: the argv and env each call got."""
        shutil.rmtree(J.clones_dir())
        seen, real_run = [], M.run

        def spy(argv, cwd=None, timeout=60, env=None):
            seen.append((argv, dict(env or {})))
            return (0, "", "") if argv[:2] == ["git", "clone"] else real_run(argv, cwd=cwd, timeout=timeout, env=env)
        with mock.patch.object(M, "run", spy):
            self.assertEqual(M.member_clone("alice--proj", url)[1], "")
        return [(a, e) for a, e in seen if a[:2] == ["git", "clone"]][0], [a for a, _ in seen]

    def test_an_app_org_clone_and_fetch_use_the_app_helper_not_the_link(self):
        self.make_member()
        helper = self.app_box()
        (argv, cenv), calls = self.clone_spy("https://github.com/appco/proj.git")
        self.assertIn([f"{J.bin_dir()}/cc-gh-token", "gitargs", "https://github.com/appco/proj.git", "alice"], calls)
        self.assertEqual((cenv["GIT_CONFIG_COUNT"], cenv["GIT_CONFIG_KEY_0"], cenv["GIT_CONFIG_VALUE_0"]),
                         ("3", "credential.helper", ""))   # the reset first: gh's helper never answers
        self.assertEqual((cenv["GIT_CONFIG_KEY_1"], cenv["GIT_CONFIG_VALUE_1"]), ("credential.helper", helper))
        self.assertFalse([x for x in argv if "tok-value" in x or "cc-gh-token" in x])   # nothing of it in argv
        self.assertEqual(cenv["GIT_TERMINAL_PROMPT"], "0")   # a refused helper fails the clone, never waits on a tty
        # every later fetch: env() reads the clone's URL, the one the lander fetches from
        root = f"{J.clones_dir()}/alice--proj"
        self.git(self.tmp, "clone", "-q", self.origin, root)
        self.git(root, "remote", "set-url", "origin", "https://github.com/appco/proj.git")
        e = M.env("alice", "alice--proj")
        self.assertEqual(e["GIT_CONFIG_VALUE_1"], helper)
        self.assertNotIn("GH_TOKEN", e)   # the link's token rides along nowhere on the app's door
        with open(f"{root}/.git/config") as f:
            self.assertNotIn("cc-gh-token", f.read())
        # gitargs names no helper: no credential at all, never a fall back to gh's
        self.set_box(gitargs={})
        self.assertEqual({k: v for k, v in M.env("alice", "alice--proj").items() if k.startswith("GIT_")},
                         M.NO_CREDENTIAL)
        # the app org that is also an org the workspace holds a token for keeps the link's path
        self.org_grant(f"{self.home}/.cc/secrets/github-alice-appco.token")
        self.set_box(config={"CC_GH_APP_OWNER": "appco", "CC_GH_APP_INSTALL_ID": "1"})
        self.assertTrue(M.link_door("alice", "appco"))
        self.assertFalse(M.link_door("bob", "AppCo"))

    def test_env_with_no_repo_has_no_door_and_hands_out_no_token(self):
        # no clone URL to choose a door by: never the link's token (a publish fetch reads member_token itself)
        self.make_member()
        self.app_box()
        self.assertEqual(M.env("alice"), M.NO_CREDENTIAL)

    def test_hookless_env_merges_a_callers_git_config_under_its_own_pins(self):
        # a caller spreads members' env into hookless_env: a GIT_CONFIG_COUNT/KEY_0 of the caller's once
        # replaced the pins, so a fetch ran with the clone's hooks and commit-graph
        helper = "!/x/cc-gh-token --workspace alice"
        e = G.hookless_env(GIT_DIR="/x", GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="credential.helper", GIT_CONFIG_VALUE_0="",
                           GIT_CONFIG_KEY_1="credential.helper", GIT_CONFIG_VALUE_1=helper,
                           GIT_CONFIG_KEY_2="core.hooksPath", GIT_CONFIG_VALUE_2="/evil")
        pairs = [(e[f"GIT_CONFIG_KEY_{i}"], e[f"GIT_CONFIG_VALUE_{i}"]) for i in range(int(e["GIT_CONFIG_COUNT"]))]
        self.assertEqual(pairs, [("credential.helper", ""), ("credential.helper", helper), ("core.hooksPath", "/evil"),
                                 ("core.attributesFile", os.devnull), ("core.hooksPath", os.devnull),
                                 ("core.commitGraph", "false")])
        self.assertEqual(e["GIT_DIR"], "/x")
        # what git itself reads from it: the pin, last, wins over the caller's; the helpers keep their order
        got = lambda *a: subprocess.run(["git", "config", *a], env=dict(e, GIT_DIR=self.origin),  # noqa: E731
                                        capture_output=True, text=True).stdout.split("\n")[:-1]
        self.assertEqual(got("--get", "core.hooksPath"), [os.devnull])
        self.assertEqual(got("--get-all", "credential.helper"), ["", helper])
        self.assertEqual(G.hookless_env(GH_TOKEN="t")["GIT_CONFIG_COUNT"], "3")   # no entries of the caller's: as before
        for bad in ({"GIT_CONFIG_COUNT": "x"}, {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "a", "GIT_CONFIG_VALUE_0": "b"},
                    {"GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/evil"}, {"GIT_CONFIG_GLOBAL": "/evil"}):
            with self.assertRaises(ValueError, msg=bad):
                G.hookless_env(**bad)

    def test_app_gitenv_names_no_credential_on_any_doubt(self):
        self.make_member()
        url = "https://github.com/appco/proj.git"
        helper = self.app_box()
        good = f"-c\ncredential.helper=\n-c\ncredential.helper={helper}"
        self.assertEqual(M.app_gitenv("alice", url)["GIT_CONFIG_VALUE_1"], helper)   # control: a helper is named
        for why, box in (("rc", {"gitargs_rc": 1, "gitargs": {"alice": good}}),
                         ("odd", {"gitargs": {"alice": good + "\n-c"}}),
                         ("no --workspace", {"gitargs": {"alice": "-c\ncredential.helper=\n-c\n"
                                                                  "credential.helper=!/x/cc-gh-token"}})):
            self.set_box(**dict({"gitargs_rc": 0}, **box))
            self.assertEqual(M.app_gitenv("alice", url), M.NO_CREDENTIAL, why)

    def test_a_failed_or_slow_config_read_never_hands_out_the_links_token(self):
        # the link may be the owner's own token: a cc-config that fails or times out at Lane() once made every gh
        # call and fetch of an app-org PR run as the owner (review of #1079). Each read, each way, on both URLs.
        self.make_member()
        self.app_box()
        root = f"{J.clones_dir()}/alice--proj"
        real_run = M.subprocess.run
        for key in ("CC_GH_PERSONAL_OWNER", "CC_GH_APP_OWNER", "CC_GH_APP_INSTALL_ID"):
            for how in ("fails", "times out"):
                for url in ("https://github.com/appco/proj.git", "https://github.com/own/proj.git"):
                    if key != "CC_GH_PERSONAL_OWNER" and "own/" in url:
                        continue   # the owner's account reads only CC_GH_PERSONAL_OWNER
                    with self.subTest(key=key, how=how, url=url):
                        self.app_box()
                        cfg = dict(self.box()["config"])
                        if how == "fails":
                            cfg[key] = False
                        self.set_box(config=cfg, app_token="", gh_tokens=[])

                        def slow(argv, *a, **kw):
                            if argv[-2:] == ["get", key] and how == "times out":
                                raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
                            return real_run(argv, *a, **kw)
                        self.git(root, "remote", "set-url", "origin", url)
                        with mock.patch.object(M.subprocess, "run", slow):
                            lane = L.Lane("alice--proj", units={})
                        self.assertTrue(callable(lane.token))
                        self.assertNotIn("GH_TOKEN", lane.genv or {})
                        self.assertEqual(GH.pr_facts(root, 1, "state", lane.token)[0], None)
                        self.assertEqual(self.box()["gh_tokens"], [])   # gh never ran, as the link or the box
        # control: the same reads answering keep the owner's account on the link's token
        self.app_box()
        self.git(root, "remote", "set-url", "origin", "https://github.com/own/proj.git")
        self.assertEqual(M.gh_token("alice", "alice--proj"), "tok-value")
        self.assertEqual((M.config_read("CC_GH_PERSONAL_OWNER"), M.config_read("NOT_SET")), ("own", ""))
        self.set_box(config={"CC_GH_PERSONAL_OWNER": False})
        self.assertIsNone(M.config_read("CC_GH_PERSONAL_OWNER"))
        self.assertEqual(M.config("CC_GH_PERSONAL_OWNER", "d"), "d")   # the old readers keep their default

    def test_removing_the_install_id_with_a_job_queued_never_reaches_the_link(self):
        self.make_member()
        self.app_box()
        self.git(f"{J.clones_dir()}/alice--proj", "remote", "set-url", "origin", "https://github.com/appco/proj.git")
        self.row_pr("https://github.com/appco/proj/pull/1")
        self.pr(1, {"docs/r.md": "n\n"})
        with mock.patch.object(M, "member_clone", lambda repo, url: (f"{J.clones_dir()}/{repo}", "")):
            rc, _, err = self.queue("alice--proj", "1", "--no-start")
        self.assertEqual(rc, 0, err)
        # the host removes the installation; cc-gh-token then hands out no app token
        self.set_box(config={"CC_GH_PERSONAL_OWNER": "own", "CC_GH_APP_OWNER": "appco"}, app_token="", gh_tokens=[])
        u, _ = self.land("alice--proj")
        j = self.job(1, "alice--proj")
        self.assertNotEqual(j.state, T.DONE)
        self.assertIn("gh was not run", j.extra.get("why", ""))
        self.assertEqual((self.box()["gh_tokens"], self.box().get("merges", [])), ([], []))

    def test_the_watch_and_the_door_card_ask_gh_with_the_app_token(self):
        self.make_member()
        self.app_box()
        self.git(f"{J.clones_dir()}/alice--proj", "remote", "set-url", "origin", "https://github.com/appco/proj.git")
        self.set_box(app_token="app-tok", gh_tokens=[], prs={"1": {"state": "MERGED"}})   # read, then the watch ends
        os.makedirs(J.handed_dir(), exist_ok=True)
        J.write_atomic(f"{J.handed_dir()}/alice--proj-1.json",
                       {"repo": "alice--proj", "pr": 1, "branch": "", "head": "", "until": "2999-01-01T00:00:00Z"})
        TK.sweep_handed()   # tick's pr_facts on a handed-back member PR
        C._door_head(T.Job(repo="alice--proj", pr=1, member="alice"))   # the door card's head
        self.assertEqual(self.box()["gh_tokens"], ["app-tok", "app-tok"])

    def test_an_app_org_prs_gh_calls_carry_the_app_token_not_the_links(self):
        self.make_member()
        self.app_box()
        self.set_box(app_token="app-tok")
        root = f"{J.clones_dir()}/alice--proj"
        self.git(root, "remote", "set-url", "origin", "https://github.com/appco/proj.git")
        lane = L.Lane("alice--proj", units={})
        self.set_box(gh_tokens=[])
        GH.pr_facts(root, 1, "state", lane.token)
        self.assertEqual(self.box()["gh_tokens"], ["app-tok"])
        self.assertIn("path=appco/proj.git", self.box()["cred_in"])
        self.assertTrue([c for c in self.box()["calls"] if c[:4] == ["cc-gh-token", "--workspace", "alice", "get"]])
        # cc-gh-token refuses: gh is not run at all, so neither the link's token nor the box's login answers
        self.set_box(app_token="", gh_tokens=[])
        rc, _, err = GH.gh(["pr", "view", "1"], root, token=lane.token)
        self.assertEqual((rc, self.box()["gh_tokens"]), (1, []))
        self.assertIn("gh was not run", err)
        # the owner's account keeps the link's token
        self.git(root, "remote", "set-url", "origin", "https://github.com/own/proj.git")
        self.assertEqual(M.gh_token("alice", "alice--proj"), "tok-value")

    def test_a_personal_owner_clone_and_fetch_keep_the_links_token(self):
        self.make_member()
        self.app_box()
        (argv, cenv), calls = self.clone_spy("https://github.com/own/proj.git")
        self.assertEqual(cenv["GH_TOKEN"], "tok-value")
        self.assertFalse([k for k in cenv if k.startswith("GIT_CONFIG")])
        self.assertFalse([c for c in calls if "gitargs" in c])
        root = f"{J.clones_dir()}/alice--proj"
        self.git(self.tmp, "clone", "-q", self.origin, root)
        self.git(root, "remote", "set-url", "origin", "https://github.com/own/proj.git")
        self.assertEqual(M.env("alice", "alice--proj"), {"GH_TOKEN": "tok-value"})

    def test_walls(self):
        self.make_member()
        base = self.origin_rev("main")
        ok = self.push("t-ok", {"docs/r.md": "fine\n"})
        cc = self.push("t-cc", {".cc/member-workspace": "x\n"})
        tok = self.push("t-tok", {"b/y": "key = ghp_" + "A" * 36 + "\n"})
        self.git(self.root, "fetch", "-q", "origin")
        self.assertEqual(M.walls(self.root, base, ok, ["docs/r.md"]), "")
        self.assertIn(".cc/member-workspace", M.walls(self.root, base, cc, [".cc/member-workspace"]))
        self.assertIn("token", M.walls(self.root, base, tok, ["b/y"]))
        gone = self.push("t-tok", {"b/y": "clean\n"}, fresh=False)       # a token REMOVED is not a wall
        self.git(self.root, "fetch", "-q", "origin")
        self.assertEqual(M.walls(self.root, tok, gone, ["b/y"]), "")
        self.assertTrue(M.boundary_path(".ssh/id_rsa") and not M.boundary_path("src/ssh.py"))

    def test_walls_let_the_design_system_through(self):
        # apply-design-system has a workspace commit .cc/design-tokens.json and .cc/design-fonts/; the rest of .cc/ stays walled
        self.make_member()
        base = self.origin_rev("main")
        toks, font = ".cc/design-tokens.json", ".cc/design-fonts/plex-400.ttf"
        ds = self.push("t-ds", {toks: '{"colors": {}}\n', font: "\0font\n", ".cc/design-fonts/Plex-600.OTF": "f\n"})
        track = self.push("t-track", {".cc/track": "x\n"})
        conf = self.push("t-conf", {".cc/LANDING.toml": "x\n"})
        woff = self.push("t-woff", {".cc/design-fonts/plex.woff2": "f\n"})
        tok = self.push("t-dstok", {toks: '{"k": "ghp_' + "A" * 36 + '"}\n'})
        self.git(self.work, "checkout", "-q", "-B", "t-link", "origin/main")
        os.makedirs(f"{self.work}/.cc/design-fonts", exist_ok=True)
        os.symlink("/etc/passwd", f"{self.work}/.cc/design-fonts/x.ttf")
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-qm", "link")
        self.git(self.work, "push", "-q", "-f", "origin", "t-link:refs/heads/t-link")
        link = self.git(self.work, "rev-parse", "HEAD")
        self.git(self.root, "fetch", "-q", "origin")
        self.assertEqual(M.walls(self.root, base, ds, [toks, font, ".cc/design-fonts/Plex-600.OTF"]), "")
        self.assertIn(".cc/track", M.walls(self.root, base, track, [".cc/track"]))
        self.assertIn(".cc/LANDING.toml", M.walls(self.root, base, conf, [".cc/LANDING.toml"]))
        self.assertIn(".ttf or .otf", M.walls(self.root, base, woff, [".cc/design-fonts/plex.woff2"]))
        self.assertIn("not a regular file (git mode 120000)", M.walls(self.root, base, link, [".cc/design-fonts/x.ttf"]))
        self.assertIn("shaped like a token", M.walls(self.root, base, tok, [toks]))   # the token scan still reads it
        self.git(self.work, "checkout", "-q", "-B", "t-ds", ds)
        self.git(self.work, "rm", "-q", font)
        self.git(self.work, "commit", "-qm", "rm font")
        self.git(self.work, "push", "-q", "-f", "origin", "t-ds:refs/heads/t-ds")
        gone = self.git(self.work, "rev-parse", "HEAD")
        self.git(self.root, "fetch", "-q", "origin")
        self.assertEqual(M.walls(self.root, ds, gone, [font]), "")   # a font deleted is no wall
        # a secret's place or a near name is never carved out
        self.assertFalse(M.design_path(".cc/design-fonts/") or M.design_path(".cc/design-tokens.json.bak")
                         or M.design_path(".cc/design-fontsx/a.ttf") or M.design_path("x/.cc/design-tokens.json"))
        self.assertTrue(M.design_path(toks) and M.design_path(font))

    def test_design_walls_read_the_tree_as_bytes(self):
        # a name git.py decodes with errors="replace" (\xff -> U+FFFD) once dodged the mode check: ls-tree found no
        # entry for the decoded name. Every case is walled with the file list the lane really hands walls()
        self.make_member()
        base = self.origin_rev("main")
        fonts = f"{self.work}/.cc/design-fonts"

        def commit(branch, make, start="origin/main", add=True):
            self.git(self.work, "checkout", "-q", "-B", branch, start)
            os.makedirs(fonts, exist_ok=True)
            make()
            if add:   # a gitlink lives in the index only: add -A would stage its removal
                self.git(self.work, "add", "-A")
            self.git(self.work, "commit", "-qm", branch)
            self.git(self.work, "push", "-q", "-f", "origin", f"{branch}:refs/heads/{branch}")
            self.git(self.root, "fetch", "-q", "origin")
            return self.git(self.work, "rev-parse", "HEAD")

        def walled(head, frm=base, files=None):
            return M.walls(self.root, frm, head, G.pr_changed(self.root, frm, head) if files is None else files)

        ok = commit("t-ok", lambda: pathlib.Path(f"{fonts}/plex.ttf").write_text("f\n"))
        self.assertEqual(walled(ok), "")   # the allowed case still passes
        ff = commit("t-ff", lambda: os.symlink(os.path.expanduser("~/.cc/config"), fonts.encode() + b"/\xff.ttf"))
        self.assertIn("must be a UTF-8 name", walled(ff))
        # named past the U+FFFD check, the tree read still sees the raw name
        self.assertIn("must be a UTF-8 name", walled(ff, files=[".cc/design-fonts/plex.ttf"]))
        gone = commit("t-ff", lambda: os.unlink(fonts.encode() + b"/\xff.ttf"), start=ff)
        self.assertIn("must be a UTF-8 name", walled(gone, frm=ff, files=[".cc/design-fonts/plex.ttf"]))
        sub = self.git(self.work, "rev-parse", "origin/main")
        gl = commit("t-gl", lambda: self.git(self.work, "update-index", "--add", "--cacheinfo",
                                             f"160000,{sub},.cc/design-fonts/sub.ttf"), add=False)
        self.assertIn("not a regular file (git mode 160000)", walled(gl))
        ln = commit("t-ln", lambda: os.symlink("/etc/passwd", f"{self.work}/.cc/design-tokens.json"))
        self.assertIn("not a regular file (git mode 120000)", walled(ln))
        dr = self.push("t-dir", {".cc/design-tokens.json/x": "{}\n", ".cc/design-fonts/a.ttf": "f\n"})
        self.git(self.root, "fetch", "-q", "origin")
        self.assertIn(".cc/design-tokens.json/x", walled(dr))
        self.assertIn("must be one regular file", walled(dr, files=[".cc/design-fonts/a.ttf"]))
        # a design path the list names that the head neither holds nor deletes: fail closed
        self.assertIn("neither held by its head nor deleted", walled(ok, files=[".cc/design-fonts/ghost.ttf"]))

    def test_a_member_lane_keeps_its_checks_on_the_box_with_a_laptop_configured(self):
        # a member's PR never runs on the owner's laptop: no laptop flight, no box_only, the member's own runner
        self.make_member()
        self.pr(1, {"a/x": "m\n"})
        J.submit("alice--proj", 1)
        kws, flights = [], []
        flight = L.Flight

        class Kw(Runner):
            def run_plan(self, *a, **kw):
                kws.append(kw.get("box_only"))
                return super().run_plan(*a, **kw)

        def record(*a, **k):
            f = flight(*a, **k)
            flights.append(f.laptop)
            return f
        with mock.patch.object(L.A, "LAPTOP_SLOTS", 5), mock.patch.object(L, "Flight", record), \
                mock.patch.object(L.RUN, "laptop_dest", return_value="ccsuite@r"), \
                mock.patch.object(L.RUN, "may_leave", return_value=True):
            u, _ = self.land("alice--proj", runner=Kw())
        self.assertEqual(self.job(1, "alice--proj").state, T.DONE)
        self.assertEqual(flights, [False])
        self.assertEqual(kws, [None])
        self.assertEqual(u["runner"].calls[0][2], "member:alice")
        # the same check on the owner's own lane does go to the laptop: the case the member's is kept from
        c = T.Check(name="a", run="x", klass=T.HOST, where=["box", "laptop"])
        with mock.patch.object(L.RUN, "laptop_dest", return_value="ccsuite@r"), \
                mock.patch.object(L.RUN.A, "overloaded", return_value="load 50.0 on 20 cores (at least 2x)"):
            self.assertEqual((L.RUN.choose_where(c), L.RUN.choose_where(c, "alice")), ("laptop", "member:alice"))

    def test_member_lane_walls_hand_back_and_clean_lands_without_deploy(self):
        self.make_member()
        self.pr(1, {".cc/x": "no\n"})
        J.submit("alice--proj", 1)
        u, _ = self.land("alice--proj")
        self.assertIsNone(self.job(1, "alice--proj"))
        self.assertEqual(u["cards"].calls[0][0], "stopped")
        self.assertEqual(u["cards"].calls[0][3], "#alice")
        self.pr(2, {"a/x": "m\n"})
        J.submit("alice--proj", 2)
        u, _ = self.land("alice--proj")
        j = self.job(2, "alice--proj")
        self.assertEqual((j.state, j.member), (T.DONE, "alice"))
        self.assertEqual(u["runner"].calls[0][2], "member:alice")
        self.assertEqual(u["deploy"].calls, [])
        self.assertEqual(L.M.route(j), "#alice")
        self.assertEqual(M.route(T.Job(repo="demo", pr=1)), "")

    def test_a_members_bare_workspace_board_lands_without_deploy(self):
        # ~/dev/<h> holds several of the member's clones, so its origin's main may never fast-forward its main
        os.makedirs(f"{self.home}/.cc/members/demo")
        open(f"{self.home}/.cc/members/demo/member-workspace", "w").close()
        self.pr(1, {"a/x": "m\n"})
        J.submit("demo", 1)
        u, _ = self.land()
        self.assertEqual(self.job(1).state, T.DONE)
        self.assertEqual(u["deploy"].calls, [])


class Compiled(Fixture):
    """Perms, after #1298: "EVERY lane refuses __pycache__, .pyc, .pyo, .so, .pyd and NUL-bearing blobs under core/
    AND bin-private/ ... Add an end-to-end case in which a .so beside a gate module is refused in the ordinary lane"."""

    def handed_why(self, pr):
        return J.read_json(J.handed_path("demo", pr)).get("why") or ""

    def test_a_so_beside_a_gate_module_is_handed_back_in_the_ordinary_lane(self):
        so = "core/lander/git.cpython-314-x86_64-linux-gnu.so"
        self.pr(1, {"core/lander/git.py": "X = 1\n", so: "not really an ELF\n"})
        J.submit("demo", 1)
        u, _ = self.land()
        self.assertIsNone(self.job(1))
        self.assertEqual(u["cards"].calls[0][0], "stopped")
        self.assertIn(so, self.handed_why(1))
        self.assertNotIn("core/lander/git.py,", self.handed_why(1))
        self.assertEqual(u["runner"].calls, [])   # refused before a check ran or a read was bought

    def test_a_nul_bearing_file_under_bin_private_is_handed_back_and_source_beside_it_lands(self):
        self.pr(1, {"bin-private/door": "#!/bin/sh\n\0x\n", "bin-private/door-ok": "#!/bin/sh\n"})
        J.submit("demo", 1)
        self.land()
        self.assertIsNone(self.job(1))
        self.assertIn("bin-private/door)", self.handed_why(1))
        self.pr(2, {"core/lander/fast.py": "Y = 1\n", "bin-private/door-ok": "#!/bin/sh\n"})
        J.submit("demo", 2)
        self.land()
        self.assertEqual(self.job(2).state, T.DEPLOY_PENDING)

    def test_a_binary_outside_both_roots_is_the_ordinary_lanes_as_before(self):
        self.pr(1, {"docs/pic.png": "\x89PNG\0"})
        J.submit("demo", 1)
        self.land()
        self.assertEqual(self.job(1).state, T.DEPLOY_PENDING)

    def linked(self, num, files, links, branch=None, gone=()):
        """pr() with `links` ({path: target}) committed as symlinks beside `files`, after `gone` (paths) are removed;
        branch "main" pushes to main."""
        branch = branch or f"track/row-{num}"
        self.git(self.work, "fetch", "-q", "origin")
        self.git(self.work, "checkout", "-q", "-B", branch, "origin/main")
        for rel in gone:
            self.git(self.work, "rm", "-rq", rel)
        self.write(self.work, files)
        for rel, target in links.items():
            os.makedirs(os.path.dirname(os.path.join(self.work, rel)), exist_ok=True)
            os.symlink(target, os.path.join(self.work, rel))
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-qm", f"{branch} links")
        self.git(self.work, "push", "-q", "-f", "origin", f"{branch}:refs/heads/{branch}")
        if branch != "main":
            b = self.box()
            b["prs"][str(num)] = {"headRefName": branch, "title": f"row {num} change"}
            self.set_box(prs=b["prs"])

    def test_a_symlinked_package_dir_onto_a_so_outside_the_roots_is_handed_back(self):
        """Opus security read of #1301: "A PR adds the symlink core/lander/git -> ../../docs/p and puts
        docs/p/__init__.cpython-314-x86_64-linux-gnu.so outside both roots; binaries() returns []"."""
        so = "docs/p/__init__.cpython-314-x86_64-linux-gnu.so"
        self.linked(1, {so: "not really an ELF\n"}, {"core/lander/git": "../../docs/p"})
        J.submit("demo", 1)
        self.land()
        self.assertIsNone(self.job(1))
        self.assertIn("core/lander/git,", self.handed_why(1))
        self.assertIn(so, self.handed_why(1))

    def test_a_new_symlink_under_core_is_handed_back_even_onto_source(self):
        self.linked(1, {"docs/p/__init__.py": "X = 1\n"}, {"core/lander/git": "../../docs/p"})
        J.submit("demo", 1)
        self.land()
        self.assertIsNone(self.job(1))
        self.assertIn("(core/lander/git)", self.handed_why(1))

    def test_a_compiled_name_outside_both_roots_is_handed_back(self):
        so = "docs/p/x.cpython-314-x86_64-linux-gnu.so"
        self.pr(1, {so: "not really an ELF\n"})
        J.submit("demo", 1)
        self.land()
        self.assertIsNone(self.job(1))
        self.assertIn(f"({so})", self.handed_why(1))

    def test_a_symlink_main_already_tracks_lands(self):
        self.linked(0, {}, {"core/bin/cc-mail": "../mail/receiver.py"}, branch="main")
        self.linked(1, {"core/bin/other": "#!/bin/sh\n"}, {})
        J.submit("demo", 1)
        self.land()
        self.assertEqual(self.job(1).state, T.DEPLOY_PENDING)

    def test_a_root_replaced_whole_by_a_symlink_is_handed_back(self):
        """Opus delta read of #1301 at 5889bc9a: "a PR that deletes bin-private's files and adds the symlink
        bin-private -> /home/<member>/x lists the bare path 'bin-private'" — here onto a dir inside the repo, so
        only the bare-root rule names it."""
        self.linked(0, {"bin-private/door": "#!/bin/sh\n", "docs/p/door": "#!/bin/sh\n"}, {}, branch="main")
        self.linked(1, {}, {"bin-private": "docs/p"}, gone=("bin-private",))
        J.submit("demo", 1)
        self.land()
        self.assertIsNone(self.job(1))
        self.assertIn("(bin-private)", self.handed_why(1))

    def test_a_file_outside_the_roots_turned_into_a_symlink_out_of_the_repo_is_handed_back(self):
        """The same read: "type-changing a file outside the roots (dashboard/server.py ...) into a symlink with an
        absolute target, or one that resolves outside the repo ... lands unread"."""
        self.linked(0, {"dashboard/server.py": "print(1)\n", "vr/server.py": "print(2)\n"}, {}, branch="main")
        self.linked(1, {}, {"dashboard/server.py": "/tmp/evil.py", "vr/server.py": "../../evil.py"},
                    gone=("dashboard/server.py", "vr/server.py"))
        J.submit("demo", 1)
        self.land()
        self.assertIsNone(self.job(1))
        self.assertIn("(dashboard/server.py, vr/server.py)", self.handed_why(1))

    def test_a_symlink_under_config_system_lands_and_one_inside_the_repo_does_not(self):
        self.linked(1, {"vr/real.py": "print(3)\n"},
                    {"config/system/etc/x.service": "/usr/lib/systemd/system/x.service"})
        J.submit("demo", 1)
        self.land()
        self.assertEqual(self.job(1).state, T.DEPLOY_PENDING)
        self.linked(2, {}, {"vr/server.py": "real.py"})
        J.submit("demo", 2)
        self.land()
        self.assertIsNone(self.job(2))
        self.assertIn("(vr/server.py)", self.handed_why(2))

    def test_a_link_chained_through_config_system_is_handed_back(self):
        """Opus delta read of #1301 at b57c0deb, bypass (a): "config/system/evil -> /tmp/evil.py plus
        dashboard/server.py -> ../config/system/evil"."""
        self.linked(0, {"dashboard/server.py": "print(1)\n"}, {}, branch="main")
        self.linked(1, {}, {"config/system/evil": "/tmp/evil.py", "dashboard/server.py": "../config/system/evil"},
                    gone=("dashboard/server.py",))
        J.submit("demo", 1)
        self.land()
        self.assertIsNone(self.job(1))
        self.assertIn("(dashboard/server.py)", self.handed_why(1))

    def test_a_link_through_a_directory_link_is_handed_back(self):
        """The same read, bypass (b): "docs/up -> .. plus dashboard/server.py -> ../docs/up/../../tmp/evil.py"."""
        self.linked(0, {"dashboard/server.py": "print(1)\n"}, {}, branch="main")
        self.linked(1, {}, {"docs/up": "..", "dashboard/server.py": "../docs/up/../../tmp/evil.py"},
                    gone=("dashboard/server.py",))
        J.submit("demo", 1)
        self.land()
        self.assertIsNone(self.job(1))
        self.assertIn("(dashboard/server.py, docs/up)", self.handed_why(1))

    def test_no_self_tool_holds_the_job_rather_than_letting_it_through(self):
        self.pr(1, {"core/lander/fast.py": "Y = 1\n"})
        J.submit("demo", 1)
        with mock.patch.object(L, "SELF_TOOL", os.path.join(self.tmp, "gone")), mock.patch.object(L, "_SELF", []):
            self.land()
        j = self.job(1)
        self.assertEqual(j.state, T.HELD)
        self.assertIn("compiled", j.extra["why"])


class Machine(Fixture):
    def test_every_edge(self):
        for s in T.JOB_STATES:
            for t in T.JOB_STATES:
                j = T.Job(repo="edge", pr=1, state=s)
                with self.subTest(f"{s}->{t}"):
                    if t in J.NEXT.get(s, ()):
                        J.move(j, t)
                        d = J.read_json(J.file_of(j))
                        self.assertEqual((d["state"], d["stage"]), (t, J.STAGE_OF[t]))
                    else:
                        with self.assertRaises(ValueError):
                            J.move(j, t)
        self.assertEqual(set(J.STAGE_OF), set(T.JOB_STATES))

    def test_job_file_at_todays_path_with_stage(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        u, _ = self.land()
        p = f"{os.environ['CC_LANDER_STATE']}/demo-1.json"
        d = J.read_json(p)
        self.assertEqual((d["state"], d["stage"]), (T.DEPLOY_PENDING, "install"))
        self.assertEqual([h["state"] for h in d["history"]],
                         ["queued", "planned", "checking", "mergeable", "merged", "deploy-pending"])
        self.assertEqual(u["deploy"].calls, [("request", "demo", self.origin_rev("main"), [])])
        self.assertEqual([c[0] for c in u["board"].calls + u["cards"].calls + u["tip"].calls],
                         ["close", "landed", "kick"])

    def test_a_hung_slack_holds_no_landing_and_only_one_cards_pass_runs(self):
        """Opus read, 10-13: "positions() must not hold the lane loop on a slow Slack"."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        slow = SlowCards()
        try:
            with mock.patch.object(L, "CARDS_WAIT", 0.2):
                t0 = time.time()
                self.land(cards=slow)
                took = time.time() - t0
        finally:
            slow.go.set()
        self.assertLess(took, 30)   # a lane held by the hung card would have waited its 60 s
        self.assertEqual(self.job(1).state, T.DEPLOY_PENDING)
        self.assertEqual([c[0] for c in slow.calls], ["landed"])
        self.assertEqual(len(slow.positions_calls), 1)   # while one pass hangs, no second one is started

    def test_a_slack_that_answers_gets_each_move_once_and_the_lane_ends_on_the_last(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        u, _ = self.land()
        seen = [states for _, states in u["cards"].positions_calls]
        self.assertEqual(seen[-1], [(1, T.DEPLOY_PENDING)])   # the PR's card hears it left before the lock goes
        self.assertEqual(len(seen), len(set(map(tuple, seen))))   # an unchanged queue is not handed over twice

    def test_a_cards_pass_that_faults_is_handed_the_same_queue_again(self):
        """Opus read, 10-13: `carded` was set before the pass ran, so a faulted pass waited for the queue to move."""
        calls = []

        class Flaky:
            def positions(self, repo, jobs):
                calls.append(repo)
                if len(calls) == 1:
                    raise OSError("slack said no")

        lane = types.SimpleNamespace(repo="demo", carding=None, carded=None, unit=lambda n: Flaky(),
                                     call=lambda n, fn, *a: L.Lane.call(lane, n, fn, *a))
        jobs = [T.Job(repo="demo", pr=1, state=T.QUEUED, stage=T.QUEUED, extra={"queued_at": "x"})]
        L.Lane.cards_pass(lane, jobs, wait=5)
        self.assertEqual(lane.carded, None)   # the fault left the queue unmarked
        L.Lane.cards_pass(lane, jobs, wait=5)
        self.assertEqual(len(calls), 2)   # so the same queue went again
        L.Lane.cards_pass(lane, jobs, wait=5)
        self.assertEqual(len(calls), 2)   # and once through, an unchanged queue is not handed over again

    def test_a_cards_pass_with_an_edit_held_is_handed_the_same_queue_again(self):
        """A card edit the box-wide cap or a Slack 429 held (positions -> False) goes on a later pass."""
        calls = []

        class Held:
            def positions(self, repo, jobs):
                calls.append(repo)
                return len(calls) > 1

        lane = types.SimpleNamespace(repo="demo", carding=None, carded=None, unit=lambda n: Held(),
                                     call=lambda n, fn, *a: L.Lane.call(lane, n, fn, *a))
        jobs = [T.Job(repo="demo", pr=1, state=T.QUEUED, stage=T.QUEUED, extra={"queued_at": "x"})]
        L.Lane.cards_pass(lane, jobs, wait=5)
        self.assertEqual(lane.carded, None)   # an edit was held, so the queue is left unmarked
        L.Lane.cards_pass(lane, jobs, wait=5)
        self.assertEqual(len(calls), 2)   # so the same queue went again
        L.Lane.cards_pass(lane, jobs, wait=5)
        self.assertEqual(len(calls), 2)   # and once through, an unchanged queue is not handed over again

    def test_a_local_branch_named_origin_main_is_not_main(self):
        """refs/heads/origin/<b> (a worker's `git branch origin/main`) must never stand in for origin's <b>."""
        head = self.pr(1, {"a/x": "n\n"})
        base = self.origin_rev("main")
        tree = self.git(self.root, "rev-parse", "HEAD^{tree}")
        planted = self.git(self.root, "commit-tree", tree, "-m", "planted")
        self.git(self.root, "branch", "-f", "origin/main", planted)
        self.git(self.root, "branch", "-f", "origin/track/row-1", planted)
        J.submit("demo", 1)
        u, _ = self.land()
        d = J.read_json(f"{os.environ['CC_LANDER_STATE']}/demo-1.json")
        self.assertEqual(d["state"], T.DEPLOY_PENDING)
        self.assertEqual((d["base_sha"], d["head"]), (base, head))
        self.assertEqual(u["deploy"].calls, [("request", "demo", self.origin_rev("main"), [])])

    def forge_origin(self):
        """What a worker can do to the shared .git with no guard in its way: origin repointed to its own bare repo
        whose main is a planted child of main, the fetch refspec unset, refs/remotes/origin/main written to it."""
        evil = os.path.join(self.tmp, "evil.git")
        shutil.copytree(self.origin, evil, symlinks=True)
        tree = self.git(self.root, "rev-parse", "HEAD^{tree}")
        planted = self.git(self.root, "commit-tree", tree, "-p", "HEAD", "-m", "planted")
        self.git(self.root, "push", "-q", "-f", evil, f"{planted}:refs/heads/main")
        self.git(self.root, "remote", "set-url", "origin", evil)
        self.git(self.root, "config", "--unset-all", "remote.origin.fetch")
        self.git(self.root, "update-ref", "refs/remotes/origin/main", planted)
        return planted

    def test_a_forged_origin_in_the_shared_git_dir_is_ignored(self):
        """The tip, lane and deploy paths fetch the URL the lander holds, never the checkout's "origin"."""
        from lander import deploy as D
        from lander import tip as TP
        head = self.pr(1, {"a/x": "n\n"})
        real = self.origin_rev("main")
        planted = self.forge_origin()
        self.assertEqual(G.fetch(self.root, "main"), {"main": real})   # what origin sent, not what the ref says
        self.git(self.root, "update-ref", "refs/remotes/origin/main", planted)
        self.assertEqual(TP.origin_tip(self.root, "main"), real)                                    # tip
        self.assertEqual(self.git(self.root, "rev-parse", "refs/remotes/origin/main"), real)
        self.git(self.root, "update-ref", "refs/remotes/origin/main", planted)
        J.submit("demo", 1)                                                                          # lane
        u, _ = self.land()
        d = J.read_json(f"{os.environ['CC_LANDER_STATE']}/demo-1.json")
        self.assertEqual((d["state"], d["base_sha"], d["head"]), (T.DEPLOY_PENDING, real, head))
        merged = self.origin_rev("main")
        self.assertEqual(u["deploy"].calls, [("request", "demo", merged, [])])
        self.git(self.root, "update-ref", "refs/remotes/origin/main", planted)                     # deploy
        with self.assertRaises(D.Failed) as e:
            D.pull(self.root, "main", planted)
        self.assertIn("is not on origin/main", e.exception.why)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), real)
        D.pull(self.root, "main", merged)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), merged)
        self.assertEqual(G.remote_head(self.root, "main"), merged)

    def test_an_untracked_file_where_main_adds_one_is_moved_aside(self):
        """#930 (2026-10-03): an untracked draft at a path main then committed made read-tree refuse every try. It is
        moved to deploy-aside/ and the deploy goes on; an untracked file the merge does not touch stays where it is."""
        from lander import deploy as D
        self.write(self.root, {"docs/draft.md": "old draft\n", "a/b": "a file where main makes a dir\n",
                               "docs/mine.md": "not in the merge\n"})
        merged = self.push("main", {"docs/draft.md": "committed\n", "a/b/c": "x\n"})
        said = []
        D.pull(self.root, "main", merged, said=said)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), merged)
        self.assertEqual(open(os.path.join(self.root, "docs/draft.md")).read(), "committed\n")
        self.assertEqual(open(os.path.join(self.root, "docs/mine.md")).read(), "not in the merge\n")
        self.assertEqual(len(said), 1)
        self.assertIn(D.MOVED, said[0])
        dest = said[0].split(" to ", 1)[1].split(": ", 1)[0]
        self.assertTrue(dest.startswith(C.state("deploy-aside", "demo")), dest)
        self.assertEqual(open(os.path.join(dest, "docs/draft.md")).read(), "old draft\n")
        self.assertEqual(open(os.path.join(dest, "a/b")).read(), "a file where main makes a dir\n")
        self.assertFalse(os.path.exists(os.path.join(dest, "docs/mine.md")))
        self.assertEqual(self.git(self.root, "status", "--porcelain"), "?? docs/mine.md")

    def test_a_refusal_that_moving_aside_cannot_cure_puts_the_files_back(self):
        """A changed tracked file is a person's edit: read-tree still refuses, nothing merges and the untracked file
        moved for the retry is back where it was."""
        from lander import deploy as D
        first = self.push("main", {"keep.txt": "v1\n"})
        D.pull(self.root, "main", first)
        self.write(self.root, {"keep.txt": "a local edit\n", "docs/draft.md": "old draft\n"})
        merged = self.push("main", {"keep.txt": "v2\n", "docs/draft.md": "committed\n"})
        said = []
        with self.assertRaises(D.Failed) as e:
            D.pull(self.root, "main", merged, said=said)
        self.assertIn("they are back", e.exception.why)
        self.assertEqual((self.git(self.root, "rev-parse", "HEAD"), said), (first, []))
        self.assertEqual(open(os.path.join(self.root, "docs/draft.md")).read(), "old draft\n")
        self.assertEqual(open(os.path.join(self.root, "keep.txt")).read(), "a local edit\n")

    def test_a_staged_file_already_equal_to_mains_deploys(self):
        """2026-10-21: a stale staged draft of read.py, its file on disk already main's, held every dispatch deploy
        for 1.5 h. A local change that is already what the merge brings no longer stops it."""
        from lander import deploy as D
        self.write(self.root, {"read.py": "early draft\n"})
        self.git(self.root, "add", "read.py")
        merged = self.push("main", {"read.py": "committed\n"})
        self.write(self.root, {"read.py": "committed\n"})
        D.pull(self.root, "main", merged)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), merged)
        self.assertEqual(self.git(self.root, "status", "--porcelain"), "")

    def test_a_differing_local_edit_fails_named_as_a_dirty_checkout(self):
        """A person's edit that differs from main is kept, and the failure says it is the checkout, not main."""
        from lander import deploy as D
        first = self.push("main", {"keep.txt": "v1\n"})
        D.pull(self.root, "main", first)
        self.write(self.root, {"keep.txt": "a local edit\n"})
        merged = self.push("main", {"keep.txt": "v2\n"})
        with self.assertRaises(D.Failed) as e:
            D.pull(self.root, "main", merged)
        self.assertTrue(e.exception.why.startswith(
            f"a dirty checkout, not main red: {self.root} has local changes the merge would overwrite, left for a "
            "person: keep.txt; "), e.exception.why)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), first)
        self.assertEqual(open(os.path.join(self.root, "keep.txt")).read(), "a local edit\n")

    def test_an_update_ref_failure_after_a_move_still_names_the_moved_file(self):
        """read-tree succeeds once the draft is aside, then update-ref fails: the move is in the error, not lost."""
        from lander import deploy as D
        self.write(self.root, {"docs/draft.md": "old draft\n"})
        merged = self.push("main", {"docs/draft.md": "committed\n"})
        real = D.git

        def git(root, *argv, **kw):
            return (1, "cannot lock ref") if argv[:1] == ("update-ref",) else real(root, *argv, **kw)
        with mock.patch.object(D, "git", git), self.assertRaises(D.Failed) as e:
            D.pull(self.root, "main", merged)
        self.assertIn("cannot lock ref", e.exception.why)
        self.assertIn(f"{D.MOVED} to ", e.exception.why)
        self.assertIn("docs/draft.md", e.exception.why)

    def aside_root(self):
        return C.state("deploy-aside", "demo")

    def test_an_untracked_symlink_where_main_adds_a_file_is_moved_as_a_link(self):
        """A symlink in the way is moved as itself; what it points at, outside the checkout, is not touched."""
        from lander import deploy as D
        outside = os.path.join(self.tmp, "outside.txt")
        self.write(self.tmp, {"outside.txt": "not the checkout's\n"})
        os.makedirs(os.path.join(self.root, "docs"), exist_ok=True)
        os.symlink(outside, os.path.join(self.root, "docs/link"))
        merged = self.push("main", {"docs/link": "committed\n"})
        said = []
        D.pull(self.root, "main", merged, said=said)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), merged)
        dest = said[0].split(" to ", 1)[1].split(": ", 1)[0]
        self.assertEqual(os.readlink(os.path.join(dest, "docs/link")), outside)
        self.assertEqual(open(outside).read(), "not the checkout's\n")

    def test_a_directory_where_main_adds_a_file_is_refused_and_never_moved(self):
        """A PR adding a file `.mail-out` must not move the mail queue: read-tree's refusal stands and names the dir."""
        from lander import deploy as D
        self.write(self.root, {".mail-out/queued.eml": "a queued message\n", "docs/draft.md": "old draft\n"})
        merged = self.push("main", {".mail-out": "a file now\n", "docs/draft.md": "committed\n"})
        head = self.git(self.root, "rev-parse", "HEAD")
        said = []
        with self.assertRaises(D.Failed) as e:
            D.pull(self.root, "main", merged, said=said)
        self.assertIn("1 untracked dir(s) stand where the merge adds a file and are left for a person: .mail-out",
                      e.exception.why)
        self.assertEqual((self.git(self.root, "rev-parse", "HEAD"), said), (head, []))
        self.assertEqual(open(os.path.join(self.root, ".mail-out/queued.eml")).read(), "a queued message\n")
        self.assertEqual(open(os.path.join(self.root, "docs/draft.md")).read(), "old draft\n")
        self.assertFalse(os.path.exists(self.aside_root()))   # refused before anything went aside

    def test_a_move_that_fails_puts_back_what_moved_and_moves_nothing(self):
        from lander import deploy as D
        self.write(self.root, {"docs/one.md": "one\n", "docs/two.md": "two\n"})
        merged = self.push("main", {"docs/one.md": "committed\n", "docs/two.md": "committed\n"})
        head = self.git(self.root, "rev-parse", "HEAD")
        real = D.move

        def move(src, dst, rel):
            if (src, rel) == (self.root, "docs/two.md"):
                raise OSError(28, "No space left on device")
            return real(src, dst, rel)
        with mock.patch.object(D, "move", move), self.assertRaises(D.Failed) as e:
            D.pull(self.root, "main", merged)
        self.assertIn("moving docs/two.md aside failed", e.exception.why)
        self.assertIn("nothing was moved", e.exception.why)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), head)
        self.assertEqual(open(os.path.join(self.root, "docs/one.md")).read(), "one\n")
        self.assertEqual(open(os.path.join(self.root, "docs/two.md")).read(), "two\n")
        self.assertEqual(os.listdir(self.aside_root()), [])

    def test_a_file_that_cannot_go_back_is_named_with_its_aside_path(self):
        """When the retry still refuses and a file cannot be put back, the deploy says where it is, never "back"."""
        from lander import deploy as D
        first = self.push("main", {"keep.txt": "v1\n"})
        D.pull(self.root, "main", first)
        self.write(self.root, {"keep.txt": "a local edit\n", "docs/draft.md": "old draft\n"})
        merged = self.push("main", {"keep.txt": "v2\n", "docs/draft.md": "committed\n"})
        real = D.move

        def move(src, dst, rel):
            if (dst, rel) == (self.root, "docs/draft.md"):
                raise OSError(13, "Permission denied")
            return real(src, dst, rel)
        with mock.patch.object(D, "move", move), self.assertRaises(D.Failed) as e:
            D.pull(self.root, "main", merged)
        self.assertNotIn("they are back", e.exception.why)
        [dest] = os.listdir(self.aside_root())
        stuck = os.path.join(self.aside_root(), dest, "docs/draft.md")
        self.assertIn(f"0 went back and 1 could not, so they stay in deploy-aside: {stuck}", e.exception.why)
        self.assertEqual(open(stuck).read(), "old draft\n")

    def test_a_dotdot_tree_entry_moves_nothing_outside_the_checkout(self):
        """A crafted tree with a `..` entry: git diff names `../canary`, and nothing outside the root is touched."""
        from lander import deploy as D
        canary = os.path.join(os.path.dirname(self.root), "canary")
        self.write(os.path.dirname(self.root), {"canary": "outside\n"})
        before = os.lstat(canary)
        self.git(self.work, "fetch", "-q", "origin")
        base = self.git(self.work, "rev-parse", "origin/main")
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=self.work, input="x\n", text=True,
                              check=True, capture_output=True).stdout.strip()
        sub = subprocess.run(["git", "mktree"], cwd=self.work, input=f"100644 blob {blob}\tcanary\n", text=True,
                             check=True, capture_output=True).stdout.strip()
        rows = self.git(self.work, "ls-tree", f"{base}^{{tree}}") + f"\n040000 tree {sub}\t..\n"
        tree = subprocess.run(["git", "mktree"], cwd=self.work, input=rows, text=True, check=True,
                              capture_output=True).stdout.strip()
        bad = self.git(self.work, "commit-tree", tree, "-p", base, "-m", "a crafted tree")
        self.git(self.work, "push", "-q", "-f", "origin", f"{bad}:refs/heads/main")
        head = self.git(self.root, "rev-parse", "HEAD")
        with self.assertRaises(D.Failed):
            D.pull(self.root, "main", bad)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), head)
        after = os.lstat(canary)
        self.assertEqual((after.st_ino, after.st_ctime_ns), (before.st_ino, before.st_ctime_ns))
        self.assertEqual(open(canary).read(), "outside\n")
        self.assertFalse(os.path.exists(self.aside_root()))
        self.assertTrue(D.unsafe("../canary") and D.unsafe("a/./b") and D.unsafe("a//b") and D.unsafe(".GIT/x"))
        self.assertFalse(D.unsafe("docs/.gitignore"))

    def push_forced(self, files):
        """A commit on main that adds `files` with `git add -f`, past the tree's own .gitignore."""
        self.git(self.work, "fetch", "-q", "origin")
        self.git(self.work, "checkout", "-q", "-B", "main", "origin/main")
        self.write(self.work, files)
        self.git(self.work, "add", "-f", *files)
        self.git(self.work, "commit", "-qm", f"forced {sorted(files)}")
        self.git(self.work, "push", "-q", "origin", "main:refs/heads/main")
        return self.git(self.work, "rev-parse", "HEAD")

    def test_an_ignored_file_where_main_adds_one_is_moved_aside_never_overwritten(self):
        """The #967 security read (2026-10-04): git 2.53's read-tree -m -u overwrites an ignored file without
        refusing, so a merge adding core/ccbox/env would replace the token file. It is moved aside as an untracked one
        is; an ignored file the merge does not touch stays."""
        from lander import deploy as D
        D.pull(self.root, "main", self.push("main", {".gitignore": "env\nother\n"}))
        self.write(self.root, {"env": "SECRET\n", "other": "mine\n"})
        self.assertIn("!! env", self.git(self.root, "status", "--porcelain", "--ignored"))
        merged = self.push_forced({"env": "committed\n"})
        said = []
        D.pull(self.root, "main", merged, said=said)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), merged)
        self.assertEqual(open(os.path.join(self.root, "env")).read(), "committed\n")
        self.assertEqual(open(os.path.join(self.root, "other")).read(), "mine\n")
        self.assertIn(D.MOVED, said[0])
        dest = said[0].split(" to ", 1)[1].split(": ", 1)[0]
        self.assertEqual(open(os.path.join(dest, "env")).read(), "SECRET\n")
        self.assertFalse(os.path.exists(os.path.join(dest, "other")))

    def test_an_ignored_dir_where_main_adds_a_file_is_refused_and_kept(self):
        """read-tree would delete an ignored folder (.claude/worktrees) to write a file there: the deploy refuses
        before read-tree runs, so the folder and HEAD stay, and nothing goes aside."""
        from lander import deploy as D
        first = self.push("main", {".gitignore": "wt\n"})
        D.pull(self.root, "main", first)
        self.write(self.root, {"wt/session/notes": "a worktree\n"})
        merged = self.push_forced({"wt": "a file now\n"})
        with self.assertRaises(D.Failed) as e:
            D.pull(self.root, "main", merged)
        self.assertIn("1 untracked dir(s) stand where the merge adds a file and are left for a person: wt",
                      e.exception.why)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), first)
        self.assertEqual(open(os.path.join(self.root, "wt/session/notes")).read(), "a worktree\n")
        self.assertFalse(os.path.exists(self.aside_root()))

    def test_a_tracked_dir_holding_an_ignored_file_that_main_makes_a_file_is_refused(self):
        """A tracked dir main replaces with a file would lose the ignored file inside it with the tracked ones: refused,
        and a tracked dir with nothing else in it still becomes the file."""
        from lander import deploy as D
        first = self.push("main", {".gitignore": "*.tok\n", "cfg/a": "tracked\n", "plain/b": "tracked\n"})
        D.pull(self.root, "main", first)
        self.write(self.root, {"cfg/secret.tok": "SECRET\n"})
        self.git(self.work, "rm", "-q", "-r", "cfg")
        self.git(self.work, "commit", "-qm", "drop cfg")
        self.git(self.work, "push", "-q", "origin", "main:refs/heads/main")
        merged = self.push_forced({"cfg": "a file now\n"})
        with self.assertRaises(D.Failed) as e:
            D.pull(self.root, "main", merged)
        self.assertIn("left for a person: cfg", e.exception.why)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), first)
        self.assertEqual(open(os.path.join(self.root, "cfg/secret.tok")).read(), "SECRET\n")
        os.unlink(os.path.join(self.root, "cfg/secret.tok"))   # the kept case: nothing but tracked files
        D.pull(self.root, "main", merged)
        self.assertEqual(open(os.path.join(self.root, "cfg")).read(), "a file now\n")

    def test_a_symlinked_parent_dir_moves_as_a_link_and_its_target_is_never_touched(self):
        """An untracked symlink `docs2` -> a dir outside, where main adds docs2/draft.md: the link moves aside as
        itself and the file behind it is untouched."""
        from lander import deploy as D
        out = os.path.join(self.tmp, "outdir")
        self.write(out, {"draft.md": "outside\n"})
        os.symlink(out, os.path.join(self.root, "docs2"))
        merged = self.push("main", {"docs2/draft.md": "committed\n"})
        said = []
        D.pull(self.root, "main", merged, said=said)
        self.assertEqual(open(os.path.join(self.root, "docs2/draft.md")).read(), "committed\n")
        self.assertFalse(os.path.islink(os.path.join(self.root, "docs2")))
        dest = said[0].split(" to ", 1)[1].split(": ", 1)[0]
        self.assertEqual(os.readlink(os.path.join(dest, "docs2")), out)
        self.assertEqual(open(os.path.join(out, "draft.md")).read(), "outside\n")

    def test_a_state_dir_on_another_filesystem_gets_a_copy_with_its_mode_and_links_as_links(self):
        """No hard link across filesystems (EXDEV): the file is copied with its mode, a symlink is made anew, and the
        originals leave the checkout; without EXDEV nothing is copied."""
        from lander import deploy as D
        out = os.path.join(self.tmp, "outside.txt")
        self.write(self.tmp, {"outside.txt": "not the checkout's\n"})
        self.write(self.root, {"docs/run.sh": "#!/bin/sh\n"})
        os.chmod(os.path.join(self.root, "docs/run.sh"), 0o750)
        os.symlink(out, os.path.join(self.root, "docs/link"))
        merged = self.push("main", {"docs/run.sh": "committed\n", "docs/link": "committed\n"})

        def link(*a, **kw):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        said = []
        with mock.patch.object(D.os, "link", link), mock.patch.object(D, "copy_at", wraps=D.copy_at) as cp:
            D.pull(self.root, "main", merged, said=said)
        self.assertEqual(cp.call_count, 2)
        dest = said[0].split(" to ", 1)[1].split(": ", 1)[0]
        self.assertEqual(open(os.path.join(dest, "docs/run.sh")).read(), "#!/bin/sh\n")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(dest, "docs/run.sh")).st_mode), 0o750)
        self.assertEqual(os.readlink(os.path.join(dest, "docs/link")), out)
        self.assertEqual(open(os.path.join(self.root, "docs/link")).read(), "committed\n")
        self.assertEqual(open(out).read(), "not the checkout's\n")
        self.write(self.root, {"docs/new.md": "draft\n"})                     # same filesystem: a link, no copy
        merged = self.push("main", {"docs/new.md": "committed\n"})
        with mock.patch.object(D, "copy_at", wraps=D.copy_at) as cp:
            D.pull(self.root, "main", merged)
        self.assertEqual(cp.call_count, 0)

    def test_a_parent_swapped_for_a_symlink_after_the_walk_moves_nothing_through_it(self):
        """The race the #967 re-read named: a parent dir turned into a symlink between the lstat walk and the move.
        The move opens each parent with O_NOFOLLOW, so it refuses, the deploy fails and the file outside stays."""
        from lander import deploy as D
        out = os.path.join(self.tmp, "outdir")
        self.write(out, {"draft.md": "outside\n"})
        os.symlink(out, os.path.join(self.root, "docs2"))
        merged = self.push("main", {"docs2/draft.md": "committed\n"})
        head = self.git(self.root, "rev-parse", "HEAD")
        with mock.patch.object(D, "in_the_way", lambda *a: (["docs2/draft.md"], [])), \
                self.assertRaises(D.Failed) as e:
            D.pull(self.root, "main", merged)
        self.assertIn("moving docs2/draft.md aside failed", e.exception.why)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), head)
        self.assertEqual(open(os.path.join(out, "draft.md")).read(), "outside\n")
        self.assertEqual(os.listdir(self.aside_root()), [])

    def test_a_git_that_cannot_list_the_index_fails_the_deploy_and_merges_nothing(self):
        """in_the_way -> None when `git ls-files` fails: the deploy fails before read-tree and HEAD stays; with
        ls-files working the same merge goes in."""
        from lander import deploy as D
        merged = self.push("main", {"docs/new.md": "committed\n"})
        head = self.git(self.root, "rev-parse", "HEAD")
        real = D.git

        def git(root, *args, **kw):
            return (128, "fatal: index file corrupt") if args[:1] == ("ls-files",) else real(root, *args, **kw)
        with mock.patch.object(D, "git", git), self.assertRaises(D.Failed) as e:
            D.pull(self.root, "main", merged)
        self.assertIn("git could not list what", e.exception.why)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), head)
        D.pull(self.root, "main", merged)
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), merged)

    def test_an_unreadable_subdir_of_a_tracked_dir_counts_as_holding_something(self):
        """A 000-mode dir under a tracked dir main makes a file: what cannot be seen is never handed to read-tree to
        delete, so the deploy refuses; readable again and holding only tracked files, it goes in."""
        from lander import deploy as D
        if os.geteuid() == 0:
            self.skipTest("root reads a 000-mode dir")
        first = self.push("main", {"cfg/sub/a": "tracked\n"})
        D.pull(self.root, "main", first)
        self.git(self.work, "rm", "-q", "-r", "cfg")
        self.git(self.work, "commit", "-qm", "drop cfg")
        self.git(self.work, "push", "-q", "origin", "main:refs/heads/main")
        merged = self.push("main", {"cfg": "a file now\n"})
        sub = os.path.join(self.root, "cfg/sub")
        os.chmod(sub, 0)
        try:
            self.assertTrue(D.holds_untracked(self.root, "cfg", {"cfg/sub/a"}))
            with self.assertRaises(D.Failed) as e:
                D.pull(self.root, "main", merged)
            self.assertIn("left for a person: cfg", e.exception.why)
            self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), first)
        finally:
            os.chmod(sub, 0o755)
        self.assertFalse(D.holds_untracked(self.root, "cfg", {"cfg/sub/a"}))
        D.pull(self.root, "main", merged)
        self.assertEqual(open(os.path.join(self.root, "cfg")).read(), "a file now\n")

    def two_dirs(self, files):
        src, dst = os.path.join(self.tmp, "src"), os.path.join(self.tmp, "dst")
        self.write(src, files)
        os.makedirs(os.path.join(dst, "d"), exist_ok=True)
        return src, dst

    def test_a_source_that_will_not_unlink_leaves_no_copy_behind(self):
        """move(): when the source unlink fails the destination link is removed and the error raised, so the file is
        in one place only; with the unlink working it moves."""
        from lander import deploy as D
        src, dst = self.two_dirs({"d/f": "mine\n"})
        real, calls = os.unlink, []

        def unlink(name, *a, dir_fd=None, **kw):
            calls.append(name)
            if len(calls) == 1:
                raise OSError(errno.EACCES, "Permission denied")
            return real(name, *a, dir_fd=dir_fd, **kw)
        with mock.patch.object(D.os, "unlink", unlink), self.assertRaises(OSError):
            D.move(src, dst, "d/f")
        self.assertEqual(calls, ["f", "f"])
        self.assertEqual(open(os.path.join(src, "d/f")).read(), "mine\n")
        self.assertFalse(os.path.lexists(os.path.join(dst, "d/f")))
        D.move(src, dst, "d/f")
        self.assertFalse(os.path.lexists(os.path.join(src, "d/f")))
        self.assertEqual(open(os.path.join(dst, "d/f")).read(), "mine\n")

    def test_a_link_refused_with_eperm_is_copied_without_setuid_and_other_errors_stand(self):
        """The FIX read (2026-10-12): under fs.protected_hardlinks=1 linking another user's file fails with EPERM, so a
        stray root-owned file would fail every deploy. EPERM copies as EXDEV does, and the copy keeps the permission
        bits but never a setuid or setgid bit; any other link error still fails the move and copies nothing."""
        from lander import deploy as D
        src, dst = self.two_dirs({"d/run": "#!/bin/sh\n", "d/other": "x\n"})
        os.chmod(os.path.join(src, "d/run"), 0o6755)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(src, "d/run")).st_mode) & 0o6000, 0o6000)

        def link(*a, **kw):
            raise OSError(errno.EPERM, "Operation not permitted")
        with mock.patch.object(D.os, "link", link), mock.patch.object(D, "copy_at", wraps=D.copy_at) as cp:
            D.move(src, dst, "d/run")
        self.assertEqual(cp.call_count, 1)
        self.assertFalse(os.path.lexists(os.path.join(src, "d/run")))
        self.assertEqual(open(os.path.join(dst, "d/run")).read(), "#!/bin/sh\n")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(dst, "d/run")).st_mode), 0o755)

        def link2(*a, **kw):
            raise OSError(errno.EACCES, "Permission denied")
        with mock.patch.object(D.os, "link", link2), mock.patch.object(D, "copy_at", wraps=D.copy_at) as cp, \
                self.assertRaises(OSError):
            D.move(src, dst, "d/other")
        self.assertEqual(cp.call_count, 0)
        self.assertEqual(open(os.path.join(src, "d/other")).read(), "x\n")
        self.assertFalse(os.path.lexists(os.path.join(dst, "d/other")))

    def test_copy_at_refuses_a_fifo_and_removes_a_part_written_copy(self):
        """copy_at() copies only a file or a symlink: a fifo raises EPERM and nothing is made. A write that fails part
        way removes the copy; the same file with writes working is copied whole."""
        from lander import deploy as D
        src, dst = self.two_dirs({"d/big": "a" * (3 << 20)})
        os.mkfifo(os.path.join(src, "d/pipe"))
        s, d = os.open(os.path.join(src, "d"), os.O_RDONLY), os.open(os.path.join(dst, "d"), os.O_RDONLY)
        try:
            with self.assertRaises(OSError) as e:
                D.copy_at(s, d, "pipe")
            self.assertEqual(e.exception.errno, errno.EPERM)
            self.assertFalse(os.path.lexists(os.path.join(dst, "d/pipe")))
            real, n = os.write, []

            def write(fd, b):
                n.append(1)
                if len(n) > 1:
                    raise OSError(errno.ENOSPC, "No space left on device")
                return real(fd, b)
            with mock.patch.object(D.os, "write", write), self.assertRaises(OSError):
                D.copy_at(s, d, "big")
            self.assertEqual(len(n), 2)   # one chunk written before the failure
            self.assertFalse(os.path.lexists(os.path.join(dst, "d/big")))
            D.copy_at(s, d, "big")
            self.assertEqual(os.path.getsize(os.path.join(dst, "d/big")), 3 << 20)
        finally:
            os.close(s)
            os.close(d)

    def test_a_state_dir_that_cannot_be_made_fails_the_deploy_cleanly_and_counts(self):
        """A file where deploy-aside/ goes: no OSError escapes; read-tree's refusal stands, the target is failed and
        its tries count, so the deploy-stopped card goes and it stops after TRIES."""
        from lander import deploy as D
        os.makedirs(C.state(), exist_ok=True)
        self.write(C.state(), {"deploy-aside": "a file, not a dir\n"})
        self.write(self.root, {"docs/draft.md": "old draft\n"})
        merged = self.push("main", {"docs/draft.md": "committed\n"})
        head = self.git(self.root, "rev-parse", "HEAD")
        with self.assertRaises(D.Failed) as e:
            D.pull(self.root, "main", merged)
        self.assertIn("no untracked file was moved aside", e.exception.why)
        D.request("demo", merged)
        with mock.patch.object(C, "say") as say:
            st = D.run("demo", green=lambda r, s: True)["targets"]["demo"]
        self.assertEqual((st["state"], st["tries"]), ("failed", 1))
        self.assertIn("no untracked file was moved aside", st["why"])
        self.assertIn("[demo] deploy stopped", say.call_args[0][1])
        self.assertEqual(self.git(self.root, "rev-parse", "HEAD"), head)
        self.assertEqual(open(os.path.join(self.root, "docs/draft.md")).read(), "old draft\n")

    def test_a_config_rewrite_of_the_pinned_url_is_refused(self):
        """url.<x>.insteadOf in the shared .git/config would redirect even the pinned URL: the lander refuses."""
        from lander import deploy as D
        from lander import tip as TP
        self.forge_origin()
        self.git(self.root, "config", f"url.{self.tmp}/evil.git.insteadOf", self.origin)
        self.assertEqual((G.remote_url(self.root), TP.origin_tip(self.root, "main")), ("", ""))
        with self.assertRaises(G.GitError):
            G.fetch(self.root, "main")
        with self.assertRaises(D.Failed):
            D.pull(self.root, "main", self.origin_rev("main"))
        self.git(self.root, "config", "--unset", f"url.{self.tmp}/evil.git.insteadOf")
        self.git(self.root, "config", f"url.{self.tmp}/evil.git.pushInsteadOf", self.origin)
        self.assertEqual(G.remote_url(self.root), "")

    def test_a_rewrite_with_a_space_in_its_subsection_via_include_is_refused(self):
        """url.<tmp>/e x.insteadOf, brought in through include.path: -z parsing still finds the value."""
        from lander import tip as TP
        self.forge_origin()
        shutil.copytree(os.path.join(self.tmp, "evil.git"), os.path.join(self.tmp, "e x"), symlinks=True)
        cfg = os.path.join(self.tmp, "x.cfg")
        with open(cfg, "w") as f:
            f.write(f'[url "{self.tmp}/e x"]\n\tinsteadOf = {self.origin}\n')
        self.git(self.root, "config", "include.path", cfg)
        self.assertIn(f"url.{self.tmp}/e x.insteadof",
                      self.git(self.root, "config", "--get-regexp", r"^url\..*\.insteadof$"))
        self.assertTrue(G.rewritten(self.root, self.origin))
        self.assertEqual((G.remote_url(self.root), TP.origin_tip(self.root, "main")), ("", ""))
        with self.assertRaises(G.GitError):
            G.fetch(self.root, "main")

    def test_only_a_github_https_url_is_taken_from_remotes_json(self):
        """remotes.json is reachable by a worker: outside the member clones dir only https://github.com/o/r is
        taken; a member's clone keeps the URL the lander set on it."""
        with mock.patch.object(G, "ALLOW_LOCAL", False):
            for bad in (self.origin, "file:///tmp/x.git", "https://evil.example/o/demo.git",
                        "https://github.com.evil/o/demo.git", "ssh://git@github.com/o/demo.git",
                        "https://github.com/o/demo.git/../../x"):
                self.pin_remote(self.root, bad)
                self.assertEqual(G.remote_url(self.root), "", bad)
            for good in ("https://github.com/o/demo.git", "https://github.com/o/demo"):
                self.pin_remote(self.root, good)
                self.assertEqual(G.remote_url(self.root), good)
            clone = f"{J.clones_dir()}/h--t"
            os.makedirs(J.clones_dir(), exist_ok=True)
            self.git(self.tmp, "clone", "-q", "--bare", self.origin, clone)
            self.assertEqual(G.remote_url(clone), self.origin)

    def test_a_checkout_with_no_pinned_url_is_refused(self):
        from lander import deploy as D
        from lander import tip as TP
        os.unlink(f"{self.home}/.cc/lander/remotes.json")
        self.assertEqual(TP.origin_tip(self.root, "main"), "")
        self.assertEqual(G.remote_head(self.root, "main"), "")
        with self.assertRaises(G.GitError):
            G.fetch(self.root, "main")
        with self.assertRaises(D.Failed):
            D.pull(self.root, "main", self.origin_rev("main"))

    def test_missing_planner_holds(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        u = self.units()
        del u["planner"]
        L.Lane("demo", u).run()
        j = self.job()
        self.assertEqual((j.state, j.extra["why"]), (T.HELD, "planner is not installed"))
        self.assertTrue(J.not_before_left(j) > 0)

    def test_draft_and_conflict_hold(self):
        self.pr(1, {"a/x": "n\n"}, isDraft=True)
        self.pr(2, {"b/y": "n\n"}, mergeable="CONFLICTING")
        J.submit("demo", 1)
        J.submit("demo", 2)
        u, _ = self.land()
        self.assertIn("draft", self.job(1).extra["why"])
        self.assertIn("conflicts", self.job(2).extra["why"])
        self.assertEqual(u["runner"].calls, [])

    def test_lander_class_goes_to_lander_self(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        u, _ = self.land(planner=Planner(klass=T.LANDER))
        self.assertEqual(self.job().state, T.QUERY)
        self.assertEqual(u["cards"].calls[0][3], "lander-self")


class Repair(Fixture):
    """A conflict with main mends itself (repair.py): one rebase round per conflict, and ONE
    message to the planning seat when nothing will repair it."""

    def setUp(self):
        super().setUp()
        with open(f"{os.environ['CC_BOARDS']}/demo.json", "w") as f:
            json.dump({"tracks": {f"row-{n}": {"status": "review"} for n in (1, 2, 3)}}, f)

    def due(self, pr=1):
        j = self.job(pr)
        j.extra["not_before"] = E.stamp(time.time() - 1)
        J.save(j)

    def gos(self):
        return [c for c in self.box().get("calls", []) if c[0] == "cc" and ("--go" in c or "--say" in c)]

    def held_job(self, pr, state=T.CHECKING, files=("a/x",), branch=None):
        j = T.Job(repo="demo", pr=pr, head="e" * 40, base_sha="d" * 40, files=list(files), state=state,
                  extra={"branch": branch or f"track/row-{pr}", "base_ref": "main", "queued_at": E.stamp()})
        J.save(j)
        return j

    def test_main_moves_under_a_queued_pr_and_its_round_repairs_it(self):
        self.pr(1, {"a/x": "pr\n"})
        self.push("main", {"a/x": "main\n"}, fresh=False)
        J.submit("demo", 1)
        self.land(repair=RP)
        j = self.job()
        self.assertEqual(j.state, T.HELD)
        self.assertIn("conflicts with main: a/x — rebase round 1 of 2 dispatched in row-1", j.extra["why"])
        go = self.gos()
        self.assertEqual(len(go), 1)
        self.assertEqual(go[0][1:4], ["demo", "row-1", "--go"])
        self.assertIn("merge origin/main into this branch", go[0][4])
        self.assertIn("--no-extend", go[0])
        # the round's worker: main merged into the PR's own branch, resolved, pushed
        self.git(self.work, "fetch", "-q", "origin")
        self.git(self.work, "checkout", "-q", "-B", "track/row-1", "origin/track/row-1")
        subprocess.run(["git", "merge", "-q", "origin/main"], cwd=self.work, capture_output=True)
        self.write(self.work, {"a/x": "both\n"})
        self.git(self.work, "commit", "-qam", "merge main")
        self.git(self.work, "push", "-q", "origin", "track/row-1")
        self.due()
        self.land(repair=RP)
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)
        self.assertEqual(self.git(self.tmp, "--git-dir", self.origin, "show", "main:a/x"), "both")
        self.assertEqual(len(self.gos()), 1)   # the repaired head needed no second round

    def test_the_rounds_push_requeues_the_held_pr_at_the_next_tick(self):
        """2026-10-12: #998's round pushed and no queue line followed; it sat held until landing queued it by hand.
        The tick watches a repair-held PR's branch as it watches a handed one, so the push alone requeues it."""
        self.pr(1, {"a/x": "pr\n"})
        self.push("main", {"a/x": "main\n"}, fresh=False)
        J.submit("demo", 1, chat="C1", ts="1.1")
        self.land(repair=RP)
        self.assertEqual(self.job().state, T.HELD)
        self.assertEqual(TK.sweep_repairs(), [])   # no push yet: nothing
        self.git(self.work, "fetch", "-q", "origin")
        self.git(self.work, "checkout", "-q", "-B", "track/row-1", "origin/track/row-1")
        subprocess.run(["git", "merge", "-q", "origin/main"], cwd=self.work, capture_output=True)
        self.write(self.work, {"a/x": "both\n"})
        self.git(self.work, "commit", "-qam", "merge main")
        self.git(self.work, "push", "-q", "origin", "track/row-1")
        self.assertEqual(len(TK.sweep_repairs()), 1)
        self.assertEqual(TK.sweep_repairs(), [])   # the request already waiting does it; no second one
        self.assertEqual([(r["who"], r["chat"]) for _, r in J.requests("demo")], [("repair push", "C1")])
        self.assertIn("repair pushed", self.log())
        self.land(repair=RP)   # not made due by hand: the request alone takes it up
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)
        self.assertEqual(len(self.gos()), 1)

    def test_a_held_pr_no_round_was_started_for_is_not_watched(self):
        for pr, why, r in ((1, "PR #1 conflicts with main: a/x — rebase it", {}),
                           (2, "PR #2 conflicts with main: a/x — rebase round 1 of 2 dispatched in row-2",
                            {"head": "c" * 40}),
                           (3, "a draft", {"head": "e" * 40})):
            j = self.held_job(pr, state=T.HELD)
            j.extra.update(why=why, hold="pr")
            J.save(j)
            if r:
                J.put_repair("demo", pr, r)
        with mock.patch.object(G, "remote_head", lambda *a, **k: "f" * 40):
            self.assertEqual(TK.sweep_repairs(), [])
            J.put_repair("demo", 2, {"head": "e" * 40})   # the same job with a round at its head is watched
            self.assertEqual(len(TK.sweep_repairs()), 1)
        self.assertEqual([r["pr"] for _, r in J.requests("demo")], [2])

    def test_a_round_still_running_is_not_dispatched_again(self):
        self.pr(1, {"a/x": "pr\n"})
        self.push("main", {"a/x": "main\n"}, fresh=False)
        J.submit("demo", 1)
        self.land(repair=RP)
        self.due()
        self.land(repair=RP)
        self.assertEqual(len(self.gos()), 1)
        self.assertIn("has until", self.job().extra["why"])

    def test_refused_launches_spend_no_round_and_the_last_sends_one_message_and_never_another(self):
        self.pr(1, {"a/x": "pr\n"})
        self.push("main", {"a/x": "main\n"}, fresh=False)
        self.set_box(go_rc=1, go_out="cc: demo is paused")
        J.submit("demo", 1)
        cards = Rec()
        self.land(repair=RP, cards=cards)
        self.assertIn("rebase round 1 in row-1 was not dispatched: cc: demo is paused — the next wake tries again",
                      self.job().extra["why"])
        for _ in range(RP.REFUSALS - 1):
            self.due()
            self.land(repair=RP, cards=cards)
        self.assertEqual(len(self.gos()), RP.REFUSALS)
        self.assertIn("rebase round 1 in row-1 was not dispatched: cc: demo is paused — the next wake hands it to "
                      "the planning seat", self.job().extra["why"])
        self.assertEqual((J.repair_record("demo", 1)["rounds"], J.repair_record("demo", 1)["refusals"]),
                         (0, RP.REFUSALS))
        self.assertEqual([c for c in cards.calls if c[0] == "stopped"], [])   # the refusals said nothing yet
        self.due()
        self.land(repair=RP, cards=cards)
        for _ in range(3):   # later wakes and a sweep find nothing to say again
            self.land(repair=RP, cards=cards)
            with contextlib.redirect_stdout(io.StringIO()):
                RP.cmd_sweep([])
        stops = [c for c in cards.calls if c[0] == "stopped"]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0][3], "planning")
        self.assertIn(f"PR #1 conflicts with main: a/x — the launch of its rebase round in row-1 was refused "
                      f"{RP.REFUSALS} times (the last: cc: demo is paused): a/x — next: clear that refusal, or merge main into "
                      f"it by hand and push; the push queues it again", stops[0][2])
        self.assertEqual(len(self.gos()), RP.REFUSALS)
        self.assertTrue(os.path.exists(J.handed_path("demo", 1)))   # a push re-queues it

    def test_a_pr_no_row_owns_goes_to_planning_at_once(self):
        cards = Rec()
        j = self.held_job(7, branch="planning/seat-fix")
        L.Lane("demo", self.units(repair=RP, cards=cards)).conflict(j, ["a/x"])
        self.assertEqual(self.gos(), [])
        self.assertEqual([c[3] for c in cards.calls if c[0] == "stopped"], ["planning"])
        self.assertIn("no row owns it", cards.calls[-1][2])

    def test_a_cloud_pr_its_body_closes_a_row_for_still_goes_to_planning(self):
        cards = Rec()
        j = self.held_job(1, branch="cloud/fix-it-x7")
        j.extra["body"] = "Closes row-1"
        self.assertEqual(L.BoardRules().find_track("demo", j), "")   # the body names its row for close only
        L.Lane("demo", self.units(repair=RP, cards=cards)).conflict(j, ["a/x"])
        self.assertEqual(self.gos(), [])
        self.assertIn("no row owns it", cards.calls[-1][2])

    def conflicting_push(self, text):
        """The round's worker pushed, but the head still conflicts; its re-queue goes through the request path."""
        self.push("track/row-1", {"a/x": text}, fresh=False)
        J.submit("demo", 1, who="cc-loop")

    def test_a_requeue_keeps_the_round_count_and_round_3_goes_to_planning(self):
        self.pr(1, {"a/x": "pr\n"})
        self.push("main", {"a/x": "main\n"}, fresh=False)
        J.submit("demo", 1)
        cards = Rec()
        self.land(repair=RP, cards=cards)
        self.assertIn("rebase round 1 of 2 dispatched", self.job().extra["why"])
        self.conflicting_push("pr two\n")
        self.land(repair=RP, cards=cards)   # drained as a fresh start (jobs._fresh): the count is not in job.extra
        self.assertIn("rebase round 2 of 2 dispatched", self.job().extra["why"])
        self.conflicting_push("pr three\n")
        self.land(repair=RP, cards=cards)
        self.assertEqual(len(self.gos()), 2)
        stops = [c for c in cards.calls if c[0] == "stopped"]
        self.assertEqual([c[3] for c in stops], ["planning"])
        self.assertIn("2 rebase rounds in row-1 did not resolve it: a/x — next: merge main into it by hand, or brief "
                      "row-1 on the conflict, and push; the push queues it again", stops[0][2])

    def test_a_new_head_after_a_refusal_streak_gets_its_round(self):
        self.pr(1, {"a/x": "pr\n"})
        self.push("main", {"a/x": "main\n"}, fresh=False)
        self.set_box(go_rc=1, go_out="cc: demo is paused")
        J.submit("demo", 1)
        cards = Rec()
        self.land(repair=RP, cards=cards)
        for _ in range(RP.REFUSALS):
            self.due()
            self.land(repair=RP, cards=cards)
        self.assertEqual([c[3] for c in cards.calls if c[0] == "stopped"], ["planning"])
        self.set_box(go_rc=0, go_out="")
        self.conflicting_push("pr two\n")   # the pause is over and the seat pushed: a new streak
        self.land(repair=RP, cards=cards)
        self.assertIn("rebase round 1 of 2 dispatched", self.job().extra["why"])
        self.assertEqual(J.repair_record("demo", 1)["refusals"], 0)

    def test_the_record_ends_with_the_merge(self):
        J.put_repair("demo", 1, {"rounds": 2})
        j = self.held_job(1, state=T.MERGEABLE)
        J.move(j, T.MERGED, "landed")
        self.assertEqual(J.repair_record("demo", 1), {})

    def test_a_close_keeps_the_record_so_a_reopen_buys_no_rounds(self):
        J.put_repair("demo", 1, {"rounds": 2})
        J.move(self.held_job(1, state=T.QUEUED), T.DONE, "the PR is closed")
        self.assertEqual(J.repair_record("demo", 1), {"rounds": 2})
        cards = Rec()
        L.Lane("demo", self.units(repair=RP, cards=cards)).conflict(self.held_job(1), ["a/x"])
        self.assertEqual(self.gos(), [])
        self.assertIn("2 rebase rounds in row-1 did not resolve it", cards.calls[-1][2])

    def test_a_record_that_will_not_read_goes_to_planning_and_a_negative_count_reads_as_none(self):
        bad = ('{"rounds": 1', "[2]", '"x"', '{"rounds": "x"}', '{"refusals": [1]}', '{"rounds": 1e999}')
        for n, text in enumerate(bad, 1):
            with self.subTest(text=text):
                os.makedirs(os.path.dirname(J.repair_path("demo", 1)), exist_ok=True)
                with open(J.repair_path("demo", 1), "w") as f:
                    f.write(text)
                cards = Rec()
                L.Lane("demo", self.units(repair=RP, cards=cards)).conflict(self.held_job(1), ["a/x"])
                self.assertEqual(self.gos(), [])
                self.assertEqual([c[3] for c in cards.calls if c[0] == "stopped"], ["planning"])
                self.assertIn("its rebase-round record will not read, so no round runs for it in row-1: a/x",
                              cards.calls[-1][2])
        J.put_repair("demo", 1, {"rounds": -9, "refusals": -9})
        j = self.held_job(1)
        L.Lane("demo", self.units(repair=RP)).conflict(j, ["a/x"])
        self.assertIn("rebase round 1 of 2 dispatched", j.extra["why"])
        self.assertEqual((J.repair_record("demo", 1)["rounds"], J.repair_record("demo", 1)["refusals"]), (1, 0))

    def test_a_refused_launch_is_said_and_tried_again_at_the_next_wake(self):
        self.set_box(go_rc=1, go_out="cc: demo/row-1 waits: the tier holds it")
        j = self.held_job(1)
        L.Lane("demo", self.units(repair=RP)).conflict(j, ["a/x"])
        self.assertIn("round 1 in row-1 was not dispatched: cc: demo/row-1 waits: the tier holds it — the next wake "
                      "tries again", j.extra["why"])
        self.assertIn("--repair", self.gos()[0])   # cc reserves the repair, and adopts one a refusal left open
        r = J.repair_record("demo", 1)
        self.assertEqual((r["rounds"], r["refusals"], r["refused"]),
                         (0, 1, "cc: demo/row-1 waits: the tier holds it"))   # the round is given back
        self.assertLessEqual(r["deadline"], time.time())   # no wait on a round that never ran
        self.set_box(go_rc=0)
        j = self.held_job(1)
        L.Lane("demo", self.units(repair=RP)).conflict(j, ["a/x"])
        self.assertIn("rebase round 1 of 2 dispatched", j.extra["why"])

    def test_two_refusals_then_a_launch_still_get_round_1_and_round_2(self):
        lane = L.Lane("demo", self.units(repair=RP))
        self.set_box(go_rc=1, go_out="cc: demo is paused")
        for _ in range(2):
            j = self.held_job(1)
            lane.conflict(j, ["a/x"])
            self.assertIn("round 1 in row-1 was not dispatched", j.extra["why"])
        self.set_box(go_rc=0)
        j = self.held_job(1)
        lane.conflict(j, ["a/x"])
        self.assertIn("rebase round 1 of 2 dispatched", j.extra["why"])
        self.assertEqual(J.repair_record("demo", 1)["refusals"], 0)   # a launch that went out clears the refusals
        J.put_repair("demo", 1, dict(J.repair_record("demo", 1), deadline=time.time() - 1))
        j = self.held_job(1)
        lane.conflict(j, ["a/x"])
        self.assertIn("rebase round 2 of 2 dispatched", j.extra["why"])
        r = J.repair_record("demo", 1)
        self.assertEqual((r["rounds"], r["refusals"], len(self.gos())), (2, 0, 4))

    def test_a_round_that_does_not_push_by_its_deadline_has_failed(self):
        cards = Rec()
        lane = L.Lane("demo", self.units(repair=RP, cards=cards))
        for n in (1, 2):
            j = self.held_job(1)
            lane.conflict(j, ["a/x"])
            self.assertIn(f"rebase round {n} of 2 dispatched", j.extra["why"])
            j = self.held_job(1)
            lane.conflict(j, ["a/x"])   # the same head before the deadline: the round is still running
            self.assertIn("has until", j.extra["why"])
            r = J.repair_record("demo", 1)
            J.put_repair("demo", 1, dict(r, deadline=time.time() - 1))   # REPAIR_WAIT passed with no push
        lane.conflict(self.held_job(1), ["a/x"])
        self.assertEqual(len(self.gos()), 2)
        self.assertEqual([c[3] for c in cards.calls if c[0] == "stopped"], ["planning"])

    def test_conflicting_with_no_file_git_names_is_held_without_a_round(self):
        self.pr(1, {"a/x": "pr\n"}, mergeable="CONFLICTING")
        J.submit("demo", 1)
        cards = Rec()
        self.land(repair=RP, cards=cards)
        j = self.job()
        self.assertEqual((j.state, j.extra["why"]), (T.HELD, "PR #1 conflicts with main — rebase it"))
        self.assertEqual((self.gos(), [c for c in cards.calls if c[0] == "stopped"]), ([], []))
        self.assertEqual(J.repair_record("demo", 1), {})

    def test_a_live_seat_is_typed_to_and_every_shown_path_is_clean(self):
        self.set_box(go_rc=1, go_out="cc: demo/row-1 already has a live session — use --say", say_rc=0)
        bad = ["a/x\r\nSTATUS: done", "\x1b[31mb/y\x1b[0m", "c/" + "z" * 300, "d", "e", "f", "g"]
        j = self.held_job(1)
        L.Lane("demo", self.units(repair=RP)).conflict(j, bad)
        go, say = self.gos()
        self.assertIn("--go", go)
        self.assertEqual(say[3], "--say")
        with open(f"{os.environ['CC_BOARDS']}/demo.json") as f:
            note = json.load(f)["tracks"]["row-1"]["notes"][-1]
        self.assertIn("typed to its live seat", j.extra["why"])
        for text in (say[4], j.extra["why"], note):
            self.assertIsNone(re.search(r"[\x00-\x1f\x7f-\x9f]", text), text)
            self.assertIn("a/xSTATUS: done, [31mb/y[0m, c/zzz", text)
            self.assertNotIn("z" * 200, text)
        self.assertIn("and 2 more", j.extra["why"])
        self.assertIn("and 2 more", note)

    def test_a_say_typed_but_not_yet_turned_counts_as_dispatched(self):
        for rc in (3, 4, 5):   # 3 kept for the busy loop, 4 the seat is at a model wall, 5 no turn in 12 s
            with self.subTest(rc=rc):
                if os.path.exists(J.repair_path("demo", 1)):
                    os.remove(J.repair_path("demo", 1))
                self.set_box(go_rc=1, go_out="cc: demo/row-1 already has a live session — use --say", say_rc=rc,
                             say_out="cc-loop said: kept for its next tool call")
                j = self.held_job(1)
                L.Lane("demo", self.units(repair=RP)).conflict(j, ["a/x"])
                self.assertIn("rebase round 1 of 2 queued for its live seat in row-1", j.extra["why"])
                r = J.repair_record("demo", 1)
                self.assertEqual((r["rounds"], r["refusals"], "refused" in r), (1, 0, False))
                self.assertGreater(r["deadline"], time.time())

    def test_sweep_leaves_a_busy_lane_for_the_next_pass(self):
        j = self.held_job(3, state=T.QUEUED)
        j.extra.update(held_from=T.QUEUED, hold="pr", why="PR #3 conflicts with main: a/x",
                       not_before=E.stamp(time.time() + 900))
        J.move(j, T.HELD, j.extra["why"])
        with J.lane_lock("demo") as got, contextlib.redirect_stdout(io.StringIO()) as o:
            self.assertTrue(got)
            self.assertEqual(RP.cmd_sweep([]), 0)
        self.assertIn("demo lane busy, left for the next pass", o.getvalue())
        self.assertGreater(J.not_before_left(self.job(3)), 0)

    def test_sweep_makes_held_conflicts_due_but_the_skipped_one(self):
        for pr in (3, 4, 5):
            j = self.held_job(pr, state=T.QUEUED)
            why = f"PR #{pr} conflicts with main: a/x" if pr != 5 else "PR #5 is a draft — mark it ready for review"
            j.extra.update(held_from=T.QUEUED, hold="pr", why=why, not_before=E.stamp(time.time() + 900))
            J.move(j, T.HELD, why)
        with contextlib.redirect_stdout(io.StringIO()) as o:
            self.assertEqual(RP.cmd_sweep(["--skip", "demo#4"]), 0)
        self.assertEqual(J.not_before_left(self.job(3)), 0)
        self.assertGreater(J.not_before_left(self.job(4)), 0)
        self.assertGreater(J.not_before_left(self.job(5)), 0)
        self.assertIn("1 held on a conflict made due: demo#3", o.getvalue())


class Lanes(Fixture):
    def test_second_lane_stands_down(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        with J.lane_lock("demo") as got:
            self.assertTrue(got)
            self.assertEqual(J.running("demo"), os.getpid())
            u, lines = self.land()
            self.assertIn("already running", lines[0])
            self.assertEqual(u["runner"].calls, [])
            self.assertEqual(len(J.requests("demo")), 1)
        self.assertEqual(J.running("demo"), 0)
        self.land()
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)

    def test_pause_and_tier_hold_leave_the_file_untouched(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        p = J.job_path("demo", 1)
        def read():
            with open(p) as f:
                return f.read()
        before = read()
        self.set_box(paused=["demo"])
        u, lines = self.land()
        self.assertEqual(read(), before)
        self.assertIn("paused", lines[0])
        self.set_box(paused=[], tier_stop=True)
        u, lines = self.land()
        self.assertEqual(read(), before)
        self.assertEqual(u["runner"].calls, [])
        self.assertIn("tier", lines[0])
        # the tier lets a job past its merge go on
        j = self.job()
        j.state = T.MERGED
        j.extra["tip_sha"] = self.origin_rev("main")
        J.save(j)
        self.land()
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)
        self.assertNotIn("stage demo#1 lane", self.log())   # a held job is not timed


class ReleaseSwitch(Fixture):
    """A promote reaches a running lane between jobs: the job in flight ends on its release, the next one does not
    start there."""

    def setUp(self):
        super().setUp()
        self.rels = {}
        for n in ("aaaa", "bbbb"):
            d = self.rels[n] = os.path.realpath(os.path.join(self.home, ".cc", "lander", "releases", n))
            os.makedirs(os.path.join(d, "core", "lander"))
            open(os.path.join(d, "core", "lander", "cli.py"), "w").close()
        self.point("aaaa")
        self.mine = self.rels["aaaa"]
        p = mock.patch.object(J, "running_release", lambda: self.mine)
        p.start()
        self.addCleanup(p.stop)
        self.spawned = []
        p = mock.patch.object(L, "spawn_lane", lambda repo, rel: (self.spawned.append((repo, rel, J.running(repo))),
                                                                  (True, "test"))[1])
        p.start()
        self.addCleanup(p.stop)

    def point(self, n):
        cur = os.path.join(self.home, ".cc", "lander", "current")
        with contextlib.suppress(OSError):
            os.unlink(cur)
        os.symlink(self.rels[n], cur)

    def test_a_promote_between_jobs_switches_before_the_next_job(self):
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        runner = Runner(hook=lambda name, n: self.point("bbbb") if n == 1 else None)   # promoted mid-check of #1
        with mock.patch.object(L.Lane, "width", lambda self: 1):   # #2 is planned, and waits for #1's slot
            u, lines = self.land(runner=runner, reviewer=Reviewer(V("LAND"), V("LAND")))
        # the check in flight finished on the release it started on and was recorded; nothing new started after it
        self.assertEqual((self.job(1).state, sorted(self.job(1).results)), (T.CHECKING, ["a"]))
        self.assertEqual([c[0] for c in runner.calls], ["a"])
        # #2 was planned and waiting for the slot, or not yet taken up, as the promote met the lane: either way no check
        self.assertIn(self.job(2).state, (T.QUEUED, T.CHECKING))
        self.assertEqual(self.job(2).results, {})
        self.assertFalse(self.box().get("merges"))
        # a lane from the new release was started, after the lock was let go
        self.assertEqual(self.spawned, [("demo", self.rels["bbbb"], 0)])
        self.assertIn("this lane takes no new job", lines[-1])
        self.assertIn("lane-switch demo", self.log())
        self.assertFalse(os.path.exists(J.lane_file("demo", "running")))
        # the lane on the new release takes both on from where they stood: #1 does not run `a` again
        self.mine = self.rels["bbbb"]
        self.land(runner=runner, reviewer=Reviewer(V("LAND")))
        self.assertEqual((self.job(1).state, self.job(2).state), (T.DEPLOY_PENDING, T.DEPLOY_PENDING))
        self.assertEqual([c[0] for c in runner.calls], ["a", "b"])
        self.assertEqual(len(self.spawned), 1)

    def test_a_promote_met_while_a_finished_check_is_reaped_switches_before_the_job_moves_on(self):
        # the order the lane can meet by chance, forced: it looks for a promote and finds none, then the check
        # in flight promotes and finishes before the lane records it; the job must not move on the old release
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        seen, looked = {}, threading.Event()
        real_loop, real_stale = L.Lane.loop, J.stale_release

        def loop(lane, tried):
            seen["lane"] = lane
            return real_loop(lane, tried)

        def stale():
            r, lane = real_stale(), seen.get("lane")
            if not r and lane and lane.inflight and not looked.is_set():
                looked.set()   # the look came first; the promote and the check's end come after it
                futures.wait([f.future for f in lane.inflight.values()], timeout=10)
            return r

        runner = Runner(hook=lambda name, n: (looked.wait(10), self.point("bbbb")) if n == 1 else None)
        with mock.patch.object(L.Lane, "loop", loop), mock.patch.object(J, "stale_release", stale):
            u, lines = self.land(runner=runner, reviewer=Reviewer(V("LAND")))
        self.assertTrue(looked.is_set())
        self.assertEqual((self.job(1).state, sorted(self.job(1).results)), (T.CHECKING, ["a"]))
        self.assertFalse(self.box().get("merges"))
        self.assertEqual(self.spawned, [("demo", self.rels["bbbb"], 0)])
        self.assertIn("this lane takes no new job", lines[-1])

    def test_a_switch_whose_new_lane_will_not_start_leaves_the_job_for_the_next_tick(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.point("bbbb")
        with mock.patch.object(L, "spawn_lane", lambda repo, rel: (False, "no bus")):
            u, lines = self.land(runner=Runner(), reviewer=Reviewer(V("LAND")))
        self.assertIsNone(self.job(1))   # nothing taken on the old release: the request still waits to be drained
        self.assertTrue(J.requests("demo"))
        self.assertIn("the next tick starts it", lines[-1])
        self.assertIn("no lane: no bus", self.log())
        self.assertFalse(os.path.exists(J.lane_file("demo", "running")))

    def test_a_lane_started_on_an_old_release_takes_nothing(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.point("bbbb")
        u, _ = self.land()
        self.assertEqual(u["runner"].calls, [])
        self.assertEqual(len(J.requests("demo")), 1)   # not even drained
        self.assertEqual(len(self.spawned), 1)

    def test_the_running_marker_names_the_release_and_a_checkout_never_switches(self):
        with J.lane_lock("demo"):
            self.assertEqual(J.read_json(J.lane_file("demo", "running"))["release"], self.mine)
        self.assertEqual(J.stale_release(), "")
        self.point("bbbb")
        self.assertEqual(J.stale_release(), self.rels["bbbb"])
        self.mine = self.work                    # a checkout: whatever current says, it is not switched
        self.assertEqual(J.stale_release(), "")
        os.unlink(os.path.join(self.home, ".cc", "lander", "current"))
        os.symlink(self.tmp, os.path.join(self.home, ".cc", "lander", "current"))   # outside releases/
        self.mine = self.rels["aaaa"]
        self.assertEqual(J.stale_release(), "")


class Merge(Fixture):
    def test_merge_argv_pins_and_deletes(self):
        head = self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.land()
        argv = self.box()["rest_merges"][0]   # over REST: no GraphQL hour spent on the merge
        self.assertEqual(argv[:4], ["api", "-X", "PUT", "repos/o/demo/pulls/1/merge"])
        self.assertEqual(argv[4:], ["-f", "merge_method=squash", "-f", f"sha={head}",
                                    "-f", "commit_title=row 1 change (#1)"])
        self.assertEqual(self.box()["deleted"], ["track/row-1"])   # the branch, as --delete-branch did
        self.assertIn(f"stage demo#1 merged sha={head[:12]}", self.log())

    def test_a_fork_pr_is_a_query_never_checked_merged_or_deleted(self):
        # perms on #1925: a fork's branch of a name origin also has was checked at origin's head, then re-queued as
        # "moved" at every pass
        self.pr(1, {"a/x": "n\n"}, isCrossRepository=True, headRepo="someone/demo")
        J.submit("demo", 1)
        u, _ = self.land()
        self.assertEqual((self.job().state, u["runner"].calls), (T.QUERY, []))
        self.assertIn("comes from a fork", self.job().extra["why"])
        self.assertNotIn("rest_merges", self.box())
        self.assertNotIn("deleted", self.box())   # not ours to delete

    def test_a_failed_branch_delete_still_reports_the_merge(self):
        head = self.pr(1, {"a/x": "n\n"})
        self.set_box(delete_fail="gh: Reference does not exist (HTTP 422)")
        J.submit("demo", 1)
        self.land()
        self.assertEqual(self.box()["deleted"], ["track/row-1"])
        self.assertIn(f"stage demo#1 merged sha={head[:12]}", self.log())
        # what merge() puts after "merged (squash, " instead of "remote branch deleted"
        self.assertEqual(GH.delete_branch(self.work, 1), "the branch was left: gh: Reference does not exist (HTTP 422)")

    def test_a_branch_name_with_a_hash_is_deleted_whole(self):
        self.pr(1, {"a/x": "n\n"}, branch="track/x#y")
        J.submit("demo", 1)
        self.land()
        self.assertEqual(self.box()["deleted"], ["track/x%23y"])   # never DELETE …/heads/track/x, another branch

    def test_disjoint_delta_merges_without_rerun(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        hook = lambda name, n: self.push("main", {"b/y": "moved\n"}, fresh=True) if n == 1 else None  # noqa: E731
        u, _ = self.land(runner=Runner(hook=hook))
        self.assertEqual([c[0] for c in u["runner"].calls], ["a"])
        j = self.job()
        self.assertEqual(j.state, T.DEPLOY_PENDING)
        self.assertNotIn("rerun", j.extra)
        self.assertNotIn("tip", j.extra)            # the proof held: merge-tree on the main read before the call
        self.assertEqual(len(self.box()["merges"]), 1)

    def test_a_check_main_gained_after_the_pr_was_checked_is_not_rerun_at_merge(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        planner = Planner()

        def hook(name, n):
            if n == 1:
                self.push("main", {"b/y": "moved\n"})
                planner.owners["new"] = "a/"
        u, _ = self.land(planner=planner, runner=Runner(hook=hook))
        self.assertEqual([c[0] for c in u["runner"].calls], ["a"])   # rule 2: the verdict it has stands
        j = self.job()
        self.assertEqual((j.state, j.plan.checks), (T.DEPLOY_PENDING, ["a"]))
        self.assertNotIn("rerun", j.extra)

    def test_tree_proof_ok_vs_mismatch(self):
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n"})
        J.submit("demo", 1)
        u, _ = self.land()
        self.assertEqual(len(u["deploy"].calls), 1)
        self.set_box(race=True)
        J.submit("demo", 2)
        u, _ = self.land()
        j = self.job(2)
        self.assertEqual((j.state, j.extra["tip"]), (T.DONE, "unvalidated"))
        self.assertEqual(u["deploy"].calls, [])
        self.assertIn("stage demo#2 merged", self.log())
        self.assertIn("proof=mismatch", self.log())
        self.assertEqual(self.log().count("proof=mismatch"), 1)

    def test_git_lock_is_cc_land_lock_and_held_during_the_merge(self):
        path = G.git_lock_path(self.root)
        self.assertEqual(path, os.path.join(self.root, ".git", "cc-land.lock"))
        wt = os.path.join(self.tmp, "wt")
        self.git(self.root, "worktree", "add", "-q", wt, "origin/main")
        self.assertEqual(G.git_lock_path(wt), path)
        self.pr(1, {"a/x": "n\n"})
        self.set_box(lockpath=path)
        subprocess.run(["gh", "pr", "merge", "99", "--match-head-commit", "x"], capture_output=True)  # no PR 99
        J.submit("demo", 1)
        self.land()
        self.assertEqual(self.box()["lock_during_merge"], "held")
        self.set_box(prs={"5": {"headRefName": "track/row-1"}}, merges=[])
        self.push("track/row-1", {"c/z": "q\n"})
        subprocess.run(["gh", "pr", "merge", "5", "--match-head-commit", "x"], capture_output=True)
        self.assertEqual(self.box()["lock_during_merge"], "free")   # nobody holds it outside a merge

    def test_crash_mid_merge_resumes_and_proves(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        real = GH.merge

        def crash(*a, **kw):
            real(*a, **kw)
            raise KeyboardInterrupt("killed after the merge call")
        with mock.patch.object(GH, "merge", crash), self.assertRaises(KeyboardInterrupt):
            self.land()
        j = self.job()
        self.assertEqual(j.state, T.MERGEABLE)
        self.assertIn("merge_attempt", j.extra)
        u, _ = self.land()
        j = self.job()
        self.assertEqual(j.state, T.DEPLOY_PENDING)
        self.assertNotIn("tip", j.extra)
        self.assertNotIn("merge_attempt", j.extra)
        self.assertEqual(len(self.box()["merges"]), 1)              # never merged twice
        self.assertEqual(u["deploy"].calls[0][2], self.origin_rev("main"))

    def test_timeout_after_github_merged_keeps_the_attempt_until_gh_answers(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.set_box(merge_then_timeout=True)
        self.land()
        j = self.job()
        self.assertEqual((j.state, j.extra["held_from"], j.extra["hold"]), (T.HELD, T.MERGEABLE, "box"))
        self.assertIn("merge_attempt", j.extra)
        self.assertFalse(j.extra.get("attempts"))   # an unconfirmed merge is not a refusal
        for _ in range(2):   # gh still down: the resume holds again, the attempt kept
            j = self.job()
            j.extra["not_before"] = E.stamp(time.time() - 1)
            J.save(j)
            os.unlink(GH.backoff_path())
            self.land()
            j = self.job()
            self.assertEqual((j.state, j.extra.get("hold")), (T.HELD, "box"))
            self.assertIn("merge_attempt", j.extra)
            self.assertIn("could not say whether", j.extra["why"])
        self.set_box(down=False)
        j.extra["not_before"] = E.stamp(time.time() - 1)
        J.save(j)
        os.unlink(GH.backoff_path())
        u, _ = self.land()
        j = self.job()
        self.assertEqual(j.state, T.DEPLOY_PENDING)
        self.assertNotIn("tip", j.extra)
        self.assertNotIn("merge_attempt", j.extra)
        self.assertEqual(len(self.box()["merges"]), 1)
        self.assertEqual(u["deploy"].calls[0][2], self.origin_rev("main"))

    def test_resume_proves_against_the_squash_commit_not_a_moved_tip(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        real = GH.merge

        def crash(*a, **kw):
            real(*a, **kw)
            raise KeyboardInterrupt("killed after the merge call")
        with mock.patch.object(GH, "merge", crash), self.assertRaises(KeyboardInterrupt):
            self.land()
        squash = self.origin_rev("main")
        self.push("main", {"b/later": "someone else\n"})   # main moves on before the resume
        self.land()
        j = self.job()
        self.assertEqual(j.state, T.DEPLOY_PENDING)
        self.assertNotIn("tip", j.extra)                  # proved: not "unvalidated" against the moved tip
        self.assertEqual(j.extra["tip_sha"], squash)
        self.assertNotIn("proof=mismatch", self.log())

    def test_merge_pins_head_not_a_stale_approved_head(self):
        head = self.pr(1, {"b/y": "n\n"})
        J.approve("demo", 1, "UOWNER", "0" * 40)   # no protected path: nothing to pin to
        J.submit("demo", 1)
        self.land()
        argv = self.box()["merges"][0]
        self.assertEqual(argv[argv.index("--match-head-commit") + 1], head)
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)

    def test_merged_before_and_head_moved(self):
        self.pr(1, {"a/x": "n\n"}, state="MERGED", headRefOid="f" * 40)
        J.submit("demo", 1)
        self.land()
        self.assertIn("stage demo#1 merged by=before", self.log())
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)
        # a head that moves between the checks and the merge sends the job back to queued (and it lands the new head)
        self.pr(2, {"b/y": "n\n"})
        J.submit("demo", 2)
        hook = lambda name, n: self.push("track/row-2", {"b/y": "n2\n"}, fresh=False) if n == 1 else None  # noqa
        u, _ = self.land(runner=Runner(hook=hook))
        self.assertEqual(self.job(2).head, self.git(self.work, "rev-parse", "track/row-2"))
        self.assertIn("queued", [h["state"] for h in self.job(2).history[1:]])


class Together(Runner):
    """A runner whose each check waits (at most `wait` s) for another check to be running beside it, and counts the
    most it saw running at once."""

    def __init__(self, wait=1.0, **kw):
        super().__init__(**kw)
        self.wait, self.now, self.peak, self.cv = wait, 0, 0, threading.Condition()

    def run(self, check, tree, where):
        with self.cv:
            self.now += 1
            self.peak = max(self.peak, self.now)
            self.cv.notify_all()
            self.cv.wait_for(lambda: self.now > 1, timeout=self.wait)
        try:
            return super().run(check, tree, where)
        finally:
            with self.cv:
                self.now -= 1


class AtOnce(Fixture):
    """Brief, 10-13: "(1) every queued PR is planned and checked at once, no parking. (2) At merge time, re-check only
    when merge-tree finds a text conflict with current main, or main is red on a check the PR's plan includes.
    Otherwise merge on the verdict it already has. (3) A PR whose plan includes a check that is red on main jumps the
    queue. (4) A main-red fix's checks take first claim on a free slot." Each case asserts what is kept and what is not.
    """

    def setUp(self):
        super().setUp()
        p = mock.patch.object(L, "POLL", 0.05)
        p.start()
        self.addCleanup(p.stop)

    def merged_order(self):
        return [int(argv[2]) for argv in self.box().get("merges", [])]

    def ci_moves_main(self, files, red=()):
        """At the first GitHub CI look of PR #1, main moves (`files`), and main's record holds `red` red."""
        moved, real = [], L.Lane.ci_green

        def ci_green(lane, job):
            if job.pr == 1 and not moved:
                moved.append(self.push("main", files))
                if red:
                    self.main_red(*red)
            return real(lane, job)
        return moved, mock.patch.object(L.Lane, "ci_green", ci_green)

    def test_two_prs_changing_the_same_lines_are_checked_side_by_side(self):
        for width, peak in ((2, 2), (1, 1)):   # kept: both in flight at once; one slot: one at a time
            with self.subTest(width=width):
                self.setUp()
                self.pr(1, {"a/x": "one\n"})
                self.pr(2, {"a/x": "two\n"})   # the same line of the same file
                J.submit("demo", 1)
                J.submit("demo", 2)
                runner = Together()
                with mock.patch.object(L.Lane, "width", lambda lane: width):
                    _, lines = self.land(runner=runner)
                self.assertEqual(runner.peak, peak, lines)
                self.assertEqual(sorted(c[0] for c in runner.calls), ["a", "a"])
                self.assertFalse([ln for ln in lines if "waits for PR" in ln])   # nobody parked
                merged = self.merged_order()   # one merges, and the other then conflicts with the main it made
                self.assertEqual(len(merged), 1)
                self.assertIn("conflicts with main: a/x", self.job(3 - merged[0]).extra["why"])

    def test_a_clean_pr_merges_on_its_verdict_after_main_moved(self):
        # kept: main moved, no red record; and main red only on a check outside the plan: the same, no rerun
        for red in ((), ("b",)):
            with self.subTest(red=red):
                self.setUp()
                self.pr(1, {"a/x": "n\n"})
                J.submit("demo", 1)
                moved, patch = self.ci_moves_main({"c/z": "moved\n"}, red)
                with patch:
                    u, lines = self.land()
                j = self.job()
                self.assertEqual([c[0] for c in u["runner"].calls], ["a"], lines)
                self.assertEqual((j.state, j.base_sha), (T.DEPLOY_PENDING, moved[0]))
                self.assertNotIn("rerun", j.extra)
                self.assertNotIn(T.CHECKING, [h["state"] for h in j.history][3:])   # it never went back
                self.assertEqual(self.merged_order(), [1])

    def test_a_light_fix_with_no_ci_is_handed_back(self):
        # security read of #1922: a PR that drops its own CI trigger lands as "no CI"; a demoted FIX needs CI that ran
        for light in (True, False):
            with self.subTest(light=light):
                self.setUp()
                self.pr(1, {"a/x": "n\n"})
                J.submit("demo", 1)
                saved = T.Verdict(verdict=T.LAND, digest="d", extra={"light_fix": True} if light else {})
                with mock.patch.object(R, "saved", lambda digest: saved):
                    _, lines = self.land()
                self.assertEqual(self.merged_order(), [] if light else [1], lines)
                if light:
                    self.assertIn("no GitHub CI ran", J.read_json(J.handed_path("demo", 1))["why"])
                else:
                    self.assertEqual((self.job().state, self.job().extra.get("ci")), (T.DEPLOY_PENDING, "none"))

    def test_a_light_fix_with_no_ci_is_handed_back_when_its_state_file_is_lost(self):
        # security read of #1922: the light flag lived only in the saved review state; the PR's marker carries it too
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        marker = R.marker(T.Verdict(verdict=T.LAND, digest="d", extra={"light_fix": True}), "b" * 40, "c" * 40, "me")
        self.assertTrue(R.imported(marker).extra.get("light_fix"))
        light = T.Verdict(verdict=T.LAND, digest="d", extra=R.imported(marker).extra)
        with mock.patch.object(R, "saved", lambda digest: None), \
                mock.patch.object(R, "recorded", lambda comments, digests, head="": light), \
                mock.patch.object(R, "pr_view", lambda *a, **k: {"comments": []}):
            _, lines = self.land()
        self.assertEqual(self.merged_order(), [], lines)
        self.assertIn("no GitHub CI ran", J.read_json(J.handed_path("demo", 1))["why"])

    def test_a_mergeable_pr_that_conflicts_with_the_moved_main_goes_to_repair(self):
        with open(f"{os.environ['CC_BOARDS']}/demo.json", "w") as f:   # the board row its round goes to
            json.dump({"tracks": {"row-1": {"status": "review"}}}, f)
        self.pr(1, {"a/x": "pr\n"})
        J.submit("demo", 1)
        _, patch = self.ci_moves_main({"a/x": "main\n"})   # kept: the same line on main
        with patch:
            u, _ = self.land(repair=RP)
        j = self.job()
        self.assertEqual(self.merged_order(), [])
        self.assertEqual(j.state, T.HELD)
        self.assertIn("conflicts with main: a/x — rebase round 1 of 2 dispatched in row-1", j.extra["why"])
        self.assertEqual([c[0] for c in u["runner"].calls], ["a"])   # a conflict reruns nothing itself
        self.setUp()   # suppressed: main moved on another file, so it merges
        self.pr(1, {"a/x": "pr\n"})
        J.submit("demo", 1)
        _, patch = self.ci_moves_main({"b/y": "main\n"})
        with patch:
            self.land(repair=RP)
        self.assertEqual((self.job().state, self.merged_order()), (T.DEPLOY_PENDING, [1]))

    def test_main_red_on_a_planned_check_reruns_that_check_alone(self):
        for red, again in (("b", ["b"]), ("c", [])):   # kept: b is in the plan; suppressed: c is not
            with self.subTest(red=red):
                self.setUp()
                self.pr(1, {"a/x": "n\n", "b/y": "n\n"})
                J.submit("demo", 1)
                _, patch = self.ci_moves_main({"docs/r.md": "moved\n"}, (red,))
                with patch:
                    u, lines = self.land()
                j = self.job()
                calls = [c[0] for c in u["runner"].calls]
                self.assertEqual(sorted(calls), sorted(["a", "b"] + again), lines)
                self.assertEqual((j.state, sorted(j.results)), (T.DEPLOY_PENDING, ["a", "b"]))
                whys = [h.get("why") for h in j.history]
                if again:
                    self.assertIn("main moved and is red on b: rerun b", whys)
                    self.assertEqual(j.extra["rerun"], ["b"])
                else:
                    self.assertNotIn("rerun", j.extra)

    def test_a_check_red_on_main_still_runs_on_a_pr_that_owns_none_of_its_paths(self):
        # 10-20: main's record held a check red, so a PR that owned none of its paths was planned without it, and
        # a new red case in it landed unseen. Kept: the PR runs it, and judge's red is the PR's, handed back;
        # suppressed: a ratchet pass (every red case red on main too) merges.
        for status, merged in ((T.FAILED, []), (T.PASSED, [1])):
            with self.subTest(status=status):
                self.setUp()
                self.push("main", {"tests/LANDING.toml": Express.MANIFEST})   # b owns b/** alone
                self.main_red("b")
                self.pr(1, {"a/x": "n\n"})
                J.submit("demo", 1)
                runner = Runner(status={"b": status}, notes={"b": "ratchet: no new reds, b is red on the base too"})
                u, lines = self.land(planner=Planner(owners={"a": "a/", "b": ""}), runner=runner)   # b: a default
                self.assertIn("b", [c[0] for c in runner.calls], lines)
                self.assertEqual(self.merged_order(), merged)
                if not merged:
                    self.assertIn("check b failed", J.read_json(J.handed_path("demo", 1))["why"])

    def test_a_check_red_on_main_that_names_no_case_goes_through_only_on_its_failure_count(self):
        # planning seat's read of #1635: with health.trim gone, a main red whose output names no case ids must not
        # hold every PR; run.judge's ratchet passes the head when it fails no more than the base, else holds it
        from lander import run as RUN

        class Counted(Runner):
            def __init__(self, counts):
                super().__init__()
                self.counts = counts

            def run_plan(self, root, m, plan, files, head_tree, base_tree="", **kw):
                def run(check, tree, where, alone=False, **k):
                    return T.Result(check=check.name, tree=tree, status=T.FAILED, runner="box:x:-",
                                    extra={"loaded": False, "fails": [], "ends": True,
                                           "failed": self.counts[tree == head_tree]})
                return {n: RUN.judge(T.Check(name=n, run="true"), head_tree, base_tree, runner=run)
                        for n in plan.checks}
        for counts, merged in (({True: 2, False: 3}, [1]), ({True: 4, False: 3}, []), ({True: None, False: 3}, [])):
            with self.subTest(counts=counts):
                self.setUp()
                self.push("main", {"tests/LANDING.toml": Express.MANIFEST})
                self.main_red("b")
                self.pr(1, {"a/x": "n\n"})
                J.submit("demo", 1)
                u, lines = self.land(planner=Planner(owners={"a": "a/", "b": ""}), runner=Counted(counts))
                self.assertEqual(self.merged_order(), merged, lines)

    def checked_both(self, red, first=None):
        """#1 (a/x, plan [a]) queued before #2 (b/y, plan [b]); main's record holds `red` red; both planned with no
        slot yet, PR `first` then put first, then the lane runs with one slot. -> the runner"""
        self.push("main", {"tests/LANDING.toml": Express.MANIFEST})
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        if red:
            self.main_red(*red)
        with mock.patch.object(L.Lane, "width", lambda lane: 0):   # planned, no check started
            self.land()
        self.assertEqual((self.job(1).state, self.job(2).state), (T.CHECKING, T.CHECKING))
        if first:
            J.put_first("demo", first, "seat")
        runner = Runner()
        with one_slot():
            self.land(runner=runner)
        return runner

    def test_a_main_red_fix_is_checked_and_merged_before_an_older_pr(self):
        runner = self.checked_both(("b",))   # kept: #2's plan holds b, which main is red on
        self.assertEqual([c[0] for c in runner.calls], ["b", "a"])
        self.assertEqual(self.merged_order(), [2, 1])
        self.setUp()
        runner = self.checked_both(())      # suppressed: main is green, the older goes first
        self.assertEqual([c[0] for c in runner.calls], ["a", "b"])
        self.assertEqual(self.merged_order(), [1, 2])

    def test_a_main_red_fixs_check_takes_the_first_claim_and_an_ordinary_one_does_not(self):
        runner = self.checked_both(("b",))
        self.assertEqual(sorted(runner.firsts), [(1, ("a",), False), (2, ("b",), True)])
        self.setUp()
        runner = self.checked_both(())
        self.assertEqual(sorted(runner.firsts), [(1, ("a",), False), (2, ("b",), False)])

    def test_a_put_first_jobs_check_takes_the_first_claim(self):
        # dispatch #2026, 10-25: put first, its check waited in the slot queue behind later PRs' for 5 h
        runner = self.checked_both((), first=2)
        self.assertEqual([c[0] for c in runner.calls], ["b", "a"])
        self.assertEqual(sorted(runner.firsts), [(1, ("a",), False), (2, ("b",), L.A.FRONT)])

    def test_a_check_that_never_starts_is_said_and_stopped_once(self):
        # dispatch #2026, 10-25: its gate dir sat 5 h with no check run in it, and nothing said so or tried again
        lane = L.Lane.__new__(L.Lane)
        lane.repo, lane.inflight = "demo", {}
        for pr, since in ((1, time.time() - L.NOSTART - 1), (2, time.time()), (3, 0)):   # stuck, fresh, started
            f = L.Flight(None, pr, "a", "h" * 40, "b" * 40, "t" * 40, False, threading.Event())
            f.beat["since"] = since
            lane.inflight[(f"demo-{pr}", "a")] = f
        lane.nostart()
        lane.nostart()
        self.assertEqual([f.stop.is_set() for f in lane.inflight.values()], [True, False, False])
        said = [ln for ln in self.log().splitlines() if "\tnostart demo#" in ln]
        self.assertEqual(len(said), 1, self.log())
        self.assertIn("nostart demo#1 check=a check a has not started in 120 min", said[0])

    def test_a_check_with_no_place_says_so_in_the_queue_log_once_until_it_gets_one(self):
        # dispatch 10-24/25: the lane said "waiting for a slot" only to its own lines, which go nowhere, so a PR
        # waiting on the box looked wedged
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        with mock.patch.object(L.Lane, "width", lambda lane: 0):   # every box place taken, no laptop
            self.land()
        waits = [ln for ln in self.log().splitlines() if "\tslot demo#1 " in ln]
        self.assertEqual(len(waits), 1, self.log())   # once a lane run, not once a look
        self.assertIn("check=a", waits[0])
        self.assertIn("box=0/0", waits[0])

    def test_a_check_left_without_a_place_beside_its_jobs_running_one_says_so_each_time_it_waits_again(self):
        # one slot, three checks: a runs, b has no place (the box places filled inside the per-check loop), b runs,
        # c has no place. A place taken in between clears the job's line, so the second wait is said too
        self.push("main", {"tests/LANDING.toml": Express.MANIFEST})
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})
        J.submit("demo", 1)
        with one_slot():
            self.land(runner=Runner())
        waits = [ln for ln in self.log().splitlines() if "\tslot demo#1 " in ln]
        self.assertEqual([ln.split("check=")[1].split()[0] for ln in waits], ["b", "c"], self.log())
        self.assertIn("box=1/1", waits[0])
        self.assertEqual(sorted(self.job(1).results), ["a", "b", "c"])


class HostFallback(Fixture):
    """A repo that ships no LANDING.toml gets its checks from the release's tests/landing-repos/<repo>.toml
    (review of #771). The lane plans and checks by it, and the tip run reaches its box checks."""
    FB = ('[[check]]\nname = "check"\nrun = "tests/check.sh"\npaths = ["**"]\nclass = "host"\n\n'
          '[[check]]\nname = "e2e"\nrun = "true"\npaths = ["**"]\nclass = "box"\n')

    def test_a_repo_with_no_manifest_is_planned_and_checked_by_its_fallback(self):
        from lander import manifest as MF
        from lander import plan as P
        fb = os.path.join(self.tmp, "release", "tests", "landing-repos")
        self.write(fb, {"demo.toml": self.FB})
        head = self.pr(1, {"b/y": "n\n"})
        J.submit("demo", 1)
        rv = Runner()
        # its host check runs on the host, so it waits for perms' LAND at the head (HostHold): recorded here
        with mock.patch.object(MF, "FALLBACK_DIR", fb), mock.patch.object(R, "perms_recorded", lambda *a: True):
            self.assertEqual(L.Lane("demo", self.units()).fallback, os.path.join(fb, "demo.toml"))
            self.land(planner=P, runner=rv)
            base = self.origin_rev("main")
            tip = TK.tip_plan(self.root, base, head, ["b/y"], fallback=MF.host_fallback("demo"))
        self.assertEqual([c[0] for c in rv.calls], ["check"])
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)
        self.assertEqual(tip.checks, ["e2e"])
        # …and with no fallback for the repo the same change plans no check at all
        self.pr(2, {"b/y": "m\n"})
        J.submit("demo", 2)
        rv2 = Runner()
        with mock.patch.object(MF, "FALLBACK_DIR", os.path.join(self.tmp, "empty")):
            self.land(planner=P, runner=rv2)
        self.assertEqual(rv2.calls, [])


class HostHold(Fixture):
    """A check the box runs on the host itself (manifest.on_host) runs the head's code as the box's user, so it waits
    for perms' security LAND recorded at exactly that head (perms' LAND on #1561, 10-20). The rest of the plan runs
    first."""
    FB = ('[[check]]\nname = "unit"\nrun = "true"\npaths = ["**"]\nclass = "static"\n\n'
          '[[check]]\nname = "on-host"\nrun = "true"\npaths = ["**"]\nclass = "host"\nwhere = ["box"]\n')

    def lane(self, recorded, reading=("", False), read_at=None, entries=None):
        """`entries`, when given, is perms' file itself (review.perms_reads) and perms_recorded runs for real on it,
        each entry at the PR's head and change; else perms_recorded answers `recorded`. `read_at` is perms' read file
        at the head (review.load_read)."""
        from lander import plan as P
        fb = os.path.join(self.tmp, "release", "tests", "landing-repos")
        self.write(fb, {"demo.toml": self.FB})
        head = self.pr(1, {"b/y": "n\n"})
        J.submit("demo", 1)
        rv, asked = Runner(), []
        real = R.perms_recorded

        def recorded_(*a):
            asked.append(a)
            return real(*a) if entries is not None else recorded

        def reads(repo):
            j = self.job()
            return [dict(e, repo="demo", pr=1, head=head, change=j.digest) for e in entries or []], ""
        with mock.patch.object(MF, "FALLBACK_DIR", fb), \
                mock.patch.object(R, "perms_recorded", recorded_), mock.patch.object(R, "perms_reads", reads), \
                mock.patch.object(R, "perms_reading", lambda *a: reading), \
                mock.patch.object(R, "load_read", lambda *a: (read_at, "" if read_at else "absent")):
            self.land(planner=P, runner=rv)
        return head, rv, asked

    def test_with_no_land_at_the_head_the_host_check_never_runs_and_planning_is_asked(self):
        head, rv, asked = self.lane(False)
        self.assertEqual([c[0] for c in rv.calls], ["unit"])
        j = self.job()
        self.assertEqual(j.state, T.QUERY)
        self.assertIn(f"on-host runs the head's code on the host, so it waits for perms' security LAND at {head[:12]}",
                      j.extra["why"])
        self.assertIn("lander perms-read demo 1", j.extra["why"])
        self.assertEqual({(a[0], a[1], a[2]) for a in asked}, {("demo", 1, head)})
        self.assertEqual(asked[0][3], {j.digest})   # the exact change digest, never a carried one

    def test_an_older_land_with_the_same_own_lines_runs_the_host_check(self):
        """A merge of main that moved only context (review.same_change) keeps perms' LAND of the older head."""
        with mock.patch.object(R, "same_change", lambda job, olds=None: "a" * 40):
            _, rv, _ = self.lane(False)
        self.assertEqual(sorted(c[0] for c in rv.calls), ["on-host", "unit"])
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)

    def test_an_older_land_whose_lines_differ_asks_perms_for_the_delta_read(self):
        with mock.patch.object(R, "land_heads", lambda job: ["a" * 40]):
            self.lane(False)
        self.assertIn(f"lander perms-read demo 1 --since {'a' * 40}", self.job().extra["why"])

    def test_with_perms_reading_the_head_the_job_is_held_not_queried(self):
        _, rv, _ = self.lane(False, reading=("perms' security read of PR #1 at x is still running", True))
        self.assertEqual([c[0] for c in rv.calls], ["unit"])
        j = self.job()
        self.assertEqual((j.state, j.extra["hold"]), (T.HELD, "box"))
        self.assertTrue(j.extra["why"].endswith(": perms' security read of PR #1 at x is still running"), j.extra["why"])

    def test_with_perms_land_at_the_head_the_host_check_runs_and_it_merges(self):
        _, rv, _ = self.lane(True)
        self.assertEqual(sorted(c[0] for c in rv.calls), ["on-host", "unit"])
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)

    def unread(self, verdict):
        """Perms' read of #1564: perms_recorded matched repo, PR, head and digest but not the verdict, so a FIX at the
        head ran its host checks as the box's user."""
        _, rv, asked = self.lane(None, entries=[{"verdict": verdict}])
        self.assertTrue(asked)
        self.assertEqual([c[0] for c in rv.calls], ["unit"])
        self.assertEqual(self.job().state, T.QUERY)

    def test_a_fix_in_perms_file_at_the_head_runs_no_host_check(self):
        self.unread("FIX")

    def test_a_do_not_land_in_perms_file_at_the_head_runs_no_host_check(self):
        self.unread("DO-NOT-LAND")

    def ran(self, entry):
        _, rv, _ = self.lane(None, entries=[entry])
        self.assertEqual(sorted(c[0] for c in rv.calls), ["on-host", "unit"])
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)

    def test_a_land_in_perms_file_at_the_head_runs_the_host_check(self):
        self.ran({"verdict": T.LAND})

    def test_an_entry_with_no_verdict_word_is_a_land(self):
        self.ran({})

    def test_a_finished_land_read_not_in_perms_ledger_asks_for_perms_adopt(self):
        self.lane(False, read_at={"state": "done", "verdict": T.LAND})
        j = self.job()
        self.assertEqual(j.state, T.QUERY)
        self.assertIn("lander perms-adopt demo 1", j.extra["why"])
        self.assertNotIn("perms-read", j.extra["why"])
        self.assertEqual(j.extra["host_hold"], j.head)   # review.requeue_held finds it by this when the LAND lands

    def swept(self, *entries, repo="", other=None, edit=None):
        """perms-d3, 10-20: a fresh perms seat writes its LAND into security-reads.json itself, with no `lander
        record`; the tick's `landed` sweep re-queues the held job only for a LAND at its exact head and change.
        `entries` are demo's ledger, each over an entry at the job's repo, PR, head and change; `other`, when given,
        is the ledger of the same held job in a second repo, "other"; `edit` changes demo's job first."""
        head, _, _ = self.lane(False)
        j = self.job()
        base = {"repo": "demo", "pr": 1, "head": head, "change": j.digest}

        def ledger(r, es):
            path = R.perms_reads_path(r)
            os.makedirs(os.path.dirname(path))
            with open(path, "w") as f:
                json.dump([dict(base, **{"repo": r, **e}) for e in es], f)
            os.chmod(path, 0o600)
        with mock.patch.object(R, "PERMS_STATE", os.path.join(self.tmp, "perms-state")):
            ledger("demo", entries)
            if other is not None:
                ledger("other", other)
                J.save(dataclasses.replace(j, repo="other"))
            if edit:
                edit(j)
                J.save(j)
            lines = TK.sweep_landed(repo)
        return lines, [(r["repo"], r["pr"], r["who"]) for _, r in J.requests()]

    def test_a_land_written_into_perms_file_requeues_the_held_job(self):
        lines, reqs = self.swept({"verdict": T.LAND})
        self.assertEqual(reqs, [("demo", 1, "perms")])
        self.assertIn("perms' LAND at", lines[0])

    def test_an_entry_with_no_verdict_word_requeues_the_held_job(self):
        self.assertEqual(self.swept({})[1], [("demo", 1, "perms")])

    def test_a_land_at_another_head_requeues_nothing(self):
        self.assertEqual(self.swept({"head": "c" * 40}), ([], []))

    def test_a_land_of_another_change_requeues_nothing(self):
        self.assertEqual(self.swept({"change": "other"}), ([], []))

    def test_a_land_on_another_pr_requeues_nothing(self):
        self.assertEqual(self.swept({"pr": 2}), ([], []))

    def test_a_land_on_another_repo_requeues_nothing(self):
        self.assertEqual(self.swept({"repo": "other"}), ([], []))

    def test_a_fix_in_perms_file_requeues_nothing(self):
        self.assertEqual(self.swept({"verdict": "FIX"}), ([], []))

    def test_a_fix_after_a_land_requeues_nothing(self):
        self.assertEqual(self.swept({"verdict": T.LAND}, {"verdict": "FIX"}), ([], []))

    def test_a_job_not_in_query_requeues_nothing(self):
        self.assertEqual(self.swept({}, edit=lambda j: setattr(j, "state", T.HANDBACK)), ([], []))

    def test_a_job_with_no_host_hold_requeues_nothing(self):
        self.assertEqual(self.swept({}, edit=lambda j: j.extra.pop("host_hold")), ([], []))

    def test_the_repo_filter_sweeps_only_that_repo(self):
        self.assertEqual(self.swept({}, other=[{}], repo="other")[1], [("other", 1, "perms")])

    def test_a_bad_ledger_entry_is_said_and_the_other_repo_is_still_swept(self):
        """Opus read of #1744: a `change` that is a list made perms_recorded raise, which ended the tick before any
        lane ran."""
        lines, reqs = self.swept({"change": ["x"]}, other=[{}])
        self.assertEqual(reqs, [("other", 1, "perms")])
        self.assertIn("[demo] PR #1: the landed sweep failed: TypeError", "\n".join(lines))
        self.assertIn("landed: TypeError", self.log())


class Review(Fixture):
    def test_incomplete_holds_without_counting_a_read(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.land(planner=Planner(paid=True), reviewer=Reviewer(V(T.INCOMPLETE, tokens=0)))
        j = self.job()
        self.assertEqual((j.state, j.reads_used, j.extra["hold"]), (T.HELD, 0, "box"))
        self.assertIn("stage demo#1 verdict verdict=INCOMPLETE", self.log())
        # …and a bought LAND counts one
        j.extra["not_before"] = E.stamp(time.time() - 1)
        J.save(j)
        self.land(planner=Planner(paid=True), reviewer=Reviewer(V(T.LAND)))
        j = self.job()
        self.assertEqual((j.state, j.reads_used), (T.DEPLOY_PENDING, 1))

    def test_a_head_pushed_while_it_checked_is_not_read(self):
        """hive#67 on 10-23: a worker pushed twice while its PR waited, and the lane bought a full read of each
        superseded head (07:09Z and 07:11Z) before the one it merged. The live head is read before a read is bought."""
        self.pr(1, {"a/x": "one\n"})
        J.submit("demo", 1)
        rv = Reviewer(V(T.LAND), V(T.LAND))
        rv.digest_of = lambda root, base, head: head
        new = []
        pushed = lambda name, n: n == 1 and new.append(self.pr(1, {"a/x": "two\n"}))
        with mock.patch.object(L, "RECHECK_SECS", 3600):
            self.land(planner=Planner(paid=True), reviewer=rv, runner=Runner(hook=pushed))
        j = self.job()
        self.assertEqual([c[0] for c in rv.calls], ["review"])
        self.assertEqual((j.state, j.head), (T.DEPLOY_PENDING, new[0]))
        self.assertIn("before its read", json.dumps(j.history))

    def test_a_handback_standing_from_an_earlier_head_is_read_again_off_the_paid_paths(self):
        """#1064: a seat's security HANDBACK at one head, a new head on no paid path -> read again, never merged unread."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        rv = Reviewer(V(T.HANDBACK_VERDICT, blocking=["still wipes the disk"]))
        rv.stands = V(T.HANDBACK_VERDICT, blocking=["wipes any NVMe disk"], head="c" * 40)
        u, _ = self.land(planner=Planner(paid=False), reviewer=rv)
        self.assertEqual(rv.calls, [("review", "f" * 40)])
        self.assertIsNone(self.job())                               # handed back, not merged
        self.assertEqual(u["cards"].calls[0][3], "seat")
        # …and the same unpaid change with no handback standing merges with no read, as before
        self.pr(2, {"a/y": "n\n"})
        J.submit("demo", 2)
        rv = Reviewer()
        self.land(planner=Planner(paid=False), reviewer=rv)
        self.assertEqual((rv.calls, self.job(2).state), ([], T.DEPLOY_PENDING))

    def test_the_jobs_own_handback_is_read_again_off_the_paid_paths_with_none_on_the_pr(self):
        """The job's own last read was a HANDBACK and nothing stands on the PR (standing() is None): still read."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        j = self.job()
        j.extra["verdict"] = V(T.HANDBACK_VERDICT, blocking=["wipes any NVMe disk"]).to_dict()
        J.save(j)
        rv = Reviewer(V(T.HANDBACK_VERDICT, blocking=["still wipes the disk"]))
        u, _ = self.land(planner=Planner(paid=False), reviewer=rv)
        self.assertEqual(rv.calls, [("delta", T.HANDBACK_VERDICT)])
        self.assertIsNone(self.job())                               # handed back, not merged
        self.assertEqual(u["cards"].calls[0][3], "seat")

    def test_a_handback_keeps_the_jobs_hold_reasons_in_its_attic_file(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        lane = L.Lane("demo", self.units())
        self.assertFalse(os.path.exists(J.attic_path("demo", 1)))
        lane.hold(self.job(), "main-red: check x is red on main too")
        lane.handback(self.job(), "check y failed")
        self.assertIsNone(self.job())                               # off the queue and out of rest/, as before
        with open(J.attic_path("demo", 1)) as f:
            kept = [json.loads(ln) for ln in f]
        self.assertEqual([h.get("why") for h in kept[-1]["history"] if h["state"] == T.HELD],
                         ["main-red: check x is red on main too"])
        self.assertEqual(kept[-1]["state"], T.HANDBACK)
        self.assertEqual(stat.S_IMODE(os.stat(J.attic_path("demo", 1)).st_mode), 0o600)

    def test_a_link_planted_at_the_attic_path_is_refused(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        target = os.path.join(self.tmp, "victim")
        with open(target, "w") as f:
            f.write("untouched\n")
        os.makedirs(os.path.dirname(J.attic_path("demo", 1)), exist_ok=True)
        os.symlink(target, J.attic_path("demo", 1))
        J.remove(self.job())
        self.assertIsNone(self.job())                               # the job still leaves the queue
        with open(target) as f:
            self.assertEqual(f.read(), "untouched\n")               # nothing appended through the link
        self.assertTrue(os.path.islink(J.attic_path("demo", 1)))

    def test_a_fifo_at_the_attic_path_never_hangs_the_removal_and_a_loose_mode_is_tightened(self):
        # read of #1315: O_NONBLOCK and a plain-file check, so a FIFO is refused at once and the refusal is logged
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        os.makedirs(os.path.dirname(J.attic_path("demo", 1)), exist_ok=True)
        os.mkfifo(J.attic_path("demo", 1))
        J.remove(self.job())
        self.assertIsNone(self.job())
        with open(E.log_path()) as f:
            self.assertIn(f"attic demo#1 {J.attic_path('demo', 1)}: not written: errno", f.read())
        os.unlink(J.attic_path("demo", 1))
        with open(J.attic_path("demo", 1), "w"):
            pass
        os.chmod(J.attic_path("demo", 1), 0o644)
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        J.remove(self.job())
        self.assertEqual(stat.S_IMODE(os.stat(J.attic_path("demo", 1)).st_mode), 0o600)

    def test_no_read_count_turns_a_handback_into_a_query(self):
        # owner 10-16: the second handback went to planning as a query and stalled; every one goes back to the seat
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        u, _ = self.land(planner=Planner(paid=True), reviewer=Reviewer(V(T.HANDBACK_VERDICT, blocking=["bug"])))
        self.assertIsNone(self.job())                               # first: handed back
        self.assertEqual(u["cards"].calls[0][3], "seat")
        w = J.read_json(J.handed_path("demo", 1))
        self.assertEqual((w["reads_used"], w["verdict"]["verdict"]), (1, "HANDBACK"))
        J.carry("demo", 1, w["reads_used"])          # what the tick does on a push (sweep_handed)
        J.submit("demo", 1)
        rv = Reviewer(V(T.HANDBACK_VERDICT, blocking=["still"]))
        u, _ = self.land(planner=Planner(paid=True), reviewer=rv)
        self.assertIsNone(self.job())                               # second: handed back again, not a query
        self.assertEqual(J.read_json(J.handed_path("demo", 1))["reads_used"], 2)
        # the prior verdict is not carried by the lane: the reviewer finds it among the box's own PR markers
        self.assertEqual([c[0] for c in rv.calls], ["review"])
        self.assertEqual(u["cards"].calls[0][3], "seat")

    def test_a_read_the_host_failed_twice_goes_to_planning_never_back_to_the_author(self):
        # owner, 10-12: "If it fails again, the PR is held with that reason recorded and no fix asked of the author"
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        held = V(T.INCOMPLETE, tokens=0, host=True, cap=True, why="the read hit its own cap twice at abc")
        u, _ = self.land(planner=Planner(paid=True), reviewer=Reviewer(held))
        j = self.job()
        self.assertEqual((j.state, j.reads_used), (T.QUERY, 0))
        self.assertIn("own cap twice", j.extra["why"])
        self.assertIsNone(J.read_json(J.handed_path("demo", 1)))   # no handback written
        self.assertEqual(u["cards"].calls[0][3], "planning")
        # …while a plain INCOMPLETE (the first failure) is still only held for the retry
        self.pr(2, {"b/y": "n\n"})
        J.submit("demo", 2)
        self.land(planner=Planner(paid=True), reviewer=Reviewer(V(T.INCOMPLETE, tokens=0, why="no answer")))
        self.assertEqual(self.job(2).state, T.HELD)

    def test_a_silent_read_is_held_as_a_retry_not_a_wall(self):
        # a reader that handed back naming no blocker (#919) is retried, and the hold says so, not "a budget wall"
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        quiet = V(T.INCOMPLETE, tokens=0, silent=True, why="codex: no answer: rc=0")
        self.land(planner=Planner(paid=True), reviewer=Reviewer(quiet))
        j = self.job()
        self.assertEqual(j.state, T.HELD)
        self.assertIn("handed back without naming a blocker", j.extra["why"])
        self.assertNotIn("budget wall", j.extra["why"])

    def test_a_ratchet_pass_lands_and_logs_both_sets(self):
        # owner, 10-13: "a red check on main stops holding PRs that don't make it worse"
        class Ratchet(Runner):
            def run_plan(self, *a, **kw):
                out = super().run_plan(*a, **kw)
                out["a"].sets = {"pr": ["FAIL x"], "main": ["FAIL x", "FAIL y"]}
                return out
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.land(runner=Ratchet(notes={"a": "ratchet: no new reds, a is red on the base too"}))
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)
        self.assertIn("gate=a ok=ratchet", self.log())
        self.assertRegex(self.log(), r"ratchet demo#1 check=a head=\w+ base=\w+ pr_reds=FAIL x main_reds=FAIL x;FAIL y")
        self.assertNotIn("ok=yes", self.log().split("gate=a ")[1].split("\n")[0])

    def test_a_main_red_hold_keeps_when_it_first_held_on_that_check(self):
        lane = mock.Mock()
        job = T.Job(repo="demo", pr=1, head="h" * 40, base_sha="b" * 40, extra={})
        blocked = {"a": L.RUN.Outcome("a", L.RUN.BLOCKED, "blocked-by-main:a", [],
                                      {"pr": ["FAIL n"], "main": ["FAIL m"]})}
        f = mock.Mock(tree="t" * 40)
        f.name = "a"
        L.Lane.took(lane, job, f, blocked)
        first = job.extra["main_red"]
        self.assertEqual((first["check"], first["fails"]), ("a", ["FAIL m"]))
        job.extra["main_red"]["since"] = "2026-10-13T00:00:00Z"
        L.Lane.took(lane, job, f, blocked)
        self.assertEqual(job.extra["main_red"]["since"], "2026-10-13T00:00:00Z")   # held again: the same hour runs on
        f.name = "b"
        L.Lane.took(lane, job, f, {"b": L.RUN.Outcome("b", L.RUN.BLOCKED, "blocked-by-main:b")})
        self.assertNotEqual(job.extra["main_red"]["since"], "2026-10-13T00:00:00Z")   # another check starts its own

    def test_a_flaky_check_passes_and_is_logged_by_name(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.land(runner=Runner(notes={"a": "flaky: red, then green on the same tree"}))
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)
        self.assertIn("flake demo#1 check=a", self.log())
        # a check that passed the first time logs no flake
        self.pr(2, {"a/x": "m\n"})
        J.submit("demo", 2)
        self.land(runner=Runner())
        self.assertNotIn("flake demo#2", self.log())

    def test_unrunnable_holds_then_queries(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        for n in range(3):
            j = self.job()
            if j:
                j.extra["not_before"] = E.stamp(time.time() - 1)
                J.save(j)
            self.land(runner=Runner(status={"a": T.UNRUNNABLE}))
        j = self.job()
        self.assertEqual((j.state, j.extra["attempts"]), (T.QUERY, 3))
        self.assertIn("gate=a ok=no", self.log())

    def test_unrunnable_query_says_why(self):
        """The query carries the last try's reason (#1087: a full /tmp reached planning as 'could not run 3 times')."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        for n in range(3):
            j = self.job()
            if j:
                j.extra["not_before"] = E.stamp(time.time() - 1)
                J.save(j)
            self.land(runner=Runner(status={"a": T.UNRUNNABLE}, notes={"a": "No space left on device"}))
        j = self.job()
        self.assertEqual(j.state, T.QUERY)
        self.assertEqual(j.extra["why"], "check a could not run 3 times: No space left on device — next: clear what "
                                         "stops the check on the box (the reason above), then queue the PR again")

    # a gate's output line: an ANSI colour, broadcasts, mrkdwn, a handle split by a zero-width space, a bidi
    # override, a newline, and far more than fits
    RAW_NOTE = ("bwrap: \x1b[31m<!channel> *ping* `x` @ada\u200b.byron @channel @here @everyone\u202e\x1b[0m\n"
                "fake: line " + "y" * 400)
    CLEAN_NOTE = "bwrap: !channel ping x \ufe6bada.byron \ufe6bchannel \ufe6bhere \ufe6beveryone fake: line y"

    def assert_clean(self, why, prefix):
        """`prefix` is a regex for the lander's own words before the quoted line."""
        self.assertRegex(why, "^" + prefix + re.escape(self.CLEAN_NOTE))
        for c in ("\x1b", "\n", "<", ">", "`", "*", "@", "[31m", "[0m", "\u200b", "\u202e"):
            self.assertNotIn(c, why)
        self.assertTrue(why.endswith("…"), why)

    def test_unrunnable_note_is_quoted_clean(self):
        """A gate's own output line reaches the note without control or markup characters and cut short."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.land(runner=Runner(status={"a": T.UNRUNNABLE}, notes={"a": self.RAW_NOTE}))
        self.assert_clean(self.job().extra.get("why") or "", re.escape("check a could not run (try 1 of 3): "))
        self.assertEqual(J.quoted("No space left on device"), "No space left on device")   # a plain reason as it is

    def test_unrunnable_query_quotes_clean(self):
        """The third try's query, which goes to Slack as the stopped card, carries the same clean line."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        for n in range(3):
            j = self.job()
            if j:
                j.extra["not_before"] = E.stamp(time.time() - 1)
                J.save(j)
            self.land(runner=Runner(status={"a": T.UNRUNNABLE}, notes={"a": self.RAW_NOTE}))
        j = self.job()
        self.assertEqual((j.state, j.extra["attempts"]), (T.QUERY, 3))
        why = j.extra.get("why") or ""
        self.assertTrue(why.endswith(L.NEXT_UNRUNNABLE), why)
        self.assert_clean(why[:-len(L.NEXT_UNRUNNABLE)], re.escape("check a could not run 3 times: "))

    def test_failed_handback_quotes_clean(self):
        """A failed check's handback, kept in the handed record and sent as the stopped card, carries the clean line."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        u, _ = self.land(runner=Runner(status={"a": T.FAILED}, notes={"a": self.RAW_NOTE}))
        self.assertIsNone(self.job())
        prefix = r"check a failed on the merge with \S+ \([0-9a-f]+\): "
        self.assert_clean(J.read_json(J.handed_path("demo", 1))["why"], prefix)
        self.assert_clean(u["cards"].calls[0][2], prefix)

    def test_a_red_on_a_main_that_moved_is_gated_again_not_handed_back(self):
        """#1468, 10-20: queued, then main took a fix (#1471) while its gate ran on the old main, which failed it.
        The red is gated again on the main it would merge into, which passes, so it lands, never handed back."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        runner = Runner(status={"a": T.FAILED})

        def hook(name, count):
            if count == 1:   # main takes the fix mid-gate; this run still fails on the old main
                self.push("main", {"b/fix": "10\n"}, fresh=False)
            else:
                runner.status.clear()
        runner.hook = hook
        self.land(runner=runner)
        self.assertFalse(os.path.exists(J.handed_path("demo", 1)))
        self.assertEqual(len(runner.calls), 2)
        self.assertNotEqual(runner.calls[0][1], runner.calls[1][1])   # the second gate's tree is the new main's
        self.assertRegex(self.log(), r"gate=a ok=no secs=\d+\n\S+\tstage demo#1 queued\n")   # back, not handed
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)
        self.assertEqual(self.git(self.tmp, "--git-dir", self.origin, "show", "main:b/fix"), "10")

    def test_a_red_again_on_a_newer_main_is_handed_back_after_one_regate(self):
        """Opus read of #1767: main moves under every gate, so a PR that is really red is gated again once at its
        head, then handed back naming both mains, never re-queued without end."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        runner = Runner(status={"a": T.FAILED})
        runner.hook = lambda name, count: self.push("main", {f"b/m{count}": "x\n"}, fresh=False)
        self.land(runner=runner)
        self.assertEqual(len(runner.calls), 2)
        self.assertTrue(os.path.exists(J.handed_path("demo", 1)))
        mains = re.search(r"red on (\w{12}) and again on (\w{12})", J.read_json(J.handed_path("demo", 1))["why"])
        self.assertNotEqual(mains[1], mains[2])


class HeldRereads(Fixture):
    """A held job re-reads the PR's state and head when it is looked at again (2026-09-30: a PR sat closed for days,
    held <-> checking at a head it no longer had). Each case holds its own job from checking, then releases it."""

    def held(self):
        head = self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.land(planner=Planner(paid=True), reviewer=Reviewer(V(T.INCOMPLETE, tokens=0)))
        j = self.job()
        self.assertEqual((j.state, j.extra["held_from"], j.head), (T.HELD, T.CHECKING, head))
        j.extra["not_before"] = E.stamp(time.time() - 1)
        J.save(j)
        return head

    def after_hold(self, j):
        states = [h["state"] for h in j.history]
        return states[len(states) - states[::-1].index(T.HELD):]

    def test_unchanged_goes_back_to_checking(self):
        self.held()
        rv = Reviewer(V(T.LAND))
        self.land(planner=Planner(paid=True), reviewer=rv)
        j = self.job()
        self.assertEqual(j.state, T.DEPLOY_PENDING)
        self.assertEqual(self.after_hold(j)[0], T.CHECKING)       # no fresh start: its results are kept
        self.assertEqual([c[0] for c in rv.calls], ["review"])

    def test_closed_while_held_leaves_with_one_line(self):
        self.held()
        self.set_box(prs={"1": {**self.box()["prs"]["1"], "state": "CLOSED", "headRefOid": "e" * 40}})
        rv = Reviewer(V(T.LAND))
        u, _ = self.land(planner=Planner(paid=True), reviewer=rv)
        j = self.job()
        self.assertEqual(j.state, T.DONE)
        self.assertEqual(self.after_hold(j), [T.QUEUED, T.DONE])
        self.assertIn("the PR is closed", j.history[-2]["why"])
        self.assertEqual(self.log().count("\tdone demo#1 rc=1"), 1)
        self.assertEqual((rv.calls, u["deploy"].calls), ([], []))
        self.assertFalse(os.path.exists(J.job_path("demo", 1)))   # off the queue, at rest

    def test_merged_while_held_is_merged_before(self):
        head = self.held()
        self.set_box(prs={"1": {**self.box()["prs"]["1"], "state": "MERGED", "headRefOid": head}})
        rv = Reviewer(V(T.LAND))
        self.land(planner=Planner(paid=True), reviewer=rv)
        j = self.job()
        self.assertEqual(self.after_hold(j)[:2], [T.QUEUED, T.MERGED])
        self.assertEqual(rv.calls, [])

    def test_a_new_head_is_a_fresh_job(self):
        old = self.held()
        new = self.push("track/row-1", {"a/y": "m\n"}, fresh=False)
        pl, rv = Planner(paid=True), Reviewer(V(T.LAND))
        self.land(planner=pl, reviewer=rv)
        j = self.job()
        self.assertNotEqual(old, new)
        self.assertEqual((j.state, j.head), (T.DEPLOY_PENDING, new))
        self.assertEqual(self.after_hold(j)[:2], [T.QUEUED, T.PLANNED])
        self.assertIn(f"the head moved to {new[:12]}", [h for h in j.history if h["state"] == T.QUEUED][-1]["why"])

    def test_gh_unreadable_stays_held(self):
        self.held()
        self.set_box(down=True)
        rv = Reviewer(V(T.LAND))
        self.land(planner=Planner(paid=True), reviewer=rv)
        j = self.job()
        self.assertEqual((j.state, j.extra["held_from"]), (T.HELD, T.CHECKING))
        self.assertTrue(J.not_before_left(j) > 0)
        self.assertEqual(rv.calls, [])

    def pr_views(self):
        return [c for c in self.box().get("calls", []) if c[:3] == ["gh", "pr", "view"]]

    def test_backoff_stays_held_without_asking_gh(self):
        self.held()
        J.write_atomic(GH.backoff_path(), {"until": time.time() + 600, "fails": 1})
        before = len(self.pr_views())
        rv = Reviewer(V(T.LAND))
        self.land(planner=Planner(paid=True), reviewer=rv)
        j = self.job()
        self.assertEqual((j.state, j.extra["held_from"]), (T.HELD, T.CHECKING))
        self.assertEqual(len(self.pr_views()), before)     # gh is not called during a backoff
        self.assertEqual(rv.calls, [])

    def test_a_spent_rest_quota_backs_off_though_stdout_is_json(self):
        # gh api prints GitHub's error JSON on stdout and the reason on stderr: the reason still backs off,
        # while a JSON body that merely says "timeout" (a PR title) with nothing on stderr does not
        with contextlib.suppress(FileNotFoundError):
            os.unlink(GH.backoff_path())
        GH._note(1, '{"message":"timeout in the title"}', "")
        self.assertFalse(os.path.exists(GH.backoff_path()))
        GH._note(1, '{"message":"API rate limit exceeded for user ID 1."}', "gh: API rate limit exceeded for user ID 1. (HTTP 403)")
        self.assertGreater(GH.backoff(), 0)
        os.unlink(GH.backoff_path())

    def test_pending_merge_attempt_skips_the_reread(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.set_box(merge_then_timeout=True)
        self.land()
        j = self.job()
        self.assertEqual((j.state, j.extra["held_from"]), (T.HELD, T.MERGEABLE))
        self.assertIn("merge_attempt", j.extra)
        self.set_box(down=False)
        j.extra["not_before"] = E.stamp(time.time() - 1)
        J.save(j)
        os.unlink(GH.backoff_path())
        real, seen = GH.pr_facts, []

        def rec(root, pr, fields, *a, **kw):
            seen.append(fields)
            return real(root, pr, fields, *a, **kw)
        with mock.patch.object(GH, "pr_facts", rec):
            u, _ = self.land()
        j = self.job()
        self.assertNotIn("state,headRefOid,baseRefName", seen)   # mergeable() proves the attempt, not the re-read
        self.assertEqual(self.after_hold(j)[0], T.MERGEABLE)
        self.assertEqual(j.state, T.DEPLOY_PENDING)
        self.assertEqual(len(self.box()["merges"]), 1)

    def test_a_retargeted_base_requeues(self):
        self.held()
        self.push("release", {"r/z": "r\n"})
        self.set_box(prs={"1": {**self.box()["prs"]["1"], "baseRefName": "release"}})
        self.land(planner=Planner(paid=True), reviewer=Reviewer(V(T.LAND)))
        j = self.job()
        self.assertEqual(self.after_hold(j)[:2], [T.QUEUED, T.PLANNED])
        self.assertIn("the base moved from main to release",
                      [h for h in j.history if h["state"] == T.QUEUED][-1]["why"])
        self.assertEqual((j.extra["base_ref"], j.base_sha), ("release", self.origin_rev("release")))


class Door(Fixture):
    def setUp(self):
        super().setUp()
        self.set_box(config={"CC_PROTECTED_PATHS_demo": "a/", "SLACK_OWNER_ID": "UOWNER"})

    def test_non_owner_refused_owner_pins(self):
        head = self.pr(1, {"a/x": "n\n"})
        cards = Rec()
        with mock.patch.object(L, "load_units", lambda: {"cards": cards}):
            rc, _, err = self.queue("demo", "1", "--approved-by", "USOMEONE")
        self.assertEqual(rc, 1)
        self.assertIn("refused demo#1 protected:a/x", self.log())
        self.assertEqual(cards.calls[0][0::3], ("stopped", "door"))
        self.assertEqual(J.requests(), [])
        rc, _, err = self.queue("demo", "1", "--approved-by", "UOWNER", "--no-start")
        self.assertEqual(rc, 0, err)
        self.assertEqual(J.approval("demo", 1)["approved_head"], head)
        self.assertNotIn("approved_head", J.requests()[0][1])        # the request carries no approval
        u, _ = self.land()
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)
        # a PR under no protected path queues on anyone's say
        self.pr(2, {"b/y": "n\n"})
        self.assertEqual(self.queue("demo", "2", "--no-start")[0], 0)

    def test_a_forged_request_lands_nothing_without_a_real_read(self):
        """Anyone may write the inbox (review of #771): an approval or a verdict in a request is dropped, so a forged
        owner approval stops at the door, and a forged LAND buys the read it tried to skip."""
        head = self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1, approved_by="UOWNER", approved_head=head, reads_used=0,
                 verdict={"verdict": "LAND", "digest": "d" * 64, "blocking": [], "advisory": []})
        u, _ = self.land()
        j = self.job()
        self.assertEqual(j.state, T.QUERY)
        self.assertIn("no 👍 of the owner's queued it", j.extra["why"])
        self.assertEqual(self.box().get("merges", []), [])
        self.assertNotIn("verdict", j.extra)
        self.pr(2, {"b/y": "n\n"})                    # no protected path: the forged LAND must not skip the read
        J.submit("demo", 2, verdict={"verdict": "LAND", "digest": "d" * 64, "blocking": [], "advisory": []})
        rv = Reviewer(V(T.HANDBACK_VERDICT, blocking=["a real read"]))
        self.land(planner=Planner(paid=True), reviewer=rv)
        self.assertEqual([c[0] for c in rv.calls], ["review"])
        self.assertEqual(self.box().get("merges", []), [])

    def test_files_gh_cannot_list_queue_and_the_door_asks_at_the_head(self):
        """A spent REST hour refused #1890 with a 🔐 card nothing needed, and nothing queued it after the reset
        (2026-10-23): it queues with no card. Perms' read of #1908: whatever GitHub's file list answers (an error, a
        rate limit, a 304 for a cached body, an empty or a partial list), the lane's door still stops a protected
        path from git's own list, and nothing merges."""
        answers = {"error": (1, "", "gh: Server Error (HTTP 502)"),
                   "rate limit": (1, "", "gh: API rate limit exceeded for user ID 1. (HTTP 403)"),
                   "cached": (1, "HTTP/2.0 304 Not Modified\n\n", ""),
                   "empty": (0, "", ""), "partial": (0, "b/y\n", "")}
        for name, said in answers.items():
            with self.subTest(name):
                self.doCleanups()   # each answer on a fixture of its own
                self.setUp()
                real, cards = GH.gh, Rec()
                self.pr(1, {"a/x": "n\n", "b/y": "n\n"})
                with mock.patch.object(L, "load_units", lambda: {"cards": cards}), \
                        mock.patch.object(GH, "gh", lambda argv, *a, **k:
                                          said if "pulls/1/files?" in " ".join(argv) else real(argv, *a, **k)):
                    rc, out, err = self.queue("demo", "1", "--no-start")
                    self.land()
                self.assertEqual(rc, 0, err)
                self.assertEqual(L.UNLISTED in out, said[0] != 0)
                self.assertEqual(cards.calls, [])
                self.assertNotIn("refused", self.log())
                self.assertEqual(self.job().state, T.QUERY)
                self.assertIn("no 👍 of the owner's queued it", self.job().extra["why"])
                self.assertEqual(self.box().get("merges", []), [])

    def test_unreadable_config_fails_closed(self):
        self.set_box(config={"SLACK_OWNER_ID": "UOWNER", "CC_PROTECTED_PATHS_demo": False})
        self.pr(1, {"b/y": "n\n"})
        self.assertEqual(self.queue("demo", "1")[0], 1)
        self.assertIn("refused demo#1 protected:?", self.log())

    def test_carry_when_protected_files_identical_reask_when_not(self):
        h1 = self.pr(1, {"a/x": "n\n"})
        self.queue("demo", "1", "--approved-by", "UOWNER", "--no-start")
        h2 = self.push("track/row-1", {"b/y": "later\n"}, fresh=False)
        self.land()
        self.assertIn(f"approval demo#1 carried {h1[:12]} → {h2[:12]}", self.log())
        argv = self.box()["merges"][0]
        self.assertEqual(argv[argv.index("--match-head-commit") + 1], h2)
        self.pr(2, {"a/x": "second\n"})
        self.queue("demo", "2", "--approved-by", "UOWNER", "--no-start")
        self.push("track/row-2", {"a/x": "changed under the rule\n"}, fresh=False)
        u, _ = self.land()
        self.assertEqual(self.job(2).state, T.QUERY)
        self.assertEqual(u["cards"].calls[0][3], "owner")
        self.assertIn("has not 👍'd", self.job(2).extra["why"])


class QueueTask(Fixture):
    RECEIPT = {"task_id": "t1", "errors": [], "pending": {}, "pr_url": "https://github.com/o/demo/pull/1",
               "committed_sha": "c" * 40, "card": {"chat": "C9", "ts": "1.2"}}

    def task(self, lands, **rec):
        self.set_box(receipt={**self.RECEIPT, **rec}, lands=lands)
        o, e = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
            rc = L.cmd_queue(["--task", "demo", "row-1"])
        return rc, json.loads(o.getvalue().strip().splitlines()[-1]), e.getvalue()

    def test_receipt_per_grant(self):
        self.pr(1, {"docs/r.md": "n\n"})
        rc, rec, _ = self.task(0)
        self.assertEqual((rc, rec["landing"]["status"]), (0, "queued"))
        self.assertEqual(J.requests()[0][1]["who"], "cc done")
        self.assertEqual(J.requests()[0][1]["chat"], "C9")
        rc, rec, _ = self.task(1)
        self.assertEqual((rc, rec["landing"]["status"]), (0, "approval"))
        rc, rec, _ = self.task(2)
        self.assertEqual((rc, rec["landing"]["status"]), (2, "refused"))
        rc, rec, _ = self.task(0, pr_url="https://example.invalid/not-a-pr")
        self.assertEqual((rc, rec["landing"]["status"]), (1, "failed"))
        rc, rec, _ = self.task(0, pr_url="", pending={"docs": 1})
        self.assertEqual((rc, rec["landing"]["status"]), (0, "none"))
        self.assertIn("delivery-pending demo/row-1 pr=- projections=docs", self.log())
        self.assertEqual(len(J.requests()), 1)                     # only the grant-0 case queued

    def test_bad_receipt(self):
        self.set_box(receipt={"nope": 1}, lands=0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(L.cmd_queue(["--task", "demo", "row-1"]), 1)


class Board(Fixture):
    def board_file(self, tracks):
        with open(f"{os.environ['CC_BOARDS']}/demo.json", "w") as f:
            json.dump({"tracks": tracks}, f)

    def rows(self):
        return J.board("demo")["tracks"]

    def job(self, body=""):
        return T.Job(repo="demo", pr=7, extra={"branch": "track/own", "title": "t", "body": body})

    def test_own_row_merged_and_closes(self):
        self.board_file({"own": {"status": "review"}, "r-sub": {"status": "queued", "agent": "@3:99"},
                         "r-held": {"status": "queued", "held": "a person"}, "r-live": {"status": "running"},
                         "r-done": {"status": "done"}})
        line = L.BoardRules().close(self.job("Closes r-sub, r-held and r-live, r-done and no-such-row. Closes prose"))
        r = self.rows()
        self.assertEqual(r["own"]["status"], "merged")
        self.assertEqual((r["r-sub"]["status"], r["r-sub"]["agent"]), ("done", ""))
        self.assertEqual((r["r-held"]["status"], r["r-live"]["status"]), ("queued", "running"))
        self.assertIn("closes r-sub", line)
        self.assertIn("left open: r-held, r-live", line)
        self.assertIn("no row on the board: no-such-row", line)
        self.assertNotIn("prose", line)

    def test_cloud_pr_closes_its_row_merged(self):
        self.board_file({"row-a": {"status": "review", "agent": "x"}, "row-b": {"status": "queued"}})
        j = self.job("Fixes it.\n\nCloses row-a and row-b")
        j.extra["branch"] = "cloud/fix-it-x7"
        line = L.BoardRules().close(j)
        r = self.rows()
        self.assertEqual((r["row-a"]["status"], r["row-b"]["status"]), ("merged", "done"))
        self.assertIn("demo/row-a -> merged", line)

    def test_cloud_pr_skips_a_held_row_named_first(self):
        self.board_file({"row-h": {"status": "queued", "held": "someone"}, "row-l": {"status": "running"},
                         "row-a": {"status": "review", "agent": "x"}})
        j = self.job("Closes row-h, row-l and row-a")
        j.extra["branch"] = "cloud/fix-it-x7"
        line = L.BoardRules().close(j)
        r = self.rows()
        self.assertEqual([r[n]["status"] for n in ("row-h", "row-l", "row-a")], ["queued", "running", "merged"])
        self.assertIn("demo/row-a -> merged", line)
        self.assertIn("left open: row-h, row-l", line)

    def test_cloud_pr_skips_a_row_carrying_another_pr(self):
        self.board_file({"row-x": {"status": "review", "agent": "x", "pr": "42"},
                         "row-a": {"status": "review", "agent": "y"}})
        j = self.job("Closes row-x and row-a")
        j.extra["branch"] = "cloud/fix-it-x7"
        line = L.BoardRules().close(j)
        r = self.rows()
        self.assertEqual((r["row-x"]["status"], r["row-a"]["status"]), ("done", "merged"))
        self.assertIn("demo/row-a -> merged", line)

    def test_other_branch_no_row_carries_falls_through_to_closes(self):
        self.board_file({"row-a": {"status": "queued"}})
        j = self.job("Closes row-a")
        j.extra["branch"] = "fix-it"
        self.assertEqual(L.BoardRules().find_track("demo", j), "")
        self.assertIn("demo/row-a -> merged", L.BoardRules().close(j))

    def test_orch_held_row_gets_a_note_only(self):
        self.board_file({"own": {"status": "review", "agent": "@7:1"}})
        self.set_box(windows=["@7\tdemo@orch1"])
        line = L.BoardRules().close(self.job())
        self.assertEqual(self.rows()["own"]["status"], "review")
        self.assertIn("demo@orch1", self.rows()["own"]["notes"][0])
        self.assertIn("left open", line)

    def test_found_by_pr_url_and_unknown_and_symlink(self):
        self.board_file({"x": {"pr": "https://github.com/o/demo/pull/7"}})
        j = self.job()
        j.extra["branch"] = "other"
        L.BoardRules().close(j)
        self.assertEqual(self.rows()["x"]["status"], "merged")
        j.pr = 8
        self.assertIn("no row", L.BoardRules().close(j))
        real = f"{self.tmp}/elsewhere.json"
        os.replace(f"{os.environ['CC_BOARDS']}/demo.json", real)
        os.symlink(real, f"{os.environ['CC_BOARDS']}/demo.json")
        self.assertEqual(J.board("demo"), {})
        self.assertEqual(L.closes_rows("Closes a-1 and b-2, c-3"), ["a-1", "b-2", "c-3"])


class Events(Fixture):
    def test_lines_and_times(self):
        E.log("queued", "demo", 1, who="a\tb", chat=None)
        E.stage("demo", 1, "lane")
        E.stage("demo", 1, "gate", gate="a", ok="yes", secs=12)
        E.stage("demo", 1, "merged", sha="abc")
        E.log("done", "demo", 1, rc=0)
        E.log("refused", "demo", 2, "protected:a/x")
        lines = self.log().splitlines()
        self.assertEqual(lines[0].split("\t", 1)[1], "queued demo#1 who=a b")
        for ln in lines[:5]:
            self.assertTrue(E.LOG_EVENT_RE.match(ln), ln)
        self.assertTrue(lines[5].endswith("\trefused demo#2 protected:a/x"))
        got = E.lead_times(lines)
        self.assertEqual((len(got["first"]), got["gates"]), (1, {"a": [12]}))
        self.assertTrue(set(E.KINDS) >= {"queued", "stage", "done", "handed", "handed-pushed", "handed-end",
                                          "notify", "recorded", "approval", "delivery-pending"})
        o = io.StringIO()
        with contextlib.redirect_stdout(o):
            self.assertEqual(E.cmd_times([]), 0)
        self.assertIn("merged in the last 7 days — 1", o.getvalue())

    def test_a_real_landing_is_timed(self):
        self.pr(1, {"a/x": "n\n"})
        self.queue("demo", "1", "--no-start")
        self.land()
        got = E.lead_times(self.log().splitlines())
        self.assertEqual((len(got["first"]), len(got["lane"]), list(got["gates"])), (1, 1, ["a"]))
        self.assertEqual(E.pctl([1, 2, 3, 4], 50), 2)
        self.assertEqual(E.span_words(4 * 3600 + 5 * 60), "4h05m")


class Tick(Fixture):
    def test_handback_then_tick_requeues_on_push_and_ends_on_expiry(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1, chat="C1", ts="1.1")
        u, _ = self.land(runner=Runner(status={"a": T.FAILED}))
        self.assertIsNone(self.job())
        w = J.read_json(J.handed_path("demo", 1))
        self.assertEqual((w["branch"], w["chat"]), ("track/row-1", "C1"))
        self.assertGreater(E.epoch_of(w["until"]), time.time() + 6 * 86400)
        self.assertIn("handed demo#1", self.log())
        self.assertIn("failed", u["cards"].calls[0][2])
        units = self.units()
        with mock.patch.object(L, "load_units", lambda: units):
            self.assertEqual(TK.sweep_handed(), [])                  # no push: nothing
            self.push("track/row-1", {"a/x": "fixed\n"}, fresh=False)
            TK.sweep_handed()
        self.assertFalse(os.path.exists(J.handed_path("demo", 1)))
        req = J.requests("demo")[0][1]
        self.assertEqual((req["who"], req["chat"]), ("handback push", "C1"))
        self.assertIn("handed-pushed demo#1", self.log())
        J.write_atomic(J.handed_path("demo", 2), {"repo": "demo", "pr": 2, "head": "x", "branch": "b",
                                                  "until": E.stamp(time.time() - 5)})
        TK.sweep_handed()
        self.assertFalse(os.path.exists(J.handed_path("demo", 2)))
        self.assertIn("handed-end demo#2", self.log())

    def test_tick_runs_lanes_and_backoff_skips(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        units = self.units()
        with mock.patch.object(L, "load_units", lambda: units), contextlib.redirect_stdout(io.StringIO()):
            self.set_box(down=True)
            GH.pr_facts(self.root, 1, "state")
            self.assertGreater(GH.backoff(), 0)
            o = io.StringIO()
            with contextlib.redirect_stdout(o):
                TK.cmd_tick([])
            self.assertIn("backoff", o.getvalue())
            self.assertEqual(len(J.requests("demo")), 1)             # nothing ran
            self.set_box(down=False)
            GH.pr_facts(self.root, 1, "state")
            self.assertEqual(GH.backoff(), 0)
            TK.cmd_tick([])
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)

    def test_rearm_arms_one_unit_per_repo(self):
        os.makedirs(J.repo_root("other"))             # tick skips a repo with no checkout
        for repo, pr in (("demo", 1), ("demo", 2), ("other", 3)):
            J.save(T.Job(repo=repo, pr=pr, state=T.HELD, extra={"not_before": E.stamp(time.time() + 300),
                                                                "queued_at": E.stamp()}))
        J.save(T.Job(repo="calm", pr=4, state=T.DONE))
        units = self.units()
        with mock.patch.object(L, "load_units", lambda: units), contextlib.redirect_stdout(io.StringIO()):
            TK.cmd_tick(["--rearm"])
            arms = [c for c in self.box()["calls"] if c[0] == "systemd-run"]
            unstamped = sorted(re.sub(r"-\d+$", "", c[3]) for c in arms)   # a stamp per arming (tick.rearm)
            self.assertEqual(unstamped, ["--unit=lander-tick-demo", "--unit=lander-tick-other"])
            self.assertTrue(all(c[-3:] == ["--repo", re.sub(r"-\d+$", "", c[3].split("lander-tick-")[1]), "--rearm"]
                                for c in arms))
            soon = int(time.time()) + 100   # a timer named for when it fires, before demo's 300 s
            self.set_box(calls=[], timers=f"Sun 2026-09-27 lander-tick-demo-{soon}.timer "
                                          f"lander-tick-demo-{soon}.service")
            TK.cmd_tick(["--rearm"])
        arms = [c for c in self.box()["calls"] if c[0] == "systemd-run"]
        self.assertEqual([re.sub(r"-\d+$", "", c[3]) for c in arms], ["--unit=lander-tick-other"])

    def test_a_wall_hold_is_read_again_when_its_time_passes_with_no_hand_queue(self):
        """10-22: the lane held six hive-lite PRs on a review usage wall "asked again at 05:10:19Z", repair pushes gave
        three of them new heads during the hold, and nothing read them again for 4 h until a seat queued them by hand.
        The lane that holds must arm the tick its hold waits for, a later timer is no wait for an earlier hold, and a
        hold that runs out while a lane runs is followed up."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        until = E.stamp(time.time() + 900)
        wall = V(T.INCOMPLETE, tokens=0, until=until, why="Fable: resets 1am NY")
        rv = Reviewer(wall, V(T.LAND))
        units = self.units(planner=Planner(paid=True), reviewer=rv)
        arms = lambda: [c for c in self.box()["calls"] if c[0] == "systemd-run"]   # noqa: E731
        with mock.patch.object(L, "load_units", lambda: units), contextlib.redirect_stdout(io.StringIO()):
            L.cmd_lane(["demo"])   # a lane no tick ran: a lane switch's, or `tick --detach`'s
            j = self.job()
            self.assertEqual((j.state, j.extra["deferred"], j.extra["not_before"]), (T.HELD, True, until))
            self.assertEqual(len(arms()), 1)                              # the lane armed its own wake-up
            fires = int(arms()[0][3].rsplit("-", 1)[1])
            self.assertTrue(0 <= fires - E.epoch_of(until) <= 3)          # …named for when it fires, just past the until
            later = f"lander-tick-demo-{fires + 3600}.timer"
            self.set_box(calls=[], timers=later)
            TK.rearm(["demo"])
            self.assertEqual(len(arms()), 1)                              # a timer firing later does not stand for it
            self.set_box(calls=[], timers=arms()[0][3].split("=")[1] + ".timer")
            TK.rearm(["demo"])
            self.assertEqual(arms(), [])                                  # its own timer does
            new = self.push("track/row-1", {"a/x": "m\n"}, fresh=False)   # a repair push during the hold
            j.extra["not_before"] = E.stamp(time.time() - 1)              # the until passes
            J.save(j)
            with mock.patch.object(J, "running", lambda r: 4242):
                self.assertEqual(TK.waits("demo"), [TK.TICK_SECS])        # met by a running lane: followed up
            TK.cmd_tick(["--repo", "demo", "--rearm"])                   # the timer's tick
        j = self.job()
        self.assertEqual((j.state, j.head), (T.DEPLOY_PENDING, new))      # read again at its new head
        self.assertEqual([c[0] for c in rv.calls], ["review", "review"])
        self.assertEqual(J.requests("demo"), [])                          # nobody queued it


class Branches(Fixture):
    """The smaller branches: a refused merge, a member's charge and cap, deploy retries, detached starts."""

    def test_refused_merge_holds_then_queries(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.set_box(merge_fail="Pull request is not mergeable: the base branch policy prohibits the merge")
        for _ in range(3):
            j = self.job()
            if j:
                j.extra["not_before"] = E.stamp(time.time() - 1)
                J.save(j)
            self.land()
        j = self.job()
        self.assertEqual((j.state, j.extra["attempts"]), (T.QUERY, 3))
        self.assertTrue(j.extra["why"].startswith("the merge was refused 3 times: "), j.extra["why"])
        self.assertTrue(j.extra["why"].endswith(L.NEXT_REFUSED), j.extra["why"])   # the reason and the next step
        self.assertNotIn("merge_attempt", j.extra)
        self.assertNotIn("updates", self.box())   # a refusal that is not BEHIND never updates the branch
        ok, text = GH.merge(self.root, 1, "x" * 40, "t")
        self.assertFalse(ok)
        self.assertFalse(any("auto" in x for m in self.box()["rest_merges"] for x in m))   # REST arms no auto-merge

    def unhold(self):
        j = self.job()
        j.extra["not_before"] = E.stamp(time.time() - 1)
        J.save(j)

    def test_a_behind_refusal_updates_the_branch_once_tells_the_seat_and_lands_at_the_new_head(self):
        """Row note (10-13): "on a strict BEHIND refusal, update the branch, wait for checks at the new head and retry
        once, and say so to the repo's seat"."""
        old = self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.enterContext(mock.patch.object(GH, "slug", lambda root: "o/demo"))   # update-branch names the repo
        self.set_box(behind=True)
        u, _ = self.land()
        j = self.job()
        self.assertEqual((j.state, j.extra["behind_update"]["from"]), (T.HELD, old))
        self.assertEqual(self.box()["updates"], [["repos/o/demo/pulls/1/update-branch", "-f",
                                                  f"expected_head_sha={old}"]])
        said = [c for c in u["cards"].calls if c[0] == "behind"]
        self.assertEqual(len(said), 1)
        self.assertIn(f"behind main, so the lane updated the branch from {old[:12]}", said[0][2])
        self.assertEqual([c for c in u["cards"].calls if c[0] == "stopped"], [])
        new = self.origin_rev("refs/heads/track/row-1")
        self.assertNotEqual(new, old)
        self.unhold()
        for _ in range(3):
            self.land()
        j = self.job()
        self.assertEqual(j.state, T.DEPLOY_PENDING)
        self.assertEqual(j.head, new)   # merged at the updated head, after its checks ran there
        pins = [m[m.index("--match-head-commit") + 1] for m in self.box()["merges"]]
        self.assertEqual(pins, [old, new])
        self.assertEqual(len(self.box()["updates"]), 1)

    def test_behind_again_after_the_one_update_is_a_query_not_another_merge(self):
        """Row note: "don't retry the same refusal"."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.enterContext(mock.patch.object(GH, "slug", lambda root: "o/demo"))   # update-branch names the repo
        self.set_box(behind=True, stay_behind=True)
        self.land()
        self.unhold()
        for _ in range(3):
            self.land()
        j = self.job()
        self.assertEqual(j.state, T.QUERY)
        self.assertIn("again after the lane updated the branch once", j.extra["why"])
        self.assertEqual((len(self.box()["updates"]), len(self.box()["merges"])), (1, 2))
        self.assertFalse(j.extra.get("attempts"))

    def test_an_update_github_refuses_is_a_query(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.enterContext(mock.patch.object(GH, "slug", lambda root: "o/demo"))   # update-branch names the repo
        self.set_box(behind=True, update_fail="gh: Resource not accessible by integration (HTTP 403)")
        u, _ = self.land()
        j = self.job()
        self.assertEqual(j.state, T.QUERY)
        self.assertIn("updating the branch failed: gh: Resource not accessible", j.extra["why"])
        self.assertNotIn("behind_update", j.extra)
        self.assertEqual([c[3] for c in u["cards"].calls if c[0] == "stopped"], ["planning"])
        self.assertEqual([c for c in u["cards"].calls if c[0] == "behind"], [])

    def test_closed_pr_is_done_and_unknown_check_is_a_query(self):
        self.pr(1, {"a/x": "n\n"}, state="CLOSED", headRefOid="e" * 40)
        J.submit("demo", 1)
        self.land()
        self.assertEqual(self.job().state, T.DONE)
        self.assertIn("done demo#1 rc=1", self.log())
        self.pr(2, {"b/y": "n\n"})
        J.submit("demo", 2)
        self.land(runner=Runner(missing={"b"}))   # the manifest lacks b
        self.assertEqual(self.job(2).state, T.QUERY)
        self.assertIn("lacks: b", self.job(2).extra["why"])

    def test_member_review_is_charged_and_capped(self):
        Members.make_member(self)
        self.set_box(config={"CC_GH_PERSONAL_OWNER": "own", "MEMBER_DAILY_USD": "1.5"})
        self.pr(1, {"a/x": "n\n"})
        J.submit("alice--proj", 1)
        v = V(T.LAND)
        v.extra["usd"] = 1.25
        self.land("alice--proj", planner=Planner(paid=True), reviewer=Reviewer(v))
        self.assertEqual(M.spent("alice"), (1.25, 1.5))
        self.assertEqual(self.job(1, "alice--proj").state, T.DONE)
        self.assertEqual(M.charge("alice", 1.0), (1.25, 1.5))          # over the cap: refused, nothing charged
        M.charge("alice", 0.25)
        self.pr(2, {"b/y": "n\n"})
        J.submit("alice--proj", 2)
        rv = Reviewer(V(T.LAND))
        self.land("alice--proj", planner=Planner(paid=True), reviewer=rv)
        j = self.job(2, "alice--proj")
        self.assertEqual((j.state, rv.calls), (T.HELD, []))
        self.assertIn("review cap", j.extra["why"])

    def test_tick_retries_a_deploy_once_and_starts_detached(self):
        J.save(T.Job(repo="demo", pr=1, state=T.DEPLOY_PENDING, extra={"tip_sha": "d" * 40, "post": {}}))
        units = self.units()
        with mock.patch.object(L, "load_units", lambda: units), contextlib.redirect_stdout(io.StringIO()):
            TK.cmd_tick([])
            TK.cmd_tick([])
        self.assertEqual(units["deploy"].calls, [("request", "demo", "d" * 40, [])])
        self.assertEqual(units["tip"].calls, [("kick", "demo"), ("kick", "demo")])
        self.assertEqual(self.job().extra["post"]["deploy"], "ok")
        started = []
        fake = mock.Mock(side_effect=lambda argv, **kw: started.append((argv, kw)) or mock.Mock(pid=7))
        J.submit("demo", 2)
        with mock.patch.object(TK.subprocess, "Popen", fake), mock.patch.object(TK, "rearm", lambda r: []), \
                mock.patch.object(TK, "tip_and_deploy", lambda r, u: []), \
                mock.patch.object(TK, "sweep_strays", lambda r: []), contextlib.redirect_stdout(io.StringIO()):
            TK.cmd_tick(["--detach"])
        self.assertEqual(started[0][0][-2:], ["lane", "demo"])
        self.assertTrue(started[0][1]["start_new_session"])

    def test_spawn_tick_argv(self):
        started = []
        fake = mock.Mock(side_effect=lambda argv, **kw: started.append((argv, kw)) or mock.Mock(pid=9))
        with mock.patch.object(L.subprocess, "Popen", fake):
            self.assertEqual(REAL_SPAWN_TICK("demo"), (True, "pid 9"))   # the fixture stubs L.spawn_tick
        self.assertEqual(started[0][0][-3:], ["tick", "--repo", "demo"])
        self.assertTrue(started[0][0][2].endswith(os.path.join("lander", "cli.py")))

    def test_spawn_tick_drops_the_reviewer_keys(self):
        # a worker's `CC_CLAUDE=<fake> cc done` must not reach the review the tick runs (security read of #847)
        started = []
        fake = mock.Mock(side_effect=lambda argv, **kw: started.append((argv, kw)) or mock.Mock(pid=9))
        chosen = {"CC_CLAUDE": "/tmp/fake-claude", "CC_CODEX": "/tmp/fake-codex", "CC_CONFIG": "/tmp/own-config",
                  "CC_LAND_REVIEW_MODEL": "haiku", "CC_LAND_REVIEW_BUDGET": "0.01", "CC_LAND_REVIEW_EFFORT": "low",
                  "CC_LAND_REVIEWERS": "none", "CODEX_HOME": "/tmp/own-codex", "CC_LAND_STATE": "/tmp/own-state"}
        with mock.patch.dict(os.environ, dict(chosen, LANG="C.UTF-8", LC_ALL="C.UTF-8")), \
                mock.patch.object(L.subprocess, "Popen", fake):
            self.assertEqual(REAL_SPAWN_TICK("demo"), (True, "pid 9"))
        env = started[0][1]["env"]
        self.assertEqual([k for k in chosen if k in env], [])
        self.assertEqual((env.get("LANG"), env.get("LC_ALL")), ("C.UTF-8", "C.UTF-8"))
        self.assertEqual(env.get("PYTHONDONTWRITEBYTECODE"), "1")

    def test_spawn_tick_gives_the_tick_the_passwd_home_and_none_of_the_queuers_roots(self):
        # `ANTHROPIC_BASE_URL=… cc done` pointed the reviewer at a fake server (#849 Opus read); a HOME or state root of
        # the queuer's moved the job queue, the read count and the brief (#847 delta reads); a PATH of its own picked
        # git, gh and claude (security read of #849); GIT_CONFIG_PARAMETERS named hooks for every git the tick ran
        started = []
        fake = mock.Mock(side_effect=lambda argv, **kw: started.append((argv, kw)) or mock.Mock(pid=9))
        chosen = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9", "ANTHROPIC_AUTH_TOKEN": "x", "HOME": "/tmp/own-home",
                  "PATH": "/tmp/own-bin:/usr/bin", "CC_LANDER_STATE": "/tmp/q", "LANDER_STATE": "/tmp/q",
                  "CC_STATE": "/tmp/s", "CC_DEV": "/tmp/d", "CC_BOARDS": "/tmp/b", "CC_MEMBERS": "/tmp/m",
                  "CC_BIN": "/tmp/bin", "CC_LAND_SCRATCH": "/tmp/t", "GH_CONFIG_DIR": "/tmp/gh",
                  "GIT_CONFIG_PARAMETERS": "'core.hookspath'='/tmp/h'", "HTTPS_PROXY": "http://127.0.0.1:9",
                  "https_proxy": "http://127.0.0.1:9", "SSL_CERT_FILE": "/tmp/ca", "NODE_OPTIONS": "--require /tmp/x",
                  "LD_PRELOAD": "/tmp/x.so", "PYTHONPATH": "/tmp/py"}
        with mock.patch.dict(os.environ, chosen), mock.patch.object(L.subprocess, "Popen", fake), \
                mock.patch("lander.cards.PASSWD_HOME", "/home/owner"), mock.patch.object(L.os, "makedirs"):
            self.assertEqual(REAL_SPAWN_TICK("demo"), (True, "pid 9"))
        env = started[0][1]["env"]
        self.assertEqual([k for k in chosen if k in env and k not in ("HOME", "PATH")], [])
        self.assertEqual((env["HOME"], env["PATH"]),
                         ("/home/owner", "/usr/local/bin:/usr/bin:/bin:/home/owner/bin:/home/owner/.local/bin"))
        self.assertEqual(env.get("PYTHONDONTWRITEBYTECODE"), "1")

    def test_tick_env_is_an_allow_list(self):
        # a filter misses what nobody listed (#862 review reads): XDG_CONFIG_HOME names a git config whose
        # url.insteadOf redirects the fetch and a gh config whose http_unix_socket redirects every gh call, GH_REPO
        # points pr_facts at a decoy PR, and BASH_ENV / ENV run a file of the worker's in every script the tick calls
        hostile = {"XDG_CONFIG_HOME": "/tmp/own-xdg", "GH_REPO": "evil/decoy", "BASH_ENV": "/tmp/x.sh",
                   "ENV": "/tmp/x.sh", "XDG_RUNTIME_DIR": "/tmp/own-run", "LANDER_SYSTEMD_RUN": "/tmp/fake",
                   "SOMETHING_NEW": "1"}
        with mock.patch("lander.cards.PASSWD_HOME", "/home/owner"), mock.patch.object(L.os, "makedirs"):
            env = L.tick_env(dict(hostile, LANG="C.UTF-8", LC_CTYPE="C.UTF-8", USER="owner", HOME="/tmp/h"))
        self.assertEqual([k for k in hostile if k in env and k != "XDG_RUNTIME_DIR"], [])
        self.assertNotEqual(env.get("XDG_RUNTIME_DIR"), "/tmp/own-run")
        self.assertEqual((env["LANG"], env["LC_CTYPE"], env["USER"], env["HOME"]),
                         ("C.UTF-8", "C.UTF-8", "owner", "/home/owner"))

    def test_tick_env_tmpdir_is_the_box_scratch(self):
        # a lane's runs must not fall to /tmp (dispatch's fence masks it), and a caller's TMPDIR never steers them
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        with mock.patch("lander.cards.PASSWD_HOME", home):
            self.assertEqual(L.tick_env({"TMPDIR": "/tmp/own"})["TMPDIR"], os.path.join(home, ".cc", "tmp"))
            self.assertTrue(os.path.isdir(os.path.join(home, ".cc", "tmp")))   # a missing scratch is made, not skipped

    def test_tick_env_scratch_is_made_0700_and_an_unmakeable_one_fails_the_spawn_not_the_caller(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        with mock.patch("lander.cards.PASSWD_HOME", home):
            L.tick_env({})
            self.assertEqual(os.stat(os.path.join(home, ".cc", "tmp")).st_mode & 0o777, 0o700)
            shutil.rmtree(os.path.join(home, ".cc"))
            open(os.path.join(home, ".cc"), "w").close()   # ~/.cc is a file: makedirs raises whoever runs this
            self.assertFalse(REAL_SPAWN_TICK("demo")[0])

    def test_tick_path_puts_the_system_dirs_first(self):
        # a gh, git or claude a worker drops in ~/bin or ~/.local/bin must not shadow the system's (#862 review reads)
        with mock.patch("lander.cards.PASSWD_HOME", "/home/owner"):
            dirs = L.tick_path().split(":")
        self.assertEqual(dirs[:3], ["/usr/local/bin", "/usr/bin", "/bin"])
        self.assertEqual(sorted(dirs[3:]), ["/home/owner/.local/bin", "/home/owner/bin"])

    def test_pr_facts_names_the_repo(self):
        # a GH_REPO of the caller's would point gh pr view at a decoy PR: -R, or the REST path, names the lander's own slug
        seen = []
        ran = mock.Mock(side_effect=lambda argv, **kw: seen.append(argv) or mock.Mock(returncode=0, stdout="{}",
                                                                                     stderr=""))
        with mock.patch.object(GH, "slug", lambda root: "o/demo"), mock.patch.object(GH.subprocess, "run", ran):
            GH.pr_facts(self.root, 5, "state")
            GH.pr_files(self.root, 5)
            GH.pr_facts(self.root, 5, "comments")
        self.assertEqual([next((x for x in a if x.startswith("repos/o/demo/")), "") or a[a.index("-R") + 1]
                          for a in seen if a[1:3] != ["api", "user"]],   # comments too: none of them over GraphQL
                         ["repos/o/demo/pulls/5", "repos/o/demo/pulls/5/files?per_page=100",
                          "repos/o/demo/issues/5/comments?per_page=100"])
        with mock.patch.object(GH, "slug", lambda root: ""), mock.patch.object(GH.subprocess, "run", ran):
            GH.pr_facts(self.root, 5, "state")
        self.assertNotIn("-R", seen[-1])

    def test_usage_refusals(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(TK.cmd_tick(["--bogus"]), 2)
            self.assertEqual(L.cmd_lane(["bad name"]), 2)
            self.assertEqual(E.cmd_times(["--days"]), 2)
        self.assertEqual(J.repo_root("demo"), self.root)


def one_slot():
    """The lane as it runs on an overloaded box: one check in flight at a time."""
    return mock.patch.object(L.Lane, "width", lambda self: 1)


def first_check_waits(test, until, then=0.0):
    """A Runner whose first check runs until `until()` holds (at most 10 s), and each later one `then` seconds: the
    lane records a finished check at every turn, so an instant fake check would otherwise let the job that ran it go
    on before a later job's turn."""
    def hook(name, n):
        end = time.time() + 10
        while n == 1 and not until() and time.time() < end:
            time.sleep(0.02)
        if n > 1:
            time.sleep(then)
    return Runner(hook=hook)


class SmallFirst(Fixture):
    """A free slot goes to the small PR first (owner, 2026-09-28: #779, one line and a minute of checks, waited behind
    ~20 full-suite PRs). With one slot — the box overloaded — a small PR waits for at most one check of a full suite,
    never the suite. Here a plan of more than one check is heavy."""

    def merged_order(self):
        return [int(argv[2]) for argv in self.box()["merges"]]

    def test_a_small_pr_queued_behind_a_full_suite_merges_first(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})   # three checks: heavy
        self.pr(2, {"docs/r.md": "n\n", "a/x2": "n\n"})           # one check: small
        J.submit("demo", 1)
        J.submit("demo", 2)
        with mock.patch.object(L, "SMALL_CHECKS", 1), one_slot():
            u, _ = self.land()
        self.assertEqual(self.merged_order(), [2, 1])
        # #1's first check, #2's only one, #1's rest; #2's merge moved main under #1, which is not red: no rerun
        self.assertEqual([c[0] for c in u["runner"].calls], ["a", "a", "b", "c"])
        self.assertEqual((self.job(1).state, self.job(2).state), (T.DEPLOY_PENDING, T.DEPLOY_PENDING))

    def test_a_heavy_pr_put_first_goes_before_a_small_one(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})   # three checks: heavy, but put first
        self.pr(2, {"docs/r.md": "n\n", "a/x2": "n\n"})           # one check: small
        J.submit("demo", 1)
        J.submit("demo", 2)
        J.put_first("demo", 1, "seat")
        with mock.patch.object(L, "SMALL_CHECKS", 1), one_slot():
            u, _ = self.land()
        self.assertEqual(self.merged_order(), [1, 2])
        self.assertEqual([c[0] for c in u["runner"].calls][:3], ["a", "b", "c"])   # #1's suite before #2's check

    def test_a_query_keeps_a_put_first(self):
        # dispatch #2026, 10-25: put first, then a query for perms' read and queued again, it sat behind 8 older PRs
        self.pr(2, {"b/y": "n\n"})
        self.pr(1, {"a/x": "n\n"})
        for n in (1, 2):
            J.submit("demo", n)
        with J.lane_lock("demo"):
            J.drain("demo")
        J.put_first("demo", 2, "seat")
        J.move(self.job(2), T.QUERY, why="perms' read")
        J.move(self.job(2), T.QUEUED, why="queued again")
        self.assertEqual([j.pr for j in J.lane_jobs("demo")], [2, 1])

    def test_a_new_head_after_a_query_drops_a_put_first(self):
        # perms-c9, 10-26: kept through a query, a put-first stayed at the front for whatever head came next
        for push in (False, True):
            self.setUp()
            head = self.pr(1, {"a/x": "n\n"})
            J.submit("demo", 1)
            with J.lane_lock("demo"):
                J.drain("demo")
            J.put_first("demo", 1, "seat")
            job = self.job(1)
            job.head = head
            J.move(job, T.QUERY, why="perms' read")
            self.assertEqual(J.first("demo", 1)["head"], head)
            J.move(self.job(1), T.QUEUED, why="queued again")
            if push:
                self.push("track/row-1", {"a/x": "m\n"})
            with mock.patch.object(L.Lane, "width", lambda lane: 0):   # read and planned, no check started
                self.land()
            self.assertEqual(bool(J.first("demo", 1)), not push, push)

    def test_the_lanes_own_branch_update_keeps_a_put_first(self):
        # #1960 review: a put-first kept through a query was dropped at the head the lane's own update-branch made.
        # #1982 review: an author's push on top of that update kept it too
        for author in (False, True):
            self.setUp()
            head = self.pr(1, {"a/x": "n\n"})
            J.submit("demo", 1)
            with J.lane_lock("demo"):
                J.drain("demo")
            J.put_first("demo", 1, "seat")
            job = self.job(1)
            job.head = head
            J.move(job, T.QUERY, why="perms' read")
            job = self.job(1)
            job.extra["behind_update"] = {"from": head, "at": E.stamp()}
            J.move(job, T.QUEUED, why="queued again")
            new = self.push("track/row-1", {"a/x": "m\n"}, fresh=False)   # on the head, as GitHub's merge would be
            if author:
                new = self.push("track/row-1", {"a/x": "o\n"}, fresh=False)
            with mock.patch.object(L.Lane, "width", lambda lane: 0):
                self.land()
            self.assertEqual(J.first("demo", 1).get("head"), None if author else new, author)

    def test_a_put_first_is_good_for_one_landing(self):
        # merged or closed, the record goes: a PR closed unmerged and queued again later waits its turn
        self.pr(3, {"a/x": "n\n"}, state="CLOSED", headRefOid="e" * 40)
        self.pr(2, {"b/y": "n\n"})
        self.pr(1, {"c/z": "n\n"})
        for n in (3, 2):
            J.submit("demo", n)
            J.put_first("demo", n, "seat")
        self.land()
        self.assertEqual((self.job(3).state, self.job(2).state), (T.DONE, T.DEPLOY_PENDING))
        self.assertEqual((J.first("demo", 3), J.first("demo", 2)), ({}, {}))
        self.assertFalse(os.path.exists(J.first_path("demo", 3)))
        self.set_box(prs={**self.box()["prs"], "3": {**self.box()["prs"]["3"], "state": "OPEN"}})
        J.submit("demo", 1)
        J.submit("demo", 3)
        with J.lane_lock("demo"):
            J.drain("demo")
        self.assertEqual([j.pr for j in J.lane_jobs("demo") if j.state == T.QUEUED], [1, 3])
        J.put_first("demo", 1, "seat")   # and a removed job's record goes with it
        J.remove(self.job(1))
        self.assertFalse(os.path.exists(J.first_path("demo", 1)))

    def test_with_no_heavy_plan_the_queue_keeps_its_order(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})
        self.pr(2, {"docs/r.md": "n\n", "a/x2": "n\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        with mock.patch.object(L, "SMALL_CHECKS", 3), one_slot():   # three checks is still small: oldest first
            u, _ = self.land(runner=first_check_waits(self, lambda: self.job(2).state != T.QUEUED))
        self.assertEqual(self.merged_order(), [1, 2])
        # #1's suite, then #2's `a`; #1's merge moved main under #2, which is not red: no rerun
        self.assertEqual([c[0] for c in u["runner"].calls], ["a", "b", "c", "a"])

    def test_a_small_pr_queued_mid_suite_goes_in_after_the_running_check(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})
        self.pr(2, {"a/x2": "n\n"})
        J.submit("demo", 1)
        hook = lambda name, n: J.submit("demo", 2) if n == 1 else None  # noqa: E731
        with mock.patch.object(L, "SMALL_CHECKS", 1), one_slot():
            u, _ = self.land(runner=Runner(hook=hook))
        self.assertEqual(self.merged_order(), [2, 1])
        self.assertEqual([c[0] for c in u["runner"].calls][:2], ["a", "a"])   # #1's first check, then #2's only one
        self.assertEqual(self.job(1).state, T.DEPLOY_PENDING)

    def test_a_plan_with_the_full_suite_is_heavy_however_few_its_checks(self):
        # two checks, one of them check-sh (the whole suite): a count is not a cost
        planner = Planner(owners={"check-sh": "a/", "lint": "a/", "b": "b/"})
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        with one_slot():   # SMALL_CHECKS stays at its default of 5
            u, _ = self.land(planner=planner)
        self.assertEqual(self.merged_order(), [2, 1])
        self.assertEqual([c[0] for c in u["runner"].calls], ["check-sh", "b", "lint"])
        self.assertTrue(L.Lane.heavy(self.job(1)))
        self.assertFalse(L.Lane.heavy(self.job(2)))

    def test_two_heavy_prs_keep_their_order(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n"})
        self.pr(2, {"b/y2": "n\n", "c/z": "n\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        with mock.patch.object(L, "SMALL_CHECKS", 1), one_slot():
            u, _ = self.land()
        self.assertEqual(self.merged_order(), [1, 2])
        # #2 is planned while #1's first check runs (that is how the lane learns it is heavy), then waits: the older
        # heavy job gets each free slot until its suite is done; #1's merge moved main under #2, not red: no rerun
        self.assertEqual([c[0] for c in u["runner"].calls], ["a", "b", "b", "c"])


class Gate(Runner):
    """A runner whose checks on PR `pr`'s tree wait for `release` (at most 20 s), so a test can hold one running."""

    def __init__(self, tree_of_pr, wait=20, **kw):
        super().__init__(**kw)
        self.release, self.tree_of_pr, self.timed_out, self.wait = threading.Event(), tree_of_pr, False, wait

    def run(self, check, tree, where):
        if tree == self.tree_of_pr():
            self.timed_out = not self.release.wait(self.wait)
        return super().run(check, tree, where)


class Parallel(Fixture):
    """Checks run side by side and merges one at a time (lander-redesign.tex, "Changes that don't overlap land side by
    side"; 2026-09-29 a three-file PR waited over 7 h behind ~11 half-hour PRs)."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(L.Lane, "width", lambda self: 3)
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(L, "POLL", 0.05)
        q.start()
        self.addCleanup(q.stop)
        # these cases are about the runners' flights, which go out only while this host is overloaded
        r = mock.patch.object(L.RUN, "spill", return_value="load 50.0 on 20 cores (at least 2x)")
        r.start()
        self.addCleanup(r.stop)
        # and about where checks go, not perms' hold on a host check (HostHold)
        h = mock.patch.object(L.Lane, "host_unread", lambda self, job, m, todo: [])
        h.start()
        self.addCleanup(h.stop)

    def merged_order(self):
        return [int(argv[2]) for argv in self.box()["merges"]]

    def test_a_heavy_check_running_does_not_stop_a_small_prs_checks(self):
        heads = {1: self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"}), 2: self.pr(2, {"docs/r.md": "n\n"})}
        planner = Planner(owners={"a": "a/", "b": "b/", "c": "c/", "docs": "docs/"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        runner = Gate(lambda: (self.job(1).extra or {}).get("tree"))
        board = Rec()
        merges_on = []
        real_merge = GH.merge

        def merge(*a, **k):   # every merge is the lane's own thread, and #2's frees #1's held check
            merges_on.append(threading.current_thread() is threading.main_thread())
            got = real_merge(*a, **k)
            runner.release.set()
            return got
        with mock.patch.object(L, "SMALL_CHECKS", 1), mock.patch.object(GH, "merge", merge):
            _, lines = self.land(planner=planner, runner=runner, board=board)
        self.assertFalse(runner.timed_out, "#1's check held the lane: #2 never merged while it ran")
        self.assertEqual(self.merged_order(), [2, 1])
        self.assertEqual(merges_on, [True, True])
        for pr, argv in zip((2, 1), self.box()["merges"]):   # each pinned to the head its checks ran on
            self.assertEqual(argv[argv.index("--match-head-commit") + 1], heads[pr])
            self.assertIn(f"stage demo#{pr} merged sha={heads[pr][:12]}", self.log())
        self.assertNotIn("proof=mismatch", self.log())
        self.assertEqual((self.job(1).state, self.job(2).state), (T.DEPLOY_PENDING, T.DEPLOY_PENDING))
        self.assertEqual(sorted(self.job(1).results), ["a", "b", "c"])

    def test_no_more_checks_run_at_once_than_the_lane_has_slots(self):
        for n in (1, 2, 3, 4):   # each its own directory and check, so no merge moves another's check
            self.pr(n, {f"x{n}/f": "n\n"})
            J.submit("demo", n)
        live, most, lock = [0], [0], threading.Lock()
        started = [0]
        both = threading.Barrier(2, timeout=30)   # the first two checks wait for each other, so both are live at once

        class Counting(Runner):
            def run(self, check, tree, where):
                with lock:
                    live[0] += 1
                    most[0] = max(most[0], live[0])
                    started[0] += 1
                    first_two = started[0] <= 2
                if first_two:
                    both.wait()
                else:
                    time.sleep(0.05)
                with lock:
                    live[0] -= 1
                return super().run(check, tree, where)
        with mock.patch.object(L.Lane, "width", lambda self: 2):
            u, _ = self.land(planner=Planner(owners={f"p{n}": f"x{n}/" for n in (1, 2, 3, 4)}), runner=Counting())
        self.assertLessEqual(most[0], 2)
        self.assertEqual(most[0], 2)
        self.assertEqual(len(u["runner"].calls), 4)
        self.assertEqual(sorted(self.merged_order()), [1, 2, 3, 4])

    def test_a_heavy_prs_checks_fill_every_free_box_slot_when_no_other_job_wants_one(self):
        # brief, 10-13: 3 of 5 slots sat free for hours while 39 jobs were checking, each held to one box check
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})
        J.submit("demo", 1)
        three, broke = threading.Barrier(3, timeout=5), []

        class Together(Runner):
            def run(self, check, tree, where):
                try:
                    three.wait()
                except threading.BrokenBarrierError:
                    broke.append(check.name)
                return super().run(check, tree, where)
        with mock.patch.object(L.RUN, "spill", return_value=""):   # this host keeps its own checks
            u, _ = self.land(runner=Together())
        self.assertEqual(broke, [], "the PR's three checks did not run at once on three free box slots")
        self.assertEqual(sorted(c[0] for c in u["runner"].calls), ["a", "b", "c"])
        self.assertEqual(self.merged_order(), [1])

    def test_a_heavy_pr_takes_no_second_box_slot_while_another_job_waits_for_its_first(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})
        self.pr(2, {"d/w": "n\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        both, started, lock = threading.Barrier(2, timeout=10), [], threading.Lock()

        class FirstTwo(Runner):
            def run(self, check, tree, where):
                with lock:
                    started.append(check.name)
                    first_two = len(started) <= 2
                if first_two:   # the first two checks wait for each other: both are live at once
                    both.wait()
                return super().run(check, tree, where)
        with mock.patch.object(L.Lane, "width", lambda self: 2):
            self.land(planner=Planner(owners={"a": "a/", "b": "b/", "c": "c/", "d": "d/"}), runner=FirstTwo())
        self.assertEqual(sorted(started[:2]), ["a", "d"])   # #1's first check and #2's only one, not #1's first two
        self.assertEqual(sorted(started), ["a", "b", "c", "d"])
        self.assertEqual(sorted(self.merged_order()), [1, 2])

    def test_a_review_read_does_not_stop_another_jobs_checks(self):
        # 10-13: 3 of 5 box slots sat free for hours with 39 jobs checking. A read (up to READ_TIMEOUT per reader) ran
        # on the lane's thread, so no finished check was recorded and no free slot filled until it ended
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        runner, seen = Runner(), []

        class Slow(Reviewer):
            def review(self, job):   # #1's read lasts until #2's check has run (at most 5 s)
                end = time.time() + 5
                while "b" not in [c[0] for c in runner.calls] and time.time() < end:
                    time.sleep(0.02)
                seen.append([c[0] for c in runner.calls])
                return super().review(job)
        with one_slot():   # #2's check waits for #1's slot, which frees just before #1's read
            # three reads: #2 is read again once #1's merge moves main
            self.land(planner=Planner(paid=True), runner=runner, reviewer=Slow(*[V(T.LAND)] * 3))
        self.assertEqual(seen[0], ["a", "b"], "#2's check did not run while #1's review read was in the pool")
        self.assertEqual(sorted(self.merged_order()), [1, 2])

    def spare_lane(self, *states):
        """A lane whose pass read #1 (checking, two checks, none run) and one job per state in `states` (#2, #3…),
        each with a plan of one check. -> (lane, #1, [the others])."""
        for n in range(1, len(states) + 2):
            self.pr(n, {f"f/{n}": "n\n"})
            J.submit("demo", n)
        with J.lane_lock("demo"):
            J.drain("demo")
        lane = L.Lane("demo", self.units())
        me = self.job(1)
        me.state, me.plan = T.CHECKING, T.Plan(checks=["a", "b"])
        others = []
        for n, st in enumerate(states, 2):
            j = self.job(n)
            j.state, j.plan = st, T.Plan(checks=["c"])
            others.append(j)
        lane.jobs = [me] + others
        quiet = mock.patch.object(L.RUN, "spill", return_value="")   # no admission ticket waits, a slot is free
        quiet.start()
        self.addCleanup(quiet.stop)
        return lane, me, others

    def test_no_spare_slot_in_a_member_lane_or_while_a_check_waits_at_the_door(self):
        # perms, 10-13: a member PR ran 3 checks at once where main runs 1, its tickets ahead of the owner's greens
        lane, me, _ = self.spare_lane()
        self.assertTrue(lane.spare_box(me))    # alone, on a quiet host: spare
        lane.member = "alice"
        self.assertFalse(lane.spare_box(me))
        lane.member = ""
        with mock.patch.object(L.RUN, "spill", return_value="every admission slot on this host is held"):
            self.assertFalse(lane.spare_box(me))

    def sibling_stopped(self, red, wait):
        """#1 runs a and b side by side (a quiet host); a ends as `red` says while b waits up to `wait` seconds for
        its stop. -> [whether b was stopped]."""
        self.pr(1, {"a/x": "n\n", "b/y": "n\n"})
        J.submit("demo", 1)
        stopped = []

        class Red(Runner):
            def run_plan(self, *a, only=None, **kw):
                if only == ["b"]:
                    stopped.append(kw["cancel"].wait(wait))
                return super().run_plan(*a, only=only, **kw)
        with mock.patch.object(L.RUN, "spill", return_value=""):
            self.land(planner=Planner(owners={"a": "a/", "b": "b/"}), runner=Red(status={"a": red} if red else {}))
        return stopped

    def test_a_handback_stops_the_jobs_other_checks(self):
        # perms, 10-13: after a handback the job's other checks kept running for nothing
        self.assertEqual(self.sibling_stopped(T.FAILED, 5), [True])
        self.assertEqual(self.job(1), None)    # handed back: it left the lane

    def test_a_main_red_hold_stops_the_jobs_other_checks(self):
        self.assertEqual(self.sibling_stopped(L.RUN.BLOCKED, 5), [True])
        self.assertEqual(self.job(1).state, T.HELD)

    def test_a_green_check_stops_none_of_the_others(self):
        self.assertEqual(self.sibling_stopped(None, 0.3), [False])
        self.assertEqual(self.merged_order(), [1])

    def reads_lane(self, member=""):
        """A lane with #1 and #2 checking at their own digests, and a pool whose reads end only when the test ends
        them. -> (lane, #1, #2, [the futures of the reads submitted])."""
        heads = {n: self.pr(n, {f"f/{n}": "n\n"}) for n in (1, 2)}
        for n in (1, 2):
            J.submit("demo", n)
        with J.lane_lock("demo"):
            J.drain("demo")
        lane = L.Lane("demo", self.units())
        lane.member, lane.waiting = member, set()
        submitted = []

        class Pool:
            def submit(self, *a):
                submitted.append(futures.Future())
                return submitted[-1]
        lane.pool = Pool()
        one, two = self.job(1), self.job(2)
        for j in (one, two):   # at the head origin has, so review()'s look at the live head lets the read start
            j.state, j.digest, j.head = T.CHECKING, f"{j.pr}" * 40, heads[j.pr]
            j.extra["branch"] = f"track/row-{j.pr}"
        return lane, one, two, submitted

    def test_a_read_whose_job_left_checking_holds_its_place_until_it_ends(self):
        # opus, 10-13: a read dropped when its job left checking kept running, and a second read started beside it
        lane, one, two, submitted = self.reads_lane()
        self.assertFalse(lane.review(one))
        one.state = T.QUEUED   # a push mid-read
        lane.drop_reads([one, two])
        self.assertFalse(lane.review(two))
        self.assertEqual(len(submitted), 1, "a second read started beside a dropped one (REVIEW_SLOTS=1)")
        self.assertIn(two.key, lane.waiting)
        submitted[0].set_result(V(T.LAND))
        lane.drop_reads([one, two])
        self.assertFalse(lane.review(two))
        self.assertEqual(len(submitted), 2, "the dropped read ended, yet #2's read did not start")

    def test_a_read_whose_job_left_checking_is_charged_when_it_ends(self):
        # opus, 10-13: a member who pushed during each read stayed under the day's cap
        Members.make_member(self)
        self.set_box(config={"CC_GH_PERSONAL_OWNER": "own", "MEMBER_DAILY_USD": "5"})
        lane, one, two, submitted = self.reads_lane(member="alice")
        lane.review(one)
        one.state = T.QUEUED
        lane.drop_reads([one, two])
        self.assertEqual(M.spent("alice")[0], 0)   # still running: nothing charged yet
        submitted[0].set_result(V(T.LAND, usd=0.5))
        lane.drop_reads([one, two])
        self.assertEqual(M.spent("alice")[0], 0.5)
        lane.drop_reads([one, two])
        self.assertEqual(M.spent("alice")[0], 0.5)   # charged once

    def test_a_read_of_an_earlier_digest_holds_its_place_until_it_ends(self):
        # opus, 10-13: a push within one pass (a new digest, still checking) dropped the running read uncounted
        lane, one, _, submitted = self.reads_lane()
        self.assertFalse(lane.review(one))
        one.digest = "9" * 40
        self.assertFalse(lane.review(one))
        self.assertEqual(len(submitted), 1, "a read of the new digest started beside the earlier one (REVIEW_SLOTS=1)")
        submitted[0].set_result(V(T.LAND))
        lane.drop_reads([one])
        self.assertFalse(lane.review(one))
        self.assertEqual(len(submitted), 2, "the earlier read ended, yet the new digest's read did not start")

    def test_the_lane_waits_for_a_dropped_read_still_running(self):
        # opus, 10-13: loop() returned while a dropped read ran, so it was never charged
        lane, one, two, submitted = self.reads_lane()
        lane.review(one)
        one.state = T.QUEUED
        lane.drop_reads([one, two])
        self.assertEqual(lane.pending_reads(), [submitted[0]])
        submitted[0].set_result(V(T.LAND))
        lane.drop_reads([one, two])
        self.assertEqual(lane.pending_reads(), [])

    def test_review_slots_come_from_cc_config(self):
        # 2026-10-22: ~/.cc/config set LANDER_REVIEW_SLOTS=3, the lane read only its own environment and ran one read
        self.set_box(config={"LANDER_REVIEW_SLOTS": "2"})
        lane, one, two, submitted = self.reads_lane()
        self.assertEqual(lane.review_slots, 2)
        self.assertFalse(lane.review(one))
        self.assertFalse(lane.review(two))
        self.assertEqual(len(submitted), 2, "a second read waited though cc-config gives two places")

    def test_a_read_that_ends_while_a_promote_waits_is_recorded(self):
        # 2026-10-22: #23's read ended 20 min into a promote, the lane switched without it, and the next lane read again
        lane, one, _, submitted = self.reads_lane()
        for j in (one, _):
            J.save(j)
        lane.review(one)
        land = T.Verdict(verdict=T.LAND, digest=one.digest, tokens=100, blocking=[], extra={})
        threading.Timer(0.3, submitted[0].set_result, [land]).start()
        with mock.patch.object(J, "stale_release", lambda: "/rel/new"):
            self.assertEqual(lane.loop(set()), "/rel/new")
        got = self.job(1)
        self.assertEqual(got.extra["verdict"]["verdict"], T.LAND)
        self.assertTrue(L.landed_at(got, got.extra["verdict"]), "the next lane would buy the read again")

    def test_a_promote_sleeps_while_one_read_is_done_and_another_runs(self):
        # Opus, 10-23: a finished read nobody marked seen made the promote's wait return at once, 963,786 passes a second
        self.set_box(config={"LANDER_REVIEW_SLOTS": "2"})
        lane, one, two, submitted = self.reads_lane()
        for j in (one, two):
            J.save(j)
        lane.review(one)
        lane.review(two)
        land = T.Verdict(verdict=T.LAND, digest=one.digest, tokens=100, blocking=[], extra={})
        submitted[0].set_result(land)
        threading.Timer(0.5, submitted[1].set_result,
                        [T.Verdict(verdict=T.LAND, digest=two.digest, tokens=100, blocking=[], extra={})]).start()
        calls, real = [], lane.reap
        lane.reap = lambda w: (calls.append(w), real(w))
        with mock.patch.object(J, "stale_release", lambda: "/rel/new"):
            self.assertEqual(lane.loop(set()), "/rel/new")
        self.assertLess(len(calls), 20, "the promote's wait spun on the finished read")
        self.assertEqual(self.job(1).extra["verdict"]["verdict"], T.LAND)
        self.assertEqual(self.job(2).extra["verdict"]["verdict"], T.LAND)

    def test_a_reviewer_fault_met_at_a_promote_holds_the_job(self):
        lane, one, _, submitted = self.reads_lane()
        J.save(one)
        lane.review(one)
        submitted[0].set_exception(L.UnitFault("review.read: TimeoutError"))
        with mock.patch.object(J, "stale_release", lambda: "/rel/new"):
            self.assertEqual(lane.loop(set()), "/rel/new")
        self.assertEqual(self.job(1).state, T.HELD)

    def test_a_git_error_met_at_a_promote_holds_the_job_and_an_unpin_tells_the_seat(self):
        # a read #1895 (10-23): a G.GitError escaped loop() and the lane exited without starting the new release's lane
        lane, one, _, submitted = self.reads_lane()
        J.save(one)
        lane.review(one)
        submitted[0].set_exception(G.Unpinned("no pin"))
        pins = []
        with mock.patch.object(J, "stale_release", lambda: "/rel/new"), \
                mock.patch.object(lane, "tell_pin", lambda job, why: pins.append(why)):
            self.assertEqual(lane.loop(set()), "/rel/new")
            for t in [t for t in threading.enumerate() if t.name == "pin"]:
                t.join(10)
        got = self.job(1)
        self.assertEqual((got.state, got.extra["hold"], pins), (T.HELD, "box", ["no pin"]))

    def test_a_checking_job_with_no_box_check_keeps_the_slot_from_a_second_one(self):
        lane, me, (c,) = self.spare_lane(T.CHECKING)
        self.assertFalse(lane.spare_box(me))   # a check left and none on the box: it wants a box slot
        done = futures.Future()
        lane.inflight[(c.key, "c")] = L.Flight(done, c.pr, "c", c.head, c.base_sha, "t", False, threading.Event())
        self.assertTrue(lane.spare_box(me))    # its one is on the box
        lane.inflight.clear()
        c.results["c"] = "k"
        self.assertTrue(lane.spare_box(me))    # nothing left to run

    def test_a_prs_laptop_checks_run_side_by_side_beside_one_box_slot(self):
        # owner 2026-09-29: the laptop sat at 4% while 19 PRs waited; every check that may leave the box goes there,
        # several at once, and does not wait for the box's slots (width 1 here, as on an overloaded box)
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})
        J.submit("demo", 1)
        three = threading.Barrier(3, timeout=20)
        broke = []

        class Together(Runner):
            def run(self, check, tree, where):
                try:
                    three.wait()
                except threading.BrokenBarrierError:
                    broke.append(check.name)
                return super().run(check, tree, where)
        with mock.patch.object(L.Lane, "width", lambda self: 1), mock.patch.object(L.A, "LAPTOP_SLOTS", 5), \
                mock.patch.object(L.RUN, "laptop_dest", return_value="ccsuite@r"), \
                mock.patch.object(L.RUN, "may_leave", return_value=True), \
                mock.patch.object(L.Lane, "manifest", lambda self, job: types.SimpleNamespace(
                    checks={n: T.Check(name=n, run="true") for n in "abc"})):
            u, _ = self.land(planner=Planner(owners={"a": "a/", "b": "b/", "c": "c/"}), runner=Together())
        self.assertEqual(broke, [], "the laptop's checks of one PR did not run at once")
        self.assertEqual(sorted(c[0] for c in u["runner"].calls), ["a", "b", "c"])
        self.assertEqual(self.merged_order(), [1])

    def test_only_a_silent_laptop_rests_it_a_busy_one_does_not(self):
        from lander import run as RUN

        def outs(why):
            return {"a": RUN.Outcome("a", T.PASSED, "", [T.Result(check="a", tree="t", status=T.PASSED,
                                                                  extra={"laptop": why} if why is not None else {})])}
        self.assertTrue(RUN.laptop_gone(outs("laptop refused or did not answer: timeout")))
        self.assertFalse(RUN.laptop_gone(outs("cc-suite-runner: busy (no free slot)")))
        self.assertFalse(RUN.laptop_gone(outs(None)))

    def test_a_laptop_that_gave_no_answer_sends_the_next_checks_to_the_box_one_per_job(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n"})
        J.submit("demo", 1)
        kws, live, most, lock = [], [0], [0], threading.Lock()

        class Box(Runner):
            def run_plan(self, *a, **kw):
                kws.append(kw.get("box_only"))
                return super().run_plan(*a, **kw)

            def run(self, check, tree, where):
                with lock:
                    live[0] += 1
                    most[0] = max(most[0], live[0])
                time.sleep(0.1)
                with lock:
                    live[0] -= 1
                return super().run(check, tree, where)
        lane_init = L.Lane.__init__

        def init(self, *a, **k):
            lane_init(self, *a, **k)
            self.laptop_down = time.time()
        with mock.patch.object(L.Lane, "__init__", init), \
                mock.patch.object(L.RUN, "laptop_dest", return_value="ccsuite@r"), \
                mock.patch.object(L.RUN, "may_leave", return_value=True), \
                mock.patch.object(L.Lane, "manifest", lambda self, job: types.SimpleNamespace(
                    checks={n: T.Check(name=n, run="true") for n in "ab"})):
            u, _ = self.land(planner=Planner(owners={"a": "a/", "b": "b/"}), runner=Box())
        self.assertEqual(kws, [True, True])
        self.assertEqual(most[0], 1)   # on the box, one check of a job at a time
        self.assertEqual(self.merged_order(), [1])

    def test_a_laptop_that_gives_no_answer_mid_lane_rests_and_the_next_checks_go_to_the_box(self):
        # lane.reap: a laptop check whose result says the laptop gave no answer rests the laptop for LAPTOP_REST, so
        # the job's next checks go to the box (box_only)
        self.assertEqual(self.laptop_answers("laptop refused or did not answer: timeout"), [False, True, True])

    def test_a_laptop_that_answers_busy_is_not_rested(self):
        # the suppressed case: a full runner takes the next check when a slot frees, so the laptop stays in use
        self.assertEqual(self.laptop_answers("cc-suite-runner: busy (no free slot)"), [False, False, False])

    def laptop_answers(self, why):
        """Land one PR of three laptop checks whose laptop runs say `why`; -> box_only per run_plan, in order."""
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})
        J.submit("demo", 1)
        kws = []

        class Said(Runner):
            def run_plan(self, *a, **kw):
                kws.append(bool(kw.get("box_only")))
                out = super().run_plan(*a, **kw)
                if not kw.get("box_only"):
                    for o in out.values():
                        for r in o.results:
                            r.extra["laptop"] = why
                return out
        # the box has no slot while the laptop is up, so the checks go one after another and only the rest (or its
        # absence) decides where the next one runs
        with mock.patch.object(L.Lane, "width", lambda self: 1 if self.laptop_down else 0), \
                mock.patch.object(L.A, "LAPTOP_SLOTS", 1), \
                mock.patch.object(L.RUN, "laptop_dest", return_value="ccsuite@r"), \
                mock.patch.object(L.RUN, "may_leave", return_value=True), \
                mock.patch.object(L.Lane, "manifest", lambda self, job: types.SimpleNamespace(
                    checks={n: T.Check(name=n, run="true") for n in "abc"})):
            self.land(planner=Planner(owners={"a": "a/", "b": "b/", "c": "c/"}), runner=Said())
        self.assertEqual(self.merged_order(), [1])
        return kws

    def test_where_a_check_runs_is_the_base_tips_word_not_the_prs_stale_base(self):
        # 17:3xZ 2026-09-29: PRs based before main let host checks leave kept them on a box at load 20; main's
        # `where` is taken for a check with the same run, class and cwd, and only for that
        def m(**checks):
            return MF.Manifest(checks=checks, cwd={n: "" for n in checks})
        old = m(a=T.Check(name="a", run="x", klass=T.HOST, where=["box"]),
                b=T.Check(name="b", run="y", klass=T.HOST, where=["box"]),
                c=T.Check(name="c", run="z", klass=T.HOST, where=["box", "laptop"]),
                d=T.Check(name="d", run="w", klass=T.HOST, where=["box"]))
        tip = m(a=T.Check(name="a", run="x", klass=T.HOST, where=["box", "laptop"]),
                b=T.Check(name="b", run="y2", klass=T.HOST, where=["box", "laptop"]),
                c=T.Check(name="c", run="z", klass=T.HOST, where=["box"]))
        got = MF.placed(old, tip)
        self.assertEqual(got.checks["a"].where, ["box", "laptop"])   # main let it go: it goes
        self.assertEqual(got.checks["b"].where, ["box"])             # its run is not main's: the PR's own word
        self.assertEqual(got.checks["c"].where, ["box"])             # main took it back: it stays
        self.assertEqual(got.checks["d"].where, ["box"])             # main has no such check
        self.assertEqual(old.checks["a"].where, ["box"])             # the PR's manifest itself is not changed

    def test_a_job_whose_checks_all_need_the_box_waits_for_a_box_slot_while_the_laptop_has_room(self):
        # review 2026-09-29: the laptop's free room let the job in, every check skipped it, and it sat in `tried`
        # with nothing in flight until the lane restarted; it now waits for the box slot and lands after #1
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        with mock.patch.object(L.Lane, "width", lambda self: 1), mock.patch.object(L.A, "LAPTOP_SLOTS", 5), \
                mock.patch.object(L.RUN, "laptop_dest", return_value="ccsuite@r"), \
                mock.patch.object(L.RUN, "may_leave", return_value=False), \
                mock.patch.object(L.Lane, "manifest", lambda self, job: types.SimpleNamespace(
                    checks={n: T.Check(name=n, run="true") for n in "ab"})):
            u, _ = self.land(planner=Planner(owners={"a": "a/", "b": "b/"}),
                             runner=Runner(hook=lambda n, i: time.sleep(0.2)))
        self.assertEqual(sorted(self.merged_order()), [1, 2])

    def test_a_check_that_may_leave_runs_on_a_free_box_slot_when_the_laptop_is_full(self):
        # review 2026-09-29: the box sat idle while a check waited for the laptop's one slot; the laptop is still
        # taken first, and the box (box_only, so it is not sent on to ssh) takes the next one beside it
        self.pr(1, {"a/x": "n\n", "b/y": "n\n"})
        J.submit("demo", 1)
        two = threading.Barrier(2, timeout=10)
        broke, kws = [], []

        class Both(Runner):
            def run_plan(self, *a, **kw):
                kws.append(bool(kw.get("box_only")))
                return super().run_plan(*a, **kw)

            def run(self, check, tree, where):
                try:
                    two.wait()
                except threading.BrokenBarrierError:
                    broke.append(check.name)
                return super().run(check, tree, where)
        with mock.patch.object(L.Lane, "width", lambda self: 1), mock.patch.object(L.A, "LAPTOP_SLOTS", 1), \
                mock.patch.object(L.RUN, "laptop_dest", return_value="ccsuite@r"), \
                mock.patch.object(L.RUN, "may_leave", return_value=True), \
                mock.patch.object(L.Lane, "manifest", lambda self, job: types.SimpleNamespace(
                    checks={n: T.Check(name=n, run="true") for n in "ab"})):
            u, _ = self.land(planner=Planner(owners={"a": "a/", "b": "b/"}), runner=Both())
        self.assertEqual(broke, [], "the box did not take a check beside the laptop's")
        self.assertEqual(kws, [False, True])   # the laptop's slot first, then the box's
        self.assertEqual(self.merged_order(), [1])

    def placed(self, spill):
        """Land one PR of three checks that may leave, on a lane of 3 box places with RUN.spill() saying `spill`;
        -> where the lane placed each run_plan call, in order ("box" or "runners")."""
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})
        J.submit("demo", 1)
        got = []

        class Where(Runner):
            def run_plan(self, *a, **kw):
                got.append("runners" if kw.get("runners") else "box" if kw.get("box_only") else "?")
                return super().run_plan(*a, **kw)
        with mock.patch.object(L.A, "LAPTOP_SLOTS", 5), mock.patch.object(L.RUN, "spill", return_value=spill), \
                mock.patch.object(L.RUN, "laptop_dest", return_value="ccsuite@r"), \
                mock.patch.object(L.RUN, "may_leave", return_value=True), \
                mock.patch.object(L.Lane, "manifest", lambda self, job: types.SimpleNamespace(
                    checks={n: T.Check(name=n, run="true") for n in "abc"})):
            self.land(planner=Planner(owners={"a": "a/", "b": "b/", "c": "c/"}), runner=Where())
        self.assertEqual(self.merged_order(), [1])
        return got

    def test_a_calm_box_takes_one_check_of_a_job_and_the_runners_take_the_rest(self):
        # Opus handback on #1160: spilling only while overloaded kept a calm box at its slots while the runner
        # idled; a job holds one box check at a time, so its others go to the runners rather than wait for it
        self.assertEqual(self.placed(""), ["box", "runners", "runners"])

    def test_every_check_goes_to_the_runners_while_spill_says_the_box_is_full(self):
        # the lane gates its box place on RUN.spill(): overloaded, or every admission slot held (#772: a check every
        # 8-30 min on 1-2 box slots while the laptop answered `free 6`)
        self.assertEqual(self.placed("every admission slot on this host is held"), ["runners"] * 3)

    def test_a_queued_pr_refused_by_a_github_backoff_gets_its_turn_when_the_backoff_ends(self):
        # brief, 10-13 cause 2: a queued job that used its turn without moving waited in `tried`; one refused by a
        # backoff had nothing to let it back while another PR's check ran, so it sat queued until the lane ended
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n"})
        J.submit("demo", 1)
        moved, said, say = [], [], L.Lane.say

        def saying(lane, ln, *a, **k):
            said.append(ln)
            return say(lane, ln, *a, **k)

        def hook(name, n):
            if n != 1 or moved:
                return
            J.write_atomic(GH.backoff_path(), {"until": time.time() + 600, "fails": 1})
            J.submit("demo", 2)
            end = time.time() + 10
            while not any("PR #2: GitHub backoff" in ln for ln in said) and time.time() < end:
                time.sleep(0.02)
            os.unlink(GH.backoff_path())
            end = time.time() + 5
            while J.load("demo", 2).state == T.QUEUED and time.time() < end:
                time.sleep(0.02)
            moved.append(J.load("demo", 2).state != T.QUEUED)   # while #1's check still runs
        with mock.patch.object(L.Lane, "say", saying):
            self.land(runner=Runner(hook=hook))
        self.assertTrue(any("PR #2: GitHub backoff" in ln for ln in said), said)
        self.assertEqual(moved, [True])

    def test_a_check_whose_job_left_checking_meanwhile_is_not_recorded(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)

        def hook(name, n):   # something outside the lane moves the job while its check runs
            if n == 1:
                job = J.load("demo", 1)
                J.move(job, T.HELD, "held by hand")
                job.extra.update(held_from=T.QUEUED, hold="box", not_before=E.stamp(time.time() + 900))
                J.save(job)
        _, lines = self.land(runner=Runner(hook=hook))
        self.assertIn("[demo] PR #1: check a finished for a head or base the job has left; not recorded", lines)
        self.assertEqual(self.job(1).state, T.HELD)
        self.assertEqual(self.job(1).results, {})

    def test_a_promote_waits_for_the_checks_in_flight_and_records_them(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n"})
        J.submit("demo", 1)
        moved = []
        hook = lambda name, n: moved.append("/rel/new") if n == 1 else None  # noqa: E731
        with mock.patch.object(J, "stale_release", lambda: moved[0] if moved else ""), \
                mock.patch.object(L, "spawn_lane", lambda repo, rel: (True, "unit x")), one_slot():
            u, lines = self.land(runner=Runner(hook=hook))   # one slot: `b` would otherwise start beside `a`
        self.assertEqual([c[0] for c in u["runner"].calls], ["a"])   # nothing new after the promote
        self.assertEqual(sorted(self.job(1).results), ["a"])           # the one in flight is kept
        self.assertEqual(self.job(1).state, T.CHECKING)
        self.assertTrue(any("this lane takes no new job" in ln for ln in lines))


class Express(Fixture):
    """A check a mergeable PR runs again only because main moved and is red on it goes at once, beside the box slot
    another PR's check holds (2026-10-02/03: #905 went back to checking four times for a 0 s rerun that then waited
    hours behind half-hour suites, and main moved again meanwhile)."""

    def setUp(self):
        super().setUp()
        q = mock.patch.object(L, "POLL", 0.05)
        q.start()
        self.addCleanup(q.stop)

    MANIFEST = "".join(f'[[check]]\nname = "{n}"\nrun = "{n}/run.sh"\npaths = ["{n}/**"]\nclass = "static"\n\n'
                       for n in "abc")

    def race(self, wait=20, pr2=None, first=False):
        """#2's `b` and #1's `a` start side by side; #1's holds its slot (a Gate) until #2 merges. At #2's first CI
        look the box narrows to one slot and main moves, red on `b`, so #2 must run `b` again. pr2: more files #2
        changes. first: #2 is put first (queue --first). -> the runner"""
        self.push("main", {"tests/LANDING.toml": self.MANIFEST})
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n", **(pr2 or {})})
        J.submit("demo", 2)
        J.submit("demo", 1)
        if first:
            J.put_first("demo", 2, "seat")
        def green_again(name, n):   # main's health goes green with #2's rerun of b: a later move reruns nothing
            if name == "b" and [c[0] for c in runner.calls].count("b") == 2:
                self.main_red()
        runner = Gate(lambda: (self.job(1).extra or {}).get("tree"), wait=wait, hook=green_again)
        narrow, real_ci, real_merge = [], L.Lane.ci_green, GH.merge

        def ci_green(lane, job):
            if job.pr == 2 and not narrow:
                narrow.append(True)
                self.push("main", {"b/z": "main moved\n"})
                self.main_red("b")
            return real_ci(lane, job)

        def merge(*a, **k):
            got = real_merge(*a, **k)
            runner.release.set()
            return got
        with mock.patch.object(L.Lane, "width", lambda lane: 1 if narrow else 2), \
                mock.patch.object(L.Lane, "ci_green", ci_green), mock.patch.object(GH, "merge", merge):
            self.land(runner=runner)
        self.assertEqual([c[0] for c in runner.calls].count("b"), 2)
        self.assertIn("main moved and is red on b: rerun b", [h.get("why") for h in self.job(2).history])
        return runner

    def merged_order(self):
        return [int(argv[2]) for argv in self.box()["merges"]]

    def test_a_rerun_after_main_moved_runs_beside_the_slot_a_check_holds(self):
        runner = self.race()
        self.assertFalse(runner.timed_out, "#2's rerun of b waited for #1's slot")
        self.assertEqual(self.merged_order(), [2, 1])
        self.assertEqual(self.job(2).extra["express"]["checks"], ["b"])

    def test_a_rerun_of_a_pr_put_first_still_goes_express(self):
        runner = self.race(first=True)
        self.assertFalse(runner.timed_out, "#2's rerun of b waited for #1's slot")
        self.assertEqual(self.merged_order(), [2, 1])
        self.assertEqual(self.job(2).extra["express"]["checks"], ["b"])
        self.assertIn((("b",), True, True), runner.plan_kw)   # the rerun: express, and the lane's
        self.assertEqual(J.first("demo", 2), {})              # merged: the record is gone

    def test_a_full_suite_rerun_still_waits_for_a_slot(self):
        with mock.patch.object(L, "FULL_CHECKS", ("b",)):
            runner = self.race(wait=1)
        self.assertTrue(runner.timed_out, "#2's rerun of a full suite took no slot")
        self.assertEqual(self.job(2).extra["express"]["checks"], [])

    def test_no_express_under_memory_pressure(self):
        # admission keeps one slot under memory pressure because parallel checks ran the box out of memory: an
        # express run would be a second check beside it
        with mock.patch.object(L.A, "mem_loaded", return_value=True):
            runner = self.race(wait=1)
        self.assertTrue(runner.timed_out, "#2's rerun went express under memory pressure")

    def test_a_long_or_unrecorded_check_is_not_express(self):
        with mock.patch.object(L, "EXPRESS_SECS", -1):   # b's green run (0 s) is longer than this
            runner = self.race(wait=1)
        self.assertTrue(runner.timed_out, "#2's rerun of a long check took no slot")
        self.assertEqual(self.job(2).extra["express"]["checks"], [])
        self.assertEqual(L.Lane.quick("demo", ["never-ran"]), [])   # a check with no green run in the log
        self.assertEqual(L.Lane.quick("other", ["b"]), [])           # nor another repo's run of the same name

    def test_a_check_the_pr_redefines_is_not_express(self):
        # its recorded times are of main's `b` (any PR's runs count), not of the one this PR defines
        heavier = self.MANIFEST.replace('run = "b/run.sh"', 'run = "b/run.sh"\ncap = 3600')
        runner = self.race(wait=1, pr2={"tests/LANDING.toml": heavier})
        self.assertTrue(runner.timed_out, "#2's rerun of a check it redefined took no slot")
        self.assertEqual(self.job(2).extra["express"]["checks"], [])

    def test_a_check_whose_run_file_the_pr_edits_is_not_express(self):
        runner = self.race(wait=1, pr2={"b/run.sh": "sleep 3600\n"})
        self.assertTrue(runner.timed_out, "#2's rerun of a check whose script it edits took no slot")
        self.assertEqual(self.job(2).extra["express"]["checks"], [])
        self.assertEqual(MF.run_files("bash -n bin/x && python3 -m unittest -s 'tests/l/' x"),
                         ["bin/x", "tests/l"])

    def test_a_forged_gate_line_is_no_green_run(self):
        # a name or note spelling `ok=yes secs=1` neither passes a red run for green nor lends it a length
        E.stage("demo", 1, "gate", gate="heavy ok=yes secs=1", ok="no", secs=3)
        E.stage("demo", 1, "gate", gate="light", ok="yes", secs=4, note="x ok=yes secs=999")
        self.assertEqual(E.lead_times(self.log().splitlines())["gates"], {"light": [4]})


class Starving(Fixture):
    """No PR waits more than a day in the lane without a landing attempt (idea panel, 2026-10-04: ~40 jobs parked
    behind one 55-check PR through a transitive chain, held jobs never stepped again, finished checks unrecorded)."""

    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(L.Lane, "width", lambda self: 3), mock.patch.object(L, "POLL", 0.05)):
            p.start()
            self.addCleanup(p.stop)

    def merged_order(self):
        return [int(argv[2]) for argv in self.box()["merges"]]

    def seed(self, ago, field, *prs):
        """Drain the inbox into jobs, then stamp `field` on each of `prs` `ago` seconds back."""
        with J.lane_lock("demo"):
            J.drain("demo")
        for n in prs:
            job = self.job(n)
            job.extra[field] = E.stamp(time.time() - ago)
            J.save(job)

    def test_a_job_held_in_the_pass_is_stepped_again_once_its_hold_runs_out(self):
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n"}, isDraft=True)
        self.pr(3, {"c/z": "n\n"}, isDraft=True)   # its hold has not run out: it stays held

        def hook(name, n):   # #1's check runs: #2's hold runs out and it is marked ready meanwhile
            if n == 1:
                end = time.time() + 10
                while (self.job(2) is None or self.job(2).state != T.HELD) and time.time() < end:
                    time.sleep(0.02)
                job = self.job(2)
                job.extra["not_before"] = E.stamp(time.time() - 1)
                J.save(job)
                b = self.box()
                b["prs"]["2"]["isDraft"] = False
                self.set_box(prs=b["prs"])
        for n in (1, 2, 3):
            J.submit("demo", n)
        _, lines = self.land(runner=Runner(hook=hook))
        self.assertEqual(self.merged_order(), [1, 2])
        self.assertEqual(self.job(3).state, T.HELD)
        self.assertEqual(len([ln for ln in lines if ln.startswith("[demo] PR #3 held")]), 1)

    def test_a_handed_back_pr_queued_again_gets_its_turn_in_the_same_lane(self):
        """raised-a-handed-pr-requeued-never-gets-a-turn: #1226, #1228 and #1234 were handed back by their read,
        queued again, and sat in the lane's `tried` set until the lane process restarted. Here #2's read hands it back
        in its own turn and it is queued again while #1's check still runs: it must merge in this same lane run."""
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n"})
        requeued = []

        class Reads(Reviewer):   # #2's first read hands it back; every other read lands
            def review(self, job):
                self.calls.append(("review", job.pr))
                return V(T.HANDBACK_VERDICT, blocking=["bug"]) if job.pr == 2 and not requeued else V(T.LAND)

            def delta_review(self, job, prior):
                return self.review(job)

        def hook(name, n):   # #1's check runs until #2 is handed back, then #2 is queued again
            end = time.time() + 10
            while name == "a" and not requeued and time.time() < end:
                if self.job(2) is None and os.path.exists(J.handed_path("demo", 2)):
                    J.submit("demo", 2)
                    requeued.append(True)
                    break
                time.sleep(0.02)
        for n in (1, 2):
            J.submit("demo", n)
        self.land(planner=Planner(paid=True), reviewer=Reads(), runner=Runner(hook=hook))
        self.assertEqual(requeued, [True])                     # handed back, then queued again mid-lane
        self.assertEqual(sorted(self.merged_order()), [1, 2])  # and the re-queue had its turn before the lane ended

    def test_a_pr_that_ended_unplanned_and_is_queued_again_in_the_same_second_gets_its_turn(self):
        """The case the test above cannot reach: there the re-queue clears a head the job had, so its queued mark
        moves anyway. #1 here ends before it is planned (the PR is closed: no head read) and is queued again in the
        same one-second stamp, so its (queued_at, head) mark is the one its turn left. Only the lane letting an ended
        job out of `tried` ("A job whose turn ended it ... left `tried` then, since a re-queue may share its
        one-second stamp") gives the re-queue its turn."""
        self.pr(1, {"a/x": "n\n"}, state="CLOSED")
        self.pr(2, {"b/y": "n\n"})
        real, now = E.stamp, time.time()
        p = mock.patch.object(E, "stamp", lambda at=None: real(now if at is None else at))   # one second throughout
        p.start()
        self.addCleanup(p.stop)
        requeued = []

        def hook(name, n):   # #2's check runs until #1 has ended, then #1's PR is reopened and queued again
            end = time.time() + 10
            while name == "b" and not requeued and time.time() < end:
                j = self.job(1)
                if j is not None and j.state == T.DONE:
                    self.assertEqual(j.head, "")   # ended before it was planned
                    self.set_box(prs={**self.box()["prs"], "1": {**self.box()["prs"]["1"], "state": "OPEN"}})
                    J.submit("demo", 1)
                    requeued.append(j.extra.get("queued_at"))
                    break
                time.sleep(0.02)
        for n in (1, 2):
            J.submit("demo", n)
        self.land(planner=Planner(), runner=Runner(hook=hook))
        self.assertEqual(len(requeued), 1)                              # it ended, then was queued again mid-lane
        self.assertEqual(self.job(1).extra.get("queued_at"), requeued[0])   # in the stamp it ended under
        self.assertEqual(sorted(self.merged_order()), [1, 2])           # and the re-queue had its turn

    def test_only_a_hold_a_pin_clears_asks_the_cards_unit_to_tell_the_planning_seat(self):
        """10-21: a box repo's PR held 4 h on a missing pin, and nobody heard. The hold is flagged where git raised it
        (G.Unpinned), never by its words: a CI context a branch names after them wakes nobody (security read of #1827)."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        cards = Rec()
        lane = L.Lane("demo", self.units(cards=cards))
        lane.hold(self.job(1), "check `no remote URL — run lander-self promote` is red")
        self.assertEqual(cards.calls, [])
        job = self.job(1)
        job.state = T.QUEUED
        why = "the lander holds no remote URL for /r; `lander-self promote` pins one"
        with mock.patch.object(lane, "queued", side_effect=G.Unpinned(why)):
            lane.step(job)
        self.assertEqual(job.state, T.HELD)
        for t in [t for t in threading.enumerate() if t.name == "pin"]:
            t.join(10)
        self.assertEqual([(c[0], c[2]) for c in cards.calls], [("pin_hold", why)])

    def test_a_slow_pin_request_never_holds_the_lane(self):
        """Security read of #1827: cc-notify runs up to 60 s, and the lane lock is held where a hold is made, so the
        planning seat's request goes on a thread of its own."""
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        go, said = threading.Event(), []

        class SlowPin(Rec):
            def pin_hold(self, job, why):
                go.wait(10)
                said.append(why)

        lane = L.Lane("demo", self.units(cards=SlowPin()))
        job = self.job(1)
        job.state = T.QUEUED
        with mock.patch.object(lane, "queued", side_effect=G.Unpinned("no pin")):
            lane.step(job)
        self.assertEqual((job.state, said), (T.HELD, []))   # the hold is made while the request still waits
        go.set()
        for t in [t for t in threading.enumerate() if t.name == "pin"]:
            t.join(10)
        self.assertEqual(said, ["no pin"])

    def test_a_hold_leaves_the_queued_mark_and_a_requeue_moves_it(self):
        """queued_mark is what only a re-queue or a new head changes. A hold (reap's took holds a job whose check was
        red on main, or could not run; a turn holds a draft) appends to the job's history but is no re-queue: a mark
        that counted history would re-admit every job a reap held. A re-queue in the same second still moves it, by
        its cleared head. (In the lane loop today reap lets the job it holds out of `tried` itself, so only the mark
        shows this.)"""
        self.pr(1, {"a/x": "n\n"})
        real, now = E.stamp, time.time()
        p = mock.patch.object(E, "stamp", lambda at=None: real(now if at is None else at))
        p.start()
        self.addCleanup(p.stop)
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        job = self.job(1)
        job.head = "a" * 40   # as planning leaves it
        job.state = T.CHECKING
        J.save(job)
        lane = L.Lane("demo", self.units())
        mark = lane.queued_mark(job)
        lane.hold(job, "PR #1 is a draft — mark it ready for review")   # a pr hold: a new queue starts it afresh
        job = self.job(1)
        self.assertEqual(job.state, T.HELD)
        self.assertEqual(lane.queued_mark(job), mark)      # held: the same mark, though its history grew
        J.submit("demo", 1)
        with J.lane_lock("demo"):
            J.drain("demo")
        job = self.job(1)
        self.assertEqual(job.state, T.QUEUED)
        self.assertNotEqual(lane.queued_mark(job), mark)   # queued again, same second: the mark moves

    def test_a_finished_check_is_recorded_while_other_jobs_wait_their_turn(self):
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n"})
        self.pr(3, {"c/z": "n\n"})
        for n in (1, 2, 3):
            J.submit("demo", n)
        real, seen = L.Lane.reap, []

        def reap(lane, wait):
            if wait == 0 and lane.inflight and not seen:   # the first turn with a check out: let it finish first
                futures.wait([f.future for f in lane.inflight.values()], timeout=10)
                due = [j.pr for j in J.lane_jobs("demo") if j.key not in lane.tried and lane.due(j)]
                before = len(lane.inflight)
                real(lane, wait)
                return seen.append((due, before, len(lane.inflight)))
            return real(lane, wait)
        with mock.patch.object(L.Lane, "reap", reap):
            self.land()
        self.assertTrue(seen)
        due, before, after = seen[0]
        self.assertTrue(due)                  # other jobs still had their turn to come…
        self.assertEqual((before, after), (1, 0))   # …and the finished check was recorded, its slot freed
        self.assertEqual(self.merged_order(), [1, 2, 3])

    def test_a_job_in_the_lane_past_the_cap_goes_before_a_younger_small_one(self):
        planner = Planner(owners={"a": "a/", "b": "b/", "c": "c/", "d": "d/", "e": "e/"})
        self.pr(1, {"c/z": "n\n"})                 # small, young
        self.pr(2, {"a/x": "n\n", "b/y": "n\n"})   # heavy, a day in the lane
        self.pr(3, {"d/w": "n\n", "e/v": "n\n"})   # heavy, young: small first still holds for it
        for n in (1, 2, 3):
            J.submit("demo", n)
        self.seed(L.WAIT_CAP + 60, "queued_at", 2)
        with mock.patch.object(L, "SMALL_CHECKS", 1), one_slot():
            u, _ = self.land(planner=planner)
        self.assertEqual(self.merged_order(), [2, 1, 3])
        self.assertEqual([c[0] for c in u["runner"].calls][:2], ["a", "b"])

    def heavy_among_small(self, ago):
        """#1 small (c) holds the one slot, while #2 heavy (a, b) queued `ago` seconds back and #3 small (d) meet
        at the free slot; HEAVY_WAIT an hour (create: on a lane without it the case reads as a wrong order, not a
        missing name). -> the runner's calls."""
        planner = Planner(owners={"a": "a/", "b": "b/", "c": "c/", "d": "d/"})
        self.pr(1, {"c/z": "n\n"})
        self.pr(2, {"a/x": "n\n", "b/y": "n\n"})
        self.pr(3, {"d/w": "n\n"})
        for n in (1, 2, 3):
            J.submit("demo", n)
        self.seed(ago + 60, "queued_at", 1)   # #1 stays first in arrival order
        self.seed(ago, "queued_at", 2)
        with mock.patch.object(L, "SMALL_CHECKS", 1), mock.patch.object(L, "HEAVY_WAIT", 3600, create=True), \
                one_slot():
            # c runs until #2 and #3 are both planned and wait for the slot: they meet there, not in their turns' order
            u, _ = self.land(planner=planner, runner=first_check_waits(
                self, lambda: all(self.job(n).state == T.CHECKING for n in (2, 3))))
        return [c[0] for c in u["runner"].calls]

    def test_a_heavy_job_queued_an_hour_ago_counts_as_small_until_its_first_check_runs(self):
        # brief, 10-13: #943 (38 checks) ran none for 3 h behind small and parked jobs; and owner, 09-28: a one-line
        # PR waits for at most that first check, not for every check of every aged heavy PR
        self.assertEqual(self.heavy_among_small(3600 + 60), ["c", "a", "d", "b"])
        self.assertEqual(self.merged_order(), [1, 3, 2])

    def test_a_heavy_job_queued_under_an_hour_ago_still_waits_for_a_small_one(self):
        self.assertEqual(self.heavy_among_small(3600 - 600), ["c", "d", "a", "b"])
        self.assertEqual(self.merged_order(), [1, 3, 2])

    def test_a_pr_put_first_goes_before_one_past_the_cap(self):
        planner = Planner(owners={"a": "a/", "b": "b/", "c": "c/"})
        self.pr(1, {"a/x": "n\n", "b/y": "n\n"})   # heavy, a day in the lane
        self.pr(2, {"c/z": "n\n"})                 # small, young, put first
        for n in (1, 2):
            J.submit("demo", n)
        self.seed(L.WAIT_CAP + 60, "queued_at", 1)
        J.put_first("demo", 2, "seat")
        with mock.patch.object(L, "SMALL_CHECKS", 1), one_slot():
            u, _ = self.land(planner=planner)
        self.assertEqual(self.merged_order(), [2, 1])
        self.assertEqual([c[0] for c in u["runner"].calls][0], "c")

class SpawnLaneTest(unittest.TestCase):
    def test_the_new_lane_is_its_own_unit_not_a_child_of_the_tick(self):
        # a child left in the tick's unit would be killed with it when the tick ends, mid-job
        with tempfile.TemporaryDirectory() as t:
            fake, got = os.path.join(t, "systemd-run"), os.path.join(t, "argv")
            with open(fake, "w") as f:
                f.write(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {got}\n")
            os.chmod(fake, 0o755)
            with mock.patch.dict(os.environ, {"LANDER_SYSTEMD_RUN": fake}):
                ok, how = L.spawn_lane("demo", "/rel/bbbb")
            argv = open(got).read().split("\n")
        self.assertTrue(ok)
        self.assertTrue(how.startswith("unit lander-lane-demo-"), how)
        self.assertIn("--user", argv)
        self.assertEqual(argv[-4:-1], ["/rel/bbbb/core/lander/cli.py", "lane", "demo"])

    def fallback(self, env):
        popen = mock.MagicMock(return_value=mock.MagicMock(pid=4242))
        with mock.patch.dict(os.environ, env), mock.patch.object(L, "run", lambda *a, **k: (1, "", "no bus")), \
                mock.patch.object(L.subprocess, "Popen", popen):
            if "INVOCATION_ID" not in env:
                os.environ.pop("INVOCATION_ID", None)
            return L.spawn_lane("demo", "/rel/bbbb"), popen

    def test_inside_a_unit_a_failed_systemd_run_starts_no_child(self):
        (ok, how), popen = self.fallback({"INVOCATION_ID": "x"})
        self.assertFalse(ok)
        self.assertIn("inside a unit", how)
        popen.assert_not_called()

    def test_outside_a_unit_a_failed_systemd_run_falls_back_to_a_detached_child(self):
        (ok, how), popen = self.fallback({})
        self.assertEqual((ok, how), (True, "pid 4242"))
        self.assertTrue(popen.call_args.kwargs["start_new_session"])



class Stoppable(Runner):
    """A runner whose first plan calls then() and waits (at most `wait` s) for the lane to stop it through run_plan's
    cancel; a plan that was stopped gives nothing back, one that was not runs as Runner's does."""

    def __init__(self, then, wait=20, **kw):
        super().__init__(**kw)
        self.then, self.wait, self.first, self.stopped = then, wait, None, None

    def run_plan(self, root, m, plan, files, head_tree, base_tree="", *, cancel=None, **kw):
        if self.first is None:
            self.first = head_tree
            self.then()
            self.stopped = bool(cancel is not None and cancel.wait(self.wait))
            if self.stopped:
                return {}
        return super().run_plan(root, m, plan, files, head_tree, base_tree, **kw)


class Rereads(Fixture):
    """A checking job re-reads its PR's state and head every RECHECK_SECS and after an `again`, and stops its checks
    when the PR merged, closed or moved on (10-04: #794 merged at 16:47Z while still checking and held 57 parked jobs
    for 40+ min, under the parking rule since dropped; ai-ee #99 checked a stale head for 50 min after a push). Each
    case queues its own PRs."""

    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(L.Lane, "width", lambda self: 3), mock.patch.object(L, "POLL", 0.05)):
            p.start()
            self.addCleanup(p.stop)
        self.reads, self.merged_on_github = [], threading.Event()
        real = GH.pr_facts

        def facts(root, pr, fields, *a, **k):   # GitHub as the lane sees it: #1 merged once the flag is set
            got, why = real(root, pr, fields, *a, **k)
            if fields == "state,headRefOid":
                self.reads.append(pr)
            if got is not None and int(pr) == 1 and self.merged_on_github.is_set() and "state" in got:
                got = {**got, "state": "MERGED"}
            return got, why
        p = mock.patch.object(GH, "pr_facts", facts)
        p.start()
        self.addCleanup(p.stop)

    def test_a_pr_merged_mid_check_stops_its_checks_and_ends_merged(self):
        self.pr(1, {"a/x": "one\n"})
        self.pr(2, {"b/y": "two\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        runner = Stoppable(self.merged_on_github.set)   # GitHub merges #1 while its check runs
        with mock.patch.object(L, "RECHECK_SECS", 1):
            _, lines = self.land(runner=runner)
        self.assertTrue(runner.stopped, "#1's check ran on after its PR merged")
        j1, j2 = self.job(1), self.job(2)
        self.assertEqual((j1.state, j2.state), (T.DEPLOY_PENDING, T.DEPLOY_PENDING))
        self.assertEqual([h["state"] for h in j1.history][-4:], [T.CHECKING, T.QUEUED, T.MERGED, T.DEPLOY_PENDING])
        self.assertIn("the PR is merged while it was checking", j1.history[-3]["why"])
        self.assertEqual(j1.history[-2].get("by"), "before")
        self.assertEqual([int(a[2]) for a in self.box()["merges"]], [2])   # the lane never merged #1 itself
        self.assertEqual(sorted(j2.results), ["b"])   # #2's check was not stopped: it ran and was recorded

    def test_a_push_mid_check_says_again_and_the_old_heads_check_is_stopped(self):
        old = self.pr(1, {"a/x": "one\n"})
        heads = []

        def push():
            heads.append(self.push("track/row-1", {"a/x": "two\n"}, fresh=False))
            J.submit("demo", 1)   # what the push's re-queue writes: `again` for a job in flight
        runner = Stoppable(push)
        J.submit("demo", 1)
        with mock.patch.object(L, "RECHECK_SECS", 3600):   # the `again`, not the timer, makes it read
            self.land(runner=runner)
        self.assertTrue(runner.stopped, "the old head's check ran on after the push")
        j = self.job()
        self.assertEqual((j.state, j.head), (T.DEPLOY_PENDING, heads[0]))
        self.assertNotEqual(old, heads[0])
        self.assertIn(f"the head moved to {heads[0][:12]} while it was checking",
                      [h for h in j.history if h["state"] == T.QUEUED][-1]["why"])
        self.assertIn("\tagain demo#1", self.log())
        merge = self.box()["merges"][0]
        self.assertEqual(merge[merge.index("--match-head-commit") + 1], heads[0])
        self.assertEqual(len(runner.calls), 1)   # the new head's check; the stopped one gave nothing

    def test_an_again_at_the_same_head_reads_github_and_lets_the_check_run(self):
        self.pr(1, {"a/x": "one\n"})
        runner = Stoppable(lambda: J.submit("demo", 1), wait=1.5)
        J.submit("demo", 1)
        with mock.patch.object(L, "RECHECK_SECS", 3600):
            self.land(runner=runner)
        self.assertFalse(runner.stopped)
        self.assertEqual(self.reads, [1])   # one re-read, for the `again`; the timer never came due
        j = self.job()
        self.assertEqual((j.state, sorted(j.results)), (T.DEPLOY_PENDING, ["a"]))
        self.assertNotIn("while it was checking", json.dumps(j.history))

    def test_a_lane_paused_while_a_job_checks_sleeps_on_it_rather_than_spinning(self):
        # seat Opus read: a re-read due on a job the box holds re-admitted it every pass, refused before it read,
        # with no sleep, under the lane lock
        self.pr(1, {"a/x": "one\n"})
        held, calls = threading.Event(), [0]

        def paused(target):
            calls[0] += 1
            if calls[0] > 500:   # the spin never ends on its own: stop it here, so the case fails, not hangs
                raise AssertionError("the lane spun on the held job")
            return held.is_set()
        runner = Stoppable(held.set, wait=1.0)   # the lane is paused once its check is in flight, for a second
        J.submit("demo", 1)
        with mock.patch.object(L, "paused", paused), mock.patch.object(L, "RECHECK_SECS", 0):
            _, lines = self.land(runner=runner)
        self.assertFalse(runner.stopped)
        self.assertEqual(self.reads, [1])   # the read before its check; none while the box held it
        self.assertLess(calls[0], 100, "the lane spun on the held job")   # ~20 passes at POLL 0.05; the spin made 1000s
        self.assertLessEqual(sum("is paused" in ln for ln in lines), 1, lines[-3:])
        self.assertEqual(self.job().state, T.CHECKING)

    def test_a_merged_or_closed_pr_reads_no_remote_head(self):
        # Opus security read of #1925: the ls-remote (120 s) ran on the lane thread for a PR that had already ended
        for state in ("MERGED", "CLOSED"):
            with self.subTest(state=state):
                j = T.Job(repo="demo", pr=1, head="e" * 40, state=T.CHECKING, extra={"branch": "track/row-1"})
                J.save(j)
                asked = []
                with mock.patch.object(GH, "pr_facts", lambda *a, **k: ({"state": state, "headRefOid": "f" * 40}, "")), \
                        mock.patch.object(G, "remote_head", lambda *a, **k: asked.append(a) or "f" * 40):
                    self.assertTrue(L.Lane("demo", self.units()).reread(j))
                self.assertEqual(asked, [])
                self.assertEqual(J.load("demo", 1).state, T.QUEUED)


class FlakeRetry(Fixture):
    """Brief, 10-12: "a check that fails and then passes on retry at the same head is recorded as flaky". Perms, 10-12:
    "a re-queue after a red handback or a new head starts a fresh queued_at; only the early holds keep the place, and
    that keep must be bounded"."""

    def handed(self, pr, head, queued_at):
        os.makedirs(J.handed_dir(), exist_ok=True)
        J.write_atomic(J.handed_path("demo", pr), {"repo": "demo", "pr": pr, "head": head, "queued_at": queued_at,
                                                  "red": {"check": "a", "head": head}})

    def requeue(self, pr):
        J.submit("demo", pr)
        with J.lane_lock("demo"):
            J.drain("demo")

    def test_a_red_check_hands_back_with_the_red_named(self):
        head = self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        self.land(runner=Runner(status={"a": T.FAILED}))
        w = J.read_json(J.handed_path("demo", 1))
        self.assertEqual(w["red"], {"check": "a", "head": head})
        self.assertNotIn("queued_at", w)

    def test_a_retry_at_the_same_head_goes_to_the_back_and_its_green_is_a_flake(self):
        head = self.pr(1, {"a/x": "n\n"})
        old = E.stamp(time.time() - 3600)
        self.handed(1, head, old)
        self.requeue(1)
        self.assertNotEqual(self.job(1).extra["queued_at"], old)
        self.land()
        self.assertRegex(self.log(), r"flake demo#1 check=a head=\w+ on=retry")
        self.assertNotIn("retry", self.job(1).extra)

    def test_a_retry_at_another_head_goes_to_the_back_and_logs_no_flake(self):
        self.pr(1, {"a/x": "n\n"})
        old = E.stamp(time.time() - 3600)
        self.handed(1, "f" * 40, old)   # red at a head the branch has left
        self.requeue(1)
        self.assertNotEqual(self.job(1).extra["queued_at"], old)
        self.land()
        self.assertNotIn("on=retry", self.log())

    def test_a_hold_keeps_the_place_for_place_holds_holds_and_no_more(self):
        self.pr(1, {"a/x": "n\n"})
        self.requeue(1)
        job, lane = self.job(1), L.Lane("demo", self.units())
        old = E.stamp(time.time() - 3600)
        job.extra["queued_at"] = old
        for n in range(L.PLACE_HOLDS):   # kept: each of the first PLACE_HOLDS holds
            lane.hold(job, "gh could not read it", kind="box")
            self.assertEqual(job.extra["queued_at"], old)
            job.state = T.QUEUED
        lane.hold(job, "gh could not read it", kind="box")   # suppressed: the next one stamps it afresh
        self.assertNotEqual(job.extra["queued_at"], old)
        self.assertLess(time.time() - E.epoch_of(job.extra["queued_at"]), 120)


class LandedAt(unittest.TestCase):
    """A LAND the job already holds lets it skip the reviewer, but on a security path only while perms' own file
    records this head and change (review.perms_recorded): no LAND marker, whoever it names."""

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="lander-landed-at.")
        self.addCleanup(shutil.rmtree, tmp, True)
        p = mock.patch.object(R, "PERMS_STATE", tmp)
        p.start()
        self.addCleanup(p.stop)

    def job(self, security=()):
        plan = T.Plan(paid=True, extra={"security": list(security)} if security else {})
        return T.Job(repo="demo", pr=7, head="h" * 40, base_sha="b" * 40, digest="d1", plan=plan)

    def record(self, **kw):
        path = R.perms_reads_path("demo")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump([dict({"repo": "demo", "pr": 7, "head": "h" * 40, "change": "d1"}, **kw)], f)
        os.chmod(path, 0o600)

    def test_a_security_path_needs_perms_record(self):
        plain, door = self.job(), self.job(["config/systemd-user/tunnel.service"])
        for n in ("opus", "x-security", "security", "perms-security-read-2", "perms-security-read"):
            pv = {"verdict": T.LAND, "digest": "d1", "model": n}
            self.assertTrue(L.landed_at(plain, pv), n)
            self.assertFalse(L.landed_at(door, pv), n)   # no record: no marker counts
        self.record(head="c" * 40)
        self.assertFalse(L.landed_at(door, {"verdict": T.LAND, "digest": "d1", "model": "opus"}))
        self.record()
        pv = {"verdict": T.LAND, "digest": "d1", "model": "opus"}
        self.assertTrue(L.landed_at(door, pv))
        for bad in ({}, dict(pv, digest="d0"), dict(pv, verdict=T.HANDBACK_VERDICT)):
            self.assertFalse(L.landed_at(door, bad))
            self.assertFalse(L.landed_at(plain, bad))


class PermsReading(Fixture):
    """dispatch#1296 (10-19): the lane merged a PR on its own read while perms' security read of it still ran. A
    read perms has running (or its hold) holds the merge; a read that ended short of a LAND is a query, so a dead one
    surfaces (perms' read of #1525); none lets it go."""

    def test_a_running_perms_read_holds_the_merge(self):
        from lander import review as R
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        with mock.patch.object(R, "perms_reading", lambda repo, pr, head, digest, carried="": ("perms' read of PR #1 is still running", True)):
            _, lines = self.land()
        j = self.job()
        self.assertEqual((j.state, j.extra.get("hold")), (T.HELD, "box"), lines)
        self.assertIn("still running", j.extra["why"])
        self.assertFalse(self.box().get("merges"))

    def test_no_perms_read_lets_it_merge(self):
        from lander import review as R
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        with mock.patch.object(R, "perms_reading", lambda repo, pr, head, digest, carried="": ("", False)):
            _, lines = self.land()
        self.assertEqual(self.job().state, T.DEPLOY_PENDING, lines)

    def test_a_perms_read_that_ended_short_of_a_land_is_a_query(self):
        from lander import review as R
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        asked = []
        with mock.patch.object(R, "perms_reading", lambda repo, pr, head, digest, carried="": asked.append(digest) or (
                "perms' security read of PR #1 died with no verdict", False)):
            _, lines = self.land()
        j = self.job()
        self.assertEqual(j.state, T.QUERY, lines)
        self.assertIn("died with no verdict", j.extra["why"])
        self.assertEqual(asked, [j.digest])   # the job's change, so an older head's LAND at it can carry
        self.assertFalse(self.box().get("merges"))


if __name__ == "__main__":
    unittest.main()
