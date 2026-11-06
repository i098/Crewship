import { expect, test } from "bun:test";
import type { DeskProc } from "./desk.ts";
import { createHelper, helperMayAct } from "./desk-helper.ts";

const proc = (out: string, code = 0) => ({ stdout: new Blob([out]), exited: Promise.resolve(code) }) as unknown as DeskProc;
const answer = (text: string) => `${JSON.stringify({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text }] } })}\n`;

test("the helper is busy while it runs, answers with its last message, and frees itself", async () => {
  const gate = Promise.withResolvers<void>();
  const helper = createHelper(() => ({ stdout: new Blob([answer("Done.")]), exited: gate.promise.then(() => 0) }) as unknown as DeskProc);
  const running = helper.run("install it");
  expect(helper.busy()).toBe(true);
  gate.resolve();
  expect(await running).toBe("Done.");
  expect(helper.busy()).toBe(false);
});

test("a failed run gives no answer and frees the helper", async () => {
  const failed = createHelper(() => proc(answer("half"), 1));
  expect(await failed.run("x")).toBeUndefined();
  expect(failed.busy()).toBe(false);
  const broken = createHelper(() => { throw new Error("no omp"); });
  await expect(broken.run("x")).rejects.toThrow("no omp");
  expect(broken.busy()).toBe(false);
});

test("only a simple ask may go to the helper", () => {
  const ask = (text: string) => [{ requestId: "r", text, mateEligible: true, firstmate: false }];
  expect(helperMayAct(ask("install the ripgrep skill"))).toBe(true);
  expect(helperMayAct(ask("what is the latest bun version?"))).toBe(true);
  for (const text of ["deploy it", "which option should we take", "buy a domain", "pay the invoice", "tweet the launch", "delete the old skill"]) expect(helperMayAct(ask(text))).toBe(false);
});
