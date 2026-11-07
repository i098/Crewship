---
name: usage-card
description: Use when the operator asks about usage, quota, resources, server load or disk. Answer with this card (a PNG), not a list.
---

# Answer usage and resource questions with the card

A list of numbers is hard to read on a phone. When the operator asks about usage, quota, resources, server load or disk, send the card. Do not answer with a list.

The card is an 840 px wide image (630 px minimum tall). It shows the 5 h and 7 d use of Claude and Codex, averaged across accounts, each with its soonest reset. It also shows server load, RAM and the mounted disks.

## Steps

1. Run the helper that the Crewship `firstmate` profile installs in `~/.local/bin/`:
   `f=$(mktemp --suffix=.png) && fm-usage-brief --png "$f"`
   Without `--png` it prints the same figures as text.
2. Look at the PNG. Then send it with `fm-imessage --image "$f"`, and delete it right after: `rm -f "$f"`. Do not keep these images.
3. To card any other short update, run `fm-text-card "$f" < text`, with a temp file the same way.
4. For a status update or a review of the projects, run `fm-status-card --send < status` instead. It sends a visual card 1170 px wide: one row per project with a progress bar, the merged, open and today counts, and state chips, plus load, RAM and disk gauges. Write each project as `- name: merged 4, open 2, today 3, running`. The states are `live`, `running`, `waiting on you` and `blocked`. Other parts of the line become a note. The input can also be JSON (see the header of `fm-status-card`). Add `--light` for the light theme. Compute `today_since` as `fm-status-card --today-start`: local midnight in the owner's time zone (`STATUS_CARD_TZ`, else `TZ`, else the host zone). Count "today" from it and pass it in a JSON input as `today_since`. The card footer then names that zone; without `today_since` it prints no zone footer.

## Hourly reminder

While the operator texts, `fm-usage-remind` sends this card at most once an hour. It runs as a second `ExecStart` of the stall nudge service. `crewship_usage_remind_every` sets the interval (default 3600 seconds) and `crewship_usage_disks` sets the mounts.

## Note

`fm-usage-brief`, `fm-usage-remind`, `fm-text-card` and `fm-status-card` ship in the `blueprint/maintenance/` folder. If they are not on `main` on your host, the commands do not exist yet: say so and do not invent the figures.

## Install

Crewship installs this skill with every other public skill: an apply copies it to `~/.omp/agent/skills/usage-card/` for omp and `~/.claude/skills/usage-card/` for Claude Code (see [Skills](../../../../docs/omp.md#skills)). To install it by hand, copy this folder to both paths.
