# shellcheck shell=bash disable=SC2154,SC2034
# cc-checkpoint's selfcheck cases, moved out of bin/cc-checkpoint. That tool's selfcheck() sources this file, whose
# definition replaces it, and then calls it: the cases run in the tool's own shell, with its functions and
# globals, as they did when the body sat there. SC2154/SC2034 are off because those globals live in bin/cc-checkpoint.

selfcheck(){   # the pick_remote rule, on fixtures of its own: a HOME, workspaces and repos it builds here, and
  # a cc-gh-token that RECORDS what it was asked to create instead of creating anything. No repository of this
  # box's is read, no token is minted, nothing reaches GitHub and no directory outside the temp dir is written.
  local n=0 f=0 out rc d bin
  k(){ n=$((n+1)); if [ "$1" = 0 ]; then echo "  ok   $2"; else echo "  FAIL $2 — $3"; f=$((f+1)); fi; }
  eq(){ k "$([ "$2" = "$3" ] && echo 0 || echo 1)" "$1" "got '$2', wanted '$3'"; }
  T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
  HOME="$T/home"; export HOME GIT_CONFIG_GLOBAL="$T/gitconfig" GIT_CONFIG_SYSTEM=/dev/null
  bin="$T/bin"; mkdir -p "$bin" "$HOME/.cc/worktrees" "$HOME/dev"
  # Every case runs as if fenced (loopback only), so a push at a fixture's example.test url fails its lookup at once
  # wherever this runs, rather than waiting out RESOLVE_WAITS on a host; the resolve cases below give themselves an uplink.
  printf 'Inter-|\n face |\n    lo: 0\n' > "$T/net-lo"; printf 'Inter-|\n face |\n    lo: 0\n  eth0: 0\n' > "$T/net-up"
  NET_DEV="$T/net-lo"; CC_NET_DEV="$T/net-lo"; export CC_NET_DEV
  cp "$(readlink -f "$0")" "$bin/cc-checkpoint"   # a COPY: a symlink resolves back to core/bin, and the stubs beside it would never be reached
  CALLS="$T/calls"; NOTES="$T/notes"; DEFS="$T/defaults"; RACE="$T/race"; ROWS="$T/rows"; UPACK="$T/upack"
  export CALLS NOTES DEFS RACE ROWS UPACK; : > "$UPACK"
  # `default` stands in for GitHub the way `create` does, and records into a file of its own so the create cases
  # above still read a $CALLS with one line in it. BARE, when the case sets it, makes `create` a real bare repo the
  # seeding below can actually push into.
  cat > "$bin/cc-gh-token" <<'SH'
#!/usr/bin/env bash
if [ "$1" = default ]; then printf '%s\n' "$*" >> "$DEFS"
  [ -z "${CC_NODEFAULT:-}" ] || { echo "GitHub refused" >&2; exit 1; }
  git -C "$BARE/$3.git" symbolic-ref HEAD "refs/heads/$4" 2>/dev/null; exit 0; fi
printf '%s\n' "$*" >> "$CALLS"
# $RACE = "<remote url> <worktree>": the member's live session committing WHILE the host pushes. gitargs is asked for
# the credential inside lease_push, after the sweep read HEAD and before the push goes out, so a commit made here
# lands in exactly that window — and only for the project whose url is named, since a sweep asks for many.
if [ "$1" = gitargs ] && [ -s "${RACE:-/dev/null}" ]; then
  read -r ru rw < "$RACE"
  if [ "$2" = "$ru" ]; then : > "$RACE"
    echo race >> "$rw/work.txt"; git -C "$rw" add -A >/dev/null 2>&1
    git -C "$rw" -c user.name=t -c user.email=t@t commit -q -m "a commit made while the host was pushing" >/dev/null 2>&1
  fi
fi
# $UPACK names a stand-in for the REMOTE's upload-pack, handed to git the way a credential is. Every read of the
# remote inside the push path goes through it — lease_refresh's fetch and remote_gone's ls-remote — so a case can
# make the remote lose the branch, or stop answering, between this worktree's plain push and its leased one.
if [ "$1" = gitargs ] && [ -s "${UPACK:-/dev/null}" ]; then printf -- '-c\nremote.origin.uploadpack=%s\n' "$(cat "$UPACK")"; fi
[ "$1" = create ] || exit 0
[ -z "${CC_FAIL:-}" ] || { echo "GitHub refused to create $3" >&2; exit 1; }
u="https://example.test/org/$3.git"; [ -z "${BARE:-}" ] || { git init -q --bare "$BARE/$3.git"; u="$BARE/$3.git"; }
rn=origin; [ -z "$(git remote 2>/dev/null)" ] || rn="$3"   # cc-gh-token's own rule: a workspace's FIRST repository is its origin
git remote add "$rn" "$u" 2>/dev/null
echo "https://example.test/org/$3"
SH
  # `base` is the board answering what the project's base branch is, and the REAL cc-board answers it, on a real
  # board under this fixture's HOME (`setbase` below writes one). A stub answering it would prove the stub: this
  # file called `base` for a whole PR before cc-board had the subcommand (review of #230). Every other subcommand
  # is recorded instead of run — the board-note cases read $NOTES — except `get`, which answers a row the landing
  # cases wrote under $ROWS/<h>/<t>/<field> (`row` below): a status and a PR url, nothing else.
  REALBIN="$BIN"; export REALBIN
  printf '#!/usr/bin/env bash\n[ "$1" = base ] && exec "$REALBIN/cc-board" "$@"\n[ "$1" = get ] && { cat "$ROWS/$2/$3/$4" 2>/dev/null; exit 0; }\nprintf "%%s\\n" "$*" >> "$NOTES"\n' > "$bin/cc-board"
  setbase(){ "$BIN/cc-board" init "$1" "$HOME/dev/$1" "$2" >/dev/null; }   # what the board records as this repo's base
  nobase(){ rm -f "$HOME/.cc/boards/$1.json"; }                            # …and back to a repo with no board at all
  printf '#!/usr/bin/env bash\nexit 0\n' > "$bin/cc-config"   # the commit cases below ask it for a git identity; the fixture's gitconfig has one
  chmod +x "$bin/cc-gh-token" "$bin/cc-board" "$bin/cc-config"
  printf '[user]\n\tname = t\n\temail = t@t\n' > "$T/gitconfig"
  ws(){ mkdir -p "$HOME/dev/$1/.cc"; : > "$HOME/dev/$1/.cc/member-workspace"; }   # the marker IS the workspace
  mkwt(){   # $1 <repo>/<track> (or an absolute path, for a worktree that is not one of ours), then name/url pairs
    local p="$1"; shift; case "$p" in /*) ;; *) p="$HOME/.cc/worktrees/$p" ;; esac
    mkdir -p "$p/.cc"; git init -q "$p" 2>/dev/null
    while [ "$#" -gt 1 ]; do git -C "$p" remote add "$1" "$2"; shift 2; done
    printf '%s\n' "$p"; }
  run(){ : > "$CALLS"; : > "$NOTES"; ( cd "$1" && env CC_FAIL="${2:-}" "$bin/cc-checkpoint" --remote 2>/dev/null ); }
  ws ws1; ws ws2
  # NOT a member workspace, and it has a remote named after the track: origin still wins, and nothing is ever
  # created for it. The kept case and the suppressed one in one fixture (review of #214: this rule ran first
  # and so applied to every repo on the box).
  d=$(mkwt myrepo/t1 origin https://example.test/org/myrepo.git t1 https://example.test/org/t1.git)
  printf 'myrepo\nt1\n' > "$d/.cc/track"
  eq "plain repo: origin, not the remote named after the track" "$(run "$d")" origin
  eq "plain repo: nothing is created for it" "$(cat "$CALLS")" ""
  # A member workspace's project, with its own repository already wired up: that one, not the workspace's origin.
  d=$(mkwt ws1/proj1 origin https://example.test/org/first.git proj1 https://example.test/org/proj1.git)
  printf 'ws1\nproj1\n' > "$d/.cc/track"
  eq "workspace project: its own remote is NOT taken when its url is not origin's: origin" "$(run "$d")" origin
  eq "workspace project: nothing is created when it has one" "$(cat "$CALLS")" ""
  irun(){ : > "$CALLS"; ( cd "$1" && env CC_MEMBER_SANDBOX=1 "$bin/cc-checkpoint" --remote 2>/dev/null; echo "rc=$?" ); }
  # origin=A and a track-named remote=B: origin, nothing created, and one stderr line naming the remote and its url —
  # ONCE: this runs every Stop hook and every sweep tick, so the same remote and url are not said again (review of #1031).
  said(){ ( cd "$1" && "$bin/cc-checkpoint" --remote 2>&1 >/dev/null | grep -c "remote $2 (.*) is not origin" ); }
  rm -f "${d:?}/.cc/own-remote.said"
  eq "workspace project: the contradicting remote is named on stderr" "$(said "$d" proj1)" 1
  k "$(grep -q 'remote proj1 (example.test/org/proj1) is not origin' "$d/.cc/own-remote.said" && echo 0 || echo 1)" "…naming the remote and its url" "$(cat "$d/.cc/own-remote.said" 2>/dev/null)"
  eq "…and not again on the next turn" "$(said "$d" proj1)" 0
  git -C "$d" remote set-url proj1 https://example.test/org/proj1b.git
  eq "…but a different url for it is said again" "$(said "$d" proj1)" 1
  # …by its url_key only: a url can carry a token, and this line is kept in .cc and printed on every hook's stderr.
  d=$(mkwt ws1/tk origin https://example.test/org/first.git tk https://bot:SECRETTOKEN8@example.test/org/tk.git); printf 'ws1\ntk\n' > "$d/.cc/track"
  tko=$( cd "$d" && "$bin/cc-checkpoint" --remote 2>&1 >/dev/null )
  k "$(grep -q 'remote tk (example.test/org/tk) is not origin' <<<"$tko" && ! grep -q SECRETTOKEN8 <<<"$tko" && ! grep -q SECRETTOKEN8 "$d/.cc/own-remote.said" && echo 0 || echo 1)" "token: the contradicting remote is named without its password" "$tko $(cat "$d/.cc/own-remote.said" 2>/dev/null)"
  # THE PUSH DESTINATIONS, not the fetch url (review of #1031): a track-named remote with origin's url and a pushurl
  # elsewhere, or a second pushurl elsewhere, still sends the branch to another repository. Origin, and said.
  d=$(mkwt ws1/pu1 origin https://example.test/org/first.git pu1 https://example.test/org/first.git); printf 'ws1\npu1\n' > "$d/.cc/track"
  git -C "$d" remote set-url --push pu1 https://example.test/other/pu1.git
  eq "own remote with origin's url but a pushurl elsewhere: origin" "$(run "$d")" origin
  rm -f "${d:?}/.cc/own-remote.said"; eq "…and it is said" "$(said "$d" pu1)" 1
  eq "…and inside the boundary it is origin too" "$(irun "$d" | tr '\n' ' ')" "origin rc=0 "
  d=$(mkwt ws1/pu2 origin https://example.test/org/first.git pu2 https://example.test/org/first.git); printf 'ws1\npu2\n' > "$d/.cc/track"
  git -C "$d" remote set-url --add --push pu2 https://example.test/org/first.git
  git -C "$d" remote set-url --add --push pu2 https://example.test/other/pu2.git
  eq "own remote whose second pushurl is elsewhere: origin" "$(run "$d")" origin
  rm -f "${d:?}/.cc/own-remote.said"; eq "…and it is said" "$(said "$d" pu2)" 1
  d=$(mkwt ws1/pu3 origin https://example.test/org/first.git pu3 https://example.test/org/first.git); printf 'ws1\npu3\n' > "$d/.cc/track"
  git -C "$d" remote set-url --push pu3 git@example.test:org/first.git
  eq "own remote whose pushurl is origin's repository in another spelling: taken" "$(run "$d")" pu3
  # …but a track-named remote that IS origin's repository in another spelling is taken.
  n=0; for sp in https://example.test/org/first.git/ https://EXAMPLE.test/org/first git@example.test:org/first.git ssh://git@example.test/org/first.git; do
    n=$((n+1)); d=$(mkwt ws1/sp$n origin https://example.test/org/first.git sp$n "$sp"); printf 'ws1\nsp%s\n' "$n" > "$d/.cc/track"
    eq "workspace project: own remote spelled $sp is origin's repository: taken" "$(run "$d")" "sp$n"
    rm -f "${d:?}/.cc/own-remote.said"
    eq "…and inside the boundary it is origin, no complaint" \
      "$( ( cd "$d" && env CC_MEMBER_SANDBOX=1 "$bin/cc-checkpoint" --remote 2>"$T/sp.err"; echo "rc=$?" ) | tr '\n' ' ')|$(grep -c 'is not origin' "$T/sp.err")" "origin rc=0 |0"
  done
  # The workspace's FIRST project is wired up as `origin` (cc-gh-token create), so origin IS that project's
  # repository when it carries the project's name — and nothing is created a second time.
  d=$(mkwt ws1/proj2 origin https://example.test/org/proj2.git)
  printf 'ws1\nproj2\n' > "$d/.cc/track"
  eq "workspace project: origin when origin is this project's repository" "$(run "$d")" origin
  eq "workspace project: and nothing created for it" "$(cat "$CALLS")" ""
  # A workspace project with no repository at all: one is made for it, the board hears once, and the push has
  # somewhere to go. This workspace has no remote either, so its first repository is `origin`.
  d=$(mkwt ws2/proj3); printf 'ws2\nproj3\n' > "$d/.cc/track"
  eq "workspace project with no remote: a repository is created for it" "$(run "$d")" origin
  eq "created for the workspace and project that own it" "$(cat "$CALLS")" "create ws2 proj3"
  k "$(grep -q 'github: created https://example.test/org/proj3' "$NOTES" && echo 0 || echo 1)" "the board is told which repository was made" "$(cat "$NOTES")"
  # A workspace that already has an origin: a track with no remote of its own is a task on that project, so it goes
  # to origin and NOTHING is created — a repository made here once took a finished task's whole history (2026-10-05).
  d=$(mkwt ws1/proj4 origin https://example.test/org/first.git); printf 'ws1\nproj4\n' > "$d/.cc/track"
  eq "a task track of a workspace with an origin: delivered to that origin" "$(run "$d")" origin
  eq "…and no repository is created for it" "$(cat "$CALLS")" ""
  # INSIDE THE BOUNDARY (the member's own `cc done`): origin, never the track-named remote, never a repository
  # created. Only a workspace with no origin is nowhere to push, rc=1, which `cc done` reports as undelivered for
  # the host (review of #965).
  d=$(mkwt ws1/proj6 origin https://example.test/org/first.git proj6 https://example.test/org/proj6.git); printf 'ws1\nproj6\n' > "$d/.cc/track"
  eq "inside, a second project with its own remote elsewhere: origin, never its remote" "$(irun "$d" | tr '\n' ' ')|$(cat "$CALLS")" "origin rc=0 |"
  d=$(mkwt ws1/proj9 origin https://example.test/org/first.git); printf 'ws1\nproj9\n' > "$d/.cc/track"
  eq "inside, a task track with no remote of its own: origin, as the host would, and nothing created" "$(irun "$d" | tr '\n' ' ')|$(cat "$CALLS")" "origin rc=0 |"
  d=$(mkwt ws1/proj13 origin https://example.test/org/first.git proj13 https://example.test/org/first.git); printf 'ws1\nproj13\n' > "$d/.cc/track"
  eq "inside, a task track whose own remote is origin's repository (how they were bound by hand): origin" "$(irun "$d" | tr '\n' ' ')|$(cat "$CALLS")" "origin rc=0 |"
  d=$(mkwt ws1/proj10 origin https://example.test/org/proj10.git); printf 'ws1\nproj10\n' > "$d/.cc/track"
  eq "inside, the workspace's own project (origin named after it, nothing else): delivered to origin" "$(irun "$d" | tr '\n' ' ')|$(cat "$CALLS")" "origin rc=0 |"
  d=$(mkwt ws1/proj11 origin https://example.test/org/proj11.git proj11 https://example.test/org/proj11.git); printf 'ws1\nproj11\n' > "$d/.cc/track"
  eq "inside, a track-named remote that agrees with origin: origin" "$(irun "$d" | tr '\n' ' ')|$(cat "$CALLS")" "origin rc=0 |"
  d=$(mkwt ws1/proj12 origin https://example.test/org/proj12.git proj12 https://example.test/org/other.git); printf 'ws1\nproj12\n' > "$d/.cc/track"
  eq "inside, a track-named remote elsewhere than origin: origin, never that remote" "$(irun "$d" | tr '\n' ' ')|$(cat "$CALLS")" "origin rc=0 |"
  d=$(mkwt ws1/proj7 proj7 https://example.test/org/proj7.git); printf 'ws1\nproj7\n' > "$d/.cc/track"
  eq "inside, a track-named remote and no origin: nowhere to push, and nothing created" "$(irun "$d" | tr '\n' ' ')|$(cat "$CALLS")" "rc=1 |"
  d=$(mkwt ws1/proj8); printf 'ws1\nproj8\n' > "$d/.cc/track"
  eq "inside, no remote at all: nowhere to push, and nothing created" "$(irun "$d" | tr '\n' ' ')|$(cat "$CALLS")" "rc=1 |"
  # A TRACK THE HOST BOUND to its project's remote delivers THERE, host and sandbox alike: a member project
  # (2026-10-12) had origin=another project and a remote named after the track, pushed to origin and opened its PR
  # there. The binding is cc-track.<track>.remote in ~/dev/<ws>/.git/config, the file the member cannot write.
  ws wsb; git init -q "$HOME/dev/wsb"
  git -C "$HOME/dev/wsb" remote add origin https://example.test/org/first.git
  git -C "$HOME/dev/wsb" remote add projb https://example.test/org/projb.git
  d=$(mkwt wsb/projb origin https://example.test/org/first.git projb https://example.test/org/projb.git); printf 'wsb\nprojb\n' > "$d/.cc/track"
  eq "unbound, a track-named remote elsewhere is not taken on the host: origin" "$(run "$d")" origin
  eq "…nor inside the boundary" "$(irun "$d" | tr '\n' ' ')" "origin rc=0 "
  out=$( cd "$T" && "$bin/cc-checkpoint" bind wsb projb 2>&1 ); rc=$?
  eq "bind on the host records the binding" "$rc|$(git config --file "$HOME/dev/wsb/.git/config" --get cc-track.projb.remote)" "0|projb"
  eq "bound: the host pushes to the project's own remote" "$(run "$d")|$(cat "$CALLS")" "projb|"
  eq "bound: inside the boundary too, and nothing created" "$(irun "$d" | tr '\n' ' ')|$(cat "$CALLS")" "projb rc=0 |"
  rm -f "$d/.cc/own-remote.said"; eq "bound: and no 'is not origin' complaint" "$( ( cd "$d" && "$bin/cc-checkpoint" --remote 2>&1 >/dev/null ) | grep -c 'is not origin')" 0
  # …kept to the HOST's word: a binding the worktree's own config claims (the member's to write) is not one, and a
  # member who names a new track after another project's remote reaches origin, not that repository (review of #965).
  d=$(mkwt wsb/projc origin https://example.test/org/first.git projc https://example.test/org/projc.git); printf 'wsb\nprojc\n' > "$d/.cc/track"
  git -C "$d" config cc-track.projc.remote projc
  eq "a binding written in the worktree's own config is not taken: origin" "$(run "$d")" origin
  eq "…nor inside the boundary" "$(irun "$d" | tr '\n' ' ')" "origin rc=0 "
  d=$(mkwt wsb/projd origin https://example.test/org/first.git projb https://example.test/org/projb.git); printf 'wsb\nprojd\n' > "$d/.cc/track"
  eq "another track does not inherit projb's binding: origin" "$(run "$d")|$(irun "$d" | tr '\n' ' ')" "origin|origin rc=0 "
  # bind refuses inside the boundary, a remote the workspace does not have, and a directory that is no workspace
  out=$( cd "$T" && CC_MEMBER_SANDBOX=1 "$bin/cc-checkpoint" bind wsb projc 2>&1 ); rc=$?
  eq "bind refuses inside the boundary, and writes nothing" "$rc|$(git config --file "$HOME/dev/wsb/.git/config" --get cc-track.projc.remote)" "1|"
  out=$( cd "$T" && "$bin/cc-checkpoint" bind wsb projc nosuch 2>&1 ); rc=$?
  eq "bind refuses a remote the workspace does not have" "$rc|$(git config --file "$HOME/dev/wsb/.git/config" --get cc-track.projc.remote)" "1|"
  out=$( cd "$T" && "$bin/cc-checkpoint" bind myrepo t1 2>&1 ); rc=$?
  eq "bind refuses a repo that is not a member workspace" "$rc" 1
  # A TOKEN IN THE REMOTE'S URL stays out of the confirmation, which names the repository by its url_key (review of #1137).
  git -C "$HOME/dev/wsb" remote add projs https://bot:SECRET@example.test/org/projs.git
  out=$( cd "$T" && "$bin/cc-checkpoint" bind wsb projs 2>&1 ); rc=$?
  eq "bind with a token in the remote's url still binds it" "$rc|$(git config --file "$HOME/dev/wsb/.git/config" --get cc-track.projs.remote)" "0|projs"
  eq "…and its confirmation prints no token" "$(grep -c SECRET <<<"$out")|$(grep -c 'delivers to projs (example.test/org/projs)' <<<"$out")" "0|1"
  # THE MIGRATION (review of #1137), in the reported shape: a workspace wired before tracks were bound. origin is one
  # project, a remote named after its own repository is another, a mirror is named otherwise, an alias is origin's
  # repository under a task's name, and one track the host already bound elsewhere. --wired binds the project alone,
  # and its track then delivers there on both sides.
  ws wsm; git init -q "$HOME/dev/wsm"
  git -C "$HOME/dev/wsm" remote add origin https://example.test/org/first.git
  git -C "$HOME/dev/wsm" remote add projm https://bot:SECRET@example.test/org/projm.git
  git -C "$HOME/dev/wsm" remote add mirm https://example.test/org/wsm-mirm.git
  git -C "$HOME/dev/wsm" remote add taskm https://example.test/org/first.git
  git -C "$HOME/dev/wsm" remote add kept https://example.test/org/kept.git
  git config --file "$HOME/dev/wsm/.git/config" cc-track.kept.remote mirm
  d=$(mkwt wsm/projm origin https://example.test/org/first.git projm https://example.test/org/projm.git); printf 'wsm\nprojm\n' > "$d/.cc/track"
  eq "before the migration, a project wired with its own remote still delivers to origin" "$(run "$d")|$(irun "$d" | tr '\n' ' ')" "origin|origin rc=0 "
  out=$( cd "$T" && "$bin/cc-checkpoint" bind wsm --wired 2>&1 ); rc=$?
  eq "--wired binds the remote named after its own repository, and nothing else" "$rc|$(git config --file "$HOME/dev/wsm/.git/config" --get-regexp '^cc-track\.' | tr '\n' ' ')" "0|cc-track.kept.remote mirm cc-track.projm.remote projm "
  eq "…says what it bound by url_key, with no token" "$(grep -c 'track projm of wsm delivers to projm (example.test/org/projm)' <<<"$out")|$(grep -c SECRET <<<"$out")" "1|0"
  eq "migrated: the host pushes to the project's own remote" "$(run "$d")|$(cat "$CALLS")" "projm|"
  eq "migrated: inside the boundary too, and nothing created" "$(irun "$d" | tr '\n' ' ')|$(cat "$CALLS")" "projm rc=0 |"
  out=$( cd "$T" && "$bin/cc-checkpoint" bind wsm --wired 2>&1 ); rc=$?
  eq "--wired run again binds nothing new and says so" "$rc|$out" "0|cc-checkpoint bind: nothing in wsm left to bind"
  out=$( cd "$T" && CC_MEMBER_SANDBOX=1 "$bin/cc-checkpoint" bind wsm --wired 2>&1 ); rc=$?
  eq "--wired refuses inside the boundary" "$rc" 1
  # THE ONE THAT MATTERS. .cc/track is bound read-WRITE into the member session, so it is the member's word;
  # the worktree's path is not. A .cc/track naming another workspace and a free name must not become an
  # org-admin call for that name (review of #214).
  d=$(mkwt ws1/proj5); printf 'ws2\nvictim\n' > "$d/.cc/track"
  out=$(run "$d")
  eq "a lying .cc/track creates the path's own project" "$(cat "$CALLS")" "create ws1 proj5"
  eq "and the lying .cc/track's remote is not what is pushed to" "$out" origin
  # A worktree that is not under ~/.cc/worktrees cannot be trusted to name anything: origin only, nothing made.
  d=$(mkwt "$T/loose"); printf 'ws1\nloose\n' > "$d/.cc/track"
  out=$(run "$d"); rc=$?
  eq "a worktree outside ~/.cc/worktrees: nothing is created for it" "$(cat "$CALLS")" ""
  k "$([ "$rc" = 1 ] && [ -z "$out" ] && echo 0 || echo 1)" "and with no origin it answers that there is nowhere to push" "rc=$rc out='$out'"
  # A creation that could not happen leaves its reason where the next turn replaces it. With no origin there is
  # nowhere else to push; a workspace with an origin never reaches the creation at all (proj4 above).
  d=$(mkwt ws2/proj7); printf 'ws2\nproj7\n' > "$d/.cc/track"
  out=$(run "$d" 1); rc=$?
  k "$([ "$rc" = 1 ] && [ -z "$out" ] && echo 0 || echo 1)" "a failed creation with no origin: nowhere to push, and it says so" "rc=$rc out='$out'"
  k "$(grep -q 'refused to create proj7' "$d/.cc/create.err" && echo 0 || echo 1)" "and leaves the reason in .cc/create.err" "$(cat "$d/.cc/create.err" 2>/dev/null)"
  # ── the branch ends up in the project's repository and is taken out of the other projects' ──────────
  bare(){ git init -q --bare "$T/$1.git"; printf '%s\n' "$T/$1.git"; }
  mkproj(){   # $1 <ws>/<track>, then name/url pairs → a worktree on track/<track> carrying one commit of its own
    local p t; p=$(mkwt "$@"); t=${1#*/}
    printf '%s\n%s\n' "${1%%/*}" "$t" > "$p/.cc/track"
    git -C "$p" symbolic-ref HEAD "refs/heads/track/$t"
    echo "$t" > "$p/work.txt"; git -C "$p" add -A
    git -C "$p" -c user.name=t -c user.email=t@t commit -q -m "$t"
    printf '%s\n' "$p"; }
  has(){ git ls-remote --heads "$1" "refs/heads/$2" 2>/dev/null | grep -q .; }
  mkproj_main(){   # like mkproj, but the branch is cut from a `main` that already carries the workspace's README — as a workspace's is
    local p t ws; p=$(mkwt "$@"); t=${1#*/}; ws=${1%%/*}
    printf '%s\n%s\n' "$ws" "$t" > "$p/.cc/track"
    git -C "$p" symbolic-ref HEAD refs/heads/main
    printf '# %s\n\nscratch workspace\n' "$ws" > "$p/README.md"; git -C "$p" add -A
    git -C "$p" -c user.name=t -c user.email=t@t commit -q -m inherited
    git -C "$p" checkout -q -b "track/$t"; echo "$t" > "$p/work.txt"; git -C "$p" add -A
    git -C "$p" -c user.name=t -c user.email=t@t commit -q -m "$t"
    printf '%s\n' "$p"; }
  # runp = a push from an ESTABLISHED track: the host already holds a lease for it (evict_elsewhere fires only then;
  # a track with no host lease is the pre-move / never-pushed case, tested on its own below). The lease value does
  # not matter here — every push in this section is a fast-forward, so it is never consulted — only that it exists.
  runp(){ : > "$CALLS"; : > "$NOTES"; git -C "$1" rev-parse HEAD > "$1/.cc/pushed" 2>/dev/null; ( cd "$1" && "$bin/cc-checkpoint" --push >/dev/null 2>&1 ); }
  ws ws3
  # A workspace's first repository holding a second project's branch — the shape measured on a real workspace
  # on 2026-09-04. The branch is pushed to the project's own repository and then removed from that one.
  oa=$(bare ownA); ta=$(bare otherA)
  d=$(mkproj ws3/projA origin "$oa" stale "$ta"); git -C "$d" push -q stale track/projA
  runp "$d"
  k "$(has "$oa" track/projA && echo 0 || echo 1)" "the branch is in the project's own repository" "not on $oa"
  k "$(has "$ta" track/projA && echo 1 || echo 0)" "and is taken out of the other project's repository" "still on $ta"
  k "$(grep -q 'removed from' "$NOTES" && echo 0 || echo 1)" "the board is told what was removed" "$(cat "$NOTES")"
  # A tip over there that is NOT in this branch is somebody's work: it is left alone and named, never deleted.
  ob=$(bare ownB); tb=$(bare otherB)
  d=$(mkproj ws3/projB origin "$ob" stale "$tb")
  sb=$(mkwt "$T/strayB"); git -C "$sb" symbolic-ref HEAD refs/heads/track/projB
  echo stray > "$sb/stray.txt"; git -C "$sb" add -A; git -C "$sb" -c user.name=t -c user.email=t@t commit -q -m stray
  git -C "$sb" push -q "$tb" track/projB
  runp "$d"
  k "$(has "$ob" track/projB && echo 0 || echo 1)" "an unrelated tip elsewhere does not stop the push" "not on $ob"
  k "$(has "$tb" track/projB && echo 0 || echo 1)" "a tip that is not in this branch is left alone" "deleted from $tb"
  k "$(grep -q 'left alone' "$d/.cc/evict.err" && echo 0 || echo 1)" "and evict.err names the repository that still holds it" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  k "$([ -e "$d/.cc/push.err" ] && echo 1 || echo 0)" "and push.err, which means the push failed, is not written for it" "$(cat "$d/.cc/push.err" 2>/dev/null)"
  k "$(grep -c 'left alone' "$NOTES" | grep -qx 1 && echo 0 || echo 1)" "and the board hears it — the one case that needs a person" "$(cat "$NOTES")"
  ( cd "$d" && "$bin/cc-checkpoint" --push >/dev/null 2>&1 )   # the next turn, same shape: the board is not told again
  k "$(grep -c 'left alone' "$NOTES" | grep -qx 1 && echo 0 || echo 1)" "…once, not every turn" "$(cat "$NOTES")"
  # ONE repository under two remote names — how the owner binds a project to a repository he already had.
  # Compared by name, "the other remote" is the project's own and the branch is deleted the moment it lands.
  oc=$(bare ownC)
  d=$(mkproj ws3/projC origin "$oc/" projC "$oc")
  runp "$d"
  k "$(has "$oc" track/projC && echo 0 || echo 1)" "one repository under two remote names is not evicted from itself" "gone from $oc"
  k "$(grep -q 'removed from' "$NOTES" && echo 1 || echo 0)" "and nothing is reported as removed" "$(cat "$NOTES")"
  # …and under a spelling url_key CANNOT unify (a symlink here; ssh against https on GitHub): the delete goes
  # through, the project's own remote is asked, and the branch is put back (review of #217).
  oc2=$(bare ownC2); ln -s "$oc2" "$T/aliasC2.git"
  d=$(mkproj ws3/projC2 origin "$oc2" dup "$T/aliasC2.git")
  runp "$d"
  k "$(has "$oc2" track/projC2 && echo 0 || echo 1)" "a repository deleted from under itself gets its branch put back" "gone from $oc2"
  k "$(grep -q 'put back' "$d/.cc/evict.err" && echo 0 || echo 1)" "and evict.err names the duplicate remote" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  k "$(grep -q 'put back' "$NOTES" && echo 0 || echo 1)" "and so does the board" "$(cat "$NOTES")"
  ( cd "$d" && "$bin/cc-checkpoint" --push >/dev/null 2>&1 )   # the next turn: the duplicate is remembered, not cycled
  k "$(grep -qxF "$(same_key "$T/aliasC2.git")" "$d/.cc/evict.same" && echo 0 || echo 1)" "the duplicate remote is remembered in evict.same" "$(cat "$d/.cc/evict.same" 2>/dev/null)"
  k "$(grep -c 'put back' "$NOTES" | grep -qx 1 && echo 0 || echo 1)" "and is not deleted and put back again the turn after" "$(cat "$NOTES")"
  k "$(has "$oc2" track/projC2 && echo 0 || echo 1)" "and the branch is still in the project's own repository" "gone from $oc2"
  # A delete the other repository REFUSES (GitHub: its default branch; here receive.denyDeletes) is said, once.
  oi=$(bare ownI); ti=$(bare otherI); git -C "$ti" config receive.denyDeletes true
  d=$(mkproj ws3/projI origin "$oi" stale "$ti"); git -C "$d" push -q stale track/projI
  runp "$d"
  k "$(has "$ti" track/projI && echo 0 || echo 1)" "a refused delete leaves the branch where it was" "gone from $ti"
  k "$(grep -q 'refused' "$d/.cc/evict.err" && echo 0 || echo 1)" "and evict.err says the delete was refused" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  k "$(grep -c 'refused' "$NOTES" | grep -qx 1 && echo 0 || echo 1)" "and the board hears it" "$(cat "$NOTES")"
  # NEVER THE TRACK'S OWN DELIVERY (a member project's PR, closed three times on 2026-10-12 while the push went to
  # origin): the remote named after the track keeps the branch its PR stands on. A sibling remote with the same tip
  # in the same run is still emptied, so the rule is the name and not a broken eviction.
  oj=$(bare ownEvJ); tj=$(bare ownProjEvJ); sj=$(bare siblingEvJ)
  d=$(mkproj ws3/projJ origin "$oj" projJ "$tj" stale "$sj"); git -C "$d" push -q projJ track/projJ; git -C "$d" push -q stale track/projJ
  runp "$d"
  k "$(has "$oj" track/projJ && echo 0 || echo 1)" "an unbound track still delivers to origin" "not on $oj"
  k "$(has "$tj" track/projJ && echo 0 || echo 1)" "…and its branch is NOT deleted from the remote named after the track" "deleted from $tj"
  k "$(has "$sj" track/projJ && echo 1 || echo 0)" "…while a sibling project's repository is still tidied" "still on $sj"
  # BY PUSH DESTINATION, NEVER BY FETCH URL (lander, #1118). `push --delete` goes to a remote's pushurl, so who is
  # own, who is the mirror and what is probed are all asked of where each remote pushes, not of its url.
  # (a) the mirror's pushurl is the branch's real home and its url is a repository of no interest: another remote
  # reading that home is the mirror under another name, and the branch is not deleted from it.
  ws ws9; oq=$(bare ownPuQ); mq=$(bare mirPuQ); xq=$(bare elsePuQ)
  d=$(mkproj ws9/projQ origin "$oq" projQ "$xq" mirq "$mq"); git -C "$d" config remote.projQ.pushurl "$mq"
  git -C "$d" push -q projQ track/projQ; git -C "$d" rev-parse HEAD > "$d/.cc/mirrored"   # mirrored already, so no re-push hides a delete
  runp "$d"
  k "$(has "$mq" track/projQ && echo 0 || echo 1)" "pushurl: the mirror's push destination keeps the branch under another remote's name" "deleted from $mq"
  k "$(grep -q 'removed from' "$NOTES" && echo 1 || echo 0)" "pushurl: and nothing is reported as removed" "$(cat "$NOTES")"
  # (b) the project's own remote fetches from one repository and pushes to another; a sibling remote reading that
  # push destination is the project's own repository, and its branch is neither deleted nor deleted-and-put-back.
  orr=$(bare ownPuR); zr=$(bare readPuR)
  d=$(mkproj ws9/projR origin "$zr" sibr "$orr"); git -C "$d" config remote.origin.pushurl "$orr"
  git -C "$d" push -q "$zr" track/projR; runp "$d"
  k "$(has "$orr" track/projR && echo 0 || echo 1)" "pushurl: the own remote's push destination is not evicted through a sibling's name" "deleted from $orr"
  k "$(grep -q 'removed from\|put back' "$NOTES" && echo 1 || echo 0)" "pushurl: and nothing was deleted and put back either" "$(cat "$NOTES")"
  # (c) a genuine contaminated sibling whose url and pushurl differ: the branch is probed and deleted where the
  # sibling PUSHES, and the repository its url names is not touched (it holds somebody's tip of its own here).
  os=$(bare ownPuS); fs=$(bare fetchPuS); ps=$(bare pushPuS)
  d=$(mkproj ws9/projS origin "$os" sibs "$fs"); git -C "$d" config remote.sibs.pushurl "$ps"
  git -C "$d" push -q "$ps" track/projS
  ss=$(mkwt "$T/strayPuS"); git -C "$ss" symbolic-ref HEAD refs/heads/track/projS
  echo stray > "$ss/stray.txt"; git -C "$ss" add -A; git -C "$ss" -c user.name=t -c user.email=t@t commit -q -m stray
  git -C "$ss" push -q "$fs" track/projS; fss=$(git -C "$fs" rev-parse track/projS)
  runp "$d"
  k "$(has "$ps" track/projS && echo 1 || echo 0)" "pushurl: a contaminated sibling loses the branch at its push destination" "still on $ps"
  eq "pushurl: and the repository its fetch url names is left as it was" "$(git -C "$fs" rev-parse track/projS 2>/dev/null)" "$fss"
  k "$(grep -q 'removed from pushpus' "$NOTES" && echo 0 || echo 1)" "pushurl: and the board names the push destination" "$(cat "$NOTES")"
  # (d) a sibling with two pushurls, one of them the project's own: only the other one loses the branch.
  ot=$(bare ownPuT); pt=$(bare pushPuT)
  d=$(mkproj ws9/projT origin "$ot" sibt "$pt"); git -C "$d" config --add remote.sibt.pushurl "$pt"; git -C "$d" config --add remote.sibt.pushurl "$ot"
  git -C "$d" push -q "$pt" track/projT; runp "$d"
  k "$(has "$ot" track/projT && ! has "$pt" track/projT && echo 0 || echo 1)" "pushurl: of two push destinations only the sibling's loses the branch" "own=$(has "$ot" track/projT && echo y) sib=$(has "$pt" track/projT && echo y)"
  k "$(grep -q 'put back' "$NOTES" && echo 1 || echo 0)" "pushurl: and the project's own one was never deleted and put back" "$(cat "$NOTES")"
  # …AND ONLY WHERE GIT DOES NOT REWRITE THE URL AGAIN (security read of #1118). get-url has applied the rewrite
  # rules once; a url handed back to git is rewritten a second time, by pushInsteadOf for `push` and by insteadOf
  # for `ls-remote`. (e) Two chained pushInsteadOf rules (B->A, A->own) and a sibling whose url is B: the probe
  # asked A, the delete landed on the project's own repository, and the self-heal re-push closed its open PR.
  ou=$(bare ownPuU); au=$(bare aPuU); buu="$T/bPuU.git"
  d=$(mkproj ws9/projU origin "$ou" sibu "$buu"); git -C "$d" push -q "$au" track/projU
  git -C "$d" config "url.$au.pushInsteadOf" "$buu"; git -C "$d" config "url.$ou.pushInsteadOf" "$au"
  runp "$d"
  k "$(grep -q 'removed from\|put back' "$NOTES" && echo 1 || echo 0)" "rewrite: a delete git would send somewhere else is not made, nor put back" "$(cat "$NOTES")"
  k "$(grep -q 'is rewritten to' "$d/.cc/evict.err" 2>/dev/null && echo 0 || echo 1)" "rewrite: and evict.err says where the push would have gone" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  # (f) a sibling's pushurl that ls-remote rewrites again (insteadOf X->Y, Y->own): never probed, never deleted.
  ov=$(bare ownPuV); xv="$T/xPuV.git"; yv="$T/yPuV.git"
  d=$(mkproj ws9/projV origin "$ov" sibv "$T/nonePuV.git"); git -C "$d" config remote.sibv.pushurl "$xv"
  git -C "$d" config "url.$yv.insteadOf" "$xv"; git -C "$d" config --add "url.$ov.insteadOf" "$yv"
  runp "$d"
  k "$(grep -q 'removed from\|put back' "$NOTES" && echo 1 || echo 0)" "rewrite: a sibling url ls-remote reads elsewhere is not probed or deleted" "$(cat "$NOTES")"
  k "$(grep -q 'rewrites to another url when it reads it — left alone' "$d/.cc/evict.err" 2>/dev/null && echo 0 || echo 1)" "rewrite: and evict.err names it" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  # (g) the project's own push url is one ls-remote rewrites again, so the self-heal could not ask it: no eviction.
  og=$(bare ownPuG); qg=$(bare qPuG); rg=$(bare rPuG); sg=$(bare sibPuG)
  d=$(mkproj ws9/projG origin "$og" sibg "$sg"); git -C "$d" config remote.origin.pushurl "$T/pPuG.git"
  git -C "$d" config "url.$qg.insteadOf" "$T/pPuG.git"; git -C "$d" config --add "url.$rg.insteadOf" "$qg"
  git -C "$d" push -q "$og" track/projG; git -C "$d" push -q "$sg" track/projG
  runp "$d"
  k "$(has "$sg" track/projG && echo 0 || echo 1)" "rewrite: with its own url unaskable, nothing is taken out of a sibling" "deleted from $sg"
  k "$(grep -q 'could not be asked' "$d/.cc/evict.err" 2>/dev/null && echo 0 || echo 1)" "rewrite: and evict.err says why" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  # (h) a push url beginning with '-' is an option to git, not a url: `--upload-pack=<cmd>` ran <cmd> as the owner
  # when it was probed (security read of #1118). It is never handed to git, and it is said.
  ow=$(bare ownPuW); tw=$(bare sibPuW)
  d=$(mkproj ws9/projW origin "$ow" sibw "$tw"); git -C "$d" push -q "$tw" track/projW
  git -C "$d" config remote.sibw.pushurl "--upload-pack=touch $T/PWNED-ls #"; git -C "$d" config --add remote.sibw.pushurl "--receive-pack=touch $T/PWNED-push #"
  runp "$d"
  k "$([ -e "$T/PWNED-ls" ] || [ -e "$T/PWNED-push" ] && echo 1 || echo 0)" "dash: a push url that is really an option is never run" "$(printf '%s ' "$T"/PWNED-*)"
  k "$(grep -c "beginning with '-'" "$d/.cc/evict.err" 2>/dev/null | grep -qx 2 && echo 0 || echo 1)" "dash: and evict.err names each one" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  # (i) a sibling naming the MIRROR under a spelling url_key cannot unify (a symlink here) took the mirror's branch,
  # and nothing put it back, since .cc/mirrored already recorded that head (security read of #1118).
  ox=$(bare ownPuX); mx=$(bare mirPuX); ln -s "$mx" "$T/mirlinkPuX.git"
  d=$(mkproj ws9/projX origin "$ox" projX "$mx" sibx "$T/mirlinkPuX.git")
  git -C "$d" push -q projX track/projX; git -C "$d" rev-parse HEAD > "$d/.cc/mirrored"
  runp "$d"
  k "$(has "$mx" track/projX && echo 0 || echo 1)" "mirror alias: a delete through another spelling of the mirror is put back" "gone from $mx"
  k "$(grep -qxF "$(same_key "$T/mirlinkPuX.git")" "$d/.cc/evict.same" 2>/dev/null && echo 0 || echo 1)" "mirror alias: and that remote is remembered in evict.same" "$(cat "$d/.cc/evict.same" 2>/dev/null)"
  k "$(grep -q "mirror projX under another spelling" "$d/.cc/evict.err" 2>/dev/null && echo 0 || echo 1)" "mirror alias: and evict.err names the mirror" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  : > "$NOTES"; ( cd "$d" && "$bin/cc-checkpoint" --push >/dev/null 2>&1 )
  k "$(has "$mx" track/projX && ! grep -q 'put back\|removed from' "$NOTES" && echo 0 || echo 1)" "mirror alias: and the next turn neither deletes nor puts it back again" "$(cat "$NOTES")"
  # (j) a mirror that never got the branch does not make a real sibling its alias: the sibling is cleaned as ever.
  oy=$(bare ownPuY); my=$(bare mirPuY); sy=$(bare sibPuY)
  d=$(mkproj ws9/projY origin "$oy" projY "$my" siby "$sy"); git -C "$d" push -q "$sy" track/projY
  git -C "$d" rev-parse HEAD > "$d/.cc/mirrored"   # recorded, yet not there: what an emptied mirror looks like from here
  runp "$d"
  k "$(has "$sy" track/projY && echo 1 || echo 0)" "mirror alias: a sibling is still cleaned when the mirror never held the branch" "still on $sy"
  k "$(grep -qxF "$(same_key "$sy")" "$d/.cc/evict.same" 2>/dev/null && echo 1 || echo 0)" "mirror alias: and it is not mistaken for the mirror" "$(cat "$d/.cc/evict.same" 2>/dev/null)"
  # THE DRY RUN'S "To" LINE HAS NO USER IN IT (security read of #1118, round 3). git prints the url without its user
  # or password, so `git@host:path`, `ssh://git@host/…` and `https://user:TOKEN@host/…` never equalled it: an ssh
  # sibling was never cleaned again, and a url carrying a token went into evict.err and onto the board whole. A fake
  # ssh stands in for the network here: it ignores the host and every option and runs the command git hands it.
  printf '#!/usr/bin/env bash\nfor a; do c=$a; done; exec sh -c "$c"\n' > "$T/fakessh"; chmod +x "$T/fakessh"
  sshp(){ ( export GIT_SSH_COMMAND="$T/fakessh" GIT_SSH_VARIANT=ssh; runp "$1" ); }
  notok(){ ! grep -rq "$1" "$NOTES" "$2/.cc" 2>/dev/null; }   # $1 a password, $2 the worktree: in no note and no state file
  ws ws10
  # (k) the scp form, and (l) ssh:// with a user: both are cleaned as any other sibling, and the board names them.
  osk=$(bare ownSshK); ssk=$(bare sibSshK)
  d=$(mkproj ws10/projSK origin "$osk" sibk "git@localhost:$ssk"); git -C "$d" push -q "$ssk" track/projSK
  sshp "$d"
  k "$(has "$ssk" track/projSK && echo 1 || echo 0)" "ssh: a sibling in scp form (git@host:path) loses the branch" "still on $ssk: $(cat "$d/.cc/evict.err" 2>/dev/null)"
  k "$(grep -q 'removed from sibsshk' "$NOTES" && echo 0 || echo 1)" "ssh: and the board names it" "$(cat "$NOTES")"
  osl=$(bare ownSshL); ssl=$(bare sibSshL)
  d=$(mkproj ws10/projSL origin "$osl" sibl "ssh://git@localhost$ssl"); git -C "$d" push -q "$ssl" track/projSL
  sshp "$d"
  k "$(has "$ssl" track/projSL && echo 1 || echo 0)" "ssh: a sibling at ssh://git@host/path loses the branch" "still on $ssl: $(cat "$d/.cc/evict.err" 2>/dev/null)"
  k "$(grep -q 'removed from sibsshl' "$NOTES" && echo 0 || echo 1)" "ssh: and the board names it" "$(cat "$NOTES")"
  # (m) a password in a sibling's url: cleaned the same way, and the password is in no note and no file of .cc.
  osm=$(bare ownSshM); ssm=$(bare sibSshM)
  d=$(mkproj ws10/projSM origin "$osm" sibm "ssh://bot:SECRETTOKEN1@localhost$ssm"); git -C "$d" push -q "$ssm" track/projSM
  sshp "$d"
  k "$(has "$ssm" track/projSM && echo 1 || echo 0)" "token: a sibling whose url carries a password loses the branch" "still on $ssm: $(cat "$d/.cc/evict.err" 2>/dev/null)"
  k "$(notok SECRETTOKEN1 "$d" && echo 0 || echo 1)" "token: and the password is written nowhere" "$(grep -r SECRETTOKEN1 "$NOTES" "$d/.cc" 2>/dev/null)"
  # (n) as (e), the url push rewrites again carrying a password: left alone and said, without the password.
  osn=$(bare ownSshN); asn=$(bare aSshN); tsn="ssh://bot:SECRETTOKEN2@localhost$asn"
  d=$(mkproj ws10/projSN origin "$osn" sibn "$T/bSshN.git"); git -C "$d" push -q "$asn" track/projSN
  git -C "$d" config "url.$tsn.pushInsteadOf" "$T/bSshN.git"; git -C "$d" config "url.$osn.pushInsteadOf" "$tsn"
  sshp "$d"
  k "$(has "$asn" track/projSN && grep -q 'is rewritten to' "$d/.cc/evict.err" 2>/dev/null && echo 0 || echo 1)" "token: a delete push would send elsewhere is not made, and is said" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  k "$(notok SECRETTOKEN2 "$d" && echo 0 || echo 1)" "token: without the password" "$(grep -r SECRETTOKEN2 "$NOTES" "$d/.cc" 2>/dev/null)"
  # (o) as (f), a sibling's push url with a password that ls-remote rewrites again.
  oso=$(bare ownSshO); tso="ssh://bot:SECRETTOKEN3@localhost$T/xSshO.git"
  d=$(mkproj ws10/projSO origin "$oso" sibo "$T/noneSshO.git"); git -C "$d" config remote.sibo.pushurl "$T/pSshO.git"
  git -C "$d" config "url.$tso.insteadOf" "$T/pSshO.git"; git -C "$d" config --add "url.$oso.insteadOf" "$tso"
  sshp "$d"
  k "$(grep -q 'rewrites to another url when it reads it — left alone' "$d/.cc/evict.err" 2>/dev/null && echo 0 || echo 1)" "token: a sibling url ls-remote reads elsewhere is said" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  k "$(notok SECRETTOKEN3 "$d" && echo 0 || echo 1)" "token: without the password" "$(grep -r SECRETTOKEN3 "$NOTES" "$d/.cc" 2>/dev/null)"
  # (p) as (g), the project's own push url carries a password and ls-remote rewrites it again.
  osg=$(bare ownSshG); rsg=$(bare rSshG); ssg=$(bare sibSshG); tsg="ssh://bot:SECRETTOKEN4@localhost$osg"
  d=$(mkproj ws10/projSG origin "$osg" sibg "$ssg"); git -C "$d" config remote.origin.pushurl "$T/pSshG.git"
  git -C "$d" config "url.$tsg.insteadOf" "$T/pSshG.git"; git -C "$d" config --add "url.$rsg.insteadOf" "$tsg"
  git -C "$d" push -q "$ssg" track/projSG
  sshp "$d"
  k "$(has "$ssg" track/projSG && grep -q 'could not be asked' "$d/.cc/evict.err" 2>/dev/null && echo 0 || echo 1)" "token: with its own url unaskable nothing is taken, and that is said" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  k "$(notok SECRETTOKEN4 "$d" && echo 0 || echo 1)" "token: without the password" "$(grep -r SECRETTOKEN4 "$NOTES" "$d/.cc" 2>/dev/null)"
  # (q) a delete refused through a url with a password: said, with git's own words, without the password.
  osq=$(bare ownSshQ); ssq=$(bare sibSshQ); git -C "$ssq" config receive.denyDeletes true
  d=$(mkproj ws10/projSQ origin "$osq" sibq "ssh://bot:SECRETTOKEN5@localhost$ssq"); git -C "$d" push -q "$ssq" track/projSQ
  sshp "$d"
  k "$(has "$ssq" track/projSQ && grep -q 'refused' "$d/.cc/evict.err" 2>/dev/null && echo 0 || echo 1)" "token: a refused delete is said" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  k "$(notok SECRETTOKEN5 "$d" && echo 0 || echo 1)" "token: without the password" "$(grep -r SECRETTOKEN5 "$NOTES" "$d/.cc" 2>/dev/null)"
  # (r) a self-alias reached through a url with a password: put back, and evict.same remembers it by a hash of its
  # url_key, never the url. The rows above never reached this path, which is the only one that writes evict.same.
  osr=$(bare ownSshR); ln -s "$osr" "$T/aliasSshR.git"; tsr="ssh://bot:SECRETTOKEN6@localhost$T/aliasSshR.git"
  d=$(mkproj ws10/projSR origin "$osr" sibr "$tsr")
  sshp "$d"
  k "$(has "$osr" track/projSR && grep -q 'put back' "$NOTES" && echo 0 || echo 1)" "token: a self-alias with a password is put back" "$(cat "$NOTES")"
  eq "token: and evict.same holds only the hash of its url_key" "$(cat "$d/.cc/evict.same" 2>/dev/null)" "$(same_key "$tsr")"
  k "$(notok SECRETTOKEN6 "$d" && echo 0 || echo 1)" "token: and the password is written nowhere" "$(grep -r SECRETTOKEN6 "$NOTES" "$d/.cc" 2>/dev/null)"
  ( export GIT_SSH_COMMAND="$T/fakessh" GIT_SSH_VARIANT=ssh; : > "$NOTES"; cd "$d" && "$bin/cc-checkpoint" --push >/dev/null 2>&1 )
  k "$(has "$osr" track/projSR && ! grep -q 'put back\|removed from' "$NOTES" && echo 0 || echo 1)" "token: and the next turn does not cycle it" "$(cat "$NOTES")"
  # (s) an evict.same written before this, holding the raw url: still honoured, and rewritten to the hash.
  oss=$(bare ownSshS); ln -s "$oss" "$T/aliasSshS.git"; tss="ssh://bot:SECRETTOKEN7@localhost$T/aliasSshS.git"
  d=$(mkproj ws10/projSS origin "$oss" sibs "$tss"); git -C "$d" push -q "$oss" track/projSS; printf '%s\n' "$tss" > "$d/.cc/evict.same"
  sshp "$d"
  k "$(has "$oss" track/projSS && ! grep -q 'put back\|removed from' "$NOTES" && echo 0 || echo 1)" "legacy: a raw url in evict.same is still a known alias, never cycled" "$(cat "$NOTES")"
  eq "legacy: and it is rewritten to the hash, password and all gone" "$(cat "$d/.cc/evict.same" 2>/dev/null)" "$(same_key "$tss")"
  # …and git's words are cut free of a password before they are kept: a refusal or a mirror error quotes them.
  eq "token: a url's user and password are dropped from git's words" "$(no_userinfo <<<"fatal: unable to access 'https://bot:TOK@github.com/o/r.git/': x; git@host:o/r")" "fatal: unable to access 'https://github.com/o/r.git/': x; git@host:o/r"
  # …nor from the repository the track's PR is on (the board's pr url), under whatever remote name: kept while the
  # row names that PR, and tidied once it names another. Over ssh in the scp form, with ssh run from $T, so git
  # reaches the bare repository without rewriting the url, and its url_key (localhost/acme/prk) is the PR's repository.
  printf '#!/usr/bin/env bash\nfor a; do c=$a; done; cd "%s" && exec sh -c "$c"\n' "$T" > "$T/fakesshT"; chmod +x "$T/fakesshT"
  sshK(){ ( export GIT_SSH_COMMAND="$T/fakesshT" GIT_SSH_VARIANT=ssh; runp "$1" ); }
  ok=$(bare ownEvK); pk=$(bare acme/prK)
  d=$(mkproj ws10/projK origin "$ok" other "git@localhost:acme/prK.git"); git -C "$d" push -q "$pk" track/projK
  mkdir -p "$ROWS/ws10/projK"; echo https://localhost/acme/prK/pull/3 > "$ROWS/ws10/projK/pr"
  sshK "$d"
  k "$(has "$pk" track/projK && echo 0 || echo 1)" "the branch of the PR the row names is not deleted" "deleted from $pk: $(cat "$d/.cc/evict.err" 2>/dev/null)"
  echo https://localhost/acme/ownK/pull/1 > "$ROWS/ws10/projK/pr"
  sshK "$d"
  k "$(has "$pk" track/projK && echo 1 || echo 0)" "…and once the row's PR is elsewhere, that repository is tidied as any other" "still on $pk: $(cat "$d/.cc/evict.err" 2>/dev/null)"
  # Not a member workspace: its remotes are its own business and nothing is ever taken out of them.
  od=$(bare ownD); td=$(bare otherD)
  d=$(mkproj myrepo2/t2 origin "$od" t2 "$td"); git -C "$d" push -q t2 track/t2
  runp "$d"
  k "$(has "$od" track/t2 && echo 0 || echo 1)" "a plain repo still pushes to origin" "not on $od"
  k "$(has "$td" track/t2 && echo 0 || echo 1)" "and nothing is removed from its other remotes" "deleted from $td"
  # NO HOST LEASE, NO EVICTION (round 9 of #225). A track whose host lease predates the move to ~/.cc/push-state has
  # its evict.same orphaned in <wt>/.cc, which the host will not read; re-running the self-alias delete+repush would
  # close its open PR (the #217 hole). So the destructive path fires only on positive host state — a lease of our
  # own — never on its absence. Same self-alias shape as projC2, but with NO host lease: nothing is deleted, nothing
  # is put back, and the branch still reaches the project's own repository.
  oe1=$(bare ownE1); ln -s "$oe1" "$T/aliasE1.git"
  d=$(mkproj ws3/projE1 origin "$oe1" dup "$T/aliasE1.git")
  : > "$CALLS"; : > "$NOTES"; rm -f "$d/.cc/pushed"   # the absence case: the host holds no lease of its own for this track
  ( cd "$d" && "$bin/cc-checkpoint" --push >/dev/null 2>&1 )
  k "$(has "$oe1" track/projE1 && echo 0 || echo 1)" "no host lease: the branch still reaches the project's own repository" "not on $oe1"
  k "$([ -e "$d/.cc/evict.err" ] && echo 1 || echo 0)" "…and no eviction is attempted at all — no delete, no put-back" "$(cat "$d/.cc/evict.err" 2>/dev/null)"
  k "$(grep -q 'put back' "$NOTES" && echo 1 || echo 0)" "…so no delete+repush cycle can close an open PR" "$(cat "$NOTES")"
  # …and the very next run, now holding a lease of its own, heals the workspace as before.
  : > "$NOTES"; ( cd "$d" && "$bin/cc-checkpoint" --push >/dev/null 2>&1 )
  k "$(grep -q 'put back' "$NOTES" && echo 0 || echo 1)" "…and once a host lease is on record the self-alias is handled normally" "$(cat "$NOTES")"
  # ── the project's mirror: a track-named remote that is not origin's repository gets every commit, fast-forward only ──
  # ece298a's pll: origin delivers, and the project's own repository must carry every revision too (2026-10-12).
  com(){ echo "$2" >> "$1/work.txt"; git -C "$1" -c user.name=t -c user.email=t@t commit -qam "$2"; }
  ws ws8; om=$(bare ownMr8); mm=$(bare mirMr8)
  d=$(mkproj ws8/projM origin "$om" projM "$mm"); git -C "$d" push -q projM track/projM   # the mirror already holds the branch, a commit behind after the next one
  com "$d" m2; runp "$d"
  eq "mirror: the delivery goes to origin" "$(git -C "$om" rev-parse track/projM 2>/dev/null)" "$(git -C "$d" rev-parse HEAD)"
  eq "mirror: and the project's own remote is fast-forwarded to the same commit" "$(git -C "$mm" rev-parse track/projM 2>/dev/null)" "$(git -C "$d" rev-parse HEAD)"
  k "$(grep -q 'removed from' "$NOTES" && echo 1 || echo 0)" "mirror: and the owner-present eviction does not delete the branch from it" "$(cat "$NOTES")"
  eq "mirror: the commit it got is recorded" "$(cat "$d/.cc/mirrored" 2>/dev/null)" "$(git -C "$d" rev-parse HEAD)"
  # A mirror holding a commit this branch lacks is refused, never forced, and said once for that commit.
  x=$(git -C "$d" commit-tree -p HEAD -m theirs "$(git -C "$d" rev-parse 'HEAD^{tree}')"); git -C "$d" push -qf projM "$x:refs/heads/track/projM"
  com "$d" m3; runp "$d"; rc=$?
  eq "mirror: a mirror somebody else wrote to is not forced" "$(git -C "$mm" rev-parse track/projM)" "$x"
  eq "mirror: while origin still gets the commit, and the push still succeeds" "rc=$rc $(git -C "$om" rev-parse track/projM)" "rc=0 $(git -C "$d" rev-parse HEAD)"
  k "$(grep -q '^note ws8 projM github: track/projM not mirrored to projM' "$NOTES" && echo 0 || echo 1)" "mirror: and the board is told" "$(cat "$NOTES")"
  k "$(grep -q "^$(git -C "$d" rev-parse HEAD) " "$d/.cc/mirror.refused" 2>/dev/null && echo 0 || echo 1)" "mirror: the refusal is kept against that commit" "$(cat "$d/.cc/mirror.refused" 2>/dev/null)"
  runp "$d"
  eq "mirror: the same commit refused again is not said again" "$(cat "$NOTES")" ""
  # Not a member workspace: a track-named remote of its own is the repo's business, and nothing is mirrored to it.
  op=$(bare ownMr9); mp=$(bare mirMr9)
  d=$(mkproj myrepo9/t9 origin "$op" t9 "$mp"); git -C "$d" push -q t9 track/t9; t9a=$(git -C "$d" rev-parse HEAD)
  com "$d" p2; runp "$d"
  eq "mirror: a box repo's track-named remote is left alone" "$(git -C "$op" rev-parse track/t9 2>/dev/null) $(git -C "$mp" rev-parse track/t9)" "$(git -C "$d" rev-parse HEAD) $t9a"
  # ── no push waits for a person ──────────────────────────────────────────────────────────────────────
  # The 2026-09-07 hang: a member track with no credential sat 6h38m inside git-remote-https on a username
  # prompt, on a stdin no unattended run can answer. Both halves of the rule are checked, each on its own
  # fixture: the ask turned into an error, and the bound that catches a transport hanging with nothing to say.
  # THE ASK, in one offline step. `git credential fill` IS the code the wedged push was blocked inside, so this
  # asks git the same question the push did and wants an error back rather than a wait.
  out=$( printf 'protocol=https\nhost=example.test\n\n' | ( PUSH_TIMEOUT=5; git_unattended credential fill ) 2>&1 ); rc=$?
  k "$([ "$rc" != 0 ] && grep -q 'terminal prompts disabled' <<<"$out" && echo 0 || echo 1)" \
    "no credential: git comes back non-zero saying the prompt is disabled, instead of waiting on it" "rc=$rc out='$out'"
  # …and the case that is NOT suppressed: the lock is on asking a PERSON, not on authenticating. A credential
  # that is there is still used — otherwise this rule would break every push it was meant to keep.
  printf '#!/usr/bin/env bash\n[ "$1" = get ] && printf "username=u\\npassword=p\\n"\nexit 0\n' > "$bin/cred"; chmod +x "$bin/cred"
  out=$( printf 'protocol=https\nhost=example.test\n\n' | ( PUSH_TIMEOUT=5; git_unattended -c credential.helper="$bin/cred" credential fill ) 2>&1 ); rc=$?
  k "$([ "$rc" = 0 ] && grep -qx 'username=u' <<<"$out" && echo 0 || echo 1)" \
    "…while a credential that IS there is still handed over" "rc=$rc out='$out'"
  # THE BOUND, end to end through --push. The remote is ssh-shaped and its transport sleeps, which is the
  # 6h38m shape with the clock wound down: nothing to read, nothing to say, and no reason to ever return.
  owW=$(bare ownW)
  printf '#!/usr/bin/env bash\nsleep 45\n' > "$bin/wedge-ssh"; chmod +x "$bin/wedge-ssh"   # a path unique to this run, so the survivor check below can name it
  d=$(mkproj myrepoW/tW origin "user@example.test:w.git")
  t0=$(date +%s)
  ( cd "$d" && env CC_PUSH_TIMEOUT=3 GIT_SSH_COMMAND="$bin/wedge-ssh" "$bin/cc-checkpoint" --push >/dev/null 2>&1 ); rc=$?
  el=$(( $(date +%s) - t0 ))
  k "$([ "$rc" != 0 ] && [ "$el" -lt 30 ] && echo 0 || echo 1)" \
    "a transport that never answers is killed at the bound, so the push cannot outlive its loop" "rc=$rc after ${el}s"
  k "$(grep -q 'did not finish within 3s' "$d/.cc/push.err" && echo 0 || echo 1)" \
    "…and push.err carries the reason, which the kill leaves git itself with no chance to write" "$(cat "$d/.cc/push.err" 2>/dev/null)"
  k "$(pgrep -f "$bin/wedge-ssh" >/dev/null && echo 1 || echo 0)" "…and the transport dies with it, rather than being left behind" "a helper outlived the push"
  # The same worktree against a remote that answers: pushed as before, and the marker cleared. A bound that
  # also stopped working pushes would pass every case above and be an outage.
  git -C "$d" remote set-url origin "$owW"; runp "$d"; rc=$?
  k "$([ "$rc" = 0 ] && has "$owW" track/tW && [ ! -e "$d/.cc/push.err" ] && echo 0 || echo 1)" \
    "…while a remote that answers is pushed to as before, and push.err is cleared" "rc=$rc"
  # ── a name that did not resolve is asked again ────────────────────────────────────────────────────
  # 2026-10-14: two tracks' pushes failed 17 s apart on 'Could not resolve host: github.com'. A git on PATH that fails
  # its lookup for the first $FLAPS calls stands in for that resolver; each case counts the calls it made.
  mkdir -p "$T/flapbin"; RCOUNT="$T/rcount"; export RCOUNT
  printf '#!/usr/bin/env bash\nn=$(( $(cat "$RCOUNT" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$RCOUNT"\n[ -z "${REMOTE:-}" ] || { echo "remote: error: hook: Could not resolve host: ci.internal" >&2; exit 1; }\n[ "$n" -le "${FLAPS:-0}" ] || { [ -z "${DENY:-}" ] || { echo "fatal: Authentication failed" >&2; exit 128; }; echo pushed; exit 0; }\necho "fatal: unable to access '"'"'https://github.com/o/r.git/'"'"': Could not resolve host: github.com" >&2; exit 128\n' > "$T/flapbin/git"
  chmod +x "$T/flapbin/git"
  flap(){   # $1 the interfaces file · $2 how many lookups fail · $3 non-empty: then refuse, as a failed login does
    : > "$RCOUNT"; ( PATH="$T/flapbin:$PATH"; NET_DEV="$1"; RESOLVE_WAITS="0 0 0"; FLAPS="$2" DENY="${3:-}"; export FLAPS DENY
    git_unattended push origin x ) 2>"$T/flap.err"; }
  out=$(flap "$T/net-up" 2); rc=$?
  eq "a lookup that fails twice and then answers is pushed on the third try" "rc=$rc out=$out calls=$(cat "$RCOUNT")" "rc=0 out=pushed calls=3"
  k "$(grep -q 'Could not resolve host: github.com — asking again in 0s' "$T/flap.err" && echo 0 || echo 1)" \
    "…and each retry is said on stderr, where push.err keeps it" "$(cat "$T/flap.err")"
  out=$(flap "$T/net-up" 9); rc=$?
  eq "a resolver that stays down is given up on after the last wait, with git's own exit" "rc=$rc calls=$(cat "$RCOUNT")" "rc=128 calls=4"
  k "$(tail -1 "$T/flap.err" | grep -q '^fatal: unable to access' && echo 0 || echo 1)" \
    "…and git's own line is the last on stderr, so push.err names the real reason" "$(cat "$T/flap.err")"
  out=$(flap "$T/net-up" 0 deny); rc=$?
  eq "a failure that is not the lookup is returned at once, never asked again" "rc=$rc calls=$(cat "$RCOUNT")" "rc=128 calls=1"
  out=$(REMOTE=1 flap "$T/net-up" 0); rc=$?
  eq "a lookup error on a 'remote:' line is the server's text, returned at once" "rc=$rc calls=$(cat "$RCOUNT")" "rc=1 calls=1"
  # a kill during the pause takes the scratch file with it, and lands at once rather than after the sleep
  mkdir -p "$T/flaptmp"; : > "$RCOUNT"
  ( PATH="$T/flapbin:$PATH"; NET_DEV="$T/net-up"; RESOLVE_WAITS="30"; FLAPS=9 TMPDIR="$T/flaptmp"; export FLAPS TMPDIR
    git_unattended push origin x ) 2>/dev/null & fp=$!
  for _ in $(seq 50); do [ -s "$RCOUNT" ] && break; sleep 0.1; done; sleep 0.2
  t0=$SECONDS; kill -TERM "$fp"; wait "$fp"; rc=$?
  eq "a kill during the pause exits 143 at once with no scratch file left" \
    "rc=$rc fast=$([ $((SECONDS - t0)) -lt 10 ] && echo y) left=$(ls -A "$T/flaptmp" | wc -l)" "rc=143 fast=y left=0"
  out=$(flap "$T/net-lo" 9); rc=$?
  eq "inside a fence (loopback only) a failed lookup is final at once: there is no network to come back" "rc=$rc calls=$(cat "$RCOUNT")" "rc=128 calls=1"
  # …AND END TO END through --push, on a real remote behind an ssh whose lookup fails the first time it is called.
  owF=$(bare ownF)
  printf '#!/usr/bin/env bash\nn=$(( $(cat "$RCOUNT" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$RCOUNT"\n[ "$n" -gt 1 ] || { echo "ssh: Could not resolve hostname example.test: Temporary failure in name resolution" >&2; exit 255; }\ncd "%s" && eval "${@: -1}"\n' "$T" > "$bin/flap-ssh"
  chmod +x "$bin/flap-ssh"
  d=$(mkproj myrepoF/tF origin "user@example.test:ownF.git"); : > "$RCOUNT"
  ( cd "$d" && env CC_NET_DEV="$T/net-up" CC_RESOLVE_WAITS="0 0" GIT_SSH_COMMAND="$bin/flap-ssh" "$bin/cc-checkpoint" --push >/dev/null 2>&1 ); rc=$?
  k "$([ "$rc" = 0 ] && has "$owF" track/tF && [ "$(cat "$RCOUNT")" = 2 ] && [ ! -e "$d/.cc/push.err" ] && echo 0 || echo 1)" \
    "--push through a lookup that fails once: pushed on the retry, with no push.err left behind" "rc=$rc calls=$(cat "$RCOUNT") $(cat "$d/.cc/push.err" 2>/dev/null)"
  # ── a push the remote rejects is said, once per reason ─────────────────────────────────────────────
  # 2026-09-08: GitHub rejected every checkpoint of a track (a workflow file, no `workflow` scope), and all anyone
  # saw was `push!`. A bare repository whose hook declines is the same answer from a real git remote: the line
  # git prints is `! [remote rejected] <branch> -> <branch> (<reason>)`, as it is from GitHub.
  deny(){ printf '#!/bin/sh\nexit 1\n' > "$1/hooks/$2"; chmod +x "$1/hooks/$2"; }   # $1 bare repo · $2 pre-receive|update
  commit_on(){ echo "$2" >> "$1/work.txt"; git -C "$1" add -A; git -C "$1" -c user.name=t -c user.email=t@t commit -q -m "$2"; }
  rjR=$(bare rejR); deny "$rjR" pre-receive
  d=$(mkproj myrepoR/tR origin "$rjR"); jR="$HOME/.cc/state/myrepoR/tR/progress.md"
  runp "$d"; rc=$?
  k "$([ "$rc" != 0 ] && grep -qx '\[remote rejected\] track/tR -> track/tR (pre-receive hook declined)' "$d/.cc/push.rejected" 2>/dev/null && echo 0 || echo 1)" \
    "a push the remote rejects keeps the remote's own line in push.rejected" "rc=$rc $(cat "$d/.cc/push.rejected" 2>/dev/null)"
  k "$(grep -c 'push rejected by origin.*pre-receive hook declined' "$NOTES" | grep -qx 1 && echo 0 || echo 1)" "…and the row's board note names it" "$(cat "$NOTES")"
  k "$(grep -q 'push rejected by origin.*pre-receive hook declined' "$jR" 2>/dev/null && echo 0 || echo 1)" "…and so does the track's journal" "$(cat "$jR" 2>/dev/null)"
  : > "$NOTES"; commit_on "$d" second; ( cd "$d" && "$bin/cc-checkpoint" --push >/dev/null 2>&1 )
  k "$([ -s "$NOTES" ] && echo 1 || echo 0)" "…once per reason, not once per checkpoint" "$(cat "$NOTES")"
  k "$(grep -c 'push rejected by' "$jR" | grep -qx 1 && echo 0 || echo 1)" "…in the journal too" "$(cat "$jR")"
  # A later run that fails for ANOTHER reason (the sandboxed Stop hook has no credential) replaces push.err, and
  # must not take the rejection with it: nothing has reached the remote since.
  git -C "$d" remote set-url origin "$T/nowhere.git"; ( cd "$d" && "$bin/cc-checkpoint" --push >/dev/null 2>&1 )
  k "$(grep -q 'rejected' "$d/.cc/push.err" && echo 1 || echo 0)" "a later push failing for another reason replaces push.err" "$(cat "$d/.cc/push.err")"
  k "$(grep -q 'pre-receive hook declined' "$d/.cc/push.rejected" 2>/dev/null && [ ! -s "$NOTES" ] && echo 0 || echo 1)" \
    "…and leaves the kept rejection, with nothing said again" "$(cat "$d/.cc/push.rejected" 2>/dev/null) notes: $(cat "$NOTES")"
  # A DIFFERENT refusal is new news.
  rjU=$(bare rejU); deny "$rjU" update; git -C "$d" remote set-url origin "$rjU"; ( cd "$d" && "$bin/cc-checkpoint" --push >/dev/null 2>&1 )
  k "$(grep -c 'push rejected by origin.*(hook declined)' "$NOTES" | grep -qx 1 && grep -q '(hook declined)' "$d/.cc/push.rejected" && echo 0 || echo 1)" \
    "a different rejection is said again, and replaces the kept one" "$(cat "$NOTES")"
  # …and a push that goes through leaves no stale rejection behind.
  rm -f "$rjU/hooks/update"; ( cd "$d" && "$bin/cc-checkpoint" --push >/dev/null 2>&1 ); rc=$?
  k "$([ "$rc" = 0 ] && has "$rjU" track/tR && [ ! -e "$d/.cc/push.rejected" ] && [ ! -e "$d/.cc/push.err" ] && echo 0 || echo 1)" \
    "a push that succeeds clears push.rejected" "rc=$rc $(cat "$d/.cc/push.rejected" 2>/dev/null)"
  # THE STOP HOOK, on a fixture of its own: the path a worker's every turn takes. Rejected, then accepted, then
  # rejected again with the same reason — which is said again, because the success in between made it news.
  stop(){ ( cd "$1" && "$bin/cc-checkpoint" </dev/null >/dev/null 2>&1 ); }   # the Stop hook (`hook` below is the same, defined later)
  rjH=$(bare rejH); deny "$rjH" pre-receive
  d=$(mkproj myrepoH/tH origin "$rjH"); : > "$NOTES"; echo hooked >> "$d/work.txt"; stop "$d"   # the hook pushes what it commits
  k "$(grep -q 'pre-receive hook declined' "$d/.cc/push.rejected" 2>/dev/null && grep -c 'push rejected by origin' "$NOTES" | grep -qx 1 && echo 0 || echo 1)" \
    "the Stop hook's push, rejected, is kept and said" "$(cat "$NOTES")"
  stop "$d"   # a turn with nothing to commit pushes nothing, and wipes nothing
  k "$([ -s "$d/.cc/push.rejected" ] && echo 0 || echo 1)" "…a turn that committed nothing leaves it standing" "gone"
  rm -f "$rjH/hooks/pre-receive"; echo accepted >> "$d/work.txt"; stop "$d"
  k "$(has "$rjH" track/tH && [ ! -e "$d/.cc/push.rejected" ] && echo 0 || echo 1)" "…and the hook's push that succeeds clears it" "$(cat "$d/.cc/push.rejected" 2>/dev/null)"
  deny "$rjH" pre-receive; echo again >> "$d/work.txt"; stop "$d"
  k "$(grep -c 'push rejected by origin' "$NOTES" | grep -qx 2 && echo 0 || echo 1)" "…so the same rejection after a success is said again" "$(cat "$NOTES")"
  # ── which branch the repository the box made opens on ───────────────────────────────────────────────
  # GitHub gives an empty repository whichever branch lands first as its default, and the track landing first is
  # the bug: the base goes in ahead of it, and is asked for by name if that still did not settle it. Here `create`
  # makes a real bare repo under $BARE and `default` moves its HEAD, so GitHub's two halves are both fixtures.
  export BARE="$T/gh"; mkdir -p "$BARE"
  ws ws4
  # ws4 has NO BOARD for these first cases, and a fixture worktree has no origin/HEAD either: that is the state a
  # workspace is in the moment its first project is created, and the base is main because nothing recorded another.
  d=$(mkproj_main ws4/projJ)   # no remote at all: one is created for it, and seeded before the track lands
  : > "$DEFS"; runp "$d"; rJ="$BARE/projJ.git"
  k "$(has "$rJ" main && echo 0 || echo 1)" "the base is pushed into the repository the box just made" "not on $rJ"
  k "$(has "$rJ" track/projJ && echo 0 || echo 1)" "…and so is the project's own branch" "not on $rJ"
  eq "…and that repository's default branch is the base" "$(git -C "$rJ" symbolic-ref HEAD)" refs/heads/main
  eq "…asked for by name, for this project's own repository" "$(cat "$DEFS")" "default ws4 projJ main"
  k "$([ -e "$d/.cc/base-seed" ] && echo 1 || echo 0)" "…and the marker is gone: this happens once, at creation" ""
  : > "$DEFS"; runp "$d"
  eq "every push after it asks GitHub nothing" "$(cat "$DEFS")" ""
  # A repository whose default is ALREADY the track — the shape every repository the box made ended up in.
  rK="$BARE/projK.git"; git init -q --bare "$rK"
  d=$(mkproj_main ws4/projK projK "$rK"); git -C "$d" push -q projK track/projK
  git -C "$rK" symbolic-ref HEAD refs/heads/track/projK
  : > "$DEFS"; : > "$d/.cc/base-seed"; runp "$d"   # created last turn, seeded on this one
  eq "a repository whose default is the track is moved to the base" "$(git -C "$rK" symbolic-ref HEAD)" refs/heads/main
  eq "…by name, once the base is really there to point at" "$(cat "$DEFS")" "default ws4 projK main"
  # THE BOARD says what the base is, and a track is not an answer — the same rule cc cuts a track with.
  rL="$BARE/projL.git"; git init -q --bare "$rL"
  d=$(mkproj_main ws4/projL projL "$rL"); git -C "$d" branch trunk main
  : > "$DEFS"; : > "$d/.cc/base-seed"; setbase ws4 trunk; runp "$d"; nobase ws4
  k "$(has "$rL" trunk && echo 0 || echo 1)" "the board's base is the branch that is seeded" "not on $rL"
  eq "…and the one the default is set to" "$(cat "$DEFS")" "default ws4 projL trunk"
  rM="$BARE/projM.git"; git init -q --bare "$rM"
  d=$(mkproj_main ws4/projM projM "$rM")
  : > "$DEFS"; : > "$d/.cc/base-seed"; setbase ws4 track/projM; runp "$d"; nobase ws4
  eq "a board that answers a track is not believed: the base is main" "$(cat "$DEFS")" "default ws4 projM main"
  # A base nobody can push because it is not in this checkout. It used to drop the marker and say nothing, so the
  # repository kept opening on the track and no turn ever tried again — the board hears it once instead.
  rQ="$BARE/projQ.git"; git init -q --bare "$rQ"
  d=$(mkproj_main ws4/projQ projQ "$rQ")
  : > "$DEFS"; : > "$d/.cc/base-seed"; setbase ws4 nosuchbase; runp "$d"; nobase ws4
  k "$(grep -q "base branch 'nosuchbase' is not in this checkout" "$NOTES" && echo 0 || echo 1)" \
    "a base that is not in the checkout is said once instead of silently dropped" "$(cat "$NOTES")"
  eq "…and nothing is asked of GitHub for it" "$(cat "$DEFS")" ""
  k "$([ -e "$d/.cc/base-seed" ] && echo 1 || echo 0)" "…and it is not retried every turn from then on" ""
  # A repository the box did NOT make has no marker: nothing is pushed into it and its default is left alone.
  rN="$BARE/projN.git"; git init -q --bare "$rN"
  d=$(mkproj_main ws4/projN projN "$rN")
  : > "$DEFS"; runp "$d"
  k "$(has "$rN" main && echo 1 || echo 0)" "a repository the owner bound himself gets no base pushed into it" "main is on $rN"
  eq "…and its default branch is never asked about" "$(cat "$DEFS")" ""
  # …and where the base push alone settled it (GitHub's own rule), nothing is asked either.
  rO="$BARE/projO.git"; git init -q --bare "$rO"
  d=$(mkproj_main ws4/projO projO "$rO"); git -C "$d" push -q projO main; git -C "$rO" symbolic-ref HEAD refs/heads/main
  : > "$DEFS"; : > "$d/.cc/base-seed"; runp "$d"
  eq "a repository already opening on the base is not asked to change it" "$(cat "$DEFS")" ""
  # A default GitHub will not set is a person's job, so it is said once and not tried every turn from then on.
  rP="$BARE/projP.git"; git init -q --bare "$rP"
  d=$(mkproj_main ws4/projP projP "$rP")
  : > "$DEFS"; : > "$d/.cc/base-seed"; export CC_NODEFAULT=1; runp "$d"; unset CC_NODEFAULT
  k "$(grep -q 'default branch is still' "$NOTES" && echo 0 || echo 1)" "a default GitHub refuses to set reaches the board, with the command that sets it" "$(cat "$NOTES")"
  k "$([ -e "$d/.cc/base-seed" ] && echo 1 || echo 0)" "…once, not on every push after it" ""
  unset BARE
  # ── whose README a project's repository opens on ────────────────────────────────────────────────────
  hook(){ ( cd "$1" && "$bin/cc-checkpoint" </dev/null >/dev/null 2>&1 ); }
  d=$(mkproj_main ws3/projE projE "$(bare ownE)")
  hook "$d"
  eq "the README names the project" "$(head -1 "$d/README.md")" "# projE"
  k "$(grep -q '^# ws3' "$d/README.md" && echo 1 || echo 0)" "and no longer names the workspace" "$(head -1 "$d/README.md")"
  # A project whose branch was cut with no default branch to compare against is left alone: nothing to prove it is inherited.
  d=$(mkproj ws3/projE2 projE2 "$(bare ownE2)"); printf '# ws3\n\nscratch workspace\n' > "$d/README.md"
  git -C "$d" add -A; git -C "$d" -c user.name=t -c user.email=t@t commit -q -m readme
  hook "$d"
  eq "with no default branch to compare against, the README is left as it is" "$(head -1 "$d/README.md")" "# ws3"
  # A word a person set is never rewritten by a machine: the heading is the test, and it is the whole test.
  d=$(mkproj_main ws3/projF projF "$(bare ownF)"); printf '# odoo inventory\n\nmine, and not a stub\n' > "$d/README.md"
  hook "$d"
  eq "a README somebody retitled keeps its heading" "$(head -1 "$d/README.md")" "# odoo inventory"
  k "$(grep -q 'mine, and not a stub' "$d/README.md" && echo 0 || echo 1)" "and keeps what they wrote under it" "$(cat "$d/README.md")"
  # Words written THIS turn under the inherited heading are somebody's, uncommitted, and not replaced (review of #217).
  d=$(mkproj_main ws3/projH projH "$(bare ownH)")
  printf '\nnotes for this project\n' >> "$d/README.md"
  hook "$d"
  eq "a README edited this turn keeps its heading" "$(head -1 "$d/README.md")" "# ws3"
  k "$(grep -q 'notes for this project' "$d/README.md" && echo 0 || echo 1)" "and what was written under it" "$(cat "$d/README.md")"
  hook "$d"   # the turn after: those words are committed now, clean against HEAD, and still under the old heading
  eq "…and the turn after, once those words are committed, still keeps its heading" "$(head -1 "$d/README.md")" "# ws3"
  k "$(grep -q 'notes for this project' "$d/README.md" && echo 0 || echo 1)" "and still keeps the words" "$(cat "$d/README.md")"
  # Not a member workspace: its README is nobody's business here, even titled after the repo.
  d=$(mkproj myrepo3/t3 origin "$(bare ownG)"); printf '# myrepo3\n\nnot a workspace\n' > "$d/README.md"
  hook "$d"
  eq "a repo that is not a member workspace keeps its README" "$(head -1 "$d/README.md")" "# myrepo3"
  k "$(grep -q 'not a workspace' "$d/README.md" && echo 0 || echo 1)" "and all of it" "$(cat "$d/README.md")"
  # A TASK on the workspace's project delivers to origin, so the README it inherited is the project's and not retitled:
  # with no remote of its own, and with one bound by hand to origin's repository. A project of its own still is.
  tO=$(bare ws3task); d=$(mkproj_main ws3/taskA origin "$tO"); hook "$d"
  eq "a task track of a workspace with an origin keeps the project's README" "$(head -1 "$d/README.md")" "# ws3"
  d=$(mkproj_main ws3/taskB origin "$tO" taskB "$tO"); hook "$d"
  eq "…and so does one whose own remote is origin's repository" "$(head -1 "$d/README.md")" "# ws3"
  d=$(mkproj_main ws3/taskB2 origin "$tO" taskB2 "$tO/"); hook "$d"
  eq "…and one whose own remote is origin's repository spelled with a trailing slash" "$(head -1 "$d/README.md")" "# ws3"
  # THE DASHBOARD SHAPE (review of #1031): origin is the workspace's project, a remote named after the track points at
  # another repository, and the README is still the inherited one. pick_remote passes that remote over for origin, so
  # the README rides onto origin's PR and must stay the project's — not the track's stub.
  d=$(mkproj_main ws3/dashA origin "$tO" dashA "$(bare dashA-elsewhere)"); hook "$d"
  eq "a track whose own remote points elsewhere delivers to origin, so its inherited README is not retitled" "$(head -1 "$d/README.md")" "# ws3"
  eq "…and no commit rewrote it: the branch carries main's README blob" "$(git -C "$d" rev-parse HEAD:README.md)" "$(git -C "$d" rev-parse main:README.md)"
  d=$(mkproj_main ws3/taskC taskC "$(bare owntaskC)"); hook "$d"
  eq "…while a project bound to a repository of its own, in a workspace with no origin, is retitled" "$(head -1 "$d/README.md")" "# taskC"
  # ── …and the base of the repository the box made opens on that same README ──────────────────────────
  # The base is the WORKSPACE's branch and carries the workspace's README, so a project's repository opened on a
  # page about the workspace even once its default branch was the base — until the project's first PR merged.
  stub(){ printf '# %s\n\nA project of the %s workspace, and the only project in this repository.\nIts work is the `track/%s` branch.\n' "$2" "$1" "$2"; }
  save(){ git -C "$1" add -A; git -C "$1" -c user.name=t -c user.email=t@t commit -q -m "${2:-x}"; }
  export BARE="$T/gh2"; mkdir -p "$BARE"
  ws ws5   # ws5 has NO origin: a project bound to a repository of its own is only taken where origin does not contradict it (own_remote_ok)
  # A workspace with an origin no longer has repositories made for its tracks (2026-10-05), so a separate project's
  # fresh one is bound by hand here and marked the way a creation marks it.
  fresh(){ git init -q --bare "$BARE/$1.git"; printf '%s\n' "$BARE/$1.git"; }
  d=$(mkproj_main ws5/projQ projQ "$(fresh projQ)"); : > "$d/.cc/base-seed"; mQ=$(git -C "$d" rev-parse main)
  hook "$d"; rQ="$BARE/projQ.git"
  eq "the base pushed into the new repository names the project" "$(git -C "$rQ" show main:README.md 2>/dev/null | head -1)" "# projQ"
  eq "…the same file the project's own branch carries, so its first PR has nothing to merge there" \
     "$(git -C "$rQ" rev-parse main:README.md 2>/dev/null)" "$(git -C "$d" rev-parse HEAD:README.md)"
  eq "…one commit on top of the base, not a rewrite of it" "$(git -C "$rQ" rev-parse main^ 2>/dev/null)" "$mQ"
  eq "…and that commit is the README and nothing else" "$(git -C "$rQ" diff --name-only main^ main 2>/dev/null)" README.md
  eq "…and the workspace's own branch here never moved: every project in it is cut from that one" "$(git -C "$d" rev-parse main)" "$mQ"
  # THE WORKSPACE'S FIRST PROJECT. Its repository is wired up as the workspace's own `origin`, so that base branch
  # is the one ~/dev/<workspace> sits on: a commit there rejects the workspace's push and its pull retitles the
  # WORKSPACE's README. The base still goes first and the default is still set — only the README is not touched.
  ws ws6
  d=$(mkproj_main ws6/projU); mU=$(git -C "$d" rev-parse main); hook "$d"; rU="$BARE/projU.git"
  eq "the workspace's own origin gets the base exactly as the workspace has it" "$(git -C "$rU" rev-parse main 2>/dev/null)" "$mU"
  eq "…so a member's workspace README is never traded for a project's" "$(git -C "$rU" show main:README.md 2>/dev/null | head -1)" "# ws6"
  eq "…and that repository still opens on the base" "$(git -C "$rU" symbolic-ref HEAD 2>/dev/null)" refs/heads/main
  eq "…while the project's own branch is retitled as ever" "$(head -1 "$d/README.md")" "# projU"
  # Somebody's own words are not put on a branch they did not write; they reach the base when their PR merges.
  d=$(mkproj_main ws5/projT projT "$(fresh projT)"); : > "$d/.cc/base-seed"; printf '# my thing\n\nmine\n' > "$d/README.md"; save "$d" mine
  echo t > "$d/more.txt"   # the turn that makes the repository is a later one: their README is committed already
  hook "$d"
  eq "a README somebody wrote is not pushed onto the base" "$(git -C "$BARE/projT.git" show main:README.md 2>/dev/null | head -1)" "# ws5"
  # A base already carrying this project's README, and a project with no README at all: nothing is added either way.
  mkbase(){   # $1 <ws>/<track>, $2 a command run on `main` before the track is cut from it
    local p t; t=${1#*/}; p=$(mkwt "${1}" "$t" "$(fresh "$t")")
    printf '%s\n%s\n' "${1%%/*}" "$t" > "$p/.cc/track"
    git -C "$p" symbolic-ref HEAD refs/heads/main; ( cd "$p" && eval "$2" )
    echo base > "$p/base.txt"; save "$p" base
    git -C "$p" checkout -q -b "track/$t"; echo "$t" > "$p/work.txt"; : > "$p/.cc/base-seed"
    printf '%s\n' "$p"; }
  d=$(mkbase ws5/projZ 'stub ws5 projZ > README.md'); mZ=$(git -C "$d" rev-parse main); hook "$d"
  eq "a base whose README is already the project's is pushed unchanged" "$(git -C "$BARE/projZ.git" rev-parse main 2>/dev/null)" "$mZ"
  d=$(mkbase ws5/projY ':'); mY=$(git -C "$d" rev-parse main); hook "$d"
  eq "a project with no README anywhere leaves the base exactly as it is" "$(git -C "$BARE/projY.git" rev-parse main 2>/dev/null)" "$mY"
  k "$([ -e "$d/README.md" ] && echo 1 || echo 0)" "…and is not given one" ""
  # The sibling this seeding makes: a track cut from that base inherits ANOTHER project's stub, whose heading is no
  # longer the workspace's name for the test above to catch. Still nobody's words, so still replaced.
  d=$(mkproj_main ws5/projR projR "$(bare ownRb)"); stub ws5 projQ > "$d/README.md"; save "$d" sibling
  hook "$d"
  eq "a track that inherited a sibling project's stub gets its own" "$(head -1 "$d/README.md")" "# projR"
  k "$(grep -q 'track/projR' "$d/README.md" && echo 0 || echo 1)" "…naming its own branch" "$(cat "$d/README.md")"
  # …and the steady state after that: the stub already names this project, so no turn ever rewrites or commits it.
  d=$(mkproj_main ws5/projV projV "$(bare ownVb)"); stub ws5 projV > "$d/README.md"; save "$d" own
  hV=$(git -C "$d" rev-parse HEAD); hook "$d"
  eq "a stub already naming this project keeps its heading" "$(head -1 "$d/README.md")" "# projV"
  eq "…and is not rewritten, so the turn commits nothing" "$(git -C "$d" rev-parse HEAD)" "$hV"
  # One line added to it and the whole file is theirs, heading and all.
  d=$(mkproj_main ws5/projS projS "$(bare ownSb)"); { stub ws5 projQ; echo mine; } > "$d/README.md"; save "$d" theirs
  hook "$d"
  eq "a stub somebody added a line to is theirs" "$(head -1 "$d/README.md")" "# projQ"
  k "$(grep -q '^mine$' "$d/README.md" && echo 0 || echo 1)" "…and keeps the line" "$(cat "$d/README.md")"
  # No '# ' heading to rebuild the template from: not a stub, and not this file's to touch.
  d=$(mkproj_main ws5/projX projX "$(bare ownXb)"); printf 'no heading here\n' > "$d/README.md"; save "$d" plain
  hook "$d"
  eq "a README with no heading is left alone" "$(cat "$d/README.md")" "no heading here"
  # ── …and the project's FIRST PR merges into the base it was seeded with ─────────────────────────────
  # The seed is a change to README.md that only the base has, so as soon as the session writes its own README
  # both sides have touched that file against the merge base and the first PR conflicts in it, which is the very
  # thing the seeding is for (review of #238). It goes on the track, so the base is an ancestor of the branch.
  merges(){   # $1 a bare repo, $2 a branch in it → 0 when that branch merges into its base with no conflict; PRC = the clone
    PRC=$(mktemp -d "$T/pr.XXXXXX")
    { git clone -q "$1" "$PRC" >/dev/null 2>&1 && git -C "$PRC" checkout -q main 2>/dev/null; } || return 1
    git -C "$PRC" -c user.name=t -c user.email=t@t merge -q --no-edit "origin/$2" >/dev/null 2>&1; }
  d=$(mkproj_main ws5/projW projW "$(fresh projW)"); : > "$d/.cc/base-seed"; hook "$d"; rW="$BARE/projW.git"; bW=$(git -C "$rW" rev-parse main)
  k "$(git -C "$d" merge-base --is-ancestor "$bW" track/projW 2>/dev/null && echo 0 || echo 1)" \
    "the commit the base is seeded with is on the project's own branch" "$bW is not in track/projW"
  eq "…carried there by a merge that changes no file on that branch" \
     "$(git -C "$d" rev-parse 'HEAD^{tree}')" "$(git -C "$d" rev-parse 'HEAD^1^{tree}')"
  printf '# projW\n\nwhat this project is, in my own words\n' > "$d/README.md"; hook "$d"   # a later turn: the session writes the README
  merges "$rW" track/projW; rc=$?
  k "$([ "$rc" = 0 ] && echo 0 || echo 1)" "and the project's first PR merges into that base with no conflict" "git merge exited $rc"
  eq "…leaving the base on the words the session wrote" "$(sed -n 3p "$PRC/README.md" 2>/dev/null)" "what this project is, in my own words"
  # THE CONTROL, built by hand and never through this file: a README commit the base has and the branch does not.
  # The same clone and the same merge, and it conflicts — which is what the case above is worth.
  rB="$BARE/projB2.git"; git init -q --bare "$rB"
  d=$(mkproj_main ws5/projB2 projB2 "$rB"); git -C "$d" push -q projB2 main "track/projB2"
  sc=$(mktemp -d "$T/seed.XXXXXX"); git clone -q "$rB" "$sc" >/dev/null 2>&1; git -C "$sc" checkout -q main
  stub ws5 projB2 > "$sc/README.md"; save "$sc" seed; git -C "$sc" push -q origin main
  printf '# projB2\n\nmy own words\n' > "$d/README.md"; save "$d" mine; git -C "$d" push -q projB2 "track/projB2"
  merges "$rB" track/projB2; rc=$?
  k "$([ "$rc" = 0 ] && echo 1 || echo 0)" "a seed commit the branch does not have is the conflict this must never make" "it merged clean"
  # A seed whose push never reached the remote keeps the marker, and next turn is the SAME commit: rebuilt it
  # would be a new sha, and a repository unreachable for a week would collect one merge a turn.
  rW3="$BARE/projW3.git"; git init -q --bare "$rW3"
  d=$(mkproj_main ws5/projW3 projW3 "$rW3"); hook "$d"   # the stub README is committed on the track, nothing is seeded
  git -C "$d" remote set-url projW3 "$T/gone.git"; : > "$d/.cc/base-seed"; runp "$d"; h1=$(git -C "$d" rev-parse HEAD)
  k "$([ -s "$d/.cc/base-seed" ] && echo 0 || echo 1)" "a seed that could not be pushed is kept for the next turn" "$(cat "$d/.cc/base-seed" 2>/dev/null)"
  git -C "$d" remote set-url projW3 "$rW3"; runp "$d"
  eq "…and that turn reuses it instead of merging another" "$(git -C "$d" rev-parse HEAD)" "$h1"
  eq "…so the base is pushed at the commit the track already carries" "$(git -C "$rW3" rev-parse main 2>/dev/null)" "$(git -C "$d" rev-parse 'HEAD^2')"
  # THE BASE MOVED ON after the track was cut — the workspace's branch is shared, and a sibling's PR lands on it.
  # The seed merge takes the track's tree entire, so seeding here would record that later commit as reverted and
  # it would leave the new repository's base as soon as the project's first PR merged (review round 2 of #238).
  d=$(mkproj_main ws5/projV2 projV2 "$(fresh projV2)")
  git -C "$d" checkout -q main; echo plan > "$d/plan.md"; save "$d" plan; mV2=$(git -C "$d" rev-parse main)
  git -C "$d" checkout -q track/projV2; : > "$d/.cc/base-seed"
  hook "$d"; rV2="$BARE/projV2.git"
  eq "a base that moved on since the track was cut is pushed unseeded" "$(git -C "$rV2" rev-parse main 2>/dev/null)" "$mV2"
  k "$([ -n "$(git -C "$d" rev-parse -q --verify 'HEAD^2' 2>/dev/null)" ] && echo 1 || echo 0)" \
    "…so no merge that would take what it gained back off it is put on the track" "$(git -C "$d" log --oneline -1 'HEAD^2' 2>/dev/null)"
  merges "$rV2" track/projV2; rc=$?
  k "$([ "$rc" = 0 ] && echo 0 || echo 1)" "…and the project's first PR still merges into that base" "git merge exited $rc"
  k "$([ -e "$PRC/plan.md" ] && echo 0 || echo 1)" "…leaving on it what it gained after the cut" "plan.md is gone from the base"
  unset BARE
  # Reliable completion: the Stop hook's zero is not a receipt. All pushes below use this fixture's bare repo.
  d=$(mkproj_main receipt/task origin "$(bare receipt)"); echo '/.cc/' >> "$d/.git/info/exclude"
  strict(){ ( cd "$1" && "$bin/cc-checkpoint" --commit </dev/null >/dev/null 2>&1 ); }
  before=$(git -C "$d" rev-parse HEAD); echo changed >> "$d/work.txt"
  strict "$d"; rc=$?; tip=$(git -C "$d" rev-parse HEAD)
  k "$([ "$rc" = 0 ] && [ "$tip" != "$before" ] && ! has "$T/receipt.git" track/task && echo 0 || echo 1)" \
    "C1: strict completion commits but does not push" "rc=$rc before=$before tip=$tip"
  strict "$d"; rc=$?
  k "$([ "$rc" = 0 ] && [ "$(git -C "$d" rev-parse HEAD)" = "$tip" ] && echo 0 || echo 1)" \
    "C1 control: a clean retry succeeds without another commit" "rc=$rc"
  echo fixture > "$d/.env"; hook "$d"; hookrc=$?; strict "$d"; rc=$?
  k "$([ "$hookrc" = 0 ] && [ "$rc" != 0 ] && [ "$(git -C "$d" rev-parse HEAD)" = "$tip" ] \
    && [ -n "$(git -C "$d" status --porcelain)" ] && git -C "$d" diff --cached --quiet && echo 0 || echo 1)" \
    "C2: a secret refusal stays zero for the hook, fails completion, and leaves no secret staged" "rc=$rc hook=$hookrc"
  rm "$d/.env"; echo later >> "$d/work.txt"
  printf '#!/bin/sh\nexit 1\n' > "$d/.git/hooks/pre-commit"; chmod +x "$d/.git/hooks/pre-commit"
  strict "$d"; rc=$?
  k "$([ "$rc" != 0 ] && [ "$(git -C "$d" rev-parse HEAD)" = "$tip" ] && echo 0 || echo 1)" \
    "C3: a failed git commit cannot finish" "rc=$rc"
  rm "$d/.git/hooks/pre-commit"; : > "$d/.git/index.lock"; strict "$d"; rc=$?; rm "$d/.git/index.lock"
  k "$([ "$rc" != 0 ] && [ "$(git -C "$d" rev-parse HEAD)" = "$tip" ] && echo 0 || echo 1)" \
    "C3 control: a failed git add also cannot finish" "rc=$rc"
  strict "$d"; rc=$?
  k "$([ "$rc" = 0 ] && [ "$(git -C "$d" rev-parse HEAD)" != "$tip" ] && echo 0 || echo 1)" \
    "C3 recovery: removing the failure commits the same work" "rc=$rc"
  # G1: NO PROGRAM THE WORKER CONFIGURED RUNS IN THE HOST'S CHECKPOINT. With extensions.worktreeConfig on, a hook dir and
  # a core.fsmonitor planted in config.worktree (a worker could once write its admin dir's, which git reads as repo
  # config): the unpinned checkpoint commits and runs neither; with the caller's pin the hook it names does run; plain
  # git runs the fsmonitor, so the plant is live and the first case can fail.
  dg=$(mkproj_main gplant/task origin "$(bare gplant)"); echo '/.cc/' >> "$dg/.git/info/exclude"; g=$(git -C "$dg" rev-parse --absolute-git-dir)
  mkdir -p "$T/g1hooks"; printf '#!/bin/sh\ntouch "%s/g1.hook"\n' "$T" > "$T/g1hooks/pre-commit"; printf '#!/bin/sh\ntouch "%s/g1.fsm"\nexit 1\n' "$T" > "$T/g1fsm"
  chmod +x "$T/g1hooks/pre-commit" "$T/g1fsm"; printf '[extensions]\n\tworktreeConfig = true\n' >> "$g/config"
  printf '[core]\n\tfsmonitor = %s\n\thooksPath = %s/g1hooks\n' "$T/g1fsm" "$T" > "$g/config.worktree"
  before=$(git -C "$dg" -c core.fsmonitor=false rev-parse HEAD); echo planted >> "$dg/work.txt"; strict "$dg"; rc=$?
  k "$([ "$rc" = 0 ] && [ "$(git -C "$dg" -c core.fsmonitor=false rev-parse HEAD)" != "$before" ] && [ ! -e "$T/g1.hook" ] && [ ! -e "$T/g1.fsm" ] && echo 0 || echo 1)" \
    "G1: the checkpoint commits and runs neither the planted hook nor the planted fsmonitor" "rc=$rc $(cd "$T" && echo g1.*)"
  echo pinned >> "$dg/work.txt"; GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0="$T/g1hooks" strict "$dg"
  k "$([ -e "$T/g1.hook" ] && [ ! -e "$T/g1.fsm" ] && echo 0 || echo 1)" "G1: …a hooksPath the caller pinned is still honoured" "$(cd "$T" && echo g1.*)"
  echo plain >> "$dg/work.txt"; command git -C "$dg" add -A >/dev/null 2>&1   # `command`: sourced into cc-checkpoint, a bare git here is its guarded one
  k "$([ -e "$T/g1.fsm" ] && echo 0 || echo 1)" "G1 control: plain git add -A does run that fsmonitor" "no g1.fsm"
  rm -f "$T/g1.hook" "$T/g1.fsm" "$T/g1fsm"
  git -C "$d" checkout -q main; before=$(git -C "$d" rev-parse HEAD); echo offtrack > "$d/stray.txt"
  strict "$d"; rc=$?
  k "$([ "$rc" != 0 ] && [ "$(git -C "$d" rev-parse HEAD)" = "$before" ] && echo 0 || echo 1)" \
    "C4: strict completion refuses the default branch" "rc=$rc"
  git -C "$d" checkout -q -b track/impostor; printf 'receipt\nimpostor\n' > "$d/.cc/track"
  strict "$d"; rc=$?
  k "$([ "$rc" != 0 ] && [ "$(git -C "$d" rev-parse HEAD)" = "$before" ] && echo 0 || echo 1)" \
    "C4 control: a matching lying marker cannot make the wrong branch canonical" "rc=$rc"
  d=$(mkproj "$T/outside" origin "$(bare outside)"); strict "$d"; rc=$?
  k "$([ "$rc" != 0 ] && ! has "$T/outside.git" "track/$T/outside" && echo 0 || echo 1)" \
    "C5: an outside worktree gains no strict completion or push" "rc=$rc"
  # ── the sweep: what an interactive member session committed reaches its repository with nobody present ──────
  # A HOME of its own: the workspaces above hold projects wired to example.test, and a sweep over them would go
  # looking for it. $bin, the stubs in it and the fixture gitconfig are absolute, so they carry over.
  HOME="$T/home2"; mkdir -p "$HOME/.cc/worktrees" "$HOME/dev"
  # …and REAL worktrees here, not repos of their own: the sweep runs git in a member's tree only where that tree
  # hangs off ~/dev/<handle>/.git, so a fixture built any other way would be refused before it proved anything.
  mkws(){ ws "$1"; git init -q "$HOME/dev/$1"; git -C "$HOME/dev/$1" symbolic-ref HEAD refs/heads/main
    mkdir -p "$HOME/dev/$1/.git/info"; echo '.cc/' > "$HOME/dev/$1/.git/info/exclude"   # what ensure_track writes
    printf '# %s\n' "$1" > "$HOME/dev/$1/README.md"; git -C "$HOME/dev/$1" add README.md
    git -C "$HOME/dev/$1" -c user.name=t -c user.email=t@t commit -q -m init; }
  mkwork(){   # $1 <ws>/<track>, then name/url pairs → a real worktree of ~/dev/<ws> on track/<track>, one commit of its own
    local w=${1%%/*} t=${1#*/} p="$HOME/.cc/worktrees/$1"
    git -C "$HOME/dev/$w" worktree add -q -b "track/$t" "$p"; shift
    while [ "$#" -gt 1 ]; do git -C "$p" remote add "$1" "$2"; shift 2; done
    mkdir -p "$p/.cc"; printf '%s\n%s\n' "$w" "$t" > "$p/.cc/track"
    echo "$t" > "$p/work.txt"; git -C "$p" add -A; git -C "$p" -c user.name=t -c user.email=t@t commit -q -m "$t"
    printf '%s\n' "$p"; }
  mkws ws5
  osw=$(bare ownS); d=$(mkwork ws5/projS projS "$osw")
  osn=$(bare ownN); mkproj plain5/t5 origin "$osn" >/dev/null                                   # not a workspace: the sweep is not for it
  osh=$(bare ownH2); dh=$(mkwork ws5/projH2 projH2 "$osh"); git -C "$dh" checkout -q --detach   # HEAD off its branch: --push's own rule, so skipped
  dn=$(mkwork ws5/projNR)                                                                       # a project with no remote at all
  # A GIT DIR OF THE MEMBER'S. ~/.cc/worktrees/<h> is read-write inside the boundary, so this is a directory a member
  # can leave there: .cc/track, and a `.git` naming a git dir whose config they wrote — an `ext::sh -c …` remote named
  # after the track, which is exactly the remote pick_remote would choose, and a core.fsmonitor beside it. Unattended
  # every five minutes, that is the owner's shell (review of #225).
  printf '#!/bin/sh\ntouch %s/PWNED\n' "$T" > "$T/pwn"; chmod +x "$T/pwn"   # a file, not an inline sh -c: git splits an ext:: command on spaces
  git init -q "$T/memberdir"; git -C "$T/memberdir" symbolic-ref HEAD refs/heads/track/evil
  git -C "$T/memberdir" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
  git -C "$T/memberdir" remote add evil "ext::$T/pwn %S"
  git -C "$T/memberdir" config protocol.ext.allow always   # a config the member wrote, so the transport git blocks by default is on
  git -C "$T/memberdir" config core.fsmonitor "$T/pwn"   # the payload goes in LAST: set earlier, the commit above would fire it
  ev="$HOME/.cc/worktrees/ws5/evil"; mkdir -p "$ev/.cc"; printf 'ws5\nevil\n' > "$ev/.cc/track"
  printf 'gitdir: %s\n' "$T/memberdir/.git" > "$ev/.git"
  : > "$CALLS"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(has "$osw" track/projS && echo 0 || echo 1)" "sweep: a member project's commit is pushed to its repository" "$sw"
  eq "sweep: and the lease is recorded — in the host's own directory, under no bind" "$(cat "$HOME/.cc/push-state/ws5/projS/pushed" 2>/dev/null)" "$(git -C "$d" rev-parse HEAD)"
  # AND NOTHING IS WRITTEN INSIDE THE MEMBER'S TREE. A pre-check cannot make a redirection into ~/.cc/worktrees/<h>
  # safe — the member's session is live and can put a link at the name after the check (security review of #225) —
  # so the push writes none of these there, whatever is or is not at those names when it runs.
  left=; for sfile in pushed push.err push.err.tmp; do if [ -e "$d/.cc/$sfile" ]; then left="$left $sfile"; fi; done   # NOT `f`: that is this selfcheck's own failure count
  eq "…and the member's tree is written to not at all: no pushed, no push.err, no push.err.tmp" "$left" ""
  k "$(grep -qx "gitargs $osw ws5" "$CALLS" && echo 0 || echo 1)" "sweep: with the credential minted for that workspace and no other" "$(cat "$CALLS")"
  k "$(grep -q 'ws5/projS: pushed' <<<"$sw" && echo 0 || echo 1)" "sweep: and says so" "$sw"
  k "$(has "$osn" track/t5 && echo 1 || echo 0)" "sweep: a track that is not a member workspace's is left to its own hook" "pushed to $osn"
  k "$(has "$osh" track/projH2 && echo 1 || echo 0)" "sweep: a worktree whose HEAD is off its branch is skipped, not forced" "pushed to $osh"
  # THE WALL (review of #225). No git of ours goes anywhere near that git dir, so neither payload ever runs.
  k "$([ -e "$T/PWNED" ] && echo 1 || echo 0)" "sweep: an ext:: remote in a git dir the member wrote is never run" "$T/PWNED exists"
  k "$(grep -q 'ext::' "$CALLS" && echo 1 || echo 0)" "sweep: and no credential is even minted for a url out of that config" "$(cat "$CALLS")"
  k "$([ -e "$ev/.cc/pushed" ] && echo 1 || echo 0)" "sweep: a worktree whose .git is not the workspace's own is skipped, never pushed" "it pushed"
  k "$(grep -q 'ws5/evil: refusing to run git' <<<"$sw" && echo 0 || echo 1)" "sweep: and the skip is named, with the worktree" "$sw"
  # NOTHING IS CREATED FROM A TIMER: a project with no repository waits for `cc done`, and is not named again every tick.
  k "$(grep -q '^create' "$CALLS" && echo 1 || echo 0)" "sweep: a project with no remote gets no repository created" "$(cat "$CALLS")"
  k "$(grep -q 'ws5/projNR: no repository recorded' <<<"$sw" && echo 0 || echo 1)" "sweep: and it says the project is waiting for one" "$sw"
  k "$({ [ -e "$dn/.cc/create.err" ] || [ -e "$HOME/.cc/push-state/ws5/projNR/create.err" ]; } && echo 1 || echo 0)" "sweep: and no creation was even attempted for it" "$(cat "$dn/.cc/create.err" "$HOME/.cc/push-state/ws5/projNR/create.err" 2>/dev/null)"
  : > "$CALLS"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "sweep: nothing ahead — nothing pushed, no token asked for, and neither skip said twice" "$(cat "$CALLS")/$sw" "/"
  echo more > "$d/work.txt"; git -C "$d" add -A; git -C "$d" -c user.name=t -c user.email=t@t commit -q -m more
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "sweep: the next commit goes on the next tick" "$(git ls-remote --heads "$osw" refs/heads/track/projS | cut -c1-40)" "$(git -C "$d" rev-parse HEAD)"
  # A REFUSED LEASE IS SAID ONCE PER COMMIT, not every five minutes: --push writes push.err and posts a board note
  # every time it runs, and out here there is nobody to stop it doing that 288 times a day (review of #225).
  osr=$(bare ownR); dr=$(mkwork ws5/projR projR "$osr")
  sr=$(mkwt "$T/strayR"); git -C "$sr" symbolic-ref HEAD refs/heads/track/projR
  echo stray > "$sr/stray.txt"; git -C "$sr" add -A; git -C "$sr" -c user.name=t -c user.email=t@t commit -q -m stray
  git -C "$sr" push -q "$osr" track/projR   # a write this worktree did not make: its push is refused, and the lease with it
  : > "$NOTES"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q 'ws5/projR: push refused' <<<"$sw" && echo 0 || echo 1)" "sweep: a branch something else wrote to is refused, not forced, and the refusal is said" "$sw"
  eq "…and the board hears it once" "$(grep -c 'push refused' "$NOTES")" 1
  pe=$(wc -l < "$HOME/.cc/push-state/ws5/projR/push.err")   # the host's copy: the member's tree is not written to at all
  : > "$CALLS"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "sweep: the tick after does not try that same head again — nothing said, no token minted" "$(cat "$CALLS")/$sw" "/"
  eq "…so the board is not told a second time" "$(grep -c 'push refused' "$NOTES")" 1
  eq "…and push.err does not grow a line every five minutes" "$(wc -l < "$HOME/.cc/push-state/ws5/projR/push.err")" "$pe"
  echo again > "$dr/work.txt"; git -C "$dr" add -A; git -C "$dr" -c user.name=t -c user.email=t@t commit -q -m again
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q 'ws5/projR: push refused' <<<"$sw" && echo 0 || echo 1)" "sweep: a new commit is tried, and refused again out loud" "$sw"
  eq "…and the board hears that commit's refusal too" "$(grep -c 'push refused' "$NOTES")" 2
  # AND THE REFUSAL SAYS WHOSE TRACK IT IS FROM THE PATH. .cc/track is bound read-WRITE into the member session,
  # so its first line is the member's word: naming another workspace there would put this note on THAT workspace's
  # board and its Slack lane, and make a directory under ~/.cc/state for it — from a timer, nobody present
  # (review of #225). Line 2 is left alone here because a lie in it stops --push before any of this.
  osx=$(bare ownX); dx=$(mkwork ws5/projX projX "$osx")
  printf 'victimws\nprojX\n' > "$dx/.cc/track"
  sx=$(mkwt "$T/strayX"); git -C "$sx" symbolic-ref HEAD refs/heads/track/projX
  echo stray > "$sx/stray.txt"; git -C "$sx" add -A; git -C "$sx" -c user.name=t -c user.email=t@t commit -q -m stray
  git -C "$sx" push -q "$osx" track/projX
  : > "$NOTES"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q 'ws5/projX: push refused' <<<"$sw" && echo 0 || echo 1)" "sweep: a branch something else wrote to is refused whatever .cc/track says" "$sw"
  k "$(grep -q '^note ws5 projX push refused' "$NOTES" && echo 0 || echo 1)" "sweep: and the refusal is filed under the track the PATH names" "$(cat "$NOTES")"
  k "$(grep -q victimws "$NOTES" && echo 1 || echo 0)" "…so a lying .cc/track puts nothing on another workspace's board" "$(cat "$NOTES")"
  k "$([ -e "$HOME/.cc/state/victimws" ] && echo 1 || echo 0)" "…and no journal is created under the name it claimed" "$HOME/.cc/state/victimws was created"
  k "$(grep -q '^STATUS: BLOCKED' "$HOME/.cc/state/ws5/projX/progress.md" 2>/dev/null && echo 0 || echo 1)" "…the track's own journal getting the blocked line instead" "$(cat "$HOME/.cc/state/ws5/projX/progress.md" 2>/dev/null)"
  # …AND THAT JOURNAL IS NEVER WRITTEN THROUGH A LINK. ~/.cc/state/<h> is bound read-WRITE into the member's boundary
  # (cc-sandbox), so progress.md and the directory over it are theirs to replace with one — and `>>` follows a link.
  # This runs as the owner from a timer with nobody present, so it was an unattended write-as-owner primitive: link
  # progress.md at ~/.bashrc, arrange a refused lease, and two of our lines land in the owner's shell profile
  # (security review of #225, round 13). Both shapes, each on its own commit so the marker does not skip the tick.
  bump(){ echo "$1" > "$dx/work.txt"; git -C "$dx" add -A; git -C "$dx" -c user.name=t -c user.email=t@t commit -q -m "$1"; }
  echo "not yours" > "$T/victimJ"
  rm -f "$HOME/.cc/state/ws5/projX/progress.md"; ln -sf "$T/victimJ" "$HOME/.cc/state/ws5/projX/progress.md"
  bump j1; : > "$NOTES"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q 'ws5/projX: push refused' <<<"$sw" && echo 0 || echo 1)" "sweep: the refusal is still said out loud with the journal out of reach" "$sw"
  eq "…and NOTHING went through a link left at progress.md — the one write that stayed in a member-writable path" "$(cat "$T/victimJ")" "not yours"
  k "$(grep -q '^note ws5 projX push refused' "$NOTES" && echo 0 || echo 1)" "…the board note being written all the same: refusing costs the third warning, not the first two" "$(cat "$NOTES")"
  mkdir -p "$T/decoyJ"
  rm -rf "$HOME/.cc/state/ws5/projX"; ln -s "$T/decoyJ" "$HOME/.cc/state/ws5/projX"   # …the same bind lets them swap the DIRECTORY
  bump j2; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$([ -e "$T/decoyJ/progress.md" ] && echo 1 || echo 0)" "…nor into a track directory that is a link, where O_NOFOLLOW on the file alone would not have helped" "$(ls "$T/decoyJ")"
  rm -f "$HOME/.cc/state/ws5/projX"
  mv "$HOME/.cc/state/ws5" "$T/ws5state"; ln -s "$T/decoyJ" "$HOME/.cc/state/ws5"   # …nor the WORKSPACE directory, checked BEFORE the mkdir that would otherwise make one through it
  bump j3; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$([ -e "$T/decoyJ/projX" ] && echo 1 || echo 0)" "…nor into a linked workspace directory, and no directory is made through one either" "$(ls "$T/decoyJ")"
  rm -f "$HOME/.cc/state/ws5"; mv "$T/ws5state" "$HOME/.cc/state/ws5"; mkdir -p "$HOME/.cc/state/ws5/projX"
  bump j4; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q '^STATUS: BLOCKED' "$HOME/.cc/state/ws5/projX/progress.md" 2>/dev/null && echo 0 || echo 1)" "…while a plain journal in a plain directory still gets the line, which is the whole point of writing it" "$(cat "$HOME/.cc/state/ws5/projX/progress.md" 2>/dev/null)"
  # A SYMLINKED ENTRY. The sweep's glob matches a link to a directory, and the member may write in
  # ~/.cc/worktrees/<h>: this one points at a REAL worktree of their workspace inside their own checkout, so the
  # .git wall passes and .cc is plain — and every identity downstream would come off the .cc/track in it, which is
  # theirs to write (security review of #225).
  ose=$(bare ownE)
  git -C "$HOME/dev/ws5" worktree add -q -b track/evilL "$HOME/dev/ws5/evilwt"
  git -C "$HOME/dev/ws5/evilwt" remote add origin "$ose"   # the remote pick_remote falls back to once path_ids has failed
  mkdir -p "$HOME/dev/ws5/evilwt/.cc"; printf 'victimws\nevilL\n' > "$HOME/dev/ws5/evilwt/.cc/track"
  echo evil > "$HOME/dev/ws5/evilwt/work.txt"; git -C "$HOME/dev/ws5/evilwt" add -A
  git -C "$HOME/dev/ws5/evilwt" -c user.name=t -c user.email=t@t commit -q -m evil
  ( cd / && "$bin/cc-checkpoint" --sweep >/dev/null 2>&1 )   # the origin just added is the workspace's, so ws5's projects now deliver there and mirror to their own remotes: let that tick pass first
  ln -s "$HOME/dev/ws5/evilwt" "$HOME/.cc/worktrees/ws5/evilL"
  : > "$CALLS"; : > "$NOTES"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q 'ws5/evilL: refusing to push from' <<<"$sw" && echo 0 || echo 1)" "sweep: an entry that is a symlink, not the track's own directory, is skipped" "$sw"
  k "$(has "$ose" track/evilL && echo 1 || echo 0)" "…so nothing is pushed out of it" "pushed to $ose"
  eq "…and no credential is minted for it" "$(grep -c gitargs "$CALLS")" 0
  k "$(grep -q victimws "$NOTES" && echo 1 || echo 0)" "…no board of another workspace's is written to" "$(cat "$NOTES")"
  eq "…the only note being the skip, against the entry's own name" "$(cut -d' ' -f1-3 "$NOTES")" "note ws5 evilL"
  k "$([ -e "$HOME/.cc/state/victimws" ] && echo 1 || echo 0)" "…and nothing is created under ~/.cc/state in the name it claims" "$HOME/.cc/state/victimws was created"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q evilL <<<"$sw" && echo 1 || echo 0)" "…said once, not every five minutes" "$sw"
  # …and the same tree reached directly: a --push from inside a member workspace that is not one of its tracks has
  # no workspace to scope the credential to, so it mints none.
  : > "$CALLS"; out=$(cd "$HOME/dev/ws5/evilwt" && CC_CHECKPOINT_NO_CREATE=1 "$bin/cc-checkpoint" --push 2>&1); rc=$?
  k "$([ "$rc" != 0 ] && echo 0 || echo 1)" "push: a member workspace's tree that is not one of its tracks is refused" "rc=$rc out='$out'"
  eq "…with no credential minted for it" "$(grep -c gitargs "$CALLS")" 0
  k "$(grep -q 'refusing to push with an unscoped one' "$HOME/dev/ws5/evilwt/.cc/push.err" 2>/dev/null && echo 0 || echo 1)" "…and the reason is left in the worktree" "$(cat "$HOME/dev/ws5/evilwt/.cc/push.err" 2>/dev/null)"
  rm -f "$HOME/.cc/worktrees/ws5/evilL"   # out of the way of the cases below, which sweep this workspace again
  git -C "$HOME/dev/ws5" remote remove origin   # a worktree's remotes are the workspace's: the cases below run in a workspace with no origin
  # AND THE TIMER SEEDS THE BASE, BUT MOVES NO DEFAULT BRANCH. A repository created for a project whose push never
  # reached it is still empty, so the track landing there first from a timer is bug #218 again: the base is a plain
  # push and goes ahead of it here too. `cc-gh-token default` is the org-admin half, and that waits — which is why
  # the marker is kept for the next owner-present run (review of #225).
  osb=$(bare ownB2); mkwork ws5/projB2 projB2 "$osb" >/dev/null
  mkdir -p "$HOME/.cc/push-state/ws5/projB2"; : > "$HOME/.cc/push-state/ws5/projB2/base-seed"   # written where pick_remote writes it: the host's directory, not the member's tree
  : > "$DEFS"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q 'ws5/projB2: pushed' <<<"$sw" && echo 0 || echo 1)" "sweep: a project carrying a base-seed marker still has its commit pushed" "$sw"
  k "$(has "$osb" main && echo 0 || echo 1)" "sweep: and the base goes in ahead of the track, so the repository does not open on it" "main is not on $osb"
  eq "…while no default branch is moved for it from a timer" "$(cat "$DEFS")" ""
  k "$([ -e "$HOME/.cc/push-state/ws5/projB2/base-seed" ] && echo 0 || echo 1)" "…the marker being kept for the owner-present run that asks GitHub by name" "it was spent from the timer"
  # AND IT DELETES NOTHING FROM ANY REPOSITORY. evict_elsewhere runs `git push --delete` against the workspace's other
  # remotes once a push lands: a destructive remote action, and the sweep pushes and NOTHING ELSE. A branch left in a
  # sibling project's repository waits for `cc done` or the next owner-present turn (review of #225).
  osv=$(bare ownV); otv=$(bare otherV); dv=$(mkwork ws5/projV sibling "$otv" projV "$osv")
  git -C "$dv" push -q sibling track/projV
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(has "$osv" track/projV && echo 0 || echo 1)" "sweep: a project's commit reaches its own repository" "$sw"
  k "$(has "$otv" track/projV && echo 0 || echo 1)" "sweep: and no branch is deleted from the workspace's other repositories" "gone from $otv"
  k "$({ [ -e "$dv/.cc/evict.err" ] || [ -e "$HOME/.cc/push-state/ws5/projV/evict.err" ]; } && echo 1 || echo 0)" "sweep: nor is an eviction so much as attempted from a timer" "$(cat "$dv/.cc/evict.err" "$HOME/.cc/push-state/ws5/projV/evict.err" 2>/dev/null)"
  # THE MIRROR FROM THE TIMER: the project's own remote gets each commit too, and one origin already has is still sent.
  mkws ws7; o7=$(bare ownMr7); m7=$(bare mirMr7); d7=$(mkwork ws7/projP origin "$o7" projP "$m7")
  : > "$CALLS"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "sweep: a project's commit reaches origin and its mirror" "$(git -C "$o7" rev-parse track/projP 2>/dev/null) $(git -C "$m7" rev-parse track/projP 2>/dev/null)" "$(git -C "$d7" rev-parse HEAD) $(git -C "$d7" rev-parse HEAD)"
  k "$(grep -q "ws7/projP: mirrored $(git -C "$d7" rev-parse --short=7 HEAD) to projP" <<<"$sw" && echo 0 || echo 1)" "sweep: and says both" "$sw"
  # pll on 2026-10-12: origin holds the head and the lease says so, while the mirror is a commit behind.
  echo q2 >> "$d7/work.txt"; git -C "$d7" -c user.name=t -c user.email=t@t commit -qam q2; git -C "$d7" push -q origin track/projP
  git -C "$d7" rev-parse HEAD > "$HOME/.cc/push-state/ws7/projP/pushed"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "sweep: a mirror behind an origin that is current is caught up" "$(git -C "$m7" rev-parse track/projP)" "$(git -C "$d7" rev-parse HEAD)"
  k "$(grep -q 'ws7/projP: mirrored' <<<"$sw" && echo 0 || echo 1)" "sweep: and that is said" "$sw"
  : > "$CALLS"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q 'ws7' <<<"$sw$(cat "$CALLS")" && echo 1 || echo 0)" "sweep: both current — nothing pushed, nothing said, no token minted for it" "$sw $(cat "$CALLS")"
  git -C "$HOME/dev/ws7" remote remove origin   # out of the way of the cases below: a remote is the repository's, so it would outlive this case
  # A LINK PLANTED AT A STATE FILE. --push writes .cc/push.err.tmp as the OWNER, and ~/.cc/worktrees/<h> is bound
  # read-write into the member's boundary at this same path: a link there aims that write at any file the owner can
  # write, every five minutes with nobody present (review of #225).
  osl=$(bare ownL2); dl=$(mkwork ws5/projL2 projL2 "$osl")
  echo "not yours" > "$T/victim"; ln -sf "$T/victim" "$dl/.cc/push.err.tmp"
  : > "$NOTES"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "sweep: a link planted at a state file is not written through" "$(cat "$T/victim")" "not yours"
  k "$(has "$osl" track/projL2 && echo 1 || echo 0)" "sweep: and that worktree is not pushed from at all" "pushed to $osl"
  k "$(grep -q 'ws5/projL2: refusing to push from' <<<"$sw" && echo 0 || echo 1)" "sweep: the skip is named, with the worktree" "$sw"
  eq "…and the board hears it once" "$(grep -c 'refusing to push from' "$NOTES")" 1
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q projL2 <<<"$sw" && echo 1 || echo 0)" "sweep: and it is not said again every five minutes" "$sw"
  eq "…nor is the board told twice" "$(grep -c 'refusing to push from' "$NOTES")" 1
  # A PUSH THAT FAILED FOR A REASON THAT MAY PASS IS TRIED AGAIN. The marker used to keep this head whatever went
  # wrong, so one DNS blip, 5xx or unmintable credential left a member's commit on the box until they made another
  # one — the bug this file exists to close (security review of #225). Here the remote is not there, and then it is.
  ost=$(bare ownT); dt=$(mkwork ws5/projT projT "$T/gone.git")
  : > "$NOTES"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q 'ws5/projT: push failed' <<<"$sw" && echo 0 || echo 1)" "sweep: a push that failed for a reason that may pass is said" "$sw"
  eq "…and the board hears the reason once" "$(grep -c projT "$NOTES")" 1
  : > "$NOTES"; : > "$CALLS"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q "gitargs $T/gone.git ws5" "$CALLS" && echo 0 || echo 1)" "sweep: and the next tick tries that same commit again" "$(cat "$CALLS")"
  eq "…without telling the board a second time" "$(grep -c projT "$NOTES")" 0
  git -C "$dt" remote set-url projT "$ost"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(has "$ost" track/projT && echo 0 || echo 1)" "sweep: so when the reason passes the commit goes, with no new commit needed to prompt it" "$sw"
  # A LINK AT EVERY NAME THE PUSH ONCE WROTE, AND THE PUSH RUNS ANYWAY. The member's session is live while the host
  # pushes, so a link can be put at any of these AFTER a check has passed — which is why the state now lives in a
  # directory of the host's, under no bind, and there is nothing aimed at those names to follow (security review of
  # #225). This is --push under exactly the environment --sweep gives it.
  osp=$(bare ownP); dp=$(mkwork ws5/projP projP "$osp")
  echo "not yours" > "$T/victimP"; echo "nor this" > "$T/victimP2"
  ln -sf "$T/victimP" "$dp/.cc/push.err.tmp"; ln -sf "$T/victimP" "$dp/.cc/push.err"; ln -sf "$T/victimP2" "$dp/.cc/pushed"
  sdp="$HOME/.cc/push-state/ws5/projP"; mkdir -p "$sdp"
  out=$(cd "$dp" && env CC_ROLE=worker CC_CHECKPOINT_NO_CREATE=1 "CC_CHECKPOINT_STATE_DIR=$sdp" "$bin/cc-checkpoint" --push 2>&1); rc=$?
  eq "push: a link raced in at push.err.tmp is not written through" "$(cat "$T/victimP")" "not yours"
  eq "…nor one at pushed" "$(cat "$T/victimP2")" "nor this"
  k "$([ "$rc" = 0 ] && has "$osp" track/projP && echo 0 || echo 1)" "…while the commit still reaches the repository" "rc=$rc out='$out'"
  eq "…its lease recorded where the member cannot reach it" "$(cat "$sdp/pushed" 2>/dev/null)" "$(git -C "$dp" rev-parse HEAD)"
  rm -f "$dp/.cc/push.err.tmp" "$dp/.cc/push.err" "$dp/.cc/pushed"
  # AND THE PLAIN CHECKPOINT — the mode `cc done` runs before it asks where to push — COMMITS AND PUSHES, so it
  # writes pushed and push.err.tmp too, and checkpoint.err when it refuses. Only --push was ever handed the state
  # dir, so on a dirty worktree the host went on writing inside ~/.cc/worktrees/<h>/<t>/.cc and a link left at one
  # of those names was written through as the owner (review of #225). Same links, same live member, commit mode.
  osc=$(bare ownW); dc=$(mkwork ws5/projW projW "$osc")
  echo "not yours" > "$T/victimW"; echo "nor this" > "$T/victimW2"
  ln -sf "$T/victimW" "$dc/.cc/pushed"; ln -sf "$T/victimW" "$dc/.cc/push.err.tmp"; ln -sf "$T/victimW2" "$dc/.cc/checkpoint.err"
  echo dirty > "$dc/dirty.txt"   # what makes the plain checkpoint commit, and then push
  sdc="$HOME/.cc/push-state/ws5/projW"; mkdir -p "$sdc"
  ( cd "$dc" && env CC_ROLE=worker CC_CHECKPOINT_NO_CREATE=1 "CC_CHECKPOINT_STATE_DIR=$sdc" "$bin/cc-checkpoint" ) </dev/null >/dev/null 2>&1
  eq "commit: a link at pushed is not written through by the checkpoint's own push" "$(cat "$T/victimW")" "not yours"
  k "$(has "$osc" track/projW && echo 0 || echo 1)" "…while the commit still reaches the repository" "nothing on $osc"
  eq "…its lease recorded in the host's own directory" "$(cat "$sdc/pushed" 2>/dev/null)" "$(git -C "$dc" rev-parse HEAD)"
  git -C "$dc" checkout -q --detach; echo more > "$dc/dirty.txt"   # HEAD off the track's branch: the checkpoint refuses
  ( cd "$dc" && env CC_ROLE=worker CC_CHECKPOINT_NO_CREATE=1 "CC_CHECKPOINT_STATE_DIR=$sdc" "$bin/cc-checkpoint" ) </dev/null >/dev/null 2>&1
  eq "…and its refusal is not appended through a link at checkpoint.err either" "$(cat "$T/victimW2")" "nor this"
  k "$(grep -q 'refused: HEAD is' "$sdc/checkpoint.err" 2>/dev/null && echo 0 || echo 1)" "…it goes where the caller asked, so the host can still read it" "$(cat "$sdc/checkpoint.err" 2>/dev/null)"
  # A PUSH THAT LANDS UNLINKS NOTHING IN THE MEMBER'S TREE. It used to take their .cc/push.err away so `cc ls`
  # stopped showing `push!` — but `rm` resolves .cc at removal time and the member's session is live, so a link
  # swapped in during the push has the host unlink a file of that name wherever it points (security review of
  # #225). The marker is theirs; cc-reconcile, which checks the branch and not the file, is what clears it.
  osu=$(bare ownU); du=$(mkwork ws5/projU projU "$osu")
  echo "the member's own" > "$du/.cc/push.err"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(has "$osu" track/projU && echo 0 || echo 1)" "sweep: a project with a push.err of the member's own is still pushed" "$sw"
  eq "…and nothing in their tree is unlinked for it" "$(cat "$du/.cc/push.err" 2>/dev/null)" "the member's own"
  # A TICK NEVER LANDS INSIDE AN IN-FLIGHT `cc done` ON THE SAME TRACK. Both write the same ~/.cc/push-state files;
  # `cc done` holds $sd/done.lock across its checkpoint, push and PR, and a tick pushing underneath it had lease_keep
  # unlink the push.err.tmp `cc done`'s own rejected push was about to read — so `cc done` reported "push failed — no
  # PR opened" for a branch that WAS pushed (review round 11 of #225). The tick steps aside, says so, retires nothing.
  oso=$(bare ownO); mkwork ws5/projO projO "$oso" >/dev/null
  sdo="$HOME/.cc/push-state/ws5/projO"; mkdir -p "$sdo"
  { flock -n 9 || echo "the fixture could not take the lock"   # stands in for the `cc done` holding this track
    swo=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1); } 9>"$sdo/done.lock"
  k "$(grep -q "ws5/projO: skipped this tick" <<<"$swo" && echo 0 || echo 1)" "sweep: a track a 'cc done' is holding is stepped aside from, and said" "$swo"
  k "$(has "$oso" track/projO && echo 1 || echo 0)" "…and nothing of it is pushed from under that run" "it pushed to $oso while the lock was held"
  k "$([ -e "$HOME/.cc/sweep/ws5/projO" ] && echo 1 || echo 0)" "…and no marker retires the commit" "$(cat "$HOME/.cc/sweep/ws5/projO" 2>/dev/null)"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(has "$oso" track/projO && echo 0 || echo 1)" "…so the very next tick, with the lock free, pushes it" "$sw"
  # A COMMIT THAT LANDS WHILE THE PUSH RUNS IS STILL A PUSH. The tick reads HEAD, then the member's live session
  # commits again before the push goes out, so what the push put on the branch is not the head this tick read. Judged
  # against that head the run fell through rc=0 to the last branch and told the member's board "no repository recorded
  # for this project" about a project that has one and had just been pushed to (review round 11 of #225). The outcome
  # is read off the lease the push RECORDED. (The stub commits when lease_push asks it for this url's credential.)
  osr=$(bare ownRace); dr=$(mkwork ws5/projRace projRace "$osr")
  : > "$NOTES"; printf '%s %s\n' "$osr" "$dr" > "$RACE"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q 'ws5/projRace: pushed' <<<"$sw" && echo 0 || echo 1)" "sweep: a commit landing while the push runs is still reported as pushed" "$sw"
  k "$(grep -q 'ws5/projRace: no repository recorded' <<<"$sw" && echo 1 || echo 0)" "…never as a project with no repository" "$sw"
  eq "…and its board is told nothing" "$(grep -c projRace "$NOTES")" 0
  eq "…the lease being what the push actually put there" "$(cat "$HOME/.cc/push-state/ws5/projRace/pushed" 2>/dev/null)" "$(git -C "$dr" rev-parse HEAD)"
  # AND A DIVERGED BRANCH IS NEVER FORCED WITH A LEASE TAKEN FROM refs/remotes. That ref lives in the member's own
  # ~/dev/<handle>/.git and any fetch refreshes it to whatever is really on the remote, so leasing against it
  # force-pushes over the other writer instead of refusing — and the recorded lease goes whenever the worktree does
  # (security review of #225). Here the other writer is on the remote, the ref has been fetched, and there is no
  # lease of ours.
  osz=$(bare ownZ); dz=$(mkwork ws5/projZ projZ "$osz")
  git -C "$dz" push -q projZ track/projZ
  sz=$(mkwt "$T/strayZ"); git -C "$sz" symbolic-ref HEAD refs/heads/track/projZ
  echo stray > "$sz/stray.txt"; git -C "$sz" add -A; git -C "$sz" -c user.name=t -c user.email=t@t commit -q -m stray
  git -C "$sz" push -q --force "$osz" track/projZ; zs=$(git -C "$sz" rev-parse HEAD)
  git -C "$dz" fetch -q projZ   # what refreshes the tracking ref to the other writer's commit
  echo more > "$dz/work.txt"; git -C "$dz" add -A; git -C "$dz" -c user.name=t -c user.email=t@t commit -q -m more
  : > "$NOTES"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "sweep: a diverged branch with no lease of ours is not forced over the other writer" "$(git ls-remote --heads "$osz" refs/heads/track/projZ | cut -c1-40)" "$zs"
  k "$(grep -q 'ws5/projZ: push refused' <<<"$sw" && echo 0 || echo 1)" "…it is refused, and said" "$sw"
  eq "…and the board hears it" "$(grep -c 'push refused' "$NOTES")" 1
  # A TRACK FROM BEFORE #225, REBASED, IS NOT FALSELY BLOCKED BY THE SWEEP. Its lease lived at <wt>/.cc/pushed; the
  # new ~/.cc/push-state is empty on the first tick and the sweep will not read the member file for a lease — so a
  # since-rebased branch takes the plain push's non-fast-forward with nothing to lease against. That used to be
  # called "something else wrote" and stopped the track (review round 8 of #225). Now the sweep sees it is a pre-#225
  # track (the plain <wt>/.cc/pushed footprint), pushes nothing, writes NO STATUS: BLOCKED and NO board note, and
  # leaves it for `cc done`. Nothing is forced: the remote keeps what the host last put there.
  osm=$(bare ownM); dm=$(mkwork ws5/projM projM "$osm")
  git -C "$dm" push -q projM track/projM; ma=$(git -C "$dm" rev-parse HEAD)
  git -C "$dm" rev-parse HEAD > "$dm/.cc/pushed"   # the pre-#225 lease, in the OLD location the sweep will not read
  git -C "$dm" -c user.name=t -c user.email=t@t commit -q --amend --allow-empty -m "projM rebased"   # a head the remote tip is no ancestor of
  : > "$NOTES"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "sweep: a pre-#225 rebased track is not forced — the remote keeps the host's last push" "$(git ls-remote --heads "$osm" refs/heads/track/projM | cut -c1-40)" "$ma"
  k "$(grep -q 'ws5/projM: not pushed' <<<"$sw" && echo 0 || echo 1)" "sweep: it is reported quietly, not as a foreign write" "$sw"
  k "$(grep -qF "cc-checkpoint adopt ws5 projM" <<<"$sw" && echo 0 || echo 1)" "…and it names the ONE way out, not a push that can never happen" "$sw"
  k "$(grep -q 'ws5/projM: push refused' <<<"$sw" && echo 1 || echo 0)" "…never 'push refused'" "$sw"
  k "$(grep -q 'something else wrote' "$NOTES" && echo 1 || echo 0)" "…and no board note claims another writer" "$(cat "$NOTES")"
  k "$(grep -q '^STATUS: BLOCKED' "$HOME/.cc/state/ws5/projM/progress.md" 2>/dev/null && echo 1 || echo 0)" "…and NO false STATUS: BLOCKED is written to its journal" "$(cat "$HOME/.cc/state/ws5/projM/progress.md" 2>/dev/null)"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q 'ws5/projM' <<<"$sw" && echo 1 || echo 0)" "sweep: and it is not said again every five minutes for the same commit" "$sw"
  # …AND THAT WAY OUT IS REAL. rc=3 used to be a circle — the sweep said `cc done` would push it and `cc done` said
  # the next push would record the lease, while a diverged branch can never fast-forward, so the track was unlandable
  # by any automated path (review round 10 of #225). `adopt` is the exit and the only one: it reports without
  # recording, refuses a sha the remote does not answer with, and on the one the operator read it writes the host's
  # lease — after which the ordinary sweep reconciles the branch. Nothing is read out of <wt>/.cc anywhere in it.
  sdm="$HOME/.cc/push-state/ws5/projM"
  am=$(cd / && "$bin/cc-checkpoint" adopt ws5 projM 2>&1); arc=$?
  k "$([ "$arc" = 1 ] && grep -qF "$ma" <<<"$am" && echo 0 || echo 1)" "adopt: with no sha it says what the remote holds" "rc=$arc $am"
  k "$([ ! -e "$sdm/pushed" ] && echo 0 || echo 1)" "…and records nothing: reading costs nothing" "$(cat "$sdm/pushed" 2>/dev/null)"
  am=$(cd / && "$bin/cc-checkpoint" adopt ws5 projM 0000000000000000000000000000000000000000 2>&1); arc=$?
  k "$([ "$arc" = 1 ] && [ ! -e "$sdm/pushed" ] && echo 0 || echo 1)" "adopt: a sha the remote does not answer with records nothing" "rc=$arc $am"
  am=$(cd / && "$bin/cc-checkpoint" adopt ws5 projM "$ma" 2>&1); arc=$?
  eq "adopt: the sha the operator read becomes the HOST's lease" "$(cat "$sdm/pushed" 2>/dev/null)" "$ma"
  k "$([ "$arc" = 0 ] && echo 0 || echo 1)" "…and it says the next push reconciles the branch" "rc=$arc $am"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "…which the very next sweep tick does: the member's commit is on the repository" "$(git ls-remote --heads "$osm" refs/heads/track/projM | cut -c1-40)" "$(git -C "$dm" rev-parse HEAD)"
  k "$([ ! -e "$sdm/adopted" ] && echo 0 || echo 1)" "…and the adopted flag is spent, so the push after it evicts like any other" "$(ls "$sdm")"
  # A FORGED <wt>/.cc/pushed IS NEVER A FORCE-WITH-LEASE TARGET (round 9 of #225). The migration that copied its
  # CONTENTS into the host lease is gone, so a member who writes the sha currently on the remote into it can no
  # longer make the host force-push over that commit. Here another writer holds the remote at $fga; the member
  # forges the file to exactly that sha and rebases; --push, run as `cc done` runs it (state under ~/.cc/push-state,
  # none of its own recorded), refuses with rc=3 and forces nothing.
  osfg=$(bare ownFg); dfg=$(mkwork ws5/projFg projFg "$osfg")
  git -C "$dfg" push -q projFg track/projFg
  sfg=$(mkwt "$T/strayFg"); git -C "$sfg" symbolic-ref HEAD refs/heads/track/projFg
  echo other > "$sfg/o.txt"; git -C "$sfg" add -A; git -C "$sfg" -c user.name=t -c user.email=t@t commit -q -m other
  git -C "$sfg" push -q --force "$osfg" track/projFg; fga=$(git -C "$sfg" rev-parse HEAD)   # the other writer's commit, now on the remote
  git -C "$dfg" -c user.name=t -c user.email=t@t commit -q --amend --allow-empty -m "projFg rebased"   # local diverges from the remote
  printf '%s\n' "$fga" > "$dfg/.cc/pushed"   # THE FORGERY: the member writes the remote's current sha, hoping cc done leases against it
  sdfg="$HOME/.cc/push-state/ws5/projFg"; mkdir -p "$sdfg"; rm -f "$sdfg/pushed"   # the host holds no lease of its own
  out=$(cd "$dfg" && env CC_ROLE=worker CC_CHECKPOINT_NO_CREATE=1 "CC_CHECKPOINT_STATE_DIR=$sdfg" "$bin/cc-checkpoint" --push 2>&1); rc=$?
  eq "a forged <wt>/.cc/pushed does not become a force target — the other writer's commit stands" "$(git ls-remote --heads "$osfg" refs/heads/track/projFg | cut -c1-40)" "$fga"
  k "$([ "$rc" = 3 ] && echo 0 || echo 1)" "…and --push returns rc=3 (no host lease to reconcile), never forcing" "rc=$rc out='$out'"
  # The contrast that shows why the migration had to go: hand --push that very sha as the HOST's own lease (what the
  # deleted seed did) and it DOES force over the other writer — so keeping any member file out of $sd/pushed is the fix.
  printf '%s\n' "$fga" > "$sdfg/pushed"
  ( cd "$dfg" && env CC_ROLE=worker CC_CHECKPOINT_NO_CREATE=1 "CC_CHECKPOINT_STATE_DIR=$sdfg" "$bin/cc-checkpoint" --push >/dev/null 2>&1 )
  eq "…proof that sha is a real force target: given as a HOST lease it overwrites the other writer" "$(git ls-remote --heads "$osfg" refs/heads/track/projFg | cut -c1-40)" "$(git -C "$dfg" rev-parse HEAD)"
  # …and the same wall, asked directly: what `cc done` calls before any git of its own (review-156c).
  gd=$(cd / && "$bin/cc-checkpoint" gitdir ws5 "$d"); grc=$?
  k "$([ "$grc" = 0 ] && [ -z "$gd" ] && echo 0 || echo 1)" "gitdir: a track that really hangs off ~/dev/<handle>/.git passes, silently" "rc=$grc out='$gd'"
  gd=$(cd / && "$bin/cc-checkpoint" gitdir ws5 "$ev"); grc=$?
  k "$([ "$grc" = 1 ] && grep -q "^refusing to run git in $ev " <<<"$gd" && echo 0 || echo 1)" "gitdir: a redirected .git is refused, and the reason names the worktree" "rc=$grc out='$gd'"
  gd=$(cd / && "$bin/cc-checkpoint" gitdir plain5 "$T/loose"); grc=$?
  k "$([ "$grc" = 0 ] && echo 0 || echo 1)" "gitdir: a repo that is not a member workspace is nobody's business here" "rc=$grc out='$gd'"
  # ── …and a head an owner track's worker loop could not push (~/.cc/push-owed, cc-loop push_host) ──────────────
  # A HOME of its own: an owner repo (no member-workspace marker), one real worktree on track/o1 with a commit origin
  # lacks. Every case builds what it reads here and asserts both the head that is pushed and the one that is left.
  HOME="$T/home4"; mkdir -p "$HOME/.cc/worktrees/own1" "$HOME/dev"
  git init -q "$HOME/dev/own1"; git -C "$HOME/dev/own1" symbolic-ref HEAD refs/heads/main
  git -C "$HOME/dev/own1" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
  oo=$(bare ownO); git -C "$HOME/dev/own1" remote add origin "$oo"
  ow1="$HOME/.cc/worktrees/own1/o1"; git -C "$HOME/dev/own1" worktree add -q -b track/o1 "$ow1"
  mkdir -p "$ow1/.cc"; printf 'own1\no1\n' > "$ow1/.cc/track"
  echo merge > "$ow1/work.txt"; git -C "$ow1" add -A; git -C "$ow1" -c user.name=t -c user.email=t@t commit -q -m "merge main"
  oh=$(git -C "$ow1" rev-parse HEAD); owed="$HOME/.cc/push-owed/own1/o1"
  : > "$NOTES"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(has "$oo" track/o1 && echo 1 || echo 0)" "owed: an owner track with nothing owed is left to its own hook and loop" "$sw"
  mkdir -p "${owed%/*}"; printf '%s\n' "$oh" > "$owed"
  mkdir -p "$HOME/.cc/state/own1/o1"
  bash -c 'sleep 30; :' cc-loop own1 o1 x & lp=$!; echo "$lp" > "$HOME/.cc/state/own1/o1/loop.pid"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(has "$oo" track/o1 && echo 1 || echo 0)" "owed: a head whose loop is still live is left for that loop to push" "$sw"
  k "$([ -f "$owed" ] && echo 0 || echo 1)" "…and stays owed" "marker gone"
  kill "$lp" 2>/dev/null; wait "$lp" 2>/dev/null
  git -C "$HOME/dev/own1" remote set-url origin "$T/nowhere.git"   # a push that fails for a reason that may pass
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q "own1/o1: the host's push of ${oh:0:7} failed" <<<"$sw" && echo 0 || echo 1)" "owed: a failed push is said, and kept for the next tick" "$sw"
  eq "…and the board hears it" "$(grep -c "host's push of ${oh:0:7} failed" "$NOTES")" 1
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "…once per head and reason, not every tick" "$(grep -c "host's push of ${oh:0:7} failed" "$NOTES")/$sw" "1/"
  git -C "$HOME/dev/own1" remote set-url origin "$oo"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "owed: once its loop is gone the host pushes the head the loop could not" "$(git ls-remote --heads "$oo" refs/heads/track/o1 | cut -c1-40)" "$oh"
  k "$([ -e "$owed" ] && echo 1 || echo 0)" "…and it is owed no more" "$(cat "$owed" 2>/dev/null)"
  k "$(grep -q "the host pushed ${oh:0:7}" "$NOTES" && echo 0 || echo 1)" "…and the board hears that it went" "$(cat "$NOTES")"
  # ── owed, on a side branch, and a failure that quotes a url: a HOME and repo of their own ────────────────────────
  HOME="$T/home4b"; mkdir -p "$HOME/.cc/worktrees/own2" "$HOME/dev"
  git init -q "$HOME/dev/own2"; git -C "$HOME/dev/own2" symbolic-ref HEAD refs/heads/main
  git -C "$HOME/dev/own2" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
  o2=$(bare ownO2); git -C "$HOME/dev/own2" remote add origin "$o2"
  ow2="$HOME/.cc/worktrees/own2/o2"; git -C "$HOME/dev/own2" worktree add -q -b track/o2 "$ow2"
  mkdir -p "$ow2/.cc"; printf 'own2\no2\n' > "$ow2/.cc/track"
  echo merge > "$ow2/work.txt"; git -C "$ow2" add -A; git -C "$ow2" -c user.name=t -c user.email=t@t commit -q -m "merge main"
  oh2=$(git -C "$ow2" rev-parse HEAD); owed2="$HOME/.cc/push-owed/own2/o2"
  mkdir -p "${owed2%/*}"; printf '%s\n' "$oh2" > "$owed2"
  git -C "$ow2" checkout -q -b side
  : > "$NOTES"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(has "$o2" track/o2 && echo 1 || echo 0)" "owed: a worktree moved to a side branch is not pushed" "$sw"
  eq "…and the marker is kept, and why is said once to the board" "$([ -f "$owed2" ] && echo kept)|$(grep -c "push is held: its worktree is not on track/o2" "$NOTES")" "kept|1"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "…not every tick" "$(grep -c "push is held" "$NOTES")/$sw" "1/"
  git -C "$ow2" checkout -q track/o2
  # git's own words redact a url's password, so a git that quotes one on push stands in for whatever else might
  mkdir -p "$T/gitshim"; rg=$(type -P git)   # the binary: inside the tool git may be a function, and exec of that name re-runs the shim
  printf '#!/bin/sh\nfor a; do [ "$a" = push ] && { echo "remote rejected: https://x-access-token:SECRETTOK@github.com/o/r.git" >&2; exit 1; }; done\nexec %s "$@"\n' "$rg" > "$T/gitshim/git"; chmod +x "$T/gitshim/git"
  : > "$NOTES"; sw=$(cd / && PATH="$T/gitshim:$PATH" "$bin/cc-checkpoint" --sweep 2>&1)
  eq "owed: a failure quoting a url with a token reaches neither the board nor the tick's output with it" \
    "$(cat "$NOTES" "$owed2" 2>/dev/null | grep -c SECRETTOK)|$(grep -c SECRETTOK <<<"$sw")|$(grep -c "host's push of ${oh2:0:7} failed.*https://github.com/o/r.git" "$NOTES")" "0|0|1"
  # ── …and the landing (land_queue): a finished track's PR is queued from the same tick, once per PR and head ──────
  # A HOME of its own again. `cc lands` answers 0 for every workspace but the one $NOLANDS names; CC_LAND points at a
  # fake that logs its argv and refuses while $QREFUSE exists; the board row is what the stub answers `get` from $ROWS,
  # its notes still recorded into $NOTES.
  HOME="$T/home3"; mkdir -p "$HOME/.cc/worktrees" "$HOME/dev"
  printf '#!/usr/bin/env bash\n[ "$1" = lands ] || exit 0\n[ "$2" != "${NOLANDS:-}" ]\n' > "$bin/cc"
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "$QLOG"\n[ ! -e "$QREFUSE" ] || { echo "refused: the base is ahead of this branch"; exit 1; }\necho accepted\n' > "$bin/landq"
  chmod +x "$bin/cc" "$bin/landq"
  QLOG="$T/qlog"; QREFUSE="$T/qrefuse"; CC_LAND="$bin/landq"; export QLOG QREFUSE CC_LAND; : > "$QLOG"
  row(){ mkdir -p "$ROWS/$1/$2"; printf '%s\n' "$4" > "$ROWS/$1/$2/$3"; }
  stamp(){ cat "$HOME/.cc/push-state/$1/$2/landing-queued" 2>/dev/null; }
  mkws ws7; dq=$(mkwork ws7/projQ projQ "$(bare ownQ)")
  row ws7 projQ status review; row ws7 projQ pr https://github.com/o/r/pull/12
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "land: a track in review with a PR, in a workspace holding the grant, is queued once — by the project's name and PR number" "$(cat "$QLOG")" "queue ws7--projQ 12 --who cc-checkpoint --sweep"
  eq "…the stamp recording the PR and the head it was queued at, in the host's own directory" "$(stamp ws7 projQ)" "12 $(git -C "$dq" rev-parse HEAD)"
  k "$(grep -q 'ws7/projQ: PR #12 queued to land' <<<"$sw" && echo 0 || echo 1)" "…and the tick says so" "$sw"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "land: the next tick at the same head queues nothing again" "$(wc -l < "$QLOG")" 1
  echo more > "$dq/work.txt"; git -C "$dq" add -A; git -C "$dq" -c user.name=t -c user.email=t@t commit -q -m more
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "land: a new commit on the track is a new landing — queued again" "$(grep -c '^queue ws7--projQ 12 ' "$QLOG")" 2
  eq "…and the stamp moves to the new head" "$(stamp ws7 projQ)" "12 $(git -C "$dq" rev-parse HEAD)"
  # A row that is not in review is not finished: nothing is queued for it, and no stamp is written.
  mkwork ws7/projN projN "$(bare ownN7)" >/dev/null
  row ws7 projN status running; row ws7 projN pr https://github.com/o/r/pull/13
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "land: a row that is not in review queues nothing" "$(grep -c projN "$QLOG")" 0
  k "$([ -e "$HOME/.cc/push-state/ws7/projN/landing-queued" ] && echo 1 || echo 0)" "…and no stamp is written for it" "$(stamp ws7 projN)"
  # A workspace `cc lands` says no to — no token, or named in CC_SELF_LAND_EXCEPT — has its finished track left alone.
  mkws ws8; mkwork ws8/projG projG "$(bare ownG8)" >/dev/null
  row ws8 projG status review; row ws8 projG pr https://github.com/o/r/pull/14
  sw=$(cd / && env NOLANDS=ws8 "$bin/cc-checkpoint" --sweep 2>&1)
  eq "land: a workspace without the grant has nothing queued" "$(grep -c projG "$QLOG")" 0
  k "$([ -e "$HOME/.cc/push-state/ws8/projG/landing-queued" ] && echo 1 || echo 0)" "…and no stamp written" "$(stamp ws8 projG)"
  # THE DOOR REFUSES. Said out loud and to the board, and the stamp stands: tried once at this head, not every five minutes.
  df=$(mkwork ws7/projF projF "$(bare ownF7)")
  row ws7 projF status review; row ws7 projF pr https://github.com/o/r/pull/12
  : > "$NOTES"; : > "$QREFUSE"; sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q 'ws7/projF: PR #12 would not queue' <<<"$sw" && echo 0 || echo 1)" "land: a queue the door refuses is said, with the reason" "$sw"
  eq "…and the board hears it" "$(grep -c '^note ws7 projF landing: PR #12 would not queue .*refused: the base is ahead' "$NOTES")" 1
  eq "…the stamp still written: tried once at this head" "$(stamp ws7 projF)" "12 $(git -C "$df" rev-parse HEAD)"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "land: and the next tick does not try that head again" "$(grep -c '^queue ws7--projF ' "$QLOG")" 1
  eq "…nor tells the board twice" "$(grep -c '^note ws7 projF landing' "$NOTES")" 1
  # ONLY A HEAD THE HOST PUSHED (review of #418). The remote is not there, so the push fails for this head: nothing is
  # queued and no stamp is written — queued on the worktree's HEAD, the landing would have merged the older remote head
  # and the stamp would then have kept this one from ever being queued. When the remote answers, the same tick that
  # pushes queues it, at that head.
  dk=$(mkwork ws7/projK projK "$T/goneK.git"); okK=$(bare ownK)
  row ws7 projK status review; row ws7 projK pr https://github.com/o/r/pull/15
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  k "$(grep -q 'ws7/projK: push failed' <<<"$sw" && echo 0 || echo 1)" "land: (fixture) the push for this head failed" "$sw"
  eq "land: a head whose push failed is not queued" "$(grep -c '^queue ws7--projK ' "$QLOG")" 0
  k "$([ -e "$HOME/.cc/push-state/ws7/projK/landing-queued" ] && echo 1 || echo 0)" "…and no stamp is written for it" "$(stamp ws7 projK)"
  git -C "$dk" remote set-url projK "$okK"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "land: the tick whose push goes out queues it" "$(grep -c '^queue ws7--projK 15 ' "$QLOG")" 1
  eq "…stamped at the head the host pushed" "$(stamp ws7 projK)" "15 $(git -C "$okK" rev-parse track/projK)"
  # …and the shape the review named: a NEW commit whose push fails leaves the stamp at the head that IS on the remote,
  # so the landing already queued is the one cc-land runs, and the new head is queued only once it is pushed.
  hK=$(git -C "$dk" rev-parse HEAD); git -C "$dk" remote set-url projK "$T/goneK.git"
  echo more > "$dk/work.txt"; git -C "$dk" add -A; git -C "$dk" -c user.name=t -c user.email=t@t commit -q -m more
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "land: a new commit whose push failed is not queued at that head" "$(grep -c '^queue ws7--projK ' "$QLOG")" 1
  eq "…and the stamp stays at the head the remote holds" "$(stamp ws7 projK)" "15 $hK"
  git -C "$dk" remote set-url projK "$okK"
  sw=$(cd / && "$bin/cc-checkpoint" --sweep 2>&1)
  eq "land: once pushed, the new head is a new landing" "$(grep -c '^queue ws7--projK 15 ' "$QLOG")" 2
  eq "…stamped at what the host pushed, which is now HEAD" "$(stamp ws7 projK)" "15 $(git -C "$dk" rev-parse HEAD)"
  rm -f "$QREFUSE"; unset CC_LAND
  # ── the knowledge base (cc-lib): what a turn wrote is indexed by the hook, what bypassed it by the sweep ──────
  # A HOME of its own with one board, one track journal and one memory file; the REAL cc-lib copied beside the copy
  # under test (a link into the checkout is what the scratch-bin rule forbids); a baseline pass first, so the only
  # stale source a lazy ask could catch up on is the write each case makes. `re-read` absent from COVERAGE is the
  # proof: the ask found the record already indexed and brought nothing in itself.
  cp "$REALBIN/cc-lib" "$bin/cc-lib"; chmod +x "$bin/cc-lib"
  LH="$T/libhome"; mkdir -p "$LH/.cc/boards" "$LH/.cc/state/r1/t1" "$LH/.claude/projects/-x/memory" "$LH/dev/r1"
  printf '{"repo":"r1","path":"%s","tracks":{"t1":{"title":"t","status":"running","notes":[]}},"log":[]}\n' "$LH/dev/r1" > "$LH/.cc/boards/r1.json"
  printf '## 2026-09-11T10:00Z iter 1\nstarted.\n' > "$LH/.cc/state/r1/t1/progress.md"
  HOME="$LH" "$bin/cc-lib" index >/dev/null 2>&1
  printf '\n## 2026-09-11T10:30Z iter 2\nthe zebrafish gate went green at this head.\n' >> "$LH/.cc/state/r1/t1/progress.md"
  printf -- '---\nname: axolotl-rule\ndescription: an axolotl figure is checked at the boundary\nmetadata:\n  type: feedback\n---\n\nowner 09-11: check the axolotl figure at the boundary.\n' > "$LH/.claude/projects/-x/memory/axolotl-rule.md"
  ( cd "$T" && HOME="$LH" "$bin/cc-checkpoint" </dev/null >/dev/null 2>&1 )   # the Stop hook, as Claude runs it: no payload, no track
  o=$(HOME="$LH" "$bin/cc-lib" ask --object r1/t1 --need history "zebrafish gate" 2>/dev/null)
  k "$(grep -q 'zebrafish gate' <<<"$o" && grep -q checkpoint <<<"$o" && grep -q 'OUTCOME answered' <<<"$o" && ! grep -q 're-read' <<<"$o" && echo 0 || echo 1)" \
    "hook: the journal line a turn appended is indexed when the turn ends — cc-lib ask finds it as a checkpoint under its track, with nothing left for the ask to re-read" "$o"
  o=$(HOME="$LH" "$bin/cc-lib" ask --need decision "axolotl figure" 2>/dev/null)
  k "$(grep -q 'axolotl' <<<"$o" && grep -q decision <<<"$o" && grep -q 'OUTCOME answered' <<<"$o" && ! grep -q 're-read' <<<"$o" && echo 0 || echo 1)" \
    "hook: the memory file a turn saved is indexed when the turn ends — found as a decision (type feedback), nothing re-read" "$o"
  # THE MEMORY INDEX SPLIT, by the same hook: the project line a turn added to MEMORY.md moves to MEMORY-facts.md, the
  # feedback line stays, the pointer line is there once — and the fact is found by cc-lib ask (its file is the record).
  printf -- '---\nname: capybara-packet\ndescription: where the capybara packet lives\nmetadata:\n  type: project\n---\n\nthe capybara packet is under state/dash.\n' > "$LH/.claude/projects/-x/memory/capybara-packet.md"
  printf -- '- [Axolotl rule](axolotl-rule.md) — check the figure at the boundary\n- [Capybara packet](capybara-packet.md) — where the capybara packet lives\n' > "$LH/.claude/projects/-x/memory/MEMORY.md"
  ( cd "$T" && HOME="$LH" "$bin/cc-checkpoint" </dev/null >/dev/null 2>&1 )
  eq "hook: the memory index split — the rule line stays in MEMORY.md, the fact line moves to MEMORY-facts.md, one pointer line" \
    "$(grep -c 'Axolotl rule' "$LH/.claude/projects/-x/memory/MEMORY.md"):$(grep -c 'Capybara packet' "$LH/.claude/projects/-x/memory/MEMORY.md"):$(grep -c 'cc-lib ask' "$LH/.claude/projects/-x/memory/MEMORY.md"):$(grep -c 'Capybara packet' "$LH/.claude/projects/-x/memory/MEMORY-facts.md" 2>/dev/null)" '1:0:1:1'
  o=$(HOME="$LH" "$bin/cc-lib" ask --need history "capybara packet" 2>/dev/null)
  k "$(grep -q 'under state/dash' <<<"$o" && grep -q 'OUTCOME answered' <<<"$o" && echo 0 || echo 1)" \
    "…and the fact that left the loaded text is found by cc-lib ask, indexed by the same hook" "$o"
  printf '\n## 2026-09-11T10:40Z iter 3\nwritten inside a member boundary.\n' >> "$LH/.cc/state/r1/t1/progress.md"
  ( cd "$T" && HOME="$LH" CC_MEMBER_SANDBOX=1 "$bin/cc-checkpoint" </dev/null >/dev/null 2>&1 )
  eq "…and NOT inside a member's boundary: the workspace's knowledge-base file is the host's, read-only, so that hook indexes nothing (the host's next pass finds the journal stale)" \
    "$(HOME="$LH" "$bin/cc-lib" index --json 2>/dev/null | grep -o '"indexed_now": [0-9]*')" '"indexed_now": 1'
  # the sweep: an edit that bypassed every hook (a journal appended to and never turned on) is picked up by the
  # five-minute tick, and a pass that reached everything clears the hooks' misses log
  printf '\n## 2026-09-11T11:00Z iter 4\nthe pangolin rebase landed with no hook run.\n' >> "$LH/.cc/state/r1/t1/progress.md"
  echo "2026-09-11T10:59:00Z $LH/.cc/state/r1/t1/progress.md locked" >> "$LH/.cc/library/owner/misses.log"
  sw=$(cd / && HOME="$LH" "$bin/cc-checkpoint" --sweep 2>&1)
  eq "sweep: a bypassed edit is reconciled by the tick — a pass right after it finds nothing stale" \
    "$(HOME="$LH" "$bin/cc-lib" index --json 2>/dev/null | grep -o '"indexed_now": [0-9]*')" '"indexed_now": 0'
  o=$(HOME="$LH" "$bin/cc-lib" ask --object r1/t1 --need history "pangolin rebase" 2>/dev/null)
  k "$(grep -q 'pangolin rebase' <<<"$o" && grep -q 'OUTCOME answered' <<<"$o" && ! grep -q 're-read' <<<"$o" && ! grep -q 'hook-misses' <<<"$o" && echo 0 || echo 1)" \
    "…so cc-lib ask finds it with nothing to re-read, and the misses log the sweep repaired is cleared" "$o"
  k "$([ -e "$LH/.cc/library/owner/misses.log" ] && echo 1 || echo 0)" "…the misses log itself being gone" "$(cat "$LH/.cc/library/owner/misses.log" 2>/dev/null)"
  # ── the hand-off nudge: past the line a session is told to journal, once, whatever kind of session it is ────────
  # The REAL cc-context beside the copy under test (a link into the checkout is what the scratch-bin rule forbids),
  # measuring fixture transcripts of its own. $bin/cc-config answers nothing, so the line cc-context reads is its
  # built-in 150k default and never this box's ~/.cc/config, and CC_CTX_WINDOW settles the window without a fork.
  cp "$REALBIN/cc-context" "$bin/cc-context"; chmod +x "$bin/cc-context"
  tx(){ printf '{"type":"assistant","isSidechain":false,"message":{"model":"m","usage":{"input_tokens":%s,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":10}}}\n' "$2" > "$T/$1.jsonl"; }
  pay(){ printf '{"session_id":"%s","transcript_path":"%s","cwd":"%s","stop_hook_active":%s}' "$1" "$T/$1.jsonl" "${2:-$T}" "${3:-false}"; }
  stophook(){ ( cd "${2:-$T}" && env CC_CTX_WINDOW=200000 CC_CTX_BOX_MODEL= CC_STATUSLINE_DIR="$T/nostatusline" \
      CC_CHECKPOINT_NUDGE_MIN="${NUDGE_MIN:-60}" "$bin/cc-checkpoint" 2>/dev/null <<<"$1" ); }
  tx big 160000; tx small 20000; tx held 160000; tx tracked 170000
  out=$(stophook "$(pay big)")
  k "$(grep -qF '"decision": "block"' <<<"$out" && grep -qF 'Append a dated entry' <<<"$out" && [ "$(grep -c . <<<"$out")" = 1 ] && echo 0 || echo 1)" \
    "nudge: a session past the hand-off line is told, in ONE Stop line, to append a dated journal entry" "$out"
  eq "…carrying the measurement cc-context made of that session's transcript" "$(grep -c '80%  160k/200k' <<<"$out")" 1
  out=$(stophook "$(pay big)")
  k "$([ -z "$out" ] && echo 0 || echo 1)" "…and not again next turn: a session that journalled a moment ago is not told twice" "$out"
  NUDGE_MIN=0; out=$(stophook "$(pay big)"); NUDGE_MIN=60
  k "$(grep -qF '"decision": "block"' <<<"$out" && echo 0 || echo 1)" "…until the cooldown is up (CC_CHECKPOINT_NUDGE_MIN), which is a cooldown and not a once-ever" "$out"
  # the permission seat's line names cc-perms handoff; the same transcript from any other directory gets the journal line
  mkdir -p "$HOME/.cc/state/rp/perms"; echo brief > "$HOME/.cc/state/rp/perms/brief.md"; tx seat 160000; tx notseat 160000; tx seatshut 160000
  # a stub cc-perms in the fixture bin answers `gate` from a flag file (open while $HOME/.cc/gate-open exists) and runs the real one for the rest
  printf '#!/bin/sh\n[ "$1" = gate ] && { [ -e "$HOME/.cc/gate-open" ]; exit; }\nexec env CC_PERMS_FIXTURE=1 "$REALBIN/cc-perms" "$@"\n' > "$bin/cc-perms"; chmod +x "$bin/cc-perms"
  # …but only while the hand-off gate is open. Shut (no CC_WORKER_SANDBOX=1 in ~/.cc/config; the environment's key does
  # not count), the seat is told to journal and why there is no hand-off, and nothing that sends it to hand off.
  out=$(stophook "$(pay seatshut "$HOME/.cc/state/rp/perms")" "$HOME/.cc/state/rp/perms")
  k "$(grep -qF 'The hand-off is shut until go-live' <<<"$out" && grep -qF 'state/rp/perms/handoff.md' <<<"$out" \
      && ! grep -qF 'run cc-perms handoff' <<<"$out" && ! grep -qF 'HAND-OFF ENTRY' <<<"$out" && ! grep -qF 'in the foreground' <<<"$out" \
      && [ "$(grep -c . <<<"$out")" = 1 ] && echo 0 || echo 1)" \
    "nudge: with the hand-off gate shut, the permission seat past the line journals and hears the hand-off is shut until go-live, with no push to hand off" "$out"
  mkdir -p "$HOME/.cc"; printf 'CC_WORKER_SANDBOX=1\n' > "$HOME/.cc/config"; : > "$HOME/.cc/gate-open"   # the stub gate is open
  out=$(stophook "$(pay seat "$HOME/.cc/state/rp/perms")" "$HOME/.cc/state/rp/perms")
  k "$(! grep -qF 'shut until go-live' <<<"$out" && echo 0 || echo 1)" "…and with it open (cc-perms gate exits 0), no word of it being shut" "$out"
  k "$(grep -qF 'run cc-perms handoff' <<<"$out" && grep -qF 'state/rp/perms/handoff.md' <<<"$out" && ! grep -qF 'perms-handoff' <<<"$out" && grep -qF '## HAND-OFF ENTRY' <<<"$out" \
      && grep -qF 'cc-perms handoff in the foreground' <<<"$out" && grep -qF 'Bash timeout of at least 120000 ms' <<<"$out" \
      && ! grep -qF 'Append a dated entry' <<<"$out" && [ "$(grep -c . <<<"$out")" = 1 ] && echo 0 || echo 1)" \
    "nudge: the permission seat past the line is told to write its HAND-OFF ENTRY, then run cc-perms handoff in the foreground under a Bash timeout of at least 120000 ms" "$out"
  out=$(stophook "$(pay notseat)")
  k "$(grep -qF 'Append a dated entry' <<<"$out" && ! grep -qF 'cc-perms' <<<"$out" && echo 0 || echo 1)" \
    "…and a session anywhere else gets the journal line, with no word of cc-perms" "$out"
  # the key says 1 but cc-perms gate says shut (no go-live marker): the seat hears the shut line, not a hand-off
  rm -f "$HOME/.cc/gate-open"; tx seatshut2 160000
  out=$(stophook "$(pay seatshut2 "$HOME/.cc/state/rp/perms")" "$HOME/.cc/state/rp/perms")
  k "$(grep -qF 'The hand-off is shut until go-live' <<<"$out" && ! grep -qF 'run cc-perms handoff' <<<"$out" && echo 0 || echo 1)" \
    "nudge: the config key at 1 does not open the gate while cc-perms gate says shut (no go-live marker): the seat hears the shut line" "$out"
  rm -f "$HOME/.cc/config"   # the pins cases below start with the gate shut
  # the seat's pins: the REAL cc-perms beside the copy under test, run against this fixture's HOME (which makes it a
  # fixture of its own), with a claude stand-in where a launch looks for one. Removed after, so no later case asks it.
  pd="$HOME/.cc/state/rp/perms"
  mkdir -p "$HOME/.local/bin" "$HOME/.local/share/claude/versions" "$HOME/.claude/skills/s"; echo s > "$HOME/.claude/skills/s/SKILL.md"
  printf '#!/bin/sh\n' > "$HOME/.local/share/claude/versions/9.9.9"; chmod +x "$HOME/.local/share/claude/versions/9.9.9"
  ln -sfn "$HOME/.local/share/claude/versions/9.9.9" "$HOME/.local/bin/claude"
  "$bin/cc-perms" __pins "$pd" > "$pd/pins" 2>/dev/null; tx pinned 20000; tx pinned2 20000; tx pinned3 20000
  out=$(stophook "$(pay pinned "$pd")" "$pd")
  k "$([ -z "$out" ] && [ -s "$pd/pins" ] && echo 0 || echo 1)" "pins: the permission seat whose startup files are as it pinned them hears nothing" "$out"
  echo planted >> "$HOME/.claude/skills/s/SKILL.md"
  out=$(stophook "$(pay pinned "$pd")" "$pd")
  k "$(grep -qF '"decision": "block"' <<<"$out" && grep -qF "startup surface changed since the last pin: $HOME/.claude/skills — review each change before re-pinning; never pin an entry you haven't read." <<<"$out" \
      && ! grep -qF 'run cc-perms pin' <<<"$out" && ! grep -qiF 'and run cc-perms' <<<"$out" && [ "$(grep -c . <<<"$out")" = 1 ] && echo 0 || echo 1)" \
    "pins: a changed skill puts 'startup surface changed since the last pin: <entry>' on the permission seat's stop line, naming ~/.claude/skills, and tells it to review each change, never just to pin" "$out"
  k "$(grep -qF 'The hand-off is shut until go-live' <<<"$out" && ! grep -qF 'refuse to start a seat' <<<"$out" && echo 0 || echo 1)" \
    "…and with the hand-off gate shut it says the hand-off is shut until go-live, not that a hand-off waits on the pins" "$out"
  o2=$(stophook "$(pay pinned "$pd")" "$pd"); echo x > "$HOME/.claude/CLAUDE.md"; o3=$(stophook "$(pay pinned "$pd")" "$pd")
  k "$([ -z "$o2" ] && grep -qF "since the last pin: $HOME/.claude/CLAUDE.md, $HOME/.claude/skills — review" <<<"$o3" && echo 0 || echo 1)" \
    "…once per set of entries: the same set next turn is not said again, and a further change names both" "$o2 | $o3"
  # gate open: the same review line, then that hand-off and relaunch wait on the pins; and nothing about it being shut
  echo CC_WORKER_SANDBOX=1 > "$HOME/.cc/config"; : > "$HOME/.cc/gate-open"; tx pinned4 20000; out=$(stophook "$(pay pinned4 "$pd")" "$pd")
  k "$(grep -qF 'review each change before re-pinning; never pin an entry you' <<<"$out" && grep -qF 'Until the pins match, cc-perms handoff and relaunch refuse to start a seat.' <<<"$out" \
      && ! grep -qF 'shut until go-live' <<<"$out" && ! grep -qF 'run cc-perms pin' <<<"$out" && echo 0 || echo 1)" \
    "pins: with the hand-off gate open, the line says to review each change, and that hand-off and relaunch wait until the pins match" "$out"
  # both lines at once, gate shut: the pins line first, the nudge after it, and the shut sentence said once, not twice
  rm -f "$HOME/.cc/config" "$HOME/.cc/gate-open"; tx pinnedbig 160000; out=$(stophook "$(pay pinnedbig "$pd")" "$pd")
  k "$([[ $out == *'startup surface changed since the last pin'*'You are the permission seat, past the hand-off line'* ]] \
      && [ "$(grep -o 'shut until go-live' <<<"$out" | grep -c .)" = 1 ] && ! grep -qF 'run cc-perms handoff' <<<"$out" && [ "$(grep -c . <<<"$out")" = 1 ] && echo 0 || echo 1)" \
    "…and with the gate shut and the seat past the hand-off line too, one stop line: pins first, then the journal ask, the shut sentence once" "$out"
  out=$(stophook "$(pay pinned2 "$pd" true)" "$pd"); o2=$(stophook "$(pay pinned3 "$T")")
  k "$([ -z "$out" ] && [ -z "$o2" ] && echo 0 || echo 1)" \
    "…and never while a Stop hook holds the turn, nor in a session outside the seat's directory" "$out | $o2"
  rm -f "$bin/cc-perms" "$HOME/.local/bin/claude" "$HOME/.claude/CLAUDE.md"; rm -rf "$HOME/.claude/skills"
  out=$(stophook "$(pay small)")
  k "$([ -z "$out" ] && echo 0 || echo 1)" "nudge: a session under the line is told nothing at all" "$out"
  out=$(stophook "$(pay held "" true)")
  k "$([ -z "$out" ] && echo 0 || echo 1)" "nudge: nothing while a Stop hook already holds this turn open — blocking again there is a block-loop" "$out"
  d=$(mkproj nudgews/nudgetrack); echo nudged > "$d/work.txt"
  out=$(stophook "$(pay tracked "$d")" "$d")
  k "$(grep -qF '"decision": "block"' <<<"$out" && git -C "$d" log -1 --format=%s | grep -q '^wip: checkpoint' && echo 0 || echo 1)" \
    "nudge: a track is told too, and its work is committed FIRST — the session is asked to journal after the commit" "$out"
  # ── THE BRANCH IT COMMITS, AND THE REFUSAL THE SESSION HEARS (raised-checkpoint-refuses-a-study-branch) ───────
  # The ece203 course seat's track branch was deleted by a squash merge, so it cut study/ece203-2026-09-19 and
  # worked there; the hook refused every turn end into a file nobody read, and the day's commits were lost.
  tx side 20000   # under the hand-off line: the only line these cases can hear is a refusal
  d=$(mkproj sidews/ece203); t0=$(git -C "$d" rev-parse track/ece203); git -C "$d" checkout -q -b study/ece203-2026-09-19
  echo "the seat's work" > "$d/work.txt"; out=$(stophook "$(pay side "$d")" "$d")
  k "$(git -C "$d" log -1 --format=%s | grep -q '^wip: checkpoint' && echo 0 || echo 1)" \
    "branch: a dated side branch of this track is committed — <kind>/<track>-YYYY-MM-DD" "$(git -C "$d" log --oneline -2) out='$out'"
  k "$([ -e "$d/.cc/checkpoint.err" ] && echo 1 || echo 0)" "…with no refusal lit" "$(cat "$d/.cc/checkpoint.err" 2>/dev/null)"
  k "$([ -z "$out" ] && echo 0 || echo 1)" "…and nothing said: an accepted branch is not news" "$out"
  eq "…on the side branch, HEAD's own" "$(git -C "$d" rev-parse --abbrev-ref HEAD)" study/ece203-2026-09-19
  eq "…and the track's own branch left exactly where it was" "$(git -C "$d" rev-parse track/ece203)" "$t0"
  git -C "$d" checkout -q -b study/ece203   # the same, undated
  echo more > "$d/work.txt"; out=$(stophook "$(pay side "$d")" "$d")
  eq "branch: <kind>/<track> is this track's too" "$(git -C "$d" log -1 --format=%s | cut -c1-15)" "wip: checkpoint"
  # …and everything else is refused, out loud. `track/ece203-lab1` is the case that matters: around here
  # <track>-<suffix> is a SECOND TRACK's name (ece231, ece231-lab1), never a side branch of the first.
  for b in main track/other track/ece203-lab1 study/ece206-2026-09-19; do
    git -C "$d" checkout -q -b "$b"; tip=$(git -C "$d" rev-parse HEAD); rm -f "$d/.cc/checkpoint.err"
    echo "on $b" > "$d/work.txt"; out=$(stophook "$(pay side "$d")" "$d")
    eq "branch: nothing is committed on '$b' — not this track's branch" "$(git -C "$d" rev-parse HEAD)" "$tip"
    k "$(grep -qF '"decision": "block"' <<<"$out" && grep -qF "HEAD is '$b'" <<<"$out" && grep -qF "track/ece203" <<<"$out" \
        && [ "$(grep -c . <<<"$out")" = 1 ] && echo 0 || echo 1)" \
      "…and the session is told so in ONE line, naming '$b' and the branch it wants" "$out"
    k "$(grep -q "refused: HEAD is '$b'" "$d/.cc/checkpoint.err" 2>/dev/null && echo 0 || echo 1)" "…with checkpoint.err written as before" "$(cat "$d/.cc/checkpoint.err" 2>/dev/null)"
    out=$(stophook "$(pay side "$d" true)" "$d")
    k "$([ -z "$out" ] && echo 0 || echo 1)" "…and said nothing while a Stop hook already holds the turn open: a refusal is not a block-loop" "$out"
  done
  # A refusal is the more urgent of the two things this hook can say, so it goes in FRONT of the hand-off nudge.
  tx over 160000; NUDGE_MIN=0; out=$(stophook "$(pay over "$d")" "$d"); NUDGE_MIN=60
  k "$(grep -q 'reason": "refused: HEAD is' <<<"$out" && grep -q 'Append a dated entry' <<<"$out" && [ "$(grep -c . <<<"$out")" = 1 ] && echo 0 || echo 1)" \
    "branch: a refusal and the hand-off nudge together are one line, the refusal first" "$out"
  # ── A BRANCH MOVED UNDER THE WORKTREE (raised-shared-branch-stages-a-revert, 2026-09-18) ──────────────────────
  # Two worktrees of one box repo on one branch: the seat, whose hook this is, and a hand worktree that takes the
  # branch with --ignore-other-worktrees and commits a fix. The seat's index then holds the fix REVERSED, staged.
  git init -q -b main "$HOME/dev/shared"; echo base > "$HOME/dev/shared/work.txt"; git -C "$HOME/dev/shared" add -A
  git -C "$HOME/dev/shared" -c user.name=t -c user.email=t@t commit -q -m base; echo '.cc/' >> "$HOME/dev/shared/.git/info/exclude"   # as `cc` stamps a repo
  seat="$HOME/.cc/worktrees/shared/seat"; git -C "$HOME/dev/shared" worktree add -q -b track/seat "$seat"
  mkdir -p "$seat/.cc"; printf 'shared\nseat\n' > "$seat/.cc/track"; osS=$(bare sharedS); git -C "$seat" remote add origin "$osS"
  hand="$T/hand"; git -C "$HOME/dev/shared" worktree add -q -b scratch "$hand"
  handfix(){   # $1 what work.txt says after the hand fix → the branch tip it leaves
    git -C "$hand" checkout -q --ignore-other-worktrees track/seat; printf '%s\n' "$1" > "$hand/work.txt"
    git -C "$hand" -c user.name=t -c user.email=t@t commit -qam "hand: $1"; git -C "$hand" checkout -q scratch
    git -C "$HOME/dev/shared" rev-parse track/seat; }
  seatrun(){ ( cd "$seat" && env CC_ROLE=worker "$bin/cc-checkpoint" </dev/null >/dev/null 2>&1 ); }
  sj="$HOME/.cc/state/shared/seat/progress.md"
  fix=$(handfix fix1)
  k "$(git -C "$seat" diff --cached --quiet 2>/dev/null; [ $? = 1 ] && echo 0 || echo 1)" "moved: the fixture is the real thing — the seat's index holds a staged diff against the hand fix" "$(git -C "$seat" status --porcelain)"
  seatrun
  eq "moved: the hook commits no revert — the branch still ends at the hand fix" "$(git -C "$seat" rev-parse HEAD)" "$fix"
  eq "…and the seat's index is left clean" "$(git -C "$seat" status --porcelain)" ""
  eq "…its files carried to the fix" "$(cat "$seat/work.txt")" fix1
  k "$([ -e "$seat/.cc/checkpoint.err" ] && echo 1 || echo 0)" "…and no refusal is lit: a carried tree is not a failed commit" "$(cat "$seat/.cc/checkpoint.err" 2>/dev/null)"
  eq "…the journal says so, once" "$(grep -c 'track/seat moved' "$sj" 2>/dev/null)" 1
  seatrun
  eq "…and not again next turn: HEAD's reflog is stamped" "$(grep -c 'track/seat moved' "$sj" 2>/dev/null)" 1
  fix=$(handfix fix2); echo mine > "$seat/notes.txt"   # the seat's own edit, to a file the fix did not touch
  seatrun
  eq "moved: the seat's own edit rides along — committed on top of the hand fix" "$(git -C "$seat" rev-parse 'HEAD^' 2>/dev/null)" "$fix"
  eq "…that commit carrying only the seat's file" "$(git -C "$seat" diff --name-only 'HEAD^' HEAD 2>/dev/null)" notes.txt
  eq "…and the fix intact" "$(cat "$seat/work.txt")" fix2
  fix=$(handfix fix3); echo collide > "$seat/work.txt"   # the seat's own edit, to the file the fix changed
  seatrun
  eq "moved: an edit that collides with the fix is refused — the branch still ends at the hand fix" "$(git -C "$seat" rev-parse HEAD)" "$fix"
  eq "…the seat's edit untouched" "$(cat "$seat/work.txt")" collide
  k "$(grep -q 'edited here too' "$seat/.cc/checkpoint.err" 2>/dev/null && echo 0 || echo 1)" "…and checkpoint.err says which case this is" "$(cat "$seat/.cc/checkpoint.err" 2>/dev/null)"
  seatrun   # NOT sorted: the refusal stamped nothing, so the guard fires again instead of committing the seat's stale copy over the fix
  eq "…and unsorted, the next turn refuses again — the branch still ends at the hand fix (review of #544)" "$(git -C "$seat" rev-parse HEAD)" "$fix"
  eq "…the seat's edit still untouched" "$(cat "$seat/work.txt")" collide
  eq "…and checkpoint.err holds the refusal twice" "$(grep -c 'edited here too' "$seat/.cc/checkpoint.err" 2>/dev/null)" 2
  git -C "$seat" checkout -q -- work.txt; seatrun   # sorted by hand: the next turn carries on
  eq "…and once sorted, the next turn leaves the seat clean" "$(git -C "$seat" status --porcelain)" ""
  # The hand worktree DROPS the last commit: the branch now ends before this seat's own tip, and the seat's files still
  # hold the dropped commit's content — a wip commit here would land that content again (review of #544).
  git -C "$hand" checkout -q --ignore-other-worktrees track/seat; git -C "$hand" reset -q --hard HEAD~1
  git -C "$hand" checkout -q scratch; rw=$(git -C "$HOME/dev/shared" rev-parse track/seat); echo later > "$seat/notes.txt"
  k "$([ "$(cat "$seat/work.txt")" != "$(git -C "$seat" show "$rw:work.txt")" ] && echo 0 || echo 1)" "rewritten: the fixture is the real thing — the seat's tree differs from the branch's new tip" "$(cat "$seat/work.txt") vs $(git -C "$seat" show "$rw:work.txt")"
  seatrun
  eq "rewritten: nothing is committed on a branch rewritten under the worktree" "$(git -C "$seat" rev-parse HEAD)" "$rw"
  k "$(grep -q 'rewritten under this worktree' "$seat/.cc/checkpoint.err" 2>/dev/null && echo 0 || echo 1)" "…and the refusal names it" "$(cat "$seat/.cc/checkpoint.err" 2>/dev/null)"
  seatrun   # the next turn: refused again, no wip re-lands the dropped commit's content
  eq "…and the next turn refuses again — HEAD still the tip the hand left, no wip made (review of #544)" "$(git -C "$seat" rev-parse HEAD)" "$rw"
  eq "…the seat's tree untouched" "$(cat "$seat/work.txt")" fix3
  eq "…and checkpoint.err holds the refusal twice" "$(grep -c 'rewritten under this worktree' "$seat/.cc/checkpoint.err" 2>/dev/null)" 2
  # THE KEPT CASE. A seat that undoes its own last wip commit by editing the file back stages a diff that reverts its
  # branch head exactly — and it is committed, because the head was this worktree's own move.
  seat2="$HOME/.cc/worktrees/shared/seat2"; git -C "$HOME/dev/shared" worktree add -q -b track/seat2 "$seat2"
  mkdir -p "$seat2/.cc"; printf 'shared\nseat2\n' > "$seat2/.cc/track"   # origin: the repo's, shared with the seat
  seat2run(){ ( cd "$seat2" && env CC_ROLE=worker "$bin/cc-checkpoint" </dev/null >/dev/null 2>&1 ); }
  echo tried > "$seat2/work.txt"; seat2run; c1=$(git -C "$seat2" rev-parse HEAD)
  echo base > "$seat2/work.txt"; seat2run   # back to what it was before c1: a staged revert of HEAD, the seat's own
  k "$([ "$(git -C "$seat2" rev-parse HEAD)" != "$c1" ] && [ "$(git -C "$seat2" rev-parse 'HEAD^')" = "$c1" ] && echo 0 || echo 1)" "kept: a seat undoing its own last wip commit by hand is still committed" "$(git -C "$seat2" log --oneline -3)"
  eq "…to the tree it had before" "$(git -C "$seat2" rev-parse 'HEAD^{tree}')" "$(git -C "$seat2" rev-parse 'HEAD~2^{tree}')"
  # ── A HAND PUSH FROM THE WORKTREE DOES NOT STALE THE LEASE (raised-hand-commit-on-track-branch-stales-push-lease) ──
  osL=$(bare leaseL); dl=$(mkproj boxl/tl origin "$osL")   # a box track: nothing under ~/dev/boxl calls it a workspace
  lpush(){ ( cd "$dl" && "$bin/cc-checkpoint" --push </dev/null >/dev/null 2>&1 ); }
  lpush; la=$(git -C "$dl" rev-parse HEAD)
  eq "lease: the first push records its lease" "$(cat "$dl/.cc/pushed" 2>/dev/null)" "$la"
  echo repair > "$dl/work.txt"; git -C "$dl" -c user.name=t -c user.email=t@t commit -qam "hand repair"
  git -C "$dl" push -q origin track/tl 2>/dev/null   # pushed by hand, outside cc-checkpoint: the lease still says $la
  git -C "$dl" -c user.name=t -c user.email=t@t commit -q --amend -m "hand repair, rebased"; lb=$(git -C "$dl" rev-parse HEAD)   # the remote now holds the pre-rebase head
  lpush; rc=$?
  eq "lease: a rebase over a hand push from this worktree is pushed, not refused" "rc=$rc $(git -C "$osL" rev-parse track/tl)" "rc=0 $lb"
  eq "…and the lease is what was just pushed" "$(cat "$dl/.cc/pushed" 2>/dev/null)" "$lb"
  k "$(grep -q 'STATUS: BLOCKED' "$HOME/.cc/state/boxl/tl/progress.md" 2>/dev/null && echo 1 || echo 0)" "…with no STATUS: BLOCKED written" "$(cat "$HOME/.cc/state/boxl/tl/progress.md" 2>/dev/null)"
  git clone -q "$osL" "$T/elsewhere" 2>/dev/null; git -C "$T/elsewhere" checkout -q track/tl 2>/dev/null   # a writer this branch's reflog has never seen
  echo theirs > "$T/elsewhere/work.txt"; git -C "$T/elsewhere" -c user.name=o -c user.email=o@o commit -qam "someone else"
  git -C "$T/elsewhere" push -q origin track/tl 2>/dev/null; lc=$(git -C "$T/elsewhere" rev-parse HEAD)
  git -C "$dl" -c user.name=t -c user.email=t@t commit -q --amend -m "rebased again"
  lpush; rc=$?
  eq "lease: a tip this branch never held is still refused — the remote keeps it" "rc=$rc $(git -C "$osL" rev-parse track/tl)" "rc=2 $lc"
  eq "…and the lease is not moved to it" "$(cat "$dl/.cc/pushed" 2>/dev/null)" "$lb"
  k "$(grep -q 'something else wrote' "$HOME/.cc/state/boxl/tl/progress.md" 2>/dev/null && echo 0 || echo 1)" "…and it is said as before" "$(cat "$HOME/.cc/state/boxl/tl/progress.md" 2>/dev/null)"
  # ── THE BRANCH THE LANDING DELETED, AND THE TURN THAT PUSHED NOTHING (raised-checkpoint-push-lost-after-merge-deletes-branch) ──
  # A session row is a living project: its branch outlives each PR. A squash merge deletes track/<track> at origin
  # (and cc-reconcile deletes it again every pass while the row sits `merged`), the seat works on, and for 38 h
  # nothing it committed reached anybody while it reported "the hook pushes" — two rescues and one false statement
  # to the owner (ece206 and ece207, 2026-09-19/20).
  tx del 20000   # under the hand-off line: the only line these cases can hear is the push's
  osD=$(bare delD); dD=$(mkproj boxd/tD origin "$osD"); jD="$HOME/.cc/state/boxd/tD/progress.md"
  echo '.cc/' >> "$dD/.git/info/exclude"   # as `cc` stamps a repo: a turn that changed nothing is then really one
  hookD(){ out=$(stophook "$(pay del "$dD" "${1:-false}")" "$dD"); }
  echo first > "$dD/work.txt"; hookD
  k "$([ "$(git -C "$osD" rev-parse track/tD 2>/dev/null)" = "$(git -C "$dD" rev-parse HEAD)" ] && [ -z "$out" ] && echo 0 || echo 1)" \
    "deleted branch: the first checkpoint pushes, and says nothing — a push that arrived is not news" "$out"
  # THE DELETE BETWEEN COMMITS: the daily sweep takes the branch again while this seat commits nothing new, so the
  # receipt still equals HEAD and only asking the remote can see it (branch_back, review of #588).
  git -C "$osD" update-ref -d refs/heads/track/tD
  hookD
  eq "…and a branch deleted while nothing changed here is put back by the next quiet turn" "$(git -C "$osD" rev-parse track/tD 2>/dev/null)" "$(git -C "$dD" rev-parse HEAD)"
  k "$([ -z "$out" ] && echo 0 || echo 1)" "…saying nothing: the work is back where it belongs" "$out"
  hookD
  k "$([ "$(git -C "$osD" rev-parse track/tD 2>/dev/null)" = "$(git -C "$dD" rev-parse HEAD)" ] && [ -z "$out" ] && echo 0 || echo 1)" \
    "…and a quiet turn with the branch still there changes nothing and says nothing" "$out"
  git -C "$osD" update-ref -d refs/heads/track/tD
  printf '#!/bin/sh\necho "refusing every push" >&2\nexit 1\n' > "$osD/hooks/pre-receive"; chmod +x "$osD/hooks/pre-receive"
  hookD; hq=$(git -C "$dD" rev-parse HEAD)
  k "$(grep -qF '"decision": "block"' <<<"$out" && grep -qF "deleted at origin and putting it back failed" <<<"$out" && grep -qF "${hq:0:12}" <<<"$out" \
      && ! git -C "$osD" rev-parse -q --verify track/tD >/dev/null 2>&1 && echo 0 || echo 1)" \
    "…and one that cannot be put back is said in the Stop line, though the receipt still equals HEAD" "$out"
  rm -f "$osD/hooks/pre-receive"; hookD
  eq "…and the quiet turn after the remote takes pushes again puts it back" "$(git -C "$osD" rev-parse track/tD 2>/dev/null)" "$hq"
  # REGRESSION GUARD, not this change: a delete followed by a NEW commit was always put back, because the plain
  # push is then a create and succeeds before any lease is read.
  git -C "$osD" update-ref -d refs/heads/track/tD   # the landing squash-merges the PR and deletes the branch
  echo second > "$dD/work.txt"; hookD
  eq "…and after the delete a new commit's plain push puts the work back on the remote under track/tD (as before)" "$(git -C "$osD" rev-parse track/tD 2>/dev/null)" "$(git -C "$dD" rev-parse HEAD)"
  eq "…with the lease recorded again, so the turn after it leases against what is really there" "$(cat "$dD/.cc/pushed" 2>/dev/null)" "$(git -C "$dD" rev-parse HEAD)"
  k "$([ -z "$out" ] && echo 0 || echo 1)" "…and still nothing said: the work is where it belongs" "$out"
  k "$(grep -q 'STATUS: BLOCKED' "$jD" 2>/dev/null && echo 1 || echo 0)" "…and no STATUS: BLOCKED: nothing wrote to that branch, it was simply gone" "$(cat "$jD" 2>/dev/null)"
  # A PUSH THAT TRULY CANNOT HAPPEN IS HEARD IN THE TURN IT FAILED, in the one line a refusal takes.
  git -C "$dD" remote set-url origin "$T/nowhere.git"
  echo third > "$dD/work.txt"; hookD; hD=$(git -C "$dD" rev-parse HEAD)
  k "$(grep -qF '"decision": "block"' <<<"$out" && grep -qF "is NOT on origin" <<<"$out" && grep -qF "${hD:0:12}" <<<"$out" \
      && grep -qF "track/tD" <<<"$out" && [ "$(grep -c . <<<"$out")" = 1 ] && echo 0 || echo 1)" \
    "a turn that pushed nothing is said in ONE Stop line, naming the commit that did not leave and its branch" "$out"
  k "$([ -s "$dD/.cc/push.err" ] && echo 0 || echo 1)" "…with push.err written as before, for cc ls and the digest" "$(cat "$dD/.cc/push.err" 2>/dev/null)"
  hookD   # a turn with nothing to commit: the gap does not close by itself, so the push is tried again and said again
  k "$(grep -qF '"decision": "block"' <<<"$out" && grep -qF "is NOT on origin" <<<"$out" && grep -qF "${hD:0:12}" <<<"$out" \
      && ! grep -qF "nothing was committed this turn" <<<"$out" && echo 0 || echo 1)" \
    "…and a turn with nothing to commit says it too, naming the push that failed and not the empty index" "$out"
  hookD true
  k "$([ -z "$out" ] && echo 0 || echo 1)" "…and said nothing while a Stop hook already holds the turn open: not a block-loop" "$out"
  git -C "$dD" remote set-url origin "$osD"; echo fourth > "$dD/work.txt"; hookD
  k "$([ "$(git -C "$osD" rev-parse track/tD)" = "$(git -C "$dD" rev-parse HEAD)" ] && [ -z "$out" ] && echo 0 || echo 1)" \
    "…and a remote that answers again is pushed to, with nothing said" "$out"
  # A COMMIT THIS HOOK DID NOT MAKE. The session committed by hand and pushed by hand, so the index is clean and HEAD
  # is past the receipt: the quiet turn used to push nothing and tell the seat, turn after turn, that work the remote
  # already held was not live and to say nothing was live (review of #588).
  echo fifth > "$dD/work.txt"; git -C "$dD" -c user.name=t -c user.email=t@t commit -qam "hand commit, hand push"
  git -C "$dD" push -q origin track/tD 2>/dev/null; hookD
  k "$([ -z "$out" ] && echo 0 || echo 1)" "a commit pushed by hand is not called unpushed by the quiet turn after it" "$out"
  eq "…and the receipt moves up to what the remote really holds" "$(cat "$dD/.cc/pushed" 2>/dev/null)" "$(git -C "$dD" rev-parse HEAD)"
  echo sixth > "$dD/work.txt"; git -C "$dD" -c user.name=t -c user.email=t@t commit -qam "hand commit, no push"; hookD
  k "$([ "$(git -C "$osD" rev-parse track/tD 2>/dev/null)" = "$(git -C "$dD" rev-parse HEAD)" ] && [ -z "$out" ] && echo 0 || echo 1)" \
    "…and one the session committed and did not push is PUSHED by that turn, not reported to it" "$out"
  git -C "$dD" remote remove origin; echo seventh > "$dD/work.txt"
  git -C "$dD" -c user.name=t -c user.email=t@t commit -qam "hand commit, nowhere to push"; hookD
  k "$(grep -qF "is NOT on origin" <<<"$out" && grep -qF "nothing was committed this turn" <<<"$out" && echo 0 || echo 1)" \
    "…and with no remote to try, the gap is still said, in the words of a turn that committed nothing" "$out"
  git -C "$dD" remote add origin "$osD"
  # THE DELETE THAT LANDS MID-PUSH, which is where the lease used to call a missing tip "something else wrote". The
  # remote is ahead (a real other writer), so the plain push is rejected; $UPACK then takes the branch away inside the
  # push path, between that rejection and the leased push.
  osR=$(bare delR); dR=$(mkproj boxr/tR origin "$osR"); jR2="$HOME/.cc/state/boxr/tR/progress.md"
  rpush(){ ( cd "$dR" && "$bin/cc-checkpoint" --push </dev/null >/dev/null 2>&1 ); }
  rpush   # a lease of our own on file
  git clone -q "$osR" "$T/elseR" 2>/dev/null
  theirs(){   # a writer this branch's reflog has never seen, on top of whatever the remote holds → its tip on stdout
    git -C "$T/elseR" fetch -q origin "refs/heads/track/tR" 2>/dev/null
    git -C "$T/elseR" checkout -q -B track/tR FETCH_HEAD 2>/dev/null
    echo "$1" > "$T/elseR/work.txt"; git -C "$T/elseR" -c user.name=o -c user.email=o@o commit -qam "$1"
    git -C "$T/elseR" push -q origin track/tR 2>/dev/null; git -C "$T/elseR" rev-parse HEAD; }
  mine(){ git -C "$dR" -c user.name=t -c user.email=t@t commit -q --amend -m "$1"; }   # our own rebase: the plain push is then rejected
  printf '#!/usr/bin/env bash\ngit -C "%s" update-ref -d refs/heads/track/tR 2>/dev/null\nexec git-upload-pack "$@"\n' "$osR" > "$bin/upack-del"
  printf '#!/usr/bin/env bash\nexit 1\n' > "$bin/upack-dead"; chmod +x "$bin/upack-del" "$bin/upack-dead"
  theirs one >/dev/null; mine rebased
  printf '%s\n' "$bin/upack-del" > "$UPACK"; rpush; rc=$?
  eq "a branch deleted between the two pushes is put back, not leased against a tip that is gone" "rc=$rc $(git -C "$osR" rev-parse track/tR 2>/dev/null)" "rc=0 $(git -C "$dR" rev-parse HEAD)"
  eq "…and the lease is what was just pushed" "$(cat "$dR/.cc/pushed" 2>/dev/null)" "$(git -C "$dR" rev-parse HEAD)"
  k "$(grep -q 'STATUS: BLOCKED' "$jR2" 2>/dev/null && echo 1 || echo 0)" "…with nothing blocked: no other writer was refused, the ref was gone" "$(cat "$jR2" 2>/dev/null)"
  lrk=$(git -C "$dR" rev-parse HEAD)   # the lease that push left on file: no refusal below may move it
  lr2=$(theirs two); mine "rebased again"
  printf '%s\n' "$bin/upack-dead" > "$UPACK"; rpush; rc=$?
  eq "a remote that does not answer is not a deleted branch: the refusal stands and its tip is kept" "rc=$rc $(git -C "$osR" rev-parse track/tR)" "rc=2 $lr2"
  : > "$UPACK"   # the remote answers for itself again
  lr3=$(theirs three); mine "rebased once more"; rpush; rc=$?
  eq "…and a tip this branch never held, on a remote that has it, is refused exactly as before" "rc=$rc $(git -C "$osR" rev-parse track/tR)" "rc=2 $lr3"
  eq "…and neither refusal moved the lease" "$(cat "$dR/.cc/pushed" 2>/dev/null)" "$lrk"
  k "$(grep -q 'something else wrote' "$jR2" 2>/dev/null && echo 0 || echo 1)" "…and said, as before" "$(cat "$jR2" 2>/dev/null)"
  echo "cc-checkpoint selfcheck: $((n - f)) passed, $f failed"; [ "$f" = 0 ]
}
