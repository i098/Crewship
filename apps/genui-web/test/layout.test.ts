import { expect, test } from "bun:test";
import { layout, type Item, type Rel } from "../src/layout";

const it = (id: string, proj: string, prio: number): Item => ({ id, proj, prio, done: false });
const items = [it("d1", "swap", 90), it("p1", "swap", 60), it("t1", "swap", 50), it("c1", "crew", 80), it("k1", "crew", 40), it("i1", "bill", 70), it("h1", "host", 10)];
const rels: Rel[] = [{ from: "d1", to: "c1", label: "blocks" }];
const desk = { W: 1280, H: 800, topH: 60, botH: 150 };
const st = { view: null, spread: false, picked: new Set<string>(), order: {} };
const fit = (id: string, w: number) => (id === "d1" ? 300 : 120) + (w < 300 ? 60 : 0);
const overlap = (a: { x: number; y: number; w: number; h: number }, b: typeof a) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

test("the top cluster sits in front; a linked cluster steps out, the rest fade behind", () => {
  const L = layout(items, rels, desk, st, fit);
  expect(L.front).toBe("swap");
  expect(L.center).toBe("d1");
  const by = Object.fromEntries(L.clusters.map((c) => [c.proj, c]));
  expect(by.swap.front && by.swap.s).toBe(1);
  expect(by.crew.far).toBe(false);
  expect(by.bill.far && by.host.far).toBe(true);
  expect(L.tiles.c1.away).toBe(true);
  expect(L.lines).toEqual([{ f: "d1", o: "c1", label: "blocks", proj: "swap", g: null }]);
});

test("cards in a cluster tile with no overlap and no gap: a row is as tall as its tallest card", () => {
  const L = layout(items, rels, desk, st, fit);
  const ids = ["d1", "p1", "t1"];
  for (const a of ids) for (const b of ids) if (a !== b) expect(overlap(L.tiles[a], L.tiles[b])).toBe(false);
  expect(L.tiles.d1.w).toBe(776); // odd count: the top card takes the full row
  expect(L.tiles.p1.h).toBe(L.tiles.t1.h);
  expect(L.tiles.p1.y).toBe(L.tiles.t1.y);
});

test("a phone stacks one column and fits it on screen", () => {
  const L = layout(items, rels, { W: 390, H: 844, topH: 110, botH: 170 }, st, fit);
  expect(new Set(["d1", "p1", "t1"].map((id) => L.tiles[id].x)).size).toBe(1);
  const front = L.clusters[0];
  expect(front.w * L.cam.k).toBeLessThanOrEqual(390);
});

test("spread puts every cluster in front and a picked card shows its cross-cluster line", () => {
  const L = layout(items, rels, desk, { ...st, spread: true, picked: new Set(["c1"]) }, fit);
  expect(L.clusters.every((c) => c.front && c.s === 1 && !c.far)).toBe(true);
  for (const a of L.clusters) for (const b of L.clusters) if (a !== b) expect(overlap(a, b)).toBe(false);
  expect(L.lines).toEqual([{ f: "c1", o: "d1", label: "blocks", proj: "swap", g: "crew" }]);
});

test("an opened cluster comes to the front; a pinned card stays at its spot", () => {
  const L = layout([...items, { ...it("u1", "me", 99), pin: { x: 5000, y: 7 } }], rels, desk, { ...st, view: "bill" }, fit);
  expect(L.front).toBe("bill");
  expect(L.tiles.u1).toMatchObject({ x: 5000, y: 7, proj: null });
});
