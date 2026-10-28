# crewboard-tui

Read-only terminal viewer for the crewboard message board.
It runs the `crewboard` CLI (`sub`, `topics`); the tasks view also runs `tasks-axi` and reads `state/*.status` files, and the decision queue view reads `state/decision-queue/*.rec`. It never publishes or writes.
The left pane lists topics with unread counts; the right pane shows messages.
The background is transparent; colors come from `../tui-theme/theme.ts`.

```bash
bun install
bun crewboard-tui.ts
```

Each topic shows its one-line summary under its name, and the message pane shows it in full at the top.
The summaries come from `crewboard topics --summary --json`, read every 10 seconds. A topic without a summary, or a board that has none, shows nothing extra.

```bash
bun test   # the summary reader, against a fake crewboard command
```

## Tasks view

Press `t` (or start with `--tasks`) for one read-only view over every firstmate home: its `tasks-axi list` backlog plus `state/*.status` logs.
Each agent (an in-flight task) shows its current task, the next queued items of its project, its open decision, and the time since its last status event.
Stalled agents (no status event for 30 min while in flight; `paused`, `done` and `failed` do not count) are pinned on top, longest quiet first; the list shows the top 10 until you press Enter on its head.
Below, agents are grouped by mate (home) and project, collapsed by default. A filter opens the matching groups. Only the visible rows are rendered.

Keys: `↑↓/jk` move, `Enter`/`Space` open or close, `e`/`E` open or close all groups, `/` filter (Enter keeps it, Esc clears), `s` stalled only, `r` reload, `t` back to the board.
A decision is the latest `needs-decision` or `blocked` status line without a matching `resolved` line for its key.

Homes come from the arguments, else `$CREWBOARD_TASKS_HOMES` (colon list), else `~/.treehouse/firstmate-*/<n>/firstmate`.
`$TASKS_AXI_BIN` overrides the `tasks-axi` command. `--stall-min N` sets the stall time.

```bash
bun crewboard-tui.ts --once [--expand] [--filter TEXT] [--width N] [home...]   # plain snapshot, then exit
bun fixture.ts /tmp/fx 1500 30                                                  # disposable fake homes for a demo
```

## Decision queue view

Press `d` (or start with `--queue`) for the decision queue of every home: the `state/decision-queue/*.rec` records that `fm-decision-queue.sh` writes.
Each mate (home) shows its count per state, then one row per record: origin, key, note, and its age.
A `queued` record shows as open, `dispatched` as in progress, `closed` as answered (close reason `answered`) or closed, and `stuck` as stuck.
Open, in progress and stuck rows count from enqueue; answered and closed rows count from the close. The view reloads every 15 seconds and never edits a record.

Keys: `↑↓/jk` move, `r` reload, `t` tasks, `d` back to the view you came from. `bun crewboard-tui.ts --once --queue [home...]` prints a plain snapshot.
