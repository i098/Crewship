// Two-way iMessage between the owner and Firstmate over the transports that FM_IMESSAGE_TRANSPORTS lists in order:
//   photon (the default), the line of a Photon Spectrum project, and bluebubbles, self-hosted BlueBubbles servers on
//   Macs (bluebubbles.ts). See routes for outbound transport selection and docs/imessage.md for the routing contract.
// Inbound: each text the owner sends is filed first as a Firstmate inbox note, which wakes Firstmate for the
//   real answer, then marked read. A one-shot front-desk model steps in only when Firstmate stays silent for the
//   quiet period after his last text; it often skips or uses a tapback, like a person would. No transport reports
//   inbound typing, so a new text is what restarts the wait. The desk sees the whole chat through its memory
//   (memory.ts), which logs every text both ways.
// Outbound: POST text to http://127.0.0.1:$FM_IMESSAGE_PORT/send (the fm-imessage command does this).
//   The text goes to a durable outbox (outbox.ts) and the answer comes once it is on disk; one loop sends the outbox
//   in order, as plain messages by default, and tries again with backoff while the upstream
//   fails. Measured on the free shared line: plain sends into the owner's own conversation work, while a
//   conversation the service opened itself was refused. That text's conversation and message ids are kept in the
//   state directory, so a restart can still reach him.
// Location: when he shares his location with the Photon line in Find My, GET /location (the fm-location command).
// Edits: spectrum-ts drops the Photon line's message.edited events, so the bridge reads them from that line's own
//   client and files each edit as a new note, "[edited] <new text> (was: <old text>)".
// Runs as the systemd --user service fm-imessage (docs/imessage.md). Docs: https://photon.codes/docs/spectrum-ts
import { appendFileSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import type { AdvancedIMessage, EventTypeMap } from "@photon-ai/advanced-imessage/grpc";
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import { BlueBubbles } from "./bluebubbles.ts";
import { type Attachment, bubbles, describe, DeskTiming, deskInput, deskPrompt, failover, inbound, isSkip, type LineMessage, localCommand, notSent, parseReact, type Route, typingPause } from "./desk.ts";
import { type Chat, type Kind, Memory } from "./memory.ts";
import { brief, permanent, Queue, transient } from "./outbox.ts";

const env = process.env;
const need = (name: string) => env[name] || (() => { throw new Error(`fm-imessage: ${name} is not set`); })();
const OWNER = need("FM_IMESSAGE_OWNER");
const FM_HOME = need("FM_HOME");
const INBOX = env.FM_INBOX_CMD || `${FM_HOME}/bin/fm-inbox.sh`;
const PORT = Number(env.FM_IMESSAGE_PORT || 8765);
const TRANSPORTS = (env.FM_IMESSAGE_TRANSPORTS || "photon").split(/\s+/).filter(Boolean);
const DESK_MODEL = env.FM_IMESSAGE_DESK_MODEL || "claude-haiku-5-5";
const DESK_PROMPT = deskPrompt(env.FM_IMESSAGE_OWNER_NAME || "the owner", DESK_MODEL, env.FM_IMESSAGE_SUPERVISOR_MODEL || "");
const QUIET_MS = 4000; // the desk waits this long for Firstmate's own answer
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
for (const dir of [STATE, DESK_DIR, ATTACH_DIR]) mkdirSync(dir, { recursive: true, mode: 0o700 });
let burstFrom: number | undefined; // the memory id of his first text the desk has not answered yet
const recent: Ref[] = []; // his last texts, newest last, for a threaded reply to one a few bubbles up
const said = new Map<string, string>(); // his last 100 texts by message id, for the "was:" part of an edit note
// One line for a transient upstream failure; the whole error, with its stack, for anything else.
const log = (what: string) => (e: unknown) =>
  transient(e) ? console.error(`fm-imessage: ${what}: ${brief(e)}`) : console.error(`fm-imessage: ${what}:`, e);
// Typing bubbles are best effort: an error is logged and never fails or delays a send.
const typing = (space: LineMessage["space"], on: boolean) =>
  void (on ? space.startTyping() : space.stopTyping()).catch(log(on ? "start typing" : "stop typing"));
// This service is the memory's one writer: systemd runs one instance of the unit.
const memory = new Memory(MEMORY_DIR, compactChat, log("memory"));
const desk = new DeskTiming(QUIET_MS, (current) => void runDesk(current).catch(log("desk failed")));
let deskRun: Bun.Subprocess | undefined;

// A message by its transport, conversation and message ids, which outlive a restart. An item queued before there
// were transports has no `line` and is Photon's.
type Ref = { line?: string; space: string; id: string };
// One outbox item for his text `id`: a tapback, or bubbles (`done` of them sent so far), the first one threaded to
// his text `reply` when set. `kind` is whose memory line it makes (Firstmate's unless "desk"); `silent` makes none.
// `guid` is the client GUID of its sends (BlueBubbles tempGuid). `at` is when it was queued. `maybe` maps each transport
// where bubble `done` may already be out to the conversation it was sent into, and `since` is when that try started.
type Out = Ref & { react?: string; bubbles?: string[]; done?: number; reply?: string; kind?: Kind; silent?: boolean; guid?: string; at?: number; maybe?: Record<string, string>; since?: number };
// One transport. `find` reads a message whole (with its attachments); `send` sends one bubble into a conversation,
// threaded to message `reply` when set; `home` is a conversation with him that works before he texts this transport;
// `latest` is his latest text on it.
type Line = {
  name: string;
  messages: AsyncIterable<LineMessage>;
  find(ref: Ref): Promise<LineMessage>;
  separated(space: string, id: string): Promise<boolean>;
  send(space: string, text: string, reply?: string, guid?: string): Promise<unknown>;
  sent?(space: string, text: string, since: number): Promise<boolean>;
  react(ref: Ref, emoji: string): Promise<unknown>;
  markSeen?(id: string): void; // the bridge has handled message `id`; a transport that keeps its own seen-set stores it
  release?(id: string): void; // the bridge failed to handle message `id`; the transport may deliver it again
  home?: string;
  latest?: Ref;
};
let raw: AdvancedIMessage | undefined; // the Find My client (Photon only)
const lines: Line[] = [];
for (const name of TRANSPORTS) {
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
    Bun.serve({ hostname: listen.hostname, port: Number(listen.port), fetch: (req) => bb.webhook(req) });
    bb.start();
    lines.push({
      name,
      messages: bb,
      find: (ref) => bb.message(ref.id),
      separated: (space, id) => bb.separated(space, id),
      send: (space, text, reply, guid) => bb.send(space, text, reply, guid),
      sent: (space, text, since) => bb.sent(space, text, since),
      markSeen: (id) => bb.markSeen(id),
      release: (id) => bb.release(id),
      react: (ref, emoji) => bb.react(ref.space, ref.id, emoji),
      home: `iMessage;-;${OWNER}`,
    });
    continue;
  }
  if (name !== "photon") throw new Error(`fm-imessage: unknown transport ${name}`);
  // ponytail: a Photon line that cannot start is skipped when another transport is set, until the next restart.
  const app = await Spectrum({
    projectId: need("PHOTON_PROJECT_ID"),
    projectSecret: need("PHOTON_PROJECT_SECRET"),
    providers: [imessage.config()],
  }).catch((e) => {
    if (TRANSPORTS.length === 1) throw e;
    console.error(`fm-imessage: photon did not start, using the other transports: ${brief(e)}`);
  });
  if (!app) continue;
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
  lines.push({
    name,
    messages: (async function* () {
      for await (const [, message] of app.messages) yield message;
    })(),
    find,
    async separated(space, id) {
      if (!photon) throw new Error("cannot check reply separation: Photon chat client is unavailable");
      const last = (await photon.chats.get(space)).lastMessage?.guid;
      return !!last && last !== id;
    },
    async send(space, text, reply) {
      // A reply target that is gone sends the bubble unthreaded.
      const thread = reply ? await find({ space, id: reply }).catch((e) => {
        if (!permanent(e)) throw e;
        console.error(`fm-imessage: reply target ${reply} gone, sending unthreaded: ${brief(e)}`);
      }) : undefined;
      return thread ? thread.reply(text) : (await imessage(app).space.get(space)).send(text);
    },
    react: async (ref, emoji) => (await find(ref)).react(emoji),
  });
}
// The active transport of a queued item or a kept text; undefined when absent or unable to start.
const lineOf = (ref: Ref) => lines.find((line) => line.name === (ref.line ?? "photon"));
// A Ref on a transport; a Photon one has no `line`, the same as the items queued before there were transports.
const refOn = (name: string, space: string, id: string): Ref => (name === "photon" ? { space, id } : { line: name, space, id });
// Each transport's latest text, kept so a restart can still reach him: space, id and time, one per line.
// Photon keeps the file name it always had. A file without the time (the older format) counts as the oldest.
const latestFile = (name: string) => (name === "photon" ? LATEST_FILE : `${LATEST_FILE}-${name}`);
let latest: LineMessage | undefined; // his latest text on any transport: typing, tapbacks and the desk go there
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
if (latestRef) latest = await lineOf(latestRef)?.find(latestRef).catch((e) => void log("could not restore the latest text; sends still go to it")(e));
const outbox = new Queue<Out>(OUTBOX_DIR, "outbox item", deliver, RETRY_MS);
const downloads = new Queue<Ref>(DOWNLOADS_DIR, "attachment download", fetchAgain, RETRY_MS, (ref) => {
  if (!fileNote(`${ref.line ?? "photon"}-${ref.id}-lost`, `(an earlier attachment of message ${ref.id} could not be saved; the bridge gave up, so no path will follow)`)) {
    console.error(`fm-imessage: the inbox note for the lost attachment of message ${ref.id} failed`);
  }
});

// Stop a pending or running desk turn: he sent more, or Firstmate is active on the line.
function cancelDesk() {
  if (!deskRun) return;
  deskRun.kill();
  deskRun = undefined;
  if (latest) typing(latest.space, false);
}

Bun.serve({
  hostname: "127.0.0.1",
  port: PORT,
  async fetch(req) {
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
    if (req.method !== "POST" || !["/send", "/typing", "/react"].includes(url.pathname)) return new Response("not found", { status: 404 });
    const ref = latestRef;
    if (!ref) return new Response("no text from the owner yet; he must text the line first\n", { status: 503 });
    // Any Firstmate activity on the line means the real answer is coming, so the desk stands down.
    desk.firstmateActive();
    burstFrom = undefined;
    cancelDesk();
    // Typing shows only while Firstmate is really composing: /typing starts it, and every send clears it.
    if (url.pathname === "/typing") {
      if (latest) typing(latest.space, true);
      return new Response("typing\n");
    }
    if (url.pathname === "/react") {
      const emoji = (await req.text()).trim();
      if (!emoji) return new Response("no emoji", { status: 400 });
      return queue({ ...ref, react: emoji }, `tapback ${emoji}`);
    }
    const parts = bubbles(await req.text());
    if (!parts.length) return new Response("empty message", { status: 400 });
    // ?reply=N targets his Nth latest text. ?no-thread forces plain, even with an explicit target.
    const replyTo = Number(url.searchParams.get("reply") ?? 0);
    const target = replyTo > 0 ? recent[recent.length - replyTo] : undefined;
    if (replyTo > 0 && !target) return new Response(`nothing queued: only ${recent.length} text(s) kept since the service started\n`, { status: 400 });
    // A threaded reply goes out on the transport and in the conversation of the text it replies to.
    const destination = target ?? proactiveRef;
    if (!destination) return new Response("no direct text from the owner yet; he must text the line first\n", { status: 503 });
    return queue({ ...destination, bubbles: parts, reply: url.searchParams.has("no-thread") ? undefined : target?.id }, `${parts.length} bubble(s)`);
  },
});
console.log(`fm-imessage: listening on 127.0.0.1:${PORT}, latest text ${latest ? "restored" : latestRef ? "known by id" : "unknown"}`);

// Puts one item in the outbox and answers once the item is on disk.
function queue(item: Out, what: string) {
  put(item);
  return new Response(`queued ${what}; the bridge sends in order and retries while the upstream fails\n`);
}

// Puts one item in the outbox with a client GUID of its own.
function put(item: Out) {
  outbox.add({ guid: crypto.randomUUID(), at: Date.now(), ...item });
}

async function deliver(o: Out, save: (o: Out) => void) {
  const kind = o.kind ?? "supervisor";
  if (o.react) {
    // A tapback is best effort: when its transport stays down it is dropped, so it never holds the sends behind it.
    if (o.at === undefined) save((o = { ...o, at: Date.now() }));
    if (Date.now() - o.at! > REACT_MAX_MS) throw Object.assign(new Error(`tapback ${o.react} older than ${REACT_MAX_MS / 1000} s, dropped`), { permanent: true });
    const line = lineOf(o);
    if (!line) throw Object.assign(new Error(`transport ${o.line} is not set`), { permanent: true });
    await line.react(o, o.react);
    remember(kind, `tapback ${o.react} on his last text`);
    return;
  }
  const parts = o.bubbles ?? [];
  for (let i = o.done ?? 0; i < parts.length; i++) {
    if (i > 0) {
      if (latest) typing(latest.space, true);
      await Bun.sleep(typingPause(parts[i]!));
    }
    if (latest) typing(latest.space, false);
    await sendBubble(o, i, save);
    save((o = { ...o, done: i + 1, maybe: undefined, since: undefined }));
  }
  if (!o.silent) remember(kind, parts.join("\n\n"));
}

async function sendBubble(o: Out, i: number, save: (o: Out) => void) {
  const text = o.bubbles![i]!;
  const maybe: Record<string, string> = {};
  for (const [name, space] of Object.entries(o.maybe ?? {})) {
    const line = lines.find((l) => l.name === name);
    if (!line) {
      if (TRANSPORTS.includes(name)) maybe[name] = space;
      continue;
    }
    if (!line.sent) maybe[name] = space;
    else if (await line.sent(space, text, o.since ?? 0)) return;
  }
  const since = o.since ?? Date.now();
  try {
    const via = await failover(routes(o, i, maybe), text, (line) => console.error(`fm-imessage: outbox ${line}`));
    if (via !== (o.line ?? "photon")) console.error(`fm-imessage: sent bubble ${i + 1} on the ${via} fallback`);
  } catch (e) {
    if (Object.keys(maybe).length) save({ ...o, maybe, since });
    throw e;
  }
}

// Plain sends stay on their queued chat's transport, including --no-thread replies and desk responses.
// An uncertain attempt stays in its original chat, even when a newer inbound text changes line.latest.
function routes(o: Out, i: number, maybe: Record<string, string>): Route[] {
  const guid = o.guid && `${o.guid}-${i}`;
  const only = Object.keys(maybe);
  const preferred = !o.reply || i === 0 ? lineOf(o) : undefined;
  const ordered = only.length ? lines : !o.reply ? (preferred ? [preferred] : []) :
    preferred ? [preferred, ...lines.filter((line) => line !== preferred)] : lines;
  return ordered.flatMap((line) => {
    const own = line === lineOf(o);
    const space = maybe[line.name] ?? (own ? o.space : line.latest?.space ?? line.home);
    if (!space || (only.length && !only.includes(line.name))) return [];
    const reply = own && i === 0 ? o.reply : undefined;
    return [{ name: line.name, send: async (text: string) => {
      // A read-only lookup cannot have sent text, so its failure can use a fallback.
      const separated = reply ? await line.separated(space, reply).catch((e: unknown) => {
        throw Object.assign(e instanceof Error ? e : new Error(String(e)), { maybeSent: false });
      }) : false;
      const thread = separated ? reply : undefined;
      try {
        await line.send(space, text, thread, guid);
      } catch (e) {
        if (!notSent(e)) maybe[line.name] = space;
        throw e;
      }
    } }];
  });
}

// A memory error never stops a send, a tapback or the inbox note: it is logged.
function remember(kind: Kind, text: string): number | undefined {
  try {
    return memory.append(kind, text);
  } catch (e) {
    log("memory")(e);
  }
}

// One desk turn for his latest burst. It drops its draft if he sent more or Firstmate answered meanwhile.
async function runDesk(current: () => boolean) {
  const target = latest;
  const at = latestRef;
  if (!target || !at) return;
  typing(target.space, true);
  const inbox = Bun.spawn([INBOX, "status"], { cwd: FM_HOME, env: { ...env, FM_HOME }, stdout: "pipe", stderr: "ignore" });
  const status = await new Response(inbox.stdout).text();
  if (!current()) return typing(target.space, false);
  // The view of the chat before his burst, then the per-turn state, then his burst, all under the ceiling.
  const from = burstFrom ?? memory.msgs.length;
  const { prompt, spent } = deskInput(DESK_PROMPT, memory.render(from), status, memory.msgs.slice(from).map((m) => `${m.kind}: ${m.text}`).join("\n"));
  const proc = Bun.spawn(
    ["omp", "-p", "--no-extensions", "-e", `${import.meta.dir}/zoom.ts`, "--no-tools", "--no-skills", "--no-rules", "--no-session",
      "--thinking=off", "--model", DESK_MODEL, "--system-prompt", DESK_PROMPT],
    { cwd: DESK_DIR, env: { ...env, FM_DESK_MEMORY: MEMORY_DIR, FM_DESK_SPENT: String(spent) }, stdin: new Blob([prompt]), stdout: "pipe", stderr: "ignore", timeout: 45_000 },
  );
  deskRun = proc;
  const drafted = (await new Response(proc.stdout).text()).replace(/^Working\.\.\.\s*/m, "").trim();
  const ok = (await proc.exited) === 0 && drafted !== "";
  if (deskRun !== proc) return; // cancelled while drafting
  deskRun = undefined;
  typing(target.space, false);
  if (!current()) return;
  burstFrom = undefined;
  const skip = !ok || isSkip(drafted); // a failed desk stays quiet; Firstmate still has the note
  const tapback = skip ? undefined : parseReact(drafted);
  if (tapback) put({ ...at, react: tapback, kind: "desk" });
  else if (!skip) put({ ...at, bubbles: [drafted], kind: "desk" });
  const outcome = !ok ? "skip (desk failed)" : skip ? "skip" : tapback ? `react ${tapback}` : drafted.replace(/\s+/g, " ");
  appendFileSync(DESK_LOG, `${new Date().toISOString()} ${target.id} ${outcome}\n`, { mode: 0o600 });
}

// One compaction conversation: an omp session in its own private directory, which end() removes.
// Haiku 4.5 honors thinking=off; automatic reasoning on newer models exceeded 60 seconds even with small inputs.
function compactChat(system: string): Chat {
  const dir = mkdtempSync(`${STATE}/compact-`);
  let turns = 0;
  return {
    async say(text) {
      const proc = Bun.spawn(
        ["omp", "-p", "--no-extensions", "--no-tools", "--no-skills", "--no-rules", "--session-dir", dir, ...(turns++ ? ["--continue"] : []),
          "--thinking=off", "--model", "anthropic/claude-haiku-4-5", "--system-prompt", system],
        { cwd: DESK_DIR, stdin: new Blob([text]), stdout: "pipe", stderr: "ignore", timeout: 60_000 },
      );
      const line = (await new Response(proc.stdout).text()).replace(/^Working\.\.\.\s*/m, "").trim();
      if ((await proc.exited) !== 0 || !line) throw new Error(`compaction call failed (exit ${proc.exitCode})`);
      return line;
    },
    end: () => rmSync(dir, { recursive: true, force: true }),
  };
}

async function saveAttachment(c: Attachment, id: string) {
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
  }));
  return { text, failed };
}

// Files a Firstmate inbox note; true when the inbox took it.
function fileNote(requestId: string, text: string): boolean {
  const note = Bun.spawnSync(
    [INBOX, "note", "--request-id", requestId, "--", `[iMessage from the owner; answer with fm-imessage] ${text}`],
    { cwd: FM_HOME, env: { ...env, FM_HOME } },
  );
  return note.exitCode === 0;
}

// Tries the attachments of his message again; once all are saved, files its note again with their paths.
async function fetchAgain(ref: Ref) {
  const line = lineOf(ref);
  if (!line) throw Object.assign(new Error(`transport ${ref.line} is not set`), { permanent: true });
  const { text, failed } = await noteText(await line.find(ref));
  if (failed !== undefined) throw failed;
  if (text !== undefined && !fileNote(`${line.name}-${ref.id}-saved`, `(an earlier attachment is saved now) ${text}`)) {
    throw new Error("the inbox note failed");
  }
}

async function handle(line: Line, message: LineMessage) {
  const { text, failed } = await noteText(message);
  console.log(`fm-imessage: inbound ${line.name} ${message.content.type} -> ${text === undefined ? "ignored" : "note"}`);
  if (text === undefined) return;
  const ref = refOn(line.name, message.space.id, message.id);
  if (!wake(`${line.name}-${message.id}`, text, ref)) return;
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
    await Bun.write(latestFile(line.name), `${message.space.id}\n${message.id}\n${at}\n`).catch(log("persist the latest text"));
  }
  if (directChat.test(ref.space) && at >= proactiveAt) {
    proactiveRef = ref;
    proactiveAt = at;
    await Bun.write(`${latestFile(line.name)}-direct`, `${ref.space}\n${ref.id}\n${at}\n`).catch(log("persist the latest direct text"));
  }
  await message.read().catch(log("mark read"));
}

// Hands his text to Firstmate first, so the wake never waits on the desk model, then starts the desk's quiet
// period. False when the inbox refused the note: he is asked to send it again.
function wake(requestId: string, text: string, ref: Ref): boolean {
  if (!fileNote(requestId, text)) {
    put({ ...ref, bubbles: ["firstmate did not get that, send it again"], silent: true });
    return false;
  }
  const id = remember("owner", text);
  if (id !== undefined) burstFrom ??= id;
  cancelDesk();
  desk.inboundText();
  return true;
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
  const text = e.content.text ?? "(no text)";
  const was = said.get(e.messageGuid) ?? "not known: the bridge did not see the text before the edit";
  console.log("fm-imessage: inbound edit -> note");
  if (wake(`photon-${e.messageGuid}-edit-${e.sequence}`, `[edited] ${text} (was: ${was})`, { space: e.chatGuid, id: e.messageGuid })) {
    heard(e.messageGuid, text);
  }
}

if (raw) void watchEdits(raw);

// Every transport's messages, each message once even when two transports report it. A message that fails to be
// handled is released, so a webhook or catch-up delivers it again.
const delivered = new Set<string>();
for await (const [line, message] of inbound(lines, 1000, delivered)) {
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
  if (handled) line.markSeen?.(message.id);
  else {
    delivered.delete(message.id);
    line.release?.(message.id);
  }
}
