# Capacity and pruners

Sizing for a fleet host, and every process that prunes or reaps on its own.
Figures are estimates from a measured fleet host.

## Load estimate

### What one lane costs

| Component | Memory | Source |
| --- | --- | --- |
| omp crewmate (one agent process) | 300-750 MB RSS | measured |
| no-mistakes pipeline agent (omp) while a lane ships | about 450 MB | measured |
| `next dev` / `next-server` for a UI lane | 3-4 GB | [fleet guards](fleet-guards.md) |
| `tsc --noEmit` | about 0.6 GB | measured |
| chrome-devtools-axi bridge + `chrome-devtools-mcp` | about 0.3 GB for the MCP child; an idle bridge holds about 2 GB | measured |
| Obscura browser tier | about 25 MB idle | [browser ladder](fleet-guards.md#browser-ladder) |
| **Light lane** (docs, config, backend: agent + pipeline + tests) | **about 1.35-1.8 GB**; plan 2 GB | sum of the agent, pipeline and `tsc` rows |
| **UI lane** (agent + dev server + tsc + browser) | **5-8 GB**; plan 8 GB | [fleet guards](fleet-guards.md) |

Fixed cost, whatever the lane count: the OS, Herdr, Firstmate, its secondmates and Docker.

Firstmate refuses a new spawn while `MemAvailable` is under
`config/spawn-memory-floor-mb` (8000 MB), and free swap does not count. Plan RAM
from the top of each range:

```
RAM ≈ 8 GB spawn floor + 3 GB fixed + (light lanes × 2 GB) + (UI lanes × 8 GB)
vCPU ≈ (light lanes × 1) + (UI lanes × 2)
```

Idle chrome-devtools-axi bridges come on top: each holds about 2 GB until
`chrome-autoprune` stops it after two idle hours.

### Recommended specs

| Concurrent lanes | vCPU | RAM | Swap | Disk |
| --- | --- | --- | --- | --- |
| 2 light | 4 | 16 GB | 8 GB | 100 GB |
| 2 UI + 2 light, or 8 light | 8 | 32 GB | 16 GB | 200 GB |
| 4 UI + 8 light, or 16 light | 16 | 64 GB | 32 GB | 300 GB |

- **CPU:** the vCPU line above is an estimate for lanes while they compile.
- **RAM:** a 24 GB host fits one UI lane plus two light lanes, or six light lanes.
- **Swap:** keeps the host reachable during a spike. It is not capacity, because the spawn floor ignores it and a swapping host thrashes.
- **Disk:** Docker images and build cache grow with the lane count. The storage guard warns at 85% and prunes at 92%, stale gitignored worktree output first (see [Stale worktree output](fleet-guards.md#stale-worktree-output)).
- **File watchers:** every agent runs file watchers (LSP servers, bundlers, test runners) as the one Crewship account, and the stock limit is 128 inotify instances per user. Every host that starts services gets `/etc/sysctl.d/60-agent-host.conf` with `fs.inotify.max_user_instances = 8192`; apply loads it with `sysctl -p` when it writes the file.

### Hosting advice

This is buying advice, not a measurement.
Start with a VPS for the 16 GB and 32 GB presets.
For sustained 16 vCPU / 64 GB work, compare dedicated hardware with a dedicated-vCPU VPS.
Prefer dedicated hardware if its price fits that sustained load.
A 64 GB requirement alone does not require dedicated hardware.
Provider vCPU labels do not guarantee equal performance.
Choose SSD or NVMe storage and add space for your repositories, images, and data.

The laptop guide, `npx crewship init`, uses these presets to recommend a size before purchase.
Count active work lanes, including review and test agents, rather than queued jobs.
Choose a preset that meets both the CPU and RAM estimates, plus your disk needs.
For needs above 16 vCPU or 64 GB, use the formulas above and request a larger offer.
If the budget is too low, reduce the agreed concurrency or stop before purchase.
Never count swap as RAM capacity.

## Auto pruners

### Provisioned by this recipe

The Setting column names the profile that installs each pruner and what tunes it: a key under `crewship` in `.local/host.yml`, an Ansible variable, or a script default.

| Pruner | Removes | Runs | Setting |
| --- | --- | --- | --- |
| Docker guard (`crewship-docker-guard.timer`) | Stopped containers 24 h (default) after they exit. Running containers 48 h old are reported, never removed. Never a container with the `crewship.keep` label or a restart policy, a volume or an image. | every hour | `fleet.docker_guard.stopped_hours`; profile `fleet_guards` |
| Storage guard (`crewship-storage-guard.timer`) | At 92% disk use: gitignored build output (`node_modules`, `.venv`, `target`, `dist`, `.next`, ...) in Treehouse pool worktrees that nothing changed for 7 days, found with `find` (sizes from [fdu](configuration.md#profiles) when installed, else `du`); then Docker build cache, dangling images, and unused images created more than 168 h ago. Never tracked files, uncommitted or unpushed work, volumes, containers, repositories, logs or other home content. | every 5 min | `crewship_storage_guard_*` (`worktree_age_days` is the 7) in `blueprint/ansible/group_vars/all/fleet.yml`; profile `fleet_guards` |
| Dev-server reaper (`crewship-dev-server-reaper.timer`) | `next dev`, `next-server` and `tsc --noEmit` trees whose lane is done, paused, blocked or failed, has no agent, or is idle for 30 min or more. | every 2 min | `REAPER_IDLE_MIN` (30) in the script; profile `fleet_guards` |
| Devtools-bridge reaper (`crewship-devtools-bridge-reaper.timer`) | Attached chrome-devtools-axi bridges whose process tree used no CPU and whose session state did not change for 60 min. Never any other bridge. | every 10 min | `REAPER_IDLE_MIN` (60) in the script; profile `fleet_guards` |
| Browser autoprune (`chrome-autoprune.timer`) | AXI bridge browser processes idle for 2 h. Never headed, attached or persistent-profile browsers. | every 5 min | `browser_prune.enabled`, `browser_prune.idle_seconds` (7200), `browser_prune.poll_seconds` (300); profile `agents` |
| Browser ladder gc (`fleet-browser-gc.timer`) | Browser ladder tiers 2 and 3 (`chrome`, `vnc`) after 30 idle minutes with no CDP client. | every 5 min | `FLEET_BROWSER_IDLE_MIN` (30); profile `fleet_browsers` or `fleet_guards` |
| Docker init (`/etc/docker/daemon.json`) | Zombie processes inside every container (docker-init runs as PID 1). | continuously | `docker.init`; profile `docker` |
| Firstmate orphan sweep (`bin/fm-orphan-sweep.sh`) | Dead per-task desktops, leaked treehouse worktrees, disowned browser, ssh-agent, caddy and websockify processes, and `/tmp` scratch older than two days. Never anything a live mate owns. | on Firstmate's wake drain, at most hourly | profile `firstmate` |
| Firstmate Herdr cleanup (`bin/fm-herdr-session-cleanup.sh`) | Idle restored-shell Herdr presentation panes and their journals. Never a workspace or a pane with an agent. | on every locked session start | profile `firstmate` |
| Firstmate branch prune (`bin/fm-fleet-sync.sh`) | Local project branches whose upstream is gone. Never the checked-out branch or one with a worktree. | on session start | `FM_FLEET_PRUNE=0` turns it off; profile `firstmate` |
| Firstmate remote-job reaper (`bin/fm-remote-job-reap-orphans.sh`) | Remote-job worker processes whose Firstmate code root was deleted. | on every `fm-teardown.sh` | profile `firstmate` |
