# lavish-tui and lavish-keep

`lavish-tui` is a read-only terminal view of every lavish board on the host, from the sessions in `~/.lavish-axi/state.json` (`LAVISH_AXI_STATE_DIR`).
Each row shows the status, the owner worker, the session key, the last update, the board title and the board link.
The link is the public one from `lavish-public link` when that command is installed, else the plain session URL.
The background is transparent; colors come from `../tui-theme/theme.ts`.

```bash
bun install
bun lavish-tui.ts            # live view: a all/open, ↑↓ scroll, r refresh, q quit
bun lavish-tui.ts --once     # plain text; add --all for ended boards, --anonymize for screenshots
```

The owner is the task of the board's firstmate `data/<task>/` dir or of the worktree a task meta names.
`WORKER` shows `GONE` when the owner worker is torn down:

- `kept`: the board loads from a `lavish-keep` copy.
- `deleted`: the board file no longer exists.
- `torn down`: no task meta owns the data dir or the worktree slot.

Open boards of gone workers sort first. The tool never writes `state.json`.

## lavish-keep

`../lavish-keep/lavish-keep` keeps a worker's boards loading after its worktree is cleaned up.
It copies each board of the given worktree or board file to `~/.local/share/lavish-keep/<session key>/` (`LAVISH_KEEP_DIR`) and points the session's `file` at the copy.
It changes only that field, writes `state.json` atomically and saves the first version as `state.json.lavish-keep.bak`.
It never ends or closes a session. `--list` shows what it would keep.

A teardown keeps the boards with one line before cleanup:

```bash
lavish-keep "$WORKTREE" || true
```

Run `uv run pytest tests/test_lavish_tui.py` for the tests.
