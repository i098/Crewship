# cf-genui-plan: generative UI app, plan board

**Board:** private session links removed from this repo copy (they carry an access token).
Source `lavish-02a1139251fe6600` is bound and armed (`bin/fm-procevent-lavish.sh arm … --for cf-genui-plan`).
The build is held for the captain as backlog task `cf-genui-build` (origin `cf-genui-plan`). The board's Send button gives one keyed answer for it (`schema fm-bearings-answer.v1`, `question cf-genui-build`, `selection <stack>.<source>.<cutoff>`, `close release`).
No product code was written. No repo file was changed.

## Summary
A web app replaces iMessage: you ask, the AI picks the best view (board, table, chart, diff and more), and it shows live what it is working on.
One responsive shell changes shape across phone, tablet and desktop. The plan uses json-render + Vercel AI SDK, and does not build a renderer from scratch.

## 1. The reel (https://www.instagram.com/reel/DfD-qxGzjMB/)
Fetched anonymously through the Geonode proxy: `reel_watch.py <url> --detail balanced` (env from `~/super.env`, 40 s, no login).
- 33 s, by @mudasirdevv. He reacts to a post by Phil Pitus (@pitus_), "Generative UI #2 - Merge conflicts" (2.4K likes).
- The screen shows one light-theme chat agent. In the thread it draws a commit/task list for "Refresh sessions in the auth middleware #128", then a conflict card with a code diff (`auth.ts`, `middleware.ts`) and a "Resolve conflicts" button. Then it shows checks (Tests, Lint, Types, Preview) and "Ready to merge" with a Merge button. The composer stays at the bottom.
- Speech: "instead of just giving you text, it actually builds the interface you need on the spot … give this video to Claude and ask it to recreate something similar". One model name was not clear in the transcript ("Jev") [unverified].
- The reel shows desktop only. It does not show phone or tablet layouts.
- Contact sheet: `shots/cf-genui-grid.jpg`.

## 2. Reuse check (GitHub API, `gh api repos/<r>`, 2026-10-29)
| Project | Stars | Licence | Verdict | Why |
|---|---|---|---|---|
| vercel-labs/json-render | 18.8k | Apache-2.0 | **Use** | The model can use only components in your zod catalog. It streams progressive renders. One catalog serves React, React Native, Vue and Svelte. It includes 36 shadcn components. |
| vercel/ai (AI SDK) | 27.6k | Apache-2.0 (LICENSE file; API says NOASSERTION) | **Use** | Streaming, tool calls and step events give the data for the "working on" rail. |
| CopilotKit + AG-UI | 38.3k / 16.9k | MIT | Alt | Has a good agent-state stream, but it is a heavier runtime and framework. |
| a2ui-project/a2ui (Google) | 16.9k | Apache-2.0 | Alt | Open spec with flat incremental components. It is an "early stage public preview" (v0.9.1, v1.0 RC), and its first-party renderers are Lit/Angular/Flutter. |
| thesysdev/openui | 14.4k | MIT | Skip | Uses its own "OpenUI Lang" DSL, which is lock-in. |
| assistant-ui | 12.8k | MIT | Skip | Gives a chat shell. We want a canvas that the AI owns. |
Web search providers were blocked (DuckDuckGo bot check), so all facts come from the GitHub API and READMEs.

## 3. Board contents (fits one screen; checked at 1280×760, 1440×860, 1512×900)
- 2-line summary.
- Three live HTML mocks of **one** responsive page (`mock.html`), rendered in iframes at real widths 390 / 820 / 1440:
  - phone: one column, a "Working · 2/4" pill and an inline progress strip;
  - tablet: thread folds into a question header; view + work rail;
  - desktop: thread, generated view and work rail.
- Approach diagram: ask → model plans → pick view (data shape + screen) → stream JSON spec (catalog only, zod-checked) → render per screen. Step events feed the "Working on" rail. Catalog v1 has 8 views.
- Reuse table, as above.
- Timeline: about 10 h wall time with agents in parallel and 16 h of agent work. Spike 2 h → view catalog 4 h ‖ responsive shell 3 h ‖ planner + steps 3 h → firstmate bridge 2 h → QA (3 screens, a11y) 2 h.
- 3 open choices with defaults, and one Send button:
  1. Render stack: **json-render + AI SDK** / CopilotKit + AG-UI / A2UI.
  2. First data source: **firstmate + crew (PRs, tasks)** / general chat.
  3. The cut-off ask "…and there's n…": **no fixed screens (AI picks every view)** / no chat log, canvas only / no install, web/PWA only / free text for the rest of his sentence.

## Evidence of the visual check
Playwright headless shell (`shots/shot.mjs`) took screenshots, and I read each one. The script reported no element past the viewport at any size.
- Mock: `shots/phone.png` (390×844), `shots/tablet.png` (820×1180), `shots/desktop.png` (1440×900).
- Board: `shots/b1280.png` and `shots/b1440.png` (one screen, Send visible), `shots/b390.png` (stacks on phone).
- Fixes made after I looked: the desktop mock overlapped the approach panel; the gantt label overlapped a bar; the gantt axis scale was wrong; Send was below the fold at 760 px; the phone progress strip did not show (CSS order).
- `curl` to the Lavish server: `/artifact/02a1139251fe6600/mock.html` returns 200, so the iframes load. The public link returns 302 to the session.
I did not open the real board in a browser, so that no extra review window connects to it.

## Round 1: poll interrupted
`lavish-02a1139251fe6600.1.result` held only `Error: Lavish Editor poll response was interrupted` (`SERVER_ERROR`) and no captain input. The session page returned 200, so I armed the board again with no reply.

## Round 2: captain feedback, applied
Captain message (`lavish-02a1139251fe6600.2.result`): "does not look cool ngl - also it needs to be creative with it and have cool animations".
Changes (first versions kept as `shots/mock-v1.html` and `shots/index-v1.html`):
- **Mock redesigned** with a dark glass look, a drifting aurora background, the Geist font (`fonts/`, copied from the caveman plugin cache) and double-bezel cards.
- **The mock now plays a loop of two scenes that show the product working:**
  1. The question types into the composer and the orb spins faster while the AI thinks. "Working on" steps slide in with progress spinners that turn into ticks.
  2. The view picker scans Table, Board, Timeline and Chart, then locks on one, with a reason ("3 items with status → board"). Skeleton cards shimmer, then cards spring in one after the other.
  3. In the cards, check pills pop in, progress bars fill, the diff types out, the conflict card glows and the Merge buttons shine. A throughput line draws itself.
  4. Scene 2 ("When does the swap app ship?") blurs the board away and picks **Timeline**. Gantt bars grow, a "today" line sweeps across and a launch milestone pops in.
- Phone, tablet and desktop still use one page with CSS breakpoints. `prefers-reduced-motion` turns the motion off, and `#still` shows a fixed state.
- **Board restyled** in the same visual language: entrance stagger, flowing diagram edges, growing gantt bars and pill radio choices.
- Plan changes: added **Motion** (motiondivision/motion, MIT, 34.6k★, checked by `gh api`) to the reuse table as USE, and added a "Motion + polish" 2 h slice. Wall time stays about 10 h, and agent work is now 18 h.
- Checks: `shots/r2/seq.mjs` took Playwright frames at set times. Mock frames: `d-7000/15500` (1440×900), `t-7000/15500` (820×1180), `p-2800/7000/15500` (390×844). Board frames: `B1280-7500` (fits 1280×760), `B1440-3000` and `B390-3000`. All runs logged no page errors and no element past the viewport, except on the phone board, where the page scrolls as intended. Fixes made after I looked: the spark card stacked instead of sitting in a row; phone suggestion chips ran under the composer; the board grid was not closed correctly; the SVG word spacing was too tight.

## Round 3: captain asked for a prototype he can use
His note (5 parts): "its just boxes, it doesn't actually try to build uniquely in ways that help me understand"; build a prototype he can interact with, without the integrations; iMessage links look bad and he falls back to images; give "one very concise reply with mostly visualization"; he does not want to read 5 bubbles; the canvas must adapt as projects and decisions come in; "higher priority being generated in the center first and stuff being shifted around as priorities change and i address them".

What I built: `index.html` is now a clickable prototype that uses fake data and no integrations. The round-2 board is kept as `plan.html` and linked from the drawer, and the old versions are in `shots/index-v2.html` and `shots/mock-v2.html`.
- **One line, no bubbles:** the top shows one sentence about the center tile, plus "+N more need you". A pill shows what the crew works on now.
- **Priority canvas:** the tile with the highest priority takes the center. A desktop shows the center tile and two side columns, a tablet shows the center tile above a 2×2 grid, and a phone shows the center tile above a dock of 3. Tiles slide when the priority changes. What you ask for stays in the center for 25–30 s, ahead of new events.
- **A bespoke view per item, not boxes:** a decision fork (the curves lead to the options, the AI pick is marked, the chosen path lights up and the other fades), a git branch graph for the merge conflict, a pipeline track with a moving dot, a gantt with a "now" line that moves when he decides, a crew orbit around "you", a failing-test pulse ring with a fix diff, and a diverging bar chart for "Vercel vs Fly".
- **Live world (scripted):** at 6 s the pipeline moves. At 15 s a billing test fails, the AI fixes it over 3 attempts, and the tile leaves. At 38 s a new decision arrives: ship Friday or wait.
- **Cause and effect:** if he picks Postgres, a Migrate stage is added to #209 and the ship bar moves to Fri 16:00. If he merges #212, the conflict tile changes to a merged graph and the crew orbit updates. Done tiles move to the side and then leave.
- The plan drawer ("Plan + Send") holds the build plan and the same 3 choices with defaults. The default for the cut-off ask changed to "no chat bubbles", because his round-3 words point there.
- Checks: `shots/r3/act.mjs` loads the page, picks Postgres, merges with AI, taps the compare chip, waits for the incident, taps a side tile and opens the drawer. I ran it at 1440×900, 820×1180 and 390×844 and looked at each frame (`shots/r3/X-*`, `T-1load`, `P-*`). No page errors. `send.mjs` with a stub `window.lavish` showed that Send queues `selection: jsonrender.fleet.nobubbles` for question `cf-genui-build` and sends it. `plan.html` and the fonts load from the Lavish server (HTTP 200).
- Fixes made after I looked: `classList.toggle(name, undefined)` flipped the classes, which restarted the entrance animation and made the tiles disappear; the line lost its spaces; side tiles were empty; a new event took the center from a tile he had asked for; the fork SVG was 300 px wide; the fork dot was stretched; the phone dock text was clipped.

## Round 4: "a lot of empty space, too blocky … the canvas doesnt feel infinite"
- **Infinite canvas:** the fixed slots are gone. Drag or two-finger scroll pans, and pinch or ctrl+scroll zooms (0.25×–2×). A dot grid moves with the camera. "◎ Back to what matters" appears after you move, and an ask or a tile tap flies the camera back.
- **Priority spiral:** the top item sits at the origin at full size. The next items are 64%, then 52%, then 42%. Each item spirals out from its own fixed angle until it does not overlap anything. Landscape screens spread the items wide, and portrait screens stack them tall. Dashed flowing lines link each item to the center, and items from the same project have brighter lines.
- **No empty space:** each card is now as tall as its content (the SVG keeps its aspect ratio), and the double bezel is gone. Done items stay on the canvas, faded at the outer ring, so the history grows outward. A new far item, "Shipped in the last 14 days", has animated bars.
- Checks: `shots/r4/act.mjs` now also drags, zooms out and taps re-center, at 1440×900, 820×1180 and 390×844. No page errors. Send still queues `jsonrender.fleet.nobubbles`. Fixes made after I looked: the portrait tablet fitted the center too small; a drag selected the header text.

## Round 5: "visual limit seems to be the edge around the center piece ... it should scale infinitely ... the lines make no sense ... keep the font consistent"
- **No edges:** the canvas fills the whole window; the top line and the composer float over it and fade into it. Cards have no border or frame; a dark fill only hides the lines behind them.
- **Zoom has no practical limit:** 0.02×–50× (was 0.25×–2×). The dot grid spacing repeats every doubling, so the grid never runs out at any zoom.
- **Lines only for real relations:** the center-to-everything spokes are gone. Seven named relations remain, each with a label (for example "adds a migrate step", "cf-auth waits on this", "billing slips"). Lines start and end at card edges.
- **One font:** Geist everywhere; GeistMono is removed.
- Checks: `shots/r5/act.mjs` at 1440×900, 820×1180 and 390×844, no page errors; Send still queues `jsonrender.fleet.nobubbles`. Fixed after I looked: link lines and labels showed through the cards; tile text showed through the top line.

## Round 6: "it should be clusters and the closer they are to the center the more important ... click on one / multiple / draw to add or ask more ... now theres no hierachy, too fractured ... keep the border and make sure theres no weird overlap" (+ screenshot)
- **Clusters:** one bordered group per project (swapapp, crew, billing, all). The most important cluster sits in the middle at full size; the others ring it at 62% and then 46%. The center item is the largest card in its cluster.
- **Borders back**, with an opaque fill so lines and cards behind a cluster do not show through. Cluster boxes are placed so they do not overlap.
- **Select and ask:** tap one or more items (or shift-drag / ✎ to draw a loop around them), then type. The answer appears as a new item in their cluster: a skeleton while the AI works, then a view of what it found. A loop around empty canvas marks a spot; asking then pins a new item there.
- **Lines:** at most one labelled line per pair of clusters. A label is dropped when it does not fit the gap.
- Checks: `shots/r6/act6.mjs` at 1440×900, 820×1180 and 390×844 (load, conflict, incident, select, ask, draw, add, zoom out); no page errors; Send still queues `jsonrender.fleet.nobubbles`. Fixed after I looked: the canvas `pen` class matched the ✎ button's styles, so drawing broke the camera; asked items stayed as skeletons (the ready flag was set on a copy); clusters were see-through; line labels slid under clusters; the phone hint overflowed.

## Round 7: "auto zoom is too close in ... a decision/statement queue ... below the search bar that inserts from right to left ... crewship crewship is redundant ... click outside the current cluster → display that cluster, selection only within it ... make it clear an issue is already claimed ... it fades in instead of building it live and morphing" (+ screenshot, 15 layout warnings at 2958 px)
- **Zoom:** the camera fits the cluster on screen to 48% of a wide window and never goes past real size (k ≤ 1 for the middle cluster). At 2958 px the neighbours are now in view.
- **Up-next queue** under the input box: decisions waiting on you, claimed work, and what lands next (`#209 → Preview`, `swapapp ships Fri 16:00`). The oldest item is on the left, and new items slide in from the right. Finished items shrink out, and the rest slide left. A tap brings that item to the center.
- **One project label:** cards inside a cluster no longer repeat the project pill. Only items pinned outside a cluster show it.
- **Cluster focus:** a tap on another cluster opens it, and the camera flies there. Only the open cluster takes taps and lasso hits. The other clusters are `inert`, which also clears the 15 "control outside the viewport" warnings (probe: 0 reachable controls off screen at 2958×1600). "◎ Back to what matters" returns to the top cluster.
- **Claimed issues:** the billing incident shows a pink `CLAIMED · CF-BILL` flag and a "cf-bill claimed this and is fixing it · attempt n of 3" row. The cluster header says "cf-bill is on it", the queue shows "cf-bill claimed: …", and the red alarm pulse is off for claimed items.
- **Live build and morph, no fade:** a new card starts as a skeleton ("building…"), then its parts are written in: text types out, and new blocks wipe in left to right. A state change patches the live DOM (a small morph, no library). Kept nodes stay, SVG geometry tweens from the old value to the new one, and changed text retypes. Probe: pipeline bar `x2` went 200 → 272 → 290 over about 450 ms at the stage change.
- Checks: `shots/r7/act7.mjs` at 1440×900, 820×1180 and 390×844 (build, load, pick, merge, incident, open other cluster, select, ask, zoom out); `shots/r7/probe7.mjs` at 2958×1600; no page errors; Send still queues `jsonrender.fleet.nobubbles`. Fixed after I looked: later items waited 1.9 s as skeletons (the load stagger also ran for them); the claimed flag used the red "failing" colour.

## Round 8: "the most important in the middle ... NOT at fullsize, only centered ... an ack to dismiss [each custom thing] ... title and status should be in the same row ... same font ... make the boxes consistent - fill out like window tile managers ... auto update as things progress ... nothing displayed is ever stale" (+ 2 screenshots)
- **No size by rank:** every cluster has the same size and scale. Importance shows only by distance from the middle.
- **Tiling:** every cluster has the same width (2 × 380 px columns). With an odd count, the top item takes a full row. The other items pair up, and each row is as tall as its tallest item, so the edges line up. Phones (< 600 px) use one column.
- **Header row:** the title and the status pill share the top row (CSS grid in `.core`). The font is Geist only, and the title is 20 px.
- **Dismiss:** items that you make (asked items, the Vercel/Fly compare) have a "Got it ✓" button. It removes the item, and the card shrinks away. If you ask again, a new card is built.
- **Never stale:** a card re-renders when its markup would change (it compares the HTML, not a hand-made key). Each card has a "live · updated Ns ago" stamp. After the script, the world keeps moving: the clock ticks every 6 s, #209 walks through its stages to "merged", shipped goes from 67 to 68 PRs, and the timeline "now" line moves.
- Checks: `shots/r8/act7.mjs` at 1440×900, 820×1180 and 390×844. `shots/r8/probe8.mjs` at 1440×900 and 390×844 showed: Got it removes `t-cmp`; at 84 s, #209 is `merged`, shipped is `68 PRs` and the now line went from x=132 to 158; no page errors. Fixed after I looked: on the phone, the 2-column cluster zoomed to about 0.45, so text was too small. Phones now use one column.

## Round 9: "show system stats and the tuis ... a summary ontop [the header] and i can click for it to generate the ui that updates live ... remove these two since its not realistic ... the boxes can actual embed things ... any media format ... lines arent being overlapped by boxes ... NO subtext ... too glowy ... conveyed as diagrams, shapes ... once something is done, it should be also dismissed and removed" (+ screenshot)
- **Header stats:** CPU, MEM, DISK and NET sparklines plus one pill per crew TUI (cf-auth, cf-feed, cf-bill, cf-ops). A tap builds a live card ("This host", or a terminal tail) in a host cluster; both update every second.
- **Removed:** the two cards in his screenshot; all `sub` subtext lines (0 left); the aurora background and the glow on the orb and cards.
- **Embeds:** an `embed` card type for video, image, site (iframe) and a board; the board plays `media/rounds.mp4` (rounds 3–8) and shows `media/stack.svg`.
- **Done means gone:** a decided item leaves the canvas (`d1` disappears 2.6 s after a pick); the merged pipeline card goes after the plan Send.
- **Lines never under boxes:** a link goes straight when clear; else it takes the shortest orthogonal path on the grid of cluster edges (Dijkstra, bends cost extra) around every other cluster. Code comment `shortcut:` marks the linear scan as fine for tens of clusters, not hundreds.
- Checks: `shots/r9/act9.mjs` at 1440×900, 820×1180 and 390×844 (load, pick, gone, host stats, TUI, live TUI, plan, Send, after). At every step: 0 link segments cross a cluster, 0 cluster overlaps in the final layout, no page errors; video 4 s at 1280 px and the image load. Send still queues `jsonrender.fleet.nobubbles`-style picks. Fixed after I looked: the first router found no clear path for a link past the host cluster (1 crossing); the grid router fixed that, after I fixed its point mapping (it made 40 crossings).

## Round 10: "add an action log in the header ... when selecting something - lock it so other new things that spawn into the same cluster must shift around it ... buttons arent really consistent - and the got it isn't really needed ... some of these previews cannot be expanded ... click to select vs click to view as full ... the lines look off and detached - maybe use some kind of line library ... cluster backgrounds ... liquid glass ... no card border" (+ screenshot)
- **Action log:** a `log N` pill at the end of the header opens a side panel with every event, newest first, timed from page open (new items, picks, merges, claims, fix attempts, stage moves, removals, asks, Send). Esc or ✕ closes it.
- **Selection lock:** a selected card keeps its place in its cluster. New cards fill the rows and the free column around it. When you clear the selection, the cluster tiles again.
- **One button style:** actions, options, plan radios, Send and icon buttons now use one height, one radius and one font, with no borders. The main action is filled. "Got it" is gone. Cards you made that have no buttons of their own get a small ✕.
- **Select vs view:** a tap still selects. Each card has a ⤢ button that opens it in a full view, where it is live and you can use it: the site iframe takes clicks and the video has controls. Esc, ✕ or a tap outside closes it.
- **Lines:** I checked libraries with `gh api`: xyflow (React Flow, MIT, 38.8k★, active), leader-line (MIT, archived), elkjs (active). A library is not needed in the prototype: lines now leave a box from the side that faces the other box and have a dot at each end. They run at right angles and have rounded corners (the React Flow "smoothstep" shape). For the real build, xyflow is the fit.
- **Glass clusters, no borders:** each cluster is a frosted panel (backdrop blur and saturate, inner highlight, a faint tint in the project colour). Cards have no border, only a darker glass fill. A selected card gets a cyan ring.
- Checks: `shots/r10/act10.mjs` ran at 1440×900, 820×1180 and 390×844. A non-top card (`e1`) was locked, and then a card with a higher priority was added to its cluster. The locked card stayed in place (desktop `[418,368]`) and moved after release (`[418,386]`). The full-view iframe has `pointer-events:auto`, the full-view video has `controls`, and the log shows 21–22 rows after a pick. The test sampled 200 points on each line: 0 points fall inside a cluster. There were no page errors. `shots/r10/probe10.mjs` counted 0 cluster overlaps from 1 s to 6 s. I fixed one problem after I looked at the screenshots: in full view, the status label sat under ✕.

## Round 11: "this button feels out of place ... hot key focused ... settings toggle ... ask for the same thing again - it does a shift ... clicking the resource display twice shifts it twice ... limit the other things ... overlap and dim or blur ... draw in and draw out animation ... the resize button doesnt need to have a bg ... visual conflict ... never do any kind of important metric hidden small" (+ 4 screenshots)
- **Navigation toggle:** a header pill switches between `hotkeys` (laptop default) and `buttons` (touch default); `localStorage` keeps the choice. Hotkeys: `0` back, `[` `]` other clusters, `/` ask, `L` log, `Esc` close. The back button moved into the input bar.
- **Same ask twice:** the camera move happens only when the view changes. Test: a second identical ask left `CAM` unchanged at all three sizes.
- **Focus:** clusters that are not open are dimmed and blurred and take no input.
- **Draw in / out:** new cards wipe in from the top; removed cards and clusters fade, shrink and blur out.
- **Expand button:** a bare glyph with no fill, centred on the card header row.
- **Big numbers:** ETA, active agents and shipped PRs are 26 px numbers in the card header.
- Checks: `shots/r11/act11.mjs` at 1440×900, 820×1180 and 390×844; no page errors. Fixed after I looked: at 820 and 1024 px the header squeezed the top line into a narrow column; below 1100 px the header now wraps onto two rows.

## Round 12: "i dont see shit at all, why do i need to do a manual press to see shit"
- **Cause (round 11 regression):** Lavish loads the board in an iframe with `sandbox="allow-scripts allow-forms ..."` and no `allow-same-origin`. Reading `localStorage` there throws a SecurityError, so the script stopped before the first render and the canvas stayed empty. My round-11 tests opened the file directly, so they did not catch this.
- **Fix:** storage reads and writes are in `try`; in the sandbox the hotkeys/buttons choice lasts for the page only.
- Checks: `shots/r12/sbx3.mjs` loads the board inside the same sandboxed iframe over HTTP. Before: 0 cards, `localStorage` SecurityError. After: 10 cards at 1440×900, 820×1180 and 390×844, no script errors.
- Known limit: Lavish sends no CORS header for `fonts/geist-sans.woff2`, so the sandboxed board falls back to the system font. The real app serves its fonts from its own origin, so it does not have this problem.
- Prevention: board checks now run inside a sandboxed iframe like the Lavish one.

## Round 13: "weird bug when i press this" (+ screenshot) / "i cant click the other clusters to bring them up front" / "why cant i open up the log page"
- **Press bug:** a tap locked the card at its pixel position, so the next layout tiled the other cards around that lock and moved them. The preview card then sat over the card below. Fix: the layout tiles as usual first. The lock steps in only when that layout would move a selected card, with 4 px of slack. A tap now moves nothing.
- **Clusters behind:** the front cluster is frosted glass, so the clusters behind show through it, but a tap there hit the front cluster. Fix: a tap on the front glass where a cluster behind shows through opens that cluster.
- **Log and other taps:** a drag that ended away from where it started left the drag counter set. The next tap (the log pill, a chip) was then taken as the end of a drag and dropped. Fix: each new press clears the counter, and drags that start on a control do not count.
- Checks (all inside a copy of the sandboxed Lavish frame, `shots/r13/sbx13c.mjs` at 1280×760 and 1440×900): a press keeps every card where it was; the log opens on one tap after a drag that ended over the header; a tap on a cluster that shows through the glass opens it (`crew`). The same script on the round-12 file failed two of the three: the press moved `d1`/`p1`, and the see-through tap kept `swap` open. WebKit (`sbx13d.mjs`): a direct tap on a cluster behind opens it, and the press keeps the layout. No page errors.
- Not reproduced: headless Chrome opened the log on a plain tap even before the fix. The drag-counter cause is my best match for what he saw [INFERENCE].

## Round 14: "the expand button also doesnt work" / "not clear what the line points to" / "the lines arent being redrawn and it doesnt show what two boxes are connected" / "use monospace by default to prevent layout shift caused by different numbers" (+ 2 screenshots)
- **Lines:** a line now joins two cards, not two clusters. It leaves the front card from its outer side, or through the gap under the card when the card is in the inner column, so it never crosses another card. It then runs in the gutter and ends on the card it affects. Both cards get a ring in the line's colour, and the card behind loses its blur. The label sits on a pill in the line's colour and stays inside the screen.
- **Redraw:** the lines moved out of the zoomed world into a screen-space SVG. A `requestAnimationFrame` loop draws them from the live card positions, so they follow cards while those move, zoom and switch clusters.
- **Monospace:** one `--font` variable, Geist Mono first, then `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`. Lavish blocks the Geist file (no CORS header), so in the board the system monospace font shows. All digits have the same width either way.
- **Expand:** not reproduced. The ⤢ button opened the full view for `d1`, `p1` and `e1` in Chrome and WebKit, also after a drag (`shots/r14/sbx14c.mjs`, `sbx14d.mjs`). His note arrived 5 s after I armed round 13, so he probably saw the round 12 board. On that board a tap moved the preview over the card below, which covered that card's ⤢ [INFERENCE]. The reply asks him to say which card if it still fails.
- Checks (`shots/r14/sbx14e.mjs`, inside a copy of the sandboxed Lavish frame, at 1440×900, 820×1180, 390×844 in Chrome and 1280×760 in WebKit): each line starts on its front card and ends on its target card; 0 segments cross another front card; the label fits inside the screen; the body font is Geist Mono; no page errors. During a cluster switch the line path changed in 3-6 of 6 samples in Chrome. In headless WebKit the cards did not animate either, and the line still matched its card.

## Round 15: "first expand the box then draw the frame inside it" (dithercn / ascii-reveal) / "the glass should be clear, not frosted" / "rewind an action" / "the lines still can point to the wrong thing" (+ screenshot); owner notes via firstmate (`016.msg`): stable layout with no entry animation on refresh, no bend inside a line's own cluster, frosted cards on a liquid-glass cluster
- **Build-in:** a new card first grows its box, then its text decodes from glyphs left to right (ascii-reveal style, in plain JS, no dependency). `ascii-reveal` (MIT, 532★, React ≥17) and `dithercn` (MIT, 108★, shadcn) both fit the real app; ascii-reveal is the closer match.
- **Glass:** the cluster is liquid glass: an SVG displacement filter (`#lg`) bends what is behind it, with no blur. Chromium only; other engines get a clear tint. The cards are frosted (`blur(18px)`).
- **Rewind:** `z` (or ⌘/Ctrl+Z) rewinds the last action, and each log row has a ↶ rewind button. A rewind restores the card and the choices it changed.
- **Lines:** a line leaves the front card through its own outer edge. When the target is on the other side, the line goes out that edge, then down past the cluster, so no bend falls inside the cluster. It ends on a part of the target that the front cluster does not cover, and never under the composer.
- **Stable refresh:** the first paint has no entry animation, no skeleton and no camera move; the canvas starts with transitions off, and a second render fits the camera after the header fills.
- Checks (`shots/r15/sbx15.mjs`, `sbx15w.mjs`, inside a copy of the sandboxed Lavish frame, Chrome at 1440×900, 820×1180, 390×844, WebKit at 1280×760): card and cluster positions were identical at load and 3.5 s later (`stable true`, 0 born); 0 line bends inside the front cluster; every visible endpoint sits on its target card; pick → `z` undoes it; log ↶ undoes it; no page errors. Fixed after I looked: in WebKit at 1280×760 a line ended under the composer, so the endpoint is now held above it; at 1440 the header line wrapped into a narrow column, so it now has a minimum width.
- Not checked: the WebKit rewind step timed out because the test waited for a moving card to stop; Chrome passed it. The refraction is Chromium-only, so Safari shows clear glass.

## Round 16: "why is it animating in on each refresh" / "tight bend in lines" / "multiple layers of glass is not a good idea - go back to frosted" / "glass curves are too weird" / "too many layers" / "sensitive numbers should not be small" / "some things can be an icon" / "if it points to another cluster, the cluster should move out" / "this looks like shit" (conflict card) / "set aspect ratios, custom _ x _, drag to resize, or auto" (+ 10 screenshots)
- **Refresh:** nothing draws until the font and the page have loaded. The canvas stays hidden for two frames, gets its layout again, and then shows with no transition. The cause in WebKit: `fonts.ready` resolved before the font was asked for, and ratio boxes got their size one frame late. Known media carry their shape (`nat`), so a load does not move anything.
- **Glass:** one glass layer only. The cluster is frosted glass; the cards on it are solid. The SVG refraction filter (`#lg`) is gone.
- **Pull-out:** when the front cluster has a line to a card in another cluster, that cluster steps out beside the front one; clusters with no link fade to 30%.
- **Icons and numbers:** embed type flags are icons (site, image, video, audio, board); the plan card shows `~10h build` at 26 px; header numbers sit in a fixed 3ch box, so the pills keep their width.
- **Conflict card:** both branches meet at one `!` marker with "2 files"; the files are chips under the graph.
- **Previews:** each preview has Auto, 16:9, 4:3, 1:1, 9:16 and W × H inputs; its corner drags to resize, and the new shape is kept.
- Checks (`shots/r16/sbx16.mjs` and `shots/r15/sbx15.mjs`, in a copy of the sandboxed Lavish frame, Chrome at 1440×900, 820×1180, 390×844 and WebKit at 1280×760): positions are the same at 0.4 s and 3 s in Chrome; in WebKit the only change happens while the canvas is still hidden (`dbg16d.mjs`); header pills keep their width over 3 s; linked target cards are 0% covered by the front cluster; 1:1 gives 1.00, 3 × 1 gives 3.00, a 60 px corner drag gives a new height at the same width; 0 line bends inside the front cluster; no page errors.
- Fixed after I looked: pills changed width because the figure-space padding fell back to another font; a corner drag widened the box instead of making it taller; WebKit shifted the layout about 1 s after load.
- Not checked: corner drag in headless WebKit (native resize does not react to synthetic mouse input there); real Safari and touch.

## Rounds 17 and 18: "all projects is gonna point to a bajillion things" / "thin animated borders on hover" / "lines teleport during layout shift" / "aspect ratio teleports" / "always run a check for overlap" / "dots dont line up" / "load out should use ascii-reveal" / "render mermaid natively" (mermaid-rs-renderer) / "no animation when the cluster title shifts" / "aspect ratio not working when expanded" / "not aligned"; round 18: "selection colour should never be a connection colour" / "rewrite the content inside each box for the new space" / "no empty space in a box" / "overlap issues" (labels) / "selection border thin on top and bottom"
- **Lines:** in the all-projects view a line shows only for a selected card or a card you asked about. When a route changes shape, the old route blends into the new one. The dots sit on the flat parts of the branches.
- **Labels:** a label goes first on a long straight run of its line, then beside the lane, then over or under the front cluster. It may cover a blurred card behind, never a front card, a linked card, or another label. A label keeps its spot while that spot stays free.
- **Motion:** a thin light runs round a border on hover and fades in and out. The cluster title slides when the cluster moves side. A ratio change grows the box. Removed cards and a closing full view scramble their text back to glyphs (ascii-reveal style, out direction).
- **Mermaid:** `mmdr` (mermaid-rs-renderer v0.3.1, MIT, native Rust, no browser) renders `media/flow.mmd` to `media/flow.svg` in about 0.1 s. A "How it works" diagram card shows it.
- **Boxes:** a box that changes width tier gets its content rewritten for the new width (for example, the conflict card lists its files when wide and shows "2 files" when narrow). The main view fills the spare height. The full view keeps the ratio. Every layout pass checks for overlap in a cluster and lays the cluster out again if two cards touch; text that does not fit wraps.
- **Selection:** white, which no project and no line uses. Rings keep 1.5 screen px at any zoom, so the top and bottom edges no longer vanish when zoomed out.
- Checks (`shots/r18/sbx18.mjs`, `sbx15.mjs`, `sbx16.mjs`, `sbx17b.mjs`, Chrome at 1440×900, 820×1180, 390×844 and WebKit at 1280×760): label cover on front or linked cards is 0 px² in all views at all four sizes; empty space under the last block of a front card is 0 px; no page errors.
- Fixed after I looked: a label spot index from an older route threw "undefined is not iterable"; in headless WebKit the line loop stopped because animation frames were throttled, so lines stayed on the old view. Now the layout also redraws the lines when it settles, and the loop cannot run twice.
- Not checked: real Safari, touch, and how the motion feels at full frame rate.

## Round 19: "it draws the line then moves... it should always move first then draw and undraw then move" / "tf is this" (media past the card) / "dude its overflowing" / "wtf does this triangle mean"
- **Lines:** when a layout change moves cards, the lines undraw first (0.2 s); the cards wait for that, then move. While any card, cluster or the camera is in a move transition (`document.getAnimations()`), no line shows. When all moves stop, the lines draw again from the source card, then the dots and label fade in.
- **Overflow:** the round-18 "fill the spare height" rule stretched media boxes, and their fixed ratio then made them wider than the card. Media boxes are now card width with their own ratio.
- **Triangle:** it was the swapapp ship marker in the billing colour. A cyan "ships" label at the end of the swapapp bar replaces it.
- Checks (`shots/r19/sbx19b.mjs`, Chrome 1440×900, 820×1180, 390×844, WebKit 1280×760): 0 frames where a card moves while a line shows, in the crew and swap views; no media box past its card edge; no triangle; no page errors.
- Not checked: the timing in headless WebKit, which slows animation frames in a background frame. Media cards with a short ratio can leave space under the preview when the card next to them is taller.

## Rounds 20 and 21: dismiss glitch, lines redraw on unrelated shifts, scroll in previews, ask for decisions, plan in a cluster, chat in full view, AI does board actions; "line draw is really delayed", "cards within teleport", "all cards should be manually closeable", "when I start typing it should auto select the input bar", "input box can be dragged to expand outside the box"
- **Round 20:** a dismissed card shrinks and fades in one piece. A line redraws only when its own cards, the front cluster or the camera move. A tapped preview scrolls and takes clicks. A vague ask makes a decision card with options. "plan X" makes a plan card in that cluster. In full view the ask box stays on top, and answers sit under the card. The ask box runs expand, collapse, dismiss, select, clear and rewind.
- **Lines:** a line draws when its move is in the last tenth of the spring, not 1.2 s after. Cards no longer wait 0.2 s for lines to undraw.
- **Teleport cause:** `fit()` measured a card by turning its transition off and reading its height, which cut a running move short. It now measures a hidden copy (cached by width, content and inline sizes).
- **Round 21:** every card has ✕ (rewind restores it). A printable key outside a field focuses the ask box, so the letter lands there; hotkeys stay. The note box and preview corners resize, and the card grows live (`ResizeObserver`) and keeps the note height.
- Checks (`shots/r20/`, Chrome 1440×900, 820×1180, 390×844): 15 of 15 moved cards start their transition in the same frame as their cluster, 0 skip it; 11 of 11 cards have ✕; typing "hello" fills the ask box; a 120 px note drag grows the card 486→682 px with no overflow; earlier suites (stable boot, views, labels, pull-out, ratios, picks, rewind) pass with 0 page errors.
- Not checked: headless WebKit runs no CSS transitions and no native corner drag (a plain 1 s `left` transition stays at 0 after 300 ms), so the move and drag checks are Chrome only. Real Safari and touch are not tested.

## Round 22: "i should be able to drag and resize the popup board freely"
- **Move:** press any empty spot of the full-view window and drag it. The window stays at least 60 px on screen and stops above the ask box.
- **Resize:** drag the grip in the bottom-right corner. The top-left corner stays in place, and the preview height follows the window (`--fh`). The window content scrolls inside, so the grip and the close button stay visible.
- Checks (`shots/r22/sbx23.mjs`, Chrome 1440×900, 820×1180, 390×844, WebKit 1280×760): drag moved the window, the grip resized it by −200×−100, and there were no page errors. The full-view, close, typing and stable-layout regressions pass.
- Not checked: touch drag on a real phone.

## Round 23: "why tf are there two x buttons"
- **Cause:** the full view showed the window ✕ and the card's own remove ✕ (`data-act=drop`).
- **Fix:** the card's remove button hides inside the full view (`#fullBody>.hd [data-act=drop]`), the same way its expand button already did. Cards are still removable from the canvas or by asking.
- Checks (`shots/r23/sbx24.mjs`, Chrome 1440×900 and 390×844): the full views of `e3`, `d1`, `c1` and `p1` each show 1 ✕; 11/11 canvas cards still have a close button; no page errors.

## Round 24: "need a hotkey / button to spread all boards out so i can see all boards at a glance"
- **Spread view:** Space (hotkey mode), the ⊞ button in the ask bar, or asking "show all boards" lays every cluster out at full size, sharp, in the shortest of a few columns (about √(n×1.6) columns on wide screens, √(n×0.7) on narrow ones). The camera fits the whole set. Lines are hidden in this view.
- A tap on a cluster opens it. Space, ⊞, Esc, 0, `[` or `]` leaves the spread view.
- Checks (`shots/r24/sbx25.mjs`, Chrome 1440×900, 820×1180, 390×844): spread shows 4 clusters, all in view, no overlap, 0 blurred cards; a tap opens `g-all`; Esc returns; the AI ask spreads again; no page errors. The earlier view, rewind, dismiss, full-view, close and typing regressions still pass.
- Not checked: headless WebKit stops CSS transitions, so its mid-move state cannot be checked. Real touch is not tested.

## Round 25: "when showing all boards, i should still be able to click to load in the connections between clusters"
- **Spread links:** in the all-boards view a tap on a card selects it and draws its links to cards on other boards, from that card's own board. A tap on open glass still opens the board.
- **Camera fix:** `render()` now runs `selUI()` before `layout()`, so the camera fits once to the new composer height. Before, the line drew, undrew and drew again 1 s later.
- Checks (`shots/r25/`): Chrome 1440×900, 820×1180, 390×844; `c1`, `t1`, `k1`, `p1` each draw one line that ends on top of its target card; no page errors.

## Round 26: "draw should be just normal drawing, not lasso" / "allow all media uploads" / "how come selection store swaps doesnt make a link to swapapp ships?"
- **Draw:** the pen draws solid freehand ink in world space (`#ink` inside `#world`), so it pans and zooms with the board. The lasso selection, polygon test and dashed ghost box are removed. The last stroke marks where the next ask lands (next to the drawing). Clear erases the ink.
- **Uploads:** a ＋ button and drop anywhere. Image, video and audio play; text, JSON, XML and HTML show as escaped text; PDF uses an iframe; any other file gets a Download card. File names are escaped.
- **Link:** `REL` gains `d1 → t1` ("Postgres adds a migrate day"), matching the 8 h ship shift for Postgres.
- Checks (`shots/r26/sbx27.mjs`): Chrome 1440×900 and 390×844; no page errors.
- Not checked: PDF preview (headless Chrome has no PDF viewer), real touch or stylus drawing. A pinned card can sit on a board that later moves into that spot.

## Round 27: "why does everything shift when i select", "empty gap below", billing fades in two parts, a line crosses a label, free cluster and card size, AI sizing; then: hover Postgres to see the timeline change, every component resizable, move components like windows
- **Select shift:** the selection bar floats over the canvas (`.selbar` absolute), so the composer height and the camera stay the same.
- **Gap:** each card grows down to the card under it or to the cluster floor (`layout()`, the `IB` step).
- **Fade:** the cluster glass fades with its cards (`.cluster.gone`, 0.4 s) and is removed at 450 ms.
- **Labels:** `#links` has two layers, `#lnL` (lines) and `#lbL` (labels on top).
- **Size and move:** corner grips (`.tgrip`, `.cgrip`, with a 10 px wider hit area) size a card or a cluster. The cluster header moves the cluster (`S.cpos`). A card's title row moves the card inside its cluster: the card under the pointer swaps place (`S.cord`), and the held card follows the pointer.
- **AI:** the `size` verb: "make billing bigger" sizes the cluster; "make the timeline taller" sizes the card.
- **Hover:** `S.hov` with `pv()` previews an open choice. The timeline bars (CSS `x`/`width` transitions), the "ships" label and the #209 stages change, and they animate back on leave.
- Checks (`shots/r27/sbx29*.mjs`): Chrome 1440x900 and 390x844. Hover 138 px -> 162 px -> 138 px; move d1,p1,e1 -> p1,d1,e1; a tap on the title still selects; grips and the header move work; both AI asks work; no page errors. Earlier probes (sbx15/20/22/25/26/19b/27) pass.
- Not checked: real touch and real Safari. In headless Chrome the hover bar starts to move about 0.4 s late on desktop (0.25 s on the phone size). I did not find the cause.

## Recommendation
Accept the defaults. Build a Next.js/React PWA on the tailnet with json-render (shadcn catalog) + AI SDK. Feed the "working on" rail from firstmate status files and the fleet ledger. Keep iMessage as fallback. Start with the 2 h spike (stream one spec, render it at 3 widths) before the parallel slices.

Skipped: the full app-plan-board pages (security, CI/CD, flow tree), because the spec asked for one short board. These come with the build plan after Send.
