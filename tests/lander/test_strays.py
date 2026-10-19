"""lander tick's strays sweep: the box's own open PR that nothing queued gets queued, and nothing else does.

gh, `cc lands` and the queue itself are answered by fakes; the landing state, queue.log and the stamps are real files
under a temp dir. Run:
python3 -m unittest discover -s core/tests/lander -t core/tests/lander -p 'test_strays.py'
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from lander import events as E  # noqa: E402
from lander import gh as GH  # noqa: E402
from lander import git as G  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import lane as L  # noqa: E402
from lander import review as R  # noqa: E402
from lander import tick as TK  # noqa: E402
from lander import types as T  # noqa: E402

SELF_MERGE_HEADS = TK.self_merge_heads   # setUp fakes it for the sweep


def pr(n, branch="fix-docs", age=3600, draft=False, base="main"):
    return {"number": n, "headRefName": branch, "baseRefName": base, "isDraft": draft,
            "createdAt": E.stamp(time.time() - age)}


def changed(*paths, old=None):
    return [dict({"filename": f}, **({"previous_filename": old} if old else {})) for f in paths]


class Strays(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lander-strays.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        land = os.path.join(self.tmp, "land")
        p = mock.patch.dict(os.environ, {"CC_LAND_STATE": land, "CC_LANDER_STATE": land, "HOME": self.tmp,
                                         "CC_DEV": os.path.join(self.tmp, "dev"),
                                         "CC_BOARDS": os.path.join(self.tmp, "boards"),
                                         "LANDER_STRAY_SECS": "900"})
        p.start()
        self.addCleanup(p.stop)
        for repo in ("demo", "other"):
            os.makedirs(os.path.join(self.tmp, "dev", repo, ".git"))
        self.open = {"demo": [], "other": []}   # what gh pr list answers, per repo
        self.lists, self.queued, self.lands = [], [], {"demo": True, "other": True}
        self.gh_rc = 0
        self.heads, self.files, self.asked = {}, {}, []   # the box's self-merge prefixes; each PR's files (None fails)
        self.default, self.fetched = {"demo": "main", "other": "main"}, []   # each repo's default branch (None fails)

        def gh(argv, root, token=None, timeout=120):
            repo = os.path.basename(root)
            if argv[0] == "api" and argv[1].count("/") == 2:   # repos/<slug>: the repo itself
                d = self.default[repo]
                return (0, json.dumps({"default_branch": d}), "") if d is not None else (1, "", "HTTP 502")
            if argv[0] == "api":
                n = int(argv[1].split("/")[4])
                self.asked.append((repo, n))
                return (0, json.dumps(self.files[n]), "") if self.files.get(n) is not None else (1, "", "HTTP 502")
            self.lists.append(repo)
            return (self.gh_rc, "" if self.gh_rc else json.dumps(self.open[repo]), "boom" if self.gh_rc else "")

        def queue(argv):
            self.queued.append((argv[0], int(argv[1])))
            print(f"[{argv[0]}] PR #{argv[1]} queued")
            return 0

        def fetch(root, *branches, env=None):
            self.fetched.append((os.path.basename(root), branches))
            if "gone" in branches:
                raise G.GitError("git fetch: couldn't find remote ref")
            return {b: b for b in branches}   # the commit is the branch's name, so security_globs can tell them apart

        globs = ["tests/LANDING-security.toml", "host/**", "fx.py"]
        for target, name, fake in ((GH, "slug", lambda root: "o/" + os.path.basename(root)), (GH, "gh", gh),
                                   (TK, "self_lands", lambda repo: self.lands[repo]), (L, "cmd_queue", queue),
                                   (TK, "self_merge_heads", lambda repo: self.heads.get(repo, [])), (G, "fetch", fetch),
                                   (R, "security_globs",
                                    lambda root, base, repo: {"nolist": None, "nosec": []}.get(base, globs))):
            p = mock.patch.object(target, name, fake)
            p.start()
            self.addCleanup(p.stop)

    def test_only_a_ready_stray_of_the_box_is_queued(self):
        self.open["demo"] = [pr(5), pr(6, draft=True), pr(7, branch="track/row"), pr(8, age=120),
                             pr(9, age=3 * 86400)]
        lines = TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 5)])   # kept: ready, not a track's, inside the window
        self.assertEqual(len(lines), 1)
        self.assertIn("PR #5 was open with no landing record — queued it", lines[0])

    def test_a_pr_the_lander_holds_or_ever_logged_is_left_alone(self):
        self.open["demo"] = [pr(5), pr(10), pr(11), pr(50)]
        E.log("refused", "demo", 5, "protected:x")       # seen once: a refusal is not undone by a sweep
        J.submit("demo", 10)                            # an inbox request already waits
        E.log("queued", "xdemo", 11)                    # another repo's line names no PR of this one
        E.log("queued", "demo", 500)                    # nor does a longer number
        TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 11), ("demo", 50)])

    def test_a_pr_with_only_a_job_a_rest_file_or_a_handed_watch_is_left_alone(self):
        self.open["demo"] = [pr(12), pr(13), pr(14), pr(50)]   # none of 12-14 has a queue.log line
        J.save(T.Job(repo="demo", pr=12, state=T.CHECKING))      # a live job
        for path in (J.rest_path("demo", 13), J.handed_path("demo", 14)):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("{}")                                    # exists, but J.load reads no job from it
        self.assertIsNone(J.load("demo", 13))
        TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 50)])

    def test_a_failed_queue_is_said(self):
        self.open["demo"] = [pr(5)]
        with mock.patch.object(L, "cmd_queue", lambda argv: (print("no room"), 1)[1]):
            lines = TK.sweep_strays(["demo"])
        self.assertEqual(lines, ["[demo] PR #5 was open with no landing record — queueing it failed: no room"])

    def test_a_member_repo_is_never_listed(self):
        os.makedirs(os.path.join(self.tmp, "dev", "h--t", ".git"))
        self.open["h--t"] = [pr(5)]
        TK.sweep_strays(["h--t"])
        self.assertEqual((self.lists, self.queued), ([], []))

    def test_a_repo_that_does_not_land_itself_is_not_queued(self):
        self.open["demo"] = [pr(5)]
        self.open["other"] = [pr(6)]
        self.lands["other"] = False
        TK.sweep_strays(["demo", "other"])
        self.assertEqual(self.queued, [("demo", 5)])
        self.assertEqual(self.lists, ["demo"])          # its PRs are never even listed

    def test_the_sweep_reads_github_once_per_window(self):
        self.open["demo"] = [pr(5)]
        TK.sweep_strays(["demo"])
        TK.sweep_strays(["demo"])
        self.assertEqual(self.lists, ["demo"])          # suppressed: the stamp is fresh
        os.utime(TK.C.state("tip", "demo.strays"), (time.time() - 901, time.time() - 901))
        TK.sweep_strays(["demo"])
        self.assertEqual(self.lists, ["demo", "demo"])  # kept: the window has passed

    def test_a_gh_failure_is_said_and_queues_nothing(self):
        self.open["demo"] = [pr(5)]
        self.gh_rc = 1
        lines = TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [])
        self.assertEqual(lines, ["[demo] strays: gh could not list the open PRs — boom"])
        self.gh_rc = 0
        os.unlink(TK.C.state("tip", "demo.strays"))
        TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 5)])    # kept: the next window's read queues it

    def test_a_repo_with_no_checkout_or_no_github_origin_is_skipped(self):
        self.open["demo"] = [pr(5)]
        with mock.patch.object(GH, "slug", lambda root: ""):
            TK.sweep_strays(["demo", "nowhere"])
        self.assertEqual((self.lists, self.queued), ([], []))
        TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 5)])

    def test_a_declared_head_that_touches_no_security_path_is_left_to_its_repo(self):
        self.heads["demo"] = ["dispatch/"]
        self.open["demo"] = [pr(5, branch="dispatch/run-5"), pr(6)]
        self.files[5] = changed("README.md", "host.md", "docs/host/x.md")   # a glob, never a substring
        lines = TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 6)])     # kept: a head on no declared prefix queues as before
        self.assertEqual(self.asked, [("demo", 5)])      # only a declared head's files are asked for
        self.assertEqual(len(lines), 1)                  # and the one left says nothing

    def test_a_declared_head_on_a_security_path_is_queued(self):
        self.heads["demo"] = ["hive/", "dispatch/"]
        self.open["demo"] = [pr(5, branch="dispatch/a"), pr(6, branch="dispatch/b"), pr(7, branch="dispatch/c")]
        self.files.update({5: changed("README.md", "host/unit.service"),
                           6: changed("fx2.py", old="fx.py"),            # a rename off the list counts its old name
                           7: changed("tests/LANDING-security.toml")})   # the list itself, a removal included
        TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 5), ("demo", 6), ("demo", 7)])

    def test_a_repo_with_no_declared_heads_is_unchanged(self):
        self.heads["demo"] = ["dispatch/"]
        self.open["other"] = [pr(6, branch="dispatch/a")]
        self.files[6] = changed("README.md")
        TK.sweep_strays(["other"])
        self.assertEqual((self.queued, self.asked), ([("other", 6)], []))

    def test_a_declared_head_whose_files_or_list_will_not_read_is_queued(self):
        self.heads["demo"] = ["dispatch/"]
        self.open["demo"] = [pr(5, branch="dispatch/a"), pr(6, branch="dispatch/b"), pr(7, branch="dispatch/c"),
                             pr(10, branch="dispatch/f"), pr(11, branch="dispatch/ok")]
        self.files.update({6: changed(*(f"docs/{i}.md" for i in range(100))),   # gh's page is full: maybe more
                           7: [], 10: [{"path": "README.md"}], 11: changed("README.md")})
        TK.sweep_strays(["demo"])          # 5: the lookup fails; 7: no file; 10: no filename
        self.assertEqual([n for _, n in self.queued], [5, 6, 7, 10])

    def test_a_declared_head_whose_default_branch_or_its_list_will_not_read_is_queued(self):
        for default in (None, "gone", "nolist", "nosec"):   # no answer; no fetch; no list; an empty list tells nothing
            with self.subTest(default=default):
                self.queued.clear()
                os.environ["LANDER_STRAY_SECS"] = "0"
                self.heads["demo"], self.default["demo"] = ["dispatch/"], default
                self.open["demo"] = [pr(5, branch="dispatch/a", base=default or "main")]
                self.files[5] = changed("README.md")
                TK.sweep_strays(["demo"])
                self.assertEqual(self.queued, [("demo", 5)])

    def test_a_declared_head_to_another_base_is_queued(self):
        self.heads["demo"] = ["dispatch/"]
        self.open["demo"] = [pr(5, branch="dispatch/a", base="release"), pr(6, branch="dispatch/b"),
                             pr(7, branch="dispatch/c")]
        self.files.update({5: changed("README.md"), 6: changed("README.md"), 7: changed("README.md")})
        TK.sweep_strays(["demo"])
        self.assertEqual(self.queued, [("demo", 5)])     # only the default branch's PRs are the repo's own to merge
        self.assertEqual(self.fetched, [("demo", ("main",))])   # its base fetched fresh, once per sweep

    def test_self_merge_heads_reads_the_repo_key_on_the_box(self):
        answers = {"LANDER_SELF_MERGE_HEADS_dispatch": (0, "dispatch/ hive/\n", ""),
                   "LANDER_SELF_MERGE_HEADS_a_b": (1, "", ""), "LANDER_SELF_MERGE_HEADS_slow": (125, "", "timeout"),
                   "LANDER_SELF_MERGE_HEADS_deep": (0, "hive/runs/\n", "")}
        bad = ["dispatch", "dispatch/ d", "*/", "/", "../", "dispatch/ -x/", "a//"]
        answers.update({f"LANDER_SELF_MERGE_HEADS_bad{i}": (0, v, "") for i, v in enumerate(bad)})
        with mock.patch.object(L, "run", lambda argv, timeout=60: answers[argv[2]]):
            self.assertEqual(SELF_MERGE_HEADS("dispatch"), ["dispatch/", "hive/"])
            self.assertEqual(SELF_MERGE_HEADS("deep"), ["hive/runs/"])
            self.assertEqual(SELF_MERGE_HEADS("a.b"), [])     # unset
            self.assertEqual(SELF_MERGE_HEADS("slow"), [])    # cc-config did not answer: queue as before
            for i, v in enumerate(bad):                       # one word that is no namespace voids the whole setting
                self.assertEqual(SELF_MERGE_HEADS(f"bad{i}"), [], v)


if __name__ == "__main__":
    unittest.main()
