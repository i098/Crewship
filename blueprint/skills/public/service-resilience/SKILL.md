---
name: service-resilience
description: Use when designing or reviewing a service that calls dependencies that can fail or stall.
---

# Service resilience

Source: [Instagram reel](https://www.instagram.com/reel/DfHzTY3BZ6s/).

For each remote dependency:

1. Set a finite timeout within the caller's total time budget. Cancel abandoned work when the client supports it.
2. Use a circuit breaker to stop repeated calls after a configured failure threshold. A closed breaker allows calls and counts failures; an open breaker fails fast; a half-open breaker allows probes after a cooldown.
3. Define a safe fallback, such as a cached result or a clear failure response. Do not report fallback data as fresh success.
4. Test the timeout, open transition, probe, recovery, and fallback paths. Choose thresholds and cooldowns for the service; do not copy example values from another system.

Availability multiplication applies only when dependencies fail independently and each dependency is required for the request.
