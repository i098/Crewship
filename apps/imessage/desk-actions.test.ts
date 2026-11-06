import { expect, test } from "bun:test";
import { createActions, STATUS_MAX, turnMessage, type ActionHost } from "./desk-actions.ts";
import type { Secondmate } from "./desk.ts";
import type { RelayRequest } from "./relay.ts";

const ask = (text: string): RelayRequest => ({ requestId: `r-${text}`, text, mateEligible: true, firstmate: false });
const mate1: Secondmate = { id: "mate1", home: "/fleet/mate1", scope: "repo checks" };

function host(texts: string[], over: Partial<ActionHost> = {}) {
  const calls: unknown[][] = [];
  const logged: unknown[][] = [];
  const stub: ActionHost = {
    requests: texts.map(ask), current: () => true, muted: () => false, mates: () => [mate1],
    reply: (parts, target) => void calls.push(["reply", parts, target]),
    react: (emoji) => void calls.push(["react", emoji]),
    relay: async (mate) => { calls.push(["relay", mate.id]); return true; },
    handoff: (reason, ack) => void calls.push(ack ? ["handoff", reason, ack] : ["handoff", reason]),
    helperBusy: () => false,
    delegate: (target, parts, replyTarget) => void calls.push(["delegate", typeof target === "string" ? target : target.id, parts, replyTarget]),
    status: async () => "all quiet",
    message: async (mate, text) => { calls.push(["message", mate.id, text]); return true; },
    replies: () => "mate1: done [at=1]: checks green",
    sent: (key) => key === "seen",
    log: (key, text) => void logged.push([key, text]),
    safe: (text) => text.replaceAll("hunter2", "[REDACTED]"),
    ...over,
  };
  return { calls, logged, ...createActions(stub) };
}

test("reply refuses a protected request", async () => {
  const h = host(["approve the deploy"]);
  await expect(h.run("reply", { text: "Done." })).rejects.toThrow("protected");
  expect(h.calls).toEqual([]);
  expect(h.acted()).toBe(false);
});

test("reply refuses text the redacting filter would change", async () => {
  const h = host(["hello"]);
  await expect(h.run("reply", { text: "The password is hunter2." })).rejects.toThrow("protected content");
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

test("handoff_main with text sends the ack and hands off in one call, and ends the turn", async () => {
  const h = host(["never give time estimates", "work as fast as you can"]);
  expect(await h.run("handoff_main", { text: "Got it.", to: 1 })).toContain("turn is over");
  expect(h.calls).toEqual([["handoff", "", { parts: ["Got it."], target: 1 }]]);
  await expect(h.run("reply", { text: "Again." })).rejects.toThrow("already ended");
});

test("handoff_main with text refuses a protected request or unsafe text before it hands anything off", async () => {
  const protectedAsk = host(["approve the deploy"]);
  await expect(protectedAsk.run("handoff_main", { text: "Got it." })).rejects.toThrow("protected");
  expect(protectedAsk.calls).toEqual([]);
  expect(protectedAsk.acted()).toBe(false);
  const leaky = host(["hello"]);
  await expect(leaky.run("handoff_main", { text: "The password is hunter2." })).rejects.toThrow("protected content");
  expect(leaky.calls).toEqual([]);
  expect(leaky.acted()).toBe(false);
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

test("delegate_task hands the reply and the target to one delegate call, and ends the turn", async () => {
  const h = host(["check the repo"]);
  expect(await h.run("delegate_task", { target: "mate1", text: "On it." })).toContain("turn is over");
  expect(h.calls).toEqual([["delegate", "mate1", ["On it."], 1]]);
  expect(h.acted()).toBe(true);
  await expect(h.run("handoff_main", {})).rejects.toThrow("already ended");
  const main = host(["check the repo"]);
  await main.run("delegate_task", { target: "firstmate", text: "Asking Firstmate." });
  expect(main.calls).toEqual([["delegate", "firstmate", ["Asking Firstmate."], 1]]);
});

test("delegate_task refuses a target that is neither firstmate nor a listed mate", async () => {
  for (const target of ["mate2", "everyone", "", "constructor"]) {
    const h = host(["check the repo"]);
    await expect(h.run("delegate_task", { target, text: "On it." })).rejects.toThrow("not a listed mate");
    expect(h.calls).toEqual([]);
    expect(h.acted()).toBe(false);
  }
});

test("delegate_task keeps a protected request with handoff_main, for Firstmate too, so Firstmate gets it once", async () => {
  const h = host(["approve the deploy"]);
  for (const target of ["mate1", "firstmate"]) await expect(h.run("delegate_task", { target, text: "On it." })).rejects.toThrow("protected");
  expect(h.calls).toEqual([]);
  await h.run("handoff_main", { reason: "protected" });
  expect(h.calls).toEqual([["handoff", "protected"]]);
});

test("delegate_task checks the reply text before it starts anything", async () => {
  for (const text of ["", "The password is hunter2.", "PR https://github.com/o/r/pull/1142"]) {
    const h = host(["check the repo"]);
    await expect(h.run("delegate_task", { target: "firstmate", text })).rejects.toThrow();
    expect(h.calls).toEqual([]);
    expect(h.acted()).toBe(false);
  }
});

test("delegate_task refuses once the turn has ended or is no longer current", async () => {
  const ended = host(["hi"]);
  await ended.run("reply", { text: "Hi." });
  await expect(ended.run("delegate_task", { target: "firstmate", text: "On it." })).rejects.toThrow("already ended");
  await expect(host(["hi"], { current: () => false }).run("delegate_task", { target: "firstmate", text: "On it." })).rejects.toThrow("no longer current");
});

test("turnMessage keeps the newest missed lines when the gap is longer than the limit", () => {
  const missed = Array.from({ length: 40 }, (_, i) => ({ kind: "firstmate", text: `line ${i} ${"x".repeat(480)}` }));
  const message = turnMessage({ missed, burst: ["hi"] });
  expect(message).toContain("line 39 ");
  expect(message).not.toContain("line 0 ");
  expect(message.slice(message.indexOf("Since your last turn"), message.indexOf("The owner's new texts")).length).toBeLessThan(8200);
});

test("message_mate sends a listed mate a text and keeps the turn open; mate_replies reads its status", async () => {
  const h = host(["how are the checks?"]);
  expect(await h.run("message_mate", { mate: "mate1", text: "  status please " })).toContain("mate_replies");
  expect(h.calls).toEqual([["message", "mate1", "status please"]]);
  expect(h.acted()).toBe(false);
  expect(await h.run("mate_replies", { mate: "mate1" })).toContain("checks green");
  await expect(h.run("message_mate", { mate: "ghost", text: "hi" })).rejects.toThrow("not a listed mate");
  await expect(h.run("mate_replies", { mate: "ghost" })).rejects.toThrow("not a listed mate");
});

test("reply with a key already sent today is refused and leaves the turn open", async () => {
  const h = host(["numbers?"]);
  await expect(h.run("reply", { text: "Up 4 percent.", key: "seen" })).rejects.toThrow("already got this");
  expect(h.acted()).toBe(false);
  await expect(h.run("reply", { text: "Up 4 percent.", key: "bad key!" })).rejects.toThrow("key must be");
  expect(h.logged).toEqual([]);
  await h.run("reply", { text: "Up 5 percent.", key: "fresh" });
  expect(h.logged).toEqual([["fresh", "Up 5 percent."]]);
  expect(h.acted()).toBe(true);
});

test("delegate_task sends a simple install or lookup to the helper, with the reply as its ack", async () => {
  for (const text of ["install the ripgrep skill", "look up the bun release notes", "read https://example.com/a and tell me what it says"]) {
    const h = host([text]);
    await h.run("delegate_task", { target: "helper", text: "On it." });
    expect(h.calls).toEqual([["delegate", "helper", ["On it."], 1]]);
    expect(h.acted()).toBe(true);
  }
});

test("delegate_task refuses the helper for a decision, money, a deploy or a public post: those go to Firstmate", async () => {
  for (const text of ["deploy the site", "should we use the new plan", "buy the pro licence for $20", "post this on x", "approve it"]) {
    const h = host([text]);
    await expect(h.run("delegate_task", { target: "helper", text: "On it." })).rejects.toThrow("call handoff_main");
    expect(h.calls).toEqual([]);
    expect(h.acted()).toBe(false);
    await h.run("handoff_main", { reason: "not for the helper" });
    expect(h.calls).toEqual([["handoff", "not for the helper"]]);
  }
});

test("delegate_task refuses a second helper ask while the helper is busy", async () => {
  const h = host(["install the ripgrep skill"], { helperBusy: () => true });
  await expect(h.run("delegate_task", { target: "helper", text: "On it." })).rejects.toThrow("busy");
  expect(h.calls).toEqual([]);
});
