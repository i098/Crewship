# omp configuration

omp (`@oh-my-pi/pi-coding-agent`) is the agent harness Crewship installs. This guide covers what the recipe sets up, how to sign in, and how to change models and settings. For every omp setting, run `omp config list` or read omp's own docs.

## What the recipe sets up

With the `agents` profile on, `./ship.sh launch`:

1. Installs the latest published omp, resolved from the npm registry on every apply, plus the omp plugins ponytail, i-have-adhd and caveman, upgraded on every apply (see [Dependencies](dependencies.md#latest-releases)).
2. Copies [`blueprint/config/omp.yml`](../blueprint/config/omp.yml) to `~/.omp/agent/config.yml` (directory `0700`, file `0600`), and [`blueprint/config/omp-lsp.json`](../blueprint/config/omp-lsp.json) to `~/.omp/agent/lsp.json`, which disables the markdown language server (marksman): it costs each session about 90 MB, and markdown diagnostics add nothing to agent work.
   Every apply also merges [`blueprint/config/omp-models.yml`](../blueprint/config/omp-models.yml) into `~/.omp/agent/models.yml`, preserving user providers and unshipped model keys.
   Shipped override keys take precedence over existing values.
   It reads the first existing configuration in omp's order: `models.yml`, `models.yaml`, then legacy `models.json`.
   The installed Bun parser preserves YAML 1.2 scalar types and reads legacy JSONC comments and trailing commas.
   When an existing model file needs parsing, missing Bun makes check mode report the installation prerequisite and skip the dependent merge.
   Normal apply fails if that parser is unavailable.
   When the merge changes the configuration or creates `models.yml`, it writes JSON, a YAML 1.2 subset, to preserve scalar types.
   It leaves the other source files unchanged.
   See [Default config](default-config.md) for the Codex context windows.
   omp limits the effective window to the provider's supported input window.
   The config seed enables `extendedContext: true`; existing hosts must enable it in their own config.
3. Installs the extension `~/.omp/agent/extensions/crewship-herdr-sidebar.ts`, which feeds the Herdr Agent sidebar the session topic, the pane's short name, and the pull request line (pull request, issue and diff size). Every apply rewrites it. See [Herdr sidebar](herdr.md).
4. Installs the extension `~/.omp/agent/extensions/aa-mode-icons.ts` from [`blueprint/config/omp-status-icons.ts`](../blueprint/config/omp-status-icons.ts). Every apply rewrites it. See [Status line icons](#status-line-icons).
5. Installs the extension `~/.omp/agent/extensions/fm-no-pattern-kill.ts` from [`blueprint/config/omp-no-pattern-kill.ts`](../blueprint/config/omp-no-pattern-kill.ts). It blocks `pkill`, `killall` and kill-by-`pgrep` commands in every omp session: all agents on the host run as one user and each worker's brief sits in its command line, so a name or pattern can match other workers. Kill a process by the PID you started instead. Every apply rewrites it. It is a best-effort seatbelt, not a barrier: it matches the command text, so it lets through an absolute path (`/usr/bin/pkill`), a kill whose targets come from `pidof`, `ps | grep` or a `pgrep` loop, and the list form in an eval cell (`subprocess.run(["pkill", ...])`), and it blocks read-only mentions such as `grep -rn pkill docs/`. Removing worker briefs from the command line is the real fix and is out of scope for this recipe.
   The same extension checks GitHub write targets; see [GitHub write guard](#github-write-guard).
6. Installs the extension `~/.omp/agent/extensions/crewship-quality-gate.ts` from [`blueprint/config/omp-quality-gate.ts`](../blueprint/config/omp-quality-gate.ts), the sentrux and fallow check at the end of every agent turn. Every apply rewrites it. See [Quality gate](#quality-gate).
7. Sets up omp as the no-mistakes pipeline agent. See [no-mistakes pipeline agent](#no-mistakes-pipeline-agent).
8. Installs the skills in [`blueprint/skills/`](../blueprint/skills/) for omp and Claude Code. See [Skills](#skills).
9. Installs [`blueprint/config/AGENTS.md`](../blueprint/config/AGENTS.md) as the global instructions of Claude Code, omp and Codex, when `profiles.agent_instructions` is on. See [Global instructions](#global-instructions).
10. Installs the omp rules in [`blueprint/rules/`](../blueprint/rules/) to omp's global rules folder. See [Rules](#rules).

The `config.yml` and `lsp.json` copies are first-write-only.
The recipe preserves existing settings except the two keys required by [Status line icons](#status-line-icons).
Model overrides follow the merge policy above.
See [Updating an existing host](#updating-an-existing-host).

No credentials are installed. You sign in on each host.

## Sign in

1. Start omp as the account that runs the fleet:

   ```bash
   omp
   ```

2. On first run, choose a theme or use the displayed skip option, then select a provider in the setup screen.
   Complete these screens before entering slash commands at the normal prompt.
   Open the printed login URL in your own browser.
   If omp requests a returned code or redirect URL, enter it directly in the terminal.
   Follow the provider's remote-login instructions; your browser's localhost is not the remote server.

3. At the normal prompt, sign in to each other provider you use in `modelRoles` or the [crewmate and gate tiers](default-config.md).
   If you skipped provider setup, sign in here too.
   For Anthropic:

   ```text
   /login anthropic
   ```

   Run `/login` with no argument to pick from every provider. Logins are per provider: signing in to `anthropic` does not sign in to any other provider.

4. Optional: run `/login anthropic` again with another account. omp pools several accounts of the same provider and rotates between them.

Stored credentials live in `~/.omp/agent/agent.db`. An environment variable such as `ANTHROPIC_API_KEY` also works, but a stored login takes precedence over it. Never copy `agent.db` from another host; see [Security](security.md).

## Model access

omp talks straight to the provider APIs. `blueprint/config/omp.yml` maps every model role to a provider-prefixed id (such as `anthropic/claude-sonnet-5`), and `retry.fallbackChains` uses provider-prefixed ids too. A fresh host needs no router, gateway, or proxy, and binds no extra port. Account rotation is built into omp, so more than one account is not a reason to add a gateway. Bringing back a router or gateway is an explicit operator decision; the header of `blueprint/config/omp.yml` records this rule.

## Model roles

Each key under `modelRoles` picks the model for one kind of work. A role value is `provider/model-id`, optionally with a thinking suffix such as `:off`, `:high`, `:xhigh`, or `:auto`.

| Role | Used for |
| --- | --- |
| `default` | The main session model. |
| `smol`, `slow` | Fast and deep alternatives. `cycleOrder` sets the order the model switcher cycles through (`smol`, `default`, `slow`, `subagent` here). |
| `task` | Subagents spawned from a session. |
| `plan`, `commit`, `tiny`, `vision`, `memory` | Planning, commit messages, small helper calls, image input, and memory. |
| `advisor` | The advisor model. See [Advisor](#advisor). |

`blueprint/config/omp.yml` also defines custom roles (`designer`, `subagent`, `Kimi`). The current model for each role is in [`blueprint/config/omp.yml`](../blueprint/config/omp.yml).

`retry.fallbackChains` lists, for a model id or role, the models to try when it keeps failing (rate limits, quota, outages). `retry.maxDelayMs` caps the retry backoff; a provider-stated wait longer than that fails fast instead of sleeping.

## Changing models

On one host, now: open `/model` in a session and use the **Roles** view, or edit `modelRoles` in `~/.omp/agent/config.yml`. Check the result with:

```bash
omp config get modelRoles
omp models --kind chat      # models you can assign
```

For every future host, edit [`blueprint/config/omp.yml`](../blueprint/config/omp.yml) in this repository and commit it. New hosts get it on their first apply. Existing hosts do not; see below.

For one repository only, create `<repo>/.omp/config.yml` with the keys to override. It is merged over the global config when omp starts in that directory. Arrays replace the global value instead of appending to it.

## Advisor

The advisor is a second model that reviews each completed turn and can add notes. `blueprint/config/omp.yml` picks its model (`modelRoles.advisor`) and sets `advisor.enabled: false`, so the advisor is off. Turn it on for one session with `/advisor on`, or for every session with `advisor.enabled: true` in `~/.omp/agent/config.yml`.

Firstmate turns it on for omp crewmate and scout launches only, never secondmates, by layering the seeded `blueprint/config/omp-crew-overlay.yml` over `~/.omp/agent/config.yml` (see [Seeded Firstmate and OMP configuration](agents/architecture.md#seeded-firstmate-and-omp-configuration)). Crews get fable 5.1 at low thinking, with `providers.anthropic.serverSideFallback: false`, because Anthropic rejects the global server-side fallback on every advisor call with a 400. They never wait on it, because the overlay's `syncBacklog: "off"` overrides the global `"1"`. Turns that land during a review batch into the next call, and the advisor interrupts at most once per 10 turns. omp has no every-N-turns setting.

The omp that the no-mistakes daemon spawns gets its own advisor from a separate overlay, not from Firstmate. See [no-mistakes pipeline agent](#no-mistakes-pipeline-agent).

## Other seeded preferences

`blueprint/config/omp.yml` also sets the theme (`dark-rose-pine`), a custom status line (see [Status line icons](#status-line-icons)), `textVerbosity: low`, `readLineNumbers: true`, hidden thinking blocks (`hideThinkingBlock: true`), steering, follow-up and interrupt modes, vim mode in the editor (`tui.vimMode`), the OpenAI priority service tier (`tier.openai: priority`), and at most 128 parallel subagent tasks (`task.maxConcurrency`). Memory uses the mnemopi backend (`memory.backend: mnemopi`) with no embeddings, the `smol` model for its own calls, and polyphonic recall, enhanced recall and proactive linking on. Change a single value with `omp config set <key> <value>`, or use `/settings`.

## Status line icons

The status icons extension puts the mode indicators and the configured hooks on the main status line as one row of evenly spaced Nerd Font icons, instead of one extension status line per plugin and a separate hooks line:

- Modes: caveman, ADHD (`i-have-adhd`) and ponytail. An icon shows if and only if its mode is on in that omp session; an off mode has no icon, because omp strips all styling from extension statuses and a dimmed icon would look the same as a lit one. The extension takes over the `ponytail` and `i-have-adhd` status keys those plugins set, so their own text statuses no longer show; each plugin clears its key when its mode turns off. A plugin configured with `hideStatus` never sets its key, so its icon stays hidden even while the mode is on.
- caveman has no omp extension, and omp does not run the Claude Code hooks the `caveman@caveman` plugin ships, so nothing records caveman's state. The icon works it out from the session itself: caveman is on at the start when the session's system prompt names `skill://caveman` (an always-apply rule that keeps it in force), then every prompt you send is read with caveman's own parser from the installed plugin (`src/hooks/caveman-parse.js`), so "stop caveman", "normal mode" and `/caveman off` hide it, and "talk like caveman" or invoking the caveman skill (`/caveman`) shows it again. A skill invocation is read with its arguments, so `/skill:caveman off` hides it, and the icon updates at the end of that turn. Moving to another point in the session tree re-reads that branch. Without the plugin installed the icon never shows. It reflects what you asked for in the session, not whether the model actually writes that way.
- Hooks: the hooks in `~/.claude/settings.json` and `<cwd>/.claude/settings.json`. Known hooks get their own icon; the rest show as one icon followed by their count.

The file is installed as `aa-mode-icons.ts` on purpose: omp loads extensions in name order, and the extension must wrap the status API before the ponytail and ADHD plugins set their statuses.

The row needs two keys in `statusLine`: `status` in `leftSegments`, which shows extension statuses on the main line, and `showHookStatus: false`, which drops the separate hooks line. omp reads `leftSegments` only when `preset` is `custom`. `blueprint/config/omp.yml` seeds all three. On a host whose `~/.omp/agent/config.yml` already exists and uses `preset: custom`, every apply appends `status` to `leftSegments` when it is missing and sets `showHookStatus` to `false`, and leaves every other key alone. A config with any other preset, or none, is left untouched: switch it to `preset: custom` by hand to get the row. Start a new omp session to see the change. Check the result with:

```bash
omp config get statusLine.leftSegments
omp config get statusLine.showHookStatus
```

## GitHub write guard

The existing `fm-no-pattern-kill.ts` extension checks literal `gh` and `gh-axi` commands before omp runs a bash or eval tool.
It covers issue mutations, including issue transfers and both repositories in a transfer.
It also checks `gh-axi issue subissue add|remove`; `subissue list` remains read-only.
Each write needs `-R owner/repo`, `--repo owner/repo`, or a supported positional GitHub URL.
`gh-axi` requires a repository flag because its issue selectors are numbers, not URLs.
The guard checks every issue selector and each parent, sub-issue, or blocking relationship target.
Recognized reads and help commands pass unchanged.
Unknown flags or invalid boolean values block API commands because the guard cannot safely determine whether they write.

The guard also checks API writes to `repos/owner/repo/issues`, including issue comments and other child paths.
It recognizes `-X`, `--method`, and the positional HTTP method in `gh-axi api`.
For `gh api`, fields and input imply POST unless an explicit method overrides it.
`gh-axi api` defaults to GET even with fields or input.
API targets must use literal repository names, not `{owner}` or `{repo}` placeholders.
GraphQL issue mutations and shared mutations that can change issues require `CREWSHIP_GITHUB_APPROVED_REPO`, even when the task contract is set.
The value names the explicitly approved target repository because the guard cannot resolve GraphQL node IDs.
File and stdin GraphQL payloads also require this approval because the command-text guard cannot inspect their contents.

Missing-target blocking is always active.
Repository mismatch checks apply only when `CREWSHIP_GITHUB_REPO=owner/repo` is set in the environment that starts the task's omp session.
Crewship has no repository-aware task launcher here; Firstmate owns that launch path and must supply this variable separately.
Set `CREWSHIP_GITHUB_APPROVED_REPO=owner/repo` there only after approval for that exact additional repository.
Both values compare without letter case.
`GH_REPO`, the working directory, shell comments, and URLs in titles or bodies do not satisfy an explicit target.

The normal agent apply installs the guard for host and worker omp sessions.
To update only this guard from a verified checkout, run `install -m 0644 blueprint/config/omp-no-pattern-kill.ts ~/.omp/agent/extensions/fm-no-pattern-kill.ts`.
Start a new omp session to load the update; existing sessions retain their loaded extension.
Run `uv run pytest tests/test_omp_github_target.py tests/test_omp_no_pattern_kill.py` for offline checks with recording stubs.

This command-text guard is not an operating-system security boundary.
It does not cover raw terminals, sessions with extensions disabled, other clients such as curl, or commands hidden in scripts or constructed dynamically.
Literal shell commands and nested `sh -c` forms are covered; arbitrary eval-language programs and argv arrays are not.

## Quality gate

The quality gate extension runs when an agent turn ends, in the git repository of the session's working directory. It has two parts.

**Blocking.** This part runs only when the repository has `.sentrux/baseline.json` and the turn changed files (a new commit counts). It runs `sentrux gate .` once. A `DEGRADED` verdict, or a `Quality: <baseline> -> <current>` drop of more than `FM_QUALITY_MAX_DROP` points, sends the agent one continuation with the evidence: fix the structure, or re-baseline on purpose. A low score alone never blocks. The gate blocks at most once per prompt: the continuation turn it starts is never blocked again.

**Advisory.** When the repository has uncommitted changes, these checks run in the background:

- `sentrux check .`, when `.sentrux/rules.toml` exists.
- `fallow audit --changed-since HEAD`, when `package.json` or `tsconfig.json` exists.

A check that fails is shown to the agent at the start of its next prompt. The advisory checks never block. A second run does not start while one runs, or for a diff that was already checked.

A missing `sentrux` or `fallow`, a repository without a baseline, a timeout, or output the extension cannot parse never blocks. Supervisor homes without `.sentrux/baseline.json` are not gated.

Two environment variables change the gate. Set them in the environment that starts omp:

| Variable | Effect |
| --- | --- |
| `SENTRUX_GATE=advisory` | Turns the block off. The advisory checks still run. |
| `FM_QUALITY_MAX_DROP` | The quality drop, in points, that the gate tolerates. Default `250`. |

To turn the gate on for a repository, or to accept a structural change on purpose, save a new baseline and commit it:

```bash
sentrux gate --save .
git add .sentrux/baseline.json
```

This repository gates itself the same way. The `quality gate` CI job runs `bun blueprint/config/omp-quality-gate.ts` (the same blocking rule, exit 1 on a block) against the committed [`.sentrux/baseline.json`](../.sentrux/baseline.json), and `fallow audit` on the changed files as a warning that never fails the job. Unlike the omp extension, the CI job fails closed: it also exits 1, naming the cause, when `.sentrux/baseline.json` is missing, when `sentrux` is missing, crashes or times out, or when its output has no parseable `Quality:` line.

## no-mistakes pipeline agent

no-mistakes has no native omp agent.
Crewship runs omp through the native Pi adapter, which supports per-run model and effort choices.
The verified configuration uses `agent: pi`, without an ACP fallback that could ignore those choices.
An adapter pin mismatch selects `acp:omp` until the wrapper is verified again.
Every apply:

1. Installs [`blueprint/config/omp-as-pi/`](../blueprint/config/omp-as-pi/) to `~/.no-mistakes/omp-as-pi/`.
   The wrapper maps `--session` to `--resume` and neutralizes context files with the pinned gate overlay.
   It refuses unsupported arguments with exit 64 and logs the refusal to `~/.no-mistakes/omp-as-pi/refusals.log`.
   Pi-only runs fail on refusal instead of changing the selected gate model through ACP.
2. Checks the pi adapter of the no-mistakes release it installs. no-mistakes installs at its newest non-draft release, prereleases included, but the wrapper only translates the arguments the adapter it was proven against builds. `check-adapter.sh v<version>` fetches that release's four adapter sources (`pi.go`, `pi_profile.go`, `fallback.go`, `ompgate.go`) and compares them with the sha256 pins in `check-adapter.sh`, the only place the pins live. It exits 0 when every pin matches, 1 when a source differs from its pin or is gone from the tag (HTTP 404), and 2 when it proves nothing: a network error, a timeout, or any other HTTP status.
3. Sets `agent: pi` after a successful adapter check.
   It sets `agent_path_override.pi` to the installed wrapper and `agent_config.pi` to Sonnet 5.5 with effort `high`.
   A pin mismatch sets `agent: [acp:omp]` and reports why.
   An inconclusive check leaves the setting unchanged and prints a warning.
   Crewship manages its current agent choice and its previous agent lists; other agent choices stay unchanged.
   Never add `acp_registry_overrides` for omp: no-mistakes refuses these overrides when `disable_project_settings: true`.
4. Installs [`blueprint/config/no-mistakes-omp.yml`](../blueprint/config/no-mistakes-omp.yml) as the daemon's omp overlay.
   It enables an Opus 5.5 advisor at medium effort and sets the default model to Sonnet 5.5 at high effort.
   ACP uses that default; Pi passes the selected model and effort explicitly.
   The `no-mistakes-daemon-` systemd drop-in sets `PI_CONFIG_FILES` to this overlay.

Restarting the daemon kills the pipeline runs in flight, so the recipe never does it. When the daemon's omp overlay, its systemd drop-in, or the agent setting in `~/.no-mistakes/config.yaml` changes, the apply prints a reminder: run `no-mistakes daemon restart` once no pipeline run is active.

Verification runs `~/.no-mistakes/omp-as-pi/omp-as-pi --omp-as-pi-check`, which confirms the installed omp still lists every flag the wrapper uses and the gate overlay matches its pin. CI runs the wrapper's offline tests with `bash blueprint/config/omp-as-pi/test.sh`; `test.sh --live` also drives the real omp with a cheap model.

When a new no-mistakes release changes the adapter, re-prove the wrapper against it (`test.sh --live` and a pipeline run), then update the pins in `check-adapter.sh`.

Select a gate tier for each run with `no-mistakes axi run --model <id> --effort <level>`.
Without these options, the verified Pi configuration uses the ordinary tier.

See [Default config](default-config.md) for the gate tiers and their model and effort choices.

For a hard run, use `no-mistakes axi run --intent "..." --model anthropic/claude-opus-5-5 --effort high`.

## Skills

Crewship keeps skills, not personal notes, in `blueprint/skills/`. `CLAUDE.md` and `AGENTS.md` stay free of personal content.

- `blueprint/skills/public/<name>/SKILL.md`, with any helper files beside it: skills that ship with Crewship. A folder with no `SKILL.md` of its own is a group of skills, `<group>/<name>/SKILL.md`, that can share files kept once in the group folder.
- `blueprint/skills/private/<name>/SKILL.md`: skills that stay on the host. Git ignores this folder except its README, and Docker builds leave it out.

The public skills and the public rules are opt-in. Set `profiles.public_skills: true` in `.local/host.yml` to install them. With `false`, apply installs no public skill or rule. With no key, apply installs them only on a host that already has them, so an update never takes them away. Turning the key off stops updates and deletes nothing: delete a skill from `~/.omp/agent/skills/` and `~/.claude/skills/` by hand to remove it. Private skills and private rules always install.

Every apply copies each skill to `~/.omp/agent/skills/<name>/` and `~/.claude/skills/<name>/` with [`scripts/skills.py`](../scripts/skills.py). A group is copied whole, with its symlinks, to `<group>/`, and each skill in it gets the link `<name>` to `<group>/<name>`, so omp and Claude Code find it under its own name and its shared files stay one copy. A private skill wins over a public skill with the same name. A private group or skill with the name of a public group replaces that whole group, so the public skills in it do not install. The installer records the names it installed in `~/.local/share/crewship/skills.json`. It rewrites only those skills, and removes one when its source leaves `blueprint/skills/`. A skill directory that the manifest does not list belongs to the operator: the installer never replaces or removes it and reports it under `skipped`. An unchanged apply changes nothing.

To fill `blueprint/skills/private/` on every host from one private source, set `skills.private_source` in `.local/host.yml` ([The host config](configuration.md#the-host-config)). It is an absolute local directory or a git URL (`https://`, `ssh://`, `file://` or `user@host:path`), with an optional `skills.private_ref` that applies only to a git URL; validation rejects it beside a local directory. Each skill in the source is a top-level `<name>/SKILL.md` or, as in the public tree, a skill in a group, `<group>/<name>/SKILL.md`. Two skills with the same name in one tree stop the install with an error. Before the install, apply fetches a git source into `~/.cache/crewship/private-skills/` and copies its skills into `blueprint/skills/private/`. A git fetch signs in with the account's own git or GitHub login (for example `gh auth setup-git`), never with the config file, so the schema rejects an `https://` URL that holds a user name or token. The same manifest, under `blueprint/skills/private`, records the filled skills: a skill that leaves the source leaves `blueprint/skills/private/`, and a private skill put there by hand is never replaced. Without the setting, apply fetches nothing. Removing the setting and applying removes the skills an earlier fill added, from `blueprint/skills/private/` and from both install folders, and leaves private skills put there by hand.

## Rules

Crewship ships general omp rules, including Time Traveling Stream Rules (TTSR), in `blueprint/rules/`. Each rule is one Markdown file in omp's rule format: YAML frontmatter (`description`, and `alwaysApply`, or a TTSR `condition` and `scope`) and a body.

- `blueprint/rules/public/<name>.md`: rules that ship with Crewship. Keep them general: no personal paths, host names, user names, emails, accounts, or project names. `tests/test_skills.py` scans them for these markers.
- `blueprint/rules/private/<name>.md`: rules that stay on the host. Git ignores this folder except its README, and Docker builds leave it out.

When `profiles.public_skills` is on, every apply copies each rule to `~/.omp/agent/rules/<name>.md` with the skills installer, [`scripts/skills.py`](../scripts/skills.py). A private rule wins over a public rule with the same name. The installer records the rules it installed in the same manifest as the skills, and treats them the same way: it rewrites or removes only those rules, a rule file that the manifest does not list belongs to the operator, and an unchanged apply changes nothing.

Apply installs `drive-the-browser-yourself.md` and `fleet-browser-default-tier.md` only when `profiles.fleet_browsers` or `profiles.fleet_guards` enables the browser ladder.
Without the ladder, apply passes `--skip-rule` for both names to the installer.
This excludes both public and private copies from installation and removes earlier manifest-owned copies from omp's rules folder.
Files added by hand remain unchanged.
The other rules install with the `agents` profile.

The same `skills.private_source` fills `blueprint/rules/private/` from the source's `rules/` folder (`rules/<name>.md`).
The manifest records these files under `blueprint/rules/private`; it never replaces private rules added by hand.
If a rule leaves the source or you remove the setting, apply removes its manifest-owned private copy.
Apply then installs the public rule of the same name, if one exists and is not excluded by `--skip-rule`.
Otherwise, apply removes the manifest-owned installed rule.

## Global instructions

[`blueprint/config/AGENTS.md`](../blueprint/config/AGENTS.md) holds the generic working rules; see that file for skill, review, and search guidance.
The global instructions are opt-in.
`profiles.agent_instructions: true` turns them on; `false` turns them off.
With no key, apply installs them only on a host with the manifest below or a file containing a Crewship block.
Turning them off deletes nothing.

[`scripts/instructions.py`](../scripts/instructions.py) writes the text to `~/.claude/CLAUDE.md` (Claude Code) and `~/.codex/AGENTS.md` (Codex, which has no import). When `~/.claude/RTK.md` exists, the Claude Code file also gets the `@RTK.md` import. omp's own `~/.omp/agent/AGENTS.md` shadows `~/.claude/CLAUDE.md`, so that file is the single line `@~/.claude/CLAUDE.md`.

`instructions_mode` says what happens to a target file that already exists. A missing file is always written.

| Mode | Existing file |
| --- | --- |
| `append` (default) | One block between `<!-- crewship:begin -->` and `<!-- crewship:end -->` goes at the end. A re-run replaces that block in place and never adds a second. Text outside the markers stays. A file with only one marker is left alone and reported. |
| `overwrite` | The file moves to `<file>.<UTC time>.bak` in the same folder, then the text is written. The apply prints the backup paths. |
| `skip` | The file stays as it is. |

The installer records the SHA-256 of each whole file it wrote in `~/.local/share/crewship/instructions.json`. A file that still matches is Crewship's own, so `overwrite` replaces it without a backup and `append` turns it into a block. An unchanged apply changes nothing.

## Updating an existing host

Because the seed is first-write-only, an edit to `blueprint/config/omp.yml` never reaches a host that already has `~/.omp/agent/config.yml`, except the two keys [Status line icons](#status-line-icons) needs. To update one:

1. Compare the two files:

   ```bash
   diff ~/.omp/agent/config.yml blueprint/config/omp.yml
   ```

2. Merge the changes you want into `~/.omp/agent/config.yml` by hand, or use `/settings` and `/model` in a session.

To upgrade omp itself, run `./ship.sh launch`: it installs the newest published omp and relinks `~/.local/bin/omp`.
