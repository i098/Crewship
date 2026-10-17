# Fleet guards

`crewship.profiles.fleet_guards` installs the Docker guard, reapers, storage guard and browser ladder.
The profile is off by default.
See [Project databases](project-databases.md) for the optional per-project dev databases.

The controls address abandoned containers, orphan processes, idle dev servers and unbounded lane concurrency.

Sizing per lane count and the full list of pruners are in
[Capacity and pruners](capacity.md).

## What is provisioned

The Docker guard, reapers and storage guard require `fleet_guards`.
Each profile manages only its own units.
The Docker defaults and Firstmate spawn floor belong to their respective profiles.
See [Project databases](project-databases.md#worktree-environment) for the separate database seeder.

| Path (under the account home) | Purpose |
| --- | --- |
| `oss-fleet/doctor/docker-guard.sh` | Every hour: removes stopped containers that agents left behind and reports long-running ones that nothing claims. See [Docker guard](#docker-guard). |
| `oss-fleet/doctor/dev-server-reaper.sh` | Every 2 minutes: kills `next dev`/`next-server`/`tsc --noEmit` trees in treehouse worktrees whose lane last reported `done:`/`paused:`/`blocked:`/`failed:`, has no agent process, or whose agent transcript is idle >= 30 min (`REAPER_IDLE_MIN`). A dev server is 3-4 GB and restarts in 10 s; idle ones from finished lanes are what filled swap. One `next dev` per branch is inherent - Next compiles the whole app per process - so the fix is lifetime, not sharing. |
| `oss-fleet/doctor/storage-guard.sh` | Measures disk pressure, attempts alerts, and reclaims eligible data. See [Storage guard](#storage-guard) for delivery, retry, and reclaim rules. |
| `oss-fleet/doctor/devtools-bridge-reaper.sh` | Every 10 minutes: stops attached chrome-devtools-axi bridges (`CHROME_DEVTOOLS_AXI_BROWSER_URL` set) whose process tree used no CPU and whose session state files did not change for 60 min (`REAPER_IDLE_MIN`). See [Devtools-bridge reaper](#devtools-bridge-reaper). |
| `.config/systemd/user/crewship-*.{service,timer,path}` | `fleet_guards` enables the guard and reaper timers. Apply retires only selected `flotilla-*` guard units. |
| `/etc/docker/daemon.json` | `init: true` and `live-restore: true` merged in (tasks/docker.yml, any profile with docker). |
| Firstmate `config/spawn-memory-floor-mb` | `8000`: `bin/fm-spawn.sh` refuses a fresh spawn while host `MemAvailable` is below it. Free swap is not counted - "there is swap left" is the thrash state. |

## Cleanup pool roots

The storage guard, output pruner and dev-server reaper share `doctor/treehouse-roots.py`.
They read the native global config at `~/.config/treehouse/config.toml`, without shell startup files.
`TREEHOUSE_ROOT` takes precedence over the native `root` value.
Treehouse expands environment variables in that value and appends `.treehouse`.
The scripts also scan `~/.treehouse` for legacy pools and remove duplicate resolved roots.
They skip relative native roots because the timers have no repository context.
Repository-local roots, custom worktree layouts and per-command `--root` values are not discovered.

`WORKTREE_PRUNE_POOLS` still replaces pool discovery for the storage guard and output pruner.
It names the pool directory itself, so the scripts do not append `.treehouse`.
The guard prunes each root only when its filesystem reaches CRIT.
The reaper searches lane metadata under both roots and retains the existing `~/.no-mistakes/worktrees/<repo>/<run>` match.
Its process, lane-state and transcript-idle checks do not change.

## Storage guard

Nothing else alerts on a filling disk: docker-guard acts on containers,
Firstmate's orphan sweep on aged litter. Docker images, build cache, or one
looping process writing to `/var/log` can take `/` to 100%.

`crewship-storage-guard.timer` runs `storage-guard.sh` every five minutes.
It measures mounted block filesystems once per device, excluding pseudo filesystems and loop devices.
It also measures the filesystems that hold `/`, `/var/log`, the home, and Docker's data root.
Thresholds use `crewship_storage_guard_*` in `blueprint/ansible/group_vars/all/fleet.yml`.

| Tier | Trigger (default) | Action |
| --- | --- | --- |
| FILL | Growth projects a full filesystem within six hours, at or above 70% used | Alert before reclaim, including below WARN; repeat at most every 30 minutes. |
| WARN | 85% used | Alert once per filesystem and episode; re-arm below 82%. |
| CRIT | 92% used | Alert first, then reclaim only eligible worktree output and Docker data; repeat alerts at most every 30 minutes. |

The guard attempts alerts for all measured pressured filesystems before it starts consumer scans or reclaim.
It retries pending alerts before filesystem discovery, even when pressure has fallen.
Each pending record keeps the original body and a stable request ID.
Pending records and receipts also keep the event counter and episode state, so a failed sample write cannot reuse an earlier receipt.
The guard calls `fm-inbox.sh note --request-id <id> --json -- <body>` under `FM_HOME`.
The service sets `FM_HOME` to `crewship_firstmate_dir`.
A matching receipt must confirm a saved note and either announcement or prior acknowledgement.
Only that receipt clears the pending record.
Failed calls, invalid receipts, and uncertain announcements retain the record and return a nonzero service status.
`STORAGE_NOTIFY_TIMEOUT` bounds each inbox attempt to five seconds, plus a two-second hard-stop allowance.
`notify-master.sh`, or `wall` if necessary, provides a bounded fallback broadcast.
A broadcast never counts as an inbox receipt; its marker prevents repeated successful broadcasts during retries.
Older Firstmate versions without request IDs and JSON receipts cannot confirm delivery.
Upgrade Firstmate to restore acknowledged delivery; pending records remain until then.

With `crewship.data_dir` configured, state, pending alerts, receipts, logs, and diagnostics use `<data_dir>/storage-guard`.
The service passes `STORAGE_DATA_DIR` from `crewship.data_dir`.
The configured data directory must exist on a mounted filesystem different from root.
Apply checks the mount and creates the guard directory for the account with mode `0700`, including under a root-owned data directory.
The guard checks the mount before creating state.
When this check fails, the guard attempts a mount-error broadcast and exits before retries, discovery, diagnostics, or reclaim.
It never creates a root-backed substitute.
This check identifies the covering filesystem, not a pinned disk UUID.
Without `data_dir`, state remains in `oss-fleet/doctor/.storage-guard`; logs now reside there too.
This compatibility mode cannot retain new alerts when that filesystem cannot accept writes.
If a pending record cannot be saved, the guard still attempts inbox delivery and fallback broadcast before scans or reclaim.
It returns a nonzero status without recording retention or acknowledgement.
State creation or lock errors cause unsaved notifications and a nonzero status.
Only the lock owner can change pending records, receipts, broadcast markers, samples, logs, or diagnostic files.
Without the lock, the guard sends diagnostic output to standard error.
Lock contention exits without delivery or maintenance.
Changing the state directory does not migrate earlier samples or pending records; preserve and move them before switching.
Earlier alerts without pending records cannot be reconstructed.
Manual runs can set `STORAGE_DATA_DIR` to use the same placement.

After notification, CRIT runs `worktree-prune.sh` on the filesystem that holds the Treehouse pools.
Only filesystems measured at CRIT during the notification pass can start reclaim.
Later measurements can stop reclaim but cannot make another filesystem eligible.
`WORKTREE_PRUNE_CMD` can replace this command.
On Docker's filesystem, it then prunes build cache, dangling images, and unused images created more than 168 hours ago.
It re-measures before reclaim and after each step, and stops reclaim below CRIT.
After reclaim, the guard updates the usage sample so rapid growth from the reduced usage still triggers FILL.
The image filter uses creation time, not last use.
Existing worktree safety checks remain unchanged.

Diagnostics follow notification and record the top consumers in `storage-guard.log` and `<filesystem-key>.scan`.
The bounded `du` walk includes the filesystem root, its largest entry, the home, and `/var/log` on that filesystem.
The log also records growth since the previous scan and `docker system df` on Docker's filesystem.
Reclaim results remain in the log rather than delaying or changing the original alert body.

The guard never deletes volumes, containers, repositories, `/tmp` content,
logs or anything under the home except the worktree output below; it reports
them. Firstmate's orphan sweep owns whole leaked worktrees and `/tmp` litter,
and a runaway log needs whoever owns the process writing it.
`storage-guard.sh --dry-run` prints the measurement, the tier, what each CRIT
step would free (for the worktree step, each directory it would remove) and the
alert a real run would send, and changes nothing. `tests/test_storage_guard.py`
drives the tiers against stubbed `df`, `du`, `findmnt` and `docker`.

### Stale worktree output

`worktree-prune.sh` removes gitignored build output from Treehouse pool
worktrees (`<pool-root>/<pool>/<n>/<repo>`).
It uses the [cleanup pool roots](#cleanup-pool-roots).
A directory is removed only when all of these hold:

- Its name is `node_modules`, `.venv`, `venv`, `target`, `dist`, `build`, `.next`, `.nuxt`, `.turbo`, `.parcel-cache`, `__pycache__`, `.pytest_cache`, `.mypy_cache` or `.ruff_cache` (`WORKTREE_PRUNE_NAMES`).
- Nothing inside it changed for 7 days (`crewship_storage_guard_worktree_age_days`, or `WORKTREE_PRUNE_AGE_DAYS` by hand).
- The nearest enclosing git repository ignores it (`git check-ignore`), tracks no file in it, and has no untracked file in it that is not ignored.
- It holds no nested git repository, which could carry unpushed commits.
- It is a real directory, not a symlink, and its resolved path is still inside the worktree.

Tracked files, untracked work outside such directories, anything outside the
pools and every directory that fails one check stay. `find` discovers the
candidates by name and age: it stops at the first build directory, and measured
on 165 worktrees it took 23 s where `fdu --ignored only` took 94 s for the same
104 directories. The opt-in [`fdu` profile](configuration.md#profiles) is used
only for the size in each report line (`fdu --view summary`); without fdu, or
when fdu fails, `du` gives it. fdu never decides what is removed.
`~/oss-fleet/doctor/worktree-prune.sh --dry-run` prints what a real run would
remove. `tests/test_worktree_prune.py` runs it against real git repositories.

## Docker guard

Agents start containers for tests, databases and previews and seldom remove
them. `crewship-docker-guard.timer` runs `docker-guard.sh` every hour:

| Container | Action |
| --- | --- |
| Stopped (exited, created or dead) for `crewship.fleet.docker_guard.stopped_hours` (24) or more, counted from its exit, or from its creation when it never ran | Removed with a plain `docker rm`: its volumes stay, and a container that started again since the check is refused. |
| Running for 48 h or more (fixed) | Reported, never stopped or removed: one log line, one `COMMS.md` line and one `notify-master.sh` alert per container. It is reported again only after it stops qualifying and then qualifies again. |
| Claimed: label `crewship.keep` (any value), or a restart policy other than `no` | Never removed or reported. |

The guard never touches volumes, images or networks.
To keep a container, start it with `--label crewship.keep` or `--restart unless-stopped`.
`docker-guard.sh --dry-run` prints each verdict and changes nothing.
`tests/test_docker_guard.py` drives the rules against a stubbed `docker`.

## Browser ladder

Three browser tiers share one cookie jar. The `fleet_browsers` profile, or
`fleet_guards`, installs them under `~/oss-fleet/browsers/`, and puts their
environment in shell profiles and the Herdr unit. Sources of truth:
`blueprint/fleet/browsers/fleet-browser` (runtime, `alive` probe),
`blueprint/fleet/browsers/env.sh` (defaults every shell inherits),
`blueprint/fleet/browsers/cookie-sync.ts` (jar), `blueprint/ansible/tasks/fleet-browsers.yml` and
`blueprint/ansible/templates/fleet-browser-*.{service,timer}.j2` (units, cadences).
The playbook tag `fleet_browsers` (or `fleet`) narrows a run to the ladder;
`--skip-tags journald` also leaves out its host-wide journald cap.
Those runs leave the Herdr unit alone. The unit gets the ladder environment
only on a run that includes the `herdr` tag, for example
`--tags herdr,fleet_browsers`, and that run restarts Herdr.

| Tier | CDP port | Always on? | Use it when |
| --- | --- | --- | --- |
| 1 `obscura` | `127.0.0.1:9222` | Yes (`fleet-browser-obscura.service`) | Default for everything: clicks, screenshots, screencast. ~25 MB idle; ~5x less RAM per page than Chrome. |
| 2 `chrome` | `127.0.0.1:9522` | On demand (`fleet-browser up chrome`) | Obscura misrenders the page, a site blocks it, or the maintainer needs pixel-exact before/after evidence. Headless Chromium, persistent profile. |
| 3 `vnc` | `127.0.0.1:9523`, noVNC `http://127.0.0.1:6909/vnc.html` | On demand (`fleet-browser up vnc`) | A human must see or drive the browser: OAuth consent, second factors, captchas, native dialogs, sites such as Google that refuse any automated browser. TigerVNC display `:9` + headed Chromium. |

Move down one tier only when the tier above cannot do the job; move back to
`obscura` for the next task. `fleet-browser-gc.timer` (every 5 min) stops tiers
2 and 3 after 30 idle minutes (`FLEET_BROWSER_IDLE_MIN`, no CDP client
connected). Tier 3 needs TigerVNC and noVNC, which the ladder installs from
Ubuntu (`ConditionPathExists=/usr/bin/tigervncserver`). Tiers 2 and 3 need a
Chrome/Chromium binary (`FLEET_CHROME_BIN`, Google Chrome, Chromium, or a
Playwright Chromium).

Obscura ships for x86_64 and aarch64; apply installs the latest release for the
host's platform (see [Dependencies](dependencies.md#optional-fleet-browsers)).
A new release never restarts a running tier: apply repoints the `obscura`
symlink, and the tier picks up the new binary at its next idle refresh or
restart, because Obscura restarts only when no lane is connected to it.

Log flood cap: apply writes `/etc/systemd/journald.conf.d/50-fleet-ratelimit.conf`
(`RateLimitIntervalSec=30s`, `RateLimitBurst=1000`) and restarts journald. The cap
is host-wide, counts lines not bytes, and is the only limit on journald intake:
a user unit's own `LogRateLimit*` is ignored, and the `page task error` warning
Obscura logs for a page whose top-level await never resolves is not suppressed
at its source. rsyslog still rotates `/var/log/syslog` weekly only.

All three tiers share one session. `cookie-sync.ts` keeps a canonical jar at
`~/.fleet-browser/cookies.json` and converges every live tier to it over CDP.
`fleet-browser-sync.timer` runs it every 2 minutes, and
`fleet-browser up chrome|vnc` runs it before returning (`up obscura` returns as
soon as the tier answers, without a converge). So a login made in any tier is
present in every tier within one sync. Cookies are synced; localStorage is
engine-local and is not. Google cookies (google.com, Google's country domains,
youtube.com) are the exception: each stays in the tier that set it. Google
treats one session replayed from several browsers as theft and revokes it, so
a Google sign-in made by hand in the `vnc` tier stays in `vnc`. A Google cookie
that another tier holds with the same value as `vnc` is deleted from that tier.
Obscura ignores cookie deletes over CDP, so `fleet-browser sync` stops
`obscura`, rewrites its session file, and starts it again, only when no lane is
connected to it.

Rule: an agent never launches its own Chrome, headless or not, and never uses a
private `--user-data-dir`. A private profile has none of the fleet's logins and
is outside the sync. Use the tier that is already running, or bring one up with
`fleet-browser up`.

The ladder's `vnc` tier is not the `desktop` profile's operator desktop (XFCE +
TigerVNC, noVNC on `127.0.0.1:6080`, profile `~/.vnc-chrome-profile`, see
[Desktop access](recovery.md#desktop-access)). The desktop is a human
workstation; the `vnc` tier is a fleet browser with a human window into it.

### Testing a tier before using it

Every shell an agent inherits sources `env.sh`, so
`CHROME_DEVTOOLS_AXI_BROWSER_URL` already points at `obscura`:

```bash
fleet-browser env            # prints the exports for the default tier
fleet-browser env chrome     # or: eval "$(fleet-browser env chrome)" to escalate for one task
```

1. Probe the tier's CDP endpoint. This is the same `alive` check `fleet-browser` uses:

   ```bash
   curl -s -m 3 http://127.0.0.1:9222/json/version    # obscura
   curl -s -m 3 http://127.0.0.1:9522/json/version    # chrome
   curl -s -m 3 http://127.0.0.1:9523/json/version    # vnc
   ```

   Healthy: exit 0 and a JSON object with `"Browser"`, `"Protocol-Version": "1.3"`
   and a `"webSocketDebuggerUrl"` on the same port. Anything else (empty output,
   exit 7 or 28, HTML) means the tier is down. Run `fleet-browser up chrome` or
   `fleet-browser up vnc` (waits until the probe answers), or for `obscura` run
   `systemctl --user start fleet-browser-obscura.service`.

2. Check the whole ladder at once. `STATE` is `up`/`down`, `CLIENTS` counts open
   CDP connections, and the `session:` line shows the jar and the last sync:

   ```bash
   fleet-browser status
   ```

3. Confirm the fleet's logins are there. The jar must exist and the sync timer
   must be active:

   ```bash
   ls -l ~/.fleet-browser/cookies.json
   systemctl --user list-timers fleet-browser-sync.timer
   fleet-browser sync           # force a converge now instead of waiting up to 2 min
   ```

   A site still asking for a login on every tier means nobody has signed in yet.
   Bring up `vnc`, sign in through noVNC (`ssh -L 6909:127.0.0.1:6909 <host>`,
   then `http://127.0.0.1:6909/vnc.html?autoconnect=1`), and the next sync
   carries the session to `obscura` and `chrome`. A Google sign-in stays in `vnc`.
   On a tailnet host, publish noVNC to the tailnet once, never with Funnel:
   `sudo tailscale serve --bg --https=6909 http://127.0.0.1:6909`. Then open
   `https://<host>.<tailnet>.ts.net:6909/vnc.html?autoconnect=1`. The VNC
   display has no password, so every tailnet device that the tailnet policy
   lets reach that port can drive the signed-in browser.

## Devtools-bridge reaper

Every chrome-devtools-axi session starts a bridge that detaches to init by
design, plus a chrome-devtools-mcp child. Idle bridges pile up and hold
gigabytes, mostly in swap, and no fleet memory guard sees them: they are
neither fleet repo processes nor agent panes.

The split with `chrome-autoprune` (agents profile): it stops idle disposable
bridges and refuses attached ones, which is every bridge an agent starts on a
fleet host because the browser ladder exports `CHROME_DEVTOOLS_AXI_BROWSER_URL`;
this reaper stops only those attached bridges and skips every other one, so a
headed or persistent-profile Chrome is never killed.

`crewship-devtools-bridge-reaper.timer` runs `devtools-bridge-reaper.sh` every
10 minutes. Each run records the CPU ticks of every attached bridge's whole
process tree; a tree that moved, or a session whose `bridge.pid` or
`snapshot-generation` changed, counts as busy, and a bridge seen for the first
time is never reaped on that run. A bridge idle for `REAPER_IDLE_MIN` (60)
minutes gets TERM, then after a 5 s grace KILL for whatever is left of its
exact tree, every pid re-checked by start time. The session's next command
starts a fresh bridge attached to the same ladder browser: only the MCP
connection and page selection are dropped, and the browser keeps its pages and
cookies. The script reads `/proc` in one pass because a per-process version is
too slow on a heavily loaded host. `--dry-run` prints each attached
bridge's idle time and verdict and changes nothing.
`tests/test_devtools_bridge_reaper.py` drives it against a fixture process
tree.

## Operating

```
systemctl --user status crewship-docker-guard.timer crewship-storage-guard.timer crewship-devtools-bridge-reaper.timer
~/oss-fleet/doctor/docker-guard.sh --dry-run
~/oss-fleet/doctor/storage-guard.sh --dry-run
~/oss-fleet/doctor/devtools-bridge-reaper.sh --dry-run
tail ~/oss-fleet/doctor/docker-guard.log
tail ~/oss-fleet/doctor/devtools-bridge-reaper.log
```

Read the storage guard log from the [storage guard state directory](#storage-guard).
