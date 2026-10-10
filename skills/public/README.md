# Public skills

Skills that ship with Crewship. Put each skill in `skills/public/<name>/SKILL.md`, with any helper files beside it. The `agents` profile installs every skill here for omp (`~/.omp/agent/skills/`) and Claude Code (`~/.claude/skills/`). A skill in [`skills/private/`](../private/README.md) with the same name wins on that host. See [Skills](../../docs/omp.md#skills).

- [`code-clarity`](code-clarity/SKILL.md): write, review and simplify code by its naming, flow, state and abstractions (MIT, credited in [CREDITS.md](../../CREDITS.md)).
- [`code-navigation`](code-navigation/SKILL.md): use CodeGraph and tokensave before grep or reading files.
- [`engineering-standards`](engineering-standards/SKILL.md): weigh quality over cost, reproduce bugs end to end, fix lint, test and UI faults you see.
- [`git-and-prs`](git-and-prs/SKILL.md): commit messages, generated files, and PR size and splits checked with `ponytail-review`.
- [`ieee-documentation`](ieee-documentation/SKILL.md): IEEE 1016 design and IEEE 829 test documents, kept in proportion.
- [`operating-rules`](operating-rules/SKILL.md): ask or act, keep scope, finish the work, and answer a question as a question.
- [`opus-speed`](opus-speed/SKILL.md): wall-clock speed for Opus 5 with parallel, non-overlapping subagents.
- [`process-safety`](process-safety/SKILL.md): kill by pid, not by pattern, and keep test services and worktree ports apart.
- [`progress-bars`](progress-bars/SKILL.md): a fixed ASCII progress-bar format with percentages from real counts.
- [`quality-gates`](quality-gates/SKILL.md): sentrux and fallow gates and the pull-based codex advisor.
- [`talk-style`](talk-style/SKILL.md): short, plain ASD-STE100 replies with no preamble and no em dash.
- [`tooling-conventions`](tooling-conventions/SKILL.md): bun, gh-axi, lavish, no-mistakes, herdr, skillspector, caveman and ponytail.
