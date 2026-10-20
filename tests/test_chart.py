import getpass
import grp
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_agent_chart_creates_only_directories(tmp_path):
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    sentinel = home / ".local/bin/ponytail-review"
    sentinel.write_text("keep this existing file\n")
    before = sentinel.stat()
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/agents.yml").read_text())
    end = next(i for i, task in enumerate(tasks) if task["name"] == "Point daemon-spawned omp at the overlay")
    tasks = [task for task in tasks[:end + 1]
             if any(key in task for key in ("ansible.builtin.file", "ansible.builtin.copy", "ansible.builtin.stat"))]
    playbook = tmp_path / "chart.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars_files": [str(path) for path in sorted((ROOT / "blueprint/ansible/group_vars/all").glob("*.yml"))],
        "tasks": tasks,
        "handlers": [{"name": name, "ansible.builtin.debug": {"msg": "deferred"}}
                     for name in ("reload user systemd", "no-mistakes daemon restart required")],
    }]))
    variables = {
        "crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"),
        "crewship": {"home": str(home), "user": getpass.getuser()}, "ansible_become": False,
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
    }
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook),
         "--check", "-e", json.dumps(variables)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert {path.relative_to(home) for path in home.rglob("*") if path.is_file()} == {
        Path(".local/bin/ponytail-review")
    }
    assert sentinel.read_text() == "keep this existing file\n"
    assert (sentinel.stat().st_mode, sentinel.stat().st_mtime_ns) == (before.st_mode, before.st_mtime_ns)
    assert all((home / path).is_dir() for path in (
        ".omp/agent/extensions", ".no-mistakes", ".acpx", ".config/systemd/user/no-mistakes-daemon-.service.d",
    ))
