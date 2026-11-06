import { expect, test } from "bun:test";
import { createServer } from "node:http";
import { STE_STYLE } from "./ste.ts";
import { deskPrompt, voicePrompt } from "./desk.ts";
import { sessionPrompt, turnMessage } from "./desk-actions.ts";
import { helperPrompt } from "./desk-helper.ts";
import { COMPACT_PROMPT } from "./memory.ts";
import { answerStatus } from "./front.ts";

const OLD_STYLE = [/gen z/i, /blunt/i, /slang as/i, /like a text message/i, /act like a person texting/i];
const expectSte = (prompt: string) => {
  expect(prompt).toContain(STE_STYLE);
  for (const old of OLD_STYLE) expect(prompt).not.toMatch(old);
};

test("every emitted desk prompt carries the STE style and no old style cue", () => {
  expectSte(sessionPrompt("Sam", "m", "s"));
  expectSte(turnMessage({ missed: [], burst: ["hi"] }));
  expectSte(deskPrompt("Sam", "m", "s"));
  expectSte(deskPrompt("Sam", "m", "s", "Instagram"));
  expectSte(helperPrompt("Sam"));
  expectSte(voicePrompt("What is the build status?"));
  expectSte(COMPACT_PROMPT);
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
  expectSte(system);
});
