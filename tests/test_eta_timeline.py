import importlib.util
import json
import struct
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).parents[1] / "blueprint/skills/public/eta-timeline"
# The public-skill privacy scan reads every file in the skill folder: leave no .pyc there.
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("eta_timeline", SKILL / "eta_timeline.py")
eta = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eta)

ITEMS = [
    {
        "label": "Footer",
        "group": "Landing",
        "start": "2026-10-12T16:00",
        "end": "2026-10-12T16:00",
        "state": "done",
    },
    {
        "label": "Mobile pass",
        "group": "Landing",
        "start": "2026-10-12T16:30",
        "end": "2026-10-12T18:00",
        "state": "planned",
    },
    {
        "label": "0.4.3 release",
        "group": "Crewship",
        "start": "2026-10-12T16:30",
        "end": "2026-10-12T17:30",
        "state": "moved",
    },
]


def test_renders_840_wide_png_at_least_630_tall(tmp_path):
    src, out = tmp_path / "items.json", tmp_path / "eta.png"
    src.write_text(json.dumps(ITEMS))
    subprocess.run(
        [
            sys.executable,
            str(SKILL / "eta_timeline.py"),
            str(src),
            "--tz",
            "America/Los_Angeles",
            "--now",
            "2026-10-12T16:26",
            "--out",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height >= 630) == (840, True)


def test_duration_and_ticks_follow_the_operator_clock():
    tz = eta.ZoneInfo("America/Los_Angeles")
    items = [
        {"label": "a", "group": "g", "state": s, "start": eta.parse(a, tz), "end": eta.parse(b, tz)}
        for s, a, b in (
            ("planned", "2026-10-12T16:30", "2026-10-12T18:00"),
            ("moved", "2026-10-12T23:00", "2026-10-13T00:15"),
        )
    ]
    page, _ = eta.build_page(items, tz, eta.parse("2026-10-12T16:26", tz))
    assert "1 h 30 min" in page and "1 h 15 min" in page and "4:00 PM" in page
