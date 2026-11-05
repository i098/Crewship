"""Dia cookie sync: offered only after `ssh mac`, off unless accepted, idempotent when on."""

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("ship_dia", ROOT / "scripts/ship.py")
ship = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ship)
CONFIG = Path("/host.yml")


def _offer_config(tmp_path, **mac_ssh):
    return {
        "crewship": {
            "user": ship.pwd.getpwuid(ship.os.getuid()).pw_name,
            "home": str(tmp_path),
            "workspace": str(tmp_path),
            "mac_ssh": {"host": "mac.example", "user": "operator", **mac_ssh},
        }
    }


def _offer(monkeypatch, document, tty, ssh_ok=True):
    runs = []
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(ship.sys, "stdin", types.SimpleNamespace(isatty=lambda: tty))
    monkeypatch.setattr(ship, "host_environment", lambda config: {})
    monkeypatch.setattr(ship, "omp_signed_in", lambda environment: True)
    monkeypatch.setattr(
        ship.subprocess,
        "run",
        lambda argv, **kw: runs.append(argv) or types.SimpleNamespace(returncode=0 if argv[0] != "ssh" or ssh_ok else 255),
    )
    return runs, ship.dia_cookies_offer(document, CONFIG)


def test_offer_is_made_once_with_its_own_marker_even_after_new_host_questions(tmp_path, monkeypatch):
    document = _offer_config(tmp_path)
    done = tmp_path / ".local/share/crewship"
    done.mkdir(parents=True)
    (done / "new-host-questions-done").touch()
    runs, _ = _offer(monkeypatch, document, tty=True)
    assert [str(r[0]) for r in runs] == ["ssh", str(tmp_path / ".local/bin/omp")]
    assert (done / "dia-cookies-offer-done").exists()
    runs, _ = _offer(monkeypatch, document, tty=True)
    assert runs == []


@pytest.mark.parametrize("mac_ssh", [{"dia_cookies": True}, {"dia_cookies": False}])
def test_no_offer_once_answered(tmp_path, monkeypatch, mac_ssh):
    runs, _ = _offer(monkeypatch, _offer_config(tmp_path, **mac_ssh), tty=True)
    assert runs == []


def test_no_offer_without_ssh_mac(tmp_path, monkeypatch):
    document = _offer_config(tmp_path)
    del document["crewship"]["mac_ssh"]
    runs, _ = _offer(monkeypatch, document, tty=True)
    assert runs == []


def test_failed_ssh_skips_omp_and_keeps_offer_pending(tmp_path, monkeypatch):
    runs, _ = _offer(monkeypatch, _offer_config(tmp_path), tty=True, ssh_ok=False)
    assert [r[0] for r in runs] == ["ssh"]
    assert not (tmp_path / ".local/share/crewship/dia-cookies-offer-done").exists()


def test_non_interactive_run_prints_hint_and_keeps_offer_pending(tmp_path, monkeypatch, capsys):
    runs, _ = _offer(monkeypatch, _offer_config(tmp_path), tty=False)
    assert runs == []
    assert "mac_ssh.dia_cookies" in capsys.readouterr().out
    assert not (tmp_path / ".local/share/crewship/dia-cookies-offer-done").exists()


def _refresh(tmp_path, ssh_body, umask=0o022):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "ssh").write_text(f"#!/bin/sh\ncat >/dev/null\n{ssh_body}\n")
    (bin_dir / "ssh").chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}", "DIA_COOKIES_DIR": str(tmp_path / "store" / "dia")}
    return subprocess.run(
        [sys.executable, str(ROOT / "tools/dia-cookies/dia-cookies"), "refresh"],
        env=env, capture_output=True, preexec_fn=lambda: os.umask(umask),
    )


PROFILE = {"name": "Work", "cookies": [{"name": "a", "value": "v", "domain": ".x.com", "path": "/", "expires": -1, "secure": True, "httpOnly": False}]}


def test_refresh_exit_codes_separate_stale_profile_from_failure(tmp_path):
    stale = json.dumps({"profiles": {"P1": PROFILE}, "unread": {"P2": "Home"}})
    result = _refresh(tmp_path, f"echo '{stale}'")
    assert result.returncode == 3
    assert (tmp_path / "store/dia").stat().st_mode & 0o777 == 0o700
    assert _refresh(tmp_path, "echo boom >&2; exit 255").returncode == 1
    assert _refresh(tmp_path, "true").returncode == 1
    ok = json.dumps({"profiles": {"P1": PROFILE}, "unread": {}})
    assert _refresh(tmp_path, f"echo '{ok}'").returncode == 0


def test_get_requires_explicit_output(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path), "DIA_COOKIES_DIR": str(tmp_path / "store")}
    result = subprocess.run([sys.executable, str(ROOT / "tools/dia-cookies/dia-cookies"), "get", "work"], env=env, capture_output=True)
    assert result.returncode == 2 and b"--output" in result.stderr


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
