# How a change lands

The lander takes a green PR from the queue to merged main and then to the running box. It is the `core/lander/`
package, run through `bin/lander`, and it always runs a **pinned release** (`~/.cc/lander/current`), never the
checkout. `bin/cc-land` is the old name kept as a thin shim, so every caller that still says `cc-land queue …`,
`cc-land record …` or `cc-land work` reaches the same verbs.

## The path of one PR

1. **Queue.** `lander queue <repo> <pr>` (or the owner's 👍 on a card, or `cc-loop` at a worker's end) drops a
   request into the inbox, `~/.cc/state/land/jobs/new/`, and starts a tick. The job file,
   `~/.cc/state/land/<repo>-<pr>.json`, appears once the tick takes it in. It keeps a `stage` key in the old
   lander's words, so the tools that only read it keep working.
2. **Plan.** The repo's manifest, `tests/LANDING.toml` read from the *base*, says which check owns which paths.
   The plan is the static checks, every check whose paths the change touches, and a changed tool's direct
   callers. A path no check owns widens to the manifest's `default` set, and the card names it. The path policy
   (`tests/LANDING-policy.toml`, also read from the base) says which paths need every check before the merge
   (`gate_first`), which need a paid review, and which only `lander-self` may land.
3. **Run.** Hermetic checks run in bwrap on the merge tree, with no network and no tokens. A red check is compared
   with the same check on the base: red there too means main is red, and the PR waits as `blocked-by-main` without
   blame. Box-class checks (the ones that need tmux, systemd or live state) run on main's tip after the merge.
   Under high load the box serializes rather than stalls: `core/lander/admission.py` (`overloaded()`) drops to one check
   at a time, not niced down, and `cc-room` holds new `--go` worker starts on the same signal so the queue that is
   already there keeps draining instead of growing. The lane checks PRs side by side, as many checks at once as
   the box has slots (three, or one while it is overloaded), and merges them one at a time; a PR that changes a
   file another PR in flight also changes waits for that one to merge first. A free slot goes to the small PR
   first, so a leaf or docs PR never waits for a whole suite (`core/lander/lane.py`, CHECKS RUN IN PARALLEL).
4. **Review.** A paid-review path with no recorded read at the change's digest gets one read. The verdict is
   `LAND` or `HANDBACK`, and a handback leaves the queue with the findings on the row.
5. **Merge.** One merge lane per repo, `--squash --match-head-commit`. The board row closes and the approval card
   turns to landed.
6. **Tip and deploy.** The tick runs the tip checks the merged range reaches, then deploys merged main target by
   target. A new unit that policy keeps for the owner stays off behind a 🔐 card whose 👍 runs the enable.

`lander times` reads the queue log. `lander plan <repo> <pr>` prints a plan without running anything.

## A worker's own green

`cc-green` runs `lander check <worktree>`: the same plan the landing would select, run the same way, so a worker
no longer waits on the whole suite. `core/tests/check.sh` and `selftest.sh` are still there, for the pre-commit
hook, CI and the manifest's own `check-sh` and e2e entries, but neither is a landing gate any more.

## Changing the lander itself

The lander refuses a PR that touches its own paths (the `lander` list in the policy file). Those go through
`lander-self`, a separate tool that shares no code with the package and runs from its own pinned copy:

- `lander-self check <repo> <pr>` needs a security read and one other read recorded at the head, every changed
  path on the `lander` list, the candidate's own tests green in bwrap, and a shadow plan over the live queue that
  plans every job the current release plans.
- `lander-self land <repo> <pr>` merges after that check. It does not switch releases.
- `lander-self promote [REV]` builds a release from committed code, runs its selfcheck, and only then points
  `current` at it, keeping the one before as `previous`. Each lane re-execs `current` between jobs, so nothing is
  killed.
- `lander-self shadow [REV]` prints the shadow plan on its own.

## Rolling back

- A bad release: `lander-self rollback` points `current` back at `previous`.
- Back to the lander from before the rebuild: `lander-self rollback --legacy` sends every `cc-land` call to the
  tree pinned by `lander-self legacy <rev>`, unchanged. The next `promote` clears it.

`lander-self status` says which release is current, which is previous, and whether the legacy switch is on.
