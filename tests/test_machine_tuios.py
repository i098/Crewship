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
        ["sh", str(tmp_path / "machine-tuios"), *args], check=True, capture_output=True, text=True,
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", "STATE": str(tmp_path / "state.json")},
    )


def test_every_installed_tui_gets_one_window_and_a_rerun_adds_none(tmp_path):
    shutil.copy(LAUNCHER, tmp_path / "machine-tuios")
    (tmp_path / "tuios").write_text(FAKE_TUIOS)
    for name in ("tuios", "usage-tui", "runs-tui", "crewship-schedules-view"):
        (tmp_path / name).touch()
        (tmp_path / name).chmod(0o755)
    run_launcher(tmp_path, "--no-attach")
    run_launcher(tmp_path, "--no-attach")
    windows = json.loads((tmp_path / "state.json").read_text())["windows"]
    # The bare shell is closed, a missing command (btop) gets no window, and the
    # schedules fallback runs once.
    assert [w["display_name"] for w in windows] == ["usage", "schedules", "runs"]
    run_launcher(tmp_path)
    assert (tmp_path / "state.json.cmds").read_text().splitlines()[-1] == "attach machine"
