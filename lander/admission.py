"""Admission: how many checks run at once, and the limits each runs under (review S8).

SLOTS. K = LANDER_SLOTS (default 3) box-wide slots, each a flock on `<state>/slots/slot.<n>`. The box's load is
mostly not the lander's, so a load average would give one slot nearly always; pressure is the signal instead. When
/proc/pressure/memory `some avg10` reaches PSI_MEM (default 20) or /proc/pressure/cpu `some avg10` reaches PSI_CPU
(default 99.5 — this box idles near 98, so only a saturated one counts), only slot 1 admits. Never 0: a check always
gets to run, only later. A diagnostic rerun takes every slot at once (alone=True), so it runs by itself.

LAPTOP. busy() is a static check's lower bar for the laptop: cpu `some avg10` at PSI_LAPTOP (default 50) or memory
at PSI_MEM. A box under loaded()'s near-saturation mark all day is still slow. Hermetic checks keep loaded().

SCOPES. Each run goes into a transient `systemd-run --user --scope` on slice `lander.slice` (no unit file) with a low
CPUWeight, a MemoryMax and no swap (a box already deep in swap is what this guards against), so the kernel,
not the lander, stops a check that eats the box — and one killed there is unrunnable, never red. Hermetic and
static checks also run under `nice -n 10`; host, box and timing checks keep today's priority. With no user systemd
bus (or LANDER_SCOPE=0) the scope is dropped and the run says so in its runner string, never silently.

TIMING checks race the clock: they run before the merge only while loaded() is false; otherwise the run is
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
PSI_LAPTOP = float(os.environ.get("LANDER_PSI_LAPTOP", "50"))
MEM_MAX = os.environ.get("LANDER_MEM_MAX", "6G")
SWAP_MAX = os.environ.get("LANDER_SWAP_MAX", "0")
CPU_WEIGHT = "20"
PSI_DIR = "/proc/pressure"


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


def loaded(root: str = PSI_DIR) -> bool:
    return psi("memory", root) >= PSI_MEM or psi("cpu", root) >= PSI_CPU


def busy(root: str = PSI_DIR) -> bool:
    """Busy enough that a static check goes to the laptop; lower than loaded(), and slots ignore it."""
    return psi("memory", root) >= PSI_MEM or psi("cpu", root) >= PSI_LAPTOP


def slots_now(root: str = PSI_DIR, k: int | None = None) -> int:
    k = max(1, SLOTS if k is None else k)
    return 1 if loaded(root) else k


@contextlib.contextmanager
def slot(state: str, alone: bool = False, poll: float = 2.0, deadline: float | None = None, psi_root: str = PSI_DIR,
         k: int | None = None):
    """Hold one slot (or all of them, alone=True) for the with-block; yields the slot numbers held. Waits, polling,
    until one admits; deadline (seconds) raises TimeoutError instead of waiting on."""
    d = os.path.join(state, "slots")
    os.makedirs(d, exist_ok=True)
    total = max(1, SLOTS if k is None else k)
    t0 = time.monotonic()
    held: list = []
    try:
        while True:
            want = range(1, total + 1) if alone else range(1, slots_now(psi_root, total) + 1)
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


def wrap(check: T.Check, argv: list, label: str = "") -> tuple:
    """-> (argv, how): argv inside its scope and priority, and a word for Result.runner ("scope" or "noscope")."""
    pre = ["nice", "-n", "10"] if check.klass in (T.HERMETIC, T.STATIC) else []
    if not scope_available():
        return pre + argv, "noscope"
    unit = f"lander-{''.join(c if c.isalnum() else '-' for c in (label or check.name))[:60]}-{uuid.uuid4().hex[:8]}"
    return (["systemd-run", "--user", "--scope", "--quiet", "--collect", "--slice=lander.slice", f"--unit={unit}",
             "-p", f"CPUWeight={CPU_WEIGHT}", "-p", f"MemoryMax={MEM_MAX}", "-p", f"MemorySwapMax={SWAP_MAX}", "--"]
            + pre + argv), "scope"
