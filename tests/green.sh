#!/usr/bin/env bash
# tests/green.sh — what the two suites share: what a green run leaves behind, and how far a change reaches.
# Sourced by check.sh and selftest.sh; read by cc-land (green_run there).
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
green_record(){   # $1 = the suite that just passed, as it was invoked ("$0"); $2 = the scope it ran at ("" = everything)
  local self root rel dir idx tree scope
  self=$(readlink -f "$1" 2>/dev/null) || return 0
  root=$(cd "$(dirname "$self")" && git rev-parse --show-toplevel 2>/dev/null) || return 0
  [ -n "$root" ] || return 0
  rel=${self#"$root"/}                     # how the landing names this gate: "core/tests/check.sh", "tests/check.sh"
  dir="${CC_GREEN_DIR:-$HOME/.cc/state/land/green}"
  idx=$(mktemp "${TMPDIR:-/tmp}/cc-green.XXXXXX" 2>/dev/null) || return 0
  # An index of its own, so hashing the working copy neither stages anything nor disturbs the real one.
  tree=$(cd "$root" && GIT_INDEX_FILE="$idx" git read-tree HEAD 2>/dev/null &&
         GIT_INDEX_FILE="$idx" git add -A 2>/dev/null && GIT_INDEX_FILE="$idx" git write-tree 2>/dev/null) || tree=""
  rm -f "$idx"
  [ -n "$tree" ] && [ -n "$rel" ] || return 0
  mkdir -p "$dir" 2>/dev/null || return 0
  scope=${2:-}; scope=${scope//[\"\\]/}
  printf '{"suite": "%s", "tree": "%s", "scope": "%s", "at": "%s"}\n' "$rel" "$tree" "$scope" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "$dir/$(basename "$rel")-${tree:0:12}.json" 2>/dev/null
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
  # that drives it through cc-handoff. The three shapes a tool is invoked by on this box: `$BIN/cc-foo` and
  # `${BIN}/cc-foo` in shell and python strings, `$B/cc-foo` in the suites, and python's
  # `os.path.join(BIN, "cc-foo")` — cc-context, cc-handoff and cc-graphs call every one of their siblings that way.
  queue=$tools
  while [ -n "$queue" ]; do
    nxt=""
    for t in $queue; do
      for p in $(grep -l -E -- "BIN\}?/$t([^A-Za-z0-9_-]|$)|\\\$B/$t([^A-Za-z0-9_-]|$)|join\([A-Za-z_][A-Za-z0-9_]*, *[\"']${t}[\"']" "$b"/* 2>/dev/null); do
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
