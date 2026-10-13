"""The light lane: a small isolated PR lands on a review already recorded and its static and hermetic checks, ahead of
the queue (owner, 2026-10-13: "small isolated changes should land after a manual check or review", landings in
parallel instead of everything going through the full protocol).

WHO: a PR in the repo's own lane (never a member's) none of whose files is on a list the lander already keeps for a
guarded landing — no second list: the box's CC_PROTECTED_PATHS, and at the BASE the policy's protected, lander,
gate_first and paid_review lists, the security list (LANDING-security.toml), the default paths (an unowned path widens to default_checks), and every manifest, policy, security and
reach file and config/names.json (NEVER, hard-coded so a policy cannot drop them). Between them that is the guard, the sandbox, the member
walls and perms tools, dispatch, the lander and lander-self, the manifests, and secrets. A base whose manifest will
not load, or that has no policy file, qualifies nothing (fail closed). why_not() names the first file on a
list and the list, which `lander queue --light` prints and the lane keeps in job.extra["light"].
WHAT IT NEEDS: a LAND recorded at the PR's head and digest (review.land_recorded: any seat's `lander record`, or an
earlier read), and its plan's static and hermetic checks (trim(); no host, box, timing or e2e- check) green on the
merge tree. A plan that widened to default_checks (widened()), or keeps no check that way, is not light (lane.planned).
WHAT THE LANE DOES WITH IT (lane.py): a check the runner calls blocked by main (since the ratchet,
reds it refused to call main's) hands it back, never a hold and never a kept result; it goes before every other due job but one put first or one whose plan holds a check main is red on; when main
moves under it the base moves with it and nothing is re-checked; a conflict with the base hands it back, never a
repair round. A red check hands it back as
any red does. Host checks run on main's tip after the merge, as every merged range's do.
"""
from __future__ import annotations

from lander import manifest as M
from lander import types as T

KEEP = (T.STATIC, T.HERMETIC)
# security read of #1316: "every manifest and reach file" is never light, whatever the policy at the base says
# perms 10-13: config/names.json holds the box's own names, which the identity gate keeps out of core/
NEVER = [p + f for p in M.PREFIXES for f in (M.MANIFEST, M.POLICY, M.SECURITY, M.REACH)] + ["config/names.json"]


def lists(policy: T.Policy, protected=()) -> list:
    """[(name, globs)] in the order why_not names them: the lists the lander already guards a landing by."""
    return [("protected", list(protected) + list(policy.protected)),
            ("lander", NEVER + list(policy.lander)),
            ("gate_first", list(policy.gate_first)),
            ("paid_review", list(policy.paid_review)),
            ("security", list(policy.security_review)),
            ("default", list(policy.extra.get("default_paths", [])))]   # perms 10-13: an unowned path widens to default_checks, so never light


def path_hit(policy: T.Policy, files, protected=()) -> str:
    """Why `files` do not qualify by path, naming the first one on a list and the list; '' when none is.
    protected: CC_PROTECTED_PATHS (prefixes, lane.under's rule) — None, a config that would not read, is a hit."""
    if protected is None:
        return "the box's protected paths would not read"
    for f in files:
        if any(f == r.rstrip("/") or f.startswith(r.rstrip("/") + "/") for r in protected):
            return f"it touches {f}, a protected path"
        for name, globs in lists(policy):
            if globs and M.match(globs, f):
                return f"it touches {f}, on the lander's {name} list"
    return ""


def why_not(root: str, base: str, files, protected=(), fallback: str = "") -> str:
    """path_hit() on the policy at `base`, or why it cannot be asked: no file, a manifest that will not load, or no
    policy file at the base (each qualifies nothing). The LAND the lane also needs is review.land_recorded's, asked by lane.light()."""
    if not files:
        return "it changes no file"
    try:
        m = M.load(root, base, fallback=fallback)
    except Exception as e:  # noqa: BLE001 — any fault is the normal lane, never a light landing on a guess
        return f"the manifest at {base[:12]} would not load ({type(e).__name__})"
    if not any(s.endswith(M.POLICY) for s in m.sources):   # no policy, no protected list: fail closed
        return f"the base {base[:12]} has no {M.POLICY}"
    return path_hit(m.policy, files, protected)


def widened(plan: T.Plan) -> str:
    """Why `plan` is not light because it widened to default_checks, naming the file; '' when it did not. Opus read of
    #1316 at e84e183e: "a plan of klass T.WIDE, or any widening entry in unowned, is not light" — trim() would drop the
    host checks the widening added, and an unowned new tool would land with no check on it. plan.py's widening entries
    are the unowned files not in extra["add_only"] (the quiet ones)."""
    quiet = set(plan.extra.get("add_only", []))
    wide = [f for f in plan.unowned if f not in quiet]
    if wide:
        return f"no check owns {wide[0]}, so its plan widens to the default checks"
    return "its plan widens to the default checks" if plan.klass == T.WIDE else ""


def trim(m: M.Manifest, plan: T.Plan) -> T.Plan:
    """`plan` with only its static and hermetic checks; the rest go in extra["light_off"] (an e2e- check whatever
    its class, and one the manifest lacks). A plan that comes out with no check means the PR is not light, which the
    caller decides (lane.planned)."""
    keep = [n for n in plan.checks
            if n in m.checks and m.checks[n].klass in KEEP and not n.startswith("e2e-")]
    off = [n for n in plan.checks if n not in keep]
    extra = dict(plan.extra, **({"light_off": off} if off else {}))
    return T.Plan(checks=keep, owned=plan.owned, klass=plan.klass, paid=plan.paid, unowned=plan.unowned,
                  extra=extra)

