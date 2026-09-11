# Landing self-review — the six things the review keeps stopping PRs for

Read this against `git diff origin/<base>` before you call the work done, and FIX what it finds.
On 2026-09-01 the landing review stopped 6 of 11 PRs in a day and every stop was one of these six;
a stop costs a fix iteration, a re-review and a re-lane, all of which reading this diff yourself avoids.

1. **The contract says what the code now does.** Every rule, flag or subcommand the change adds is in
   the file's docstring / usage line — and every sentence the change made false is gone, not softened.
2. **Nothing new is unreachable.** Every subcommand, helper or option the change adds has a real caller.
   If nothing calls it, delete it; a caller you plan to write later is not a caller.
3. **Each selfcheck case stands on its own fixture.** It builds its own state, and it asserts BOTH the case
   that is kept and the case that is suppressed — never on state an earlier case happened to leave behind.
4. **No condition is inverted.** Quote the brief's own line in a comment beside the code that implements it
   and read the two together: a flipped `!`, a swapped operand or a negated default is the commonest stop.
5. **Compare at the resolution the source prints.** Minute-floored stamps compare as minutes, not seconds,
   and the current minute is a case with an answer — decide it deliberately, because the edge is where it breaks.
6. **A word a person set is never rewritten by a machine.** State a human chose (`waiting`, `kind=session`)
   is read by an automatic pass and reported on; it is not overwritten by one.

## And then the last thing you do: hand over a tree a suite has already passed on

Run `cc-green`. It takes the tree your working copy would commit and says, per gate, whether a green record
already exists for it; `cc-green run` runs the ones that do not, one run per worktree, into a log it names. The
landing then spends those records instead of running the ~22-minute suite again on its own queue, where it is the
slowest thing in the flow. A gate that long outlives a foreground tool call, so detach it — `setsid nohup cc-green
run >/dev/null 2>&1 &` — then `cc-green wait` until its exit is not 3 (still going), and read the log it names; a
background job that dies with your iteration leaves you with no run and no record.

**Fix everything above BEFORE that run, and edit nothing after it.** A doc fix, a comment, a rebuilt artefact —
each makes a tree nothing has passed on, and reasoning about how harmless it was does not change that. Of the 34
gate-landings inside one record window on 2026-09-07, 7 spent a record; 11 had run the gate green and then moved
between one and eight of their own files afterwards, one of them a docs edit its journal called harmless.
