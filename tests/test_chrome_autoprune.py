import importlib.util
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "blueprint/maintenance/chrome-autoprune.py"
BRIDGE = "node_modules/chrome-devtools-axi/dist/bin/chrome-devtools-axi-bridge.js"


@pytest.fixture
def autoprune(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setitem(sys.modules, "psutil", types.ModuleType("psutil"))
    spec = importlib.util.spec_from_file_location("chrome_autoprune", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        (f".local/share/crewship/chrome-devtools-axi/0.4.1/{BRIDGE}", True),
        (f".local/share/crewship/chrome-devtools-axi/0.3.0/{BRIDGE}", True),
        (f".local/share/crewship/npm/{BRIDGE}", True),
        (f".local/share/crewship/chrome-devtools-axi/{BRIDGE}", False),
        (f".local/share/crewship/other/{BRIDGE}", False),
        (f".local/share/crewship/npm/other/{BRIDGE}", False),
    ],
)
def test_only_installed_or_retired_prefix_bridges_are_recognized(
    autoprune, tmp_path, relative, expected
):
    assert autoprune.installed_bridge(str(tmp_path / relative)) is expected
