"""blueprint/fleet/doctor/storage-guard.sh against stubbed df, du and docker.

The stubs model one 100 GiB filesystem per line of `fs` ("mount size used");
docker's prune commands give back the GiB configured per step, so tier
thresholds, hysteresis and the order of the reclaim steps are observable.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
G = 1 << 30
STUBS = {
    "df": r"""
p=${!#} best=
while read -r m s u; do
  case "$p/" in "${m%/}/"*) [ ${#m} -gt ${#best} ] && best=$m size=$s used=$u ;; esac
done < "$STUB/fs"
[ -n "$best" ] || exit 1
echo "Used Avail Use% Mounted on"
echo "$used $((size - used)) $(( (used * 100 + size - 1) / size ))% $best"
""",
    "du": 'cat "$STUB/du" 2>/dev/null',
    "docker": r"""
echo "$*" >> "$STUB/docker.log"
free() {
  local g m s u
  g=$(cat "$STUB/free.$1" 2>/dev/null || echo 0)
  while read -r m s u; do
    [ "$m" = / ] && u=$((u - g * 1073741824)); echo "$m $s $u"
  done < "$STUB/fs" > "$STUB/fs.new" && mv "$STUB/fs.new" "$STUB/fs"
  echo "Total reclaimed space: ${g}GB"
}
case "$*" in
  info*) [ -e "$STUB/docker-down" ] && exit 1; echo /var/lib/docker ;;
  "system df -v"*) cat "$STUB/df-v.json" ;;
  "system df --format {{.Type}}|"*) echo "Build Cache|500MB" ;;
  "system df"*) echo "Images 10GB, reclaimable 5GB (50%)" ;;
  "builder prune -f") free builder ;;
  "image prune -f") free dangling ;;
  "image prune -af --filter until=168h") free old ;;
esac
""",
}
STEPS = ["builder prune -f", "image prune -f", "image prune -af --filter until=168h"]


class Guard:
    def __init__(self, tmp: Path):
        self.doctor = tmp / "doctor"
        self.stub = tmp / "stub"
        (self.stub / "bin").mkdir(parents=True)
        self.doctor.mkdir()
        shutil.copy(ROOT / "blueprint/fleet/doctor/storage-guard.sh", self.doctor)
        self._exe(self.doctor / "notify-master.sh", 'echo "$1" >> "$STUB/alerts"')
        for name, body in STUBS.items():
            self._exe(self.stub / "bin" / name, body)
        self.env = {
            "PATH": f"{self.stub / 'bin'}:/usr/bin:/bin",
            "HOME": "/home/tester",
            "STUB": str(self.stub),
        }
        self.fs({"/": 50})

    @staticmethod
    def _exe(path: Path, body: str):
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(0o755)

    def fs(self, pcts: dict[str, int]):
        lines = [f"{m} {100 * G} {p * G}" for m, p in pcts.items()]
        (self.stub / "fs").write_text("\n".join(lines) + "\n")

    def free(self, **gib: int):
        for step, amount in gib.items():
            (self.stub / f"free.{step}").write_text(str(amount))

    def pct(self) -> int:
        used = int((self.stub / "fs").read_text().split()[2])
        return used * 100 // (100 * G)

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.doctor / "storage-guard.sh"), *args],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )

    def _lines(self, name: str) -> list[str]:
        path = self.stub / name
        return path.read_text().splitlines() if path.exists() else []

    def prunes(self) -> list[str]:
        return [c for c in self._lines("docker.log") if "prune" in c]

    def alerts(self) -> list[str]:
        return self._lines("alerts")


@pytest.fixture
def guard(tmp_path):
    return Guard(tmp_path)


def test_warn_alerts_once_per_episode_and_rearms_only_below_hysteresis(guard):
    guard.run()
    assert guard.alerts() == []
    guard.fs({"/": 86})
    guard.run()
    guard.run()
    assert len(guard.alerts()) == 1
    assert guard.alerts()[0].startswith("WARN / 86% used, 14.0G free: at 86% (WARN 85%). top:")
    guard.fs({"/": 83})  # under WARN, not under WARN - hysteresis: same episode
    guard.run()
    guard.fs({"/": 86})
    guard.run()
    assert len(guard.alerts()) == 1
    guard.fs({"/": 81})
    guard.run()
    guard.fs({"/": 86})
    guard.run()
    assert len(guard.alerts()) == 2
    assert (guard.doctor / "COMMS.md").read_text().count("[storage-guard -> orchestrator]") == 2
    assert guard.prunes() == []


@pytest.mark.parametrize(
    ("start", "gib", "calls", "end"),
    [
        (95, {"builder": 1, "dangling": 2, "old": 5}, STEPS, 87),
        (93, {"builder": 2, "dangling": 9, "old": 9}, STEPS[:1], 91),
        (95, {"builder": 1, "dangling": 2, "old": 8}, STEPS, 84),
    ],
)
def test_crit_reclaims_cheapest_first_and_stops_once_under_crit(guard, start, gib, calls, end):
    guard.fs({"/": start})
    guard.free(**gib)
    guard.run()
    assert guard.prunes() == calls
    assert guard.pct() == end
    (alert,) = guard.alerts()
    assert alert.startswith(f"CRIT / {end}% used")
    assert f"back to {end}% after reclaiming {start - end}.0G of regenerable Docker data" in alert
    assert "build cache" in (guard.doctor / "storage-guard.log").read_text()
    guard.fs({"/": start})  # refilled by the next tick: reclaimed again, not re-alerted
    guard.run()
    assert guard.prunes() == calls * 2
    assert guard.alerts() == [alert]


def test_crit_that_reclaim_cannot_fix_alerts_loudly_rate_limited(guard):
    guard.fs({"/": 97})
    guard.run()
    guard.run()
    assert guard.prunes() == STEPS * 2
    (alert,) = guard.alerts()
    assert alert.startswith("CRIT / 97% used")
    assert "still at 97% (CRIT 92%) after reclaiming 0B" in alert
    assert "needs a human" in alert
    assert alert.endswith("; docker: Images 10GB, reclaimable 5GB (50%)")
    guard.run(STORAGE_REPEAT_MIN="0")
    assert len(guard.alerts()) == 2
    verbs = {" ".join(c.split()[:2]) for c in guard._lines("docker.log")}
    assert verbs <= {"info -f", "system df", "builder prune", "image prune"}


def test_filesystem_without_docker_is_measured_separately_and_never_pruned(guard):
    guard.fs({"/": 50, "/home": 95})
    guard.run()
    assert guard.prunes() == []
    (alert,) = guard.alerts()
    assert alert.startswith("CRIT /home 95% used")
    assert "no Docker data here to reclaim" in alert


@pytest.mark.parametrize(
    ("fs", "docker_down", "expected"),
    [
        (
            {"/": 95, "/home": 50},
            True,
            "CRIT / 95% used, 5.0G free: at 95% (CRIT 92%), Docker unreachable so nothing reclaimed",
        ),
        (
            {"/": 50, "/home": 50, "/var/log": 96},
            False,
            "CRIT /var/log 96% used, 4.0G free: at 96% (CRIT 92%), no Docker data here to reclaim",
        ),
    ],
)
def test_root_and_var_log_are_measured_even_when_docker_is_elsewhere_or_down(
    guard, fs, docker_down, expected
):
    guard.fs(fs)
    if docker_down:
        (guard.stub / "docker-down").touch()
    guard.run()
    assert guard.prunes() == []
    (alert,) = guard.alerts()
    assert alert.startswith(expected)


def test_fill_rate_alarm_fires_below_warn_and_names_the_fastest_grower(guard):
    state = guard.doctor / ".storage-guard"
    state.mkdir()
    now = int(time.time())
    (state / "_").write_text(f"{now - 600} {49 * G + G // 2} 0 0 0\n")
    guard.run()
    assert guard.alerts() == []  # 0.5G in 10 min: full in ~16h, outside 6h

    (state / "_").write_text(f"{now - 600} {40 * G} 0 0 0\n")
    (state / "_.scan").write_text(
        f"{now - 600} 1\n{30 * G}\t/var\n{1 * G}\t/var/log/syslog\n{20 * G}\t/home\n"
    )
    (guard.stub / "du").write_text(
        f"{40 * G}\t/var\n{11 * G}\t/var/log/syslog\n{10 * G}\t/var/log\n"
        f"{20 * G}\t/home\n{5 * G}\t/home/tester/work\n"
    )
    guard.run()
    (alert,) = guard.alerts()
    assert alert.startswith("FILL / 50% used, 50.0G free: filling: +10.0G in 10m")
    assert "grew most: /var/log/syslog +10.0G in the 10m since the previous scan" in alert
    assert "under /: var 40.0G, home 20.0G; under /var/log: syslog 11.0G" in alert
    assert "under /home/tester: work 5.0G" in alert
    assert guard.prunes() == []


def test_fill_eta_uses_the_free_space_left_after_a_crit_reclaim(guard):
    state = guard.doctor / ".storage-guard"
    state.mkdir()
    (state / "_").write_text(f"{int(time.time()) - 600} {90 * G} 0 0 0\n")
    guard.fs({"/": 95})
    guard.free(builder=1, dangling=2, old=8)
    guard.run()
    (alert,) = guard.alerts()
    assert alert.startswith("CRIT / 84% used, 16.0G free: filling: +5.0G in 10m")
    assert "full in ~0h32m" in alert  # 16G free at 5G per 10m
    assert "back to 84% after reclaiming 11.0G" in alert


def test_dry_run_estimates_each_step_and_writes_nothing(guard):
    old = "2020-01-01 00:00:00 +0000 UTC"
    images = [
        {
            "Repository": "<none>",
            "Tag": "<none>",
            "Containers": "0",
            "CreatedAt": old,
            "UniqueSize": "1GB",
        },
        {
            "Repository": "app",
            "Tag": "v1",
            "Containers": "0",
            "CreatedAt": old,
            "UniqueSize": "2.5GB",
        },
        {"Repository": "db", "Tag": "v1", "Containers": "1", "CreatedAt": old, "UniqueSize": "7GB"},
    ]
    (guard.stub / "df-v.json").write_text(json.dumps({"Images": images, "BuildCache": []}))
    guard.fs({"/": 95})
    before = sorted(p.name for p in guard.doctor.iterdir())
    out = guard.run("--dry-run").stdout
    assert "CRIT step 1 (would run now, stopping once under 92%): docker builder prune -f" in out
    assert "build cache, frees ~476.8M" in out
    assert "dangling images, frees ~953.7M" in out
    assert "unused images created over 168h ago, frees ~2.3G" in out
    assert "a real run would alert: CRIT / 95% used" in out
    assert guard.prunes() == [] and guard.alerts() == [] and guard.pct() == 95
    assert sorted(p.name for p in guard.doctor.iterdir()) == before
