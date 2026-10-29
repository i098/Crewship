import { expect, test } from "bun:test";
import { layout, type Item, type Rel } from "../src/layout";

const it = (id: string, proj: string, prio: number): Item => ({ id, proj, prio, done: false });
const items = [it("d1", "swap", 90), it("p1", "swap", 60), it("t1", "swap", 50), it("c1", "crew", 80), it("k1", "crew", 40), it("i1", "bill", 70), it("h1", "host", 10)];
const rels: Rel[] = [{ from: "d1", to: "c1", label: "blocks" }];
const desk = { W: 1280, H: 800, topH: 60, botH: 150 };
const st = { view: null, spread: false, picked: new Set<string>(), order: {} };
const fit = (id: string, w: number) => (id === "d1" ? 300 : 120) + (w < 300 ? 60 : 0);
const overlap = (a: { x: number; y: number; w: number; h: number }, b: typeof a) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

test("the top cluster sits in the middle; a linked cluster takes the next spot, the rest fade around", () => {
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

test("cards in a cluster sit around its top card with no overlap", () => {
  const many = Array.from({ length: 9 }, (_, i) => it(`m${i}`, "swap", 90 - i));
  const L = layout(many, [], desk, st, fit);
  const ts = many.map((t) => L.tiles[t.id]);
  for (const a of ts) for (const b of ts) if (a !== b) expect(overlap(a, b)).toBe(false);
  const mid = (t: (typeof ts)[0]) => [t.x + t.w / 2, t.y + t.h / 2];
  const [cx, cy] = mid(ts[0]);
  expect(new Set(ts.map((t) => t.y)).size).toBeGreaterThan(1); // not one row
  // the next four take the sides: right, below, left, above
  const [r, d, l, u] = ts.slice(1, 5).map(mid);
  expect([r[0] > cx, d[1] > cy, l[0] < cx, u[1] < cy]).toEqual([true, true, true, true]);
});

test("clusters sit apart with clear space; a phone stacks them and fits the top card on screen", () => {
  for (const vp of [desk, { W: 390, H: 844, topH: 110, botH: 170 }]) {
    const L = layout(items, rels, vp, { ...st, spread: true }, fit);
    const grow = (c: (typeof L.clusters)[0]) => ({ x: c.x - 50, y: c.y - 50, w: c.w + 100, h: c.h + 100 });
    for (const a of L.clusters) for (const b of L.clusters) if (a !== b) expect(overlap(grow(a), b)).toBe(false);
  }
  const L = layout(items, rels, { W: 390, H: 844, topH: 110, botH: 170 }, st, fit);
  expect(new Set(L.clusters.map((c) => c.x + (c.w * c.s) / 2)).size).toBe(1);
  expect(L.tiles.d1.w * L.cam.k).toBeLessThanOrEqual(390);
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
