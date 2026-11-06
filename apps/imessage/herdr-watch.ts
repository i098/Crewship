import { existsSync, readFileSync, statSync, watch, type FSWatcher } from "node:fs";

// Alerts from herdr agent status (read-only: the bridge only runs `herdr agent list`). The watcher keeps the last
// confirmed status per pane, holds a change for `debounceMs` so a status that flips back is ignored, and turns the
// confirmed changes of one poll into one plain text. Kept free of the bridge so tests run on recorded JSON.
import { basename } from "node:path";
import { cleanText } from "./clean.ts";

export type HerdrConfig = { alertOn: string[]; debounceMs: number; skip: string[] };
type Agent = { id: string; status: string; project: string; task: string };

const SAY: Record<string, string> = { done: "is done", blocked: "needs your input", idle: "is idle" };

// Workers only: a pane with a supervisor token, or one whose project folder is in `skip`, is not a worker.
export function agentsOf(json: string, skip: string[]): Agent[] {
  const list: unknown = JSON.parse(json)?.result?.agents;
  if (!Array.isArray(list)) throw new Error("herdr agent list: no agents array");
  const out: Agent[] = [];
  for (const a of list) {
    const id = a?.pane_id, status = a?.agent_status, dir = a?.foreground_cwd ?? a?.cwd;
    if (typeof id !== "string" || typeof status !== "string" || typeof dir !== "string") continue;
    const project = basename(dir.replace(/\/+$/, ""));
    if (a.tokens?.who || skip.includes(project)) continue;
    // The pane title is "<glyph> PREFIX: task"; keep the task words.
    const task = String(a.terminal_title_stripped ?? a.display_agent ?? "").replace(/^[^\p{L}\p{N}]+/u, "").replace(/^[A-Z]{2,}:\s*/, "").trim();
    out.push({ id, status, project, task });
  }
  return out;
}

export class HerdrWatch {
  private seen = new Map<string, string>(); // pane -> last confirmed status
  private held = new Map<string, { status: string; since: number; line: string }>();

  constructor(private config: HerdrConfig) {}

  private alerts(status: string) {
    return this.config.alertOn.includes(status) && SAY[status] !== undefined;
  }

  private forgetClosed(live: Set<string>): string[] {
    const lines: string[] = [];
    for (const id of [...this.seen.keys()]) {
      if (live.has(id)) continue;
      const held = this.held.get(id);
      if (held && this.alerts(held.status)) lines.push(held.line);
      this.seen.delete(id);
      this.held.delete(id);
    }
    return lines;
  }

  // Takes one `herdr agent list` output; returns the text to send, if a change is confirmed. The first poll only records.
  poll(json: string, now: number): string | undefined {
    const agents = agentsOf(json, this.config.skip);
    const lines = this.forgetClosed(new Set(agents.map((a) => a.id)));
    const first = this.seen.size === 0 && this.held.size === 0;
    for (const a of agents) {
      const was = this.seen.get(a.id);
      if (was === undefined || first) { this.seen.set(a.id, a.status); continue; }
      if (a.status === was) { this.held.delete(a.id); continue; }
      const held = this.held.get(a.id);
      if (held?.status !== a.status) {
        const line = `${a.task ? `The agent on "${a.task}"` : "An agent"} in ${a.project} ${SAY[a.status] ?? ""}.`;
        this.held.set(a.id, { status: a.status, since: now, line });
        continue;
      }
      if (now - held.since < this.config.debounceMs) continue;
      this.held.delete(a.id);
      this.seen.set(a.id, a.status);
      if (this.alerts(a.status)) lines.push(held.line);
    }
    if (!lines.length) return undefined;
    return cleanText(lines.length === 1 ? lines[0]! : `${lines.length} agent updates:\n${lines.map((l) => `- ${l}`).join("\n")}`);
  }
}

// The omp extension fm-stranded-wake.ts appends "<epoch>\twoken\tnotes=N\tqueue=bool" to state/.stranded-wake.log
// when it starts a turn in an idle main. This turns each new line into one honest owner text, at most one per cooldown.
export const WAKE_NOTICE_COOLDOWN_MS = 30 * 60_000;

export function wakeNotice(lines: string[]): string | undefined {
  const notes = lines.map((l) => /\twoken\tnotes=(\d+)/.exec(l)).filter((m) => m).map((m) => Number(m![1]));
  if (!notes.length) return undefined;
  const n = Math.max(...notes);
  return `Main was idle and ${n > 0 ? `${n} of your note${n > 1 ? "s were" : " was"}` : "a queued wake was"} waiting, so I woke it. It should answer in a minute.`;
}

/** Watches the wake log; `send` gets the text. Returns the watcher, or undefined when the state folder is missing. */
export function watchStrandedWake(log: string, send: (text: string) => boolean, now = Date.now): FSWatcher | undefined {
  let offset = existsSync(log) ? statSync(log).size : 0;
  let lastSent = -Infinity;
  const read = () => {
    if (!existsSync(log)) return;
    const size = statSync(log).size;
    if (size < offset) offset = 0;
    if (size === offset) return;
    const text = readFileSync(log, "utf8").slice(offset);
    const notice = wakeNotice(text.split("\n").filter(Boolean));
    if (notice && now() - lastSent >= WAKE_NOTICE_COOLDOWN_MS) {
      if (!send(notice)) return;
      lastSent = now();
    }
    offset = size;
  };
  const dir = log.slice(0, log.lastIndexOf("/"));
  return existsSync(dir) ? watch(dir, (_event, name) => { if (name === ".stranded-wake.log") read(); }) : undefined;
}
