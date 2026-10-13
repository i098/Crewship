"""The site-walkthrough-video skill: the camera controller, the near-geometry check and the sound gate."""

import importlib.util
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).parents[1] / "blueprint/skills/public/site-walkthrough-video"
sys.dont_write_bytecode = True


def load(name):
    spec = importlib.util.spec_from_file_location(name, SKILL / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# An L-shaped corridor, 3 m wide, on a 0.1 m grid: east 12 m along z = 1.5, then north 10 m along x = 10.5.
# The controller walks it from a standing start facing north (90 degrees off the first leg), stops at the end,
# then turns to look at a point. Kinematics: the view follows the controller exactly, the walk moves forward at
# the key speed times the forward duty, and a step into a wall is refused, as a site's collision does.
WALK = r"""
import { grid, path, Ctl, DT } from "./walk.mjs";
const R = 0.1, nx = 140, nz = 140, fy = [], bl = [];
for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
  const x = (i + 0.5) * R, z = (j + 0.5) * R, open = (z < 3 && x < 12) || (x > 9 && x < 12 && z < 13);
  fy.push(1); bl.push(open ? 0 : 1);
}
const g = grid({ x0: 0, z0: 0, R, nx, nz, fy, bl });
const legs = [{ name: "L", path: path(g, [[1, 1.5], [10.5, 1.5], [10.5, 11]]), grid: g, end: "stop", looks: [{ at: [10.5, 1.6, 20], hold: 0.5 }] }];
const ctl = new Ctl(legs), p = { x: 1, z: 1.5, yaw: 0, pitch: 0, eye: 2.6 }, out = { yawStep: 0, bumps: 0, minClear: 9, speeds: [] };
for (let f = 0; f < 60 * 40 && !ctl.done; f++) {
  const o = ctl.step(p);
  out.yawStep = Math.max(out.yawStep, Math.abs(Math.atan2(Math.sin(o.yaw - p.yaw), Math.cos(o.yaw - p.yaw))));
  p.yaw = o.yaw; p.pitch = o.pitch;
  const v = 3.4 * o.f * DT, nx2 = p.x + Math.sin(p.yaw) * v, nz2 = p.z + Math.cos(p.yaw) * v;
  if (v > 0) {
    if (g.clear(nx2, nz2) > 0) { p.x = nx2; p.z = nz2; } else out.bumps++;
    out.minClear = Math.min(out.minClear, g.clear(p.x, p.z));
  }
  out.speeds.push([p.x, p.z, v / DT]);
}
Object.assign(out, { done: ctl.done, end: [p.x, p.z], yaw: p.yaw });
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def walk():
    if not shutil.which("node"):
        pytest.skip("needs node")
    run = subprocess.run(
        ["node", "--input-type=module", "-e", WALK],
        cwd=SKILL,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(run.stdout)


def test_walk_reaches_the_end_turns_smoothly_and_looks_at_the_target(walk):
    assert walk["done"], "the controller never finished the leg and its look"
    assert abs(walk["end"][0] - 10.5) < 0.15 and abs(walk["end"][1] - 11) < 0.15
    assert walk["bumps"] == 0 and walk["minClear"] > 0.35, (
        "the path must keep off the walls, the inside corner too"
    )
    # no snap: the largest change of view in one frame is small, even for the 90 degree start and the corner
    assert walk["yawStep"] < 0.06
    assert abs(math.atan2(math.sin(walk["yaw"]), math.cos(walk["yaw"]))) < 0.05, (
        "the final look faces the target (+z)"
    )


def test_walk_slows_into_the_corner_and_stops_at_the_end(walk):
    speeds = walk["speeds"]
    straight = max(v for x, z, v in speeds if 4 < x < 7 and z < 3)
    corner = min(v for x, z, v in speeds if 8 < x < 12 and 1 < z < 4)
    assert corner < 0.6 * straight
    assert speeds[-1][2] == 0


def test_near_flags_a_box_the_eye_passes_and_ignores_the_floor():
    review = load("review")
    track = [[x / 10, 0.0, 0.0, 0.0, None, 1.6] for x in range(40)]
    boxes = [
        {"bb": [-50, -1, -50, 50, 0, 50], "name": "ground"},
        {"bb": [2.0, 1.4, -0.2, 2.3, 2.2, 0.2], "name": "tree crown"},
    ]
    runs = review.near({"track": track, "fps": 60}, boxes)
    assert [(r[2], r[3]) for r in runs] == [("tree crown", 0.0)]
    assert runs[0][0] <= 20 <= runs[0][1]


def test_sound_is_silent_until_the_first_click():
    np = pytest.importorskip("numpy")
    synth = load("synth")
    log = {
        "frames": 120,
        "fps": 60,
        "steps": [0.2, 1.5],
        "clicks": [1.0],
        "rooms": [],
        "doors": [],
    }
    out = synth.mix(log)
    assert np.abs(out[: int(0.9 * synth.SR)]).max() < 1e-6
    assert np.abs(out[int(1.3 * synth.SR) :]).max() > 0.05
