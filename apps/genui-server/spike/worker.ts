// P0 spike: Worker routes to one Durable Object per board; the DO validates a spec,
// logs ops (seq, actor, cause, patch, inverse) in DO SQLite and streams AG-UI events over WebSocket.
import { DurableObject } from "cloudflare:workers";
import { applyPatch, event, opRow, SNAPSHOT_EVERY, spec, type GenuiEvent, type PatchOp, type Spec } from "@crewship/genui-spec";
import page from "./page.html";

const EMPTY: Spec = { root: "", elements: {}, style: {}, links: [] };
let ctorCount = 0; // survives only while the isolate lives; a change means the DO was rebuilt

export class Board extends DurableObject {
  doc: Spec = EMPTY;
  seq = 0;
  generation = ++ctorCount;

  constructor(ctx: DurableObjectState, env: unknown) {
    super(ctx, env);
    // DO SQLite calls are synchronous, so the replay finishes before any request runs.
    // In-DO timers stay frozen during sync work, so wake time is measured by the client (measure.ts).
    const sql = ctx.storage.sql;
    sql.exec("CREATE TABLE IF NOT EXISTS ops(seq INTEGER PRIMARY KEY, actor TEXT, cause INTEGER, patch TEXT, inverse TEXT, at REAL)");
    sql.exec("CREATE TABLE IF NOT EXISTS snap(seq INTEGER PRIMARY KEY, doc TEXT)");
    const s = sql.exec<{ seq: number; doc: string }>("SELECT seq, doc FROM snap ORDER BY seq DESC LIMIT 1").toArray()[0];
    if (s) { this.doc = JSON.parse(s.doc); this.seq = s.seq; }
    for (const r of sql.exec<{ seq: number; patch: string }>("SELECT seq, patch FROM ops WHERE seq > ? ORDER BY seq", this.seq)) {
      this.doc = applyPatch(this.doc, JSON.parse(r.patch)); this.seq = r.seq;
    }
  }

  async fetch(req: Request): Promise<Response> {
    const url = new URL(req.url);
    if (url.pathname === "/ws") {
      const [client, server] = Object.values(new WebSocketPair());
      this.ctx.acceptWebSocket(server); // hibernation API: socket survives DO eviction
      this.send(server, { type: "STATE_SNAPSHOT", snapshot: this.doc, seq: this.seq });
      return new Response(null, { status: 101, webSocket: client });
    }
    if (url.pathname === "/stats") {
      return Response.json({ generation: this.generation, seq: this.seq, sockets: this.ctx.getWebSockets().length });
    }
    // shortcut: no auth on /emit; local `wrangler dev` only. P6 adds the CF Access / tailnet identity adapter.
    if (url.pathname === "/emit" && req.method === "POST") return this.emit(await req.json().catch(() => null), req.headers.get("x-actor") ?? "agent:spike");
    return new Response("not found", { status: 404 });
  }

  // One agent tool call (emit_view) -> one spec -> progressive STATE_DELTA events.
  // shortcut: two emits at once interleave their ops; P2 queues runs per board.
  async emit(raw: unknown, actor: string): Promise<Response> {
    const parsed = spec.safeParse(raw);
    if (!parsed.success) return Response.json({ error: parsed.error.issues }, { status: 400 });
    const next = parsed.data;
    const prev = this.doc;
    const runId = crypto.randomUUID();
    this.broadcast({ type: "RUN_STARTED", threadId: "board", runId });
    const ops: PatchOp[] = [{ op: "replace", path: "", value: { ...next, elements: {} } }];
    const ptr = (id: string) => `/elements/${id.replace(/~/g, "~0").replace(/\//g, "~1")}`; // RFC 6901 escape
    for (const [id, e] of Object.entries(next.elements)) ops.push({ op: "add", path: ptr(id), value: e });
    const firstSeq = this.seq + 1;
    for (const [i, op] of ops.entries()) {
      const inverse: PatchOp[] = i === 0 ? [{ op: "replace", path: "", value: prev }] : [{ op: "remove", path: op.path }];
      this.commit(actor, i === 0 ? null : firstSeq, [op], inverse);
      if (i) await scheduler.wait(70); // visible streaming
    }
    this.broadcast({ type: "RUN_FINISHED", threadId: "board", runId });
    return Response.json({ ok: true, seq: this.seq, ops: ops.length });
  }

  commit(actor: string, cause: number | null, patch: PatchOp[], inverse: PatchOp[]) {
    const seq = this.seq + 1;
    const row = opRow.parse({ seq, actor, cause, patch, inverse, at: Date.now() });
    const doc = applyPatch(this.doc, patch); // apply first: a patch that throws never reaches the log
    this.ctx.storage.sql.exec("INSERT INTO ops VALUES(?,?,?,?,?,?)", seq, actor, cause, JSON.stringify(patch), JSON.stringify(inverse), row.at);
    this.doc = doc; this.seq = seq;
    if (seq % SNAPSHOT_EVERY === 0) this.ctx.storage.sql.exec("INSERT INTO snap VALUES(?,?)", seq, JSON.stringify(this.doc));
    this.broadcast({ type: "STATE_DELTA", delta: patch, seq });
  }

  send(ws: WebSocket, ev: GenuiEvent) { ws.send(JSON.stringify(event.parse(ev))); }
  broadcast(ev: GenuiEvent) { for (const ws of this.ctx.getWebSockets()) this.send(ws, ev); }

  webSocketMessage(_ws: WebSocket, msg: string | ArrayBuffer) {
    let raw: unknown;
    try { raw = JSON.parse(String(msg)); } catch { return; }
    const p = event.safeParse(raw);
    if (p.success && p.data.type === "CUSTOM") console.log("intent", JSON.stringify(p.data.value));
  }
  webSocketClose(ws: WebSocket, code: number) { ws.close(code === 1005 || code === 1006 ? 1000 : code); } // reserved codes cannot be sent
}

export default {
  async fetch(req: Request, env: { BOARD: DurableObjectNamespace }): Promise<Response> {
    const url = new URL(req.url);
    if (url.pathname === "/") return new Response(page, { headers: { "content-type": "text/html; charset=utf-8" } });
    return env.BOARD.get(env.BOARD.idFromName("main")).fetch(req);
  },
};
