---
name: clean-code-errors
description: "Use when you write or review error handling: try/catch, thrown exceptions, return or error codes, catch blocks that act as an if, wrapping a library's exception types, or the contract of a function that can fail."
---

# Clean code: error handling

Error handling is a separate concern from the algorithm.
Keep the two readable apart.
These rules come from the s4.codes "clean code" series (the error handling and boundaries chapters of Robert C. Martin's *Clean Code*).

## Rules

### 1. Use exceptions, not return codes
Return codes force the caller to check at once, nest every step, and share an enum that ties files together.
Exceptions keep the algorithm flat: the steps read as a list.

```ts
// Don't
const r = verifySession(s);
if (r === Code.OK) {
  const c = resolveChannel(id);
  if (c.code === Code.OK) { /* ...each step deeper... */ }
}

// Do
function post(session: Session, channelId: string, text: string) {
  verifySession(session);
  const channel = resolveChannel(channelId);
  moderate(text);
  broadcast(channel, text);
}
```

### 2. Extract the try/catch body
A `try` block mixes normal and error processing in one place.
Move the body into its own function so the function that catches does only error handling.

```ts
function register(input: Input) {
  try { createAccount(input); }
  catch (e) { handleRegistrationFailure(e); }
}
```

### 3. Do not use `catch` as an `if`
If the exception represents one of two normal paths, it is not an exception.
Exceptions are for what breaks, not for branches the code already plans for.
Return an object that handles the normal case (the special-case pattern).

```ts
// Don't
let rule: TaxRule;
try { rule = rules.forRegion(order.region); }
catch { rule = DEFAULT_RULE; }

// Do
const rule = rules.forRegion(order.region);   // returns DEFAULT_RULE when none matches
```

### 4. Do not return null. Do not guard against null.
Return a real value for the empty case (an empty list, a default rule).
The caller then needs no null check.

### 5. Write the `try`/`catch`/`finally` first
When logic can throw, start from the failure test and the `try`/`catch` shell, then add the logic.
The shell is the contract: it states what the function handles and what the caller can expect.
1. Write a test for the failure you expect ("throws `TransactionFailed`").
2. See it fail.
3. In the `catch`, translate any thrown error into `TransactionFailed`.
4. Add logic inside the `try`. It stays inside the contract.

```ts
function withdraw(accountId: string, amount: Money) {
  try {
    const account = accounts.find(accountId);
    account.debit(amount);
  } catch (e) {
    throw new TransactionFailed(accountId, { cause: e });
  } finally {
    audit.record(accountId);
  }
}
```

### 6. Wrap a library's exceptions
Exception types are part of your design.
A catch block that lists the library's three exception types and handles all three the same way has copied the library's shape into your code.
1. Put a wrapper class between the library and your code.
2. The wrapper catches the library's exceptions and throws types **you** define (often one).
3. Everything else catches your type only.

```ts
// Don't
try { s3.putObject(params); }
catch (e) { if (e instanceof S3TimeoutError || e instanceof S3AuthError || e instanceof S3QuotaError) retryLater(); }

// Do
class Storage {
  put(key: string, data: Buffer) {
    try { s3.putObject({ Key: key, Body: data }); }
    catch (e) { throw new StorageFailure(key, { cause: e }); }
  }
}
// Swapping S3 for another store changes only Storage.
```

## Checklist

- [ ] No function returns an error code that the caller must check.
- [ ] The algorithm reads without any failure branch in view.
- [ ] No `catch` implements a normal branch.
- [ ] No function returns null for "nothing". Empty cases return a real value.
- [ ] A function that can fail has a documented, tested exception type.
- [ ] The `try` body is one call, or the try/catch sits in its own function.
- [ ] Each library's exception types stay inside one wrapper.
- [ ] Every wrapped exception keeps the original as `cause`.

## Sources

Reels by `@s4.codes` (TikTok; the Instagram profile is not readable without login):
- Prefer exceptions to error codes: https://www.tiktok.com/@s4.codes/video/7603381199523908886
- Use exceptions so the algorithm can breathe: https://www.tiktok.com/@s4.codes/video/7627871907634760982
- Catch is not an if: https://www.tiktok.com/@s4.codes/video/7660112834449181974
- Define the contract before the logic: https://www.tiktok.com/@s4.codes/video/7631563183194524950
- Wrap third-party exceptions: https://www.tiktok.com/@s4.codes/video/7655300304321187094
- Rule 4 (null) comes only from the caption "Don't guard against null. Stop returning it." on the profile mirror. That video was not in the list `yt-dlp` returned, so it has no transcript.
