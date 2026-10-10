"""Check the harbor's cloud layers: wind drift, moonlit edges, cover, and the sky buffer's refresh."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_clouds_drift_light_cover_and_refresh():
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
const unit = (v) => { const l = Math.hypot(...v); return v.map((c) => c / l); };
const around = (yaw0, step, f) => {
  for (let yaw = yaw0 - Math.PI; yaw < yaw0 + Math.PI; yaw += step) {
    for (let el = 0.15; el < 1.2; el += step) f([Math.sin(yaw) * Math.cos(el), Math.sin(el), Math.cos(yaw) * Math.cos(el)]);
  }
};

// A camera carried downwind at a layer's speed sees the same clouds: each layer drifts with the wind.
const layers = CLOUD_LAYERS.slice();
for (const layer of layers) {
  CLOUD_LAYERS.splice(0, CLOUD_LAYERS.length, layer);
  let clouded = 0, moved = 0;
  around(0, 0.05, (d) => {
    Object.assign(cam, {x: 0, y: 2.8, z: 0}); T = 10; gatherClouds(0);
    const before = cloudDensity(...d);
    T = 40; gatherClouds(0);
    if (Math.abs(cloudDensity(...d) - before) > 0.1) moved++;
    Object.assign(cam, {x: WIND[0] * layer.speed * 30, z: WIND[2] * layer.speed * 30}); gatherClouds(0);
    assert(Math.abs(cloudDensity(...d) - before) < 1e-5, 'clouds must drift downwind at their layer speed');
    if (before > 0.5) clouded++;
  });
  assert(clouded > 20 && moved > 20, 'the drift check must see clouds move');
}
CLOUD_LAYERS.splice(0, CLOUD_LAYERS.length, ...layers);

// Cloud edges that face the moon are lit; edges that face away are not.
Object.assign(cam, {x: 0, y: 2.8, z: 0}); T = 0; gatherClouds(0);
const edges = {toward: [], away: []};
around(Math.atan2(MOON[0], MOON[2]), 0.01, (d) => {
  const density = cloudDensity(...d), rim = cloudEdge;
  if (density < 0.2 || density > 0.8) return;
  const m = d[0] * MOON[0] + d[1] * MOON[1] + d[2] * MOON[2];
  const near = unit(d.map((v, k) => v + (MOON[k] - v) * 0.004 / Math.sqrt(2 - 2 * m)));
  edges[cloudDensity(...near) < density ? 'toward' : 'away'].push(rim / density);
});
const mean = (list) => list.reduce((a, b) => a + b, 0) / list.length;
assert(edges.toward.length > 100 && edges.away.length > 100, 'the sample must cross many cloud edges');
assert(mean(edges.toward) > 3 * mean(edges.away), 'moon-side edges must be brighter');

// Thick cloud hides the moon and the stars; thin cloud only dims the moon.
const read = skyClouds;
function skyWith(cover, d) {
  skyClouds = () => cover; cloudRim = 0.3;
  shadeSky(0, ...d);
  skyClouds = read;
  return [G[0], C[0]];
}
assert.deepEqual(skyWith(0, MOON), ['@', 'k'], 'a clear moon must stay bright');
assert.deepEqual(skyWith(0.45, MOON), ['%', 'k4'], 'thin cloud must dim the moon');
cloudRim = 0.3;
shadeCloud(0, 0.8, 1);
const thick = [G[0], C[0]];
assert.deepEqual(skyWith(0.8, MOON), thick, 'thick cloud must cover the moon');
let star = null;
for (let a = 0; !star && a < 6; a += 0.002) {
  const d = unit([Math.sin(a), 0.6, Math.cos(a)]);
  if (skyWith(0, d)[0] === '*') star = d;
}
assert(star, 'the sky must have a star to cover');
assert.notEqual(skyWith(0.5, star)[0], '*', 'cloud must hide the stars');

// Sky cells read the buffer: turning within fresh texels computes no clouds, each texel refreshes once a tenth of a
// second with the elevation rows taking turns, and a refresh uses the clouds seen from where the camera stands.
let computed = 0;
const compute = cloudDensity;
cloudDensity = (...d) => { computed++; return compute(...d); };
const sweep = (yaw) => around(yaw, 0.02, (d) => skyClouds(Math.atan2(d[0], d[2]), Math.asin(d[1])));
let tenths = 100;
gatherClouds(tenths); sweep(0);
const texels = computed;
assert(texels > 1000, 'the first look must fill the buffer');
computed = 0; sweep(0.3);
assert.equal(computed, 0, 'turning must only read the buffer');
const steps = [];
for (let n = 1; n <= 6; n++) {
  computed = 0; gatherClouds(tenths += 1 / 6); sweep(0);
  steps.push(computed);
}
const total = steps.reduce((x, y) => x + y, 0);
assert(Math.abs(total - texels) <= 0.05 * texels, 'each texel must refresh once in a tenth of a second');
assert(Math.max(...steps) < 0.4 * total, 'one frame must not refresh most rows');
Object.assign(cam, {x: 400, z: -300}); gatherClouds(tenths += 1);
const texelCentre = (i, j) => [(i + 0.5) * 2 * Math.PI / SKY_W - Math.PI, (j + 0.5) * Math.PI / 2 / SKY_H];
const toward = (a, b) => [Math.cos(b) * Math.sin(a), Math.sin(b), Math.cos(b) * Math.cos(a)];
let cloudy = null;
for (let k = 0; !cloudy && k < SKY_W * 40; k++) if (compute(...toward(...texelCentre(k % SKY_W, 10 + Math.floor(k / SKY_W)))) > 0.5) cloudy = texelCentre(k % SKY_W, 10 + Math.floor(k / SKY_W));
assert(cloudy, 'the new camera place must see a cloud');
assert(Math.abs(skyClouds(...cloudy) - compute(...toward(...cloudy))) < 1e-6,
  'a texel must refresh from the new camera place within a tenth of a second');
`, context);
""",
        text=True,
        check=True,
        capture_output=True,
    )
