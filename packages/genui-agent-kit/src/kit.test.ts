import { afterAll, beforeAll, expect, test } from "bun:test";
import { createGenuiClient } from "./client";
import { createBridge, parseStatusLine } from "./bridge";

const posts: { path: string; body: any }[] = [];
let sockets: any[] = [];
let server: ReturnType<typeof Bun.serve>;
let url: string;

beforeAll(() => {
  server = Bun.serve({
    port: 0,
    async fetch(req, srv) {
      const u = new URL(req.url);
      // Like genui-server: only ?role=agent sockets receive forwarded intents.
      if (u.pathname.startsWith("/ws/")) return u.searchParams.get("role") === "agent" && srv.upgrade(req) ? undefined : new Response("no", { status: 400 });
      if (req.method === "POST" && u.pathname.startsWith("/agent/")) {
        const body = await req.json();
        posts.push({ path: u.pathname, body });
        return Response.json({ seq: posts.length });
      }
      return new Response("nf", { status: 404 });
    },
    websocket: {
      open: (ws) => void sockets.push(ws),
      message: () => {},
    },
  });
  url = `http://localhost:${server.port}`;
});
afterAll(() => server.stop(true));

test("tools POST the contract body and return seq", async () => {
  posts.length = 0;
  const c = createGenuiClient({ url, boardId: "b 1" });
  expect(await c.link("a", "b")).toEqual({ seq: 1 });
  await c.pin("a");
  await c.setStyle("a", { color: "hsl(0 0% 50%)" });
  await c.reset();
  await c.emitView([{ op: "remove", path: "/components/a" }]);
  await c.emitView({ components: {}, links: [], tokens: {} });
  expect(posts.map((p) => p.body.tool)).toEqual(["link", "pin", "set_style", "reset", "emit_view", "emit_view"]);
  expect(posts[0].path).toBe("/agent/b%201");
  expect(posts[4].body.args.event.type).toBe("STATE_DELTA");
  expect(posts[5].body.args.event.type).toBe("STATE_SNAPSHOT");
});

test("non-2xx rejects", async () => {
  const bad = createGenuiClient({ url: `${url}/nope`, boardId: "b" });
  await expect(bad.reset()).rejects.toThrow("404");
});

test("onIntent delivers intent frames, sends hello, unsubscribes", async () => {
  sockets = [];
  const c = createGenuiClient({ url, boardId: "b", clientId: "k" });
  const got: any[] = [];
  const off = c.onIntent((i) => got.push(i));
  while (!sockets.length) await Bun.sleep(5);
  sockets[0].send(JSON.stringify({ t: "ack", id: "x", seq: 1 }));
  sockets[0].send(JSON.stringify({ t: "intent", id: "i1", kind: "move", targetId: "a", payload: { x: 1 } }));
  while (!got.length) await Bun.sleep(5);
  expect(got).toEqual([{ id: "i1", kind: "move", targetId: "a", payload: { x: 1 } }]);
  off();
  sockets[0].send(JSON.stringify({ t: "intent", id: "i2", kind: "pin", targetId: "a", payload: null }));
  await Bun.sleep(50);
  expect(got.length).toBe(1);
  c.close();
});

test("parseStatusLine", () => {
  expect(parseStatusLine("working [at=12]: building")).toEqual({ state: "working", at: 12, text: "building" });
  expect(parseStatusLine("done [at=5] [key=x]: PR https://x/1")?.text).toBe("PR https://x/1");
  expect(parseStatusLine("random text")).toBeUndefined();
  expect(parseStatusLine("done [url=https://x/1] [at=3]: ok")).toEqual({ state: "done", at: 3, text: "ok" });
});

test("parseStatusLine rejects pathological input in linear time", () => {
  const t = performance.now();
  expect(parseStatusLine(`a${" [".repeat(50000)}`)).toBeUndefined();
  expect(parseStatusLine(`a${"[x]".repeat(50000)}`)).toBeUndefined();
  expect(parseStatusLine("a [x] junk: t")).toBeUndefined();
  expect(performance.now() - t).toBeLessThan(500);
});

test("client url tolerates many trailing slashes", async () => {
  posts.length = 0;
  await createGenuiClient({ url: `${url}${"/".repeat(50000)}`, boardId: "b" }).reset();
  expect(posts.length).toBe(1);
});

test("bridge maps tail headers and lines to emit_view patches", async () => {
  posts.length = 0;
  const feed = createBridge(createGenuiClient({ url, boardId: "b" }));
  await feed("==> state/cf-genui-p4.status <==");
  await feed("working [at=9]: tests");
  await feed("noise");
  expect(posts.length).toBe(1);
  const op = posts[0].body.args.event.delta[0];
  expect(op.path).toBe("/components/task-cf-genui-p4");
  expect(op.value.props).toEqual({ task: "cf-genui-p4", state: "working", text: "tests", at: 9 });
});
