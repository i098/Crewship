"""The crewship npm package ships only its installer launcher, never the rest of the repository."""

import json
import os
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


@pytest.mark.skipif(not (shutil.which("npm") and shutil.which("node")), reason="needs npm and node")
@pytest.mark.parametrize("os_name", ["linux", "darwin", "win32"])
def test_packed_tarball_installs_and_runs_its_bin(tmp_path, os_name):
    subprocess.run(["npm", "pack", "--pack-destination", str(tmp_path)], cwd=PACKAGE, capture_output=True, check=True)
    (tarball,) = tmp_path.glob("crewship-*.tgz")
    # npm_config_os makes npm judge the install as on that OS: a package "os" field fails it with EBADPLATFORM.
    env = {**os.environ, "npm_config_os": os_name, "npm_config_cache": str(tmp_path / "cache")}
    subprocess.run(
        ["npm", "install", "-g", "--prefix", str(tmp_path / "prefix"), "--offline", str(tarball)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    bin_path = tmp_path / "prefix/bin/crewship"
    version = json.loads((PACKAGE / "package.json").read_text())["version"]
    for flag in ("--version", "--help"):
        result = subprocess.run([str(bin_path), flag], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Usage: crewship ")
    assert subprocess.run([str(bin_path), "--version"], capture_output=True, text=True).stdout == f"{version}\n"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_launcher_off_ubuntu_says_where_to_run_it_and_never_fetches(tmp_path):
    stub = tmp_path / "darwin.js"
    stub.write_text(
        "Object.defineProperty(process, 'platform', { value: 'darwin' });\n"
        "globalThis.fetch = () => { throw new Error('fetch called'); };\n"
    )
    run = lambda *args: subprocess.run(  # noqa: E731
        [shutil.which("node"), "--require", str(stub), str(PACKAGE / "crewship.js"), *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    for args in ([], ["update"]):
        result = run(*args)
        assert result.returncode == 1
        assert "installs on an Ubuntu 24.04 or 26.04 server, not on darwin" in result.stderr
    assert run("--version").returncode == 0
    assert run("--help").returncode == 0
