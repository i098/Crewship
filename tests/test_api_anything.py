import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("api_anything", ROOT / "scripts/api_anything.py")
api_anything = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api_anything)
BRIDGE = ROOT / "blueprint/fleet/browsers/api-anything-fleet"


@pytest.fixture
def host(tmp_path):
    home = tmp_path / "home"
    package = home / ".local/share/crewship/api-anything/1.0.0/node_modules/api-anything"
    (package / "dist").mkdir(parents=True)
    (package / "skills/api-anything").mkdir(parents=True)
    (package / "dist/cli.js").write_text("")
    (package / "skills/api-anything/SKILL.md").write_text("upstream skill\n")
    (home / ".local/bin").mkdir(parents=True)
    (home / ".local/bin/api-anything").symlink_to(package / "dist/cli.js")
    return home, home / ".local/state/crewship/api-anything"


def test_sharing_is_off_and_the_catalog_is_private(host):
    home, state = host
    api_anything.install(home, state)
    settings = json.loads((state / "settings.json").read_text())
    assert settings["share"] is False and settings["askedAt"]
    assert state.stat().st_mode & 0o777 == 0o700
    entry = json.loads((home / ".omp/agent/mcp.json").read_text())["mcpServers"]["api-anything"]
    assert entry["env"]["API_ANYTHING_HOME"] == str(state)
    assert entry["env"]["API_ANYTHING_BROWSER_ROOTS"] == "[]"


def test_rerun_changes_nothing_and_keeps_an_owner_opt_in(host):
    home, state = host
    api_anything.install(home, state)
    assert api_anything.install(home, state) == {"changed": False}
    (state / "settings.json").write_text('{"share": true}')
    api_anything.install(home, state)
    assert json.loads((state / "settings.json").read_text())["share"] is True


def test_other_mcp_servers_stay_and_skills_carry_the_addendum(host):
    home, state = host
    (home / ".omp/agent").mkdir(parents=True)
    (home / ".omp/agent/mcp.json").write_text('{"mcpServers": {"other": {"command": "x"}}}')
    api_anything.install(home, state)
    assert set(json.loads((home / ".omp/agent/mcp.json").read_text())["mcpServers"]) == {"other", "api-anything"}
    for rel in api_anything.SKILLS:
        text = (home / rel / "SKILL.md").read_text()
        assert text.startswith("upstream skill") and "Sharing is off" in text


def test_playbook_env_matches_the_mcp_entry():
    vars = yaml.safe_load((ROOT / "blueprint/ansible/group_vars/all/base.yml").read_text())
    env = vars["crewship_managed_shell_env"]
    assert env["API_ANYTHING_BROWSER_ROOTS"] == api_anything.ENV["API_ANYTHING_BROWSER_ROOTS"]
    assert env["API_ANYTHING_HOME"] == "{{ crewship_api_anything_home }}"
    assert vars["crewship_api_anything_home"].endswith("/.local/state/crewship/api-anything")


def test_call_renews_the_login_from_the_jar_once_on_auth(tmp_path):
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    (home / ".fleet-browser").mkdir(parents=True)
    bin_dir.mkdir()
    (home / ".fleet-browser/cookies.json").write_text(
        json.dumps({"a|/|s": {"name": "s", "value": "v", "domain": "a.test", "path": "/"}})
    )
    log = tmp_path / "log"
    (bin_dir / "fleet-browser").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "api-anything").write_text(
        f'#!/bin/sh\necho "$1 $2" >> {log}\n'
        'if [ "$1" = login ]; then cat "$4" >> ' + str(log) + "; echo >> " + str(log) + "; exit 0; fi\n"
        f'if grep -q "^login" {log}; then echo \'{{"ok":true,"data":1}}\'; else echo \'{{"ok":false,"class":"auth"}}\'; fi\n'
    )
    for name in ("fleet-browser", "api-anything"):
        (bin_dir / name).chmod(0o755)
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    run = subprocess.run([sys.executable, str(BRIDGE), "call", "site", "op"], env=env, capture_output=True, text=True)
    assert run.stdout.strip() == '{"ok":true,"data":1}'
    lines = log.read_text().splitlines()
    assert [line.split()[0] for line in lines if line.split()[0] in ("call", "login")] == ["call", "login", "call"]
    assert '"value": "v"' in log.read_text()
