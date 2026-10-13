#!/usr/bin/env python3
"""Self-review of a captured walk: per-leg motion stats, contact sheets, and an eye-to-geometry check.

usage: review.py FRAMES_DIR OUTDIR [BOXES.json]
FRAMES_DIR holds the frames and log.json from capture.mjs. Per leg it prints the length, the peak yaw rate, and
the worst angle between where the camera moves and where it looks (facing error). It writes OUTDIR/legNN.png:
one tile every 0.5 s, every 4 frames for 0.4 s around each door crossing, and around the fastest turn.
BOXES.json, optional: [{"bb": [x0, y0, z0, x1, y1, z1], "name": "...", "room": null | "name"}], every scene box,
solid or not. It prints each run of frames where the eye comes within 0.45 m of a box above the floor.
"""

import json
import math
import subprocess
import sys
from pathlib import Path


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def legs(log):
    n, tr = log["frames"], log["track"]
    marks = [(round(t * log["fps"]), name) for t, name in log["marks"]] + [(n, "")]
    cross = {i for i in range(1, len(tr)) if tr[i][4] != tr[i - 1][4]}
    for (a, name), (b, _) in zip(marks, marks[1:]):
        steady = [i for i in range(max(a, 1), min(b, len(tr))) if i not in cross]
        if b - a < 2 or not steady:
            continue
        rate = {i: abs(wrap(tr[i][2] - tr[i - 1][2])) * log["fps"] for i in steady}
        facing = [
            abs(wrap(math.atan2(tr[i][0] - tr[i - 1][0], tr[i][1] - tr[i - 1][1]) - tr[i][2]))
            for i in steady
            if math.hypot(tr[i][0] - tr[i - 1][0], tr[i][1] - tr[i - 1][1]) * log["fps"] > 0.3
        ]
        yield {
            "leg": name,
            "from": a,
            "to": b,
            "max_yaw_rate": max(rate.values()),
            "fastest": max(rate, key=rate.get),
            "facing_deg": math.degrees(max(facing, default=0)),
            "crossings": sorted(c for c in cross if a <= c < b),
        }


def near(log, boxes, lim=0.45):
    """Runs of frames [(first, last, box name, min metres)] where the eye is within lim of a box above the floor."""
    cells = {}  # boxes by room and 2 m cell, so each frame tests only the boxes around it
    for b in boxes:
        x0, _, z0, x1, _, z1 = b["bb"]
        for i in range(math.floor((x0 - lim) / 2), math.floor((x1 + lim) / 2) + 1):
            for j in range(math.floor((z0 - lim) / 2), math.floor((z1 + lim) / 2) + 1):
                cells.setdefault((b.get("room"), i, j), []).append(b)
    runs = []
    for f, (x, z, _, _, room, eye) in enumerate(log["track"]):
        best = None
        for b in cells.get((room, math.floor(x / 2), math.floor(z / 2)), []):
            x0, y0, z0, x1, y1, z1 = b["bb"]
            if y1 < eye - 1.25 or y0 > eye + 1.0:  # the floor under you and things far overhead
                continue
            d = math.dist(
                (0, 0, 0),
                (max(0, x0 - x, x - x1), max(0, y0 - eye, eye - y1), max(0, z0 - z, z - z1)),
            )
            if d < lim and (best is None or d < best[1]):
                best = (b["name"], d)
        if best:
            if runs and runs[-1][2] == best[0] and runs[-1][1] == f - 1:
                runs[-1] = (runs[-1][0], f, best[0], min(runs[-1][3], best[1]))
            else:
                runs.append((f, f, best[0], best[1]))
    return runs


def sheet(frames_dir, picks, out):
    lst = out.with_suffix(".txt")
    lst.write_text(
        "".join(f"file '{frames_dir.resolve()}/{i:05d}.png'\nduration 1\n" for i in picks)
    )
    rows = math.ceil(len(picks) / 6)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-vf",
            f"scale=340:-2,tile=6x{rows}:padding=2",
            "-frames:v",
            "1",
            str(out),
        ],
        check=True,
    )
    lst.unlink()


def main():
    frames_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    log = json.loads((frames_dir / "log.json").read_text())
    for k, leg in enumerate(legs(log)):
        a, b = leg["from"], leg["to"]
        picks = set(range(a, b, 30)) | {leg["fastest"] + d for d in (-6, 0, 6)}
        for c in leg["crossings"]:
            picks |= set(range(max(a, c - 24), min(b, c + 24), 4))
        picks = sorted(i for i in picks if (frames_dir / f"{i:05d}.png").exists())
        if picks:
            sheet(frames_dir, picks, out / f"leg{k:02d}.png")
        print(
            f"{k:2} {leg['leg'][:44]:44} {(b - a) / log['fps']:5.1f}s  yaw rate {leg['max_yaw_rate']:4.2f} rad/s"
            f"  facing {leg['facing_deg']:4.1f} deg  crossings {len(leg['crossings'])}"
        )
    if len(sys.argv) > 3:
        for f0, f1, name, d in near(log, json.loads(Path(sys.argv[3]).read_text())):
            print(f"near {f0}-{f1} ({(f1 - f0 + 1) / log['fps']:.1f}s) {name} {d:.2f} m")


if __name__ == "__main__":
    main()
