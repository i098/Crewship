"""The crewship npm package ships only its installer launcher, never the rest of the repository."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parents[1] / "tools/npm"


@pytest.mark.skipif(not shutil.which("npm"), reason="needs npm")
def test_tarball_holds_only_the_launcher():
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--json"],
        cwd=PACKAGE,
        capture_output=True,
        text=True,
        check=True,
    )
    files = {entry["path"] for entry in json.loads(result.stdout)[0]["files"]}
    assert files == {"package.json", "README.md", "crewship.js"}
