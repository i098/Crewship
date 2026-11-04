import { afterEach, expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { COMPACT_AT, DeskSession, sessionConfig, type SessionOptions, type ToolRunner } from "./desk-session.ts";

const FAKE = join(import.meta.dir, "../../tests/fake_desk_omp.ts");
const cleanup: (() => void)[] = [];
afterEach(() => { for (const done of cleanup.splice(0)) done(); });

function session(over: Partial<SessionOptions> = {}) {
  const dir = mkdtempSync(join(process.env.TMPDIR ?? "/tmp", "desk-session-"));
  const logPath = join(dir, "fake.jsonl");
  const options: SessionOptions = {
    argv: [process.execPath, FAKE], cwd: dir, sessionDir: join(dir, "sessions"), tools: [], model: "fake/desk-model",
    env: { ...process.env, FAKE_DESK_LOG: logPath }, ...over,
  };
  const desk = new DeskSession(options);
  cleanup.push(() => { desk.close(); rmSync(dir, { recursive: true, force: true }); });
  const lines = () => existsSync(logPath) ? readFileSync(logPath, "utf8").trim().split("\n").map((line) => JSON.parse(line)) : [];
  return { desk, dir, options, lines };
}

const calls: [string, Record<string, unknown>][] = [];
const run: ToolRunner = async (name, args) => { calls.push([name, args]); return name === "fleet_status" ? "all quiet" : "ok"; };
const live = () => new AbortController().signal;

// The fake child is another process: poll its log file, no in-process signal exists.
async function until(check: () => boolean) {
  for (let i = 0; i < 200 && !check(); i++) await Bun.sleep(25);
  expect(check()).toBe(true);
}

test("one ask sends the prompt and the host tool call reaches the runner", async () => {
  calls.length = 0;
  const { desk, lines } = session();
  expect(await desk.ask(() => "hello", live(), run)).toEqual({ status: "completed" });
  expect(calls).toEqual([["reply", { text: "Fake desk reply." }]]);
  expect(lines().filter((line) => line.prompt)).toEqual([{ prompt: "hello" }]);
  calls.length = 0;
  expect((await desk.ask(() => "STATUS", live(), run)).status).toBe("completed");
  expect(calls).toEqual([["fleet_status", {}], ["reply", { text: "all quiet" }]]);
});

test("the seed goes only to a new session directory", async () => {
  const first = session();
  const seeds: boolean[] = [];
  await first.desk.ask((seed) => { seeds.push(seed); return "hi"; }, live(), run);
  await first.desk.ask((seed) => { seeds.push(seed); return "hi"; }, live(), run);
  expect(seeds).toEqual([true, false]);
  first.desk.close();
  mkdirSync(first.options.sessionDir, { recursive: true });
  writeFileSync(join(first.options.sessionDir, "session.jsonl"), "{}\n");
  const again = new DeskSession(first.options);
  cleanup.push(() => again.close());
  await again.ask((seed) => { seeds.push(seed); return "hi"; }, live(), run);
  expect(seeds).toEqual([true, false, false]);
});

test("a crash rejects the ask, a new ask waits out the backoff, then the child restarts", async () => {
  let clock = 1_000_000;
  const { desk, lines } = session({ now: () => clock });
  await expect(desk.ask(() => "CRASH", live(), run)).rejects.toThrow("exited");
  await expect(desk.ask(() => "hi", live(), run)).rejects.toThrow("restarting");
  clock += 1001;
  expect((await desk.ask(() => "hi", live(), run)).status).toBe("completed");
  expect(lines().filter((line) => line.argv).length).toBe(2);
});

test("a compaction makes the next prompt carry the seed again", async () => {
  const { desk } = session();
  const seeds: boolean[] = [];
  for (const text of ["COMPACT", "hi", "hi"]) await desk.ask((seed) => { seeds.push(seed); return text; }, live(), run);
  expect(seeds).toEqual([true, true, false]);
});

test("the session config compacts the model at the fixed trigger", () => {
  expect(JSON.parse(sessionConfig("fake/desk-model"))).toMatchObject({ compaction: { enabled: true, modelThresholds: { "fake/desk-model": `f${COMPACT_AT}` } } });
  expect(sessionConfig("m")).toContain("f80000");
});

test("the usage of each assistant message goes to the token log", async () => {
  const { desk, dir } = session();
  const before = process.env.STATE_DIRECTORY;
  process.env.STATE_DIRECTORY = join(dir, "state");
  try {
    await desk.ask(() => "hi", live(), run);
    const row = JSON.parse(readFileSync(join(dir, "state/tokens.jsonl"), "utf8").trim());
    expect(row).toMatchObject({ kind: "desk-session", model: "fake/desk-model", input_tokens: 90000, output_tokens: 10 });
  } finally {
    if (before === undefined) delete process.env.STATE_DIRECTORY; else process.env.STATE_DIRECTORY = before;
  }
});

test("an abort signal aborts the turn in flight", async () => {
  const { desk, lines } = session();
  const controller = new AbortController();
  const asked = desk.ask(() => "SLOW", controller.signal, run);
  await until(() => lines().some((line) => line.prompt === "SLOW"));
  controller.abort();
  expect(await asked).toEqual({ status: "aborted" });
});

test("a turn that answers in words returns them as text", async () => {
  const { desk } = session();
  expect(await desk.ask(() => "PLAIN", live(), run)).toEqual({ status: "completed", text: "Plain words." });
});
