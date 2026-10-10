"""Check where the harbor's tall grass grows, without the browser and rendering loop."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_tall_grass_keeps_off_paving_and_crowds_trail_edges():
    source = (ROOT / "harbor/public/harbor.js").read_text()
    world = source[source.index("const SX =") : source.index("const me =")]
    check = r"""
const assert = require('node:assert/strict');
assert.deepEqual(plantGrass(), GRASS, 'clumps must be the same on every visit');
const clumps = [];
for (let k = 0; k < GRASS.length; k += 5) clumps.push([GRASS[k], GRASS[k + 1], GRASS[k + 2]]);
for (const [x, y, z] of clumps) {
  const [way, , concrete] = roadAt(x, z), at = `${x.toFixed(2)}, ${z.toFixed(2)}`;
  assert(!(concrete && way < 1.5), 'clump on a road at ' + at);
  assert(Math.hypot(x - 5, z - 24.6) > 3.2, 'clump on the plaza at ' + at);
  assert(y >= 1.12 && !(x > 3 && x < 7 && z < 14), 'clump on sand, the dock or the sea at ' + at);
  assert(!world.some(s => walkingSolid(s, y) && x > s.bb[0] && x < s.bb[3] && z > s.bb[2] && z < s.bb[5]),
    'clump inside a building or another solid at ' + at);
}
// Clumps per square metre of land in a band around the dirt trails, and in the open.
function density(band) {
  let count = 0, area = 0;
  for (const [x, , z] of clumps) if (band(...roadAt(x, z))) count++;
  for (let x = -62; x < 46; x += 0.5) {
    for (let z = -43; z < 55; z += 0.5) if (terrainY(x, z) >= 1.12 && band(...roadAt(x, z))) area += 0.25;
  }
  return count / area;
}
const trail = density((way, along, concrete) => !concrete && way < 0.5);
const edge = density((way, along, concrete) => !concrete && way >= 0.5 && way < 1.5);
const open = density(way => way > 5);
assert(edge > 1.5 * open, `trail edges (${edge}) must be denser than open ground (${open})`);
assert(trail < 0.5 * open, `trails (${trail}) must be thinner than open ground (${open})`);
"""
    subprocess.run(["node", "-"], input=world + check, text=True, check=True, timeout=60)
