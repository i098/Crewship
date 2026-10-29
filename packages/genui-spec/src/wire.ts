// Board wire contract shared by genui-server (P2), genui-web (P3) and genui-agent-kit (P4).
// The board is a flat component map; every change is an op with its inverse (undo, rewind).
export type PatchOp =
  | { op: "add" | "replace"; path: string; value: unknown }
  | { op: "remove"; path: string };

export type Rect = { x: number; y: number; w: number; h: number };

export type Component = {
  type: string;
  props: Record<string, unknown>;
  children?: string[];
  style?: Record<string, unknown>; // web turns only safe tokens into CSS variables (safeStyle)
  rect?: Rect;
};

export type Link = { from: string; to: string };

export type BoardSpec = {
  components: Record<string, Component>;
  links: Link[];
  tokens: Record<string, unknown>;
};

export const emptyBoard = (): BoardSpec => ({ components: {}, links: [], tokens: {} });

export type Actor = "agent" | "user";

export type Op = { seq: number; actor: Actor; cause: string; patch: PatchOp[]; inverse: PatchOp[] };

export type IntentKind = "move" | "resize" | "link" | "pin" | "style" | "input";

export type Intent = { id: string; kind: IntentKind; targetId: string; payload: Record<string, unknown> };

export type ClientMsg =
  | { t: "hello"; boardId: string; clientId: string }
  // baseSeq: the seq the user saw; under "agent wins" the server rejects a move older than the agent's last write.
  | ({ t: "intent"; baseSeq?: number } & Intent)
  | { t: "undo" };

export type IntentMsg = Extract<ClientMsg, { t: "intent" }>;

export type ServerMsg =
  | { t: "snapshot"; seq: number; spec: BoardSpec }
  | { t: "ops"; ops: Op[] }
  | { t: "ack"; id: string; seq: number }
  | { t: "error"; id: string; msg: string }
  // Sent only to sockets opened with ?role=agent.
  | ({ t: "intent" } & Intent);

export type AgentTool = "emit_view" | "set_style" | "link" | "pin" | "reset";

export type AgentCall = { tool: AgentTool; args: Record<string, unknown> };

export type AgentReply = { seq: number };

/** AG-UI-shaped payload of `emit_view`: a whole board or a JSON Patch against it. */
export type ViewEvent =
  | { type: "STATE_SNAPSHOT"; snapshot: BoardSpec }
  | { type: "STATE_DELTA"; delta: PatchOp[] };
