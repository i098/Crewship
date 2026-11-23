// The log of every text that went to the owner: topic key, sender, content hash, time. One file in the state dir.
// A keyed text is skipped when the same key and the same content were already sent on the same local day.
import { Database } from "bun:sqlite";
import { appendFileSync, readFileSync, statSync } from "node:fs";

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

const THREAD_MAX_AGE_MS = 30 * 86_400_000;

export function openThreadSenders(dir: string, now = Date.now()) {
  const db = new Database(`${dir}/thread-senders.sqlite`);
  if (!db.query("SELECT 1 FROM sqlite_schema WHERE name = 'thread_sender'").get()) db.transaction(() => {
    db.exec("CREATE TABLE thread_sender (id TEXT PRIMARY KEY, sender TEXT NOT NULL, at INTEGER NOT NULL)");
    db.exec("CREATE INDEX thread_sender_at ON thread_sender (at)");
    const path = `${dir}/senders.json`;
    let legacy: unknown;
    let at = 0;
    try {
      at = Math.floor(statSync(path).mtimeMs);
      if (at >= now - THREAD_MAX_AGE_MS) legacy = JSON.parse(readFileSync(path, "utf8"));
    } catch { /* no usable legacy records */ }
    if (!Array.isArray(legacy)) return;
    const insert = db.query("INSERT OR IGNORE INTO thread_sender VALUES (?, ?, ?)");
    for (const row of legacy.slice(-5000)) {
      if (typeof row?.id === "string" && row.id && typeof row.sender === "string") insert.run(row.id, row.sender, at);
    }
  })();
  const insert = db.query("INSERT OR IGNORE INTO thread_sender VALUES (?, ?, ?)");
  const expire = db.query("DELETE FROM thread_sender WHERE at < ?");
  const cap = db.query("DELETE FROM thread_sender WHERE rowid <= (SELECT rowid FROM thread_sender ORDER BY rowid DESC LIMIT 1 OFFSET 5000)");
  const remember = db.transaction((id: string, sender: string, at = Date.now()) => {
    expire.run(at - THREAD_MAX_AGE_MS);
    insert.run(id, sender, at);
    cap.run();
  });
  const lookup = db.query<{ sender: string }, [string, number]>("SELECT sender FROM thread_sender WHERE id = ? AND at >= ?");
  return {
    remember,
    find(id: string, at = Date.now()) { return lookup.get(id, at - THREAD_MAX_AGE_MS)?.sender; },
  };
}
