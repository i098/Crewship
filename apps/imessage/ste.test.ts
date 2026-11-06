import { expect, test } from "bun:test";
import { createServer } from "node:http";
import { STE_STYLE, steGate, steViolations } from "./ste.ts";
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

const lintByDash = async (t: string) => (t.match(/—/g) ?? []).map(() => "dash");

test("a text that passes the check is sent unchanged and never rewritten", async () => {
  let asked = 0;
  expect(await steGate("The build passes.", async () => { asked++; return "x"; }, lintByDash)).toBe("The build passes.");
  expect(asked).toBe(0);
});

test("a failing text is rewritten once, and the rewrite is sent when it is better", async () => {
  let asked = 0;
  const text = await steGate("It works — and it is fast — now.", async () => { asked++; return "It works. It is fast now."; }, lintByDash);
  expect([text, asked]).toEqual(["It works. It is fast now.", 1]);
});

test("the original text is sent when the rewrite fails, is no better, or the check cannot run", async () => {
  const bad = "It works — now.";
  expect(await steGate(bad, async () => undefined, lintByDash)).toBe(bad);
  expect(await steGate(bad, async () => "Still — bad.", lintByDash)).toBe(bad);
  expect(await steGate(bad, async () => "Fine.", async () => undefined)).toBe(bad);
});

test.skipIf(!Bun.which("vale") && !process.env.FM_STE_VALE)("the vale style flags dashes, contractions, semicolons and long sentences", async () => {
  expect(await steViolations("The build passes. Firstmate will send the command.")).toEqual([]);
  expect((await steViolations("On it — I'll pass it; fine."))?.length).toBe(4);
  expect((await steViolations(`${"word ".repeat(26)}end.`))?.length).toBe(1);
});
