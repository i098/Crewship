---
name: quality-gates
description: Use before handing off code changes, when a sentrux, fallow, or codex-review finding appears, or when setting a sentrux baseline in a new repo.
---

# Quality gates

- `sentrux gate` is the "don't let it get worse" regression block. Only an explicit DEGRADED verdict blocks (exit 2); pre-existing debt never blocks. Run it synchronously.
- Run the advisory parts (`sentrux check`, `fallow audit`) in the background so they never hold up the turn, and read their findings on the next turn.
- New repo: `sentrux gate --save .` to set the baseline. Stale numbers: `rm .sentrux/cache.bin`.
- Gotchas: sentrux misreads functions containing backtick regex literals (a lone size flag is a likely false positive); fallow can flag re-exported symbols as unused - verify before deleting.
- When a repository has a Sentrux baseline, run `sentrux gate .` before handing off code changes. Preserve the existing score; do not refactor merely to raise it.
- Codex advisor: pull-based. Invoke `codex` yourself when you want a second opinion. Do not wire a diff review to every edit or stop event: it fires once per edit, costs git churn each time, and in practice produced nothing. Reviewing a plan once, when it is final, is worth it.
- Keep local quality tooling local unless the user explicitly asks to change CI.
