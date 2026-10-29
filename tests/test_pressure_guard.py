"""blueprint/fleet/doctor/pressure-guard.sh against stubbed df, docker, lsof and uv."""

import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
STUBS = {
    "df": 'case "$*" in *pcent*) echo Use%; if [ -e "$STUB/pruned" ]; then echo "${DISK_AFTER:-$DISK_PCT}%"; else echo "${DISK_PCT}%"; fi ;; *) echo Mounted; echo / ;; esac',
    "docker": 'echo "$*" >> "$STUB/calls"; case "$1" in info) echo /var/lib/docker ;; image) touch "$STUB/pruned" ;; esac',
    "lsof": 'case "$3" in *busy*) echo 123; exit 1 ;; *) exit 1 ;; esac',
    "uv": 'echo "uv $*" >> "$STUB/calls"',
    "bun": 'echo "bun $*" >> "$STUB/calls"',
    "du": 'printf "5242880\\t/a/b/c\\n100\\t/a/b\\n"',
    "pgrep": 'exit 1',
    "text": 'echo "$*" >> "$STUB/texts"',
    "wall": 'cat >> "$STUB/alerts"',
}


@pytest.fixture
def run(tmp_path):
    stub = tmp_path / "stub"
    (stub / "bin").mkdir(parents=True)
    for name, body in STUBS.items():
        exe = stub / "bin" / name
        exe.write_text(f"#!/bin/sh\n{body}\n")
        exe.chmod(0o755)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    mem = tmp_path / "meminfo"

    def go(*args, disk=10, ram=10, **env):
        mem.write_text(f"MemTotal: 100 kB\nMemAvailable: {100 - ram} kB\n")
        e = {
            **{k: v for k, v in os.environ.items() if k != "FM_HOME"},
            "PATH": f"{stub / 'bin'}:{os.environ['PATH']}",
            "STUB": str(stub),
            "DISK_PCT": str(disk),
            "PRESSURE_MEMINFO": str(mem),
            "PRESSURE_TMP_ROOT": str(tmp),
            "PRESSURE_TEXT_CMD": str(stub / "bin" / "text"),
            "PRESSURE_STATE_DIR": str(tmp_path / "state"),
            "HOME": str(tmp_path),
            **{k: str(v) for k, v in env.items()},
        }
        r = subprocess.run(
            [str(ROOT / "blueprint/fleet/doctor/pressure-guard.sh"), *args],
            env=e, capture_output=True, text=True, check=False,
        )
        calls = (stub / "calls").read_text() if (stub / "calls").exists() else ""
        alerts = (stub / "alerts").read_text() if (stub / "alerts").exists() else ""
        go.texts = (stub / "texts").read_text() if (stub / "texts").exists() else ""
        return r, calls, alerts

    go.tmp = tmp
    return go


def old_dir(path: Path, hours=3):
    path.mkdir()
    t = time.time() - hours * 3600
    os.utime(path, (t, t))
    return path


def test_below_threshold_does_nothing(run):
    r, calls, alerts = run(disk=70, ram=70)
    assert r.returncode == 0 and "prune" not in calls and alerts == ""


@pytest.mark.parametrize("disk,ram", [(71, 10), (10, 71)])
def test_either_resource_over_threshold_prunes_and_alerts(run, disk, ram):
    r, calls, alerts = run(disk=disk, ram=ram)
    assert "builder prune -af" in calls and "image prune -af" in calls
    assert "uv cache prune" in calls and "bun pm cache rm" in calls
    assert "volume" not in calls
    assert "over 70%" in alerts


def test_scratch_removal_skips_busy_recent_and_git_dirs(run):
    gone = old_dir(run.tmp / "pytest-of-a")
    busy = old_dir(run.tmp / "pytest-of-busy")
    git = old_dir(run.tmp / "pytest-of-git")
    (git / ".git").mkdir()
    fresh = old_dir(run.tmp / "pytest-of-fresh", hours=0)
    run(ram=90)
    assert not gone.exists()
    assert busy.exists() and git.exists() and fresh.exists()


def test_dry_run_changes_nothing_and_reports_steps(run):
    d = old_dir(run.tmp / "pytest-of-a")
    r, calls, alerts = run("--dry-run", PRESSURE_PCT=1)
    assert "would: docker builder cache" in r.stdout and f"scratch {d}" in r.stdout
    assert d.exists() and "prune" not in calls and alerts == ""


def test_alert_repeats_only_after_the_interval(run):
    _, _, first = run(disk=90)
    _, _, second = run(disk=90)
    assert first and second == first


def test_owner_is_texted_only_when_prunes_cannot_get_under_the_threshold(run):
    run(disk=90, DISK_AFTER=50)
    assert run.texts == ""
    r, _, alerts = run(disk=90, DISK_AFTER=80, PRESSURE_STATE_DIR=run.tmp / "other-state")
    assert "Still over 70%" in alerts and "still over 70%" in run.texts


def test_owner_text_is_sent_once_per_still_over_state_and_rearms_after_recovery(run):
    s = {"PRESSURE_REPEAT_MIN": 0}
    run(disk=90, DISK_AFTER=80, **s)
    run(disk=90, DISK_AFTER=80, **s)
    assert run.texts.count("still over") == 1
    run(disk=90, DISK_AFTER=50, **s)
    run(disk=90, DISK_AFTER=80, **s)
    assert run.texts.count("still over") == 2


def test_cleared_pressure_drops_stale_text_key_even_inside_alert_window(run):
    run(disk=80, DISK_AFTER=80, PRESSURE_REPEAT_MIN=0)
    assert run.texts.count("still over") == 1
    (run.tmp.parent / "stub" / "pruned").unlink()
    r, _, _ = run(disk=80, DISK_AFTER=10)
    assert r.returncode == 0 and run.texts.count("still over") == 1
    assert not (run.tmp.parent / "state" / "last-text").exists()
    (run.tmp.parent / "stub" / "pruned").unlink()
    run(disk=80, DISK_AFTER=80, PRESSURE_REPEAT_MIN=0)
    assert run.texts.count("still over") == 2
