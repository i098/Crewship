import configparser
import getpass
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "blueprint/schemas/crewship.schema.json").read_text())
DEFAULTS = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())


@pytest.mark.parametrize("settings", [
    {"fm_home": "/srv/reports", "snapshots": ["/srv/saved.json"]},
    {"fm_home": "/srv/reports", "ledger": "/srv/usage.sqlite", "enabled": False},
])
def test_optional_reader_configuration_is_accepted(settings):
    config = {**DEFAULTS, "crewship": {**DEFAULTS["crewship"], "token_suggestions": settings}}
    jsonschema.validate(config, SCHEMA)


@pytest.mark.parametrize("settings", [
    {}, {"fm_home": "relative"}, {"fm_home": "/srv/reports", "enabled": "yes"},
    {"fm_home": "/srv/reports", "ledger": "relative.sqlite"},
    {"fm_home": "/srv/reports", "snapshots": ["/srv/saved.json"] * 9},
    {"fm_home": "/srv/reports", "scan_sessions": True},
])
def test_unsafe_reader_configuration_is_rejected(settings):
    config = {**DEFAULTS, "crewship": {**DEFAULTS["crewship"], "token_suggestions": settings}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(config, SCHEMA)


@pytest.fixture
def installation(tmp_path):
    container = (os.environ.get("CREWSHIP_TOKEN_SUGGESTIONS_CONTAINER") == "1"
                 and Path("/.dockerenv").exists())
    vm = (os.environ.get("CREWSHIP_TOKEN_SUGGESTIONS_VM") == "1"
          and Path("/run/systemd/system").is_dir() and os.getuid() != 0)
    if not (container or vm):
        pytest.skip("apply proof requires the explicit disposable container or VM account")
    if not shutil.which("ansible-playbook"):
        pytest.fail("the proof environment needs ansible-playbook")
    (tmp_path / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
    configuration = tmp_path / "ansible.cfg"
    configuration.write_text("[defaults]\nretry_files_enabled=False\n"
                             f"local_tmp={tmp_path}/local-tmp\nremote_tmp={tmp_path}/remote-tmp\n")
    playbook = tmp_path / "play.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars_files": [str(ROOT / "blueprint/ansible/group_vars/all" / f"{name}.yml")
                       for name in ("base", "services", "token_suggestions")],
        "tasks": [{"ansible.builtin.import_tasks":
                   str(ROOT / "blueprint/ansible/tasks/token_suggestions.yml")}],
        "handlers": [{"name": "Reload user units", "ansible.builtin.systemd_service": {
            "scope": "user", "daemon_reload": True},
            "environment": "{{ crewship_user_systemd_env }}",
            "when": "crewship_manage_services | bool", "listen": "reload user systemd"}],
    }]))

    def apply(settings=None, *options, manage=False):
        home = Path.home() if manage else tmp_path / "account"
        crewship = {"home": str(home), "user": getpass.getuser(), "start_services": manage}
        if settings is not None:
            crewship["token_suggestions"] = settings
        variables = {"crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"),
                     "crewship": crewship, "ansible_become": False,
                     "crewship_user_uid": os.getuid(), "ansible_python_interpreter": sys.executable}
        result = subprocess.run(
            ["ansible-playbook", "-i", "localhost,", str(playbook), "-e", json.dumps(variables),
             *options], env={**os.environ, "ANSIBLE_CONFIG": str(configuration)},
            capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    return tmp_path, apply


def saved_report(path, cutoff):
    end = cutoff.astimezone(ZoneInfo("America/Los_Angeles")).replace(
        hour=0, minute=0, second=0, microsecond=0)
    path.write_text(json.dumps({
        "schema": "caveman.learn.v1", "basis": "inferred", "caveats": [],
        "window": {"from": (end - timedelta(days=1)).isoformat(), "to": end.isoformat()},
        "sinks": [{"sink_id": "recurring_context:repaste:fixture", "evidence": {
            "recurrence_sessions": 3, "occurrences_total": 4, "block_tokens": 200,
            "occurrence_tokens_total": 800}}],
    }))


def test_preview_does_not_create_assets(installation):
    root, apply = installation
    apply({"fm_home": str(root / "reports")}, "--check")
    assert not (root / "account").exists()
    assert not (root / "reports").exists()


def test_install_manual_cycle_disable_and_remove_preserve_data(installation):
    root, apply = installation
    cutoff = datetime.now(UTC)
    snapshot = root / "saved.json"
    saved_report(snapshot, cutoff)
    preserved = snapshot.read_bytes()
    home = root / "reports"
    settings = {"fm_home": str(home), "snapshots": [str(snapshot)], "enabled": True}
    account = root / "account"
    assets = account / ".local/share/crewship/token-suggestions"
    units = account / ".config/systemd/user"
    service = units / "crewship-token-suggestions.service"
    activation = units / "timers.target.wants/crewship-token-suggestions.timer"
    assert "changed=0" in apply()
    apply(settings)
    assert "changed=0" in apply(settings)
    assert assets.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in assets.iterdir())
    assert not activation.exists()
    assert not (units / "crewship-token-suggestions.timer").exists()
    unit = configparser.ConfigParser(interpolation=None)
    unit.read(service)
    command = shlex.split(unit["Service"]["ExecStart"])
    result = subprocess.run([*command, "--cutoff", cutoff.isoformat()],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    latest = home / "data/token-savings/latest.md"
    assert "Observed tokens: 800" in latest.read_text()
    reports = {p.name: p.read_bytes() for p in latest.parent.iterdir()}
    assert not (assets / "__pycache__").exists()
    activation.parent.mkdir()
    activation.symlink_to(units / "crewship-token-suggestions.timer")
    disabled = {**settings, "enabled": False}
    apply(disabled)
    assert not activation.is_symlink()
    assert service.exists()
    assert "changed=0" in apply(disabled)
    apply()
    assert "changed=0" in apply()
    assert not service.exists()
    assert not any(assets.iterdir())
    assert {p.name: p.read_bytes() for p in latest.parent.iterdir()} == reports
    assert snapshot.read_bytes() == preserved


def userctl(*args, check=True):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                          timeout=90, check=check)


def wait_for_start_process(service):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        pid = int(userctl("show", "--property=ControlPID", "--value", service).stdout)
        if pid:
            return pid
        time.sleep(0.1)
    pytest.fail("the service did not reach its pre-start process")


@pytest.mark.skipif(os.environ.get("CREWSHIP_TOKEN_SUGGESTIONS_VM") != "1",
                    reason="requires a fresh non-root VM account and its real user manager")
def test_runtime_failure_status_and_disable_stop(installation):
    root, apply = installation
    home = Path.home()
    snapshot = root / "saved.json"
    saved_report(snapshot, datetime.now(UTC))
    settings = {"fm_home": str(home), "snapshots": [str(snapshot)], "enabled": True}
    apply(settings, manage=True)
    assert "changed=0" in apply(settings, manage=True)
    units = home / ".config/systemd/user"
    service, timer = "crewship-token-suggestions.service", "crewship-token-suggestions.timer"
    userctl("start", service)
    latest = home / "data/token-savings/latest.md"
    before = latest.read_bytes()
    assets = home / ".local/share/crewship/token-suggestions"
    delay = root / "delay.py"
    delay.write_text(
        "import sys, time\n"
        f"sys.path.insert(0, {str(assets)!r})\n"
        "import token_suggestions as report\n"
        "def delayed(*args): time.sleep(120)\n"
        "report.read_snapshot = delayed\n"
        f"sys.exit(report.main(['--config', {str(assets / 'config.json')!r}]))\n"
    )
    dropin = units / f"{service}.d"
    dropin.mkdir()
    override = dropin / "proof.conf"
    override.write_text(f"[Service]\nExecStart=\nExecStart=/usr/bin/python3 -B {delay}\n")
    userctl("daemon-reload")
    result = userctl("start", service, check=False)
    assert result.returncode != 0
    assert json.loads(latest.with_name("status.json").read_text())["state"] == "failed"
    assert latest.read_bytes() == before
    override.write_text("[Service]\nExecStartPre=/usr/bin/sleep 30\n")
    (units / timer).write_text("[Timer]\nOnActiveSec=1h\n"
                              f"Unit={service}\n[Install]\nWantedBy=timers.target\n")
    userctl("daemon-reload")
    userctl("enable", "--now", timer)
    userctl("start", "--no-block", service)
    pid = wait_for_start_process(service)
    apply({**settings, "enabled": False}, manage=True)
    assert userctl("show", "--property=ActiveState", "--value", timer).stdout.strip() == "inactive"
    assert userctl("show", "--property=ActiveState", "--value", service).stdout.strip() in {
        "inactive", "failed"}
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not (units / "timers.target.wants" / timer).is_symlink()
    assert "changed=0" in apply({**settings, "enabled": False}, manage=True)
    apply(manage=True)
    assert "changed=0" in apply(manage=True)
    assert not (units / service).exists() and not (units / timer).exists()
    assert latest.read_bytes() == before
    override.unlink()
    dropin.rmdir()
    userctl("daemon-reload")
