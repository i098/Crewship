// Priority layout from the design (docs/genui/design, layout()): one glass cluster per project. Clusters sit apart
// around the top one, and inside a cluster the cards sit around its top card, ring by ring.
// No DOM here: card heights come from `fit`, so the tests run it with fake heights.
import type { Rect } from "@crewship/genui-spec";

export type Item = {
  id: string;
  proj: string;
  prio: number;
  done: boolean;
  /** A free spot (a pinned card); it stays out of the clusters. */
  pin?: { x: number; y: number };
  /** A size the user gave; the width sets its column in a two-up row, the height is a floor. */
  size?: { w?: number; h?: number };
};
export type Rel = { from: string; to: string; label: string };
export type Viewport = { W: number; H: number; topH: number; botH: number };
export type State = {
  /** The cluster you opened; null means the top one. */
  view: string | null;
  spread: boolean;
  /** Cards you selected or asked for. */
  picked: Set<string>;
  /** Card order per cluster that you set by dragging. */
  order: Record<string, string[]>;
};
export type ClusterBox = Rect & { proj: string; s: number; z: number; front: boolean; far: boolean; right: boolean; ids: string[] };
export type TileBox = Rect & { s: number; z: number; away: boolean; far: boolean; center: boolean; proj: string | null };
/** A line from a card `f` to the card `o` it affects; `g` is the cluster it leaves from in spread. */
export type Line = { f: string; o: string; label: string; proj: string; g: string | null };
export type Layout = {
  clusters: ClusterBox[];
  tiles: Record<string, TileBox>;
  lines: Line[];
  /** The front cluster and the item at the very centre. */
  front: string | undefined;
  center: string | undefined;
  /** Cluster order, most important first ([ and ] walk it). */
  order: string[];
  spread: boolean;
  cam: { x: number; y: number; k: number };
};

export const P = 22, HD = 48, GAP = 16, CW0 = 380, CGAP = 120;

type Fit = (id: string, w: number) => number;
type Group = { proj: string; ts: Item[]; p: number };
/** What decides which links count: the cards, the front cluster and the cards you picked. */
type Scope = { byId: Map<string, Item>; vg: Group | undefined; picked: Set<string> };

const live = (a: Item | undefined, b: Item | undefined): a is Item => !!a && !!b && !(a.done && b.done);
// the all-projects cluster touches everything, so there a line shows only for a card you picked
const want = (sc: Scope, a: string, b: string) => !sc.vg || sc.vg.proj !== "all" || sc.picked.has(a) || sc.picked.has(b);

export function layout(items: Item[], rels: Rel[], vp: Viewport, st: State, fit: Fit): Layout {
  const { W, H } = vp;
  const gs = groups(items, st.order);
  const vg = gs.find((g) => g.proj === st.view) ?? gs[0];
  const SP = st.spread && gs.length > 1;
  const sc: Scope = { byId: new Map(items.map((t) => [t.id, t])), vg, picked: st.picked };
  const tiles = pinned(items, fit);
  // the clusters' grid follows the screen's shape: wide screens get more columns, phones a stack
  const cols = Math.max(1, Math.round(Math.sqrt(gs.length * (W / H))));
  const { clusters, gOf } = place(gs, vg, pulled(rels, gs, sc), tiles, { SP, cols, fit });
  return {
    clusters,
    tiles,
    lines: linesOf(rels, gOf, clusters[0], sc, SP),
    front: vg?.proj,
    center: gs[0]?.ts[0]?.id,
    order: gs.map((g) => g.proj),
    spread: SP,
    cam: fitCam(clusters, tiles, SP ? undefined : focusOf(clusters[0], tiles, W < 600), vp, SP),
  };
}

/** What the camera fits in focus: the front cluster, or on a phone its top card so it reads at full size. */
function focusOf(V: ClusterBox | undefined, tiles: Record<string, TileBox>, one: boolean): Rect | undefined {
  const t = V && tiles[V.ids[0]];
  return one && t ? { x: t.x - GAP, y: t.y - GAP, w: t.w + 2 * GAP, h: t.h + 2 * GAP } : V;
}

/** Loose cards by project, most important project first. Cards you moved keep the order you gave them; new ones still come in on top by priority. */
function groups(items: Item[], order: State["order"]): Group[] {
  const by = new Map<string, Item[]>();
  for (const t of items) if (!t.pin) by.set(t.proj, [...(by.get(t.proj) ?? []), t]);
  const rk = (proj: string, t: Item) => {
    const i = (order[proj] ?? []).indexOf(t.id);
    return i < 0 ? -1000 - t.prio : i;
  };
  return [...by].map(([proj, ts]) => (ts.sort((a, b) => rk(proj, a) - rk(proj, b)), { proj, ts, p: Math.max(...ts.map((t) => t.prio)) })).sort((a, b) => b.p - a.p);
}

/** Items you placed stay where you put them. */
function pinned(items: Item[], fit: Fit): Record<string, TileBox> {
  const tiles: Record<string, TileBox> = {};
  for (const t of items)
    if (t.pin) {
      const w = t.size?.w || CW0;
      tiles[t.id] = { x: t.pin.x, y: t.pin.y, w, h: Math.max(fit(t.id, w), t.size?.h ?? 0), s: 1, z: 32, away: false, far: false, center: false, proj: null };
    }
  return tiles;
}

/** A cluster holding a card the front one points at steps out beside it. */
function pulled(rels: Rel[], gs: Group[], sc: Scope): Set<string> {
  const inV = new Set(sc.vg ? sc.vg.ts.map((t) => t.id) : []);
  const other = (a: string, b: string) => {
    const A = sc.byId.get(a), B = sc.byId.get(b);
    return live(A, B) && want(sc, a, b) && inV.has(a) && !inV.has(b) ? [B!.proj] : [];
  };
  return new Set(rels.flatMap((r) => [...other(r.from, r.to), ...other(r.to, r.from)]).filter((p) => gs.some((g) => g.proj === p && g !== sc.vg)));
}

type PlaceOpts = { SP: boolean; cols: number; fit: Fit };

/** The open cluster takes the middle; a cluster it links to takes the next spot, then the rest by priority, ring by ring.
 * In focus the ones around are smaller the further out they sit; in spread all are full size. */
function place(gs: Group[], vg: Group | undefined, pull: Set<string>, tiles: Record<string, TileBox>, o: PlaceOpts) {
  const rest = gs.filter((g) => g !== vg);
  const ord = vg ? [vg, ...rest.filter((g) => pull.has(g.proj)), ...rest.filter((g) => !pull.has(g.proj))] : [];
  const inner = ord.map((g) => tile(g.ts, o.fit));
  const grid = cellsAround(ord.length, o.cols);
  const s = grid.ring.map((d) => (o.SP ? 1 : 0.9 ** d));
  const spot = around(inner.map((b, i) => [b.w * s[i], b.h * s[i]]), grid, CGAP);
  const clusters: ClusterBox[] = [];
  const gOf = new Map<string, ClusterBox>();
  ord.forEach((g, i) => {
    const front = o.SP || i === 0, d = front ? 0 : grid.ring[i], far = !front && pull.size > 0 && !pull.has(g.proj);
    const [x, y] = spot.at[i], box: ClusterBox = { proj: g.proj, x, y, w: inner[i].w, h: inner[i].h, s: s[i], z: 30 - 3 * d, front, far, right: x > spot.at[0][0], ids: g.ts.map((t) => t.id) };
    clusters.push(box);
    g.ts.forEach((t, j) => {
      const r = inner[i].local[j];
      gOf.set(t.id, box);
      tiles[t.id] = { x: x + r[0] * s[i], y: y + r[1] * s[i], w: r[2], h: r[3], s: s[i], z: 31 - 3 * d, away: !front, far, center: g === gs[0] && j === 0, proj: g.proj };
    });
  });
  return { clusters, gOf };
}

/** Cards around the cluster's top card: [x, y, w, h] per card inside the cluster, and the cluster's size. */
function tile(ts: Item[], fit: Fit) {
  const sz = ts.map((t) => {
    const w = t.size?.w ? Math.max(200, Math.min(2 * CW0, t.size.w)) : CW0;
    return [w, Math.max(fit(t.id, w), t.size?.h ?? 0)];
  });
  const spot = around(sz, cellsAround(ts.length, Math.ceil(Math.sqrt(ts.length))), GAP);
  return { local: sz.map((s, i) => [P + spot.at[i][0], HD + spot.at[i][1], s[0], s[1]]), w: spot.w + 2 * P, h: HD + spot.h + P };
}

type Grid = { cells: number[][]; cx: number; cy: number; ring: number[] };

/** Grid cells for `n` boxes: the first takes the middle cell, the next ones the nearest cells, right, below, left, above. */
function cellsAround(n: number, cols: number): Grid {
  const rows = Math.ceil(n / cols), cx = (cols - 1) >> 1, cy = (rows - 1) >> 1;
  const key = ([c, r]: number[]) => {
    const dx = c - cx, dy = r - cy;
    return [Math.max(Math.abs(dx), Math.abs(dy)), dx * dx + dy * dy, (Math.atan2(dy, dx) + 2 * Math.PI) % (2 * Math.PI)];
  };
  const cmp = (a: number[], b: number[]) => a.map((v, i) => v - b[i]).find((v) => Math.abs(v) > 1e-9) ?? 0;
  const cells = Array.from({ length: cols * rows }, (_, i) => [i % cols, Math.floor(i / cols)]).sort((a, b) => cmp(key(a), key(b))).slice(0, n);
  return { cells, cx, cy, ring: cells.map((c) => key(c)[0]) };
}

/** Boxes `sz` ([w, h]) in their cells: a column is as wide as its widest box, a row as tall as its tallest,
 * empty ones take no room, and each box leans toward the middle cell. Returns [x, y] per box and the total size. */
function around(sz: number[][], g: Grid, gap: number) {
  const X = lanes(g.cells.map((c) => c[0]), sz.map((s) => s[0]), gap), Y = lanes(g.cells.map((c) => c[1]), sz.map((s) => s[1]), gap);
  const lean = (d: number, at: number, cell: number, len: number) => at + (d < 0 ? cell - len : d > 0 ? 0 : (cell - len) / 2);
  const at = g.cells.map(([c, r], i) => [lean(c - g.cx, X.start[c], X.size[c], sz[i][0]), lean(r - g.cy, Y.start[r], Y.size[r], sz[i][1])]);
  return { at, w: X.total, h: Y.total };
}

/** Where each lane (a column or a row) starts; `lane[i]` is box i's lane and `len[i]` its length. */
function lanes(lane: number[], len: number[], gap: number) {
  const size: number[] = [], start: number[] = [];
  lane.forEach((l, i) => (size[l] = Math.max(size[l] ?? 0, len[i])));
  let at = 0;
  for (let l = 0; l < size.length; l++)
    if (size[l] !== undefined) {
      start[l] = at;
      at += size[l] + gap;
    }
  return { start, size, total: Math.max(0, at - gap) };
}

/** A line joins a card in the front cluster `V` to the card it affects in a cluster behind.
 * In spread every cluster is in front, so a line shows only for a card you picked, from that card's cluster. */
function linesOf(rels: Rel[], gOf: Map<string, ClusterBox>, V: ClusterBox | undefined, sc: Scope, SP: boolean): Line[] {
  const lines: Line[] = [];
  for (const r of rels) {
    const A = gOf.get(r.from), B = gOf.get(r.to), a = sc.byId.get(r.from);
    if (!A || !B || A === B || !live(a, sc.byId.get(r.to))) continue;
    const f = SP ? [r.from, r.to].find((id) => sc.picked.has(id)) : (A === V || B === V) && want(sc, r.from, r.to) ? (A === V ? r.from : r.to) : undefined;
    if (f !== undefined) lines.push({ f, o: f === r.from ? r.to : r.from, label: r.label, proj: a.proj, g: SP ? sc.byId.get(f)!.proj : null });
  }
  return lines;
}

/** Fits the front cluster between the top line and the composer, with a strip of the ones around showing; never past real size.
 * With no `focus` (spread) it fits the box round every cluster instead. */
function fitCam(clusters: ClusterBox[], tiles: Record<string, TileBox>, focus: Rect | undefined, vp: Viewport, SP: boolean) {
  const { W, H } = vp, wide = W / H > 1.1;
  const all = [...clusters.map((c) => ({ x: c.x, y: c.y, w: c.w * c.s, h: c.h * c.s })), ...Object.values(tiles).filter((t) => !t.proj)];
  const bb = all.reduce((q, p) => [Math.min(q[0], p.x), Math.min(q[1], p.y), Math.max(q[2], p.x + p.w), Math.max(q[3], p.y + p.h)], [1e9, 1e9, -1e9, -1e9]);
  const o = focus ?? (all.length ? { x: bb[0], y: bb[1], w: bb[2] - bb[0], h: bb[3] - bb[1] } : { x: 0, y: 0, w: W, h: H });
  const k = Math.max(0.02, Math.min(1, (SP ? W - 40 : wide ? W * 0.72 : W - 56) / o.w, ((H - vp.topH - vp.botH - 30) * (SP ? 0.96 : 0.88)) / o.h));
  return { x: o.x + o.w / 2, y: o.y + o.h / 2 + (vp.botH - vp.topH) / 2 / k, k };
}
