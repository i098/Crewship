import { expect, mock, test } from "bun:test";
import type { BoardSpec, Component, PatchOp } from "@crewship/genui-spec";

// the feeder reads GENUI_FM_MAIN when it loads, so it is set before a dynamic import; a static import would load first
process.env.GENUI_FM_MAIN ??= "/nonexistent-fleet-home";
// the model is an external boundary: a chat here must never call it
const real = await import("../fleet/chat");
mock.module("../fleet/chat", () => ({ ...real, chat: async () => {} }));
const { diff, extra, onIntent } = await import("../feeder/feeder");

const ask = (n: number, text: string, about?: unknown) =>
  onIntent({ id: `i${n}`, kind: "input", targetId: "input", payload: { text, ...(about ? { about } : {}) } });
const deckOpen = () => {
  const empty: BoardSpec = { components: {}, links: [], tokens: {} };
  const projects = diff(empty, {}, new Set()).find((p): p is Extract<PatchOp, { op: "add" }> => p.op === "add" && p.path === "/projects");
  return Object.hasOwn((projects?.value ?? {}) as object, "all");
};

test("a question about a deck card keeps the deck open; an ask about something else puts the decisions back", async () => {
  await ask(1, "show it to me one by one");
  expect(deckOpen()).toBe(true);
  extra.d1 = { type: "card", props: { kind: "ask", proj: "all", key: "k1", task: "t1", q: "Ship it?" } } as Component;
  await ask(2, "what does this one mean?", { ids: ["d1"] });
  expect(deckOpen()).toBe(true);
  await ask(3, "what failed on the build?");
  expect(deckOpen()).toBe(false);
});
