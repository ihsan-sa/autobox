"""The bwrap profile a hermetic check runs in (review B2b), modelled on `cc-suites runner`, not on `cc-sandbox vet`.

WHAT IS INSIDE: the distribution read-only (/usr and the merged-usr links, the real /etc — vet's tmpfs /etc loses
/usr/bin/awk through /etc/alternatives), /opt and /var/lib/texmf (the TeX formats /usr's pdflatex
loads) when there, a fresh /proc, /dev and tmpfs /tmp; the check's tree
read-write at /work/tree — never at its host path, whose parent directories would name this user's HOME — as a git
repo with one commit (the identity check greps it, B1); a tmpfs HOME at /work/home holding only a stub
`~/.local/bin/claude` that sleeps (the suite stubs every model call; a window that starts one must stay up) — off
/tmp, since the guard and cc-slack's upload check let anything under /tmp through, so a HOME there passed writes and
uploads their checks expect refused; an empty directory at this user's passwd home, so a command that runs from there
(cc-slack's approved runs, cwd=PW_HOME) finds its directory and nothing of the host's in it; XDG_RUNTIME_DIR at
/run/user/<uid>, an empty 0700 directory on the tmpfs /run (systemd-analyze --user cannot start without one); and a
private tmux server (TMUX_TMPDIR=/tmp/tmux) with a session `main`. Each of the check's `mounts` is bound read-only
at its own path (a leading ~ is this user's HOME) — a mount that is not there makes the run unrunnable, never a skip
that passes (MissingMount).

WHAT IS NOT: the network (unless the check says net = true), this user's HOME and ~/.cc, every token, the host's
tmux server, and every variable of the caller's environment (--clearenv; env() is all there is). User namespaces
stay allowed: cc-sandbox's own selfcheck, lessons, the library editor and cc-lib's member cases nest bwrap. With
kernel.apparmor_restrict_unprivileged_userns=1 every child of /usr/bin/bwrap runs under unpriv_bwrap, which denies all
capabilities, so a bwrap nested in it cannot mount ("No permissions to create a new namespace": cc-lib's eight member
cases, 10-20). The box's claude-bwrap copy has a profile of its own that leaves its children unconfined
(config/etc/claude-bwrap), so the cage starts with it where it is installed (WRAPPERS, as tests/member_v2.py does).

The run itself is `/bin/sh -c <run>` from the check's directory inside the tree; CC_SELFTEST_HELD tells selftest.sh
this run already holds its slot, and CC_SELFTEST_SPILL=0 keeps it from spilling to a laptop from in here.

SETUP SAYS IT STARTED OUT OF BAND (started(), say()): given started_fd, the sandbox's own SETUP (the stub and its
directories) runs first, then STARTED is written to that fd and the fd closed before tmux or anything of the check's
runs, so the check never holds it. The lander reads the pipe's other end: no STARTED means the sandbox never started, and the check's own output — which may say
`bwrap:` as well as anything — is never what decides that (perms on #1452).
"""
from __future__ import annotations

import os
import pwd
import shutil
import sys

from lander import types as T

HOME_IN = "/work/home"
RUNTIME_IN = f"/run/user/{os.getuid()}"
TREE_IN = "/work/tree"
TMUX_IN = "/tmp/tmux"
PATH_IN = f"{HOME_IN}/.local/bin:/usr/local/bin:/usr/bin:/bin"
STARTED = b"started"
# the fd the run says STARTED on: dash (/bin/sh) takes no fd above 9 in `>&N` or `exec N>&-`, and the lander's own
# pipe is often 10 or more, so pin() moves it here before anything else of the run starts
FD = 3
PIN = (f"import os, sys\nn = int(sys.argv[1])\nif n != {FD}:\n    os.dup2(n, {FD})\n    os.close(n)\n"
       "os.execvp(sys.argv[2], sys.argv[2:])\n")
STUB = ("#!/bin/sh\n# the lander's sandbox stub: the suite stubs every model call; this only keeps a window up\n"
        "exec sleep 3600\n")
# a setup step that fails stops the run with this as its first line, which run.SETUP_RE reads as unrunnable
SETUP_FAILED = "lander-sandbox: setup failed, nothing ran"
SETUP = (f'err=$({{ mkdir -p "{TMUX_IN}" "{HOME_IN}/.local/bin" "{RUNTIME_IN}" && chmod 700 "{TMUX_IN}" "{RUNTIME_IN}" && '
         f'cp "$LANDER_STUB" "{HOME_IN}/.local/bin/claude" && chmod +x "{HOME_IN}/.local/bin/claude"; }} 2>&1) || '
         f'{{ printf "%s: %s\\n" "{SETUP_FAILED}" "$err" >&2; exit 125; }}; ')
CHECK = ('command -v tmux >/dev/null 2>&1 && tmux new-session -d -s main -x 200 -y 50 >/dev/null 2>&1; '
         'exec /bin/sh -c "$1"')


class MissingMount(RuntimeError):
    pass


WRAPPERS = ("/usr/local/libexec/claude-bwrap", "bwrap")


def wrapper() -> str | None:
    return next((w for w in WRAPPERS if shutil.which(w)), None)


def available() -> bool:
    return wrapper() is not None


def env(extra: dict | None = None) -> dict:
    user = os.environ.get("USER") or "lander"
    e = {"PATH": PATH_IN, "HOME": HOME_IN, "USER": user, "LOGNAME": user, "LANG": "C.UTF-8", "TERM": "dumb",
         "SHELL": "/bin/bash", "TMPDIR": "/tmp", "TMUX_TMPDIR": TMUX_IN, "XDG_RUNTIME_DIR": RUNTIME_IN,
         "CC_SELFTEST_HELD": "1",
         "CC_SELFTEST_SPILL": "0", "LANDER_STUB": "/tmp/.lander-stub"}
    e.update(extra or {})
    return e


def pw_home() -> str:
    """This user's home in the password database, which the cage's real /etc names anyway; "" when it has none."""
    try:
        return pwd.getpwuid(os.getuid()).pw_dir.rstrip("/") or "/"
    except KeyError:
        return ""


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


def pin(fd: int) -> list:
    """The argv prefix that moves `fd` to FD (inheritable) and execs the rest; the host's own python, outside every
    sandbox and scope. A failure exits non-zero having said nothing: unrunnable."""
    return [sys.executable, "-I", "-c", PIN, str(fd)]


def started(fd: int) -> list:
    """The argv prefix that says STARTED on `fd`, closes it, then execs the rest; it exits 125, running nothing,
    when it cannot say it."""
    return ["/bin/sh", "-c", say(fd) + 'exec "$@"', "lander-started"]


def say(fd: int) -> str:
    """Shell that says STARTED on `fd` (at most 9: dash) and closes it, or exits 125."""
    return f'printf {STARTED.decode()} >&{fd} || exit 125; exec {fd}>&-; '


def argv(check: T.Check, tree: str, stub: str, cwd: str = "", extra_env: dict | None = None,
         home: str | None = None, started_fd: int | None = None) -> list:
    """The full bwrap command line that runs check.run in `tree` (a host directory). stub: write_stub()'s file.
    cwd: the check's directory inside the tree (its manifest prefix). started_fd: said on (say()) once the
    sandbox is up and its SETUP (the stub) is in, before tmux or the check starts."""
    a = [wrapper() or "bwrap", "--die-with-parent", "--new-session", "--unshare-all", "--hostname", "lander", "--clearenv",
         "--ro-bind", "/usr", "/usr"]
    if check.net:
        a.append("--share-net")
    for d in ("bin", "lib", "lib32", "lib64", "sbin"):
        p = "/" + d
        if os.path.islink(p):
            a += ["--symlink", os.readlink(p), p]
        elif os.path.isdir(p):
            a += ["--ro-bind", p, p]
    a += ["--ro-bind", "/etc", "/etc", "--ro-bind-try", "/opt", "/opt",
          "--ro-bind-try", "/var/lib/texmf", "/var/lib/texmf", "--proc", "/proc", "--dev", "/dev",
          "--tmpfs", "/tmp", "--tmpfs", "/run"]
    if check.net:   # the resolver the real /etc points at
        a += ["--ro-bind-try", "/run/systemd/resolve", "/run/systemd/resolve"]
    for p in mounts(check, home):
        a += ["--ro-bind", p, p]
    a += ["--bind", tree, TREE_IN, "--tmpfs", HOME_IN]
    pw = pw_home()
    if pw not in ("", "/", HOME_IN):
        a += ["--dir", pw]
    for k, v in env(extra_env).items():
        a += ["--setenv", k, v]
    a += ["--ro-bind", stub, "/tmp/.lander-stub", "--chdir", os.path.join(TREE_IN, cwd.rstrip("/")) if cwd else TREE_IN,
          "--", "/bin/sh", "-c", SETUP + (say(started_fd) if started_fd is not None else "") + CHECK, "lander-run",
          check.run]
    return a

