import getpass
import grp
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("existing_home", [False, True])
def test_chart_creates_only_missing_directories(tmp_path, existing_home):
    home = tmp_path / "home"
    home.mkdir()
    if existing_home:
        for path, mode in (
            (".local/bin", 0o750), (".acpx", 0o750), (".omp/agent/extensions", 0o700),
            (".config/systemd/user/no-mistakes-daemon-.service.d", 0o700),
        ):
            directory = home / path
            directory.mkdir(parents=True)
            directory.chmod(mode)
        (home / ".local/bin/ponytail-review").write_text("keep this existing file\n")
    before_files = {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
                    for path in home.rglob("*") if path.is_file()}
    before_dirs = {path: (path.stat().st_mode, path.stat().st_uid, path.stat().st_gid)
                   for path in home.rglob("*") if path.is_dir()}
    account_tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/account.yml").read_text())
    layout = [task for task in account_tasks
              if task["name"] in ("Inspect the home layout", "Ensure the home layout")]
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/agents.yml").read_text())
    end = next(i for i, task in enumerate(tasks) if task["name"] == "Point daemon-spawned omp at the overlay")
    tasks = [task for task in tasks[:end + 1]
             if any(key in task for key in ("ansible.builtin.file", "ansible.builtin.copy", "ansible.builtin.stat"))]
    playbook = tmp_path / "chart.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars_files": [str(path) for path in sorted((ROOT / "blueprint/ansible/group_vars/all").glob("*.yml"))],
        "tasks": layout + tasks,
        "handlers": [{"name": name, "ansible.builtin.debug": {"msg": "deferred"}}
                     for name in ("reload user systemd", "no-mistakes daemon restart required")],
    }]))
    variables = {
        "crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"),
        "crewship": {"home": str(home), "workspace": str(home / "Dev"), "user": getpass.getuser()},
        "ansible_become": False, "crewship_become_target": False, "crewship_account_ready": True,
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
    }
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook),
         "--check", "-e", json.dumps(variables)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
            for path in home.rglob("*") if path.is_file()} == before_files
    assert {path: (path.stat().st_mode, path.stat().st_uid, path.stat().st_gid)
            for path in before_dirs} == before_dirs
    assert all((home / path).is_dir() for path in (
        ".local/bin", ".omp/agent/extensions", ".no-mistakes", ".acpx",
    ))
