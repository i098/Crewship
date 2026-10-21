# Instructions

Rules for this account live in skills, not in this file.
Read the `operating-rules` and `talk-style` skills at the start of every session and keep them in force.
Load any other skill when its description matches the task.

Before a PR is opened or marked ready, run `ponytail-review` exactly one round on its diff: cut what it names, and record any finding you judge wrong as a named keep in the PR body. Never run it twice on one PR. The `git-and-prs` skill has the details.

For code or document search by meaning (you know what the code does but not its name), use `sgrep "<plain-English query>" <path>` first (`-n 10`, `--json`); to rank a focused ripgrep result, pipe `rg --json -C 3 '<pattern>' <path> | sgrep "<query>" --stdin`. Use ripgrep for exact names, text and regexes. sgrep is local: no account and no network after the first model download.
