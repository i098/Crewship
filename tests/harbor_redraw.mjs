// Run through the browser harness after building and serving harbor/dist:
// await tab.run(async ({ page }) => {
//   const { checkRedraw } = await import(process.cwd() + '/tests/harbor_redraw.mjs');
//   return await checkRedraw(page, 'http://127.0.0.1:8317');
// });
import assert from 'node:assert/strict';

export async function checkRedraw(page, origin) {
  const source = await (await fetch(`${origin}/harbor.js`)).text();
  await page.setCacheEnabled(false);
  await page.setRequestInterception(true);
  const intercept = request => {
    if (request.url() !== `${origin}/harbor.js`) return request.continue();
    return request.respond({ contentType: 'text/javascript', body: source + `
// The page draws alone here (workerCount = 0): this check compares its own row redraws. Ray workers skip the hook.
if (PAGE) workerCount = 0;
if (PAGE) window.checkRedrawReady = () => introProgress === 1 && cols > 0 && DG[0] !== undefined;
if (PAGE) window.checkRedraw = () => {
  const wasVisible = visible;
  visible = false;
  const differences = [];
  const saved = { x: me.x, z: me.z, yaw: me.yaw, mapMode };
  try {
    render();
    for (const mode of [0, 1, 2, 0]) {
      mapMode = mode;
      for (let turn = 0; turn < 3; turn++) {
        me.yaw += 0.1;
        me.x += 0.1;
        render();
        const incremental = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        for (let j = 0; j < rows; j++) redraw(j, 0, cols - 1);
        drawMap();
        const full = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        let count = 0;
        for (let i = 0; i < full.length; i++) if (full[i] !== incremental[i]) count++;
        differences.push(count);
      }
    }
  } finally {
    Object.assign(me, { x: saved.x, z: saved.z, yaw: saved.yaw });
    mapMode = saved.mapMode;
    visible = wasVisible;
    dirty = true;
  }
  return differences;
};` });
  };
  page.on('request', intercept);
  try {
    await page.goto(origin, { waitUntil: 'load' });
    await page.waitForFunction(() => window.checkRedrawReady?.() && document.fonts.status === 'loaded');
    const differences = await page.evaluate(() => window.checkRedraw());
    assert.deepEqual(differences, new Array(12).fill(0), 'incremental pixels differ from full-row pixels');
    return { comparisons: differences.length, differentChannels: 0 };
  } finally {
    page.off('request', intercept);
    await page.setRequestInterception(false);
    await page.setCacheEnabled(true);
  }
}
