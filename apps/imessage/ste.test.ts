import { expect, test } from "bun:test";
import { createServer } from "node:http";
import { STE_STYLE } from "./ste.ts";
import { deskPrompt } from "./desk.ts";
import { sessionPrompt, turnMessage } from "./desk-actions.ts";
import { helperPrompt } from "./desk-helper.ts";
import { COMPACT_PROMPT } from "./memory.ts";
import { answerStatus } from "./front.ts";

test("the session prompt and every turn message carry the STE style", () => {
  expect(sessionPrompt("Sam", "m", "s")).toContain(STE_STYLE);
  expect(sessionPrompt("Sam", "m", "s")).not.toContain("like a text message");
  expect(turnMessage({ missed: [], burst: ["hi"] })).toContain(STE_STYLE);
});

test("the single-shot desk prompt carries the STE style on both channels", () => {
  expect(deskPrompt("Sam", "m", "s")).toContain(STE_STYLE);
  expect(deskPrompt("Sam", "m", "s", "Instagram")).toContain(STE_STYLE);
});

test("the helper prompt carries the STE style", () => {
  expect(helperPrompt("Sam")).toContain(STE_STYLE);
});

test("the memory compaction prompt requires STE wording", () => {
  expect(COMPACT_PROMPT).toContain("ASD-STE100");
});

test("the status answer prompt carries the STE style", async () => {
  let system = "";
  const server = createServer(async (req, res) => {
    let body = ""; for await (const chunk of req) body += chunk;
    system = JSON.parse(body).messages[0].content;
    res.end(JSON.stringify({ choices: [{ message: { content: '{"answer":"The build passes."}' } }] }));
  }).listen(0);
  const port = (server.address() as { port: number }).port;
  const text = await answerStatus({ original: ["status?"], status: "build passes", apiKey: "k", signal: new AbortController().signal, redact: (p) => p, endpoint: `http://127.0.0.1:${port}/` });
  server.close();
  expect(text).toBe("The build passes.");
  expect(system).toContain(STE_STYLE);
});
