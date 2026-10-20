---
name: prod-readiness
description: 'Use before any production launch, deploy, or release to users, and when asked "is this ready". Check 20 production risks with pass, fail, or not applicable verdicts and evidence.'
---

# Production readiness

Checklist adapted from a public production-readiness list.

Run all 20 checks in order against the release candidate and its intended production configuration.
Use an isolated environment for fault injection, load tests, payment tests, and backup restoration.
Never make real charges, disrupt live users, or overwrite production data for a check.
Read the linked skills for checks they cover; do not repeat their implementation guidance.
Record the release revision, environment, and test time with the evidence.
Cite command output, test results, configuration paths, or screenshots; redact secrets and personal data.
For each item, apply its pass condition; otherwise mark fail, including missing evidence or an unrun check.
Use not applicable only for the stated absence, with evidence and a reason; missing implementation is a failure.
Do not call the release ready while any item fails; this review does not authorize a deployment.

## 1. Rate limiting
Check: Bound requests per caller on exposed endpoints, including across service instances.
Verify: Exceed the configured rate in an isolated test; cite the limit configuration and rejection responses.
Verdict: Pass if excess requests stop at the configured bound; not applicable only if no request endpoint exists.

## 2. API limits
Check: Keep external API calls within provider quotas, including concurrency and retry limits.
Verify: Inject a quota response such as HTTP 429; cite provider limits and a trace showing bounded retries and recovery.
Verdict: Pass if calls stay bounded and quota errors recover safely; not applicable only if no external API exists.

## 3. Spending caps
Check: Enforce a total spending ceiling for paid services; an alert alone is not a cap.
Verify: Cite provider hard limits or application enforcement; simulate exhausted credit and show paid work stops.
Verdict: Pass if spending cannot exceed the declared ceiling; not applicable only if no metered cost exists.

## 4. Error handling
Check: Apply [clean-code-errors](../clean-code-errors/SKILL.md) to the failure contracts.
Verify: Inject dependency and application errors; cite tests showing the documented failure result without leaked secrets.
Verdict: Pass if callers receive the documented failure result; not applicable only if no executable component exists.

## 5. Loading states
Check: Apply the loading policy in [app-dashboard](../ui-ux/app-dashboard/SKILL.md#9-one-loading-policy-by-expected-wait-dbq-cgmu56t-dykrtx1okkn).
Verify: Delay each user-facing operation; cite screenshots during the wait and after success or failure.
Verdict: Pass if the linked policy holds and waiting ends; not applicable only if no user-facing asynchronous operation exists.

## 6. Empty states
Check: Give zero-data and zero-result views a clear explanation and a valid next action; never show a perpetual loader.
Verify: Open a new account and an empty search; cite screenshots, using [mobile flow mapping](../mobile-app-first-build/SKILL.md#4-map-the-flows) where relevant.
Verdict: Pass if each empty view explains the result and next action; not applicable only if no collection view exists.

## 7. Failed requests
Check: Apply [clean-code-errors](../clean-code-errors/SKILL.md) to request failures and the linked loading policy to visible failures.
Verify: Inject offline, HTTP 4xx, and HTTP 5xx cases; cite results showing preserved input, visible failure, and safe retry where supported.
Verdict: Pass if failures end waiting without false success or lost input; not applicable only if no network request exists.

## 8. API timeouts
Check: Set finite deadlines for network calls, including retries, and stop abandoned work where supported.
Verify: Use a stalled dependency; cite timeout configuration and elapsed-time output showing the operation ends within its total deadline.
Verdict: Pass if stalled calls finish within the declared bound; not applicable only if no network call exists.

## 9. Preventing duplicate submissions
Check: Apply [app-dashboard's submission guidance](../ui-ux/app-dashboard/SKILL.md#8-keep-submit-enabled-point-to-what-is-missing-dcugs9hafaj); also enforce uniqueness on the server.
Verify: Double-click, resend, and submit concurrently with the same operation identity; cite responses and the resulting record count.
Verdict: Pass if one intended mutation occurs; not applicable only if no submission changes state.

## 10. Preventing duplicate payments
Check: Keep one charge per intended payment across client retries, timeouts, and repeated provider events.
Verify: Replay a sandbox payment and its webhook concurrently; cite provider charge IDs and the application ledger.
Verdict: Pass if one charge and one ledger effect occur; not applicable only if the product cannot take payments.

## 11. Optimized database queries
Check: Keep representative reads and writes within declared latency and query-count budgets at expected data volume.
Verify: Run query plans and request traces with realistic data; cite timings and query counts, including repeated per-row lookups.
Verdict: Pass if each critical query path meets its budgets; not applicable only if no database exists.

## 12. Database indexes
Check: Match indexes to critical filters, joins, ordering, and uniqueness constraints.
Verify: Cite schema definitions and query plans at expected data volume; explain intentional scans of small tables.
Verdict: Pass if plans meet the query budgets and required uniqueness holds; not applicable only if no indexed database exists.

## 13. Pagination of large results
Check: Bound server result sizes and traverse large collections with stable ordering.
Verify: Request oversized pages and traverse multiple pages with tied sort values; cite bounds and missing or duplicate record checks.
Verdict: Pass if limits hold and traversal is complete without duplicates; not applicable only if no growing collection is returned.

## 14. Compressing uploads
Check: Reduce compressible media before storage or transfer without breaking required quality or file integrity.
Verify: Upload representative files; cite original and stored byte counts, file validity, and visual quality where relevant.
Verdict: Pass if size falls within the declared budget and content remains usable; not applicable for no uploads or justified noncompressible formats.

## 15. Upload size limits
Check: Enforce upload size limits on the server, including streamed bodies and expanded content where processed.
Verify: Send boundary and oversized files, including without Content-Length; cite rejection responses and absence of stored oversized files.
Verdict: Pass if limits hold before unbounded processing or storage; not applicable only if no upload path exists.

## 16. Caching repeated requests
Check: Reuse safe repeated reads with bounded freshness, invalidation, and isolation between users.
Verify: Repeat a read, change its source, and read as another user; cite hits, source-call counts, and fresh isolated results.
Verdict: Pass if repeated work falls without stale or cross-user results; not applicable only if no read is safely reusable, with rationale.

## 17. Uptime monitoring
Check: Monitor the public service path externally and route failures to a responsible responder.
Verify: Trigger an isolated failed probe and recovery; cite monitor configuration and received failure and recovery notifications.
Verdict: Pass if detection and notification meet declared timing targets; not applicable only if no running service exists.

## 18. Error logging
Check: Record actionable application errors with request correlation, without secrets or personal payloads.
Verify: Inject an error; cite its searchable log event, correlation ID, and redaction check in the configured log destination.
Verdict: Pass if the responder can trace the failure safely; not applicable only if no executable component exists.

## 19. Testing simultaneous users
Check: Preserve correctness and declared latency and error budgets at expected peak concurrency.
Verify: Run representative parallel reads and writes; cite load parameters, latency, errors, resource use, and final data invariants.
Verdict: Pass if budgets and invariants hold; not applicable only if the product cannot have concurrent operations.

## 20. Testing backup restoration
Check: Restore durable data and required configuration within declared recovery-time and data-loss targets.
Verify: Restore a real backup into isolation; cite backup age, elapsed time, integrity checks, and a working application read.
Verdict: Pass if restored data works within both targets; not applicable only if all state is disposable and reproducible, with evidence.

## Output

Return one table with all 20 items in order.
Use `pass`, `fail`, or `not applicable`; include the failed condition or the absence reason in the evidence cell.

| Item | Verdict | Evidence |
| --- | --- | --- |
