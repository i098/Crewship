"""Ambient sound follows the player: emitters, room fire, and ducking."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_sound_emitters_and_rooms():
    source = (ROOT / "harbor/public/harbor.js").read_text()
    setup = r"""
const assert = require('node:assert/strict');
const element = {
  hidden: false, classList: {add() {}, remove() {}, toggle() {}}, focus() {}, addEventListener() {}, setAttribute() {},
  firstElementChild: {style: {}}, clientWidth: 600, clientHeight: 400,
  style: {setProperty() {}},
  replaceChildren() {}, getContext: () => ({setTransform() {}, fillRect() {}, measureText: () => ({width: 6})})
};
const document = {getElementById: () => element, querySelectorAll: () => [], hidden: false,
  documentElement: {}, addEventListener() {}, fonts: {load: () => Promise.resolve(), ready: Promise.resolve()}};
const matchMedia = () => ({matches: false, addEventListener() {}});
const getComputedStyle = () => ({getPropertyValue: () => 'monospace'});
const devicePixelRatio = 1, innerWidth = 600;
const performance = {now: () => 0};
const IntersectionObserver = class {observe() {}}, ResizeObserver = class {observe() {}};
function requestAnimationFrame() {}
function addEventListener() {}
function removeEventListener() {}
const window = {};
// Web Audio stand-ins that keep the last target of each parameter; the loops never load.
const param = () => ({value: 0, setTargetAtTime(v) { this.value = v; }});
class AudioContext {
  constructor() { this.currentTime = 0; this.listener = {setPosition: (...p) => { this.ear = p; }, setOrientation: (...p) => { this.facing = p; }}; }
  resume() { return Promise.resolve(); }
  suspend() { return Promise.resolve(); }
}
class GainNode { constructor() { this.gain = param(); } connect(n) { return n; } }
class PannerNode {
  constructor() { this.positionX = param(); this.positionY = param(); this.positionZ = param(); }
  connect(n) { return n; }
}
const fetch = () => Promise.reject(new Error('offline'));
"""
    check = r"""
const at = (i) => { const p = audio.nodes[i].panner; return [p.positionX.value, p.positionY.value, -p.positionZ.value]; };
const gain = (i) => audio.nodes[i].gain.gain.value;
const ear = () => { const [x, y, z] = audio.ctx.ear; return [x, y, -z]; };
const flat = (a, b) => Math.hypot(a[0] - b[0], a[2] - b[2]);
let clock = 0;
const tick = () => { clock += 100; soundTick(clock); };
assert.equal(audio, null, 'no audio before a click or tap');
setSound(true);

// Outdoors by the fountain: the outdoor loops play, the fire is silent, the fountain stays at the basin.
Object.assign(me, {x: 5, z: 21, yaw: 0, eye: 3});
tick();
assert.deepEqual(ear(), [5, 3, 21]);
assert.deepEqual(at(1), [POOL.x, POOL.y, POOL.z]);
assert.equal(gain(4), 0, 'no fire outdoors');
assert.equal(gain(0), 0.8);
assert(flat(at(0), ear()) < 10, 'the sea plays from the nearby harbour wall');
assert(flat(at(2), ear()) < 7, 'the wind plays from the nearest tree');

// Inside the house: the fireplace crackles where it stands in the room, and the outdoors is muffled.
crossInto(HOUSE, {x: 1, z: 2, yaw: 0});
me.eye = 1.6;
tick();
assert.equal(gain(4), 0.9);
assert(Math.abs(flat(at(4), ear()) - Math.hypot(HEARTH[0] - 1, HEARTH[2] - 2)) < 1e-9, 'fire at the hearth, seen from the player');
assert(at(4)[1] < 0.5, 'the fire burns in the fireplace, not at the lamp');
assert(flat(ear(), [HOUSE.exit[0], 0, HOUSE.exit[1]]) < 6, 'the outdoors is heard from where the house stands');
assert(gain(0) < 0.2 && gain(3) < 0.2, 'house walls muffle the sea and the ship');

// The gun deck keeps the ship's creaking and plays the nearest lantern.
crossInto(GUN_DECK, {x: SX, z: 0, yaw: Math.PI});
me.eye = 1.6;
tick();
assert.equal(gain(3), 0.6, 'creaking stays at full level below deck');
assert.equal(gain(4), 0.9);
const lamps = [];
for (let k = 0; k < GUN_DECK_LAMPS.length; k += 3) lamps.push(Math.hypot(GUN_DECK_LAMPS[k] - SX, GUN_DECK_LAMPS[k + 2]));
assert(Math.abs(flat(at(4), ear()) - Math.min(...lamps)) < 1e-9, 'the nearest gun deck lantern crackles');
assert(gain(0) > 0.2 && gain(0) < 0.8, 'the hull muffles the sea');

// The cabin is drawn turned half-way round: walking into it heads towards the stern, and the lantern hangs there.
crossInto(CABIN, {x: 0, z: 4, yaw: 0});
me.eye = 1.6;
tick();
assert.deepEqual(ear(), [CABIN.exit[0], 1.6, CABIN.exit[1] - 4], 'four metres into the cabin is four metres further towards the stern');
assert(Math.abs(audio.ctx.facing[2] - 1) < 1e-9, 'facing into the cabin is facing the stern (-z)');
assert.deepEqual(at(4), [CABIN.exit[0], CABIN.lights[1], CABIN.exit[1] - CABIN.lights[2]], 'the lantern hangs at its world position');
assert.equal(gain(4), 0.9);
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
        timeout=30,
    )
