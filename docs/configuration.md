# Configuration

`.local/host.yml` is the single source of truth for one host. It is gitignored and owner-only (`0600`).

## Commands

| New name | Old name | What it does |
| --- | --- | --- |
| `./onboard.sh` | `./bootstrap.sh` | Installs the repository tooling: the latest uv, then the locked Python environment with Ansible. Changes nothing else on the host. |
| `./ship.sh dock` | | Copies `blueprint/config/default.yml` to `.local/host.yml` with your user, home, and `~/Dev` workspace filled in. Never overwrites an existing file. On a terminal it shows one checklist of the opt-in features. Options: `--user`, `--home`, `--container`, and `--with NAMES`, which turns on the named opt-ins instead of asking (`--with none` for none). The names: `public_skills`, `development`, `docker`, `chat`, `gateway`, `jj`, `fdu`, `fleet_guards`, `project_databases`, `fleet_browsers`, `tailscale`, `koncreet`, `desktop`, and `board` (the [crew board](board.md)). A choice brings what it needs: `docker` for `fleet_guards` and `project_databases`, `development` for `board`. |
| `./ship.sh inspect` | | Does the one-time config rewrite below if needed, then checks the config against `blueprint/schemas/crewship.schema.json` and the cross-field rules below. |
| `./ship.sh chart` | | Runs the Ansible playbook in check mode. Reports what would change; mutates nothing except for the one-time config rewrite below. |
| `./ship.sh launch` | | Does the one-time config rewrite below if needed, then runs the playbook for real. Asks for the sudo password when passwordless sudo is not available. With the `firstmate` profile on, the first successful interactive apply with omp signed in then opens the new-host questions (below). |
| `./ship.sh survey` | | Checks that each expected tool runs and reports `gh` authentication. Changes nothing except for the one-time config rewrite below. |
| `scripts/ship.py` | | The Python program behind `ship.sh`. |
| `scripts/provisions.py` | `scripts/install_tools.py` | Installs the public tools into the user-owned Crewship prefix. |
| `scripts/stow-secrets.sh` | `scripts/push-super-env.sh` | Pushes `~/super.env` to Cloudflare Secrets Store and redeploys the fleet-secrets Worker. |
| `scripts/put-secret.sh NAME` | | Creates or updates one secret in Cloudflare Secrets Store from stdin. Deletes nothing and deploys nothing. |
| `scripts/fetch-secrets.sh` | `scripts/fetch-super-env.sh` | Pulls `super.env` from the fleet-secrets Worker into `~/super.env`. With `NAME`, prints that one readable secret instead. |

`inspect`, `chart`, `launch`, and `survey` read `--config <path>` if you pass one, otherwise `.local/host.yml`. If `.local/host.yml` does not exist, `inspect`, `chart`, and `survey` fall back to `blueprint/config/default.yml` (user `coder`); `launch` refuses to run.

The next config read rewrites an old root key to `crewship` and prints one notice.
It keeps the original bytes in `<config>.bak` beside the config.
The rewritten YAML does not keep comments; the backup keeps them.
Both files have owner-only permissions (`0600`).
The second read changes neither file.
The rewrite keeps unknown keys and values; schema validation still rejects unsupported keys.
If both root names or an existing backup are present, the command stops without changing the config.
Keep an existing backup and move it aside before you try the rewrite again.
Host paths, unit names, and the compose image name do not change in this step.

## The host config

An excerpt with the defaults `./ship.sh dock` writes. The full document is [`blueprint/config/default.yml`](../blueprint/config/default.yml).

```yaml
crewship:
  user: coder
  home: /home/coder
  workspace: /home/coder/Dev
  start_services: true
  enable_linger: true
  data_dir: ""            # See Data disk below for path requirements and storage behavior
  profiles:
    agents: true          # Chrome autoprune, AXI tools, browser defaults
    development: false    # Rust, build tools
    firstmate: true       # Firstmate clone + dispatch settings
    docker: false         # Docker engine (group membership opt-in separately)
    tailscale: false      # Daemon only; authenticate separately
    desktop: false        # XFCE + TigerVNC + noVNC
    fleet_guards: false   # Docker guard, reapers, storage guard and browser ladder
    project_databases: false # Optional per-project dev databases, helper and env seeder
    jj: false             # Jujutsu (jj) for agents, colocated with git
    fdu: false            # fdu, a fast gitignore-aware du for large worktrees
    # public_skills: true # Optional, set only in .local/host.yml: the public skills and rules; absent keeps them on a host that has them (omp.md#skills)
    # agent_instructions: true # Optional, set only in .local/host.yml: the global agent instructions; absent keeps them on a host that has them (omp.md#global-instructions)
    fleet_browsers: false # Browser ladder (obscura tier on 127.0.0.1:9222)
    chat: false           # Concord (Discord) and slk (Slack) terminal clients
    gateway: false        # Password gateway + Cloudflare Quick Tunnel
    forgejo: false        # Self-hosted Forgejo on 127.0.0.1:20250 (tailnet HTTPS with Tailscale)
  gateway:
    allow_hours: 24       # How long an address stays allowed after the password
  herdr:
    theme: rose-pine
    toast_delivery: terminal  # notifications go to the outer terminal
    sidebar_width: 46     # Spaces and Agents sidebar layouts: see herdr.md
    sidebar_max_width: 56
    sidebar_space_rows: |
      [ ... ]
    sidebar_agent_rows: |
      [ ... ]
    sidebar_bg: "reset"   # the terminal's own background
  fleet:
    docker_guard:
      stopped_hours: 24   # Remove a stopped container this long after it exits
  firstmate:
    url: https://github.com/kunchenguid/firstmate.git
    # checklist:          # Optional; set only in .local/host.yml
    #   repo: owner/private-repo
    #   path: checklist.md
  # mac_ssh:              # Optional; set only in .local/host.yml. See security.md#ssh-to-a-mac
  #   host: <Mac tailnet name or IP>
  #   user: <Mac login>
  # skills:               # Optional, off when absent (removing it removes the skills and rules an earlier fill added); set only in .local/host.yml. See omp.md#skills
  #   private_source: git@github.com:owner/private-skills.git   # or an absolute local path
  #   private_ref: main   # Optional git branch, tag or commit; the default is the remote HEAD
  # imessage:             # Optional, off when absent; set only in .local/host.yml. See imessage.md
  #   owner: "+<country code><number>"
  #   owner_name: the owner          # the default; how the desk prompt names him
  #   # desk_provider, desk_model, desk_reasoning: optional; see imessage.md#enable-it
  #   supervisor_model: ""           # the default; see imessage.md#what-it-does for identity routing
  #   transports: [photon]           # the default; in order, e.g. [photon, bluebubbles] with the block below
  #   bluebubbles:
  #     relays:                      # in failover order
  #       - url: http://<relay>:1234
  #         password_env: BLUEBUBBLES_PASSWORD   # the default; a variable name in ~/super.env
  #     webhook_listen: <agent host address>:8766
  #   cards:                         # Optional: app cards; see imessage.md#cards
  #     url: https://cards.example.com   # the public hostname of the named card tunnel
  #     port: 8767                       # the default; the card-only loopback port
  #     tunnel_token_env: CARDS_TUNNEL_TOKEN   # the default; a variable name in ~/super.env
  # github_board:         # Optional, off when absent; set only in .local/host.yml. See github-board.md
  #   repo: owner/board
  #   project: 3
  # board:                # Optional, off when absent; set only in .local/host.yml. See board.md
  #   history: 256        # the defaults
  #   cap_mb: 64
  #   max_msg_kb: 64
  # ci_pool:              # Optional; self-hosted GitHub Actions slots. See ci-pool.md
  #   data_dir: /mnt/data/ci
  #   repos:
  #     - { repo: owner/name, slots: 2, labels: [my-label] }
```

`inspect` also enforces these rules:

- `user` is not `root`, and `workspace` is inside `home`.
- `firstmate` and `browser_prune.enabled` need `agents`.
- `fleet_guards` needs `docker` and `firstmate`. Obscura is always its latest release. An older `.local/host.yml` that still sets `browsers.obscura_version` or `browsers.obscura_sha256` keeps working: both keys are deprecated, ignored, and reported in one warning on stderr. No edit is required.
- `project_databases` needs `docker` and `firstmate`, but does not need `fleet_guards`. The old name `shared_postgres` still works as an alias and prints a note to rename it.
- `ci_pool` needs `docker`, and no two `ci_pool.repos` entries may make the same unit name.
- `imessage` needs `firstmate`, and `imessage.owner` is a phone number in E.164 form (`+` and digits). `bluebubbles` in `transports` needs the `bluebubbles` block.
- `github_board` needs `firstmate`, `github_board.repo` is `owner/name`, and `github_board.project` is a Project number.
- `board` needs `firstmate` and `development`.

The Firstmate checkout tracks the default branch of upstream Firstmate, not a sha. Every apply fetches `origin/main` and puts `main` at that revision plus the [Firstmate patch layer](dependencies.md#firstmate-patch-layer), so tracking it is how a host stays current. Do not re-pin it to a sha. Each run resolves `origin/main` once and reports the sha it installed. To track a fork, set `firstmate.url` in `.local/host.yml`. The URL applies to a fresh clone; verification fails when an existing checkout's `origin` is a different URL, and provisioning never changes it for you. To switch an existing checkout, run `git -C <workspace>/firstmate remote set-url origin <url>` and `git -C <workspace>/firstmate fetch origin`, reconcile any local commits on `main` with `origin/main` by hand, then run `./ship.sh launch`.

## New-host questions

After a successful `./ship.sh launch` with the `firstmate` profile on, once omp has a provider login, Crewship starts omp in the Firstmate checkout with an opening prompt. Firstmate then asks the move decisions for this host one question at a time: which secondmate homes, services, tools, and unpushed work to bring over.

- The questions follow `firstmate.checklist` when it is set and `gh` can read it: `repo` is a GitHub repository (it can be private) and `path` is the checklist file in it. Set it only in `.local/host.yml`, never in `blueprint/config/default.yml`. Otherwise they follow [Agent host move](agent-host-move.md).
- When `.local/host.yml` has no `github_board` block, a question asks whether to turn on the [GitHub board](github-board.md). The answer is off unless you choose it.
- With the `development` profile on and no `board` block in `.local/host.yml`, one more question asks whether to turn on the [crew board](board.md). The answer is off unless you choose it.
- When `project_databases` is off or omitted, a question offers the [per-project dev databases](project-databases.md).
  The prompt names the resolved config path and does not enable the profile without your choice.
- They are asked once per host. When the omp session exits successfully, apply writes the marker `~/.local/share/crewship/new-host-questions-done`; while it exists, later applies skip the questions and print one line naming it. If omp exits non-zero, apply writes no marker and prints one line saying the questions did not complete. To ask again, delete the marker and rerun `./ship.sh launch` interactively.
- The launch needs an interactive terminal, run as `crewship.user`. When stdin is not a TTY, when `CI` is set, or when another account runs apply, apply skips them without writing the marker and prints one line saying to rerun `./ship.sh launch` interactively.
- They need an omp provider login. Apply checks with `omp models --json`; when it lists no models or fails, apply skips the questions without writing the marker and prints one line saying to sign in to omp with `/login` ([Sign in](omp.md#sign-in)) and rerun `./ship.sh launch` interactively. On a new host the first apply installs omp, so sign in after it and then rerun apply.

The recipe refuses to overwrite a conflicting unmanaged command or an independently advanced Firstmate checkout. See [Drift and upgrades](recovery.md#drift-and-upgrades).

## Profiles

| Profile | Default | What it installs |
| --- | --- | --- |
| `agents` | on | omp, AXI tools, gh, no-mistakes, treehouse, gws (Google Workspace CLI; [sign-in](google-workspace.md) is manual), acpx; safe omp presentation and model-role settings (see [omp configuration](omp.md)); omp as the [no-mistakes pipeline agent](omp.md#no-mistakes-pipeline-agent); first-write acpx config; the pattern-kill guard omp extension; `~/.local/bin/ponytail-review`; browser env defaults; Chrome autoprune timer. |
| `public_skills` | off; absent keeps them on a host that has them | The skills and rules that ship with Crewship, in `~/.omp/agent/skills/`, `~/.claude/skills/` and `~/.omp/agent/rules/`. `false` or absent on a new host installs none; `true` installs and updates them; turning it off later deletes nothing. See [Skills](omp.md#skills). Private skills always install. |
| `agent_instructions` | off; absent keeps them on a host that has them | The [global instructions](omp.md#global-instructions): `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, and `~/.omp/agent/AGENTS.md` as one import line. `instructions_mode` (`skip`, `overwrite` or `append`, default `append`) says what happens to a file that exists. The installer checklist asks it when one does. |
| `development` | off | Rust toolchain (stable), build essentials. |
| `firstmate` | on | Firstmate clone tracking upstream `main`, plus seeded Firstmate config: crew dispatch, crew and secondmate harness, the crew omp overlay (crew advisor, see [omp configuration](omp.md#advisor)), Herdr backend selection, startup memory budget, the spawn memory floor, presentation spaces off, and the turn-end pane-churn flag (see [Seeded Firstmate and OMP configuration](agents/architecture.md#seeded-firstmate-and-omp-configuration)). |
| `docker` | off | Docker engine and Compose v2, with daemon defaults `init` (reaps orphaned children) and `live-restore`. Group membership is opt-in through the Ansible variable `crewship_docker_group_users`. |
| `fleet_guards` | off | Docker guard, dev-server reaper, devtools-bridge reaper, storage guard and browser ladder. See [Fleet guards](fleet-guards.md). |
| `project_databases` | off | One [dev database container per project](project-databases.md), in the engine the project's compose file names, with a helper and a worktree environment seeder. |
| `jj` | off | The latest [Jujutsu](jj.md) (`jj`), verified against its release digest, for use colocated with git. Installs no repository change. |
| `fdu` | off | The latest [fdu](https://github.com/jlevy/fdu) (MIT), a fast gitignore-aware `du` for worktrees with 100 GB or more, installed with `uv tool install --no-build fdu` into `~/.local/bin`. It uses the PyPI wheel, so it needs no Rust toolchain, and nothing is pinned: each apply moves it to the newest release. It needs the `uv` that the installer always provides. |
| `fleet_browsers` | off | The [browser ladder](fleet-guards.md#browser-ladder): the always-on Obscura CDP tier on `127.0.0.1:9222`, the on-demand `chrome` and `vnc` tiers with the `vnc` tier's TigerVNC and noVNC packages, the cookie sync and gc timers, and the ladder environment in shell profiles and the Herdr unit. `fleet_guards` provisions the same ladder, so a `fleet_guards` host needs no change. Needs no other profile; the ladder needs `iproute2` (`ss`) from the base image, which only `desktop` installs. |
| `chat` | off | The latest [Concord](https://github.com/chojs23/concord) (Discord) and [slk](https://github.com/gammons/slk) (Slack) terminal clients, their shared libraries, and a first-write config for each. Logins stay manual. See [Chat clients](chat.md). |
| `gateway` | off | The [password gateway](gateway.md) and the latest `cloudflared`: one password opens the host's loopback web pages over a Cloudflare Quick Tunnel. `crewship.gateway.allow_hours` (default 24) sets how long an address stays allowed. `./ship.sh dock` writes `true` into a new host config; the installer's `--no-gateway` writes `false`. `blueprint/config/default.yml` has `false`, so a host config from before the gateway, without the key, keeps it off on update. To turn it on there, set `profiles.gateway: true` in `.local/host.yml` and run `./ship.sh launch`. |
| `koncreet` | off for a new host; an older host config without the key keeps it | The [Koncreet](security.md#host-hardening) host hardening toolkit, installed as root and never run. See [Host hardening](security.md#host-hardening). |
| `forgejo` | off | [Self-hosted Forgejo](forgejo.md): the latest release on `127.0.0.1:20250` with SQLite, published to the tailnet over HTTPS when Tailscale runs with HTTPS certificates, an admin account with a generated password, a nightly `forgejo dump`, and an opt-in push of feature branches to GitHub. With `agents`, also the no-mistakes Forgejo base URL and token; `forgejo-axi` comes with every `agents` host. |
| `tailscale` | off | Tailscale daemon only, an option beside the gateway. Authentication is manual; see [Security](security.md#remote-access). |
| `desktop` | off | Loopback-only XFCE + TigerVNC + noVNC operator desktop on `127.0.0.1:6080`, and the Google Chrome apt package. Needs an operator-created VNC password; see [Desktop access](recovery.md#desktop-access). |

The latest Herdr release is always installed, with the captured UI preferences, the [Spaces and Agents sidebar layouts](herdr.md) with the reporter timer that feeds Spaces, and one canonical, versioned user-service executable. What each profile installs, and where it comes from, is in [Dependencies](dependencies.md).

See [Project databases](project-databases.md) for existing-host management and safe removal.

## Data disk

Set `data_dir` to an absolute path on a large data disk to keep fast-growing data off the system disk.
The default is `""`.
See [Storage guard](fleet-guards.md#storage-guard) for guard state placement and mount requirements.

| Data | Location with `data_dir` set | How |
| --- | --- | --- |
| Docker images, containers and volumes | `<data_dir>/docker` | `data-root` in `/etc/docker/daemon.json` (`docker` profile) |
| npm cache | `<data_dir>/cache/npm` | `npm_config_cache` |
| pip cache | `<data_dir>/cache/pip` | `PIP_CACHE_DIR` |
| General syslog | `<data_dir>/host-logs/rsyslog/syslog` | [Bounded general syslog](#bounded-general-syslog) |

The variables go into the managed block of `~/.profile`, the Herdr unit and the no-mistakes daemon drop-in. A running Herdr server or no-mistakes daemon reads them only after its next restart. Apply creates `<data_dir>/cache` for the account; Docker creates its own data root. The cargo cache stays in `~/.cargo` on purpose: `CARGO_HOME` also holds `bin` and `config.toml`, so moving it would break `cargo install` on PATH and ignore the existing cargo config.

The bun, pnpm and uv caches stay on the system disk on purpose. These tools hardlink packages from their cache into each worktree's `node_modules` or `.venv`, and a hardlink works only on one filesystem. With the cache on another disk, each install copies full packages into the worktree, so the worktree pools grow faster on the system disk. Move these caches only together with the pools (see below).

### Bounded general syslog

Apply changes only the general file action in the distribution `/etc/rsyslog.d/50-default.conf`.
Native rsyslog rotates the file at 128 MiB plus one message batch.
The native rotation helper accepts no argument or its exact configured file path.
It retains eight archives and one active file, approximately 1.125 GiB plus message batches.
Authentication, kernel, mail, journal, audit rules and other operator settings remain unchanged.
Only `/var/log/syslog` leaves the distribution rsyslog logrotate list, after validated logger activation succeeds.
Existing `/var/log/syslog` files, links and archives remain intact; apply neither copies nor truncates them.
Archive old files manually only after you confirm that no writer holds them.

The data directory must already exist at a canonical path on a separate mounted filesystem.
Apply rejects the system filesystem, symlinks in the configured path and unsafe existing log paths.
The logger receives stop requests from the identified mount without automatically mounting it again through socket activation.
Its startup and rotation helper reject an absent mount before they can write.
The log directory uses `syslog:adm` ownership and `2750` access.
Files use `0640` when the distribution's global `$FileCreateMode 0640` setting remains in place.
Native recreation on rsyslog 8.2312.0 uses that global setting, not the action's `fileCreateMode`.
The setgid directory bit keeps group `adm` on files that native rotation recreates, even when the logger's primary group differs.
The distribution `syslog` account needs search access through the data directory and its parents.
Keep these parent directories under trusted ownership; apply does not change their access policy.

The host must have distribution rsyslog and logrotate installed.
The rsyslog build must accept `omfile` size-limit rotation; configuration validation fails for unsupported versions.
Apply validates the complete configuration, including operator templates in other files.
If validation fails, apply restores the original rules before it changes rotation ownership or restarts the logger.
Apply activates the validated configuration inside the logging tasks, before unrelated provisioning tasks can fail.
It records checksums for the helper, mount dependency, local AppArmor policy and general action only after a successful restart.
An unchanged service-enabled apply retries deferred or failed activation.
Every service-enabled apply also starts a stopped or failed logger before rotation cleanup, without restarting a healthy unchanged logger.
Apply clears failed logger and socket activation limits before it starts or restarts rsyslog.
Custom general actions without the Crewship marker require operator reconciliation before apply.
An empty `data_dir` leaves logging unchanged, including an earlier data-drive configuration.
Removing or changing that configuration requires a planned log migration, not a silent fallback.

Where the distribution rsyslog AppArmor profile exists, apply adds only the required local paths and actual helper executables.
The profile must include `local/usr.sbin.rsyslogd`; other profile forms require operator reconciliation.
Apply keeps existing local rules; the distribution service hook reloads the profile at startup and safely handles disabled AppArmor.
Custom service units must retain that distribution hook.
With `start_services: false`, apply writes files and validates syntax but does not reload policy, reload systemd or start rsyslog.
Old rotation ownership remains until a service-enabled apply completes activation.
Check mode writes nothing.

The focused tests run helper safety checks in the normal suite.
Set `CREWSHIP_SYSLOG_CONTAINER=1` only inside a disposable root container to run the provisioning and native rotation checks.
These checks need rsyslog, logrotate, systemd tools, a tmpfs mount at `/mnt/data`, and mount permission in the container namespace.
They apply the logging task twice and require the second apply to report `changed=0`.
The activation regression also requires systemd inside the container.
It checks deferred starts, failed activation, recovery before an unrelated task failure, and unchanged recovery of stopped or rate-limited loggers.
Native checks use a copied distribution binary to avoid the host's executable AppArmor attachment.
The native rotation check verifies file ownership, modes and active/archive reads with only `adm` group access.
The checks validate profile syntax, but a separate systemd VM must verify kernel policy enforcement and service mount-loss behavior.

### Moving an existing Docker data root

Apply sets the new `data-root` but copies nothing, so Docker starts with an empty root and pulls images again. Apply refuses the switch while a container runs, because `live-restore` cannot carry containers to a new root. To keep the images, volumes and stopped containers, move the root by hand before apply:

1. Make sure that `sudo docker ps -q` prints nothing. Do not stop containers that other work needs.
2. `sudo systemctl stop docker.socket docker.service`
3. `sudo rsync -aHAX /var/lib/docker/ <data_dir>/docker/`
4. Set `"data-root": "<data_dir>/docker"` in `/etc/docker/daemon.json`, or run `./ship.sh launch`.
5. `sudo systemctl start docker.service`, then make sure that `sudo docker info -f '{{.DockerRootDir}}'` and `sudo docker images` show the new root and the images.
6. Remove `/var/lib/docker` only after that check.

For a cache, copy it with `rsync -aHAX`, apply, check the new path (for example `npm config get cache`), then remove the old copy.

### Later: pools and hardlinking caches together

The worktree pools are the largest user of the system disk after Docker. Treehouse places new pools under `<root>/.treehouse`, where `<root>` comes from `--root`, the `TREEHOUSE_ROOT` variable, or `root` in a project's `treehouse.toml` (default `$HOME`). Treehouse looks up a pool under the same root, so a changed root does not find the pools that exist now. Change it only for a project whose pool has no live worktree. When the pools are on the data disk, point the bun (`BUN_INSTALL_CACHE_DIR`), pnpm (`store-dir`) and uv (`UV_CACHE_DIR`) caches to the same disk, so the hardlinks work again. The recipe does not do this step.
