import configparser
import json
import os
import subprocess
import sys
from pathlib import Path


def dind_pools(config, image):
    for machine in config["machines"]:
        if machine["name"] == "local":
            places = [p for p in machine["places"] if p.get("image") == image]
            if places:
                return config["github"]["repos"], config["stateDir"], {**machine, "places": places}
    return None


def slice_limits(text):
    unit = configparser.ConfigParser(interpolation=None)
    unit.read_string(text)
    return dict(unit["Slice"])


def output(*command):
    return subprocess.check_output(command, text=True).strip()


def in_use(instances, units):
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    for instance in instances:
        unit = f"runner-up@{instance}.service"
        if any(p.is_symlink() for target in ("wants", "requires")
               for p in units.glob(f"*.{target}/{unit}")):
            return True
        if runtime and any((Path(runtime) / p).exists() for p in ("bus", "systemd/private")):
            states = output(
                "systemctl", "--user", "show", "--value",
                "-p", "ActiveState", "-p", "UnitFileState", unit,
            ).splitlines()
            if set(states) & {
                "active", "activating", "reloading", "deactivating", "refreshing",
                "enabled", "enabled-runtime",
            }:
                return True
    socket = Path(os.environ.get("RUNNER_UP_DOCKER_SOCK", "/var/run/docker.sock"))
    if not instances and not socket.exists():
        return False
    docker = [os.environ.get("RUNNER_UP_DOCKER", "/usr/bin/docker")]
    if not os.access(socket, os.W_OK):
        docker[:0] = ["sudo", "-n"]
    networks = output(*docker, "ps", "--format", "{{.Networks}}")
    return any(n.strip().startswith("runner-up-dind-") for n in networks.replace("\n", ",").split(","))


def main():
    config_dir, units, slice_file, tag_file = map(Path, sys.argv[1:5])
    if not tag_file.is_file():
        return
    installed_image = tag_file.read_text().strip()
    installed = {}
    for path in config_dir.glob("*.json"):
        pools = dind_pools(json.loads(path.read_text()), installed_image)
        if pools:
            installed[path.stem] = pools
    request = json.load(sys.stdin)
    desired = {
        name: dind_pools(json.loads(config) if isinstance(config, str) else config, sys.argv[5])
        for name, config in request["configs"].items()
    }
    desired = {name: pools for name, pools in desired.items() if pools}
    if (
        installed and installed == desired and slice_file.is_file()
        and slice_limits(slice_file.read_text()) == slice_limits(request["slice"])
    ):
        return
    if in_use(installed, units):
        sys.exit(
            "runner-up: Stop all Docker-in-Docker places and stop and disable their coordinators "
            "before changing pools, storage, or slice limits."
        )


if __name__ == "__main__":
    main()
