---
name: pick-crewmate-work
description: Use when Firstmate needs to pick the next crewmate task from the work graph or propose new research when tracked work has no actionable item.
---

# Pick crewmate work

Covers GitHub repositories; for a Forgejo-hosted project, list its issues and PRs with that forge's tool.

Use the current goal, the repositories in scope, and the latest task status.
Pick at most one actionable item for each available crewmate.
Check for active owners and duplicate records across issues, pull requests, tasks, and backlog entries.
Treat records for the same outcome as one item.
Do not select the same outcome twice in one run.
Do not select work that has an active owner unless that owner hands it off.
Skip held work, including work with a hold on a linked record.
Skip work that needs an unresolved decision, permission, or prerequisite.
Use only read-only sources when picking work.
For stalled tasks and linked outcomes, read existing Firstmate task records, status lines, handoff records, and current PR state.
Exclude a task or linked outcome as complete or in review only if the evidence shows it landed or only awaits review.
A raw `done:` line or a passed run alone does not prove either.
Run the forge lists for each GitHub repository in scope.
For each open pull request or issue list, accept the list as complete if the returned count matches an exact total.
Increase `--limit` if the exact total exceeds the returned count or if the total is unknown and the list reaches the limit.
If the total is unknown and a successful list returns fewer records than requested, accept the list as complete.
Apply the same rules to the larger list.
Treat the source as incomplete if you cannot confirm that the list contains all open records.
If an in-scope prerequisite is actionable, consider it as its own item in the order below.

## Take the first actionable item in this order

1. **Open pull requests with failed checks or blockers (unfinished).** List open pull requests with `gh-axi pr list --state open --repo OWNER/REPO --limit 30`.
   Read the current checks and `merge_state` with `gh-axi pr view <number> --checks --repo OWNER/REPO`.
   If the branch is `BEHIND`, check whether the base branch's merge rules require an update.
   Read the review history with `gh-axi pr view <number> --reviews --repo OWNER/REPO`.
   Confirm that a specific change request still applies to the current PR before selecting it.
   Do not use a request that a later approval from the same reviewer, a dismissal, or a PR update invalidates.
   Pick a failed check, merge conflict, current change request, or confirmed required branch update the crewmate can fix.
   Skip pull requests that only await checks, review, or an external decision.
2. **Stalled tasks (unfinished).** Find candidates in `state/<task-id>.meta` records from the Firstmate home.
   Skip records with `mode=secondmate` because they describe persistent agents, not work items.
   Use linked backlog rows as evidence, not as a requirement for a candidate.
   Confirm that unfinished work stopped and no worker or pipeline still owns the next action.
   If validation passed but a required PR was never opened, consider opening it as the next action.
   Pick up from the last verified result and name the next action.
3. **Unblocked open issues (next).** List open issues with `gh-axi issue list --state open --repo OWNER/REPO --limit 30`.
   Treat confirmed disabled issues as not applicable for that repository.
   Treat access failures and unknown results as unavailable, not as disabled.
   Check dependency records, linked work, and assignments before selecting an issue.
   Choose an actionable issue based on the current goal.
4. **Backlog (next).** Run `bin/fm-tasks-axi.sh ready` once from the Firstmate home.
   Select only actionable entries from `ready`, not from `ready_public_followups`.
   Apply the repository scope to the returned entries, including untagged entries that identify their repository through a link.
5. **New research.** Propose research only after checking all applicable sources and finding no actionable item.
   Pick one unanswered question that affects the current goal.
   Ask for evidence, a recommendation, and the decision the result will inform.
   Keep the task read-only. Do not ask for an implementation.

Report any source that is unavailable or incomplete.
Do not treat such a source as empty or use it to justify a lower-priority pick.

## Write one brief for the selected item

- **Source:** Name the tier and give the issue or pull request URL, task ID, or backlog reference.
  For research, cite the goal or decision that needs evidence.
- **Why now:** Give the evidence that the item is actionable and that no higher tier has an actionable item.
- **Outcome:** State one result and name the repository and scope.
- **Start here:** Give the first action and the relevant links, files, or last verified result.
- **Done when:** Give a check or a deliverable that proves the result.

Return the briefs without dispatching work or recording assignments.
If no tier yields a concrete brief, report why.
