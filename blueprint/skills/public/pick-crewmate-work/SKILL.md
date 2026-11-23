---
name: pick-crewmate-work
description: Use when Firstmate needs to pick the next crewmate task from the work graph or assign new research when tracked work has no actionable item.
---

# Pick crewmate work

Use the current goal, the repositories in scope, and the latest task status.
Run the forge lists for each repository in scope.
Pick one actionable item for each available crewmate.
Check for active owners and duplicate records across issues, pull requests, tasks, and backlog entries.
Treat records for the same outcome as one item.
Do not reassign work that has an active owner unless that owner hands it off.
Skip held work, including work with a hold on a linked record.
Skip work that needs an unresolved decision, permission, or prerequisite.
Increase the forge list limit if the result shows only part of the open work.
If an in-scope prerequisite is actionable, consider it as its own item in the order below.

## Take the first actionable item in this order

1. **Open pull requests with failed checks or blockers (unfinished).** List open pull requests with `gh-axi pr list --state open --repo OWNER/REPO`.
   Read the current checks with `gh-axi pr view <number> --checks --repo OWNER/REPO`.
   Read requested changes with `gh-axi pr view <number> --reviews --repo OWNER/REPO`.
   Pick a specific failed check, merge conflict, or requested change the crewmate can fix.
   Skip pull requests that only await checks, review, or an external decision.
2. **Stalled tasks (unfinished).** Read the current Firstmate task status and handoff records.
   Run `bin/fm-tasks-axi.sh list --state in_flight` from the Firstmate home to find task records, not to prove a stall.
   Confirm that work stopped and no worker or pipeline still owns the next action.
   Resume from the last verified result and name the next action.
3. **Unblocked open issues (next).** List open issues with `gh-axi issue list --state open --repo OWNER/REPO`.
   Check dependency records, linked work, and assignments before selecting an issue.
   Take the oldest issue by creation time with no unmet dependencies and no active work.
   Compare exact `created_at` timestamps across repositories with `gh-axi api repos/OWNER/REPO/issues/NUMBER --jq .created_at`.
   Use the issue number to break a tie within a repository.
4. **Backlog (next).** Read the project backlog or run `bin/fm-tasks-axi.sh ready --repo <name>` from the Firstmate home.
   Follow the backlog's recorded order.
5. **New research.** Start research only after checking all four sources and finding no actionable item.
   Pick one unanswered question that affects the current goal.
   Ask for evidence, a recommendation, and the decision the result will inform.
   Keep the task read-only. Do not ask for an implementation.

If a source is unavailable, report which source you could not check.
Do not treat an unavailable source as empty or use it to justify a lower-priority pick.

## Write one brief for the selected item

- **Source:** Name the tier and give the issue or pull request URL, task ID, or backlog reference.
  For research, cite the goal or decision that needs evidence.
- **Why now:** Give the evidence that the item is actionable and that no higher tier has an actionable item.
- **Outcome:** State one result and name the repository and scope.
- **Start here:** Give the first action and the relevant links, files, or last verified result.
- **Done when:** Give a check or a deliverable that proves the result.

Refresh the source and ownership before dispatch.
Use the existing dispatch workflow to record the assignment before selecting work for another crewmate.
If no tier yields a concrete brief, report why instead of dispatching an open-ended task.
