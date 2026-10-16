// fm-insta-reply on the official Instagram API (INSTAGRAM_DM_BACKEND=graph): DMs the operator through
// graph.instagram.com with Instagram Login, and keeps the long-lived token fresh. Meta lets a business answer only
// within 24 h of the user's last DM, so a send outside that window is refused here, before any call.
//   bun instagram-graph.ts reply [TEXT] [--thread ID] [--react EMOJI] [--typing] [-- TEXT]
//   bun instagram-graph.ts token < file   save the token from stdin to INSTAGRAM_DM_DIR/graph-token.json (mode 0600)
//   bun instagram-graph.ts refresh        the weekly timer: a new token once the saved one is 24 h old (Meta's rule)
// Settings are the instagram-dm skill's env vars (SKILL.md#official-api-backend). The token is never printed.
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { parseArgs } from "node:util";
import type { Row } from "./instagram-desk.ts";

const env = process.env;
const dir = env.INSTAGRAM_DM_DIR || `${env.HOME}/.local/state/instagram-dm`;
const tokenFile = `${dir}/graph-token.json`;
const base = env.INSTAGRAM_GRAPH_URL || "https://graph.instagram.com";
const REPLY_MAX = 500; // characters: the operator asked for short plain texts
const TYPING_MIN = 100; // characters: a typing indicator only comes before a reply longer than this
const WINDOW_S = 86_400;
let secret = ""; // scrubbed from every message printed

function die(msg: string): never {
  console.error(secret ? msg.replaceAll(secret, "***").replaceAll(encodeURIComponent(secret), "***") : msg);
  process.exit(1);
}

const NO_TOKEN = `no token in ${tokenFile}: seed it with \`bun instagram-graph.ts token < file\``;
type Saved = { token: string; at: number };
type GraphReply = { access_token?: string; expires_in?: number; error?: { message?: string } };

function refuse(why: string): never {
  die(`not sending: ${why}`);
}

function save(token: string) {
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  writeFileSync(`${tokenFile}.tmp`, JSON.stringify({ token, at: Math.floor(Date.now() / 1000) }), { mode: 0o600 });
  renameSync(`${tokenFile}.tmp`, tokenFile);
}

// The same row as instagram_dm.py record_sent: the front desk stands down on it. Best effort.
function record(kind: string, thread: string, text = "") {
  const sent = env.INSTAGRAM_DM_SENT || `${dir}/sent.jsonl`;
  try {
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    appendFileSync(sent, `${JSON.stringify({ at: Math.floor(Date.now() / 1000), thread, kind, by: env.INSTAGRAM_DM_ACTOR || "firstmate", ...(text && { text }) })}\n`);
  } catch {}
}

// The operator's latest DM, from the log the webhook writes.
function lastDm(operator: string): Row | undefined {
  const log = env.INSTAGRAM_DM_LOG || `${dir}/messages.jsonl`;
  return (existsSync(log) ? readFileSync(log, "utf8").split("\n") : [])
    .flatMap((l) => {
      try {
        return [JSON.parse(l) as Row];
      } catch {
        return []; // a blank, torn or foreign line
      }
    })
    .findLast((r) => r.thread === operator);
}

// The operator, his latest DM and the token, or an exit with the reason no send may go out now.
function cleared(thread?: string): { operator: string; last: Row; token: string } {
  const operator = env.INSTAGRAM_DM_OPERATOR;
  if (!operator) refuse("set INSTAGRAM_DM_OPERATOR");
  if (thread && thread !== operator) refuse(`thread ${thread} is not the operator's`);
  if (existsSync(`${dir}/stop`)) refuse(`the line is stopped (${readFileSync(`${dir}/stop`, "utf8").trim() || "stopped"})`);
  const last = lastDm(operator);
  if (!last) refuse("no DM from the operator yet: the API answers only within 24 h of his last DM");
  const age = Date.now() / 1000 - last.at;
  if (age >= WINDOW_S) refuse(`outside the 24-hour window: his last DM was ${Math.floor(age / 3600)} h ago`);
  if (!existsSync(tokenFile)) refuse(NO_TOKEN);
  const { token }: Saved = JSON.parse(readFileSync(tokenFile, "utf8"));
  secret = token;
  return { operator, last, token };
}

function parse(args: string[]) {
  try {
    return parseArgs({ args, allowPositionals: true, options: { thread: { type: "string" }, react: { type: "string" }, typing: { type: "boolean" } } });
  } catch (e) {
    die(String(e));
  }
}

async function reply(args: string[]) {
  const a = parse(args);
  const { thread, react = "", typing = false } = a.values;
  const text = a.positionals.join(" ").replace(/\s+/g, " ").trim();
  const length = [...text].length;
  if (length > REPLY_MAX) die(`reply is ${length} characters: keep it under ${REPLY_MAX}, short and plain`);
  if (!(text || react || typing)) die("nothing to send: give TEXT, --react or --typing");
  const kinds = [typing && length > TYPING_MIN && "typing", react && "react", text && "text"].filter(Boolean);
  if (!kinds.length) return console.log("no typing indicator for a short reply: nothing to send");

  const { operator, last, token } = cleared(thread);
  const actions: Record<string, object> = {
    typing: { sender_action: "typing_on" },
    react: { sender_action: "react", payload: { message_id: last.id, reaction: react } },
    text: { message: { text } },
  };
  for (const kind of kinds as string[]) {
    const res = await fetch(`${base}/v25.0/me/messages`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ recipient: { id: operator }, ...actions[kind] }),
    }).catch((e) => die(`send failed: ${kind} ${e}`));
    if (!res.ok) {
      const body: GraphReply = await res.json().catch(() => ({}));
      die(`send failed: ${kind} HTTP ${res.status} ${body.error?.message ?? ""}`);
    }
    record(kind, operator, { react, text }[kind] ?? "");
    if (kind === "typing") await Bun.sleep(800); // a beat of typing before the text
  }
}

async function refresh() {
  if (!existsSync(tokenFile)) die(NO_TOKEN);
  const saved: Saved = JSON.parse(readFileSync(tokenFile, "utf8"));
  secret = saved.token;
  const hours = Math.floor((Date.now() / 1000 - saved.at) / 3600);
  if (hours < 24) return console.log(`token is ${hours} h old: refresh not due`);
  const res = await fetch(`${base}/refresh_access_token?grant_type=ig_refresh_token&access_token=${encodeURIComponent(saved.token)}`).catch((e) =>
    die(`refresh failed: ${e}`),
  );
  const body: GraphReply = await res.json().catch(() => ({}));
  if (!res.ok || !body.access_token) die(`refresh failed: HTTP ${res.status} ${body.error?.message ?? ""}`);
  save(body.access_token);
  console.log(`token refreshed; expires in ${Math.floor((body.expires_in ?? 0) / 86_400)} days`);
}

if (import.meta.main) {
  const [cmd, ...args] = process.argv.slice(2);
  if (cmd === "reply") await reply(args);
  else if (cmd === "refresh") await refresh();
  else if (cmd === "token") {
    const token = (await Bun.stdin.text()).trim();
    if (!token) die("no token on stdin");
    save(token);
    console.log("token saved");
  } else die("usage: bun instagram-graph.ts reply [TEXT] [--thread ID] [--react EMOJI] [--typing] [-- TEXT] | token < file | refresh");
}
