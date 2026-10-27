---
name: observability
description: Use when adding, reviewing, or debugging logs, metrics, traces, alerts, or SLOs in a service; not for general code review.
---

# Observability: seven levels

Walk the levels in order. Stop at the first gap and fix it before going higher.

1. **Logs.** One line per event: what happened and when. Include level, timestamp, and the entity ID. No secrets.
2. **Metrics.** Numbers over time: request rate, error rate, latency, saturation. Use them to see trends.
3. **Traces.** One request across services, with time per step. Use them to find the slow step.
4. **Correlation.** One request ID in every log line, metric exemplar, and trace span. Pass it across service calls.
5. **Alerts.** Alert on a symptom with a threshold and a window, for example "errors above 5% for 5 minutes". Every alert has an action.
6. **SLOs.** Define what "good" means for the user. Page only when the target is at risk of being missed.
7. **Cardinality.** Keep metric labels few and bounded. Put per-user or per-request detail in logs or traces, never in metric labels.

## Review checklist

- [ ] Each failure path logs one line with the request ID.
- [ ] Rate, errors, and latency exist as metrics.
- [ ] A slow request can be followed across services in a trace.
- [ ] The same request ID appears in logs, metrics, and traces.
- [ ] Each alert names a threshold, a window, and a responder action.
- [ ] Each SLO has a user-facing good/bad definition and an error budget.
- [ ] No metric label takes unbounded values (user ID, URL path, email).
