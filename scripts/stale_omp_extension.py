#!/usr/bin/env python3
"""List running firstmate omp sessions that have not loaded the stranded-wake extension.

The extension writes state/.stranded-wake.loaded/<pid> at session start. omp loads extensions
only at process start, so a session without a marker written after it started is stale or
failed to load it. A marker older than its process belongs to a dead session with a reused pid.
Usage: stale_omp_extension.py   (prints "pid<TAB>home" per such session)
"""

import json
import os
from pathlib import Path


def boot_time() -> float:
    for line in Path("/proc/stat").read_text().splitlines():
        if line.startswith("btime "):
            return float(line.split()[1])
    raise RuntimeError("no btime in /proc/stat")


def started_at(pid_dir: Path, btime: float) -> float:
    # field 22 of /proc/PID/stat; split after the ")" that ends the command name
    fields = (pid_dir / "stat").read_text().rpartition(")")[2].split()
    return btime + int(fields[19]) / os.sysconf("SC_CLK_TCK")


def loaded(marker: Path, started: float) -> bool:
    try:
        return json.loads(marker.read_text())["at"] >= int(started) - 1
    except (OSError, ValueError, KeyError, TypeError):
        return False


def missing_marker() -> list[tuple[int, str]]:
    btime = boot_time()
    found = []
    for pid_dir in Path("/proc").glob("[0-9]*"):
        try:
            if (pid_dir / "comm").read_text().strip() != "omp":
                continue
            home = os.readlink(pid_dir / "cwd")
            if not (Path(home, "bin/fm-wake-drain.sh").exists() and Path(home, "state/inbox").is_dir()):
                continue
            if not loaded(Path(home, "state/.stranded-wake.loaded", pid_dir.name), started_at(pid_dir, btime)):
                found.append((int(pid_dir.name), home))
        except OSError:
            continue  # process exited or is not ours
    return found


if __name__ == "__main__":
    for pid, home in missing_marker():
        print(f"{pid}\t{home}")
