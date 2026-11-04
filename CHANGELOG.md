# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.8] - 2026-10-28

### Added

- Add a public skill that points to Floorplan, a third-party Claude Code plugin for interactive codebase maps.
- Add search crawler access, a GPTBot block, a sitemap, and canonical page metadata to the Crewship site ([#759](https://github.com/i098/Crewship/issues/759)).
- Add a readable About page at `/about` and a product summary in the home page's HTML and initial harbor sign ([#760](https://github.com/i098/Crewship/issues/760)).
- The Harbor start menu now waits for Explore before animation and sound. Settings saves graphics, motion, and sound choices.
  Map selections remain visible when landmarks share a cell ([#761](https://github.com/i098/Crewship/issues/761)).
- Add `crewship init` with load, extra storage, browser sizing, a starter choice, and nominal capacity checks.
  Support manual or SSH setup with existing keys, matching releases, and curl prerequisites.
  Restrict guided SSH setup to public-key authentication and show both sizing formulas for loads above the presets ([#762](https://github.com/i098/Crewship/issues/762)).
- Added `crewship schedules`, a read-only OpenTUI viewer for local cron entries, systemd timers, and registered Firstmate checks.
  It shows purpose labels, proven owners, schedules, service results, source errors, and journal details without running jobs.
  The viewer puts failed jobs first, colors results, and keeps raw properties behind a key.
  The inventory includes check metadata from every validated registry home and uses only executable, script, unit, and working-directory paths to prove ownership.
  The viewer normalizes home paths before identity matching and renders control and format characters as visible escapes.
  The viewer shows `ExecCondition` skips as non-failure results, even without main-process history.
  Metadata read errors preserve stale checks without scanning unvalidated homes, and unresolved command expansions no longer prove ownership ([#771](https://github.com/i098/Crewship/issues/771)).
- The Slack relay has an optional explicit-mention-only filter and a read-only dry run that sends no notifications ([#773](https://github.com/i098/Crewship/issues/773)).
- The Slack relay accepts `"mention_only": "direct"` to notify for every eligible direct mention and one-to-one DM, regardless of the model's verdict.
  Failed model calls or missing lines use the plain sender, channel, and message text, including during replay.
  Boolean filtering, deduplication, and notification limits stay unchanged.
  Switching to direct mode clears queued lines and does not automatically replay old dropped messages.
  An optional `dbs` list reads multiple slk profile caches read-only, with shared deduplication and per-workspace self IDs ([#781](https://github.com/i098/Crewship/issues/781)).
- The Slack relay can keep `@everyone`, `@channel`, and `@here` messages in direct mode for each workspace with `broadcasts: true`.
  The option defaults to false and preserves deduplication, delivery limits, and read-only Slack access.
  Notifications for enabled workspaces include the workspace name.
  All notification paths collapse whitespace and remove URLs before queuing each message as one line, without decoding message text again.
  If URL removal empties a model line, the notification uses the cached sender, channel, and message text ([#785](https://github.com/i098/Crewship/issues/785)).
- New hosts get limited models and environment-based Inception credentials; apply preserves model choices but seeds missing model files and enforces Codex context overrides ([#791](https://github.com/i098/Crewship/issues/791)).
- The `agents` profile caps Opus 5.5 effort at `high` in Firstmate-spawned omp sessions and no-mistakes `pi` gates.
  Primary omp sessions, other models, and lower effort levels remain unchanged.
  Set `FM_OPUS_EFFORT_UNCAPPED=1` in the process environment to disable the cap ([#792](https://github.com/i098/Crewship/issues/792)).
- With services enabled, `launch` creates a missing `schedules` tab in the Herdr `machine` workspace and starts `crewship schedules` there.
  It creates missing workspaces and preserves custom tabs and focus.
  It never sends input to an existing tab or pane.
  If the schedules tab exists, `launch` leaves it unchanged and prints: `run crewship schedules in the schedules tab`.
  Set `crewship.herdr.schedules_tab: false` to skip this setup.
  The existing installer supplies the CLI link in `~/.local/bin` ([#795](https://github.com/i098/Crewship/issues/795)).
- Install the opt-in `fm-gluttony.ts` omp extension for Firstmate crewmates and scouts.
  Each home enables it with `config/gluttony`; it stays off by default.
  Bound vibe workers, ordinary subagents, retries, and restored workers; require a good worker to handle status appends, edits, and commits.
  Set native Codex Sol workers to `priority` and direct OpenAI Sol workers to `ultrafast`, including subagents and restored workers.
  Leave shared tier defaults unchanged.
  Document model prerequisites, the omp 18.12.1 API dependency, and the Luna ultrafast limitation ([#802](https://github.com/i098/Crewship/issues/802)).
- The iMessage front desk selects a reply target within each burst.
  Strictly social reactions can complete without a supervisor handoff.
  Approvals, requests, sensitive content, and mixed bursts still reach Firstmate.
  Routing records, checked answers, draft cancellation, and delivery recovery remain in place.
  Desk answers remain in their original chat and transport during delivery recovery.
  Thread metadata does not change authored-text classification.
  Unsupported reactions cause a handoff, while uncertain reactions retain their durable delivery state.
  Unsupported typing remains silent when no healthy relay enables the Private API.
  Failed Photon reaction lookups allow delivery recovery without clearing uncertainty from earlier reaction attempts.
  A crash during a Photon lookup no longer creates false delivery uncertainty.
  BlueBubbles records reaction uncertainty only after health and capability checks, immediately before sending.
  The front-desk regression tests use a controlled clock with real disk writes for fast, repeatable recovery checks ([#804](https://github.com/i098/Crewship/issues/804)).
- The iMessage desk adds typing indicators.
  See [the typing lifecycle](docs/imessage.md#what-it-does) for refresh timing, cleanup, and chat restrictions ([#814](https://github.com/i098/Crewship/issues/814)).
- Give the desk up to 12 recent messages beside the whole-chat summary, with message ids and source kinds.
  Keep the original text up to 500 UTF-8 bytes per message, bound the block to 6,000 bytes, and drop older messages first.
  Preserve zoom, the input limits, and the rule that owner text cannot support a direct answer ([#815](https://github.com/i098/Crewship/issues/815)).
- The iMessage desk now rewrites checked text replies in the owner's short chat style.
  The change also cancels queued desk bubbles and drops restored desk text after a restart.
  See the [iMessage behavior and recovery contract](https://github.com/i098/Crewship/blob/main/docs/imessage.md#what-it-does) for voice checks, cancellation, and delivery evidence ([#824](https://github.com/i098/Crewship/issues/824)).
- Add the iMessage bridge [mute switch](https://github.com/i098/Crewship/blob/main/docs/imessage.md#mute) ([#832](https://github.com/i098/Crewship/issues/832)).
- The iMessage desk can route clear single-domain work to a registered second mate while keeping Firstmate informed. Unclear or sensitive requests and failed deliveries stay with Firstmate.
  Registered routing preserves evidence-backed short answers, including questions about approval counts and policies.
  Mate delivery does not block the bridge, and cancellation preserves delivery uncertainty without repeating sends.
  Each mate send rechecks the registry; changed entries send the remaining texts to Firstmate ([#835](https://github.com/i098/Crewship/issues/835)).
- Document Treehouse worker isolation, pool locations, configuration, reuse, and safe cleanup ([#838](https://github.com/i098/Crewship/issues/838)).
- Add native iMessage desk tools and direct mate delivery, and include transcription in installed bridges.
  Align desk test runners with the native result protocol ([#840](https://github.com/i098/Crewship/issues/840)).
- Add standalone guarded front, worker, dispatch, and relay modules without replacing the bridge loop.
  See [guarded front modules](../docs/imessage.md#guarded-front-modules) for their contracts and integration limits ([#849](https://github.com/i098/Crewship/issues/849)).
- Add the default-off `imessage.desk_v2` setting to select the V2 front desk while retaining the legacy loop for rollback ([#850](https://github.com/i098/Crewship/issues/850)).
- A read-only terminal view shows token usage and cost by period, day, hour and model ([#859](https://github.com/i098/Crewship/issues/859)).
- A read-only terminal viewer shows crewboard topics, unread counts and messages ([#861](https://github.com/i098/Crewship/issues/861)).
- Add `tools/fleet-health`, a read-only TUI that lists every Crewship component with its installed version, latest version, and an up-to-date, outdated, unknown, custom or not-installed state ([#868](https://github.com/i098/Crewship/issues/868)).
- Add the omp composer token rate and compact tui spacing to the default theme ([#870](https://github.com/i098/Crewship/issues/870)).
- Added the `usage-tui` and `crewboard-tui` commands to the install, and `launch` now opens each as a Herdr tab in the `machine` workspace beside `schedules`.
  Set `crewship.herdr.usage_tab` or `crewboard_tab` to `false` to skip a tab; both default to `true`.
  `crewship update` opens the new tabs in an existing `machine` workspace once, without duplicates, and leaves running panes alone ([#871](https://github.com/i098/Crewship/issues/871)).
- Add one-line summaries to crew board threads, set and read with the crewboard command and refreshed by a debounced model call outside the daemon ([#873](https://github.com/i098/Crewship/issues/873)).
- Show each topic's one-line summary in crewboard-tui, under the topic name and at the top of the message pane ([#880](https://github.com/i098/Crewship/issues/880)).
- Add desk helpers the V2 front desk needs: secret values export, read result type, voice word-order guard, multi-clause exact output ([#881](https://github.com/i098/Crewship/issues/881)).
- The usage TUI shows how much quota is left per account and window, with the reset time, and has a `--once` text mode ([#886](https://github.com/i098/Crewship/issues/886)).
- Add the relay target and dispatch policy modules the V2 front desk uses ([#888](https://github.com/i098/Crewship/issues/888)).
- Add the front desk classifier module for the V2 desk ([#894](https://github.com/i098/Crewship/issues/894)).
- Install the kun skill during apply and tell agents to load it when unsure how to implement something ([#896](https://github.com/i098/Crewship/issues/896)).
- Install backpass with the `agents` profile, and tell agents in the default global instructions to edit AGENTS.md and CLAUDE.md through it. Existing hosts keep their instructions file ([#897](https://github.com/i098/Crewship/issues/897)).
- Install the vision skill (kunchenguid/vision) by default with the Crewship skills step, at the newest default-branch commit, and add a draft VISION.md for Crewship ([#898](https://github.com/i098/Crewship/issues/898)).
- The tooling-conventions skill turns answered Lavish boards into a tasks-axi task list and works it to completion ([#899](https://github.com/i098/Crewship/issues/899)).
- Add the desk subagent module for the V2 desk ([#907](https://github.com/i098/Crewship/issues/907)).
- Wire the V2 front desk into the iMessage bridge: a typed front answer, silent social turns as one tapback, and a fail-closed handoff to Firstmate ([#912](https://github.com/i098/Crewship/issues/912)).
- Add the `observability` public skill: a seven-level checklist for logs, metrics, traces, correlation, alerts, SLOs, and cardinality ([#915](https://github.com/i098/Crewship/issues/915)).
- Add an HSL color palette rule to the UI shared basics: one brand hue, fixed neutral lightness steps, and dark and light mode values ([#917](https://github.com/i098/Crewship/issues/917)).
- Add a tasks view to crewboard-tui (key `t`, `--once` for a plain snapshot): per agent the current task, next queued items, open decisions and time since last progress, with stalled agents pinned on top, grouped by mate and project, collapsed by default, filterable and virtualized ([#919](https://github.com/i098/Crewship/issues/919)).
- Add a shared validation post-mortem log, a script that rejects empty fields, and a contributor rule to land prevention changes ([#929](https://github.com/i098/Crewship/issues/929)).
- `runs-tui` shows validation post-mortem lines under the run that they name in the current view, and key `p` lists the lines that name no visible run. It reads `docs/validation-postmortems.md` and the files named by `CREWSHIP_POSTMORTEM_PATHS` ([#931](https://github.com/i098/Crewship/issues/931)).
- A new `lavish-tui` terminal view lists every lavish board with its owner worker and flags open boards whose worker is torn down, and `lavish-keep` keeps the boards of a worker loading after its worktree is cleaned up ([#941](https://github.com/i098/Crewship/issues/941)).
- Add the MIT-licensed be-ambitious public skill with source attribution ([#942](https://github.com/i098/Crewship/issues/942)).
- Publish the README, setup guide, and repository guides as crawlable HTML at crewship.si/docs with linked navigation, per-page metadata, breadcrumb structured data, a generated sitemap, and a dependency-free build and local preview ([#951](https://github.com/i098/Crewship/issues/951)).
- crewship.si hosts an IndexNow key file, so changed pages can be submitted to Bing, Yandex, and other IndexNow search engines ([#953](https://github.com/i098/Crewship/issues/953)).
- crewship.si serves the Google Search Console verification file ([#957](https://github.com/i098/Crewship/issues/957)).
- The crewship.si About, How, and docs pages show a title, description, and preview image when shared ([#965](https://github.com/i098/Crewship/issues/965)).
- crewship.si structured data names the site crewship.si and gives search engines the Crewship logo and official profiles ([#971](https://github.com/i098/Crewship/issues/971)).
- The base packages now include zoxide, and apply adds a guarded block to `~/.bashrc` that loads `z` and `zi` in interactive Bash only. Agent shells and omp's bash tool do not get it ([#973](https://github.com/i098/Crewship/issues/973)).
- Add a Firstmate patch that queues needs-decision and blocked lines, sends each to one crewmate that texts the owner, and texts a progress line when a second mate finishes a chunk ([#977](https://github.com/i098/Crewship/issues/977)).
- Add a decision queue view to crewboard-tui (key `d`, `--once --queue` for a plain snapshot): per mate the count of open, in progress, answered, closed and stuck decisions, then one row per queued record. It is read-only.
  `launch` and `crewship update` open it as a `decision-queue` tab in the `machine` workspace, under the `crewship.herdr.crewboard_tab` switch ([#980](https://github.com/i098/Crewship/issues/980)).
- A new `runs-tui` terminal view lists every no-mistakes validation run on the host with its home, mate, task, repo, PR, current step, fix loops, elapsed time and outcome. Use `--json` to print the runs and their post-mortem lines as one JSON document for agents.
- Add the apple-hig public skill: a short Apple Human Interface Guidelines digest with current iOS design and SwiftUI resources, for iOS, macOS and mobile UI work.

### Changed

- Skip file-removal calls for absent managed paths in the disabled board, GitHub board, gateway, usage and token suggestion cleanups, using the read-only path checker ([#747](https://github.com/i098/Crewship/issues/747)).
- Resolve independent release sources concurrently while keeping one lookup per GitHub repository per apply and all publisher checksum checks ([#751](https://github.com/i098/Crewship/issues/751)).
- Isolate prereleases from stable release channels, require owner approval for stable releases, and preserve legacy archive installation through an approved installer ([#763](https://github.com/i098/Crewship/issues/763)).
- Document the guided server quick start, existing-key SSH setup, and hosting advice. Clarify where commands run and that the gateway is opt-in ([#764](https://github.com/i098/Crewship/issues/764)).
- Read the default omp plugin registry directly during apply to avoid an extra process on warm runs.
  Keep marketplace refreshes, missing-plugin installation, and upgrades.
  Use the CLI fallback for custom registry layouts and when supported dotenv files exist ([#780](https://github.com/i098/Crewship/issues/780)).
- The iMessage front desk starts reading inbox status before saving the message and refreshes the read for each new text.
  Slow disk writes no longer delay status startup ([#786](https://github.com/i098/Crewship/issues/786)).
- Firstmate dispatch now selects Mercury 3 at high thinking for simple coding and limits Opus profiles to high thinking.
  Fable remains outside explicit spawn choices; the automatic Opus fallback is unchanged.
  The configuration guide explains how to keep local dispatch settings ([#793](https://github.com/i098/Crewship/issues/793)).
- Check home-layout directory ownership in one batch before applying filesystem changes.
  Skip unchanged real directories while preserving their modes.
  Keep the existing Ansible task for missing paths, links, type errors, and ownership repairs ([#819](https://github.com/i098/Crewship/issues/819)).
- The iMessage desk starts a turn after 350 milliseconds of silence, with a two-second cap on continuous text batching. New text still cancels an older draft, and Firstmate activity still stops the desk. Status reads start with each text; Instagram timing stays unchanged ([#822](https://github.com/i098/Crewship/issues/822)).
- The iMessage desk now chooses occasional fitting social reactions and can add a short, checked acknowledgement. Requests, questions, approvals, sensitive messages, and mixed bursts receive no desk reaction. A combined response keeps its text delivery progress through reaction retries and restarts.
  Delivered replies use stable memory identities, so a restart between delivery progress and memory recording neither loses nor duplicates the reply.
  Transport checks cover social reactions and work-request handoffs separately on Photon and BlueBubbles ([#823](https://github.com/i098/Crewship/issues/823)).
- Reject desk voice rewrites that turn `paused` into `running` or `cannot start` into `can start`, while keeping contractions and shorter wording valid ([#829](https://github.com/i098/Crewship/issues/829)).
- New Firstmate checkouts default to Herdr through `firstmate.backend`, while existing backend choices and pane safeguards remain intact on current upstream ([#845](https://github.com/i098/Crewship/issues/845)).
- The schedules terminal view uses a shared palette and a transparent background ([#858](https://github.com/i098/Crewship/issues/858)).
- Seed the compaction and tool-output spill settings in the omp config and state that GPT-6 Astra is never a worker model ([#860](https://github.com/i098/Crewship/issues/860)).
- The docs recommend WezTerm as the terminal on the computer you attach from, with the install line and a short config example ([#876](https://github.com/i098/Crewship/issues/876)).
- crewship.si now allows GPTBot, adds SoftwareApplication, WebSite and FAQPage JSON-LD, and links the How and About pages ([#879](https://github.com/i098/Crewship/issues/879)).
- New crewship omp configs compact with snapcompact first, then remote as fallback (`compaction.methodOrder`) ([#883](https://github.com/i098/Crewship/issues/883)).
- Show the DeepSeek prepaid balance, labelled with its wallet currency, in the usage TUI quota row, read from the signed-in DeepSeek platform site through Dia over CDP in a background tab, with an unavailable note when the read fails. A second `deepseek (reseller)` row shows the spend so far on the reseller key, read from a response header of a 1-token chat call ([#903](https://github.com/i098/Crewship/issues/903)).
- Crewmate and scout briefs now include a rule that a feature branch built from several slices gets one validation run ([#920](https://github.com/i098/Crewship/issues/920)).
- The README skill now compares peer repositories and forbids Last commit and Updated badges ([#938](https://github.com/i098/Crewship/issues/938)).
- The GitHub Actions workflows now use `astral-sh/setup-uv` 10.3.2 ([#945](https://github.com/i098/Crewship/issues/945)).
- Lead the README Quick start with the agent-assisted setup instruction and move the manual commands into a collapsed Manual setup block ([#955](https://github.com/i098/Crewship/issues/955)).
- The README and the npm package page link to crewship.si and its docs ([#959](https://github.com/i098/Crewship/issues/959)).
- The crewship.si home page and harbor signs link feature guides to their crewship.si docs pages, not to GitHub ([#967](https://github.com/i098/Crewship/issues/967)).

### Fixed

- The test retries up to 3 times when load makes the 15 s collector timeout drop a record ([#754](https://github.com/i098/Crewship/issues/754)).
- Start the storage guard test `notify-master` stub with `sh` to reduce the chance of a dropped fallback broadcast under load ([#755](https://github.com/i098/Crewship/issues/755)).
- Bound npm release lookups with 10-second socket timeouts and one full-document fallback for timeouts or HTTP 5xx.
  Include the URL and attempt count in final lookup errors, including incomplete reads, invalid npm JSON, and missing npm metadata fields ([#775](https://github.com/i098/Crewship/issues/775)).
- Fix devcontainer startup by selecting the provisioned builder stage, so Dev Containers does not try to pull `scratch`.
  The published worker image and its isolation remain unchanged ([#777](https://github.com/i098/Crewship/issues/777)).
- Create missing CLI and schedule directories during checkout and cloud-init previews for existing target accounts.
  Preview the command symlink before its target is installed, without changing existing files or directory access ([#778](https://github.com/i098/Crewship/issues/778)).
- Run the harbor browser checks in the matching Playwright image instead of downloading Ubuntu packages during CI. Keep the 10-minute job limit and all browser checks ([#784](https://github.com/i098/Crewship/issues/784)).
- The iMessage bridge and optional card tunnel now source `~/super.env` through the service shell. This supports shell `export` assignments and prevents systemd from logging rejected secret assignments through its environment-file parser ([#794](https://github.com/i098/Crewship/issues/794)).
- Keep the last Herdr sidebar usage percentages when `omp usage` fails, mark them stale after one hour, and allow 60 seconds for refreshes ([#799](https://github.com/i098/Crewship/issues/799)).
- Refresh the gluttony credential check at each worker spawn, and check credentials only on the first entry read of a restored session, so a sign-in after session start works ([#807](https://github.com/i098/Crewship/issues/807)).
- Bound the `smol` helper role in gluttony child sessions to the fast tier: its model, provider and effort follow the same bounds as fast workers. When no fast model has a usable credential, `smol` keeps its configured model ([#808](https://github.com/i098/Crewship/issues/808)).
- Bound the CI fakeroot installation to five minutes with apt retries and network timeouts, skip installation when fakeroot is available, and allow 35 minutes for the Python and configuration job ([#809](https://github.com/i098/Crewship/issues/809)).
- Use the public release Atom feed when the prerelease API returns no non-draft releases, so an empty or all-draft response does not stop tool provisioning ([#811](https://github.com/i098/Crewship/issues/811)).
- Limit Herdr sidebar disk refreshes to one due home and 30 seconds per run. Slow refreshes keep the last good disk value, and deferred homes retry on the next run. Other sidebar rows wait at most 30 seconds for disk work ([#820](https://github.com/i098/Crewship/issues/820)).
- The iMessage bridge fixes unanswered requests and expired typing.
  Targeted replies preserve older unanswered requests, chat deadlines do not interrupt another chat's draft, and restart recovery has no age cutoff.
  Synchronous inbox commands remain limited to five seconds each and can delay the deadline and typing timers.
  Initial card replay confirms acceptance without treating later edits as new answers, and cross-chat desk answers preserve other chats' unanswered requests.
  Explicit replies include current edits, and the deadline clears typing without waiting for active mate delivery.
  Known Photon edits retain the original chat reference when raw events use a different chat identifier.
  Cancellation tests wait for asynchronous transport completion.
  Native-tool tests control deadline time independently of model-call duration.
  Missing-session tests check halted behavior without requiring untruncated diagnostic text.
  Desk answer rejection uses one branch while retaining handoff tracing.
  See [the routing and typing contract](docs/imessage.md#what-it-does) for timing, trace fields, and recovery limits.
  Queued supervisor responses retain their original request coverage, including when a later request arrives in the same millisecond.
  Accepted bubbles and reactions keep their outbox progress when response confirmation fails, so journal errors do not resend them.
  Transport acceptance traces keep their original timestamps through confirmation failures; history checks, confirmation recovery, and card edits use separate event labels.
  Routing tests wait for outbox completion before checking response confirmations, so accepted sends cannot race those checks.
  The BlueBubbles plain-reply test checks transport acceptance instead of the obsolete empty return value ([#841](https://github.com/i098/Crewship/issues/841)).
- Fix [iMessage replies](https://github.com/i098/Crewship/blob/main/docs/imessage.md#what-it-does) to use plain wording, preserve requested exact output, and mask credential placeholders consistently ([#844](https://github.com/i098/Crewship/issues/844)).
- Skip the redundant CA-store inspection when changed distrust settings already force a rebuild; keep both pre-network trust checks ([#846](https://github.com/i098/Crewship/issues/846)).
- Send iMessage desk text as normal messages, including text sent with a reaction, even when later messages follow the selected target ([#852](https://github.com/i098/Crewship/issues/852)).
- Stop the iMessage desk from sending the fixed "I saved ...; no confirmed answer yet" receipt after eight seconds.
  The deadline still stops typing and hands unassigned requests to Firstmate, and the owner now gets only real answers ([#853](https://github.com/i098/Crewship/issues/853)).
- Send a short V2 iMessage front reply before relay or dispatch work, without completing the request or stopping its typing indicator ([#857](https://github.com/i098/Crewship/issues/857)).
- Desk no longer replies "I'll check <his words>"; the prompt forbids it, and the desk drops "I'll check", "I will check", "I'll look into" and "Let me check" replies ([#862](https://github.com/i098/Crewship/issues/862)).
- Stop the usage-tui stats sync from making herdr list its pane as an omp agent ([#891](https://github.com/i098/Crewship/issues/891)).
- Block the "I'll ask about" echo template in desk replies ([#901](https://github.com/i098/Crewship/issues/901)).
- The usage TUI quota refresh runs `omp usage --json` in its own session, so the pane no longer flickers as an `omp` agent ([#902](https://github.com/i098/Crewship/issues/902)).
- The crewship.si How page links to the About page ([#949](https://github.com/i098/Crewship/issues/949)).
- The ASCII harbor loads its unchanged start view sooner by building the walking graph only when an animated map walk first needs it ([#961](https://github.com/i098/Crewship/issues/961)).
- The Sentrux baseline accepts the intended How and About page links, so the quality gate passes on main again ([#962](https://github.com/i098/Crewship/issues/962)).
- The crewship.si home footer links to the Architecture docs page on crewship.si ([#969](https://github.com/i098/Crewship/issues/969)).

### Security

- Distrust the four emSign roots before Ansible network lookups and recover interrupted trust rebuilds.
  Update the system CA package and check the CA bundle and hashed certificate directories.
  Keep latest Node selection while enforcing the 22.23.4, 24.22.1, and 26.12.1 security minimums.
  Enforce pip 26.2.2 and certifi 2026.10.19 minimums when present in the repository, pruner, and fdu Python environments.
  Leave absent packages absent and retain Ubuntu certifi's system CA store.
  Report Python upgrades accurately with inherited packages and keep fdu replay unchanged under lowest-version resolver settings.
  Direct Node, requests, and pip to filtered system trust in shell profiles and the user-service environment.
  Disable pip's additive truststore backend and conflicting Node CA selectors while preserving unrelated flags.
  Honor custom uv project environments and reject unsafe Node archives before installation.
  Isolate runtime trust checks from inherited XDG configuration paths ([#830](https://github.com/i098/Crewship/issues/830)).
- Run the four instagrapi entrypoints in isolated uv environments with certifi>=2026.10.19. Exclude older pip and certifi packages from the base interpreter and current project without adding an unused pip installation ([#833](https://github.com/i098/Crewship/issues/833)).

## [0.4.7] - 2026-10-21

### Added

- Add a private, read-only token-suggestions report for existing usage metadata and saved Caveman measurements ([#668](https://github.com/i098/Crewship/issues/668)).
- Shared UI skills now cover ten missing UX decision rules, including response timing, progressive disclosure, input tolerance, and task completion ([#672](https://github.com/i098/Crewship/issues/672)).
- Add the public `prod-readiness` skill with 20 ordered checks, evidence-based verdicts, and links to existing guidance before production releases ([#673](https://github.com/i098/Crewship/issues/673)).
- Add optional private token-suggestions reader installation, a bounded manual service, and state-preserving disable and removal ([#677](https://github.com/i098/Crewship/issues/677)).
- Add `ship.sh setup` to report software, sign-ins and Firstmate readiness separately, with commands for missing steps from any directory.
  Check the running Herdr service regardless of `start_services`, and preserve the selected config in setup recovery commands.
  Recover a stopped Herdr service without another apply when other checks pass ([#692](https://github.com/i098/Crewship/issues/692)).
- The required pull request body check reruns after body edits and rejects invalid opening references, empty sections, missing checklist items, and unexplained unchecked items ([#695](https://github.com/i098/Crewship/issues/695)).
- Add opt-in daily private token-suggestion delivery, gated by a completed cycle for the configured inputs ([#722](https://github.com/i098/Crewship/issues/722)).
- Add bounded, metadata-only omp session support to private token-saving reports, including nested subagent and advisor sessions ([#729](https://github.com/i098/Crewship/issues/729)).

### Changed

- Pipeline pull requests use the repository template, omit generated intent, and keep validation evidence in a collapsed section ([#685](https://github.com/i098/Crewship/issues/685)).
- Lead the README with server requirements, the curl installer, and source-available license terms ([#691](https://github.com/i098/Crewship/issues/691)).
- Document issue form fields, dry-run commands, and pull request formatting for people and agents ([#694](https://github.com/i098/Crewship/issues/694)).
- Explain omp's first-run screens and remote GitHub device login without a server browser or clipboard ([#696](https://github.com/i098/Crewship/issues/696)).
- Provide a standalone Docker worker launch command, shell access, and the worker-only boundary ([#697](https://github.com/i098/Crewship/issues/697)).
- Recommend curl for fresh servers and explain Bun, Node.js, and pnpm launcher prerequisites and release selection ([#698](https://github.com/i098/Crewship/issues/698)).
- The one-command installer no longer repeats the full Ansible preview before applying; run `./ship.sh chart` for a separate preview ([#711](https://github.com/i098/Crewship/issues/711)).
- Semantic search is now opt-in with `--with sgrep` or `profiles.sgrep: true`; core installs skip its Rust build and model downloads ([#712](https://github.com/i098/Crewship/issues/712)).
- Run project-database smoke and Python checks on separate CI runners while preserving the combined required check ([#718](https://github.com/i098/Crewship/issues/718)).
- Link the private token-suggestions installation guide and its real-user CI checks from the configuration and architecture references ([#720](https://github.com/i098/Crewship/issues/720)).
- Complete the semantic-search opt-in documentation, migration guidance, credits, and optional-tool instructions ([#724](https://github.com/i098/Crewship/issues/724)).
- Batch read-only checks of required inputs, installed outputs, and legacy paths without changing missing-path or error behavior ([#726](https://github.com/i098/Crewship/issues/726)).
- Skip the redundant local plugin upgrade check on a fresh account while retaining marketplace updates and upgrades for existing installations ([#728](https://github.com/i098/Crewship/issues/728)).
- Batch remaining setup path checks while preserving input order, first-write configuration, existing directory permissions, check-mode behavior, and installation privileges ([#734](https://github.com/i098/Crewship/issues/734)).
- Install up to four independent native tools concurrently without changing latest-release resolution, checksum verification, dependent setup order, or unchanged-repeat behavior.
  Keep concurrent download progress messages on separate lines ([#735](https://github.com/i098/Crewship/issues/735)).
- Migration skips commands for missing legacy paths after stopping writers and refreshing collision checks, preserving existing data, migration order, and unchanged-repeat behavior ([#740](https://github.com/i098/Crewship/issues/740)).
- Load inactive setup task files only when selected, while preserving profile behavior, privilege boundaries, tags, and existing configurations ([#741](https://github.com/i098/Crewship/issues/741)).
- Batch Firstmate source inspection while retaining directory-aware copying, first-write behavior, symlink handling, and existing path-checker output ([#743](https://github.com/i098/Crewship/issues/743)).

### Fixed

- ETA and timeline charts keep date labels and the now marker clear, show completion only when supplied, and allow finish estimates based on stated evidence.
  Fixed-day intervals that can occur twice in one month retain distinct day labels ([#653](https://github.com/i098/Crewship/issues/653)).
- `ponytail-review` accepts one approved verdict unless a line starts with a finding location or negative net summary; it trusts prose-only cuts as clean.
  Finding locations support file paths with spaces ([#676](https://github.com/i098/Crewship/issues/676)).
- The guides clarify that unchanged applies report `changed=0` when no upstream tool has published a new release or source update since the last apply ([#680](https://github.com/i098/Crewship/issues/680)).
- Skip absent Herdr, Herdr Spaces, Chrome pruner and stall nudge units during install previews, including notified restarts. Keep installed-unit errors visible and leave real service starts unchanged ([#681](https://github.com/i098/Crewship/issues/681)).
- `scripts/new-issue` sends form data through the GitHub REST API and shows the child error summary and HTTP response body when issue creation fails ([#683](https://github.com/i098/Crewship/issues/683)).
- Print the selected Crewship release before main package setup. Explain pnpm's release-age policy when the registry lists a newer release ([#687](https://github.com/i098/Crewship/issues/687)).
- Ansible provisioning avoids injected-fact deprecation warnings and skips absent legacy directories while preserving migration through directory symlinks ([#688](https://github.com/i098/Crewship/issues/688)).
- Check available RAM before Firstmate setup questions and during `survey` and `setup`. Report the 8,000 MB worker spawn floor without changing it ([#689](https://github.com/i098/Crewship/issues/689)).
- Show short install progress lines, keep full output in private log files outside migration paths, and print the log path on success or failure.
  Keep password-required apply output visible.
  Keep the interactive terminal visible during new-host questions while capturing its output.
  Drain both output streams before the terminal session closes ([#690](https://github.com/i098/Crewship/issues/690)).
- Local provisioning now resolves the host configuration once and enables Ansible pipelining, while keeping the same tasks, tool versions, and verification ([#704](https://github.com/i098/Crewship/issues/704)).
- Managed `gh` and `gh-axi` wrappers now reject missing, unauthorized, or unresolved issue-write targets before either CLI starts, while worker-image checks verify the wrapped release paths ([#727](https://github.com/i098/Crewship/issues/727)).
- Include Mesa Vulkan drivers in the CI pool image for headless GPU tests ([#748](https://github.com/i098/Crewship/issues/748)).

## [0.4.6] - 2026-10-20

### Added

- Optional `board.github_sink` settings manage a user service that copies crew board messages to a GitHub issue ([#429](https://github.com/i098/Crewship/issues/429)).

### Fixed

- Fix fresh-host `ship.sh chart` previews for missing directories and Obscura releases, and fix the fleet-browser journald task ([#441](https://github.com/i098/Crewship/issues/441)).
- Restore fresh default installs by rebasing the Firstmate pane lifecycle patch onto current upstream code while preserving repeat-apply behavior ([#663](https://github.com/i098/Crewship/issues/663)).
- The installer waits up to ten minutes for package locks instead of failing during first-boot updates ([#664](https://github.com/i098/Crewship/issues/664)).

## [0.4.5] - 2026-10-20

### Added

- `instagram_dm.py stop` and a halt now write one flag file that `poll`, `listen`, `reply`, the reel curator, the Instagram front desk and `reel_watch.py` all honor ([#497](https://github.com/i098/Crewship/issues/497)).
- Watch Instagram reels without a login with `reel_watch.py` in the `instagram-dm` skill: one fetch at a time, at least 20 s apart, no cookies ([#499](https://github.com/i098/Crewship/issues/499)).
- Route anonymous Instagram reel fetches through the Geonode residential proxy when `GEONODE_*` settings are present in `reel_watch.py` (`instagram-dm` skill); with none set, the fetch stays direct ([#508](https://github.com/i098/Crewship/issues/508)).
- Install the global agent instructions only with `profiles.agent_instructions` (a host that already has them keeps them), set `instructions_mode` to skip, overwrite after a backup, or append one marked block to a file that exists, and make `~/.omp/agent/AGENTS.md` a one-line import of `~/.claude/CLAUDE.md` ([#510](https://github.com/i098/Crewship/issues/510)).
- Offer the global agent instructions on the installer checklist, off by default, and ask whether to skip, overwrite or append when one of the files already exists ([#511](https://github.com/i098/Crewship/issues/511)).
- Transcribe iMessage voice memos and audio attachments on the host with ffmpeg and whisperx, and file the note as `[voice memo, Ns] <words>` with the saved path; the front desk sees the same text ([#512](https://github.com/i098/Crewship/issues/512)).
- Install sgrep (local search by meaning for code and documents) on every host, with ripgrep and the Rust toolchain it needs, warm its models once, and tell agents in the global instructions to use it ([#519](https://github.com/i098/Crewship/issues/519)).
- The herdr Spaces host line shows how many agent panes are working, as "◉ working/total", after the machine shares ([#534](https://github.com/i098/Crewship/issues/534)).
- Seven public skills, `clean-code-classes`, `-comments`, `-errors`, `-formatting`, `-functions`, `-naming` and `-tests`, give rules for class design, comments, error handling, layout, functions, names and unit tests; they install only with `profiles.public_skills` ([#536](https://github.com/i098/Crewship/issues/536)).
- Four more public skills, `frontend-ui-craft`, `credentials`, `fleet-browser` and `third-party-signups`, cover UI hierarchy, handling secrets, the browser ladder and signups on an owner's standing authorization; they install only with `profiles.public_skills` ([#537](https://github.com/i098/Crewship/issues/537)).
- `blueprint/maintenance/mac-runner.sh` runs macOS GitHub Actions jobs on a Mac with just-in-time runners, one launchd agent per repository, all in one folder that one command removes ([#541](https://github.com/i098/Crewship/issues/541)).
- The CI pool job image now has Postgres 18 with pgvector. Postgres 17 stays. Each job starts the version it needs with `pg_ctlcluster` ([#552](https://github.com/i098/Crewship/issues/552)).
- A CI pool repository with `docker: dind` gets a Docker daemon of its own in each slot: a rootless `docker:dind-rootless` sidecar on the slot's own network, reached over TLS through `DOCKER_HOST`, never the host's socket. The job image now has the `docker compose` plugin ([#553](https://github.com/i098/Crewship/issues/553)).
- The `fm-imessage` card-page listener takes signed Instagram DM webhooks at `/instagram/webhook` and files each DM of the operator like the instagrapi poller does ([#556](https://github.com/i098/Crewship/issues/556)).
- `instagram-graph.ts` sends Instagram replies through the official API inside the 24-hour window, stores the API token with mode 600, and refreshes it ([#557](https://github.com/i098/Crewship/issues/557)).
- With `crewship_instagram_dm_backend: graph`, `fm-insta-reply` sends through the official Instagram API, `fm-imessage` takes the DM webhook, and a weekly timer refreshes the API token ([#558](https://github.com/i098/Crewship/issues/558)).
- The CI pool job image now includes the codex-gpui build dependencies (clang, cmake, OpenSSL, font, audio, Wayland, X11 and Vulkan development packages), so those jobs no longer install them on every run ([#559](https://github.com/i098/Crewship/issues/559)).
- Add opt-in request metadata, durable 35-day storage, retry-safe OTLP export, Pacific reports, and SigNoz custom dashboards ([#577](https://github.com/i098/Crewship/issues/577)).
- The harbor site now includes `/llms.txt` with links to the canonical Crewship documentation ([#588](https://github.com/i098/Crewship/issues/588)).
- The native usage adapter now keeps metadata in a bounded retry spool (`scripts/usage.py --store spool`) until SigNoz acknowledges it, packs an offline backlog by hour and model with lossless compression, and sends it in gzip requests with jittered spacing ([#593](https://github.com/i098/Crewship/issues/593)).
- `scripts/put-secret.sh NAME` creates or updates one Cloudflare Secrets Store secret from stdin without deletes or a Worker deploy, and the fleet-secrets Worker serves the one secret named in `FLEET_SECRETS_READABLE` at `GET /NAME`, which `scripts/fetch-secrets.sh NAME` prints ([#594](https://github.com/i098/Crewship/issues/594)).
- The Herdr Spaces sidebar shows cached Claude and OpenAI account quota means and each workspace's working/total agent count ([#597](https://github.com/i098/Crewship/issues/597)).
- Add an optical alignment rule to the `frontend-ui-craft` skill: center glyphs by visual mass, not bounding box, and check at the real viewing size ([#603](https://github.com/i098/Crewship/issues/603)).
- Add loading-policy, enabled-submit, relative-unit and UX-law rules to the `frontend-ui-craft` skill from five routed reels ([#606](https://github.com/i098/Crewship/issues/606)).
- The iMessage front desk takes `desk_provider` (`omp` or `inception`) and `desk_reasoning` settings; the default stays Claude Haiku 5.5 through omp with thinking off ([#615](https://github.com/i098/Crewship/issues/615)).
- `crewship.ci_pool.nice` lowers the CPU priority of CI: the slots get that `Nice=`, and job containers start in `ci.slice` with a lower `CPUWeight` and no CPU cap, so CI yields the CPU to agents and interactive work and still uses idle CPU ([#624](https://github.com/i098/Crewship/issues/624)).
- Add the `signal-chunks` public skill: a weekly deadline and eighteen-hour chunk method with CHUNK status updates ([#627](https://github.com/i098/Crewship/issues/627)).
- Add the public `mobile-app-first-build` skill for idea validation, platform choice, flow planning, building, testing, and release, with credit to u/olenami's guide ([#642](https://github.com/i098/Crewship/issues/642)).
- Add optional SigNoz usage installation with storage access checks, authenticated export, randomized scheduling and requests, deferred unit reloads, and data-preserving removal ([#644](https://github.com/i098/Crewship/issues/644)).

### Changed

- `instagram_dm.py` sends, tapbacks, typing indicators and read receipts now share one limiter (20-30 s apart, 10 texts an hour and 40 a day, 20 tapbacks and typing an hour, no sends for 30 min after an error), realtime events cause at most one poll every 30 s, and the poll timer jitters by 60 s ([#494](https://github.com/i098/Crewship/issues/494)).
- The Instagram front desk now waits 60 s of quiet after a reel link and answers a run of two or more links with one "got N reels" text and one tapback ([#495](https://github.com/i098/Crewship/issues/495)).
- The Instagram reel curator is now off by default (`crewship_instagram_curator_enabled`) and runs only on its own account, never the DM bot's, with at most 40 Instagram calls a run, no run within 60 min of DM activity or 24 h of a halt, and no run while the line is stopped ([#496](https://github.com/i098/Crewship/issues/496)).
- The Instagram DM note now carries a shared reel's author, caption and duration from the DM payload, and the bot makes no media, clip, user or download request of its own ([#498](https://github.com/i098/Crewship/issues/498)).
- Rename the `shared_postgres` profile to `project_databases`, because it holds a database of any engine for each project; a host config that still says `shared_postgres` keeps working ([#520](https://github.com/i098/Crewship/issues/520)).
- The storage guard now watches every mounted real block filesystem, not only the ones holding `/`, `/var/log`, the home and Docker, names the entries that grew most, and sends each alert to Firstmate as an inbox note ([#530](https://github.com/i098/Crewship/issues/530)).
- The storage guard FILL alert ignores a mount below STORAGE_FILL_MIN_PCT (70) use; WARN and CRIT are unchanged ([#532](https://github.com/i098/Crewship/issues/532)).
- The CI pool builds one runner image on the host with a compiler, GTK, Postgres 17, and bun, rebuilds it every hour, and starts every job from it ([#545](https://github.com/i098/Crewship/issues/545)).
- CI pool jobs keep the bun, npm, pnpm, cargo, and apt package caches between jobs, and write their heavy temporary data (/tmp, Postgres, apt) to the data disk ([#546](https://github.com/i098/Crewship/issues/546)).
- The CI pool watch runs every minute and restarts a slot only when GitHub shows its runner offline and the Docker daemon twice lists no container for it; slots stop their container with a grace period and wait for its removal ([#547](https://github.com/i098/Crewship/issues/547)).
- A Herdr pane and its agent now end together: closing either one ends both, a pane you close is never relaunched, and a crashed agent is still recovered. Herdr no longer resumes agents after a server restart, and the Firstmate patch layer gains `0005-herdr-pane-life.patch` ([#565](https://github.com/i098/Crewship/issues/565)).
- The iMessage desk answers supported basic questions with Haiku 5.5 and uses durable, deduplicated Firstmate handoffs for all other requests ([#578](https://github.com/i098/Crewship/issues/578)).
- The dependency patch table now describes queued inbox note timing independently of iMessage routing and links to the routing documentation ([#582](https://github.com/i098/Crewship/issues/582)).
- Arrange the SigNoz usage dashboard in shared rows, with the request and token line graphs side by side at the top ([#587](https://github.com/i098/Crewship/issues/587)).
- The `frontend-ui-craft` skill now covers fewer symbols, clearer value groups, readable actions and measured progress ([#591](https://github.com/i098/Crewship/issues/591)).
- The `frontend-ui-craft` skill is now two skills in one `ui-ux` folder, `app-dashboard` and `landing-marketing`, that share one `shared-basics.md`; the skill installer installs a skill in a group folder under its own name ([#612](https://github.com/i098/Crewship/issues/612)).
- The eta-timeline skill separates an ETA (when the current task or tasks finish) from a timeline (how long each project needs to reach its full vision, phase by phase with estimated dates) ([#616](https://github.com/i098/Crewship/issues/616)).
- The Herdr sidebar usage row shows each provider's percentage with no extra mark, also when an account has no weekly quota left ([#625](https://github.com/i098/Crewship/issues/625)).
- The agents profile installs the latest Ondine release, and public agent rules use it by default.
  Documentation diagrams use Ondine images with preserved source and flow-specific alternative text ([#645](https://github.com/i098/Crewship/issues/645)).
- The dashboard UI skill now requires Playwright measurements for skeleton layouts and a check for zero layout shift, with credit to Aiden Bai ([#646](https://github.com/i098/Crewship/issues/646)).

### Removed

- Remove the Updated badge from the README and preserve all other badges ([#567](https://github.com/i098/Crewship/issues/567)).

### Fixed

- `instagram_dm.py` no longer logs in by itself: a missing or dead session, or the first challenge, suspension, `feedback_required`, `login_required` or please-wait, halts the Instagram line until a human runs `resume`, and every failure names its exception class and endpoint ([#493](https://github.com/i098/Crewship/issues/493)).
- README feature and layout bullets now fit on one line, and the star history chart URL has a cache-busting parameter ([#517](https://github.com/i098/Crewship/issues/517)).
- A CI pool slot that hangs in `docker create` now times out and restarts, jobs no longer pull the runner image each time, and a watch timer restarts slots that stay without a container ([#543](https://github.com/i098/Crewship/issues/543)).
- The storage guard attempts alerts before scans or reclaim even when state initialization or pending writes fail.
  It retains saved requests for stable-ID retries.
  It derives state placement from the configured data directory.
  Only the lock owner changes saved state; only first-pass CRIT pressure enables reclaim ([#569](https://github.com/i098/Crewship/issues/569)).
- Configured data disks now supply supported native bulk defaults without replacing existing tool settings, credentials, or data.
  New bulk directories use mode `0700`; existing directory modes remain unchanged.
  Explicit environment values win, and bulk-only Herdr changes wait for its next start.
  Apply and preview reject unavailable pnpm configuration links before writing native defaults.
  Native settings that share a symbolic-link target retain all defaults after one apply.
  Legacy apply and preview tolerate a missing Bash startup file.
  User-manager defaults load before inactive services start without restarting active services.
  Pip cache overrides retain precedence across supported configuration locations and equivalent key spellings.
  Read-only pip override checks skip unavailable files, as pip does.
  Herdr reloads updated units before startup so stopped services do not inherit retired cache overrides.
  Worktree pruning tests disable automatic Git maintenance to prevent repository-copy races ([#570](https://github.com/i098/Crewship/issues/570)).
- Configured data filesystems now hold general syslog with native 128 MiB rotation, eight archives, mount protection and narrow access, while existing history remains intact.
  Validated activation now completes before old rotation ownership changes; unchanged service-enabled applies retry deferred or failed activation.
  Service-enabled applies clear failed activation limits and start an unchanged stopped or failed logger before rotation cleanup, without restarting a healthy logger.
  The setgid log directory preserves `adm` reader access after native rotation recreates the active file ([#571](https://github.com/i098/Crewship/issues/571)).
- Project database discovery now includes native configured Treehouse roots while keeping explicit root overrides, legacy home pools and registered projects ([#572](https://github.com/i098/Crewship/issues/572)).
- Fleet cleanup now covers native configured Treehouse roots and legacy home pools while preserving output-pruning checks and No-Mistakes reaper coverage ([#573](https://github.com/i098/Crewship/issues/573)).
- The mobile settlement test isolates host process metrics while keeping its no-change and changed-pane checks and the sidebar suite's subprocess entrypoint coverage ([#574](https://github.com/i098/Crewship/issues/574)).
- Fix the generated usage dashboard's Float64 metadata predicate and Pacific calendar labels for ClickHouse 25.12 ([#581](https://github.com/i098/Crewship/issues/581)).
- The preview and manual deploy commands in `site/README.md` now use the correct `site/` directory ([#595](https://github.com/i098/Crewship/issues/595)).
- The Spaces usage row now shows the Claude and OpenAI marks (Nerd Font glyphs) in place of the stand-in symbols `✳` and `◎` ([#600](https://github.com/i098/Crewship/issues/600)).
- `ci-pool.py watch` no longer fails on every run after an interrupted or failed write left its state file empty: the file is replaced whole, so a failed write keeps the old state, and an empty one counts as no sightings ([#602](https://github.com/i098/Crewship/issues/602)).
- A CI pool repository with `docker: dind` can set `userns: true`, so its sidecars run under an AppArmor profile that allows the user namespace rootless Docker needs on a host with `kernel.apparmor_restrict_unprivileged_userns=1`; other sidecars, job containers, and the host setting stay unchanged ([#607](https://github.com/i098/Crewship/issues/607)).
- Correct `frontend-ui-craft` rules 14 and 15 to match their reels: the equal-corner check applies to the play triangle only, and a skeleton is for known waits under about three seconds ([#609](https://github.com/i098/Crewship/issues/609)).
- The Herdr sidebar usage row shows the shared weekly quota left as the account mean that `omp usage` shows, labelled `7d left`, instead of an unlabelled mean of each account's fullest window of any length or model tier ([#614](https://github.com/i098/Crewship/issues/614)).
- The OMP usage patch applies again to the installed omp 18.12.1 release, so native usage collection and its tests work again ([#618](https://github.com/i098/Crewship/issues/618)).
- Herdr tests can no longer reach the live `default` session: pytest refuses an unstubbed `herdr`, and `tests/herdr-lab` runs real Herdr calls only in a named `fm-lab-*` session ([#622](https://github.com/i098/Crewship/issues/622)).
- `herdr-patch` keeps its image channel socket in `/run/user/<uid>`, so a cleaner of idle `/tmp` folders no longer turns the images of a long mosh connection into half-block characters ([#626](https://github.com/i098/Crewship/issues/626)).
- Document that the CI pool image has the `docker` CLI and `buildx`, and that a job that builds an image, such as `wrangler deploy` for a Worker with containers, needs `docker: dind` for a daemon ([#632](https://github.com/i098/Crewship/issues/632)).
- CI pool slots of one repository no longer share their tool, `~/.cache`, and cargo caches, so a job's cache cleanup cannot delete files under another job's running build. Each slot keeps its own caches in `<data_dir>/ci-pool/cache/<slot>/` ([#635](https://github.com/i098/Crewship/issues/635)).
- The messaging front desk accepts only structured replies or explicit actions, so raw model reasoning cannot become a text bubble.
  The worktree-prune tests disable automatic Git maintenance to prevent repository copy races in CI ([#638](https://github.com/i098/Crewship/issues/638)).
- The `ponytail-review` wrapper now requires exactly one approved positive verdict and permits only approved progress and information lines after Markdown normalization.
  Unapproved output, including cuts, negative summaries, findings, and free prose, fails the review ([#652](https://github.com/i098/Crewship/issues/652)).
- The iMessage bridge bounds startup requests, starts fallback transports in the background, and opens the listener without waiting for saved-message reads ([#654](https://github.com/i098/Crewship/issues/654)).
- Keep metered model calls independent of slow or failed usage collection, including process exit, with a bounded shutdown write and explicit unknown coverage ([#655](https://github.com/i098/Crewship/issues/655)).

## [0.4.4] - 2026-10-14

### Added

- A password gateway, on by default for a new host, opens the host's web pages over a Cloudflare Quick Tunnel: one password allows the visitor's address for 24 hours (`crewship.gateway.allow_hours`), and `--no-gateway` turns it off. An existing host keeps it off until `profiles.gateway: true` is set in `.local/host.yml` ([#369](https://github.com/i098/Crewship/issues/369)).
- The new public skill `openmontage` makes videos on demand with OpenMontage: install pointer, key names, `render.py` for Remotion props and three.js scenes (a rotating moon sample included), and `screencast.mjs`, which records a live site through Chrome DevTools into the cache dir that is pruned after 1 day; `render.py` can send a poster frame with `fm-imessage --image` (#392) ([#392](https://github.com/i098/Crewship/issues/392)).
- Add an Instagram front desk that answers DMs main has left alone for about 8 seconds ([#393](https://github.com/i098/Crewship/issues/393)).
- The `openmontage` skill now has a Motion and sound section (Remotion `spring()` for every move, synthesized click track, cuts on beat frames) and a Self-review step that scores segments and re-renders any under 8; `render.py --frames-every N` dumps review frames and `scenes/beat.tsx` is a spring and beat sample (#400) ([#400](https://github.com/i098/Crewship/issues/400)).
- The `instagram-dm` skill now has a reel curator, `reel_curator.py`, and a user timer `instagram-reel-curator.timer` that runs it three times a day: it pulls new reels from the accounts and hashtags in a host config file, skips any reel already logged or in the operator's thread, transcribes them with the `watch` skill, scores them with one `omp -p` call, rejects engagement bait, and shares at most three a day with one line (what, repo link, why), logging every pick and rejection in `reels.jsonl` (#403) ([#403](https://github.com/i098/Crewship/issues/403)).
- The new `slack-relay` skill relays important Slack messages to iMessage: it reads the slk TUI cache read-only, keeps DMs, mentions, thread replies, decisions, deadlines, asks and incidents with one `omp -p` call, sends at most one `fm-imessage` text per minute, dedupes by message ts and logs every kept or dropped message. It ships an opt-in `systemd --user` unit and never writes to Slack (#410) ([#410](https://github.com/i098/Crewship/issues/410)).
- A `site-walkthrough-video` skill records a smooth walk-through of a 3D or WebGL site, with real keyboard and mouse-look input, a planned route, spring turns, frame-exact parallel capture and a per-leg review ([#412](https://github.com/i098/Crewship/issues/412)).
- The `forgejo` profile now shows in [Configuration](docs/configuration.md#profiles) and [Default config](docs/default-config.md) with the other profiles, and `blueprint/config/default.yml` sets it to `false`. [Self-hosted Forgejo](docs/forgejo.md) also covers the published URL, security and removal ([#418](https://github.com/i098/Crewship/issues/418)).
- `fm-imessage --card` sends an iMessage app card: a `choice` card whose tap files `[iMessage card pick] <key>: <choice>` with the Firstmate inbox and edits the bubble in place, or a `bars`, `timeline` or `table` card drawn on its page. A card-only listener serves the pages by single-use, expiring tokens behind a named Cloudflare tunnel (`crewship.imessage.cards`) ([#419](https://github.com/i098/Crewship/issues/419)).
- The opt-in `forgejo` profile (`crewship.profiles.forgejo`) runs a self-hosted Forgejo; [Self-hosted Forgejo](docs/forgejo.md) describes it. The recipe (`blueprint/ansible/tasks/forgejo.yml`) runs the latest Forgejo release on `127.0.0.1:20250` with SQLite after its checksum and its release-key signature match. It publishes Forgejo to the tailnet over HTTPS when Tailscale runs with HTTPS certificates enabled, and otherwise keeps the installed tailnet URL; it uses the loopback URL only on a first install. It creates an admin account with a host-local password, and dumps Forgejo every night with a copy of its secret files, which a restore needs. Before a new release first starts, the installed release makes the same dump, also when the service is stopped; if that dump fails, the apply stops and Forgejo keeps the installed release ([#420](https://github.com/i098/Crewship/issues/420)).
- `forgejo-github-push enable <owner>/<repo> <GitHub URL>` makes a Forgejo repository push every branch that a push created or updated, except `main`, `master` and its default branch, to GitHub. Each push leases on the commit the hook last pushed for that branch, so a rebased branch replaces it, but a commit made only on GitHub (Update branch, a suggestion, a web edit) is never overwritten: the push fails and each later push of the branch warns until the branch merges it. It never pushes `main`, `master`, the default branch or tags and never deletes a GitHub branch. A push that fails three times for another reason stays as a failed `forgejo-github-push-*` user unit. Forgejo mirrors are off, also in the API, because a push mirror deletes every GitHub branch that it does not push ([#421](https://github.com/i098/Crewship/issues/421)).
- Apply installs `forgejo-axi` with the `agents` profile. With the Forgejo recipe and the `agents` profile, apply also creates a scoped Forgejo token once in a mode-600 file, and gives the no-mistakes daemon the Forgejo base URL and that token through a drop-in. Apply never restarts the daemon; a restart loads the drop-in ([#422](https://github.com/i098/Crewship/issues/422)).
- `crewboard github-sink` posts the messages of crew board topics (default `fleet`) as one batched REST comment on a GitHub issue every 5 minutes or more, through the host's gh login ([#427](https://github.com/i098/Crewship/issues/427)).
- With the crew board on, a message on the board's `fm` topic wakes Firstmate within about a second, and an optional `config/board-doorbell` rings the pane of a task that gets a `task/<id>` message, through the carried Firstmate patch `0004-watch-crewboard-event-source.patch` ([#434](https://github.com/i098/Crewship/issues/434)).
- iMessage cards have a `text` kind that reads the `fm-text-card` lines, `fm-text-card --send` and `eta_timeline.py --send` can send a text or timeline card, and the docs name the Mac limit of app cards ([#435](https://github.com/i098/Crewship/issues/435)).
- An opt-in `jj` profile installs the latest Jujutsu release for agents, verified against its published digest, and [docs/jj.md](docs/jj.md) explains how to use it colocated with git, with one `jj workspace` per worktree and without `jj undo` or `jj op restore` ([#448](https://github.com/i098/Crewship/issues/448)).
- The eta-timeline skill shows the percent complete of each bar: an optional `percent` per item, else the elapsed share of start..end, with a darker fill for the done part ([#451](https://github.com/i098/Crewship/issues/451)).
- The new public skill `repo-readme` teaches the README structure for a repository: hero with badges and a Sponsor button, a live screenshot, present-tense features, quick start, a how-it-works diagram, repository layout and license, with a fill-in template and a polish checklist (community files, templates, topics, social preview). (#458) ([#458](https://github.com/i098/Crewship/issues/458)).
- `bunx crewship`, `install.sh` and `./ship.sh dock` show one checklist of every opt-in feature on a new host, and `--with NAMES` answers it (`--with none` for the core only). `--with` replaces `dock --board`, and a choice brings what it needs, such as `docker` for `fleet_guards` ([#461](https://github.com/i098/Crewship/issues/461)).
- The opt-in `fdu` profile installs [fdu](https://github.com/jlevy/fdu), a fast gitignore-aware `du` for large worktrees, with `uv tool install` and moves it to the newest release on each apply ([#470](https://github.com/i098/Crewship/issues/470)).
- At CRIT the storage guard also removes gitignored build output (`node_modules`, `.venv`, `target`, `dist`, `.next`, ...) that nothing changed for 7 days in Treehouse pool worktrees. `find` discovers it, and the opt-in `fdu` profile only supplies the sizes in the report (`du` otherwise). It never touches tracked files, uncommitted or unpushed work, or paths outside the pools, and `worktree-prune.sh --dry-run` lists what it would remove ([#471](https://github.com/i098/Crewship/issues/471)).
- The install checklist and `--with` offer the `fdu` profile ([#483](https://github.com/i098/Crewship/issues/483)).
- The opt-in install checklist (`bunx crewship`, `install.sh --with`, `SETUP.md`) now offers `forgejo`, the self-hosted Forgejo. A container worker image does not offer it, because Forgejo runs as a host service ([#486](https://github.com/i098/Crewship/issues/486)).

### Changed

- The worker image is smaller: a `builder` stage provisions it and deletes the files no worker process reads (apt indexes, node C headers, source maps and TypeScript declarations in the npm tool prefixes, omp's unused `onnxruntime-web` and extra `onnxruntime-node`, the AVX2 copy of omp's native addon, and Mesa's GPU driver and LLVM), strips the symbol tables of the rustup toolchain and the npm native addons, and the `worker` stage copies the result into one layer; `.dockerignore` also keeps the Dockerfile, the changelog, the contributor and setup guides and `install.sh` out of the build context ([#391](https://github.com/i098/Crewship/issues/391)).
- **Breaking:** the `shared_postgres` profile no longer runs one host-wide Postgres container. Each project gets one dev database container of the engine its own compose file names (Postgres, MySQL, MariaDB or Redis), shared by all of its worktrees, with its own port, password and data volume, and the seeder writes `DATABASE_URL` or `REDIS_URL` into each worktree's `.env.local`. The `crewship-shared-postgres` container and its volume stay untouched; [Project databases](docs/shared-postgres.md#migrate-from-the-host-wide-postgres) explains how to move the data ([#426](https://github.com/i098/Crewship/issues/426)).
- `fm-imessage --card` sends a Spectrum app bubble with its live view again by default (`"app": false` keeps the link), the bubble shows the title and one status line, and the card page looks like an iOS view in light and dark mode ([#432](https://github.com/i098/Crewship/issues/432)).
- `fm-text-card --send` and `eta_timeline.py --send` send their PNG image by default again; `--card` sends a `text` or `timeline` card first, with the PNG as the fallback ([#438](https://github.com/i098/Crewship/issues/438)).
- The per-project database CI steps, Ansible task names and `scripts/ship.py` errors now say "project database" instead of "shared Postgres" ([#447](https://github.com/i098/Crewship/issues/447)).
- The architecture, agent-host-move, agents/architecture and fleet-guards docs now link to the per-project dev databases instead of the host-wide Postgres ([#449](https://github.com/i098/Crewship/issues/449)).
- The public skills and rules install only when `profiles.public_skills` is true. A new host gets none; a host that already has them keeps them, and turning the key off deletes nothing ([#460](https://github.com/i098/Crewship/issues/460)).
- A new host config now turns on only `agents` and `firstmate`. `development`, `docker`, `chat` and `gateway` are off until chosen, and `./ship.sh dock` no longer opens the gateway or takes `--no-gateway`. A host config that already sets these keys keeps its values; a host config with no `chat` key no longer gets the chat clients ([#462](https://github.com/i098/Crewship/issues/462)).
- The Koncreet host hardening toolkit installs only with `profiles.koncreet`, which the install checklist offers. A new host config turns it off; a host config without the key keeps getting it ([#472](https://github.com/i098/Crewship/issues/472)).

### Fixed

- The installer no longer fails when GitHub's API rate limit (60 requests an hour per IP without `GITHUB_TOKEN`) is spent: `scripts/provisions.py` then reads each tool's latest release from github.com's public pages (the `releases/latest` redirect, the release Atom feed and the asset list with its SHA-256 digests), which have no request budget, and prints a message saying so ([#397](https://github.com/i098/Crewship/issues/397)).
- The `./ship.sh chart` preview no longer fails on a fresh host with a missing `~/.config/btop` directory, because the btop configuration preview now waits for the directory ([#398](https://github.com/i098/Crewship/issues/398)).
- The release lookups in `scripts/provisions.py` now retry a dropped connection, a TLS EOF, a timeout or a 5xx answer three times, as the downloads already did, so one network hiccup no longer fails an apply ([#399](https://github.com/i098/Crewship/issues/399)).
- The reel curator now sends only English reels: before scoring it drops a reel whose spoken language (the language the `watch` skill names, else a common-word count) or caption is not English, and logs it as `non-english:<lang>` (#406) ([#406](https://github.com/i098/Crewship/issues/406)).
- The link preview image (`site/public/og.png`) and the repository social preview show only "Crewship", without the subtitle (#416) ([#416](https://github.com/i098/Crewship/issues/416)).
- `fm-imessage --card` now sends the card page's URL as a plain text by default, which iMessage shows as a link preview from the page's Open Graph tags, because a Spectrum app card shows only a plain balloon on a phone without the Spectrum app; `"app": true` still sends the app bubble ([#428](https://github.com/i098/Crewship/issues/428)).
- The project database seeder now removes the legacy `DATABASE_URL` line, left by the old host-wide Postgres, from the `.env.local` of a Redis project ([#442](https://github.com/i098/Crewship/issues/442)).
- An iMessage card now opens as a full-width sheet, and its page fills the width Messages gives it: text, bars and tables reflow with no fixed width. A card is a live bubble only with `"live": true`; the live bubble has a narrow width that Messages sets (#443) ([#443](https://github.com/i098/Crewship/issues/443)).
- An apply for a second account, such as a sandbox or test home, no longer repoints the host's `/usr/local/bin/herdr` and `/usr/local/bin/herdr-patch` links. Apply changes these links only when they are missing or already point into the account's own home, and verify checks them only for that account ([#464](https://github.com/i098/Crewship/issues/464)).

## [0.4.3] - 2026-10-13

### Added

- `fm-imessage --image PATH [caption]` sends a photo (png, jpg or webp) over the Photon line, downscaling a side over 2048 px and queueing it like a text bubble ([#340](https://github.com/i098/Crewship/issues/340)).
- Hosts with the `firstmate` profile now install a user timer that types a nudge into main Firstmate's herdr pane when an operator note or a wake waits too long, so an idle main session starts a turn again ([#346](https://github.com/i098/Crewship/issues/346)).
- The stall nudge also wakes main Firstmate once for each Lavish board answer that nobody replied to within 300 s, and now nudges after an operator note waits 45 s, checking every 15 s with at least 120 s between nudges ([#349](https://github.com/i098/Crewship/issues/349)).
- The `firstmate` profile installs a registered Firstmate check that clears stale unsent text from a second mate input box and rings its doorbell ([#356](https://github.com/i098/Crewship/issues/356)).
- Hosts that set `crewship_gh_replies_account` get a registered Firstmate check that wakes main when someone else comments on or reviews a GitHub PR or issue ([#357](https://github.com/i098/Crewship/issues/357)).
- Hosts with the `firstmate` profile now install `fm-usage-brief`, `fm-usage-remind` and `fm-text-card`: while the owner texts Firstmate, the stall nudge service sends an image card of Claude and Codex use, server load, RAM and disks at most once an hour, and `fm-text-card` renders any short update as an image card ([#358](https://github.com/i098/Crewship/issues/358)).
- Add `scripts/new-issue`, which files issues that follow the issue forms ([#360](https://github.com/i098/Crewship/issues/360)).
- The new public skill `eta-timeline` answers an ETA question with a timeline chart: an 840 px wide PNG in the operator's local time, with one bar per item, done dots, moved items in amber and a "now" line, rendered by headless Chrome (#375).
  The new public skill `usage-card` answers usage, quota, resource, server load and disk questions with the `fm-usage-brief --png` card (#375) ([#375](https://github.com/i098/Crewship/issues/375)).
- The new public skill `manim` explains math and diagrams with Manim animations: a scene template and `render.py`, which renders mp4 or gif into one cache dir pruned after 1 day and can send the gif with `fm-imessage --image` (#381) ([#381](https://github.com/i098/Crewship/issues/381)).
- Added the public `instagram-dm` skill: it reads the agent Instagram DMs with `instagrapi` and passes each shared post link, normalised to the `/reel/` form, to yt-dlp. It is read-only by default ([#382](https://github.com/i098/Crewship/issues/382)).
- The `instagram-dm` skill now uses `instagrapi` (saved session, email-code login). With `crewship_instagram_dm_operator` set, a `firstmate` host keeps a realtime listener and a backstop poll timer that file each new DM from the operator with the Firstmate inbox (read receipt included), and installs `fm-insta-reply` to answer by text, reaction or typing indicator. No media is downloaded ([#385](https://github.com/i098/Crewship/issues/385)).

### Changed

- The how page explains movement, the shape list, windows and zoom, and the harbor shows a one-time zoom hint ([#338](https://github.com/i098/Crewship/issues/338)).
- The landing page folder `harbor/` is now `site/`, `proxy-fixes/` is now `blueprint/patches/proxy-fixes/`, and `SECURITY.md`, `SUPPORT.md`, and `CODE_OF_CONDUCT.md` are now in `.github/` ([#348](https://github.com/i098/Crewship/issues/348)).
- Split `blueprint/ansible/group_vars/all.yml` into one file per topic under `blueprint/ansible/group_vars/all/`, with the same variables and values ([#352](https://github.com/i098/Crewship/issues/352)).
- The top level is grouped into `blueprint/` (the Ansible playbook and everything it provisions), `apps/` (`crewboard`, `imessage`, `fleet-secrets`), and `tools/` (`npm`, `herdr-patch`, `dia-debug`); `install.sh` moves private skills and rules from an older install into `blueprint/skills/private/` and `blueprint/rules/private/` ([#354](https://github.com/i098/Crewship/issues/354)).
- The installer puts omp and the agent CLIs in place with `bun add -g` instead of npm, `~/.bun/bin` is on the `PATH` of shells and user units, and the docs show `bunx crewship` first with `npx crewship` and `pnpm dlx crewship` as the other ways to run the package ([#367](https://github.com/i098/Crewship/issues/367)).
- The worker image drops the package-manager caches (npm, uv, bun, pip, cargo), the rustup docs, the onnxruntime-node binaries for other operating systems and CPU architectures, and the onnxruntime CUDA and TensorRT providers, which makes it smaller with the same tools; `.dockerignore` also keeps `docs/`, `changelog.d/` and all tests except `tests/container-smoke.sh` out of the build context ([#377](https://github.com/i098/Crewship/issues/377)).

### Fixed

- Every `pr-preview` board now ends with a roomy approval form: stacked choices, a full-width comment box for "Request changes", a right-aligned Send, and pass badges that no longer wrap (#342) ([#342](https://github.com/i098/Crewship/issues/342)).
- The iMessage bridge tests pick their ports without collisions under xdist, so the bridge no longer exits at start with EADDRINUSE ([#344](https://github.com/i098/Crewship/issues/344)).
- The `herdr-patch` escape-sequence patterns spell their byte ranges as explicit hex escapes, which closes CodeQL alerts #6 and #7; the bytes they match do not change ([#365](https://github.com/i098/Crewship/issues/365)).
- `npx crewship` and `npm i -g crewship` no longer fail with EBADPLATFORM on macOS and Windows (#368): the package has no `os` restriction, `crewship --version` prints the package version, and off Ubuntu the launcher prints one line saying to run it on the server ([#368](https://github.com/i098/Crewship/issues/368)).
- Two iMessage tests no longer fail at random: the fake Photon's outage counter was overwritten by the bridge (#374) ([#374](https://github.com/i098/Crewship/issues/374)).

## [0.4.2] - 2026-10-11

### Added

- `npx crewship update` installs the newest release over a host, keeping its `.local/` files, and migrates a v0.4.0 host's tool links and removed `host.yml` keys first; the README says so ([#284](https://github.com/i098/Crewship/issues/284)) ([#284](https://github.com/i098/Crewship/issues/284)).
- The crewship.si harbor plays positional ambient sound after the first click or tap: sea and surf, the fountain, wind in the trees, the ship's creaking timbers, fire in the rooms, and distant gulls, each fading with distance, with a speaker button that mutes it and remembers the choice ([#287](https://github.com/i098/Crewship/issues/287)).

### Changed

- The harbor island now rises into gentle, slope-shaded hills with curving dirt roads, and its grass, sand and roads blend without square patches ([#203](https://github.com/i098/Crewship/issues/203)).
- The harbor ship's deck stairs are now a steep companionway ladder with thick handrails on posts, and the ship's wheel stands on the cabin roof with eight handled spokes, a hub, and a pedestal.
  The upright wheel now runs across the ship, with its axle along the keel and its handles and hub cap pointing aft toward the helmsman.
  Keyboard and touch movement now use short segments so slow frames do not skip the ladder treads.
  The exterior now reduces glyph detail during slow rendering or missed frames to keep the stern scene responsive.
  The CI checks now cover exterior and interior detail adaptation and use fixed grids for browser geometry checks ([#222](https://github.com/i098/Crewship/issues/222)).
- CI runs the Python tests in parallel with pytest-xdist, splits the slow harbor scene test into six parts, overlaps the shared Postgres smoke with the tests, and runs only the iMessage tests, plus a short core, for a pull request that changes only `imessage/` ([#269](https://github.com/i098/Crewship/issues/269)).
- README setup is one line to paste into your AI, and Opus 5.5 falls back to Fable 5.1 at medium thinking ([#274](https://github.com/i098/Crewship/issues/274)).
- The harbor scene now starts zoomed out like Cmd-minus once and stays that way while you walk: glyphs are 0.9 times as tall up to 2560 by 1440 stages (larger stages get taller glyphs to cap the cell count) and drawn on whole device pixels, and a slow outdoor frame casts every other row instead of growing the glyphs (only a touch device whose fields and shadows are already off may grow them, up to 1.5 times, and they shrink back when frames are fast) ([#278](https://github.com/i098/Crewship/issues/278)).
- The README puts How it works below Quick start, and its Show all features and Default config lists moved to docs/features.md and docs/default-config.md ([#280](https://github.com/i098/Crewship/issues/280)).
- The daily sponsors workflow and its script are removed, because the README has no Sponsors section for them to fill ([#282](https://github.com/i098/Crewship/issues/282)) ([#282](https://github.com/i098/Crewship/issues/282)).
- The harbor's house windows, ship cabin windows and gun ports are now openings you see through both ways: the outside from inside each room, and the lit room from outside ([#291](https://github.com/i098/Crewship/issues/291)).
- The README and the crewship.si landing page link each feature and section to its docs page again, and the Architecture page is linked from both ([#293](https://github.com/i098/Crewship/issues/293)) ([#293](https://github.com/i098/Crewship/issues/293)).
- README tagline is now "This makes it super easy to start using agents in the cloud, enjoy!", and the landing page and npm package descriptions match it ([#296](https://github.com/i098/Crewship/issues/296)).
- The `pr-preview` skill renders every board in GitHub dark mode only ([#304](https://github.com/i098/Crewship/issues/304)).
- The harbor's how page now leads with a plain explanation that the scene is drawn natively by a ray caster on a 2D canvas, with a step diagram, the shapes used and measured frame costs ([#311](https://github.com/i098/Crewship/issues/311)).
- On a desktop, the harbor on crewship.si now casts and draws its rows in web workers on the other cores, so slow frames never cost rows, shadows or glyph size; only a slow phone turns shadows off and then grows glyphs, never past 1.5 times ([#314](https://github.com/i098/Crewship/issues/314)).
- Sync the recipe with the current host: the home model runs Opus 5.5 at high thinking, OpenAI requests use the priority tier, ordinary crew work goes to Sonnet 5.5 first and to Sol 6.1 only when the Anthropic quota is exhausted, and secondmates run Opus 5.5 at medium thinking ([#334](https://github.com/i098/Crewship/issues/334)).

### Fixed

- The night clouds now use soft, wind-stretched noise with holes, tapered cumulus sides, cached moon-side light, and dim stars through thin cloud ([#223](https://github.com/i098/Crewship/issues/223)).
- The installer installs GitHub's source archive of the tag, after checking its commit against the tag, when a release has no install artifact; releases are immutable, so the release steps now attach the artifact to the draft before publishing ([#265](https://github.com/i098/Crewship/issues/265)).
- Pushes to main no longer cancel each other's CI runs, so the README badge reflects the latest run ([#276](https://github.com/i098/Crewship/issues/276)).
- The pre-rename migration no longer stops `crewship update` on a v0.4.0 host: the share directory the installer already created (releases, tools, lock file) no longer counts as a clash, and the old directory is merged into it ([#284](https://github.com/i098/Crewship/issues/284)) ([#284](https://github.com/i098/Crewship/issues/284)).
- Fence posts and signs in the harbor scene keep level ground under them again: trees no longer build the ground-seating grid before the rest of the scenery stands ([#288](https://github.com/i098/Crewship/issues/288)).
- The harbor page footer keeps its Architecture link, and the code-quality gate no longer reports a coupling regression for it ([#298](https://github.com/i098/Crewship/issues/298)).
- The harbor page now gives every scene object a doc sign, so the iPhone WebKit check passes again, and a sign with no entry no longer throws ([#300](https://github.com/i098/Crewship/issues/300)).
- Inside the ship's cabin on crewship.si, the ambient sound now comes from the right place: the listener and the cabin lantern use the world position and heading, not the room's own turned frame ([#322](https://github.com/i098/Crewship/issues/322)).
- CI no longer starts two runs for one PR head when a label is added; the changelog check now runs as its own workflow ([#330](https://github.com/i098/Crewship/issues/330)).

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

[Unreleased]: https://github.com/i098/Crewship/compare/v0.4.8...HEAD
[0.4.8]: https://github.com/i098/Crewship/releases/tag/v0.4.8
[0.4.7]: https://github.com/i098/Crewship/releases/tag/v0.4.7
[0.4.6]: https://github.com/i098/Crewship/releases/tag/v0.4.6
[0.4.5]: https://github.com/i098/Crewship/releases/tag/v0.4.5
[0.4.4]: https://github.com/i098/Crewship/releases/tag/v0.4.4
[0.4.3]: https://github.com/i098/Crewship/releases/tag/v0.4.3
[0.4.2]: https://github.com/i098/Crewship/releases/tag/v0.4.2
[0.4.1]: https://github.com/i098/Crewship/releases/tag/v0.4.1
[0.4.0]: https://github.com/i098/Crewship/releases/tag/v0.4.0
[0.3.0]: https://github.com/i098/Crewship/releases/tag/v0.3.0
[0.2.0]: https://github.com/i098/Crewship/releases/tag/v0.2.0
[0.1.0]: https://github.com/i098/Crewship/releases/tag/v0.1.0
