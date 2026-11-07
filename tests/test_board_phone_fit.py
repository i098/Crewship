"""board-phone-fit renders real boards in headless Chrome at 390x844."""

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

loader = importlib.machinery.SourceFileLoader(
    "board_phone_fit", str(Path(__file__).parents[1] / "blueprint/maintenance/board-phone-fit")
)
fit = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(fit)

HEAD = '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">'
WIDE = '<pre class="log">' + "x" * 120 + "</pre>"
SMALL = '<p class="note" style="font-size:12px">fine print</p>'


@pytest.fixture(autouse=True)
def needs_chrome():
    try:
        fit.chrome()
    except SystemExit:
        pytest.skip("needs headless Chrome")


def board(tmp_path, body, css=""):
    path = tmp_path / "board.html"
    path.write_text(f"{HEAD}<style>pre{{white-space:pre}}{css}</style></head><body>{body}</body></html>")
    return path


def test_fitting_board_passes(tmp_path):
    assert fit.failures(board(tmp_path, "<h1>Plan</h1><p>Short text at the default size.</p>")) == []


def test_overflow_fails_with_its_selector(tmp_path):
    found = fit.failures(board(tmp_path, WIDE))
    assert found[0].startswith("overflow: page is ")
    assert any("pre.log" in line for line in found[1:])


def test_text_under_14px_fails_with_its_selector(tmp_path):
    assert fit.failures(board(tmp_path, SMALL)) == ['text: html > body > p.note is 12px: "fine print"']


def test_shared_mobile_css_fixes_wrapping_and_small_text(tmp_path):
    assert fit.failures(board(tmp_path, WIDE + SMALL.replace(' style="font-size:12px"', ""), "p{font-size:12px}" + fit.MOBILE_CSS)) == []
