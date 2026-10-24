# crewboard-tui

Read-only terminal viewer for the crewboard message board.
It runs `crewboard sub` only and never publishes.
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
