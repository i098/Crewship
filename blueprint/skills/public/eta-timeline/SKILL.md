---
name: eta-timeline
description: Use when the operator asks for an ETA, a timeline, or when something will be done. Answer with this timeline chart (a PNG), not a list.
---

# Answer ETA questions with the chart

A list hides overlap and slip. When the operator asks for an ETA, a timeline, or when something will be done, draw the chart and show it. Do not answer with a list.

The chart is an 840 px wide PNG (630 px minimum tall) for iMessage. It has a time axis in the operator's local time with AM/PM ticks, one bar per item from start to ETA with the duration inside, a red "now" line, a legend, and items grouped by project. A done item is a green dot. A moved item (the ETA slipped) is amber. A planned item is blue. An item with start equal to end is a dot.

## Steps

1. Write the items to a JSON file outside the repository, for example `/tmp/eta.json`:
   `[{"label": "0.4.3 release", "group": "Crewship", "start": "2026-10-12T16:30", "end": "2026-10-12T17:30", "state": "planned"}]`
   `state` is `planned`, `done` or `moved`. A time without an offset is read in the operator's timezone.
2. Run the script that sits next to this file. It needs headless Chrome (`CHROME` overrides the path):
   `eta_timeline.py /tmp/eta.json --tz America/Los_Angeles`
   It prints the path of a temp PNG. Delete that file after you use it. Do not keep these images: pass `--out` only when a file must persist.
   Add `--now ISO` to fix the now line (default: the current time).
3. Look at the PNG before you send it. Then show it to the operator. To send it over iMessage, run the script with `--send "caption"` and no `--out`. It renders to a temp file, runs `fm-imessage --image`, and deletes the file right after. Add `--card` to send a timeline card with `fm-imessage --card -` first (the caption is the title); the PNG then goes only when cards are off. It stops with a message when `fm-imessage` does not exist. With `--send` you cannot look first: render once without it to check.

## Install

Crewship installs this skill with every other public skill: an apply copies it to `~/.omp/agent/skills/eta-timeline/` for omp and `~/.claude/skills/eta-timeline/` for Claude Code (see [Skills](../../../../docs/omp.md#skills)). To install it by hand, copy this folder to both paths.
