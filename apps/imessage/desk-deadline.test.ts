import { expect, test } from "bun:test";
import { createBurst, TIMEOUT_REPLY, timeOutTurn, typingOutlivesTurn, withDeadline } from "./desk-deadline.ts";

test("a stuck turn times out once and the late result is ignored", async () => {
  let fired = 0;
  const stuck = new Promise<void>((_, reject) => setTimeout(() => reject(new Error("late")), 60));
  expect(await withDeadline(stuck, 10, () => fired++)).toBe(false);
  await Bun.sleep(80);
  expect(fired).toBe(1);
});

test("a turn that ends in time does not time out", async () => {
  let fired = 0;
  expect(await withDeadline(Promise.resolve(), 50, () => fired++)).toBe(true);
  await Bun.sleep(70);
  expect(fired).toBe(0);
});

test("a turn that throws in time rejects to the caller", async () => {
  await expect(withDeadline(Promise.reject(new Error("boom")), 50, () => {})).rejects.toThrow("boom");
});

test("a stuck pending turn aborts, hands off and queues one reply", () => {
  const controller = new AbortController();
  const calls: string[] = [];
  const stuck = timeOutTurn([{ route: "pending" }], controller, () => true, () => calls.push("handoff"), (b) => calls.push(b));
  expect(stuck).toBe(true);
  expect(controller.signal.aborted).toBe(true);
  expect(calls).toEqual(["handoff", TIMEOUT_REPLY]);
});

test("a turn that already routed or went stale queues no reply", () => {
  for (const [route, current] of [["desk", true], ["pending", false]] as const) {
    const controller = new AbortController();
    const calls: string[] = [];
    expect(timeOutTurn([{ route }], controller, () => current, () => calls.push("h"), () => calls.push("r"))).toBe(false);
    expect(controller.signal.aborted).toBe(true);
    expect(calls).toEqual([]);
  }
});

test("typing outlives a turn only for a desk answer awaiting delivery", () => {
  expect(typingOutlivesTurn([{ route: "desk", out: { bubbles: ["hi"] } }])).toBe(true);
  expect(typingOutlivesTurn([{ route: "handoff" }])).toBe(false);
  expect(typingOutlivesTurn([{ route: "desk", out: { bubbles: [] } }])).toBe(false);
});

test("a burst allows one honest line per chat until that chat's next desk reply resets it", () => {
  const burst = createBurst();
  expect([burst.claim("a"), burst.claim("a"), burst.claim("b")]).toEqual([true, false, true]);
  burst.reset("a");
  expect([burst.claim("a"), burst.claim("b")]).toEqual([true, false]);
});
