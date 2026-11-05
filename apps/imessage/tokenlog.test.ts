import { expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { logTokens, tokenDir, usageTokens } from "./tokenlog.ts";

const withDir = (run: (env: Record<string, string>, dir: string) => void) => {
  const dir = mkdtempSync(join(process.env.TMPDIR ?? "/tmp", "tokenlog-"));
  try { run({ STATE_DIRECTORY: dir }, dir); } finally { rmSync(dir, { recursive: true, force: true }); }
};

test("each call appends one row and the day's line holds the running total", () => withDir((env, dir) => {
  logTokens({ kind: "front", model: "mercury-3", input: 100, output: 10 }, env, new Date("2026-11-04T10:00:00Z"));
  logTokens({ kind: "compaction", model: "gpt-6-luna", input: 50, output: 5 }, env, new Date("2026-11-04T11:00:00Z"));
  const rows = readFileSync(`${dir}/tokens.jsonl`, "utf8").trim().split("\n").map((line) => JSON.parse(line));
  expect(rows).toEqual([
    { ts: "2026-11-04T10:00:00.000Z", kind: "front", model: "mercury-3", input_tokens: 100, output_tokens: 10 },
    { ts: "2026-11-04T11:00:00.000Z", kind: "compaction", model: "gpt-6-luna", input_tokens: 50, output_tokens: 5 },
  ]);
  expect(readFileSync(`${dir}/tokens-daily.log`, "utf8")).toBe("2026-11-04 calls=2 input_tokens=150 output_tokens=15\n");
}));

test("a new day gets its own line and leaves the earlier day alone", () => withDir((env, dir) => {
  logTokens({ kind: "desk", model: "m", input: 1, output: 2 }, env, new Date("2026-11-04T23:59:00Z"));
  logTokens({ kind: "desk", model: "m", input: 3, output: 4 }, env, new Date("2026-11-05T00:01:00Z"));
  expect(readFileSync(`${dir}/tokens-daily.log`, "utf8")).toBe(
    "2026-11-04 calls=1 input_tokens=1 output_tokens=2\n2026-11-05 calls=1 input_tokens=3 output_tokens=4\n");
}));

test("a log failure does not throw", () => {
  expect(() => logTokens({ kind: "desk", model: "m", input: 1, output: 1 }, { STATE_DIRECTORY: "/proc/nope/state" })).not.toThrow();
});

test("usage reads both provider shapes and refuses a missing count", () => {
  expect(usageTokens({ prompt_tokens: 7, completion_tokens: 3, total_tokens: 10 })).toEqual({ input: 7, output: 3 });
  expect(usageTokens({ input: 7, output: 3, cacheRead: 0 })).toEqual({ input: 7, output: 3 });
  expect(usageTokens({ prompt_tokens: 7 })).toBeUndefined();
  expect(usageTokens(undefined)).toBeUndefined();
});

test("the state directory follows STATE_DIRECTORY, then HOME", () => {
  expect(tokenDir({ STATE_DIRECTORY: "/s", HOME: "/h" })).toBe("/s");
  expect(tokenDir({ HOME: "/h" })).toBe("/h/.local/state/fm-imessage");
});
