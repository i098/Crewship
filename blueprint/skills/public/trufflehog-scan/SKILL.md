---
name: trufflehog-scan
description: Use when you need to scan an authorized Git repository for verified exposed credentials with TruffleHog.
---

# Scan a Git repository with TruffleHog

Use TruffleHog to scan only repositories that you own or have permission to test.

Run a verified-results scan:

```bash
trufflehog git <AUTHORIZED_REPOSITORY_URL> --results=verified
```

Replace the URL with the authorized repository URL. The `verified` filter reports credentials that TruffleHog confirms are valid, rather than every pattern match.

Treat any finding as a secret. Do not paste credential values into chat, issues, logs, or commits. Restrict access to the scan output, revoke confirmed exposed credentials, and notify the repository owner through an approved channel.

Source: https://www.instagram.com/reel/DdweG3txUWI/
