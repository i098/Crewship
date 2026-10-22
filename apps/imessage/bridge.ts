// Two-way iMessage between the owner and Firstmate over the transports that FM_IMESSAGE_TRANSPORTS lists in order:
//   photon (the default), the line of a Photon Spectrum project, and bluebubbles, self-hosted BlueBubbles servers on
//   Macs (bluebubbles.ts). See routes for outbound transport selection and docs/imessage.md for the routing contract.
// Inbound routing: docs/imessage.md#what-it-does. Save each request before transport acknowledgement.
// Outbound: POST text to http://127.0.0.1:$FM_IMESSAGE_PORT/send (the fm-imessage command does this).
//   The text goes to a durable outbox (outbox.ts) and the answer comes once it is on disk; one loop sends the outbox
//   in order, as plain messages by default, and tries again with backoff while the upstream
//   fails. Measured on the free shared line: plain sends into the owner's own conversation work, while a
//   conversation the service opened itself was refused. That text's conversation and message ids are kept in the
//   state directory, so a restart can still reach him.
// Photos: POST a multipart form to /image (fm-imessage --image). image.ts checks and downscales it, and the file waits in
//   the state directory while its outbox item is delivered. Photon only: the bridge has no BlueBubbles attachment send.
// Voice: a voice memo or audio attachment is saved, then transcribed by local whisperx (transcribe.ts). The note reads
//   "[voice memo, Ns] <words>" and the saved path, or the path and "transcription failed". Sends are not held up by it;
//   the next inbound message waits for it.
// Location: when he shares his location with the Photon line in Find My, GET /location (the fm-location command).
// Edits: spectrum-ts drops the Photon line's message.edited events, so the bridge reads them from that line's own
//   client and files each edit as a new note, "[edited] <new text> (was: <old text>)".
// Cards: POST card JSON to /card (fm-imessage --card). The bubble is a Spectrum app card that opens
//   FM_IMESSAGE_CARD_URL/c/<token>, which a second, card-only listener on 127.0.0.1:FM_IMESSAGE_CARD_PORT serves
//   (cards.ts). A pick files "[iMessage card pick] <key>: <choice>" and edits the bubble in place.
// Instagram: with INSTAGRAM_DM_BACKEND=graph, that listener also takes Meta's DM webhook on /instagram/webhook
//   (instagram-webhook.ts).
// Runs as the systemd --user service fm-imessage (docs/imessage.md). Docs: https://photon.codes/docs/spectrum-ts
import { AsyncLocalStorage } from "node:async_hooks";
import { appendFileSync, closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, rmSync, truncateSync, writeFileSync, writeSync } from "node:fs";
import type { AdvancedIMessage, EventTypeMap } from "@photon-ai/advanced-imessage/grpc";
import { app as appCard, attachment, edit, Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import { BlueBubbles } from "./bluebubbles.ts";
import { cardLayout, cardRoutes, Cards, letter, type Layout, parseCard, type Stored } from "./cards.ts";
import { basicAnswer, bubbles, compactChat, describe, type DeskProc, DeskTiming, deskInput, deskPrompt, failover, inbound, type LineMessage, localCommand, notSent, type Route, readDesk, type Saveable, socialOnly, spawnDesk, typingPause, voiceAnswer, VOICE_PROMPT } from "./desk.ts";
import { ImageError, type Picture, type PreparedImage, prepareImage } from "./image.ts";
import { instagramWebhook } from "./instagram-webhook.ts";
import { type Kind, Memory } from "./memory.ts";
import { brief, permanent, Queue, transient } from "./outbox.ts";
import { listenFrom, transcribe } from "./transcribe.ts";

let stopping = false;
const children = new Set<Bun.Subprocess>();
function track<T extends Bun.Subprocess>(proc: T): T {
  children.add(proc);
  void proc.exited.finally(() => children.delete(proc));
  return proc;
}

async function stop() {
  if (stopping) return;
  stopDeskTyping?.();
  stopping = true;
  const running = [...children];
  for (const proc of running) proc.kill("SIGTERM");
  await Promise.race([Promise.all([deskTypingPending, ...running.map((proc) => proc.exited)]), Bun.sleep(2000)]);
  for (const proc of children) proc.kill("SIGKILL");
  // Reap killed children, but do not let a stuck child hold the bridge open.
  await Promise.race([Promise.all([...children].map((proc) => proc.exited)), Bun.sleep(500)]);
  process.exit(0);
}
process.on("SIGTERM", () => void stop());
process.on("SIGINT", () => void stop());

function persistLatest(path: string, text: string) {
  try {
    writeFileSync(`${path}.tmp`, text, { mode: 0o600 });
    renameSync(`${path}.tmp`, path);
  } catch (e) {
    log("persist the latest text")(e);
  }
}
const env = process.env;
const need = (name: string) => env[name] || (() => { throw new Error(`fm-imessage: ${name} is not set`); })();
// Spectrum has no request-timeout option. Scope this wrapper to startup so token renewals keep their own deadlines.
const photonRequests = new AsyncLocalStorage<{ active: boolean }>();
const fetchRequest = globalThis.fetch;
globalThis.fetch = Object.assign((input: RequestInfo | URL, init?: RequestInit) => {
  if (!photonRequests.getStore()?.active) return fetchRequest(input, init);
  const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined);
  const timeout = AbortSignal.timeout(3000);
  return fetchRequest(input, { ...init, signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
}, fetchRequest);
const OWNER = need("FM_IMESSAGE_OWNER");
const FM_HOME = need("FM_HOME");
const INBOX = env.FM_INBOX_CMD || `${FM_HOME}/bin/fm-inbox.sh`;
const PORT = Number(env.FM_IMESSAGE_PORT || 8765);
const TRANSPORTS = (env.FM_IMESSAGE_TRANSPORTS || "photon").split(/\s+/).filter(Boolean);
const DESK_PROVIDER = env.FM_IMESSAGE_DESK_PROVIDER || "omp";
const DESK_MODEL = env.FM_IMESSAGE_DESK_MODEL || "claude-haiku-5-5";
const DESK_REASONING = env.FM_IMESSAGE_DESK_REASONING || "off";
// The desks vetted for direct answers; any other provider and model hands every request to Firstmate.
const DESK_VETTED = ["omp claude-haiku-5-5", "inception mercury-3"].includes(`${DESK_PROVIDER} ${DESK_MODEL}`);
const SUPERVISOR_MODEL = env.FM_IMESSAGE_SUPERVISOR_MODEL || "";
const DESK_PROMPT = deskPrompt(env.FM_IMESSAGE_OWNER_NAME || "the owner", DESK_MODEL, SUPERVISOR_MODEL);
// Only the test suite may override the short quiet period and the burst cap.
const QUIET_MS = env.FM_IMESSAGE_TEST === "1" && env.FM_IMESSAGE_TEST_QUIET_MS ? Number(env.FM_IMESSAGE_TEST_QUIET_MS) : 350;
const MAX_WAIT_MS = env.FM_IMESSAGE_TEST === "1" && env.FM_IMESSAGE_TEST_MAX_WAIT_MS ? Number(env.FM_IMESSAGE_TEST_MAX_WAIT_MS) : 2000;
const RETRY_MS = Number(env.FM_IMESSAGE_RETRY_MS || 1000); // the first retry step of the outbox and the downloads
const REACT_MAX_MS = Number(env.FM_IMESSAGE_REACT_MAX_MS || 120_000); // a tapback older than this is dropped, not retried
// systemd's StateDirectory= sets STATE_DIRECTORY; the directory is private to the account.
const STATE = env.STATE_DIRECTORY || `${env.HOME}/.local/state/fm-imessage`;
const LATEST_FILE = `${STATE}/latest`;
const DESK_DIR = `${STATE}/desk`; // empty cwd: no project context files load
const DESK_LOG = `${STATE}/desk.log`; // what the desk did, for Firstmate to read
const ATTACH_DIR = `${STATE}/attachments`; // his files, for Firstmate to open
const MEMORY_DIR = `${STATE}/memory`; // the desk's memory: the whole chat, word for word (memory.ts)
const OUTBOX_DIR = `${STATE}/outbox`; // sends and tapbacks not delivered yet, one file each (outbox.ts)
const DOWNLOADS_DIR = `${STATE}/downloads`; // his messages with an attachment not saved yet
const OUTGOING_DIR = `${STATE}/outgoing`; // photos for the outbox, until every bubble of their item is sent
const CARD_URL = env.FM_IMESSAGE_CARD_URL?.replace(/\/+$/, ""); // cards are off without it
const CARD_PORT = Number(env.FM_IMESSAGE_CARD_PORT || 8767);
const listen = listenFrom(env, track); // voice memos and audio attachments are transcribed here (transcribe.ts)
const cards = CARD_URL ? new Cards(`${STATE}/cards`) : undefined; // one file per card, token as its name
const IG_MISSING = ["INSTAGRAM_GRAPH_APP_SECRET", "INSTAGRAM_GRAPH_VERIFY_TOKEN"].filter((name) => !env[name]);
if (env.INSTAGRAM_DM_BACKEND === "graph" && IG_MISSING.length) console.error(`fm-imessage: the Instagram webhook is off: set ${IG_MISSING.join(" and ")}`);
// Meta's DM webhook, on the card listener (instagram-webhook.ts); off unless the graph backend is fully set.
const igWebhook = env.INSTAGRAM_DM_BACKEND === "graph" && !IG_MISSING.length ? instagramWebhook({
  appSecret: env.INSTAGRAM_GRAPH_APP_SECRET!,
  verifyToken: env.INSTAGRAM_GRAPH_VERIFY_TOKEN!,
  operator: env.INSTAGRAM_DM_OPERATOR || "",
  log: env.INSTAGRAM_DM_LOG || `${env.INSTAGRAM_DM_DIR || `${env.HOME}/.local/state/instagram-dm`}/messages.jsonl`,
  notify: (env.INSTAGRAM_DM_NOTIFY || "").split(/\s+/).filter(Boolean),
  say: (line) => console.log(`fm-imessage: ${line}`),
}) : undefined;
for (const dir of [STATE, DESK_DIR, ATTACH_DIR, OUTGOING_DIR]) mkdirSync(dir, { recursive: true, mode: 0o700 });
const recent: Ref[] = []; // his last texts, newest last, for a threaded reply to one a few bubbles up
const said = new Map<string, string>(); // his last 100 texts by message id, for the "was:" part of an edit note
// One line for a transient upstream failure; the whole error, with its stack, for anything else.
const log = (what: string) => (e: unknown) =>
  transient(e) ? console.error(`fm-imessage: ${what}: ${brief(e)}`) : console.error(`fm-imessage: ${what}:`, e);
// Typing bubbles are best effort: an error is logged and never fails or delays a send.
const typing = (space: LineMessage["space"] | undefined, on: boolean) => {
  if (!space) return;
  deskTypingPending = deskTypingPending.then(() => {
    if (!stopping) return on ? space.startTyping() : space.stopTyping();
  }).catch(log(on ? "start typing" : "stop typing"));
};
// This service is the memory's one writer: systemd runs one instance of the unit.
const memory = new Memory(MEMORY_DIR, (system) => compactChat(system, () => stopping, track), log("memory"));
const memoryByRequest = new Map<string, number>();
for (const message of memory.msgs) if (message.requestId) memoryByRequest.set(message.requestId, message.i);
const desk = new DeskTiming(QUIET_MS, (current) => void runDesk(current).catch((e) => {
  log("desk failed")(e);
  handoffPending();
}), undefined, MAX_WAIT_MS);
let deskRun: Bun.Subprocess | undefined;
let stopDeskTyping: (() => void) | undefined;
let deskTypingRequestId: string | undefined;
let deskTypingPending: Promise<unknown> = Promise.resolve();
let inboxStatus: Promise<{ status: string; statusOk: boolean } | void>;

// A message by its transport, conversation and message ids, which outlive a restart. An item queued before there
// were transports has no `line` and is Photon's.
type Ref = { line?: string; space: string; id: string };
// One outbox item for his text `id`: bubbles followed by an optional tapback; `done` counts sent bubbles.
// The first bubble threads to his text `reply` when set. A photo in `image` is bubble 0, before text bubbles.
// `kind` selects the memory author (Firstmate unless "desk"); `silent` omits the text memory record.
// `guid` identifies sends (BlueBubbles tempGuid) and deduplicates text memory. `at` is the queue time.
// `maybe` maps each transport to the chat where the current bubble or reaction may already exist.
// `since` records when the text attempt started.
// `card` is the token of a card to send, or to edit in place once it is out.
type Out = Ref & { react?: string; bubbles?: string[]; image?: Picture; done?: number; reply?: string; kind?: Kind; silent?: boolean; guid?: string; at?: number; maybe?: Record<string, string>; since?: number; card?: string; requestId?: string; requests?: string[] };
type Received = { requestId: string; text: string; authored?: string; ref: Ref; memoryId: number; firstmate: boolean };
type Routing = Received & { route: "pending" | "handoff" | "desk" | "done"; out?: Out };
type DeskResult = { answer: { answer: string } | { react: string; text?: string }; target: Routing };
type RouteEvent = { received: Received } | { ids: string[]; route: Routing["route"]; out?: Out };
const ROUTING_LOG = `${STATE}/routing.jsonl`;
const routing = new Map<string, Routing>();
let routingRetry: NodeJS.Timeout | undefined;
type Bubble = string | Picture;
// One transport. `find` reads a message whole (with its attachments); `send` sends one bubble into a conversation,
// threaded to message `reply` when set; `home` is a conversation with him that works before he texts this transport;
// `latest` is his latest text on it.
type Line = {
  name: string;
  messages: AsyncIterable<LineMessage>;
  find(ref: Ref): Promise<LineMessage>;
  separated(space: string, id: string): Promise<boolean>;
  send(space: string, text: string, reply?: string, guid?: string): Promise<unknown>;
  sendImage?(space: string, picture: Picture, reply?: string): Promise<unknown>; // Photon only
  sendCard?(space: string, url: string, layout: Layout, live?: boolean, session?: unknown): Promise<unknown>; // Photon only; returns the card session
  sent?(space: string, text: string, since: number): Promise<boolean>;
  react(ref: Ref, emoji: string, beforeSend: () => void): Promise<unknown>;
  markSeen?(id: string): void; // the bridge has handled message `id`; a transport that keeps its own seen-set stores it
  release?(id: string): void; // the bridge failed to handle message `id`; the transport may deliver it again
  home?: string;
  latest?: Ref;
};
let raw: AdvancedIMessage | undefined; // the Find My client (Photon only)
const lines: Line[] = [];
async function startLine(name: string): Promise<Line> {
  if (name === "bluebubbles") {
    // FM_BLUEBUBBLES_RELAYS: "url,VARIABLE" items, space-separated, in failover order. VARIABLE names the environment
    // variable (from ~/super.env) that holds that relay's password.
    const relays = need("FM_BLUEBUBBLES_RELAYS").split(/\s+/).filter(Boolean).map((item) => {
      const [url = "", variable = ""] = item.split(",");
      return { url, password: need(variable) };
    });
    const bb = new BlueBubbles(relays, STATE);
    // The relays post their webhooks to this address:port; bluebubbles.ts reads each message back with the password.
    const listen = new URL(`http://${need("FM_BLUEBUBBLES_WEBHOOK")}`);
    Bun.serve({ hostname: listen.hostname, port: Number(listen.port), fetch: (req) =>
      stopping ? new Response("stopping\n", { status: 503 }) : bb.webhook(req) });
    bb.start();
    return {
      name,
      messages: bb,
      find: (ref) => bb.message(ref.id),
      separated: (space, id) => bb.separated(space, id),
      send: (space, text, reply, guid) => bb.send(space, text, reply, guid),
      sent: (space, text, since) => bb.sent(space, text, since),
      markSeen: (id) => bb.markSeen(id),
      release: (id) => bb.release(id),
      react: (ref, emoji, beforeSend) => bb.react(ref.space, ref.id, emoji, beforeSend),
      home: `iMessage;-;${OWNER}`,
    };
  }
  const startup = { active: true };
  const app = await photonRequests.run(startup, async () => {
    try {
      return await Spectrum({
        projectId: need("PHOTON_PROJECT_ID"),
        projectSecret: need("PHOTON_PROJECT_SECRET"),
        providers: [imessage.config()],
      });
    } finally {
      startup.active = false;
    }
  });
  // Spectrum has no public accessor for the line's Advanced iMessage client, which owns Find My locations and the raw
  // message events with his edits; this reads its internal platform map (spectrum-ts 12.10). Recheck after a
  // spectrum-ts upgrade.
  const internals = Reflect.get(app, "__internal") as { platforms?: Map<string, { client?: { client?: AdvancedIMessage }[] }> } | undefined;
  raw = internals?.platforms?.get?.("imessage")?.client?.[0]?.client;
  if (!raw) console.warn("fm-imessage: no Advanced iMessage client in spectrum-ts internals; GET /location and edits are off until the bridge is updated for this spectrum-ts");
  const find = async (ref: Ref) => {
    const message = await (await imessage(app).space.get(ref.space)).getMessage(ref.id);
    if (!message) throw new Error(`message ${ref.id} not found`);
    return message;
  };
  const photon = raw;
  // A reply target that is gone sends the bubble unthreaded.
  const threadOf = async (space: string, reply?: string) => reply ? await find({ space, id: reply }).catch((e) => {
    if (!permanent(e)) throw e;
    console.error(`fm-imessage: reply target ${reply} gone, sending unthreaded: ${brief(e)}`);
  }) : undefined;
  return {
    name,
    messages: (async function* () {
      if (photon) void watchEdits(photon);
      for await (const [, message] of app.messages) yield message;
    })(),
    find,
    async separated(space, id) {
      if (!photon) throw new Error("cannot check reply separation: Photon chat client is unavailable");
      const last = (await photon.chats.get(space)).lastMessage?.guid;
      return !!last && last !== id;
    },
    async send(space, text, reply) {
      const thread = await threadOf(space, reply);
      return thread ? thread.reply(text) : (await imessage(app).space.get(space)).send(text);
    },
    async sendImage(space, picture, reply) {
      const content = attachment(picture.path, { name: picture.name, mimeType: picture.mimeType });
      const thread = await threadOf(space, reply);
      return thread ? thread.reply(content) : (await imessage(app).space.get(space)).send(content);
    },
    // A card goes out once as an app bubble; with its card session, the same bubble is edited in place.
    async sendCard(space, url, layout, live, session) {
      const chat = await imessage(app).space.get(space);
      const content = appCard(url, { layout, ...(live === undefined ? {} : { live }) });
      if (!session) return Reflect.get((await chat.send(content)) ?? {}, "miniAppCardSession");
      // The edit reads only the target's card session, and its send replaces that with the next session.
      const target = { id: Reflect.get(session as object, "messageGuid"), direction: "outbound", content: { type: "app" }, miniAppCardSession: session };
      await chat.send(edit(content, target as never));
      return target.miniAppCardSession;
    },
    react: async (ref, emoji, beforeSend) => {
      const message = await find(ref).catch((e: unknown) => {
        throw Object.assign(e instanceof Error ? e : new Error(String(e)), { maybeSent: false });
      });
      beforeSend();
      return message.react(emoji);
    },
  };
}
const startups = TRANSPORTS.map((name) => {
  if (!["photon", "bluebubbles"].includes(name)) throw new Error(`fm-imessage: unknown transport ${name}`);
  const notReady = async (): Promise<never> => {
    throw Object.assign(new Error(`${name} is not ready`), { status: 503, maybeSent: false });
  };
  const line: Line = {
    name, find: notReady, separated: notReady, send: notReady, react: notReady,
    ...(name === "photon" ? { sendCard: notReady, sendImage: notReady } : {}),
    messages: (async function* () {
      const ready = await started;
      if (ready) yield* ready.messages;
    })(),
  };
  lines.push(line);
  const started = startLine(name).then((ready) => {
    Object.assign(line, ready);
    return ready;
  }).catch((e) => {
    if (TRANSPORTS.length === 1) throw e;
    console.error(`fm-imessage: ${name} did not start, using the other transports: ${brief(e)}`);
  });
  return started;
});
await startups[0];
// A configured transport, including one whose startup has not completed.
const lineOf = (ref: Ref) => lines.find((line) => line.name === (ref.line ?? "photon"));
// A Ref on a transport; a Photon one has no `line`, the same as the items queued before there were transports.
const refOn = (name: string, space: string, id: string): Ref => (name === "photon" ? { space, id } : { line: name, space, id });
// Each transport's latest text, kept so a restart can still reach him: space, id and time, one per line.
// Photon keeps the file name it always had. A file without the time (the older format) counts as the oldest.
const latestFile = (name: string) => (name === "photon" ? LATEST_FILE : `${LATEST_FILE}-${name}`);
let latest: LineMessage | undefined; // his latest text on any transport: command typing and tapbacks go there
let latestRef: Ref | undefined; // the ids of `latest`, kept even when it cannot be fetched after a restart
let latestAt = -1;
let proactiveRef: Ref | undefined;
let proactiveAt = -1;
const directChat = /^[^;]+;-;[^;]+$/;
for (const name of TRANSPORTS) {
  for (const suffix of ["", "-direct"]) {
    const saved = Bun.file(`${latestFile(name)}${suffix}`);
    if (!(await saved.exists())) continue;
    const [space = "", id = "", time = ""] = (await saved.text()).trim().split("\n");
    const ref = refOn(name, space, id);
    const at = Number(time) || 0;
    if (!suffix) {
      const line = lineOf(ref);
      if (line) line.latest = ref;
      if (at > latestAt) [latestRef, latestAt] = [ref, at];
    }
    if (directChat.test(space) && at > proactiveAt) [proactiveRef, proactiveAt] = [ref, at];
  }
}
const outbox = new Queue<Out>(OUTBOX_DIR, "outbox item", deliver, RETRY_MS, lostDeskAnswer, (o) => o.requestId);
const downloads = new Queue<Ref>(DOWNLOADS_DIR, "attachment download", fetchAgain, RETRY_MS, (ref) => {
  if (!fileNote(`${ref.line ?? "photon"}-${ref.id}-lost`, `(an earlier attachment of message ${ref.id} could not be saved; the bridge gave up, so no path will follow)`)) {
    console.error(`fm-imessage: the inbox note for the lost attachment of message ${ref.id} failed`);
  }
});

// Replay routing before a transport can release ownership. A torn final line was never acknowledged.
if (existsSync(ROUTING_LOG)) {
  const saved = readFileSync(ROUTING_LOG, "utf8");
  const rows = saved.split("\n");
  let torn = false;
  for (let i = 0; i < rows.length; i++) {
    if (!rows[i]) continue;
    try { applyRoute(JSON.parse(rows[i])); }
    catch (e) {
      if (i !== rows.length - 1) throw e;
      log("torn routing tail")(e);
      torn = true;
    }
  }
  if (torn) truncateSync(ROUTING_LOG, Buffer.byteLength(saved.slice(0, saved.lastIndexOf("\n") + 1)));
  else if (saved && !saved.endsWith("\n")) appendFileSync(ROUTING_LOG, "\n");
}
for (const item of routing.values()) ensureRemembered(item);
flushRoutes();
if (pendingRoutes().length) {
  prefetchInboxStatus();
  desk.inboundText();
}

// Stop a pending or running desk turn: he sent more, or Firstmate is active on the line.
function cancelDesk() {
  stopDeskTyping?.();
  if (!deskRun) return;
  deskRun.kill();
  deskRun = undefined;
}

Bun.serve({
  hostname: "127.0.0.1",
  port: PORT,
  async fetch(req) {
    if (stopping) return new Response("stopping\n", { status: 503 });
    if (!localCommand(req.headers, PORT)) return new Response("forbidden\n", { status: 403 });
    const url = new URL(req.url);
    if (req.method === "GET" && url.pathname === "/location") {
      if (!raw) return new Response("no location: it needs the photon transport and a spectrum-ts whose location client the bridge can reach\n", { status: 503 });
      try {
        return Response.json(await raw.locations.get(OWNER));
      } catch (e) {
        return new Response(`no location: ${e instanceof Error ? e.message : String(e)}; he shares it with the line in Find My\n`, { status: 503 });
      }
    }
    if (req.method !== "POST" || !["/send", "/image", "/typing", "/react", "/card"].includes(url.pathname)) return new Response("not found", { status: 404 });
    const ref = latestRef;
    if (!ref) return new Response("no text from the owner yet; he must text the line first\n", { status: 503 });
    // Any Firstmate activity on the line means the real answer is coming, so the desk stands down.
    desk.firstmateActive();
    handoffPending();
    cancelDesk();
    if (url.pathname === "/typing") {
      typing(latest?.space, true);
      return new Response("typing\n");
    }
    if (url.pathname === "/react") {
      const emoji = (await req.text()).trim();
      if (!emoji) return new Response("no emoji", { status: 400 });
      return queue({ ...ref, react: emoji }, `tapback ${emoji}`);
    }
    if (url.pathname === "/card") {
      if (!cards) return new Response("nothing queued: cards are off; set FM_IMESSAGE_CARD_URL\n", { status: 503 });
      let card;
      try {
        card = parseCard(await req.text());
      } catch (e) {
        return new Response(`nothing queued: ${e instanceof Error ? e.message : String(e)}\n`, { status: 400 });
      }
      // Like a proactive text, a card goes to his latest direct chat. Only Photon can send an app bubble.
      const chat = proactiveRef;
      if (!chat || !lineOf(chat) || (card.app && !lineOf(chat)!.sendCard)) return new Response(`nothing queued: ${card.app ? "an app card needs his latest direct chat on the photon transport" : "no direct chat with him yet"}\n`, { status: 503 });
      return queue({ ...chat, card: cards.add(card, chat).token }, `card ${card.key}`);
    }
    // /image is a multipart form: the file `image` and the optional text `caption`, sent as bubbles after the photo.
    const form = url.pathname === "/image" ? await req.formData().catch(() => new FormData()) : undefined;
    const photo = form && await photoOf(form);
    if (photo instanceof Response) return photo;
    const parts = bubbles(form ? String(form.get("caption") ?? "") : await req.text());
    if (!parts.length && !photo) return new Response("empty message", { status: 400 });
    // ?reply=N targets his Nth latest text. ?no-thread forces plain, even with an explicit target.
    const replyTo = Number(url.searchParams.get("reply") ?? 0);
    const target = replyTo > 0 ? recent[recent.length - replyTo] : undefined;
    if (replyTo > 0 && !target) return new Response(`nothing queued: only ${recent.length} text(s) kept since the service started\n`, { status: 400 });
    // A threaded reply goes out on the transport and in the conversation of the text it replies to.
    const destination = target ?? proactiveRef;
    if (!destination) return new Response("no direct text from the owner yet; he must text the line first\n", { status: 503 });
    const image = photo && stage(photo);
    const what = [image && `image ${image.name}${photo?.resized ? " (downscaled)" : ""}`, parts.length && `${parts.length} bubble(s)`].filter(Boolean).join(" and ");
    return queue({ ...destination, image, bubbles: parts, reply: url.searchParams.has("no-thread") ? undefined : target?.id }, what);
  },
});

// The photo of an /image request, checked and downscaled, or the refusal to answer with.
async function photoOf(form: FormData): Promise<PreparedImage | Response> {
  const file = form.get("image");
  if (!(file instanceof File)) return new Response("nothing queued: no image in the request\n", { status: 400 });
  if (!lines.some((line) => line.sendImage)) return new Response("nothing queued: photos need the photon transport, which is not running\n", { status: 503 });
  try {
    return await prepareImage(await file.bytes(), file.name);
  } catch (e) {
    if (e instanceof ImageError) return new Response(`nothing queued: ${e.message}\n`, { status: 400 });
    throw e;
  }
}
if (cards || igWebhook) {
  const routes = cards ? cardRoutes(cards, picked) : () => new Response("not found\n", { status: 404 });
  // This port is public through the tunnel: no debug page, and no error line that names a token. Meta's webhook
  // payloads pass 4 KiB, so the body limit is larger with the webhook on.
  Bun.serve({ hostname: "127.0.0.1", port: CARD_PORT, maxRequestBodySize: igWebhook ? 65536 : 4096, development: false,
    fetch: (req) => stopping ? new Response("stopping\n", { status: 503 })
      : igWebhook && new URL(req.url).pathname === "/instagram/webhook" ? igWebhook(req) : routes(req),
    error(e) {
      console.error(`fm-imessage: card page failed: ${brief(e).replace(/[A-Za-z0-9_-]{43}/g, "<token>")}`);
      return new Response("error\n", { status: 500 });
    } });
  if (cards) console.log(`fm-imessage: card pages on 127.0.0.1:${CARD_PORT} for ${CARD_URL}`);
  if (igWebhook) console.log(`fm-imessage: Instagram webhook on 127.0.0.1:${CARD_PORT}/instagram/webhook`);
}
console.log(`fm-imessage: listening on 127.0.0.1:${PORT}, latest text ${latest ? "restored" : latestRef ? "known by id" : "unknown"}`);
if (latestRef) {
  const ref = latestRef;
  void startups[TRANSPORTS.indexOf(ref.line ?? "photon")]?.then((line) => line?.find(ref)).then((message) => {
    if (latestRef === ref) latest = message;
  }).catch(log("could not restore the latest text; sends still go to it"));
}

// Puts one item in the outbox and answers once the item is on disk.
function queue(item: Out, what: string) {
  if (stopping) return new Response("stopping\n", { status: 503 });
  put(item);
  return new Response(`queued ${what}; the bridge sends in order and retries while the upstream fails\n`);
}

// Saves a photo for the outbox. The file is synced to disk before the item that names it is queued.
function stage(photo: PreparedImage): Picture {
  const path = `${OUTGOING_DIR}/${crypto.randomUUID()}-${photo.name}`;
  const fd = openSync(path, "w", 0o600);
  try {
    writeSync(fd, photo.bytes);
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  return { path, name: photo.name, mimeType: photo.mimeType };
}

// Puts one item in the outbox with a client GUID of its own.
function put(item: Out) {
  if (stopping) return;
  outbox.add({ guid: crypto.randomUUID(), at: Date.now(), ...item });
}

function finishDeskDelivery(o: Out) {
  if (o.requestId && o.requestId === deskTypingRequestId) stopDeskTyping?.();
}

async function deliver(o: Out, save: (o: Out) => void) {
  if (stopping) throw new Error("bridge stopping");
  const kind = o.kind ?? "supervisor";
  if (o.card) return deliverCard(o, kind);
  const parts: Bubble[] = [...(o.image ? [o.image] : []), ...(o.bubbles ?? [])];
  if (parts.length && !o.guid) save((o = { ...o, guid: crypto.randomUUID() }));
  for (let i = o.done ?? 0; i < parts.length; i++) {
    const part = parts[i]!;
    if (i > 0 && typeof part === "string") {
      deliveryTyping(kind, true);
      await Bun.sleep(typingPause(part));
    }
    deliveryTyping(kind, false);
    await sendBubble(o, i, part, save);
    finishDeskDelivery(o);
    save((o = { ...o, done: i + 1, maybe: undefined, since: undefined }));
  }
  const text = deliveredText(o);
  if (text !== undefined) remember(kind, text, `outbox-text-${o.guid}`);
  if (o.react) return deliverReaction(o, save);
  if (o.image) rmSync(o.image.path, { force: true });
}

function deliveryTyping(kind: Kind, on: boolean) {
  if (latest && kind !== "desk" && !stopDeskTyping) typing(latest.space, on);
}

function deliveredText(o: Out) {
  if (o.silent || (!o.image && !o.bubbles?.length)) return;
  return [...(o.image ? [`[image: ${o.image.name}]`] : []), ...(o.bubbles ?? [])].join("\n\n");
}

async function deliverReaction(o: Out, save: (o: Out) => void) {
  // A tapback is best effort: when its transport stays down it is dropped, so it never holds the sends behind it.
  if (o.at === undefined) save((o = { ...o, at: Date.now() }));
  if (Date.now() - o.at! > REACT_MAX_MS) throw Object.assign(new Error(`tapback ${o.react} older than ${REACT_MAX_MS / 1000} s, dropped`), { permanent: true });
  const line = lineOf(o);
  if (!line) throw Object.assign(new Error(`transport ${o.line} is not set`), { permanent: true });
  try {
    await line.react(o, o.react!, () => save({ ...o, maybe: { ...o.maybe, [line.name]: o.space } }));
  } catch (e) {
    if (notSent(e)) save(o);
    throw e;
  }
  finishDeskDelivery(o);
  remember(o.kind ?? "supervisor", `tapback ${o.react} on message ${o.id}`);
}

// Sends a card's bubble. A link card is its page's URL as a plain text, which iMessage shows as a link preview from
// the page's Open Graph tags. An app card (`"app": true`) is a Spectrum app bubble, edited in place once it is out.
// An outage retries in order like a text. Any other failure (the plan or the line refuses app cards, for example)
// moves the item to the dead-letter folder, so the texts behind it go on, and files a note the first time. No error
// that names the token reaches a log.
async function deliverCard(o: Out, kind: Kind) {
  const card = cards?.read(o.card!);
  if (!card) throw Object.assign(new Error("the card's record is gone (expired)"), { permanent: true });
  const line = lineOf(o);
  if (!line || (card.app && !line.sendCard)) throw Object.assign(new Error(`a card needs the ${card.app ? "photon" : o.line ?? "photon"} transport`), { permanent: true });
  if (card.sent && !card.session) {
    console.error(`fm-imessage: card ${card.key} has no card session, so its bubble stays as it was sent`);
    return;
  }
  const url = `${CARD_URL}/c/${card.token}`;
  try {
    const session = card.app ? await line.sendCard!(o.space, url, cardLayout(card), card.live, card.session) : await line.send(o.space, url, undefined, o.guid && `${o.guid}-0`).then(() => undefined);
    cards!.save({ ...cards!.read(card.token)!, sent: true, session: session ?? card.session });
  } catch (e) {
    if (transient(e)) throw e;
    const why = brief(e).replaceAll(card.token, "<token>");
    if (!card.sent) fileNote(`card-${card.key}-${card.expires}-failed`, `(card ${card.key} was not sent: ${why})`);
    throw Object.assign(new Error(`card ${card.key}: ${why}`), { permanent: true });
  }
  if (!card.sent) remember(kind, `[card ${card.key}: ${card.title}]`);
}

// His pick on a choice card's page: the inbox note, then the bubble edit, queued behind the sends before it.
function picked(card: Extract<Stored, { kind: "choice" }>, choice: number): boolean {
  const text = `[iMessage card pick] ${card.key}: ${letter(choice)}. ${card.options[choice]}`;
  if (!fileNote(`card-${card.key}-${card.expires}-pick`, text)) return false;
  remember("owner", text);
  if (card.chat && card.app) put({ ...card.chat, card: card.token });
  return true;
}

async function sendBubble(o: Out, i: number, bubble: Bubble, save: (o: Out) => void) {
  const maybe: Record<string, string> = {};
  for (const [name, space] of Object.entries(o.maybe ?? {})) {
    if (o.kind === "desk" && (name !== (o.line ?? "photon") || space !== o.space)) continue;
    const line = lines.find((l) => l.name === name);
    if (!line) {
      if (TRANSPORTS.includes(name)) maybe[name] = space;
      continue;
    }
    // A photo has no text to look for, so a try that may have sent it stays on its transport and is sent again.
    if (!line.sent || typeof bubble !== "string") maybe[name] = space;
    else if (await line.sent(space, bubble, o.since ?? 0)) return;
  }
  const since = o.since ?? Date.now();
  try {
    const via = await failover(routes(o, i, maybe), bubble, (line) => console.error(`fm-imessage: outbox ${line}`));
    if (via !== (o.line ?? "photon")) console.error(`fm-imessage: sent bubble ${i + 1} on the ${via} fallback`);
  } catch (e) {
    if (Object.keys(maybe).length) save({ ...o, maybe, since });
    throw e;
  }
}

// Desk responses stay on their queued chat's transport, even during retries.
// Other plain sends, including --no-thread replies, stay there unless retrying an uncertain attempt.
// `routes` preserves each uncertain attempt's chat even when a newer inbound text changes line.latest.
// A photo can use another transport when its queued transport cannot send images.
function candidates(o: Out, i: number, retry: boolean): Line[] {
  const photo = o.image !== undefined && i === 0;
  const pool = photo ? lines.filter((line) => line.sendImage) : lines;
  const queued = lineOf(o);
  if (o.kind === "desk") return queued ? [queued] : [];
  const preferred = (!o.reply || i === 0) && queued && pool.includes(queued) ? queued : undefined;
  if (retry || (photo && !preferred)) return pool;
  if (!o.reply) return preferred ? [preferred] : [];
  return preferred ? [preferred, ...pool.filter((line) => line !== preferred)] : pool;
}

function routes(o: Out, i: number, maybe: Record<string, string>): Route<Bubble>[] {
  const guid = o.guid && `${o.guid}-${i}`;
  const only = Object.keys(maybe);
  return candidates(o, i, only.length > 0).flatMap((line) => {
    const own = line === lineOf(o);
    const space = o.kind === "desk" ? o.space : maybe[line.name] ?? (own ? o.space : line.latest?.space ?? line.home);
    if (!space || (only.length && !only.includes(line.name))) return [];
    const reply = own && i === 0 ? o.reply : undefined;
    return [{ name: line.name, send: async (bubble: Bubble) => {
      if (stopping) throw new Error("bridge stopping");
      // A read-only lookup cannot have sent text, so its failure can use a fallback.
      const separated = reply ? await line.separated(space, reply).catch((e: unknown) => {
        throw Object.assign(e instanceof Error ? e : new Error(String(e)), { maybeSent: false });
      }) : false;
      const thread = separated ? reply : undefined;
      try {
        if (stopping) throw Object.assign(new Error("bridge stopping"), { maybeSent: false });
        if (typeof bubble === "string") await line.send(space, bubble, thread, guid);
        else await line.sendImage!(space, bubble, thread);
      } catch (e) {
        if (!notSent(e)) maybe[line.name] = space;
        throw e;
      }
    } }];
  });
}

// A memory error never stops a send, a tapback or the inbox note: it is logged.
function remember(kind: Kind, text: string, requestId?: string): number | undefined {
  if (requestId && memoryByRequest.has(requestId)) return memoryByRequest.get(requestId);
  try {
    const id = memory.append(kind, text, requestId);
    if (requestId) memoryByRequest.set(requestId, id);
    return id;
  } catch (e) {
    log("memory")(e);
  }
}

function prefetchInboxStatus() {
  if (DESK_VETTED) inboxStatus = readInboxStatus().catch(log("read inbox status"));
}

async function readInboxStatus() {
  const inbox = track(Bun.spawn([INBOX, "status"], { cwd: FM_HOME, env: { ...env, FM_HOME }, stdout: "pipe", stderr: "ignore", timeout: 5000 }));
  const status = await new Response(inbox.stdout).text();
  return { status, statusOk: await inbox.exited === 0 };
}

function startDeskTyping(pending: Routing[], current: () => boolean) {
  const space = pending.every(({ ref }) => ref.space === latestRef?.space
    && (ref.line ?? "photon") === (latestRef?.line ?? "photon")) ? latest?.space : undefined;
  let active = true;
  let refreshing = false;
  const refresh = () => {
    if (!active || refreshing || !space) return;
    refreshing = true;
    deskTypingPending = deskTypingPending.then(async () => {
      if (active && !stopping && current()) await space.startTyping();
    }).catch(log("start typing")).finally(() => { refreshing = false; });
  };
  const timer = setInterval(() => {
    if (stopping || !current()) finishTyping();
    else refresh();
  }, 4000);
  const finishTyping = () => {
    if (!active) return;
    active = false;
    clearInterval(timer);
    if (stopDeskTyping === finishTyping) {
      stopDeskTyping = undefined;
      deskTypingRequestId = undefined;
    }
    deskTypingPending = deskTypingPending.then(() => space?.stopTyping()).catch(log("stop typing"));
  };
  stopDeskTyping = finishTyping;
  refresh();
  return finishTyping;
}

// One classification and answer for the whole pending burst; cancellation leaves every request owned on disk.
async function runDesk(current: () => boolean) {
  if (stopping) return;
  const pending = pendingRoutes();
  if (!pending.length) return;
  if (pending.some((r) => r.firstmate) || !DESK_VETTED) return handoffPending();
  const finishTyping = startDeskTyping(pending, current);
  let queued = false;
  try {
    const result = await draftBasic(pending, current);
    if (stopping || !current()) return;
    if (result === undefined) handoffPending();
    else {
      commitDeskAnswer(pending, result);
      queued = true;
    }
    const at = result?.target.ref ?? pending.at(-1)!.ref;
    appendFileSync(DESK_LOG, `${new Date().toISOString()} ${at.id} ${result === undefined ? "handoff" : "answer" in result.answer ? "basic" : `react ${result.answer.react}`}\n`, { mode: 0o600 });
  } finally {
    if (!queued) finishTyping();
  }
}

function commitDeskAnswer(pending: Routing[], result: DeskResult) {
  const { answer, target } = result;
  const ids = pending.map((r) => r.requestId);
  deskTypingRequestId = target.requestId;
  recordRoute({ ids, route: "desk",
    out: { ...target.ref, requestId: target.requestId, requests: ids,
      ...("answer" in answer ? { bubbles: bubbles(answer.answer), reply: target.ref.id }
        : { react: answer.react, ...(answer.text ? { bubbles: [answer.text], reply: target.ref.id } : {}) }),
      kind: "desk", guid: crypto.randomUUID(), at: Date.now() } });
  flushRoutes();
}

async function draftBasic(pending: Routing[], current: () => boolean): Promise<DeskResult | undefined> {
  const result = await inboxStatus;
  if (!result || stopping || !current()) return;
  const { status, statusOk } = result;
  const from = pending.reduce((first, r) => Math.min(first, memoryByRequest.get(r.requestId) ?? r.memoryId), memory.msgs.length);
  const latestText = pending.map((r, i) => `owner ${i + 1}: ${r.text}`).join("\n");
  const { prompt, spent } = deskInput(DESK_PROMPT, memory.render(from), status, latestText, DESK_PROVIDER, memory.recent(from));
  if (!statusOk || !prompt.includes(latestText)) return;
  const proc = track(spawnDesk({ provider: DESK_PROVIDER, model: DESK_MODEL, reasoning: DESK_REASONING, system: DESK_PROMPT, prompt, spent, memoryDir: MEMORY_DIR, cwd: DESK_DIR, env }));
  deskRun = proc;
  const { ok, drafted } = await readDesk(proc);
  if (deskRun !== proc) return;
  deskRun = undefined;
  if (stopping || !current()) return;
  const answer = basicAnswer(ok, drafted, status, memory.msgs, { desk: DESK_MODEL, supervisor: SUPERVISOR_MODEL });
  if (!answer) return;
  const target = pending[(answer.target ?? pending.length) - 1];
  if (!target) return;
  if ("react" in answer && !socialOnly(pending.map((r) => r.authored ?? r.text), memory.msgs[from - 1])) return;
  if ("answer" in answer) answer.answer = await rewriteVoice(answer.answer);
  if (stopping || !current()) return;
  return { answer, target };
}

async function rewriteVoice(draft: string): Promise<string> {
  let proc: DeskProc | undefined;
  try {
    proc = track(spawnDesk({ provider: DESK_PROVIDER, model: DESK_MODEL, voice: true,
      system: VOICE_PROMPT, prompt: JSON.stringify({ draft }), spent: 0, memoryDir: MEMORY_DIR, cwd: DESK_DIR, env }));
    deskRun = proc;
    const { ok, drafted } = await readDesk(proc);
    return voiceAnswer(draft, ok, drafted);
  } catch {
    return draft;
  } finally {
    if (deskRun === proc) deskRun = undefined;
  }
}

function applyRoute(event: RouteEvent) {
  if ("received" in event) routing.set(event.received.requestId, { ...event.received, route: "pending" });
  else for (const id of event.ids) Object.assign(routing.get(id)!, { route: event.route, out: event.out });
}

function recordRoute(event: RouteEvent) {
  const fd = openSync(ROUTING_LOG, "a", 0o600);
  try {
    writeSync(fd, `${JSON.stringify(event)}\n`);
    fsyncSync(fd);
  } finally { closeSync(fd); }
  const dir = openSync(STATE, "r");
  try { fsyncSync(dir); } finally { closeSync(dir); }
  applyRoute(event);
}

function ensureRemembered(item: Received) {
  if (memoryByRequest.has(item.requestId)) return;
  try { memoryByRequest.set(item.requestId, memory.append("owner", item.text, item.requestId)); }
  catch (e) {
    log("memory")(e);
    if (routing.get(item.requestId)?.route === "pending") recordRoute({ ids: [item.requestId], route: "handoff" });
  }
}

function lostDeskAnswer(item: Out) {
  finishDeskDelivery(item);
  if (!item.requests?.length || item.done || Object.keys(item.maybe ?? {}).length) return;
  recordRoute({ ids: item.requests, route: "handoff" });
  flushRoutes();
}

function pendingRoutes() {
  return [...routing.values()].filter((r) => r.route === "pending");
}

function handoffPending() {
  const pending = pendingRoutes();
  if (pending.length) recordRoute({ ids: pending.map((r) => r.requestId), route: "handoff" });
  flushRoutes();
}

// The decision is durable before either side effect. Inbox ids and keyed outbox receipts close replay gaps.
function flushRoutes() {
  if (stopping) return;
  clearTimeout(routingRetry);
  let failed = false;
  for (const item of routing.values()) {
    try {
      if (item.route === "handoff") {
        if (!fileNote(item.requestId, item.text)) throw new Error("the inbox note failed; routing retains the request");
      } else if (item.route !== "desk") continue;
      if (item.out) outbox.add(item.out);
      recordRoute({ ids: [item.requestId], route: "done" });
    } catch (e) {
      log("route delivery")(e);
      failed = true;
    }
  }
  if (failed) routingRetry = setTimeout(flushRoutes, RETRY_MS);
}

async function saveAttachment(c: Saveable, id: string) {
  const path = `${ATTACH_DIR}/${id}-${String(c.name ?? "file").replace(/[^\w.-]/g, "_")}`;
  await Bun.write(path, await c.read());
  return path;
}

// The note text for a message, and the first error of an attachment that could not be saved.
async function noteText(message: LineMessage) {
  let failed: unknown;
  const text = await describe(message.content, message.id, (c, id) => saveAttachment(c, id).catch((e) => {
    failed ??= e;
    throw e;
  }), (path) => transcribe(path, listen).catch((e) => {
    log("transcribe")(e);
    throw e;
  }));
  return { text, failed };
}

// Files a Firstmate inbox note; true when the inbox took it.
function fileNote(requestId: string, text: string): boolean {
  if (stopping) return false;
  const note = Bun.spawnSync(
    [INBOX, "note", "--request-id", requestId, "--", `[iMessage from the owner; answer with fm-imessage] ${text}`],
    { cwd: FM_HOME, env: { ...env, FM_HOME } },
  );
  return note.exitCode === 0;
}

// Tries the attachments of his message again; once all are saved, files its note again with their paths.
async function fetchAgain(ref: Ref) {
  if (stopping) throw new Error("bridge stopping");
  const line = lineOf(ref);
  if (!line) throw Object.assign(new Error(`transport ${ref.line} is not set`), { permanent: true });
  const { text, failed } = await line.find(ref).then(noteText).catch((e) => {
    // A shutdown must not bury a download before its final inbox notice can be filed.
    throw stopping ? new Error("bridge stopping") : e;
  });
  if (stopping) throw new Error("bridge stopping");
  if (failed !== undefined) throw failed;
  if (text !== undefined && !fileNote(`${line.name}-${ref.id}-saved`, `(an earlier attachment is saved now) ${text}`)) {
    throw new Error("the inbox note failed");
  }
}

async function handle(line: Line, message: LineMessage) {
  const { text, failed } = await noteText(message);
  if (stopping) return;
  console.log(`fm-imessage: inbound ${line.name} ${message.content.type} -> ${text === undefined ? "ignored" : "note"}`);
  if (text === undefined) return;
  const ref = refOn(line.name, message.space.id, message.id);
  const authored = authoredText(message.content);
  receive(`${line.name}-${message.id}`, text, ref, authored === undefined || !directChat.test(ref.space), authored);
  heard(message.id, text);
  if (failed !== undefined) {
    log("download an attachment")(failed);
    downloads.add(ref);
  }
  const at = message.timestamp?.getTime() || Date.now();
  if (at >= latestAt) {
    latest = message;
    latestRef = line.latest = ref;
    latestAt = at;
    recent.push(ref);
    recent.splice(0, Math.max(0, recent.length - 10));
    persistLatest(latestFile(line.name), `${message.space.id}\n${message.id}\n${at}\n`);
  }
  if (directChat.test(ref.space) && at >= proactiveAt) {
    proactiveRef = ref;
    proactiveAt = at;
    persistLatest(`${latestFile(line.name)}-direct`, `${ref.space}\n${ref.id}\n${at}\n`);
  }
  await message.read().catch(log("mark read"));
  if (pendingRoutes().some((r) => r.firstmate)) handoffPending();
}

// Persist the full input before marking it read or seen. A duplicate never opens another routing decision.
function receive(requestId: string, text: string, ref: Ref, firstmate: boolean, authored = text) {
  if (routing.has(requestId)) return;
  // Obvious actions, approvals, and secrets never depend on a model's willingness to hand off.
  firstmate ||= /^\s*(?:please\s+)?(?:approve\b|(?:deploy|implement|fix|build|change|send|run|restart|stop|delete)\s+(?:the|a|an|this|that|these|those|it|them|my|our|your)\b)|^\s*(?:(?:approved|yes|ok|go ahead|proceed|ship it|do it)\b[ \t,;.!]*)+(?:$|(?:please|and|deploy|implement|fix|build|change|send|run|restart|stop|delete|approve|merge)\b)|\b(?:can|could|will|would)\s+you\s+(?:deploy|implement|fix|build|change|send|run|restart|stop|delete|approve)\b|\b(?:password|secret|credential|private key|api key|access token|ssn|prescription|diagnosis)\b/im.test(authored);
  const received = { requestId, text, ...(authored === text ? {} : { authored }), ref, memoryId: memory.msgs.length, firstmate };
  prefetchInboxStatus();
  recordRoute({ received });
  ensureRemembered(received);
  flushRoutes();
  cancelDesk();
  desk.inboundText();
}

function authoredText(content: LineMessage["content"]): string | undefined {
  if (content.type === "text") return content.text;
  if (content.type === "markdown") return content.markdown;
  if (content.type === "reply" || content.type === "effect") return authoredText(content.content);
  if (content.type === "group") {
    const parts = content.items.map((m) => authoredText(m.content));
    return parts.every((part) => part !== undefined) ? parts.join("\n") : undefined;
  }
}

function heard(id: string, text: string) {
  said.delete(id);
  said.set(id, text);
  if (said.size > 100) said.delete(said.keys().next().value!);
}

// His edits, from the Photon line's own event stream: spectrum-ts consumes message.edited without passing it on.
// ponytail: an edit made while this stream is down is lost; replay events.catchUp if that matters.
async function watchEdits(client: AdvancedIMessage) {
  for (;;) {
    try {
      for await (const e of client.messages.subscribeEvents()) {
        if (e.type === "message.edited" && !e.isFromMe && (e.actor?.address ?? e.chatGuid.split(";-;")[1]) === OWNER) edited(e);
      }
    } catch (e) {
      log("edit stream")(e);
    }
    await Bun.sleep(5 * RETRY_MS);
  }
}

function edited(e: EventTypeMap["message.edited"]) {
  if (stopping) return;
  const text = e.content.text ?? "(no text)";
  const was = said.get(e.messageGuid) ?? "not known: the bridge did not see the text before the edit";
  console.log("fm-imessage: inbound edit -> note");
  receive(`photon-${e.messageGuid}-edit-${e.sequence}`, `[edited] ${text} (was: ${was})`, { space: e.chatGuid, id: e.messageGuid }, true);
  heard(e.messageGuid, text);
  handoffPending();
}

// Every transport's messages, each message once even when two transports report it. A message that fails to be
// handled is released, so a webhook or catch-up delivers it again.
const delivered = new Set<string>();
for await (const [line, message] of inbound(lines, 1000, delivered)) {
  if (stopping) break;
  if (message.direction === "outbound") {
    line.markSeen?.(message.id);
    continue;
  }
  if (message.sender?.id !== OWNER) {
    console.log(`fm-imessage: ignored a ${line.name} message from ${message.sender?.id ?? "unknown"}`);
    line.markSeen?.(message.id);
    continue;
  }
  const handled = await handle(line, message).then(() => true, (e) => void log("failed to handle a message")(e));
  if (stopping) break;
  if (handled) line.markSeen?.(message.id);
  else {
    delivered.delete(message.id);
    line.release?.(message.id);
  }
}
