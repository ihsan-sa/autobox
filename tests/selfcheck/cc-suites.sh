# shellcheck shell=bash disable=SC2154,SC2034
# cc-suites's selfcheck cases, moved out of bin/cc-suites. That tool's selfcheck() sources this file, whose
# definition replaces it, and then calls it: the cases run in the tool's own shell, with its functions and
# globals, as they did when the body sat there. SC2154/SC2034 are off because those globals live in bin/cc-suites.

selfcheck(){
  local D pass=0 fail=0 R out rc p1 p2 p3 p4 tree
  D=$(mktemp -d "${TMPDIR:-/tmp}/cc-suites-selfcheck.XXXXXX") || return 1
  k(){ if [ "$1" = 0 ]; then pass=$((pass + 1)); echo "  ✓ $2"; else fail=$((fail + 1)); echo "  ✗ $2"; fi; }
  t(){ "$@" >/dev/null 2>&1; echo $?; }
  b(){ if eval "$1"; then echo 0; else echo 1; fi; }   # a condition as a case
  export CC_SUITES_DIR="$D/sd" CC_SUITES_RUNNER_DIR="$D/runner" CC_GREEN_DIR="$D/green"
  SD="$D/sd"; RUNNER_DIR="$D/runner"   # this shell's own view too: the cases below call its functions
  unset CC_SUITES_SSH CC_SUITES_GPUSTAT_TIMEOUT CC_SUITE_PART CC_LAND_CHANGED CC_SUITES_SPILL_TIMEOUT CC_SUITES_RUNNER_TIMEOUT
  # the runner's view of power and load is a fixture too: on AC (no supply info) and idle, unless a case says not
  mkdir -p "$D/power" && echo "0.00 0.00 0.00 1/1 1" > "$D/loadavg"
  export CC_SUITES_POWER_DIR="$D/power" CC_SUITES_LOADAVG="$D/loadavg" CC_SUITES_RUNNER_NEEDS="bash git"
  export CC_SUITES_FLOOR="$D/floor"; FLOOR="$D/floor"   # none unless a case writes one (never this host's /etc)
  # --- REAP: four fake runs under $D, each on a fixture of its own; only $D is looked at (CC_SUITES_REAP_UNDER)
  mkdir -p "$D/a/tests" "$D/b/tests" "$D/c/tests" "$D/d/tests"
  for x in a b c d; do printf 'sleep 300\n' > "$D/$x/tests/selftest.sh"; done
  sleep 300 & local live=$!
  ( exec env CC_SELFTEST_HELD=999999999 bash "$D/a/tests/selftest.sh" ) >/dev/null 2>&1 & p1=$!     # owner gone
  ( exec env CC_SELFTEST_HELD=$live bash "$D/b/tests/selftest.sh" ) >"$D/b.log" 2>&1 & p2=$!        # owned, logging: kept
  ( exec env CC_SELFTEST_HELD=$live bash "$D/c/tests/selftest.sh" ) >"$D/c.log" 2>&1 & p3=$!        # log deleted
  ( exec env CC_SELFTEST_HELD=$live bash "$D/d/tests/selftest.sh" ) >"$D/d.log" 2>&1 & p4=$!        # tree deleted
  sleep 0.5; rm -f "$D/c.log"; rm -rf "$D/d"
  out=$(CC_SUITES_REAP_UNDER="$D" reap --dry)
  k "$(t kill -0 $p1)" "a dry reap kills nothing…"
  k "$(b 'grep -c '\''would reap'\'' <<<"$out" | grep -qx 3')" "…and names the three orphans: $(grep -o 'gone\|deleted' <<<"$out" | tr '\n' ' ')"
  out=$(CC_SUITES_REAP_UNDER="$D" reap)
  sleep 0.3
  k "$(b '! kill -0 $p1 2>/dev/null')" "a run whose slot holder is gone is reaped"
  k "$(t kill -0 $p2)" "…and a run whose holder and log are both there is kept"
  k "$(b '! kill -0 $p3 2>/dev/null')" "a run whose log was deleted is reaped"
  k "$(b '! kill -0 $p4 2>/dev/null')" "a run whose suite file was deleted (worktree removed) is reaped"
  out=$(CC_SUITES_REAP_UNDER="$D/elsewhere" reap)
  k "$(b '[ -z "$out" ] && kill -0 $p2 2>/dev/null')" "a reap scoped elsewhere touches nothing under $D"
  # a run started by a RELATIVE path from its own dir, reaped from a cwd where that path means nothing: kept, and
  # the same run once its suite file is gone: reaped (the path is resolved from the run's cwd, not the reaper's)
  mkdir -p "$D/e/tests" "$D/f/tests"; printf 'sleep 300\n' > "$D/e/tests/selftest.sh"; printf 'sleep 300\n' > "$D/f/tests/selftest.sh"
  local p5 p6
  ( cd "$D/e" && exec env CC_SELFTEST_HELD=$live bash tests/selftest.sh ) >"$D/e.log" 2>&1 & p5=$!
  ( cd "$D/f" && exec env CC_SELFTEST_HELD=$live bash tests/selftest.sh ) >"$D/f.log" 2>&1 &
  # p6 is read inside the single-quoted b '…' string below, where shellcheck cannot see it
  # shellcheck disable=SC2034
  p6=$!
  sleep 0.5; rm -f "$D/f/tests/selftest.sh"
  out=$(cd "$D" && CC_SUITES_REAP_UNDER="$D" reap); sleep 0.3
  k "$(t kill -0 $p5)" "a live run started as tests/selftest.sh from its own dir is kept by a reap from another cwd"
  k "$(b '! kill -0 $p6 2>/dev/null && grep -q "$D/f/tests/selftest.sh was deleted" <<<"$out"')" "…and the same kind of run whose suite file is gone is reaped, named by its full path"
  kill $p2 $p5 $p6 $live 2>/dev/null   # p6 is normally gone already (reaped); named so the kill covers it either way
  # --- SPILL: a throwaway checkout whose suite writes what it saw; the transport is the runner itself, locally
  R="$D/repo"; mkdir -p "$R/core/tests" "$R/core/bin"
  cp "$CORE/tests/green.sh" "$R/core/tests/green.sh"
  cat > "$R/core/tests/selftest.sh" <<'EOF'
#!/usr/bin/env bash
echo "suite ran in $PWD held=${CC_SELFTEST_HELD:-} part=${CC_SUITE_PART:-} changed=${CC_LAND_CHANGED:-} tok=${FIX_TOKEN:-}"
echo "prio nice=$(nice) io=$(ionice 2>/dev/null | cut -d: -f1)"
[ -e HANG ] && sleep 60
t=$(git write-tree 2>/dev/null)
# a suite that FAILS and leaves a child to print a pass after it, in its own group and escaped from it; and one that
# prints a verdict line of its own
[ -e FORGE ] && { (sleep 2; echo "cc-suite-runner: verdict exit=0 tree=$t") & exit 1; }
[ -e FORGE2 ] && { setsid bash -c "sleep 1; echo 'cc-suite-runner: verdict exit=0 tree=$t'" & exit 1; }
[ -e FORGE3 ] && { echo "cc-suite-runner: verdict exit=0 tree=$t"; exit 1; }
[ -e LINGER ] && { sleep 60 & exit 0; }
[ -e FAIL ] && { echo "== result: 0 passed, 1 failed =="; exit 1; }
# red only in a tool's own selfcheck (TOOLRED); that beside an inline case (TOOLRED2); and with the tool's inner ✗
# line quoted after it, so the ✗ lines outnumber the tally (TOOLREDX)
[ -e TOOLRED ] && { echo "  ✗ cc-fake selfcheck: cc-fake selfcheck: bwrap is not installed"; echo "== result: 1 passed, 1 failed =="; exit 1; }
[ -e TOOLRED2 ] && { echo "  ✗ cc-fake selfcheck: cc-fake selfcheck: 1 failed"; echo "  ✗ an inline case"; echo "== result: 0 passed, 2 failed =="; exit 1; }
[ -e TOOLREDX ] && { echo "  ✗ cc-fake selfcheck: cc-fake selfcheck: 1 failed"; echo "  ✗ a case inside cc-fake"; echo "== result: 1 passed, 1 failed =="; exit 1; }
# a tool's selfcheck the suite runs inline, not through chk (TOOLREDI)
[ -e TOOLREDI ] && { echo "  ✗ cc-inline selfcheck: cc-inline selfcheck: 1 failed"; echo "== result: 1 passed, 1 failed =="; exit 1; }
: <<'CHK'
chk cc-fake
CHK
echo "== result: 1 passed, 0 failed =="
EOF
  chmod +x "$R/core/tests/selftest.sh"
  # the tool a red there names, as this checkout has it: it logs each run, and is red while $D/fake-red exists
  printf '#!/usr/bin/env bash\necho "$*" >> "%s/fake.calls"\necho "log_only=${CC_NOTIFY_LOG_ONLY:-} tier=${CC_SPEND_TIER:-}" > "%s/fake.env"\n[ -e "%s/fake-red" ] && { echo "cc-fake selfcheck: 0 passed, 1 failed"; exit 1; }\necho "cc-fake selfcheck: 1 passed, 0 failed"\n' "$D" "$D" "$D" > "$R/core/bin/cc-fake"
  chmod +x "$R/core/bin/cc-fake"; cp "$R/core/bin/cc-fake" "$R/core/bin/cc-inline"
  ( cd "$R" && git init -q && git add -A && git -c user.name=t -c user.email=t@t commit -qm init )
  cat > "$D/xport" <<EOF
#!/usr/bin/env bash
# the stub ssh: the forced command, run by the runner code, with a HOME of its own and none of this shell's secrets
exec env -u FIX_TOKEN HOME="$D/rhome" CC_SUITES_RUNNER_PREP=0 SSH_ORIGINAL_COMMAND="\$*" CC_SUITES_RUNNER_DIR="$D/runner" bash "$SELF" runner
EOF
  chmod +x "$D/xport"; mkdir -p "$D/rhome"
  out=$(bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ]')" "no runner set: spill says 75 and runs nothing (got $rc)"
  out=$(bash "$SELF" status 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && grep -q '\''no runner set'\'' <<<"$out"')" "…and status says there is none"
  export CC_SUITES_SSH="$D/xport"
  tree=$(cd "$R" && . core/tests/green.sh && green_tree "$R")
  out=$(FIX_TOKEN=sekrit CC_LAND_CHANGED="core/bin/x" bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ]')" "a free runner runs the suite and its pass is this exit (got $rc)"
  k "$(b 'grep -q "suite ran in $D/runner/run\." <<<"$out"')" "…in a scratch copy on the runner, not in this checkout"
  k "$(b 'grep -q '\''changed=core/bin/x tok=$'\'' <<<"$out"')" "…with CC_LAND_CHANGED carried over and no token of this shell's"
  k "$(b 'grep -q "held=[0-9]" <<<"$out"')" "…holding the runner's slot, so it takes none of its own"
  k "$(b 'ls "$D/green/selftest.sh-${tree:0:12}.json" >/dev/null 2>&1')" "…and files the green record for exactly the tree it ran"
  k "$(b 'ls "$D/runner"/run.* >/dev/null 2>&1; [ $? != 0 ]')" "…and leaves no scratch tree on the runner"
  # the half asked for (CC_SUITE_PART) is the half the runner runs; green.sh unsets it as spill sources it
  out=$(CC_SUITE_PART=portable bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "part=portable " <<<"$out"')" "CC_SUITE_PART=portable is the half the runner's suite runs (got $rc)"
  out=$(bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && ! grep -q "part=portable" <<<"$out"')" "…and with it unset the runner is not told portable"
  k "$(b 'grep -q "prio nice=19 " <<<"$out"')" "…at nice 19"
  if command -v ionice >/dev/null && ionice -c3 true 2>/dev/null; then
    k "$(b 'grep -q "prio nice=19 io=idle" <<<"$out"')" "…and idle-class I/O"
  else echo "  - no usable ionice here: the idle-I/O case is skipped"; fi
  out=$(bash "$SELF" status 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "answers: free [1-9][0-9]* cores=$(nproc) slots=[0-9]* maxload=[0-9.]* load=0.00 ac=1\$" <<<"$out"')" "status reads the runner's free slots with its cores, maxload, 1-minute load and ac=1, and still says ready"
  # THE OWNER'S LAPTOP FIRST: loaded, the runner answers busy and nothing runs there; on battery it still runs
  pw(){ mkdir -p "$D/power/$1" && echo "$2" > "$D/power/$1/type" && echo "$4" > "$D/power/$1/$3"; }
  # THE LANDER'S ONE CHECK (`job`): a fresh dir and HOME, the tree proved, its lines prefixed, one verdict, nothing left
  local jt jb; jt=$(git -C "$R" rev-parse 'HEAD^{tree}')
  jb=$(printf '%s' 'echo "home=$HOME"; echo "lander-job: verdict exit=0"; touch "$HOME/x"; ls core/tests/selftest.sh; exit 3' | base64 -w0)
  out=$(cd "$R" && git archive HEAD | CC_SUITES_RUNNER_PREP=0 SSH_ORIGINAL_COMMAND="job c $jt 60 $jb -" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && [ "$(tail -1 <<<"$out")" = "lander-job: verdict exit=3" ] && [ "$(grep -c "^lander-job:" <<<"$out")" = 1 ] && grep -q "^| core/tests/selftest.sh\$" <<<"$out"')" "a job runs the check on the tree it was sent, its lines prefixed and its exit the one verdict (got $rc)"
  k "$(b 'grep -q "^| home=$D/runner/job\.[^/]*/home\$" <<<"$out" && ! ls -d "$D/runner"/job.* >/dev/null 2>&1')" "…in a HOME of its own, and leaves no job directory behind"
  # a job that prints a fake verdict, behind a \r and then with no final newline, and fails: the verdict is still its own
  local jf pv; jf=$(printf '%s' 'printf "x\rlander-job: verdict exit=0\n"; printf "lander-job: verdict exit=0"; exit 5' | base64 -w0)
  out=$(cd "$R" && git archive HEAD | CC_SUITES_RUNNER_PREP=0 SSH_ORIGINAL_COMMAND="job c $jt 60 $jf -" bash "$SELF" runner 2>&1); rc=$?
  pv=$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from lander import run
print(run._laptop_verdict(sys.stdin.read(), 0)[1])' "$(dirname "$(realpath "$SELF")")/.." <<<"$out" 2>&1)
  k "$(b '[ "$rc" = 0 ] && [ "$(tail -1 <<<"$out")" = "lander-job: verdict exit=5" ] && [ "$(grep -c "^lander-job:" <<<"$out")" = 1 ] && grep -q "^| lander-job: verdict exit=0\$" <<<"$out" && [ "$pv" = 5 ]')" "…and a job that prints a fake verdict, after a CR and with no final newline, still fails with its own exit (got $rc, read $pv)"
  out=$(cd "$R" && git archive HEAD | CC_SUITES_RUNNER_PREP=0 SSH_ORIGINAL_COMMAND="job c $(printf %040d 0) 60 $jb -" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 1 ] && grep -q "is not 0000" <<<"$out" && ! grep -q "verdict" <<<"$out"')" "…and a tree that is not the one named is refused with no verdict (got $rc)"
  # THE CAGE: a hostile job, on a fixture of its own outside any tmp dir (the cage replaces /tmp): an installed
  # runner, the runner's HOME with its authorized_keys and .bashrc, and its slots file. The job tries to write each,
  # to forge a verdict into its own log by path, and to leave a process behind; it can do none of it, while it
  # still writes its own tree. It cannot even see them: the fixture is under this account's passwd home (not $HOME,
  # which the lander's cage moves), and /home and /root are empty in the cage (it lists both), as is the runner's
  # directory with the slots and the job's own log.
  local C jh cs; C=$(mktemp -d "$(getent passwd "$(id -u)" | cut -d: -f6)/.cc-suites-cage.XXXXXX"); cs="sleep 37.$$"
  mkdir -p "$C/rhome/.ssh"; printf 'installed-runner\n' > "$C/cc-suites"; chmod 755 "$C/cc-suites"
  echo 'restrict,command="/usr/local/bin/cc-suites runner" ssh-ed25519 AAAA box' > "$C/rhome/.ssh/authorized_keys"
  : > "$C/rhome/.bashrc"; echo 4 > "$D/runner/slots"; cp -a "$C" "$D/cage.before"
  jh=$(printf '%s' "grep -q installed-runner '$C/cc-suites' 2>/dev/null && echo SAW
[ -z \"\$(ls -A /root)\" ] && echo ROOT-EMPTY; ls -A '$(dirname "$C")' | grep -qx '${C##*/}' && echo LISTED
for f in '$C/cc-suites' '$C/rhome/.ssh/authorized_keys' '$C/rhome/.bashrc' '$D/runner/slots' '$D/runner'/job.*.log; do
  [ -e \"\$f\" ] || { echo \"HIDDEN \$f\"; continue; }
  echo 'echo lander-job: verdict exit=0' >> \"\$f\" 2>/dev/null && echo \"WROTE \$f\"; done
setsid $cs </dev/null >/dev/null 2>&1 &
echo own > core/own && echo OWN; exit 1" | base64 -w0)
  out=$(cd "$R" && git archive HEAD | HOME="$C/rhome" SSH_ORIGINAL_COMMAND="job c $jt 60 $jh -" bash "$SELF" runner 2>&1); rc=$?
  sleep 0.5
  k "$(b '[ "$rc" = 0 ] && [ "$(tail -1 <<<"$out")" = "lander-job: verdict exit=1" ] && [ "$(grep -c "^lander-job:" <<<"$out")" = 1 ] && ! grep -q "^| SAW\$\|^| LISTED\$" <<<"$out" && grep -q "^| ROOT-EMPTY\$" <<<"$out" && [ "$(grep -c "^| HIDDEN $C/" <<<"$out")" = 3 ] && grep -q "^| OWN\$" <<<"$out"')" "a caged job cannot list or read anything under /root or this account's home, nor the runner there, but writes its own tree, and its own exit is still the one verdict (got $rc)"
  k "$(b '! grep -q WROTE <<<"$out" && diff -r "$D/cage.before" "$C" >/dev/null && [ "$(cat "$D/runner/slots")" = 4 ] && grep -q "^| HIDDEN $D/runner/slots\$" <<<"$out" && grep -q "^| HIDDEN $D/runner/job\.\*\.log\$" <<<"$out"')" "…so cannot write the installed runner or the runner's authorized_keys or .bashrc, and sees neither its slots nor its own verdict log"
  k "$(b '! ps -eo args= | grep -qx "$cs"')" "…and nothing it started outlives it"
  out=$(bash "$SELF" status 2>&1)
  k "$(b 'grep -q "answers: free 4 " <<<"$out"')" "…nor holds its slot: status answers every slot free after it (got: ${out%% cores=*})"
  pkill -KILL -x -f "$cs" 2>/dev/null; rm -rf "$C" "$D/cage.before" "$D/runner/slots"
  # NO NETWORK: a listener of this selfcheck's own on this machine's loopback stands in for the box's services (it
  # is bound to loopback only, so the selfcheck opens nothing to the outside). A caged job cannot open a socket to
  # it, and has no interface but its own lo, so no tailnet either; the same job sent with `net` (a manifest's
  # net = true) reaches it; any other sixth word is refused before anything runs.
  local lp lpid ln jn; ln="$D/listen.port"; rm -f "$ln"
  python3 -c 'import socket, sys
s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(8); open(sys.argv[1], "w").write(str(s.getsockname()[1]))
while True: s.accept()[0].close()' "$ln" & lpid=$!
  for _ in $(seq 1 50); do [ -s "$ln" ] && break; sleep 0.1; done; lp=$(cat "$ln" 2>/dev/null)
  jn=$(printf '%s' "echo IF \$(awk -F: \"NR > 2 { print \\\$1 }\" /proc/net/dev); python3 -c 'import socket, sys
try: socket.create_connection((\"127.0.0.1\", int(sys.argv[1])), timeout=3); print(\"REACHED\")
except OSError: print(\"CUT\")' $lp" | base64 -w0)
  out=$(cd "$R" && git archive HEAD | CC_SUITES_RUNNER_PREP=0 SSH_ORIGINAL_COMMAND="job c $jt 60 $jn -" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ -n "$lp" ] && [ "$rc" = 0 ] && grep -qx "| CUT" <<<"$out" && grep -qx "| IF lo" <<<"$out" && ! grep -q "REACHED" <<<"$out"')" "a caged job cannot open a socket to a service on this machine, and has no interface but lo (got $rc)"
  out=$(cd "$R" && git archive HEAD | CC_SUITES_RUNNER_PREP=0 SSH_ORIGINAL_COMMAND="job c $jt 60 $jn - net" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -qx "| REACHED" <<<"$out"')" "…and the same job sent with net reaches it (got $rc)"
  out=$(cd "$R" && git archive HEAD | CC_SUITES_RUNNER_PREP=0 SSH_ORIGINAL_COMMAND="job c $jt 60 $jn - share" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 2 ] && grep -q "refused: job CHECK TREE CAP RUN_B64 CWD_B64 \[net\]" <<<"$out" && ! grep -q "REACHED\|CUT\|IF \|verdict" <<<"$out"')" "…and any sixth word but net is refused and runs nothing (got $rc)"
  # a check name with a newline in it arrives as two lines, the first a well-formed job ending in net: refused whole
  out=$(cd "$R" && git archive HEAD | CC_SUITES_RUNNER_PREP=0 SSH_ORIGINAL_COMMAND="job c $jt 60 $jn - net"$'\n'"junk" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 2 ] && grep -q "refused: a command is one line" <<<"$out" && ! grep -q "REACHED\|CUT\|IF \|verdict" <<<"$out"')" "…and a command with a second line in it is refused and runs nothing (got $rc)"
  out=$(cd "$R" && git archive HEAD | CC_SUITES_RUNNER_PREP=0 SSH_ORIGINAL_COMMAND="job c $jt 60 $jn - net"$'\r' bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 2 ] && grep -q "refused: a command is one line" <<<"$out" && ! grep -q "REACHED\|CUT\|IF \|verdict" <<<"$out"')" "…and so is one with a carriage return in it (got $rc)"
  kill "$lpid" 2>/dev/null; wait "$lpid" 2>/dev/null
  # …NOR A SOCKET UNDER /run: a Unix socket of this selfcheck's own, planted in the first world-writable directory
  # under /run (the stand-in for a daemon's socket there), answers outside the cage and is not there inside it
  local rd rs rpid; rd=""; for rs in /run/lock /run/screen; do [ -d "$rs" ] && [ -w "$rs" ] && { rd=$rs; break; }; done
  if [ -n "$rd" ] && rd=$(mktemp -d "$rd/cc-suites-selfcheck.XXXXXX"); then
    rs="$rd/s.sock"; python3 -c 'import os, socket, sys
s = socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.listen(8)
while True: s.accept()[0].close()' "$rs" & rpid=$!
    for _ in $(seq 1 50); do [ -S "$rs" ] && break; sleep 0.1; done
    jn=$(printf '%s' "python3 -c 'import socket, sys
s = socket.socket(socket.AF_UNIX); s.settimeout(3)
try: s.connect(sys.argv[1]); print(\"REACHED\")
except OSError: print(\"CUT\")' $rs" | base64 -w0)
    p1=$(python3 -c 'import socket, sys; socket.socket(socket.AF_UNIX).connect(sys.argv[1]); print("up")' "$rs" 2>&1)
    out=$(cd "$R" && git archive HEAD | CC_SUITES_RUNNER_PREP=0 SSH_ORIGINAL_COMMAND="job c $jt 60 $jn -" bash "$SELF" runner 2>&1); rc=$?
    k "$(b '[ "$p1" = up ] && [ "$rc" = 0 ] && grep -qx "| CUT" <<<"$out" && ! grep -q "REACHED" <<<"$out"')" "…nor connect to a Unix socket planted under /run, which answers outside the cage (got $rc, outside: $p1)"
    kill "$rpid" 2>/dev/null; wait "$rpid" 2>/dev/null; rm -rf "$rd"
  else echo "  - no writable directory under /run here: the /run socket case is skipped"; fi
  # a bwrap that runs but cannot cut the network is no cage: unfit, and nothing runs
  mkdir -p "$D/nonet"; printf '#!/bin/sh\nfor a; do [ "$a" != --unshare-net ] || exit 1; done\nexec %s "$@"\n' "$(command -v bwrap)" > "$D/nonet/bwrap"; chmod +x "$D/nonet/bwrap"
  out=$(cd "$R" && git archive HEAD | PATH="$D/nonet:$PATH" CC_SUITES_JOB_NEEDS=git SSH_ORIGINAL_COMMAND="job c $jt 60 $jb -" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && grep -q "unfit (missing: bwrap(does-not-run))" <<<"$out" && ! grep -q "verdict\|home=" <<<"$out"')" "a runner whose bwrap cannot cut the network answers unfit to a job, 75, and runs nothing (got $rc)"
  # …and a machine whose bwrap does not run takes no job, whatever the needs are set to: nothing runs uncaged
  mkdir -p "$D/nobw"; printf '#!/bin/sh\nexit 1\n' > "$D/nobw/bwrap"; chmod +x "$D/nobw/bwrap"
  out=$(cd "$R" && git archive HEAD | PATH="$D/nobw:$PATH" CC_SUITES_JOB_NEEDS=git SSH_ORIGINAL_COMMAND="job c $jt 60 $jb -" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && grep -q "unfit (missing: bwrap(does-not-run))" <<<"$out" && ! grep -q "verdict\|home=" <<<"$out"')" "a runner whose bwrap does not run answers unfit to a job, 75, and runs nothing (got $rc)"
  out=$(cd "$R" && git archive HEAD | PATH="$D/nobw:$PATH" SSH_ORIGINAL_COMMAND="run core/tests/selftest.sh $tree all -" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && grep -q "unfit (missing: bwrap(does-not-run))" <<<"$out" && ! grep -q "suite ran" <<<"$out"')" "…and to a suite, though the needs this selfcheck sets leave bwrap out (got $rc)"
  pw AC Mains online 0
  out=$(bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" != 75 ] && grep -q '\''suite ran'\'' <<<"$out"')" "on battery (the Mains supply offline): spill still runs (got $rc)"
  out=$(bash "$SELF" status 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "answers: free [1-9][0-9]* cores=$(nproc) slots=[0-9]* maxload=[0-9.]* load=0.00 ac=0\$" <<<"$out"')" "…and status says the runner is free on battery, with its cores, maxload, load and ac=0"
  out=$(cd "$R" && git archive HEAD | CC_SUITES_RUNNER_PREP=0 SSH_ORIGINAL_COMMAND="run core/tests/selftest.sh $tree all -" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" != 75 ] && ! grep -q '\''busy'\'' <<<"$out"')" "…and a run that asks is accepted, not refused as busy"
  out=$(cd "$R" && git archive HEAD | CC_SUITES_RUNNER_PREP=0 SSH_ORIGINAL_COMMAND="job c $jt 60 $jb -" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "^lander-job: verdict exit=3" <<<"$out" && ! grep -q "busy" <<<"$out"')" "…and a lander job is accepted too: it runs and gives its verdict (got $rc)"
  pw AC Mains online 1; pw BAT0 Battery status Discharging
  k "$(b 'runner_on_battery && [ -z "$(runner_unfit)" ]')" "a battery discharging is on battery, whatever the Mains supply says, and still fit to run"
  pw BAT0 Battery status Charging
  k "$(b '[ -z "$(runner_unfit)" ] && ! runner_on_battery')" "on AC with the battery charging: fit to run, not on battery"
  rm -rf "$D/power"/*
  k "$(b '[ -z "$(runner_unfit)" ]')" "no power supply info at all (a WSL with none) counts as on AC"
  echo "99.00 99.00 99.00 1/1 1" > "$D/loadavg"
  out=$(bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && ! grep -q '\''suite ran'\'' <<<"$out" && grep -q "^load 99.00" <<<"$(runner_unfit)"')" "a 1-minute load above half the cores: busy, 75, nothing ran (got $rc)"
  # the runner's own maxload file replaces the n/2 default, the same way slots does
  echo 100 > "$D/runner/maxload"
  k "$(b '[ -z "$(runner_unfit)" ]')" "…and a maxload file above the current load answers fit, though it is above n/2"
  out=$(bash "$SELF" status 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "maxload=100 " <<<"$out"')" "…named in status as the bound in force"
  rm -f "$D/runner/maxload"
  k "$(b '[ -n "$(runner_unfit)" ]')" "…and with the file gone the n/2 default answers busy again"
  echo "0.00 0.00 0.00 1/1 1" > "$D/loadavg"
  # WALL-CLOCK BOUNDS. The runner stops a suite past its limit and gives no verdict; the box then runs it here
  touch "$R/HANG"; SECONDS=0
  out=$(CC_SUITES_RUNNER_TIMEOUT=2s bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 76 ] && grep -q '\''ran past 2s'\'' <<<"$out" && [ "$SECONDS" -lt 20 ]')" "a suite that hangs on the runner is stopped there: no verdict, 76, in ${SECONDS}s"
  rm -f "$R/HANG"
  # …and a runner that stays up while nothing comes back holds the box no longer than CC_SUITES_SPILL_TIMEOUT
  printf '#!/usr/bin/env bash\n[ "$1" = status ] && { echo "free 1"; exit 0; }\ncat >/dev/null; echo "suite ran, then hung"; exec sleep 120\n' > "$D/xport-hang"
  chmod +x "$D/xport-hang"; SECONDS=0
  out=$(CC_SUITES_SSH="$D/xport-hang" CC_SUITES_SPILL_TIMEOUT=2s bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 76 ] && grep -q '\''longer than 2s'\'' <<<"$out" && [ "$SECONDS" -lt 20 ]')" "a runner that never answers is given up on after the limit: 76, in ${SECONDS}s"
  # READINESS: a runner missing a tool the suite needs answers unfit and runs nothing
  out=$(CC_SUITES_RUNNER_NEEDS="bash no-such-tool-xyz" bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && ! grep -q '\''suite ran'\'' <<<"$out"')" "a runner missing a tool the suite needs: 75, and nothing ran (got $rc)"
  out=$(CC_SUITES_RUNNER_NEEDS="bash no-such-tool-xyz" bash "$SELF" status 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && grep -q '\''unfit (missing: no-such-tool-xyz)'\'' <<<"$out"')" "…and status names what it lacks"
  out=$(cd "$R" && git archive HEAD | CC_SUITES_RUNNER_NEEDS="no-such-tool-xyz" SSH_ORIGINAL_COMMAND="run core/tests/selftest.sh $tree all -" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && grep -q unfit <<<"$out" && ! grep -q '\''suite ran'\'' <<<"$out"')" "…and a run that asks anyway is refused before it starts"
  k "$(b '[ -z "$(runner_missing)" ] && grep -q "bwrap" <<<"$RUNNER_NEEDS"')" "a runner with every need is ready, and bwrap is among the needs"
  # FLOOR: a laptop pass is final, so a python3 older than the box's answers unfit, and one at or above it does not
  echo "python3 99.0" > "$D/floor"
  out=$(bash "$SELF" status 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && grep -q "unfit (missing: python3([0-9.]*<99.0))" <<<"$out"')" "a runner whose python3 is older than the floor answers unfit and names it (got $rc)"
  out=$(cd "$R" && git archive HEAD | SSH_ORIGINAL_COMMAND="job c $(printf %040d 0) 60 $(printf true | base64) -" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && grep -q "unfit (missing: python3(" <<<"$out"')" "…and so does the lander's job, though its own needs leave python3 out (got $rc)"
  printf 'python3 3.0\nsh 99\n' > "$D/floor"
  k "$(b '[ -z "$(runner_older)" ]')" "…a python3 at or above the floor is fit, and a floor line naming any other tool is not read"
  rm -f "$D/floor"
  k "$(b '[ "$(slots_for 22)" = 3 ] && [ "$(slots_for 6)" = 1 ] && [ "$(slots_for 16)" = 2 ] && [ "$(slots_for 128)" = 8 ]')" "slots by default: about one per 8 cores, so suites take about half (22 cores → 3, 6 → 1, capped at 8)"
  echo 5 > "$D/runner/slots"; k "$(b '[ "$(runner_slots)" = 5 ]')" "…and the runner's own slots file sets it"
  echo 0 > "$D/runner/slots"; k "$(b '[ "$(runner_slots)" = "$(slots_for "$(nproc)")" ]')" "…and a slots file out of 1..32 is the default"
  rm -f "$D/runner/slots"
  k "$(b '[ "$(limit 90x 90m)" = 90m ] && [ "$(limit 0 90m)" = 90m ] && [ "$(limit 5s 90m)" = 5s ]')" "a limit that is not timeout's form, or zero, is the default"
  touch "$R/FAIL"
  out=$(bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 76 ] && grep -q '\''running it here'\'' <<<"$out" && [ "$(find "$D/green" -name "selftest.sh-*.json" ! -name "*${tree:0:12}*" | wc -l)" = 0 ]')" "a red there fails nothing on its own: 76, so it runs here and is not offered again (got $rc), and files no record"
  rm -f "$R/FAIL"
  # FINISH HERE: a red there only in a tool's own selfcheck runs that selfcheck here, and nothing else here
  touch "$R/TOOLRED"; rm -rf "$D/green"; rm -f "$D/fake.calls" "$D/fake-red"; tree=$(cd "$R" && . core/tests/green.sh && green_tree "$R")
  out=$(bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && [ "$(cat "$D/fake.calls")" = selfcheck ] && grep -q "finished here: cc-fake selfcheck: 1 passed, 0 failed" <<<"$out" && ls "$D/green/selftest.sh-${tree:0:12}.json" >/dev/null 2>&1')" "a red there only in a tool's own selfcheck: that selfcheck alone runs here, and its pass is the pass, filed for the tree (got $rc)"
  k "$(b 'grep -q "red (exit 1) after [0-9]*s, only in the own selfcheck of: cc-fake" <<<"$out"')" "…and the line says how long the runner had it, and which tool is finished here"
  k "$(b '[ "$(cat "$D/fake.env")" = "log_only=1 tier=autonomous" ]')" "…and the tool runs with the suite's own flags: CC_NOTIFY_LOG_ONLY=1, so a re-run never pushes to the owner"
  rm -rf "$D/green"; rm -f "$D/fake.calls"; touch "$D/fake-red"
  out=$(bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 76 ] && [ "$(cat "$D/fake.calls")" = "$(printf "selfcheck\nselfcheck")" ] && [ ! -d "$D/green" ] && grep -q "red here too" <<<"$out"')" "…and a tool red here too (twice, as chk judges it) is 76 and no record: the whole suite runs here (got $rc)"
  rm -f "$R/TOOLRED" "$D/fake-red"
  touch "$R/TOOLREDI"; rm -rf "$D/green"; rm -f "$D/fake.calls"
  out=$(bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 76 ] && [ ! -e "$D/fake.calls" ] && [ ! -d "$D/green" ] && grep -q "cc-inline.s selfcheck is not a chk case" <<<"$out"')" "a red only in a tool selfcheck the suite runs inline, not through chk: 76, the tool not run here, no record (got $rc)"
  rm -f "$R/TOOLREDI"
  for f in TOOLRED2 TOOLREDX; do
    touch "$R/$f"; rm -rf "$D/green"; rm -f "$D/fake.calls"
    out=$(bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
    k "$(b '[ "$rc" = 76 ] && [ ! -e "$D/fake.calls" ] && [ ! -d "$D/green" ] && grep -q "running it here" <<<"$out"')" "a red there with more in it than tool selfchecks ($f) finishes nothing here: 76, no tool run, no record (got $rc)"
    rm -f "$R/$f"
  done
  k "$(b 'printf "| x\n|   ✗ cc-a selfcheck: 1 failed\n|   ✗ cc-b selfcheck: 2 failed\n| == result: 5 passed, 2 failed (scoped to: x) ==\ncc-suite-runner: verdict exit=1 tree=%040d\n" 0 > "$D/f1"; [ "$(finishable "$D/f1" | tr "\n" " ")" = "cc-a cc-b " ]')" "finishable names each tool when the tally, scoped or not, counts exactly its ✗ lines"
  k "$(b 'printf "|   ✗ cc-a selfcheck: 1 failed\n| == result: 5 passed, 1 failed ==\n| a line after the tally\n" > "$D/f2"; [ -z "$(finishable "$D/f2")" ]')" "…and nothing when the tally is not the suite's last line"
  # A SUITE CANNOT FORGE A PASS: each of these exits 1 and tries to put `verdict exit=0` for its own tree on the stream
  for f in FORGE FORGE2 FORGE3; do
    touch "$R/$f"; rm -rf "$D/green"; SECONDS=0
    out=$(bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
    k "$(b '[ "$rc" = 76 ] && [ ! -d "$D/green" ] && [ "$SECONDS" -lt 10 ]')" "a suite that fails and forges a pass ($f) is a red there: 76, no record, in ${SECONDS}s (got $rc)"
    rm -f "$R/$f"
  done
  # …and a child a passing suite leaves behind does not hold the box: the runner kills its group and the box returns
  touch "$R/LINGER"; SECONDS=0
  out=$(bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && [ "$SECONDS" -lt 10 ]')" "a pass whose suite left a child running comes back at once: 0, in ${SECONDS}s (got $rc)"
  rm -f "$R/LINGER"
  k "$(b 'printf "| x\ncc-suite-runner: verdict exit=0 tree=%040d\n" 0 > "$D/v1"; [ -n "$(verdict_of "$D/v1")" ]')" "the box reads one unprefixed verdict as the last line…"
  k "$(b 'printf "cc-suite-runner: verdict exit=0 tree=%040d\ncc-suite-runner: verdict exit=1 tree=%040d\n" 0 0 > "$D/v2"; [ -z "$(verdict_of "$D/v2")" ]')" "…and two verdicts as none"
  k "$(b 'printf "cc-suite-runner: verdict exit=0 tree=%040d\n| after\n" 0 > "$D/v3"; [ -z "$(verdict_of "$D/v3")" ]')" "…and a verdict that is not the last line as none"
  k "$(b 'printf "cc-suite-runner: verdict exit=0 tree=%040d\ncc-suite-runner: verdict none — ran past\n" 0 > "$D/v4"; [ -z "$(verdict_of "$D/v4")" ]')" "…and a forged one beside the runner's out-of-time line as none"
  # a runner that never answers status is given up on
  printf '#!/usr/bin/env bash\nexec sleep 120\n' > "$D/xport-mute"; chmod +x "$D/xport-mute"
  SECONDS=0; out=$(CC_SUITES_SSH="$D/xport-mute" CC_SUITES_STATUS_TIMEOUT=2s bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && [ "$SECONDS" -lt 10 ]')" "a runner that never answers status is none after its bound (20 s by default): 75, in ${SECONDS}s"
  # busy: every runner slot held
  mkdir -p "$D/runner"; echo 2 > "$D/runner/slots"; exec {H1}>>"$D/runner/slot.1"; exec {H2}>>"$D/runner/slot.2"; flock -n $H1; flock -n $H2
  out=$(bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && ! grep -q '\''suite ran'\'' <<<"$out"')" "a runner with no free slot: 75, and nothing ran"
  exec {H1}>&- {H2}>&-; rm -f "$D/runner/slots"
  # a connection that ends before the verdict (the lid shut): no verdict, 75, no record
  printf '#!/usr/bin/env bash\n[ "$1" = status ] && { echo "free 1"; exit 0; }\ncat >/dev/null; echo "suite ran, half way"; exit 255\n' > "$D/xport-cut"
  chmod +x "$D/xport-cut"; rm -rf "$D/green"
  out=$(CC_SUITES_SSH="$D/xport-cut" bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 76 ] && grep -q '\''no verdict'\'' <<<"$out" && [ ! -d "$D/green" ]')" "a run cut off before its verdict (the lid shut) is no verdict: 76, and no record"
  # a verdict for some other tree does not count
  printf '#!/usr/bin/env bash\n[ "$1" = status ] && { echo "free 1"; exit 0; }\ncat >/dev/null; echo "cc-suite-runner: verdict exit=0 tree=%040d"\n' 0 > "$D/xport-other"
  chmod +x "$D/xport-other"
  out=$(CC_SUITES_SSH="$D/xport-other" bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 76 ] && [ ! -d "$D/green" ]')" "a verdict naming another tree is not this run's: 76, and no record"
  # the runner refuses what it was not built for
  out=$(cd "$D" && SSH_ORIGINAL_COMMAND="run ../../etc/passwd $tree all -" bash "$SELF" runner 2>&1 </dev/null); rc=$?
  k "$(b '[ "$rc" = 2 ]')" "the runner refuses a suite outside its list (exit $rc)"
  out=$(cd "$D" && SSH_ORIGINAL_COMMAND="bash -i" bash "$SELF" runner 2>&1 </dev/null); rc=$?
  k "$(b '[ "$rc" = 2 ]')" "…and any command but status and run"
  out=$(cd "$R" && git archive HEAD | SSH_ORIGINAL_COMMAND="run core/tests/selftest.sh $(printf %040d 0) all -" bash "$SELF" runner 2>&1); rc=$?
  k "$(b 'grep -q '\''refused'\'' <<<"$out" && ! grep -q '\''suite ran'\'' <<<"$out"')" "…and a tar that is not the tree it was told, before running a line of it"
  # --- RENDER: a fake Blender that keeps RENDER_PY's contract by hand (the device line, exit 3 with no GPU while
  # $FB/nogpu exists, or the code it holds; a GPU named by $FB/gpuname with its niceness; a frame file per frame into
  # CC_RENDER_OUT saying the device and its niceness), and runs the
  # scene script with bash, so a scene of a case's own can try things inside the cage. It lives under HOME, which
  # the cage shows read-only (its /tmp is fresh). Each case has its own scene directory and OUT.
  local FB SC rt ro; FB=$(mktemp -d "$HOME/.cc-suites-blender.XXXXXX"); SC="$D/scenes"
  cat > "$FB/blender" <<'EOF'
#!/usr/bin/env bash
sc=""; while [ "$#" -gt 0 ]; do [ "$1" = --python ] && sc=$2; shift; done
d=${CC_RENDER_DEVICE:-CPU}; [ "$d" = GPU ] && d="OPTIX Fake GPU"; fb=$(dirname "$0")
[ "$d" = CPU ] || [ ! -e "$fb/gpuname" ] || d="OPTIX $(cat "$fb/gpuname") nice=$(nice)"
if [ "$CC_RENDER_DEVICE" = GPU ] && [ -e "$fb/nogpu" ]; then echo "cc-render: device none, Blender 9.9"; c=$(cat "$fb/nogpu"); exit "${c:-3}"; fi
echo "cc-render: device $d, Blender 9.9"
[ "${CC_RENDER_PROBE:-}" = 1 ] && exit 0
echo "cc-render: ld=${LD_LIBRARY_PATH:-}"
[ -z "$sc" ] || . "$sc"
for f in $(seq "${CC_RENDER_START:-1}" "${CC_RENDER_END:-2}"); do
  printf 'frame %s %s nice=%s\n' "$f" "$CC_RENDER_DEVICE" "$(nice)" > "$CC_RENDER_OUT/frame_$(printf %04d "$f").png"; done
EOF
  chmod +x "$FB/blender"; export CC_SUITES_BLENDER="$FB/blender" CC_SUITES_WSL_LIB="$D/no-wsl-lib"
  printf '#!/usr/bin/env bash\necho "$*" >> "%s/render.calls"\nexec env HOME="%s/rhome" SSH_ORIGINAL_COMMAND="$*" CC_SUITES_RUNNER_DIR="%s/runner" bash "%s" runner\n' "$D" "$D" "$D" "$SELF" > "$D/xport-render"
  chmod +x "$D/xport-render"; echo "0.00 0.00 0.00 1/1 1" > "$D/loadavg"; rm -f "$D/runner/slots" "$D/runner/maxload"
  sc(){ mkdir -p "$SC/$1" && printf '%s\n' "${2:-true}" > "$SC/$1/scene.py"; }   # a scene directory of a case's own
  sc gpu; echo "a neighbour" > "$SC/gpu/texture.txt"
  out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/gpu/scene.py" "$D/o-gpu" 3 4 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "rendered on the laptop (OPTIX Fake GPU, Blender 9.9)" <<<"$out" && [ "$(ls "$D/o-gpu" | tr "\n" " ")" = "frame_0003.png frame_0004.png " ] && grep -qx "frame 4 GPU nice=19" "$D/o-gpu/frame_0004.png"')" "render: a free laptop renders the frames asked on its GPU at nice 19, and they come back as files (got $rc)"
  k "$(b 'grep -q "^cc-render: device OPTIX Fake GPU" "$D/o-gpu.log" && [ -z "$(ls -d "$D/runner"/render.* 2>/dev/null)" ]')" "…with Blender's log beside OUT, and nothing left in the runner's directory"
  k "$(b 'grep -q "^cc-render: device OPTIX Fake GPU" "$D/o-gpu.log" && grep -qx "cc-render: ld=" "$D/o-gpu.log"')" "…and with no WSL library directory, no LD_LIBRARY_PATH"
  mkdir -p "$D/wsl-lib"; sc wsl
  out=$(CC_SUITES_WSL_LIB="$D/wsl-lib" CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/wsl/scene.py" "$D/o-wsl" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "rendered on the laptop" <<<"$out" && grep -qx "cc-render: ld=$D/wsl-lib" "$D/o-wsl.log"')" "…on WSL, Blender gets its NVIDIA library directory on LD_LIBRARY_PATH, so OptiX can load by name (got $rc)"
  touch "$FB/nogpu"; sc nogpu
  out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/nogpu/scene.py" "$D/o-nogpu" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "unfit (Blender sees no GPU)" <<<"$out" && grep -q "rendered on this box.s CPU (nice 19)" <<<"$out" && grep -qx "frame 2 CPU nice=19" "$D/o-nogpu/frame_0002.png"')" "…a laptop whose Blender sees no GPU is unfit, and the box renders it on its CPU at nice 19 (got $rc)"
  k "$(b 'grep -qx "cc-render: device none, Blender 9.9" "$D/o-nogpu.laptop.log" && grep -q "o-nogpu.laptop.log" <<<"$out" && grep -qx "frame 2 CPU nice=19" "$D/o-nogpu/frame_0002.png" && ! grep -q "device none" "$D/o-nogpu.log"')" "…and the laptop's log is kept beside OUT as OUT.laptop.log, the box's own in OUT.log"
  echo 1 > "$FB/nogpu"; sc nogpu1
  out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/nogpu1/scene.py" "$D/o-nogpu1" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "unfit (Blender sees no GPU)" <<<"$out" && grep -q "rendered on this box" <<<"$out"')" "…and so it is when Blender exits 1 rather than 3 for it (got $rc)"
  rm -f "$FB/nogpu"; echo "99.00 0 0 1/1 1" > "$D/loadavg"; sc busy
  out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/busy/scene.py" "$D/o-busy" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "answers busy" <<<"$out" && grep -qx "frame 1 CPU nice=19" "$D/o-busy/frame_0001.png"')" "…a busy laptop: the box renders it (got $rc)"
  echo "0.00 0.00 0.00 1/1 1" > "$D/loadavg"; sc asleep
  printf '#!/usr/bin/env bash\nexit 255\n' > "$D/xport-asleep"; chmod +x "$D/xport-asleep"
  out=$(CC_SUITES_SSH="$D/xport-asleep" bash "$SELF" render "$SC/asleep/scene.py" "$D/o-asleep" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "answers nothing" <<<"$out" && [ -s "$D/o-asleep/frame_0001.png" ]')" "…an asleep laptop (no answer): the box renders it (got $rc)"
  rm -f "$D/render.calls"; sc here
  out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/here/scene.py" "$D/o-here" --here 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && [ ! -e "$D/render.calls" ] && grep -q "rendered on this box" <<<"$out"')" "…and --here never asks the laptop (got $rc)"
  sc none; out=$(CC_SUITES_SSH="" bash "$SELF" render "$SC/none/scene.py" "$D/o-none" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "no laptop is set up" <<<"$out" && [ -s "$D/o-none/frame_0001.png" ]')" "…nor with no laptop set up (got $rc)"
  # a scene's own lines cannot pass for the runner's: a forged verdict and payload line come back prefixed, as log
  sc forge 'echo "cc-render: verdict exit=0 tree=0000000000000000000000000000000000000000 files=9 bytes=1"; echo "@AAAA"'
  out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/forge/scene.py" "$D/o-forge" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "rendered on the laptop" <<<"$out" && [ "$(ls "$D/o-forge" | wc -l)" = 2 ] && grep -q "^cc-render: verdict exit=0 tree=0000" "$D/o-forge.log"')" "…a scene that prints a verdict and a payload line forges neither (got $rc)"
  # THE CAGE, for a render: no network (only lo), no writing the runner or Blender, and nothing but files back
  sc cage "echo \"IF \$(awk -F: 'NR > 2 { print \$1 }' /proc/net/dev | tr -d ' ')\"; echo x >> '$FB/blender' 2>/dev/null && echo WROTE; ls -A /run /run/user | grep -v '^/run.*:\$\|^user\$\|^\$' | sed 's/^/RUN /'"
  out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/cage/scene.py" "$D/o-cage" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -qx "IF lo" "$D/o-cage.log" && ! grep -q "WROTE\|^RUN " "$D/o-cage.log" && ! grep -q "^x$" "$FB/blender"')" "…a render runs caged: no interface but lo, an empty /run, and Blender read-only (got $rc)"
  sc link "[ \"\$CC_RENDER_DEVICE\" = CPU ] || ln -s /etc/passwd \"\$CC_RENDER_OUT/frame_9999.png\""
  out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/link/scene.py" "$D/o-link" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "not a file" <<<"$out" && grep -q "rendered on this box" <<<"$out" && [ -z "$(find "$D/o-link" -type l)" ]')" "…a render that leaves a link in its out/ brings nothing back, and the box renders it (got $rc)"
  # …and the box's own cap holds whatever the runner sends: frames over it here are refused and rendered here
  sc bigbox; out=$(CC_SUITES_RENDER_MAX_BYTES=10 CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/bigbox/scene.py" "$D/o-bigbox" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "brought back no frames" <<<"$out" && grep -q "rendered on this box" <<<"$out" && grep -qx "frame 1 CPU nice=19" "$D/o-bigbox/frame_0001.png"')" "…a stream whose frames are over the box's own cap is refused here, and the box renders it (got $rc)"
  sc big; printf '#!/usr/bin/env bash\nexec env CC_SUITES_RENDER_MAX_BYTES=10 "%s" "$@"\n' "$D/xport-render" > "$D/xport-small"; chmod +x "$D/xport-small"
  out=$(CC_SUITES_SSH="$D/xport-small" bash "$SELF" render "$SC/big/scene.py" "$D/o-big" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "over 10" <<<"$out" && grep -q "rendered on this box" <<<"$out"')" "…frames over the size cap stay there, and the box renders them (got $rc)"
  # the box takes back only regular files, for the tree it shipped: a runner that sends a link, or names another tree
  sc evil; mkdir -p "$D/evil"; ln -s /etc/passwd "$D/evil/frame_0001.png"; tar -C "$D/evil" -cf "$D/evil.tar" .
  printf '#!/usr/bin/env bash\n[ "$1" = status ] && { echo "free 1"; exit 0; }\ncat >/dev/null; base64 -w76 "%s" | sed "s/^/@/"; echo "cc-render: verdict exit=0 tree=$2 files=1 bytes=1"\n' "$D/evil.tar" > "$D/xport-evil"; chmod +x "$D/xport-evil"
  out=$(CC_SUITES_SSH="$D/xport-evil" bash "$SELF" render "$SC/evil/scene.py" "$D/o-evil" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "rendered on this box" <<<"$out" && [ -z "$(find "$D/o-evil" -type l)" ] && grep -qx "frame 1 CPU nice=19" "$D/o-evil/frame_0001.png"')" "…the box refuses a payload holding a link and renders it itself (got $rc)"
  sed -i 's/tree=\$2/tree=%040d/; s/%040d/0000000000000000000000000000000000000000/' "$D/xport-evil"; sc other
  rm -rf "$D/evil"; mkdir -p "$D/evil"; echo x > "$D/evil/frame_0001.png"; tar -C "$D/evil" -cf "$D/evil.tar" .
  out=$(CC_SUITES_SSH="$D/xport-evil" bash "$SELF" render "$SC/other/scene.py" "$D/o-other" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "rendered on this box" <<<"$out" && grep -qx "frame 1 CPU nice=19" "$D/o-other/frame_0001.png"')" "…and frames for another tree (got $rc)"
  # the box counts the files' own size, whatever the verdict says: a 20-byte file over a 10-byte cap, and a sparse
  # file whose few KB of archive are 50 MB once written, are refused before a byte is extracted
  sc logical; rm -rf "$D/evil"; mkdir -p "$D/evil"; printf '%020d' 0 > "$D/evil/frame_0001.png"; tar -C "$D/evil" -cf "$D/evil.tar" .
  sed -i 's/tree=0\{40\} files=1 bytes=1/tree=$2 files=1 bytes=20/' "$D/xport-evil"
  out=$(CC_SUITES_RENDER_MAX_BYTES=10 CC_SUITES_SSH="$D/xport-evil" bash "$SELF" render "$SC/logical/scene.py" "$D/o-logical" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "brought back no frames" <<<"$out" && grep -qx "frame 1 CPU nice=19" "$D/o-logical/frame_0001.png"')" "…a payload whose files are over the box's cap, though its verdict owns to it (got $rc)"
  sc sparse; rm -rf "$D/evil"; mkdir -p "$D/evil"; truncate -s 50M "$D/evil/frame_0001.png"; tar -S -C "$D/evil" -cf "$D/evil.tar" .
  out=$(CC_SUITES_RENDER_MAX_BYTES=1048576 CC_SUITES_SSH="$D/xport-evil" bash "$SELF" render "$SC/sparse/scene.py" "$D/o-sparse" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && [ "$(stat -c %s "$D/evil.tar")" -lt 1048576 ] && grep -q "brought back no frames" <<<"$out" && grep -qx "frame 1 CPU nice=19" "$D/o-sparse/frame_0001.png"')" "…and a sparse file whose small archive is over the cap once written (got $rc)"
  rm -rf "$D/evil" "$D/evil.tar"
  # THE STREAM BOUND: render_wire is the `@` lines' exact size, and a render at the very cap, with a log of long
  # lines, comes back whole under render_stream_max (log lines cut to RENDER_LOG_WIDTH)
  local ws=""; for ro in 0 1 2 3 56 57 58 59 1000 10240 99999; do
    [ "$(head -c "$ro" /dev/zero | base64 -w 76 | sed 's/^/@/' | wc -c)" = "$(render_wire "$ro")" ] || ws="$ws $ro"; done
  k "$(b '[ -z "$ws" ]')" "render_wire is the size of a payload's \`@\` lines, byte for byte (off at:${ws:- none})"
  sc atcap "for i in \$(seq 70); do head -c 1000 /dev/zero | tr '\\0' L; echo; done; head -c 199960 /dev/zero > \"\$CC_RENDER_OUT/big.bin\""
  rt=$(cd "$SC/atcap" && tar -cf - . | { mkdir -p "$D/rt-atcap" && tar -x -C "$D/rt-atcap" && cd "$D/rt-atcap" && git init -q && git add -A && git write-tree; })
  (cd "$SC/atcap" && tar -cf - . | CC_SUITES_RENDER_MAX_BYTES=200000 CC_SUITES_RENDER_TAR_SLACK=20480 SSH_ORIGINAL_COMMAND="render $rt 60 - - scene.py" bash "$SELF" runner >"$D/atcap.stream" 2>&1)
  ro=$(RENDER_MAX_BYTES=200000; RENDER_TAR_SLACK=20480; render_stream_max)
  k "$(b 'tail -1 "$D/atcap.stream" | grep -q "^cc-render: verdict exit=0 .* bytes=200000$" && [ "$(wc -c <"$D/atcap.stream")" -le "$ro" ] && ! grep -a "^| " "$D/atcap.stream" | awk "length > $RENDER_LOG_WIDTH + 2 { f = 1 } END { exit !f }"')" "a render at the cap, with 70 log lines of 1000 bytes, is under its stream bound ($(wc -c <"$D/atcap.stream") <= $ro)"
  out=$(CC_SUITES_RENDER_MAX_BYTES=200000 CC_SUITES_RENDER_TAR_SLACK=20480 CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/atcap/scene.py" "$D/o-atcap" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "rendered on the laptop" <<<"$out" && [ "$(stat -c %s "$D/o-atcap/big.bin")" = 199960 ]')" "…and the box takes it whole (got $rc)"
  out=$(CC_SUITES_RENDER_MAX_BYTES=200000 CC_SUITES_RENDER_TAR_SLACK=1 CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/atcap/scene.py" "$D/o-tarcap" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "the frames.* tar is [0-9]* bytes, over 200001" <<<"$out" && grep -q "rendered on this box" <<<"$out"')" "…while frames whose tar is over render_tar_max stay there, and the box renders them (got $rc)"
  # THE SCENE'S DIRECTORY: measured before a byte of it is tarred, and never HOME, /tmp or one holding .ssh or .cc
  sc sshdir; mkdir -p "$SC/sshdir/sub/.ssh"; rm -f "$D/render.calls"
  out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/sshdir/scene.py" "$D/o-sshdir" 2>&1); rc=$?
  k "$(b '[ "$rc" = 2 ] && grep -q "directory of its own" <<<"$out" && [ ! -e "$D/render.calls" ]')" "render refuses a scene whose directory holds a .ssh, and asks the laptop nothing (got $rc)"
  sc ccdir; mkdir -p "$SC/ccdir/.cc"
  out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/ccdir/scene.py" "$D/o-ccdir" --here 2>&1); rc=$?
  k "$(b '[ "$rc" = 2 ] && grep -q "directory of its own" <<<"$out"')" "…or a .cc (got $rc)"
  sc homedir; out=$(HOME="$SC/homedir" CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/homedir/scene.py" "$D/o-homedir" 2>&1); rc=$?
  k "$(b '[ "$rc" = 2 ] && grep -q "directory of its own" <<<"$out" && [ ! -e "$D/render.calls" ]')" "…or one that is HOME (got $rc)"
  sc bigdir; head -c 1000 /dev/zero > "$SC/bigdir/texture.bin"
  out=$(CC_SUITES_RENDER_TREE_MAX=500 CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/bigdir/scene.py" "$D/o-bigdir" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "is [0-9]* bytes, over the 500 the laptop takes" <<<"$out" && ! grep -q "^render" "$D/render.calls" && grep -qx "frame 1 CPU nice=19" "$D/o-bigdir/frame_0001.png"')" "…and a directory du says is over RENDER_TREE_MAX is never tarred or sent: the box renders it (got $rc)"
  # WHAT THE LAPTOP SAYS ON STDERR is the reason (an older runner refuses render there), bounded and printable
  printf '#!/usr/bin/env bash
case $1 in status) echo "free 1";; gpustat) echo "cc-suite-runner: refused: gpustat" >&2; exit 2;; gpu) printf "cc-suite-runner: refused: gpu\\033[2J\\n" >&2; exit 2;; *) cat >/dev/null; head -c 9000 /dev/zero | tr "\\0" x >&2; printf "\\ncc-suite-runner: refused: render\\n" >&2; exit 2;; esac
' > "$D/xport-old"; chmod +x "$D/xport-old"
  sc oldrunner; out=$(CC_SUITES_SSH="$D/xport-old" bash "$SELF" render "$SC/oldrunner/scene.py" "$D/o-oldrunner" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "brought back no frames after [0-9]*s (cc-suite-runner: refused: render)" <<<"$out" && grep -qx "cc-suites: the laptop said: cc-suite-runner: refused: render" "$D/o-oldrunner.laptop.log" && grep -q "rendered on this box" <<<"$out"')" "a render the laptop refuses on stderr names the refusal as the reason, and keeps it in OUT.laptop.log (got $rc)"
  out=$(CC_SUITES_SSH="$D/xport-old" bash "$SELF" status 2>&1)
  k "$(b 'grep -qx "cc-suites: its Blender renders with: not asked (its runner is older than gpu; rerun laptop-setup)" <<<"$out" && ! grep -q $'"'"'\033'"'"' <<<"$out"')" "…and status reads a gpu refusal as a runner older than the question, never printing its control bytes"
  k "$(b 'grep -qx "cc-suites: runner .* answers: free 1" <<<"$out" && grep -qx "cc-suites: its GPU: not asked (its runner is older than gpustat; rerun laptop-setup)" <<<"$out"')" "…and a runner from before gpustat is still free, its GPU line saying it was not asked, not that it gave no answer"
  printf '#!/usr/bin/env bash
echo "ssh: connect to host x port 22: No route to host" >&2; exit 255
' > "$D/xport-gone"; chmod +x "$D/xport-gone"
  out=$(CC_SUITES_SSH="$D/xport-gone" bash "$SELF" status 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && grep -qx "cc-suites: runner .* does not answer (ssh: connect to host x port 22: No route to host)" <<<"$out"')" "…and a status nobody answers says what ssh said (got $rc)"
  sc gone; out=$(CC_SUITES_SSH="$D/xport-gone" bash "$SELF" render "$SC/gone/scene.py" "$D/o-gone" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "the laptop answers nothing (ssh: connect to host x port 22: No route to host)" <<<"$out"')" "…and so does a render (got $rc)"
  # the runner's refusals: nothing freer than its one form, and nothing of a tree it cannot prove; Blender never starts
  rt=$(cd "$SC/gpu" && tar -cf - . | { mkdir -p "$D/rt" && tar -x -C "$D/rt" && cd "$D/rt" && git init -q && git add -A && git write-tree; })
  for ro in "render $rt 60 - - ../scene.py" "render $rt 60 - - /etc/scene.py" "render $rt 60 5 3 scene.py" "render $rt 60 08 9 scene.py" \
            "render $rt 0 - - scene.py" "render $rt 90000 - - scene.py" "render $rt 60 - - scene.py x" "render $rt 60 - 3 scene.py" "render $rt 60 - - scene.sh"; do
    out=$(cd "$SC/gpu" && tar -cf - . 2>/dev/null | SSH_ORIGINAL_COMMAND="$ro" bash "$SELF" runner 2>&1); rc=$?   # it refuses unread: tar's EPIPE is expected
    k "$(b '[ "$rc" = 2 ] && grep -q "refused: render TREE CAP START END SCENE" <<<"$out" && ! grep -q "cc-render: device" <<<"$out"')" "the runner refuses '${ro#render $rt }' and runs nothing (got $rc)"
  done
  out=$(cd "$SC/gpu" && tar -cf - . | SSH_ORIGINAL_COMMAND="render $(printf %040d 0) 60 - - scene.py" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 1 ] && grep -q "is not 0000" <<<"$out" && ! grep -q "cc-render: device" <<<"$out"')" "…a tar that is not the tree it was told (got $rc)"
  out=$(cd "$SC/gpu" && tar -cf - . | SSH_ORIGINAL_COMMAND="render $rt 60 - - other.py" bash "$SELF" runner 2>&1); rc=$?
  k "$(b '[ "$rc" = 1 ] && grep -q "no scene other.py" <<<"$out" && ! grep -q "cc-render: device" <<<"$out"')" "…and a scene the tree does not hold (got $rc)"
  out=$(SSH_ORIGINAL_COMMAND="gpu" bash "$SELF" runner 2>&1 </dev/null); rc=$?
  k "$(b '[ "$rc" = 0 ] && [ "$out" = "gpu OPTIX Fake GPU, Blender 9.9" ]')" "gpu names what Blender renders with (got: $out)"
  touch "$FB/nogpu"; out=$(SSH_ORIGINAL_COMMAND="gpu" bash "$SELF" runner 2>&1 </dev/null); rm -f "$FB/nogpu"
  k "$(b '[ "$out" = "gpu none, Blender 9.9" ]')" "…and none when it sees no GPU (got: $out)"
  printf 'G' > "$FB/gpuname"; out=$(SSH_ORIGINAL_COMMAND="gpu" bash "$SELF" runner 2>&1 </dev/null)
  k "$(b '[ "$out" = "gpu OPTIX G nice=19, Blender 9.9" ]')" "…asked at nice 19, like a render (got: $out)"
  echo "99.00 0 0 1/1 1" > "$D/loadavg"; touch "$FB/nogpu"
  out=$(SSH_ORIGINAL_COMMAND="gpu" bash "$SELF" runner 2>&1 </dev/null); echo "0.00 0.00 0.00 1/1 1" > "$D/loadavg"; rm -f "$FB/nogpu"
  k "$(b '[[ $out == "gpu not asked (busy: load 99.00 on "* ]]')" "…and never while the machine is loaded: Blender does not start (got: $out)"
  printf 'E\033[31mX' > "$FB/gpuname"; sc escname
  out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" render "$SC/escname/scene.py" "$D/o-escname" 2>&1); rc=$?; rm -f "$FB/gpuname"
  k "$(b '[ "$rc" = 0 ] && grep -qF "rendered on the laptop (OPTIX E?[31mX nice=19, Blender 9.9)" <<<"$out" && ! grep -q $'"'"'\033'"'"' <<<"$out"')" "a render's success line prints the laptop's device name printable (got $rc)"
  out=$(SSH_ORIGINAL_COMMAND="gpu now" bash "$SELF" runner 2>&1 </dev/null); rc=$?
  k "$(b '[ "$rc" = 2 ]')" "…and takes no argument (got $rc)"
  # GPUSTAT: nvidia-smi's word on the GPU, a fake that answers as nvidia-smi does (no devices while $FB/nodev exists)
  printf '#!/usr/bin/env bash\n[ -e "%s/nodev" ] && { echo "No devices were found"; exit 6; }\necho "NVIDIA Fake 4070, 12, 900, 8188, 41"\n' "$FB" > "$FB/nvidia-smi"
  chmod +x "$FB/nvidia-smi"; export CC_SUITES_NVIDIA_SMI="$FB/nvidia-smi"
  out=$(SSH_ORIGINAL_COMMAND="gpustat" bash "$SELF" runner 2>&1 </dev/null); rc=$?
  k "$(b '[ "$rc" = 0 ] && [ "$out" = "gpustat NVIDIA Fake 4070, 12% busy, 900/8188 MiB, 41 C" ]')" "gpustat gives the GPU's name, use, memory and temperature (got: $out)"
  touch "$FB/nodev"; out=$(SSH_ORIGINAL_COMMAND="gpustat" bash "$SELF" runner 2>&1 </dev/null); rm -f "$FB/nodev"
  k "$(b '[ "$out" = "gpustat none (nvidia-smi: No devices were found)" ]')" "…none, with nvidia-smi's reason, when it finds no GPU (got: $out)"
  out=$(CC_SUITES_NVIDIA_SMI="$D/no-such-smi" SSH_ORIGINAL_COMMAND="gpustat" bash "$SELF" runner 2>&1 </dev/null); rc=$?
  k "$(b '[ "$rc" = 0 ] && [ "$out" = "gpustat none (no nvidia-smi)" ]')" "…none when the laptop has no nvidia-smi (got: $out)"
  out=$(SSH_ORIGINAL_COMMAND="gpustat now" bash "$SELF" runner 2>&1 </dev/null); rc=$?
  k "$(b '[ "$rc" = 2 ] && grep -q "refused: gpustat takes nothing" <<<"$out" && ! grep -q "^gpustat " <<<"$out"')" "…and takes no argument: refused, nvidia-smi never asked (got $rc)"
  rm -f "$D/render.calls"; out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" status 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -qx "cc-suites: its Blender renders with: OPTIX Fake GPU, Blender 9.9" <<<"$out" && grep -qx gpu "$D/render.calls"')" "status says the GPU the runner's Blender renders with, asking it gpu (got $rc)"
  k "$(b '[ "$(sed -n 2p <<<"$out")" = "cc-suites: its GPU: NVIDIA Fake 4070, 12% busy, 900/8188 MiB, 41 C" ] && grep -qx gpustat "$D/render.calls"')" "…and names the GPU with its stats, under the runner's answer"
  rm -f "$D/render.calls"; out=$(CC_SUITES_SSH="$D/xport-render" bash "$SELF" status --quick 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "answers: free" <<<"$out" && grep -qx "cc-suites: its GPU: NVIDIA Fake 4070, 12% busy, 900/8188 MiB, 41 C" <<<"$out" && grep -qx gpustat "$D/render.calls"')" "status --quick still prints the GPU's stats (got $rc)"
  k "$(b '[ "$(wc -l <<<"$out")" = 2 ] && ! grep -q "Blender" <<<"$out" && ! grep -qx gpu "$D/render.calls"')" "…but never asks gpu, so Blender is not started there"
  out=$(CC_SUITES_NVIDIA_SMI="$D/no-such-smi" CC_SUITES_SSH="$D/xport-render" bash "$SELF" status --quick 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -qx "cc-suites: its GPU: none (no nvidia-smi)" <<<"$out"')" "…and a laptop with no nvidia-smi says so, still free (got $rc)"
  # NO ANSWER IS NOT A GPU FAULT (2026-10-03): a refusal says the runner predates the question, silence only that it
  # was not answered, and both say a 1-frame render is the test, so nobody reads either as a broken GPU
  printf '#!/usr/bin/env bash\n[ "$1" = gpustat ] && { echo "cc-suite-runner: refused: gpustat" >&2; exit 2; }\nexec "%s" "$@"\n' "$D/xport-render" > "$D/xport-pregpustat"; chmod +x "$D/xport-pregpustat"
  out=$(CC_SUITES_SSH="$D/xport-pregpustat" bash "$SELF" status 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -qx "cc-suites: its GPU: not asked (its runner is older than gpustat; rerun laptop-setup)" <<<"$out" && grep -qx "cc-suites: its Blender renders with: OPTIX Fake GPU, Blender 9.9" <<<"$out" && ! grep -q "no answer" <<<"$out"')" "…a runner from before gpustat whose Blender sees the GPU: its GPU was not asked, beside the device it renders with (got $rc: $out)"
  printf '#!/usr/bin/env bash\ncase $1 in gpustat) exit 255;; gpu) printf "ssh: lost\\033[2J\\n" >&2; exit 255;; esac\nexec "%s" "$@"\n' "$D/xport-render" > "$D/xport-silent"; chmod +x "$D/xport-silent"
  out=$(CC_SUITES_SSH="$D/xport-silent" bash "$SELF" status 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -qx "cc-suites: its GPU: no answer to gpustat (not a GPU fault on its own; a 1-frame render tells)" <<<"$out" && grep -qx "cc-suites: its Blender renders with: no answer to gpu (ssh: lost?\[2J; not a GPU fault on its own; a 1-frame render tells)" <<<"$out" && ! grep -q "not asked" <<<"$out"')" "…a runner silent on both says no answer, names what ssh said (printable), and that a render is the test (got $rc: $out)"
  printf '#!/usr/bin/env bash\ncase $1 in gpustat|gpu) echo "cc-suite-runner: refused: $1" >&2; exit 2;; esac\nexec "%s" "$@"\n' "$D/xport-render" > "$D/xport-pregpu"; chmod +x "$D/xport-pregpu"
  out=$(CC_SUITES_SSH="$D/xport-pregpu" bash "$SELF" status 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -qx "cc-suites: its Blender renders with: not asked (its runner is older than gpu; rerun laptop-setup)" <<<"$out" && grep -q "its GPU: not asked" <<<"$out"')" "…and a runner from before gpu says that line was not asked either (got $rc: $out)"
  # a runner whose nvidia-smi is slow: gpustat gets two thirds of the status bound, so the answer still arrives in
  # time and the GPU line says its stats are unavailable (exec sleep, so the pipe closes when timeout kills it)
  printf '#!/usr/bin/env bash\n[ "$1" = gpustat ] && exec sleep 30\nexec "%s" "$@"\n' "$D/xport-render" > "$D/xport-slowgpu"
  chmod +x "$D/xport-slowgpu"
  local ms; ms=$(date +%s%N); out=$(CC_SUITES_SSH="$D/xport-slowgpu" CC_SUITES_STATUS_TIMEOUT=3s bash "$SELF" status --quick 2>&1); rc=$?
  ms=$(( ($(date +%s%N) - ms) / 1000000 ))
  k "$(b '[ "$rc" = 0 ] && [ "$ms" -lt 3000 ] && grep -q "answers: free" <<<"$out" && grep -qx "cc-suites: its GPU: stats unavailable (gpustat gave nothing in 2s)" <<<"$out"')" "…and a runner whose GPU stats are slow still answers free inside the bound, its stats unavailable (got $rc in ${ms}ms)"
  k "$(b '[ "$(twothirds 08s)" = 5s ] && [ "$(twothirds 09m)" = 360s ] && [ "$(twothirds 09)" = 6s ] && [ "$(twothirds x)" = 1s ]')" "…a leading zero (08, 09) is a decimal number, not octal, and junk is 1s"
  k "$(b '[ "$(twothirds 6s)" = 4s ] && [ "$(twothirds 20s)" = 13s ] && [ "$(twothirds 1m)" = 40s ] && [ "$(twothirds 1s)" = 1s ] && [ "$(twothirds 30)" = 20s ]')" "…the stats get two thirds of the bound, in whole seconds and at least 1"
  k "$(b '[ "$(twothirds 08s)" = 5s ] && [ "$(twothirds 090)" = 60s ] && [ "$(twothirds 09m)" = 360s ] && [ "$(limit 00s 20s)" = 20s ] && [ "$(limit 09s 20s)" = 09s ]')" "…a bound with a leading zero is read in base 10, not octal, and 00s is no bound"
  k "$(b '[ "$(t bash "$SELF" status --slow)" = 2 ] && [ "$(t bash "$SELF" status --quick x)" = 2 ]')" "status refuses any argument but --quick"
  unset CC_SUITES_NVIDIA_SMI; rm -f "$FB/nvidia-smi"
  # with two runners, render goes to the last (the laptop, the one with a GPU) and never asks the first
  mkdir -p "$D/sd"; printf 'ccsuite@peer\nccsuite@laptop\n' > "$D/sd/remote"; : > "$D/render2.calls"
  printf '#!/usr/bin/env bash\necho "$CC_SUITES_DEST $1" >> "%s/render2.calls"\nexec "%s/xport-render" "$@"\n' "$D" "$D" > "$D/xport-render2"
  chmod +x "$D/xport-render2"; sc tworun
  out=$(CC_SUITES_SSH="$D/xport-render2" bash "$SELF" render "$SC/tworun/scene.py" "$D/o-tworun" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "rendered on the laptop" <<<"$out" && grep -qx "ccsuite@laptop render" "$D/render2.calls" && ! grep -q "^ccsuite@peer" "$D/render2.calls"')" "render with two runners goes to the last, and the first is never asked (got $rc)"
  rm -f "${D:?}/sd/remote"
  mkdir -p "$D/o-full"; : > "$D/o-full/x"
  k "$(b '[ "$(t bash "$SELF" render "$SC/gpu/scene.py" "$D/o-full")" = 2 ] && [ "$(t bash "$SELF" render "$SC/gpu/scene.py" "$D/o-rev" 4 3)" = 2 ] && [ "$(t bash "$SELF" render "$SC/gpu/texture.txt" "$D/o-txt")" = 2 ]')" "render refuses an OUT that is not empty, a range backwards, and a scene that is not NAME.py"
  unset CC_SUITES_BLENDER CC_SUITES_WSL_LIB; rm -f "$FB/blender"; rmdir "$FB"
  # laptop-setup: the key, the remote, and a script that carries this very file and the key's public half
  local cmd re f="$D/sd/laptop-setup.ps1"
  mkdir -p "$D/sd" && echo stale > "$f"
  # cmd is read inside the single-quoted b '…' strings below, where shellcheck cannot see it
  # shellcheck disable=SC2034
  cmd=$(CC_SUITES_BOX=my-box bash "$SELF" laptop-setup my-node 2>/dev/null); rc=$?
  k "$(b '[ "$rc" = 0 ] && [ "$(cat "$D/sd/remote")" = ccsuite@my-node ] && [ -s "$D/sd/id_ed25519" ]')" "laptop-setup makes the key and points the remote at ccsuite@my-node"
  k "$(b '[ "$(stat -c %a "$f")" = 600 ] && ! grep -qx stale "$f" && grep -q "^# SECRET" "$f"')" "…writes a fresh script over the last one's, to a file only this user can read (mode 600)"
  # A failed fetch must run nothing. No PowerShell here, so the command's shape is what is checked: the copy's name
  # is made fresh on the laptop (no leftover of an interrupted setup can be the file run), the one `powershell` sits
  # in the branch taken only when scp's own exit code is 0 and the file is there, and a finally deletes the copy.
  # shellcheck disable=SC2034
  re='^\$ps1 = Join-Path \$env:TEMP "cc-suites-\$\(\[guid\]::NewGuid\(\)\)\.ps1"; try \{ scp [^ ;]+ \$ps1; if \(\$LASTEXITCODE -eq 0 -and \(Test-Path \$ps1\)\) \{ powershell -ExecutionPolicy Bypass -File \$ps1 \} else \{ [^{}]* \} \} finally \{ Remove-Item -Force -ErrorAction SilentlyContinue \$ps1 \}$'
  k "$(b '[ "$(wc -l <<<"$cmd")" = 1 ] && [[ $cmd =~ $re ]] && [ "$(grep -o powershell <<<"$cmd" | wc -l)" = 1 ] && ! grep -q "cc-suites\.ps1" <<<"$cmd"')" "…and prints one command that runs the laptop's copy only when this scp worked, under a fresh name, and deletes it in a finally"
  k "$(b 'grep -qF "scp $(id -un)@my-box:$f \$ps1;" <<<"$cmd"')" "…fetching the script from this box as this account"
  # the same pattern must refuse the old shape, where ; ran a leftover copy whatever scp did
  k "$(b '! [[ "scp u@b:/x \$env:TEMP\\cc-suites.ps1; powershell -ExecutionPolicy Bypass -File \$env:TEMP\\cc-suites.ps1; del \$env:TEMP\\cc-suites.ps1" =~ $re ]]')" "…a check that refuses a command running the copy whatever scp did"
  out=$(cat "$f")
  k "$(b 'grep -qF "restrict,command=\"/usr/local/bin/cc-suites runner\" $(cat "$D/sd/id_ed25519.pub")" <<<"$out"')" "…and its script pins that key to the runner, restricted"
  k "$(b 'awk "/^base64 -d/{f=1;next} /^B64\$/{f=0} f" <<<"$out" | base64 -d | cmp -s - "$SELF"')" "…and carries this file byte for byte"
  k "$(b 'grep -q "bubblewrap" <<<"$out"')" "…installs bwrap, which the suite's sandbox cases run"
  k "$(b 'grep -qF "https://download.blender.org/release/Blender5.2/blender-$BLENDER_VERSION-linux-x64.tar.xz" <<<"$out" && grep -qF "echo \"$BLENDER_SHA256  \$t/b.tar.xz\" | sha256sum -c --quiet" <<<"$out" && grep -qx "  ln -sfn /opt/blender-$BLENDER_VERSION/blender /usr/local/bin/blender" <<<"$out" && grep -q "SSH_ORIGINAL_COMMAND=gpu " <<<"$out" && grep -q "SSH_ORIGINAL_COMMAND=gpustat " <<<"$out"')" "…installs the official Blender $BLENDER_VERSION, checked by sha256, as /usr/local/bin/blender, and says what GPU it sees and its stats"
  k "$(b 'grep -qx "printf '\''python3 %s\\\\nshellcheck %s\\\\n'\'' $(tool_version python3 | cut -d. -f1,2) $(tool_version shellcheck) >/etc/cc-suites/floor; chmod 644 /etc/cc-suites/floor" <<<"$out" && grep -q "sha256sum -c" <<<"$out"')" "…writes this box's python3 and shellcheck as the floor, and checks the shellcheck it fetches"
  # …and leaves the runner account nothing of its own to rewrite: the runner, the home, .ssh and authorized_keys root's
  k "$(b 'grep -qx "chown root:root /usr/local/bin/cc-suites; chmod 755 /usr/local/bin/cc-suites" <<<"$out" && grep -qx "install -d -m 755 -o root -g root /home/ccsuite /home/ccsuite/.ssh" <<<"$out" && grep -qx "chown root:root /home/ccsuite/.ssh/authorized_keys; chmod 644 /home/ccsuite/.ssh/authorized_keys" <<<"$out" && ! grep -q "chown ccsuite\|-o ccsuite -g ccsuite /home/ccsuite/.ssh\|useradd -m" <<<"$out"')" "…makes the runner, the runner account's home, .ssh and authorized_keys root's, never the account's"
  k "$(b 'grep -qx "usermod -s /bin/sh ccsuite" <<<"$out" && grep -qx "pkill -KILL -u ccsuite 2>/dev/null || true" <<<"$out" && grep -qx "rm -rf /home/ccsuite" <<<"$out" && grep -qx "keep_slots=; keep_maxload=; r=/home/ccsuite/.cc-suite-runner" <<<"$out" && ! grep -q "cp /home/ccsuite" <<<"$out"')" "…and wipes what an uncaged run could have left there (its processes, its home) but keeps its slots and maxload"
  k "$(b 'grep -q '\''^enabled=false'\'' <<<"$out" && grep -q '\''AllowUsers ccsuite@100.64.0.0/10'\'' <<<"$out"')" "…with interop and the C: mount off, and sshd for ccsuite from the tailnet only"
  awk "/^cat >\/etc\/ssh\/ssh_host_cc_suites_ed25519/{f=1;next} /^KEY\$/{f=0} f" <<<"$out" > "$D/hk"; chmod 600 "$D/hk"
  k "$(b '[ "$(cat "$D/sd/known_hosts")" = "my-node $(ssh-keygen -y -f "$D/hk" | cut -d" " -f1,2)" ] && grep -q "^HostKey /etc/ssh/ssh_host_cc_suites_ed25519" <<<"$out"')" "…and pins a host key of its own making: known here for my-node, installed there as sshd's only one"
  k "$(b '[ -z "$(ls "$D/sd" | grep -v "^id_ed25519\|^known_hosts\$\|^remote\$\|^laptop-setup.ps1\$\|^laptop-setup.node\$")" ] && [ "$(cat "$D/sd/laptop-setup.node")" = ccsuite@my-node ] && grep -q "PRIVATE KEY" "$f" && ! grep -q "PRIVATE KEY" <<<"$cmd"')" "…keeps that private key here only in the script's file, and never prints it"
  SECONDS=0; out=$(CC_SUITES_SSH="$D/xport-mute" CC_SUITES_STATUS_TIMEOUT=2s bash "$SELF" status --quick 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && [ "$SECONDS" -lt 4 ] && grep -q "does not answer" <<<"$out" && ! grep -q "its GPU" <<<"$out"')" "status --quick against a runner that hangs waits one bound, not one per question, and prints no GPU line (got $rc in ${SECONDS}s)"
  k "$(b '[ -s "$f" ]')" "a status the runner does not answer keeps the box's copy of the script…"
  # xport-old answers both status and the gpu question status now asks, so this waits on neither
  CC_SUITES_SSH="$D/xport-old" bash "$SELF" status >/dev/null 2>&1
  k "$(b '[ ! -e "$f" ]')" "…and the first status it answers removes it"
  echo again > "$f"; printf '#!/usr/bin/env bash\n[ "$1" = status ] && echo busy\n' > "$D/xport-busy"; chmod +x "$D/xport-busy"
  CC_SUITES_SSH="$D/xport-mute" CC_SUITES_STATUS_TIMEOUT=2s bash "$SELF" spill "$R/core/tests/selftest.sh" >/dev/null 2>&1
  k "$(b '[ -s "$f" ]')" "a spill the runner does not answer keeps it too…"
  CC_SUITES_SSH="$D/xport-busy" bash "$SELF" spill "$R/core/tests/selftest.sh" >/dev/null 2>&1; rc=$?
  k "$(b '[ "$rc" = 75 ] && [ ! -e "$f" ]')" "…and one it answers, even busy, removes it and runs nothing (got $rc)"
  # THE RUNNERS: two in `remote`, tried in order. The first answers busy and is passed over; the second takes the run.
  # Both busy: nothing runs and the box keeps it (75). The stub tells them apart by CC_SUITES_DEST.
  printf 'ccsuite@peer\nccsuite@laptop\n' > "$D/sd/remote"; : > "$D/two.calls"
  cat > "$D/xport-two" <<EOF
#!/usr/bin/env bash
echo "\$CC_SUITES_DEST \$1" >> "$D/two.calls"
[ "\$1" = status ] && [ -e "$D/busy.\${CC_SUITES_DEST#*@}" ] && { echo "busy (load 9.00)"; exit 0; }
exec "$D/xport" "\$@"
EOF
  chmod +x "$D/xport-two"; touch "$D/busy.peer"
  out=$(CC_SUITES_SSH="$D/xport-two" bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "running on the runner ccsuite@laptop" <<<"$out" && grep -q "ccsuite@peer answers busy" <<<"$out"')" "two runners, the first busy: the second runs the suite and the log names it (got $rc)"
  k "$(b '[ "$(grep -c "^ccsuite@peer" "$D/two.calls")" = 1 ] && grep -qx "ccsuite@peer status" "$D/two.calls" && grep -qx "ccsuite@laptop run" "$D/two.calls"')" "…the busy one was asked its status and given nothing to run"
  : > "$D/two.calls"; rm -f "$D/busy.peer"
  out=$(CC_SUITES_SSH="$D/xport-two" bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "running on the runner ccsuite@peer" <<<"$out" && ! grep -q "^ccsuite@laptop" "$D/two.calls"')" "…and with the first free, the first takes it and the second is never asked (got $rc)"
  touch "$D/busy.peer" "$D/busy.laptop"; : > "$D/two.calls"
  out=$(CC_SUITES_SSH="$D/xport-two" bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && [ "$(grep -c " status$" "$D/two.calls")" = 2 ] && ! grep -q " run$" "$D/two.calls"')" "both busy: spill asks each, runs nothing and says 75 (got $rc)"
  out=$(CC_SUITES_SSH="$D/xport-two" bash "$SELF" status 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && grep -q "runner ccsuite@peer answers: busy" <<<"$out" && grep -q "runner ccsuite@laptop answers: busy" <<<"$out"')" "…and status reports both, in order (got $rc)"
  rm -f "$D/busy.peer" "$D/busy.laptop"
  # the setup script is the laptop's: a peer that answers first must not delete it before the laptop has fetched it
  echo again > "$D/sd/laptop-setup.ps1"; echo ccsuite@laptop > "$D/sd/laptop-setup.node"
  printf '#!/usr/bin/env bash\n[ "${CC_SUITES_DEST#*@}" = laptop ] && exit 0\nexec "%s" "$@"\n' "$D/xport" > "$D/xport-lapmute"; chmod +x "$D/xport-lapmute"
  CC_SUITES_SSH="$D/xport-lapmute" bash "$SELF" status >/dev/null 2>&1
  k "$(b '[ -s "$f" ] && [ -s "$D/sd/laptop-setup.node" ]')" "two runners, the peer answers and the laptop does not: status leaves the laptop's setup script (and its record) alone"
  CC_SUITES_SSH="$D/xport-two" bash "$SELF" spill "$R/core/tests/selftest.sh" >/dev/null 2>&1
  k "$(b '[ -s "$f" ]')" "…and so does a spill the peer takes"
  touch "$D/busy.peer"; CC_SUITES_SSH="$D/xport-two" bash "$SELF" spill "$R/core/tests/selftest.sh" >/dev/null 2>&1; rc=$?
  k "$(b '[ "$rc" = 0 ] && [ ! -e "$f" ] && [ ! -e "$D/sd/laptop-setup.node" ]')" "the laptop answering (the busy peer passed over) removes the script and its record (got $rc)"
  rm -f "$D/busy.peer"
  # a silent peer (its stub exits with no output) is passed over for the next runner; only the last says nothing of a next
  cat > "$D/xport-silent" <<EOF
#!/usr/bin/env bash
[ "\${CC_SUITES_DEST#*@}" = peer ] && exit 0
exec "$D/xport" "\$@"
EOF
  chmod +x "$D/xport-silent"
  out=$(CC_SUITES_SSH="$D/xport-silent" bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 0 ] && grep -q "running on the runner ccsuite@laptop" <<<"$out" && grep -q "ccsuite@peer answers nothing: trying the next" <<<"$out"')" "a silent first runner is passed over and the second runs the suite (got $rc)"
  touch "$D/busy.peer" "$D/busy.laptop"
  out=$(CC_SUITES_SSH="$D/xport-two" bash "$SELF" spill "$R/core/tests/selftest.sh" 2>&1); rc=$?
  k "$(b '[ "$rc" = 75 ] && grep -q "ccsuite@peer answers busy.*: trying the next" <<<"$out" && grep -q "ccsuite@laptop answers busy" <<<"$out" && ! grep -q "ccsuite@laptop answers busy.*trying the next" <<<"$out"')" "the last runner passed over says nothing about a next (got $rc)"
  rm -f "$D/busy.peer" "$D/busy.laptop"
  # a rerun of laptop-setup keeps the other runner's line and pinned key, and replaces only its own node's, last
  printf 'ccsuite@peer\nccsuite@my-node\n' > "$D/sd/remote"; echo "peer ssh-ed25519 AAAApeer" >> "$D/sd/known_hosts"
  local oldkey; oldkey=$(grep '^my-node ' "$D/sd/known_hosts")
  CC_SUITES_BOX=my-box bash "$SELF" laptop-setup my-node >/dev/null 2>&1; rc=$?
  k "$(b '[ "$rc" = 0 ] && [ "$(cat "$D/sd/remote")" = "$(printf "ccsuite@peer\nccsuite@my-node")" ] && grep -qx "peer ssh-ed25519 AAAApeer" "$D/sd/known_hosts" && [ "$(grep -c "^my-node " "$D/sd/known_hosts")" = 1 ] && ! grep -qxF "$oldkey" "$D/sd/known_hosts"')" "a rerun of laptop-setup keeps the peer host first and its key, and re-pins only its own node"
  unset CC_SUITES_SSH; local -a XP
  # here-strings, not printf | grep -q: under pipefail grep -q's early exit breaks printf's pipe and fails the case
  k "$(b 'xport_argv && grep -qx StrictHostKeyChecking=yes <<<"$(printf "%s\n" "${XP[@]}")" && ! grep -q accept-new <<<"$(printf "%s\n" "${XP[@]}")"')" "the transport takes that key and no other (StrictHostKeyChecking=yes)"
  rm -f "$D/sd/known_hosts"
  k "$(b '! configured')" "…and with no pinned key there is no runner"
  kill $p1 $p2 $p3 $p4 2>/dev/null; rm -rf "$D"
  echo "cc-suites selfcheck: $pass passed, $fail failed"
  [ "$fail" = 0 ]
}
