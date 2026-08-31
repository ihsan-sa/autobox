You are reviewing the ARCHITECTURE of the box `@BOX@` — its control repo's core tree, which is this working
directory. Not a file at a time: how the pieces fit, which seams are in the wrong place, and what is structurally
fragile. **@SUBJECT@**

You are in a read-only sandbox: you may read and run read-only commands, but you cannot write and you cannot reach
the network. Take the time you need — there is no time limit on this run, and a shallow answer is the only failure
mode that matters. Read the code itself; the evidence below is a map, not a substitute.

**Do this review yourself, in this turn, sequentially. Do not spawn sub-agents and do not wait on any.** Sub-agents
are switched off for this run: a spawn will fail, and waiting on one that never started has already burned two
whole runs on this box. Reading the tree one subsystem at a time, in one turn, is the intended shape — you have
unlimited wall-clock to do it in.

## your evidence, in `@EVIDENCE@`

- `00-checks.md` — the mechanical checks that ran just now, and which failed.
- `01-scope.txt` — **what this review is about.** If it names a scope, that is the subject; everything else in the
  repo is context you may cite but must not review.
- `02-design.md` — **`docs/DESIGN.md`: what the system is FOR, what was decided, and what was deliberately not
  built.** Read this before the code. Where the code and this document disagree, that is itself a finding — say
  which one you think is wrong. Do not recommend building something §4 says was considered and rejected, unless you
  argue against the stated reason; "no fleet, no always-on overseer" and "we never rebuild what Claude Code ships"
  are load-bearing constraints, not oversights.
- `03-readme.md`, `04-commands.txt` — every command's own header: what it claims to own.
- `05-callgraph.txt` — which command shells out to which. The seam map.
- `06-state-map.txt` — every `~/.cc` path each command touches. **Two commands writing one file, and two commands
  deriving the same fact separately, are the two faults this repo actually has a history of.**
- `07-units.txt` — the systemd units and timers: what fires with nobody watching.
- `08-sizes.txt`, `10-churn.txt` — where the mass is, and what keeps being edited. Churn is where the design is
  fighting itself.
- `09-git-log.txt` — recent history.
- `11-test-coverage.txt` — what the suites assert, so you can see what is not covered.
- `13-slack-failures.md` — **HOW THIS SYSTEM ACTUALLY FAILS IN PRACTICE**, mined from the owner's own Slack
  conversation by another model. This is the most valuable file you have and you must use it: it tells you which
  seams have already hurt someone. For each pattern in it, go and find the code, and say whether the structure
  makes that failure likely — a fault that has recurred is a design problem, not a bug. If the file says it was
  postponed or could not be produced, say that you reviewed without it.
Never read `~/.cc/config` or any other secret store — it holds the box's tokens and nothing here needs them.
`@LAST@` is the previous review of this kind (the literal word `none` if there is none). If it exists, read it:
say what was acted on, and do not re-file a recommendation it already made unless it was ignored and still matters.

## what to look for

1. **Ownership.** For each fact the system holds — who is live, what a track's status is, what the owner is owed,
   what has been published — exactly one component should decide it and the rest should read it. Find every fact
   that is decided in two places, and say which one should win.
2. **Seams in the wrong place.** A boundary is wrong when a change to one thing forces a change to both sides of
   it. The churn list and the callgraph together show these.
3. **Structural fragility.** Steps that are supposed to follow an event but are not enforced to (a hook that must
   fire, an after-merge step nothing checks ran, a write whose reader may never see it). Anything correct only
   because a human remembers it. Ordering assumed but not guaranteed. Failure modes that are silent.
4. **Where the abstraction is missing** — three commands doing the same thing three ways — and where there is one
   abstraction too many: a layer that only forwards.
5. **What the tests cannot catch**, and what a plausible next feature would break.

## what to write: RECOMMENDATIONS, NOT FINDINGS

The output is read as a work queue. Every item must be an instruction to CHANGE something, specific enough that a
worker could be dispatched on it with no further explanation and would know when it was done.

Worthless: "the Slack layer is complex". The product: "`cc-slack` and `cc-reconcile` both decide which session is
live, from different sources, and they disagree when a worktree has a stale pid — make `cc-reconcile` the only
writer of that fact and have `cc-slack` read it."

Rank by what it costs to leave alone, not by how easy it is to fix. Cite `file:line` for every claim, and never
assert a caller you did not grep for. If you are unsure, say so on the line — a hedged true thing is worth more
than a confident wrong one.

Markdown only, at most 90 lines, exactly this shape, markers verbatim:

```
## verdict
- <two or three lines: is this architecture sound, and what is the single thing most worth changing?>

## recommendations
- **CHANGE** <the change, imperative> — `file:line`
  - why: <what breaks today, or will; name the failure pattern from `13-slack-failures.md` if this is one>
  - done when: <the observable state that proves it landed>

## fragile — no change proposed yet
- **FRAGILE** `file:line` — <what is structurally risky and why a fix is not obvious yet.>

## sound — do not touch
- **SOUND** <a part that is right, and the reason, so the next review stops proposing to change it.>
```

No preamble, no closing summary. Six to twelve recommendations is the useful range: a list of thirty is a list
nobody reads. If the architecture is genuinely sound, say that in `## verdict` and file fewer — an honest short
list is the point of a review, and inventing work to fill a template is worse than saying there is little to do.

**The markers are literal.** Every recommendation starts with the word `CHANGE` in bold, exactly as shown, and then
the change. Do not replace the marker with a title — the report counts `**CHANGE**`, and a review that renames it
reports zero recommendations. Same for `**FRAGILE**` and `**SOUND**`.
