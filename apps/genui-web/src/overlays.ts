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
    home(): void;
    spread(on?: boolean): void;
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
const byId = <T extends HTMLElement>(id: string) => {
  const e = document.getElementById(id);
  if (!e) throw new Error(`overlays: #${id} is missing from the shell`);
  return e as T;
};

/** The file kind decides how its card shows it. HTML is text: a blob frame would run it on this origin. */
export function uploadType(f: { type: string; name: string }) {
  const m = f.type.split("/")[0];
  if (m === "image" || m === "video" || m === "audio") return m;
  if (/^text\/|json|xml/.test(f.type) || /\.(md|txt|csv|log|json|html?)$/i.test(f.name)) return "text";
  if (/pdf/.test(f.type)) return "pdf";
  return "file";
}

export function initOverlays(ctx: OverlayCtx) {
  const body = document.body;
  const q = byId<HTMLInputElement>("q");
  const pen = byId<HTMLButtonElement>("pen");
  const file = byId<HTMLInputElement>("file");
  const bottom = document.querySelector<HTMLElement>(".bottom") ?? body;
  const k = { v: 1 };

  // ---------- ink and uploads: window-wide layers that follow the board camera ----------
  const inkl = document.createElementNS(SVGNS, "svg");
  inkl.setAttribute("class", "inkl");
  inkl.setAttribute("aria-hidden", "true");
  const ink = document.createElementNS(SVGNS, "g");
  inkl.append(ink);
  const upl = el("div", "upl");
  const uplw = el("div", "uplw");
  upl.append(uplw);
  body.append(upl, inkl);
  ctx.cam.onChange((transform, scale) => {
    // the world and these layers share the window's origin, so one transform places both
    const transition = getComputedStyle(document.querySelector(".world") ?? body).transition;
    for (const e of [ink as unknown as HTMLElement, uplw]) Object.assign(e.style, { transform, transition });
    k.v = scale;
    body.style.setProperty("--k", String(scale));
  });

  // ---------- selection bar and full view ----------
  const selbar = el("div", "selbar", '<b></b><button class="chip" type="button" data-sel="center">Bring to center</button><button class="chip" type="button" data-sel="clear">Clear</button>');
  bottom.append(selbar);
  const full = el(
    "div",
    "full",
    '<div class="fullc"><button class="ib" type="button" aria-label="Close full view">✕</button><div class="core"></div><i class="grip" aria-hidden="true"></i></div>',
  );
  Object.assign(full, { id: "full", role: "dialog", ariaModal: "true", ariaLabel: "Full view" });
  body.append(full);
  const fc = full.querySelector<HTMLElement>(".fullc")!;
  const fb = fc.querySelector<HTMLElement>(".core")!;

  let open: string | undefined;
  let addAt: Rect | undefined;
  let pressed = false;
  let stroke: { pts: number[][]; path: SVGPathElement } | undefined;
  let down = { x: 0, y: 0 };
  let threads = 0;
  let shown = ""; // the full view's last html; innerHTML reads back normalised, so it cannot be compared

  ctx.about = () => ({ of: open, ids: [...ctx.sel], at: addAt });

  const live = (id: string) => {
    const c = ctx.board.view().components[id];
    return c && c.props.removed !== true ? c : undefined;
  };

  function sync() {
    if (open && !live(open)) open = undefined;
    const n = ctx.sel.size;
    selbar.classList.toggle("show", n > 0 || !!addAt);
    selbar.querySelector("b")!.textContent = addAt ? "Your drawing" : `${n} selected`;
    selbar.querySelector<HTMLElement>('[data-sel="center"]')!.hidden = !!addAt;
    q.placeholder = addAt
      ? "Ask about your drawing; the answer lands next to it"
      : open
        ? "Ask about this, or tell the AI what to do"
        : n
          ? `Ask about ${n === 1 ? "this item" : `these ${n}`}, or add to them`
          : "Ask anything, tell the AI what to do, ✎ draw or ＋ upload";
    full.classList.toggle("open", !!open);
    body.classList.toggle("fullon", !!open);
    if (!open) {
      // the old content stays while the window fades out; the next open replaces it
      if (shown) (shown = ""), (threads = 0), fc.removeAttribute("style");
      return;
    }
    // follow-up answers about the open card sit under it, so the talk about it stays in the window
    const comps = ctx.board.view().components;
    const th = Object.keys(comps).filter((id) => comps[id].props.of === open && live(id));
    fb.dataset.id = open;
    const html = ctx.html(open) + th.map((id) => `<div class="thr" data-id="${esc(id)}">${ctx.html(id)}</div>`).join("");
    if (html !== shown) fb.innerHTML = shown = html;
    if (th.length > threads) requestAnimationFrame(() => fb.scrollTo({ top: fb.scrollHeight, behavior: "smooth" }));
    threads = th.length;
  }

  const refresh = () => (ctx.paint(), sync());
  const clear = () => {
    ctx.sel.clear();
    addAt = undefined;
    ink.replaceChildren();
    refresh();
  };
  const close = () => ((open = undefined), sync());

  selbar.addEventListener("click", (e) => {
    const a = (e.target as Element).closest<HTMLElement>("[data-sel]")?.dataset.sel;
    if (a === "center") {
      const ids = [...ctx.sel];
      ctx.sel.clear();
      ctx.bring(ids);
      refresh();
    } else if (a === "clear") clear();
  });

  // ---------- taps: select, full view, card actions ----------
  addEventListener("pointerdown", (e) => (down = { x: e.clientX, y: e.clientY }), true);
  document.addEventListener("click", (e) => {
    if (Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5) return; // the end of a drag, not a tap
    const t = e.target as Element;
    const b = t.closest<HTMLElement>("[data-act]");
    const holder = t.closest<HTMLElement>(".tile[data-id], #full [data-id]");
    if (b && holder) {
      const act = b.dataset.act!;
      const id = b.dataset.id ?? holder.dataset.id!;
      if (act === "link") return; // the canvas owns link drags
      if (act === "full") return void ((open = id), sync());
      if (act === "drop") {
        ctx.sel.delete(id);
        if (open === id) open = undefined;
        ctx.intent("input", id, { field: "removed", value: true });
      } else if (act === "pin") ctx.intent("pin", id, { pinned: b.getAttribute("aria-pressed") !== "true" });
      else ctx.intent("input", id, { field: act, value: b.dataset.k ?? true });
      return refresh();
    }
    const tile = t.closest<HTMLElement>(".world .tile[data-id]");
    if (!tile || t.closest(IA)) return;
    const id = tile.dataset.id!;
    if (!ctx.sel.delete(id)) ctx.sel.add(id);
    addAt = undefined;
    refresh();
  });
  document.addEventListener("dblclick", (e) => {
    const t = e.target as Element;
    const tile = t.closest<HTMLElement>(".world .tile[data-id]");
    if (!tile || t.closest(IA)) return;
    ctx.sel.delete(tile.dataset.id!);
    ctx.bring([tile.dataset.id!]);
    refresh();
  });

  // ---------- full view window: drag by any empty spot, resize by the corner grip, stay above the ask box ----------
  fc.querySelector(".ib")!.addEventListener("click", close);
  let bg = false;
  full.addEventListener("pointerdown", (e) => (bg = e.target === full));
  full.addEventListener("click", (e) => e.target === full && bg && close());
  {
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

  // ---------- ink: the pen or shift-drag draws on the board; the last stroke marks where the next ask lands ----------
  pen.addEventListener("click", () => {
    pressed = !pressed;
    pen.setAttribute("aria-pressed", String(pressed));
    body.classList.toggle("inking", pressed);
  });
  addEventListener(
    "pointerdown",
    (e) => {
      const t = e.target as Element;
      if (e.button || !(pressed || e.shiftKey) || !t.closest(".canvas") || t.closest(IA)) return;
      e.stopPropagation(); // the canvas would pan or drag a card instead
      e.preventDefault();
      const p = ctx.cam.toWorld(e.clientX, e.clientY);
      const path = document.createElementNS(SVGNS, "path");
      ink.append(path);
      stroke = { pts: [[p.x, p.y]], path };
    },
    true,
  );
  addEventListener(
    "pointermove",
    (e) => {
      if (!stroke) return;
      e.stopPropagation();
      const p = ctx.cam.toWorld(e.clientX, e.clientY);
      stroke.pts.push([p.x, p.y]);
      stroke.path.setAttribute("d", `M${stroke.pts.map((pt) => pt.map((v) => v.toFixed(1)).join(" ")).join("L")}`);
    },
    true,
  );
  const endStroke = (e: Event) => {
    if (!stroke) return;
    e.stopPropagation();
    const { pts, path } = stroke;
    stroke = undefined;
    if (pts.length < 2) return path.remove();
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]), x = Math.min(...xs), y = Math.min(...ys);
    ctx.sel.clear();
    addAt = { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
    refresh();
  };
  addEventListener("pointerup", endStroke, true);
  addEventListener("pointercancel", endStroke, true);

  // an ask about the selection or the drawing takes them with it
  q.form?.addEventListener(
    "submit",
    () => {
      if (!q.value.trim()) return;
      setTimeout(() => {
        ctx.sel.clear();
        addAt = undefined;
        refresh();
      });
    },
    true,
  );

  // ---------- uploads: ＋ or drop anywhere; each file becomes a card on the board ----------
  // shortcut: upload cards live in this tab only (blob URLs), not in the spec; move them into the spec when the wire gets an upload intent.
  let n = 0;
  function upload(files: FileList) {
    const at = files.length === 1 ? addAt : undefined;
    const c = ctx.cam.toWorld(innerWidth / 2, innerHeight / 2);
    [...files].forEach((f, i) => {
      const type = uploadType(f), src = URL.createObjectURL(f), name = esc(f.name);
      const media =
        type === "image"
          ? `<img class="media" src="${src}" alt="${name}">`
          : type === "video"
            ? `<video class="media" src="${src}" controls playsinline></video>`
            : type === "audio"
              ? `<audio class="media" src="${src}" controls></audio>`
              : type === "pdf"
                ? `<iframe class="media" src="${src}" title="${name}"></iframe>`
                : type === "text"
                  ? '<pre class="txt">Reading…</pre>'
                  : `<a class="dl" href="${src}" download="${name}">Download · ${f.size < 1e6 ? `${Math.ceil(f.size / 1e3)} KB` : `${(f.size / 1e6).toFixed(1)} MB`}</a>`;
      const card = el("div", "tile uptile", `<div class="core"><div class="title">${name}</div><div class="hd"><button class="ib" type="button" data-up="drop" aria-label="Remove">✕</button></div>${media}</div>`);
      // several files sit side by side from the middle of the view, so no card hides another
      const x = at ? at.x + at.w + 24 : c.x - 160 + 340 * i, y = at ? at.y : c.y - 160;
      Object.assign(card.style, { left: `${x}px`, top: `${y}px` });
      card.dataset.up = String(++n);
      uplw.append(card);
      if (type === "text") f.text().then((s) => (card.querySelector(".txt")!.textContent = s.slice(0, 20000)));
    });
    addAt = undefined;
    refresh();
  }
  uplw.addEventListener("click", (e) => {
    const b = (e.target as Element).closest('[data-up="drop"]');
    if (b) b.closest(".uptile")!.remove();
  });
  // an upload card moves by its title, like a pinned card
  uplw.addEventListener("pointerdown", (e) => {
    const t = e.target as Element, card = t.closest<HTMLElement>(".uptile");
    if (!card || !t.closest(".title")) return;
    const x0 = e.clientX, y0 = e.clientY, l = parseFloat(card.style.left), tp = parseFloat(card.style.top);
    const mv = (m: PointerEvent) => Object.assign(card.style, { left: `${l + (m.clientX - x0) / k.v}px`, top: `${tp + (m.clientY - y0) / k.v}px` });
    const up = () => (removeEventListener("pointermove", mv), removeEventListener("pointerup", up));
    addEventListener("pointermove", mv);
    addEventListener("pointerup", up);
  });
  byId("attach").addEventListener("click", () => file.click());
  file.addEventListener("change", () => {
    if (file.files?.length) upload(file.files);
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
    upload(e.dataTransfer.files);
  });

  // ---------- hotkeys ----------
  addEventListener("keydown", (e) => {
    const t = e.target as Element;
    const typing = !!t.closest?.("input,textarea,select");
    const keys = body.classList.contains("keys");
    if (e.key === "Escape") {
      const log = document.querySelector(".logp.open");
      if (open) close();
      else if (log) document.getElementById("logBtn")?.click();
      else if (ctx.sel.size || addAt) clear();
      else if (ctx.cam.spreading) ctx.cam.spread(false);
      else (document.activeElement as HTMLElement | null)?.blur();
      return;
    }
    if (e.key.toLowerCase() === "z" && !e.altKey && (e.metaKey || e.ctrlKey || keys) && !typing) {
      e.preventDefault();
      return ctx.send({ t: "undo" });
    }
    if (e.metaKey || e.ctrlKey || e.altKey || typing) return;
    // any other key goes to the ask box, focused before the key lands so the letter is kept
    const typed = () => e.key.length === 1 && e.key !== " " && q.focus();
    if (!keys) return typed();
    if (e.key === "[" || e.key === "]") ctx.cam.cycle(e.key === "[" ? -1 : 1);
    else if (e.key === "0") ctx.cam.home();
    else if (e.key === " " && !t.closest("button")) (e.preventDefault(), ctx.cam.spread());
    else if (e.key === "/") (e.preventDefault(), q.focus());
    else if (e.key === "l" || e.key === "L") document.getElementById("logBtn")?.click();
    else typed();
  });

  sync();
  return { sync };
}
