import { afterAll, describe, expect, test } from "bun:test";
import type { Op, ServerMsg, Spec } from "../src/contract";
import { applyPatch, Board, filterAgentPatch, invertPatch, safeStyle } from "../src/model";
import { seedSpec, start } from "../mock/server";

const op = (seq: number, actor: Op["actor"], patch: Op["patch"]): ServerMsg => ({ t: "ops", ops: [{ seq, actor, cause: "t", patch, inverse: [] }] });
const agentMove = (seq: number, x: number): ServerMsg => op(seq, "agent", [{ op: "add", path: "/components/feed/rect", value: { x, y: 0, w: 300, h: 200 } }]);

function boardWith(spec: Spec = seedSpec()) {
  const b = new Board();
  b.receive({ t: "snapshot", seq: 1, spec });
  return b;
}

describe("patch", () => {
  test("invert undoes add, replace and remove, on objects and arrays", () => {
    const doc: Record<string, unknown> = { a: { b: 1 }, list: [1, 2, 3] };
    const patch = [
      { op: "add", path: "/a/c", value: 2 },
      { op: "replace", path: "/a/b", value: 9 },
      { op: "remove", path: "/list/0" },
      { op: "add", path: "/list/-", value: 4 },
    ] as const;
    const after = applyPatch(doc, [...patch]);
    expect(after).toEqual({ a: { b: 9, c: 2 }, list: [2, 3, 4] });
    expect(applyPatch(after, invertPatch(doc, [...patch]))).toEqual(doc);
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
    b.propose("move", "feed", { x: 500, y: 500 });
    expect(b.view().components.feed.rect?.x).toBe(500);
    b.receive(agentMove(2, 7));
    expect(b.view().components.feed.rect?.x).toBe(7);
  });

  test("user wins, or a pinned card: the user's pending move stays on top", () => {
    for (const patch of [{ op: "add", path: "/components/header/props/wins", value: "user" }, { op: "add", path: "/components/feed/props/pinned", value: true }] as const) {
      const b = boardWith(applyPatch(seedSpec(), [patch]));
      b.propose("move", "feed", { x: 500, y: 500 });
      b.receive(agentMove(2, 7));
      expect(b.view().components.feed.rect?.x).toBe(500);
    }
  });

  test("an error drops the pending intent; an old seq is ignored", () => {
    const b = boardWith();
    const i = b.propose("resize", "feed", { w: 10, h: 10 });
    expect(b.view().components.feed.rect).toMatchObject({ w: 160, h: 96 });
    expect(b.receive({ t: "error", id: i.id, msg: "no" })).toBe("no");
    expect(b.view().components.feed.rect?.w).toBe(460);
    b.receive(agentMove(1, 7));
    expect(b.seq).toBe(1);
  });

  test("the server drops agent rect changes on pinned cards, and on placed cards while the user wins", () => {
    const spec = applyPatch(seedSpec(), [{ op: "add", path: "/components/header/props/wins", value: "user" }]);
    const patch = [
      { op: "add" as const, path: "/components/feed/rect", value: {} },
      { op: "add" as const, path: "/components/feed/props/title", value: "t" },
      { op: "add" as const, path: "/components/cpu/rect", value: {} },
    ];
    expect(filterAgentPatch(spec, patch, new Set(["feed"])).map((o) => o.path)).toEqual(["/components/feed/props/title", "/components/cpu/rect"]);
    expect(filterAgentPatch(seedSpec(), patch, new Set(["feed"]))).toHaveLength(3);
    const pinned = applyPatch(seedSpec(), [{ op: "add", path: "/components/cpu/props/pinned", value: true }]);
    expect(filterAgentPatch(pinned, patch, new Set()).map((o) => o.path)).toEqual(["/components/feed/rect", "/components/feed/props/title"]);
  });
});

test("style keeps HSL tokens and drops other colours, URLs and bad keys", () => {
  expect(safeStyle({ accent: "hsl(10 50% 50%)", a: "#fff", b: "rgb(0 0 0)", c: "url(x)", d: "red;x:y", "Bad Key": "1px", radius: "4px" })).toEqual({
    accent: "hsl(10 50% 50%)",
    radius: "4px",
  });
});

describe("mock server contract", () => {
  const server = start(0);
  afterAll(() => server.stop(true));

  async function open() {
    const ws = new WebSocket(`ws://${server.url.host}/ws/t-${crypto.randomUUID()}`);
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
    return { ws, next, boardId: new URL(ws.url).pathname.split("/").pop()! };
  }

  test("hello, intent, agent call and undo round trip", async () => {
    const { ws, next, boardId } = await open();
    ws.send(JSON.stringify({ t: "hello", boardId, clientId: "c" }));
    const snap = await next("snapshot");
    expect(snap.t === "snapshot" && snap.spec.components.header.props.wins).toBe("agent");

    ws.send(JSON.stringify({ t: "intent", id: "i1", kind: "move", targetId: "feed", payload: { x: 5, y: 6 } }));
    const moved = await next("ops");
    expect(moved.t === "ops" && moved.ops[0]).toMatchObject({ seq: 1, actor: "user", patch: [{ value: { x: 5, y: 6 } }] });
    expect(await next("ack")).toEqual({ t: "ack", id: "i1", seq: 1 });

    // Agent wins by default, so the agent may move a card the user placed.
    const move = { patch: [{ op: "add", path: "/components/feed/rect", value: { x: 1, y: 1, w: 200, h: 200 } }] };
    const res = await fetch(`${server.url}agent/${boardId}`, { method: "POST", body: JSON.stringify({ tool: "emit_view", args: move }) });
    expect(await res.json()).toEqual({ seq: 2 });
    const byAgent = await next("ops");
    expect(byAgent.t === "ops" && byAgent.ops[0].actor).toBe("agent");

    ws.send(JSON.stringify({ t: "intent", id: "bad", kind: "move", targetId: "nope", payload: {} }));
    expect(await next("error")).toMatchObject({ id: "bad" });

    ws.send(JSON.stringify({ t: "undo" }));
    const undo = await next("ops");
    expect(undo.t === "ops" && undo.ops[0].patch[0]).toMatchObject({ value: { x: 5, y: 6 } });
    ws.close();
  });

  test("user wins: the server keeps the user's placement against the agent", async () => {
    const { ws, next, boardId } = await open();
    ws.send(JSON.stringify({ t: "hello", boardId, clientId: "c" }));
    await next("snapshot");
    ws.send(JSON.stringify({ t: "intent", id: "w", kind: "input", targetId: "header", payload: { field: "wins", value: "user" } }));
    ws.send(JSON.stringify({ t: "intent", id: "m", kind: "move", targetId: "feed", payload: { x: 5, y: 6 } }));
    await next("ack");
    await next("ack");
    const move = { patch: [{ op: "add", path: "/components/feed/rect", value: { x: 1, y: 1, w: 200, h: 200 } }] };
    const res = await fetch(`${server.url}agent/${boardId}`, { method: "POST", body: JSON.stringify({ tool: "emit_view", args: move }) });
    expect(await res.json()).toEqual({ seq: 2 });
    ws.close();
  });
});
