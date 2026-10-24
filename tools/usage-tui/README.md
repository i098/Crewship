# usage-tui

Terminal view of token usage and cost from omp's local stats store (`~/.omp/stats.db`, read-only).
It shows input, output and cache tokens as graphs, with today and month cost.
The background is transparent; colors come from `../tui-theme/theme.ts`.

```bash
bun install
bun usage-tui.ts
```

A quota panel shows how much is left per account and window (percent left, reset time) for Claude and Codex from `omp usage --json`, GLM from the Z.ai quota endpoint, Mercury tokens per key against 100M counted from omp session files, and the DeepSeek prepaid balance labelled with its wallet currency.
A window the source does not report shows "not reported"; a source that cannot be read shows one "unavailable" note with the reason. DeepSeek has no quota API, so its balance comes from the platform site the owner is signed in to: a background Dia tab on the Mac replays the site's own request and CDP returns that response, so no cookie or token leaves the browser. That read needs a password-less `ssh mac` alias (see `docs/security.md#ssh-to-a-mac`) and Dia serving CDP on 127.0.0.1:9222, which `tools/dia-debug` maintains.
The quota sources are read at most once per 60 seconds. A DeepSeek read, success or failure, is held for 10 minutes, because each read opens a browser tab in Dia; a signed-out owner therefore never sees a tab appear and vanish every minute.
`bun usage-tui.ts --once` prints the quota rows as text; add `--fixture file.json` to read recorded inputs instead. Run `bun test` for the tests.
