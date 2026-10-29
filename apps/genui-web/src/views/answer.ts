// Views the AI builds in answer to you: a comparison, an ask it is working on, a plan form to send back.
import { acts, esc, hd, kpi, list, num, title, wide, type View } from "./chrome";

// Props: a, b (the two options), subject, metrics [[label, a, b]], verdict, acts [{ k, b, pri }].
// Each row is a pair of bars from the centre; the larger value is solid. Numbers and the verdict show when wide.
export const compare: View = (p, id, tier, spec) => {
  const wd = wide(tier), m = list<unknown[]>(p.metrics).filter(Array.isArray);
  const top = Math.max(1, ...m.flatMap((r) => [num(r[1]), num(r[2])])), s = 180 / top;
  const rows = m
    .map((r, i) => {
      const a = num(r[1]), b = num(r[2]), y = 48 + i * 36, anim = `animation:gx 1s var(--spring) ${i * 0.12}s both`;
      return `<text x="200" y="${42 + i * 36}" text-anchor="middle" class="m">${esc(r[0])}</text>
<rect x="${(195 - a * s).toFixed(1)}" y="${y}" width="${(a * s).toFixed(1)}" height="10" rx="5" fill="${a > b ? "hsl(262 92% 70%)" : "hsl(262 92% 70% / .35)"}" style="transform-origin:195px 0;${anim}"/>
<rect x="205" y="${y}" width="${(b * s).toFixed(1)}" height="10" rx="5" fill="${b > a ? "hsl(188 95% 58%)" : "hsl(188 95% 58% / .35)"}" style="transform-origin:205px 0;${anim}"/>${
        wd ? `<text x="${(190 - a * s).toFixed(1)}" y="${y + 9}" text-anchor="end" class="m">${a}</text><text x="${(210 + b * s).toFixed(1)}" y="${y + 9}" class="m">${b}</text>` : ""
      }`;
    })
    .join("");
  return `${hd(p, id, spec, { text: "you asked" })}${title(`${esc(p.a)} <span style="color:var(--dim)">vs</span> <span style="color:var(--cyan)">${esc(p.b)}</span>${p.subject ? ` for ${esc(p.subject)}` : ""}`)}
<div class="viz"><svg viewBox="0 0 400 ${30 + m.length * 36}" preserveAspectRatio="xMidYMid meet">
<text x="190" y="14" text-anchor="end" class="m">${esc(p.a)}</text><text x="210" y="14" class="m" style="fill:hsl(188 95% 58%)">${esc(p.b)}</text>${rows}</svg></div>${
    wd && p.verdict ? `<div class="m">${esc(p.verdict)}</div>` : ""
  }${acts(id, list(p.acts))}`;
};

const hash = (s: string) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 9973, 7);

// Props: q (your words), about[] (what it looked at), ready. A dithered skeleton until the answer is ready.
export const ask: View = (p, id, _tier, spec) => {
  const about = list(p.about).map(String), row = (a: string, i: number) => `<div class="ar"><span>${esc(a)}</span><i style="width:${35 + (hash(a) % 60)}%;animation-delay:${i * 0.1}s"></i></div>`;
  // while the model works, each step it has streamed shows above the skeleton
  const body = p.ready
    ? `<div class="ans">${(about.length ? about : ["New view for this spot"]).map(row).join("")}</div>`
    : `${about.length ? `<div class="ans">${about.map(row).join("")}</div>` : ""}<div class="skel"><i></i><i></i><i></i></div>`;
  return `${hd(p, id, spec, p.ready ? { text: "answer", cls: "g" } : { text: "working" })}${title(esc(p.q))}${body}`;
};

type Field = { name?: unknown; label?: unknown; opts?: unknown };

// Props: title, kpi, fields [{ name, label, opts [[value, label]] }] (first option is the AI pick), done.
// The form posts with data-act="send"; the plan box has no full view.
export const plan: View = (p, id, _tier, spec) => {
  const done = p.done === true;
  const sets = list<Field>(p.fields)
    .map(
      (f) =>
        `<fieldset><legend>${esc(f.label)}</legend><div class="ro">${list<unknown[]>(f.opts)
          .filter(Array.isArray)
          .map((o, i) => `<label><input type="radio" name="${esc(f.name)}" value="${esc(o[0])}"${i ? "" : " checked"}>${esc(o[1])}${i ? "" : " <i>AI pick</i>"}</label>`)
          .join("")}</div></fieldset>`,
    )
    .join("");
  return `${hd(p, id, spec, done ? { text: "sent", cls: "g" } : undefined, done ? "" : kpi(p), false)}${title(esc(p.title ?? "Plan the build"))}<form class="planf" data-act="send" data-id="${esc(id)}">${sets}<textarea class="note" name="note" rows="2" maxlength="300" placeholder="Anything else?"></textarea><button class="send" type="submit"${done ? " disabled" : ""}>${done ? "Sent ✓" : "Send"}</button></form>`;
};
