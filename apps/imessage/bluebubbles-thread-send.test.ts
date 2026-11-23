import { afterEach, expect, test } from "bun:test";
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

function relay(privateApi: boolean) {
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
        return Response.json({ data: { guid: "sent-1" } });
      }
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

for (const retry of ["relay", "outbox"]) {
  test(`the ${retry} retry deduplicates delivery without creating a sender match`, async () => {
    const chat = "iMessage;-;+15550000000";
    const tempGuid = crypto.randomUUID();
    const history = [
      { guid: "same-text", text: "Done.", isFromMe: true, chats: [{ guid: chat }] },
      { guid: "sent-by-relay", text: "Done.", isFromMe: true, chats: [{ guid: chat }] },
    ];
    let posts = 0;
    const server = Bun.serve({
      hostname: "127.0.0.1",
      port: 0,
      async fetch(req) {
        const path = new URL(req.url).pathname;
        if (path.endsWith("/server/info")) return Response.json({ data: {} });
        if (path.endsWith("/message/text")) {
          posts++;
          return new Response("lost answer", { status: 500 });
        }
        if (path.endsWith(`/chat/${encodeURIComponent(chat)}/message`)) return Response.json({ data: history });
        return Response.json({ data: history.find((m) => path.endsWith(`/message/${m.guid}`)) });
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
      receiving = new BlueBubbles([relay], dir, {}, () => {});
      expect(await receiving.sent(chat, "Done.", Date.now())).toBe(true);
    }
    expect(posts).toBe(1);
    expect(recorded).toEqual([]);
    for (const [match, guid] of [[crypto.randomUUID(), "same-text"], [tempGuid, "sent-by-relay"]]) {
      await receiving.webhook(new Request("http://localhost/bluebubbles", {
        method: "POST",
        body: JSON.stringify({ type: "new-message", data: { isFromMe: true, tempGuid: match, guid } }),
      }));
    }
    expect(recorded).toEqual(retry === "relay" ? ["sent-by-relay"] : []);
  });
}

test("a definite rejection does not block attribution for the next send", async () => {
  const { bb, reject } = relay(false);
  const chat = "iMessage;-;+15550000000";
  reject(true);
  await expect(bb.send(chat, "Done.")).rejects.toThrow("HTTP 400");
  reject(false);
  const recorded: string[] = [];
  await bb.send(chat, "Done!", undefined, undefined, undefined, (id) => recorded.push(id));
  expect(recorded).toEqual(["sent-1"]);
});

test("ambiguous relay matches record no sender through either response path", async () => {
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
  const bb = new BlueBubbles([{ url: `http://127.0.0.1:${server.port}`, password: "p" }], dir, {}, () => {});
  const recorded: string[] = [];
  const record = (id: string) => recorded.push(id);
  const first = bb.send(chat, "Done!", undefined, firstGuid, undefined, record);
  await started;
  const secondGuid = crypto.randomUUID();
  try {
    expect(await bb.send(chat, "Done?", undefined, secondGuid, undefined, record)).toBe("accepted");
    expect(await bb.sent(chat, "Done!", Date.now())).toBe(true);
    await bb.webhook(new Request("http://localhost/bluebubbles", {
      method: "POST",
      body: JSON.stringify({ type: "new-message", data: { isFromMe: true, tempGuid: firstGuid, guid: bubble.guid } }),
    }));
  } finally {
    release();
    await first;
  }
  expect(recorded).toEqual([]);
});
