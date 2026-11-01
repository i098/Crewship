import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { rmSync } from "node:fs";
import { tmpdir } from "node:os";
import type { Op, ServerMsg, BoardSpec } from "@crewship/genui-spec";
import { applyPatch, Board, safeStyle } from "../src/model";

const op = (seq: number, actor: Op["actor"], patch: Op["patch"]): ServerMsg => ({ t: "ops", ops: [{ seq, actor, cause: "t", patch, inverse: [] }] });
const agentMove = (seq: number, x: number): ServerMsg => op(seq, "agent", [{ op: "add", path: "/components/p1/rect", value: { x, y: 0, w: 300, h: 200 } }]);

/** A header and two cards: the least a board needs for the move rule. */
const seed = (): BoardSpec => ({
  components: {
    header: { type: "header", props: { wins: "agent" } },
    p1: { type: "card", props: { kind: "pipeline", title: "p1" } },
    k1: { type: "card", props: { kind: "crew", title: "k1" } },
  },
  links: [],
  tokens: {},
});

function boardWith(spec: BoardSpec = seed()) {
  const b = new Board();
  b.receive({ t: "snapshot", seq: 1, spec });
  return b;
}

describe("patch", () => {
  test("add, replace and remove apply to objects and arrays without touching the input", () => {
    const doc: Record<string, unknown> = { a: { b: 1 }, list: [1, 2, 3] };
    const patch = [
      { op: "add", path: "/a/c", value: 2 },
      { op: "replace", path: "/a/b", value: 9 },
      { op: "remove", path: "/list/0" },
      { op: "add", path: "/list/-", value: 4 },
    ] as const;
    expect(applyPatch(doc, [...patch])).toEqual({ a: { b: 9, c: 2 }, list: [2, 3, 4] });
    expect(doc).toEqual({ a: { b: 1 }, list: [1, 2, 3] });
  });

  test("a path that does not resolve throws", () => {
    expect(() => applyPatch({}, [{ op: "replace", path: "/x", value: 1 }])).toThrow();
    expect(() => applyPatch({}, [{ op: "add", path: "/x/y", value: 1 }])).toThrow();
  });
});

describe("move rule", () => {
  test("agent wins: an agent move drops the user's pending move", () => {
    const b = boardWith();
    b.propose("move", "p1", { x: 500, y: 500 });
    expect(b.view().components.p1.rect?.x).toBe(500);
    b.receive(agentMove(2, 7));
    expect(b.view().components.p1.rect?.x).toBe(7);
  });

  test("user wins, or a pinned card: the user's pending move stays on top", () => {
    for (const patch of [{ op: "add", path: "/components/header/props/wins", value: "user" }, { op: "add", path: "/components/p1/props/pinned", value: true }] as const) {
      const b = boardWith(applyPatch(seed(), [patch]));
      b.propose("move", "p1", { x: 500, y: 500 });
      b.receive(agentMove(2, 7));
      expect(b.view().components.p1.rect?.x).toBe(500);
    }
  });

  test("an error drops the pending intent; an old seq is ignored", () => {
    const b = boardWith();
    const i = b.propose("resize", "p1", { w: 10, h: 10 });
    expect(b.view().components.p1.rect).toMatchObject({ w: 160, h: 96 });
    expect(b.receive({ t: "error", id: i.id, msg: "no" })).toBe("no");
    expect(b.view().components.p1.rect).toBeUndefined();
    b.receive(agentMove(1, 7));
    expect(b.seq).toBe(1);
  });
});

test("style keeps HSL tokens and drops other colours, URLs and bad keys", () => {
  expect(safeStyle({ accent: "hsl(10 50% 50%)", a: "#fff", b: "rgb(0 0 0)", c: "url(x)", d: "red;x:y", "Bad Key": "1px", radius: "4px" })).toEqual({
    accent: "hsl(10 50% 50%)",
    radius: "4px",
  });
});

// The contract runs against the real genui-server (Worker plus BoardDO) under `wrangler dev --local`.
describe("genui-server contract", () => {
  const port = 18000 + Math.floor(Math.random() * 2000);
  const base = `http://127.0.0.1:${port}`;
  const persist = `${tmpdir()}/genui-test-${port}`;
  let server: Bun.Subprocess | undefined;

  beforeAll(async () => {
    server = Bun.spawn(["bunx", "wrangler", "dev", "--local", "--port", String(port), "--persist-to", persist], {
      cwd: new URL("../../genui-server/", import.meta.url).pathname, stdout: "ignore", stderr: "ignore",
    });
    // wrangler prints no machine-readable ready signal, so poll its port until the Worker answers
    for (let i = 0; i < 120; i++) {
      if (await fetch(`${base}/agent/up`).then((r) => r.status === 405, () => false)) return;
      await Bun.sleep(500);
    }
    throw new Error("genui-server did not start");
  }, 70_000);
  afterAll(async () => {
    server?.kill();
    await server?.exited;
    rmSync(persist, { recursive: true, force: true });
  });

  const agent = async (boardId: string, tool: string, args: Record<string, unknown>) =>
    (await fetch(`${base}/agent/${boardId}`, { method: "POST", body: JSON.stringify({ tool, args }) })).json();

  async function open() {
    const boardId = `t-${crypto.randomUUID()}`;
    await agent(boardId, "emit_view", { spec: seed() });
    const ws = new WebSocket(`ws://127.0.0.1:${port}/ws/${boardId}`);
    const inbox: ServerMsg[] = [];
    let wake = () => {};
    ws.onmessage = (e) => (inbox.push(JSON.parse(String(e.data))), wake());
    const opened = Promise.withResolvers<void>();
    ws.onopen = () => opened.resolve();
    await opened.promise;
    // Waits for the next message of type `t`; the test timeout catches one that never comes.
    const next = async (t: ServerMsg["t"]) => {
      for (;;) {
        const k = inbox.findIndex((m) => m.t === t);
        if (k >= 0) return inbox.splice(k, 1)[0];
        const arrived = Promise.withResolvers<void>();
        wake = arrived.resolve;
        await arrived.promise;
      }
    };
    await next("snapshot"); // the server sends one on connect
    return { ws, next, boardId };
  }

  test("hello, intent, agent call and undo round trip", async () => {
    const { ws, next, boardId } = await open();
    ws.send(JSON.stringify({ t: "hello", boardId, clientId: "c" }));
    const snap = await next("snapshot");
    expect(snap.t === "snapshot" && snap.spec.components.header.props.wins).toBe("agent");

    ws.send(JSON.stringify({ t: "intent", id: "i1", kind: "move", targetId: "p1", payload: { x: 5, y: 6 } }));
    const moved = await next("ops");
    expect(moved.t === "ops" && moved.ops[0]).toMatchObject({ seq: 2, actor: "user", patch: [{ value: { x: 5, y: 6 } }] });
    expect(await next("ack")).toEqual({ t: "ack", id: "i1", seq: 2 });

    // Agent wins by default, so the agent may move a card the user placed.
    expect(await agent(boardId, "emit_view", { patch: [{ op: "add", path: "/components/p1/rect", value: { x: 1, y: 1, w: 200, h: 200 } }] })).toEqual({ seq: 3 });
    const byAgent = await next("ops");
    expect(byAgent.t === "ops" && byAgent.ops[0].actor).toBe("agent");

    ws.send(JSON.stringify({ t: "intent", id: "bad", kind: "move", targetId: "nope", payload: {} }));
    expect(await next("error")).toMatchObject({ id: "bad" });

    ws.send(JSON.stringify({ t: "undo" }));
    const undo = await next("ops");
    expect(undo.t === "ops" && undo.ops[0]).toMatchObject({ actor: "user", cause: "undo:2" });
    ws.close();
  }, 15_000);

  test("user wins: the server keeps the user's placement against the agent", async () => {
    const { ws, next, boardId } = await open();
    ws.send(JSON.stringify({ t: "intent", id: "w", kind: "input", targetId: "header", payload: { field: "wins", value: "user" } }));
    ws.send(JSON.stringify({ t: "intent", id: "m", kind: "move", targetId: "p1", payload: { x: 5, y: 6, w: 300, h: 200 } }));
    await next("ack");
    await next("ack");
    await agent(boardId, "emit_view", { patch: [{ op: "add", path: "/components/p1/rect", value: { x: 1, y: 1, w: 200, h: 200 } }] });
    ws.send(JSON.stringify({ t: "hello", boardId, clientId: "c" }));
    const snap = await next("snapshot");
    expect(snap.t === "snapshot" && snap.spec.components.p1.rect).toMatchObject({ x: 5, y: 6 });
    ws.close();
  }, 15_000);
});
