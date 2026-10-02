#!/usr/bin/env bash
# generated from selftest.sh by split.py; edit selftest.sh and re-run split.py.
# suite-reporting.sh — the stanza "the suite's own reporting, and what a green run leaves behind", run alone on the fixtures it stands on.
. "$(dirname "$0")/lib.sh"
. "$(dirname "$SELF")/green.sh"   # this stanza calls what green.sh defines
# ── from selftest.sh's preamble: the machinery this stanza tests
qbad(){ local q; q=$(quarantined "$1" "✗ $2") && { ok "$q"; return 0; }; bad "$2"; }
# ── from selftest.sh's preamble: the machinery this stanza tests
land_scope "$B"
# ── from selftest.sh's preamble: the machinery this stanza tests
declare -A STANZA_TOOLS   # title -> the tools its lines drive, scanned once from this file
declare -A STANZA_HALF CHK_HALF   # …and which half of the suite runs it, DERIVED from the body — see below
# WHICH HALF A STANZA IS IN IS READ OFF ITS OWN BODY, never from a list somebody keeps. A stanza whose body is
# nothing but `chk cc-foo` lines is that tool's own selfcheck and nothing else: hermetic by chk's contract — its
# own temp root, its own HOME, its own fixtures — so it runs wherever the portable half runs. A stanza with a body
# of ITS OWN drives this machine end to end (the tmux session `main`, this box's systemd, its kernel, its ~/.cc)
# and stays here. That is the whole rule, and it cannot drift out of step with the file the way a list of forty
# titles would: adding a stanza classifies it, and turning a chk-only stanza into an end-to-end one moves it back
# to this box on the same commit.
while IFS=$'\t' read -r title tools half chks; do
  STANZA_TOOLS[$title]=$tools; STANZA_HALF[$title]=$half
  for c in $chks; do CHK_HALF[$c]=$half; done   # …and which half will READ each prefetched tool
done < <(awk -v have=" $(ls "$B" | tr '\n' ' ')" '
  function found(m) { if (index(" " tools " ", " " m " ") == 0) tools = tools " " m }
  function emit() { print title "\t" tools "\t" (other ? "box" : "portable") "\t" chks }
  /^(if )?stanza "/ { if (title != "") emit()
                      title = $0; sub(/^(if )?stanza "/, "", title); sub(/".*$/, "", title); tools = ""
                      chks = ""; other = 0; hdr = 1 }
  { line = $0
    # A body line that is not a comment, not blank, not the `then`/`fi` that wrap the stanza and not a bare `chk`
    # is a body of the stanza s OWN — which is what puts it in the box half. `then` is excluded for the same reason
    # as `fi`: it is the wrapper the half is enforced by, not something the stanza does.
    if (title != "" && !hdr && line !~ /^[ \t]*#/ && line !~ /^[ \t]*$/ && line != "fi" && line != "then" &&
        line !~ /^chk +cc-[a-z0-9-]+[ \t]*(#.*)?$/) other = 1   # `&&` ENDS the line: awk takes a continuation
                                                                # after an operator, never before one
    hdr = 0
    if (match(line, /(^|[ ;{(])chk +cc-[a-z0-9-]+/)) { m = substr(line, RSTART, RLENGTH); sub(/^.*chk +/, "", m); found(m)
                                                       if (index(" " chks " ", " " m " ") == 0) chks = chks " " m }
    while (match(line, /\$B\/(cc-[a-z0-9-]+|ccbox|box-status|cc")/)) {
      m = substr(line, RSTART + 3, RLENGTH - 3); rest = substr(line, RSTART + RLENGTH)
      if (m == "cc\"") { m = "cc"; if (match(rest, /^ +[a-z-]+/)) { sub_ = substr(rest, RSTART, RLENGTH); gsub(/ /, "", sub_)
                                                                     if (index(have, " cc-" sub_ " ")) found("cc-" sub_) }
                          if (rest ~ /--go/) found("cc-loop"); if (rest ~ /--say/) found("cc-msg") }   # what `cc … --go` and `--say` start
      found(m); line = rest } }
  END { if (title != "") emit() }' "$SELF")
# ── from selftest.sh's preamble: the machinery this stanza tests
selftest_reach(){   # $1 = this file, $2 = the base → the tools the edited stanzas drive, or rc 1 = everything
  local f=$1 d spans title tools="" t
  [ -n "${2:-}" ] || return 1
  d=$(git -C "$(dirname "$f")" diff -U0 "$2" -- "$f" 2>/dev/null) || return 1
  # "@@ -a,b +s,c @@" → the new side's lines s..s+c-1; a pure deletion (c=0) sits between s and s+1, so both count
  spans=$(awk '/^@@/ { split($3, n, ","); s = substr(n[1], 2) + 0; c = (n[2] == "" ? 1 : n[2] + 0)
                       print s, (c ? s + c - 1 : s + 1) }' <<<"$d")
  [ -n "$spans" ] || return 1
  while IFS= read -r title; do
    [ -n "$title" ] && [ -n "${STANZA_TOOLS[$title]:-}" ] || return 1
    tools="$tools ${STANZA_TOOLS[$title]}"
  done < <(awk -v spans="$spans" '
    BEGIN { n = split(spans, a, "\n"); for (i = 1; i <= n; i++) { split(a[i], r, " "); lo[i] = r[1]; hi[i] = r[2] } }
    /^if stanza "/ { title = $0; sub(/^if stanza "/, "", title); sub(/".*$/, "", title); alw = ($0 ~ /^if stanza "[^"]*" always/); open = 1 }
    { for (i = 1; i <= n; i++) if (NR >= lo[i] && NR <= hi[i]) { seen[i] = 1; print (open && !alw) ? title : "" } }
    /^fi$/ { open = 0 }
    END { for (i = 1; i <= n; i++) if (!seen[i]) print "" }' "$f" | sort -u)   # a span no line reached: everything
  printf '%s' "$tools"; }
# ── from selftest.sh's preamble: the machinery this stanza tests
stanza(){   # `stanza "<title>" [always]`: the header, and whether this change reaches anything the stanza drives.
            # WHICH HALF runs it is not a word here — it is read off the stanza's own body (STANZA_HALF, above),
            # so there is nothing to keep in step. A body of its own = this box; nothing but `chk` = anywhere.
  echo "== $1 =="
  local t hit=""
  # REACH FIRST, then the half. A stanza this change does not reach is not the other half's either: it runs
  # nowhere, on purpose, and part_out is what says so to the audit at the end.
  if [ -n "$REACH" ] && [ "${2:-}" != always ]; then
    for t in ${STANZA_TOOLS[$1]:-}; do want "$t" && { hit=1; break; }; done
    [ -n "$hit" ] || { echo "  · not in this change's reach (${STANZA_TOOLS[$1]:-nothing it drives}): not run"
                       part_out "$1"; return 1; }
  fi
  part_here "$1" "${STANZA_HALF[$1]:-box}" || { echo "  · $PART_WHY"; return 1; }
  return 0; }
# ── from selftest.sh's preamble: the machinery this stanza tests
chk(){   # `chk cc-foo`: that tool's own selfcheck as one case here, or a · line when the change does not reach it. The
         # tally is the tool's own line, found by name, never whatever printed last — no tally = it died = red.
  local t=$1 o r rc keep q
  want_selfcheck "$t" || { echo "  · $t selfcheck: not in this change's reach, not run"; return 0; }
  if [ -n "${PFPID[$t]:-}" ]; then   # `prefetch` started this one earlier; it is READ here, where it always printed
    wait "${PFPID[$t]}" 2>/dev/null || true
    # AND IT LEAVES $KIDS THE MOMENT IT IS REAPED, the way the holder fixtures below do. The trap kills each pid
    # in that list by looking its process group up in ps, so a pid left there after the process is gone is a pid
    # the kernel may have handed to somebody else by then — and the trap would take that stranger's whole group.
    # Dropping it here also means a second `chk` of this tool runs the tool again, inline, exactly as it used to.
    unclaim "${PFPID[$t]}"; unset "PFPID[$t]"
    # Started and empty is red, never a quiet pass — the same rule check.sh's loop uses. A job that was killed
    # before it could write its rc has proved nothing, and silence is exactly what this suite exists to catch.
    if [ -f "$PFD/$t.rc" ]; then rc=$(cat "$PFD/$t.rc"); o=$(cat "$PFD/$t.out")
    else bad "$t selfcheck: started early and left no result — killed, or it died before it could report"; return 0; fi
  else o=$("$B/$t" selfcheck 2>&1); rc=$?; fi
  r=$(grep -o "$t selfcheck: .*" <<<"$o" | tail -1)
  # ANCHORED: "10 failed" ends in "0 failed", so a bare substring test reads any tally ending in a zero as green —
  # 10, 20, 100 failed cases all landed. The two shapes the tools write are "…: 0 failed" and "…, 0 failed".
  grep -qE '(: |, )0 failed' <<<"$r" && { ok "$r"; return 0; }
  # RED ONCE IS NOT RED FOR THE DIFF. This suite runs beside other workers' suites and three landings' gate dirs,
  # and a case that asserts on timing against live shared state — cc-sandbox's swap during the launch, a delivery
  # wait — flips under that load and is green alone on the same tree (451/1 twice on one tree, a different case
  # each time, 2026-09-09; each 183/0 or 192/0 alone). Each red was a ~22 min rerun and no record. So a tool that
  # came back red is run ONCE more, inline and after its prefetched siblings, and judged again by the same rules:
  # green now is reported as LOAD-BOUND with the cases that flipped named, so it is never mistaken for a pass that
  # was clean; red twice is red. A case that is wrong is wrong both times, and a rerun buys it nothing.
  if [ -n "$r" ] && [ "${CC_SELFTEST_RERUN:-1}" != 0 ]; then
    local o2 r2 flipped
    o2=$("$B/$t" selfcheck 2>&1); r2=$(grep -o "$t selfcheck: .*" <<<"$o2" | tail -1)
    if grep -qE '(: |, )0 failed' <<<"$r2"; then
      # …AND THE PASS LINE MUST NOT READ AS RED. A landing does not judge a gate by its exit code alone: cc-land
      # searches the whole output for `(\d+) failed` and calls the gate red on any non-zero count "whatever it
      # exited with" (FAILED_RE). Quoting the load run's tally and its ✗ lines verbatim put "1 failed" in this PASS
      # line, and that is what failed PR #527's landing off a check.sh that exited 0 (2026-09-19) — this rule
      # breaking the very landing it was written to save. So the flip is told with no red shape in it.
      flipped=$(grep -E '✗|✘|FAIL' <<<"$o" | head -n "$RED_CASES" | sed 's/^ *//' | tr '\n' ';')
      ok "$r2 — LOAD-BOUND: $(unred <<<"$r") beside the suite, green alone; the cases that flipped: $(unred <<<"${flipped%;}")"; return 0
    fi
    # RED TWICE ON ONLY QUARANTINED CASES is reported, not red — green.sh's QUARANTINE says when it may be.
    [ -n "$r2" ] && { q=$(quarantined "$t" "$o2") && { ok "$q"; return 0; }
                      red "$t selfcheck: $r2 (and $r the first time — red alone as well, not load)" "$o2"; return 0; }
    # …and a rerun that died (no tally) proves nothing either way: the first red stands, judged on its own output.
  fi
  # …and the first red too (no rerun, or a death with no tally — cc-native's deadline dies that way).
  q=$(quarantined "$t" "$o") && { ok "$q"; return 0; }
  [ -n "$r" ] && { red "$t selfcheck: $r" "$o"; return 0; }
  # NO TALLY is not a failed case — the selfcheck never reached its last line: killed, or never started. PR #235's
  # gate said "it printed no tally line" and not one thing more, and the same suite was green in ten re-runs after
  # it, so there was nothing left to read. Say the exit status (128+n is a signal) and keep every byte it did say.
  keep=/tmp/$t-selfcheck-$RUN.log; printf '%s\n' "$o" > "$keep" 2>/dev/null || keep=nowhere
  bad "$t selfcheck: no tally line — exit $rc, $(printf %s "$o" | wc -c) bytes, kept in $keep"
  [ -n "$o" ] && tail -3 <<<"$o" | sed 's/^/      /'
  return 0; }
# ── from selftest.sh's preamble: the machinery this stanza tests
declare -A PFPID; PFD=""
unclaim(){ local k n=""; for k in $KIDS; do [ "$k" = "$1" ] || n="$n $k"; done; KIDS=$n; }   # exact pid, never a substring
# ── fixture: cc main + track creation
if stanza "cc main + track creation" always; then
cd ~ && "$B/cc" $REPO >/dev/null 2>&1; sleep 1; tmux list-windows -t main -F '#W' | grep -qx "$REPO" && ok "main window created" || bad "main window"
"$B/cc" $REPO w1 >/dev/null 2>&1; sleep 1
[ -d ~/.cc/worktrees/$REPO/w1/.cc ] && [ "$(git -C ~/.cc/worktrees/$REPO/w1 symbolic-ref --short HEAD)" = track/w1 ] && ok "worktree on track/w1 with marker" || bad "worktree/branch"
grep -qxF '.cc/' "$(git -C ~/dev/$REPO rev-parse --path-format=absolute --git-common-dir)/info/exclude" && ok ".cc/ git-excluded" || bad ".cc/ exclusion"
[ "$("$B/cc-board" get $REPO w1 status)" = running ] && ok "board tracks status" || bad "board status"
# A TRACK IS CUT FROM THE PROJECT'S BASE, NOT FROM WHATEVER THE REMOTE CALLS ITS DEFAULT. GitHub makes the first branch
# pushed into a new repository its default, so a workspace's origin/HEAD came to name another project's TRACK, and the
# next track was cut from that — carrying a whole other project's tree into a fresh repository (2026-09-04). The board
# records the base and cc-land already lands against it; creation asks the same place.
( cd ~/dev/$REPO && git checkout -q -b other && echo carpet > carpet.txt && git add -A && git commit -qm "another project's tree" \
  && git push -q origin other:track/other && git checkout -q main && git branch -q -D other ) >/dev/null 2>&1
git -C ~/dev/$REPO fetch -q origin; git -C ~/dev/$REPO symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/track/other
"$B/cc" $REPO w9 >/dev/null 2>&1; sleep 1
{ [ ! -e ~/.cc/worktrees/$REPO/w9/carpet.txt ] && git -C ~/.cc/worktrees/$REPO/w9 merge-base --is-ancestor origin/main HEAD; } \
  && ok "a new track is cut from the board's base even when origin/HEAD names a track branch" \
  || bad "track w9 was cut from origin/HEAD: another project's tree came with it"
git -C ~/dev/$REPO symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main
fi
# ── fixture: checkpoint hook
if stanza "checkpoint hook" always; then
echo hi > ~/.cc/worktrees/$REPO/w1/a.txt; ( cd ~/.cc/worktrees/$REPO/w1 && "$B/cc-checkpoint" )
git -C "$T/remote.git" branch | grep -q track/w1 && ok "checkpoint committed + pushed track branch" || bad "checkpoint push"
echo junk > ~/dev/$REPO/junk.txt; ( cd ~/dev/$REPO && "$B/cc-checkpoint" ); git -C ~/dev/$REPO status --short | grep -q junk && ok "checkpoint no-op on primary worktree" || bad "primary worktree touched!"
# H1: a session that repoints HEAD at the default branch must not get its work committed+pushed there
wt=~/.cc/worktrees/$REPO/w1; m0=$(git -C "$T/remote.git" rev-parse main)
( cd "$wt" && git symbolic-ref HEAD refs/heads/main && echo a > a.txt && "$B/cc-checkpoint" )
[ "$(git -C "$T/remote.git" rev-parse main)" = "$m0" ] && [ -s "$wt/.cc/checkpoint.err" ] && ok "checkpoint refuses a HEAD repointed at main (remote main untouched)" || bad "checkpoint pushed a rewritten HEAD!"
( cd "$wt" && git symbolic-ref HEAD refs/heads/track/w1; rm -f a.txt "$wt/.cc/checkpoint.err" )
printf 'x\n' > "$wt/.env.local"; ( cd "$wt" && "$B/cc-checkpoint" )
[ -s "$wt/.cc/checkpoint.err" ] && ! git -C "$wt" log -1 --name-only 2>/dev/null | grep -q '\.env\.local' && ok "checkpoint refuses secret-looking files (.env.local)" || bad "secret committed"
rm -f "$wt/.env.local" "$wt/.cc/checkpoint.err"
touch "$wt/.cc/push.err"; lsout=$("$B/cc" ls 2>/dev/null)   # capture, don't pipe: grep -q would SIGPIPE cc and pipefail would call that a failure
grep -q 'push!' <<<"$lsout" && ok "cc ls surfaces a failed push" || bad "push.err invisible"; rm -f "$wt/.cc/push.err"
# ── the lease. 2026-08-31: a track rebased its own branch, the plain push was rejected non-fast-forward, and it
# finished green with everything committed and NO PR — only the watchdog saw it. A track branch has exactly one
# writer, so its own rewrite has to land; a write it did NOT make has to stop it dead, and out loud.
echo pre > "$wt/pre.txt"; ( cd "$wt" && "$B/cc-checkpoint" )   # a commit of OUR OWN to rewrite below: later cases still read the branch this suite built above
( cd "$wt" && git commit -q --amend -m "rewritten by a rebase" )   # what a rebase leaves behind: a diverged branch
echo rebased > "$wt/b.txt"; ( cd "$wt" && "$B/cc-checkpoint" )
{ [ "$(git -C "$T/remote.git" rev-parse track/w1)" = "$(git -C "$wt" rev-parse HEAD)" ] && [ ! -f "$wt/.cc/push.err" ]; } \
  && ok "checkpoint pushes a branch this worktree rebased — the lease holds, no non-fast-forward dead end" || bad "a rebased branch never reached the remote"
git clone -q "$T/remote.git" "$T/foreign" 2>/dev/null   # somebody ELSE writes to that branch: the one case the lease exists for
( cd "$T/foreign" && git config user.email o@o && git config user.name o && git checkout -q track/w1 \
  && echo not-ours > f.txt && git add -A && git commit -qm "a write this track did not make" && git push -q origin track/w1 )
fw=$(git -C "$T/remote.git" rev-parse track/w1)
( cd "$wt" && git commit -q --amend -m "and this track rebases again" )   # diverged too, so a plain push could not have landed either
echo more > "$wt/c.txt"; ( cd "$wt" && "$B/cc-checkpoint" )
[ "$(git -C "$T/remote.git" rev-parse track/w1)" = "$fw" ] && ok "a foreign write is NOT overwritten — the lease refuses rather than force" || bad "the lease clobbered somebody else's commit"
{ grep -q 'push refused' "$wt/.cc/push.err" && grep -q '^STATUS: BLOCKED: push refused' ~/.cc/state/$REPO/w1/progress.md \
  && "$B/cc-board" show $REPO 2>/dev/null | grep -q 'push refused'; } \
  && ok "...and says so in all three places at once: push.err (cc ls), the journal (STATUS: BLOCKED stops the loop) and the board" \
  || bad "the refusal was silent somewhere — err=$(grep -c refused "$wt/.cc/push.err" 2>/dev/null) journal=$(grep -c 'STATUS: BLOCKED' ~/.cc/state/$REPO/w1/progress.md 2>/dev/null) board=$("$B/cc-board" show $REPO 2>/dev/null | grep -c 'push refused')"
echo again > "$wt/c2.txt"; ( cd "$wt" && "$B/cc-checkpoint" )   # the hook fires again next turn (with work, or it never reaches the push) and the branch is still blocked
[ "$(grep -c '^STATUS: BLOCKED: push refused' ~/.cc/state/$REPO/w1/progress.md)" = 1 ] && ok "a hook firing every turn does not spam the journal with the same refusal" || bad "duplicate STATUS lines: $(grep -c '^STATUS: BLOCKED' ~/.cc/state/$REPO/w1/progress.md)"
( cd "$wt" && git fetch -q origin && git rebase -q origin/track/w1 >/dev/null 2>&1 )   # the human answer: take the foreign commit in, then carry on
echo after > "$wt/d.txt"; ( cd "$wt" && "$B/cc-checkpoint" )
{ [ "$(git -C "$T/remote.git" rev-parse track/w1)" = "$(git -C "$wt" rev-parse HEAD)" ] && [ ! -f "$wt/.cc/push.err" ]; } \
  && ok "once the foreign commit is rebased in, the very next checkpoint pushes again (the block is not sticky)" || bad "still blocked after the branch was reconciled"
rm -rf "$T/foreign"
# H2: a hand-deleted worktree dir stays registered in git; cc must prune + rebuild it, never stamp a plain dir
# THE RELAUNCH MUST FIND W1'S TRANSCRIPT. `cc __run` on a started session with no transcript mints a NEW session_id,
# a second or more later in its own window. The cc-context fixture below reads the id after this, so under load it
# read the old one and every cc-context case said 'no transcript' (the #463 and #465 landings, 2026-09-12). With a
# transcript there, the relaunch resumes the id it has; the fixture fills the file in.
PD=~/.claude/projects/$REPO-ctx; mkdir -p "$PD"; : > "$PD/$("$B/cc-board" get $REPO w1 session_id).jsonl"
rm -rf "$wt"; "$B/cc" $REPO w1 >/dev/null 2>&1; sleep 1
[ "$(git -C "$wt" rev-parse --show-toplevel 2>/dev/null)" = "$(readlink -f "$wt")" ] && [ -f "$wt/.cc/track" ] && ok "hand-deleted worktree is rebuilt as a real worktree" || bad "worktree rebuilt as a plain dir"
# H3: repo/track names are validated — no path traversal, no options as track names
mkdir -p ~/.cc/state/${REPO}_canary; "$B/cc" rm $REPO ../${REPO}_canary >/dev/null 2>&1
[ $? != 0 ] && [ -d ~/.cc/state/${REPO}_canary ] && ok "cc rm refuses a traversing track name" || bad "cc rm traversal!"
rmdir ~/.cc/state/${REPO}_canary 2>/dev/null
# …but a row name over 64 characters, on the board before its add refused one, is still removable: the janitor's
# `cc rm` failed 77 times on 8 such worktrees (2026-09-14..27). Its own fixture; a 256-character name stays refused.
LONG=r-$(printf 'x%.0s' $(seq 1 70)); mkdir -p ~/.cc/worktrees/$REPO/$LONG ~/.cc/state/$REPO/$LONG
"$B/cc" rm $REPO $LONG >/dev/null 2>&1; lrc=$?
[ $lrc = 0 ] && [ ! -d ~/.cc/worktrees/$REPO/$LONG ] && [ ! -d ~/.cc/state/$REPO/$LONG ] && ok "cc rm removes a worktree whose row name is over 64 characters" || bad "cc rm refused a long row name (rc=$lrc)"
TOOLONG=r-$(printf 'x%.0s' $(seq 1 254)); "$B/cc" rm $REPO $TOOLONG >/dev/null 2>&1
[ $? != 0 ] && ok "…while a 256-character track name is still refused" || bad "cc rm took a 256-character name"
"$B/cc" $REPO --go "x" >/dev/null 2>&1; [ $? != 0 ] && [ ! -d ~/.cc/worktrees/$REPO/--go ] && ok "cc refuses a track named --go" || bad "track '--go' created"
fi
# ── top level, between stanzas
export CC_STATUSLINE_DIR="$T/statusline" CC_CONTEXT_HANDOFF_TOKENS=150000 CC_CTX_BOX_MODEL=   # status-line files under $T, and this box's own model never sizes a fixture
mkdir -p "$CC_STATUSLINE_DIR"
PD=~/.claude/projects/$REPO-ctx; mkdir -p "$PD"    # a transcript for the session the board names for w1 (and see H2: it must exist before a relaunch)
sid=$("$B/cc-board" get $REPO w1 session_id)
printf '{"type":"assistant","message":{"model":"claude-opus-5","usage":{"input_tokens":10,"cache_creation_input_tokens":1000,"cache_read_input_tokens":19000,"output_tokens":5}}}\n' > "$PD/$sid.jsonl"
# ── top level, between stanzas
export CC_HANDOFF_DIR="$T/handoff" CC_CTX_RECORDS="$T/ctx" CC_HANDOFF_RETIRE_GRACE=1 CC_HANDOFF_DRAIN=1   # never the box's own records — CC_CTX_RECORDS is
# ── the stanza
if stanza "the suite's own reporting, and what a green run leaves behind" always; then
# A red stanza names its cases. The tally alone was the whole record of the gate that stopped PR #211 on 09-04.
r=$(red "cc-fake selfcheck: 8 passed, 2 failed" "$(printf 'ok   the one that passed\nFAIL the row it wrote was the wrong row\n  ✗ and the other shape\n')")
{ grep -q '8 passed, 2 failed' <<<"$r" && grep -q 'the row it wrote was the wrong row' <<<"$r" \
  && grep -q 'and the other shape' <<<"$r" && ! grep -q 'the one that passed' <<<"$r"; } \
  && ok "a red stanza prints the tally AND the cases that failed, in both shapes the tools write them" \
  || bad "a red stanza named no case: $(tr '\n' ' ' <<<"$r")"
r=$(red "cc-fake selfcheck: 0 passed, 40 failed" "$(seq 1 40 | sed 's/^/FAIL case /')")
[ "$(wc -l <<<"$r")" = $((RED_CASES + 1)) ] \
  && ok "...capped at $RED_CASES cases, so one broken selfcheck cannot bury the rest of the run" \
  || bad "the cap let $(wc -l <<<"$r") lines through"
# The green record: the CONTENT this passed on, which is what a landing spends instead of running it again. Keyed
# by the tree the working copy WOULD COMMIT, because the worker runs the suite and the hook commits after it.
# EVERY green_record BELOW SAYS `SUITE_PART=all`, and does not inherit this run's half. These cases are about
# the content and the scope a record carries, which is the same question in either half — and a record's
# name now carries the half, so inheriting one would have them looking for files under another name. The
# half's own rule is a case of its own, at the end of these.
GR="$T/green"; GD="$T/greenrepo"; mkdir -p "$GD/tests"
( cd "$GD" && git init -q && git config user.email t@t && git config user.name t && echo one > a.txt && git add -A && git commit -qm init ) >/dev/null 2>&1
echo two > "$GD/a.txt"; echo new > "$GD/b.txt"; : > "$GD/tests/check.sh"   # edited, plus a file not yet added
( cd / && SUITE_PART=all CC_GREEN_DIR="$GR" green_record "$GD/tests/check.sh" )   # …and from anywhere: cwd is not the key
rec=$(cat "$GR"/check.sh-*.json 2>/dev/null)
want=$( cd "$GD" && git add -A && git commit -qm work >/dev/null 2>&1 && git rev-parse "HEAD^{tree}" )
{ grep -q "\"tree\": \"$want\"" <<<"$rec" && grep -q '"suite": "tests/check.sh"' <<<"$rec"; } \
  && ok "a green run records the content it ran on — the tree the commit after it carries — and names the suite as the landing names it" \
  || bad "the green record does not name that content: [$rec] wanted tree $want"
echo three > "$GD/a.txt"; ( cd / && SUITE_PART=all CC_GREEN_DIR="$GR" green_record "$GD/tests/check.sh" )
[ "$(grep -ho '"tree": "[0-9a-f]*"' "$GR"/check.sh-*.json | sort -u | wc -l)" = 2 ] \
  && ok "...and an edit after the run is a different tree: that record cannot answer for it, so the suite runs again" \
  || bad "an edited tree recorded the same content: $(ls "$GR")"
( cd / && SUITE_PART=all CC_GREEN_DIR="$GR" green_record "$GD/tests/check.sh" "core/bin/x core/bin/y" )
grep -q '"scope": "core/bin/x core/bin/y"' "$GR"/check.sh-*.json && grep -q '"scope": ""' <<<"$rec" \
  && ok "...and a record says the SCOPE it ran at — the paths it was narrowed to, or nothing when everything ran — so a narrowed run can never answer for a full one" \
  || bad "the scope is not on the record: $(cat "$GR"/check.sh-*.json | tr '\n' ' ')"
# …and in a LINKED WORKTREE, which is where a worker actually runs it (and where the landing runs it too): its own
# HEAD and its own index, neither of which this may disturb.
( cd "$GD" && git worktree add -q "$GD/wt" -b track/w1 ) >/dev/null 2>&1
mkdir -p "$GD/wt/tests"; : > "$GD/wt/tests/check.sh"; echo four > "$GD/wt/a.txt"
dirt=$(git -C "$GD/wt" status --porcelain)
( cd / && SUITE_PART=all CC_GREEN_DIR="$GR" green_record "$GD/wt/tests/check.sh" )
still=$(git -C "$GD/wt" status --porcelain)
wt=$( cd "$GD/wt" && git add -A && git commit -qm w >/dev/null 2>&1 && git rev-parse "HEAD^{tree}" )
{ grep -q "\"tree\": \"$wt\"" "$GR/check.sh-${wt:0:12}.json" 2>/dev/null && [ "$still" = "$dirt" ]; } \
  && ok "...in a track's own worktree too — where the worker runs it — and nothing of that worktree's own index moved" \
  || bad "no record for the worktree's content ($wt), or its index moved: [$dirt] -> [$still]"
# …AND WHICH HALF LEFT IT, which is the whole safety of running one half off the box: a record of half a run must
# never answer an ask about the whole gate. So the half is in the file AND in its name, and a half's record sits
# BESIDE the whole run's rather than on top of it. What is done with the two — which ask each one answers — is
# cc-land's own selfcheck (green_run); this is only that they are two files and say which is which.
echo five > "$GD/a.txt"
( cd / && SUITE_PART=portable CC_GREEN_DIR="$GR" green_record "$GD/tests/check.sh" )
( cd / && SUITE_PART=all      CC_GREEN_DIR="$GR" green_record "$GD/tests/check.sh" )
h5=$( cd "$GD" && git add -A && git commit -qm five >/dev/null 2>&1 && git rev-parse "HEAD^{tree}" )
{ grep -q '"part": "portable"' "$GR/check.sh-portable-${h5:0:12}.json" 2>/dev/null \
  && grep -q '"part": ""' "$GR/check.sh-${h5:0:12}.json" 2>/dev/null; } \
  && ok "a run of ONE half records under its own name, beside the whole run's and never over it, and each says which half it was" \
  || bad "the half is not in the record's name: $(ls "$GR" | tr '\n' ' ')"

# …AND ONLY A TREE THE RUN ACTUALLY TESTED. green.sh takes the tree as it is SOURCED — a suite's first act — and
# green_record files nothing when the tree at the end is a different one. On 2026-09-15 a self-review edit moved
# core/bin/cc-wakes seven minutes before a detached selftest.sh ended: the record was filed under the post-edit
# tree nothing had run, cc-green read it back as green, and the next iteration re-ran the ~22-minute suite by hand.
# The cases above call green_record in THIS process, where the start tree is this checkout's and the record's is a
# fixture's, so they never meet the guard. This one is a stub suite in a repo of its own, sourcing green.sh at its
# start and recording at its end exactly as check.sh does, run twice off ONE fixture: once with a file moving under
# it, once still. Both, because a guard that never fires and a guard that always does look alike from the green side.
GM="$T/greenmoved"; mkdir -p "$GM/repo/tests" "$GM/rec"
( cd "$GM/repo" && git init -q && git config user.email t@t && git config user.name t \
  && echo one > a.txt && git add -A && git commit -qm init ) >/dev/null 2>&1
{ echo '#!/usr/bin/env bash'
  echo 'set -e; SELF=$(readlink -f "$0"); cd "$(dirname "$SELF")/.."'     # what check.sh and check-extra.sh do…
  echo ". \"$(dirname "$SELF")/green.sh\""                                # …and they source it before a single case
  echo '[ -z "${MOVE:-}" ] || echo moved > a.txt'                         # the edit that lands while the suite runs
  echo 'green_record "$SELF" ""'                                          # CC_SUITE_PART is unset by green.sh, so
  echo 'echo STUB-OK'                                                     # this child records under the plain name
} > "$GM/repo/tests/check.sh"; chmod +x "$GM/repo/tests/check.sh"
gmov=$( cd "$GM/repo" && MOVE=1 CC_GREEN_DIR="$GM/rec" ./tests/check.sh 2>&1 ); gmrc=$?
{ [ "$gmrc" != 0 ] && [ -z "$(ls -A "$GM/rec")" ] && grep -q 'a\.txt' <<<"$gmov" && ! grep -q STUB-OK <<<"$gmov"; } \
  && ok "a tree that moved while the suite ran gets NO record: the suite names the file that moved and exits non-zero" \
  || bad "a moved tree was recorded, or passed quietly: rc=$gmrc records=[$(ls -A "$GM/rec" | tr '\n' ' ')] out=[$(tr '\n' ' ' <<<"$gmov")]"
( cd "$GM/repo" && git checkout -q -- a.txt )        # the same stub on the same fixture, with nothing moving
gsti=$( cd "$GM/repo" && CC_GREEN_DIR="$GM/rec" ./tests/check.sh 2>&1 ); gsrc=$?
gmt=$( cd "$GM/repo" && git add -A && git commit -qm still >/dev/null 2>&1 && git rev-parse "HEAD^{tree}" )
{ [ "$gsrc" = 0 ] && grep -q "\"tree\": \"$gmt\"" "$GM/rec/check.sh-${gmt:0:12}.json" 2>/dev/null; } \
  && ok "...and a still tree records what it always did, so what the guard refuses is the move and not the run" \
  || bad "a still tree filed no record: rc=$gsrc out=[$(tr '\n' ' ' <<<"$gsti")] records=[$(ls -A "$GM/rec" | tr '\n' ' ')]"

# THE REACH OF A CHANGE (tests/green.sh, land_scope): what the landing's CC_LAND_CHANGED turns into here. Its own
# bin/ of four stubs: a leaf, a caller that runs it, a talker that only names it in a comment, and cc, which runs both.
SB="$T/scopebin"; mkdir -p "$SB"
printf '#!/bin/sh\n"$BIN/cc-leaf" x\n' > "$SB/cc-caller"; printf '#!/bin/sh\n' > "$SB/cc-leaf"
printf '#!/bin/sh\n# cc-leaf is mentioned here and never run\n' > "$SB/cc-talker"; printf '#!/bin/sh\n"$BIN/cc-leaf"; "$BIN/cc-caller"\n' > "$SB/cc"
reach(){ ( CC_LAND_CHANGED="$1" land_scope "$SB"; printf '%s|%s' "$REACH" "$SCOPE" ); }
[ "$(reach core/bin/cc-leaf)" = " cc-caller cc-leaf |core/bin/cc-leaf" ] \
  && ok "a changed tool reaches itself and the tools that INVOKE it — not one that only mentions it, and never cc, the door to everything" \
  || bad "reach of cc-leaf: [$(reach core/bin/cc-leaf)]"
[ "$(reach 'core/bin/cc-caller core/tests/x.sh')" = "|" ] && [ "$(reach core/bin/cc)" = "|" ] && [ "$(reach core/bin/cc-gone)" = "|" ] \
  && ok "a path that is not a tool, a tool too short to grep for, and a tool that is gone each reach everything" \
  || bad "widening: [$(reach 'core/bin/cc-caller core/tests/x.sh')] [$(reach core/bin/cc)] [$(reach core/bin/cc-gone)]"
# …and the reach is TRANSITIVE, and it reads python's own two ways of naming a sibling. cc-context, cc-handoff and
# cc-graphs run every tool they drive through os.path.join(BIN, "cc-foo"), which no $BIN/ pattern matches, and one
# hop stopped at the direct caller: a PR to cc-msg alone skipped every stanza that drives it through cc-handoff.
# cc-native, cc-task and the member tools spell it `BIN / "cc-foo"` instead, which matched nothing either.
SB2="$T/scopebin2"; mkdir -p "$SB2"
printf '#!/bin/sh\n' > "$SB2/cc-deep"
printf '#!/usr/bin/env python3\nsubprocess.run([os.path.join(BIN, "cc-deep"), "x"])\n' > "$SB2/cc-mid"
printf '#!/bin/sh\n"$BIN/cc-mid"\n' > "$SB2/cc-far"
printf '#!/usr/bin/env python3\npolicy = (BIN / "cc-deep").read_text()\n' > "$SB2/cc-pathlib"
printf '#!/bin/sh\n# cc-deep is only named here\n' > "$SB2/cc-idle"
r2(){ ( CC_LAND_CHANGED="$1" land_scope "$SB2"; printf '%s' "$REACH" ); }
[ "$(r2 core/bin/cc-deep)" = " cc-deep cc-far cc-mid cc-pathlib " ] \
  && ok "the reach is transitive and reads both python spellings — os.path.join(BIN, \"cc-foo\") and BIN / \"cc-foo\" — the caller and the caller's caller, never a file that only names it" \
  || bad "transitive reach: [$(r2 core/bin/cc-deep)]"
# …and that second spelling is how a tool READS a sibling's source, which is a harder dependency than a call and
# was invisible: cc-member-import takes the host staged-name policy out of cc-checkpoint, so a rename of SECRETS
# there makes every member import refuse — and no landing of cc-checkpoint alone ran the case that catches it.
edge=$( CC_LAND_CHANGED="core/bin/cc-checkpoint" land_scope "$B"; printf '%s' "$REACH" )
case "$edge" in *" cc-member-import "*) ok "a change to cc-checkpoint alone reaches cc-member-import, which reads its staged-name policy";;
  *) bad "cc-checkpoint does not reach cc-member-import: [$edge]";; esac
# …and a CASE FILE reaches what it tests, not everything: a tool's own selfcheck file stands for the tool, and an
# edit to selftest.sh runs the stanza it sits in (selftest_reach) — outside every stanza, or in an `always` one, it
# still runs them all. Each case builds its own file and repo; STANZA_TOOLS is set in the subshell for that file.
[ "$(reach core/tests/cc-leaf-selfcheck.py)" = " cc-caller cc-leaf |core/tests/cc-leaf-selfcheck.py" ] \
  && [ "$(reach core/tests/leaf_selfcheck.py)" = " cc-caller cc-leaf |core/tests/leaf_selfcheck.py" ] \
  && [ "$(reach core/tests/nobody_selfcheck.py)" = "|" ] && [ "$(reach core/tests/check.sh)" = "|" ] \
  && [ "$(CC_LAND_CHANGED=core/tests/selftest.sh land_scope "$SB"; printf '%s|%s' "$REACH" "$SELFTEST_EDITED")" = " |1" ] \
  && ok "a tool's selfcheck file reaches that tool, selftest.sh is marked for the suite to place, and a selfcheck of no tool or any other test file reaches everything" \
  || bad "case-file reach: [$(reach core/tests/cc-leaf-selfcheck.py)] [$(reach core/tests/leaf_selfcheck.py)] [$(reach core/tests/nobody_selfcheck.py)] [$(reach core/tests/check.sh)]"
SR6="$T/stanzareach"; mkdir -p "$SR6"; git -C "$SR6" init -q
printf '%s\n' '# prelude' 'if stanza "one"; then' '  "$B/cc-leaf" x' 'fi' 'if stanza "base" always; then' '  echo base' 'fi' \
  'if stanza "bare"; then' '  echo nothing' 'fi' > "$SR6/st.sh"
git -C "$SR6" add st.sh && git -C "$SR6" -c user.email=t@t -c user.name=t commit -qm base
sr6=$(git -C "$SR6" rev-parse HEAD)
r6(){ ( declare -A STANZA_TOOLS=([one]="cc-leaf" [base]="cc-other" [bare]="")
        cp "$SR6/st.sh" "$SR6/st.orig"; sed -i "$1" "$SR6/st.sh"; o=$(selftest_reach "$SR6/st.sh" "$2") && printf '%s' "$o" || printf 'ALL'
        mv "$SR6/st.orig" "$SR6/st.sh" ); }
[ "$(r6 '3s/x/y/' "$sr6")" = " cc-leaf" ] && [ "$(r6 '1s/prelude/p/' "$sr6")" = ALL ] && [ "$(r6 '6s/base/b/' "$sr6")" = ALL ] \
  && [ "$(r6 '9s/nothing/n/' "$sr6")" = ALL ] && [ "$(r6 '3s/x/y/' "")" = ALL ] && [ "$(r6 '3d' "$sr6")" = " cc-leaf" ] \
  && ok "an edit inside a stanza runs that stanza's tools, and one in the prelude, an always stanza, a stanza that drives nothing, or with no base runs everything" \
  || bad "selftest_reach: in=[$(r6 '3s/x/y/' "$sr6")] prelude=[$(r6 '1s/prelude/p/' "$sr6")] always=[$(r6 '6s/base/b/' "$sr6")] bare=[$(r6 '9s/nothing/n/' "$sr6")] nobase=[$(r6 '3s/x/y/' "")] del=[$(r6 '3d' "$sr6")]"
# …and the ONE EDGE THE GREP CANNOT SEE: the member launcher runs cc-fence at its path INSIDE bwrap
# ("$HOME/bin/cc-fence"), which no `$BIN/`-shaped pattern matches, and its cases live under cc-sandbox's
# selfcheck rather than its own. green.sh names the five tools outright; without it a change to cc-member-v2
# alone left the fence's gate and the canary out of the landing's reach.
SB4="$T/scopebin4"; mkdir -p "$SB4"
for f in cc-member-v2 cc-member-broker cc-member-import cc-fence cc-sandbox cc-leaf; do printf '#!/bin/sh\n' > "$SB4/$f"; done
r4(){ ( CC_LAND_CHANGED="$1" land_scope "$SB4"; printf '%s' "$REACH" ); }
{ [ "$(r4 core/bin/cc-member-v2)" = " cc-fence cc-member-broker cc-member-import cc-member-v2 cc-sandbox " ] \
  && [ "$(r4 core/bin/cc-fence)" = " cc-fence cc-member-broker cc-member-import cc-member-v2 cc-sandbox " ] \
  && [ "$(r4 core/bin/cc-member-broker)" = " cc-fence cc-member-broker cc-member-import cc-member-v2 cc-sandbox " ] \
  && [ "$(r4 core/bin/cc-member-import)" = " cc-fence cc-member-broker cc-member-import cc-member-v2 cc-sandbox " ] \
  && [ "$(r4 core/bin/cc-sandbox)" = " cc-fence cc-member-broker cc-member-import cc-member-v2 cc-sandbox " ] \
  && [ "$(r4 core/bin/cc-leaf)" = " cc-leaf " ]; } \
  && ok "each of the five member tools reaches all five; the independent leaf reaches only itself" \
  || bad "member-launcher reach: [$(r4 core/bin/cc-member-v2)] [$(r4 core/bin/cc-fence)] [$(r4 core/bin/cc-leaf)]"
# …and a path OUTSIDE the tree bin/ sits in reaches nothing, because that tree ships and is tested alone: an
# overlay's own tool or lesson beside core/ ran every case in the suite (#616, #584). Inside the tree
# the old rules hold, and a bin/ at the top of its checkout has no outside, so there every path counts as before.
SR="$T/scoperepo"; mkdir -p "$SR/core/bin" "$SR/flat/bin"; git -C "$SR" init -q; git -C "$SR/flat" init -q
printf '#!/bin/sh\n' > "$SR/core/bin/cc-leaf"; printf '#!/bin/sh\n"$BIN/cc-leaf" x\n' > "$SR/core/bin/cc-caller"
printf '#!/bin/sh\n' > "$SR/flat/bin/cc-leaf"
r5(){ ( CC_LAND_CHANGED="$1" land_scope "$SR/$2/bin"; want cc-leaf cc-caller && w=runs || w=skips
        printf '%s|%s|%s' "$REACH" "$SCOPE" "$w" ); }
{ [ "$(r5 'bin-private/x lessons/a.py' core)" = " |bin-private/x lessons/a.py|skips" ] \
  && [ "$(r5 'core/bin/cc-leaf lessons/a.py' core)" = " cc-caller cc-leaf |core/bin/cc-leaf lessons/a.py|runs" ] \
  && [ "$(r5 'core/templates/x lessons/a.py' core)" = "||runs" ] \
  && [ "$(r5 'lessons/a.py' flat)" = "||runs" ]; } \
  && ok "a diff only outside core/ reaches no tool and keeps its scope for the record; beside a core tool it adds nothing; a non-tool inside core/, or any path where bin/ is at the top, still runs everything" \
  || bad "outside-the-tree reach: [$(r5 'bin-private/x lessons/a.py' core)] [$(r5 'core/bin/cc-leaf lessons/a.py' core)] [$(r5 'core/templates/x lessons/a.py' core)] [$(r5 'lessons/a.py' flat)]"
# …and the SCOPE it hands back is the LANDING'S OWN STRING, byte for byte. The landing writes the paths in python's
# byte order; sorting them again here runs in the box's locale, where GNU sort ignores the `-` on its first pass and
# hands `core/bin/cc-graphs core/bin/ccbox` back swapped. (The old lander's green_run, which spent a record only on an
# equal scope, went with #771; the order is still the landing's to set, so the case checks the string alone.)
SB3="$T/scopebin3"; mkdir -p "$SB3"
printf '#!/bin/sh\n' > "$SB3/cc-graphs"; printf '#!/bin/sh\n' > "$SB3/ccbox"
U8=$(locale -a 2>/dev/null | grep -ix 'en_US.utf-\?8' | head -1); U8=${U8:-C.UTF-8}
told="core/bin/cc-graphs core/bin/ccbox"   # exactly as the landing writes it: " ".join(sorted(paths))
got=$( export LC_ALL=$U8 LANG=$U8; CC_LAND_CHANGED="$told" land_scope "$SB3"; printf '%s' "$SCOPE" )
[ "$got" = "$told" ] \
  && ok "the scope is handed back as the landing wrote it, not re-sorted: under $U8, a diff of core/bin/cc-graphs + core/bin/ccbox keeps its order" \
  || bad "scope round-trip under $U8: got [$got] wanted [$told]"
( REACH=" cc-leaf "; want cc-leaf && ! want cc-talker && REACH="" && want cc-talker ) \
  && ok "want: a reached tool, not an unreached one, and everything when nothing was narrowed" || bad "want"
# Every fixture stanza below declares THIS run's half, so these cases are about the reach and nothing else; the
# half is the case after them. Named `fake`/`fake2` in a SUBSHELL, so the audit's inventory never sees them.
( REACH=" cc-other "; STANZA_TOOLS[fake]="cc-leaf"; STANZA_HALF[fake]=$SUITE_PART; r1=$(stanza fake); a=$?; STANZA_TOOLS[fake]="cc-leaf cc-other"; stanza fake >/dev/null; b=$?
  r3=$(stanza fake always); c=$?; [ $a = 1 ] && grep -q 'not in this change' <<<"$r1" && [ $b = 0 ] && [ $c = 0 ] && ! grep -q 'not run' <<<"$r3" ) \
  && ok "a stanza runs when the change reaches something it drives, or when it is marked always; otherwise it says so and is skipped" \
  || bad "stanza gating"
# …and THEN the half, which is the second gate and asked only of a stanza the change reaches. Both answers are
# asserted in every mode: a whole run owns both halves, and each half runs the ones it owns and REFUSES the
# other's by name — never skips it quietly, which is the one thing a split must not be able to do.
( REACH=""; STANZA_TOOLS[fake2]="cc-leaf"
  STANZA_HALF[fake2]=box;      rb=$(stanza fake2); hb=$?
  STANZA_HALF[fake2]=portable; rp=$(stanza fake2); hp=$?
  case "$SUITE_PART" in
    all)      [ $hb = 0 ] && [ $hp = 0 ];;
    box)      [ $hb = 0 ] && [ $hp = 1 ] && grep -q 'off the box' <<<"$rp" && grep -q fake2 <<<"$rp";;
    portable) [ $hp = 0 ] && [ $hb = 1 ] && grep -q 'needs this box' <<<"$rb" && grep -q fake2 <<<"$rb";;
  esac ) \
  && ok "...and then which HALF owns it: a whole run owns both, and one half runs its own and refuses the other's by name (this run: $SUITE_PART)" \
  || bad "stanza half gating under SUITE_PART=$SUITE_PART"
{ [ "${STANZA_TOOLS[usage limits (cc-limit + cc-loop)]#* }" != "${STANZA_TOOLS[usage limits (cc-limit + cc-loop)]}" ] \
  && case " ${STANZA_TOOLS[usage limits (cc-limit + cc-loop)]} " in *" cc-limit "*" cc-loop "*|*" cc-loop "*" cc-limit "*) true;; *) false;; esac \
  && case " ${STANZA_TOOLS[resume/digest/rm]} " in *" cc-reconcile "*) true;; *) false;; esac \
  && case " ${STANZA_TOOLS[cc-reconcile (board vs reality: decision table + one end-to-end apply, no network)]} " in *" cc-reconcile "*) true;; *) false;; esac; } \
  && ok "the scan reads each stanza's tools off its own lines: \$B/cc-foo, chk cc-foo, and \$B/cc <sub> as the cc-<sub> it dispatches to" \
  || bad "the scan: limits=[${STANZA_TOOLS[usage limits (cc-limit + cc-loop)]}] resume=[${STANZA_TOOLS[resume/digest/rm]}]"
( REACH=" cc-other "; o=$(chk cc-leaf); [ $? = 0 ] && grep -q 'not in this' <<<"$o" ) \
  && ok "chk: a selfcheck the change does not reach is a · line, not a run and not a red" || bad "chk gating"
# …and chk reads the TALLY anchored. "10 failed" ends in "0 failed": on a substring test every red run whose
# failure count ends in a zero was reported green, its own tally line printed beside the tick (reviewer, PR #235).
CB="$T/chkbin"; mkdir -p "$CB"
printf '#!/bin/sh\necho "cc-ten selfcheck: 3 passed, 10 failed"; echo "FAIL the tenth"; exit 1\n' > "$CB/cc-ten"
printf '#!/bin/sh\necho "cc-zero selfcheck: 4 passed, 0 failed"\n' > "$CB/cc-zero"
printf '#!/bin/sh\necho "cc-one selfcheck: 0 failed"\n' > "$CB/cc-one"
chmod +x "$CB"/cc-ten "$CB"/cc-zero "$CB"/cc-one
r=$( B=$CB; REACH=""; chk cc-ten; chk cc-zero; chk cc-one )
{ grep -q '✗ .*cc-ten selfcheck: 3 passed, 10 failed' <<<"$r" && grep -q 'FAIL the tenth' <<<"$r" \
  && grep -q '✓ cc-zero selfcheck: 4 passed, 0 failed' <<<"$r" && grep -q '✓ cc-one selfcheck: 0 failed' <<<"$r"; } \
  && ok "chk reads the tally anchored: 10 failed is RED, and both shapes a tool writes a real zero in are green" \
  || bad "chk tally: $(tr '\n' ' ' <<<"$r")"
# …and a selfcheck that never reaches its tally must not be reported as a shrug. PR #235's gate said only "it
# printed no tally line": no exit status, no output, nothing to chase, and the case was green in every re-run.
printf '#!/bin/sh\necho "cc-mute: half a run"; kill -9 $$\n' > "$CB/cc-mute"; chmod +x "$CB/cc-mute"
r=$( B=$CB; REACH=""; chk cc-mute )
{ grep -q '✗ cc-mute selfcheck: no tally line — exit 137' <<<"$r" && grep -q 'half a run' <<<"$r" \
  && grep -q "kept in /tmp/cc-mute-selfcheck-$RUN.log" <<<"$r" && [ -s "/tmp/cc-mute-selfcheck-$RUN.log" ]; } \
  && ok "...and one that dies before its tally says so with the exit status that killed it, its last lines, and the whole output on disk — never a bare 'no tally line' nobody can chase" \
  || bad "chk no-tally: $(tr '\n' ' ' <<<"$r")"
rm -f "/tmp/cc-mute-selfcheck-$RUN.log"
# …and a red that is green on its second run, alone, is LOAD-BOUND and said so, never red for the diff; one that
# is red both times is red. A counter file is the fixture's memory of how many times it has been run.
printf '#!/bin/sh\nn=$(cat "$0.n" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$0.n"\nif [ $n = 1 ]; then echo "FAIL the swap during the launch"; echo "cc-flaky selfcheck: 9 passed, 1 failed"; exit 1; fi\necho "cc-flaky selfcheck: 10 passed, 0 failed"\n' > "$CB/cc-flaky"
printf '#!/bin/sh\necho "FAIL the same case"; echo "cc-broken selfcheck: 9 passed, 1 failed"; exit 1\n' > "$CB/cc-broken"
chmod +x "$CB/cc-flaky" "$CB/cc-broken"; rm -f "$CB/cc-flaky.n"
r=$( B=$CB; REACH=""; chk cc-flaky; chk cc-broken )
{ grep -q '✓ cc-flaky selfcheck: 10 passed, 0 failed — LOAD-BOUND: cc-flaky selfcheck: 9 passed, 1 red beside the suite, green alone; the cases that flipped: red the swap during the launch' <<<"$r" \
  && [ "$(cat "$CB/cc-flaky.n")" = 2 ] \
  && grep -q '✗ cc-broken selfcheck: cc-broken selfcheck: 9 passed, 1 failed (and cc-broken selfcheck: 9 passed, 1 failed the first time — red alone as well, not load)' <<<"$r" \
  && grep -q 'FAIL the same case' <<<"$r"; } \
  && ok "chk: a tool red beside the suite and green on its one rerun is LOAD-BOUND, said so with the cases that flipped, and not red; one red both times is red with its cases" \
  || bad "chk rerun: $(tr '\n' ' ' <<<"$r")"
# …AND THE LOAD-BOUND LINE IS READ BACK THE WAY THE LANDING READS IT (cc-land's FAILED_RE, `(\d+) failed` over the
# whole output, and the ✗/FAIL its card names the case by). A pass that still says "1 failed" anywhere fails the
# gate however this suite exits — that is what happened to PR #527 off a check.sh that exited 0, 2026-09-19.
{ ! grep -qE '[1-9][0-9]* failed|✗|✘|FAIL' <<<"$(grep LOAD-BOUND <<<"$r")" \
  && grep -qE '[1-9][0-9]* failed' <<<"$(grep cc-broken <<<"$r")"; } \
  && ok "…and that LOAD-BOUND line carries no red shape a landing would read as a failed gate, while the one that is red twice still does" \
  || bad "chk rerun shape: $(grep 'LOAD-BOUND' <<<"$r")"
r=$( B=$CB; REACH=""; CC_SELFTEST_RERUN=0; rm -f "$CB/cc-flaky.n"; chk cc-flaky )
{ grep -q '✗ cc-flaky selfcheck: cc-flaky selfcheck: 9 passed, 1 failed' <<<"$r" && [ "$(cat "$CB/cc-flaky.n")" = 1 ]; } \
  && ok "…and CC_SELFTEST_RERUN=0 runs nothing twice: the first red stands" || bad "chk rerun off: $(tr '\n' ' ' <<<"$r")"
# QUARANTINE (green.sh): a tool red twice on ONLY a listed case is reported, not red — and only where the landing
# named a diff that touches neither that tool nor a protected path. Each case below builds its own list and tool.
printf '#!/bin/sh\nn=$(cat "$0.n" 2>/dev/null || echo 0); echo $((n+1)) > "$0.n"\necho "FAIL the listed race"; echo "cc-qrace selfcheck: 9 passed, 1 failed"; exit 1\n' > "$CB/cc-qrace"
printf '#!/bin/sh\necho "FAIL the listed race"; echo "FAIL a real bug"; echo "cc-qmix selfcheck: 8 passed, 2 failed"; exit 1\n' > "$CB/cc-qmix"
chmod +x "$CB/cc-qrace" "$CB/cc-qmix"; qexp=$(date -d '+30 days' +%F); printf 'cc-qrace\tthe listed race\twhy\towner\t%s\ncc-qmix\tthe listed race\twhy\towner\t%s\n' "$qexp" "$qexp" > "$CB/quarantine"
qchk(){ ( B=$CB; REACH=""; QUARANTINE_FILES=$CB/quarantine; CC_LAND_CHANGED=$1; rm -f "$CB/cc-qrace.n"; chk "$2" ); }
r=$(qchk "core/bin/cc-other" cc-qrace)
{ grep -q '✓ cc-qrace: QUARANTINED — red only on known load-sensitive cases .*red the listed race' <<<"$r" \
  && ! grep -qE '[1-9][0-9]* failed|✗|✘|FAIL' <<<"$r" && [ "$(cat "$CB/cc-qrace.n")" = 2 ]; } \
  && ok "quarantine: a tool red twice on only a listed case, for a diff that does not touch it, is reported QUARANTINED — rerun once first, and with no red shape a landing would read" \
  || bad "quarantine kept: $(tr '\n' ' ' <<<"$r")"
r=$(qchk "core/bin/cc-qrace" cc-qrace)
{ grep -q '✗ cc-qrace selfcheck' <<<"$r" && ! grep -q QUARANTINED <<<"$r"; } \
  && ok "quarantine: …but a diff that touches the tool itself keeps its listed case red" || bad "quarantine own tool: $(tr '\n' ' ' <<<"$r")"
r=$(qchk "core/bin/cc-guard" cc-qrace)
{ grep -q '✗ cc-qrace selfcheck' <<<"$r" && ! grep -q QUARANTINED <<<"$r"; } \
  && ok "quarantine: …and so does a diff to a protected path (cc-guard here)" || bad "quarantine protected: $(tr '\n' ' ' <<<"$r")"
r=$(qchk "core/tests/quarantine" cc-qrace)
{ grep -q '✗ cc-qrace selfcheck' <<<"$r" && ! grep -q QUARANTINED <<<"$r"; } \
  && ok "quarantine: …and a diff to the list itself, so no PR quarantines its own red" || bad "quarantine list edit: $(tr '\n' ' ' <<<"$r")"
r=$(qchk "" cc-qrace)
{ grep -q '✗ cc-qrace selfcheck' <<<"$r" && ! grep -q QUARANTINED <<<"$r"; } \
  && ok "quarantine: …and a run that names no diff (a hand run, cc-green's) is strict" || bad "quarantine no diff: $(tr '\n' ' ' <<<"$r")"
r=$(qchk "core/bin/cc-other" cc-qmix)
{ grep -q '✗ cc-qmix selfcheck' <<<"$r" && grep -q 'FAIL a real bug' <<<"$r" && ! grep -q QUARANTINED <<<"$r"; } \
  && ok "quarantine: …and a listed case beside one that is not listed is red, with the unlisted case named" || bad "quarantine mixed: $(tr '\n' ' ' <<<"$r")"
r=$( B=$CB; QUARANTINE_FILES=$CB/quarantine; CC_LAND_CHANGED=docs/x.md; fail=0; qbad cc-qrace "the listed race took +97s"; echo "fail=$fail" )
r2=$( B=$CB; QUARANTINE_FILES=$CB/quarantine; CC_LAND_CHANGED=docs/x.md; fail=0; qbad cc-qrace "an unlisted case"; echo "fail=$fail" )
r3=$( B=$CB; QUARANTINE_FILES=$CB/quarantine; unset CC_LAND_CHANGED; fail=0; qbad cc-qrace "the listed race took +97s"; echo "fail=$fail" )
{ grep -q '✓ cc-qrace: QUARANTINED' <<<"$r" && grep -q '✗ an unlisted case' <<<"$r2" && grep -q 'fail=1' <<<"$r2" \
  && grep -q '✗ the listed race' <<<"$r3" && grep -q 'fail=1' <<<"$r3"; } \
  && ok "quarantine: an inline case (qbad) listed for its tool is reported QUARANTINED; an unlisted one, or one with no diff named, is red" \
  || bad "quarantine inline: $(tr '\n' ' ' <<<"$r $r2 $r3")"
# brief: "each with an owner and an expiry" — a row past its date, or with none, no longer quarantines; one due today still does
printf 'cc-qrace\tthe listed race\twhy\towner\t2000-01-01\n' > "$CB/quarantine.old"
printf 'cc-qrace\tthe listed race\twhy\n' > "$CB/quarantine.bare"; printf 'cc-qrace\tthe listed race\twhy\towner\t%s\n' "$(date +%F)" > "$CB/quarantine.today"
r=$( B=$CB; QUARANTINE_FILES=$CB/quarantine.old; CC_LAND_CHANGED=docs/x.md; fail=0; qbad cc-qrace "the listed race took +97s"; echo "fail=$fail" )
r2=$( B=$CB; QUARANTINE_FILES=$CB/quarantine.bare; CC_LAND_CHANGED=docs/x.md; fail=0; qbad cc-qrace "the listed race took +97s"; echo "fail=$fail" )
r3=$( B=$CB; QUARANTINE_FILES=$CB/quarantine.today; CC_LAND_CHANGED=docs/x.md; fail=0; qbad cc-qrace "the listed race took +97s"; echo "fail=$fail" )
{ grep -q '✗ the listed race' <<<"$r" && grep -q 'fail=1' <<<"$r" && grep -q '✗ the listed race' <<<"$r2" && grep -q 'fail=1' <<<"$r2" \
  && grep -q '✓ cc-qrace: QUARANTINED' <<<"$r3" && grep -q 'fail=0' <<<"$r3"; } \
  && ok "quarantine: a row past its expiry, or with none, is red again; one that expires today still counts" \
  || bad "quarantine expiry: $(tr '\n' ' ' <<<"$r $r2 $r3")"
# review of #692: awk compared the expiry as a string, so "never" or 2999-01-01 sorted after today and quarantined for good
printf 'cc-qrace\tthe listed race\twhy\towner\tnever\n' > "$CB/quarantine.word"; printf 'cc-qrace\tthe listed race\twhy\towner\t2999-01-01\n' > "$CB/quarantine.far"
r=$( B=$CB; QUARANTINE_FILES=$CB/quarantine.word; CC_LAND_CHANGED=docs/x.md; fail=0; qbad cc-qrace "the listed race took +97s"; echo "fail=$fail" )
r2=$( B=$CB; QUARANTINE_FILES=$CB/quarantine.far; CC_LAND_CHANGED=docs/x.md; fail=0; qbad cc-qrace "the listed race took +97s"; echo "fail=$fail" )
{ grep -q '✗ the listed race' <<<"$r" && grep -q 'fail=1' <<<"$r" && grep -q '✗ the listed race' <<<"$r2" && grep -q 'fail=1' <<<"$r2"; } \
  && ok "quarantine: an expiry that is not a date, or one more than 60 days out, does not count" \
  || bad "quarantine expiry shape: $(tr '\n' ' ' <<<"$r $r2")"
fi
e2e_end
# recurring-defect-ok: pause-hold-missing — a test of cc on a fixture repo; the pause check is the tool's, not the stanza's
# recurring-defect-ok: held-files-unchecked — a test of cc on a fixture repo; held_files is checked in the tool it drives
