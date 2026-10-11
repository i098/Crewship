"""Every outside window pane opens into its room, and the room shows the outside through it."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

SETUP = r"""
const assert = require('node:assert/strict');
const context = new Proxy({}, {get: (target, key) => key in target ? target[key] : () => ({width: 6})});
const element = {
  hidden: false, classList: {add() {}, remove() {}, toggle() {}}, focus() {}, addEventListener() {},
  firstElementChild: {style: {}}, clientWidth: 1200, clientHeight: 800,
  style: {setProperty() {}}, replaceChildren() {}, getContext: () => context
};
const document = {getElementById: () => element, querySelectorAll: () => [],
  documentElement: {}, addEventListener() {}, fonts: {load: () => Promise.resolve(), ready: Promise.resolve()}};
const matchMedia = () => ({matches: false, addEventListener() {}});
const getComputedStyle = () => ({getPropertyValue: () => 'monospace'});
const devicePixelRatio = 1, innerWidth = 1200;
const performance = {now: () => 0};
const IntersectionObserver = class {observe() {}}, ResizeObserver = class {observe() {}};
function requestAnimationFrame() {}
function addEventListener() {}
function removeEventListener() {}
const window = {};
"""

CHECK = r"""
finishIntro();
measure();
// A point on a pane of each window, a quarter of the way across and a fifth down, on the outside wall (the world or
// the ship's frame, which match while the ship rests), and the wall's outward normal [x, z].
const panes = [];
const [hy0, hy1] = OFFICE_PANES, hy = hy1 - 0.2 * (hy1 - hy0);
for (const [a, b] of officeFrontWindows) {
  panes.push([HOUSE, [a + (b - a) / 4, hy, 21], [0, -1]], [HOUSE, [a + (b - a) / 4, hy, 28], [0, 1]]);
}
for (const [a, b] of officeSideWindows) {
  panes.push([HOUSE, [-9, hy, a + (b - a) / 4], [-1, 0]], [HOUSE, [-1, hy, a + (b - a) / 4], [1, 0]]);
}
const [w, cy0, cy1] = CABIN_PANES, cy = cy1 - 0.2 * (cy1 - cy0), half = (z) => 2.1 + 0.08 * (z + 14.6);
for (const u of CABIN_WINDOWS.front) panes.push([CABIN, [SX + u - w / 2, cy, -9], [0, 1]]);
for (const u of CABIN_WINDOWS.stern) panes.push([CABIN, [SX + u - w / 2, cy, -14.6], [0, -1]]);
for (const z of CABIN_WINDOWS.side) for (const side of [-1, 1]) panes.push([CABIN, [SX + side * half(z - w / 2), cy, z - w / 2], [side, 0]]);
const py = PORT[2] - 0.2 * (PORT[2] - PORT[1]);
for (const z of GUN_PORTS) for (const side of [-1, 1]) panes.push([GUN_DECK, [SX + side * (2.2 + 0.45 * py), py, z + PORT[0] / 2], [side, 0]]);
assert.equal(panes.length, 8 + 8 + 8);
// The solid the middle cell shows when the camera at `eye` looks at `at`.
function seen(eye, at) {
  const dx = at[0] - eye[0], dy = at[1] - eye[1], dz = at[2] - eye[2];
  Object.assign(me, {x: eye[0], eye: eye[1], z: eye[2], yaw: Math.atan2(dx, dz), pitch: Math.atan2(dy, Math.hypot(dx, dz))});
  moved = true; // past the welcome sign
  render();
  return Math.abs(ID[(rows >> 1) * cols + (cols >> 1)]) >> 4;
}
for (const [R, p, [nx, nz]] of panes) {
  const ids = new Set(R.solids.map((s) => s.id)), name = `${R === HOUSE ? 'house' : R === CABIN ? 'cabin' : 'gun deck'} window at ${p}`;
  // From just outside, looking up through the pane, the ray lands on the room's ceiling.
  interior = null;
  assert(ids.has(seen([p[0] + 0.6 * nx, p[1] - 0.2, p[2] + 0.6 * nz], p)), `${name}: the pane must show the room`);
  // From 1.2 m inside, looking level out through the same place, the ray leaves the room.
  const s = R.flip ? -1 : 1, q = [s * (p[0] - R.at[0]), p[1] - R.at[1], s * (p[2] - R.at[2])], ox = s * nx, oz = s * nz;
  interior = R;
  assert(!ids.has(seen([q[0] - 1.2 * ox, q[1], q[2] - 1.2 * oz], q)), `${name}: the room must open to the outside there`);
}
"""


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_windows_open_both_ways():
    source = (ROOT / "harbor/public/harbor.js").read_text()
    # The script is larger than the 128 KiB limit for one command-line argument, so it goes in on stdin.
    subprocess.run(
        ["node", "-"],
        input="(async () => {\n"
        + SETUP
        + source
        + "\nawait new Promise(setImmediate);\n"
        + CHECK
        + "\n})().catch(error => { console.error(error); process.exit(1); });",
        text=True,
        check=True,
        timeout=60,
    )
