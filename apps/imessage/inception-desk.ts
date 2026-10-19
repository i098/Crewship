// The front desk's call on Inception's OpenAI-compatible chat-completions API, run like `omp -p`: argv is the model,
// the reasoning effort and the system prompt, stdin the prompt, stdout the answer, and exit 0 only with an answer.
// spawnDesk (desk.ts) starts it, so the 45-second timeout, the kill on a new text and the stop stay the same.
// Its one tool is zoom, as in zoom.ts. stderr gets one safe line per request: never the key, the prompt or a body.
import { Budget, load, zoom } from "./memory.ts";

const [model, reasoning, system] = process.argv.slice(2);
const url = process.env.FM_DESK_INCEPTION_URL || "https://api.inceptionlabs.ai/v1/chat/completions";
const key = process.env.INCEPTION_API_KEY;
// A missing FM_DESK_SPENT counts as a full call: the first zoom ends it.
const budget = new Budget(Number(process.env.FM_DESK_SPENT || Infinity));
const tools = [{
  type: "function",
  function: {
    name: "zoom",
    description: "Open the line id+n of the <chat> view into the two lines of n/2 under it; n = 1 gives the message whole, with its date.",
    parameters: {
      type: "object",
      properties: { id: { type: "integer", description: "the line's first message" }, n: { type: "integer", description: "how many messages the line covers" } },
      required: ["id", "n"],
    },
  },
}];
type Call = { id: string; function: { name: string; arguments: string } };
type Reply = { content?: string | null; tool_calls?: Call[] };
const tag = `fm-imessage desk: inception ${model} reasoning=${reasoning}`;
function fail(why: string): never {
  console.error(`${tag} ${why}`);
  process.exit(1);
}

function zoomResult(call: Call): string {
  let args: { id?: unknown; n?: unknown } = {};
  try { args = JSON.parse(call.function.arguments); } catch { /* zoom() answers bad arguments itself */ }
  const { msgs, nodes } = load(process.env.FM_DESK_MEMORY ?? "");
  const text = call.function.name === "zoom" ? zoom(msgs, nodes, Number(args.id), Number(args.n)) : `no tool ${call.function.name}`;
  // Even the refusal would pass the byte ceiling: end the call. The desk stays quiet.
  return budget.take(text) ?? fail("context limit reached");
}

if (!key) fail("INCEPTION_API_KEY is not set");
const messages: unknown[] = [{ role: "system", content: system }, { role: "user", content: await Bun.stdin.text() }];
for (;;) {
  const body = JSON.stringify({ model, reasoning_effort: reasoning, messages, tools });
  const started = performance.now();
  const response = await fetch(url, { method: "POST", headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" }, body })
    .catch((e: unknown) => fail(`request failed: ${e instanceof Error ? e.name : "error"}`));
  console.error(`${tag} HTTP ${response.status} ${Math.round(performance.now() - started)}ms`);
  if (!response.ok) fail("refused");
  const reply: Reply | undefined = (await response.json().catch(() => undefined))?.choices?.[0]?.message;
  if (!reply) fail("no message in the response");
  if (!reply.tool_calls?.length) {
    await Bun.write(Bun.stdout, reply.content ?? "");
    process.exit(reply.content?.trim() ? 0 : 1);
  }
  messages.push(reply);
  for (const call of reply.tool_calls) messages.push({ role: "tool", tool_call_id: call.id, content: zoomResult(call) });
}
