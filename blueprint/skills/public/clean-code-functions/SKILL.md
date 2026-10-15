---
name: clean-code-functions
description: "Use when you write, split, or review a function or method: size, one responsibility, abstraction level, argument count, boolean flags, side effects, switch statements, command-query separation, or duplicated code."
---

# Clean code: functions

A function is the first unit of organization.
It must be small, do one thing, and read like a short story.
These rules come from the s4.codes "clean code" series (the functions chapter of Robert C. Martin's *Clean Code*).

## Rules

### 1. Small, then smaller
Long functions bury the logic under detail.
Name the low-level steps, move loops out, and keep the body of each `if`, `else`, and `while` to one line (a call).

```ts
// Don't
function upload(file: File) {
  if (file.size > LIMIT) {
    const chunks = [];
    for (let i = 0; i < file.size; i += CHUNK) chunks.push(file.slice(i, i + CHUNK));
    for (const c of chunks) { /* ...retry, hash, send... */ }
  } else { /* ...send whole file... */ }
}

// Do
function upload(file: File) {
  if (isTooLarge(file)) uploadInChunks(file);
  else uploadWhole(file);
}
```

### 2. Do one thing
Two tests that a function does more than one thing:
1. You can label sections inside it ("initialize", "validate", "save").
2. You can extract another function whose name is *not* a restatement of the body.

Stop extracting when the next name would only repeat the code (`uploadBasedOnSize`).

### 3. One level of abstraction per function
Write each function as a "to" paragraph: "To process an order, we validate stock, calculate the bill, charge the customer, and notify the warehouse."
Each step lives one layer below.
Do not mix high-level intent with raw API syntax.

```ts
// Don't
function processOrder(o: Order) {
  validateStock(o);
  const total = o.items.reduce((s, i) => s + i.price * i.qty, 0) * 1.2;
  stripe.charges.create({ amount: Math.round(total * 100), currency: "usd" });
}

// Do
function processOrder(order: Order) {
  validateStock(order);
  const bill = calculateBill(order);
  charge(order.customer, bill);
  notifyWarehouse(order);
}
```

### 4. Bury the `switch`
A `switch` on a type does n things, and the same switch spreads to pay, benefits, scheduling, and reports.
Use it once, inside a factory. Use polymorphism after that.

```ts
// Don't
function pay(e: Employee) { switch (e.type) { case "FT": /*...*/ case "CONTRACT": /*...*/ } }
function benefits(e: Employee) { switch (e.type) { /* same cases again */ } }

// Do
interface Employee { pay(): Money; benefits(): Benefits; }
const createEmployee = (record: Record): Employee =>
  record.type === "FT" ? new FullTime(record) : new Contractor(record);
```

### 5. Keep the argument count low
Zero is ideal, one is clear, two is acceptable, three is a signal to group.
Related arguments want to become an object with a name.

```ts
// Don't
makeCircle(x, y, radius, color, width);

// Do
makeCircle({ center: { x, y }, radius }, style);
```

### 6. Arguments: use the three good single-argument forms
A single argument is fine when the function:
- asks a question: `fileExists(path)`
- transforms: `parseDate(text)` returns a new value
- handles an event: `onUserCreated(event)`

Avoid:
- **Boolean flags.** `render(true)` makes one function do two jobs. Write two functions.
- **Output arguments.** Return the result. Do not mutate an input.

```ts
// Don't
render(true);
appendFooter(report);          // mutates report

// Do
renderForPrint(); renderForScreen();
const withFooter = addFooter(report);
```

### 7. Order arguments so the call site is obvious
Pairs like `(x, y)` belong together.
Unrelated pairs and triads hide the order (`assertEquals(message, expected, actual)`).
Make one argument the owner, put the noun in the name (`writeField(name)`), or encode order in the name (`assertExpectedEqualsActual`).

### 8. No side effects
A function that does more than its name says will cause a bug.
`checkPassword` that also starts a session wipes the cart when the user only wanted to confirm a password.
Move the side effect out. Do not hide it in a longer, uglier name.

```ts
// Don't
function checkPassword(user: User, pass: string) {
  if (hash(pass) === user.hash) { Session.init(); return true; }
  return false;
}

// Do
function isPasswordValid(user: User, pass: string) { return hash(pass) === user.hash; }
// the caller decides whether to start a session
```

### 9. Command-query separation
A function either **does** something or **answers** something. Never both.

```ts
// Don't
if (set("username", "bob")) { /* did it exist, or did the update work? */ }

// Do
if (!attributeExists("username")) setAttribute("username", "bob");
```

### 10. Split a function where the data stops being shared
Do not split a long function by line count.
Promote the shared locals to fields, extract each block, then group the methods that touch the same fields into classes.
The original function now only coordinates.
(See `clean-code-classes` for the class side.)

### 11. Move a method to the data it uses
If a method takes most of its arguments from one object, the method belongs on that object.

```ts
// Don't
billing.amountDue(invoice.subtotal, invoice.tax, invoice.credit);

// Do
invoice.amountDue();
```

### 12. DRY: one truth, one place
Every piece of knowledge has one authoritative representation.
Extract repeated fetch, error check, and timeout logic once.
Then a change (a new timeout) lands in one function, not twenty.

### 13. Write it messy, then rewrite it
Nobody writes clean code on the first try.
Get the logic down, keep tests green, then split functions, rename, and remove duplication.
Clean code is rewritten, not written.

## Checklist

- [ ] The function is a few lines. Blocks inside `if` and `while` are one-line calls.
- [ ] I cannot label sections inside it, and I cannot extract a function with a non-trivial name.
- [ ] All statements sit at one level of abstraction.
- [ ] No repeated `switch` on the same type.
- [ ] At most two arguments. Three or more are grouped.
- [ ] No boolean flag, no output argument.
- [ ] The name tells the whole truth: no hidden side effect.
- [ ] The function either changes state or returns an answer.
- [ ] No method sits far from the data it reads.
- [ ] No repeated block of knowledge.

## Sources

Reels by `@s4.codes` (TikTok; the Instagram profile is not readable without login):
- Small functions: https://www.tiktok.com/@s4.codes/video/7591511622535908630
- Do one thing: https://www.tiktok.com/@s4.codes/video/7592680869156949270 and https://www.tiktok.com/@s4.codes/video/7591165703521193238
- One level of abstraction: https://www.tiktok.com/@s4.codes/video/7593505805610077462
- Switch statements: https://www.tiktok.com/@s4.codes/video/7594069080802462998
- Argument count: https://www.tiktok.com/@s4.codes/video/7597422198231502082
- Flags, output arguments, single arguments: https://www.tiktok.com/@s4.codes/video/7597756714603056406
- Dyads and triads: https://www.tiktok.com/@s4.codes/video/7599650287996980502
- Side effects: https://www.tiktok.com/@s4.codes/video/7601152407522905366
- Command-query separation: https://www.tiktok.com/@s4.codes/video/7602236288397397251
- DRY: https://www.tiktok.com/@s4.codes/video/7604472795266895126
- Rewrite after the first draft: https://www.tiktok.com/@s4.codes/video/7604850075147210006
- Split where the data stops being shared: https://www.tiktok.com/@s4.codes/video/7686533796581346562
- Move the method to the data: https://www.tiktok.com/@s4.codes/video/7686533107440160022
