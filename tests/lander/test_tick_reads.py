"""What a round of the per-repo tick units costs GitHub's REST hour: each repo's tick reads its own handed-back
watches only (2026-10-23: each of ~18 units read every repo's, about 9,000 calls an hour), and a PR read again is a
conditional GET that GitHub answers 304, which costs no quota.

gh is a counting fake on PATH that speaks REST with -i's headers; the watches and the ETag store are real files under
a temp dir. Run:
python3 -m unittest discover -s core/tests/lander -t core/tests/lander -p 'test_tick_reads.py'
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from lander import events as E  # noqa: E402
from lander import gh as GH  # noqa: E402
from lander import git as G  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import tick as TK  # noqa: E402

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, re, sys
a = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(json.dumps(a) + "\n")
m = re.fullmatch(r"repos/o/(\w+)/pulls/(\d+)", a[1]) if a[:1] == ["api"] and len(a) > 1 else None
if not m or "-i" not in a:
    sys.exit(1)
if m.group(2) == "404":   # an error reply over HTTP/1.1: its "Connection:" header is no network failure
    print('HTTP/1.1 404 Not Found\r\nConnection: keep-alive\r\n\r\n{"message": "Not Found"}')
    print("gh: Not Found (HTTP 404)", file=sys.stderr)
    sys.exit(1)
state = json.load(open(os.environ["FAKE_GH_STATE"])) if os.path.exists(os.environ["FAKE_GH_STATE"]) else {}
v = state.get(a[1], {"state": "open", "v": 1})
tag = f'"e-{m.group(1)}-{m.group(2)}-{v["v"]}"'
if f"If-None-Match: {tag}" in a:
    print("HTTP/1.1 304 Not Modified\r\nConnection: keep-alive\r\nEtag: " + tag + "\r\n\r\n", end="")
    sys.exit(1)   # gh's exit on a status it does not call success; the 304 is read from the headers
print("HTTP/2.0 200 OK\r\nEtag: " + tag + "\r\n\r\n" + json.dumps(
    {"number": int(m.group(2)), "state": v["state"], "merged_at": v.get("merged_at"),
     "head": {"sha": v.get("head", "h" * 40), "ref": "b"}}))
'''


class TickReads(unittest.TestCase):
    REPOS = ("alpha", "beta", "gamma")
    PRS = (1, 2)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lander-reads.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        land, bin_ = os.path.join(self.tmp, "land"), os.path.join(self.tmp, "bin")
        os.makedirs(bin_)
        with open(os.path.join(bin_, "gh"), "w") as f:
            f.write(FAKE_GH)
        os.chmod(os.path.join(bin_, "gh"), 0o755)
        self.log = os.path.join(self.tmp, "gh.log")
        p = mock.patch.dict(os.environ, {"CC_LAND_STATE": land, "CC_LANDER_STATE": land, "HOME": self.tmp,
                                         "CC_DEV": os.path.join(self.tmp, "dev"), "FAKE_GH_LOG": self.log,
                                         "FAKE_GH_STATE": os.path.join(self.tmp, "gh-state.json"),
                                         "PATH": bin_ + os.pathsep + os.environ["PATH"]})
        p.start()
        self.addCleanup(p.stop)
        self.remote = "h" * 40
        for patch in (mock.patch.object(GH, "slug", lambda root: "o/" + os.path.basename(root)),
                      mock.patch.object(G, "remote_head", lambda root, branch, env=None: self.remote)):
            patch.start()
            self.addCleanup(patch.stop)
        for repo in self.REPOS:
            os.makedirs(os.path.join(self.tmp, "dev", repo, ".git"))
            for pr in self.PRS:   # handed back at head h…: no push, so every round keeps the watch
                J.write_atomic(f"{J.handed_dir()}/{repo}-{pr}.json", {"repo": repo, "pr": pr, "head": "h" * 40,
                                                                     "branch": "b", "until": E.stamp(9999999999)})

    def reads(self):
        """Each PR GET gh was asked for this round, as (pr path, conditional)."""
        with open(self.log) as f:
            got = [json.loads(ln) for ln in f]
        os.unlink(self.log)
        return [(a[1], any(x.startswith("If-None-Match") for x in a)) for a in got if a[0] == "api"]

    def round(self):
        """One tick round: every repo's own unit, as the per-repo timers run it (`lander tick --repo R`)."""
        for repo in self.REPOS:
            self.assertEqual(TK.sweep_handed(repo), [])

    def test_a_round_reads_each_pr_once_and_a_read_again_is_a_304(self):
        self.round()
        first = self.reads()
        every = sorted(f"repos/o/{r}/pulls/{n}" for r in self.REPOS for n in self.PRS)
        self.assertEqual(sorted(p for p, _ in first), every)   # each PR once: 6 GETs, not 3 units x 6 = 18
        self.assertFalse(any(c for _, c in first))             # nothing kept yet, so nothing conditional
        self.round()
        again = self.reads()
        self.assertEqual(sorted(p for p, _ in again), every)
        self.assertTrue(all(c for _, c in again))              # each one a conditional GET, answered 304: free
        self.assertFalse(os.path.exists(GH.backoff_path()))   # a 304's exit 1 and "Connection" header set no backoff
        self.assertEqual(len(os.listdir(J.handed_dir())), 6)    # the kept body still says open: every watch stays

    def change(self, path, **v):
        f = os.environ["FAKE_GH_STATE"]
        state = J.read_json(f) or {}
        state[path] = v
        J.write_atomic(f, state)

    def test_a_cached_merged_body_is_asked_again(self):
        """Opus read: a repo deleted and made again under its name has a new #1, which a kept merged copy of the old
        #1 would have called MERGED without asking."""
        root, path = os.path.join(self.tmp, "dev", "alpha"), "repos/o/alpha/pulls/1"
        self.change(path, state="closed", merged_at="2026-10-23T03:00:00Z", v=1)
        self.assertEqual(GH.pr_facts(root, 1, "state")[0], {"state": "MERGED"})
        self.reads()
        self.change(path, state="open", v=2)                   # the repo made again: its #1 is open
        self.assertEqual(GH.pr_facts(root, 1, "state")[0], {"state": "OPEN"})
        self.assertEqual(self.reads(), [(path, True)])         # asked, with the kept ETag

    def test_a_200_after_a_kept_copy_replaces_it(self):
        root, path = os.path.join(self.tmp, "dev", "alpha"), "repos/o/alpha/pulls/1"
        self.assertEqual(GH.pr_facts(root, 1, "headRefOid,state")[0], {"headRefOid": "h" * 40, "state": "OPEN"})
        self.change(path, state="open", head="n" * 40, v=2)   # a new head
        self.assertEqual(GH.pr_facts(root, 1, "headRefOid,state")[0], {"headRefOid": "n" * 40, "state": "OPEN"})
        self.change(path, state="closed", head="n" * 40, v=3)  # then closed
        self.assertEqual(GH.pr_facts(root, 1, "state")[0], {"state": "CLOSED"})
        self.reads()
        self.assertEqual(GH.pr_facts(root, 1, "state")[0], {"state": "CLOSED"})
        self.assertEqual(self.reads(), [(path, True), (path, False)])   # a 304 on a closed copy is asked again plainly

    def kept(self, path):
        d = f"{J.landq()}/gh-etag"
        os.makedirs(d, exist_ok=True)
        return f"{d}/{hashlib.sha1(path.encode()).hexdigest()}.json"

    def test_a_planted_merged_copy_with_a_current_etag_settles_nothing(self):
        """perms' read of #1908: anyone who can write the kept file can give it the current ETag, and GitHub's 304
        would then vouch for a merged body it never sent."""
        root, path = os.path.join(self.tmp, "dev", "alpha"), "repos/o/alpha/pulls/1"
        J.write_atomic(self.kept(path), {"etag": '"e-alpha-1-1"', "body": {"state": "closed", "merged_at": "x"}})
        self.assertEqual(GH.pr_facts(root, 1, "state")[0], {"state": "OPEN"})
        self.assertEqual(self.reads(), [(path, True), (path, False)])

    def test_a_linked_kept_file_is_no_copy(self):
        root, path = os.path.join(self.tmp, "dev", "alpha"), "repos/o/alpha/pulls/1"
        planted = os.path.join(self.tmp, "planted.json")
        J.write_atomic(planted, {"etag": '"e-alpha-1-1"', "body": {"state": "open", "head": {"sha": "p" * 40}}})
        os.symlink(planted, self.kept(path))
        self.assertEqual(GH.pr_facts(root, 1, "headRefOid")[0], {"headRefOid": "h" * 40})
        self.assertEqual(self.reads(), [(path, False)])        # not read, so asked plainly

    def test_a_fifo_kept_file_is_no_copy_and_no_hang(self):
        root, path = os.path.join(self.tmp, "dev", "alpha"), "repos/o/alpha/pulls/1"
        f = self.kept(path)
        os.mkfifo(f)
        got = []
        t = threading.Thread(target=lambda: got.append(GH.pr_facts(root, 1, "state")[0]), daemon=True)
        t.start()
        t.join(10)
        if t.is_alive():   # the read blocked on the pipe: let it go before failing
            os.close(os.open(f, os.O_WRONLY | os.O_NONBLOCK))
            t.join(10)
            self.fail("get() hung on a FIFO kept file")
        self.assertEqual(got, [{"state": "OPEN"}])
        self.assertEqual(self.reads(), [(path, False)])

    def test_an_error_replys_headers_set_no_backoff(self):
        rc, _, _ = GH.get(os.path.join(self.tmp, "dev", "alpha"), "repos/o/alpha/pulls/404")
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(GH.backoff_path()))   # "Connection" would match "connect"

    def test_a_kept_answer_a_day_old_is_pruned(self):
        GH.get(os.path.join(self.tmp, "dev", "alpha"), "repos/o/alpha/pulls/1")
        d = f"{J.landq()}/gh-etag"
        (f,) = os.listdir(d)
        GH.prune_kept()
        self.assertEqual(os.listdir(d), [f])                   # fresh: kept
        os.utime(f"{d}/{f}", (0, 0))
        GH.prune_kept()
        self.assertEqual(os.listdir(d), [])

    def test_a_handed_watch_alone_arms_its_repo_and_its_push_is_seen(self):
        """Opus read: a repo arms its tick only for what waits() finds, so with each tick sweeping its own repo's
        watches, a watch in a repo with nothing else to wait on (dispatch, 10-23) was never swept."""
        self.assertEqual(TK.waits("alpha"), [TK.TICK_SECS])
        self.remote = "p" * 40                                 # pushed after it was handed back
        lines = TK.sweep_handed("alpha")
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("pushed after it was handed back" in ln for ln in lines))
        # its watches ended, but the push's request waits in the inbox for the next tick's drain: one tick more
        self.assertEqual(TK.waits("alpha"), [TK.TICK_SECS])
        with J.lane_lock("alpha"):
            J.drain("alpha")
        self.assertEqual(TK.waits("alpha"), [])                # drained: nothing left to wake for

if __name__ == "__main__":
    unittest.main()
