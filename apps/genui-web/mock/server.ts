// Local stand-in for apps/genui-server (P2): serves the canvas and speaks the stub WebSocket and agent contract.
// Run: bun apps/genui-web/mock/server.ts  (PORT defaults to 4610)
import type { ServerWebSocket } from "bun";
import page from "../index.html";
import type { Actor, AgentCall, ClientMsg, Op, PatchOp, ServerMsg, BoardSpec } from "@crewship/genui-spec";
import { applyPatch, filterAgentPatch, intentPatch, invertPatch, safeStyle } from "../src/model";
import { type About, seedSpec, World } from "./world";

type Room = { spec: BoardSpec; seq: number; undo: Op[]; byUser: boolean; placed: Set<string>; sockets: Set<ServerWebSocket<{ boardId: string }>>; world: World };
const rooms = new Map<string, Room>();

const room = (id: string) => {
  let r = rooms.get(id);
  if (!r) {
    const made: Room = {
      spec: seedSpec(), seq: 0, undo: [], byUser: false, placed: new Set(), sockets: new Set(),
      // the world's own changes are the agent's and not on your undo stack; what it does at once for your action is
      world: new World(() => made.spec, (cause, patch) => commit(made, "agent", cause, patch, made.byUser)),
    };
    rooms.set(id, (r = made));
    made.world.start();
  }
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

/** Only well-formed parts of the client's `about` reach the world. */
function aboutOf(v: unknown): About {
  if (!v || typeof v !== "object") return {};
  const a = v as Record<string, unknown>; // client JSON, checked field by field below
  const at = a.at && typeof a.at === "object" ? (a.at as About["at"]) : undefined;
  return {
    of: typeof a.of === "string" ? a.of : undefined,
    ids: Array.isArray(a.ids) ? a.ids.filter((i): i is string => typeof i === "string") : [],
    at,
  };
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
    r.world.change("world:undo");
    return;
  }
  try {
    const patch = intentPatch(r.spec, msg.kind, msg.targetId, msg.payload ?? {});
    if (msg.kind === "move" || msg.kind === "resize") r.placed.add(msg.targetId);
    const mark = r.undo.length;
    // Ops go out before the ack, so the client never shows the card back at its old place.
    commit(r, "user", `intent:${msg.id}`, patch);
    send(ws, { t: "ack", id: msg.id, seq: r.seq });
    if (msg.kind !== "input") return;
    const text = msg.payload.text, open = msg.payload.open;
    r.byUser = true;
    try {
      if (typeof open === "string") r.world.open(open);
      else if (typeof text === "string" && text.trim()) r.world.answer(text, aboutOf(msg.payload.about));
      else r.world.react(msg.targetId, msg.payload.field);
    } finally {
      r.byUser = false;
    }
    // one action is one step back: fold the intent and the world's reply into one undo entry
    const ops = r.undo.splice(mark);
    if (ops.length) r.undo.push({ ...ops.at(-1)!, patch: ops.flatMap((o) => o.patch), inverse: ops.toReversed().flatMap((o) => o.inverse) });
  } catch (e) {
    send(ws, { t: "error", id: msg.id, msg: (e as Error).message });
  }
}

function onAgent(boardId: string, call: AgentCall): number {
  const r = room(boardId);
  const a = call.args ?? {};
  let patch: PatchOp[] = [];
  if (call.tool === "emit_view") patch = filterAgentPatch(r.spec, ((a.event as { delta?: PatchOp[] } | undefined)?.delta ?? a.patch ?? []) as PatchOp[], r.placed);
  else if (call.tool === "set_style") {
    const id = typeof a.id === "string" ? a.id : undefined;
    const tokens = safeStyle(a.tokens as Record<string, unknown>);
    patch = id ? intentPatch(r.spec, "style", id, { tokens }) : [{ op: "replace", path: "/tokens", value: { ...r.spec.tokens, ...tokens } }];
  } else if (call.tool === "link") patch = intentPatch(r.spec, "link", String(a.from), { to: a.to });
  else if (call.tool === "pin") patch = intentPatch(r.spec, "pin", String(a.id), { pinned: a.pinned !== false });
  else if (call.tool === "reset") r.placed.clear(); // the agent takes the layout back
  commit(r, "agent", `tool:${call.tool}`, patch);
  r.world.change("world:agent");
  return r.seq;
}

export function start(port = Number(process.env.PORT ?? 4610)) {
  return Bun.serve<{ boardId: string }>({
    hostname: "127.0.0.1", // a dev mock: never listen beyond this host
    port,
    routes: {
      "/": page,
      // the design's media for the seed world's embeds
      "/media/:file": (req: Bun.BunRequest<"/media/:file">) => {
        const f = req.params.file;
        return /^[\w-]+\.(svg|mp4|html)$/.test(f) ? new Response(Bun.file(new URL(`./media/${f}`, import.meta.url))) : new Response("not found", { status: 404 });
      },
      // the sandboxed site embed has origin null, so its fonts need CORS
      "/media/fonts/:file": (req: Bun.BunRequest<"/media/fonts/:file">) => {
        const f = req.params.file;
        if (!/^geist-(sans|mono)\.woff2$/.test(f)) return new Response("not found", { status: 404 });
        return new Response(Bun.file(new URL(`./media/fonts/${f}`, import.meta.url)), { headers: { "access-control-allow-origin": "*" } });
      },
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
