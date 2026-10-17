import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "blueprint/ansible/templates/crewship-syslog-rotate.j2"
ISOLATED = os.environ.get("CREWSHIP_SYSLOG_CONTAINER") == "1" and Path("/.dockerenv").exists()
container_only = pytest.mark.skipif(not ISOLATED, reason="requires the isolated syslog container")


def render_helper(directory, mount, destination):
    destination.write_text(Environment(undefined=StrictUndefined).from_string(
        TEMPLATE.read_text()
    ).render(crewship_syslog_dir=str(directory), crewship_syslog_mount={"stdout": str(mount)}))
    destination.chmod(0o755)
    return destination


@pytest.fixture
def rotation(tmp_path):
    with tempfile.TemporaryDirectory(prefix="crewship-syslog-", dir="/dev/shm") as name:
        directory = Path(name)
        yield directory, render_helper(directory, "/dev/shm", tmp_path / "rotate")


@pytest.mark.parametrize("filename_argument", [False, True])
def test_rotation_retains_eight_archives_and_rejects_other_paths(rotation, filename_argument):
    directory, helper = rotation
    for number in range(1, 9):
        (directory / f"syslog.{number}").write_text(f"history {number}")
    active = directory / "syslog"
    active.write_text("active history")
    rejected = subprocess.run([helper, "/unrelated/syslog"], capture_output=True)
    assert rejected.returncode == 2
    assert active.read_text() == "active history"
    subprocess.run([helper, *([active] if filename_argument else [])], check=True)
    assert not active.exists()
    assert (directory / "syslog.1").read_text() == "active history"
    assert [(directory / f"syslog.{n}").read_text() for n in range(2, 9)] == [
        f"history {n}" for n in range(1, 8)
    ]
    assert sorted(p.name for p in directory.iterdir()) == [f"syslog.{n}" for n in range(1, 9)]


@pytest.mark.parametrize("unsafe", ["syslog", "syslog.4", "syslog.8"])
def test_rotation_rejects_symlinks_before_changing_any_history(rotation, tmp_path, unsafe):
    directory, helper = rotation
    external = tmp_path / "external"
    external.write_text("protected history")
    for name in ("syslog", "syslog.1", "syslog.4", "syslog.8"):
        (directory / name).write_text(name)
    (directory / unsafe).unlink()
    (directory / unsafe).symlink_to(external)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert subprocess.run([helper], capture_output=True).returncode != 0
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
    assert external.read_text() == "protected history"


def test_missing_active_log_leaves_archives_unchanged(rotation):
    directory, helper = rotation
    for number in range(1, 9):
        (directory / f"syslog.{number}").write_text(f"history {number}")
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert subprocess.run([helper], capture_output=True).returncode != 0
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


def apply_syslog(tmp_path, data_dir="/mnt/data", check=False):
    site = yaml.safe_load((ROOT / "blueprint/ansible/site.yml").read_text())[0]
    playbook = tmp_path / "syslog.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": {"crewship_data_dir": data_dir, "crewship_blueprint": str(ROOT / "blueprint"),
                 "crewship_manage_services": False},
        "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/syslog.yml"),
                   "when": "crewship_data_dir | length > 0"}],
        "handlers": [h for h in site["handlers"] if h.get("listen") == "restart bounded syslog"],
    }]))
    return subprocess.run([
        str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook),
        *(["--check"] if check else []),
    ], text=True, capture_output=True)


@container_only
def test_provisioning_preserves_history_rules_and_second_apply(tmp_path):
    rules = Path("/etc/rsyslog.d/50-default.conf")
    rotation_rules = Path("/etc/logrotate.d/rsyslog")
    Path("/etc/rsyslog.d/20-operator.conf").write_text(
        'template(name="Operator" type="string" string="%msg%\\n")\n'
    )
    original = rules.read_text() + "\n# operator policy\nlocal5.* /var/log/operator.log;Operator\n"
    rules.write_text(original)
    Path("/etc/rsyslog.d/60-audit.conf").write_text("local6.* /var/log/audit-preserved.log\n")
    original_rotation = rotation_rules.read_bytes()
    old = Path("/var/log/syslog")
    old.write_text("existing general history\n")
    Path("/var/log/syslog.1").write_text("existing archived history\n")
    owned = Path("/usr/local/libexec/crewship-syslog-rotate")
    baseline = rules.read_bytes()
    preview = apply_syslog(tmp_path, check=True)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert rules.read_bytes() == baseline and not owned.exists()
    invalid = Path("/etc/rsyslog.d/30-invalid.conf")
    invalid.write_text('module(load="crewship_nonexistent_module")\n')
    rejected = apply_syslog(tmp_path)
    assert rejected.returncode != 0
    assert rules.read_bytes() == baseline
    assert rotation_rules.read_bytes() == original_rotation
    invalid.unlink()
    result = apply_syslog(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"changed=[1-9]", result.stdout)
    after = rules.read_text()
    def without_action(text):
        return [line for line in text.splitlines()
                if not re.match(r"^[^#\s].*\s-?/var/log/syslog\s*$", line)
                and not line.endswith("# crewship bounded syslog")]

    assert without_action(after) == without_action(original)
    assert rotation_rules.read_bytes() == original_rotation.replace(b"/var/log/syslog\n", b"")
    assert old.read_text() == "existing general history\n"
    assert Path("/var/log/syslog.1").read_text() == "existing archived history\n"
    assert Path("/etc/rsyslog.d/60-audit.conf").read_text() == "local6.* /var/log/audit-preserved.log\n"
    assert not Path("/run/rsyslogd.pid").exists()
    second = apply_syslog(tmp_path)
    assert second.returncode == 0 and "changed=0" in second.stdout, second.stdout + second.stderr
    preview = apply_syslog(tmp_path, check=True)
    assert preview.returncode == 0 and "changed=0" in preview.stdout, preview.stdout + preview.stderr
    no_data = apply_syslog(tmp_path, data_dir="")
    assert no_data.returncode == 0 and "changed=0" in no_data.stdout
    assert rules.read_text() == after
    subprocess.run(["rsyslogd", "-N1"], check=True)
    subprocess.run(["logrotate", "--debug", "/etc/logrotate.conf"], check=True)
    subprocess.run(["systemd-analyze", "verify", "rsyslog.service"], check=True)
    exercise_native_rotation(tmp_path)


def wait_until(predicate):
    for _ in range(100):
        if predicate():
            return
        time.sleep(0.05)
    pytest.fail("The isolated logger did not reach the expected state.")


def exercise_native_rotation(tmp_path):
    socket_path = tmp_path / "logger.sock"
    config = tmp_path / "runtime.conf"
    config.write_text(f'module(load="imuxsock" SysSock.Name="{socket_path}")\n'
                      '$PrivDropToUser syslog\n$PrivDropToGroup syslog\n'
                      f'$IncludeConfig /etc/rsyslog.d/*.conf\n')
    for parent in (tmp_path, *tmp_path.parents):
        if parent == Path("/tmp"):
            break
        parent.chmod(0o755)
    active = Path("/mnt/data/host-logs/rsyslog/syslog")
    active.write_text("rotation history\n")
    subprocess.run(["chown", "syslog:adm", active], check=True)
    with active.open("r+b") as stream:
        stream.truncate(134217728 + 1)
    executable = tmp_path / "rsyslog-isolated"
    shutil.copy2("/usr/sbin/rsyslogd", executable)
    daemon = subprocess.Popen([executable, "-n", "-i", str(tmp_path / "logger.pid"), "-f", config],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        wait_until(socket_path.exists)
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            for facility, number in (("user", 1), ("auth", 4), ("kern", 0), ("mail", 2),
                                     ("local5", 21), ("local6", 22)):
                message = (f"<{number * 8 + 5}>{time.strftime('%b %d %H:%M:%S')} "
                           f"testhost crewship-check: crewship-check-{facility}")
                client.sendto(message.encode(), str(socket_path))
        archive = active.with_name("syslog.1")
        wait_until(lambda: archive.exists() and active.exists()
                   and "crewship-check-local6" in active.read_text())
        assert 134217728 <= archive.stat().st_size < 134217728 + 65536
        with archive.open("rb") as stream:
            stream.seek(-65536, 2)
            tail = stream.read().decode()
        assert "crewship-check-user" in tail or "crewship-check-user" in active.read_text()
        for facility, path in (("auth", "/var/log/auth.log"), ("kern", "/var/log/kern.log"),
                               ("mail", "/var/log/mail.log"), ("local5", "/var/log/operator.log"),
                               ("local6", "/var/log/audit-preserved.log")):
            assert f"crewship-check-{facility}" in Path(path).read_text()
        assert "crewship-check-auth" not in active.read_text()
    finally:
        daemon.terminate()
        stdout, stderr = daemon.communicate(timeout=10)
    assert daemon.returncode == 0, (stdout, stderr)


@container_only
def test_missing_mount_blocks_rotation_and_provisioning_without_root_fallback(tmp_path):
    mount = tmp_path / "mounted"
    mount.mkdir()
    subprocess.run(["mount", "-t", "tmpfs", "tmpfs", mount], check=True)
    directory = mount / "logs"
    directory.mkdir()
    helper = render_helper(directory, mount, tmp_path / "rotate")
    subprocess.run(["umount", mount], check=True)
    directory.mkdir()
    active = directory / "syslog"
    active.write_text("root fallback must not change")
    assert subprocess.run([helper], capture_output=True).returncode != 0
    assert active.read_text() == "root fallback must not change"
    result = apply_syslog(tmp_path, data_dir=str(mount))
    assert result.returncode != 0 and "system filesystem" in result.stdout
    assert not (mount / "host-logs").exists()
