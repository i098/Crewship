import { expect, test } from "bun:test";
import { createActions, STATUS_MAX, turnMessage, type ActionHost } from "./desk-actions.ts";
import type { Secondmate } from "./desk.ts";
import type { RelayRequest } from "./relay.ts";

const ask = (text: string): RelayRequest => ({ requestId: `r-${text}`, text, mateEligible: true, firstmate: false });
const mate1: Secondmate = { id: "mate1", home: "/fleet/mate1", scope: "repo checks" };

function host(texts: string[], over: Partial<ActionHost> = {}) {
  const calls: unknown[][] = [];
  const stub: ActionHost = {
    requests: texts.map(ask), current: () => true, muted: () => false, mates: () => [mate1],
    reply: (parts, target) => void calls.push(["reply", parts, target]),
    react: (emoji) => void calls.push(["react", emoji]),
    relay: async (mate) => { calls.push(["relay", mate.id]); return true; },
    handoff: (reason) => void calls.push(["handoff", reason]),
    status: async () => "all quiet",
    ...over,
  };
  return { calls, ...createActions(stub) };
}

test("reply refuses a protected request", async () => {
  const h = host(["approve the deploy"]);
  await expect(h.run("reply", { text: "Done." })).rejects.toThrow("protected");
  expect(h.calls).toEqual([]);
  expect(h.acted()).toBe(false);
});

test("reply refuses a raw status line", async () => {
  const h = host(["how are you"]);
  await expect(h.run("reply", { text: "PR https://github.com/o/r/pull/1142" })).rejects.toThrow("raw status line");
  expect(h.calls).toEqual([]);
});

test("reply cleans the text, splits bubbles and ends the turn", async () => {
  const h = host(["how are you", "and the build?"]);
  expect(await h.run("reply", { text: "done: it works\n\nAll good." })).toContain("turn is over");
  expect(h.calls).toEqual([["reply", ["it works", "All good."], 2]]);
  expect(h.acted()).toBe(true);
  await expect(h.run("tapback", { emoji: "👍" })).rejects.toThrow("already ended");
  await expect(h.run("reply", { text: "again" })).rejects.toThrow("already ended");
  expect(h.calls.length).toBe(1);
});

test("reply refuses when the turn is no longer current or the desk is muted", async () => {
  await expect(host(["hi"], { current: () => false }).run("reply", { text: "Hi." })).rejects.toThrow("no longer current");
  await expect(host(["hi"], { muted: () => true }).run("reply", { text: "Hi." })).rejects.toThrow("no longer current");
});

test("tapback takes only a listed emoji and never answers a question", async () => {
  await expect(host(["thanks"]).run("tapback", { emoji: "🔥" })).rejects.toThrow("emoji must be one of");
  await expect(host(["is it done?"]).run("tapback", { emoji: "❤️" })).rejects.toThrow("question");
  const h = host(["thanks"]);
  await h.run("tapback", { emoji: "❤️" });
  expect(h.calls).toEqual([["react", "❤️"]]);
});

test("relay_mate gives the text only to a listed mate of a desk-safe request", async () => {
  await expect(host(["check the repo"]).run("relay_mate", { mate: "mate9" })).rejects.toThrow("not a listed mate");
  await expect(host(["approve the deploy"]).run("relay_mate", { mate: "mate1" })).rejects.toThrow("protected");
  const h = host(["check the repo"]);
  expect(await h.run("relay_mate", { mate: "mate1" })).toContain("routed to mate1");
  expect(h.calls).toEqual([["relay", "mate1"]]);
  expect(h.acted()).toBe(true);
  await expect(host(["check the repo"], { relay: async () => false }).run("relay_mate", { mate: "mate1" })).rejects.toThrow("did not complete");
});

test("handoff_main works for a protected request", async () => {
  const h = host(["approve the deploy"]);
  await h.run("handoff_main", { reason: "approval" });
  expect(h.calls).toEqual([["handoff", "approval"]]);
  expect(h.acted()).toBe(true);
});

test("fleet_status refuses a protected request and clips the text", async () => {
  await expect(host(["approve the deploy"]).run("fleet_status", {})).rejects.toThrow("protected");
  const h = host(["what is running"], { status: async () => "x".repeat(STATUS_MAX + 50) });
  expect((await h.run("fleet_status", {})).length).toBe(STATUS_MAX);
  expect(h.acted()).toBe(false);
});

test("turnMessage puts the seed view first, then the missed lines, then the numbered burst", () => {
  const message = turnMessage({ view: "m1+2|hello", missed: [{ kind: "firstmate", text: "Deploy is live." }], burst: ["hi", "how are you"] });
  expect(message.startsWith("<chat>\nm1+2|hello\n</chat>")).toBe(true);
  expect(message.indexOf("Since your last turn")).toBeGreaterThan(message.indexOf("</chat>"));
  expect(message).toContain("firstmate: Deploy is live.");
  expect(message.endsWith("1: hi\n2: how are you")).toBe(true);
  expect(turnMessage({ missed: [], burst: ["hi"] })).not.toContain("<chat>");
  expect(turnMessage({ missed: [], burst: ["hi"] })).not.toContain("Since your last turn");
});
