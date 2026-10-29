// Priority layout from the design (docs/genui/design, layout()): one glass cluster per project,
// the top cluster in front, the rest fanned out behind it; cards tile in two columns with no empty space.
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

export const P = 22, HD = 48, GAP = 16, CW0 = 380;

export function layout(items: Item[], rels: Rel[], vp: Viewport, st: State, fit: (id: string, w: number) => number): Layout {
  const { W, H } = vp, wide = W / H > 1.1, one = W < 600, W2 = one ? CW0 : 2 * CW0 + GAP; // phones stack one column
  const byId = new Map(items.map((t) => [t.id, t]));
  const tiles: Record<string, TileBox> = {};
  const by = new Map<string, Item[]>();
  for (const t of items) if (!t.pin) by.set(t.proj, [...(by.get(t.proj) ?? []), t]);
  // cards you moved keep the order you gave them; new ones still come in on top by priority
  const rk = (proj: string, t: Item) => {
    const i = (st.order[proj] ?? []).indexOf(t.id);
    return i < 0 ? -1000 - t.prio : i;
  };
  const gs = [...by].map(([proj, ts]) => (ts.sort((a, b) => rk(proj, a) - rk(proj, b)), { proj, ts, p: Math.max(...ts.map((t) => t.prio)) })).sort((a, b) => b.p - a.p);
  const vg = gs.find((g) => g.proj === st.view) ?? gs[0];
  // items you placed stay where you put them
  for (const t of items)
    if (t.pin) {
      const w = t.size?.w || CW0;
      tiles[t.id] = { x: t.pin.x, y: t.pin.y, w, h: Math.max(fit(t.id, w), t.size?.h ?? 0), s: 1, z: 32, away: false, far: false, center: false, proj: null };
    }
  const SP = st.spread && gs.length > 1;
  const colY: number[] = Array(Math.max(1, Math.ceil(Math.sqrt(gs.length * (wide ? 1.6 : 0.7))))).fill(0);
  const SPW = W2 + 2 * P;
  // the all-projects cluster touches everything, so there a line shows only for a card you picked
  const want = (a: string, b: string) => !vg || vg.proj !== "all" || st.picked.has(a) || st.picked.has(b);
  const inV = new Set(vg ? vg.ts.map((t) => t.id) : []);
  const live = (a: Item | undefined, b: Item | undefined): a is Item => !!a && !!b && !(a.done && b.done);
  const other = (a: string, b: string) => {
    const A = byId.get(a), B = byId.get(b);
    return live(A, B) && want(a, b) && inV.has(a) && !inV.has(b) ? [B!.proj] : [];
  };
  // a cluster holding a card the front one points at steps out beside it
  const pull = new Set(rels.flatMap((r) => [...other(r.from, r.to), ...other(r.to, r.from)]).filter((p) => gs.some((g) => g.proj === p && g !== vg)));
  const clusters: ClusterBox[] = [];
  const gOf = new Map<string, ClusterBox>();
  let V0: Rect | undefined, rank = 0, pr = 0;
  for (const g of vg ? [vg, ...gs.filter((x) => x !== vg)] : []) {
    const CW = one ? W2 : (W2 - GAP) / 2;
    const fitT = (i: number, w: number) => Math.max(fit(g.ts[i].id, w), g.ts[i].size?.h ?? 0);
    const clW = (v: number) => Math.max(200, Math.min(W2 - GAP - 200, v));
    const colW = (a: Item, b: Item) => (a.size?.w ? clW(a.size.w) : b.size?.w ? W2 - GAP - clW(b.size.w) : CW);
    // window-manager tiling: the top item takes a full row when the count is odd, the rest pair up,
    // and each row is as tall as its tallest item so the edges line up
    const local: number[][] = [];
    let yy = HD;
    for (let j = 0; j < g.ts.length; ) {
      const n = one || (g.ts.length - j) % 2 ? 1 : 2, row = [j, j + 1].slice(0, n);
      const wa = n === 1 ? W2 : colW(g.ts[j], g.ts[j + 1]), ws = [wa, W2 - GAP - wa], h = Math.max(...row.map((i, c) => fitT(i, ws[c])));
      row.forEach((i, c) => (local[i] = [P + c * (wa + GAP), yy, ws[c], h]));
      yy += h + GAP;
      j += n;
    }
    // no empty gap: every card grows down to the card under it, or to the cluster's floor
    const IB = Math.max(...local.map((r) => r[1] + r[3]));
    for (const r of local) {
      const under = local.filter((q) => q !== r && q[1] > r[1] + 4 && q[0] < r[0] + r[2] && q[0] + q[2] > r[0]).map((q) => q[1] - GAP);
      r[3] = Math.max(r[3], Math.min(IB, ...under) - r[1]);
    }
    const w = W2 + 2 * P, h = IB + P;
    // focus: the open cluster sits in front; the rest fan out behind it, right then left, smaller and further the less they matter
    const front = SP || g === vg, out = !front && pull.has(g.proj), far = !front && pull.size > 0 && !out;
    const k = front ? 0 : out ? pr++ : pull.size + rank++, side = front ? 0 : k % 2 ? -1 : 1, d = front ? 0 : (k >> 1) + 1, s = 0.9 ** d;
    let x = 0, y = 0;
    if (SP) {
      const c = colY.indexOf(Math.min(...colY));
      x = c * (SPW + 56);
      y = colY[c];
      colY[c] += h + 56;
    } else if (V0 && out) {
      x = side > 0 ? V0.x + V0.w + 56 : V0.x - 56 - w * s;
      y = V0.y + (V0.h - h * s) / 2;
    } else if (V0) {
      x = side > 0 ? V0.x + V0.w + 300 + (d - 1) * 110 - w * s : V0.x - 300 - (d - 1) * 110;
      y = V0.y + (V0.h - h * s) / 2 + (d - 1) * 28;
    }
    if (g === vg) V0 = { x, y, w: w * s, h: h * s };
    const box: ClusterBox = { proj: g.proj, x, y, w, h, s, z: 30 - 3 * d, front, far, right: side > 0, ids: g.ts.map((t) => t.id) };
    clusters.push(box);
    g.ts.forEach((t, i) => {
      const r = local[i];
      gOf.set(t.id, box);
      tiles[t.id] = { x: x + r[0] * s, y: y + r[1] * s, w: r[2], h: r[3], s, z: 31 - 3 * d, away: !front, far, center: g === gs[0] && i === 0, proj: g.proj };
    });
  }
  const V = vg && clusters[0];
  // a line joins a card in the front cluster to the card it affects in a cluster behind.
  // in spread every cluster is in front, so a line shows only for a card you picked, from that card's cluster
  const lines: Line[] = [];
  for (const r of rels) {
    const A = gOf.get(r.from), B = gOf.get(r.to), a = byId.get(r.from), b = byId.get(r.to);
    if (!A || !B || A === B || !live(a, b)) continue;
    if (SP) {
      if (!st.picked.has(r.from) && !st.picked.has(r.to)) continue;
      const f = st.picked.has(r.from) ? r.from : r.to;
      lines.push({ f, o: f === r.from ? r.to : r.from, label: r.label, proj: a.proj, g: byId.get(f)!.proj });
    } else if ((A === V || B === V) && want(r.from, r.to)) {
      lines.push(A === V ? { f: r.from, o: r.to, label: r.label, proj: a.proj, g: null } : { f: r.to, o: r.from, label: r.label, proj: a.proj, g: null });
    }
  }
  // fit the front cluster between the top line and the composer, with a strip of the ones behind showing; never past real size.
  // spread fits the box round every cluster instead
  const all = [...clusters.map((c) => ({ x: c.x, y: c.y, w: c.w * c.s, h: c.h * c.s })), ...Object.values(tiles).filter((t) => !t.proj)];
  const bb = all.reduce((q, p) => [Math.min(q[0], p.x), Math.min(q[1], p.y), Math.max(q[2], p.x + p.w), Math.max(q[3], p.y + p.h)], [1e9, 1e9, -1e9, -1e9]);
  const o = !SP && V0 ? V0 : all.length ? { x: bb[0], y: bb[1], w: bb[2] - bb[0], h: bb[3] - bb[1] } : { x: 0, y: 0, w: W, h: H };
  const k = Math.max(0.1, Math.min(1, (SP ? W - 40 : wide ? W * 0.48 : W - 56) / o.w, ((H - vp.topH - vp.botH - 30) * (SP ? 0.96 : 0.88)) / o.h));
  return {
    clusters,
    tiles,
    lines,
    front: vg?.proj,
    center: gs[0]?.ts[0]?.id,
    order: gs.map((g) => g.proj),
    spread: SP,
    cam: { x: o.x + o.w / 2, y: o.y + o.h / 2 + (vp.botH - vp.topH) / 2 / k, k },
  };
}
