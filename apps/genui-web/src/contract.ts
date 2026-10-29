// Stub copy of the shared genui contract (data/cf-genui-build/shared.md, "Parallel slices").
// Replace this file with an import from @crewship/genui-spec when P1 lands.

export type Rect = { x: number; y: number; w: number; h: number };

export type Component = {
  type: string;
  props: Record<string, unknown>;
  children?: string[];
  style?: Record<string, string>;
  rect?: Rect;
};

export type Link = { from: string; to: string };

export type Spec = {
  components: Record<string, Component>;
  links: Link[];
  tokens: Record<string, string>;
};

/** One RFC 6902 operation; the canvas uses add, remove and replace. */
export type PatchOp =
  | { op: "add" | "replace"; path: string; value: unknown }
  | { op: "remove"; path: string };

export type Actor = "agent" | "user";

export type Op = { seq: number; actor: Actor; cause: string; patch: PatchOp[]; inverse: PatchOp[] };

export type IntentKind = "move" | "resize" | "link" | "pin" | "style" | "input";

/** baseSeq: the seq the user saw; under "agent wins" the server rejects a move older than the agent's last write. */
export type Intent = { t: "intent"; id: string; kind: IntentKind; targetId: string; payload: Record<string, unknown>; baseSeq?: number };

export type ClientMsg = { t: "hello"; boardId: string; clientId: string } | Intent | { t: "undo" };

export type ServerMsg =
  | { t: "snapshot"; seq: number; spec: Spec }
  | { t: "ops"; ops: Op[] }
  | { t: "ack"; id: string; seq: number }
  | { t: "error"; id: string; msg: string };

export type AgentTool = "emit_view" | "set_style" | "link" | "pin" | "reset";

export type AgentCall = { tool: AgentTool; args: Record<string, unknown> };
