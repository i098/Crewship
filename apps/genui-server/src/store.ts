import type { Op, Spec } from "./contract";

export interface Store {
  append(op: Op): void;
  /** Ops with seq > after, ascending. */
  opsAfter(after: number): Op[];
  latestSnapshot(): { seq: number; spec: Spec } | null;
  saveSnapshot(seq: number, spec: Spec): void;
}

export class MemoryStore implements Store {
  ops: Op[] = [];
  snaps: { seq: number; spec: Spec }[] = [];
  append(op: Op) { this.ops.push(structuredClone(op)); }
  opsAfter(after: number) { return this.ops.filter((o) => o.seq > after).map((o) => structuredClone(o)); }
  latestSnapshot() { const s = this.snaps[this.snaps.length - 1]; return s ? structuredClone(s) : null; }
  saveSnapshot(seq: number, spec: Spec) { this.snaps.push({ seq, spec: structuredClone(spec) }); }
}
