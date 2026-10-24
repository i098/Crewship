# Configuration

`.local/host.yml` is the single source of truth for one host. It is gitignored and owner-only (`0600`).

## Commands

| New name | Old name | What it does |
| --- | --- | --- |
| `./onboard.sh` | `./bootstrap.sh` | Installs the repository tooling: the latest uv, then the locked Python environment with Ansible. Changes nothing else on the host. |
| `./ship.sh dock` | | Copies `blueprint/config/default.yml` to `.local/host.yml` with your user, home, and `~/Dev` workspace filled in. Never overwrites an existing file. On a terminal it shows one checklist of the opt-in features. Options: `--user`, `--home`, `--container`, and `--with NAMES`, which turns on the named opt-ins instead of asking (`--with none` for none). See [Profiles](#profiles) and the [crew board](board.md) for the choices. A choice brings what it needs: `docker` for `fleet_guards` and `project_databases`, `development` for `board`. |
| `./ship.sh inspect` | | Does the one-time config rewrite below if needed, then checks the config against `blueprint/schemas/crewship.schema.json` and the cross-field rules below. |
| `./ship.sh chart` | | Runs the Ansible playbook in check mode and reports what would change. Creates missing home-layout, agent preference, extension, and enabled-profile directories under the configured user's home. Leaves existing directory permissions, ownership, and managed files unchanged. Reports missing Obscura releases without downloading or extracting binaries. Also performs the one-time config rewrite below. |
| `./ship.sh launch` | | Does the one-time config rewrite below if needed, then runs the playbook for real. Asks for the sudo password when passwordless sudo is not available. Then follows the [new-host question rules](#new-host-questions). |
| `./ship.sh survey` | | Checks expected tools and `gh` authentication, plus Firstmate memory as described below. Changes nothing except for the one-time config rewrite below. |
| `./ship.sh setup` | | Checks setup readiness; see the details below. Does not install or sign in. |
| `crewship schedules` | | Opens a read-only terminal view of local cron entries, systemd timers, and registered Firstmate checks. |
| `scripts/ship.py` | | The Python program behind `ship.sh`. |
| `scripts/provisions.py` | `scripts/install_tools.py` | Installs the public tools into the user-owned Crewship prefix. |
| `scripts/stow-secrets.sh` | `scripts/push-super-env.sh` | Pushes `~/super.env` to Cloudflare Secrets Store and redeploys the fleet-secrets Worker. |
| `scripts/put-secret.sh NAME` | | Creates or updates one secret in Cloudflare Secrets Store from stdin. Deletes nothing and deploys nothing. |
| `scripts/fetch-secrets.sh` | `scripts/fetch-super-env.sh` | Pulls `super.env` from the fleet-secrets Worker into `~/super.env`. With `NAME`, prints that one readable secret instead. |

The home layout includes the Crewship CLI and schedule directories.
For an existing target account, `chart` creates these directories when missing and previews the command link without writing its target files.
If the target account is absent, `chart` reports the account work and skips steps that need that account.

For absent Herdr, Herdr Spaces, Chrome pruner, and stall nudge units, `chart` skips service starts and notified restarts.
Errors from installed units remain visible.
`launch` keeps its existing service enablement and start behavior.

`inspect`, `chart`, `launch`, and `survey` read `--config <path>` if you pass one, otherwise `.local/host.yml`. If `.local/host.yml` does not exist, `inspect`, `chart`, and `survey` fall back to `blueprint/config/default.yml` (user `coder`); `launch` refuses to run.

Run `"$HOME/Crewship/ship.sh" setup` from any directory after installation.
It reports three status lines: software, sign-ins, and fleet readiness, plus a Firstmate memory result when enabled.
It uses the same tool checks as `survey`.
With the `agents` profile enabled, it also checks GitHub authentication and requires a non-empty model list from `omp models --json`.
With the `firstmate` profile enabled, it checks the installed entry point, the new-host question marker, the running Herdr user service, and available RAM.
The service check does not depend on `start_services`, which controls provisioning actions only.
Without the `firstmate` profile, the fleet line reports that Firstmate is not enabled.
Run it as `crewship.user`; another account gets unchecked states and a command to switch accounts.
It exits with status 1 while a required check is missing or fails, and status 0 when all required checks pass.
It does not start Firstmate, prove [worker capacity](capacity.md), or send a model request.
Run each printed recovery command, then repeat `setup`.
Recovery commands for `ship.sh` use absolute paths and preserve the selected config.
If only Herdr is stopped, the recovery command starts its user service without another apply.
A memory failure does not hide recovery commands for other pending setup steps.
`setup` accepts `--config <path>`; otherwise it reads `.local/host.yml` under the Crewship installation.
It requires an existing host config instead of using the default example.
Like the other config readers, it performs the one-time rewrite below when needed.

With the `firstmate` profile on, `launch`, `survey`, and `setup` also check available RAM against the worker spawn floor.
All three commands read `MemAvailable` from `/proc/meminfo`, not total RAM or swap.
They use [`blueprint/config/spawn-memory-floor-mb`](../blueprint/config/spawn-memory-floor-mb); see [Capacity](capacity.md#load-estimate) for sizing.
`launch` checks after provisioning succeeds and before the [new-host questions](#new-host-questions).
Below the floor, or when available RAM cannot be read, all three commands return a failure status.
`launch` does not open the questions when this check fails.
The installed software stays in place.
When RAM is below the floor, free memory or add RAM, then run the command again.
If the read fails, check that `/proc/meminfo` is readable and contains a valid `MemAvailable` value.
Correct that problem, then run the command again.
A passed memory check does not prove authentication or network access.

The next config read rewrites an old root key to `crewship` and prints one notice.
It keeps the original bytes in `<config>.bak` beside the config.
The rewritten YAML does not keep comments; the backup keeps them.
Both files have owner-only permissions (`0600`).
The second read changes neither file.
The rewrite keeps unknown keys and values; schema validation still rejects unsupported keys.
If both root names or an existing backup are present, the command stops without changing the config.
Keep an existing backup and move it aside before you try the rewrite again.
Host paths, unit names, and the compose image name do not change in this step.

## Schedule viewer

Run `crewship schedules` in a terminal after installing Crewship.
The viewer uses OpenTUI's native TypeScript API on Bun and a Python standard-library collector.
It never runs a job, writes a schedule, starts a service, or sends a model request.
Press `r` to refresh; the viewer does not poll while open.

With services enabled, `launch` creates a missing `schedules` tab in the Herdr `machine` workspace and starts the viewer there.
It creates the workspace when absent and preserves custom tabs and focus.
It never sends input to an existing tab or pane, including after a restart.
If the schedules tab exists, `launch` leaves it unchanged and prints: `run crewship schedules in the schedules tab`.
Set `crewship.herdr.schedules_tab: false` to skip this setup; existing tabs stay open.
With `start_services: false`, run `launch` with services enabled after boot to open the tab.
The installer already links `~/.local/bin/crewship` to the installed CLI.
Ensure `~/.local/bin` is on your shell's `PATH` when running the command outside Herdr.

Use arrows or `j`/`k` to select a row, and Enter to open or close its details.
Press `/` to enter search; press Enter or Escape to leave search entry.
Outside search entry, press `s` to cycle sources, `o` to cycle owners, and Escape to clear all filters.
Use Page Up and Page Down to scroll details.
Press `J` to read the selected service's last 40 journal lines, and `q` to quit.
Press `p` to show or hide raw systemd properties.
Each source command has an eight-second timeout; the collector process has a 75-second limit.
Narrow terminals show the job name and result first.
Failed jobs appear first; other jobs follow their next run time.
Results use red for failure, yellow for running, green for success, and dim text for unknown or skipped results.
The time and result columns show unknown values as `-`; owner labels keep `Unknown`.

The installation records its Firstmate home in `~/.config/crewship/schedules.json`.
`FM_HOME` or `--home DIR` overrides that home.
The viewer reads that home's `data/secondmates.md`; `--registry FILE` selects another registry.
Only registered home paths with matching `.fm-secondmate-home` metadata establish second-mate ownership.
The viewer resolves relative components and symbolic links before it compares home paths or matches ownership evidence.
Worker ownership stays Unknown without proof.
Checks come from `state/*.check.sh` in the selected home and every validated registry home.
The viewer reads only check names, paths, and file modes; it never reads script contents or trust files.
Each check shows the default five-minute watcher interval.
Checks use the same validated home ownership; unmatched homes remain Unknown.
Unresolved command expansions do not establish ownership; literal unit, working-directory, and listed-check paths remain valid evidence.

The inventory covers the current login's crontab and user timers, plus system cron and system timers.
It does not scan other logins, remote hosts, containers, unloaded timer files, or the child scripts under `/etc/cron.*`.
Cron history and results stay Unknown.
The Last column means the timer's last trigger, not service completion.
Details keep service start, exit, result, exit code, and success policy separate.
A nonzero exit can be successful under systemd's policy.
An `ExecCondition` skip appears as `Skipped`, not as a failure or missing history.
Read errors remain visible as rows; failed refreshes retain previous rows marked STALE.
Unreadable home identity metadata keeps cached checks stale without reading that home's state directory.
Home identity mismatches discard cached checks.
Registry removals discard cached checks from homes other than the selected home.
Control and format characters appear as visible code-point escapes in terminal filters and errors.
Purpose labels come from service descriptions, explicit `# Purpose:` comments, or known maintenance names.
Other labels use the script name for recognized interpreters, or the executable name.
For a leading `cd DIR && command`, the viewer uses DIR as working-directory evidence and resolves relative executable or script paths.
Other wrappers keep their executable names; the viewer does not inspect their child commands.

### Terminal panes

The installer also installs two more OpenTUI panes from `tools/` into `~/.local/share/crewship/tui` and links their commands in `~/.local/bin`.
`launch` opens each one in the `machine` workspace in the same way as the schedules tab: a missing tab is created and the command starts there.
The tab label is the command name, except `crewship schedules`, which is labelled `schedules`.
An existing tab is never changed; `launch` prints `run <command> in the <label> tab` instead.
`crewship update` re-applies the same recipe, so an updated host gets every new pane and a tab for each in its existing `machine` workspace.
A rerun adds no duplicate tab, and it never restarts Herdr or touches a running pane.

| Command | Shows | Switch (default `true`) |
| --- | --- | --- |
| `crewship schedules` | local cron entries, timers, and Firstmate checks | `crewship.herdr.schedules_tab` |
| `usage-tui` | token usage from the omp stats store | `crewship.herdr.usage_tab` |
| `crewboard-tui` | crew board topics and messages | `crewship.herdr.crewboard_tab` |

A switch set to `false` skips only the tab; the command stays installed and existing tabs stay open.

## The host config

An excerpt with the defaults `./ship.sh dock` writes. The full document is [`blueprint/config/default.yml`](../blueprint/config/default.yml).
See [Model usage metadata](usage.md#installation) for the optional `crewship.usage` configuration.
See [Private token-saving suggestions](usage.md#optional-reader-installation) for the optional `crewship.token_suggestions` configuration.

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
    sgrep: false          # Semantic code search; builds with Rust
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
    backend: herdr       # New Firstmate checkouts only
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

See [iMessage credential loading](imessage.md#enable-it) for the shell format and security requirements of `~/super.env`.
Keep iMessage off by omitting `imessage`; omit `imessage.cards` to keep only the card tunnel off.

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

### Firstmate backend

New setups use `firstmate.backend: herdr`, including the guided checklist.
Set `firstmate.backend` in `.local/host.yml` before the apply that creates the checkout.
Use a supported value from the [host schema](../blueprint/schemas/crewship.schema.json).
Install an alternative backend separately.
Apply seeds `<workspace>/firstmate/config/backend` only when it creates the Firstmate checkout.
Existing checkouts keep their backend file unchanged, including an empty or absent file and its runtime detection.
Changing the recipe does not switch a running fleet.
Explicit Firstmate `--backend` and `FM_BACKEND` choices still take precedence.

### Firstmate dispatch defaults

The `firstmate` profile copies `blueprint/config/crew-dispatch.json` to `<workspace>/firstmate/config/crew-dispatch.json`.
Firstmate selects Haiku 5.5 or Luna for mechanical work and Mercury 3 for simple coding.
Sonnet 5.5 handles ordinary engineering; Opus 5.5 handles hard work.
Sonnet 5.5 is the default; Sol 6.1 takes ordinary work only when the Anthropic quota is exhausted.
Mercury 3 and Opus use `effort: high`; other tiers leave effort to the spawning home.
Astra (GPT-6) is never a worker choice.
Fable is not a spawn choice; see [Default config](default-config.md) for the automatic fallback chain.
Provider credentials are not included in the dispatch file.

Each apply normally updates the seeded Firstmate settings.
To keep local settings, use the existing Ansible override on each apply instead of `./ship.sh launch`:

```bash
uv run ansible-playbook -i blueprint/ansible/inventory.yml blueprint/ansible/site.yml \
  -e @.local/host.yml -e crewship_firstmate_config_first_write=true
```

Then edit `<workspace>/firstmate/config/crew-dispatch.json` to change a model or effort.
This option preserves existing entries in `crewship_firstmate_config_names` and copies only absent entries, including whole directories.
To skip Firstmate provisioning entirely, set `crewship.profiles.firstmate: false` in `.local/host.yml`.

## New-host questions

After a successful `./ship.sh launch` with the `firstmate` profile on, once omp has a provider login, Crewship starts omp in the Firstmate checkout with an opening prompt. Firstmate then asks the move decisions for this host one question at a time: which secondmate homes, services, tools, and unpushed work to bring over.

- The [memory check](#commands) must pass before the questions start.
- The questions follow `firstmate.checklist` when it is set and `gh` can read it: `repo` is a GitHub repository (it can be private) and `path` is the checklist file in it. Set it only in `.local/host.yml`, never in `blueprint/config/default.yml`. Otherwise they follow [Agent host move](agent-host-move.md).
- When `.local/host.yml` has no `github_board` block, a question asks whether to turn on the [GitHub board](github-board.md). The answer is off unless you choose it.
- With the `development` profile on and no `board` block in `.local/host.yml`, one more question asks whether to turn on the [crew board](board.md). The answer is off unless you choose it.
- When `project_databases` is off or omitted, a question offers the [per-project dev databases](project-databases.md).
  The prompt names the resolved config path and does not enable the profile without your choice.
- They are asked once per host.
  When the omp session exits successfully, apply writes the marker `~/.local/share/crewship/new-host-questions-done`.
  While the marker exists, later applies skip the questions and print its path.
  If omp exits non-zero, apply writes no marker and prints a recovery command.
  To ask again, delete the marker and run the printed recovery command interactively.
- The launch needs an interactive terminal, run as `crewship.user`.
  When stdin is not a TTY, `CI` is set, or another account runs apply, apply skips the questions without writing the marker.
  It prints an absolute recovery command that preserves the selected config.
- They need an omp provider login.
  Apply checks with `omp models --json`; when it lists no models or fails, apply skips the questions without writing the marker.
  It prints instructions to [sign in with `/login`](omp.md#sign-in), then run the recovery command interactively.
  On a new host the first apply installs omp, so sign in after it and then rerun apply.

The recipe refuses to overwrite a conflicting unmanaged command or an independently advanced Firstmate checkout. See [Drift and upgrades](recovery.md#drift-and-upgrades).

## Profiles

| Profile | Default | What it installs |
| --- | --- | --- |
| `agents` | on | omp, AXI tools, gh, no-mistakes, treehouse, gws (Google Workspace CLI; [sign-in](google-workspace.md) is manual), acpx; safe omp presentation and model-role settings (see [omp configuration](omp.md)); omp as the [no-mistakes pipeline agent](omp.md#no-mistakes-pipeline-agent); first-write acpx config; the pattern-kill guard omp extension; the [spawned Opus effort cap](#spawned-opus-effort-cap); the opt-in [gluttony](omp.md#gluttony-mode) omp extension; `~/.local/bin/ponytail-review`; browser env defaults; Chrome autoprune timer. |
| `public_skills` | off; absent keeps them on a host that has them | The skills and rules that ship with Crewship, in `~/.omp/agent/skills/`, `~/.claude/skills/` and `~/.omp/agent/rules/`. `false` or absent on a new host installs none; `true` installs and updates them; turning it off later deletes nothing. See [Skills](omp.md#skills). Private skills always install. |
| `agent_instructions` | off; absent keeps them on a host that has them | The [global instructions](omp.md#global-instructions): `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, and `~/.omp/agent/AGENTS.md` as one import line. `instructions_mode` (`skip`, `overwrite` or `append`, default `append`) says what happens to a file that exists. The installer checklist asks it when one does. |
| `development` | off | Rust toolchain (stable), build essentials. |
| `sgrep` | off | Semantic code and document search. Select `--with sgrep` on a new host, or set `profiles.sgrep: true` and apply on an existing host. Disabling it leaves installed files untouched. See [Dependencies](dependencies.md#latest-releases) for its Rust build and model downloads. |
| `firstmate` | on | Firstmate clone tracking upstream `main`, with [seeded configuration](agents/architecture.md#seeded-firstmate-and-omp-configuration) and [backend selection](#firstmate-backend). |
| `docker` | off | Docker engine and Compose v2, with daemon defaults `init` (reaps orphaned children) and `live-restore`. Group membership is opt-in through the Ansible variable `crewship_docker_group_users`. |
| `fleet_guards` | off | Docker guard, dev-server reaper, devtools-bridge reaper, storage guard and browser ladder. See [Fleet guards](fleet-guards.md). |
| `project_databases` | off | One [dev database container per project](project-databases.md), in the engine the project's compose file names, with a helper and a worktree environment seeder. |
| `jj` | off | The latest [Jujutsu](jj.md) (`jj`), verified against its release digest, for use colocated with git. Installs no repository change. |
| `fdu` | off | The latest [fdu](https://github.com/jlevy/fdu) (MIT), a fast gitignore-aware `du` for worktrees with 100 GB or more, installed with `uv tool install --no-build fdu` into `~/.local/bin`. It uses the PyPI wheel, so it needs no Rust toolchain, and nothing is pinned: each apply moves it to the newest release. It needs the `uv` that the installer always provides. |
| `fleet_browsers` | off | The [browser ladder](fleet-guards.md#browser-ladder): the always-on Obscura CDP tier on `127.0.0.1:9222`, the on-demand `chrome` and `vnc` tiers with the `vnc` tier's TigerVNC and noVNC packages, the cookie sync and gc timers, and the ladder environment in shell profiles and the Herdr unit. `fleet_guards` provisions the same ladder, so a `fleet_guards` host needs no change. Needs no other profile; the ladder needs `iproute2` (`ss`) from the base image, which only `desktop` installs. |
| `chat` | off | The latest [Concord](https://github.com/chojs23/concord) (Discord) and [slk](https://github.com/gammons/slk) (Slack) terminal clients, their shared libraries, and a first-write config for each. Logins stay manual. See [Chat clients](chat.md). |
| `gateway` | off | The [password gateway](gateway.md) and the latest `cloudflared`: one password opens the host's loopback web pages over a Cloudflare Quick Tunnel. `crewship.gateway.allow_hours` (default 24) sets how long an address stays allowed. Select `--with gateway` on a new host. On an existing host, set `profiles.gateway: true` in `.local/host.yml` and run `./ship.sh launch`. |
| `koncreet` | off for a new host; an older host config without the key keeps it | The [Koncreet](security.md#host-hardening) host hardening toolkit, installed as root and never run. See [Host hardening](security.md#host-hardening). |
| `forgejo` | off | [Self-hosted Forgejo](forgejo.md): the latest release on `127.0.0.1:20250` with SQLite, published to the tailnet over HTTPS when Tailscale runs with HTTPS certificates, an admin account with a generated password, a nightly `forgejo dump`, and an opt-in push of feature branches to GitHub. With `agents`, also the no-mistakes Forgejo base URL and token; `forgejo-axi` comes with every `agents` host. |
| `tailscale` | off | Tailscale daemon only, an option beside the gateway. Authentication is manual; see [Security](security.md#remote-access). |
| `desktop` | off | Loopback-only XFCE + TigerVNC + noVNC operator desktop on `127.0.0.1:6080`, and the Google Chrome apt package. Needs an operator-created VNC password; see [Desktop access](recovery.md#desktop-access). |

The latest Herdr release is always installed, with the captured UI preferences, the [Spaces and Agents sidebar layouts](herdr.md) with the reporter timer that feeds Spaces, and one canonical, versioned user-service executable. What each profile installs, and where it comes from, is in [Dependencies](dependencies.md).

See [Project databases](project-databases.md) for existing-host management and safe removal.

### Spawned Opus effort cap

The `agents` profile caps Opus 5.5 at `high` effort in Firstmate-spawned omp sessions and no-mistakes `pi` gates.
Other models and lower effort levels remain unchanged.
The extension requires both `FM_OMP_HARNESS=omp` and `OMP_SKIP_SETUP=1`, so primary sessions remain unchanged.
It caps request-level and message-level provider effort after `auto` resolves, including effort changes during a session.
The status line can still show the requested level.
The gate wrapper caps explicit `xhigh`, `max`, and `auto` requests, including model suffixes, and selects `high` when effort is absent.
The `acp:omp` fallback does not use the wrapper.

Set `FM_OPUS_EFFORT_UNCAPPED=1` in the spawned omp process environment to disable the cap for that process.
For no-mistakes gates, set this variable in the daemon environment before starting the daemon.
A shell export does not change an existing daemon or tmux pane.
Wait until no pipeline runs remain before restarting the daemon.
Crewship installs both guards on every apply; it does not restart the daemon.

### Omp model defaults

New `agents` hosts receive the restricted `enabledModels` list from the [shipped omp configuration](../blueprint/config/omp.yml).
The list includes Anthropic models, GPT models through `openai` and `openai-codex`, and Mercury 3 through Inception.
Edit `enabledModels` in `~/.omp/agent/config.yml` to change this list, or remove the key to use omp's full model list.
Apply preserves existing model choices in this file; see [omp configuration](omp.md#what-the-recipe-sets-up) for the status-line exceptions.

The Inception provider uses `https://api.inceptionlabs.ai/v1` and reads `INCEPTION_API_KEY` from the omp process environment.
Set that variable before starting omp; Crewship never installs its value.
Without the variable, Mercury requests cannot authenticate; other providers remain available.
Edit the `inception` provider in `~/.omp/agent/models.yml` to override its endpoint, credential command, or model list.
Apply seeds Inception only when no `models.yml`, `models.yaml`, or `models.json` file exists.
Existing model files keep their Inception settings unchanged, including missing fields or a removed provider.
Apply still merges the shipped Codex context-window overrides; those keys replace existing values without changing other model settings.
Disable `profiles.agents` to skip agent configuration on a new host.

## Data disk

Set `data_dir` to an existing absolute path on a mounted data disk.
On a fresh account, the default `""` keeps the legacy storage layout and writes no bulk defaults.
Clearing `data_dir` removes the managed Bash block and user-manager file.
Apply and preview tolerate a missing `.bashrc`.
Native tool keys and existing data remain unchanged.
Apply refuses a missing path or a path on the root mount before it creates bulk directories.
Keep the underlying, unmounted mountpoint root-owned and non-writable by the account.
This prevents native tools from creating replacement directories on the system disk after an unmount.
Temporary build output requires execution permission on the data mount.
See [Storage guard](fleet-guards.md#storage-guard) for guard state placement and mount requirements.

| New bulk data | Location with `data_dir` set | Default setting |
| --- | --- | --- |
| Docker images, containers and volumes | `<data_dir>/docker` | `data-root` in `/etc/docker/daemon.json` (`docker` profile) |
| Treehouse pools | `<data_dir>/.treehouse` | User Treehouse TOML `root` |
| npm, pip, Bun, uv, pnpm packages | `<data_dir>/cache/<tool>` | Native user configuration |
| Go build cache and modules | `<data_dir>/cache/go-build`, `<data_dir>/cache/go-mod` | Native Go environment file |
| Deno cache | `<data_dir>/cache/deno` | `DENO_DIR` |
| Bun transpiler cache | `<data_dir>/cache/bun-transpiler` | `BUN_RUNTIME_TRANSPILER_CACHE_PATH` |
| Temporary files, including new installer Cargo install builds | `<data_dir>/tmp` | `TMPDIR`, `TMP`, `TEMP` |
| Downloads | `<data_dir>/downloads` | XDG `user-dirs.dirs` |
| General syslog | `<data_dir>/host-logs/rsyslog/syslog` | [Bounded general syslog](#bounded-general-syslog) |

Native configuration works without shell initialization.
Apply adds missing keys and preserves existing keys, comments, credentials, modes, and symbolic links.
Updates through symbolic links to the same file accumulate before the write.
An unavailable symbolic-link target blocks writes through that link.
New per-account pool, cache, download, and temporary directories use mode `0700`.
Apply preserves the modes of existing directories.
Existing native paths remain explicit choices, including paths written by an earlier apply.
Change those keys explicitly when changing disks.
Pip cache settings in any supported configuration file prevent a new default.
The spellings `cache_dir`, `cache-dir`, and `--cache-dir` identify the same pip option.
Read-only pip probes skip files that pip cannot open.
The pnpm 10 user rc receives a missing store default.
When pnpm is available, its native configuration command also sets a missing global store default, including pnpm 11 YAML.
Install an absent pnpm and apply again to configure its version-specific store.
pnpm 11 ignores an old `.npmrc` store path; configure that version's native YAML setting instead.
Unsupported TOML table layouts fail without replacing the file.
Alternate configuration roots and explicit configuration files remain operator choices.

The inherited defaults enter `~/.profile`, interactive `~/.bashrc`, and `~/.config/environment.d/60-crewship-bulk.conf`.
An existing, non-empty environment variable wins in a new shell or installer process.
A changed file notifies the existing user-manager reload, which runs before service starts when `start_services` is true.
Apply does not import shell values or restart a service for this file.
Herdr and no-mistakes inherit these defaults from the user manager on their next start.
Herdr reloads its rendered unit before starting an inactive service.
A bulk-only Herdr unit change does not restart the running service.
Explicit service environment settings can override these defaults.
Native package cache settings do not become service environment overrides.
Global `XDG_CACHE_HOME`, `CARGO_HOME`, and `RUSTUP_HOME` do not change.

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

### Compatibility limits

Apply moves or deletes no existing pools, caches, source trees, global installations, credentials, or Downloads files.
Old Treehouse pools remain at their old root.
Use an explicit old root or a worktree path when operating on an old pool.
Native defaults select future pools; they do not update every repository.
Daemon-owned worktrees for unmapped repositories can still use that daemon's existing fallback.
Crewship does not change Firstmate's launcher or the shared daemon.

Treehouse places new pools under `<root>/.treehouse`.
`--root`, `TREEHOUSE_ROOT`, project `treehouse.toml`, and `~/.config/treehouse/config.toml` can select the root.
Treehouse looks up a pool under the same root, so a changed root does not find the pools that exist now.
Change it only for a project whose pool has no live worktree.
See [Cleanup pool roots](fleet-guards.md#cleanup-pool-roots) for the roots that fleet cleanup discovers and its limits.

Bun, pnpm, and uv caches share the configured disk with future default Treehouse pools.
Hardlinks require the same filesystem; explicit pool or cache paths can break that alignment and cause copies.
Previously installed packages and caches remain in place; a new store can start cold.
Command flags, project settings, explicit environment variables, and browser download preferences can override defaults.
Missing tools create no output until installed.
Go uses its native default environment file unless `GOENV` or another configuration root selects a different file.

New Cargo install scratch builds from the installer use the configured temporary directory.
Crewship does not own an arbitrary project's Cargo output policy or an existing Cargo wrapper.
Existing `target/` directories, explicit `CARGO_TARGET_DIR`, and the crew board's explicit build directory remain unchanged.
This change does not provide a general per-project Rust output wrapper.
Running processes keep their inherited paths until a new process receives new settings.
