"""maintenance/fm-main-stall-nudge decision logic, with herdr and the send helper stubbed."""

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "maintenance/fm-main-stall-nudge"

# The real helper exits 0 and prints its verdict; the stub prints $SEND_OUT.
BACKEND = """\
fm_backend_send_text_submit() { echo "$@" >> "$CALLS"; printf '%s' "${SEND_OUT-empty}"; return "${SEND_RC-0}"; }
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
    lavish = tmp_path / "lavish.json"
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

        def board(self, role="user", age=400, session="b1"):
            at = datetime.fromtimestamp(time.time() - age, timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            sessions = json.loads(lavish.read_text())["sessions"] if lavish.exists() else {}
            sessions[session] = {"chat": [{"role": "agent", "at": at}, {"role": role, "at": at}]}
            lavish.write_text(json.dumps({"sessions": sessions}))

        @property
        def latch(self):
            path = home / "state/.stall-nudge-boards"
            return path.read_text().split() if path.exists() else []

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
                    "LAVISH_STATE": str(lavish),
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
        ("note", 40, False),
        ("note", 50, True),
        ("wake", 590, False),
        ("wake", 610, True),
    ],
)
def test_thresholds(host, kind, age, sent):
    getattr(host, kind)(age)
    assert host.run().returncode == 0
    assert bool(host.sends) is sent


def test_threshold_variables_override_defaults(host):
    host.note(20)
    assert host.run().returncode == 0 and host.sends == []
    assert host.run(NOTE_MAX="10").returncode == 0 and len(host.sends) == 1


def test_sends_to_discovered_pane_with_session_prefix(host):
    host.note(400)
    result = host.run()
    assert result.returncode == 0
    assert "nudged default:w2:pZ: an operator note waits" in result.stdout
    assert host.sends[0].startswith("herdr default:w2:pZ stall watchdog: an operator note waits")


def test_rate_limit(host):
    host.note(400)
    host.stamp(110)
    assert host.run().returncode == 0 and host.sends == []
    host.stamp(130)
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


@pytest.mark.parametrize(
    ("env", "code", "log", "stream"),
    [
        ({}, 0, "nudged default:w2:pZ", "stdout"),
        ({"SEND_OUT": "send-failed"}, 1, "nudge FAILED for default:w2:pZ", "stderr"),
        ({"SEND_OUT": "unknown"}, 0, "nudge uncertain for default:w2:pZ", "stdout"),
        ({"SEND_OUT": "pending"}, 0, "nudge uncertain for default:w2:pZ", "stdout"),
        ({"SEND_RC": "3"}, 1, "nudge FAILED for default:w2:pZ", "stderr"),
        ({"SEND_OUT": ""}, 1, "nudge FAILED for default:w2:pZ", "stderr"),
    ],
    ids=["empty", "send-failed", "unknown", "pending", "nonzero-rc", "no-output"],
)
def test_send_verdict(host, env, code, log, stream):
    host.note(400)
    result = host.run(**env)
    assert result.returncode == code
    assert log in getattr(result, stream)
    assert len(host.sends) == 1
    assert int(host.stamp_file.read_text()) > time.time() - 5


@pytest.mark.parametrize(
    "env", [{"SEND_OUT": "send-failed"}, {"SEND_RC": "3"}, {"SEND_OUT": "unknown"}]
)
def test_no_second_nudge_inside_gap_after_failed_or_uncertain_send(host, env):
    host.note(400)
    host.run(**env)
    assert host.run().returncode == 0
    assert len(host.sends) == 1


@pytest.mark.parametrize(
    ("age", "sent"), [(250, False), (310, True), (86000, True), (86500, False)]
)
def test_board_answer_age_window(host, age, sent):
    host.board(age=age)
    assert host.run().returncode == 0
    assert bool(host.sends) is sent


def test_board_answer_from_the_agent_is_not_waiting(host):
    host.board(role="agent")
    assert host.run().returncode == 0 and host.sends == []


def test_board_threshold_variable(host):
    host.board(age=60)
    assert host.run().returncode == 0 and host.sends == []
    assert host.run(BOARD_MAX="30").returncode == 0 and len(host.sends) == 1


def test_board_answer_nudges_once_per_answer(host):
    host.board()
    result = host.run()
    assert "an answer on Lavish board b1 has no reply" in result.stdout
    assert len(host.latch) == 1
    host.stamp(400)
    assert host.run().returncode == 0 and len(host.sends) == 1
    host.board(age=350)  # a new answer on the same board has a new timestamp
    host.stamp(400)
    assert host.run().returncode == 0 and len(host.sends) == 2
    assert len(host.latch) == 2


def test_board_answer_inside_gap_stays_unlatched(host):
    host.board()
    host.stamp(100)
    assert host.run().returncode == 0 and host.sends == []
    assert host.latch == []
    host.stamp(400)
    assert host.run().returncode == 0 and len(host.sends) == 1


@pytest.mark.parametrize("env", [{"SEND_OUT": "send-failed"}, {"SEND_RC": "3"}, {"SEND_OUT": ""}])
def test_failed_send_leaves_board_unlatched(host, env):
    host.board()
    assert host.run(**env).returncode == 1
    assert host.latch == []
    host.stamp(400)
    assert host.run().returncode == 0 and len(host.sends) == 2
    assert len(host.latch) == 1


def test_uncertain_send_latches_board(host):
    host.board()
    assert host.run(SEND_OUT="unknown").returncode == 0
    assert len(host.latch) == 1


def test_board_answer_stays_unlatched_without_a_main_pane(host):
    host.board()
    host.panes()
    assert host.run().returncode == 1
    assert host.latch == []


def test_missing_lavish_state_is_not_an_error(host):
    assert host.run().returncode == 0 and host.sends == []


def test_note_nudge_leaves_board_unlatched(host):
    host.note(400)
    host.board()
    assert host.run().returncode == 0 and len(host.sends) == 1
    assert host.latch == []
