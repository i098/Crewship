import assert from 'node:assert/strict';

export async function checkMeasure(page, origin) {
  const source = await (await fetch(`${origin}/harbor.js`)).text();
  await page.setCacheEnabled(false);
  await page.setRequestInterception(true);
  const intercept = request => {
    if (request.url() !== `${origin}/harbor.js`) return request.continue();
    return request.respond({ contentType: 'text/javascript', body: source + `
window.checkMeasureReady = () => introProgress === 1 && cols > 0 && DG[0] !== undefined;
window.checkMeasure = () => {
  const saved = { visible, interior, scale, mapMode };
  visible = false;
  mapMode = 0;
  const results = [];
  try {
    for (const [room, size] of [[true, 1], [true, 1.15], [true, 1.3225], [true, 1.15], [false, 1.15], [true, 1.15]]) {
      interior = room ? HOUSE : null;
      scale = size;
      const width = canvas.width, height = canvas.height;
      ctx.fillStyle = "#ff00ff";
      ctx.fillRect(0, 0, width / dpr, height / dpr);
      measure();
      const cleared = ctx.getImageData(0, 0, width, height).data;
      const background = (data, i) => data[i] === 6 && data[i + 1] === 10 && data[i + 2] === 20 && data[i + 3] === 255;
      let stale = 0;
      for (let i = 0; i < cleared.length; i += 4) if (!background(cleared, i)) stale++;
      render();
      const painted = ctx.getImageData(0, 0, width, height).data;
      const x0 = Math.round(padX * dpr), x1 = Math.round((padX + cols * cellW) * dpr);
      const y0 = Math.round(padY * dpr), y1 = Math.round((padY + rows * cellH) * dpr);
      let padding = 0;
      for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
        if ((x < x0 || x >= x1 || y < y0 || y >= y1) && !background(painted, (y * width + x) * 4)) padding++;
      }
      results.push({ stale, padding, sameSize: canvas.width === width && canvas.height === height });
    }
  } finally {
    interior = saved.interior;
    scale = saved.scale;
    mapMode = saved.mapMode;
    measure();
    visible = saved.visible;
    dirty = true;
  }
  return results;
};` });
  };
  page.on('request', intercept);
  try {
    await page.goto(origin, { waitUntil: 'load' });
    await page.waitForFunction(() => window.checkMeasureReady?.() && document.fonts.status === 'loaded');
    const results = await page.evaluate(() => window.checkMeasure());
    assert.equal(results.length, 6);
    for (const result of results) {
      assert.equal(result.stale, 0, 'grid invalidation retains old pixels');
      assert.equal(result.padding, 0, 'render retains old padding pixels');
      assert.equal(result.sameSize, true, 'grid invalidation resizes the backing store');
    }
    return { invalidations: results.length, stalePixels: 0 };
  } finally {
    page.off('request', intercept);
    await page.setRequestInterception(false);
    await page.setCacheEnabled(true);
  }
}
