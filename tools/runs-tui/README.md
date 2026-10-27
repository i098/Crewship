# runs-tui

Terminal view of every no-mistakes validation run on this host (read-only).
It reads no-mistakes' own run records (`~/.no-mistakes/state.sqlite`) and each firstmate home's `state/*.meta` files. It never calls GitHub: the PR comes from the run record.
Columns: home, mate, task, repo, PR, current step, fix loops per step, elapsed time, outcome.
Runs sort running first, then parked on a decision, failed, passed and cancelled, newest first.
The default view shows running and parked runs plus runs updated in the last 24 hours; `a` (or `--all`) shows every run.

Mapping, in order: a task meta matching repo and branch, then branch alone, then the home from the repo's `projects/` path, the worktree name or any meta that names the repo.
The mate is the second mate whose `kind=secondmate` meta (in the main home's `state/`) names the home; the main home shows `main`.
A run with no task meta uses its branch name as the task. Only a home that no file names shows `unknown`.

Post-mortem lines show under the run that they name in the current view: a line names a run when it contains the run ID, the PR URL or the PR number (`#42`). A line that names a run hidden by the 24h view counts as unmatched until `a` shows that run.
`p` lists the lines that name no run; `--once` prints them below the table.
The tool reads `docs/validation-postmortems.md` in this repo, plus the files that `CREWSHIP_POSTMORTEM_PATHS` names (`:`-separated paths or globs, for example `$HOME/fm/*/data/validation-postmortems.md`).
It reads two formats: markdown table rows whose first cell is a date, and lines that start with a date, such as `2026-10-27 | PR: <url> | text`.
A plain line directly after a dated line continues that entry.
Missing files are skipped, and the tool never writes these files.
`--anonymize` does not show post-mortem lines.

The background is transparent; colors come from `../tui-theme/theme.ts`.

```bash
bun install
bun runs-tui.ts                # live, refreshes every 5s; a all/24h, p unmatched post-mortems, up/down scroll, r refresh, q quit
bun runs-tui.ts --once --all   # plain text, for tests and screenshots
bun runs-tui.ts --anonymize    # home, mate, task, repo and PR become placeholders (for screenshots)
```

`RUNS_TUI_DB` and `RUNS_TUI_HOMES` (`:`-separated home roots) override the data locations.
