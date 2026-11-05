import { afterAll, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { claimSend } from "./sender-log.ts";

const dir = mkdtempSync(`${tmpdir()}/sender-log-`);
afterAll(() => rmSync(dir, { recursive: true, force: true }));
const noon = new Date(2026, 10, 5, 12).getTime();
const day = 86_400_000;

test("the same key and content twice in one day sends once, even as a (repost)", () => {
  expect(claimSend(dir, { key: "nums", sender: "mate1", text: "Up 4 percent, 120 visits." }, noon)).toBe(true);
  expect(claimSend(dir, { key: "nums", sender: "main", text: "Up 4 percent, 120 visits." }, noon + 1000)).toBe(false);
  expect(claimSend(dir, { key: "nums", sender: "mate1", text: "(repost) Up 4  percent, 120 visits." }, noon + 2000)).toBe(false);
});

test("different content on the same key, another key, or the next day goes out", () => {
  expect(claimSend(dir, { key: "nums", text: "Up 5 percent, 130 visits." }, noon + 3000)).toBe(true);
  expect(claimSend(dir, { key: "other", text: "Up 4 percent, 120 visits." }, noon + 3000)).toBe(true);
  expect(claimSend(dir, { key: "nums", text: "Up 4 percent, 120 visits." }, noon + day)).toBe(true);
});

test("an unkeyed text always goes out and is logged", () => {
  expect(claimSend(dir, { text: "ok" }, noon)).toBe(true);
  expect(claimSend(dir, { text: "ok" }, noon)).toBe(true);
});
