# Dependencies

Everything the recipe installs, grouped by source.
Each `./ship.sh launch` resolves the newest tool releases once, then installs those releases.
Re-running apply upgrades an existing host.
The installer verifies downloads against publisher checksums and refuses releases without them.
Optional Koncreet failures produce a warning instead.
The omp marketplace plugins and Neovim plugins use upstream Git repositories without publisher checksums.
Neovim downloads its plugins on first start, not during apply.
The installer records resolved releases in `~/.local/share/crewship/resolved.json` for the container smoke checks.
`ansible/tasks/verify.yml` also checks that Herdr and omp run the resolved releases.
`./ship.sh chart` installs none of this.

## Repository tooling

`onboard.sh`, `pyproject.toml`, `uv.lock`

- The latest uv (below), then `uv sync --locked`: ansible-core 2.21.4, jsonschema 4.26.0, PyYAML 6.0.3. `uv.lock` is this repository's own development environment, so it stays locked.
- See [pyproject.toml](../pyproject.toml) for the dev dependency group.

## Latest releases

`scripts/provisions.py`. Native tools are linked into `~/.local/bin`; npm tools are each installed with `npm install` into `~/.local/share/crewship/<tool>/<version>` (npm checks the registry integrity) and linked from there. Superseded versions stay on disk.

- Always: herdr ([herdrdev/herdr](https://github.com/herdrdev/herdr/releases/latest)), bun ([oven-sh/bun](https://github.com/oven-sh/bun/releases/latest), the x64 `baseline` build), uv ([astral-sh/uv](https://github.com/astral-sh/uv/releases/latest)), btop ([aristocratos/btop](https://github.com/aristocratos/btop/releases/latest), the static musl build, linked as `btop-bin`; `btop` is the launcher in [btop](herdr.md#btop)), sentrux ([sentrux/sentrux](https://github.com/sentrux/sentrux/releases/latest), the binary plus the same release's `grammars-<platform>.tar.gz`, whose grammars are linked into `~/.sentrux/plugins/<language>/grammars/` so sentrux never downloads them itself, unverified, on first run), fallow ([fallow-rs/fallow](https://github.com/fallow-rs/fallow/releases/latest), the static musl binary `fallow-linux-<arch>-musl`, for the [quality gate](omp.md#quality-gate)), verified against the GitHub release-asset digest. A herdr upgrade rewrites and restarts `herdr.service`.
- Always: Pyrefly ([facebook/pyrefly](https://github.com/facebook/pyrefly/releases/latest)), the static musl build for x86_64 or arm64, verified against the release's `<asset>.sha256` file.
- Always: node, the newest release in the [nodejs.org index](https://nodejs.org/dist/index.json) (not the LTS line), verified against that release's `SHASUMS256.txt`.
- Always: Neovim ([neovim/neovim](https://github.com/neovim/neovim/releases/latest)), verified against the GitHub release-asset digest.
  The installer keeps the complete `nvim-linux-<arch>` tree and links `~/.local/bin/nvim` to its executable.
- `agents` profile, native: gh ([cli/cli](https://github.com/cli/cli/releases/latest)), treehouse ([kunchenguid/treehouse](https://github.com/kunchenguid/treehouse/releases/latest)), verified against the GitHub release-asset digest.
- `agents` profile, native: gws, the Google Workspace CLI ([googleworkspace/cli](https://github.com/googleworkspace/cli/releases/latest), the static musl build), verified against the `<asset>.sha256` file the release publishes. Signing in Google accounts is manual: see [Google Workspace CLI](google-workspace.md).
- `agents` profile, no-mistakes ([kunchenguid/no-mistakes](https://github.com/kunchenguid/no-mistakes/releases)): the one tool that tracks the prerelease channel. Each apply resolves the newest non-draft release, betas included (not only the latest stable one), and verifies it against the GitHub release-asset digest.
- `agents` profile, npm: omp (`@oh-my-pi/pi-coding-agent`), chrome-devtools-axi, gh-axi, lavish-axi, quota-axi, tasks-axi, acpx (runs `omp acp`; see [no-mistakes pipeline agent](omp.md#no-mistakes-pipeline-agent)), and chrome-devtools-mcp (the MCP build chrome-devtools-axi launches through `CHROME_DEVTOOLS_AXI_MCP_PATH`, which points at `~/.local/share/crewship/chrome-devtools-mcp/current`, a link the installer re-points at each release, so a new release never changes the Herdr unit or the `.profile` block and never restarts `herdr.service`). The fleet requires at least quota-axi 0.1.54 and tasks-axi 0.2.6.
- `agents` profile, no-mistakes pi adapter check: every apply downloads four pi adapter source files of the no-mistakes release it installs from `raw.githubusercontent.com` (each fetch gives up after 30 seconds) and compares them with the sha256 pins in `config/omp-as-pi/check-adapter.sh`. A source that differs from its pin, or is gone from the tag (HTTP 404), switches the gate agent to `acp:omp`; a network error, a timeout or any other HTTP status leaves the agent setting as it is and prints a warning; neither fails the apply (see [no-mistakes pipeline agent](omp.md#no-mistakes-pipeline-agent)).
- Retired: codex and pnpm are no longer installed (bun is the single package manager and runner; omp is the pi agent). An apply on a host that still has them removes the `codex`, `pnpm` and `pnpx` links in `~/.local/bin` that point into the old `~/.local/share/crewship/npm` prefix and changes `defaultAgent` in `~/.acpx/config.json` from `codex` to `omp` when it is still `codex`. The old prefix stays on disk, like every superseded install, so shells and AXI bridges started before the upgrade keep their files; delete it by hand when nothing uses it. Commands of the same name installed any other way are left alone.
- `agents` profile, omp plugins: ponytail ([DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail)), i-have-adhd ([ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd)) and caveman ([JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman)) from their GitHub marketplaces.
  Apply installs them once and runs `omp plugin upgrade` on later applies.
  These plugins have no publisher checksums and track each author's default branch.
  They load as agent instructions and hooks.
- `chat` profile: concord ([chojs23/concord](https://github.com/chojs23/concord/releases/latest), `concord-<arch>-unknown-linux-gnu.tar.xz`) and slk ([gammons/slk](https://github.com/gammons/slk/releases/latest), `slk_<version>_linux_<arch>.tar.gz`), verified against the GitHub release-asset digest. See [Chat clients](chat.md).
- `development` profile: rustup-init, the version in rustup's [stable release](https://static.rust-lang.org/rustup/release-stable.toml), verified against the `.sha256` published beside it, installing the Rust `stable` toolchain (minimal profile + rustfmt + clippy). Every apply moves the toolchain to the newest stable.

The GitHub API allows 60 unauthenticated requests per hour per IP.
Shared IPs, such as CI runners, can reach this limit.
A resolution makes one request per GitHub repository, at most sixteen.
Only the tools a run installs are resolved, so an unused source cannot fail the run.
The lookups use `GITHUB_TOKEN` from the environment that runs `./ship.sh launch` or `./onboard.sh`, if set.
The token goes to the GitHub API only.
Container builds take the token as the optional BuildKit secret `github_token` (`docker build --secret id=github_token,env=GITHUB_TOKEN ...`).
The token never enters the image.

## Neovim and LazyVim

Every host gets Neovim.
Apply copies the vendored [LazyVim starter](https://github.com/LazyVim/starter) from `config/nvim/` when `~/.config/nvim` is missing or an empty real directory.
Apply leaves nonempty directories, files, and symlinks unchanged, including dangling symlinks.
Apply also leaves directories unchanged when it cannot complete the directory scan.
It never merges files or installs plugins during apply.

Run `nvim` to start the editor.
The first start needs network access: the starter downloads lazy.nvim, LazyVim, and their plugins.
Plugin downloads use the upstream Git repositories, not the Crewship checksum installer.
LazyVim manages later plugin updates.
The added `lua/plugins/pyrefly.lua` uses the Pyrefly executable from PATH with `mason = false`, so Mason does not install another copy.
See the Pyrefly entry under [Latest releases](#latest-releases) for its installation.
Use a Python project with `pyrefly.toml` to select its project root.

The runtime starter files and Apache-2.0 license come from commit `803bc181d7c0d6d5eeba9274d9be49b287294d99`.
The unused example plugin and upstream development files are not included.
The Pyrefly configuration is the only added runtime file.

## Ubuntu packages

`ansible/group_vars/all.yml`, `ansible/tasks/packages.yml`. Distribution versions, not pinned.

- Base: ca-certificates, curl, git, gcc, libc6-dev, gnupg, jq, tar, unzip, xz-utils, zstd, procps, acl, python3, python3-venv, openssl, rsync, libgtk-3-0t64 (the sentrux binary links GTK 3 even for its CLI), mosh (`mosh-server` for `mosh <host>`).
  gcc and libc6-dev let LazyVim compile Treesitter parsers even when the `development` profile is disabled.
- Headless browser libraries, every apply, without recommends: libxcomposite1, libxdamage1, libxfixes3, libxrandr2, libasound2t64, libatk1.0-0t64, libatk-bridge2.0-0t64, libatspi2.0-0t64, libgbm1, libnss3, libnspr4, libxkbcommon0, fonts-dejavu-core. The chrome-headless-shell that omp's browser tool and puppeteer download needs the libraries to start and a font to draw text.
- `chat`, without recommends: libegl1, libpipewire-0.3-0t64, libva2, libva-drm2 (the Concord binary links them).
- `development`: build-essential, pkg-config, libssl-dev, python3-dev, cmake, ripgrep.
- `docker`: docker.io, docker-compose-v2 (Ubuntu's packages, never Docker CE).
- `desktop`: xfce4, xfce4-terminal, dbus-x11, xauth, x11-xserver-utils, fonts-dejavu-core, tigervnc-standalone-server, tigervnc-common, tigervnc-tools, novnc, websockify, iproute2.
- `tailscale`: `tailscale` from pkgs.tailscale.com, stable track. `crewship_tailscale_version` pins it; empty by default.
- Google Chrome: `google-chrome-stable` from dl.google.com (`ansible/tasks/browser.yml`). Installed when `crewship_chrome_install` is `true`, or `auto` (the default) with the `desktop` profile. `crewship_chrome_version` pins it; empty by default.

## Optional fleet browsers

- `fleet_browsers` or `fleet_guards` profile: Obscura, the latest [h4ckf0r0day/obscura release](https://github.com/h4ckf0r0day/obscura/releases/latest) for the host's platform, verified against the GitHub release-asset digest (`ansible/tasks/fleet-browsers.yml`). Each release extracts into its own `~/oss-fleet/browsers/obscura-<version>/`. The `vnc` tier's Ubuntu packages: tigervnc-standalone-server, websockify, novnc, xfwm4.

## Optional shared Postgres

The database profile uses the official Postgres container and the Docker Compose plugin.
See [Shared Postgres](shared-postgres.md) for setup, backups and removal.

## Koncreet

Every host that starts services (`start_services: true`); the container worker image skips it.

- [Koncreet](https://github.com/jimididit/koncreet), the latest release's `koncreet.tar.gz`, verified against the GitHub release-asset digest (`ansible/tasks/koncreet.yml`). It installs as root into `/usr/local/lib/crewship/koncreet/<version>-<patch hash>/` with `/usr/local/bin/koncreet` linked to it, and `patches/koncreet/ubuntu-26.04.patch` is layered on top. It is optional: when its lookup, checksum, or download fails, apply warns and skips it. Apply never runs it; [Host hardening](security.md#host-hardening) has the manual run.

## Chrome autopruner

`agents` profile with `browser_prune.enabled`.

- psutil, the latest PyPI release, installed into a private venv with `uv pip install --require-hashes` against the SHA-256 digests PyPI publishes for that release (`ansible/tasks/browser_prune.yml`).

## iMessage bridge

`crewship.imessage` set ([iMessage bridge](imessage.md)).

- spectrum-ts, the npm registry's latest release, installed with `bun add --exact` into `~/.local/share/crewship/imessage` (`ansible/tasks/imessage.yml`). bun is a core tool.

## Crew board

`crewship.board` set ([Crew board](board.md)).

- crewboard, built from `crewboard/` in this repository with `cargo build --release --locked` by the Rust toolchain of the `development` profile (`ansible/tasks/board.yml`). Its crates are the versions in `crewboard/Cargo.lock`, verified by cargo against the checksums in that file.

## Firstmate

`firstmate` profile.

- `git clone` of `crewship.firstmate.url` (upstream `https://github.com/kunchenguid/firstmate.git` by default), tracking `origin/main`, never pinned. Every apply fetches `origin/main` and puts `main` at that revision plus the patch layer below (`ansible/tasks/firstmate.yml`).

### Firstmate patch layer

`patches/firstmate/` holds fixes that upstream Firstmate does not have yet. Apply builds one local commit per patch on top of `origin/main`, in file-name order. Each commit takes its author, date, and message from the patch file, plus a `Crewship-Patch: <file name>` trailer, so an unchanged host gets the same commits again and the apply changes nothing.

| Patch | What it does |
| --- | --- |
| `0001-watch-wake-on-queued-inbox-note.patch` | The watcher wakes Firstmate on its next cycle when an inbox note is queued. Without it, the note waits for an unrelated wake, which can take hours. |
| `0002-watch-end-idle-wait-for-inbox-note.patch` | The watcher ends its idle wait within about 1 s when an inbox note arrives, instead of up to the full poll interval. Together, the two make a text from the iMessage bridge wake Firstmate in about 2 s. |
| `0003-brief-crewboard.patch` | Adds the optional [Firstmate board instructions](board.md#firstmate-instructions). |

How apply handles each case:

- Upstream moved: apply builds the layer again on the new `origin/main`. It applies each patch three-way, so upstream edits near a patch do not break it.
- Upstream already has a patch's change: apply prints `skipped, upstream already has it: <file>` and makes no commit for it.
- A patch no longer applies: the play stops and names the patch. The checkout stays as it was. Update the patch for the new upstream code, or drop it.
- Local commits: every commit on `main` that is not upstream must carry the `Crewship-Patch` trailer. Apply replaces all of them with the rebuilt layer, so an edited, added, or dropped patch needs no manual step. Apply refuses any commit without the trailer, and a dirty tree or another branch, and never resets, stashes, or cleans.

Verification requires `main` to be exactly `origin/main` plus the patch layer.

To update a patch, edit its file in a pull request. To drop a patch, delete its file, once upstream has it or when it is no longer needed. On the next apply, each host rebuilds the layer from the files.

## Container images

`Dockerfile`, `compose.yml`

- Worker base `ubuntu:latest` (the newest Ubuntu LTS), pulled from `mirror.gcr.io/library/ubuntu:latest`, Google's Docker Hub mirror with no anonymous pull limit, plus apt: bash, build-essential, ca-certificates, curl, git, iproute2, jq, less, libssl-dev, openssh-client, pkg-config, procps, python3, python3-apt, python3-venv, sudo, tar, unzip, xz-utils, zstd.
- Optional compose backing services, never installed by apply: `postgres:18-bookworm`, `redis:8-alpine`, from the same mirror, digest-pinned because a floating Postgres tag would move a data volume across major versions it cannot read.
- CI pool job containers (`maintenance/ci-pool.py`, only with `crewship.ci_pool`): the official `ghcr.io/actions/actions-runner:latest`, pulled again when a new image is available. It is the runner GitHub publishes, so it is not checksum-verified here; see [CI pool](ci-pool.md).
- Shared Postgres (`profiles.shared_postgres` only): the official `postgres:latest`, pulled once per apply with Compose, like the CI pool's latest-image pattern.
  A new major version needs a manual database upgrade; see [Shared Postgres](shared-postgres.md#data-and-upgrades).

## Assumed on the host

The recipe never installs these. The base requirements (Ubuntu, sudo, Python, `git`, `gh`) are in the [Quick start](../README.md#quick-start). Notes on those:

- `onboard.sh` refuses to run without Python 3.12+.
- The recipe installs the latest gh later, under `agents`; the Quick start needs an authenticated `gh` before that.

Also needed, depending on profile:

- Membership in the `docker` group for the account that runs fleet guards. Opt in with `crewship_docker_group_users`.
- `psmisc` (`fuser`) for `fleet-browser seed`.
- `iproute2` (`ss`) for the CLIENTS column of `fleet-browser status`. Without `ss`, every tier reports 0 clients and gc can stop a tier in use. Only the `desktop` profile installs `iproute2`, so a `fleet_browsers` or `fleet_guards` host without `desktop` needs it in the base image.
- A VNC password created by the operator, for the `desktop` profile.
