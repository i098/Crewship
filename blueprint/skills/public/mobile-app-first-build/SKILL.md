---
name: mobile-app-first-build
description: "Use when building a first mobile app: validate the idea, choose web or mobile, map flows, write requirements, build, test, and release."
---

# Build a first mobile app

Follow these steps in order.
Reuse completed work and record the evidence before moving to the next step.

## 1. Define the idea

- Name the target users, their problem, and the one task the app must help them complete.
- Choose a problem you know or an established category with demand.
- Check competing apps, prices, reviews, and complaints; state what this app will do better.
- Keep the first release small; list what it excludes.

## 2. Validate with a mobile web prototype

- Use existing tools to build the core task as a mobile web prototype before investing in an installed app.
- Aim for two days of prototype work, then about a week of feedback within a one-to-two-week validation period.
- Show the prototype to target users; observe whether they understand and complete the task.
- Record useful features, confusing steps, and features to remove.
- Change or drop the idea if feedback does not support it; do not treat a working prototype as proof of demand.

## 3. Decide whether an installed app is needed

- Keep the web version if it meets the need.
- Name the phone capabilities or distribution needs that require an installed app before choosing its technology.
- Compare a web wrapper, React Native, and native Swift for iOS or Kotlin for Android against those needs.
- Record the target platforms, the choice, and the expected code reuse or rebuild.

The source author prefers fully native apps; this is a preference, not a requirement for every project.

## 4. Map the flows

- Sketch each screen and transition before writing mobile code; use the web prototype screenshots as references.
- Separate onboarding, registration, pricing, and core product flows where the app needs them.
- Add mobile capabilities such as notifications, widgets, or camera access only when they support the validated task.
- Include back navigation, permission denial, empty states, and errors in each relevant flow.

## 5. Write the product requirements document

- Describe the users, problem, release scope, target platforms, and each flow in a product requirements document (PRD).
- Give each flow its screens, actions, data needs, and observable completion criteria.
- Attach the sketches and prototype references so the agent has concrete context.

## 6. Choose the builder

- Check ongoing costs, code ownership, export terms, supported platforms, and whether the tool fits the user's workflow.
- Prefer tools that use an existing agent subscription and allow free code export when they meet the requirements.
- Verify current terms before committing; do not select a vendor because the source promotes it.

## 7. Build one flow at a time

- Give the agent one flow specification, its screenshots, and its completion criteria instead of one prompt for the whole app.
- Implement the flow, run it on the target device or simulator, and check the completion criteria before starting another flow.
- Animate meaningful state changes with short transitions, about 0.2 seconds as a starting point. Reserve stronger motion for major user milestones.
- Use skeleton loading when the screen layout is known. Respect reduced-motion settings, and pause decorative animation in low-power mode.
- Check real phone behavior before release; report any device or platform that you could not test.
- Reserve time for debugging and fixes; do not promise the source author's build times for a different app.

## 8. Test and release

- Verify current developer account, signing, store, privacy, and payment requirements for each target platform.
- Use TestFlight for iOS testers or the corresponding Android test track before a public release.
- Test with five to seven real people; ask each person to complete the core task and give feedback.
- Fix blockers, repeat the affected flows, and keep optional pricing out of the first release if it delays learning.
- Get the owner's approval before account purchases, external invitations, or a public release.
- Release the smallest useful version, collect feedback, and improve it one feature at a time.

## Source

Distilled from [u/olenami's first mobile app guide on r/vibecoding](https://www.reddit.com/r/vibecoding/comments/1x7p4xo/a_stepbystep_guide_to_your_first_mobile_app_from/).
The author discloses a role in an app builder; this skill does not endorse that product.
Motion guidance adapted from [Cecilia Kim's reel](https://www.instagram.com/reel/DfF2EGqSuGI/).
