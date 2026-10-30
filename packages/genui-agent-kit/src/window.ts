import type { PatchOp, Rect } from "@crewship/genui-spec";

/** Scriptable floating windows over the board, like Rex's floating layers: open, move, raise, lower, float, sink, close. */
export type WindowCmd = "open" | "move" | "raise" | "lower" | "float" | "sink" | "close";
export const WINDOW_CMDS: readonly WindowCmd[] = ["open", "move", "raise", "lower", "float", "sink", "close"];

export type WindowOpts = { title?: string; body?: string; src?: string; at?: Partial<Rect>; now?: number };

const ID = /^[A-Za-z0-9_-]{1,64}$/;

/** "x,y" or "x,y,w,h" in board px. */
export function parseAt(s: string): Partial<Rect> {
  const n = s.split(",").map(Number);
  if ((n.length !== 2 && n.length !== 4) || n.some((v) => !Number.isFinite(v))) throw new Error(`--at wants x,y or x,y,w,h, got "${s}"`);
  const [x, y, w, h] = n;
  return n.length === 4 ? { x, y, w, h } : { x, y };
}

/** The board patch one window command makes; the layer is a time stamp, so the last raised window is on top. */
export function windowPatch(cmd: WindowCmd, id: string, o: WindowOpts = {}): PatchOp[] {
  if (!ID.test(id)) throw new Error(`window id must be 1-64 of A-Z a-z 0-9 _ -, got "${id}"`);
  const at = `/components/${id}`;
  const prop = (k: string, value: unknown): PatchOp => ({ op: "add", path: `${at}/props/${k}`, value });
  const stamp = Math.floor((o.now ?? Date.now()) / 1000);
  const rect = { x: 0, y: 0, w: 380, h: 240, ...o.at };
  switch (cmd) {
    case "open": {
      const look = o.src ? { kind: "embed", type: "site", src: o.src, ar: "4/3" } : { kind: "note", body: o.body ?? "" };
      const props = { ...look, proj: "me", base: 80, title: o.title ?? id, float: true, layer: stamp, removed: false };
      return [{ op: "add", path: at, value: { type: "card", props, rect } }];
    }
    case "move":
      if (!o.at) throw new Error("move needs --at x,y[,w,h]");
      return Object.entries(o.at).map(([k, v]) => ({ op: "add", path: `${at}/rect/${k}`, value: v }));
    case "float":
      return [...(o.at ? [{ op: "add", path: `${at}/rect`, value: rect } as PatchOp] : []), prop("float", true), prop("layer", stamp)];
    case "raise":
      return [prop("layer", stamp)];
    case "lower":
      return [prop("layer", -stamp)];
    case "sink":
      return [prop("float", false)];
    case "close":
      return [prop("removed", true)];
  }
}
