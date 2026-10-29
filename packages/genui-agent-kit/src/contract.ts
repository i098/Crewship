// Local copy of the stub contract (docs/genui, shared spec). Replace with an import from
// @crewship/genui-spec once P1 lands.

export type Rect = { x: number; y: number; w: number; h: number };

export type Component = {
  type: string;
  props: Record<string, unknown>;
  children?: string[];
  style?: Record<string, string | number>;
  rect?: Rect;
};

export type Spec = {
  components: Record<string, Component>;
  links: { from: string; to: string }[];
  tokens: Record<string, string | number>;
};

/** RFC 6902 operation applied to `spec`. */
export type PatchOp = {
  op: "add" | "remove" | "replace" | "move" | "copy" | "test";
  path: string;
  from?: string;
  value?: unknown;
};

/** AG-UI-shaped event carried by `emit_view`. */
export type ViewEvent =
  | { type: "STATE_SNAPSHOT"; snapshot: Spec }
  | { type: "STATE_DELTA"; delta: PatchOp[] };

export type AgentTool = "emit_view" | "set_style" | "link" | "pin" | "reset";

export type AgentRequest = { tool: AgentTool; args: Record<string, unknown> };
export type AgentReply = { seq: number };

export type IntentKind = "move" | "resize" | "link" | "pin" | "style" | "input";

export type Intent = {
  id: string;
  kind: IntentKind;
  targetId: string;
  payload: unknown;
};

export type ClientFrame =
  | { t: "hello"; boardId: string; clientId: string }
  | ({ t: "intent" } & Intent)
  | { t: "undo" };

export type ServerFrame =
  | { t: "snapshot"; seq: number; spec: Spec }
  | { t: "ops"; ops: { seq: number; actor: "agent" | "user"; cause: string; patch: PatchOp[]; inverse: PatchOp[] }[] }
  | { t: "ack"; id: string; seq: number }
  | ({ t: "intent" } & Intent)
  | { t: "error"; id?: string; msg: string };
