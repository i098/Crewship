import type { GenuiClient } from "./client";
import type { PatchOp } from "@crewship/genui-spec";

export type StatusLine = { state: string; at?: number; text: string };

const NAME = /^[a-z][a-z-]*/;

/** Parses `state [at=epoch]: text`. Returns undefined for any other line. Linear time: no nested quantifiers. */
export function parseStatusLine(line: string): StatusLine | undefined {
  const t = line.trim();
  const name = NAME.exec(t);
  if (!name) return undefined;
  let i = name[0].length;
  const tags: string[] = [];
  for (;;) {
    while (t[i] === " " || t[i] === "\t") i++;
    if (t[i] !== "[") break;
    const end = t.indexOf("]", i);
    if (end < 0) return undefined;
    tags.push(t.slice(i, end + 1));
    i = end + 1;
  }
  if (t[i] !== ":") return undefined;
  const at = /\[at=(\d+)\]/.exec(tags.join(""));
  return { state: name[0], at: at ? Number(at[1]) : undefined, text: t.slice(i + 1).trim() };
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
