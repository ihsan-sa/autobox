# shellcheck shell=bash disable=SC2154,SC2034
# cc-audit's selfcheck cases, moved out of bin/cc-audit. That tool's selfcheck() sources this file, whose
# definition replaces it, and then calls it: the cases run in the tool's own shell, with its functions and
# globals, as they did when the body sat there. SC2154/SC2034 are off because those globals live in bin/cc-audit.
# recurring-defect-ok: pause-hold-missing — moved test cases: the board writes and dispatches are fixtures in a temp tree, never a real one

selfcheck(){
  local d n=0 f=0 out rc LOG POSTPONED DEFER_UNTIL
  d=$(mktemp -d "${TMPDIR:-/tmp}/cc-audit-sc.XXXXXX") || return 1   # dynamically scoped above: postponed/log see these, never the box's
  LOG="$d/audit.log"; out="$d/report.md"; POSTPONED=""; DEFER_UNTIL=""
  sck(){ n=$((n+1)); if [ "$1" = 0 ]; then echo "  ok   $2"; else echo "  FAIL $2"; f=$((f+1)); fi; }
  ntf(){ if "$@"; then echo 1; else echo 0; fi; }   # tf's inverse: the assertion is that the command FAILS
  export CC_SC_ARGV="$d/argv"

  local EV
  # 7b. THE WALL AROUND THE LLM PASSES — the deny list and the scrub. Both were short here: ~/.cc/secrets (this
  # box's GitHub App key and the ghs_ installation tokens cc-gh-token caches beside it) and ~/.cc/members (a
  # member's live Claude OAuth credential, mode 600, minted by `cc-sandbox mint`) were on no deny list, and scrub
  # matched Slack tokens only. Asserted here so a path or a token shape going missing is a red gate.
  # THIS FILE HOLDS THE CANONICAL PATH LIST, so its own case SPELLS THE PATHS OUT: a case that asserted
  # $SECRET_PATHS against the list that built it would go green when somebody empties the list, which is the bug
  # it is here for. The copies do the opposite — they read this file. Both halves are needed: this anchors the
  # content, theirs anchor the spread.
  local s
  for s in '.cc/config' '.cc/secrets/**' '.cc/members/**' 'ccbox/env' '.ssh/**' '.claude/.credentials.json' '.claude.json' '.config/gh/**'; do
    sck "$(tf grep -qF -- "Read(/$HOME/$s)" <<<"$DENY")" "deny: Read(/\$HOME/$s) — the LLM passes allow Read, so a path off this list is readable"
    sck "$(tf grep -qF -- "Grep(/$HOME/$s)" <<<"$DENY")" "deny: …and Grep(/\$HOME/$s) — denied to one tool and not the other is not denied"
  done
  sck "$(ntf grep -qF -- "Read(/$HOME/.cc/state)" <<<"$DENY")" "deny: the evidence dir under ~/.cc/state is still readable — this is a list of paths, not a blanket"

  local T36 sd; T36=a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1; sd="$d/scrub"; mkdir -p "$sd"; EV="$sd"
  { echo "slack xoxb-123456-abcdef"; echo "installation ghs_$T36"; echo "classic ghp_$T36"
    echo "fine-grained github_pat_$T36"; echo "anthropic sk-ant-api03-$T36"; echo "not a token ghx_$T36"; } > "$sd/01-ev.txt"
  scrub
  sck "$(ntf grep -q 'xoxb-123456' "$sd/01-ev.txt")" "scrub: a Slack token never reaches the evidence the model reads"
  sck "$(ntf grep -q "ghs_$T36" "$sd/01-ev.txt")" "scrub: nor a ghs_ installation token — the shape this box mints hourly, and the one the pattern missed"
  sck "$(ntf grep -q "ghp_$T36" "$sd/01-ev.txt")" "scrub: nor a ghp_ personal token"
  sck "$(ntf grep -q "github_pat_$T36" "$sd/01-ev.txt")" "scrub: nor a fine-grained github_pat_"
  sck "$(ntf grep -q "sk-ant-api03-$T36" "$sd/01-ev.txt")" "scrub: nor an Anthropic key"
  sck "$(tf grep -q "ghx_$T36" "$sd/01-ev.txt")" "scrub: …while ghx_ is left alone — the pattern is the token prefixes, not everything starting \`gh\`"
  sck "$(tf grep -q 'redacted-token' "$sd/01-ev.txt")" "scrub: and what it took out says so, rather than vanishing"

  # 8. THE MAIN-GATE ROW. Driven through the REAL cc-board — a stub would only prove this function talks to a stub —
  # against a throwaway $HOME, so every write lands in $d and the box's own board is never touched. `local HOME` is
  # what makes that true for the cc-board child too: bash's dynamic scope reaches exported variables.
  local HOME CTL SUITE_FAIL pass fail RPT   # NOT BOARD: it is an absolute sibling path and must survive the fake $HOME
  HOME="$d/home"; CTL=sc-repo; pass=0; fail=0; RPT=""
  # cc-audit's OWN rows skip cc-brief's gate (CC_BRIEF_MACHINE=1), but the hand-typed row below does not: it goes
  # through cc-brief's arithmetic over the brief's shape, which is all that gate is — nothing here asks a model.
  mkdir -p "$HOME/.cc"
  "$BOARD" init "$CTL" "$d/repo" main >/dev/null 2>&1
  local RED='tests/check.sh — ✗ the digest names the timezone'
  main_gate "$RED"
  sck "$(tf grep -q '^main is red: tests/check.sh' <<<"$(mg_get title)")" "main-gate: a red baseline puts ONE row on the board"
  sck "$(tf grep -q 'digest names the timezone' <<<"$(mg_get title)")" "main-gate: the row carries the failing gate AND the first line of the failure"
  sck "$(tf test "$(mg_get status)" = queued)" "main-gate: it lands \`queued\` — cc-reconcile reads any other live status with no worktree as broken"
  sck "$(tf test "$("$BOARD" tracks "$CTL" | grep -c .)" -eq 1)" "main-gate: exactly one row"
  sck "$(tf grep -q 'cc-audit checks --dry' <<<"$(mg_get instructions)")" "main-gate: whoever picks it up is told how to reproduce it"

  "$BOARD" json "$CTL" > "$d/board-1"
  main_gate "$RED"
  "$BOARD" json "$CTL" > "$d/board-2"
  sck "$(tf cmp -s "$d/board-1" "$d/board-2")" "main-gate: the SAME red again writes nothing at all — not a row, not a note, not a timestamp"
  sck "$(tf test "$("$BOARD" tracks "$CTL" | grep -c .)" -eq 1)" "main-gate: ...and never a second row"

  main_gate 'tests/selftest.sh — ✗ the 👍 runs the gates before it merges'
  sck "$(tf grep -q 'selftest.sh' <<<"$(mg_get title)")" "main-gate: a DIFFERENT failure updates the one row in place"
  sck "$(tf test "$("$BOARD" tracks "$CTL" | grep -c .)" -eq 1)" "main-gate: ...still one row"
  sck "$(tf test "$("$BOARD" json "$CTL" | jq '.tracks["main-gate"].notes | length')" -eq 2)" "main-gate: one note per CHANGE of failure, so the row carries its own history"

  main_gate ""
  sck "$(tf test "$("$BOARD" tracks "$CTL" | grep -c .)" -eq 0)" "main-gate: green closes the row — the board shows main red only while it IS red"
  "$BOARD" json "$CTL" > "$d/board-3"; main_gate ""; "$BOARD" json "$CTL" > "$d/board-4"
  sck "$(tf cmp -s "$d/board-3" "$d/board-4")" "main-gate: green twice writes nothing — the daily timer is silent on a healthy box"

  # once a session takes the row it is an ordinary track: cc-reconcile owns its status and this must stop writing
  main_gate "$RED"; mkdir -p "$HOME/.cc/worktrees/$CTL/$MG"
  "$BOARD" json "$CTL" > "$d/board-5"
  main_gate 'cc-units selfcheck — ✗ something else entirely'; main_gate ""
  "$BOARD" json "$CTL" > "$d/board-6"
  sck "$(tf cmp -s "$d/board-5" "$d/board-6")" "main-gate: once a worker is in its worktree, cc-audit never writes that row again"
  sck "$(tf test "$("$BOARD" tracks "$CTL" | grep -c .)" -eq 1)" "main-gate: ...and green does not yank a row somebody is working in"
  rmdir "$HOME/.cc/worktrees/$CTL/$MG"
  # a person takes the name over by renaming it: a re-add keeps an existing row's title (cc-board), so set it
  "$BOARD" set "$CTL" "$MG" title "somebody typed this row by hand" >/dev/null
  main_gate ""
  sck "$(tf test "$("$BOARD" tracks "$CTL" | grep -c .)" -eq 1)" "main-gate: a row on that name it did not write is never deleted — the only destructive step undoes its own work"
  "$BOARD" rm "$CTL" "$MG"

  # what feeds it: the FIRST red gate, and a line of the failure worth reading
  SUITE_FAIL=""
  gate 1 "tests/check.sh" "3 failed" "$(printf 'suite\n  ✓ a\n  ✗ the row it wrote was the wrong row\n  ✓ b\n')"
  gate 1 "tests/selftest.sh" "1 failed" "  ✗ a second red"
  sck "$(tf grep -q 'the row it wrote was the wrong row' <<<"$SUITE_FAIL")" "suites: the row gets the first line that FAILED, never the banner"
  sck "$(ntf grep -q 'selftest' <<<"$SUITE_FAIL")" "suites: the FIRST red gate owns the row — a second red is the same red, not a second row"
  SUITE_FAIL=""; gate 0 "tests/check.sh" "OK" "check.sh: OK"
  sck "$(tf test -z "$SUITE_FAIL")" "suites: a green gate feeds nothing"
  sck "$(tf test "$(fail_line "no marker anywhere in here" "== result: 2 failed ==")" = "== result: 2 failed ==")" "suites: output with no failure line falls back to the tally, rather than to a banner"
  sck "$(ntf grep -q $'\x1b' <<<"$(fail_line "$(printf '\033[31m  ✗ coloured\033[0m')" x)")" "suites: colour codes never reach the board title"
  local fl; fl=$(fail_line "$(printf '== s ==\n  ✓ when the link fails, cc-notify FAILS\nok 2 - FAIL path covered\n  ✗ the real red\n')" x)
  sck "$(tf test "$fl" = "✗ the real red")" "suites: a pass whose text says FAIL is never the row's failure line — the ✗ below it is"
  fl=$(fail_line "$(printf 'warning: Error budget low\n  ✓ a\n  ✗ what broke\n')" x)
  sck "$(tf test "$fl" = "✗ what broke")" "suites: a ✗ outranks an earlier line that only says Error"
  fl=$(fail_line "$(printf '  ✓ a\nFAIL: 1 case\n')" x)
  sck "$(tf test "$fl" = "FAIL: 1 case")" "suites: no ✗ at all, a FAIL line still names it"

  # 9. the two probes that were reading the wrong thing. Both failed SILENTLY — a green box looking red, and a busy
  # week costing $0.00 — which is the failure mode a check must not have, so both are pinned here.
  local st5; st5=$(printf 'tokens: bot set\nwho is heard: channels\npolicy: every channel answers\napprovals: #approvals\ndaemon: up 2508s, slack connected, bot U0B\nsubscribed sessions: somerepo [main]\n')
  out=$(slack_probe "$st5"); rc=$?
  sck $rc "slack probe: a connected daemon passes wherever its line sits — #92 pushed it to line 5 and line 3 became policy"
  sck "$(tf grep -q '^daemon: up 2508s' <<<"$out")" "slack probe: the row names the daemon line, not whichever line is third"
  out=$(slack_probe "$(printf 'tokens: bot set\npolicy: x\ndaemon: down, slack disconnected\n')"); rc=$?
  sck "$(tf test $rc -ne 0)" "slack probe: a daemon that is actually down still fails"
  out=$(slack_probe ""); rc=$?
  sck "$(tf test $rc -ne 0)" "slack probe: no output at all is a failure, not a pass"
  sck "$(tf test "$out" = "no status")" "slack probe: ...and says so"

  local rd="$d/state/w/runs"; mkdir -p "$rd"
  echo '{"total_cost_usd":1.25}' > "$rd/a.json"; echo '{"total_cost_usd":0.75}' > "$rd/b.json"
  sck "$(tf test "$(spend_since "$d/state" 0)" = 2.00)" "spend: the run costs are summed"
  : > "$rd/half-written.json"; echo '{"total_cost' > "$rd/corrupt.json"; echo '{"other":1}' > "$rd/nocost.json"
  sck "$(tf test "$(spend_since "$d/state" 0)" = 2.00)" "spend: one unparseable run json — a worker mid-run always has one — no longer zeroes the whole week"
  sck "$(tf test "$(spend_since "$d/state" $(( $(date -u +%s) + 60 )))" = 0.00)" "spend: nothing inside the window is \$0.00, not empty"
  sck "$(tf test "$(spend_since "$d/no-such-dir" 0)" = 0.00)" "spend: no state dir at all is \$0.00, not empty"

  # 10. the header: date and time from ONE UTC read, and the test override pins the date beside the time
  local DAY STAMP; CC_AUDIT_DATE=2026-01-01 stamp_init
  sck "$(tf grep -Eq '^# .+ audit — checks — 2026-01-01T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' <<<"$(header)")" "header: <local date>T<utc time>Z cannot happen — a fixed CC_AUDIT_DATE is the date beside the time"

  # 11. `failure <claim>`: the packet, two passes behind the same wall, one report, one message, no board row.
  # A HOME of its own: the stub model, cc-slack, cc-board and cc-notify sit in $HOME/bin, which line 3 puts first
  # on PATH; the ledger is CC_FAILURES; nothing reaches the box's own state, channel or board.
  local fh="$d/fhome" cl F; mkdir -p "$fh/bin" "$fh/.cc/failures"; F="$R/bin/cc-failures"
  cat > "$fh/bin/claude" <<'S'
#!/bin/sh
printf '%s\n' "$@" >> "$CC_SC_ARGV"
p=""; n=0; for a in "$@"; do [ "$n" = 1 ] && { p=$a; n=0; }; [ "$a" = -p ] && n=1; done
SPEND='{"type":"result","subtype":"success","is_error":true,"result":"You'"'"'ve hit your monthly spend limit · raise it at claude.ai/settings/usage","total_cost_usd":0,"num_turns":1}'
case "$CC_SC_END" in   # how the BROAD pass ends without a result, the way `claude -p --output-format json` really does (probed 2026-09-12)
  budget) printf '{"type":"result","subtype":"error_max_budget_usd","is_error":true,"result":null,"total_cost_usd":0.44,"num_turns":9}'; exit 1;;
  turns) printf '{"type":"result","subtype":"error_max_turns","is_error":true,"result":null,"total_cost_usd":0.21,"num_turns":60}'; exit 1;;
  timeout) exit 124;;   # what `timeout 20m` leaves the caller: rc 124 and nothing on stdout
  # AN UNLISTED SUBTYPE WITH AN EMBEDDED NEWLINE IN .result — llm_why's catch-all interpolates raw model text through
  # short(), which truncates at 160 chars but never collapses newlines: a marker with a real \n in it broke cc-failures'
  # one-line NOT_INVESTIGATED regex (`\A...`, `.` not matching newline) and the claim read back `reported`.
  newline) printf '{"type":"result","subtype":"error_during_execution","is_error":true,"result":"## pattern\\nrefusals on text","total_cost_usd":0.05,"num_turns":3}'; exit 0;;
  # THE BOX'S BILLING STATE, verbatim from i-b3fc3b8b's narrow pass (2026-09-12): subtype success, is_error true, and
  # the cap in .result. It names NO reset, which is why cc-limit answers "not a limit" and cc-audit has to tell it
  # from a model that ran and failed. exit 0, like the run that really did this one.
  spend) printf '%s' "$SPEND"; exit 0;;
  # …and the same refusal reaching only the NARROW pass, which is what i-b3fc3b8b was: the broad pass answers
  # normally (no arm matches here, so the prompt case below runs) and only the band's model is refused.
  spend-narrow) case "$p" in *"You are the narrow pass"*) printf '%s' "$SPEND"; exit 0;; esac;;
esac
case "$p" in
  *"You are the narrow pass"*) printf '{"result":"## hypothesis\\nthe guard reads the text, not the command\\n## message\\n**Decision:** review the guard.\\nPattern: three refusals on text.\\nHypothesis: text, not command.\\nCost so far: three turns.\\nNext review: the guard selfcheck.\\n","total_cost_usd":0.30}';;
  *) printf '{"result":"## pattern\\nrefusals on text\\n## test\\nrun the guard on the three commands\\nBAND: %s\\nTEST: %s\\n","total_cost_usd":0.05}' "${CC_SC_BAND:-interacting}" "${CC_SC_TEST:-yes}";;
esac
S
  printf '#!/bin/sh\nprintf "%%s\\n" "$@" >> "$HOME/slack.log"\n' > "$fh/bin/cc-slack"
  printf '#!/bin/sh\nprintf "%%s\\n" "$@" >> "$HOME/board.log"; [ "$1" = boards ] && exit 0; echo "{}"\n' > "$fh/bin/cc-board"
  printf '#!/bin/sh\nprintf "%%s\\n" "$@" >> "$HOME/notify.log"\n' > "$fh/bin/cc-notify"
  chmod +x "$fh"/bin/*
  # days ago, not fixed dates: the claim window is 14 days, so 2026-09-01..05 went ineligible on 2026-09-15 and emptied $cl
  local day; for day in 5 3 1; do CC_FAILURES="$fh/.cc/failures" "$F" record --scope sc --kind guard-policy/permitted-text-refused --observed "a grep pattern was refused" --ts "$(date -u -d "$day days ago" +%Y-%m-%dT%H:%MZ)" >/dev/null; done
  cl=$(CC_FAILURES="$fh/.cc/failures" "$F" claim | cut -f1)
  # THE NEGATIVE CONTROL for the line above: fixed calendar stamps are exactly what aged the old fixture out
  # (2026-09-01..05 went ineligible on 2026-09-15) — pinned here so a revert back to fixed dates reds this case,
  # not a calendar page three weeks out. Both halves ask `eligible`, never `claim`: the claim above spent the day's
  # one routine slot, which cc-failures counts across every scope, so a second claim is empty whatever the stamps say.
  local oldelig newelig; for day in 2020-01-01 2020-01-03 2020-01-05; do CC_FAILURES="$fh/.cc/failures" "$F" record --scope scold --kind guard-policy/permitted-text-refused --observed "a grep pattern was refused" --ts "${day}T00:00Z" >/dev/null; done
  oldelig=$(CC_FAILURES="$fh/.cc/failures" "$F" eligible --scope scold); newelig=$(CC_FAILURES="$fh/.cc/failures" "$F" eligible --scope sc)
  sck "$(tf test -z "$oldelig")" "failure fixture: stamps fixed on the calendar age out of the 14-day window — nothing eligible, the bug this fixture was filed on"
  sck "$(tf test -n "$newelig")" "…and the \"days ago\" stamps beside them are eligible whatever day this runs — one command, only the stamps differ"
  CC_SC_ARGV="$d/fargv"; : > "$CC_SC_ARGV"
  # off $R, not $0: line 58 already cd-ed, so a relative $0 (core/bin/cc-audit selfcheck from the repo root) no longer resolves
  # CC_LIMIT_STAMP is pinned at the fixture's own: cc-limit reads that hook ahead of $HOME, and selftest.sh exports one
  # of its own for the whole suite ("a test limit must never make a real loop wait"). Without it here, the usage-limit
  # case below wrote a stamp nothing read — green alone and red under the suite — and every other case ran against
  # whatever limit the caller's stamp happened to hold.
  fb(){ env HOME="$fh" CC_FAILURES="$fh/.cc/failures" CC_CLAUDE="$fh/bin/claude" CC_BOARD="$fh/bin/cc-board" CC_LIMIT_STAMP="$fh/.cc/state/claude-limit" CC_AUDIT_FAILURE_TO='#sc-test' "$@" "$R/bin/cc-audit" failure "$cl"; }
  out=$(fb 2>&1); rc=$?
  sck "$(tf test "$rc" = 0)" "failure: runs end to end against the stub model — rc 0, the report path on stdout"
  sck "$(tf test -s "$fh/.cc/failures/reports/$cl.md")" "failure: ONE report, at ~/.cc/failures/reports/<claim>.md, and show says reported"
  sck "$(tf grep -q "$cl reported" <<<"$(CC_FAILURES="$fh/.cc/failures" "$F" show --scope sc)")" "…and cc-failures show says so"
  sck "$(tf test "$(grep -cxF -- "$ALLOW" "$CC_SC_ARGV")" = 2)" "failure: THE WALL — both passes carry the allow-list: Read, Grep, Glob, LS and nothing else"
  local rh; rh=${DENY#*Read(/}; rh=${rh%%/.cc/config)*}   # the HOME the list above was built with: section 8 made HOME local
  sck "$(tf test "$(grep -cxF -- "${DENY//$rh/$fh}" "$CC_SC_ARGV")" = 2)" "failure: …and the deny-list: Bash, every escape hatch, the secret paths (under the child's own HOME)"
  sck "$(tf test "$(grep -c -- '^--strict-mcp-config$' "$CC_SC_ARGV")" = 2)" "failure: …and no MCP server, so no Slack tool to post with"
  sck "$(tf test "$(grep -c -- '^--setting-sources$' "$CC_SC_ARGV")" = 2)" "failure: …and no settings file, so the allow-list is the whole permission surface"
  sck "$(tf test "$(grep -A1 -- '^--model$' "$CC_SC_ARGV" | grep -v -- '^--' | paste -sd' ')" = 'claude-sonnet-5 claude-opus-5-5')" "failure: the broad pass is Sonnet; BAND: interacting sends the narrow pass to Opus"
  sck "$(ntf grep -q -- '^--effort$' "$CC_SC_ARGV")" "…and neither pass names an effort: both run at their model's own default"
  sck "$(tf test "$(grep -A1 -- '^--max-budget-usd$' "$CC_SC_ARGV" | grep -v -- '^--' | paste -sd' ')" = '0.60 1.95')" "failure: the strong cap is \$2 for the job — the narrow pass gets what the broad pass left"
  sck "$(tf test "$(grep -c '^post$' "$fh/slack.log")" = 1)" "failure: ONE message — no canvas, no second post"
  sck "$(tf grep -qx -- '--to' "$fh/slack.log" && grep -qx '#sc-test' "$fh/slack.log" && grep -q '^\*\*Review:\*\* review the guard\.' "$fh/slack.log" && grep -qx -- "$fh/.cc/failures/reports/$cl.md" "$fh/slack.log")" "…to the chat named, the five lines opening with what to review, the report as its file"
  sck "$(ntf grep -q 'Decision:' "$fh/slack.log")" "…and no \"Decision:\" head that reads like the owner's card"
  sck "$(ntf grep -q -- '--mention' "$fh/slack.log")" "…and no mention"
  sck "$(ntf test -s "$fh/board.log")" "failure: no board row — a finding cannot make work"
  sck "$(ntf test -s "$fh/notify.log")" "failure: no cc-notify — the one message is the whole delivery"
  sck "$(tf grep -q '^_investigation .* band interacting (claude-opus-5-5) .* ran ' "$fh/.cc/failures/reports/$cl.md")" "failure: the report's first line says the band, the model and what it cost"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$fh/.cc/failures/reports/$cl.md"
  out=$(fb CC_SC_BAND=authority 2>&1)
  sck "$(tf test "$(grep -A1 -- '^--model$' "$CC_SC_ARGV" | grep -v -- '^--' | paste -sd' ')" = 'claude-sonnet-5 claude-opus-5-5')" "failure: BAND: authority sends the narrow pass to Opus 5.5…"
  sck "$(tf test "$(grep -A1 -- '^--effort$' "$CC_SC_ARGV" | grep -v -- '^--' | paste -sd' ')" = xhigh)" "…at xhigh, and the broad pass names no effort"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$fh/.cc/failures/reports/$cl.md"
  # WHERE IT GOES BY DEFAULT, on its own fixture (no CC_AUDIT_FAILURE_TO): #<control repo>-updates, never top level
  # in #<control repo>. A post that fails there is ONE planner request to the seat, still no Slack card of his
  # (the child's control repo is $BOX: its HOME is the fixture's, so this copy is under no ~/dev/<repo>)
  out=$(fb CC_AUDIT_FAILURE_TO= 2>&1)
  sck "$(tf grep -qxF -- "#$BOX-updates" "$fh/slack.log" && ! grep -qxF -- "#$BOX" "$fh/slack.log" && ! test -s "$fh/notify.log")" "failure: by default the report goes to #<control repo>-updates, never top level in #<control repo>, and the seat is not asked"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$fh/.cc/failures/reports/$cl.md"
  local okslack; okslack=$(cat "$fh/bin/cc-slack")
  printf '#!/bin/sh\nprintf "%%s\\n" "$@" >> "$HOME/slack.log"; exit 1\n' > "$fh/bin/cc-slack"
  out=$(fb CC_AUDIT_FAILURE_TO= 2>&1)
  sck "$(tf test "$(grep -c -- '^--ask$' "$fh/notify.log")" = 1 && grep -qx "failure-report:$cl" "$fh/notify.log" && grep -q '^\*\*Review:\*\* review the guard\.' "$fh/notify.log" && grep -q " — report: $fh/.cc/failures/reports/$cl.md$" "$fh/notify.log" && ! grep -q -- '--decision' "$fh/notify.log")" "failure: a post the -updates lane refuses goes to the seat as ONE cc-notify --ask (stable --id), naming the report — never a decision card"
  printf '%s\n' "$okslack" > "$fh/bin/cc-slack"; rm -f "$fh/notify.log"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$fh/.cc/failures/reports/$cl.md"
  out=$(fb CC_SC_BAND=routine 2>&1)
  sck "$(tf test "$(grep -A1 -- '^--max-budget-usd$' "$CC_SC_ARGV" | grep -v -- '^--' | paste -sd' ')" = '0.60 0.95')" "failure: BAND: routine — Sonnet both passes, \$1 for the job"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$fh/.cc/failures/reports/$cl.md"
  # A BROAD PASS THAT ENDS WITHOUT A RESULT NAMES ITS CAUSE — in the report, the message and audit.log — never `rc=1`:
  # "the report said only '(audit run failed: rc=1)' ... and the owner had to ask why" (i-b3fc3b8b, 2026-09-12).
  local flog="$fh/.cc/state/audit/audit.log" frep="$fh/.cc/failures/reports/$cl.md"
  out=$(fb CC_SC_END=budget 2>&1); rc=$?
  sck "$(tf test "$rc" = 0 && test "$(grep -c -- '^--model$' "$CC_SC_ARGV")" = 1 && test -s "$frep")" "failure: a budget-killed broad pass still ends in a report, rc 0, and no narrow pass is bought on a missing handoff"
  sck "$(tf grep -q 'audit run failed: budget ran out: \$0\.44 spent of the \$0\.60 cap after 9 turns (claude-sonnet-5, subtype error_max_budget_usd)' "$frep")" "…the report's broad pass names the cause: budget, what was spent against which cap, the subtype"
  sck "$(tf grep -q 'no narrow pass: the broad pass ended without a handoff — budget ran out' "$frep")" "…and its narrow pass says the same where the reader lands"
  sck "$(tf grep -q 'model run ended without a result — budget ran out: \$0\.44' "$fh/slack.log")" "…the one message carries it too"
  sck "$(tf grep -q 'llm .*02-handoff.md failed: budget ran out: \$0\.44 .* subtype error_max_budget_usd' "$flog")" "…and so does audit.log"
  sck "$(ntf grep -Eq 'rc=1\b' "$frep" "$fh/slack.log")" "…no bare exit code anywhere a reason belongs"
  sck "$(tf grep -q 'Sonnet \$0\.44 + \$0\.00' "$frep")" "…the report says what it cost"
  # A GENUINE MODEL FAILURE STAYS A FAILED RUN. The pass ran, spent $0.44 and died on the cap: that is a result, and
  # telling a postponement from a failure must not turn it into one — `failed`, never `deferred`, in the report and in
  # what cc-failures reads off it. It comes back a day on, not at once: repeating it spends the cap again.
  sck "$(tf grep -qE '^\*\*Not investigated \(failed\):\*\* budget ran out: \$0\.44 .*· again after [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' "$frep")" "failure: a broad pass that ran and failed opens the report as failed, with the cause and when it comes back"
  sck "$(tf grep -q "$cl failed" <<<"$(CC_FAILURES="$fh/.cc/failures" "$F" show --scope sc)")" "…and cc-failures says failed, not reported: rc=1 is no longer a gravestone for a cluster nobody investigated"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$frep"
  # A NEWLINE IN THE MODEL'S OWN TEXT MUST NOT BREAK THE ONE-LINE MARKER (the exact shape of the motivating incident,
  # i-b3fc3b8b: subtype error_during_execution, is_error true, an embedded \n in .result). cc-failures' NOT_INVESTIGATED
  # regex is `\A...` with `.` not matching newline, so a marker split across two lines matches nothing and the claim
  # reads back `reported` — the gravestone this PR exists to remove.
  out=$(fb CC_SC_END=newline 2>&1); rc=$?
  sck "$(tf test "$rc" = 0 && test "$(grep -c -- '^--model$' "$CC_SC_ARGV")" = 1 && test -s "$frep")" "failure: an unlisted-subtype broad-pass error still ends in a report, rc 0, and no narrow pass is bought on a missing handoff"
  sck "$(tf grep -qE '^\*\*Not investigated \(failed\):\*\* subtype error_during_execution.*· again after [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' <<<"$(head -1 "$frep")")" "failure: a newline embedded in the model's own text is collapsed — the marker stays ONE line, whatever the model's raw text does"
  sck "$(tf grep -q "$cl failed" <<<"$(CC_FAILURES="$fh/.cc/failures" "$F" show --scope sc)")" "…so cc-failures still reads failed, not reported — a two-line marker matches nothing there"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$frep"
  out=$(fb CC_SC_END=turns 2>&1)
  sck "$(tf grep -q 'audit run failed: turns ran out: 60 turns, \$0\.21 spent (claude-sonnet-5, subtype error_max_turns)' "$frep" && grep -q 'failed: turns ran out' "$flog")" "failure: a turn-capped broad pass names that (error_max_turns), report and log"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$frep"
  out=$(fb CC_SC_END=timeout 2>&1)
  sck "$(tf grep -q 'audit run failed: timed out: the 20 min cap fell before claude-sonnet-5 answered (rc=124, no result JSON)' "$frep" && grep -q 'failed: timed out' "$flog" && ! grep -q 'no narrow pass: the broad pass did not run' "$frep")" "failure: a timed-out broad pass names the cap, not a bare rc"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$frep"
  # A PASS THAT NEVER RAN IS NOT A PASS THAT RAN AND FAILED (raised-a-postponed-investigation-counts-as-reported).
  # BOTH PASSES POSTPONED, on its own fixture: a live shared stamp two runs have hit, which is what makes cc-limit
  # answer `status` for every caller. llm() postpones before it spends, so no model is launched and the report that is
  # written must say it stands for nothing — it used to be indistinguishable from one an investigation wrote.
  mkdir -p "$fh/.cc/state"
  printf '%s\tbackoff:30\t%s\tsonnet\taaaaaaaa,bbbbbbbb\n' "$(( $(date +%s) + 1800 ))" "$(date +%s)" > "$fh/.cc/state/claude-limit"
  out=$(fb 2>&1); rc=$?
  sck "$(tf test "$rc" = 0 && test ! -s "$CC_SC_ARGV" && test -s "$frep")" "failure: both passes postponed on a usage limit — no model is launched at all, and a report is still written"
  sck "$(tf grep -qE '^\*\*Not investigated \(deferred\):\*\* Claude usage limit until [0-9]{2}:[0-9]{2}Z.*· again after [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' "$frep")" "…its first line is the deferral: why it never ran, and when it comes back"
  sck "$(tf grep -q "$cl deferred" <<<"$(CC_FAILURES="$fh/.cc/failures" "$F" show --scope sc)")" "…so cc-failures says deferred, not reported — the cluster is offered again instead of counting as investigated"
  sck "$(ntf grep -q 'audit run failed' "$frep")" "…and nothing in it is booked as a run that failed"
  rm -f "$fh/.cc/state/claude-limit"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$frep"
  # THE MONTHLY SPEND LIMIT IS THE BOX'S BILLING STATE (raised-monthly-spend-limit-reads-as-a-failed-run, i-b3fc3b8b):
  # the run reached the API and was refused, is_error true with the cap in .result and no reset for cc-limit to read.
  out=$(fb CC_SC_END=spend 2>&1); rc=$?
  sck "$(tf test "$rc" = 0 && test "$(grep -c -- '^--model$' "$CC_SC_ARGV")" = 1 && test -s "$frep")" "failure: a spend-limit refusal ends in a report, rc 0, and no narrow pass is bought on a refusal"
  sck "$(tf grep -qF "**Not investigated (deferred):** the account's monthly spend limit" "$frep")" "…the report calls it a refusal, not claude-sonnet-5 failing the task"
  sck "$(ntf grep -qE 'audit run failed|subtype success' "$frep")" "…so is_error beside a spend cap is no longer a failed model run"
  sck "$(tf grep -q 'llm .*02-handoff.md postponed: the account' "$flog")" "…and audit.log says postponed, where the ledger of what this box ran is read"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$frep"
  # THE SAME REFUSAL ONE PASS LATER, which is i-b3fc3b8b itself: the broad pass hands off and the NARROW pass, on the
  # band's model, is refused by the cap. The broad pass's work is real and stays in the report — but the discriminating
  # test never ran, so the report is not a result and the claim has to come back.
  out=$(fb CC_SC_END=spend-narrow 2>&1); rc=$?
  sck "$(tf test "$rc" = 0 && test "$(grep -c -- '^--model$' "$CC_SC_ARGV")" = 2 && test -s "$frep")" "failure: a narrow pass refused by the spend cap — both passes were launched, and a report is still written"
  sck "$(tf grep -qE '^\*\*Not investigated \(deferred\):\*\* the narrow pass was refused: the account.*· again after [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' "$frep")" "…the report opens as deferred and names the pass that was refused, not the model failing the task"
  sck "$(tf grep -q "$cl deferred" <<<"$(CC_FAILURES="$fh/.cc/failures" "$F" show --scope sc)")" "…so cc-failures says deferred, not reported: a test that never ran leaves the cluster to come back"
  sck "$(tf grep -q 'refusals on text' "$frep")" "…and the broad pass's handoff is still in the report: a deferral throws no work away"
  sck "$(tf grep -q 'not investigated (deferred), the pass was refused or postponed' "$fh/slack.log")" "…and the one message says so in the same words, not that a model run ended without a result"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$frep"
  out=$(fb CC_SC_TEST=none 2>&1); rc=$?
  sck "$(tf test "$rc" = 0 && test "$(grep -c -- '^--model$' "$CC_SC_ARGV")" = 1)" "failure: TEST: none — no discriminating test, so no narrow pass: one model context, not two"
  sck "$(tf grep -q 'no narrow pass' "$fh/.cc/failures/reports/$cl.md" && grep -q '^\*\*Investigation ' "$fh/slack.log")" "…the report says so and the message is the fallback line, still one post"
  : > "$CC_SC_ARGV"; rm -f "$fh/slack.log" "$fh/.cc/failures/reports/$cl.md"
  out=$(env HOME="$fh" CC_FAILURES="$fh/.cc/failures" CC_CLAUDE="$fh/bin/claude" "$R/bin/cc-audit" failure i-nope 2>&1); rc=$?
  sck "$(tf test "$rc" = 2 && ! test -s "$CC_SC_ARGV" && ! test -f "$fh/slack.log")" "failure: an id the ledger does not hold is refused before any model runs, rc 2, nothing posted"
  out=$(env HOME="$fh" CC_FAILURES="$fh/.cc/failures" CC_CLAUDE="$fh/bin/claude" "$R/bin/cc-audit" failure "$cl" --no-llm 2>&1); rc=$?
  sck "$(tf test "$rc" = 0 && ! test -s "$CC_SC_ARGV" && ! test -f "$fh/slack.log" && grep -q '^# failure packet' "$out")" "failure --no-llm: the packet is built and printed by path, no model runs, nothing is posted"
  out=$(env HOME="$fh" CC_FAILURES="$fh/.cc/failures" CC_CLAUDE="$fh/bin/claude" "$R/bin/cc-audit" failure "$cl" --dry 2>&1); rc=$?
  sck "$(tf test "$rc" = 0 && ! test -f "$fh/.cc/failures/reports/$cl.md" && ! test -f "$fh/slack.log" && grep -q '^## message' <<<"$out")" "failure --dry: the report prints, nothing is written under ~/.cc/failures and nothing is posted"
  unset -f fb

  # THE PIPELINE CHECK, in a ledger of the fixture's own: a bin dir whose cc-guard has lost its writer, and a
  # cc-failures that fails, are each ONE FAIL row naming the producer.
  local fb="$d/fbin" fl="$d/.cc/failures" CTLsave=$CTL FAILsave=$FAILURES RPTsave=$RPT
  mkdir -p "$fb" "$fl"; CTL=_ccauditsc; FAILURES="$R/bin/cc-failures"; export CC_FAILURES="$fl"
  RPT=""; pass=0; fail=0
  for p in $PRODUCERS; do printf '#!/bin/sh\ncc-failures record\n' > "$fb/$p"; done
  pipeline_check "$fb"
  sck "$(tf test "$fail" = 0 && grep -q 'every producer names cc-failures$' <<<"$RPT")" "pipeline check: a bin where every producer names the writer and the ledger writes → no FAIL row"
  RPT=""; pass=0; fail=0; printf '#!/bin/sh\necho no writer here\n' > "$fb/cc-guard"
  pipeline_check "$fb"
  sck "$(tf grep -q 'FAIL\*\* failure writers — every producer names cc-failures; broken: cc-guard$' <<<"$RPT")" "pipeline check: a producer whose writer is gone is ONE FAIL row naming it (cc-guard)"
  printf '#!/bin/sh\necho "ledger: disk full" >&2; exit 1\n' > "$fb/cc-failures"; chmod +x "$fb/cc-failures"
  RPT=""; pass=0; fail=0; FAILURES="$fb/cc-failures"; pipeline_check "$fb"
  sck "$(tf grep -q 'FAIL\*\* failure ledger — cc-failures record fails: ledger: disk full' <<<"$RPT")" "pipeline check: a ledger door that fails is a FAIL row saying what it said"
  CTL=$CTLsave; FAILURES=$FAILsave; RPT=$RPTsave; unset CC_FAILURES

  # 12. THE TIMER'S DAY, end to end: `auto` leaves the dated checks report behind and posts nothing. The Slack Home
  # tab and the #<repo> canvas both read the newest ~/.cc/state/audit/<date>-checks.md, so a timer that wrote only a
  # board row left them on a report days old — which is what a gate-only path that exited before the write did.
  # A TREE AND A HOME OF ITS OWN: cc-audit is COPIED into a fixture root (never linked — the prologue's `readlink -f
  # "$0"` would resolve a link straight back to this repo and run the real suites), whose tests/ is empty and whose
  # bin/ holds only the copy, so every gate fails fast; cc-slack, cc-notify, cc-board, journalctl and docker are stubs
  # in the fixture's own $HOME/bin, which line 3 puts first on PATH. Nothing of this box's is run, read or posted.
  local ah="$d/ahome" ar="$d/aroot" arep
  mkdir -p "$ah/bin" "$ar/bin" "$ar/tests"
  cp "$R/bin/cc-audit" "$ar/bin/cc-audit"; chmod +x "$ar/bin/cc-audit"
  printf '#!/bin/sh\nprintf "%%s\\n" "$@" >> "$HOME/slack.log"\n' > "$ah/bin/cc-slack"
  printf '#!/bin/sh\nprintf "%%s\\n" "$@" >> "$HOME/notify.log"\n' > "$ah/bin/cc-notify"
  printf '#!/bin/sh\nexit 0\n' > "$ah/bin/cc-board"
  printf '#!/bin/sh\nexit 0\n' > "$ah/bin/journalctl"
  printf '#!/bin/sh\nexit 0\n' > "$ah/bin/docker"
  chmod +x "$ah"/bin/*
  arep="$ah/.cc/state/audit/2026-01-02-checks.md"
  out=$(env HOME="$ah" CC_AUDIT_DATE=2026-01-02 CC_BOARD="$ah/bin/cc-board" "$ar/bin/cc-audit" auto 2>&1); rc=$?
  sck "$(tf test -s "$arep")" "auto: the timer still writes ~/.cc/state/audit/<date>-checks.md — the Home tab and the canvas read that file"
  sck "$(tf test "$rc" = 0)" "auto: …and ends rc 0, red gates and all: the report is the day's trace, not an error"
  sck "$(tf grep -q '^\*\*verdict: ' "$arep")" "auto: …the whole report, verdict line and all, not a stub of one"
  sck "$(ntf grep -qx canvas "$ah/slack.log")" "auto: …and the day is still quiet in Slack: no canvas"
  sck "$(ntf test -e "$ah/notify.log")" "auto: …and no cc-notify — the timer pages nobody"
  sck "$(ntf test -d "$ah/.cc/state/audit/2026-01-02-checks")" "auto: …and no empty evidence dir left behind, one per day"

  unset CC_SC_ARGV; rm -rf "$d"
  echo "cc-audit selfcheck: $((n - f)) passed, $f failed"
  [ "$f" -eq 0 ]
}
