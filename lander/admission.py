"""Admission: how many checks run at once, and the limits each runs under (review S8).

SLOTS. K = slots() box-wide slots, each a flock on `<state>/slots/slot.<n>`. K is LANDER_SLOTS as cc-config reads
it (the environment, then ~/.cc/config) when that is a whole number of at least 1; otherwise the host's own: one slot
per CORES_PER_SLOT (2) cores, and no more than MemTotal holds of LANDER_MEM_MAX, the most one check may use (on
2026-10-12 a box of 20 cores and 30 GB ran 3, at load ~9 with PRs and green runs queued for a slot; it now runs 5,
which its memory bounds, and the old box's 6 cores still run 3). Never below 1, and a LANDER_SLOTS above the box's
cores counts as its cores. MEMORY: every check's scope shares lander.slice (SCOPES), so a check also waits until
the slice has room for it: the memory its running checks hold (memory.stat `anon`, so page cache the kernel can drop
does not count) or, when that is more, what they reserved, plus this check's own need, within the slice's MemoryHigh.
A check's need is the peak a green run of it reached, or half the need kept before when that is more, so an old peak
fades once runs stop reaching it (run.py records the most `anon` its scope cgroup's memory.stat showed while it ran,
since memory.peak counts the page cache of every file it read, or wait4's ru_maxrss, the largest process alone, when
that is more, in `<state>/slots/peak/<repo>/<check>`; a red or capped run may have died before its peak, so it records
nothing), never below a quarter of CHECK_MEM, and CHECK_MEM (LANDER_CHECK_MEM, default 1536M, about a
heavy check's peak) until it has one, or while one is being written; the holder of a slot writes
its need in the slot's file, which is what it reserved. A slice whose memory.stat does not read counts reservations
alone, so with no peak recorded the slice holds MemoryHigh / CHECK_MEM checks. A slice with no MemoryHigh, or a
systemctl that does not answer, sets no memory bound, and a check always runs when no slot is held. On 2026-10-25
the tower's K of 8, LANDER_SLOTS in its ~/.cc/config, let seven ~1.4G dispatch checks run together, and they
thrashed the slice's 6G for 33 min and dragged the tower into memory pressure; a fixed 1536M for every check then held
fast gates to the same 4 slots. cc-config is asked again once CONFIG_TTL (60) seconds have passed, so a running lane follows a new
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
tenant's own stall stays out of it. An unreadable file counts as calm, the same as PSI_DIR's, and says so once per
process on stderr and in queue.log (_unread), since a dead signal otherwise looks like a calm box, and a lane started
detached sends its stderr to /dev/null. A LANDER_MEM_FLOOR of `infinity` sets no floor. When memory `some avg10`
reaches PSI_MEM (default 20) or short() says so, the box is mem_loaded(); when it is, or cpu `some avg10` reaches PSI_CPU
(default 99.5 — this box idles near 98, so only a saturated one counts), the box is loaded(). It is overloaded() when it is
loaded() or its 1-minute load average reaches LANDER_LOAD_FACTOR (default 2) times its cores. While overloaded by cpu
PSI or the load average only slots 1-2 admit; under memory pressure only slot 1, because parallel checks have run the
box out of memory. Never 0: a check always gets to run, only later. An EXPRESS run (the lane's Δ rerun of a
mergeable job's short check; each lane runs at most lane.EXPRESS_SLOTS of them at once, so the box runs that many per
lane, and none while mem_loaded()) takes no slot and no ticket, so it reserves no memory either, though what it
holds counts in the slice's `anon` (MEMORY). A diagnostic rerun takes every
slot at once (alone=True), so it runs by itself; it takes them in order and never past a busy one, because one
lane now runs several checks at once and two alone runs each holding a slot would wait on each other forever.
SETTLE (dispatch, 10-24/25: under another user's load the box's checks ran slow, five alone reruns queued, the
oldest 92 min, and main stayed red ~6 h behind its fix). An alone wait given settle= (run.py: the largest cap in the
check's manifest, the longest any of its checks holding a slot may run; a security check too, though run.py then takes no answer from it, so a loaded run cannot pass one) that still
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
an older lane's. AGED (convert-refuses-a-former-member-repo's green run, 10-26/27: the dispatch lane's heavy checks
ran back to back and the worker waited over 12 h while the count ahead of it grew): a worker's wait still without a
slot after AGED seconds (LANDER_WORKER_AGED, default 2 h, never under AGED_MIN's 10 min whatever a caller sets)
takes a lane's ticket named when its wait began, so from then on it goes ahead of every lane ticket younger than it,
and waits as a lane that came when it did would. It never goes ahead of a put-first job's: it is named FRONT_GAP
behind the newest in their leading run, which leaves the room behind them for later ones, and the same behind a
live PROVE HOLD's, again whenever a hold is taken behind it later (perms and Opus' reads of #1996). A lane
waits behind a worker only once that worker has waited AGED, so a pile of fresh worker runs still never holds it up,
and a worker waits at most AGED plus what was queued as a lane before it came. 2 h is a third of the ~6 h longest
wait a fair queue sees (TICKET_CAP is twice that), so it never pushes a starved worker past the cap.
A ticket whose holder died is unlocked, and the next
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
PASS (a2920, 10-26: dispatch's check in slot 1 reserved 3.4G and its next, at the head, wanted 3.4G more of the
slice's 6G, so every later ticket waited behind it over an hour with 7 slots free). A waiter that would take a slot
but for room() writes the need it waits on into its ticket. A later waiter, not alone, passes such a ticket while
the slots held by checks that passed nobody, reserving R, keep it out (R plus its need is past MemoryHigh), and takes
a slot when it fits itself; it then holds a flock on the slot's sibling `slot.N.passed`, and the slot file stays a
bare need, which older releases' cc-green runs still read. Once those holders finish nobody new passes, so the head
waits at most for the passers already running. A head that needs more than the whole slice is passed too while a
non-passer holds, and runs once the slots are empty, as room() lets it.

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
main health's checks) and the lane's checks of a job put first or whose plan holds a check main's record holds red.
It is still a TICKET, so TICKET_CAP and a dead holder treat it as any other. The lane passes first as a callable, asked
again each poll: a check already waiting when its job is put first takes a first ticket then, in place of its own
(dispatch #2026, 10-25: put first while its check waited, it waited 5 h more), named the older of FIRST_BACK back and
its own wait's start. A put-first job's says FRONT: its ticket is named before every live one too, so it goes
ahead of every waiter however long they have waited (FIRST_BACK alone did nothing for one past it), and never before
a live PROVE HOLD's ticket (_hold: its pid is a lander-self's). Several put first keep the order they were put first in:
the first goes FRONT_GAP before the oldest waiter, and each later one one ns behind the newest FRONT ticket, which its
name marks (its rand starts FRONT_MARK, every other's `0`; an older cc-green's random rand starts so 1 time in 65536).
Only the leading run of FRONT tickets counts, so a waiter's never does; a stale ticket neither joins nor ends the run.
A later first ticket is younger than a FRONT one.
STOP: slot(stop=) is asked each poll too, and a waiter it says is stopped leaves the queue with TimeoutError, as one
past its deadline does: the lane stops a check whose job moved on. run asks it to keep the lane's beat too, so a live
wait is never taken for a check that has not started (lane NOSTART).

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
ORPHANS. A scope is its own cgroup, outside the unit of the lane or cc-green run that started it, so that process's
death (a restart, a kill) would leave the check running, past its cap, which only its starter enforced, and its
memory counted against the slice in room(). wrap() names the scope with its starter's pid, and room() first kills
(cgroup.kill) every scope whose starter is gone (reap()), once, saying so in queue.log. A live starter ends a check
that holds its slot while idle itself (run.execute, IDLE).

TIMING checks race the clock: they run before the merge only while loaded() is false (PSI only, not the load average); otherwise the run is
unrunnable ("box busy") and the lane tries again.
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid

from lander import events as E
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
CHECK_MEM = os.environ.get("LANDER_CHECK_MEM", "1536M")   # a check's need until its own peak is recorded
SLICE_HIGH: str | None = None   # lander.slice's MemoryHigh for a test to fix; None: systemctl says it
SLICE_DIR = os.environ.get("LANDER_SLICE_DIR") or \
    f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/lander.slice"
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
FRONT = "front"     # slot(first=) for a put-first job's check: ahead of every waiter, behind a PROVE HOLD (FIRST CLAIM)
FRONT_GAP = 10**6   # ns the first FRONT ticket goes before the oldest waiter: room for later ones behind it
FRONT_MARK = "ffff"   # a FRONT ticket's rand starts with it: an older cc-green's random one does 1 time in 65536
AGED_MIN = 600   # seconds: no caller's LANDER_WORKER_AGED makes a worker's wait a lane's sooner (AGED)


def _aged(v: str | None) -> float:
    """AGED's seconds from LANDER_WORKER_AGED: 7200 unset or not a number, never under AGED_MIN."""
    try:
        n = float(v or 7200)
    except ValueError:
        return 7200.0
    return max(float(AGED_MIN), n) if math.isfinite(n) else 7200.0


AGED = _aged(os.environ.get("LANDER_WORKER_AGED"))   # seconds before a worker waits as a lane (AGED)


def psi(kind: str, root: str = PSI_DIR, which: str = "some") -> float:
    """`<which> avg10` for cpu/memory/io from a cgroup's `<kind>.pressure` or /proc/pressure's `<kind>`, else 0.0."""
    path = os.path.join(root, kind + ".pressure")
    path = path if os.path.exists(path) else os.path.join(root, kind)
    try:
        with open(path) as f:
            for line in f:
                if line.startswith(which + " "):
                    return float(dict(kv.split("=") for kv in line.split()[1:])["avg10"])
    except (OSError, KeyError, ValueError):
        pass
    _unread(f"{path} `{which} avg10`")
    return 0.0


_dead: set = set()   # the signals _unread() has already told of in this process


def _unread(what: str, so: str = "it counts as calm") -> None:
    """Say once per process, on stderr (the lander's log) and in queue.log, that a signal would not read or parse and
    so what it counts as: a dead signal looks like a calm box, so a broken read must leave a trace, and a lane started
    detached has its stderr on /dev/null."""
    if what in _dead:
        return
    _dead.add(what)
    with contextlib.suppress(OSError, ValueError):   # a gone or closed stderr
        print(f"lander: {what} does not read, so {so}", file=sys.stderr, flush=True)
    E.line(f"unread lander {what} does not read, so {so}")


def short(sys_psi: str | None = None, meminfo: str | None = None) -> str:
    """"" unless the whole box runs short of memory, else one line saying how."""
    full, avail = psi("memory", sys_psi or SYS_PSI, "full"), _meminfo("MemAvailable:", meminfo)
    if full >= PSI_FULL:
        return f"box-wide memory pressure (PSI full) at {full:.0f}"
    floor = _bytes(MEM_FLOOR)
    if floor is None and MEM_FLOOR.strip().lower() != "infinity":
        _unread(f"LANDER_MEM_FLOOR={MEM_FLOOR!r}")
    if avail is not None and avail < (floor or 0):
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
            n = next((int(line.split()[1]) * 1024 for line in f if line.startswith(key)), None)
        if n is not None:
            return n
    _unread(f"{meminfo or MEMINFO} {key}")
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


_high: tuple = ("", None)   # (MemoryHigh as systemctl said it, when): asked once per CONFIG_TTL, as cc-config is


def slice_high(now: float | None = None) -> int | None:
    """lander.slice's MemoryHigh in bytes; None when it has none (`infinity`) or does not read, which _unread says."""
    global _high
    now = time.monotonic() if now is None else now
    high, at = _high
    if SLICE_HIGH is None and (at is None or now - at >= CONFIG_TTL):
        try:
            high = subprocess.run(["systemctl", "--user", "show", "-p", "MemoryHigh", "--value", "lander.slice"],
                                  capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            high = ""
        _high = (high, now)
    high = high if SLICE_HIGH is None else SLICE_HIGH
    n = _bytes(high)
    if n is None and high.strip().lower() != "infinity":
        _unread(f"lander.slice's MemoryHigh ({high!r})", "no memory bound holds a check")
    return n


def slice_used() -> int | None:
    """The memory lander.slice's checks hold now, memory.stat's `anon` (page cache the kernel can drop does not
    count); 0 while the slice is not running; None when it does not read, which _unread says."""
    if not os.path.isdir(SLICE_DIR):
        return 0
    path = os.path.join(SLICE_DIR, "memory.stat")
    try:
        return anon(path)
    except (OSError, ValueError, IndexError, StopIteration):
        _unread(f"{path} anon", "only what running checks reserved counts")
        return None


_reaped: set = set()   # reap(): scopes killed, which stay until systemd collects them


def reap() -> list:
    """Kill each scope in lander.slice whose run outlived the process that started it (ORPHANS), named in its unit
    by wrap() as `-p<pid>-`; -> the scopes killed. A scope named before that, or whose pid now names another
    process, is left alone, and one killed before is not killed or said again."""
    killed = []
    with contextlib.suppress(OSError):
        for name in os.listdir(SLICE_DIR):
            m = re.fullmatch(r"lander-.*-p([0-9]+)-[0-9a-f]{8}\.scope", name)
            if not m or name in _reaped or os.path.exists(f"/proc/{m.group(1)}"):
                continue
            with contextlib.suppress(OSError):
                with open(os.path.join(SLICE_DIR, name, "cgroup.kill"), "w") as f:
                    f.write("1")
                _reaped.add(name)
                killed.append(name)
                E.line(f"orphan lander killed {name}: the process that started it (pid {m.group(1)}) is gone")
    return killed


def anon(stat: str) -> int:
    """The `anon` bytes a cgroup's memory.stat file says it holds; raises when that does not read."""
    with open(stat) as f:
        return next(int(line.split()[1]) for line in f if line.startswith("anon "))


def _peak_path(state: str, repo: str, name: str) -> str:
    safe = lambda v: re.sub(r"[^A-Za-z0-9._-]", "-", v)[:120]
    return os.path.join(state, "slots", "peak", safe(os.path.basename(os.path.realpath(repo))), safe(name))


def _flock(f, how: int, wait: float = 1.0) -> None:
    """flock `f` without blocking for good: LOCK_NB again every 10 ms for `wait` seconds, then BlockingIOError."""
    end = time.monotonic() + wait
    while True:
        try:
            return fcntl.flock(f, how | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.monotonic() >= end:
                raise
            time.sleep(0.01)


def peak(state: str, repo: str, name: str) -> int | None:
    """The need record() kept for `repo`'s check `name`, in bytes, and never below a quarter of CHECK_MEM, so a few
    small runs cannot shrink a need a burst then runs far past; None, which counts as CHECK_MEM, when none reads or
    record() holds the lock, so a stuck writer never holds an admission up."""
    with contextlib.suppress(OSError, ValueError):
        with open(_peak_path(state, repo, name)) as f:
            _flock(f, fcntl.LOCK_SH)
            n = int(f.read())
        return max(n, (_bytes(CHECK_MEM) or 0) // 4) if n > 0 else None
    return None


def record(state: str, repo: str, name: str, n: int) -> None:
    """Keep `n` bytes, or half the peak kept before when that is more, as `repo`'s check `name`'s need next time
    (MEMORY): the largest peak stands while runs keep reaching it, and one no run reaches again halves at each run. The
    caller records only a green run's, and nothing comes of a peak that did not measure. Two runs finishing together
    take turns on the file's lock, so neither loses the other's peak."""
    if n <= 0:
        return
    p = _peak_path(state, repo, name)
    with contextlib.suppress(OSError):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            try:
                n = max(n, int(f.read()) // 2)
            except ValueError:
                pass
            f.seek(0)
            f.truncate()
            f.write(str(n))


def scope_stat(argv: list) -> str:
    """The memory.stat file of the scope wrap() put argv in; "" for a run with no scope."""
    unit = next((a[len("--unit="):] for a in argv if a.startswith("--unit=")), "")
    return os.path.join(SLICE_DIR, f"{unit}.scope", "memory.stat") if unit else ""


def _nofollow(path: str, flags: int) -> int:
    """open()'s opener for a `slot.N.passed` mark: a symlink planted in its place is never followed, a FIFO never parks."""
    return os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644)


def _held(d: str) -> tuple:
    """(how many slots are held, the memory their holders reserved, what the holders that passed nobody (PASS)
    reserved, None while none of them holds one): each held slot's file names its holder's need, a flocked
    `slot.N.passed` beside it says its holder passed, and one that names none (written a moment from now, or by a
    release before MEMORY) counts as CHECK_MEM."""
    n = reserved = 0
    kept = None
    for name in os.listdir(d):
        if not re.fullmatch(r"slot\.[0-9]+", name):
            continue
        with open(os.path.join(d, name), "a+") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
                continue   # nobody holds it
            except OSError:
                pass
            f.seek(0)
            mem = _bytes(f.read()) or _bytes(CHECK_MEM) or 0
            n += 1
            reserved += mem
            try:
                with open(os.path.join(d, name + ".passed"), opener=_nofollow) as p:
                    fcntl.flock(p, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:   # its holder passed
                continue
            except OSError:
                pass
            kept = (kept or 0) + mem
    return n, reserved, kept


def room(d: str, need: int) -> str:
    """"" when a check that needs `need` bytes fits in lander.slice now (MEMORY), else what it waits for. Always ""
    while no slot is held, so a check always gets to run. A scope its starter left running is killed first (ORPHANS)."""
    reap()
    high = slice_high()
    if high is None:
        return ""
    n, reserved, _ = _held(d)
    # brief: "weighs the slice's live memory.current plus each check's recorded peak", with `anon` for current
    used = max(slice_used() or 0, reserved)
    if not n or used + need <= high:
        return ""
    return f"room in lander.slice ({used >> 20} of {high >> 20} MiB held, {need >> 20} MiB wanted)"


_read: tuple = (None, 0.0)   # (K, when): config_slots() spawns cc-config, and slot() asks every poll (2 s)


def slots(now: float | None = None) -> int:
    """K before any backoff: SLOTS when a caller fixed it, else LANDER_SLOTS from cc-config, else host_slots(), read
    again once CONFIG_TTL seconds have passed, so a running lane follows a change without a restart."""
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


def _ticket(qdir: str, lane: bool = False, first: bool = False, born: int | None = None, aged: bool = False):
    """Join the queue: a file named by when the wait began, flocked for as long as this process waits. It is locked
    before it is given its listed name, so nobody sees it unlocked and takes it for a dead one. A lane's name starts
    `+` (LANES FIRST), which sorts before a digit and still reads as the same number. first: a lane's name, its time
    FIRST_BACK seconds back (FIRST CLAIM), or `born` (ns) when that is older; first=FRONT: FRONT_GAP before the oldest
    live ticket too, but one ns behind the newest FRONT one in the leading run of them (FRONT_MARK), and never
    before a PROVE HOLD (_hold); aged: FRONT_GAP behind those and the hold (AGED); never before time 1 either, so a
    planted time-0 ticket cannot make a name TICKET does not match."""
    now = time.time_ns()
    born = min(now - (FIRST_BACK * 10**9 if first else 0), born or now)
    if first == FRONT or aged:
        _, oldest, stale, _ = _ahead(qdir, "~")   # _ahead drops the dead, so the fronts left are live
        hold, fronts = _hold(qdir), []   # the leading run of FRONT tickets
        for n in sorted(n for n in os.listdir(qdir) if TICKET.fullmatch(n) and n not in stale):
            if n.split("-")[2].startswith(FRONT_MARK):
                fronts.append(int(n.split("-")[0]))
            elif int(n.split("-")[0]) > (hold or 0):   # what waits behind a hold does not end the run before it
                break
        step = 1 if first == FRONT else FRONT_GAP   # aged: the room a first FRONT one leaves stays for later ones
        born = min(born, int(oldest.split("-")[0]) - FRONT_GAP) if oldest and first == FRONT else born
        born = max([born, *(f + step for f in fronts)])   # put first later, it goes behind those put first before
        born = max(born, hold + step) if hold is not None else born
    born = min(max(born, 1), 10**19 - 1)   # 19 digits: a hold near the top cannot spill into 20
    rand = FRONT_MARK + uuid.uuid4().hex[:4] if first == FRONT else "0" + uuid.uuid4().hex[:7]
    name = f"{'+' if lane or first else '0'}{born:019d}-{os.getpid()}-{rand}"
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


def _ahead(qdir: str, mine: str, cap: float | None = None, passes=None) -> tuple:
    """-> (n, oldest, stale, passed): how many live tickets are older than mine, the oldest of those, the live ones
    past cap seconds, which no longer count, and how many it may pass: a ticket naming the need it waits on room for
    (PASS) when passes(need) says so. A dead ticket (its flock free) is removed on the way, and so is a ticket-named
    entry that is not a regular file, or a `.new-` ticket a crash left before its rename. A name _ticket would not
    have given is skipped."""
    cap = TICKET_CAP if cap is None else cap
    hold = os.environ.get("LANDER_PROVE_HOLD", "")   # PROVE HOLD: the proof's sweep counts only what is older
    stop = min(mine, hold) if TICKET.fullmatch(hold) else mine
    n, oldest, stale, passed = 0, None, [], 0
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
                mark = os.pread(fd, 32, 0) if fd is not None and passes else b""
                if mark.isdigit() and passes(int(mark)):
                    passed += 1
                    continue
                n += 1
                oldest = oldest or name
                continue
            if not name.startswith(".") or time.time() - st.st_mtime > 60:
                _drop(p)   # its waiter is gone
        finally:
            if fd is not None:
                os.close(fd)
    return n, oldest, stale, passed


def _hold(qdir: str) -> int | None:
    """The time (ns) a live PROVE HOLD's ticket is named, the newest when there are more, else None: a ticket whose
    pid is a running lander-self (it holds no slot wait of its own, so only its process says what it is): one of its
    first argv entries is named exactly that, so a check run inside a lander-self.check.X tree is not one."""
    born = None
    for name in os.listdir(qdir):
        if TICKET.fullmatch(name) and name.startswith("+"):
            with contextlib.suppress(OSError):
                with open(f"/proc/{name.split('-')[1]}/cmdline", "rb") as f:
                    if any(os.path.basename(a) == b"lander-self" for a in f.read().split(b"\0")[:3]):
                        born = max(born or 0, int(name.split("-")[0]))
    return born


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
         first=False, settle: float | None = None, stop=None, need: int | None = None):
    """Hold one slot (or all of them, alone=True) for the with-block; yields the slot numbers held. Waits its turn
    in the queue (FAIR WAIT), polling, until one admits; deadline (seconds) raises TimeoutError instead of waiting
    on. say(line) is told while it waits; stderr by default. lane=True: a landing lane's wait (LANES FIRST).
    first=True (or a callable that says so, asked each poll): main health's or a main-red fix's check; FRONT: one of a
    job put first (FIRST CLAIM). stop: a callable; True leaves the wait with TimeoutError (STOP). settle (seconds): an
    alone wait that has not got every slot by then waits for one slot instead, in the same place in the queue (SETTLE).
    need (bytes): the check's recorded peak, None for CHECK_MEM; a slot is taken only while lander.slice has room for
    it (MEMORY)."""
    d = os.path.join(state, "slots")
    q = os.path.join(d, "queue")
    os.makedirs(q, exist_ok=True)
    total = max(1, slots() if k is None else k)
    say = say or (lambda line: print(line, file=sys.stderr, flush=True))
    t0, said, since, began = time.monotonic(), None, time.strftime("%H:%MZ", time.gmtime()), time.time()
    held: list = []
    gate = None   # the ALONE GATE: exclusive for an alone run, shared beside another's slot
    told: set = set()
    need = need or _bytes(CHECK_MEM) or 0
    ask = first if callable(first) else lambda: first
    firsted, worker = ask(), not lane
    mine, tf = _ticket(q, lane, firsted)
    marked, mark_f = "", None
    try:
        while True:
            if stop is not None and stop():
                raise TimeoutError("stopped while it waited for a lander slot")
            aged = worker and not firsted and time.time() - began >= AGED and (   # AGED: a worker's wait becomes a
                not lane or (_hold(q) or 0) >= int(mine.split("-")[0]))   # lane's, and goes behind a hold taken since
            if aged or firsted != FRONT and ask() not in (firsted, False):   # aged, or put first meanwhile: up, never back
                lane, firsted = lane or aged, ask()
                new, nf = _ticket(q, lane, firsted, born=int(mine.split("-")[0]), aged=aged)
                with contextlib.suppress(OSError):
                    os.unlink(os.path.join(q, mine))
                tf.close()
                mine, tf, marked = new, nf, ""
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
            high, kept = slice_high(), _held(d)[2]   # PASS: a ticket short of room only for what non-passers hold
            passes = None if alone or high is None or kept is None else lambda h: kept + h > high
            ahead, oldest, stale, passed = _ahead(q, mine, passes=passes)
            for name in set(stale) - told:
                told.add(name)
                line = (f"lander: {who or 'a check'} no longer waits on ticket {name} ({_whose(name)}): "
                        f"older than {TICKET_CAP / 3600:g} h, so its waiter is taken for stuck")
                with contextlib.suppress(OSError, ValueError):   # only say(): a gone or closed stderr
                    say(line)
            if alone and not ahead and gate is None:
                gate = _gate(d, fcntl.LOCK_EX)   # none while any check holds a slot, whatever K it counted
            short_of = room(d, need) if not alone and not ahead else ""   # an alone run has the slice to itself
            if (mark := str(need) if short_of else "") != marked:   # PASS: what it waits on room for, for those behind
                with contextlib.suppress(OSError):
                    os.ftruncate(tf.fileno(), 0)
                    tf.write(mark)
                    tf.flush()
                marked = mark
            for n in want if not ahead and not short_of and (gate or not alone) else ():   # only the oldest takes one
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
                    os.ftruncate(f.fileno(), 0)   # what it reserved, for the next waiter's room()
                    f.write(str(need))
                    f.flush()
                    if passed:   # advisory: a mark it can't open or lock only counts it a non-passer
                        with contextlib.suppress(OSError):
                            mark_f = open(os.path.join(d, f"slot.{n}.passed"), "a", opener=_nofollow)
                            _flock(mark_f, fcntl.LOCK_EX)   # waits out a peer _held()'s brief LOCK_SH, else not passed
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
                        else f"one of slots 1-{len(want)} (load admits {len(want)} of {total})"
                        + (f" and {short_of}" if short_of else ""))
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
        if mark_f is not None:   # before its slot, so the next holder of the slot never waits on this mark
            mark_f.close()
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


def free(state: str, psi_root: str = PSI_DIR, k: int | None = None, loadavg: str | None = None,
         need: int | None = None) -> int:
    """How many of slots_now()'s slots a check would take now without waiting: each one nobody holds, and none while
    a ticket waits in the queue (it goes first, FAIR WAIT), an alone run holds the gate or lander.slice has no room
    for a check of `need` bytes (MEMORY; None: CHECK_MEM). It only looks: a slot is
    flocked for the instant it takes to see it is free. run.spill() asks it, so a check that would wait here goes to
    a runner instead."""
    d = os.path.join(state, "slots")
    if not os.path.isdir(d):
        return slots_now(psi_root, k, loadavg)
    q = os.path.join(d, "queue")
    if os.path.isdir(q) and _ahead(q, "~")[0]:   # "~" sorts after every ticket's name, so each live one counts
        return 0
    if room(d, need or _bytes(CHECK_MEM) or 0):
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
    label = ''.join(c if c.isalnum() else '-' for c in (label or check.name))[:60]
    unit = f"lander-{label}-p{os.getpid()}-{uuid.uuid4().hex[:8]}"   # the pid: reap() kills it once that is gone
    return (["systemd-run", "--user", "--scope", "--quiet", "--collect", "--slice=lander.slice", f"--unit={unit}",
             "-p", f"CPUWeight={CPU_WEIGHT}", "-p", f"MemoryMax={MEM_MAX}", "-p", f"MemorySwapMax={SWAP_MAX}", "--"]
            + pre + argv), "scope"
