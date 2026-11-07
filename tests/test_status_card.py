"""fm-status-card: the text and JSON inputs parse to one card, and the page shows each part."""

import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

CARD = Path(__file__).parents[1] / "blueprint/maintenance/fm-status-card"
TEXT = """Fleet status
- code-factory: merged 4, open 2, 3 today, running
- swarms: open 1 · Waiting on you · needs the screenshot OK
- plain bullet: fix CI, then ship
disk: 62%
# Next
eta: 40 min
"""
CARD_DATA = {
    "title": "Fleet status",
    "projects": [
        {"name": "code-factory", "merged": 4, "open": 2, "today": 3, "states": ["running"], "note": ""},
        {"name": "swarms", "merged": 0, "open": 1, "today": 0, "states": ["waiting on you"], "note": "needs the screenshot OK"},
    ],
    "gauges": {"disk": 62},
    "today_since": None,
    "notes": ["- plain bullet: fix CI, then ship", "# Next", "eta: 40 min"],
}


@pytest.fixture
def card():
    loader = importlib.machinery.SourceFileLoader("fm_status_card", str(CARD))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def test_text_format_parses_projects_gauges_and_notes(card):
    assert card.parse(TEXT) == CARD_DATA


def test_json_input_parses_to_the_same_card(card):
    data = {**CARD_DATA, "projects": [{**p, "states": [s.title() for s in p["states"]], "today": str(p["today"])} for p in CARD_DATA["projects"]]}
    data["projects"][1]["states"].append("unknown")
    assert card.parse(json.dumps(data)) == CARD_DATA


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_page_has_rows_chips_and_only_hsl_colors(card, theme):
    data = card.parse(TEXT.replace("code-factory", "a <b>"))
    page, height = card.render(data, theme)
    assert "a &lt;b&gt;" in page and "67% merged" in page and "waiting on you" in page and "62%" in page
    assert not re.search(r"#[0-9a-f]{3,6}\b|rgb\(", page)
    assert height == 2 * card.PAD + card.TITLE + card.GAUGES + 3 * card.GAP + 2 * card.ROW + card.ROW_NOTE + card.HEAD + 2 * card.NOTE


def test_heading_over_only_projects_is_dropped(card):
    page, _ = card.render(card.parse("T\n# Projects\n- a: open 1\ndisk: 5%"))
    assert "<h2>" not in page


@pytest.mark.parametrize(
    ("env", "now", "start", "name"),
    [
        # 03:00 UTC is still the evening before in Los Angeles, so "today" began the day before.
        ({"STATUS_CARD_TZ": "America/Los_Angeles", "TZ": "UTC"}, "2026-11-07T03:00:00+00:00", "2026-11-06T00:00:00-08:00", "America/Los_Angeles"),
        ({"TZ": ":Europe/Berlin"}, "2026-11-06T23:30:00+00:00", "2026-11-07T00:00:00+01:00", "Europe/Berlin"),
        # A zone name that does not exist falls through to the next source.
        ({"STATUS_CARD_TZ": "Not/AZone", "TZ": "Asia/Tokyo"}, "2026-11-06T16:00:00+00:00", "2026-11-07T00:00:00+09:00", "Asia/Tokyo"),
    ],
)
def test_today_start_is_local_midnight(card, monkeypatch, env, now, start, name):
    monkeypatch.delenv("STATUS_CARD_TZ", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert card.today_start(card.datetime.fromisoformat(now)).isoformat() == start
    page, _ = card.render(card.parse(json.dumps({"title": "T", "projects": [{"name": "a", "open": 1}], "gauges": {"Disk": 5},
                                                 "today_since": start})))
    assert f"Today counts from 00:00, {name} time." in page


def test_parser_keeps_today_since_from_json(card):
    assert card.parse('{"title": "T", "today_since": "2026-11-07T00:00:00-08:00"}')["today_since"] == "2026-11-07T00:00:00-08:00"


@pytest.mark.parametrize("bad", ["2026-11-07T00:00:00", "yesterday", 5, None])
def test_unusable_today_since_prints_no_footer(card, bad):
    c = card.parse(json.dumps({"title": "T", "projects": [{"name": "a", "open": 1}], "gauges": {"Disk": 5}, "today_since": bad}))
    assert c["today_since"] is None and "Today counts" not in card.render(c)[0]


@pytest.mark.parametrize(
    ("tz", "since", "shown"),
    [("America/Los_Angeles", "2026-11-06T08:00:00+00:00", "00:00"), ("Asia/Tokyo", "2026-11-06T15:30:00+00:00", "00:30")],
)
def test_footer_shows_the_cutoff_in_the_card_zone(card, monkeypatch, tz, since, shown):
    monkeypatch.setenv("STATUS_CARD_TZ", tz)
    c = card.parse(json.dumps({"title": "T", "projects": [{"name": "a", "open": 1}], "gauges": {"Disk": 5}, "today_since": since}))
    assert f"Today counts from {shown}, {tz} time." in card.render(c)[0]


def test_card_without_today_since_has_no_zone_footer(card):
    page, _ = card.render(card.parse("T\n- a: open 1\ndisk: 5%"))
    assert "Today counts" not in page


def test_send_texts_the_png_and_deletes_it(card, monkeypatch):
    shots, calls = [], []
    monkeypatch.setattr(card, "shoot", lambda c, theme, out: shots.append(out))
    monkeypatch.setattr(card.subprocess, "run", lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0))
    card.send(CARD_DATA, "dark")
    assert calls == [["fm-imessage", "--image", shots[0]]] and not os.path.exists(shots[0])


@pytest.mark.parametrize(("load", "timeout"), [(10, 60), (96, 120), (192, 240), (960, 300)])
def test_screenshot_timeout_grows_with_load_per_core(card, monkeypatch, load, timeout):
    text_card = card.sibling("fm-text-card")
    monkeypatch.setattr(text_card.os, "getloadavg", lambda: (load, 0, 0))
    monkeypatch.setattr(text_card.os, "cpu_count", lambda: 96)
    monkeypatch.setattr(text_card, "chrome", lambda: "chrome")
    seen = []
    monkeypatch.setattr(text_card.subprocess, "run", lambda argv, **kw: seen.append(kw["timeout"]))
    text_card.shoot("<p>x</p>", 100, "out.png")
    assert seen == [timeout]


class FakeTextCard:
    """fm-text-card whose screenshot fails the first `fails` times."""

    def __init__(self, fails):
        self.fails, self.shots = fails, []

    def render(self, text):
        return f"text:{text}", 1

    def shoot(self, page, height, out, width=840):
        self.shots.append(page)
        if len(self.shots) <= self.fails:
            raise subprocess.TimeoutExpired("chrome", 60)


def test_a_failed_screenshot_is_retried_once(card, monkeypatch):
    fake = FakeTextCard(fails=1)
    monkeypatch.setattr(card, "sibling", lambda name: fake)
    card.shoot(CARD_DATA, "dark", "out.png")
    assert len(fake.shots) == 2 and not fake.shots[1].startswith("text:")


def test_two_failed_screenshots_fall_back_to_the_text_card(card, monkeypatch):
    fake = FakeTextCard(fails=2)
    monkeypatch.setattr(card, "sibling", lambda name: fake)
    card.shoot(CARD_DATA, "dark", "out.png")
    assert len(fake.shots) == 3
    assert fake.shots[2].splitlines()[:3] == [
        "text:Fleet status",
        "- code-factory: merged 4, open 2, today 3, running",
        "- swarms: merged 0, open 1, today 0, waiting on you, needs the screenshot OK",
    ]
    # The fallback text parses back to the same projects.
    assert card.parse(fake.shots[2].removeprefix("text:"))["projects"] == CARD_DATA["projects"]


def test_a_failed_fallback_raises(card, monkeypatch):
    monkeypatch.setattr(card, "sibling", lambda name: FakeTextCard(fails=3))
    with pytest.raises(subprocess.TimeoutExpired):
        card.shoot(CARD_DATA, "dark", "out.png")
