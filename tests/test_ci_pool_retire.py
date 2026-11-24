import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "blueprint/maintenance/ci-pool-retire.sh"


def test_retire_stops_the_old_units_once_and_leaves_their_files(tmp_path):
    units = tmp_path / ".config/systemd/user"
    wants = units / "default.target.wants"
    wants.mkdir(parents=True)
    (units / "ci-runner@.service").write_text("[Service]\n")
    (wants / "ci-runner@acme.service").symlink_to(units / "ci-runner@.service")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    active = tmp_path / "active"
    active.write_text("ci-pool-watch.timer\nci-runner@acme.service\n")
    stub = bin_dir / "systemctl"
    stub.write_text(
        f"""#!/bin/sh
if [ "$2" = list-units ]; then cat {active}; exit 0; fi
if [ "$2" = disable ]; then
  grep -vx "$4" {active} > {active}.new; mv {active}.new {active}
  rm -f {wants}/"$4"; exit 0
fi
exit 1
"""
    )
    stub.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    def run():
        return subprocess.run([SCRIPT], env=env, capture_output=True, text=True, check=True).stdout

    assert run().split() == ["ci-pool-watch.timer", "ci-runner@acme.service"]
    assert run() == ""
    assert (units / "ci-runner@.service").exists()
