"""runner-up recipe (docs/runner-up.md): the generated config, the caps, the scripts.

The task file runs against a throwaway home with no root and no real systemd or Docker.
The scripts run with stub `docker` and `sudo` commands.
"""

import getpass
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
MAINTENANCE = ROOT / "blueprint/maintenance"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ship = load("ship_runner_up", "scripts/ship.py")
pool_script = load("ci_pool_runner_up", "blueprint/maintenance/ci-pool.py")

# The shapes of a real CI pool list: one label, a reserved label beside the pool label, a named
# second group of one repository, a Docker-in-job entry, and several labels.
REPOS = [
    {"repo": "acme/web", "slots": 3, "labels": ["web"]},
    {"repo": "acme/engine", "slots": 2, "labels": ["engine"]},
    {"repo": "acme/engine", "name": "engine-quick", "slots": 1, "labels": ["engine-quick"]},
    {"repo": "acme/api", "slots": 1, "labels": ["linux", "api"]},
    {
        "repo": "acme/e2e.tests",
        "slots": 1,
        "labels": ["linux", "e2e"],
        "docker": "dind",
        "userns": True,
    },
    {"repo": "acme/mixed", "slots": 1, "labels": ["self-hosted", "Linux", "one", "two"]},
]


@pytest.fixture
def home(tmp_path):
    """An account whose layout exists, as on a host the installer ran on: a copy from the
    checkout needs its parent directory even in check mode."""
    home = tmp_path / "home"
    for path in (
        ".local/bin",
        ".local/share/runner-up/shim",
        ".config/runner-up",
        ".config/systemd/user",
    ):
        (home / path).mkdir(parents=True)
    return home


def validator():
    """The real check-config when runner-up is installed; otherwise one that accepts any file."""
    program = shutil.which("runner-up") or str(Path.home() / ".local/bin/runner-up")
    return f"{program} check-config --config %s" if os.access(program, os.X_OK) else "true %s"


def apply(home, runner_up, *flags, ci_pool=None, facts=None, start_services=False):
    playbook = home.parent / "runner_up.yml"
    if not (home.parent / "templates").exists():
        (home.parent / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars_files": [
                        str(f)
                        for f in sorted((ROOT / "blueprint/ansible/group_vars/all").glob("*.yml"))
                    ],
                    "tasks": [
                        {
                            "ansible.builtin.import_tasks": str(
                                ROOT / "blueprint/ansible/tasks/runner_up.yml"
                            )
                        }
                    ],
                    "handlers": [
                        {
                            "name": "user",
                            "ansible.builtin.debug": {"msg": "x"},
                            "listen": "reload user systemd",
                        },
                        {
                            "name": "system",
                            "ansible.builtin.debug": {"msg": "x"},
                            "listen": "reload system systemd",
                        },
                    ],
                }
            ]
        )
    )
    crewship = {
        "user": getpass.getuser(),
        "home": str(home),
        "start_services": start_services,
        "runner_up": runner_up,
    }
    if ci_pool:
        crewship["ci_pool"] = ci_pool
    variables = {
        "ansible_become": False,
        "crewship_repo": str(ROOT),
        "crewship_blueprint": str(ROOT / "blueprint"),
        "crewship_become_target": False,
        "crewship_runner_up_slice_dir": str(home.parent / "etc"),
        "crewship_runner_up_check": validator(),
        "ansible_facts": facts or {},
        "crewship": crewship,
    }
    (home.parent / "etc").mkdir(exist_ok=True)
    result = subprocess.run(
        [
            Path(sys.executable).parent / "ansible-playbook",
            "-i",
            "localhost,",
            str(playbook),
            "--extra-vars",
            json.dumps(variables),
            *flags,
        ],
        cwd=home.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return int(result.stdout.rsplit("changed=", 1)[1].split()[0])


def config(home):
    return json.loads((home / ".config/runner-up/config.json").read_text())


def units(home):
    return home / ".config/systemd/user"


def pool(home, **extra):
    data_dir = home.parent / "data"
    data_dir.mkdir(exist_ok=True)
    return {
        "data_dir": str(data_dir),
        "total_slots": 6,
        "job_cpus": 4,
        "job_memory_gb": 8,
        "repos": REPOS,
        **extra,
    }


def test_config_maps_every_ci_pool_entry_to_places_and_pools_and_leaves_dind_out(home):
    apply(home, {}, ci_pool=pool(home))
    cfg = config(home)
    assert cfg["github"]["repos"] == ["acme/web", "acme/engine", "acme/api", "acme/mixed"]
    # A reserved label is no pool: runner-up refuses it, and every self-hosted runner has it.
    assert [p["label"] for p in cfg["pools"]] == [
        "web",
        "engine",
        "engine-quick",
        "api",
        "one",
        "two",
    ]
    places = {p["id"]: p for p in cfg["machines"][0]["places"]}
    assert sorted(places) == [
        "acme-api-1",
        "acme-engine-1",
        "acme-engine-2",
        "acme-mixed-1",
        "acme-web-1",
        "acme-web-2",
        "acme-web-3",
        "engine-quick-1",
    ]
    # A named group keeps places of its own, so quick jobs never wait behind the long ones.
    assert places["engine-quick-1"]["pools"] == ["engine-quick"]
    assert places["acme-engine-1"]["pools"] == ["engine"]
    assert places["acme-mixed-1"]["pools"] == ["one", "two"]
    assert {p["provider"] for p in places.values()} == {"docker"}
    assert {(p["cores"], p["memoryMB"]) for p in places.values()} == {(4, 8192)}
    assert not any("e2e" in json.dumps(v) for v in (cfg["pools"], places))


def test_the_machine_budget_holds_total_slots_jobs_and_logs_are_kept_for_a_week(home):
    apply(home, {}, ci_pool=pool(home))
    cfg = config(home)
    assert cfg["machines"][0]["cores"] == 6 * 4
    assert cfg["machines"][0]["memoryMB"] == 6 * 8192
    assert cfg["logKeepDays"] == 7
    assert cfg["stateDir"] == f"{home.parent}/data/runner-up"


def test_auto_slots_take_half_of_the_host_like_the_ci_pool(home):
    auto = {key: value for key, value in pool(home).items() if key != "total_slots"}
    apply(home, {}, ci_pool=auto, facts={"processor_vcpus": 96, "memtotal_mb": 250 * 1024})
    machine = config(home)["machines"][0]
    assert (
        machine["cores"] == pool_script.auto_slots({"job_cpus": 4, "job_memory_gb": 8}, 96, 250) * 4
    )


def test_runner_up_repos_replace_the_ci_pool_list_and_need_no_ci_pool(home):
    apply(home, {"repos": [{"repo": "acme/solo", "slots": 2, "labels": ["solo"]}]})
    cfg = config(home)
    assert cfg["github"]["repos"] == ["acme/solo"]
    assert [p["id"] for p in cfg["machines"][0]["places"]] == ["acme-solo-1", "acme-solo-2"]


def test_another_machine_joins_with_a_hard_budget_and_serves_every_pool(home):
    machine = {
        "name": "laptop",
        "ssh": ["ci@laptop"],
        "slots": 1,
        "job_cpus": 2,
        "job_memory_gb": 4,
        "cores": 2,
        "memory_gb": 4,
        "agent": "/opt/agent",
    }
    apply(home, {"machines": [machine]}, ci_pool=pool(home))
    cfg = config(home)
    laptop = cfg["machines"][1]
    assert (laptop["name"], laptop["ssh"], laptop["agent"]) == (
        "laptop",
        ["ci@laptop"],
        "/opt/agent",
    )
    assert (laptop["cores"], laptop["memoryMB"]) == (2, 4096)
    (place,) = laptop["places"]
    assert (place["cores"], place["memoryMB"]) == (2, 4096)
    assert place["pools"] == [p["label"] for p in cfg["pools"]]
    assert "image" not in place  # runner-up's own pinned runner image


def unit_sections(path):
    sections, current = {}, None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
        else:
            key, _, value = line.partition("=")
            current.setdefault(key, []).append(value)
    return sections


def test_the_slice_and_the_units_carry_the_caps(home):
    apply(home, {"cpu_weight": 15, "memory_max": "30%"}, ci_pool=pool(home))
    slice_ = unit_sections(home.parent / "etc/runnerup.slice")["Slice"]
    assert slice_["CPUWeight"] == ["15"]
    assert slice_["IOWeight"] == ["20"]
    assert slice_["MemoryMax"] == ["30%"]
    service = unit_sections(units(home) / "runner-up.service")["Service"]
    assert service["Nice"] == ["10"]
    assert service["KillMode"] == ["process"]  # stopping the coordinator leaves running jobs alone
    assert any(
        v.startswith(f"PATH={home}/.local/share/runner-up/shim:") for v in service["Environment"]
    )
    assert any("image --ensure" in v for v in service["ExecStartPre"])
    clean = unit_sections(units(home) / "runner-up-clean.service")["Service"]
    assert "RUNNER_UP_DISK_MAX_GB=50" in clean["Environment"]
    assert clean["IOSchedulingClass"] == ["idle"]
    assert (units(home) / "timers.target.wants/runner-up-clean.timer").is_symlink()
    assert (units(home) / "default.target.wants/runner-up.service").is_symlink()


def test_the_image_timer_runs_only_when_the_ci_pool_does_not_build_the_image(home):
    apply(home, {}, ci_pool=pool(home))
    assert not (units(home) / "runner-up-image.timer").exists()
    apply(home, {"repos": [{"repo": "acme/solo", "slots": 1, "labels": ["solo"]}]}, ci_pool=None)
    assert (units(home) / "runner-up-image.timer").exists()
    assert (units(home) / "timers.target.wants/runner-up-image.timer").is_symlink()
    apply(home, {}, ci_pool=pool(home))
    assert not (units(home) / "runner-up-image.timer").exists()
    assert not (units(home) / "timers.target.wants/runner-up-image.timer").exists()


def test_a_second_apply_changes_nothing_and_check_mode_writes_nothing(home):
    assert apply(home, {}, "--check", ci_pool=pool(home)) > 0
    assert not (home / ".config/runner-up/config.json").exists()
    assert apply(home, {}, ci_pool=pool(home)) > 0
    assert apply(home, {}, ci_pool=pool(home)) == 0


def test_the_job_image_recipe_is_the_ci_pools_image(home):
    assert (
        ROOT / "blueprint/containers/ci-runner.Dockerfile"
    ).read_text() == pool_script.DOCKERFILE


def test_reserved_labels_match_the_validator_and_the_template(home):
    variables = yaml.safe_load(
        (ROOT / "blueprint/ansible/group_vars/all/runner_up.yml").read_text()
    )
    assert tuple(variables["crewship_runner_up_reserved_labels"]) == ship.RUNNER_UP_RESERVED_LABELS


# --- ship.py checks ---------------------------------------------------------


POOL_DOC = {"data_dir": "/data/ci", "repos": REPOS}


def document(**extra):
    base = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    base["crewship"]["profiles"]["docker"] = True
    base["crewship"].update(extra)
    return base


def test_inspect_accepts_the_ci_pool_list_and_refuses_a_pool_without_its_own_label():
    ship.validate_config(document(ci_pool=POOL_DOC, runner_up={}))
    bad = [{"repo": "acme/web", "slots": 1, "labels": ["linux", "self-hosted"]}]
    with pytest.raises(ValueError, match="needs a label besides"):
        ship.validate_config(document(runner_up={"repos": bad}))
    only_dind = {**POOL_DOC, "repos": [REPOS[4]]}
    with pytest.raises(ValueError, match="runner_up needs repos"):
        ship.validate_config(document(ci_pool=only_dind, runner_up={}))


@pytest.mark.parametrize(
    "block",
    [
        {"repos": [{**REPOS[0], "docker": "dind"}]},
        {"machines": [{"name": "laptop", "ssh": ["ci@laptop"]}]},
        {"memory_max": "lots"},
    ],
)
def test_the_schema_refuses_dind_a_machine_without_a_budget_and_a_bad_memory_cap(block):
    with pytest.raises(ValueError, match="invalid crewship.runner_up"):
        ship.validate_document(document(runner_up=block), "crewship.schema.json")


# --- scripts ----------------------------------------------------------------


@pytest.fixture
def stubs(tmp_path):
    """A `docker` and a `sudo` that record their arguments; `docker image inspect` fails
    unless the file `image` exists."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls"
    for name in ("docker", "sudo"):
        stub = bin_dir / name
        stub.write_text(
            "#!/bin/sh\n"
            f'echo "{name} $*" >> {log}\n'
            '[ "$1 $2" = "image inspect" ] && [ ! -e "$IMAGE_EXISTS" ] && exit 1\n'
            "exit 0\n"
        )
        stub.chmod(0o755)
    return bin_dir, log


def run_script(script, stubs, *args, env=None, **kwargs):
    bin_dir, log = stubs
    environment = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "RUNNER_UP_DOCKER": str(bin_dir / "docker"),
        "XDG_RUNTIME_DIR": str(log.parent),
        **(env or {}),
    }
    done = subprocess.run(
        [str(MAINTENANCE / script), *args],
        env=environment,
        capture_output=True,
        text=True,
        **kwargs,
    )
    assert done.returncode == 0, done.stderr
    return log.read_text().splitlines() if log.exists() else []


def test_the_shim_puts_jobs_and_builds_in_the_slice_and_limits_job_processes(stubs, tmp_path):
    sock = tmp_path / "docker.sock"
    sock.touch()
    env = {"RUNNER_UP_DOCKER_SOCK": str(sock), "RUNNER_UP_SLICE": "runnerup.slice"}
    calls = run_script("runner-up-docker", stubs, "run", "--rm", "-i", "img", env=env)
    assert calls == ["docker run --cgroup-parent runnerup.slice --pids-limit 8192 --rm -i img"]
    calls = run_script("runner-up-docker", stubs, "build", "--tag", "t", "-", env=env)
    assert calls[-1] == "docker build --cgroup-parent runnerup.slice --tag t -"
    calls = run_script("runner-up-docker", stubs, "ps", "-a", env=env)
    assert calls[-1] == "docker ps -a"
    assert "sudo" not in "".join(calls)


def test_the_shim_uses_sudo_when_the_account_cannot_write_the_docker_socket(stubs, tmp_path):
    env = {"RUNNER_UP_DOCKER_SOCK": str(tmp_path / "missing.sock")}
    calls = run_script("runner-up-docker", stubs, "run", "img", env=env)
    assert calls[0].startswith("sudo -n ")
    assert " run --cgroup-parent runnerup.slice " in calls[0]


def test_clean_removes_stopped_place_containers_and_layers_and_caps_the_build_cache(stubs):
    calls = run_script("runner-up-maintain", stubs, "clean", env={"RUNNER_UP_DISK_MAX_GB": "7"})
    assert calls == [
        "docker container prune --force --filter label=runner-up.place --filter until=1h",
        "docker image prune --force",
        "docker builder prune --force --reserved-space 7GB",
    ]


def test_the_image_is_built_with_the_build_output_removed_and_old_layers_pruned(stubs, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM scratch\n")
    env = {"RUNNER_UP_DOCKERFILE": str(dockerfile), "IMAGE_EXISTS": str(tmp_path / "image")}
    calls = run_script("runner-up-maintain", stubs, "image", "--ensure", env=env)
    (build,) = [c for c in calls if c.startswith("docker build")]
    for flag in ("--pull", "--rm", "--force-rm", "--tag crewship-ci-runner:latest"):
        assert flag in build
    assert calls[-1] == "docker image prune --force"


def test_ensure_builds_nothing_while_the_image_exists_and_a_plain_image_run_always_builds(
    stubs, tmp_path
):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM scratch\n")
    present = tmp_path / "image"
    present.touch()
    env = {"RUNNER_UP_DOCKERFILE": str(dockerfile), "IMAGE_EXISTS": str(present)}
    calls = run_script("runner-up-maintain", stubs, "image", "--ensure", env=env)
    assert calls == ["docker image inspect crewship-ci-runner:latest"]
    calls = run_script("runner-up-maintain", stubs, "image", env=env)
    assert any(c.startswith("docker build") for c in calls[1:])
