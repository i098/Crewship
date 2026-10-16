---
name: clean-code-naming
description: Use when you name or rename a variable, function, class, parameter, or constant, or when you review a diff for unclear names, abbreviations, Hungarian notation, magic numbers, or names like Manager and Processor.
---

# Clean code: naming

A name is written once and read hundreds of times.
Optimize for the reader.
These rules come from the s4.codes "clean code" series, which teaches the naming chapter of Robert C. Martin's *Clean Code*.

## Rules

### 1. Reveal intent
The name answers three questions: why it exists, what it does, how to use it.
If a name needs a comment, change the name.

```ts
// Don't
const d = 7;
const list1 = items.filter(x => x[0] === 4);

// Do
const daysSinceLastLogin = 7;
const activeUsers = users.filter(user => user.status === Status.Active);
```

### 2. Avoid mental mapping
Never make the reader translate a name in their head.
Single letters (`t`, `tx`, `p`, `q`) are only for a loop index in a short scope.

```ts
// Don't
const calc = (p: number, t: number, q: number) => (p + t) * q;

// Do
const orderTotal = (price: number, tax: number, quantity: number) => (price + tax) * quantity;
```

### 3. Do not lie (no disinformation)
- Do not call a map a `list`. A name promises a type and a behavior.
- Do not use names that differ by a small detail (`UserProfileHandlerForAccounts` and `UserProfileHandlerForAccount`).
- Do not use look-alike characters: lowercase `l` and `1`, uppercase `O` and `0`.

```ts
// Don't
const accountList = new Map<string, Account>();

// Do
const accountsById = new Map<string, Account>();
```

### 4. Make meaningful distinctions
Two different names must mean two different things.
Number series (`a1`, `a2`), noise words (`Data`, `Info`, `Object`), and suffixes (`Manager`, `Handler`, `Processor`) add no meaning.
A name that cannot be told from its neighbor is a failed name.

```ts
// Don't
function copy(a1: string[], a2: string[]) {}

// Do
function copy(source: string[], destination: string[]) {}
```

### 5. Use pronounceable names
If you cannot say the name in a code review, rename it.

```ts
// Don't
class DtaRcrd102 { genymdhms: Date; modymdhms: Date; }

// Do
class Customer { generationTimestamp: Date; modificationTimestamp: Date; }
```

### 6. Use searchable names
Single letters and bare numbers cannot be found with search.
Give every constant a name.

```ts
// Don't
const days = tasks.length * 5 / 4;

// Do
const WORKDAYS_PER_WEEK = 5;
const TASKS_PER_DEVELOPER_DAY = 4;
const days = tasks.length * WORKDAYS_PER_WEEK / TASKS_PER_DEVELOPER_DAY;
```

### 7. Avoid encodings
Do not put the type or scope in the name (`strName`, `iCount`, `m_total`, `IShape`).
The IDE shows the type on hover and the compiler checks it.

```ts
// Don't
const strName: string = "Ada";
const arrUsers: User[] = [];

// Do
const name = "Ada";
const users: User[] = [];
```

### 8. Match name length to scope, for variables
The wider the scope of a variable, the longer and more descriptive its name.
A one-line scope may use `i`.
A module-wide or exported variable needs full words.

### 9. Match name length to *neighbors*, for functions
Function names run the other way.
A private helper in a narrow class competes with similar helpers, so it needs extra words (`importCsvHeader`, `importCsvRows`).
A widely called public function is a general operation: one verb is enough (`save`, `charge`).
Ask "what must this name tell apart from the names beside it?" before you debate length.

### 10. Name a function for why you call it, not for what it does
The name sits one level of abstraction above the code.
It describes the concept and hides the implementation.

```ts
// Don't: restates the implementation
const isEndDateGreaterThanStartDate = (a: Date, b: Date) => b > a;

// Do: states the intent
const isValidDateRange = (start: Date, end: Date) => end > start;
```

### 11. Name a class with one noun phrase
Words like `Manager`, `Processor`, `Helper`, and `Util` mean the class has no single job.
Do not rename it to something narrower that is still false.
If the honest name needs an "and" (`OrderPricingAndPayment`), split the class at the "and".
A class name is a measurement of the code, not a label you pick.

```ts
// Don't
class OrderManager { price(order: Order) {} charge(order: Order) {} }

// Do
class OrderPricing { price(order: Order) {} }
class PaymentGateway { charge(order: Order) {} }
```

## Checklist

- [ ] Every name states why the thing exists.
- [ ] No single-letter name outside a short loop.
- [ ] No type of container in the name that the thing is not (`List`, `Map`, `Array`).
- [ ] No number series and no noise words.
- [ ] I can say every name aloud.
- [ ] No magic number or string stays unnamed.
- [ ] No Hungarian prefix or `I` interface prefix.
- [ ] Variable name length matches scope. Function name length matches its neighbors.
- [ ] Function names describe intent, one level above the code.
- [ ] No `Manager`, `Processor`, `Helper` class. Each class name is one noun phrase.

## Sources

Reels by `@s4.codes` (TikTok; the Instagram profile is not readable without login):
- Intention-revealing names: https://www.tiktok.com/@s4.codes/video/7581610397447294230
- Disinformation: https://www.tiktok.com/@s4.codes/video/7581949305494293782
- Meaningful distinctions: https://www.tiktok.com/@s4.codes/video/7582591148443569430
- Pronounceable names: https://www.tiktok.com/@s4.codes/video/7583709380646882563
- Searchable names: https://www.tiktok.com/@s4.codes/video/7586219681409764630
- Avoid encodings: https://www.tiktok.com/@s4.codes/video/7587182714776718614
- Avoid mental mapping: https://www.tiktok.com/@s4.codes/video/7591165703521193238
- Name length and scope of a function: https://www.tiktok.com/@s4.codes/video/7681920097149029654
- Name a function for why: https://www.tiktok.com/@s4.codes/video/7680636500165512451
- Manager and processor class names: https://www.tiktok.com/@s4.codes/video/7683126514610900246
