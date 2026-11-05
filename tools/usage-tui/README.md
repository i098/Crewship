# usage-tui

Terminal view of token usage and cost from omp's local stats store (`~/.omp/stats.db`, read-only).
It shows input, output and cache tokens as graphs, with today and month cost.
The background is transparent; colors come from `../tui-theme/theme.ts`.

```bash
bun install
bun usage-tui.ts
```

A quota panel shows how much is left per account and window (percent left, reset time) for Claude and Codex from `omp usage --json`, GLM from the Z.ai quota endpoint, Mercury tokens per key against 100M counted from omp session files, and the DeepSeek reseller plan quota from an optional external command.
A window the source does not report shows "not reported"; a source that cannot be read shows one "unavailable" note with the reason. The `deepseek (reseller)` rows show 5h and 7d percent left and reset time from the reseller's quotaMe call: set `USAGE_TUI_DEEPSEEK_CMD` to a command (split on spaces, no shell) that prints `{"rows":[{"window","used","limit","resets_at"}]}` (`resets_at` in epoch seconds). With no command, or when it fails, the row shows n/a with the reason. The TUI never opens a browser.
The quota sources are read at most once per 60 seconds. A DeepSeek command result, success or failure, is held for 10 minutes.
`bun usage-tui.ts --once` prints the quota rows as text; add `--fixture file.json` to read recorded inputs instead. Run `bun test` for the tests.
