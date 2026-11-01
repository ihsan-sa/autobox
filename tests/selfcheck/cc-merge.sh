#!/usr/bin/env bash
# cc-merge's selfcheck: each case builds its own fixture (a bare remote, the deployed checkout cloned from it, a track
# branch for PR 7) and runs cc-merge against a fake gh and fake box tools; never a real GitHub.
#   bash core/tests/selfcheck/cc-merge.sh      exit 0 when every case passes
set -uo pipefail
HERE=$(cd "$(dirname "$(realpath "$0")")/../.." && pwd)   # core/
n=0 f=0
t(){ n=$((n + 1)); if [ "$2" = "$3" ]; then echo "ok   $1"; else f=$((f + 1)); echo "FAIL $1: got [$2] want [$3]"; fi; }
TOP=$(mktemp -d); trap 'rm -rf "${TOP:?}"' EXIT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t GIT_CONFIG_NOSYSTEM=1

fx(){   # $1 case name → a fresh fixture in $T; PR 7 is track/x adding x.txt on top of main
  T="$TOP/$1"; mkdir -p "$T/fb" "$T/home" "$T/dev" "$T/o"
  git init -q --bare -b main "$T/o/r.git"
  git clone -q "$T/o/r.git" "$T/dev/r" 2>/dev/null
  ( cd "$T/dev/r" && mkdir tests && printf 'paths = ["secret/**"]\n' > tests/LANDING-security.toml && echo a > a.txt \
    && git add -A && git commit -qm base && git push -q origin main \
    && git checkout -qb track/x && echo x > x.txt && git add x.txt && git commit -qm x && git push -q origin track/x \
    && git checkout -q main )
  echo true > "$T/merge"; echo 0 > "$T/check.rc"; echo 0 > "$T/workflows"; echo 0 > "$T/ci.rc"
  for c in cc-board cc-slack cc-failures; do printf '#!/bin/sh\necho "%s $*" >> "%s/calls"\n' "$c" "$T" > "$T/fb/$c"; done
  # the real lander: exit 0 when it queued, even paused (its "lander: … paused" line); non-zero only when it refused
  printf '#!/bin/sh\necho "cc-land $*" >> "%s/calls"\necho "[r] PR #7 queued"; [ -f "%s/land.say" ] && cat "%s/land.say"\n[ -f "%s/land.no" ] || exit 0; echo "the door refused it"; exit 1\n' "$T" "$T" "$T" "$T" > "$T/fb/cc-land"
  printf '#!/bin/sh\n[ "$1" = lands ] || exit 9\nexit $(cat "%s/lands.rc")\n' "$T" > "$T/fb/cc"; echo 0 > "$T/lands.rc"; echo main > "$T/dflt"
  printf 'o/r\n' > "$T/headrepo"
  printf '#!/bin/sh\n' > "$T/fb/cc-gh-token"
  # the real cc-config on the fixture HOME's own config, which holds a key but no CC_PROTECTED_PATHS_r
  printf '#!/bin/sh\nunset CC_CONFIG; exec "%s/bin/cc-config" "$@"\n' "$HERE" > "$T/fb/cc-config"; mkdir "$T/home/.cc"; echo 'OTHER=1' > "$T/home/.cc/config"
  cat > "$T/fb/gh" <<EOF
#!/usr/bin/env bash
T="$T"
case "\$*" in
  "api repos/o/r/pulls/7 "*) echo "gh pr read" >> "\$T/calls"; [ -f "\$T/pr.fail" ] && exit 1
    printf 'track/x\tmain\topen\t%s\t%s\tAdd x\n' "\$(cat "\$T/headrepo")" "\$(cat "\$T/dflt")" ;;
  "api repos/o/r/actions/workflows"*) [ "\$(cat "\$T/workflows")" = fail ] && { echo "HTTP 502" >&2; exit 1; }; cat "\$T/workflows" ;;
  "pr checks 7 -R o/r"*) echo "gh pr checks \$*" >> "\$T/calls"; [ -f "\$T/ci.hang" ] && exec sleep 30; exit "\$(cat "\$T/ci.rc")" ;;
  "api -X PUT repos/o/r/pulls/7/merge"*) sha=\$(grep -o 'sha=[0-9a-f]*' <<<"\$*"); echo "merge \$sha" >> "\$T/calls"
    m=\$(cat "\$T/merge"); [ "\$m" = true ] && git --git-dir="\$T/o/r.git" update-ref refs/heads/main "\${sha#sha=}"
    [ -f "\$T/on-merge" ] && . "\$T/on-merge"; echo "\$m"; [ "\$m" = true ] ;;
  *) echo "fake gh: \$*" >&2; exit 9 ;;
esac
EOF
  printf '#!/bin/sh\necho "check $(git rev-parse HEAD) token=${GH_TOKEN-unset} in=$PWD" >> "%s/calls"\nexit $(cat "%s/check.rc")\n' "$T" "$T" > "$T/check"
  chmod +x "$T"/fb/* "$T/check"; }
run(){   # → cc-merge's exit code; its output in $T/out. RUNIN: the cwd it starts in. CHECK="": the real runner
  ( export CC_MERGE_TEST=1 HOME="$T/home" CC_DEV="$T/dev" CC_MERGE_BIN="$T/fb" CC_MERGE_CORE="$HERE" CC_MERGE_CHECK="${CHECK-$T/check}" \
      CC_MERGE_SETTLE=0 PATH="${PFX:-}$T/fb:$PATH" CC_MERGE_PATH="${DPATH:-$T/fb:/usr/local/bin:/usr/bin:/bin}" GH_TOKEN=secret
    cd "${RUNIN:-.}" && "$HERE/bin/cc-merge" r 7 ) > "$T/out" 2>&1; echo $?; }
calls(){ cat "$T/calls" 2>/dev/null | grep -c "^$1"; }
tip(){ git --git-dir="$T/o/r.git" rev-parse "$1"; }

fx kept; (cd "$T/dev/r" && git checkout -q track/x && mkdir secret && echo s > secret/k && git add -A && git commit -qm s && git push -q origin track/x && git checkout -q main)
t 'a kept-list hit goes to the lander queue and is not merged' "$(run):$(grep -c '^cc-land queue r 7 --who cc-merge' "$T/calls"):$(calls merge):$(calls check)" '3:1:0:0'

fx kept-from-base; (cd "$T/dev/r" && git checkout -q track/x && printf 'paths = []\n' > tests/LANDING-security.toml && mkdir secret && echo s > secret/k && git add -A && git commit -qm s && git push -q origin track/x && git checkout -q main)
t 'the kept list is the base'"'"'s: a PR emptying it in its own tree is still kept' "$(run):$(calls merge)" '3:0'

fx protected; echo 'CC_PROTECTED_PATHS_r=x.txt' >> "$T/home/.cc/config"
t 'a path under the repo'"'"'s CC_PROTECTED_PATHS is kept for the lander'"'"'s owner door' "$(run):$(calls merge)" '3:0'

fx catchup; (cd "$T/dev/r" && echo b > b.txt && git add b.txt && git commit -qm b && git push -q origin main)
mainb=$(tip main)
rc=$(run); head=$(tip track/x)
t 'catch-up: main is merged into the branch with a plain push, checked and merged at that head' \
  "$rc:$(git --git-dir="$T/o/r.git" merge-base --is-ancestor "$mainb" "$head" && echo in):$(git --git-dir="$T/o/r.git" rev-list --parents -1 "$head" | wc -w):$(grep -c "^check $head" "$T/calls"):$(grep -c "^merge sha=$head" "$T/calls")" '0:in:3:1:1'

fx red; echo 1 > "$T/check.rc"
t 'a red lander check goes back to the worker and nothing merges' "$(run):$(calls merge):$(grep -c 'NOT MERGED' "$T/out")" '1:0:1'

fx ci-red; echo 1 > "$T/workflows"; echo 1 > "$T/ci.rc"
t 'red GitHub checks go back to the worker and nothing merges' "$(run):$(calls 'gh pr checks'):$(calls merge)" '1:1:0'

fx refused; echo '{"message":"Head branch was modified"}' > "$T/merge"
t 'a refused merge goes back to the worker with no after-steps' "$(run):$(calls merge):$(calls cc-board):$(calls cc-slack)" '1:1:0:0'

fx clean; x=$(tip track/x)
rc=$(run)
t 'a clean merge: checked with no token, merged at the head, row merged, card posted, checkout fast-forwarded' \
  "$rc:$(grep -c "^check $x token=unset" "$T/calls"):$(grep -c "^merge sha=$x" "$T/calls"):$(calls 'cc-board status r x merged'):$(calls 'cc-slack post-approval --landed r 7'):$(git -C "$T/dev/r" rev-parse HEAD)" \
  "0:1:1:1:1:$x"
t 'the throwaway worktree is gone after the run' "$(git -C "$T/dev/r" worktree list | wc -l)" 1

fx installer; (cd "$T/dev/r" && printf '#!/bin/sh\necho installed >> "%s/calls"\n' "$T" > inst.sh && chmod +x inst.sh \
  && printf 'installer = "inst.sh"\n' > tests/LANDING-deploy.toml && git add -A && git commit -qm i && git push -q origin main)
printf '#!/bin/sh\necho "systemctl $*" >> "%s/calls"\n' "$T" > "$T/fb/systemctl"; chmod +x "$T/fb/systemctl"
t 'after the merge the installer the repo names runs, then a user daemon-reload' "$(run):$(calls installed):$(calls 'systemctl --user daemon-reload')" '0:1:1'

fx moved; (cd "$T/dev/r" && git checkout -q -b elsewhere)
t 'a moved checkout: merged, but the deploy refuses loudly and moves nothing' \
  "$(run):$(grep -c 'DEPLOY REFUSED' "$T/out"):$(git -C "$T/dev/r" symbolic-ref --short HEAD)" '0:1:elsewhere'

fx kept-config; echo 'r x.txt   # a box glob' > "$T/kept.txt"
t 'a glob the box keeps for this repo (CC_MERGE_KEPT, not core) is kept' "$(CC_MERGE_KEPT="$T/kept.txt" run):$(calls merge)" '3:0'

fx land-refuses; (cd "$T/dev/r" && git checkout -q track/x && mkdir secret && echo s > secret/k && git add -A && git commit -qm s && git push -q origin track/x && git checkout -q main)
touch "$T/land.no"
t 'a lander that refuses to queue a kept PR: exit 4 with its own reason, nothing merged' "$(run):$(calls merge):$(tail -1 "$T/out" | grep -c 'the door refused it')" '4:0:1'

fx wf-fault; echo fail > "$T/workflows"; echo 1 > "$T/ci.rc"
t 'a workflows lookup that fails is not "no workflows": CI is waited on, and red CI does not merge' "$(run):$(calls 'gh pr checks'):$(calls merge)" '1:1:0'

fx pr-fault; touch "$T/pr.fail"
t 'a PR GitHub will not read is retried, then left in the lander'"'"'s queue with the reason' "$(run):$(calls 'gh pr read'):$(calls 'cc-land queue r 7'):$(tail -1 "$T/out" | grep -c 'would not say')" '3:3:1:1'

fx fork; echo 'someone/r' > "$T/headrepo"; x=$(tip track/x); (cd "$T/dev/r" && echo b > b.txt && git add b.txt && git commit -qm b && git push -q origin main)
t 'a fork PR on a branch named like ours is neither caught up nor merged' "$(run):$(calls merge):$(calls check):$(tip track/x)" "2:0:0:$x"

fx deploy-refused; (cd "$T/dev/r" && git checkout -q -b moved)
t 'a refused deploy after the merge: merged, said on the last line, and recorded' \
  "$(run):$(calls merge):$(tail -1 "$T/out" | grep -c 'merged, but the deploy was refused'):$(calls 'cc-failures record')" '0:1:1:1'

fx per-run; echo 1 > "$T/check.rc"; run >/dev/null; run >/dev/null
t 'each run checks in a worktree of its own' "$(grep -o 'in=[^ ]*' "$T/calls" | sort -u | wc -l)" 2

kpr(){ (cd "$T/dev/r" && git checkout -q track/x && mkdir -p "$(dirname "$1")" && echo k > "$1" && git add -A && git commit -qm k && git push -q origin track/x && git checkout -q main); }
fx kept-utf8; kpr 'secret/zé'
t 'a kept path with a non-ASCII name (which git quotes) is still kept' "$(run):$(calls merge)" '3:0'

fx kept-lander-lists; (cd "$T/dev/r" && printf '[paths]\ngate_first = ["core/bin/cc-config"]\n' > tests/LANDING-policy.toml && git add -A && git commit -qm p && git push -q origin main && git checkout -q track/x && git merge -q main && git push -q origin track/x && git checkout -q main)
kpr core/bin/cc-config
t 'a path on the base policy'"'"'s gate_first list (the lander'"'"'s own lists) is kept' "$(run):$(calls merge)" '3:0'

fx kept-never; kpr config/names.json
t 'config/names.json (the lander'"'"'s NEVER list) is kept whatever the policy' "$(run):$(calls merge)" '3:0'

fx prot-unread; printf '#!/bin/sh\nexit 2\n' > "$T/fb/cc-config"
t 'protected paths that will not read keep every file' "$(run):$(calls merge)" '3:0'
fx prot-exit1; printf '#!/bin/sh\nexit 1\n' > "$T/fb/cc-config"
t 'a cc-config that exits 1 with no answer is a failed read: every file is kept' "$(run):$(calls merge)" '3:0'
fx prot-noperm; chmod 000 "$T/home/.cc/config"
t 'a config file that cannot be read is a failed read: every file is kept' "$(run):$(calls merge)" '3:0'
fx prot-nofile; rm -f "$T/home/.cc/config"
t 'a config file that is not there is a failed read: every file is kept' "$(run):$(calls merge)" '3:0'
fx prot-unset
t 'a key the config really does not set is a real empty: the PR merges' "$(run):$(calls merge)" '0:1'
fx prot-empty; echo 'CC_PROTECTED_PATHS_r=' >> "$T/home/.cc/config"
t 'a key the config really sets to nothing is a real empty: the PR merges' "$(run):$(calls merge)" '0:1'

fx paused; kpr secret/k; echo 'lander: r is paused — nothing lands until `cc-pause off r`' > "$T/land.say"
t 'a lander that queues but is paused (exit 0): its line is on the last line, nothing merged' "$(run):$(calls merge):$(tail -1 "$T/out" | grep -c 'waits in the lander.s queue (r is paused')" '3:0:1'

# a worker's chmod and a copy: the head tree's loose object now holds the base tree's bytes, so the shared checkout's diff lists no file
poison(){ local o=$T/dev/r/.git/objects h b; h=$(git -C "$T/dev/r" rev-parse 'track/x^{tree}'); b=$(git -C "$T/dev/r" rev-parse 'main^{tree}')
  chmod u+w "$o/${h:0:2}/${h:2}"; cp -f "$o/${b:0:2}/${b:2}" "$o/${h:0:2}/${h:2}"; }
fx kept-poisoned; kpr secret/k; poison
t 'a kept PR whose head tree a worker overwrote with the base'"'"'s bytes is still held: a read that raises keeps it' \
  "$(run):$(calls 'cc-land queue r 7'):$(calls merge):$(tail -1 "$T/out" | grep -c 'would not read sealed')" '3:1:0:1'

# the base and the deployed tip are what the fetch reported. hide: a kept file below a fake base, so a diff from there lists no kept file
hide(){ kpr secret/k; kpr y.txt; }
# a worker moving refs/remotes/origin/main right after each fetch of it, to the commit in $T/moved
mover(){ local real; real=$(command -v git); printf '#!/bin/sh\n"%s" "$@"; rc=$?\ncase "$*" in *" fetch "*refs/remotes/origin/main*) "%s" -C "%s/dev/r" update-ref refs/remotes/origin/main "$(cat "%s/moved")" ;; esac\nexit $rc\n' "$real" "$real" "$T" "$T" > "$T/fb/git"; chmod +x "$T/fb/git"; }
fx tag-base; hide; git -C "$T/dev/r" tag origin/main track/x^
t 'a tag named origin/main does not become the base: the kept file below it still holds the PR' "$(run):$(calls merge)" '3:0'
fx tag-deploy; x=$(tip track/x); git -C "$T/dev/r" tag origin/main main
t 'a tag named origin/main does not stop the deploy: the checkout reaches the remote branch' "$(run):$(git -C "$T/dev/r" rev-parse HEAD)" "0:$x"
fx ref-moved; hide; git -C "$T/dev/r" rev-parse track/x^ > "$T/moved"; mover
t 'origin/main moved after the fetch does not become the base: the PR is still held' "$(run):$(calls merge)" '3:0'
fx ref-moved-deploy; x=$(tip track/x); git -C "$T/dev/r" commit-tree -p main -m junk 'main^{tree}' > "$T/moved"; mover
t 'origin/main moved after the fetch is not what deploys' "$(run):$(git -C "$T/dev/r" rev-parse HEAD)" "0:$x"

# the base moved a file onto a kept path, and the PR only edits the old name: the kept check on the old head sees no kept
# file, and the merge's rename detection lands the PR's edit on the kept path
fx catchup-kept; (cd "$T/dev/r" && seq 1 40 > long.txt && git add -A && git commit -qm long && git push -q origin main \
  && git checkout -q track/x && git merge -q main && sed -i '1s/.*/mine/' long.txt && git add -A && git commit -qm edit && git push -q origin track/x \
  && git checkout -q main && mkdir secret && git mv long.txt secret/long && git commit -qm moved && git push -q origin main)
oldhead=$(tip track/x)
t 'a catch-up merge that lands on a kept path is held after its push: exit 3, queued, not checked or merged' \
  "$(run):$(calls 'cc-land queue r 7'):$(calls check):$(calls merge):$([ "$(tip track/x)" != "$oldhead" ] && echo pushed):$(tail -1 "$T/out" | grep -c 'catch-up merge changes a kept path (secret/long)')" '3:1:0:0:pushed:1'

# a worker's chmod and a copy, after a first run primed the sealed cache: a docs/ subtree or a blob now reads as other bytes
# in the shared objects, which the root tree's hash check never sees
swap(){ local o=$T/dev/r/.git/objects; chmod u+w "$o/${1:0:2}/${1:2}"; cp -f "$o/${2:0:2}/${2:2}" "$o/${1:0:2}/${1:2}"; }
docs(){ (cd "$T/dev/r" && git checkout -q track/x && mkdir docs && echo real > docs/f && git add -A && git commit -qm d && git push -q origin track/x && git checkout -q main)
  printf 'ls docs >> "%s/seen"; cat docs/f >> "%s/seen"\nexit $(cat "%s/check.rc")\n' "$T" "$T" "$T" > "$T/check"; echo 1 > "$T/check.rc"; run >/dev/null; rm -f "$T/seen"; echo 0 > "$T/check.rc"; }
blob(){ printf %s "$1" | git -C "$T/dev/r" hash-object -w --stdin; }
fx sub-poisoned; docs; e=$(blob evil); swap "$(git -C "$T/dev/r" rev-parse track/x:docs)" "$(printf '100644 blob %s\tevil\n' "$e" | git -C "$T/dev/r" mktree)"
rc=$(run)
t 'a swapped subtree never reaches the check: its tree comes from the sealed fetch' "$rc:$(tr '\n' ' ' < "$T/seen")" '0:f real '
t 'a swapped subtree never reaches the deploy: the checkout gets the tree GitHub merged' "$(ls "$T/dev/r/docs"):$(cat "$T/dev/r/docs/f")" 'f:real'
fx blob-poisoned; docs; e=$(blob evil); swap "$(git -C "$T/dev/r" rev-parse track/x:docs/f)" "$e"
rc=$(run)
t 'a swapped blob reaches neither the check nor the deploy' "$rc:$(tr '\n' ' ' < "$T/seen"):$(cat "$T/dev/r/docs/f")" '0:f real :real'
# a commit the sealed cache has not read, whose subtree is swapped: the deploy holds and nothing moves
fx deploy-mismatch; docs
cat > "$T/on-merge" <<EOF
( cd "$T/dev/r" && git worktree add -q --detach "$T/later" "\${sha#sha=}" && cd "$T/later" && mkdir more && echo real > more/g && git add -A && git commit -qm later && git push -q origin HEAD:refs/heads/main
  o=\$(git rev-parse HEAD:more); s=\$(printf '100644 blob %s\tevil\n' "\$(printf evil | git hash-object -w --stdin)" | git mktree); d="$T/dev/r/.git/objects"; chmod u+w "\$d/\${o:0:2}/\${o:2}"; cp -f "\$d/\${s:0:2}/\${s:2}" "\$d/\${o:0:2}/\${o:2}" ) >/dev/null 2>&1
EOF
was=$(git -C "$T/dev/r" rev-parse HEAD)
t 'a deploy tip that will not read sealed is refused and nothing moves' \
  "$(run):$(grep -c 'DEPLOY REFUSED' "$T/out"):$(git -C "$T/dev/r" rev-parse HEAD):$(ls "$T/dev/r/more" 2>/dev/null | wc -l)" "0:1:$was:0"
fx dirty; echo mine > "$T/dev/r/x.txt"
t 'a checkout with a local file in the way: merged, the deploy refuses and keeps the file' "$(run):$(grep -c 'DEPLOY REFUSED' "$T/out"):$(cat "$T/dev/r/x.txt")" '0:1:mine'
fx planted; (cd "$T/dev/r" && git checkout -q track/x && echo mine > a.txt && git add -A && git commit -qm m && git push -q origin track/x && git checkout -q main && echo base > b.txt && git add -A && git commit -qm b && git push -q origin main)
printf '* filter=x\nb.txt filter=x\n' > "$T/dev/r/.git/info/attributes"
git -C "$T/dev/r" config filter.x.smudge "touch $T/ran; cat"; git -C "$T/dev/r" config filter.x.required true
run >/dev/null
t 'a filter planted in the shared config runs in neither the worktree nor the deploy' "$(ls "$T/ran" 2>/dev/null | wc -l):$(calls merge)" '0:1'
fx planted-driver; (cd "$T/dev/r" && git checkout -q track/x && echo mine > a.txt && git add -A && git commit -qm m && git push -q origin track/x && git checkout -q main && echo theirs > a.txt && git add -A && git commit -qm b && git push -q origin main)
echo '* merge=x' > "$T/dev/r/.git/info/attributes"; git -C "$T/dev/r" config merge.x.driver "touch $T/ran; true"
t 'a merge driver planted in the shared config does not run: the conflict goes back to the worker' "$(run):$(ls "$T/ran" 2>/dev/null | wc -l):$(calls merge)" '1:0:0'

# a worker's cwd: a planted module must not load in any python of cc-merge, on the deploy's path or the kept check's
fx planted-module; (cd "$T/dev/r" && printf '#!/bin/sh\necho installed >> "%s/calls"\n' "$T" > inst.sh && chmod +x inst.sh && printf 'installer = "inst.sh"\n' > tests/LANDING-deploy.toml && git add -A && git commit -qm i && git push -q origin main)
printf '#!/bin/sh\n' > "$T/fb/systemctl"; chmod +x "$T/fb/systemctl"; mkdir "$T/wk"
for m in tomllib subprocess tempfile; do printf 'open("%s/ran", "w")\n' "$T" > "$T/wk/$m.py"; done
t 'modules planted in the cwd cc-merge starts in do not load, and the installer the toml names still runs' "$(RUNIN="$T/wk" run):$(ls "$T/ran" 2>/dev/null | wc -l):$(calls installed)" '0:0:1'

# the real runner, on a repo whose check owns src/**: red on the head, green on the base. A first run primes the sealed
# cache; then a worker's copy puts the head's src tree under the base's name, so a diff of the shared objects lists no src/a
realfx(){ fx "$1"; (cd "$T/dev/r" && mkdir src && echo a > src/a && printf '[[check]]\nname = "src-red"\nrun = "grep -q a src/a"\npaths = ["src/**"]\nclass = "static"\ncap = 60\n' > tests/LANDING.toml && git add -A && git commit -qm m && git push -q origin main \
  && git checkout -q track/x && git merge -q main && echo b > src/a && git add -A && git commit -qm red && git push -q origin track/x && git checkout -q main); }
rlog(){ ls -t "$T/home/.cc/state/r"/merge-*.log | head -1; }
realfx real-plain
wt=$T/plain; git -C "$T/dev/r" worktree add -q --detach "$wt" track/x
t 'a plain lander check, outside cc-merge and with no --head, still plans the working copy' \
  "$(cd "$wt" && echo more > untracked && HOME="$T/home" CC_DEV="$T/dev" python3 -P "$HERE/lander/cli.py" check --base "$(git -C "$T/dev/r" rev-parse main)" "$wt" 2>&1 | grep -c '^lander check: 3 file(s) changed, 1 check(s)')" 1
realfx real-swap; CHECK='' run >/dev/null
swap "$(git -C "$T/dev/r" rev-parse main:src)" "$(git -C "$T/dev/r" rev-parse track/x:src)"
rc=$(CHECK='' run)
t 'a swapped base subtree does not deselect the real runner'"'"'s check: it stays selected and nothing merges' "$rc:$(calls merge):$(grep -c '^lander check: 2 file(s) changed, 1 check(s)' "$(rlog)")" '1:0:1'
fx real-clean; (cd "$T/dev/r" && git checkout -q track/x && printf 'open("%s/ran", "w")\n' "$T" > subprocess.py && git add -A && git commit -qm p && git push -q origin track/x && git checkout -q main)
t 'the real runner on a PR carrying a planted module: the module does not load, and a PR no check owns merges' "$(CHECK='' run):$(calls merge):$(ls "$T/ran" 2>/dev/null | wc -l)" '0:1:0'

# a check only the host can run, whose script the PR edits: an unread head never runs there. $1 the check's own lines
hostmf(){ printf '[[check]]\nname = "host-only"\nrun = "sh src/h.sh"\npaths = ["src/**"]\nclass = "host"\ncap = 60\n%b' "$1" > tests/LANDING.toml; }
hostfx(){ fx "$1"; (cd "$T/dev/r" && mkdir src && echo 'echo ok' > src/h.sh && hostmf "$2" && git add -A && git commit -qm m && git push -q origin main \
  && git checkout -q track/x && git merge -q main && printf 'touch "%s/ran"\n' "$T" > src/h.sh && git add -A && git commit -qm h && git push -q origin track/x && git checkout -q main); }
held(){ local rc; rc=$(CHECK='' run); echo "$rc:$(calls 'cc-land queue r 7'):$(calls merge):$(ls "$T/ran" 2>/dev/null | wc -l):$(tail -1 "$T/out" | grep -c 'runs only on the host (host-only)')"; }
hostfx host-unread 'where = ["box"]\n'
t 'a host-only check whose script the PR edits never runs: queued for a read, nothing merged' "$(held)" '3:1:0:0:1'
hostfx host-bare 'bare = true\nwhere = ["box", "laptop"]\n'
t 'a bare host check never runs on an unread head either, wherever else it may run' "$(held)" '3:1:0:0:1'
fx host-catchup; (cd "$T/dev/r" && mkdir src && echo 'echo ok' > src/h.sh && git add -A && git commit -qm s && git push -q origin main \
  && git checkout -q track/x && git merge -q main && printf 'touch "%s/ran"\n' "$T" > src/h.sh && git add -A && git commit -qm h && git push -q origin track/x \
  && git checkout -q main && hostmf 'where = ["box"]\n' && git add -A && git commit -qm m && git push -q origin main)
oldhead=$(tip track/x)
t 'a host-only check main brought in holds after the catch-up: pushed, queued, never run' "$(held):$([ "$(tip track/x)" != "$oldhead" ] && echo pushed)" '3:1:0:0:1:pushed'
hostfx host-plain 'where = ["box"]\n'; wt=$T/plain; git -C "$T/dev/r" worktree add -q --detach "$wt" track/x
t 'a plain lander check with no --head still runs a host check' "$(cd "$wt" && HOME="$T/home" CC_DEV="$T/dev" python3 -P "$HERE/lander/cli.py" check --base "$(git -C "$T/dev/r" rev-parse main)" "$wt" >/dev/null 2>&1; echo "$?:$(ls "$T/ran" 2>/dev/null | wc -l)")" '0:1'
hostfx host-caged 'where = ["box", "laptop"]\n'; CHECK='' run >/dev/null
t 'a host check the cage can run is not held: no read is asked for, and it never touches the host' "$(calls 'cc-land queue r 7'):$(ls "$T/ran" 2>/dev/null | wc -l)" '0:0'

# a name new to core/bin or bin-private goes on ~/bin at the install, ahead of a real command: it waits for a read
binfx(){ fx "$1"; (cd "$T/dev/r" && mkdir -p core/bin bin-private boxes/x core/docs && echo t > core/bin/tool && echo p > bin-private/tool && echo b > boxes/x/BOX.md && echo w > core/docs/WORKING.md && git add -A && git commit -qm b && git push -q origin main \
  && git checkout -q track/x && git merge -q main && echo "$3" > "$2" && git add -A && git commit -qm n && git push -q origin track/x && git checkout -q main); }
binfx bin-new core/bin/systemctl planted
t 'a PR adding a name to core/bin is kept: queued, nothing merged' "$(run):$(calls 'cc-land queue r 7'):$(calls merge)" '3:1:0'
binfx bin-private-new bin-private/systemctl planted
t 'a PR adding a name to bin-private is kept the same way' "$(run):$(calls 'cc-land queue r 7'):$(calls merge)" '3:1:0'
binfx bin-edit core/bin/tool edited
t '…and one editing a name already there is not, in a repo with no box list' "$(run):$(calls 'cc-land queue r 7'):$(calls merge)" '0:0:1'
# the box's own list, read from the real file: in the box repo an edit to a tool or a standing rule file waits for a read too
sed -E 's/^[^ #]+ /r /' "$HERE/../config/merge-kept.txt" > "$TOP/box-kept.txt"
for kf in core/bin/tool bin-private/tool boxes/x/BOX.md core/docs/WORKING.md; do
  binfx "box-list-${kf//\//-}" "$kf" edited
  t "with the box's list, an edit to $kf is kept" "$(CC_MERGE_KEPT="$TOP/box-kept.txt" run):$(calls 'cc-land queue r 7'):$(calls merge)" '3:1:0'
done
binfx box-list-other x.txt edited
t "…and with that list a file off it still merges itself" "$(CC_MERGE_KEPT="$TOP/box-kept.txt" run):$(calls 'cc-land queue r 7'):$(calls merge)" '0:0:1'
# the deploy: a systemctl an earlier merge linked ahead on the caller's PATH never runs, and no token reaches the installer
fx deploy-env; (cd "$T/dev/r" && printf '#!/bin/sh\necho "installed token=${GH_TOKEN-unset} path=$PATH" >> "%s/calls"\n' "$T" > inst.sh && chmod +x inst.sh \
  && printf 'installer = "inst.sh"\n' > tests/LANDING-deploy.toml && git add -A && git commit -qm i && git push -q origin main)
mkdir "$T/planted" "$T/fixed"; for w in planted fixed; do printf '#!/bin/sh\necho "%s systemctl token=${GH_TOKEN-unset}" >> "%s/calls"\n' "$w" "$T" > "$T/$w/systemctl"; chmod +x "$T/$w/systemctl"; done
rm -f "$T/fb/systemctl"
fixed="$T/fixed:$T/fb:/usr/bin:/bin"
rc=$(DPATH="$fixed" PFX="$T/planted:" run)
t 'the deploy runs on the fixed PATH with no token: the planted systemctl never runs, and the installer sees neither' \
  "$rc:$(calls 'planted systemctl'):$(calls 'fixed systemctl token=unset'):$(grep -c "^installed token=unset path=$fixed\$" "$T/calls")" '0:0:1:1'

# the ratchet: `lander check` with the real judge, only the cage swapped for a plain shell, since a sandbox may not start bwrap
cat > "$TOP/nocage" <<EOF
#!/usr/bin/env python3
import os, sys
sys.path.insert(0, "$HERE")
from lander import check, run as R, sandbox as S
def plain(c, head, cwd, run_dir, env, started_fd=None):
    pin, said = (S.pin(started_fd), S.started(S.FD)) if started_fd is not None else ([], [])
    return pin + said + ["/bin/sh", "-c", c.run], os.path.join(head, cwd) if cwd else head, R.clean_env({**(env or {}), "TMPDIR": R.host_tmp(run_dir)}), "host"
R._box_argv = plain; S.available = lambda: True
sys.exit(check.cmd_check(sys.argv[1:]))
EOF
chmod +x "$TOP/nocage"
redfx(){ fx "$1"; (cd "$T/dev/r" && mkdir src && printf 'exit 1\n' > src/t.sh && printf '[[check]]\nname = "both-red"\nrun = "sh src/t.sh"\npaths = ["src/**"]\nclass = "static"\ncap = 60\n' > tests/LANDING.toml && git add -A && git commit -qm m && git push -q origin main \
  && git checkout -q track/x && git merge -q main && printf '# mine\nexit 1\n' > src/t.sh && git add -A && git commit -qm t && git push -q origin track/x && git checkout -q main); }
redfx ratchet
t 'a check red on the PR and on main, which the PR touches, is refused by the ratchet: back to the worker, named, not merged' "$(CHECK="$TOP/nocage" run):$(calls merge):$(tail -1 "$T/out" | grep -c "would not call it main's: both-red")" '1:0:1'
goneman(){ (cd "$T/dev/r" && mkdir src && echo a > src/a && printf '[[check]]\nname = "gone"\nrun = "src/gone.sh"\npaths = ["src/**"]\nclass = "static"\ncap = 60\n' > tests/LANDING.toml && git add -A && git commit -qm m && git push -q origin main \
  && git checkout -q track/x && git merge -q main && echo b > src/a && git add -A && git commit -qm t && git push -q origin track/x && git checkout -q main); }
fx blocked-gone; goneman
t 'a check main registered with no run file is blocked under the real runner: not merged either' "$(CHECK='' run):$(calls merge):$(tail -1 "$T/out" | grep -c "would not call it main's: gone")" '1:0:1'
fx blocked-plain; goneman; wt=$T/plain; git -C "$T/dev/r" worktree add -q --detach "$wt" track/x
t 'a plain lander check with no --head still says main-red and exits 0, as cc-green reads it' "$(cd "$wt" && HOME="$T/home" CC_DEV="$T/dev" python3 -P "$HERE/lander/cli.py" check --base "$(git -C "$T/dev/r" rev-parse main)" "$wt" 2>&1 | grep -c '^  main-red gone'; echo "${PIPESTATUS[0]}")" "1
0"

# the restart list: a real file under svc/ and another tree's bytes under more/'s name, swapped in the old commit's objects
fx restarts; (cd "$T/dev/r" && mkdir -p core/bin svc more && printf '#!/bin/sh\nshift 3\nprintf "%%s\\n" "$@" > "%s/restart-for"\n' "$T" > core/bin/cc-units && chmod +x core/bin/cc-units \
  && echo u > svc/u && echo g > more/g && printf '#!/bin/sh\n' > inst.sh && chmod +x inst.sh && printf 'installer = "inst.sh"\n' > tests/LANDING-deploy.toml && git add -A && git commit -qm i && git push -q origin main \
  && git checkout -q track/x && git merge -q main && echo v > svc/u && git add -A && git commit -qm v && git push -q origin track/x && git checkout -q main)
printf '#!/bin/sh\n' > "$T/fb/systemctl"; chmod +x "$T/fb/systemctl"
echo 1 > "$T/check.rc"; run >/dev/null; echo 0 > "$T/check.rc"
swap "$(git -C "$T/dev/r" rev-parse main:svc)" "$(git -C "$T/dev/r" rev-parse track/x:svc)"
swap "$(git -C "$T/dev/r" rev-parse main:more)" "$(printf '100644 blob %s\tnever-merged\n' "$(blob e)" | git -C "$T/dev/r" mktree)"
rc=$(run)
t 'the restart list is the sealed diff: a swapped subtree neither hides a merged file nor adds one GitHub never merged' "$rc:$(tr '\n' ' ' < "$T/restart-for")" '0:svc/u x.txt '

# one git call fails or is meddled with; $1 the pattern, $2 what it runs first
gitfake(){ local real; real=$(command -v git); printf '#!/bin/sh\ncase "$*" in *"%s"*) %s ;; esac\nexec "%s" "$@"\n' "$1" "${2//\$real/$real}" "$real" > "$T/fb/git"; chmod +x "$T/fb/git"; }
fx catchup-unread; (cd "$T/dev/r" && echo b > b.txt && git add b.txt && git commit -qm b && git push -q origin main); gitfake 'merge-base --is-ancestor' 'exit 128'
t 'a catch-up that will not read sealed holds: queued, nothing checked or merged' "$(run):$(calls check):$(calls merge):$(tail -1 "$T/out" | grep -c 'would not read sealed')" '3:0:0:1'
fx tree-unread; gitfake 'read-tree -m -u' 'exit 1'
t 'a tree that will not write out sealed holds: queued, nothing checked or merged' "$(run):$(calls check):$(calls merge):$(tail -1 "$T/out" | grep -c 'would not read sealed')" '3:0:0:1'
fx diverged; (cd "$T/dev/r" && echo l > local.txt && git add -A && git commit -qm local); was=$(git -C "$T/dev/r" rev-parse HEAD)
t 'a checkout with a commit the remote lacks is not below the tip: the deploy refuses and keeps the commit' "$(run):$(calls merge):$(grep -c 'DEPLOY REFUSED' "$T/out"):$(git -C "$T/dev/r" rev-parse HEAD)" "0:1:1:$was"
fx stat-only; (cd "$T/dev/r" && git checkout -q track/x && git merge -q main && echo mine > a.txt && git add -A && git commit -qm a && git push -q origin track/x && git checkout -q main); x=$(tip track/x); touch -d 2001-01-01 "$T/dev/r/a.txt"
t 'a file touched but not changed is not dirt: the refresh lets the deploy through' "$(run):$(grep -c 'DEPLOY REFUSED' "$T/out"):$(git -C "$T/dev/r" rev-parse HEAD)" "0:0:$x"
fx head-moved; moved=$(git -C "$T/dev/r" commit-tree -p main -m other 'main^{tree}'); gitfake 'dev/r update-ref refs/heads/main' "\$real -C $T/dev/r update-ref refs/heads/main $moved"
t 'a branch that moves before the update-ref is not overwritten: the old value holds, and the deploy refuses' "$(run):$(grep -c 'DEPLOY REFUSED' "$T/out"):$(git -C "$T/dev/r" rev-parse refs/heads/main)" "0:1:$moved"

fx ci-stuck; echo 1 > "$T/workflows"; touch "$T/ci.hang"
s0=$SECONDS; rc=$(CC_MERGE_CI_LIMIT=1 run); s=$((SECONDS - s0))
t 'GitHub checks that never finish hand back with the reason at the limit: nothing merged' "$rc:$([ "$s" -lt 20 ] && echo quick):$(calls merge):$(tail -1 "$T/out" | grep -c 'had not finished after 1s')" '1:quick:0:1'

fx not-default; echo trunk > "$T/dflt"
t 'a PR whose base is not the default branch is refused, not merged' "$(run):$(calls merge):$(calls check)" '2:0:0'

fx no-grant; echo 1 > "$T/lands.rc"
t 'a repo without the standing grant (cc lands not 0) is refused inside cc-merge' "$(run):$(calls merge):$(calls 'gh pr read')" '2:0:0'

fx log-prune; echo 1 > "$T/check.rc"; for _ in 1 2 3 4 5 6 7; do run >/dev/null; done
t 'only the last few check logs are kept' "$(ls "$T/home/.cc/state/r"/merge-*.log | wc -l)" 5

# cc's hand `cc done` call, queue_pr, lifted out of core/bin/cc: the merge runs detached and the line names its log
fx detach; eval "$(sed -n '/^queue_pr(){/,/^  \[ -n "\$lo" \]/p' "$HERE/bin/cc")"; pr_slug(){ echo o/r; }
printf '#!/bin/sh\nsleep 3\necho "cc-merge: merged PR #$2"\n' > "$T/slow"; chmod +x "$T/slow"
s0=$SECONDS; out=$(HOME="$T/home" BOARD=false CC_MERGE="$T/slow" CC_MERGE_WAIT=1 PATH="$T/fb:$PATH" queue_pr r x "$T/dev/r" 7); s=$((SECONDS - s0))
lg=$(sed -n 's/^merging: PR #7 — cc-merge runs on its own; log //p' <<<"$out")
lg2=$(HOME="$T/home" BOARD=false CC_MERGE="$T/slow" CC_MERGE_WAIT=0 PATH="$T/fb:$PATH" queue_pr r x "$T/dev/r" 7 | sed -n 's/.*; log //p'); sleep 3
t 'a hand cc done starts cc-merge detached, returns, and names the log the merge then ends in' \
  "$([ "$s" -lt 3 ] && echo quick):${lg%-*}:$(cat "$lg.rc" 2>/dev/null):$(tail -1 "$lg" 2>/dev/null)" "quick:$T/home/.cc/state/r/cc-merge-7:0:cc-merge: merged PR #7"
t '…and a second hand run on the same PR writes a log of its own' "$([ -n "$lg2" ] && [ "$lg2" != "$lg" ] && echo own)" own
printf '#!/bin/sh\n[ "$1" = note ] && echo "$*" >> "%s/notes"\nexit 0\n' "$T" > "$T/board"; chmod +x "$T/board"
printf '#!/bin/sh\nsleep 2\necho "cc-merge: NOT MERGED — lander check is red"\nexit 1\n' > "$T/redrun"; printf '#!/bin/sh\nsleep 2\necho "cc-merge: fine"\n' > "$T/okrun"; chmod +x "$T/redrun" "$T/okrun"
lg=$(HOME="$T/home" BOARD="$T/board" CC_MERGE="$T/redrun" CC_MERGE_WAIT=0 PATH="$T/fb:$PATH" queue_pr r x "$T/dev/r" 7 | sed -n 's/.*; log //p'); for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do [ -s "$lg.rc" ] && break; sleep 1; done
t 'a hand run that ends red after cc done returned goes on the row, with the reason and the log' "$(cat "$T/notes" 2>/dev/null)" "note r x cc-merge ended 1 on PR #7: cc-merge: NOT MERGED — lander check is red (log $lg)"
: > "$T/notes"; lg=$(HOME="$T/home" BOARD="$T/board" CC_MERGE="$T/okrun" CC_MERGE_WAIT=0 PATH="$T/fb:$PATH" queue_pr r x "$T/dev/r" 7 | sed -n 's/.*; log //p'); for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do [ -s "$lg.rc" ] && break; sleep 1; done
t '…and one that ends well writes no note' "$(cat "$lg.rc"):$(wc -c < "$T/notes")" 0:0

echo "cc-merge selfcheck: $((n - f))/$n passed"; [ "$f" = 0 ]
