# shellcheck shell=bash disable=SC2154,SC2034
# cc-bin-at's selfcheck cases, moved out of bin/cc-bin-at. That tool's selfcheck() sources this file, whose
# definition replaces it, and then calls it: the cases run in the tool's own shell, with its functions and
# globals, as they did when the body sat there. SC2154/SC2034 are off because those globals live in bin/cc-bin-at.

selfcheck(){
  local n=0 f=0 rc out d w o sha old before named
  k(){ n=$((n+1)); if [ "$1" = 0 ]; then echo "  ok   $2"; else echo "  FAIL $2"; f=$((f+1)); fi; }
  T=$(mktemp -d); trap 'rm -rf "$T"' EXIT   # T is not local: the EXIT trap fires outside this function
  # A CHECKOUT OF ITS OWN, under a temp dir: this box's core/bin is never read, and the only tree any case here can
  # damage is this one. Its bin/ carries a tracked symlink because the real one does, and that is the entry a copy
  # gets wrong. cc-alpha is then edited in the worktree so "at main" and "on disk" are different bytes. A first
  # commit, "old", has no tests/selfcheck; main adds cc-gamma, a tool whose case file sits there, as most tools' do.
  R=$T/repo; mkdir -p "$R/core/bin" "$R/core/mail"
  printf '#!/usr/bin/env bash\necho alpha-at-main\n' > "$R/core/bin/cc-alpha"; chmod 755 "$R/core/bin/cc-alpha"
  printf 'beta-at-main\n' > "$R/core/bin/cc-beta"; chmod 644 "$R/core/bin/cc-beta"
  printf 'receiver-at-main\n' > "$R/core/mail/receiver.py"
  ln -s ../mail/receiver.py "$R/core/bin/cc-post"
  g -C "$R" init -q -b main >/dev/null 2>&1
  g -C "$R" add -A >/dev/null 2>&1
  g -C "$R" -c user.email=selfcheck@invalid -c user.name=selfcheck -c commit.gpgsign=false commit -qm old >/dev/null 2>&1
  old=$(g -C "$R" rev-parse HEAD)
  mkdir -p "$R/core/tests/selfcheck"
  # shellcheck disable=SC2016   # the $(…) is the fixture tool's own code, expanded when IT runs
  printf '#!/usr/bin/env bash\n. "$(dirname "$(dirname "$(readlink -f "$0")")")/tests/selfcheck/cc-gamma.sh"\n' > "$R/core/bin/cc-gamma"
  chmod 755 "$R/core/bin/cc-gamma"; printf 'echo gamma-case-at-main\n' > "$R/core/tests/selfcheck/cc-gamma.sh"
  g -C "$R" add -A >/dev/null 2>&1
  g -C "$R" -c user.email=selfcheck@invalid -c user.name=selfcheck -c commit.gpgsign=false commit -qm main >/dev/null 2>&1
  sha=$(g -C "$R" rev-parse HEAD)
  printf 'edited-in-worktree\n' >> "$R/core/bin/cc-alpha"
  B(){ TMPDIR=$T "$SELF" -C "$R/core/bin" "$@"; }
  # The fixture checkout's every regular file, by content: what a clobber through a copy would change.
  fp(){ find "$R" -path "$R/.git" -prune -o -type f -print0 | sort -z | xargs -0 md5sum 2>/dev/null | md5sum; }
  printf 'CLOBBERED\n' > "$T/clob"

  d=$(B main); rc=$?
  k "$([ $rc = 0 ] && [ -d "$d" ] && echo 0 || echo 1)" "<ref> makes the directory and prints its path"
  # …and if it printed nothing, every case below still has a path that goes nowhere to work with. An empty $d
  # would make `"$d"/*` glob the ROOT of this box, and the cp cases below would then walk it.
  [ -n "$d" ] || d=$T/no-copy-was-made
  k "$(grep -qx 'echo alpha-at-main' "$d/cc-alpha" && ! grep -q edited-in-worktree "$d/cc-alpha" && echo 0 || echo 1)" "…holding the REF's bytes, not the edited worktree's"
  k "$([ -x "$d/cc-alpha" ] && [ ! -x "$d/cc-beta" ] && echo 0 || echo 1)" "…with the exec bit each file has at that ref"
  k "$([ -z "$(find "$d" -type l -print -quit)" ] && echo 0 || echo 1)" "NO SYMLINK ANYWHERE IN THE COPY — the one thing this tool promises"
  k "$([ -f "$d/cc-post" ] && [ "$(cat "$d/cc-post")" = receiver-at-main ] && echo 0 || echo 1)" "…and the tracked symlink is a real file holding its target's bytes at that ref"
  k "$([ "$(cd "$T" && "$d/cc-alpha")" = alpha-at-main ] && echo 0 || echo 1)" "the copy is a usable BIN dir: a sibling runs out of it, which is what a baseline selfcheck needs"
  k "$([ "$(B "$sha" | wc -l)" = 1 ] && echo 0 || echo 1)" "any ref, a bare sha included, and the path is the only thing printed"
  k "$([ "${d##*/}" = bin ] && [ "$(cd "$T" && "$d/cc-gamma")" = gamma-case-at-main ] && echo 0 || echo 1)" "the path printed is DIR/bin, and a tool whose cases sit in tests/selfcheck runs them out of the copy, at the ref"
  o=$(B "$old"); [ -n "$o" ] || o=$T/no-copy-was-made
  k "$([ -f "$o/cc-alpha" ] && [ ! -e "$o/../tests" ] && echo 0 || echo 1)" "…while a ref from before tests/selfcheck existed copies bin/ alone"

  # THE INCIDENT, both halves. Every file in the copy overwritten with `cp`, the verb both incidents used, and the
  # source checkout must come back byte for byte — its bin/ and the mail/ file the tracked symlink pointed at.
  before=$(fp)
  for p in "$d"/* "$d"/../tests/selfcheck/*; do cp "$T/clob" "$p"; done
  k "$([ "$before" = "$(fp)" ] && echo 0 || echo 1)" "cp over every file in the copy, its cases included, and the source checkout is byte-identical — the incident cannot happen through this copy"
  # CONTROL — THE OLD WAY, so the case above is known to be able to fail. A symlink into the fixture checkout (never
  # a real one: this whole tree is under the temp dir), the same cp, and the checkout MUST change. Without it, an
  # fp() that had stopped seeing anything would pass the case above in silence.
  mkdir "$T/farm"; ln -s "$R/core/bin/cc-alpha" "$T/farm/cc-alpha"; cp "$T/clob" "$T/farm/cc-alpha"
  k "$([ "$before" != "$(fp)" ] && grep -q CLOBBERED "$R/core/bin/cc-alpha" && echo 0 || echo 1)" "control: the same cp through a hand-made symlink farm DOES overwrite the checkout, so the case above can fail"
  g -C "$R" checkout -q -- core/bin/cc-alpha; printf 'edited-in-worktree\n' >> "$R/core/bin/cc-alpha"

  w=$(B worktree); [ -n "$w" ] || w=$T/no-copy-was-made
  k "$(grep -q edited-in-worktree "$w/cc-alpha" && echo 0 || echo 1)" "'worktree' copies what is on disk right now, uncommitted edits and all"
  k "$([ -z "$(find "$w" -type l -print -quit)" ] && [ "$(cat "$w/cc-post")" = receiver-at-main ] && echo 0 || echo 1)" "…with no symlink in it either, the tracked one resolved to its bytes"
  k "$(cmp -s "$w/../tests/selfcheck/cc-gamma.sh" "$R/core/tests/selfcheck/cc-gamma.sh" && echo 0 || echo 1)" "…and the checkout's tests/selfcheck beside it"
  before=$(fp); for p in "$w"/* "$w"/../tests/selfcheck/*; do cp "$T/clob" "$p"; done
  k "$([ "$before" = "$(fp)" ] && echo 0 || echo 1)" "…and a cp over every file in THAT copy leaves the checkout byte-identical too"

  named=$T/named; out=$(B main "$named"); rc=$?
  k "$([ $rc = 0 ] && [ "$out" = "$named/bin" ] && [ -f "$named/bin/cc-alpha" ] && [ -f "$named/tests/selfcheck/cc-gamma.sh" ] && echo 0 || echo 1)" "a named DIR is made and used: bin/ and tests/selfcheck/ in it, DIR/bin printed"
  out=$(B main "$named" 2>&1); rc=$?
  k "$([ $rc != 0 ] && grep -q 'already exists' <<<"$out" && [ -f "$named/bin/cc-alpha" ] && echo 0 || echo 1)" "…and a DIR that already exists is refused, never written into"
  out=$(B main "$R/scratchbin" 2>&1); rc=$?
  k "$([ $rc != 0 ] && [ ! -e "$R/scratchbin" ] && grep -q 'inside the checkout' <<<"$out" && echo 0 || echo 1)" "a DIR inside a checkout is refused — the same accident one step removed"
  before=$(ls -d "$T"/cc-bin-at.* 2>/dev/null | wc -l)
  out=$(B no-such-ref 2>&1); rc=$?
  k "$([ $rc != 0 ] && grep -q 'no ref called' <<<"$out" && [ "$before" = "$(ls -d "$T"/cc-bin-at.* 2>/dev/null | wc -l)" ] && echo 0 || echo 1)" "an unknown ref fails, says so, and leaves no half-made directory behind"
  out=$("$SELF" -C "$T/farm" main 2>&1); rc=$?
  k "$([ $rc != 0 ] && grep -q 'not inside a git checkout' <<<"$out" && echo 0 || echo 1)" "a bin/ outside any checkout has no ref to read, and is told so rather than half-copied"

  k "$([ "$(g -C "$R" status --porcelain)" = " M core/bin/cc-alpha" ] && echo 0 || echo 1)" "after every case above, the source checkout holds only the edit this selfcheck made: the tool reads it and writes nothing"
  echo "cc-bin-at selfcheck: $((n - f)) passed, $f failed"
  [ "$f" -eq 0 ]; }
