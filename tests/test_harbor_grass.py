"""Check where the harbor's tall grass grows, without the browser and rendering loop."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_tall_grass_keeps_off_paving_and_crowds_edges_and_slopes():
    source = (ROOT / "harbor/public/harbor.js").read_text()
    world = source[source.index("const SX =") : source.index("const me =")]
    check = r"""
const assert = require('node:assert/strict');
assert.deepEqual(plantGrass(), GRASS, 'clumps must be the same on every visit');
const x = -29.48990, z = -9.73310, g = grassGround(x, z);
assert(['o:', 'o,', 'o.'].includes(ground(x, g[0], z, 0, 1)), 'regression point must render as a trail');
assert(g[1] < 0 && !g[2], 'regression point must be inside a dirt trail');
assert.equal(grassChance(x, z, g[1], g[2], g[3]), 0.1, 'rendered trail must get on-path density');
const clumps = [];
for (let k = 0; k < GRASS.length; k += 5) clumps.push([GRASS[k], GRASS[k + 1], GRASS[k + 2]]);
for (const [x, y, z] of clumps) {
  const [way, , concrete] = roadAt(x, z), at = `${x.toFixed(2)}, ${z.toFixed(2)}`;
  assert(!(concrete && way < 1.5), 'clump on a road at ' + at);
  assert(Math.hypot(x - 5, z - 24.6) > 3.2, 'clump on the plaza at ' + at);
  assert(y >= 0.55 && !harbourWall(x, y, z) && !(x > 3 && x < 7 && z < 14),
    'clump on wet sand, the harbour wall, the dock or the sea at ' + at);
  assert(!world.some(s => walkingSolid(s, y) && x > s.bb[0] && x < s.bb[3] && z > s.bb[2] && z < s.bb[5]),
    'clump inside a building or another solid at ' + at);
}
// Clumps per square metre of land at heights where land(y) holds, in a band around the ways.
function density(land, band) {
  let count = 0, area = 0;
  for (const [x, y, z] of clumps) if (land(y) && band(...roadAt(x, z))) count++;
  for (let x = -62; x < 46; x += 0.5) {
    for (let z = -43; z < 55; z += 0.5) {
      const y = terrainY(x, z);
      if (land(y) && !harbourWall(x, y, z) && band(...roadAt(x, z))) area += 0.25;
    }
  }
  return count / area;
}
const plateau = y => y >= 1.12, dunes = y => y >= 0.55 && y < 1.12;
const trail = density(plateau, (way, along, concrete) => !concrete && way < trailHalfWidth(along));
const edge = density(plateau, (way, along, concrete) => !concrete && way >= trailHalfWidth(along) && way < trailHalfWidth(along) + 1);
const open = density(plateau, way => way > 5);
const slope = density(dunes, way => way > 5);
assert(edge > 1.5 * open, `trail edges (${edge}) must be denser than open ground (${open})`);
assert(trail < 0.5 * open, `trails (${trail}) must be thinner than open ground (${open})`);
assert(slope > 1.5 * open, `beach slopes (${slope}) must be denser than open ground (${open})`);
"""
    subprocess.run(["node", "-"], input=world + check, text=True, check=True, timeout=60)
