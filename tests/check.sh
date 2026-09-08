#!/usr/bin/env bash
# tests/check.sh — static checks over core/. bin/ and config/ are LIVE via symlinks: run before committing on
# the default branch (the pre-commit hook does). Extra python files to compile can be passed as arguments
# (a private overlay adds its own that way).
# WALL CLOCK (measured 2026-09-08, docs/2026-09-08-gate-profile.md): the tools' own selfchecks are about two
# thirds of this gate and shellcheck is most of the rest. Both now run CC_CHECK_JOBS at a time (default 4; 1 is
# one at a time, the old behaviour). Concurrency only: every file is still shellchecked and every selfcheck still
# runs, each judged in the same order by the same rules — nothing here is skipped to make the gate faster.
set -e; SELF=$(readlink -f "$0"); cd "$(dirname "$0")/.."   # $0 is resolved BEFORE the cd moves out from under it
sh=(); py=()
for f in bin/* install.sh ccbox/*.sh; do [ -f "$f" ] || continue; head -1 "$f" | grep -q bash && sh+=("$f"); head -1 "$f" | grep -q python && py+=("$f"); done
JOBS=${CC_CHECK_JOBS:-4}   # how many of this gate's own jobs run at once. Concurrency, never coverage.
GD=$(mktemp -d "${TMPDIR:-/tmp}/cc-check.XXXXXX"); trap 'rm -rf "$GD"' EXIT   # one scratch dir, one trap, both blocks
bash -n "${sh[@]}"
# SHELLCHECK EVERY FILE, $JOBS AT A TIME. One call over all of bin/ was 38 s of this gate on one core — the largest
# block after the selfchecks. Splitting it changes no file's report: -e SC1090 already forbids following a `source`,
# so shellcheck never read one of these files while checking another, and the only thing the single call added was a
# single exit code. Each file's report is kept whole in a file of its own and printed BELOW IN LIST ORDER, so a red
# gate reads the way it always did instead of four processes interleaving mid-finding. `rc=0 … || rc=$?` is not
# decoration: `set -e` is on and inherited by these subshells, so without it a file WITH a finding would die before
# writing its rc, and the loop below would call that the killed-job case instead of the finding it is.
nsh=0
for f in "${sh[@]}"; do
  { rc=0; shellcheck -S warning -e SC1090,SC1010 "$f" > "$GD/sc.$nsh.out" 2>&1 || rc=$?; echo "$rc" > "$GD/sc.$nsh.rc"; } &
  nsh=$((nsh + 1)); [ "$((nsh % JOBS))" -ne 0 ] || wait
done
wait
scrc=0
for i in $(seq 0 $((nsh - 1))); do
  [ -f "$GD/sc.$i.rc" ] || { echo "check.sh: shellcheck of ${sh[$i]} was started and left no result — it was killed,"
                             echo "  or it died before it could report. Nothing here passed."; exit 1; }
  cat "$GD/sc.$i.out"; [ "$(cat "$GD/sc.$i.rc")" = 0 ] || scrc=1
done
[ "$scrc" = 0 ] || exit 1
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile "${py[@]}" tests/slack_sim.py tests/member_v2.py tests/member_broker.py tests/member_import.py "$@"
for f in slack/*.json config/claude-settings.json config/units.json config/claude-managed.json; do jq -e . "$f" >/dev/null; done
# the agent types (templates/home/agents/ -> ~/.claude/agents/). Nothing else reads these files: a frontmatter the
# harness rejects takes out every spawn of that type at dispatch time, with no earlier signal. install.sh's own case
# in selftest.sh checks that the installed copies match; this checks the templates are loadable in the first place.
KNOWN_TOOLS="Bash BashOutput Edit Glob Grep KillShell NotebookEdit Read SlashCommand Task TodoWrite WebFetch WebSearch Write"
for f in templates/home/agents/*.md; do
  [ -f "$f" ] || { echo "templates/home/agents/: no agent types — install.sh and docs/WORKING.md expect them"; exit 1; }
  n="$(basename "$f" .md)"; [ "$(head -1 "$f")" = "---" ] || { echo "$f: no YAML frontmatter"; exit 1; }
  h="$(sed -n '2,/^---$/p' "$f")"
  grep -qx "name: $n" <<<"$h" || { echo "$f: frontmatter 'name' must be '$n' (the harness spawns by it)"; exit 1; }
  grep -q '^description: .' <<<"$h" || { echo "$f: frontmatter needs a 'description' — it is what picks the type"; exit 1; }
  grep -qE '^model: (opus|sonnet|haiku|inherit)$' <<<"$h" || { echo "$f: frontmatter needs 'model: opus|sonnet|haiku|inherit'"; exit 1; }
  # `tools` is the type's reach. A name the harness does not know is dropped in silence, so a review type asking for
  # Grep and getting nothing looks like a quiet agent, not a broken file. No key at all means every tool: fine for a
  # builder, wrong for a *reviewer, which must not be able to write — so that one states its list, without Write/Edit.
  t="$(sed -n 's/^tools: *//p' <<<"$h" | tr -d ' ')"
  for x in ${t//,/ }; do
    case " $KNOWN_TOOLS " in *" $x "*) ;; *) echo "$f: 'tools' names $x, which is not a tool the harness has"; exit 1;; esac
  done
  case "$n" in *reviewer)
    [ -n "$t" ] || { echo "$f: a review type must list its 'tools' — with no key it gets every tool, Write and Edit included"; exit 1; }
    case ",$t," in *,Write,*|*,Edit,*) echo "$f: a review type must not list Write or Edit — it reads a diff, it does not fix it"; exit 1;; esac;;
  esac
done
H=$(mktemp -d); ln -s "$PWD/bin" "$H/bin"   # verify the units against THIS tree's bin/, not against what the box happens to have linked
v=$(HOME="$H" systemd-analyze --user verify config/systemd-user/*.service config/systemd-user/*.timer 2>&1 | grep -v '^\s*$' || true); rm -rf "$H"
[ -z "$v" ] || { echo "$v"; exit 1; }
# A unit nobody links is a unit that never runs. install.sh used to name each one, so this test grepped it; now
# config/units.json is the one list and `cc-units selfcheck` fails when it and config/systemd-user/ disagree in
# either direction — a new unit file without a row, or a row without a file. Both selfchecks are static: they read
# this tree and their own fixtures, never live systemd and never ~/.claude/settings.json.
# cc-board's is the same shape: the default board view's filter, and the one-authority rule for the brief, both
# against its own fixtures in a HOME of its own — never this box's board.
# cc-config's is the same: its own config file in a temp dir, never this box's — precedence, locking, and the
# one that matters, that a value like $(…) is read back as those characters and executes nothing.
# cc-msg's runs a whole fake box — its own HOME, a stub tmux whose pane text is a file, a stub ps — over the
# prompts it may answer, the ones it must never touch, and the spool: no tmux of this box's is read or typed at.
# cc-spend's ticks a synthetic transcript in a HOME of its own: the rates table, the offset/dedupe rules and both
# phantom rules, never this box's ledger and never a model.
# cc-econ's is fixtures of its own — a fake landing log, fake run files, a throwaway git repo — over the two
# splits that decide every number it prints: worker vs fix round, and which population a dollar belongs to.
# cc-time's is the clock rule itself: a known UTC instant rendered in a zone of its own (never this box's), and
# cc-notify's one Slack-facing stamp driven through in log-only mode with the UTC log line beside it.
# cc-watch's is fixtures too — a process table in a file, a queue log and a `gh` of its own in a temp HOME — over
# the false alarms its two watches were rebuilt four times to stop: a landing keyed on repo+PR and not on pid,
# gone only after two consecutive polls and confirmed with gh, a duplicate loop that has to survive two polls,
# and a headless run reported by pid and cwd with never a word of its argv. No process of this box's is read,
# nothing is killed, and no PR anywhere is asked about.
# cc-broker's runs the classifier, the grouping and the debounce against a stub for the daemon's door in a HOME
# of its own: no session on this box is written to, and no message of this box's is read.
# cc-guard's runs the gates themselves against fixtures in a HOME of its own, with the owner's two real
# doors (cc-notify, cc-slack) stubbed: which denies page and which never do, and the worker kill fence.
# cc-pause's builds a whole box per case under a HOME of its own — two projects, a stub `cc` and a stub `cc-loop`
# — over pause, resume and the cold start a reboot is: the flag is a file, so a fresh process with no memory of
# the pause still reads it. Its fixture projects carry this process's pid in their names, because `on` finds the
# loops to stop with pgrep over the whole process table and a shared name would signal a real project's worker.
# cc-brief's is fixtures too — briefs it writes itself, a board and a throwaway git repo under a temp dir, and
# CC_BRIEF_FAKE standing in for the judge's verdict, or a fake `claude` of its own where the CALL is what is
# being pinned (the turn cap, the wall it carries), so the fast gate never reaches a model.
# cc-gh-token's mints against an API of its own on localhost, signing with an RSA key it generates: minting,
# reuse, the expiry margin, an absent key and which remotes it answers for — and, over a ~/dev of member
# workspaces it builds itself, which repositories a workspace owns, that its token is minted for those alone
# and for no other workspace's, that creating one wires it up, and that `default` moves a repository's default
# branch to the base and refuses a track. No GitHub App of this box's is read,
# nothing leaves the machine, no repository is created anywhere (the create endpoint is the fixture's too),
# and its token caches are files under the temp dir, never the real ones.
# cc-checkpoint's is the rule that decides WHERE a track pushes, which branch the repository it makes opens on, and
# which repositories a project's branch is taken back out of,
# over workspaces, projects and bare repos it builds in a HOME and temp dir of its own, with
# a cc-gh-token that records what it was asked to create instead of creating it: no repository of this box's is
# read, nothing is created anywhere, and the only branches pushed or deleted are in those fixtures.
# cc-publish's is the repo lock and nothing else: in a fixture repo with its own origin and public repo under a
# temp HOME, that the file it locks is the one cc-land's own git_lock_path names — for a checkout, a linked
# worktree and a directory with no .git — and that its fetch waits while a landing holds it. Nothing of this
# box's is fetched and the public repo is never reached: it publishes into a bare repo in the temp dir.
# …and that it gives cc-arch its turn after a push and not otherwise, against a stub that records its argv, and
# that the turn it allows covers cc-arch's own worst case and sits inside this unit's — both read out of the
# files rather than written down twice.
# cc-arch's own is fixtures too — its own HOME with its own repos and remotes under it and a stub `cc-slack` that
# records instead of uploading — over the one promise: a landing posts the rebuilt overview only where the commit
# that landed DECLARED itself an architecture revision, including the landing that rewrote the source and said
# nothing. It runs the real pdflatex, on a one-page document of its own and once on the overview source in this
# tree, which is how a document that stopped building fails here rather than on the morning the box has something
# to say; those cases are SKIPPED with a line, never failed, where pdflatex is not installed. Nothing leaves the
# machine, nothing outside its temp HOME is written, and a link planted where it writes is a case of its own.
# cc-fence's is the only one that runs its cases against the KERNEL: private fixtures, and every forbidden
# operation run three times — unfenced (so a case that stopped testing anything is caught), fenced outside the
# task tree, fenced inside it. Nothing of this box's is written. cc-member-v2 applies the fence, behind
# CC_MEMBER_V2=1, off by default and selected by no live session — its own cases run under cc-sandbox's. On a
# kernel that cannot carry the profile it exits 77 and this loop reports it as skipped, not passed.
# cc-voice's builds a box of its own — a fake venv whose python prints a transcript, a fake `claude`, a fake
# recording — over the two halves of a memo: no weights are downloaded, no model is called, no ~/.cc is read.
# cc-steward's is fixtures too — two events cc-broker would deliver, a stub model answering with a fixture verdict
# and a stub for every `cc-*` a chain calls — over the one thing it promises: one event in, ONE command out, and a
# line that needs a person refused before any model is asked. No model is called, nothing is sent, and no chain
# leaves its temp dir.
# cc-task's is the claim rule itself, in a HOME, state dir, board and git repo of its own: that one task id
# survives a release, a change of executor and a new owner, that two processes racing for a row leave one winner,
# and that a claim is never taken while its owner is alive. No board of this box's is read and no runtime is run.
# cc-native's drives dispatch, bootstrap and end payloads concurrently in its own HOME, board and local Git
# remotes, with off and refusal controls. No live runtime or service is used and no settings are applied.
# cc-green's is throwaway git repos with STUB gates and a record directory of its own — never this box's records
# and never a real suite: a green run, then one tracked file edited after it, and the record must stop answering.
# It also reads cc-land's GATES tuple out of that source, because a gate list it has fallen behind on is a worker
# told it is green on a gate the landing is still going to run.
# cc-evals', cc-model's and cc-vitals' are the three no suite in this tree had ever named, found by the discovery
# below rather than by anyone remembering them: cc-evals runs fixture cases in a temp dir with CC_EVALS_CLAUDE
# pointed at a fake binary, so it spends nothing and reaches no model; cc-model drives its classifier and its chain
# over stub transcripts of its own, with no network and no tmux; cc-vitals stubs the system resolver and git and
# writes nothing outside its own temp dir. Their cases were in the repository and run by nobody until this loop
# stopped asking a list.
# …and only the ones a change reaches, when the landing says what changed (CC_LAND_CHANGED — tests/green.sh has
# the rule): the static checks above run whatever the change, a selfcheck of a tool nothing here touched does not.
# cc-board's is the exception and runs whenever any tool changed — one of its cases reads all the others.
. tests/green.sh; land_scope "$PWD/bin"; skipped=""
# THE TALLY SHAPE, read exactly the way selftest.sh's chk() reads it: the tool's OWN line, found by name, with the
# count anchored so that "10 failed" is never mistaken for a zero. A selfcheck that ends in any other shape —
# "28/28", "all passed" — is green here and unreadable there, and chk() reports an unreadable tally the way it
# reports a selfcheck that DIED. That is how a cc-native with 28 of 28 cases passing came back as a red selftest
# (2026-09-07): a one-line formatting mistake, found by reading the log and then chk() itself. This loop already
# has the output in hand, so it is the place that can say which tool and which shape. Fix the tool, not chk().
tally_line(){ grep -o "$1 selfcheck: .*" <<<"$2" | tail -1; }
tally_ok(){ grep -qE '(: |, )0 failed' <<<"$(tally_line "$1" "$2")"; }
# CONTROL: the two greps above are a copy of chk()'s, and a copy that stopped discriminating would pass every tool
# in silence. These are the shapes that matter, including the two that have actually been written by mistake.
tally_ok x "x selfcheck: 12 passed, 0 failed" && tally_ok x "x selfcheck: 0 failed" \
  && ! tally_ok x "x selfcheck: 28/28" && ! tally_ok x "x selfcheck: all passed" \
  && ! tally_ok x "x selfcheck: 4 passed, 10 failed" && ! tally_ok x "ran 12 cases, none failed" \
  || { echo "check.sh: the tally-shape rule no longer tells a readable tally from an unreadable one"; exit 1; }
# RUN THEM AT ONCE, JUDGE THEM IN ORDER. Every selfcheck here is hermetic by construction — its own HOME, its own
# temp dir, its own fixtures, reading nothing of this box's (that is what the paragraphs above each promise) — so
# nothing makes them a queue except that they were written as one. Serially they were the largest block in this
# gate: every tool that ships one, on one core, on a gate that runs for every PR. They are started $JOBS at a time and each
# one's output is kept whole in a file of its own; the verdict loop below then reads them back IN THE ORDER THEY
# WERE STARTED, so what this prints, and which tool it stops on, is exactly what it printed and stopped on serially.
# Nothing is judged in the background: a case's rc and output are only read here, by the same three rules.
#
# WHICH TOOLS THOSE ARE IS ASKED OF THE TREE, NOT OF A LIST. A line of names kept by hand was wrong in two
# directions at once. Three branches in one day each wanted to edit it, and one line makes every collision a
# whole-line conflict; worse, while it was held, cc-sense's 36 cases and cc's 14 sat in the repository run by
# nobody, and cc-evals, cc-model and cc-vitals had never been named by a suite here at all. A tool's selfcheck now
# runs because the tool exists. A tool that ships none is not a failure and is named below so its absence stays
# visible; a selfcheck that exists and nothing runs cannot happen, which is why this reads bin/ instead of a list.
ships_selfcheck(){   # bin/<tool> -> 0 when that file implements `<tool> selfcheck`
  # The tally line it has to print (the shape judged below), or `selfcheck` as an arm of its own dispatch, in the
  # shapes this tree writes it: a shell case arm, a shell test, python's argv compare, a dict key, argparse, a
  # cmd_selfcheck. A false positive here is LOUD — the run fails on `bin/<tool> selfcheck` — and never silent,
  # which is the direction a discovery has to err in, and a shape none of these catch is caught below instead.
  grep -qF "${1##*/} selfcheck:" "$1" ||
    grep -qE 'selfcheck\)|"selfcheck":|== *\[?"selfcheck"\]?|add_parser\("selfcheck"|def cmd_selfcheck|= *"?selfcheck"?( *\]|$)' "$1"; }
runs_selfcheck(){   # <file> <tool> -> 0 when <file> already runs `<tool> selfcheck`
  # Some selfchecks have a home of their own and must not run twice: a stanza in tests/selftest.sh that builds
  # fixtures first (cc-pulse's, and cc-scope's in the ask-ledger stanza), or another tool's selfcheck driving it
  # (cc-sandbox runs cc-member-v2's inside its own canary gate). Both are read out of the file that runs them, in
  # the two shapes they are written in: the suite's `chk`/`prefetch` lines, and a `<path>/<tool> selfcheck` call.
  grep -qE "/$2[\"'] +selfcheck([^A-Za-z0-9_-]|\$)|^(chk|prefetch)( +[A-Za-z0-9_-]+)* +$2( |\$)" "$1"; }
discover_selfchecks(){   # <bin dir> <suite> <tools that run here whatever else runs them>
  # -> FOUND (ships one) · HERE (this gate runs it) · ELSEWHERE (the tool, or tool(runner) when the runner is not
  # the suite) · NOSC (ships none). ONE HOP FROM THE SUITE AND NO FURTHER: a chain of tools allowed to claim each
  # other could claim its way out of running at all — two tools each naming the other would leave both unrun and
  # this loop none the wiser — so a claim has to reach the suite, which is the root nothing claims.
  local b=$1 s=$2 always=${3//$'\n'/ } f t x by suite=""   # the always set is written one name per line; match on words
  FOUND=""; HERE=""; ELSEWHERE=""; NOSC=""
  for f in "$b"/*; do [ -f "$f" ] || continue
    if ships_selfcheck "$f"; then FOUND="$FOUND ${f##*/}"; else NOSC="$NOSC ${f##*/}"; fi; done
  for t in $FOUND; do if [ -f "$s" ] && runs_selfcheck "$s" "$t"; then suite="$suite $t"; fi; done
  for t in $FOUND; do
    case " $always " in *" $t "*) HERE="$HERE $t"; continue;; esac
    by=""
    case " $suite " in *" $t "*) by=${s##*/};; *)
      for x in $suite; do if [ -f "$b/$x" ] && runs_selfcheck "$b/$x" "$t"; then by=$x; break; fi; done;; esac
    if   [ -z "$by" ];               then HERE="$HERE $t"
    elif [ "$by" = "${s##*/}" ];     then ELSEWHERE="$ELSEWHERE $t"
    else                                  ELSEWHERE="$ELSEWHERE $t($by)"; fi
  done; }
# AND THE FALSE NEGATIVE THIS CANNOT AFFORD. A tool whose dispatch is written in a shape ships_selfcheck() does not
# know lands in NOSC and is reported as shipping none — the silent skip this whole block exists to end, wearing the
# words of a clean answer. So every file called NOSC is read once more for the word at all: a tool that never says
# "selfcheck" ships none, and one that says it where the rules above see no dispatch stops this gate until a person
# has looked. That is #310's rule — what cannot be measured stays red, it never becomes a quiet skip.
nosc_says_selfcheck(){   # <bin dir> <the NOSC set> -> 1, and the reason, on the first file that says it with no dispatch
  local b=$1 t
  for t in $2; do grep -qi selfcheck "$b/$t" || continue
    echo "check.sh: $b/$t says 'selfcheck', but the discovery above sees no way to dispatch one, so nothing would"
    echo "  ever run it. Teach ships_selfcheck() that dispatch shape, or take the word out of the file."
    return 1; done; return 0; }
# CONTROL: a discovery that stopped discriminating would run nothing and report that in the same calm sentence, so
# both halves are proven on fixtures of their own before either is believed — the QUIET half as much as the loud
# one, because a rule that answered yes to everything would be obeyed by deleting it. These also pin what the
# rules do not see: `selfcheck` in prose is not a dispatch, and a tool merely NAMED beside the word is not run.
mkdir -p "$GD/sc" "$GD/disc/bin"
sc(){ local w=$1 s; printf '%s\n' "$3" > "$GD/sc/$2"
  if ships_selfcheck "$GD/sc/$2"; then s=yes; else s=no; fi
  [ "$s" = "$w" ] || { echo "check.sh: 'ships a selfcheck' reads $2 as $s, not $w: $3"; exit 1; }; }
sc yes cc-tally   'echo "cc-tally selfcheck: 3 passed, 0 failed"'
sc yes cc-arm     'case "$1" in selfcheck) run;; esac'
sc yes cc-test    '[ "$1" = selfcheck ] && run'
sc yes cc-argv    'if sys.argv[1:] == ["selfcheck"]: sys.exit(selfcheck())'
sc yes cc-table   '          "selfcheck": lambda o: selfcheck()}'
sc no  cc-prose   '# some other tool selfcheck is talked about here, and nothing dispatches on the word'
sc no  cc-quiet   'echo hello'
rs(){ local w=$1 s; printf '%s\n' "$4" > "$GD/sc/r.$2"
  if runs_selfcheck "$GD/sc/r.$2" "$3"; then s=yes; else s=no; fi
  [ "$s" = "$w" ] || { echo "check.sh: 'already run elsewhere' reads $2 as $s, not $w: $4"; exit 1; }; }
rs yes chk        cc-pulse     'chk cc-pulse'
rs yes chk-note   cc-loop      'chk cc-loop   # its own tally line, not the journal fixtures it prints above it'
rs yes prefetched cc-pulse     'prefetch cc-reconcile cc-janitor cc-pulse cc-secretary'
rs yes invoked    cc-slack     '"$B/cc-slack" selfcheck > "$T/slack-selfcheck.out" 2>&1 && ok "…"'
rs yes by-a-tool  cc-member-v2 '  "$BIN/cc-member-v2" selfcheck; t "v2 cases" "$?" 0'
rs no  prefix     cc-member    'chk cc-member-broker'
rs no  named-only cc-pulse     '# cc-pulse selfcheck is described here and run nowhere'
rs no  another    cc-pulse     'chk cc-pause'
# …AND THE TWO TOGETHER, on a bin/ and a suite of its own, because what this gate runs is their COMPOSITION and
# neither half on its own says it: a tool nothing runs is run HERE — the failure this whole block exists to stop —
# one the suite runs is left to the suite, one another tool drives is left to that tool and named for it, a tool
# with no selfcheck is reported and not run, and the always-here names run here even though the suite runs them too
# — passed the way the real call passes them, one per line, because a set that only worked as one word would break
# on the first name added under the next.
d(){ printf '%s\n' "$2" > "$GD/disc/$1"; }
d bin/cc-orphan 'case "$1" in selfcheck) :;; esac'
d bin/cc-suited 'case "$1" in selfcheck) :;; esac'
d bin/cc-driver 'case "$1" in selfcheck) "$BIN/cc-driven" selfcheck;; esac'
d bin/cc-driven 'case "$1" in selfcheck) :;; esac'
d bin/cc-nosc   'echo this tool has no cases of its own'
d bin/cc-always 'case "$1" in selfcheck) :;; esac'
d bin/cc-both   'case "$1" in selfcheck) :;; esac'
d bin/cc-prosaic 'echo "to check this one, run cc-orphan selfcheck by hand"'   # says the word, dispatches nothing
d suite         $'chk cc-suited\nchk cc-driver\nchk cc-always\nchk cc-both'
discover_selfchecks "$GD/disc/bin" "$GD/disc/suite" $'\ncc-always\ncc-both\n'
[ "$FOUND" = " cc-always cc-both cc-driven cc-driver cc-orphan cc-suited" ] && [ "$NOSC" = " cc-nosc cc-prosaic" ] \
  && [ "$HERE" = " cc-always cc-both cc-orphan" ] && [ "$ELSEWHERE" = " cc-driven(cc-driver) cc-driver cc-suited" ] \
  || { echo "check.sh: the selfcheck discovery no longer splits a fixture bin/ the way it says it does:"
       echo "  found:$FOUND / here:$HERE / elsewhere:$ELSEWHERE / no selfcheck:$NOSC"; exit 1; }
# …AND THE TRIPWIRE ON THAT SAME FIXTURE, END TO END. No real tool takes this branch today, so nothing else here
# would notice it break — a mistyped variable or a grep that stopped matching would sit quiet until the day a tool
# needed it, which is the day it must not be quiet. cc-prosaic is the shape it hunts: the word with no dispatch,
# carried through discover_selfchecks into NOSC and fed to the same function the real tree is judged by. Both
# answers are pinned, because one that always refused would be obeyed by deleting it.
if o=$(nosc_says_selfcheck "$GD/disc/bin" "$NOSC"); then trc=0; else trc=$?; fi
{ [ "$trc" = 1 ] && grep -q "cc-prosaic says 'selfcheck'" <<<"$o"; } \
  || { echo "check.sh: a NOSC tool that says 'selfcheck' with no dispatch no longer stops this gate (rc=$trc):"
       echo "  ${o:-<it said nothing>}"; exit 1; }
nosc_says_selfcheck "$GD/disc/bin" cc-nosc \
  || { echo "check.sh: the NOSC tripwire now fires on a tool that never says 'selfcheck' — it would refuse every"
       echo "  clean tree, and the way to make this gate green again would be to delete the rule."; exit 1; }
# THE FEW THIS GATE RUNS ANYWAY, ONE NAME PER LINE. Each is a tool tests/selftest.sh runs too, and this gate runs
# it regardless, because check.sh is what a COMMIT has to pass and the suite is not: cc-board because its tripwire
# reads every other tool under bin/, and the other five because the suite's own stanzas say they run here "too"
# (selftest.sh, cc-notify's stanza). Leaving them to the suite would have quietly taken five selfchecks off the
# pre-commit gate to fix a conflict that was never theirs.
# THIS IS NOT THE LIST THIS BLOCK REPLACED AND CANNOT DECAY INTO IT. Every name here is already running somewhere;
# a tool missing from here is a selfcheck the suite still runs, once, while a tool missing from the OLD list was a
# selfcheck nobody ran at all. Being wrong here costs a duplicate run, which is the only direction this file is
# allowed to be wrong in. One name per line, so two branches adding different ones do not touch the same line.
also_here='
cc-board
cc-brief
cc-native
cc-notify
cc-task
cc-watch
'
discover_selfchecks bin tests/selftest.sh "$also_here"
nosc_says_selfcheck bin "$NOSC" || exit 1
others=""; for t in $HERE; do [ "$t" = cc-board ] || others="$others $t"; done
SCD=$GD   # the dir and its trap are set at the top; a second EXIT trap here would have replaced the first
running=0; ran=""
# cc-board is named here for a reason that is not the list's: the loop must stay one literal `for c in cc-…` line
# holding ` cc-board `, gated by one `want_selfcheck "$c"`, because cc-board's own selfcheck reads this file and
# pins both shapes — the rule that its tripwire runs for a change to ANY tool is dead the moment this loop goes
# back to asking `want`. $others is everything else the discovery put HERE, so a tool added tomorrow is run
# tomorrow by nobody's memory, and the one name in the source is a shape cc-board pins, not a roster to keep.
for c in cc-board $others; do
  want_selfcheck "$c" || { skipped="$skipped $c"; continue; }
  ran="$ran $c"
  { rc=0; o=$("bin/$c" selfcheck 2>&1) || rc=$?; printf '%s' "$o" > "$SCD/$c.out"; echo "$rc" > "$SCD/$c.rc"; } &
  running=$((running + 1))
  [ "$running" -lt "$JOBS" ] || { wait -n 2>/dev/null || wait; running=$((running - 1)); }
done
# WHAT THE DISCOVERY DECIDED, SAID OUT LOUD AND BEFORE THE VERDICTS, so a run that goes red still shows what it
# chose to run. The old list was silent about everything it left out, which is how cc-evals', cc-model's and
# cc-vitals' cases lived in the repository with no suite here ever running them. Every set is NAMED and not just
# counted — what ran here, what another runner owns, what ships nothing, what this change did not reach — because
# a count cannot tell you which tool went missing and the name can.
n_of(){ set -- $1; echo $#; }   # counted inside a function, so this gate's own "$@" (extra python files) is untouched
echo "check.sh: selfchecks: $(n_of "$FOUND") of $(n_of "$FOUND$NOSC") tools under bin/ ship one — $(n_of "$ran") ran here, $(n_of "$ELSEWHERE") run elsewhere, $(n_of "$skipped") out of this change's reach"
echo "  here:$ran"
echo "  elsewhere, not twice (tests/selftest.sh, or the tool named):$ELSEWHERE"
echo "  ships none — not a failure, named so an absent selfcheck is visible:$NOSC"
[ -z "$skipped" ] || echo "  not in this change's reach, not run:$skipped"
wait
# THE VERDICT LOOP WALKS WHAT WAS STARTED, not what happens to have left a file behind. A job killed before it
# could write its rc leaves nothing, and a loop reading the directory would have counted that silence as a tool
# that was never in reach — the one failure this gate exists to catch, passing quietly. Started and empty is red.
for c in $ran; do
  [ -f "$SCD/$c.rc" ] || { echo "$c: its selfcheck was started and left no result — killed, or it died before it"
                           echo "  could report. Nothing here passed; run 'bin/$c selfcheck' on its own to see it."
                           exit 1; }
  rc=$(cat "$SCD/$c.rc"); o=$(cat "$SCD/$c.out")
  # 77 is cc-fence's ALONE, and means one thing: this kernel has no Landlock to apply, so its cases did not run.
  # Its line is printed and stays visible — that is not a pass. Any other tool exiting 77, and cc-fence exiting
  # 77 for any other reason (it refuses to report a skip when the kernel HAS Landlock and declined), fails here.
  [ "$rc" = 0 ] || { echo "$o"; { [ "$rc" = 77 ] && [ "$c" = cc-fence ]; } || exit 1; }
  tally_ok "$c" "$o" || { g=$(tally_line "$c" "$o")
    echo "$c: its cases passed, but its tally line is a shape selftest.sh's chk() cannot read, so the suite will"
    echo "  call this tool dead when it is green. Fix the tool's last line — chk() is right, see its comment."
    echo "  got:  ${g:-<no \"$c selfcheck: …\" line at all>}"
    echo "  want: \"$c selfcheck: <n> passed, 0 failed\" or \"$c selfcheck: 0 failed\""
    exit 1; }; done
# THE DOC THAT TELLS THE OWNER WHEN HIS PHONE RINGS MUST NAME EVERY ROW THAT RINGS IT. USAGE.md went on promising a
# push for every cc-notify call long after the table stopped giving one (found by review, 2026-09-07): that file is
# what he reads to know what reaching him costs, and a promise the code does not keep is worse than no promise. So
# the phone=yes rows are read out of the table itself and each has to appear in the text — add a ringing row, or take
# the sentence away, and this is red until the two agree. A row name is matched with its dashes as spaces, so the row
# `notify-test` is satisfied by the command the owner actually types, `cc-notify test`.
rings=$(sed -n '/^declare -A RUNGS=(/,/^)/p' bin/cc-notify | sed -n 's/^ *\[\([a-z-]*\)\]="[145] yes .*/\1/p')
[ -n "$rings" ] || { echo "check.sh: no phone=yes row in cc-notify's table — this rule would pass by reading nothing"; exit 1; }
for r in $rings; do
  grep -qF "${r//-/ }" templates/home/USAGE.md || {
    echo "check.sh: cc-notify rings the owner's phone for '$r', and templates/home/USAGE.md never says so."
    echo "  That line is how he knows what reaches him. Name the row there, or stop ringing for it."; exit 1; }; done
# …AND THE OTHER HALF: no template may say the box rings his phone for something the table keeps quiet. Four
# documents have now promised a push the code stopped giving — USAGE, DESIGN, cc-slack's docstring, COMMS — each
# found one review at a time. So every line in these files that claims the phone must name a row that actually
# rings it. "from your phone" is the owner USING his phone, not the box reaching it, and is not a claim.
for d in templates/home/USAGE.md templates/home/COMMS.md templates/home/RUNBOOK.md; do
  [ -f "$d" ] || continue
  while IFS= read -r ln; do
    for r in $rings; do case "$ln" in *"${r//-/ }"*) continue 2;; esac; done
    echo "check.sh: $d says the box reaches his phone, on a line naming none of the rows that ring it ($(echo $rings | tr '\n' ' ')):"
    echo "  ${ln:0:160}"
    echo "  Either name the row, or stop claiming the phone — this promise has now been wrong in four documents."
    exit 1
  done < <(grep -niE 'your phone' "$d" | grep -viE 'from your phone')
done

# AND THE PROMPT MUST TEACH A COMMAND THAT ACTUALLY REACHES HIM. Every track and planning session is told in its
# system prompt how to reach the owner when it is truly blocked. When the table moved the rung-1 door to
# --decision/--owner, that one sentence was not moved with it, so the box's main blocked-escalation path went
# ambient and stayed ambient through two reviews. The prompt is a caller like any other, so it is checked like one:
# the form it teaches has to be a form the table rings for.
while IFS= read -r ln; do
  case "$ln" in *"cc-notify --decision"*|*"cc-notify --owner"*) ;;
    *) echo "check.sh: bin/cc tells a session to reach the owner with a cc-notify the table routes AMBIENT:"
       echo "  ${ln:0:200}"
       echo "  Rung 1 is --decision (or --owner). A plain cc-notify is rung 5: no phone, no @-mention."; exit 1;; esac
done < <(grep -n 'Reach the owner' bin/cc)

# THE PREFETCH WINDOW, as a tripwire rather than a comment. selftest.sh starts a few tools' selfchecks early and
# collects each at its own `chk`. A selfcheck inherits whatever that file has exported by the time it starts, so an
# `export`, `unset` or `cd` added BETWEEN the `prefetch` line and the `chk` that reads it makes the tool run under
# an environment its stanza never set up: it still prints a tally, still goes green, and is checking something
# else. That is the one trade the suite must not make, and nothing else would notice it. Conservative on purpose —
# it flags such a line even inside a `( … )` subshell, where it would not actually leak. The fix is to move the
# `prefetch` line to after the change, never to delete this.
pf_window(){ awk '
  # PER TOOL, not per file: each one is checked between ITS OWN prefetch line and the first chk that collects it,
  # so a second `prefetch` line elsewhere is covered too rather than quietly moving the window for all of them.
  /^prefetch / { for (i = 2; i <= NF; i++) pf[$i] = NR }
  /^chk /      { if ($2 in pf && !($2 in ck)) ck[$2] = NR }   # the FIRST chk of that tool is the one that reads it
  /^(export|unset|cd) / { off[NR] = $0 }
  END {
    for (t in pf) {
      if (!(t in ck)) { printf "  %s is started early but nothing ever collects it — there is no `chk %s`\n", t, t; continue }
      for (n in off) if (n+0 > pf[t] && n+0 < ck[t])
        printf "  line %d sits between `prefetch %s` and its `chk`: %.90s\n", n, t, off[n]
    }
  }' "$1"; }   # <file> -> one line per offence, empty when the window is clean
# PROVEN BOTH WAYS BEFORE IT IS TRUSTED, on fixtures of its own — never on selftest.sh, whose window is clean today
# and so can only ever show the quiet half. A tripwire nobody has watched fire is a comment with an exit code; and
# the half that matters as much here is the QUIET one, because a rule that flagged everything would be obeyed by
# deleting it. These also pin what the rule does NOT see, which is the honest limit of reading a shell file with
# awk: only a line that BEGINS with export, unset or cd, so `foo; export BAR=1` mid-line goes through. Widening
# that is a change to the awk above and a case here, in that order.
pf_case(){ local want=$1 name=$2 got saw
  printf '%s\n' "$3" > "$GD/pf.$name"; got=$(pf_window "$GD/pf.$name")
  if [ -n "$got" ]; then saw=flag; else saw=quiet; fi
  [ "$saw" = "$want" ] || { echo "check.sh: the prefetch-window rule reads the '$name' fixture as $saw, not $want:"
                            printf '%s\n' "$3" | sed 's/^/    /'; echo "$got"; exit 1; }; }
pf_case quiet clean           $'prefetch cc-a\nchk cc-a'
pf_case flag  export-inside   $'prefetch cc-a\nexport X=1\nchk cc-a'
pf_case flag  unset-inside    $'prefetch cc-a\nunset X\nchk cc-a'
pf_case flag  cd-inside       $'prefetch cc-a\ncd /tmp\nchk cc-a'
pf_case quiet export-before   $'export X=1\nprefetch cc-a\nchk cc-a'
pf_case quiet export-after    $'prefetch cc-a\nchk cc-a\nexport X=1'
pf_case flag  never-collected $'prefetch cc-a\nchk cc-b'
pf_case flag  second-tool     $'prefetch cc-a cc-b\nchk cc-a\nexport X=1\nchk cc-b'
pf_case quiet first-chk-wins  $'prefetch cc-a\nchk cc-a\nexport X=1\nchk cc-a'
w=$(pf_window tests/selftest.sh)
[ -z "$w" ] || { echo "check.sh: tests/selftest.sh prefetches a selfcheck across a change to its own environment:"
                 echo "$w"
                 echo "  A prefetched tool must run under the same environment as the chk that reads it."; exit 1; }

# Green: leave a record of the CONTENT this passed on — and the scope it ran at — so the landing does not run it
# again on the same files the worker already ran it on (tests/green.sh, read by cc-land).
green_record "$SELF" "$SCOPE"
echo "check.sh: OK (${#sh[@]} shell, $((${#py[@]} + 4 + $#)) python, json, units, manifests, agent types)"
