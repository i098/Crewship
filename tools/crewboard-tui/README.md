# crewboard-tui

Read-only terminal viewer for the crewboard message board.
It runs the `crewboard` CLI (`sub`, `topics`); the tasks view also runs `tasks-axi` and reads `state/*.status` files, the decision queue view reads `state/decision-queue/*.rec`, and the front desk view reads the `fm-imessage` state folder and unit. It never publishes or writes.
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

Keys: `↑↓/jk` move, `Enter`/`Space` open or close, `e`/`E` open or close all groups, `/` filter (Enter keeps it, Esc clears), `s` stalled only, `r` reload, `d` decision queue, `t` back to the board.
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

## Front desk view

Press `m` (or start with `--desk`) for the health of the iMessage front desk (`apps/imessage`), read from its state folder (`$FM_IMESSAGE_STATE`, else `~/.local/state/fm-imessage`) and the `fm-imessage` user unit.
It shows counts, ages and latencies only; it never opens a queue item, so no message text, number or name is shown, and it never writes, restarts or sends.

- Bridge up or down: `systemctl --user is-active fm-imessage`, plus the age of the last `desk.log` line.
- Pending bubbles: files in `outbox/`; the oldest pending age is the oldest file's modification time.
- Retries: the highest `failed (try N)` for a pending item in the last 24 hours of the unit's journal. The queue keeps no retry count on disk.
- Sent, last 24 hours: `transport-accepted` and `history-reconciled` lines in `desk.log` (one per bubble or tapback the transport took, or found already delivered on retry). `outbox-done/` keeps only keyed items, so it is not used.
- Failed, last 24 hours: files in `outbox-dead/`, by the burial time in the file name.
- Desk reply latency: per message, `inbox-accepted` to its first `response-confirmed` in `desk.log`; last, median and p95 over 24 hours.

Keys: `r` reload, `m` back to the board, `t` tasks, `d` decision queue. It reloads every 15 seconds. `bun crewboard-tui.ts --once --desk` prints a plain snapshot.
