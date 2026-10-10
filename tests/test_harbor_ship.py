"""Exercise the pirate ship's walking, ray hits, and map silhouette."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _run_ship_scene(checks):
    subprocess.run(
        ["node", "-", str(ROOT / "harbor/public/harbor.js"), checks],
        input=r"""
const fs = require('node:fs'), vm = require('node:vm');
const assert = require('node:assert/strict');
const element = {
  hidden: false, classList: { add() {}, toggle() {} }, focus() {}, addEventListener() {},
  firstElementChild: {}, clientWidth: 600, clientHeight: 400,
  style: {setProperty() {}}, replaceChildren() {},
  getContext: () => ({setTransform() {}, fillRect() {}, measureText: () => ({width: 6})})
};
const context = vm.createContext({
  document: {getElementById: () => element,
    querySelectorAll: () => ['how', 'spyglass'].map(id => ({
      dataset: {spot: id},
      querySelector: tag => tag === 'a' ? {textContent: id, href: '#'} : {}
    })),
    documentElement: {}, addEventListener() {},
    fonts: { load: () => Promise.resolve(), ready: Promise.resolve() }},
  matchMedia: () => ({matches: false, addEventListener() {}}),
  getComputedStyle: () => ({getPropertyValue: () => 'monospace'}),
  devicePixelRatio: 1, innerWidth: 600, performance: {now: () => 0},
  IntersectionObserver: class {observe() {}}, ResizeObserver: class {observe() {}},
  requestAnimationFrame() {}, console, window: {}, assert, addEventListener() {}
});
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8') + '\nmeasure();\n' + process.argv[3], context);
""",
        text=True,
        check=True,
        capture_output=True,
    )


def test_ship_deck_ports_and_map_match_the_hull():
    _run_ship_scene(
        r"""
const spawn = [me.x, me.z];
keys.add('f'); step(0.1); keys.clear();
assert(Math.hypot(me.x - spawn[0], me.z - spawn[1]) > 0.2, 'the default view must start on clear walking ground');
assert.equal(floorAt(-5, 0), DECK, 'the wider waist must support walking');
assert.equal(floorAt(-5, 11), null, 'the bow must not leave an invisible square deck');
assert(floorAt(SX, 11) > DECK, 'the bow sheer must rise above the waist');
assert(blocked(SX, 6, floorAt(SX, 6)), 'the foremast must block walking through its base');
const mast = ship.find(s => s.cone && s.bb[1] === DECK && s.bb[4] > 18);
const lowerPole = hit(mast, SX + 2, 3, -3, -1, 0, 0);
const upperPole = hit(mast, SX + 2, 20, -3, -1, 0, 0);
assert(Math.abs(lowerPole - upperPole) < 1e-6 && 2 - lowerPole < 0.3, 'the main mast must remain a thin straight pole');
assert(blocked(SX, -12, DECK), 'the cabin walls must still block walking through their lower level');
me.x = SX + 1.7; me.z = -4.8; me.yaw = Math.PI;
keys.add('f');
for (let i = 0; i < 100; i++) step(0.02);
keys.clear();
assert(me.z < -11.5, 'the stairs must let a visitor reach the stern deck');
assert(Math.abs(floorAt(me.x, me.z) - 4.8) < 1e-6, 'the stern floor must match the castle roof');
assert(!blocked(me.x, me.z, floorAt(me.x, me.z)), 'the castle roof must provide a clear walking surface');
me.yaw = 0; keys.add('f');
for (let i = 0; i < 100; i++) step(0.02);
keys.clear();
assert(me.z > -5 && Math.abs(floorAt(me.x, me.z) - DECK) < 1e-6, 'the stairs must let a visitor descend to the main deck');
me.x = SX + 0.5; me.z = 10; me.yaw = Math.PI / 2;
keys.add('f');
for (let i = 0; i < 200; i++) step(0.02);
keys.clear();
assert(me.x > SX + 0.5, 'the bow deck must allow lateral walking');
assert(me.x < SX + shipProfile(10)[0] - 0.2, 'walking must stop before the tapered rail');
me.x = 0; me.z = -1.2; me.yaw = Math.PI / 2;
keys.add('f');
for (let i = 0; i < 70; i++) step(0.02);
keys.clear();
assert(me.x > 4, 'the open rail and gangway must join the ship to the dock');
const hull = ship.filter(s => s.hull);
const waistHit = Math.min(...hull.map(s => hit(s, 3, 1.02, 0.6, -1, 0, 0)));
const bowHit = Math.min(...hull.map(s => hit(s, 3, 2.5, 11, -1, 0, 0)));
assert(bowHit > waistHit, 'a side ray must see the narrowing bow');
const barrelHit = Math.min(...ship.filter(s => !s.hull).map(s => hit(s, 3, 1.02, 0.6, -1, 0, 0)));
assert(barrelHit < waistHit, 'the cannon must emerge from the side gun port');
for (const origin of [[25,5,0], [-25,5,0], [SX,5,-24], [SX,5,24], [SX,30,0], [0,3.6,-7.4]]) {
  for (const s of ship) {
    const b = s.bb, delta = [0,1,2].map(k => (b[k] + b[k+3]) / 2 - origin[k]);
    const length = Math.hypot(...delta), ray = delta.map(v => v / length);
    const t = hit(s, ...origin, ...ray);
    if (!Number.isFinite(t)) continue;
    const envelope = boxEntry(SHIP_BOUNDS, ...origin, ...ray.map(v => 1 / v));
    assert(envelope <= t + 1e-6 || Number.isNaN(envelope), 'the aggregate bounds must not hide a visible ship part');
  }
}
const rail = ship.find(s => s.rail && s.bb[2] < -4 && s.bb[5] > -4 && s.bb[0] > SX);
assert.equal(hit(rail, 3, 2.55, -4, -1, 0, 0), Infinity, 'the railing must leave open space between its bars');
assert(Number.isFinite(hit(rail, 3, 2.3, -4, -1, 0, 0)), 'the railing crossbar must remain visible');
cols = rows = 3; G = Array(9).fill(' '); C = Array(9).fill(''); SP = Array(9).fill(null);
ID = new Int32Array(9); D = new Float32Array(9).fill(Infinity);
cam.tanH = cam.tanV = 0.62; G[4] = '@'; D[4] = 5;
drawRope([-100, 1.5, 10], [100, 1.5, 10]);
assert.equal(G[3], '-', 'an off-screen stay must enter the visible grid');
assert.equal(G[4], '@', 'a stay must not draw through a nearer hull');
assert.equal(G[5], '-', 'an off-screen stay must reach the opposite grid edge');
cols = 240; rows = 120; mapMode = 2;
mapBox = {oi:1,oj:1,w:238,h:118,iw:236,ih:115};
mapTerrain();
for (const s of hull) footprint(s, 'o');
const cell = (x,z) => {
  const [i,j] = toMap(x,z);
  return MAPCELLS.get((mapBox.oj+j+1)*cols+mapBox.oi+i+1);
};
assert.equal(cell(-5,0)[1], 'o', 'the map must include the wider hull');
assert.notEqual(cell(-5,11)[1], 'o', 'the map must leave water beside the narrowing bow');
assert.equal(cell(SX,11)[1], 'o', 'the map must retain the raised bow');
"""
    )


def test_ship_canvas_stays_pale_and_flag_stays_black_at_night():
    _run_ship_scene(
        r"""
function paintPart(s, y, x = (s.bb[0] + s.bb[3]) / 2) {
  cam.x = cam.lx = x;
  cam.y = cam.ly = y; cam.z = s.bb[2] - 4; cam.r = [1, 0, 0]; cam.tanV = 0.62;
  hitS = s; hitT = hit(s, cam.lx, cam.ly, cam.z, 0, 0, 1); hitK = entryK;
  shadeSolid(0, 0, true, 0, 0, 1, 0, 0);
  return COLORS[C[0]].slice(1).match(/../g).map(v => parseInt(v, 16));
}
const canvasPart = ship.find(s => s.tex === sailTexture);
const pale = paintPart(canvasPart, (canvasPart.bb[1] + canvasPart.bb[4]) / 2);
assert(pale.every(v => v > 150), 'the canvas must remain pale under night lighting');
const flag = ship.find(s => s.flag);
paintPart(flag, FLAG.at[1] - 2.8);
assert.equal(G[0], ' ', 'the black flag must leave its cloth dark');
const skull = paintPart(flag, FLAG.at[1] - 1.12, FLAG.at[0] + 2.5 * FLAG.cu);
assert(G[0] === '@' && skull.every(v => v > 150), 'the skull must stand out pale on the black flag');
const wood = paintPart(ship.find(s => s.hull), 0.15);
assert(wood[0] - wood[1] > 20 && wood[1] - wood[2] > 20, 'the hull must keep its warm wood tone instead of using the cloth paint');
"""
    )


def test_sails_fill_downwind_and_their_sheets_follow_the_corners():
    _run_ship_scene(
        r"""
const part = cloth => ship.find(s => s.cloth === cloth);
const corner = (sail, side) => clothPoint(sail, side * sail.half, clothFoot(sail, side * sail.half));
for (const sail of SAILS) {
  // Rays along the canvas normal: the foot sags below its corners in the middle, and the leeches bow out.
  const s = part(sail), low = (clothFoot(sail, sail.half) + sail.v1) / 2;
  const at = (u, v) => { const p = clothPoint(sail, u, v); return hit(s, p[0] + 10 * sail.su, p[1], p[2] - 10 * sail.cu, -sail.su, 0, sail.cu); };
  assert(Number.isFinite(at(0, low)), 'the foot must sag below the corners in the middle');
  assert.equal(at(0.95 * sail.half, low), Infinity, 'the foot must rise to the corners');
  assert(Number.isFinite(at(1.03 * sail.half, clothFoot(sail, sail.half) / 2)), 'the leeches must bow out');
}
for (const sail of SAILS) {
  // A ray along the wind, aimed past the mast, meets the canvas well downwind of the yard.
  const from = [sail.at[0] - 20 * WIND.x, sail.at[1] - sail.v1 * 0.7, sail.at[2] - 20 * WIND.z];
  assert(hit(part(sail), ...from, WIND.x, 0, WIND.z) - 20 > 1, 'each sail must belly at least a metre downwind');
}
const fly = clothPoint(FLAG, FLAG.u1, FLAG.v1 / 2), hoist = clothPoint(FLAG, 0, FLAG.v1 / 2);
assert((fly[0] - hoist[0]) * WIND.x + (fly[2] - hoist[2]) * WIND.z > 3, 'the flag must stream downwind of its staff');
T = 0; billow();
const still = SAILS.flatMap(sail => [corner(sail, -1), corner(sail, 1)]);
let breath = 0;
for (let time = 0.25; time < 6; time += 0.25) {
  T = time; billow();
  for (const sail of [...SAILS, FLAG]) {
    const box = part(sail).bb;
    for (let i = 0; i <= 10; i++) for (let j = 0; j <= 10; j++) {
      const u = sail.u0 + (sail.u1 - sail.u0) * i / 10, p = clothPoint(sail, u, clothFoot(sail, u) * j / 10);
      assert(p.every((v, k) => v >= box[k] - 1e-9 && v <= box[k + 3] + 1e-9), 'the culling box must hold the moving cloth');
    }
  }
  SAILS.flatMap(sail => [corner(sail, -1), corner(sail, 1)]).forEach((p, i) => {
    assert(RIGGING.some(([a]) => Math.hypot(a[0] - p[0], a[1] - p[1], a[2] - p[2]) < 1e-9), 'a sheet must stay on each moving sail corner');
    breath = Math.max(breath, Math.hypot(...p.map((v, k) => v - still[i][k])));
  });
}
assert(breath > 0.05, 'the sails must breathe over time');
"""
    )


def test_map_walks_use_supported_ship_and_dock_connections():
    _run_ship_scene(
        r"""
const dock = [me.x, me.z];
const starts = [dock, [-4,7], [-2.95,-3.5], [-4,2], [-5.1,1.2]];
function checkSegment(a, b) {
  const samples = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 0.01));
  let previous = floorAt(...a);
  for (let i = 0; i <= samples; i++) {
    const x = a[0] + (b[0] - a[0]) * i / samples;
    const z = a[1] + (b[1] - a[1]) * i / samples;
    const height = floorAt(x, z);
    assert.notEqual(height, null, `map walk crosses water at ${x},${z}`);
    assert(!blocked(x, z, height), `map walk crosses a solid at ${x},${z}`);
    assert(Math.abs(height - previous) <= 0.6, `map walk skips a height transition at ${x},${z}`);
    previous = height;
  }
}
function walk(id, start, dt) {
  me.x = start[0]; me.z = start[1]; me.eye = floorAt(...start) + 1.6;
  const destination = standFor(anchors[id]);
  go(id);
  assert(walkPath.length, `no route from ${start} to ${id}`);
  let previous = start;
  for (const waypoint of walkPath) {
    checkSegment(previous, waypoint);
    previous = waypoint;
  }
  let frames = 0;
  while (walkPath.length && frames++ < 10000) {
    const before = [me.x, me.z];
    step(dt);
    checkSegment(before, [me.x, me.z]);
  }
  assert.equal(walkPath.length, 0, 'map walk did not finish');
  assert.equal(jumped, id, 'map walk did not face the destination');
  assert.deepEqual([me.x, me.z], destination, 'map walk missed the destination');
  return destination;
}
for (const dt of [0.02, 0.1]) {
  for (const start of starts) {
    assert(!blocked(...start, floorAt(...start)), 'the deck start must be reachable');
    anchors.return = {x: start[0], y: floorAt(...start), z: start[1] + 2.5, r: 0,
      ship: floorAt(...start) > 1.6};
    for (const id of ['how', 'spyglass']) {
      const end = walk(id, start, dt);
      if (id === 'spyglass') assert.equal(floorAt(...end), 4.8, 'the spyglass walk must reach the stern roof');
      const returned = walk('return', end, dt);
      assert(Math.hypot(returned[0] - start[0], returned[1] - start[1]) < 1e-9,
        'the return walk must reach the original start');
    }
  }
}
"""
    )


def test_cabin_door_leads_into_a_furnished_room_and_back_to_the_deck():
    _run_ship_scene(
        r"""
function walk(channel, yaw, frames) {
  me.yaw = yaw;
  if (channel === 'keyboard') keys.add('f'); else stick.y = 1;
  for (let i = 0; i < frames; i++) step(0.02);
  keys.clear(); stick.y = 0; step(0);
}
for (const channel of ['keyboard', 'touch']) {
  Object.assign(me, {x: SX, z: -8.4});
  walk(channel, Math.PI, 6);
  assert.equal(interior, CABIN, `${channel}: the cabin door must lead inside`);
  assert.deepEqual([me.x, me.z, me.yaw], [0, 0.8, 0], 'entry must face into the cabin');
  assert(floorAt(me.x, me.z) === 0 && !blocked(me.x, me.z, 0), 'entry must leave the player clear of the furniture');
  mapKey({code: 'KeyM'});
  minimap();
  assert.equal(mapMode, 0, 'the island map must not open inside');
  assert.equal(mapBox, null);
  walk(channel, Math.PI, 8);
  assert.equal(interior, null, `${channel}: the inside door must lead back out`);
  assert.deepEqual([me.x, me.z, me.yaw], [SX, -8.35, 0], 'the exit must face the bow just outside the door');
  const deck = floorAt(me.x, me.z);
  assert(deck > 1.6 && !blocked(me.x, me.z, deck), 'the exit must land on clear deck');
}
for (const x of [SX - 0.6, SX + 0.6]) {
  Object.assign(me, {x, z: -8.4});
  walk('keyboard', Math.PI, 20);
  assert.equal(interior, null, 'walking into the cabin front beside the door must not enter');
  assert(me.z >= -8.75, 'the cabin front must still block walking');
}
interior = CABIN;
for (const [x, z] of [[0, 3.2], [0, 4.3], [1.8, 1.9], [-1.8, 1.3]]) {
  assert(blocked(x, z, 0), `the table, chair, bunk and chest must block walking at ${x},${z}`);
}
for (const [x, z] of [[0, 1.6], [1.6, 4.6], [-1.6, 4.6]]) {
  assert(floorAt(x, z) === 0 && !blocked(x, z, 0), `the aisles must reach the stern windows at ${x},${z}`);
}
assert.equal(floorAt(0, 5.1), null, 'the stern wall must bound the cabin floor');
"""
    )


def test_stair_treads_sit_where_the_walking_lane_puts_your_feet():
    _run_ship_scene(
        r"""
let previous = DECK;
for (const [x0, x1, z0, z1] of STERN_STEPS) {
  const x = (x0 + x1) / 2, z = (z0 + z1) / 2, height = floorAt(x, z);
  const tread = 9 - Math.min(...ship.map(s => hit(s, x, 9, z, 0, -1, 0)));
  assert(Math.abs(tread - height) < 1e-9, `the tread at z ${z} must be at the walking height`);
  assert(Math.abs(height - previous - 0.28) < 1e-9, 'every step must rise by one equal riser');
  previous = height;
}
assert(Math.abs(previous - 4.8) < 1e-9, 'the top step must be level with the stern roof');
"""
    )
