"""The bwrap profile a hermetic check runs in (review B2b), modelled on `cc-suites runner`, not on `cc-sandbox vet`.

WHAT IS INSIDE: the distribution read-only (/usr and the merged-usr links, the real /etc — vet's tmpfs /etc loses
/usr/bin/awk through /etc/alternatives), /opt when there is one, a fresh /proc, /dev and tmpfs /tmp; the check's tree
read-write at /work/tree — never at its host path, whose parent directories would name this user's HOME — as a git
repo with one commit (the identity check greps it, B1); a tmpfs HOME at /tmp/home holding only a stub
`~/.local/bin/claude` that sleeps (the suite stubs every model call; a window that starts one must stay up); and a
private tmux server (TMUX_TMPDIR=/tmp/tmux) with a session `main`. Each of the check's `mounts` is bound read-only
at its own path (a leading ~ is this user's HOME) — a mount that is not there makes the run unrunnable, never a skip
that passes (MissingMount).

WHAT IS NOT: the network (unless the check says net = true), this user's HOME and ~/.cc, every token, the host's
tmux server, and every variable of the caller's environment (--clearenv; env() is all there is). User namespaces
stay allowed: cc-sandbox's own selfcheck, lessons and the library editor nest bwrap.

The run itself is `/bin/sh -c <run>` from the check's directory inside the tree; CC_SELFTEST_HELD tells selftest.sh
this run already holds its slot, and CC_SELFTEST_SPILL=0 keeps it from spilling to a laptop from in here.
"""
from __future__ import annotations

import os
import shutil

from lander import types as T

HOME_IN = "/tmp/home"
TREE_IN = "/work/tree"
TMUX_IN = "/tmp/tmux"
PATH_IN = f"{HOME_IN}/.local/bin:/usr/local/bin:/usr/bin:/bin"
STUB = ("#!/bin/sh\n# the lander's sandbox stub: the suite stubs every model call; this only keeps a window up\n"
        "exec sleep 3600\n")
PRELUDE = (f'mkdir -p "{TMUX_IN}" "{HOME_IN}/.local/bin" && chmod 700 "{TMUX_IN}" && '
           f'cp "$LANDER_STUB" "{HOME_IN}/.local/bin/claude" && chmod +x "{HOME_IN}/.local/bin/claude"; '
           'command -v tmux >/dev/null 2>&1 && tmux new-session -d -s main -x 200 -y 50 >/dev/null 2>&1; '
           'exec /bin/sh -c "$1"')


class MissingMount(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("bwrap") is not None


def env(extra: dict | None = None) -> dict:
    user = os.environ.get("USER") or "lander"
    e = {"PATH": PATH_IN, "HOME": HOME_IN, "USER": user, "LOGNAME": user, "LANG": "C.UTF-8", "TERM": "dumb",
         "SHELL": "/bin/bash", "TMPDIR": "/tmp", "TMUX_TMPDIR": TMUX_IN, "CC_SELFTEST_HELD": "1",
         "CC_SELFTEST_SPILL": "0", "LANDER_STUB": "/tmp/.lander-stub"}
    e.update(extra or {})
    return e


def mounts(check: T.Check, home: str | None = None) -> list:
    """Each of check.mounts as an absolute host path. Raises MissingMount for one that is not there."""
    home = home or os.path.expanduser("~")
    out = []
    for m in check.mounts:
        p = home + m[1:] if m == "~" or m.startswith("~/") else m
        if not os.path.isabs(p):
            raise MissingMount(f"mount {m!r} is not an absolute path")
        if not os.path.exists(p):
            raise MissingMount(f"mount {m!r} is not on this host ({p})")
        out.append(p)
    return out


def write_stub(scratch: str) -> str:
    """STUB as a file in the run's scratch directory (outside the tree, so it never changes the tree's hash)."""
    p = os.path.join(scratch, "claude-stub")
    with open(p, "w") as f:
        f.write(STUB)
    return p


def argv(check: T.Check, tree: str, stub: str, cwd: str = "", extra_env: dict | None = None,
         home: str | None = None) -> list:
    """The full bwrap command line that runs check.run in `tree` (a host directory). stub: write_stub()'s file.
    cwd: the check's directory inside the tree (its manifest prefix)."""
    a = ["bwrap", "--die-with-parent", "--new-session", "--unshare-all", "--hostname", "lander", "--clearenv",
         "--ro-bind", "/usr", "/usr"]
    if check.net:
        a.append("--share-net")
    for d in ("bin", "lib", "lib32", "lib64", "sbin"):
        p = "/" + d
        if os.path.islink(p):
            a += ["--symlink", os.readlink(p), p]
        elif os.path.isdir(p):
            a += ["--ro-bind", p, p]
    a += ["--ro-bind", "/etc", "/etc", "--ro-bind-try", "/opt", "/opt", "--proc", "/proc", "--dev", "/dev",
          "--tmpfs", "/tmp", "--tmpfs", "/run"]
    if check.net:   # the resolver the real /etc points at
        a += ["--ro-bind-try", "/run/systemd/resolve", "/run/systemd/resolve"]
    for p in mounts(check, home):
        a += ["--ro-bind", p, p]
    a += ["--bind", tree, TREE_IN, "--dir", HOME_IN]
    for k, v in env(extra_env).items():
        a += ["--setenv", k, v]
    a += ["--ro-bind", stub, "/tmp/.lander-stub", "--chdir", os.path.join(TREE_IN, cwd.rstrip("/")) if cwd else TREE_IN,
          "--", "/bin/sh", "-c", PRELUDE, "lander-run", check.run]
    return a

