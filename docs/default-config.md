# Default config

- **Models:** [omp](omp.md) runs the agents. Opus 5.5 at high thinking runs the home, with the advisor off. OpenAI requests use the priority tier. Firstmate picks a model for each task: Haiku 5.5 or Luna for small work, Sonnet 5.5 for ordinary work (the default), and Opus 5.5 for hard work only. Sol 6.1 takes ordinary work only when the Anthropic quota is exhausted. The spawning agent picks the thinking level.
- **Fallbacks:** a model that keeps failing falls back to the next one. Opus 5.5 falls back to Fable 5.1 at medium thinking, Fable 5.1 to Opus 5, and Sonnet 5 to Fable 5.1, then Opus 5.
- **Plugins and extensions:** the omp plugins `ponytail`, `i-have-adhd`, and `caveman`. Extensions add the [turn-end quality check](omp.md#quality-gate), [status-line icons](omp.md#status-line-icons), the [Herdr sidebar](herdr.md) feed, and a block on kill-by-name commands such as `pkill` and `killall`.
- **Gates:** the [no-mistakes pipeline](omp.md#no-mistakes-pipeline-agent) and `ponytail-review` check every change. Gates use Sonnet 5.5 at high thinking, and Opus 5.5 for hard work. Pick another model for one run with `--model`.
- **Skills and rules:** [`blueprint/skills/`](../blueprint/skills/) and [`blueprint/config/AGENTS.md`](../blueprint/config/AGENTS.md) serve omp, Claude Code, and Codex. Public files install only with `profiles.public_skills` (opt-in; a host that already has them keeps them), and private files take precedence ([omp](omp.md#skills)). The [rules](omp.md#rules) set plain technical writing, always-on skills, and native stacked PRs.
- **Profiles on by default:** `agents`, `firstmate`
- **Opt-in profiles:** see [Profiles](configuration.md#profiles) for the full list and defaults.
- **New hosts:** `./ship.sh dock` writes the core only: `agents` and `firstmate`. Pick more with the checklist `bunx crewship` shows, or `--with NAMES` ([Configuration](configuration.md)). A host config made before this keeps its own values.
- **Opt-in settings:** `data_dir`, `usage`, `firstmate.checklist`, `mac_ssh`, `imessage`, `github_board`, `board`, `board.github_sink`, `ci_pool`
- **Full lists:** [`blueprint/config/default.yml`](../blueprint/config/default.yml), [`blueprint/config/omp.yml`](../blueprint/config/omp.yml), and the [wiki](https://github.com/i098/Crewship/wiki).
