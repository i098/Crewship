// Decision fork: an amber origin dot with one curve to each option; the AI pick carries a cyan tag.
// Props: q | title, body, opts [{ k, b, rec, preview }], pick, done.
import { body, C, esc, hd, list, title, type View } from "./chrome";

type Opt = { k?: unknown; b?: unknown; rec?: unknown };

export const decision: View = (p, id, _tier, spec) => {
  const opts = list<Opt>(p.opts), n = opts.length || 1, done = p.done === true;
  const curves = opts
    .map((o, i) => {
      const y = ((i + 0.5) / n) * 100, on = p.pick != null && p.pick === o.k, lost = done && !on;
      const stroke = on ? C.cyan : lost ? "hsl(0 0% 100% / .1)" : "hsl(38 98% 62% / .7)";
      return `<path class="draw" d="M8 50 C 55 50, 45 ${y}, 100 ${y}" fill="none" stroke="${stroke}" stroke-width="${on ? 3 : 1.6}" vector-effect="non-scaling-stroke" style="animation-delay:${i * 0.15}s"/>`;
    })
    .join("");
  const buttons = opts
    .map((o) => {
      const cls = p.pick != null && p.pick === o.k ? "chosen" : done ? "lost" : o.rec ? "rec" : "";
      return `<button type="button" class="opt ${cls}" data-act="pick" data-id="${esc(id)}" data-k="${esc(o.k)}"><b>${esc(o.b)}</b></button>`;
    })
    .join("");
  return `${hd(p, id, spec, done ? { text: "decided", cls: "g" } : { text: "needs you" })}${title(esc(p.q ?? p.title))}${body(p.body)}
<div class="fork"><svg viewBox="0 0 100 100" preserveAspectRatio="none"><path d="M8 50h0" stroke="${C.amber}" stroke-width="14" stroke-linecap="round" vector-effect="non-scaling-stroke"/>${curves}</svg>
<div class="opts">${buttons}</div></div>`;
};
