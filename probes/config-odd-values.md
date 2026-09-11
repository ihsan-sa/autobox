model: haiku
target: cc-config set/get/unset/list with odd keys and values
turns: 25
---
The command is `cc-config` (no arguments prints the usage; the file is ~/.cc/config, mode 600, and the tool's
contract is that a value is a literal string end to end — the file is never sourced, so `$(…)` in a value is
just characters). Try:

1. `cc-config set K V` with a value of `$(echo pwned)`, one with a single quote, one with `=` in it, one with a
   leading space, one with a `#`, one that is empty, and one 10 000 characters long; read each back with
   `cc-config get K` and compare byte for byte (`cmp` or `diff <(…)`).
2. Keys: lowercase `foo`, `WITH SPACE`, `A=B`, an empty key, `-x`, a key with a newline.
3. `cc-config set` with a value that contains a newline — then `cc-config list` and `cc-config path`: is the
   file still one KEY=VALUE per line, and does `get` of a DIFFERENT key still work afterwards?
4. `cc-config unset` on a key that is not there (exit code?), and on a key set twice (`set A 1; set A 2` — list
   should show one line).
5. `cc-config get K default` when K is set but empty: the docstring says a SET variable wins even when empty.
   Also `K= cc-config get K filedefault` with K in the file.
6. `CC_CONFIG=/nonexistent/dir/config cc-config get A` and `… set A 1`.
7. `stat -c %a ~/.cc/config` after every set: still 600?

A finding is a value that does not round-trip, a file left with a broken line that breaks reads of other keys,
a mode that is not 600, or a traceback. A refusal that names the reason is fine.
