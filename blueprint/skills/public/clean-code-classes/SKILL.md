---
name: clean-code-classes
description: "Use when you design or review a class or module: single responsibility, when to stop splitting, objects versus data structures, getters and setters, Law of Demeter, private versus public boundaries, wrapping third-party libraries, or when to refactor."
---

# Clean code: classes and design

A class is a bet on what kind of change comes next.
These rules come from the s4.codes "clean code" series (the classes, objects, data structures, and boundaries chapters of Robert C. Martin's *Clean Code*).

## Rules

### 1. One job, one reason to change
A job is the one thing a class is in charge of.
A reason to change is an *actor*: a group of people who can demand a change.
One actor, one class.
Look at the method list. Methods that fall into distinct groups are a second job.
Ask "what would make me change this class?" More than one answer means more than one class.

```ts
// Don't: tax rules, email layout, and delivery all change this class
class Invoice { total() {} buildEmail() {} sendEmail() {} }

// Do
class Invoice { total() {} }
class InvoiceEmail { build(invoice: Invoice) {} }
class Mailer { send(message: Message) {} }
```

Benefits to name in a review: a change for one group does not hit the other, you test the arithmetic without a database, and you reuse a part without dragging the rest.

### 2. Split at the "and"
If the honest name needs "and", split the class at the "and" (see `clean-code-naming`, rule 11).
If you cannot name a class with one noun phrase, split it until you can.

### 3. Stop splitting when the next class earns nothing
Small classes, one job, and separation of policy from detail all turn one class into many.
Past a point the pieces add nothing, and that is over-engineering.
Add another class only if it does one of four things:
1. Lets you test one piece on its own.
2. Removes code written twice.
3. Gives a name to something that never had one.
4. Holds new behavior so working code does not change.

### 4. Refactor on a real requirement, not on a guess
Cleaning up for a requirement you imagine adds awkward conditions when the real one arrives.
1. If the code works, leave it.
2. A real requirement arrives.
3. If it fits the existing logic, add it.
4. If it needs different logic, first reshape the code *without changing behavior* to make room, then add the feature.

```ts
// Real requirement: a fixed-amount coupon next to percentage coupons.
// Step 1: refactor with no behavior change.
interface Discount { apply(price: number): number; }
class PercentOff implements Discount { constructor(private pct: number) {} apply(p: number) { return p * (1 - this.pct); } }
// Step 2: add the new behavior as its own class.
class AmountOff implements Discount { constructor(private amt: number) {} apply(p: number) { return p - this.amt; } }
```

### 5. A module declares or does. Never both.
A workflow module lists steps and delegates each one.
An implementation module does the work of one step.
A pricing calculation in the middle of a checkout workflow gives the file two reasons to change.
For every file ask "is it declaring or doing?" If both, move the detail out.

### 6. Private is a promise about what may change
The public interface sits at a high level and says *what*.
The private part holds *how*.
The line between them marks what you expect to stay still and what you expect to move.
Do not leave a general helper public "just in case". Other modules will use it, and then every format change breaks them.
Add a dedicated public method for each real use case instead.

### 7. Objects hide data and expose behavior. Data structures expose data and have no behavior.
Pick a side.
A **hybrid** (public getters and setters plus real logic) is the worst of both: you cannot add a function and you cannot add a type.
- DTOs: public fields, no logic. They carry data.
- Active records: data plus `save` and `delete`. Keep them that way. Put business rules in another object.

```ts
// Don't: hybrid
class Subscription { getPrice() {} setPrice(p: number) {} discount() {} }

// Do
class SubscriptionRecord { price!: number; save() {} }      // active record, no rules
class SubscriptionPricing { discount(s: SubscriptionRecord) {} }
```

### 8. Not everything is an object: choose by the change you expect
- Data structures plus procedures: easy to add **functions** (a new `perimeter` touches no shape), hard to add **types**.
- Objects: easy to add **types** (a new `Triangle` touches nothing), hard to add **functions**.

Ask "am I more likely to add new data types or new behaviors?" before you write the class.

### 9. Expose behavior, not structure
Private fields with a getter and setter for each one are public fields in disguise.
Hide the representation so you can change it (Cartesian to polar).
The interface may enforce policy, such as setting `x` and `y` together as one atomic operation.

```ts
// Don't
interface Vehicle { getFuelTankCapacityInGallons(): number; getGallonsOfGasoline(): number; }

// Do
interface Vehicle { percentFuelRemaining(): number; }
```

### 10. Law of Demeter: talk to friends, not to strangers
A method calls only methods of: its own object, objects it creates, its arguments, and its fields.
Do not call a method on an object that a call returned.

```ts
// Don't
const path = ctx.getOptions().getScratchDir().getAbsolutePath();

// Do: tell the object what you need
const scratch = ctx.createScratchFile(name);
```

The rule applies to objects, not to data structures (data exposes its parts).
Collapsing the chain into `getOptionsScratchDirAbsolutePath()` does not help.
The structure knowledge only moved. Ask *why* you need the path and tell the object that.

### 11. Own your boundaries
You cannot stop a library from changing.
You can decide how much of your code touches it.
1. Wrap a third-party API in one small class in your own words (`charge(order)`, `refund(payment)`).
2. Keep the library's types and details inside that class.
3. When the library has a breaking change, only the wrapper changes.

```ts
// Don't: SDK calls everywhere
await stripe.charges.create({ amount: cents, source: token });

// Do
interface Payments { charge(order: Order): Promise<Receipt>; }
class StripePayments implements Payments { /* the only file that imports the SDK */ }
```

### 12. Write the interface you wish you had
If a piece your code needs is not ready, define the interface from *your* code's needs and build against a simple fake.
Later, an **adapter** that implements your interface and calls the real provider translates between them (dollars to cents, card to token).
The finished code does not change.
Translate at the border, not in the conversation.

## Checklist

- [ ] I can state the single job of the class and name the one actor who changes it.
- [ ] The class name is one noun phrase with no "and".
- [ ] Each extracted class tests, de-duplicates, names, or extends something.
- [ ] I refactor for a real requirement, not a guess.
- [ ] No file both declares a workflow and does the low-level work.
- [ ] No public helper exists only because nothing blocks it.
- [ ] The type is an object, a DTO, or an active record, never a hybrid.
- [ ] I chose objects or data structures by the change I expect.
- [ ] No method exposes how data is stored.
- [ ] No call chain reaches through a returned object.
- [ ] Each third-party library is behind one wrapper.

## Sources

Reels by `@s4.codes` (TikTok; the Instagram profile is not readable without login):
- Single Responsibility Principle: https://www.tiktok.com/@s4.codes/video/7692411315620433174
- Why one reason to change matters: https://www.tiktok.com/@s4.codes/video/7692412565657373955
- When to stop splitting: https://www.tiktok.com/@s4.codes/video/7691233378904935702
- Do not refactor on a guess: https://www.tiktok.com/@s4.codes/video/7686535118680296726
- Declare the workflow or do the work: https://www.tiktok.com/@s4.codes/video/7686534140895825154
- Split at the AND: https://www.tiktok.com/@s4.codes/video/7683126514610900246
- Private as a promise: https://www.tiktok.com/@s4.codes/video/7680534238562700566
- Hybrids, DTOs, and active records: https://www.tiktok.com/@s4.codes/video/7626390439926582550
- Law of Demeter: https://www.tiktok.com/@s4.codes/video/7625297108576374039
- Objects versus data structures: https://www.tiktok.com/@s4.codes/video/7623778304193039638
- Expose behavior, not data: https://www.tiktok.com/@s4.codes/video/7620476246824160534
- Wrap a third-party library: https://www.tiktok.com/@s4.codes/video/7671271971249868054
- Translate at the border: https://www.tiktok.com/@s4.codes/video/7672004184476060950
