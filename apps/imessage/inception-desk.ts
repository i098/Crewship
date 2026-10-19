// The front desk's call on Inception's OpenAI-compatible chat-completions API, run like `omp -p`: argv is the model,
// the reasoning effort and the system prompt, stdin the prompt, stdout the answer, and exit 0 only with an answer.
// spawnDesk (desk.ts) starts it, so the 45-second timeout, the kill on a new text and the stop stay the same.
// Its one tool is zoom, as in zoom.ts. stderr gets one safe line per request: never the key, the prompt or a body.
// No request body passes INCEPTION_MAX serialized bytes; zoom results stop with LIMIT_REACHED before one could.
import { INCEPTION_MAX } from "./desk.ts";
import { CALL_OVERHEAD, clip, LIMIT_REACHED, load, ZOOM_MAX, zoom } from "./memory.ts";

const [model, reasoning, system] = process.argv.slice(2);
const url = process.env.FM_DESK_INCEPTION_URL || "https://api.inceptionlabs.ai/v1/chat/completions";
const key = process.env.INCEPTION_API_KEY;
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

function zoomText(call: Call): string {
  let args: { id?: unknown; n?: unknown } = {};
  try { args = JSON.parse(call.function.arguments); } catch { /* zoom() answers bad arguments itself */ }
  const { msgs, nodes } = load(process.env.FM_DESK_MEMORY ?? "");
  const text = call.function.name === "zoom" ? zoom(msgs, nodes, Number(args.id), Number(args.n)) : `no tool ${call.function.name}`;
  return clip(text, ZOOM_MAX);
}

if (!key) fail("INCEPTION_API_KEY is not set");
const messages: unknown[] = [{ role: "system", content: system }, { role: "user", content: await Bun.stdin.text() }];
const body = () => JSON.stringify({ model, reasoning_effort: reasoning, messages, tools });
// The bytes one tool message adds to the next body: the serialized message and its comma.
const toolBytes = (id: string, content: string) => Buffer.byteLength(JSON.stringify({ role: "tool", tool_call_id: id, content })) + 1;

// Each call's tool message. A zoom result is taken only while a LIMIT_REACHED for every later call, and one more
// zoom turn (its call's CALL_OVERHEAD and its LIMIT_REACHED), still fit under INCEPTION_MAX. Else the call gets
// LIMIT_REACHED; when even that cannot fit, the desk call ends and the burst goes to Firstmate.
function answerCalls(calls: Call[]) {
  let spent = Buffer.byteLength(body());
  const nextTurn = CALL_OVERHEAD + toolBytes(calls[0].id, LIMIT_REACHED);
  calls.forEach((call, k) => {
    const later = calls.slice(k + 1).reduce((sum, c) => sum + toolBytes(c.id, LIMIT_REACHED), 0);
    let content = zoomText(call);
    if (spent + toolBytes(call.id, content) + later + nextTurn > INCEPTION_MAX) content = LIMIT_REACHED;
    if (spent + toolBytes(call.id, content) + later > INCEPTION_MAX) fail(`request would pass ${INCEPTION_MAX} bytes`);
    spent += toolBytes(call.id, content);
    messages.push({ role: "tool", tool_call_id: call.id, content });
  });
}

for (;;) {
  const sent = body();
  const size = Buffer.byteLength(sent);
  if (size > INCEPTION_MAX) fail(`request of ${size} bytes passes ${INCEPTION_MAX} bytes`);
  const started = performance.now();
  const response = await fetch(url, { method: "POST", headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" }, body: sent })
    .catch((e: unknown) => fail(`request failed: ${e instanceof Error ? e.name : "error"}`));
  console.error(`${tag} HTTP ${response.status} ${Math.round(performance.now() - started)}ms ${size} bytes`);
  if (!response.ok) fail("refused");
  const reply: Reply | undefined = (await response.json().catch(() => undefined))?.choices?.[0]?.message;
  if (!reply) fail("no message in the response");
  if (!reply.tool_calls?.length) {
    await Bun.write(Bun.stdout, reply.content ?? "");
    process.exit(reply.content?.trim() ? 0 : 1);
  }
  // Only the fields the next request needs, so extra response fields never grow it.
  messages.push({ role: "assistant", content: reply.content ?? null, tool_calls: reply.tool_calls });
  answerCalls(reply.tool_calls);
}
