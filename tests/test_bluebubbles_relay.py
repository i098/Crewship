"""Offline relay preparation and fail-closed checks; no Mac or live relay is contacted."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
HELPER = ROOT / "apps/imessage/bluebubbles-relay"
PASSWORD = "bb-" + "a" * 64


@pytest.fixture
def relay(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    commands = {
        "pgrep": '''#!/bin/bash
if [[ "$2" == '[B]lueBubbles' ]]; then
  exit "${APP_STATUS:-1}"
fi
exit "${TUNNEL_STATUS:-1}"
''',
        "openssl": '#!/bin/bash\nprintf "%064d\\n" 0\n',
        "curl": f'''#!{sys.executable}
import os
import sys
args = sys.argv[1:]
# No secret may be passed through the process arguments.
assert not any("bb-" in value for value in args)
assert args[args.index("--noproxy") + 1] == "*"
assert args[-1] == "http://127.0.0.1:1234/api/v1/server/info"
if os.environ.get("API_DOWN"):
    sys.exit(7)
if "--data-urlencode" not in args:
    kind = "NO_PASSWORD"
else:
    assert args[args.index("--data-urlencode") + 1] == "password@-"
    token = sys.stdin.read()
    kind = "CORRECT_PASSWORD" if token == {PASSWORD!r} else "WRONG_PASSWORD"
print(os.environ.get(kind, "200" if kind == "CORRECT_PASSWORD" else "401"), end="")
''',
    }
    for name, content in commands.items():
        command = tmp_path / name
        command.write_text(content)
        command.chmod(0o755)
    return {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "HOME": str(home)}


def run(relay, action, password=PASSWORD):
    return subprocess.run(
        ["bash", str(HELPER), action],
        input=password + "\n", text=True, capture_output=True, env=relay, timeout=10,
    )


def test_prepare_writes_private_offline_settings_without_launching(relay):
    result = run(relay, "prepare")
    assert result.returncode == 0, result.stderr
    config = Path(relay["HOME"]) / "bluebubbles.yml"
    settings = yaml.safe_load(config.read_text())
    assert settings == {
        "persist-config": False, "password": "bb-" + "0" * 64,
        "proxy_service": "lan-url", "socket_port": 1234,
    }
    assert config.stat().st_mode & 0o777 == 0o600
    assert not (config.parent / "config.db").exists()


def test_prepare_preserves_existing_settings(relay):
    config = Path(relay["HOME"]) / "bluebubbles.yml"
    config.write_text("existing settings\n")
    result = run(relay, "prepare")
    assert result.returncode == 1
    assert "not overwritten" in result.stderr
    assert config.read_text() == "existing settings\n"


@pytest.mark.parametrize("status", ["APP_STATUS", "TUNNEL_STATUS"])
def test_prepare_refuses_running_processes(relay, status):
    relay[status] = "0"
    result = run(relay, "prepare")
    assert result.returncode == 1
    assert "is running" in result.stderr
    assert not (Path(relay["HOME"]) / "bluebubbles.yml").exists()


def test_check_accepts_only_authenticated_api(relay):
    result = run(relay, "check")
    assert result.returncode == 0, result.stderr
    assert "Safety check passed" in result.stdout
    assert PASSWORD not in result.stdout + result.stderr


@pytest.mark.parametrize("setting,value,reason", [
    ("TUNNEL_STATUS", "0", "a public tunnel is running"),
    ("TUNNEL_STATUS", "2", "cannot inspect processes"),
    ("NO_PASSWORD", "200", "without a password"),
    ("NO_PASSWORD", "404", "without a password"),
    ("WRONG_PASSWORD", "200", "with a wrong password"),
    ("CORRECT_PASSWORD", "401", "with the password"),
    ("CORRECT_PASSWORD", "302", "with the password"),
    ("API_DOWN", "1", "unreachable"),
])
def test_check_stops_on_an_unsafe_or_unverified_relay(relay, setting, value, reason):
    relay[setting] = value
    result = run(relay, "check")
    assert result.returncode == 1
    assert reason in result.stderr
    assert "do not continue setup" in result.stderr
    assert "Safety check passed" not in result.stdout
    assert PASSWORD not in result.stdout + result.stderr


def test_check_refuses_empty_password(relay):
    result = run(relay, "check", password="")
    assert result.returncode == 1
    assert "password is empty" in result.stderr
