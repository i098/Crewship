# Herdr sidebar

Crewship renders `~/.config/herdr/config.toml` from [`blueprint/ansible/templates/herdr.toml.j2`](../blueprint/ansible/templates/herdr.toml.j2) and the `herdr` block of `.local/host.yml`. This guide covers the two sidebar layouts it ships, Spaces and Agents, and the two feeders that report their `$` tokens: an omp extension for Agents and a reporter timer for Spaces.

The config sets `[session] resume_agents_on_restore = false`. After a Herdr server restart, each pane comes back as a plain shell: Firstmate relaunches its own agents through its launch line, which closes the pane when the agent exits on purpose. Start main Firstmate again by hand with `exec omp` in its pane, so that quitting omp also closes the pane.

The sidebar is 46 columns wide (`sidebar_width`; it may grow to `sidebar_max_width`, 56). That fits the widest pull request line: a 4-digit pull request and issue, 5-digit line counts and a 3-digit file count. There is no status word: the state icon already shows it. The recipe sets `[ui] status_indicators = "symbols"`, so the state icon is a different symbol for each agent state, not only a different color. This guide calls it the state dot.

## Spaces: one entry per home

Spaces shows one entry per home workspace. It never repeats per-agent detail, which lives in Agents.

```text
● ⌂ ⚙ 41% ▤ 18.2/31.0G 59% ⛁ 402/937G 43% ◉ 13/42
  7d left <Claude> ▰▱▱▱  22%  <OpenAI> ▰▰▱▱  50%
● firstmate · ⚑ 3 · ▶ 1/5 · ◷ 4
  ⚙ 29%  ▤ 8%  ⛁ 2%
● webapp · ⚑ 2 · ▶ 0/2 · ◷ 3
  ⚙ 1%  ▤ 3%  ⛁ 4%
  ⚠ watcher silent
○ ☾ afk
```

Herdr indents every line after an entry's first by two columns, so every entry's state dot sits in the same column and the lines below sit under the name.
See [The machine entry](#the-machine-entry) for the optional top entry.

| Line | Shows |
| --- | --- |
| 1 | The state dot, then the short name (`$short`): the primary home (`firstmate`) in bold blue, other homes in mauve. A dead helper space (label contains `-afk-daemon-`) shows `☾ afk`, dimmed, and nothing else. A space with no short name shows its own label, dimmed. Then the decision, working/total agent and queue counts, each in its own color. Zero decision and queue counts are hidden. On the `machine` workspace only, the whole machine (`$machine`) instead. |
| 2 | What the space costs the machine, as shares, in light grey (`#a6adc8`): `⚙` CPU, `▤` RAM, `⛁` disk. |
| 3 | The whole machine (`$host`), on the primary home's entry only (the workspace labelled `firstmate`; without one, the first workspace listed), and only while no `machine` workspace exists. Every other entry leaves this line empty, and Herdr hides it. |
| 4 | Provider usage (`$usage`), immediately below the whole-machine row. The label `7d left`, then the Claude mark (U+EC82) and the OpenAI mark (U+EC81), each with a four-cell bar and the percentage of the weekly quota left. |
| 5 | `⚠ watcher silent` in orange, only when the home's watcher stopped reporting. |

| Token | Value | Source |
| --- | --- | --- |
| `$short` | `webapp` for `2ndmate-webapp-mate-s4` | The workspace label: `firstmate` stays as is, `2ndmate-<name>-mate-<id>` becomes `<name>`, `└ <task> · p:<token>` becomes `└ <task>`. Other labels have no short name. |
| `$decisions` | `⚑ N` (red, bold) | Fresh decisions waiting on the operator, counted where they can be acted on. Every count comes from the primary home's status logs, through the read-only `status_open_decisions` fold of its `bin/fm-classify-lib.sh`, cached until each log changes. The primary home here is only the workspace labelled `firstmate`: without one, no Space shows `⚑`. A second-level home's Space counts the open decisions in its own status log (`state/<home>.status`, the record whose `herdr_workspace_id` is that Space). The primary Space counts only its own workers' logs. A second-level home's own workers are not counted: it decides for them, and escalates anything it cannot decide into its status log in the primary home, which is what its Space counts. Parked holds (keys starting `captain-hold-`) never count, and a second-level home without a live Space is not counted anywhere. |
| `$crew` | `▶ working/total` (green) | Actual agent panes in this workspace. Only `agent_status = working` counts as working. Idle, blocked and unknown agents count only in the total. Shell panes and task records do not count. |
| `$queue` | `◷ N` (yellow) | Tasks queued and ready to start: `count` from the home's `bin/fm-tasks-axi.sh ready`, recounted when the home's `data/backlog.md` changes and at least once a minute. |
| `$res` | `⚙ 29%  ▤ 8%  ⛁ 2%` | CPU (share of all cores) and resident memory (share of `MemTotal`) summed over every process whose environment carries the space's `HERDR_WORKSPACE_ID`, so its workers count. CPU is each process's own CPU time (`utime` + `stime`) gained between two runs, for every process present in both, clamped to 0–100%. Disk is the home plus the worktree pools of its projects, as `treehouse status --json` lists them, as a share of the filesystem holding the home; a pool worktree that is itself another home is left out. |
| `$alert` | `⚠ watcher silent` (orange) | `fm_supervision_unhealthy` from the home's `bin/fm-supervision-lib.sh`: the home has work that needs a watcher and the watcher's beacon is stale. |
| `$host` | `⌂ ⚙ 41% ▤ 18.2/31.0G 59% ⛁ 402/937G 43% ◉ 13/42` (light grey) | The whole machine: CPU busy share from `/proc/stat`, used memory (`MemTotal` − `MemAvailable`) from `/proc/meminfo`, and the root filesystem from `statvfs`, each with its share. Memory keeps one decimal while the total is under 100G (`18.2/31.0G`); disk is in whole G (`45/93G`, `402/937G`). Both are whole G from 100G and switch to T from 1000G (`1.4/1.9T`, whole T from 10T). `◉` counts the agent panes (panes with an `agent`) that are working, over all agent panes. Reported on the primary home, only while no `machine` workspace exists. |
| `$machine` | the same as `$host` | The same line, reported on the `machine` workspace instead. The two are never both set. |
| `$usage` | `7d left <Claude> ▰▱▱▱  22%  <OpenAI> ▰▰▱▱  50%` | The weekly quota left, as the mean over each provider's accounts, from `omp usage --json`. Only the workspace carrying `$machine` or `$host` receives this row. |

The provider row reads `reports[]` from `omp usage --json`.
Claude uses provider `anthropic`; OpenAI uses `openai-codex`.
Each account contributes its shared seven-day window: the `limits[]` entry whose `scope.windowId` is `7d` and that has no `scope.tier`.
That window gates every model; five-hour windows and model-tier windows (for example Fable) do not count.
Each provider shows the mean of its accounts' `usedFraction` as percent left, rounded as the `omp usage` panel rounds it, so the row and the panel's seven-day figure agree.
Account IDs identify duplicate credential aliases, which count once; organization IDs keep distinct subscriptions separate.
When an account ID is absent, the reporter uses its email if available, or keeps the report separate.
The row has 32 terminal columns and fits at sidebar widths 46 and 38.

If an account has no seven-day window or an unknown one, that provider shows `░░?░   ?%`.
An account listed under `accountsWithoutUsage` also makes its provider unknown.
A failed command or an absent provider shows unknown, never zero usage.
The reporter reads only the usage command's output; it does not open or change credential stores.

The marks are the `cod-claude` (U+EC82) and `cod-openai` (U+EC81) glyphs of Nerd Fonts (the Hack Nerd Font 3.5.0 file already contains both), which come from the Codicons [`claude.svg`](https://github.com/microsoft/vscode-codicons/blob/main/src/icons/claude.svg) and [`openai.svg`](https://github.com/microsoft/vscode-codicons/blob/main/src/icons/openai.svg) sources.
Herdr's sidebar draws text cells only, so the terminal font on the machine that shows Herdr must be Nerd Font patched with these glyphs (older fonts may lack them), or these two cells show a missing-glyph box.

### The machine entry

The whole-machine line goes on a workspace labelled `machine` when one exists. It is an otherwise empty workspace you create once, then move to the top of the workspace list:

```bash
herdr workspace create --cwd ~ --label machine --no-focus
```

Its entry shows the state dot and the machine line, followed by the provider row.
It shows no name, label, workspace counts or workspace resource line.

Without a `machine` workspace, the machine line is the primary home's `$host` line (the workspace labelled `firstmate`; without one, the first workspace listed), below its CPU and RAM line.

### The reporter

[`blueprint/maintenance/herdr-spaces.py`](../blueprint/maintenance/herdr-spaces.py) is installed as `~/.local/bin/herdr-spaces.py` and run by the user timer `herdr-spaces.timer` every second. It uses only the Python standard library.

For every Herdr workspace it finds the home from its panes' directories: the nearest git top-level that holds both `state/` and `data/`.
It reports the tokens above under `crewship:spaces` and clears tokens without values.
Helper and per-task spaces (`└ …`) keep their short name only.
A space without a home keeps its short name, CPU and RAM.
The `machine` workspace receives `machine` and `usage`; without one, the primary home receives `host` and `usage`.
Provider usage stays out of mobile metadata.
The other mobile fields follow the existing mechanism (see [On a phone](#on-a-phone)).

| Source | Refresh | Cost |
| --- | --- | --- |
| CPU, RAM, counts, watcher, machine | every run (1 s) | One pass over `/proc` and file reads. CPU needs two runs, so it appears from the second run on. |
| Queue | when the backlog changes, else every minute | One `fm-tasks-axi.sh ready` per home, most of a run's cost when it runs. |
| Disk | every 15 minutes | One `du` over each home and its pools. On a host with large pools this run can take a minute; the other values wait for it. |
| Provider usage | every 3 minutes | One `omp usage --json` call with a 20-second timeout. The reporter also caches failures for 3 minutes. `omp` itself reuses each account's report for 5 minutes ±25%, so with healthy fetches the cache lifetimes add up to about 9 minutes 16 seconds, plus run time. A failed `omp` fetch can return an older last good report. |

The caches live in `~/.cache/crewship/herdr-spaces.json`.
A failed usage refresh replaces the provider percentages with unknown; other failed sources keep their previous values.
A failed run never fails the unit: errors go to the journal (`journalctl --user -u herdr-spaces.service`).
Herdr drops workspace tokens when its server restarts; the next run reports them again.

Inspect what a space reports:

```bash
herdr workspace get <workspace_id>
```

The result carries `tokens.short`, `tokens.decisions`, and so on.

## Agents: one entry per agent

```text
● firstmate
  Planning the release checklist
● └ Fixing the token refresh race
    ⎇ 1537 · ○ 1529 · +12847 · −3902 · ✎ 214
● webapp
  Fix ratings cache key collision
  ⎇ 1561 · ○ 1558 · +84 · −12 · ✎ 3
```

| Line | Shows |
| --- | --- |
| 1 | The state dot, then the pane's `who` name: the same short names as Spaces. The primary home is bold blue, other homes bold mauve, and a dead helper (`☾ afk`) mauve, not bold. A spawned worker has no `who` name: its line is `└ ` and its session topic, in teal, because a worker works on one thing and its topic says what. |
| 2 | A home's current session topic, dimmed on a brighter base (`#cdd6f4`) so it reads lighter than the name, without omp's `π` and spinner. Herdr's two-column indent puts it under the name. A worker has no line 2: its topic is on line 1. |
| 3 | The pull request line, for any agent whose current branch has an open pull request, workers and homes alike, and for every worker: a worker shows its line counts as soon as its checkout differs from the default branch, before any commit or pull request, and its issue when its task names one. Indented to line up under the name: four columns for a worker, two for a home. |

| Token | Value | Color |
| --- | --- | --- |
| `$pr` | `⎇ <pr>`: the open pull request whose head is the current branch, in the checkout's repository or a fork | blue |
| `$issue` | `○ <issue>`: the issue the work is for | mauve |
| `$add` | `+<added>` lines | green |
| `$del` | `−<deleted>` lines (U+2212) | red |
| `$files` | `✎ <files>` changed | yellow |

Herdr indents every line after the first by two columns. For a worker, the first part present adds two U+2800 blank characters to that. The line counts cover the work in the session's checkout: `git diff --shortstat --merge-base <base>`, which counts committed, staged, and unstaged changes to tracked files since the merge base of the base and `HEAD`, plus every untracked file that is not ignored, counted as a new file (its lines, one for a symlink, or none for a binary file). The base is `origin/<default branch>` while a pull request is open, else `origin/HEAD`, the remote's default branch; a checkout without that ref uses `origin/main`, then `origin/master`, and with none of them shows no counts. An empty diff shows no counts either. The pull request comes from the GitHub REST API through `gh api`. It is looked up with the checkout's repository owner as the head owner first, then with the owner of each GitHub remote in `git remote -v`, in order, so a pull request opened from a fork shows as long as the checkout has the fork as a remote.

The issue comes from the worker's task record in its home first: the first `issues/<n>` link or `issue <n>` / `issue #<n>` in the task's backlog entry (`data/backlog.md`), then in its brief (`data/<task>/brief.md`). The home is the ancestor of the pane's launch directory that holds `state/<task>.meta`. So a worker shows its issue before its pull request opens, after it merges, and when the body has no closing keyword. Without a task record, the issue is the first one the pull request body closes (`Closes #N`, `Fixes #N`, `Resolves #N`).

### The omp extension

Herdr configuration alone cannot drop the `π` (omp puts it at the start of every terminal title) or know about pull requests. With the `agents` profile on, `./ship.sh launch` installs [`blueprint/config/herdr-sidebar.ts`](../blueprint/config/herdr-sidebar.ts) as `~/.omp/agent/extensions/crewship-herdr-sidebar.ts`. omp loads it at startup. Every apply rewrites it, so do not edit the installed copy.

The extension does nothing outside Herdr (`HERDR_ENV` is not `1`) or in an omp started from another omp's shell (`OMPCODE=1`). Inside a Herdr pane it:

- Sets the terminal title to the bare session topic, and sets it again within a second whenever omp resets it (rename, `/new`, `/resume`, a cwd change). A spawned worker (`FM_TASK_ID` set) gets `└ ` in front; the Agents layout shows a title that starts with `└` on line 1 and hides it on line 2.
- Reports the pane tokens `who`, `pr`, `issue`, `add`, `del` and `files` under the source `crewship:sidebar`, and clears the ones without a value.

It reports when a session starts and when a turn ends. The pull request and the task's issue are looked up then too, at most every 5 minutes; a turn that ends sooner gets its lookup when the 5 minutes are up. The line counts are recomputed on every turn end and every 10 seconds while the session runs, for a worker and for a home while a pull request is open, so they follow edits, stages, and commits inside a long turn; the 10-second refresh runs only the local `git` commands (never rewriting the checkout's index), skips a tick while the previous refresh still runs, and reports only counts not yet reported successfully, so a failed report is retried at the next tick. Lookups run in the background with a timeout. A failed lookup keeps the previous value and never fails or slows a turn. Herdr drops pane tokens when its server restarts; the extension reports them again at the next turn end. All tokens are cleared when omp exits.

Inspect what a pane reports:

```bash
herdr agent get <pane_id>
```

The result carries `terminal_title` and `tokens.who`, `tokens.pr`, and so on.

### Pane state

Herdr learns whether an omp agent is working, blocked or idle from its own omp extension, `~/.omp/agent/extensions/herdr-omp-agent-state.ts`. With the `agents` profile on, every `./ship.sh launch` runs `herdr integration install omp` with the herdr it installed, so a herdr upgrade refreshes the extension; apply reports a change only when herdr rewrote the file, and verification fails unless `herdr integration status` reports `omp: current`. Without the extension Herdr shows every omp agent as idle. Apply installs no integration for other agents.

## Override the layouts or turn parts off

Set these keys under `crewship.herdr` in `.local/host.yml`, then run `./ship.sh launch`:

| Key | Default | Effect |
| --- | --- | --- |
| `sidebar_width` | `46` | Expanded sidebar width in columns. |
| `sidebar_max_width` | `56` | Maximum expanded sidebar width. |
| `sidebar_space_rows` | the Spaces layout above | TOML array written as `[ui.sidebar.spaces] rows`. |
| `sidebar_agent_rows` | the Agents layout above | TOML array written as `[ui.sidebar.agents] rows`. |
| `sidebar_bg` | `reset` | `[theme.custom] sidebar_bg`. `reset` is Herdr's alias for the terminal's own background, so the sidebar follows a transparent terminal; set a color such as `#1e1e2e` to pin it. |

Token syntax: [Herdr configuration](https://herdr.dev/docs/configuration/). Copy the default rows from [`blueprint/config/default.yml`](../blueprint/config/default.yml) and edit them:

- To turn a part off, delete its entry, for example `{ token = "$queue", … }` or the `$files` entry. Delete a whole row, such as the `$res` row, to drop that line.
- To change a color, edit its `fg`, `bold` or `dim`.

To check an override before applying, render it to a file and run Herdr's own validator on it without touching the live configuration:

```bash
HERDR_CONFIG_PATH=/path/to/rendered.toml herdr config check
```

## On a phone

At or below Herdr's `mobile_width_threshold` (64 columns by default; a phone in portrait over SSH or mosh is about 50), Herdr switches to its single-column mobile layout: the full-width pane plus a switch menu (tap `switch`, or `prefix+w`). That layout ignores the sidebar rows above, so the reporter also writes a compact form of the same data into the fields the switch menu does show. Every entry starts with `Local · <workspace label>`; the second line is Herdr's own, built from these fields:

```text
  agents
   ● Local · firstmate
   1 · ⚑3 ▶1/5 ◷4 ⚙11% ▤36% ⛁71% · Planning the release checklist
   ● Local · firstmate
   fix-token-race · ⎇1537 +12847 −3902 ✎214 · └ f…
   ● Local · 2ndmate-webapp-mate-s4
   ⚑2 ▶0/2 ◷3 ⚙4% ▤9% ⛁12% ⚠watcher ⎇1561 +84 −12 ✎3 · Fix ratings …
  spaces
   + new workspace
   · Local · machine
   shell · tab ⚙11% ▤36% ⛁71%
   ● Local · firstmate
   shell · tab 1 · 1/2
```

| Entry | Second line | Field the reporter writes |
| --- | --- | --- |
| Agent: a home's own agent (its pane has a `who` token) | The tab (only in a workspace with more than one), then the home's `⚑ ▶ ◷` counts, its `⚙ ▤ ⛁` shares, `⚠watcher` when its watcher is silent, and its pull request line, then its session topic. | The pane's `idle`, `working`, `done` and `unknown` state labels, and its display agent (the terminal title). `blocked` keeps Herdr's own word. |
| Agent: any other agent, such as a worker | The tab, its pull request line, then the name Firstmate gave it (`└ <task>`). | The same state labels. The display agent is Firstmate's and is never written. |
| Space: `machine` | The machine's CPU, RAM and disk shares, while its first tab is the active one. | The `machine` workspace's first tab, renamed under the rules below. |
| Space: any other | Herdr's own (`shell · tab 1`). | None: workspace labels and Firstmate's tab names route work (the orchestrator finds its agents by tab label), so no home workspace's tabs are renamed. |

Glyphs carry no space after them, and the parts are single-spaced, to fit more before Herdr cuts the line with `…`. The state label replaces Herdr's state word; the state dot still shows the state. A line longer than the screen loses its end: on a 50-column phone that is the session topic. The values follow the sidebar's: the same run reports both, every second. None of the desktop sidebar rows reads these fields, so the sidebar stays as above.

The `machine` tab is renamed under these rules:

- It is one pinned tab: the `machine` workspace's first tab, recorded by its tab id, never the active tab. Reordering the tabs does not move the pin; it moves to the new first tab only if the pinned tab is closed.
- The reporter writes only over a label that is Herdr's own number (`1`, `2`, …) or the text it wrote last. Any other label, such as a name an operator chose, is left alone. Rename the tab back to its number to hand it back.
- It looks at the tab at most once every 30 seconds, so it renames at most that often and its shares can be up to 30 seconds old.
- The shares show in the desktop tab bar and navigator while `machine` is focused, and on the phone in the `machine` Space line while that tab is the active one.

A home pane's display agent is its session topic. With `show_agent_labels_on_pane_borders` on (the Crewship default), a home pane in a split shows the topic on its border instead of `omp`, and the border follows the topic when the session is renamed. Every pane report names the pane's agent (`--agent`), so when that agent exits Herdr drops the topic and the state labels with it.

What the mobile layout forces, compared with the desktop sidebar:

- The switch menu lists agents before spaces, and the `machine` entry is not its first line.
- Entries show the workspace label, not the short name, and no colors. Herdr builds the Space entries itself, so a home's Space entry keeps `shell · tab N`; its counts and shares are on its agent entry.
- Each entry has one line of its own, so a home's counts, shares and pull request line come before its topic on the same line, and a long line loses its end, often the topic or worker name.
- A home's counts and shares are on its own agent's entry, so a home with no agent pane carrying a `who` token shows none. Without a `machine` workspace, the machine's shares do not show either.
- The issue (`○`) is left out for width.

### btop

btop draws nothing in a pane smaller than its shown boxes need; it shows `Terminal size too small` instead. All four boxes need 80x24 in btop 1.4 (the cpu box is 60 columns wide, the proc box 44 beside the 36 of mem and net), so a 50-column phone pane is too small.

`./ship.sh launch` installs the latest btop release as `~/.local/bin/btop-bin`, [`blueprint/config/btop.conf`](../blueprint/config/btop.conf) as `~/.config/btop/btop.conf`, and [`blueprint/maintenance/btop.sh`](../blueprint/maintenance/btop.sh) as `~/.local/bin/btop`. The launcher starts btop with preset 0 (all four boxes) in a pane of at least 80x24, and otherwise with preset 4 (processes only, which needs 44x16). When a phone attaches to the same session and the pane crosses 80x24, the launcher restarts btop with the other preset. Quitting btop ends the launcher.

btop saves its config on exit, including the last preset's boxes; the launcher always passes a preset, so that never changes what it shows. Every apply rewrites the config, so make lasting changes in `blueprint/config/btop.conf`, and keep preset 4 there.

## Viewing from another machine

Sidebar layouts are client-side: Herdr draws the sidebar from the config of the machine you view from, even over `herdr --remote`. The host still reports every token, but the viewing machine needs the host's layout to show them. `./ship.sh launch` installs [`blueprint/maintenance/herdr-sidebar-to-client.py`](../blueprint/maintenance/herdr-sidebar-to-client.py) as `~/.local/bin/herdr-sidebar-to-client.py`. On the viewing machine, run it against the host with Python 3 and ssh access, where `<host>` is anything `ssh` accepts, such as `user@host`:

```bash
ssh <host> cat .local/bin/herdr-sidebar-to-client.py | python3 - <host>
```

It copies the host's `sidebar_width`, `sidebar_max_width`, `[ui.sidebar.agents]`, `[ui.sidebar.spaces]` and `[theme.custom] sidebar_bg` into `~/.config/herdr/config.toml` on the viewing machine, or into the path given as a second argument, and leaves every other setting there as is. It writes a timestamped `.bak-sidebar-` copy of that file first. Run it again after the host's layout changes.

Pane state (the sidebar dots) is reported on the host by the omp integration `./ship.sh launch` installs, so the host needs nothing more. A machine that views the host with `herdr --remote` should run the same Herdr release as the host: the host runs the latest, so on the viewing machine run `herdr update`, then compare `herdr --version` with the host's.

## Over mosh

Over mosh, Herdr 0.9.3 can paint an opaque fill over older panes ([herdr#3773](https://github.com/herdrdev/herdr/issues/3773)), and mosh drops the images in the panes. `./ship.sh launch` installs [`tools/herdr-patch/herdr-patch`](../tools/herdr-patch/herdr-patch) as `~/.local/bin/herdr-patch`, which fixes both. `mosh-server` starts its command with the system `PATH`, which has no `~/.local/bin`, so apply also links `/usr/local/bin/herdr-patch` and `/usr/local/bin/herdr` to the installed files.
Apply changes such a link only when it is missing or already points into this account's home. It never changes a link into another account's home, for example after a sandbox or test apply for a second home, even when that link dangles, and it never changes a file that is not a link. Verification checks the two links only for the account that owns them.

On your computer, install the same script and attach with real images:

```bash
herdr-patch <user>@<host>
```

In a mobile mosh app, or with plain mosh, set the host command to `herdr-patch` (`mosh <user>@<host> -- herdr-patch`). The [herdr-patch README](../tools/herdr-patch/README.md) has the install steps for your computer, the images, the `HERDR_PATCH_FILL` fill list, the limits, and the removal steps.

Retired: `herdr-mosh` is now `herdr-patch`. An apply on a host that still has `~/.local/bin/herdr-mosh` or `/usr/local/bin/herdr-mosh` removes both (the second only under the same rule), so a saved mosh command that runs `herdr-mosh` must change to `herdr-patch`.

## Known limits

- Agents without the extension, including non-omp agents, show only their dot on line 1: nothing reports their `who` token.
- Short names and colors match workspace labels (`firstmate`, `2ndmate-…`, `└ …`, `-afk-daemon-`). A home workspace with another name has no short name and shows its label.
- Only closing keywords in the pull request body count as issues there. Issues linked only in the GitHub UI are not shown, because the REST API does not list them.
- CPU and RAM count only processes the reporter's account can read, and RAM is resident memory, so shared pages count once per process. CPU counts a process only while two runs a second apart both see it: a process that starts and ends between two runs is not counted, and the time before the first run that sees it or after the last is lost, so a space running many short builds reads low.
- The machine line's parts are single-spaced so it fits even with CPU at 100% and memory and disk at 99%: after the `machine` entry's state dot, or two columns in under the primary home's name, where Herdr shows 40 columns at width 46. At 100%, or on a narrower sidebar, Herdr cuts its end.
- Herdr sidebar styles offer color, bold and dim only: no italic and no thinner weight.
