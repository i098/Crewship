// Runs the WebKit browser checks documented in README.md. Run harbor/build.py first.
import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import { webkit, devices } from "playwright";

const dist = new URL("dist/", import.meta.url);
const browser = await webkit.launch();
const errors = [];
for (const [name, width, height, touch, scale = 1] of [
  ["desktop", 1440, 900, false],
  ["iphone15pro", 393, 852, true],
  ["portrait", 390, 844, true],
  ["landscape", 844, 390, true],
  ["narrow-portrait", 320, 568, true, 1.15 ** 6],
  ["narrow-landscape", 568, 320, true, 1.15 ** 6],
  ["short-landscape", 568, 256, true, 1.15 ** 6],
  ["shortest-landscape", 568, 192, true, 1.15 ** 6]
]) {
const page = await browser.newPage({
  ...(touch ? devices["iPhone 15 Pro"] : {}),
  viewport: { width, height }
});
const expectedInsets = touch ? (width > height ? [0, 47, 21, 47] : [47, 0, 34, 0]) : [0, 0, 0, 0];
page.on("pageerror", (e) => errors.push(`uncaught: ${e.message}`));
page.on("crash", () => errors.push("the page crashed"));
page.on("console", (m) => m.type() === "error" && errors.push(`console: ${m.text()}`));
await page.addInitScript(() => {
  const fillText = CanvasRenderingContext2D.prototype.fillText;
  window.longest = 0;
  CanvasRenderingContext2D.prototype.fillText = function (text, ...rest) {
    window.longest = Math.max(window.longest, text.length);
    return fillText.call(this, text, ...rest);
  };
});
await page.context().route("**/*", async (route) => {
  const url = new URL(route.request().url());
  if (url.origin !== "http://harbor.test") {
    await route.fulfill({ body: "<title>Link destination</title>", contentType: "text/html" });
    return;
  }
  const path = url.pathname.slice(1) || "index.html";
  const type = { html: "text/html", js: "text/javascript", css: "text/css" }[path.split(".").pop()];
  if (path === "harbor.js") {
    // Force slow frames to check that the exterior grid and projection stay fixed.
    const source = await readFile(new URL(path, dist), "utf8");
    return route.fulfill({ contentType: type, body: source + `
["top", "right", "bottom", "left"].forEach((side, n) => stage.style.setProperty("--safe-" + side, ${JSON.stringify(expectedInsets)}[n] + "px"));
const drawPopup = drawSign;
drawSign = function() {
  window.signGlyphs = 0;
  window.highlightedHref = null;
  const fill = ctx.fillText;
  ctx.fillText = function(text, ...args) {
    window.signGlyphs += text.trim().length;
    if (text.startsWith("[") && ctx.fillStyle === COLORS.l) window.highlightedHref = document.activeElement.href;
    return fill.call(this, text, ...args);
  };
  try { drawPopup(); } finally { ctx.fillText = fill; }
};
window.frames = [];
window.introClocks = [];
window.firstFrameBlack = false;
window.lateMeasures = 0;
const measureGrid = measure;
measure = function() {
  if (window.frames.length) window.lateMeasures++;
  measureGrid();
  if (${scale} !== 1) {
    cellH *= ${scale};
    ctx.font = cellH + "px " + MONO;
    cellW = ctx.measureText("M").width;
    cols = Math.floor(stage.clientWidth / cellW);
    rows = Math.floor(stage.clientHeight / cellH);
    padX = (stage.clientWidth - cols * cellW) / 2;
    padY = (stage.clientHeight - rows * cellH) / 2;
    G = new Array(cols * rows); C = new Array(cols * rows);
    ID = new Int32Array(cols * rows); D = new Float32Array(cols * rows); SP = new Array(cols * rows);
  }
};
const renderScene = render;
render = function() {
  const start = performance.now();
  renderScene();
  if (!window.frames.length) {
    const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    window.firstFrameBlack = pixels.every((value, i) => i % 4 === 3 || value === 0);
  }
  if (introProgress < 1) window.introClocks.push(T);
  window.frames.push([cols, rows, cellW, cellH, cam.tanH, cam.tanV, canvas.width, canvas.height]);
  while (performance.now() - start < 25) {}
};
let signCheckWidth = Infinity;
const fitSign = signFit;
signFit = (at, i0, j0, i1, j1, mode, ...options) => fitSign(at, i0, j0, Math.min(i1, i0 + signCheckWidth), j1, mode, ...options);
window.harborCheck = {
  place(x, z, yaw) { Object.assign(me, {x, z, yaw, pitch: 0}); moved = dirty = true; },
  state() { return {inside: insideHouse, x: me.x, z: me.z, yaw: me.yaw, clear: !blocked(me.x, me.z, floorAt(me.x, me.z))}; },
  ids: ORDER,
  postView(id, angle, distance, pitch, turn) {
    const posts = world.filter(s => s.spot === id && s.bb[3] - s.bb[0] < 0.16 && s.bb[4] - s.bb[1] >= 1);
    const x = posts.reduce((n, s) => n + (s.bb[0] + s.bb[3]) / 2, 0) / posts.length;
    const z = posts.reduce((n, s) => n + (s.bb[2] + s.bb[5]) / 2, 0) / posts.length;
    Object.assign(me, { x: x + Math.sin(angle) * distance, z: z - Math.cos(angle) * distance, yaw: -angle + turn, pitch });
    me.eye = floorAt(me.x, me.z) + 1.6;
    moved = true; jumped = id; render();
    const screen = (x, y, z) => {
      const p = [x - cam.x, y - cam.y, z - cam.z];
      const dot = v => v.reduce((n, c, k) => n + c * p[k], 0), depth = dot(cam.f);
      return [(dot(cam.r) / depth / cam.tanH + 1) * cols / 2, (1 - dot(cam.u) / depth / cam.tanV) * rows / 2];
    };
    return { ...this.bounds(), cols, tops: posts.map(s => screen(
      (s.bb[0] + s.bb[3]) / 2, s.bb[4], (s.bb[2] + s.bb[5]) / 2)) };
  },
  go(id) {
    signCheckWidth = Infinity;
    if (id) go(id);
    else { moved = false; jumped = null; show(null); }
    render(); dirty = false;
  },
  stack() {
    this.go(null);
    signCheckWidth = 24;
    render();
    return this.bounds();
  },
  focusState() {
    step(1 / 60);
    render();
    return {
      map: mapMode, pending: walkPath.length, destination: walkTo, target,
      drawn: !!signBox && window.signGlyphs > 0, highlighted: window.highlightedHref,
      href: document.activeElement.href,
      x: stage.scrollLeft, y: stage.scrollTop
    };
  },
  focusLink(selector, pendingId) {
    walkPath = [[me.x, me.z]];
    walkTo = pendingId;
    document.querySelector(selector).focus();
    return this.focusState();
  },
  bounds() {
    return {
      box: signBox,
      glyphs: window.signGlyphs,
      x: padX + signBox.i * cellW, y: padY + signBox.j * cellH,
      width: signBox.w * cellW, height: signBox.h * cellH,
      cellH, dpr: canvas.width / stage.clientWidth,
      safe: [safe.top, safe.right, safe.bottom, safe.left], screenWidth: stage.clientWidth, screenHeight: stage.clientHeight,
      pad: pad.offsetParent ? pad.getBoundingClientRect().toJSON() : null,
      map: mapBox ? { x: padX + mapBox.oi * cellW, y: padY + mapBox.oj * cellH,
        width: mapBox.w * cellW, height: mapBox.h * cellH } : null,
      links: signLinks.map(({start, height, left = 1, width = signBox.w - 2, a}) => ({
        x: padX + (signBox.i + left + width / 2) * cellW,
        y: padY + (signBox.j + 1 + start + height / 2) * cellH,
        href: a.href, height: height * cellH,
        hit: signHit(padX + (signBox.i + left + width / 2) * cellW,
          padY + (signBox.j + 1 + start + height / 2) * cellH)?.href,
        top: padY + (signBox.j + 1 + start) * cellH,
        bottom: padY + (signBox.j + 1 + start + height) * cellH,
        left: padX + (signBox.i + left) * cellW,
        right: padX + (signBox.i + left + width) * cellW
      }))
    };
  }
};
stage.addEventListener("pointerdown", () => { if (padId !== null) for (let i = 0; i < 8; i++) step(0.02); });
` });
  }
  await route.fulfill({ body: await readFile(new URL(path, dist)), contentType: type });
});
await page.goto("http://harbor.test/");
try {
  await page.waitForFunction(() => window.frames?.length >= 30, null, { timeout: 30000 });
} catch (e) {
  errors.push(`the scene did not draw 30 frames: ${e.message}`);
}
if (!page.isClosed() && !errors.length) {
  const { scene, longest } = await page.evaluate(() => ({ scene: !document.getElementById("stage").hidden, longest: window.longest }));
  if (!scene) errors.push("the scene fell back to the plain page");
  if (touch && longest !== 1) errors.push(`fillText drew ${longest} glyphs at once; touch devices must draw one at a time`);
  const { frames, lateMeasures } = await page.evaluate(() => ({ frames: window.frames, lateMeasures: window.lateMeasures }));
  if (frames.some((frame) => frame.some((value, i) => value !== frames[0][i]))) errors.push("the grid or field of view changed after the first draw");
  if (lateMeasures) errors.push(`the canvas layout changed ${lateMeasures} times after the first draw`);
  const { firstFrameBlack, introClocks } = await page.evaluate(() => ({ firstFrameBlack: window.firstFrameBlack, introClocks: window.introClocks }));
  if (!firstFrameBlack) errors.push("the first intro frame was not fully black");
  if (introClocks.length < 2 || introClocks.at(-1) <= introClocks[0]) errors.push("the scene froze during the intro");
}
if (touch && !page.isClosed() && !errors.length) {
await page.evaluate(() => window.harborCheck.place(-5, 20.6, 0));
await page.locator("#pad").waitFor({ state: "visible" });
const pad = await page.locator("#pad").boundingBox();
const padX = pad.x + pad.width / 2, padY = pad.y + 2;
await page.touchscreen.tap(padX, padY);
await page.waitForTimeout(2000);
const room = await page.evaluate(() => window.harborCheck.state());
await page.keyboard.down("ArrowRight");
await page.waitForTimeout(2000);
await page.keyboard.up("ArrowRight");
await page.waitForTimeout(100);
const painted = await page.evaluate(() => {
  const canvas = document.getElementById("scene");
  return canvas.getContext("2d").getImageData(canvas.width / 2, canvas.height / 2, 1, 1).data[3] === 255;
});
if (!painted) errors.push("the idle room cleared after looking around");
if (!room.inside || !room.clear) errors.push("touch walking did not enter a clear room");
const indoor = await page.evaluate(() => {
  const before = window.harborCheck.state();
  const focus = window.harborCheck.focusLink('#manifest [data-spot="docsboard"] a', "mast");
  return { before, after: window.harborCheck.state(), focus };
});
assert(indoor.before.inside && indoor.after.inside, `${name}: manifest focus left the house`);
assert.deepEqual([indoor.after.x, indoor.after.z], [indoor.before.x, indoor.before.z],
  `${name}: manifest focus moved the player`);
assert.equal(indoor.focus.target, "docsboard", `${name}: indoor manifest focus selected the wrong sign`);
assert(indoor.focus.drawn, `${name}: indoor focused sign did not draw`);
const indoorBounds = await page.evaluate(() => window.harborCheck.bounds());
assert.equal(indoorBounds.map, null, `${name}: indoor sign retained a map exclusion rectangle`);
assert.equal(indoorBounds.links.length, 1, `${name}: indoor sign link is missing`);
for (const link of indoorBounds.links) {
  assert.equal(link.hit, link.href, `${name}: indoor sign link is not hit-testable`);
  assert(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y) === document.getElementById("scene"),
    { x: link.x, y: link.y }), `${name}: indoor sign tap point is covered by an HTML control`);
}
await page.evaluate(() => {
  const {x, z} = window.harborCheck.state();
  window.harborCheck.place(x, z, Math.PI);
});
await page.touchscreen.tap(padX, padY);
await page.touchscreen.tap(padX, padY);
await page.waitForTimeout(1000);
const outside = await page.evaluate(() => window.harborCheck.state());
if (outside.inside || !outside.clear || outside.z >= 20.75 || outside.yaw !== Math.PI) errors.push("touch walking did not return outside facing away");
}
if (!page.isClosed() && !errors.length) {
await page.emulateMedia({ reducedMotion: "reduce" });
const overlaps = (a, b) => b && a.x < b.x + b.width && a.x + a.width > b.x
  && a.y < b.y + b.height && a.y + a.height > b.y;
if (["desktop", "iphone15pro", "landscape"].includes(name)) {
  for (const id of ["how", "docsboard", "mailbox"]) {
    const views = [[0, 5.5, 0, 0], [-0.6, 5, 0.1, 0.08], [0.6, 8, -0.1, -0.08]];
    if (id === "docsboard") views.push([-1.0653, Math.hypot(3.225, 1.785), 0, 0]);
    for (const view of views) {
      const bounds = await page.evaluate(({ id, view }) => window.harborCheck.postView(id, ...view), { id, view });
      if (bounds.tops.some(([i]) => i < 1 || i >= bounds.cols - 1)) {
        assert(bounds.glyphs > 0 && !bounds.box.seated, `${name}/${id}: off-screen supports must retain a fallback sign`);
        continue;
      }
      const bottom = bounds.box.j + bounds.box.h - 1;
      assert(bounds.box.seated && bottom === Math.max(...bounds.tops.map(([, j]) => Math.floor(j))),
        `${name}/${id}/${view}: board bottom misses its lowest support: ${JSON.stringify(bounds)}`);
      for (const [i, j] of bounds.tops) {
        assert(Math.floor(j) <= bottom, `${name}/${id}/${view}: a gap separates the board and its support`);
        assert(Math.floor(i) >= bounds.box.i && Math.floor(i) < bounds.box.i + bounds.box.w,
          `${name}/${id}/${view}: board misses its post horizontally`);
      }
    }
    for (const view of [[0, 0.5, 0, 0], [0, 8, 1.1, 0]]) {
      const bounds = await page.evaluate(({ id, view }) => window.harborCheck.postView(id, ...view), { id, view });
      assert(bounds.glyphs > 0 && !bounds.box.seated, `${name}/${id}: an unfit or off-screen post must retain its fallback sign`);
      assert(bounds.links.every(link => link.hit === link.href), `${name}/${id}: fallback links are not hit-testable`);
    }
  }
}
for (const id of [null, ...await page.evaluate(() => window.harborCheck.ids)]) {
  const timeout = setTimeout(() => {
    console.error(`${name}/${id}: sign rendering stalled`);
    process.exit(1);
  }, 10000);
  const bounds = await page.evaluate((id) => {
    window.harborCheck.go(id);
    return window.harborCheck.bounds();
  }, id);
  clearTimeout(timeout);
  assert.deepEqual(bounds.safe, expectedInsets, `${name}/${id}: safe insets were not measured`);
  assert(bounds.glyphs > 0, `${name}/${id}: sign did not draw`);
  const [top, right, bottom, left] = bounds.safe;
  assert(bounds.x >= left && bounds.y >= top, `${name}/${id}: sign starts outside the safe area`);
  assert(bounds.x + bounds.width <= bounds.screenWidth - right, `${name}/${id}: sign extends past the safe area: ${JSON.stringify(bounds)}`);
  assert(bounds.y + bounds.height <= bounds.screenHeight - bottom, `${name}/${id}: sign extends below the safe area`);
  if (!bounds.box.overlay) {
    assert(!overlaps(bounds, bounds.map), `${name}/${id}: sign covers the map`);
    assert(!overlaps(bounds, bounds.pad), `${name}/${id}: sign covers the move pad`);
  }
  assert.equal(bounds.links.length, id ? 1 : 3, `${id}: a sign link is missing`);
  if (touch) assert(bounds.dpr <= 2, `${name}/${id}: touch canvas exceeds DPR 2`);
  if (name === "iphone15pro" && !id) {
    // Title, description, one blank row, one link row, and two frame rows.
    assert(bounds.height <= 6 * bounds.cellH, `${name}: welcome sign has excess vertical spacing`);
  }
  for (const link of bounds.links) {
    assert.equal(link.hit, link.href, `${name}/${id}: link is not hit-testable`);
    assert(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y) === document.getElementById("scene"),
      { x: link.x, y: link.y }), `${name}/${id}: link tap point is covered by an HTML control`);
    const stacked = bounds.links.some((other) => other.y !== link.y);
    if (touch) assert(link.height >= (stacked ? 24 : 44), `${name}/${id}: touch link is too short`);
    if (touch) {
      assert(link.top >= top && link.bottom <= bounds.screenHeight - bottom, `${name}/${id}: link hit padding extends outside the safe area`);
      const hitBox = { x: link.left, y: link.top, width: link.right - link.left, height: link.height };
      assert(!overlaps(hitBox, bounds.pad), `${name}/${id}: link hit padding covers the move pad`);
      if (!bounds.box.overlay) assert(!overlaps(hitBox, bounds.map), `${name}/${id}: link hit padding covers the map`);
    } else assert(link.top >= bounds.y && link.bottom <= bounds.y + bounds.height, `${id}: link region extends outside the frame`);
    assert(link.left >= bounds.x && link.right <= bounds.x + bounds.width, `${id}: link region extends outside the frame`);
    const popup = page.waitForEvent("popup");
    if (touch) await page.touchscreen.tap(link.x, link.y);
    else await page.mouse.click(link.x, link.y);
    const opened = await popup;
    await opened.waitForLoadState();
    assert.equal(opened.url(), link.href, `${id}: grid tap opened the wrong link`);
    await opened.close();
  }
  for (let n = 0; n < bounds.links.length; n++) {
    const focus = await page.evaluate(({ n, id }) =>
      window.harborCheck.focusLink("#card a:nth-of-type(" + (n + 1) + ")", window.harborCheck.ids.find((other) => other !== id)),
      { n, id });
    assert.equal(focus.x, 0, `${name}/${id}: keyboard focus scrolled the stage horizontally`);
    assert.equal(focus.y, 0, `${name}/${id}: keyboard focus scrolled the stage vertically`);
    assert.equal(focus.pending, 0, `${name}/${id}: card focus retained an auto-walk`);
    assert.equal(focus.destination, null, `${name}/${id}: card focus retained an arrival selection`);
    assert(focus.drawn, `${name}/${id}: focused sign did not draw`);
    assert.equal(focus.highlighted, focus.href, `${name}/${id}: focused sign link was not highlighted`);
  }
}
if (name === "iphone15pro") {
  const stacked = await page.evaluate(() => window.harborCheck.stack());
  assert(stacked.links.every((link, n) => !n || link.y > stacked.links[n - 1].y), "narrow sign did not stack its links");
  for (const [n, link] of stacked.links.entries()) {
    assert(link.height >= 24, "stacked touch target is shorter than 24px");
    if (n) assert(link.top >= stacked.links[n - 1].bottom - 0.001, "stacked touch targets overlap");
    for (const offset of [-6, 6]) {
      assert(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y) === document.getElementById("scene"),
        { x: link.x, y: link.y + offset }), "stacked tap point is covered by an HTML control");
      const popup = page.waitForEvent("popup");
      await page.touchscreen.tap(link.x, link.y + offset);
      const opened = await popup;
      await opened.waitForLoadState();
      assert.equal(opened.url(), link.href, "off-center stacked tap opened the wrong link");
      await opened.close();
    }
  }
  await page.evaluate(() => window.harborCheck.go(null));
}
for (const id of await page.evaluate(() => window.harborCheck.ids)) {
  await page.locator("#stage").focus();
  await page.keyboard.press("m");
  await page.keyboard.press("m");
  const focus = await page.evaluate((id) =>
    window.harborCheck.focusLink('#manifest [data-spot="' + id + '"] a',
      window.harborCheck.ids.find((other) => other !== id)), id);
  assert.equal(focus.map, 0, `${name}/${id}: manifest focus did not close the full map`);
  assert.equal(focus.pending, 0, `${name}/${id}: manifest focus retained an auto-walk`);
  assert.equal(focus.destination, null, `${name}/${id}: manifest focus retained an arrival selection`);
  assert.equal(focus.target, id, `${name}/${id}: arrival replaced the focused sign`);
  assert(focus.drawn, `${name}/${id}: focused sign did not draw`);
  assert.equal(focus.highlighted, focus.href, `${name}/${id}: manifest link did not highlight its sign`);
  assert.equal(focus.x, 0, `${name}/${id}: manifest focus scrolled the stage horizontally`);
  assert.equal(focus.y, 0, `${name}/${id}: manifest focus scrolled the stage vertically`);
}
await page.locator('#manifest [data-spot="docsboard"] a').focus();
const keyboardPopup = page.waitForEvent("popup");
await page.keyboard.press("Enter");
const opened = await keyboardPopup;
await opened.waitForLoadState();
assert.equal(opened.url(), "https://github.com/i098/Crewship#features");
await opened.close();
await page.locator("#stage").focus();
const stagePopup = page.waitForEvent("popup");
await page.keyboard.press("Enter");
const stageOpened = await stagePopup;
await stageOpened.waitForLoadState();
assert.equal(stageOpened.url(), "https://github.com/i098/Crewship#features");
await stageOpened.close();
if (!page.isClosed()) {
  const { scene, longest } = await page.evaluate(() => ({ scene: !document.getElementById("stage").hidden, longest: window.longest }));
  if (!scene) errors.push("the scene fell back to the plain page");
  if (touch && longest !== 1) errors.push(`fillText drew ${longest} glyphs at once; touch devices must draw one at a time`);
}
}
await page.close();
}
await browser.close();
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log("harbor: desktop and WebKit iPhone portrait/landscape checks passed");
