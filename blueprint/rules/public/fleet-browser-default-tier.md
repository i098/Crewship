---
name: fleet-browser-default-tier
description: "Browser work uses the shared fleet ladder (obscura -> chrome -> vnc), never a private per-lane Chrome profile or a DISPLAY probe"
condition: ["--user-data-dir=(?!\\S*/\\.fleet-browser/|/tmp/puppeteer)", "DISPLAY=:(?!9\\b)\\d", "fm-desktop", "\\.vnc-chrome-profile", "(?:pgrep|ps -eo)[^\\n]{0,80}chrom[^\\n]{0,200}DISPLAY", "installed browsers[\\s\\S]{0,400}google-chrome-stable"]
scope: "tool:bash"
---
## Use the shared ladder; do not probe for private browsers

The box runs ONE browser ladder, already wired into your shell:

| Tier | Endpoint | When |
| --- | --- | --- |
| **obscura** (default) | `CHROME_DEVTOOLS_AXI_BROWSER_URL=http://127.0.0.1:9222` | All normal browsing, screenshots, clicks. Rust engine, ~5x less RAM than Chrome. |
| **chrome** (fallback) | `fleet-browser up chrome` -> `:9522` | Pixel-critical before/after evidence, or a page Obscura misrenders. |
| **vnc** (last resort) | `fleet-browser up vnc` -> `:9523`, noVNC `:6909` | A human must see or drive it: OAuth consent, captcha, native dialog. |

Do NOT:
- launch Chrome/Chromium with your own `--user-data-dir` (the regex above allows the fleet tiers' own profiles and puppeteer temp dirs only);
- probe for a desktop on any `DISPLAY` other than `:9` — only `:9` (the on-demand vnc tier) exists;
- enumerate `google-chrome`/`chromium` on `PATH` or look for a default Chrome profile — the host holds no such profile by design, an empty result is a false negative;
- copy, prune, or hand-edit the shared session jar.

Cookies other than Google cookies sync through one shared jar across all three tiers every 2 min.
Google cookies never enter the shared jar; they stay in the tier that holds the login.
For a signed-in Google task, use that tier, even when it is not the default.
To use a fallback tier for one task: `eval "$(fleet-browser env chrome)"` (it sets a separate axi session so it does not collide with the default).
The gc timer stops idle fallbacks; do not kill another lane's tier.
`fleet-browser status` shows the live tiers.

When the wrong identity is signed in, do NOT copy the jar, prune cookies, or spin a throwaway profile — that fragments session state and strands logins. Instead drive the same tier, sign out of the app (or its account menu), sign back in as the required account, and leave the shared jar in place. If a session must not persist, use an incognito context in the same tier, not a new profile.

A missing API secret is not a blocker if a browser session provides the required access.
Check the session before escalating for a credential; for Google, check the tier that holds the login.
