"""Check paving and shore glyphs without starting the browser scene."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_paving_and_shore_glyphs_and_colours():
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            r"""
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
const source = fs.readFileSync(process.argv[1], "utf8");
const names = ["plazaCurb", "plazaStone", "plazaPaving", "wetSand",
  "waterFoam", "waterReflection", "waterGlyph"];
const functions = names.map(name =>
  source.match(new RegExp(`^function ${name}\\(.*?^}`, "ms"))[0]);
const constants = ["hash", "RAMP", "tier", "glyph", "SEA"].map(name =>
  source.match(new RegExp(`^const ${name} = .*;$`, "m"))[0]);
const put = source.match(/^function put\(.*$/m)[0];
vm.runInNewContext([...constants, ...functions, put, `
let T = 0;
const G = [], C = [], ID = [], D = [];
// Joint line, curb stone, curb joint and open stone include material and glyph.
assert.equal(plazaPaving(4.81, 24.5, 0.3), "s|");
assert.equal(plazaPaving(5.2, 24.31, 0.3), "s-");
assert.equal(plazaPaving(8, 24.6, 3), "s=");
const jointAngle = 3.004166666666667 - Math.PI;
assert.equal(plazaPaving(5 + 3 * Math.cos(jointAngle),
  24.6 + 3 * Math.sin(jointAngle), 3), "t:");
assert.match(plazaPaving(5.2, 24.5, 0.3), /^t[,.]$/);
// A moving foam edge and wet sand retain distinct colours and glyphs.
assert.equal(wetSand(0, 0.12, 0), "k~");
assert.equal(wetSand(0, 0.3, 0), "n:");
assert.equal(wetSand(0, 0.5, 0), null);
waterGlyph(0, 10, waterFoam(0, 0, 0, 1), 0.05, 1, "w");
assert.equal(G[0], "~");
assert.equal(C[0], "k4");
assert.equal(waterFoam(0, 0, 0, 0), 0);
waterGlyph(0, 10, waterFoam(0, 0, 0, 0), 0.12, 1, "d");
assert.equal(G[0], String.fromCharCode(96));
assert.equal(C[0], "d1");
assert.equal(waterReflection(0.2, 0.15), "l");
assert.equal(waterReflection(0.15, 0.2), "m");
assert.equal(waterReflection(0.1, 0.1), null);
`].join("\n"), { assert });
""",
            str(ROOT / "harbor/public/harbor.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_touch_redraw_repaints_changed_runs_and_leaves_the_rest():
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            r"""
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
const source = fs.readFileSync(process.argv[1], "utf8");
const names = ["draw", "update", "forgetSign", "redraw", "paint", "edge", "outline", "drawMap", "drawSign"];
const functions = names.map(name =>
  source.match(new RegExp(`^function ${name}\\(.*?^}`, "ms"))[0]);
const constants = ["beyond", "slope", "snap"].map(name =>
  source.match(new RegExp(`^const ${name} = .*;$`, "m"))[0]);
vm.runInNewContext([...constants, ...functions, `
const painted = [];
const ctx = { save() {}, restore() {}, beginPath() {}, rect() {}, clip() {}, fillRect() {},
  fillText(ch, x, y) { painted.push([x, y, ch]); } };
const touchFirst = { matches: true }, COLORS = { k: "#fff" }, MAPCELLS = new Map(), LINE = new Map();
const BACKGROUND = "#000", cols = 40, rows = 3, padX = 0, padY = 0, cellW = 1, cellH = 1, dpr = 1, viewW = 40, viewH = 3;
const introProgress = 1, target = null, mapBox = null, signBox = null;
let signDrawn = null;
const G = Array(cols * rows).fill("."), C = Array(cols * rows).fill("k"), DG = [...G], DC = [...C];
const ID = new Int32Array(cols * rows), D = new Float32Array(cols * rows), SP = [];
// Two separate changes on the middle row: two cells at the left and two near the right.
const changed = [3, 4, 30, 33];
for (const i of changed) G[cols + i] = "#";
draw(-1);
for (const i of changed) {
  assert(painted.some(([x, y, ch]) => x === i && y === 1 && ch === "#"), "a changed cell was not repainted");
}
assert(painted.every(([x, y]) => y === 1), "unchanged rows were repainted");
assert(!painted.some(([x]) => x >= 10 && x <= 25), "cells far from any change were repainted");
`].join("\n"), { assert });
""",
            str(ROOT / "harbor/public/harbor.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
