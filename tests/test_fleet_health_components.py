import json
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
