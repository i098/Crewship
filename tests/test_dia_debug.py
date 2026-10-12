"""tools/dia-debug/dia-debug: when it relaunches the browser with the CDP port flag."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "tools/dia-debug/dia-debug"
STUBS = {
    "lsappinfo": "echo '\"pid\"=4242'",
    "ps": 'case "$2" in command=) echo "$CMD" ;; etime=) echo "$ETIME" ;; esac',
    "kill": '[ "$1" = -0 ] && exit 1; echo "kill $*" >> "$LOG"',
    "open": 'echo "open $*" >> "$LOG"',
}
PLAIN = "/Applications/Dia.app/Contents/MacOS/Dia"
RELAUNCH = ["kill -TERM 4242", "open -b company.thebrowser.dia --args --remote-debugging-port=9222"]


@pytest.fixture
def run(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n")
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "log"

    def go(cmd, etime, *args):
        env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            TMPDIR=str(tmp_path),
            LOG=str(log),
            CMD=cmd,
            ETIME=etime,
        )
        # kill is a bash builtin; turn it off so the PATH stub answers.
        subprocess.run(
            ["bash", "-c", 'enable -n kill; . "$0" "$@"', str(SCRIPT), *args], env=env, check=True
        )
        calls = log.read_text().splitlines() if log.exists() else []
        log.unlink(missing_ok=True)
        return calls

    return go


def test_syntax():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


@pytest.mark.parametrize(
    "cmd,etime",
    [
        (PLAIN + " --remote-debugging-port=9222", "00:05"),
        (PLAIN, "01:30"),
        (PLAIN, "01:00:05"),
        (PLAIN, "2-03:00:00"),
    ],
)
def test_no_action(run, cmd, etime):
    assert run(cmd, etime) == []


def test_young_flagless_relaunches_once_per_pid(run):
    assert run(PLAIN, "01:29") == RELAUNCH
    assert run(PLAIN, "01:29") == []


def test_now_relaunches_old_browser(run):
    assert run(PLAIN, "2-03:00:00", "--now") == RELAUNCH
