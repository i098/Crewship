import { expect, test } from "bun:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { sendRecorded } from "./outbox";
import { pickTarget, refusal } from "./reply-target";

const texts = (...ids: string[]) => ids.map((id) => ({ id, space: "chat" }));
const q = (s: string) => new URLSearchParams(s);

test("an id target stays fixed after a newer text arrives; a position target moves", () => {
  const recent = texts("a", "b");
  expect(pickTarget(recent, q("reply-id=a")).target?.id).toBe("a");
  expect(pickTarget(recent, q("reply=2")).target?.id).toBe("a");
  recent.push(...texts("c"));
  expect(pickTarget(recent, q("reply-id=a")).target?.id).toBe("a");
  expect(pickTarget(recent, q("reply=2")).target?.id).toBe("b");
});

test("position N still counts from the newest text and refuses a position past the kept texts", () => {
  expect(pickTarget(texts("a", "b"), q("reply=1")).target?.id).toBe("b");
  expect(pickTarget(texts("a"), q("reply=3")).error).toContain("only 1 text(s) kept");
});

test("an unknown or empty id is refused with a clear error", () => {
  expect(pickTarget(texts("a"), q("reply-id=zzz")).error).toContain("no kept text has the id zzz");
  expect(pickTarget(texts("a"), q("reply-id=")).error).toContain("(empty)");
});

test("both parameters together are refused; neither picks nothing", () => {
  expect(pickTarget(texts("a"), q("reply=1&reply-id=a")).error).toContain("not both");
  expect(pickTarget(texts("a"), q("no-thread=1"))).toEqual({});
});

test("a refused target answers 400 with the real reason, not undefined", async () => {
  const res = refusal(pickTarget(texts("a"), q("reply-id=zzz")))!;
  expect(res.status).toBe(400);
  expect(await res.text()).toBe("nothing queued: no kept text has the id zzz; 1 text(s) kept since the service started\n");
  expect(refusal(pickTarget(texts("a"), q("reply-id=a")))).toBeUndefined();
});

test("a deduped repeat of the same key and text records no reply row", () => {
  const dir = mkdtempSync(`${tmpdir()}/reply-target-`);
  const rows: string[] = [];
  const o = { key: "k", text: "Deploy is green." };
  const go = () => sendRecorded(dir, o, () => rows.push("row"), () => new Response("queued"));
  expect(go().status).toBe(200);
  expect(rows).toEqual(["row"]);
  expect((go().status)).toBe(200);
  expect(rows).toEqual(["row"]);
});
