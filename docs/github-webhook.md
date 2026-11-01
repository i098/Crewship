# GitHub webhooks for the Firstmate watcher

Many Firstmate homes share one GitHub account, so polling pull requests drains the shared REST quota. With webhooks, GitHub tells the host when a pull request merges, and the watcher reads the API only as a slow fallback.

Three parts, all on the Firstmate profile with `development` on:

- `fm-gh-webhook` (`apps/fm-gh-webhook/`) is a small Rust service on `127.0.0.1:8788`. It accepts `POST /gh-webhook`, checks `X-Hub-Signature-256` (HMAC-SHA256 under `GH_WEBHOOK_SECRET`), and stores a file for each merged pull request (`pull_request`) and each completed `check_suite`, `check_run` and `workflow_run`. The secret is never logged. Without it the service exits 78 and stays down.
- Firstmate patch `0007-watch-webhook-events.patch`: the merged-PR poll reads these files first. It calls the API only once per `FM_GH_FALLBACK_POLL` seconds for each pull request (default 600). Before it does, it reads `rate_limit` (at most once a minute). Below 20 percent remaining, the interval is four times longer. Below 5 percent, it makes no call. Events live in `~/.local/state/crewship/gh-webhook` (`FM_GH_EVENTS_DIR`).
- Merge attempts and manual PR commands still call the API when you run them. They are not polled.

## Enable it

The playbook installs and starts the service. It never registers a webhook, opens the funnel or writes the secret.

1. Add `GH_WEBHOOK_SECRET=<long random string>` to `~/super.env`, then run `systemctl --user restart fm-gh-webhook`.
2. Publish the port on the host's Tailscale funnel: `tailscale funnel --bg --set-path /gh-webhook http://127.0.0.1:8788/gh-webhook`. The payload URL is `https://<host>.<tailnet>.ts.net/gh-webhook`.
3. In each repository, open Settings, Webhooks, Add webhook:
   - Payload URL: the URL from step 2.
   - Content type: `application/json`.
   - Secret: the same string as in step 1.
   - Events: Pull requests, Check suites, Check runs, Workflow runs.
4. Check the Recent Deliveries tab: a merge shows `204`; a bad secret shows `401`.

Until a repository has the webhook, its pull requests are found by the fallback poll, so merge detection takes up to `FM_GH_FALLBACK_POLL` seconds. Set the variable in the watcher's environment to change it.
