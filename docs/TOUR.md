# A five-minute tour

For a person meeting the box for the first time. The detail is in [DESIGN.md](DESIGN.md) and [WORKING.md](WORKING.md).
Each diagram is also a PNG for slides, in [tour/](tour/).

## What it is

One always-on Linux machine with no screen. It runs Claude Code sessions in one tmux, and the owner drives them from
Slack on a phone or from SSH on a laptop. Each project in `~/dev` gets its own Slack channel and its own planning
session. The code that runs all this is plain shell and Python scripts; the thinking is Claude.

```mermaid
flowchart LR
  owner["Owner<br/>phone or laptop"] -->|Slack| slack["Slack workspace<br/>one channel per project"]
  owner -->|SSH| tmux
  slack <-->|cc-slack daemon| tmux["tmux on the box<br/>one window per session"]
  tmux --> repos["~/dev/&lt;project&gt;<br/>git worktrees"]
  repos -->|push, PR| gh["GitHub"]
  member["Member"] -->|their own channel| slack
```

Three ideas carry the design:

- **Scripts keep the books, Claude thinks.** Worktrees, commits, pushes, PRs, the board and notices are scripts. No
  agent sits in the middle managing the others.
- **One task, one worktree.** Every piece of work gets its own git branch and folder, so two workers never write over
  each other.
- **State lives in files.** Journals, the board, git and PRs hold the state. A session can die at any moment and the
  next one reads where it got to.

## The life of one request

The owner types "add a health check to the dashboard" in the project's channel. This is what happens.

```mermaid
sequenceDiagram
  actor O as Owner
  participant S as Slack
  participant P as Planning session
  participant W as Worker
  participant L as cc-land
  participant G as GitHub
  O->>S: message in #project
  S->>P: cc-slack daemon types it into the session
  P->>P: adds a board row, writes a brief
  P->>W: cc project track --go "brief"
  Note over W: own worktree and branch<br/>fresh context per iteration
  W->>W: works, journals, a hook commits and pushes
  W->>G: STATUS DONE, cc done opens the PR
  G-->>S: approval card in #approvals
  O-->>S: 👍, or the project lands its own PRs
  S->>L: queue the landing
  L->>L: gates, review verdict
  L->>G: squash-merge
  L->>L: install and restart what changed
  L-->>S: landed, in the track's thread
```

A small job can skip the worker: the planning session does it itself, or hands it to a subagent. Either way it ends
as a PR.

## Who does what

```mermaid
flowchart TB
  owner["Owner<br/>decides the approval list"]
  plan["Planning session, one per project<br/>plans, dispatches, lands"]
  orch["Orchestrator<br/>a peer with its own channel, for a big project"]
  worker["Worker<br/>one task, headless, ends in a PR"]
  sub["Subagent<br/>small scoped job, dies with its parent"]
  ms["Member session<br/>sandboxed to the member's own folder"]
  owner -. "@-mention only for approvals" .- plan
  plan --> worker
  plan --> sub
  plan --- orch
  orch --> worker
  ms -->|asks the box| worker
```

Sessions decide and act on their own. The owner is asked only for a short list, written in `~/CLAUDE.md`: deploys,
spend over budget, host and network changes, anything destructive, anything sent outward in the owner's name, and anything
that opens the box to the outside. A hook (`cc-guard`) enforces the list, so an agent cannot talk its way past it.

## How work is gated and landed

Nothing merges by hand. `cc-land` is the only thing that merges.

```mermaid
flowchart LR
  pr["PR open"] --> q{"Project lands<br/>its own PRs?"}
  q -->|yes| queue["landing queued"]
  q -->|no| up["owner 👍 on the card"] --> queue
  queue --> gates["gates: check.sh, selftest.sh<br/>on main merged with the PR"]
  gates -->|red| stop["stop, say why in the thread"]
  gates -->|green| rev["one review read of the diff"]
  rev -->|DO-NOT-LAND or FIX| stop
  rev -->|LAND| merge["squash-merge"] --> dep["install.sh, restart changed units"]
```

A gate result is recorded against the tree it ran on, so a tree that already passed is not tested twice. Commits and
the public mirror both refuse anything that names the private box.

## How a member gets a workspace

A member is a person the owner adds who is not the owner. They get a channel and a folder, and nothing else of the box.

```mermaid
flowchart LR
  add["cc-slack member add @person"] --> ch["#handle channel"]
  add --> dir["~/dev/handle"]
  mint["owner: cc-sandbox mint handle"] --> cred["their own Claude credential"]
  ch --> sess["member session<br/>inside a sandbox"]
  cred --> sess
  sess -->|sees| dir
  sess -. "cannot see" .-> rest["other projects, keys,<br/>config, tmux"]
```

A member session can start work only by asking the box, and it has a daily spend cap.

## Where to go next

- [DESIGN.md](DESIGN.md): why each piece is shaped the way it is.
- [WORKING.md](WORKING.md): what a session does between tasks.
- [../README.md](../README.md): installing it on a blank box.
