import { expect, test } from "bun:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { sendRecorded, sendReply } from "./outbox";
import { pickTarget, refusal, routeRow, withTarget } from "./reply-target";

const dir = mkdtempSync(`${tmpdir()}/reply-send-`);
const texts = (...ids: string[]) => ids.map((id) => ({ id, space: "chat" }));
const q = (s: string) => new URLSearchParams(s);

test("an id target stays fixed after a newer text arrives; a position target moves", () => {
  const recent = texts("a", "b");
  expect(pickTarget(recent, q("reply-id=a")).target?.id).toBe("a");
  expect(pickTarget(recent, q("reply=2")).target?.id).toBe("a");
  recent.push(...texts("c"));
  expect(pickTarget(recent, q("reply-id=a")).target?.id).toBe("a");
  expect(pickTarget(recent, q("reply=2")).target?.id).toBe("b");
});

test("position N still counts from the newest text and refuses a position past the kept texts", () => {
  expect(pickTarget(texts("a", "b"), q("reply=1")).target?.id).toBe("b");
  expect(pickTarget(texts("a"), q("reply=3")).error).toContain("only 1 text(s) kept");
});

test("an unknown or empty id is refused with a clear error", () => {
  expect(pickTarget(texts("a"), q("reply-id=zzz")).error).toContain("no kept text has the id zzz");
  expect(pickTarget(texts("a"), q("reply-id=")).error).toContain("(empty)");
});

test("both parameters together are refused; neither picks nothing", () => {
  expect(pickTarget(texts("a"), q("reply=1&reply-id=a")).error).toContain("not both");
  expect(pickTarget(texts("a"), q("no-thread=1"))).toEqual({});
});

test("a refused target answers 400 with the real reason, not undefined", async () => {
  const res = refusal(pickTarget(texts("a"), q("reply-id=zzz")))!;
  expect(res.status).toBe(400);
  expect(await res.text()).toBe("nothing queued: no kept text has the id zzz; 1 text(s) kept since the service started\n");
  expect(refusal(pickTarget(texts("a"), q("reply-id=a")))).toBeUndefined();
});

test("a deduped repeat of the same key and text records no reply row", () => {
  const dir = mkdtempSync(`${tmpdir()}/reply-target-`);
  const rows: string[] = [];
  const o = { key: "k", text: "Deploy is green." };
  const go = () => sendRecorded(dir, o, () => rows.push("row"), () => new Response("queued"));
  expect(go().status).toBe(200);
  expect(rows).toEqual(["row"]);
  expect((go().status)).toBe(200);
  expect(rows).toEqual(["row"]);
});

test("reply-id takes the raw message id or the inbox request id <line>-<id>", () => {
  const recent = [{ id: "g1", space: "chat" }, { id: "g2", space: "chat", line: "bluebubbles" }];
  expect(pickTarget(recent, q("reply-id=photon-g1")).target?.id).toBe("g1");
  expect(pickTarget(recent, q("reply-id=bluebubbles-g2")).target?.id).toBe("g2");
  expect(pickTarget(recent, q("reply-id=g2")).target?.id).toBe("g2");
  expect(pickTarget(recent, q("reply-id=photon-g2")).error).toContain("no kept text");
});

const ask = (query: string, over: { muted?: boolean; key?: string } = {}) => {
  const rows: unknown[] = [];
  const queued: string[] = [];
  const send = () => sendReply({ recent: texts("a", "b"), params: q(query), proactive: { id: "p", space: "chat" }, muted: !!over.muted, dir, sender: "main", text: "Deploy is green.", alone: false,
    key: () => over.key, record: (row) => rows.push(row), queue: (target, destination) => (queued.push(`${target?.id}>${destination.id}`), new Response("queued")) });
  return { send, rows, queued };
};

test("/send path: an unknown reply-id answers 400 with the real reason and queues nothing", async () => {
  const t = ask("reply-id=zzz");
  const res = t.send();
  expect(res.status).toBe(400);
  expect(await res.text()).toBe("nothing queued: no kept text has the id zzz; 2 text(s) kept since the service started\n");
  expect(t.queued).toEqual([]);
  expect(t.rows).toEqual([]);
});

test("/send path: a threaded send logs one row; --no-thread or a repeat of the same key logs none", () => {
  const dir1 = ask("reply-id=a", { key: "k1" });
  expect(dir1.send().status).toBe(200);
  expect(dir1.rows).toEqual([{ replyTarget: "a", space: "chat", by: "id" }]);
  expect(dir1.send().status).toBe(200);
  expect(dir1.rows).toHaveLength(1);
  const plain = ask("reply-id=a&no-thread=1", { key: "k2" });
  expect(plain.send().status).toBe(200);
  expect(plain.queued).toEqual(["a>a"]);
  expect(plain.rows).toEqual([]);
  const none = ask("", { key: "k3" });
  expect(none.send().status).toBe(200);
  expect(none.queued).toEqual(["undefined>p"]);
  expect(none.rows).toEqual([]);
});

test("/send path: muted queues nothing", () => {
  const t = ask("reply=1", { muted: true });
  expect(t.send().status).toBe(503);
  expect(t.queued).toEqual([]);
});

test("the routing row names the target, its space and how it was chosen", () => {
  expect(routeRow({ id: "a", space: "chat" }, q("reply-id=a"))).toEqual({ replyTarget: "a", space: "chat", by: "id" });
  expect(routeRow({ id: "a", space: "chat" }, q("reply=1"))).toEqual({ replyTarget: "a", space: "chat", by: "position" });
});
