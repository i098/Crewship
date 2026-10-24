# usage-tui

Terminal view of token usage and cost from omp's local stats store (`~/.omp/stats.db`, read-only).
It shows input, output and cache tokens as graphs, with today and month cost.
The background is transparent; colors come from `../tui-theme/theme.ts`.

```bash
bun install
bun usage-tui.ts
```

A quota panel shows how much is left per account and window (percent left, reset time) for Claude and Codex from `omp usage --json`, GLM from the Z.ai quota endpoint, and Mercury tokens per key against 100M, counted from omp session files.
A window the source does not report shows "not reported"; DeepSeek shows "no quota API".
The quota sources are read at most once per 60 seconds.
`bun usage-tui.ts --once` prints the quota rows as text; add `--fixture file.json` to read recorded inputs instead. Run `bun test` for the tests.
