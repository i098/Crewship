"""Check the harbor's cloud layers: wind drift, moonlit edges, cover, and redraw steps."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_clouds_drift_light_cover_and_step():
    subprocess.run(
        ["node", "-", str(ROOT / "harbor/public/harbor.js")],
        input=r"""
const fs = require('node:fs'), vm = require('node:vm');
const assert = require('node:assert/strict');
const element = {
  hidden: false, classList: { add() {}, toggle() {} }, focus() {}, addEventListener() {},
  firstElementChild: {}, clientWidth: 600, clientHeight: 400,
  style: {setProperty() {}},
  getContext: () => ({setTransform() {}, fillRect() {}, measureText: () => ({width: 6})})
};
const context = vm.createContext({
  document: {getElementById: () => element, querySelectorAll: () => [],
    documentElement: {}, addEventListener() {},
    fonts: { load: () => Promise.resolve(), ready: Promise.resolve() }},
  matchMedia: () => ({matches: false, addEventListener() {}}),
  getComputedStyle: () => ({getPropertyValue: () => 'monospace'}),
  devicePixelRatio: 1, innerWidth: 600, performance: {now: () => 0},
  IntersectionObserver: class {observe() {}}, ResizeObserver: class {observe() {}},
  requestAnimationFrame() {}, console, window: {}, assert, addEventListener() {}
});
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8') + `
measure();
Object.assign(cam, {x: 0, y: 2, z: 0});
const unit = (v) => { const l = Math.hypot(...v); return v.map((c) => c / l); };

// A camera carried downwind at a layer's speed sees the same cloud: the pattern drifts with the wind.
for (const layer of CLOUD_LAYERS) {
  let clouded = 0;
  for (let a = 0; a < 6.28; a += 0.05) {
    const ray = unit([Math.sin(a), 0.5, Math.cos(a)]), before = layerCover(layer, ...ray, 10);
    cam.x = WIND[0] * layer.speed * 7; cam.z = WIND[2] * layer.speed * 7;
    assert(Math.abs(layerCover(layer, ...ray, 17) - before) < 1e-9, 'clouds must drift downwind');
    cam.x = cam.z = 0;
    if (before > 0) clouded++;
  }
  assert(clouded > 5, 'the drift check must look at clouds');
}

// Cloud edges that face the moon are brighter than edges that face away from it.
keepClouds();
const sides = {toward: [], away: []};
for (let az = -0.7; az <= 0.7; az += 0.004) for (let el = 0.15; el <= 0.75; el += 0.03) {
  const yaw = Math.atan2(MOON[0], MOON[2]) + az, d = [Math.sin(yaw) * Math.cos(el), Math.sin(el), Math.cos(yaw) * Math.cos(el)];
  const m = d[0] * MOON[0] + d[1] * MOON[1] + d[2] * MOON[2];
  const near = unit(d.map((v, k) => v + (MOON[k] - v) * 0.004 / Math.sqrt(2 - 2 * m)));
  moonlitClouds(0, ...d, m, 30);
  const cover = cloudCover[0], light = cloudLights[0];
  moonlitClouds(0, ...near, m, 30);
  if (cover > 0.3 && cover < 0.7) sides[cloudCover[0] < cover ? 'toward' : 'away'].push(light / cover);
}
const mean = (list) => list.reduce((a, b) => a + b, 0) / list.length;
assert(sides.toward.length > 50 && sides.away.length > 50, 'the sample must cross many cloud edges');
assert(mean(sides.toward) > 1.15 * mean(sides.away), 'moon-side edges must be brighter');

// Thick cloud hides the moon and the stars; thin cloud only dims the moon.
const realClouds = clouds;
function skyWith(cover, d) {
  clouds = () => cover; cloudLight = 0.3;
  shadeSky(0, ...d);
  clouds = realClouds;
  return [G[0], C[0]];
}
assert.deepEqual(skyWith(0, MOON), ['@', 'k'], 'a clear moon must stay bright');
assert.deepEqual(skyWith(0.45, MOON), ['%', 'k4'], 'thin cloud must dim the moon');
cloudLight = 0.3;
shadeCloud(0, 0.8);
const thick = [G[0], C[0]];
assert.deepEqual(skyWith(0.8, MOON), thick, 'thick cloud must cover the moon');
let star = null;
for (let a = 0; !star && a < 6; a += 0.002) {
  const d = unit([Math.sin(a), 0.6, Math.cos(a)]);
  if (skyWith(0, d)[0] === '*') star = d;
}
assert(star, 'the sky must have a star to cover');
assert.notEqual(skyWith(0.5, star)[0], '*', 'cloud must hide the stars');

// Still camera: a 60 Hz frame moves the clouds of at most a tenth of the rows, and of every row once per half second.
const sweep = () => { for (let j = 0; j < rows; j++) clouds(j * cols, 0, 0.5, 0.866, 0); };
T = 40; keepClouds(); sweep();
let most = 0, steppedRows = new Set();
for (let frame = 1; frame <= 30; frame++) {
  const before = Array.from({length: rows}, (_, j) => cloudSteps[j * cols]);
  T = 40 + frame / 60; keepClouds(); sweep();
  const stepped = before.flatMap((step, j) => (cloudSteps[j * cols] === step ? [] : [j]));
  most = Math.max(most, stepped.length); stepped.forEach((j) => steppedRows.add(j));
}
assert(most <= rows / 10, 'a still frame must not move the clouds of most sky rows: ' + most);
assert.equal(steppedRows.size, rows, 'each row must move its clouds every half second');
// Moving the camera replaces kept clouds with the clouds seen from the new place.
const view = unit([0.2, 0.5, 0.84]), viewMoon = view[0] * MOON[0] + view[1] * MOON[1] + view[2] * MOON[2];
const seenCovers = new Set();
for (let x = 20; x < 420; x += 20) {
  cam.x = x; keepClouds();
  const kept = clouds(0, ...view, viewMoon);
  moonlitClouds(0, ...view, viewMoon, Math.floor(T * 2) / 2);
  assert.equal(kept, cloudCover[0], 'a camera move must not keep stale clouds');
  seenCovers.add(kept);
}
assert(seenCovers.size > 3, 'the camera moves must change the clouds');
`, context);
""",
        text=True,
        check=True,
        capture_output=True,
    )
