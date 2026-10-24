# fleet-health

`fleet-health-tui` lists every Crewship component with its installed version, the latest published version, and a state: up to date, outdated, or unknown. It is read-only: it never installs or upgrades anything. Run `./ship.sh chart` and `./ship.sh launch` to upgrade.

```bash
cd tools/fleet-health && bun install
bun fleet-health-tui.ts
```

Keys: `↑↓` or `j k` scroll, `r` refresh, `q` quit. Installed versions refresh every 5 minutes and on `r`.

- `components.ts` mirrors `GITHUB_LATEST`, `NPM_LATEST` and `OMP_PLUGINS` in `scripts/provisions.py`, plus node, rustup, psutil, fdu, sgrep, forgejo and spectrum-ts. `tests/test_fleet_health_components.py` fails when they drift.
- Latest versions come from the GitHub releases API (one request per component), the npm registry, PyPI, nodejs.org, rust-lang.org and Codeberg. Results are cached 30 minutes in `~/.cache/fleet-health/latest.json`, so `r` never re-fetches a fresh entry and unauthenticated GitHub stays under 60 requests per hour.
- Unknown means the component is not installed, has no published release to compare (sgrep builds from its default branch), or the lookup failed.
- Colors come from `../tui-theme/theme.ts`; the background stays transparent.
