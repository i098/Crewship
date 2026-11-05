import { afterAll, expect, test } from "bun:test";

// A mate pushes a text with one command: fm-imessage sends the key and the mate's FM_HOME as sender.
const seen: { key: string | null; sender: string | null; body: string }[] = [];
const server = Bun.serve({ port: 0, hostname: "127.0.0.1", async fetch(req) {
  seen.push({ key: req.headers.get("x-fm-key"), sender: req.headers.get("x-fm-sender"), body: await req.text() });
  return new Response("queued 1 bubble(s)\n");
} });
afterAll(() => server.stop(true));

test("fm-imessage --key sends the topic key and the sender to the bridge", async () => {
  const run = Bun.spawn([`${import.meta.dir}/fm-imessage`, "--key", "nums", "Up 4 percent."], {
    env: { PATH: process.env.PATH, FM_IMESSAGE_PORT: String(server.port), FM_HOME: "/fleet/mate1" }, stdout: "pipe", stderr: "pipe" });
  expect(await run.exited).toBe(0);
  expect(seen).toEqual([{ key: "nums", sender: "/fleet/mate1", body: "Up 4 percent." }]);
});
