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

The Dockerfile's `worker` target is an isolated, non-root, devcontainer-style image built by the same recipe. It runs `./ship.sh launch --config containers/crewship.container.yml`, which sets `start_services: false` and `enable_linger: false` and turns off the `docker`, `tailscale`, `desktop`, `firstmate`, and `chat` profiles and the browser pruner. The image carries the agent and development toolchain and the rendered agent configs, with no systemd services, linger, or Docker-in-Docker. The devcontainer, Compose, and CI use the same image.

```bash
docker pull ghcr.io/i098/crewship:latest                  # released image (or :X.Y.Z), published on each release
docker tag ghcr.io/i098/crewship:latest crewship/worker:dev  # name Compose uses; skip to let Compose build it
docker build --target worker --tag crewship/worker .  # or build it here
docker compose --profile worker up -d                    # worker only
docker compose --profile worker --profile data up -d     # + example Postgres and Redis
```

## Seeded Firstmate and OMP configuration

The `firstmate` profile copies each name in `crewship_firstmate_config_names` (`ansible/group_vars/all.yml`) from this repository's `config/` into the Firstmate checkout's `config/`, which Firstmate gitignores. Preflight requires every source and verify requires every destination. The seeded files:

| File | Value |
| --- | --- |
| `crew-dispatch.json` | [Per-task model choice](../../README.md): small, normal, and hard tiers, with Sonnet 5.5 or GPT-6.1 Sol as the default. The spawning agent picks the thinking level. |
| `secondmate-harness` | `omp anthropic/claude-opus-5-5 xhigh`. |
| `omp-crew-overlay.yml` | omp overlay Firstmate applies to crewmate and scout launches, never secondmates, ahead of its tracked worker overlay. It sets `modelRoles.advisor: anthropic/claude-fable-5-1:low`, `advisor.enabled: true`, `advisor.immuneTurns: 10` and `advisor.syncBacklog: "off"`, plus `providers.anthropic.serverSideFallback: false`: with the global server-side fallback on, Anthropic rejects every advisor call with a 400. Every omp crewmate runs a fable-5.1 advisor at low thinking (its lowest level). Crews never wait on it, because `syncBacklog: "off"` overrides the global `"1"`. Turns that land during a review batch into the next call instead of one call per turn, and the advisor interrupts at most once per 10 turns. omp has no every-N-turns setting. |
| `spawn-memory-floor-mb` | `8000`; see [fleet guards](../fleet-guards.md). |
| `crew-harness`, `backend` | Crew harness and Herdr backend. |
| `startup-memory-budget` | `1000000` estimated tokens: no practical cap on the startup prompt memory. |
| `herdr-presentation-spaces` | `off`: crewmates and scouts use the flat Herdr layout, not one workspace per task. |
| `turnend-churn-absorb` | Present (empty): the watcher may also count a pane that changed as work evidence for a bare turn end. |

`config/omp.yml` seeds `~/.omp/agent/config.yml` on first write only. It holds the host's `modelRoles` (`default` is `anthropic/claude-opus-5-5:xhigh`, `task` and `subagent` are `anthropic/claude-opus-5-5:auto`, `memory` is `anthropic/claude-haiku-5-5`, `advisor` is `anthropic/claude-opus-5-5:auto`, `smol` is `anthropic/claude-sonnet-5-5:off`, and `commit` and `tiny` are `anthropic/claude-haiku-5-5`) and `retry.fallbackChains` with no `default` chain. Its `advisor` block keeps the global advisor off (`enabled: false`) with `syncBacklog: '1'`; only crews and the omp the no-mistakes daemon spawns turn it on. Crews do it through the overlay above, which also sets `syncBacklog` to `"off"`; the daemon's omp does it through its own overlay ([no-mistakes pipeline agent](../omp.md#no-mistakes-pipeline-agent)). No router or gateway sits between omp and the provider.

Crews use the dispatch policy above, not the host's `modelRoles.default`.
See [omp setup](../omp.md#what-the-recipe-sets-up) for model override merging and context configuration.

Host sizing and every auto pruner are listed in [Capacity and pruners](../capacity.md).

## Reproducibility policy

1. Follow [Dependencies](../dependencies.md) for tool release selection, download verification, and exceptions.
2. Do not copy a live global package directory.
3. Three locks stay, because they are this repository's own development environment rather than installed tools: change Python dependencies with `uv lock` and commit the lock, change `crewboard/` Rust dependencies with `cargo update` or `cargo add` and commit `crewboard/Cargo.lock` (CI builds with `--locked`), and keep each GitHub Action pinned to the commit SHA of its latest release, which `.github/dependabot.yml` advances weekly.
4. Keep machine differences in ignored `.local/host.yml`; schema validation precedes provisioning.
5. Do not force, stash, reset, or overwrite a modified Firstmate checkout or an unmanaged command. Resolve that conflict explicitly.
6. Keep authentication and mutable application state outside the recipe. Provider model access must be checked on the destination account.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on pushes to `main`, on every pull request, and on manual dispatch:

- `uv sync --locked --group dev`, then `ruff check` and `pytest`.
- The [shared Postgres service verification](../shared-postgres.md#verification).
- `tests/test_herdr_patch.py` again on Python 3.9, the version macOS ships, because [herdr-patch](../../herdr-patch/README.md) also runs on the operator's computer.
- `bash config/omp-as-pi/test.sh`, the offline tests of the omp-as-pi wrapper ([no-mistakes pipeline agent](../omp.md#no-mistakes-pipeline-agent)).
- `./ship.sh inspect` for `config/default.yml` and `containers/crewship.container.yml`.
- Audits of the Dockerfile, devcontainer, and Compose definitions (the image builds from `mirror.gcr.io/library/ubuntu:latest`, Compose services are digest-pinned, no host namespaces or socket, resource caps).
- The `quality gate` job: `sentrux gate .` checks the committed baseline and blocks structural regressions or an unavailable verdict.
  On PRs, `fallow audit` warns about changed JS/TS ([Quality gate](../omp.md#quality-gate)).
- A full worker image build and the behavior smoke in `tests/container-smoke.sh`.
- The harbor checks in WebKit on iPhone and in desktop Chromium.

The `changes` job compares the PR merge commit with its base and outputs `code=true` or `code=false`.
Documentation-only PRs change only `README*`, `docs/**`, `changelog.d/**`, or `*.md` files at any depth.
Files under `skills/`, `rules/`, and `config/` count as code, including Markdown files.
Renames check both the old and new paths.
Each heavy job uses a job-level condition, so skipped required checks still report.
The separate `changelog fragment` job runs on PRs unless they have the `no changelog` label.
CodeQL keeps running through GitHub's default setup.
Code PRs, pushes to `main`, and manual runs execute all heavy jobs.

Every action is pinned to the commit SHA of its latest release (Dependabot moves the pins weekly), and the CI token is read-only. uv and Bun are their latest releases, the same as `./onboard.sh` and `./ship.sh launch` install.

`.github/workflows/npm-publish.yml` runs when a `vX.Y.Z` GitHub release is published. It sets the version of the `crewship` npm package (`npm/`) to the tag and publishes it with npm trusted publishing: the job's OIDC token (`id-token: write`, its only other permission is `contents: read`) replaces a stored npm token, and npm adds a provenance attestation. The npm trusted publisher accepts only this workflow in the `npm` environment, and only `v*` tags can deploy to that environment. Each publish shows under Deployments with the package page as its URL. The package holds only `npm/crewship.js`, which fetches and runs `install.sh` from the release with the same version; `tests/test_npm_package.py` fails if anything else enters the tarball.

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
