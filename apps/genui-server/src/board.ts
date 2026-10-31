import { type AgentCall, type Actor, type ClientMsg, type Op, type PatchOp, type Rect, type BoardSpec, emptyBoard } from "@crewship/genui-spec";
import { guardPatch } from "./guard";
import { applyPatch, pointer, validatePatch } from "./patch";
import type { Store } from "./store";

export const SNAPSHOT_EVERY = 100;
const UNDO = "undo:";

type Intent = Extract<ClientMsg, { t: "intent" }>;
const rectPath = /^\/components\/([^/]+)\/rect(\/|$)/;

/** Board state machine: sequencing, op log, snapshots, undo, move conflicts. No I/O beyond Store. */
export class Board {
  spec: BoardSpec = emptyBoard();
  seq = 0;
  private rectWriter = new Map<string, Actor>();
  private agentRectSeq = new Map<string, number>();
  private undone = new Set<number>();
  private userOps: Op[] = []; // undo candidates, ascending
  private agentOps: Op[] = [];

  constructor(private store: Store) {
    const snap = store.latestSnapshot();
    if (snap) { this.spec = snap.spec; this.seq = snap.seq; }
    // shortcut: bookkeeping replays the whole log on load; fine for one board, add a snapshot of it if logs get huge.
    for (const op of store.opsAfter(0)) {
      if (op.seq > this.seq) { this.spec = applyPatch(this.spec, op.patch).spec; this.seq = op.seq; }
      this.track(op);
    }
  }

  /** "User wins" is components.header.props.wins === "user" (default: agent wins). */
  get moveWins(): "agent" | "user" {
    return this.spec.components.header?.props?.wins === "user" ? "user" : "agent";
  }

  agent(call: AgentCall): Op[] {
    const a = call.args ?? {};
    const cause = typeof a.cause === "string" ? a.cause : `agent:${call.tool}`;
    let patch: PatchOp[];
    switch (call.tool) {
      case "emit_view": patch = this.emitPatch(a); break;
      case "set_style": patch = this.stylePatch((a.id === undefined ? undefined : str(a.id, "id")), obj(a.tokens, "tokens")); break;
      case "link": patch = [{ op: "add", path: "/links/-", value: { from: str(a.from, "from"), to: str(a.to, "to") } }]; break;
      case "pin": patch = this.pinPatch(str(a.id, "id"), a.pinned !== false); break;
      case "reset": patch = this.resetPatch(a); break;
      default: throw new Error(`unknown tool: ${(call as AgentCall).tool}`);
    }
    // Pinned cards always keep their placement; under "user wins" so does anything the user moved.
    if (call.tool !== "reset") patch = this.guard(patch, call.tool !== "pin");
    return patch.length || call.tool === "reset" ? [this.commit("agent", cause, patch)] : [];
  }

  intent(m: Intent): Op[] {
    if (m.kind === "input" && !("field" in m.payload)) return []; // {text}: forwarded to the agent, no spec change
    const id = m.targetId;
    this.component(id);
    if (m.kind === "move" || m.kind === "resize") {
      if (this.moveWins === "agent" && m.baseSeq !== undefined && (this.agentRectSeq.get(id) ?? 0) > m.baseSeq) {
        throw new Error("agent moved this component; agent wins");
      }
    }
    return [this.commit("user", m.id, this.intentPatch(m))];
  }

  /** Revert the latest user op and every later agent op that names it as cause. */
  undo(): Op[] {
    const target = [...this.userOps].reverse().find((o) => !this.undone.has(o.seq));
    if (!target) throw new Error("nothing to undo");
    const group = [target, ...this.agentOps.filter((o) => o.seq > target.seq && o.cause === target.cause && !this.undone.has(o.seq))];
    return group.reverse().map((o) => this.commit("user", UNDO + o.seq, o.inverse));
  }

  private commit(actor: Actor, cause: string, patch: PatchOp[]): Op {
    const { spec, inverse } = applyPatch(this.spec, validatePatch(patch));
    const op: Op = { seq: this.seq + 1, actor, cause, patch, inverse };
    this.store.append(op);
    this.spec = spec;
    this.seq = op.seq;
    this.track(op);
    if (op.seq % SNAPSHOT_EVERY === 0) this.store.saveSnapshot(op.seq, this.spec);
    return op;
  }

  private track(op: Op) {
    const undoes = op.cause.startsWith(UNDO) ? Number(op.cause.slice(UNDO.length)) : null;
    if (undoes !== null) this.undone.add(undoes);
    else (op.actor === "user" ? this.userOps : this.agentOps).push(op);
    for (const p of op.patch) {
      const m = rectPath.exec(p.path);
      if (!m) continue;
      if (undoes !== null) this.rectWriter.delete(m[1]);
      else {
        this.rectWriter.set(m[1], op.actor);
        if (op.actor === "agent") this.agentRectSeq.set(m[1], op.seq);
      }
    }
  }

  private guard(patch: PatchOp[], keepPin: boolean): PatchOp[] {
    const user = this.moveWins === "user";
    const components = this.spec.components;
    const rectLocked = (id: string) => (Object.hasOwn(components, id) && components[id].props?.pinned === true) || (user && this.rectWriter.get(id) === "user");
    return guardPatch({ components, rectLocked, keepPin }, patch);
  }

  private emitPatch(a: Record<string, unknown>): PatchOp[] {
    // AG-UI shape: { event: STATE_DELTA {delta} | STATE_SNAPSHOT {snapshot} }; also accept { patch } or a full { spec }.
    const ev = a.event as { delta?: unknown; snapshot?: unknown } | undefined;
    if (ev?.delta !== undefined) return validatePatch(ev.delta);
    if (a.patch !== undefined) return validatePatch(a.patch);
    const full = ev?.snapshot ?? a.spec;
    if (full && typeof full === "object") {
      const s = { ...emptyBoard(), ...(full as Partial<BoardSpec>) };
      return (["components", "links", "tokens"] as const).map((k) => ({ op: "add", path: "/" + k, value: s[k] }));
    }
    throw new Error("emit_view needs event.delta, event.snapshot, patch or spec");
  }

  private stylePatch(id: string | undefined, tokens: Record<string, unknown>): PatchOp[] {
    if (id === undefined) return [{ op: "add", path: "/tokens", value: { ...this.spec.tokens, ...tokens } }];
    const c = this.component(id);
    return [{ op: "add", path: pointer("components", id, "style"), value: { ...c.style, ...tokens } }];
  }

  private pinPatch(id: string, pinned: boolean): PatchOp[] {
    const c = this.component(id);
    return [{ op: "add", path: pointer("components", id, "props"), value: { ...c.props, pinned } }];
  }

  private resetPatch(a: Record<string, unknown>): PatchOp[] {
    const ids = a.id === undefined ? Object.keys(this.spec.components) : [str(a.id, "id")];
    const rect = a.rect as Rect | undefined;
    const patch: PatchOp[] = [];
    for (const id of ids) {
      const c = this.component(id);
      if (rect) patch.push({ op: c.rect ? "replace" : "add", path: pointer("components", id, "rect"), value: rect });
      else if (c.rect && this.rectWriter.get(id) === "user") patch.push({ op: "remove", path: pointer("components", id, "rect") });
      this.rectWriter.delete(id);
    }
    return patch;
  }

  private intentPatch(m: Intent): PatchOp[] {
    const id = m.targetId;
    const c = this.component(id);
    const p = m.payload;
    switch (m.kind) {
      case "move": case "resize": {
        const r = { ...(c.rect ?? { x: 0, y: 0, w: 0, h: 0 }) };
        const keys = m.kind === "move" ? (["x", "y"] as const) : (["w", "h"] as const);
        for (const k of keys) {
          if (typeof p[k] !== "number" || !Number.isFinite(p[k])) throw new Error(`payload.${k} must be a number`);
          r[k] = p[k] as number;
        }
        return [{ op: c.rect ? "replace" : "add", path: pointer("components", id, "rect"), value: r }];
      }
      case "link": {
        const to = str(p.to, "payload.to");
        this.component(to);
        return [{ op: "add", path: "/links/-", value: { from: id, to } }];
      }
      case "input": {
        const field = str(p.field, "payload.field");
        return [{ op: "add", path: pointer("components", id, "props"), value: { ...c.props, [field]: p.value } }];
      }
      case "pin": return this.pinPatch(id, p.pinned !== false);
      case "style": return this.stylePatch(id, obj(p.tokens ?? p, "payload.tokens"));
      default: throw new Error(`unknown intent kind: ${m.kind}`);
    }
  }

  private component(id: string) {
    const c = Object.hasOwn(this.spec.components, id) ? this.spec.components[id] : undefined;
    if (!c) throw new Error(`no such component: ${id}`);
    return c;
  }
}

function str(v: unknown, name: string): string {
  if (typeof v !== "string" || !v) throw new Error(`${name} must be a non-empty string`);
  return v;
}
function obj(v: unknown, name: string): Record<string, unknown> {
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error(`${name} must be an object`);
  return v as Record<string, unknown>;
}
