import { DurableObject } from "cloudflare:workers";
import { Board } from "./board";
import type { AgentCall, ClientMsg, Op, ServerMsg, Spec } from "./contract";
import type { Store } from "./store";

class SqlStore implements Store {
  constructor(private sql: SqlStorage) {
    sql.exec(`CREATE TABLE IF NOT EXISTS ops (seq INTEGER PRIMARY KEY, actor TEXT NOT NULL, cause TEXT NOT NULL, patch TEXT NOT NULL, inverse TEXT NOT NULL)`);
    sql.exec(`CREATE TABLE IF NOT EXISTS snapshots (seq INTEGER PRIMARY KEY, spec TEXT NOT NULL)`);
  }
  append(o: Op) {
    this.sql.exec(`INSERT INTO ops VALUES (?,?,?,?,?)`, o.seq, o.actor, o.cause, JSON.stringify(o.patch), JSON.stringify(o.inverse));
  }
  opsAfter(after: number): Op[] {
    return this.sql.exec(`SELECT * FROM ops WHERE seq > ? ORDER BY seq`, after).toArray().map((r) => ({
      seq: r.seq as number, actor: r.actor as Op["actor"], cause: r.cause as string,
      patch: JSON.parse(r.patch as string), inverse: JSON.parse(r.inverse as string),
    }));
  }
  latestSnapshot() {
    const r = this.sql.exec(`SELECT seq, spec FROM snapshots ORDER BY seq DESC LIMIT 1`).toArray()[0];
    return r ? { seq: r.seq as number, spec: JSON.parse(r.spec as string) as Spec } : null;
  }
  saveSnapshot(seq: number, spec: Spec) { this.sql.exec(`INSERT OR REPLACE INTO snapshots VALUES (?,?)`, seq, JSON.stringify(spec)); }
}

/** One Durable Object per board. Hibernating WebSockets; socket role lives in the attachment. */
export class BoardDO extends DurableObject {
  private board: Board;

  constructor(ctx: DurableObjectState, env: unknown) {
    super(ctx, env);
    this.board = new Board(new SqlStore(ctx.storage.sql));
  }

  async fetch(req: Request): Promise<Response> {
    if (req.headers.get("upgrade") === "websocket") {
      const pair = new WebSocketPair();
      const role = new URL(req.url).searchParams.get("role") === "agent" ? "agent" : "user";
      this.ctx.acceptWebSocket(pair[1]);
      pair[1].serializeAttachment({ role });
      this.send(pair[1], this.snapshotMsg());
      return new Response(null, { status: 101, webSocket: pair[0] });
    }
    try {
      const call = (await req.json()) as AgentCall;
      const ops = this.board.agent(call);
      this.broadcast(ops);
      return Response.json({ seq: this.board.seq });
    } catch (e) {
      return Response.json({ error: (e as Error).message }, { status: 400 });
    }
  }

  webSocketMessage(ws: WebSocket, data: string | ArrayBuffer) {
    let m: ClientMsg;
    let id = "";
    try {
      m = JSON.parse(typeof data === "string" ? data : new TextDecoder().decode(data));
      switch (m.t) {
        case "hello": return this.send(ws, this.snapshotMsg());
        case "undo": return this.broadcast(this.board.undo());
        case "intent": {
          id = m.id;
          const ops = this.board.intent(m);
          this.broadcast(ops);
          this.send(ws, { t: "ack", id, seq: this.board.seq });
          const fwd: ServerMsg = { t: "intent", id, kind: m.kind, targetId: m.targetId, payload: m.payload };
          for (const s of this.ctx.getWebSockets()) if (s.deserializeAttachment()?.role === "agent") this.send(s, fwd);
          return;
        }
        default: throw new Error("unknown message");
      }
    } catch (e) {
      this.send(ws, { t: "error", id, msg: (e as Error).message });
    }
  }

  private snapshotMsg(): ServerMsg { return { t: "snapshot", seq: this.board.seq, spec: this.board.spec }; }
  private send(ws: WebSocket, m: ServerMsg) { ws.send(JSON.stringify(m)); }
  private broadcast(ops: Op[]) { if (ops.length) this.broadcastAll({ t: "ops", ops }); }
  private broadcastAll(m: ServerMsg) { for (const s of this.ctx.getWebSockets()) this.send(s, m); }
}
