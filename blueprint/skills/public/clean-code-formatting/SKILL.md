---
name: clean-code-formatting
description: "Use when you lay out a source file: blank lines between concepts, function order, where to declare variables and class fields, indentation, or when a team argues about brace and quote style."
---

# Clean code: formatting

Good formatting lets code speak before it is read.
These rules come from the s4.codes "clean code" series (the formatting chapter of Robert C. Martin's *Clean Code*).
If the repo has a formatter, the formatter wins over these rules.

## Rules

### 1. Newspaper order: highest-level function first
The headline is the function that says what happens.
Put it at the top.
Put every function directly below its caller, in call order.
A reader who sees a call then finds the definition just below.

```ts
export function monthlyReport() {      // headline
  const data = fetchUserData();
  const report = buildReport(data);
  saveReport(report);
}
function fetchUserData() {}            // defined in call order
function buildReport(data: Data) {}
function saveReport(report: Report) {}
function formatDate(d: Date) {}        // shared helpers, grouped by purpose
function formatScore(n: number) {}
```

Group functions with *conceptual affinity* (`formatDate`, `formatScore`) even when they do not call each other.

### 2. Vertical spacing separates concepts. Density joins them.
- A blank line means "a new concept starts here".
- Related lines stay together, with no blank line between them.
- Do not put a blank line between every line. Do not use none at all.

```ts
function invoiceSummary(invoice: Invoice) {
  const lines = invoice.lines;                 // extract data
  const currency = invoice.currency;

  const subtotal = sum(lines.map(l => l.amount));   // business logic
  const tax = subtotal * taxRate(currency);

  return { subtotal, tax, total: subtotal + tax };  // result
}
```

### 3. Indent every scope level
Each scope gets its own indent.
The indent makes the code a visual hierarchy you can navigate at a glance.

### 4. Declare a local variable next to its first use
A variable declared early is baggage that the reader carries on their mental stack.
Move it into the block, or to the line just before it is used.

```ts
// Don't
let skippedLog: string[] = [];
let report: Report;
for (const u of users) { if (!u.active) { skippedLog.push(u.id); continue; } /* ... */ }
report = build(users, skippedLog);

// Do
for (const u of users) {
  if (!u.active) { const skippedLog = [u.id]; /* ... */ continue; }
}
const report = build(users);
```

### 5. Declare class properties in one place
Class properties are shared by design.
Do not place a property above the one method that uses it. Other methods will not find it.
Choose one place (the top of the class in most languages, the bottom in some) and keep to it.

### 6. Let the team decide the rest
Brace on the same line or the next, tabs or spaces, single or double quotes.
The decision matters less than the single standard.
Automate it with a formatter and a lint rule.

## Checklist

- [ ] The highest-level function is first in the file.
- [ ] Each helper sits below its first caller, in call order.
- [ ] Functions with the same purpose sit together.
- [ ] Blank lines separate concepts. Related lines have none.
- [ ] Indentation shows every scope level.
- [ ] Each local variable is declared next to its first use.
- [ ] Class properties sit in the one place the team chose.
- [ ] A formatter enforces the team style.

## Sources

Reels by `@s4.codes` (TikTok; the Instagram profile is not readable without login):
- Newspaper order, stepdown rule: https://www.tiktok.com/@s4.codes/video/7617091999790796054
- Vertical spacing, density, indentation: https://www.tiktok.com/@s4.codes/video/7617132278875016470
- Variable declaration, class properties, team style: https://www.tiktok.com/@s4.codes/video/7618224597942406422
