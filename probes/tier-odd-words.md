model: haiku
target: cc-tier set/allows/line with odd words and a missing config
turns: 20
---
The command is `cc-tier` (the header of ~/bin/cc-tier says what each tier allows; it reads CC_SPEND_TIER through
cc-config from ~/.cc/config — the fixture's). Try:

1. `cc-tier set` with `STOP`, `Stop `, `essential ` (trailing space), `moderate\n`, `off`, an empty string, and
   `autonomous`. After each: `cc-tier` (one word) and `cc-tier line` — do the two agree, and does the file hold
   a word the tool would accept back?
2. `cc-tier allows` with no argument, with `start`, with `START`, with `start fx/t1`, with `start t1` (no slash),
   with `start fx/nosuchrow`, with `explore` under each tier. Exit codes: the header says 0 allowed, 1 wait, 2 usage.
3. Under `essential`: `cc board set fx t1 critical yes` (or `cc-board set …`) then `cc-tier allows start fx/t1`;
   then mark t2 running (`cc-board status fx t2 running` — it already is) and ask again: "one at a time" is read
   off the boards.
4. `CC_SPEND_TIER=banana cc-tier` and `CC_SPEND_TIER= cc-tier` (empty — the environment wins even when empty).
5. `cc-config unset CC_SPEND_TIER` then `cc-tier` and `cc-tier line`: the default is autonomous — is it printed
   as one, and does `line` say since when without a stamp to read?

A finding is a tier word accepted that the tool then cannot read back, `cc-tier` and `cc-tier line` disagreeing,
an exit code other than the three the header names, or a traceback.
