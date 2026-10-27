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
        if name == "concord":  # now installed from npm; provisions.py still lists the old release
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
    (tmp_path / ".cargo/bin/sgrep").write_text("#!/bin/sh\n")
    (tmp_path / ".cargo/bin/sgrep").chmod(0o755)
    found = _bun(
        'import {binPath} from "./components.ts"; console.log(JSON.stringify([binPath("sgrep"), binPath("nope-xyz")]))',
        tmp_path,
    )
    assert found == [str((tmp_path / ".cargo/bin/sgrep").resolve()), None]


def test_running_process_counts_by_name_or_path():
    live = _bun(
        'import {isRunning} from "./components.ts"; const live = new Set(["/h/.cargo/bin/sgrep", "sgrep"]);'
        'console.log(JSON.stringify([isRunning("sgrep", null, live), isRunning("x", "/h/.cargo/bin/sgrep", live), isRunning("herdr", "/h/herdr", live)]))',
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


def test_newest_atime_walks_package_dir_and_missing_path_is_none(tmp_path):
    import os

    pkg = tmp_path / "pkg/sub"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text("")
    os.utime(pkg / "a.py", (1_700_000_000, 1_700_000_000))
    (tmp_path / "pkg/b.py").write_text("")
    os.utime(tmp_path / "pkg/b.py", (1_800_000_000, 1_700_000_000))
    out = _bun(
        'import {newestAtime} from "./components.ts";'
        f'console.log(JSON.stringify([newestAtime("{tmp_path}/pkg/sub/a.py"), newestAtime("{tmp_path}/pkg/b.py"), newestAtime("{tmp_path}/none")]))',
        tmp_path,
    )
    assert out == [1_700_000_000_000, 1_800_000_000_000, None]


def test_plugin_trace_uses_its_own_install_dir_and_sgrep_reads_cargo_commit(tmp_path):
    import os

    cache = tmp_path / ".omp/plugins/cache/plugins"
    (cache / "ponytail___ponytail___5.3.2").mkdir(parents=True)
    (cache / "caveman___caveman___4.0.1").mkdir(parents=True)
    os.utime(cache / "ponytail___ponytail___5.3.2", (1_700_000_000, 1_700_000_000))
    os.utime(cache / "caveman___caveman___4.0.1", (1_800_000_000, 1_800_000_000))
    (tmp_path / ".cargo").mkdir()
    (tmp_path / ".cargo/.crates2.json").write_text(
        json.dumps(
            {
                "installs": {
                    "sgrep 0.3.0 (git+https://github.com/x/sgrep#dde0c13c8d6081f9c6d6d1d33580eebf1034aecf)": {}
                }
            }
        )
    )
    out = _bun(
        'import {components, traceFor} from "./components.ts"; const by = n => components.find(c => c.name === n);'
        'console.log(JSON.stringify([traceFor(by("ponytail"), null), traceFor(by("caveman"), null), await by("sgrep").installed()]))',
        tmp_path,
    )
    assert out == [1_700_000_000_000, 1_800_000_000_000, "dde0c13"]


def test_concord_is_an_npm_component_read_from_its_version_dir(tmp_path):
    pkg = tmp_path / ".local/share/code-factory/concord/2.6.3/node_modules/@chojs23/concord"
    pkg.mkdir(parents=True)
    (pkg / "run-concord.js").write_text("")
    (tmp_path / ".local/bin").mkdir(parents=True)
    (tmp_path / ".local/bin/concord").symlink_to(pkg / "run-concord.js")
    out = _bun(
        'import {components} from "./components.ts"; const c = components.find(c => c.name === "concord")!;'
        "console.log(JSON.stringify([c.source, await c.installed()]))",
        tmp_path,
    )
    assert out == [{"kind": "npm", "pkg": "@chojs23/concord"}, "2.6.3"]


def test_kun_and_vision_skills_read_their_pinned_commit(tmp_path):
    for name, sha in (("kun", "8a04a9b"), ("vision", "7a20c38")):
        skill = tmp_path / ".omp/agent/skills" / name
        skill.mkdir(parents=True)
        (skill / ".code-factory-source").write_text(
            f"https://github.com/kunchenguid/{name}.git@{sha}3c66c4f4c051e43a82c1f05c8bf8ef9ba\n"
        )
    out = _bun(
        'import {components, skillCommit} from "./components.ts"; const by = n => components.find(c => c.name === n)!;'
        'console.log(JSON.stringify([by("kun").source, by("vision").source, skillCommit("kun"), skillCommit("vision"), skillCommit("nope")]))',
        tmp_path,
    )
    assert out == [
        {"kind": "head", "repo": "kunchenguid/kun"},
        {"kind": "head", "repo": "kunchenguid/vision"},
        "8a04a9b",
        "7a20c38",
        None,
    ]


def test_kun_and_vision_use_their_skill_dir_as_last_used_trace(tmp_path):
    skill = tmp_path / ".omp/agent/skills/kun"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("")
    import os

    for path in (skill, skill / "SKILL.md"):
        os.utime(path, (1_700_000_000, 1_700_000_000))
    out = _bun(
        'import {components, traceFor} from "./components.ts"; const by = n => components.find(c => c.name === n)!;'
        'console.log(JSON.stringify([traceFor(by("kun"), null), traceFor(by("vision"), null)]))',
        tmp_path,
    )
    assert out == [1_700_000_000_000, None]


def test_backpass_reads_its_npm_version_and_is_null_when_absent(tmp_path):
    pkg = tmp_path / ".local/share/code-factory/backpass/0.1.38/node_modules/backpass"
    pkg.mkdir(parents=True)
    (pkg / "cli.js").write_text("")
    (tmp_path / ".local/bin").mkdir(parents=True)
    (tmp_path / ".local/bin/backpass").symlink_to(pkg / "cli.js")
    code = (
        'import {components} from "./components.ts"; const c = components.find(c => c.name === "backpass")!;'
        "console.log(JSON.stringify([c.source, await c.installed()]))"
    )
    assert _bun(code, tmp_path) == [{"kind": "npm", "pkg": "backpass"}, "0.1.38"]
    absent = tmp_path / "empty"
    absent.mkdir()
    assert _bun(code, absent) == [{"kind": "npm", "pkg": "backpass"}, None]


def test_compact_adviser_is_tracked_and_reports_not_installed(tmp_path):
    out = _bun(
        'import {components} from "./components.ts"; const c = components.find(c => c.name === "compact-adviser")!;'
        "console.log(JSON.stringify([c.source, await c.installed()]))",
        tmp_path,
    )
    assert out == [{"kind": "npm", "pkg": "compact-adviser"}, None]


def test_every_installed_kunchenguid_tool_is_tracked():
    listed = _components()
    npm_tools = {
        "gh-axi",
        "chrome-devtools-axi",
        "tasks-axi",
        "quota-axi",
        "lavish-axi",
        "backpass",
        "compact-adviser",
    }
    assert npm_tools <= {n for n, s in listed.items() if s["kind"] == "npm"}
    assert {n for n, s in listed.items() if s["kind"] == "head"} == {"sgrep", "kun", "vision"}
    assert {n: s["repo"] for n, s in listed.items() if s["kind"] == "github"}.get(
        "no-mistakes"
    ) == "kunchenguid/no-mistakes"
