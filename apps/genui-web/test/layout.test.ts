import { expect, test } from "bun:test";
import { GAP, type Item, layout, packCheck, type Rel } from "../src/layout";

const it = (id: string, proj: string, prio: number): Item => ({ id, proj, prio, done: false });
const items = [
  it("d1", "swap", 90),
  it("p1", "swap", 60),
  it("t1", "swap", 50),
  it("c1", "crew", 80),
  it("k1", "crew", 40),
  it("i1", "bill", 70),
  it("h1", "host", 10),
];
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

// mixed heights per card, so the packing has to close the holes a short card leaves
const H: Record<string, number> = { m0: 80, m1: 300, m2: 140, m3: 60, m4: 220 };
const mixed = Object.keys(H).map((id, i) => it(id, "swap", 90 - i));
const tall = (id: string) => H[id] ?? 120;

test("a cluster packs cards of mixed height with no overlap, no hole and nothing outside its frame", () => {
  for (const vp of [desk, { W: 390, H: 844, topH: 110, botH: 170 }]) {
    const L = layout(mixed, [], vp, st, tall);
    const c = L.clusters[0];
    const ts = mixed.map((t) => L.tiles[t.id]);
    // the front cluster is at scale 1, so its cards and frame share one space
    expect(c.s).toBe(1);
    expect(packCheck(c, ts)).toEqual({ gap: 0, overlap: 0, outside: 0 });
    for (const t of mixed) expect(L.tiles[t.id].h).toBeGreaterThanOrEqual(H[t.id]);
    // the frame wraps the cards: the bottom card ends one padding above the frame floor
    expect(Math.max(...ts.map((t) => t.y + t.h))).toBeCloseTo(c.y + c.h - 22);
  }
});

test("the packing check sees a hole wider than the gutter, an overlap and a card that leaves its cluster", () => {
  const c = { x: 0, y: 0, w: 22 * 2 + 400, h: 48 + 22 + 200 };
  const a = { x: 22, y: 48, w: 192, h: 200 };
  expect(packCheck(c, [a, { x: 22 + 192 + GAP, y: 48, w: 192, h: 200 }])).toEqual({ gap: 0, overlap: 0, outside: 0 });
  expect(packCheck(c, [a, { x: 22 + 192 + GAP, y: 48, w: 192, h: 100 }]).gap).toBeGreaterThan(0);
  expect(packCheck(c, [a, { x: 400, y: 48, w: 192, h: 200 }]).outside).toBeGreaterThan(0);
  expect(packCheck(c, [a, { ...a, x: 100 }]).overlap).toBeGreaterThan(0);
});

test("a user size wins: its width sets its column and its height is a floor the row grows to", () => {
  const sized = mixed.map((t) => (t.id === "m1" ? { ...t, size: { w: 500, h: 400 } } : t));
  const L = layout(sized, [], desk, st, tall);
  expect(L.tiles.m1.w).toBe(500);
  expect(L.tiles.m1.h).toBe(400);
  expect(
    packCheck(
      L.clusters[0],
      sized.map((t) => L.tiles[t.id]),
    ),
  ).toEqual({ gap: 0, overlap: 0, outside: 0 });
});

test("a plan's layout: a wide card takes the row alone, a stacked card peeks out behind its front, an edge card sits beside", () => {
  const plan: Item[] = [
    { ...it("m0", "swap", 90), wide: true },
    it("m1", "swap", 80),
    it("m2", "swap", 70),
    { ...it("m3", "swap", 60), under: "m1" },
    { ...it("m4", "swap", 50), edge: true },
  ];
  const L = layout(plan, [], desk, st, tall);
  const [c, t] = [L.clusters[0], L.tiles];
  expect(c.s).toBe(1);
  expect(t.m0.w).toBeCloseTo(t.m1.w + GAP + t.m2.w);
  expect(t.m1.y).toBeGreaterThan(t.m0.y + t.m0.h);
  expect(t.m3.x).toBeGreaterThan(t.m1.x);
  expect(t.m3.y).toBeGreaterThan(t.m1.y);
  expect(t.m3.z).toBeLessThan(t.m1.z);
  expect(t.m4.x).toBeGreaterThan(t.m0.x + t.m0.w);
  const flat = ["m0", "m1", "m2", "m4"].map((id) => t[id]);
  for (const a of flat) for (const b of flat) if (a !== b) expect(overlap(a, b)).toBe(false);
  for (const x of Object.values(t)) {
    expect(x.x + x.w).toBeLessThanOrEqual(c.x + c.w);
    expect(x.y + x.h).toBeLessThanOrEqual(c.y + c.h);
  }
});

test("floating windows keep their spot and stack by layer: the highest layer is on top", () => {
  const wins: Item[] = [
    { ...it("wa", "me", 0), pin: { x: 0, y: 0 }, layer: 9 },
    { ...it("wb", "me", 0), pin: { x: 50, y: 50 }, layer: -3 },
    { ...it("wc", "me", 0), pin: { x: 90, y: 90 } },
  ];
  const t = layout([...items, ...wins], rels, desk, st, fit).tiles;
  expect([t.wa.x, t.wb.y]).toEqual([0, 50]);
  expect(t.wb.z).toBeLessThan(t.wc.z);
  expect(t.wc.z).toBeLessThan(t.wa.z);
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
