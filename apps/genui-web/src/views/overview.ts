// Overview views across projects: when things land, who is working, what shipped.
import { body, C, esc, hd, hsl, list, num, title, wide, type View } from "./chrome";

type Row = { name?: unknown; hsl?: unknown; from?: unknown; len?: unknown };

// Props: subject, ship (e.g. "Fri 14:00"), days[], rows [{ name, hsl, from, len }] in days from days[0],
// now (day position), shipAt (day position of the "ships" mark), shipRow (row the mark sits on).
// One day is one 75-unit column; a changed bar or mark slides to its new place.
export const timeline: View = (p, id, _tier, spec) => {
  const X = (d: number) => 90 + d * 75, now = X(num(p.now, 0.53)), row = num(p.shipRow, 1);
  const head = p.ship ? `${esc(p.subject)} ships <span style="color:var(--cyan)">${esc(p.ship)}</span>` : esc(p.title);
  return `${hd(p, id, spec)}${title(head)}
<div class="viz"><svg viewBox="0 0 400 150" preserveAspectRatio="xMidYMid meet">
${list(p.days).map((d, i) => `<text x="${X(i)}" y="12" class="m">${esc(d)}</text><line x1="${X(i)}" y1="18" x2="${X(i)}" y2="140" stroke="hsl(0 0% 100% / .05)"/>`).join("")}
${list<Row>(p.rows)
  .map((r, i) => `<text x="0" y="${45 + i * 38}" class="m">${esc(r.name)}</text><rect y="${33 + i * 38}" height="16" rx="8" fill="${hsl(r.hsl, C.mute)}" style="x:${X(num(r.from))}px;width:${num(r.len) * 75}px;transition:x .8s var(--spring),width .8s var(--spring)"/>`)
  .join("")}
<line x1="${now}" y1="18" x2="${now}" y2="140" stroke="${C.cyan}" stroke-width="1.5"/><text x="${now + 4}" y="146" class="m" style="fill:${C.cyan}">now</text>
${p.shipAt != null ? `<text x="0" y="${28 + row * 38}" text-anchor="end" class="m" style="fill:${C.cyan};transform:translateX(${X(num(p.shipAt))}px);transition:transform .8s var(--spring)">ships</text>` : ""}
</svg></div>`;
};

type Member = { name?: unknown; hsl?: unknown; doing?: unknown };

// Props: title, body, members [{ name, hsl, doing }]. A wide card also lists what each one is doing.
export const crew: View = (p, id, tier, spec) => {
  const m = list<Member>(p.members), wd = wide(tier);
  // every row fits the 200-unit box, and the "doing" column starts after the longest name (mono glyph ~8.6 units)
  const step = Math.min(40, 180 / Math.max(1, m.length)), short = (s: unknown, n: number) => { const t = String(s ?? ""); return t.length > n ? `${t.slice(0, n - 1)}…` : t; };
  const nameN = Math.min(20, Math.max(0, ...m.map((a) => String(a.name ?? "").length))), dx = 345 + nameN * 8.6 + 16;
  const orbit = m
    .map((a, i) => {
      const t = (i / m.length) * 2 * Math.PI - Math.PI / 4, x = 150 + 74 * Math.cos(t), y = 100 + 74 * Math.sin(t), col = hsl(a.hsl, C.mute);
      return `<line x1="${(150 + 22 * Math.cos(t)).toFixed(1)}" y1="${(100 + 22 * Math.sin(t)).toFixed(1)}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="${col}" stroke-opacity=".4"/><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="8" fill="${col}"/><text x="${x.toFixed(1)}" y="${(y + (y > 100 ? 24 : -14)).toFixed(1)}" text-anchor="middle" style="font-size:11px">${esc(short(a.name, 14))}</text>`;
    })
    .join("");
  const doing = wd
    ? m.map((a, i) => { const y = 20 + step * (i + 0.5); return `<circle cx="330" cy="${y.toFixed(1)}" r="5" fill="${hsl(a.hsl, C.mute)}"/><text x="345" y="${(y + 5).toFixed(1)}">${esc(short(a.name, 20))}</text><text x="${dx.toFixed(1)}" y="${(y + 5).toFixed(1)}" class="m">${esc(short(a.doing ?? "idle", Math.max(8, Math.floor((700 - dx) / 7.6))))}</text>`; }).join("")
    : "";
  return `${hd(p, id, spec, undefined, `${m.length}<small>active</small>`)}${title(esc(p.title ?? "Crew right now"))}${body(p.body)}<div class="viz"><svg viewBox="0 0 ${wd ? 700 : 300} 200" preserveAspectRatio="xMidYMid meet">
<circle cx="150" cy="100" r="20" fill="hsl(262 92% 70% / .2)" stroke="${C.vio}"/><text x="150" y="104" text-anchor="middle">you</text>${orbit}${doing}</svg></div>`;
};

// Props: total, bars[] (PRs per day, oldest first). A narrow card shows 7 days, a wide one 14.
export const shipped: View = (p, id, tier, spec) => {
  const n = wide(tier) ? 14 : 7, d = list(p.bars).map((v) => num(v)).slice(-n), bw = 400 / n, top = Math.max(9, ...d);
  const bars = d
    .map((v, i) => {
      const h = (v / top) * 72;
      return `<rect x="${(i * bw + 2).toFixed(1)}" y="${(78 - h).toFixed(1)}" width="${(bw * 0.7).toFixed(1)}" height="${(h + 2).toFixed(1)}" rx="5" fill="hsl(152 72% 56% / ${(0.3 + v / (top * 1.55)).toFixed(2)})" style="transform-box:fill-box;transform-origin:bottom;animation:gy .9s var(--spring) ${i * 0.04}s both"/>`;
    })
    .join("");
  return `${hd(p, id, spec, undefined, `${esc(num(p.total))}<small>PRs</small>`)}${title(`Shipped in the last ${n} days`)}<div class="viz"><svg viewBox="0 0 400 84">${bars}</svg></div>`;
};
