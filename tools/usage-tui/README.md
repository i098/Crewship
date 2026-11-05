# usage-tui

Terminal view of token usage and cost from omp's local stats store (`~/.omp/stats.db`, read-only).
It shows input, output and cache tokens as graphs, with today and month cost.
The background is transparent; colors come from `../tui-theme/theme.ts`.

```bash
bun install
bun usage-tui.ts
```

A quota panel shows how much is left per account and window (percent left, reset time) for Claude and Codex from `omp usage --json`, GLM from the Z.ai quota endpoint, Mercury tokens per key against 100M counted from omp session files, and the DeepSeek reseller plan quota from the reseller's quotaMe call.
A window the source does not report shows "not reported"; a source that cannot be read shows one "unavailable" note with the reason. The `deepseek (reseller) <plan>` rows, one 5h and 7d pair per plan, show 5h and 7d percent left and reset time from the reseller's quotaMe call: read over HTTP through `api-anything` with its saved login, which is renewed from the fleet cookie jar (`~/.fleet-browser/cookies.json`) when it expires. When the call fails the row shows n/a with the reason. The TUI never opens a browser.
The quota sources are read at most once per 60 seconds. A DeepSeek quota result, success or failure, is held for 10 minutes.
`bun usage-tui.ts --once` prints the quota rows as text; add `--fixture file.json` to read recorded inputs instead. Run `bun test` for the tests.

## Provider list

`usage-tui-detect` finds which subscriptions and accounts this host has and writes `~/.config/crewship/usage-providers.json` (override with `USAGE_TUI_PROVIDERS`). It reads provider names and account counts only: omp auth providers from `~/.omp/agent/agent.db`, the Codex CLI login, a `zai-glm` provider in `models.yml`, `rtk` when `rtk gain` runs, and the variables `INCEPTION_API_KEY(S)`, `DEEPSEEK_API_KEY`, `ZAI_API_KEY` or `GLM_API_KEY` by name. It never reads or stores a key, token or email. The TUI reads that file and shows quota rows only for the sources it lists; a provider with no quota source gets a row that says so. Without the file it detects on each load. Setup (`launch`) runs it once; run `usage-tui-detect --print` after you add or remove an account to detect again. It prints `changed` or `unchanged`, and `--check` writes nothing.
