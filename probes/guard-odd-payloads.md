model: sonnet
target: cc-guard as a PreToolUse hook fed malformed and odd hook payloads
turns: 40
---
`cc-guard` is a Claude Code PreToolUse hook: it reads ONE JSON object on stdin — the shape is
`{"tool_name":"Bash","tool_input":{"command":"…"},"cwd":"…"}` (for Write/Edit/Read: `"tool_input":{"file_path":"…"}`)
— and answers with exit 0 (allowed) or exit 2 and a reason on stderr (denied). Its header says it applies when
CC_ROLE=worker|member|steward is set or the cwd is under a dir marked .cc/track. It must never crash: a hook that
dies leaves the harness with no answer. Run it as `printf '%s' '<json>' | CC_ROLE=worker cc-guard; echo rc=$?`
and read stderr too. Feed it:

1. Empty stdin; a bare `{}`; `[]`; `null`; a string; invalid JSON (`{"tool_name":`); 1 MB of `x`.
2. `tool_name` missing, `tool_name` an integer, an unknown tool name, `tool_input` missing, `tool_input` a string.
3. Bash with `command` empty, `command` an integer, a 200 000-character command, a command holding a NUL byte (build it with printf, do not paste it),
   one that is only whitespace, one that is a heredoc (`cat <<EOF … EOF`).
4. Write with `file_path` empty, relative (`../../x`), a path under /tmp, a path under $HOME, a path with a
   newline; then the same for Read.
5. `cwd` missing, `cwd` pointing at a directory that does not exist, `cwd` = "/".
6. The same three payloads with CC_ROLE unset, and with CC_ROLE=banana: the header says only the three roles gate.
7. Run `cc-guard` with an argument (`cc-guard --help`, `cc-guard foo`) — what does it do with argv?

A finding is any traceback or a non-{0,2} exit code, an exit 2 with an EMPTY reason, a deny whose reason names a
rule the payload cannot have matched, or an allow (exit 0) on something the header lists as a deny for a worker
(merging, pushing, host changes, the box's secrets) — say exactly which line of the header. A deny with a true
reason is the tool working.
