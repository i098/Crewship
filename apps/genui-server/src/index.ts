import { resolveIdentity } from "./identity";
export { BoardDO } from "./board-do";
import type { BoardDO } from "./board-do";

export interface Env {
  BOARD: DurableObjectNamespace<BoardDO>;
  GENUI_AGENT_TOKEN?: string;
}

const route = /^\/(ws|agent)\/([A-Za-z0-9_-]{1,64})$/;

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const m = route.exec(url.pathname);
    if (!m) return new Response("not found", { status: 404 });
    const [, kind, boardId] = m;
    if (kind === "ws" && req.headers.get("upgrade") !== "websocket") return new Response("expected websocket", { status: 426 });
    if (kind === "agent" && req.method !== "POST") return new Response("method not allowed", { status: 405 });
    const role = kind === "agent" || url.searchParams.get("role") === "agent" ? "agent" : "user";
    if (!resolveIdentity(req, env, role)) return new Response("unauthorized", { status: 401 });
    return env.BOARD.get(env.BOARD.idFromName(boardId)).fetch(req);
  },
};
