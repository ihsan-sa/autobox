#!/usr/bin/env bash
# tests/check.sh — static checks over core/. bin/ and config/ are LIVE via symlinks: run before committing on
# the default branch (the pre-commit hook does). Extra python files to compile can be passed as arguments
# (a private overlay adds its own that way).
set -e; SELF=$(readlink -f "$0"); cd "$(dirname "$0")/.."   # $0 is resolved BEFORE the cd moves out from under it
sh=(); py=()
for f in bin/* install.sh ccbox/*.sh; do [ -f "$f" ] || continue; head -1 "$f" | grep -q bash && sh+=("$f"); head -1 "$f" | grep -q python && py+=("$f"); done
bash -n "${sh[@]}"
shellcheck -S warning -e SC1090,SC1010 "${sh[@]}"
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
for c in cc-units cc-settings cc-board cc-task cc-native cc-broker cc-config cc-msg cc-spend cc-econ cc-time cc-guard cc-brief cc-gh-token cc-checkpoint cc-digest cc-notify cc-pause cc-publish cc-voice cc-fence cc-member-broker cc-steward cc-member-import cc; do
  want_selfcheck "$c" || { skipped="$skipped $c"; continue; }
  rc=0; o=$("bin/$c" selfcheck 2>&1) || rc=$?
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
[ -z "$skipped" ] || echo "check.sh: not in this change's reach, not run:$skipped"
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

# Green: leave a record of the CONTENT this passed on — and the scope it ran at — so the landing does not run it
# again on the same files the worker already ran it on (tests/green.sh, read by cc-land).
green_record "$SELF" "$SCOPE"
echo "check.sh: OK (${#sh[@]} shell, $((${#py[@]} + 4 + $#)) python, json, units, manifests, agent types)"
