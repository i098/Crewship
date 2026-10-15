---
name: clean-code-tests
description: "Use when you write, name, structure, or review unit tests: F.I.R.S.T, one concept per test, build-operate-check layout, test-driven development, skipped or tangled tests, or hesitation to change code that has no tests."
---

# Clean code: tests

Tests are what keep code flexible, maintainable, and reusable.
They do not prove the code is right.
They make the code something you are still willing to change.
These rules come from the s4.codes "clean code" series (the unit tests chapter of Robert C. Martin's *Clean Code*).

## Rules

### 1. Tests are why you can change code
"If it works, do not touch it" is fear.
With tests that check behavior, you may replace the implementation (a slow one, a hard-to-read one).
A failing test then says exactly what broke.
Write the tests that make you willing to change the code.

### 2. Keep tests as clean as production code
A tangled test costs time on every feature, because you are in the tests first.
Then someone skips a test that is too hard to read, and the suite fills with skips.
A test you can read is a test you can update.
Never skip a test because it is hard to read. Fix it.

### 3. F.I.R.S.T
- **Fast.** A slow suite is run less often, so you find bugs late and lose the freedom to clean code.
- **Independent.** One test never sets up conditions for the next. Shared state makes one failure cascade and hide the real bug.
- **Repeatable.** The test passes in CI and on a laptop with no network, every time.
- **Self-validating.** The result is a boolean: green or red. No log reading.
- **Timely.** Write the test just before the production code. Tests written after tend to need tightly coupled code.

### 4. One test, one promise (one concept per test)
Name the test for the behavior it guards, not for the function it calls.
A test that checks three behaviors documents none of them.

```ts
// Don't
test("createMember", () => {
  const m = createMember("ada", "pw");
  expect(m.active).toBe(true);
  expect(m.plan).toBe("free");
  expect(JSON.stringify(m)).not.toContain("pw");        // different promise
  expect(() => createMember("ada", "pw")).toThrow(); // another promise
});

// Do
test("a new member starts active on the free plan", () => { /* ... */ });
test("a member never exposes the raw password", () => { /* ... */ });
test("registering an existing email is rejected", () => { /* ... */ });
```

### 5. Build the world, run the action, check the result
Each part says *what*, not *how*.
- **Build:** facts about the world, not steps to assemble it.
- **Operate:** one action.
- **Check:** one claim, with no unpacking of the result.

Move the assembly to named helpers that serve the whole suite.

```ts
// Do
test("a card that expired in 2020 is rejected as expired", () => {
  const today = givenToday("2026-01-15");
  const card = aCard({ expires: "2020-12" });

  const result = validateCard(card, today);

  expect(result).toBe(CardStatus.Expired);
});
```

### 6. Test-driven development: three stops
1. Write no production code until a test fails.
2. Write only enough of the test to fail (a compile error counts). Then stop.
3. Write only enough production code to pass that test. Then stop.

Every line of production code exists because a test asked for it.

```ts
// Test 1: canEdit(author, post) -> true   Production: return true     (looks like cheating)
// Test 2: canEdit(stranger, post) -> false  forces:  return post.authorId === user.id
```

### 7. Rewrite with the tests green
Nobody writes clean code first time.
With tests covering the behavior, split functions, rename, and remove duplication step by step.

## Checklist

- [ ] The test fails for the right reason before the fix.
- [ ] The suite runs in seconds and does not depend on order or network.
- [ ] The result is a pass or fail assertion, not a log to read.
- [ ] Each test name states one behavior. Each test checks one concept.
- [ ] The test reads build, operate, check, with helpers for setup.
- [ ] No skipped test because it is hard to read.
- [ ] I wrote the test before the code, and only enough code to pass it.
- [ ] Code with no tests gets tests before refactoring.

## Sources

Reels by `@s4.codes` (TikTok; the Instagram profile is not readable without login):
- Tests keep code changeable: https://www.tiktok.com/@s4.codes/video/7674677557056245014
- Clean tests: https://www.tiktok.com/@s4.codes/video/7673863008807865622
- F.I.R.S.T: https://www.tiktok.com/@s4.codes/video/7678248337367207190
- One test, one promise: https://www.tiktok.com/@s4.codes/video/7676100855019441430
- Build, operate, check: https://www.tiktok.com/@s4.codes/video/7675002892054433046
- Test-driven development: https://www.tiktok.com/@s4.codes/video/7672748006994660630
- Rewrite after the first draft: https://www.tiktok.com/@s4.codes/video/7604850075147210006
