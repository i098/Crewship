# usage-notify

Texts one line through `fm-imessage` when the quota left for a Claude account, Codex, DeepSeek reseller plan or Mercury key (5h and 7d windows) drops below a 10% step (90, 80, ... left), and once per window when the last hour's use rate is at least 2x the average over the kept history (up to 24h, at least 2h). Both are armed again when the window resets. The first reading of a window only sets the baseline.

It reads the same rows as the Usage TUI (`../usage-tui/quota.ts`, `loadQuota` and `buildRows`). The TUI has no refresh event another process can subscribe to, so a systemd user timer runs `notify.ts` once every 5 minutes; each run reads the quota sources once and exits.

- `USAGE_NOTIFY_STATE`: state file (default `~/.local/state/usage-notify/state.json`).
- `USAGE_NOTIFY_SEND`: send command, text on stdin (default `fm-imessage`).
- `--fixture file.json`: read a recorded `QuotaInput` instead of the live sources.

State is saved only after every text is sent, so a failed send is retried on the next run. Install: copy the two unit files to `~/.config/systemd/user/`, then `systemctl --user enable --now usage-notify.timer`. Run `bun test` for the tests.
