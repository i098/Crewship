#!/usr/bin/env python3
"""List running firstmate omp sessions that have not loaded the stranded-wake extension.

The extension writes state/.stranded-wake.loaded/<pid> at session start. omp loads extensions
only at process start, so a session without that marker is stale or failed to load it.
Usage: stale_omp_extension.py   (prints "pid<TAB>home" per such session)
"""

import os
from pathlib import Path


def missing_marker() -> list[tuple[int, str]]:
    found = []
    for pid_dir in Path("/proc").glob("[0-9]*"):
        try:
            if (pid_dir / "comm").read_text().strip() != "omp":
                continue
            home = os.readlink(pid_dir / "cwd")
            if not (Path(home, "bin/fm-wake-drain.sh").exists() and Path(home, "state/inbox").is_dir()):
                continue
            if not Path(home, "state/.stranded-wake.loaded", pid_dir.name).is_file():
                found.append((int(pid_dir.name), home))
        except OSError:
            continue  # process exited or is not ours
    return found


if __name__ == "__main__":
    for pid, home in missing_marker():
        print(f"{pid}\t{home}")
