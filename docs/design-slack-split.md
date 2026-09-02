# Splitting cc-slack

`bin/cc-slack` is one ~10k-line file: daemon, Home tab, members, approvals, post/inject, canvas,
and a 4k-line selfcheck. Six open PRs and four queued tracks touch it on one day, every one
serialised behind the last — the file, not the work, is the bottleneck. Split it into a package so
two tracks can land at once. Behaviour does not change; this is a move, not a rewrite.

## Layout

A python package beside the entrypoint — `core/lib/cc_slack/`, found by realpath, never linked.

| file | what | ~lines |
|---|---|---|
| `const.py` | paths, regexes, TTLs, emoji tables, `load_cfg`/`set_cfg`, `log` | 150 |
| `text.py` | mrkdwn, chunking, attachment folding (pure) + the `@`-mentions half, which is not: `user_handles`/`user_table`/`channel_member_ids` call the API and read/write `users.json` | 290 |
| `slack.py` | **adapters**: Web API, `post`/`react`/`upload`/`outbox`, `Effects`, the router socket `inject` rides | 210 |
| `targets.py` | **routing**: target ↔ channel ↔ tmux window, the two lanes, `routes.json`, orch channels | 290 |
| `store.py` | the JSON state files (marks, flags, last, canvases, provisioned) and their locking | 125 |
| `home.py` | **Home tab renderer**: one state dict → blocks. Pure, and the easiest to test | 910 |
| `members.py` | member workspaces: provisioning, the per-member channel, the facing marker | 310 |
| `channels.py` | create/join/lane/inherit/archive a channel | 260 |
| `approvals.py` | the `#approvals` card, its sweep, and the 👍 → land path | 300 |
| `daemon.py` | `Conn` + `Daemon`: routing, events, marks, cycles | 2250 |
| `channel.py` | the stdio MCP channel server claude spawns per session | 290 |
| `cli.py` | the verb table and the one-shot commands (`inject`, status, history, edit, pin, canvas, manifest) | 530 |
| `selfcheck/` | the harness plus one module per band | 4000 |

`daemon.py` stays large on purpose: cutting a class is a behaviour risk, not a file move. A later
pass lifts the mark/thread state machine (`root_mark` … `reconcile_reactions`, ~700 lines) into
`marks.py`; nothing here depends on that happening.

## What stays in the entrypoint

`bin/cc-slack` keeps its shebang, its docstring — that docstring *is* the help text and the
selftest greps it — the venv/`lib` `sys.path` bootstrap, and a `main()` that calls `cli.main`.
Under 200 lines, and frozen after step 1 so no track has to rebase on it.

## The one hazard: the flat namespace

The selfcheck fakes Slack by writing into module globals — `globals()["api"] = fake`, 264 times.
That works only while there is one namespace. In a package, a module that did
`from .slack import api` binds its own name and the fake silently misses: the tests go green
having tested nothing, or reach the real API.

**The rule, in every module: import the module, call through it.** `from . import slack` then
`slack.api(...)`. Attribute lookup is late, so `slack.api = fake` is seen by every caller. Never
`from X import <name>` — constants included, no exceptions: the selfcheck patches "constants"
~30 times (`DIR`, `HOME`, `DEV`, `HANDOFF_DIR`, `VITALS_DIR`, `QUICK_LOG`, `RAPL`, `SELF*`), and a
module that had bound one with `from .const import DIR` would make those patches silently miss —
the lock/outbox checks would then flock the box's real `~/.cc/slack/` files and fight the live
daemon. `Effects.install()` rebinds `DEV` as well as `EFFECTS`, so it must write the attribute on
the module that owns `DEV`, never its own globals. Shell-outs already have the
better version of this seam (`EFFECTS.run_impl`); the selfcheck grows one `patch(mod, name, val)`
helper that restores on exit, and each move rewrites only its own band's patch sites.

## Guards, install, tests

- **cc-guard matches command text**, not a path: `[^ ]*cc-slack +(inject|post|post-approval)` and
  the re-wiring rule. So **no module may become a second entrypoint** — `python -m cc_slack.post`
  would post with the guard blind. Nothing under `lib/` gets a shebang, an executable bit or a
  `__main__.py`, and a new selftest case asserts exactly that. The guard rules themselves need no
  edit, which is the point of keeping one binary.
- **install.sh needs no change**: it links executables under `bin/` only, so `lib/` is never
  linked and never should be. The package is found through the entrypoint's own realpath (`ROOT`
  already resolves the `~/bin` symlink). The invariant this rests on: the entrypoint may be
  symlinked anywhere, never *copied* out of its tree.
- **check.sh** compiles `bin/*` only — step 1 adds `lib/cc_slack/**/*.py` to its list, or nothing
  in the package is ever syntax-checked. `cc-audit`'s slack file list gains it too.
- **The self-source checks scan the whole package, not `__file__`.** The selfcheck reads its own
  source and asserts the merge verbs and `--auto` appear nowhere — the fence keeping a second
  merge path out of cc-slack. Split into `selfcheck/`, `__file__` is one selfcheck module and the
  check passes vacuously while `approvals.py` or `daemon.py` could carry a merge past cc-land's
  gates. The step that moves `selfcheck/` re-points that read at every file under `lib/cc_slack/`
  plus the entrypoint; this is a check that may not be weakened.
- **The selftest execs the binary** (`selfcheck`, `channel`, `inject`, the help greps) and its
  member/notify stubs replace it with a shell script — both keep working untouched. `ln -sf` to a
  per-run name still resolves. `__pycache__/` is already ignored.
- **`Channel.stale()` compares the entrypoint's mtime**, so after the split a deploy that changes
  only a module would leave every live channel server on old code — the 2026-08-31 incident shape
  (a retired session posting past a mute deployed hours earlier). The hazard opens at the FIRST
  module move and steps 4-5 make module-only deploys the normal case, so it is fixed in step 1,
  before anything moves: newest mtime across the entrypoint and every file under `lib/cc_slack/`.
- `core/` may not name this box — the identity gate refuses the publish rather than trim.

## Migration order

Each step is one PR: move the band, rewrite that band's patch sites, `check.sh` +
`tests/selftest.sh` + `cc-slack selfcheck` green before it lands. No step needs the next one.

1. **Scaffold, nothing moves.** Create the package, the bootstrap, the `patch()` helper; add the
   package to check.sh and cc-audit; add the not-executable selftest case; widen `Channel.stale()`
   to the newest mtime across the entrypoint and everything under `lib/cc_slack/`.
2. `const.py`, then the pure half of `text.py` (mrkdwn, chunking, attachment folding) — leaves,
   no callers to invert yet. The `@`-mentions half stays: it calls `api`, which at this step still
   lives in the un-importable entrypoint (no `.py`, a hyphen), so moving it raises `NameError: api`
   on the first `@handle` post and the mention tests would be patching an `api` the module cannot see.
3. `slack.py`, then the `@`-mentions half of `text.py` (`user_handles`, `user_table`,
   `channel_member_ids`, `linkify_mentions`). The big patch surface (`api` alone is ~100 sites),
   but purely mechanical.
4. `home.py` — pure, and touches nothing in 3. **Runs in parallel with it.**
5. `targets.py` + `store.py`.
6. `channels.py`, then `members.py` (which uses it), then `approvals.py`. Three PRs, sequential.
7. `daemon.py`, then `channel.py` (with the staleness fix), then `cli.py`; the entrypoint shrinks.
8. `selfcheck/` splits by band — one PR per band, and from here on any two are independent.

Steps 4 and 5 can run beside 3. Everything before 7 can be paused indefinitely: a half-migrated
file is still one working binary.

## Who owns what

One track per module, for the life of that track. The only shared files are `const.py` —
append-only, add a constant, never re-flow — and the entrypoint, frozen after step 1. A track that
needs a second module says so on the board and takes both, or waits.

| track | files |
|---|---|
| the mover | whichever module its step names, plus that band's selfcheck cases |
| home-tab work | `home.py`, `selfcheck/home.py` |
| members / approvals | `members.py` + `channels.py` · `approvals.py`, and their selfcheck bands |
| daemon/routing work | `daemon.py`, `targets.py`, `store.py` |

Two tracks writing different selfcheck bands is the case that matters most: today every one of
them edits the same 4k-line function.

## Open risks

- A mechanical move still reorders imports and can change import-time side effects. The selfcheck
  is the only thing standing between this plan and a silent regression — treat a step that needs
  the selfcheck *weakened* as a step that has gone wrong.
- Steps 2–6 leave a mixed file, and a PR opened before a step and merged after it rebases badly.
  Land the moves on quiet days, or ask the queued tracks to rebase first.
- 13 files is more places to look. The docstring in the entrypoint stays the one index.
