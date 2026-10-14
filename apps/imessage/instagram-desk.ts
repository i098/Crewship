// The Instagram front desk: the iMessage desk (desk.ts, memory.ts) on the Instagram DM line. A small service, with no
// Instagram client of its own, that follows two logs of the instagram-dm skill's listener:
//   INSTAGRAM_DM_LOG   one row per new DM from the operator (poll), after it went to the Firstmate inbox
//   INSTAGRAM_DM_SENT  one row per fm-insta-reply send, tapback or typing, with `by`: "desk" for the desk's own calls
// Each DM restarts the quiet period; any send, tapback or typing by Firstmate since his last DM stands the desk down
// for that burst. When the quiet period ends, one desk turn answers the whole burst through `fm-insta-reply`.
// Runs as the systemd --user service instagram-desk (docs/imessage.md#instagram-front-desk).
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, statSync, writeFileSync } from "node:fs";
import { compactChat, type DeskProc, DeskTiming, deskInput, deskPrompt, readDesk, spawnDesk, verdict } from "./desk.ts";
import { type Chat, type Kind, Memory } from "./memory.ts";

export type Row = { at: number; thread: string; id?: string; sender?: string; type?: string; text?: string; url?: string; kind?: string; by?: string };
export type Options = {
  dir: string; // private state: memory/, desk/, desk.log, offsets.json
  model: string;
  owner: string;
  supervisorModel: string;
  quietMs: number;
  replyCmd: string[]; // fm-insta-reply
  statusCmd: string[]; // prints the fleet status
  env: Record<string, string | undefined>;
  chat: (system: string) => Chat; // the memory's compaction conversation
  log?: (e: unknown) => void;
};

const FRESH_S = 60; // a row older than this (replayed after a restart) is remembered, never answered

export class InstagramDesk {
  readonly memory: Memory;
  private system: string;
  private timing: DeskTiming;
  private run?: DeskProc;
  private thread?: string;
  private lastId = "";
  private burstFrom?: number; // the memory id of his first DM the desk has not answered yet

  constructor(private o: Options) {
    for (const sub of ["", "/desk"]) mkdirSync(`${o.dir}${sub}`, { recursive: true, mode: 0o700 });
    this.system = deskPrompt(o.owner, o.model, o.supervisorModel, "Instagram");
    this.memory = new Memory(`${o.dir}/memory`, o.chat, o.log);
    this.timing = new DeskTiming(o.quietMs, (current) => void this.turn(current).catch((e) => (o.log ?? console.error)(e)));
  }

  // One row of either log. `fresh` rows act on the desk; older ones only fill the memory.
  feed(source: "messages" | "sent", row: Row, fresh: boolean) {
    if (source === "messages") {
      const i = this.remember("owner", row.url ?? (row.text ? row.text : `(sent a ${row.type ?? "message"})`));
      if (!fresh) return;
      this.burstFrom ??= i;
      this.thread = row.thread;
      this.lastId = row.id ?? this.lastId;
      this.cancel();
      this.timing.inboundText();
      return;
    }
    const desk = row.by === "desk";
    if (row.kind === "react") this.remember(desk ? "desk" : "supervisor", `tapback ${row.text} on his last text`);
    else if (row.kind === "text") this.remember(desk ? "desk" : "supervisor", row.text ?? "");
    if (!desk && fresh) {
      this.timing.firstmateActive();
      this.cancel();
    }
  }

  // Stop a running desk turn: he sent more, or Firstmate is active on the line.
  private cancel() {
    this.run?.kill();
    this.run = undefined;
  }

  private remember(kind: Kind, text: string): number | undefined {
    try {
      return this.memory.append(kind, text);
    } catch (e) {
      (this.o.log ?? console.error)(e);
    }
  }

  private async turn(current: () => boolean) {
    const thread = this.thread;
    if (!thread) return;
    const status = await new Response(Bun.spawn(this.o.statusCmd, { env: this.o.env, stdout: "pipe", stderr: "ignore" }).stdout).text();
    if (!current()) return;
    const from = this.burstFrom ?? this.memory.msgs.length;
    const { prompt, spent } = deskInput(this.system, this.memory.render(from), status, this.memory.msgs.slice(from).map((m) => `${m.kind}: ${m.text}`).join("\n"));
    const proc = spawnDesk({ model: this.o.model, system: this.system, prompt, spent, memoryDir: `${this.o.dir}/memory`, cwd: `${this.o.dir}/desk`, env: this.o.env });
    this.run = proc;
    const { ok, drafted } = await readDesk(proc);
    if (this.run !== proc) return; // cancelled while drafting
    this.run = undefined;
    if (!current()) return;
    this.burstFrom = undefined;
    const { skip, tapback, outcome } = verdict(ok, drafted);
    let sent = "";
    if (tapback || !skip) {
      // `--` keeps a text that starts with "-" from being read as an option. The desk's own call must not stand it down.
      const args = tapback ? ["--react", tapback, "--thread", thread] : ["--thread", thread, "--", drafted];
      const reply = Bun.spawn([...this.o.replyCmd, ...args], { env: { ...this.o.env, INSTAGRAM_DM_ACTOR: "desk" }, stdout: "ignore", stderr: "pipe" });
      const [exit, err] = await Promise.all([reply.exited, new Response(reply.stderr).text()]);
      // fm-insta-reply says why it failed (exception class, endpoint, backoff or halt) on stderr: keep it in the desk log.
      if (exit !== 0) sent = ` (send failed, exit ${exit}: ${err.trim().replace(/\s+/g, " ").slice(0, 300)})`;
    }
    appendFileSync(`${this.o.dir}/desk.log`, `${new Date().toISOString()} ${this.lastId} ${outcome}${sent}\n`, { mode: 0o600 });
  }
}

// The complete new lines of a log from byte `from`, parsed, and the offset after them. A torn last line waits for its
// newline; a shrunken file starts over.
export function readNew(file: string, from: number): { rows: Row[]; next: number } {
  if (!existsSync(file)) return { rows: [], next: from };
  const buf = readFileSync(file);
  if (buf.length < from) from = 0;
  const end = buf.lastIndexOf(10) + 1;
  if (end <= from) return { rows: [], next: from };
  const rows = buf.subarray(from, end).toString().split("\n").flatMap((l) => {
    try {
      return l ? [JSON.parse(l) as Row] : [];
    } catch {
      return []; // a torn or foreign line
    }
  });
  return { rows, next: end };
}

// Follow both logs. Offsets persist in `offsetsFile`; with none, the logs are followed from their ends, so old DMs are
// never answered. Each tick merges the new rows of both logs by time, the DM first on a tie.
export function follow(desk: InstagramDesk, messages: string, sent: string, offsetsFile: string, ms = 500): () => void {
  let offsets: { messages: number; sent: number } = existsSync(offsetsFile)
    ? JSON.parse(readFileSync(offsetsFile, "utf8"))
    : { messages: existsSync(messages) ? statSync(messages).size : 0, sent: existsSync(sent) ? statSync(sent).size : 0 };
  const tick = () => {
    const m = readNew(messages, offsets.messages);
    const s = readNew(sent, offsets.sent);
    const rows = [...m.rows.map((r) => ["messages", r] as const), ...s.rows.map((r) => ["sent", r] as const)].sort((a, b) => a[1].at - b[1].at);
    for (const [source, row] of rows) desk.feed(source, row, Date.now() / 1000 - row.at <= FRESH_S);
    if (m.next !== offsets.messages || s.next !== offsets.sent || !existsSync(offsetsFile)) {
      offsets = { messages: m.next, sent: s.next };
      writeFileSync(`${offsetsFile}.tmp`, JSON.stringify(offsets), { mode: 0o600 });
      renameSync(`${offsetsFile}.tmp`, offsetsFile);
    }
  };
  const timer = setInterval(tick, ms);
  tick();
  return () => clearInterval(timer);
}

if (import.meta.main) {
  const env = process.env;
  const home = env.HOME ?? "";
  const igDir = env.INSTAGRAM_DM_DIR || `${home}/.local/state/instagram-dm`;
  const state = env.STATE_DIRECTORY || `${home}/.local/state/instagram-desk`;
  const children = new Set<Bun.Subprocess>();
  let stopping = false;
  const track = <T extends Bun.Subprocess>(proc: T): T => {
    children.add(proc);
    void proc.exited.finally(() => children.delete(proc));
    return proc;
  };
  process.on("SIGTERM", () => {
    stopping = true;
    for (const proc of children) proc.kill("SIGTERM");
    process.exit(0);
  });
  const fmHome = env.FM_HOME;
  const desk = new InstagramDesk({
    dir: state,
    model: env.FM_INSTAGRAM_DESK_MODEL || "claude-haiku-5-5",
    owner: env.FM_INSTAGRAM_DESK_OWNER_NAME || "the owner",
    supervisorModel: env.FM_INSTAGRAM_DESK_SUPERVISOR_MODEL || "",
    quietMs: Number(env.FM_INSTAGRAM_DESK_QUIET_MS || 8000),
    replyCmd: (env.FM_INSTA_REPLY_CMD || "fm-insta-reply").split(/\s+/),
    statusCmd: (env.FM_INBOX_CMD || `${fmHome}/bin/fm-inbox.sh`).split(/\s+/).concat("status"),
    env: { ...env, FM_HOME: fmHome },
    chat: (system) => compactChat(system, () => stopping, track),
    log: (e) => console.error("instagram-desk:", e),
  });
  follow(desk, env.INSTAGRAM_DM_LOG || `${igDir}/messages.jsonl`, env.INSTAGRAM_DM_SENT || `${igDir}/sent.jsonl`, `${state}/offsets.json`);
  console.log("instagram-desk: following the Instagram DM logs");
}
