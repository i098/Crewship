// Card chrome shared by every view: safe readers for agent props, the header row, KPI and icons.
// Every string from the spec is escaped here; colours must be plain HSL.
import type { BoardSpec, Component, Project } from "@crewship/genui-spec";

export type Props = Component["props"];
/** narrow: a tile up to 500px; wide: a wider tile; full: the full view window. */
export type WidthTier = "narrow" | "wide" | "full";
export type View = (p: Props, id: string, tier: WidthTier, spec: BoardSpec) => string;

export const esc = (v: unknown) => (v == null ? "" : String(v).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`));
export const num = (v: unknown, d = 0) => (typeof v === "number" && Number.isFinite(v) ? v : d);
export const list = <T = unknown>(v: unknown): T[] => (Array.isArray(v) ? v : []);
const HSL = /^hsl\(\s*\d+(\.\d+)?(deg)?\s+\d+(\.\d+)?%\s+\d+(\.\d+)?%(\s*\/\s*\d*\.?\d+%?)?\s*\)$/;
export const hsl = (v: unknown, d: string) => (typeof v === "string" && HSL.test(v) ? v : d);
export const wide = (tier: WidthTier) => tier !== "narrow";

export const C = {
  ink: "hsl(230 30% 96%)", mute: "hsl(232 12% 64%)", vio: "hsl(262 92% 70%)", cyan: "hsl(188 95% 58%)",
  pink: "hsl(320 90% 66%)", ok: "hsl(152 72% 56%)", amber: "hsl(38 98% 62%)", red: "hsl(0 90% 66%)",
};

export const projectOf = (spec: BoardSpec, p: Props): Project | undefined => {
  const pr = typeof p.proj === "string" ? spec.projects?.[p.proj] : undefined;
  return pr && { name: String(pr.name), hsl: hsl(pr.hsl, C.mute) };
};

/** A big number with its unit: `{ value, unit }`. */
export const kpi = (p: Props) => {
  const k = p.kpi as { value?: unknown; unit?: unknown } | undefined;
  return k && k.value != null ? `${esc(k.value)}<small>${esc(k.unit)}</small>` : "";
};

/** Flag colour: amber by default; g green, r red, c pink, ico a bare icon. */
export type Flag = { text: string; cls?: "" | "g" | "r" | "c" | "ico" };

/**
 * The header row as in the design: project pill (only on a pinned card, which sits outside its cluster),
 * flag, KPI, then bare glyphs ⤢ full view and ✕ remove. Pin and link live in the card's bottom tools.
 */
export function hd(p: Props, id: string, spec: BoardSpec, flag?: Flag, k = "", full = true) {
  const pr = p.pinned === true ? projectOf(spec, p) : undefined;
  const i = esc(id);
  return `<div class="hd">${pr ? `<span class="proj" style="background:${pr.hsl}">${esc(pr.name)}</span>` : ""}${
    flag?.text ? `<span class="flag ${flag.cls ?? ""}">${flag.cls === "ico" ? flag.text : esc(flag.text)}</span>` : ""
  }${k ? `<span class="kpi">${k}</span>` : ""}${tools(i, p.pinned === true)}${
    full ? `<button type="button" class="ib" data-act="full" data-id="${i}" aria-label="Open full view">⤢</button>` : ""
  }<button type="button" class="ib" data-act="drop" data-id="${i}" aria-label="Remove">✕</button></div>`;
}

/** Pin and link sit beside full view and remove in the top row, where the reference places a card's buttons. */
function tools(i: string, pinned: boolean) {
  const pinTip = pinned ? "Unpin" : "Pin in place", linkTip = "Link: drag onto another card";
  return `<span class="tools"><button type="button" class="ib" data-act="pin" data-id="${i}" aria-pressed="${pinned}" aria-label="${pinTip}" title="${pinTip}" data-tip="${pinTip}">${
    pinned ? "◉" : "○"
  }</button><button type="button" class="ib" data-act="link" data-id="${i}" aria-label="${linkTip}" title="${linkTip}" data-tip="${linkTip}">⤳</button></span>`;
}

export const title = (html: string) => `<div class="title">${html}</div>`;

/** Action buttons `[{ k, b, pri }]`; the first `pri` one is filled. */
export const acts = (id: string, items: { k?: unknown; b?: unknown; pri?: unknown }[], act = "act") =>
  items.length
    ? `<div class="acts">${items
        .map((a) => `<button type="button" class="act${a.pri ? " pri" : ""}" data-act="${act}" data-id="${esc(id)}" data-k="${esc(a.k)}">${esc(a.b)}</button>`)
        .join("")}</div>`
    : "";

/** Sparkline path for values 0-100. */
export const spark = (a: number[], x: number, y: number, w: number, h: number) =>
  a.length < 2 ? "" : "M" + a.map((v, i) => `${(x + (i * w) / (a.length - 1)).toFixed(1)} ${(y + h - (Math.max(0, Math.min(100, v)) / 100) * h).toFixed(1)}`).join(" L");

const ic = (d: string, label: string) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="${label}"><title>${label}</title>${d}</svg>`;
const doc = '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>';
export const ICON: Record<string, string> = {
  image: ic('<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>', "image"),
  video: ic('<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10 9l5 3-5 3z"/>', "video"),
  audio: ic('<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>', "audio"),
  site: ic('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>', "site"),
  board: ic('<rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="8" rx="2"/><rect x="3" y="13" width="8" height="8" rx="2"/><rect x="13" y="13" width="8" height="8" rx="2"/>', "board"),
  pdf: ic(doc, "pdf"),
  diagram: ic('<rect x="3" y="4" width="6" height="5" rx="1.5"/><rect x="15" y="4" width="6" height="5" rx="1.5"/><rect x="9" y="15" width="6" height="5" rx="1.5"/><path d="M6 9v3h12V9M12 12v3"/>', "diagram"),
  file: ic(doc, "file"),
};

/** The component's id: its key in the spec (the contract passes the component, not the id). */
export const idOf = (spec: BoardSpec, c: Component) =>
  Object.keys(spec.components).find((k) => spec.components[k] === c) ?? String(c.props.id ?? "");
