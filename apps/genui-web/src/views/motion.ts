// Build-in motion for cards: a dithered skeleton while the AI writes, the box opening out, text decoding
// from glyphs, changes morphing in place, and removed cards shrinking out. Ported from the design.
type Tile = HTMLElement & { _html?: string; _next?: string; _hold?: number };
// The latest run per node: a newer tween or typing run makes the older one stop.
const typing = new WeakMap<Node, object>(), tweens = new WeakMap<Element, Record<string, object>>();

const NUM = /-?\d*\.?\d+/g, GEO = /^(x|y|x1|x2|y1|y2|cx|cy|r|width|height|d|stroke-dasharray|transform)$/;
const reduced = () => matchMedia("(prefers-reduced-motion:reduce)").matches;
const BUILD_MS = 700;
const SKELETON = `<div class="core"><div class="skel"><i></i><i></i><i></i></div></div><i class="tgrip" aria-hidden="true"></i><span class="ago"></span>`;

/** Moves an SVG number attribute (x, d, r…) to its new value over .8s instead of jumping. */
function tween(el: Element, a: string, from: string, to: string) {
  const f = from.match(NUM), g = to.match(NUM);
  if (reduced() || !f || !g || f.length !== g.length || from.replace(NUM, "") !== to.replace(NUM, "")) return el.setAttribute(a, to);
  const parts = to.split(NUM), t0 = performance.now(), id = {}, runs = tweens.get(el) ?? {};
  tweens.set(el, Object.assign(runs, { [a]: id }));
  const step = (n: number) => {
    if (runs[a] !== id) return;
    const k = Math.min(1, (n - t0) / 800), e = 1 - (1 - k) ** 3;
    el.setAttribute(a, parts.map((s, i) => s + (i < g.length ? +(+f[i] + (+g[i] - +f[i]) * e).toFixed(2) : "")).join(""));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/** Types changed text in, two characters a frame. */
function type(node: Node, to: string) {
  const id = {};
  typing.set(node, id);
  let i = 0;
  const tick = () => {
    if (typing.get(node) !== id) return;
    node.nodeValue = to.slice(0, (i += 2));
    if (i < to.length) setTimeout(tick, 18);
  };
  tick();
}

/** A new part wipes in from the left. */
function grow(n: Node) {
  if (!(n instanceof HTMLElement)) return;
  n.classList.add("grow");
  n.addEventListener("animationend", (e) => e.target === n && n.classList.remove("grow"));
}

/** A node with no old counterpart: text types in, an element wipes in. */
function add(a: Node, n: Node) {
  const v = n.nodeValue ?? "";
  a.appendChild(n);
  if (n.nodeType !== 3 || !/\S/.test(v)) return grow(n);
  n.nodeValue = "";
  type(n, v);
}

/** Moves the old element's attributes to the new ones; SVG geometry tweens, a running wipe-in is kept. */
function syncAttrs(o: Element, n: Element) {
  for (const { name } of [...o.attributes]) if (!n.hasAttribute(name)) o.removeAttribute(name);
  for (const { name, value } of [...n.attributes]) {
    const v = o.getAttribute(name);
    if (v === value) continue;
    if (name === "class") o.setAttribute("class", value + (o.classList.contains("grow") ? " grow" : ""));
    else if (o instanceof SVGElement && GEO.test(name) && v != null) tween(o, name, v, value);
    else o.setAttribute(name, value);
  }
}

/** Turns the old node `o` into `n` in place. */
function update(o: ChildNode, n: Node) {
  if (o.nodeType !== n.nodeType || o.nodeName !== n.nodeName) return void (o.replaceWith(n), grow(n));
  const v = n.nodeValue ?? "";
  if (n.nodeType === 3) {
    if (o.nodeValue !== v) /\S/.test(v) && v.length < 90 && !reduced() ? type(o, v) : (o.nodeValue = v);
  } else if (o instanceof Element && n instanceof Element) {
    syncAttrs(o, n);
    patch(o, n);
  }
}

function patch(a: Node, b: Node) {
  const ac = [...a.childNodes], bc = [...b.childNodes];
  bc.forEach((n, i) => (ac[i] ? update(ac[i], n) : add(a, n)));
  ac.slice(bc.length).forEach((o) => o.remove());
}

/** Patches the live DOM toward `html`, so kept parts move and change in place instead of re-appearing. */
export function morph(el: Element, html: string) {
  const t = document.createElement("div");
  t.innerHTML = html;
  patch(el, t);
}

/** Text decodes in from glyphs, left to right (ascii-reveal); `out` scrambles it back. Mono glyphs keep widths fixed. */
export function reveal(root: Node, out = false, ms = BUILD_MS) {
  if (reduced()) return;
  const G = "░▒▓█#%*+=:", ns: { n: Node; s: string; v: string | null }[] = [], t0 = performance.now();
  const g = (s: string) => s.replace(/\S/g, () => G[(Math.random() * G.length) | 0]);
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) if (/\S/.test(w.currentNode.nodeValue ?? "")) ns.push({ n: w.currentNode, s: w.currentNode.nodeValue ?? "", v: null });
  const step = () => {
    const k = (performance.now() - t0) / ms;
    for (const o of ns) {
      if (o.v !== null && o.n.nodeValue !== o.v) continue; // something else wrote this text since
      const m = Math.floor(Math.min(1, k) * o.s.length);
      o.v = o.n.nodeValue = out ? g(o.s.slice(0, m)) + o.s.slice(m) : k >= 1 ? o.s : o.s.slice(0, m) + g(o.s.slice(m));
    }
    if (k < 1) requestAnimationFrame(step);
  };
  step();
}

/** Writes "now", "7s ago" or "building…" into a card's live stamp. */
export function stamp(el: HTMLElement) {
  const t = el as Tile, ago = el.querySelector(":scope > .ago");
  if (!ago) return;
  const s = Math.round((Date.now() - Number(el.dataset.upd ?? Date.now())) / 1000);
  ago.textContent = (t._hold ?? 0) > Date.now() ? "building…" : s < 3 ? "now" : `${s < 60 ? s + "s" : Math.round(s / 60) + "m"} ago`;
}

/** Ticks every card's live stamp; call once a second. */
export const tickStamps = (root: ParentNode) => root.querySelectorAll<HTMLElement>(".tile[data-upd]").forEach(stamp);

/**
 * Paints `html` (from renderCard) into a tile element. The first paint after boot shows a skeleton,
 * opens the box out, then decodes the text in; the world you open with is drawn at once, in place.
 * Later changes morph in place. The stamp records when the view last changed.
 */
export function mountCard(el: HTMLElement, html: string, booted: boolean) {
  const t = el as Tile;
  t._next = html;
  if ((t._hold ?? 0) > Date.now() || t._html === html) return;
  el.classList.add("tile");
  if (t._html === undefined && booted && !reduced()) {
    t._html = "";
    t._hold = Date.now() + BUILD_MS;
    el.innerHTML = SKELETON;
    el.classList.add("born");
    el.addEventListener("animationend", (e) => e.target === el && el.classList.remove("born"));
    setTimeout(() => {
      t._hold = 0;
      el.innerHTML = t._html = t._next ?? "";
      el.dataset.upd = String(Date.now());
      reveal(el.firstChild as Node);
      stamp(el);
    }, BUILD_MS);
    return stamp(el);
  }
  if (t._html === undefined) el.innerHTML = html;
  else morph(el, html);
  t._html = html;
  el.dataset.upd = String(Date.now());
  stamp(el);
}

/** A removed card shrinks back, blurs and fades as one piece, then leaves the DOM. */
export function dropCard(el: HTMLElement) {
  el.classList.add("gone");
  setTimeout(() => el.remove(), 450);
}
