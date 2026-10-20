# shellcheck shell=bash disable=SC2154,SC2034
# cc-config's selfcheck cases, moved out of bin/cc-config. That tool's selfcheck() sources this file, whose
# definition replaces it, and then calls it: the cases run in the tool's own shell, with its functions and
# globals, as they did when the body sat there. SC2154/SC2034 are off because those globals live in bin/cc-config.

selfcheck(){
  local n=0 f=0 out rc i   # T is NOT local: the EXIT trap that removes it fires outside this function
  k(){ n=$((n+1)); if [ "$1" = 0 ]; then echo "  ok   $2"; else echo "  FAIL $2"; f=$((f+1)); fi; }
  t(){ if "$@" >/dev/null 2>&1; then echo 0; else echo 1; fi; }
  T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
  # Fixture keys are neutral names (ALPHA/BETA…): core/ is published, and nothing in it may name a box.
  cat > "$T/config" <<'EOF'
# a comment, and a blank line follow

ALPHA=one
  BETA = "two"
GAMMA='three'
ALPHA=four
not a key at all
DOLLAR=$(touch @T@/pwned-file)
BACKTICK=`touch @T@/pwned-tick`
SEMI=x; touch @T@/pwned-semi
EOF
  sed -i "s#@T@#$T#g" "$T/config"
  C(){ CC_CONFIG="$T/config" "$SELF" "$@"; }

  k "$(t test "$(C get ALPHA)" = four)" "the last line for a key wins"
  k "$(t test "$(C get BETA)" = two)" "whitespace around key and value trimmed, one layer of quotes stripped"
  k "$(t test "$(C get GAMMA)" = three)" "single quotes too"
  C get ALPHA >/dev/null; k $? "a key that is set exits 0"
  k "$(t test "$(C get NOPE fallback)" = fallback)" "an absent key gives the default"
  C get NOPE fallback >/dev/null; rc=$?; k "$(t test $rc = 1)" "…and exits 1, so a caller can tell a default from a value"
  k "$(t test -z "$(C get NOPE)")" "an absent key with no default is empty"
  # PRECEDENCE — one rule, both directions
  k "$(t test "$(export ALPHA=env; C get ALPHA)" = env)" "the environment wins over the file"
  k "$(t test -z "$(export ALPHA=''; C get ALPHA)")" "…and a variable SET but EMPTY wins too ('KEY= cmd' means off)"
  out=$(C get CFG shell-state-must-not-leak); rc=$?
  k "$(t test "$out" = shell-state-must-not-leak -a "$rc" = 1)" "the shell's OWN variables (CFG) are nobody's environment — only printenv's world counts"
  ( export ALPHA=''; C get ALPHA >/dev/null ); k $? "…exiting 0: it was set, it was just empty"
  # NO EVAL — the whole reason this file exists
  k "$(t test "$(C get DOLLAR)" = '$(touch '"$T"'/pwned-file)')" "a \$(…) value is returned as literal characters"
  k "$(t test "$(C get BACKTICK)" = '`touch '"$T"'/pwned-tick`')" "…and a backtick value too"
  k "$(t test "$(C get SEMI)" = "x; touch $T/pwned-semi")" "…and a value with a ; command after it"
  k "$(t test ! -e "$T/pwned-file" -a ! -e "$T/pwned-tick" -a ! -e "$T/pwned-semi")" "reading the file executed NOTHING"
  C list >/dev/null; k $? "list reads the same file without executing it"
  k "$(t test ! -e "$T/pwned-file")" "…still nothing executed"
  k "$(t grep -qx 'not a key at all' "$T/config")" "a line that is not KEY=VALUE is left alone"
  # list
  out="$(C list)"
  k "$(t grep -qx 'ALPHA=four' <<<"$out")" "list gives each file key once, at its resolved value"
  k "$(t test "$(grep -c '^ALPHA=' <<<"$out")" = 1)" "…once, not once per line"
  k "$(t grep -qx 'ALPHA=env' <<<"$(export ALPHA=env; C list)")" "list applies the same precedence"
  out="$(export DELTA=only-in-env; C list DELTA)"
  k "$(t test "$out" = 'DELTA=only-in-env')" "a named key the environment alone has is listed, and nothing else is"
  k "$(t test "$(C list ALPHA)" = 'ALPHA=four')" "list KEY prints that one file key, not the whole file"
  k "$(t test -z "$(C list NOSUCH)")" "…and a named key set nowhere prints nothing"
  k "$(t test -z "$(export DELTA=only-in-env; C list | grep '^DELTA=')")" "…and is not, when it was not named"
  # set / unset
  C set NEW 'a value with spaces' && k 0 "set exits 0" || k 1 "set exits 0"
  k "$(t test "$(C get NEW)" = 'a value with spaces')" "…and reads back exactly"
  C set NEW 'second'
  k "$(t test "$(grep -c '^NEW=' "$T/config")" = 1)" "set replaces, it does not append a second line"
  k "$(t grep -q '^# a comment' "$T/config")" "…and keeps the comments"
  C set EVIL '$(touch '"$T"'/pwned-set)'
  k "$(t test "$(C get EVIL)" = '$(touch '"$T"'/pwned-set)' -a ! -e "$T/pwned-set")" "a \$(…) written by set stays a string"
  C unset NEW; k $? "unset exits 0 when the key was there"
  k "$(t test -z "$(C get NEW)")" "…and the key is gone"
  C unset NEVERSET >/dev/null 2>&1; rc=$?; k "$(t test $rc = 1)" "unset exits 1 when it was not"
  k "$(t test "$(stat -c %a "$T/config")" = 600)" "the file stays mode 600 — it holds tokens"
  C set BAD-NAME v >/dev/null 2>&1; rc=$?; k "$(t test $rc = 2)" "a key that is not a variable name is refused"
  C set MULTI "$(printf 'a\nb')" >/dev/null 2>&1; rc=$?; k "$(t test $rc = 2)" "a value with a newline is refused: it would forge a second key"
  # DENIED: the one file CC_CONFIG_DENY names reads as empty and is not written; any other file is untouched by it.
  D(){ CC_CONFIG_DENY="$T/config" "$SELF" "$@"; }
  out=$(CC_CONFIG="$T/config" D get ALPHA fallback); rc=$?
  k "$(t test "$out" = fallback -a "$rc" = 1)" "a denied file reads as empty: get gives the default and exits 1"
  k "$(t test -z "$(CC_CONFIG="$T/config" D list)")" "…and list prints nothing from it"
  k "$(t test "$(export ALPHA=env; CC_CONFIG="$T/config" D get ALPHA)" = env)" "…while the environment still wins (it is not the file)"
  ln -s "$T/config" "$T/alias"
  k "$(t test -z "$(CC_CONFIG="$T/alias" D get ALPHA)")" "the denial holds through a symlink to the same file (realpath)"
  CC_CONFIG="$T/config" D set ALPHA denied-write >/dev/null 2>&1; rc=$?
  k "$(t test "$rc" = 1 -a "$(C get ALPHA)" = four)" "set on the denied file exits 1 and writes nothing"
  k "$(t test "$(C get ALPHA)" = four)" "control: the same file, not denied, still reads"
  k "$(t test "$(CC_CONFIG="$T/config" CC_CONFIG_DENY="$T/other" "$SELF" get ALPHA)" = four)" "control: a denial naming another file changes nothing here"
  # LOCKING: twenty writers, each read-modify-writing the whole file. Unlocked, most of these keys are lost.
  : > "$T/many"
  for i in $(seq 1 20); do CC_CONFIG="$T/many" "$SELF" set "K$i" "v$i" & done
  wait 2>/dev/null
  k "$(t test "$(grep -c '^K[0-9]*=v[0-9]*$' "$T/many")" = 20)" "twenty concurrent writers all land (flock'd read-modify-write)"
  echo "cc-config selfcheck: $((n - f)) passed, $f failed"
  [ "$f" -eq 0 ]
}
