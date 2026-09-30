"""Admission: how many checks run at once, and the limits each runs under (review S8).

SLOTS. K = LANDER_SLOTS (default 3) box-wide slots, each a flock on `<state>/slots/slot.<n>`. The box's load is
mostly not the lander's, so a load average would give one slot nearly always; pressure is the signal instead. When
/proc/pressure/memory `some avg10` reaches PSI_MEM (default 20) or /proc/pressure/cpu `some avg10` reaches PSI_CPU
(default 99.5 — this box idles near 98, so only a saturated one counts), the box is loaded(). It is overloaded() when it is
loaded() or its 1-minute load average reaches LANDER_LOAD_FACTOR (default 2) times its cores. While overloaded by cpu
PSI or the load average only slots 1-2 admit; under memory pressure only slot 1, because parallel checks have run the
box out of memory. Never 0: a check always gets to run, only later. A diagnostic rerun takes every
slot at once (alone=True), so it runs by itself; it takes them in order and never past a busy one, because one
lane now runs several checks at once and two alone runs each holding a slot would wait on each other forever.

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
import fcntl
import os
import shutil
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


@contextlib.contextmanager
def slot(state: str, alone: bool = False, poll: float = 2.0, deadline: float | None = None, psi_root: str = PSI_DIR,
         k: int | None = None, loadavg: str | None = None):
    """Hold one slot (or all of them, alone=True) for the with-block; yields the slot numbers held. Waits, polling,
    until one admits; deadline (seconds) raises TimeoutError instead of waiting on."""
    d = os.path.join(state, "slots")
    os.makedirs(d, exist_ok=True)
    total = max(1, SLOTS if k is None else k)
    t0 = time.monotonic()
    held: list = []
    try:
        while True:
            want = range(1, total + 1) if alone else range(1, slots_now(psi_root, total, loadavg) + 1)
            for n in want:
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
            if not alone:
                for _, f in held:
                    f.close()
                held = []
            time.sleep(poll)
        yield [n for n, _ in held]
    finally:
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
