You are reading the working conversation between the box `@BOX@` and its owner, and answering ONE question:

**what goes wrong REPEATEDLY?**

Not what went wrong once. A single bad day is noise. You are looking for the fault that has happened more than
once — usually under a different name each time, which is exactly why nobody has noticed it is one fault.

Your evidence is in `@EVIDENCE@` and it is all you have; read every file in it before you write anything:
Slack history per channel and the owner DM (`01`–`03`), the OWNER'S ASK LEDGER (`04-asks.json`, `05-asks-missed.txt`)
which records what he asked for and whether it was measured as delivered, the board (`06-`), the track journals
(`07-`), what the box pushed to him (`08-notify.log`) and what actually landed in git (`09-git-log.txt`).
`10-gaps.txt` says what could not be collected — respect it, and never assert something it tells you you cannot see.
Never read `~/.cc/config` or any other secret store. You have no network: everything is already on disk.

## the six signals, in the order they are worth reading for

1. **He asked twice.** The same request made again — reworded, or with "again", "still", "I already said", "as I
   said" — is the strongest signal in the corpus, because he only repeats himself when the first ask died.
2. **Reported done, was not.** The box said it landed; the ledger, the git log or his own next message says it did
   not. `04-asks.json` makes this mechanical: an ask at `delivered` that never reached `verified`, or one he
   reopened after the box closed it. Cross-check every claim of completion against `09-git-log.txt`.
3. **He corrected the box.** A message that begins by fixing something the box just said or did. Correction is
   expensive for him and he does not do it for fun — each one is a rule the box did not have or did not follow.
4. **A thread went unanswered.** He wrote, and there is no reply from the box after it. Note where you are inferring
   this from transcript order rather than seeing it (see `10-gaps.txt`) and say so.
5. **The same failure under different names.** Two incidents that were reported and fixed as separate bugs but share
   a cause — the same missing after-step, the same assumption that a write reached a reader, the same "it worked in
   the test". Merging these is the most useful thing you can do, and no one else in this pipeline can do it.
6. **A rule that had to be said more than once.** A standing instruction he has now given twice is a rule the system
   never enforced mechanically, and prompting harder will not fix it.

## what makes a pattern real

A pattern needs **at least two occurrences you can point at**, each with its date and a short quote. One occurrence
is an incident: put it under `## once, but expensive` if it was costly, and nowhere otherwise. Say how many times
you found it — the count is what makes the owner act. If a pattern is strong but you only have one instance, say
"1 instance" honestly rather than padding it. Do not infer a pattern from the absence of evidence.

Weigh recency: a fault last seen three weeks ago and fixed since is history, not a pattern. If the git log shows it
was fixed, say so and drop it.

## output

Markdown only, at most 70 lines. No preamble. This file is read by another model as evidence for an architecture
review, so every pattern must end in something a code reviewer can look for.

```
## patterns
- **PATTERN** <one line naming the fault as a fault, not as a story> — <N> instances.
  - evidence: <date> "<short quote>" · <date> "<short quote>"
  - cause, as far as the transcript shows: <one line — and "unclear from the transcript" is a legitimate answer>
  - where to look in the code: <the command or the seam a reviewer should open>

## once, but expensive
- **ONCE** <one line> — <date>, and why it would be worth preventing anyway.

## what is working
- <one line — something the box does reliably that the owner has never had to chase. Keep this short and true;
  it tells the architecture reviewer which parts NOT to redesign.>
```

Do not recommend fixes here — that is the next model's job, and it can see the code, which you cannot. Your job is
to name the fault precisely enough that it can go looking. Quote him rather than paraphrasing: his words carry the
severity, and a paraphrase loses it.

**The marker is literal.** Every pattern line starts with the word `PATTERN` in bold, exactly as shown, and
then the name of the fault. Do not replace the marker with the fault's name — the report counts `**PATTERN**`, and a
pass that renames it reports zero patterns found. Same for `**ONCE**`.
