---
name: tooling-conventions
description: Use when installing dependencies, picking a package manager, or choosing a tool for GitHub, visual plans, pushing, herdr, no-mistakes, skill installs, or caveman/ponytail modes. Use bun for JS packages.
---

# Package manager

- Use bun, not pnpm, npm, or yarn. If a repo has only `package-lock.json`, `pnpm-lock.yaml`, or `yarn.lock`, run `bun install` to generate `bun.lock` and remove the old lockfile rather than falling back to another manager.

# On-demand tooling (details live in skills and hooks - do not preload)

- Cross-chat coordination: where a SessionStart hook creates the repo's herdr workspace and this session's pane (ids appear in context as "herdr: workspace=... own_pane=..."), the herdr skill has the peer/messaging API. Never launch the herdr TUI.
- Visual plans/reports: lavish skill. Build an HTML artifact, open with `npx -y lavish-axi <file>`, user annotates in browser, collect feedback via `npx -y lavish-axi poll`. Plans still show current state AND the planned change.
- GitHub ops: gh-axi skill (`npx -y gh-axi`) over raw `gh` or GitHub MCP.
- Pushing work: in repos with a no-mistakes gate, `git push no-mistakes` instead of origin; one-time `no-mistakes init` per repo sets it up.
- New agent skills: scan with `skillspector scan <skill-dir> --no-llm` BEFORE installing. Scan the installable skill dir, not the whole repo (repo-wide scans false-positive on test fixtures).
- Caveman governs prose, ponytail governs code. Orthogonal modes, banners injected at SessionStart; setting one never changes the other.

# Delivery tooling

- Use `gh-axi` for GitHub operations, Graphify for repository maps, Lavish for rich review surfaces, and `no-mistakes` for full delivery pipelines when its branch, commit, push, and PR workflow is authorized.
- Run `no-mistakes` pipelines in the background and monitor with `no-mistakes axi status`; do not block on sleep or polling loops.
- Auto-fix no-mistakes review findings by default; still escalate findings that change user intent, scope, or destructive behavior.
- Let Headroom and Herdr hooks manage their own session setup when installed.
