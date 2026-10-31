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
  private held = new Map<string, { status: string; since: number }>();

  constructor(private config: HerdrConfig) {}

  // Takes one `herdr agent list` output; returns the text to send, if a change is confirmed. The first poll only records.
  poll(json: string, now: number): string | undefined {
    const agents = agentsOf(json, this.config.skip);
    const live = new Set(agents.map((a) => a.id));
    for (const id of [...this.seen.keys()]) if (!live.has(id)) { this.seen.delete(id); this.held.delete(id); }
    const first = this.seen.size === 0 && this.held.size === 0;
    const lines: string[] = [];
    for (const a of agents) {
      const was = this.seen.get(a.id);
      if (was === undefined || first) { this.seen.set(a.id, a.status); continue; }
      if (a.status === was) { this.held.delete(a.id); continue; }
      const held = this.held.get(a.id);
      if (held?.status !== a.status) { this.held.set(a.id, { status: a.status, since: now }); continue; }
      if (now - held.since < this.config.debounceMs) continue;
      this.held.delete(a.id);
      this.seen.set(a.id, a.status);
      if (this.config.alertOn.includes(a.status) && SAY[a.status]) {
        lines.push(`${a.task ? `The agent on "${a.task}"` : "An agent"} in ${a.project} ${SAY[a.status]}.`);
      }
    }
    if (!lines.length) return undefined;
    return cleanText(lines.length === 1 ? lines[0]! : `${lines.length} agent updates:\n${lines.map((l) => `- ${l}`).join("\n")}`);
  }
}
