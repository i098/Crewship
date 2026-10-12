---
name: process-safety
description: Use before killing a process, starting a long-lived test service, or starting dev servers in a parallel worktree. Never kill by a broad command-line pattern.
---

# Process safety

- **Never kill a process by a broad `pkill -f` pattern.**
  A pattern such as `pkill -f 'target/release/<app>'` can kill a live service, because another build path on the same machine holds that substring; a supervisor restart can hide the outage.
  Resolve the pid first - `pgrep -x <name>` or `pgrep -af <pattern>`, read what it names, then `kill <pid>`.
  Remember that `pkill -f` also matches the shell command line running it, so a loose pattern kills your own session.
- Run a long-lived test service from a scratch path such as `/tmp`, never from the repo's `target/`.
  A supervisor watching the product's binary path will kill or restart anything whose path matches it.
- For parallel worktrees, assign an unused frontend/API port pair to each worktree before starting services; keep the default pair for the primary worktree. Do not start a fixed-port launcher when it would conflict.
