import { expect, test } from "bun:test";
import { describe } from "./desk.ts";

test("a thread reply names the whole parent message as the one being replied to", async () => {
  const parent = `I graded five cards this week. ${"Card details. ".repeat(20)}End of list.`;
  const note = await describe(
    { type: "reply", content: { type: "text", text: "Whats the cost of each card" }, target: { id: "p1", content: { type: "text", text: parent } } } as never,
    "m1", async () => "", async () => ({ text: "", seconds: 0 }),
  );
  expect(note).toContain("Whats the cost of each card");
  expect(note).toContain(`thread reply to the earlier message: "${parent}"`);
});
