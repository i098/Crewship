"""maintenance/fm-main-stall-nudge decision logic, with herdr and the send helper stubbed."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "maintenance/fm-main-stall-nudge"

# The real helper exits 0 and prints its verdict; the stub prints $SEND_OUT.
BACKEND = """\
fm_backend_send_text_submit() { echo "$@" >> "$CALLS"; printf '%s' "${SEND_OUT-empty}"; }
"""
HERDR = """\
#!/bin/sh
echo "$@" >> "$CALLS"
cat "$PANES"
"""


def panes(*rows):
    return json.dumps(
        {
            "result": {
                "panes": [
                    {"pane_id": pid, "foreground_cwd": cwd, **({"agent": "omp"} if agent else {})}
                    for pid, cwd, agent in rows
                ]
            }
        }
    )


@pytest.fixture
def host(tmp_path):
    home = tmp_path / "firstmate"
    (home / "bin").mkdir(parents=True)
    (home / "state/inbox").mkdir(parents=True)
    (home / "bin/fm-backend.sh").write_text(BACKEND)
    herdr = tmp_path / "herdr"
    herdr.write_text(HERDR)
    herdr.chmod(0o755)
    calls = tmp_path / "calls"
    pane_file = tmp_path / "panes.json"
    pane_file.write_text(panes(("w2:pZ", str(home), True)))

    class Host:
        def note(self, age):
            path = home / "state/inbox/a.note"
            path.write_text("hi")
            os.utime(path, (time.time() - age,) * 2)

        def wake(self, age):
            (home / "state/.wake-queue").write_text(f"{int(time.time() - age)}\tw\n")

        def stamp(self, age):
            (home / "state/.stall-nudge-last").write_text(str(int(time.time() - age)))

        def panes(self, *rows):
            pane_file.write_text(panes(*rows))

        @property
        def stamp_file(self):
            return home / "state/.stall-nudge-last"

        @property
        def sends(self):
            lines = calls.read_text().splitlines() if calls.exists() else []
            return [ln for ln in lines if ln.startswith("herdr ")]

        def run(self, **env):
            return subprocess.run(
                [str(SCRIPT)],
                capture_output=True,
                text=True,
                check=False,
                env={
                    **os.environ,
                    "FM_HOME": str(home),
                    "HERDR_BIN_PATH": str(herdr),
                    "CALLS": str(calls),
                    "PANES": str(pane_file),
                    **env,
                },
            )

    Host.home = home
    return Host()


def test_nothing_waiting_sends_nothing(host):
    assert host.run().returncode == 0
    assert host.sends == []


@pytest.mark.parametrize(
    ("kind", "age", "sent"),
    [
        ("note", 170, False),
        ("note", 190, True),
        ("wake", 590, False),
        ("wake", 610, True),
    ],
)
def test_thresholds(host, kind, age, sent):
    getattr(host, kind)(age)
    assert host.run().returncode == 0
    assert bool(host.sends) is sent


def test_threshold_variables_override_defaults(host):
    host.note(60)
    assert host.run().returncode == 0 and host.sends == []
    assert host.run(NOTE_MAX="30").returncode == 0 and len(host.sends) == 1


def test_sends_to_discovered_pane_with_session_prefix(host):
    host.note(400)
    result = host.run()
    assert result.returncode == 0
    assert "nudged default:w2:pZ: an operator note waits" in result.stdout
    assert host.sends[0].startswith("herdr default:w2:pZ stall watchdog: an operator note waits")


def test_rate_limit(host):
    host.note(400)
    host.stamp(100)
    assert host.run().returncode == 0 and host.sends == []
    host.stamp(400)
    assert host.run().returncode == 0 and len(host.sends) == 1
    assert int(host.stamp_file.read_text()) > time.time() - 5


def test_discovery_needs_an_agent_in_the_firstmate_home(host):
    host.note(400)
    host.panes(
        ("w1:p1", str(host.home), False),
        ("w3:p2", "/elsewhere", True),
        ("w4:p9", str(host.home), True),
    )
    assert host.run().returncode == 0
    assert host.sends[0].startswith("herdr default:w4:p9 ")


def test_no_main_pane_logs_and_stops(host):
    host.note(400)
    host.panes(("w3:p2", "/elsewhere", True))
    result = host.run()
    assert result.returncode == 1
    assert "no main pane" in result.stderr
    assert host.sends == [] and not host.stamp_file.exists()


def test_pane_override_skips_discovery(host):
    host.note(400)
    host.panes()
    assert host.run(MAIN_PANE="w9:p1", HERDR_SESSION="alt").returncode == 0
    assert host.sends[0].startswith("herdr alt:w9:p1 ")


@pytest.mark.parametrize("verdict", ["send-failed", "unknown", "pending", ""])
def test_unconfirmed_send_fails_and_retries_next_run(host, verdict):
    host.note(400)
    result = host.run(SEND_OUT=verdict)
    assert result.returncode == 1
    assert "nudge FAILED for default:w2:pZ" in result.stderr
    assert not host.stamp_file.exists()
    assert host.run().returncode == 0 and len(host.sends) == 2
