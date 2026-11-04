import { afterEach, expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createDelegator, type DelegateHost, type DelegateTarget } from "./desk-delegate.ts";

const mate1 = { id: "mate1", home: "/fleet/mate1", scope: "repo checks" };
const dirs: string[] = [];
afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true }); });

function rig(over: Partial<DelegateHost<string>> = {}) {
  const dir = mkdtempSync(join(process.env.TMPDIR ?? "/tmp", "desk-delegate-"));
  dirs.push(dir);
  const sent: { target: DelegateTarget; text: string }[] = [];
  const reports: { parts: string[]; origin: string }[] = [];
  const errors: unknown[] = [];
  const host: DelegateHost<string> = {
    answerDir: join(dir, "tasks"), waitMs: 3000, pollMs: 10, stopping: () => false, muted: () => false,
    safe: (text) => text.replaceAll("hunter2", "[REDACTED]"), listed: () => true,
    send: async (target, _id, text) => { sent.push({ target, text }); return true; },
    report: (parts, _id, origin) => void reports.push({ parts, origin }), log: (error) => void errors.push(error), ...over,
  };
  const answerPath = () => /to (\S+\.answer)$/.exec(sent.at(-1)!.text)![1];
  return { delegate: createDelegator(host), sent, reports, errors, answerPath };
}
const until = async (check: () => boolean) => { for (let i = 0; i < 300 && !check(); i++) await Bun.sleep(10); expect(check()).toBe(true); };

test("the delegator returns before the send finishes, and the answer is reported only after it", async () => {
  const gate = Promise.withResolvers<void>();
  const r = rig({ send: async (target, _id, text) => { await gate.promise; r.sent.push({ target, text }); return true; } });
  r.delegate(mate1, "check the repo", "chat-1");
  expect(r.sent).toEqual([]);
  gate.resolve();
  await until(() => r.sent.length === 1);
  expect(r.reports).toEqual([]);
  writeFileSync(r.answerPath(), "All green.\n\nNo failures.");
  await until(() => r.reports.length === 1);
  expect(r.reports).toEqual([{ parts: ["All green.", "No failures."], origin: "chat-1" }]);
  expect(existsSync(r.answerPath())).toBe(false);
});

test("the task carries the owner's text and the answer path to the target", async () => {
  const r = rig();
  r.delegate("firstmate", "check the repo", "chat-1");
  await until(() => r.sent.length === 1);
  expect(r.sent[0].target).toBe("firstmate");
  expect(r.sent[0].text.startsWith("check the repo\n")).toBe(true);
  expect(r.answerPath()).toMatch(/\/tasks\/[0-9a-f-]{36}\.answer$/);
});

test("an answer the checked reply path refuses is not reported", async () => {
  const r = rig();
  r.delegate(mate1, "check the repo", "chat-1");
  await until(() => r.sent.length === 1);
  writeFileSync(r.answerPath(), "The password is hunter2.");
  await until(() => r.errors.length === 1);
  expect(String(r.errors[0])).toContain("protected content");
  expect(r.reports).toEqual([]);
});

test("a muted desk drops the answer", async () => {
  let muted = false;
  const r = rig({ muted: () => muted });
  r.delegate(mate1, "check the repo", "chat-1");
  await until(() => r.sent.length === 1);
  muted = true;
  writeFileSync(r.answerPath(), "All green.");
  await until(() => !existsSync(r.answerPath()));
  await Bun.sleep(50);
  expect(r.reports).toEqual([]);
});

test("a mate that left the routing table, or that fails the send, gets no task and nothing goes to Firstmate", async () => {
  const gone = rig({ listed: () => false });
  gone.delegate(mate1, "check the repo", "chat-1");
  await until(() => gone.errors.length === 1);
  const failing = rig({ send: async (target, _id, text) => { failing.sent.push({ target, text }); return false; } });
  failing.delegate(mate1, "check the repo", "chat-1");
  await until(() => failing.errors.length === 1);
  await Bun.sleep(50);
  expect(gone.sent).toEqual([]);
  expect(failing.sent.map((entry) => entry.target)).toEqual([mate1]);
  expect(String(failing.errors[0])).toContain("mate1 was not delivered");
});

test("a task nobody could receive is logged and never waits", async () => {
  const r = rig({ send: async () => false });
  r.delegate("firstmate", "check the repo", "chat-1");
  await until(() => r.errors.length === 1);
  expect(String(r.errors[0])).toContain("was not delivered");
});
