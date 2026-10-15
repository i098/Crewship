---
name: fleet-browser
description: "Use for web interaction, screenshots or browser automation on a fleet host: which browser tier (obscura, chrome, vnc) to use and how the shared login session works."
---

# Fleet browser ladder: one shared session, three tiers

Needs the `fleet_browsers` profile (Crewship `docs/fleet-guards.md`, Browser ladder).
Default tier: Obscura (a Rust engine, CDP `http://127.0.0.1:9222`, always on, about 5x less RAM than Chrome).
Every agent shell exports `CHROME_DEVTOOLS_AXI_BROWSER_URL`, so `chrome-devtools-axi` and omp's browser tools attach to it and launch no private Chrome.

Ladder, driven with `fleet-browser status|env|up|down|sync`:

| Tier | Endpoint | Use |
| --- | --- | --- |
| **obscura** (default) | `:9222` | All normal browsing, screenshots, clicks. |
| **chrome** (fallback) | `fleet-browser up chrome` then `:9522` | Pixel-critical before/after evidence, or a page Obscura renders wrong. Stops after 30 idle minutes. |
| **vnc** (last resort) | `fleet-browser up vnc` then `:9523`, noVNC `:6909` over an SSH tunnel | A human must see or drive the browser: OAuth consent, captcha, native dialog. |

Use a fallback tier for one task with `eval "$(fleet-browser env chrome)"`. It sets a separate axi session, so it does not collide with the default.

## Session sync

One canonical cookie jar (`~/.fleet-browser/cookies.json`) converges across all three tiers every 2 minutes and on every `up`.
Sign in once in any tier and every tier has the login.
Google cookies never enter the jar: they stay in the tier that holds the login, so use that tier for a signed-in Google task.
localStorage belongs to one engine and is not synced.

## Rules

- Drive the browser yourself. The public rules `drive-the-browser-yourself` and `fleet-browser-default-tier` enforce this and the ladder.
- Do not probe for private Chrome profiles, `DISPLAY` values or dead VNC desktops.
- Do not start Chrome with your own `--user-data-dir`.
- Do not copy, prune or hand-edit the jar. If the wrong identity is signed in, sign out and in again in the same tier.
- Do not stop a tier that another lane uses. The gc timer stops idle fallback tiers.
