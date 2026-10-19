"""tests/herdr-lab: Herdr calls reach only a named fm-lab-* session, with a fake Herdr."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

GUARD = Path(__file__).parent / "herdr-lab"
LAB = "fm-lab-sidebar-1"


def guard(tmp_path, *argv, **env):
    calls = tmp_path / "calls"
    fake = tmp_path / "herdr"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*${{HERDR_SOCKET_PATH:+ socket=$HERDR_SOCKET_PATH}}" >> {calls}\n')
    fake.chmod(0o755)
    done = subprocess.run(
        [str(GUARD), *argv],
        env={**os.environ, "HERDR_BIN_PATH": str(fake), **env},
        capture_output=True,
        text=True,
    )
    return done, calls.read_text().splitlines() if calls.exists() else []


@pytest.mark.parametrize(
    "op",
    [
        ["workspace", "rename", "w1", "firstmate"],
        ["workspace", "create"],
        ["workspace", "close", "w1"],
    ],
)
@pytest.mark.parametrize(
    ("argv", "env"),
    [
        ([""], {}),
        (["default"], {}),
        (["work"], {}),
        ([], {}),
        ([LAB], {"HERDR_SESSION": "default"}),
        ([LAB, "--session", "default"], {}),
    ],
    ids=["empty", "default", "unnamed", "omitted", "env-contradicts", "leading-session"],
)
def test_refuses_lifecycle_calls_without_a_named_lab_before_running_herdr(tmp_path, op, argv, env):
    done, calls = guard(tmp_path, *argv, *op, **env)
    assert done.returncode == 2 and "refused" in done.stderr
    assert calls == []


@pytest.mark.parametrize(
    "argv",
    [
        ["workspace", "rename", "w1", "x", "--session", "default"],
        ["server", "stop"],
        ["session", "delete", LAB],
    ],
)
def test_refuses_a_caller_session_and_server_or_session_operations(tmp_path, argv):
    done, calls = guard(tmp_path, LAB, *argv)
    assert done.returncode == 2 and calls == []


def test_runs_the_call_in_the_named_lab(tmp_path):
    done, calls = guard(
        tmp_path, LAB, "workspace", "rename", "w1", "firstmate", HERDR_SESSION=LAB, HERDR_SOCKET_PATH="/run/default.sock"
    )
    assert done.returncode == 0
    assert calls == [f"workspace rename w1 firstmate --session {LAB}"]
    done, calls = guard(tmp_path, LAB, "agent", "start", "--", "omp")
    assert calls[-1] == f"agent start --session {LAB} -- omp"


def test_bare_herdr_under_pytest_refuses():
    done = subprocess.run(["herdr", "workspace", "rename", "w1", "x"], capture_output=True, text=True)
    assert done.returncode == 97 and "refused" in done.stderr


@pytest.mark.skipif(Path("/etc/crewship-image").exists(), reason="inside the Crewship image")
def test_container_smoke_refuses_in_container_mode_outside_the_image(tmp_path):
    calls = tmp_path / "calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("dirname", "basename"):
        (bin_dir / name).symlink_to(shutil.which(name))
    for name in ("mktemp", "herdr", "python3", "sudo", "docker", "uname"):
        (bin_dir / name).write_text(f'#!/bin/sh\necho "{name} $*" >> {calls}\nexit 97\n')
        (bin_dir / name).chmod(0o755)
    done = subprocess.run(
        ["/bin/bash", str(GUARD.parent / "container-smoke.sh"), "--in-container"],
        env={"PATH": str(bin_dir), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 2 and "refused" in done.stderr
    assert not calls.exists()
