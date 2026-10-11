# Default config

- **Models:** [omp](omp.md) runs the agents. Opus 5.5 at extra-high thinking runs the home, with the advisor off. Firstmate picks a model for each task: Haiku 5.5 or Luna for small work, Sonnet 5.5 or Sol 6.1 for ordinary work (the default), and Opus 5.5 for hard work only. The spawning agent picks the thinking level.
- **Fallbacks:** a model that keeps failing falls back to the next one. Opus 5.5 falls back to Fable 5.1 at medium thinking, Fable 5.1 to Opus 5, and Sonnet 5 to Fable 5.1, then Opus 5.
- **Plugins and extensions:** the omp plugins `ponytail`, `i-have-adhd`, and `caveman`. Extensions add the [turn-end quality check](omp.md#quality-gate), [status-line icons](omp.md#status-line-icons), the [Herdr sidebar](herdr.md) feed, and a block on kill-by-name commands such as `pkill` and `killall`.
- **Gates:** the [no-mistakes pipeline](omp.md#no-mistakes-pipeline-agent) and `ponytail-review` check every change. Gates use Sonnet 5.5 at high thinking, and Opus 5.5 for hard work. Pick another model for one run with `--model`.
- **Skills and rules:** [`skills/`](../skills/) and [`config/AGENTS.md`](../config/AGENTS.md) serve omp, Claude Code, and Codex. Public files install with the `agents` profile, and private files take precedence ([omp](omp.md#skills)). The [rules](omp.md#rules) set plain technical writing, always-on skills, and native stacked PRs.
- **Profiles on by default:** `agents`, `development`, `firstmate`, `docker`, `chat`
- **Opt-in profiles:** `tailscale`, `desktop`, `fleet_guards`, `shared_postgres`, `fleet_browsers`
- **Opt-in settings:** `data_dir`, `firstmate.checklist`, `mac_ssh`, `imessage`, `github_board`, `board`, `ci_pool`
- **Full lists:** [`config/default.yml`](../config/default.yml), [`config/omp.yml`](../config/omp.yml), and the [wiki](https://github.com/i098/Crewship/wiki).
