---
name: landing-marketing
description: Use when designing, building, or reviewing landing pages, marketing sites, hero sections, event or product promos, sign-up CTAs and their copy, entrance motion, or gradients. Skip app screens and dashboards, and backend, CLI, or non-visual work.
---

# Landing and marketing UI

Less is the default. Each rule: rule, why, do/don't, review line.
Sources: Zander Whitehurst reels, `https://www.instagram.com/reel/<id>/` (ids in brackets).
Rules come from the reel transcripts. Examples are Tailwind translations, not frame copies.
Read [shared-basics.md](shared-basics.md) first: alignment, one primary button per view, relative units and accessibility apply here too.

## 1. Less content [DYMhapEoAHC]
Why: filler splits attention. Show the primary thing large (event, team logos), demote the date, remove the extra actions.
Check: name the one thing the screen is about. It is the largest item.

## 2. CTA copy [DW3nH1YCIRC, DYMhapEoAHC]
Auth: ghost "Sign in" + primary "Sign up". Start each CTA with a verb ("Buy tickets"). A free tier: verb + value.
Check: every CTA starts with a verb.

## 3. Motion follows hierarchy [DWjMgRTiHH-]
Why: if everything appears at once, nothing stands out.
Rule of three: animate primary (heading, by word/line), then secondary, then tertiary, in sequence. Use custom easing.
```css
.p{animation:in .6s cubic-bezier(.2,.8,.2,1) both}.s{animation-delay:.15s}.t{animation-delay:.3s}
```
Check: three layers, staggered, no simultaneous reveal.

## 4. Gradients [DUlFbcniJNj]
Why: dark + light in RGB passes through muddy gray.
Work in HSL with one hue. Light source = highest saturation and lightness. Anchor = darkest. Add hold and falloff steps. Blend in color. For a palette, change only the hue.
```css
background: linear-gradient(135deg, hsl(250 90% 70%), hsl(250 70% 45%), hsl(250 60% 20%));
```
Check: hue constant across stops.

## 5. Test marketing ideas with repeatable systems [DfDgu1Ry-Gb]
Build reusable workflows for ad tests, landing-page variants, and buyer-question content. Turn one source asset or a keyword dataset into multiple drafts, then review each draft before publishing.
For paid ads, compare performance against a chosen metric and pause weak ads only when the evidence supports that choice. Check tracking before using results to make decisions.
Check: does each workflow create reviewable variants, use a defined success measure, and preserve human approval before publication or spend changes?
