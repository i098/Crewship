import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import provisions  # noqa: E402

TOOL = ROOT / "tools/fleet-health"


def _components():
    code = 'import {components} from "./components.ts"; console.log(JSON.stringify(components.map(c => ({name: c.name, source: c.source}))))'
    try:
        out = subprocess.run(
            ["bun", "-e", code], cwd=TOOL, capture_output=True, text=True, check=True, timeout=60
        ).stdout
    except FileNotFoundError:
        pytest.skip("bun not installed")
    return {c["name"]: c["source"] for c in json.loads(out)}


def test_fleet_health_sources_match_provisions():
    listed = _components()
    github = {n: (s["repo"], s["prefix"]) for n, s in listed.items() if s["kind"] == "github"}
    npm = {n: s["pkg"] for n, s in listed.items() if s["kind"] == "npm"}
    for name, (repo, prefix, *_rest) in provisions.GITHUB_LATEST.items():
        if name == "sentrux-grammars":  # shares sentrux's release
            continue
        assert github.get(name) == (repo, prefix), name
    for name, pkg in provisions.NPM_LATEST.items():
        assert npm.get(name) == pkg, name
    for name, repo in provisions.OMP_PLUGINS.items():
        assert github.get(name, (None,))[0] == repo, name


def _bun(code, home):
    bun = shutil.which("bun")
    if not bun:
        pytest.skip("bun not installed")
    out = subprocess.run(
        [bun, "-e", code],
        cwd=TOOL,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": str(home)},
    ).stdout
    return json.loads(out)


def test_commands_off_path_are_found_in_cargo_and_bun_homes(tmp_path):
    for sub in (".cargo/bin", ".bun/bin"):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / ".cargo/bin/concord").write_text("#!/bin/sh\n")
    (tmp_path / ".cargo/bin/concord").chmod(0o755)
    found = _bun(
        'import {binPath} from "./components.ts"; console.log(JSON.stringify([binPath("concord"), binPath("nope-xyz")]))',
        tmp_path,
    )
    assert found == [str((tmp_path / ".cargo/bin/concord").resolve()), None]


def test_running_process_counts_by_name_or_path():
    live = _bun(
        'import {isRunning} from "./components.ts"; const live = new Set(["/h/.cargo/bin/concord", "concord"]);'
        'console.log(JSON.stringify([isRunning("concord", null, live), isRunning("x", "/h/.cargo/bin/concord", live), isRunning("herdr", "/h/herdr", live)]))',
        "/tmp",
    )
    assert live == [True, True, False]


def test_custom_build_is_never_outdated_and_prerelease_is_lower():
    states = _bun(
        'import {classify} from "./latest.ts"; console.log(JSON.stringify(['
        'classify("0.1.87-sketch3", "0.1.92", /sketch/), classify("0.1.87", "0.1.92", /sketch/),'
        'classify("1.2.0-beta.2", "1.2.0"), classify("1.2.0", "1.2.0-beta.2"), classify("1.0.0", null)]))',
        "/tmp",
    )
    assert states == ["custom", "outdated", "outdated", "up to date", "unknown"]


def test_npm_tool_version_keeps_custom_suffix_from_install_directory(tmp_path):
    cli = tmp_path / "share/lavish-axi/0.1.87-sketch9/node_modules/lavish-axi/dist/cli.mjs"
    cli.parent.mkdir(parents=True)
    cli.write_text("")
    (tmp_path / ".local/bin").mkdir(parents=True)
    (tmp_path / ".local/bin/lavish-axi").symlink_to(cli)
    version = _bun(
        'import {components} from "./components.ts"; const c = components.find(c => c.name === "lavish-axi")!;'
        "console.log(JSON.stringify(await c.installed()))",
        tmp_path,
    )
    assert version == "0.1.87-sketch9"
