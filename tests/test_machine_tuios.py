"""machine-tuios opens each machine TUI once as a window of the tuios session `machine`."""

import json
import shutil
import subprocess
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "blueprint" / "maintenance" / "machine-tuios.sh"

FAKE_TUIOS = r"""#!/bin/sh
# State is a JSON file of the session's windows; only the verbs the launcher uses.
state=$STATE
case "$1" in
ls) [ -s "$state" ] && echo '[{"name":"machine"}]' || echo '[]' ;;
new) echo '{"windows":[{"window_id":"shell","display_name":"Terminal"}]}' > "$state" ;;
list-windows) cat "$state" ;;
new-window)
    name=$2; shift 2
    jq --arg n "$name" '.windows += [{"window_id":$n,"display_name":$n}]' "$state" > "$state.new" && mv "$state.new" "$state"
    echo "$name $*" >> "$STATE.cmds" ;;
close-window) jq --arg w "$2" '.windows |= map(select(.window_id != $w))' "$state" > "$state.new" && mv "$state.new" "$state" ;;
attach) echo "attach $2" >> "$STATE.cmds" ;;
esac
"""


def run_launcher(tmp_path, *args):
    return subprocess.run(
        ["sh", str(tmp_path / "bin" / "machine-tuios"), *args], check=True, capture_output=True, text=True,
        env={"PATH": f"{tmp_path / 'path'}:/usr/bin:/bin", "STATE": str(tmp_path / "state.json")},
    )


def install(tmp_path, *tuis):
    """Launcher and TUIs live in bin/, which is not on PATH; only the fake tuios is."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "path").mkdir()
    shutil.copy(LAUNCHER, tmp_path / "bin" / "machine-tuios")
    (tmp_path / "path" / "tuios").write_text(FAKE_TUIOS)
    (tmp_path / "path" / "tuios").chmod(0o755)
    for name in tuis:
        (tmp_path / "bin" / name).touch()
        (tmp_path / "bin" / name).chmod(0o755)


def test_every_installed_tui_gets_one_window_and_a_rerun_adds_none(tmp_path):
    install(tmp_path, "usage-tui", "runs-tui", "crewship-schedules-view")
    run_launcher(tmp_path, "--no-attach")
    run_launcher(tmp_path, "--no-attach")
    windows = json.loads((tmp_path / "state.json").read_text())["windows"]
    assert [w["display_name"] for w in windows] == ["usage", "schedules", "runs"]
    run_launcher(tmp_path)
    assert (tmp_path / "state.json.cmds").read_text().splitlines()[-1] == "attach machine"


def test_tui_beside_the_launcher_runs_by_its_own_path(tmp_path):
    install(tmp_path, "usage-tui")
    run_launcher(tmp_path, "--no-attach")
    assert (tmp_path / "state.json.cmds").read_text().splitlines() == [f"usage -s machine --no-focus -- {tmp_path}/bin/usage-tui"]


def test_no_installed_tui_keeps_the_shell_window_and_names_each_skip(tmp_path):
    install(tmp_path)
    result = run_launcher(tmp_path, "--no-attach")
    windows = json.loads((tmp_path / "state.json").read_text())["windows"]
    assert [w["display_name"] for w in windows] == ["Terminal"]
    assert "skipping runs, runs-tui not installed" in result.stderr
    assert result.stderr.count("skipping schedules") == 1


def test_schedules_fallback_prints_no_skip_line(tmp_path):
    install(tmp_path, "crewship-schedules-view")
    result = run_launcher(tmp_path, "--no-attach")
    assert "skipping schedules" not in result.stderr
