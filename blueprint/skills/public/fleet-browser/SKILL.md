---
name: fleet-browser
description: "Use for web interaction, screenshots or browser automation on a fleet host: which browser tier (obscura, chrome, voxl) to use and how the shared login session works."
---

# Fleet browser ladder: one shared session, three tiers

Needs the `fleet_browsers` profile (Crewship `docs/fleet-guards.md`, Browser ladder).
Default tier: Obscura (a Rust engine, CDP `http://127.0.0.1:9222`, always on, about 5x less RAM than Chrome).
Every agent shell exports `CHROME_DEVTOOLS_AXI_BROWSER_URL`, so `chrome-devtools-axi` and omp's browser tools attach to it and launch no private Chrome.

Ladder, driven with `fleet-browser status|env|up|down|sync`:

| Tier | Endpoint | Use |
| --- | --- | --- |
| **obscura** (default) | `:9222` | All normal browsing, screenshots, clicks. |
| **chrome** (headless) | `fleet-browser up chrome` then `:9522` | Pixel-critical before/after evidence, or a page Obscura renders wrong. Stops after 30 idle minutes. |
| **voxl** (headed) | always on at `:9523`, voxl viewer `:6913` over an SSH tunnel or the tailnet URL | A challenge the headless tiers fail. You click Cloudflare Turnstile, consent and captchas yourself in the viewer. |

The Geonode residential proxy is an option on any tier, not a tier.
At each tier try first without it. If that fails, run `fleet-browser up <tier> --proxy` (one sticky exit IP until the tier restarts; `--direct` switches back), then go to the next tier.
Order: obscura, obscura `--proxy`, chrome, chrome `--proxy`, voxl, voxl `--proxy`.
Dia (the owner's Mac browser) is no tier: use it only for a cookie pull.
Never wait for the owner or his Mac to clear a Turnstile; climb the ladder.

Use a fallback tier for one task with `eval "$(fleet-browser env chrome)"`. It sets a separate axi session, so it does not collide with the default.

## Session sync

One canonical cookie jar (`~/.fleet-browser/cookies.json`) converges across the tiers every 2 minutes and on every `up`.
Sign in once in any tier and every tier has the login.
Google cookies never enter the jar: they stay in the tier that holds the login, so use that tier for a signed-in Google task.
localStorage belongs to one engine and is not synced.

## Rules

- Drive the browser yourself. The public rules `drive-the-browser-yourself` and `fleet-browser-default-tier` enforce this and the ladder.
- Do not probe for private Chrome profiles, `DISPLAY` values or dead VNC desktops.
- Do not start Chrome with your own `--user-data-dir`.
- Do not copy, prune or hand-edit the jar. If the wrong identity is signed in, sign out and in again in the same tier.
- Do not stop a tier that another lane uses. The gc timer stops idle fallback tiers.
