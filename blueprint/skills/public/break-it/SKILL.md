---
name: break-it
description: "Use after you build or change a UI or feature, before you call it done: try to break it with worst-case input (very long names, huge lists, unusual emails, long labels, empty and unicode data, narrow screens), then fix what breaks. Source: https://x.com/emilkowalski/status/2103516287452483885"
---

# Break it

Source: Emil Kowalski, https://x.com/emilkowalski/status/2103516287452483885: ask the AI to try to break what it built, with lots of data, long names, unusual emails and labels. Worst case first.

Use this after the happy path works. Do not stop at the demo data.

## Worst-case inputs

Try each input that applies to the field, list or screen you built:

- Long text: a name or title of 300+ characters with no spaces, and one with spaces.
- Huge lists: 1,000+ rows, and a single row with 500+ tags or options.
- Unusual emails: a local part of 64+ characters with `+` and dots, a long multi-label domain, quoted local parts, and 254-character addresses.
- Long labels and buttons: translated or long words that push the layout.
- Empty and missing data: empty string, whitespace only, `null`, zero items.
- Unicode: RTL text, combining marks, emoji, CJK, zero-width characters.
- Numbers: `0`, negative, `Number.MAX_SAFE_INTEGER`, decimals with 10+ places.
- Narrow screens: 320 px width, large zoom, and text scaled to 200%.

## Loop

1. List the inputs that apply to what you built.
2. Enter each one in the real UI, or call the real function or endpoint.
3. Record what breaks: overflow, clipped text, lost data, error, crash, slow render.
4. Fix the root cause in the shared code, then repeat step 2 for the same input.
5. Stop when every applicable input passes.

## Proof

- For a UI, attach a screenshot of the worst-case input after the fix.
- For logic, add a test or show the command output for the input that failed before.
- Name each input you tried and whether it passed. Do not claim an input you did not try.
