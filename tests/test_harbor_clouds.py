"""Check the harbor's cloud layers (wind drift and streaks, soft edges, glyphs, moonlit edges, cover, the sky buffer's refresh) and the horizon."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
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
    Object.assign(cam, {x: WIND.x * layer.speed * 30, z: WIND.z * layer.speed * 30}); gatherClouds(0);
    assert(Math.abs(cloudDensity(...d) - before) < 1e-5, 'clouds must drift downwind at their layer speed');
    if (before > 0.2) clouded++;
  });
  assert(clouded > 20 && moved > 20, 'the drift check must see clouds move');
}

// The middle and high sheets draw streaks along the wind: they change less downwind than across the wind.
for (const layer of layers.slice(1)) {
  CLOUD_LAYERS.splice(0, CLOUD_LAYERS.length, layer);
  Object.assign(cam, {x: 0, y: 2.8, z: 0}); T = 0; gatherClouds(0);
  clumpCount = 0; // the sheet alone
  const at = (along, across) => {
    const x = along * WIND.x + across * WIND.z, y = layer.base - cam.y, z = along * WIND.z - across * WIND.x, l = Math.hypot(x, y, z);
    return cloudDensity(x / l, y / l, z / l);
  };
  let downwind = 0, crosswind = 0;
  for (let a = -3 * layer.base; a < 3 * layer.base; a += layer.base / 13) {
    for (let b = -3 * layer.base; b < 3 * layer.base; b += layer.base / 12) {
      const here = at(a, b);
      downwind += Math.abs(at(a + layer.base / 3, b) - here);
      crosswind += Math.abs(at(a, b + layer.base / 3) - here);
    }
  }
  assert(downwind < 0.8 * crosswind, 'cloud streaks must run along the wind');
}
CLOUD_LAYERS.splice(0, CLOUD_LAYERS.length, ...layers);

// Cloud thins out to clear sky: dense cloud seldom lies within 1° of clear sky.
const toward = (a, b) => [Math.cos(b) * Math.sin(a), Math.sin(b), Math.cos(b) * Math.cos(a)];
const degrees = (az, el) => toward(az * Math.PI / 180, el * Math.PI / 180);
Object.assign(cam, {x: 0, y: 2.8, z: 0}); T = 0; gatherClouds(0);
let dense = 0, abrupt = 0;
for (let az = -180; az < 180; az += 2) {
  for (let el = 15.5; el < 80; el += 2) {
    if (cloudDensity(...degrees(az, el)) < 0.4) continue;
    dense++;
    if ([[1, 0], [-1, 0], [0, 1], [0, -1]].some(([p, q]) => cloudDensity(...degrees(az + p, el + q)) < 0.05)) abrupt++;
  }
}
assert(dense > 200 && abrupt < 0.1 * dense, 'cloud must thin out to clear sky, not end at a hard edge');

// A cumulus clump must fade to clear sky before either side of its billboard.
CLOUD_LAYERS.splice(0, CLOUD_LAYERS.length);
clumpCount = 1;
for (let seed = 0; seed < 10; seed++) {
  CLUMPS.set([0, 1, 0, 260, 1, 0, 0, 0, 1, 0, 260, 1, seed], 0);
  assert(cloudDensity(...unit([0, 1, 0.02])) > 0.2, 'the isolated clump must have a body');
  for (const sign of [-1, 1]) {
    for (const x of [0.48, 0.49, 0.5]) {
      assert.equal(cloudDensity(...unit([sign * x, 1, 0.02])), 0, 'clump sides must fade before the billboard cutoff');
    }
  }
}
CLOUD_LAYERS.splice(0, CLOUD_LAYERS.length, ...layers);
gatherClouds(0);

// Cloud draws mostly light glyphs from its ramp, and its densest glyph rarely.
const glyphs = {};
let cells = 0;
around(0, 0.02, (d) => {
  if (skyClouds(Math.atan2(d[0], d[2]), Math.asin(d[1])) < 0.15) return;
  shadeSky(0, ...d);
  if (!CLOUD_TONES.includes(C[0])) return; // a star, the moon or the lighthouse beam
  glyphs[G[0]] = (glyphs[G[0]] || 0) + 1;
  cells++;
});
const share = (set) => [...set].reduce((n, g) => n + (glyphs[g] || 0), 0) / cells;
assert(cells > 300 && Object.keys(glyphs).every((g) => CLOUD_RAMP.includes(g)), 'cloud must draw glyphs from its ramp');
assert(share('.:~') > 0.5 && share('*') < 0.02, 'cloud must be mostly light glyphs and rarely the densest');

// Cloud edges that face the moon are lit; edges that face away are not. The rim spans 1.5°.
const edges = {toward: [], away: []};
around(Math.atan2(MOON[0], MOON[2]), 0.01, (d) => {
  const az = Math.atan2(d[0], d[2]), el = Math.asin(d[1]), cover = skyClouds(az, el);
  if (cover < 0.2 || cover > 0.8) return;
  const m = d[0] * MOON[0] + d[1] * MOON[1] + d[2] * MOON[2];
  const near = unit(d.map((v, k) => v + (MOON[k] - v) * 0.026 / Math.sqrt(2 - 2 * m)));
  skyClouds(az, el, true);
  edges[cloudDensity(...near) < cloudDensity(...d) ? 'toward' : 'away'].push(cloudRim / cover);
});
const mean = (list) => list.reduce((a, b) => a + b, 0) / list.length;
assert(edges.toward.length > 100 && edges.away.length > 100, 'the sample must cross many cloud edges');
assert(mean(edges.toward) > 3 * mean(edges.away), 'moon-side edges must be brighter');

// Thick cloud hides the moon and the stars; thin cloud dims them.
const read = skyClouds;
function skyWith(cover, d) {
  skyClouds = () => cover;
  shadeSky(0, ...d);
  skyClouds = read;
  return [G[0], C[0]];
}
assert.deepEqual(skyWith(0, MOON), ['@', 'k'], 'a clear moon must stay bright');
assert.deepEqual(skyWith(0.45, MOON), ['%', 'k4'], 'thin cloud must dim the moon');
const thick = skyWith(0.8, MOON)[0];
assert(thick !== ' ' && CLOUD_RAMP.includes(thick), 'thick cloud must cover the moon');
let star = null;
for (let a = 0; !star && a < 6; a += 0.002) {
  const d = unit([Math.sin(a), 0.6, Math.cos(a)]);
  if (skyWith(0, d)[0] === '*') star = d;
}
assert(star, 'the sky must have a star to cover');
assert.deepEqual(skyWith(0.25, star), ['*', 'k1'], 'stars must show faintly through thin cloud');
assert.notEqual(skyWith(0.5, star)[0], '*', 'thicker cloud must hide the stars');
// Just above the horizon the sky is empty or dark hills, never pale haze, at every azimuth.
const horizon = new Set();
for (let a = -Math.PI; a < Math.PI; a += 0.003) {
  for (let el = 0; el < 0.04; el += 0.004) {
    const [ch, cls] = skyWith(0, [Math.sin(a) * Math.cos(el), Math.sin(el), Math.cos(a) * Math.cos(el)]);
    if (cls[0] !== 'l') horizon.add(ch + cls);
  }
}
assert.deepEqual([...horizon].sort(), [' f', '#v'], 'the horizon must show only empty sky and dark hills');

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
let cloudy = null;
for (let k = 0; !cloudy && k < SKY_W * 40; k++) if (compute(...toward(...texelCentre(k % SKY_W, 10 + Math.floor(k / SKY_W)))) > 0.3) cloudy = texelCentre(k % SKY_W, 10 + Math.floor(k / SKY_W));
assert(cloudy, 'the new camera place must see a cloud');
assert(Math.abs(skyClouds(...cloudy) - compute(...toward(...cloudy))) < 1e-6,
  'a texel must refresh from the new camera place within a tenth of a second');

Object.assign(cam, {x: 0, y: 2.8, z: 0}); T = 0;
SKY_STEP.fill(-1); gatherClouds(100);
const rowDirections = Array.from({length: SKY_W}, (_, i) => texelCentre(i, 20));
const readRow = () => rowDirections.map((d) => skyClouds(...d));
const initialRow = readRow();
assert(initialRow.some((cover) => cover > 0.3), 'the movement check must see a cloud');
cam.x += 0.1; gatherClouds(100.16);
const normalRow = readRow();
assert.deepEqual(normalRow, initialRow, 'fresh texels must remain cached during normal-motion walking');

reduced.matches = true;
gatherClouds(100.32);
const transitionedRow = readRow();
let transitionChanges = 0;
rowDirections.forEach((d, i) => {
  assert(Math.abs(transitionedRow[i] - compute(...toward(...d))) < 1e-6,
    'enabling reduced motion after walking must refresh density without further movement');
  if (Math.abs(transitionedRow[i] - normalRow[i]) > 1e-5) transitionChanges++;
});
assert(transitionChanges > 0, 'the mode transition must replace stale cloud positions');
for (const axis of ['x', 'y', 'z']) {
  for (const delta of [1, -1]) {
    const before = readRow();
    cam[axis] += delta; gatherClouds(100.16);
    const after = readRow();
    let changed = 0;
    rowDirections.forEach((d, i) => {
      assert(Math.abs(after[i] - compute(...toward(...d))) < 1e-6,
        'reduced-motion movement must refresh density at the final camera position');
      if (Math.abs(after[i] - before[i]) > 1e-5) changed++;
    });
    assert(changed > 0, 'each camera axis must change the visible cloud density');
    computed = 0; gatherClouds(100.16);
    assert.deepEqual(readRow(), after, 'a render after releasing movement must retain the final cloud position');
    assert(computed > 0, 'each reduced-motion render must refresh the texels it reads');
    computed = 0;
    assert.deepEqual(readRow(), after, 'repeated reads within one render must retain density');
    assert.equal(computed, 0, 'each texel must refresh only once per reduced-motion render');
  }
}
reduced.matches = false;
gatherClouds(100.32);
const resumedRow = readRow();
computed = 0; gatherClouds(100.32);
assert.deepEqual(readRow(), resumedRow, 'disabling reduced motion must restore the time-based cache');
assert.equal(computed, 0, 'normal-motion renders within the same time step must reuse texels');
`, context);
""",
        text=True,
        check=True,
        capture_output=True,
    )
