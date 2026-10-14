# shellcheck shell=bash disable=SC2154,SC2034
# cc-units's selfcheck cases, moved out of bin/cc-units. That tool's selfcheck() sources this file, whose
# definition replaces it, and then calls it: the cases run in the tool's own shell, with its functions and
# globals, as they did when the body sat there. SC2154/SC2034 are off because those globals live in bin/cc-units.

selfcheck(){
  local n=0 f=0 u en st he re out d pa tok T dn runs
  k(){ n=$((n+1)); if [ "$1" = 0 ]; then echo "  ok   $2"; else echo "  FAIL $2"; f=$((f+1)); fi; }
  t(){ if "$@" >/dev/null 2>&1; then echo 0; else echo 1; fi; }   # a check that PRINTS (jq -e) must not leak into the verdict
  nt(){ if "$@" >/dev/null 2>&1; then echo 1; else echo 0; fi; }  # …and one that must NOT hold
  k "$(t jq -e . "$M")" "manifest is valid json"
  # …and so is every manifest a landing reads, the overlay's own included — nothing else lints that one on a
  # bare box, and unreadable it would declare no unit at all without saying so
  k "$(t lint_manifests)" "every manifest a landing reads is valid json"
  # #1325: the hostdoor relay and its timers stay off on the hub — their core rows say owner, whatever the overlay does
  for u in cc-hostdoor-relay.service cc-hostdoor-queries.timer cc-hostdoor-sync.timer; do
    k "$(t test "$(cell "$u" enable)" = owner)" "$u answers enable=owner, so a landing never switches it on"
  done
  k "$(t test "$(rows | wc -l)" -gt 0)" "manifest has rows"
  # every declared unit exists, and every unit file is declared: adding a file without a row must FAIL, loudly
  out=""; while IFS=$'\t' read -r u _; do [ -f "$UD/$u" ] || out="$out $u"; done < <(rows)
  k "$(t test -z "$out")" "every manifest row has a unit file —${out:- none missing}"
  out=""; for u in "$UD"/*; do [ -f "$u" ] || continue; rows | cut -f1 | grep -qxF "$(basename "$u")" || out="$out $(basename "$u")"; done
  k "$(t test -z "$out")" "every unit file has a manifest row —${out:- none missing}"
  # the field vocabulary: a typo in a policy word must not read as "nothing to do"
  out=""; while IFS=$'\t' read -r u en st he re; do
    case "$en" in required|owner|timer) ;; *) out="$out $u:enable=$en";; esac
    case "$st" in now|no-block|none) ;; *) out="$out $u:start=$st";; esac
    case "$he" in active|not-failed|none) ;; *) out="$out $u:health=$he";; esac
    case "$re" in restart|rearm|owner|none) ;; *) out="$out $u:restart=$re";; esac
  done < <(rows)
  k "$(t test -z "$out")" "every policy word is one of the known values —${out:- all known}"
  # a .timer is rearm and a .service is never rearm: the whole point of the field. The exception is a timer the
  # OWNER switches on (enable=owner): it is linked but off, and re-arming it on a landing would start the very
  # thing they have not switched on yet — so the landing records the action for them instead.
  out=""; while IFS=$'\t' read -r u en st he re; do
    case "$u" in
      *.timer)   if [ "$en" = owner ]; then [ "$re" = owner ] || out="$out $u"; else [ "$re" = rearm ] || out="$out $u"; fi;;
      *.service) [ "$re" = rearm ] && out="$out $u";;
    esac
  done < <(rows)
  k "$(t test -z "$out")" "every timer re-arms, bar one the owner switches on, and no service does —${out:- correct}"
  # the proven cost, 2026-08-31: editing cc-audit.timer's OnCalendar restarts and re-arms the TIMER
  out=$(restart_for core/config/systemd-user/cc-audit.timer)
  k "$(t grep -qx 'cc-audit.timer	rearm' <<<"$out")" "a changed .timer file re-arms that timer (#86's silent switch-off)"
  # the first .path row (cc-model.path, #953): an edited path file restarts that path unit, so its new watch list is live
  out=$(restart_for core/config/systemd-user/cc-model.path)
  k "$(t grep -qx 'cc-model.path	restart' <<<"$out")" "a changed .path file restarts that path unit"
  # and a changed script still reaches the unit whose ExecStart runs it
  out=$(restart_for core/bin/cc-slack)
  k "$(t grep -qx 'cc-slackd.service	restart' <<<"$out")" "a changed script restarts the unit whose ExecStart runs it"
  out=$(restart_for core/bin/cc-rc)
  k "$(t grep -qx 'tmux-main.service	owner' <<<"$out")" "the shared tmux server is reported as the owner's action, never restarted"
  out=$(restart_for core/bin/cc-audit)
  k "$(t grep -qx 'cc-audit.service	none' <<<"$out")" "a timer-driven oneshot's script comes back as none, said out loud rather than omitted — silence is what lets the caller's own name test restart it anyway"
  # a caller gates on this: "nothing to restart" must exit 0, or every landing that touches no unit reads as failed
  out=$(restart_for core/docs/DESIGN.md)
  k "$(t test -z "$out")" "a change no row and no ExecStart names comes back empty"
  "$0" restart-for core/docs/DESIGN.md >/dev/null 2>&1; k $? "…and exits 0 saying so"
  "$0" restart-for core/config/systemd-user/cc-audit.timer >/dev/null 2>&1; k $? "restart-for exits 0 when it does match"

  # ---- a unit whose code is a DIRECTORY, in a fixture tree shaped like a box: a core tree inside an overlay, each
  # with its own manifest. This is the case that went wrong on 2026-09-06 — a merged change moved a server's modules
  # and web assets, its ExecStart file did not move, and the deploy left the old process serving the new version.
  T=$(mktemp -d)
  mkdir -p "$T/core/config/systemd-user" "$T/config/systemd-user" "$T/elsewhere"
  cat > "$T/core/config/units.json" <<'J'
{ "units": [ { "unit": "tool.service", "enable": "required", "start": "now", "health": "active", "restart": "restart" } ],
  "daemons": [ { "daemon": "graphs", "runs": "bin/graphs", "paths": ["bin/graphs", "web/graphs"],
                 "restart": ["bin/graphs", "serve"] } ] }
J
  cat > "$T/config/units.json" <<'J'
{ "units": [ { "unit": "dash.service",  "restart": "restart", "enable": "owner", "paths": ["dashboard", "bin-private/dashsrc"] },
             { "unit": "quiet.service", "restart": "restart", "paths": ["quiet"] },
             { "unit": "tool.service", "enable": "owner" } ],
  "daemons": [ { "daemon": "site", "runs": "bin-private/site", "restart": "owner" } ] }
J
  printf '[Service]\nExecStart=%%h/bin/tool run\n' > "$T/core/config/systemd-user/tool.service"
  # its ExecStart names NOTHING the cases below change: every hit on this unit is a declared path's doing
  printf '[Service]\nExecStart=%%h/bin/dashd --foreground\n' > "$T/config/systemd-user/dash.service"
  rf(){ CC_UNITS_MANIFEST="$T/core/config/units.json" CC_UNITS_DIR="$T/core/config/systemd-user" \
        CC_UNITS_OVERLAY="$T" "$0" restart-for "$@"; }
  out=$(rf dashboard/server.py dashboard/web/app.js docs/note.md)
  k "$(t grep -qx 'dash.service	restart' <<<"$out")" "a change under a unit's declared directory restarts it, with its ExecStart file untouched"
  k "$(nt grep -q 'quiet.service' <<<"$out")" "…and a unit whose declared paths did not change is left alone"
  out=$(rf bin-private/dashsrc)
  k "$(t grep -qx 'dash.service	restart' <<<"$out")" "a declared path that is a FILE counts too, not only a directory"
  out=$(rf docs/note.md README.md dashboardish.md)
  k "$(t test -z "$out")" "a change outside every declared path restarts nothing — and a declared path matches at a / , not as a string prefix"
  out=$(rf core/bin/tool)
  k "$(t grep -qx 'tool.service	restart' <<<"$out")" "the core tree's own rows still answer for the file their ExecStart runs, from inside an overlay"
  out=$(rf --root "$T/elsewhere" dashboard/server.py core/bin/tool)
  k "$(t test -z "$out")" "…and landing ANOTHER repo restarts none of them: a path is declared relative to the tree that declares it"
  # ---- and the same questions for a process NO unit owns. systemctl knows nothing about one, so every case
  # above is blind to it: on 2026-09-07 a landing restarted each unit it touched, reported "deployed", and the
  # graphs server went on answering from the pre-merge code because a shell had started it.
  df(){ CC_UNITS_MANIFEST="$T/core/config/units.json" CC_UNITS_DIR="$T/core/config/systemd-user" \
        CC_UNITS_OVERLAY="$T" "$0" daemons-for "$@"; }
  out=$(df core/bin/graphs)
  k "$(t grep -qx 'graphs	core/bin/graphs serve	core/bin/graphs' <<<"$out")" "a daemon row answers with the argv that brings it back and the file it runs, each prefixed by the tree that declares it"
  out=$(df core/web/graphs/app.js)
  k "$(t grep -q '^graphs	' <<<"$out")" "…and a change to the ASSETS it serves hits it too, though the file it runs never moved — the shape that left a merged server on old code"
  out=$(df core/docs/note.md graphsish.md)
  k "$(t test -z "$out")" "a change outside every declared path names no daemon"
  df core/docs/note.md >/dev/null 2>&1; k $? "…and exits 0 saying so"
  out=$(df bin-private/site)
  k "$(t grep -qx 'site	owner	bin-private/site' <<<"$out")" "an overlay's own daemon is read, its paths default to the file it runs, and restart=owner comes back as that word — the landing names it instead of restarting it"
  out=$(df --root "$T/elsewhere" core/bin/graphs bin-private/site)
  k "$(t test -z "$out")" "…and landing ANOTHER repo declares none of them"

  # `policy` used to answer only from $M — a unit an overlay declares (its own enable=owner among them) came back
  # empty, and cc-land's unit_policy(u, "enable") == "owner" check never held: a landing enabled a brand new
  # overlay timer straight past the owner (#679's review). It must read every manifest a landing does.
  pl(){ CC_UNITS_MANIFEST="$T/core/config/units.json" CC_UNITS_DIR="$T/core/config/systemd-user" \
        CC_UNITS_OVERLAY="$T" "$0" policy "$@"; }
  k "$(t test "$(pl tool.service enable)" = required)" "policy answers a core-declared field from the core manifest"
  k "$(t test "$(pl dash.service enable)" = owner)" "…and an OVERLAY-declared field too — the gap #679's review caught"
  k "$(t test "$(pl tool.service enable)" = required)" "a unit both manifests name answers from core — the overlay only fills a field core leaves blank"
  k "$(t test -z "$(pl quiet.service restart_typo)")" "…and a field no row names comes back empty, not a stale answer"
  # owner 10-13: declaring a unit in the overlay IS wanting it, so a row there with no enable word answers
  # `required` (a landing enables it); an explicit owner stays owner, and a unit with no row stays empty (owner)
  k "$(t test "$(pl quiet.service enable)" = required)" "an overlay row with no enable word answers required, not the empty answer a landing cards"
  k "$(t test "$(pl dash.service enable)" = owner)" "…while an overlay row that says owner still answers owner"
  k "$(t test "$(pl quiet.service start)" = "")" "…and only enable is filled: another blank overlay field stays empty"
  k "$(t test -z "$(pl no-such.service enable)")" "…and a unit no manifest declares comes back empty, not an error"
  unset -f pl

  # a manifest with a typo in it must not read as "this tree declares nothing": jq complains on stderr and keeps
  # going, and an empty answer that exits 0 is what a landing believes
  printf '{ this is not valid json\n' > "$T/config/units.json"
  out=$(rf dashboard/server.py 2>&1); re=$?
  k "$(t test "$re" -ne 0)" "an unreadable overlay manifest exits non-zero — an empty answer here is a landing's silent guess"
  k "$(t grep -q 'not valid json' <<<"$out")" "…and says which file, on stderr"
  out=$(CC_UNITS_MANIFEST="$T/core/config/units.json" CC_UNITS_DIR="$T/core/config/systemd-user" \
        CC_UNITS_OVERLAY="$T" "$0" policy quiet.service enable 2>/dev/null)
  k "$(t test -z "$out")" "…and policy hears no row in an unreadable overlay manifest: empty, which a landing cards as owner"
  out=$(df core/bin/graphs 2>&1); re=$?
  k "$(t test "$re" -ne 0)" "…and daemons-for refuses it the same way: a daemon a landing cannot be told about is one it leaves on the old code"
  rm -rf "$T"; unset -f rf df

  # the rows a landing reads — the overlay's included — must name a policy it knows, and declare plain relative paths
  out=""; while IFS=$'\t' read -r u re d pa; do
    case "$re" in restart|rearm|owner|none) ;; *) out="$out $u:restart=$re";; esac
    for tok in $pa; do case "$tok" in /*|*..*|*'*'*|*'?'*) out="$out $u:paths=$tok";; esac; done
  done < <(prows)
  k "$(t test -z "$out")" "every row a landing reads names a restart policy, over plain relative paths —${out:- all do}"
  # …and on a box that keeps an overlay, a unit file of its own with no row has no restart policy at all, which is
  # exactly how a landing leaves a merged change on the old process.
  if [ -n "$OV" ] && [ -f "$OV/config/units.json" ]; then
    out=""; for u in "$OV"/config/systemd-user/*; do [ -f "$u" ] || continue
      jq -r '.units[].unit' "$OV/config/units.json" | grep -qxF "$(basename "$u")" || out="$out $(basename "$u")"; done
    k "$(t test -z "$out")" "every overlay unit file has a row in the overlay manifest —${out:- none missing}"
  fi
  # the daemon rows a landing reads: each names a file to RUN — that is how the process is recognised — a restart
  # policy it knows, and plain relative paths. `restart` is an argv joined by spaces here, so a token with a space
  # in it would silently become two arguments.
  out=""; while IFS=$'\t' read -r dn runs re pa; do
    [ -n "$dn" ] || continue
    case "$dn" in '?') out="$out ?:daemon";; esac
    case "$runs" in ''|*'?') out="$out $dn:runs=$runs";; /*|*..*) out="$out $dn:runs=$runs";; esac
    case "$re" in owner|none) ;; '?'|'') out="$out $dn:restart=$re";; /*|*..*) out="$out $dn:restart=$re";; esac
    for tok in $pa; do case "$tok" in /*|*..*|*'*'*|*'?'*) out="$out $dn:paths=$tok";; esac; done
  done < <(dprows)
  k "$(t test -z "$out")" "every daemon row a landing reads names a file to run, a restart it knows and plain relative paths —${out:- all do}"
  # the row the whole field exists for: nothing in systemd owns the graphs server, so without a row here a landing
  # that changes it restarts every unit, says "deployed", and leaves the old process answering (2026-09-07)
  k "$(t test -n "$(jq -r '.daemons[]? | select(.daemon=="cc-graphs") | .runs' "$M")")" \
    "the graphs server is declared a daemon — no unit owns it, and a landing has to be told that"

  # an unlinked unit is a fault even for a `timer` row, which every other test skips
  out=$(CC_UNITS_LINKDIR="$UD/no-such-link-dir" check 2>&1)   # a path that cannot exist: no temp dir to leak
  k "$(t grep -q 'cc-audit.service=unlinked' <<<"$out")" "an unlinked timer-driven .service is reported, not skipped"
  # a timer whose own service is running shows NEXT '-' until the run ends: armed, not a fault (the 03:30 monthly audit
  # reported cc-audit.timer=not-armed — itself, mid-run, 2026-09-01). sc is a function, so a subshell fakes systemd.
  fake(){ local svc="$1"; shift; case "$1" in list-timers) ;; is-active) case "$2" in cc-audit.service) echo "$svc";; *) echo active;; esac;; is-failed) echo active;; *) echo enabled;; esac; }
  out=$( sc(){ fake activating "$@"; }; CC_UNITS_LINKDIR="$UD" check 2>&1 )
  k "$(nt grep -q 'cc-audit.timer=not-armed' <<<"$out")" "a timer with no NEXT whose service is running is armed, not a fault"
  out=$( sc(){ fake inactive "$@"; }; CC_UNITS_LINKDIR="$UD" check 2>&1 )
  k "$(t grep -q 'cc-audit.timer=not-armed' <<<"$out")" "…and with its service idle it is not-armed, as before"
  # a `health: active` row whose ExecCondition said no is skipped, not down: tmux-main.service is inactive whenever the
  # main tmux server runs outside it (10-13: listed as tmux-main.service=inactive with the server up)
  skfake(){ case "$1:${2:-}:${3:-}:${5:-}" in
      is-active:tmux-main.service::) echo inactive;; is-active:*) echo active;; is-failed:*) echo active;; list-timers:*) ;;
      show:-p:Result:tmux-main.service) echo "$SKIP";; show:*) echo success;; *) echo enabled;; esac; }
  out=$( sc(){ skfake "$@"; }; SKIP=exec-condition; CC_UNITS_LINKDIR="$UD" check 2>&1 )
  k "$(nt grep -q 'tmux-main.service=' <<<"$out")" "a core unit its ExecCondition skipped is not down"
  out=$( sc(){ skfake "$@"; }; SKIP=success; CC_UNITS_LINKDIR="$UD" check 2>&1 )
  k "$(t grep -q 'tmux-main.service=inactive' <<<"$out")" "…but the same unit stopped after a start that ran is"
  # the overlay's own rows (10-01: a linked, never-enabled library editor stayed down 3.5 h after a restart). Its own
  # fixture tree: one unit each that is reported, and one each that is kept quiet.
  T=$(mktemp -d); mkdir -p "$T/config/systemd-user"; d="$T/config/systemd-user"
  printf '[Service]\nType=oneshot\n[Install]\nWantedBy=default.target\n' > "$d/ov-boot.service"   # linked, never enabled
  printf '[Service]\nType=oneshot\n' > "$d/ov-bytimer.service"                                    # linked, no [Install]: its timer's
  printf '[Service]\nType=simple\n[Install]\nWantedBy=default.target\n' > "$d/ov-down.service"     # enabled, not running
  printf '[Service]\nType=simple\n[Install]\nWantedBy=default.target\n' > "$d/ov-up.service"       # enabled and running
  printf '[Service]\nType=oneshot\n[Install]\nWantedBy=default.target\n' > "$d/ov-ran.service"     # enabled oneshot, done
  printf '[Service]\nType=simple\n[Install]\nWantedBy=default.target\n' > "$d/ov-wk@.service"      # a template; its instances are units
  ln -s /dev/null "$d/ov-masked.service"                                                          # masked: no [Install] to read
  printf '[Service]\nType=oneshot\n' > "$d/ov-gone.service"                                       # no [Install], and systemd cannot load it
  # a timer-driven .service can have [Install] and still be started only by its timer
  printf '[Service]\nType=oneshot\n[Install]\nWantedBy=default.target\n' > "$d/ov-timed.service"    # linked; its timer is on and running
  printf '[Service]\nType=oneshot\n[Install]\nWantedBy=default.target\n' > "$d/ov-stale.service"    # linked; its timer is enabled but stopped
  printf '[Timer]\nOnBootSec=1min\n[Install]\nWantedBy=timers.target\n' > "$d/ov-owneroff.timer"   # enable=owner, switched off (a finished move)
  printf '[Timer]\nOnBootSec=1min\n[Install]\nWantedBy=timers.target\n' > "$d/ov-owneron.timer"    # enable=owner, enabled but not running
  printf '[Service]\nType=simple\n[Install]\nWantedBy=default.target\n' > "$d/ov-skip.service"     # enabled; its condition said no
  printf '[Service]\nType=simple\n[Install]\nWantedBy=default.target\n' > "$d/ov-never.service"    # enabled, never started: no condition ran
  printf '[Service]\nType=oneshot\n[Install]\nWantedBy=default.target\n' > "$d/ov-stimed.service"  # linked; a static, running timer starts it
  printf '{"units":[{"unit":"ov-boot.service"},{"unit":"ov-bytimer.service"},{"unit":"ov-down.service"},{"unit":"ov-up.service"},{"unit":"ov-ran.service"},{"unit":"ov-tpl@.service"},{"unit":"ov-wk@reports.service"},{"unit":"ov-wk@live.service"},{"unit":"ov-masked.service"},{"unit":"ov-gone.service"},{"unit":"ov-timed.service"},{"unit":"ov-stale.service"},{"unit":"ov-owneroff.timer","enable":"owner"},{"unit":"ov-owneron.timer","enable":"owner"},{"unit":"ov-skip.service"},{"unit":"ov-never.service"},{"unit":"ov-stimed.service"}]}\n' > "$T/config/units.json"
  ovfake(){ case "$1:$2" in
      is-enabled:ov-boot.service|is-enabled:ov-bytimer.service|is-enabled:ov-timed.service|is-enabled:ov-stale.service|is-enabled:ov-stimed.service) echo linked;;
      is-enabled:ov-stimed.timer) echo static;;
      is-enabled:ov-wk@reports.service|is-enabled:ov-owneroff.timer) echo disabled;;
      is-enabled:ov-masked.service) echo masked;; is-enabled:ov-gone.service) echo not-found;;
      is-enabled:*) echo enabled;;
      is-active:ov-down.service|is-active:ov-ran.service|is-active:ov-wk@reports.service) echo inactive;;
      is-active:ov-stale.timer|is-active:ov-owneroff.timer|is-active:ov-owneron.timer|is-active:ov-skip.service|is-active:ov-never.service) echo inactive;; is-active:*) echo active;;
      is-failed:*) echo inactive;;
      show:-p) case "$3:$5" in TriggeredBy:ov-timed.service) echo ov-timed.timer;; TriggeredBy:ov-stale.service) echo ov-stale.timer;; TriggeredBy:ov-stimed.service) echo ov-stimed.timer;;
                 TriggeredBy:ov-boot.service) echo ov-boot.path;; ConditionResult:ov-skip.service|ConditionResult:ov-never.service) echo no;; ConditionResult:*) echo yes;;
                 ConditionTimestampMonotonic:ov-never.service) echo 0;; ConditionTimestampMonotonic:*) echo 51234567;; esac;;
      *) ;; esac; }
  out=$( sc(){ ovfake "$@"; }; OV="$T"; CC_UNITS_LINKDIR="$d" check 2>&1 )
  k "$(t grep -q 'ov-boot.service=not-enabled(linked)' <<<"$out")" "an overlay unit linked but never enabled is reported"
  k "$(nt grep -q 'ov-bytimer' <<<"$out")" "…but one with no [Install] is its timer's to start, not a fault"
  k "$(t grep -q 'ov-down.service=inactive' <<<"$out")" "an enabled overlay service that is not running is reported down"
  k "$(nt grep -qE 'ov-up|ov-ran|ov-tpl|ov-wk@live' <<<"$out")" "…while a running one, a oneshot that has run and a template are not"
  # an instance of a template is a unit of its own (the 922 review: `*@*` hid a disabled worker@reports.service)
  k "$(t grep -q 'ov-wk@reports.service=not-enabled(disabled)' <<<"$out")" "…but a declared instance of a template that is not enabled is"
  k "$(t grep -q 'ov-masked.service=not-enabled(masked)' <<<"$out")" "…and so is a masked one, though its /dev/null has no [Install]"
  k "$(t grep -q 'ov-gone.service=not-enabled(not-found)' <<<"$out")" "…and one with no [Install] that systemd cannot load"
  k "$(nt grep -q 'ov-timed' <<<"$out")" "a linked service with [Install] that an enabled, running timer starts is not a fault"
  k "$(t grep -q 'ov-stale.service=not-enabled(linked)' <<<"$out")" "…but one whose timer is stopped is (and so is one only a .path triggers: ov-boot above)"
  k "$(nt grep -q 'ov-owneroff' <<<"$out")" "an enable=owner overlay row the owner left off is not a fault"
  k "$(t grep -q 'ov-owneron.timer=inactive' <<<"$out")" "…but once enabled it must be up"
  k "$(nt grep -q 'ov-skip' <<<"$out")" "an enabled overlay service its condition skipped is not down (ov-down above still is)"
  # systemd reports ConditionResult=no for a unit whose conditions were never evaluated (the #1338 review)
  k "$(t grep -q 'ov-never.service=inactive' <<<"$out")" "…but an enabled service never started (ConditionResult=no, no condition timestamp) is down"
  k "$(nt grep -q 'ov-stimed' <<<"$out")" "a linked service a static, running timer starts is not a fault either"
  rm -rf "$T"
  # a unit the installer enables must have somewhere to be enabled FROM
  out=""; while IFS=$'\t' read -r u en st he re; do
    [ "$en" = required ] || continue
    case "$u" in *.timer) continue;; esac
    grep -q '^\[Install\]' "$UD/$u" 2>/dev/null || out="$out $u"
  done < <(rows)
  k "$(t test -z "$out")" "every required .service has an [Install] section —${out:- all do}"
  # tmux-main's ExecCondition, run against a throwaway tmux server on its own socket dir (env -u TMUX, or tmux would
  # talk to the live server this session sits in). A "main" the unit does not own reads as up and skips the start
  # (2026-10-12: every deploy failed on "duplicate session: main"); no server, or only a "main2", still starts one.
  if command -v tmux >/dev/null; then
    u=$(sed -n 's/^ExecCondition=//p' "$UD/tmux-main.service")
    T=$(mktemp -d /tmp/ccu.XXXXXX); mkfifo "$T/hold"
    tx(){ env -u TMUX TMUX_TMPDIR="$T" "$@"; }
    k "$(t tx bash -c "$u")" "tmux-main starts a server when none runs (a fresh boot, or the old server died)"
    tx tmux new-session -d -s main2 "cat $T/hold"
    k "$(t tx bash -c "$u")" "…and when the only session is main2, which a prefix match would have taken for main"
    tx tmux new-session -d -s main "cat $T/hold"
    k "$(nt tx bash -c "$u")" "a session main started outside the unit counts as up: the start is skipped, not failed"
    : > "$T/hold"   # both panes read EOF and exit; the empty server exits with them
    for _ in 1 2 3 4 5 6 7 8 9 10; do tx tmux has-session 2>/dev/null || break; sleep 0.2; done
    rm -rf "$T"
  else
    k 1 "tmux is installed, so tmux-main's ExecCondition can be checked"
  fi
  echo "cc-units selfcheck: $((n - f)) passed, $f failed"
  [ "$f" -eq 0 ]
}
