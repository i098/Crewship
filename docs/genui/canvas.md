# Generative UI: web canvas

`apps/genui-web/` is the page that draws a board. An agent sends a spec; the canvas renders it and sends the user's changes back as intents. Every component, including the header and the input box, comes from the spec, so the agent controls all of it.

## Run it

```sh
(cd apps/genui-web && bun run dev)  # http://127.0.0.1:4610/  (PORT to change)
(cd apps/genui-web && bun test)     # model, feeder, and genui-server contract tests
```

`bun run dev` starts `apps/genui-server` under `wrangler dev --local` (port 8787, `GENUI_SERVER` to change), a page server that serves the canvas and passes `/ws/:boardId` through to it, and the feeder. Agent calls go to the board server at `POST /agent/:boardId`. Open `?board=<id>` for another board, or `?ws=<url>` to point the page at another server.

Try an agent call:

```sh
curl -X POST 127.0.0.1:8787/agent/demo -d '{"tool":"emit_view","args":{"patch":[{"op":"add","path":"/components/header/props/title","value":"Hello from the agent"}]}}'
curl -X POST 127.0.0.1:8787/agent/demo -d '{"tool":"set_style","args":{"tokens":{"accent":"hsl(320 90% 66%)"}}}'
```

## What the user can do

| Action | How | Intent sent |
|---|---|---|
| Reorder cards | drag a card's title row onto another card in its cluster; a pinned card moves freely | none (local order); `move {x,y}` on drop for a pinned card |
| Resize a card | drag the corner grip (width and height) | `resize {w,h}` on drop |
| Link two cards | drag a card's link glyph onto another card | `link {to}` |
| Pin a card | tap `pin` | `pin {pinned}` |
| Choose who wins a move | header `wins` pill (tap to switch) | `input {field:"wins",value}` on `header` |
| Ask the agent | type in the input box, Enter | `input {text}` on `input` |
| Undo | Ctrl+Z or Cmd+Z; plain `z` in hotkeys mode | `undo` |
| Select | tap a card: white ring and a `locked` tag; the bar shows "N selected · Bring to center · Clear"; double tap brings it to the centre | none; the next ask carries `about.ids` |
| Full view | `⤢` on a card: a window over the board; drag it by any empty spot, resize it from the corner grip; the ask box stays on top and answers (`props.of`) sit under the card | the next ask carries `about.of` |
| Remove a card | `✕` | `input {field:"removed",value:true}` |
| Draw | the pen button (white when on), or shift-drag on the board; white ink; the bar shows "Your drawing · Clear" | none; the next ask carries `about.at` (the drawing's box) |
| Upload | `＋`, or drop files anywhere: image, video and audio play; text, JSON and HTML show as escaped text; a PDF opens in a frame; other files get a Download link | none (local only) |
| Hotkeys | `0` back, `[` `]` clusters, `/` ask, `L` log, `z` rewind, space spread, Esc closes (full view, log, selection, spread); any letter types into the ask box | as the button they press |
| Pan, zoom | drag the empty canvas or scroll; pinch or Ctrl/Cmd+scroll zooms 0.02–50× | none |
| Open a cluster | tap a cluster behind, or any cluster in the spread view | none |

A change shows at once and stays laid over the server state until the server acks it. An `error` reply puts the card back.

## Agent wins or user wins

The header's `props.wins` holds the rule; the default is agent wins.

- **Agent wins:** an agent move of a card replaces the user's move, even one not acked yet.
- **User wins:** a card the user placed stays where the user put it; the server drops the agent's rect changes to it until the agent calls `reset`.
- **Pinned:** a pinned card keeps its place under both rules.

`src/model.ts` holds the client side of the rule (`userKeeps`) and the patch code, with no DOM; `apps/genui-server/src/guard.ts` holds the server side.

## Layout and camera

The canvas ports the frozen design's engine (`docs/genui/design/index.html`, `layout()` and `drawLinks()`):

- **Clusters** (`src/layout.ts`): cards group by `props.proj` into one frosted-glass panel per project, coloured from `spec.projects[proj].hsl`, with a header pill that says how many cards need you.
- **Priority:** the cluster with the highest `props.priority` takes the middle of the board; the others sit around it, ring by ring, with 120 px of clear space between clusters. The grid follows the screen's shape: more columns on a wide screen, fewer on a phone. In focus a cluster is smaller the further out its ring is, dimmed and blurred; in spread all are full size. A cluster that the front one links to takes the next spot beside it, and the rest fade to 30%. `done` cards rank last; `removed` cards leave.
- **Cards in a cluster:** the cards tile in rows like a window manager, with no hole between them. A cluster of n cards has ⌈√n⌉ columns of 380 px (one on a phone); the top row takes the cards left over, so the top card is the widest. Each row is as wide as the widest row and as tall as its tallest card, and the cluster frame wraps the rows. A card taller than its content gives the spare room to its view, or shows more body lines (`src/fit.ts`). A `rect` width keeps that card's width and the other cards in its row share the rest; a `rect` height is a floor for its row. `rect.x/y` places a card only when it is pinned. `packCheck` in `src/layout.ts` measures holes, overlaps and cards outside the frame; in a browser, `genuiCheck()` runs it for every cluster on the page.
- **Links** (`src/links.ts`): a line joins a card in the front cluster to the card it affects in another cluster, with right-angle routes, a dot at each end, a `label` pill, and a ring on both cards. Lines are drawn in screen space every frame; a line undraws while its cards move and draws again after.
- **Camera:** fits the front cluster to 72% of a wide screen between the header and the ask bar; on a phone it fits the front cluster's top card to the full width, and the cards under it show at the bottom edge. `ctx.cam` gives `home()`, `spread()`, `cycle(±1)`, `open(proj)` and `toWorld()` to the shell and the overlays. The spread view lays every cluster out at a glance.

## Feeder

`feeder/feeder.ts` is the agent that fills the board with real state, as `emit_view` calls on an agent socket (`/ws/:boardId?role=agent`). Nothing in it is invented: a source it cannot read shows in a "Sources not read" card.

- **Sources:** open PRs and their checks and merged PRs per day (`gh api`), crew threads (`crewboard topics --summary`), today's model cost (`~/.omp/stats.db`, read-only), and this host's CPU, memory and disk, sampled by the feeder. It polls every 60 s. The newest open PR also shows GitHub's preview image as an embed.
- **Derived props:** each card's `priority` and `line`, and the header line (`header.props.title`, `*…*` marks the emphasised words) from the top card plus how many others need you.
- **Actions:** approve or decline on a PR, and "Claim the fix" on a PR with failed checks, write a record to the crewboard topic `genui`. A merge is never run: the approve record carries the `gh pr merge` command as a draft for the owner. A typed ask goes to the same topic with an id; a crew agent answers with `crewboard pub genui '{"to":"<id>","reply":"…"}'`, and the reply fills the ask card. A header pill opens host stats or that agent's `crewboard tail` lines.

## Spec and style

Types come from `@crewship/genui-spec` (`packages/genui-spec/src/wire.ts`). The canvas draws `type: "card"` components from these props: `title`, `flag`, `kpi {value,unit}`, `steps {items,at}`, `body`, `items`, `pinned`, `hidden`. A child with no `rect` is drawn inside its parent. The `header` and `input` ids dock at the top and bottom unless the spec gives them a `rect`.

Style uses tokens only. `spec.tokens` sets CSS variables on the page (for example `bg`, `ink`, `accent`); a component's `style` sets them on that component. `safeStyle` keeps a token only when its name is lower-case and its value has no URL, no `#`, `rgb` or other non-HSL colour, and no `;{}<>\`. Changing numbers use tabular digits.

## Shell

`src/shell.ts` draws the header, the bottom bar and the action log; `paintShell(spec, ctx)` runs on every paint. All of it comes from the spec:

| Part | Spec source | A tap sends |
|---|---|---|
| Header line | `header.props.title`; `*starred words*` show amber. It is one line with an ellipsis; hover shows the full text, and a tap opens it in a popover | none |
| Host stats | `header.props.stats {cpu,mem,disk,net: number[]}` (0-100 samples; `net` in MB/s) | `input {text,open:"sys"}` on `header` |
| Terminal pills | `header.props.tuis [{name,proj}]`; the dot is `spec.projects[proj].hsl` | `input {text,open:"tui-<name>"}` on `header` |
| Chips | `input.props.chips: string[]` | `input {text}` on `input` (same as typing it) |
| Placeholder | `input.props.placeholder`; a selection or the full view use their own copy | none |
| Up next | cards with `need` (Decide), `claim` (claimed) or a `next` string | `ctx.cam.bring([id])` |
| Action log | `log.props.items [{at,text,proj,seq?,rwd?}]`, `at` in seconds | `input {rewind: seq}` on `log` |

The header has a fixed height: one row on a wide screen, two rows at 760 px wide or less. Nothing in it wraps, so it never pushes the board down. The host stats and terminal pills are one row that scrolls sideways; ‹ folds that row away and › shows it again. The nav pill switches the hint row between hotkeys and buttons. The nav and fold choices stay in `localStorage`. ◎ calls `ctx.cam.home()`, ⊞ calls `ctx.cam.spread()`, and ＋ opens the hidden `#file` input.

## Fixed rule: the sketch layer is on top

The ink layer is a fixed SVG at the maximum z-index, above every card, link, header, full view and input box. No spec, token or style can move a component above it. It copies the board camera's transform, so strokes pan and zoom with the board. `src/overlays.ts` owns it with the selection, the full view, uploads and hotkeys.

## Limits

- Strokes and uploaded files stay in this browser; they are not sent or saved. Upload cards float on the board in world space, outside the cluster layout.
- A drag sends one intent on drop, not a patch per frame.
- Card order set by dragging stays in this browser only.
- A link between two cards in one cluster is kept in the spec but not drawn, as in the design.
