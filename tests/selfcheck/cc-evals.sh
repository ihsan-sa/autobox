# shellcheck shell=bash disable=SC2154,SC2034
# cc-evals's selfcheck cases, moved out of bin/cc-evals. That tool's selfcheck() sources this file, whose
# definition replaces it, and then calls it: the cases run in the tool's own shell, with its functions and
# globals, as they did when the body sat there. SC2154/SC2034 are off because those globals live in bin/cc-evals.

selfcheck(){
  local n=0 fl=0 d out
  k(){ n=$((n+1)); if [ "$1" = 0 ]; then echo "  ok   $2"; else echo "  FAIL $2"; fl=$((fl+1)); fi; }
  t(){ if "$@" >/dev/null 2>&1; then echo 0; else echo 1; fi; }
  # The trap clears itself: a RETURN trap outlives the function that set it, so it would fire again as the stub in
  # bin/cc-evals returns, with this local gone and whatever $d means out there (in cc-evals, the repo's evals/cases).
  d=$(mktemp -d); trap 'rm -rf "$d"; trap - RETURN' RETURN
  # a repo of its own with two commits, so "base" and "head" are real and frozen
  git init -q "$d/repo"; mkdir -p "$d/repo/bin"
  printf '#!/bin/sh\necho old\n' > "$d/repo/bin/thing"; chmod +x "$d/repo/bin/thing"
  git -C "$d/repo" -c user.email=t@t -c user.name=t add -A >/dev/null
  git -C "$d/repo" -c user.email=t@t -c user.name=t commit -qm base
  local BASE; BASE=$(git -C "$d/repo" rev-parse HEAD)
  printf '#!/bin/sh\necho new\n' > "$d/repo/bin/thing"
  git -C "$d/repo" -c user.email=t@t -c user.name=t commit -qam head
  mkdir -p "$d/cases" "$d/state"
  mk(){ { printf '# @set: %s\n# @kind: %s\n# @base: %s\n# @title: %s\n' "$2" "$3" "$4" "$5"; printf '%s\n' "$6"; } > "$d/cases/$1.sh"; }
  mk good regression replay "$BASE" 'the fix is in'          'probe(){ [ "$("$CC_EVALS_BIN"/thing)" = new ]; }'
  mk vac  regression replay "$BASE" 'passes everywhere'      'probe(){ true; }'
  mk bad  regression replay "$BASE" 'broken at head'         'probe(){ false; }'
  mk inc  regression replay "$BASE" 'cannot run'             'probe(){ exit 2; }'
  mk prop regression property ""    'no base needed'         'probe(){ [ -x "$CC_EVALS_BIN"/thing ]; }'
  mk paid regression property ""    'reports its own spend'  'probe(){ echo cost=0.25 >> "$CC_EVALS_METRICS"; echo loops=3 >> "$CC_EVALS_METRICS"; }'
  mk hom  regression property ""    'gets a scratch HOME'    'probe(){ [ "$HOME" != "'"$HOME"'" ] && [ -d "$HOME" ]; }'
  mk pipe regression property ""    'pipes into an early exit'  'probe(){ seq 1 100000 | grep -q 7; }'
  mk gred regression property ""    'reads stdin greedily'      'probe(){ cat >/dev/null; }'
  mk cap  capability capability ""  'graded against a ref'   'probe(){ echo "the answer"; }'
  mk cap2 capability capability ""  'graded, never blessed'  'probe(){ echo "another answer"; }'
  mk capreg regression capability "" 'graded, in the nightly set' 'probe(){ echo "a third answer"; }'
  # the runner tests the tree it LIVES in, so the fixture repo gets its own copy of it — that is what makes
  # "base" and "head" below real commits rather than two directories that happen to differ
  cp "$(readlink -f "$0")" "$d/repo/bin/cc-evals"; local RB="$d/repo/bin"
  E(){ env CC_EVALS_HOME="$d/state" CC_EVALS_CASES="$d/cases" CC_EVALS_REFS="$d/state/refs" "$RB/cc-evals" "$@" 2>&1; }
  out=$(E run --set regression --case good); k $? "a replay that fails on base and passes at head is PASS"
  k "$(t grep -q '^  PASS ' <<<"$out")" "…and says PASS"
  out=$(E run --set regression --case vac); k "$(t test $? -ne 0)" "a probe that passes on base too is red"
  k "$(t grep -q 'VACUOUS' <<<"$out")" "…and is named VACUOUS, not counted green (an eval that cannot fail proves nothing)"
  out=$(E run --set regression --case bad); k "$(t test $? -ne 0)" "a probe that fails at head is red"
  k "$(t grep -q '^  FAIL ' <<<"$out")" "…and says FAIL"
  out=$(E run --set regression --case inc); k "$(t test $? -ne 0)" "rc 2 in the regression set is RED: a baseline that cannot run is not a baseline that holds"
  k "$(t grep -q 'INCONCLUSIVE' <<<"$out")" "…named INCONCLUSIVE, never PASS, and it is not counted as one"
  k "$(t grep -qE 'RED — 0/1 passed' <<<"$out")" "…so an all-inconclusive run can never print green"
  out=$(E run --set regression --case prop); k $? "a property case needs no base"
  out=$(E run --set regression --case paid --json)
  k "$(t grep -qE '"cost_usd": *0\.25' <<<"$out")" "a probe's own spend is recorded, not guessed"
  k "$(t grep -qE '"loops": *3' <<<"$out")" "…and so are its loops"
  k "$(t grep -q '"verdict": *"FAIL"' <<<"$out")" "a regression case that SPENDS is red — free is a rule, not a promise in the docs"
  k "$(t grep -q 'must be free' <<<"$out")" "…and is told where spend belongs (the capability set)"
  out=$(E run --set regression --case hom); k $? "a probe gets a scratch HOME, never the caller's"
  out=$(E run --set regression --case pipe); k $? "a probe is judged on its own answer, not the runner's pipefail"
  out=$(E run --set regression --case gred); k $? "a probe that reads stdin gets none of it…"
  out=$(E run --set regression)
  k "$(t test "$(grep -c '^  [A-Z]' <<<"$out")" = "$(grep -l '@set: regression' "$d"/cases/*.sh | wc -l)")" \
    "…and cannot eat the case list: every case runs, not just the ones before it"
  out=$(E run --set regression); k "$(t test $? -ne 0)" "one red case makes the whole run red"
  k "$(t grep -q 'cc-evals: RED' <<<"$out")" "…and the last line is the verdict, red or green"
  k "$(t grep -qv 'graded against a ref' <<<"$(grep '^  ' <<<"$out")")" "--set regression leaves the capability set out"
  out=$(E run --set capability); local caprc=$?
  k "$(t grep -q 'SKIP' <<<"$out")" "a capability case with no blessed reference is SKIP, not red — a fresh box has no refs"
  k "$caprc" "…and does not make the run red"
  out=$(E run --set regression --case capreg); k "$(t test $? -ne 0)" \
    "…but an unblessed graded case in the NIGHTLY set is red: a nightly gate that grades nothing is not a gate"
  # ## bless — a person's act. Everything below proves the wall, because a worker that can re-bless grades itself.
  out=$(E bless cap 2>&1); k "$(t test $? -eq 3)" "bless refuses with no terminal (a session, a hook, a gate — none of them is the owner)"
  k "$(t grep -q 'refusing' <<<"$out")" "…and says which wall it hit"
  k "$(t test ! -e "$d/state/refs/cap.ref")" "…and wrote nothing"
  # the allowed path needs a real terminal, so the fixture gets one: `script` is the only pty this gate can borrow.
  bl(){ script -qec "env CC_EVALS_HOME='$d/state' CC_EVALS_CASES='$d/cases' CC_EVALS_REFS='$d/state/refs' '$RB/cc-evals' bless $1" /dev/null; }
  if command -v script >/dev/null 2>&1; then
    CC_ROLE=worker bl cap >/dev/null 2>&1; k "$(t test $? -eq 3)" "a worker is refused AT a terminal too — CC_ROLE is the wall, not the tty"
    mkdir -p "$d/track/.cc"; : > "$d/track/.cc/track"
    ( cd "$d/track" && bl cap ) >/dev/null 2>&1; k "$(t test $? -eq 3)" "…and so is anything run inside a track worktree"
    k "$(t test ! -e "$d/state/refs/cap.ref")" "…neither of them left a reference behind"
    # …from $d, not from wherever the gate was invoked: this selfcheck's own home is usually a track worktree, and
    # being refused there is the wall working, not a failure
    ( cd "$d" && unset CC_ROLE && bl cap ) >/dev/null 2>&1; k $? "the owner, at a terminal, outside a worktree, can bless"
    k "$(t test -s "$d/state/refs/cap.ref")" "…and that writes the reference"
  else echo "  --   no script(1) here: the allowed half of the bless wall is unchecked, and so are the refs below"; fi
  if [ -s "$d/state/refs/cap.ref" ]; then
    out=$(E run --set capability --case cap); k $? "a blessed capability case passes"
    k "$(t grep -q '^  PASS ' <<<"$out")" "…against the hidden reference"
    out=$(E run --set capability --case cap2); k "$(t test $? -ne 0)" \
      "…and once this box holds refs, a case whose own ref is MISSING is red: deleting one must not read as a skip"
    # ## rc 2 in the graded set. Run on `cap`, whose ref IS blessed, so what is under test is the rc handling and
    # not the missing-ref arm above it. Both halves: no answer is soft, a wrong answer is still red.
    mk cap capability capability "" 'graded against a ref' 'probe(){ echo "a limit, not an answer"; return 2; }'
    out=$(E run --set capability --case cap)
    k "$(t grep -q '^  INCONCLUSIVE ' <<<"$out")" \
      "a graded question that never reached a model is INCONCLUSIVE, not FAIL — a usage limit is not the model answering wrong"
    k "$(if grep -q '^  FAIL ' <<<"$out"; then echo 1; else echo 0; fi)" \
      "…and nothing in that run is reported as a failure"
    mk cap capability capability "" 'graded against a ref' 'probe(){ echo "a wrong answer"; return 1; }'
    out=$(E run --set capability --case cap)
    k "$(t grep -q '^  FAIL ' <<<"$out")" "…while a probe that ran and said no is still red: the soft arm is rc 2 alone"
    mk cap capability capability "" 'graded against a ref' 'probe(){ echo "the answer"; }'

    # ## refs — the four properties that make "hidden" true
    k "$(t grep -qv 'the answer' "$d/state/refs/cap.ref")" "the reference is a DIGEST: the expected output is not in it"
    k "$(t test "$(stat -c %a "$d/state/salt")" = 600)" "the salt is not readable by anyone else — without it the digest cannot be reproduced"
    printf 'the answer\n' | sha256sum | cut -d' ' -f1 > "$d/plain"
    k "$(t test "$(cat "$d/state/refs/cap.ref")" != "$(cat "$d/plain")")" "the digest is SALTED: guessing the output does not reproduce it"
  fi
  # scoped to evals/: this runs on every land, and a `*.ref` fixture or a `salt` script anywhere else in the repo is
  # not this suite's business — a gate that fails forever on an unrelated filename is a gate someone deletes
  k "$(t test -z "$(git -C "$TOP" ls-files -- evals 2>/dev/null | grep -E '(^|/)(salt|.*\.ref)$' | head -1)")" \
    "no reference is tracked in git NOW"
  k "$(t test -z "$(git -C "$TOP" log --all --pretty=format: --name-only --diff-filter=A -- evals 2>/dev/null | grep -E '(^|/)(salt|.*\.ref)$' | head -1)")" \
    "…nor was one ever committed — a worker checkout cannot read the answers out of history either"
  k "$(t sh -c '[ ! -d "$1" ] || ! git -C "$1" rev-parse --show-toplevel' sh "$REFS")" \
    "the live refs directory is outside every git tree"
  # ## ask — the door from a probe to a model, on a FAKE one: what is under test is the wall around the call, and a
  # suite that spent real money to check its own plumbing would be a suite nobody runs.
  cat > "$d/fakeclaude" <<'FAKE'
#!/bin/sh
cat >/dev/null
echo call >> "$FAKE_CALLS"
printf '%s\n' "$*" > "$FAKE_ARGV"
printf '%s\n' "$FAKE_JSON"
FAKE
  chmod +x "$d/fakeclaude"
  local OK='{"is_error":false,"result":"FAKE-ANSWER","total_cost_usd":0.011}'
  A(){ env CC_EVALS_HOME="$d/state" CC_EVALS_CASES="$d/cases" CC_EVALS_REFS="$d/state/refs" \
        CC_EVALS_CLAUDE="$d/fakeclaude" FAKE_CALLS="$d/calls" FAKE_ARGV="$d/argv" FAKE_JSON="$1" \
        CC_EVALS_METRICS="$d/metrics" "$RB/cc-evals" "${@:2}" 2>&1; }
  absent(){ if grep -q "$1" <<<"$2"; then echo 1; else echo 0; fi; }
  : > "$d/calls"; : > "$d/metrics"; : > "$d/argv"
  out=$(A "$OK" ask <<<'a question'); k $? "ask hands back the model's answer"
  k "$(t test "$out" = FAKE-ANSWER)" "…and only the answer"
  k "$(t grep -q 'cost=0.011' "$d/metrics")" "…with the spend appended to the probe's metrics, not left to the case"
  k "$(t test "$(wc -l < "$d/calls")" = 1)" "…asked once"
  # THE WALL, ON THE ARGV THAT WAS ACTUALLY SENT — a list that is right in the file and never reaches the call is
  # the same hole. Until 2026-09-06 this call passed no --disallowedTools at all, so `--tools ""` was the whole of
  # it, and the .ask shim hands the process the REAL home.
  k "$(t sh -c 'for f in --tools --setting-sources --strict-mcp-config --disallowedTools; do
                  grep -qF -- "$f" "$1" || exit 1; done' sh "$d/argv")" \
    "the call carries its whole wall: no tools, no settings file, no MCP server, and the escape hatches named — \`Bash\` alone is not enough, a probe once reached the shell through \`Monitor\`"
  # THE DRIFT CASE. cc-audit's SECRET_PATHS is the canonical list and is READ from that file, never spelled out
  # again here: hand-copying it is what left .cc/secrets out of three files and .cc/members out of six. MISSING,
  # never DIFFERENT — this call may deny more than cc-audit does and may never deny less. A cc-audit that cannot
  # be read or parsed leaves $cp empty and the case goes RED, because a drift case that has stopped checking must
  # not report green. The real cc-audit, beside the real cc-evals: $RB is a fixture copy with no siblings.
  local cp bad s; cp=$(sed -n 's/^SECRET_PATHS="\(.*\)"$/\1/p' "$R/bin/cc-audit" 2>/dev/null)   # $R, not $0: cwd may have moved
  bad=""; set -f; for s in $cp; do   # set -f: the case reads the same globs the call does, and must not expand them either
    grep -qF -- "Read(/$HOME/$s)" "$d/argv" && grep -qF -- "Grep(/$HOME/$s)" "$d/argv" || bad="$bad $s"
  done; set +f
  k "$(t test -n "$cp" -a -z "$bad")" \
    "…and every secret store cc-audit denies is denied here too, by path, to Read and to Grep alike${bad:+ — missing:$bad}"
  k "$(t sh -c '! grep -qF -- "Read(/$1/.cc/state)" "$2"' sh "$HOME" "$d/argv")" \
    "…and those paths and no others — a case that could not tell a missing one apart proves nothing"
  # …AND THE LIST SURVIVES THE CWD. The case above runs where nothing matches, so it passed while the loop was
  # glob-expanding: found in review of #294. Run it where `.cc/members/*` DOES match and the difference shows.
  mkdir -p "$d/glob/.cc/members/alice" "$d/glob/.cc/secrets"; : > "$d/glob/.cc/secrets/app.pem"
  : > "$d/argv"; (cd "$d/glob" && A "$OK" ask <<<'q' >/dev/null 2>&1)
  k "$(t sh -c 'grep -qF -- "Read(/$1/.cc/members/**)" "$2" && ! grep -qF -- "Read(/$1/.cc/members/alice)" "$2"' \
        sh "$HOME" "$d/argv")" \
    "…and it is the list, not whatever the working directory held: started beside a real \`.cc/members/alice\`, the rule still reads \`.cc/members/**\` and never the directory it would have expanded to"
  : > "$d/calls"
  out=$(A '{"is_error":false,"result":"prose","structured_output":{"verdict":"LAND"},"total_cost_usd":0}' ask <<<'q')
  k "$(t test "$out" = '{"verdict":"LAND"}')" "a schema answer comes back as the structure, not the prose beside it"
  : > "$d/calls"
  out=$(A '{"is_error":true,"result":""}' ask <<<'q'); k "$(t test $? -eq 2)" \
    "a question that got no answer is rc 2 — INCONCLUSIVE, which is not a model answering wrong"
  k "$(absent FAKE-ANSWER "$out")" "…and prints no answer of its own"
  k "$(t test "$(wc -l < "$d/calls")" = 2)" "…after exactly one retry: one blip must not throw away the questions already paid for"
  mk askcap capability capability "" 'reaches a model through ask' 'probe(){ printf q | "$CC_EVALS_ASK"; }'
  mk askreg regression property   "" 'reaches a model, in the free set' 'probe(){ printf q | "$CC_EVALS_ASK" >/dev/null; }'
  out=$(A "$OK" run --set capability --case askcap --show --no-record)
  k "$(t grep -q 'FAKE-ANSWER' <<<"$out")" "a probe reaches a model through the shim, with no credentials of its own"
  k "$(t grep -q '0.011' <<<"$out")" "…and that spend lands in the run's total"
  out=$(A "$OK" run --set capability --case askcap --no-record)
  k "$(absent FAKE-ANSWER "$out")" "…and without --show a graded case's output stays unread"
  out=$(A "$OK" run --set regression --case askreg --no-record); k "$(t test $? -ne 0)" \
    "a case that reaches a model in the FREE set is red — the door does not widen the rule it walks through"
  rm -f "$d/cases/askcap.sh" "$d/cases/askreg.sh"
  rm -rf "$d/cases"; mkdir -p "$d/cases"
  out=$(E run --set regression); k $? "a bare install with no cases exits 0"
  k "$(t grep -q 'no cases' <<<"$out")" "…and says so rather than reporting a green it did not earn"
  # replay the RETURN trap this run set, in the stub's shape (a function calling the one that set it): the
  # caller's own $d must survive the caller's return, or the trap fired twice
  local tp; tp=$(trap -p RETURN)
  k "$(t bash -c '[ -n "$1" ] || exit 1; c=$(mktemp -d); d=$c
    inner(){ local d; d=$(mktemp -d); eval "$1"; }; outer(){ inner "$1"; }; outer "$1"
    [ -d "$c" ] && rm -rf "$c"' _ "$tp")" "the scratch-dir trap clears itself, so it never removes the caller's \$d"
  echo "cc-evals selfcheck: $((n - fl)) passed, $fl failed"
  [ "$fl" -eq 0 ]
}
