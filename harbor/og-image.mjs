// See README.md#link-preview for image regeneration and its Playwright requirements.
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

const dist = new URL("dist/", import.meta.url);
const pub = new URL("public/", import.meta.url);
// x, z, eye height, yaw, pitch: south-east of the ship, so the moon, the ship and the house all fit.
const POSE = [22, -26, 7, -0.45, 0];
// The scene renders at 1500x788 and the preview keeps its middle 1200x630, a slightly narrower view.
const HOOK = `
window.ogPose = (x, z, eye, yaw, pitch) => {
  show = () => { target = null; card.replaceChildren(); };
  minimap = () => { MAPCELLS.clear(); mapBox = null; };
  const base = render;
  render = () => { Object.assign(me, { x, z, eye, yaw, pitch }); shadows = true; base(); window.ogDrawn = true; };
  dirty = true;
};
window.ogReady = () => cols > 0 && introProgress === 1;`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 750, height: 394 }, deviceScaleFactor: 2, reducedMotion: "reduce" });
await page.route("http://harbor.test/**", async (route) => {
  const path = new URL(route.request().url()).pathname.slice(1) || "index.html";
  const type = { html: "text/html", js: "text/javascript", css: "text/css" }[path.split(".").pop()];
  const body = await readFile(new URL(path, dist)).catch(() => null);
  if (!body) return route.fulfill({ status: 404, body: "" });
  await route.fulfill({ body: path === "harbor.js" ? body + HOOK : body, contentType: type });
});
await page.goto("http://harbor.test/");
await page.waitForFunction(() => window.ogReady?.());
await page.addStyleTag({ content: "#pad { display: none !important; }" });
await page.evaluate((pose) => window.ogPose(...pose), POSE);
await page.waitForFunction(() => window.ogDrawn);
const scene = (await page.locator("#scene").screenshot()).toString("base64");

const tagline = (await readFile(new URL("index.html", dist), "utf8")).match(/property="og:description" content="([^"]+)"/)[1];
const card = await browser.newPage({ viewport: { width: 1200, height: 630 } });
await card.setContent(`<!doctype html><style>
  body { margin: 0; width: 1200px; height: 630px; position: relative; overflow: hidden; background: #060a14; }
  img { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); filter: brightness(1.6) saturate(1.15); }
  .shade { position: absolute; inset: 0; background: radial-gradient(ellipse 52% 56% at 80% 80%, #060a14fa 0%, #060a14f0 45%, #060a14b0 72%, #060a1400 100%); }
  .text { position: absolute; right: 56px; bottom: 46px; text-align: right; color: #f2f5fc; }
  h1 { margin: 0; font: 700 100px/1 "Liberation Mono", monospace; }
  p { margin: 16px 0 0; font: 400 30px/1.3 "Liberation Mono", monospace; color: #d3dcef; }
  </style><img src="data:image/png;base64,${scene}"><div class="shade"></div>
  <div class="text"><h1>Crewship</h1><p>${tagline.replace(" - ", "<br>- ")}</p></div>`);
await card.screenshot({ path: new URL("og.png", pub).pathname });

// iOS rounds the corners itself, so the icon fills the whole square.
const icon = await browser.newPage({ viewport: { width: 180, height: 180 } });
await icon.setContent(`<body style="margin:0;background:#0a0f1c">${await readFile(new URL("favicon.svg", pub), "utf8")}</body>`);
await icon.locator("svg").evaluate((svg) => svg.setAttribute("width", 180));
await icon.screenshot({ path: new URL("apple-touch-icon.png", pub).pathname });
await browser.close();
console.log("harbor: wrote public/og.png and public/apple-touch-icon.png");
