import { expect, test } from "bun:test";
import { gate } from "./standby.ts";

test("polls during a failing desk check share one run and make one desk call", async () => {
  let desk = 0;
  const ready = gate({ desk: async () => { desk++; await Bun.sleep(30); throw new Error("no stub reply"); } });
  const results = await Promise.all([ready(), ready(), ready()]);
  expect(results.map((r) => r.ok)).toEqual([false, false, false]);
  expect((await ready()).failed.desk).toBe("no stub reply");
  expect(desk).toBe(1);
});

test("a failure is retried once its cache time is over, and a pass is kept", async () => {
  let desk = 0;
  const ready = gate({ desk: async () => { if (++desk === 1) throw new Error("slow model"); } }, 20);
  expect((await ready()).ok).toBe(false);
  await Bun.sleep(40);
  expect((await ready()).ok).toBe(true);
  await Bun.sleep(40);
  expect((await ready()).ok).toBe(true);
  expect(desk).toBe(2);
});

test("a build whose natives fail makes no desk call", async () => {
  let desk = 0;
  const ready = gate({ natives: async () => { throw new Error("natives do not load"); }, desk: async () => { desk++; } });
  const result = await ready();
  expect(result.failed).toEqual({ natives: "natives do not load", desk: "skipped: natives failed" });
  expect(desk).toBe(0);
});
