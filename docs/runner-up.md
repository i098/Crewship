# runner-up

[runner-up](https://github.com/kunchenguid/runner-up) runs GitHub Actions jobs on this host, one fresh Docker container per job.
It replaces the [CI pool](ci-pool.md) one repository at a time.
The CI pool keeps one idle runner container for every slot.
runner-up starts a container only when a job waits, so an idle host runs one small coordinator process and no job container.

## Turn it on

Add a `runner_up` block to `.local/host.yml`.
With no `repos` key, it takes the repositories, slot groups, labels and caps from `crewship.ci_pool`.

```yaml
crewship:
  runner_up: {}
  # runner_up:
  #   repos:                    # only these repositories; same shape as ci_pool.repos
  #     - { repo: owner/name, slots: 2, labels: [my-label] }
  #   total_slots: auto         # most jobs at one time; default is the ci_pool value, else auto
  #   job_cpus: 4               # CPU cap of each job container
  #   job_memory_gb: 8          # memory cap of each job container
  #   cpu_weight: 20            # CPUWeight of the slice (default 100 is the share of other work)
  #   io_weight: 20             # IOWeight of the slice
  #   nice: 10                  # Nice of the coordinator
  #   memory_max: 50%           # MemoryMax of the slice, a size (64G) or a percent of the host
  #   disk_max_gb: 50           # build cache the hourly cleanup keeps
  #   data_dir: /mnt/data/ci    # state; default is ci_pool.data_dir, else ~/.local/state/runner-up
  #   machines: []              # other machines; see "Other machines"
```

`./ship.sh launch` installs the latest runner-up release (checksum verified, see [Dependencies](dependencies.md#latest-releases)), writes the config and the units, and starts the coordinator.
A second apply changes nothing.
It needs the `docker` profile.

## How the config is made

`~/.config/runner-up/config.json` is a template of the repository list.
The coordinator applies an edited file by itself, so a change needs no restart and no job stops.

| ci_pool | runner-up |
| --- | --- |
| `repos[].repo` | one entry in `github.repos` |
| `repos[].slots` | that many places, named `<slot name>-<n>` as the CI pool names its slots |
| `repos[].name` | the slot name; a second group of one repository (a quick group) keeps its own places |
| `repos[].labels` | one pool for each label except `self-hosted`, `linux` and the other labels that runner-up reserves; only the entry's own places serve it |
| `job_cpus`, `job_memory_gb` | `--cpus` and `--memory` of each place |
| `total_slots` | the machine budget: `total_slots` times the job caps, so that at most that many jobs run together |
| `docker: dind` | not mapped; the entry stays on the CI pool (see [Not covered](#not-covered)) |

A pool is a scale set of GitHub, one for each repository and pool pair in the config.
The workflow asks for the pool with the label alone: `runs-on: my-label`.
`runs-on: [self-hosted, linux, my-label]` still goes to the CI pool.

## Caps

Every job container and image build runs in `runnerup.slice`, so these caps hold for all of CI as one group:

| Cap | Value | Effect |
| --- | --- | --- |
| `CPUWeight` | `cpu_weight` (20) | When the host wants the CPU, CI gets about a fifth of what an equal-weight task gets. An idle CPU is free for CI. |
| `IOWeight` | `io_weight` (20) | The same for disk I/O. |
| `MemoryMax` | `memory_max` (50%) | A hard limit. The kernel stops the biggest process of the slice at the limit, not a process of the host. |
| `Nice` | `nice` (10) | Priority of the coordinator and its place runners. |
| Process limit | 8192 for each job | As in the CI pool. |
| Concurrency | `total_slots` | The machine budget in the config. |

runner-up starts a job with a plain `docker run`, which puts the container in `system.slice`.
The unit puts a `docker` shim first in `PATH` (`~/.local/share/runner-up/shim/docker`, from `blueprint/maintenance/runner-up-docker`).
The shim adds `--cgroup-parent runnerup.slice` and `--pids-limit 8192` to `docker run` and `--cgroup-parent` to `docker build`, and uses `sudo -n docker` when the account is not in the `docker` group.
The coordinator's own processes run under `Nice=` and a low I/O priority in the user manager.

Check the caps:

```bash
systemctl show runnerup.slice -p CPUWeight -p IOWeight -p MemoryMax
sudo docker inspect runner-up-<place> --format '{{.HostConfig.CgroupParent}}'   # runnerup.slice
```

## Disk

A job container is removed when its job ends (`docker run --rm`), and its work directory goes with it.
`runner-up-clean.timer` runs `runner-up-maintain clean` every hour:

- removes stopped containers that carry the label `runner-up.place` and are older than an hour (a place that crashed left them);
- removes untagged image layers;
- keeps the Docker build cache under `disk_max_gb`.

It never touches a running container.
The job image `crewship-ci-runner:latest` is the CI pool's image (`blueprint/containers/ci-runner.Dockerfile`).
The coordinator's start builds it when it is missing.
`runner-up-image.timer` rebuilds it every hour with `--pull --rm --force-rm` and prunes the old layers, only when `crewship.ci_pool` is absent: the CI pool's own timer builds the same image.

## Cut over one repository

Run the CI pool and runner-up side by side, and move a repository only after a real job passed on runner-up.
No step stops a busy runner.

1. List the repository in `runner_up.repos` (the whole entry, as in `ci_pool.repos`) and apply.
   Once `runner_up.repos` exists, it is the list; every repository that already moved stays in it.
   The CI pool keeps all of its slots.
2. Run the repository's workflow from a branch with `runs-on: <label>` (the label alone) on one job.
   It must pass on a runner named `runner-up-<place>`.
   A job in the old form keeps going to the CI pool, so no job waits in the gap.
3. Merge that `runs-on` change.
4. Remove the repository's entry from `ci_pool.repos` and apply.
   The CI pool stops each idle slot of the entry, where idle means GitHub shows the runner `busy: false` and its container runs no `Runner.Worker`; a failed read counts as busy.
   A busy slot is disabled and leaves after its job, so no job is cut.
5. Repeat for the next repository.

Keep `crewship.ci_pool` until every repository moved; a `docker: dind` entry stays in it.
To roll back a repository, add its entry back to `ci_pool.repos` and apply, so the CI pool starts its slots, and change `runs-on` back.
Remove it from `runner_up.repos` once the CI pool serves its jobs again.
Removing a repository from `runner_up.repos` closes its scale sets and leaves running jobs alone.

## Other machines

`runner_up.machines` adds machines that the coordinator reaches over SSH.
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

The machine's places serve every pool.
runner-up must be on the machine under the name in `agent` (default `runner-up`), and the SSH account must reach Docker.
The slice, the shim and the cleanup of this page apply to the coordinator's host only; cap a Mac with its own settings (`orb config set cpu` and `memory_mib`) and the budget above.

## Container engine

runner-up needs only a `docker` command that works.
On a Mac, use OrbStack: it is a drop-in `docker` with low idle CPU and memory, and its VM takes its cores and memory from `orb config set`.
On Linux, keep Docker.
Podman with its Docker socket is also a drop-in, but it would save only dockerd itself: on the Crewship host that is 141 MB of memory and 0.5% of one core while idle.
`fleet_guards` and `project_databases` need dockerd on the same host anyway, and a rootless engine cannot put a container in the system slice that carries the caps.

## Not covered

- **Docker in the job.** runner-up's Docker place is a plain container with no daemon, and no sidecar.
  A `docker: dind` entry of `ci_pool.repos` stays on the CI pool and is not in the runner-up config.
- **Caches between jobs.** The CI pool mounts per-slot tool, cargo, apt and bun caches.
  A runner-up job starts with the caches of the image, so `actions/cache` and `Swatinem/rust-cache` restore from GitHub, and a job that relied on a warm local cache runs slower.
- **Data-disk scratch.** A container's writes go to Docker's data root, as with any container.
  Put that root on a data disk with `crewship.data_dir` ([Data disk](configuration.md#data-disk)).
- **Updates of runner-up.** An apply installs the newest release; the running coordinator keeps its version until you run `systemctl --user restart runner-up`.
  A restart stops no job.

## Files on the host

| Path | Contents |
| --- | --- |
| `~/.local/bin/runner-up` | The program (installer, latest release). |
| `~/.config/runner-up/config.json` | The setup. Apply writes it. |
| `~/.config/systemd/user/runner-up.service` | The coordinator. |
| `~/.config/systemd/user/runner-up-clean.{service,timer}` | The hourly cleanup. |
| `~/.config/systemd/user/runner-up-image.{service,timer}` | The hourly image build, without `ci_pool`. |
| `/etc/systemd/system/runnerup.slice` | The caps. |
| `~/.local/share/runner-up/` | The docker shim and the image recipe. |
| `~/.local/bin/runner-up-maintain` | The image build and the cleanup. |

## See what runs

```bash
runner-up status                       # places, running jobs and waiting jobs
runner-up usage                        # sampled use of finished jobs
journalctl --user -u runner-up -f      # the coordinator
systemctl --user list-timers 'runner-up-*'
```
