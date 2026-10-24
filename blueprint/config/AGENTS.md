# Instructions

Rules for this account live in skills, not in this file.
Read the `operating-rules` and `talk-style` skills at the start of every session and keep them in force.
Load any other skill when its description matches the task.

Before a PR is opened or marked ready, run `ponytail-review` exactly one round on its diff: cut what it names, and record any finding you judge wrong as a named keep in the PR body. Never run it twice on one PR. The `git-and-prs` skill has the details.

Edit AGENTS.md and CLAUDE.md only through backpass: run `backpass` in the checkout for a project file, or `backpass --scope user` for the global one. For omp sessions set its `harnesses` list to include `pi` and `includeOmp: true`, and pass a model from the host enabled list; never edit by hand. Where Crewship manages the host, also make the edit in blueprint/config/AGENTS.md, because the next apply rebuilds the managed block.

When sgrep is installed, use `sgrep "<plain-English query>" <path> -n 10 --json` for code or document search by meaning.
To rank exact matches, pipe `rg --json -C 3 '<pattern>' <path>` into `sgrep "<query>" --stdin`.
Use ripgrep for exact names, text and regexes, or when sgrep is not installed.
sgrep needs no account or network after its first model download.
