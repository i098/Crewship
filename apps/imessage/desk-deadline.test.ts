import { expect, test } from "bun:test";
import { withDeadline } from "./desk-deadline.ts";

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
