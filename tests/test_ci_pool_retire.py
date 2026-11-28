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
    (wants / "ci-runner@broken.service").symlink_to(units / "ci-runner@.service")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    states = tmp_path / "states"
    states.write_text(
        "ci-pool-watch.service inactive\nci-pool-watch.timer active\n"
        "ci-runner@acme.service active\nci-runner@broken.service failed\n"
    )
    stub = bin_dir / "systemctl"
    stub.write_text(
        """#!/bin/sh
states=%(states)s
if [ "$2" = list-units ]; then
  want=",${5#--state=},"
  shift 5
  while read -r name state; do
    for pat in "$@"; do
      case "$name" in $pat)
        case "$want" in *",$state,"*) echo "$name" ;; esac ;;
      esac
    done
  done < "$states"
  exit 0
fi
if [ "$2" = disable ]; then
  # A timer fires once while it is being stopped; a service whose timer is still active restarts.
  fired=""
  case "$4" in
  *.timer) fired="${4%%.timer}.service" ;;
  *.service) grep -qx "${4%%.service}.timer active" "$states" && fired="$4" ;;
  esac
  while read -r name state; do
    if [ "$name" = "$4" ] && [ "$state" != failed ]; then state=inactive; fi
    if [ "$name" = "$fired" ]; then state=active; fi
    echo "$name $state"
  done < "$states" > "$states.new"
  mv "$states.new" "$states"
  rm -f %(wants)s/"$4"
  exit 0
fi
if [ "$2" = reset-failed ]; then
  while read -r name state; do
    if [ "$name" = "$3" ] && [ "$state" = failed ]; then state=inactive; fi
    echo "$name $state"
  done < "$states" > "$states.new"
  mv "$states.new" "$states"
  exit 0
fi
exit 1
"""
        % {"states": states, "wants": wants}
    )
    stub.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    def run():
        return subprocess.run([SCRIPT], env=env, capture_output=True, text=True, check=True).stdout

    assert sorted(run().split()) == [
        "ci-pool-watch.service",
        "ci-pool-watch.timer",
        "ci-runner@acme.service",
        "ci-runner@broken.service",
    ]
    assert run() == ""
    assert (units / "ci-runner@.service").exists()
