---
name: clean-code-comments
description: Use when you write, review, or delete a code comment, docstring, TODO, license header, commented-out code, author tag, or changelog comment, or when a comment looks redundant, misleading, or out of date.
---

# Clean code: comments

The best code needs no comment.
A comment is for what the code cannot say.
A wrong comment is worse than none, because comments do not change when code changes.
These rules come from the s4.codes "clean code" series (the comments chapter of Robert C. Martin's *Clean Code*).

## Write a comment only to...

1. **Explain intent or a business decision** the code cannot show.
2. **Translate** a pattern or math into plain words.
3. **Warn** about a consequence, so nobody "cleans up" a deliberate choice.
4. **Amplify** a detail that looks small but matters.
5. **Record a TODO** for work that cannot happen yet. Keep a reason and a tracker link, not a delay.
6. **Document a public API** for people who will not read the implementation.

```ts
// Business rule: the free tier stops at 3 projects. Do not raise without product sign-off.
const FREE_TIER_PROJECT_LIMIT = 3;

// Do not share one formatter: SimpleDateFormat is not thread-safe.
const fmt = () => new SimpleDateFormat("yyyy-MM-dd");

// Add one day so users west of UTC do not see early expiry.
const expiresAt = addDays(issuedAt, ttlDays + 1);

// TODO(#412): remove when Chrome fixes the clipboard bug.
```

A public API comment has five parts: what it does, what goes in, what comes out, what can go wrong, and a usage example.
Put a standard license reference (not the full text) at the top of the file.

## Do not write

### Redundant or noise comments
If the code already says it, the comment is clutter.
It doubles the lines to scan, needs updating on every change, and trains readers to skip every comment.
Do not accept a "comment on every function" rule.

```ts
// Don't
// If there are no items in the cart, return early.
if (cart.isEmpty()) return;

// Do
if (cart.isEmpty()) return;
```

### Misleading comments
A comment that is "technically true" but hides what the code does makes the reader stop reading.
```ts
// Don't: non-premium users also get a discount
// Returns the discount for premium users.
function discount(user: User) { return user.premium ? 0.2 : 0.05; }
```

### Mumbling comments
Do not write "not sure if this works" or "handle RJ's edge case".
Write the constraint as a specific TODO, or delete the comment.

### Comments on code you do not control
"Default timeout is 5000 ms" in a setter will be wrong the day someone changes the default elsewhere.
Keep a comment about the code next to it.

### Historical essays
"Dave from 2018, RFC 7231, a bug in a dead dependency" is history.
Delete it.
The code and version control already say what matters today.

### Comments that need a comment
If the reader cannot tell which part of `x * 4 + 12` is the "header", name the parts (`HEADER_ROWS`, `PADDING`) and remove the comment.

### HTML tags in comments
Use plain text. The reader sees the raw text in the editor.

### Apologies for structure
- Closing-brace comments (`} // end while`): the function is too long. Shorten it.
- Position markers (`// ===== AUTH =====`): the file does too much. Split it.
- A marker is acceptable only when a framework forces one boilerplate file to split into groups.

### What version control already holds
Delete all of these:
- Commented-out code. Version control has every line.
- Author attributions (`// by Dana`). They go stale.
- Journal or change-log comments. `git log` does it better.

## Checklist

- [ ] The comment explains why, a warning, or public API use. It does not repeat the code.
- [ ] I tried a better name or a function extraction first.
- [ ] The comment is true now, and would stay true after a nearby change.
- [ ] It is about the code next to it.
- [ ] It names the thing: no "RJ", no "it", no "not sure".
- [ ] It uses plain text.
- [ ] No commented-out code, no author tag, no change journal, no closing-brace or banner comment.
- [ ] Each TODO has a reason and a tracker reference.

## Sources

Reels by `@s4.codes` (TikTok; the Instagram profile is not readable without login):
- Comments lie: https://www.tiktok.com/@s4.codes/video/7606002862673366294
- Good comments (why): https://www.tiktok.com/@s4.codes/video/7606341472094473475
- Protective comments: https://www.tiktok.com/@s4.codes/video/7607457317616946434
- Documentation and legal headers: https://www.tiktok.com/@s4.codes/video/7608583795217829142
- Redundant and noise comments: https://www.tiktok.com/@s4.codes/video/7609708147044945175
- Misleading, vague, and non-local comments: https://www.tiktok.com/@s4.codes/video/7610799453880044822
- Commented code, attributions, and journals: https://www.tiktok.com/@s4.codes/video/7612447996038434070
- Apology and position-marker comments: https://www.tiktok.com/@s4.codes/video/7613411993508269334
- Mumbling, history, and HTML comments: https://www.tiktok.com/@s4.codes/video/7614129768853769494
