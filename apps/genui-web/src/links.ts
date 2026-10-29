// Link lines from the design (drawLinks()): drawn in screen space every frame from where both cards are now.
// Right-angle routes leave the front cluster through its edge into a side lane; a dot at each end; a label pill;
// both cards get a ring in the line's colour. A line whose card, cluster or camera is moving undraws, then draws again.
import type { Line } from "./layout";

export type LinkSource = {
  lines: Line[];
  front: string | undefined;
  spread: boolean;
  k: number;
  colour: (proj: string) => string;
};

const SVGNS = "http://www.w3.org/2000/svg";
const MOVE = /^(left|top|width|height|transform)$/;
const ease = (e: number) => 1 - (1 - e) ** 3;
const cl = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
const esc = (v: string) => v.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
type Pt = [number, number];
type Route = { key: string; pts: Pt[]; from: Pt[] | null; t0: number; back: boolean; li?: number };

type Box = number[]; // [x, y, w, h, weight] in canvas space
/** One frame's shared view: where the canvas is, its floor, the cards a label should not cover, the lanes used per side. */
type Frame = { cv: DOMRect; bottom: number; boxes: Box[]; lane: Record<string, number>; k: number; spread: boolean; ms: number };
type Geo = { pts: Pt[]; side: number; fb: DOMRect; rkey: string };

const byId = (id: string) => document.getElementById(id);

/** Every card on screen: a label pill should cover none; if it must, it covers a blurred card behind (weight 1, not 10). */
function tileBoxes(cv: DOMRect): Box[] {
  return [...document.querySelectorAll(".tile:not(.gone)")].map((e) => {
    const r = e.getBoundingClientRect();
    return [r.left - cv.left, r.top - cv.top, r.width, r.height, e.matches(".away") ? 1 : 10];
  });
}

/** A line whose card, front cluster or camera is moving stays undrawn until that move is in its last tenth. */
function moving() {
  return new Set(
    document.getAnimations().flatMap((a) => {
      const t = a as CSSTransition;
      return MOVE.test(t.transitionProperty ?? "") && a.playState === "running" && (a.effect?.getComputedTiming().progress ?? 1) < 0.9 ? [(a.effect as KeyframeEffect).target] : [];
    }),
  );
}

/** The right-angle route from card `ea` in cluster `FB` out to a side lane and into card `eb`, in screen space. */
function route(fr: Frame, FB: HTMLElement, ea: HTMLElement, eb: HTMLElement): Geo {
  const fb = FB.getBoundingClientRect(), ra = ea.getBoundingClientRect(), rb = eb.getBoundingClientRect();
  const side = rb.left + rb.width / 2 > fb.left + fb.width / 2 ? 1 : -1, n = fr.lane[side]++, gx = side > 0 ? fb.right + 18 + n * 12 : fb.left - 18 - n * 12;
  const { p, near, far } = leave(fb, ra, side, fr.k);
  const { x1, y1, free, below, above } = arrive(fb, rb, side, gx, fr);
  // the card a line points at is lifted over the clusters between it and the front one
  const z = !fr.spread && (free || below || above) ? "29" : "32";
  if (eb.style.zIndex !== z) eb.style.zIndex = z;
  p.push([gx, p.at(-1)![1]], [gx, y1], [x1, y1]);
  return { pts: p.map(([x, y]): Pt => [x - fr.cv.left, y - fr.cv.top]), side, fb, rkey: [side, n, near, far, free, below, above].join() };
}

/** Leave the front card `ra` straight out through the cluster's outer edge, so no bend falls inside the cluster. */
function leave(fb: DOMRect, ra: DOMRect, side: number, k: number) {
  const ys = ra.top + Math.min(ra.height / 2, 60 * k), hx = side > 0 ? fb.left - 18 : fb.right + 18;
  const near = side > 0 ? fb.right - ra.right < 40 : ra.left - fb.left < 40, far = side > 0 ? ra.left - fb.left < 40 : fb.right - ra.right < 40;
  const sx = side > 0 ? ra.right - 30 : ra.left + 30;
  const p: Pt[] = near ? [[side > 0 ? ra.right : ra.left, ys]] : far ? [[side > 0 ? ra.left : ra.right, ys], [hx, ys], [hx, fb.bottom + 18]] : [[sx, ra.bottom], [sx, fb.bottom + 18]];
  return { p, near, far };
}

/** End on a part of the target `rb` the front cluster does not cover, never under the composer. */
function arrive(fb: DOMRect, rb: DOMRect, side: number, gx: number, fr: Frame) {
  let x1 = cl(side > 0 ? gx + 16 : gx - 16, rb.left + 14, rb.right - 14), y1 = rb.top + Math.min(rb.height / 2, 50 * fr.k);
  if (side > 0 ? rb.left >= gx : rb.right <= gx) x1 = side > 0 ? rb.left : rb.right;
  const free = side > 0 ? x1 >= fb.right + 8 : x1 <= fb.left - 8, below = rb.bottom - fb.bottom >= 24, above = fb.top - rb.top >= 24;
  if (!free && (below || above)) {
    y1 = below ? (Math.max(rb.top, fb.bottom) + rb.bottom) / 2 : (rb.top + Math.min(rb.bottom, fb.top)) / 2;
    x1 = side > 0 ? rb.right - 20 : rb.left + 20;
  }
  return { x1, y1: Math.min(y1, Math.max(rb.top + 8, fr.bottom - 12)), free, below, above };
}

/** A route that changes shape blends into the new one; a new or returning line starts on its final route. */
function blend(st: Route, q: Pt[], rkey: string, ms: number): Pt[] {
  if (st.back) Object.assign(st, { key: rkey, pts: q, from: null, t0: ms - 1e4 });
  else if (st.key !== rkey) Object.assign(st, { key: rkey, from: st.pts, t0: ms });
  const from = st.from ?? st.pts, pad = q.map((_, i) => from[Math.max(0, i - (q.length - from.length))] ?? q[0]), e = ease(Math.min(1, (ms - st.t0) / 450));
  if (e >= 1) st.from = null;
  return (st.pts = e >= 1 ? q : q.map(([x, y], i): Pt => [pad[i][0] + (x - pad[i][0]) * e, pad[i][1] + (y - pad[i][1]) * e]));
}

/** The label takes the first spot along the line that covers no card and no other label; it keeps its last spot while that stays free, so it never flickers. */
function labelSpot(fr: Frame, st: Route, pts: Pt[], g: Geo, label: string): Pt {
  const { cv } = fr, { side, fb } = g;
  const tw = label.length * 7.8, Wl = tw + 18, lgx = pts.at(-2)![0], ey = pts.at(-1)![1], my = (pts.at(-3)![1] + ey) / 2;
  const runs = pts.slice(1).flatMap(([x, y], i): Pt[] => {
    const [x0, y0] = pts[i];
    return Math.abs(y - y0) < 1 && Math.abs(x - x0) > Wl + 20 ? [[(x + x0) / 2 - tw / 2, y - 11]] : [];
  });
  const bx = side > 0 ? fb.right - cv.left - Wl : fb.left - cv.left + 9, maxY = fr.bottom - cv.top - 26, sx = side > 0 ? lgx + 10 : lgx - 10 - tw;
  const spots = [...runs, [lgx + 10, my - 11], [lgx - 10 - tw, my - 11], [sx, ey - 30], [sx, ey + 10], [lgx - 10 - tw, ey - 30], [lgx + 10, ey - 30], [bx, fb.bottom - cv.top + 30], [bx, fb.top - cv.top - 30]].map(
    ([x, y]): Pt => [cl(x, 18, cv.width - 18 - tw), cl(y, 4, maxY)],
  );
  const hit = ([x, y]: Pt) => fr.boxes.reduce((s, b) => s + b[4] * Math.max(0, Math.min(x - 9 + Wl, b[0] + b[2]) - Math.max(x - 9, b[0])) * Math.max(0, Math.min(y + 22, b[1] + b[3]) - Math.max(y, b[1])), 0);
  let li = st.li !== undefined && spots[st.li] && !hit(spots[st.li]) ? st.li : spots.findIndex((s) => !hit(s));
  if (li < 0) li = spots.reduce((a, s, i) => (hit(s) < hit(spots[a]) ? i : a), 0);
  const spot = spots[(st.li = li)];
  fr.boxes.push([spot[0] - 9, spot[1], Wl, 22, 10]);
  return spot;
}

/** The line markup (cased path and end dots) and the label pill markup. */
function markup(pts: Pt[], [lx, ly]: Pt, label: string, col: string): [string, string] {
  const d = "M" + pts.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join("L"), Wl = label.length * 7.8 + 18;
  const dots = [pts[0], pts.at(-1)!].map(([x, y]) => `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5" fill="${col}"/>`).join("");
  const pill = label ? `<rect x="${(lx - 9).toFixed(1)}" y="${ly.toFixed(1)}" width="${Wl.toFixed(1)}" height="22" rx="11" fill="var(--bg)" stroke="${col}"/><text x="${lx.toFixed(1)}" y="${(ly + 15).toFixed(1)}">${esc(label)}</text>` : "";
  return [`<path class="case" pathLength="1" d="${d}"/><path pathLength="1" d="${d}" stroke="${col}"/>${dots}`, pill];
}

/** The two SVG layers, the world (its transform moves every card) and each line's route state. */
type Layers = { L: SVGGElement; LB: SVGGElement; world: HTMLElement; LP: Record<string, Route>; shown: WeakMap<Element, string> };
type Part = [string, string | null, string | null];

/** One line's [key, line markup, label markup]; null markup means the line undraws while its cards move. */
function part(ls: Layers, fr: Frame, run: Set<unknown>, fbx: HTMLElement, { f, o, label, proj, g }: Line, col: string): Part {
  const FB = (g && byId(`g-${g}`)) || fbx, ea = byId(`t-${f}`), eb = byId(`t-${o}`), key = `${f}>${o}`;
  if (!ea || !eb) return [key, "", ""];
  // set only on change: rewriting a class or a property every frame forces a style pass over the board
  for (const e of [ea, eb]) {
    if (!e.classList.contains("lk")) e.classList.add("lk");
    if (e.style.getPropertyValue("--lk") !== col) e.style.setProperty("--lk", col);
  }
  if ([ea, eb, FB, ls.world].some((e) => run.has(e))) {
    if (ls.LP[key]) ls.LP[key].back = true;
    return [key, null, null];
  }
  const geo = route(fr, FB, ea, eb);
  const st = (ls.LP[key] ??= { key: geo.rkey, pts: geo.pts, from: null, t0: fr.ms, back: true });
  const pts = blend(st, geo.pts, geo.rkey, fr.ms);
  return [key, ...markup(pts, labelSpot(fr, st, pts, geo, label), label, col)];
}

/** One group per line in the line layer, one per label in the label layer above every line. */
function sync(ls: Layers, parts: Part[]) {
  for (const key in ls.LP) if (!parts.some(([x]) => x === key)) delete ls.LP[key]; // a line that comes back grows out again
  for (const layer of [ls.L, ls.LB]) for (const g of [...layer.children] as SVGGElement[]) if (!parts.some(([key]) => key === g.dataset.k)) g.remove();
  for (const [key, h, hl] of parts) {
    const st = ls.LP[key], back = h !== null && !!st?.back;
    if (back) st.back = false;
    show(ls, ls.L, key, h, back);
    show(ls, ls.LB, key, hl, back);
  }
}

function show(ls: Layers, layer: SVGGElement, key: string, html: string | null, back: boolean) {
  let g = ([...layer.children] as SVGGElement[]).find((x) => x.dataset.k === key);
  if (!g) {
    g = document.createElementNS(SVGNS, "g");
    g.dataset.k = key;
    layer.append(g);
  }
  if (html === null) return g.setAttribute("class", "out");
  if (back) {
    g.setAttribute("class", "in");
    setTimeout(() => g.removeAttribute("class"), 800);
  }
  if (ls.shown.get(g) !== html) (ls.shown.set(g, html), (g.innerHTML = html));
}

/** Starts the line loop on `svg` (which holds a line layer and a label layer); `get` reads the current layout. */
export function startLinks(svg: SVGSVGElement, get: () => LinkSource) {
  const L = document.createElementNS(SVGNS, "g"), LB = document.createElementNS(SVGNS, "g");
  svg.append(L, LB);
  const canvas = svg.parentElement!;
  const ls: Layers = { L, LB, world: canvas.querySelector<HTMLElement>(".world")!, LP: {}, shown: new WeakMap() };

  function draw() {
    requestAnimationFrame(draw);
    const { lines, front, spread, k, colour } = get();
    const fbx = front ? byId(`g-${front}`) : null, cv = canvas.getBoundingClientRect();
    const bar = document.querySelector(".bottom, .composer")?.getBoundingClientRect();
    const linked = new Set(lines.flatMap((l) => [byId(`t-${l.f}`), byId(`t-${l.o}`)]));
    for (const e of document.querySelectorAll<HTMLElement>(".tile.lk")) if (!fbx || !linked.has(e)) e.classList.remove("lk");
    // no line to draw: skip measuring every card, which is most of a frame on a large board
    if (!fbx || !lines.length) return sync(ls, []);
    const fr: Frame = { cv, bottom: bar?.height ? bar.top : cv.bottom, boxes: tileBoxes(cv), lane: { 1: 0, "-1": 0 }, k, spread, ms: performance.now() };
    const run = moving();
    sync(ls, lines.map((l) => part(ls, fr, run, fbx, l, colour(l.proj))));
  }
  requestAnimationFrame(draw);
}
