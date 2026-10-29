# genui-server

Cloudflare Worker plus one Durable Object (`BoardDO`) per board. Code: `apps/genui-server/`. Run it locally only:

```
cd apps/genui-server && bun install
bun test                # op log, undo, snapshot, conflict rules
bunx wrangler dev --local
```

No deploy, account or credential is used.

## Endpoints

| Route | Use |
|---|---|
| `GET /ws/:boardId` (upgrade) | Canvas socket. Add `?role=agent` for an agent socket. |
| `POST /agent/:boardId` | Agent tool call `{tool, args}`; reply `{seq}`. |

Types live in `src/contract.ts` (stub copy of the P1 `@crewship/genui-spec` types).

## WebSocket frames (JSON text)

- Client: `hello`, `intent {id, kind, targetId, payload, baseSeq?}` (`input` takes `{text}`, forwarded to agents with no spec change, or `{field,value}`, which sets `props[field]`), `undo`.
- Server: `snapshot {seq, spec}` (on connect and `hello`), `ops {ops}`, `ack {id, seq}`, `error {id, msg}`.
- Agent sockets also get every user `intent` frame (this is how `input` reaches the agent).

## Agent tools

`emit_view` (`args.event.delta`, `args.patch` or `args.spec`), `set_style {id?, tokens}`, `link {from, to}`, `pin {id, pinned?}`, `reset {id?, rect?}`. Any tool accepts `args.cause`. A bad call returns HTTP 400 and writes nothing.

## Op log

Each op stores `seq, actor, cause, patch, inverse` in DO SQLite (`ops` table). Patches are RFC 6902 `add`/`replace`/`remove`. A snapshot is saved every 100 ops; on wake the DO loads the latest snapshot and replays later ops.

## Undo

`undo` finds the latest user op not yet undone. It appends the inverse of that op and of every later agent op whose `cause` equals the user op's `cause` (user intents use their intent `id`), newest first. Undo ops have `cause = "undo:<seq>"`.
Limit: inverses are positional. Undoing an op that a later, unrelated op overwrote at the same path restores the old value.

## Move conflicts

Header toggle: `components.header.props.wins` (`"user"`, otherwise agent wins), set by an `input {field:"wins", value}` intent on `header`.
- `agent`: a user move or resize is rejected (`error`) when `baseSeq` is older than the last agent write to that rect.
- `user`: user moves apply; agent patches to a rect the user last moved are dropped until the agent calls `reset` (which clears the user mark).
- Either way, agent rect patches to a pinned card (`props.pinned`) are dropped; `reset` with a `rect` still applies.
- Ops are broadcast before the `ack`.

## Identity

`src/identity.ts` is the only auth seam. The stub trusts everyone, except agent calls must send `Authorization: Bearer $GENUI_AGENT_TOKEN` when that var is set. CF Access and tailnet checks replace it later with the same signature.
