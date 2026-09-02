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
