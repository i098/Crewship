<h1 align="center">🚢 Crewship</h1>

<div align="center">

**This makes it super easy to start using agents in the cloud, enjoy!**

[![CI](https://img.shields.io/github/actions/workflow/status/i098/Crewship/ci.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=CI)](https://github.com/i098/Crewship/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/i098/Crewship?style=for-the-badge&logo=github&label=&color=2563eb)](https://github.com/i098/Crewship/releases/latest)
[![License: FSL-1.1-Apache-2.0](https://img.shields.io/badge/FSL--1.1--Apache--2.0-0d9488?style=for-the-badge)](LICENSE)
[![Stars](https://img.shields.io/github/stars/i098/Crewship?style=for-the-badge&logo=github&color=d97706)](https://github.com/i098/Crewship/stargazers)
[![Sponsor](https://img.shields.io/badge/Sponsor-db61a2?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/i098)

[Docs](#more-docs) · [Install](#quick-start) · [Changelog](CHANGELOG.md) · [Discussions](https://github.com/i098/Crewship/discussions)

</div>

## Quick start

Do you already have a server for Crewship?

**No:** run this on your laptop with Node.js 18 or newer and npm:

```bash
npx crewship init
```

Or use `bunx crewship init` with Bun and Node.js installed.
The guide recommends a server size from your expected load and waits for purchase confirmation before setup.

**Yes:** use Ubuntu 24.04 or 26.04 with systemd, at least 4 vCPUs, and 16 GB RAM.
Check [Capacity](docs/capacity.md) for your load.
Sign in over SSH with a non-root account that has sudo, then run this **on the server**:

```bash
curl -fsSL https://raw.githubusercontent.com/i098/Crewship/main/install.sh | bash
```

The installer offers a feature checklist and installs omp agents and Firstmate.
Then check or resume setup **on the server**, from any directory:

```bash
"$HOME/Crewship/ship.sh" setup
```

Follow the printed commands and the [manual sign-in steps](SETUP.md#1-sign-in-to-github).
See [Setup checks](docs/configuration.md#commands) for the command's scope and limits.

For agent-assisted setup, give your coding agent this instruction:

```text
Ask whether I already have a server for Crewship first.
If yes, check its details and start setup on that server.
If no, recommend a server for my expected load and wait for purchase confirmation.
Follow https://github.com/i098/Crewship/blob/main/SETUP.md
```

To update, run the same install command again.
See [Install, update and migrate](docs/install.md) for other launchers and options.

Crewship is **source-available under FSL-1.1**, not OSI open source.
Each version becomes Apache-2.0 after two years.
See [LICENSE](LICENSE).

<div align="center">

<img src="docs/images/crewship.png" alt="Herdr with a sidebar of workspaces and omp agents working on demo repositories in parallel">

*A finished host: Herdr lists the workspaces and agents on the left, and omp agents work side by side.*

</div>

## Features

- **[Firstmate orchestration](docs/architecture.md#agent-fleet-and-supervision):** one supervisor agent runs many coding agents.
- **[Web pages from anywhere](docs/gateway.md):** one password opens agent pages and previews (opt-in).
- **[Custom Herdr sidebar](docs/herdr.md):** every workspace and agent, with state and load, at a glance.
- **[In-memory message board](docs/board.md):** agents on one host talk over topics, not disk (opt-in).
- **[Guards](docs/fleet-guards.md):** block `pkill`, gate quality, and clean up stray containers and dev servers.
- **[Schedule viewer](docs/configuration.md#schedule-viewer):** run `crewship schedules` on the server to view local jobs, owners, and results without changing schedules.
- **[Browser ladder](docs/fleet-guards.md#browser-ladder):** a light browser first, full Chrome or noVNC when needed (opt-in).
- **[Chat clients](docs/chat.md):** Discord, Slack, and [iMessage](docs/imessage.md) from the terminal (opt-in).
- **[Credentials](docs/secrets.md):** one `super.env` file, fetched by each new host via a private Worker.
- **[Mac control](docs/security.md#ssh-to-a-mac):** JARVIS-style, agents run `ssh mac` to control apps on your Mac (opt-in).

The other features, each with its docs link, are listed in [docs/features.md](docs/features.md).

## How it works

For how a host gets set up, see the [setup flow](SETUP.md#setup-flow). This is what runs on a finished host, and how its parts connect is in [Architecture](docs/architecture.md):

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/how-it-works-dark.svg">
  <img alt="You reach Firstmate from a phone or laptop with a terminal over SSH or iMessage. On your server, Firstmate hands work to second mates, who lead workers; each worker runs in its own isolated copy. An optional iMessage bridge (Photon, or a BlueBubbles relay on your Mac) and the Discord and Slack terminal chat clients run on the server. Workers use model providers and GitHub. Optional guards, the optional crew board and the secrets file are shared on the server; the secrets file can optionally come from an external Cloudflare Worker. A block of third-party services lists what the server installs or calls: bun, no-mistakes, Lavish, Sentrux and Google Workspace, and optionally Tailscale. The agents can optionally control your Mac over SSH." src="docs/how-it-works-light.svg">
</picture>

## Repository layout

- [`blueprint/`](blueprint/): what provisions a host: the Ansible playbook, seeds, skills, and guards.
- [`apps/`](apps/): services Crewship runs: crew board, iMessage bridge, and secrets Worker.
- [`tools/`](tools/): stand-alone helpers: the `crewship` launcher and schedule viewer, `herdr-patch`, and `dia-debug`.
- [`scripts/`](scripts/): the `ship.sh` CLI code, the release artifact build, and secrets helpers.
- [`site/`](site/): the crewship.si landing page.
- [`docs/`](docs/): the guides.
- [`tests/`](tests/): the test suite.
- [`changelog.d/`](changelog.d/): changelog fragments, one per pull request.

`install.sh`, `ship.sh`, and `onboard.sh` stay at the top, because the install URL and the release tarball depend on them.

## More docs

- [Architecture](docs/architecture.md)
- [Vision](VISION.md)
- [Contributing](CONTRIBUTING.md)
- [Support](.github/SUPPORT.md)
- [Report a bug](../../issues/new?template=bug_report.yml)
- [Request a feature](../../issues/new?template=feature_request.yml)
- [Pull request template](.github/PULL_REQUEST_TEMPLATE.md)
- [Security](.github/SECURITY.md)
- [Code of conduct](.github/CODE_OF_CONDUCT.md)
- [Default config](docs/default-config.md)
- [Model usage metadata](docs/usage.md)

## Built with

Built on Herdr, Firstmate, omp, Ansible and more: see [CREDITS.md](CREDITS.md).

## Star history

<a href="https://star-history.com/#i098/Crewship&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=i098/Crewship&type=Date&theme=dark&v=20261015">
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=i098/Crewship&type=Date&v=20261015">
    <img alt="Star history chart for i098/Crewship" src="https://api.star-history.com/svg?repos=i098/Crewship&type=Date&v=20261015">
  </picture>
</a>
