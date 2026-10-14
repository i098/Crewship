// iMessage app cards (docs/imessage.md#cards): the card JSON, its records, its page, and the card-only listener.
// A card is a Spectrum app bubble that opens CARD_URL/c/<token>. The token is 256 random bits; anyone who has it
// sees that one card and nothing else. A choice card takes one pick; every card expires. Kept free of spectrum-ts.
import { randomBytes } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";

type Base = { key: string; title: string; subtitle?: string; hours?: number; app?: boolean; live?: boolean };
export type Card = Base & (
  | { kind: "choice"; options: string[] }
  | { kind: "bars"; bars: { label: string; value: number }[]; unit?: string }
  | { kind: "timeline"; items: { when: string; text: string }[] }
  | { kind: "table"; columns: string[]; rows: (string | number)[][] }
);
// `expires` is in ms since the epoch; `chat` is the outbox destination of its bubble; `picked` is the option index;
// `sent` is set once the bubble is out, and `session` is the bubble's miniAppCardSession, which an edit needs.
type Chat = { line?: string; space: string; id: string };
export type Stored = Card & { token: string; expires: number; chat?: Chat; picked?: number; sent?: boolean; session?: unknown };
export type Layout = { caption: string; subcaption?: string; trailingCaption?: string; summary: string };

const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const DAY = 86_400_000;

function text(v: unknown, max: number, what: string): string {
  if (typeof v !== "string" || !v.trim() || v.length > max) throw new Error(`${what} must be text of 1 to ${max} characters`);
  return v;
}
function list<T>(v: unknown, min: number, max: number, what: string, item: (x: unknown, i: number) => T): T[] {
  if (!Array.isArray(v) || v.length < min || v.length > max) throw new Error(`${what} must be a list of ${min} to ${max} items`);
  return v.map(item);
}
const object = (v: unknown, what: string) => {
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error(`${what} must be an object`);
  return v as Record<string, unknown>;
};

// Each kind's own fields, checked; an Error names the first bad field.
const FIELDS: Record<Card["kind"], (c: Record<string, unknown>) => object> = {
  choice: (c) => ({ options: list(c.options, 2, 6, "options", (o, i) => text(o, 120, `option ${i + 1}`)) }),
  bars: (c) => ({
    ...(c.unit === undefined ? {} : { unit: text(c.unit, 12, "unit") }),
    bars: list(c.bars, 1, 30, "bars", (b, i) => {
      const o = object(b, `bar ${i + 1}`);
      if (typeof o.value !== "number" || !Number.isFinite(o.value) || o.value < 0) throw new Error(`bar ${i + 1} value must be a number of 0 or more`);
      return { label: text(o.label, 60, `bar ${i + 1} label`), value: o.value };
    }),
  }),
  timeline: (c) => ({ items: list(c.items, 1, 50, "items", (x, i) => {
    const o = object(x, `item ${i + 1}`);
    return { when: text(o.when, 40, `item ${i + 1} when`), text: text(o.text, 200, `item ${i + 1} text`) };
  }) }),
  table: (c) => {
    const columns = list(c.columns, 1, 8, "columns", (x, i) => text(x, 40, `column ${i + 1}`));
    return { columns, rows: list(c.rows, 1, 100, "rows", (r, i) => list(r, columns.length, columns.length, `row ${i + 1}`, (cell) => {
      if ((typeof cell === "number" && Number.isFinite(cell)) || (typeof cell === "string" && cell.length <= 200)) return cell;
      throw new Error(`row ${i + 1} cells must be text of at most 200 characters or numbers`);
    })) };
  },
};

// The fields every kind has.
function base(c: Record<string, unknown>): Base {
  if (typeof c.key !== "string" || !/^[A-Za-z0-9._-]{1,40}$/.test(c.key)) throw new Error("key must be 1 to 40 letters, digits, '.', '_' or '-'");
  const b: Base = { key: c.key, title: text(c.title, 120, "title") };
  if (c.subtitle !== undefined) b.subtitle = text(c.subtitle, 200, "subtitle");
  if (c.hours !== undefined && (!Number.isInteger(c.hours) || (c.hours as number) < 1 || (c.hours as number) > 168)) throw new Error("hours must be a whole number from 1 to 168");
  if (c.hours !== undefined) b.hours = c.hours as number;
  // A card is an app bubble with its live view unless it says otherwise.
  for (const flag of ["app", "live"] as const) {
    if (c[flag] !== undefined && typeof c[flag] !== "boolean") throw new Error(`${flag} must be true or false`);
    b[flag] = (c[flag] as boolean | undefined) ?? true;
  }
  return b;
}

// The card in `json`, checked field by field; an Error names the first bad field.
export function parseCard(json: string): Card {
  let raw: unknown;
  try {
    raw = JSON.parse(json);
  } catch {
    throw new Error("the card is not valid JSON");
  }
  const c = object(raw, "the card");
  const kind = c.kind as Card["kind"];
  if (!Object.hasOwn(FIELDS, kind)) throw new Error(`kind must be one of ${Object.keys(FIELDS).join(", ")}`);
  return { ...base(c), kind, ...FIELDS[kind](c) } as Card;
}

export const letter = (i: number) => String.fromCharCode(65 + i);

// The bubble: the title, then one status line. No trailing caption: without the card app, Messages runs the caption
// and the trailing caption together into one line.
export function cardLayout(card: Stored): Layout {
  const status = card.kind === "choice"
    ? card.picked === undefined ? card.subtitle ?? `Pick one of ${card.options.length}` : `Picked ${letter(card.picked)}: ${card.options[card.picked]}`
    : card.subtitle ?? { bars: "Bar chart", timeline: "Timeline", table: "Table" }[card.kind];
  return { caption: card.title, subcaption: status, summary: card.title };
}

// One JSON file per card, named by its token, in a directory private to the account. The bridge is the only writer.
export class Cards {
  constructor(private dir: string) {
    mkdirSync(dir, { recursive: true, mode: 0o700 });
  }

  // Stores a new card for `chat` and returns it with its token. Cards a day past their expiry are deleted here.
  add(card: Card, chat: Chat): Stored {
    const now = Date.now();
    for (const f of readdirSync(this.dir)) {
      const old = this.read(f.replace(/\.json$/, ""));
      if (old && old.expires < now - DAY) rmSync(`${this.dir}/${f}`, { force: true });
    }
    const stored: Stored = { ...card, token: randomBytes(32).toString("base64url"), expires: now + (card.hours ?? 24) * 3_600_000, chat };
    this.save(stored);
    return stored;
  }

  save(card: Stored) {
    const path = `${this.dir}/${card.token}.json`;
    writeFileSync(`${path}.tmp`, JSON.stringify(card), { mode: 0o600 });
    renameSync(`${path}.tmp`, path);
  }

  // The card with this token, expired or not; undefined for a token of the wrong form or an unknown one.
  read(token: string): Stored | undefined {
    if (!TOKEN.test(token)) return undefined;
    try {
      return JSON.parse(readFileSync(`${this.dir}/${token}.json`, "utf8")) as Stored;
    } catch {
      return undefined;
    }
  }

  // The card a visitor may see: known and not expired.
  open(token: string): Stored | undefined {
    const card = this.read(token);
    return card && Date.now() < card.expires ? card : undefined;
  }
}

const HEADERS = {
  "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'",
  "referrer-policy": "no-referrer", // the token is in the URL
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "x-robots-tag": "noindex",
};
const esc = (s: string | number) => String(s).replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`);
// iOS system look: the system font and text styles, the system colours for light and dark, inset grouped lists,
// 44 pt rows, safe-area padding, and an instant pressed state with no tap delay.
const STYLE = `:root{color-scheme:light dark;--bg:#f2f2f7;--cell:#fff;--fg:#000;--muted:rgba(60,60,67,.6);--sep:rgba(60,60,67,.29);--fill:rgba(120,120,128,.16);--press:#d1d1d6;--accent:#007aff;--done:#34c759}
@media(prefers-color-scheme:dark){:root{--bg:#000;--cell:#1c1c1e;--fg:#fff;--muted:rgba(235,235,245,.6);--sep:rgba(84,84,88,.65);--fill:rgba(120,120,128,.32);--press:#3a3a3c;--accent:#0a84ff;--done:#30d158}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{background:var(--bg);-webkit-text-size-adjust:100%}
body{font:17px/22px -apple-system,system-ui,sans-serif;letter-spacing:-.4px;color:var(--fg);margin:0 auto;max-width:600px;padding:max(16px,env(safe-area-inset-top)) max(16px,env(safe-area-inset-right)) max(24px,env(safe-area-inset-bottom)) max(16px,env(safe-area-inset-left));-webkit-user-select:none;user-select:none}
h1{font-size:22px;line-height:28px;font-weight:700;letter-spacing:-.26px;margin:4px 4px 2px}
p{font-size:15px;line-height:20px;letter-spacing:-.24px;color:var(--muted);margin:0 4px 16px}
.group{background:var(--cell);border-radius:10px;overflow:hidden;margin:0 0 16px}
.cell{display:flex;align-items:center;gap:12px;width:100%;min-height:44px;padding:11px 16px;font:inherit;color:inherit;text-align:left;background:none;border:0;border-radius:0;position:relative;touch-action:manipulation}
.cell+.cell:before{content:"";position:absolute;top:0;left:16px;right:0;height:.5px;background:var(--sep)}
button.cell:active:not(:disabled){background:var(--press)}button.cell:disabled{opacity:1;color:inherit}
.l{flex:none;width:28px;height:28px;border-radius:14px;background:var(--accent);color:#fff;font-size:15px;font-weight:600;display:flex;align-items:center;justify-content:center}
.t{flex:1}.check{flex:none;color:var(--accent);font-weight:600}.dim .l{background:var(--fill);color:var(--muted)}.dim .t{color:var(--muted)}
.note{display:flex;align-items:center;gap:8px;color:var(--done);font-size:15px;font-weight:600;margin:0 4px 12px}
.bar{display:block}.row{display:flex;justify-content:space-between;gap:12px}.v{color:var(--muted);font-variant-numeric:tabular-nums}
.track{height:6px;border-radius:3px;background:var(--fill);margin-top:8px}.fillbar{height:100%;border-radius:3px;background:var(--accent)}
.when{font-size:13px;line-height:18px;color:var(--muted)}.dot{flex:none;width:10px;height:10px;border-radius:5px;background:var(--accent);align-self:flex-start;margin-top:6px}
.wide{overflow-x:auto;-webkit-overflow-scrolling:touch}table{border-collapse:collapse;width:100%;font-size:15px;line-height:20px;font-variant-numeric:tabular-nums}
th{font-size:13px;font-weight:400;color:var(--muted);text-align:left;padding:10px 16px 6px}td{text-align:left;padding:11px 16px;border-top:.5px solid var(--sep);white-space:nowrap}`;

// `description` makes the Open Graph tags that iMessage reads for the link preview of a card's URL.
function page(status: number, title: string, body: string, description?: string) {
  const og = description === undefined ? "" : `<meta property="og:title" content="${esc(title)}"><meta property="og:description" content="${esc(description)}"><meta property="og:site_name" content="Firstmate"><meta property="og:type" content="website">`;
  return new Response(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="color-scheme" content="light dark"><title>${esc(title)}</title>${og}<style>${STYLE}</style></head><body>${body}</body></html>`,
    { status, headers: { ...HEADERS, "content-type": "text/html; charset=utf-8" } });
}

// The card's page, made to look like an iOS view inside Messages. A choice card shows one row per option until it
// has its pick; then the rows stay, with a check on the pick.
export function cardPage(card: Stored, status = 200, notice = "") {
  const head = `<h1>${esc(card.title)}</h1>${card.subtitle ? `<p>${esc(card.subtitle)}</p>` : ""}${notice ? `<p>${esc(notice)}</p>` : ""}`;
  let body: string;
  if (card.kind === "choice") {
    const done = card.picked !== undefined;
    const row = (o: string, i: number) => `<button class="cell${done && card.picked !== i ? " dim" : ""}" name="choice" value="${i}"${done ? " disabled" : ""}><span class="l">${letter(i)}</span><span class="t">${esc(o)}</span>${card.picked === i ? '<span class="check">&#10003;</span>' : ""}</button>`;
    const rows = `<div class="group">${card.options.map(row).join("")}</div>`;
    body = done ? `<div class="note">&#10003; Picked ${letter(card.picked!)}. Firstmate has it.</div>${rows}` : `<form method="post" action="/c/${card.token}/pick">${rows}</form>`;
  } else if (card.kind === "bars") {
    // A percentage fills its track out of 100; any other unit is scaled to the largest bar.
    const max = Math.max(...card.bars.map((b) => b.value), card.unit === "%" ? 100 : 0) || 1;
    body = `<div class="group">${card.bars.map((b) => `<div class="cell bar"><div class="row"><span>${esc(b.label)}</span><span class="v">${esc(b.value)}${card.unit ? ` ${esc(card.unit)}` : ""}</span></div><div class="track"><div class="fillbar" style="width:${((b.value / max) * 100).toFixed(1)}%"></div></div></div>`).join("")}</div>`;
  } else if (card.kind === "timeline") {
    body = `<div class="group">${card.items.map((x) => `<div class="cell"><span class="dot"></span><span class="t"><span class="when">${esc(x.when)}</span><br>${esc(x.text)}</span></div>`).join("")}</div>`;
  } else {
    body = `<div class="group wide"><table><thead><tr>${card.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${card.rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  return page(status, card.title, head + body, cardLayout(card).subcaption);
}

// The card-only listener: GET /c/<token> and POST /c/<token>/pick, nothing else. `pick` gets the card with its pick
// already saved, files the note, and returns false when the inbox refused it; the pick is then undone. The check,
// the save and `pick` run synchronously, so two picks cannot both pass.
export function cardRoutes(cards: Cards, pick: (card: Extract<Stored, { kind: "choice" }>, choice: number) => boolean) {
  return async (req: Request): Promise<Response> => {
    const m = /^\/c\/([^/]+)(\/pick)?$/.exec(new URL(req.url).pathname);
    if (!m || req.method !== (m[2] ? "POST" : "GET")) return new Response("not found\n", { status: 404, headers: HEADERS });
    const token = m[1]!;
    const form = m[2] ? await req.formData().catch(() => undefined) : undefined;
    const card = cards.open(token);
    if (!card || (m[2] && card.kind !== "choice")) return page(404, "Card not found", "<h1>This card is gone</h1><p>It expired or it never existed. Ask for a new one.</p>");
    if (!m[2] || card.kind !== "choice") return cardPage(card);
    const raw = form?.get("choice");
    const choice = typeof raw === "string" && /^[0-9]$/.test(raw) ? Number(raw) : -1;
    if (choice < 0 || choice >= card.options.length) return cardPage(card, 400, "That is not one of the options.");
    if (card.picked !== undefined) return cardPage(card, 409, "This card already has its pick.");
    const done = { ...card, picked: choice };
    cards.save(done);
    if (!pick(done, choice)) {
      cards.save(card);
      return cardPage(card, 503, "Firstmate did not get it. Try again.");
    }
    return new Response(null, { status: 303, headers: { ...HEADERS, location: `/c/${token}` } });
  };
}
