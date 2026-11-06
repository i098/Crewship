"""browsers-tuios opens the browsers session once and never kills or recreates a session."""

import os
import stat
import subprocess
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "blueprint" / "maintenance" / "browsers-tuios"

# A stand-in tuios on PATH: `ls --json` lists $SESSIONS, every call is logged, no real session is touched.
FAKE = """#!/bin/sh
echo "$*" >> "$LOG"
case "$1" in
ls) printf '[%s]' "$SESSIONS" ;;
list-windows) printf '{"windows":[%s]}' "$WINDOWS" ;;
esac
"""


def launch(tmp_path, sessions, windows='{"window_id":"w0"}'):
    fake = tmp_path / "tuios"
    fake.write_text(FAKE)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "log"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "LOG": str(log),
        "SESSIONS": sessions,
        "WINDOWS": windows,
    }
    subprocess.run(["sh", str(LAUNCHER), "--no-attach"], env=env, check=True)
    return log.read_text().splitlines() if log.exists() else []


def test_missing_session_is_created_with_the_viewer_and_the_bare_shell_dropped(tmp_path):
    calls = launch(tmp_path, "")
    assert "new browsers --detach" in calls
    assert "new-window browsers -s browsers --no-focus -- browser-view" in calls
    assert "close-window w0 -s browsers" in calls


def test_session_with_its_viewer_window_is_left_alone(tmp_path):
    calls = launch(tmp_path, '{"name":"browsers"}', '{"window_id":"w1","custom_name":"browsers"}')
    assert not [c for c in calls if c.startswith(("new ", "new-window", "close-window"))]


def test_session_whose_viewer_quit_gets_it_back_without_closing_anything(tmp_path):
    calls = launch(tmp_path, '{"name":"browsers"}', '{"window_id":"w0"}')
    assert "new-window browsers -s browsers --no-focus -- browser-view" in calls
    assert not [c for c in calls if c.startswith(("new ", "close-window"))]
