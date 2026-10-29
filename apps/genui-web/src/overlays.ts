// Overlays and gestures over the canvas: selection, the full view window, ink, uploads and hotkeys (design docs/genui/design).
import type { ClientMsg, IntentKind, Rect } from "@crewship/genui-spec";
import type { Board } from "./model";

export type About = { of?: string; ids: string[]; at?: Rect };
export type OverlayCtx = {
  board: Board;
  send(msg: ClientMsg): void;
  intent(kind: IntentKind, targetId: string, payload: Record<string, unknown>): void;
  cam: {
    spreading: boolean;
    cycle(dir: number): void;
    toWorld(clientX: number, clientY: number): { x: number; y: number };
    onChange(fn: (transform: string, k: number) => void): void;
  };
  sel: Set<string>;
  paint(): void;
  html(id: string): string;
  bring(ids: string[]): void;
  about?: () => About;
};

const SVGNS = "http://www.w3.org/2000/svg";
// Controls inside a card keep their own taps; a preview's corner resizes it.
const IA = "button,form,video,audio,input,textarea,select,a,label,.mw";
const esc = (v: unknown) => String(v ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, html = "") =>
  Object.assign(document.createElement(tag), { className: cls, innerHTML: html });
const need = <T extends HTMLElement>(sel: string) => {
  const e = document.querySelector<T>(sel);
  if (!e) throw new Error(`overlays: ${sel} is missing from the shell`);
  return e;
};

/** The file kind decides how its card shows it. HTML is text: a blob frame would run it on this origin. */
export function uploadType(f: { type: string; name: string }) {
  const m = f.type.split("/")[0];
  if (m === "image" || m === "video" || m === "audio") return m;
  if (/^text\/|json|xml/.test(f.type) || /\.(md|txt|csv|log|json|html?)$/i.test(f.name)) return "text";
  if (/pdf/.test(f.type)) return "pdf";
  return "file";
}

/** State the overlay parts share. */
type St = {
  ctx: OverlayCtx;
  body: HTMLElement;
  q: HTMLInputElement;
  bottom: HTMLElement;
  ink: SVGGElement;
  uplw: HTMLElement;
  selbar: HTMLElement;
  full: HTMLElement;
  fc: HTMLElement;
  fb: HTMLElement;
  k: number;
  open?: string;
  addAt?: Rect;
  threads: number;
  shown: string; // the full view's last html; innerHTML reads back normalised, so it cannot be compared
};

export function initOverlays(ctx: OverlayCtx) {
  const st = build(ctx);
  ctx.about = () => ({ of: st.open, ids: [...ctx.sel], at: st.addAt });
  ctx.cam.onChange((transform, scale) => {
    // the world and these layers share the window's origin, so one transform places both
    const transition = getComputedStyle(document.querySelector(".world") ?? st.body).transition;
    for (const e of [st.ink as unknown as HTMLElement, st.uplw]) Object.assign(e.style, { transform, transition });
    st.k = scale;
    st.body.style.setProperty("--k", String(scale));
  });
  wireTaps(st);
  wireFull(st);
  wireInk(st);
  wireUploads(st);
  // capture: runs before the shell's own Esc, so one Esc closes one thing
  addEventListener("keydown", (e) => onKey(st, e), true);
  sync(st);
  return { sync: () => sync(st) };
}

/** Makes the layers S4 owns: ink, uploads, the selection bar and the full view window. */
function build(ctx: OverlayCtx): St {
  const body = document.body;
  const bottom = document.querySelector<HTMLElement>(".bottom") ?? body;
  const inkl = document.createElementNS(SVGNS, "svg");
  inkl.setAttribute("class", "inkl");
  inkl.setAttribute("aria-hidden", "true");
  const ink = document.createElementNS(SVGNS, "g");
  inkl.append(ink);
  const upl = el("div", "upl");
  const uplw = el("div", "uplw");
  upl.append(uplw);
  const selbar = el("div", "selbar", '<b></b><button class="chip" type="button" data-sel="center">Bring to center</button><button class="chip" type="button" data-sel="clear">Clear</button>');
  bottom.append(selbar);
  const full = el(
    "div",
    "full",
    '<div class="fullc"><button class="ib" type="button" aria-label="Close full view">✕</button><div class="core"></div><i class="grip" aria-hidden="true"></i></div>',
  );
  Object.assign(full, { id: "full", role: "dialog", ariaModal: "true", ariaLabel: "Full view" });
  body.append(upl, full, inkl);
  const fc = full.querySelector<HTMLElement>(".fullc")!;
  return { ctx, body, q: need(".composer input[name=ask]"), bottom, ink, uplw, selbar, full, fc, fb: fc.querySelector<HTMLElement>(".core")!, k: 1, threads: 0, shown: "" };
}

const live = (st: St, id: string) => {
  const c = st.ctx.board.view().components[id];
  return c && c.props.removed !== true ? c : undefined;
};

function sync(st: St) {
  const { ctx, selbar, addAt } = st;
  if (st.open && !live(st, st.open)) st.open = undefined;
  const n = ctx.sel.size;
  selbar.classList.toggle("show", n > 0 || !!addAt);
  selbar.querySelector("b")!.textContent = addAt ? "Your drawing" : `${n} selected`;
  selbar.querySelector<HTMLElement>('[data-sel="center"]')!.hidden = !!addAt;
  // the shell sets the other placeholders on paint; only the drawing's is ours
  if (addAt) st.q.placeholder = "Ask about your drawing; the answer lands next to it";
  syncFull(st);
}

function syncFull(st: St) {
  const { ctx, open, fb } = st;
  st.full.classList.toggle("open", !!open);
  st.body.classList.toggle("fullon", !!open);
  if (!open) {
    // the old content stays while the window fades out; the next open replaces it
    if (st.shown) (st.shown = ""), (st.threads = 0), st.fc.removeAttribute("style");
    return;
  }
  // follow-up answers about the open card sit under it, so the talk about it stays in the window
  const comps = ctx.board.view().components;
  const th = Object.keys(comps).filter((id) => comps[id].props.of === open && live(st, id));
  fb.dataset.id = open;
  const html = ctx.html(open) + th.map((id) => `<div class="thr" data-id="${esc(id)}">${ctx.html(id)}</div>`).join("");
  if (html !== st.shown) fb.innerHTML = st.shown = html;
  if (th.length > st.threads) requestAnimationFrame(() => fb.scrollTo({ top: fb.scrollHeight, behavior: "smooth" }));
  st.threads = th.length;
}

const refresh = (st: St) => (st.ctx.paint(), sync(st));

function clear(st: St) {
  st.ctx.sel.clear();
  st.addAt = undefined;
  st.ink.replaceChildren();
  refresh(st);
}

/** Tile data-acts: full view, remove, pin, and any other card action as an input intent. */
function act(st: St, b: HTMLElement, id: string) {
  const { ctx } = st;
  const a = b.dataset.act!;
  if (a === "link") return; // the canvas owns link drags
  if (a === "full") return void ((st.open = id), refresh(st));
  if (a === "drop") {
    ctx.sel.delete(id);
    if (st.open === id) st.open = undefined;
    ctx.intent("input", id, { field: "removed", value: true });
  } else if (a === "pin") ctx.intent("pin", id, { pinned: b.getAttribute("aria-pressed") !== "true" });
  else ctx.intent("input", id, { field: a, value: b.dataset.k ?? true });
  refresh(st);
}

/** Taps: select a tile, double tap brings it in, card buttons act; the selection bar's chips. */
function wireTaps(st: St) {
  const { ctx } = st;
  let down = { x: 0, y: 0 };
  st.selbar.addEventListener("click", (e) => {
    const a = (e.target as Element).closest<HTMLElement>("[data-sel]")?.dataset.sel;
    if (a === "clear") return clear(st);
    if (a !== "center") return;
    const ids = [...ctx.sel];
    ctx.sel.clear();
    ctx.bring(ids);
    refresh(st);
  });
  addEventListener("pointerdown", (e) => (down = { x: e.clientX, y: e.clientY }), true);
  document.addEventListener("click", (e) => {
    if (Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5) return; // the end of a drag, not a tap
    const t = e.target as Element;
    const b = t.closest<HTMLElement>("[data-act]");
    const holder = t.closest<HTMLElement>(".tile[data-id], #full [data-id]");
    if (b && holder) return act(st, b, b.dataset.id ?? holder.dataset.id!);
    const tile = t.closest<HTMLElement>(".world .tile[data-id]");
    if (!tile || t.closest(IA)) return;
    if (!ctx.sel.delete(tile.dataset.id!)) ctx.sel.add(tile.dataset.id!);
    st.addAt = undefined;
    refresh(st);
  });
  document.addEventListener("dblclick", (e) => {
    const t = e.target as Element;
    const tile = t.closest<HTMLElement>(".world .tile[data-id]");
    if (!tile || t.closest(IA)) return;
    ctx.sel.delete(tile.dataset.id!);
    ctx.bring([tile.dataset.id!]);
    refresh(st);
  });
  // an ask about the selection or the drawing takes them with it
  st.q.form?.addEventListener(
    "submit",
    () => {
      if (!st.q.value.trim()) return;
      setTimeout(() => {
        ctx.sel.clear();
        st.addAt = undefined;
        refresh(st);
      });
    },
    true,
  );
}

/** The full view is a window: drag it by any empty spot, resize it from the corner grip, keep it above the ask box. */
function wireFull(st: St) {
  const { full, fc, bottom } = st;
  const close = () => ((st.open = undefined), refresh(st));
  fc.querySelector(".ib")!.addEventListener("click", close);
  let bg = false;
  full.addEventListener("pointerdown", (e) => (bg = e.target === full));
  full.addEventListener("click", (e) => e.target === full && bg && close());
  const tr = () => (fc.style.translate || "0px 0px").split(" ").map((v) => parseFloat(v) || 0);
  let d: { size: boolean; cx: number; cy: number; x: number; y: number; w: number; h: number } | undefined;
  fc.addEventListener("pointerdown", (e) => {
    const size = !!(e.target as Element).closest(".grip");
    if (e.button || (!size && (e.target as Element).closest("button,input,textarea,select,a,label,form,video,audio,iframe,.mw,.media,.opts"))) return;
    const r = fc.getBoundingClientRect(), [x, y] = tr();
    d = { size, cx: e.clientX, cy: e.clientY, x, y, w: r.width, h: r.height };
    fc.setPointerCapture(e.pointerId);
    fc.classList.add("mv");
    e.preventDefault();
  });
  fc.addEventListener("pointermove", (e) => {
    if (!d) return;
    const dx = e.clientX - d.cx, dy = e.clientY - d.cy, r = fc.getBoundingClientRect(), floor = bottom.getBoundingClientRect().top - 8;
    if (d.size) {
      // the window is centred, so a resize shifts it by half the growth, which keeps its top-left corner in place
      const w = Math.max(320, Math.min(innerWidth - 8 - r.left, d.w + dx)), h = Math.max(180, Math.min(floor - r.top, d.h + dy));
      Object.assign(fc.style, { width: `${w}px`, height: `${h}px`, maxHeight: "none", translate: `${d.x + (w - d.w) / 2}px ${d.y + (h - d.h) / 2}px` });
      fc.style.setProperty("--fh", `${Math.max(160, h - 170)}px`);
      return;
    }
    const [x0, y0] = tr(), bx = r.left - x0, by = r.top - y0;
    fc.style.translate = `${Math.max(60 - bx - r.width, Math.min(innerWidth - 60 - bx, d.x + dx))}px ${Math.max(-by, Math.min(floor - by - r.height, d.y + dy))}px`;
  });
  const up = () => ((d = undefined), fc.classList.remove("mv"));
  fc.addEventListener("pointerup", up);
  fc.addEventListener("pointercancel", up);
}

/** The pen or shift-drag draws on the board; the last stroke marks where the next ask lands. */
function wireInk(st: St) {
  const { ctx, body } = st;
  const pen = need<HTMLButtonElement>(".composer .pen");
  let pressed = false;
  let stroke: { pts: number[][]; path: SVGPathElement } | undefined;
  pen.addEventListener("click", () => {
    pressed = !pressed;
    pen.setAttribute("aria-pressed", String(pressed));
    body.classList.toggle("inking", pressed);
  });
  const start = (e: PointerEvent) => {
    const t = e.target as Element;
    if (e.button || !(pressed || e.shiftKey) || !t.closest(".canvas") || t.closest(IA)) return;
    e.stopPropagation(); // the canvas would pan or drag a card instead
    e.preventDefault();
    const p = ctx.cam.toWorld(e.clientX, e.clientY);
    const path = document.createElementNS(SVGNS, "path");
    st.ink.append(path);
    stroke = { pts: [[p.x, p.y]], path };
  };
  const move = (e: PointerEvent) => {
    if (!stroke) return;
    e.stopPropagation();
    const p = ctx.cam.toWorld(e.clientX, e.clientY);
    stroke.pts.push([p.x, p.y]);
    stroke.path.setAttribute("d", `M${stroke.pts.map((pt) => pt.map((v) => v.toFixed(1)).join(" ")).join("L")}`);
  };
  const end = (e: Event) => {
    if (!stroke) return;
    e.stopPropagation();
    const { pts, path } = stroke;
    stroke = undefined;
    if (pts.length < 2) return path.remove();
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]), x = Math.min(...xs), y = Math.min(...ys);
    ctx.sel.clear();
    st.addAt = { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
    refresh(st);
  };
  addEventListener("pointerdown", start, true);
  addEventListener("pointermove", move, true);
  addEventListener("pointerup", end, true);
  addEventListener("pointercancel", end, true);
}

/** The card body for an uploaded file: media plays, text is escaped, a PDF frames, the rest downloads. */
function uploadMedia(f: File, src: string, name: string) {
  const type = uploadType(f);
  if (type === "image") return `<img class="media" src="${src}" alt="${name}">`;
  if (type === "video") return `<video class="media" src="${src}" controls playsinline></video>`;
  if (type === "audio") return `<audio class="media" src="${src}" controls></audio>`;
  if (type === "pdf") return `<iframe class="media" src="${src}" title="${name}"></iframe>`;
  if (type === "text") return '<pre class="txt">Reading…</pre>';
  const size = f.size < 1e6 ? `${Math.ceil(f.size / 1e3)} KB` : `${(f.size / 1e6).toFixed(1)} MB`;
  return `<a class="dl" href="${src}" download="${name}">Download · ${size}</a>`;
}

// shortcut: upload cards live in this tab only (blob URLs), not in the spec; move them into the spec when the wire gets an upload intent.
function upload(st: St, files: FileList) {
  const at = files.length === 1 ? st.addAt : undefined;
  const c = st.ctx.cam.toWorld(innerWidth / 2, innerHeight / 2);
  [...files].forEach((f, i) => {
    const name = esc(f.name);
    const card = el("div", "tile uptile", `<div class="core"><div class="title">${name}</div><div class="hd"><button class="ib" type="button" data-up="drop" aria-label="Remove">✕</button></div>${uploadMedia(f, URL.createObjectURL(f), name)}</div>`);
    // several files sit side by side from the middle of the view, so no card hides another
    const x = at ? at.x + at.w + 24 : c.x - 160 + 340 * i, y = at ? at.y : c.y - 160;
    Object.assign(card.style, { left: `${x}px`, top: `${y}px` });
    st.uplw.append(card);
    if (uploadType(f) === "text") f.text().then((s) => (card.querySelector(".txt")!.textContent = s.slice(0, 20000)));
  });
  st.addAt = undefined;
  refresh(st);
}

/** ＋ or drop anywhere; upload cards remove by ✕ and move by their title, like a pinned card. */
function wireUploads(st: St) {
  const { uplw, body } = st;
  const file = need<HTMLInputElement>("#file");
  uplw.addEventListener("click", (e) => (e.target as Element).closest('[data-up="drop"]')?.closest(".uptile")!.remove());
  uplw.addEventListener("pointerdown", (e) => {
    const t = e.target as Element, card = t.closest<HTMLElement>(".uptile");
    if (!card || !t.closest(".title")) return;
    const x0 = e.clientX, y0 = e.clientY, l = parseFloat(card.style.left), tp = parseFloat(card.style.top);
    const mv = (m: PointerEvent) => Object.assign(card.style, { left: `${l + (m.clientX - x0) / st.k}px`, top: `${tp + (m.clientY - y0) / st.k}px` });
    const up = () => (removeEventListener("pointermove", mv), removeEventListener("pointerup", up));
    addEventListener("pointermove", mv);
    addEventListener("pointerup", up);
  });
  file.addEventListener("change", () => {
    if (file.files?.length) upload(st, file.files);
    file.value = "";
  });
  addEventListener("dragover", (e) => {
    if (!e.dataTransfer?.types.includes("Files")) return;
    e.preventDefault();
    body.classList.add("dropping");
  });
  addEventListener("dragleave", (e) => !e.relatedTarget && body.classList.remove("dropping"));
  addEventListener("drop", (e) => {
    body.classList.remove("dropping");
    if (!e.dataTransfer?.files.length) return;
    e.preventDefault();
    upload(st, e.dataTransfer.files);
  });
}

/** Esc closes the top thing: full view, then log, then selection or drawing, then spread. */
function escape(st: St) {
  if (st.open) return (st.open = undefined), refresh(st);
  if (document.querySelector(".logp.open")) return; // the shell closes its log
  if (st.ctx.sel.size || st.addAt) return clear(st);
  if (st.ctx.cam.spreading) return document.getElementById("spread")?.click();
  (document.activeElement as HTMLElement | null)?.blur();
}

/** The action for a hotkeys-mode key, if it has one. */
function hotkey(st: St, key: string, t: Element): (() => void) | undefined {
  if (key === " ") return t.closest("button") ? undefined : () => document.getElementById("spread")?.click();
  const nav: Record<string, () => void> = {
    "[": () => st.ctx.cam.cycle(-1),
    "]": () => st.ctx.cam.cycle(1),
    "0": () => document.getElementById("recenter")?.click(),
    "/": () => st.q.focus(),
    l: () => need(".logbtn").click(),
    L: () => need(".logbtn").click(),
  };
  return nav[key];
}

/** Hotkeys mode (body.keys): 0 [ ] space / L z; any other letter types into the ask box. */
function onKey(st: St, e: KeyboardEvent) {
  if (e.key === "Escape") return escape(st);
  const t = e.target as Element;
  if (e.altKey || t.closest?.("input,textarea,select")) return;
  const keys = st.body.classList.contains("keys");
  const mod = e.metaKey || e.ctrlKey;
  if (e.key.toLowerCase() === "z" && (mod || keys)) return e.preventDefault(), st.ctx.send({ t: "undo" });
  if (mod) return;
  const run = keys ? hotkey(st, e.key, t) : undefined;
  if (run) return e.preventDefault(), run();
  // any other key goes to the ask box, focused before the key lands so the letter is kept
  if (e.key.length === 1 && e.key !== " ") st.q.focus();
}
