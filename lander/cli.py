#!/usr/bin/env python3
"""lander — the one entry point. Every command lives in the module that owns it.

    lander <command> [args…]
    lander --help          every command this release has, with its module
    lander selfcheck       the skeleton's own cases (types round trip, command collection, module health)

A MODULE ADDS COMMANDS by defining, at module level,

    COMMANDS = {"plan": (cmd_plan, "print the plan for <repo> <pr>")}

where each function takes the argument list after the command name and returns an exit code. This file never
names a unit's commands, so four units add theirs without touching it. Every lander/*.py but this file, types
and __init__ is imported; a module that is not there yet is simply absent. A module that fails to IMPORT is
not silent: its commands are missing, it says so on stderr, and selfcheck goes red. Two modules claiming one
command name is the same kind of fault — the first in name order keeps it.
"""
import importlib
import os
import sys

# This directory holds a types.py that would shadow the stdlib one; run as a script, Python puts it first on
# sys.path. Take it off and put the package's parent on instead, so the modules are `lander.<name>`.
PKG = os.path.dirname(os.path.realpath(__file__))
sys.path[:] = [p for p in sys.path if os.path.realpath(p or ".") != PKG]
sys.path.insert(0, os.path.dirname(PKG))

SKIP = {"cli", "types", "__init__"}


def modules(pkg_dir=PKG):
    return sorted(f[:-3] for f in os.listdir(pkg_dir)
                  if f.endswith(".py") and not f.startswith(("_", ".")) and f[:-3] not in SKIP)


def collect(names, load=lambda m: importlib.import_module(f"lander.{m}")):
    """-> (commands {name: (func, help, module)}, faults [str]). `load` is swapped out by the tests."""
    cmds, faults = {}, []
    for m in names:
        try:
            mod = load(m)
        except ModuleNotFoundError as e:
            if e.name in (m, f"lander.{m}"):   # the module itself is absent: skipped, by design
                continue
            faults.append(f"{m}: cannot import: {e}")
            continue
        except Exception as e:  # noqa: BLE001 — any import-time fault is reported, never raised into the CLI
            faults.append(f"{m}: cannot import: {type(e).__name__}: {e}")
            continue
        table = getattr(mod, "COMMANDS", {})
        if not isinstance(table, dict):
            faults.append(f"{m}: COMMANDS is a {type(table).__name__}, not a dict")
            continue
        for name, entry in table.items():
            if not (isinstance(entry, tuple) and len(entry) == 2 and callable(entry[0]) and isinstance(entry[1], str)):
                faults.append(f"{m}: COMMANDS[{name!r}] is not (func, 'help')")
            elif name in cmds or name in BUILTIN:
                faults.append(f"{m}: command {name!r} is already {cmds[name][2] if name in cmds else 'cli'}'s")
            else:
                cmds[name] = (entry[0], entry[1], m)
    return cmds, faults


def usage(cmds):
    lines = [__doc__.split("\n\n")[1].rstrip(), "", "commands:"]
    rows = [(n, h, m) for n, (_, h, m) in cmds.items()] + [(n, h, "cli") for n, (_, h) in BUILTIN.items()]
    w = max(len(n) for n, _, _ in rows)
    lines += [f"  {n:<{w}}  {h}  [{m}]" for n, h, m in sorted(rows)]
    return "\n".join(lines)


def cmd_selfcheck(argv):
    """Runs tests/lander/test_types.py beside this package, then imports every present module. Prints the tally
    line check.sh reads: `lander selfcheck: N passed, M failed`."""
    import unittest
    here = os.path.join(os.path.dirname(PKG), "tests", "lander")
    suite = unittest.defaultTestLoader.discover(here, pattern="test_types.py", top_level_dir=here)
    res = unittest.TextTestRunner(stream=sys.stderr, verbosity=0).run(suite)
    n, bad = res.testsRun, len(res.failures) + len(res.errors)
    _, faults = collect(modules())
    for f in faults:
        print(f"lander selfcheck: FAIL {f}")
    n, bad = n + 1, bad + (1 if faults else 0)
    if res.testsRun == 0:
        print(f"lander selfcheck: FAIL no cases found under {here}")
        bad += 1
    print(f"lander selfcheck: {n - bad} passed, {bad} failed")
    return 1 if bad else 0


BUILTIN = {"selfcheck": (cmd_selfcheck, "the skeleton's own cases")}


def main(argv):
    if argv[:1] == ["selfcheck"]:   # never depends on another module importing cleanly
        return cmd_selfcheck(argv[1:])
    cmds, faults = collect(modules())
    for f in faults:
        print(f"lander: {f}", file=sys.stderr)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage(cmds))
        return 0 if argv else 2
    if argv[0] not in cmds:
        print(f"lander: no command {argv[0]!r} (lander --help lists them)", file=sys.stderr)
        return 2
    return int(cmds[argv[0]][0](argv[1:]) or 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
