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


def test_shared_mobile_css_wraps_but_leaves_small_text_failing(tmp_path):
    found = fit.failures(board(tmp_path, WIDE + SMALL, "pre{font-size:16px}" + fit.MOBILE_CSS))
    assert found == ['text: html > body > p.note is 12px: "fine print"']


def test_flex_columns_fail_until_shared_css_stacks_them(tmp_path):
    cols = '<div class="cols"><div>Left column text</div><div>Right column text</div></div>'
    css = ".cols{display:flex;gap:16px} .cols>div{flex:1}"
    assert fit.failures(board(tmp_path, cols, css)) == ["columns not stacked: html > body > div.cols"]
    assert fit.failures(board(tmp_path, cols, css + fit.MOBILE_CSS)) == []


def test_columns_with_centered_unequal_heights_fail(tmp_path):
    cols = '<div class="cols"><div>One<br>two<br>three</div><div>Right</div></div>'
    css = ".cols{display:flex;align-items:center;gap:16px} .cols>div{flex:1}"
    assert fit.failures(board(tmp_path, cols, css)) == ["columns not stacked: html > body > div.cols"]


@pytest.mark.parametrize("row", [
    '<div style="display:inline-flex;gap:8px"><div style="width:150px">alpha</div><div style="width:150px">beta</div></div>',
    '<div class="no-stack" style="display:flex;gap:8px"><div style="width:150px">alpha</div><div style="width:150px">beta</div></div>',
    '<div style="display:flex;gap:8px"><div class="pill" style="width:150px">alpha</div><div class="pill" style="width:150px">beta</div></div>',
    '<table><tr><td style="width:150px">alpha</td><td style="width:150px">beta</td></tr></table>',
    '<div class="no-stack" style="display:grid;grid-template-columns:repeat(2,1fr)"><div>alpha</div><div>beta</div></div>',
])
def test_pill_rows_are_not_columns(tmp_path, row):
    assert fit.failures(board(tmp_path, row)) == []


def test_grid_of_list_items_fails_until_shared_css_stacks_it(tmp_path):
    grid = '<ul class="cards"><li>First card</li><li>Second card</li></ul>'
    css = ".cards{display:grid;grid-template-columns:1fr 1fr;padding:0;list-style:none}"
    assert fit.failures(board(tmp_path, grid, css)) == ["columns not stacked: html > body > ul.cards"]
    assert fit.failures(board(tmp_path, grid, css + fit.MOBILE_CSS)) == []
