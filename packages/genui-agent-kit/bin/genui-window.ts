#!/usr/bin/env bun
// Usage: genui-window --url <server> --board <id> <open|move|raise|lower|float|sink|close> <window-id>
//          [--title T] [--body B | --src URL] [--at x,y[,w,h]] [--near <card-id>]
// Rule: large text or extra context opens a window here (open --near <card>); never rewrite a card's own content to hold it.
import { agentClient } from "../src/client";
import { parseAt, WINDOW_CMDS, type WindowCmd, windowPatch } from "../src/window";

const args = process.argv.slice(2);
const opt = (n: string) => {
  const i = args.indexOf(`--${n}`);
  return i >= 0 ? args.splice(i, 2)[1] : undefined;
};
const url = opt("url") ?? process.env.GENUI_URL;
const board = opt("board") ?? process.env.GENUI_BOARD;
const title = opt("title"),
  body = opt("body"),
  src = opt("src"),
  at = opt("at"),
  near = opt("near");
const [cmd, id] = args;
if (!url || !board || !WINDOW_CMDS.includes(cmd as WindowCmd) || !id) {
  console.error(
    `usage: genui-window --url <server> --board <id> <${WINDOW_CMDS.join("|")}> <window-id> [--title T] [--body B | --src URL] [--at x,y[,w,h]] [--near <card-id>]`,
  );
  process.exit(2);
}
try {
  const delta = windowPatch(cmd as WindowCmd, id, { title, body, src, near, at: at ? parseAt(at) : undefined });
  const reply = await agentClient(url, board, process.env.GENUI_AGENT_TOKEN).call("emit_view", { event: { delta }, cause: `window:${cmd}` });
  console.log(JSON.stringify(reply));
} catch (e) {
  console.error((e as Error).message);
  process.exit(1);
}
