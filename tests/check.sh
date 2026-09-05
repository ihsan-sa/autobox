#!/usr/bin/env bash
# tests/check.sh — static checks over core/. bin/ and config/ are LIVE via symlinks: run before committing on
# the default branch (the pre-commit hook does). Extra python files to compile can be passed as arguments
# (a private overlay adds its own that way).
set -e; SELF=$(readlink -f "$0"); cd "$(dirname "$0")/.."   # $0 is resolved BEFORE the cd moves out from under it
sh=(); py=()
for f in bin/* install.sh ccbox/*.sh; do [ -f "$f" ] || continue; head -1 "$f" | grep -q bash && sh+=("$f"); head -1 "$f" | grep -q python && py+=("$f"); done
bash -n "${sh[@]}"
shellcheck -S warning -e SC1090,SC1010 "${sh[@]}"
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile "${py[@]}" tests/slack_sim.py "$@"
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
# …and only the ones a change reaches, when the landing says what changed (CC_LAND_CHANGED — tests/green.sh has
# the rule): the static checks above run whatever the change, a selfcheck of a tool nothing here touched does not.
# cc-board's is the exception and runs whenever any tool changed — one of its cases reads all the others.
. tests/green.sh; land_scope "$PWD/bin"; skipped=""
for c in cc-units cc-settings cc-board cc-broker cc-config cc-msg cc-spend cc-econ cc-time cc-guard cc-brief cc-gh-token cc-checkpoint cc-pause cc-publish; do
  want_selfcheck "$c" || { skipped="$skipped $c"; continue; }
  o=$("bin/$c" selfcheck 2>&1) || { echo "$o"; exit 1; }; done
[ -z "$skipped" ] || echo "check.sh: not in this change's reach, not run:$skipped"
# Green: leave a record of the CONTENT this passed on — and the scope it ran at — so the landing does not run it
# again on the same files the worker already ran it on (tests/green.sh, read by cc-land).
green_record "$SELF" "$SCOPE"
echo "check.sh: OK (${#sh[@]} shell, $((${#py[@]} + 1 + $#)) python, json, units, manifests, agent types)"
