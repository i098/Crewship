// The bridge's durable queues (bridge.ts): the outbox of sends and tapbacks, and the attachment downloads to try
// again. Kept free of spectrum-ts so tests run without it.
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readdirSync, readFileSync, renameSync, unlinkSync, writeSync } from "node:fs";

const NETWORK = /^(TimeoutError|ETIMEDOUT|ECONNRESET|ECONNREFUSED|EAI_AGAIN|ENOTFOUND|ENETUNREACH|EHOSTUNREACH|EPIPE|ConnectionRefused|ConnectionClosed|FailedToOpenSocket|UND_ERR_SOCKET|UND_ERR_CONNECT_TIMEOUT|UND_ERR_HEADERS_TIMEOUT|UND_ERR_BODY_TIMEOUT|UND_ERR_CLOSED)$/;

// The code of an upstream outage, for the log line: gRPC UNAVAILABLE (code 14, which Photon's HTTP client also gives
// for HTTP 502 and 503), an HTTP 502, 503 or 504, a timeout (gRPC DEADLINE_EXCEEDED, code 4), or a network failure
// with no response. Undefined for any other error.
export function transient(e: unknown): string | undefined {
  for (let x: unknown = e; x instanceof Object; x = Reflect.get(x, "cause")) {
    const status = Reflect.get(x, "status");
    const message = String(Reflect.get(x, "message"));
    if (Reflect.get(x, "grpcCode") === 14 || Reflect.get(x, "code") === 14 || /\bUNAVAILABLE\b/.test(message)) return "UNAVAILABLE";
    if (status === 502 || status === 503 || status === 504) return `HTTP ${status}`;
    if (NETWORK.test(`${Reflect.get(x, "name")}`) || NETWORK.test(`${Reflect.get(x, "code")}`) || Reflect.get(x, "grpcCode") === 4 ||
      Reflect.get(x, "code") === 4 || /\b(DEADLINE_EXCEEDED|timed out)\b|fetch failed|Unable to connect|connection (was )?closed/i.test(message)) return "TIMEOUT";
  }
}

// True only when the error proves the item itself is bad, so a later try cannot pass: a message or attachment that
// is not found or expired (HTTP 404 or 410, gRPC NOT_FOUND), an item the upstream refuses as invalid (HTTP 400 or
// 422, gRPC INVALID_ARGUMENT), or a queue file that cannot be read (marked `permanent`). Every other error, an
// unknown one too, may be an outage, so the item is tried again.
export function permanent(e: unknown): boolean {
  if (transient(e)) return false;
  for (let x: unknown = e; x instanceof Object; x = Reflect.get(x, "cause")) {
    const code = Reflect.get(x, "grpcCode") ?? Reflect.get(x, "code");
    const message = String(Reflect.get(x, "message"));
    if (Reflect.get(x, "permanent") === true || [400, 404, 410, 422].includes(Reflect.get(x, "status")) || code === 3 || code === 5 ||
      /\b(INVALID_ARGUMENT|NOT_FOUND)\b|\bnot found\b|\b(attachment|message)\b.*\bexpired\b|\bexpired\b.*\b(attachment|message)\b/i.test(message)) return true;
  }
  return false;
}

// One line for a failed operation: the transient code (else the error name), then the first line of the message.
export function brief(e: unknown): string {
  const message = (e instanceof Error ? e.message : String(e)).split("\n")[0];
  return `${transient(e) ?? (e instanceof Error ? e.name : "error")}: ${message}`;
}

// A durable FIFO queue in `dir`: one JSON file per item, named by a rising sequence number and written atomically
// (fsync, then rename), so an item survives a crash or a restart once add() returns. One loop per lane (`lane`;
// default: one lane for all) delivers the oldest item of its lane, so a slow or failing send holds only its own lane.
// When that fails, the loop logs one line, waits one backoff step (at most 60 × `retryMs`) and tries the same
// item again, so the order holds. Only an item that is provably bad (see `permanent`, or a file that does not
// parse) moves to `${dir}-dead/`; the loop logs one line and goes on with the next item.
// See docs/imessage.md#upstream-outages before manually removing or replaying an item.
// `deliver` may save progress with `save`. Startup resumes pending items; `lost` receives parsed dead letters.
// An optional key deduplicates submissions against pending, completed, and dead-letter receipts.
// Keyed completion keeps the item in `${dir}-done/`; keyed dead letters replay `lost` after restart.
export class Queue<T> {
  private next: number;
  private busy = new Set<string>();
  private laneBySeq = new Map<number, string>();
  private keys = new Set<string>();

  constructor(
    private dir: string,
    private name: string,
    private deliver: (item: T, save: (item: T) => void) => Promise<void>,
    private retryMs: number,
    private lost?: (item: T) => void,
    private key?: (item: T) => string | undefined,
    private lane?: (item: T) => string,
  ) {
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    this.next = (this.seqs().at(-1) ?? 0) + 1;
    if (key) {
      mkdirSync(`${dir}-done`, { recursive: true, mode: 0o700 });
      for (const folder of [dir, `${dir}-done`, `${dir}-dead`]) this.restoreKeys(folder, key);
    }
    this.drainAll();
  }

  add(item: T) {
    const id = this.key?.(item);
    if (id && this.keys.has(id)) this.syncDir();
    else {
      try { this.write(this.next, item); this.laneBySeq.set(this.next++, this.lane?.(item) ?? ""); }
      catch (e) {
        if (id && this.key) this.restoreKeys(this.dir, this.key);
        throw e;
      }
      if (id) this.keys.add(id);
    }
    this.drainAll();
  }

  // One drain loop per lane that has pending items; a running lane's loop picks up its new items itself.
  private drainAll() {
    for (const lane of new Set(this.seqs().map((seq) => this.laneOf(seq)))) void this.drain(lane);
  }

  private laneOf(seq: number): string {
    if (!this.lane) return "";
    let lane = this.laneBySeq.get(seq);
    if (lane === undefined) {
      try { lane = this.lane(JSON.parse(readFileSync(this.file(seq), "utf8"))); }
      catch { lane = ""; } // the drain buries an unreadable file
      this.laneBySeq.set(seq, lane);
    }
    return lane;
  }

  private restoreKeys(folder: string, key: (item: T) => string | undefined) {
    if (!existsSync(folder)) return;
    for (const file of readdirSync(folder).filter((f) => f.endsWith(".json"))) {
      let item: T;
      try { item = JSON.parse(readFileSync(`${folder}/${file}`, "utf8")); }
      catch { continue; } // The normal drain handles an unreadable pending item.
      const id = key(item);
      if (id) this.keys.add(id);
      if (folder === `${this.dir}-done`) this.next = Math.max(this.next, parseInt(file, 10) + 1);
      if (id && folder === `${this.dir}-dead`) queueMicrotask(() => {
        try { this.lost?.(item); }
        catch (e) { console.error(`fm-imessage: ${this.name} restored lost notice failed: ${brief(e)}`); }
      });
    }
  }

  private seqs(): number[] {
    return readdirSync(this.dir).filter((f) => /^\d+\.json$/.test(f)).map((f) => parseInt(f, 10)).sort((a, b) => a - b);
  }

  private file(seq: number): string {
    return `${this.dir}/${seq}.json`;
  }

  private write(seq: number, item: T) {
    const tmp = `${this.file(seq)}.tmp`;
    const fd = openSync(tmp, "w", 0o600);
    try {
      writeSync(fd, JSON.stringify(item));
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
    renameSync(tmp, this.file(seq));
    this.syncDir();
  }

  private syncDir() {
    const dir = openSync(this.dir, "r");
    try {
      fsyncSync(dir);
    } finally {
      closeSync(dir);
    }
  }

  private bury(seq: number, e: unknown): boolean {
    try {
      const dead = `${this.dir}-dead`;
      mkdirSync(dead, { recursive: true, mode: 0o700 });
      renameSync(this.file(seq), `${dead}/${Date.now()}-${seq}.json`);
      this.laneBySeq.delete(seq);
      console.error(`fm-imessage: ${this.name} ${seq} cannot be delivered, moved to ${dead}/: ${brief(e)}`);
      return true;
    } catch (x) {
      console.error(`fm-imessage: ${this.name} ${seq} could not be moved to the dead-letter folder: ${brief(x)}`);
      return false;
    }
  }

  private async drain(lane: string) {
    if (this.busy.has(lane)) return;
    this.busy.add(lane);
    const first = () => this.seqs().find((seq) => this.laneOf(seq) === lane);
    let head: number | undefined;
    let attempt = 0;
    try {
      for (let seq = first(); seq !== undefined; seq = first()) {
        if (seq !== head) [head, attempt] = [seq, 0];
        let item: T | undefined;
        try {
          try {
            item = JSON.parse(readFileSync(this.file(seq), "utf8"));
          } catch (e) {
            throw Object.assign(new Error(`unreadable queue file: ${brief(e)}`), { permanent: true });
          }
          await this.deliver(item as T, (next) => {
            this.write(seq, next);
            item = next;
          });
          if (this.key?.(item as T)) renameSync(this.file(seq), `${this.dir}-done/${seq}.json`);
          else unlinkSync(this.file(seq));
          this.laneBySeq.delete(seq);
        } catch (e) {
          if (permanent(e) && this.bury(seq, e)) {
            if (item !== undefined) try { this.lost?.(item); } catch (x) { console.error(`fm-imessage: ${this.name} ${seq} lost notice failed: ${brief(x)}`); }
            continue;
          }
          // Capped exponential backoff with jitter, so retries spread out.
          const wait = Math.min(60 * this.retryMs, this.retryMs * 2 ** attempt++) * (0.5 + Math.random() / 2);
          console.error(`fm-imessage: ${this.name} ${seq} failed (try ${attempt}), next try in ${(wait / 1000).toFixed(1)} s: ${brief(e)}`);
          await Bun.sleep(wait);
        }
      }
    } finally {
      this.busy.delete(lane);
    }
  }
}
