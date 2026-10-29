# Generative UI: web canvas

`apps/genui-web/` is the page that draws a board. An agent sends a spec; the canvas renders it and sends the user's changes back as intents. Every component, including the header and the input box, comes from the spec, so the agent controls all of it.

## Run it

```sh
bun apps/genui-web/mock/server.ts   # http://127.0.0.1:4610/  (PORT to change)
(cd apps/genui-web && bun test)    # model and mock-server contract tests
```

The mock server stands in for `apps/genui-server`. It serves the page, speaks the WebSocket contract at `/ws/:boardId`, and takes agent calls at `POST /agent/:boardId`. Open `?board=<id>` for another board, or `?ws=<url>` to point the page at a real server.

Try an agent call:

```sh
curl -X POST 127.0.0.1:4610/agent/demo -d '{"tool":"emit_view","args":{"patch":[{"op":"add","path":"/components/header/props/title","value":"Hello from the agent"}]}}'
curl -X POST 127.0.0.1:4610/agent/demo -d '{"tool":"set_style","args":{"tokens":{"accent":"hsl(320 90% 66%)"}}}'
```

## What the user can do

| Action | How | Intent sent |
|---|---|---|
| Reorder cards | drag a card's title row onto another card in its cluster; a pinned card moves freely | none (local order); `move {x,y}` on drop for a pinned card |
| Resize a card | drag the corner grip (width and height) | `resize {w,h}` on drop |
| Link two cards | drag a card's link glyph onto another card | `link {to}` |
| Pin a card | tap `pin` | `pin {pinned}` |
| Choose who wins a move | header toggle `agent wins` / `user wins` | `input {field:"wins",value}` on `header` |
| Ask the agent | type in the input box, Enter | `input {text}` on `input` |
| Undo | Ctrl+Z or Cmd+Z | `undo` |
| Draw | the pen button, or shift-drag; Esc clears | none (local only) |
| Pan, zoom | drag the empty canvas or scroll; pinch or Ctrl/Cmd+scroll zooms 0.02–50× | none |
| Open a cluster | tap a cluster behind, or any cluster in the spread view | none |

A change shows at once and stays laid over the server state until the server acks it. An `error` reply puts the card back.

## Agent wins or user wins

The header's `props.wins` holds the rule; the default is agent wins.

- **Agent wins:** an agent move of a card replaces the user's move, even one not acked yet.
- **User wins:** a card the user placed stays where the user put it; the server drops the agent's rect changes to it until the agent calls `reset`.
- **Pinned:** a pinned card keeps its place under both rules.

`src/model.ts` holds the rule (`userKeeps`, `filterAgentPatch`) and the patch code, with no DOM, so the mock server and the tests use the same code.

## Layout and camera

The canvas ports the frozen design's engine (`docs/genui/design/index.html`, `layout()` and `drawLinks()`):

- **Clusters** (`src/layout.ts`): cards group by `props.proj` into one frosted-glass panel per project, coloured from `spec.projects[proj].hsl`, with a header pill that says how many cards need you.
- **Priority:** the cluster with the highest `props.priority` sits in front; the others fan out behind it, smaller, dimmed and blurred. A cluster that the front one links to steps out beside it, and the rest fade to 30%. `done` cards rank last; `removed` cards leave.
- **Tiling:** two 380 px columns (one on a phone). With an odd count the top card takes a full row; each row is as tall as its tallest card, and every card grows down to the card under it, so no empty space is left. A `rect` width and height act only as a user-set size floor; `rect.x/y` places a card only when it is pinned.
- **Links** (`src/links.ts`): a line joins a card in the front cluster to the card it affects in another cluster, with right-angle routes, a dot at each end, a `label` pill, and a ring on both cards. Lines are drawn in screen space every frame; a line undraws while its cards move and draws again after.
- **Camera:** fits the front cluster to 48% of a wide screen (the full width on a phone) between the header and the ask bar. `ctx.cam` gives `home()`, `spread()`, `cycle(±1)`, `open(proj)` and `toWorld()` to the shell and the overlays. The spread view lays every cluster out at a glance.

## Spec and style

Types come from `@crewship/genui-spec` (`packages/genui-spec/src/wire.ts`). The canvas draws `type: "card"` components from these props: `title`, `flag`, `kpi {value,unit}`, `steps {items,at}`, `body`, `items`, `pinned`, `hidden`. A child with no `rect` is drawn inside its parent. The `header` and `input` ids dock at the top and bottom unless the spec gives them a `rect`.

Style uses tokens only. `spec.tokens` sets CSS variables on the page (for example `bg`, `ink`, `accent`); a component's `style` sets them on that component. `safeStyle` keeps a token only when its name is lower-case and its value has no URL, no `#`, `rgb` or other non-HSL colour, and no `;{}<>\`. Changing numbers use tabular digits.

## Fixed rule: the sketch layer is on top

The sketch layer is a fixed SVG at the maximum z-index, above every card, link, header and input box. No spec, token or style can move a component above it. While the pen is on, the layer takes all pointer input; a tap on the pen's spot turns it off.

## Limits

- Strokes stay in this browser; they are not sent or saved.
- A drag sends one intent on drop, not a patch per frame.
- Card order set by dragging stays in this browser only.
- A link between two cards in one cluster is kept in the spec but not drawn, as in the design.
