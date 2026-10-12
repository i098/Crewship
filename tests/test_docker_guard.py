"""blueprint/fleet/doctor/docker-guard.sh against a stubbed docker.

The stub serves `docker inspect` lines from a fixture file, one container per
line in the guard's own format, and records every call, so the selection rules
(age, keep label, restart policy) are observable through the `rm` calls and
the alerts.
"""

import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
ZERO = "0001-01-01T00:00:00Z"
DOCKER = r"""
echo "$*" >> "$STUB/docker.log"
case "$1" in
  info) exit 0 ;;
  ps) cut -d'|' -f1 "$STUB/containers" ;;
  inspect) cat "$STUB/containers" ;;
  rm) grep -v "^$2|" "$STUB/containers" > "$STUB/c.new"; mv "$STUB/c.new" "$STUB/containers" ;;
esac
"""


def ago(hours: float) -> str:
    t = datetime.now(timezone.utc) - timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%S.123456789Z")


def stopped(cid, hours, restart="no", keep=""):
    return f"{cid}|/{cid}|exited|{ago(hours + 1)}|{ago(hours + 1)}|{ago(hours)}|{restart}|{keep}"


def never_started(cid, hours):
    return f"{cid}|/{cid}|created|{ago(hours)}|{ZERO}|{ZERO}|no|"


def running(cid, hours, restart="no", keep=""):
    return f"{cid}|/{cid}|running|{ago(hours)}|{ago(hours)}|{ZERO}|{restart}|{keep}"


class Guard:
    def __init__(self, tmp: Path):
        self.doctor = tmp / "doctor"
        self.stub = tmp / "stub"
        (self.stub / "bin").mkdir(parents=True)
        self.doctor.mkdir()
        shutil.copy(ROOT / "blueprint/fleet/doctor/docker-guard.sh", self.doctor)
        for path, body in (
            (self.stub / "bin/docker", DOCKER),
            (self.doctor / "notify-master.sh", 'echo "$1" >> "$STUB/alerts"'),
        ):
            path.write_text("#!/usr/bin/env bash\n" + body)
            path.chmod(0o755)
        self.containers()

    def containers(self, *lines: str):
        (self.stub / "containers").write_text("".join(f"{line}\n" for line in lines))

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.doctor / "docker-guard.sh"), *args],
            env={"PATH": f"{self.stub / 'bin'}:/usr/bin:/bin", "STUB": str(self.stub), **env},
            capture_output=True,
            text=True,
            timeout=60,
        )

    def lines(self, path: Path) -> list[str]:
        return path.read_text().splitlines() if path.exists() else []

    def removed(self) -> list[str]:
        return [c for c in self.lines(self.stub / "docker.log") if c.startswith("rm")]

    def alerts(self) -> list[str]:
        return self.lines(self.stub / "alerts")


@pytest.fixture
def guard(tmp_path):
    return Guard(tmp_path)


def test_removes_only_unclaimed_stopped_containers_past_the_age(guard):
    guard.containers(
        stopped("old", 30),
        stopped("young", 2),
        stopped("kept", 30, keep="keep"),
        stopped("restarts", 30, restart="unless-stopped"),
        never_started("never-ran", 30),
        never_started("just-made", 2),
        running("busy", 30),
    )
    assert guard.run().returncode == 0
    assert guard.removed() == ["rm old", "rm never-ran"]
    assert guard.alerts() == []


def test_the_stopped_age_setting_moves_the_cutoff(guard):
    guard.containers(stopped("a", 30), stopped("b", 80))
    assert guard.run(DOCKER_GUARD_STOPPED_HOURS="72").returncode == 0
    assert guard.removed() == ["rm b"]
    assert guard.run(DOCKER_GUARD_STOPPED_HOURS="0").returncode == 2


def test_long_running_unclaimed_containers_are_reported_once_and_never_removed(guard):
    lines = [
        running("forgotten", 50),
        running("kept", 50, keep="keep"),
        running("service", 50, restart="always"),
        running("recent", 2),
    ]
    guard.containers(*lines)
    assert guard.run().returncode == 0
    assert guard.alerts() == ["docker-guard: 1 long-running unclaimed container(s): forgotten (50h)"]
    assert guard.run().returncode == 0
    assert len(guard.alerts()) == 1

    # Gone for one run, back again: reported again.
    guard.containers(*lines[1:])
    guard.run()
    guard.containers(*lines)
    guard.run()
    assert len(guard.alerts()) == 2
    assert guard.removed() == []


def test_dry_run_reports_verdicts_and_changes_nothing(guard):
    guard.containers(stopped("old", 30), running("forgotten", 50))
    result = guard.run("--dry-run")
    assert result.returncode == 0
    assert "would remove old (exited 30h)" in result.stdout
    assert "REPORT forgotten running 50h" in result.stdout
    assert guard.removed() == []
    assert guard.alerts() == []
    assert sorted(p.name for p in guard.doctor.iterdir()) == ["docker-guard.sh", "notify-master.sh"]
