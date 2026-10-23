// The desk memory tool, an omp extension: zoom(id, n) opens a line of its memory view.
// It reads the memory directory that FM_DESK_MEMORY names; bridge.ts is the only writer. FM_DESK_SPENT is the
// bytes the call's prompt already holds; results past the ceiling are refused (memory.ts Budget).
import { Budget, load, zoom } from "./memory.ts";
import { canonicalWritePath } from "./desk.ts";

// The slice of omp's ExtensionAPI this file uses.
type Zod = { object(shape: Record<string, unknown>): unknown; number(): { describe(text: string): unknown } };
export default function (pi: {
  zod: Zod;
  registerTool(tool: unknown): void;
  on(event: "before_provider_request", handler: (event: { payload: Record<string, unknown> }) => unknown): void;
  on(event: "tool_call", handler: (event: { toolName: string; input: Record<string, unknown> }) => unknown): void;
}) {
  const z = pi.zod;
  if (process.env.FM_DESK_INCEPTION_INSTANT === "1") {
    pi.on("before_provider_request", ({ payload }) => ({ ...payload, reasoning_effort: "instant" }));
  }
  pi.on("tool_call", guardServerTools);
  // A missing FM_DESK_SPENT counts as a full call: the first zoom ends it.
  const budget = new Budget(Number(process.env.FM_DESK_SPENT || Infinity));
  pi.registerTool({
    approval: "read",
    name: "zoom",
    label: "Zoom",
    description: "Open the line id+n of the <chat> view into the two lines of n/2 under it; n = 1 gives the message whole, with its date.",
    parameters: z.object({ id: z.number().describe("the line's first message"), n: z.number().describe("how many messages the line covers") }),
    async execute(_call: string, p: { id: number; n: number }) {
      const { msgs, nodes } = load(process.env.FM_DESK_MEMORY ?? "");
      const text = budget.take(zoom(msgs, nodes, p.id, p.n));
      // Even the refusal would pass the ceiling: end the call before its next request. The desk stays quiet.
      if (text === undefined) process.exit(1);
      return { content: [{ type: "text", text }] };
    },
  });
}

const LOCAL_SCHEMES: Record<string, true> = { file: true, artifact: true, local: true, proc: true };

function guardServerTools({ toolName, input }: { toolName: string; input: Record<string, unknown> }) {
  if (["read", "grep", "glob"].includes(toolName) && typeof input.path === "string") {
    for (const match of input.path.matchAll(/(?:^|;)\s*([a-z][\w+.-]*):\/\//gi)) {
      if (!LOCAL_SCHEMES[match[1].toLowerCase()]) return { block: true, reason: "External reads require owner approval. Hand off this request." };
    }
  }
  if (toolName === "edit") return { block: true, reason: "Use an explicitly authorized file write." };
  if (toolName !== "write") return;
  const allowed = process.env.FM_DESK_WRITE_PATH;
  if (!allowed || typeof input.path !== "string" || canonicalWritePath(input.path) !== allowed
    || typeof input.content !== "string" || !input.content.trim()) {
    return { block: true, reason: "The owner did not authorize this non-empty write to this absolute path. Hand off for approval." };
  }
}
