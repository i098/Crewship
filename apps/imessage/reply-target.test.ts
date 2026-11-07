import { expect, test } from "bun:test";
import { pickTarget } from "./reply-target";

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
