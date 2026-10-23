// Inception's tool-free voice pass. Classification uses omp's native tool runtime.
import { INCEPTION_MAX } from "./desk.ts";

const [model, reasoning, system, mode] = process.argv.slice(2);
const url = process.env.FM_DESK_INCEPTION_URL || "https://api.inceptionlabs.ai/v1/chat/completions";
const key = process.env.INCEPTION_API_KEY;
const tag = `fm-imessage desk: inception ${model} reasoning=${reasoning}`;
function fail(why: string): never {
  console.error(`${tag} ${why}`);
  process.exit(1);
}

if (mode !== "voice") fail("classification requires the native tool runtime");
if (!key) fail("INCEPTION_API_KEY is not set");
const messages = [{ role: "system", content: system }, { role: "user", content: await Bun.stdin.text() }];
const body = JSON.stringify({ model, reasoning_effort: reasoning, messages });
const size = Buffer.byteLength(body);
if (size > INCEPTION_MAX) fail(`request of ${size} bytes passes ${INCEPTION_MAX} bytes`);
const started = performance.now();
const response = await fetch(url, { method: "POST", headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" }, body })
  .catch((e: unknown) => fail(`request failed: ${e instanceof Error ? e.name : "error"}`));
console.error(`${tag} HTTP ${response.status} ${Math.round(performance.now() - started)}ms ${size} bytes`);
if (!response.ok) fail("refused");
const reply = (await response.json().catch(() => undefined))?.choices?.[0]?.message;
if (!reply) fail("no message in the response");
if (reply.tool_calls?.length) fail("unexpected voice tool call");
await Bun.write(Bun.stdout, reply.content ?? "");
process.exit(reply.content?.trim() ? 0 : 1);
