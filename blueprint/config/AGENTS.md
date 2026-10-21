# Instructions

Rules for this account live in skills, not in this file.
Read the `operating-rules` and `talk-style` skills at the start of every session and keep them in force.
Load any other skill when its description matches the task.

Before a PR is opened or marked ready, run `ponytail-review` exactly one round on its diff: cut what it names, and record any finding you judge wrong as a named keep in the PR body. Never run it twice on one PR. The `git-and-prs` skill has the details.

When sgrep is installed, use `sgrep "<plain-English query>" <path> -n 10 --json` for code or document search by meaning.
To rank exact matches, pipe `rg --json -C 3 '<pattern>' <path>` into `sgrep "<query>" --stdin`.
Use ripgrep for exact names, text and regexes, or when sgrep is not installed.
sgrep needs no account or network after its first model download.
