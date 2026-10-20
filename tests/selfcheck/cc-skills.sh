# shellcheck shell=bash disable=SC2154,SC2034
# cc-skills's selfcheck cases, moved out of bin/cc-skills. That tool's selfcheck() sources this file, whose
# definition replaces it, and then calls it: the cases run in the tool's own shell, with its functions and
# globals, as they did when the body sat there. SC2154/SC2034 are off because those globals live in bin/cc-skills.

selfcheck(){   # its own HOME: a fixture upstream, a fixture list, a fixture notifier; git only, no network
  local fh n=0 bad=0 up up2 out rc a
  fh=$(mktemp -d "${TMPDIR:-/tmp}/ccskills-XXXXXX") || return 1
  t(){ n=$((n+1)); [ "$2" = "$3" ] && return 0; bad=$((bad+1)); printf 'FAIL %s: got %s, want %s\n' "$1" "$2" "$3"; }
  run(){ env -u CC_SKILLS_TIMEOUT HOME="$fh" CC_SKILLS_LIST="$fh/list" CC_SKILLS_NOTIFY="$fh/notify" CC_SKILLS_TREE="$fh/tree" CC_SKILLS_OVERLAY="$fh/overlay" \
    GIT_CONFIG_GLOBAL="$fh/gitconfig" GIT_CONFIG_NOSYSTEM=1 "$SELF" "$@"; }
  gi(){ git -c user.name=t -c user.email=t@t "$@"; }
  printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s/notified"\n' "$fh" > "$fh/notify"; chmod +x "$fh/notify"; : > "$fh/gitconfig"
  up="$fh/up/fx-skill"; mkdir -p "$up" "$fh/.claude/skills/synced/own" || return 1
  echo keep > "$fh/.claude/skills/synced/own/SKILL.md"
  git -C "$up" init -q -b main && printf -- '---\nname: fx-skill\n---\nv1\n' > "$up/SKILL.md" && gi -C "$up" add -A && gi -C "$up" commit -qm v1 || return 1
  mkdir -p "$fh/.claude/skills/handmade" && echo mine > "$fh/.claude/skills/handmade/SKILL.md"
  printf '# a comment\nfx-skill %s\nhandmade %s\nsynced %s\nBad/Name %s\nleaky https://u:tok@example.invalid/x.git\n' "$up" "$up" "$up" "$up" > "$fh/list"
  out=$(run sync 2>&1); rc=$?
  t 'sync: a listed skill that is missing is cloned at ~/.claude/skills/<name>, at the upstream tip' "$(tail -1 "$fh/.claude/skills/fx-skill/SKILL.md" 2>/dev/null)" v1
  t 'sync: no half-made clone is left under a dot name' "$(find "$fh/.claude/skills" -maxdepth 1 -name '.*cc-skills*' | wc -l)" 0
  t 'sync: synced is never taken, a bad name and a url with a token in it are refused, each saying so' \
    "$(grep -c 'other than synced' <<<"$out")/$(grep -c 'user or a token' <<<"$out")/$(cat "$fh/.claude/skills/synced/own/SKILL.md")" 2/1/keep
  t 'sync: a hand-made directory at a listed name is left alone and the run exits 1' "$(cat "$fh/.claude/skills/handmade/SKILL.md")/$rc" mine/1
  t 'names: only the listed skill that is a clone of its url — not synced, not the hand-made one' "$(run names 2>/dev/null | tr '\n' ' ')" 'fx-skill '
  printf 'fx-skill %s\n' "$up" > "$fh/list"; : > "$fh/notified"; rm -f "$fh/.cc/skills/"*.fail
  # a new commit upstream reaches the clone on the next sync
  printf -- '---\nname: fx-skill\n---\nv2\n' > "$up/SKILL.md" && gi -C "$up" commit -qam v2 || return 1
  out=$(run sync 2>&1); rc=$?
  t 'sync: a new commit on the default branch reaches the clone in one sync' "$rc/$(tail -1 "$fh/.claude/skills/fx-skill/SKILL.md")/$(grep -c 'fx-skill .* -> ' <<<"$out")" 0/v2/1
  # the upstream goes away: the fetch fails, the last good copy stays, one report
  mv "$up" "$up.gone"
  run sync >/dev/null 2>&1; rc=$?; run sync >/dev/null 2>&1
  t 'sync: a failed pull exits 1 and keeps the last good copy' "$rc/$(tail -1 "$fh/.claude/skills/fx-skill/SKILL.md")" 1/v2
  t 'sync: …and is reported once across two failing syncs, as a request under one id' "$(wc -l < "$fh/notified")/$(grep -c -- '--ask --id skill-pull:fx-skill' "$fh/notified")" 1/1
  t 'list: says the skill is failing' "$(run list | cut -f4 | cut -c1-8)" failing:
  mv "$up.gone" "$up"; printf -- '---\nname: fx-skill\n---\nv3\n' > "$up/SKILL.md" && gi -C "$up" commit -qam v3 || return 1
  out=$(run sync 2>&1); rc=$?
  t 'sync: the upstream back, the next sync catches up, clears the stamp and says so' \
    "$rc/$(tail -1 "$fh/.claude/skills/fx-skill/SKILL.md")/$([ -e "$fh/.cc/skills/fx-skill.fail" ] && echo stamp || echo clear)/$(grep -c 'updates again' <<<"$out")" 0/v3/clear/1
  # the clone diverges (someone committed in it): not a fast-forward, nothing moves, reported
  gi -C "$fh/.claude/skills/fx-skill" commit -q --allow-empty -m local
  printf -- '---\nname: fx-skill\n---\nv4\n' > "$up/SKILL.md" && gi -C "$up" commit -qam v4 || return 1
  out=$(run sync 2>&1); rc=$?
  t 'sync: a diverged clone is not forced — exit 1, content stays, the reason says fast-forward' \
    "$rc/$(tail -1 "$fh/.claude/skills/fx-skill/SKILL.md")/$(grep -c 'not a fast-forward' <<<"$out")" 1/v3/1
  t 'the clone'"'"'s own config names only the url: no credential in it' "$(git -C "$fh/.claude/skills/fx-skill" config --list --local | grep -ci 'credential\|token\|password')" 0
  # A SKILL KEPT IN THE TREE: its own list and its own fixture tree, no git
  rm -rf "$fh/.claude/skills" "$fh/.cc/skills"; mkdir -p "$fh/tree/skills/tx" "$fh/.claude/skills/handtree"
  printf -- '---\nname: tx\n---\nt1\n' > "$fh/tree/skills/tx/SKILL.md"; echo mine > "$fh/.claude/skills/handtree/SKILL.md"
  printf 'tx tree:skills/tx\nhandtree tree:skills/tx\nup tree:../x\nabs tree:/etc\nnone tree:skills/none\n' > "$fh/list"
  out=$(run sync 2>&1); rc=$?
  t 'tree: a listed tree skill is copied whole to ~/.claude/skills/<name>, its mark naming the source' \
    "$(tail -1 "$fh/.claude/skills/tx/SKILL.md" 2>/dev/null)/$(cat "$fh/.claude/skills/tx/.cc-skills-tree" 2>/dev/null)" "t1/$fh/tree/skills/tx"
  t 'tree: a dir that climbs out or is absolute is refused, a missing one fails, a hand-made dir is left alone, exit 1' \
    "$(grep -c 'absolute or climbs out' <<<"$out")/$(grep -c 'not there or has no SKILL.md' <<<"$out")/$(cat "$fh/.claude/skills/handtree/SKILL.md")/$rc" 2/1/mine/1
  t 'tree: names lists the copy and not the hand-made dir at a tree name' "$(run names 2>/dev/null | tr '\n' ' ')" 'tx '
  printf 'tx tree:skills/tx\n' > "$fh/list"
  out=$(run sync 2>&1); rc=$?
  t 'tree: an unchanged source is not copied again' "$rc/$(grep -c 'copied' <<<"$out")" 0/0
  printf -- '---\nname: tx\n---\nt2\n' > "$fh/tree/skills/tx/SKILL.md"; echo extra > "$fh/tree/skills/tx/new.md"
  out=$(run sync 2>&1); rc=$?
  t 'tree: a changed source is copied again whole, in one sync, and no dot dir is left behind' \
    "$rc/$(tail -1 "$fh/.claude/skills/tx/SKILL.md")/$(cat "$fh/.claude/skills/tx/new.md")/$(grep -c 'copied again' <<<"$out")/$(find "$fh/.claude/skills" -maxdepth 1 -name '.*cc-skills*' | wc -l)" 0/t2/extra/1/0
  t 'list: a tree skill reads as a tree copy' "$(run list | cut -f4)" 'at tree copy'
  # AN OVERLAY SKILL: the same copy, read from the overlay's root; one that climbs out is refused like a tree one
  mkdir -p "$fh/overlay/tool/skill"; printf -- '---\nname: ox\n---\no1\n' > "$fh/overlay/tool/skill/SKILL.md"
  printf 'ox overlay:tool/skill\noup overlay:../tool\n' > "$fh/list"
  out=$(run sync 2>&1); rc=$?
  t 'overlay: a listed overlay skill is copied from the overlay root, one that climbs out is refused' \
    "$(tail -1 "$fh/.claude/skills/ox/SKILL.md" 2>/dev/null)/$(cat "$fh/.claude/skills/ox/.cc-skills-tree" 2>/dev/null)/$(grep -c 'absolute or climbs out' <<<"$out")/$rc" \
    "o1/$fh/overlay/tool/skill/1/0"
  t '--help exits 0' "$("$SELF" --help >/dev/null 2>&1; echo $?)" 0
  # ALIAS lines: a second clone holding a sub-skill, a symlink inside it that escapes, a directory sitting at an
  # unlisted name, and every name/target failure names is supposed to catch
  up2="$fh/up/fx-clone"; mkdir -p "$up2/skills/vde" "$up2/skills/ade" "$up2/skills/nomd"
  printf -- '---\nname: vde\n---\nv1\n' > "$up2/skills/vde/SKILL.md"; printf -- '---\nname: ade\n---\na1\n' > "$up2/skills/ade/SKILL.md"
  ln -s /etc "$up2/skills/escape"
  git -C "$up2" init -q -b main && gi -C "$up2" add -A && gi -C "$up2" commit -qm v1 || return 1
  mkdir -p "$fh/.claude/skills/nope-clone/skills/x" && printf -- '---\nname: x\n---\n' > "$fh/.claude/skills/nope-clone/skills/x/SKILL.md"
  printf 'fx-clone %s\nvde -> fx-clone/skills/vde\nsynced -> fx-clone/skills/vde\nBad/Name -> fx-clone/skills/vde\nescaped -> fx-clone/skills/escape\ngone -> fx-clone/skills/gone\nbaremd -> fx-clone/skills/nomd\nstray -> nope-clone/skills/x\nabs -> /etc\nclimb -> fx-clone/../nope-clone/skills/x\n' "$up2" > "$fh/list"
  out=$(run sync 2>&1); rc=$?
  t 'sync: a good alias line is kept as a symlink to its target' "$(readlink "$fh/.claude/skills/vde" 2>/dev/null)" 'fx-clone/skills/vde'
  t 'sync: a target that is absolute or climbs out with .., escapes its clone, dangles, has no SKILL.md or sits in no listed clone gets no link at all, each saying so, exit 1' \
    "$(find "$fh/.claude/skills" -maxdepth 1 -type l -printf '%f\n' | sort | tr '\n' ' ')/$(grep -c 'absolute or climbs out with' <<<"$out")/$(grep -c 'does not resolve to a skill' <<<"$out")/$rc" 'vde /2/4/1'
  t 'aliases: prints each well-formed alias line, refused targets included, for cc-sandbox to check itself' \
    "$(run aliases 2>/dev/null | cut -f1 | tr '\n' ' ')" 'vde escaped gone baremd stray abs climb '
  t 'sync: synced and a bad name are refused as aliases too, each saying so' "$(grep -c 'other than synced' <<<"$out")" 2
  # sync made none of the bad links, so plant them by hand: names has to refuse what is on disk on its own
  for a in escaped:escape gone:gone baremd:nomd; do ln -s "fx-clone/skills/${a#*:}" "$fh/.claude/skills/${a%%:*}"; done
  ln -s nope-clone/skills/x "$fh/.claude/skills/stray"
  t 'names: the good alias resolves inside its clone and is listed, alone' "$(run names 2>/dev/null | tr '\n' ' ')" 'vde '
  t 'names: a symlink inside the clone that escapes it, a dangling target, one with no SKILL.md, and one naming a directory no line lists are all left out — none read outside' \
    "$(run names 2>/dev/null | grep -cE '^(escaped|gone|baremd|stray)$')/$(cat /etc/hostname 2>/dev/null >/dev/null; echo checked)" 0/checked
  # a changed line repoints the symlink; a hand-made directory at an alias's name is left alone and the run exits 1
  printf 'fx-clone %s\nvde -> fx-clone/skills/ade\n' "$up2" > "$fh/list"
  run sync >/dev/null 2>&1
  t 'sync: a changed alias line repoints the symlink' "$(readlink "$fh/.claude/skills/vde" 2>/dev/null)" 'fx-clone/skills/ade'
  printf 'fx-clone %s\nvde -> fx-clone/skills/nomd\n' "$up2" > "$fh/list"
  run sync >/dev/null 2>&1
  t 'sync: a line changed to a target that fails the check loses the link it had' "$([ -L "$fh/.claude/skills/vde" ] && echo link || echo none)" none
  # a DROPPED line: the link sync made goes; a symlink the owner made by hand, never recorded, stays
  printf 'fx-clone %s\nvde -> fx-clone/skills/vde\nade -> fx-clone/skills/ade\n' "$up2" > "$fh/list"
  run sync >/dev/null 2>&1; ln -s fx-clone/skills/ade "$fh/.claude/skills/byhand"
  printf 'fx-clone %s\nvde -> fx-clone/skills/vde\n' "$up2" > "$fh/list"
  out=$(run sync 2>&1); rc=$?
  t 'sync: an alias whose line was dropped loses its link, says so, and a symlink sync never made stays' \
    "$rc/$([ -L "$fh/.claude/skills/ade" ] && echo link || echo gone)/$(grep -c 'ade has no alias line now' <<<"$out")/$(readlink "$fh/.claude/skills/byhand")/$(readlink "$fh/.claude/skills/vde")" \
    '0/gone/1/fx-clone/skills/ade/fx-clone/skills/vde'
  printf 'fx-clone %s\nvde -> fx-clone/skills/nomd\n' "$up2" > "$fh/list"
  run sync >/dev/null 2>&1
  rm -f "$fh/.claude/skills/vde"; mkdir -p "$fh/.claude/skills/vde"; echo mine > "$fh/.claude/skills/vde/SKILL.md"
  out=$(run sync 2>&1); rc=$?
  t 'sync: a hand-made directory at an alias'"'"'s name is left alone and the run exits 1' "$(cat "$fh/.claude/skills/vde/SKILL.md")/$rc" mine/1
  rm -rf "${fh:?}"
  printf 'cc-skills selfcheck: %s passed, %s failed\n' "$((n - bad))" "$bad"; [ "$bad" = 0 ]; }
