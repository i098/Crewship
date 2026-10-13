#!/usr/bin/env node
// Frame the capture as a browser window on a desktop wallpaper: soft gradient wallpaper, rounded window with a
// shadow, title bar with traffic lights and a URL pill, a spring entrance; 1920x1080 at 60 fps, H.264 + AAC.
// usage: bun compose.mjs FRAMES_DIR OUT.mp4 AUDIO.wav TITLE       frames are FRAMES_DIR/NNNNN.png at 1700x920
// The page's colours pass through unchanged: no curves or shadow lift (a lift flattens contrast and looks washed out).
import { execFileSync } from "child_process";
import fs from "fs";
import { chromium } from "playwright-core";

const [dir, out, audio, title] = process.argv.slice(2);
const names = fs.readdirSync(dir).filter((f) => /^\d{5}\.png$/.test(f)).sort(), frames = names.length;
if (!frames) throw new Error(`no NNNNN.png frames in ${dir}`);
const first = +names[0].slice(0, 5);
const A = `${dir}/_frame`, P = 160, WW = 1700, WH = 984, R = 18; // window: 1700x920 page + 64 px title bar
fs.mkdirSync(A, { recursive: true });
const b = await chromium.launch();
const shot = async (html, w, h, file, transparent) => {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  await p.setContent(`<style>*{box-sizing:border-box;margin:0}body{width:${w}px;height:${h}px;overflow:hidden;font-family:'DejaVu Sans',sans-serif;${transparent ? "background:transparent" : ""}}</style>${html}`);
  await p.screenshot({ path: `${A}/${file}`, omitBackground: !!transparent });
  await p.close();
};
await shot(`<div style="width:1920px;height:1080px;position:relative;background:#14122e;overflow:hidden">
 <div style="position:absolute;inset:-200px;filter:blur(90px);background:radial-gradient(40% 45% at 18% 22%,#6a4cff 0,transparent 70%),
  radial-gradient(38% 42% at 82% 18%,#19b7d6 0,transparent 70%),radial-gradient(45% 50% at 72% 90%,#e0407f 0,transparent 70%),
  radial-gradient(40% 40% at 8% 88%,#2a7bff 0,transparent 70%)"></div>
 <div style="position:absolute;inset:0;background:radial-gradient(120% 100% at 50% 50%,transparent 55%,rgba(5,4,20,.55))"></div></div>`, 1920, 1080, "wallpaper.png");
await shot(`<div style="position:absolute;left:${P}px;top:${P}px;width:${WW}px;height:${WH}px;border-radius:${R}px;background:#0b0e18;
 box-shadow:0 50px 120px rgba(0,0,0,.55),0 14px 34px rgba(0,0,0,.45)"></div>`, WW + 2 * P, WH + 2 * P, "base.png", true);
const dot = (c) => `<i style="width:18px;height:18px;border-radius:50%;background:${c};display:block"></i>`;
await shot(`<div style="position:absolute;left:${P}px;top:${P}px;width:${WW}px;height:${WH}px;border-radius:${R}px;border:2px solid rgba(255,255,255,.22)"></div>
 <div style="position:absolute;left:${P}px;top:${P}px;width:${WW}px;height:64px;border-radius:${R}px ${R}px 0 0;background:linear-gradient(#262b3d,#1c2030);
  border:2px solid rgba(255,255,255,.22);border-bottom:1px solid #0c0f19;display:flex;align-items:center;padding:0 26px;gap:14px">${dot("#ff5f57")}${dot("#febc2e")}${dot("#28c840")}
  <div style="margin:0 auto;transform:translateX(-30px);width:520px;height:38px;border-radius:10px;background:#0e111b;color:#aab4cf;font-size:21px;line-height:38px;text-align:center">&#128274;&nbsp; ${title}</div></div>`,
  WW + 2 * P, WH + 2 * P, "top.png", true);
await shot(`<div style="width:${WW}px;height:920px;background:#000"><div style="width:${WW}px;height:920px;background:#fff;border-radius:0 0 ${R}px ${R}px"></div></div>`, WW, 920, "mask.png");
await b.close();

// Entrance: the window rises 34 px and grows 6 % to rest, an underdamped spring in closed form, per frame.
const w = 2 * Math.PI * 2, z = 0.62, wd = w * Math.sqrt(1 - z * z), K = `exp(-${z * w}*t)*(cos(${wd}*t)+${(z * w) / wd}*sin(${wd}*t))`;
const loop = (f) => ["-loop", "1", "-framerate", "60", "-i", `${A}/${f}`];
const graph = [
  "[0:v]format=rgba[v]", "[4:v]format=gray[m]", "[v][m]alphamerge[vm]",
  `[2:v][vm]overlay=${P}:${P + 64}:format=auto[w1]`, "[w1][3:v]overlay=0:0:format=auto[w]",
  `[w]scale=w='2*trunc(${(WW + 2 * P) / 2}*(1-0.06*${K}))':h='2*trunc(${(WH + 2 * P) / 2}*(1-0.06*${K}))':eval=frame[ws]`,
  // explicit sRGB -> BT.709 limited-range YUV, tagged: an untagged or implicit (BT.601) conversion looks washed out,
  // most of all on an HDR display
  `[1:v][ws]overlay=x='(W-w)/2':y='(H-h)/2+34*${K}':format=rgb:shortest=1,zscale=rangein=full:primariesin=709:transferin=709:matrix=709:primaries=709:transfer=709:range=limited,format=yuv420p,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709[out]`,
].join(";");
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", "60", "-start_number", String(first), "-i", `${dir}/%05d.png`, ...loop("wallpaper.png"), ...loop("base.png"), ...loop("top.png"), ...loop("mask.png"),
  "-i", audio, "-filter_complex", graph, "-map", "[out]", "-map", "5:a", "-c:a", "aac", "-b:a", "192k", "-t", String(frames / 60), "-r", "60",
  "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", out], { stdio: "inherit" });
fs.rmSync(A, { recursive: true });
console.log(out);
