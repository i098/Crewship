"""Reaper discovery uses only fixture PIDs and never sends a signal."""

import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DOCTOR = ROOT / "blueprint/fleet/doctor"


@contextmanager
def process(cwd, name):
    child = subprocess.Popen(
        [sys.executable, "-c", "import ctypes,time; "
         f"ctypes.CDLL(None).prctl(15, {name.encode()!r}, 0, 0, 0); "
         "print('ready', flush=True); time.sleep(120)"],
        cwd=cwd, stdout=subprocess.PIPE, text=True,
    )
    try:
        assert child.stdout.readline() == "ready\n"
        yield child
    finally:
        child.terminate()
        child.wait(timeout=5)
        child.stdout.close()


@pytest.fixture
def reaper(tmp_path):
    home = tmp_path / "home"
    native = tmp_path / "native [root]"
    config = home / ".config/treehouse/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f"root = {json.dumps(str(native))}\n")
    doctor = tmp_path / "doctor"
    doctor.mkdir()
    for source in DOCTOR.glob("*.py"):
        shutil.copy(source, doctor)
    shutil.copy(DOCTOR / "dev-server-reaper.sh", doctor)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pgrep = bin_dir / "pgrep"
    pgrep.write_text('#!/bin/sh\ncase "$*" in\n'
                     '  "-x omp|claude|codex|grok|kimi|cursor") echo "$AGENT_PID" ;;\n'
                     '  "-P "*) exit 1 ;;\n'
                     '  *) echo "$TARGET_PID" ;;\nesac\n')
    pgrep.chmod(0o755)
    return home, native, doctor, bin_dir


def run(reaper, target, agent=""):
    home, _, doctor, bin_dir = reaper
    subprocess.run(
        [str(doctor / "dev-server-reaper.sh")],
        env={"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin",
             "REAPER_DRY_RUN": "1", "TARGET_PID": str(target.pid), "AGENT_PID": str(agent)},
        check=True, capture_output=True, text=True, timeout=30,
    )
    assert target.poll() is None
    log = doctor / "dev-server-reaper.log"
    assert not (doctor / "COMMS.md").exists()
    return log.read_text() if log.exists() else ""


def worktree(reaper, layout):
    home, native, _, _ = reaper
    roots = {"native": native / ".treehouse", "legacy": home / ".treehouse"}
    wt = (home / ".no-mistakes/worktrees/repo/run" if layout == "no-mistakes"
          else roots[layout] / "project-1/2/repo")
    wt.mkdir(parents=True)
    return wt


@pytest.mark.parametrize("layout", ["native", "legacy", "no-mistakes"])
def test_orphan_server_matches_supported_roots(reaper, layout):
    wt = worktree(reaper, layout)
    with process(wt, "next-server") as target:
        assert "no agent process in worktree" in run(reaper, target)


@pytest.mark.parametrize("metadata_root", ["native", "legacy"])
@pytest.mark.parametrize("layout", ["native", "legacy", "no-mistakes"])
def test_lane_metadata_is_found_across_roots(reaper, layout, metadata_root):
    home, native, _, _ = reaper
    wt = worktree(reaper, layout)
    base = native if metadata_root == "native" else home
    meta = base / ".treehouse/firstmate-1/1/firstmate/state/lane.meta"
    meta.parent.mkdir(parents=True)
    meta.write_text(f"worktree={wt}\n")
    meta.with_suffix(".status").write_text("done [at=1]: complete\n")
    with process(wt, "next-server") as target, process(wt, "omp") as agent:
        assert "lane reported done:" in run(reaper, target, agent.pid)


@pytest.mark.parametrize("layout", ["native", "legacy", "no-mistakes"])
def test_unknown_active_lane_is_preserved(reaper, layout):
    wt = worktree(reaper, layout)
    with process(wt, "next-server") as target, process(wt, "omp") as agent:
        assert run(reaper, target, agent.pid) == ""


def test_server_outside_supported_roots_is_preserved(reaper, tmp_path):
    wt = tmp_path / "unmanaged/project-1/2/repo"
    wt.mkdir(parents=True)
    with process(wt, "next-server") as target:
        assert run(reaper, target) == ""


@pytest.mark.parametrize("layout", ["native", "legacy", "no-mistakes"])
def test_busy_agent_is_preserved_but_idle_agent_is_eligible(reaper, layout):
    home, _, _, _ = reaper
    wt = worktree(reaper, layout)
    relative = str(wt).removeprefix(f"{home}/").replace("/", "-")
    transcript = home / f".omp/agent/sessions/project-{relative}/session.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}\n")
    with process(wt, "next-server") as target, process(wt, "omp") as agent:
        assert run(reaper, target, agent.pid) == ""
        os.utime(transcript, (1, 1))
        assert "agent idle" in run(reaper, target, agent.pid)
