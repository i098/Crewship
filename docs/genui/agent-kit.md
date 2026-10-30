# Generative UI agent kit

`packages/genui-agent-kit` lets an agent drive a Generative UI board. It talks to the board server over the wire types in `@crewship/genui-spec` (`packages/genui-spec/src/wire.ts`). Its intent socket connects with `?role=agent`, because the server forwards user intents only to agent sockets.

## Client

```ts
import { createGenuiClient } from "@crewship/genui-agent-kit";

const g = createGenuiClient({ url: "http://localhost:8787", boardId: "main" });
await g.emitView([{ op: "add", path: "/components/h", value: { type: "Header", props: { text: "Hi" } } }]);
await g.setStyle("h", { color: "hsl(210 40% 50%)" });
await g.link("h", "input");
await g.pin("h");
const off = g.onIntent((i) => console.log(i.kind, i.targetId, i.payload));
```

| Method | Wire call |
|---|---|
| `emitView(spec \| patch)` | `POST /agent/:boardId` `{tool:"emit_view",args:{event}}`. A full `BoardSpec` (`wire.ts`) sends `STATE_SNAPSHOT`. An RFC 6902 array sends `STATE_DELTA`. |
| `setStyle(id, tokens)` | `{tool:"set_style",args:{id,tokens}}` |
| `link(from, to)` | `{tool:"link",args:{from,to}}` |
| `pin(id)` | `{tool:"pin",args:{id}}` |
| `reset()` | `{tool:"reset",args:{}}` |
| `onIntent(handler)` | WebSocket `/ws/:boardId`. The client sends `hello`, then calls the handler for each `{t:"intent"}` frame the server forwards. It returns an unsubscribe function. |

Each tool call returns `{seq}`. A non-2xx reply rejects the promise. `close()` closes the socket.

## Firstmate bridge

`bin/genui-bridge.ts` reads status lines (`state [at=epoch]: text`) and sends one `emit_view` patch for each line. The patch sets component `task-<id>` (type `StatusCard`).

```sh
tail -F state/*.status | bun packages/genui-agent-kit/bin/genui-bridge.ts --url http://localhost:8787 --board main
```

`tail -F` headers (`==> path.status <==`) set the task id. For plain stdin, pass `--task <id>`; the default is `firstmate`. `GENUI_URL` and `GENUI_BOARD` replace the flags. Lines that do not match the status format are ignored.

## Test

`cd packages/genui-agent-kit && bun test` runs against a local mock server. No P2 server is needed.

## Auth

The kit sends no token in this phase. Keep `GENUI_AGENT_TOKEN` unset on the server until the P6 auth work. With the token set, every kit and bridge call gets 401. With the token unset, any client can claim `role=agent` with `?role=agent` and receive forwarded intents.
