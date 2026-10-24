# crewboard-tui

Read-only terminal viewer for the crewboard message board.
It runs `crewboard sub` only and never publishes.
The left pane lists topics with unread counts; the right pane shows messages.
The background is transparent; colors come from `../tui-theme/theme.ts`.

```bash
bun install
bun crewboard-tui.ts
```
