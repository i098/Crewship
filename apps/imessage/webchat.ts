// The web chat (docs/imessage.md#web-chat): one page that shows the thread from the desk memory and files typed text
// as an inbox note. The bridge serves it on its own loopback port; the operator publishes that port on the tailnet.
// The page can send text as the owner, so every request must name an allowed Host, and a send must come from the
// page itself (its Origin is that Host).
import { existsSync } from "node:fs";
import { basename } from "node:path";
import type { Msg } from "./memory.ts";

export const WEB_MARK = "[web chat] "; // starts the note and the memory entry of a text typed on the page
const FIRST_PAGE = 200; // messages on a fresh page; shortcut: no older history, add paging when he asks for it
const TYPES: Record<string, string> = { png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif", webp: "image/webp" };
const typeOf = (name: string) => TYPES[name.slice(name.lastIndexOf(".") + 1).toLowerCase()];
const HEADERS = { "cache-control": "no-store", "referrer-policy": "no-referrer", "x-content-type-options": "nosniff" };
const plain = (status: number, text: string) => new Response(`${text}\n`, { status, headers: HEADERS });

export type WebChat = {
  port: number;
  host?: string; // the tailnet name that `tailscale serve` publishes the port under
  msgs: () => Msg[];
  send: (text: string) => boolean; // files the note; false when the inbox did not take it
  attachDir: string; // the owner's saved attachments
  sentDir: string; // photos sent to him, named <memory index>-<name>
};

// The pictures of one message, as page paths: his saved attachments, and the photo of an `[image: name]` entry.
function images(o: WebChat, m: Msg): string[] {
  if (m.kind === "owner") {
    return [...m.text.matchAll(/saved for Firstmate at (\S+?)\)/g)].map((x) => x[1]!)
      .filter((path) => path === `${o.attachDir}/${basename(path)}` && typeOf(path))
      .map((path) => `/file/a/${encodeURIComponent(basename(path))}`);
  }
  const name = /^\[image: ([^\]\n]+)\]/.exec(m.text)?.[1];
  return name && existsSync(`${o.sentDir}/${m.i}-${name}`) ? [`/file/s/${encodeURIComponent(`${m.i}-${name}`)}`] : [];
}

export function webchatRoutes(o: WebChat) {
  const hosts = new Set([`127.0.0.1:${o.port}`, ...(o.host ? [o.host.toLowerCase()] : [])]);
  const messages = (url: URL): Response => {
    const all = o.msgs();
    const after = Number(url.searchParams.get("after") ?? -1); // no `after`: a fresh page
    const from = Number.isInteger(after) && after >= 0 ? after + 1 : Math.max(0, all.length - FIRST_PAGE);
    return Response.json({ messages: all.slice(from).map((m) => ({ i: m.i, kind: m.kind, text: m.text, date: m.date, images: images(o, m) })) }, { headers: HEADERS });
  };
  const file = async (dir: string, name: string): Promise<Response> => {
    const type = typeOf(name);
    const body = Bun.file(`${dir}/${name}`);
    // The name is one path segment with an image extension, so it cannot leave its directory.
    if (name !== basename(name) || !type || !await body.exists()) return plain(404, "not found");
    return new Response(body, { headers: { ...HEADERS, "cache-control": "private, max-age=86400", "content-type": type } });
  };
  const send = async (req: Request, host: string): Promise<Response> => {
    let origin: string | undefined;
    try { origin = new URL(req.headers.get("origin") ?? "").host.toLowerCase(); } catch { /* no Origin: not the page */ }
    if (origin !== host) return plain(403, "forbidden");
    const text = (await req.text()).trim();
    if (!text) return plain(400, "empty message");
    return o.send(text) ? plain(200, "sent") : plain(503, "Firstmate did not get it. Try again.");
  };
  return async (req: Request): Promise<Response> => {
    const host = (req.headers.get("host") ?? "").toLowerCase();
    if (!hosts.has(host)) return plain(403, "forbidden");
    const url = new URL(req.url);
    if (req.method === "POST") return url.pathname === "/send" ? send(req, host) : plain(404, "not found");
    if (req.method !== "GET") return plain(404, "not found");
    if (url.pathname === "/") return page();
    if (url.pathname === "/messages") return messages(url);
    const path = /^\/file\/([as])\/([^/]+)$/.exec(url.pathname);
    return path ? file(path[1] === "a" ? o.attachDir : o.sentDir, decodeURIComponent(path[2]!)) : plain(404, "not found");
  };
}

function page(): Response {
  const nonce = crypto.randomUUID();
  return new Response(PAGE.replaceAll("NONCE", nonce), { headers: { ...HEADERS, "content-type": "text/html; charset=utf-8",
    "content-security-policy": `default-src 'none'; img-src 'self'; connect-src 'self'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'` } });
}

// For XR glasses: large type, white on black, one column, big targets. The script has no backtick, so it stays one literal.
const PAGE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Firstmate</title>
<style nonce="NONCE">
*, *::before, *::after { box-sizing: border-box; }
html { background: hsl(0 0% 0%); color: hsl(0 0% 100%); font: 22px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; -webkit-text-size-adjust: 100%; }
body { margin: 0 auto; max-width: 46rem; padding: 0 1rem; min-height: 100dvh; display: flex; flex-direction: column; }
h1 { font-size: 1.25rem; margin: 0; padding: 1rem 0 .5rem; }
#log { flex: 1; }
h2 { font-size: .8rem; font-weight: 600; color: hsl(0 0% 78%); margin: 1.5rem 0 .5rem; text-transform: uppercase; letter-spacing: .06em; }
article { border-left: .25rem solid var(--who); padding: .25rem 0 .25rem .75rem; margin: 0 0 1.1rem; }
article.owner { --who: hsl(200 100% 72%); }
article.supervisor { --who: hsl(48 100% 66%); }
article.desk { --who: hsl(140 70% 66%); }
header { display: flex; flex-wrap: wrap; align-items: baseline; gap: .6rem; font-size: .8rem; }
.who { color: var(--who); font-weight: 700; }
.via { border: 1px solid hsl(0 0% 78%); border-radius: .3rem; padding: 0 .35rem; }
time { color: hsl(0 0% 78%); font-variant-numeric: tabular-nums; }
p { margin: .15rem 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
article a { display: block; margin-top: .5rem; border-radius: .5rem; }
img { display: block; max-width: 100%; max-height: 80dvh; border-radius: .5rem; }
form { position: sticky; bottom: 0; background: hsl(0 0% 0%); border-top: 1px solid hsl(0 0% 35%); padding: .75rem 0 1rem; display: flex; gap: .75rem; align-items: stretch; }
textarea { flex: 1; min-width: 0; min-height: 4rem; font: inherit; color: inherit; background: hsl(0 0% 10%); border: 2px solid hsl(0 0% 60%); border-radius: .5rem; padding: .5rem .75rem; resize: vertical; }
button { font: inherit; font-weight: 700; min-width: 5rem; min-height: 4rem; color: hsl(0 0% 0%); background: hsl(48 100% 66%); border: 0; border-radius: .5rem; cursor: pointer; }
button:disabled { background: hsl(0 0% 45%); cursor: default; }
:focus-visible { outline: .2rem solid hsl(200 100% 72%); outline-offset: .15rem; }
#state { margin: 0; min-height: 1.5em; font-size: .8rem; color: hsl(20 100% 75%); }
</style>
</head>
<body>
<h1>Firstmate</h1>
<main id="log" aria-live="polite"></main>
<p id="state" role="status"></p>
<form id="form">
<textarea id="box" aria-label="Message" autocomplete="off" enterkeyhint="send" required></textarea>
<button id="go">Send</button>
</form>
<script nonce="NONCE">
const MARK = ${JSON.stringify(WEB_MARK)};
const NAMES = { owner: "You", supervisor: "Firstmate", desk: "Desk" };
const log = document.getElementById("log"), state = document.getElementById("state");
const form = document.getElementById("form"), box = document.getElementById("box"), go = document.getElementById("go");
const clock = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const day = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" });
let last = -1, lastDay = "";
const el = (tag, text, cls) => { const e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; };
const atEnd = () => innerHeight + scrollY >= document.documentElement.scrollHeight - 120;
const toEnd = () => scrollTo(0, document.documentElement.scrollHeight);

function show(m, stick) {
  const when = new Date(m.date), dayText = day.format(when), web = m.kind === "owner" && m.text.startsWith(MARK);
  let text = web ? m.text.slice(MARK.length) : m.text;
  // The picture stands for its "[image: name]" line.
  if (m.images.length && text.startsWith("[image: ")) text = text.slice(text.indexOf("]") + 1).trim();
  if (dayText !== lastDay) log.append(el("h2", lastDay = dayText));
  const item = el("article", "", m.kind), head = el("header");
  const time = el("time", clock.format(when));
  time.dateTime = m.date;
  head.append(el("span", NAMES[m.kind] || m.kind, "who"), ...(web ? [el("span", "web chat", "via")] : []), time);
  item.append(head);
  if (text) item.append(el("p", text));
  for (const src of m.images) {
    const link = el("a"), img = el("img");
    link.href = src; link.target = "_blank"; link.rel = "noopener";
    img.src = src; img.alt = "Image in this message";
    img.onload = () => { if (stick) toEnd(); };
    link.append(img); item.append(link);
  }
  log.append(item);
}

async function refresh() {
  try {
    const r = await fetch("/messages?after=" + last, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    const stick = last < 0 || atEnd();
    const fresh = (await r.json()).messages.filter((m) => m.i > last);
    for (const m of fresh) { show(m, stick); last = m.i; }
    if (fresh.length && stick) toEnd();
    if (state.dataset.net) { state.textContent = ""; delete state.dataset.net; }
  } catch {
    state.textContent = "No connection. Trying again.";
    state.dataset.net = "1";
  }
}
(async function loop() { await refresh(); setTimeout(loop, 2000); })();

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = box.value.trim();
  if (!text || go.disabled) return;
  go.disabled = true;
  try {
    const r = await fetch("/send", { method: "POST", body: text });
    if (!r.ok) throw new Error((await r.text()).trim());
    box.value = "";
    state.textContent = "";
    await refresh();
    toEnd();
  } catch (e) {
    state.textContent = "Not sent. " + (e instanceof TypeError ? "No connection. Try again." : e.message || "Try again.");
  }
  go.disabled = false;
  box.focus();
});
box.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
});
</script>
</body>
</html>
`;
