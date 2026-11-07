"""scripts/stale_omp_extension.py: a firstmate omp session without a stranded-wake load marker is reported."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_session_without_a_load_marker_is_reported(tmp_path):
    home = tmp_path / "home"
    (home / "bin").mkdir(parents=True)
    (home / "state/inbox").mkdir(parents=True)
    (home / "bin/fm-wake-drain.sh").write_text("")
    other = tmp_path / "other"  # same process name, not a firstmate home
    other.mkdir()
    fake = tmp_path / "omp"  # the process name comes from the executable path
    fake.symlink_to(shutil.which("python3"))
    procs = [
        subprocess.Popen(
            ["python3", "-c", "import time; time.sleep(30)"], executable=str(fake), cwd=d
        )
        for d in (home, other)
    ]
    try:
        time.sleep(0.2)

        def check():  # real sessions on the host may show up too; look only at ours
            out = subprocess.run(
                [sys.executable, str(ROOT / "scripts/stale_omp_extension.py")],
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            return [line for line in out if line.split("\t")[0] in {str(p.pid) for p in procs}]

        assert check() == [f"{procs[0].pid}\t{home}"]
        marker = home / "state/.stranded-wake.loaded" / str(procs[0].pid)
        marker.parent.mkdir()
        marker.write_text(json.dumps({"pid": procs[0].pid, "at": int(time.time())}))
        assert check() == []  # loaded: nothing reported
        marker.write_text(json.dumps({"pid": procs[0].pid, "at": int(time.time()) - 3600}))
        assert check() == [f"{procs[0].pid}\t{home}"]  # marker predates the process: reused pid
    finally:
        for p in procs:
            p.kill()
            p.wait()
