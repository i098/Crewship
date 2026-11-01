// Live views of this host: its load, and one crew agent's terminal.
import { esc, hd, list, num, spark, title, wide, type View } from "./chrome";

const COLOR: Record<string, string> = { cpu: "hsl(188 95% 58%)", mem: "hsl(262 92% 70%)", disk: "hsl(38 98% 62%)", net: "hsl(152 72% 56%)" };
const UNIT: Record<string, string> = { cpu: "%", mem: "%", disk: "%", net: " MB/s" };

// Props: series { cpu, mem, disk, net: number[] (0-100) }. No subtext: the numbers are the view.
export const sys: View = (p, id, _tier, spec) => {
  const rows = Object.entries((p.series ?? {}) as Record<string, unknown>).filter(([k]) => k in COLOR);
  const lines = rows
    .map(([k, v], i) => {
      const a = list(v).map((x) => num(x));
      return `<text x="0" y="${i * 36 + 20}" class="m">${k}</text><path d="${spark(a, 50, i * 36 + 2, 250, 26)}" fill="none" stroke="${COLOR[k]}" stroke-width="2"/><text x="400" y="${i * 36 + 24}" text-anchor="end" style="font-size:20px;font-weight:650">${esc(a.at(-1) ?? "")}${UNIT[k]}</text>`;
    })
    .join("");
  return `${hd(p, id, spec, { text: "live", cls: "g" })}${title(esc(p.title ?? "This host"))}<div class="viz"><svg viewBox="0 0 400 ${Math.max(1, rows.length) * 36}">${lines}</svg></div>`;
};

// Props: agent, lines[] (newest last). A narrow card shows the last 8 lines, a wide one 14.
export const tui: View = (p, id, tier, spec) =>
  `${hd(p, id, spec, { text: "live", cls: "g" })}${title(esc(p.agent))}<pre class="term">${esc(list(p.lines).slice(wide(tier) ? -14 : -8).join("\n"))}</pre>`;
