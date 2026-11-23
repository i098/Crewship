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
import time
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

# The shapes of a real repository list: one label, a reserved label beside the pool label, a named
# second group of one repository, and several labels.
REPOS = [
    {"repo": "acme/web", "slots": 3, "labels": ["web"]},
    {"repo": "acme/engine", "slots": 2, "labels": ["engine"]},
    {"repo": "acme/engine", "name": "engine-quick", "slots": 1, "labels": ["engine-quick"]},
    {"repo": "acme/api", "slots": 1, "labels": ["linux", "api"]},
    {"repo": "acme/mixed", "slots": 1, "labels": ["self-hosted", "Linux", "one", "two"]},
]
# A CI pool entry with the legacy AppArmor switch.
DIND = {
    "repo": "acme/e2e.tests",
    "slots": 1,
    "labels": ["linux", "e2e"],
    "docker": "dind",
    "userns": True,
}


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


def apply(home, runner_up, *flags, ci_pool=None, facts=None, docker_stub=None):
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
        "start_services": docker_stub is not None,
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
    environment = os.environ.copy()
    if facts and facts.get("distribution_version") == "24.04":
        device = home.parent / "test-block-device"
        runner_up.setdefault("io_write_device", str(device))
        lsblk = home / ".local/bin/lsblk"
        lsblk.write_text(
            f'#!/bin/sh\n[ "$5" = {json.dumps(str(device))} ] || exit 1\n'
            f'exec findmnt -rn -o MAJ:MIN -T {json.dumps(str(home))}\n'
        )
        lsblk.chmod(0o755)
        environment["PATH"] = f'{lsblk.parent}:{environment["PATH"]}'
    socket = home.parent / ("docker.sock" if docker_stub else "no-docker.sock")
    environment["RUNNER_UP_DOCKER_SOCK"] = str(socket)
    if docker_stub:
        socket.touch()
        bin_dir, log = docker_stub
        shutil.copy2(bin_dir / "cat", home / ".local/share/runner-up/shim/cat")
        systemctl = home / ".local/bin/systemctl"
        systemctl.write_text(
            '#!/bin/sh\n'
            f'case " $* " in *" daemon-reload "*) printf "systemctl %s\\n" "$*" >> "{log}";; esac\n'
            'case " $* " in *" show "*) printf "%s\\n" '
            'LoadState=loaded ActiveState=active UnitFileState=enabled;; esac\nexit 0\n'
        )
        systemctl.chmod(0o755)
        variables["crewship_user_runtime_dir"] = str(home.parent)
        environment.update(
            RUNNER_UP_DOCKER=str(bin_dir / "docker"),
            IMAGES=str(home.parent / "images"),
            DOCKER_CGROUP_DRIVER="systemd",
        )
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
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return int(result.stdout.rsplit("changed=", 1)[1].split()[0])


def config(home, instance="acme-web"):
    """The setup of one repository's coordinator (runner-up@<instance>)."""
    return json.loads((home / f".config/runner-up/{instance}.json").read_text())


def instances(home):
    return sorted(p.stem for p in (home / ".config/runner-up").glob("*.json"))


def units(home):
    return home / ".config/systemd/user"


def runner(home, **extra):
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


def test_config_maps_every_entry_to_its_repositorys_places_and_pools(home):
    apply(home, runner(home))
    # One coordinator for each repository.
    assert instances(home) == ["acme-api", "acme-engine", "acme-mixed", "acme-web"]
    places = {}
    for instance, repo, pools in (
        ("acme-web", "acme/web", ["web"]),
        ("acme-engine", "acme/engine", ["engine", "engine-quick"]),
        # A reserved label is no pool: runner-up refuses it, and every self-hosted runner has it.
        ("acme-api", "acme/api", ["api"]),
        ("acme-mixed", "acme/mixed", ["one", "two"]),
    ):
        cfg = config(home, instance)
        assert cfg["github"]["repos"] == [repo]
        # No other repository's label: a pool is global to its coordinator and opens a scale set
        # in every repository the coordinator serves.
        assert [p["label"] for p in cfg["pools"]] == pools
        assert [m["name"] for m in cfg["machines"]] == ["local"]
        places.update({p["id"]: p for p in cfg["machines"][0]["places"]})
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


def test_total_slots_is_split_across_coordinators_by_their_slots_and_logs_are_kept_for_a_week(home):
    apply(home, runner(home))
    cfg = config(home)
    # 6 total slots over 3+3+1+1 repository slots: web 6*3//8=2, engine 2, api and mixed 6//8=0 raised to 1.
    shares = {
        name: (
            config(home, name)["machines"][0]["cores"],
            config(home, name)["machines"][0]["memoryMB"],
        )
        for name in instances(home)
    }
    assert shares == {
        "acme-web": (2 * 4, 2 * 8192),
        "acme-engine": (2 * 4, 2 * 8192),
        "acme-api": (1 * 4, 1 * 8192),
        "acme-mixed": (1 * 4, 1 * 8192),
    }
    assert cfg["logKeepDays"] == 7
    # Each coordinator keeps its own state, so two never share a session file.
    assert cfg["stateDir"] == f"{home.parent}/data/runner-up/acme-web"
    assert config(home, "acme-api")["stateDir"] == f"{home.parent}/data/runner-up/acme-api"


def test_the_single_coordinator_of_the_earlier_layout_is_removed(home):
    (units(home) / "default.target.wants").mkdir()
    old = [
        units(home) / "runner-up.service",
        units(home) / "default.target.wants/runner-up.service",
        home / ".config/runner-up/config.json",
    ]
    for path in old:
        path.write_text("{}")
    apply(home, runner(home))
    assert not any(p.exists() or p.is_symlink() for p in old)
    assert instances(home) == ["acme-api", "acme-engine", "acme-mixed", "acme-web"]


def test_two_repositories_with_one_instance_name_write_nothing(home):
    repos = [
        {"repo": "a/b-c", "slots": 1, "labels": ["one"]},
        {"repo": "a-b/c", "slots": 1, "labels": ["two"]},
    ]
    with pytest.raises(AssertionError, match="one runner-up instance name"):
        apply(home, {"repos": repos})
    assert instances(home) == []


def test_auto_slots_take_half_of_the_host_like_the_ci_pool(home):
    auto = {key: value for key, value in runner(home).items() if key != "total_slots"}
    apply(home, auto, facts={"processor_vcpus": 96, "memtotal_mb": 250 * 1024})
    machine = config(home)["machines"][0]
    total = pool_script.auto_slots({"job_cpus": 4, "job_memory_gb": 8}, 96, 250)
    assert machine["cores"] == total * 3 // 8 * 4


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
    apply(home, runner(home, machines=[machine]))
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
    assert place["pools"] == ["web"]  # the pools of the coordinator it joins
    assert "image" not in place  # runner-up's own pinned runner image
    # A machine's budget is not shared between coordinators, so no other one lists it.
    assert [m["name"] for m in config(home, "acme-engine")["machines"]] == ["local"]


def test_a_machine_joins_the_repository_that_the_setup_names(home):
    machine = {
        "name": "laptop",
        "ssh": ["ci@laptop"],
        "job_cpus": 2,
        "job_memory_gb": 4,
        "cores": 2,
        "memory_gb": 4,
    }
    apply(home, runner(home, machines=[machine], machines_repo="acme/engine"))
    assert [m["name"] for m in config(home, "acme-web")["machines"]] == ["local"]
    laptop = config(home, "acme-engine")["machines"][1]
    assert laptop["places"][0]["pools"] == ["engine", "engine-quick"]


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
    apply(
        home,
        runner(home, cpu_weight=15, memory_max="30%", cpu_share=25),
        facts={"processor_vcpus": 8},
    )
    slice_ = unit_sections(home.parent / "etc/runnerup.slice")["Slice"]
    assert slice_["CPUWeight"] == ["15"]
    assert slice_["IOWeight"] == ["20"]
    assert slice_["MemoryMax"] == ["30%"]
    # A hard cap for every coordinator together: a quarter of 8 CPUs.
    assert slice_["CPUQuota"] == ["200%"]
    service = unit_sections(units(home) / "runner-up@.service")["Service"]
    assert any(
        v.endswith("serve --config " + str(home) + "/.config/runner-up/%i.json")
        for v in service["ExecStart"]
    )
    assert service["Nice"] == ["10"]
    assert service["KillMode"] == ["process"]  # stopping the coordinator leaves running jobs alone
    assert any(
        v.startswith(f"PATH={home}/.local/share/runner-up/shim:") for v in service["Environment"]
    )
    assert service["ExecStartPre"] == [
        f"{home}/.local/bin/runner-up-maintain start {home}/.config/runner-up/%i.json"
    ]
    clean = unit_sections(units(home) / "runner-up-clean.service")["Service"]
    assert "RUNNER_UP_DISK_MAX_GB=50" in clean["Environment"]
    assert clean["IOSchedulingClass"] == ["idle"]
    assert (units(home) / "timers.target.wants/runner-up-clean.timer").is_symlink()
    for instance in instances(home):
        assert (units(home) / f"default.target.wants/runner-up@{instance}.service").is_symlink()
    assert len(instances(home)) == 4


def test_the_slice_caps_writes_only_when_a_disk_is_named(home):
    path = home.parent / "etc/runnerup.slice"
    apply(home, runner(home))
    assert "IOWriteBandwidthMax" not in path.read_text()
    apply(home, runner(home, io_write_device="/dev/sdc"))
    slice_ = unit_sections(path)["Slice"]
    assert slice_["IOWriteBandwidthMax"] == ["/dev/sdc 120M"]
    assert slice_["IOWriteIOPSMax"] == ["/dev/sdc 600"]
    apply(home, runner(home, io_write_device="/dev/sdc", io_write_mb=200, io_write_iops=900))
    slice_ = unit_sections(path)["Slice"]
    assert slice_["IOWriteBandwidthMax"] == ["/dev/sdc 200M"]
    assert slice_["IOWriteIOPSMax"] == ["/dev/sdc 900"]


def test_the_image_timer_runs_only_when_the_ci_pool_does_not_build_the_image(home):
    ci_pool = {"data_dir": str(home.parent / "data"), "repos": [DIND]}
    apply(home, runner(home), ci_pool=ci_pool)
    assert not (home / ".local/share/runner-up/runner-up-dind.Dockerfile").exists()
    assert not (units(home) / "runner-up-image.timer").exists()
    apply(home, runner(home))
    assert (units(home) / "runner-up-image.timer").exists()
    assert (units(home) / "timers.target.wants/runner-up-image.timer").is_symlink()
    apply(home, runner(home), ci_pool=ci_pool)
    assert not (units(home) / "runner-up-image.timer").exists()
    assert not (units(home) / "timers.target.wants/runner-up-image.timer").exists()


def test_a_second_apply_changes_nothing_and_check_mode_writes_nothing(home):
    assert apply(home, runner(home), "--check") > 0
    assert not (home / ".config/runner-up/acme-web.json").exists()
    assert apply(home, runner(home)) > 0
    assert apply(home, runner(home)) == 0


def test_a_repository_that_leaves_the_list_loses_its_unit_and_config_and_the_others_stay(home):
    apply(home, runner(home))
    (home / ".config/runner-up/config.json").write_text("{}")  # the old single-coordinator file
    apply(home, runner(home, repos=[r for r in REPOS if r["repo"] != "acme/api"]))
    assert instances(home) == ["acme-engine", "acme-mixed", "acme-web"]
    wants = units(home) / "default.target.wants"
    assert not (wants / "runner-up@acme-api.service").exists()
    assert not (wants / "runner-up@config.service").exists()
    assert (wants / "runner-up@acme-web.service").is_symlink()


def test_github_default_and_runner_up_reserved_labels_do_not_make_pools(home):
    reserved = ["self-hosted", "Linux", "Windows", "macOS", "X64", "ARM64", "ARM", "X86"]
    repo = {"repo": "acme/web", "slots": 1}
    with pytest.raises(ValueError, match="needs a label besides"):
        ship.validate_config(document(runner_up={"repos": [{**repo, "labels": reserved}]}))
    with_pool = {**repo, "labels": [*reserved, "web"]}
    ship.validate_config(document(runner_up={"repos": [with_pool]}))
    apply(home, runner(home, repos=[with_pool]))
    cfg = config(home)
    assert [pool["label"] for pool in cfg["pools"]] == ["web"]
    assert cfg["machines"][0]["places"][0]["pools"] == ["web"]


# --- ship.py checks ---------------------------------------------------------


POOL_DOC = {"data_dir": "/data/ci", "repos": [*REPOS, DIND]}


def document(**extra):
    base = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    base["crewship"]["profiles"]["docker"] = True
    base["crewship"].update(extra)
    return base


def test_inspect_accepts_the_repos_and_refuses_a_pool_without_its_own_label():
    ship.validate_config(document(ci_pool=POOL_DOC, runner_up={"repos": REPOS}))
    bad = [{"repo": "acme/web", "slots": 1, "labels": ["linux", "self-hosted"]}]
    with pytest.raises(ValueError, match="needs a label besides"):
        ship.validate_config(document(runner_up={"repos": bad}))


def test_inspect_refuses_runner_up_without_repos_even_beside_a_ci_pool():
    with pytest.raises(ValueError, match="runner_up needs repos"):
        ship.validate_config(document(ci_pool=POOL_DOC, runner_up={}))


@pytest.mark.parametrize("custom_image", [False, True])
def test_dind_places_only_serve_their_pool_locally(home, custom_image, stubs):
    dind = {key: value for key, value in DIND.items() if key != "userns"}
    plain = {**dind, "repo": dind["repo"].upper(), "name": "plain", "labels": ["plain"]}
    del plain["docker"]
    machine = {"name": "laptop", "ssh": ["ci@laptop"], "cores": 2, "memory_gb": 8}
    settings = runner(
        home,
        repos=[plain, dind, REPOS[1]],
        machines=[machine],
        machines_repo="Acme/E2E.Tests",
        io_write_device=str(home.parent / "test-block-device"),
        io_write_mb=200,
        io_write_iops=500,
    )
    ship.validate_config(document(runner_up=settings))
    facts = {"distribution": "Ubuntu", "distribution_version": "24.04"}
    ci_pool = {"data_dir": str(home.parent / "data"), "repos": [DIND]}
    if custom_image:
        ci_pool["image"] = "acme/ci:latest"
    apply(home, settings, facts=facts, ci_pool=ci_pool, docker_stub=stubs)
    cfg = config(home, "acme-e2e-tests")
    assert cfg["github"]["repos"] == ["acme/e2e.tests"]
    assert instances(home) == ["acme-e2e-tests", "acme-engine"]
    local, remote = cfg["machines"]
    assert local["cores"] == 12
    by_pool = {place["pools"][0]: place["image"] for place in local["places"]}
    assert by_pool == {"e2e": "crewship-ci-runner-dind:latest", "plain": "crewship-ci-runner:latest"}
    assert remote["places"][0]["pools"] == ["plain"]
    directory = home / ".local/share/runner-up"
    service = unit_sections(units(home) / "runner-up@.service")["Service"]
    assert f"RUNNER_UP_DIND_DOCKERFILE={directory}/runner-up-dind.Dockerfile" in service["Environment"]
    assert f'"RUNNER_UP_GUARD_PATH={home.parent}/data"' in service["Environment"]
    assert (directory / "runner-up-dind.Dockerfile").is_file()
    assert (directory / "shim/dind-image").read_text().strip() == by_pool["e2e"]
    image_service = unit_sections(units(home) / "runner-up-image.service")["Service"]
    refresh = int(custom_image)
    assert f"RUNNER_UP_REFRESH_BASE={refresh}" in image_service["Environment"]
    limits = unit_sections(home.parent / "etc/runnerup.slice")["Slice"]
    assert limits["IOWriteBandwidthMax"] == [f'{settings["io_write_device"]} 200M']
    assert limits["IOWriteIOPSMax"] == [f'{settings["io_write_device"]} 500']
    assert apply(home, settings, facts=facts, ci_pool=ci_pool, docker_stub=stubs) == 0


def test_apply_refuses_dind_on_ubuntu_2604(home):
    dind = {key: value for key, value in DIND.items() if key != "userns"}
    facts = {"distribution": "Ubuntu", "distribution_version": "26.04"}
    with pytest.raises(AssertionError, match="Docker-in-Docker requires Ubuntu 24.04"):
        apply(home, runner(home, repos=[dind]), facts=facts)
    assert instances(home) == []


@pytest.mark.parametrize("settings", [{"data_dir": ""}, {"io_write_device": "/dev/null"}])
def test_apply_refuses_dind_without_data_on_the_capped_device(home, settings):
    dind = {key: value for key, value in DIND.items() if key != "userns"}
    facts = {"distribution": "Ubuntu", "distribution_version": "24.04"}
    with pytest.raises(AssertionError, match="data_dir must be on runner_up.io_write_device"):
        apply(home, runner(home, repos=[dind], **settings), facts=facts)
    assert instances(home) == []


def test_deferred_apply_does_not_publish_dind_configs(home, stubs):
    apply(home, runner(home))
    original = config(home)
    existing = {**REPOS[0], "repo": "ACME/Web", "docker": "dind", "labels": ["web-dind"]}
    new = {key: value for key, value in DIND.items() if key != "userns"}
    facts = {"distribution": "Ubuntu", "distribution_version": "24.04"}
    apply(home, runner(home, repos=[existing, new]), facts=facts)
    assert config(home) == original
    assert "acme-e2e-tests" not in instances(home)
    wants = units(home) / "default.target.wants"
    assert not (wants / "runner-up@acme-e2e-tests.service").exists()
    apply(home, runner(home, repos=[existing, new]), facts=facts)
    assert config(home) == original
    assert not (wants / "runner-up@acme-e2e-tests.service").exists()
    apply(home, runner(home, repos=[REPOS[1]]))
    assert "acme-web" not in instances(home)
    apply(home, runner(home, repos=[existing]), facts=facts)
    assert "acme-web" not in instances(home)
    assert not (wants / "runner-up@acme-web.service").exists()
    slice_file = home.parent / "etc/runnerup.slice"
    before = slice_file.stat().st_mtime_ns
    apply(home, runner(home, repos=[existing, new]), facts=facts, docker_stub=stubs)
    assert config(home)["pools"][0]["label"] == "web-dind"
    assert config(home, "acme-e2e-tests")["pools"][0]["label"] == "e2e"
    assert slice_file.stat().st_mtime_ns == before
    calls = stubs[1].read_text().splitlines()
    reload = calls.index("systemctl daemon-reload")
    assert reload < next(i for i, call in enumerate(calls) if call.startswith("docker image inspect "))
    for docker_stub in (None, stubs):
        settings = runner(home, repos=[REPOS[1]])
        with pytest.raises(AssertionError, match="Stop all Docker-in-Docker places"):
            apply(home, settings, docker_stub=docker_stub)
        assert slice_file.stat().st_mtime_ns == before
        assert stubs[1].read_text().splitlines() == calls
        assert config(home)["pools"][0]["label"] == "web-dind"


def test_inspect_and_direct_apply_reject_a_pool_shared_by_plain_and_dind_places(home):
    dind = {key: value for key, value in DIND.items() if key != "userns"}
    plain = {**dind, "name": "plain", "labels": ["E2E"]}
    del plain["docker"]
    with pytest.raises(ValueError, match="both plain and Docker-in-Docker"):
        ship.validate_config(document(runner_up={"repos": [dind, plain]}))
    with pytest.raises(AssertionError, match="both plain and Docker-in-Docker"):
        apply(home, runner(home, repos=[dind, plain]))
    assert instances(home) == []


@pytest.mark.parametrize("field", ["docker", "io_write_device", "io_write_mb", "io_write_iops"])
def test_direct_apply_rejects_invalid_docker_and_io_settings(home, field):
    settings = runner(home)
    if field == "docker":
        settings["repos"] = [{**REPOS[0], "docker": "DinD"}]
    else:
        settings[field] = "invalid"
    with pytest.raises(AssertionError, match="ValidationError"):
        apply(home, settings)
    assert instances(home) == []


@pytest.mark.parametrize(
    "block",
    [
        {"machines": [{"name": "laptop", "ssh": ["ci@laptop"]}]},
        {"memory_max": "lots"},
    ],
)
def test_the_schema_refuses_a_machine_without_a_budget_and_a_bad_memory_cap(block):
    with pytest.raises(ValueError, match="invalid crewship.runner_up"):
        ship.validate_document(document(runner_up=block), "crewship.schema.json")


# --- scripts ----------------------------------------------------------------


@pytest.fixture
def stubs(tmp_path):
    """Record Docker arguments and store each local image tag separately."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls"
    (tmp_path / "images").mkdir()
    shutil.copy2(MAINTENANCE / "runner-up-docker", bin_dir / "runner-up-docker")
    cat = bin_dir / "cat"
    cat.write_text(
        '#!/bin/sh\nif [ "$*" = /etc/os-release ]; then\n'
        '  printf "%s\\n" ID=ubuntu VERSION_ID=24.04\n'
        'else exec /bin/cat "$@"; fi\n'
    )
    cat.chmod(0o755)
    runtime = bin_dir / "sysbox-runc"
    runtime.write_text('#!/bin/sh\nprintf "version:\\t%s\\n" "${SYSBOX_VERSION:-0.7.2}"\n')
    runtime.chmod(0o755)
    for name in ("docker", "sudo"):
        stub = bin_dir / name
        stub.write_text(
            "#!/bin/sh\n"
            f'echo "{name} $*" >> {log}\n'
            'if [ "$1 $2" = "builder prune" ]; then\n'
            "  shift 2\n"
            '  for a in "$@"; do\n'
            '    case "$a" in --keep-storage|--force|--filter|--all|[0-9]*|label=*|until=*) ;;\n'
            '      *) echo "unknown flag: $a" >&2; exit 125;; esac\n'
            "  done\n"
            "fi\n"
            'case "$*" in *"${DOCKER_FAILS:-@none@}"*) exit "${DOCKER_FAIL_CODE:-1}";; esac\n'
            'if [ "$1" = info ]; then\n'
            '  case "$3" in *CgroupDriver*) printf "%s\\n" "${DOCKER_CGROUP_DRIVER:-}";;\n'
            f'    *) printf "%s\\n" "{runtime}";; esac\n'
            'fi\n'
            'if [ "$1 $2" = "image inspect" ]; then test -f "$IMAGES/$3"; exit $?; fi\n'
            'if [ "$1" = build ]; then\n'
            '  while [ "$1" != --tag ]; do shift; done\n'
            '  printf "%s\\n" "${BUILD_CONTENT:-built}" > "$IMAGES/$2"\n'
            'fi\n'
            'if [ "$1" = tag ]; then cp "$IMAGES/$2" "$IMAGES/$3"; fi\n'
            'if [ "$1 $2" = "image rm" ]; then rm "$IMAGES/$3"; fi\n'
            'if [ "$1 $2" = "network create" ]; then for last; do :; done; echo "$last"; fi\n'
            'case "$*" in *" --check-dind-runtime") printf "%s\\n" '
            '"${DOCKER_STORE_DEVICE:-$(stat -c %d "$IMAGES")}";; esac\n'
            "exit 0\n"
        )
        stub.chmod(0o755)
    return bin_dir, log


def run_script(script, stubs, *args, env=None, code=0, **kwargs):
    bin_dir, log = stubs
    environment = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "RUNNER_UP_DOCKER": str(bin_dir / "docker"),
        "XDG_RUNTIME_DIR": str(log.parent),
        "IMAGES": str(log.parent / "images"),
        **(env or {}),
    }
    program = bin_dir / script if script == "runner-up-docker" else MAINTENANCE / script
    done = subprocess.run(
        [str(program), *args],
        env=environment,
        capture_output=True,
        text=True,
        **kwargs,
    )
    assert done.returncode == code, done.stderr
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


@pytest.mark.parametrize(("release", "code"), [
    ("26.04", 125),
    ("24.04", 0),
])
def test_dind_release_policy(stubs, release, code):
    run_script("runner-up-docker", stubs, "check-dind-release", "ubuntu", release, code=code)


@pytest.mark.parametrize(("version", "driver", "code"), [
    ("0.7.1", "systemd", 125),
    ("0.7.2", "cgroupfs", 125),
    ("0.7.2", "systemd", 0),
    ("0.10.0", "systemd", 0),
])
def test_the_shim_requires_a_supported_dind_host_and_does_not_mount_the_cache(
    stubs, tmp_path, version, driver, code
):
    sock = tmp_path / "docker.sock"
    sock.touch()
    env = {
        "RUNNER_UP_DOCKER_SOCK": str(sock),
        "SYSBOX_VERSION": version,
        "RUNNER_UP_SHARED_CACHE": str(tmp_path / "cache"),
        "DOCKER_CGROUP_DRIVER": driver,
    }
    image = "crewship-ci-runner-dind:latest"
    (stubs[0] / "dind-image").write_text(f"{image}\n")
    (tmp_path / "images" / image).touch()
    calls = run_script("runner-up-docker", stubs, "run", "--rm", image, env=env, code=code)
    expected = ['docker info --format {{with index .Runtimes "sysbox-runc"}}{{.Path}}{{end}}']
    if version != "0.7.1":
        expected.append("docker info --format {{.CgroupDriver}}")
    if not code:
        assert calls[:3] == [*expected, f"docker image inspect {image}"]
        assert "--runtime=sysbox-runc" in calls[4]
        assert "--cgroup-parent runnerup.slice" in calls[4]
        assert "--volume" not in calls[4] and " -v " not in calls[4]
        return
    assert calls == expected


def test_each_dind_place_gets_its_own_bridge_and_removes_it_at_teardown(stubs, tmp_path):
    image = "crewship-ci-runner-dind:latest"
    (tmp_path / "images" / image).touch()
    tag = stubs[0] / "dind-image"
    tag.write_text(f"{image}\n")
    socket = tmp_path / "docker.sock"
    socket.touch()
    env = {
        "RUNNER_UP_DOCKER_SOCK": str(socket),
        "DOCKER_CGROUP_DRIVER": "systemd",
        "DOCKER_FAILS": "second-place",
        "DOCKER_FAIL_CODE": "125",
    }
    networks = []
    for place, code in (("first-place", 0), ("second-place", 125)):
        calls = run_script(
            "runner-up-docker", stubs, "run", "--rm", "--name", place, image, env=env, code=code
        )
        create, launch, remove = calls[-3:]
        assert create.startswith("docker network create --driver bridge ")
        network = create.split()[-1]
        assert launch.split()[launch.split().index("--network") + 1] == network
        assert remove == f"docker network rm {network}"
        networks.append(network)
    assert networks[0] != networks[1]


@pytest.mark.parametrize(("dind", "code"), [(False, 0), (True, 0), (True, 125)])
def test_coordinator_start_requires_the_daemon_only_for_local_dind_places(stubs, tmp_path, dind, code):
    bin_dir, _ = stubs
    base = "crewship-ci-runner:latest"
    derived = "crewship-ci-runner-dind:latest"
    (tmp_path / "images" / base).touch()
    (bin_dir / "dind-image").write_text(f"{derived}\n")
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "docker").symlink_to(bin_dir / "runner-up-docker")
    (shim / "dind-image").symlink_to(bin_dir / "dind-image")
    sock = tmp_path / "docker.sock"
    sock.touch()
    recipe = tmp_path / "Dockerfile"
    recipe.write_text("FROM scratch\n")
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"machines": [
        {"name": "local", "places": [{"provider": "docker", "image": derived if dind else base}]},
        {"name": "remote", "places": [{"provider": "docker", "image": derived}]},
    ]}))
    env = {
        "PATH": f"{shim}:{bin_dir}:/usr/bin:/bin",
        "RUNNER_UP_DOCKER_SOCK": str(sock),
        "RUNNER_UP_GUARD_PATH": str(tmp_path),
        "RUNNER_UP_DOCKERFILE": str(recipe),
        "RUNNER_UP_DIND_DOCKERFILE": str(recipe),
        "DOCKER_CGROUP_DRIVER": "systemd",
        "DOCKER_FAILS": "--check-dind-runtime" if code else "@none@",
        "DOCKER_FAIL_CODE": "125",
    }
    calls = run_script(
        "runner-up-maintain", stubs, "start", str(config_file), env=env, code=code
    )
    assert (tmp_path / "images" / derived).exists() == (dind and code == 0)
    if dind:
        (probe,) = [call for call in calls if "--entrypoint /home/runner/run.sh" in call]
        assert probe.endswith(f"{derived}-candidate --check-dind-runtime")
        assert any(call.startswith("docker network rm ") for call in calls)
    else:
        assert calls == [f"docker image inspect {base}"]


def test_the_shim_mounts_the_shared_build_cache_when_it_is_set(stubs, tmp_path):
    sock, cache = tmp_path / "docker.sock", tmp_path / "shared"
    sock.touch()
    env = {
        "RUNNER_UP_DOCKER_SOCK": str(sock),
        "RUNNER_UP_SHARED_CACHE": str(cache),
        "RUNNER_UP_CACHE_MAX_GB": "20",
    }
    (call,) = run_script("runner-up-docker", stubs, "run", "img", env=env)
    assert f"-v {cache}/sccache:/sccache" in call
    assert f"-v {cache}/cargo-lock:/home/runner/.cargo/.package-cache " in call
    assert "-e SCCACHE_CACHE_SIZE=20G" in call and call.endswith(" img")
    assert f"-v {cache}/pnpm-store:/home/runner/.cache/pnpm-store" in call
    assert (cache / "cargo-registry").is_dir()


def test_the_shim_limits_cargo_jobs_to_the_job_cpus(stubs, tmp_path):
    sock = tmp_path / "docker.sock"
    sock.touch()
    env = {"RUNNER_UP_DOCKER_SOCK": str(sock), "RUNNER_UP_JOB_CPUS": "4"}
    (call,) = run_script("runner-up-docker", stubs, "run", "--rm", "img", env=env)
    assert call == (
        "docker run --cgroup-parent runnerup.slice --pids-limit 8192 -e MOLD_JOBS=1 -e CARGO_BUILD_JOBS=4 --rm img"
    )


def test_the_service_passes_the_job_cpus_to_the_shim(home):
    apply(home, runner(home))
    service = unit_sections(units(home) / "runner-up@.service")["Service"]
    assert "RUNNER_UP_JOB_CPUS=4" in service["Environment"]


def test_the_shim_uses_sudo_when_the_account_cannot_write_the_docker_socket(stubs, tmp_path):
    env = {"RUNNER_UP_DOCKER_SOCK": str(tmp_path / "missing.sock")}
    calls = run_script("runner-up-docker", stubs, "run", "img", env=env)
    assert calls[0].startswith("sudo -n ")
    assert " run --cgroup-parent runnerup.slice " in calls[0]


def test_clean_removes_stopped_place_containers_and_layers_and_caps_the_build_cache(stubs):
    calls = run_script("runner-up-maintain", stubs, "clean", env={"RUNNER_UP_DISK_MAX_GB": "7"})
    assert calls == [
        "docker container prune --force --filter label=runner-up.place --filter until=1h",
        "docker network prune --force --filter label=runner-up.dind --filter until=1h",
        "docker image prune --force",
        "docker builder prune --force --keep-storage 7GB",
    ]


def test_clean_runs_every_step_when_one_fails_and_fits_the_unit_deadline(stubs, home):
    bin_dir, log = stubs
    timeout = bin_dir / "timeout"
    timeout.write_text(f'#!/bin/sh\necho "timeout $1 $2" >> {log}\nshift 2\nexec "$@"\n')
    timeout.chmod(0o755)
    env = {"DOCKER_FAILS": "container prune"}
    calls = run_script("runner-up-maintain", stubs, "clean", env=env, code=1)
    apply(home, runner(home))
    service = unit_sections(units(home) / "runner-up-clean.service")["Service"]
    (deadline,) = service["TimeoutStartSec"]
    limits = [call.split()[1:] for call in calls if call.startswith("timeout ")]
    assert len(limits) == 4
    budget = sum(
        int(kill.removeprefix("--kill-after=").removesuffix("s")) + int(limit)
        for kill, limit in limits
    )
    assert budget < int(deadline)
    assert [c.split()[1] for c in calls if c.startswith("docker ")] == [
        "container", "network", "image", "builder"
    ]


def guard(stubs, tmp_path, used, *, paused="", active=True, failed=False, env=None):
    """Run `guard` with a stub `df` that reports `used` percent and a `systemctl` that logs."""
    bin_dir, log = stubs
    (bin_dir / "df").write_text(f'#!/bin/sh\necho "Use%"\necho " {used}%"\n')
    (bin_dir / "systemctl").write_text(
        f'#!/bin/sh\necho "systemctl $*" >> {log}\n[ "$2" = show ] && {{ for a; do :; done; echo "$a" | tr -dc 0-9; exit 0; }}\n'
        + (
            'case "$2 $3" in "is-active --quiet") ;; "is-active "*) echo active;; esac\n'
            if active else
            '[ "$2" != is-active ] || { case " ${ACTIVE_UNITS:-} " in *" $4 "*) exit 0;; esac; exit 3; }\n'
        )
        + ("" if failed else '[ "$2" = is-failed ] && exit 1\n')
        + "exit 0\n"
    )
    for name in ("df", "systemctl"):
        (bin_dir / name).chmod(0o755)
    state = tmp_path / "paused"
    if paused:
        state.write_text(paused)
    env = {"RUNNER_UP_INSTANCES": "a-b c-d", "RUNNER_UP_GUARD_STATE": str(state), **(env or {})}
    calls = run_script("runner-up-maintain", stubs, "guard", env=env)
    return [c for c in calls if c.startswith("systemctl")], state


def test_guard_prunes_stopped_place_containers_without_the_age_filter_and_never_forces_running_ones(
    stubs, tmp_path
):
    guard(stubs, tmp_path, 10)
    calls = [c for c in stubs[1].read_text().splitlines() if c.startswith("docker")]
    assert calls[0] == "docker container prune --force --filter label=runner-up.place"
    assert not any(c.startswith("docker rm") or " stop " in c for c in calls)


def test_guard_pauses_even_when_the_prune_hangs(stubs, tmp_path):
    docker = stubs[0] / "docker"
    docker.write_text("#!/bin/sh\nsleep 30\n")
    started = time.monotonic()
    calls, state = guard(stubs, tmp_path, 95, env={"RUNNER_UP_GUARD_PRUNE_TIMEOUT": "1"})
    assert "systemctl --user stop runner-up@a-b.service" in calls
    assert state.read_text() == "a-b\nc-d\n"
    assert time.monotonic() - started < 10


def test_guard_stops_the_coordinators_at_88_percent_and_remembers_them(stubs, tmp_path):
    calls, state = guard(stubs, tmp_path, 88)
    assert calls == [
        "systemctl --user is-active runner-up@a-b.service",
        "systemctl --user stop runner-up@a-b.service",
        "systemctl --user is-active runner-up@c-d.service",
        "systemctl --user stop runner-up@c-d.service",
    ]
    assert state.read_text() == "a-b\nc-d\n"


def test_guard_does_not_stop_at_87_percent_or_remember_a_unit_that_was_not_running(stubs, tmp_path):
    assert not any(" stop " in c for c in guard(stubs, tmp_path, 87)[0])
    calls, state = guard(stubs, tmp_path, 95, active=False)
    assert not any(" stop " in c for c in calls) and not state.exists()


def test_guard_starts_only_the_coordinators_it_stopped_below_85_percent(stubs, tmp_path):
    calls, state = guard(stubs, tmp_path, 84, paused="a-b\nc-d\n", active=False)
    assert [c for c in calls if " start " in c] == [
        "systemctl --user --no-block start runner-up@a-b.service runner-up@c-d.service",
    ]
    assert state.read_text() == "a-b\nc-d\n"
    stubs[1].write_text("")
    calls, state = guard(
        stubs, tmp_path, 84, active=False, env={"ACTIVE_UNITS": "runner-up@c-d.service"}
    )
    assert [c for c in calls if " start " in c] == [
        "systemctl --user --no-block start runner-up@a-b.service",
    ]
    assert state.read_text() == "a-b\n"


def test_guard_keeps_the_pause_between_85_and_87_percent(stubs, tmp_path):
    calls, state = guard(stubs, tmp_path, 86, paused="a-b\n")
    assert not any(" start " in c or " stop " in c for c in calls) and state.exists()


def io_guard(
    stubs, tmp_path, avg60, *, now, used=10, io=None, disk_paused="", calm=None, active_units=""
):
    """Run `guard` at time `now` with a stub pressure file; state lives in tmp_path between runs."""
    pressure = tmp_path / "io"
    pressure.write_text(
        f"some avg10=0.00 avg60=0.00 avg300=0.00 total=1\nfull avg10=1.00 avg60={avg60} avg300=0.00 total=1\n"
    )
    io_state = tmp_path / "io.paused"
    if io is None:
        io = "runner-up@a-b.service\nrunner-up@c-d.service\n"
    if io:
        io_state.write_text(io)
    if calm is not None:
        (tmp_path / "io.paused.calm").write_text(str(calm))
    env = {
        "RUNNER_UP_PRESSURE_FILE": str(pressure),
        "RUNNER_UP_IO_STATE": str(io_state),
        "RUNNER_UP_NOW": str(now),
        "ACTIVE_UNITS": active_units,
    }
    stubs[1].write_text("")
    calls, _ = guard(stubs, tmp_path, used, paused=disk_paused, active=False, env=env)
    left = io_state.read_text().split() if io_state.exists() else []
    return [c for c in calls if " start " in c], left


def test_io_resume_waits_for_the_two_minute_window_then_starts_one_unit_per_run(stubs, tmp_path):
    a, b = "runner-up@a-b.service", "runner-up@c-d.service"
    assert io_guard(stubs, tmp_path, "12.50", now=1000) == ([], [a, b])
    assert io_guard(stubs, tmp_path, "39.99", now=1119, io="")[0] == []
    calls, left = io_guard(stubs, tmp_path, "5.00", now=1120, io="")
    assert calls == [f"systemctl --user --no-block start {a}"] and left == [b, a]
    calls, left = io_guard(stubs, tmp_path, "5.00", now=1240, io="")
    assert calls == [f"systemctl --user --no-block start {b}"] and left == [a, b]
    active = f"{a} {b}"
    assert io_guard(stubs, tmp_path, "5.00", now=1360, io="", active_units=active) == ([], [b])
    assert io_guard(stubs, tmp_path, "5.00", now=1480, io="", active_units=active) == ([], [])
    assert not (tmp_path / "io.paused.calm").exists()


def test_an_io_spike_resets_the_calm_window(stubs, tmp_path):
    io_guard(stubs, tmp_path, "5.00", now=1000)
    assert io_guard(stubs, tmp_path, "40.00", now=1300, io="")[0] == []
    assert io_guard(stubs, tmp_path, "5.00", now=1700, io="")[0] == []
    assert io_guard(stubs, tmp_path, "5.00", now=1819, io="")[0] == []
    assert io_guard(stubs, tmp_path, "5.00", now=1820, io="")[0] == [
        "systemctl --user --no-block start runner-up@a-b.service"
    ]


def test_io_resume_leaves_disk_paused_units_to_the_disk_rule(stubs, tmp_path):
    calls, left = io_guard(stubs, tmp_path, "1.00", now=5000, calm=0, used=86, disk_paused="a-b\n")
    assert calls == [] and left == ["runner-up@a-b.service", "runner-up@c-d.service"]


def test_disk_resume_leaves_io_paused_units_until_io_recovers(stubs, tmp_path):
    unit = "runner-up@a-b.service"
    calls, left = io_guard(
        stubs, tmp_path, "60.00", now=1000, io=f"{unit}\n", disk_paused="a-b\nc-d\n"
    )
    assert calls == ["systemctl --user --no-block start runner-up@c-d.service"]
    assert left == [unit]
    assert (tmp_path / "paused").read_text() == "c-d\n"
    calls, _ = io_guard(
        stubs, tmp_path, "5.00", now=1100, io="", active_units="runner-up@c-d.service"
    )
    assert calls == []
    assert io_guard(stubs, tmp_path, "5.00", now=1220, io="") == (
        [f"systemctl --user --no-block start {unit}"], [unit]
    )


def test_guard_discards_removed_coordinators_from_both_pause_records(stubs, tmp_path):
    unit = "runner-up@a-b.service"
    calls, left = io_guard(
        stubs,
        tmp_path,
        "5.00",
        now=1200,
        calm=1000,
        io=f"runner-up@removed.service\n{unit}\n",
        disk_paused="removed\n",
    )
    assert calls == [f"systemctl --user --no-block start {unit}"]
    assert left == [unit]
    assert not (tmp_path / "paused").exists()


def heal(stubs, tmp_path, used, *, disk_paused="", io_paused="", failed=True, env=None):
    """Run `guard` with both coordinators down and return the `start` calls."""
    (tmp_path / "io.paused").write_text(io_paused)
    stubs[1].write_text("")
    env = {
        "RUNNER_UP_IO_STATE": str(tmp_path / "io.paused"),
        "RUNNER_UP_PRESSURE_FILE": str(tmp_path / "none"),
        "RUNNER_UP_NOW": "1000",
        **(env or {}),
    }
    calls, _ = guard(
        stubs, tmp_path, used, paused=disk_paused, active=False, failed=failed, env=env
    )
    return [c for c in calls if " start " in c]


def test_guard_restarts_a_failed_coordinator_held_by_no_pause(stubs, tmp_path):
    assert heal(stubs, tmp_path, 10) == [
        "systemctl --user --no-block start runner-up@a-b.service runner-up@c-d.service",
    ]


def test_guard_leaves_a_coordinator_stopped_by_hand_alone(stubs, tmp_path):
    assert heal(stubs, tmp_path, 10, failed=False) == []


def test_guard_leaves_a_coordinator_alone_while_a_pause_holds_it(stubs, tmp_path):
    assert heal(stubs, tmp_path, 95) == []
    assert heal(stubs, tmp_path, 86, disk_paused="a-b\n") == [
        "systemctl --user --no-block start runner-up@c-d.service"
    ]
    (tmp_path / "paused").unlink()
    assert heal(stubs, tmp_path, 10, io_paused="runner-up@a-b.service\n") == [
        "systemctl --user --no-block start runner-up@c-d.service"
    ]


def test_guard_keeps_a_heavy_coordinator_down_while_the_io_pressure_is_high(stubs, tmp_path):
    pressure = tmp_path / "hot"
    pressure.write_text("full avg10=1.00 avg60=64.00 avg300=0.00 total=1\n")
    env = {"RUNNER_UP_PRESSURE_FILE": str(pressure), "RUNNER_UP_IO_HEAVY": "a-b"}
    assert heal(stubs, tmp_path, 10, env=env) == [
        "systemctl --user --no-block start runner-up@c-d.service"
    ]


def io_hot_guard(stubs, tmp_path, avg60, now, heavy="h1 h2 h3"):
    pressure = tmp_path / "io"
    pressure.write_text(f"full avg10=1.00 avg60={avg60} avg300=0.00 total=1\n")
    env = {
        "RUNNER_UP_PRESSURE_FILE": str(pressure),
        "RUNNER_UP_IO_STATE": str(tmp_path / "io.paused"),
        "RUNNER_UP_NOW": str(now),
        "RUNNER_UP_IO_HEAVY": heavy,
        "RUNNER_UP_INSTANCES": heavy,
    }
    stubs[1].write_text("")
    calls, _ = guard(stubs, tmp_path, 10, env=env)
    return [c for c in calls if " stop " in c]


def test_io_pause_stops_the_newest_heavy_unit_after_three_minutes_above_the_level(stubs, tmp_path):
    assert io_hot_guard(stubs, tmp_path, "64.0", 1000) == []
    assert io_hot_guard(stubs, tmp_path, "64.0", 1179) == []
    assert io_hot_guard(stubs, tmp_path, "64.0", 1180) == [
        "systemctl --user stop runner-up@h3.service"
    ]
    assert (tmp_path / "io.paused").read_text() == "runner-up@h3.service\n"
    # one unit per window: the next one needs three more minutes (the stub keeps h3 active, so it leaves the list)
    assert io_hot_guard(stubs, tmp_path, "64.0", 1200) == []
    assert io_hot_guard(stubs, tmp_path, "64.0", 1380, heavy="h1 h2") == [
        "systemctl --user stop runner-up@h2.service"
    ]


def test_io_pause_does_not_flap_on_a_short_spike_or_pause_unlisted_units(stubs, tmp_path):
    io_hot_guard(stubs, tmp_path, "64.0", 1000)
    assert io_hot_guard(stubs, tmp_path, "40.0", 1170) == []
    assert io_hot_guard(stubs, tmp_path, "64.0", 1180) == []
    assert io_hot_guard(stubs, tmp_path, "64.0", 1359) == []
    assert io_hot_guard(stubs, tmp_path, "64.0", 1360, heavy="") == []


def test_io_pause_stops_and_records_units_once(stubs, tmp_path):
    bin_dir, log = stubs
    (bin_dir / "systemctl").write_text(
        f'#!/bin/sh\necho "systemctl $*" >> {log}\n[ "$3" = bad ] && exit 1\nexit 0\n'
    )
    (bin_dir / "systemctl").chmod(0o755)
    state = tmp_path / "io.paused"
    env = {"RUNNER_UP_IO_STATE": str(state)}
    run_script("runner-up-maintain", stubs, "io-pause", "a", "bad", "a", "b", env=env)
    assert state.read_text() == "a\nb\n"


def test_the_guard_timer_is_enabled_and_sets_the_levels(home):
    apply(home, runner(home))
    service = unit_sections(units(home) / "runner-up-guard.service")["Service"]
    assert "RUNNER_UP_PAUSE_PCT=88" in service["Environment"]
    assert "RUNNER_UP_RESUME_PCT=85" in service["Environment"]
    assert (units(home) / "timers.target.wants/runner-up-guard.timer").is_symlink()


def test_the_guard_unit_quotes_the_instance_list_so_systemd_keeps_every_name(home):
    apply(home, runner(home))
    service = unit_sections(units(home) / "runner-up-guard.service")["Service"]
    (value,) = [e for e in service["Environment"] if "RUNNER_UP_INSTANCES" in e]
    prefix = '"RUNNER_UP_INSTANCES='
    assert value.startswith(prefix) and value.endswith('"')
    assert sorted(value[len(prefix) : -1].split()) == instances(home)


def test_the_image_is_built_with_the_build_output_removed_and_old_layers_pruned(stubs, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM scratch\n")
    env = {"RUNNER_UP_DOCKERFILE": str(dockerfile)}
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
    (tmp_path / "images/crewship-ci-runner:latest").touch()
    env = {"RUNNER_UP_DOCKERFILE": str(dockerfile)}
    calls = run_script("runner-up-maintain", stubs, "image", "--ensure", env=env)
    assert calls == ["docker image inspect crewship-ci-runner:latest"]
    calls = run_script("runner-up-maintain", stubs, "image", env=env)
    assert any(c.startswith("docker build") for c in calls[1:])


def test_dind_image_maintenance_uses_the_base_without_rebuilding_it(stubs, tmp_path):
    base = "crewship-ci-runner:latest"
    derived = "crewship-ci-runner-dind:latest"
    images = tmp_path / "images"
    (images / base).touch()
    bin_dir, _ = stubs
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "docker").symlink_to(bin_dir / "runner-up-docker")
    (shim / "dind-image").write_text(f"{derived}\n")
    sock = tmp_path / "docker.sock"
    sock.touch()
    recipe = tmp_path / "Dockerfile"
    recipe.write_text("FROM scratch\n")
    guard_path = tmp_path / "guard"
    guard_path.symlink_to("/proc", target_is_directory=True)
    env = {
        "PATH": f"{shim}:{bin_dir}:/usr/bin:/bin",
        "RUNNER_UP_DOCKER_SOCK": str(sock),
        "DOCKER_CGROUP_DRIVER": "systemd",
        "RUNNER_UP_GUARD_PATH": str(guard_path),
        "DOCKER_STORE_DEVICE": str(os.stat("/proc").st_dev),
        "RUNNER_UP_DOCKERFILE": str(recipe),
        "RUNNER_UP_DIND_DOCKERFILE": str(recipe),
        "RUNNER_UP_REFRESH_BASE": "0",
    }
    calls = run_script("runner-up-maintain", stubs, "image", "--ensure", env=env)
    assert sorted(tag.name for tag in images.iterdir()) == [derived, base]
    (build,) = [call for call in calls if call.startswith("docker build")]
    assert f"--build-arg BASE_IMAGE={base}" in build
    assert f"--tag {derived}-candidate" in build
    calls = run_script("runner-up-maintain", stubs, "image", "--ensure", env=env)
    assert sum(call.startswith("docker build") for call in calls) == 1
    failed = {**env, "BUILD_CONTENT": "bad", "DOCKER_FAILS": "--check-dind-runtime"}
    run_script("runner-up-maintain", stubs, "image", env=failed, code=1)
    assert (images / derived).read_text() == "built\n"
    assert sorted(tag.name for tag in images.iterdir()) == [derived, base]
    run_script(
        "runner-up-maintain",
        stubs,
        "image",
        env={
            **env, "BUILD_CONTENT": "wrong disk", "DOCKER_STORE_DEVICE": str(guard_path.lstat().st_dev)
        },
        code=125,
    )
    assert (images / derived).read_text() == "built\n"
    assert sorted(tag.name for tag in images.iterdir()) == [derived, base]
    calls = run_script(
        "runner-up-maintain", stubs, "image", env={**env, "BUILD_CONTENT": "fresh"}
    )
    assert (images / derived).read_text() == "fresh\n"
    assert [call.split(" --tag ")[1].split()[0] for call in calls if " --tag " in call] == [
        f"{derived}-candidate",
        f"{derived}-candidate",
        f"{derived}-candidate",
        f"{derived}-candidate",
    ]


def gate(tmp_path, *args, env=None, timeout=20, stdin=None):
    pressure = tmp_path / "pressure"
    if not pressure.exists():
        pressure.write_text(
            "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10=0.00 avg60=1.00 avg300=0.00 total=0\n"
        )
    environment = {
        "PATH": "/usr/bin:/bin",
        "BUILD_GATE_DIR": str(tmp_path / "gate"),
        "BUILD_GATE_SLOTS_FILE": str(tmp_path / "slots"),
        "BUILD_GATE_PRESSURE_FILE": str(pressure),
        "BUILD_GATE_DISK_PATH": str(tmp_path),
        "BUILD_GATE_DISK_PCT": "100",
        "BUILD_GATE_POLL": "1",
        **(env or {}),
    }
    return subprocess.Popen(
        [str(MAINTENANCE / "build-gate"), *args],
        env=environment,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_build_gate_runs_the_command_and_passes_its_status(tmp_path):
    ok = gate(tmp_path, "sh", "-c", "echo $BUILD_GATE_HELD")
    assert ok.communicate(timeout=20)[0] == "1\n"
    bad = gate(tmp_path, "sh", "-c", "exit 7")
    bad.communicate(timeout=20)
    assert bad.returncode == 7


def test_build_gate_hands_its_standard_input_to_the_command(tmp_path):
    # runner-up sends the job's JIT config on stdin of `docker run -i`; a lost stdin ended every runner at once.
    piped = gate(tmp_path, "sh", "-c", "read -r x; echo got=$x", stdin=subprocess.PIPE)
    assert piped.communicate("config\n", timeout=20)[0] == "got=config\n"


def test_build_gate_waits_while_io_pressure_is_high_and_then_runs(tmp_path):
    pressure = tmp_path / "pressure"
    pressure.write_text("full avg10=0.00 avg60=56.92 avg300=0.00 total=0\n")
    job = gate(tmp_path, "echo", "ran")
    time.sleep(2.5)
    assert job.poll() is None
    pressure.write_text("full avg10=0.00 avg60=10.00 avg300=0.00 total=0\n")
    assert job.communicate(timeout=20)[0] == "ran\n"


def test_build_gate_waits_while_the_disk_is_above_the_limit(tmp_path):
    job = gate(tmp_path, "echo", "ran", env={"BUILD_GATE_DISK_PCT": "0"})
    time.sleep(2.5)
    assert job.poll() is None
    job.kill()
    job.communicate()


def test_build_gate_slot_count_comes_from_the_shared_file(tmp_path):
    (tmp_path / "slots").write_text("1\n")
    first = gate(tmp_path, "sleep", "4")
    time.sleep(1)
    second = gate(tmp_path, "echo", "second")
    time.sleep(1.5)
    assert second.poll() is None
    assert second.communicate(timeout=20)[0] == "second\n"
    first.communicate()


def test_build_gate_default_is_four_slots_when_no_count_is_installed(tmp_path):
    holders = [gate(tmp_path, "sleep", "5") for _ in range(4)]
    time.sleep(1.5)
    fifth = gate(tmp_path, "echo", "fifth")
    time.sleep(1.5)
    assert fifth.poll() is None
    fifth.kill()
    fifth.communicate()
    for holder in holders:
        holder.kill()
        holder.communicate()


def test_build_gate_exits_zero_when_a_signalled_command_still_exits_zero(tmp_path):
    job = gate(tmp_path, "sh", "-c", "trap 'exit 0' TERM; while :; do sleep 0.2; done")
    time.sleep(1.5)
    job.terminate()
    job.communicate(timeout=20)
    assert job.returncode == 0


def cargo_shim(tmp_path, *args, io="99.00", wrap=False):
    bindir = tmp_path / "bin"
    realdir = tmp_path / "real"
    bindir.mkdir(exist_ok=True)
    realdir.mkdir(exist_ok=True)
    for name in ("cargo-gate", "build-gate"):
        target = bindir / ("cargo" if name == "cargo-gate" else name)
        if not target.exists():
            target.write_text((MAINTENANCE / name).read_text())
            target.chmod(0o755)
    real = realdir / "cargo"
    real.write_text('#!/bin/sh\necho "real:$BUILD_GATE_HELD:$*"\n')
    real.chmod(0o755)
    if wrap:
        (bindir / "cargo.wrap").write_text('#!/bin/sh\necho "wrap:$BUILD_GATE_HELD:$*"\n')
        (bindir / "cargo.wrap").chmod(0o755)
    pressure = tmp_path / "pressure"
    pressure.write_text(f"full avg10=0.00 avg60={io} avg300=0.00 total=0\n")
    environment = {
        "PATH": f"{bindir}:{realdir}:/usr/bin:/bin",
        "BUILD_GATE_DIR": str(tmp_path / "gate"),
        "BUILD_GATE_SLOTS_FILE": str(tmp_path / "slots"),
        "BUILD_GATE_DISK_PATH": str(tmp_path),
        "BUILD_GATE_DISK_PCT": "100",
        "BUILD_GATE_PRESSURE_FILE": str(pressure),
        "BUILD_GATE_POLL": "1",
    }
    return subprocess.Popen(
        [str(bindir / "cargo"), *args], env=environment, stdout=subprocess.PIPE, text=True
    )


def test_the_cargo_shim_holds_heavy_subcommands_at_the_gate_and_runs_the_real_cargo(tmp_path):
    heavy = cargo_shim(tmp_path, "build", "--release")
    time.sleep(2.5)
    assert heavy.poll() is None
    heavy.kill()
    heavy.communicate()
    light = cargo_shim(tmp_path, "--version")
    assert light.communicate(timeout=20)[0] == "real::--version\n"


def test_the_cargo_shim_runs_a_heavy_subcommand_under_the_gate_when_the_host_is_quiet(tmp_path):
    job = cargo_shim(tmp_path, "+nightly", "test", io="1.00")
    assert job.communicate(timeout=20)[0] == "real:1:+nightly test\n"


def test_the_cargo_shim_chains_the_gate_to_cargo_wrap_when_it_exists(tmp_path):
    heavy = cargo_shim(tmp_path, "build", io="1.00", wrap=True)
    assert heavy.communicate(timeout=20)[0] == "wrap:1:build\n"
    light = cargo_shim(tmp_path, "--version", wrap=True)
    assert light.communicate(timeout=20)[0] == "wrap::--version\n"


def test_build_gate_skips_when_off_or_already_held(tmp_path):
    pressure = tmp_path / "pressure"
    pressure.write_text("full avg10=0.00 avg60=99.00 avg300=0.00 total=0\n")
    for env in ({"BUILD_GATE": "off"}, {"BUILD_GATE_HELD": "1"}):
        assert gate(tmp_path, "echo", "ran", env=env).communicate(timeout=20)[0] == "ran\n"


def test_the_shim_starts_jobs_through_the_build_gate_when_it_is_set(stubs, tmp_path):
    sock = tmp_path / "docker.sock"
    sock.touch()
    gate_stub = tmp_path / "gate-stub"
    gate_stub.write_text(f'#!/bin/sh\necho "gate $*" >> {stubs[1]}\nexec "$@"\n')
    gate_stub.chmod(0o755)
    env = {"RUNNER_UP_DOCKER_SOCK": str(sock), "RUNNER_UP_BUILD_GATE": str(gate_stub)}
    calls = run_script("runner-up-docker", stubs, "run", "img", env=env)
    assert calls[0].startswith("gate ") and calls[0].endswith(
        "docker run --cgroup-parent runnerup.slice --pids-limit 8192 img"
    )
    assert calls[1].startswith("docker run")


def test_the_service_sets_the_build_gate_only_when_asked(home):
    apply(home, runner(home))
    env = unit_sections(units(home) / "runner-up@.service")["Service"]["Environment"]
    assert not any(v.startswith("RUNNER_UP_BUILD_GATE") for v in env)
    apply(home, runner(home, build_gate=True))
    env = unit_sections(units(home) / "runner-up@.service")["Service"]["Environment"]
    assert f"RUNNER_UP_BUILD_GATE={home}/.local/bin/build-gate" in env
