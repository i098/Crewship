"""Dia cookie sync: offered only after `ssh mac`, off unless accepted, idempotent when on."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("ship_dia", ROOT / "scripts/ship.py")
ship = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ship)
CONFIG = Path("/host.yml")


@pytest.mark.parametrize(
    "config,offered",
    [
        ({}, False),
        ({"mac_ssh": {"host": "mac.example", "user": "operator"}}, True),
        ({"mac_ssh": {"host": "mac.example", "user": "operator", "dia_cookies": False}}, False),
        ({"mac_ssh": {"host": "mac.example", "user": "operator", "dia_cookies": True}}, False),
    ],
)
def test_question_follows_ssh_mac_and_is_asked_once(config, offered):
    text = ship.dia_cookies_question(config, CONFIG)
    assert bool(text) == offered
    if offered:
        assert "ssh -o BatchMode=yes mac true" in text and "Only if it succeeds" in text


def _apply(tmp_path, home, enabled):
    if not (tmp_path / "templates").exists():
        (tmp_path / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "handlers": [
                        {"name": "reload", "ansible.builtin.debug": {"msg": "reload"}, "listen": "reload user systemd"}
                    ],
                    "tasks": [
                        {
                            "ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/dia_cookies.yml"),
                            "when": "crewship_cfg.mac_ssh.dia_cookies | default(false) | bool",
                        }
                    ],
                }
            ]
        )
    )
    mac_ssh = {"host": "mac.example", "user": "operator", **({"dia_cookies": True} if enabled else {})}
    variables = {
        "crewship_cfg": {"user": "coder", "home": str(home), "mac_ssh": mac_ssh},
        "crewship_repo": str(ROOT),
        "crewship_dia_cookies_bin": str(home / ".local/bin/dia-cookies"),
        "crewship_user_units": str(home / ".config/systemd/user"),
        "crewship_manage_services": False,
    }
    (home / ".local/bin").mkdir(parents=True, exist_ok=True)
    (home / ".config/systemd/user").mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook),
         "--extra-vars", json.dumps(variables)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_declining_installs_nothing(tmp_path):
    home = tmp_path / "home"
    _apply(tmp_path, home, enabled=False)
    assert not (home / ".local/bin/dia-cookies").exists()
    assert not list((home / ".config/systemd/user").iterdir())


def test_accepting_installs_script_and_timer_idempotently(tmp_path):
    home = tmp_path / "home"
    _apply(tmp_path, home, enabled=True)
    units = home / ".config/systemd/user"
    script = home / ".local/bin/dia-cookies"
    assert script.stat().st_mode & 0o777 == 0o755
    assert (units / "timers.target.wants/dia-cookies.timer").is_symlink()
    service = (units / "dia-cookies.service").read_text()
    assert f"ExecStart={script} refresh" in service and "UMask=0077" in service
    assert "OnUnitActiveSec=30min" in (units / "dia-cookies.timer").read_text()
    assert "changed=0" in _apply(tmp_path, home, enabled=True)
