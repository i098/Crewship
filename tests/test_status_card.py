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


def test_send_texts_the_png_and_deletes_it(card, monkeypatch):
    shots, calls = [], []
    monkeypatch.setattr(card, "shoot", lambda c, theme, out: shots.append(out))
    monkeypatch.setattr(card.subprocess, "run", lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0))
    card.send(CARD_DATA, "dark")
    assert calls == [["fm-imessage", "--image", shots[0]]] and not os.path.exists(shots[0])
