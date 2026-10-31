// The genui web canvas: draws the spec as the design's project clusters, owns the camera and the card gestures,
// and hands the shell (S1), the card views (S2) and the overlays (S4) one shared context.
import type { BoardSpec, ClientMsg, Component, IntentKind, ServerMsg } from "@crewship/genui-spec";
import { fitCards } from "./fit";
import { CW0, type Item, type Layout, layout, type Move, stepCard } from "./layout";
import { startLinks } from "./links";
import { Board, MIN_H, MIN_W, safeStyle } from "./model";
import { type About, initOverlays } from "./overlays";
import { paintShell } from "./shell";
import { bindCards, dropCard, mountCard, renderCard, tickStamps } from "./views/index";

const q = new URLSearchParams(location.search);
const boardId = q.get("board") ?? "demo";
const wsUrl = q.get("ws") ?? `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${encodeURIComponent(boardId)}`;
const clientId = crypto.randomUUID();

const canvas = document.querySelector<HTMLElement>(".canvas")!;
const world = canvas.querySelector<HTMLElement>(".world")!;
// lines are drawn in screen space, so their layer sits on the canvas, not in the world
const linkSvg = document.querySelector<SVGSVGElement>("svg.links") ?? document.createElementNS("http://www.w3.org/2000/svg", "svg");
linkSvg.setAttribute("class", "links");
canvas.append(linkSvg);
canvas.classList.add("boot");

const SHELL = new Set(["header", "input", "log"]); // the shell draws these; they are never cards
const FALLBACK = "hsl(188 95% 58%)";
const IA = "button,form,video,audio,input,textarea,select,a,.mw";

const board = new Board();
let ws: WebSocket | undefined;
let live = false;
let spec: BoardSpec = board.view();
let L: Layout | undefined;
/** Cluster order you set by dragging cards, and the ask boost that brings cards to the centre. */
const order: Record<string, string[]> = {};
const asked = new Map<string, number>();
/** A size or spot shown while you drag, before the intent lands. */
type Held = { w?: number; h?: number; x?: number; y?: number };
const held = new Map<string, Held>();
const listeners: ((transform: string, k: number) => void)[] = [];

function send(msg: ClientMsg) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function intent(kind: IntentKind, targetId: string, payload: Record<string, unknown>) {
  if (!live) return paint();
  // a card you pin stays where it is on screen now, out of the tiling
  const t = L?.tiles[targetId];
  if (kind === "pin" && payload.pinned === true && t) send(board.propose("move", targetId, { x: t.x, y: t.y }));
  send(board.propose(kind, targetId, payload));
  paint();
}
let sentView: string | null = null; // the cluster the feeder was last told the camera is on

function connect(delay = 1000) {
  ws = new WebSocket(wsUrl);
  ws.onopen = () => {
    live = true;
    delay = 1000;
    send({ t: "hello", boardId, clientId });
  };
  ws.onmessage = (e) => {
    board.receive(JSON.parse(String(e.data)) as ServerMsg);
    paint();
  };
  ws.onclose = () => {
    live = false;
    paint();
    setTimeout(() => connect(Math.min(delay * 2, 10_000)), delay);
  };
}

/** Cards you selected; the overlays draw the selection bar from it. */
const sel = new Set<string>();
const cam = {
  x: 0,
  y: 0,
  k: 1,
  /** True once you pan or zoom; the camera then stops following the layout until you go home. */
  free: false,
  view: null as string | null,
  spreading: false,
  home() {
    Object.assign(cam, { free: false, view: null, spreading: false });
    paint();
  },
  /** Turns the spread view on or off (default: toggle); returns whether it is on. */
  spread(on?: boolean): boolean {
    on ??= !cam.spreading;
    Object.assign(cam, { free: false, spreading: on });
    sel.clear();
    paint();
    return on;
  },
  cycle(dir: number) {
    const o = L?.order ?? [];
    if (!o.length) return;
    cam.open(o[(o.indexOf(L?.front ?? o[0]) + dir + o.length) % o.length]);
  },
  /** Moves the selection one card inside its cluster (keys): the card comes to the front of its stack and into view.
   * `add` (Tab held) keeps the cards already selected, so the walk builds a multi-selection. */
  step(m: Move, add = false) {
    const id = L && stepCard(L, [...sel].at(-1), m);
    if (!id) return;
    if (!add) sel.clear();
    sel.delete(id); // the newest pick is last, so the next step starts from it
    sel.add(id);
    if (L!.tiles[id]?.under) toFront(id);
    const t = L!.tiles[id],
      vp = viewport(),
      sx = (x: number) => (x - cam.x) * cam.k + vp.W / 2,
      sy = (y: number) => (y - cam.y) * cam.k + vp.H / 2;
    const out = sx(t.x) < 0 || sx(t.x + t.w * t.s) > vp.W || sy(t.y) < vp.topH || sy(t.y + t.h * t.s) > vp.H - vp.botH;
    if (out) Object.assign(cam, { free: true, x: t.x + (t.w * t.s) / 2, y: t.y + (t.h * t.s) / 2 });
    paint();
  },
  open(proj: string) {
    Object.assign(cam, { free: false, view: proj, spreading: false });
    sel.clear();
    paint();
  },
  /** Brings cards to the centre for a while: what you asked for holds the centre over new events. */
  bring(ids: string[]) {
    asked.clear();
    ids.forEach((id, i) => asked.set(id, performance.now() + 25_000 - i));
    sel.clear();
    cam.home();
  },
  toWorld(cx: number, cy: number) {
    const r = canvas.getBoundingClientRect();
    return { x: (cx - r.left - r.width / 2) / cam.k + cam.x, y: (cy - r.top - r.height / 2) / cam.k + cam.y };
  },
  onChange(fn: (transform: string, k: number) => void) {
    listeners.push(fn);
  },
};

const ctx = {
  board,
  send,
  intent,
  cam,
  sel,
  paint,
  /** A card's wide view, for the full view window. */
  html: (id: string) => (spec.components[id] ? renderCard(spec, spec.components[id], "wide") : ""),
  bring: cam.bring,
  /** Set by the overlays: what an ask is about (open card, selection, drawn spot). */
  about: undefined as undefined | (() => About),
};

function place() {
  const tx = canvas.clientWidth / 2 - cam.x * cam.k,
    ty = canvas.clientHeight / 2 - cam.y * cam.k;
  const transform = `translate(${tx}px,${ty}px) scale(${cam.k})`;
  world.style.transform = transform;
  world.style.setProperty("--k", String(cam.k));
  // dot spacing repeats every doubling, so zoom never runs out of grid
  const g = 30 * cam.k * 2 ** -Math.floor(Math.log2(cam.k));
  Object.assign(canvas.style, { backgroundPosition: `${tx}px ${ty}px`, backgroundSize: `${g}px ${g}px` });
  for (const fn of listeners) fn(transform, cam.k);
}

const zoomAt = (k2: number, mx: number, my: number) => {
  const r = canvas.getBoundingClientRect(),
    dx = mx - r.left - r.width / 2,
    dy = my - r.top - r.height / 2;
  k2 = Math.max(0.02, Math.min(50, k2));
  cam.x += dx / cam.k - dx / k2;
  cam.y += dy / cam.k - dy / k2;
  cam.k = k2;
  cam.free = true;
  place();
};

/** Sets a component's safe tokens as CSS variables; style keys never reach plain CSS properties. */
function tokens(el: HTMLElement, c: Component) {
  for (const k of [...el.style]) if (k.startsWith("--") && k !== "--s" && k !== "--lk" && k !== "--ring") el.style.removeProperty(k);
  for (const [k, v] of Object.entries(safeStyle(c.style))) el.style.setProperty(`--${k}`, v);
}

let rootKeys: string[] = [];
function rootTokens() {
  const root = document.documentElement.style;
  for (const k of rootKeys) root.removeProperty(`--${k}`);
  const t = safeStyle(spec.tokens);
  for (const [k, v] of Object.entries(t)) root.setProperty(`--${k}`, v);
  rootKeys = Object.keys(t);
}

const colour = (proj: string) => spec.projects?.[proj]?.hsl ?? FALLBACK;
const tierOf = (w: number) => (w > 500 ? "wide" : "narrow");
const tileEl = (id: string) => document.getElementById(`t-${id}`);

// a card's height is read from a hidden copy at the target width, so a card in a move keeps moving
const fits = new Map<string, number>();
let meter: HTMLElement | undefined;
function fit(id: string, w: number) {
  const html = renderCard(spec, spec.components[id], tierOf(w)),
    key = `${id}|${w}|${html}`;
  const hit = fits.get(key);
  if (hit !== undefined) return hit;
  if (!meter) {
    meter = document.createElement("div");
    meter.className = "tile";
    meter.setAttribute("aria-hidden", "true");
    // off screen on purpose, so it must not skip its content the way an off-screen card does
    Object.assign(meter.style, { transition: "none", left: "-99999px", top: "0", visibility: "hidden", contentVisibility: "visible" });
    world.append(meter);
  }
  meter.style.width = `${w}px`;
  meter.innerHTML = html;
  meter.querySelectorAll("iframe,video").forEach((x) => x.replaceWith(Object.assign(document.createElement("div"), { className: x.className })));
  const h = meter.offsetHeight;
  if (fits.size > 500) fits.clear();
  fits.set(key, h);
  return h;
}

// heights read before the card font loaded are the fallback font's, so measure again once it is in
document.fonts?.ready.then(() => (fits.clear(), paint()));

function items(): Item[] {
  const nested = new Set(Object.values(spec.components).flatMap((c) => c.children ?? []));
  const now = performance.now();
  const ts = Object.entries(spec.components)
    .filter(([id, c]) => !SHELL.has(id) && !nested.has(id) && c.props.removed !== true && c.props.aside !== true)
    .map(([id, c]) => item(id, c, now));
  return restack(ts);
}

/** A stack's front card in the plan → the card you brought in front of it. Local: the plan's stack is unchanged. */
const fronted = new Map<string, string>();

/** The cards you brought to the front of their stacks swap places with the plan's front card. */
function restack(ts: Item[]): Item[] {
  for (const [f, x] of fronted) {
    if (ts.find((t) => t.id === x)?.under !== f) {
      fronted.delete(f); // the plan changed the stack
      continue;
    }
    for (const t of ts) if (t.id === f || t.under === f) t.under = t.id === x ? undefined : x;
  }
  return ts;
}

/** Brings a card behind to the front of its stack; its plan front card puts the stack back. */
function toFront(id: string) {
  const f = spec.components[id]?.props.under;
  if (fronted.has(id)) fronted.delete(id);
  else if (typeof f === "string") fronted.set(f, id);
}

// a stack is browsable: a tap on a card behind brings it to the front, a tap on the plan's front card puts it back
document.addEventListener(
  "click",
  (e) => {
    const id = (e.target as Element).closest<HTMLElement>(".world .tile.under[data-id]")?.dataset.id;
    if (!id) return;
    e.stopPropagation();
    e.preventDefault();
    toFront(id);
    paint();
  },
  true,
);

/** A card as the layout sees it: your size and pinned spot win over the spec's, and an ask boost lifts it to the front. */
function item(id: string, c: Component, now: number): Item {
  const p = c.props,
    r = c.rect,
    h = held.get(id);
  const done = p.done === true,
    boost = (asked.get(id) ?? 0) > now ? 200 : 0;
  const size = r || h ? { w: h?.w ?? r?.w, h: h?.h ?? r?.h } : undefined;
  const pin = floats(p) ? (r ? { x: h?.x ?? (Number(r.x) || 0), y: h?.y ?? (Number(r.y) || 0) } : nearSpot(p)) : undefined;
  const plain = {
    id,
    proj: typeof p.proj === "string" ? p.proj : "board",
    prio: done ? 5 : (Number(p.priority) || 0) + boost,
    done,
    pin,
    layer: Number(p.layer) || 0,
  };
  return { ...plain, ...planShape(p, size) };
}

/** A floating window: one you pinned, or one an agent opened with float. It keeps its own spot over any layout. */
const floats = (p: Component["props"]) => p.pinned === true || p.float === true;

/** A window opened about a card (`near`) and not yet moved sits over that card's right part, so its title and first lines show;
 * on a narrow card (a phone) it starts near the left edge so it stays on screen. */
function nearSpot(p: Component["props"]): Item["pin"] {
  const t = typeof p.near === "string" ? L?.tiles[p.near] : undefined;
  return t && { x: Math.max(t.x + 24, t.x + t.w - CW0), y: t.y + 56 };
}

/** Grabbing a floating window brings it to the top of the windows, as `genui-window raise` does. */
function raise(id: string) {
  const layers = Object.values(spec.components)
    .filter((c) => floats(c.props))
    .map((c) => Number(c.props.layer) || 0);
  const mine = Number(spec.components[id]?.props.layer) || 0;
  // another window is level with it or above it
  if (layers.filter((l) => l >= mine).length > 1) intent("input", id, { field: "layer", value: Math.max(...layers) + 1 });
}

/** A plan's shape for a card: l takes a full row, s a narrow column, plus its stack and edge; a size you gave wins. */
function planShape(p: Component["props"], size: Item["size"]): Partial<Item> {
  const stack = { under: typeof p.under === "string" ? p.under : undefined, edge: p.edge === true };
  if (size) return { ...stack, size };
  return { ...stack, wide: p.size === "l", size: p.size === "s" ? { w: 320 } : undefined };
}

function viewport() {
  const top = document.querySelector<HTMLElement>(".top"),
    bottom = document.querySelector<HTMLElement>(".bottom") ?? document.querySelector<HTMLElement>(".composer");
  return {
    W: canvas.clientWidth,
    H: canvas.clientHeight,
    topH: top && !top.hidden ? top.getBoundingClientRect().bottom : 0,
    botH: bottom && !bottom.hidden ? canvas.clientHeight - bottom.getBoundingClientRect().top : 0,
  };
}

function fade(el: Element) {
  el.removeAttribute("id");
  el.classList.add("gone");
  setTimeout(() => el.remove(), 450);
}

function paintClusters(spec: BoardSpec, lay: Layout) {
  for (const b of lay.clusters) {
    let box = document.getElementById(`g-${b.proj}`);
    if (!box) {
      box = document.createElement("div");
      box.id = `g-${b.proj}`;
      box.className = "cluster";
      box.innerHTML = '<div class="cl-hd"></div>';
      world.prepend(box);
    }
    const col = colour(b.proj),
      cs = b.ids.map((id) => spec.components[id].props);
    // a paging card carries how many cards off its page still need him
    const need = cs.reduce((n, p) => n + (p.need && p.done !== true ? 1 : 0) + (typeof p.unseen === "number" ? p.unseen : 0), 0),
      claimed = cs.find((p) => p.claim && p.done !== true)?.claim;
    const say = need
      ? `${need} need${need > 1 ? "" : "s"} you`
      : claimed
        ? `${claimed} is on it`
        : cs.every((p) => p.done === true)
          ? "all done"
          : "nothing needs you";
    const name = spec.projects?.[b.proj]?.name ?? b.proj;
    const hd = `<b style="background:${col}">${esc(name)}</b>${esc(say)}`;
    if (box.firstElementChild!.innerHTML !== hd) box.firstElementChild!.innerHTML = hd;
    box.classList.toggle("away", !b.front);
    box.classList.toggle("r", b.right);
    box.classList.toggle("far", b.far);
    Object.assign(box.style, {
      left: `${b.x}px`,
      top: `${b.y}px`,
      width: `${b.w}px`,
      height: `${b.h}px`,
      zIndex: String(b.z),
      background: `linear-gradient(160deg,${col.replace(")", " / .08)")},hsl(240 30% 100% / .01) 45%,${col.replace(")", " / .04)")})`,
    });
    box.style.setProperty("--s", String(b.s));
    box.style.setProperty("--ring", col);
  }
  // a cluster with nothing left fades out instead of vanishing
  for (const box of world.querySelectorAll(".cluster[id]")) if (!lay.clusters.some((b) => `g-${b.proj}` === box.id)) fade(box);
}

/** Motion order when cards leave (an answer's plan rebuilds the board): the header has already changed, the leaving cards
 * shrink out first, the staying cards move after them, and new cards build in last, so the eye follows to the answer. */
const MOVE_AFTER = 0.35,
  ARRIVE_AFTER = 0.8;
let unstage = 0;

function paintTiles(spec: BoardSpec, lay: Layout) {
  const leaving = [...world.querySelectorAll<HTMLElement>(".tile[id]")].filter((el) => !lay.tiles[el.dataset.id!]);
  const staged = leaving.length > 0 && !matchMedia("(prefers-reduced-motion:reduce)").matches;
  if (staged) clearTimeout(unstage);
  for (const [id, t] of Object.entries(lay.tiles)) {
    const c = spec.components[id];
    let el = tileEl(id);
    if (!el) {
      el = document.createElement("div");
      el.id = `t-${id}`;
      el.className = "tile";
      el.dataset.id = id;
      if (staged) el.style.animationDelay = `${ARRIVE_AFTER}s`;
      world.append(el);
    } else if (staged) el.style.transitionDelay = `${MOVE_AFTER}s`;
    const html = renderCard(spec, c, tierOf(t.w));
    // the first card after boot builds in from a skeleton; later changes morph in place
    if (!el.classList.contains("held")) mountCard(el, html, !canvas.classList.contains("boot"));
    tokens(el, c);
    Object.assign(el.style, { left: `${t.x}px`, top: `${t.y}px`, width: `${t.w}px`, height: `${t.h}px`, zIndex: String(t.z) });
    el.style.setProperty("--s", String(t.s));
    if (t.proj) el.style.setProperty("--ring", colour(t.proj));
    for (const [k, on] of [
      ["away", t.away],
      ["far", t.far],
      ["center", t.center],
      ["sel", sel.has(id)],
      ["done", c.props.done === true],
      ["pinned", c.props.pinned === true],
      ["float", c.props.float === true],
      ["under", t.under === true],
    ] as const)
      el.classList.toggle(k, on);
    // a floating window is capped in height and scrolls, so long context never covers the board or the ask bar
    el.toggleAttribute("data-scrolls", c.props.float === true);
    // a card behind is not usable until its cluster is opened
    el.inert = t.away;
  }
  for (const el of leaving) {
    el.removeAttribute("id");
    dropCard(el);
  }
  // the delays hold for this change only; later changes move at once
  if (staged)
    unstage = window.setTimeout(() => {
      for (const el of world.querySelectorAll<HTMLElement>(".tile")) el.style.transitionDelay = el.style.animationDelay = "";
    }, 1500);
}

const esc = (v: unknown) => String(v ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

let queued = false;
function paint() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => {
    queued = false;
    spec = board.view();
    rootTokens();
    paintShell(spec, ctx); // first: the shell's height sets the camera fit
    for (const id of sel) if (!spec.components[id]) sel.delete(id);
    const picked = new Set([...sel, ...[...asked].filter(([, t]) => t > performance.now()).map(([id]) => id)]);
    const rels = spec.links.map((l) => ({ from: l.from, to: l.to, label: typeof l.label === "string" ? l.label : "" }));
    // a plan keeps cards from several boards, each in its own cluster: all of them show at full size, like the spread view
    const planned = Object.values(spec.components).some((c) => c.props?.aside === true);
    L = layout(items(), rels, viewport(), { view: cam.view, spread: cam.spreading || planned, picked, order }, fit);
    if (cam.view && !L.order.includes(cam.view)) cam.view = null;
    // the feeder loads a cluster's detail only while the camera is on it
    if (cam.view !== sentView && spec.components.header) intent("input", "header", { cluster: (sentView = cam.view) });
    cam.spreading &&= L.spread;
    document.body.classList.toggle("spread", L.spread);
    paintClusters(spec, L);
    paintTiles(spec, L);
    fitCards(world);
    if (!cam.free) Object.assign(cam, L.cam);
    place();
    // first paint lands in place at once; the canvas shows only after it is laid out
    if (canvas.classList.contains("boot") && Object.keys(L.tiles).length)
      requestAnimationFrame(() => requestAnimationFrame(() => canvas.classList.remove("boot")));
    overlays.sync();
  });
}

startLinks(linkSvg, () => ({ lines: L?.lines ?? [], front: L?.front, spread: L?.spread ?? false, k: cam.k, colour }));
new ResizeObserver(() => paint()).observe(canvas);

// ---------- gestures: pan, zoom, card drag, resize, link ----------
const ptr = new Map<number, [number, number]>();
let moved = 0;
type Gesture = { move(e: PointerEvent): void; end(e: PointerEvent): void };
let gesture: Gesture | undefined;
let linkTmp: SVGPathElement | undefined;

function startCard(e: PointerEvent, el: HTMLElement, mode: "size" | "card" | "link") {
  const id = el.dataset.id!,
    t = L!.tiles[id],
    k = cam.k * t.s,
    x0 = e.clientX,
    y0 = e.clientY,
    r0 = el.getBoundingClientRect();
  const pinned = floats(spec.components[id]?.props ?? {});
  if (pinned) raise(id);
  let on = false,
    last: string | undefined;
  gesture = {
    move(ev) {
      const dx = ev.clientX - x0,
        dy = ev.clientY - y0;
      moved = Math.abs(dx) + Math.abs(dy);
      if (!on) {
        if (moved <= 5) return;
        on = true;
        cam.free = true;
        if (mode === "card") el.classList.add("held");
        else if (mode === "size") document.body.classList.add("sizing");
      }
      if (mode === "link") return linkPreview(el, ev);
      if (mode === "size") {
        held.set(id, { ...held.get(id), w: Math.max(MIN_W, t.w + dx / k), h: Math.max(MIN_H, t.h + dy / k) });
        return paint();
      }
      if (pinned) {
        held.set(id, { ...held.get(id), x: t.x + dx / cam.k, y: t.y + dy / cam.k });
        return paint();
      }
      last = swapUnder(id, ev, last);
      const r = el.getBoundingClientRect(),
        [tx, ty] = (el.style.translate || "0px 0px").split(" ").map((v) => parseFloat(v) || 0);
      el.style.translate = `${(r0.left + dx - r.left) / k + tx}px ${(r0.top + dy - r.top) / k + ty}px`;
    },
    end(ev) {
      document.body.classList.remove("sizing");
      el.classList.remove("held");
      el.style.translate = "";
      const h = held.get(id);
      held.delete(id);
      if (!on) return;
      moved = 99;
      drop(id, mode, pinned, h, ev);
    },
  };
}

function linkPreview(el: HTMLElement, ev: PointerEvent) {
  linkTmp ??= linkSvg.appendChild(document.createElementNS("http://www.w3.org/2000/svg", "path"));
  const c = canvas.getBoundingClientRect(),
    r = el.getBoundingClientRect();
  linkTmp.setAttribute("class", "tmp");
  linkTmp.setAttribute("d", `M${r.left + r.width / 2 - c.left} ${r.top + r.height / 2 - c.top}L${ev.clientX - c.left} ${ev.clientY - c.top}`);
}

/** The card under the pointer trades places with the held one `id`; returns the card under the pointer, so one hover swaps once. */
function swapUnder(id: string, ev: PointerEvent, last: string | undefined) {
  const proj = L!.tiles[id].proj!,
    ids = L!.clusters.find((b) => b.proj === proj)!.ids;
  const b = ids.find((o) => {
    if (o === id) return false;
    const r = tileEl(o)?.getBoundingClientRect();
    return !!r && ev.clientX > r.left && ev.clientX < r.right && ev.clientY > r.top && ev.clientY < r.bottom;
  });
  if (b && b !== last) {
    const a = [...ids],
      i = a.indexOf(id),
      j = a.indexOf(b);
    [a[i], a[j]] = [a[j], a[i]];
    order[proj] = a;
    paint();
  }
  return b;
}

/** A gesture's one intent, sent on drop: link, resize or a pinned card's move; a reorder stays local. */
function drop(id: string, mode: "size" | "card" | "link", pinned: boolean, h: Held | undefined, ev: PointerEvent) {
  if (mode === "link") {
    linkTmp?.remove();
    linkTmp = undefined;
    const to = document.elementFromPoint(ev.clientX, ev.clientY)?.closest<HTMLElement>(".tile")?.dataset.id;
    if (to && to !== id) intent("link", id, { to });
  } else if (mode === "size" && h) intent("resize", id, { w: Math.round(h.w!), h: Math.round(h.h!) });
  else if (pinned && h) intent("move", id, { x: Math.round(h.x!), y: Math.round(h.y!) });
  else paint();
}

canvas.addEventListener("pointerdown", (e) => {
  moved = 0;
  // the pen and shift-drag belong to the ink layer
  if (e.button !== 0 || e.shiftKey || document.body.classList.contains("pen")) return;
  const t = e.target as Element,
    el = t.closest<HTMLElement>(".tile:not(.away)");
  const mode = !el
    ? undefined
    : t.closest('[data-act="link"]')
      ? "link"
      : t.closest(".tgrip")
        ? "size"
        : t.closest(".core>.title, .core>.hd") && !t.closest("button")
          ? "card"
          : undefined;
  if (el && mode && L?.tiles[el.dataset.id!]) {
    e.preventDefault();
    return startCard(e, el, mode);
  }
  if (t.closest(IA)) return;
  // no pointer capture: it would retarget the click to the canvas, and taps on cards and clusters need their own target
  ptr.set(e.pointerId, [e.clientX, e.clientY]);
});

addEventListener("pointermove", (e) => {
  if (gesture) return gesture.move(e);
  const p = ptr.get(e.pointerId);
  if (!p) return;
  if (ptr.size === 2) {
    // pinch zooms round the point between the two fingers
    const [a, b] = [...ptr.values()],
      d0 = Math.hypot(a[0] - b[0], a[1] - b[1]);
    ptr.set(e.pointerId, [e.clientX, e.clientY]);
    const [c, d] = [...ptr.values()];
    zoomAt((cam.k * Math.hypot(c[0] - d[0], c[1] - d[1])) / d0, (c[0] + d[0]) / 2, (c[1] + d[1]) / 2);
    moved = 99;
    canvas.classList.add("drag");
    return;
  }
  const dx = e.clientX - p[0],
    dy = e.clientY - p[1];
  ptr.set(e.pointerId, [e.clientX, e.clientY]);
  moved += Math.abs(dx) + Math.abs(dy);
  if (moved > 5) {
    canvas.classList.add("drag");
    cam.x -= dx / cam.k;
    cam.y -= dy / cam.k;
    cam.free = true;
    place();
  }
});

const endPtr = (e: PointerEvent) => {
  if (gesture) {
    const g = gesture;
    gesture = undefined;
    return g.end(e);
  }
  ptr.delete(e.pointerId);
  if (!ptr.size) canvas.classList.remove("drag");
};
addEventListener("pointerup", endPtr);
addEventListener("pointercancel", endPtr);

canvas.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) return zoomAt(cam.k * Math.exp(-e.deltaY * 0.01), e.clientX, e.clientY);
    canvas.classList.add("drag");
    clearTimeout(wheelEnd);
    wheelEnd = window.setTimeout(() => canvas.classList.remove("drag"), 150);
    cam.x += e.deltaX / cam.k;
    cam.y += e.deltaY / cam.k;
    cam.free = true;
    place();
  },
  { passive: false },
);
let wheelEnd = 0;

// a drag must not also count as a tap on what is under the pointer
document.addEventListener("click", (e) => void (moved > 5 && (e.stopPropagation(), e.preventDefault(), (moved = 0))), true);

// a tap on a cluster behind opens it, also where it shows through the glass of the one in front; in spread any cluster opens
canvas.addEventListener("click", (e) => {
  const t = e.target as HTMLElement;
  const behind =
    t.classList.contains("cluster") && !t.classList.contains("away")
      ? [...world.querySelectorAll<HTMLElement>(".cluster.away")]
          .filter((c) => {
            const r = c.getBoundingClientRect();
            return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
          })
          .sort((a, b) => Number(b.style.zIndex) - Number(a.style.zIndex))[0]
      : undefined;
  const g = t.closest<HTMLElement>(".cluster.away") ?? behind ?? (cam.spreading ? t.closest<HTMLElement>(".cluster") : null);
  if (g?.id) cam.open(g.id.slice(2));
});

const overlays = initOverlays(ctx);
bindCards(world, paint);
// the ask: what you typed, plus what it is about (open card, selection, drawn box)
const ask = document.querySelector<HTMLInputElement>(".composer input[name=ask]")!;
ask.form!.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = ask.value.trim();
  if (!text) return;
  intent("input", "input", { text, about: ctx.about?.() });
  ask.value = "";
});
// the tick also re-fits cards whose text arrived after the paint (build-in) or whose size was mid-transition
setInterval(() => (tickStamps(world), fitCards(world)), 1000);
paint();
connect();
