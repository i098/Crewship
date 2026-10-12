"""Removed backend checks; apply runs only in the disposable Docker lab."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from test_fleet_units import apply

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("ship_removed", ROOT / "scripts/ship.py")
ship = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ship)


@pytest.mark.parametrize(
    ("enabled", "fleet"),
    [
        (False, {}),
        (True, {}),
        (False, dict(zip(ship.REMOVED_FLEET_KEYS, ("swarms-shared", "", [".treehouse/project"])))),
        (None, dict(zip(ship.REMOVED_FLEET_KEYS, ("swarms-shared", "", [".treehouse/project"])))),
        (None, {"fixture_archive": "", "worktree_pools": [".treehouse/project"]}),
        (None, {ship.REMOVED_FLEET_KEYS[0]: "swarms-shared"}),
        (None, {"fixture_archive": ""}),
        (None, {"worktree_pools": []}),
    ],
    ids=["disabled", "enabled", "old-defaults", "old-fleet-defaults", "partial-cleanup",
         "project-only", "archive-only", "pools-only"],
)
def test_removed_switch_reports_replacement_without_traceback(tmp_path, enabled, fleet):
    document = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    if enabled is not None:
        document["crewship"]["profiles"][ship.REMOVED_PROFILE] = enabled
    document["crewship"]["fleet"].update(fleet)
    host = tmp_path / "host.yml"
    host.write_text(yaml.safe_dump(document))
    before = host.read_bytes()
    result = subprocess.run(
        [sys.executable, ROOT / "scripts/ship.py", "inspect", "--config", host],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "support was removed" in result.stderr
    assert "profiles.shared_postgres (docs/shared-postgres.md)" in result.stderr
    for key in (f"profiles.{ship.REMOVED_PROFILE}",
                *(f"fleet.{key}" for key in ship.REMOVED_FLEET_KEYS)):
        assert key in result.stderr
    assert "Traceback" not in result.stderr
    assert host.read_bytes() == before
    document["crewship"]["profiles"].pop(ship.REMOVED_PROFILE, None)
    for key in ship.REMOVED_FLEET_KEYS:
        document["crewship"]["fleet"].pop(key, None)
    host.write_text(yaml.safe_dump(document))
    cleaned = host.read_bytes()
    result = subprocess.run(
        [sys.executable, ROOT / "scripts/ship.py", "inspect", "--config", host],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "Valid host configuration:" in result.stdout
    assert result.stderr == ""
    assert host.read_bytes() == cleaned


@pytest.mark.skipif(os.environ.get("CREWSHIP_POSTGRES_LAB") != "1", reason="disposable Docker lab only")
def test_apply_preserves_running_retired_stack_and_volume(tmp_path, capsys, monkeypatch):
    home = tmp_path / "home"
    stack = home / ship.RETIRED_STACK
    stack.mkdir(parents=True)
    backend = ship.REMOVED_PROFILE.removeprefix("shared_")
    name = f"{backend}_db_disposable"
    volume = f"{name}_data"
    subprocess.run(["docker", "run", "-d", "--name", name, "--restart", "unless-stopped",
                    "-v", f"{volume}:/data", "alpine", "sh", "-c",
                    "echo fixture > /data/proof; exec sleep infinity"], check=True, capture_output=True)
    units = home / ".config/systemd/user"
    units.mkdir(parents=True)
    paths = []
    for prefix in ("crewship", "flotilla"):
        for suffix in (f"shared-{backend}.service", f"shared-{backend}-check.timer",
                       "worktree-env-seed.service", "worktree-env-seed.path", "worktree-env-seed.timer"):
            path = units / f"{prefix}-{suffix}"
            path.write_text(f"[Service]\nExecStop=docker stop {name}\n")
            paths.append(path)
            wants = units / ("timers.target.wants" if suffix.endswith(".timer") else "default.target.wants")
            wants.mkdir(exist_ok=True)
            link = wants / path.name
            link.symlink_to(path)
            paths.append(link)
    fixture = stack / "fixture"
    fixture.write_text("keep integration\n")
    paths.append(fixture)
    before = {p: (p.read_bytes(), p.lstat().st_mtime_ns) for p in paths}
    def inspect():
        return json.loads(subprocess.run(
            ["docker", "inspect", name], check=True, capture_output=True, text=True,
        ).stdout)[0]

    original = inspect()
    try:
        apply(home, scripts=True)
        # Route the CLI apply through the same real task consumer inside this lab.
        repo = tmp_path / "repo"
        ansible = repo / "blueprint/ansible"
        ansible.mkdir(parents=True)
        (ansible / "site.yml").write_bytes((tmp_path / "units.yml").read_bytes())
        (ansible / "inventory.yml").write_text("all:\n  hosts:\n    localhost:\n")
        (ansible / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
        monkeypatch.setattr(ship, "ROOT", repo)
        document = {
            "ansible_become": False, "crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"),
            "crewship_group": "root", "crewship_become_target": False,
            "crewship": {"home": str(home), "user": "root", "start_services": False,
                         "profiles": {"fleet_guards": True}},
        }
        assert ship.provision(document, False) == 0
        notice = capsys.readouterr().out
        assert "remains untouched" in notice
        assert "remove it manually" in notice
        assert "docs/shared-postgres.md" in notice
        assert {p: (p.read_bytes(), p.lstat().st_mtime_ns) for p in paths} == before
        current = inspect()
        assert current["State"]["Running"] is True
        assert current["Id"] == original["Id"]
        assert current["State"]["StartedAt"] == original["State"]["StartedAt"]
        assert subprocess.run(["docker", "exec", name, "cat", "/data/proof"],
                              check=True, capture_output=True, text=True).stdout == "fixture\n"
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=True, capture_output=True)
        subprocess.run(["docker", "volume", "rm", volume], check=True, capture_output=True)
