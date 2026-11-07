---
name: never-bounce-login-back-to-the-owner
description: "When an account is missing or signed out, create or complete the sign-in in the shared fleet browser instead of handing the task back to the owner"
condition: ["open the desktop yourself", "sign in(?:to)? (?:GitHub|Google|Gmail|the site|it) (?:there )?yourself", "sign into \\w+ yourself on the desktop", "type your (?:GitHub|Google|Gmail|actual) [a-z]* ?password", "log in with your \\W{0,2}(?:GitHub|Google|Gmail)\\W{0,2} password", "send me your actual", "Tell me when you have signed in", "his Mac is offline", "need(?:s)? (?:his )?Mac (?:to be )?awake", "(?:wait(?:ing)? for|needs?) (?:his|the owner's) Mac", "open (?:a|the) login URL"]
scope: ["text", "thinking"]
---
Do not hand a login back to the owner when an account is missing or a site is signed out. That is your task, not an escalation.
Handing it back costs the owner a round trip on work already authorized, and it means you did not try.
Waiting for the owner's Mac to wake up is the same hand-back.

### Do this instead
1. **Drive the shared fleet browser.** Climb the ladder in order: obscura (headless, `http://127.0.0.1:9222`), chrome headless, then chrome headed in voxl.
   At each tier try without the Geonode proxy first, then with `fleet-browser up <tier> --proxy`, then go to the next tier.
   One canonical cookie jar syncs across the tiers, so the owner's logins are usually already present.
   The owner's Mac browser is only a source for a cookie pull, never a tier.
2. **A human-only step is yours too in voxl.** In voxl you click Cloudflare Turnstile, consent screens and captchas yourself in the headed Chrome (viewer `:6913` over an SSH tunnel).
3. **No account? Create one.** Complete the signup flow in the browser, then report what now exists. Creating an ordinary account on a service the owner uses is reversible and inside the work you were given.
4. **Signed out?** Sign in with a credential already on the box, then continue the original task in the same turn.
5. **Escalate only what needs the owner:** payment, hardware-gated 2FA (a physical tap), or a decision. Say which, and keep every other part of the job moving.

### Credential handling, non-negotiable
- **Never ask for a password in chat, and never repeat one back.** Chat is journalled permanently; a password that appears there is burned. Reference a `state/secrets/<name>` path, not the value. If a secret must reach the box, use the one-shot file receiver that lands it in a file at mode 600.
- **One sign-in attempt per account.** Stop at the first refusal and report it. Do not retry and risk a lockout.
- Do not copy, prune, or hand-edit the shared jar to "fix" a login. Sign out and back in inside the same tier instead.
