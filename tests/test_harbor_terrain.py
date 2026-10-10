"""Check the island's rolling relief, its seated objects, roads and the walking bounds on its slopes."""

from test_harbor_ship import _run_ship_scene as _run_scene


def test_ground_rolls_inland_without_square_patches_and_keeps_objects_seated():
    _run_scene(
        r"""
let top = -Infinity;
for (let x = WORLD.x0; x <= WORLD.x1; x++) for (let z = WORLD.z0; z <= WORLD.z1; z++) top = Math.max(top, terrainY(x, z));
assert(top > 1.2 + 1.5, 'the island must rise into hills, not stay a flat plateau');
// Whatever stands at plateau height keeps its footing on the dock or the ground.
for (const s of world.filter((s) => s.bb[1] === 1.2)) {
  const [x0, , z0, x1, , z1] = s.bb;
  for (const [x, z] of [[x0, z0], [x1, z0], [x0, z1], [x1, z1], [(x0 + x1) / 2, (z0 + z1) / 2]]) {
    assert(Math.abs(floorAt(x, z) - 1.2) < 0.04, `the ground moved under the object at ${x}, ${z}`);
  }
}
// Grass blades change within each fifth of a metre of ground, so no square near the eye shows one glyph.
for (const [x, z] of [[-12.19, 19.81], [-30.39, 31.61], [14.61, 23.01]]) {
  const blades = new Set();
  for (let i = 0; i < 10; i++) for (let k = 0; k < 10; k++) blades.add(blade(x + i * 0.02, z + k * 0.02, 0, 0.2));
  assert(blades.size > 2, `one grass glyph fills the square at ${x}, ${z}`);
}
// The roads run through their junctions and fade out into the grass.
for (const [x, z] of NODES.slice(5, JUNCTIONS)) assert.equal(pathMask(x, z), 1, `no road at junction ${x}, ${z}`);
assert.equal(pathMask(-40, 40), 0, 'road cover away from every road');
"""
    )


def test_ground_lean_and_greens_blend_cell_by_cell():
    _run_scene(
        r"""
let mixed = 0;
for (let n = 0; n < 120; n++) {
  T = n / 12;
  const leans = new Set();
  for (let i = 0; i < 5; i++) for (let k = 0; k < 5; k++) {
    const ch = blade(-12.19 + i * 0.02, 19.81 + k * 0.02, 0, 0.2);
    if (ch === '/' || ch === '|' || ch === '\\') leans.add(ch);
  }
  if (leans.size > 1) mixed++;
}
const edges = [];
let previous = grass(-20, 1.2, 19.81), lastSwitch = -Infinity;
for (let i = 1; i <= 2000; i++) {
  const green = grass(-20 + i / 100, 1.2, 19.81);
  if (green !== previous) {
    if (i - lastSwitch > 20) edges.push(0);
    edges[edges.length - 1]++;
    lastSwitch = i;
  }
  previous = green;
}
assert(mixed > 60, `only ${mixed} moments mix tall blade leans; green switches per edge: ${edges}`);
assert(edges.length >= 3, `only ${edges.length} green edges`);
assert(edges.every(count => count >= 3), `green switches per edge: ${edges}`);
"""
    )


def test_walking_height_bounds_hold_on_the_slopes():
    _run_scene(
        r"""
// Map routes decide clearance from terrainRange, so it must bound the ground along any segment.
let seed = 7;
const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
for (let n = 0; n < 4000; n++) {
  const a = [-60 + random() * 105, -40 + random() * 94], length = random() * 12, angle = random() * 6.283;
  const c = [a[0] + length * Math.cos(angle), a[1] + length * Math.sin(angle)], [low, high] = terrainRange(a, c);
  for (let i = 0; i <= 40; i++) {
    const y = terrainY(a[0] + (c[0] - a[0]) * i / 40, a[1] + (c[1] - a[1]) * i / 40);
    assert(y >= low - 1e-9 && y <= high + 1e-9, `terrainRange misses the ground between ${a} and ${c}`);
  }
}
"""
    )
