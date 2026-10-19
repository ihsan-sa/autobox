# shellcheck shell=bash disable=SC2154,SC2034
# cc-green's selfcheck cases, moved out of bin/cc-green. That tool's selfcheck() sources this file, whose
# definition replaces it, and then calls it: the cases run in the tool's own shell, with its functions and
# globals, as they did when the body sat there. SC2154/SC2034 are off because those globals live in bin/cc-green.

selfcheck(){
  local n=0 f=0 D D2 R R2 out rc rc2 p p2 pid gpid log runid np
  k(){ n=$((n+1)); if [ "$1" = 0 ]; then echo "  ok   $2"; else echo "  FAIL $2"; f=$((f+1)); fi; }
  t(){ if "$@" >/dev/null 2>&1; then echo 0; else echo 1; fi; }
  nt(){ if "$@" >/dev/null 2>&1; then echo 1; else echo 0; fi; }   # …and one that must NOT hold: `t !` runs `!` as a command
  # The trap clears itself: a RETURN trap outlives the function that set it, so it would fire again as the stub in
  # bin/cc-green returns, with this local gone and whatever $D means out there (unset, which set -u turns into exit 1).
  D=$(mktemp -d); trap 'rm -rf "$D"; trap - RETURN' RETURN
  unset CC_GREEN_RUNID CC_GREEN_SCOPE   # a selfcheck run under a cc-green run must not pass for that run
  unset CC_GREEN_ASK CC_ROLE CC_MEMBER_SANDBOX   # …nor take a worker's fence from the shell it runs in: a case sets these itself
  export CC_FAILURES="$D/failures"   # every record a case below writes goes to a scratch ledger, never the box's own
  export CC_REVIEWS_DIR="$D/reviews" CC_STATE_BASE="$D/state"   # …and the review record the report reads is a scratch one

  # A fixture repo whose core/lander/cli.py is a FAKE lander: it writes its arguments and pid beside the fixture
  # (under $D, never in the tree), sleeps $2 seconds, runs $D/<name>.py if a case wrote one, appends `check` to
  # $D/<name>.log and exits with the code in $D/<name>.rc (0 when there is none). No real check ever runs.
  newrepo(){   # $1 = a name, $2 = seconds the fake check takes (none = instant) → the repo's path
    local w="$D/$1"
    mkdir -p "$w/core/lander"
    ( cd "$w" && git init -q && git config user.email t@t && git config user.name t )
    echo one > "$w/a.txt"
    cat > "$w/core/lander/cli.py" <<EOS
import os, sys, time
D, NAME, SECS = "$D", "$1", ${2:-0}
open(f"{D}/{NAME}.args", "w").write(" ".join(sys.argv[1:]) + "\n")
with open(f"{D}/{NAME}.pid", "a") as fh: fh.write(f"{os.getpid()}\n")
if SECS:
    open(f"{D}/{NAME}.started", "w").close(); time.sleep(SECS)
if os.path.exists(f"{D}/{NAME}.py"):
    exec(open(f"{D}/{NAME}.py").read())
rc = int(open(f"{D}/{NAME}.rc").read()) if os.path.exists(f"{D}/{NAME}.rc") else 0
print(f"lander check: fake {NAME}, exit {rc}", flush=True)
with open(f"{D}/{NAME}.log", "a") as fh: fh.write("check\n")
sys.exit(rc)
EOS
    ( cd "$w" && git add -A && git commit -qm one )
    echo "$w"
  }

  # 1 THE CASE THIS TOOL EXISTS FOR: a green run, then an edit, and the verdict must no longer answer.
  D2=$(mktemp -d); R=$(newrepo moved)
  ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run >/dev/null 2>&1 ); rc=$?
  k "$rc" "a run whose lander check exits 0 is green, exit 0"
  k "$(t test "$(cat "$D/moved.args")" = "check $(git -C "$R" rev-parse --show-toplevel)")" "…having run the worktree's own core/lander/cli.py as \`check <root>\`"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a -n "$(grep 'green   lander check' <<<"$out")")" "…and a plain call on the same tree says green, exit 0, without running it again"
  k "$(t test "$(grep -cx check "$D/moved.log")" = 1)" "…one check ran"
  echo two > "$R/a.txt"            # ONE tracked file edited after the run — the whole failure this measures
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 1 -a -n "$(grep 'RUN     lander check — its last verdict .* not this tree' <<<"$out")")" "a tree that moved after its green run does NOT match, exit 1"
  k "$(t grep -q 'NOT green' <<<"$out")" "…and says NOT green"
  git -C "$R" checkout -q -- a.txt
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" 2>&1 ); rc=$?
  k "$rc" "…and putting the file back makes the same verdict answer again"
  echo scratch > "$R/note.md"      # an untracked file is part of the tree too: the Stop hook commits it
  ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 1)" "an untracked file added after the run also moves the tree"
  rm -rf "$D2"
  # 1b A RUN INSIDE A WORKER'S FENCE says so in its verdict (caged=1), and cc-try will not put a PR live on it.
  D2=$(mktemp -d); R=$(newrepo caged); echo bwrap > "$D/pid1"; echo systemd > "$D/pid1-host"
  ( cd "$R" && CC_GREEN_PID1_COMM="$D/pid1" CC_GREEN_DIR="$D2" "$SELF" run >/dev/null 2>&1 )
  k "$(t grep -qx caged=1 "$D2"/*.verdict)" "a run where pid 1 is bwrap writes caged=1 into its verdict"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" 2>&1 )
  k "$(t test -n "$(grep 'green   lander check — passed' <<<"$out")" -a -z "$(grep 'caged checks only' <<<"$out")")" \
    "…and its green line does not say caged checks only: it ran every check it could"
  rm -rf "$D2"; D2=$(mktemp -d)
  ( cd "$R" && CC_GREEN_PID1_COMM="$D/pid1-host" CC_GREEN_DIR="$D2" "$SELF" run >/dev/null 2>&1 )
  k "$(nt grep -q caged "$D2"/*.verdict)" "…and a run on the host does not"
  rm -rf "$D2"
  # 1c A WORKER IN ITS FENCE ASKS AND RUNS NOTHING: under cc-loop (CC_GREEN_ASK) where pid 1 is bwrap, `start` writes the
  # request and starts no run, so nothing is left to die with the fence; the loop runs it on the host (green_kick).
  D2=$(mktemp -d); R=$(newrepo asked); mkdir -p "$D/askst"
  out=$( cd "$R" && CC_GREEN_ASK="$D/askst/green.ask" CC_GREEN_PID1_COMM="$D/pid1" CC_GREEN_DIR="$D2" "$SELF" start 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a -e "$D/askst/green.ask")" "in a fence under cc-loop, start writes the request and exits 0"
  k "$(t grep -q 'asked the loop to run lander check on this tree on the host' <<<"$out")" "…and says the loop runs it on the host"
  k "$(t test ! -e "$D/asked.args" -a -z "$(ls -A "$D2")")" "…having run no check and taken no lock, status or log"
  rm -f "$D/askst/green.ask"
  out=$( cd "$R" && CC_GREEN_ASK="$D/askst/green.ask" CC_GREEN_PID1_COMM="$D/pid1" CC_GREEN_DIR="$D2" "$SELF" start -- core/tests/check.sh 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 2 -a ! -e "$D/askst/green.ask" -a -n "$(grep 'the loop runs lander check for you on the host and no suite' <<<"$out")")" "in a fence, start -- SUITE is refused (exit 2) and asks nothing: the host runs no suite for a worker"
  ( cd "$R" && CC_GREEN_ASK="$D/askst/green.ask" CC_GREEN_PID1_COMM="$D/pid1" CC_GREEN_DIR="$D2" "$SELF" wait 1 >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 1)" "in a fence, wait exits 1 and never 3, so a worker does not sit in it"
  out=$( cd "$R" && CC_GREEN_ASK="$D/askst/green.ask" CC_GREEN_PID1_COMM="$D/pid1" CC_GREEN_DIR="$D2" "$SELF" 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 1 -a -n "$(grep -F "journaled in $D/askst/progress.md" <<<"$out")" -a -n "$(grep -F "copied to $D/askst/green.log" <<<"$out")")" \
    "in a fence, a bare cc-green exits 1 and points at the journal line and the green.log copy"
  rm -rf "$D2"; D2=$(mktemp -d); R=$(newrepo askhost)
  ( cd "$R" && CC_GREEN_ASK="$D/askst/green.ask" CC_GREEN_PID1_COMM="$D/pid1-host" CC_GREEN_DIR="$D2" "$SELF" start >/dev/null 2>&1 \
      && CC_GREEN_DIR="$D2" "$SELF" wait 30 >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a -e "$D/askhost.args" -a ! -e "$D/askst/green.ask")" "on the host, CC_GREEN_ASK changes nothing: start runs the check itself"
  rm -rf "$D2"; D2=$(mktemp -d); R=$(newrepo outside)
  ( cd "$R" && CC_GREEN_PID1_COMM="$D/pid1" CC_GREEN_DIR="$D2" "$SELF" run >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a -e "$D/outside.args")" "in a fence with no CC_GREEN_ASK (a member's loop), run still runs the check in there"
  rm -rf "$D2"
  # 1c' A WORKER WHOSE LOOP PREDATES THE ASK: a loop started before #1420 sets CC_ROLE=worker and no CC_GREEN_ASK, and
  # its worker's start ran the check in the fence and left no verdict (2026-10-17). Now it runs nothing and says why.
  D2=$(mktemp -d); R=$(newrepo stale)
  out=$( cd "$R" && CC_ROLE=worker CC_GREEN_PID1_COMM="$D/pid1" CC_GREEN_DIR="$D2" "$SELF" start 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 2 -a ! -e "$D/stale.args" -a -z "$(ls -A "$D2")")" "a worker in its fence with no CC_GREEN_ASK: start exits 2, having run no check and taken no lock, status or log"
  k "$(t grep -q 'set no CC_GREEN_ASK' <<<"$out")" "…and says its loop set no CC_GREEN_ASK"
  ( cd "$R" && CC_ROLE=worker CC_MEMBER_SANDBOX=1 CC_GREEN_PID1_COMM="$D/pid1" CC_GREEN_DIR="$D2" "$SELF" start >/dev/null 2>&1 \
      && CC_GREEN_DIR="$D2" CC_GREEN_PID1_COMM="$D/pid1" "$SELF" wait 30 >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a -e "$D/stale.args")" "…while inside a member boundary, where no loop asks, start still runs the check in there"
  rm -rf "$D2" "$D/stale.args"; D2=$(mktemp -d)
  ( cd "$R" && CC_ROLE=worker CC_GREEN_PID1_COMM="$D/pid1-host" CC_GREEN_DIR="$D2" "$SELF" start >/dev/null 2>&1 \
      && CC_GREEN_DIR="$D2" "$SELF" wait 30 >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a -e "$D/stale.args")" "…and a worker on the host (sandbox off) still starts its own run"
  rm -rf "$D2"
  # 1d A RUN THE HOST STARTS FOR A WORKER (CC_GREEN_FOR_WORKER=1) runs the pinned lander, caged checks only, and none of
  # the tree's own code: the fixture's core/lander/cli.py writes <name>.args when it runs, so its absence is the proof.
  printf '#!/bin/sh\necho "$*" > "%s/pinned.args"\necho "lander check: fake pinned"\n' "$D" > "$D/pinned"; chmod +x "$D/pinned"
  D2=$(mktemp -d); R=$(newrepo forw)
  ( cd "$R" && CC_GREEN_FOR_WORKER=1 CC_GREEN_LANDER="$D/pinned" CC_GREEN_PID1_COMM="$D/pid1-host" CC_GREEN_DIR="$D2" "$SELF" run >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a "$(cat "$D/pinned.args" 2>/dev/null)" = "check --caged-only $(git -C "$R" rev-parse --show-toplevel)")" \
    "for a worker, the run is the pinned lander's \`check --caged-only <root>\`, exit 0"
  k "$(nt test -e "$D/forw.args")" "…and the worktree's own core/lander/cli.py never ran"
  k "$(t grep -qx caged=1 "$D2"/*.verdict)" "…its verdict carries caged=1 though pid 1 is not bwrap"
  out=$( cd "$R" && CC_GREEN_FOR_WORKER=1 CC_GREEN_DIR="$D2" "$SELF" 2>&1 )
  k "$(t grep -q 'green   lander check — passed on this tree at .* (caged checks only)' <<<"$out")" "…and its green line says caged checks only"
  # A pinned release older than --caged-only refuses it as an unknown option: said loudly, no verdict, nothing else run.
  rm -rf "$D2"; D2=$(mktemp -d); R=$(newrepo forwold)
  printf '#!/bin/sh\necho "lander check: unknown option --caged-only" >&2\nexit 2\n' > "$D/oldpin"; chmod +x "$D/oldpin"
  out=$( cd "$R" && CC_GREEN_FOR_WORKER=1 CC_GREEN_LANDER="$D/oldpin" CC_GREEN_PID1_COMM="$D/pid1-host" CC_GREEN_DIR="$D2" "$SELF" run 2>&1 ); rc=$?
  k "$(t test "$rc" -ne 0 -a ! -e "$D/forwold.args" -a -n "$(grep 'PINNED LANDER PREDATES' <<<"$out")" -a -n "$(grep 'no verdict (exit 3' <<<"$out")")" \
    "for a worker, a pinned lander without --caged-only fails loudly with no verdict, and the tree's own never runs"
  rm -rf "$D2"; D2=$(mktemp -d); R=$(newrepo forwnone)
  ( cd "$R" && CC_GREEN_FOR_WORKER=1 CC_GREEN_LANDER="$D/absent" CC_GREEN_PID1_COMM="$D/pid1-host" CC_GREEN_DIR="$D2" "$SELF" run >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -ne 0 -a ! -e "$D/forwnone.args")" "for a worker with no pinned lander: no verdict, and still not the tree's own"
  # …and no suite, on a fixture whose suite HEAD tracks, so suite_ok alone would let it run (the control below does).
  rm -rf "$D2"; D2=$(mktemp -d); mkdir -p "$R/tests"
  printf '#!/bin/sh\ntouch "%s/forwsuite.ran"\n' "$D" > "$R/tests/check-x.sh"; chmod +x "$R/tests/check-x.sh"
  git -C "$R" add tests/check-x.sh && git -C "$R" commit -qm suite
  out=$( cd "$R" && CC_GREEN_FOR_WORKER=1 CC_GREEN_LANDER="$D/pinned" CC_GREEN_DIR="$D2" "$SELF" run -- tests/check-x.sh 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 2 -a ! -e "$D/forwsuite.ran" -a -n "$(grep 'a run for a worker is lander check only, never a suite' <<<"$out")")" \
    "for a worker, -- SUITE is refused (exit 2) and the suite never ran"
  ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run -- tests/check-x.sh >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a -e "$D/forwsuite.ran")" "…control: the same suite runs when the run is not for a worker"
  rm -rf "$D2"
  # 1e THE SLOT-WAIT RECORD'S NAMES come from .cc/track, which the worker writes: one carrying '/' or '..' is not taken.
  R=$(newrepo trk); mkdir -p "$R/.cc"
  printf '../../escape\nrow/../../x\n' > "$R/.cc/track"
  k "$(t test "$(GDIR="$D/g" wait_log "$R")" = "$D/g/waits-trk.tsv trk")" \
    "a .cc/track repo and row carrying '/' or '..' are refused: the record stays in the green dir under the fallback names"
  printf '..\n.hidden\n' > "$R/.cc/track"
  k "$(t test "$(GDIR="$D/g" wait_log "$R")" = "$D/g/waits-trk.tsv trk")" "…and so are a bare '..' and a leading dot"
  printf 'somerepo\nmy-row.2\n' > "$R/.cc/track"
  k "$(t test "$(GDIR="$D/g" wait_log "$R")" = "$D/g/waits-somerepo.tsv my-row.2")" "…control: plain names are taken as written"
  # 1f …and the file is read only when it is a regular one reached through no symlink. Each case is its own repo.
  R=$(newrepo trkfifo); mkdir -p "$R/.cc"; mkfifo "$R/.cc/track"
  out=$(GDIR="$D/g" timeout 10 bash -c "$(declare -f name_ok track_lines wait_log); wait_log \"\$1\"" _ "$R"); rc=$?
  k "$(t test "$rc" -eq 0 -a "$out" = "$D/g/waits-trkfifo.tsv trkfifo")" "a FIFO at .cc/track is not read: no stall, the fallback names stand"
  R=$(newrepo trklink); mkdir -p "$R/.cc"; printf 'hostrepo\nhostrow\n' > "$D/host-file"; ln -s "$D/host-file" "$R/.cc/track"
  k "$(t test "$(GDIR="$D/g" wait_log "$R")" = "$D/g/waits-trklink.tsv trklink")" "…nor a symlink at .cc/track, so a host file's lines never name the record"
  R=$(newrepo trkdir); mkdir -p "$D/hostdir"; printf 'hostrepo\nhostrow\n' > "$D/hostdir/track"; ln -s "$D/hostdir" "$R/.cc"
  k "$(t test "$(GDIR="$D/g" wait_log "$R")" = "$D/g/waits-trkdir.tsv trkdir")" "…nor a track reached through a symlinked .cc"
  R=$(newrepo trkreg); mkdir -p "$R/.cc"; printf 'regrepo\nregrow\n' > "$R/.cc/track"
  k "$(t test "$(GDIR="$D/g" wait_log "$R")" = "$D/g/waits-regrepo.tsv regrow")" "…control: a regular .cc/track on its own repo is read"
  D2=$(mktemp -d); R=$(newrepo never)
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 1 -a -n "$(grep 'no verdict on this worktree' <<<"$out")")" "a worktree nothing has run on is not green, exit 1"
  k "$(nt test -e "$D/never.args")" "…and a plain call runs nothing"
  rm -rf "$D2"

  # 2 LANDER CHECK'S EXIT → cc-green's ANSWER. 1 (a check red) and 3 (no verdict) are both exit 1, each said as
  # what it is, in the run, in `wait` and in a later plain call; and a red files nothing in the failures ledger —
  # lander check holds a red that is main's against main, so what it reports is the branch's own work.
  for p in 1 3; do
    D2=$(mktemp -d); R=$(newrepo "rc$p"); echo "$p" > "$D/rc$p.rc"
    out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run 2>&1 ); rc=$?
    if [ "$p" = 1 ]; then k "$(t test "$rc" -eq 1 -a -n "$(grep 'RED     lander check' <<<"$out")")" "lander check exit 1: the run is red, exit 1, and says RED"
    else k "$(t test "$rc" -eq 1 -a -n "$(grep 'RUN     lander check — no verdict (exit 3' <<<"$out")")" "lander check exit 3: the run is not green, exit 1, and says no verdict"; fi
    out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 5 2>&1 ); rc=$?
    k "$(t test "$rc" -eq 1 -a -n "$(grep 'has ended (exit 1)' <<<"$out")")" "…wait after it says the run ended with exit 1, and exits 1"
    ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" >/dev/null 2>&1 ); rc=$?
    k "$(t test "$rc" -eq 1)" "…and so does a plain call on the same tree"
    rm -rf "$D2"
  done
  k "$(t test -z "$(find "$CC_FAILURES" -name '*.jsonl' -size +0 2>/dev/null)")" "a red check writes nothing to the failures ledger"

  # 3 WHICH LANDER. No core/lander in the worktree: the `lander` on PATH, given `check <root>`. Neither: no verdict,
  # exit 1 — never a green, and never the pinned release's absence mistaken for a pass.
  D2=$(mktemp -d); R=$(newrepo onpath)
  ( cd "$R" && git rm -rq core/lander && git commit -qm nolander )
  mkdir -p "$D/pbin"; printf '#!/bin/sh\necho "$*" > "%s"\nexit 0\n' "$D/onpath.pathargs" > "$D/pbin/lander"; chmod +x "$D/pbin/lander"
  ( cd "$R" && PATH="$D/pbin:$PATH" CC_GREEN_DIR="$D2" "$SELF" run >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a "$(cat "$D/onpath.pathargs" 2>/dev/null)" = "check $(git -C "$R" rev-parse --show-toplevel)")" "a worktree with no core/lander runs the lander on PATH, \`check <root>\`"
  np=$(tr ':' '\n' <<<"$PATH" | while read -r p; do [ -x "$p/lander" ] || printf '%s:' "$p"; done); np=${np%:}
  out=$( cd "$R" && PATH="$np" CC_GREEN_DIR="$D2" "$SELF" run 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 1 -a -n "$(grep 'no lander here' <<<"$out")")" "…and with none on PATH either, the run says so and is not green, exit 1"
  rm -rf "$D2"

  # 4 A CHECK THAT MOVES THE TREE leaves a verdict for content this checkout no longer holds. That is the one way
  # `run` could hand back a false green, so it re-takes the tree afterwards, says what moved and keeps no verdict.
  D2=$(mktemp -d); R=$(newrepo dirty)
  printf '%s\n' 'open("residue.txt", "w").write("x")' > "$D/dirty.py"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 1)" "a check that dirties the tree does not come back green"
  k "$(t grep -q 'the run itself moved the tree.*residue.txt' <<<"$out")" "…and the file it left is named"
  k "$(nt ls "$D2"/*.verdict)" "…and no verdict is kept"

  # 5 NOT IN A CHECKOUT is exit 2, not a green: an answer about no tree at all must never read as an answer.
  mkdir -p "$D/nogit"; ( cd "$D/nogit" && "$SELF" >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 2)" "outside a git checkout it refuses, and does not report green"

  # 6 ONE RUN PER ROOT. A check slow enough to be caught going: a second `run` on the same root while it holds the
  # lock starts nothing and says so; `wait` says the same and gives the call back inside its bound; once it is
  # over, `wait` is the report. One line in the fake's log is the whole claim — one check ran.
  D2=$(mktemp -d); R=$(newrepo locked 15)
  ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run >/dev/null 2>&1 ) & p=$!
  for _ in $(seq 50); do [ -f "$D/locked.started" ] && break; sleep 0.1; done     # …the check is going, so the lock is held
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 3)" "a second run on the same root while one is going exits 3"
  k "$(t grep -q 'a run is already going' <<<"$out")" "…and says so"
  pid=$(sed -n 's/.*(pid \([0-9]*\),.*/\1/p' <<<"$out" | head -1)
  k "$(t test -n "$pid")" "…with the pid of the run that is"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" 2>&1 )
  k "$(t grep -q "a run is going on this worktree (pid $pid," <<<"$out")" "a plain call meanwhile says a run is going"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 1 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 3)" "wait while it is going gives the call back and exits 3"
  k "$(t grep -q "still running (pid $pid," <<<"$out")" "…naming the same pid"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 60 2>&1 ); rc=$?
  k "$rc" "wait after it has ended is the report, exit 0"
  k "$(t grep -q "green   lander check" <<<"$out")" "…for the tree the run passed on"
  wait "$p"
  k "$(t test "$(grep -cx check "$D/locked.log")" = 1)" "…and exactly one check ran"
  log=$(sed -n 's/^log=//p' "$D2"/run-*.status)
  k "$(t grep -q 'hand over now' "$log")" "…whose own log, at the path the status names, holds its report"
  rm -rf "$D2"

  # 7 …AND THE LOCK IS THE ROOT'S, NOT THE BOX'S. Two repos, two runs at once: a lock keyed by anything wider
  # than the root would have the second exit 3, and a worker on one worktree waiting on a check on another.
  D2=$(mktemp -d); R=$(newrepo rootA 2); R2=$(newrepo rootB 2)
  ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run >/dev/null 2>&1 ) & p=$!
  ( cd "$R2" && CC_GREEN_DIR="$D2" "$SELF" run >/dev/null 2>&1 ) & p2=$!
  wait "$p"; rc=$?; wait "$p2"; rc2=$?
  k "$(t test "$rc$rc2" = 00)" "two roots run at once, and neither is told the other's run is its own"
  k "$(t test "$(grep -cx check "$D/rootA.log")$(grep -cx check "$D/rootB.log")" = 11)" "…each running its own check once"
  rm -rf "$D2"

  # 8 THE CHECK CANNOT REACH A CREDENTIAL from here. The fake prints its environment; the run is started with a
  # token of each shape in its own, and the check must see none of them — but must see the non-secret CC_* and
  # the denial of the live config that cc-config honours. The control is the same fake run by hand.
  D2=$(mktemp -d); R=$(newrepo secret)
  printf '%s\n' "import re" "open('$D/secret.env', 'w').write(''.join(f'{k}={v}\\n' for k, v in sorted(os.environ.items()) if re.match(r'(FIX_TOKEN|FIX_API_KEY|FIX_SECRET|FIX_CREDS|GH_TOKEN|CC_KEEP|CC_CONFIG_DENY)\$', k)))" > "$D/secret.py"
  ( cd "$R" && FIX_TOKEN=t FIX_API_KEY=k FIX_SECRET=s FIX_CREDS=c GH_TOKEN=g CC_KEEP=yes python3 -P core/lander/cli.py check . ) >/dev/null 2>&1
  k "$(t grep -q '^FIX_TOKEN=t$' "$D/secret.env")" "control: run by hand, the fake carries the tokens it was given"
  ( cd "$R" && FIX_TOKEN=t FIX_API_KEY=k FIX_SECRET=s FIX_CREDS=c GH_TOKEN=g CC_KEEP=yes CC_GREEN_DIR="$D2" "$SELF" run ) >/dev/null 2>&1; rc=$?
  k "$rc" "a run with a token of each shape in its environment still goes green"
  k "$(nt grep -qE '^(FIX_TOKEN|FIX_API_KEY|FIX_SECRET|FIX_CREDS|GH_TOKEN)=' "$D/secret.env")" "…and the check saw none of them: *_TOKEN, *_KEY, *_SECRET and the named tokens are dropped"
  k "$(t grep -q '^CC_KEEP=yes$' "$D/secret.env")" "…while a non-secret CC_* passes"
  k "$(t grep -q "^CC_CONFIG_DENY=$(realpath -m "$HOME/.cc/config")\$" "$D/secret.env")" "…and the live ~/.cc/config is denied to it (CC_CONFIG_DENY, which cc-config reads as empty)"
  rm -rf "$D2"

  # 8b THE SLOT WAIT OUTLIVES THE LOG: the check is told the per-repo wait file and the row, from .cc/track when
  # the worktree has one, else the main checkout's name and the worktree's. The fake prints what it was told.
  for nm in waitrow waitbare; do
    printf '%s\n' "open('$D/$nm.env', 'w').write(os.environ.get('LANDER_WAIT_LOG', '-') + ' ' + os.environ.get('LANDER_WAIT_ROW', '-'))" > "$D/$nm.py"; done
  D2=$(mktemp -d); R=$(newrepo waitrow); mkdir -p "$R/.cc"; printf 'repo1\nrow1\n' > "$R/.cc/track"
  ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run ) >/dev/null 2>&1
  k "$(t test "$(cat "$D/waitrow.env")" = "$D2/waits-repo1.tsv row1")" "a run tells its check the repo's wait file and its row, from .cc/track"
  rm -rf "$D2"; D2=$(mktemp -d); R=$(newrepo waitbare)
  ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run ) >/dev/null 2>&1
  k "$(t test "$(cat "$D/waitbare.env")" = "$D2/waits-waitbare.tsv waitbare")" "…and with no .cc/track, the checkout's name and the worktree's"
  rm -rf "$D2"

  # 8c A RUN HELD ON A LANDER SLOT SAYS SO. The check is told the run's status file (LANDER_WAIT_NOTE); the fake
  # writes a `waiting=` line there as admission does past WAIT_SAY, and `wait` on the running run prints it. Before
  # that line is written, the same wait prints none.
  cat > "$D/slotwait.py" <<EOS
open(f"{D}/slotwait.started", "w").close(); time.sleep(3)
open(os.environ["LANDER_WAIT_NOTE"], "a").write("waiting=T0 lander: waiting for a check slot — not a hang\n")
open(f"{D}/slotwait.noted", "w").close(); time.sleep(4)
EOS
  D2=$(mktemp -d); R=$(newrepo slotwait)
  ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run >/dev/null 2>&1 ) & p=$!
  for _ in $(seq 50); do [ -f "$D/slotwait.started" ] && break; sleep 0.1; done
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 1 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 3)" "a run on a lander slot: wait while it is going exits 3"
  k "$(nt grep -q 'waiting for a check slot' <<<"$out")" "…and says nothing of a slot before the check notes one"
  for _ in $(seq 80); do [ -f "$D/slotwait.noted" ] && break; sleep 0.1; done
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 1 2>&1 ); rc=$?
  k "$(t grep -qx '  T0 lander: waiting for a check slot — not a hang' <<<"$out")" "…and once it has, wait prints the check's waiting= line under still running"
  wait "$p"; rm -rf "$D2"

  # 9 `red` WRITES ONE LEDGER RECORD PER KEY, with a bounded excerpt of the log that outlives it, and never fails
  # its caller: cc-loop's stops call it.
  printf 'line\n  ✗ the thing that broke\nmore\n' > "$D/red.log"
  out=$("$SELF" red redscope worker-loop/barren-stop "loop:x:5:1" --observed "cc-loop exit 5" --log "$D/red.log" --writer cc-loop 2>&1); rc=$?
  k "$(t test "$rc" -eq 0 -a -n "$(grep '^recorded f-' <<<"$out")")" "red records once and says the id"
  p=$("$BIN/cc-failures" show --json --scope redscope | jq -r '.[0].evidence[] | select(startswith("excerpt:")) | sub("^excerpt:";"")')
  rm -f "$D/red.log"
  k "$(t grep -q '✗ the thing that broke' "$p")" "…with an excerpt that still reads the red line once the log is gone"
  out=$("$SELF" red redscope worker-loop/barren-stop "loop:x:5:1" --observed "again" 2>&1)
  k "$(t test "$out" = "already $("$BIN/cc-failures" show --json --scope redscope | jq -r '.[0].id')")" "…and the same key again is 'already <id>', no second record"
  mkdir -p "$D/ro"; chmod 500 "$D/ro"
  out=$(CC_FAILURES="$D/ro/failures" "$SELF" red roscope worker-loop/barren-stop "k" --observed "x" 2>&1); rc=$?
  k "$(t test "$rc" -eq 0 -a -n "$(grep 'not recorded:' <<<"$out")")" "…and with the ledger unwritable it says not recorded, exit 0"
  chmod 700 "$D/ro"

  # 10 THE RUN WAITS ON THE CHECK, NOT ON WHAT IT LEAVES BEHIND. A check that leaves a child holding its stdout:
  # `run` comes back on the check's own exit — the verdict kept, the lock free — while the child is still going.
  D2=$(mktemp -d); R=$(newrepo linger)
  printf '%s\n' "import subprocess" "subprocess.Popen(['sh', '-c', 'sleep 15; touch $D/linger.done'])" > "$D/linger.py"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run 2>&1 ); rc=$?
  k "$rc" "a check that leaves a child behind is green on its own exit"
  k "$(t test ! -f "$D/linger.done")" "…and run came back while the child was still going, not when it was gone"
  k "$(t grep -q 'hand over now' <<<"$out")" "…with its report given"
  k "$(t flock -n "$(ls "$D2"/run-*.lock)" true)" "…and the root's lock free: the child holds no fd of the run's"
  rm -rf "$D2"

  # 11 A CTRL-C TAKES THE CHECK WITH IT. The check runs async in a shell with no job control, which starts it with
  # SIGINT ignored: without a group of its own and the run forwarding the signal, the INT ended cc-green and its
  # lock while the check ran on as an orphan. The fake says what pid it is, so its death is what this asserts.
  D2=$(mktemp -d); R=$(newrepo interrupted 8)
  # …started the way a terminal starts it, INT at default: a signal ignored at entry cannot be trapped, so the run
  # under a plain `&` here would sit through the INT and this case would pass on a tool that never handled one.
  ( cd "$R" && CC_GREEN_DIR="$D2" env --default-signal=INT,TERM "$SELF" run >/dev/null 2>&1 ) & p=$!
  for _ in $(seq 100); do [ -s "$D/interrupted.pid" ] && break; sleep 0.1; done
  gpid=$(head -1 "$D/interrupted.pid" 2>/dev/null)
  pid=$(sed -n 's/^pid=//p' "$D2"/run-*.status 2>/dev/null | head -1)
  k "$(t test -n "$gpid")" "a run with a slow check has a check of its own to lose"
  sleep 0.5                        # the run is on `wait`, past the breath between starting the check and trapping
  kill -INT "$pid" 2>/dev/null
  wait "$p"; rc=$?
  k "$(t test "$rc" -eq 130)" "an INT on a foreground run ends it, 130"
  for _ in $(seq 50); do kill -0 "$gpid" 2>/dev/null || break; sleep 0.1; done
  k "$(nt kill -0 "$gpid")" "…and the check goes with it, rather than running on as an orphan"
  k "$(t flock -n "$(ls "$D2"/run-*.lock)" true)" "…so the root's lock is free, and the next run is not a second one"
  k "$(nt grep -qx check "$D/interrupted.log")" "…and the check it interrupted never finished"
  rm -rf "$D2"

  # 12 A RUN OUTLIVES ITS LAUNCHER. A worker iteration's `setsid nohup cc-green run &` died with the iteration. Here
  # the launcher is a group leader of its own and the whole group is TERMed mid-check — what a tool ending
  # "everything this command started" does. The run finishes, keeps its verdict, and holds the lock while it goes.
  D2=$(mktemp -d); R=$(newrepo outlives 15)
  ( cd "$R" && CC_GREEN_DIR="$D2" exec setsid env --default-signal=INT,TERM "$SELF" run >/dev/null 2>&1 ) & p=$!
  for _ in $(seq 50); do [ -f "$D/outlives.started" ] && break; sleep 0.1; done
  k "$(nt test -e "/proc/$p/fd/9")" "a launcher whose run has started holds no fd 9 of its own"
  kill -TERM -- -"$p" 2>/dev/null; wait "$p"; rc=$?
  k "$(t test "$rc" -eq 143)" "a TERM on the launcher's group ends the launcher"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 3 -a -n "$(grep 'a run is already going' <<<"$out")")" "…while the run it started still holds the lock: a second run says already going, exit 3"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 60 2>&1 ); rc=$?
  k "$rc" "…and wait on that run is the report, exit 0"
  k "$(t grep -q 'has ended (exit 0)' <<<"$out")" "…saying the run ended with exit 0"
  k "$(t grep -q "green   lander check" <<<"$out")" "…and the check it ran is green"
  k "$(t test "$(grep -cx check "$D/outlives.log")" = 1)" "…one check ran"
  rm -rf "$D2"

  # 13 A KILLED RUN IS SAID TO BE KILLED. SIGKILL leaves no exit line, and the lock goes with the process: `wait`
  # must not call that green nor wait for ever, and the launcher following it must not exit 0.
  D2=$(mktemp -d); R=$(newrepo killed 8)
  ( cd "$R" && CC_GREEN_DIR="$D2" exec "$SELF" run >/dev/null 2>&1 ) & p=$!
  for _ in $(seq 100); do [ -s "$D/killed.pid" ] && break; sleep 0.1; done
  gpid=$(head -1 "$D/killed.pid" 2>/dev/null); pid=$(sed -n 's/^pid=//p' "$D2"/run-*.status 2>/dev/null | head -1)
  kill -KILL "$pid" 2>/dev/null; kill -KILL -- -"$gpid" 2>/dev/null   # the check too: a SIGKILLed run cannot take it along
  wait "$p"; rc=$?
  k "$(t test "$rc" -eq 1)" "a launcher whose run was SIGKILLed exits 1, not the run's green"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" timeout 10 "$SELF" wait 5 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 1)" "wait on a SIGKILLed run exits 1 at once, not 0 and not 3"
  k "$(t grep -q "the run (pid $pid, .*) was KILLED before it finished" <<<"$out")" "…and says the run was killed"
  rm -rf "$D2"

  # 14 A CTRL-C ON THE LAUNCHER IS A CTRL-C ON THE RUN. The run is in a session of its own, so a terminal's INT
  # reaches only the launcher; it carries the INT over, the run takes its check down, and wait says interrupted.
  D2=$(mktemp -d); R=$(newrepo ctrlc 8)
  ( cd "$R" && CC_GREEN_DIR="$D2" exec env --default-signal=INT,TERM "$SELF" run >/dev/null 2>&1 ) & p=$!
  for _ in $(seq 100); do [ -s "$D/ctrlc.pid" ] && break; sleep 0.1; done
  gpid=$(head -1 "$D/ctrlc.pid" 2>/dev/null); sleep 0.5
  kill -INT "$p" 2>/dev/null
  wait "$p"; rc=$?
  k "$(t test "$rc" -eq 130)" "an INT on the launcher ends the run, and the launcher exits with its 130"
  for _ in $(seq 50); do kill -0 "$gpid" 2>/dev/null || break; sleep 0.1; done
  k "$(nt kill -0 "$gpid")" "…and the run's check went with it"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 5 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 1 -a -n "$(grep 'was interrupted (exit 130)' <<<"$out")")" "…and wait says interrupted, exit 1"
  k "$(nt grep -qx check "$D/ctrlc.log")" "…and the check never finished"
  rm -rf "$D2"

  # 15 `__run` IS THE LAUNCHER'S. By hand it refuses; with a runid forged while a run holds the root it opens the
  # lock itself and finds it taken — never a second run.
  D2=$(mktemp -d); R=$(newrepo byhand 3)
  ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" __run >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 2)" "__run by hand refuses, exit 2"
  ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" run >/dev/null 2>&1 ) & p=$!
  for _ in $(seq 50); do [ -f "$D/byhand.started" ] && break; sleep 0.1; done
  out=$( cd "$R" && CC_GREEN_DIR="$D2" CC_GREEN_RUNID=forged "$SELF" __run 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 3 -a -n "$(grep 'a run is already going' <<<"$out")")" "…and a forged one while a run is going finds the lock taken, exit 3"
  wait "$p"
  k "$(t test "$(grep -cx check "$D/byhand.log")" = 1)" "…so one check ran"
  rm -rf "$D2"

  # 16 THE SCOPE. Where the user manager answers, the run sits in a transient scope of its own, out of the cgroup
  # that started it; CC_GREEN_SCOPE=0 keeps it in place. Both, on one slow fixture each.
  if timeout 10 systemd-run --user --scope --quiet --collect true </dev/null >/dev/null 2>&1; then
    for p2 in 1 0; do
      D2=$(mktemp -d); R=$(newrepo "scope$p2" 2)
      ( cd "$R" && CC_GREEN_DIR="$D2" CC_GREEN_SCOPE=$p2 "$SELF" run >/dev/null 2>&1 ) & p=$!
      for _ in $(seq 50); do [ -f "$D/scope$p2.started" ] && break; sleep 0.1; done
      pid=$(sed -n 's/^pid=//p' "$D2"/run-*.status 2>/dev/null | head -1)
      out=$(cat "/proc/$pid/cgroup" 2>/dev/null)
      if [ "$p2" = 1 ]; then k "$(t grep -q 'cc-green-' <<<"$out")" "a run gets a scope of its own where systemd-run --user answers"
      else k "$(t test -n "$out" -a "$out" = "$(cat /proc/$$/cgroup)")" "…and CC_GREEN_SCOPE=0 leaves it in the caller's cgroup"; fi
      wait "$p"; rm -rf "$D2"
    done
  else
    k 0 "no user manager answers systemd-run here: the scope cases are not checked"
  fi

  # 17 `start` IS THE WORKER'S ROUTE PAST A FOREGROUND TOOL CALL, with no setsid/nohup/& typed by the caller (the
  # classifier refused those twice, 2026-09-25). It returns while the check is still going; `wait` is 3, then the
  # report. `start -- SUITE` runs one of the repo's own suites in place of lander check, and `wait` answers with its
  # exit and no report — 1 for a suite that failed, 0 for one that passed.
  D2=$(mktemp -d); R=$(newrepo started 15)
  out=$( cd "$R" && CC_GREEN_DIR="$D2" timeout 20 "$SELF" start 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a -n "$(grep 'started lander check on' <<<"$out")")" "start returns 0 once the run is going, and says so"
  k "$(nt grep -qx check "$D/started.log")" "…before its check has finished"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 1 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 3)" "…so a short wait on it says still running, exit 3"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 60 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a -n "$(grep 'green   lander check' <<<"$out")")" "…and a longer one is the report, green, exit 0"
  k "$(t test "$(grep -cx check "$D/started.log")" = 1)" "…one check ran"
  mkdir -p "$R/tests" "$R/bin"
  printf '#!/bin/sh\nsleep 1; echo slow-suite-ran; exit 5\n' > "$R/tests/check-slow.sh"
  printf '#!/bin/sh\n[ "$1" = selfcheck ] && echo tool-selfcheck-ran\n' > "$R/bin/cc-tool"
  chmod +x "$R/tests/check-slow.sh" "$R/bin/cc-tool"; ( cd "$R" && git add -A && git commit -qm suites )
  out=$( cd "$R" && CC_GREEN_DIR="$D2" timeout 20 "$SELF" start -- tests/check-slow.sh 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0)" "start -- SUITE returns 0 once the repo's own suite is going"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 60 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 1 -a -n "$(grep 'has ended (exit 5)' <<<"$out")")" "…and wait on a suite that failed says its exit, exit 1"
  k "$(nt grep -q 'lander check' <<<"$out")" "…with no check report, which would answer a question nobody asked"
  k "$(t grep -qx slow-suite-ran "$(ls "$D2"/run-*.log)")" "…and the suite's output is in the run's log"
  ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" start -- ./bin/cc-tool selfcheck >/dev/null 2>&1 )
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 60 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a -n "$(grep 'has ended (exit 0)' <<<"$out")")" "…a tool's selfcheck runs the same way, and on one that passed, exit 0"
  # 17b NOTHING ELSE DETACHES. An open `-- CMD` would be a general way round the classifier's refusal of a detached
  # process (review of PR #675): any command, a tool with other arguments, a path out of the repo, a symlink, a
  # script HEAD does not track, and __run called straight — each refused, exit 2, and none of them runs.
  printf '#!/bin/sh\ntouch "%s/escaped"\n' "$D" > "$R/tests/check-new.sh"; chmod +x "$R/tests/check-new.sh"
  ln -s /bin/true "$R/tests/check-link.sh"
  printf '#!/bin/sh\ntouch "%s/escaped"\n' "$D" > "$R/bin/cc-nosc"; chmod +x "$R/bin/cc-nosc"
  ( cd "$R" && git add bin/cc-nosc && git commit -qm nosc )     # tracked, executable, and no selfcheck arm
  for c in "bin/cc-nosc selfcheck" "sh -c true" "bin/cc-tool rm" "tests/check-slow.sh extra" "../x/tests/check.sh" \
           "/bin/true" "tests/check-new.sh" "tests/check-link.sh" "bin/../tests/check-new.sh"; do
    # shellcheck disable=SC2086   # the words are the case
    out=$( cd "$R" && CC_GREEN_DIR="$D2" timeout 20 "$SELF" start -- $c 2>&1 ); rc=$?
    k "$(t test "$rc" -eq 2 -a -n "$(grep -E 'refused|not an executable file' <<<"$out")")" "start -- $c is refused with a reason, exit 2"
  done
  out=$( cd "$R" && CC_GREEN_DIR="$D2" timeout 20 "$SELF" run -- sh -c "touch $D/escaped" 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 2)" "…run -- CMD is refused the same way"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" CC_GREEN_RUNID=x timeout 20 "$SELF" __run -- sh -c "touch $D/escaped" 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 2)" "…and so is __run -- CMD called straight"
  sleep 1; k "$(nt test -e "$D/escaped")" "…and not one of them ran"
  ( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" start -- >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 2)" "start -- with no command is a usage error, exit 2"
  rm -rf "$D2"

  # 18 A STALE RUN IS STOPPED FOR ITS OWN WORKTREE, AND ONLY ITS OWN. Two roots each start a slow check; one root's
  # tree moves under its run. `start` there is refused and says the run is stale and names `stop`; `stop` ends that
  # run and its check, `wait` calls it interrupted, and `start` then runs on the new tree — while the other root's
  # run and check go on untouched. A lock held by a process that carries no runid of the note's is never signalled.
  D2=$(mktemp -d)
  for p2 in stA stB; do
    R=$(newrepo "$p2" 120)
    ( cd "$R" && CC_GREEN_DIR="$D2" CC_GREEN_SCOPE=0 timeout 20 "$SELF" start >/dev/null 2>&1 )
    for _ in $(seq 100); do [ -s "$D/$p2.pid" ] && break; sleep 0.1; done
  done
  R="$D/stA"; R2="$D/stB"; gpid=$(head -1 "$D/stA.pid"); p=$(head -1 "$D/stB.pid")
  GDIR=$D2 lock_files "$R2"; p2=$(status_field pid)
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" stop 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0 -a -n "$(grep 'stopped' <<<"$out")")" "stop on a root whose run is going ends it, exit 0"
  k "$(nt kill -0 "$gpid")" "…and its check is gone"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 5 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 1 -a -n "$(grep 'was interrupted' <<<"$out")")" "…and wait on it says interrupted, exit 1 — never green"
  k "$(t kill -0 "$p")" "…while the other root's check is still going"
  k "$(t kill -0 "$p2")" "…and so is the other root's run"
  out=$( cd "$R2" && CC_GREEN_DIR="$D2" "$SELF" wait 1 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 3)" "…which its own wait still calls running, exit 3"
  out=$( cd "$R2" && CC_GREEN_DIR="$D2" timeout 20 "$SELF" start 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 3)" "start on a root whose run is going is still refused, exit 3"
  k "$(nt grep -q 'cc-green stop' <<<"$out")" "…and with its tree unmoved nothing calls that run stale"
  echo two > "$R2/a.txt"
  out=$( cd "$R2" && CC_GREEN_DIR="$D2" timeout 20 "$SELF" start 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 3 -a -n "$(grep 'its verdict will not answer for it' <<<"$out")")" "…but once its tree has moved, the refusal says the run is stale"
  k "$(t grep -q 'cc-green stop' <<<"$out")" "…and names cc-green stop"
  out=$( cd "$R" && CC_GREEN_DIR="$D2" timeout 20 "$SELF" start 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0)" "after stop, start on that root runs again, exit 0 — no stale run holds it"
  for _ in $(seq 100); do [ "$(wc -l < "$D/stA.pid")" -ge 2 ] && break; sleep 0.1; done
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" stop 2>&1 ); rc=$?
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" stop 2>&1 ); rc2=$?
  k "$(t test "$rc$rc2" = 00 -a -n "$(grep 'nothing to stop' <<<"$out")")" "stop with no run going says so, exit 0"
  GDIR=$D2 lock_files "$R2"; runid=$(status_field runid)
  sleep 60 & pid=$!                                        # a process of ours that is no run: it carries no runid
  printf 'pid=%s\nrunid=%s\n' "$pid" "$runid" > "$STATUS"   # the lock held, the note naming it
  out=$( cd "$R2" && CC_GREEN_DIR="$D2" "$SELF" stop 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 1 -a -n "$(grep 'nothing signalled' <<<"$out")")" "a note naming a pid that is not the run's is refused, exit 1"
  k "$(t kill -0 "$pid")" "…and that pid is not signalled"
  k "$(t kill -0 "$p")" "…nor the run's check"
  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
  printf 'pid=%s\nrunid=%s\n' "$p2" "$runid" > "$STATUS"
  ( cd "$R2" && CC_GREEN_DIR="$D2" "$SELF" stop >/dev/null 2>&1 ); rc=$?
  k "$(t test "$rc" -eq 0)" "…and the note put right, the other root's own stop ends its run"
  k "$(t test "$(cat "$D/stA.log" "$D/stB.log" 2>/dev/null)" = "")" "…and no stopped check ever finished"
  rm -rf "$D2"

  # 18b START AND STOP IN TWO OF A WORKER'S BASH CALLS. Each call is a signal scope of its own (cc-nosignal-shell), so
  # the stop's call can neither read the run's environment nor signal it: the stop asks, and the run ends itself.
  if "$BIN/cc-nosignal" probe >/dev/null 2>&1; then
    D2=$(mktemp -d); R=$(newrepo stC 120)
    ( cd "$R" && CC_GREEN_DIR="$D2" CC_GREEN_SCOPE=0 timeout 20 "$BIN/cc-nosignal-shell" "$SELF start" >/dev/null 2>&1 )
    for _ in $(seq 100); do [ -s "$D/stC.pid" ] && break; sleep 0.1; done
    gpid=$(head -1 "$D/stC.pid"); GDIR=$D2 lock_files "$R"; p2=$(status_field pid)
    out=$( cd "$R" && CC_GREEN_DIR="$D2" "$BIN/cc-nosignal-shell" "test -r /proc/$p2/environ && : < /proc/$p2/environ" 2>&1 ); rc=$?
    k "$(t test "$rc" -ne 0)" "a second Bash call cannot read the run's environment (the control: why stop must ask)"
    out=$( cd "$R" && CC_GREEN_DIR="$D2" timeout 60 "$BIN/cc-nosignal-shell" "$SELF stop" 2>&1 ); rc=$?
    k "$(t test "$rc" -eq 0 -a -n "$(grep 'asking it to stop' <<<"$out")" -a -n "$(grep 'stopped' <<<"$out")")" \
      "stop in a later Bash call asks the run, and it stops, exit 0"
    k "$(nt kill -0 "$gpid")" "…and its check is gone"
    out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" wait 5 2>&1 ); rc=$?
    k "$(t test "$rc" -eq 1 -a -n "$(grep 'was interrupted' <<<"$out")")" "…and wait on it says interrupted, exit 1"
    k "$(t test "$(cat "$D/stC.log" 2>/dev/null)" = "")" "…and the check never finished"
    k "$(t test ! -e "$STATUS.stop")" "…and the stop took its .stop file away once the run was gone"
    rm -rf "$D2"
  else echo "  skip 18b: no Landlock signal scope here, so a Bash call is no scope of its own"; fi
  # 18c A STOP ASKED BEFORE THE CHECK STARTS. The watcher starts with the run, so a runid already in .stop while the
  # run is still taking its tree ends the run there, and its check never starts. A git whose write-tree takes 50 s
  # holds the run in that step: a watcher that started only with the check (the code before) let the run sit there
  # past the 45 s a `cc-green stop` waits on the run's lock, so that stop gave up though the run stopped later.
  D2=$(mktemp -d); R=$(newrepo stD 120); GDIR=$D2 lock_files "$R"; mkdir -p "$D2" "$D/sgit"; echo early > "$STATUS.stop"
  # Only the fixture's tree is slow, not the one green.sh takes of this checkout as cc-green sources it. The subcommand
  # is the first word past git's own options: green_tree leads with `-c key=value` pairs, and a stub that read only $1
  # never saw write-tree, so the run was not held there and this case stopped testing a stop during the hashing.
  printf '#!/bin/sh\nsub=; skip=; for a in "$@"; do if [ -n "$skip" ]; then skip=; continue; fi; case "$a" in -c|-C|--git-dir|--work-tree|--namespace|--config-env) skip=1;; -*) ;; *) sub=$a; break;; esac; done\n[ "$sub" = write-tree ] && [ "$(pwd -P)" = "%s" ] && for _ in $(seq 500); do [ -e "%s/sgit/go" ] && break; sleep 0.1; done\nexec %s "$@"\n' \
    "$(readlink -f "$R")" "$D" "$(command -v git)" > "$D/sgit/git"; chmod +x "$D/sgit/git"
  t0=$SECONDS
  out=$( cd "$R" && PATH="$D/sgit:$PATH" CC_GREEN_DIR="$D2" CC_GREEN_RUNID=early timeout 60 "$SELF" __run 2>&1 ); rc=$?
  k "$(t test "$((SECONDS - t0))" -lt 45)" "a stop asked while the run takes its tree ends it inside the 45 s a stop waits ($((SECONDS - t0)) s)"
  k "$(t test "$rc" -ne 0 -a "$rc" -ne 124 -a -n "$(grep 'asked to stop' <<<"$out")")" "…not exit 0 and not the timeout, and it says it was asked"
  k "$(t test ! -e "$D/stD.pid")" "…and its check never started"
  touch "$D/sgit/go"; rm -rf "$D2"

  # THE WORKER SANDBOX'S SHAPE: only the control repo's core/bin is bound there, as ~/bin, so no tests/ sits beside
  # it. A copy of this bin with nothing beside it stands in for that. With the checkout carrying core/tests/green.sh,
  # `start` finds the worktree's own and its run goes; with none, it exits 2 and nothing is started (2026-10-14: it
  # said "No such file", then "started", and two workers each waited out an iteration on a run that never began).
  mkdir -p "$D/sb/bin"; cp "$SELF" "$BIN/cc-nosignal" "$D/sb/bin/"
  D2=$(mktemp -d); R=$(newrepo sbown); mkdir -p "$R/core/tests"; cp "$TESTS/green.sh" "$R/core/tests/"
  ( cd "$R" && git add -A && git commit -qm tests )
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$D/sb/bin/cc-green" start 2>&1 ); rc=$?
  k "$(t test "$rc" = 0 -a -n "$(grep 'started lander check' <<<"$out")")" "a bin with no tests/ beside it, in a checkout carrying core/tests/green.sh, starts its run, exit 0"
  ( cd "$R" && CC_GREEN_DIR="$D2" "$D/sb/bin/cc-green" wait 60 ) >/dev/null 2>&1
  k "$(t test "$(cat "$D/sbown.args" 2>/dev/null)" = "check $(git -C "$R" rev-parse --show-toplevel)")" "…and that run ran the checkout's lander check"
  rm -rf "$D2"
  D2=$(mktemp -d); R=$(newrepo sbnone)
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$D/sb/bin/cc-green" start 2>&1 ); rc=$?
  k "$(t test "$rc" = 2 -a -n "$(grep 'no tests/green.sh .* nothing was started' <<<"$out")")" "a bin with no tests/ beside it, in a checkout with none either, exits 2 and says nothing was started"
  k "$(t test -z "$(grep 'started lander check' <<<"$out")" -a ! -e "$D/sbnone.args" -a -z "$(ls -A "$D2")")" "…and claims no run, runs no check and leaves no run state"
  rm -rf "$D2"

  # THE RECURRING DEFECTS: every catalogue class against its own fixtures, then the report holding a hand-over on one.
  out=$(python3 "$CORE/tests/recurring_defects.py" selftest 2>&1); rc=$?
  k "$rc" "every recurring-defect class goes red on its fixture diff and holds its suppressed cases ($(tail -1 <<<"$out"))"
  [ "$rc" = 0 ] || grep -A3 FAIL <<<"$out"
  D2=$(mktemp -d); R=$(newrepo defects); mkdir -p "$R/bin" "$D/reviews"
  ( cd "$R" && git update-ref refs/remotes/origin/main HEAD && CC_GREEN_DIR="$D2" "$SELF" run ) >/dev/null 2>&1
  for p in 1 2; do printf 'VERDICT: LAND-AFTER-FIX\n\n1. x:1 — the tick never asks cc-pause is <repo>\n' > "$D/reviews/r-$p-00000000000$p.md"; done
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" 2>&1 ); rc=$?
  k "$(t test "$rc" = 0 -a -n "$(grep 'clean   recurring defects' <<<"$out")")" "a green tree whose diff carries no recurring defect is green, and says it looked"
  printf '#!/usr/bin/env bash\ncc "$repo" "$row" --go "$brief"\n' > "$R/bin/cc-tick"
  ( cd "$R" && git add -A && git commit -qm tick && CC_GREEN_DIR="$D2" "$SELF" run ) >/dev/null 2>&1
  out=$( cd "$R" && CC_GREEN_DIR="$D2" "$SELF" 2>&1 ); rc=$?
  k "$(t test "$rc" = 1 -a -n "$(grep 'DEFECT  pause-hold-missing at bin/cc-tick:2' <<<"$out")")" "a green tree whose diff launches with no pause check is NOT green, and names the line"
  k "$(t grep -q 'green   lander check' <<<"$out")" "…while its check itself is green"
  rm -rf "$D2"

  # THE TREE IS HASHED ON THE HOST WITHOUT RUNNING THE WORKER'S PROGRAMS. cc-loop asks for it in a worker's tree, and
  # with extensions.worktreeConfig on the admin dir's config.worktree is repo config: a core.fsmonitor and a
  # post-index-change hook planted there (as a worker could before cc-sandbox walled that file) run on a plain
  # `git add -A`. green_tree still answers, and runs neither; the control runs the same plant with plain git.
  local cw="$D/cfgwt" cwt="$D/cfgwt-t" ctree
  git init -q -b main "$cw" && printf '[extensions]\n\tworktreeConfig = true\n' >> "$cw/.git/config" \
    && git -C "$cw" -c user.name=t -c user.email=t@t commit -q --allow-empty -m i && git -C "$cw" worktree add -q -b track/t "$cwt" >/dev/null 2>&1
  mkdir -p "$cwt/.hk"; printf '#!/bin/sh\ntouch "%s/cw.fsm"\nexit 1\n' "$D" > "$cwt/.fsm"; printf '#!/bin/sh\ntouch "%s/cw.hook"\n' "$D" > "$cwt/.hk/post-index-change"
  chmod +x "$cwt/.fsm" "$cwt/.hk/post-index-change"
  printf '[core]\n\tfsmonitor = %s/.fsm\n\thooksPath = %s/.hk\n' "$cwt" "$cwt" > "$cw/.git/worktrees/cfgwt-t/config.worktree"
  echo x > "$cwt/f"; ctree=$(green_tree "$cwt")
  k "$([ -n "$ctree" ] && [ ! -e "$D/cw.fsm" ] && [ ! -e "$D/cw.hook" ] && echo 0 || echo 1)" \
    "green_tree hashes a worker's tree without running the fsmonitor or hook its config.worktree names"
  git -C "$cwt" add -A >/dev/null 2>&1
  k "$([ -e "$D/cw.fsm" ] && [ -e "$D/cw.hook" ] && echo 0 || echo 1)" "…control: plain git add -A there runs both"
  git -C "$cw" worktree remove --force "$cwt" >/dev/null 2>&1

  echo "cc-green selfcheck: $((n - f)) passed, $f failed"
  [ "$f" -eq 0 ]
}
