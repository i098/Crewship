# ci-pool-tui

Read-only terminal view of the CI pool.
It shows each `ci-runner@` slot with its unit, container, GitHub runner and job, the queued and running workflow runs, and an optional Forgejo runs panel.
The top panel lists what is held up: a pool job queued over 5 minutes, with the cause, and a slot whose problem lasts 2 minutes or more.
It never restarts or cancels anything.

```bash
bun install
bun ci-pool-tui.ts
```

## Inputs

- The pool file `~/.config/ci-pool/pool.json`, or the path in `CI_POOL_CONFIG`. With no pool file the view shows no slots.
- `systemctl --user show ci-runner@*.service` and `docker ps` (through `sudo -n` when the docker socket is not writable).
- `gh api` for runners, runs and jobs: 20 calls a minute at most, and each read repeats after 2 minutes at the soonest. On a rate-limit error, reads pause until the limit resets.
- `forgejo-axi run list` for each repo in `CI_POOL_TUI_FORGEJO_REPOS` (comma-separated `owner/repo`).

## Keys

`r` reads systemd, docker and Forgejo again, `q` quits.

## Flags

`--once` reads everything once, prints the panels as text and exits.
`--fixture file.json` with `--once` prints a recorded `Snapshot` (the shape in `ci-pool-tui.ts`) instead of the host.

```bash
bun test   # slot rows, held and stuck findings, and the GitHub read scheduler
```
