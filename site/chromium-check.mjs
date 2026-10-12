// Loads the built page (dist/) in Playwright Chromium as a large high-DPR desktop window and fails on
// a fallback to the plain page, a black canvas 3 s after load, a canvas backing store over the size
// limit, or a console error. A browser add-on's failing image and rejected promise are injected:
// errors outside the scene must not show the plain page. Run harbor/build.py first.
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

const dist = new URL("dist/", import.meta.url);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 3651, height: 2160 }, deviceScaleFactor: 2 });
const errors = [];
const addOn = (text) => text.includes("add-on");
page.on("pageerror", (e) => addOn(e.message) || errors.push(`uncaught: ${e.message}`));
page.on("crash", () => errors.push("the page crashed"));
page.on("console", (m) => m.type() === "error" && !addOn(m.text() + m.location().url) && errors.push(`console: ${m.text()}`));
await page.addInitScript(() => addEventListener("DOMContentLoaded", () => {
  const img = document.createElement("img");
  img.src = "/add-on.png";
  img.hidden = true;
  document.body.append(img);
  Promise.reject(new Error("add-on promise"));
}));
await page.route("http://harbor.test/**", async (route) => {
  const path = new URL(route.request().url()).pathname.slice(1) || "index.html";
  const type = { html: "text/html", js: "text/javascript", css: "text/css" }[path.split(".").pop()];
  try {
    await route.fulfill({ body: await readFile(new URL(path, dist)), contentType: type });
  } catch {
    await route.fulfill({ status: 404, body: "" });
  }
});
await page.goto("http://harbor.test/");
await page.waitForTimeout(3000);
if (!page.isClosed()) {
  const { scene, width, height, lit } = await page.evaluate(() => {
    const canvas = document.getElementById("scene");
    const small = document.createElement("canvas");
    small.width = 160;
    small.height = 90;
    const sctx = small.getContext("2d");
    if (canvas.width && canvas.height) sctx.drawImage(canvas, 0, 0, 160, 90);
    const pixels = sctx.getImageData(0, 0, 160, 90).data;
    return {
      scene: !document.getElementById("stage").hidden,
      width: canvas.width,
      height: canvas.height,
      lit: pixels.some((value, i) => i % 4 !== 3 && value > 0),
    };
  });
  if (!scene) errors.push("the scene fell back to the plain page");
  if (width * height > 4096 * 4096) errors.push(`the canvas backing store is ${width}x${height}, over 4096x4096 pixels`);
  if (!lit) errors.push("the canvas was still black 3 s after load");
}
await browser.close();
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log("harbor: Chromium desktop high-DPR check passed");
