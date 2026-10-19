---
name: signal-chunks
description: Use when planning a week, setting or checking a deadline or priority, choosing the signal tasks for the next eighteen hours, or applying the Steve Jobs signal and noise idea. Gives the owner's Jobs-inspired method, with one weekly shipping goal, an explicit deadline and timezone, eighteen-hour chunks, three to five signal tasks per chunk, named noise, an eighty-percent effort target, and CHUNK status updates with an on-track, at-risk or late verdict.
---

This is the owner's Jobs-inspired method.
It is not a claim that Steve Jobs used eighteen-hour windows.
The idea comes from Jobs: focus means saying no to good ideas.
Keep the signal.
Name the noise.
Cut or pause the noise.

## Set the week

1. Write one measurable weekly shipping goal.
   Example: "Merge the billing export and deploy it to staging."
2. Write the deadline with a date, a time and a timezone.
   Example: "Friday 18:00 Pacific."
3. Convert the deadline to the local timezone of the owner.
   Use the zone name and the tz database, not a fixed daylight-saving abbreviation.
4. Keep the goal and deadline in the existing tracker.
   Do not create a new planning file, scheduler or dashboard.

## Split into chunks

1. Start at the authoritative start time of the week.
2. Make each chunk eighteen hours long.
3. Clip the final partial chunk at the weekly deadline.
4. Name each chunk by its end time in the owner's local time.

## Pick the signal

For the current chunk, pick three to five signal tasks.
A signal task moves the weekly goal.
Each task needs:

- One concrete outcome, with a file, PR, command or person named.
- One acceptance check that a third person can verify.
- A done checkbox, ticked only with evidence: a link, a command output or a commit.

Do not add a sixth task.
If a new task arrives, pick one current task to pause, or name the new task as noise.

## Name the noise

Noise is work that does not move the weekly goal.
For each noise item, write one line: what it is, and whether it is cut or paused.

- Cut: the work will not happen this week.
- Paused: the work waits. Record what state it is in, so it can restart.

Preserve unlanded work.
Do not delete a branch, a draft or a partial change only because it is noise.

Do not call these noise: safety checks, validation, tests, monitoring and rollback plans.
They protect the signal.

## Effort target

Target eighty percent of effort on signal tasks.
Use this as a target only.
Report a real percentage only when effort is measured, for example by counted task time.
Never invent a completion percentage.

## Publish CHUNK updates

Publish one CHUNK line in these cases:

- After every signal task completion.
- At every chunk rollover.
- At least once an hour.

Use this exact form:

```text
CHUNK goal="..." chunk_end="YYYY-MM-DD HH:MM PT" tasks="[x] a; [ ] b; [ ] c" noise="..." verdict=on-track
```

- `goal` is the weekly shipping goal.
- `chunk_end` is the end of the current chunk, with the timezone of the owner.
- `tasks` lists the signal tasks. Use `[x]` only for finished tasks with evidence.
- `noise` names the cut or paused items.
- `verdict` is `on-track`, `at-risk` or `late`.

Set `at-risk` when a signal task slips past its chunk, or when the weekly goal needs more than the remaining chunks.
Set `late` when the deadline passes before the goal ships.

## Update from real outcomes

Change the tracker only when an outcome changes.
Mark a task done only after its check passes.
Move a task to the next chunk only with a named reason.

## Deadline and ETA are not the vision timeline

The weekly deadline and the current-task ETA answer one question: will this week's goal ship on time?
A full project vision timeline answers a different question: when will the whole project finish?
Do not use a chunk verdict to predict the project finish date.
