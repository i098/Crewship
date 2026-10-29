// Stub copy of the wire contract (see data/cf-genui-build/shared.md).
// shortcut: replace with an import from @crewship/genui-spec once P1 lands.

export type Rect = { x: number; y: number; w: number; h: number };

export type Component = {
  type: string;
  props: Record<string, unknown>;
  children?: string[];
  style?: Record<string, unknown>;
  rect?: Rect;
};

export type Spec = {
  components: Record<string, Component>;
  links: { from: string; to: string }[];
  tokens: Record<string, unknown>;
};

/** RFC 6902 subset: add, remove, replace. */
export type PatchOp =
  | { op: "add"; path: string; value: unknown }
  | { op: "replace"; path: string; value: unknown }
  | { op: "remove"; path: string };

export type Actor = "agent" | "user";

export type Op = {
  seq: number;
  actor: Actor;
  cause: string;
  patch: PatchOp[];
  inverse: PatchOp[];
};

export type IntentKind = "move" | "resize" | "link" | "pin" | "style" | "input";

export type ClientMsg =
  | { t: "hello"; boardId: string; clientId: string }
  // baseSeq (optional): the seq the client's view was at when the user acted; drives move conflicts.
  | { t: "intent"; id: string; kind: IntentKind; targetId: string; payload: Record<string, unknown>; baseSeq?: number }
  | { t: "undo" }
  // Header toggle: who wins a move conflict. Default "agent".
  | { t: "policy"; moveWins: MoveWins };

export type ServerMsg =
  | { t: "snapshot"; seq: number; spec: Spec; moveWins: MoveWins }
  | { t: "ops"; ops: Op[] }
  | { t: "ack"; id: string; seq: number }
  | { t: "error"; id: string; msg: string }
  // Sent only to sockets opened with ?role=agent.
  | { t: "intent"; id: string; kind: IntentKind; targetId: string; payload: Record<string, unknown> };

export type MoveWins = "agent" | "user";

export type AgentCall = {
  tool: "emit_view" | "set_style" | "link" | "pin" | "reset";
  args: Record<string, unknown>;
};

export const emptySpec = (): Spec => ({ components: {}, links: [], tokens: {} });
