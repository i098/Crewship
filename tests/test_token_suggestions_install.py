import configparser
import fcntl
import getpass
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import jsonschema
import pytest
import yaml
from test_token_suggestions import CUTOFF, ledger_fixture, snapshot_fixture
from test_token_suggestions import report as report

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "blueprint/schemas/crewship.schema.json").read_text())
DEFAULTS = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())


@pytest.mark.parametrize("settings", [
    {"fm_home": "/srv/reports", "snapshots": ["/srv/saved.json"]},
    {"fm_home": "/srv/reports", "ledger": "/srv/usage.sqlite", "enabled": False},
    {"fm_home": "/srv/reports", "omp_sessions": "/srv/omp/sessions"},
])
def test_optional_reader_configuration_is_accepted(settings):
    config = {**DEFAULTS, "crewship": {**DEFAULTS["crewship"], "token_suggestions": settings}}
    jsonschema.validate(config, SCHEMA)


@pytest.mark.parametrize("settings", [
    {}, {"fm_home": "relative"}, {"fm_home": "/srv/reports", "enabled": "yes"},
    {"fm_home": "/srv/reports", "ledger": "relative.sqlite"},
    {"fm_home": "/srv/reports", "omp_sessions": "relative"},
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
    settings = {"fm_home": str(home), "snapshots": [str(snapshot)],
                "omp_sessions": str(root / "sessions")}
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
    assert (units / "crewship-token-suggestions.timer").is_file()
    unit = configparser.ConfigParser(interpolation=None)
    unit.read(service)
    command = shlex.split(unit["Service"]["ExecStart"])
    result = subprocess.run([*command, "--cutoff", cutoff.isoformat()],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    latest = home / "data/token-savings/latest.md"
    assert "Observed tokens: 800" in latest.read_text()
    assert "changed=0" in apply({**settings, "enabled": True})
    assert not activation.is_symlink()
    reports = {p.name: p.read_bytes() for p in latest.parent.iterdir()}
    assert not (assets / "__pycache__").exists()
    activation.parent.mkdir()
    activation.symlink_to(units / "crewship-token-suggestions.timer")
    old_config = (assets / "config.json").read_bytes()
    changed = root / "changed.json"
    changed.write_bytes(snapshot.read_bytes())
    with pytest.raises(AssertionError, match="Enable service management"):
        apply({**settings, "snapshots": [str(changed)]})
    assert (assets / "config.json").read_bytes() == old_config
    assert activation.is_symlink()
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
    cutoff = datetime.now(UTC)
    snapshot = root / "saved.json"
    saved_report(snapshot, cutoff)
    settings = {"fm_home": str(home), "snapshots": [str(snapshot)], "enabled": False}
    apply(settings, manage=True)
    assert "changed=0" in apply(settings, manage=True)
    units = home / ".config/systemd/user"
    service, timer = "crewship-token-suggestions.service", "crewship-token-suggestions.timer"
    assets = home / ".local/share/crewship/token-suggestions"
    unit = configparser.ConfigParser(interpolation=None)
    unit.read(units / service)
    command = shlex.split(unit["Service"]["ExecStart"])
    dropin = units / f"{service}.d"
    dropin.mkdir()
    override = dropin / "proof.conf"
    fixed_start = ("[Service]\nExecStart=\nExecStart="
                   + shlex.join([*command, "--cutoff", cutoff.isoformat()]) + "\n")
    override.write_text(fixed_start)
    userctl("daemon-reload")
    with pytest.raises(AssertionError, match="completed cycle for this configuration"):
        apply({**settings, "enabled": True}, manage=True)
    assert not (units / "timers.target.wants" / timer).is_symlink()
    userctl("start", service)
    latest = home / "data/token-savings/latest.md"
    before = latest.read_bytes()
    enabled = {**settings, "enabled": True}
    apply(enabled, manage=True)
    assert "changed=0" in apply(enabled, manage=True)
    assert userctl("show", "--property=ActiveState", "--value", timer).stdout.strip() == "active"
    changed = root / "changed.json"
    changed.write_bytes(snapshot.read_bytes())
    with pytest.raises(AssertionError, match="completed cycle for this configuration"):
        apply({**enabled, "snapshots": [str(changed)]}, manage=True)
    assert userctl("show", "--property=ActiveState", "--value", timer).stdout.strip() == "inactive"
    assert not (units / "timers.target.wants" / timer).is_symlink()
    apply(enabled, manage=True)
    assert userctl("show", "--property=ActiveState", "--value", timer).stdout.strip() == "active"
    calendar = configparser.ConfigParser(interpolation=None)
    calendar.read(units / timer)
    assert not calendar["Timer"].getboolean("Persistent")
    assert calendar["Timer"]["RandomizedDelaySec"] == "15min"
    schedule = subprocess.run(
        ["systemd-analyze", "calendar", "--iterations=2",
         "--base-time=2026-03-07 12:00:00 UTC", calendar["Timer"]["OnCalendar"]],
        env={**os.environ, "TZ": "UTC"}, capture_output=True, text=True, check=True)
    assert "Sat 2026-03-07 17:00:00 UTC" in schedule.stdout
    assert "Sun 2026-03-08 16:00:00 UTC" in schedule.stdout
    userctl("stop", timer)
    delay = root / "delay.py"
    delay.write_text(
        "import sys, time\n"
        f"sys.path.insert(0, {str(assets)!r})\n"
        "import token_suggestions as report\n"
        "def delayed(*args):\n"
        "    assert report.signal.getitimer(report.signal.ITIMER_REAL)[0] > 0\n"
        "    report.signal.setitimer(report.signal.ITIMER_REAL, 0.1)\n"
        "    time.sleep(120)\n"
        "report.read_snapshot = delayed\n"
        f"sys.exit(report.main(['--config', {str(assets / 'config.json')!r}, "
        f"'--cutoff', {cutoff.isoformat()!r}]))\n"
    )
    override.write_text(f"[Service]\nExecStart=\nExecStart=/usr/bin/python3 -B {delay}\n")
    userctl("daemon-reload")
    result = userctl("start", service, check=False)
    assert result.returncode != 0
    assert json.loads(latest.with_name("status.json").read_text())["state"] == "failed"
    assert latest.read_bytes() == before
    override.write_text(fixed_start + "ExecStartPre=/usr/bin/sleep 30\n")
    userctl("daemon-reload")
    userctl("start", timer)
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


@pytest.mark.parametrize("failure", ["termination", "startup_deadline", "elapsed_deadline",
                                     "sqlite_termination", "sqlite_deadline"])
def test_interrupted_cli_records_failure_and_preserves_report(tmp_path, report, failure):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(snapshot_fixture(report.windows(CUTOFF))))
    config = {"fm_home": str(tmp_path / "home"), "snapshots": [str(snapshot)]}
    ledger = tmp_path / "usage.sqlite"
    ledger_fixture(ledger, report.windows(CUTOFF))
    config["ledger"] = str(ledger)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    report.publish(config, CUTOFF)
    latest = tmp_path / "home/data/token-savings/latest.md"
    before = latest.read_bytes()
    script = f"""
import builtins, os, runpy, signal, sys, time
sys.path.insert(0, {str(ROOT / "scripts")!r})
original_import = builtins.__import__
def import_source(name, *args, **kwargs):
    module = original_import(name, *args, **kwargs)
    if name == "token_suggestions_sources":
        if {failure!r} == "startup_deadline":
            clock = time.monotonic
            time.monotonic = lambda: clock() + 60
        elif {failure!r} == "elapsed_deadline":
            read_snapshot = module.read_snapshot
            def expire(*args):
                clock = time.monotonic
                time.monotonic = lambda: clock() + 60
                return read_snapshot(*args)
            module.read_snapshot = expire
        elif {failure!r}.startswith("sqlite_"):
            normalize = module.normalized_input
            def interrupt(*args):
                if {failure!r} == "sqlite_termination":
                    os.kill(os.getpid(), signal.SIGTERM)
                else:
                    signal.setitimer(signal.ITIMER_REAL, 0.001)
                    time.sleep(0.05)
                return normalize(*args)
            module.normalized_input = interrupt
        else:
            def terminate(*args):
                os.kill(os.getpid(), signal.SIGTERM)
            module.read_snapshot = terminate
    return module
builtins.__import__ = import_source
sys.argv = ["token_suggestions.py", "--config", {str(config_path)!r},
            "--cutoff", {CUTOFF.isoformat()!r}]
runpy.run_path({str(ROOT / "scripts/token_suggestions.py")!r}, run_name="__main__")
"""
    result = subprocess.run([sys.executable, "-B", "-c", script],
                            capture_output=True, text=True, timeout=10)
    status_path = latest.with_name("status.json")
    assert json.loads(status_path.read_text())["state"] == "failed", result.stderr
    assert result.returncode == 1
    assert latest.read_bytes() == before
    report.publish(config, CUTOFF)
    assert "previous cycle failed" in latest.read_text()




def test_activation_requires_a_completed_cycle_for_exact_inputs(tmp_path, report):
    snapshot = tmp_path / "saved.json"
    saved_report(snapshot, CUTOFF)
    config = {"fm_home": str(tmp_path / "home"), "snapshots": [str(snapshot)]}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    args = ["--config", str(path), "--check-cycle"]
    assert report.main(args) == 1
    report.publish(config, CUTOFF)
    status = tmp_path / "home/data/token-savings/status.json"
    latest = status.with_name("latest.md")
    before = status.read_bytes(), latest.read_bytes(), snapshot.read_bytes()
    assert report.main(args) == 0
    assert before == (status.read_bytes(), latest.read_bytes(), snapshot.read_bytes())
    fd = os.open(status.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert report.main(args) == 1
    finally:
        os.close(fd)
    assert before == (status.read_bytes(), latest.read_bytes(), snapshot.read_bytes())
    other = tmp_path / "other.json"
    other.write_bytes(snapshot.read_bytes())
    path.write_text(json.dumps({**config, "snapshots": [str(other)]}))
    assert report.main(args) == 1
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        report.publish({**config, "snapshots": []}, CUTOFF)
    assert report.main(args) == 1
    assert latest.read_bytes() == before[1]


@pytest.mark.parametrize("boundary", ["latest.md", "status.json"])
def test_killed_publication_never_proves_a_cycle(tmp_path, report, boundary):
    snapshot = tmp_path / "saved.json"
    saved_report(snapshot, CUTOFF)
    config = {"fm_home": str(tmp_path / "home"), "snapshots": [str(snapshot)]}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    script = f"""
import os, signal, sys
sys.path.insert(0, {str(ROOT / "scripts")!r})
import token_suggestions as report
write = report.atomic_write
def kill_before(path, content):
    if path.name == {boundary!r}:
        os.kill(os.getpid(), signal.SIGKILL)
    write(path, content)
report.atomic_write = kill_before
sys.exit(report.main(["--config", {str(path)!r}, "--cutoff", {CUTOFF.isoformat()!r}]))
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == -signal.SIGKILL
    assert report.main(["--config", str(path), "--check-cycle"]) == 1


def test_receipt_write_failure_keeps_previous_report(tmp_path, report, monkeypatch):
    snapshot = tmp_path / "saved.json"
    saved_report(snapshot, CUTOFF)
    config = {"fm_home": str(tmp_path / "home"), "snapshots": [str(snapshot)]}
    report.publish(config, CUTOFF)
    latest = tmp_path / "home/data/token-savings/latest.md"
    before = latest.read_bytes()
    data = json.loads(snapshot.read_text())
    data["sinks"][0]["evidence"]["occurrence_tokens_total"] = 1200
    snapshot.write_text(json.dumps(data))
    write = report.atomic_write

    def fail_receipt(path, content):
        if path.name == "status.json" and json.loads(content)["state"] == "complete":
            raise OSError("synthetic receipt write failure")
        write(path, content)

    monkeypatch.setattr(report, "atomic_write", fail_receipt)
    with pytest.raises(OSError, match="synthetic receipt"):
        report.publish(config, CUTOFF)
    assert latest.read_bytes() == before
    assert json.loads(latest.with_name("status.json").read_text())["state"] == "failed"
