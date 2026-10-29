// Card fit, run after every layout: no text may run out of its card (the design's layout check, docs/genui/design).
// A title steps its size down until it fits two lines, measured with pretext. Text wider than its box wraps anywhere,
// and what still runs out of the card is cut with an ellipsis. Each run starts over, so a card that grew gets its text back.
import { layout, prepare } from "@chenglou/pretext";

const SIZES = [20, 18, 16, 14];
const sized = new Map<string, number>();

/** The largest title size whose text fits two lines of `width`; `ls` is the letter spacing in em. */
function titleSize(text: string, width: number, weight: string, family: string, ls: number) {
  const key = `${width}|${weight}|${family}|${text}`;
  let s = sized.get(key);
  if (s === undefined) {
    s = SIZES.find((n) => layout(prepare(text, `${weight} ${n}px ${family}`, { letterSpacing: ls * n }), width, n).lineCount <= 2) ?? SIZES.at(-1)!;
    if (sized.size > 500) sized.clear();
    sized.set(key, s);
  }
  return s;
}

function fitTitle(el: HTMLElement) {
  const cs = getComputedStyle(el), ls = parseFloat(cs.letterSpacing) / parseFloat(cs.fontSize) || 0;
  // clientWidth rounds; a pixel less keeps pretext from fitting a line the browser would wrap
  const s = titleSize(el.textContent ?? "", el.clientWidth - 1, cs.fontWeight, cs.fontFamily, ls);
  const size = s === SIZES[0] ? "" : `${s}px`;
  // a write between two cards' reads makes the browser lay out the page again, so write only a change
  if (el.style.fontSize !== size) el.style.fontSize = size;
}

/** Wider than its box, and neither scrolling nor ending in an ellipsis on purpose. */
function wider(e: Element) {
  if (e.scrollWidth <= e.clientWidth + 1) return false;
  const cs = getComputedStyle(e);
  return cs.textOverflow !== "ellipsis" && cs.overflowX !== "auto" && cs.overflowX !== "scroll";
}

const outside = (e: Element, box: DOMRect) => {
  const r = e.getBoundingClientRect();
  return r.width > 0 && (r.left < box.left - 1 || r.right > box.right + 1 || r.top < box.top - 1 || r.bottom > box.bottom + 1);
};

/** The parts of a card's view that run out of their box or the card; SVG insides scale with their viewBox. */
export function overflows(tile: HTMLElement) {
  const box = tile.getBoundingClientRect();
  return [...tile.querySelectorAll<HTMLElement>(".core *")].filter((e) => !e.parentElement?.closest("svg") && (wider(e) || outside(e, box)));
}

/** Fits one card: title size, then wrap, then ellipsis. Returns what still runs out. */
function fitCard(tile: HTMLElement) {
  for (const e of tile.querySelectorAll(".cut")) e.classList.remove("cut");
  const t = tile.querySelector<HTMLElement>(".core > .title");
  if (t) fitTitle(t);
  const bad = overflows(tile);
  if (!bad.length) return bad;
  for (const e of bad) e.classList.add("ovf");
  const still = overflows(tile);
  for (const e of still) e.classList.add("cut");
  return overflows(tile);
}

const fitted = new WeakMap<HTMLElement, string>();

/** Runs after each layout over the cards in `root` whose html or size changed since their last fit; anything it could not fit is logged. */
export function fitCards(root: ParentNode) {
  const left = [...root.querySelectorAll<HTMLElement>(".tile[id]")].filter((t) => {
    // measuring forces layout, so a card is measured again only when its html or drawn size (mid-transition too) changed;
    // a card whose content is skipped off screen waits until it is drawn (the one-second tick fits it then)
    if (t.firstElementChild?.checkVisibility?.({ contentVisibilityAuto: true }) === false) return false;
    const key = `${t.offsetWidth}|${t.offsetHeight}|${(t as HTMLElement & { _html?: string })._html}`;
    if (fitted.get(t) === key) return false;
    const bad = fitCard(t);
    fitted.set(t, key);
    return bad.length;
  });
  if (left.length) console.warn("card fit: text still runs out of", left.map((t) => t.id).join(", "));
  return left.length;
}
