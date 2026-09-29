"""The lane's cases (U1): intake, the inbox, the job machine, Δ revalidation, the merge and its tree proof, the
door, the board rules, events/times, handback + tick, crash resume.

    python3 -m unittest discover -s core/tests/lander -p 'test_lane.py' -v

Hermetic: every case builds a bare origin + clones under a tmp dir, HOME and every lander path point there, and
PATH starts with a tmp bin of fakes (gh answering from a JSON file and squashing for real onto the bare origin;
cc-config, cc-pause, cc-tier, cc-board, cc, cc-gh-token, systemd-run, systemctl, tmux). The units are stubs.
"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

CORE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from lander import events as E  # noqa: E402
from lander import gh as GH  # noqa: E402
from lander import git as G  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import lane as L  # noqa: E402
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
if me == "cc-gh-token":
    out(0, "\n".join(box.get("member_repos", [])))
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
        env = {"HOME": self.home, "CC_LANDER_STATE": f"{self.home}/.cc/state/land", "CC_BIN": self.bindir,
               "CC_DEV": f"{self.home}/dev", "CC_BOARDS": f"{self.home}/.cc/boards",
               "CC_MEMBERS": f"{self.home}/.cc/members", "PATH": self.bindir + os.pathsep + os.environ["PATH"],
               "FAKE_BOX": self.box_path, **GIT_ENV, "LANDER_TMUX": f"{self.bindir}/tmux",
               "LANDER_SYSTEMD_RUN": f"{self.bindir}/systemd-run", "LANDER_SYSTEMCTL": f"{self.bindir}/systemctl"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for k in ("GH_TOKEN", "CC_SLACK_ALIAS"):
            os.environ.pop(k, None)
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
        u, lines = self.land(runner=runner, reviewer=Reviewer(V("LAND"), V("LAND")))
        # the job in flight finished on the release it started on
        self.assertEqual(self.job(1).state, T.DEPLOY_PENDING)
        self.assertEqual([c[0] for c in runner.calls], ["a"])
        # the next job was not taken up here; a lane from the new release was started, after the lock was let go
        self.assertEqual(self.job(2).state, T.QUEUED)
        self.assertEqual(self.spawned, [("demo", self.rels["bbbb"], 0)])
        self.assertIn("this lane takes no new job", lines[-1])
        self.assertIn("lane-switch demo", self.log())
        self.assertFalse(os.path.exists(J.lane_file("demo", "running")))
        # the lane on the new release takes #2
        self.mine = self.rels["bbbb"]
        self.land(runner=runner, reviewer=Reviewer(V("LAND")))
        self.assertEqual(self.job(2).state, T.DEPLOY_PENDING)
        self.assertEqual(len(self.spawned), 1)

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
                mock.patch.object(TK, "tip_and_deploy", lambda r, u: []), contextlib.redirect_stdout(io.StringIO()):
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

    def test_usage_refusals(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(TK.cmd_tick(["--bogus"]), 2)
            self.assertEqual(L.cmd_lane(["bad name"]), 2)
            self.assertEqual(E.cmd_times(["--days"]), 2)
        self.assertEqual(J.repo_root("demo"), self.root)


class SmallFirst(Fixture):
    """A small PR waits for at most one check of a full suite, never the suite (owner, 2026-09-28: #779, one line
    and a minute of checks, waited behind ~20 full-suite PRs). Here a plan of more than one check is heavy."""

    def merged_order(self):
        return [int(argv[2]) for argv in self.box()["merges"]]

    def test_a_small_pr_queued_behind_a_full_suite_merges_first(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})   # three checks: heavy
        self.pr(2, {"docs/r.md": "n\n", "a/x2": "n\n"})           # one check: small
        J.submit("demo", 1)
        J.submit("demo", 2)
        with mock.patch.object(L, "SMALL_CHECKS", 1):
            _, lines = self.land()
        self.assertEqual(self.merged_order(), [2, 1])
        self.assertIn("[demo] PR #1 steps aside for PR #2 (0 of 3 checks done)", lines)
        self.assertEqual((self.job(1).state, self.job(2).state), (T.DEPLOY_PENDING, T.DEPLOY_PENDING))

    def test_with_no_heavy_plan_the_queue_keeps_its_order(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})
        self.pr(2, {"docs/r.md": "n\n", "a/x2": "n\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        with mock.patch.object(L, "SMALL_CHECKS", 3):              # three checks is still small: nobody steps aside
            _, lines = self.land()
        self.assertEqual(self.merged_order(), [1, 2])
        self.assertFalse([ln for ln in lines if "steps aside" in ln])

    def test_a_small_pr_queued_mid_suite_goes_in_after_the_running_check(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})
        self.pr(2, {"a/x2": "n\n"})
        J.submit("demo", 1)
        hook = lambda name, n: J.submit("demo", 2) if n == 1 else None  # noqa: E731
        with mock.patch.object(L, "SMALL_CHECKS", 1):
            u, lines = self.land(runner=Runner(hook=hook))
        self.assertEqual(self.merged_order(), [2, 1])
        self.assertIn("[demo] PR #1 steps aside for a new request (1 of 3 checks done)", lines)
        self.assertEqual([c[0] for c in u["runner"].calls][:2], ["a", "a"])   # #1's first check, then #2's only one
        self.assertEqual(self.job(1).state, T.DEPLOY_PENDING)

    def test_a_plan_with_the_full_suite_is_heavy_however_few_its_checks(self):
        # one check, but it is check-sh (the whole suite): a count is not a cost
        planner = Planner(owners={"check-sh": "a/", "b": "b/"})
        self.pr(1, {"a/x": "n\n"})
        self.pr(2, {"b/y": "n\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        _, lines = self.land(planner=planner)   # SMALL_CHECKS stays at its default of 5
        self.assertEqual(self.merged_order(), [2, 1])
        self.assertIn("[demo] PR #1 steps aside for PR #2 (0 of 1 checks done)", lines)
        self.assertTrue(L.Lane.heavy(self.job(1)))
        self.assertFalse(L.Lane.heavy(self.job(2)))

    def test_a_heavy_pr_steps_aside_for_a_heavy_request_in_the_inbox_and_goes_first_after(self):
        # the request lands in the inbox mid-suite: #1 steps aside once so it is drained and planned; #2 is heavy
        # and behind, so it hands straight back and #1 finishes its suite first — the lane does not ping-pong
        self.pr(1, {"a/x": "n\n", "b/y": "n\n", "c/z": "n\n"})
        self.pr(2, {"b/y2": "n\n", "c/z2": "n\n"})
        J.submit("demo", 1)
        hook = lambda name, n: J.submit("demo", 2) if n == 1 else None  # noqa: E731
        with mock.patch.object(L, "SMALL_CHECKS", 1):
            u, lines = self.land(runner=Runner(hook=hook))
        self.assertIn("[demo] PR #1 steps aside for a new request (1 of 3 checks done)", lines)
        self.assertIn("[demo] PR #2 steps aside for PR #1 (0 of 2 checks done)", lines)
        self.assertEqual(len([ln for ln in lines if "PR #1 steps aside" in ln]), 1)
        self.assertEqual(self.merged_order(), [1, 2])
        self.assertEqual([c[0] for c in u["runner"].calls][:3], ["a", "b", "c"])   # #1's whole suite, unbroken

    def test_two_heavy_prs_keep_their_order(self):
        self.pr(1, {"a/x": "n\n", "b/y": "n\n"})
        self.pr(2, {"b/y2": "n\n", "c/z": "n\n"})
        J.submit("demo", 1)
        J.submit("demo", 2)
        with mock.patch.object(L, "SMALL_CHECKS", 1):
            u, lines = self.land()
        self.assertEqual(self.merged_order(), [1, 2])
        # #2 is planned (that is how the lane learns it is heavy), then hands back before running any check
        self.assertIn("[demo] PR #2 steps aside for PR #1 (0 of 2 checks done)", lines)
        self.assertEqual([c[0] for c in u["runner"].calls][:2], ["a", "b"])   # #1's whole suite first


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


if __name__ == "__main__":
    unittest.main()
