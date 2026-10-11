# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.1] - 2026-10-11

### Added

- The iMessage bridge can use self-hosted BlueBubbles relays on Macs, alone or as the fallback line when Photon fails, with relay failover, no double sends, and de-duplicated inbound messages ([#62](https://github.com/i098/Crewship/issues/62)).
- Firstmate briefs add optional crew board instructions, and supervisor start output adds a read-only subscription step while the status file remains the durable ledger ([#120](https://github.com/i098/Crewship/issues/120)).
- The harbor plaza has a stone fountain with flowing water, a solid basin, and a mini map marker ([#134](https://github.com/i098/Crewship/issues/134)).
- Visitors can enter the harbor house, explore a warmly lit ASCII room, and walk back outside with keyboard or touch controls.
  See the [house guidance](https://github.com/i098/Crewship/tree/main/harbor#harbor) for controls and the [frame loop](https://crewship.si/how.html#frame-loop) for adaptive detail ([#153](https://github.com/i098/Crewship/issues/153)).
- `fm-imessage --reply N` checks ordered history across BlueBubbles relays; plain sends never thread, and `--no-thread` forces plain ([#156](https://github.com/i098/Crewship/issues/156)).
- The harbor hides the initial page text and adds a skippable ASCII noise intro that fades in from black and respects reduced motion ([#158](https://github.com/i098/Crewship/issues/158)).
- Add opt-in shared Postgres with Docker access checks, TCP readiness, per-project databases and roles, and private environment files for serialized worktree seeding ([#164](https://github.com/i098/Crewship/issues/164)).
- The harbor ship's cabin is detailed and opens onto a furnished room, and its deck stairs have real treads, risers, and hand rails ([#194](https://github.com/i098/Crewship/issues/194)).
- Visitors can climb down a lantern-lit hatch on the pirate ship to a gun deck with a cannon on a wheeled carriage at every gun port, racks of round shot, dark cross-beams, and the moonlit sea outside the ports, and climb back up with keyboard or touch controls ([#196](https://github.com/i098/Crewship/issues/196)).
- The crewship.si night sky has three layers of moonlit clouds that move with the wind and pass in front of the moon and the stars ([#198](https://github.com/i098/Crewship/issues/198)).
- Links to https://crewship.si show a link preview: the title, the tagline, and a 1200x630 image of the ship, the house, and the moon drawn by the landing page's own renderer, with a new favicon and an apple-touch-icon ([#200](https://github.com/i098/Crewship/issues/200)).
- The harbor island has tufts of tall grass that sway in the wind, densest along path edges and on the beach slopes, and still with reduced motion ([#204](https://github.com/i098/Crewship/issues/204)).
- The harbor house shows four framed public-domain paintings by Hokusai, Vernet, Aivazovsky, and Turner, drawn as glyphs with brass name plaques ([#226](https://github.com/i098/Crewship/issues/226)).
- Crewship installs checksum-verified Pyrefly musl releases on every host for Python type checks and language-server support ([#231](https://github.com/i098/Crewship/issues/231)).
- Every host gets verified Neovim, compiler prerequisites, and a LazyVim/Pyrefly starter for missing or empty configuration directories, while other paths remain unchanged ([#232](https://github.com/i098/Crewship/issues/232)).
- A public skill, `code-clarity` (MIT, by Lakr233), for readable code: naming, early return, abstraction levels and class design. Vendored unchanged from [Lakr233/code-clarity](https://github.com/Lakr233/code-clarity) at commit `a0d5802` ([#233](https://github.com/i098/Crewship/issues/233)).
- A public skill, `pr-preview`, that builds a Lavish board recreating the GitHub PR, issue or comment page before it is posted: the header with "wants to merge N commits into base from fork:branch", the body rendered by GitHub's Markdown API with the Primer Markdown CSS (vendored from `github-markdown-css`, MIT), and Commits and Files changed tabs from the real branch ([#236](https://github.com/i098/Crewship/issues/236)).
- Add an optional `--rules` contribution rules cross-reference table to the `pr-preview` skill ([#247](https://github.com/i098/Crewship/issues/247)).

### Changed

- **Breaking:** renamed the config keys and variables to Crewship names, with no aliases. `ship.sh` rewrites an old host config once, keeps a private backup beside it, and prints a notice. Update these names by hand: Compose, devcontainer, and image `FACTORY_USER`, `FACTORY_UID`, `FACTORY_GID`, `FACTORY_HOME`, `FACTORY_WORKSPACE`, `CODE_FACTORY_TAG`, `CODE_FACTORY_SECRET_DIR`, `CODE_FACTORY_ROOT`, `CODE_FACTORY_CONFIG`, `CODE_FACTORY_IMAGE` are now `CREWSHIP_USER`, `CREWSHIP_UID`, `CREWSHIP_GID`, `CREWSHIP_HOME`, `CREWSHIP_WORKSPACE`, `CREWSHIP_TAG`, `CREWSHIP_SECRET_DIR`, `CREWSHIP_ROOT`, `CREWSHIP_CONFIG`, `CREWSHIP_IMAGE`; the Docker build argument `FACTORY_CONFIG` is now `CREWSHIP_CONFIG_FILE`; direct `ansible-playbook -e factory_*` overrides are now `crewship_*`, and `code_factory_repo` is now `crewship_repo` ([#97](https://github.com/i098/Crewship/issues/97)).
- **Breaking:** renamed the on-host paths and unit names from `code-factory` to `crewship`, with no aliases: for example `~/.local/share/crewship`, `~/.cache/crewship`, `~/.local/state/crewship`, `/usr/local/lib/crewship`, `crewship-vnc.service`, `crewship-novnc.service`, the omp extensions `crewship-herdr-sidebar.ts` and `crewship-quality-gate.ts`, the Compose project and image `crewship/worker`, `/opt/crewship` in the image, and the Firstmate patch trailer `Crewship-Patch`. The playbook migrates an existing install once: it stops and removes the old units, moves the old paths to the new names, and then installs and enables the new units; a second apply changes nothing. Compose and devcontainer volumes get new names; copy their data by hand ([#98](https://github.com/i098/Crewship/issues/98)).
- The CI runner label is now `crewship` ([#99](https://github.com/i098/Crewship/issues/99)).
- Crewship adds tiered crewmate models, verified Pi-only gate selection, and Codex long-context overrides that preserve user configuration across YAML and legacy JSONC formats ([#110](https://github.com/i098/Crewship/issues/110)).
- The harbor house now has roof and wall trim, framed warm windows with sills, and a framed door with a step.
  The house trim preserves Releases targeting, the feature anchor, collision bounds, and map cells ([#135](https://github.com/i098/Crewship/issues/135)).
- The harbor island has varied paving, stones and grass tufts, textured trees, and a clearer shoreline with foam and rocks ([#136](https://github.com/i098/Crewship/issues/136)).
- Document the release version policy: patch bumps only, with minor or major bumps requiring owner approval ([#137](https://github.com/i098/Crewship/issues/137)).
- Crewmates use per-task model tiers with Sonnet 5.5 or GPT-6.1 Sol as the default, and the README checks these tiers against `config/crew-dispatch.json` ([#138](https://github.com/i098/Crewship/issues/138)).
- The harbor ship has a larger tapered hull, two square-rigged masts with pale sails, a pirate flag, cannons, railings, and warm lanterns.
  Map walks from the dock and ship use supported gangway and stair connections and avoid deck obstacles in both directions.
  Ship cloth shading uses a separate path to keep the structural complexity gate clean ([#154](https://github.com/i098/Crewship/issues/154)).
- The mobile harbor joystick now sits at the bottom-left with safe-area spacing, while touch look remains available on the right ([#155](https://github.com/i098/Crewship/issues/155)).
- Harbor pop-ups now use short ASCII signs with clickable grid links and off-screen keyboard and screen reader access.
  The docs link opens the feature index.
  Signs reflow on narrow phones and use compact scene placement when no clear rectangle fits.
  Compact signs keep their links clear of the touch move pad.
  Keyboard link focus closes the map and cancels pending automatic selection ([#159](https://github.com/i098/Crewship/issues/159)).
- Replace architecture prose with six diagrams and preserve the detailed reference for agents with updated section links ([#160](https://github.com/i098/Crewship/issues/160)).
- The crewship.si scene runs at a higher frame rate: it tests only the objects each part of the screen can see and redraws only changed cells ([#161](https://github.com/i098/Crewship/issues/161)).
- The README features section now uses a distinct label for its collapsed list ([#186](https://github.com/i098/Crewship/issues/186)).
- One scene wind fills the harbor ship's sails into gently moving curved bellies with taut sheets. A black skull-and-crossbones flag and the pennants stream with it ([#195](https://github.com/i098/Crewship/issues/195)).
- The harbor house room now has a fireplace with a fire, a bookcase, chairs, an armchair, sea charts, crates, a sea chest, potted plants, and a rug ([#197](https://github.com/i098/Crewship/issues/197)).
- The README footer now lists documentation links with short, readable labels ([#199](https://github.com/i098/Crewship/issues/199)).
- The iMessage desk now requests Luna 6 for memory compaction with thinking off and the priority service tier, without changing the desk model ([#218](https://github.com/i098/Crewship/issues/218)).
- The harbor's oak, lime, and birch trees have tapered trunks that branch into ragged clumps of leaves, with gaps that show the sky.
  The palms have curved, ringed trunks and drooping fronds of many leaflets, and all trees sway in the scene's wind ([#227](https://github.com/i098/Crewship/issues/227)).
- Skip heavy CI jobs on documentation-only pull requests while required checks still report.
  Keep classification and changelog failures blocking through an existing required check, and keep the quality gate PR-only ([#250](https://github.com/i098/Crewship/issues/250)).
- The installer downloads and verifies a release tarball and its checksum into a versioned directory instead of running `git clone`; rerunning it updates and keeps `.local/host.yml`, and an existing git install moves to a backup beside the new layout ([#255](https://github.com/i098/Crewship/issues/255)).
- The crewboard daemon and CLI now default to `$XDG_RUNTIME_DIR/crewboard.sock` (else `/run/user/<uid>/crewboard.sock`) when `CREWBOARD_SOCKET` is unset, so running agents need no restart. The Firstmate board patch gates use the same default ([#257](https://github.com/i098/Crewship/issues/257)).
- Skip heavy CI jobs for pull requests limited to harbor files, documentation, or both.
  Keep the changelog check and the separate harbor deployment workflow unchanged ([#259](https://github.com/i098/Crewship/issues/259)).

### Removed

- **Breaking:** remove the shared Supabase profile and installer; use [Shared Postgres](../docs/shared-postgres.md), remove `profiles.shared_supabase`, `fleet.supabase_project_id`, `fleet.fixture_archive`, and `fleet.worktree_pools`, and remove existing stacks manually when no longer needed ([#165](https://github.com/i098/Crewship/issues/165)).
- Remove the stale `opus-speed` public skill; the skills installer removes its installed copies on the next apply ([#237](https://github.com/i098/Crewship/issues/237)).

### Fixed

- BlueBubbles relay setup now writes a password and disables public tunnels before the first launch, then checks that the API requires the password ([#117](https://github.com/i098/Crewship/issues/117)).
- The BlueBubbles bridge skips typing and tapbacks and sends replies without a thread when a relay's Private API is off ([#141](https://github.com/i098/Crewship/issues/141)).
- The crewship.si landing page no longer crashes on iPhone Safari: phones and tablets draw the scene one glyph at a time at 2 device pixels per CSS pixel at most ([#143](https://github.com/i098/Crewship/issues/143)).
- Keep main CI runs from being cancelled by newer pushes ([#146](https://github.com/i098/Crewship/issues/146)).
- Harbor map walks now route around every walking obstacle from shared collision bounds, including trees, hedges, the fountain basin, and the house.
  Map walks use the local floor height and continuous ground coverage, including sloped beaches and the dock-to-gangway crossing.
  Map walks reach the mast and bow sign from nearby deck positions instead of reporting arrival at the starting position ([#150](https://github.com/i098/Crewship/issues/150)).
- The harbor keeps its first grid and field of view, waits for fonts, and redraws resizes without blank frames ([#157](https://github.com/i098/Crewship/issues/157)).
- The BlueBubbles bridge reports a refused relay connection as "connection refused" with Bun 1.4.3 and later, which use the `ECONNREFUSED` error code ([#168](https://github.com/i098/Crewship/issues/168)).
- The landing page no longer shows the plain page when a browser add-on adds a failing resource or promise, and large high-DPR windows keep the canvas within browser size limits ([#178](https://github.com/i098/Crewship/issues/178)).
- The iMessage bridge tests publish complete fake messages atomically and wait for queue completion without reading files that can disappear ([#189](https://github.com/i098/Crewship/issues/189)).
- Touch signs use compact link rows with padded tap regions, so the welcome sign hides less of the ship ([#190](https://github.com/i098/Crewship/issues/190)).
- Harbor ASCII signs now seat rectangular frames on the lowest projected support top, covering each post, with compact layouts when space is limited ([#201](https://github.com/i098/Crewship/issues/201)).
- Proactive iMessage sends stay in the owner's latest direct chat, including through transport startup outages, without delivery-confirmation blocking ([#207](https://github.com/i098/Crewship/issues/207)).
- The iMessage desk uses small compaction chunks and retries failures with exponential backoff while keeping source messages intact.
  Each compaction chunk and reduction retains the source message's kind ([#208](https://github.com/i098/Crewship/issues/208)).
- The iMessage routing tests wait for recorded sends before checking results, which removes outbox read races ([#215](https://github.com/i098/Crewship/issues/215)).
- The harbor fountain's water now falls as droplets well inside its upper bowl and basin, breaking up as it falls, with splashes, spreading ripples, and mist where the streams land ([#224](https://github.com/i098/Crewship/issues/224)).
- The crewship.si landing page no longer draws a pale band of dotted rows on the horizon; low, dark hills rise from the sea on part of it instead ([#225](https://github.com/i098/Crewship/issues/225)).
- The iMessage bridge stops its running model children within a few seconds on SIGTERM or SIGINT, with a 10-second systemd stop limit ([#228](https://github.com/i098/Crewship/issues/228)).
- The iMessage bridge disables inherited compaction memory work and saves a shared exponential cooldown across restarts without delaying desk replies ([#235](https://github.com/i098/Crewship/issues/235)).
- The harbor ship now sways gently at its mooring: a much smaller roll and bob, a slower eased period, still scaled by the wind.
  The cabin and gun deck now share the gentle sway, with a small pitch and moving lanterns.
  Reduced motion keeps the ship and both rooms still ([#243](https://github.com/i098/Crewship/issues/243)).

## [0.4.0] - 2026-10-10

### Added

- Default omp rules: `rules/public/` (committed) and `rules/private/` (git-ignored) rule files, installed to omp's global rules folder by the `agents` profile with the skills installer; `skills.private_source` also fills `rules/private/` from the `rules/` folder of that source, a private rule wins over a public one of the same name, and rules added by hand are never touched.
  The browser rules install only when `fleet_browsers` or `fleet_guards` enables the ladder; disabling it removes only manifest-owned copies ([#89](https://github.com/i098/Crewship/issues/89)).
- Opt-in crew board configuration now exports `CREWBOARD_SOCKET` to new shells and Herdr agents ([#119](https://github.com/i098/Crewship/issues/119)).

### Changed

- Renamed the repository-only names that still said factory: `containers/factory.container.yml` is `containers/crewship.container.yml`, `schemas/factory.schema.json` is `schemas/crewship.schema.json` (with its `$id`), the Python project is `crewship`, and the docs say Crewship; host config keys, paths and unit names do not change ([#96](https://github.com/i098/Crewship/issues/96)).
- README: the Features list shows each opt-in feature with an "(opt-in)" tag, and a new collapsed Default config part lists what a fresh host gets; `tests/test_readme.py` checks both against the host config schema, `config/default.yml`, and `config/omp.yml` ([#100](https://github.com/i098/Crewship/issues/100)).
- The README puts documentation links in the Features list and links issue forms from its footer ([#108](https://github.com/i098/Crewship/issues/108)).

### Fixed

- `harbor/`: the island ground has no square patches of bare earth, moss or flowers; the grass mixes its greens blade by blade and the flowers are small dots ([#81](https://github.com/i098/Crewship/issues/81)).
- The npm publish workflow no longer fails when the release PR already set `npm/package.json` to the release version; it checks that the version matches the tag and stops with an error before the publish when they differ ([#122](https://github.com/i098/Crewship/issues/122)).
- Fixed Python test collection by loading the renamed Crewship schema in the README checks ([#129](https://github.com/i098/Crewship/issues/129)).

## [0.3.0] - 2026-10-10

### Added

- Optional `skills.private_source` host setting (a local directory or a git URL, with an optional `skills.private_ref`) that fills `skills/private/` before the skills install; git uses the account's own sign-in, without the setting nothing is fetched, and removing it removes the skills an earlier fill added ([#57](https://github.com/i098/Crewship/issues/57)).
- README: a Built with section that lists each third-party project Crewship installs or builds on, with a link and its license ([#73](https://github.com/i098/Crewship/issues/73)).
- Eleven public skills in `skills/public/` with general working rules: code navigation, engineering standards, git and PR habits, IEEE documentation, operating rules, Opus speed, process safety, progress bars, quality gates, talk style, and tooling conventions; a test fails when a public skill holds a private detail such as a home path, an email or a host address ([#85](https://github.com/i098/Crewship/issues/85)).
- Generic global instructions in `config/AGENTS.md`, installed by the `agents` profile as `~/.claude/CLAUDE.md`, `~/.omp/agent/AGENTS.md` and `~/.codex/AGENTS.md`; a file changed on the host is moved to a timestamped backup first, and an unchanged apply changes nothing ([#86](https://github.com/i098/Crewship/issues/86)).
- Optional crew board (`factory.board`, `./ship.sh dock --board`, or a new-host question): apply builds `crewboard/` with cargo and runs it as the user service `crewboard.service` with a memory limit; without the key, apply stops and removes the service and the binary ([#95](https://github.com/i098/Crewship/issues/95)).

### Changed

- Each pull request adds its changelog entry as its own file, `changelog.d/<issue>.<type>.md`, and no longer edits `CHANGELOG.md`, so pull requests that run at the same time do not conflict; the release step assembles the files into `CHANGELOG.md` with `towncrier build`, and CI fails a pull request without a fragment unless it has the `no changelog` label ([#90](https://github.com/i098/Crewship/issues/90)).
- README: the install part is labeled command blocks, and host sizing is one sentence ([#91](https://github.com/i098/Crewship/issues/91)).
- Deployments link each GHCR image push to the package page and each landing page deploy to https://crewship.si instead of its `workers.dev` address ([#102](https://github.com/i098/Crewship/issues/102)).
- The README tagline, the landing page description, and the npm package description are now "Orchestrate hundreds of agents effortlessly - hardware is the limit." ([#105](https://github.com/i098/Crewship/issues/105)).
- The README now links to CREDITS.md for the full third-party list ([#115](https://github.com/i098/Crewship/issues/115)).

### Fixed

- `npx crewship --help` and `install.sh --help` print the usage and change nothing; a bad option prints the usage and exits with an error ([#94](https://github.com/i098/Crewship/issues/94)).

## [0.2.0] - 2026-10-09

### Added

- README screenshot of a finished host, captured from demo repositories ([#35](https://github.com/i098/Crewship/issues/35)).
- Git conventions and branch rules in `CONTRIBUTING.md`, issue forms, a pull request template, `SUPPORT.md`, and `CODEOWNERS` for `.github/` ([#47](https://github.com/i098/Crewship/issues/47)).
- Sponsor button on the repository page, from `.github/FUNDING.yml`, that opens the i098 GitHub Sponsors profile ([#59](https://github.com/i098/Crewship/issues/59)).
- Optional GitHub board (`factory.github_board`): a user timer mirrors Firstmate work items to issues in a repository you choose, keeps a Project `Status` field in step (queued, in progress, in review, done), and posts new status lines as batched issue comments. The new-host questions ask whether to turn it on; without the key the host makes no GitHub calls for it ([#45](https://github.com/i098/Crewship/issues/45)).
- README: a centered header with a badge row and short links, a Why Crewship list, a collapsed Features list, a Get a machine part with sizing, a Sponsors section, and a star-history chart; `SECURITY.md`, `CODE_OF_CONDUCT.md`, and a 1280x640 social preview image ([#39](https://github.com/i098/Crewship/issues/39)).
- `skills/public/` (committed) and `skills/private/` (git-ignored) skill folders, installed for omp and Claude Code by the `agents` profile; a private skill wins over a public one of the same name, and skills added by hand are never touched ([#56](https://github.com/i098/Crewship/issues/56)).
- Each release publishes the worker container image to the GitHub Container Registry as `ghcr.io/i098/crewship:X.Y.Z` and `:latest`, so the repository page lists it under Packages ([#54](https://github.com/i098/Crewship/issues/54)).
- README sponsor list: a daily `sponsors` workflow writes the GitHub Sponsors of i098 into the Sponsors section and opens one pull request when the list changes; while there are no sponsors, the "be the first" line stays ([#68](https://github.com/i098/Crewship/issues/68)).
- One-command install for a fresh Ubuntu machine: `install.sh` (`curl … | bash`) and the `crewship` npm package (`npx crewship`), published from each release with npm trusted publishing ([#40](https://github.com/i098/Crewship/issues/40)).
- `crewboard/`, a Rust daemon and command line tool for an opt-in, host-local, in-memory message board between agents over a Unix socket; nothing installs or runs it yet ([#71](https://github.com/i098/Crewship/issues/71)).
- `harbor/`: the crewship.si landing page, a first-person ASCII walk around the docked ship that opens a card per feature, deployed to Cloudflare Workers from GitHub Actions and kept out of every host and image ([#49](https://github.com/i098/Crewship/issues/49)).

### Changed

- The license is now FSL-1.1-Apache-2.0 (SPDX `FSL-1.1-ALv2`), not MIT: each version becomes Apache 2.0 two years after its release, and releases up to and including v0.1.0 stay MIT ([#50](https://github.com/i098/Crewship/issues/50)).
- **Breaking:** the fleet guard units are now `crewship-*`, not `flotilla-*`; apply stops and deletes the old units, except that the old shared Supabase unit is deleted without being stopped, so the shared stack keeps running through the rename. The Docker guard is general and runs every hour: it removes stopped containers 24 h after they exit and reports running ones 48 h old (fixed), and it never touches a container with the `crewship.keep` label or a restart policy, volumes or images. It no longer removes second Supabase stacks; `docker-guard-allow.txt` is deleted. Tune the stopped age with `fleet.docker_guard.stopped_hours` ([#43](https://github.com/i098/Crewship/issues/43)).
- **Breaking:** renamed the entry points and scripts to nautical names, and the old names no longer exist: `bootstrap.sh` is `onboard.sh`; `factory` is `ship.sh`, with `init`, `validate`, `plan`, `apply`, `doctor` now `dock`, `inspect`, `chart`, `launch`, `survey`; `scripts/factory.py`, `install_tools.py`, `push-super-env.sh`, `fetch-super-env.sh` are now `ship.py`, `provisions.py`, `stow-secrets.sh`, `fetch-secrets.sh`. Update notes and scripts that use the old commands ([#44](https://github.com/i098/Crewship/issues/44)).
- Renamed the project to Crewship; the repository is now i098/Crewship ([#38](https://github.com/i098/Crewship/issues/38)).
- README screenshot now shows a real Herdr session with Firstmate, with the other project names and agent text changed to generic examples ([#35](https://github.com/i098/Crewship/issues/35)).

### Fixed

- `scripts/stow-secrets.sh` no longer fails with `maximum_secrets_exceeded` once `super.env` has more than 100 variables: it stores the whole file in a few chunks instead of one secret per variable, and it deletes the per-variable secrets the chunks replace. On a full store it deletes just enough of them before creating the chunks, so fetches can fail for a few seconds during that one push ([#58](https://github.com/i098/Crewship/issues/58)).
- The worker image and the compose backing services pull from `mirror.gcr.io`, Google's Docker Hub mirror, so the CI image build no longer fails on Docker Hub's anonymous pull limit (`429 Too Many Requests`); the images are the same official ones ([#63](https://github.com/i098/Crewship/issues/63)).
- The iMessage bridge no longer loses messages when the Photon service is down: every send and tapback, including the desk's and the "firstmate did not get that" reply, goes to a durable outbox that retries transient errors with backoff and keeps the order, failed attachment downloads are retried and their note is filed again with the saved path, an item that can never pass moves to a dead-letter folder instead of blocking the queue, typing errors never fail a send, and an `UNAVAILABLE` reply is logged as one line ([#61](https://github.com/i098/Crewship/issues/61)).
- The iMessage bridge no longer drops the owner's edited texts: each edit becomes a new inbox note, `[edited] <new text> (was: <old text>)`, that wakes Firstmate; when the bridge does not know the old text, the note says so ([#80](https://github.com/i098/Crewship/issues/80)).

## [0.1.0] - 2026-10-09

### Added

- Ansible recipe and `factory` CLI (`init`, `validate`, `plan`, `apply`, `doctor`) that turn a fresh Ubuntu host into an AI-agent coding host: Herdr, Firstmate, the omp agent fleet, fleet guards, Docker, and the Concord and slk chat clients, from latest checksum-verified releases.
- `herdr-patch` command that removes Herdr's opaque background fill over mosh and restores mosh images ([#2](https://github.com/i098/Crewship/pull/2), [#9](https://github.com/i098/Crewship/pull/9)).
- Fleet-browser VNC tier packages ([#7](https://github.com/i098/Crewship/pull/7)).
- Optional data disk for the Docker data root and the npm and pip caches ([#14](https://github.com/i098/Crewship/pull/14)).
- `gws` install and multi-account Google sign-in docs ([#15](https://github.com/i098/Crewship/pull/15)).
- Self-hosted CI pool of just-in-time GitHub Actions runners ([#16](https://github.com/i098/Crewship/pull/16)).
- `dia-debug`: keeps Dia running on a Mac with a prompt-free CDP port ([#18](https://github.com/i098/Crewship/pull/18)).
- Optional iMessage bridge to Firstmate over Photon Spectrum, with a persistent compressed chat memory for the front desk ([#22](https://github.com/i098/Crewship/pull/22), [#26](https://github.com/i098/Crewship/pull/26)).
- sentrux and fallow quality gate for omp agents and CI ([#32](https://github.com/i098/Crewship/pull/32)).

### Changed

- Recipe synced with the running host: chat profile, inotify limit, omp and Herdr settings ([#10](https://github.com/i098/Crewship/pull/10)).
- README shows Concord and slk in the default install ([#21](https://github.com/i098/Crewship/pull/21)).

### Fixed

- `herdr-mosh` is installed from `herdr-patch` and linked into `/usr/local/bin` ([#4](https://github.com/i098/Crewship/pull/4)).
- iMessage front desk waits a 4-second quiet period, sends multi-bubble replies, and keeps the full intake ([#25](https://github.com/i098/Crewship/pull/25), [#28](https://github.com/i098/Crewship/pull/28)).
- Firstmate inbox wake patches apply on top of upstream main ([#30](https://github.com/i098/Crewship/pull/30)).

[Unreleased]: https://github.com/i098/Crewship/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/i098/Crewship/releases/tag/v0.4.1
[0.4.0]: https://github.com/i098/Crewship/releases/tag/v0.4.0
[0.3.0]: https://github.com/i098/Crewship/releases/tag/v0.3.0
[0.2.0]: https://github.com/i098/Crewship/releases/tag/v0.2.0
[0.1.0]: https://github.com/i098/Crewship/releases/tag/v0.1.0
