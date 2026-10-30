// The shell around the canvas: header line, stats and terminal pills, hint, chips, ask bar, up-next queue and action log.
// Everything here comes from the spec; canvas.ts calls paintShell on every paint.
import type { BoardSpec, ClientMsg, Component, IntentKind } from "@crewship/genui-spec";
import { safeStyle, type Board } from "./model";

export type ShellCtx = {
  board: Board;
  send: (msg: ClientMsg) => void;
  intent: (kind: IntentKind, targetId: string, payload: Record<string, unknown>) => void;
  cam: { home(): void; spread(): boolean; bring(ids: string[]): void; free: boolean; view: string | null; spreading: boolean; onChange(fn: () => void): void };
  sel: Set<string>;
  /** What an ask is about (set by the overlays). */
  about?: () => unknown;
};

type LogItem = { at?: number; text?: string; proj?: string; seq?: number; rwd?: boolean };

const $ = <T extends Element>(sel: string) => document.querySelector(sel) as T;
const esc = (v: unknown) => String(v ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const DOT = "hsl(48 96% 60%)"; // the design's "you added" colour, for a row with no project
const SYSC: Record<string, string> = { cpu: "hsl(188 95% 58%)", mem: "hsl(262 92% 70%)", disk: "hsl(38 98% 62%)", net: "hsl(152 72% 56%)" };
const UNIT: Record<string, string> = { net: " MB/s" };
const NAV = {
  keys: ["⌨ hotkeys", "0 back to what matters · space all boards · [ ] other clusters · / ask · z rewind · L log · esc close · shift-drag to draw · drop files to upload"],
  buttons: ["☝ buttons", "tap to select · ⊞ all boards · ✎ to draw · ＋ to upload · drag to move · pinch to zoom · rewind in log"],
} as const;

let ctx: ShellCtx;
let spec: BoardSpec;
const memo = new Map<Element, string>();
/** Writes markup only on change, so a tap that spans a repaint still lands and animations do not restart. */
const put = (el: Element, html: string) => memo.get(el) !== html && (memo.set(el, html), (el.innerHTML = html));

/** "*Needs you:* Store swaps … *+2 more* need you." → words that slide in; starred runs are amber. */
export function lineHtml(s: string): string {
  let em = false;
  return s.split(" ").map((w, i) => {
    const start = w.startsWith("*");
    if (start) em = true;
    const word = esc(w.replace(/\*/g, ""));
    const out = `<span class="w" style="animation-delay:${i * 30}ms">${em ? `<em>${word}</em>` : word}</span>`;
    if (w.slice(+start).includes("*")) em = false;
    return out;
  }).join(" ");
}

const spark = (a: number[]) => "M" + a.map((v, i) => `${((i * 38) / Math.max(1, a.length - 1)).toFixed(1)} ${(13 - (v / 100) * 12).toFixed(1)}`).join(" L");
// Project colours come from the agent and land in a style attribute, so they pass the same filter as tokens.
const projHsl = (p: unknown) => safeStyle({ c: spec.projects?.[String(p)]?.hsl }).c ?? DOT;
const mmss = (s: number) => `${String((s / 60) | 0).padStart(2, "0")}:${String(s % 60 | 0).padStart(2, "0")}`;

function tokens(el: HTMLElement, c: Component | undefined) {
  el.removeAttribute("style");
  for (const [k, v] of Object.entries(safeStyle(c?.style))) el.style.setProperty(`--${k}`, v);
  el.hidden = !c || c.props.hidden === true;
  // A spec rect undocks the header or the ask bar to where the agent put it.
  const r = c?.rect;
  if (r) Object.assign(el.style, { position: "fixed", left: `${Number(r.x) || 0}px`, top: `${Number(r.y) || 0}px`, width: `${Number(r.w) || 0}px`, right: "auto", bottom: "auto" });
}

function paintHeader(c: Component | undefined) {
  const top = $<HTMLElement>(".top");
  tokens(top, c);
  if (!c) return;
  $(".orb").classList.toggle("busy", ctx.board.pending.size > 0);
  follow();
  const stats = (c.props.stats ?? {}) as Record<string, number[]>;
  const tuis = (Array.isArray(c.props.tuis) ? c.props.tuis : []) as { name: string; proj?: string }[];
  // Pills are built once per set; a tick only moves the sparkline and the number.
  const box = $(".stats");
  const sig = JSON.stringify([Object.keys(stats), tuis]);
  if (box.getAttribute("data-sig") !== sig) {
    box.setAttribute("data-sig", sig);
    box.innerHTML =
      Object.keys(stats).map((k) => `<button type="button" class="st" data-sys="${esc(k)}"><b>${esc(k)}</b><svg viewBox="0 0 38 14"><path fill="none" stroke="${SYSC[k] ?? "var(--cyan)"}" stroke-width="1.5"/></svg><span class="sn"></span>${UNIT[k] ?? "%"}</button>`).join("") +
      tuis.map((t, i) => `<button type="button" class="st${i ? "" : " gap"}" data-tui="${esc(t.name)}"><i style="background:${esc(projHsl(t.proj))}"></i>${esc(t.name)}</button>`).join("");
  }
  for (const [k, a] of Object.entries(stats)) {
    const b = box.querySelector(`[data-sys="${CSS.escape(k)}"]`);
    if (!b || !Array.isArray(a) || !a.length) continue;
    b.querySelector("path")!.setAttribute("d", spark(a.slice(-12).map(Number)));
    b.querySelector(".sn")!.textContent = String(a.at(-1));
  }
  const wins = c.props.wins === "user" ? "user" : "agent";
  put($(".wins"), `<b>wins</b><span>${wins}</span>`);
  $(".wins").setAttribute("aria-label", `${wins} wins a move; tap for ${wins === "user" ? "agent" : "user"} wins`);
}

/** Runs after every layout and camera move: the line speaks for the centre card (design say()), and ◎ is off while you are home. */
function follow() {
  const { cam } = ctx;
  $<HTMLButtonElement>("#recenter").disabled = !(cam.free || cam.view || cam.spreading);
  const id = document.querySelector<HTMLElement>(".tile[id].center")?.dataset.id;
  const line = id && spec.components[id]?.props.line;
  if (typeof line !== "string") return setLine(String(spec.components.header?.props.title ?? ""));
  const more = Object.entries(spec.components).filter(([k, c]) => k !== id && c.props.need === true && c.props.done !== true && c.props.removed !== true).length;
  setLine(line + (more ? ` *+${more} more* need${more > 1 ? "" : "s"} you.` : ""));
}

/** The line stays one row with an ellipsis; hover shows the full text, a tap opens it in a popover. */
function setLine(s: string) {
  const el = $<HTMLElement>(".line");
  if (put(el, lineHtml(s)) === false) return;
  el.title = s.replace(/\*/g, "");
  if ($(".linep").matches(":popover-open")) $(".linep").innerHTML = el.innerHTML;
}

function showLine(open: boolean) {
  const p = $<HTMLElement>(".linep");
  if (open) p.innerHTML = $(".line").innerHTML;
  p.togglePopover(open);
}

let folded = false;
function setFold(f: boolean) {
  folded = f;
  try { localStorage.setItem("genui-pills", f ? "folded" : "open"); } catch {}
  $(".top").classList.toggle("folded", f);
  const b = $(".fold");
  b.textContent = f ? "›" : "‹";
  b.setAttribute("aria-expanded", String(!f));
  b.setAttribute("aria-label", f ? "Show the pills" : "Hide the pills");
}

function paintBottom(input: Component | undefined) {
  const form = $<HTMLFormElement>(".composer");
  tokens(form, input);
  const chips = Array.isArray(input?.props.chips) ? input.props.chips : [];
  put($(".chips"), chips.map((t) => `<button type="button" class="chip">${esc(t)}</button>`).join(""));
  const n = ctx.sel.size;
  $<HTMLInputElement>(".composer input[name=ask]").placeholder = document.body.classList.contains("fullon")
    ? "Ask about this, or tell the AI what to do"
    : n ? `Ask about ${n === 1 ? "this item" : `these ${n}`}, or add to them`
    : String(input?.props.placeholder ?? "Ask anything, tell the AI what to do, ✎ draw or ＋ upload");
}

/** Up next: decisions waiting on you, claimed work, then what lands next; oldest left, new ones slide in from the right. */
function paintQueue() {
  const items: [key: string, id: string, kind: string, text: string][] = [];
  const live = Object.entries(spec.components).filter(([, c]) => !c.props.hidden && !c.props.done && c.props.removed !== true);
  for (const [id, c] of live) if (c.props.need) items.push([`n${id}`, id, "decide", `Decide: ${c.props.q ?? c.props.title ?? id}`]);
  for (const [id, c] of live) if (c.props.claim) items.push([`c${id}`, id, "claimed", `${c.props.claim} claimed: ${c.props.title ?? id}`]);
  for (const [id, c] of live) if (typeof c.props.next === "string") items.push([`x${id}${c.props.next}`, id, "next", c.props.next]);
  const q = $(".queue"), keys = new Set(items.map((i) => i[0]));
  for (const e of q.querySelectorAll<HTMLElement>(".qi:not(.out)"))
    if (!keys.has(e.dataset.k!)) (e.classList.add("out"), setTimeout(() => e.remove(), 650));
  for (const [key, id, kind, text] of items) {
    if (q.querySelector(`.qi[data-k="${CSS.escape(key)}"]:not(.out)`)) continue;
    const e = document.createElement("button");
    e.type = "button";
    e.className = `qi ${kind}`;
    Object.assign(e.dataset, { k: key, id });
    e.innerHTML = `<i></i>${esc(text)}`;
    q.append(e);
  }
}

function paintLog() {
  const items = (spec.components.log?.props.items ?? []) as LogItem[];
  $(".logbtn .num").textContent = String(items.length);
  if (!$(".logp").classList.contains("open")) return;
  put($(".logp ol"), items.map((e) =>
    `<li${e.rwd ? ' class="rwd"' : ""}><time>${mmss(Number(e.at) || 0)}</time><i style="background:${esc(projHsl(e.proj))}"></i><span>${esc(e.text)}</span>${typeof e.seq === "number" && !e.rwd ? `<button type="button" class="rw" data-rw="${e.seq}">↶ rewind</button>` : ""}</li>`).reverse().join(""));
}

let nav: keyof typeof NAV;
function setNav(m: keyof typeof NAV) {
  nav = m;
  try { localStorage.setItem("genui-nav", m); } catch {} // storage throws in a sandboxed frame; the choice then lasts for the page
  document.body.classList.toggle("keys", m === "keys");
  $(".nav").textContent = NAV[m][0];
  $(".hint").textContent = NAV[m][1];
}

function toggleLog(open = !$(".logp").classList.contains("open")) {
  $(".logp").classList.toggle("open", open);
  $(".logbtn").setAttribute("aria-expanded", String(open));
  paintLog();
}

function bind() {
  let saved: string | null = null;
  try { saved = localStorage.getItem("genui-nav"); } catch {}
  setNav(saved === "keys" || saved === "buttons" ? saved : matchMedia("(pointer: fine)").matches ? "keys" : "buttons");
  $(".nav").addEventListener("click", () => setNav(nav === "keys" ? "buttons" : "keys"));
  let pills: string | null = null;
  try { pills = localStorage.getItem("genui-pills"); } catch {}
  setFold(pills === "folded");
  $(".fold").addEventListener("click", () => setFold(!folded));
  $(".line").addEventListener("click", () => showLine(!$(".linep").matches(":popover-open")));
  addEventListener("pointerdown", (e) => !(e.target as Element).closest?.(".line, .linep") && showLine(false));
  addEventListener("keydown", (e) => e.key === "Escape" && showLine(false));
  $(".wins").addEventListener("click", () => ctx.intent("input", "header", { field: "wins", value: spec.components.header?.props.wins === "user" ? "agent" : "user" }));
  // A tap on a stat or a terminal asks for a live view of it.
  $(".stats").addEventListener("click", (e) => {
    const b = (e.target as Element).closest<HTMLElement>(".st");
    const tui = b?.dataset.tui;
    if (b) ctx.intent("input", "header", tui ? { text: `Open the ${tui} terminal`, open: `tui-${tui}` } : { text: "Open host stats", open: "sys" });
  });
  $(".logbtn").addEventListener("click", () => toggleLog());
  $(".logx").addEventListener("click", () => toggleLog(false));
  $(".logp ol").addEventListener("click", (e) => {
    const seq = (e.target as Element).closest<HTMLElement>(".rw")?.dataset.rw;
    if (seq) ctx.intent("input", "log", { rewind: Number(seq) });
  });
  addEventListener("keydown", (e) => e.key === "Escape" && $(".logp").classList.contains("open") && toggleLog(false));
  $(".chips").addEventListener("click", (e) => {
    const c = (e.target as Element).closest(".chip");
    if (c) ctx.intent("input", "input", { text: c.textContent, about: ctx.about?.() });
  });
  $(".queue").addEventListener("click", (e) => {
    const id = (e.target as Element).closest<HTMLElement>(".qi")?.dataset.id;
    if (id && spec.components[id]) ctx.cam.bring([id]);
  });
  $("#attach").addEventListener("click", () => $<HTMLInputElement>("#file").click());
  $("#recenter").addEventListener("click", () => ctx.cam.home());
  ctx.cam.onChange(follow);
  $("#spread").addEventListener("click", () => $("#spread").setAttribute("aria-pressed", String(ctx.cam.spread())));
}

export function paintShell(s: BoardSpec, c: ShellCtx) {
  const first = !ctx;
  ctx = c;
  spec = s;
  if (first) bind();
  paintHeader(s.components.header);
  paintBottom(s.components.input);
  paintQueue();
  paintLog();
}
