#!/usr/bin/env python3
"""List running firstmate omp sessions that started before an extension file was written.

omp loads extensions only at process start, so such a session runs without the extension.
Usage: stale_omp_extension.py EXTENSION_FILE   (prints "pid<TAB>home" per stale session)
"""

import os
import sys
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


def stale(extension: Path) -> list[tuple[int, str]]:
    written = extension.stat().st_mtime
    btime = boot_time()
    found = []
    for pid_dir in Path("/proc").glob("[0-9]*"):
        try:
            if (pid_dir / "comm").read_text().strip() != "omp":
                continue
            home = os.readlink(pid_dir / "cwd")
            if not (Path(home, "bin/fm-wake-drain.sh").exists() and Path(home, "state/inbox").is_dir()):
                continue
            if started_at(pid_dir, btime) < written:
                found.append((int(pid_dir.name), home))
        except OSError:
            continue  # process exited or is not ours
    return found


if __name__ == "__main__":
    for pid, home in stale(Path(sys.argv[1])):
        print(f"{pid}\t{home}")
