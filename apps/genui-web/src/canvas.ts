// The genui web canvas: draws the spec, sends user intents, and keeps the sketch layer on top.
import type { ClientMsg, Component, IntentKind, Rect, ServerMsg, BoardSpec } from "@crewship/genui-spec";
import { Board, MIN_H, MIN_W, safeStyle } from "./model";

const q = new URLSearchParams(location.search);
const boardId = q.get("board") ?? "demo";
const wsUrl = q.get("ws") ?? `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${encodeURIComponent(boardId)}`;
const clientId = crypto.randomUUID();

const $ = <T extends Element>(sel: string) => document.querySelector(sel) as T;
const header = $<HTMLElement>(".top");
const canvas = $<HTMLElement>(".canvas");
const world = $<HTMLElement>(".world");
const links = $<SVGSVGElement>(".links");
const composer = $<HTMLFormElement>(".composer");
const field = $<HTMLInputElement>(".composer input");
const sketch = $<SVGSVGElement>(".sketch");

const board = new Board();
let ws: WebSocket | undefined;
let live = false;
let notice = "";
let pan = { x: 0, y: 0 };
// One gesture at a time; its rect is drawn until the drop sends the intent.
let drag: { id: string; mode: "move" | "resize"; rect: Rect; x0: number; y0: number; r0: Rect } | undefined;
let linking: { from: string; x: number; y: number } | undefined;
const cards = new Map<string, { el: HTMLElement; html: string }>();
const SHELL = new Set(["header", "input"]);
const SVGNS = "http://www.w3.org/2000/svg";

const escHtml = (v: unknown) => String(v ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function send(msg: ClientMsg) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function intent(kind: IntentKind, targetId: string, payload: Record<string, unknown>) {
  if (!live) return paint();
  send(board.propose(kind, targetId, payload));
  paint();
}

function connect(delay = 1000) {
  ws = new WebSocket(wsUrl);
  ws.onopen = () => {
    live = true;
    delay = 1000;
    send({ t: "hello", boardId, clientId });
  };
  ws.onmessage = (e) => {
    // An error shows until the next server message.
    notice = board.receive(JSON.parse(String(e.data)) as ServerMsg) ?? "";
    paint();
  };
  ws.onclose = () => {
    live = false;
    paint();
    setTimeout(() => connect(Math.min(delay * 2, 10_000)), delay);
  };
}

/** Sets a component's safe tokens as CSS variables; style keys never reach plain CSS properties. */
function tokens(el: HTMLElement, c: Component | undefined) {
  el.removeAttribute("style");
  for (const [k, v] of Object.entries(safeStyle(c?.style))) el.style.setProperty(`--${k}`, v);
  el.hidden = c?.props.hidden === true;
}

let rootKeys: string[] = [];
function rootTokens(spec: BoardSpec) {
  const root = document.documentElement.style;
  for (const k of rootKeys) root.removeProperty(`--${k}`);
  const t = safeStyle(spec.tokens);
  for (const [k, v] of Object.entries(t)) root.setProperty(`--${k}`, v);
  rootKeys = Object.keys(t);
}

let headerHtml = "";
function paintHeader(c: Component | undefined) {
  tokens(header, c);
  if (!c) return void (header.hidden = true);
  const wins = c.props.wins === "user" ? "user" : "agent";
  const status = live ? `live · seq <b class="num">${board.seq}</b>` : "reconnecting";
  const html = `<i class="orb${board.pending.size ? " busy" : ""}"></i>
<h1 class="line">${escHtml(c.props.title)}</h1>
<span class="st${live ? " on" : ""}" role="status">${status}${notice ? ` · ${escHtml(notice)}` : ""}</span>
<div class="seg" role="group" aria-label="When you and the agent both move a card">
<button type="button" data-wins="agent" aria-pressed="${wins === "agent"}">agent wins</button>
<button type="button" data-wins="user" aria-pressed="${wins === "user"}">user wins</button></div>`;
  // Rebuild only on change, so a click that spans a repaint still lands on its button.
  if (html !== headerHtml) header.innerHTML = headerHtml = html;
  if (c.rect) Object.assign(header.style, { left: `${c.rect.x}px`, top: `${c.rect.y}px`, width: `${c.rect.w}px`, right: "auto" });
}

function paintInput(c: Component | undefined) {
  tokens(composer, c);
  composer.hidden ||= !c;
  field.placeholder = String(c?.props.placeholder ?? "Ask anything");
  if (c?.rect) Object.assign(composer.style, { left: `${c.rect.x}px`, top: `${c.rect.y}px`, width: `${c.rect.w}px`, bottom: "auto", right: "auto" });
}

function body(spec: BoardSpec, c: Component, depth = 0): string {
  const p = c.props;
  const kpi = p.kpi as { value?: unknown; unit?: unknown } | undefined;
  const steps = p.steps as { items?: unknown[]; at?: number } | undefined;
  let h = "";
  if (kpi) h += `<div class="kpi num">${escHtml(kpi.value)}<small>${escHtml(kpi.unit)}</small></div>`;
  if (Array.isArray(steps?.items))
    h += `<ol class="steps">${steps.items.map((s, i) => `<li class="${i < (steps.at ?? 0) ? "done" : i === steps.at ? "at" : ""}">${escHtml(s)}</li>`).join("")}</ol>`;
  if (p.body) h += `<p>${escHtml(p.body)}</p>`;
  if (Array.isArray(p.items)) h += `<ul class="items">${p.items.map((s) => `<li>${escHtml(s)}</li>`).join("")}</ul>`;
  // Children without their own rect sit inside the parent; depth stops a cycle in a bad spec.
  for (const id of depth < 4 ? (c.children ?? []) : []) {
    const k = spec.components[id];
    if (k && !k.rect) h += `<div class="kid"><b>${escHtml(k.props.title)}</b>${body(spec, k, depth + 1)}</div>`;
  }
  return h;
}

function cardHtml(spec: BoardSpec, c: Component): string {
  const pinned = c.props.pinned === true;
  return `<div class="hd">${c.props.flag ? `<span class="flag">${escHtml(c.props.flag)}</span>` : ""}
<button type="button" class="ib" data-act="pin" aria-pressed="${pinned}" title="${pinned ? "Unpin" : "Pin in place"}">${pinned ? "pinned" : "pin"}</button>
<button type="button" class="ib" data-act="link" title="Drag to another card to link">link</button></div>
<div class="title">${escHtml(c.props.title ?? c.type)}</div>
<div class="core">${body(spec, c)}</div><i class="grip" data-act="resize" aria-hidden="true"></i>`;
}

/** Numbers only: rects come from the agent's spec and end up in SVG markup and styles. */
function rectOf(spec: BoardSpec, id: string): Rect | undefined {
  const r = drag?.id === id ? drag.rect : spec.components[id]?.rect;
  return r && { x: Number(r.x) || 0, y: Number(r.y) || 0, w: Number(r.w) || 0, h: Number(r.h) || 0 };
}

function paintLinks(spec: BoardSpec) {
  // Side by side: right edge to left edge. Stacked (the two overlap in x): bottom edge to top edge.
  const edge = (a: Rect, b: Rect) => {
    if (a.x < b.x + b.w && b.x < a.x + a.w) {
      const [t, u] = a.y <= b.y ? [a, b] : [b, a];
      const x1 = t.x + t.w / 2, y1 = t.y + t.h, x2 = u.x + u.w / 2, y2 = u.y, bend = Math.max(30, (y2 - y1) / 2);
      return `M${x1} ${y1}C${x1} ${y1 + bend} ${x2} ${y2 - bend} ${x2} ${y2}`;
    }
    const [l, r] = a.x <= b.x ? [a, b] : [b, a];
    const x1 = l.x + l.w, y1 = l.y + l.h / 2, x2 = r.x, y2 = r.y + r.h / 2, bend = Math.max(30, (x2 - x1) / 2);
    return `M${x1} ${y1}C${x1 + bend} ${y1} ${x2 - bend} ${y2} ${x2} ${y2}`;
  };
  let h = "";
  for (const l of spec.links) {
    const a = rectOf(spec, l.from), b = rectOf(spec, l.to);
    if (a && b) h += `<path class="case" d="${edge(a, b)}"/><path d="${edge(a, b)}"/>`;
  }
  const a = linking && rectOf(spec, linking.from);
  if (linking && a) h += `<path class="tmp" d="${edge(a, { x: linking.x, y: linking.y, w: 0, h: 0 })}"/>`;
  links.innerHTML = h;
}

let queued = false;
function paint() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => {
    queued = false;
    const spec = board.view();
    rootTokens(spec);
    paintHeader(spec.components.header);
    paintInput(spec.components.input);
    const nested = new Set(Object.values(spec.components).flatMap((c) => c.children ?? []));
    const ids = Object.keys(spec.components).filter((id) => !SHELL.has(id) && !(nested.has(id) && !spec.components[id].rect));
    for (const [id, c] of cards) if (!ids.includes(id)) (c.el.remove(), cards.delete(id));
    for (const id of ids) {
      const c = spec.components[id];
      let card = cards.get(id);
      if (!card) {
        const el = document.createElement("section");
        el.className = "card";
        el.dataset.id = id;
        world.append(el);
        cards.set(id, (card = { el, html: "" }));
      }
      const html = cardHtml(spec, c);
      if (html !== card.html) card.el.innerHTML = card.html = html;
      tokens(card.el, c);
      const r = rectOf(spec, id) ?? { x: 40, y: 40, w: 300, h: 180 };
      Object.assign(card.el.style, { left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px`, height: `${r.h}px` });
      card.el.classList.toggle("held", drag?.id === id);
      card.el.classList.toggle("pinned", c.props.pinned === true);
    }
    paintLinks(spec);
    world.style.transform = `translate(${pan.x}px,${pan.y}px)`;
  });
}

// World coordinates of a pointer event.
const at = (e: PointerEvent) => {
  const b = canvas.getBoundingClientRect();
  return { x: e.clientX - b.left - pan.x, y: e.clientY - b.top - pan.y };
};

let stroke: SVGPolylineElement | undefined;
function startStroke(e: PointerEvent) {
  stroke = document.createElementNS(SVGNS, "polyline");
  stroke.setAttribute("points", `${e.clientX},${e.clientY}`);
  sketch.append(stroke);
}

canvas.addEventListener("pointerdown", (e) => {
  if (e.button !== 0) return;
  const t = e.target as Element;
  if (e.shiftKey) return (canvas.setPointerCapture(e.pointerId), startStroke(e));
  if (t.closest("button:not([data-act=link])")) return;
  const el = t.closest<HTMLElement>(".card");
  const id = el?.dataset.id;
  canvas.setPointerCapture(e.pointerId);
  const p = at(e);
  if (!id) return void (drag = { id: "", mode: "move", rect: { x: pan.x, y: pan.y, w: 0, h: 0 }, x0: e.clientX, y0: e.clientY, r0: { ...pan, w: 0, h: 0 } });
  if (t.closest('[data-act="link"]')) return void (linking = { from: id, ...p });
  const mode = t.closest('[data-act="resize"]') ? "resize" : t.closest(".hd, .title") ? "move" : undefined;
  const r0 = rectOf(board.view(), id);
  if (mode && r0) drag = { id, mode, rect: { ...r0 }, x0: e.clientX, y0: e.clientY, r0 };
});

canvas.addEventListener("pointermove", (e) => {
  if (stroke) return void stroke.setAttribute("points", `${stroke.getAttribute("points")} ${e.clientX},${e.clientY}`);
  if (linking) return (Object.assign(linking, at(e)), paint());
  if (!drag) return;
  const dx = e.clientX - drag.x0, dy = e.clientY - drag.y0, r = drag.r0;
  if (!drag.id) pan = { x: r.x + dx, y: r.y + dy };
  else drag.rect = drag.mode === "move" ? { ...r, x: r.x + dx, y: r.y + dy } : { ...r, w: Math.max(MIN_W, r.w + dx), h: Math.max(MIN_H, r.h + dy) };
  paint();
});

canvas.addEventListener("pointerup", (e) => {
  stroke = undefined;
  if (linking) {
    const to = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>(".card")?.dataset.id;
    const from = linking.from;
    linking = undefined;
    if (to && to !== from) intent("link", from, { to });
    return paint();
  }
  const d = drag;
  drag = undefined;
  if (!d?.id) return;
  const r = d.rect;
  if (r.x !== d.r0.x || r.y !== d.r0.y || r.w !== d.r0.w || r.h !== d.r0.h)
    intent(d.mode, d.id, d.mode === "move" ? { x: r.x, y: r.y } : { w: r.w, h: r.h });
  else paint();
});
canvas.addEventListener("pointercancel", () => ((drag = linking = stroke = undefined), paint()));

world.addEventListener("click", (e) => {
  const b = (e.target as Element).closest<HTMLButtonElement>('button[data-act="pin"]');
  const id = b?.closest<HTMLElement>(".card")?.dataset.id;
  if (id) intent("pin", id, { pinned: b.getAttribute("aria-pressed") !== "true" });
});

header.addEventListener("click", (e) => {
  const wins = (e.target as Element).closest<HTMLElement>("[data-wins]")?.dataset.wins;
  if (wins) intent("input", "header", { field: "wins", value: wins });
});

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = field.value.trim();
  if (!text) return;
  intent("input", "input", { text });
  field.value = "";
});

// The pen turns the whole window into the sketch layer; shift-drag draws without it.
const pen = $<HTMLButtonElement>(".composer .pen");
pen.addEventListener("click", () => pen.setAttribute("aria-pressed", String(document.body.classList.toggle("pen"))));
sketch.addEventListener("pointerdown", (e) => {
  // The sketch covers the pen button while drawing, so a tap on that spot still turns the pen off.
  const b = pen.getBoundingClientRect();
  if (e.clientX >= b.left && e.clientX <= b.right && e.clientY >= b.top && e.clientY <= b.bottom) return pen.click();
  sketch.setPointerCapture(e.pointerId);
  startStroke(e);
});
sketch.addEventListener("pointermove", (e) => stroke && stroke.setAttribute("points", `${stroke.getAttribute("points")} ${e.clientX},${e.clientY}`));
sketch.addEventListener("pointerup", () => (stroke = undefined));

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    sketch.replaceChildren();
    document.body.classList.remove("pen");
    pen.setAttribute("aria-pressed", "false");
  } else if ((e.ctrlKey || e.metaKey) && e.key === "z" && document.activeElement !== field) {
    e.preventDefault();
    send({ t: "undo" });
  }
});

paint();
connect();
