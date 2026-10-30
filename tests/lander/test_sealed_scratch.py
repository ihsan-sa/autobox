"""What a sealed read writes to disk: on a repo with a large history, a read after the first adds only the new
objects to the lander's cache and next to nothing to its scratch dir, and a scratch dir a killed run left is removed
by the next read.

    python3 -m unittest discover -s core/tests/lander -p 'test_sealed_scratch.py'
"""
import contextlib
import glob
import os
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

CORE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from lander import git as G  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def size(d):
    return sum(os.path.getsize(os.path.join(p, f)) for p, _, fs in os.walk(d) for f in fs)


class Scratch(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(prefix="lander-sealed-test.")
        self.addCleanup(d.cleanup)
        self.tmp = d.name
        self.scratch = os.path.join(self.tmp, "tmp")   # the temp dir sealed() makes its cc-land.git.* in
        self.cache = os.path.join(self.tmp, "cache")
        os.mkdir(self.scratch)
        for p in (mock.patch.object(tempfile, "tempdir", self.scratch), mock.patch.object(G, "SEALED_CACHE", self.cache),
                  mock.patch.dict(os.environ, {"CC_DEV": self.tmp})):   # $CC_DEV/repo: a checkout the host made
            p.start()
            self.addCleanup(p.stop)
        self.repo = os.path.join(self.tmp, "repo")
        git(self.tmp, "init", "-q", "-b", "main", self.repo)
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")

    def commit(self, name, data):
        with open(os.path.join(self.repo, name), "wb") as f:
            f.write(data)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", name)
        return git(self.repo, "rev-parse", "HEAD")

    def test_a_read_after_the_first_writes_only_the_new_objects(self):
        """40 commits of 256 KiB of noise each, about 10 MB of history. The first read fills the cache with it; a
        check on the next change writes under 64 KiB to the scratch dir and grows the cache by under 64 KiB."""
        for i in range(40):
            base = self.commit(f"blob{i}", os.urandom(256 << 10))
        self.assertEqual(G.pr_changed(self.repo, base, base), [])
        full = size(self.cache)
        self.assertGreater(full, 10 << 20)
        head = self.commit("f", b"one\n")
        with G.sealed(self.repo, base, head) as ((rc, out), run):
            self.assertEqual(rc, 0, out)
            (d,) = os.listdir(self.scratch)
            written = size(os.path.join(self.scratch, d))
            self.assertEqual(run("diff", "--name-only", base, head)[1].strip(), "f")
        self.assertLess(written, 64 << 10)
        self.assertLess(size(self.cache) - full, 64 << 10)
        self.assertEqual(os.listdir(self.scratch), [])   # gone on exit

    def test_a_killed_runs_scratch_dir_is_removed_by_the_next_read(self):
        """A read SIGKILLed mid-way never reaches its finally: its cc-land.git.<pid>.* stays until the next read,
        which removes it since that pid is dead, and keeps one whose pid is alive."""
        a = self.commit("f", b"one\n")
        live = tempfile.mkdtemp(prefix=f"cc-land.git.{os.getpid()}.")
        code = (f"import os, signal, sys, tempfile; sys.path.insert(0, {CORE!r}); from lander import git as G; "
                f"tempfile.tempdir = {self.scratch!r}; G.SEALED_CACHE = {self.cache!r}\n"
                f"with G.sealed({self.repo!r}, {a!r}): os.kill(os.getpid(), signal.SIGKILL)")
        p = subprocess.Popen([sys.executable, "-c", code], stderr=subprocess.PIPE)
        self.assertEqual(p.wait(), -signal.SIGKILL, p.stderr.read())
        p.stderr.close()
        left = [n for n in os.listdir(self.scratch) if n.startswith(f"cc-land.git.{p.pid}.")]
        self.assertEqual(len(left), 1)
        with G.sealed(self.repo, a) as ((rc, out), _):
            self.assertEqual(rc, 0, out)
        self.assertEqual(os.listdir(self.scratch), [os.path.basename(live)])

    def cache_of(self, repo):
        """The cache's dir after a read of repo's HEAD; a repo that is not there fails the fetch after the sweep."""
        key = G.hashlib.sha256(os.path.realpath(os.path.join(repo, ".git")).encode()).hexdigest()[:16]
        ids = []
        if os.path.isdir(repo):
            git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "c")
            ids = [git(repo, "rev-parse", "HEAD")]
        with contextlib.suppress(G.GitError), G.sealed_cache(os.path.join(repo, ".git"), ids):
            pass
        return os.path.join(self.cache, key + ".git")

    def test_a_cache_whose_checkout_is_gone_is_removed(self):
        """The cache keeps a checkout's objects across reads; once that checkout is gone, the next read removes it."""
        other = os.path.join(self.tmp, "other")
        git(self.tmp, "init", "-q", other)
        kept, gone = self.cache_of(self.repo), self.cache_of(other)
        subprocess.run(["rm", "-rf", "--", other], check=True)
        self.cache_of(self.repo)
        self.assertTrue(os.path.isdir(kept))
        self.assertFalse(os.path.exists(gone))

    def test_a_sweep_beside_a_read_never_removes_a_live_cache(self):
        """A cache's cc-checkout is written once, before the cache is renamed into place, and a sweep that finds the
        file empty keeps the cache, so a sweep running beside a read never removes a live one."""
        d = self.cache_of(self.repo)
        mark = os.path.join(d, "cc-checkout")
        before = os.stat(mark)
        self.cache_of(self.repo)
        self.assertEqual((os.stat(mark).st_ino, os.stat(mark).st_mtime_ns), (before.st_ino, before.st_mtime_ns))
        open(mark, "w").close()
        self.cache_of(os.path.join(self.tmp, "other"))
        self.assertTrue(os.path.isdir(d))

    def test_a_fetch_killed_mid_way_leaves_nothing_after_the_next_read(self):
        """A read whose fetch is killed while index-pack writes (what _sh's timeout does) leaves a tmp_pack in the
        cache; the next read, which holds the cache's lock so no fetch is running, removes it."""
        for i in range(120):   # past fetch.unpackLimit, so index-pack writes a pack, as on a real repo
            a = self.commit(f"blob{i}", os.urandom(256 << 10))
        pack = os.path.join(self.cache, "*.git", "objects", "pack", "tmp_*")
        code = (f"import glob, os, signal, subprocess, sys, tempfile, time; sys.path.insert(0, {CORE!r}); "
                f"from lander import git as G; tempfile.tempdir = {self.scratch!r}; G.SEALED_CACHE = {self.cache!r}\n"
                "def sh(argv, cwd=None, env=None, timeout=120):\n"
                "    if 'fetch' not in argv: return G._sh(argv, cwd=cwd, env=env, timeout=timeout)\n"
                "    p = subprocess.Popen(argv, cwd=cwd, env=env)\n"
                f"    while not glob.glob({pack!r}) and p.poll() is None: time.sleep(0.001)\n"
                "    os.killpg(0, signal.SIGKILL)\n"
                f"with G.sealed({self.repo!r}, {a!r}, sh=sh): pass")
        p = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
        self.assertEqual(p.wait(timeout=120), -signal.SIGKILL)
        self.assertTrue(glob.glob(pack))   # what a killed fetch leaves
        with G.sealed(self.repo, a) as ((rc, out), _):
            self.assertEqual(rc, 0, out)
        self.assertEqual(glob.glob(pack), [])

    def test_a_cache_with_no_config_or_too_many_refs_is_made_anew(self):
        """A killed init leaves a cache with a config.lock and no config; one past SEALED_KEEP refs has kept too much.
        The next read builds each anew and reads."""
        a = self.commit("f", b"one\n")
        d = self.cache_of(self.repo)
        os.remove(os.path.join(d, "config"))
        open(os.path.join(d, "config.lock"), "w").close()
        with G.sealed(self.repo, a) as ((rc, out), _):
            self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(os.path.join(d, "config.lock")))
        with mock.patch.object(G, "SEALED_KEEP", 0):
            with G.sealed(self.repo, a) as ((rc, out), _):
                self.assertEqual(rc, 0, out)
        self.assertEqual(os.listdir(os.path.join(d, "refs", "sealed")), [a])

    def test_reads_on_a_cold_cache_at_once_all_read(self):
        """Eight reads start together on a cache that does not exist yet: one builds it and fetches, the rest wait on
        its lock and fetch nothing more, and every read succeeds."""
        a = self.commit("f", b"one\n")
        got = []

        def read():
            with G.sealed(self.repo, a) as ((rc, out), _):
                got.append((rc, out))
        ts = [threading.Thread(target=read) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(got, [(0, [a])] * 8)

    def test_a_rebuild_waits_for_every_read_of_the_cache(self):
        """A read holds the cache while it runs: a second read that finds the cache past SEALED_KEEP leaves it as it
        is, so the first still reads its objects, and the next read with no other running makes it anew."""
        a = self.commit("f", b"one\n")
        git(self.repo, "checkout", "-q", "--orphan", "other")   # b shares no object with a
        b = self.commit("g", b"two\n")
        with G.sealed(self.repo, a) as ((rc, out), run):
            self.assertEqual(rc, 0, out)
            with mock.patch.object(G, "SEALED_KEEP", 0), G.sealed(self.repo, b) as ((rc, out), _):
                self.assertEqual(rc, 0, out)
            self.assertEqual(run("cat-file", "-p", f"{a}:f"), (0, "one\n"))
        (d,) = glob.glob(os.path.join(self.cache, "*.git"))
        self.assertEqual(sorted(os.listdir(os.path.join(d, "refs", "sealed"))), sorted([a, b]))
        with mock.patch.object(G, "SEALED_KEEP", 0), G.sealed(self.repo, b) as ((rc, out), _):
            self.assertEqual(rc, 0, out)
        self.assertEqual(os.listdir(os.path.join(d, "refs", "sealed")), [b])

    def test_a_cache_that_lost_its_objects_is_made_anew(self):
        """A cache whose refs and commits are there but whose trees and blobs are gone (a disk filled mid-gc, a hand
        prune) offers those commits as haves, so the checkout sends too little and the fetch fails; the read makes the
        cache anew, fetches again and reads."""
        a = self.commit("f", b"one\n")
        with G.sealed(self.repo, a) as ((rc, out), _):
            self.assertEqual(rc, 0, out)
        (d,) = glob.glob(os.path.join(self.cache, "*.git"))
        for p, _, fs in os.walk(os.path.join(d, "objects")):
            for f in fs:
                if os.path.basename(p) + f != a and len(f) == 38:   # every loose object but a's commit
                    os.remove(os.path.join(p, f))
        head = self.commit("g", b"two\n")
        with G.sealed(self.repo, a, head) as ((rc, out), run):
            self.assertEqual(rc, 0, out)
            self.assertEqual(run("cat-file", "-p", f"{a}:f"), (0, "one\n"))

    def test_three_reads_of_one_change_at_once_fetch_it_once(self):
        """Three commands read one base and head at the same moment: the first fetch writes the one pack, the other
        two find every object in the cache and fetch nothing."""
        for i in range(120):   # past fetch.unpackLimit, so a fetch writes a pack
            head = self.commit(f"blob{i}", os.urandom(1 << 10))
        base = git(self.repo, "rev-parse", "HEAD~60")
        got = []

        def read():
            with G.sealed(self.repo, base, head) as ((rc, out), _):
                got.append(rc)
        ts = [threading.Thread(target=read) for _ in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(got, [0, 0, 0])
        self.assertEqual(len(glob.glob(os.path.join(self.cache, "*.git", "objects", "pack", "*.pack"))), 1)


if __name__ == "__main__":
    unittest.main()
