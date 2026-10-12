---
name: always-on-skills
alwaysApply: true
description: Output shaping and working method that apply to every session, not on request.
---

# Always-on skills

Three projects define how agents on this host write and work, so they apply to
every session rather than being selected when they happen to look relevant. Two
mechanisms carry them, and the split is the point:

**Extensions hold state.** All three are installed as omp plugins (`omp plugin list`).
The ponytail and i-have-adhd extensions load at session start; caveman has no omp extension.
The `ADHD ON` and `ponytail: FULL` status entries come from `ctx.ui.setStatus`, which a skill cannot call.
`i-have-adhd` injects its own ruleset whenever its settings file sets
`alwaysOn: true`, and turns off only on "stop adhd mode" or "normal mode".
It also ships `disable-model-invocation: true`, so it is hidden from
model-initiated selection and could never activate as a skill on its own.

**This rule covers what an extension does not.** Loading an extension does not
put a skill's body in the prompt, so read these at the start of a session and
keep them in force:

- `skill://ponytail` — working method. Write the least code that works; delete
  more than you add.
- `skill://caveman` — evidence discipline and compressed output. Investigate
  before changing, and carry proof rather than assertion.

The bodies are not inlined here on purpose: the three run to roughly 20 KB
together, and this rule is injected into every system prompt on every turn.
Naming them costs a few lines and one read; inlining them would tax every turn
of every agent for content that one read already delivers.

If a later instruction in the session conflicts with the output shaping, the
later instruction wins for that turn; the shaping resumes afterwards unless the
reader turned it off explicitly.
