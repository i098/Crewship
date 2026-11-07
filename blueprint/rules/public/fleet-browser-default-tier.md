---
name: fleet-browser-default-tier
description: "Browser work uses the shared fleet ladder (obscura -> chrome headless -> chrome headed in voxl, each direct first, then with the Geonode proxy), never a private per-lane Chrome profile, a DISPLAY probe, or a wait for the owner's Mac"
condition: ["--user-data-dir=(?!\\S*/\\.fleet-browser/|/tmp/puppeteer)", "DISPLAY=:(?!9\\b)\\d", "fm-desktop", "\\.vnc-chrome-profile", "(?:pgrep|ps -eo)[^\\n]{0,80}chrom[^\\n]{0,200}DISPLAY", "installed browsers[\\s\\S]{0,400}google-chrome-stable", "Cloudflare[^\\n]{0,60}Turnstile[^\\n]{0,60}(?:block|stop|stuck|fail)", "(?:block|stop|stuck|fail)[^\\n]{0,60}Turnstile", "his Mac is offline", "need(?:s)? (?:his )?Mac (?:to be )?awake", "(?:wait(?:ing)? for|needs?) (?:his|the owner's) Mac", "open (?:a|the) login URL"]
scope: ["tool:bash", "text", "thinking"]
---
## Use the shared ladder; do not probe for private browsers

The box runs ONE browser ladder, already wired into your shell:

| Tier | Endpoint | When |
| --- | --- | --- |
| **1 obscura** (default, headless) | `CHROME_DEVTOOLS_AXI_BROWSER_URL=http://127.0.0.1:9222` | All normal browsing, screenshots, clicks. Rust engine, ~5x less RAM than Chrome. |
| **2 chrome** (headless) | `fleet-browser up chrome` -> `:9522` | Pixel-critical before/after evidence, or a page Obscura misrenders. |
| **3 voxl** (chrome headed) | always on at `:9523`, voxl viewer `:6913` | A challenge the headless tiers fail. You click Cloudflare Turnstile, consent and captchas yourself in the viewer. |

The Geonode residential sticky proxy is an option on any tier, not a tier. At each tier try without it first; if that fails, run `fleet-browser up <tier> --proxy`, then go to the next tier.
Order: obscura, obscura `--proxy`, chrome, chrome `--proxy`, voxl, voxl `--proxy`.
Dia (the owner's Mac browser) is only a source for a cookie pull, never a tier.
A Cloudflare Turnstile block, an offline Mac, or a login URL is never a reason to wait for the owner: climb the ladder and click it yourself in voxl.

Do NOT:
- launch Chrome/Chromium with your own `--user-data-dir` (the regex above allows the fleet tiers' own profiles and puppeteer temp dirs only);
- probe for a desktop on any `DISPLAY` other than `:9` — only `:9` (the permanent voxl tier) exists;
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
