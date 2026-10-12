# Features

- [omp agents](omp.md): sign-in, model roles, fallbacks, and the advisor
- [Shared Postgres](shared-postgres.md): one container, per-project databases and worktree connection strings (opt-in)
- [Configuration](configuration.md): `.local/host.yml`, the one file that describes a host
- [Capacity and auto pruners](capacity.md): host sizing per lane count, and cleanup timers
- [Data disk](configuration.md#data-disk): Docker and the npm and pip caches on a second disk (opt-in)
- [Self-hosted CI pool](ci-pool.md): GitHub Actions runners, one job per fresh container (opt-in)
- [GitHub board](github-board.md): agent work as issues on a Project board (opt-in)
- [Host-move checklist](configuration.md#new-host-questions): new-host questions that follow your own checklist (opt-in)
- [Google Workspace CLI](google-workspace.md): `gws` with several Google accounts on a headless host
- [herdr-patch](../tools/herdr-patch/README.md): Herdr over mosh with real images
- [Checksum-verified toolchain](dependencies.md): every tool, package, and image the recipe installs
- [Neovim with LazyVim](dependencies.md#neovim-and-lazyvim): a terminal editor on every host, with Pyrefly for Python
- [Install, update and migrate](install.md): release artifact, updates, moving a git install
- [Migration and recovery](recovery.md): new-device sequence, desktop access, upgrades
- [Review desktop](recovery.md#desktop-access): XFCE through loopback noVNC (opt-in)
- [Tailscale](security.md#remote-access): the Tailscale daemon for remote access (opt-in)
- [Agent host move](agent-host-move.md): move the agents to a new host with parity checks
- [Security](security.md): credential handling and remote access
