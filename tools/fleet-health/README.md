# fleet-health

`fleet-health-tui` lists every Crewship component, grouped by kind, with its installed version, the latest published version, when it was last used, and a state: up to date, outdated, unknown, custom, or not installed. It is read-only: it never installs or upgrades anything. Run `./ship.sh chart` and `./ship.sh launch` to upgrade.

```bash
cd tools/fleet-health && bun install
bun fleet-health-tui.ts
```

Keys: `↑↓` or `j k` scroll, `r` refresh, `q` quit. Installed versions refresh every 5 minutes and on `r`.

- `components.ts` mirrors `GITHUB_LATEST`, `NPM_LATEST` and `OMP_PLUGINS` in `scripts/provisions.py`, plus node, rustup, psutil, fdu, sgrep, forgejo, spectrum-ts, concord, backpass, compact-adviser, kun and vision. `tests/test_fleet_health_components.py` fails when they drift.
- Latest versions come from the GitHub releases API (one request per component), the npm registry, PyPI, nodejs.org, rust-lang.org and Codeberg. Results are cached 30 minutes in `~/.cache/fleet-health/latest.json`, so `r` never re-fetches a fresh entry and unauthenticated GitHub stays under 60 requests per hour.
- The Bun packages group is installed with `bun add --global` and only reads versions from the npm registry.
- A component whose `custom` pattern in `components.ts` matches the installed version (lavish-axi, the owner's `-sketch` build) shows `custom`, never outdated. Commands are looked up on PATH, `~/.cargo/bin`, `~/.bun/bin`, `/usr/local/bin` and the fleet browser directory; a live process counts as in use.
- Unknown means the lookup failed or no release is published.
- Colors come from `../tui-theme/theme.ts`; the background stays transparent.
- Last used: a live process, else the newest access time under the binary or the component's own files (plugin install dir, spectrum-ts package, the pruner's Python libs for psutil). `never seen` means no file or process shows use. The filesystem is mounted `relatime`, so atimes can lag by about a day.
- sgrep has no releases: its installed commit (from cargo's `.crates2.json`) is compared with the default-branch head commit.
- Set `GITHUB_TOKEN` or `GH_TOKEN` to raise the unauthenticated GitHub rate limit; a 403 shows as the unknown note.
- kunchenguid tools: `gh-axi`, `chrome-devtools-axi`, `tasks-axi`, `quota-axi` and `lavish-axi` come from npm; `backpass` and `compact-adviser` are tracked from npm too, and show as not installed while they are absent from the host. The `kun` and `vision` skills are git checkouts: their pinned commit (`.code-factory-source`) is compared with the default-branch head.
