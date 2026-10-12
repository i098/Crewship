// The front desk's one tool, an omp extension (`omp -p -e zoom.ts`): zoom(id, n) opens a line of its memory view.
// It reads the memory directory that FM_DESK_MEMORY names; bridge.ts is the only writer. FM_DESK_SPENT is the
// bytes the call's prompt already holds; results past the ceiling are refused (memory.ts Budget).
import { Budget, load, zoom } from "./memory.ts";

// The slice of omp's ExtensionAPI this file uses.
type Zod = { object(shape: Record<string, unknown>): unknown; number(): { describe(text: string): unknown } };
export default function (pi: { zod: Zod; registerTool(tool: unknown): void }) {
  const z = pi.zod;
  // A missing FM_DESK_SPENT counts as a full call: the first zoom ends it.
  const budget = new Budget(Number(process.env.FM_DESK_SPENT || Infinity));
  pi.registerTool({
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
