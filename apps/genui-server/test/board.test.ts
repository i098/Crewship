import { expect, test } from "bun:test";
import { Board, SNAPSHOT_EVERY } from "../src/board";
import { applyPatch } from "../src/patch";
import { MemoryStore } from "../src/store";

const card = { type: "card", props: { t: 1 }, rect: { x: 0, y: 0, w: 10, h: 10 } };
const seed = (b: Board) => b.agent({ tool: "emit_view", args: { patch: [{ op: "add", path: "/components/a", value: card }, { op: "add", path: "/components/b", value: { type: "card", props: {} } }] } });
const move = (id: string, x: number, baseSeq?: number) => ({ t: "intent" as const, id: `i${x}`, kind: "move" as const, targetId: id, payload: { x, y: 5 }, baseSeq });

test("patch inverse round-trips add/replace/remove on objects and arrays", () => {
  const s = { components: {}, links: [{ from: "a", to: "b" }], tokens: { c: 1 } };
  const patch = [
    { op: "add", path: "/links/0", value: { from: "x", to: "y" } },
    { op: "replace", path: "/tokens/c", value: 2 },
    { op: "add", path: "/tokens/d", value: 3 },
    { op: "remove", path: "/links/1" },
  ] as const;
  const r = applyPatch(s, [...patch]);
  expect(r.spec.links).toEqual([{ from: "x", to: "y" }]);
  expect(applyPatch(r.spec, r.inverse).spec).toEqual(s);
});

test("bad patch is rejected and leaves the log untouched", () => {
  const store = new MemoryStore();
  const b = new Board(store);
  expect(() => b.agent({ tool: "emit_view", args: { patch: [{ op: "remove", path: "/components/zzz" }] } })).toThrow();
  expect(b.seq).toBe(0);
  expect(store.ops).toHaveLength(0);
});

test("emit_view accepts the kit's AG-UI STATE_SNAPSHOT event", () => {
  const b = new Board(new MemoryStore());
  b.agent({ tool: "emit_view", args: { event: { type: "STATE_SNAPSHOT", snapshot: { components: { a: card } } } } });
  expect(b.spec).toEqual({ components: { a: card }, links: [], tokens: {} });
});

test("seq is dense and every op stores patch and inverse", () => {
  const b = new Board(new MemoryStore());
  const ops = [...seed(b), ...b.agent({ tool: "link", args: { from: "a", to: "b" } })];
  expect(ops.map((o) => o.seq)).toEqual([1, 2]);
  expect(ops[1].inverse).toEqual([{ op: "remove", path: "/links/0" }]);
});

test("snapshot every 100 ops; reload equals live state", () => {
  const store = new MemoryStore();
  const b = new Board(store);
  seed(b);
  for (let i = b.seq; i < SNAPSHOT_EVERY + 5; i++) b.agent({ tool: "set_style", args: { id: "a", tokens: { n: i } } });
  expect(store.snaps.map((s) => s.seq)).toEqual([100]);
  const again = new Board(store);
  expect(again.seq).toBe(b.seq);
  expect(again.spec).toEqual(b.spec);
});

test("reload replays only ops after the snapshot", () => {
  const store = new MemoryStore();
  const b = new Board(store);
  seed(b);
  for (let i = 0; i < 100; i++) b.agent({ tool: "set_style", args: { id: "a", tokens: { n: i } } });
  store.ops = store.ops.filter((o) => o.seq > 100); // pre-snapshot ops gone: snapshot must carry them
  const again = new Board(store);
  expect(again.spec).toEqual(b.spec);
});

test("agent set_style / pin / link / reset tools", () => {
  const b = new Board(new MemoryStore());
  seed(b);
  b.agent({ tool: "set_style", args: { tokens: { accent: "hsl(1 2% 3%)" } } });
  b.agent({ tool: "pin", args: { id: "b" } });
  expect(b.spec.tokens.accent).toBe("hsl(1 2% 3%)");
  expect(b.spec.components.b.props.pinned).toBe(true);
  b.intent(move("a", 50));
  b.agent({ tool: "reset", args: { id: "a" } });
  expect(b.spec.components.a.rect).toBeUndefined();
});

test("undo reverts the latest user op", () => {
  const b = new Board(new MemoryStore());
  seed(b);
  b.intent(move("a", 50));
  expect(b.spec.components.a.rect!.x).toBe(50);
  const ops = b.undo();
  expect(ops[0].cause).toBe("undo:2");
  expect(b.spec.components.a.rect!.x).toBe(0);
  expect(() => b.undo()).toThrow("nothing to undo");
});

test("undo also reverts agent ops that name the user op as cause, in reverse order", () => {
  const b = new Board(new MemoryStore());
  seed(b);
  b.intent(move("a", 50)); // cause "i50"
  b.agent({ tool: "set_style", args: { id: "b", tokens: { z: 1 }, cause: "i50" } });
  b.agent({ tool: "pin", args: { id: "b", cause: "unrelated" } });
  const ops = b.undo();
  expect(ops.map((o) => o.cause)).toEqual(["undo:3", "undo:2"]);
  expect(b.spec.components.a.rect!.x).toBe(0);
  expect(b.spec.components.b.style).toBeUndefined();
  expect(b.spec.components.b.props.pinned).toBe(true); // unrelated op stays
});

test("undo state survives reload", () => {
  const store = new MemoryStore();
  const b = new Board(store);
  seed(b);
  b.intent(move("a", 50));
  b.undo();
  expect(() => new Board(store).undo()).toThrow("nothing to undo");
});

test("agent wins: stale user move is rejected, fresh one applies", () => {
  const b = new Board(new MemoryStore());
  seed(b);
  const stale = b.seq;
  b.agent({ tool: "emit_view", args: { patch: [{ op: "replace", path: "/components/a/rect", value: { x: 9, y: 9, w: 1, h: 1 } }] } });
  expect(() => b.intent(move("a", 50, stale))).toThrow("agent wins");
  expect(b.spec.components.a.rect!.x).toBe(9);
  expect(b.intent(move("a", 50, b.seq))).toHaveLength(1);
  expect(b.spec.components.a.rect!.x).toBe(50);
});

test("user wins: user move conflicts apply, agent rect patches are dropped until reset", () => {
  const b = new Board(new MemoryStore());
  seed(b);
  b.agent({ tool: "emit_view", args: { patch: [{ op: "add", path: "/components/header", value: { type: "header", props: { wins: "agent" } } }] } });
  b.intent({ t: "intent", id: "w", kind: "input", targetId: "header", payload: { field: "wins", value: "user" } });
  const stale = b.seq;
  b.agent({ tool: "emit_view", args: { patch: [{ op: "replace", path: "/components/a/rect", value: { x: 9, y: 9, w: 1, h: 1 } }] } });
  b.intent(move("a", 50, stale)); // not rejected under user wins
  const before = b.seq;
  expect(b.agent({ tool: "emit_view", args: { patch: [{ op: "replace", path: "/components/a/rect", value: { x: 1, y: 1, w: 1, h: 1 } }] } })).toEqual([]);
  expect(b.seq).toBe(before);
  b.agent({ tool: "reset", args: { id: "a", rect: { x: 1, y: 1, w: 1, h: 1 } } });
  expect(b.spec.components.a.rect!.x).toBe(1);
  b.agent({ tool: "emit_view", args: { patch: [{ op: "replace", path: "/components/a/rect", value: { x: 2, y: 2, w: 1, h: 1 } }] } });
  expect(b.spec.components.a.rect!.x).toBe(2);
});

test("header.props.wins toggle persists in the spec across reload; default is agent", () => {
  const store = new MemoryStore();
  const b = new Board(store);
  seed(b);
  expect(b.moveWins).toBe("agent");
  b.agent({ tool: "emit_view", args: { patch: [{ op: "add", path: "/components/header", value: { type: "header", props: {} } }] } });
  b.intent({ t: "intent", id: "w", kind: "input", targetId: "header", payload: { field: "wins", value: "user" } });
  expect(new Board(store).moveWins).toBe("user");
});

test("pinned card keeps its placement against agent rect patches; reset overrides", () => {
  const b = new Board(new MemoryStore());
  seed(b);
  b.agent({ tool: "pin", args: { id: "a" } });
  const before = b.seq;
  expect(b.agent({ tool: "emit_view", args: { patch: [{ op: "replace", path: "/components/a/rect", value: { x: 9, y: 9, w: 1, h: 1 } }] } })).toEqual([]);
  expect(b.seq).toBe(before);
  b.agent({ tool: "reset", args: { id: "a", rect: { x: 3, y: 3, w: 1, h: 1 } } });
  expect(b.spec.components.a.rect!.x).toBe(3);
});

test("user intents: bad target and bad payload throw; z rewinds an ask together with the agent's reply", () => {
  const b = new Board(new MemoryStore());
  seed(b);
  expect(() => b.intent(move("nope", 1))).toThrow("no such component");
  expect(() => b.intent({ t: "intent", id: "x", kind: "move", targetId: "a", payload: { x: "1" } })).toThrow();
  expect(b.intent({ t: "intent", id: "y", kind: "input", targetId: "a", payload: { text: "open host stats" } })[0]).toMatchObject({ actor: "user", cause: "y", patch: [] });
  b.agent({ tool: "emit_view", args: { cause: "y", patch: [{ op: "add", path: "/components/sys", value: { type: "card", props: {} } }] } });
  b.undo();
  expect(b.spec.components.sys).toBeUndefined();
  expect(b.spec.components.a).toBeDefined();
});

test("__proto__ paths and targets never touch Object.prototype", () => {
  const b = new Board(new MemoryStore());
  seed(b);
  expect(() => b.intent({ t: "intent", id: "p", kind: "pin", targetId: "__proto__", payload: {} })).toThrow();
  expect(() => b.agent({ tool: "emit_view", args: { patch: [{ op: "add", path: "/components/__proto__/props", value: { polluted: 1 } }] } })).toThrow();
  expect(() => b.agent({ tool: "emit_view", args: { patch: [{ op: "add", path: "/components/constructor/prototype/polluted", value: 1 }] } })).toThrow();
  expect(({} as Record<string, unknown>).props).toBeUndefined();
  expect(({} as Record<string, unknown>).polluted).toBeUndefined();
});

test("agent whole-component and whole-map writes keep a pinned card's rect and pin", () => {
  const b = new Board(new MemoryStore());
  seed(b);
  b.agent({ tool: "pin", args: { id: "a" } });
  b.agent({ tool: "emit_view", args: { patch: [{ op: "add", path: "/components/a", value: { type: "card", props: { t: 2 } } }] } });
  expect(b.spec.components.a).toMatchObject({ props: { t: 2, pinned: true }, rect: card.rect });
  b.agent({ tool: "emit_view", args: { event: { snapshot: { components: { a: { type: "card", props: {} } } } } } });
  expect(b.spec.components.a).toMatchObject({ props: { pinned: true }, rect: card.rect });
  b.agent({ tool: "pin", args: { id: "a", pinned: false } });
  expect(b.spec.components.a.props.pinned).toBe(false);
});
