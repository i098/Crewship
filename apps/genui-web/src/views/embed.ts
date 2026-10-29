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

export const embed: View = (p, id, tier, spec) => {
  const type = String(p.type ?? "site"), src = safeSrc(p.src), name = esc(p.title), i = esc(id);
  const icon = { text: ICON[type] ?? ICON.site, cls: "ico" as const };
  const head = `${hd(p, id, spec, icon)}${title(name)}`;
  if (type === "audio") return `${head}<audio class="media" src="${src}" controls></audio>`;
  if (type === "file") {
    const n = num(p.size);
    return `${head}<a class="dl" href="${src}" download="${name}">Download · ${n < 1e6 ? Math.ceil(n / 1e3) + " KB" : (n / 1e6).toFixed(1) + " MB"}</a>`;
  }
  if (type === "text") return `${head}<pre class="txt">${esc(p.text ?? "Reading…")}</pre>`;
  const media =
    type === "image" || type === "diagram"
      ? `<img class="media" src="${src}" alt="${name}">`
      : type === "video"
        ? `<video class="media" src="${src}" autoplay muted loop playsinline${tier === "full" ? " controls" : ""}></video>`
        : `<iframe class="media" src="${src}" loading="lazy" title="${name}" sandbox="allow-scripts allow-forms allow-popups"></iframe>`;
  const ar = AR.includes(String(p.ar)) ? String(p.ar) : ratio(p.ar) || "auto";
  const [cw, ch] = AR.includes(ar) ? ["", ""] : ar.split("/");
  const shape = ar === "auto" ? ratio(p.nat) || "16/10" : ar, [rw, rh] = shape.split("/").map(Number);
  return `${head}<div class="mw" data-id="${i}" data-ar="${ar}" style="aspect-ratio:${shape};--r:${(rw / rh).toFixed(4)}">${media}</div>
<div class="arbar">${AR.map((a) => `<button type="button" class="${a === ar ? "on" : ""}" data-act="ar" data-id="${i}" data-k="${a}">${a === "auto" ? "Auto" : a.replace("/", ":")}</button>`).join("")}<input class="arw" data-id="${i}" inputmode="numeric" aria-label="Custom width" placeholder="W" value="${cw}">×<input class="arh" data-id="${i}" inputmode="numeric" aria-label="Custom height" placeholder="H" value="${ch}"></div>`;
};
