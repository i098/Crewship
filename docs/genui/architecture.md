# Generative UI architecture

Agents get one live screen that they fully control.
An agent calls a tool, the tool sends a spec, and the page draws the spec while it streams.
The frozen design is in [`design/`](design/) (open `design/index.html`); this document is the backend plan that goes with it.

## Picks

| Topic | Pick | Why |
|---|---|---|
| Transport | WebSocket | Lowest drag latency (tldraw pattern); SSE is one-way |
| Host | Cloudflare Worker + one Durable Object (DO) per board | Close to the user, and state survives restarts |
| Wire format | AG-UI event shapes; `STATE_DELTA` carries JSON Patch ops | Reuses a public event format without the AG-UI runtime |
| Store | DO SQLite op log, with a snapshot every 100 ops | Replay, audit, undo and rewind |
| Style | HSL tokens and whitelisted CSS variables | Full look control without raw CSS, so no XSS |
| User vs agent move | Agent wins; a header switch turns it off | When off, user moves stay |
| Auth | Cloudflare Access JWT or Tailscale header, through one identity adapter | Works on and off the tailnet |

Fixed rules: the sketch layer is always the top z-layer, and no spec can change it.
The agent controls every component, including the header and the input box.

## File layout

| Path | Holds |
|---|---|
| `docs/genui/design/` | Frozen design board, fonts and media. Read only |
| [`packages/genui-spec/`](../../packages/genui-spec/src/index.ts) | Zod catalog, style tokens, AG-UI event types, op log row, `applyPatch`, and the board wire types in `src/wire.ts`. Every other part imports it |
| `packages/genui-agent-kit/` | Agent client (`emit_view`, `set_style`, `link`, `pin`, `reset`, `onIntent`) and the Firstmate status bridge. See [agent-kit.md](agent-kit.md) |
| `apps/genui-server/` | Worker + DO: op log, snapshots, undo, move conflicts, WebSocket, identity seam. See [server.md](server.md). [`spike/`](../../apps/genui-server/spike/) holds the P0 spike |
| `apps/genui-web/` | Canvas page and a mock server for local work. See [canvas.md](canvas.md) |
| `data/genui/` | Local runtime data only: `board.sqlite`, `media/` |

## What the agent controls

| Layer | Control |
|---|---|
| `shell` | The page is one spec: header, input box, selection bar, work rail, canvas (`SHELL_SLOTS`). The agent can restyle, move, hide or swap each |
| `view` | Component and props from the zod `catalog` |
| `style` | HSL tokens, type scale, motion preset, and the CSS variables in `STYLE_VARS` |
| `layout` | Cluster, priority, size, position, pin, hidden |
| `links` | Card-to-card relation with a label |
| `custom` | A sandboxed iframe for anything the catalog does not have |
| `sketch` | Fixed: always on top (`SKETCH_Z`). No spec field exists for it |

## Data flow

<!-- ondine:eNo9kNFKw0AQRd_7FfcDGmzVJ5FCNAWFaoIbyUMIZdNMk8VkN-5Osyr5eEla-noOZ2aYY2v8oZGWsftYAGEe1qT5sbQ3G-oU7wdFHmxMWyAINmMSixSup8OILM-M_SJbLIBskojyJyNthSie-zUG2apKMsErbvBnqpnfwrHsejj6XsJbxQTTwxo_2zs4LXvXGAYNZH-xXq1gejfLexylhjnxtDSaL8rEA0Qaptu9eA8T8RKnS3BD-gKj7S4NRyR5TfqkAk8lelnT1CfX_vlTpPEblGbSPCK6Dj8TdOScrGnE6_k9ULo0P8U_pXhl9A -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="architecture-1.dark.svg">
  <img alt="Mermaid flowchart diagram" src="architecture-1.light.svg">
</picture>
<!-- /ondine -->

1. A client connects over WebSocket and gets one `STATE_SNAPSHOT` with its `seq`.
2. An agent tool call sends one spec. The DO validates it against the catalog and stores it as ops.
   Each op is one row: `seq`, `actor`, `cause`, `patch`, `inverse`.
3. The DO sends one `STATE_DELTA` per op, so the page draws the spec while it streams.
   `RUN_STARTED` and `RUN_FINISHED` mark the edges of the tool call.
4. User actions return as `CUSTOM` events named `intent` and go to the agent inbox.

## Persistence and undo

- Every change is one op row, and each row stores its inverse.
- Undo appends the inverse ops (Ctrl+Z, grouped per agent turn).
- Rewind is a time slider to any `seq`; then the user keeps that state or branches from it.
- When the user undoes a wrong choice, the agent ops whose `cause` points at it are reverted too.
- On wake, the DO loads the latest snapshot and replays the ops after it.

## Latency

- Moves apply locally first. A drag sends one patch per frame and saves on drop.
- One WebSocket stays open. The hibernation API keeps it connected while the DO sleeps.
- A cold start happens only after full eviction. Its cost is the constructor plus the snapshot read.
- `locationHint` on the first `get()` puts the DO near the user. Media comes from the R2 cache.

## P0 spike results

The spike in [`apps/genui-server/spike/`](../../apps/genui-server/spike/) proves the path end to end on `wrangler dev --local`.
It uses no Cloudflare account, no deploy and no credentials.

```sh
cd apps/genui-server/spike
bun install
bun run dev                 # wrangler dev --local on :8787; open http://127.0.0.1:8787/
bun emit-view.ts            # one emit_view tool call: 1 spec -> 12 ops -> 12 STATE_DELTA events
bun measure.ts 15           # connect-to-snapshot times; waits 15 s idle, then connects again
```

Measured on 2026-10-29 (workerd from wrangler 4.155, local host; times are WebSocket connect to first `STATE_SNAPSHOT`):

| Case | DO state | Time |
|---|---|---|
| Warm | Same DO instance | 4–9 ms |
| Wake after 15 s idle | DO evicted and rebuilt (new `generation`); replay of 84 ops, or snapshot at 100 plus 20 ops | 14–21 ms |
| Cold process start | New workerd process, state read from disk | 51–101 ms |
| One `emit_view` call | 12 ops, with a 70 ms gap added on purpose so the stream is visible | ≈ 825 ms to `RUN_FINISHED` |

The page drew the same spec at 1280, 768 and 390 px with no horizontal overflow and no page errors.
Limits: these are local workerd numbers, not edge numbers.
In-DO timers stay frozen while synchronous code runs, so the DO cannot time its own boot; `measure.ts` measures from the client.

## Integration check

With `wrangler dev --local` running in `apps/genui-server/` and the `apps/genui-web` mock serving the page, open `http://127.0.0.1:4610/?ws=ws://127.0.0.1:8787/ws/<board>`. The page then draws the real server's board. One run used the agent kit for `emitView` (full spec, then a patch), `setStyle` and `link`. The page drew both cards and the link at 1280 and 390 px with no page errors. A user `input` intent reached the agent's `onIntent` handler.

## Build order

| Phase | Scope | Estimate |
|---|---|---|
| P0 | Spike: one tool call streams one spec through Worker + DO to a page | 2 h |
| P1 | `packages/genui-spec`: catalog, tokens, events; this document; the design copy | 3 h |
| P2 | DO server, op log store, WebSocket, undo and rewind | 4 h |
| P3 | Web canvas: port the frozen design to `apps/genui-web` | 5 h |
| P4 | Agent kit and Firstmate bridge | 3 h |
| P5 | Intents: drag, resize, link; persisted and replayed | 3 h |
| P6 | Auth, PWA, QA on 3 screen sizes | 3 h |

P2, P3 and P4 run in parallel after P1.

## Prior art

| Project | Pattern reused |
|---|---|
| [tldraw-sync-cloudflare](https://github.com/tldraw/tldraw-sync-cloudflare) | WebSocket to one DO per room, SQLite in the DO, assets in R2 |
| [json-render](https://github.com/vercel-labs/json-render) | SpecStream turns model output chunks into JSON patches |
| [AG-UI](https://github.com/ag-ui-protocol/ag-ui) | Event shapes on any transport |
| [A2UI](https://github.com/a2ui-project/a2ui) | Flat component list with small updates |
