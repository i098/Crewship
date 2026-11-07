# usage-notify

Texts one line through `fm-imessage` when the quota left for a Claude account, Codex or DeepSeek reseller plan (5h and 7d windows), or a Mercury key (its flat 100M-token quota), drops below a 10% step (90, 80, ... left), and once per window when the last hour's use rate is at least 2x the average over the kept history (up to 24h, at least 2h). Both are armed again when a 5h or 7d window resets; a Mercury quota never resets. The first reading of a window only sets the baseline.

It reads the same rows as the Usage TUI (`../usage-tui/quota.ts`, `buildRows`). `notify.ts` reads only a snapshot file (one `QuotaInput` JSON) that the TUI writes atomically after each refresh; it never calls a live source. A systemd path unit (`usage-notify.path`, `PathChanged=` on the snapshot) runs `notify.ts` once per change. The saved state holds the snapshot's mtime and size, so an unchanged snapshot does nothing. The TUI hook that writes the snapshot is pending.

- `USAGE_NOTIFY_STATE`: state file (default `~/.local/state/usage-notify/state.json`).
- `USAGE_NOTIFY_SEND`: send command, text on stdin (default `fm-imessage`).
- `USAGE_SNAPSHOT`: snapshot file (default `~/.local/state/usage-tui/snapshot.json`). Also `--fixture file.json`, an alias used by tests.

State is saved only after every text is sent, so a failed send is retried on the next run. Install: copy the service and path unit files to `~/.config/systemd/user/`, then `systemctl --user enable --now usage-notify.path`. Run `bun test` for the tests.
