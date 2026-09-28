"""The lander's shared records and the calls between its units — the one file U1-U4 code against.

Every record is a dataclass that goes to and from plain JSON: `to_dict()` gives only str/int/float/bool/None,
lists and dicts, and `Cls.from_dict(d)` builds it back and validates it. A record is validated when it is built
and again when it is written, so a bad state never reaches a job file.

KEYS THIS FILE DOES NOT KNOW ARE KEPT, not dropped. from_dict() puts them in `extra` and to_dict() writes them
back at the top level, so a unit that adds a field ahead of this file, or an older release reading a newer job,
rewrites the file without losing it. `Check` is the exception: a manifest key nobody reads is a typo (`path=`
owning nothing), so Check.validate() refuses it.

THE NAME. This module is `lander.types` and shadows the stdlib `types` for anything run with core/lander/ on
sys.path. bin/lander runs cli.py with `python3 -P`, and cli.py drops its own directory from sys.path; import it
as `from lander import types as T`, never as a bare `import types`.

ENUMS are string constants plus a tuple of the allowed values. A value outside the tuple is a ValueError.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional, Protocol

# --- enums ---------------------------------------------------------------------------------------------------------

QUEUED, PLANNED, CHECKING, MERGEABLE = "queued", "planned", "checking", "mergeable"
MERGED, DEPLOY_PENDING, DEPLOYED, DONE = "merged", "deploy-pending", "deployed", "done"
HANDBACK, HELD, QUERY = "handback", "held", "query"
JOB_STATES = (QUEUED, PLANNED, CHECKING, MERGEABLE, MERGED, DEPLOY_PENDING, DEPLOYED, DONE, HANDBACK, HELD, QUERY)

# Plan.klass: what kind of change this is, which decides the lane's route (gate-first runs box checks pre-merge,
# serially; lander goes to lander-self and is refused here; protected stops for a person).
DOCS, LEAF, WIDE, GATE_FIRST, LANDER, PROTECTED = "docs", "leaf", "wide", "gate-first", "lander", "protected"
PLAN_CLASSES = (DOCS, LEAF, WIDE, GATE_FIRST, LANDER, PROTECTED)

# Result.status. `unrunnable` is killed, OOM or no result: never read as red.
PASSED, FAILED, UNRUNNABLE = "passed", "failed", "unrunnable"
RESULT_STATUSES = (PASSED, FAILED, UNRUNNABLE)

# Verdict.verdict. INCOMPLETE is a usage or budget wall: the job goes `held`, no read is spent, the next tick retries.
LAND, HANDBACK_VERDICT, INCOMPLETE = "LAND", "HANDBACK", "INCOMPLETE"
VERDICTS = (LAND, HANDBACK_VERDICT, INCOMPLETE)

# Check.klass, the manifest's `class`. static: reads files only. hermetic: in bwrap. box: needs the live box, runs
# on the tip after merges (pre-merge only for gate-first). timing: load-sensitive. host: on the host with a scrubbed
# env, serial per repo, pre-merge — the day-one class for anything not yet proven in bwrap.
STATIC, HERMETIC, BOX, TIMING, HOST = "static", "hermetic", "box", "timing", "host"
CHECK_CLASSES = (STATIC, HERMETIC, BOX, TIMING, HOST)


def check_enum(what: str, value: Any, allowed: tuple) -> None:
    if value not in allowed:
        raise ValueError(f"{what}: {value!r} is not one of {', '.join(allowed)}")


def _check_type(owner: str, name: str, value: Any, kinds: tuple, optional: bool = False) -> None:
    if value is None and optional:
        return
    # bool is an int in Python; a pr of True is still wrong
    if not isinstance(value, kinds) or (isinstance(value, bool) and bool not in kinds):
        raise ValueError(f"{owner}.{name}: {value!r} is a {type(value).__name__}, "
                         f"not {' or '.join(k.__name__ for k in kinds)}")


def _check_strs(owner: str, name: str, value: Any) -> None:
    _check_type(owner, name, value, (list,))
    for v in value:
        _check_type(owner, name + "[]", v, (str,))


# --- the record base -----------------------------------------------------------------------------------------------

class Record:
    """to_dict/from_dict/validate for the dataclasses below. NESTED names a field holding another Record (or a
    list of them); KEYS renames a field on the wire (Check.klass is `class` in the manifest)."""
    NESTED: ClassVar[dict] = {}
    KEYS: ClassVar[dict] = {}

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        raise NotImplementedError

    def to_dict(self) -> dict:
        self.validate()
        out: dict = {}
        for f in dataclasses.fields(self):  # type: ignore[arg-type]
            if f.name == "extra":
                continue
            v = getattr(self, f.name)
            if isinstance(v, Record):
                v = v.to_dict()
            elif isinstance(v, list):
                v = [x.to_dict() if isinstance(x, Record) else x for x in v]
            out[self.KEYS.get(f.name, f.name)] = v
        for k, v in getattr(self, "extra", {}).items():
            out.setdefault(k, v)
        return out

    @classmethod
    def from_dict(cls, d: dict):
        if not isinstance(d, dict):
            raise ValueError(f"{cls.__name__}: expected an object, got {type(d).__name__}")
        wire = {cls.KEYS.get(f.name, f.name): f.name for f in dataclasses.fields(cls) if f.name != "extra"}  # type: ignore[arg-type]
        kw: dict = {}
        extra: dict = {}
        for k, v in d.items():
            if k not in wire:
                extra[k] = v
                continue
            name = wire[k]
            sub = cls.NESTED.get(name)
            if sub is not None and isinstance(v, dict):
                v = sub.from_dict(v)
            elif sub is not None and isinstance(v, list):
                v = [sub.from_dict(x) if isinstance(x, dict) else x for x in v]
            kw[name] = v
        if "extra" in {f.name for f in dataclasses.fields(cls)}:  # type: ignore[arg-type]
            kw["extra"] = extra
        try:
            return cls(**kw)
        except TypeError as e:   # a required key missing
            raise ValueError(f"{cls.__name__}: {e}") from None


# --- the records ---------------------------------------------------------------------------------------------------

@dataclass
class Plan(Record):
    """plan()'s answer. checks: the check names to run. owned: changed files some check owns. unowned: changed
    executable files nothing owns (they widen to the policy's default set, and the card names them). paid: the
    change touches a paid_review path, so the lander buys a read when no recorded one exists."""
    checks: list = field(default_factory=list)
    owned: list = field(default_factory=list)
    klass: str = LEAF
    paid: bool = False
    unowned: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def validate(self) -> None:
        check_enum("Plan.klass", self.klass, PLAN_CLASSES)
        for n in ("checks", "owned", "unowned"):
            _check_strs("Plan", n, getattr(self, n))
        _check_type("Plan", "paid", self.paid, (bool,))


@dataclass
class Result(Record):
    """One run of one check on one tree, stored at ~/.cc/state/land/results/<check>/<tree>.json. cases: one
    {"name", "status"} per case the check reported. release/nonce stamp a base-tree run the lane made, the only
    kind another job may reuse."""
    check: str
    tree: str
    status: str
    cases: list = field(default_factory=list)
    secs: float = 0.0
    cpu_secs: float = 0.0
    load: float = 0.0
    runner: str = ""
    release: str = ""
    nonce: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """The value Job.results holds for this check."""
        return f"{self.check}/{self.tree}"

    def validate(self) -> None:
        check_enum("Result.status", self.status, RESULT_STATUSES)
        for n in ("check", "tree", "runner", "release", "nonce"):
            _check_type("Result", n, getattr(self, n), (str,))
        for n in ("secs", "cpu_secs", "load"):
            _check_type("Result", n, getattr(self, n), (int, float))
        _check_type("Result", "cases", self.cases, (list,))


@dataclass
class Verdict(Record):
    """A review's answer for one change digest. blocking: concrete findings only (an input and the wrong outcome,
    or the exact leak); advisory: everything else, which becomes one follow-up row. A delta read also fills
    resolved/unresolved against the prior verdict's blocking list."""
    verdict: str
    digest: str
    blocking: list = field(default_factory=list)
    advisory: list = field(default_factory=list)
    model: str = ""
    tokens: int = 0
    resolved: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def validate(self) -> None:
        check_enum("Verdict.verdict", self.verdict, VERDICTS)
        _check_type("Verdict", "digest", self.digest, (str,))
        _check_type("Verdict", "model", self.model, (str,))
        _check_type("Verdict", "tokens", self.tokens, (int,))
        for n in ("blocking", "advisory", "resolved", "unresolved"):
            _check_strs("Verdict", n, getattr(self, n))


@dataclass
class Job(Record):
    """One landing, one JSON file per (repo, pr), written by the lane alone (atomic rename). Until a later PR
    repoints every reader the file stays at ~/.cc/state/land/<repo>-<pr>.json and keeps `stage`, the key today's
    readers show; `state` is the new machine's. repo is `<h>--<t>` for a member landing, with `member` = <h>.
    results maps check name -> Result.key. history: one {"at", "state", ...} per transition, oldest first."""
    repo: str
    pr: int
    head: str = ""
    base_sha: str = ""
    digest: str = ""
    files: list = field(default_factory=list)
    state: str = QUEUED
    stage: str = QUEUED
    plan: Optional[Plan] = None
    results: dict = field(default_factory=dict)
    review_key: str = ""
    reads_used: int = 0
    history: list = field(default_factory=list)
    member: Optional[str] = None
    extra: dict = field(default_factory=dict)
    NESTED: ClassVar[dict] = {"plan": Plan}

    @property
    def key(self) -> str:
        """The job file's stem: <repo>-<pr>."""
        return f"{self.repo}-{self.pr}"

    def validate(self) -> None:
        check_enum("Job.state", self.state, JOB_STATES)
        _check_type("Job", "pr", self.pr, (int,))
        for n in ("repo", "head", "base_sha", "digest", "stage", "review_key"):
            _check_type("Job", n, getattr(self, n), (str,))
        _check_strs("Job", "files", self.files)
        _check_type("Job", "plan", self.plan, (Plan,), optional=True)
        _check_type("Job", "results", self.results, (dict,))
        _check_type("Job", "reads_used", self.reads_used, (int,))
        _check_type("Job", "history", self.history, (list,))
        _check_type("Job", "member", self.member, (str,), optional=True)


@dataclass
class Check(Record):
    """One manifest [[check]] (LANDING.toml). run: the command, from the repo root. paths: the globs it owns.
    cap: seconds before it is killed (unrunnable, not red). where: runners it may use ("box", "laptop",
    "member"; U2 owns the list). mounts/net/fixtures: what its bwrap profile adds to the default."""
    name: str
    run: str
    paths: list = field(default_factory=list)
    klass: str = HOST
    cap: int = 600
    where: list = field(default_factory=lambda: ["box"])
    mounts: list = field(default_factory=list)
    net: bool = False
    fixtures: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    KEYS: ClassVar[dict] = {"klass": "class"}

    def validate(self) -> None:
        check_enum(f"Check {self.name!r} class", self.klass, CHECK_CLASSES)
        if self.extra:
            raise ValueError(f"Check {self.name!r}: unknown key(s) {', '.join(sorted(self.extra))}")
        _check_type("Check", "name", self.name, (str,))
        _check_type("Check", "run", self.run, (str,))
        _check_type("Check", "cap", self.cap, (int,))
        _check_type("Check", "net", self.net, (bool,))
        for n in ("paths", "where", "mounts", "fixtures"):
            _check_strs("Check", n, getattr(self, n))
        if not self.name or not self.run:
            raise ValueError("Check: name and run must be non-empty")


@dataclass
class Policy(Record):
    """LANDING-policy.toml [paths], read from BASE. Every field but `default` is a list of path globs: gate_first
    (box checks pre-merge, serially), paid_review (a recorded read or one the lander buys), lander (lander-self
    only), protected (a person decides). default: the check NAMES an unowned executable path widens to."""
    gate_first: list = field(default_factory=list)
    paid_review: list = field(default_factory=list)
    lander: list = field(default_factory=list)
    protected: list = field(default_factory=list)
    default: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def validate(self) -> None:
        for n in ("gate_first", "paid_review", "lander", "protected", "default"):
            _check_strs("Policy", n, getattr(self, n))


RECORDS = (Job, Plan, Result, Verdict, Check, Policy)


# --- the calls between units ---------------------------------------------------------------------------------------
# Each is implemented by a module-level function of the same name in the module named, so the module itself
# satisfies the Protocol: `from lander import plan as P; P.plan(...)`.

class Planner(Protocol):
    def plan(self, repo_root: str, base_sha: str, head_sha: str, files: list) -> Plan:
        """U2, lander/plan.py. Pure: reads the manifest and policy from base_sha (the head may only widen) and
        answers which checks the change reaches. No side effects; `lander plan <repo> <pr>` prints it."""

    def checks(self, repo_root: str, sha: str) -> list:
        """U2, lander/plan.py. The manifest's [[check]] entries read at `sha`, as Check records, so the lane can
        hand run() the Check a plan names."""


class Runner(Protocol):
    def run(self, check: Check, tree_sha: str, where: str) -> Result:
        """U2, lander/run.py. Runs one check on one tree on runner `where` under admission, and stores the Result
        at results/<check>/<tree>.json. Killed, OOM or no result -> UNRUNNABLE, never FAILED."""


class Reviewer(Protocol):
    def review(self, job: Job) -> Verdict:
        """U3, lander/review.py. One read per change digest: returns a recorded verdict at job.digest if any, else
        buys one (paid paths only). A usage or budget wall -> INCOMPLETE, and no read is counted."""

    def delta_review(self, job: Job, prior: Verdict) -> Verdict:
        """U3, lander/review.py. The re-read after a handback: the interdiff against prior.blocking, filling
        resolved/unresolved; new blockers only on added lines."""


class Events(Protocol):
    def log(self, kind: str, repo: str, pr: int, **kv: Any) -> None:
        """U1, lander/events.py. Appends `<stamp>\\t<kind> <repo>#<pr> k=v…` to queue.log, keeping today's line
        shapes (queued/stage/verdict/merged/done/stages) for the readers of that file."""


class Cards(Protocol):
    def landed(self, job: Job) -> None:
        """U3, lander/cards.py. The one card saying the PR merged (and what the tip and deploy will do)."""

    def stopped(self, job: Job, why: str, route: str) -> None:
        """U3, lander/cards.py. The card for a job that left the lane: why in plain words; route is who picks it
        up (the row's seat for a handback, the planning seat for a query)."""


class Board(Protocol):
    def close(self, job: Job) -> None:
        """U3, lander/board.py. Marks the job's board row done once it has merged."""


class Deploy(Protocol):
    def request(self, repo: str, sha: str, targets: list) -> None:
        """U3, lander/deploy.py. Asks for merged main at exactly `sha` to go to `targets`. It happens only after
        the tip run is green for that target; a red target is held on its own."""


class Tip(Protocol):
    def kick(self, repo: str) -> None:
        """U3, lander/tip.py. Wakes the coalesced tip run for `repo` after a merge. Idempotent."""
