# CI pool

The CI pool runs GitHub Actions jobs on this host with no runner to register or remove by hand. One list in `.local/host.yml` names each repository and its number of slots. Each slot is a systemd user unit that asks GitHub for a just-in-time (JIT) runner, runs one job in a fresh container, and exits. GitHub removes a JIT runner after its one job, and systemd starts the slot again for the next job.

```mermaid
flowchart LR
    start["ci-runner@slot starts"] --> jit["POST generate-jitconfig (host gh login)"]
    jit --> run["fresh runner container: one job"]
    run --> gone["GitHub removes the runner"]
    gone --> exit["slot exits"]
    exit -->|systemd restarts it| start
```

## Opt a repository in

1. Add the repository to `crewship.ci_pool.repos` in `.local/host.yml`:

   ```yaml
   crewship:
     ci_pool:
       data_dir: /mnt/data/ci     # on a data disk, not the system disk
       # total_slots: auto        # or a number; see "Pool size"
       # job_cpus: 4              # CPU cap of each job container
       # job_memory_gb: 8         # memory cap of each job container
       repos:
         - repo: owner/name
           slots: 2
           labels: [my-label]
   ```

2. Run `./ship.sh launch`. To change only the pool, without a full apply, use [Apply without the playbook](#apply-without-the-playbook).
3. In the repository's workflow, run the job on the pool:

   ```yaml
   runs-on: [self-hosted, my-label]
   ```

Every slot carries the `self-hosted` label and the labels of its repository entry. The account that runs the pool must have a `gh` login that can administer the repository's runners (the `repo` scope).

To remove a repository, delete its entry and apply again. Its idle slots stop and are disabled, and its work and cache directories are deleted. A slot that runs a job at that time is disabled but not stopped: it finishes the job, then leaves, and a later apply deletes its directories. To stop the whole pool, set `repos: []` and apply. Removing the whole `ci_pool` section does not stop running slots, because apply then skips the pool.

## Configuration

| Key | Default | Meaning |
| --- | --- | --- |
| `data_dir` | required | Parent of the pool's directory `<data_dir>/ci-pool/`, which holds every work directory and cache. Apply creates `data_dir`, owned by `crewship.user`. Put it on a data disk. The pool deletes only inside `<data_dir>/ci-pool/`, so `data_dir` may hold other data. |
| `total_slots` | `auto` | Most slots the pool runs. `auto` computes it at apply (see below). A number fixes it. |
| `job_cpus` | `4` | `docker --cpus` of each job container. |
| `job_memory_gb` | `8` | `docker --memory` and `--memory-swap` of each job container, in GiB. |
| `repos[].repo` | required | `owner/name` on github.com. |
| `repos[].slots` | required | Slots for this repository: the most jobs it runs at one time. |
| `repos[].labels` | required | Runner labels that the workflow's `runs-on` selects. |

`./ship.sh inspect` refuses the pool without the `docker` profile, a `data_dir` with `..`, and two repositories that make the same unit name.

## Pool size

With `total_slots: auto`, apply takes half of the host's CPUs and memory. It reads the totals, not the load, so the size is the same on every apply and does not change while jobs run:

```
total_slots = floor(min(CPUs × 0.5 / job_cpus,
                        MemTotal GiB × 0.5 / job_memory_gb))
```

The other half stays free for the agents and for load peaks. Example: 96 CPUs and 247 GiB with the default caps give `min(12, 15.4)`, so 12 slots.

Slots are assigned in list order. When the repository entries ask for more slots than the total, apply starts the first ones, prints a warning that names the slots it did not start, and starts nothing else.

When the total drops, apply stops the idle slots that are over it. A slot that runs a job is never stopped: apply disables it, and it leaves after its current job. A job is never killed by apply.

When apply changes `pool.json`, it restarts the idle slots, so they register again with the new labels and caps. A slot that runs a job keeps its settings until the job ends; its next start reads the new file.

## What a job gets

- The official runner image `ghcr.io/actions/actions-runner:latest` (Ubuntu, the `runner` user with passwordless `sudo`). Each job pulls the image when a new one is available.
- The CPU and memory caps above, and at most 8192 processes.
- No Docker daemon: the host's Docker socket is not mounted. Jobs that build or run containers stay on GitHub-hosted runners.
- An empty `_work` directory for each job, emptied when the container starts.
- Caches that stay between the jobs of one repository: the tool cache (`RUNNER_TOOL_CACHE`, which the `actions/setup-*` actions use) and `~/.cache` (uv, pip, and other tools).
- A check before the first step: the runner's job-started hook ends the job container when its code comes from outside the repository, which is a pull request from a fork or a `workflow_run` that a fork's pull request started. The hook kills every process in the container, so no later step runs, not even an `if: always()` step. The slot then deletes the runner. Only the repositories in the pool's list, and only their own branches, run on the host.

## Files on the host

| Path | Contents |
| --- | --- |
| `~/.local/bin/ci-pool.py` | The script: `apply` converges the slots, `run <slot>` is each slot's `ExecStart`. |
| `~/.config/systemd/user/ci-runner@.service` | The one unit template. Apply writes it; instances are `ci-runner@<owner>-<name>-<n>.service`. |
| `~/.config/ci-pool/pool.json` | The `ci_pool` section as apply last wrote it. Each slot reads it when it starts. |
| `~/.config/ci-pool/job-started.sh` | The job-started hook. Apply writes it; each job container mounts it read-only. A slot whose hook file is missing does not start a job. |
| `<data_dir>/ci-pool/work/<slot>/` | The slot's job work directory. |
| `<data_dir>/ci-pool/cache/<owner>-<name>/tool/`, `.../home/` | The repository's tool cache and `~/.cache`. |

No token is stored. Each slot reads the host's `gh` login when it starts. When an account is not in the `docker` group, the script runs `sudo -n docker`.

## See what runs

```bash
systemctl --user list-units 'ci-runner@*'          # the slots and their state
journalctl --user -u 'ci-runner@*' -f              # runner names, job progress, errors
sudo docker ps --filter label=crewship.ci-pool # one container for each slot
gh api repos/OWNER/NAME/actions/runners            # the runners GitHub knows
```

A slot that waits for a job shows as an `online` runner that is not busy. In a job log, the "Set up job" step names the runner: `pool-<slot>-<unix time>`.

## Apply without the playbook

The playbook is not necessary for the pool. On a host where you do not want a full apply, run the same steps by hand:

```bash
sudo install -d -o "$USER" -g "$USER" -m 0755 /mnt/data/ci
install -m 0755 blueprint/maintenance/ci-pool.py ~/.local/bin/ci-pool.py
echo '{"data_dir": "/mnt/data/ci", "repos": [{"repo": "owner/name", "slots": 2, "labels": ["my-label"]}]}' \
  | python3 blueprint/maintenance/ci-pool.py apply --check   # preview; then run it without --check
```

`apply` prints one line for each change and nothing when the pool already matches the config.

## Public repositories

A self-hosted runner runs the code of the workflow that selects it. On a public repository, a pull request from a fork can change the workflow. The job-started hook ends such a job's container before any of its steps run. That is the first barrier; the trigger rule below is the second. The job container limits CPU, memory, and processes, and has no Docker socket, but it shares the host's network, and its caches stay for the next job of the same repository.

- Opt in private repositories freely. For a public repository, select the pool only in workflows that outside contributors cannot start: `workflow_dispatch` and `push` to protected branches. Never use `pull_request` from forks.
- This repository's `ci.yml` stays on GitHub-hosted runners. `ci-pool-smoke.yml` runs the same checks on the pool, and only `workflow_dispatch` starts it. It stays queued until `.local/host.yml` has the entry `{ repo: i098/Crewship, slots: N, labels: [crewship] }` in `crewship.ci_pool.repos`.
- Do not opt in a repository whose jobs need secrets that a fork pull request could reach.
- A job can change the repository's caches (`<data_dir>/ci-pool/cache/<owner>-<name>/`), which later jobs of that repository read, including jobs on the default branch. Each JIT runner is registered to one repository only, so other repositories' jobs never run in its slots or read its caches.

## macOS runner

The pool runs Linux jobs only. For macOS jobs, `blueprint/maintenance/mac-runner.sh` runs just-in-time runners on a Mac that you reach with `ssh mac` (see [SSH to a Mac](security.md#ssh-to-a-mac)).
Each repository gets one launchd user agent. The agent asks GitHub for a JIT runner, runs one job, and exits; launchd then starts it again.
The agent reads the Mac's own `gh` login, so the Mac needs `gh` signed in with the `repo` scope. No token is stored.
Every file is in one folder, `~/actions-runner-<name>/`, except one plist for each repository in `~/Library/LaunchAgents/`.

Install, from this repository on the host (the folder name is free; this example uses `i098`):

```bash
ssh mac 'mkdir -p ~/actions-runner-i098 && cat > ~/actions-runner-i098/mac-runner.sh && chmod +x ~/actions-runner-i098/mac-runner.sh' \
  < blueprint/maintenance/mac-runner.sh
ssh mac '~/actions-runner-i098/mac-runner.sh install owner/name another/repo'
```

`install` downloads the latest official `osx-arm64` runner and checks its SHA-256 digest from the GitHub release. Run it again to update the runner or to add a repository. It restarts the agents that it names, and a job that runs on one of them stops.

In the workflow, run the job on the runner, and start the workflow only for files that can change the macOS result:

```yaml
on:
  pull_request:
    paths: [.github/workflows/mac.yml, "**/*.swift", "**/*.plist", "**/*[mM]ac[oO][sS]*"]
jobs:
  test:
    runs-on: [self-hosted, macOS, mac-name]   # mac-<repository name>
```

What a job gets:

- The account's own user, with a `HOME` in `~/actions-runner-<name>/home/`. Toolchains and caches that jobs install (rustup, npm, the tool cache) stay there. Repositories share that `HOME`.
- `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, and Xcode when it is installed. No `gh` login.
- An empty work directory (`<owner>-<name>/_work/`) and `TMPDIR` for each job, and the launchd `Nice` value 10, so the Mac stays responsive.
- The same check as the pool before the first step: the job-started hook ends the runner when the code comes from a fork's pull request or a `workflow_run` that one started.

A job runs as the account on the Mac, without a container. It can read what that account can read. Opt in only repositories whose code you trust, and see [Public repositories](#public-repositories).

See what runs:

```bash
ssh mac 'launchctl list | grep mac-runner'                          # one agent for each repository
ssh mac 'tail ~/actions-runner-i098/<owner>-<name>/agent.log'        # runner IDs and job results
gh api repos/OWNER/NAME/actions/runners                             # mac-<name>-<unix time> runners
```

Remove everything (the agents, their plists, and the folder):

```bash
ssh mac '~/actions-runner-i098/mac-runner.sh remove'
```

A runner that waited for a job then shows as offline in the repository settings. GitHub deletes an offline JIT runner within one day. To delete it at once, run `gh api -X DELETE repos/OWNER/NAME/actions/runners/ID`.
