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


def test_scene_renders_through_its_own_entry_and_software_gl():
    cmd = render.command("src/scenes/moon.tsx", "o.mp4", 3)
    assert cmd[3:5] == ["src/scenes/moon.tsx", "Scene"] and "--gl=swangle" in cmd and "--frames=0-89" in cmd


def test_review_command_selects_every_nth_frame():
    cmd = render.review_command("o.mp4", Path("f"), 15)
    assert "select=not(mod(n\\,15))" in cmd and cmd[-1] == "f/%04d.png"
