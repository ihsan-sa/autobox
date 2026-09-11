model: haiku
target: cc's argument parsing, without tmux
turns: 25
---
The command is `cc` (~/bin/cc; `sed -n 1,60p ~/bin/cc` is its usage). There is NO tmux here, so anything that
would open a session fails at tmux — that is expected and NOT a finding. What you are probing is everything
BEFORE that: how it reads its arguments and what it says when they are wrong. Try:

1. `cc --help`, `cc -h`, `cc help`, `cc --version`, `cc ""`, `cc -- fx`.
2. `cc nosuchrepo` and `cc nosuchrepo t1` — a repo with no ~/dev/<repo>: does it say so before touching tmux?
3. `cc fx` and `cc fx t1` — the fixture repo exists at ~/dev/fx; read the error: is it the tmux one, or
   something earlier that names the wrong cause?
4. `cc fx t1 --go` (no instruction), `cc fx t1 --go "" --loop x`, `--loop -1`, `--budget abc`, `--budget 1e9`,
   `--model ""`, an unknown flag `--frobnicate`, and the flags in the wrong order (`cc --go "x" fx t1`).
5. `cc fx 'a b'` (a track with a space), `cc fx ../x`, `cc fx -x`, `cc fx UPPER`.
6. `cc claim fx t1` (no --executor), `cc claim fx t1 --executor banana`, `cc claim fx nosuchrow --executor worker`.
7. `cc handoff` alone, `cc handoff fx`, `cc handoff --status`.
8. `cc board show fx` and `cc board nosuchverb` — the board passthrough.

A finding is a traceback, a usage line that does not match what the header says the arguments are, a bad value
that is accepted silently (a negative loop count, a non-numeric budget) and only fails later or not at all, or an
error that names the wrong cause. "tmux: no server" and its cousins are not findings.
