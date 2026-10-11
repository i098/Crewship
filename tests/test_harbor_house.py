"""Window light stays inside the frames; house detail does not block the approach."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_house_panes_and_approach():
    source = (ROOT / "harbor/public/harbor.js").read_text()
    # Run the real world and collision code without the browser and rendering loop.
    world = source[source.index("const SX =") : source.index("const me =")]
    check = r"""
const assert = require('node:assert/strict');
const wall = world.find(s => s.spot === 'office' && s.mat === 's');
const front = (x, y) => wall.tex(x, y, 21, 0, 0, -1);
assert.equal(front(-7.9, 2.7), 'l');
assert.notEqual(front(-8.25, 2.7), 'l'); // outer frame
assert.notEqual(front(-7.4, 2.7), 'l'); // vertical crossbar
assert.notEqual(front(-7.9, 3), 'l');   // horizontal crossbar
assert.notEqual(front(-7.9, 3.9), 'l'); // wall above the window
assert.notEqual(front(-5, 2.7), 'l');  // door
assert.equal(blocked(-5, 20.7, 1.2), false); // the step adds no obstacle
assert.equal(blocked(-5, 20.8, 1.2), true);  // the old wall still blocks
assert.equal(blocked(-0.7, 23, 1.2), false); // side approach
assert.equal(blocked(-0.8, 23, 1.2), true);
"""
    # The world section with the paintings' textures nears the 128 KiB limit for one argument, so it goes in on stdin.
    subprocess.run(["node", "-"], input=world + check, text=True, check=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_house_trim_targets_office_without_moving_anchor():
    source = (ROOT / "harbor/public/harbor.js").read_text()
    scene = source[source.index("const SX =") : source.index("const MONO =")]
    shading = source[source.index("const GRAIN =") : source.index("// ---- The sea:")]
    put = source[source.index("function put(") : source.index("// Is neighbour")]
    nearby = source[source.index("function nearby(") : source.index("// Cards are built")]
    check = r"""
const assert = require('node:assert/strict');
for (const [key, value] of Object.entries({x: -5, y: 4.85, z: 24.5, r: 4.4})) {
  assert.ok(Math.abs(anchors.office[key] - value) < 1e-12);
}
assert.equal(anchors.office.n, 2);
assert.equal(anchors.office.ship, 0);
const cam = {};
let G = [], C = [], ID = [], D = [], SP = [];
moveLights();
Object.assign(me, {x: -5, z: 19.6, eye: 2.8});
assert.equal(nearby(), null);
function aim(list, origin, point) {
  Object.assign(cam, {x: origin[0], y: origin[1], z: origin[2]});
  const delta = point.map((v, i) => v - origin[i]);
  const length = Math.hypot(...delta);
  const [dx, dy, dz] = delta.map(v => v / length);
  hitT = Infinity; hitS = null;
  trace(list, 0, ...origin, dx, dy, dz);
  assert.ok(hitS);
  shadeSolid(0, 0, false, dx, dy, dz, dx, dy);
  assert.equal(SP[0], 'office');
  assert.ok(D[0] < RANGE.office);
}
aim(world, [-5, 2.8, 19.6], [-5, 3.95, 20.91]);
assert.equal(hitS.solid, false);
aim(world, [-5, 2.8, 19.6], [-7.9, 2.7, 21]);
assert.equal(hitS.solid, true);
aim(world, [0, 2.8, 24.5], [-0.91, 3.95, 24.5]);
assert.equal(hitS.solid, false);
for (const s of world.filter(s => s.anchor === false)) {
  const b = s.bb;
  const point = [(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2];
  for (const axis of [0, 1, 2]) for (const direction of [-1, 1]) {
    const origin = [...point];
    origin[axis] = b[axis + (direction > 0 ? 3 : 0)] + direction;
    aim([s], origin, point);
  }
}
"""
    # The script is larger than the 128 KiB limit for one command-line argument, so it goes in on stdin.
    subprocess.run(
        ["node", "-"],
        input="const spots = {office: {}}; const touchFirst = {matches: false};\n"
        + scene
        + shading
        + put
        + nearby
        + check,
        text=True,
        check=True,
        timeout=10,
    )


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_house_entry_exit_and_room_collisions():
    source = (ROOT / "harbor/public/harbor.js").read_text()
    setup = r"""
const assert = require('node:assert/strict');
const element = {
  hidden: false, classList: {add() {}, remove() {}, toggle() {}}, focus() {}, addEventListener() {},
  firstElementChild: {style: {}}, clientWidth: 600, clientHeight: 400,
  style: {setProperty() {}},
  replaceChildren() {}, getContext: () => ({setTransform() {}, fillRect() {}, measureText: () => ({width: 6})})
};
const document = {getElementById: () => element, querySelectorAll: () => [],
  documentElement: {}, addEventListener() {}, fonts: {load: () => Promise.resolve(), ready: Promise.resolve()}};
const matchMedia = () => ({matches: false, addEventListener() {}});
const getComputedStyle = () => ({getPropertyValue: () => 'monospace'});
const devicePixelRatio = 1, innerWidth = 600;
let clock = 0;
const performance = {now: () => clock};
const IntersectionObserver = class {observe() {}}, ResizeObserver = class {observe() {}};
function requestAnimationFrame() {}
function addEventListener() {}
function removeEventListener() {}
const window = {};
"""
    check = r"""
Object.assign(me, {x: -5, z: 20.6, yaw: 0});
keys.add('f');
for (let i = 0; i < 4; i++) step(0.02);
keys.clear();
step(0);
assert.equal(interior, HOUSE, 'walking into the door must enter the room');
assert.equal(floorAt(me.x, me.z), 0);
assert(!blocked(me.x, me.z, 0), 'entry must leave the player in a clear aisle');
assert.equal(walkPath.length, 0);
mapKey({code: 'KeyM'});
minimap();
assert.equal(mapMode, 0, 'the island map must not open inside');
assert.equal(mapBox, null);
// Table, bed, fireplace, bookcase, chair, armchair, crates, sea chest and corner plant.
for (const [x, z] of [[-2, 3], [0, 4], [2.4, 4.4], [-2.4, 5.7], [-1.85, 2.12], [2.2, 2.1], [2.5, 0.4], [-2, 0.3], [2.55, 5.5]]) {
  assert(blocked(x, z, 0), `interior furniture must block walking at ${x}, ${z}`);
}
assert(!blocked(0.2, 2, 0), 'the rug must not block walking');
Object.assign(me, {x: 0, z: 0.8, yaw: 0});
keys.add('f');
for (let i = 0; i < 60; i++) step(0.02);
keys.clear();
assert(me.z > 2.5 && me.z < 3, 'walking must stop at the bed foot');
keys.add('r');
for (let i = 0; i < 24; i++) step(0.02);
keys.clear();
keys.add('f');
for (let i = 0; i < 60; i++) step(0.02);
keys.clear();
assert(me.z > 5 && !blocked(me.x, me.z, 0), 'the right aisle must reach the window');
for (const [x, z, yaw] of [[-2.7, 1, -Math.PI/2], [2.7, 1, Math.PI/2], [1.8, 5.4, 0]]) {
  Object.assign(me, {x, z, yaw});
  keys.add('f');
  for (let i = 0; i < 30; i++) step(0.02);
  keys.clear();
  assert.equal(interior, HOUSE, 'walking into a wall must not leave the room');
  assert.notEqual(floorAt(me.x, me.z), null, 'walking must stay within room bounds');
  assert(!blocked(me.x, me.z, 0));
}
Object.assign(me, {x: 0, z: 0.8, yaw: Math.PI});
stick.y = 1;
for (let i = 0; i < 8; i++) step(0.02);
stick.y = 0;
step(0);
assert.equal(interior, null, 'the touch stick must exit through the door');
assert.equal(me.yaw, Math.PI);
assert(me.z < 20.75 && me.z > 19.8, 'exit must land just outside the door');
assert(!blocked(me.x, me.z, floorAt(me.x, me.z)));
Object.assign(me, {x: -5, z: 20.6, yaw: 0});
stick.y = 1;
for (let i = 0; i < 4; i++) step(0.02);
stick.y = 0;
step(0);
assert.equal(interior, HOUSE, 'the touch stick must enter through the door');
Object.assign(me, {x: 0, z: 0.8, yaw: Math.PI});
keys.add('f');
for (let i = 0; i < 8; i++) step(0.02);
keys.clear();
assert.equal(interior, null, 'keyboard walking must exit through the door');
step(0);
for (const x of [-5.5, -4.5]) {
  Object.assign(me, {x, z: 20.6, yaw: 0});
  keys.add('f');
  for (let i = 0; i < 20; i++) step(0.02);
  keys.clear();
  assert.equal(interior, null, 'walking into the door frame must not enter');
  assert(me.z <= 20.75, 'the exterior wall must still block walking');
}
for (const channel of ['keyboard', 'touch', 'combined']) {
  for (const direction of ['f', 'b', 'l', 'r']) {
    for (const startInside of [false, true]) {
      keys.clear(); stick.x = stick.y = 0; step(0);
      interior = startInside ? HOUSE : null;
      const yaw = {f: 0, b: Math.PI, l: Math.PI / 2, r: -Math.PI / 2}[direction];
      Object.assign(me, startInside ? {x: 0, z: 0.8, yaw: yaw + Math.PI} : {x: -5, z: 20.6, yaw});
      if (channel !== 'touch') keys.add(direction);
      if (channel !== 'keyboard') {
        stick.y = direction === 'f' ? 1 : direction === 'b' ? -1 : 0;
        stick.x = direction === 'r' ? 1 : direction === 'l' ? -1 : 0;
      }
      for (let i = 0; i < 100; i++) step(0.02);
      assert.equal(interior, startInside ? null : HOUSE, `${channel} ${direction}: held input must cross only once`);
      assert.equal(me.z, startInside ? 20.35 : 0.8);
      assert.equal(me.yaw, startInside ? Math.PI : 0);
      if (channel === 'combined') {
        const heldX = stick.x, heldY = stick.y;
        stick.x = stick.y = 0;
        for (let i = 0; i < 30; i++) step(0.02);
        assert.equal(interior, startInside ? null : HOUSE, 'a held key must keep the touch release locked');
        stick.x = heldX; stick.y = heldY;
        keys.clear();
        for (let i = 0; i < 30; i++) step(0.02);
        assert.equal(interior, startInside ? null : HOUSE, 'a held touch must keep the keyboard release locked');
      }
      keys.clear(); stick.x = stick.y = 0; step(0);
      if (channel === 'keyboard') keys.add('b');
      else stick.y = -1;
      for (let i = 0; i < 100; i++) step(0.02);
      assert.equal(interior, startInside ? HOUSE : null, 'released input must permit the next crossing');
    }
  }
}
keys.clear(); stick.x = stick.y = 0; step(0);
let renderCost = 2;
render = () => { clock += renderCost; };
for (const scene of [null, HOUSE, CABIN, GUN_DECK]) {
  interior = scene;
  for (const interval of [1000 / 60, 1000 / 30]) {
    refreshMs = Infinity; paintedLastFrame = false; probeMs = 0;
    scale = 1.5; shadows = false; slow = fast = 0;
    renderCost = 2;
    const runFrame = () => { dirty = true; last = clock; clock += interval; frame(clock); };
    for (let i = 0; i < 91; i++) runFrame();
    assert(scale < 1.5, 'a cheap render must recover detail at either display refresh rate');
    scale = 1; shadows = true; slow = fast = 0;
    renderCost = 25;
    for (let i = 0; i < 42; i++) runFrame();
    assert.equal(shadows, false, 'expensive rendering must drop shadows');
    assert(scale > 1, 'expensive rendering must reduce detail in every scene');
  }
}
renderCost = 2;
let paintQueued = false;
render = () => { clock += renderCost; paintQueued = true; };
const paintFrame = (period, paintDelay = 0) => {
  const interval = period + (paintQueued ? paintDelay : 0);
  paintQueued = false;
  dirty = true; last = clock; clock += interval; frame(clock);
};
for (const scene of [null, HOUSE, CABIN, GUN_DECK]) {
interior = scene;
paintQueued = false;
scale = 1; shadows = false; slow = fast = 0;
refreshMs = Infinity; paintedLastFrame = false; probeMs = 0;
keys.add('tr');
paintFrame(1000 / 60);
const startYaw = me.yaw;
for (let i = 0; i < 126; i++) paintFrame(1000 / 30);
assert.equal(scale, 1, 'a native 60 Hz to 30 Hz switch during held turning must not reduce detail');
assert(me.yaw > startYaw, 'cadence sampling must not interrupt held turning');
scale = 1.5; slow = fast = 0;
for (let i = 0; i < 100; i++) paintFrame(1000 / 30);
assert(scale < 1.5, 'detail must recover at the changed native cadence during held turning');
scale = 1.5; slow = fast = 0;
for (let i = 0; i < 100; i++) paintFrame(1000 / 60);
assert(scale < 1.5, 'detail must recover when the display returns to 60 Hz');
keys.clear();
scale = 1; shadows = false; slow = fast = 0;
refreshMs = Infinity; paintedLastFrame = false; paintQueued = false; probeMs = 0;
paintFrame(1000 / 60);
for (let i = 0; i < 12; i++) paintFrame(1000 / 60, 1000 / 60);
for (let i = 0; i < 126; i++) paintFrame(1000 / 30);
assert.equal(scale, 1, 'a native cadence change must clear prior painting-overload evidence before coarsening');
for (const period of [1000 / 60, 1000 / 30]) {
  scale = 1; shadows = true; slow = fast = 0;
  refreshMs = Infinity; paintedLastFrame = false; paintQueued = false; probeMs = 0;
  paintFrame(period);
  for (let i = 0; i < 60; i++) paintFrame(period, period);
  assert(!shadows && scale > 1, 'deferred painting must reduce detail after an unloaded cadence sample');
  const coarseScale = scale;
  for (let i = 0; i < 100; i++) paintFrame(period);
  assert(scale < coarseScale, 'detail must recover when deferred painting stops dropping frames');
}
}
for (const period of [1000 / 60, 1000 / 30]) {
  for (const entryMode of ['frame', 'step']) {
    keys.clear(); stick.x = stick.y = 0; step(0);
    interior = null;
    scale = 1; shadows = false; slow = fast = 0;
    refreshMs = Infinity; paintedLastFrame = false; paintQueued = false; probeMs = 0;
    Object.assign(me, {x: -5, z: 19, yaw: 0});
    keys.add('tr');
    paintFrame(period);
    for (let i = 0; i < 1000; i++) paintFrame(1000 / 30);
    assert.equal(scale, 1, 'native exterior cadence changes must not reduce detail');
    keys.clear();
    Object.assign(me, {x: -5, z: 20.6, yaw: 0});
    keys.add('f');
    if (entryMode === 'step') for (let i = 0; i < 4; i++) step(0.02);
    const paintDelay = period < 20 ? period : 0;
    for (let i = 0; i < 5; i++) paintFrame(period, paintDelay);
    assert.equal(interior, HOUSE, 'the movement path must enter after prolonged exterior timing drift');
    keys.clear(); step(0); keys.add('tr');
    const entryYaw = me.yaw;
    for (let i = 0; i < 80; i++) paintFrame(period, paintDelay);
    assert(me.yaw > entryYaw, 'room-entry sampling must preserve continuous turning');
    if (paintDelay) {
      assert(scale > 1, 'room entry must detect deferred painting despite inherited exterior timing');
      const coarseScale = scale;
      for (let i = 0; i < 100; i++) paintFrame(period);
      assert(scale < coarseScale, 'room detail must recover after entry painting overload ends');
    } else {
      assert.equal(scale, 1, 'room entry on a native 30 Hz display must not reduce detail');
    }
  }
}
keys.clear();
"""
    # The script is larger than the 128 KiB limit for one command-line argument, so it goes in on stdin.
    subprocess.run(
        ["node", "-"],
        input="(async () => {\n"
        + setup
        + source
        + "\nawait new Promise(setImmediate);\n"
        + check
        + "\n})().catch(error => { console.error(error); process.exit(1); });",
        text=True,
        check=True,
        timeout=10,
    )


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_house_paintings_show_their_textures_and_plaques():
    source = (ROOT / "harbor/public/harbor.js").read_text()
    setup = r"""
const assert = require('node:assert/strict');
// Any 2D context call is a no-op; measureText reports a 6 px wide cell.
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
    check = r"""
// Every texel names a palette colour and glyph, and each smaller texture halves the one before.
for (const [key, [pal, w, h, ...levels]] of Object.entries(ART)) {
  assert.equal(levels.length, 3, key);
  levels.forEach((level, k) => {
    assert.equal(level.length, Math.ceil(w / 2 ** k) * Math.ceil(h / 2 ** k), `${key} level ${k} size`);
    for (const ch of level) assert(ch.charCodeAt(0) - 35 - (ch > '\\') < pal.length / 2 * ART_GLYPHS.length, key);
  });
}
finishIntro();
Object.assign(me, {x: -5, z: 20.7, yaw: 0, pitch: 0});
crossDoor(-5, 20.8);
measure();
// Face each plaque from 1.2 m: its painter's name shows once, on one glyph row.
const plaques = room.filter(s => s.mat === 'o' && s.tex && Math.min(s.bb[3] - s.bb[0], s.bb[5] - s.bb[2]) < 0.013);
assert.equal(plaques.length, 4);
const seen = [];
for (const {bb} of plaques) {
  const alongX = bb[3] - bb[0] > bb[5] - bb[2], cx = (bb[0] + bb[3]) / 2, cz = (bb[2] + bb[5]) / 2;
  const nx = alongX ? 0 : Math.sign(-cx), nz = alongX ? Math.sign(3 - cz) : 0;
  Object.assign(me, {x: cx + nx * 1.2, z: cz + nz * 1.2, yaw: Math.atan2(-nx, -nz), pitch: 0, eye: (bb[1] + bb[4]) / 2});
  render();
  // G holds the cast glyphs, before the aim mark and edge glyphs are drawn over them.
  const text = Array.from({length: rows}, (_, j) => G.slice(j * cols, (j + 1) * cols).join('')).join('\n');
  const names = ['HOKUSAI', 'VERNET', 'AIVAZOVSKY', 'TURNER'].filter(name => text.includes(` ${name} `));
  assert.equal(names.length, 1, `one whole name under the plaque at ${cx}, ${cz}`);
  assert.equal(text.split(names[0]).length, 2, `${names[0]} shows once`);
  seen.push(names[0]);
}
assert.deepEqual(seen.sort(), ['AIVAZOVSKY', 'HOKUSAI', 'TURNER', 'VERNET']);
"""
    # The script is larger than the 128 KiB limit for one command-line argument, so it goes in on stdin.
    subprocess.run(
        ["node", "-"],
        input="(async () => {\n"
        + setup
        + source
        + "\nawait new Promise(setImmediate);\n"
        + check
        + "\n})().catch(error => { console.error(error); process.exit(1); });",
        text=True,
        check=True,
        timeout=20,
    )
