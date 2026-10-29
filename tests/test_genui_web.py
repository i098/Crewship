import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).parents[1] / "apps/genui-web"


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_genui_web_canvas_suite():
    # CI runs pytest only; the canvas model and mock-server contract tests live in bun.
    run = subprocess.run(["bun", "test"], cwd=APP, capture_output=True, text=True, timeout=180)
    assert run.returncode == 0, run.stdout + run.stderr
