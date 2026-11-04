import { afterEach, expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createDelegator, type DelegateHost, type DelegateTarget, FOLLOW_UP } from "./desk-delegate.ts";

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
  const answerPath = (at = -1) => /to (\S+\.answer)$/.exec(sent.at(at)!.text)![1];
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

test("an answer the checked reply path refuses is not reported: the owner gets the follow-up and Firstmate the task", async () => {
  const r = rig();
  r.delegate(mate1, "check the repo", "chat-1");
  await until(() => r.sent.length === 1);
  writeFileSync(r.answerPath(), "The password is hunter2.");
  await until(() => r.reports.length === 1);
  expect(String(r.errors[0])).toContain("protected content");
  expect(r.reports).toEqual([{ parts: [FOLLOW_UP], origin: "chat-1" }]);
  expect(r.sent.map((entry) => entry.target)).toEqual([mate1, "firstmate"]);
  expect(r.sent[1].text).toContain("check the repo\nThe desk stopped waiting for this task (the answer was refused). Answer the owner directly.");
  expect(r.sent[1].text).toContain("The answer the desk refused to send:\nThe password is hunter2.");
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

test("a mate that left the routing table gets no task: Firstmate gets the text and the owner the follow-up", async () => {
  const r = rig({ listed: () => false });
  r.delegate(mate1, "check the repo", "chat-1");
  await until(() => r.reports.length === 1);
  expect(r.sent).toEqual([{ target: "firstmate", text: "check the repo\nThe desk stopped waiting for this task (not delivered). Answer the owner directly." }]);
  expect(r.reports).toEqual([{ parts: [FOLLOW_UP], origin: "chat-1" }]);
  expect(String(r.errors[0])).toContain("mate1 was not delivered");
});

test("a mate send that fails goes to Firstmate and the owner gets the follow-up", async () => {
  const r = rig({ send: async (target, _id, text) => { r.sent.push({ target, text }); return target === "firstmate"; } });
  r.delegate(mate1, "check the repo", "chat-1");
  await until(() => r.reports.length === 1);
  expect(r.sent.map((entry) => entry.target)).toEqual([mate1, "firstmate"]);
  expect(r.reports).toEqual([{ parts: [FOLLOW_UP], origin: "chat-1" }]);
});

test("a task no inbox could take is logged and the owner is not told Firstmate has it", async () => {
  const r = rig({ send: async () => false });
  r.delegate(mate1, "check the repo", "chat-1");
  await until(() => r.errors.length === 2);
  expect(String(r.errors[1])).toContain("reached no inbox");
  expect(r.reports).toEqual([]);
  const first = rig({ send: async () => false });
  first.delegate("firstmate", "check the repo", "chat-1");
  await until(() => first.errors.length === 2);
  expect(first.reports).toEqual([]);
});

test("no answer by the wait limit gives Firstmate a fresh note and the owner the follow-up once, and a late answer is not reported", async () => {
  const r = rig({ waitMs: 60 });
  r.delegate("firstmate", "check the repo", "chat-1");
  await until(() => r.reports.length === 1);
  const taskPath = r.answerPath(0);
  expect(r.reports).toEqual([{ parts: [FOLLOW_UP], origin: "chat-1" }]);
  expect(r.sent.map((entry) => entry.target)).toEqual(["firstmate", "firstmate"]);
  expect(r.sent[1].text).toBe("check the repo\nThe desk stopped waiting for this task (no answer in time). Answer the owner directly.");
  writeFileSync(taskPath, "All green.");
  await Bun.sleep(100);
  expect(r.reports.length).toBe(1);
});

test("a stopping bridge ends the wait with no follow-up", async () => {
  let stopping = false;
  const r = rig({ stopping: () => stopping });
  r.delegate("firstmate", "check the repo", "chat-1");
  await until(() => r.sent.length === 1);
  stopping = true;
  await Bun.sleep(100);
  expect(r.reports).toEqual([]);
});

test("a muted desk gets no follow-up", async () => {
  const r = rig({ waitMs: 60, muted: () => true });
  r.delegate("firstmate", "check the repo", "chat-1");
  await Bun.sleep(200);
  expect(r.reports).toEqual([]);
});

test("an empty answer file is not an answer: the job waits for its content", async () => {
  const r = rig();
  r.delegate(mate1, "check the repo", "chat-1");
  await until(() => r.sent.length === 1);
  writeFileSync(r.answerPath(), "");
  await Bun.sleep(100);
  expect(r.reports).toEqual([]);
  expect(r.errors).toEqual([]);
  writeFileSync(r.answerPath(), "All green.");
  await until(() => r.reports.length === 1);
  expect(r.reports[0].parts).toEqual(["All green."]);
});
