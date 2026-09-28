"""U2's selection cases: manifest and policy parsing, add-only (S3), prose (S10), one-hop reach, plan() and its class.

    python3 -m unittest discover -s core/tests/lander -p 'test_plan.py'

Each case builds its own fixture (a manifest text, or a git repo of its own), and asserts both what is selected and
what is left out.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

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
        self.root = self.d.name
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
            self.assertEqual(list(M.load(d, "HEAD", fallback=fb).checks), ["check"])
            self.assertEqual(M.load(d, "HEAD").checks, {})


class AddOnly(unittest.TestCase):
    def two(self, head_text, base_text=CORE_MANIFEST):
        base = M.Manifest()
        for c in M.parse_checks(base_text, "core/", "b")[0]:
            base.checks[c.name], base.cwd[c.name] = c, "core/"
        base.policy = M.parse_policy(POLICY, "", "p")[0]
        head = M.Manifest()
        for c in M.parse_checks(head_text, "core/", "h", head.unclassed)[0]:
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
        }
        for what, (text, words) in cases.items():
            base, head = self.two(text)
            faults = M.widen_faults(base, head)
            self.assertTrue(any(words in f for f in faults), (what, faults))
            self.assertNotIn("new", M.widen(base, head).checks, what)   # an added one is never selected to run

    def test_a_new_check_with_no_class_runs_in_the_sandbox_and_an_old_one_keeps_its_default(self):
        base_text = CORE_MANIFEST + '\n[[check]]\nname = "old"\nrun = "true"\n'   # no class: host, at base
        head_text = base_text + '\n[[check]]\nname = "new"\nrun = "true"\n'
        base, head = self.two(head_text, base_text)
        self.assertEqual(M.widen_faults(base, head), [])
        w = M.widen(base, head)
        self.assertEqual((w.checks["new"].klass, w.checks["old"].klass), (T.HERMETIC, T.HOST))
        r = Repo(self)   # the same through load(): the missing class line is seen in the git text
        head = r.commit("add", {"tests/LANDING.toml": OVERLAY_MANIFEST + '\n[[check]]\nname="n"\nrun="true"\n'})
        self.assertEqual(M.widen(M.load(r.root, r.base), M.load(r.root, head)).checks["n"].klass, T.HERMETIC)
        self.assertTrue(M.widen_check(r.root, r.base, head)[0])

    def test_a_grant_the_base_already_has_is_not_a_widening(self):
        base_text = CORE_MANIFEST.replace('class = "box"', 'class = "box"\nnet = true\nmounts = ["/opt/x"]')
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
        ok, text = M.widen_check(r.root, r.base, r.commit("drop", {"tests/LANDING.toml": ""}))
        self.assertFalse(ok)
        self.assertIn("identity", text)


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

    def sel(self, *files, protected=()):
        return P.select(self.m, list(files), protected)

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

    def test_the_class_order_protected_lander_gate_first(self):
        self.assertEqual(self.sel("core/lander/plan.py", "core/bin/guard").klass, T.LANDER)
        self.assertEqual(self.sel("core/lander/plan.py", protected=["core/lander/**"]).klass, T.PROTECTED)
        self.assertEqual(self.sel("tests/LANDING-policy.toml").klass, T.LANDER)   # the policy file itself
        self.assertEqual(self.sel("core/bin/a").klass, T.LEAF)

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

    def test_plan_on_a_head_that_removes_the_policy_is_lander_class(self):
        r = Repo(self)
        os.unlink(os.path.join(r.root, "tests/LANDING-policy.toml"))
        head = r.commit("rm")
        p = P.plan(r.root, r.base, head, P.changed(r.root, r.base, head))
        self.assertEqual(p.klass, T.LANDER)

    def test_plan_is_pure(self):
        r = Repo(self)
        before = git(r.root, "status", "--porcelain")
        P.plan(r.root, r.base, r.base, ["core/bin/a"])
        self.assertEqual(git(r.root, "status", "--porcelain"), before)


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


if __name__ == "__main__":
    unittest.main()
