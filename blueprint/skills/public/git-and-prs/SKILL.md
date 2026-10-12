---
name: git-and-prs
description: Use before writing a commit message, editing a CHANGELOG or generated file, or opening, sizing, or splitting a pull request. Requires ponytail-review on every PR diff.
---

# Commits

- When writing commit messages, NEVER auto-add your agent name as co-author.
- Never manually modify CHANGELOG.md files or any files that are marked as auto-generated.

# Pull request size

There is no line cap. A number was the wrong gate: it passed bloated 400-line PRs and blocked lean 700-line ones.

The real question is whether the diff contains anything that should not exist. Ask ponytail, not a counter.

Before opening any PR, run the ponytail review on the diff:

```
ponytail-review                      # uncommitted work
ponytail-review origin/main          # this branch against a base
git diff main... | ponytail-review --stdin
```

- It names what to cut: reinvented stdlib, unneeded dependencies, speculative abstractions, dead flexibility.
- **Cut everything it names**, then run it again.
- **Exit 0** = `Lean already. Ship.` The size is justified whatever the number says. Open the PR.
- **Exit 2** = findings remain. Cut them.
- **Exit 1** = the gate could not run (plugin missing, agent missing, empty diff). **Report that. It is never a pass.**

Use `ponytail-review`, not the `/ponytail-review` slash command: the slash command is a Claude plugin and is unavailable under other harnesses, so workers on pi could not run it. The wrapper builds its prompt from the plugin's own files, so it is the same review from anywhere.

A large lean diff is fine. A small bloated one is not.

## Splitting

Split when the change has genuinely independent seams, not because a total looked big.
Split along seams that stand up on their own: contracts and types first, then implementation, then callers, then docs.
A split that leaves an intermediate PR broken or untested is not a split - rework the seam instead.

## What a reviewer needs said

State these in the PR body, because they change how the diff should be read:

- A pure move or rename with no content change - say so explicitly so it is not read line by line.
- A merge commit reconciling upstream history - reviewed by provenance, not by line.
- Generated artifacts and lockfiles - name them so they are skipped.
- A ponytail finding deliberately NOT cut - name it and say why it earns its place.

Never ship a diff you have not put through ponytail, and never pad the "skip this" list to make a diff look leaner than it is.
