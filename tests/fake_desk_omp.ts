// A fake `omp --mode rpc` child for the desk session tests. Each prompt runs one script, chosen by a token
// in the owner's texts: TAPBACK, RELAY <mate>, HANDOFF, STATUS, CRASH, COMPACT (also compacts before a PLAIN answer), DELEGATE <target> (delegate_task with a reply), SLOW, PLAIN (answers in words, then uses reply when reminded), STUBBORN (answers in words even when reminded), ERRORWORDS (words, then the prompt ends in error), ERRORRETRY (words, then the reminder turn ends in error), NARRATE (words, then fleet_status, then an empty final message); else one plain reply.
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

let stubborn = "";
let retryError = false;
let narrate = false;
let said = "";

function say(text: string) {
  said = text;
  send({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text }] } });
}

const reminded = (message: string) => message.includes("without an action tool");
const compacted = { type: "auto_compaction_end", result: {}, aborted: false };

// First match wins; a script may return the prompt's end status.
const scripts: [hit: (texts: string, message: string) => boolean, run: (texts: string) => Promise<string | void>][] = [
  [(t) => t.includes("SLOW"), async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    aborted = resolve;
    await promise;
    return "aborted";
  }],
  [(t) => t.includes("TAPBACK"), () => call("tapback", { emoji: "❤️" })],
  [(_, m) => retryError && reminded(m), async () => "error"],
  [(t) => t.includes("ERRORWORDS") || t.includes("ERRORRETRY"), async (t) => {
    retryError = t.includes("ERRORRETRY");
    say("Earlier words.");
    if (t.includes("ERRORWORDS")) return "error";
  }],
  [(t, m) => t.includes("STUBBORN") || (!!stubborn && reminded(m)), async (t) => {
    if (t.includes("STUBBORN")) stubborn = t.includes("STATUSLINE") ? "working: cf-x on tests" : "Stubborn words."; // a reminder has no owner text
    say(stubborn);
  }],
  [(t, m) => t.includes("PLAIN") && !reminded(m), async (t) => {
    if (t.includes("COMPACT")) send(compacted);
    say("Plain words.");
  }],
  [(t) => t.includes("HANDOFF"), () => call("handoff_main", { reason: "fake handoff" })],
  [(t) => t.includes("Never give time estimates"), () => call("handoff_main", { text: "Got it, passing that to Firstmate." })],
  [(t) => /DELEGATE (\S+)/.test(t), (t) => call("delegate_task", { target: /DELEGATE (\S+)/.exec(t)![1], text: "On it." })],
  [(t) => /RELAY (\S+)/.test(t), (t) => call("relay_mate", { mate: /RELAY (\S+)/.exec(t)![1] })],
  [(t, m) => t.includes("NARRATE") || (narrate && reminded(m)), async () => {
    narrate = true;
    say("Let me check the fleet.");
    await call("fleet_status", {});
    said = "";
  }],
  [(t) => t.includes("STATUS"), async () => { await call("reply", { text: await call("fleet_status", {}) }); }],
  [() => true, async (t) => {
    if (t.includes("COMPACT")) send(compacted);
    await call("reply", { text: "Fake desk reply." });
  }],
];

async function prompt(id: string, message: string) {
  record({ prompt: message });
  said = "";
  send({ type: "response", id, command: "prompt", success: true });
  // Only the owner's texts choose the script, not the chat view that comes before them.
  const texts = message.slice(Math.max(0, message.lastIndexOf("The owner's new texts")));
  if (texts.includes("CRASH")) process.exit(1);
  const [, run] = scripts.find(([hit]) => hit(texts, message))!;
  const status = (await run(texts)) || "completed";
  send({ type: "message_end", message: { role: "assistant", content: said ? [{ type: "text", text: said }] : [], usage: { input: 90000, output: 10 } } });
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
