#!/usr/bin/env bash
# tests/green.sh — what the two suites share: what a green run leaves behind, and how far a change reaches.
# Sourced by check.sh, selftest.sh and cc-green; read by cc-land (green_run there).
#
# THE RECORD. The worker runs these suites before it opens its PR and the landing ran them again on the same code —
# confirmed on PR #211, 2026-09-04 — with nothing reading the second result differently from the first. A sentence
# in a journal is not evidence; a record naming the CONTENT it passed on is.
#
# THE KEY IS THE CONTENT, NOT THE COMMIT. A worker runs the suite and the Stop hook commits after it, so the sha
# it ran at is never the sha the PR carries — a record keyed by HEAD would never once match. What is recorded is
# the git tree the working copy would commit: every tracked and addable file, hashed by git, ignores obeyed. An
# edit after the run, a rebase onto a moved base, a merge — each makes a different tree, and the suite runs again.
#
# …AND THE SCOPE IT RAN AT. A run that skipped what the change did not reach (below) must not answer for a run
# that would not have: the record says which paths it was scoped to, and a landing spends it only when that is
# empty (everything ran) or exactly its own.
#
# It is written by the SUITE, on green, and by nothing else. It is not a signature: anything running as this user
# can write one by hand, and no file on this box can stop it. It is evidence of content, which is what the second
# run was buying.
green_tree(){     # $1 = a repo root → the git tree its working copy WOULD commit, or nothing if that cannot be taken
  local idx tree
  idx=$(mktemp "${TMPDIR:-/tmp}/cc-green.XXXXXX" 2>/dev/null) || return 0
  # An index of its own, so hashing the working copy neither stages anything nor disturbs the real one.
  tree=$(cd "$1" && GIT_INDEX_FILE="$idx" git read-tree HEAD 2>/dev/null &&
         GIT_INDEX_FILE="$idx" git add -A 2>/dev/null && GIT_INDEX_FILE="$idx" git write-tree 2>/dev/null) || tree=""
  rm -f "$idx"
  printf '%s' "$tree"
  return 0
}
# ONE ALGORITHM, WRITER AND READER. cc-green asks the same question before a worker hands over — is a record
# already filed for what I am about to push? — and asked with a hash of its own it could answer yes where the
# suite would have filed a different tree. Two algorithms is how a green comes to name content it did not pass on,
# which is worse than no green at all. So there is one, here, and both callers go through it.

green_record(){   # $1 = the suite that just passed, as it was invoked ("$0"); $2 = the scope it ran at ("" = everything)
  local self root rel dir tree scope part
  self=$(readlink -f "$1" 2>/dev/null) || return 0
  root=$(cd "$(dirname "$self")" && git rev-parse --show-toplevel 2>/dev/null) || return 0
  [ -n "$root" ] || return 0
  rel=${self#"$root"/}                     # how the landing names this gate: "core/tests/check.sh", "tests/check.sh"
  dir="${CC_GREEN_DIR:-$HOME/.cc/state/land/green}"
  tree=$(green_tree "$root")
  [ -n "$tree" ] && [ -n "$rel" ] || return 0
  mkdir -p "$dir" 2>/dev/null || return 0
  scope=${2:-}; scope=${scope//[\"\\]/}
  # …AND WHICH HALF IT WAS. A record of the portable half must never answer an ask about the whole gate, so the
  # half is both in the file and in its NAME: `check.sh-portable-<tree>.json` beside `check.sh-<tree>.json`.
  # A whole run (CC_SUITE_PART unset) keeps the name it always had, so every existing record still reads.
  case "${SUITE_PART:-all}" in all) part="";; *) part=$SUITE_PART;; esac   # never `[ … ] && part=`: under set -e a
                                        # false test IS this line's status, and the suite that passed would exit 1
  printf '{"suite": "%s", "tree": "%s", "scope": "%s", "part": "%s", "at": "%s"}\n' \
    "$rel" "$tree" "$scope" "$part" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "$dir/$(basename "$rel")${part:+-$part}-${tree:0:12}.json" 2>/dev/null
  return 0   # a record is an optimisation and never a result: nothing here can fail a run that passed
}

# HOW FAR A CHANGE REACHES. cc-land hands a suite the paths a PR changes (CC_LAND_CHANGED, space-separated, as git
# names them). A tool's own selfcheck, and every case that drives it, is then worth running only if that tool
# changed or a tool that INVOKES it did — `$BIN/cc-foo` in the source, which is a smaller and truer list than every
# file that mentions the name in a comment. Nothing here is a list somebody keeps: the source is the graph. What
# widens it back to everything: a path that is not a tool under bin/ (a test, a config, a template, install.sh —
# what those touch is not something a grep can answer), a tool too short to grep for, and a tool that is gone.
# `cc` itself is the front door to nearly every tool, so it is never pulled in as an invoker — a stanza that calls
# `cc` runs for a change to cc, which is everything, and not for every change to something cc can start.
land_scope(){   # $1 = this tree's bin/. Sets SCOPE ("" = everything) and REACH (" tool tool ": the tools worth running for)
  local b=$1 p t tools="" queue nxt
  SCOPE=""; REACH=""
  [ -n "${CC_LAND_CHANGED:-}" ] || return 0
  for p in $CC_LAND_CHANGED; do
    t=${p##*/}
    case "$p" in */bin/"$t"|bin/"$t") [ -f "$b/$t" ] && [ ${#t} -ge 3 ] || return 0;; *) return 0;; esac
    tools="$tools $t"
  done
  # …and TRANSITIVELY: a caller's caller drives the changed tool just as surely, so this walks out from the changed
  # tools until nothing new appears. Stopping at one hop left a change to cc-msg out of the reach of every stanza
  # that drives it through cc-handoff. The four shapes a tool is named by on this box: `$BIN/cc-foo` and
  # `${BIN}/cc-foo` in shell and python strings, `$B/cc-foo` in the suites, python's
  # `os.path.join(BIN, "cc-foo")` — cc-context, cc-handoff and cc-graphs call every one of their siblings that way
  # — and pathlib's `BIN / "cc-foo"`, which cc-native, cc-task and the member tools use. That last one was missing
  # and hid every edge spelled with it: cc-member-import READS cc-checkpoint's staged-name policy out of its
  # source, and a change to cc-checkpoint alone never ran the selfcheck that catches a rename of it. A source read
  # is a harder dependency than a call, and it is spelled the same way, so the same grep answers for both.
  queue=$tools
  # The member launcher calls its fence at the path inside bwrap, which the host
  # invocation grep cannot see. Its cases live under cc-sandbox's canary gate.
  case " $tools " in *" cc-fence "*|*" cc-member-v2 "*|*" cc-member-broker "*|*" cc-member-import "*|*" cc-sandbox "*)
    tools="$tools cc-fence cc-member-v2 cc-member-broker cc-member-import cc-sandbox"; queue=$tools;; esac
  while [ -n "$queue" ]; do
    nxt=""
    for t in $queue; do
      for p in $(grep -l -E -- "BIN\}?/$t([^A-Za-z0-9_-]|$)|\\\$B/$t([^A-Za-z0-9_-]|$)|join\([A-Za-z_][A-Za-z0-9_]*, *[\"']${t}[\"']|BIN */ *[\"']${t}[\"']" "$b"/* 2>/dev/null); do
        p=${p##*/}
        case " $tools $nxt " in *" $p "*) ;; *) [ "$p" = cc ] || nxt="$nxt $p";; esac
      done
    done
    tools="$tools$nxt"; queue=$nxt
  done
  REACH=" $(tr ' ' '\n' <<<"$tools" | grep . | sort -u | tr '\n' ' ')"
  # NOT re-sorted. cc-land already emits CC_LAND_CHANGED sorted and unique, in python's byte order, and the record
  # this scope goes on is spent only when the two strings are EQUAL. A `sort -u` here runs in the box's own locale,
  # where GNU sort ignores punctuation on the first pass: `core/bin/cc-graphs core/bin/ccbox` comes back swapped,
  # nothing ever matches, and the suite that already passed on that content runs again every landing.
  SCOPE=$CC_LAND_CHANGED
}
want(){ [ -z "${REACH:-}" ] && return 0; local t; for t; do case "$REACH" in *" $t "*) return 0;; esac; done; return 1; }

# A SELFCHECK THAT READS ITS SIBLINGS runs for a change to any of them, and the graph above cannot say so: it maps
# who INVOKES whom, and this one invokes nobody. cc-board's has a tripwire over every tool in bin/ — no sibling
# opens a board file itself — so gating it on the graph guards nothing. On 2026-09-05 a direct read landed in a
# tool cc-board neither is nor calls, and no landing since ran the case. Any narrowed scope is a set of tools under
# bin/ (anything else widened it back to everything), so for cc-board this is true whenever it is asked.
want_selfcheck(){ [ "$1" = cc-board ] || want "$1"; }

# ── WHICH HALF OF THE SUITE THIS RUN IS ───────────────────────────────────────────────────────────────────────
# One suite, two halves, and no second copy of a case anywhere: CC_SUITE_PART says which half a run is doing.
#   all       every unit — what the pre-commit hook and a person typing the file get, and what this box always ran
#   portable  the units that need no particular machine: their own fixtures, their own HOME, their own temp dir
#   box       the units that need THIS one — its tmux, its systemd, its kernel's namespaces, its ~/.cc, its install
# A UNIT IS PORTABLE UNLESS IT SAYS `box`, and that default is the safe direction on purpose. An undeclared unit
# that does need the box runs off-box and FAILS there, by name, in the open; a portable unit wrongly declared box
# only costs the box the seconds of running it. The direction that would be dangerous — a unit that quietly runs
# in NEITHER half — is the one part_audit() refuses: every unit lands in ran, deferred or out-of-reach, and a name
# in none of the three stops the gate.
SUITE_PART=${CC_SUITE_PART:-all}
case "$SUITE_PART" in all|portable|box) ;;
  *) echo "CC_SUITE_PART=$SUITE_PART: it is 'portable', 'box', or unset for both halves" >&2; exit 2;; esac
# …AND IT IS READ OFF THE ENVIRONMENT ONCE AND THEN TAKEN OUT OF IT. The half belongs to the SUITE RUN, not to
# anything the suite starts: a tool's own selfcheck builds its own fixtures and is one whole thing either way, and
# a suite that let its half through to its children would be telling them to run half of themselves. That is not
# theory — `CC_SUITE_PART=portable core/tests/check.sh` took cc-green's selfcheck from 26 passed to 17 passed, 9
# failed, because cc-green sources this file, inherited the half, and its fixture gates began filing records under
# a name its own reader does not look for. Unsetting here fixes every call site at once, including ones nobody has
# written yet; $SUITE_PART is this shell's own copy and is untouched.
unset CC_SUITE_PART
# THE THREE LISTS ARE NEWLINE-SEPARATED, not space-separated, because a unit's name is as often a sentence as a
# word: a selftest stanza is titled, not slugged, and "cc main + track creation" split on spaces is four units
# that add up to nothing and an audit that passes by not understanding its own inventory.
PART_RAN=""; PART_DEFERRED=""; PART_OUT=""; PART_WHY=""
part_has(){ case $'\n'"$2" in *$'\n'"$1"$'\n'*) return 0;; esac; return 1; }
part_here(){   # part_here <unit> [box] -> 0 when THIS half owns the unit; 1 when the other half does, with the
               # sentence to print in $PART_WHY. Every call lands the unit in exactly one of the two lists.
  local u=$1 p=${2:-portable}
  PART_WHY=""
  if [ "$SUITE_PART" = all ] || [ "$SUITE_PART" = "$p" ]; then PART_RAN="$PART_RAN$u"$'\n'; return 0; fi
  PART_DEFERRED="$PART_DEFERRED$u"$'\n'
  if [ "$p" = box ]; then
    PART_WHY="$u: needs this box (its tmux, its systemd, its kernel, its ~/.cc) — refused here, and run in the box half"
  else PART_WHY="$u: portable — this is the box half, so it ran, or is running, off the box"; fi
  return 1; }
part_out(){ PART_OUT="$PART_OUT$1"$'\n'; }   # …and the third place a unit may legitimately be: out of this
                                             # change's reach, which is neither half's to run
# THE TOOLS WHOSE OWN SELFCHECK NEEDS THIS MACHINE. One name per line, each with its reason, so two branches
# adding different ones do not touch the same line — and so that "why is this one still on the box" is answered in
# the file rather than in somebody's journal. EVERY OTHER TOOL IS PORTABLE, including ones nobody has thought
# about: a tool that does need the box and is missing from here fails off-box, by name, which is the direction
# this list is allowed to be wrong in. Adding a name costs the box that tool's seconds and nothing else.
PART_BOX_TOOLS='
cc-sandbox
cc-fence
cc-member-v2
cc-arch
'
# cc-sandbox   real bwrap and unprivileged user namespaces; it returns 1 rather than skipping, which is correct
# cc-fence     runs its cases against the KERNEL's Landlock and exits 77 — reported as skipped, printed green —
#              where there is none. Off-box that is a pass by absence, which is what this split must not create.
# cc-member-v2 its cases run inside cc-sandbox's canary gate, so they need what cc-sandbox needs
# cc-arch      runs the real pdflatex and SKIPS those cases with a line where it is absent: a pass by absence again
part_of_tool(){ case " $(echo $PART_BOX_TOOLS) " in *" $1 "*) echo box;; *) echo portable;; esac; }
part_caps(){   # what a `portable` run must NOT quietly do without. The box half is allowed to find something
               # missing and say so; the portable half is where a tool that is simply absent looks exactly like a
               # pass. Named here and asserted before a single case runs, so an image that lost one goes red at
               # the door rather than reporting a hollow green from the middle of a gate.
  local m="" c
  for c in "$@"; do command -v "$c" >/dev/null 2>&1 || m="$m $c"; done
  [ -z "$m" ] || { echo "this run has no$m, and the blocks that need them would report nothing rather than fail."
                   echo "  A portable run says what it has before it starts: install them, or run the box half here."
                   return 1; }
  return 0; }
part_n(){ printf '%s' "$1" | awk 'NF {n++} END {print n + 0}'; }
part_names(){ printf '%s' "$1" | awk 'NF {printf "%s%s", (n++ ? " · " : ""), $0} END {print ""}'; }
part_audit(){   # part_audit <suite> <inventory, one unit per line> -> 0 when each one ran, was left to the other
                # half, or was out of this change's reach. A unit in none of the three is a unit that stopped
                # running ANYWHERE while both halves reported green — the one failure a split can introduce, and
                # the one nothing else here would notice.
  local suite=$1 u lost=""
  while IFS= read -r u; do
    [ -n "$u" ] || continue
    part_has "$u" "$PART_RAN$PART_DEFERRED$PART_OUT" || lost="$lost  $u"$'\n'
  done <<<"$2"
  [ -z "$lost" ] || { echo "$suite: these units ran in NEITHER half, and were not out of this change's reach:"
                      printf '%s' "$lost"
                      echo "  A unit in no half is a test that runs nowhere. Give it a half, or take it out."
                      return 1; }
  return 0; }
part_line(){   # the one sentence every suite ends on, so a `portable` run and a `box` run are read the same way
  local suite=$1
  [ "$SUITE_PART" != all ] || return 0   # `!=` and never `[ = all ] && return`: see green_record above
  echo "$suite: the $SUITE_PART half — $(part_n "$PART_RAN") unit(s) ran here, $(part_n "$PART_DEFERRED") in the other half"
  [ -z "$PART_DEFERRED" ] || echo "  the other half owns, and is where these report: $(part_names "$PART_DEFERRED")"
  return 0; }
