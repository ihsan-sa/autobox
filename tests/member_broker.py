"""Private fixtures for cc-member-broker selfcheck; real launcher, sockets and namespaces."""
import array
import fcntl
import json
import os
from pathlib import Path
import select
import socket
import subprocess as sp
import tempfile
import time

CLIENT = r'''
import array, json, os, socket, sys, time
def connect(spec):
    c = socket.socket(socket.AF_UNIX); c.settimeout(8)
    c.connect('/run/cc/broker/sock')
    data = spec.get('raw', json.dumps(spec.get('request')) + '\n').encode() + spec.get('body', '').encode()
    if spec.get('fd'):
        fd = os.open('/dev/null', os.O_RDONLY)
        c.sendmsg([data], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]))]); os.close(fd)
    else:
        c.sendall(data)
    if not spec.get('stall'): c.shutdown(socket.SHUT_WR)
    return c
def answer(c):
    with c:
        data = b''
        while b'\n' not in data:
            part = c.recv(65536)
            if not part: raise ValueError('missing response')
            data += part
        return json.loads(data)
print(json.dumps({'ready': True, 'mount': next(line.split()[5] for line in open('/proc/self/mountinfo') if line.split()[4] == '/run/cc/broker')}), flush=True)
for line in sys.stdin:
    spec = json.loads(line)
    if 'parallel' in spec:
        sockets = [connect(s) for s in spec['parallel']]
        print('submitted', flush=True)
        value = [answer(c) for c in sockets]
    else:
        value = answer(connect(spec))
    print(json.dumps(value), flush=True)
'''


def selfcheck(m):
    passed = failed = 0
    def check(ok, name, detail=""):
        nonlocal passed, failed
        passed += bool(ok); failed += not ok
        print(f"  {'ok' if ok else 'FAIL'} broker: {name}" + (f": {detail}" if not ok else ""), flush=True)
    def line(p):
        m.require(select.select([p.stdout], [], [], 12)[0], "fixture response timed out")
        raw = p.stdout.readline()
        if not raw:
            raise ValueError("fixture exited: " + p.stderr.read().decode())
        return raw
    with tempfile.TemporaryDirectory(prefix="cc-member-broker-") as temp:
        root = Path(temp).resolve(); h, v = root / "home", root / "v"
        for name in (".claude", ".local/bin", ".cc/members/team"):
            (h / name).mkdir(parents=True)
        (h / ".local/bin/claude").write_text("#!/bin/sh\nexit 0\n")
        (h / ".local/bin/claude").chmod(0o755)
        (h / ".claude/settings.json").write_text('{}')
        (h / ".cc/members/team/credentials.json").write_text('{"claudeAiOauth":{"accessToken":"fixture"}}')
        (v / "registry").mkdir(parents=True)
        record = dict(workspace="team", project="project", remote="fixture", branch="refs/heads/task", base="a"*40, generation=1)
        for task in ("task", "other"):
            (v / "registry" / f"{task}.json").write_text(json.dumps(record))
            (v / "state" / task).mkdir(parents=True)
            (v / "state" / task / "ready.json").write_text(json.dumps(record))
            for part in ("repo", "state", "claude", "npm", "cache"):
                (v / "data" / task / part).mkdir(parents=True)
        env = dict(os.environ, HOME=str(h), CC_MEMBER_V2_ROOT=str(v), CC_MEMBER_V2="1")
        env.pop("CC_MEMBER_SANDBOX", None)
        command = [str(m.BIN / "cc-sandbox"), "member", "team", "task", "--", "/usr/bin/python3", "-IS", "-c", CLIENT]
        log = v / "state/task/status.jsonl"
        records = lambda: [json.loads(s) for s in log.read_text().splitlines()] if log.exists() else []
        with sp.Popen(command, env=env, stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE) as p:
            def ask(request=None, **options):
                p.stdin.write(m.encoded(dict(request=request, **options))); p.stdin.flush()
                return json.loads(line(p))
            def req(op="status", value=True, **extra):
                return dict(task="task", generation=1, **{op: value}, **extra)
            try:
                ready = json.loads(line(p))
                good = ask(req())
                check(ready["ready"] and "ro" in ready["mount"].split(",") and good["ok"],
                      "connect through RO directory and fence --ro succeeds")
                sock = v / "endpoints/task-1/sock"
                check(sock.stat().st_mode & 0o777 == 0o600, "host endpoint mode 0600; in-session connect is the control")
                outside = socket.socket(socket.AF_UNIX); outside.settimeout(5); outside.connect(str(sock))
                with outside:
                    refused = json.loads(outside.recv(65536))
                check(not refused["ok"] and refused["reason"] == "caller is outside the registered session"
                      and ask(req())["ok"], "same UID on real V path refuses; registered namespaces work")
                before = len(records())
                refused = ask(dict(req(), task="other"))
                check(not refused["ok"] and refused["reason"] == "request names another task"
                      and ask(req())["ok"] and not (v / "state/other/status.jsonl").exists()
                      and len(records()) == before + 2, "cross-task ID refuses; own task works and logs both")
                qsp = h / ".cc/queries/member/team/queries.spool"
                first = qsp.read_bytes(); ask(dict(req(), task="other"))
                check(qsp.read_bytes() == first and json.loads(first)["class"] == "nopage"
                      and json.loads(first)["workspace"] == "team", "visible refusal queues host identity once; retry deduplicates")
                for name, spec in (
                    ("two operation keys", dict(request=req(submit=0))),
                    ("descriptor with request", dict(request=req(), fd=True)),
                    ("non-object", dict(raw='[]\n')),
                    ("unknown field", dict(request=req(path="/tmp/file"))),
                    ("path value", dict(request=req("dispatch", "/tmp/file"))),
                    ("URL value", dict(request=req("dispatch", "https://invalid.test"))),
                    ("git argument", dict(request=req("board", "--force"))),
                    ("string cap", dict(request=dict(req(), task="t" * 65))),
                    ("duplicate field", dict(raw='{"task":"task","task":"task","generation":1,"status":true}\n')),
                    ("overlong line", dict(raw="x" * 4096 + "\n")),
                    ("stalled writer", dict(raw='{"task":', stall=True)),
                    ("extra line", dict(raw=json.dumps(req()) + '\n{}\n')),
                    ("short submission", dict(request=req("submit", 2), body="x")),
                    ("submission cap", dict(request=req("submit", m.PAYLOAD + 1))),
                ):
                    start = time.monotonic()
                    result = ask(**spec)
                    control = ask(req())
                    check(not result["ok"] and control["ok"] and time.monotonic() - start < 6,
                          f"{name} refuses; one well-formed request works", str(result))
                check(qsp.read_bytes() == first, "quiet framing refusals leave queue unchanged; visible refusal above queues")
                # The broker PID is a child of the host launcher; steady descriptors must expose no V path.
                broker_pid = next(int(pid) for pid in Path(f"/proc/{p.pid}/task/{p.pid}/children").read_text().split()
                                  if b"cc-member-broker" in Path(f"/proc/{pid}/cmdline").read_bytes())
                def descriptors():
                    return sorted(os.readlink(f) for f in Path(f"/proc/{broker_pid}/fd").iterdir())
                old = descriptors()
                for _ in range(3): ask(req(), fd=True)
                check(descriptors().count("/dev/null") == old.count("/dev/null") == 0
                      and not any(str(v) in s for s in old),
                      "received descriptors close; ordinary requests hold no V descriptor")
                # A GENERATION KILLED OUTRIGHT MUST LAUNCH AGAIN. cc-member-v2 sends SIGKILL when the
                # broker does not exit in 5 s, so it never reaches the removal it does at exit and the
                # socket stays; reading that as a live owner refuses the bind and strands the generation.
                def serving(task, generation):
                    return sp.Popen([str(m.BIN / "cc-member-broker"), "serve", task, str(generation)],
                                    env=env, stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE)
                spare = v / "endpoints/other-1"
                killed = serving("other", 1)
                m.require(line(killed) == b"endpoint\n", "the second endpoint did not bind")
                killed.kill(); killed.wait(timeout=12)
                for stream in (killed.stdin, killed.stdout, killed.stderr):
                    stream.close()
                left = (spare / "sock").is_socket()
                back = serving("other", 1)
                bound = line(back)
                back.stdin.close(); back.wait(timeout=12)
                for stream in (back.stdout, back.stderr):
                    stream.close()
                check(left and bound == b"endpoint\n" and not spare.exists(),
                      "a killed broker's socket is left behind, the next launch of that generation "
                      "binds anyway, and the endpoint directory goes when it exits", f"{left} {bound}")
                # …and the control: this session's broker is live, so its endpoint is not taken from it.
                sock_inode = sock.stat().st_ino
                taken = serving("task", 1)
                refusal = taken.communicate(timeout=30)[1].decode()
                check("another broker owns this endpoint" in refusal and sock.stat().st_ino == sock_inode
                      and ask(req())["ok"], "a live broker's endpoint is not taken; it keeps answering", refusal)
                for op, value in (("board", "running"), ("dispatch", "review")):
                    rejected = ask(req(op, "elsewhere")); allowed = ask(req(op, value))
                    check(not rejected["ok"] and allowed["ok"] and allowed["workspace"] == "team",
                          f"{op} refuses other values; permitted fixture change records this workspace")
                fd = os.open(v / "state/task", os.O_RDONLY | os.O_DIRECTORY)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    before = records()
                    p.stdin.write(m.encoded({"parallel": [dict(request=req("submit", 1), body=c) for c in "ab"]})); p.stdin.flush()
                    started = line(p)
                    waiting = not select.select([p.stdout], [], [], 0.2)[0] and records() == before
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    results = json.loads(line(p))
                finally:
                    os.close(fd)
                check(started == b"submitted\n" and waiting and all(r["ok"] for r in results)
                      and results[1]["seq"] == results[0]["seq"] + 1
                      and [r["transfer"] for r in records()[-2:]] == [r["transfer"] for r in results]
                      and [(v / "transfers" / r["transfer"] / "bytes").read_bytes() for r in results] == [b"a", b"b"],
                      "two submissions wait on host flock; release serializes both bytes and receipts")
                (v / "registry/task.json").write_text(json.dumps(dict(record, generation=2)))
                before = set((v / "transfers").iterdir())
                refused = ask(req("submit", 1), body="c"); status = ask(req())
                check(not refused["ok"] and refused["reason"] == "retired generation cannot mutate"
                      and status["ok"] and set((v / "transfers").iterdir()) == before,
                      "retired generation mutation refuses; retired status still reads")
                refused = ask(dict(req(), generation=2))
                check(not refused["ok"] and refused["reason"] == "request names another generation"
                      and ask(req())["ok"], "endpoint generation must match request; registered generation reads")
                projection = json.loads((v / "control/task-1/view/status.json").read_text())
                check(len(projection) == 32 and projection == records()[-32:] and len(records()) > 32,
                      "projection bounded to 32; full accepted and refused history retained on host")
                # THE QUERY QUEUE IS NOT ON THE REQUEST PATH. cc-msg holds ~/.cc/queries/.lock across a
                # Slack post and a tmux inject for a whole drain tick. A refusal that waited for it used
                # to wait holding V/state/<task> — the lock every later request and every host launch
                # takes — and the endpoint answered nothing until Slack came back.
                edited = json.dumps(dict(record, generation=2, branch="refs/heads/elsewhere"))
                (v / "registry/task.json").write_text(edited)
                spool = qsp.read_bytes()
                blocked = (h / ".cc/queries/.lock").open("a")
                task_lock = os.open(v / "state/task", os.O_RDONLY | os.O_DIRECTORY)
                try:
                    fcntl.flock(blocked, fcntl.LOCK_EX)
                    p.stdin.write(m.encoded({"parallel": [dict(request=req())]})); p.stdin.flush()
                    m.require(line(p) == b"submitted\n", "the queue case did not start")
                    free = False
                    for _ in range(60):
                        try:
                            fcntl.flock(task_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            fcntl.flock(task_lock, fcntl.LOCK_UN)
                            free = True
                            break
                        except OSError:
                            time.sleep(0.01)
                    waited = json.loads(line(p))[0]
                    (v / "registry/task.json").write_text(json.dumps(dict(record, generation=2)))
                    start = time.monotonic()
                    prompt = ask(req())
                    elapsed = time.monotonic() - start
                finally:
                    fcntl.flock(blocked, fcntl.LOCK_UN); blocked.close(); os.close(task_lock)
                check(free and not waited["ok"] and waited["reason"] == "task binding changed"
                      and qsp.read_bytes() == spool and prompt["ok"] and elapsed < m.QUEUE_WAIT,
                      "a refusal waiting on the query lock holds neither the task lock nor the next "
                      "reply, and stays in the host status log", f"free={free} {elapsed:.2f}s {waited}")
                (v / "registry/task.json").write_text(edited)
                queued = ask(req())
                (v / "registry/task.json").write_text(json.dumps(dict(record, generation=2)))
                check(not queued["ok"] and json.loads(qsp.read_bytes()[len(spool):])["reason"]
                      == "task binding changed" and len(records()) > 32,
                      "control: with the query lock free the same refusal enters the queue")
                # IDENTITY IS THE KERNEL'S. A descriptor on the caller pins the process the namespaces
                # below are read from, so no pid it once had can be reused for them. The control is the
                # path a kernel without that socket option leaves: identity is still the peer's, read
                # from credentials alone, and namespaces that are not the registered ones refuse there
                # too. An option this kernel does not have is what its absence looks like here.
                lone = object.__new__(m.Broker)   # the same handle(), with the registration set by hand
                lone.__dict__.update(task="task", generation=1, v=v, home=h, registration=record,
                                     state=v / "state/task", view=v / "control/task-1/view",
                                     peer=["pid:[0]", "mnt:[0]"])
                near, far = socket.socketpair()
                saved, m.PEERPIDFD = m.PEERPIDFD, -1
                try:
                    near.sendall(m.encoded(req())); near.shutdown(socket.SHUT_WR)
                    lone.handle(far)
                    fallback = json.loads(near.recv(65536))
                finally:
                    m.PEERPIDFD = saved; near.close(); far.close()
                check(good["identity"] == "pidfd" and fallback["identity"] == "peercred"
                      and not fallback["ok"] and fallback["reason"] == "caller is outside the registered session",
                      "a descriptor on the caller identifies the session; the older path refuses a "
                      "caller whose namespaces are not the registration", str(fallback))
            finally:
                p.stdin.close(); p.wait(timeout=12)
            check(p.returncode == 0 and not (v / "endpoints/task-1").exists(),
                  "endpoint and its directory removed after launcher exit; connection during launch worked",
                  p.stderr.read().decode())
        source = (m.BIN / "cc-guard").read_text()
        check(all(text.replace("{reason}", "$1") in source for _, text in m.REFUSALS.values()),
              "all five catalogue sentences exactly match guard; quiet classes have no queue")
    print(f"cc-member-broker selfcheck: {passed} passed, {failed} failed")
    return int(bool(failed))
