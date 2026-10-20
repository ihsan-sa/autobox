"""U2's selection cases: manifest and policy parsing, add-only (S3), prose (S10), one-hop reach, plan() and its class.

    python3 -m unittest discover -s core/tests/lander -p 'test_plan.py'

Each case builds its own fixture (a manifest text, or a git repo of its own), and asserts both what is selected and
what is left out.
"""
import ast
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock

CORE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from lander import manifest as M  # noqa: E402
from lander import plan as P  # noqa: E402
from lander import reach as R  # noqa: E402
from lander import types as T  # noqa: E402

CORE_MANIFEST = textwrap.dedent('''
    [[check]]
    name = "sc-a"
    run = "bash -n bin/a"
    paths = ["bin/a"]
    class = "static"

    [[check]]
    name = "a"
    run = "bin/a selfcheck"
    paths = ["bin/a"]
    class = "hermetic"

    [[check]]
    name = "b"
    run = "bin/b selfcheck"
    paths = ["bin/b"]
    class = "host"

    [[check]]
    name = "c"
    run = "bin/c selfcheck"
    paths = ["bin/c"]
    class = "host"

    [[check]]
    name = "e2e-x"
    run = "tests/e2e/x.sh"
    paths = ["bin/b"]
    class = "box"
    fixtures = ["tests/e2e/lib.sh"]

    [[check]]
    name = "docs-lint"
    run = "true"
    paths = ["docs/**"]
    class = "static"
''')
OVERLAY_MANIFEST = textwrap.dedent('''
    [[check]]
    name = "identity"
    run = "tests/check-extra.sh"
    paths = ["core/**"]
    class = "static"

    [[check]]
    name = "check-sh"
    run = "core/tests/check.sh"
    paths = ["core/tests/check.sh"]
    class = "host"
''')
POLICY = textwrap.dedent('''
    default_checks = ["check-sh"]
    [paths]
    gate_first = ["core/bin/guard", "tests/**"]
    paid_review = ["core/bin/b", "core/config/**"]
    lander = ["core/lander/**"]
    default = ["home/**"]
''')
REACH = "# a comment\nb\ta\nc\tb\n"


def git(root, *a):
    return subprocess.run(["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


def write(root, files):
    for p, text in files.items():
        full = os.path.join(root, p)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)


class Repo:
    """A git repo with the two manifests, the policy and the reach graph committed as its base."""

    def __init__(self, tc, extra=None):
        self.d = tempfile.TemporaryDirectory()
        tc.addCleanup(self.d.cleanup)
        self.root = os.path.join(self.d.name, "repo")   # $CC_DEV/repo: a checkout the host made (git.host_tree)
        os.mkdir(self.root)
        p = mock.patch.dict(os.environ, {"CC_DEV": self.d.name})
        p.start()
        tc.addCleanup(p.stop)
        git(self.root, "init", "-q")
        write(self.root, {"core/tests/LANDING.toml": CORE_MANIFEST, "tests/LANDING.toml": OVERLAY_MANIFEST,
                          "tests/LANDING-policy.toml": POLICY, "core/tests/reach.tsv": REACH,
                          "core/bin/a": "#!/bin/sh\n", "core/bin/b": "#!/bin/sh\n", "core/bin/c": "#!/bin/sh\n",
                          **(extra or {})})
        self.base = self.commit("base")

    def commit(self, msg, files=None):
        write(self.root, files or {})
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", msg, "--allow-empty")
        return git(self.root, "rev-parse", "HEAD")


class Globs(unittest.TestCase):
    def test_star_stays_in_a_segment_and_double_star_crosses(self):
        self.assertTrue(M.match(["bin/*"], "bin/a"))
        self.assertFalse(M.match(["bin/*"], "bin/x/a"))
        self.assertTrue(M.match(["docs/**"], "docs/x/y.md"))
        self.assertTrue(M.match(["**/agents/**"], "core/agents/r.md"))
        self.assertTrue(M.match(["**/REVIEW.md"], "REVIEW.md"))
        self.assertFalse(M.match(["docs/**"], "core/docs/y.md"))
        self.assertTrue(M.match(["**"], "anything/at/all"))


class Parsing(unittest.TestCase):
    def test_paths_and_fixtures_are_prefixed_and_the_run_file_is_owned(self):
        checks, faults = M.parse_checks(CORE_MANIFEST, "core/", "x")
        self.assertEqual(faults, [])
        e2e = next(c for c in checks if c.name == "e2e-x")
        self.assertEqual(e2e.paths, ["core/bin/b"])
        self.assertEqual(e2e.fixtures, ["core/tests/e2e/lib.sh"])
        m = M.Manifest(checks={c.name: c for c in checks}, cwd={c.name: "core/" for c in checks})
        self.assertTrue(m.owns("e2e-x", "core/tests/e2e/x.sh"))      # its own run file (S2)
        self.assertTrue(m.owns("e2e-x", "core/tests/e2e/lib.sh"))    # its fixture
        self.assertFalse(m.owns("e2e-x", "core/tests/e2e/y.sh"))     # another script is not its

    def test_a_typo_key_and_a_bad_class_are_faults_not_silence(self):
        _, faults = M.parse_checks('[[check]]\nname="x"\nrun="y"\npath=["a"]\n', "", "m")
        self.assertTrue(any("path" in f for f in faults), faults)
        _, faults = M.parse_checks('[[check]]\nname="x"\nrun="y"\nclass="sometimes"\n', "", "m")
        self.assertTrue(faults)
        _, faults = M.parse_checks('[[rule]]\nx=1\n', "", "m")
        self.assertTrue(any("rule" in f for f in faults))
        checks, faults = M.parse_checks('[[check]]\nname="x"\nrun="y"\n', "", "m")
        self.assertEqual((len(checks), faults), (1, []))

    def test_bare_is_a_host_or_box_checks_boolean_and_anything_else_is_a_fault(self):
        one = '[[check]]\nname="x"\nrun="y"\n'
        checks, faults = M.parse_checks(one + 'class="host"\nbare=true\n', "", "m")
        self.assertEqual(([c.bare for c in checks], faults), ([True], []))
        self.assertFalse(M.parse_checks(one + 'class="host"\n', "", "m")[0][0].bare)   # default: in the scope
        for bad in ('class="host"\nbare="yes"\n', 'class="host"\nbare=1\n', 'class="hermetic"\nbare=true\n',
                    'class="static"\nbare=true\n', 'class="timing"\nbare=true\n', 'bare=true\n'):
            checks, faults = M.parse_checks(one + bad, "", "m")
            self.assertEqual(checks, [], bad)
            self.assertTrue(any("bare" in f for f in faults), (bad, faults))

    def test_the_shipped_manifest_runs_bare_only_what_a_landlock_domain_blinds(self):
        with open(os.path.join(CORE, "tests", "LANDING.toml")) as f:
            checks, faults = M.parse_checks(f.read(), "core/", "core/tests/LANDING.toml")
        self.assertEqual(faults, [])
        self.assertEqual(sorted(c.name for c in checks if c.bare),
                         ["e2e-cc-context", "selfcheck-cc-fence", "selfcheck-cc-sandbox"])

    def test_a_name_that_could_write_log_fields_is_a_fault(self):
        # the queue log keeps `gate=<name>`, and the lane's express path reads check times back from it
        checks, faults = M.parse_checks('[[check]]\nname="heavy ok=yes secs=1"\nrun="y"\n'
                                        '[[check]]\nname="ok.name_2-x"\nrun="y"\n', "", "m")
        self.assertEqual([c.name for c in checks], ["ok.name_2-x"])
        self.assertTrue(any("heavy ok=yes" in f for f in faults), faults)

    def test_policy_maps_default_checks_and_keeps_default_paths_apart(self):
        pol, faults = M.parse_policy(POLICY, "", "p")
        self.assertEqual(faults, [])
        self.assertEqual(pol.default, ["check-sh"])
        self.assertEqual(pol.extra["default_paths"], ["home/**"])
        self.assertIn("core/bin/guard", pol.gate_first)
        _, faults = M.parse_policy('[paths]\ngate_frist=["x"]\n', "", "p")
        self.assertTrue(faults)

    def test_a_broken_base_raises_and_a_broken_head_is_carried(self):
        r = Repo(self)
        bad = r.commit("bad", {"tests/LANDING.toml": "[[check]\n"})
        with self.assertRaises(M.ManifestError):
            M.load(r.root, bad)
        m = M.load(r.root, bad, strict=False)
        self.assertTrue(m.faults)
        self.assertIn("a", M.load(r.root, r.base).checks)

    def test_a_duplicate_name_across_manifests_is_a_fault(self):
        r = Repo(self)
        dup = r.commit("dup", {"tests/LANDING.toml": OVERLAY_MANIFEST + '\n[[check]]\nname="a"\nrun="x"\n'})
        with self.assertRaises(M.ManifestError):
            M.load(r.root, dup)

    def test_the_fallback_is_read_only_when_the_tree_has_no_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            git(d, "init", "-q")
            write(d, {"x": "1"})
            git(d, "add", "-A")
            git(d, "commit", "-qm", "x")
            with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
                f.write('[[check]]\nname="check"\nrun="tests/check.sh"\npaths=["**"]\n')
            fb = f.name
            self.addCleanup(os.unlink, fb)
            with mock.patch.dict(os.environ, {"CC_DEV": os.path.dirname(d)}):   # $CC_DEV/<d>: a host checkout
                self.assertEqual(list(M.load(d, "HEAD", fallback=fb).checks), ["check"])
                self.assertEqual(M.load(d, "HEAD").checks, {})

    def test_a_repo_with_no_manifest_plans_the_pytest_of_its_host_fallback(self):
        # a repo that ships no manifest is planned by the release's landing-repos/<repo>.toml; with none it plans 0
        with tempfile.TemporaryDirectory() as d:
            fbdir = os.path.join(d, "landing-repos")
            write(fbdir, {"demo.toml": '[[check]]\nname="pytest"\nrun="python3 -m pytest -q"\npaths=["**"]\n'
                                       'class="host"\n'})
            root = os.path.join(d, "demo")
            os.mkdir(root)
            git(root, "init", "-q")
            write(root, {"pytest.ini": "[pytest]\n", "app.py": "x = 1\n", "tests/test_app.py": "def test_x(): pass\n"})
            git(root, "add", "-A")
            git(root, "commit", "-qm", "base")
            base = git(root, "rev-parse", "HEAD")
            write(root, {"app.py": "x = 2\n"})
            git(root, "commit", "-qam", "head")
            head = git(root, "rev-parse", "HEAD")
            with mock.patch.object(M, "FALLBACK_DIR", fbdir), \
                    mock.patch.dict(os.environ, {"CC_DEV": d}):   # git.taken: $CC_DEV/<repo> is a host checkout
                fb = M.host_fallback("demo")
                self.assertEqual(fb, os.path.join(fbdir, "demo.toml"))
                self.assertEqual(M.host_fallback("other"), "")
                self.assertEqual(P.plan(root, base, head, ["app.py"], fallback=fb).checks, ["pytest"])
                self.assertEqual(P.plan(root, base, head, ["app.py"]).checks, [])


class AddOnly(unittest.TestCase):
    def two(self, head_text, base_text=CORE_MANIFEST):
        base = M.Manifest()
        for c in M.parse_checks(base_text, "core/", "b")[0]:
            base.checks[c.name], base.cwd[c.name] = c, "core/"
        base.policy = M.parse_policy(POLICY, "", "p")[0]
        head = M.Manifest()
        for c in M.parse_checks(head_text, "core/", "h")[0]:
            head.checks[c.name], head.cwd[c.name] = c, "core/"
        head.policy = base.policy
        return base, head

    def test_adding_a_check_or_a_path_or_moving_up_a_class_is_allowed(self):
        text = CORE_MANIFEST.replace('paths = ["bin/c"]', 'paths = ["bin/c", "bin/d"]')
        text = text.replace('run = "bash -n bin/a"\npaths = ["bin/a"]\nclass = "static"',
                            'run = "bash -n bin/a"\npaths = ["bin/a"]\nclass = "hermetic"')
        text += '\n[[check]]\nname = "new"\nrun = "true"\nclass = "hermetic"\n'
        self.assertEqual(M.widen_faults(*self.two(text)), [])

    def test_a_check_may_not_widen_its_own_boundary(self):
        new = '\n[[check]]\nname = "new"\nrun = "true"\nclass = "hermetic"\n'
        cases = {   # what the head writes -> the words its fault must carry
            "added host": (CORE_MANIFEST + '\n[[check]]\nname = "new"\nrun = "true"\nclass = "host"\n',
                           "'new': adds itself to class host"),
            "added box": (CORE_MANIFEST + '\n[[check]]\nname = "new"\nrun = "true"\nclass = "box"\n',
                          "'new': adds itself to class box"),
            "changed to box": (CORE_MANIFEST.replace('paths = ["bin/a"]\nclass = "hermetic"',
                                                     'paths = ["bin/a"]\nclass = "box"'),
                               "'a': changes itself to class box"),
            "added net": (CORE_MANIFEST + new + 'net = true\n', "'new': adds itself to net = true"),
            "added mount": (CORE_MANIFEST + new + 'mounts = ["/opt/x"]\n', "'new': adds itself to mount /opt/x"),
            "changed to host": (CORE_MANIFEST.replace('class = "box"', 'class = "host"'),
                                "'e2e-x': changes itself to class host"),
            "changed net": (CORE_MANIFEST.replace('class = "box"', 'class = "box"\nnet = true'),
                            "'e2e-x': changes itself to net = true"),
            "changed mount": (CORE_MANIFEST.replace('class = "box"', 'class = "box"\nmounts = ["~/.venv"]'),
                              "'e2e-x': changes itself to mount ~/.venv"),
            "added bare": (CORE_MANIFEST + '\n[[check]]\nname = "new"\nrun = "true"\nclass = "host"\nbare = true\n',
                           "'new': adds itself to bare = true"),
            "changed bare": (CORE_MANIFEST.replace('class = "box"', 'class = "box"\nbare = true'),
                             "'e2e-x': changes itself to bare = true"),
        }
        for what, (text, words) in cases.items():
            base, head = self.two(text)
            faults = M.widen_faults(base, head)
            self.assertTrue(any(words in f for f in faults), (what, faults))
            self.assertNotIn("new", M.widen(base, head).checks, what)   # an added one is never selected to run

    def test_a_check_with_no_class_runs_in_the_sandbox_as_the_prs_own_and_as_a_base_check(self):
        # 2026-10-14, #1300's security read: one reviewed as hermetic while new kept T.Check's host default once merged
        unclassed = '\n[[check]]\nname = "u"\nrun = "true"\n'
        base, head = self.two(CORE_MANIFEST + unclassed)   # the PR's own
        self.assertEqual(M.widen_faults(base, head), [])
        own = M.widen(base, head).checks["u"].klass
        base, head = self.two(CORE_MANIFEST + unclassed, CORE_MANIFEST + unclassed)   # merged: now a base check
        self.assertEqual(M.widen_faults(base, head), [])
        merged = M.widen(base, head).checks["u"].klass
        self.assertEqual((own, merged), (T.HERMETIC, T.HERMETIC))
        hosted = CORE_MANIFEST + unclassed + 'class = "host"\n'   # writing host in later is a widening, not a no-op
        self.assertTrue(any("'u': changes itself to class host" in f
                            for f in M.widen_faults(*self.two(hosted, CORE_MANIFEST + unclassed))))
        r = Repo(self)   # the same through load() and plan(): the missing class line is seen in the git text
        text = OVERLAY_MANIFEST + '\n[[check]]\nname="n"\nrun="true"\npaths=["n.txt"]\n'
        head = r.commit("add", {"tests/LANDING.toml": text})
        self.assertEqual(M.widen(M.load(r.root, r.base), M.load(r.root, head)).checks["n"].klass, T.HERMETIC)
        self.assertTrue(M.widen_check(r.root, r.base, head)[0])
        later = r.commit("later", {"n.txt": "x\n"})   # a later PR, on top of the merged one
        self.assertEqual(M.load(r.root, head).checks["n"].klass, T.HERMETIC)
        self.assertEqual(M.widen(M.load(r.root, head), M.load(r.root, later)).checks["n"].klass, T.HERMETIC)

    def test_a_grant_the_base_already_has_is_not_a_widening(self):
        base_text = CORE_MANIFEST.replace('class = "box"', 'class = "box"\nnet = true\nmounts = ["/opt/x"]\nbare = true')
        wider = base_text.replace('paths = ["bin/b"]\nclass = "box"', 'paths = ["bin/b", "bin/y"]\nclass = "box"')
        self.assertEqual(M.widen_faults(*self.two(wider, base_text)), [])
        more = base_text.replace('mounts = ["/opt/x"]', 'mounts = ["/opt/x", "/opt/y"]')
        self.assertEqual([f for f in M.widen_faults(*self.two(more, base_text)) if "mount" in f],
                         ["check 'e2e-x': changes itself to mount /opt/y, which its base definition does not have"])

    def test_every_narrowing_is_named(self):
        cases = {
            "removed": CORE_MANIFEST.replace('name = "c"', 'name = "c2"'),
            "run changed": CORE_MANIFEST.replace('run = "bin/b selfcheck"', 'run = "true"'),
            "paths lost": CORE_MANIFEST.replace('paths = ["docs/**"]', 'paths = ["docs/x/**"]'),
            "fixtures lost": CORE_MANIFEST.replace('fixtures = ["tests/e2e/lib.sh"]', ''),
            "class moved": CORE_MANIFEST.replace('class = "box"', 'class = "hermetic"'),
        }
        words = {"removed": "removed", "run changed": "run changed", "paths lost": "paths lost",
                 "fixtures lost": "fixtures lost", "class moved": "class moved"}
        for what, text in cases.items():
            faults = M.widen_faults(*self.two(text))
            self.assertTrue(any(words[what] in f for f in faults), (what, faults))

    def test_host_to_box_is_a_narrowing_static_to_hermetic_is_not(self):
        down = CORE_MANIFEST.replace('name = "b"\nrun = "bin/b selfcheck"\npaths = ["bin/b"]\nclass = "host"',
                                     'name = "b"\nrun = "bin/b selfcheck"\npaths = ["bin/b"]\nclass = "box"')
        self.assertTrue(M.widen_faults(*self.two(down)))
        up = CORE_MANIFEST.replace('run = "bash -n bin/a"\npaths = ["bin/a"]\nclass = "static"',
                                   'run = "bash -n bin/a"\npaths = ["bin/a"]\nclass = "hermetic"')
        self.assertEqual(M.widen_faults(*self.two(up)), [])

    def test_a_policy_entry_removed_is_a_narrowing(self):
        base, head = self.two(CORE_MANIFEST)
        head.policy = M.parse_policy(POLICY.replace('"core/bin/guard", ', ''), "", "p")[0]
        self.assertTrue(any("gate_first lost core/bin/guard" in f for f in M.widen_faults(base, head)))

    def test_widen_uses_the_base_definition_plus_the_heads_extra_paths(self):
        text = CORE_MANIFEST.replace('run = "bin/b selfcheck"\npaths = ["bin/b"]',
                                     'run = "true"\npaths = ["bin/b", "bin/z"]')
        base, head = self.two(text)
        w = M.widen(base, head)
        self.assertEqual(w.checks["b"].run, "bin/b selfcheck")            # the narrowing is ignored
        self.assertEqual(w.checks["b"].paths, ["core/bin/b", "core/bin/z"])  # the widening is kept

    def test_widen_check_on_two_commits(self):
        r = Repo(self)
        added = OVERLAY_MANIFEST + '\n[[check]]\nname="n"\nrun="true"\nclass="static"\n'
        ok, _ = M.widen_check(r.root, r.base, r.commit("add", {"tests/LANDING.toml": added}))
        self.assertTrue(ok)
        # identity's run file has to be in a tree, or the check never ran and may go (DeadWeight)
        ok, text = M.widen_check(r.root, r.base, r.commit("drop", {"tests/LANDING.toml": "",
                                                                   "tests/check-extra.sh": "#!/bin/sh\n"}))
        self.assertFalse(ok)
        self.assertIn("identity", text)


class Retired(unittest.TestCase):
    """A check main removed after a PR branched does not come back from that PR's head (fork). 2026-10-14: #1286
    dropped the cc-member-* checks and every PR branched before it ran them, red on main, for a day."""
    OLD = '\n[[check]]\nname = "old"\nrun = "core/bin/a"\npaths = ["core/bin/a"]\nclass = "static"\n'

    def setUp(self):
        self.r = Repo(self, {"tests/LANDING.toml": OVERLAY_MANIFEST + self.OLD})
        self.main = self.r.commit("main drops old", {"tests/LANDING.toml": OVERLAY_MANIFEST})

    def head(self, files):
        git(self.r.root, "checkout", "-q", "-b", "pr" + str(len(files)), self.r.base)
        head = self.r.commit("pr", {"core/bin/a": "#!/bin/sh\necho\n", **files})
        git(self.r.root, "checkout", "-q", "-")
        return head

    def test_a_check_main_retired_stays_out_of_a_stale_heads_plan(self):
        head = self.head({})
        self.assertIn("old", M.widen(M.load(self.r.root, self.main), M.load(self.r.root, head)).checks)   # the bug
        self.assertEqual(M.fork(self.r.root, self.main, head).checks["old"].run, "core/bin/a")
        self.assertNotIn("old", P.plan(self.r.root, self.main, head, ["core/bin/a"]).checks)

    def test_a_check_the_head_adds_or_changes_still_runs(self):
        new = '\n[[check]]\nname = "new"\nrun = "core/bin/a"\npaths = ["core/bin/a"]\nclass = "static"\n'
        head = self.head({"tests/LANDING.toml": OVERLAY_MANIFEST + self.OLD + new})
        p = P.plan(self.r.root, self.main, head, ["core/bin/a", "tests/LANDING.toml"])
        self.assertIn("new", p.checks)
        self.assertNotIn("old", p.checks)
        changed = self.OLD.replace('paths = ["core/bin/a"]', 'paths = ["core/bin/a", "core/bin/b"]')
        head = self.head({"tests/LANDING.toml": OVERLAY_MANIFEST + changed, "core/x": "1"})
        self.assertIn("old", P.plan(self.r.root, self.main, head, ["core/bin/a", "tests/LANDING.toml"]).checks)

    def test_no_fork_for_the_working_copy_or_a_head_on_the_base(self):
        self.assertIsNone(M.fork(self.r.root, self.main, ""))
        self.assertIsNone(M.fork(self.r.root, self.main, self.r.commit("on main", {"core/bin/a": "#!/bin/sh\n:\n"})))


class DeadWeight(unittest.TestCase):
    """A head may narrow only what it deletes: an entry naming files the base has and the head does not."""
    BASE = textwrap.dedent('''
        [[check]]
        name = "selfcheck-cc-model"
        run = "bin/cc-model selfcheck"
        paths = ["bin/cc-model", "config/claude-settings.json"]
        class = "host"
        where = ["box", "laptop"]

        [[check]]
        name = "e2e-limit-episode"
        run = "tests/e2e/limit-episode.sh"
        paths = ["bin/cc-limit", "bin/cc-model", "tests/e2e/limit-episode.sh"]
        class = "host"
        where = ["box", "laptop"]
        fixtures = ["tests/e2e/lib.sh"]

        [[check]]
        name = "member"
        run = "bin/cc-member selfcheck"
        paths = ["bin/cc-member", "tests/member.py", "tests/quarantine"]
        class = "host"
        fixtures = ["tests/member-lib.sh"]

        [[check]]
        name = "py-compile-tests"
        run = "python3 -m py_compile mail/*.py tests/slack.py tests/member.py"
        paths = ["mail/**", "tests/slack.py", "tests/member.py"]
        class = "static"

        [[check]]
        name = "noop"
        run = "true"
        class = "static"
    ''')
    BASE_FILES = {"core/bin/cc-model", "core/config/claude-settings.json", "core/bin/cc-limit",
                  "core/tests/e2e/limit-episode.sh", "core/tests/e2e/lib.sh", "core/bin/cc-member",
                  "core/tests/member.py", "core/tests/quarantine/a", "core/tests/quarantine/b/c",
                  "core/tests/member-lib.sh", "core/mail/x.py", "core/tests/slack.py"}

    @classmethod
    def trees(cls, deleted=(), moved=None, edited=None):
        """Trees-like {path: blob}: each base file its own blob; deleted ones gone, moved ones {old: new} renamed,
        edited ones {old: new} renamed with new bytes, which only git's -M (moved) still ties to the old path."""
        base = {p: "blob:" + p for p in cls.BASE_FILES}
        head = {p: o for p, o in base.items() if p[5:] not in deleted}
        for old, new in (moved or {}).items():
            head["core/" + new] = head.pop("core/" + old)
        for old, new in (edited or {}).items():
            head["core/" + new] = head.pop("core/" + old) + ":edited"
        return types.SimpleNamespace(base=base, head=head, moved={"core/" + p for p in (edited or {})})

    def faults(self, head_text, deleted=(), base_text=None, moved=None, edited=None):
        base, head = AddOnly.two(None, head_text, base_text or self.BASE)
        return M.widen_faults(base, head, self.trees(deleted, moved, edited))

    def drop(self, name, text=None):
        """The base text with check `name` cut out."""
        text = text or self.BASE
        start = text.index(f'name = "{name}"') - len("[[check]]\n")
        end = text.find("[[check]]", start + 1)
        return text[:start] + (text[end:] if end > 0 else "")

    def test_a_check_whose_files_are_all_deleted_may_go_and_one_with_a_survivor_may_not(self):
        member = ("bin/cc-member", "tests/member.py", "tests/quarantine/a", "tests/quarantine/b/c",
                  "tests/member-lib.sh")
        self.assertEqual(self.faults(self.drop("member"), member), [])
        # the run target survives: refused
        self.assertEqual(self.faults(self.drop("member"), member[1:]), ["check 'member' was removed"])
        # a directory entry with one file left under it survives too
        self.assertEqual(self.faults(self.drop("member"), member[:3] + member[4:]), ["check 'member' was removed"])
        # a fixture that survives keeps it
        self.assertEqual(self.faults(self.drop("member"), member[:4]), ["check 'member' was removed"])
        # no trees given: every removal is a fault, as before
        base, head = AddOnly.two(None, self.drop("member"), self.BASE)
        self.assertEqual(M.widen_faults(base, head), ["check 'member' was removed"])

    def test_a_check_that_names_no_file_may_never_go(self):
        self.assertEqual(self.faults(self.drop("noop"), tuple(f[5:] for f in self.BASE_FILES)),
                         ["check 'noop' was removed"])

    GHOST = textwrap.dedent('''
        [[check]]
        name = "ghost"
        run = "bin/cc-ghost selfcheck"
        paths = ["bin/cc-ghost", "bin/cc-model"]
        class = "hermetic"
    ''')

    def test_a_check_whose_run_file_is_in_neither_tree_may_go(self):
        """2026-10-13: #1046 and #1154 left checks on main for tools only unmerged PRs had; they may come out."""
        base_text = self.BASE + self.GHOST
        self.assertEqual(self.faults(self.BASE, base_text=base_text), [])
        base, head = AddOnly.two(None, self.BASE, base_text)
        self.assertNotIn("ghost", M.widen(base, head, self.trees()).checks)
        # the head that brings the tool may not drop its check, and neither may one on a base that has it
        files = self.trees()
        files.head["core/bin/cc-ghost"] = "blob:ghost"
        self.assertEqual(M.widen_faults(base, head, files), ["check 'ghost' was removed"])
        files = self.trees()
        files.base["core/bin/cc-ghost"] = files.head["core/bin/cc-ghost"] = "blob:ghost"
        self.assertEqual(M.widen_faults(base, head, files), ["check 'ghost' was removed"])

    GUARD = textwrap.dedent('''
        [[check]]
        name = "guard-replay"
        run = 'tests/guard-replay.sh'
        paths = ["bin/cc-guard", "bin/cc-guard-argv", "tests/guard-replay.sh", "tests/guard-replay.jsonl"]
        class = "hermetic"
    ''')

    def test_guard_replay_never_goes_as_dead(self):
        """2026-10-19, perms' read of #1453: a head deleting guard-replay's run file and every path it lists dropped
        the check, and landed with no guard replay at all."""
        files = self.trees()
        guard = ("bin/cc-guard", "bin/cc-guard-argv", "tests/guard-replay.sh", "tests/guard-replay.jsonl")
        for f in guard:
            files.base["core/" + f] = "blob:" + f
        base, head = AddOnly.two(None, self.BASE, self.BASE + self.GUARD)
        self.assertEqual(M.widen_faults(base, head, files), ["check 'guard-replay' was removed"])
        self.assertIn("guard-replay", M.widen(base, head, files).checks)
        # the same check under another name is dead weight and goes: only the name keeps it
        other = (self.BASE + self.GUARD).replace('"guard-replay"', '"other"')
        base, head = AddOnly.two(None, self.BASE, other)
        self.assertEqual(M.widen_faults(base, head, files), [])
        self.assertNotIn("other", M.widen(base, head, files).checks)

    def test_the_guard_selfchecks_never_go_as_dead(self):
        """perms' read of #1571: selfcheck-cc-guard and selfcheck-cc-guard-argv are the guard's own cases, so each is
        kept by name like guard-replay, though a head deleted its run file and every path."""
        for name, run in (("selfcheck-cc-guard", "bin/cc-guard selfcheck"),
                          ("selfcheck-cc-guard-argv", "bin/cc-guard-argv selfcheck")):
            with self.subTest(name):
                check = textwrap.dedent(f'''
                    [[check]]
                    name = "{name}"
                    run = '{run}'
                    paths = ["{run.split()[0]}"]
                    class = "hermetic"
                ''')
                files = self.trees()
                files.base["core/" + run.split()[0]] = "blob:" + name
                base, head = AddOnly.two(None, self.BASE, self.BASE + check)
                self.assertEqual(M.widen_faults(base, head, files), [f"check '{name}' was removed"])
                self.assertIn(name, M.widen(base, head, files).checks)
                other = (self.BASE + check).replace(f'"{name}"', '"other"')
                base, head = AddOnly.two(None, self.BASE, other)
                self.assertEqual(M.widen_faults(base, head, files), [])
                self.assertNotIn("other", M.widen(base, head, files).checks)

    def test_a_check_added_before_its_tool_is_refused(self):
        base, head = AddOnly.two(None, self.BASE + self.GHOST, self.BASE)
        self.assertEqual(M.widen_faults(base, head, self.trees()),
                         ["check 'ghost': adds itself to run core/bin/cc-ghost, which this head does not have"])
        # added with its tool: allowed
        files = self.trees()
        files.head["core/bin/cc-ghost"] = "blob:ghost"
        self.assertEqual(M.widen_faults(base, head, files), [])
        # a run that names no file, or no trees to read: no such fault
        base, head = AddOnly.two(None, self.BASE + self.GHOST.replace("bin/cc-ghost selfcheck", "true"), self.BASE)
        self.assertEqual(M.widen_faults(base, head, self.trees()), [])
        base, head = AddOnly.two(None, self.BASE + self.GHOST, self.BASE)
        self.assertEqual(M.widen_faults(base, head), [])

    def test_the_two_narrowings_1233_got_wrong_stay_refused(self):
        # both files survive the head, so neither path may be dropped from the check that covers it
        text = self.BASE.replace('paths = ["bin/cc-model", "config/claude-settings.json"]', 'paths = ["bin/cc-model"]')
        text = text.replace('paths = ["bin/cc-limit", "bin/cc-model", ', 'paths = ["bin/cc-limit", ')
        self.assertEqual(self.faults(text, ("bin/cc-member", "tests/member.py")),
                         ["check 'selfcheck-cc-model': paths lost core/config/claude-settings.json",
                          "check 'e2e-limit-episode': paths lost core/bin/cc-model"])
        # the same drops are allowed once the head deletes those files
        self.assertEqual(self.faults(text, ("config/claude-settings.json", "bin/cc-model")), [])

    def test_a_path_or_fixture_may_drop_only_when_its_file_is_deleted(self):
        text = self.BASE.replace('"tests/member.py", "tests/quarantine"]', '"tests/quarantine"]')
        text = text.replace('fixtures = ["tests/member-lib.sh"]', 'fixtures = []')
        self.assertEqual(self.faults(text, ("tests/member.py", "tests/member-lib.sh")), [])
        self.assertEqual(self.faults(text, ("tests/member.py",)),
                         ["check 'member': fixtures lost core/tests/member-lib.sh"])
        self.assertEqual(self.faults(text, ("tests/member-lib.sh",)),
                         ["check 'member': paths lost core/tests/member.py"])

    def test_a_glob_may_drop_only_when_it_matches_no_file_in_the_head(self):
        text = self.BASE.replace('paths = ["mail/**", ', 'paths = [')
        self.assertEqual(self.faults(text, ("mail/x.py",)), [])
        self.assertEqual(self.faults(text), ["check 'py-compile-tests': paths lost core/mail/**"])
        # a glob that matched nothing in the base is never gone, so it never drops
        empty = self.BASE.replace('"mail/**", ', '"mail/**", "nowhere/*.py", ')
        self.assertEqual(self.faults(self.BASE, tuple(f[5:] for f in self.BASE_FILES), empty),
                         ["check 'py-compile-tests': paths lost core/nowhere/*.py"])

    def test_a_changed_run_line_is_a_fault_even_when_its_dropped_word_is_deleted(self):
        text = self.BASE.replace(" tests/member.py\"", "\"").replace('"tests/slack.py", "tests/member.py"]',
                                                                     '"tests/slack.py"]')
        self.assertEqual(self.faults(text, ("tests/member.py",)),
                         ["check 'py-compile-tests': run changed from "
                          "'python3 -m py_compile mail/*.py tests/slack.py tests/member.py' to "
                          "'python3 -m py_compile mail/*.py tests/slack.py'"])

    def test_a_move_or_a_rename_is_not_a_delete(self):
        # git mv tests/member.py tests/m/member.py, and the path dropped: the blob survives at the new path
        text = self.BASE.replace('"tests/member.py", "tests/quarantine"]', '"tests/quarantine"]')
        self.assertEqual(self.faults(text, moved={"tests/member.py": "tests/m/member.py"}),
                         ["check 'member': paths lost core/tests/member.py"])
        # bin/cc-member renamed to bin/cc_member and the whole check dropped: refused
        member = ("tests/member.py", "tests/quarantine/a", "tests/quarantine/b/c", "tests/member-lib.sh")
        self.assertEqual(self.faults(self.drop("member"), member, moved={"bin/cc-member": "bin/cc_member"}),
                         ["check 'member' was removed"])
        # the same with bin/cc-member really deleted is allowed
        self.assertEqual(self.faults(self.drop("member"), member + ("bin/cc-member",)), [])

    def test_a_move_with_an_edit_is_not_a_delete(self):
        """perms 10-12: moving cc-member, editing one line and dropping its check is a fault. Its bytes changed, so
        no head blob matches; git's -M rename (files.moved) is what keeps it."""
        member = ("tests/member.py", "tests/quarantine/a", "tests/quarantine/b/c", "tests/member-lib.sh")
        self.assertEqual(self.faults(self.drop("member"), member, edited={"bin/cc-member": "bin/cc_member"}),
                         ["check 'member' was removed"])
        text = self.BASE.replace('"tests/member.py", "tests/quarantine"]', '"tests/quarantine"]')
        self.assertEqual(self.faults(text, edited={"tests/member.py": "tests/m/member.py"}),
                         ["check 'member': paths lost core/tests/member.py"])

    def test_a_module_run_target_names_its_file(self):
        """perms 10-12: `python3 -m unittest tests.slack` names tests/slack.py, so the check stays while it exists."""
        self.assertEqual(M.run_files("bin/x && python3 -m unittest -v tests.a tests.b.c; echo done.ok"),
                         ["bin/x", "tests/a.py", "tests/b/c.py"])
        member = ("bin/cc-member", "tests/member.py", "tests/quarantine/a", "tests/quarantine/b/c",
                  "tests/member-lib.sh")
        unit = self.BASE.replace('run = "bin/cc-member selfcheck"',
                                 'run = "bin/cc-member selfcheck && python3 -m unittest tests.slack"')
        self.assertEqual(self.faults(self.drop("member", unit), member, unit), ["check 'member' was removed"])
        self.assertEqual(self.faults(self.drop("member", unit), member + ("tests/slack.py",), unit), [])

    def test_a_redirection_or_a_variable_names_no_run_file(self):
        """the Opus read of #1311: `2>/dev/null`, `</dev/null` and `core/bin/$t` are no files, and `;` is no part of
        a word."""
        self.assertEqual(M.run_files("bin/x selfcheck 2>/dev/null </dev/null >/dev/null; for t in a; do core/bin/$t"
                                     " -n; done"), ["bin/x"])
        self.assertEqual(M.run_files("bash -n bin/x; bin/y selfcheck"), ["bin/x", "bin/y"])
        # the Opus read of #1439: a redirection with no space splits off, so the tool before it still counts
        self.assertEqual(M.run_files("bin/x>/dev/null 2>&1; bin/y 2>out/log; bin/z<in/f >out/g; bin/t2>e"),
                         ["bin/x", "bin/y", "bin/z", "bin/t2"])
        # the Opus read of #1524: `&`, `|` and `;` with no space end a word too, and `-m` reads past a redirection
        self.assertEqual(M.run_files("bin/x&>/dev/null"), ["bin/x"])
        self.assertEqual(M.run_files("bin/x|grep ok"), ["bin/x"])
        self.assertEqual(M.run_files("bin/x;bin/y"), ["bin/x", "bin/y"])
        self.assertEqual(M.run_files("bin/x&&bin/y"), ["bin/x", "bin/y"])
        self.assertEqual(M.run_files("python3 -m unittest tests.test_x>/dev/null"), ["tests/test_x.py"])
        # a check whose only slash-words are redirections names no run file, so never_ran cannot let the head drop it
        member = ("bin/cc-member", "tests/member.py", "tests/quarantine/a", "tests/quarantine/b/c",
                  "tests/member-lib.sh")
        quiet = self.BASE.replace('run = "bin/cc-member selfcheck"', 'run = "cc-member selfcheck 2>/dev/null"')
        self.assertEqual(self.faults(self.drop("member", quiet), member, quiet), ["check 'member' was removed"])
        self.assertEqual(self.faults(self.drop("member", quiet), (), quiet), ["check 'member' was removed"])

    def test_a_backtick_paren_or_bang_ends_a_word(self):
        """perms' read of #1524: a backtick, `(`, `)` or `!` attached to the only tool a check names still leaves it
        named."""
        self.assertEqual(M.run_files("echo `bin/x selfcheck`"), ["bin/x"])
        self.assertEqual(M.run_files("(bin/x selfcheck)"), ["bin/x"])
        self.assertEqual(M.run_files("!bin/x selfcheck"), ["bin/x"])
        self.assertEqual(M.run_files("test -z $(bin/x list)"), ["bin/x"])
        self.assertEqual(M.run_files("x=$(bin/x) <(bin/y) bin/z |& cat; { bin/t; }; if ! bin/u; then :; fi"),
                         ["bin/x", "bin/y", "bin/z", "bin/t", "bin/u"])
        self.assertEqual(M.run_files("cat <<< core/bin/$(uname); core/bin/`uname`"), [])

    def test_a_backtick_paren_or_bang_keeps_the_modules_after_m(self):
        """perms' read of #1532: a backtick, `(`, `)` or `!` inside a -m command does not end its module list."""
        self.assertEqual(M.run_files("python3 -m unittest $(echo -v) tests.a"), ["tests/a.py"])
        self.assertEqual(M.run_files("python3 -m unittest -k 'x(y)' tests.a"), ["tests/a.py"])
        self.assertEqual(M.run_files("(python3 -m unittest tests.a)"), ["tests/a.py"])
        self.assertEqual(M.run_files("echo `python3 -m unittest tests.a`"), ["tests/a.py"])

    def test_a_backslash_continuation_keeps_the_first_module(self):
        """perms' read of #1524: `tests.a\\<newline>` is joined to the next line, so tests.a is still named."""
        self.assertEqual(M.run_files("python3 -m unittest tests.a\\\n  tests.b"), ["tests/a.py", "tests/b.py"])
        self.assertEqual(M.run_files("python3 -m \\\n unittest tests.a"), ["tests/a.py"])
        self.assertEqual(M.run_files("bin/x\\\n selfcheck"), ["bin/x"])

    def test_an_attached_m_names_its_modules(self):
        """perms' read of #1532: `-mX` is `-m X`, so the modules after it are named."""
        self.assertEqual(M.run_files("python3 -munittest tests.a tests.b"), ["tests/a.py", "tests/b.py"])
        self.assertEqual(M.run_files("python3 -mtests.a"), ["tests/a.py"])

    def test_the_first_word_reads_past_a_paren_backtick_bang_or_brace(self):
        """the Opus read of #1532: owns() takes the first word as the check's tool, so `(bin/x` must read bin/x."""
        for run in ("(bin/x selfcheck)", "`bin/x selfcheck`", "! bin/x selfcheck", "!bin/x selfcheck",
                    "{ bin/x selfcheck; }", "bin/x\\\n selfcheck"):
            self.assertEqual(M.run_file(run), "bin/x", run)
        m = M.Manifest(checks={"x": M.T.Check(name="x", run="(bin/x selfcheck)")})
        self.assertTrue(m.owns("x", "bin/x"))
        self.assertEqual(M.run_file("$(bin/x)"), "")

    def test_a_clustered_m_names_its_modules(self):
        """perms' read of this PR: `-Im` and `-BmX` are `-m` after python flags that take no value."""
        self.assertEqual(M.run_files("python3 -Im unittest tests.a"), ["tests/a.py"])
        self.assertEqual(M.run_files("python3 -Bmunittest tests.a"), ["tests/a.py"])
        self.assertEqual(M.run_files("python3 -Bmtests.a"), ["tests/a.py"])
        self.assertEqual(M.run_files("python3 -Wm unittest tests.a"), [])   # -W takes a value: m is it

    def test_a_backtick_word_does_not_reach_back_past_a_separator(self):
        """perms' read of this PR: the backtick word ends at a `;`, `&`, `|`, `(`, `)` or redirection before it."""
        self.assertEqual(M.run_files("core/bin/cc;x/`true`"), ["core/bin/cc"])
        self.assertEqual(M.run_files("bin/x;foo/`true selfcheck`"), ["bin/x"])
        self.assertEqual(M.run_files("bin/x&&y/`true`"), ["bin/x"])
        self.assertEqual(M.run_files("(bin/x)|y/`true`"), ["bin/x"])

    def test_an_escaped_backtick_neither_hides_nor_invents_a_tool(self):
        """perms' read of #1532: a backslash before a backtick is dropped, so `` \\`bin/x\\` `` names bin/x and not
        `bin/x\\`, and `` core/bin/\\`uname\\` `` names nothing."""
        self.assertEqual(M.run_files("echo \\`bin/x selfcheck\\`"), ["bin/x"])
        self.assertEqual(M.run_files("echo \\`bin/x\\`"), ["bin/x"])
        self.assertEqual(M.run_files("core/bin/\\`uname\\` selfcheck"), [])

    def test_a_quoted_separator_keeps_the_modules_after_it(self):
        """the Opus read of #1532: a `;`, `|` or `&` inside quotes does not end the modules after `-m`."""
        self.assertEqual(M.run_files('python3 -m unittest -k "a;b" tests.a'), ["tests/a.py"])
        self.assertEqual(M.run_files("python3 -m unittest -k 'a|b' tests.a tests.b"), ["tests/a.py", "tests/b.py"])
        self.assertEqual(M.run_files('python3 -m unittest -k "a&b" tests.a; echo x.y'), ["tests/a.py"])
        self.assertEqual(M.run_files('python3 -m unittest -k "a\\";b" tests.a'), ["tests/a.py"])
        self.assertEqual(M.run_files('echo "x;bin/y"'), ["bin/y"])

    def test_an_added_check_running_only_redirections_is_not_refused_for_its_tool(self):
        quiet = self.GHOST.replace("bin/cc-ghost selfcheck", "cc-ghost selfcheck </dev/null >/dev/null")
        base, head = AddOnly.two(None, self.BASE + quiet, self.BASE)
        self.assertEqual(M.widen_faults(base, head, self.trees()), [])

    def test_a_check_whose_run_names_no_file_or_a_survivor_never_goes(self):
        # `-m unittest discover` names no file: the check stays even with every path and fixture gone
        member = ("bin/cc-member", "tests/member.py", "tests/quarantine/a", "tests/quarantine/b/c",
                  "tests/member-lib.sh")
        unit = self.BASE.replace('run = "bin/cc-member selfcheck"', 'run = "python3 -m unittest discover"')
        self.assertEqual(self.faults(self.drop("member", unit), member, unit), ["check 'member' was removed"])
        # a run file that survives keeps it, though every path and fixture is deleted
        both = self.BASE.replace('run = "bin/cc-member selfcheck"', 'run = "bin/cc-member tests/slack.py"')
        self.assertEqual(self.faults(self.drop("member", both), member, both), ["check 'member' was removed"])
        self.assertEqual(self.faults(self.drop("member", both), member + ("tests/slack.py",), both), [])

    def test_where_class_and_cwd_never_narrow_even_on_a_deleted_file(self):
        everything = tuple(f[5:] for f in self.BASE_FILES)
        where = self.BASE.replace('class = "host"\nwhere = ["box", "laptop"]\nfixtures',
                                  'class = "host"\nwhere = ["box"]\nfixtures')
        self.assertEqual(self.faults(where, everything), ["check 'e2e-limit-episode': where lost laptop"])
        down = self.BASE.replace('run = "bin/cc-member selfcheck"\npaths = ["bin/cc-member", "tests/member.py", '
                                 '"tests/quarantine"]\nclass = "host"',
                                 'run = "bin/cc-member selfcheck"\npaths = ["bin/cc-member", "tests/member.py", '
                                 '"tests/quarantine"]\nclass = "box"')
        self.assertIn("check 'member': class moved from host down to box", self.faults(down, everything))

    def test_widen_drops_a_dead_check_and_never_takes_a_changed_run(self):
        text = self.drop("member").replace(" tests/member.py\"", "\"")
        base, head = AddOnly.two(None, text, self.BASE)
        dead = ("bin/cc-member", "tests/member.py", "tests/quarantine/a", "tests/quarantine/b/c", "tests/member-lib.sh")
        w = M.widen(base, head, self.trees(dead))
        self.assertNotIn("member", w.checks)
        self.assertEqual(w.checks["py-compile-tests"].run, base.checks["py-compile-tests"].run)
        # a survivor keeps the check
        w = M.widen(base, head, self.trees(dead[2:]))
        self.assertIn("member", w.checks)
        self.assertIn("member", M.widen(base, head).checks)   # and with no trees nothing narrows

    def test_on_git_trees_and_through_plan(self):
        r = Repo(self)
        # bin/a and bin/b share bin/c's bytes, and a blob at any path in the head keeps it: c gets its own first
        r.base = r.commit("own c", {"core/bin/c": "#!/bin/sh\necho c\n"})
        manifest = CORE_MANIFEST.replace(
            '[[check]]\nname = "c"\nrun = "bin/c selfcheck"\npaths = ["bin/c"]\nclass = "host"\n', "")
        # a rename (bin/c -> bin/d) with the check dropped is refused on real trees
        os.rename(os.path.join(r.root, "core/bin/c"), os.path.join(r.root, "core/bin/d"))
        moved = r.commit("moved", {"core/tests/LANDING.toml": manifest})
        ok, text = M.widen_check(r.root, r.base, moved)
        self.assertFalse(ok)
        self.assertIn("check 'c' was removed", text)
        os.remove(os.path.join(r.root, "core/bin/d"))
        dead = r.commit("dead")
        ok, text = M.widen_check(r.root, r.base, dead)
        self.assertTrue(ok, text)
        p = P.plan(r.root, r.base, dead, P.changed(r.root, r.base, dead))
        self.assertNotIn("c", p.checks)
        self.assertIn(M.BUILTIN, p.checks)
        # the working copy reads its own files and hashes them: c's bytes at a new, untracked path are a move
        write(r.root, {"core/bin/e": "#!/bin/sh\necho c\n"})
        self.assertFalse(M.widen_check(r.root, r.base, "")[0])
        os.remove(os.path.join(r.root, "core/bin/e"))
        self.assertTrue(M.widen_check(r.root, r.base, "")[0])
        # and core/bin/c back on disk makes the removal a fault again
        write(r.root, {"core/bin/c": "#!/bin/sh\n"})
        ok, text = M.widen_check(r.root, r.base, "")
        self.assertFalse(ok)
        self.assertIn("check 'c' was removed", text)
        kept = r.commit("kept")
        self.assertFalse(M.widen_check(r.root, r.base, kept)[0])
        self.assertIn("c", P.plan(r.root, r.base, kept, ["core/tests/LANDING.toml", "core/bin/c"]).checks)


class Prose(unittest.TestCase):
    def test_prose_is_docs_pdfs_images_and_markdown(self):
        for p in ("docs/x.md", "docs/a/b.txt", "core/docs/DESIGN.md", "README.md", "a/b.pdf", "fig.svg"):
            self.assertTrue(P.is_prose(p), p)

    def test_instruction_files_are_never_prose(self):
        for p in ("core/templates/brief.md", "home/CLAUDE.md", "core/config/review-prompt.md",
                  "core/agents/builder.md", "docs/REVIEW.md", "config/x.md", "bin/a", "core/tests/check.sh"):
            self.assertFalse(P.is_prose(p), p)


class Select(unittest.TestCase):
    def setUp(self):
        r = Repo(self)
        self.root, self.base = r.root, r.base
        self.m = M.load(r.root, r.base)

    def sel(self, *files):
        return P.select(self.m, list(files))

    def test_a_leaf_tool_selects_its_checks_and_its_callers_not_further(self):
        p = self.sel("core/bin/a")
        # a's own (sc-a, a), b (its caller, one hop), identity (core/**); not c (b's caller, two hops)
        self.assertEqual(p.checks, ["a", "b", "identity", "sc-a"])
        self.assertNotIn("c", p.checks)
        # e2e-x owns b too, so it is reached, but it is box-class: the tip runs it, not the pre-merge plan
        self.assertEqual(p.extra["reached"], {"b": "core/bin/a", "e2e-x": "core/bin/a"})
        self.assertEqual(p.extra["tip"], ["e2e-x"])
        self.assertEqual((p.klass, p.paid, p.unowned), (T.LEAF, False, []))

    def test_a_static_caller_check_is_not_reached(self):
        self.m.checks["sc-b"] = T.Check(name="sc-b", run="true", paths=["core/bin/b"], klass=T.STATIC)
        self.assertNotIn("sc-b", self.sel("core/bin/a").checks)
        self.assertIn("sc-b", self.sel("core/bin/b").checks)

    def test_box_checks_go_to_the_tip_unless_the_change_is_gate_first(self):
        p = self.sel("core/bin/b")
        self.assertNotIn("e2e-x", p.checks)
        self.assertEqual(p.extra["tip"], ["e2e-x"])
        self.assertTrue(p.paid)
        g = self.sel("core/bin/b", "core/bin/guard")
        self.assertEqual(g.klass, T.GATE_FIRST)
        self.assertIn("e2e-x", g.checks)
        self.assertEqual(g.extra["tip"], [])

    def test_prose_reaches_only_static_checks(self):
        # core/docs is prose: the static checks owning it run (docs-lint, identity), and nothing else
        p = self.sel("core/docs/DESIGN.md")
        self.assertEqual((p.checks, p.klass, p.unowned), (["docs-lint", "identity"], T.DOCS, []))
        # prose nobody owns is not unowned: it widens to nothing
        p = self.sel("docs/guide.md")
        self.assertEqual((p.checks, p.klass, p.unowned), ([], T.DOCS, []))
        # a non-static check owning a prose path does not run for it
        self.m.checks["md-host"] = T.Check(name="md-host", run="true", paths=["core/docs/**"], klass=T.HOST)
        self.assertNotIn("md-host", self.sel("core/docs/DESIGN.md").checks)

    def test_an_unowned_path_widens_to_the_default_set_and_is_named(self):
        p = self.sel("home/CLAUDE.md")
        self.assertEqual((p.checks, p.unowned, p.klass), (["check-sh"], ["home/CLAUDE.md"], T.WIDE))
        self.assertEqual(self.sel("core/bin/c").unowned, [])

    def test_an_add_only_change_is_leaf_and_does_not_widen(self):
        # owner 2026-09-28: a brand-new file that touches nothing existing is leaf, not the default set
        p = P.select(self.m, ["library/new-tool"], added=["library/new-tool"])
        self.assertEqual((p.checks, p.klass, p.extra["add_only"]), ([], T.LEAF, ["library/new-tool"]))
        self.assertEqual(p.unowned, ["library/new-tool"])   # still named for the card
        # under core/ the identity check owns it, so it still runs
        p = P.select(self.m, ["core/bin/new-tool"], added=["core/bin/new-tool"])
        self.assertEqual((p.checks, p.klass), (["identity"], T.LEAF))
        # one modified file beside it: not add-only, so the unowned new path widens as before
        p = P.select(self.m, ["library/new-tool", "core/bin/a"], added=["library/new-tool"])
        self.assertEqual(p.klass, T.WIDE)
        self.assertIn("check-sh", p.checks)
        # a new file somewhere loaded by glob (a hook, a unit, a template, an agent) widens even when add-only
        # (under core/ the identity check owns every path, so nothing there is unowned to begin with)
        for f in ("home/new.md", "config/systemd-user/x.service", ".githooks/post-merge", ".github/workflows/x.yml",
                  "skills/x/run.sh", "agents/x.md", "tests/new-case.sh",
                  # read by name, not by place: every top-level file and every dotfile or dot-directory widens
                  ".mcp.json", ".gitattributes", ".gitmodules", ".envrc", "Makefile", "library/.env", "library/.x/y"):
            p = P.select(self.m, [f], added=[f])
            self.assertIn("check-sh", p.checks, f)
            self.assertNotIn("add_only", p.extra, f)
        # the class lists still decide: an added file on the gate-first list is gate-first
        self.assertEqual(P.select(self.m, ["core/bin/guard"], added=["core/bin/guard"]).klass, T.GATE_FIRST)

    def test_code_no_check_runs_on_is_paid_so_it_is_read(self):
        # finding 10-04: fund#2 landed with "plan checks [], results {}, review_key ''" — a repo with no manifest
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = os.path.join(d.name, "fund")
        os.mkdir(root)
        with mock.patch.dict(os.environ, {"CC_DEV": d.name}):   # $CC_DEV/fund: a checkout the host made
            bare = self.bare_repo(root)
        p = P.select(bare, ["collectors/old.py", "collectors/new.py", "README.md"], added=["collectors/new.py"])
        self.assertEqual(bare.checks, {})
        self.assertEqual((p.checks, p.extra["tip"], p.paid, p.extra.get("ungated")), ([], [], True, True))
        p = P.select(bare, ["collectors/new.py"], added=["collectors/new.py"])   # add-only: still nothing runs
        self.assertTrue(p.paid)
        # padding: a change that also touches tests/reach.tsv selects manifest-widen, which reads no code
        p = P.select(bare, ["collectors/new.py", "tests/reach.tsv"], added=["collectors/new.py"])
        self.assertEqual((p.checks, p.paid), ([M.BUILTIN], True))
        # kept paid: changed data (it may be read by code), and code added among data
        self.assertTrue(P.select(bare, ["collectors/table.csv"]).paid)
        self.assertTrue(P.select(bare, ["data/x.csv", "lib/run.py"], added=["data/x.csv", "lib/run.py"]).paid)
        self.assertTrue(P.select(bare, ["config/x.json"], added=["config/x.json"]).paid)   # loaded by place
        # perms 10-12: inert()'s two guards bound the exemption. Each of these is added data or prose by its
        # extension, but something loads it by place or name (loads_by_nothing) or it instructs (NOT_PROSE): read.
        for f in (".github/workflows/ci.yml", ".mcp.json", "tests/fixtures/x.json", "lib/REVIEW.md"):
            p = P.select(bare, [f], added=[f])
            self.assertEqual((p.paid, p.extra.get("ungated")), (True, True), f)
        # kept unpaid: added data and assets, which no code is in (planning 10-12)
        p = P.select(bare, ["data/x.csv", "assets/logo.png", "docs/a.md"], added=["data/x.csv", "assets/logo.png"])
        self.assertEqual((p.checks, p.unowned, p.paid), ([], ["data/x.csv"], False))
        self.assertNotIn("ungated", p.extra)
        # kept unpaid: prose alone, which nothing unowned is in
        p = P.select(bare, ["README.md", "docs/x.md"])
        self.assertEqual((p.checks, p.unowned, p.paid), ([], [], False))
        self.assertNotIn("ungated", p.extra)
        # kept unpaid: a check runs on the change (owned, or widened to by the unowned path)
        for files in (["core/bin/c"], ["home/x.sh"]):
            p = self.sel(*files)
            self.assertTrue(p.checks, files)
            self.assertFalse(p.paid, files)
            self.assertNotIn("ungated", p.extra, files)

    def test_code_a_box_check_runs_after_the_merge_is_not_ungated(self):
        # "no check runs on the change, before the merge or after it": the tip's box check is one after it
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = os.path.join(d.name, "fund")
        os.mkdir(root)
        with mock.patch.dict(os.environ, {"CC_DEV": d.name}):
            bare = self.bare_repo(root)
        files = ["collectors/old.py", "collectors/new.py"]
        self.assertTrue(P.select(bare, files, added=["collectors/new.py"]).paid)   # suppressed: nothing runs
        bare.checks["e2e"] = T.Check(name="e2e", run="true", paths=["collectors/old.py"], klass=T.BOX)
        p = P.select(bare, files, added=["collectors/new.py"])
        self.assertEqual((p.checks, p.extra["tip"], p.unowned), ([], ["e2e"], ["collectors/new.py"]))
        self.assertEqual((p.paid, p.extra.get("ungated")), (False, None))

    @staticmethod
    def bare_repo(root):
        git(root, "init", "-q")
        write(root, {"collectors/old.py": "x = 1\n", "README.md": "fund\n"})
        git(root, "add", "-A")
        git(root, "commit", "-qm", "base")
        return M.load(root, git(root, "rev-parse", "HEAD"))

    def test_the_class_order_lander_gate_first(self):
        self.assertEqual(self.sel("core/lander/plan.py", "core/bin/guard").klass, T.LANDER)
        self.assertEqual(self.sel("tests/LANDING-policy.toml").klass, T.LANDER)   # the policy file itself
        self.assertEqual(self.sel("core/bin/a").klass, T.LEAF)

    def test_a_lander_file_on_a_policy_protected_list_still_goes_to_lander_self(self):
        # tools simplification (#1508): a protected class ranked above lander, which the lane never acted on, let it
        # skip lander-self
        self.m.policy.protected = ["core/lander/**"]
        self.assertEqual(self.sel("core/lander/plan.py").klass, T.LANDER)

    def test_a_manifest_change_selects_manifest_widen(self):
        p = self.sel("tests/LANDING.toml")
        self.assertIn(M.BUILTIN, p.checks)
        self.assertNotIn(M.BUILTIN, self.sel("core/bin/a").checks)

    def test_a_default_check_the_manifest_lacks_is_a_fault(self):
        self.m.policy = T.Policy(default=["nope"])
        p = self.sel("home/x")
        self.assertIn("nope", " ".join(p.extra["faults"]))
        self.assertNotIn("nope", p.checks)


class PlanOnGit(unittest.TestCase):
    def test_plan_reads_the_base_and_lets_the_head_only_widen(self):
        r = Repo(self)
        # the head drops check `a` and adds `d` owning core/bin/a: `a` still runs (base rules), `d` runs too
        head_text = CORE_MANIFEST.replace('name = "a"\nrun = "bin/a selfcheck"', 'name = "d"\nrun = "true"')
        head = r.commit("head", {"core/tests/LANDING.toml": head_text, "core/bin/a": "#!/bin/sh\necho\n"})
        files = P.changed(r.root, r.base, head)
        self.assertEqual(sorted(files), ["core/bin/a", "core/tests/LANDING.toml"])
        p = P.plan(r.root, r.base, head, files)
        self.assertIn("a", p.checks)
        self.assertIn("d", p.checks)
        self.assertIn(M.BUILTIN, p.checks)
        self.assertEqual(p.klass, T.LEAF)

    def test_ungated_is_the_bases_word_not_a_check_the_head_adds(self):
        # perms 10-12: "a plan-level probe with run='true' over ** went unpaid" — the head's own LANDING.toml
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = os.path.join(d.name, "fund")
        os.mkdir(root)
        with mock.patch.dict(os.environ, {"CC_DEV": d.name}):
            git(root, "init", "-q")
            write(root, {"collectors/old.py": "x = 1\n"})
            git(root, "add", "-A")
            git(root, "commit", "-qm", "base")
            base = git(root, "rev-parse", "HEAD")
            write(root, {"collectors/old.py": "x = 2\n"})
            git(root, "commit", "-qam", "code")
            code = git(root, "rev-parse", "HEAD")
            write(root, {"tests/LANDING.toml": '[[check]]\nname = "probe"\nrun = "true"\npaths = ["**"]\n'})
            git(root, "add", "-A")
            git(root, "commit", "-qm", "probe")
            probe = git(root, "rev-parse", "HEAD")
            p = P.plan(root, base, code, P.changed(root, base, code))
            self.assertEqual((p.paid, p.extra.get("ungated")), (True, True))   # control: nothing runs on it
            files = P.changed(root, base, probe)
            self.assertIn("probe", M.widen(M.load(root, base), M.load(root, probe, strict=False)).checks)
            p = P.plan(root, base, probe, files)
            self.assertIn("probe", p.checks)
            self.assertEqual((p.paid, p.extra.get("ungated")), (True, True))

    def test_plan_on_a_head_that_removes_the_policy_is_lander_class(self):
        r = Repo(self)
        os.unlink(os.path.join(r.root, "tests/LANDING-policy.toml"))
        head = r.commit("rm")
        p = P.plan(r.root, r.base, head, P.changed(r.root, r.base, head))
        self.assertEqual(p.klass, T.LANDER)

    def test_plan_sees_an_added_file_as_added_and_a_modified_one_as_not(self):
        r = Repo(self)
        head = r.commit("add", {"library/new-tool": "#!/bin/sh\n"})
        p = P.plan(r.root, r.base, head, P.changed(r.root, r.base, head))
        self.assertEqual((p.checks, p.klass), ([], T.LEAF))
        head2 = r.commit("modify too", {"core/bin/c": "#!/bin/sh\necho\n"})
        p = P.plan(r.root, r.base, head2, P.changed(r.root, r.base, head2))
        self.assertEqual(p.klass, T.WIDE)
        self.assertIn("check-sh", p.checks)
        os.unlink(os.path.join(r.root, "core/bin/c"))
        head3 = r.commit("delete")
        self.assertEqual(P.added_files(r.root, head2, head3, ["core/bin/c"]), set())

    def test_plan_is_pure(self):
        r = Repo(self)
        before = git(r.root, "status", "--porcelain")
        P.plan(r.root, r.base, r.base, ["core/bin/a"])
        self.assertEqual(git(r.root, "status", "--porcelain"), before)


class GeneratedReach(unittest.TestCase):
    """brief: a reach.tsv change that matches what the generator writes on the PR's merge tree is not a lander edit;
    one that does not still goes to lander-self. Each case builds its own repo."""
    LANDER_POLICY = POLICY.replace('lander = ["core/lander/**"]',
                                   'lander = ["core/lander/**", "core/tests/reach.tsv", "tests/reach.tsv"]')
    CALLS = {"core/bin/b": '#!/bin/sh\n"$BIN/a"\n', "core/bin/c": '#!/bin/sh\n"$BIN/b"\n'}

    def repo(self):
        r = Repo(self, {"tests/LANDING-policy.toml": self.LANDER_POLICY, **self.CALLS})
        self.assertEqual(R.generate_at(r.root, r.base, "core/"), [("b", "a"), ("c", "b")])
        return r

    def plan(self, r, head):
        return P.plan(r.root, r.base, head, P.changed(r.root, r.base, head))

    def test_a_new_tool_with_its_callers_and_regenerated_reach_is_not_lander_class(self):
        r = self.repo()
        head = r.commit("new tool d, c calls it", {
            "core/bin/d": "#!/bin/sh\n", "core/bin/c": '#!/bin/sh\n"$BIN/b"\n"$BIN/d"\n',
            "core/tests/reach.tsv": R.render([("b", "a"), ("c", "b"), ("c", "d")])})
        p = self.plan(r, head)
        self.assertNotEqual(p.klass, T.LANDER)
        self.assertIn(M.BUILTIN, p.checks)   # the reach file still selects manifest-widen

    def test_an_authored_edit_that_deletes_a_line_is_lander_class(self):
        """render() drops the base's comment line, so the diff is not pure additions and nothing generates a -> d."""
        r = self.repo()
        head = r.commit("hand edge", {"core/bin/d": "#!/bin/sh\n",
                                      "core/tests/reach.tsv": R.render([("b", "a"), ("c", "b"), ("a", "d")])})
        self.assertEqual(self.plan(r, head).klass, T.LANDER)

    def test_an_authored_edge_added_alone_is_not_lander_class(self):
        """perms' terms (#1234): a reach.tsv diff of pure additions, with a clean manifest, plans with its other
        files; the same edge with one base line taken out stays lander."""
        r = self.repo()
        git(r.root, "checkout", "-qb", "add")
        head = r.commit("hand edge", {"core/bin/d": "#!/bin/sh\n", "core/tests/reach.tsv": REACH + "a\td\n"})
        files = P.changed(r.root, r.base, head)
        self.assertEqual(P.generated_reach(r.root, r.base, head, files), set())   # authored, not generated
        p = self.plan(r, head)
        self.assertNotEqual(p.klass, T.LANDER)
        self.assertIn(M.BUILTIN, p.checks)
        git(r.root, "checkout", "-q", r.base)
        cut = r.commit("hand edge, b -> a gone", {"core/bin/d": "#!/bin/sh\n",
                                                  "core/tests/reach.tsv": "# a comment\nc\tb\na\td\n"})
        self.assertEqual(self.plan(r, cut).klass, T.LANDER)

    def test_a_dropped_edge_the_code_still_makes_is_lander_class(self):
        r = self.repo()
        head = r.commit("drop b->a", {"core/bin/c": '#!/bin/sh\n"$BIN/b"\necho\n',
                                      "core/tests/reach.tsv": R.render([("c", "b")])})
        self.assertEqual(self.plan(r, head).klass, T.LANDER)

    def test_the_match_is_on_the_merge_tree_not_the_head(self):
        r = self.repo()
        git(r.root, "checkout", "-qb", "pr")
        head = r.commit("e calls a", {"core/bin/e": '#!/bin/sh\n"$BIN/a"\n',
                                      "core/tests/reach.tsv": R.render([("b", "a"), ("c", "b"), ("e", "a")])})
        self.assertNotEqual(self.plan(r, head).klass, T.LANDER)
        git(r.root, "checkout", "-q", "-")
        # main moves on and deletes a: on the merge tree nothing generates e -> a, so the PR's edge is authored there
        os.unlink(os.path.join(r.root, "core/bin/a"))
        main = r.commit("rm a", {"core/tests/reach.tsv": R.render([("c", "b")])})
        p = P.plan(r.root, main, head, P.changed(r.root, main, head))
        self.assertEqual(p.klass, T.LANDER)

    def test_drift_already_on_the_base_does_not_stop_a_pr_that_adds_its_own_edge(self):
        """main's reach.tsv lacks b -> a, which its code makes (an earlier PR never added it). A PR that adds only
        its own generated edge is not lander-class; one that adds the same edge plus an authored one is not generated,
        and is not lander-class either only because it deletes no line (perms' terms, #1234)."""
        r = Repo(self, {"tests/LANDING-policy.toml": self.LANDER_POLICY, **self.CALLS,
                        "core/tests/reach.tsv": R.render([("c", "b")])})
        files = {"core/bin/d": "#!/bin/sh\n", "core/bin/c": '#!/bin/sh\n"$BIN/b"\n"$BIN/d"\n'}
        git(r.root, "checkout", "-qb", "ok")
        ok = r.commit("own edge", {**files, "core/tests/reach.tsv": R.render([("c", "b"), ("c", "d")])})
        self.assertNotEqual(self.plan(r, ok).klass, T.LANDER)
        git(r.root, "checkout", "-q", r.base)
        bad = r.commit("own edge and a made one",
                       {**files, "core/tests/reach.tsv": R.render([("a", "c"), ("c", "b"), ("c", "d")])})
        self.assertEqual(P.generated_reach(r.root, r.base, bad, P.changed(r.root, r.base, bad)), set())
        self.assertNotEqual(self.plan(r, bad).klass, T.LANDER)

    def test_a_deleted_reach_file_is_lander_class(self):
        r = self.repo()
        os.unlink(os.path.join(r.root, "core/tests/reach.tsv"))
        self.assertEqual(self.plan(r, r.commit("rm reach")).klass, T.LANDER)

    def test_a_working_copy_proves_nothing(self):
        r = self.repo()
        write(r.root, {"core/bin/d": "#!/bin/sh\n", "core/bin/c": '#!/bin/sh\n"$BIN/b"\n"$BIN/d"\n',
                       "core/tests/reach.tsv": R.render([("b", "a"), ("c", "b"), ("c", "d")])})
        self.assertEqual(P.plan(r.root, r.base, "", P.changed(r.root, r.base, "")).klass, T.LANDER)

    def test_other_lander_files_still_route_to_lander_self(self):
        r = self.repo()
        head = r.commit("reach and a lander file", {
            "core/bin/d": "#!/bin/sh\n", "core/bin/c": '#!/bin/sh\n"$BIN/b"\n"$BIN/d"\n',
            "core/tests/reach.tsv": R.render([("b", "a"), ("c", "b"), ("c", "d")]),
            "core/lander/x.py": "x = 1\n"})
        self.assertEqual(self.plan(r, head).klass, T.LANDER)
        self.assertEqual(P.select(M.load(r.root, r.base), ["core/tests/reach.tsv"]).klass, T.LANDER)

    def test_a_replace_ref_in_the_checkout_cannot_make_an_authored_edge_match(self):
        """review (security, Opus): the check read the checkout's git, so a planted refs/replace swapped the head for
        a commit whose code makes the authored edge. It reads sealed now: the swap is invisible and the PR stays
        lander-class."""
        r = self.repo()
        reach = R.render([("a", "d"), ("b", "a"), ("c", "b")])
        git(r.root, "checkout", "-qb", "pr")
        head = r.commit("hand edge a -> d", {"core/bin/d": "#!/bin/sh\n", "core/tests/reach.tsv": reach})
        git(r.root, "checkout", "-q", r.base)
        fake = r.commit("a calls d", {"core/bin/d": "#!/bin/sh\n", "core/bin/a": '#!/bin/sh\n"$BIN/d"\n',
                                      "core/tests/reach.tsv": reach})
        git(r.root, "replace", head, fake)
        # the plant is live: the checkout's own merge of the head shows a calling d
        tree = git(r.root, "merge-tree", "--write-tree", r.base, head).split("\n")[0]
        self.assertIn("$BIN/d", git(r.root, "cat-file", "blob", f"{tree}:core/bin/a"))
        files = ["core/bin/d", "core/tests/reach.tsv"]
        self.assertEqual(P.generated_reach(r.root, r.base, head, files), set())
        self.assertEqual(P.plan(r.root, r.base, head, files).klass, T.LANDER)
        self.assertNotIn(("a", "d"), R.generate_at(r.root, head, "core/"))

    def test_a_tool_name_with_a_control_character_proves_nothing(self):
        """review (security): a name holding a newline shifted which text `cat-file --batch` handed to which file.
        Blobs are read by id now, and any tool name with a control character leaves the change lander-class."""
        r = self.repo()
        change = {"core/bin/d": "#!/bin/sh\n", "core/bin/c": '#!/bin/sh\n"$BIN/b"\n"$BIN/d"\n',
                  "core/tests/reach.tsv": R.render([("b", "a"), ("c", "b"), ("c", "d")])}
        git(r.root, "checkout", "-qb", "ok")
        self.assertNotEqual(self.plan(r, r.commit("generated", change)).klass, T.LANDER)
        for name in ("x\ny", "x\ty", "x\x7fy"):
            git(r.root, "checkout", "-q", r.base)
            head = r.commit(f"generated and {name!r}", {**change, f"core/bin/{name}": "#!/bin/sh\n"})
            self.assertEqual(self.plan(r, head).klass, T.LANDER, repr(name))
            with self.assertRaises(OSError):
                R.generate_at(r.root, head, "core/")

    def test_a_sealed_read_git_cannot_make_or_a_conflicting_merge_proves_nothing(self):
        r = self.repo()
        files = ["core/tests/reach.tsv"]
        for bad in ("0" * 40, "--output=x"):
            self.assertEqual(P.generated_reach(r.root, r.base, bad, files), set(), bad)
        git(r.root, "checkout", "-qb", "pr")
        head = r.commit("c calls d", {"core/bin/d": "#!/bin/sh\n", "core/bin/c": '#!/bin/sh\n"$BIN/b"\n"$BIN/d"\n',
                                      "core/tests/reach.tsv": R.render([("b", "a"), ("c", "b"), ("c", "d")])})
        self.assertEqual(P.generated_reach(r.root, r.base, head, files), set(files))
        git(r.root, "checkout", "-q", r.base)
        main = r.commit("c changes too", {"core/bin/c": '#!/bin/sh\n"$BIN/b"\necho\n'})
        self.assertEqual(P.generated_reach(r.root, main, head, files), set())

    def test_a_pr_cannot_pick_the_recipe_by_adding_a_directory(self):
        """review (security): the tree generator chose its recipe from which directories existed, so a PR that added
        a top-level bin/README made the overlay's generator read bin/ alone, want no edges, and pass a reach file
        emptied by hand. The recipe is pinned per prefix now, and a tree laid out otherwise proves nothing."""
        overlay = {"bin-private/p": '"$BIN/c"\n', "bin-private/q": '"$BIN/p"\n',
                   "tests/reach.tsv": R.render([("p", "c"), ("q", "p")])}
        r = Repo(self, {"tests/LANDING-policy.toml": self.LANDER_POLICY, **self.CALLS, **overlay})
        self.assertEqual(R.generate_at(r.root, r.base, ""), [("p", "c"), ("q", "p")])
        git(r.root, "checkout", "-qb", "ok")
        ok = r.commit("r calls q", {"bin-private/r": '"$BIN/q"\n',
                                    "tests/reach.tsv": R.render([("p", "c"), ("q", "p"), ("r", "q")])})
        self.assertNotEqual(self.plan(r, ok).klass, T.LANDER)
        git(r.root, "checkout", "-q", r.base)
        bad = r.commit("steer", {"bin/README": "x\n", "tests/reach.tsv": R.render([])})
        self.assertEqual(self.plan(r, bad).klass, T.LANDER)
        with self.assertRaises(OSError):
            R.generate_at(r.root, bad, "")

    def test_a_symlinked_tool_proves_something_only_when_it_links_to_a_regular_file(self):
        """review (security): a link was followed one hop, so a link to a dangling link whose target string reads
        `$BIN/a` made the generator write an edge a checkout never makes. A link to a link, a broken link and a link
        to a directory now prove nothing; a link to a regular file still does."""
        r = self.repo()
        git(r.root, "checkout", "-qb", "ok")
        write(r.root, {"lib/real.py": '"$BIN/a"\n'})
        os.symlink("../../lib/real.py", os.path.join(r.root, "core/bin/e"))
        ok = r.commit("e links to real.py", {"core/tests/reach.tsv": R.render([("b", "a"), ("c", "b"), ("e", "a")])})
        self.assertNotEqual(self.plan(r, ok).klass, T.LANDER)
        for name, how in (("chain", ["g", "$BIN/a"]), ("broken", ["nowhere"]), ("dir", ["../../lib"])):
            git(r.root, "checkout", "-q", r.base)
            write(r.root, {"lib/real.py": '"$BIN/a"\n'})
            os.symlink(how[0], os.path.join(r.root, "core/bin/e"))
            if len(how) > 1:
                os.symlink(how[1], os.path.join(r.root, "core/bin/g"))
            head = r.commit(f"e is a {name} link",
                            {"core/tests/reach.tsv": R.render([("b", "a"), ("c", "b"), ("e", "a")])})
            self.assertNotIn(("e", "a"), R.generate(os.path.join(r.root, "core")), name)
            self.assertEqual(self.plan(r, head).klass, T.LANDER, name)
            with self.assertRaises(OSError, msg=name):
                R.generate_at(r.root, head, "core/")

    def test_the_tree_generator_agrees_with_the_checkout_generator(self):
        """Core's layout and the overlay's (callers bin-private/, callees it and core/bin/), a symlinked tool read at
        its target, and a dotfile skipped, on both generators."""
        r = self.repo()
        head = r.commit("overlay", {"bin-private/p": '"$BIN/c"\n', "bin-private/q": '"$BIN/p"\n',
                                    "lib/real.py": 'BIN / "a"\n', "core/bin/.hidden": '"$BIN/a"\n'})
        os.symlink("../../lib/real.py", os.path.join(r.root, "core/bin/e"))
        head = r.commit("symlink")
        self.assertEqual(R.generate_at(r.root, head, "core/"), R.generate(os.path.join(r.root, "core")))
        self.assertIn(("e", "a"), R.generate_at(r.root, head, "core/"))
        self.assertEqual(R.generate_at(r.root, head, ""),
                         R.generate(r.root, ["bin-private"], ["bin-private", "core/bin"], []))
        self.assertEqual(R.generate_at(r.root, head, ""), [("p", "c"), ("q", "p")])


class CleanManifest(unittest.TestCase):
    """perms' terms (#1234): a LANDING.toml / reach.tsv edit that only widens inside the sandbox, or drops only what
    the head deletes, plans with the PR's other files; anything else stays lander-class. Each case builds its own
    repo, with the manifests and reach files on the policy's lander list as they are in this repo."""
    POLICY = POLICY.replace('lander = ["core/lander/**"]', 'lander = ["core/lander/**", "core/tests/LANDING.toml", '
                            '"tests/LANDING.toml", "core/tests/reach.tsv", "tests/reach.tsv"]')
    NEW = '\n[[check]]\nname = "d"\nrun = "bin/d selfcheck"\npaths = ["bin/d"]\nclass = "hermetic"\n'

    def repo(self, extra=None):
        # bin/c gets bytes of its own: a delete is judged by blob, and a, b and c would otherwise share one
        return Repo(self, {"tests/LANDING-policy.toml": self.POLICY, "core/bin/c": "#!/bin/sh\necho c\n",
                           **(extra or {})})

    def plan(self, r, head, base=None):
        base = base or r.base
        return P.plan(r.root, base, head, P.changed(r.root, base, head))

    def drop_c(self):
        """CORE_MANIFEST with check c cut out."""
        start = CORE_MANIFEST.index('[[check]]\nname = "c"')
        return CORE_MANIFEST[:start] + CORE_MANIFEST[CORE_MANIFEST.index("[[check]]", start + 1):]

    def test_an_added_hermetic_check_plans_leaf_or_wide(self):
        r = self.repo()
        head = r.commit("tool d and its check", {"core/bin/d": "#!/bin/sh\n",
                                                 "core/tests/LANDING.toml": CORE_MANIFEST + self.NEW})
        p = self.plan(r, head)
        self.assertIn(p.klass, (T.LEAF, T.WIDE))
        self.assertIn(M.BUILTIN, p.checks)   # manifest-widen runs on every such plan
        self.assertIn("d", p.checks)

    def test_an_added_host_check_is_still_lander_class(self):
        r = self.repo()
        head = r.commit("host check d", {"core/bin/d": "#!/bin/sh\n", "core/tests/LANDING.toml": CORE_MANIFEST
                                         + self.NEW.replace('class = "hermetic"', 'class = "host"')})
        self.assertEqual(self.plan(r, head).klass, T.LANDER)

    def test_a_changed_run_class_or_where_is_still_lander_class(self):
        r = self.repo()
        for what, text in {"run": CORE_MANIFEST.replace('run = "bin/c selfcheck"', 'run = "bin/c selfcheck -v"'),
                           "class": CORE_MANIFEST.replace('run = "bash -n bin/a"\npaths = ["bin/a"]\n'
                                                          'class = "static"', 'run = "bash -n bin/a"\n'
                                                          'paths = ["bin/a"]\nclass = "hermetic"'),
                           "where": CORE_MANIFEST.replace('paths = ["bin/c"]', 'paths = ["bin/c"]\n'
                                                          'where = ["box", "laptop"]')}.items():
            git(r.root, "checkout", "-q", r.base)
            head = r.commit(what, {"core/bin/d": "#!/bin/sh\n", "core/tests/LANDING.toml": text})
            self.assertEqual(self.plan(r, head).klass, T.LANDER, what)

    def test_a_path_added_to_a_host_check_is_clean(self):
        """It triggers the unsandboxed check on more changes; perms allowed it, and the PR body says so."""
        r = self.repo()
        head = r.commit("c owns d", {"core/bin/d": "#!/bin/sh\n", "core/tests/LANDING.toml":
                                     CORE_MANIFEST.replace('paths = ["bin/c"]', 'paths = ["bin/c", "bin/d"]')})
        p = self.plan(r, head)
        self.assertNotEqual(p.klass, T.LANDER)
        self.assertIn("c", p.checks)

    def test_a_deleted_file_and_its_dropped_check_plan_clean_and_a_move_does_not(self):
        r = self.repo()
        git(r.root, "checkout", "-qb", "rm")
        os.unlink(os.path.join(r.root, "core/bin/c"))
        gone = r.commit("rm c and its check", {"core/tests/LANDING.toml": self.drop_c()})
        p = self.plan(r, gone)
        self.assertNotEqual(p.klass, T.LANDER)
        self.assertNotIn("c", p.checks)   # not run on the file it named
        git(r.root, "checkout", "-q", r.base)
        git(r.root, "mv", "core/bin/c", "core/bin/c2")
        moved = r.commit("mv c and drop its check", {"core/tests/LANDING.toml": self.drop_c()})
        self.assertEqual(self.plan(r, moved).klass, T.LANDER)

    def test_a_deleted_file_keeps_its_class_when_its_check_goes_too(self):
        """Reads come from the strictest class over every file, deleted ones included: dropping a gate-first file
        with its check is gate-first, and a deleted file on the lander list keeps the change lander-class."""
        guard = '\n[[check]]\nname = "guard"\nrun = "bin/guard selfcheck"\npaths = ["bin/guard"]\nclass = "host"\n'
        r = self.repo({"core/bin/guard": "#!/bin/sh\necho guard\n", "core/lander/x.py": "x = 1\n",
                       "core/tests/LANDING.toml": CORE_MANIFEST + guard})
        git(r.root, "checkout", "-qb", "rm")
        os.unlink(os.path.join(r.root, "core/bin/guard"))
        head = r.commit("rm guard and its check", {"core/tests/LANDING.toml": CORE_MANIFEST})
        self.assertEqual(self.plan(r, head).klass, T.GATE_FIRST)
        git(r.root, "checkout", "-q", r.base)
        os.unlink(os.path.join(r.root, "core/lander/x.py"))
        head = r.commit("rm lander file, add d", {"core/bin/d": "#!/bin/sh\n",
                                                  "core/tests/LANDING.toml": CORE_MANIFEST + guard + self.NEW})
        self.assertEqual(self.plan(r, head).klass, T.LANDER)

    def test_an_added_check_may_not_raise_its_cap_above_the_base_largest(self):
        """perms 10-12: `cap = 999999999` over ** planned clean. The base's largest cap is 600 (the default)."""
        r = self.repo()
        git(r.root, "checkout", "-qb", "big")
        big = r.commit("d, uncapped", {"core/bin/d": "#!/bin/sh\n", "core/tests/LANDING.toml": CORE_MANIFEST
                                       + self.NEW.replace('paths = ["bin/d"]', 'paths = ["**"]\ncap = 999999999')})
        self.assertEqual(self.plan(r, big).klass, T.LANDER)
        git(r.root, "checkout", "-q", r.base)
        ok = r.commit("d, at the ceiling", {"core/bin/d": "#!/bin/sh\n", "core/tests/LANDING.toml": CORE_MANIFEST
                                            + self.NEW.replace('paths = ["bin/d"]', 'paths = ["bin/d"]\ncap = 600')})
        self.assertNotEqual(self.plan(r, ok).klass, T.LANDER)

    def test_a_move_with_an_edit_and_its_check_dropped_is_lander_class(self):
        """perms 10-12: git mv the guarded tool, edit one line and drop its check. Its blob is at no head path,
        but git's -M sees the rename on the merge tree, so the tool survives and the drop is a fault."""
        body = "".join(f"echo line {i}\n" for i in range(20))
        guard = '\n[[check]]\nname = "guard"\nrun = "bin/guard selfcheck"\npaths = ["bin/guard"]\nclass = "host"\n'
        r = self.repo({"core/bin/guard": "#!/bin/sh\n" + body, "core/tests/LANDING.toml": CORE_MANIFEST + guard})
        git(r.root, "checkout", "-qb", "mv")
        git(r.root, "mv", "core/bin/guard", "core/bin/guard2")
        head = r.commit("mv guard, edit a line, drop its check", {
            "core/bin/guard2": "#!/bin/sh\n" + body.replace("line 3\n", "line three\n"),
            "core/tests/LANDING.toml": CORE_MANIFEST})
        self.assertEqual(self.plan(r, head).klass, T.LANDER)
        git(r.root, "checkout", "-q", r.base)
        os.unlink(os.path.join(r.root, "core/bin/guard"))
        gone = r.commit("rm guard and its check", {"core/tests/LANDING.toml": CORE_MANIFEST})
        self.assertNotEqual(self.plan(r, gone).klass, T.LANDER)

    def test_a_move_past_gits_rename_limit_still_survives(self):
        """Opus read 10-12: with 1001 files deleted and 1001 added beside the move, git's default diff.renameLimit
        skips inexact renames (a warning, rc 0), so the edited guard read as gone. -l0 keeps the rename."""
        body = "".join(f"echo line {i}\n" for i in range(20))
        guard = '\n[[check]]\nname = "guard"\nrun = "bin/guard selfcheck"\npaths = ["bin/guard"]\nclass = "host"\n'
        junk = {f"core/junk/a{i}": f"a {i}\n" for i in range(1001)}
        r = self.repo({"core/bin/guard": "#!/bin/sh\n" + body, "core/tests/LANDING.toml": CORE_MANIFEST + guard,
                       **junk})
        git(r.root, "checkout", "-qb", "mv")
        git(r.root, "rm", "-rq", "core/junk")
        git(r.root, "mv", "core/bin/guard", "core/bin/guard2")
        head = r.commit("mv guard past the rename limit, drop its check", {
            "core/bin/guard2": "#!/bin/sh\n" + body.replace("line 3\n", "line three\n"),
            "core/tests/LANDING.toml": CORE_MANIFEST, **{f"core/more/b{i}": f"b {i} x\n" for i in range(1001)}})
        self.assertEqual(self.plan(r, head).klass, T.LANDER)

    def test_a_reach_line_dropped_beside_a_clean_check_is_lander_class_and_one_added_is_not(self):
        # c calls b, so the generator still makes c -> b and dropping it is no generated change
        r = self.repo({"core/bin/c": '#!/bin/sh\n"$BIN/b"\necho c\n'})
        files = {"core/bin/d": "#!/bin/sh\n", "core/tests/LANDING.toml": CORE_MANIFEST + self.NEW}
        git(r.root, "checkout", "-qb", "add")
        add = r.commit("d, and a -> d", {**files, "core/tests/reach.tsv": REACH + "a\td\n"})
        self.assertNotEqual(self.plan(r, add).klass, T.LANDER)
        git(r.root, "checkout", "-q", r.base)
        cut = r.commit("d, and c -> b dropped", {**files, "core/tests/reach.tsv": "# a comment\nb\ta\n"})
        self.assertEqual(self.plan(r, cut).klass, T.LANDER)

    def test_the_policy_file_is_still_lander_class(self):
        r = self.repo()
        head = r.commit("policy", {"tests/LANDING-policy.toml": self.POLICY + "# a note\n",
                                   "core/tests/LANDING.toml": CORE_MANIFEST + self.NEW, "core/bin/d": "#!/bin/sh\n"})
        self.assertEqual(self.plan(r, head).klass, T.LANDER)

    def test_it_is_judged_on_the_merge_tree_not_the_head(self):
        """main adds check z after the PR branched: against main the PR's head lacks z, which reads as a removed
        check; on the merge tree it is there, so the PR's own added check is clean."""
        r = self.repo()
        git(r.root, "checkout", "-qb", "pr")
        head = r.commit("check d", {"core/bin/d": "#!/bin/sh\n", "core/tests/LANDING.toml": CORE_MANIFEST + self.NEW})
        git(r.root, "checkout", "-q", "-")
        z = '[[check]]\nname = "z"\nrun = "bin/a z"\npaths = ["bin/a"]\nclass = "hermetic"\n'
        main = r.commit("check z", {"core/tests/LANDING.toml": z + CORE_MANIFEST})   # at the top: the merge is clean
        self.assertTrue(M.clean_faults(M.load(r.root, main), M.load(r.root, head), M.Trees(r.root, main, head)))
        self.assertNotEqual(self.plan(r, head, main).klass, T.LANDER)


class Reach(unittest.TestCase):
    def test_the_generator_finds_the_four_spellings_and_no_self_or_cc_edges(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, {"bin/t": "#!/bin/sh\n", "bin/t-longer": "#!/bin/sh\n",
                      "bin/u": '"${BIN}/t" x\n', "bin/v": 'os.path.join(BIN, "t")\n', "bin/w": '$B/t\n',
                      "bin/x": 'BIN / "t"\n', "bin/y": '"$BIN/t-longer"\n', "bin/cc": '"$BIN/t"\n',
                      "bin/self": '"$BIN/self"\n'})
            edges = R.generate(d)
            self.assertEqual(sorted(a for a, b in edges if b == "t"), ["u", "v", "w", "x"])
            self.assertEqual([a for a, b in edges if b == "t-longer"], ["y"])   # t does not match t-longer
            self.assertNotIn(("self", "self"), edges)
            self.assertFalse(any(a == "cc" for a, _ in edges))

    def test_parse_skips_comments_and_render_round_trips(self):
        edges = [("a", "b"), ("c", "d")]
        self.assertEqual(R.parse(R.render(edges)), edges)
        self.assertEqual(R.parse("# x\n\nbad line\na\tb\n"), [("a", "b")])
        self.assertEqual(R.callers([("a", "b"), ("c", "b"), ("a", "d")], "b"), ["a", "c"])


class TestLivePolicy(unittest.TestCase):
    """The repo's own policy: brief, "a lander-class PR that doesn't touch a gate land whole with ONE strong read";
    the gate paths keep lander-self."""
    PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tests", "LANDING-policy.toml")

    def test_only_the_landers_gate_paths_go_to_lander_self(self):
        if not os.path.exists(self.PATH):
            self.skipTest("no overlay policy in this tree")
        with open(self.PATH) as f:
            pol, faults = M.parse_policy(f.read(), source="policy")
        self.assertEqual(faults, [])
        for gate in ("core/lander/review.py", "core/lander/plan.py", "core/lander/check.py", "core/lander/lane.py",
                     "core/lander/sandbox.py", "core/lander/gh.py", "core/lander/records.py", "core/lander/cli.py",
                     "core/lander/board.py", "core/lander/scope.py", "core/lander/tick.py",
                     "core/bin/lander-self", "tests/LANDING-policy.toml"):
            self.assertTrue(M.match(pol.lander, gate), gate)
        for plain in ("core/lander/repair.py", "core/tests/lander/test_plan.py"):
            self.assertFalse(M.match(pol.lander, plain), plain)
            self.assertTrue(M.match(pol.paid_review, plain), plain)

    # The text forms of a lander import, read anywhere in a file: a Python import statement at any depth, a
    # `python3 -c '...'` string in a shell tool or inside a Python one, importlib.import_module("lander.x").
    TEXT_IMPORTS = (re.compile(r"\bfrom\s+lander\s+import\s+\(?([\w\s,]+)"),
                    re.compile(r"\bfrom\s+lander\.(\w+)\s+import\b"), re.compile(r"\bimport\s+lander\.(\w+)"),
                    re.compile(r"\bimport_module\(\s*['\"]lander\.(\w+)"))

    @classmethod
    def _lander_imports(cls, src):
        """The core/lander module names the text `src` imports, at any depth: a function body's imports count, since
        the function runs in the importing process (Opus read of #1277: board and scope, loaded inside cards' and
        deploy's functions, were off the lander list). Python's own `from . import x` / `from .x import` are read by
        ast when `src` parses."""
        out = set()
        for i, rx in enumerate(cls.TEXT_IMPORTS):
            for m in rx.finditer(src):
                out |= {a.split()[0] for a in m.group(1).split(",") if a.split()} if i == 0 else {m.group(1)}
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return out
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.level == 1:
                out |= {n.module.split(".")[0]} if n.module else {a.name for a in n.names}
        return out

    def test_the_import_reader_counts_function_bodies_c_strings_and_import_module(self):
        """Each form the transitive scan below must see, and text that only names the package, which it must not."""
        src = ("import os\n"
               "def f():\n    from lander import board, scope as S\n"
               "def g():\n    import importlib\n    return importlib.import_module('lander.tick')\n"
               "CMD = \"python3 -c 'from lander.repair import x'\"\n"
               "import lander.events as E\n"
               "from . import jobs\n"
               "# the lander lands it; lander_self is a word\n")
        self.assertEqual(self._lander_imports(src), {"board", "scope", "tick", "repair", "events", "jobs"})
        self.assertEqual(self._lander_imports("#!/bin/sh\npython3 -c 'from lander import run' \"$x\"\n"), {"run"})
        self.assertEqual(self._lander_imports("the lander imports nothing here\nimport landers\n"), set())

    def test_what_tools_import_from_the_live_checkout_goes_to_lander_self(self):
        """perms' read of #1277: the overlay's Cloudflare door imports lander.git and lander.members from the live
        checkout and runs them with its token, and members loads jobs, events, types and the package. Every Python
        tool in bin-private/ and core/bin/, Python or shell, is read for the lander modules it imports
        (_lander_imports: function bodies, -c strings and import_module included); what those load in turn (followed
        within core/lander, function bodies included), the package's __init__ and cards (where perms' reads are
        read, and the walls) must all be lander-class, or a change to one would run there on one paid read."""
        if not os.path.exists(self.PATH):
            self.skipTest("no overlay policy in this tree")
        with open(self.PATH) as f:
            pol, _ = M.parse_policy(f.read(), source="policy")
        root, pkg = os.path.dirname(CORE), os.path.join(CORE, "lander")
        here = lambda m: os.path.isfile(os.path.join(pkg, m + ".py"))   # noqa: E731
        todo, entry = [], {}
        for d in ("bin-private", os.path.join("core", "bin")):
            full = os.path.join(root, d)
            for name in sorted(os.listdir(full)) if os.path.isdir(full) else []:
                p = os.path.join(full, name)
                if not os.path.isfile(p) or os.path.islink(p):
                    continue
                with open(p, errors="replace") as f:
                    mods = {m for m in self._lander_imports(f.read()) if here(m)}
                if mods:
                    entry[f"{d}/{name}"] = sorted(mods)
                    todo += mods
        self.assertTrue(entry, "no tool imports the lander package: the scan found nothing to check")
        seen = set()
        while todo:
            m = todo.pop()
            if m in seen:
                continue
            seen.add(m)
            with open(os.path.join(pkg, m + ".py")) as f:
                todo += [x for x in self._lander_imports(f.read()) if here(x)]
        for m in sorted(seen | {"__init__", "cards"}):
            path = f"core/lander/{m}.py"
            who = [t for t, ms in entry.items() if m in ms] or "a module those load"
            self.assertTrue(M.match(pol.lander, path), f"{path} ({who}) is not on the lander list")


class SecurityPaths(unittest.TestCase):
    """tests/LANDING-security.toml: the changed files on it go in plan.extra["security"] and the plan is paid."""

    SEC = 'paths = ["bin-private/door", "config/systemd-user/**"]\n'

    def test_a_change_on_the_bases_security_list_is_marked_and_paid(self):
        r = Repo(self, {"tests/LANDING-security.toml": self.SEC})
        m = M.load(r.root, r.base)
        self.assertEqual(m.policy.security_review, ["bin-private/door", "config/systemd-user/**"])
        for f in ("bin-private/door", "config/systemd-user/tunnel.service"):
            p = P.select(m, [f, "core/bin/a"])
            self.assertEqual((p.extra.get("security"), p.paid), ([f], True), f)
        p = P.select(m, ["core/bin/a", "bin-private/door2", "config/units.json"])
        self.assertNotIn("security", p.extra)
        self.assertFalse(p.paid)

    def test_no_security_file_marks_nothing(self):
        r = Repo(self)
        p = P.select(M.load(r.root, r.base), ["bin-private/door", "config/systemd-user/tunnel.service"])
        self.assertNotIn("security", p.extra)

    def test_the_security_file_is_lander_class_and_may_not_narrow(self):
        r = Repo(self, {"tests/LANDING-security.toml": self.SEC})
        head = r.commit("narrow", {"tests/LANDING-security.toml": 'paths = ["bin-private/door"]\n'})
        files = P.changed(r.root, r.base, head)
        p = P.plan(r.root, r.base, head, files)
        self.assertEqual(p.klass, T.LANDER)
        self.assertIn(M.BUILTIN, p.checks)
        bad = M.widen_faults(M.load(r.root, r.base), M.load(r.root, head, strict=False))
        self.assertTrue(any("security_review lost config/systemd-user/**" in b for b in bad), bad)
        wider = r.commit("widen", {"tests/LANDING-security.toml": self.SEC.replace(']', ', "bin-private/x"]')})
        self.assertEqual(M.widen_faults(M.load(r.root, head), M.load(r.root, wider, strict=False)), [])

    def test_a_list_naming_itself_marks_a_head_that_removes_an_entry(self):
        """Perms' HANDBACK at 2f9fde5e: the list protects itself, so a removal needs the same perms read; the plan
        reads the base's list, which still names the file the head changes."""
        own = 'paths = ["tests/LANDING-security.toml", "bin-private/door", "config/systemd-user/**"]\n'
        r = Repo(self, {"tests/LANDING-security.toml": own})
        head = r.commit("drop", {"tests/LANDING-security.toml": own.replace(', "config/systemd-user/**"', "")})
        p = P.plan(r.root, r.base, head, P.changed(r.root, r.base, head))
        self.assertEqual((p.extra.get("security"), p.paid), (["tests/LANDING-security.toml"], True))
        r2 = Repo(self, {"tests/LANDING-security.toml": self.SEC})   # a list not naming itself: not marked
        head2 = r2.commit("drop", {"tests/LANDING-security.toml": 'paths = ["bin-private/door"]\n'})
        self.assertNotIn("security", P.plan(r2.root, r2.base, head2, P.changed(r2.root, r2.base, head2)).extra)

    def test_a_security_file_with_another_key_is_a_fault(self):
        self.assertEqual(M.parse_security('paths = ["a"]\n', "core/"), (["core/a"], []))
        self.assertTrue(M.parse_security('paths = ["a"]\nskip = true\n')[1])
        self.assertTrue(M.parse_security('paths = "a"\n')[1])


if __name__ == "__main__":
    unittest.main()
