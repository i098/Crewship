// Any media in a box: a site, board or pdf (iframe), image, diagram, video, audio, text or a file to download.
// Props: type, title, src, nat ("W/H" of the media), ar ("auto", a preset or "W/H"), text, size (bytes).
import { esc, hd, ICON, num, title, type View } from "./chrome";

const AR = ["auto", "16/9", "4/3", "1/1", "9/16"];

/** Only http(s), blob and same-origin paths load; anything else (javascript:, data:) is dropped. */
const safeSrc = (v: unknown) => {
  const s = String(v ?? "");
  return !/^[a-z][a-z0-9+.-]*:/i.test(s) || /^(https?|blob):/i.test(s) ? esc(s) : "";
};
const ratio = (v: unknown) => (typeof v === "string" && /^\d{1,5}\/\d{1,5}$/.test(v) && !/(^|\/)0+$/.test(v) ? v : "");

const bytes = (n: number) => (n < 1e6 ? Math.ceil(n / 1e3) + " KB" : (n / 1e6).toFixed(1) + " MB");

/** Media with no ratio box: audio, a download, plain text. */
const BARE: Record<string, (src: string, name: string, p: Record<string, unknown>) => string> = {
  audio: (src) => `<audio class="media" src="${src}" controls></audio>`,
  file: (src, name, p) => `<a class="dl" href="${src}" download="${name}">Download · ${bytes(num(p.size))}</a>`,
  text: (_src, _name, p) => `<pre class="txt">${esc(p.text ?? "Reading…")}</pre>`,
};

/** Media inside the ratio box: image, video, or a sandboxed frame for a site, board or pdf. */
function boxed(type: string, src: string, name: string, full: boolean) {
  if (type === "image" || type === "diagram") return `<img class="media" src="${src}" alt="${name}">`;
  if (type === "video") return `<video class="media" src="${src}" autoplay muted loop playsinline${full ? " controls" : ""}></video>`;
  // a foreign site keeps its own origin (a board needs its storage); a same-origin or blob frame never does, or it could escape the sandbox
  const own = /^https?:\/\//i.test(src) && new URL(src).origin !== globalThis.location?.origin ? " allow-same-origin" : "";
  return `<iframe class="media" src="${src}" loading="lazy" title="${name}" sandbox="allow-scripts allow-forms allow-popups${own}"></iframe>`;
}

export const embed: View = (p, id, tier, spec) => {
  const type = String(p.type ?? "site"), src = safeSrc(p.src), name = esc(p.title), i = esc(id);
  const head = `${hd(p, id, spec, { text: ICON[type] ?? ICON.site, cls: "ico" })}${title(name)}`;
  if (Object.hasOwn(BARE, type)) return head + BARE[type](src, name, p);
  const media = boxed(type, src, name, tier === "full");
  const ar = AR.includes(String(p.ar)) ? String(p.ar) : ratio(p.ar) || "auto";
  const [cw, ch] = AR.includes(ar) ? ["", ""] : ar.split("/");
  const shape = ar === "auto" ? ratio(p.nat) || "16/10" : ar, [rw, rh] = shape.split("/").map(Number);
  return `${head}<div class="mw" data-id="${i}" data-ar="${ar}" style="aspect-ratio:${shape};--r:${(rw / rh).toFixed(4)}">${media}</div>
<div class="arbar">${AR.map((a) => `<button type="button" class="${a === ar ? "on" : ""}" data-act="ar" data-id="${i}" data-k="${a}">${a === "auto" ? "Auto" : a.replace("/", ":")}</button>`).join("")}<input class="arw" data-id="${i}" inputmode="numeric" aria-label="Custom width" placeholder="W" value="${cw}">×<input class="arh" data-id="${i}" inputmode="numeric" aria-label="Custom height" placeholder="H" value="${ch}"></div>`;
};
