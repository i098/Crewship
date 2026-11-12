import { expect, test } from "bun:test";
import { whoSent } from "./who-sent.ts";

const desk = [{ key: "ok", sender: "", id: "d1" }, { key: "old", sender: "mate1" }];

test("a reply to the owner's ok is not labelled us when the desk once sent ok under another id", () => {
  expect(whoSent(new Set(["o1"]), desk, "o1", "ok")).toBe("the owner");
  expect(whoSent(new Set(), desk, "o1", "ok")).toBeUndefined();
});

test("a reply to the desk's own bubble is labelled us, by id", () => {
  expect(whoSent(new Set(), desk, "d1", "ok")).toBe("us");
});

test("a bubble saved without an id matches by text and keeps its sender", () => {
  expect(whoSent(new Set(), desk, "x", "old")).toBe("us (sender mate1)");
});
