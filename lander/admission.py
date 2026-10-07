"""Admission: how many checks run at once, and the limits each runs under (review S8).

SLOTS. K = LANDER_SLOTS (default 3) box-wide slots, each a flock on `<state>/slots/slot.<n>`. The box's load is
mostly not the lander's, so a load average would give one slot nearly always; pressure is the signal instead. When
/proc/pressure/memory `some avg10` reaches PSI_MEM (default 20) or /proc/pressure/cpu `some avg10` reaches PSI_CPU
(default 99.5 — this box idles near 98, so only a saturated one counts), the box is loaded(). It is overloaded() when it is
loaded() or its 1-minute load average reaches LANDER_LOAD_FACTOR (default 2) times its cores. While overloaded by cpu
PSI or the load average only slots 1-2 admit; under memory pressure only slot 1, because parallel checks have run the
box out of memory. Never 0: a check always gets to run, only later. An EXPRESS run (the lane's Δ rerun of a
mergeable job's short check; each lane runs at most lane.EXPRESS_SLOTS of them at once, so the box runs that many per
lane, and none while mem_loaded()) takes no slot and no ticket. A diagnostic rerun takes every
slot at once (alone=True), so it runs by itself; it takes them in order and never past a busy one, because one
lane now runs several checks at once and two alone runs each holding a slot would wait on each other forever.

FAIR WAIT (2026-10-01/02: worker green runs sat 2-8 h in the poll loop while a lane re-took slot.1 the moment it
let go). Every wait takes a ticket, a flocked file in `<state>/slots/queue/` named by when it began, and only the
oldest live ticket may take a slot; it drops the ticket once it holds what it wants. So a waiter is served before
anyone who came later, the lane included, and an alone run at the head of the queue gets each slot as its holder
lets go instead of losing it to the next check. Nobody gets more slots than slots_now() allows; the order changes,
not the count. A ticket whose holder died is unlocked, and the next waiter removes it, as it does anything in the
queue that is not a regular file. A name _ticket would not have given is ignored, never waited on and never said,
so a planted `!hold` that sorts first holds nobody up. A ticket it cannot open or lock for want of a file
descriptor, memory or a lock still counts as live: only a bad entry is removed. A waiter behind another holds no slot,
or an older ticket that needs it would wait forever. A ticket still locked after TICKET_CAP seconds
(LANDER_TICKET_CAP, default 12 h, about twice the longest wait a fair queue should see) is taken for a stopped
waiter and no longer counts, and the waiter that passes it says so. While it waits, slot() writes one line to
stderr (the run's log) saying what it waits for, since when and whose ticket is oldest, then again every WAIT_SAY
seconds (LANDER_WAIT_SAY, default 600). In a cc-green run, which names its status file in LANDER_WAIT_NOTE, the first line said
past WAIT_SAY is also appended there ONCE as `waiting=`, so `cc-green wait` says the run is on slots, not hung, and
what to do about it: such runs sat 2-3 h with only a header in their log five times between 09-29 and 10-01, each read
as hung. The landing lane sets no note.

HIGH LOAD (2026-09-28: load 31-80 on 12 cores and 12 GB swapped, checks went from under 5 min to 11-17). overloaded() is
the one signal for "the box is overloaded": the lander serializes on it and gives its one run priority (below), and
`cc-room` queues new `--go` workers on the same call until it clears, so the landing queue keeps moving while the
load that is already there drains. Nothing is stopped or paused; only starts wait.

LAPTOP. Every check that may leave the box goes to the laptop first (run.choose_where, owner 2026-09-29), and the lane
keeps up to LAPTOP_SLOTS (LANDER_LAPTOP_SLOTS, default 5) of them in flight beside the box's slots, which they do not
take; a laptop that answers busy sends the check back to the box. busy() no longer places checks; it was the bar: cpu `some avg10` at PSI_LAPTOP (default 25), memory at
PSI_MEM, or a 1-minute load average at LANDER_LAPTOP_LOAD (default 1) times the cores. A box under loaded()'s
near-saturation mark all day is still slow: on 2026-09-29 it sat at load 9-27 on 6 cores with cpu PSI near 38, and
sent 1 check of 200 out. busy() is not overloaded(): slots and cc-room ignore it.

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
import sys
import time
import uuid

from lander import types as T

SLOTS = int(os.environ.get("LANDER_SLOTS", "3") or 3)
PSI_MEM = float(os.environ.get("LANDER_PSI_MEM", "20"))
PSI_CPU = float(os.environ.get("LANDER_PSI_CPU", "99.5"))
PSI_LAPTOP = float(os.environ.get("LANDER_PSI_LAPTOP", "25"))
LAPTOP_SLOTS = max(0, int(os.environ.get("LANDER_LAPTOP_SLOTS", "5") or 0))
LAPTOP_LOAD = float(os.environ.get("LANDER_LAPTOP_LOAD", "1") or 1)
MEM_MAX = os.environ.get("LANDER_MEM_MAX", "6G")
SWAP_MAX = os.environ.get("LANDER_SWAP_MAX", "0")
CPU_WEIGHT = "20"
LOAD_FACTOR = float(os.environ.get("LANDER_LOAD_FACTOR", "2") or 2)
PSI_DIR = os.environ.get("LANDER_PSI_DIR") or "/proc/pressure"
LOADAVG = os.environ.get("LANDER_LOADAVG") or "/proc/loadavg"
WAIT_SAY = float(os.environ.get("LANDER_WAIT_SAY", "600") or 600)
TICKET_CAP = float(os.environ.get("LANDER_TICKET_CAP", "43200") or 43200)


def psi(kind: str, root: str = PSI_DIR) -> float:
    """`some avg10` for cpu/memory/io, or 0.0 when the kernel has no PSI."""
    try:
        with open(os.path.join(root, kind)) as f:
            for line in f:
                if line.startswith("some "):
                    return float(dict(kv.split("=") for kv in line.split()[1:])["avg10"])
    except (OSError, KeyError, ValueError):
        pass
    return 0.0


def mem_loaded(root: str = PSI_DIR) -> bool:
    return psi("memory", root) >= PSI_MEM


def loaded(root: str = PSI_DIR) -> bool:
    return mem_loaded(root) or psi("cpu", root) >= PSI_CPU


def load1(loadavg: str | None = None) -> float | None:
    """The 1-minute load average, or None when it cannot be read."""
    try:
        with open(loadavg or LOADAVG) as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def busy(root: str = PSI_DIR, loadavg: str | None = None) -> bool:
    """Busy enough that a check goes to the laptop; lower than loaded(), and slots ignore it. An unreadable load
    average counts as calm."""
    if psi("memory", root) >= PSI_MEM or psi("cpu", root) >= PSI_LAPTOP:
        return True
    l1 = load1(loadavg)
    return l1 is not None and l1 >= LAPTOP_LOAD * (os.cpu_count() or 1)


def overloaded(root: str = PSI_DIR, loadavg: str | None = None) -> str:
    """"" when the box is not overloaded, else one line saying why: loaded(), or the 1-minute load average at or
    above LOAD_FACTOR x cores. An unreadable load average counts as calm."""
    if loaded(root):
        return f"memory or cpu pressure (PSI) at {psi('memory', root):.0f}/{psi('cpu', root):.1f}"
    n, l1 = os.cpu_count() or 1, load1(loadavg)
    if l1 is None:
        return ""
    return f"load {l1:.1f} on {n} cores (at least {LOAD_FACTOR:g}x)" if l1 >= LOAD_FACTOR * n else ""


def slots_now(root: str = PSI_DIR, k: int | None = None, loadavg: str | None = None) -> int:
    k = max(1, SLOTS if k is None else k)
    if not overloaded(root, loadavg):
        return k
    # cpu PSI or the load average: two still run. Memory pressure: one, because parallel checks have run the box
    # out of memory before
    return 1 if mem_loaded(root) else min(k, 2)


TICKET = re.compile(r"[0-9]{20}-[0-9]+-[0-9a-f]{8}")   # _ticket's names: time_ns-pid-rand
BAD = (errno.ELOOP, errno.ENXIO, errno.EACCES, errno.EPERM)   # a symlink, a socket, an unreadable file: not a ticket


def _ticket(qdir: str):
    """Join the queue: a file named by when the wait began, flocked for as long as this process waits. It is locked
    before it is given its listed name, so nobody sees it unlocked and takes it for a dead one."""
    name = f"{time.time_ns():020d}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
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
    n, oldest, stale = 0, None, []
    for name in sorted(os.listdir(qdir)):
        if name >= mine:
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
         k: int | None = None, loadavg: str | None = None, who: str = "", say=None):
    """Hold one slot (or all of them, alone=True) for the with-block; yields the slot numbers held. Waits its turn
    in the queue (FAIR WAIT), polling, until one admits; deadline (seconds) raises TimeoutError instead of waiting
    on. say(line) is told while it waits; stderr by default."""
    d = os.path.join(state, "slots")
    q = os.path.join(d, "queue")
    os.makedirs(q, exist_ok=True)
    total = max(1, SLOTS if k is None else k)
    say = say or (lambda line: print(line, file=sys.stderr, flush=True))
    t0, said, since = time.monotonic(), None, time.strftime("%H:%MZ", time.gmtime())
    held: list = []
    told: set = set()
    mine, tf = _ticket(q)
    try:
        while True:
            want = range(1, total + 1) if alone else range(1, slots_now(psi_root, total, loadavg) + 1)
            ahead, oldest, stale = _ahead(q, mine)
            for name in set(stale) - told:
                told.add(name)
                line = (f"lander: {who or 'a check'} no longer waits on ticket {name} ({_whose(name)}): "
                        f"older than {TICKET_CAP / 3600:g} h, so its waiter is taken for stuck")
                with contextlib.suppress(OSError, ValueError):   # only say(): a gone or closed stderr
                    say(line)
            for n in want if not ahead else ():   # only the oldest waiter takes a slot
                if n in [h for h, _ in held]:
                    continue
                f = open(os.path.join(d, f"slot.{n}"), "a")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held.append((n, f))
                    if not alone:
                        break
                except OSError:
                    f.close()
                    if alone:   # in order, never past a busy one: two alone runs holding a slot each would wait forever
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
            time.sleep(poll)
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(q, mine))
        tf.close()
        tf = None
        yield [n for n, _ in held]
    finally:
        if tf is not None:
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(q, mine))
            tf.close()
        for _, f in held:
            f.close()


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
