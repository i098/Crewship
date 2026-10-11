"""Check that the harbor fountain's water lands well inside its basins, without the browser."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_every_droplet_flies_clear_of_stone_and_lands_well_inside_its_basin():
    source = (ROOT / "harbor/public/harbor.js").read_text()
    scene = source[source.index("const SX =") : source.index("// ---- Night lighting")]
    check = r"""
const assert = require('node:assert/strict');
const near = world.filter(s => s.bb[0] < POOL.x + 1.6 && s.bb[3] > POOL.x - 1.6 && s.bb[2] < POOL.z + 1.6 && s.bb[5] > POOL.z - 1.6);
// The first fountain solid on the way from p to q, or null.
function firstHit(p, q) {
  const d = [q[0] - p[0], q[1] - p[1], q[2] - p[2]], reach = Math.hypot(...d);
  hitT = reach; hitS = null;
  trace(near, 0, ...p, ...d.map(c => c / reach));
  return hitS;
}
const below = (x, z, top) => firstHit([x, top + 0.5, z], [x, top - 1.5, z]);
// Open water: the nearest distance from the axis, in 64 directions, where a ray down from above meets stone first.
function openRadius(water, from) {
  let radius = Infinity;
  for (let i = 0; i < 64; i++) {
    const c = Math.cos(i * Math.PI / 32), s = Math.sin(i * Math.PI / 32);
    let r = from;
    while (below(POOL.x + r * c, POOL.z + r * s, water.bb[4]) === water) r += 0.002;
    radius = Math.min(radius, r);
  }
  return radius;
}
const surface = (y) => world.find(s => s.tex === fountainWater && s.bb[4] === y);
const pool = surface(POOL.y), bowl = surface(BOWL.y);
const poolRadius = openRadius(pool, 0.6), bowlRadius = openRadius(bowl, 0.1);
for (let j = 0; j < JETS.length; j++) {
  const water = JETS[j].floor === BOWL.y ? bowl : pool, radius = water === bowl ? bowlRadius : poolRadius;
  let reach = 0;
  for (let k = 0; k < 300; k++) {
    launchDrop(j, k);
    let from = [drop[0], drop[1], drop[2]];
    for (let n = 1; n <= 30; n++) {
      const at = [...dropAt(drop[9] * n / 30)], s = firstHit(from, at);
      assert(s === null || (n === 30 && s === water), `jet ${j} droplet ${k} meets stone at ${at.map(c => c.toFixed(2))}`);
      from = at;
    }
    assert.equal(below(from[0], from[2], from[1]), water, `jet ${j} droplet ${k} misses its water`);
    reach = Math.max(reach, Math.hypot(from[0] - POOL.x, from[2] - POOL.z));
  }
  assert(reach < 0.75 * radius, `jet ${j} lands ${reach.toFixed(3)} m out in open water ${radius.toFixed(3)} m wide`);
}
// Spray, splashes and mist stay well inside the basin, and over the bowl's water above its lip.
for (let tick = 0; tick < 240; tick++) {
  updateWater(tick / 24 + 1000);
  assert(parts > 0 && parts <= PARTS.length, 'the particle buffer must hold every particle');
  for (let o = 0; o < parts; o += 5) {
    const r = Math.hypot(PARTS[o] - POOL.x, PARTS[o + 2] - POOL.z);
    assert(r < 0.75 * poolRadius && PARTS[o + 1] >= POOL.y, 'water drawn outside the basin');
    assert(PARTS[o + 1] < BOWL.y || r < bowlRadius, 'water drawn over the bowl rim');
  }
}
"""
    subprocess.run(["node", "-"], input=scene + check, text=True, check=True, timeout=60)
