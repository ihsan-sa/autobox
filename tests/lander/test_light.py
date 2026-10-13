"""The light lane (light.py, and its branches in lane.py): who qualifies, and what the lane does with a light job.

    python3 -m unittest discover -s core/tests/lander -p 'test_light.py' -v

Hermetic: the lane cases run on test_lane's fixture (a bare origin, clones and fakes under a tmp dir), with a host
fallback manifest of one static, one host and one e2e check, and a policy on main that puts b/** on paid_review.
"""
import os
import sys
import types
import unittest
from unittest import mock

CORE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
HERE = os.path.dirname(os.path.realpath(__file__))
for p in (CORE, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import test_lane as TL  # noqa: E402
from lander import jobs as J  # noqa: E402
from lander import lane as L  # noqa: E402
from lander import members as MB  # noqa: E402
from lander import review as RV  # noqa: E402
from lander import light as LT  # noqa: E402
from lander import manifest as MF  # noqa: E402
from lander import plan as P  # noqa: E402
from lander import types as T  # noqa: E402

setUpModule, tearDownModule = TL.setUpModule, TL.tearDownModule

POLICY = T.Policy(gate_first=["tests/**"], paid_review=["core/lander/**"], lander=["core/lander/lane.py"],
                  security_review=["config/cloudflare/**"])


class Qualify(unittest.TestCase):
    def test_a_change_on_no_list_qualifies(self):
        self.assertEqual(LT.path_hit(POLICY, ["docs/a.md", "bin/tool"], ["config/secret"]), "")

    def test_a_protected_path_does_not_and_is_named(self):
        self.assertEqual(LT.path_hit(POLICY, ["bin/tool", "core/lander/lane.py"]),
                         "it touches core/lander/lane.py, on the lander's lander list")
        self.assertEqual(LT.path_hit(POLICY, ["core/lander/tick.py"]),
                         "it touches core/lander/tick.py, on the lander's paid_review list")
        self.assertEqual(LT.path_hit(POLICY, ["config/cloudflare/w.js"]),
                         "it touches config/cloudflare/w.js, on the lander's security list")
        self.assertEqual(LT.path_hit(POLICY, ["tests/LANDING-policy.toml"]),
                         "it touches tests/LANDING-policy.toml, on the lander's lander list")
        self.assertEqual(LT.path_hit(POLICY, ["config/secret/k"], ["config/secret"]),
                         "it touches config/secret/k, a protected path")
        # a protected-paths config that would not read is a hit, never a pass
        self.assertEqual(LT.path_hit(POLICY, ["bin/tool"], None), "the box's protected paths would not read")

    def test_trim_keeps_static_and_hermetic_only(self):
        m = MF.Manifest(checks={n: T.Check(name=n, run="true", klass=k) for n, k in
                                (("lint", T.STATIC), ("unit", T.HERMETIC), ("suite", T.HOST),
                                 ("tip", T.BOX), ("e2e-x", T.HERMETIC))})
        p = LT.trim(m, T.Plan(checks=["e2e-x", "gone", "lint", "suite", "unit"]))
        self.assertEqual(p.checks, ["lint", "unit"])
        self.assertEqual(p.extra["light_off"], ["e2e-x", "gone", "suite"])

    def test_every_manifest_and_reach_file_is_never_light_whatever_the_policy(self):
        for f in ("tests/LANDING.toml", "core/tests/LANDING.toml", "tests/reach.tsv", "core/tests/reach.tsv",
                  "tests/LANDING-policy.toml", "core/tests/LANDING-security.toml"):
            self.assertEqual(LT.path_hit(T.Policy(), [f]), f"it touches {f}, on the lander's lander list")
        self.assertEqual(LT.path_hit(T.Policy(), ["tests/other.toml"]), "")   # the kept case beside them

    def test_a_manifest_that_will_not_load_is_not_light(self):
        with mock.patch.object(MF, "load", side_effect=MF.ManifestError("bad")):
            self.assertIn("would not load (ManifestError)", LT.why_not("/r", "a" * 40, ["a/x"]))

    def test_no_policy_file_at_the_base_is_not_light(self):
        with mock.patch.object(MF, "load", return_value=MF.Manifest(sources=["tests/LANDING.toml"])):
            self.assertEqual(LT.why_not("/r", "a" * 40, ["a/x"]),
                             f"the base aaaaaaaaaaaa has no {MF.POLICY}")
        with mock.patch.object(MF, "load", return_value=MF.Manifest(sources=[MF.POLICY])):
            self.assertEqual(LT.why_not("/r", "a" * 40, ["a/x"]), "")   # with one it qualifies

    def test_member_perms_sandbox_and_wall_tools_on_gate_first_are_never_light(self):
        # the globs tests/LANDING-policy.toml puts on gate_first for them, on a fixture policy
        pol = T.Policy(gate_first=["core/bin/cc-member-v2", "core/bin/cc-member-*", "core/bin/cc-approve",
                                   "core/bin/cc-perms-*", "core/bin/cc-hostdoor", "core/bin/cc-fence",
                                   "core/bin/cc-egress", "core/bin/gh", "core/bin/git-remote-cc-github-deny",
                                   "core/bin/cc-subagent-bound", "core/bin/cc-native", "core/bin/cc-tier",
                                   "core/bin/cc-room"])
        for f in ("core/bin/cc-member-v2", "core/bin/cc-member-broker", "core/bin/cc-member-new",
                  "core/bin/cc-approve", "core/bin/cc-perms-eval", "core/bin/cc-hostdoor", "core/bin/cc-fence",
                  "core/bin/cc-egress", "core/bin/gh", "core/bin/git-remote-cc-github-deny",
                  "core/bin/cc-subagent-bound", "core/bin/cc-native", "core/bin/cc-tier", "core/bin/cc-room"):
            self.assertEqual(LT.path_hit(pol, [f]), f"it touches {f}, on the lander's gate_first list")
        self.assertEqual(LT.path_hit(pol, ["core/bin/cc-other"]), "")   # the kept case beside them

    def test_a_widened_plan_is_not_light(self):
        self.assertEqual(LT.widened(T.Plan(checks=["lint"], unowned=["core/bin/new-tool"], klass=T.WIDE)),
                         "no check owns core/bin/new-tool, so its plan widens to the default checks")
        self.assertEqual(LT.widened(T.Plan(checks=["lint"], klass=T.WIDE)), "its plan widens to the default checks")
        # an add-only file that loads by nothing is quiet: no widening, so it stays light
        self.assertEqual(LT.widened(T.Plan(checks=["lint"], unowned=["d/new.json"], klass=T.LEAF,
                                           extra={"add_only": ["d/new.json"]})), "")
        self.assertEqual(LT.widened(T.Plan(checks=["lint"], klass=T.LEAF)), "")

    def test_config_names_is_never_light_whatever_the_policy(self):
        self.assertEqual(LT.path_hit(T.Policy(), ["config/names.json"]),
                         "it touches config/names.json, on the lander's lander list")
        self.assertEqual(LT.path_hit(T.Policy(), ["config/other.json"]), "")   # the kept case beside it

    def test_a_default_path_is_never_light_and_keeps_the_default_checks(self):
        pol, faults = MF.parse_policy('default_checks = ["check-sh", "check-extra"]\n[paths]\ndefault = ["x/**"]\n',
                                      "", "p")
        self.assertEqual(faults, [])
        checks, faults = MF.parse_checks('[[check]]\nname = "check-sh"\nrun = "true"\npaths = ["s/**"]\nclass = "static"\n\n'
                                         '[[check]]\nname = "check-extra"\nrun = "true"\npaths = ["e/**"]\n'
                                         'class = "static"\n', "", "m")
        self.assertEqual(faults, [])
        m = MF.Manifest(checks={c.name: c for c in checks}, cwd={c.name: "" for c in checks}, policy=pol)
        files = ["x/a", "s/a.sh"]
        self.assertEqual(LT.path_hit(m.policy, files), "it touches x/a, on the lander's default list")
        self.assertEqual(LT.path_hit(m.policy, ["s/a.sh"]), "")   # the statically checked file alone is light
        checks = P.select(m, files).checks
        self.assertIn("check-sh", checks)
        self.assertIn("check-extra", checks)


class Reviewer(TL.Reviewer):
    """The stub reviewer, with the LAND recorded at the head (or none)."""
    def __init__(self, land=None):
        super().__init__()
        self.land = land

    def land_recorded(self, job):
        return self.land


class LightLane(TL.Fixture):
    FB = ('[[check]]\nname = "lint"\nrun = "true"\npaths = ["**"]\nclass = "static"\n\n'
          '[[check]]\nname = "suite"\nrun = "true"\npaths = ["**"]\nclass = "host"\n\n'
          '[[check]]\nname = "e2e-x"\nrun = "true"\npaths = ["**"]\nclass = "hermetic"\n')

    def setUp(self):
        super().setUp()
        fb = os.path.join(self.tmp, "release", "tests", "landing-repos")
        self.write(fb, {"demo.toml": self.FB})
        self.fb = fb
        p = mock.patch.object(MF, "FALLBACK_DIR", fb)
        p.start()
        self.addCleanup(p.stop)
        self.push("main", {"tests/LANDING-policy.toml": '[paths]\npaid_review = ["b/**"]\n'})

    def lane(self, pr, files, land=True, runner=None):
        head = self.pr(pr, files)
        J.submit("demo", pr)
        rv = runner or TL.Runner()
        self.land(planner=P, runner=rv, reviewer=Reviewer(TL.V(T.LAND, head=head[:12]) if land else None))
        return rv

    def test_a_qualifying_pr_with_a_land_runs_only_its_static_checks_and_merges(self):
        rv = self.lane(1, {"a/x": "n\n"})
        self.assertEqual([c[0] for c in rv.calls], ["lint"])
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)
        self.assertIs(self.job().extra["light"], True)
        self.assertIn("stage demo#1 light", self.log())

    def test_no_land_recorded_goes_the_normal_way(self):
        rv = self.lane(1, {"a/x": "n\n"}, land=False)
        self.assertEqual(sorted(c[0] for c in rv.calls), ["e2e-x", "lint", "suite"])
        self.assertEqual(self.job().extra["light"], "no LAND is recorded at its head")

    def test_a_protected_path_goes_the_normal_way_named(self):
        rv = self.lane(1, {"b/y": "n\n"})
        self.assertIn("suite", [c[0] for c in rv.calls])
        self.assertEqual(self.job().extra["light"], "it touches b/y, on the lander's paid_review list")

    def test_a_static_red_hands_a_light_pr_back(self):
        self.lane(1, {"a/x": "n\n"}, runner=TL.Runner(status={"lint": T.FAILED}))
        self.assertIsNone(J.load("demo", 1))   # a handback removes the job
        self.assertTrue(os.path.exists(J.handed_path("demo", 1)))
        self.assertIn("check lint failed", J.read_json(J.handed_path("demo", 1))["why"])
        self.assertIn("stage demo#1 gate gate=lint ok=no", self.log())

    def test_a_plan_with_no_static_or_hermetic_check_is_not_light(self):
        self.write(self.fb, {"demo.toml": self.FB.split("[[check]]\nname = \"suite\"")[0].replace(
            'class = "static"', 'class = "host"')})   # lint is a host check now, and the only one
        rv = self.lane(1, {"a/x": "n\n"})
        self.assertEqual([c[0] for c in rv.calls], ["lint"])   # the whole plan ran, untrimmed
        self.assertEqual(self.job().extra["light"], "its plan keeps no static or hermetic check")

    def test_a_file_no_check_owns_widens_and_is_not_light(self):
        # Opus read of #1316: s/a.sh plus core/bin/new-tool came out trimmed to [lint], so the tool landed unchecked
        self.write(self.fb, {"demo.toml": self.FB.replace('paths = ["**"]', 'paths = ["s/**"]', 1)
                             .replace('paths = ["**"]', 'paths = ["z/**"]')})
        # s/a.sh is on main already, so the PR is not add-only and the new tool widens (an add-only one that loads by
        # nothing is quiet in plan.py, on either lane)
        self.push("main", {"tests/LANDING-policy.toml": 'default_checks = ["suite"]\n[paths]\npaid_review = ["b/**"]\n',
                           "s/a.sh": "o\n"})
        rv = self.lane(1, {"s/a.sh": "n\n", "core/bin/new-tool": "n\n"})
        self.assertIn("suite", [c[0] for c in rv.calls])   # the default check ran, untrimmed
        self.assertEqual(self.job().extra["light"],
                         "no check owns core/bin/new-tool, so its plan widens to the default checks")

    def test_a_check_blocked_by_main_hands_a_light_pr_back(self):
        from lander import run as RUN

        class MainRed(TL.Runner):   # run.judge's word when the base tree is red on the check too
            def run_plan(self, root, m, plan, files, head_tree, base_tree="", *, only=None, **kw):
                return {n: RUN.Outcome(n, RUN.BLOCKED, f"{RUN.BLOCKED}:{n}") for n in plan.checks
                        if not only or n in only}
        self.lane(1, {"a/x": "n\n"}, runner=MainRed())
        self.assertIsNone(J.load("demo", 1))   # never kept as the check's result and merged
        self.assertIn("the light lane hands it back", J.read_json(J.handed_path("demo", 1))["why"])
        # the same red on a PR that is not light holds it, as before
        self.lane(2, {"b/y": "n\n"}, runner=MainRed())
        self.assertEqual(self.job(2).state, T.HELD)
        self.assertIn("main_red", self.job(2).extra)

    def test_main_moving_into_a_conflict_hands_a_light_pr_back_unparked(self):
        def hook(name, n):   # main takes a clashing change to a/x while the light PR's check runs
            self.push("main", {"a/x": "main's\n"})
        self.lane(1, {"a/x": "n\n"}, runner=TL.Runner(hook=hook))
        self.assertIsNone(J.load("demo", 1))
        self.assertIn("conflicts with main", J.read_json(J.handed_path("demo", 1))["why"])

    def test_main_moving_cleanly_at_the_merge_moves_the_base_and_merges(self):
        def hook(name, n):
            self.push("main", {"c/z": "main's\n"})
        rv = self.lane(1, {"a/x": "n\n"}, runner=TL.Runner(hook=hook))
        self.assertEqual([c[0] for c in rv.calls], ["lint"])   # no Δ re-plan
        self.assertEqual(self.job().state, T.DEPLOY_PENDING)
        self.assertEqual(self.job().base_sha, self.origin_rev("main~1"))   # the base it merged onto: main then

    def test_main_listing_its_file_at_the_merge_ends_the_light_way(self):
        def hook(name, n):   # main's policy puts a/** on paid_review while the light PR's check runs
            self.push("main", {"tests/LANDING-policy.toml": '[paths]\npaid_review = ["b/**", "a/**"]\n'})
        rv = self.lane(1, {"a/x": "n\n"}, runner=TL.Runner(hook=hook))
        self.assertEqual(self.job().extra["light"], "it touches a/x, on the lander's paid_review list")
        self.assertIn("suite", [c[0] for c in rv.calls])   # re-planned the normal way

    def test_a_members_pr_is_never_light(self):
        lane = L.Lane("demo", self.units(reviewer=Reviewer(TL.V(T.LAND))))
        lane.member = "alice"
        job = types.SimpleNamespace(repo="demo", pr=1, head="h" * 40, base_sha="b" * 40, files=["a/x"], extra={})
        self.assertFalse(lane.light(job))
        self.assertEqual(job.extra["light"], "it is a member's PR")
        with mock.patch.object(MB, "member_of", return_value=("alice", "proj")):
            self.assertEqual(L.light_word("alice--proj", self.work, 1), "PR #1 goes the normal way: it is a member's PR")

    def test_a_land_recorded_at_an_older_head_is_not_one_at_this_head(self):
        old = self.pr(1, {"a/x": "old\n"})
        new = self.pr(1, {"a/x": "new\n"})
        base = self.origin_rev("main")
        job = types.SimpleNamespace(repo="demo", pr=1, head=new, base_sha=base, digest="d1", member="",
                                    extra={"root": self.work})
        at = lambda head: [{"body": RV.marker(T.Verdict(verdict=T.LAND, digest="d1"), base, head, "seat"),
                            "viewerDidAuthor": True}]
        self.assertIsNone(RV.land_recorded(job, at(old)))   # the real reader: a LAND at a stale head does not count
        self.assertEqual(RV.land_recorded(job, at(new)).verdict, T.LAND)   # the same LAND at this head does

    def test_queue_light_names_the_path_that_stops_it(self):
        self.pr(1, {"b/y": "n\n"})
        rc, out, err = self.queue("demo", "1", "--no-start", "--light")
        self.assertEqual(rc, 0, err)
        self.assertIn("PR #1 goes the normal way: it touches b/y, on the lander's paid_review list", out)
        self.pr(2, {"a/x": "n\n"})
        rc, out, err = self.queue("demo", "2", "--no-start", "--light")
        self.assertIn("PR #2 goes the light way once a LAND is recorded at its head", out)


if __name__ == "__main__":
    unittest.main()
