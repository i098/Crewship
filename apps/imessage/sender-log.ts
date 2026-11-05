// The log of every text that went to the owner: topic key, sender, content hash, time. One file in the state dir.
// A keyed text is skipped when the same key and the same content were already sent on the same local day.
import { appendFileSync, readFileSync } from "node:fs";

export const KEY_PATTERN = /^[A-Za-z0-9._:-]{1,64}$/;
const FILE = "sent.jsonl";

type Entry = { key: string; sender: string; hash: string; at: number };

const day = (at: number) => new Date(at).toDateString();
// "(repost)" and spacing never make a text new.
const normal = (text: string) => text.replace(/\(\s*re-?post\s*\)/gi, "").replace(/\s+/g, " ").trim().toLowerCase();
const hashOf = (text: string) => new Bun.CryptoHasher("sha256").update(normal(text)).digest("hex");

export type Send = { key?: string; sender?: string; text: string };

// True when this key already sent the same content today. No key: never.
export function alreadySent(dir: string, o: Send, now = Date.now()): boolean {
  if (!o.key) return false;
  const hash = hashOf(o.text);
  let lines: string[] = [];
  try { lines = readFileSync(`${dir}/${FILE}`, "utf8").split("\n"); } catch { /* no log yet */ }
  return lines.some((line) => {
    try {
      const seen = JSON.parse(line) as Entry;
      return seen.key === o.key && seen.hash === hash && day(seen.at) === day(now);
    } catch { return false; /* blank or damaged line */ }
  });
}

// Logs a text that reached the outbox. No key: logged under "-".
export function logSend(dir: string, o: Send, now = Date.now()): void {
  appendFileSync(`${dir}/${FILE}`, `${JSON.stringify({ key: o.key ?? "-", sender: o.sender ?? "-", hash: hashOf(o.text), at: now } satisfies Entry)}\n`, { mode: 0o600 });
}
