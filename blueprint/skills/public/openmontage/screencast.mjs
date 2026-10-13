#!/usr/bin/env node
// Record a live page to mp4: CDP Page.startScreencast -> JPEG frames -> ffmpeg.
// screencast.mjs URL OUT.mp4 [seconds=5] [width=1280] [height=720]
// Connects to a running Chrome (fleet-browser "chrome" tier by default; CDP_URL overrides). It opens its own tab and closes it.
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { env } from "node:process";

const [url, out, secs = "5", w = "1280", h = "720"] = process.argv.slice(2);
if (!url || !out) {
  console.error("usage: screencast.mjs URL OUT.mp4 [seconds] [width] [height]");
  process.exit(2);
}
const cdp = env.CDP_URL || "http://127.0.0.1:9522";
const tab = await (await fetch(`${cdp}/json/new?about:blank`, { method: "PUT" })).json();
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((ok, no) => ((ws.onopen = ok), (ws.onerror = no)));

let id = 0;
const waits = new Map();
const frames = []; // {file, t}
const dir = mkdtempSync(join(tmpdir(), "screencast-"));
const send = (method, params = {}) =>
  new Promise((ok) => {
    waits.set(++id, ok);
    ws.send(JSON.stringify({ id, method, params }));
  });
ws.onmessage = ({ data }) => {
  const m = JSON.parse(data);
  if (m.id && waits.has(m.id)) return waits.get(m.id)(m.result);
  if (m.method !== "Page.screencastFrame") return;
  const file = join(dir, `f${frames.length}.jpg`);
  writeFileSync(file, Buffer.from(m.params.data, "base64"));
  frames.push({ file, t: m.params.metadata.timestamp });
  send("Page.screencastFrameAck", { sessionId: m.params.sessionId });
};

await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: +w, height: +h, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url });
await new Promise((r) => setTimeout(r, 2000)); // let the page load before recording
await send("Page.startScreencast", { format: "jpeg", quality: 80, maxWidth: +w, maxHeight: +h, everyNthFrame: 1 });
await new Promise((r) => setTimeout(r, +secs * 1000));
await send("Page.stopScreencast");
ws.close();
await fetch(`${cdp}/json/close/${tab.id}`);
if (frames.length < 2) {
  console.error(`only ${frames.length} frame(s): the page did not change while recording`);
  process.exit(1);
}

// The screencast sends a frame only when the page changes, so hold each frame until the next one.
const list = frames.map((f, i) => `file '${f.file}'\nduration ${i + 1 < frames.length ? frames[i + 1].t - f.t : 0.04}`);
list.push(`file '${frames.at(-1).file}'`);
writeFileSync(join(dir, "list.txt"), list.join("\n"));
const ff = spawnSync(
  "ffmpeg",
  ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", join(dir, "list.txt"), "-r", "30", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", out],
  { stdio: "inherit" },
);
rmSync(dir, { recursive: true, force: true });
if (ff.status) process.exit(ff.status);
console.log(out);
