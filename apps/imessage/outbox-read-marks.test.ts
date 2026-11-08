import { expect, test } from "bun:test";
import { ReadMarks, type Receipts } from "./outbox.ts";

function rig() {
  const state = { receipts: {} as Receipts, taken: new Set<string>(), failReads: 0 };
  const read: string[] = [];
  const text = (id: string) => ({ id, read: async () => { if (state.failReads-- > 0) throw new Error("down"); read.push(id); } });
  const marks = new ReadMarks({
    receipts: async () => state.receipts,
    mateTook: (mate, marker) => state.taken.has(`${mate}/${marker}`),
    log: () => () => {}, trace: () => {},
  });
  const handled = (...ids: string[]) => { state.receipts = { handled: ids.map((request_id) => ({ request_id, acknowledged: true })) }; };
  return { state, read, text, marks, handled };
}

test("a text stays unread until its own acknowledged note is handled", async () => {
  const r = rig();
  r.marks.hold("m1", r.text("m1"));
  await r.marks.poll();
  r.handled("other");
  await r.marks.poll();
  r.state.receipts = { handled: [{ request_id: "m1", acknowledged: false }] };
  await r.marks.poll();
  expect(r.read).toEqual([]);
  r.handled("m1");
  await r.marks.poll();
  expect(r.read).toEqual(["m1"]);
});

test("a text answered by a mate is read when the mate takes the delivered message", async () => {
  const r = rig();
  r.marks.hold("m1", r.text("m1"));
  r.marks.delivered("m1", "mate1", ["m1"]);
  await r.marks.poll();
  expect(r.read).toEqual([]);
  r.state.taken.add("mate1/m1");
  await r.marks.poll();
  expect(r.read).toEqual(["m1"]);
});

test("a desk task note marks every text it answers, once Firstmate handles it", async () => {
  const r = rig();
  for (const id of ["m1", "m2", "m3"]) r.marks.hold(id, r.text(id));
  r.marks.noted("desk-task-1", ["m1", "m2"]);
  r.handled("desk-task-1");
  await r.marks.poll();
  expect(r.read).toEqual(["m1", "m2"]);
});

test("a desk task sent to a mate marks its texts when the mate takes the marked message", async () => {
  const r = rig();
  r.marks.hold("m1", r.text("m1"));
  r.marks.delivered("desk-task-1", "mate1", ["m1"]);
  r.state.taken.add("mate1/desk-task-1");
  await r.marks.poll();
  expect(r.read).toEqual(["m1"]);
});

test("a failed read is retried on the next poll", async () => {
  const r = rig();
  r.marks.hold("m1", r.text("m1"));
  r.handled("m1");
  r.state.failReads = 1;
  await r.marks.poll();
  expect(r.read).toEqual([]);
  await r.marks.poll();
  expect(r.read).toEqual(["m1"]);
});
