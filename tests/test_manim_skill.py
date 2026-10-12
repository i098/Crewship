import importlib.util
import os
import sys
import time
from pathlib import Path

SKILL = Path(__file__).parents[1] / "blueprint/skills/public/manim"
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("render", SKILL / "render.py")
render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)


def test_prune_removes_only_old_entries(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "a.mp4").write_text("x")
    t = time.time() - 2 * 86400
    os.utime(old, (t, t))
    render.prune(tmp_path)
    assert not old.exists() and new.exists()


def test_command_gif_and_quality():
    cmd = render.command("s.py", "Demo", "h", True, Path("/m"))
    assert "--format=gif" in cmd and "-qh" in cmd and cmd[-2:] == ["s.py", "Demo"]
