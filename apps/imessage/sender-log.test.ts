import { afterAll, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { sendOnce } from "./outbox.ts";
import { alreadySent, logSend } from "./sender-log.ts";

const dir = mkdtempSync(`${tmpdir()}/sender-log-`);
afterAll(() => rmSync(dir, { recursive: true, force: true }));
const noon = new Date(2026, 10, 5, 12).getTime();
const day = 86_400_000;
const claim = (o: { key?: string; sender?: string; text: string }, now: number) => {
  if (alreadySent(dir, o, now)) return false;
  logSend(dir, o, now);
  return true;
};

test("the same key and content twice in one day sends once, even as a (repost)", () => {
  expect(claim({ key: "nums", sender: "mate1", text: "Up 4 percent, 120 visits." }, noon)).toBe(true);
  expect(claim({ key: "nums", sender: "main", text: "Up 4 percent, 120 visits." }, noon + 1000)).toBe(false);
  expect(claim({ key: "nums", sender: "mate1", text: "(repost) Up 4  percent, 120 visits." }, noon + 2000)).toBe(false);
});

test("different content on the same key, another key, or the next day goes out", () => {
  expect(claim({ key: "nums", text: "Up 5 percent, 130 visits." }, noon + 3000)).toBe(true);
  expect(claim({ key: "other", text: "Up 4 percent, 120 visits." }, noon + 3000)).toBe(true);
  expect(claim({ key: "nums", text: "Up 4 percent, 120 visits." }, noon + day)).toBe(true);
});

test("an unkeyed text always goes out and is logged", () => {
  expect(claim({ text: "ok" }, noon)).toBe(true);
  expect(claim({ text: "ok" }, noon)).toBe(true);
});

test("a failed send is not logged, so the retry goes out", () => {
  const o = { key: "retry", text: "Deploy is green." };
  expect(sendOnce(dir, o, () => new Response("muted", { status: 503 })).status).toBe(503);
  expect(sendOnce(dir, o, () => new Response("queued")).status).toBe(200);
  expect(sendOnce(dir, o, () => new Response("queued"))).toHaveProperty("ok", true);
  let sends = 0;
  sendOnce(dir, o, () => (sends++, new Response("queued")));
  expect(sends).toBe(0);
});

test("a photo caption is deduped under its key; a bare photo always sends", () => {
  const caption = { key: "pic", text: "Chart: 120 visits." };
  expect(sendOnce(dir, caption, () => new Response("queued")).status).toBe(200);
  let sends = 0;
  const res = sendOnce(dir, caption, () => (sends++, new Response("queued")));
  expect(sends).toBe(0);
  expect(res.status).toBe(200);
  const dups: boolean[] = [];
  sendOnce(dir, { ...caption, alone: true }, (dup) => (dups.push(dup), new Response("queued")));
  expect(dups).toEqual([true]);
  expect(sendOnce(dir, { key: "pic", text: "" }, () => (sends++, new Response("queued"))).status).toBe(200);
  expect(sends).toBe(1);
});
