import type { GenuiClient } from "./client";
import type { PatchOp } from "./contract";

export type StatusLine = { state: string; at?: number; text: string };

const LINE = /^([a-z][a-z-]*)((?:\s*\[[^\]]*\])*):\s*(.*)$/;

/** Parses `state [at=epoch]: text`. Returns undefined for any other line. */
export function parseStatusLine(line: string): StatusLine | undefined {
  const m = LINE.exec(line.trim());
  if (!m) return undefined;
  const at = /\[at=(\d+)\]/.exec(m[2]);
  return { state: m[1], at: at ? Number(at[1]) : undefined, text: m[3] };
}

/** Component id for a crewmate task; `/` and `~` are escaped for the JSON pointer. */
export const taskComponentId = (task: string) => `task-${task.replace(/[^\w-]/g, "_")}`;

export function statusPatch(task: string, s: StatusLine): PatchOp[] {
  return [
    {
      op: "add", // RFC 6902 add replaces an existing object member
      path: `/components/${taskComponentId(task)}`,
      value: { type: "StatusCard", props: { task, state: s.state, text: s.text, at: s.at } },
    },
  ];
}

const HEADER = /^==> (.+?)(?:\.status)? <==$/; // `tail -F a.status b.status` file headers

/** Feeds lines (from stdin or `tail -F`) to emit_view. `defaultTask` applies until a tail header names one. */
export function createBridge(client: GenuiClient, defaultTask = "firstmate") {
  let task = defaultTask;
  return async (line: string) => {
    const h = HEADER.exec(line.trim());
    if (h) {
      task = h[1].split("/").pop()!;
      return;
    }
    const s = parseStatusLine(line);
    if (s) await client.emitView(statusPatch(task, s));
  };
}
