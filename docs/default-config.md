# Default config

These defaults are what the project owner personally runs. Change any of them in `.local/host.yml` or with `omp config set`.

- **Models:** [omp](omp.md) runs the agents. Opus 5.5 at high thinking runs the home, with the advisor off. OpenAI requests use the priority tier. See [Firstmate dispatch defaults](configuration.md#firstmate-dispatch-defaults) for per-task model choices and thinking levels.
- **Fallbacks:** a model that keeps failing falls back to the next one. Opus 5.5 falls back to Fable 5.1 at medium thinking, Fable 5.1 to Opus 5.5, and Sonnet 5.5 to Fable 5.1, then Opus 5.5.
- **Plugins and extensions:** the omp plugins `ponytail`, `i-have-adhd`, and `caveman`. Extensions add the [turn-end quality check](omp.md#quality-gate), [status-line icons](omp.md#status-line-icons), the [Herdr sidebar](herdr.md) feed, and a block on kill-by-name commands such as `pkill` and `killall`.
- **Gates:** the [no-mistakes pipeline](omp.md#no-mistakes-pipeline-agent) and `ponytail-review` check every change. Gates use Sonnet 5.5 at high thinking, and Opus 5.5 for hard work. Pick another model for one run with `--model`.
- **Skills and rules:** [`blueprint/skills/`](../blueprint/skills/) and [`blueprint/config/AGENTS.md`](../blueprint/config/AGENTS.md) serve omp, Claude Code, and Codex. Public files install only with `profiles.public_skills` (opt-in; a host that already has them keeps them); the upstream skills from GitHub install either way, and private files take precedence ([omp](omp.md#skills)). The [rules](omp.md#rules) set plain technical writing, always-on skills, and native stacked PRs.
- **Profiles on by default:** `agents`, `firstmate`
- **Opt-in profiles:** `development`, `sgrep`, `docker`, `tailscale`, `desktop`, `fleet_guards`, `project_databases`, `jj`, `fdu`, `vphone`, `fleet_browsers`, `chat`, `gateway`, `forgejo`
- **New hosts:** `./ship.sh dock` writes the core only: `agents` and `firstmate`. Pick more with the checklist `bunx crewship` shows, or `--with NAMES` ([Configuration](configuration.md)). A host config made before this keeps its own values.
- **Firstmate backend:** see [Firstmate backend](configuration.md#firstmate-backend) for the default, alternatives, and existing-checkout behavior.
- **Opt-in settings:** `data_dir`, `usage`, `token_suggestions`, `firstmate.checklist`, `mac_ssh`, `imessage`, `github_board`, `board`, `board.github_sink`, `ci_pool`
- **Full lists:** [`blueprint/config/default.yml`](../blueprint/config/default.yml), [`blueprint/config/omp.yml`](../blueprint/config/omp.yml), and the [wiki](https://github.com/i098/Crewship/wiki).

## Optimizations in the default

Each line names the real setting. Details are in the linked pages.

- **Compaction:** every session compacts at 200,000 tokens (`compaction.thresholdTokens`), keeps 32,000 tokens of recent messages (`compaction.v2RetainedMessageBudget`), and tries `snapcompact`, `remote`, `handoff`, `shake`, `soft` in that order (`compaction.methodOrder`).
- **Tool output spill:** output above 20 KB goes to an artifact, and 4 KB head and 4 KB tail stay inline (`tools.artifactSpillThreshold`, `tools.artifactHeadBytes`, `tools.artifactTailBytes`).
- **Cheap helper models:** `commit`, `tiny`, and `memory` use Haiku 5.5, and `smol` uses Sonnet 5.5 with thinking off (`modelRoles`). `omitThinking` and `hideThinkingBlock` are on, and `textVerbosity` is `low`.
- **Memory:** `memory.backend: mnemopi` with `mnemopi.noEmbeddings: true`, so recall needs no embedding calls.
- **Crew advisor:** off globally (`advisor.enabled: false`). Crewmates turn it on at low thinking with `syncBacklog: "off"` and `immuneTurns: 10`, so it never blocks a crew ([omp](omp.md#advisor)).
- **Model fallback:** `retry.fallbackChains` with `retry.maxDelayMs: 60000`, so a failing model does not stall a run.
- **Provider tier:** `tier.openai: priority`. Models connect to providers directly, with no router.
- **Spawn memory floor:** `spawn-memory-floor-mb` is 8000, so a crewmate does not start on a host low on RAM ([Capacity](capacity.md#load-estimate)).
- **Idle browsers:** `browser_prune` stops idle AXI browsers after 7200 s (checked every 300 s), and `browsers.idle_timeout_min` is 30.
- **Docker:** `docker.init: true`, `docker.live_restore: true`, and `fleet.docker_guard.stopped_hours: 24` ([Fleet guards](fleet-guards.md)).
- **Disk:** the storage guard warns at 85% and prunes at 92% ([Capacity](capacity.md)). Package caches go to `<data_dir>/cache/<tool>` when `data_dir` is set ([Configuration](configuration.md#data-disk)).
- **CI pool:** `job_memory_gb: 8` caps each job, and `nice` can lower CI CPU priority; its default is `0` ([CI pool](ci-pool.md#cpu-priority)).
- **Terminal UI:** `tui.tight`, `tui.vimMode`, a borderless composer with `composer.tokenRate`, and a transparent powerline status line ([omp](omp.md#other-seeded-preferences)).
