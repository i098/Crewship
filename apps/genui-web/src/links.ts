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

/** Starts the line loop on `svg` (which holds a line layer and a label layer); `get` reads the current layout. */
export function startLinks(svg: SVGSVGElement, get: () => LinkSource) {
  const L = document.createElementNS(SVGNS, "g"), LB = document.createElementNS(SVGNS, "g");
  svg.append(L, LB);
  const canvas = svg.parentElement!, world = canvas.querySelector<HTMLElement>(".world")!;
  const LP: Record<string, Route> = {}, shown = new WeakMap<Element, string>();
  const byId = (id: string) => document.getElementById(id);

  function draw() {
    requestAnimationFrame(draw);
    const { lines, front, spread, k, colour } = get();
    const fbx = front ? byId(`g-${front}`) : null, cv = canvas.getBoundingClientRect(), ms = performance.now();
    const lane: Record<string, number> = { 1: 0, "-1": 0 };
    const bar = document.querySelector(".bottom, .composer")?.getBoundingClientRect();
    const bottom = bar?.height ? bar.top : cv.bottom;
    for (const e of document.querySelectorAll<HTMLElement>(".tile.lk")) e.classList.remove("lk");
    // every card on screen: a label pill should cover none; if it must, it covers a blurred card behind (weight 1, not 10)
    const boxes: number[][] = !fbx ? [] : [...document.querySelectorAll(".tile:not(.gone)")].map((e) => {
      const r = e.getBoundingClientRect();
      return [r.left - cv.left, r.top - cv.top, r.width, r.height, e.matches(".away") ? 1 : 10];
    });
    // a line whose card, front cluster or camera is moving stays undrawn until that move is in its last tenth
    const run = new Set(
      document.getAnimations().flatMap((a) => {
        const t = a as CSSTransition;
        return MOVE.test(t.transitionProperty ?? "") && a.playState === "running" && (a.effect?.getComputedTiming().progress ?? 1) < 0.9 ? [(a.effect as KeyframeEffect).target] : [];
      }),
    );
    const parts: [string, string | null, string | null][] = !fbx ? [] : lines.map(({ f, o, label, proj, g }) => {
      const col = colour(proj), FB = (g && byId(`g-${g}`)) || fbx, ea = byId(`t-${f}`), eb = byId(`t-${o}`), key = `${f}>${o}`;
      if (!ea || !eb) return [key, "", ""];
      for (const e of [ea, eb]) e.classList.add("lk"), e.style.setProperty("--lk", col);
      if ([ea, eb, FB, world].some((e) => run.has(e))) {
        if (LP[key]) LP[key].back = true;
        return [key, null, null];
      }
      const fb = FB.getBoundingClientRect(), ra = ea.getBoundingClientRect(), rb = eb.getBoundingClientRect();
      const side = rb.left + rb.width / 2 > fb.left + fb.width / 2 ? 1 : -1, n = lane[side]++, gx = side > 0 ? fb.right + 18 + n * 12 : fb.left - 18 - n * 12;
      // leave the front card straight out through the cluster's outer edge, so no bend falls inside the cluster
      const ys = ra.top + Math.min(ra.height / 2, 60 * k), hx = side > 0 ? fb.left - 18 : fb.right + 18;
      const near = side > 0 ? fb.right - ra.right < 40 : ra.left - fb.left < 40, far = side > 0 ? ra.left - fb.left < 40 : fb.right - ra.right < 40;
      const p: Pt[] = near
        ? [[side > 0 ? ra.right : ra.left, ys]]
        : far
          ? [[side > 0 ? ra.left : ra.right, ys], [hx, ys], [hx, fb.bottom + 18]]
          : [[side > 0 ? ra.right - 30 : ra.left + 30, ra.bottom], [side > 0 ? ra.right - 30 : ra.left + 30, fb.bottom + 18]];
      // end on a part of the target the front cluster does not cover
      let x1 = cl(side > 0 ? gx + 16 : gx - 16, rb.left + 14, rb.right - 14), y1 = rb.top + Math.min(rb.height / 2, 50 * k);
      if (side > 0 ? rb.left >= gx : rb.right <= gx) x1 = side > 0 ? rb.left : rb.right;
      const free = side > 0 ? x1 >= fb.right + 8 : x1 <= fb.left - 8, below = rb.bottom - fb.bottom >= 24, above = fb.top - rb.top >= 24;
      if (!free && (below || above)) {
        y1 = below ? (Math.max(rb.top, fb.bottom) + rb.bottom) / 2 : (rb.top + Math.min(rb.bottom, fb.top)) / 2;
        x1 = side > 0 ? rb.right - 20 : rb.left + 20;
      }
      y1 = Math.min(y1, Math.max(rb.top + 8, bottom - 12)); // never end under the composer
      // the card a line points at is lifted over the clusters between it and the front one
      const z = !spread && (free || below || above) ? "29" : "32";
      if (eb.style.zIndex !== z) eb.style.zIndex = z;
      p.push([gx, p.at(-1)![1]], [gx, y1], [x1, y1]);
      // a route that changes shape blends into the new one; a new or returning line starts on its final route
      const q = p.map(([x, y]): Pt => [x - cv.left, y - cv.top]), rkey = [side, n, near, far, free, below, above].join();
      const st = (LP[key] ??= { key: rkey, pts: q, from: null, t0: ms, back: true });
      if (st.back) Object.assign(st, { key: rkey, pts: q, from: null, t0: ms - 1e4 });
      else if (st.key !== rkey) Object.assign(st, { key: rkey, from: st.pts, t0: ms });
      const from = st.from ?? st.pts, pad = q.map((_, i) => from[Math.max(0, i - (q.length - from.length))] ?? q[0]), e = ease(Math.min(1, (ms - st.t0) / 450));
      const pts: Pt[] = (st.pts = e >= 1 ? q : q.map(([x, y], i): Pt => [pad[i][0] + (x - pad[i][0]) * e, pad[i][1] + (y - pad[i][1]) * e]));
      if (e >= 1) st.from = null;
      const d = "M" + pts.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join("L");
      // the label takes the first spot along the line that covers no card and no other label
      const tw = label.length * 7.8, Wl = tw + 18, lgx = pts.at(-2)![0], ey = pts.at(-1)![1], my = (pts.at(-3)![1] + ey) / 2;
      const runs = pts.slice(1).flatMap(([x, y], i): Pt[] => {
        const [x0, y0] = pts[i];
        return Math.abs(y - y0) < 1 && Math.abs(x - x0) > Wl + 20 ? [[(x + x0) / 2 - tw / 2, y - 11]] : [];
      });
      const bx = side > 0 ? fb.right - cv.left - Wl : fb.left - cv.left + 9, maxY = bottom - cv.top - 26;
      const spots = [...runs, [lgx + 10, my - 11], [lgx - 10 - tw, my - 11], [side > 0 ? lgx + 10 : lgx - 10 - tw, ey - 30], [side > 0 ? lgx + 10 : lgx - 10 - tw, ey + 10], [lgx - 10 - tw, ey - 30], [lgx + 10, ey - 30], [bx, fb.bottom - cv.top + 30], [bx, fb.top - cv.top - 30]].map(
        ([x, y]): Pt => [cl(x, 18, cv.width - 18 - tw), cl(y, 4, maxY)],
      );
      const hit = ([x, y]: Pt) => boxes.reduce((s, b) => s + b[4] * Math.max(0, Math.min(x - 9 + Wl, b[0] + b[2]) - Math.max(x - 9, b[0])) * Math.max(0, Math.min(y + 22, b[1] + b[3]) - Math.max(y, b[1])), 0);
      // a label keeps its last spot while that stays free, so it never flickers
      let li = st.li !== undefined && spots[st.li] && !hit(spots[st.li]) ? st.li : spots.findIndex((s) => !hit(s));
      if (li < 0) li = spots.reduce((a, s, i) => (hit(s) < hit(spots[a]) ? i : a), 0);
      const [lx, ly] = spots[(st.li = li)];
      boxes.push([lx - 9, ly, Wl, 22, 10]);
      const dots = [pts[0], pts.at(-1)!].map(([x, y]) => `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5" fill="${col}"/>`).join("");
      const pill = label ? `<rect x="${(lx - 9).toFixed(1)}" y="${ly.toFixed(1)}" width="${Wl.toFixed(1)}" height="22" rx="11" fill="var(--bg)" stroke="${col}"/><text x="${lx.toFixed(1)}" y="${(ly + 15).toFixed(1)}">${esc(label)}</text>` : "";
      return [key, `<path class="case" pathLength="1" d="${d}"/><path pathLength="1" d="${d}" stroke="${col}"/>${dots}`, pill];
    });
    for (const key in LP) if (!parts.some(([x]) => x === key)) delete LP[key]; // a line that comes back grows out again
    // one group per line in the line layer, one per label in the label layer above every line
    for (const layer of [L, LB]) for (const g of [...layer.children] as SVGGElement[]) if (!parts.some(([key]) => key === g.dataset.k)) g.remove();
    for (const [key, h, hl] of parts) {
      const st = LP[key], back = h !== null && st?.back;
      if (back) st.back = false;
      for (const [layer, html] of [[L, h], [LB, hl]] as const) {
        let g = ([...layer.children] as SVGGElement[]).find((x) => x.dataset.k === key);
        if (!g) {
          g = document.createElementNS(SVGNS, "g");
          g.dataset.k = key;
          layer.append(g);
        }
        if (html === null) {
          g.setAttribute("class", "out");
          continue;
        }
        if (back) {
          g.setAttribute("class", "in");
          setTimeout(() => g.removeAttribute("class"), 800);
        }
        if (shown.get(g) !== html) (shown.set(g, html), (g.innerHTML = html));
      }
    }
  }
  requestAnimationFrame(draw);
}
