import { afterAll, expect, test } from "bun:test";

// The send command turns --reply-id ID into the query the bridge reads, and keeps --reply N as before.
const urls: string[] = [];
const server = Bun.serve({ port: 0, hostname: "127.0.0.1", fetch(req) { urls.push(req.url.slice(req.url.indexOf("/send"))); return new Response("queued 1 bubble(s)\n"); } });
afterAll(() => server.stop(true));

const run = async (...args: string[]) => {
  const p = Bun.spawn([`${import.meta.dir}/fm-imessage`, ...args], { env: { PATH: process.env.PATH, FM_IMESSAGE_PORT: String(server.port), FM_IMESSAGE_WAIT_S: "0" }, stdout: "pipe", stderr: "pipe" });
  return { code: await p.exited, err: await new Response(p.stderr).text() };
};

test("--reply-id sends the id, URL-encoded, and --reply N is unchanged", async () => {
  expect((await run("--reply-id", "p:0/A B+1", "hi")).code).toBe(0);
  expect((await run("--reply", "2", "hi")).code).toBe(0);
  expect(urls).toEqual(["/send?reply-id=p%3A0%2FA%20B%2B1", "/send?reply=2"]);
});

test("--reply-id with no id, or with --reply, sends nothing", async () => {
  urls.length = 0;
  expect((await run("--reply-id", "")).code).toBe(2);
  const both = await run("--reply", "1", "--reply-id", "x", "hi");
  expect(both.code).toBe(2);
  expect(both.err).toContain("nothing sent");
  expect(urls).toEqual([]);
});
