import { afterAll, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { Queue } from "./outbox.ts";

const root = mkdtempSync(`${tmpdir()}/read-receipt-`);
afterAll(() => rmSync(root, { recursive: true, force: true }));
type Ref = { space: string; id: string; line?: string };
const key = (r: Ref) => `${r.line ?? "photon"}-${r.id}`;
const wait = async (ok: () => boolean) => { for (let i = 0; i < 100 && !ok(); i++) await Bun.sleep(10); };

test("a text gets one read receipt, retried after a failure and never repeated", async () => {
  const sent: string[] = [];
  let fail = 1;
  const make = (dir: string) => new Queue<Ref>(dir, "read receipt", async (r) => { if (fail-- > 0) throw new Error("down"); sent.push(r.id); }, 5, undefined, key);
  const q = make(`${root}/a`);
  q.add({ space: "s", id: "m1" });
  await wait(() => sent.length === 1);
  q.add({ space: "s", id: "m1" }); // a duplicate intake
  await Bun.sleep(50);
  expect(sent).toEqual(["m1"]);
});

test("a text queued before a restart is marked read after it", async () => {
  const sent: string[] = [];
  const dir = `${root}/b`;
  new Queue<Ref>(dir, "read receipt", async () => { throw new Error("bridge went down"); }, 60_000, undefined, key).add({ space: "s", id: "m2" });
  new Queue<Ref>(dir, "read receipt", async (r) => { sent.push(r.id); }, 5, undefined, key);
  await wait(() => sent.length === 1);
  expect(sent).toEqual(["m2"]);
});
