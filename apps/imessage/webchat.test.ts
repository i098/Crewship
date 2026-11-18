import { afterEach, expect, test } from "bun:test";
import { webchatRoutes } from "./webchat.ts";
import type { Msg } from "./memory.ts";

const KEY = "WEB_ACCESS_PASSWORD";
const saved = process.env[KEY];
afterEach(() => { if (saved === undefined) delete process.env[KEY]; else process.env[KEY] = saved; });

const msg = (i: number, text: string): Msg => ({ i, kind: "supervisor", text, size: text.length, date: "2026-01-01T00:00:00Z" });
const get = async (path: string) => {
  const route = webchatRoutes({ port: 1, msgs: () => [msg(0, "the key is test-pass-123 ok"), msg(1, "test-pass-123 and test-pass-123")], send: () => true, attachDir: "/nope", sentDir: "/nope" });
  const res = await route(new Request(`http://127.0.0.1:1${path}`, { headers: { host: "127.0.0.1:1" } }));
  return ((await res.json()) as { messages: { text: string }[] }).messages.map((m) => m.text);
};

test("history and live polls serve each occurrence masked", async () => {
  process.env[KEY] = "test-pass-123";
  expect(await get("/messages")).toEqual(["the key is [hidden] ok", "[hidden] and [hidden]"]);
  expect(await get("/messages?after=0")).toEqual(["[hidden] and [hidden]"]);
});

test("the URL-encoded form is masked too", async () => {
  process.env[KEY] = "test pass&123";
  const route = webchatRoutes({ port: 1, msgs: () => [msg(0, "a test%20pass%26123 b test pass&123")], send: () => true, attachDir: "/nope", sentDir: "/nope" });
  const res = await route(new Request("http://127.0.0.1:1/messages", { headers: { host: "127.0.0.1:1" } }));
  expect(((await res.json()) as { messages: { text: string }[] }).messages[0]!.text).toBe("a [hidden] b [hidden]");
});

test("unset or short value changes nothing", async () => {
  delete process.env[KEY];
  expect((await get("/messages"))[0]).toBe("the key is test-pass-123 ok");
  process.env[KEY] = "the";
  expect((await get("/messages"))[0]).toBe("the key is test-pass-123 ok");
});
