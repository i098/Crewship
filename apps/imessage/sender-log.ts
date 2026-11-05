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

// Records the text; false (and no record) when its key already sent the same content today. No key: always sent, still logged.
export function claimSend(dir: string, o: { key?: string; sender?: string; text: string }, now = Date.now()): boolean {
  const hash = hashOf(o.text);
  const key = o.key ?? "-";
  if (o.key) {
    let lines: string[] = [];
    try { lines = readFileSync(`${dir}/${FILE}`, "utf8").split("\n"); } catch { /* no log yet */ }
    for (const line of lines) {
      try {
        const seen = JSON.parse(line) as Entry;
        if (seen.key === key && seen.hash === hash && day(seen.at) === day(now)) return false;
      } catch { /* blank or damaged line */ }
    }
  }
  appendFileSync(`${dir}/${FILE}`, `${JSON.stringify({ key, sender: o.sender ?? "-", hash, at: now } satisfies Entry)}\n`, { mode: 0o600 });
  return true;
}
