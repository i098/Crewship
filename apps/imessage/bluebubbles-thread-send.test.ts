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
  const server = Bun.serve({
    port: 0,
    async fetch(req) {
      const path = new URL(req.url).pathname;
      if (path.endsWith("/server/info")) return Response.json({ data: { private_api: privateApi } });
      if (path.endsWith("/message/text")) {
        sent.push((await req.json()) as Record<string, unknown>);
        return Response.json({ data: { guid: "sent-1" } });
      }
      return new Response("no", { status: 404 });
    },
  });
  servers.push(server);
  const dir = mkdtempSync(join(tmpdir(), "bb-thread-"));
  dirs.push(dir);
  const bb = new BlueBubbles([{ url: `http://127.0.0.1:${server.port}`, password: "p" }], dir, {}, () => {});
  return { bb, sent };
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
