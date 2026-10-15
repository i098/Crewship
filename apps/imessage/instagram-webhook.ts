// The receiver of the Instagram DM line on Meta's official API (INSTAGRAM_DM_BACKEND=graph; docs/imessage.md#cards):
// Meta POSTs each DM to /instagram/webhook on the public card listener. Each operator DM goes to the Firstmate inbox
// (INSTAGRAM_DM_NOTIFY) first, then one row to INSTAGRAM_DM_LOG, the same row the instagrapi poller writes, so
// instagram-desk.ts follows it unchanged. An unsigned or badly signed request files nothing. Meta retries a failed
// delivery for 36 h, so rows are deduped on their mid, and a failed note answers 500 to get that retry.
import { createHmac, timingSafeEqual } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname } from "node:path";
// Types only: bridge.ts runs without instagram-desk.ts beside it.
import type { Row as DeskRow } from "./instagram-desk.ts";

export type Row = DeskRow & { meta?: { caption?: string; media_id?: string } };
// The parts of Meta's payload the receiver reads. It comes off the wire, so every field may be missing.
type Attachment = { type?: string; payload?: { url?: string; title?: string; ig_post_media_id?: string | number; reel_video_id?: string | number; id?: string | number } };
export type Messaging = {
  sender?: { id?: string };
  timestamp?: number;
  message?: { mid?: string; text?: string; is_echo?: boolean; is_deleted?: boolean; is_self?: boolean; attachments?: (Attachment | null)[] };
};
type Payload = { entry?: ({ messaging?: (Messaging | null)[] } | null)[] };
type Options = { appSecret: string; verifyToken: string; operator: string; log: string; notify: string[]; say?: (line: string) => void };

const REEL_TYPES: Record<string, true> = { ig_reel: true, reel: true, ig_post: true, share: true };
const list = <T>(v: T[] | undefined): T[] => (Array.isArray(v) ? v : []); // a JSON field that should be a list

// `X-Hub-Signature-256: sha256=<hex>`: HMAC-SHA256 of the raw body with the app secret.
export function verifySignature(body: string, header: string | null, secret: string): boolean {
  const hex = /^sha256=([0-9a-f]{64})$/i.exec(header ?? "")?.[1];
  return !!hex && timingSafeEqual(Buffer.from(hex, "hex"), createHmac("sha256", secret).update(body).digest());
}

// One `messaging[]` event as a log row; none for echoes, deletions, test DMs to the account itself and non-messages.
export function messageRow(m: Messaging | null): Row | undefined {
  const msg = m?.message;
  if (!msg?.mid || msg.is_echo || msg.is_deleted || msg.is_self) return undefined;
  const sender = String(m!.sender?.id ?? "");
  const row: Row = { at: Math.floor(Number(m!.timestamp) / 1000), id: String(msg.mid), thread: sender, sender, type: "text" };
  if (msg.text) row.text = msg.text;
  const attachments = list(msg.attachments);
  const reel = attachments.find((a) => REEL_TYPES[a?.type ?? ""]); // a post share carries `share` and `ig_post` for one media
  if (reel) {
    const p = reel.payload ?? {};
    const id = p.ig_post_media_id ?? p.reel_video_id ?? p.id;
    const meta = Object.fromEntries(Object.entries({ caption: (p.title ?? "").trim().split(/\s+/).join(" ").slice(0, 300), media_id: String(id ?? "") }).filter(([, v]) => v));
    Object.assign(row, { type: reel.type, url: p.url }, Object.keys(meta).length ? { meta } : {});
  } else if (attachments[0]?.type) row.type = attachments[0].type;
  return row;
}

// The inbox note of a row (instagram_dm.py note_text).
export function noteText(row: Row): string {
  const reel = row.url ? [row.url, row.meta?.media_id && `(media ${row.meta.media_id})`, row.meta?.caption && `caption: "${row.meta.caption}"`].filter(Boolean).join(" ") : "";
  const text = (row.text ?? "").trim().split(/\s+/).join(" ").slice(0, 300);
  return `[Instagram DM from ${row.sender}; answer with fm-insta-reply] ${reel || text || `[${row.type}]`}`;
}

// The handler of /instagram/webhook: GET is Meta's verification handshake, POST a signed batch of events.
export function instagramWebhook(o: Options): (req: Request) => Promise<Response> {
  const say = o.say ?? console.log;
  let seen: Set<string> | undefined; // the mids already filed, read from the log once
  return async (req) => {
    if (req.method === "GET") {
      const q = new URL(req.url).searchParams;
      const token = Buffer.from(q.get("hub.verify_token") ?? "");
      const ok = q.get("hub.mode") === "subscribe" && token.length === Buffer.byteLength(o.verifyToken) && timingSafeEqual(token, Buffer.from(o.verifyToken));
      return ok ? new Response(q.get("hub.challenge") ?? "") : new Response("forbidden\n", { status: 403 });
    }
    if (req.method !== "POST") return new Response("not found\n", { status: 404 });
    const body = await req.text();
    if (!verifySignature(body, req.headers.get("x-hub-signature-256"), o.appSecret)) return new Response("forbidden\n", { status: 403 });
    let data: Payload | null;
    try {
      data = JSON.parse(body); // checked field by field below: list() and optional chaining
    } catch {
      return new Response("bad json\n", { status: 400 });
    }
    seen ??= new Set(existsSync(o.log) ? [...readFileSync(o.log, "utf8").matchAll(/"id":"([^"]+)"/g)].map((m) => m[1]!) : []);
    for (const row of list(data?.entry).flatMap((e) => list(e?.messaging).map(messageRow))) {
      if (!row || seen.has(row.id!)) continue;
      if (!o.operator || row.thread !== o.operator) {
        say(`instagram webhook: ignored a DM from ${row.sender} (not INSTAGRAM_DM_OPERATOR)`);
        continue;
      }
      // The note first: a refused note answers 500, and Meta's retry brings the DM back.
      if (o.notify.length && Bun.spawnSync([...o.notify, "--request-id", `ig-${row.id}`, "--", noteText(row)]).exitCode !== 0) {
        return new Response("inbox refused the note\n", { status: 500 });
      }
      mkdirSync(dirname(o.log), { recursive: true, mode: 0o700 });
      appendFileSync(o.log, `${JSON.stringify(row)}\n`, { mode: 0o600 });
      seen.add(row.id!);
    }
    return new Response("EVENT_RECEIVED");
  };
}
