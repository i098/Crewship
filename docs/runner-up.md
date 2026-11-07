# runner-up

[runner-up](https://github.com/kunchenguid/runner-up) runs GitHub Actions jobs on this host, one fresh Docker container per job.
It replaces the [CI pool](ci-pool.md), which is deprecated: it is removed when [#1179](https://github.com/i098/Crewship/issues/1179) lands.
The CI pool keeps one idle runner container for every slot.
runner-up starts a container only when a job waits, so an idle host runs one small coordinator process and no job container.

## Turn it on

Add a `runner_up` block with a `repos` list to `.local/host.yml`.
`repos` is required; runner-up takes nothing from `crewship.ci_pool`.

```yaml
crewship:
  runner_up:
    repos:                      # the repositories runner-up serves
      - { repo: owner/name, slots: 2, labels: [my-label] }
  #   total_slots: auto         # most jobs at one time; auto takes half of the host
  #   job_cpus: 4               # CPU cap of each job container
  #   job_memory_gb: 8          # memory cap of each job container
  #   cpu_weight: 20            # CPUWeight of the slice (default 100 is the share of other work)
  #   io_weight: 20             # IOWeight of the slice
  #   nice: 10                  # Nice of the coordinator
  #   memory_max: 50%           # MemoryMax of the slice, a size (64G) or a percent of the host
  #   cpu_share: 50             # CPUQuota of the slice: this percent of the host's CPUs
  #   io_write_device: /dev/sdc # disk to cap writes on; no write cap without it
  #   io_write_mb: 120          # IOWriteBandwidthMax of the slice, in MB/s
  #   io_write_iops: 600        # IOWriteIOPSMax of the slice
  #   disk_max_gb: 50           # build cache the hourly cleanup keeps
  #   pause_pct: 88             # data disk use at or above which no new job starts
  #   resume_pct: 85            # data disk use below which jobs start again
  #   io_heavy: []              # instance names (repo lowercased, other characters to '-') the guard pauses while the io pressure stays high
  #   cache_max_gb: 150         # size cap of the shared compile cache
  #   data_dir: /mnt/data/ci    # state; default is ~/.local/state/runner-up
  #   machines: []              # other machines; see "Other machines"
```

`./ship.sh launch` installs the latest runner-up release (checksum verified, see [Dependencies](dependencies.md#latest-releases)), writes the configs and the units, and starts one coordinator for each repository (`runner-up@<repo>`).
A second apply changes nothing.
It needs the `docker` profile.

## How the config is made

`~/.config/runner-up/<repo>.json` is a template of one repository's entries: one file and one coordinator (`runner-up@<repo>`) for each repository, where `<repo>` is the name in lower case with a dash for each run of other characters (`owner/My_Repo` is `owner-my-repo`).
A coordinator applies an edited file by itself, so a change needs no restart and no job stops.
Every coordinator runs in `runnerup.slice` and keeps its own state in `<state dir>/<repo>`.

| `runner_up` | runner-up config |
| --- | --- |
| `repos[].repo` | one entry in `github.repos` |
| `repos[].slots` | that many places, named `<slot name>-<n>` as the CI pool names its slots |
| `repos[].name` | the slot name; a second group of one repository (a quick group) keeps its own places |
| `repos[].labels` | one pool for each label except `self-hosted`, `linux` and the other labels that runner-up reserves; only the entry's own places serve it |
| `job_cpus`, `job_memory_gb` | `--cpus` and `--memory` of each place; `job_cpus` is also the default `CARGO_BUILD_JOBS` of each job, so a Rust job does not start a compile for every CPU of the host, and each job also gets `MOLD_JOBS=1` (one mold link at a time; harmless without mold). The thread count of one link stays bounded by the container `--cpus` quota, not reduced. A job's own value of either variable wins. To cap a heavy repository, give its entry fewer `slots` (for example `slots: 2`) |
| `total_slots` | split across the coordinators by their repositories' `slots` (each share is at least 1, so with more repositories than `total_slots` the sum is a little higher). Each coordinator's machine budget is its share times the job caps; the slice caps limit all of CI together |
| `docker: dind` | refused: runner-up has no Docker daemon in the job, so the entry stays on the CI pool (see [Not covered](#not-covered)) |

A pool is a scale set of GitHub, and it is global to its coordinator: it opens in every repository that the coordinator serves.
That is why each repository has a coordinator of its own, with only its own labels.
One coordinator for all repositories would open a scale set in each repository for every label, 272 for 16 repositories and 17 labels, and GitHub refuses many of them.
A scale set stays in the repository settings after its coordinator stops; it is idle and harmless.
The workflow asks for the pool with the label alone: `runs-on: my-label`.
`runs-on: [self-hosted, linux, my-label]` still goes to the CI pool.

## Caps

Every job container and image build runs in `runnerup.slice`, so these caps hold for all of CI as one group:

| Cap | Value | Effect |
| --- | --- | --- |
| `CPUWeight` | `cpu_weight` (20) | When the host wants the CPU, CI gets about a fifth of what an equal-weight task gets. An idle CPU is free for CI. |
| `IOWeight` | `io_weight` (20) | The same for disk I/O. |
| `MemoryMax` | `memory_max` (50%) | A hard limit. The kernel stops the biggest process of the slice at the limit, not a process of the host. |
| `CPUQuota` | `cpu_share` (50) | A hard limit: this percent of the host's CPUs, even when the host is idle. |
| `IOWriteBandwidthMax`, `IOWriteIOPSMax` | `io_write_mb` (120), `io_write_iops` (600) | Hard limits on `io_write_device`; none without it. Lower values starve Rust builds: at 40 MB/s and 200 IOPS `cargo nextest` ran over an hour and runs queued for hours. A `systemctl set-property --runtime` value is not in the recipe and an apply does not remove it; reset it with `systemctl revert runnerup.slice`. |
| `Nice` | `nice` (10) | Priority of the coordinator and its place runners. |
| Process limit | 8192 for each job | As in the CI pool. |
| Concurrency | `total_slots` | At most `max(total_slots, number of repositories)` jobs run at one time, because each coordinator keeps at least one slot. The slice CPU and memory caps always hold, whatever the count. |

runner-up starts a job with a plain `docker run`, which puts the container in `system.slice`.
The unit puts a `docker` shim first in `PATH` (`~/.local/share/runner-up/shim/docker`, from `blueprint/maintenance/runner-up-docker`).
The shim adds `--cgroup-parent runnerup.slice` and `--pids-limit 8192` to `docker run` and `--cgroup-parent` to `docker build`, and uses `sudo -n docker` when the account is not in the `docker` group.
The coordinator's own processes run under `Nice=` and a low I/O priority in the user manager.

Check the caps:

```bash
systemctl show runnerup.slice -p CPUWeight -p IOWeight -p MemoryMax
sudo docker inspect runner-up-<place> --format '{{.HostConfig.CgroupParent}}'   # runnerup.slice
```

## Build gate

One host-wide job pool keeps Cargo builds from piling up: `build-gate <command...>` (from `blueprint/maintenance/build-gate`, installed as `~/.local/bin/build-gate`). It waits, and never fails, while `/sdc-disk` is above 85% or `/proc/pressure/io` `full` avg60 is above 40. Then it takes one `flock` slot in `/tmp/build-gate` and holds it until the command ends. Every caller reads the one slot count from `~/.local/share/build-gate/slots` (`BUILD_GATE_SLOTS_FILE`; it survives a reboot; default 4 when the file is missing; set `build_gate_slots` under `runner_up`; keep it below `total_slots`). `BUILD_GATE=off` skips the gate; `BUILD_GATE_DISK_PATH`, `BUILD_GATE_DISK_PCT`, `BUILD_GATE_IO_PCT` and `BUILD_GATE_DIR` change the limits. A command that runs under the gate does not wait again.

Set `build_gate: true` under `runner_up` to install the pool on a host:

- runner-up jobs: the service gets `RUNNER_UP_BUILD_GATE`, and the docker shim starts each `docker run` through the gate, so a job holds a slot for its whole run.
- Host builds (workers, mates): `~/.local/bin/cargo` is a shim. It runs `build`, `test`, `check`, `clippy`, `nextest`, `doc`, `install` and `bench` through `build-gate`, then the next `cargo` on `PATH`. Rollout check: `command -v cargo` must print `~/.local/bin/cargo`; rustup's `~/.cargo/env` puts `~/.cargo/bin` first, so put `~/.local/bin` before it.
- Rollout is a host step, not code: set `build_gate: true` for the `codex-gpui` host or coordinator first, wait one full cycle, then set it fleet-wide.

## Disk

A job container is removed when its job ends (`docker run --rm`), and its work directory goes with it.
`runner-up-clean.timer` runs `runner-up-maintain clean` every hour:

- removes stopped containers that carry the label `runner-up.place` and are older than an hour (a place that crashed left them);
- removes untagged image layers;
- keeps the Docker build cache under `disk_max_gb`.

Each step runs alone with a time limit (`RUNNER_UP_PRUNE_TIMEOUT`, 280 s): a step that fails or hangs on a busy disk does not skip the next ones, and the unit then ends failed.
It never touches a running container.

`runner-up-guard.timer` runs `runner-up-maintain guard` every 2 minutes.
When the disk of `data_dir` (the home when unset) is at or above `pause_pct` (88), it stops the coordinators, so no new job starts; running jobs finish, because stopping a coordinator leaves its places alone.
Each run also removes every stopped place container, with the job's target directory in its layer, so a crashed place does not hold the disk for an hour; a running container stays.
Below `resume_pct` (85) it starts again only the coordinators it stopped.
`runner-up-maintain io-pause <unit...>` stops units for IO pressure (a heavy build) and records them; every manual IO pause must use it, so the unit resumes on its own.
The guard also pauses by itself: when `/proc/pressure/io` `full avg60` stays above 40% for 3 minutes, it io-pauses the running coordinator of `io_heavy` that started last, one per run; its running jobs keep running.
When `full avg60` stays below 40% for 10 minutes, each guard run starts one recorded unit and removes it from the list; a spike resets the 10 minutes.
The disk rule keeps its own units: no unit starts while the disk is at `resume_pct` or above.
The job image `crewship-ci-runner:latest` is the CI pool's image (`blueprint/containers/ci-runner.Dockerfile`).
The coordinator's start builds it when it is missing.
`runner-up-image.timer` rebuilds it every hour with `--pull --rm --force-rm` and prunes the old layers, only when `crewship.ci_pool` is absent: the CI pool's own timer builds the same image.

## Cut over one repository

Run the CI pool and runner-up side by side, and move a repository only after a real job passed on runner-up.
No step stops a busy runner.

1. Add the repository's entry to `runner_up.repos` (the same entry as in `ci_pool.repos`, without `docker`) and apply.
   `runner_up.repos` is the full list; every repository that already moved stays in it.
   Apply starts `runner-up@<repo>` for the new repository and leaves the other coordinators alone.
   The CI pool keeps all of its slots.
2. Run the repository's workflow from a branch with `runs-on: <label>` (the label alone) on one job.
   It must pass on a runner named `runner-up-<place>`.
   A job in the old form keeps going to the CI pool, so no job waits in the gap.
3. Merge that `runs-on` change.
4. Remove the repository's entry from `ci_pool.repos` and apply.
   The CI pool stops each idle slot of the entry, where idle means GitHub shows the runner `busy: false` and its container runs no `Runner.Worker`; a failed read counts as busy.
   A busy slot is disabled and leaves after its job, so no job is cut.
5. Repeat for the next repository.

Keep `crewship.ci_pool` only for repositories that did not move yet and for `docker: dind` entries, until [#1179](https://github.com/i098/Crewship/issues/1179) lands.
To roll back a repository, add its entry back to `ci_pool.repos` and apply, so the CI pool starts its slots, and change `runs-on` back.
Remove it from `runner_up.repos` once the CI pool serves its jobs again.
Removing a repository from `runner_up.repos` stops its coordinator and deletes its unit link and config; running jobs finish, and its scale sets stay idle in GitHub.

## Other machines

`runner_up.machines` adds machines that a coordinator reaches over SSH.
A machine's budget is not shared between coordinators, so a machine joins one repository's coordinator: `runner_up.machines_repo` (default is the first repository of the list).
Each machine needs a hard `cores` and `memory_gb` budget: a place takes a job only while its size fits the budget, so the machine never runs more.

```yaml
runner_up:
  machines:
    - name: laptop
      ssh: [ci@laptop]
      provider: docker      # on a Mac, Docker from OrbStack
      slots: 1              # one place: one job at a time
      job_cpus: 2
      job_memory_gb: 4
      cores: 2
      memory_gb: 4
      # agent: /Users/ci/bin/runner-up-agent   # a wrapper, for example `taskpolicy -b nice -n 19 runner-up "$@"`
```

The machine's places serve the pools of that coordinator.
runner-up must be on the machine under the name in `agent` (default `runner-up`), and the SSH account must reach Docker.
On a Mac, runner-up v0.1.12 mounts its own file into the Linux container for the fork guard, and that file is a Mach-O program, so the job fails with `exec format error`.
Put a `docker` wrapper first in the agent's `PATH` that replaces the mount that ends in `:/opt/runner-up/runner-up:ro` with the `linux-arm64` release of runner-up (checksum verified).
The `agent` wrapper sets that `PATH`, starts OrbStack when it is stopped, and runs `taskpolicy -b nice -n 19 runner-up "$@"`.
The slice, the shim and the cleanup of this page apply to the coordinator's host only; cap a Mac with its own settings (`orb config set cpu` and `memory_mib`) and the budget above.

## Container engine

runner-up needs only a `docker` command that works.
On a Mac, use OrbStack: it is a drop-in `docker` with low idle CPU and memory, and its VM takes its cores and memory from `orb config set`.
On Linux, keep Docker.
Podman with its Docker socket is also a drop-in, but it would save only dockerd itself: on the Crewship host that is 141 MB of memory and 0.5% of one core while idle.
`fleet_guards` and `project_databases` need dockerd on the same host anyway, and a rootless engine cannot put a container in the system slice that carries the caps.

## Not covered

- **Docker in the job.** runner-up's Docker place is a plain container with no daemon, and no sidecar.
  A `docker: dind` entry stays in `ci_pool.repos`; `inspect` refuses it in `runner_up.repos`.
- **Caches between jobs.** The CI pool mounts per-slot tool, cargo, apt and bun caches.
  A runner-up job starts with the caches of the image, so `actions/cache` and `Swatinem/rust-cache` restore from GitHub, and a job that relied on a warm local cache runs slower.
  The exception is the [shared build cache](#shared-build-cache): the docker shim mounts it into every local job.
- **Data-disk scratch.** A container's writes go to Docker's data root, as with any container.
  Put that root on a data disk with `crewship.data_dir` ([Data disk](configuration.md#data-disk)).
- **Updates of runner-up.** An apply installs the newest release; the running coordinator keeps its version until you run `systemctl --user restart 'runner-up@*'`.
  A restart stops no job.

## Shared build cache

Jobs do not build the same crate twice. Every local runner-up job shares one directory, `<data_dir>/ci-shared-cache/` (`~/.local/share/ci-shared-cache/` without a data directory). Apply never deletes it. Jobs on other [machines](#other-machines) do not get it.

| Directory | Mounted at | Use |
| --- | --- | --- |
| `sccache` | `/sccache` | The compile cache. The job image has `sccache` and sets `RUSTC_WRAPPER=sccache`, `SCCACHE_DIR`, `SCCACHE_CACHE_SIZE` and `CARGO_INCREMENTAL=0` for each job. |
| `cargo-registry`, `cargo-git`, `cargo-lock`, `cargo-lock-mutate` | `~/.cargo/registry`, `~/.cargo/git`, `~/.cargo/.package-cache`, `~/.cargo/.package-cache-mutate` | One registry and git cache. The two lock files are mounted so cargo's lock holds across jobs. |
| `bun`, `npm`, `pnpm-store` | `~/.cache/bun`, `~/.cache/npm`, `~/.cache/pnpm-store` | Package stores. |

`cache_max_gb` (default `150`, set under `runner_up`) caps the compile cache; sccache evicts the least recently used entries. Each job server counts its own use, so the cap holds roughly, not exactly. The directory is not shared with a live target directory: a job builds in its own checkout, and the job container, with its `target/`, goes when the job ends.

Limits: sccache caches only builds that run `rustc` through the wrapper, with the same compiler, flags and paths, so a first build on a new toolchain still compiles everything. `Swatinem/rust-cache` deletes the registry files that its own job does not use, and with a shared registry that can fail a job that runs at the same time; re-run that job. Every repository that runner-up serves can write the cache, so list only repositories whose code you trust. The account's own worktrees use their own cache: see [Data disk](configuration.md#data-disk).

## Files on the host

| Path | Contents |
| --- | --- |
| `~/.local/bin/runner-up` | The program (installer, latest release). |
| `~/.config/runner-up/<repo>.json` | The setup of one repository. Apply writes it. |
| `~/.config/systemd/user/runner-up@.service` | The coordinator unit; one instance for each repository. |
| `~/.config/systemd/user/runner-up-clean.{service,timer}` | The hourly cleanup. |
| `~/.config/systemd/user/runner-up-image.{service,timer}` | The hourly image build, without `ci_pool`. |
| `/etc/systemd/system/runnerup.slice` | The caps. |
| `~/.local/bin/build-gate` | The shared build gate. |
| `~/.local/bin/cargo` | The cargo shim, with `build_gate`. |
| `~/.local/share/build-gate/slots` | The host-wide build slot count, with `build_gate`. |
| `~/.local/share/runner-up/` | The docker shim and the image recipe. |
| `~/.local/bin/runner-up-maintain` | The image build and the cleanup. |

## See what runs

```bash
runner-up status --config ~/.config/runner-up/<repo>.json   # places, running jobs and waiting jobs
runner-up usage --config ~/.config/runner-up/<repo>.json    # sampled use of finished jobs
journalctl --user -u 'runner-up@*' -f  # the coordinators
systemctl --user list-timers 'runner-up-*'
```
