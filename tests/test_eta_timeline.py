import importlib.util
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

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


@pytest.mark.parametrize(("flags", "card_exit"), [([], 0), (["--card"], 0), (["--card"], 22)])
def test_send_is_a_png_unless_card_is_asked_for(tmp_path, flags, card_exit):
    png = not flags or card_exit
    if png:
        try:
            eta.chrome()
        except SystemExit:
            pytest.skip("the PNG needs headless Chrome")
    log, src = tmp_path / "calls.jsonl", tmp_path / "items.json"
    src.write_text(json.dumps(ITEMS))
    stub = tmp_path / "bin/fm-imessage"
    stub.parent.mkdir()
    stub.write_text(
        f"#!{sys.executable}\nimport json, sys\ncard = '--card' in sys.argv\n"
        f"with open({str(log)!r}, 'a') as f:\n"
        "    f.write(json.dumps([sys.argv[1:], sys.stdin.read() if card else '']) + '\\n')\n"
        f"sys.exit({card_exit} if card else 0)\n"
    )
    stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}"}
    subprocess.run(
        [sys.executable, str(SKILL / "eta_timeline.py"), str(src), "--tz", "America/Los_Angeles"]
        + ["--now", "2026-10-12T16:26", "--send", "Landing ETA", *flags],
        check=True,
        capture_output=True,
        env=env,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    if flags:
        assert calls[0][0] == ["--card", "-"]
        card = json.loads(calls.pop(0)[1])
        assert (card["kind"], card["title"], len(card["items"])) == ("timeline", "Landing ETA", 3)
        assert card["items"][0]["text"].endswith(" (done)")
        assert card["items"][1]["when"] == "4:30 PM – 6:00 PM"
    assert [c[0][0] for c in calls] == (["--image"] if png else [])


@pytest.mark.parametrize(
    ("percent", "label"),
    [(None, "1 h"), (25, "25% · 1 h"), (250, "100% · 1 h"), (-5, "0% · 1 h")],
)
def test_percent_is_given_or_clamped_not_derived(percent, label):
    tz = eta.ZoneInfo("America/Los_Angeles")
    item = {"label": "a", "group": "g", "state": "planned", "percent": percent}
    item |= {"start": eta.parse("2026-10-12T16:00", tz), "end": eta.parse("2026-10-12T17:00", tz)}
    page, _ = eta.build_page([item], tz, eta.parse("2026-10-12T16:30", tz))
    assert f">{label}</span>" in page
    assert ("rgba(0,0,0,.28)" in page.split("</style>")[1]) == (
        percent is not None and 0 < percent < 100
    )


def chart_geometry(tmp_path, end, start="2026-10-19T09:00"):
    tz = eta.ZoneInfo("America/Los_Angeles")
    now = eta.parse(start, tz) + eta.timedelta(hours=1)
    item = {
        "label": "Phase 1",
        "group": "Landing",
        "state": "planned",
        "start": eta.parse(start, tz),
        "end": eta.parse(end, tz),
    }
    page, _ = eta.build_page([item], tz, now)
    script = """<script>
    const box = e => {
        const r = e.getBoundingClientRect();
        return {left:r.left, right:r.right, top:r.top, bottom:r.bottom, text:e.textContent};
    };
    const result = {
        ticks: [...document.querySelectorAll('.tick')].map(box),
        heading: box(document.querySelector('h1')),
        now: box(document.querySelector('.nowl'))
    };
    const output = document.createElement('pre');
    output.id = 'geometry';
    output.textContent = JSON.stringify(result);
    document.body.append(output);
    </script>"""
    src = tmp_path / "chart.html"
    src.write_text(page.replace("</body>", script + "</body>"))
    result = subprocess.run(
        [
            eta.chrome(), "--headless=new", "--no-sandbox", "--window-size=840,630",
            "--dump-dom", src.as_uri(),
        ],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout.split('<pre id="geometry">')[1].split("</pre>")[0])


@pytest.mark.parametrize(
    "end", ["2026-10-20T15:00", "2026-10-26T17:00", "2027-10-26T17:00", "2036-10-26T17:00"]
)
def test_long_range_tick_labels_do_not_overlap(tmp_path, end):
    boxes = chart_geometry(tmp_path, end)["ticks"]
    assert all(a["right"] + 8 <= b["left"] for a, b in zip(boxes, boxes[1:]))
    assert all(0 <= box["left"] < box["right"] <= 840 for box in boxes)


@pytest.mark.parametrize(
    ("end", "second_tick"),
    [("2026-04-23", "Jan 29"), ("2026-04-27", "Jan 30"), ("2026-05-01", "Jan 31")],
)
def test_fixed_day_ticks_in_one_month_keep_distinct_labels(tmp_path, end, second_tick):
    boxes = chart_geometry(tmp_path, end, start="2026-01-01")["ticks"]
    labels = [box["text"] for box in boxes]
    assert labels[:2] == ["Jan 1", second_tick]
    assert len(set(labels)) == len(labels)
    assert all(a["right"] + 8 <= b["left"] for a, b in zip(boxes, boxes[1:]))
    assert all(0 <= box["left"] < box["right"] <= 840 for box in boxes)


def test_midnight_ticks_identify_each_day(tmp_path):
    ticks = chart_geometry(tmp_path, "2026-10-20T15:00")["ticks"]
    midnight_labels = [tick["text"] for tick in ticks if "12AM" in tick["text"]]
    assert len(midnight_labels) == 3
    assert len(set(midnight_labels)) == 3


def test_now_label_is_below_heading(tmp_path):
    boxes = chart_geometry(tmp_path, "2026-10-26T17:00")
    assert boxes["heading"]["bottom"] < boxes["now"]["top"]
