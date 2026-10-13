"""lander release — the lander lets go of a PR it queued and has not taken up, so another lander may land it.

    lander release <repo> <pr> [--by WHO] [--wait SECONDS]

perms approved this verb (perms-66, 2026-10-12) on these conditions, which are its contract. It drops the job only
while its stage is `queued`, under the repo's lane lock, and writes `released <repo>#<pr> rid=<RID> by=<WHO>
head=<SHA>` to queue.log (WHO: --by, else $USER, its control bytes taken out, anything but [A-Za-z0-9_.@+-] made `-`,
cut to 64; SHA: the head the rules were read on, the only head the caller may land). The command itself writes no
lander state. It reads the rules below, and when none refuses it files a release request in the lane's inbox
(jobs.submit: release=WHO, head=the PR's head, rid=a fresh hex id, and mark_of the job: seen=its history length,
queued_at, last=its newest history stamp), prints `lander release: <repo>#<pr> requested by <WHO> rid=<RID>` and
exits 0. A busy lane holds its lock from one job to the next, so the release does not take the lock: the lane applies
the request at its next pick, under its own lock (jobs.drain -> apply), so the lane stays the one writer of its job
files. Otherwise the command refuses: one line on stdout, `lander release: refused <repo>#<pr> <rule>: <why>`, exit
1. The rules, first match wins:
  member     a member lane: the repo is an <h>--<t> project, or the job names a member
  query      the job is an open query
  stage      there is no job, or its stage is not queued
  approval   the job carries an owner approval (jobs.approval), or an approval record is there but will not read
  lander     the job was ever planned lander-class or a lander-self query (from here on, the PR's facts)
  unread     a fact a rule below needs (the PR's head, comments or files, the base's policy, the protected paths)
             would not read: fails closed
  protected  the PR touches a protected path of the repo (the 👍 door's state)
  lander     the PR is lander-class: a changed file on the base policy's lander list or a LANDING-policy file
  handback   a standing HANDBACK the box's own login wrote: a reader's newest marker is HANDBACK at the PR's head,
             or a security reader's (its name says `security`, as lander-self reads it) newest is HANDBACK at any head
  security   the PR touches a path on the base's tests/LANDING-security.toml and perms' own file holds no record
             of the PR's head at its change digest (review.perms_recorded), as the lane itself would not merge it; a
             diff that will not read is `unread`
THE LANE APPLIES IT (apply, under the lane lock but not rest_lock, before it drains any other request). A request is
anyone's, so it is trusted for nothing but which job it names, and every rule above is read again there, the PR's
facts too, failing closed. It drops the job only when the request is whole (`request`: a hex rid, a seen that is an
int, queued_at and last stamps, a head), the job is still the one it was made for (`raced`: mark_of differs, so the
lane picked it up first, or it was queued again and a saved request is replayed), every rule passes, gh still names
the request's head (`stale-head`), and no request for the PR was filed after the release (`newer`: an owner's queue
that came later wins). Then the job goes, with its put-first record and the PR's older waiting requests (so the lane
does not make the job again from one), and `released` is logged. Else nothing is dropped and the lane logs
`release-refused <repo>#<pr> rid=<RID> by=<WHO> head=<SHA or -> <rule>: <why>` (`duplicate` for a second request a
drain finds for a PR it released; one that raises is logged `error` and moved to the inbox's failed/, out of the
names a reader of the inbox matches): the lock decides a race with the lane, and when the lane picked the job up
first the release is the loser and says so.
--wait SECONDS blocks until queue.log has the `released` (exit 0) or `release-refused` (exit 1) line for this rid,
which is the line's first field, so no WHO can stand in for it; it prints the line, and when neither came in time it
says the request still waits (exit 3). Exit 2 is usage.
"""
from __future__ import annotations

import contextlib
import os
import re
import secrets
import sys
import time

from lander import events as E
from lander import gh as GH
from lander import git as G
from lander import jobs as J
from lander import manifest as MF
from lander import review as R
from lander import types as T


class Unread(Exception):
    """A fact a rule needs would not read."""


class Refused(Exception):
    def __init__(self, rule, why):
        super().__init__(f"{rule}: {why}")
        self.rule, self.why = rule, why


def facts(repo, pr) -> dict:
    """What the remote rules read: {head, comments, files, lander (globs), protected (rules), security (the changed
    files on the base's security list), digests (the change's, when security names one)}. Raises Unread."""
    from lander import lane as L   # lane imports half the package; only a release that gets this far needs it
    root = J.repo_root(repo)
    j, err = GH.pr_facts(root, pr, "headRefOid,baseRefName,comments,files")
    if j is None:
        raise Unread(f"gh would not read the PR: {err}")
    head, base = (j.get("headRefOid") or "").strip(), (j.get("baseRefName") or "").strip()
    if not (head and base):
        raise Unread("gh named no head or no base branch")
    named = {(f.get("path") or "") for f in j.get("files") or [] if isinstance(f, dict)} - {""}
    try:
        with G.git_lock(root):
            sha = G.fetch(root, base)[base]
            G.fetch_ids(root, f"refs/pull/{pr}/head")
    except G.GitError as e:
        raise Unread(f"git would not fetch the base or the PR: {e}") from None
    try:   # gh names only a rename's new path, and stops at GH_PR_FILES: git, at the head gh named, names both sides
        files = sorted(named | set(G.pr_changed(root, sha, head)))
    except G.GitError as e:
        raise Unread(f"git would not list the PR's files at {head[:12]}: {e}") from None
    try:
        pol = MF.load(root, sha, fallback=MF.host_fallback(repo)).policy
    except (G.GitError, MF.ManifestError) as e:
        raise Unread(f"the base's policy would not read: {e}") from None
    rules = L.protected_rules(repo)
    if rules is None:
        raise Unread("cc-config would not read the repo's protected paths")
    security, digests = [p for p in files if MF.match(pol.security_review, p)], []
    if security:   # the digests a perms LAND may carry, as review.keys() names them
        diff = R.diff_of(root, sha, head)
        if not diff:
            raise Unread(f"git would not diff the PR at {head[:12]}")
        digests = sorted({R.change_digest(diff), R.change_digest(diff, legacy=True)} - {""})
    return {"head": head, "comments": j.get("comments") or [], "files": files,
            "lander": list(pol.lander) + [p + MF.POLICY for p in MF.PREFIXES], "protected": rules,
            "security": security, "digests": digests}


def standing_handback(comments, head):
    """(reader, marker head) of a standing box-written HANDBACK, or None. Each reader's newest marker counts: a
    HANDBACK at the PR's head stands, and a security reader's stands at any head; a marker naming no head stands."""
    newest = {}
    for c in comments:
        v = R.imported(c.get("body", "")) if isinstance(c, dict) and c.get("viewerDidAuthor") else None
        if v:
            newest[v.model or "?"] = v
    for by, v in newest.items():
        at = (v.extra or {}).get("head") or ""
        if v.verdict == T.HANDBACK_VERDICT and ("security" in by.lower() or not at or head.startswith(at)):
            return by, at
    return None


def local_rules(repo, pr, job):
    """The rules the job file and the approval record answer. Raises Refused."""
    if "--" in repo or (job is not None and job.member):
        raise Refused("member", f"{repo} is a member lane; its own lander lands it")
    if job is not None and job.state == T.QUERY:
        raise Refused("query", f"the job is an open query: {job.extra.get('why') or 'no reason recorded'}")
    if job is None or job.state != T.QUEUED:
        raise Refused("stage", "the lander has no job for it" if job is None else
                      f"its stage is {J.stage_of(job)}, and only a queued job is released")
    if J.approval(repo, pr):
        raise Refused("approval", "it carries the owner's approval")
    if os.path.lexists(J.approval_path(repo, pr)):   # one that will not parse is not "none": fails closed
        raise Refused("approval", "an approval record is there but will not read")
    if (job.plan is not None and job.plan.klass == T.LANDER) or any(
            "lander-self" in str(h.get("why") or "") for h in job.history if isinstance(h, dict)):
        raise Refused("lander", "it was lander-class before (planned so, or a lander-self query); lander-self lands it")


def remote_rules(job, f):
    """The rules the PR's facts answer. Raises Refused."""
    from lander import lane as L
    hit = L.first_hit(f["files"], f["protected"]) if f["protected"] else None
    if hit:   # a path is the branch's to name, so it is shown through J.path_names, as the lane shows one
        shown = hit[0] if hit[0] == "?" else J.path_names([hit[0]])
        raise Refused("protected", L.hold_words(job.repo, (shown, hit[1])))
    on = next((p for p in f["files"] if MF.match(f["lander"], p)), "")
    if on:
        raise Refused("lander", f"it is lander-class ({J.path_names([on])} is on the lander list); "
                                "lander-self lands it")
    hb = standing_handback(f["comments"], f["head"])
    if hb:
        raise Refused("handback", f"{hb[0]}'s HANDBACK at {hb[1][:12] or 'no head'} stands")
    sec = f.get("security") or []
    if sec and not R.perms_recorded(job.repo, job.pr, f["head"], set(f.get("digests") or [])):
        raise Refused("security", f"it changes {J.path_names(sec[:1])}, a security path, and perms has recorded no "
                                  "security read of this change")


def all_rules(repo, pr, job) -> dict:
    """Every rule, the job file's then the PR's (read now, failing closed). -> the facts. Raises Refused."""
    local_rules(repo, pr, job)
    try:
        f = facts(repo, pr)
    except Unread as e:
        raise Refused("unread", str(e)) from None
    remote_rules(job, f)
    return f


def mark_of(job) -> dict:
    """What ties a request to the one queued job it was made for: a re-queue writes a new queued_at, any move a new
    history entry, so a request saved and replayed later does not match the job it finds."""
    last = job.history[-1] if job.history and isinstance(job.history[-1], dict) else {}
    return {"seen": len(job.history), "queued_at": str(job.extra.get("queued_at") or ""),
            "last": str(last.get("at") or "")}


def release(repo, pr, by) -> tuple:
    """-> (0, line, rid) requested, or (1, line, "") refused. Writes nothing but the inbox request."""
    try:
        job = J.load(repo, pr)
        f = all_rules(repo, pr, job)
    except Refused as e:
        return 1, f"lander release: refused {repo}#{pr} {e.rule}: {e.why}", ""
    rid = secrets.token_hex(6)
    J.submit(repo, pr, release=by, head=f["head"], rid=rid, **mark_of(job))
    return 0, f"lander release: {repo}#{pr} requested by {by} rid={rid}", rid


RID_RE, HEAD_RE = re.compile(r"[0-9a-f]{6,32}"), re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def clean_by(by) -> str:
    """WHO as it goes on a queue.log line: its control bytes taken out (J._CONTROL), then anything but
    [A-Za-z0-9_.@+-] made `-` and cut to 64, so a WHO (the inbox is anyone's) can never write an escape, or a field of
    its own, a `rid=` above all, into the line a waiter reads."""
    return re.sub(r"[^\w.@+-]+", "-", J._CONTROL.sub("", str(by or "")).strip()).strip("-")[:64] or "?"


def clean_rid(rid) -> str:
    return rid if isinstance(rid, str) and RID_RE.fullmatch(rid) else "-"


def refuse(repo, pr, req, rule, why) -> str:
    """Log `release-refused` for one request and return the lane's line."""
    E.log("release-refused", repo, pr, f"{rule}: {why}", rid=clean_rid(req.get("rid")), by=clean_by(req.get("release")),
          head=req.get("head") if isinstance(req.get("head"), str) and HEAD_RE.fullmatch(req["head"]) else "-")
    return f"{repo}#{pr} release refused ({rule})"


def apply(repo, pr, req, path="") -> str:
    """The lane's half: call only under lane_lock(repo), never under rest_lock (jobs.drain applies it before taking
    that): it reads gh and fetches under git_lock, which a tick takes while holding rest_lock (tip.kick), so nothing
    holds rest_lock across a fetch and no path takes the two in the other order. `path` is the request's own
    file. A request is anyone's, so it is trusted for nothing but which job it names: every rule is read again here,
    the PR's too, failing closed. Drops the job when it is still the queued one the request was made for (mark_of),
    every rule passes at the head the request names, and no request for the PR was filed after it; the PR's older
    requests go with it. Logs `released … head=` or `release-refused`, and returns that line. The caller removes the
    request itself."""
    by, rid, head = clean_by(req.get("release")), clean_rid(req.get("rid")), req.get("head")
    job = J.load(repo, pr)
    try:
        mark = {k: req.get(k) for k in ("seen", "queued_at", "last")}
        if rid == "-" or type(mark["seen"]) is not int or not all(type(mark[k]) is str for k in ("queued_at", "last")) \
                or not (isinstance(head, str) and HEAD_RE.fullmatch(head)):
            raise Refused("request", "the request has no hex rid, no whole seen count, no queued_at or last stamp, "
                                     "or no head; nothing released")
        if job is not None and mark_of(job) != mark:
            raise Refused("raced", "the job is not the one the release read (the lane picked it up first, or it was "
                                   "queued again); the lane keeps it")
        f = all_rules(repo, pr, job)
        if f["head"] != head:
            raise Refused("stale-head", f"the PR moved from {head[:12]} to {f['head'][:12]} after the release read "
                                        "it; release it again")
        mine = (os.path.getmtime(path), path) if path and os.path.exists(path) else None
        older = []
        for p, r in J.requests(repo):
            if r["pr"] != pr or r.get("release"):   # drain answers each release request itself
                continue
            try:
                key = (os.path.getmtime(p), p)
            except OSError:
                continue
            if mine is None or key > mine:
                raise Refused("newer", "a request for the PR was filed after the release; the lane keeps the job")
            older.append(p)
    except Refused as e:
        return refuse(repo, pr, req, e.rule, e.why)
    J.remove(job)
    for p in older:
        with contextlib.suppress(OSError):
            os.unlink(p)
    E.log("released", repo, pr, rid=rid, by=by, head=head)
    return f"{repo}#{pr} released by {by}"


WAIT_RE = r"\t(released|release-refused) {repo}#{pr} rid={rid} by=\S+ head=\S+(?: |$)"   # rid is the 1st field


def wait(repo, pr, rid, secs, poll=1.0) -> tuple:
    """-> (0, line) released, (1, line) refused by the lane, (3, line) neither within `secs`."""
    pat = re.compile(WAIT_RE.format(repo=re.escape(repo), pr=pr, rid=re.escape(rid)))
    end = time.monotonic() + secs
    while True:
        try:
            with open(E.log_path()) as fh:
                for ln in fh:
                    m = pat.search(ln)
                    if m:
                        return (0 if m.group(1) == "released" else 1), ln.rstrip("\n").split("\t", 1)[-1]
        except OSError:
            pass
        if time.monotonic() >= end:
            return 3, f"lander release: {repo}#{pr} rid={rid} still waits for the lane after {secs:g}s"
        time.sleep(poll)


def cmd_release(argv):
    args, by, secs = list(argv), os.environ.get("USER") or "?", None
    for flag in ("--by", "--wait"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                args = []
                break
            val = args[i + 1]
            del args[i:i + 2]
            if flag == "--by":
                by = val
            else:
                try:
                    secs = float(val)
                except ValueError:
                    secs = -1.0
                if not 0 <= secs <= 86400:
                    args = []
                    break
    if len(args) != 2 or not J.REPO_RE.fullmatch(args[0]) or not args[1].isdigit() or not by.strip():
        print("usage: lander release <repo> <pr> [--by WHO] [--wait SECONDS]", file=sys.stderr)
        return 2
    repo, pr = args[0], int(args[1])
    rc, line, rid = release(repo, pr, clean_by(by))
    print(line)
    if rc or secs is None:
        return rc
    rc, line = wait(repo, pr, rid, secs)
    print(line)
    return rc


COMMANDS = {"release": (cmd_release, "let go of a queued PR so another lander may land it <repo> <pr> [--by WHO] "
                                     "[--wait SECONDS]")}
