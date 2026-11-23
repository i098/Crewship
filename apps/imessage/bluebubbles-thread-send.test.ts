import { afterEach, expect, spyOn, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { BlueBubbles } from "./bluebubbles.ts";

const servers: { stop(force?: boolean): void }[] = [];
const dirs: string[] = [];
afterEach(() => {
  for (const s of servers.splice(0)) s.stop(true);
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
});

function relay(privateApi: boolean, sendResponse: { guid?: unknown } = { guid: "sent-1" }) {
  const sent: Record<string, unknown>[] = [];
  let rejected = false;
  const server = Bun.serve({
    port: 0,
    async fetch(req) {
      const path = new URL(req.url).pathname;
      if (path.endsWith("/server/info")) return Response.json({ data: { private_api: privateApi } });
      if (path.endsWith("/message/text")) {
        sent.push((await req.json()) as Record<string, unknown>);
        if (rejected) return new Response("rejected", { status: 400 });
        return Response.json({ data: sendResponse });
      }
      if (path.endsWith("/message/sent-1")) return Response.json({
        data: { guid: "sent-1", isFromMe: true, chats: [{ guid: "iMessage;-;+15550000000" }] },
      });
      return new Response("no", { status: 404 });
    },
  });
  servers.push(server);
  const dir = mkdtempSync(join(tmpdir(), "bb-thread-"));
  dirs.push(dir);
  const bb = new BlueBubbles([{ url: `http://127.0.0.1:${server.port}`, password: "p" }], dir, {}, () => {});
  return { bb, sent, reject: (value: boolean) => { rejected = value; } };
}

test("a reply goes out as a thread reply when the relay has the Private API", async () => {
  const { bb, sent } = relay(true);
  await bb.send("iMessage;-;+15550000000", "hello", "parent-guid");
  expect(sent).toHaveLength(1);
  expect(sent[0]).toMatchObject({ message: "hello", selectedMessageGuid: "parent-guid", partIndex: 0 });
});

test("a reply goes out plain when the relay lacks the Private API", async () => {
  const { bb, sent } = relay(false);
  await bb.send("iMessage;-;+15550000000", "hello", "parent-guid");
  expect(sent).toHaveLength(1);
  expect(sent[0]!.selectedMessageGuid).toBeUndefined();
});

test("a send without a reply target is not threaded", async () => {
  const { bb, sent } = relay(true);
  await bb.send("iMessage;-;+15550000000", "hello");
  expect(sent[0]!.selectedMessageGuid).toBeUndefined();
});

test.each([{}, { guid: "" }, { guid: " " }, { guid: 42 }])("an accepted send without a usable GUID keeps its webhook match (%j)", async (response) => {
  const { bb, sent } = relay(true, response);
  const tempGuid = crypto.randomUUID();
  const recorded: string[] = [];
  expect(await bb.send("iMessage;-;+15550000000", "hello", undefined, tempGuid, undefined, (id) => recorded.push(id))).toBe("accepted");
  expect(recorded).toEqual([]);
  await bb.webhook(new Request("http://localhost/bluebubbles", {
    method: "POST",
    body: JSON.stringify({ type: "new-message", data: { isFromMe: true, tempGuid, guid: "sent-1" } }),
  }));
  expect(recorded).toEqual(["sent-1"]);
  expect(sent).toHaveLength(1);
});

for (const retry of ["relay", "outbox", "restart"]) {
  test(`the ${retry} retry deduplicates delivery without creating a sender match`, async () => {
    const chat = "iMessage;-;+15550000000";
    const tempGuid = crypto.randomUUID();
    const older = { guid: "same-text", text: "Done.", isFromMe: true, chats: [{ guid: chat }] };
    const late = { ...older, guid: "sent-by-relay" };
    let posts = 0;
    let rejectRetry = false;
    const server = Bun.serve({
      hostname: "127.0.0.1",
      port: 0,
      async fetch(req) {
        const path = new URL(req.url).pathname;
        if (path.endsWith("/server/info")) return Response.json({ data: {} });
        if (path.endsWith("/message/text")) {
          posts++;
          if (rejectRetry) return new Response("rejected", { status: 400 });
          if (posts > 1) return Response.json({ data: { guid: "next-send" } });
          return new Response("lost answer", { status: 500 });
        }
        if (path.endsWith(`/chat/${encodeURIComponent(chat)}/message`)) return Response.json({ data: [older] });
        return Response.json({ data: [older, late].find((m) => path.endsWith(`/message/${m.guid}`)) });
      },
    });
    servers.push(server);
    const dir = mkdtempSync(join(tmpdir(), "bb-thread-"));
    dirs.push(dir);
    const relay = { url: `http://127.0.0.1:${server.port}`, password: "p" };
    const bb = new BlueBubbles(retry === "relay" ? [relay, { ...relay }] : [relay], dir, {}, () => {});
    const recorded: string[] = [];
    const record = (id: string) => recorded.push(id);
    let receiving = bb;
    if (retry === "relay") {
      expect(await bb.send(chat, "Done.", undefined, tempGuid, undefined, record)).toBe("reconciled");
    } else {
      await expect(bb.send(chat, "Done.", undefined, tempGuid, undefined, record)).rejects.toThrow();
      if (retry === "restart") receiving = new BlueBubbles([relay], dir, {}, () => {});
      expect(await receiving.sent(chat, "Done.", Date.now())).toBe(true);
    }
    expect(posts).toBe(1);
    expect(recorded).toEqual([]);
    if (retry === "outbox") {
      rejectRetry = true;
      await expect(receiving.send(chat, "Done.", undefined, tempGuid, undefined, record)).rejects.toThrow("HTTP 400");
      rejectRetry = false;
    }
    await receiving.send(chat, "Done.", undefined, undefined, undefined, record);
    for (const [match, guid] of [[crypto.randomUUID(), "same-text"], [tempGuid, "sent-by-relay"]]) {
      await receiving.webhook(new Request("http://localhost/bluebubbles", {
        method: "POST",
        body: JSON.stringify({ type: "new-message", data: { isFromMe: true, tempGuid: match, guid } }),
      }));
    }
    expect(recorded).toEqual(retry === "restart" ? ["next-send"] : []);
  });
}

test("a definite rejection does not block attribution for the next send", async () => {
  const { bb, reject } = relay(false);
  const chat = "iMessage;-;+15550000000";
  reject(true);
  await expect(bb.send(chat, "Done.", undefined, undefined, undefined, () => {})).rejects.toThrow("HTTP 400");
  reject(false);
  const recorded: string[] = [];
  await bb.send(chat, "Done!", undefined, undefined, undefined, (id) => recorded.push(id));
  expect(recorded).toEqual(["sent-1"]);
});

test.each([
  { replayed: false, delay: 0 },
  { replayed: true, delay: 0 },
  { replayed: false, delay: 11_000 },
  { replayed: true, delay: 11_000 },
])("overlapping sends block attribution (%j)", async ({ replayed, delay }) => {
  const chat = "iMessage;-;+15550000000";
  const firstGuid = crypto.randomUUID();
  const { promise: held, resolve: release } = Promise.withResolvers<void>();
  const { promise: started, resolve: arrived } = Promise.withResolvers<void>();
  const bubble = { guid: "first-bubble", text: "Done!", isFromMe: true, chats: [{ guid: chat }] };
  const server = Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    async fetch(req) {
      const path = new URL(req.url).pathname;
      if (path.endsWith("/server/info")) return Response.json({ data: {} });
      if (path.endsWith("/message/text")) {
        if ((await req.json()).tempGuid === firstGuid) {
          arrived();
          await held;
        }
        return Response.json({ data: { guid: bubble.guid } });
      }
      return Response.json({ data: path.endsWith(`/message/${bubble.guid}`) ? bubble : [bubble] });
    },
  });
  servers.push(server);
  const dir = mkdtempSync(join(tmpdir(), "bb-thread-"));
  dirs.push(dir);
  const bb = new BlueBubbles([{ url: `http://127.0.0.1:${server.port}`, password: "p" }], dir, { trackPending: true }, () => {});
  const recorded: string[] = [];
  const record = (id: string) => recorded.push(id);
  const first = bb.send(chat, "Done!", undefined, firstGuid, undefined, replayed ? undefined : record);
  await started;
  const secondGuid = crypto.randomUUID();
  const now = Date.now.bind(Date);
  const clock = spyOn(Date, "now").mockImplementation(() => now() + delay);
  try {
    expect(await bb.sent(chat, "Done!", Date.now())).toBe(true);
    expect(await bb.send(chat, "Done?", undefined, secondGuid, undefined, record)).toBe("accepted");
    await bb.webhook(new Request("http://localhost/bluebubbles", {
      method: "POST",
      body: JSON.stringify({ type: "new-message", data: { isFromMe: true, tempGuid: firstGuid, guid: bubble.guid } }),
    }));
  } finally {
    clock.mockRestore();
    release();
    await first;
  }
  expect(recorded).toEqual([]);
});
