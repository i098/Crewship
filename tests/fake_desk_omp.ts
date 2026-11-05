// A fake `omp --mode rpc` child for the desk session tests. Each prompt runs one script, chosen by a token
// in the owner's texts: TAPBACK, RELAY <mate>, HANDOFF, STATUS, CRASH, COMPACT, DELEGATE <target> (delegate_task with a reply), SLOW, PLAIN (answers in words, no tool call); else one plain reply.
// $FAKE_DESK_LOG gets one JSON line per start ({argv}) and per prompt ({prompt}).
import { appendFileSync } from "node:fs";

type Frame = { type?: string; id?: string; message?: string; result?: { content?: { text?: string }[] } };

const record = (entry: object) => { if (process.env.FAKE_DESK_LOG) appendFileSync(process.env.FAKE_DESK_LOG, `${JSON.stringify(entry)}\n`); };
const send = (frame: object) => process.stdout.write(`${JSON.stringify(frame)}\n`);
const results = new Map<string, (frame: Frame) => void>();
let aborted: (() => void) | undefined;
let calls = 0;
let turn = Promise.resolve();

async function call(toolName: string, args: Record<string, unknown>): Promise<string> {
  const id = `t${++calls}`;
  const { promise, resolve } = Promise.withResolvers<Frame>();
  results.set(id, resolve);
  send({ type: "host_tool_call", id, toolName, arguments: args });
  return (await promise).result?.content?.[0]?.text ?? "";
}

async function prompt(id: string, message: string) {
  record({ prompt: message });
  send({ type: "response", id, command: "prompt", success: true });
  // Only the owner's texts choose the script, not the chat view that comes before them.
  const texts = message.slice(Math.max(0, message.lastIndexOf("The owner's new texts")));
  let status = "completed";
  if (texts.includes("CRASH")) process.exit(1);
  if (texts.includes("SLOW")) {
    const { promise, resolve } = Promise.withResolvers<void>();
    aborted = resolve;
    await promise;
    status = "aborted";
  } else if (texts.includes("TAPBACK")) await call("tapback", { emoji: "❤️" });
  else if (texts.includes("PLAIN")) send({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: "Plain words." }] } });
  else if (texts.includes("HANDOFF")) await call("handoff_main", { reason: "fake handoff" });
  else if (texts.includes("Never give time estimates")) await call("handoff_main", { text: "Got it, passing that to Firstmate." });
  else if (/DELEGATE (\S+)/.test(texts)) {
    await call("delegate_task", { target: /DELEGATE (\S+)/.exec(texts)![1], text: "On it." });
  } else if (/RELAY (\S+)/.test(texts)) await call("relay_mate", { mate: /RELAY (\S+)/.exec(texts)![1] });
  else if (texts.includes("STATUS")) await call("reply", { text: await call("fleet_status", {}) });
  else {
    if (texts.includes("COMPACT")) send({ type: "auto_compaction_end", result: {}, aborted: false });
    await call("reply", { text: "Fake desk reply." });
  }
  send({ type: "message_end", message: { role: "assistant", usage: { input: 90000, output: 10 } } });
  send({ type: "prompt_result", id, status, sessionSettled: true });
}

record({ argv: process.argv.slice(2), instant: process.env.FM_DESK_INCEPTION_INSTANT });
send({ type: "ready", protocolVersion: 1 });
for await (const line of console) {
  let frame: Frame;
  try { frame = JSON.parse(line); } catch { continue; }
  if (frame.type === "set_host_tools") send({ type: "response", id: frame.id, command: "set_host_tools", success: true, data: { toolNames: [] } });
  else if (frame.type === "host_tool_result" && frame.id) { results.get(frame.id)?.(frame); results.delete(frame.id); }
  else if (frame.type === "abort") { aborted?.(); aborted = undefined; if (frame.id) send({ type: "response", id: frame.id, command: "abort", success: true }); }
  else if (frame.type === "prompt" && frame.id) { const { id, message } = frame; turn = turn.then(() => prompt(id, String(message ?? ""))); }
}
process.exit(0);
