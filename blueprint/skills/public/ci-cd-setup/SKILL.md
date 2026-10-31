---
name: ci-cd-setup
description: Use when you set up or repair CI/CD for a repository, make CI faster, choose required checks and merge rules, or review a workflow before it ships.
---

# CI/CD setup

Ordered steps for a new repository. Do them in this order. The steps come from how this fleet sets up its own CI, plus the speed ideas in Owen Gretzinger's article "How I made our CI 20x faster": https://x.com/owengretzinger/status/2116291924219060319

Agents push, wait for CI, fix the red check and push again. A slow CI is what an agent waits on, so treat CI as a product.

## Steps

1. **Use the repository's own commands.** CI runs the same lint, test and build commands a developer runs. Lock the dependencies (a lockfile, `--locked`). Write no CI-only logic that you cannot run on a laptop.
2. **Set a least-privilege token.** Put `permissions: contents: read` at the top of the workflow. A job that needs more asks for it by name. Pass secrets to the one step that needs them. Do not persist the checkout credentials (`persist-credentials: false`).
3. **Pin every third-party action to a commit SHA.** Write the tag in a trailing comment, for example `# v7.0.1`. Add a Dependabot entry (`package-ecosystem: github-actions`, weekly) so the pins move with each release. A pin bump needs no changelog fragment.
4. **Pick the runners.** The default hosted runners can wait minutes for a machine. Article advice: move every job, including the small ones, to faster runners, because a 5-second job that waits 10 minutes is a 10-minute job. If you own a host, run a pool of one-job runners on it (see the CI pool doc in this repository) and set `runs-on: [self-hosted, <label>]`. Hosted minutes can run out; a self-hosted pool keeps CI running then.
5. **Classify the change first.** A first `changes` job reads the changed paths and outputs `code=true|false`. Documentation-only PRs skip the heavy jobs. Count skills, rules and config files as code even when they are Markdown. Check both the old and the new path of a rename. If a push to the default branch has no diff to read, treat it as code.
6. **Run the jobs in parallel.** Lint, typecheck, build and tests start at the same time, so a PR takes as long as its slowest job. Then look at what the slowest job also does, and move that work into its own job.
7. **Make lint and typecheck fast.** Agents do not tire of strict rules, so turn on every rule you can. The article swaps ESLint for Oxlint and moves to each faster typechecker as it ships. Measure on your own repository before you switch.
8. **Split slow tests.** Shard a slow test target onto bigger machines, each shard with its own database. The article found that more cores helped more than more shards. Match test concurrency to the cores: half the concurrency was as fast and ended a flaky test. If you share one app instance between test files, add a hook that resets state after each file, and tell agents what a test must clean up.
9. **Fix the setup time.** Audit the last 150 runs: split each job into waiting, setup and running. Cache the dependencies, and seed the cache from the default branch, because GitHub scopes a PR cache to its own branch. Use a blobless clone (`filter: blob:none`), not a shallow one, because a shallow clone breaks tools that read history.
10. **Run only what the PR touches.** Use an affected-projects tool, and run the full suite every night on the default branch. Test the skip logic: hide a change on purpose and check that the run fails, not that every job skips and reports green.
11. **Make a skipped required check report.** Use job-level `if:` conditions, not workflow-level path filters. A required check that never starts stays pending and blocks the merge. A failed, cancelled or skipped validation job must never give a green result.
12. **Set concurrency.** Cancel an old run of the same PR when a new push arrives. Give each push to the default branch its own group (by SHA), because GitHub replaces a pending run in the same group. Set `timeout-minutes` on every job. Do not start a run on label events; a label added while opening a PR started a second run that cancelled the first.
13. **Add the quality gate.** When the repository has a Sentrux baseline, run `sentrux gate .` on code PRs. Only an explicit DEGRADED verdict, or an unavailable verdict, blocks. Old debt never blocks. Save the first baseline with `sentrux gate --save .`. Run advisory tools (`sentrux check`, `fallow audit`) as warnings. See the `quality-gates` skill.
14. **Add the PR body check.** A small required job checks that the body starts with `Closes #N`, that every template section has text, and that each checklist item is ticked or explained. Give it its own workflow that runs on `edited`, so a body fix reruns only that check. Run the checker's own tests in the same job.
15. **Add the changelog check.** Each PR adds a fragment file (`changelog.d/<issue>.<type>.md`) and never edits the generated changelog. A `no changelog` label skips the check. Put this check in its own workflow so a label change reruns only it.
16. **Add a pre-push hook.** Run format, lint and typecheck on the changed files. An agent that sees a type error in seconds fixes it before it waits for CI. Use a hook, not a line in AGENTS.md, because agents skip steps.
17. **Set the branch rules.** Use rulesets with no bypass: the default branch changes only through a PR; no force push or delete; delete the head branch after a merge; a release tag cannot move or be deleted. Name the checks that must pass or report an allowed skip.
18. **Merge with a merge commit.** Turn off squash and rebase merging, so the history keeps each commit and its provenance.
19. **Ship the PR the same way each time.** One concern per PR. Open it as a draft, and mark it ready only when every check is green and the body is correct. Put real test evidence in the body, and tick only the boxes you ran. Run one review round on the diff before you open the PR (see `git-and-prs`).
20. **Check the cost.** Faster CI costs more. The article's bill went from $230 to $4,300 a month and was still cheap next to waiting agents. Set the pool size or spend limit on purpose.

## Checklist

- [ ] CI runs the repository's own locked commands.
- [ ] Workflow token is read-only; extra rights are per job.
- [ ] Every action is SHA-pinned; Dependabot keeps the pins fresh.
- [ ] No job waits long for a runner; no minutes limit can stop CI.
- [ ] A `changes` job classifies paths; docs-only PRs skip the heavy jobs.
- [ ] Lint, typecheck, build and tests run in parallel; the slowest job is under a few minutes.
- [ ] Dependency cache is seeded from the default branch; clone is blobless.
- [ ] A test proves that the skip logic cannot hide a real change.
- [ ] Skipped required checks report; failed or cancelled jobs never pass.
- [ ] Concurrency, `timeout-minutes` and label handling are set.
- [ ] Quality gate blocks only regressions.
- [ ] PR body check and changelog check are required, each in its own workflow.
- [ ] Pre-push hook runs format, lint and typecheck.
- [ ] Rulesets protect the default branch and release tags.
- [ ] Merge commits only; PRs are draft until green.
