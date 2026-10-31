import type { Op, BoardSpec } from "@crewship/genui-spec";

export interface Store {
  append(op: Op): void;
  /** Ops with seq > after, ascending. */
  opsAfter(after: number): Op[];
  latestSnapshot(): { seq: number; spec: BoardSpec } | null;
  saveSnapshot(seq: number, spec: BoardSpec): void;
}

export class MemoryStore implements Store {
  ops: Op[] = [];
  snaps: { seq: number; spec: BoardSpec }[] = [];
  append(op: Op) { this.ops.push(structuredClone(op)); }
  opsAfter(after: number) { return this.ops.filter((o) => o.seq > after).map((o) => structuredClone(o)); }
  latestSnapshot() { const s = this.snaps[this.snaps.length - 1]; return s ? structuredClone(s) : null; }
  saveSnapshot(seq: number, spec: BoardSpec) { this.snaps.push({ seq, spec: structuredClone(spec) }); }
}
