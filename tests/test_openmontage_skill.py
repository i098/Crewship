import importlib.util
import os
import sys
import time
from pathlib import Path

SKILL = Path(__file__).parents[1] / "blueprint/skills/public/openmontage"
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("om_render", SKILL / "render.py")
render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)


def test_prune_removes_only_old_entries(tmp_path):
    old, new = tmp_path / "old.mp4", tmp_path / "new.mp4"
    old.write_text("x")
    new.write_text("x")
    t = time.time() - 2 * 86400
    os.utime(old, (t, t))
    render.prune(tmp_path)
    assert not old.exists() and new.exists()


def test_command_limits_frames_only_when_seconds_given():
    full = render.command("p.json", "o.mp4")
    assert not any(a.startswith("--frames") for a in full)
    assert "--frames=0-89" in render.command("p.json", "o.mp4", 3)
