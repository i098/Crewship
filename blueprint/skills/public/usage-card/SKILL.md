---
name: usage-card
description: Use when the operator asks about usage, quota, resources, server load or disk. Answer with this card (a PNG), not a list.
---

# Answer usage and resource questions with the card

A list of numbers is hard to read on a phone. When the operator asks about usage, quota, resources, server load or disk, send the card. Do not answer with a list.

The card is an 840 px wide image (630 px minimum tall). It shows the 5 h and 7 d use of Claude and Codex, averaged across accounts, each with its soonest reset. It also shows server load, RAM and the mounted disks.

## Steps

1. Run the helper that the Crewship `firstmate` profile installs in `~/.local/bin/`:
   `fm-usage-brief --png /tmp/usage.png`
   Without `--png` it prints the same figures as text.
2. Look at the PNG. Then send it with `fm-imessage --image /tmp/usage.png`, or show it to the operator.
3. To card any other short update, run `fm-text-card OUT.png < text`.

## Hourly reminder

While the operator texts, `fm-usage-remind` sends this card at most once an hour. It runs as a second `ExecStart` of the stall nudge service. `crewship_usage_remind_every` sets the interval (default 3600 seconds) and `crewship_usage_disks` sets the mounts.

## Note

`fm-usage-brief`, `fm-usage-remind` and `fm-text-card` ship in the `blueprint/maintenance/` folder with the `feat/cf-port-usagecard` change. If that change is not on `main` on your host, the commands do not exist yet: say so and do not invent the figures.

## Install

Crewship installs this skill with every other public skill: an apply copies it to `~/.omp/agent/skills/usage-card/` for omp and `~/.claude/skills/usage-card/` for Claude Code (see [Skills](../../../../docs/omp.md#skills)). To install it by hand, copy this folder to both paths.
