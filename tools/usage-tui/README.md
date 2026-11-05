# usage-tui

Terminal view of token usage and cost from omp's local stats store (`~/.omp/stats.db`, read-only).
It shows input, output and cache tokens as graphs, with today and month cost.
The background is transparent; colors come from `../tui-theme/theme.ts`.

```bash
bun install
bun usage-tui.ts
```

A quota panel shows how much is left per account and window (percent left, reset time) for Claude and Codex from `omp usage --json`, GLM from the Z.ai quota endpoint, Mercury tokens per key against 100M counted from omp session files, and DeepSeek plan usage from an optional external command.
A window the source does not report shows "not reported"; a source that cannot be read shows one "unavailable" note with the reason. DeepSeek has no quota API, so set `USAGE_TUI_DEEPSEEK_CMD` to a command (split on spaces, no shell) that prints `{"rows":[{"plan","window","used","limit","resets_at"}]}` (`resets_at` in epoch seconds). With no command, or when it fails, the rows show n/a. The TUI never opens a browser.
A second row, `deepseek (reseller)`, shows the spend so far on the reseller key omp uses (the reseller is a LiteLLM proxy with no balance or quota route): a 1-token chat call reads the key from omp's credential store in-process and takes `x-litellm-key-spend` from the response headers. The key is never printed or written, and each call costs a fraction of a cent.
The quota sources are read at most once per 60 seconds. A DeepSeek command result, success or failure, is held for 10 minutes, and each reseller read is a paid call.
`bun usage-tui.ts --once` prints the quota rows as text; add `--fixture file.json` to read recorded inputs instead. Run `bun test` for the tests.
