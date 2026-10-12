---
name: progress-bars
description: Use when work has more than a couple of steps. Defines the exact ASCII progress-bar format and the rule that every percentage comes from a real count.
---

# Show progress, do not be a black box

While working on anything with more than a couple of steps, print ASCII progress bars so a human can see where the work actually is without asking.

Exact format, fixed width so stacked lines read as a table:

```
Agent repair   [██░░░░░░░░░░░░]  10%
Batch 7        [████████████░░]  88%
Whole build    [████░░░░░░░░░░]  34%
```

- Label left-aligned and padded to the widest label in the group.
- Bar is exactly 14 cells between `[` and `]`, `█` filled and `░` empty, filled cells = `round(percent * 14 / 100)`.
- Percent right-aligned in 3 characters, then `%`, separated from the bar by two spaces.
- Show the tracks that exist, innermost first: the unit of work in hand, its parent batch, then the whole job. One track is fine; never invent a hierarchy to fill lines.

**Every percentage must come from a real count you can name**: tests passed over total, files migrated over total, steps done over planned, subtasks merged over opened. Derive it as `done / total`, and be ready to say what the two numbers were.

**Never invent a number to look busy.** A fabricated 34% is worse than no bar, because it reads as measurement. When there is no countable denominator, print the honest shape instead and skip the bar:

```
Root cause     step 3, total unknown - still narrowing
```

Print a group when progress genuinely moves - a step completing, a batch finishing, a status update - not on every line, and not on a timer. Re-print the whole group each time rather than a single changed line, so the latest block always shows the full picture.

A bar never replaces the substance. It sits above or below the sentence that says what happened and what is next; it is not the report.
