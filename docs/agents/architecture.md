# Infrastructure choice

## Decision

Use Ansible core for the native Ubuntu host and Docker Compose for isolated workloads. Keep Herdr, SSH, the user service manager, and browser lifecycle management on the host.

The source machine already uses Ubuntu packages, user-level systemd services, home-directory tools, and SSH. Ansible manages those objects directly without moving the machine to a new package store or OS. The playbook consumes a validated host document; native tools are verified against publisher checksums, npm tools against registry integrity, and the provisioning Python environment has `uv.lock`.

| Candidate | Fit here | Decision |
| --- | --- | --- |
| Ansible | Existing Ubuntu machines, apt, users, files, SSH, systemd | Primary configuration management |
| Docker / Compose | Bounded project processes, reproducible tool image, named data volumes | Optional worker and backing-service layer |
| Nix + Home Manager | Strong declarative package closure; works on Ubuntu too | Not selected: adds a daemon/store/profile migration and packaging work for locally distributed tools |
| chezmoi | Dotfile templates and per-machine configuration | Not selected: does not replace host package, user-manager, and service provisioning; a second template owner is unnecessary |
| OpenTofu | Cloud instances, networks, DNS, resource lifecycle | Add when a provider/resource contract is chosen; no pretend provider configuration is shipped |
| cloud-init | Initial VM prerequisites before configuration management | Small vendor-neutral bootstrap input only |

This is repeatable configuration, not a bit-identical OS image.
Ubuntu packages receive distribution security updates.
See [Dependencies](../dependencies.md) for tool release selection and verification.
Rebuilding an environment does not recreate authenticated accounts, databases, or running processes.

## Host and container boundary

Herdr documents a persistent headless `herdr server` and SSH remote clients. The host's user manager owns that server and survives logout through lingering. Its unit names a versioned executable directly, so an old `/usr/local/bin/herdr` cannot silently win over a newer interactive CLI.

An ordinary container has a different process and filesystem lifecycle. Docker's tiny init can reap processes; it does not reproduce the host's user D-Bus, login manager, SSH identity, or desktop session. The worker image therefore disables host-service operations and does not mount host PID state, the Docker socket, credentials, browser profiles, or Herdr session state.

Use a Linux host for the native recipe. macOS and other client devices can reach that host over SSH; this repository does not claim to reproduce Linux systemd services as native macOS services. Headless Mac setup must not depend on a GUI/TCC dialog being dismissed remotely.

### Docker worker

The Dockerfile's `worker` target is an isolated, non-root, devcontainer-style image built by the same recipe. It runs `./ship.sh launch --config blueprint/containers/crewship.container.yml`, which sets `start_services: false` and `enable_linger: false` and turns off the `docker`, `tailscale`, `desktop`, `firstmate`, `chat`, and `gateway` profiles and the browser pruner. The image carries the agent and development toolchain and the rendered agent configs, with no systemd services, linger, or Docker-in-Docker. Compose and CI use this image.

The devcontainer uses the `builder` stage, with the same provisioned filesystem and non-root user before the final layer merge.
The build requires Docker Buildx because the Dockerfile uses BuildKit secret mounts.
Dev Containers inspects the base image before building; the `worker` stage starts from `scratch`, which no registry can supply.
The builder retains earlier build layers, so its image is larger; the published worker image and runtime isolation stay unchanged.

This is a **worker-only** image, not a complete Crewship host.
It does not run Firstmate or the host's Herdr and systemd services.
Use the [native install](../../README.md#quick-start) for the complete host.

With Docker installed and available to your account, run this from any directory; no checkout or Compose file is needed:

```bash
docker pull ghcr.io/i098/crewship:latest
docker run -d --name crewship-worker --init \
  --cpus 4 --memory 6g --memory-swap 6g --pids-limit 4096 \
  --shm-size 512m --cap-drop NET_RAW \
  --tmpfs /tmp:rw,nosuid,nodev,size=1g,mode=1777 \
  --mount type=volume,source=crewship-workspace,target=/home/coder/Dev \
  ghcr.io/i098/crewship:latest sleep infinity
docker exec -it crewship-worker bash
```

The shell opens as the non-root `coder` user in `/home/coder/Dev`.
Run `omp` there and follow the [sign-in guide](../omp.md#sign-in).
The named volume keeps project files when you replace the container.
Credentials created inside the container remain in that container, not in the workspace volume.
Do not mount your host's credentials, home directory, Docker socket, or Herdr state.

Leave the shell with `exit`; enter it again with `docker exec -it crewship-worker bash`.
Stop the worker with `docker stop crewship-worker`; resume it with `docker start crewship-worker`.

For Compose or local image builds, clone this repository and use its root [`compose.yml`](../../compose.yml).
The `worker` profile starts the worker; the optional `data` profile adds example PostgreSQL and Redis services.
Set up the password file described in `compose.yml` before enabling `data`.

## Treehouse and worker worktrees

The `agents` profile installs [Treehouse](https://github.com/kunchenguid/treehouse), which manages a pool of reusable Git worktrees.
Firstmate uses this pool for worker checkouts on the native Herdr backend.
A Git worktree shares the repository's objects, history, and branch references, but has its own files, index, and `HEAD`.
Each worker gets a separate checkout so its edits, staging, and branch switches do not change another worker's files.
This is filesystem isolation for concurrent development, not a security sandbox: workers still share the host, credentials, and external services.

### Paths and configuration

Without a root override, pools live under `~/.treehouse`.
The normal checkout layout is `~/.treehouse/<repo-id>/<slot>/<repo>`.
The repository ID combines the repository name with a hash of its remote URL, or its absolute path for a local-only repository.
The pool root contains multiple repository pools; it is not the primary clone or a Firstmate task home.
Firstmate keeps task records in its home's `state/` directory and records the worker checkout as `worktree` in the task metadata.
Do not infer checkout ownership from a directory name.

Treehouse appends `.treehouse` to an explicit `root`: `/srv/crew-data` selects `/srv/crew-data/.treehouse`, not `/srv/crew-data` itself.
Root selection uses `--root`, then `TREEHOUSE_ROOT`, then `root` in the project `treehouse.toml` or user `~/.config/treehouse/config.toml`.
A project config takes precedence over the user config; with neither, Treehouse uses its built-in default.
Relative roots resolve from the repository root.
Crewship's `data_dir` setting writes the user-level root for future pools; see [bulk storage and compatibility limits](../configuration.md#compatibility-limits).
Changing the root does not move existing pools and can make them invisible to a command using the new root.
Do not change it while workers use that pool.

### Create, reuse, and cleanup

1. Firstmate's `bin/fm-spawn.sh` runs `treehouse get` in the project, verifies the resulting isolated checkout, and records its task ownership.
   Treehouse fetches by default, reuses a clean, idle, unleased worktree whose work is merged, or creates a slot within `max_trees`.
   It resets the checkout to the selected base and normally hands it over with detached `HEAD`; the worker creates its task branch.
   Reuse belongs to the same backing clone, even when another clone has the same remote URL.
2. Treehouse keeps reusable slots rather than cloning the repository for every task.
   Ignored dependency and build files can remain in a returned slot, so later work can reuse them.
   Optional user-level `post_create` hooks run after acquisition, including reuse; Crewship does not require a warm-up hook.
3. Firstmate's `bin/fm-teardown.sh` checks task ownership and work safety before returning the recorded checkout.
   `treehouse return <path>` terminates lingering processes, resets the checkout, and releases its reservation for reuse.
   Returning can discard changes; workers must not return their own slot or clean another worker's pool.
   Firstmate owns task cleanup, including checking for uncommitted or unlanded work.

Show the current repository's pool:

```bash
treehouse status
treehouse status --json
```

Status is not strictly read-only: recovery can repair missing pool state, move untracked files into retained backups, and release recovered reservations.
Check recovery messages and backups before further maintenance.

Treehouse also supports durable reservations with `get --lease`; these remain reserved until returned, even without a running process.
For manual maintenance, `treehouse prune` previews stale, clean, idle, merged worktrees; `--yes` performs deletion.
Leave live-pool maintenance to Firstmate or the responsible operator, not a worker acting on an apparently idle directory.
The [fleet cleanup guards](../fleet-guards.md#cleanup-pool-roots) remove eligible build output separately; they do not replace task ownership checks.

## Seeded Firstmate and OMP configuration

The `firstmate` profile copies each name in `crewship_firstmate_config_names` (`blueprint/ansible/group_vars/all/agent_config.yml`) from this repository's `blueprint/config/` into the Firstmate checkout's `config/`, which Firstmate gitignores. Preflight requires every source and verify requires every destination. The seeded files:
The backend is separate: apply writes `firstmate.backend` only when it creates the checkout, and never requires it on an existing checkout.

| File | Value |
| --- | --- |
| `crew-dispatch.json` | See [Firstmate dispatch defaults](../configuration.md#firstmate-dispatch-defaults) for per-task model choices and thinking levels. |
| `secondmate-harness` | `omp anthropic/claude-opus-5-5 medium`. |
| `omp-crew-overlay.yml` | omp overlay Firstmate applies to crewmate and scout launches, never secondmates, ahead of its tracked worker overlay. It sets `modelRoles.advisor: anthropic/claude-fable-5-1:low`, `advisor.enabled: true`, `advisor.immuneTurns: 10` and `advisor.syncBacklog: "off"`, plus `providers.anthropic.serverSideFallback: false`: with the global server-side fallback on, Anthropic rejects every advisor call with a 400. Every omp crewmate runs a fable-5.1 advisor at low thinking (its lowest level). Crews never wait on it, because `syncBacklog: "off"` overrides the global `"1"`. Turns that land during a review batch into the next call instead of one call per turn, and the advisor interrupts at most once per 10 turns. omp has no every-N-turns setting. |
| `spawn-memory-floor-mb` | `8000`; see [fleet guards](../fleet-guards.md). |
| `crew-harness` | Crew harness. |
| `backend` | New checkouts only: `firstmate.backend`, default `herdr`. Existing files and an absent backend stay unchanged. |
| `startup-memory-budget` | `1000000` estimated tokens: no practical cap on the startup prompt memory. |
| `herdr-presentation-spaces` | `off`: crewmates and scouts use the flat Herdr layout, not one workspace per task. |
| `turnend-churn-absorb` | Present (empty): the watcher may also count a pane that changed as work evidence for a bare turn end. |

`blueprint/config/omp.yml` seeds `~/.omp/agent/config.yml` on first write only. It holds the host's `modelRoles` (`default` is `anthropic/claude-opus-5-5:high`, `task` and `subagent` are `anthropic/claude-opus-5-5:auto`, `memory` is `anthropic/claude-haiku-5-5`, `advisor` is `anthropic/claude-opus-5-5:auto`, `smol` is `anthropic/claude-sonnet-5-5:off`, and `commit` and `tiny` are `anthropic/claude-haiku-5-5`), `tier.openai: priority`, and `retry.fallbackChains` with no `default` chain. Its `advisor` block keeps the global advisor off (`enabled: false`) with `syncBacklog: '1'`; only crews and the omp the no-mistakes daemon spawns turn it on. Crews do it through the overlay above, which also sets `syncBacklog` to `"off"`; the daemon's omp does it through its own overlay ([no-mistakes pipeline agent](../omp.md#no-mistakes-pipeline-agent)). No router or gateway sits between omp and the provider.

Crews use the dispatch policy above, not the host's `modelRoles.default`.
See [omp setup](../omp.md#what-the-recipe-sets-up) for model override merging and context configuration.

Host sizing and every auto pruner are listed in [Capacity and pruners](../capacity.md).

## Reproducibility policy

1. Follow [Dependencies](../dependencies.md) for tool release selection, download verification, and exceptions.
2. Do not copy a live global package directory.
3. Three locks stay, because they are this repository's own development environment rather than installed tools: change Python dependencies with `uv lock` and commit the lock, change `apps/crewboard/` Rust dependencies with `cargo update` or `cargo add` and commit `apps/crewboard/Cargo.lock` (CI builds with `--locked`), and keep each GitHub Action pinned to the commit SHA of its latest release, which `.github/dependabot.yml` advances weekly.
4. Keep machine differences in ignored `.local/host.yml`; schema validation precedes provisioning.
5. Do not force, stash, reset, or overwrite a modified Firstmate checkout or an unmanaged command. Resolve that conflict explicitly.
6. Keep authentication and mutable application state outside the recipe. Provider model access must be checked on the destination account.

## CI

GitHub Actions (`.github/workflows/ci.yml`) starts on pushes to `main`, on pull requests, and on manual dispatch.
When classification succeeds and identifies code changes, CI runs these checks:

- `uv sync --locked --group dev`, then `ruff check` and `pytest -n auto --dist worksteal` (pytest-xdist).
- The [project database service verification](../project-databases.md#verification), run in a separate parallel job with its own 20-minute limit.
- [Token-suggestion installation and runtime checks](../../tests/test_token_suggestions_install.py) use a fresh non-root CI account, except for `scope=imessage`.
- `tests/test_herdr_patch.py` again on Python 3.9, the version macOS ships, because [herdr-patch](../../tools/herdr-patch/README.md) also runs on the operator's computer.
- `bash blueprint/config/omp-as-pi/test.sh`, the offline tests of the omp-as-pi wrapper ([no-mistakes pipeline agent](../omp.md#no-mistakes-pipeline-agent)).
- `./ship.sh inspect` for `blueprint/config/default.yml` and `blueprint/containers/crewship.container.yml`.
- Audits of the Dockerfile, devcontainer, and Compose definitions (the image builds from `mirror.gcr.io/library/ubuntu:latest`, Compose services are digest-pinned, no host namespaces or socket, resource caps).
- On code PRs, the `quality gate` job checks the committed baseline and blocks structural regressions or an unavailable verdict.
  `fallow audit` warns about changed JS/TS ([Quality gate](../omp.md#quality-gate)).
- A full worker image build and the behavior smoke in `tests/container-smoke.sh`.
- The harbor checks in WebKit on iPhone and in desktop Chromium.

The `changes` job compares the PR merge commit with its base and outputs `code=true` or `code=false`, and `scope=imessage` or `scope=all`.
Documentation-only PRs change only root-level `README*` files, files under `docs/` or `changelog.d/`, or `*.md` files at any depth.
Files under `blueprint/skills/`, `blueprint/rules/`, and `blueprint/config/` count as code, including Markdown files.
Renames check both the old and new paths.
CI skips heavy jobs on documentation-only PRs when classification succeeds.
PRs limited to `site/**` and documentation also skip heavy jobs.
Job-level conditions let skipped required checks report instead of remaining pending.
The `changelog fragment` job lives in `changelog.yml`, so label changes re-run only that workflow; `ci.yml` ignores `labeled`/`unlabeled`. It runs on PRs unless they have the `no changelog` label.
The required `pull request body` job lives in `pr-body.yml` and runs on opened, edited, synchronized, and reopened PRs.
It uses Python's standard library, runs its focused checker tests, and validates the body against the repository template.
It has no path, label, author, or release exemption.
Body edits do not restart the main build workflow.
The required `configuration and python checks` name stays unchanged.
It succeeds only when classification, Python checks, and runtime smoke all pass.
Python checks run on their own runner and keep their 20-minute limit.
Failed, cancelled, and skipped validation jobs cannot produce a successful required check.
CodeQL keeps running through GitHub's default setup.
Code PRs run all heavy jobs.
A PR that changes only `apps/imessage/` plus documentation (`scope=imessage`) runs only the iMessage tests and the core tests (changelog, instructions, README, skills) in the Python step; every other change and every push runs the whole suite.
Pushes to `main` and manual runs execute heavy jobs except the PR-only quality gate.

Every action is pinned to the commit SHA of its latest release (Dependabot moves the pins weekly), and the CI token is read-only. uv and Bun are their latest releases, the same as `./onboard.sh` and `./ship.sh launch` install.

`.github/workflows/npm-publish.yml` runs when a `v*` GitHub release is published.
See [Release channels and steps](../../CONTRIBUTING.md#changelog-and-releases) for version checks and publication rules.
The workflow uses npm trusted publishing: the job's OIDC token (`id-token: write`, with `contents: read`) replaces a stored npm token.
npm adds a provenance attestation.
The npm trusted publisher accepts only this workflow in the `npm` environment, and only `v*` tags can deploy to that environment.
Each publish shows under Deployments with the package page as its URL.
The package holds only `tools/npm/crewship.js`, which fetches and runs `install.sh` from the matching release.
`tests/test_npm_package.py` fails if anything else enters the tarball.

`.github/workflows/release-artifact.yml` attaches assets to a draft release with `contents: write` as its only permission.
It has no `published` trigger because immutable releases accept assets only before publication.
See [Release steps](../../CONTRIBUTING.md#release-steps) for channel selection and artifact preparation.
See [Install, update and migrate](../install.md) for installer selection, verification, and legacy archive support.

## Primary sources

- [Herdr installation](https://herdr.dev/docs/install/), [headless/SSH persistence](https://herdr.dev/docs/persistence-remote/), [session-state limits](https://herdr.dev/docs/session-state/), [config reference](https://herdr.dev/docs/config-reference/).
- [Herdr latest release](https://github.com/herdrdev/herdr/releases/latest). See [Dependencies](../dependencies.md#latest-releases) for each tool's checksum source.
  Crewship does not claim that a release supplies an independent SBOM or signature bundle.
- [Node.js release index](https://nodejs.org/dist/index.json). Node assets are verified against the `SHASUMS256.txt` published beside each release.
- [rustup stable release](https://static.rust-lang.org/rustup/release-stable.toml). rustup-init is verified against the `.sha256` published beside it.
- [Ansible introduction](https://docs.ansible.com/projects/ansible/latest/getting_started/index.html), [checksummed downloads](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/get_url_module.html), [user systemd/D-Bus requirements](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/systemd_service_module.html).
- [systemd lingering](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html).
- [Docker process boundaries](https://docs.docker.com/engine/containers/multi-service_container/), [Docker and host firewall behavior](https://docs.docker.com/engine/network/firewall-iptables/).
- [Nix multi-user installation](https://nix.dev/manual/nix/stable/installation/multi-user.html), [standalone Home Manager](https://nix-community.github.io/home-manager/installation/standalone.html).
- [chezmoi setup](https://www.chezmoi.io/user-guide/setup/), [OpenTofu scope](https://opentofu.org/docs/intro/).
