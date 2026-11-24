# Features

Crewship sets up AI coding agents on a VPS.
These features turn one server into a self-hosted AI coding agent server where you run parallel coding agents under one coding agent orchestrator, Firstmate.

- [omp agents](omp.md): sign-in, model roles, fallbacks, and the advisor
- [Public skills and rules](omp.md#skills): the skills and rules that ship with Crewship, installed on request (opt-in)
- [Global agent instructions](omp.md#global-instructions): the working rules for Claude Code, omp and Codex, installed on request and merged into a file you already have (opt-in)
- [Project databases](project-databases.md): one dev database container per project, in the engine its compose file names, and worktree connection strings (opt-in)
- [Jujutsu](jj.md): `jj` colocated with git for agents, digest-verified in `~/.local/bin` (opt-in)
- [fdu](configuration.md#profiles): a fast gitignore-aware `du` for large worktrees, installed with uv (opt-in)
- [vphone-linux](dependencies.md#vphone-linux): a virtual iPhone on the host for iOS app tests, so agents need no Mac (opt-in)
- [Semantic search (sgrep)](dependencies.md#latest-releases): local search by meaning for code and documents (opt-in)
- [Self-hosted Forgejo](forgejo.md): a loopback git forge for agent pushes, with nightly dumps, a GitHub feature-branch push and the no-mistakes forge profile (opt-in)
- [Configuration](configuration.md): `.local/host.yml`, the one file that describes a host
- [Capacity and auto pruners](capacity.md): host sizing per lane count, and cleanup timers
- [Data disk](configuration.md#data-disk)
- [Model usage metadata and SigNoz export](usage.md) (opt-in)
- [Private token-saving suggestions](usage.md#optional-reader-installation): a read-only report with daily delivery after a proven manual cycle (opt-in)
- [Self-hosted CI pool](ci-pool.md): GitHub Actions runners, one job per fresh container; deprecated, replaced by runner-up (opt-in)
- [runner-up](runner-up.md): GitHub Actions jobs, one container per waiting job, behind CPU, I/O, memory and disk caps (opt-in)
- [Cloudflare container runner](cloudflare-runner.md): GitHub Actions jobs, one Cloudflare Container per job (opt-in)
- [Signal bridge](../apps/signal/README.md): save a password from your phone into the secrets file, sent as a Signal Note to Self (opt-in)
- [GitHub board](github-board.md): agent work as issues on a Project board (opt-in)
- [Crew board GitHub sink](board.md#copy-messages-to-github): copy selected message topics to an existing GitHub issue (opt-in)
- [Host-move checklist](configuration.md#new-host-questions): new-host questions that follow your own checklist (opt-in)
- [Google Workspace CLI](google-workspace.md): `gws` with several Google accounts on a headless host
- [herdr-patch](../tools/herdr-patch/README.md): Herdr over mosh with real images
- [Checksum-verified toolchain](dependencies.md): every tool, package, and image the recipe installs
- [Neovim with LazyVim](dependencies.md#neovim-and-lazyvim): a terminal editor on every host, with Pyrefly for Python
- [Install, update and migrate](install.md): release artifact, updates, moving a git install
- [Migration and recovery](recovery.md): new-device sequence, desktop access, upgrades
- [Review desktop](recovery.md#desktop-access): XFCE through loopback noVNC (opt-in)
- [Host hardening](security.md#host-hardening): the Koncreet toolkit, installed as root and never run (opt-in)
- [Tailscale](security.md#remote-access): the Tailscale daemon for a private network, an option beside the gateway (opt-in)
- [Agent host move](agent-host-move.md): move the agents to a new host with parity checks
- [Security](security.md): the password gateway, Tailscale, and credentials
- [Live view and replay](#live-view-and-replay): Witch setup

## Live view and replay

Use [Witch](https://github.com/i098/witch) to watch agent sessions live and replay recordings by device.
You need access to the private Witch repository.
Crewship does not install or configure Witch.
Follow the [Witch web viewer setup](https://github.com/i098/witch/blob/HEAD/web/README.md) to watch live sessions and replays.
Set up the Witch server for real screen capture with the [Witch configuration guide](https://github.com/i098/witch/blob/HEAD/docs/configuration.md).
In `[voxl]`, map each device ID you pass to `--device` to its voxl WebSocket URL.
Witch records synthetic frames only when the `[voxl]` map is empty.
For remote access, follow [Witch’s TLS deployment guide](https://github.com/i098/witch/blob/HEAD/docs/deploy.md#tls-through-a-reverse-proxy).
Use the proxy’s HTTPS URL for the web viewer and for `--server` on remote devices.

The shared server token gives full access to recordings and capture controls for all devices.
The viewer keeps the token in the browser profile for later visits.
Open the viewer, local or remote, only in a browser profile that only trusted people use.

Enroll only Linux or macOS devices you trust with that access.
Install `cargo` and run the command from the root of the Witch checkout.
Use this bootstrap synopsis to build the command:

```text
WITCH_TOKEN="$TOKEN" scripts/bootstrap.sh --server https://witch.example.com --device laptop [--agent NAME] [-- COMMAND...]
```

Replace the server URL and device ID, and set `TOKEN` to your server token.
For the base command, omit both bracketed groups.
For each optional group you use, remove the square brackets.
Replace `NAME` with the agent name and `COMMAND...` with the command and its arguments.

Without `-- COMMAND...`, capture continues until you run `witch stop --device ID` with the same device ID.
Run the setup lines that bootstrap prints in the shell where you run `witch stop`.
With `-- COMMAND...`, Witch requests a stop when the command exits only if no session was already open.
An existing live session keeps recording after the command exits.
Witch resumes an existing paused session and keeps recording after the command exits.
