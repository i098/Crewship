// iMessage app cards (docs/imessage.md#cards): the card JSON, its records, its page, and the card-only listener.
// A card is a Spectrum app bubble that opens CARD_URL/c/<token>. The token is 256 random bits; anyone who has it
// sees that one card and nothing else. A choice card takes one pick; every card expires. Kept free of spectrum-ts.
import { randomBytes } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";

type Base = { key: string; title: string; subtitle?: string; hours?: number; live?: boolean };
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
  if (c.live !== undefined && typeof c.live !== "boolean") throw new Error("live must be true or false");
  if (c.live !== undefined) b.live = c.live as boolean;
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

// The bubble: the title, then the state of the card.
export function cardLayout(card: Stored): Layout {
  const what = card.kind === "choice"
    ? card.picked === undefined ? `${card.options.length} options` : `Picked ${letter(card.picked)}: ${card.options[card.picked]}`
    : { bars: "Bar chart", timeline: "Timeline", table: "Table" }[card.kind];
  const done = card.kind === "choice" && card.picked !== undefined;
  return { caption: card.title, subcaption: card.subtitle && !done ? card.subtitle : what, trailingCaption: done ? "Done" : card.kind === "choice" ? "Tap to pick" : "Tap to open", summary: card.title };
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
const STYLE = `:root{color-scheme:light dark;--fg:#111;--muted:#666;--line:#ddd;--accent:#0a84ff}
@media(prefers-color-scheme:dark){:root{--fg:#f2f2f2;--muted:#999;--line:#333}}
body{font:17px/1.4 -apple-system,system-ui,sans-serif;color:var(--fg);margin:0;padding:20px;max-width:640px}
h1{font-size:22px;margin:0 0 4px}p{color:var(--muted);margin:0 0 16px}
button{display:block;width:100%;text-align:left;font:inherit;padding:14px;margin:0 0 10px;border:1px solid var(--line);border-radius:12px;background:none;color:inherit}
b.l{color:var(--accent);margin-right:8px}.picked{border-color:var(--accent);border-width:2px}
.bar{margin:0 0 10px}.track{height:22px;border-radius:6px;background:var(--line)}.fill{height:100%;border-radius:6px;background:var(--accent)}
.row{display:flex;justify-content:space-between;font-size:15px}
ol{list-style:none;padding:0 0 0 16px;border-left:2px solid var(--line);margin:0}li{margin:0 0 14px;position:relative}
li:before{content:"";position:absolute;left:-23px;top:6px;width:12px;height:12px;border-radius:50%;background:var(--accent)}
li span{color:var(--muted);font-size:14px;display:block}
table{border-collapse:collapse;width:100%;font-size:15px}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line)}
.wide{overflow-x:auto}`;

function page(status: number, title: string, body: string) {
  return new Response(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title><style>${STYLE}</style></head><body>${body}</body></html>`,
    { status, headers: { ...HEADERS, "content-type": "text/html; charset=utf-8" } });
}

// The card's page. A choice card shows one form button per option until it has its pick.
export function cardPage(card: Stored, status = 200, notice = "") {
  const head = `<h1>${esc(card.title)}</h1>${card.subtitle ? `<p>${esc(card.subtitle)}</p>` : ""}${notice ? `<p>${esc(notice)}</p>` : ""}`;
  let body: string;
  if (card.kind === "choice") {
    const button = (o: string, i: number) => `<button name="choice" value="${i}"${card.picked === i ? ' class="picked"' : ""}${card.picked === undefined ? "" : " disabled"}><b class="l">${letter(i)}</b>${esc(o)}</button>`;
    body = card.picked === undefined
      ? `<form method="post" action="/c/${card.token}/pick">${card.options.map(button).join("")}</form>`
      : `<p>Picked ${letter(card.picked)}. Firstmate has it.</p>${card.options.map(button).join("")}`;
  } else if (card.kind === "bars") {
    // A percentage fills its track out of 100; any other unit is scaled to the largest bar.
    const max = Math.max(...card.bars.map((b) => b.value), card.unit === "%" ? 100 : 0) || 1;
    body = card.bars.map((b) => `<div class="bar"><div class="row"><span>${esc(b.label)}</span><span>${esc(b.value)}${card.unit ? ` ${esc(card.unit)}` : ""}</span></div><div class="track"><div class="fill" style="width:${((b.value / max) * 100).toFixed(1)}%"></div></div></div>`).join("");
  } else if (card.kind === "timeline") {
    body = `<ol>${card.items.map((x) => `<li><span>${esc(x.when)}</span>${esc(x.text)}</li>`).join("")}</ol>`;
  } else {
    body = `<div class="wide"><table><thead><tr>${card.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${card.rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  return page(status, card.title, head + body);
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
