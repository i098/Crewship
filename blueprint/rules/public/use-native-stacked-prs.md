---
name: use-native-stacked-prs
description: "Use GitHub native stacked PRs instead of manually rewriting branch history"
condition: "(?i)rebase[^\\n]{0,160}onto[^\\n]{0,160}retarget\\s+PR\\s+\\d+"
scope: "tool:write(*.md)"
---

When the user asks for stacked PRs, use GitHub's native stacked-PR workflow and inspect its current stack state first. Do not manually rebase branches, retarget PR bases, force-push, or write a custom restack plan. If native support is unavailable, report that blocker before changing history.
