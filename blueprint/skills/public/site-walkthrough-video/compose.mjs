#!/usr/bin/env node
// Frame the capture as a Safari window (macOS 26, dark) on a desktop wallpaper, with a spring entrance; 1920x1080
// at 60 fps, H.264 + AAC. The toolbar copies a real 1x Safari screenshot (a 1323 px window: traffic lights, sidebar
// and back/forward pills, centred URL field, share/+/tabs) scaled to the 1700 px window, drawn at 2x and downsampled.
// usage: bun compose.mjs FRAMES_DIR OUT.mp4 AUDIO.wav TITLE       frames are FRAMES_DIR/NNNNN.png at 1700x920
// SF_FONT=/path/SFNS.ttf uses SF Pro (Apple's licence: a Mac's own copy); otherwise the system UI font.
// The page's colours pass through unchanged: no curves or shadow lift (a lift flattens contrast and looks washed out).
import { execFileSync } from "child_process";
import fs from "fs";
import { env } from "process";
import { chromium } from "playwright-core";

const [dir, out, audio, title] = process.argv.slice(2);
const names = fs.readdirSync(dir).filter((f) => /^\d{5}\.png$/.test(f)).sort(), frames = names.length;
if (!frames) throw new Error(`no NNNNN.png frames in ${dir}`);
const first = +names[0].slice(0, 5);
// ffmpeg stops quietly at the first missing frame, so a gap (a failed capture segment) must stop the compose
if (+names[frames - 1].slice(0, 5) - first + 1 !== frames) throw new Error(`${dir}: frames ${first}..${names[frames - 1]} have gaps`);
const A = `${dir}/_frame`, k = 1700 / 1323, u = (v) => +(v * k).toFixed(3);
const P = 160, WW = 1700, TB = Math.round(u(52)), WH = TB + 920, R = u(21.5), CH = WH + 2 * P + (WH % 2); // even height
fs.mkdirSync(A, { recursive: true });
const b = await chromium.launch();
const face = env.SF_FONT ? `@font-face{font-family:SF;src:url(file://${env.SF_FONT})}` : "";
const shot = async (html, w, h, file, transparent) => {
  const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
  await p.setContent(`<style>${face}*{box-sizing:border-box;margin:0}body{width:${w}px;height:${h}px;overflow:hidden;${transparent ? "background:transparent" : ""}}</style>${html}`);
  await p.evaluate(() => document.fonts.ready);
  await p.screenshot({ path: `${A}/2x-${file}`, omitBackground: !!transparent });
  await p.close();
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", `${A}/2x-${file}`, "-vf", "scale=iw/2:ih/2:flags=lanczos", `${A}/${file}`]);
};
await shot(`<div style="width:1920px;height:1080px;position:relative;background:#14122e;overflow:hidden">
 <div style="position:absolute;inset:-200px;filter:blur(90px);background:radial-gradient(40% 45% at 18% 22%,#6a4cff 0,transparent 70%),
  radial-gradient(38% 42% at 82% 18%,#19b7d6 0,transparent 70%),radial-gradient(45% 50% at 72% 90%,#e0407f 0,transparent 70%),
  radial-gradient(40% 40% at 8% 88%,#2a7bff 0,transparent 70%)"></div>
 <div style="position:absolute;inset:0;background:radial-gradient(120% 100% at 50% 50%,transparent 55%,rgba(5,4,20,.55))"></div></div>`, 1920, 1080, "wallpaper.png");
await shot(`<div style="position:absolute;left:${P}px;top:${P}px;width:${WW}px;height:${WH}px;border-radius:${R}px;background:#000;
  box-shadow:0 ${u(22)}px ${u(60)}px rgba(0,0,0,.5),0 ${u(6)}px ${u(16)}px rgba(0,0,0,.3),0 0 0 ${u(1)}px rgba(120,120,120,.35)"></div>`, WW + 2 * P, CH, "base.png", true);
// toolbar parts, in the screenshot's pixels
const ico = (x, y, w, h, body, color = "#e6e6e6") => `<svg style="position:absolute;left:${u(x)}px;top:${u(y)}px" width="${u(w)}" height="${u(h)}" viewBox="0 0 ${w} ${h}"
  fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
const pill = (x, w) => `<div style="position:absolute;left:${u(x)}px;top:${u(8)}px;width:${u(w)}px;height:${u(36)}px;border-radius:${u(18)}px;background:#191919;box-shadow:inset 0 0 0 ${u(1)}px #2e2e2e"></div>`;
const light = (cx, c) => `<i style="position:absolute;left:${u(cx - 7)}px;top:${u(17.5)}px;width:${u(14)}px;height:${u(14)}px;border-radius:50%;background:${c};box-shadow:inset 0 0 0 ${u(0.5)}px rgba(0,0,0,.25)"></i>`;
await shot(`<div style="position:absolute;left:${P}px;top:${P}px;width:${WW}px;height:${TB}px;border-radius:${R}px ${R}px 0 0;background:#000;overflow:hidden">
  ${light(24.5, "#ff5c5f")}${light(47.5, "#fac801")}${light(70.5, "#37c75a")}${pill(95, 68)}${pill(170, 74)}${pill(394.5, 534)}${pill(1204, 108)}
  ${ico(104.5, 17.5, 21, 16, '<rect x="1" y="1" width="19" height="14" rx="3"/><path d="M7.5 1v14M3.5 4.5h1.5M3.5 7h1.5M3.5 9.5h1.5"/>')}${ico(138.5, 22.5, 10, 6, '<path d="M1 1l4 4 4-4"/>')}
  ${ico(183.5, 17.5, 9, 15, '<path d="M8 1L1.5 7.5 8 14"/>')}<i style="position:absolute;left:${u(206.5)}px;top:${u(15)}px;width:${u(1)}px;height:${u(20)}px;background:#333"></i>${ico(219.5, 17.5, 9, 15, '<path d="M1 1l6.5 6.5L1 14"/>', "#5a5a5a")}
  ${ico(404, 17.5, 13, 15, '<rect x="1" y="1" width="11" height="7" rx="1.5"/><path d="M1 11h11M1 14h7"/>')}
  <span style="position:absolute;left:${u(394.5)}px;width:${u(534)}px;top:${u(7)}px;height:${u(36)}px;display:flex;align-items:center;justify-content:center;font:590 ${u(13)}px/1 SF,-apple-system,system-ui,sans-serif;color:#fff;letter-spacing:${u(-0.2)}px">${title}</span>
  ${ico(885, 18.5, 18, 14, '<path d="M2.5 1h7A1.5 1.5 0 0 1 11 2.5V7a1.5 1.5 0 0 1-1.5 1.5H5.5L3 10.5V8.5h-.5A1.5 1.5 0 0 1 1 7V2.5A1.5 1.5 0 0 1 2.5 1z" stroke-width="1.2"/><path d="M4 6.6l2-4.4 2 4.4M4.7 5.2h2.6" stroke-width="1.1"/><path d="M9.5 5h6A1.5 1.5 0 0 1 17 6.5V10a1.5 1.5 0 0 1-1.5 1.5h-.5v2l-2.6-2H9.5A1.5 1.5 0 0 1 8 10V6.5A1.5 1.5 0 0 1 9.5 5z" fill="#e6e6e6"/><path d="M10.6 7h4.8M13 6.4V7M11.2 10.4L14.6 7.6M11.6 7.9l3.2 2.7" stroke="#191919" stroke-width="1"/>')}
  ${ico(910, 17.5, 12, 15, '<path d="M10.6 8.2A4.9 4.9 0 1 1 7.6 3.3"/><path d="M6.2 1l2 2.2-2.1 2"/>')}
  ${ico(1214.5, 14.5, 16, 20, '<path d="M8 1.5v11M4.8 4.6L8 1.5l3.2 3.1"/><path d="M5 8H3.5A2 2 0 0 0 1.5 10v6.5a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2H11"/>')}
  ${ico(1250.5, 17.5, 15, 15, '<path d="M7.5 1v13M1 7.5h13"/>')}${ico(1284.5, 16.5, 19, 18, '<rect x="5" y="4.5" width="13" height="12.5" rx="2.5"/><path d="M1.5 13V4a2.5 2.5 0 0 1 2.5-2.5h9.5"/>')}
</div>`, WW + 2 * P, CH, "top.png", true);
await shot(`<div style="width:${WW}px;height:920px;background:#000"><div style="width:${WW}px;height:920px;background:#fff;border-radius:0 0 ${R}px ${R}px"></div></div>`, WW, 920, "mask.png");
await b.close();

// Entrance: the window rises 34 px and grows 6 % to rest, an underdamped spring in closed form, per frame.
const w = 2 * Math.PI * 2, z = 0.62, wd = w * Math.sqrt(1 - z * z), K = `exp(-${z * w}*t)*(cos(${wd}*t)+${(z * w) / wd}*sin(${wd}*t))`;
const loop = (f) => ["-loop", "1", "-framerate", "60", "-i", `${A}/${f}`];
const graph = [
  "[0:v]format=rgba[v]", "[4:v]format=gray[m]", "[v][m]alphamerge[vm]",
  `[2:v][vm]overlay=${P}:${P + TB}:format=auto[w1]`, "[w1][3:v]overlay=0:0:format=auto[w]",
  `[w]scale=w='2*trunc(${(WW + 2 * P) / 2}*(1-0.06*${K}))':h='2*trunc(${CH / 2}*(1-0.06*${K}))':eval=frame[ws]`,
  // explicit sRGB -> BT.709 limited-range YUV, tagged: an untagged or implicit (BT.601) conversion looks washed out,
  // most of all on an HDR display
  `[1:v][ws]overlay=x='(W-w)/2':y='(H-h)/2+34*${K}':format=rgb:shortest=1,zscale=rangein=full:primariesin=709:transferin=709:matrix=709:primaries=709:transfer=709:range=limited,format=yuv420p,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709[out]`,
].join(";");
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", "60", "-start_number", String(first), "-i", `${dir}/%05d.png`, ...loop("wallpaper.png"), ...loop("base.png"), ...loop("top.png"), ...loop("mask.png"),
  "-i", audio, "-filter_complex", graph, "-map", "[out]", "-map", "5:a", "-c:a", "aac", "-b:a", "192k", "-t", String(frames / 60), "-r", "60",
  "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", out], { stdio: "inherit" });
fs.rmSync(A, { recursive: true });
console.log(out);
