"""Admission: how many checks run at once, and the limits each runs under (review S8).

SLOTS. K = slots() box-wide slots, each a flock on `<state>/slots/slot.<n>`. K is LANDER_SLOTS as cc-config reads
it (the environment, then ~/.cc/config) when that is a whole number of at least 1; otherwise the host's own: one slot
per CORES_PER_SLOT (2) cores, and no more than MemTotal holds of LANDER_MEM_MAX, the most one check may use (on
2026-10-12 a box of 20 cores and 30 GB ran 3, at load ~9 with PRs and green runs queued for a slot; it now runs 5,
which its memory bounds, and the old box's 6 cores still run 3). Never below 1, and a LANDER_SLOTS above the box's
cores counts as its cores. cc-config is asked again once CONFIG_TTL (60) seconds have passed, so a running lane follows a new
value without a restart; a cc-config that does not answer counts as unset. The backoff below applies to K either
way. The box's load is
mostly not the lander's, so a load average would give one slot nearly always; pressure is the signal instead, and
the pressure the box's own work feels: PSI_DIR is the user manager's cgroup (user@<uid>.service, from /proc/self/cgroup)
when its memory.pressure holds a `some avg10` figure, else /proc/pressure (psi_dir()), and LANDER_PSI_DIR overrides it
with either layout. On 2026-10-24 a tenant capped in its own unit stalled 61% against its own limit and lifted the
system figure to 57 while the box's sessions stalled ~0%, holding every launch; a real shortage still stalls the box's
tasks, and PSI counts a stall in each
cgroup ancestor, so it shows here too. CPU is read from the same cgroup for the same reason: a tenant throttled by its
own quota does not slow the box, one contending for the cores does. That cgroup does not see members, Hive, system
units or SSH sessions, so a shortage of the whole box is read too, by short(): SYS_PSI's (/proc/pressure, or
LANDER_PSI_DIR) memory `full avg10` at or above PSI_FULL (LANDER_PSI_FULL, default 10), or /proc/meminfo's MemAvailable
below MEM_FLOOR (LANDER_MEM_FLOOR, default 2G). `full` counts only while every task stalls at once, so one capped
tenant's own stall stays out of it. An unreadable file counts as calm, the same as PSI_DIR's. When memory `some avg10`
reaches PSI_MEM (default 20) or short() says so, the box is mem_loaded(); when it is, or cpu `some avg10` reaches PSI_CPU
(default 99.5 — this box idles near 98, so only a saturated one counts), the box is loaded(). It is overloaded() when it is
loaded() or its 1-minute load average reaches LANDER_LOAD_FACTOR (default 2) times its cores. While overloaded by cpu
PSI or the load average only slots 1-2 admit; under memory pressure only slot 1, because parallel checks have run the
box out of memory. Never 0: a check always gets to run, only later. An EXPRESS run (the lane's Δ rerun of a
mergeable job's short check; each lane runs at most lane.EXPRESS_SLOTS of them at once, so the box runs that many per
lane, and none while mem_loaded()) takes no slot and no ticket. A diagnostic rerun takes every
slot at once (alone=True), so it runs by itself; it takes them in order and never past a busy one, because one
lane now runs several checks at once and two alone runs each holding a slot would wait on each other forever.
SETTLE (dispatch, 10-24/25: under another user's load the box's checks ran slow, five alone reruns queued, the
oldest 92 min, and main stayed red ~6 h behind its fix). An alone wait given settle= (run.py: the largest cap in the
check's manifest, the longest any of its checks holding a slot may run; none for a security check) that still
lacks a slot by then lets go of what it holds and waits for one slot as load admits, in its place in the queue;
run.py takes a loaded red from such a run for no answer, so load still cannot fake a red, and a green under load
or a red without it stands.
ALONE GATE: K is read per process, so two callers can disagree on it (LANDER_SLOTS raised, or one's cc-config did
not answer) and slots 1..K alone would leave a busy slot past K. So an alone run first takes `<state>/slots/alone`
exclusively, which it gets only once no check holds a slot, and every other check holds it shared beside its slot.

FAIR WAIT (2026-10-01/02: worker green runs sat 2-8 h in the poll loop while a lane re-took slot.1 the moment it
let go). Every wait takes a ticket, a flocked file in `<state>/slots/queue/` named by when it began, and only the
oldest live ticket may take a slot; it drops the ticket once it holds what it wants. So a waiter is served before
anyone who came later, the lane included, and an alone run at the head of the queue gets each slot as its holder
lets go instead of losing it to the next check. Nobody gets more slots than slots_now() allows; the order changes,
not the count. LANES FIRST (planning seat, 2026-10-06: a lane sat 6h45m behind workers' green runs): a landing
lane's ticket is named `+` then 19 digits instead of 20, so it sorts before every worker's and waits only behind
an older lane's; a worker's wait is unchanged otherwise. A ticket whose holder died is unlocked, and the next
waiter removes it, as it does anything in the queue that is not a regular file. A name _ticket would not have given is ignored, never waited on and never said,
so a planted `!hold` that sorts first holds nobody up. A ticket it cannot open or lock for want of a file
descriptor, memory or a lock still counts as live: only a bad entry is removed. A waiter behind another holds no slot,
or an older ticket that needs it would wait forever. A ticket still locked after TICKET_CAP seconds
(LANDER_TICKET_CAP, default 12 h, about twice the longest wait a fair queue should see) is taken for a stopped
waiter and no longer counts, and the waiter that passes it says so. While it waits, slot() writes one line to
stderr (the run's log) saying what it waits for, since when and whose ticket is oldest, then again every WAIT_SAY
seconds (LANDER_WAIT_SAY, default 600). In a cc-green run, which names its status file in LANDER_WAIT_NOTE, the first line said
past WAIT_SAY is also appended there ONCE as `waiting=`, so `cc-green wait` says the run is on slots, not hung, and
what to do about it: such runs sat 2-3 h with only a header in their log five times between 09-29 and 10-01, each read
as hung. The landing lane sets no note. A cc-green run also names a per-repo file in LANDER_WAIT_LOG (and its row in
LANDER_WAIT_ROW), and every slot it takes appends `start end row who secs` there once held, the wait cc-i2m counts
as the green stage: the run's own log is one per worktree and the next run overwrites it.

PROVE HOLD (perms, 10-13: promotes stopped at lander-self's PROVE_CAP because the lane's queued checks took every
slot from the proof's sweep). While `lander-self promote` or `prove` proves a release, it holds a lane-named ticket
of its own, named to sort before every lane ticket less than an hour old, so every waiter after it, the lane's
included, waits behind it: the lane admits no new box check, checks already holding a slot finish, and free() is 0,
so the lane sends what it can to the runners. An express run takes no slot, so the hold does not stop it. The
sweep that lander-self starts names that ticket in LANDER_PROVE_HOLD, and to its _ahead() only the tickets older
than the hold count, so it waits behind those and nothing else. A ticket is a flock: when lander-self ends, by its
own release or by a crash, the next waiter finds it dead and removes it, as any other. lander-self does not hold
the lane for a release whose admission does not read LANDER_PROVE_HOLD, because that release's sweep would wait
behind the hold until the cap.

FIRST CLAIM (brief, 10-13: "give main health's checks and a main-red fix's checks first claim on a free slot, ahead of
ordinary PR checks, so health can't starve"). slot(first=True) takes a lane-style ticket backdated FIRST_BACK seconds,
so it goes ahead of every lane or worker ticket younger than FIRST_BACK and behind a PROVE HOLD, which lander-self
names up to its HOLD_BACK (3600 s) back: FIRST_BACK stays below that. Its callers are tick.make_check (the tip run's and
main health's checks) and the lane's checks of a job whose plan holds a check main's record holds red. It is still a
TICKET, so TICKET_CAP and a dead holder treat it as any other.

HIGH LOAD (2026-09-28: load 31-80 on 12 cores and 12 GB swapped, checks went from under 5 min to 11-17). overloaded() is
the one signal for "the box is overloaded": the lander serializes on it and gives its one run priority (below), and
`cc-room` queues new `--go` workers on the same call until it clears, so the landing queue keeps moving while the
load that is already there drains. Nothing is stopped or paused; only starts wait.

LAPTOP. While the box is overloaded(), or free() finds no slot a check could take now, every check that may leave it
goes to the runners (run.spill and run.choose_where; owner 2026-10-12, which turned round 2026-09-29's laptop-first
now the box has room to spare). The lane also sends a check out when it has no box place for it (its width() is
full, or the job already holds its one box check), so no check waits for a box slot while a runner has room. The lane
keeps up to LAPTOP_SLOTS (LANDER_LAPTOP_SLOTS, default 5) of them in flight beside the box's slots, which they do not
take; a laptop that answers busy sends the check back to the box.

SCOPES. Each run goes into a transient `systemd-run --user --scope` on slice `lander.slice` (no unit file) with a low
CPUWeight, a MemoryMax and no swap (a box already deep in swap is what this guards against), so the kernel,
not the lander, stops a check that eats the box — and one killed there is unrunnable, never red. Hermetic and
static checks also run under `nice -n 10`; host, box and timing checks keep today's priority. A run that starts while
the box is overloaded() drops that nice and runs under `ionice -c2 -n0` (the top best-effort I/O level, which needs no
privilege): it is the only lander run then, and it should finish rather than yield. The scope's CPUWeight ranks lander
runs among themselves only; lander.slice sits beside the sessions' scopes and gets its own share of the CPU either
way. With no user systemd bus (or LANDER_SCOPE=0) the scope is dropped and the run says so in its runner string,
never silently.

TIMING checks race the clock: they run before the merge only while loaded() is false (PSI only, not the load average); otherwise the run is
unrunnable ("box busy") and the lane tries again.
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid

from lander import types as T

SLOTS: int | None = None   # a fixed K for a caller that sets it (cc-replay --slots); None: slots() works it out
CORES_PER_SLOT = 2
CONFIG_TTL = 60.0
MEMINFO = "/proc/meminfo"
PSI_MEM = float(os.environ.get("LANDER_PSI_MEM", "20"))
PSI_CPU = float(os.environ.get("LANDER_PSI_CPU", "99.5"))
PSI_FULL = float(os.environ.get("LANDER_PSI_FULL", "10"))
LAPTOP_SLOTS = max(0, int(os.environ.get("LANDER_LAPTOP_SLOTS", "5") or 0))
MEM_MAX = os.environ.get("LANDER_MEM_MAX", "6G")
SWAP_MAX = os.environ.get("LANDER_SWAP_MAX", "0")
MEM_FLOOR = os.environ.get("LANDER_MEM_FLOOR", "2G")
CPU_WEIGHT = "20"
LOAD_FACTOR = float(os.environ.get("LANDER_LOAD_FACTOR", "2") or 2)


def box_cgroup(own: str = "/proc/self/cgroup", sysfs: str = "/sys/fs/cgroup") -> str | None:
    """The user manager's cgroup the box's work runs under (user@<uid>.service), when its memory.pressure reads and
    holds a `some avg10=` figure."""
    try:
        with open(own) as f:
            m = re.search(r"^0::(/.*?/user@\d+\.service)(/|$)", f.read(), re.M)
        d = sysfs + m.group(1)
        with open(os.path.join(d, "memory.pressure")) as f:
            float(re.search(r"^some .*\bavg10=(\S+)", f.read(), re.M).group(1))
        return d
    except (OSError, AttributeError, ValueError):
        return None


def psi_dir(override: str | None = None, own: str = "/proc/self/cgroup", sysfs: str = "/sys/fs/cgroup") -> str:
    """LANDER_PSI_DIR when set, else box_cgroup(), else /proc/pressure."""
    return override or box_cgroup(own, sysfs) or "/proc/pressure"


PSI_DIR = psi_dir(os.environ.get("LANDER_PSI_DIR"))
SYS_PSI = os.environ.get("LANDER_PSI_DIR") or "/proc/pressure"
LOADAVG = os.environ.get("LANDER_LOADAVG") or "/proc/loadavg"
WAIT_SAY = float(os.environ.get("LANDER_WAIT_SAY", "600") or 600)
TICKET_CAP = float(os.environ.get("LANDER_TICKET_CAP", "43200") or 43200)
FIRST_BACK = 3000   # seconds a first ticket is backdated (FIRST CLAIM); below lander-self's HOLD_BACK of 3600


def psi(kind: str, root: str = PSI_DIR, which: str = "some") -> float:
    """`<which> avg10` for cpu/memory/io from a cgroup's `<kind>.pressure` or /proc/pressure's `<kind>`, else 0.0."""
    path = os.path.join(root, kind + ".pressure")
    try:
        with open(path if os.path.exists(path) else os.path.join(root, kind)) as f:
            for line in f:
                if line.startswith(which + " "):
                    return float(dict(kv.split("=") for kv in line.split()[1:])["avg10"])
    except (OSError, KeyError, ValueError):
        pass
    return 0.0


def short(sys_psi: str | None = None, meminfo: str | None = None) -> str:
    """"" unless the whole box runs short of memory, else one line saying how."""
    full, avail = psi("memory", sys_psi or SYS_PSI, "full"), _meminfo("MemAvailable:", meminfo)
    if full >= PSI_FULL:
        return f"box-wide memory pressure (PSI full) at {full:.0f}"
    if avail is not None and avail < (_bytes(MEM_FLOOR) or 0):
        return f"box-wide memory short, {avail >> 20} MiB available"
    return ""


def mem_loaded(root: str = PSI_DIR) -> bool:
    return psi("memory", root) >= PSI_MEM or bool(short())


def loaded(root: str = PSI_DIR) -> bool:
    return mem_loaded(root) or psi("cpu", root) >= PSI_CPU


def load1(loadavg: str | None = None) -> float | None:
    """The 1-minute load average, or None when it cannot be read."""
    try:
        with open(loadavg or LOADAVG) as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def overloaded(root: str = PSI_DIR, loadavg: str | None = None) -> str:
    """"" when the box is not overloaded, else one line saying why: loaded(), or the 1-minute load average at or
    above LOAD_FACTOR x cores. An unreadable load average counts as calm."""
    if loaded(root):
        return short() or f"memory or cpu pressure (PSI) at {psi('memory', root):.0f}/{psi('cpu', root):.1f}"
    n, l1 = os.cpu_count() or 1, load1(loadavg)
    if l1 is None:
        return ""
    return f"load {l1:.1f} on {n} cores (at least {LOAD_FACTOR:g}x)" if l1 >= LOAD_FACTOR * n else ""


def _bytes(size: str) -> int | None:
    """A systemd size (`6G`, `512M`, plain bytes) in bytes; None for `infinity`, a percentage or anything else."""
    m = re.fullmatch(r"([0-9]+)([KMGT]?)", (size or "").strip().upper())
    return int(m.group(1)) * 1024 ** ("KMGT".index(m.group(2)) + 1 if m.group(2) else 0) if m else None


def _meminfo(key: str, meminfo: str | None = None) -> int | None:
    """/proc/meminfo's `key` (MemTotal:, MemAvailable:) in bytes, or None when it will not read."""
    with contextlib.suppress(OSError, ValueError, IndexError):
        with open(meminfo or MEMINFO) as f:
            return next((int(line.split()[1]) * 1024 for line in f if line.startswith(key)), None)
    return None


def host_slots(meminfo: str | None = None, cores: int | None = None) -> int:
    """The host's own K: one slot per CORES_PER_SLOT cores, and no more than MemTotal / MEM_MAX. At least 1. A
    MemTotal or MEM_MAX that will not read leaves the cores alone to decide."""
    k = (cores or os.cpu_count() or 1) // CORES_PER_SLOT
    cap, total = _bytes(MEM_MAX), _meminfo("MemTotal:", meminfo)
    if cap and total:
        k = min(k, total // cap)
    return max(1, k)


def config_slots(name: str = "LANDER_SLOTS") -> int | None:
    """`name` (LANDER_SLOTS, or the lane's LANDER_REVIEW_SLOTS) as cc-config reads it, when it is a whole number of at
    least 1 (ASCII digits: '²' is a digit to isdigit()), and no more than the box's cores (leading zeros dropped, and a
    number too long for int(), which refuses past 4300 digits, taken as above them); None when it is unset, not such
    a number, or cc-config did not answer."""
    from lander import jobs as J   # here: jobs imports events, and admission is imported by the runner's every caller
    try:
        p = subprocess.run([f"{J.bin_dir()}/cc-config", "get", name], capture_output=True, text=True,
                           timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    v = p.stdout.strip()
    n = v.lstrip("0")   # int() counts leading zeros toward its 4300 digits, so '0' * 5000 + '7' would raise
    if p.returncode != 0 or not (v.isascii() and v.isdigit()) or not n:
        return None
    cores = os.cpu_count() or 1
    return cores if len(n) > 9 else min(int(n), cores)


_read: tuple = (None, 0.0)   # (K, when): config_slots() spawns cc-config, and slot() asks every poll (2 s)


def slots(now: float | None = None) -> int:
    """K before any backoff: SLOTS when a caller fixed it, else LANDER_SLOTS from cc-config, else host_slots(),
    read again once CONFIG_TTL seconds have passed, so a running lane follows a change without a restart."""
    global _read
    if SLOTS:
        return max(1, SLOTS)
    now = time.monotonic() if now is None else now
    k, at = _read
    if k is None or now - at >= CONFIG_TTL:
        k = config_slots() or host_slots()
        _read = (k, now)
    return k


def slots_now(root: str = PSI_DIR, k: int | None = None, loadavg: str | None = None) -> int:
    k = max(1, slots() if k is None else k)
    if not overloaded(root, loadavg):
        return k
    # cpu PSI or the load average: two still run. Memory pressure: one, because parallel checks have run the box
    # out of memory before
    return 1 if mem_loaded(root) else min(k, 2)


TICKET = re.compile(r"[0-9+][0-9]{19}-[0-9]+-[0-9a-f]{8}")   # _ticket's names: time_ns-pid-rand, a lane's `+`-led
BAD = (errno.ELOOP, errno.ENXIO, errno.EACCES, errno.EPERM)   # a symlink, a socket, an unreadable file: not a ticket


def _ticket(qdir: str, lane: bool = False, first: bool = False):
    """Join the queue: a file named by when the wait began, flocked for as long as this process waits. It is locked
    before it is given its listed name, so nobody sees it unlocked and takes it for a dead one. A lane's name starts
    `+` (LANES FIRST), which sorts before a digit and still reads as the same number. first: a lane's name, its time
    FIRST_BACK seconds back (FIRST CLAIM)."""
    born = time.time_ns() - (FIRST_BACK * 10**9 if first else 0)
    name = f"{'+' if lane or first else '0'}{born:019d}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    tmp = os.path.join(qdir, f".new-{name}")
    f = open(tmp, "a")
    fcntl.flock(f, fcntl.LOCK_EX)
    os.rename(tmp, os.path.join(qdir, name))
    return name, f


_noted = False   # one waiting= line per process, however many of its checks wait


def _note(line: str) -> None:
    """Append ONE `waiting=` line to the status file LANDER_WAIT_NOTE names (cc-green's run); nothing without one."""
    global _noted
    p = os.environ.get("LANDER_WAIT_NOTE")
    if _noted or not p:
        return
    _noted = True
    line = re.sub(r"[\x00-\x1f\x7f]", " ", line)[:300]   # a check name from the tree's TOML must not plant an exit= line
    with contextlib.suppress(OSError, ValueError):   # ValueError: a NUL in the path
        with open(p, "a") as f:
            f.write(f"waiting={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {line} — a wait for a free slot, "
                    "not a hang. Way forward: keep waiting, or `cc-green stop` and hand over without this run; the "
                    "landing runs the same checks in its own place in the queue.\n")


def _waited(began: float, who: str) -> None:
    """Append `start end row who secs` (tab-separated, UTC stamps) to the file LANDER_WAIT_LOG names, once a slot is
    held: the durable record of a cc-green run's slot wait (row: LANDER_WAIT_ROW), which its one log per worktree
    loses on the next run. cc-i2m reads it as the green stage. Nothing without the variable or outside ~/.cc; never raises."""
    p = os.environ.get("LANDER_WAIT_LOG")
    if not p:
        return
    end = time.time()
    clean = lambda v: re.sub(r"[\x00-\x1f\x7f]", " ", v)[:200]   # one record is one line, whatever a name holds
    stamp = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    with contextlib.suppress(OSError, ValueError):
        root = os.path.realpath(os.path.expanduser("~/.cc")) + os.sep
        if not os.path.realpath(p).startswith(root):          # a misset variable never appends into a file elsewhere
            return
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # O_NONBLOCK: a FIFO with no reader fails at once (ENXIO) instead of blocking with the slot held
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW
        with os.fdopen(os.open(p, flags, 0o600), "a") as f:
            f.write(f"{stamp(began)}\t{stamp(end)}\t{clean(os.environ.get('LANDER_WAIT_ROW') or '-')}\t"
                    f"{clean(who or '-')}\t{int(end - began)}\n")


def _drop(p: str) -> None:
    with contextlib.suppress(OSError):
        os.unlink(p)
    with contextlib.suppress(OSError):
        os.rmdir(p)


def _ahead(qdir: str, mine: str, cap: float | None = None) -> tuple:
    """-> (n, oldest, stale): how many live tickets are older than mine, the oldest of those, and the live ones past
    cap seconds, which no longer count. A dead ticket (its flock free) is removed on the way, and so is a ticket-named
    entry that is not a regular file, or a `.new-` ticket a crash left before its rename. A name _ticket would not
    have given is skipped."""
    cap = TICKET_CAP if cap is None else cap
    hold = os.environ.get("LANDER_PROVE_HOLD", "")   # PROVE HOLD: the proof's sweep counts only what is older
    stop = min(mine, hold) if TICKET.fullmatch(hold) else mine
    n, oldest, stale = 0, None, []
    for name in sorted(os.listdir(qdir)):
        if name >= stop:
            break
        born = _born(name)
        if born is None:   # not a ticket's name: never waited on, never said
            continue
        p = os.path.join(qdir, name)
        live = False
        try:   # never follow a link, never block on a FIFO
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            continue
        except OSError as e:
            if e.errno in BAD:
                _drop(p)
                continue
            fd, live = None, True   # out of fds or memory: the ticket may well be live, so it keeps its place
        try:
            if fd is not None:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode):
                    _drop(p)
                    continue
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:   # locked: a live waiter ahead of this one
                    live = True
                except OSError:   # ENOLCK and the like say nothing about the ticket, so it keeps its place
                    live = True
            if live:
                if name.startswith("."):
                    continue
                if time.time() - born > cap:
                    stale.append(name)
                    continue
                n += 1
                oldest = oldest or name
                continue
            if not name.startswith(".") or time.time() - st.st_mtime > 60:
                _drop(p)   # its waiter is gone
        finally:
            if fd is not None:
                os.close(fd)
    return n, oldest, stale


def _born(name: str) -> float | None:
    """When a ticket's wait began, from its name (time_ns-pid-rand, maybe `.new-` before it), or None when the name
    is not one _ticket gives."""
    base = name.removeprefix(".new-")
    return int(base.split("-")[0]) / 1e9 if TICKET.fullmatch(base) else None


def _whose(name: str) -> str:
    """'pid P, A min' for the wait line; name is one _ahead passed, so a ticket's."""
    return f"pid {name.split('-')[1]}, {(time.time() - (_born(name) or time.time())) / 60:.0f} min"


@contextlib.contextmanager
def slot(state: str, alone: bool = False, poll: float = 2.0, deadline: float | None = None, psi_root: str = PSI_DIR,
         k: int | None = None, loadavg: str | None = None, who: str = "", say=None, lane: bool = False,
         first: bool = False, settle: float | None = None):
    """Hold one slot (or all of them, alone=True) for the with-block; yields the slot numbers held. Waits its turn
    in the queue (FAIR WAIT), polling, until one admits; deadline (seconds) raises TimeoutError instead of waiting
    on. say(line) is told while it waits; stderr by default. lane=True: a landing lane's wait (LANES FIRST).
    first=True: main health's or a main-red fix's check (FIRST CLAIM). settle (seconds): an alone wait that has not
    got every slot by then waits for one slot instead, in the same place in the queue (SETTLE)."""
    d = os.path.join(state, "slots")
    q = os.path.join(d, "queue")
    os.makedirs(q, exist_ok=True)
    total = max(1, slots() if k is None else k)
    say = say or (lambda line: print(line, file=sys.stderr, flush=True))
    t0, said, since, began = time.monotonic(), None, time.strftime("%H:%MZ", time.gmtime()), time.time()
    held: list = []
    gate = None   # the ALONE GATE: exclusive for an alone run, shared beside another's slot
    told: set = set()
    mine, tf = _ticket(q, lane, first)
    try:
        while True:
            if alone and settle is not None and time.monotonic() - t0 >= settle:
                alone = False   # SETTLE: what it holds goes back, and it takes one slot as load admits
                for _, f in held:
                    f.close()
                held = []
                if gate is not None:
                    gate.close()
                    gate = None
                with contextlib.suppress(OSError, ValueError):
                    say(f"lander: {who or 'a check'} had no run alone in {settle / 60:.0f} min, so it runs beside "
                        f"others as load admits")
            want = range(1, total + 1) if alone else range(1, slots_now(psi_root, total, loadavg) + 1)
            ahead, oldest, stale = _ahead(q, mine)
            for name in set(stale) - told:
                told.add(name)
                line = (f"lander: {who or 'a check'} no longer waits on ticket {name} ({_whose(name)}): "
                        f"older than {TICKET_CAP / 3600:g} h, so its waiter is taken for stuck")
                with contextlib.suppress(OSError, ValueError):   # only say(): a gone or closed stderr
                    say(line)
            if alone and not ahead and gate is None:
                gate = _gate(d, fcntl.LOCK_EX)   # none while any check holds a slot, whatever K it counted
            for n in want if not ahead and (gate or not alone) else ():   # only the oldest waiter takes a slot
                if n in [h for h, _ in held]:
                    continue
                f = open(os.path.join(d, f"slot.{n}"), "a")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    f.close()
                    if alone:   # in order, never past a busy one: two alone runs holding a slot each would wait forever
                        break
                    continue
                if not alone:
                    gate = _gate(d, fcntl.LOCK_SH)
                    if gate is None:   # an alone run holds the box
                        f.close()
                        break
                held.append((n, f))
                if not alone:
                    break
            if held and (not alone or len(held) == total):
                break
            if deadline is not None and time.monotonic() - t0 > deadline:
                raise TimeoutError(f"no lander slot free after {deadline:.0f}s")
            if said is None or time.monotonic() - said >= WAIT_SAY:
                said = time.monotonic()
                what = (f"all {total} slots (alone)" if alone
                        else f"one of slots 1-{len(want)} (load admits {len(want)} of {total})")
                line = (f"lander: {who or 'a check'} waiting since {since} ({(said - t0) / 60:.0f} min) for {what}; "
                        f"{ahead} waiting ahead of it" + (f", the oldest {_whose(oldest)}" if oldest else "")
                        + (f", holding {[h for h, _ in held]}" if held else ""))
                with contextlib.suppress(OSError, ValueError):   # only say(): a gone or closed stderr
                    say(line)
                if said - t0 >= WAIT_SAY:   # past the bound: the run's status gets its one line
                    _note(line)
            if not alone or ahead:   # behind someone: hold nothing, or an older ticket needing our slot waits forever
                for _, f in held:
                    f.close()
                held = []
                if gate is not None:
                    gate.close()
                    gate = None
            time.sleep(poll)
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(q, mine))
        tf.close()
        tf = None
        _waited(began, who)
        yield [n for n, _ in held]
    finally:
        if tf is not None:
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(q, mine))
            tf.close()
        for _, f in held:
            f.close()
        if gate is not None:
            gate.close()


def _gate(d: str, how: int):
    """The ALONE GATE flocked how (LOCK_EX or LOCK_SH) without waiting: the open file, or None when it is held the
    other way."""
    f = open(os.path.join(d, "alone"), "a")
    try:
        fcntl.flock(f, how | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def free(state: str, psi_root: str = PSI_DIR, k: int | None = None, loadavg: str | None = None) -> int:
    """How many of slots_now()'s slots a check would take now without waiting: each one nobody holds, and none while
    a ticket waits in the queue (it goes first, FAIR WAIT) or an alone run holds the gate. It only looks: a slot is
    flocked for the instant it takes to see it is free. run.spill() asks it, so a check that would wait here goes to
    a runner instead."""
    d = os.path.join(state, "slots")
    if not os.path.isdir(d):
        return slots_now(psi_root, k, loadavg)
    q = os.path.join(d, "queue")
    if os.path.isdir(q) and _ahead(q, "~")[0]:   # "~" sorts after every ticket's name, so each live one counts
        return 0
    gate = _gate(d, fcntl.LOCK_SH)
    if gate is None:
        return 0
    n = 0
    try:
        for i in range(1, slots_now(psi_root, k, loadavg) + 1):
            with open(os.path.join(d, f"slot.{i}"), "a") as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    continue
                n += 1
    finally:
        gate.close()
    return n


def scope_available() -> bool:
    if os.environ.get("LANDER_SCOPE", "1") == "0" or not shutil.which("systemd-run"):
        return False
    rt = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.exists(os.path.join(rt, "bus"))


def wrap(check: T.Check, argv: list, label: str = "", busy: bool = False) -> tuple:
    """-> (argv, how): argv inside its scope and priority, and a word for Result.runner ("scope" or "noscope").
    busy: the box was overloaded() when the slot was taken, so this is the one run going and it is not niced down."""
    if busy:
        pre = ["ionice", "-c2", "-n0"] if shutil.which("ionice") else []
    else:
        pre = ["nice", "-n", "10"] if check.klass in (T.HERMETIC, T.STATIC) else []
    if not scope_available():
        return pre + argv, "noscope"
    unit = f"lander-{''.join(c if c.isalnum() else '-' for c in (label or check.name))[:60]}-{uuid.uuid4().hex[:8]}"
    return (["systemd-run", "--user", "--scope", "--quiet", "--collect", "--slice=lander.slice", f"--unit={unit}",
             "-p", f"CPUWeight={CPU_WEIGHT}", "-p", f"MemoryMax={MEM_MAX}", "-p", f"MemorySwapMax={SWAP_MAX}", "--"]
            + pre + argv), "scope"
