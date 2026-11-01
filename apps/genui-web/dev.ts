// Local run on real data: genui-server (wrangler dev --local), the feeder, and this page server.
// The page server serves the canvas and passes /ws/:boardId through to genui-server, so the page keeps one origin.
// Run: bun dev.ts  (PORT defaults to 4610, the board server to 8787)
import type { ServerWebSocket } from "bun";
import page from "./index.html";

const PORT = Number(process.env.PORT ?? 4610);
const UPSTREAM = process.env.GENUI_SERVER ?? "http://127.0.0.1:8787";
// Behind `tailscale serve`, only these Tailscale logins may open a board socket; unset means no check (local dev).
const ALLOW = process.env.GENUI_ALLOW_LOGINS?.split(",").filter(Boolean);

type Pipe = { boardId: string; up?: WebSocket; queue: string[] };

export function start(port = PORT) {
  return Bun.serve<Pipe>({
    hostname: "127.0.0.1", // a dev server: never listen beyond this host
    port,
    routes: { "/": page },
    fetch(req, server) {
      const m = /^\/ws\/([A-Za-z0-9_-]{1,64})$/.exec(new URL(req.url).pathname);
      if (m && ALLOW && !ALLOW.includes(req.headers.get("tailscale-user-login") ?? "")) {
        console.error(`refused /ws/${m[1]}: tailscale login "${req.headers.get("tailscale-user-login") ?? ""}"`);
        return new Response("forbidden", { status: 403 });
      }
      if (m && server.upgrade(req, { data: { boardId: m[1], queue: [] } })) return;
      return new Response("not found", { status: 404 });
    },
    websocket: {
      open(ws: ServerWebSocket<Pipe>) {
        const up = new WebSocket(`${UPSTREAM.replace(/^http/, "ws")}/ws/${ws.data.boardId}`);
        ws.data.up = up;
        up.onopen = () => { for (const m of ws.data.queue.splice(0)) up.send(m); };
        up.onmessage = (e) => ws.send(String(e.data));
        up.onclose = () => ws.close();
      },
      message(ws, raw) {
        const up = ws.data.up;
        if (up?.readyState === WebSocket.OPEN) up.send(String(raw));
        else ws.data.queue.push(String(raw));
      },
      close(ws) {
        ws.data.up?.close();
      },
    },
  });
}

if (import.meta.main) {
  const kids = [
    // GENUI_STATE moves the board's storage (e.g. to /dev/shm): on a disk under heavy write load every board write waits
    // on fsync, and the page then waits minutes for its first snapshot. The feeder rebuilds the board if it is lost.
    Bun.spawn(["bunx", "wrangler", "dev", "--local", "--port", new URL(UPSTREAM).port || "8787", ...(process.env.GENUI_STATE ? ["--persist-to", process.env.GENUI_STATE] : [])], { cwd: new URL("../genui-server/", import.meta.url).pathname, stdout: "inherit", stderr: "inherit" }),
    Bun.spawn(["bun", "feeder/feeder.ts"], { cwd: import.meta.dir, stdout: "inherit", stderr: "inherit", env: { ...process.env, GENUI_SERVER: UPSTREAM } }),
  ];
  for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { for (const k of kids) k.kill(); process.exit(0); });
  console.log(`genui-web on ${start().url} (board server ${UPSTREAM})`);
}
