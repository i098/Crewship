"""blueprint/fleet/doctor/storage-guard.sh against stubbed df, du and docker.

The stubs model one 100 GiB filesystem per line of `fs` ("mount size used");
docker's prune commands give back the GiB configured per step, so tier
thresholds, hysteresis and the order of the reclaim steps are observable.
"""

import fcntl
import json
import os
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
    "du": 'echo scan >> "$STUB/events"; cat "$STUB/du" 2>/dev/null',
    "findmnt": r"""
if [[ "$*" == *" -T "* ]]; then
  if [[ "$*" == *MAJ:MIN* ]]; then
    if [ "${!#}" = / ]; then echo 0:1; else cat "$STUB/state-device" 2>/dev/null || echo 0:2; fi
  else cat "$STUB/state-mount"; fi
else cat "$STUB/mounts" 2>/dev/null; fi
""",
    "mountpoint": 'test "$(cat "$STUB/state-mount" 2>/dev/null)" != /',
    "docker": r"""
echo "$*" >> "$STUB/docker.log"
case "$*" in info*) echo discovery >> "$STUB/events" ;; *prune*) echo reclaim >> "$STUB/events" ;; esac
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
        for script in ("storage-guard.sh", "worktree-prune.sh", "treehouse-roots.py"):
            shutil.copy(ROOT / "blueprint/fleet/doctor" / script, self.doctor)
        self._exe(self.doctor / "notify-master.sh", 'echo broadcast >> "$STUB/broadcasts"')
        home = self.stub / "firstmate"
        (home / "bin").mkdir(parents=True)
        self._exe(home / "bin/fm-inbox.sh", r"""
echo "notify $3" >> "$STUB/events"
printf '%s\n' "$3" >> "$STUB/attempts"
case "$(cat "$STUB/delivery" 2>/dev/null)" in
  enospc) echo alert > /dev/full; exit 1 ;;
  timeout) sleep 10 ;;
  malformed) echo queued; exit 0 ;;
  uncertain) announced=false ;;
  *) announced=true ;;
esac
printf '%s\n' "${!#}" >> "$STUB/alerts"
jq -nc --arg id "$3" --argjson announced "$announced" \
  '{schema:"fm-inbox-note.v1", outcome:"created", id:"note-1", request_id:$id,
    saved:true, announced:$announced, acknowledged:false}'
""")
        self.home = home
        for name, body in STUBS.items():
            self._exe(self.stub / "bin" / name, body)
        self.env = {
            "PATH": f"{self.stub / 'bin'}:/usr/bin:/bin",
            "HOME": "/home/tester",
            "STUB": str(self.stub),
            "FM_HOME": str(home),
            "HOSTNAME": "fixture",
            "STORAGE_BROADCAST_TIMEOUT": "60",  # a loaded host can starve a 3s stub; the tests assert delivery, not speed
        }
        self.fs({"/": 50})

    @staticmethod
    def _exe(path: Path, body: str):
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(0o755)

    def fs(self, pcts: dict[str, int]):
        lines = [f"{m} {100 * G} {p * G}" for m, p in pcts.items()]
        (self.stub / "fs").write_text("\n".join(lines) + "\n")

    def mounts(self, text: str):
        """What `findmnt -rno TARGET,FSTYPE,SOURCE` prints; no file, no mounts."""
        (self.stub / "mounts").write_text(text)

    def free(self, **gib: int):
        for step, amount in gib.items():
            (self.stub / f"free.{step}").write_text(str(amount))

    def pct(self) -> int:
        used = int((self.stub / "fs").read_text().split()[2])
        return used * 100 // (100 * G)

    def run(self, *args: str, check=True, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.doctor / "storage-guard.sh"), *args],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=check,
            timeout=60,
        )

    def pool_with_stale_output(self, pools: Path | None = None) -> Path:
        """A Treehouse pool worktree holding a tracked file and month-old ignored output."""
        home = self.doctor.parent / "home"
        repo = (pools or home / ".treehouse") / "proj-1/2/repo"
        (repo / "node_modules/pkg").mkdir(parents=True)
        (repo / ".gitignore").write_text("node_modules/\n")
        (repo / "tracked.txt").write_text("keep")
        (repo / "node_modules/pkg/index.js").write_text("x")
        month = time.time() - 30 * 86400
        for path in (repo / "node_modules/pkg/index.js", repo / "node_modules/pkg", repo / "node_modules"):
            os.utime(path, (month, month))
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "init"], check=True)
        self.env["HOME"] = str(home)
        return repo

    def _lines(self, name: str) -> list[str]:
        path = self.stub / name
        return path.read_text().splitlines() if path.exists() else []

    def prunes(self) -> list[str]:
        return [c for c in self._lines("docker.log") if "prune" in c]

    def alerts(self) -> list[str]:
        return [line.split("] ", 1)[-1] for line in self._lines("alerts")]


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
    assert guard.alerts()[0].startswith("WARN / 86%")
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
    assert (guard.doctor / ".storage-guard/COMMS.md").read_text().count("[storage-guard -> orchestrator]") == 2
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
    assert alert.startswith(f"CRIT / {start}% used")
    log = (guard.doctor / ".storage-guard/storage-guard.log").read_text()
    assert "build cache" in log
    assert f"now {end}%" in log
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


@pytest.mark.parametrize("fs", [{"/": 95, "/home": 50}, {"/": 50, "/var/log": 96}])
def test_root_and_var_log_are_measured_even_when_docker_is_elsewhere_or_down(guard, fs):
    guard.fs(fs)
    (guard.stub / "docker-down").touch()
    guard.run()
    assert guard.prunes() == []
    assert [a.split()[1] for a in guard.alerts()] == [
        mount for mount, pct in fs.items() if pct >= 92
    ]


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
    guard.run(STORAGE_FILL_MIN_PCT="0")  # the 70% floor has its own test below
    (alert,) = guard.alerts()
    assert alert.startswith("FILL / 50% used, 50.0G free: filling: +10.0G in 10m")
    diagnostics = (state / "storage-guard.log").read_text()
    assert "/var/log/syslog +10.0G" in diagnostics
    assert "under /: var 40.0G, home 20.0G; under /var/log: syslog 11.0G" in diagnostics
    assert "under /home/tester: work 5.0G" in diagnostics
    assert guard.prunes() == []


def test_every_real_block_filesystem_is_measured_once_and_pseudo_ones_are_skipped(guard):
    guard.fs({"/": 50, "/sdb": 95, "/sdb/bind": 95, "/sdc": 86, "/snap/core": 100, "/ovl": 100, "/mnt/ram": 100})
    guard.mounts(
        "/ ext4 /dev/sda2\n/run tmpfs tmpfs\n/sdb ext4 /dev/sdb1\n/sdb/bind ext4 /dev/sdb1[/sub]\n"
        "/sdc xfs /dev/sdc1\n/snap/core squashfs /dev/loop1\n/ovl overlay overlay\n"
        "/mnt/ram ext4 /dev/loop9\n/nsfs nsfs nsfs[mnt:[1]]\n"
    )
    guard.run()
    crit, warn = guard.alerts()
    assert crit.startswith("CRIT /sdb 95% used")
    assert warn.startswith("WARN /sdc 86% used")
    assert guard.prunes() == []


def test_each_mount_alerts_once_per_episode_and_rearms_on_its_own(guard):
    guard.mounts("/ ext4 /dev/sda2\n/sdb ext4 /dev/sdb1\n/sdc ext4 /dev/sdc1\n")
    guard.fs({"/": 50, "/sdb": 86, "/sdc": 86})
    guard.run()
    guard.run()
    assert [a.split()[1] for a in guard.alerts()] == ["/sdb", "/sdc"]
    guard.fs({"/": 50, "/sdb": 70, "/sdc": 86})  # only /sdb drops below WARN - hysteresis
    guard.run()
    guard.fs({"/": 50, "/sdb": 86, "/sdc": 86})
    guard.run()
    assert [a.split()[1] for a in guard.alerts()] == ["/sdb", "/sdc", "/sdb"]


def test_alert_names_the_five_entries_that_grew_most_since_the_previous_scan(guard):
    now = int(time.time())
    scan = "".join(f"\n{G}\t/{n}" for n in "abcdefg")
    (guard.doctor / ".storage-guard").mkdir()
    (guard.doctor / ".storage-guard/_.scan").write_text(f"{now - 3600} 1{scan}\n")
    guard.fs({"/": 86})
    (guard.stub / "du").write_text("".join(f"{(i + 2) * G}\t/{n}\n" for i, n in enumerate("abcdefg")))
    guard.run()
    diagnostics = (guard.doctor / ".storage-guard/storage-guard.log").read_text()
    assert "/g +7.0G, /f +6.0G, /e +5.0G, /d +4.0G, /c +3.0G" in diagnostics


def test_scan_looks_one_level_under_the_biggest_entry_only(guard):
    guard.fs({"/": 86})
    # du prints a directory after its children
    rows = [(4, "/x/big"), (1, "/x/small"), (10, "/x"), (2, "/y/z"), (3, "/y")]
    (guard.stub / "du").write_text("".join(f"{g * G}\t{p}\n" for g, p in rows))
    guard.run()
    diagnostics = (guard.doctor / ".storage-guard/storage-guard.log").read_text()
    assert "under /: x 10.0G, y 3.0G; under /x: big 4.0G, small 1.0G" in diagnostics
    assert "/y/z" not in diagnostics and "z 2.0G" not in diagnostics


def test_crit_runs_the_configured_prune_command_instead_of_the_bundled_script(guard):
    home = guard.doctor.parent / "home"
    (home / ".treehouse").mkdir(parents=True)
    guard.env["HOME"] = str(home)
    Guard._exe(guard.stub / "prune", 'echo "called $*" >> "$STUB/prune.log"')
    guard.fs({"/": 95})
    guard.run(WORKTREE_PRUNE_CMD=str(guard.stub / "prune"))
    assert guard._lines("prune.log") == ["called "]


def test_fill_alert_uses_pressure_before_reclaim(guard):
    state = guard.doctor / ".storage-guard"
    state.mkdir()
    (state / "_").write_text(f"{int(time.time()) - 600} {90 * G} 0 0 0\n")
    guard.fs({"/": 95})
    guard.free(builder=1, dangling=2, old=8)
    guard.run()
    (alert,) = guard.alerts()
    assert "CRIT / 95% used, 5.0G free" in alert
    assert "full in ~0h10m" in alert
    assert guard.pct() == 84


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
    assert "CRIT / 95% used" in out
    assert guard.prunes() == [] and guard.alerts() == [] and guard.pct() == 95
    assert sorted(p.name for p in guard.doctor.iterdir()) == before


def test_crit_prunes_stale_gitignored_worktree_output_and_nothing_else(guard):
    repo = guard.pool_with_stale_output()
    guard.fs({"/": 95})
    guard.run()
    assert not (repo / "node_modules").exists()
    assert (repo / "tracked.txt").is_file() and (repo / ".gitignore").is_file()
    log = (guard.doctor / ".storage-guard/storage-guard.log").read_text()
    assert f"removed {repo}/node_modules" in log


def test_below_crit_and_in_dry_run_the_worktree_output_stays(guard):
    repo = guard.pool_with_stale_output()
    guard.fs({"/": 90})
    guard.run()
    assert (repo / "node_modules/pkg/index.js").is_file()
    guard.fs({"/": 95})
    out = guard.run("--dry-run").stdout
    assert f"would remove {repo}/node_modules" in out
    assert "CRIT worktree step (would run now" in out
    assert (repo / "node_modules/pkg/index.js").is_file()


@pytest.mark.parametrize("critical_root", ["native", "legacy"])
def test_native_and_legacy_pools_are_pruned_only_on_the_critical_mount(guard, critical_root):
    home_repo = guard.pool_with_stale_output()
    native = guard.doctor.parent / "bulk"
    native_repo = guard.pool_with_stale_output(native / ".treehouse")
    config = Path(guard.env["HOME"]) / ".config/treehouse/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f'root = "{native}"\n')
    critical = native if critical_root == "native" else Path(guard.env["HOME"])
    guard.fs({"/": 50, str(critical): 95})

    guard.run()

    removed, kept = ((native_repo, home_repo) if critical_root == "native" else (home_repo, native_repo))
    assert not (removed / "node_modules").exists()
    assert (kept / "node_modules/pkg/index.js").is_file()
    assert (removed / "tracked.txt").is_file()
    assert guard.prunes() == []


@pytest.mark.parametrize(("pct", "alerted"), [(25, False), (75, True)])
def test_fill_rate_alarm_waits_for_the_fill_floor(guard, pct, alerted):
    state = guard.doctor / ".storage-guard"
    state.mkdir()
    now = int(time.time())
    (state / "_").write_text(f"{now - 600} {(pct - 10) * G} 0 0 0\n")  # +10G in 10 min
    guard.fs({"/": pct})
    dry = guard.run("--dry-run").stdout
    assert ("+10.0G in 10m" in dry) and (("below FILL floor 70%" in dry) == (not alerted))
    guard.run()
    if alerted:
        (alert,) = guard.alerts()
        assert alert.startswith(f"FILL / {pct}% used, {100 - pct}.0G free: filling: +10.0G in 10m")
    else:
        assert guard.alerts() == []
    assert (state / "_").read_text().split()[1] == str(pct * G)  # sampled, so a rate exists at the crossing


def test_all_pressure_alerts_precede_scans_and_reclaim(guard):
    guard.fs({"/": 95, "/home": 95})
    guard.run()
    events = guard._lines("events")
    attempts = [i for i, event in enumerate(events) if event.startswith("notify ")]
    slow = [i for i, event in enumerate(events) if event in ("scan", "reclaim")]
    assert len(attempts) == 2
    assert max(attempts) < min(slow)


@pytest.mark.parametrize("failure", ["mkdir", "lock-open", "flock"])
@pytest.mark.parametrize("delivery", ["success", "enospc"])
def test_initialization_errors_notify_without_changing_saved_state(guard, failure, delivery):
    state = guard.doctor / ".storage-guard"
    original_body = "Original alert for the archive filesystem"
    if failure == "mkdir":
        Guard._exe(guard.stub / "bin/mkdir", 'echo "No space left on device" >&2; exit 1')
    else:
        state.mkdir()
        now = int(time.time())
        (state / "_").write_text(f"{now - 600} {80 * G} 0 0 0 0\n")
        (state / "_data").write_text(f"{now - 600} {65 * G} 0 0 0 0\n")
        (state / "_archive.WARN.pending").write_text(f"retained-request 1 0 0 1\n{original_body}\n")
        (state / "storage-guard.log").write_text("Saved log\n")
        (state / "COMMS.md").write_text("Saved communications\n")
        (state / "_.scan").write_text(f"{now - 600} 1\n{70 * G}\t/var\n")
        if failure == "lock-open":
            (state / "lock").mkdir()
        else:
            (state / "lock").write_text("Lock contents\n")
            Guard._exe(guard.stub / "bin/flock", 'echo "flock failed" >&2; exit 70')
    before_names = {p.name for p in state.iterdir()} if state.exists() else set()
    before = {p.name: p.read_bytes() for p in state.iterdir() if p.is_file()} if state.exists() else {}
    if delivery == "enospc":
        (guard.stub / "delivery").write_text(delivery)
    Guard._exe(guard.doctor / "notify-master.sh", 'echo broadcast >> "$STUB/events"')
    pools = guard.doctor.parent / "pools"
    pools.mkdir()
    Guard._exe(guard.stub / "prune", 'echo worktree-reclaim >> "$STUB/events"')
    guard.fs({"/": 95, "/home": 86, "/data": 95 if failure == "mkdir" else 75})
    guard.mounts("/data ext4 /dev/data\n")
    guard.free(builder=15)
    result = guard.run(check=False, WORKTREE_PRUNE_POOLS=str(pools),
                       WORKTREE_PRUNE_CMD=str(guard.stub / "prune"))
    assert result.returncode != 0
    events = guard._lines("events")
    attempts = [i for i, event in enumerate(events) if event.startswith("notify ")]
    slow = [i for i, event in enumerate(events) if event in ("scan", "reclaim", "worktree-reclaim")]
    assert len(attempts) == (3 if failure == "mkdir" else 4)
    assert max(attempts) < min(slow)
    assert "worktree-reclaim" in events and "scan" in events
    assert guard.prunes() == STEPS[:1]
    assert guard.pct() == 80
    if delivery == "enospc":
        broadcasts = [i for i, event in enumerate(events) if event == "broadcast"]
        assert len(broadcasts) == len(attempts)
        assert max(broadcasts) < min(slow)
    if failure == "mkdir":
        assert not state.exists()
    else:
        assert events[0] == "notify retained-request"
        assert events.index("discovery") > 0
        if delivery == "success":
            assert guard._lines("alerts")[0] == original_body
        assert {p.name for p in state.iterdir()} == before_names
        assert {p.name: p.read_bytes() for p in state.iterdir() if p.is_file()} == before


def test_lock_contention_exits_without_delivery_maintenance_or_state_changes(guard):
    state = guard.doctor / ".storage-guard"
    state.mkdir()
    (state / "lock").write_text("Lock contents\n")
    (state / "_.WARN.pending").write_text("retained-request 1 0 0 1\nOriginal alert\n")
    guard.fs({"/": 95})
    before = {p.name: p.read_bytes() for p in state.iterdir()}
    with (state / "lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = guard.run(check=False)
    assert result.returncode == 0
    assert guard._lines("events") == []
    assert guard._lines("attempts") == []
    assert guard.prunes() == []
    assert guard.pct() == 95
    assert {p.name: p.read_bytes() for p in state.iterdir()} == before


@pytest.mark.parametrize(("initial", "refreshed", "eligible"), [
    (84, 95, False),
    (86, 95, False),
    (95, 80, False),
    (95, 95, True),
])
@pytest.mark.parametrize("reclaimer", ["docker", "worktree", "both"])
def test_reclaim_requires_first_pass_pressure_and_stops_after_usage_falls(
    guard, initial, refreshed, eligible, reclaimer
):
    guard.fs({"/": refreshed, "/home": 86})
    (guard.stub / "fs-after-notify").write_bytes((guard.stub / "fs").read_bytes())
    guard.fs({"/": 80, "/home": 86})
    (guard.stub / "fs-after-worktree").write_bytes((guard.stub / "fs").read_bytes())
    if reclaimer != "docker":
        pools = guard.doctor.parent / "pools"
        pools.mkdir()
        Guard._exe(guard.stub / "prune", r"""
echo worktree-reclaim >> "$STUB/events"
cat "$STUB/fs-after-worktree" > "$STUB/fs"
""")
        guard.env["WORKTREE_PRUNE_POOLS"] = str(pools)
        guard.env["WORKTREE_PRUNE_CMD"] = str(guard.stub / "prune")
    if reclaimer == "worktree":
        (guard.stub / "docker-down").touch()
    inbox = guard.home / "bin/fm-inbox.sh"
    inbox.rename(guard.home / "bin/original-inbox")
    Guard._exe(inbox, r"""
cat "$STUB/fs-after-notify" > "$STUB/fs"
exec "$FM_HOME/bin/original-inbox" "$@"
""")
    guard.fs({"/": initial, "/home": 86})
    guard.free(builder=15)
    guard.run()
    root_alerts = [alert for alert in guard.alerts() if alert.split()[1] == "/"]
    if initial >= 85:
        assert len(root_alerts) == 1 and f"/ {initial}% used" in root_alerts[0]
    else:
        assert root_alerts == []
    events = guard._lines("events")
    attempts = [i for i, event in enumerate(events) if event.startswith("notify ")]
    slow = [i for i, event in enumerate(events) if event in ("scan", "reclaim", "worktree-reclaim")]
    assert max(attempts) < min(slow)
    assert events.count("worktree-reclaim") == int(eligible and reclaimer != "docker")
    assert guard.prunes() == (STEPS[:1] if eligible and reclaimer == "docker" else [])
    assert guard.pct() == (80 if eligible else refreshed)
    saved_usage = (guard.doctor / ".storage-guard/_").read_text().split()[1]
    assert int(saved_usage) == (80 if eligible else initial) * G


@pytest.mark.parametrize("staging", ["write", "rename"])
@pytest.mark.parametrize("delivery", ["success", "broadcast", "wall"])
def test_failed_pending_staging_attempts_all_alerts_before_maintenance(guard, staging, delivery):
    state = guard.doctor / ".storage-guard"
    state.mkdir()
    (state / "_data").write_text(f"{int(time.time()) - 600} {65 * G} 0 0 0 0\n")
    records = ("_.CRIT.pending", "_home.WARN.pending", "_data.FILL.pending")
    if staging == "write":
        for record in records:
            (state / f"{record}.tmp").symlink_to("/dev/full")
    else:
        Guard._exe(guard.stub / "bin/mv", r"""
if [[ "${!#}" == *.pending ]]; then
  echo "pending commit failed" >&2
  exit 1
fi
exec /usr/bin/mv "$@"
""")
    if delivery != "success":
        (guard.stub / "delivery").write_text("enospc")
    Guard._exe(guard.doctor / "notify-master.sh",
               'echo broadcast >> "$STUB/events"; echo broadcast >> "$STUB/broadcasts"')
    if delivery == "wall":
        (guard.doctor / "notify-master.sh").unlink()
        Guard._exe(guard.stub / "bin/wall", 'echo wall >> "$STUB/events"; cat > "$STUB/wall"')
    pools = guard.doctor.parent / "pools"
    pools.mkdir()
    Guard._exe(guard.stub / "prune", 'echo worktree-reclaim >> "$STUB/events"')
    guard.fs({"/": 95, "/home": 86, "/data": 75})
    guard.mounts("/data ext4 /dev/data\n")
    result = guard.run(check=False, WORKTREE_PRUNE_POOLS=str(pools),
                       WORKTREE_PRUNE_CMD=str(guard.stub / "prune"))
    assert result.returncode != 0
    assert result.stderr.count("cannot retain alert") == 3
    events = guard._lines("events")
    attempts = [i for i, event in enumerate(events) if event.startswith("notify ")]
    slow = [i for i, event in enumerate(events) if event in ("scan", "reclaim", "worktree-reclaim")]
    assert len(attempts) == 3
    assert max(attempts) < min(slow)
    assert "worktree-reclaim" in events and "reclaim" in events and "scan" in events
    if delivery == "success":
        assert [alert.split()[0] for alert in guard.alerts()] == ["CRIT", "WARN", "FILL"]
        assert "broadcast" not in events
    else:
        fallback = "broadcast" if delivery == "broadcast" else "wall"
        assert events.count(fallback) == 3
        assert max(i for i, event in enumerate(events) if event == fallback) < min(slow)
    assert not list(state.glob("*.pending"))
    assert not list(state.glob("*.ack"))
    assert not list(state.glob("*.broadcast"))
    assert not (state / "_").exists()
    assert not (state / "_home").exists()
    assert (state / "_data").read_text().split()[2:] == ["0", "0", "0", "0"]


@pytest.mark.parametrize("configured_data", [False, True])
def test_state_location_uses_only_the_configured_data_directory(guard, configured_data):
    unused = guard.doctor.parent / "unused-state"
    guard.env["STORAGE_STATE_DIR"] = str(unused)
    if configured_data:
        data = guard.doctor.parent / "data"
        data.mkdir()
        (guard.stub / "state-mount").write_text("/mnt/data")
        guard.env["STORAGE_DATA_DIR"] = str(data)
        state = data / "storage-guard"
    else:
        state = guard.doctor / ".storage-guard"
    guard.fs({"/": 86})
    guard.run()
    assert len(guard.alerts()) == 1
    assert len(list(state.glob("*.ack"))) == 1
    assert (state / "_").is_file()
    assert not unused.exists()


def test_enospc_keeps_original_alerts_and_retries_before_discovery(guard):
    data = guard.doctor.parent / "data"
    data.mkdir()
    (guard.stub / "state-mount").write_text("/mnt/data")
    guard.env["STORAGE_DATA_DIR"] = str(data)
    state = data / "storage-guard"
    guard.fs({"/": 86, "/home": 86})
    (guard.stub / "delivery").write_text("enospc")
    result = guard.run(check=False)
    assert result.returncode != 0 and "No space left on device" in result.stderr
    saved = {p.name: p.read_bytes() for p in state.glob("*.pending")}
    ids = guard._lines("attempts")
    assert len(saved) == len(ids) == 2
    assert not (guard.doctor / ".storage-guard").exists()
    assert (state / "storage-guard.log").is_file()
    assert not list(state.glob("*.ack"))

    guard.fs({"/": 50, "/home": 50})
    (guard.stub / "events").write_text("")
    result = guard.run(check=False)
    assert result.returncode != 0
    assert {p.name: p.read_bytes() for p in state.glob("*.pending")} == saved
    assert guard._lines("attempts") == ids * 2
    assert [line.split()[0] for line in guard._lines("events")[:3]] == [
        "notify", "notify", "discovery"
    ]
    assert guard._lines("broadcasts") == ["broadcast", "broadcast"]

    (guard.stub / "delivery").unlink()
    guard.run()
    assert not list(state.glob("*.pending"))
    assert len(list(state.glob("*.ack"))) == 2
    assert guard._lines("attempts") == ids * 3
    assert {json.loads(p.read_text().splitlines()[1])["request_id"] for p in state.glob("*.ack")} == set(ids)
    guard.run()
    assert guard._lines("attempts") == ids * 3
    assert all("86% used" in a for a in guard.alerts())


@pytest.mark.parametrize("receipt", [
    "",
    "queued",
    '{"schema":"fm-inbox-note.v1","request_id":"wrong","saved":true,"announced":true}',
    '{"schema":"fm-inbox-note.v1","saved":false,"announced":true}',
])
def test_exit_zero_without_a_matching_receipt_keeps_pending(guard, receipt):
    Guard._exe(guard.home / "bin/fm-inbox.sh", f"printf '%s\\n' '{receipt}'")
    guard.fs({"/": 86})
    result = guard.run(check=False)
    assert result.returncode != 0
    state = guard.doctor / ".storage-guard"
    assert len(list(state.glob("*.pending"))) == 1
    assert not list(state.glob("*.ack"))
    assert "delivery pending" in result.stderr


def test_saved_but_unannounced_receipt_retries_the_same_request(guard):
    (guard.stub / "delivery").write_text("uncertain")
    guard.fs({"/": 86})
    assert guard.run(check=False).returncode != 0
    (guard.stub / "delivery").unlink()
    guard.run()
    first, retry = guard._lines("attempts")
    assert first == retry
    state = guard.doctor / ".storage-guard"
    assert not list(state.glob("*.pending"))
    receipt = json.loads(next(state.glob("*.ack")).read_text().splitlines()[1])
    assert receipt["saved"] and receipt["announced"]


def test_lost_sample_does_not_duplicate_successful_delivery(guard):
    guard.fs({"/": 86})
    guard.run()
    (guard.doctor / ".storage-guard/_").write_text("0 0 0 0 0 0\n")
    guard.run()
    assert len(guard._lines("attempts")) == 1
    assert not list((guard.doctor / ".storage-guard").glob("*.pending"))


@pytest.mark.parametrize("directory_exists", [False, True])
def test_missing_configured_data_mount_never_writes_root_backed_state(guard, directory_exists):
    data = guard.doctor.parent / "data"
    if directory_exists:
        data.mkdir()
    (guard.stub / "state-mount").write_text("/")
    Guard._exe(guard.stub / "bin/wall", 'cat > "$STUB/wall"')
    result = guard.run(STORAGE_DATA_DIR=str(data), check=False)
    assert result.returncode != 0
    assert "configured data mount unavailable" in result.stderr
    assert not (data / "storage-guard").exists()
    assert not (guard.doctor / ".storage-guard").exists()
    assert guard._lines("events") == []


def test_dry_run_does_not_retry_or_change_pending_alerts(guard):
    guard.fs({"/": 86})
    (guard.stub / "delivery").write_text("enospc")
    guard.run(check=False)
    state = guard.doctor / ".storage-guard"
    before = {p.name: p.read_bytes() for p in state.iterdir()}
    attempts = guard._lines("attempts")
    guard.run("--dry-run")
    assert {p.name: p.read_bytes() for p in state.iterdir()} == before
    assert guard._lines("attempts") == attempts


def test_stalled_inbox_is_bounded_and_leaves_alerts_pending(guard):
    guard.fs({"/": 86, "/home": 86})
    (guard.stub / "delivery").write_text("timeout")
    start = time.monotonic()
    result = guard.run(check=False, STORAGE_NOTIFY_TIMEOUT="1")
    assert result.returncode != 0
    assert time.monotonic() - start < 10
    assert len(list((guard.doctor / ".storage-guard").glob("*.pending"))) == 2


def test_root_backed_bind_mount_is_not_durable_storage(guard):
    data = guard.doctor.parent / "data"
    data.mkdir()
    (guard.stub / "state-mount").write_text(str(data))
    (guard.stub / "state-device").write_text("0:1")
    Guard._exe(guard.stub / "bin/wall", 'cat > "$STUB/wall"')
    assert guard.run(STORAGE_DATA_DIR=str(data), check=False).returncode != 0
    assert not (data / "storage-guard").exists()


def test_failed_sample_commit_cannot_reuse_a_previous_episode_receipt(guard):
    Guard._exe(guard.stub / "bin/mv", r"""
if [[ "${!#}" == */.storage-guard/_ ]] && [ -f "$STUB/fail-sample" ]; then
  echo "sample commit failed" >&2
  exit 1
fi
exec /usr/bin/mv "$@"
""")
    (guard.stub / "fail-sample").touch()
    guard.fs({"/": 86})
    assert guard.run(check=False).returncode != 0
    assert len(guard.alerts()) == 1
    (guard.stub / "fail-sample").unlink()
    guard.fs({"/": 50})
    guard.run()
    guard.fs({"/": 88})
    guard.run()
    assert len(guard.alerts()) == 2
    first, second = guard._lines("attempts")
    assert first != second
    guard.run()
    assert len(guard.alerts()) == 2


def test_growth_after_reclaim_uses_the_reclaimed_usage_sample(guard):
    guard.fs({"/": 95})
    guard.free(builder=30)
    guard.run()
    assert guard.pct() == 65
    state = guard.doctor / ".storage-guard/_"
    fields = state.read_text().split()
    fields[0] = str(int(time.time()) - 600)
    state.write_text(" ".join(fields) + "\n")
    guard.fs({"/": 75})
    guard.run()
    assert len(guard.alerts()) == 2
    assert guard.alerts()[1].startswith("FILL / 75%")
