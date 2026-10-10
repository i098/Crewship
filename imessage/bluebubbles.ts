// The BlueBubbles transport of the iMessage bridge (bridge.ts, docs/imessage.md): self-hosted BlueBubbles servers,
// "relays", on Macs signed into the same Apple Account, used as one line in config order.
// Outbound: calls fail over in config order; relay eligibility is described in docs/imessage.md.
//   A send that may have reached a relay is retried on the next relay only after no relay shows it as sent.
//   The bridge's outbox (outbox.ts) retries what fails.
// Inbound: every relay posts its webhook here, and a catch-up query fills any gap. A webhook is only a hint: the
//   message itself is read back from a relay with the password, so a forged webhook can only name a real message.
//   Messages are de-duplicated by GUID with a bounded seen-set on disk. A failed attachment download is retried by
//   the bridge's download queue.
// The API takes the password only as a query parameter, so a request URL is never logged or put in an error.
// API: https://documenter.getpostman.com/view/765844/UV5RnfwM (BlueBubbles server 1.9).
import { appendFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import type { Message } from "spectrum-ts";
import { permanent } from "./outbox.ts";

export type Relay = { url: string; password: string };

// A spectrum-ts message content (a type-only import: bun erases it). A BlueBubbles message has the same shape as
// desk.ts Bubble, so the bridge handles it like a Photon one.
type Content = Message["content"];
type Bubble = {
  id: string; content: Content; direction: "inbound" | "outbound"; sender: { id: string }; timestamp?: Date;
  space: { id: string; send(text: string): Promise<unknown>; startTyping(): Promise<void>; stopTyping(): Promise<void> };
  react(emoji: string): Promise<unknown>; reply(text: string): Promise<unknown>; read(): Promise<unknown>;
};

const DEFAULTS = {
  pingMs: 3000, // health check timeout
  healthMs: 10_000, // how long a health result is kept
  callMs: 15_000, // any other call
  downloadMs: 10 * 60_000, // an attachment download, body included
  sendMs: 30_000, // a send: the server answers once Messages has the message
  skewMs: 60_000, // clock difference allowed between this host and a relay when looking for a sent text
  seenMax: 1000, // message GUIDs kept for de-duplication
  catchUpMs: 60_000, // between catch-up queries
  lookbackMs: 15 * 60_000, // how far back a catch-up query looks
};

// The tapbacks BlueBubbles can send, by emoji.
const TAPBACKS: Record<string, string> = {
  "❤️": "love", "❤": "love", "👍": "like", "👎": "dislike", "😂": "laugh", "‼️": "emphasize", "‼": "emphasize", "❓": "question",
};

// A failed relay call. `status` is the HTTP status (503 when no relay is reachable); `code` names a network failure
// (outbox.ts reads both). `maybeSent` is true when the request may have reached the relay anyway (a timeout, a
// server error). The original fetch error is not kept: it holds the URL, which holds the password.
class RelayError extends Error {
  constructor(message: string, readonly maybeSent: boolean, readonly status?: number, readonly code?: string) {
    super(message);
  }
}

type BBAttachment = { guid: string; transferName?: string; mimeType?: string; totalBytes?: number };
type BBMessage = {
  guid: string; text?: string | null; isFromMe?: boolean; isDelivered?: boolean; dateDelivered?: number; error?: number; dateCreated?: number; itemType?: number;
  handle?: { address?: string } | null; chats?: { guid: string }[]; attachments?: BBAttachment[];
  associatedMessageGuid?: string | null; threadOriginatorGuid?: string | null;
};

export class BlueBubbles implements AsyncIterable<Bubble> {
  private opts: typeof DEFAULTS;
  private health = new Map<Relay, { ok: boolean; at: number }>();
  private privateApi = new Map<Relay, { enabled: boolean; at: number }>();
  private seen = new Set<string>(); // message GUIDs handled by the bridge, oldest first, kept on disk
  private pending = new Set<string>(); // message GUIDs queued for the bridge and not handled yet
  private suspects = new Set<Relay>(); // relays whose last send may have gone out without an answer, to ask first
  private seenFile: string;
  private appended = 0;
  private queue: Bubble[] = [];
  private wake?: () => void;
  private chain = Promise.resolve();

  constructor(
    private relays: Relay[],
    dir: string,
    opts: Partial<typeof DEFAULTS> = {},
    private log: (line: string) => void = (line) => console.error(`fm-imessage: bluebubbles ${line}`),
  ) {
    if (!relays.length) throw new Error("fm-imessage: no BlueBubbles relay is set");
    this.opts = { ...DEFAULTS, ...opts };
    this.seenFile = `${dir}/bluebubbles-seen`;
    if (existsSync(this.seenFile)) {
      for (const line of readFileSync(this.seenFile, "utf8").split("\n")) {
        const guid = line.split(" ")[0]; // an older file has "guid date" lines
        if (guid) this.remember(guid);
      }
      this.compactSeen();
    }
  }

  // Start the catch-up queries: now, then every catchUpMs.
  start() {
    void this.catchUp();
    setInterval(() => void this.catchUp(), this.opts.catchUpMs);
  }

  async *[Symbol.asyncIterator]() {
    for (;;) {
      while (this.queue.length) yield this.queue.shift()!;
      await new Promise<void>((resolve) => (this.wake = resolve));
    }
  }

  // A webhook from any relay. Only "new-message" events matter; the reply is immediate.
  async webhook(req: Request): Promise<Response> {
    if (req.method !== "POST" || new URL(req.url).pathname !== "/bluebubbles") return new Response("not found\n", { status: 404 });
    // Only the GUID is used, and only after a type check: the message itself is read back from a relay.
    const event: { type?: unknown; data?: { guid?: unknown; isFromMe?: unknown } } = await req.json().catch(() => ({}));
    const guid = event.type === "new-message" && !event.data?.isFromMe ? event.data?.guid : undefined;
    if (typeof guid === "string") void this.accept(guid);
    return new Response("ok\n");
  }

  // One message read whole (content and attachments) from the first relay that has it.
  async message(guid: string): Promise<Bubble> {
    const built = await this.build(await this.read(guid), this.opts.downloadMs);
    if (!built) throw Object.assign(new Error(`message ${guid} has nothing to show`), { permanent: true });
    return built;
  }

  async separated(chat: string, guid: string): Promise<boolean> {
    const target = await this.read(guid);
    if (target?.guid !== guid || !Number.isFinite(target.dateCreated) || !target.chats?.some((c) => c.guid === chat)) {
      throw new RelayError("could not read the reply target's chat and time", false, 503);
    }
    let checked = false;
    let error: unknown;
    for (const r of await this.healthy()) {
      try {
        const found = await this.call(r, "POST", "message/query", undefined,
          { chatGuid: chat, sort: "DESC", limit: 1,
            where: [{ statement: "(message.associated_message_guid IS NULL OR message.associated_message_guid = '')", args: {} }] });
        if (!Array.isArray(found)) throw new RelayError("could not read chat history", false, 503);
        const message = found[0] as BBMessage | undefined;
        if (message && (typeof message.guid !== "string" || !Number.isFinite(message.dateCreated))) {
          throw new RelayError("could not read the chat message's GUID and time", false, 503);
        }
        if (message && message.guid !== guid && message.dateCreated! > target.dateCreated!) return true;
        checked = true;
      } catch (e) {
        error = e;
      }
    }
    if (error) throw error;
    if (!checked) throw new RelayError("could not check reply separation; no relay answered", false, 503);
    return false;
  }

  // Queue one message by GUID, once. `data` is the message when a query already read it. The GUID is only pending here:
  // it is kept on disk by markSeen, once the bridge has handled the message, so a crash before that lets the catch-up
  // find the message again. The inbound loop reads an attachment with the short call bound; the download queue keeps the
  // long one (message()).
  accept(guid: string, data?: BBMessage): Promise<void> {
    if (this.seen.has(guid) || this.pending.has(guid)) return this.chain;
    this.pending.add(guid);
    this.chain = this.chain.then(async () => {
      try {
        const built = await this.build(data ?? (await this.read(guid)), this.opts.callMs);
        if (built) this.push(built);
        else this.markSeen(guid);
      } catch (e) {
        this.pending.delete(guid); // a later webhook or catch-up tries again
        this.log(`could not read message ${guid}: ${e instanceof Error ? e.message : String(e)}`);
      }
    });
    return this.chain;
  }

  // The bridge has handled the message (filed its note, or ignored it): keep its GUID on disk, so it is not queued again.
  markSeen(guid: string) {
    this.pending.delete(guid);
    if (this.seen.has(guid)) return;
    try {
      this.remember(guid);
      appendFileSync(this.seenFile, `${guid}\n`, { mode: 0o600 });
      if (++this.appended > this.opts.seenMax) this.compactSeen();
    } catch (e) {
      this.log(`could not keep message ${guid} as seen: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // The bridge failed to handle the message: forget it, without keeping it as seen, so a later webhook or catch-up queues it again.
  release(guid: string) {
    this.pending.delete(guid);
  }

  // Ask every reachable relay for the messages of the last lookbackMs and accept each in order. The seen-set skips what
  // was filed already, so a message whose webhook was lost is found while it is still in the window.
  async catchUp() {
    const after = Date.now() - this.opts.lookbackMs;
    for (const r of await this.healthy()) {
      try {
        const found = (await this.call(r, "POST", "message/query", undefined,
          { after, sort: "DESC", limit: 500, with: ["chats", "attachments"] })) as BBMessage[];
        for (const m of found.reverse()) await this.accept(m.guid, m);
      } catch (e) {
        // An unreachable relay was already logged when it went down.
        if (!(e instanceof RelayError && (e.code || e.status === 503))) this.log(`catch-up failed: ${e instanceof Error ? e.message : String(e)}`);
      }
    }
  }

  // `guid` is the client GUID (BlueBubbles tempGuid). Reply behavior is described in docs/imessage.md.
  // A later relay in one call sends only after no relay shows the text as sent; a retry of
  // a failed call is the bridge's to check first (`sent`), because the outbox item keeps what may have gone out.
  async send(chat: string, text: string, replyTo?: string, guid?: string) {
    const started = Date.now();
    let maybeSent = false;
    let last: unknown = new RelayError("no relay is reachable", false, 503);
    for (const r of await this.healthy()) {
      try {
        const found = maybeSent ? await this.sent(chat, text, started) : undefined;
        const message = found ? { guid: found } : await this.call(r, "POST", "message/text", undefined,
          { chatGuid: chat, tempGuid: guid ?? crypto.randomUUID(), message: text, ...(replyTo && this.privateApi.get(r)?.enabled ? { selectedMessageGuid: replyTo, partIndex: 0 } : {}) }, this.opts.sendMs)
          .catch((e) => { if (e instanceof RelayError && e.maybeSent) this.suspects.add(r); throw e; }) as BBMessage;
        if (!message?.guid) throw new RelayError("the send returned no message id", true, 503);
        this.suspects.clear();
        return message.guid;
      } catch (e) {
        if (!(e instanceof RelayError)) throw e;
        maybeSent ||= e.maybeSent;
        last = maybeSent && !e.maybeSent ? new RelayError(e.message, true, e.status, e.code) : e;
      }
    }
    throw last;
  }

  // Put a tapback on a message. BlueBubbles has six; any other emoji fails with the list, as a permanent error so
  // the outbox moves it to the dead-letter folder instead of holding the queue.
  async react(chat: string, guid: string, emoji: string) {
    const reaction = TAPBACKS[emoji.trim()];
    if (!reaction) throw Object.assign(new Error(`no BlueBubbles tapback for ${emoji}; use one of ❤️ 👍 👎 😂 ‼️ ❓`), { permanent: true });
    await this.first((r) => this.call(r, "POST", "message/react", undefined, { chatGuid: chat, selectedMessageGuid: guid, reaction, partIndex: 0 }), true);
  }

  // Download an attachment from whichever relay has it. The bridge's download queue retries a failure.
  async download(guid: string, ms = this.opts.downloadMs): Promise<Buffer> {
    return (await this.first((r) => this.call(r, "GET", `attachment/${encodeURIComponent(guid)}/download`, { original: "true" }, undefined, ms, true))) as Buffer;
  }

  // The relay's own record of a message (see BBMessage); the API has no schema to check it against.
  private async read(guid: string): Promise<BBMessage> {
    return (await this.first((r) => this.call(r, "GET", `message/${encodeURIComponent(guid)}`, { with: "chats,attachments" }))) as BBMessage;
  }

  // Return the id of `text` in `chat` since `since`; presence alone does not confirm delivery.
  // Throw when no relay can be asked, so the caller does not send again unchecked.
  // Ask relays with a possibly-sent error first, regardless of health: other Macs' iCloud copies can lag.
  async sent(chat: string, text: string, since: number): Promise<string | undefined> {
    let asked = false;
    for (const r of new Set([...this.suspects, ...(await this.healthy())])) {
      let found: BBMessage | undefined;
      try {
        const recent = (await this.call(r, "GET", `chat/${encodeURIComponent(chat)}/message`,
          { after: String(since - this.opts.skewMs), sort: "DESC", limit: "50" })) as BBMessage[];
        asked = true;
        this.suspects.delete(r);
        found = recent.find((m) => m.isFromMe && m.text?.trim() === text.trim());
      } catch {
        continue;
      }
      if (found) {
        if (!found.guid) throw new RelayError("the earlier send has no message id", true, 503);
        return found.guid;
      }
    }
    if (!asked) throw new RelayError("could not check whether an earlier try was sent; no relay answered", true, 503);
    return undefined;
  }

  async delivered(chat: string, guid: string): Promise<boolean> {
    const message = await this.read(guid);
    if (!message.isFromMe || !message.chats?.some((c) => c.guid === chat)) throw new Error(`message ${guid} is not in the target chat`);
    if (message.error) throw Object.assign(new Error(`message ${guid} failed with send error ${message.error}`), { permanent: true });
    return message.isDelivered === true || (message.dateDelivered ?? 0) > 0;
  }

  // Start (POST) or stop (DELETE) the typing bubble in a chat.
  typing(chat: string, method: "POST" | "DELETE"): Promise<void> {
    // A typing error never fails or delays a send: it is logged as one line and dropped.
    return this.first((r) => this.call(r, method, `chat/${encodeURIComponent(chat)}/typing`), true).then(
      () => undefined,
      (e) => this.log(`typing failed: ${e instanceof Error ? e.message : String(e)}`),
    );
  }

  // Run `fn` on each eligible healthy relay in order until one succeeds. A permanent failure (HTTP 404) is final only when every
  // configured relay was asked and gave one; otherwise a relay that was down or cut off may still have the item, so the
  // error is a transient one and the caller tries again.
  private async first<T>(fn: (r: Relay) => Promise<T>, privateApiOnly = false): Promise<T | undefined> {
    const healthy = await this.healthy();
    const asked = privateApiOnly ? healthy.filter((r) => this.privateApi.get(r)?.enabled) : healthy;
    if (privateApiOnly && healthy.length && !asked.length) return;
    const errors: unknown[] = [];
    for (const r of asked) {
      try {
        return await fn(r);
      } catch (e) {
        errors.push(e);
      }
    }
    const last = errors.at(-1) ?? new RelayError("no relay is reachable", false, 503);
    if (permanent(last) && !(asked.length === this.relays.length && errors.every(permanent))) {
      throw new RelayError("a relay that was not asked or was cut off may still have it", false, 503);
    }
    throw last;
  }

  private async healthy(): Promise<Relay[]> {
    const ok = await Promise.all(this.relays.map(async (r) => {
      const h = this.health.get(r);
      const capability = this.privateApi.get(r);
      if (h && Date.now() - h.at < this.opts.healthMs && (!h.ok || (capability && Date.now() - capability.at < this.opts.healthMs))) return h.ok;
      try {
        const info = await this.call(r, "GET", "server/info", undefined, undefined, this.opts.pingMs) as { private_api?: boolean } | undefined;
        const enabled = info?.private_api === true;
        const was = this.privateApi.get(r)?.enabled;
        this.privateApi.set(r, { enabled, at: Date.now() });
        if (was !== enabled && (was !== undefined || !enabled)) {
          this.log(`${this.name(r)} Private API ${enabled ? "is on" : "is off; skipping typing and tapbacks, sending replies without a thread"}`);
        }
        return true;
      } catch {
        return false;
      }
    }));
    return this.relays.filter((_, i) => ok[i]);
  }

  private name(r: Relay) {
    return `relay ${this.relays.indexOf(r) + 1} (${new URL(r.url).host})`;
  }

  // Record a relay's health; a change is logged as one line.
  private mark(r: Relay, ok: boolean, why = "") {
    const was = this.health.get(r)?.ok;
    this.health.set(r, { ok, at: Date.now() });
    if (was !== ok && (was !== undefined || !ok)) this.log(`${this.name(r)} ${ok ? "is back" : `is down: ${why}`}`);
  }

  private async call(r: Relay, method: string, path: string, query: Record<string, string> = {}, body?: unknown,
    timeout = this.opts.callMs, binary = false): Promise<unknown> {
    const url = new URL(`api/v1/${path}`, r.url.endsWith("/") ? r.url : `${r.url}/`);
    for (const [k, v] of Object.entries(query)) url.searchParams.set(k, v);
    url.searchParams.set("password", r.password);
    const payload = body === undefined ? {} : { headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
    const res = await fetch(url, { method, ...payload, signal: AbortSignal.timeout(timeout) }).catch((e) => this.unreached(r, e, timeout));
    this.mark(r, true);
    if (!res.ok) {
      const detail = (await res.text().catch(() => "")).replace(/\s+/g, " ").slice(0, 200);
      throw new RelayError(`${this.name(r)}: HTTP ${res.status} ${detail}`.trim(), res.status >= 500, res.status);
    }
    if (binary) {
      return Buffer.from(await res.arrayBuffer().catch((e) => {
        const timedOut = e instanceof Error && e.name === "TimeoutError";
        throw new RelayError(`${this.name(r)}: download interrupted${timedOut ? ` after ${timeout} ms` : ""}`, false, undefined, timedOut ? "ETIMEDOUT" : "ECONNRESET");
      }));
    }
    const json: unknown = await res.json().catch(() => {
      throw new RelayError(`${this.name(r)}: unreadable answer, HTTP ${res.status}`, true, res.status);
    });
    return json && typeof json === "object" && "data" in json ? json.data : undefined;
  }

  // A relay that gave no answer: marked down, and the error without the fetch error, whose URL holds the password.
  private unreached(r: Relay, e: unknown, timeout: number): never {
    const refused = e instanceof Error && "code" in e && (e.code === "ECONNREFUSED" || e.code === "ConnectionRefused");
    const code = e instanceof Error && e.name === "TimeoutError" ? "ETIMEDOUT" : refused ? "ECONNREFUSED" : "ENETUNREACH";
    const why = { ETIMEDOUT: `no answer in ${timeout} ms`, ECONNREFUSED: "connection refused", ENETUNREACH: "unreachable" }[code];
    this.mark(r, false, why);
    throw new RelayError(`${this.name(r)}: ${why}`, code !== "ECONNREFUSED", undefined, code);
  }

  private remember(guid: string) {
    this.seen.add(guid);
    for (const old of this.seen) {
      if (this.seen.size <= this.opts.seenMax) break;
      this.seen.delete(old);
    }
  }

  private compactSeen() {
    writeFileSync(this.seenFile, [...this.seen].map((g) => `${g}\n`).join(""), { mode: 0o600 });
    this.appended = 0;
  }

  private push(m: Bubble) {
    this.queue.push(m);
    this.wake?.();
    this.wake = undefined;
  }

  // The bridge's view of one BlueBubbles message, or undefined for one with nothing to show.
  private async build(m: BBMessage, downloadMs: number): Promise<Bubble | undefined> {
    const chat = m.chats?.[0]?.guid;
    if (!chat) return undefined;
    if (m.associatedMessageGuid) return this.wrap(m, chat, { type: "reaction" } as Content);
    // Messages puts U+FFFC in the text where each attachment sits.
    const text = (m.text ?? "").replace(/\uFFFC/g, "").trim();
    const parts: Content[] = [
      ...(text ? [{ type: "text", text } as Content] : []),
      ...(m.attachments ?? []).map((a) => this.attachment(a, downloadMs)),
    ];
    if (!parts.length) return undefined;
    let content = parts.length === 1 ? parts[0]! : ({ type: "group", items: parts.map((c) => ({ content: c })) } as unknown as Content);
    if (m.threadOriginatorGuid) {
      const target = await this.first((r) => this.call(r, "GET", `message/${encodeURIComponent(m.threadOriginatorGuid!)}`)).then(
        (t) => ({ type: "text", text: ((t as BBMessage).text ?? "").replace(/\uFFFC/g, "").trim() }),
        () => ({ type: "unknown" }),
      );
      content = { type: "reply", content, target: { content: target } } as unknown as Content;
    }
    return this.wrap(m, chat, content);
  }

  private attachment(a: BBAttachment, downloadMs: number): Content {
    const c = { type: "attachment", id: a.guid, name: a.transferName || "file", mimeType: a.mimeType || "application/octet-stream", size: a.totalBytes,
      read: () => this.download(a.guid, downloadMs) };
    return c as unknown as Content;
  }

  private wrap(m: BBMessage, chat: string, content: Content): Bubble {
    const space = {
      id: chat,
      send: (text: string) => this.send(chat, text),
      startTyping: () => this.typing(chat, "POST"),
      stopTyping: () => this.typing(chat, "DELETE"),
    };
    return {
      id: m.guid,
      content,
      direction: m.isFromMe ? "outbound" : "inbound",
      timestamp: m.dateCreated ? new Date(m.dateCreated) : undefined,
      sender: { id: m.handle?.address ?? "" },
      space,
      react: (emoji: string) => this.react(chat, m.guid, emoji),
      reply: (text: string) => this.send(chat, text, m.guid),
      read: () => this.first((r) => this.call(r, "POST", `chat/${encodeURIComponent(chat)}/read`)),
    };
  }
}
