// Local stand-in for apps/genui-server (P2): serves the canvas and speaks the stub WebSocket and agent contract.
// Run: bun apps/genui-web/mock/server.ts  (PORT defaults to 4610)
import type { ServerWebSocket } from "bun";
import page from "../index.html";
import type { Actor, AgentCall, ClientMsg, Op, PatchOp, ServerMsg, Spec } from "../src/contract";
import { applyPatch, esc, filterAgentPatch, intentPatch, invertPatch, safeStyle } from "../src/model";

export const seedSpec = (): Spec => ({
  components: {
    header: { type: "header", props: { title: "#209 is on stage 4, nothing needs you there. +3 more need you.", wins: "agent" } },
    input: { type: "input", props: { placeholder: "Ask anything, tell the AI what to do, or draw" } },
    feed: {
      type: "card",
      props: { title: "#209 swap feed: preview", flag: "swapapp", kpi: { value: 12, unit: "min" }, steps: { items: ["Code", "Build", "Tests", "Preview", "Merge"], at: 3 } },
      rect: { x: 40, y: 20, w: 460, h: 220 },
    },
    decide: {
      type: "card",
      props: { title: "Store swaps in Postgres or SQLite?", flag: "needs you", items: ["Postgres · AI pick", "SQLite"] },
      rect: { x: 560, y: 20, w: 320, h: 240 },
    },
    cpu: { type: "card", props: { title: "CPU", kpi: { value: 66, unit: "%" }, body: "Host load over the last minute." }, rect: { x: 40, y: 290, w: 240, h: 180 }, style: { accent: "hsl(188 95% 58%)" } },
    ship: { type: "card", props: { title: "swapapp ships Fri 14:00", body: "Postgres adds a migrate day." }, rect: { x: 560, y: 280, w: 320, h: 140 } },
  },
  links: [
    { from: "feed", to: "decide" },
    { from: "decide", to: "ship" },
  ],
  tokens: {},
});

type Room = { spec: Spec; seq: number; undo: Op[]; placed: Set<string>; sockets: Set<ServerWebSocket<{ boardId: string }>> };
const rooms = new Map<string, Room>();

const room = (id: string) => {
  let r = rooms.get(id);
  if (!r) rooms.set(id, (r = { spec: seedSpec(), seq: 0, undo: [], placed: new Set(), sockets: new Set() }));
  return r;
};

const send = (ws: ServerWebSocket<unknown>, msg: ServerMsg) => ws.send(JSON.stringify(msg));

function commit(r: Room, actor: Actor, cause: string, patch: PatchOp[], undoable = true): Op | undefined {
  if (!patch.length) return;
  const inverse = invertPatch(r.spec, patch);
  r.spec = applyPatch(r.spec, patch);
  const op: Op = { seq: ++r.seq, actor, cause, patch, inverse };
  if (undoable) r.undo.push(op);
  for (const s of r.sockets) send(s, { t: "ops", ops: [op] });
  return op;
}

/** The mock agent answers a typed question with a new card linked to the input box. */
function answer(r: Room, text: string) {
  const id = `ask-${r.seq + 1}`;
  commit(r, "agent", `input:${id}`, [
    { op: "add", path: `/components/${esc(id)}`, value: { type: "card", props: { title: "You asked", body: text.slice(0, 400) }, rect: { x: 300, y: 470, w: 300, h: 130 } } },
  ]);
}

function onClient(ws: ServerWebSocket<{ boardId: string }>, msg: ClientMsg) {
  const r = room(ws.data.boardId);
  if (msg.t === "hello") {
    r.sockets.add(ws);
    return send(ws, { t: "snapshot", seq: r.seq, spec: r.spec });
  }
  if (msg.t === "undo") {
    const last = r.undo.pop();
    if (last) commit(r, "user", `undo:${last.seq}`, last.inverse, false);
    return;
  }
  try {
    const patch = intentPatch(r.spec, msg.kind, msg.targetId, msg.payload ?? {});
    if (msg.kind === "move" || msg.kind === "resize") r.placed.add(msg.targetId);
    // Ops go out before the ack, so the client never shows the card back at its old place.
    commit(r, "user", `intent:${msg.id}`, patch);
    send(ws, { t: "ack", id: msg.id, seq: r.seq });
    if (msg.kind === "input" && typeof msg.payload.text === "string" && msg.payload.text.trim()) answer(r, msg.payload.text);
  } catch (e) {
    send(ws, { t: "error", id: msg.id, msg: (e as Error).message });
  }
}

function onAgent(boardId: string, call: AgentCall): number {
  const r = room(boardId);
  const a = call.args ?? {};
  let patch: PatchOp[] = [];
  if (call.tool === "emit_view") patch = filterAgentPatch(r.spec, (a.patch as PatchOp[]) ?? [], r.placed);
  else if (call.tool === "set_style") {
    const id = typeof a.id === "string" ? a.id : undefined;
    const tokens = safeStyle(a.tokens as Record<string, unknown>);
    patch = id ? intentPatch(r.spec, "style", id, { tokens }) : [{ op: "replace", path: "/tokens", value: { ...r.spec.tokens, ...tokens } }];
  } else if (call.tool === "link") patch = intentPatch(r.spec, "link", String(a.from), { to: a.to });
  else if (call.tool === "pin") patch = intentPatch(r.spec, "pin", String(a.id), { pinned: a.pinned !== false });
  else if (call.tool === "reset") r.placed.clear(); // the agent takes the layout back
  commit(r, "agent", `tool:${call.tool}`, patch);
  return r.seq;
}

export function start(port = Number(process.env.PORT ?? 4610)) {
  return Bun.serve<{ boardId: string }>({
    hostname: "127.0.0.1", // a dev mock: never listen beyond this host
    port,
    routes: {
      "/": page,
      "/agent/:boardId": {
        POST: async (req: Bun.BunRequest<"/agent/:boardId">) => {
          try {
            return Response.json({ seq: onAgent(req.params.boardId, (await req.json()) as AgentCall) });
          } catch (e) {
            return Response.json({ error: (e as Error).message }, { status: 400 });
          }
        },
      },
    },
    fetch(req, server) {
      const m = /^\/ws\/([^/]+)$/.exec(new URL(req.url).pathname);
      if (m && server.upgrade(req, { data: { boardId: decodeURIComponent(m[1]) } })) return;
      return new Response("not found", { status: 404 });
    },
    websocket: {
      message(ws, raw) {
        let msg: ClientMsg;
        try {
          msg = JSON.parse(String(raw));
        } catch {
          return void send(ws, { t: "error", id: "", msg: "bad json" });
        }
        onClient(ws, msg);
      },
      close(ws) {
        rooms.get(ws.data.boardId)?.sockets.delete(ws);
      },
    },
  });
}

if (import.meta.main) console.log(`genui-web mock on ${start().url}`);
