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
| Move a card | drag its title or top row | `move {x,y}` on drop |
| Resize a card | drag the corner grip (width and height) | `resize {w,h}` on drop |
| Link two cards | drag a card's `link` button onto another card | `link {to}` |
| Pin a card | tap `pin` | `pin {pinned}` |
| Choose who wins a move | header toggle `agent wins` / `user wins` | `input {field:"wins",value}` on `header` |
| Ask the agent | type in the input box, Enter | `input {text}` on `input` |
| Undo | Ctrl+Z or Cmd+Z | `undo` |
| Draw | the pen button, or shift-drag; Esc clears | none (local only) |
| Pan | drag the empty canvas | none |

A change shows at once and stays laid over the server state until the server acks it. An `error` reply puts the card back.

## Agent wins or user wins

The header's `props.wins` holds the rule; the default is agent wins.

- **Agent wins:** an agent move of a card replaces the user's move, even one not acked yet.
- **User wins:** a card the user placed stays where the user put it; the server drops the agent's rect changes to it until the agent calls `reset`.
- **Pinned:** a pinned card keeps its place under both rules.

`src/model.ts` holds the rule (`userKeeps`, `filterAgentPatch`) and the patch code, with no DOM, so the mock server and the tests use the same code.

## Mock world

`mock/world.ts` ports the design's world, so the mock board looks and moves like `docs/genui/design/index.html`:

- **Seed:** 11 items in 4 projects (`spec.projects`), with the design's labelled relations as links. Items carry `kind`, `proj` and `priority` and no `rect`; the canvas places them by project and priority.
- **Live script:** #209 walks its stages, cf-bill claims and fixes a failed refunds test (15-32 s), a new decision arrives at 38 s, and a 6 s clock ticks the timeline and ETAs. Each second the host sampler updates `header.props.stats`, the crew card and any open terminal card.
- **Shell data:** `header.props.tuis` lists the four crew terminals, `input.props.chips` holds the design's ask chips, and `log.props.items` gets a row for each arrival, act, ask and finish. Card props `next` feed the up-next row.
- **Derived props:** `derive()` keeps the stages, ship day, header line (`header.props.title`, `*…*` marks the emphasised words) and each item's own `line` in step with the rest of the spec.
- **Agent answers:** an act on a card (`input {field:"pick"|"merge"|"fly"|"dismiss"|"send"}`) settles it. A typed ask with "or" or "should we" becomes a decision; a chip ("compare", "when", "who", "what's going on", "plan board") brings that card forward; any other ask adds an answer card at the front of the cluster in `payload.about` (`of`, `ids`, or a drawn box `at`).
- **Opens and rewind:** `input {open:"sys"|"tui-<name>"}` on `header` brings a host or terminal card to the front. `input {rewind: seq}` on `log` takes back that row's user op and reopens its card, or removes the card it made.
- **Media:** `/media/:file` serves the embeds from `mock/media/`, including the plan board `plan.html`.

## Spec and style

Types come from `@crewship/genui-spec` (`packages/genui-spec/src/wire.ts`). The canvas draws `type: "card"` components from these props: `title`, `flag`, `kpi {value,unit}`, `steps {items,at}`, `body`, `items`, `pinned`, `hidden`. A child with no `rect` is drawn inside its parent. The `header` and `input` ids dock at the top and bottom unless the spec gives them a `rect`.

Style uses tokens only. `spec.tokens` sets CSS variables on the page (for example `bg`, `ink`, `accent`); a component's `style` sets them on that component. `safeStyle` keeps a token only when its name is lower-case and its value has no URL, no `#`, `rgb` or other non-HSL colour, and no `;{}<>\`. Changing numbers use tabular digits.

## Fixed rule: the sketch layer is on top

The sketch layer is a fixed SVG at the maximum z-index, above every card, link, header and input box. No spec, token or style can move a component above it. While the pen is on, the layer takes all pointer input; a tap on the pen's spot turns it off.

## Limits

- Strokes stay in this browser; they are not sent or saved.
- A drag sends one intent on drop, not a patch per frame.
- No zoom; on a phone, drag the canvas to pan.
