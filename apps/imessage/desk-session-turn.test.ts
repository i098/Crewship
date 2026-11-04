import { afterEach, expect, test } from "bun:test";
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { deskCommand } from "./desk.ts";
import { createSessionTurn, type TurnRequest } from "./desk-session-turn.ts";

const FAKE = join(import.meta.dir, "../../tests/fake_desk_omp.ts");
const cleanup: (() => void)[] = [];
afterEach(() => { for (const done of cleanup.splice(0)) done(); });

async function sessionArgv(provider: string, model: string): Promise<string[]> {
  const dir = mkdtempSync(join(process.env.TMPDIR ?? "/tmp", "desk-turn-"));
  cleanup.push(() => rmSync(dir, { recursive: true, force: true }));
  const log = join(dir, "fake.jsonl");
  const wrapper = join(dir, "omp");
  writeFileSync(wrapper, `#!/bin/bash\nFAKE_DESK_LOG=${JSON.stringify(log)} exec ${JSON.stringify(process.execPath)} ${JSON.stringify(FAKE)} "$@"\n`);
  chmodSync(wrapper, 0o755);
  const request: TurnRequest = { requestId: "r1", text: "hi", mateEligible: true, firstmate: false, memoryId: 0, route: "pending" };
  const turn = createSessionTurn<TurnRequest>({
    env: { FM_DESK_SESSION_OMP: wrapper, PATH: process.env.PATH }, provider, model, reasoning: "off", supervisorModel: "", vetted: true,
    stateDir: dir, memoryDir: join(dir, "memory"), fmHome: dir, memory: { msgs: [], render: () => "" } as never,
    memoryIndex: () => 0, safe: (text) => text, muted: () => false, track: (proc) => { cleanup.push(() => proc.kill()); return proc; },
    log: () => () => {}, handoff: () => {}, answer: () => {}, react: () => {}, relay: async () => {}, inbox: async () => ({ status: "", statusOk: true }),
    stopping: () => false, listed: () => true, send: async () => true, report: () => {},
  });
  await turn([request], new AbortController(), () => true);
  const start = readFileSync(log, "utf8").trim().split("\n").map((line) => JSON.parse(line)).find((row) => row.argv);
  return start.argv;
}

const modelOf = (argv: string[]) => argv[argv.indexOf("--model") + 1];

test.each([["omp", "claude-haiku-5-5"], ["inception", "mercury-3"]])("the %s session starts omp with the one-shot desk's --model", async (provider, model) => {
  const oneShot = deskCommand({ provider, model, system: "", prompt: "", spent: 0, memoryDir: "", cwd: "", env: {} }, "off");
  expect(modelOf(await sessionArgv(provider, model))).toBe(modelOf(oneShot));
});

test("a background task's answer reaches the next turn as a missed line, the session's own replies do not", async () => {
  const dir = mkdtempSync(join(process.env.TMPDIR ?? "/tmp", "desk-turn-"));
  cleanup.push(() => rmSync(dir, { recursive: true, force: true }));
  const log = join(dir, "fake.jsonl");
  const wrapper = join(dir, "omp");
  writeFileSync(wrapper, `#!/bin/bash\nFAKE_DESK_LOG=${JSON.stringify(log)} exec ${JSON.stringify(process.execPath)} ${JSON.stringify(FAKE)} "$@"\n`);
  chmodSync(wrapper, 0o755);
  const msgs: { i: number; kind: string; text: string; requestId?: string }[] = [];
  const add = (kind: string, text: string, requestId?: string) => msgs.push({ i: msgs.length, kind, text, requestId });
  const turn = createSessionTurn<TurnRequest>({
    env: { FM_DESK_SESSION_OMP: wrapper, PATH: process.env.PATH }, provider: "omp", model: "claude-haiku-5-5", reasoning: "off", supervisorModel: "", vetted: true,
    stateDir: dir, memoryDir: join(dir, "memory"), fmHome: dir, memory: { msgs, render: () => "" } as never,
    memoryIndex: (r) => r.memoryId, safe: (text) => text, muted: () => false, track: (proc) => { cleanup.push(() => proc.kill()); return proc; },
    log: () => () => {}, handoff: () => {}, answer: () => {}, react: () => {}, relay: async () => {}, inbox: async () => ({ status: "", statusOk: true }), stopping: () => false, listed: () => true, send: async () => true, report: () => {},
  });
  const ask = (text: string, id: string) => {
    add("owner", text, id);
    return turn([{ requestId: id, text, mateEligible: true, firstmate: false, memoryId: msgs.length - 1, route: "pending" }], new AbortController(), () => true);
  };
  await ask("hi", "r1");
  add("desk", "On it.", "outbox-text-0b7f3c1e-0000-4000-8000-000000000001");
  add("desk", "2 tests fail, in a and b", "outbox-text-task-9d2a");
  await ask("what about b?", "r2");
  const prompts = readFileSync(log, "utf8").trim().split("\n").map((line) => JSON.parse(line)).filter((row) => row.prompt).map((row) => row.prompt as string);
  expect(prompts.length).toBe(2);
  expect(prompts[1]).toContain("desk: 2 tests fail, in a and b");
  expect(prompts[1]).not.toContain("On it.");
});
