#!/usr/bin/env bun
// Usage: tail -F state/*.status | genui-bridge --url http://host:port --board <id> [--task <id>]
import { createGenuiClient } from "../src/client";
import { createBridge } from "../src/bridge";

const args = process.argv.slice(2);
const opt = (n: string) => {
  const i = args.indexOf(`--${n}`);
  return i >= 0 ? args[i + 1] : undefined;
};
const url = opt("url") ?? process.env.GENUI_URL;
const boardId = opt("board") ?? process.env.GENUI_BOARD;
if (!url || !boardId) {
  console.error("usage: genui-bridge --url <server> --board <id> [--task <id>]  (stdin: status lines)");
  process.exit(2);
}

const feed = createBridge(createGenuiClient({ url, boardId }), opt("task"));
const dec = new TextDecoder();
let buf = "";
for await (const chunk of Bun.stdin.stream()) {
  buf += dec.decode(chunk, { stream: true });
  const lines = buf.split("\n");
  buf = lines.pop()!;
  for (const l of lines) await feed(l).catch((e) => console.error(String(e)));
}
if (buf) await feed(buf).catch((e) => console.error(String(e)));
