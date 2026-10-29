// Pure board state for the canvas: JSON patches, intents, and the agent-vs-user move rule.
// No DOM here, so the mock server and the tests use the same code.
import { emptyBoard, type Component, type IntentMsg, type IntentKind, type Op, type PatchOp, type Rect, type ServerMsg, type BoardSpec } from "@crewship/genui-spec";

export const MIN_W = 160;
export const MIN_H = 96;
const DEFAULT_RECT: Rect = { x: 40, y: 40, w: 300, h: 180 };

const unescape = (s: string) => s.replace(/~1/g, "/").replace(/~0/g, "~");
export const esc = (s: string) => s.replace(/~/g, "~0").replace(/\//g, "~1");

type Container = Record<string, unknown> | unknown[];
const isContainer = (v: unknown): v is Container => v !== null && typeof v === "object";

function walk(doc: unknown, path: string): { parent: Container; key: string } {
  const parts = path.split("/").slice(1).map(unescape);
  if (!parts.length) throw new Error("patch on the document root");
  if (parts.includes("__proto__")) throw new Error(`bad path ${path}`);
  let node: unknown = doc;
  for (const p of parts.slice(0, -1)) {
    if (!isContainer(node)) break;
    node = Array.isArray(node) ? node[Number(p)] : Object.hasOwn(node, p) ? node[p] : undefined;
  }
  if (!isContainer(node)) throw new Error(`no path ${path}`);
  return { parent: node, key: parts[parts.length - 1] };
}

function applyOne(doc: unknown, o: PatchOp) {
  const { parent, key } = walk(doc, o.path);
  if (Array.isArray(parent)) {
    const i = key === "-" ? parent.length : Number(key);
    if (!Number.isInteger(i) || i < 0 || i > parent.length) throw new Error(`bad index ${o.path}`);
    if (o.op === "add") parent.splice(i, 0, structuredClone(o.value));
    else if (i >= parent.length) throw new Error(`no path ${o.path}`);
    else if (o.op === "remove") parent.splice(i, 1);
    else parent[i] = structuredClone(o.value);
    return;
  }
  if (o.op !== "add" && !(key in parent)) throw new Error(`no path ${o.path}`);
  if (o.op === "remove") delete parent[key];
  else parent[key] = structuredClone(o.value);
}

/** Returns a new document; the input is not changed. Throws on a path that does not resolve. */
export function applyPatch<T>(doc: T, patch: PatchOp[]): T {
  const out = structuredClone(doc);
  for (const o of patch) applyOne(out, o);
  return out;
}

/** The patch that undoes `patch` when applied after it. */
export function invertPatch(doc: unknown, patch: PatchOp[]): PatchOp[] {
  const work = structuredClone(doc);
  const inverse: PatchOp[] = [];
  for (const o of patch) {
    const { parent, key } = walk(work, o.path);
    if (Array.isArray(parent)) {
      const i = key === "-" ? parent.length : Number(key);
      const at = o.path.slice(0, o.path.lastIndexOf("/") + 1) + i;
      if (o.op === "add") inverse.push({ op: "remove", path: at });
      else inverse.push({ op: o.op === "remove" ? "add" : "replace", path: at, value: structuredClone(parent[i]) });
    } else if (o.op === "add" && !(key in parent)) inverse.push({ op: "remove", path: o.path });
    else inverse.push({ op: o.op === "remove" ? "add" : "replace", path: o.path, value: structuredClone(parent[key]) });
    applyOne(work, o);
  }
  return inverse.reverse();
}

/** The component id when `path` changes its rect (or the whole component, with `whole`). */
export function rectId(path: string, whole = false): string | undefined {
  const m = /^\/components\/([^/]+)(\/rect(?:\/.*)?)?$/.exec(path);
  return m && (m[2] || whole) ? unescape(m[1]) : undefined;
}

/** True when a user move of `id` must survive an agent move: "user wins" in the header, or the card is pinned. */
export const userKeeps = (spec: BoardSpec, id: string) =>
  spec.components.header?.props.wins === "user" || spec.components[id]?.props.pinned === true;

/** Server side of the move rule: drop agent rect changes on a pinned card, and on a card the user placed while the user wins. */
export const filterAgentPatch = (spec: BoardSpec, patch: PatchOp[], placed: Set<string>) =>
  patch.filter((o) => {
    const id = rectId(o.path);
    return !(id && (spec.components[id]?.props.pinned === true || (placed.has(id) && userKeeps(spec, id))));
  });

const STYLE_KEY = /^[a-z][a-z0-9-]{0,40}$/;
// HSL only, and nothing that loads a URL or breaks out of a declaration.
const STYLE_BAD = /url\(|image|#|rgb|hwb|lab\(|lch\(|color\(|[;{}<>\\]|expression/i;

/** Keeps only token entries that are safe to set as CSS custom properties. */
export function safeStyle(tokens: Record<string, unknown> | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(tokens ?? {}))
    if (STYLE_KEY.test(k) && typeof v === "string" && v.length <= 80 && !STYLE_BAD.test(v)) out[k] = v;
  return out;
}

const num = (v: unknown, fallback: number) => (typeof v === "number" && Number.isFinite(v) ? Math.round(v) : fallback);

/** The spec change an intent asks for. The client shows it at once; the server makes it real. */
export function intentPatch(spec: BoardSpec, kind: IntentKind, targetId: string, payload: Record<string, unknown>): PatchOp[] {
  const c: Component | undefined = Object.hasOwn(spec.components, targetId) ? spec.components[targetId] : undefined;
  if (!c) throw new Error(`unknown component ${targetId}`);
  const base = `/components/${esc(targetId)}`;
  const r = c.rect ?? DEFAULT_RECT;
  switch (kind) {
    case "move":
      return [{ op: "add", path: `${base}/rect`, value: { ...r, x: num(payload.x, r.x), y: num(payload.y, r.y) } }];
    case "resize":
      return [{ op: "add", path: `${base}/rect`, value: { ...r, w: Math.max(MIN_W, num(payload.w, r.w)), h: Math.max(MIN_H, num(payload.h, r.h)) } }];
    case "link": {
      const to = payload.to;
      if (typeof to !== "string" || to === targetId || !spec.components[to]) return [];
      if (spec.links.some((l) => (l.from === targetId && l.to === to) || (l.from === to && l.to === targetId))) return [];
      return [{ op: "add", path: "/links/-", value: { from: targetId, to } }];
    }
    case "pin":
      return [{ op: "add", path: `${base}/props/pinned`, value: payload.pinned === true }];
    case "style":
      return [{ op: "add", path: `${base}/style`, value: { ...c.style, ...safeStyle(payload.tokens as Record<string, unknown>) } }];
    case "input":
      // A field is a control value on the component (the header's wins toggle); plain text goes to the agent only.
      return typeof payload.field === "string" && STYLE_KEY.test(payload.field)
        ? [{ op: "add", path: `${base}/props/${esc(payload.field)}`, value: payload.value }]
        : [];
  }
}

type Pending = { targetId: string; patch: PatchOp[] };

/** Confirmed server state plus the user's not-yet-acked intents laid over it. */
export class Board {
  spec: BoardSpec = emptyBoard();
  seq = 0;
  pending = new Map<string, Pending>();

  /** Applies a server message. Returns an error text to show, if any. */
  receive(msg: ServerMsg): string | undefined {
    if (msg.t === "snapshot") {
      this.spec = msg.spec;
      this.seq = msg.seq;
      this.pending.clear();
    } else if (msg.t === "ops") {
      for (const op of msg.ops) if (op.seq > this.seq) this.applyOp(op);
    } else if (msg.t === "ack") {
      this.pending.delete(msg.id);
    } else if (msg.t === "error") {
      this.pending.delete(msg.id);
      return msg.msg;
    }
  }

  private applyOp(op: Op) {
    this.spec = applyPatch(this.spec, op.patch);
    this.seq = op.seq;
    if (op.actor !== "agent") return;
    for (const [id, p] of this.pending) {
      const moved = op.patch.some((o) => rectId(o.path, true) === p.targetId);
      if (moved && p.patch.some((o) => rectId(o.path)) && !userKeeps(this.spec, p.targetId)) this.pending.delete(id);
    }
  }

  /** Lays an intent over the view at once; returns it ready to send. */
  propose(kind: IntentKind, targetId: string, payload: Record<string, unknown>): IntentMsg {
    const id = crypto.randomUUID();
    const patch = intentPatch(this.view(), kind, targetId, payload);
    if (patch.length) this.pending.set(id, { targetId, patch });
    return { t: "intent", id, kind, targetId, payload, baseSeq: this.seq };
  }

  /** The spec to draw: confirmed state plus pending intents that still apply. */
  view(): BoardSpec {
    let s = this.spec;
    for (const p of this.pending.values()) {
      try {
        s = applyPatch(s, p.patch);
      } catch {
        // the target went away under the intent; the server will reject it
      }
    }
    return s;
  }
}
