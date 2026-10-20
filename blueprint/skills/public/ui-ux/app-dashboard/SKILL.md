---
name: app-dashboard
description: Use when designing, building, or reviewing app screens, dashboards, admin panels, stats, tables, cards, forms, confirm dialogs, loading states, disabled buttons, or dark mode. Skip landing pages and marketing sites, and backend, CLI, or non-visual work.
---

# App and dashboard UI

Less is the default. Each rule: rule, why, do/don't, review line.
Sources: Zander Whitehurst reels, `https://www.instagram.com/reel/<id>/` (ids in brackets).
Rules come from the reel transcripts. Examples are Tailwind translations, not frame copies.
Read [shared-basics.md](shared-basics.md) first: alignment, one primary button per view, relative units and accessibility apply here too.

## 1. Numbers need structure [DeegVT1uxP_, DX9RVypIHGi]
Why: a UI is not a spreadsheet. Unlabelled numbers get skipped.
Group stats under tabs. Use label + value + helper. Make one hero metric, the rest secondary. Join metadata in one line with a dot. Prefer a chart to a bare number.
```html
<!-- don't: 6 equal numbers in a grid -->
<!-- do -->
<p class="text-sm text-neutral-500">Distance</p>
<p class="text-5xl font-semibold">10.2 km</p>
<p class="text-sm text-neutral-500">Park Run · Sat · 48:12</p>
```
Check: every number has a label, a helper, and a clear rank.

## 2. Fewer colors [C7yo_TjtaX_, DXrDg7AiHuN]
Why: color without a job breaks consistency and hierarchy.
Use neutrals up to the one primary CTA. Use two surfaces: background and elevated. Use one mode per screen. Neutral icons and avatars.
```html
<!-- don't --> <header class="bg-pink-500"> <img class="bg-pink-300 rounded-full">
<!-- do -->    <header class="bg-white"> <img class="bg-neutral-100 rounded-full">
```
Check: each color answers "what does this tell the user?"

## 3. Borderless cards [C5QeamHtT44, DbDaptQscRR, DblH1vdIhIT]
Why: each background or border adds a surface. In a grid this crowds the content. Borders draw the eye, not the hierarchy.
Group with white space, not containers. Use a surface only for emphasis. Show hover with a change, such as a preview.
```html
<!-- don't --> <div class="rounded-xl border bg-white p-6">
<!-- do -->    <div class="group"> <img class="rounded-xl group-hover:opacity-90"> ...
```
Check: delete the border and background. If grouping still reads, leave them out.

## 4. Dark mode [DY4LiGiIloa]
Never use light surfaces in dark mode. Never mix modes. Raise elevation with lighter dark tones.
```html
<!-- don't --> <div class="dark:bg-white"> <!-- do --> <div class="dark:bg-neutral-900"> inside <body class="dark:bg-neutral-950">
```
Check: view the screen in both modes.

## 5. Fewer symbols, clearer groups [Dej3pg9IYNv]
Source: the supplied visible-frame takeaway, not an audio transcript.
Why: decorative or ambiguous icons make related values harder to read.
Do: remove decorative or ambiguous icons and group related values.
Use labels, spacing and type before symbol codes such as icons or glyphs.
Make the critical value or action readable at the real viewing size.
Use helper text only for information needed to act.
Show direct progress when progress is the data.
Retain necessary labels (shared basics) and uncertainty disclosure.
Don't: imply unmeasured progress or add helper text that repeats the label.
Check: at the real viewing size, can the reader identify the critical value, its group and the action without decoding symbols?

## 6. Forms [Db8J5z5Oy8-, DXrDg7AiHuN]
Floating labels (still labelled, shared basics). Touch target 56px. Rounded corners. Group fields by decision (destination, dates, passengers). Show dates readable. Put the first decision first (trip type).
```html
<label class="relative block"><input class="peer h-14 rounded-2xl pt-5 px-4" placeholder=" "><span class="absolute left-4 top-2 text-xs">Email</span></label>
```
Check: input height ≥ 56px, one chunk per decision.

## 7. Confirm dialogs: verb + noun [DdbcSa1OBhO]
Why: "Are you sure?" says nothing. The title should say what happens, and to what.
```html
<!-- don't --> <h2>Are you sure?</h2> <button>YES</button>
<!-- do -->    <h2>Delete project?</h2> <p>Detail caption.</p>
               <button class="btn-secondary">Cancel</button> <button class="btn-destructive">Delete project</button>
```
Add a dismiss icon. Use sentence case on buttons. Order: secondary, then destructive.
Check: no "Are you sure". Button label repeats the verb.

## 8. Keep submit enabled; point to what is missing [DcugS9HAFAj]
Source: a reel by @synsation_.
Why: a disabled submit on a long form says "no" without saying why. The user must search the form for the missed field.
Do: leave submit enabled. On click with missing input, show a clear message, highlight the missing fields and move the user to the first one. Disable a button while its request is in flight (prevents duplicate submits) or when the reason is obvious: "Previous" on page one, a one-question-at-a-time survey.
Implementation clarification (not from the reel): a native `disabled` control leaves the tab order and is not focusable, so keyboard users cannot reach it or learn what enables it. Use `aria-disabled="true"` with a focusable button when it must stay discoverable, and move focus to the first invalid field with `focus()`.
Don't: disable submit until every field validates, with no message.
Check: if the button is disabled, is the way to enable it obvious without searching? If not, enable it and explain on click.

## 9. One loading policy, by expected wait [DbQ-cgmu56T, DYkRtX1oKKN]
Source: two reels by @synsation_. The seconds are the creator's heuristics, not a timing guarantee.
Why: a spinner under one second flashes and feels slower. A bare spinner past about five seconds feels broken. Looped animation past about ten seconds raises frustration. A skeleton reads as "slow connection" and gives no duration information.
Do, by expected wait:
- Under about 1 s: no indicator. Show the result.
- About 1 to 5 s: a spinner. For a known wait under about 3 s with a known final layout, a skeleton may replace it; it must match that layout so nothing jumps when content lands, and must animate with a slow, steady, left-to-right shimmer, not a pulse.
- About 5 to 10 s: spinner plus text that names the real step in progress ("Connecting…", "Fetching orders…"). Static "Loading" buys about one second only.
- Past about 10 s, or an unknown wait: a progress bar when progress is measured, else a step indicator or an indeterminate bar, not a loop.
- On failure: show the error as soon as it is known. Never hold a spinner and fail later.
Implementation clarification (not from the reels): the reel says changing text works "even if it is fake"; do not do that. Status text, step counts and percentages must reflect observed work; show a percentage only when progress is measured. With reduced motion (shared basics), show a static skeleton or spinner frame.
Do for skeletons: render the loaded UI at each target viewport and measure each element's box with Playwright `locator.boundingBox()`.
Match the skeleton blocks to those sizes and positions.
Source: Aiden Bai, https://x.com/aidenybai/status/2111991261540528454.
Don't: a skeleton for a wait you cannot bound, a pulsing fade, a spinner for a sub-second action, invented status text, a fake percentage or step.
Check: name the expected wait for each loading state. Does the indicator match the row above?
Verify zero layout shift when content loads by comparing boxes before and after, or observing CLS with a `PerformanceObserver`.

## 10. Reachable, few, familiar [Ddz0B_LCnR-]
Source: a reel by @peterstewiestartup on seven UX laws; this rule keeps the ideas not already covered above.
Why: a user barely thinks about a good interface. A far or tiny primary target, nine pricing options, or a reinvented search icon each add thinking.
Do: make the primary action large and near where the user already is (Fitts). At a decision point, cut options to a few clear ones (Hick). Keep conventions: a magnifier for search, settings top right, cart then pay, a dropdown that drops down (Jakob); put originality in the product, not in navigation. Show step progress on multi-step flows ("4 of 5"); people finish what they can see is nearly done (Zeigarnik, goal gradient). Group long navigation and settings into chunks (Miller); the lesson is overload, not the number seven.
Von Restorff (one element that differs is noticed) is the shared basic: one primary button per view.
Don't: nine plans and six CTAs on one pricing page; fifteen equal navigation items; a custom icon for a standard action.
Check: for each screen, name the one action, count the choices at its decision point, and confirm each control looks like what the user already knows.
