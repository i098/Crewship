#!/usr/bin/env node
// Frame-exact capture of a self-driven walk. The page runs on a virtual clock (one 1/60 s frame per step), and the
// walk uses real CDP input only: mouse clicks, pointer-lock mouse-look and the forward key.
// usage: node capture.mjs ADAPTER.mjs OUTDIR        env CAPFROM, CAPTO: screenshot only frames [CAPFROM, CAPTO)
// Each segment replays the walk from frame 0, so N segments with split ranges run in parallel into one OUTDIR.
// The adapter (see SKILL.md) holds everything site-specific: url, pose hook, intro clicks, legs.
import fs from "fs";
import path from "path";
import { env } from "process";
import { pathToFileURL } from "url";
import { chromium } from "playwright-core";
import { Ctl, DT } from "./walk.mjs";

const [adapterPath, OUT] = process.argv.slice(2);
const A = (await import(pathToFileURL(path.resolve(adapterPath)))).default;
const W = 1700, H = 920, FROM = +(env.CAPFROM ?? 0), TO = +(env.CAPTO ?? Infinity); // the page area compose.mjs frames
const radPerPx = A.radPerPx, wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
fs.mkdirSync(OUT, { recursive: true });

// New headless Chromium: the old headless shell reports movementX = 0 under pointer lock, so mouse-look is dead.
const browser = await chromium.launch({ channel: "chromium", args: ["--ignore-gpu-blocklist"] });
const ctx = await browser.newContext({ viewport: { width: W, height: H } });
await ctx.addInitScript(`(() => {
  let T = 0, id = 0, cbs = [];
  performance.now = () => T;
  window.requestAnimationFrame = (cb) => (cbs.push([++id, cb]), id);
  window.cancelAnimationFrame = (i) => { cbs = cbs.filter(([j]) => j !== i); };
  window.__step = (t) => { T = t; const q = cbs; cbs = []; for (const [, f] of q) f(T); };
})();\n${A.init ?? ""}`);
// the site's own script, fetched through the browser context (cookies, headers), with the hook appended
if (A.patch) await ctx.route(A.patch.match, async (r) => r.fulfill({ contentType: "text/javascript", body: (await (await r.fetch()).text()) + A.patch.append }));
const page = await ctx.newPage(), cdp = await ctx.newCDPSession(page);
page.on("popup", (p) => p.close().catch(() => {}));
await page.goto(A.url, { waitUntil: "load" });
// A drawn cursor (screenshots have none) and a click ring; hidden under pointer lock, as in a real browser.
await page.evaluate(() => {
  const d = document.createElement("div"), r = document.createElement("div");
  d.style.cssText = "position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none";
  d.innerHTML = '<svg width="30" height="40" viewBox="0 0 24 32" style="filter:drop-shadow(0 2px 2px rgba(0,0,0,.55))"><path d="M2 2 V25 L8 19.5 L12.2 29.5 L16.2 27.8 L12 18 L20 18 Z" fill="#fff" stroke="#000" stroke-width="2" stroke-linejoin="round"/></svg>';
  r.style.cssText = "position:fixed;left:0;top:0;z-index:2147483646;pointer-events:none;width:40px;height:40px;margin:-20px 0 0 -20px;border-radius:50%;border:3px solid #fff;opacity:0";
  document.body.append(r, d);
  window.__cur = (x, y, age) => {
    d.style.display = document.pointerLockElement ? "none" : "block";
    d.style.transform = `translate(${x}px,${y}px)`;
    r.style.opacity = age >= 0 && age <= 0.45 ? String(0.8 * (1 - age / 0.45)) : "0";
    r.style.transform = `translate(${x}px,${y}px) scale(${0.3 + (1.1 * age) / 0.45})`;
  };
});

// Cursor glide: a damped spring toward the goal, solved in closed form; the same point drives the real mouse.
const sw = 2 * Math.PI * 1.7, sz = 0.82, swd = sw * Math.sqrt(1 - sz * sz);
const solve = (x0, v0, g, t) => {
  const a = x0 - g, b = (v0 + sz * sw * a) / swd, e = Math.exp(-sz * sw * t), c = Math.cos(swd * t), s = Math.sin(swd * t);
  return [g + e * (a * c + b * s), e * (-sz * sw * (a * c + b * s) + swd * (-a * s + b * c))];
};
let cur = { x: W * 0.86, y: H * 0.9, vx: 0, vy: 0, gx: W * 0.86, gy: H * 0.9, t0: 0 };
const curAt = (t) => [solve(cur.x, cur.vx, cur.gx, t - cur.t0), solve(cur.y, cur.vy, cur.gy, t - cur.t0)];

const log = { track: [], steps: [], clicks: [], rooms: [], doors: [], marks: [] };
let F = 0, T = 0, clickT = -9, mouse = null, locked = false, wDown = false, pose = null, walked = 0, room = null;
const now = () => F * DT;
const mm = (x, y) => cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0 });
const key = async (down) => { if (down !== wDown) { await (down ? page.keyboard.down(A.forwardKey ?? "w") : page.keyboard.up(A.forwardKey ?? "w")); wDown = down; } };
process.on("exit", () => fs.writeFileSync(`${OUT}/log${FROM || TO < Infinity ? `.${FROM}-${TO}` : ""}.json`, JSON.stringify({ ...log, frames: F, fps: 1 / DT })));

async function frame(o) {
  const [[x], [y]] = curAt(now());
  if (!locked && (!mouse || Math.round(x) !== mouse[0] || Math.round(y) !== mouse[1])) { mouse = [Math.round(x), Math.round(y)]; await mm(...mouse); }
  if (o) { // mouse-look in whole pixels toward the controller's view, and the forward key for the duty fraction
    const dx = Math.round(wrap(o.yaw - pose.yaw) / radPerPx), dy = Math.round(-(o.pitch - pose.pitch) / radPerPx);
    if (dx || dy) { mouse = [mouse[0] + dx, mouse[1] + dy]; await mm(...mouse); }
    if (o.f > 0.999 || (o.f > 0.001 && !A.move)) await key(true);
    else if (o.f > 0.001) { await key(true); await page.evaluate(([m, d]) => window[m](d), [A.move, o.f * o.clock * DT]); await key(false); }
    else await key(false);
  }
  T += DT * (o?.clock ?? 1);
  const prev = pose;
  pose = await page.evaluate(([px, py, age, t, expr]) => { window.__cur(px, py, age); window.__step(t); return eval(expr); }, [x, y, now() - clickT, T * 1000, A.pose]);
  if (F >= FROM && F < TO) fs.writeFileSync(`${OUT}/${String(F).padStart(5, "0")}.png`, Buffer.from((await cdp.send("Page.captureScreenshot", { format: "png" })).data, "base64"));
  if (prev && prev.room === pose.room && (walked += Math.hypot(pose.x - prev.x, pose.z - prev.z)) > 0.75) { walked -= 0.75; log.steps.push(now()); }
  if (prev && prev.room !== pose.room) { log.doors.push(now()); if (room) { room.b = now(); log.rooms.push(room); } room = pose.room ? { a: now(), kind: pose.room } : null; }
  log.track.push([+pose.x.toFixed(3), +pose.z.toFixed(3), +pose.yaw.toFixed(4), +pose.pitch.toFixed(4), pose.room ?? null, +(pose.eye ?? 0).toFixed(3)]);
  if (++F >= TO) { await browser.close(); process.exit(0); }
  return prev;
}
const sleep = async (s) => { for (let n = Math.round(s / DT); n > 0; n--) await frame(); };
const api = {
  page, W, H, sleep, log,
  async glide(x, y, s = 1.1) { const [[cx, vx], [cy, vy]] = curAt(now()); cur = { x: cx, vx, y: cy, vy, gx: x, gy: y, t0: now() }; await sleep(s); },
  async click() {
    const [x, y] = curAt(now()).map(([v]) => Math.round(v));
    clickT = now(); log.clicks.push(now());
    for (const type of ["mousePressed", "mouseReleased"]) await cdp.send("Input.dispatchMouseEvent", { type, x, y, button: "left", buttons: type === "mousePressed" ? 1 : 0, clickCount: 1 });
  },
};
await frame();
if (pose.room) room = { a: 0, kind: pose.room }; // a walk that starts inside a room
await A.start(api); // intro: e.g. sound on, then one click on a plain canvas cell (no sign, no link) to lock the pointer
await sleep(0.1);
if (!(await page.evaluate(() => !!document.pointerLockElement))) throw new Error("pointer lock failed: click a plain canvas cell");
locked = true; mouse = curAt(now()).map(([v]) => Math.round(v));
const legs = await A.legs(), ctl = new Ctl(legs, { keySpeed: A.keySpeed });
for (let li = -1, start = 0; !ctl.done;) {
  if (ctl.li !== li) { li = ctl.li; start = F; log.marks.push([now(), legs[li].name]); }
  // a leg that never ends (a door trigger the route misses) fails instead of capturing forever
  if (F - start > 90 / DT) throw new Error(`leg "${legs[li].name}" ran 90 s without ending: check its route and push point`);
  const prev = await frame(ctl.step(pose));
  if (prev.room !== pose.room) { await key(false); ctl.crossed(pose); } // the site moved you through a door
}
await key(false);
log.marks.push([now(), "end"]);
await sleep(1.2);
if (room) { room.b = now(); log.rooms.push(room); } // and one that ends inside
await browser.close();
