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
