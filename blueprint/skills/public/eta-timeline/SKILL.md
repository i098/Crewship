---
name: eta-timeline
description: Use when the operator asks for an ETA (when the current task or tasks finish) or a timeline (how long a project needs to reach its full vision). Answer with the timeline chart (a PNG), not a list.
---

# Answer ETA and timeline questions with the chart

A list hides overlap and slip. Draw the chart and show it. Do not answer with a list.

## Choose ETA or timeline

Pick the view from the question. Do not mix the two in one chart.

| Question | View | Covers | Items |
|----------|------|--------|-------|
| "ETA?", "when will this be done?", "when does this task finish?" | ETA | Current task or tasks only | One bar per current task, from start to its expected finish |
| "timeline", "how long to the full vision?", "when will project X be complete?" | Timeline | Each project's full vision | Phases of the project, each with an estimated date |

- An ETA never covers the remaining project vision. It stops when the current task or tasks finish.
- A timeline never shows only the current task. It shows every phase up to the end of the vision.
- If the operator asks for both, draw two charts: one ETA chart and one timeline chart.

## Definitions

- **ETA**: the expected finish time of the current task or tasks. It answers when the work in progress ends.
- **Timeline**: the estimated path of a project from today to its full vision. It shows phases with estimated dates, so the operator can see how long each project needs.
- **Estimate**: a date that is not confirmed. Label every estimated date as an estimate in the caption.

## Use evidence for dates and progress

- Check dates, percentages and task states against the repository, tracker, or operator before you draw.
- If no finish date was supplied, estimate it from evidence such as remaining work, measured throughput, dependencies, or review time.
- State that evidence in the caption and mark the finish date as an estimate.
- If the evidence does not support a finish estimate, say so and mark the item `TBD` in the caption without a bar.
- Never infer completion from elapsed time. Omit `percent` when completion is unknown.
- Show every assumption in the caption, for example "assumes one reviewer per PR" or "assumes no slip from CI".

## Chart format

The chart is an 840 px wide PNG (630 px minimum tall) for iMessage.
It has a time axis in the operator's local time, with AM/PM ticks for short ranges and date ticks for long ranges.
Each item has a bar from start to end, a duration, and a percent complete when known ("40% · 1 h 30 min").
A darker fill shows the known completed part; an item without a percent shows only its duration, with no completion fill.
The chart has a red "now" line, a legend, and items grouped by project.
A done item is a green dot.
A moved item (the end slipped) is amber.
A planned item is blue.
An item with start equal to end is a dot.

For an ETA chart, group items by project and show only the current tasks. For a timeline chart, group items by project and use one group per phase row, with the estimated date as the end.

## Steps

1. Write the items to a JSON file outside the repository, for example `/tmp/eta.json`.
   - ETA example (current tasks only):
     `[{"label": "0.4.3 release", "group": "Crewship", "start": "2026-10-12T16:30", "end": "2026-10-12T17:30", "state": "planned"}]`
   - Timeline example (phases of one project, each with an estimated end):
     `[{"label": "Phase 1: sign-in", "group": "Landing (estimate)", "start": "2026-10-12T16:30", "end": "2026-10-14T12:00", "state": "planned"}, {"label": "Phase 2: billing (estimate)", "group": "Landing (estimate)", "start": "2026-10-14T12:00", "end": "2026-10-20T17:00", "state": "planned"}]`
   - `state` is `planned`, `done` or `moved`. `percent` (0-100) is optional: without it the chart shows only the duration, not a completion value. A given value is clamped to 0-100. Example: `{"label": "Mobile pass", "group": "Landing", "start": "2026-10-12T16:30", "end": "2026-10-12T18:00", "percent": 60}`. A time without an offset is read in the operator's timezone.
2. Run the script that sits next to this file. It needs headless Chrome (`CHROME` overrides the path):
   `eta_timeline.py /tmp/eta.json --tz America/Los_Angeles`
   It prints the path of a temp PNG. Delete that file after you use it. Do not keep these images: pass `--out` only when a file must persist.
   Add `--now ISO` to fix the now line (default: the current time).
3. Look at the PNG before you send it. Then show it to the operator. Check that every estimate has an estimate label and every assumption appears in the caption. To send it over iMessage, run the script with `--send "caption"` and no `--out`. It renders to a temp file, runs `fm-imessage --image`, and deletes the file right after. Add `--card` to send a timeline card with `fm-imessage --card -` first (the caption is the title); the PNG then goes only when cards are off. It stops with a message when `fm-imessage` does not exist. With `--send` you cannot look first: render once without it to check.

## Install

Crewship installs this skill with every other public skill: an apply copies it to `~/.omp/agent/skills/eta-timeline/` for omp and `~/.claude/skills/eta-timeline/` for Claude Code (see [Skills](../../../../docs/omp.md#skills)). To install it by hand, copy this folder to both paths.
