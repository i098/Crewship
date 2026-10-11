<div align="center">

# 🚢 Crewship

**Set up a VPS and orchestrate hundreds of agents effortlessly - hardware is the limit.**

[![CI](https://img.shields.io/github/actions/workflow/status/i098/Crewship/ci.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=CI)](https://github.com/i098/Crewship/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/i098/Crewship?style=for-the-badge&logo=github&label=&color=2563eb)](https://github.com/i098/Crewship/releases/latest)
[![License: FSL-1.1-Apache-2.0](https://img.shields.io/badge/FSL--1.1--Apache--2.0-0d9488?style=for-the-badge)](LICENSE)
[![Stars](https://img.shields.io/github/stars/i098/Crewship?style=for-the-badge&logo=github&color=d97706)](https://github.com/i098/Crewship/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/i098/Crewship?style=for-the-badge&logo=git&logoColor=white&label=updated&color=6b7280)](https://github.com/i098/Crewship/commits/main)

[Docs](#docs) · [Install](#quick-start) · [Changelog](CHANGELOG.md) · [Discussions](https://github.com/i098/Crewship/discussions)

<img src="docs/images/crewship.png" alt="Herdr with a sidebar of workspaces and omp agents working on demo repositories in parallel">

*A finished host: Herdr lists the workspaces and agents on the left, and omp agents work side by side.*

</div>

Crewship makes it super easy to start using agents in the cloud.

## Features

- **[Firstmate orchestration](docs/architecture.md#agent-fleet-and-supervision):** one supervisor agent runs many coding agents.
- **[Custom Herdr sidebar](docs/herdr.md):** every workspace and agent, with its state and load, at a glance.
- **[In-memory message board](docs/board.md):** agents on one host talk over topics that never touch disk (opt-in).
- **[Guards](docs/fleet-guards.md):** block `pkill`, gate quality, and clean up stray containers and dev servers.
- **[Browser ladder](docs/fleet-guards.md#browser-ladder):** a light browser first, full Chrome or noVNC only when needed (opt-in).
- **[Chat clients](docs/chat.md):** Discord, Slack, and [iMessage](docs/imessage.md) from the terminal.
- **[Credential management](docs/secrets.md):** one `super.env` file, fetched by each new host through a private Worker.
- **[Mac control](docs/security.md#ssh-to-a-mac):** agents run `ssh mac` to open links and control apps on your Mac (opt-in).

<details>
<summary><b>Show all features</b></summary>

- [omp agents](docs/omp.md): sign-in, model roles, fallbacks, and the advisor
- [Shared Postgres](docs/shared-postgres.md): one container, per-project databases and worktree connection strings (opt-in)
- [Capacity and auto pruners](docs/capacity.md): host sizing per lane count, and cleanup timers
- [Data disk](docs/configuration.md#data-disk): Docker and the npm and pip caches on a second disk (opt-in)
- [Self-hosted CI pool](docs/ci-pool.md): GitHub Actions runners, one job per fresh container (opt-in)
- [GitHub board](docs/github-board.md): agent work as issues on a Project board (opt-in)
- [Host-move checklist](docs/configuration.md#new-host-questions): new-host questions that follow your own checklist (opt-in)
- [Google Workspace CLI](docs/google-workspace.md): `gws` with several Google accounts on a headless host
- [herdr-patch](herdr-patch/README.md): Herdr over mosh with real images
- [Checksum-verified toolchain](docs/dependencies.md): every tool, package, and image the recipe installs
- [Neovim with LazyVim](docs/dependencies.md#neovim-and-lazyvim): a terminal editor on every host, with Pyrefly for Python
- [Install, update and migrate](docs/install.md): release artifact, updates, moving a git install
- [Migration and recovery](docs/recovery.md): new-device sequence, desktop access, upgrades
- [Review desktop](docs/recovery.md#desktop-access): XFCE through loopback noVNC (opt-in)
- [Tailscale](docs/security.md#remote-access): the Tailscale daemon for remote access (opt-in)
- [Agent host move](docs/agent-host-move.md): move the agents to a new host with parity checks
- [Security](docs/security.md): credential handling and remote access
</details>

<details>
<summary><b>Default config</b></summary>

- Agent harness: [omp](docs/omp.md), home model `anthropic/claude-opus-5-5:xhigh`, advisor off
- Models: dynamic per-task selection; small `anthropic/claude-haiku-5-5`, `openai-codex/gpt-6-luna`; ordinary (default) `anthropic/claude-sonnet-5-5`, `openai-codex/gpt-6.1-sol`; hard only `anthropic/claude-opus-5-5`.
- The spawning agent picks the thinking level.
- Codex context: 272K default, 1M maximum, `extendedContext` on.
  The current bundled omp catalog limits the effective maximum to 872K.
- omp plugins: `ponytail`, `i-have-adhd`, `caveman`
- Python tooling: [Pyrefly](https://github.com/facebook/pyrefly), a checksum-verified type checker and language server installed on every host
- omp extension `crewship-quality-gate`: [sentrux and fallow check](docs/omp.md#quality-gate) at each turn end
- omp extension `aa-mode-icons`: [mode and hook icons](docs/omp.md#status-line-icons) on the status line
- omp extension `crewship-herdr-sidebar`: topic, pane name, and PR line for the [Herdr sidebar](docs/herdr.md)
- omp extension `herdr-omp-agent-state`: Herdr's agent-state reporter
- omp extension `fm-no-pattern-kill`: blocks `pkill`, `killall`, and kill-by-`pgrep` commands
- Firstmate patch `0001-watch-wake-on-queued-inbox-note`: [wakes Firstmate](docs/dependencies.md#firstmate-patch-layer) on a queued inbox note
- Firstmate patch `0002-watch-end-idle-wait-for-inbox-note`: ends the idle wait within about 1 s for an inbox note
- Firstmate patch `0003-brief-crewboard`: adds the optional [crew board instructions](docs/board.md#firstmate-instructions)
- Hooks: `crewship-quality-gate` at omp turn end, SessionStart banners from `ponytail`, `i-have-adhd`, `caveman`, `ACTIONS_RUNNER_HOOK_JOB_STARTED` (opt-in with the [CI pool](docs/ci-pool.md))
- Pipeline gates: [no-mistakes](docs/omp.md#no-mistakes-pipeline-agent) and `ponytail-review`
- Gate models: per-run pins; routine `openai-codex/gpt-6.1-sol:medium`; ordinary (default) `anthropic/claude-sonnet-5-5:high`; hard `anthropic/claude-opus-5-5:high`.
  The verified Pi-only adapter preserves per-run model choices and fails on wrapper refusal.
- Skills and rules: [`skills/`](skills/) for omp and Claude Code, [`config/AGENTS.md`](config/AGENTS.md) for Claude Code, omp, and Codex; public files install with the `agents` profile and private files take precedence ([omp](docs/omp.md#skills)).
- omp rules ([TTSR](docs/omp.md#rules)): `always-on-skills`, `asd-ste100`, `use-native-stacked-prs`; with the browser ladder: `drive-the-browser-yourself`, `fleet-browser-default-tier`.
- Profiles on: `agents`, `development`, `firstmate`, `docker`, `chat`
- Profiles off (opt-in): `tailscale`, `desktop`, `fleet_guards`, `shared_postgres`, `fleet_browsers`
- Unset (opt-in): `data_dir`, `firstmate.checklist`, `mac_ssh`, `imessage`, `github_board`, `board`, `ci_pool`
- Full files: [`config/default.yml`](config/default.yml), [`config/omp.yml`](config/omp.yml)

</details>

After the installer finishes, paste this into your coding agent or `omp` on the new machine. It does the rest with you ([SETUP.md](SETUP.md)):

```text
Set up Crewship on this machine by following https://raw.githubusercontent.com/i098/Crewship/main/SETUP.md
```

## How it works

```mermaid
flowchart TD
    box["Fresh Ubuntu 24.04 or 26.04"] --> boot["./onboard.sh: latest uv, Ansible"]
    boot --> init["./ship.sh dock: writes .local/host.yml"]
    init --> check["./ship.sh inspect, then chart"]
    check --> apply["./ship.sh launch"]
    lock["toolchain: latest releases, checksum-verified (omp plugins excepted)"] --> apply
    apply --> profiles["Ansible profiles"]
    subgraph host["Finished host"]
        herdr["Herdr workspace"]
        fm["Firstmate orchestrator"]
        agents["omp agents"]
        guards["Fleet guards"]
        docker["Docker engine"]
        chat["Concord and slk chat clients"]
    end
    profiles --> herdr
    profiles --> fm
    profiles --> agents
    profiles --> guards
    profiles --> docker
    profiles --> chat
```

## Quick start

### Get a machine

Rent an Ubuntu 24.04 or 26.04 server from any VPS or cloud provider, for example [Hetzner Cloud](https://www.hetzner.com/cloud/), [OVHcloud VPS](https://www.ovhcloud.com/en/vps/), or [DigitalOcean Droplets](https://www.digitalocean.com/products/droplets). A spare machine at home works too.

Runs on 4 vCPU / 16 GB and up; a 96 vCPU / 247 GB host ran 37 agents in about 67 GB RAM ([Capacity](docs/capacity.md)).

### Install

With curl:

```bash
curl -fsSL https://raw.githubusercontent.com/i098/Crewship/main/install.sh | bash
```

With npx:

```bash
npx crewship
```

With bunx:

```bash
bunx crewship
```

With pnpm:

```bash
pnpm dlx crewship
```

The installer downloads and verifies a release artifact; there is no git clone. Run it again to update, and see [Install, update and migrate](docs/install.md) for the layout and for moving an older git install.

Full guide: [GitHub wiki](https://github.com/i098/Crewship/wiki).

## More docs

- [Architecture](docs/architecture.md)
- [Contributing](CONTRIBUTING.md)
- [Support](SUPPORT.md)
- [Report a bug](../../issues/new?template=bug_report.yml)
- [Request a feature](../../issues/new?template=feature_request.yml)
- [Pull request template](.github/PULL_REQUEST_TEMPLATE.md)
- [Security](SECURITY.md)
- [Code of conduct](CODE_OF_CONDUCT.md)
- [License: FSL-1.1-Apache-2.0](LICENSE)

## Built with

Built on Herdr, Firstmate, omp, Ansible and more: see [CREDITS.md](CREDITS.md).

## Sponsors

If Crewship saves you time, sponsor its development on GitHub.

<a href="https://github.com/sponsors/i098"><img src="https://img.shields.io/badge/Sponsor-db61a2?style=for-the-badge&logo=githubsponsors&logoColor=white" alt="Sponsor i098 on GitHub"></a>

<!-- The sponsors workflow writes the sponsor list between these markers; the line below is FALLBACK in scripts/sponsors.py. -->
<!-- sponsors -->
No sponsors yet. Be the first, and your name goes here.
<!-- /sponsors -->

## Star history

<a href="https://star-history.com/#i098/Crewship&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=i098/Crewship&type=Date&theme=dark">
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=i098/Crewship&type=Date">
    <img alt="Star history chart for i098/Crewship" src="https://api.star-history.com/svg?repos=i098/Crewship&type=Date">
  </picture>
</a>
