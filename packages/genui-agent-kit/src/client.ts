import type {
  AgentReply, AgentCall, AgentTool, ClientMsg, Intent, PatchOp, ServerMsg, BoardSpec, ViewEvent,
} from "@crewship/genui-spec";

export type GenuiClientOptions = { url: string; boardId: string; clientId?: string };
export type IntentHandler = (intent: Intent) => void;

export type GenuiClient = {
  emitView(specOrPatch: BoardSpec | PatchOp[]): Promise<AgentReply>;
  setStyle(id: string, tokens: Record<string, string | number>): Promise<AgentReply>;
  link(from: string, to: string): Promise<AgentReply>;
  pin(id: string): Promise<AgentReply>;
  reset(): Promise<AgentReply>;
  /** Subscribe to user intents; returns an unsubscribe function. The socket opens on first subscribe. */
  onIntent(handler: IntentHandler): () => void;
  close(): void;
};

export function createGenuiClient(opts: GenuiClientOptions): GenuiClient {
  const base = opts.url.replace(/\/+$/, "");
  const board = encodeURIComponent(opts.boardId);
  const clientId = opts.clientId ?? `agent-${crypto.randomUUID()}`;
  const handlers = new Set<IntentHandler>();
  let ws: WebSocket | undefined;

  async function call(tool: AgentTool, args: Record<string, unknown>): Promise<AgentReply> {
    const body: AgentCall = { tool, args };
    const res = await fetch(`${base}/agent/${board}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`genui ${tool} failed: ${res.status} ${await res.text()}`);
    return (await res.json()) as AgentReply;
  }

  function connect() {
    // role=agent: the server forwards user intents only to agent sockets.
    const sock = new WebSocket(`${base.replace(/^http/, "ws")}/ws/${board}?role=agent`);
    ws = sock;
    sock.onopen = () => {
      const hello: ClientMsg = { t: "hello", boardId: opts.boardId, clientId };
      sock.send(JSON.stringify(hello));
    };
    sock.onmessage = (ev) => {
      let frame: ServerMsg;
      try {
        frame = JSON.parse(String(ev.data));
      } catch {
        return; // ignore non-JSON frames
      }
      if (frame.t !== "intent") return;
      const { t: _t, ...intent } = frame;
      for (const h of handlers) h(intent);
    };
  }

  return {
    emitView(specOrPatch) {
      const event: ViewEvent = Array.isArray(specOrPatch)
        ? { type: "STATE_DELTA", delta: specOrPatch }
        : { type: "STATE_SNAPSHOT", snapshot: specOrPatch };
      return call("emit_view", { event });
    },
    setStyle: (id, tokens) => call("set_style", { id, tokens }),
    link: (from, to) => call("link", { from, to }),
    pin: (id) => call("pin", { id }),
    reset: () => call("reset", {}),
    onIntent(handler) {
      handlers.add(handler);
      if (!ws) connect();
      return () => void handlers.delete(handler);
    },
    close() {
      ws?.close();
      ws = undefined;
    },
  };
}
