# Dependencies

Everything the recipe installs, grouped by source.
Each `./ship.sh launch` resolves the newest tool releases once, then installs those releases.
Re-running apply upgrades an existing host.
The installer verifies downloads against publisher checksums and refuses releases without them.
Optional Koncreet failures produce a warning instead.
See [Latest releases](#latest-releases) and [Neovim and LazyVim](#neovim-and-lazyvim) for source builds and Git downloads without publisher checksums.
Neovim downloads its plugins on first start, not during apply.
The installer records resolved releases in `~/.local/share/crewship/resolved.json` for the container smoke checks.
`blueprint/ansible/tasks/verify.yml` also checks that Herdr and omp run the resolved releases.
`./ship.sh chart` installs none of this.

### CA trust and security minimums

`launch` first disables the four Mozilla emSign entries in `/etc/ca-certificates.conf` and rebuilds the system CA store.
It checks the CA bundle and hashed certificate directories before Ansible's first network lookup.
It then refreshes signed APT metadata, upgrades `ca-certificates` to the latest available package, and checks trust again.
The disabled roots are emSign Root CA - C1 and G1, and emSign ECC Root CA - C3 and G3.
An interrupted rebuild is retried when the effective trust store is still unsafe, even if all four configuration entries already match.
The [certifi advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2) states: “Certifi 2026.10.18 removes root certificates from "emSign" from the root store.”
`chart` checks the existing trust store without upgrading packages.
If that check fails, update the system trust store before requesting a release preview.
The earlier bootstrap downloads require an already trusted system CA store.

Node still follows the newest release, with minimum versions of 22.23.4, 24.22.1, and 26.12.1 in their respective major lines.
The installer rejects older or unsupported releases.
It checks extracted executables before promotion and installed executables before linking them onto PATH.
A rejected archive leaves no installed artifact, so a corrected release can be retried.
Newer major lines remain eligible.

The recipe also directs new shell and user-service processes to the filtered system CA store.
It writes `.profile`, `.bashrc`, and `~/.config/environment.d/60-crewship-trust.conf`.
`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, and `PIP_CERT` select `/etc/ssl/certs/ca-certificates.crt`.
`NODE_OPTIONS` appends `--no-use-system-ca --no-use-bundled-ca --use-openssl-ca` to disable conflicting selectors and preserve unrelated Node flags.
Unlike `--use-system-ca`, this option replaces Node's bundled trust instead of adding system trust to it.
`PIP_USE_DEPRECATED=legacy-certs` disables pip's additive truststore backend, so `PIP_CERT` does not retain pip's vendored roots.
The version floors alone do not remove all compromised roots from published runtime bundles.
These settings do not modify installed CA bundles or add unused Python packages.

The default recipe does not add Python's `pip` or `certifi` packages when they are absent.
The repository lock excludes both packages, and uv creates the pruner and tool environments without pip seeds.
Adding unused packages would add another trust store without serving a runtime need.
The repository, pruner, and fdu environments require `pip>=26.2.2` and `certifi>=2026.10.19` when those packages are present.
After creating or updating the repository, pruner, and fdu environments, the recipe uses uv with system certificates to enforce these floors.
The Instagram environment updates are tracked separately in [#833](https://github.com/i098/Crewship/issues/833).
`onboard.sh` handles the repository environment selected by uv, including `UV_PROJECT_ENVIRONMENT`.
When uv is available, `ship.sh` does not run this repository-environment updater.
The updater uses uv, not the environment's pip.
The fdu installer selects the newest available releases even when `UV_RESOLUTION` requests older versions.
`uv pip` is a uv command, not a Python pip installation.
The optional desktop packages bring Ubuntu's `python3-certifi` through `websockify` and `requests`.
Ubuntu patches that certifi to use `/etc/ssl/certs/ca-certificates.crt`, so its trust update comes from `ca-certificates`.
The recipe does not replace distribution Python packages with PyPI packages.

For separately managed Python environments, select filtered system trust as described above before further pip downloads.
Then update any installed certifi and pip packages to the minimum versions above before updating Node.
Environments created outside Crewship remain outside this recipe.
The [certifi advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2), [pip release notes](https://pip.pypa.io/en/stable/news/#v26-2-2), and [Node advisory](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases) describe the fixes.
The sources do not prescribe a combined update order.

## Diagrams

The `agents` profile installs the latest published [Ondine](https://github.com/wevm/ondine) release from the npm registry.
It uses the existing bun installer with versioned prefixes, registry integrity checks, and command links.
No new profile or schema setting is needed.
The public [diagram rule](../blueprint/rules/public/ondine-diagrams.md) makes Ondine the default when `profiles.public_skills` is on.

Run `ondine diagram.mmd` to render compatible Mermaid source as `diagram.svg`, then link the SVG from Markdown.
The documentation uses Ondine's GitHub image blocks with light and dark variants.
Each `<!-- ondine:... -->` marker preserves the original source without data loss, with an added `accTitle` that describes the flow.
The public service at `ondine.sh` renders the source encoded in each image URL.
Do not send private diagrams to this service.
Use `ondine file.md --svg` to write local SVG files instead.

To edit a documentation diagram, run `ondine file.md --restore`, edit the restored fence, then run `ondine file.md`.
Run `ondine file.md --check` to check the result without writing files.

## Schedule viewer

[`tools/schedules/package.json`](../tools/schedules/package.json) declares the OpenTUI dependency.
[`tools/schedules/bun.lock`](../tools/schedules/bun.lock) records the exact versions, including native platform packages.
This is Crewship's own application dependency, so the lockfile stays checked in.
The existing Bun tool runs its native TypeScript API.
Provisioning installs production dependencies with `--frozen-lockfile --ignore-scripts`.
The read-only collector uses Python's standard library.
See [Schedule viewer](configuration.md#schedule-viewer) for its controls and inventory limits.

## Repository tooling

`onboard.sh`, `pyproject.toml`, `uv.lock`

- The latest uv (below), then `uv sync --locked`: ansible-core 2.21.4, jsonschema 4.26.0, PyYAML 6.0.3. `uv.lock` is this repository's own development environment, so it stays locked.
- See [pyproject.toml](../pyproject.toml) for the dev dependency group.

## Latest releases

`scripts/provisions.py`. Native tools are linked into `~/.local/bin`; the npm-registry tools are each installed with `bun add -g` (bun's global directory pointed at `~/.local/share/crewship/<tool>/<version>`, so `~/.bun` stays untouched; bun checks the registry integrity) and linked from there. Superseded versions stay on disk.
For `gh` and `gh-axi`, these links select [managed wrappers](omp.md#github-write-guard) instead of the upstream executables.
The installer resolves at most four independent release sources at once.
Tools from the same GitHub repository share one release lookup per apply.
Each npm metadata request has a 10-second socket timeout.
If `/latest` times out or returns HTTP 5xx, the installer tries the full package document once and reads `dist-tags.latest`.
Both requests use the same timeout, without extra retries or a cache.
Final lookup errors include the URL and attempt count, including incomplete reads, invalid npm JSON, and missing npm metadata fields.
The installer downloads and extracts at most four native assets at once.
Every native installation must pass verification before registry setup starts.
The installer runs at most four independent registry installations at once.
Plugin setup starts only after those installations succeed.
Bun output stays in one labeled block per package, including command failures.

- Always: herdr ([herdrdev/herdr](https://github.com/herdrdev/herdr/releases/latest)), bun ([oven-sh/bun](https://github.com/oven-sh/bun/releases/latest), the x64 `baseline` build), uv ([astral-sh/uv](https://github.com/astral-sh/uv/releases/latest)), btop ([aristocratos/btop](https://github.com/aristocratos/btop/releases/latest), the static musl build, linked as `btop-bin`; `btop` is the launcher in [btop](herdr.md#btop)), sentrux ([sentrux/sentrux](https://github.com/sentrux/sentrux/releases/latest), the binary plus the same release's `grammars-<platform>.tar.gz`, whose grammars are linked into `~/.sentrux/plugins/<language>/grammars/` so sentrux never downloads them itself, unverified, on first run), fallow ([fallow-rs/fallow](https://github.com/fallow-rs/fallow/releases/latest), the static musl binary `fallow-linux-<arch>-musl`, for the [quality gate](omp.md#quality-gate)), verified against the GitHub release-asset digest. A herdr upgrade rewrites and restarts `herdr.service`.
- [sgrep](https://github.com/context-dot-dev/sgrep) provides local search by meaning for code and documents.
  See the [`sgrep` profile](configuration.md#profiles) to enable it.
  Apply builds the latest default branch with `cargo install --git https://github.com/context-dot-dev/sgrep --locked`.
  Cargo verifies crates against the upstream `Cargo.lock`; upstream publishes no checksum for the source build.
  It uses the base ripgrep package and requires the [upstream Rust version](https://github.com/context-dot-dev/sgrep/blob/HEAD/Cargo.toml).
  Apply warms the code and text models; a failed warmup warns without failing the apply.
  Without this profile, apply skips the sgrep build and model downloads.
- Always: Pyrefly ([facebook/pyrefly](https://github.com/facebook/pyrefly/releases/latest)), the static musl build for x86_64 or arm64, verified against the release's `<asset>.sha256` file.
- Always: node, the newest release in the [nodejs.org index](https://nodejs.org/dist/index.json) (not the LTS line), verified against that release's `SHASUMS256.txt`. node and its npm stay for `npx crewship`, which needs npm, and for the chrome-devtools-axi bridge, which runs under node; no tool of the host is installed with npm.
- Always: Neovim ([neovim/neovim](https://github.com/neovim/neovim/releases/latest)), verified against the GitHub release-asset digest.
  The installer keeps the complete `nvim-linux-<arch>` tree and links `~/.local/bin/nvim` to its executable.
- `agents` profile, native: gh ([cli/cli](https://github.com/cli/cli/releases/latest)), treehouse ([kunchenguid/treehouse](https://github.com/kunchenguid/treehouse/releases/latest)), verified against the GitHub release-asset digest.
- `agents` profile, native: gws, the Google Workspace CLI ([googleworkspace/cli](https://github.com/googleworkspace/cli/releases/latest), the static musl build), verified against the `<asset>.sha256` file the release publishes. Signing in Google accounts is manual: see [Google Workspace CLI](google-workspace.md).
- `agents` profile, no-mistakes ([kunchenguid/no-mistakes](https://github.com/kunchenguid/no-mistakes/releases)): the one tool that tracks the prerelease channel. Each apply resolves the newest non-draft release, betas included (not only the latest stable one), and verifies it against the GitHub release-asset digest.
- `agents` profile, bun: omp (`@oh-my-pi/pi-coding-agent`), chrome-devtools-axi, gh-axi, lavish-axi, quota-axi, tasks-axi, forgejo-axi (the no-mistakes Forgejo provider; see [no-mistakes](forgejo.md#no-mistakes)), acpx (runs `omp acp`; see [no-mistakes pipeline agent](omp.md#no-mistakes-pipeline-agent)), and chrome-devtools-mcp (the MCP build chrome-devtools-axi launches through `CHROME_DEVTOOLS_AXI_MCP_PATH`, which points at `~/.local/share/crewship/chrome-devtools-mcp/current`, a link the installer re-points at each release, so a new release never changes the Herdr unit or the `.profile` block and never restarts `herdr.service`). The fleet requires at least quota-axi 0.1.54 and tasks-axi 0.2.6. Shells and user units have `~/.bun/bin` on `PATH`, after `~/.local/bin`, for tools you add yourself with `bun add -g`.
  See [Diagrams](#diagrams) for the Ondine entry.
- `agents` profile, no-mistakes pi adapter check: every apply downloads four pi adapter source files of the no-mistakes release it installs from `raw.githubusercontent.com` (each fetch gives up after 30 seconds) and compares them with the sha256 pins in `blueprint/config/omp-as-pi/check-adapter.sh`. A source that differs from its pin, or is gone from the tag (HTTP 404), switches the gate agent to `acp:omp`; a network error, a timeout or any other HTTP status leaves the agent setting as it is and prints a warning; neither fails the apply (see [no-mistakes pipeline agent](omp.md#no-mistakes-pipeline-agent)).
- Retired: codex and pnpm are no longer installed (bun is the single package manager and runner; omp is the pi agent). An apply on a host that still has them removes the `codex`, `pnpm` and `pnpx` links in `~/.local/bin` that point into the old `~/.local/share/crewship/npm` prefix and changes `defaultAgent` in `~/.acpx/config.json` from `codex` to `omp` when it is still `codex`. The old prefix stays on disk, like every superseded install, so shells and AXI bridges started before the upgrade keep their files; delete it by hand when nothing uses it. Commands of the same name installed any other way are left alone.
- `agents` profile, omp plugins: ponytail ([DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail)), i-have-adhd ([ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd)) and caveman ([JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman)) from their GitHub marketplaces.
  Apply fetches each new marketplace once, refreshes existing marketplaces, and installs missing plugins.
  For the default version-2 plugin registry, apply reads installed IDs directly from `~/.omp/plugins/installed_plugins.json`.
  It uses `omp plugin list --json` for custom paths, profiles, supported dotenv files, and missing, unreadable, or unsupported registries.
  The dotenv check covers the target home's `.env`, `.env.local`, mode-specific files, `.omp/.env`, and `.omp/agent/.env`.
  If no marketplace plugins were installed before apply, it skips `omp plugin upgrade`.
  Otherwise, it runs that command after installation.
  These plugins have no publisher checksums and track each author's default branch.
  They load as agent instructions and hooks.
- `chat` profile: concord ([chojs23/concord](https://github.com/chojs23/concord/releases/latest), `concord-<arch>-unknown-linux-gnu.tar.xz`) and slk ([gammons/slk](https://github.com/gammons/slk/releases/latest), `slk_<version>_linux_<arch>.tar.gz`), verified against the GitHub release-asset digest. See [Chat clients](chat.md).
- `sgrep` or `development` profile: rustup-init, the version in rustup's [stable release](https://static.rust-lang.org/rustup/release-stable.toml), verified against the published `.sha256`.
  It installs the Rust `stable` toolchain with rustfmt and clippy.
  Each selected apply updates the toolchain to the newest stable release.
- `jj` profile: jj ([jj-vcs/jj](https://github.com/jj-vcs/jj/releases/latest), the static musl build), verified against the GitHub release-asset digest. See [Jujutsu](jj.md).
- `gateway` profile: cloudflared ([cloudflare/cloudflared](https://github.com/cloudflare/cloudflared/releases/latest), `cloudflared-linux-<arch>`), verified against the GitHub release-asset digest. See [Web pages from anywhere](gateway.md).

The GitHub API allows 60 unauthenticated requests per hour per IP.
Shared IPs, such as CI runners, can reach this limit.
When the API answers HTTP 403 or 429, the lookup prints a message and reads the same release from github.com's public pages instead.
Those pages have no request budget: the `releases/latest` redirect gives the tag (the release Atom feed, for no-mistakes), and the release's asset list shows each asset's SHA-256 digest.
If the prerelease API list is empty or contains only drafts, the lookup also uses the Atom feed and public asset pages.
Only the tools a run installs are resolved, so an unused source cannot fail the run.
The lookups use `GITHUB_TOKEN` from the environment that runs `./ship.sh launch` or `./onboard.sh`, if set.
The token goes to the GitHub API only.
Container builds take the token as the optional BuildKit secret `github_token` (`docker build --secret id=github_token,env=GITHUB_TOKEN ...`).
The token never enters the image.

## Neovim and LazyVim

Every host gets Neovim.
Apply copies the vendored [LazyVim starter](https://github.com/LazyVim/starter) from `blueprint/config/nvim/` when `~/.config/nvim` is missing or an empty real directory.
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

`blueprint/ansible/group_vars/all/packages.yml`, `blueprint/ansible/tasks/packages.yml`. Distribution versions, not pinned.

- Base: ca-certificates, curl, git, gcc, libc6-dev, gnupg, jq, tar, unzip, xz-utils, zstd, procps, acl, python3, python3-venv, openssl, rsync, ripgrep, libgtk-3-0t64 (the sentrux binary links GTK 3 even for its CLI), mosh (`mosh-server` for `mosh <host>`).
  gcc and libc6-dev let LazyVim compile Treesitter parsers even when the `development` profile is disabled.
- Headless browser libraries, every apply, without recommends: libxcomposite1, libxdamage1, libxfixes3, libxrandr2, libasound2t64, libatk1.0-0t64, libatk-bridge2.0-0t64, libatspi2.0-0t64, libgbm1, libnss3, libnspr4, libxkbcommon0, fonts-dejavu-core. The chrome-headless-shell that omp's browser tool and puppeteer download needs the libraries to start and a font to draw text.
- `chat`, without recommends: libegl1, libpipewire-0.3-0t64, libva2, libva-drm2 (the Concord binary links them).
- `development`: build-essential, pkg-config, libssl-dev, python3-dev, cmake.
- `docker`: docker.io, docker-compose-v2 (Ubuntu's packages, never Docker CE).
- `desktop`: xfce4, xfce4-terminal, dbus-x11, xauth, x11-xserver-utils, fonts-dejavu-core, tigervnc-standalone-server, tigervnc-common, tigervnc-tools, novnc, websockify, iproute2.
- `tailscale`: `tailscale` from pkgs.tailscale.com, stable track. `crewship_tailscale_version` pins it; empty by default.
- Google Chrome: `google-chrome-stable` from dl.google.com (`blueprint/ansible/tasks/browser.yml`). Installed when `crewship_chrome_install` is `true`, or `auto` (the default) with the `desktop` profile. `crewship_chrome_version` pins it; empty by default.

## Optional fleet browsers

- `fleet_browsers` or `fleet_guards` profile: Obscura, the latest [h4ckf0r0day/obscura release](https://github.com/h4ckf0r0day/obscura/releases/latest) for the host's platform, verified against the GitHub release-asset digest (`blueprint/ansible/tasks/fleet-browsers.yml`). Each release extracts into its own `~/oss-fleet/browsers/obscura-<version>/`. The `vnc` tier's Ubuntu packages: tigervnc-standalone-server, websockify, novnc, xfwm4.

## Optional project databases

The database profile uses the official database image of each project and the Docker Compose plugin.
See [Project databases](project-databases.md) for setup, backups and removal.

## Koncreet

See the [`koncreet` profile](configuration.md#profiles) for selection and existing-host defaults; installation also requires `start_services: true`.

- [Koncreet](https://github.com/jimididit/koncreet), the latest release's `koncreet.tar.gz`, verified against the GitHub release-asset digest (`blueprint/ansible/tasks/koncreet.yml`). It installs as root into `/usr/local/lib/crewship/koncreet/<version>-<patch hash>/` with `/usr/local/bin/koncreet` linked to it, and `blueprint/patches/koncreet/ubuntu-26.04.patch` is layered on top. It is optional: when its lookup, checksum, or download fails, apply warns and skips it. Apply never runs it; [Host hardening](security.md#host-hardening) has the manual run.

## Forgejo

`profiles.forgejo` (opt-in, [Self-hosted Forgejo](forgejo.md)).

- [Forgejo](https://codeberg.org/forgejo/forgejo/releases), the newest non-draft, non-prerelease release on Codeberg, `forgejo-<version>-linux-<arch>`. The binary is verified against the `.sha256` file that the release publishes, and its `.asc` signature must come from the Forgejo release key (`crewship_forgejo_key_fingerprint`), fetched from keys.openpgp.org (`blueprint/ansible/tasks/forgejo.yml`). Each release installs into `~/.local/share/crewship/forgejo/<version>/`.

## Chrome autopruner

`agents` profile with `browser_prune.enabled`.

- psutil, the latest PyPI release, installed into a private venv with `uv pip install --require-hashes` against the SHA-256 digests PyPI publishes for that release (`blueprint/ansible/tasks/browser_prune.yml`).

## iMessage bridge

`crewship.imessage` set ([iMessage bridge](imessage.md)).

- spectrum-ts, the npm registry's latest release, installed with `bun add --exact` into `~/.local/share/crewship/imessage` (`blueprint/ansible/tasks/imessage.yml`). bun is a core tool.

## Crew board

`crewship.board` set ([Crew board](board.md)).

- crewboard, built from `apps/crewboard/` in this repository with `cargo build --release --locked` by the Rust toolchain of the `development` profile (`blueprint/ansible/tasks/board.yml`). Its crates are the versions in `apps/crewboard/Cargo.lock`, verified by cargo against the checksums in that file.

## Firstmate

`firstmate` profile.

- `git clone` of `crewship.firstmate.url` (upstream `https://github.com/kunchenguid/firstmate.git` by default), tracking `origin/main`, never pinned. Every apply fetches `origin/main` and puts `main` at that revision plus the patch layer below (`blueprint/ansible/tasks/firstmate.yml`).

### Firstmate patch layer

`blueprint/patches/firstmate/` holds fixes that upstream Firstmate does not have yet. Apply builds one local commit per patch on top of `origin/main`, in file-name order. Each commit takes its author, date, and message from the patch file, plus a `Crewship-Patch: <file name>` trailer, so an unchanged host gets the same commits again and the apply changes nothing.

| Patch | What it does |
| --- | --- |
| `0001-watch-wake-on-queued-inbox-note.patch` | The watcher wakes Firstmate on its next cycle when an inbox note is queued. Without it, the note waits for an unrelated wake, which can take hours. |
| `0002-watch-end-idle-wait-for-inbox-note.patch` | The watcher ends its idle wait within about 1 s when an inbox note arrives. See [iMessage routing](imessage.md#what-it-does) for when the bridge creates a note. |
| `0003-brief-crewboard.patch` | Adds the optional [Firstmate board instructions](board.md#firstmate-instructions). |
| `0004-watch-crewboard-event-source.patch` | Needs 0001 and 0002. With the board on, a message on the board's `fm` topic wakes Firstmate within about 1 s, and an optional doorbell rings a task's pane for a `task/<id>` message ([Wake Firstmate from the board](board.md#wake-firstmate-from-the-board)). `jq` is a runtime need; the host packages already install it. |
| `0005-herdr-pane-life.patch` | A Herdr pane closes when its agent exits cleanly, and a pane closed on purpose is never relaunched: not by secondmate liveness, not by the stale wake. A crash leaves the pane as a `dead` husk, and that is still recovered. Pairs with `[session] resume_agents_on_restore = false` in [Herdr](herdr.md). |

How apply handles each case:

- Upstream moved: apply builds the layer again on the new `origin/main`. It applies each patch three-way, so upstream edits near a patch do not break it.
- Upstream already has a patch's change: apply prints `skipped, upstream already has it: <file>` and makes no commit for it.
- A patch no longer applies: the play stops and names the patch and the upstream commit. The checkout stays as it was. Update the patch for the new upstream code, or drop it.
- Local commits: every commit on `main` that is not upstream must carry the `Crewship-Patch` trailer. Apply replaces all of them with the rebuilt layer, so an edited, added, or dropped patch needs no manual step. Apply refuses any commit without the trailer, and a dirty tree or another branch, and never resets, stashes, or cleans.

Verification requires `main` to be exactly `origin/main` plus the patch layer.

To update a patch, edit its file in a pull request. To drop a patch, delete its file, once upstream has it or when it is no longer needed. On the next apply, each host rebuilds the layer from the files.

## Container images

`Dockerfile`, `compose.yml`

- Worker base `ubuntu:latest` (the newest Ubuntu LTS), pulled from `mirror.gcr.io/library/ubuntu:latest`, Google's Docker Hub mirror with no anonymous pull limit, plus apt: bash, build-essential, ca-certificates, curl, git, iproute2, jq, less, libssl-dev, openssh-client, pkg-config, procps, python3, python3-apt, python3-venv, sudo, tar, unzip, xz-utils, zstd.
- The worker image is provisioned in a `builder` stage and copied into one layer. It omits files no worker process reads, so it differs from a host: no apt indexes, package-manager caches, rustup docs or node C headers; no source maps, and no TypeScript declarations outside omp's own packages, in the npm tool prefixes; in omp, no `onnxruntime-web`, no AVX2 build of `pi-natives` (omp loads the baseline build), and only the CPU `onnxruntime-node` binaries for the image's platform; and no Mesa GPU driver or its LLVM (`libgallium`, `libLLVM`), which libgbm loads only to open a GPU device. `sudo apt-get install --reinstall mesa-libgallium libllvm21` restores them. The rustup toolchain and the npm tools' native addons are stripped of symbol tables; the release binaries the installer verifies keep their published bytes.
- Optional compose backing services, never installed by apply: `postgres:18-bookworm`, `redis:8-alpine`, from the same mirror, digest-pinned because a floating Postgres tag would move a data volume across major versions it cannot read.
- CI pool job containers (only with `crewship.ci_pool`): see [CI pool](ci-pool.md#what-a-job-gets) for the image and update policy.
  The official runner base image comes from GitHub and is not checksum-verified here.
- macOS runner (`blueprint/maintenance/mac-runner.sh`, run by hand on a Mac): the latest official `actions-runner-osx-arm64` release of [actions/runner](https://github.com/actions/runner), checked against the SHA-256 digest that GitHub lists for the release asset; see [macOS runner](ci-pool.md#macos-runner).
- Project databases (`profiles.project_databases` only): the image each project's compose file names (Postgres, MySQL, MariaDB or Redis), pulled once when the container is first created. No other image is pulled.
  A new major version needs a manual database upgrade; see [Project databases](project-databases.md#data-and-upgrades).

## Assumed on the host

The recipe never installs these. The base requirements (Ubuntu, sudo, Python, `git`, `gh`) are in the [Working on Crewship itself](../CONTRIBUTING.md#working-on-crewship-itself). Notes on those:

- `onboard.sh` refuses to run without Python 3.12+.
- The recipe installs the latest gh later, under `agents`; the Quick start needs an authenticated `gh` before that.

Also needed, depending on profile:

- Membership in the `docker` group for the account that runs fleet guards. Opt in with `crewship_docker_group_users`.
- `psmisc` (`fuser`) for `fleet-browser seed`.
- `iproute2` (`ss`) for the CLIENTS column of `fleet-browser status`. Without `ss`, every tier reports 0 clients and gc can stop a tier in use. Only the `desktop` profile installs `iproute2`, so a `fleet_browsers` or `fleet_guards` host without `desktop` needs it in the base image.
- A VNC password created by the operator, for the `desktop` profile.
