import { afterEach, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { compactReply, mateStatusLines } from "./desk.ts";
import { answerStatus, runFront } from "./front.ts";
import { deskMayAct } from "./relay.ts";

const realFetch = globalThis.fetch;
const dir = mkdtempSync(join(process.env.TMPDIR ?? "/tmp", "status-"));
process.env.STATE_DIRECTORY = dir;
afterEach(() => { globalThis.fetch = realFetch; });
process.on("exit", () => rmSync(dir, { recursive: true, force: true }));

const reply = (content: unknown, usage = { prompt_tokens: 40, completion_tokens: 6 }) =>
  Response.json({ choices: [{ message: { content: JSON.stringify(content) } }], usage });
const front = (original: string[]) => ({
  original, recent: [], mates: [{ id: "web-mate", scope: "the web app" }], models: [], apiKey: "k",
  signal: new AbortController().signal, redact: (text: string) => text,
});
const tokenRows = () => readFileSync(`${dir}/tokens.jsonl`, "utf8").trim().split("\n").map((row) => JSON.parse(row));

test("a status question becomes a status intent and its tokens are logged", async () => {
  globalThis.fetch = (async () => reply({ kind: "status", text: "" })) as unknown as typeof fetch;
  expect(await runFront(front(["what is web-mate doing?"]))).toEqual({ intents: [{ kind: "status" }] });
  expect(tokenRows().at(-1)).toMatchObject({ kind: "front", model: "mercury-3", input_tokens: 40, output_tokens: 6 });
});

test("a clear order to a mate still relays to that mate", async () => {
  globalThis.fetch = (async () => reply({ kind: "relay", target: 1, domains: [1], category: "work", text: "" })) as unknown as typeof fetch;
  expect((await runFront(front(["tell web-mate to fix the footer"]))).intents).toEqual([
    { kind: "relay", target: "web-mate", domains: ["web-mate"], category: "work" }]);
});

test("the desk answers a status question from the status text and logs the call", async () => {
  let sent = "";
  globalThis.fetch = (async (_url: unknown, init?: RequestInit) => { sent = String(init?.body); return reply({ answer: " web-mate is waiting on CI. " }); }) as unknown as typeof fetch;
  const input = { original: ["how is web-mate?"], status: "web-mate: working: waiting on CI", apiKey: "k", signal: new AbortController().signal, redact: (t: string) => t };
  expect(await answerStatus(input)).toBe("web-mate is waiting on CI.");
  expect(sent).toContain("waiting on CI");
  expect(tokenRows().at(-1)).toMatchObject({ kind: "status", input_tokens: 40 });
});

test("an empty, oversize or failed status answer hands off", async () => {
  const input = { original: ["how is web-mate?"], status: "s", apiKey: "k", signal: new AbortController().signal, redact: (t: string) => t };
  globalThis.fetch = (async () => reply({ answer: "" })) as unknown as typeof fetch;
  expect(await answerStatus(input)).toBeUndefined();
  globalThis.fetch = (async () => reply({ answer: "x".repeat(601) })) as unknown as typeof fetch;
  expect(await answerStatus(input)).toBeUndefined();
  globalThis.fetch = (async () => new Response("", { status: 503 })) as unknown as typeof fetch;
  expect(await answerStatus(input)).toBeUndefined();
  expect(await answerStatus({ ...input, apiKey: "" })).toBeUndefined();
});

const request = (text: string, over: object = {}) => ({ requestId: "r", text, firstmate: false, mateEligible: true, ...over });

test("the desk acts only on requests that need no decision", () => {
  expect(deskMayAct([request("how is web-mate doing?")])).toBe(true);
  for (const text of ["should we deploy now?", "approve the merge", "delete the old branch", "use the api key"]) {
    expect(deskMayAct([request(text)])).toBe(false);
  }
  expect(deskMayAct([request("status?", { firstmate: true })])).toBe(false);
  expect(deskMayAct([request("status?", { mutationPath: "/x" })])).toBe(false);
  expect(deskMayAct([])).toBe(false);
});

test("mate status lines take each file's last line and skip missing files", () => {
  mkdirSync(`${dir}/state`, { recursive: true });
  writeFileSync(`${dir}/state/a-mate.status`, "working: start\ndone: shipped\n");
  const mate = (id: string) => ({ id, home: "/h", scope: "s" });
  expect(mateStatusLines(dir, [mate("a-mate"), mate("b-mate")])).toBe("a-mate: done: shipped");
});

test("a compaction reply reads text and usage from the json stream, or takes plain text whole", () => {
  const stream = [
    { type: "message_end", message: { role: "user", content: [{ type: "text", text: "q" }] } },
    { type: "message_end", message: { role: "assistant", model: "gpt-6-luna", content: [{ type: "text", text: "line" }], usage: { input: 9, output: 2 } } },
  ].map((event) => JSON.stringify(event)).join("\n");
  expect(compactReply(stream)).toEqual({ text: "line", model: "gpt-6-luna", input: 9, output: 2 });
  expect(compactReply("plain line")).toEqual({ text: "plain line", model: "gpt-6-luna" });
});

test("a front timeout falls back to Firstmate and says so; other failures do not", async () => {
  globalThis.fetch = (async () => { throw new DOMException("limit", "TimeoutError"); }) as unknown as typeof fetch;
  expect(await runFront(front(["please fix the footer"]))).toMatchObject({ timedOut: true, intents: [{ kind: "relay", target: "firstmate" }] });
  globalThis.fetch = (async () => new Response("", { status: 500 })) as unknown as typeof fetch;
  expect((await runFront(front(["please fix the footer"]))).timedOut).toBeUndefined();
});
