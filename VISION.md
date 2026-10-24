# Vision

`Crewship` exists so that one person can turn a bare Ubuntu server into a working fleet of coding agents without hand-building it.
It serves the operator who owns the server and its accounts, and it turns a short config and one command into the same host every time.
It owns exactly one thing: the recipe that provisions and keeps current the host the agents run on.

## One recipe, safe to run again

Every task is idempotent, and an unchanged `launch` reports `changed=0`.
Every task is check-mode safe, so `chart` previews a change without making one.
A task that cannot prove its end state does not guess; it stops and says what is missing.
Unconditional restarts, bare commands and hidden state are refused.

## Latest, but verified

Tools install at their newest release, never pinned, so a host never falls behind quietly.
Every download is checked against the publisher's digest, and a release without one is refused.
Security floors win over "newest": trust roots, Node and Python minimums are enforced before the first network lookup.
Prereleases never reach a stable channel; a stable release needs the owner's explicit word.
Only the repository's own development environments stay locked.

## The operator owns the host

Crewship writes defaults on first install and leaves what the operator changed alone.
Anything it did not install, and anything outside its manifest, is never replaced or removed.
Opt-in features stay opt-in; a feature that reaches an outside audience or costs money is off until the operator turns it on.
Secrets, accounts and personal notes stay on the host and out of the repository.
Guards stop accidents, such as a write to the wrong GitHub repository or a pattern kill that hits another worker, and the docs say what they do not stop.

## Agents work in the open

Agent work lands as a pull request that follows the template, names its issue, and shows what ran.
A change is small, has one concern, and fixes the cause once in shared code.
Evidence beats assertion: a claim that something passed names the command, and an unrun check says it was not run.
Validation runs outside the agent that wrote the change, and CI enforces the format.
Docs and the changelog change with the code they describe.

## Scope

Crewship is not a hosted service, an agent framework, or a model router.
It does not own the agents' judgment; it installs the harnesses, skills and rules they run under and gets out of the way.
It does not manage fleets of servers; one operator, one host, one config.
A feature is built here only when a host needs it to run agents, not because an agent could use it.

A change aligns when it keeps the recipe idempotent and previewable, installs from verified latest sources, leaves operator-owned files alone, and arrives as a small, evidenced pull request.
A change should be resisted when it pins a tool to hide a problem, skips a checksum for convenience, overwrites an operator's file, turns on an outside-facing feature by default, or adds a second way to do what the recipe already does.
