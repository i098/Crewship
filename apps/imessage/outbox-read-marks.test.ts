import { expect, test } from "bun:test";
import { ReadMarks, type Receipts, senderOfQuoted, whoSent } from "./outbox.ts";

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

test("routing finds the mate by text when the reply target id matches no bubble", () => {
  expect(senderOfQuoted(desk, "old", "unknown-id")).toBe("mate1");
  expect(senderOfQuoted([{ key: "plan", sender: "mate2", id: "A" }], "plan", "other")).toBe("mate2");
});
