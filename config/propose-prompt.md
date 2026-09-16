You are writing the NEXT proposal for a loop that improves one program — `@FILE@`, the landing — by scoring
changes to it on a replay of real landings. The loop's shape is: you propose, the number decides. A person writes
neither the patch nor the verdict, so what you write here is tried as it stands.

READ, in this order, under the directory you are in:
1. `@LEDGER@` — every trial so far, one tab-separated line each: when, the proposal's name, the base it was tried
   on, the baseline's score line, the candidate's score line, keep or revert, the reason, the trace version. This
   is the record of what is already answered. Scores on different trace versions are not comparable.
2. `@TRIED@` — every proposal already tried, one heading each, holding its `why`: where the idea came from, the
   mechanism, what it was expected to move. Read it before you write yours. An idea the ledger has already answered
   is not a proposal, and neither is one of these ideas with a different constant.
3. `@READING@`
4. `@TARGET@` — the base landing itself, the exact text your patch must apply to. Read the code around whatever
   you are going to change, not only the line you change: a hunk lies about its surroundings.

YOU HAVE @TURNS@ TURNS AND $@BUDGET@, AND READING IS WHAT SPENDS THEM. Three runs in a row were cut mid-read
and wrote nothing, which costs the whole budget and buys no proposal. Read `@LEDGER@` and `@TRIED@` once each, the
reading you were given once each, and `@TARGET@` around the seam you mean to change rather than end to end. By
turn @READ_BY@ stop reading and answer, with the best proposal the reading you have done supports — a proposal
from partial reading is worth everything, and a run cut before it answers is worth nothing.

WHAT YOUR SOURCE IS. This proposal's source is **@SOURCE@**:
- `measurement` — the replay's own numbers and the ledger: a class of waiting or re-work the score lines show, that
  no tried proposal has answered.
- `outside` — an idea from outside this loop's own record: how other queues, schedulers or landing systems solve
  the class, applied to this code.
- `row` — something a person wrote down as a problem in the reading you were given.
Say which in the first line of your `why`, and name what in the reading it came from.

THE PATCH — the boundaries, which are not yours to move:
- It touches `@FILE@` and nothing else. One hunk where it can be; two only when one change genuinely needs them.
- It must be SCOREABLE BY THIS REPLAY: order, waiting and stops. A change to how fast a suite runs, to how good a
  review is, or to anything that reads a file's contents is invisible to the number — the replay answers those
  from the trace, so scoring it would prove nothing. The reading names what it cannot score; believe that list.
- It never edits a gate, a guard, an approval or permission rule, or anything about who may do what. A change that
  makes the landing merge something a person would have to approve is out, whatever it scores.
- It is a real change to behaviour, not a comment, a rename or a constant nudged by a tenth. The commonest verdict
  in the ledger is "the median did not move at all": a proposal has to be able to move minutes.
- It applies to the base as given. Build it by reading `@TARGET@` and writing a unified diff against it with
  `a/@FILE@` and `b/@FILE@` headers. The counts in the `@@` headers are recounted from each hunk's own body before
  it is applied, so do not spend turns counting them; the context lines are NOT forgiven, and every one must be
  the base's own text byte for byte with its leading space. A patch that does not apply is thrown away unscored.

THE RULE IT WILL BE JUDGED BY, fixed before you were asked and not bendable by anything you write:

@RULE@

Both arms are scored on the same pinned trace in one run, so the only difference between them is your patch.

ANSWER AS THE JSON OBJECT THE SCHEMA ASKS FOR, and nothing else:

- `name` — three to six words, lower case, hyphens, saying what the change DOES (`a-fresh-job-does-not-wait`), not
  what it hopes for. The loop puts its own number in front.
- `patch` — the unified diff, verbatim, nothing around it. No fence, no commentary.
- `why` — one paragraph a person can check the verdict against, in plain prose:
  the source (the first line), where the idea came from in the reading, the mechanism — what the landing does
  today and what it will do instead — what in the replay should move and by roughly how much, and WHAT MUST NOT
  MOVE: the thing that would make a faster number the wrong answer. Say what the number cannot see about this
  change, because a keep is a number and not permission: somebody reads this paragraph before it reaches anything
  real.
