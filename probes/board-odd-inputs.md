model: haiku
target: cc-board add/set/note/get/rm with odd names and values
turns: 40
---
The command is `cc-board` (run it with no arguments for the usage line; the board file is ~/.cc/boards/fx.json and a
row's brief is ~/.cc/state/fx/<row>/task.md). Try each of these against repo `fx` and read what came back AND what
the board file now says (`cc-board json fx`):

1. Row names: an empty string, a single space, `../escape`, `a/b`, `UPPER-Case`, a 200-character name, one with a
   newline in it, one starting with `-` (e.g. `--all`), unicode (`café`).
2. `cc-board add fx t1 'title' 'brief'` a second time on an existing row — does the title change, does the brief
   append, does the exit code say which?
3. `cc-board status fx t1 <word>` with `running`, `RUNNING`, `done `, `banana`, an empty string.
4. `cc-board note fx t1 <text>` with an empty note, a 5000-character note, a note with `\n` and `"` in it, then
   `cc-board show fx` and `cc-board json fx` — do they agree with each other about that note?
5. `cc-board set fx t1 <field> <value>` with a field it has never heard of, and `critical` with `maybe`.
6. `cc-board get fx nope title` and `cc-board rm fx nope` — a row that does not exist.
7. `cc-board rm fx t1` twice.
8. `cc-board add nosuchrepo r 'x' 'y'` — a repo with no board.

A finding is a traceback, a row written under a name that should have been refused, a title or status the file
does not show, or show/json disagreeing. A clear refusal is the right answer for most of these.
