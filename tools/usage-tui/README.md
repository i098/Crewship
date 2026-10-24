# usage-tui

Terminal view of token usage and cost from omp's local stats store (`~/.omp/stats.db`, read-only).
It shows input, output and cache tokens as graphs, with today and month cost.
The background is transparent; colors come from `../tui-theme/theme.ts`.

```bash
bun install
bun usage-tui.ts
```
