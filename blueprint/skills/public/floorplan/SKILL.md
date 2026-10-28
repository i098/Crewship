---
name: floorplan
description: Use when you need to map or explain a codebase, onboard to a repository, or see what a change touched with an interactive map.
---

# Map a codebase with Floorplan

Floorplan is a third-party Claude Code plugin that reads a codebase and creates an interactive, plain-English map with a health check.

Use it to understand a repository, support onboarding, or see what a change touched.

## Install

Run these commands in Claude Code:

```sh
claude plugin marketplace add haydenschmitty/floorplan
claude plugin install floorplan@floorplan
```

Ask Claude Code for a floorplan of the codebase.

Floorplan writes its output to `floorplan/` in the repository root.

Floorplan also adds a section to `CLAUDE.local.md`.

The Ask bar reads the real code when the Claude Code CLI is installed.

## Source

This skill points to the third-party Floorplan plugin by haydenschmitty, listed in [CREDITS.md](../../../../CREDITS.md).
The plugin is licensed under MIT.
