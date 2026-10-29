// Views of work in flight: a merge conflict, a pipeline, an incident being fixed.
import { C, acts, esc, hd, ICON, kpi, list, num, title, wide, type View } from "./chrome";

// Props: title, doneTitle, files[], branch, done (merged). Actions send data-act="merge" with k = ai | theirs | mine.
export const conflict: View = (p, id, tier, spec) => {
  const merged = p.done === true, files = list(p.files);
  const g = "hsl(232 12% 64%)";
  const chips = merged
    ? ""
    : `<div class="files">${
        wide(tier) ? files.map((f) => `<span class="file">${ICON.file}${esc(f)}</span>`).join("") : `<span class="file">${ICON.file}${files.length} files clash</span>`
      }</div>`;
  const choices = [
    { k: "ai", b: "Keep both", pri: true },
    { k: "theirs", b: "Take main" },
    { k: "mine", b: "Keep mine" },
  ];
  return `${hd(p, id, spec, merged ? { text: "merged", cls: "g" } : { text: "needs you" })}${title(esc(merged ? (p.doneTitle ?? p.title) : p.title))}
<div class="viz"><svg viewBox="0 0 400 130" preserveAspectRatio="xMidYMid meet">
<path class="draw" d="M10 65 H120 C160 65 160 25 200 25 H${merged ? "300" : "250 C280 25 280 65 294 65"}" fill="none" stroke="${g}" stroke-width="2.5"/>
<path class="draw" d="M120 65 C160 65 160 105 200 105 H${merged ? "260 C 290 105 290 65 330 65 H390" : "250 C280 105 280 65 294 65"}" fill="none" stroke="${C.vio}" stroke-width="2.5" style="animation-delay:.2s"/>
${
  merged
    ? `<path class="draw" d="M300 25 C 315 25 315 65 330 65" fill="none" stroke="${g}" stroke-width="2.5"/><circle cx="330" cy="65" r="7" fill="${C.ok}"/><text x="345" y="55" class="m">merged</text>`
    : `<circle cx="314" cy="65" r="18" fill="hsl(38 98% 62% / .15)" stroke="${C.amber}" stroke-width="2"/><text x="314" y="72" text-anchor="middle" style="font-size:20px;font-weight:800;fill:${C.amber}">!</text><text x="342" y="70" class="m" style="fill:${C.amber}">${files.length} files</text>`
}
${[40, 80, 212, 240].map((x) => `<circle cx="${x}" cy="${x < 120 ? 65 : 25}" r="4.5" fill="${g}"/>`).join("")}${[212, 240].map((x) => `<circle cx="${x}" cy="105" r="4.5" fill="${C.vio}"/>`).join("")}
<text x="200" y="14" class="m">main</text><text x="200" y="127" class="m">${esc(p.branch ?? "yours")}</text>
</svg></div>${chips}${merged ? "" : acts(id, choices, "merge")}`;
};

// Props: title, stages[], at (current stage index), kpi, done. Only the current stage is labelled until the card is wide.
export const pipeline: View = (p, id, tier, spec) => {
  const st = list(p.stages).map(String), done = p.done === true;
  const k = Math.max(0, Math.min(num(p.at), st.length - 1)), W = 400, step = (W - 40) / Math.max(1, st.length - 1);
  const dots = st
    .map((s, i) => {
      const x = 20 + step * i;
      const fill = i < k ? C.ok : i === k ? C.cyan : "hsl(240 20% 14%)";
      return `<circle cx="${x}" cy="45" r="${i === k ? 10 : 7}" fill="${fill}" stroke="${i > k ? "hsl(0 0% 100% / .2)" : "none"}"/>${
        wide(tier) || i === k ? `<text x="${x}" y="78" text-anchor="middle" class="${i === k ? "" : "m"}">${esc(s)}</text>` : ""
      }`;
    })
    .join("");
  const now = done ? "merged" : esc((st[k] ?? "").toLowerCase());
  return `${hd(p, id, spec, done ? { text: "merged", cls: "g" } : undefined, done ? "" : kpi(p))}${title(`${esc(p.title)}: ${now}`)}
<div class="viz"><svg viewBox="0 0 ${W} 90" preserveAspectRatio="xMidYMid meet">
<defs><linearGradient id="pg-${esc(id)}"><stop offset="0" stop-color="${C.ok}"/><stop offset="1" stop-color="${C.cyan}"/></linearGradient></defs>
<line x1="20" y1="45" x2="${W - 20}" y2="45" stroke="hsl(0 0% 100% / .1)" stroke-width="6" stroke-linecap="round"/>
<line x1="20" y1="45" x2="${20 + step * k}" y2="45" stroke="url(#pg-${esc(id)})" stroke-width="6" stroke-linecap="round" class="draw"/>
${dots}</svg></div>`;
};

// Props: title, doneTitle, claim, att (fix attempt 1-3), fix { from, to }, done (fixed).
export const incident: View = (p, id, _tier, spec) => {
  const fixed = p.done === true, att = num(p.att, 1), pct = fixed ? 1 : Math.min(0.9, att * 0.3);
  const fix = (p.fix ?? {}) as { from?: unknown; to?: unknown };
  const flag = fixed ? { text: "fixed", cls: "g" as const } : p.claim ? { text: `claimed · ${p.claim}`, cls: "c" as const } : { text: "failing", cls: "r" as const };
  return `${hd(p, id, spec, flag)}${title(esc(fixed ? (p.doneTitle ?? p.title) : p.title))}
<div class="viz"><svg viewBox="0 0 400 150" preserveAspectRatio="xMidYMid meet">
<circle cx="80" cy="75" r="30" fill="none" stroke="hsl(0 0% 100% / .1)" stroke-width="6"/>
<circle cx="80" cy="75" r="30" fill="none" stroke="${fixed ? C.ok : C.red}" stroke-width="6" stroke-linecap="round" stroke-dasharray="${(188 * pct).toFixed(1)} 188" transform="rotate(-90 80 75)" style="transition:stroke-dasharray .8s var(--spring)"/>
<text x="80" y="80" text-anchor="middle" style="font-size:15px;font-weight:600">${fixed ? "✓" : Math.round(pct * 100) + "%"}</text>
${fixed ? "" : [1, 2, 3].map((i) => `<circle cx="${60 + (i - 1) * 20}" cy="132" r="5" fill="${i <= att ? C.pink : "hsl(0 0% 100% / .12)"}"/>`).join("")}
<rect x="140" y="45" width="250" height="60" rx="10" fill="hsl(240 30% 2% / .6)"/>
<text x="152" y="68" style="fill:${C.red}">− ${esc(fix.from)}</text>
<text x="152" y="90" style="fill:${C.ok}">${fixed && fix.to ? `+ ${esc(fix.to)}` : "+ …writing fix"}</text>
</svg></div>`;
};
