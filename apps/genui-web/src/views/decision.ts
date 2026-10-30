// Decision fork: an amber origin dot with one curve to each option; the AI pick carries a cyan tag.
// Props: q | title, body, url (a link icon), opts [{ k, b, rec, preview }], free (a free-text answer box), pick, done.
// A decision with no options draws no fork: it is answered in words only.
import { body, C, esc, hd, list, title, type View } from "./chrome";

type Opt = { k?: unknown; b?: unknown; rec?: unknown };

const link = (url: unknown) =>
  typeof url === "string" && /^https?:\/\//.test(url)
    ? ` <a class="ib lnk" href="${esc(url)}" target="_blank" rel="noopener noreferrer" aria-label="Open link" title="Open link">↗</a>`
    : "";

function fork(p: Record<string, unknown>, id: string, opts: Opt[]) {
  const n = opts.length,
    done = p.done === true;
  const curves = opts
    .map((o, i) => {
      const y = ((i + 0.5) / n) * 100,
        on = p.pick != null && p.pick === o.k,
        lost = done && !on;
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
  return `<div class="fork"><svg viewBox="0 0 100 100" preserveAspectRatio="none"><path d="M8 50h0" stroke="${C.amber}" stroke-width="14" stroke-linecap="round" vector-effect="non-scaling-stroke"/>${curves}</svg>
<div class="opts">${buttons}</div></div>`;
}

export const decision: View = (p, id, _tier, spec) => {
  const opts = list<Opt>(p.opts),
    done = p.done === true;
  const free =
    p.free === true && !done
      ? `<form class="freef" data-act="answer" data-id="${esc(id)}"><input name="text" maxlength="4000" autocomplete="off" placeholder="Answer in your words" aria-label="Your answer"><button class="send" type="submit">Send</button></form>`
      : "";
  return `${hd(p, id, spec, done ? { text: "decided", cls: "g" } : { text: "needs you" })}${title(esc(p.q ?? p.title) + link(p.url))}${body(p.body)}${
    opts.length ? fork(p, id, opts) : ""
  }${free}`;
};
