---
name: third-party-signups
description: "Use when work needs a new third-party account, an email verification code, OAuth consent, an app approval, or a connector. How to act on an owner's standing authorization, and its hard bounds."
---

# Third-party signups, app approvals and verification

This skill applies only when the owner of the host has given a standing authorization to do signups and approvals for assigned work.
Without it, ask once, then follow the answer.
With it, do the signups and approvals yourself and stop asking.
Put the owner's words in the project instructions, so the authorization is on record.

## What the authorization covers

- Register the accounts that assigned work needs, under the owner's account email (`$ACCOUNT_EMAIL`, set in `$SECRETS_FILE`). No per-signup approval round trip.
- Read the owner's mailbox to finish email verification and device codes. Do not hand a code back to the owner to type.
- Approve OAuth consent and install third-party apps into the owner's workspaces.
- Report the end result, not the consent screens you crossed to reach it.

## Bounds that always hold

- **No paid plan, payment detail or charge.** If a service asks for a card, stop and report. A no-card trial that lapses to free is fine: say so and name the lapse date.
- **Never rotate a credential.** Report the exposure. Rotation belongs to the owner.
- **No account that acts publicly under the owner's identity** (social, forums, package registries, app stores) without asking first.
- **One sign-in attempt per account, then stop.** Retries lock accounts. Mailbox access changes how you solve a verification. It does not license repeated logins.
- Secrets go to `$SECRETS_FILE` at mode 600, by variable name. Never into a repo, brief, log, commit or chat.

## After the fact

When a grant is unusually broad, for example a vendor app that reads message history in a workspace where other people talk, say in the report what you granted and that it stays until revoked.
That informs the owner. It does not ask permission.
Do not hold the work hostage to a question about a scope you may already approve.
