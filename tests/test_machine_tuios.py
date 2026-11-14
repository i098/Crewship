"""machine-tuios opens each installed machine TUI once, in windows of one tuios session."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).parents[1] / "blueprint/maintenance/machine-tuios.sh"
# The launcher runs with a PATH of only the fake tuios, so its shell is named by path.
SHELL = shutil.which("sh")

pytestmark = pytest.mark.skipif(
    not (SHELL and shutil.which("jq")),
    reason="sh and jq run the launcher against its session state",
)

# A stand-in for the tuios CLI: sessions of windows in one JSON file, and every
# call written to a log the tests read back. Only the verbs the launcher uses.
# Its daemon is stopped until something starts it, as a restarted machine leaves it.
FAKE = """
import json, os, sys

state_path, log_path = os.environ["FAKE_STATE"], os.environ["FAKE_LOG"]
daemon_path = state_path + ".daemon"
argv = sys.argv[1:]
with open(log_path, "a") as log:
    log.write(" ".join(argv) + "\\n")
try:
    with open(state_path) as handle:
        sessions = json.load(handle)
except FileNotFoundError:
    sessions = {}

def save():
    with open(state_path, "w") as handle:
        json.dump(sessions, handle)

def flag(name):
    return argv[argv.index(name) + 1] if name in argv else None

session = flag("-s") or flag("--session") or "machine"
verb = argv[0]
if verb == "ls":
    print(json.dumps([{"name": name} for name in sessions]))
    sys.exit(0 if os.path.exists(daemon_path) else 3)
if verb == "start-server":
    open(daemon_path, "w").close()
if verb == "new":
    sessions.setdefault(argv[1], []).append(
        {"window_id": "shell", "custom_name": "Terminal", "display_name": "Terminal"}
    )
    save()
if verb == "list-windows":
    print(json.dumps({"windows": sessions.get(session, [])}))
if verb == "new-window":
    name = argv[1]
    window = {"window_id": name, "custom_name": name, "display_name": name}
    window["command"] = argv[argv.index("--") + 1 :]
    sessions.setdefault(session, []).append(window)
    save()
if verb == "close-window":
    target = argv[1]
    sessions[session] = [w for w in sessions[session] if w["window_id"] != target]
    save()
"""


def install(tmp_path, beside=(), on_path=()):
    """The launcher in bin/ with the TUIs beside it, and a PATH of only the fake tuios."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "path").mkdir()
    shutil.copy(LAUNCHER, tmp_path / "bin/machine-tuios")
    fake = tmp_path / "path/tuios"
    fake.write_text(f"#!{sys.executable}\n{FAKE}")
    fake.chmod(0o755)
    (tmp_path / "path/jq").symlink_to(shutil.which("jq"))
    for tool in beside:
        (tmp_path / "bin" / tool).touch()
        (tmp_path / "bin" / tool).chmod(0o755)
    for tool in on_path:
        (tmp_path / "path" / tool).touch()
        (tmp_path / "path" / tool).chmod(0o755)


def run_launcher(tmp_path, *args, session=None):
    env = {
        "PATH": str(tmp_path / "path"),
        "FAKE_STATE": str(tmp_path / "state.json"),
        "FAKE_LOG": str(tmp_path / "calls.log"),
    }
    if session:
        env["MACHINE_TUIOS_SESSION"] = session
    return subprocess.run(
        [SHELL, str(tmp_path / "bin/machine-tuios"), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def calls(tmp_path, verb):
    log = tmp_path / "calls.log"
    lines = log.read_text().splitlines() if log.exists() else []
    return [line for line in lines if line.split(" ")[0] == verb]


def windows(tmp_path, session="machine"):
    sessions = json.loads((tmp_path / "state.json").read_text())
    return [w["custom_name"] for w in sessions.get(session, [])]


def test_each_installed_tui_gets_one_window_and_a_rerun_adds_none(tmp_path):
    install(tmp_path, beside=("usage-tui", "runs-tui"), on_path=("crewship",))
    result = run_launcher(tmp_path, "--no-attach")
    assert result.returncode == 0, result.stderr
    assert windows(tmp_path) == ["usage", "schedules", "runs"]
    assert calls(tmp_path, "new-window") == [
        f"new-window usage -s machine --no-focus -- {tmp_path}/bin/usage-tui",
        f"new-window schedules -s machine --no-focus -- {tmp_path}/path/crewship schedules",
        f"new-window runs -s machine --no-focus -- {tmp_path}/bin/runs-tui",
    ]
    # The shell window a new session starts with goes once the TUIs stand beside it.
    assert calls(tmp_path, "close-window") == ["close-window shell -s machine"]

    assert run_launcher(tmp_path, "--no-attach").returncode == 0
    assert windows(tmp_path) == ["usage", "schedules", "runs"]
    assert len(calls(tmp_path, "new-window")) == 3
    assert len(calls(tmp_path, "close-window")) == 1

    assert run_launcher(tmp_path).returncode == 0
    assert calls(tmp_path, "attach") == ["attach machine"]


def test_a_missing_tui_is_skipped_with_one_line_and_the_shell_window_stays(tmp_path):
    install(tmp_path)
    result = run_launcher(tmp_path, "--no-attach")
    assert result.returncode == 0, result.stderr
    assert result.stderr.count("skipping") == 7
    assert "skipping usage, usage-tui is not installed" in result.stderr
    assert windows(tmp_path) == ["Terminal"]
    assert calls(tmp_path, "close-window") == []


def test_the_session_name_override_leaves_the_machine_session_alone(tmp_path):
    install(tmp_path, beside=("usage-tui",))
    (tmp_path / "state.json").write_text(
        json.dumps(
            {"machine": [{"window_id": "keep", "custom_name": "keep", "display_name": "keep"}]}
        )
    )
    assert run_launcher(tmp_path, "--no-attach", session="probe").returncode == 0
    assert windows(tmp_path) == ["keep"]
    assert windows(tmp_path, "probe") == ["usage"]
    assert calls(tmp_path, "new-window") == [
        f"new-window usage -s probe --no-focus -- {tmp_path}/bin/usage-tui"
    ]


def test_a_window_named_by_its_custom_name_counts_as_open(tmp_path):
    install(tmp_path, beside=("usage-tui",))
    (tmp_path / "state.json").write_text(
        json.dumps(
            {"machine": [{"window_id": "u", "custom_name": "usage", "display_name": "htop"}]}
        )
    )
    result = run_launcher(tmp_path, "--no-attach")
    assert result.returncode == 0, result.stderr
    assert windows(tmp_path) == ["usage"]
    assert calls(tmp_path, "new-window") == []


def test_a_stopped_daemon_is_started_and_keeps_its_saved_session(tmp_path):
    install(tmp_path, beside=("usage-tui",))
    (tmp_path / "state.json").write_text(
        json.dumps(
            {"machine": [{"window_id": "s", "custom_name": "Terminal", "display_name": "Terminal"}]}
        )
    )
    result = run_launcher(tmp_path, "--no-attach")
    assert result.returncode == 0, result.stderr
    assert calls(tmp_path, "start-server") == ["start-server"]
    # The saved session comes back as it was: nothing is created, and the TUI joins it.
    assert calls(tmp_path, "new") == []
    assert windows(tmp_path) == ["Terminal", "usage"]
