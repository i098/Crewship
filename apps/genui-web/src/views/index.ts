// Card views: one renderer per card kind, driven by the spec. src/canvas.ts is the only caller.
import type { BoardSpec, CardKind, Component } from "@crewship/genui-spec";
import "../cards.css";
import { ask, compare, plan } from "./answer";
import { acts, esc, hd, idOf, list, title, type Props, type View, type WidthTier } from "./chrome";
import { decision } from "./decision";
import { embed } from "./embed";
import { sys, tui } from "./host";
import { crew, shipped, timeline } from "./overview";
import { conflict, incident, pipeline } from "./work";

export type { WidthTier } from "./chrome";
export { dropCard, morph, mountCard, reveal, tickStamps } from "./motion";

const VIEWS: Record<CardKind, View> = { decision, conflict, pipeline, timeline, crew, shipped, plan, embed, incident, compare, ask, sys, tui };

// A component with no known kind: title, body text, a list and optional actions.
const note: View = (p, id, _tier, spec) =>
  `${hd(p, id, spec, p.flag ? { text: String(p.flag) } : undefined)}${title(esc(p.title))}${p.body ? `<p class="body">${esc(p.body)}</p>` : ""}${
    Array.isArray(p.items) ? `<ul class="items">${list(p.items).map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""
  }${Array.isArray(p.acts) ? acts(id, p.acts) : ""}`;

// While you hover a decision option, the cards it changes show that outcome: option.preview = { [cardId]: props }.
let hover: { id: string; k: string } | undefined;
const natural = new Map<string, string>(); // media's own "W/H", learned when it loads

function preview(spec: BoardSpec, id: string): Props | undefined {
  const opt = hover && list<{ k?: unknown; preview?: unknown }>(spec.components[hover.id]?.props.opts).find((o) => o.k === hover?.k);
  const pv = (opt?.preview as Record<string, unknown> | undefined)?.[id];
  return pv && typeof pv === "object" ? (pv as Props) : undefined;
}

/** The inner HTML of one card tile: its view, the resize grip, the live stamp, and the pin and link tools. */
export function renderCard(spec: BoardSpec, component: Component, widthTier: WidthTier = "narrow"): string {
  const id = idOf(spec, component);
  const p: Props = { ...component.props, ...preview(spec, id) };
  if (p.kind === "embed" && !p.nat && natural.has(id)) p.nat = natural.get(id);
  const view = typeof p.kind === "string" && Object.hasOwn(VIEWS, p.kind) ? VIEWS[p.kind as CardKind] : note;
  const i = esc(id), pinned = p.pinned === true;
  const tools = `<span class="tools"><button type="button" class="ib" data-act="pin" data-id="${i}" aria-pressed="${pinned}" aria-label="${pinned ? "Unpin" : "Pin in place"}">${
    pinned ? "◉" : "○"
  }</button><button type="button" class="ib" data-act="link" data-id="${i}" aria-label="Drag to another card to link">⤳</button></span>`;
  return `<div class="core">${view(p, id, widthTier, spec)}</div><i class="tgrip" data-act="resize" aria-hidden="true"></i><span class="ago"></span>${tools}`;
}

/**
 * Card events that change only how cards draw, not the spec: hovering a decision option previews its outcome,
 * and media report their own shape for the "Auto" ratio. `repaint` re-renders the cards.
 */
export function bindCards(root: HTMLElement, repaint: () => void) {
  const set = (next: typeof hover) => {
    if (next?.id === hover?.id && next?.k === hover?.k) return;
    hover = next;
    repaint();
  };
  root.addEventListener("pointerover", (e) => {
    const o = (e.target as Element).closest<HTMLElement>(".opt[data-k]");
    if (o) set({ id: o.dataset.id ?? "", k: o.dataset.k ?? "" });
  });
  root.addEventListener("pointerout", (e) => {
    const o = (e.target as Element).closest(".opt[data-k]");
    if (o && !o.contains(e.relatedTarget as Node | null)) set(undefined);
  });
  const shape = (e: Event) => {
    const m = e.target as HTMLImageElement & HTMLVideoElement, id = (m.closest(".mw") as HTMLElement | null)?.dataset.id;
    const w = m.naturalWidth || m.videoWidth, h = m.naturalHeight || m.videoHeight;
    if (id && w && h && natural.get(id) !== `${w}/${h}`) (natural.set(id, `${w}/${h}`), repaint());
  };
  root.addEventListener("load", shape, true);
  root.addEventListener("loadedmetadata", shape, true);
}
