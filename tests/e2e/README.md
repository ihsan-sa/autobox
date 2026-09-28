# tests/e2e: the suite's stanzas, one file each

`tests/selftest.sh` is one long suite of stanzas. The stanzas with a body of their own (the ones that drive tools
end to end, not just `chk <tool>`) are also here, one file per stanza, so the lander can run the one a change
reaches instead of the whole suite.

- `split.py` writes every `<slug>.sh` here from `selftest.sh`; `split.py --check` writes nothing and fails naming
  each file that differs. The files are generated, so edit `selftest.sh` and rerun `split.py`, never a file here.
- `lib.sh` is the shared setup every file sources: the suite's preamble without its reporting machinery.
- Each `<slug>.sh` runs alone: `tests/e2e/<slug>.sh`. It runs the base fixture stanzas and the top-level lines that
  come before its stanza in `selftest.sh`, then the stanza itself.

## The checks, and why each has its class

`tests/LANDING.toml` names every check the lander can select for this tree: the static checks, each tool's
selfcheck, and one `e2e-<slug>` per file here. The class says where and when a check runs:

- `static` reads files only, with no process state, no `~/.cc` and no tmux, so it runs on every change it owns.
- `host` is today's run: on the host, with the environment scrubbed, serially per repo, before the merge.
- `hermetic` is for checks proven to pass in the lander's sandbox. None is yet, so every selfcheck and every
  e2e file starts as `host` and moves only after that proof.

`check-sh` is the whole of `tests/check.sh`, because its agent-frontmatter, unit and prefetch-window blocks cannot
run on their own. It owns only the paths no narrower check covers.

| check | class | why that class |
|---|---|---|
| `shellcheck-box-status` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-audit` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-bin-at` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-boot` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-boot-notify` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-checkpoint` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-config` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-evals` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-gh-token` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-github-deny` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-green` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-guard` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-heartbeat` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-limit` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-loop` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-model` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-msg` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-notify` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-pause` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-publish` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-rc` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-refusals` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-sandbox` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-settings` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-skills` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-started` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-suites` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-tier` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-trust` | static | reads one file: bash -n and shellcheck |
| `shellcheck-cc-units` | static | reads one file: bash -n and shellcheck |
| `shellcheck-ccbox` | static | reads one file: bash -n and shellcheck |
| `shellcheck-gh` | static | reads one file: bash -n and shellcheck |
| `shellcheck-git-remote-cc-github-deny` | static | reads one file: bash -n and shellcheck |
| `shellcheck-ccbox-entrypoint.sh` | static | reads one file: bash -n and shellcheck |
| `shellcheck-ccbox-init-firewall.sh` | static | reads one file: bash -n and shellcheck |
| `shellcheck-install.sh` | static | reads one file: bash -n and shellcheck |
| `py-compile-cc-approve` | static | reads the file only: python compiles it |
| `py-compile-cc-ask` | static | reads the file only: python compiles it |
| `py-compile-cc-board` | static | reads the file only: python compiles it |
| `py-compile-cc-brief` | static | reads the file only: python compiles it |
| `py-compile-cc-broker` | static | reads the file only: python compiles it |
| `py-compile-cc-bundle` | static | reads the file only: python compiles it |
| `py-compile-cc-context` | static | reads the file only: python compiles it |
| `py-compile-cc-digest` | static | reads the file only: python compiles it |
| `py-compile-cc-docs` | static | reads the file only: python compiles it |
| `py-compile-cc-failures` | static | reads the file only: python compiles it |
| `py-compile-cc-fence` | static | reads the file only: python compiles it |
| `py-compile-cc-graphs` | static | reads the file only: python compiles it |
| `py-compile-cc-handoff` | static | reads the file only: python compiles it |
| `py-compile-cc-improve` | static | reads the file only: python compiles it |
| `py-compile-cc-land` | static | reads the file only: python compiles it |
| `py-compile-cc-lib` | static | reads the file only: python compiles it |
| `py-compile-cc-mail` | static | reads the file only: python compiles it |
| `py-compile-cc-member-broker` | static | reads the file only: python compiles it |
| `py-compile-cc-member-import` | static | reads the file only: python compiles it |
| `py-compile-cc-member-v2` | static | reads the file only: python compiles it |
| `py-compile-cc-name` | static | reads the file only: python compiles it |
| `py-compile-cc-native` | static | reads the file only: python compiles it |
| `py-compile-cc-queue-steward` | static | reads the file only: python compiles it |
| `py-compile-cc-reconcile` | static | reads the file only: python compiles it |
| `py-compile-cc-rename` | static | reads the file only: python compiles it |
| `py-compile-cc-replay` | static | reads the file only: python compiles it |
| `py-compile-cc-scope` | static | reads the file only: python compiles it |
| `py-compile-cc-slack` | static | reads the file only: python compiles it |
| `py-compile-cc-spend` | static | reads the file only: python compiles it |
| `py-compile-cc-stall` | static | reads the file only: python compiles it |
| `py-compile-cc-statusline` | static | reads the file only: python compiles it |
| `py-compile-cc-task` | static | reads the file only: python compiles it |
| `py-compile-cc-time` | static | reads the file only: python compiles it |
| `py-compile-cc-tmp-reap` | static | reads the file only: python compiles it |
| `py-compile-cc-unfiled` | static | reads the file only: python compiles it |
| `py-compile-cc-vitals` | static | reads the file only: python compiles it |
| `py-compile-cc-voice` | static | reads the file only: python compiles it |
| `py-compile-cc-wakes` | static | reads the file only: python compiles it |
| `py-compile-tests` | static | reads the file only: python compiles it |
| `json-manifests` | static | jq over files, nothing else |
| `landing-data` | static | parses this manifest and the reach graph, nothing else |
| `check-sh` | host | runs every selfcheck and systemd-analyze; blocks cannot run alone |
| `selfcheck-cc` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-approve` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-ask` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-audit` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-bin-at` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-board` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-brief` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-broker` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-bundle` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-checkpoint` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-config` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-context` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-docs` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-evals` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-failures` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-fence` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-gh-token` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-github-deny` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-graphs` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-lander` | host | runs the new lander's unit cases, which start the launcher under a temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-green` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-guard` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-handoff` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-improve` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-land` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-lib` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-limit` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-loop` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-mail` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-member-broker` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-member-import` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-member-v2` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-model` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-msg` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-name` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-native` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-notify` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-pause` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-publish` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-queue-steward` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-reconcile` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-refusals` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-rename` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-replay` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-sandbox` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-scope` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-settings` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-skills` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-slack` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-spend` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-stall` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-started` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-statusline` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-suites` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-task` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-tier` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-time` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-tmp-reap` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-unfiled` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-units` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-vitals` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-voice` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `selfcheck-cc-wakes` | host | starts the tool's own processes and temp HOME; not yet proven in the sandbox |
| `e2e-cc-main-track-creation` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-cc-claim` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-checkpoint-hook` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-cc-context` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-guard` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-overlapping-handoff` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-cc-notify-escalation` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-say-go-loop` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-go-covering-note` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-finished-track-board` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-step-limit` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-usage-limits` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-limit-episode` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-resume-digest-rm` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-cc-slack-local` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-model-fallback` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-ccbox-login` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-ccbox-headless` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-cc-trust-prune` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-cc-rename` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-snapshot-readers` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-cc-publish` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-install-blank-home` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-suite-reporting` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-suite-slots` | host | drives tools end to end (tmux, git, a HOME); not yet proven in the sandbox |
| `e2e-in-sync` | static | split.py compares text it would write with the files; it runs nothing |
