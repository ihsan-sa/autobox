"""The lane's cases (U1): intake, the inbox, the job machine, Δ revalidation, the merge and its tree proof, the
door, the board rules, events/times, handback + tick, crash resume.

    python3 -m unittest discover -s core/tests/lander -p 'test_lane.py' -v

Hermetic: every case builds a bare origin + clones under a tmp dir, HOME and every lander path point there, and
PATH starts with a tmp bin of fakes (gh answering from a JSON file and squashing for real onto the bare origin;
cc-config, cc-pause, cc-tier, cc-board, cc, cc-gh-token, systemd-run, systemctl, tmux). The units are stubs.
"""
import contextlib
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
from lander import jobs as J  # noqa: E402
from lander import lane as L  # noqa: E402
from lander import manifest as MF  # noqa: E402
from lander import members as M  # noqa: E402
from lander import tick as TK  # noqa: E402
from lander import types as T  # noqa: E402

REAL_SPAWN_TICK = L.spawn_tick

FAKE = r'''#!PYTHON -SI
import json, os, sys
me, a = os.path.basename(sys.argv[0]), sys.argv[1:]
box_path = os.environ["FAKE_BOX"]
box = json.load(open(box_path))
box.setdefault("calls", []).append([me] + a)
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
    if a[:2] == ["pr", "view"]:
        pr = prs.get(a[2])
        if pr is None:
            out(1, "", "no pull requests found")
        fields = a[a.index("--json") + 1].split(",")
        if "statusCheckRollup" in fields and box.get("checks_denied"):   # a token that reads the PR, not its checks
            out(1, "", box["checks_denied"])
        d = {"state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE", "baseRefName": "main",
             "title": "PR %s" % a[2], "body": ""}
        d.update(pr)
        if d["state"] == "OPEN":
            d["headRefOid"] = g("rev-parse", "refs/heads/" + pr["headRefName"])
        if "files" in fields:
            mb = g("merge-base", "refs/heads/main", d["headRefOid"])
            d["files"] = [{"path": p} for p in g("diff", "--name-only", mb, d["headRefOid"]).splitlines()]
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
            out(1, "", box["merge_fail"])
        head = g("rev-parse", "refs/heads/" + pr["headRefName"])
        pin = a[a.index("--match-head-commit") + 1]
        if pin != head:
            out(1, "", "GraphQL: Head branch was modified. Review and try the merge again.")
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
        out(0, "merged")
    if a[:1] == ["api"] and a[1].endswith("/annotations"):   # repos/<slug>/check-runs/<id>/annotations
        out(0, json.dumps(box.get("annotations", {}).get(a[1].split("/")[-2], [])))
    if a[:1] == ["api"] and ("/actions/jobs/" in a[1] or "/check-runs/" in a[1]):   # one job, one check run
        got = box.get("jobs" if "/actions/jobs/" in a[1] else "check_runs", {}).get(a[1].split("/")[-1])
        out(0, json.dumps(got)) if got is not None else out(1, "", "gh: Not Found (HTTP 404)")
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
if me == "cc-gh-token":   # member_repos: a list for any owner, or {owner: [names]} so the owner asked for counts
    r = box.get("member_repos", [])
    out(0, "\n".join(r.get(a[2] if len(a) > 2 else "", []) if isinstance(r, dict) else r))
if me == "cc":
    if a[0] == "done":
        out(0, json.dumps(box["receipt"]))
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
    def __init__(self, status=None, hook=None, missing=()):
        self.status, self.hook, self.calls, self.missing = dict(status or {}), hook, [], set(missing)

    def run_plan(self, root, m, plan, files, head_tree, base_tree="", *, member="", only=None, **kw):
        """lander.run.run_plan's shape: {name: Outcome}; a name in `missing` is one the manifest lacks."""
        from lander import run as RUN
        out = {}
        for n in plan.checks:
            if only and n not in only:
                continue
            if n in self.missing:
                out[n] = RUN.Outcome(n, T.UNRUNNABLE, "not in the manifest")
                continue
            r = self.run(T.Check(name=n, run="true"), head_tree, f"member:{member}" if member else "box")
            out[n] = RUN.Outcome(n, r.status, "", [r])
        return out

    def run(self, check, tree, where):
        self.calls.append((check.name, tree, where))
        if self.hook:
            self.hook(check.name, len(self.calls))
        return T.Result(check=check.name, tree=tree, status=self.status.get(check.name, T.PASSED), secs=2.0)


class Reviewer:
    def __init__(self, *verdicts):
        self.verdicts, self.calls = list(verdicts), []

    def digest_of(self, root, base, head):
        return "f" * 40

    def review(self, job):
        self.calls.append(("review", job.digest))
        return self.verdicts.pop(0)

    def delta_review(self, job, prior):
        self.calls.append(("delta", prior.verdict))
        return self.verdicts.pop(0)


class Rec:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a: self.calls.append((name,) + a)


def V(verdict, tokens=100, blocking=()):
    return T.Verdict(verdict=verdict, digest="", tokens=tokens, blocking=list(blocking))


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
        with mock.patch.object(L.RUN, "laptop_dest", return_value="ccsuite@r"):
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
        self.assertIn("they are back", e.exception.why)     # the draft went aside for the retry and came back
        self.assertEqual((self.git(self.root, "rev-parse", "HEAD"), said), (head, []))
        self.assertEqual(open(os.path.join(self.root, ".mail-out/queued.eml")).read(), "a queued message\n")
        self.assertEqual(open(os.path.join(self.root, "docs/draft.md")).read(), "old draft\n")
        self.assertEqual(os.listdir(self.aside_root()), [])   # the emptied aside dir is gone too

    def test_a_move_that_fails_puts_back_what_moved_and_moves_nothing(self):
        from lander import deploy as D
        self.write(self.root, {"docs/one.md": "one\n", "docs/two.md": "two\n"})
        merged = self.push("main", {"docs/one.md": "committed\n", "docs/two.md": "committed\n"})
        head = self.git(self.root, "rev-parse", "HEAD")
        real = D.shutil.move

        def move(src, dst):
            if src == os.path.join(self.root, "docs/two.md"):
                raise OSError(28, "No space left on device")
            return real(src, dst)
        with mock.patch.object(D.shutil, "move", move), self.assertRaises(D.Failed) as e:
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
        real = D.shutil.move

        def move(src, dst):
            if dst == os.path.join(self.root, "docs/draft.md"):
                raise OSError(13, "Permission denied")
            return real(src, dst)
        with mock.patch.object(D.shutil, "move", move), self.assertRaises(D.Failed) as e:
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
        argv = self.box()["merges"][0]
        self.assertEqual(argv[:4], ["pr", "merge", "1", "--squash"])
        self.assertIn("--delete-branch", argv)
        self.assertEqual(argv[argv.index("--match-head-commit") + 1], head)
        self.assertEqual(argv[argv.index("--subject") + 1], "row 1 change (#1)")
        self.assertNotIn("--auto", argv)
        self.assertIn(f"stage demo#1 merged sha={head[:12]}", self.log())

    def test_disjoint_delta_merges_without_rerun(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        hook = lambda name, n: self.push("main", {"b/y": "moved\n"}, fresh=True) if n == 1 else None  # noqa: E731
        u, _ = self.land(runner=Runner(hook=hook))
        self.assertEqual([c[0] for c in u["runner"].calls], ["a"])
        j = self.job()
        self.assertEqual(j.state, T.DEPLOY_PENDING)
        self.assertEqual(j.extra["rerun"], [])
        self.assertNotIn("tip", j.extra)            # the proof held: merge-tree on the main read before the call
        self.assertEqual(len(self.box()["merges"]), 1)

    def test_overlapping_delta_reruns_only_owned(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n"})
        J.submit("demo", 1)
        hook = lambda name, n: self.push("main", {"a/other": "m\n"}) if n == 2 else None  # noqa: E731
        u, _ = self.land(runner=Runner(hook=hook))
        self.assertEqual([c[0] for c in u["runner"].calls], ["a", "b", "a"])
        self.assertNotEqual(u["runner"].calls[0][1], u["runner"].calls[2][1])   # rerun on the new merge tree
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)

    def test_checks_grew_runs_the_new_ones(self):
        self.pr(1, {"a/x": "n\n"})
        J.submit("demo", 1)
        planner = Planner()

        def hook(name, n):
            if n == 1:
                self.push("main", {"b/y": "moved\n"})
                planner.owners["new"] = "a/"
        u, _ = self.land(planner=planner, runner=Runner(hook=hook))
        self.assertEqual([c[0] for c in u["runner"].calls], ["a", "new"])
        self.assertEqual(self.job().extra["rerun"], ["new"])

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
        with mock.patch.object(MF, "FALLBACK_DIR", fb):
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

    def test_reads_cap_goes_to_planning(self):
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
        j = self.job()
        self.assertEqual((j.state, j.reads_used), (T.QUERY, 2))
        # the prior verdict is not carried by the lane: the reviewer finds it among the box's own PR markers
        self.assertEqual([c[0] for c in rv.calls], ["review"])
        self.assertEqual(u["cards"].calls[0][3], "planning")

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
            self.set_box(calls=[], timers="Sun 2026-09-27 lander-tick-demo-1790000000.timer "
                                          "lander-tick-demo-1790000000.service")
            TK.cmd_tick(["--rearm"])
        arms = [c for c in self.box()["calls"] if c[0] == "systemd-run"]
        self.assertEqual([re.sub(r"-\d+$", "", c[3]) for c in arms], ["--unit=lander-tick-other"])


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
        self.assertNotIn("merge_attempt", j.extra)
        ok, text = GH.merge(self.root, 1, "x" * 40, "t")
        self.assertFalse(ok)
        self.set_box(merge_fail="--auto: auto-merge is not allowed")
        self.assertIn("no auto-merge was armed", GH.merge(self.root, 1, "x" * 40, "t")[1])

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
                mock.patch("lander.cards.PASSWD_HOME", "/home/owner"):
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
        with mock.patch("lander.cards.PASSWD_HOME", "/home/owner"):
            env = L.tick_env(dict(hostile, LANG="C.UTF-8", LC_CTYPE="C.UTF-8", USER="owner", HOME="/tmp/h"))
        self.assertEqual([k for k in hostile if k in env and k != "XDG_RUNTIME_DIR"], [])
        self.assertNotEqual(env.get("XDG_RUNTIME_DIR"), "/tmp/own-run")
        self.assertEqual((env["LANG"], env["LC_CTYPE"], env["USER"], env["HOME"]),
                         ("C.UTF-8", "C.UTF-8", "owner", "/home/owner"))

    def test_tick_path_puts_the_system_dirs_first(self):
        # a gh, git or claude a worker drops in ~/bin or ~/.local/bin must not shadow the system's (#862 review reads)
        with mock.patch("lander.cards.PASSWD_HOME", "/home/owner"):
            dirs = L.tick_path().split(":")
        self.assertEqual(dirs[:3], ["/usr/local/bin", "/usr/bin", "/bin"])
        self.assertEqual(sorted(dirs[3:]), ["/home/owner/.local/bin", "/home/owner/bin"])

    def test_pr_facts_names_the_repo(self):
        # a GH_REPO of the caller's would point gh pr view at a decoy PR: -R names the lander's own slug
        seen = []
        ran = mock.Mock(side_effect=lambda argv, **kw: seen.append(argv) or mock.Mock(returncode=0, stdout="{}",
                                                                                     stderr=""))
        with mock.patch.object(GH, "slug", lambda root: "o/demo"), mock.patch.object(GH.subprocess, "run", ran):
            GH.pr_facts(self.root, 5, "state")
            GH.pr_files(self.root, 5)
        self.assertEqual([a[a.index("-R") + 1] if "-R" in a else "" for a in seen], ["o/demo", "o/demo"])
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
        # #1's first check, #2's only one, #1's rest, then #1's `a` again: #2's merge moved a/ under it (the Δ re-plan)
        self.assertEqual([c[0] for c in u["runner"].calls], ["a", "a", "b", "c", "a"])
        self.assertEqual((self.job(1).state, self.job(2).state), (T.DEPLOY_PENDING, T.DEPLOY_PENDING))

    def test_with_no_heavy_plan_the_queue_keeps_its_order(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})
        self.pr(2, {"docs/r.md": "n\n", "a/x2": "n\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        with mock.patch.object(L, "SMALL_CHECKS", 3), one_slot():   # three checks is still small: oldest first
            u, _ = self.land(runner=first_check_waits(self, lambda: self.job(2).state != T.QUEUED))
        self.assertEqual(self.merged_order(), [1, 2])
        # #1's suite, then #2's `a`, and `a` again: #1's merge moved a/ under #2 while its check ran (the Δ re-plan)
        self.assertEqual([c[0] for c in u["runner"].calls], ["a", "b", "c", "a", "a"])

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
        # heavy job gets each free slot until its suite is done; #1's merge moved b/ under #2, so its `b` runs again
        self.assertEqual([c[0] for c in u["runner"].calls], ["a", "b", "b", "c", "b"])


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

    def test_a_pr_overlapping_one_in_flight_waits_and_is_planned_after_it_merges(self):
        # design: "Two changes that overlap from the start don't both burn CPU; the later one waits"
        self.pr(1, {"a/x": "n\n", "b/y": "n\n"})
        self.pr(2, {"b/y": "n\n"})
        self.pr(3, {"c/z": "n\n"})   # shares nothing: it does not wait
        for n in (1, 2, 3):
            J.submit("demo", n)
        planner = Planner()
        u, lines = self.land(planner=planner, runner=first_check_waits(self, lambda: self.job(3).state != T.QUEUED))
        self.assertIn("[demo] PR #2 waits for PR #1: both change b/y", lines)
        self.assertNotIn("PR #3 waits", " ".join(lines))
        self.assertEqual(self.merged_order().index(1) < self.merged_order().index(2), True)
        tip1 = self.job(1).extra["tip_sha"]
        # planned first from #1's merge, never from main before it (a Δ re-plan may follow if #3 merges between)
        self.assertEqual([c[0] for c in planner.calls if c[2] == ("b/y",)][0], tip1)
        self.assertEqual(len([ln for ln in lines if "PR #2 waits" in ln]), 1)            # said once
        self.assertEqual(self.log().count("stage demo#2 lane"), 1)                         # staged once
        self.assertEqual(self.job(2).state, T.DEPLOY_PENDING)

    def test_an_older_parked_pr_is_not_jumped_by_a_newer_one_sharing_a_file(self):
        # review 2026-09-29: #2 (a/x, b/y) parks behind #1 (a/x); #3 (b/y only) must not be planned ahead of #2,
        # or #2 waits on #3, then on the next newer PR, for as long as they arrive
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"a/x": "n\n", "b/y": "n\n"})
        self.pr(3, {"b/y": "n\n"})
        for n in (1, 2, 3):
            J.submit("demo", n)
        _, lines = self.land(runner=first_check_waits(self, lambda: self.job(3).extra.get("parked_since")))
        self.assertIn("[demo] PR #2 waits for PR #1: both change a/x", lines)
        self.assertIn("[demo] PR #3 waits for PR #2: both change b/y", lines)
        self.assertEqual(self.merged_order(), [1, 2, 3])
        self.assertEqual([self.job(n).state for n in (1, 2, 3)], [T.DEPLOY_PENDING] * 3)
        self.assertNotIn("parked", self.job(2).extra)

    def facts_calls(self, pr):
        """Run the lane counting its `gh pr view` reads of PR `pr` from queued() (FIELDS)."""
        real, n = GH.pr_facts, [0]

        def counting(root, num, fields, *a, **k):
            if int(num) == pr and fields == L.FIELDS:
                n[0] += 1
            return real(root, num, fields, *a, **k)
        with mock.patch.object(GH, "pr_facts", counting):
            _, lines = self.land(planner=Planner(owners={"a": "a/", "b": "b/", "c": "c/", "d": "d/", "e": "e/"}),
                                 runner=first_check_waits(self, lambda: self.job(pr).extra.get("parked_since"), 0.3))
        return n[0], lines

    def test_a_parked_pr_is_not_read_from_github_at_every_wake(self):
        # review 2026-09-29: each wake re-ran queued() for every parked job, and many parked jobs reach GH backoff
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n", "d/w": "n\n", "e/v": "n\n"})   # five checks: five wakes
        self.pr(2, {"a/x": "n\n"})
        for n in (1, 2):
            J.submit("demo", n)
        calls, lines = self.facts_calls(2)
        self.assertIn("[demo] PR #2 waits for PR #1: both change a/x", lines)
        self.assertEqual(calls, 2)   # the read that parked it, and the read before it is planned
        self.assertEqual(self.merged_order(), [1, 2])

    def test_a_parked_pr_is_read_again_once_its_read_is_stale(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n", "d/w": "n\n", "e/v": "n\n"})
        self.pr(2, {"a/x": "n\n"})
        for n in (1, 2):
            J.submit("demo", n)
        with mock.patch.object(L, "PARK_FRESH", 0):
            calls, _ = self.facts_calls(2)
        self.assertGreater(calls, 2)

    def test_a_parked_pr_whose_head_moved_is_planned_and_pinned_at_the_new_head(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n"})
        self.pr(2, {"a/x": "n\n"})
        for n in (1, 2):
            J.submit("demo", n)
        new = []

        def hook(name, n):   # while #2 is parked on #1, a push moves #2 off a/x
            if n == 1:
                end = time.time() + 10
                while not (J.load("demo", 2).extra or {}).get("parked") and time.time() < end:
                    time.sleep(0.02)
                new.append(self.push("track/row-2", {"c/z": "n\n"}))
        planner = Planner()
        _, lines = self.land(planner=planner, runner=Runner(hook=hook))
        self.assertIn("[demo] PR #2 waits for PR #1: both change a/x", lines)
        self.assertEqual(self.job(2).head, new[0])
        self.assertEqual([c[1] for c in planner.calls if c[2] == ("c/z",)], [new[0]])
        pin = self.box()["merges"][-1]
        self.assertEqual(pin[pin.index("--match-head-commit") + 1], new[0])

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
                mock.patch.object(L, "spawn_lane", lambda repo, rel: (True, "unit x")):
            u, lines = self.land(runner=Runner(hook=hook))
        self.assertEqual([c[0] for c in u["runner"].calls], ["a"])   # nothing new after the promote
        self.assertEqual(sorted(self.job(1).results), ["a"])           # the one in flight is kept
        self.assertEqual(self.job(1).state, T.CHECKING)
        self.assertTrue(any("this lane takes no new job" in ln for ln in lines))


class Express(Fixture):
    """A check a mergeable PR runs again only because main moved goes at once, beside the box slot another PR's check
    holds (2026-10-02/03: #905 went back to checking four times for a 0 s rerun that then waited hours behind
    half-hour suites, and main moved again meanwhile)."""

    def setUp(self):
        super().setUp()
        q = mock.patch.object(L, "POLL", 0.05)
        q.start()
        self.addCleanup(q.stop)

    MANIFEST = "".join(f'[[check]]\nname = "{n}"\nrun = "{n}/run.sh"\npaths = ["{n}/**"]\nclass = "static"\n\n'
                       for n in "abc")

    def race(self, wait=20, pr2=None):
        """#2's `b` and #1's `a` start side by side; #1's holds its slot (a Gate) until #2 merges. At #2's first CI
        look the box narrows to one slot and main moves under b/, so #2 must run `b` again. pr2: more files #2
        changes. -> the runner"""
        self.push("main", {"tests/LANDING.toml": self.MANIFEST})
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n", **(pr2 or {})})
        J.submit("demo", 2)
        J.submit("demo", 1)
        runner = Gate(lambda: (self.job(1).extra or {}).get("tree"), wait=wait)
        narrow, real_ci, real_merge = [], L.Lane.ci_green, GH.merge

        def ci_green(lane, job):
            if job.pr == 2 and not narrow:
                narrow.append(True)
                self.push("main", {"b/z": "main moved\n"})
            return real_ci(lane, job)

        def merge(*a, **k):
            got = real_merge(*a, **k)
            runner.release.set()
            return got
        with mock.patch.object(L.Lane, "width", lambda lane: 1 if narrow else 2), \
                mock.patch.object(L.Lane, "ci_green", ci_green), mock.patch.object(GH, "merge", merge):
            self.land(runner=runner)
        self.assertEqual([c[0] for c in runner.calls].count("b"), 2)
        self.assertIn("main moved: rerun b", [h.get("why") for h in self.job(2).history])
        return runner

    def merged_order(self):
        return [int(argv[2]) for argv in self.box()["merges"]]

    def test_a_rerun_after_main_moved_runs_beside_the_slot_a_check_holds(self):
        runner = self.race()
        self.assertFalse(runner.timed_out, "#2's rerun of b waited for #1's slot")
        self.assertEqual(self.merged_order(), [2, 1])
        self.assertEqual(self.job(2).extra["express"]["checks"], ["b"])

    def test_a_full_suite_rerun_still_waits_for_a_slot(self):
        with mock.patch.object(L, "FULL_CHECKS", ("b",)):
            runner = self.race(wait=1)
        self.assertTrue(runner.timed_out, "#2's rerun of a full suite took no slot")
        self.assertEqual(self.merged_order(), [1, 2])   # #1's check let the slot go first
        self.assertEqual(self.job(2).extra["express"]["checks"], [])

    def test_no_express_under_memory_pressure(self):
        # admission keeps one slot under memory pressure because parallel checks ran the box out of memory: an
        # express run would be a second check beside it
        with mock.patch.object(L.A, "mem_loaded", return_value=True):
            runner = self.race(wait=1)
        self.assertTrue(runner.timed_out, "#2's rerun went express under memory pressure")
        self.assertEqual(self.merged_order(), [1, 2])

    def test_a_long_or_unrecorded_check_is_not_express(self):
        with mock.patch.object(L, "EXPRESS_SECS", -1):   # b's green run (0 s) is longer than this
            runner = self.race(wait=1)
        self.assertTrue(runner.timed_out, "#2's rerun of a long check took no slot")
        self.assertEqual(self.merged_order(), [1, 2])
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

    def test_a_transitive_chain_parked_past_the_cap_is_planned_and_a_young_one_still_waits(self):
        # #3 waits on #2, which waits on #1: #3 shares no file with #1. Parked a day, both are planned from main
        self.pr(1, {"a/x": "n\n", "c/z": "n\n"})
        self.pr(2, {"a/x": "n\n", "b/y": "n\n"})
        self.pr(3, {"b/y": "n\n"})
        self.pr(4, {"c/z": "n\n"})   # parked only now: it still waits
        for n in (1, 2, 3, 4):
            J.submit("demo", n)
        self.seed(L.WAIT_CAP + 60, "parked_since", 2, 3)
        main = self.origin_rev("main")
        planner = Planner()

        def hook(name, n):   # #1's first check runs until #4 has had its turn, so #1 is in flight throughout
            if n == 1:
                end = time.time() + 10
                while not (self.job(4).extra.get("parked_since") or self.job(4).state != T.QUEUED) \
                        and time.time() < end:
                    time.sleep(0.02)
        _, lines = self.land(planner=planner, runner=Runner(hook=hook))
        self.assertNotIn("PR #2 waits", " ".join(lines))
        self.assertNotIn("PR #3 waits", " ".join(lines))
        self.assertIn("[demo] PR #4 waits for PR #1: both change c/z", lines)
        self.assertEqual(self.merged_order(), [2, 3, 1, 4])   # both landed while #1, the chain's root, still ran
        self.assertEqual([c[0] for c in planner.calls if c[2] == ("a/x", "b/y")][0], main)
        self.assertEqual([self.job(n).state for n in (1, 2, 3, 4)], [T.DEPLOY_PENDING] * 4)
        self.assertNotIn("parked_since", self.job(3).extra)   # planned: a later park starts its own day

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

    def test_the_first_park_writes_one_queue_log_line(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})   # three checks: several wakes while #2 waits
        self.pr(2, {"a/x": "n\n"})
        self.pr(3, {"b/y2": "n\n"})   # not parked: no line
        for n in (1, 2, 3):
            J.submit("demo", n)
        _, lines = self.land(planner=Planner(owners={"a": "a/", "b": "b/", "c": "c/"}),
                             runner=first_check_waits(self, lambda: self.job(3).state != T.QUEUED))
        self.assertIn("[demo] PR #2 waits for PR #1: both change a/x", lines)
        self.assertEqual(self.log().count("stage demo#2 parked on=1"), 1)
        self.assertNotIn("stage demo#3 parked", self.log())
        self.assertEqual(self.job(2).state, T.DEPLOY_PENDING)


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
    for 40+ min; ai-ee #99 checked a stale head for 50 min after a push). Each case queues its own PRs."""

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

    def test_a_pr_merged_mid_check_stops_its_checks_ends_merged_and_unparks_the_next(self):
        self.pr(1, {"a/x": "one\n"})
        self.pr(2, {"a/x": "two\n"})   # shares a/x with #1, so it parks on it
        J.submit("demo", 1)
        J.submit("demo", 2)
        def merge_once_two_parks():   # GitHub merges #1 only after #2 has parked on it
            end = time.time() + 10
            while not (self.job(2).extra or {}).get("parked") and time.time() < end:
                time.sleep(0.02)
            self.merged_on_github.set()
        runner = Stoppable(merge_once_two_parks)
        with mock.patch.object(L, "RECHECK_SECS", 1):
            _, lines = self.land(runner=runner)
        self.assertTrue(runner.stopped, "#1's check ran on after its PR merged")
        j1, j2 = self.job(1), self.job(2)
        self.assertEqual((j1.state, j2.state), (T.DEPLOY_PENDING, T.DEPLOY_PENDING))
        self.assertEqual([h["state"] for h in j1.history][-4:], [T.CHECKING, T.QUEUED, T.MERGED, T.DEPLOY_PENDING])
        self.assertIn("the PR is merged while it was checking", j1.history[-3]["why"])
        self.assertEqual(j1.history[-2].get("by"), "before")
        self.assertEqual([int(a[2]) for a in self.box()["merges"]], [2])   # the lane never merged #1 itself
        self.assertIn("[demo] PR #2 waits for PR #1: both change a/x", lines)
        self.assertIn("[demo] PR #1: check a finished for a head or base the job has left; not recorded", lines)
        self.assertEqual(sorted(j2.results), ["a"])   # #2's check was not stopped: it ran and was recorded

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


if __name__ == "__main__":
    unittest.main()
