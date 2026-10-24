# runs-tui

Terminal view of every no-mistakes validation run on this host (read-only).
It reads no-mistakes' own run records (`~/.no-mistakes/state.sqlite`) and each firstmate home's `state/*.meta` files. It never calls GitHub: the PR comes from the run record.
Columns: home, task, repo, PR, current step, fix loops per step, elapsed time, outcome.
Runs sort running first, then parked on a decision, failed, passed and cancelled, newest first.
A run with no task meta shows `unknown`. The home still shows when the repo lives under a home's `projects/` dir.
The background is transparent; colors come from `../tui-theme/theme.ts`.

```bash
bun install
bun runs-tui.ts          # live, refreshes every 5s; up/down scroll, r refresh, q quit
bun runs-tui.ts --once   # plain text, for tests and screenshots
```

`RUNS_TUI_DB` and `RUNS_TUI_HOMES` (`:`-separated home roots) override the data locations.
