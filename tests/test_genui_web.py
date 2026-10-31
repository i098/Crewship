import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
# genui-server first: the genui-web contract test spawns its wrangler, which only exists after that install.
SUITES = ["apps/genui-server", "apps/genui-web", "packages/genui-agent-kit", "packages/genui-spec"]


@pytest.mark.parametrize("suite", SUITES)
def test_genui_bun_suite(suite):
    # CI runs pytest only, so every genui bun suite is run from here.
    if not shutil.which("bun"):
        print(f"skipped {suite}: bun is not on PATH")
        pytest.skip("needs bun")
    subprocess.run(
        ["bun", "install", "--frozen-lockfile"],
        cwd=ROOT / suite,
        check=True,
        capture_output=True,
        timeout=180,
    )
    run = subprocess.run(
        ["bun", "test"], cwd=ROOT / suite, capture_output=True, text=True, timeout=180
    )
    assert run.returncode == 0, run.stdout + run.stderr
