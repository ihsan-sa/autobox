"""Called by cc-sandbox selfcheck through cc-member-v2; all effects use fixtures."""
import errno
import grp
import hashlib
import json
import os
from pathlib import Path
import subprocess as sp
import tempfile
import time


def selfcheck(m):
    passed = failed = 0

    def check(ok, name, detail=""):
        nonlocal passed, failed
        passed += bool(ok)
        failed += not ok
        print(f"  {'ok' if ok else 'FAIL'} v2: {name}" + (f": {detail}" if not ok else ""), flush=True)

    def call(command, **kwargs):
        return sp.run([str(a) for a in command], stdin=sp.DEVNULL, stdout=sp.PIPE,
                      stderr=sp.PIPE, timeout=30, **kwargs)

    with tempfile.TemporaryDirectory(prefix="cc-member-v2-") as temp:
        root = Path(temp).resolve()
        h, v = root / "home", root / "vault"
        for p in (h / ".claude", h / ".local/bin", h / ".cc/members/team", v / "registry", v / "repos"):
            p.mkdir(parents=True)
        (h / ".local/bin/claude").write_text("#!/bin/sh\nexit 0\n")
        (h / ".local/bin/claude").chmod(0o755)
        original_settings = b'{"hooks":{},"permissions":{"deny":["fixture-deny"]}}\n'
        (h / ".claude/settings.json").write_bytes(original_settings)
        (h / ".cc/members/team/credentials.json").write_text('{"claudeAiOauth":{"accessToken":"fixture"}}')
        (h / ".claude.json").write_text('{}')
        env = dict(os.environ, HOME=str(h), CC_MEMBER_V2_ROOT=str(v), CC_MEMBER_V2="1")
        env.pop("CC_MEMBER_SANDBOX", None)
        # Fixture construction is trusted Git. After provisioning, member Git runs inside.
        seed = root / "seed"
        for args in (["init", "-q", "--template=", "-b", "main", seed],
                     ["-C", seed, "-c", "user.name=fixture", "-c", "user.email=fixture", "commit", "-qm", "initial", "--allow-empty"],
                     ["clone", "-q", "--bare", "--no-local", seed, v / "repos/project.git"]):
            result = call(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", *args], env=env)
            m.require(result.returncode == 0, result.stderr.decode())
        base = call(["/usr/bin/git", "-C", seed, "rev-parse", "HEAD"], env=env).stdout.decode().strip()
        r = dict(workspace="team", project="project", remote=str(seed), branch="refs/heads/task", base=base, generation=1)
        (v / "registry/task.json").write_text(json.dumps(r))
        command = [m.BIN / "cc-sandbox", "member", "team", "task", "--"]

        # Freeze the pre-M2 legacy functions; drive them directly as the off oracle.
        source = (m.BIN / "cc-sandbox").read_text()
        legacy = source[source.index("build_member(){"):source.index("CLAUDEBIN=")]
        digest = hashlib.sha256(legacy.encode()).hexdigest()
        check(digest == "c8b472a1e7a2b5ffbd6942617f79eea101a90151d1e392ef81239c847f4b3068", "legacy implementation frozen",
              "build_member/launch_member changed. The flag-off cases below still pass, because both sides run "
              f"the same edited code. Re-read the change against the legacy profile, then pin it: {digest}")
        stub = root / "stub"
        stub.mkdir()
        (stub / "bwrap").write_text('#!/usr/bin/python3 -IS\nimport os,sys,json\nprint(json.dumps([sys.argv[1:],os.read(3,100000).decode(),os.environ.get("TMUX")]))\n')
        (stub / "bwrap").chmod(0o755)
        (h / "dev/team/.cc").mkdir(parents=True)
        (h / "dev/team/.cc/member-workspace").touch()
        legacy_functions = root / "legacy.sh"
        legacy_functions.write_text(source[:source.index('case "${1:-}" in selfcheck)')])
        offenv = dict(env, PATH=f"{stub}:/usr/bin:/bin", TMUX="fixture", CC_MEMBER_V2="0")
        direct = ["/usr/bin/bash", "-c", 'source "$1"; launch_member team "" "$2" "$3" "$4"',
                  str(m.BIN / "cc-sandbox"), legacy_functions, "/usr/bin/printf", "a b", 'c"d\n$e']
        control = call(direct, env=offenv)
        for flag in (None, "", "0"):
            e = dict(offenv)
            if flag is None:
                e.pop("CC_MEMBER_V2")
            else:
                e["CC_MEMBER_V2"] = flag
            result = call([m.BIN / "cc-sandbox", "member", "team", "--", *direct[-3:]], env=e)
            check(control.returncode == result.returncode == 0 and control.stdout == result.stdout,
                  f"flag {flag!r}: argv, fd 3 and environment equal legacy control", result.stderr.decode())

        minimal = ["/usr/bin/bwrap", "--unshare-user", "--unshare-pid", "--ro-bind", "/usr", "/usr",
                   "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64"]
        probe = call(minimal + ["--", "/usr/bin/true"])
        check(probe.returncode == 0, "real bwrap available", probe.stderr.decode().strip())
        if probe.returncode != 0:
            print("v2: mount, canary, seed and race cases NOT RUN: namespace creation denied (gate failure)")
        else:
            result = call([m.BIN / "cc-member-v2", "provision", "task"], env=env)
            check(result.returncode == 0, "independent bundle seed", result.stderr.decode())
            if result.returncode == 0:
                script = '''
lsset(){ ls -A "$1" 2>/dev/null | LC_ALL=C sort | tr '\\n' ','; }
for p in home claude cc tracks run runcc etc ssl; do
  case $p in home) d=$HOME;; claude) d=$HOME/.claude;; cc) d=$HOME/.cc;;
    tracks) d=$HOME/.cc/worktrees/team;; run) d=/run;; runcc) d=/run/cc;; etc) d=/etc;; ssl) d=/etc/ssl;; esac
  printf '%s=%s\\n' "$p" "$(lsset "$d")"
done
printf 'groups=%s\\n' "$(id -Gn | tr ' ' '\\n' | LC_ALL=C sort -u | tr '\\n' ',')"
printf 'tmux=%s\\n' "${TMUX-unset}"
printf 'status=%s\\n' "$(git status --porcelain)"
printf 'log=%s\\n' "$(git log -1 --format=%H)"
printf 'board=%s\\n' "$(cat /run/cc/view/board.json)"
for p in "$HOME/.ssh" "$HOME/.config" "$HOME/.cc" /run/docker.sock /run/user /etc/gitconfig /etc/ssl/private; do
  [ ! -e "$p" ] || exit 9
done
printf 'absent=host credentials, host config, host state, worktrees, sockets, other tasks\\n'
'''
                groups = {grp.getgrgid(os.getgid()).gr_name}
                if any(g != os.getgid() for g in os.getgroups()):
                    groups.add("nogroup")
                expected = {"home": ".cache,.claude,.claude.json,.local,.npm,bin,",
                    "claude": ".credentials.json,settings.json,", "cc": "", "tracks": "", "run": "cc,", "runcc": "broker,view,",
                    "etc": "alternatives,group,hosts,localtime,nsswitch.conf,passwd,resolv.conf,ssl,", "ssl": "certs,",
                    "groups": "".join(g + "," for g in sorted(groups)), "tmux": "unset", "status": "", "log": base,
                    "board": json.dumps({"workspace": "team", "task": "task"}),
                    "absent": "host credentials, host config, host state, worktrees, sockets, other tasks"}

                def enumeration(prefix=""):
                    out = call(command + ["/usr/bin/sh", "-ec", prefix + script], env=dict(env, TMUX="must-disappear"))
                    return out, dict(line.split("=", 1) for line in out.stdout.decode().splitlines() if "=" in line)

                out, actual = enumeration()
                check(out.returncode == 0 and actual == expected, "canary exact documented sets", f"{actual}; {out.stderr.decode()}")
                out, extra = enumeration('touch "$HOME/.unexpected";\n')
                check(out.returncode == 0 and extra != expected and extra == dict(expected, home=expected["home"].replace("bin,", ".unexpected,bin,")),
                      "canary control detects one extra entry", str(extra))
                commit = call(command + ["/usr/bin/sh", "-ec", '''
test -d .git; test ! -e .git/commondir; test ! -e .git/objects/info/alternates
git config core.fsmonitor false
mkdir .git/hooks
printf '#!/bin/sh\\nexit 0\\n' > .git/hooks/pre-commit; chmod +x .git/hooks/pre-commit
echo ordinary > file; git add file; git commit -qm ordinary
test "$(git log -1 --format=%s)" = ordinary
mkdir /local/before; mv /local/before /local/after; test -d /local/after
'''], env=env)
                check(commit.returncode == 0, "ordinary commit, writable config/hook and local rename", commit.stderr.decode())
                # THE FENCE IS ACTUALLY ON. Drop the `cc-fence run` prefix from build() and every case above
                # still passes, because the mounts alone carry them. These three writes are permitted by the
                # mounts — the root tmpfs and /dev are bwrap's own, and the control below writes all three — so
                # only Landlock refuses them, and only if the launcher really ran the fence.
                outside = 'for p in /pwn /dev/shm/pwn /dev/pwn; do touch "$p" 2>/dev/null && exit 8; done'
                inside = 'touch /work/allowed /local/allowed "$HOME/allowed" /tmp/allowed || exit 9'
                fenced = call(command + ["/usr/bin/sh", "-c", f"{inside}\n{outside}\nexit 0"], env=env)
                loose = call(minimal + ["--dev", "/dev", "--", "/usr/bin/sh", "-c", outside])
                check(fenced.returncode == 0 and loose.returncode == 8,
                      "the fence denies writes outside the task's trees; unfenced bwrap permits the same three",
                      f"fenced rc={fenced.returncode} {fenced.stderr.decode()}; unfenced rc={loose.returncode}")
                files = lambda p: {(f.stat().st_dev, f.stat().st_ino) for f in p.rglob("*") if f.is_file()}
                check(not (files(v / "repos/project.git/objects") & files(v / "data/task/repo/.git/objects")), "seed has no host object hardlinks (legacy shared Git control in cc-sandbox)")
                out = call(command + ["/usr/bin/sh", "-ec", 'cat "$HOME/.claude/settings.json"; touch /local/allowed; ! touch "$HOME/.claude/settings.json" 2>/dev/null'], env=env)
                merged = call([m.BIN / "cc-sandbox", "__settings-copy"], env=env)
                check(out.returncode == 0 and out.stdout == merged.stdout and (h / ".claude/settings.json").read_bytes() == original_settings,
                      "real settings equal legacy merge; RO denial with task-write control")
                # The workspace credential is the HOST FILE, bound rw at claude's path — the legacy invariant
                # (cc-sandbox: claude rewrites it in place, and a copy lost the refresh at exit). The read-only
                # settings.json in the case above is this one's control: both are file mounts, one each way.
                refreshed = '{"claudeAiOauth":{"accessToken":"refreshed"}}'
                out = call(command + ["/usr/bin/sh", "-ec", 'printf %s "$0" > "$HOME/.claude/.credentials.json"',
                                      refreshed], env=env)
                check(out.returncode == 0 and (h / ".cc/members/team/credentials.json").read_text() == refreshed,
                      "a credential refresh inside reaches the host file (read-only settings.json above is the control)",
                      out.stderr.decode())
                out = call([m.BIN / "cc", "__runmember", "team", "task"], env=dict(env, CC_CLAUDE="/usr/bin/true"))
                check(out.returncode == 0 and not (h / ".cc/worktrees/team/task").exists(),
                      "host v2 branch bypasses legacy tree/session setup (off control above)", out.stderr.decode())
                forged = v / "data/task/repo/.cc"
                forged.mkdir(); (forged / "track").write_text("other\nother-task\n")
                out = call(command + ["/usr/bin/sh", "-c", 'printf "%s/%s/%s" "$CC_WORKSPACE" "$CC_TASK_ID" "$CC_SESSION_GENERATION"'], env=env)
                check(out.returncode == 0 and out.stdout == b"team/task/1", "forged .cc/track cannot select identity; registry control retained")
                out = call([m.BIN / "cc-member-v2", "run", "other", "task", "--", "/usr/bin/true"], env=env)
                check(out.returncode == 2 and b"not registered" in out.stderr, "cross-workspace request refused; registered request works")
                import pty
                master, slave = pty.openpty()
                try:
                    out = sp.run([str(x) for x in command + ["/usr/bin/true"]], env=env, stdin=slave, stdout=sp.PIPE, stderr=sp.PIPE, timeout=30)
                    check(out.returncode == 2 and b"pipes or /dev/null" in out.stderr, "TTY refused; pipe launches above execute")
                    # …and the HOST side is not fenced by the operator's terminal: provisioning runs the seed
                    # step in the sandbox too, but hands it stdio of its own, so the same pty that refuses a
                    # launch provisions a second task fine.
                    (v / "registry/task2.json").write_text(json.dumps(r))
                    out = sp.run([str(x) for x in [m.BIN / "cc-member-v2", "provision", "task2"]], env=env,
                                 stdin=slave, stdout=slave, stderr=sp.PIPE, timeout=60)
                    check(out.returncode == 0 and (v / "data/task2/repo/.git").is_dir(),
                          "provisioning from a terminal works; the launch above is the refusal", out.stderr.decode())
                finally:
                    os.close(master); os.close(slave)
                # THE RECORD IS THE AUTHORITY: workspace, project, remote, branch, base and generation all
                # decide what gets built and where it may push, so each is checked before anything exists.
                # An unknown field and a missing one are both refused, rather than read for the keys it knows.
                # `generation=True` is in here because bool is a subclass of int: `type(x) is int` refuses it
                # and `isinstance` would not, and a true generation never retires.
                shapes = [(dict(r, extra="x"), "invalid registry fields"),
                          ({k: val for k, val in r.items() if k != "base"}, "invalid registry fields"),
                          (dict(r, workspace="Team"), "invalid workspace"),
                          (dict(r, project="../escape"), "invalid project"),
                          (dict(r, generation=0), "invalid session generation"),
                          (dict(r, generation=True), "invalid session generation"),
                          (dict(r, remote=""), "invalid permitted remote"),
                          (dict(r, base=base[:39]), "base must be a full object ID"),
                          (dict(r, branch="refs/tags/x"), "destination must be a branch ref"),
                          (dict(r, branch="refs/heads/../x"), "check-ref-format")]
                worst = ""
                for record, reason in shapes:
                    (v / "registry/checked.json").write_text(json.dumps(record))
                    out = call([m.BIN / "cc-member-v2", "provision", "checked"], env=env)
                    if not (out.returncode == 2 and reason.encode() in out.stderr):
                        worst = f"{reason}: rc={out.returncode} {out.stderr.decode()}"
                # …and the SAME id with the good record provisions, so the refusals are the fields' doing.
                (v / "registry/checked.json").write_text(json.dumps(r))
                good = call([m.BIN / "cc-member-v2", "provision", "checked"], env=env)
                check(not worst and good.returncode == 0,
                      "every registry field is checked before anything is built; the good record provisions",
                      worst or good.stderr.decode())
                # A RECORD EDITED AFTER PROVISIONING DOES NOT REBIND A LIVE TASK. The launch compares what
                # provisioning committed against what the registry says now, and refuses rather than seed a
                # repo for one branch and run it for another.
                (v / "registry/task2.json").write_text(json.dumps(dict(r, branch="refs/heads/elsewhere")))
                edited = call([m.BIN / "cc-member-v2", "run", "team", "task2", "--", "/usr/bin/true"], env=env)
                (v / "registry/task2.json").write_text(json.dumps(r))
                restored = call([m.BIN / "cc-member-v2", "run", "team", "task2", "--", "/usr/bin/true"], env=env)
                check(edited.returncode == 2 and b"task binding changed" in edited.stderr
                      and restored.returncode == 0,
                      "an edited record refuses the launch; the record as provisioned still runs",
                      f"edited rc={edited.returncode} {edited.stderr.decode()}; "
                      f"restored rc={restored.returncode} {restored.stderr.decode()}")

            # Execute the swap in a second namespace AFTER opening, BEFORE mounting.
            oldenv = dict(os.environ)
            os.environ.update(env)
            try:
                launcher = m.Launcher()
                launcher.record("task")   # the real record, so the permitted-mount set is the real one
                mutable, victim = h / "dev/team/race", root / "victim"
                mutable.mkdir(); victim.mkdir()
                (victim / "sentinel").write_text("safe")
                for pinned in (False, True):
                    source = mutable / ("pinned" if pinned else "vulnerable")
                    source.mkdir(); (source / "sentinel").write_text("own")
                    launcher.b = minimal.copy()
                    fd = launcher.mount(source, "/chosen", True)
                    identity = os.fstat(fd)
                    attacker = call(minimal + ["--bind", mutable, "/mutable", "--", "/usr/bin/sh", "-ec",
                        'mv "/mutable/$1" "/mutable/$1.opened"; ln -s "$2" "/mutable/$1"', "swap", source.name, victim])
                    check(attacker.returncode == 0 and source.is_symlink(), f"swap executed between open and mount: pinned={pinned}")
                    if not pinned:
                        launcher.b[-3:] = ["--bind", str(source), "/chosen"]
                    result = call(launcher.b + ["--", "/usr/bin/sh", "-ec", "stat -c '%d:%i' /chosen; echo changed > /chosen/sentinel"], pass_fds=(fd,))
                    want = identity if pinned else victim.stat()
                    check(result.returncode == 0 and result.stdout.decode().strip() == f"{want.st_dev}:{want.st_ino}" and
                          (victim / "sentinel").read_text().strip() == ("safe" if pinned else "changed"),
                          f"mounted inode and victim: {'fd pinned' if pinned else 'vulnerable pathname control'}", result.stderr.decode())
                    (victim / "sentinel").write_text("safe")
                badv = h / "dev/team/unsafe-vault"
                badv.mkdir(mode=0o700)
                result = call(minimal + ["--bind", h / "dev/team", "/member", "--", "/usr/bin/sh", "-ec", 'echo attack > /member/unsafe-vault/record'])
                check(result.returncode == 0 and (badv / "record").read_text() == "attack\n", "member-writable parent attack control, same UID, mode 0700")
                os.environ["CC_MEMBER_V2_ROOT"] = str(badv)
                try:
                    m.Launcher()
                    refused = False
                except ValueError as exc:
                    refused = "member-writable parent" in str(exc)
                check(refused, "member-writable parent refused before provisioning")
                launcher.b = []
                try:
                    launcher.mount(launcher.data.parent, "/bad", True)
                    refused = False
                except ValueError as exc:
                    refused = "member-writable parent" in str(exc)
                check(refused, "mounting a task parent refused; leaf fd mount above works")
                # AN ALLOW-LIST, so the sources under V that M2 does not mount cannot be mounted at all:
                # the record that decides this task's authority, this or another session's generated
                # settings directory, the lock dir, another task's data. Naming what was forbidden left
                # every one of those reachable by writing a line in a later milestone.
                def mount_refusal(src):
                    launcher.b = []
                    try:
                        launcher.mount(src, "/probe")
                        return ""
                    except ValueError as exc:
                        return str(exc)
                launcher.endpoint.mkdir(parents=True, exist_ok=True)   # the host's at launch; the broker removes it at exit
                permitted = [launcher.data / "repo", launcher.data / "state",
                             launcher.control / "settings.json", launcher.control / "view", launcher.endpoint]
                blocked = [v / "registry", v / "registry/task.json", v / "control", launcher.control,
                           v / "state/task", v / "data/task2/repo", v / "endpoints/task2-1"]
                check(all(mount_refusal(src) == "" for src in permitted)
                      and all("permitted mounts" in mount_refusal(src) for src in blocked),
                      "permitted mounts include this endpoint; registry, control, lock, other task data "
                      "and another session endpoint refuse (the five permitted sources are the control)",
                      str([(str(src), mount_refusal(src)) for src in permitted + blocked]))
                # Inventory is based on mounts, including an older process with no role env.
                with sp.Popen([str(x) for x in minimal + ["--bind", v, "/exposed", "--", "/usr/bin/sh", "-ec",
                              'exec 3< /exposed; echo ready; read answer']], stdin=sp.PIPE, stdout=sp.PIPE,
                              stderr=sp.PIPE) as older:
                    try:
                        m.require(older.stdout.readline() == b"ready\n", "inventory control did not start")
                        try:
                            m.inventory(v)
                            refused = False
                        except ValueError as exc:
                            refused = "exposes V" in str(exc)
                        check(refused, "older live namespace exposes V: refused")
                    finally:
                        older.communicate(b"stop\n", timeout=10)
                m.inventory(v)
                check(True, "inventory control: provisioning allowed after exposed namespace exits")
                # …AND UNDER V IS EXPOSURE TOO, not only V and above. The registry decides a task's
                # authority and the broker re-reads it under the lock; the state directory is the lock
                # and the status log. A namespace holding either is refused like one holding V. The
                # controls are what this walk must NOT refuse: the leaf a live session of another task
                # holds — every concurrent task holds its own — and a directory that is not V's at all.
                def bound(source):
                    with sp.Popen([str(x) for x in minimal + ["--bind", source, "/bound", "--",
                                  "/usr/bin/sh", "-ec", 'echo ready; read answer']],
                                  stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE) as held:
                        try:
                            m.require(held.stdout.readline() == b"ready\n", "mount case did not start")
                            try:
                                m.inventory(v)
                                return ""
                            except ValueError as exc:
                                return str(exc)
                        finally:
                            held.communicate(b"stop\n", timeout=10)
                under = {str(s): bound(s) for s in (v / "registry", v / "state/task",
                                                    v / "data/task", v / "control/task-1")}
                beside = {str(s): bound(s) for s in (v / "data/task/repo", v / "control/task-1/view",
                                                     h / "dev/team")}
                check(all("exposes V" in r for r in under.values()) and not any(beside.values()),
                      "a namespace binding the registry, the host lock, a task's data or its control is "
                      "refused; one binding a session's own leaf, or a directory outside V, is not",
                      str(under | beside))
                # AND AN INNOCENT SANDBOX MUST NOT REFUSE THE BOX. Its private root spells "/", which is a
                # parent of V, and it can mkdir V's own spelling in its own tmpfs: both are text, naming
                # different objects on a different filesystem. `exec 3< /` is the whole attack, one line
                # from any live sandbox, and it named that session in the refusal. The case above, which
                # really does reach V and holds a descriptor on it, is the control that this still refuses.
                with sp.Popen([str(x) for x in minimal + ["--", "/usr/bin/sh", "-ec",
                              'mkdir -p "$1"; exec 3< /; exec 4< "$1"; echo ready; read answer',
                              "innocent", v]], stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE) as innocent:
                    try:
                        m.require(innocent.stdout.readline() == b"ready\n", "innocent control did not start")
                        try:
                            m.inventory(v)
                            refused = ""
                        except ValueError as exc:
                            refused = str(exc)
                        check(not refused,
                              "a sandbox holding its own / and V's spelling in its own tmpfs is not an exposure",
                              refused)
                    finally:
                        innocent.communicate(b"stop\n", timeout=10)
                # A PID THAT EXITS UNDER THE WALK IS NOT EVIDENCE. An unreaped child keeps its /proc entry
                # under this UID, answers EINVAL on mountinfo and has already dropped ns/mnt — the exact
                # shape that refused a launch on a busy box. It must be skipped. The case above is the
                # control: a namespace that really is live still refuses.
                gone = sp.Popen(["/bin/true"])   # deliberately not polled: poll() reaps it
                try:
                    zombie = Path(f"/proc/{gone.pid}")
                    for _ in range(500):
                        if zombie.exists() and not (zombie / "ns/mnt").exists():
                            break
                        time.sleep(0.01)
                    shape = ""   # prove the walk really met the hostile shape, not a tidy /proc
                    try:
                        (zombie / "mountinfo").read_text()
                    except OSError as exc:
                        shape = errno.errorcode.get(exc.errno, str(exc.errno))
                    try:
                        m.inventory(v)
                        refused = ""
                    except ValueError as exc:
                        refused = str(exc)
                    check(shape == "EINVAL" and zombie.stat().st_uid == os.getuid() and not refused,
                          "a pid that exits under the inventory is skipped, not read as an exposure",
                          f"mountinfo={shape or 'readable'}; {refused}")
                finally:
                    gone.wait()
            finally:
                os.environ.clear(); os.environ.update(oldenv)
    print(f"cc-member-v2 selfcheck: {passed} passed, {failed} failed")
    return int(bool(failed))
