// The web chat (docs/imessage.md#web-chat): one page that shows the thread from the desk memory and files typed text
// as an inbox note. The bridge serves it on its own loopback port; the operator publishes that port with `tailscale serve`
// or behind an access gateway that enforces sign-in. The page has no sign-in of its own.
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
  host?: string; // the hostname that `tailscale serve` or the access gateway publishes the port under
  msgs: () => Msg[];
  send: (text: string) => boolean; // routes the text to Firstmate; false when the bridge is stopping
  attachDir: string; // the owner's saved attachments
  sentDir: string; // photos sent to him, named <memory index>-<name>
};

// The pictures of one message, as page paths: his saved attachments, and the photo of an `[image: name]` entry.
function images(o: WebChat, m: Msg): string[] {
  if (m.kind === "owner") {
    return [...m.text.matchAll(/saved for Firstmate at (\S+?)\)/g)].map((x) => x[1]!)
      .filter((path) => path === `${o.attachDir}/${basename(path)}` && typeOf(path))
      .map((path) => `file/a/${encodeURIComponent(basename(path))}`);
  }
  const name = /^\[image: ([^\]\n]+)\]/.exec(m.text)?.[1];
  return name && existsSync(`${o.sentDir}/${m.i}-${name}`) ? [`file/s/${encodeURIComponent(`${m.i}-${name}`)}`] : [];
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

// A messages app look for XR glasses: bubbles, one composer line, large type and targets, the system's light or dark
// scheme. The script has no backtick, so it stays one literal.
const PAGE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Firstmate</title>
<style nonce="NONCE">
*, *::before, *::after { box-sizing: border-box; }
:root { --bg: hsl(0 0% 100%); --fg: hsl(0 0% 7%); --muted: hsl(240 2% 40%); --them: hsl(240 6% 92%); --line: hsl(240 3% 55%);
  --hair: hsl(240 6% 90%); --bar: hsl(0 0% 100% / .92); --me: hsl(211 100% 45%); --on-me: hsl(0 0% 100%); --err: hsl(4 80% 42%); }
@media (prefers-color-scheme: dark) {
  :root { --bg: hsl(240 6% 10%); --fg: hsl(0 0% 98%); --muted: hsl(240 4% 68%); --them: hsl(240 4% 20%); --line: hsl(240 3% 50%);
    --hair: hsl(240 4% 18%); --bar: hsl(240 6% 10% / .92); --err: hsl(4 90% 72%); }
}
html { background: var(--bg); color: var(--fg); font: clamp(1.25rem, 1rem + 0.5vw, 1.5rem)/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; -webkit-text-size-adjust: 100%; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; scrollbar-width: thin; scrollbar-color: var(--line) transparent; }
body { margin: 0; min-height: 100dvh; display: flex; flex-direction: column; }
header, form { position: sticky; z-index: 1; background: var(--bar); -webkit-backdrop-filter: saturate(1.8) blur(20px); backdrop-filter: saturate(1.8) blur(20px); }
header { top: 0; border-bottom: 1px solid var(--hair); padding: .7rem 1rem; text-align: center; }
h1 { font-size: .9rem; font-weight: 600; margin: 0; }
#log, #pill, #state { width: 100%; max-width: 44rem; margin: 0 auto; }
#log { flex: 1; display: flex; flex-direction: column; padding: .5rem 1rem 1rem; }
#log:empty::before { content: "No messages yet"; margin: auto; color: var(--muted); }
.when { display: block; margin: 1.25rem 0 .5rem; text-align: center; font-size: .7rem; color: var(--muted); font-variant-numeric: tabular-nums; }
article { display: flex; flex-direction: column; align-items: flex-start; gap: .15rem; margin-top: .5rem; }
article.owner { align-items: flex-end; }
.owner + .owner, .supervisor + .supervisor, .desk + .desk { margin-top: .15rem; }
article p { margin: 0; max-width: min(82%, 32rem); padding: .45rem .85rem; border-radius: 1.2rem; background: var(--them); white-space: pre-wrap; overflow-wrap: anywhere; text-wrap: pretty; }
.owner p { background: var(--me); color: var(--on-me); }
.desk p { background: none; border: 1px solid var(--hair); color: var(--muted); }
.cap { padding: 0 .85rem; font-size: .7rem; color: var(--muted); }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
article a { max-width: min(82%, 24rem); border-radius: 1.2rem; }
img { display: block; max-width: 100%; max-height: 60dvh; border-radius: 1.2rem; outline: 1px solid hsl(0 0% 50% / .25); outline-offset: -1px; }
form { bottom: 0; margin: 0; padding: .5rem 1rem calc(.75rem + env(safe-area-inset-bottom)); }
#state { margin-bottom: .4rem; text-align: center; font-size: .7rem; color: var(--err); }
#state:empty { display: none; }
#pill { display: flex; align-items: flex-end; gap: .25rem; padding: .2rem .2rem .2rem .9rem; background: var(--bg); border: 1px solid var(--line); border-radius: 1.4rem; }
#pill:focus-within { border-color: var(--muted); }
textarea { flex: 1; min-width: 0; height: 2.4rem; max-height: 8rem; padding: .5rem 0; font: inherit; color: inherit; background: none; border: 0; outline: 0; resize: none; scrollbar-width: none; }
textarea::placeholder { color: var(--muted); opacity: 1; }
button { flex: none; display: grid; place-items: center; width: 2.4rem; height: 2.4rem; padding: 0; color: var(--on-me); background: var(--me); border: 0; border-radius: 50%; cursor: pointer; -webkit-tap-highlight-color: transparent; transition: scale 150ms ease-out, background-color 150ms ease-out; }
button:disabled { color: var(--muted); background: var(--them); cursor: default; }
button:focus-visible, a:focus-visible { outline: 2px solid var(--fg); outline-offset: 2px; }
@media (prefers-reduced-motion: no-preference) { button:not(:disabled):active { scale: .96; } }
</style>
</head>
<body>
<header><h1>Firstmate</h1></header>
<main id="log" aria-live="polite"></main>
<form id="form">
<p id="state" role="status"></p>
<div id="pill">
<textarea id="box" rows="1" placeholder="Message" aria-label="Message" autocomplete="off" enterkeyhint="send"></textarea>
<button id="go" aria-label="Send" disabled><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/></svg></button>
</div>
</form>
<script nonce="NONCE">
const MARK = ${JSON.stringify(WEB_MARK)};
const NAMES = { owner: "You", supervisor: "Firstmate", desk: "Desk" };
const log = document.getElementById("log"), state = document.getElementById("state");
const form = document.getElementById("form"), box = document.getElementById("box"), go = document.getElementById("go");
const stamp = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
let last = -1, lastWhen = 0, busy = false;
const el = (tag, text, cls) => { const e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; };
const atEnd = () => innerHeight + scrollY >= document.documentElement.scrollHeight - 120;
const toEnd = () => scrollTo(0, document.documentElement.scrollHeight);

function show(m, stick) {
  const when = new Date(m.date), web = m.kind === "owner" && m.text.startsWith(MARK);
  let text = web ? m.text.slice(MARK.length) : m.text;
  // The picture stands for its "[image: name]" line.
  if (m.images.length && text.startsWith("[image: ")) text = text.slice(text.indexOf("]") + 1).trim();
  // A time line as in a messages app: at the start and after 15 quiet minutes.
  if (when - lastWhen >= 9e5) {
    const time = el("time", stamp.format(when), "when");
    time.dateTime = m.date;
    log.append(time);
  }
  lastWhen = +when;
  const item = el("article", "", m.kind);
  item.append(el("span", NAMES[m.kind] || m.kind, m.kind === "desk" ? "cap" : "sr"));
  for (const src of m.images) {
    const link = el("a"), img = el("img");
    link.href = src; link.target = "_blank"; link.rel = "noopener";
    img.src = src; img.alt = "Image in this message";
    img.onload = () => { if (stick) toEnd(); };
    link.append(img); item.append(link);
  }
  if (text) item.append(el("p", text));
  if (web) item.append(el("span", "Web chat", "cap"));
  log.append(item);
}

async function refresh() {
  try {
    const r = await fetch("messages?after=" + last, { cache: "no-store" });
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

// The composer line grows with its text; the send button is live only with text to send.
function fit() {
  box.style.height = "";
  if (box.scrollHeight > box.clientHeight) box.style.height = box.scrollHeight + "px";
  go.disabled = busy || !box.value.trim();
}
box.addEventListener("input", fit);
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = box.value.trim();
  if (!text || busy) return;
  busy = true; fit();
  try {
    const r = await fetch("send", { method: "POST", body: text });
    if (!r.ok) throw new Error((await r.text()).trim());
    box.value = "";
    state.textContent = "";
    await refresh();
    toEnd();
  } catch (e) {
    state.textContent = "Not sent. " + (e instanceof TypeError ? "No connection. Try again." : e.message || "Try again.");
  }
  busy = false; fit();
  box.focus();
});
box.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
});
</script>
</body>
</html>
`;
