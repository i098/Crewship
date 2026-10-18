---
name: frontend-ui-craft
description: Use when designing, building, or reviewing UI screens, cards, dashboards, stats, forms, modals, buttons, dark mode, or gradients. Hierarchy rules from Zander Whitehurst's UI reels. Skip for backend, CLI, or non-visual work.
---

# Frontend UI craft

Less is the default. Each rule: rule, why, do/don't, review line.
Sources: Zander Whitehurst reels, `https://www.instagram.com/reel/<id>/` (ids in brackets).
Rules come from the reel transcripts. Examples are Tailwind translations, not frame copies.

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

## 4. Left-align text [DcN2nJEu9L2, DdbcSa1OBhO]
Why: each centered line is an alignment anchor. Left align gives one.
Use proximity: heading, image, price, CTA in a column.
```html
<!-- don't --> <div class="text-center"> <!-- do --> <div class="text-left">
```
Check: no stacks of centered lines. One anchor for content, one for actions.

## 5. Confirm dialogs: verb + noun [DdbcSa1OBhO]
Why: "Are you sure?" says nothing. The title should say what happens, and to what.
```html
<!-- don't --> <h2>Are you sure?</h2> <button>YES</button>
<!-- do -->    <h2>Delete project?</h2> <p>Detail caption.</p>
               <button class="btn-secondary">Cancel</button> <button class="btn-destructive">Delete project</button>
```
Add a dismiss icon. Use sentence case on buttons. Order: secondary, then destructive.
Check: no "Are you sure". Button label repeats the verb.

## 6. Button hierarchy and CTA copy [DW3nH1YCIRC, DYMhapEoAHC]
Why: all-primary buttons remove hierarchy.
Auth: ghost "Sign in" + primary "Sign up". One CTA per view, starting with a verb ("Buy tickets"). A free tier: verb + value.
Check: one primary button per view.

## 7. Nested corner radius [DcgD9mmunMX]
Why: guessed radii look misaligned.
`outer = inner + gap`. Example: 24 + 16 = 40.
```html
<div class="rounded-[40px] p-4"><div class="rounded-[24px]">
```
Check: every nested pair satisfies the formula.

## 8. Dark mode [DY4LiGiIloa]
Never use light surfaces in dark mode. Never mix modes. Raise elevation with lighter dark tones.
```html
<!-- don't --> <div class="dark:bg-white"> <!-- do --> <div class="dark:bg-neutral-900"> inside <body class="dark:bg-neutral-950">
```
Check: view the screen in both modes.

## 9. Gradients [DUlFbcniJNj]
Why: dark + light in RGB passes through muddy gray.
Work in HSL with one hue. Light source = highest saturation and lightness. Anchor = darkest. Add hold and falloff steps. Blend in color. For a palette, change only the hue.
```css
background: linear-gradient(135deg, hsl(250 90% 70%), hsl(250 70% 45%), hsl(250 60% 20%));
```
Check: hue constant across stops.

## 10. Motion follows hierarchy [DWjMgRTiHH-]
Why: if everything appears at once, nothing stands out.
Rule of three: animate primary (heading, by word/line), then secondary, then tertiary, in sequence. Use custom easing.
```css
.p{animation:in .6s cubic-bezier(.2,.8,.2,1) both}.s{animation-delay:.15s}.t{animation-delay:.3s}
```
Check: three layers, staggered, no simultaneous reveal.

## 11. Forms [Db8J5z5Oy8-, DXrDg7AiHuN]
Floating labels (still labelled). Touch target 56px. Rounded corners. Group fields by decision (destination, dates, passengers). Show dates readable. Put the first decision first (trip type).
```html
<label class="relative block"><input class="peer h-14 rounded-2xl pt-5 px-4" placeholder=" "><span class="absolute left-4 top-2 text-xs">Email</span></label>
```
Check: input height ≥ 56px, one chunk per decision.

## 12. Less content [DYMhapEoAHC]
Why: filler splits attention. Show the primary thing large (event, team logos), demote the date, remove the extra actions.
Check: name the one thing the screen is about. It is the largest item.

## 13. Fewer symbols, clearer groups [Dej3pg9IYNv]
Source: the supplied visible-frame takeaway, not an audio transcript.
Why: decorative or ambiguous icons make related values harder to read.
Do: remove decorative or ambiguous icons and group related values.
Use labels, spacing and type before symbol codes such as icons or glyphs.
Make the critical value or action readable at the real viewing size.
Use helper text only for information needed to act.
Show direct progress when progress is the data.
Retain accessibility, necessary labels and uncertainty disclosure.
Don't: imply unmeasured progress or add helper text that repeats the label.
Check: at the real viewing size, can the reader identify the critical value, its group and the action without decoding symbols?
