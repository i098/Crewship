import getpass
import grp
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def redirect_system_paths(tasks, root):
    for task in tasks:
        for module, key in (("ansible.builtin.file", "path"), ("ansible.builtin.copy", "dest")):
            options = task.get(module, {})
            path = options.get(key, "")
            if path.startswith("/etc/systemd/"):
                options[key] = str(root / path.lstrip("/"))


@pytest.mark.parametrize("existing_home", [False, True])
@pytest.mark.parametrize("profiles", [
    {},
    {"fleet_guards": True},
    {"fleet_browsers": True, "firstmate": True},
])
def test_chart_creates_only_missing_directories(tmp_path, existing_home, profiles):
    home = tmp_path / "home"
    home.mkdir()
    journald = tmp_path / "etc/systemd/journald.conf.d"
    journald.mkdir(parents=True)
    (tmp_path / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
    if existing_home:
        for path, mode in (
            (".local/bin", 0o750), (".acpx", 0o750), (".omp/agent/extensions", 0o700),
            (".config/systemd/user/no-mistakes-daemon-.service.d", 0o700),
            ("oss-fleet/doctor", 0o700), ("oss-fleet/browsers", 0o750),
            (".local/share/crewship/imessage", 0o700),
            (".local/share/crewship/instagram-desk", 0o750),
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
    site_tasks = yaml.safe_load((ROOT / "blueprint/ansible/site.yml").read_text())[0]["tasks"]
    for include in site_tasks:
        task_file = include.get("ansible.builtin.import_tasks")
        if task_file not in {
            "tasks/fleet_guards.yml", "tasks/fleet_units.yml", "tasks/fleet-browsers.yml",
            "tasks/imessage.yml", "tasks/instagram_dm.yml",
        }:
            continue
        profile_tasks = yaml.safe_load((ROOT / "blueprint/ansible" / task_file).read_text())
        if task_file.startswith("tasks/fleet"):
            redirect_system_paths(profile_tasks, tmp_path)
        else:
            profile_tasks = [task for task in profile_tasks
                             if task.get("ansible.builtin.copy", {}).get("remote_src")
                             or task.get("ansible.builtin.file", {}).get("state") == "directory"]
        tasks.append({
            "block": profile_tasks,
            **{key: include[key] for key in ("when", "become", "become_user", "environment")
               if key in include},
        })
    playbook = tmp_path / "chart.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars_files": [str(path) for path in sorted((ROOT / "blueprint/ansible/group_vars/all").glob("*.yml"))],
        "tasks": layout + tasks,
        "handlers": [{"name": name, "ansible.builtin.debug": {"msg": "deferred"}}
                     for name in ("reload user systemd", "no-mistakes daemon restart required",
                                  "restart fm-imessage", "restart instagram-desk",
                                  "restart journald", "restart fleet timers",
                                  "restart fleet browser obscura", "restart fleet browser timers")],
    }]))
    variables = {
        "crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"),
        "crewship": {
            "home": str(home), "workspace": str(home / "Dev"), "user": getpass.getuser(),
            "profiles": {"fleet_guards": False, "fleet_browsers": False, "firstmate": False,
                         **profiles},
            "start_services": False,
            "imessage": {"owner": "+15551234567"},
        },
        "crewship_instagram_dm_operator": "operator",
        "crewship_browser_obscura_dir": str(home / "oss-fleet/browsers/obscura-test"),
        "crewship_browser_obscura": {
            "url": (tmp_path / "absent.tar.gz").as_uri(), "sha256": "0" * 64,
        },
        "ansible_become": False, "crewship_become_target": False, "crewship_account_ready": True,
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
    }
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook),
         "--check", "-e", json.dumps(variables)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(journald.iterdir()) == []
    if profiles.get("fleet_guards") or profiles.get("fleet_browsers"):
        assert "would download and extract Obscura" in result.stdout
    assert {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
            for path in home.rglob("*") if path.is_file()} == before_files
    assert {path: (path.stat().st_mode, path.stat().st_uid, path.stat().st_gid)
            for path in before_dirs} == before_dirs
    assert all((home / path).is_dir() for path in (
        ".local/bin", ".omp/agent/extensions", ".no-mistakes", ".acpx",
    ))
    for path, enabled in (
        ("oss-fleet/doctor", profiles.get("fleet_guards", False)),
        ("oss-fleet/browsers",
         profiles.get("fleet_guards", False) or profiles.get("fleet_browsers", False)),
        (".local/share/crewship/imessage", profiles.get("firstmate", False)),
        (".local/share/crewship/instagram-desk", profiles.get("firstmate", False)),
    ):
        assert (home / path).is_dir() == (existing_home or enabled)


@pytest.mark.parametrize("task_file,unit,handler", [
    ("herdr.yml", "herdr.service", False),
    ("herdr.yml", "herdr-spaces.timer", False),
    ("browser_prune.yml", "chrome-autoprune.timer", False),
    ("stall_nudge.yml", "fm-main-stall-nudge.timer", False),
    ("herdr.yml", "herdr.service", True),
    ("browser_prune.yml", "chrome-autoprune.timer", True),
])
@pytest.mark.parametrize("check_mode,installed", [(True, False), (True, True), (False, False)])
def test_service_preview_skips_only_absent_units(tmp_path, task_file, unit, handler, check_mode, installed):
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks" / task_file).read_text())
    probes = [
        task for task in tasks
        if any(task.get(module, {}).get(key) == "{{ crewship_user_units }}/" + unit
               for module, key in (("ansible.builtin.stat", "path"), ("ansible.builtin.slurp", "src")))
    ]
    if handler:
        tasks = yaml.safe_load((ROOT / "blueprint/ansible/site.yml").read_text())[0]["handlers"]
    start = next(task for task in tasks
                 if task.get("ansible.builtin.systemd_service", {}).get("name") == unit)
    start.pop("listen", None)
    if installed:
        (tmp_path / unit).write_text("[Unit]\nDescription=Preview test\n")
    systemctl = tmp_path / "systemctl"
    systemctl.write_text("#!/bin/sh\necho 'systemd probe failed' >&2\nexit 1\n")
    systemctl.chmod(0o755)
    playbook = tmp_path / "preview.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": {
            "crewship_user_units": str(tmp_path), "crewship_manage_services": True,
            "crewship_become_target": False, "crewship_cfg": {"user": getpass.getuser()},
            "crewship_user_systemd_env": {"PATH": f"{tmp_path}:{os.environ['PATH']}"},
        },
        "tasks": probes + [start],
    }]))
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook),
         *(["--check"] if check_mode else [])],
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    if check_mode and not installed:
        assert result.returncode == 0, output
        assert "skipping: [localhost]" in output
    else:
        assert result.returncode != 0, output
        assert "systemd probe failed" in output


@pytest.mark.parametrize("check_mode", [True, False])
@pytest.mark.parametrize("release_state", ["absent", "empty", "installed"])
def test_obscura_release_preview_and_install(tmp_path, check_mode, release_state):
    browsers = tmp_path / "home/oss-fleet/browsers"
    browsers.mkdir(parents=True)
    release = browsers / "obscura-test"
    binaries = ("obscura", "obscura-worker")
    if release_state != "absent":
        release.mkdir(mode=0o700)
    if release_state == "installed":
        for binary in binaries:
            (release / binary).write_bytes(b"existing release\n")
    archive = tmp_path / "release.tar.gz"
    if not check_mode and release_state != "installed":
        source = tmp_path / "source"
        source.mkdir()
        with tarfile.open(archive, "w:gz") as bundle:
            for binary in binaries:
                (source / binary).write_bytes(b"archive release\n")
                bundle.add(source / binary, arcname=binary)
    before_files = {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
                    for path in browsers.rglob("*") if path.is_file()}
    before_dirs = {path: (path.stat().st_mode, path.stat().st_uid, path.stat().st_gid)
                   for path in browsers.rglob("*") if path.is_dir()}
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/fleet-browsers.yml").read_text())
    start = next(i for i, task in enumerate(tasks)
                 if task["name"] == "Stat the resolved Obscura release")
    end = next(i for i, task in enumerate(tasks)
               if task["name"] == "Inject the shared-browser env into shell profiles")
    playbook = tmp_path / "obscura.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "tasks": tasks[start:end],
    }]))
    variables = {
        "crewship_cfg": {"user": getpass.getuser()},
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
        "crewship_fleet_browsers_dir": str(browsers),
        "crewship_browser_obscura_dir": str(release),
        "crewship_browser_obscura": {
            "url": archive.as_uri(),
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest() if archive.exists() else "0" * 64,
        },
        "ansible_become": False,
    }
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook),
         *(["--check"] if check_mode else []), "-e", json.dumps(variables)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not release.with_suffix(".tar.gz").exists()
    if check_mode:
        assert {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
                for path in browsers.rglob("*") if path.is_file()} == before_files
        assert {path: (path.stat().st_mode, path.stat().st_uid, path.stat().st_gid)
                for path in browsers.rglob("*") if path.is_dir()} == before_dirs
        assert (f"would download and extract Obscura into {release}." in result.stdout) == (
            release_state != "installed"
        )
    else:
        expected = b"existing release\n" if release_state == "installed" else b"archive release\n"
        for binary in binaries:
            assert (release / binary).read_bytes() == expected
            assert (browsers / binary).is_symlink()
            assert (browsers / binary).resolve() == release / binary
