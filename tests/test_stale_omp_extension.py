"""scripts/stale_omp_extension.py: a firstmate omp session older than the extension file is reported."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_session_started_before_the_extension_was_installed(tmp_path):
    home = tmp_path / "home"
    (home / "bin").mkdir(parents=True)
    (home / "state/inbox").mkdir(parents=True)
    (home / "bin/fm-wake-drain.sh").write_text("")
    other = tmp_path / "other"  # same process name, not a firstmate home
    other.mkdir()
    fake = tmp_path / "omp"  # the process name comes from the executable path
    fake.symlink_to(shutil.which("python3"))
    procs = [subprocess.Popen(["python3", "-c", "import time; time.sleep(30)"], executable=str(fake), cwd=d) for d in (home, other)]
    ext = tmp_path / "fm-stranded-wake.ts"
    ext.write_text("")
    try:
        time.sleep(0.2)
        check = lambda: [  # real sessions on the host may show up too; look only at ours
            line
            for line in subprocess.run(
                [sys.executable, str(ROOT / "scripts/stale_omp_extension.py"), str(ext)], capture_output=True, text=True
            ).stdout.splitlines()
            if line.split("\t")[0] in {str(p.pid) for p in procs}
        ]
        earlier = time.time() - 10
        os.utime(ext, (earlier, earlier))
        assert check() == []  # extension older than the session: nothing stale
        later = time.time() + 5
        os.utime(ext, (later, later))  # extension written after the session started
        assert check() == [f"{procs[0].pid}\t{home}"]
    finally:
        for p in procs:
            p.kill()
            p.wait()
