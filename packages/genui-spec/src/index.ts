// Contract shared by genui-agent-kit, genui-server and genui-web.
// Wire = AG-UI event shapes (type + fields) carrying json-render style spec patches.
import { z } from "zod";

// ---- style tokens: HSL only, whitelisted CSS vars, no raw CSS ----
const hsl = z.string().regex(/^hsl\(\s*\d{1,3}(\.\d+)?\s+\d{1,3}(\.\d+)?%\s+\d{1,3}(\.\d+)?%(\s*\/\s*[\d.]+%?)?\s*\)$/, "HSL color only");
export const STYLE_VARS = [
  "--gu-bg", "--gu-card", "--gu-line", "--gu-fg", "--gu-muted", "--gu-accent",
  "--gu-radius", "--gu-gap", "--gu-font-scale", "--gu-motion",
] as const;
export const styleTokens = z.object({
  "--gu-bg": hsl, "--gu-card": hsl, "--gu-line": hsl, "--gu-fg": hsl, "--gu-muted": hsl, "--gu-accent": hsl,
  "--gu-radius": z.string().regex(/^\d{1,2}px$/),
  "--gu-gap": z.string().regex(/^\d{1,2}px$/),
  "--gu-font-scale": z.string().regex(/^[0-2](\.\d+)?$/),
  "--gu-motion": z.enum(["none", "calm", "lively"]),
}).partial().strict();
export type StyleTokens = z.infer<typeof styleTokens>;

// ---- component catalog ----
const id = z.string().min(1).max(64);
const layout = z.object({
  cluster: id.optional(),
  priority: z.number().int().min(0).max(9).optional(),
  size: z.object({ w: z.number().positive(), h: z.number().positive() }).optional(),
  pos: z.object({ x: z.number(), y: z.number() }).optional(),
  pinned: z.boolean().optional(),
  hidden: z.boolean().optional(),
});
const el = <T extends string, P extends z.ZodTypeAny>(type: T, props: P) =>
  z.object({ type: z.literal(type), props: props, children: z.array(id).default([]), layout: layout.optional(), style: styleTokens.optional() });

export const catalog = {
  Stack: el("Stack", z.object({ dir: z.enum(["row", "column"]).default("column") })),
  Card: el("Card", z.object({ title: z.string().max(120).optional() })),
  Text: el("Text", z.object({ text: z.string().max(4000), tone: z.enum(["normal", "muted", "accent"]).default("normal") })),
  Metric: el("Metric", z.object({ label: z.string().max(80), value: z.union([z.string(), z.number()]), unit: z.string().max(16).optional() })),
  Table: el("Table", z.object({ columns: z.array(z.string()).max(20), rows: z.array(z.array(z.union([z.string(), z.number()]))).max(500) })),
  Badge: el("Badge", z.object({ text: z.string().max(40), tone: z.enum(["ok", "warn", "bad", "info"]).default("info") })),
  Image: el("Image", z.object({ src: z.string().max(500), alt: z.string().max(200) })),
  Input: el("Input", z.object({ name: id, placeholder: z.string().max(200).optional() })),
  Button: el("Button", z.object({ label: z.string().max(60), intent: id })),
  // Sandboxed iframe for anything the catalog lacks.
  Custom: el("Custom", z.object({ html: z.string().max(100_000) })),
} as const;

const c = catalog;
export const element = z.discriminatedUnion("type", [c.Stack, c.Card, c.Text, c.Metric, c.Table, c.Badge, c.Image, c.Input, c.Button, c.Custom]);
export type Element = z.infer<typeof element>;

// The whole page, shell included (header, input box, selection bar, work rail, canvas), is one spec.
export const SHELL_SLOTS = ["header", "input", "selection", "rail", "canvas"] as const;
// The sketch layer is always the top z-layer; the spec has no field for it.
export const SKETCH_Z = Number.MAX_SAFE_INTEGER;

export const links = z.array(z.object({ from: id, to: id, label: z.string().max(60).optional() }));
export const spec = z.object({
  root: z.string().max(64), // "" = empty board
  elements: z.record(id, element),
  style: styleTokens.default({}),
  links: links.default([]),
});
export type Spec = z.infer<typeof spec>;

// ---- JSON Patch (RFC 6902 subset) ----
export const patchOp = z.discriminatedUnion("op", [
  z.object({ op: z.literal("add"), path: z.string(), value: z.unknown() }),
  z.object({ op: z.literal("replace"), path: z.string(), value: z.unknown() }),
  z.object({ op: z.literal("remove"), path: z.string() }),
]);
export type PatchOp = z.infer<typeof patchOp>;

// ---- AG-UI event shapes (event format only, no AG-UI runtime) ----
const base = { timestamp: z.number().optional() };
export const event = z.discriminatedUnion("type", [
  z.object({ type: z.literal("RUN_STARTED"), threadId: id, runId: id, ...base }),
  z.object({ type: z.literal("RUN_FINISHED"), threadId: id, runId: id, ...base }),
  z.object({ type: z.literal("RUN_ERROR"), message: z.string(), code: z.string().optional(), ...base }),
  z.object({ type: z.literal("TOOL_CALL_START"), toolCallId: id, toolCallName: id, ...base }),
  z.object({ type: z.literal("TOOL_CALL_ARGS"), toolCallId: id, delta: z.string(), ...base }),
  z.object({ type: z.literal("TOOL_CALL_END"), toolCallId: id, ...base }),
  // snapshot = spec at `seq`; delta = patch ops that move spec to `seq`.
  z.object({ type: z.literal("STATE_SNAPSHOT"), snapshot: spec, seq: z.number().int().nonnegative(), ...base }),
  z.object({ type: z.literal("STATE_DELTA"), delta: z.array(patchOp), seq: z.number().int().positive(), ...base }),
  // user -> agent: Button/Input intents
  z.object({ type: z.literal("CUSTOM"), name: z.literal("intent"), value: z.object({ intent: id, data: z.record(z.string(), z.unknown()).optional() }), ...base }),
]);
export type GenuiEvent = z.infer<typeof event>;

// ---- op log row (DO SQLite): every op keeps its inverse for undo/rewind ----
export const opRow = z.object({
  seq: z.number().int().positive(),
  actor: z.string().min(1),        // "agent:<id>" | "user:<id>"
  cause: z.number().int().positive().nullable(), // seq of the op this one reacts to
  patch: z.array(patchOp),
  inverse: z.array(patchOp),
  at: z.number(),
});
export type OpRow = z.infer<typeof opRow>;
export const SNAPSHOT_EVERY = 100;

// ---- minimal patch apply (immutable) used by server and web ----
const unesc = (s: string) => s.replace(/~1/g, "/").replace(/~0/g, "~");
type Node = Record<string, unknown> | unknown[];
const isNode = (v: unknown): v is Node => typeof v === "object" && v !== null;
export function applyPatch<T>(doc: T, ops: PatchOp[]): T {
  let cur: unknown = structuredClone(doc);
  for (const o of ops) {
    const keys = o.path.split("/").slice(1).map(unesc);
    if (!keys.length) { if (o.op !== "remove") cur = o.value; continue; }
    let p: unknown = cur;
    for (const k of keys.slice(0, -1)) p = isNode(p) ? (p as Record<string, unknown>)[k] : undefined;
    if (!isNode(p)) throw new Error(`bad path ${o.path}`);
    const last = keys[keys.length - 1];
    if (Array.isArray(p)) {
      const i = last === "-" ? p.length : Number(last);
      if (o.op === "remove") p.splice(i, 1);
      else p.splice(i, o.op === "add" ? 0 : 1, o.value);
    } else if (o.op === "remove") delete p[last];
    else p[last] = o.value;
  }
  return cur as T; // patches are validated upstream against the spec schema
}
