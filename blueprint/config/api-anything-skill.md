
## On this host (Crewship)

- A site learned once is called later over plain HTTP, with no browser.
- The catalog is local, under `$API_ANYTHING_HOME`. Sharing is off: nothing you learn or call leaves this host. Only reading public catalog entries is allowed.
- Never turn sharing on, and never run `api-anything publish --yes`, `setup --yes` or `login` without `--cookies`. Answer `no` if a client asks to share.
- The saved login comes from the fleet browser's shared cookie jar, not from a browser profile. Sign in to the site once in any fleet tier (see the `fleet-browser` skill), then run `api-anything-fleet login <site|url>`.
- Call with `api-anything-fleet call <site> <op> k=v`. On `class: "auth"` it renews the login from the jar once and retries once. If it still fails, sign in again in the fleet browser.
- Learn a new site with `api-anything-fleet learn ...` (same arguments as `api-anything learn`): it finds the fleet's Chromium and runs it headless with its own profile under `$API_ANYTHING_HOME`. It never touches another Chrome profile.
