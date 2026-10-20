# UI shared basics

Read by the `app-dashboard` and `landing-marketing` skills. Each rule here applies to both surfaces and lives only here.
Same format and sources as those skills: `https://www.instagram.com/reel/<id>/` (ids in brackets).
Additional decision rules draw on [Laws of UX](https://lawsofux.com/).

## Alignment

### Optical alignment, not bounding-box centering [DeAcXnovBqX]
Source: a reel by @pikacodes, not Zander Whitehurst.
Why: an alignment tool centers the bounding box, not the visual mass. A play triangle centered by its box leaves more shape on the left, so it looks off.
Do: place the glyph where it looks balanced to the eye. For an equilateral triangle, put the centroid (where the medians meet) on the circle's center: the triangle moves right and its three corners end equidistant from the circle edge. Other shapes need other adjustments. Judge the result at the size people will see it, not zoomed in.
Keep the offset inside the icon asset or component, so every reuse inherits it.
Implementation example (not from the reel): shift the glyph, keep the button box and hit target as they are.
```html
<!-- don't: center the box, leave the glyph as is -->
<button class="grid size-14 place-items-center rounded-full"><svg class="size-6">…play…</svg></button>
<!-- do: nudge the glyph only; the button, its size and its layout do not change -->
<button class="grid size-14 place-items-center rounded-full"><svg class="size-6 translate-x-px">…play…</svg></button>
```
Don't: use one pixel offset for every icon, or fix balance with negative margins on the container.
Check: for the play triangle in a circle, are the three corners the same distance from the circle edge? For any other shape, does it look balanced at the real size? Hide the glyph; the button must keep its size and position.

### Left-align text [DcN2nJEu9L2, DdbcSa1OBhO]
Why: each centered line is an alignment anchor. Left align gives one.
Use proximity: heading, image, price, CTA in a column.
```html
<!-- don't --> <div class="text-center"> <!-- do --> <div class="text-left">
```
Check: no stacks of centered lines. One anchor for content, one for actions.

### Nested corner radius [DcgD9mmunMX]
Why: guessed radii look misaligned.
`outer = inner + gap`. Example: 24 + 16 = 40.
```html
<div class="rounded-[40px] p-4"><div class="rounded-[24px]">
```
Check: every nested pair satisfies the formula.

## One primary button per view [DW3nH1YCIRC, DYMhapEoAHC]
Why: all-primary buttons remove hierarchy.
Check: one primary button per view.

## Relative units for type and spacing [DeBe2VfJ6B8]
Source: a reel by @reactjsofficial.
Why: a font size in `px` ignores a user who raises the browser default font size.
Do: `rem` for font sizes and spacing (root default 16 px, so 1.5rem = 24 px; one root change scales the site). `em` for padding that should grow with its text. `%` for widths. `px` for borders and hairlines.
Implementation clarification (not from the reel): `em` on `font-size` is relative to the parent and compounds when nested (1.2em in 1.2em = 1.44); `em` on padding or margin is relative to the element's own computed font size. `px` fonts still scale with page zoom; they ignore only a changed default font size. Never set the root font size in `px`; leave the user's preference as the root.
```css
/* don't */ html { font-size: 14px } h1 { font-size: 32px }
/* do */    h1 { font-size: 2rem } .btn { padding: .5em 1em } .col { width: 50% } .card { border: 1px solid }
```
Check: raise the browser default font size; text and spacing grow, borders do not.

## Accessibility
- Keep every necessary label. A floating label is still a label [Db8J5z5Oy8-]. Removing icons or helper text never removes a label [Dej3pg9IYNv].
- Respect `prefers-reduced-motion: reduce` (implementation clarification, not from a reel): replace looping or moving animation with a static frame.

## Aesthetic-usability effect
Why: visual polish can hide usability problems during review.
Do: test task completion separately from appearance.
Check: can a new user finish the primary task without help, even if they praise the design?

## Doherty threshold
Why: slow responses interrupt the user's flow.
Do: acknowledge input within 400 ms with a visible control state or result; follow the app's loading policy for longer work.
Check: under a slow connection, does the control respond within 400 ms without claiming the request has finished?

## Similarity
Why: similar-looking controls imply similar behavior.
Do: give controls with the same role a consistent shape, color and label style.
Check: do matching controls behave alike across the flow?

## Common region
Why: a shared boundary implies that its contents belong together.
Do: add a shared surface only when spacing alone cannot separate related groups.
Check: does each surface enclose one meaningful group without implying a relationship to unrelated content?

## Progressive disclosure
Why: secondary choices compete with the current decision.
Do: reveal advanced options when needed; keep required choices, costs and errors visible.
Check: can a user finish the common task without opening advanced options, while still seeing all required information?

## Recognition over recall
Why: remembering earlier choices adds work and errors.
Do: show available choices and earlier selections beside the decision that needs them.
Check: can the user decide without remembering another screen or copying information from it?

## Peak-end rule
Why: the most intense moment and the ending strongly affect how users remember a task.
Do: provide recovery at the highest-risk step and end with a clear outcome and next action.
Check: can the user recover from that step and tell what happened when the task ends?

## Serial position effect
Why: users tend to remember the first and last items in a sequence.
Do: place important items first or last when no task order or familiar convention takes priority.
Check: are key items buried in the middle of an otherwise unordered list?

## Tesler's law
Why: removing a control can leave its work for the user.
Do: handle routine calculations and reuse known input; keep consequential choices explicit and defaults editable.
Check: did simplification remove user work without hiding a required decision?

## Postel's law
Why: harmless formatting differences should not prevent valid input.
Do: accept equivalent input formats and normalize them without changing meaning; reject ambiguous or unsafe input with a specific message.
Check: do equivalent formats produce the same value while ambiguous input requires correction?
